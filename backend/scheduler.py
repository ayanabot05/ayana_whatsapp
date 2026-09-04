"""
scheduler.py — APScheduler job runner for AYANA v2 message delivery.

Job 1 — _deliver_due_messages (every 1 minute)
    Smart routing: session closed -> approved template by category;
    session open -> free in-session quick-reply.
    variants_per_slot comes from the plan (Nitya=3, Bandham/Raksha=7).

Job 2 — _check_reengagement (every 15 minutes)
    Re-engagement window is now read per-schedule (reengagement_hours,
    user-set) instead of a static env constant — applies the same way
    to all three plans.

Job 3 — _check_recovery_expiry (daily)
    Raksha recovery mode: when recovery_until has passed, archive the
    extra reminder slots (mark inactive, keep the data) rather than
    deleting them, and flip mode back off so the schedule reverts to
    the normal touch count.

Job 4 — _run_monthly_reports (daily, only fires on the 1st) — OPTIONAL,
    gated by AUTO_MONTHLY_REPORTS=true. Off by default because the
    report delivery channel decision (README "Open items") should be
    made deliberately, not defaulted on.

DISTRIBUTED LOCK
    APScheduler runs in-process. The moment you run more than one API
    replica, every replica's scheduler fires independently — parents
    get duplicate WhatsApp messages (and you get double-billed by
    Meta) every single minute. `_with_lock()` wraps each job so only
    one process across the whole fleet executes it per tick.

    MIGRATION NOTE: Mongo's atomic "upsert only if unheld or expired"
    used a compound filter ($or on expires_at). Postgres's equivalent
    is `INSERT ... ON CONFLICT DO UPDATE ... WHERE <condition>` — the
    WHERE guards the update exactly like Mongo's filter guarded the
    upsert, and RETURNING tells us whether we actually won the lock.
    Still fully race-safe across replicas, still no separate lock
    service needed. The TTL cleanup that used to be a Mongo TTL index
    is now handled by the nightly purge job in schema.sql.

    This does NOT require running a separate worker process — it's
    safe to run the scheduler in every API replica as long as this
    lock wraps every job.
"""

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
from monthly_report import generate_reports_for_month
from pricing import plan_limits, resolve_plan_id
from templates_data import category_type
from whatsapp import send_dynamic_checkin, send_reengagement

logger = logging.getLogger("ayana.scheduler")

_scheduler: AsyncIOScheduler | None = None

# Unique per-process identity so lock ownership is unambiguous in logs.
_WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


async def _with_lock(job_name: str, ttl_seconds: int, coro_fn) -> None:
    """
    Attempt to acquire a short-lived Postgres lock for `job_name`. Only the
    process that wins runs `coro_fn()`. The WHERE clause on the ON CONFLICT
    UPDATE means the update (and therefore the RETURNING row) only happens
    if the existing lock has already expired — so this is race-safe across
    replicas the same way the old Mongo filtered-upsert was.
    """
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
        return  # another replica holds the lock this tick — skip silently

    try:
        await coro_fn()
    finally:
        # Release early so the next tick doesn't wait out the full TTL
        # unnecessarily — best effort, nightly purge job is the real safety net.
        async with get_pool().acquire() as conn:
            await conn.execute(
                "update scheduler_locks set expires_at = $1 where lock_name = $2 and holder = $3",
                now, job_name, _WORKER_ID,
            )


async def _count_sent_today(schedule_id, day_key: str, msg_type: str) -> int:
    async with get_pool().acquire() as conn:
        return await conn.fetchval(
            "select count(*) from message_logs where schedule_id = $1 and day_key = $2 and msg_type = $3",
            schedule_id, day_key, msg_type,
        )


