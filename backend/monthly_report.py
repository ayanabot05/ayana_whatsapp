"""
monthly_report.py — Monthly (not daily) summary reports for AYANA.

Why monthly: parents already get real-time replies over WhatsApp when
they tap in, so a daily digest is redundant. A single day also has too
few data points for a meaningful mood trend. Monthly gives the mood
graph something real to show and matches all 3 plans' report cadence.

Report depth by plan:
  Nitya   — simple tap/skip counts, no mood graph
  Bandham — counts + mood graph with a short trend note
  Raksha  — same as Bandham, fanned out to both Care Circle members

Delivery: written to the `monthly_reports` table for the frontend to
fetch (GET /reports/monthly), AND pushed as a WhatsApp notification
(the 6th approved template, "report_ready") to the child.

Language: the child/account-owner record has no language field of its
own, so the notification is sent in the PARENT's configured language
as a proxy until a dedicated user-level language preference exists.

Bounded date ranges: both `voice_replies` and `_mood_series()` are
bounded to [start_day 00:00, end_day 24:00) explicitly, so a report
never picks up a reply from outside the month being reported on.
"""

import logging
from datetime import datetime, timezone, timedelta
from calendar import monthrange

from database import get_pool
from pricing import plan_limits, PLAN_BY_ID
from whatsapp import send_report_ready

logger = logging.getLogger("ayana.monthly_report")

_FEELING_SCORE = {"good": 1.0, "okay": 0.5, "not_well": 0.0}


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def _day_key_to_dt(day_key: str) -> datetime:
    return datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)


async def _mood_series(conn, parent_id, start_day: str, end_day: str) -> list[dict]:
    """One point per day the parent tapped a feeling — used for the mood graph."""
    range_start = _day_key_to_dt(start_day)
    range_end = _day_key_to_dt(end_day) + timedelta(days=1)
    replies = await conn.fetch(
        """
        select created_at, intent from parent_replies
        where parent_id = $1 and created_at >= $2 and created_at < $3
          and intent like 'feeling:%'
        order by created_at asc
        """,
        parent_id, range_start, range_end,
    )
    series, seen = [], set()
    for r in replies:
        day = r["created_at"].strftime("%Y-%m-%d")
        if day in seen:
            continue
        seen.add(day)
        feeling = r["intent"].split(":", 1)[1]
        series.append({"day": day, "feeling": feeling, "score": _FEELING_SCORE.get(feeling)})
    return series


async def _daily_details(conn, parent_id, start_day: str, end_day: str) -> dict:
    """Per-day / per-category breakdown stored alongside the summary so the
    report page (and its PDF) can show exactly what happened each day."""
    range_start = _day_key_to_dt(start_day)
    range_end = _day_key_to_dt(end_day) + timedelta(days=1)
    logs = await conn.fetch(
        """
        select id, day_key, category, msg_type, status, reply_status, created_at
        from message_logs where parent_id = $1 and day_key >= $2 and day_key <= $3
        order by created_at asc
        """,
        parent_id, start_day, end_day,
    )
    replies = await conn.fetch(
        """
        select created_at, intent, is_voice, body from parent_replies
        where parent_id = $1 and created_at >= $2 and created_at < $3
        order by created_at asc
        """,
        parent_id, range_start, range_end,
    )
    emergencies = await conn.fetchval(
        "select count(*) from emergency_events where parent_id = $1 and created_at >= $2 and created_at < $3",
        parent_id, range_start, range_end,
    )

    replies_by_day: dict[str, list] = {}
    for r in replies:
        replies_by_day.setdefault(r["created_at"].strftime("%Y-%m-%d"), []).append(r)

    days: dict[str, dict] = {}
    by_category: dict[str, dict] = {}
    for log in logs:
        d = days.setdefault(log["day_key"], {"day": log["day_key"], "sent": 0, "replied": 0, "items": []})
        delivered = log["status"] in ("sent", "simulated")
        day_replies = replies_by_day.get(log["day_key"], [])
        replied = log["reply_status"] in ("done", "skipped", "pending") or any(r["created_at"] >= log["created_at"] for r in day_replies)
        if delivered:
            d["sent"] += 1
        if replied:
            d["replied"] += 1
        d["items"].append({
            "time": log["created_at"].strftime("%H:%M"),
            "category": log["category"],
            "msg_type": log["msg_type"],
            "status": log["status"],
            "reply_status": log["reply_status"],
            "replied": replied,
        })
        cat = by_category.setdefault(log["category"], {"category": log["category"], "sent": 0, "replied": 0})
        if delivered:
            cat["sent"] += 1
        if replied:
            cat["replied"] += 1

    feelings = {"good": 0, "okay": 0, "not_well": 0}
    medicine = {"done": 0, "skipped": 0}
    for r in replies:
        intent = r["intent"] or ""
        if intent.startswith("feeling:"):
            f = intent.split(":", 1)[1]
            if f in feelings:
                feelings[f] += 1
        elif intent.startswith(("done:", "skip:")):
            action, _, cat = intent.partition(":")
            if "medicine" in (cat or ""):
                medicine["done" if action == "done" else "skipped"] += 1

    total_sent = sum(d["sent"] for d in days.values())
    total_replied = sum(d["replied"] for d in days.values())
    return {
        "days": sorted(days.values(), key=lambda x: x["day"]),
        "by_category": sorted(by_category.values(), key=lambda x: -x["sent"]),
        "feelings": feelings,
        "medicine": medicine,
        "emergencies": emergencies,
        "replies_total": len(replies),
        "reply_rate": round(total_replied / total_sent, 3) if total_sent else None,
        "active_days": len([d for d in days.values() if d["sent"] > 0]),
    }


