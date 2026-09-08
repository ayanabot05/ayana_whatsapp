"""
scheduler.py — APScheduler job runner for AYANA v2 message delivery.

Job 1 — _deliver_due_messages (every 1 minute)
    Smart routing: session closed -> approved template by category;
    session open -> free in-session quick-reply.
    variants_per_slot comes from the plan (Nitya=3, Bandham/Raksha=7).

    RELIABILITY FIX (this pass): a message slot used to be marked
    permanently "done" for the day the instant ANY message_logs row
    existed for it — success or failure. That meant a single transient
    send failure (Meta hiccup, template version mismatch, etc.) meant
    the parent got NOTHING for that slot for the rest of the day, with
    no automatic retry. Paying customers depend on these arriving every
    day without interruption, so a slot is now only considered "done"
    once a message_logs row for it shows a SUCCESSFUL status
    ('sent' or 'simulated'). A failed attempt is retried with spacing
    (5 min after the 1st failure, then 10 min, then every 10 min) until
    it succeeds or the day ends — never giving up, but never hammering
    Meta's API every single minute either.

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
from monthly_report import generate_reports_for_month
from pricing import plan_limits, resolve_plan_id
from templates_data import category_type
from whatsapp import send_dynamic_checkin, send_reengagement

logger = logging.getLogger("ayana.scheduler")

_scheduler: AsyncIOScheduler | None = None

# Unique per-process identity so lock ownership is unambiguous in logs.
_WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"

# Last successful run per job — surfaced by /api/health as the scheduler heartbeat.
_LAST_RUN: dict[str, str] = {}

# "No interruption" retry policy. A slot that fails is retried with spacing so
# we never hammer Meta's API, but we also never give up within the day — the
# only things that retire a slot are (a) a SUCCESSFUL send or (b) the day
# boundary. Spacing after each failure:
#   failure #1  -> wait 5 min before the next attempt
#   failure #2  -> wait 10 min
#   failure #3+ -> retry every 10 min, forever
# Overridable via env for ops tuning; defaults encode the schedule above.
RETRY_BACKOFF_MINUTES = [
    int(x) for x in os.environ.get("WA_RETRY_BACKOFF_MINUTES", "5,10").split(",") if x.strip()
] or [5, 10]


# ── Send-eligibility rules (pure + unit-tested in tests/test_flood_gate.py) ──
def eligible_from(created_at, activated_at, tz):
    """Parent-local moment a parent first becomes eligible for sends: the LATER
    of when the parent was created and when the account's WhatsApp was
    activated. Slots scheduled before this are never back-filled — this is what
    stops a parent added mid-day (or a 2nd parent added weeks later) from
    replaying the whole day's earlier check-ins at once."""
    def aware(dt):
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    created_at, activated_at = aware(created_at), aware(activated_at)
    if created_at and activated_at:
        anchor = max(created_at, activated_at)
    else:
        anchor = created_at or activated_at
    return anchor.astimezone(tz) if anchor else None


