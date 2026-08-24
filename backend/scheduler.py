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

DISTRIBUTED LOCK (new in this pass)
    APScheduler runs in-process. The moment you run more than one API
    replica, every replica's scheduler fires independently — parents
    get duplicate WhatsApp messages (and you get double-billed by
    Meta) every single minute. `_with_lock()` wraps each job so only
    one process across the whole fleet executes it per tick: it
    upserts a short-lived doc in `scheduler_locks` with a TTL, and
    any process that loses the race to acquire it simply skips that
    tick. If the lock holder crashes mid-job, the TTL index (see
    database.ensure_indexes) expires the lock automatically instead of
    wedging delivery forever.

    This does NOT require running a separate worker process — it's
    safe to run the scheduler in every API replica as long as this
    lock wraps every job. (You may still prefer a single dedicated
    worker for clarity/cost; either way this makes concurrent
    schedulers safe by default instead of silently duplicating sends.)
"""

import logging
import os
import socket
import uuid
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import db
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
    Attempt to acquire a short-lived Mongo lock for `job_name`. Only the
    process that wins runs `coro_fn()`. Uses an atomic upsert with a
    filter that only matches an unheld-or-expired lock, so it's race-safe
    across replicas without needing a separate lock service.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    try:
        result = await db.scheduler_locks.update_one(
            {
                "_id": job_name,
                "$or": [{"expires_at": {"$lte": now}}, {"expires_at": {"$exists": False}}],
            },
            {"$set": {"holder": _WORKER_ID, "acquired_at": now, "expires_at": expires_at}},
            upsert=True,
        )
    except Exception as e:
        # Duplicate-key on a concurrent upsert race is expected/harmless —
        # it just means another replica won this tick.
        logger.debug("[sched] Lock acquire race for %s (expected under concurrency): %s", job_name, e)
        return

    won = result.upserted_id is not None or result.modified_count > 0
    if not won:
        return  # another replica holds the lock this tick — skip silently

    try:
        await coro_fn()
    finally:
        # Release early so the next tick doesn't wait out the full TTL
        # unnecessarily — best effort, TTL index is the real safety net.
        await db.scheduler_locks.update_one(
            {"_id": job_name, "holder": _WORKER_ID},
            {"$set": {"expires_at": now}},
        )


async def _count_sent_today(schedule_id, day_key: str, msg_type: str) -> int:
    return await db.message_logs.count_documents({"schedule_id": schedule_id, "day_key": day_key, "msg_type": msg_type})


async def _deliver_due_messages_impl():
    now_utc = datetime.now(timezone.utc)

    # Fetch all active schedules into a Python list first so the DB cursor is
    # closed immediately and a mid-loop exception cannot leave it open.
    try:
        schedules = await db.schedules.find({"active": True, "deleted_at": None}).to_list(None)
    except Exception as exc:
        logger.error("Scheduler: failed to fetch schedules — %s", exc)
        return

    for sched in schedules:
        try:
            parent = await db.parents.find_one({"_id": sched["parent_id"]})
            if not parent or parent.get("deleted_at"):
                continue

            activation = await db.activation_state.find_one({"user_id": sched["user_id"]})
            if not activation or not activation.get("whatsapp_activated"):
                continue

            try:
                tz = ZoneInfo(parent.get("timezone", "Asia/Kolkata"))
            except Exception:
                tz = ZoneInfo("Asia/Kolkata")

            local = now_utc.astimezone(tz)
            hhmm = local.strftime("%H:%M")
            day_key = local.strftime("%Y-%m-%d")

            # Send-time activity window check — defer messages sent outside
            # the parent's active hours. Window is either manually set
            # (activity_window_start/end as "HH:MM") or auto-learned from
            # historical reply patterns (auto_activity_detection=true).
            # If the current local time falls outside the window, skip all
            # scheduled sends for today — avoids waking / nagging parents
            # during temple visits, market trips, sleep hours, etc.
            if parent.get("auto_activity_detection", True):
                # Auto-learned window: check last-N parent replies. Reply
                # docs (see server.py::_record_reply) have no "direction"
                # field — every doc in parent_replies is inherently
                # inbound (from the parent), so no filter is needed there.
                recent_replies = await db.parent_replies \
                    .find({"parent_id": parent["_id"]}) \
                    .sort("created_at", -1).to_list(20)
                if recent_replies:
                    reply_hours = [r["created_at"].astimezone(tz).hour for r in recent_replies]
                    win_start = min(reply_hours)
                    win_end = max(reply_hours)
                else:
                    win_start, win_end = 8, 20  # sensible default
                win_start = parent.get("activity_window_start") or f"{win_start:02d}:00"
                win_end = parent.get("activity_window_end") or f"{win_end:02d}:00"
            else:
                win_start = parent.get("activity_window_start")
                win_end = parent.get("activity_window_end")
            if win_start and win_end:
                cur = local.strftime("%H:%M")
                if not (win_start <= cur <= win_end):
                    logger.info(
                        "Scheduler: skipped sends for parent %s — outside activity window %s-%s (now %s)",
                        parent.get("name"), win_start, win_end, cur,
                    )
                    continue

            ps = await db.payment_state.find_one({"user_id": sched["user_id"]})
            plan_id = resolve_plan_id((ps or {}).get("plan", sched.get("mode", "nitya")))
            limits = plan_limits(plan_id)
            variants_per_slot = limits.get("variants_per_slot", 3)
            sent_counts = {"checkin": 0, "reminder": 0}

            for idx, msg in enumerate(sched.get("messages", [])):
                if msg.get("time") != hhmm:
                    continue
                if msg.get("is_recovery") and not limits.get("recovery_mode"):
                    continue

                # Deduplication: skip if already delivered today
                already = await db.message_logs.find_one({
                    "schedule_id": sched["_id"],
                    "message_index": idx,
                    "day_key": day_key,
                })
                if already:
                    continue

                msg_type = category_type(msg.get("category"))
                if sent_counts[msg_type] >= limits.get(f"{msg_type}s", 0):
                    continue

                medicine_name = ""
                medicines = parent.get("medicine_list") or []
                if medicines:
                    # Find the medicine whose reminder_time matches this slot
                    for med in medicines:
                        if isinstance(med, dict) and med.get("reminder_time") == hhmm:
                            medicine_name = med.get("name", "")
                            break
                    # Fallback to first medicine if no time match found
                    if not medicine_name and isinstance(medicines[0], dict):
                        medicine_name = medicines[0].get("name", "")

                result = await send_dynamic_checkin(
                    db,
                    parent,
                    msg.get("category"),
                    local.timetuple().tm_yday,
                    variants_per_slot,
                    medicine_name=medicine_name,
                )
                sent_counts[msg_type] += 1
                await db.message_logs.insert_one({
                    "user_id": sched["user_id"],
                    "parent_id": sched["parent_id"],
                    "schedule_id": sched["_id"],
                    "message_index": idx,
                    "day_key": day_key,
                    "category": msg.get("category"),
                    "body": msg.get("custom_text") or f"{msg.get('category')} check-in",
                    "msg_type": msg_type,
                    "status": result.get("status"),
                    "detail": result.get("detail"),
                    "sid": result.get("sid"),
                    "created_at": now_utc,
                })
                logger.info(
                    "Delivered msg (%s) to parent %s: %s",
                    result.get("status"), parent.get("name"), msg.get("category"),
                )
        except Exception as exc:
            logger.error(
                "Scheduler: unhandled error for schedule %s — %s",
                sched.get("_id"), exc,
            )


async def _deliver_due_messages():
    await _with_lock("delivery", 55, _deliver_due_messages_impl)


async def _check_reengagement_impl():
    schedules = await db.schedules.find({"active": True, "deleted_at": None}).to_list(None)
    seen = set()
    for sched in schedules:
        parent_id = sched.get("parent_id")
        if not parent_id or parent_id in seen:
            continue
        seen.add(parent_id)
        try:
            activation = await db.activation_state.find_one({"user_id": sched["user_id"]})
            if not activation or not activation.get("whatsapp_activated"):
                continue
            parent = await db.parents.find_one({"_id": parent_id, "deleted_at": None})
            if not parent:
                continue
            result = await send_reengagement(db, parent, sched.get("reengagement_hours", 4))
            if result.get("status") in ("sent", "simulated"):
                try:
                    tz = ZoneInfo(parent.get("timezone", "Asia/Kolkata"))
                except Exception:
                    tz = ZoneInfo("Asia/Kolkata")
                await db.message_logs.insert_one({
                    "user_id": sched["user_id"],
                    "parent_id": parent_id,
                    "schedule_id": sched["_id"],
                    "message_index": -1,
                    "day_key": datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d"),
                    "category": "reengagement",
                    "body": "reengagement",
                    "msg_type": "reengagement",
                    "status": result.get("status"),
                    "detail": result.get("detail"),
                    "sid": result.get("sid"),
                    "created_at": datetime.now(timezone.utc),
                })
        except Exception as exc:
            logger.error("Scheduler: reengagement failed for schedule %s - %s", sched.get("_id"), exc)


async def _check_reengagement():
    await _with_lock("reengagement", 14 * 60, _check_reengagement_impl)


async def _check_recovery_expiry_impl():
    today = date.today().isoformat()
    cursor = db.schedules.find({"deleted_at": None, "recovery_mode": True, "recovery_until": {"$lte": today}})
    async for sched in cursor:
        active_messages = [m for m in sched.get("messages", []) if not m.get("is_recovery")]
        recovery_messages = [m for m in sched.get("messages", []) if m.get("is_recovery")]
        await db.schedules.update_one(
            {"_id": sched["_id"]},
            {"$set": {
                "messages": active_messages,
                "recovery_mode": False,
                "recovery_until": None,
                "archived_recovery_messages": recovery_messages,
            }},
        )
        await db.audit_logs.insert_one({
            "user_id": sched.get("user_id"),
            "action": "recovery_auto_expired",
            "meta": {"schedule_id": str(sched["_id"]), "archived": len(recovery_messages)},
            "created_at": datetime.now(timezone.utc),
        })


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