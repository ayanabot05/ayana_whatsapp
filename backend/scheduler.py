"""
scheduler.py — APScheduler job runner for AYANA v2 message delivery (User-Configured Schedules).

This version replaces the old "messages JSONB" logic with the new
user-configured tables (parent_checkins, parent_health_reminders, parent_routines, medicines).

Key Features:
- Distributed lock (safe for multiple replicas).
- 15-minute cooldown (Redis-based) to prevent flooding after a reply.
- Retry with backoff for failed sends (does not give up during the day).
- Vacation mode and Activity Window support.
- Reads directly from the new DB tables.
- Plan limits (checkins/reminders per day) are enforced against the day's
  actual message_logs count, not a per-tick counter that resets every
  minute — the previous version's sent_counts was reseeded to zero on
  every scheduler run, so a "3 checkins/day" plan cap only ever blocked
  sends that happened to land in the exact same minute.
- Redis is accessed through rate_limit.get_redis() (async, same client the
  rest of the app uses) instead of a separate blocking sync client, and
  degrades gracefully (cooldown just no-ops) if Redis is unreachable,
  matching the "Redis is optional" pattern used in /ready and /health.
"""

import json
import logging
import os
import socket
import uuid
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import get_pool
from escalation import run_care_watch_impl
from pricing import plan_limits, resolve_plan_id
from rate_limit import get_redis
from templates_data import category_type
from whatsapp import send_dynamic_checkin, send_reengagement

logger = logging.getLogger("ayana.scheduler")

_scheduler: AsyncIOScheduler | None = None
_WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
_LAST_RUN: dict[str, str] = {}

COOLDOWN_SECONDS = int(os.environ.get("WA_COOLDOWN_SECONDS", "900"))  # 15 minutes

# Retry backoff (minutes): 5, 10, 10, 10...
RETRY_BACKOFF_MINUTES = [
    int(x) for x in os.environ.get("WA_RETRY_BACKOFF_MINUTES", "5,10").split(",") if x.strip()
] or [5, 10]

# Maps a schedule item's msg_type to the plan_limits() key that caps it,
# and to the message_logs.msg_type value used to count today's sends.
_LIMIT_KEY_BY_MSG_TYPE = {"checkin": "checkins", "reminder": "reminders"}