def slot_due(now_local, slot_time: str, eligible_local) -> bool:
    """Should a daily check-in slot fire right now?

    True only when BOTH hold:
      1. the slot's local time has already arrived today, and
      2. that time did not fall before the parent became eligible.
    Rule 2 is the flood guard: a parent set up at 8 PM starts from the next
    slot after 8 PM, not from breakfast.
    """
    if slot_time > now_local.strftime("%H:%M"):
        return False  # not due yet today
    try:
        sh, sm = (int(x) for x in str(slot_time).split(":")[:2])
    except Exception:
        sh, sm = 0, 0
    slot_dt = now_local.replace(hour=sh, minute=sm, second=0, microsecond=0)
    if eligible_local is not None and slot_dt < eligible_local:
        return False  # slot's time passed before the parent was eligible
    return True


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
        _LAST_RUN[job_name] = datetime.now(timezone.utc).isoformat()
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

                # #9 Vacation / holiday mode: skip ALL sends while today
                # (parent-local) falls inside the paused range; auto-resumes
                # the day after vacation_end. ISO YYYY-MM-DD strings compare
                # correctly lexicographically, so no date parsing needed.
                vac_start = parent["vacation_start"]
                vac_end = parent["vacation_end"]
                if vac_start and vac_end and vac_start <= day_key <= vac_end:
                    logger.info(
                        "Scheduler: skipped sends for parent %s — vacation mode %s..%s (today %s)",
                        parent["name"], vac_start, vac_end, day_key,
                    )
                    continue

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

                # Flood guard, anchored PER PARENT (created_at ∪ activation) —
                # see eligible_from()/slot_due(). The old code anchored on the
                # account's activation alone, so adding Nanna weeks after Amma
                # replayed his whole day of slots at once. Computed once here.
                eligible_local = eligible_from(parent["created_at"], activation["activated_at"], tz)

                for idx, msg in enumerate(sched["messages"] or []):
                    # Fire from the scheduled time onward until a SUCCESSFUL send
                    # is recorded (already_sent check below), but never backfill
                    # slots from before the parent was eligible. Both rules live
                    # in slot_due() so they stay testable.
                    if not slot_due(local, msg.get("time") or "00:00", eligible_local):
                        continue

                    if msg.get("is_recovery") and not limits.get("recovery_mode"):
                        continue

                    # Only a CONFIRMED SUCCESS retires this slot for the day.
                    # A prior 'failed' row does NOT block retrying — that was
                    # the actual bug causing silent daily drop-outs.
                    already_sent = await conn.fetchrow(
                        """
                        select 1 from message_logs
                        where schedule_id = $1 and message_index = $2 and day_key = $3
                          and status in ('sent', 'simulated')
                        """,
                        sched["id"], idx, day_key,
                    )
                    if already_sent:
                        continue

                    # "No interruption" backoff: after a failure, wait the
                    # scheduled spacing before retrying (5 min, then 10 min,
                    # then every 10 min forever) instead of retrying every
                    # single minute. A SUCCESS retires the slot via the
                    # already_sent check above; nothing here ever gives up.
                    fail_stat = await conn.fetchrow(
                        """
                        select count(*) as n, max(created_at) as last_at
                        from message_logs
                        where schedule_id = $1 and message_index = $2 and day_key = $3
                          and status = 'failed'
                        """,
                        sched["id"], idx, day_key,
                    )
                    fail_count = (fail_stat["n"] if fail_stat else 0) or 0
                    last_fail_at = fail_stat["last_at"] if fail_stat else None
                    if fail_count and last_fail_at is not None:
                        if last_fail_at.tzinfo is None:
                            last_fail_at = last_fail_at.replace(tzinfo=timezone.utc)
                        wait_min = RETRY_BACKOFF_MINUTES[min(fail_count, len(RETRY_BACKOFF_MINUTES)) - 1]
                        if now_utc < last_fail_at + timedelta(minutes=wait_min):
                            continue  # backing off — not yet time to retry this slot

                    msg_type = category_type(msg.get("category"))
                    _limit_key = {"checkin": "checkins", "reminder": "reminders", "activity": "activities"}[msg_type]
                    if sent_counts[msg_type] >= limits.get(_limit_key, 0):
                        continue

                    medicine_name = ""
                    if msg.get("category") == "medicine":
                        medicines = parent["medicine_list"] or []
                        chosen = None
                        if medicines:
                            for med in medicines:
                                if isinstance(med, dict) and med.get("reminder_time") == hhmm:
                                    chosen = med
                                    break
                            if chosen is None and isinstance(medicines[0], dict):
                                chosen = medicines[0]
                        if chosen:
                            # Describe the pill as "Name Dose (colour shape)" so
                            # the parent recognises it — e.g. "Pan 40mg (white round)".
                            name = chosen.get("name", "")
                            descr = " ".join(x for x in [chosen.get("color"), chosen.get("shape")] if x).strip()
                            dose = chosen.get("dose")
                            medicine_name = f"{name} {dose}".strip() if dose else name
                            if descr:
                                medicine_name = f"{medicine_name} ({descr})".strip() if medicine_name else descr

                    result = await send_dynamic_checkin(
                        dict(parent),
                        msg.get("category"),
                        local.timetuple().tm_yday,
                        variants_per_slot,
                        medicine_name=medicine_name,
                    )
                    status = result.get("status")
                    # Only count this slot against the plan's daily quota once
                    # it actually succeeds — a failed attempt shouldn't burn
                    # the parent's daily allowance while we keep retrying it.
                    if status in ("sent", "simulated"):
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
                        msg_type, status, result.get("detail"), result.get("sid"), now_utc,
                    )
                    if status in ("sent", "simulated"):
                        logger.info(
                            "Delivered msg (%s) to parent %s: %s",
                            status, parent["name"], msg.get("category"),
                        )
                    else:
                        next_wait = RETRY_BACKOFF_MINUTES[min(fail_count + 1, len(RETRY_BACKOFF_MINUTES)) - 1]
                        logger.warning(
                            "Scheduler: send FAILED for parent %s category %s (failure #%d today) — "
                            "will retry in ~%d min: %s",
                            parent["name"], msg.get("category"), fail_count + 1, next_wait,
                            result.get("detail"),
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
                # #9 Vacation mode: no re-engagement nudges during a paused range.
                try:
                    _tz = ZoneInfo(parent["timezone"] or "Asia/Kolkata")
                except Exception:
                    _tz = ZoneInfo("Asia/Kolkata")
                _today = datetime.now(timezone.utc).astimezone(_tz).strftime("%Y-%m-%d")
                if parent["vacation_start"] and parent["vacation_end"] and parent["vacation_start"] <= _today <= parent["vacation_end"]:
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
            _msgs_raw = sched["messages"]
            messages = json.loads(_msgs_raw) if isinstance(_msgs_raw, str) else (_msgs_raw or [])
            active_messages = [m for m in messages if not m.get("is_recovery")]
            recovery_messages = [m for m in messages if m.get("is_recovery")]
            await conn.execute(
                """
                update schedules
                set messages = $1::jsonb, recovery_mode = false, recovery_until = null,
                    archived_recovery_messages = $2::jsonb
                where id = $3
                """,
                json.dumps(active_messages), json.dumps(recovery_messages), sched["id"],
            )
            await conn.execute(
                """
                insert into audit_logs (user_id, action, meta, created_at)
                values ($1, 'recovery_auto_expired', $2, now())
                """,
                sched["user_id"],
                json.dumps({"schedule_id": str(sched["id"]), "archived": len(recovery_messages)}),
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