"""Admin-only dashboards: stats, users, messages, emergencies, schedules,
delivery health. All endpoints require role='admin' via get_current_admin.

Kept read-only. Mutating admin actions (coupons, sanity suite, care admin)
live in their own routers: routes/coupon_admin.py, routes/sanity.py, routes/care.py.
"""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from auth import get_current_admin, serialize
from database import get_pool
from services.delivery_stats import delivery_funnel
from whatsapp import whatsapp_enabled

router = APIRouter(prefix='/api/admin', tags=['Admin'])


@router.get('/stats')
async def admin_stats(admin: dict = Depends(get_current_admin)):
    async with get_pool().acquire() as conn:
        total_users = await conn.fetchval("select count(*) from users where role = 'user' and deleted_at is null")
        completed = await conn.fetchval(
            "select count(*) from users where role = 'user' and onboarding_complete = true and deleted_at is null"
        )
        new_today = await conn.fetchval(
            "select count(*) from users where role = 'user' and deleted_at is null and created_at >= date_trunc('day', now())"
        )
        new_7d = await conn.fetchval(
            "select count(*) from users where role = 'user' and deleted_at is null and created_at >= now() - interval '7 days'"
        )
        activated = await conn.fetchval("select count(*) from activation_state where whatsapp_activated = true")
        parents = await conn.fetchval("select count(*) from parents where deleted_at is null")
        schedules = await conn.fetchval("select count(*) from schedules where deleted_at is null and active = true")
        messages = await conn.fetchval("select count(*) from message_logs")
        emergencies = await conn.fetchval("select count(*) from emergency_events where status = 'open'")
        paying = await conn.fetchval("select count(*) from payment_state where status in ('active', 'paid', 'trialing')")
        plan_rows = await conn.fetch("select coalesce(plan, 'none') as plan, count(*) as n from payment_state group by plan")
        plan_breakdown = {r["plan"]: r["n"] for r in plan_rows}
        funnel = await delivery_funnel(conn)
    return {
        "total_users": total_users, "completed_onboarding": completed,
        "new_today": new_today, "new_7d": new_7d,
        "activated": activated, "parents": parents, "active_schedules": schedules,
        "messages_delivered": funnel["delivered"], "messages_total": messages,
        "open_emergencies": emergencies,
        "paying_users": paying, "plan_breakdown": plan_breakdown,
        "delivery_funnel": funnel,
        "whatsapp_enabled": whatsapp_enabled(),
    }


@router.get('/users')
async def admin_users(admin: dict = Depends(get_current_admin), skip: int = 0, limit: int = 50):
    limit = max(1, min(limit, 100))
    skip = max(0, skip)
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("select count(*) from users where role = 'user'")
        users = await conn.fetch(
            "select * from users where role = 'user' order by created_at desc offset $1 limit $2",
            skip, limit,
        )
        out = []
        for u in users:
            act = await conn.fetchrow("select * from activation_state where user_id = $1", u["id"])
            pcount = await conn.fetchval(
                "select count(*) from parents where user_id = $1 and deleted_at is null", u["id"],
            )
            scount = await conn.fetchval(
                "select count(*) from schedules where user_id = $1 and deleted_at is null", u["id"],
            )
            s = serialize(u)
            s["activated"] = bool(act and act["whatsapp_activated"])
            s["parents_count"] = pcount
            s["schedules_count"] = scount
            out.append(s)
    return {"total": total, "skip": skip, "limit": limit, "items": out}


@router.get('/messages')
async def admin_messages(admin: dict = Depends(get_current_admin), skip: int = 0, limit: int = 100):
    limit = max(1, min(limit, 200))
    skip = max(0, skip)
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("select count(*) from message_logs")
        docs = await conn.fetch(
            "select * from message_logs order by created_at desc offset $1 limit $2", skip, limit,
        )
    return {"total": total, "skip": skip, "limit": limit, "items": [serialize(d) for d in docs]}