def scheduler_heartbeat() -> dict:
    return {
        "running": _scheduler is not None and getattr(_scheduler, "running", False),
        "worker": _WORKER_ID,
        "last_runs": dict(_LAST_RUN),
        "jobs": [
            {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in (_scheduler.get_jobs() if _scheduler else [])
        ],
    }


async def _with_lock(job_name: str, ttl_seconds: int, coro_fn) -> None:
    """Distributed lock for safe multi-replica execution."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    try:
        async with get_pool().acquire() as conn:
            won_row = await conn.fetchrow(
                """
                insert into scheduler_locks (lock_name, holder, acquired_at, expires_at)
                values ($1, $2, $3, $4)
                on conflict (lock_name) do update
                    set holder = excluded.holder,
                        acquired_at = excluded.acquired_at,
                        expires_at = excluded.expires_at
                    where scheduler_locks.expires_at <= $5
                returning lock_name
                """,
                job_name, _WORKER_ID, now, expires_at, now,
            )
    except Exception as e:
        logger.debug("[sched] Lock acquire race for %s (expected under concurrency): %s", job_name, e)
        return

    if not won_row:
        return

    try:
        await coro_fn()
        _LAST_RUN[job_name] = datetime.now(timezone.utc).isoformat()
    finally:
        async with get_pool().acquire() as conn:
            await conn.execute(
                "update scheduler_locks set expires_at = $1 where lock_name = $2 and holder = $3",
                now, job_name, _WORKER_ID,
            )


async def _get_parent_schedule(parent_id) -> dict:
    """Fetches all user-configured schedule items for a parent."""
    schedule = {"checkins": [], "health": [], "routines": [], "medicines": []}

    async with get_pool().acquire() as conn:
        # 1. Daily Check-ins
        rows = await conn.fetch(
            "SELECT category, time FROM parent_checkins WHERE parent_id = $1 AND is_active = true",
            parent_id,
        )
        for r in rows:
            schedule["checkins"].append({"category": r["category"], "time": r["time"]})

        # 2. Health Reminders
        rows = await conn.fetch(
            "SELECT category, time FROM parent_health_reminders WHERE parent_id = $1 AND is_active = true",
            parent_id,
        )
        for r in rows:
            schedule["health"].append({"category": r["category"], "time": r["time"]})

        # 3. Routines
        rows = await conn.fetch(
            "SELECT category, time FROM parent_routines WHERE parent_id = $1 AND is_active = true",
            parent_id,
        )
        for r in rows:
            schedule["routines"].append({"category": r["category"], "time": r["time"]})

        # 4. Medicines (with dynamic times from JSONB). This table is now the
        # single source of truth for medicines — parents.medicine_list is
        # retired; existing rows were migrated in the startup migration.
        rows = await conn.fetch(
            "SELECT id, name, reminder_times FROM medicines WHERE parent_id = $1 AND is_active = true",
            parent_id,
        )
        for med in rows:
            times = med["reminder_times"]  # JSON array e.g., ["09:00", "21:00"]
            if isinstance(times, str):
                times = json.loads(times) if times.strip() else []
            for t in (times or []):
                schedule["medicines"].append({
                    "category": "medicine",
                    "time": t,
                    "medicine_name": med["name"],
                    "medicine_id": med["id"],
                })

    return schedule


async def _check_cooldown(parent_id) -> bool:
    """Return True if we should skip sending (parent replied within cooldown window).
    Best-effort: if Redis is unavailable, we don't block sends on it."""
    try:
        r = await get_redis()
    except Exception:
        return False
    if r is None:
        return False
    try:
        last_reply = await r.get(f"parent:{parent_id}:last_reply")
    except Exception as e:
        logger.debug("[sched] cooldown check failed, treating as no cooldown: %s", e)
        return False
    if last_reply:
        try:
            last_dt = datetime.fromisoformat(last_reply)
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < COOLDOWN_SECONDS:
                return True
        except Exception:
            pass
    return False


async def _record_reply_time(parent_id):
    try:
        r = await get_redis()
        if r is not None:
            await r.set(f"parent:{parent_id}:last_reply", datetime.now(timezone.utc).isoformat(), ex=COOLDOWN_SECONDS)
    except Exception as e:
        logger.debug("[sched] failed to record reply time (non-fatal): %s", e)


async def _todays_sent_counts(conn, parent_id, day_key: str) -> defaultdict:
    """Seeds plan-limit counters from message_logs instead of starting at
    zero every tick, so a day's checkins/reminders cap is enforced across
    the whole day, not just within a single 1-minute scheduler run."""
    row = await conn.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE msg_type = 'checkin' AND status IN ('sent', 'simulated'))  AS checkins,
            count(*) FILTER (WHERE msg_type = 'reminder' AND status IN ('sent', 'simulated')) AS reminders
        FROM message_logs
        WHERE parent_id = $1 AND day_key = $2
        """,
        parent_id, day_key,
    )
    counts = defaultdict(int)
    counts["checkin"] = (row["checkins"] if row else 0) or 0
    counts["reminder"] = (row["reminders"] if row else 0) or 0
    return counts


async def _deliver_due_messages_impl():
    now_utc = datetime.now(timezone.utc)

    try:
        async with get_pool().acquire() as fetch_conn:
            # Fetch all active parents
            parents = await fetch_conn.fetch(
                "SELECT * FROM parents WHERE deleted_at IS NULL"
            )
    except Exception as exc:
        logger.error("Scheduler: failed to fetch parents - %s", exc)
        return

    for parent in parents:
        try:
            async with get_pool().acquire() as conn:
                # Activation check
                activation = await conn.fetchrow(
                    "SELECT * FROM activation_state WHERE user_id = $1", parent["user_id"]
                )
                if not activation or not activation["whatsapp_activated"]:
                    continue

                # Timezone
                try:
                    tz = ZoneInfo(parent["timezone"] or "Asia/Kolkata")
                except Exception:
                    tz = ZoneInfo("Asia/Kolkata")

                local = now_utc.astimezone(tz)
                hhmm = local.strftime("%H:%M")
                day_key = local.strftime("%Y-%m-%d")

                # Vacation check
                vac_start = parent["vacation_start"]
                vac_end = parent["vacation_end"]
                if vac_start and vac_end and vac_start <= day_key <= vac_end:
                    continue

                # Activity window check
                DEFAULT_START = "00:00"
                DEFAULT_END = "23:59"
                win_start = parent["activity_window_start"] or DEFAULT_START
                win_end = parent["activity_window_end"] or DEFAULT_END
                if win_start and win_end:
                    if win_start <= win_end:
                        is_outside = not (win_start <= hhmm <= win_end)
                    else:
                        is_outside = win_end < hhmm < win_start
                    if is_outside:
                        continue

                # Cooldown check (15 min)
                if await _check_cooldown(parent["id"]):
                    logger.info("[scheduler] Skipped %s for %s due to cooldown.", parent["name"], parent["id"])
                    continue

                # Plan limits
                ps = await conn.fetchrow("SELECT * FROM payment_state WHERE user_id = $1", parent["user_id"])
                plan_id = resolve_plan_id((ps["plan"] if ps else None) or "nitya")
                limits = plan_limits(plan_id)
                variants_per_slot = limits.get("variants_per_slot", 3)

                # Get user-configured schedule
                schedule = await _get_parent_schedule(parent["id"])

                # Combine all items
                all_items = []
                for item in schedule["checkins"]:
                    all_items.append({"category": item["category"], "time": item["time"], "type": "checkin"})
                for item in schedule["health"]:
                    all_items.append({"category": item["category"], "time": item["time"], "type": "reminder"})
                for item in schedule["routines"]:
                    all_items.append({"category": item["category"], "time": item["time"], "type": "reminder"})
                for item in schedule["medicines"]:
                    all_items.append({
                        "category": "medicine", "time": item["time"], "type": "reminder",
                        "medicine_name": item["medicine_name"],
                    })

                # Seed from today's real counts (bug fix — see module docstring),
                # not a fresh defaultdict(int) that loses the day's history
                # every time this function re-runs a minute later.
                sent_counts = await _todays_sent_counts(conn, parent["id"], day_key)

                for item in all_items:
                    slot_time = item["time"]
                    # Is it due now?
                    if slot_time > hhmm:
                        continue

                    # Check if already sent today (success)
                    already_sent = await conn.fetchrow(
                        """
                        SELECT 1 FROM message_logs
                        WHERE parent_id = $1 AND day_key = $2 AND category = $3
                          AND status IN ('sent', 'simulated')
                        """,
                        parent["id"], day_key, item["category"],
                    )
                    if already_sent:
                        continue

                    # Retry/backoff logic
                    fail_stat = await conn.fetchrow(
                        """
                        SELECT count(*) as n, max(created_at) as last_at
                        FROM message_logs
                        WHERE parent_id = $1 AND day_key = $2 AND category = $3
                          AND status = 'failed'
                        """,
                        parent["id"], day_key, item["category"],
                    )
                    fail_count = (fail_stat["n"] if fail_stat else 0) or 0
                    last_fail_at = fail_stat["last_at"] if fail_stat else None
                    if fail_count and last_fail_at is not None:
                        if last_fail_at.tzinfo is None:
                            last_fail_at = last_fail_at.replace(tzinfo=timezone.utc)
                        wait_min = RETRY_BACKOFF_MINUTES[min(fail_count, len(RETRY_BACKOFF_MINUTES)) - 1]
                        if now_utc < last_fail_at + timedelta(minutes=wait_min):
                            continue

                    # Plan limit check — now against the day's real total.
                    msg_type = item["type"]
                    _limit_key = _LIMIT_KEY_BY_MSG_TYPE.get(msg_type, "activities")
                    if sent_counts[msg_type] >= limits.get(_limit_key, 0):
                        continue

                    # Send the message
                    result = await send_dynamic_checkin(
                        dict(parent),
                        item["category"],
                        local.timetuple().tm_yday,
                        variants_per_slot,
                        medicine_name=item.get("medicine_name", ""),
                    )
                    status = result.get("status")
                    if status in ("sent", "simulated"):
                        sent_counts[msg_type] += 1
                    await conn.execute(
                        """
                        INSERT INTO message_logs
                            (user_id, parent_id, day_key, category, body, msg_type, status, detail, sid, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        """,
                        parent["user_id"], parent["id"], day_key, item["category"],
                        f"{item['category']} check-in", msg_type, status, result.get("detail"),
                        result.get("sid"), now_utc,
                    )
                    if status in ("sent", "simulated"):
                        logger.info("Delivered msg (%s) to parent %s: %s", status, parent["name"], item["category"])
                    else:
                        logger.warning("Scheduler: send FAILED for parent %s category %s - %s", parent["name"], item["category"], result.get("detail"))

        except Exception as exc:
            logger.error("Scheduler: unhandled error for parent %s - %s", parent["id"], exc)


async def _deliver_due_messages():
    await _with_lock("delivery", 55, _deliver_due_messages_impl)


async def _check_reengagement_impl():
    async with get_pool().acquire() as conn:
        parents = await conn.fetch("SELECT * FROM parents WHERE deleted_at IS NULL")

    for parent in parents:
        try:
            async with get_pool().acquire() as conn:
                activation = await conn.fetchrow("SELECT * FROM activation_state WHERE user_id = $1", parent["user_id"])
                if not activation or not activation["whatsapp_activated"]:
                    continue
            result = await send_reengagement(dict(parent), 4)
            if result.get("status") in ("sent", "simulated"):
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO message_logs
                            (user_id, parent_id, day_key, category, body, msg_type, status, detail, sid, created_at)
                        VALUES ($1, $2, $3, 'reengagement', 'reengagement', 'reengagement', $4, $5, $6, $7)
                        """,
                        parent["user_id"], parent["id"], datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        result.get("status"), result.get("detail"), result.get("sid"), datetime.now(timezone.utc),
                    )
        except Exception as exc:
            logger.error("Scheduler: reengagement failed for parent %s - %s", parent["id"], exc)


async def _check_reengagement():
    await _with_lock("reengagement", 14 * 60, _check_reengagement_impl)


async def _run_care_watch():
    await _with_lock("care_watch", 4 * 60, run_care_watch_impl)


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(_deliver_due_messages, "interval", minutes=1, id="ayana_delivery", max_instances=1, coalesce=True)
    _scheduler.add_job(_check_reengagement, "interval", minutes=15, id="ayana_reengagement", max_instances=1, coalesce=True)
    _scheduler.add_job(_run_care_watch, "interval", minutes=5, id="ayana_care_watch", max_instances=1, coalesce=True)
    _scheduler.start()
    logger.info("AYANA v2 scheduler started (user-configured tables).")


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None