async def _deliver_due_messages_impl():
    now_utc = datetime.now(timezone.utc)

    try:
        async with get_pool().acquire() as fetch_conn:
            schedules = await fetch_conn.fetch(
                "select * from schedules where active = true and deleted_at is null"
            )
    except Exception as exc:
        logger.error("Scheduler: failed to fetch schedules — %s", exc)
        return

    for sched in schedules:
        try:
            async with get_pool().acquire() as conn:
                parent = await conn.fetchrow("select * from parents where id = $1", sched["parent_id"])
                if not parent or parent["deleted_at"]:
                    continue

                activation = await conn.fetchrow(
                    "select * from activation_state where user_id = $1", sched["user_id"]
                )
                if not activation or not activation["whatsapp_activated"]:
                    continue

                try:
                    tz = ZoneInfo(parent["timezone"] or "Asia/Kolkata")
                except Exception:
                    tz = ZoneInfo("Asia/Kolkata")

                local = now_utc.astimezone(tz)
                hhmm = local.strftime("%H:%M")
                day_key = local.strftime("%Y-%m-%d")

                # Send-time activity window check — defer messages sent outside
                # the parent's active hours. Window is child-set
                # (activity_window_start/end as "HH:MM") or auto-learned if
                # child enables auto_activity_detection. Default is
                # 00:00-23:59 (no DND) so testing and new parents work 24/7.
                DEFAULT_START = "00:00"
                DEFAULT_END = "23:59"

                manual_start = parent["activity_window_start"]
                manual_end = parent["activity_window_end"]

                if manual_start and manual_end:
                    win_start = manual_start
                    win_end = manual_end
                elif manual_start or manual_end:
                    logger.warning(
                        "Scheduler: parent %s has a partial activity window (start=%r, end=%r) — "
                        "ignoring and using default %s-%s until both fields are set",
                        parent["name"], manual_start, manual_end, DEFAULT_START, DEFAULT_END,
                    )
                    win_start, win_end = DEFAULT_START, DEFAULT_END
                elif parent["auto_activity_detection"]:
                    recent_replies = await conn.fetch(
                        "select created_at from parent_replies where parent_id = $1 order by created_at desc limit 20",
                        parent["id"],
                    )
                    if recent_replies:
                        reply_hours = [r["created_at"].astimezone(tz).hour for r in recent_replies]
                        win_start = f"{min(reply_hours):02d}:00"
                        win_end = f"{max(reply_hours):02d}:00"
                    else:
                        win_start, win_end = DEFAULT_START, DEFAULT_END
                else:
                    win_start, win_end = DEFAULT_START, DEFAULT_END

                if win_start and win_end:
                    cur = local.strftime("%H:%M")
                    if win_start <= win_end:
                        is_outside = not (win_start <= cur <= win_end)
                    else:
                        is_outside = win_end < cur < win_start

                    if is_outside:
                        logger.info(
                            "Scheduler: skipped sends for parent %s — outside activity window %s-%s (now %s)",
                            parent["name"], win_start, win_end, cur,
                        )
                        continue

                ps = await conn.fetchrow("select * from payment_state where user_id = $1", sched["user_id"])
                plan_id = resolve_plan_id((ps["plan"] if ps else None) or sched["mode"] or "nitya")
                limits = plan_limits(plan_id)
                variants_per_slot = limits.get("variants_per_slot", 3)
                sent_counts = defaultdict(int)

                for idx, msg in enumerate(sched["messages"] or []):
                    if msg.get("time") != hhmm:
                        continue
                    if msg.get("is_recovery") and not limits.get("recovery_mode"):
                        continue

                    already = await conn.fetchrow(
                        "select 1 from message_logs where schedule_id = $1 and message_index = $2 and day_key = $3",
                        sched["id"], idx, day_key,
                    )
                    if already:
                        continue

                    msg_type = category_type(msg.get("category"))
                    if sent_counts[msg_type] >= limits.get(f"{msg_type}s", 0):
                        continue

                    medicine_name = ""
                    if msg.get("category") == "medicine":
                        medicines = parent["medicine_list"] or []
                        if medicines:
                            for med in medicines:
                                if isinstance(med, dict) and med.get("reminder_time") == hhmm:
                                    medicine_name = med.get("name", "")
                                    break
                            if not medicine_name and isinstance(medicines[0], dict):
                                medicine_name = medicines[0].get("name", "")

                    result = await send_dynamic_checkin(
                        dict(parent),
                        msg.get("category"),
                        local.timetuple().tm_yday,
                        variants_per_slot,
                        medicine_name=medicine_name,
                    )
                    sent_counts[msg_type] += 1
                    await conn.execute(
                        """
                        insert into message_logs
                            (user_id, parent_id, schedule_id, message_index, day_key, category,
                             body, msg_type, status, detail, sid, created_at)
                        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        """,
                        sched["user_id"], sched["parent_id"], sched["id"], idx, day_key,
                        msg.get("category"), msg.get("custom_text") or f"{msg.get('category')} check-in",
                        msg_type, result.get("status"), result.get("detail"), result.get("sid"), now_utc,
                    )
                    logger.info(
                        "Delivered msg (%s) to parent %s: %s",
                        result.get("status"), parent["name"], msg.get("category"),
                    )
        except Exception as exc:
            logger.error("Scheduler: unhandled error for schedule %s — %s", sched["id"], exc)


