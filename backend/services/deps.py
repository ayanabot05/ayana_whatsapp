"""AYANA deps; extracted without changing API behaviour."""
import asyncio
import json
import logging
from fastapi import HTTPException, Request
from typing import Optional, Tuple
from rate_limit import check_login_rate_limit
from database import get_pool
from medicine_sync import sync_medicine_reminders
from services import billing_access
from templates_data import category_type
from pricing import PLAN_BY_ID, plan_limits, resolve_plan_id


logger = logging.getLogger("ayana")

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def login_rate_check(email: str, ip: str) -> Tuple[bool, Optional[int]]:
    return await check_login_rate_limit(email, ip)


async def _audit_write(user_id, action, meta):
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                insert into audit_logs (user_id, action, meta, created_at)
                values ($1, $2, $3::jsonb, now())
                """,
                str(user_id) if user_id else None,
                action,
                json.dumps(meta or {}),
            )
    except Exception as e:
        logger.warning("[audit] write failed for %s: %s", action, e)


_bg_tasks: set = set()


async def audit(user_id, action, meta=None):
    """Fire-and-forget: the request never waits on the audit round-trip."""
    task = asyncio.create_task(_audit_write(user_id, action, meta))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

def _parse_jsonb_field(value, default=None):
    """Safe parser for jsonb columns that may come back as str, dict/list, or None after Mongo->Postgres migration."""
    if value is None:
        return default if default is not None else []

    if isinstance(value, str):
        if not value.strip():
            return default if default is not None else []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return default if default is not None else []

    return value


def scope(user) -> str:
    """Household owner if this is a linked family member, else the user's own id.
    Both are uuid.UUID values coming off asyncpg records — callers that need
    a string (for audit meta, dict keys, etc.) should str() this themselves."""
    return user.get("household_owner_id") or user["id"]


def is_member(user) -> bool:
    return bool(user.get("household_owner_id"))


async def _get_plan_id(user) -> str:
    # Admins always get top-tier access, independent of any payment state —
    # so the owner's admin login keeps working even after payments go live.
    if (user or {}).get("role") == "admin":
        return "raksha"
    async with get_pool().acquire() as conn:
        entitlement = await billing_access.access(conn,scope(user))
    return entitlement['plan']


async def _sync_medicine_reminders_for_parent(user, parent_id, medicine_list: list[dict]) -> dict | None:
    """
    Re-syncs a parent's schedule after their medicine_list changes, so
    medicine_sync.py isn't dead code sitting unwired. No-ops (returns None)
    if the parent has no active schedule yet.
    """
    async with get_pool().acquire() as conn:
        sched = await conn.fetchrow(
            "select * from schedules where parent_id = $1::uuid and active = true and deleted_at is null",
            parent_id,
        )
        if not sched:
            return None
        plan_id = await _get_plan_id(user)
        messages = json.loads(sched["messages"]) if isinstance(sched["messages"], str) else (sched["messages"] or [])
        result = sync_medicine_reminders(
            medicine_list=medicine_list or [],
            existing_messages=messages,
            plan_id=plan_id,
        )
        await conn.execute(
            "update schedules set messages = $1::jsonb where id = $2",
            json.dumps(result["messages"]), sched["id"],
        )
    if result["dropped"]:
        logger.warning(
            "[medicine_sync] parent=%s dropped reminder time(s) over plan limit: %s",
            parent_id, result["dropped"],
        )
    return result


async def _plan_usage(owner_id) -> dict:
    pool = get_pool()
    counts, schedules = await asyncio.gather(
        pool.fetchrow(
            """
            select
              (select count(*) from parents where user_id = $1 and deleted_at is null) as parents,
              (select count(*) from users where household_owner_id = $1 and deleted_at is null) as members,
              (select count(*) from circle_invites where owner_id = $2 and status = 'pending') as pending_invites,
              (select count(*) from care_circle_siblings where owner_id = $1 and verified = true) as siblings,
              (select count(*) from schedules where user_id = $1 and deleted_at is null and recovery_mode = true) as recovery_schedules
            """,
            owner_id, str(owner_id),
        ),
        pool.fetch(
            "select id, messages, recovery_mode from schedules where user_id = $1 and deleted_at is null", owner_id
        ),
    )
    parents, members, pending_invites, siblings, recovery_schedules = (
        counts["parents"], counts["members"], counts["pending_invites"], counts["siblings"], counts["recovery_schedules"],
    )

    schedule_violations = []
    for sched in schedules:
        messages = json.loads(sched["messages"]) if isinstance(sched["messages"], str) else (sched["messages"] or [])
        checkins = sum(1 for m in messages if category_type(m.get("category")) == "checkin")
        reminders = sum(1 for m in messages if category_type(m.get("category")) == "reminder")
        schedule_violations.append({
            "schedule_id": str(sched["id"]),
            "messages": len(messages),
            "checkins": checkins,
            "reminders": reminders,
            "recovery_mode": bool(sched["recovery_mode"]),
        })

    return {
        "parents": parents,
        "members": members,
        "pending_invites": pending_invites,
        "siblings": siblings,
        # Everything that counts toward the plan's family_members limit —
        # legacy email members/invites AND the new phone-verified siblings —
        # so a downgrade correctly warns to remove them first (#11).
        "family_members_used": members + pending_invites + siblings,
        "recovery_schedules": recovery_schedules,
        "schedules": schedule_violations,
    }


async def _validate_plan_transition(owner_id, target_plan: str) -> dict:
    target_plan = resolve_plan_id(target_plan)
    limits = plan_limits(target_plan)
    usage = await _plan_usage(owner_id)
    blockers = []

    if usage["parents"] > limits.get("parents", 1):
        blockers.append(f"Remove {usage['parents'] - limits.get('parents', 1)} parent profile(s) before switching to {PLAN_BY_ID[target_plan]['name']}.")

    if usage["family_members_used"] > limits.get("family_members", 0):
        blockers.append(f"Remove {usage['family_members_used'] - limits.get('family_members', 0)} care-circle member/invite(s) before switching to {PLAN_BY_ID[target_plan]['name']}.")

    if usage["recovery_schedules"] and not limits.get("recovery_mode"):
        blockers.append("End active recovery mode before switching to a plan without surgery/recovery benefits.")

    for sched in usage["schedules"]:
        if sched["messages"] > limits.get("templates_per_day", 0):
            blockers.append(f"Schedule {sched['schedule_id']} has {sched['messages']} daily messages; target plan allows {limits.get('templates_per_day', 0)}.")
        if sched["checkins"] > limits.get("checkins", 0):
            blockers.append(f"Schedule {sched['schedule_id']} has {sched['checkins']} check-ins; target plan allows {limits.get('checkins', 0)}.")
        if sched["reminders"] > limits.get("reminders", 0):
            blockers.append(f"Schedule {sched['schedule_id']} has {sched['reminders']} reminders; target plan allows {limits.get('reminders', 0)}.")

    if blockers:
        raise HTTPException(status_code=400, detail={"message": "This downgrade needs cleanup first.", "blockers": blockers, "usage": usage})
    return usage