def _trend_note(series: list[dict]) -> str:
    scored = [p["score"] for p in series if p["score"] is not None]
    if len(scored) < 4:
        return "Not enough check-ins yet this month for a trend."
    first_half = scored[: len(scored) // 2]
    second_half = scored[len(scored) // 2:]
    avg1 = sum(first_half) / len(first_half)
    avg2 = sum(second_half) / len(second_half)
    diff = avg2 - avg1
    if diff > 0.15:
        return "Mood trended upward this month."
    if diff < -0.15:
        return "Mood dipped somewhat this month — might be worth a call."
    return "Mood stayed fairly steady this month."


async def _notify_report_ready(conn, user_id: str, parent_id, period: str, shared: bool) -> None:
    """Push the report_ready WhatsApp template to the account owner, and to
    Care Circle members too when the plan shares reports (Raksha). Failures
    here are logged, never raised — the report itself is already saved
    regardless of whether the nudge goes out."""
    parent = await conn.fetchrow("select * from parents where id = $1", parent_id)
    if not parent:
        return
    parent_display = parent["preferred_name"] or parent["name"] or "Amma"
    language = parent["language"] or "en"

    owner = await conn.fetchrow("select * from users where id = $1::uuid", user_id)
    recipients = [owner] if owner else []
    if shared:
        members = await conn.fetch(
            "select * from users where household_owner_id = $1::uuid and deleted_at is null limit 20",
            user_id,
        )
        recipients += list(members)

    for r in recipients:
        if not r or not r["phone"]:
            continue
        try:
            await send_report_ready(r["phone"], language, parent_display)
        except Exception as e:
            logger.error("[monthly_report] report_ready notify failed for user %s: %s", r["id"], e)


async def generate_monthly_report(user_id: str, parent_id, plan_id: str, year: int, month: int, notify: bool = False) -> dict:
    start_day, end_day = _month_bounds(year, month)
    range_start = _day_key_to_dt(start_day)
    range_end = _day_key_to_dt(end_day) + timedelta(days=1)  # exclusive upper bound
    limits = plan_limits(plan_id)

    async with get_pool().acquire() as conn:
        logs = await conn.fetch(
            "select * from message_logs where parent_id = $1 and day_key >= $2 and day_key <= $3",
            parent_id, start_day, end_day,
        )

        total = len(logs)
        sent = sum(1 for l in logs if l["status"] in ("sent", "simulated"))
        skipped = sum(1 for l in logs if l["skipped"])

        voice_replies = await conn.fetchval(
            """
            select count(*) from parent_replies
            where parent_id = $1 and is_voice = true and created_at >= $2 and created_at < $3
            """,
            parent_id, range_start, range_end,
        )

        parent_row = await conn.fetchrow("select name, preferred_name, relationship, language from parents where id = $1", parent_id)
        details = await _daily_details(conn, parent_id, start_day, end_day)
        details["parent_name"] = (parent_row["name"] if parent_row else None) or "Parent"
        details["relationship"] = parent_row["relationship"] if parent_row else None
        details["plan_name"] = (PLAN_BY_ID.get(plan_id) or {}).get("name", plan_id)

        report = {
            "user_id": user_id,
            "parent_id": parent_id,
            "plan": plan_id,
            "period": f"{year:04d}-{month:02d}",
            "total_touches": total,
            "delivered": sent,
            "skipped": skipped,
            "voice_replies": voice_replies,
            "mood_graph": None,
            "trend_note": None,
            "details": details,
            "shared_with_care_circle": limits.get("family_members", 1) > 1,
            "generated_at": datetime.now(timezone.utc),
        }

        # Mood graph + analysis: Bandham and Raksha only (matches plan feature table)
        if limits.get("variants_per_slot", 3) >= 7:
            series = await _mood_series(conn, parent_id, start_day, end_day)
            report["mood_graph"] = series
            report["trend_note"] = _trend_note(series)

        await conn.execute(
            """
            insert into monthly_reports
                (user_id, parent_id, plan, period, total_touches, delivered, skipped,
                 voice_replies, mood_graph, trend_note, shared_with_care_circle, generated_at, details)
            values ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13::jsonb)
            on conflict (user_id, parent_id, period) do update
                set plan = excluded.plan,
                    total_touches = excluded.total_touches,
                    delivered = excluded.delivered,
                    skipped = excluded.skipped,
                    voice_replies = excluded.voice_replies,
                    mood_graph = excluded.mood_graph,
                    trend_note = excluded.trend_note,
                    shared_with_care_circle = excluded.shared_with_care_circle,
                    generated_at = excluded.generated_at,
                    details = excluded.details
            """,
            user_id, parent_id, plan_id, report["period"], total, sent, skipped,
            voice_replies, report["mood_graph"],
            report["trend_note"], report["shared_with_care_circle"], report["generated_at"],
            details,
        )
        if notify:
            await _notify_report_ready(conn, user_id, parent_id, report["period"], report["shared_with_care_circle"])

    report["generated_at"] = report["generated_at"].isoformat()
    report["parent_id"] = str(parent_id)
    report["user_id"] = str(user_id)
    return report


async def generate_reports_for_month(year: int, month: int):
    """Run once/month (e.g. 1st of the month, per household) across all active users."""
    async with get_pool().acquire() as conn:
        parents = await conn.fetch("select * from parents where deleted_at is null")

    for parent in parents:
        async with get_pool().acquire() as conn:
            ps = await conn.fetchrow(
                "select * from payment_state where user_id = $1", parent["user_id"]
            )
        plan_id = (ps["plan"] if ps else None) or "nitya"
        try:
            await generate_monthly_report(parent["user_id"], parent["id"], plan_id, year, month, notify=True)
        except Exception as e:
            logger.error("[monthly_report] Failed for parent %s: %s", parent["id"], e, exc_info=True)