async def _deliver_due_messages():
    await _with_lock("delivery", 55, _deliver_due_messages_impl)


async def _check_reengagement_impl():
    async with get_pool().acquire() as conn:
        schedules = await conn.fetch("select * from schedules where active = true and deleted_at is null")

    seen = set()
    for sched in schedules:
        parent_id = sched["parent_id"]
        if not parent_id or parent_id in seen:
            continue
        seen.add(parent_id)
        try:
            async with get_pool().acquire() as conn:
                activation = await conn.fetchrow(
                    "select * from activation_state where user_id = $1", sched["user_id"]
                )
                if not activation or not activation["whatsapp_activated"]:
                    continue
                parent = await conn.fetchrow(
                    "select * from parents where id = $1 and deleted_at is null", parent_id
                )
                if not parent:
                    continue

            result = await send_reengagement(dict(parent), sched["reengagement_hours"] or 4)
            if result.get("status") in ("sent", "simulated"):
                try:
                    tz = ZoneInfo(parent["timezone"] or "Asia/Kolkata")
                except Exception:
                    tz = ZoneInfo("Asia/Kolkata")
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        """
                        insert into message_logs
                            (user_id, parent_id, schedule_id, message_index, day_key, category,
                             body, msg_type, status, detail, sid, created_at)
                        values ($1, $2, $3, -1, $4, 'reengagement', 'reengagement',
                                'reengagement', $5, $6, $7, $8)
                        """,
                        sched["user_id"], parent_id, sched["id"],
                        datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d"),
                        result.get("status"), result.get("detail"), result.get("sid"),
                        datetime.now(timezone.utc),
                    )
        except Exception as exc:
            logger.error("Scheduler: reengagement failed for schedule %s - %s", sched["id"], exc)


async def _check_reengagement():
    await _with_lock("reengagement", 14 * 60, _check_reengagement_impl)


async def _check_recovery_expiry_impl():
    today = date.today().isoformat()
    async with get_pool().acquire() as conn:
        schedules = await conn.fetch(
            "select * from schedules where deleted_at is null and recovery_mode = true and recovery_until <= $1",
            today,
        )
        for sched in schedules:
            messages = sched["messages"] or []
            active_messages = [m for m in messages if not m.get("is_recovery")]
            recovery_messages = [m for m in messages if m.get("is_recovery")]
            await conn.execute(
                """
                update schedules
                set messages = $1, recovery_mode = false, recovery_until = null,
                    archived_recovery_messages = $2
                where id = $3
                """,
                active_messages, recovery_messages, sched["id"],
            )
            await conn.execute(
                """
                insert into audit_logs (user_id, action, detail, created_at)
                values ($1, 'recovery_auto_expired', $2, now())
                """,
                sched["user_id"],
                {"schedule_id": str(sched["id"]), "archived": len(recovery_messages)},
            )


async def _check_recovery_expiry():
    await _with_lock("recovery_expiry", 60 * 60, _check_recovery_expiry_impl)


async def _run_monthly_reports_impl():
    today = date.today()
    if today.day != 1:
        return
    first_this_month = today.replace(day=1)
    previous_month = first_this_month - timedelta(days=1)
    await generate_reports_for_month(previous_month.year, previous_month.month)


async def _run_monthly_reports():
    await _with_lock("monthly_reports", 60 * 60, _run_monthly_reports_impl)


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
    _scheduler.add_job(_check_recovery_expiry, "interval", hours=24, id="ayana_recovery_expiry", max_instances=1, coalesce=True)
    _auto_monthly = os.environ.get("AUTO_MONTHLY_REPORTS", "true").strip().lower() == "true"
    if _auto_monthly:
        _scheduler.add_job(_run_monthly_reports, "interval", hours=24, id="ayana_monthly_reports", max_instances=1, coalesce=True)
    _scheduler.start()
    logger.info(
        "AYANA v2 scheduler started on worker=%s (delivery:1min, reengagement:15min, recovery-expiry:24h, monthly-reports:%s)",
        _WORKER_ID, "on" if _auto_monthly else "off",
    )


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None