@router.get('/emergencies')
async def admin_emergencies(admin: dict = Depends(get_current_admin)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch("select * from emergency_events order by created_at desc limit 200")
    return [serialize(d) for d in docs]


@router.get('/schedules')
async def admin_schedules(admin: dict = Depends(get_current_admin), skip: int = 0, limit: int = 50):
    limit = max(1, min(limit, 100))
    skip = max(0, skip)
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("select count(*) from schedules where deleted_at is null")
        docs = await conn.fetch(
            "select * from schedules where deleted_at is null order by created_at desc offset $1 limit $2",
            skip, limit,
        )
        parent_ids = list({d["parent_id"] for d in docs})
        user_ids = list({d["user_id"] for d in docs})
        parent_rows = await conn.fetch("select * from parents where id = any($1::uuid[])", parent_ids) if parent_ids else []
        user_rows = await conn.fetch("select * from users where id = any($1::uuid[])", user_ids) if user_ids else []
    parents_map = {str(p["id"]): p["name"] or "Unknown" for p in parent_rows}
    users_map = {str(u["id"]): u["name"] or "Unknown" for u in user_rows}
    out = []
    for d in docs:
        s = serialize(d)
        messages = d["messages"]
        messages = json.loads(messages) if isinstance(messages, str) else (messages or [])
        s["parent_name"] = parents_map.get(str(d["parent_id"]), "Unknown")
        s["user_name"] = users_map.get(str(d["user_id"]), "Unknown")
        s["message_count"] = len(messages)
        out.append(s)
    return {"total": total, "skip": skip, "limit": limit, "items": out}


@router.get('/delivery-health')
async def admin_delivery_health(
    admin: dict = Depends(get_current_admin),
    days: int = Query(7, ge=1, le=90),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_pool().acquire() as conn:
        overall_row = await conn.fetchrow(
            """
            select
                count(*) filter (where status in ('sent','simulated') or delivery_status is not null) as total,
                count(*) filter (where delivery_status in ('delivered','read'))                        as delivered,
                count(*) filter (where delivery_status = 'read')                                       as read,
                count(*) filter (where delivery_status = 'failed' or status = 'failed')                as failed
            from message_logs
            where created_at >= $1
            """,
            since,
        )
        total = overall_row["total"] or 0
        delivered = overall_row["delivered"] or 0
        read = overall_row["read"] or 0
        failed = overall_row["failed"] or 0
        pending = max(total - delivered - failed, 0)

        daily_rows = await conn.fetch(
            """
            select
                day_key,
                count(*) filter (where delivery_status in ('delivered','read'))         as delivered,
                count(*) filter (where delivery_status = 'read')                        as read,
                count(*) filter (where delivery_status = 'failed' or status = 'failed') as failed
            from message_logs
            where created_at >= $1 and day_key is not null
            group by day_key
            order by day_key desc
            limit $2
            """,
            since, days,
        )

        stuck_rows = await conn.fetch(
            """
            select ml.id, ml.category, ml.created_at, ml.sid, p.name as parent_name
            from message_logs ml
            left join parents p on p.id = ml.parent_id
            where ml.created_at <= now() - interval '2 hours'
              and ml.created_at >= $1
              and (ml.status in ('sent', 'simulated') or ml.delivery_status = 'sent' or ml.delivery_status is null)
              and ml.delivery_status is distinct from 'delivered'
              and ml.delivery_status is distinct from 'read'
              and ml.delivery_status is distinct from 'failed'
              and ml.status is distinct from 'failed'
            order by ml.created_at asc
            limit 50
            """,
            since,
        )

        # Per-parent FAILING sends: a scheduled slot (parent + category + day)
        # that has failed attempts and has NOT yet landed a successful send.
        # This is the "silent drop" signal — a parent currently getting
        # nothing while the scheduler keeps retrying with backoff.
        failing_rows = await conn.fetch(
            """
            select
                p.name  as parent_name,
                p.phone as parent_phone,
                u.email as owner_email,
                ml.category,
                ml.day_key,
                count(*) filter (where ml.status = 'failed')                      as failures,
                max(ml.created_at) filter (where ml.status = 'failed')            as last_attempt_at,
                (array_agg(ml.detail order by ml.created_at desc)
                    filter (where ml.status = 'failed'))[1]                       as last_error
            from message_logs ml
            left join parents p on p.id = ml.parent_id
            left join users   u on u.id = ml.user_id
            where ml.created_at >= $1
            group by ml.schedule_id, ml.message_index, ml.day_key, ml.category,
                     p.name, p.phone, u.email
            having count(*) filter (where ml.status = 'failed') > 0
               and bool_or(ml.status in ('sent', 'simulated')) = false
            order by max(ml.created_at) filter (where ml.status = 'failed') desc nulls last
            limit 100
            """,
            since,
        )

    def _rate(n, d):
        return round(n / d, 4) if d else None

    return {
        "range_days": days,
        "overall": {
            "total": total,
            "delivered": delivered,
            "read": read,
            "failed": failed,
            "pending": pending,
            "delivery_rate": _rate(delivered, total),
            "read_rate": _rate(read, total),
            "failure_rate": _rate(failed, total),
        },
        "daily": [
            {
                "day_key": r["day_key"],
                "delivered": r["delivered"] or 0,
                "read": r["read"] or 0,
                "failed": r["failed"] or 0,
            }
            for r in daily_rows
        ],
        "stuck_sends": [
            {
                "id": str(r["id"]),
                "parent_name": r["parent_name"] or "Unknown",
                "category": r["category"],
                "created_at": r["created_at"].isoformat(),
                "has_sid": r["sid"] is not None,
            }
            for r in stuck_rows
        ],
        "failing_parents": [
            {
                "parent_name": r["parent_name"] or "Unknown",
                "parent_phone": r["parent_phone"],
                "owner_email": r["owner_email"],
                "category": r["category"],
                "day_key": r["day_key"],
                "failures": r["failures"] or 0,
                "last_attempt_at": r["last_attempt_at"].isoformat() if r["last_attempt_at"] else None,
                "last_error": r["last_error"],
            }
            for r in failing_rows
        ],
    }
