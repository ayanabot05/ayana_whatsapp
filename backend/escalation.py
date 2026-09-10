
"""
escalation.py — AYANA Care Watch — NEW 2-WINDOW LOGIC (User request)

User spec:
- Day = 6am to 10pm active (16h), 10pm to 6am silent (default, configurable via activity_window)
- Window 1: 6am-2pm (8h) -> if no reply to morning messages, at 2pm send 1st warning to child: "Mom/Dad didn't reply, we sent another message" + nudge parent
- Window 2: 2pm-10pm (8h) -> if still no reply from morning, at 10pm send MAIN warning to child: "Mom/Dad did not reply from morning"
- Silent: 10pm-6am no messages (respects activity_window_start/end if user changed)

This replaces old 24h silence logic.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

from database import get_pool
from whatsapp import send_whatsapp, send_dynamic_checkin

logger = logging.getLogger("ayana.escalation")

# Configurable via env, defaults per user spec
DAY_START_HOUR = int(__import__("os").environ.get("AYANA_DAY_START_HOUR", "6"))   # 6am
FIRST_WARN_HOUR = int(__import__("os").environ.get("AYANA_FIRST_WARN_HOUR", "14")) # 2pm
MAIN_WARN_HOUR = int(__import__("os").environ.get("AYANA_MAIN_WARN_HOUR", "22"))  # 10pm
DAY_END_HOUR = int(__import__("os").environ.get("AYANA_DAY_END_HOUR", "22"))      # 10pm active end, after that silent

NUDGE_AFTER_MIN = 120
MAX_RESEND_ATTEMPTS = 1

BIRTHDAY_WISH = {
    "en": "🎂💛 Happy Birthday, {name}! Wishing you health, laughter and love today. Your family is thinking of you.",
    "te": "🎂💛 పుట్టినరోజు శుభాకాంక్షలు, {name}! ఈరోజు మీకు ఆరోగ్యం, ఆనందం, ప్రేమ కలగాలని కోరుకుంటున్నాం. మీ కుటుంబం మిమ్మల్ని తలచుకుంటోంది.",
    "hi": "🎂💛 जन्मदिन मुबारक हो, {name}! आज आपको सेहत, हँसी और प्यार मिले। आपका परिवार आपको याद कर रहा है।",
}

# First warning at 2pm
_FIRST_WARN_TO_PARENT = {
    "en": "{name}, we missed you this morning. Just checking in again 💛 Are you okay?",
    "te": "{name}, ఈ ఉదయం మీ నుండి వార్త లేదు. మళ్ళీ చెక్ చేస్తున్నాం 💛 బాగున్నారా?",
    "hi": "{name}, आज सुबह आपसे बात नहीं हुई। फिर से चेक कर रहे हैं 💛 आप ठीक हैं?",
}

_FIRST_WARN_TO_CHILD = {
    "en": "💛 {name} didn't reply this morning (6am-2pm). We just sent another check-in. We'll update you at 10pm if still no reply.",
    "te": "💛 {name} ఈ ఉదయం (6am-2pm) స్పందించలేదు. మేము మళ్ళీ చెక్-ఇన్ పంపాము. 10pm వరకు స్పందన లేకపోతే మీకు తెలియజేస్తాము.",
    "hi": "💛 {name} ने आज सुबह (6am-2pm) जवाब नहीं दिया। हमने दोबारा चेक-इन भेजा है। रात 10 बजे तक जवाब नहीं आया तो आपको बताएंगे।",
}

# Main warning at 10pm
_MAIN_WARN_TO_CHILD = {
    "en": "⚠️ {name} didn't reply at all today (since morning 6am). Please consider calling. Missed {count} check-ins.",
    "te": "⚠️ {name} ఈరోజు ఉదయం 6గంటల నుండి అస్సలు స్పందించలేదు. దయచేసి కాల్ చేయండి. {count} చెక్-ఇన్లు మిస్ అయ్యాయి.",
    "hi": "⚠️ {name} ने आज सुबह 6 बजे से बिल्कुल जवाब नहीं दिया। कृपया कॉल करें। {count} चेक-इन मिस हुए।",
}

_SILENCE_SOFT_PING = {
    "en": "{name}, we haven't heard from you today. Everything okay? 💛",
    "te": "{name}, ఈరోజు మీ వార్త ఏమీ లేదు. అంతా బాగుంది కదా? 💛",
    "hi": "{name}, आज आपकी कोई ख़बर नहीं मिली। सब ठीक है न? 💛",
}

FESTIVALS = {
    "01-01": {"en": "🎉 Happy New Year, {name}! May this year be gentle and joyful for you. 💛",
              "te": "🎉 నూతన సంవత్సర శుభాకాంక్షలు, {name}! ఈ సంవత్సరం మీకు ప్రశాంతంగా, ఆనందంగా గడవాలి. 💛",
              "hi": "🎉 नववर्ष की शुभकामनाएँ, {name}! यह वर्ष आपके लिए सुखद हो। 💛"},
}

def _aware(dt):
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def _parse_jsonb_field(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value

async def _has_reply_since(conn, parent_id, since_dt) -> bool:
    row = await conn.fetchrow(
        "select 1 from parent_replies where parent_id = $1 and created_at >= $2 order by created_at desc limit 1",
        parent_id, since_dt,
    )
    return row is not None

async def _count_replies_since(conn, parent_id, since_dt) -> int:
    return await conn.fetchval(
        "select count(*) from parent_replies where parent_id = $1 and created_at >= $2",
        parent_id, since_dt,
    ) or 0

async def _notify_child(conn, user_id, parent, text: str, template_type: str = "silence", parent_name: str = "", missed_count: int = 0, lang: str = "en"):
    """
    PERMANENT FIX: Uses TEMPLATES for child warnings - works OUTSIDE 24h window
    template_type: "first_warn" (2pm) or "main_warn" (10pm) or "silence"
    """
    try:
        owner = await conn.fetchrow("select * from users where id = $1::uuid", user_id)
        members = await conn.fetch(
            "select * from users where household_owner_id = $1::uuid and deleted_at is null limit 20",
            user_id,
        )
        phones = []
        phone_langs = {}
        for r in ([owner] if owner else []) + list(members):
            if r and r.get("phone"):
                phones.append(r["phone"])
                phone_langs[r["phone"]] = r.get("language") or parent.get("language") or lang
        
        emergency_contacts = _parse_jsonb_field(parent.get("emergency_contacts"), [])
        for c in emergency_contacts:
            if isinstance(c, dict) and c.get("phone"):
                phones.append(c["phone"])
                phone_langs[c["phone"]] = parent.get("language") or lang
        
        unique_phones = list(dict.fromkeys(phones))
        for p in unique_phones:
            try:
                p_lang = phone_langs.get(p, lang)
                # Try template first (works outside 24h window)
                try:
                    from whatsapp import send_first_warning_to_child, send_main_warning_to_child
                    if template_type == "first_warn":
                        res = await send_first_warning_to_child(p, p_lang, parent_name)
                        if res.get("status") == "sent":
                            logger.info("[escalation] First warn TEMPLATE sent to child %s", p)
                            continue
                    elif template_type == "main_warn":
                        res = await send_main_warning_to_child(p, p_lang, parent_name, missed_count)
                        if res.get("status") == "sent":
                            logger.info("[escalation] Main warn TEMPLATE sent to child %s", p)
                            continue
                except Exception as e:
                    logger.warning("[escalation] template send failed, fallback to plain: %s", e)
                
                # Fallback: plain text (needs 24h window)
                await asyncio.to_thread(send_whatsapp, p, text)
            except Exception as e:
                logger.warning("[escalation] notify %s failed: %s", p, e)
    except Exception as e:
        logger.error("[escalation] _notify_child failed: %s", e, exc_info=True)

_REMINDER_CATEGORIES = {"medicine", "water", "bp_check", "sugar_check", "health_check"}

def _is_in_active_window(local_time, win_start_str, win_end_str):
    """Check if local time is within user's activity window (default 6am-10pm)"""
    try:
        # Parse window like "06:00" and "22:00"
        sh, sm = map(int, (win_start_str or "06:00").split(":")[:2])
        eh, em = map(int, (win_end_str or "22:00").split(":")[:2])
        start = dtime(sh, sm)
        end = dtime(eh, em)
        cur = local_time.time()
        if start <= end:
            return start <= cur <= end
        else: # overnight window
            return cur >= start or cur <= end
    except Exception:
        # default 6am-10pm active
        cur = local_time.time()
        return dtime(6,0) <= cur <= dtime(22,0)

async def run_care_watch_impl():
    now = datetime.now(timezone.utc)

    try:
        async with get_pool().acquire() as conn:
            parents = await conn.fetch("select * from parents where deleted_at is null")
    except Exception as e:
        logger.error("[escalation] Failed to fetch parents: %s", e, exc_info=True)
        return

    for parent in parents:
        try:
            async with get_pool().acquire() as conn:
                activation = await conn.fetchrow("select * from activation_state where user_id = $1", parent["user_id"])
                if not activation or not activation.get("whatsapp_activated"):
                    continue

                try:
                    tz = ZoneInfo(parent.get("timezone") or "Asia/Kolkata")
                except Exception:
                    tz = ZoneInfo("Asia/Kolkata")
                
                local = now.astimezone(tz)
                day_key = local.strftime("%Y-%m-%d")
                user_id = parent["user_id"]
                parent_id = parent["id"]
                lang = parent.get("language") or "en"
                preferred = parent.get("preferred_name") or parent.get("name") or "Amma"
                pname = parent.get("name") or "your parent"

                # Respect user's activity window (default 6am-10pm)
                win_start = parent.get("activity_window_start") or f"{DAY_START_HOUR:02d}:00"
                win_end = parent.get("activity_window_end") or f"{DAY_END_HOUR:02d}:00"
                
                # Silent mode: 10pm-6am (outside active window) -> skip all warnings
                if not _is_in_active_window(local, win_start, win_end):
                    continue

                # Define day boundaries in UTC for queries
                # 6am local today -> convert to UTC
                day_start_local = local.replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0)
                first_warn_local = local.replace(hour=FIRST_WARN_HOUR, minute=0, second=0, microsecond=0)
                main_warn_local = local.replace(hour=MAIN_WARN_HOUR, minute=0, second=0, microsecond=0)
                
                day_start_utc = day_start_local.astimezone(timezone.utc)
                first_warn_utc = first_warn_local.astimezone(timezone.utc)
                main_warn_utc = main_warn_local.astimezone(timezone.utc)

                # ---- 1) Retry unanswered check-ins (2h nudge) - keep existing ----
                logs = await conn.fetch(
                    """select * from message_logs where parent_id = $1 and day_key = $2 and msg_type in ('checkin', 'reminder') and status in ('sent', 'simulated') limit 200""",
                    parent_id, day_key,
                )
                for log in logs:
                    try:
                        base = _aware(log["created_at"])
                        if not base:
                            continue
                        if await _has_reply_since(conn, parent_id, base):
                            continue
                        state = await conn.fetchrow("select * from escalation_state where id = $1", str(log["id"]))
                        attempts = state["attempts"] if state else 0
                        if attempts >= MAX_RESEND_ATTEMPTS:
                            continue
                        due_at = base + timedelta(minutes=NUDGE_AFTER_MIN)
                        if now < due_at:
                            continue
                        category = log["category"] or "how_feeling"
                        result = await send_dynamic_checkin(dict(parent), category, local.timetuple().tm_yday, 7, medicine_name="")
                        kind = "reminder" if category in _REMINDER_CATEGORIES else "checkin"
                        async with conn.transaction():
                            await conn.execute(
                                """insert into escalation_state (id, parent_id, user_id, attempts, last_attempt_at, kind, day_key, first_at) values ($1, $2, $3, $4, $5, $6, $7, now()) on conflict (id) do update set attempts = excluded.attempts, last_attempt_at = excluded.last_attempt_at, kind = excluded.kind, day_key = excluded.day_key""",
                                str(log["id"]), parent_id, user_id, attempts + 1, now, kind, day_key,
                            )
                            await conn.execute(
                                """insert into message_logs (user_id, parent_id, schedule_id, day_key, category, msg_type, status, escalation_of, attempt, kind, sid, created_at) values ($1, $2, NULL, $3, $4, 'escalation', $5, $6, $7, $8, $9, $10)""",
                                user_id, parent_id, day_key, category, (result or {}).get("status"), log["id"], attempts + 1, kind, (result or {}).get("sid"), now,
                            )
                        logger.info("[escalation] retry #%d -> %s (%s)", attempts + 1, parent.get("name"), category)
                    except Exception as e:
                        logger.error("[escalation] retry failed for log %s: %s", log.get("id"), e, exc_info=True)
                        continue

                # ---- 2) FIRST WARNING at 2pm (6am-2pm window no reply) ----
                # Trigger at 14:00-14:10 local (scheduler runs every 5 min)
                if local.hour == FIRST_WARN_HOUR and local.minute < 10:
                    try:
                        marker = f"{parent_id}:{day_key}:first_warn_14h"
                        # Check if already sent today
                        exists = await conn.fetchval("select 1 from escalation_daily where marker = $1", marker)
                        if not exists:
                            # Has parent replied since 6am today?
                            replies_since_morning = await _count_replies_since(conn, parent_id, day_start_utc)
                            if replies_since_morning == 0:
                                # No reply since morning 6am -> send first warning
                                # Count scheduled today morning
                                scheduled_morning = await conn.fetchval(
                                    """select count(*) from message_logs where parent_id = $1 and day_key = $2 and created_at >= $3 and created_at < $4 and msg_type in ('checkin','reminder')""",
                                    parent_id, day_key, day_start_utc, first_warn_utc,
                                )
                                if scheduled_morning and scheduled_morning > 0:
                                    # 1. Nudge parent again
                                    soft_parent = _FIRST_WARN_TO_PARENT.get(lang, _FIRST_WARN_TO_PARENT["en"]).format(name=preferred)
                                    await asyncio.to_thread(send_whatsapp, parent.get("phone") or "", soft_parent)
                                    # 2. Warn child
                                    child_text = _FIRST_WARN_TO_CHILD.get(lang, _FIRST_WARN_TO_CHILD["en"]).format(name=pname)
                                    await _notify_child(conn, user_id, parent, child_text, template_type="first_warn", parent_name=pname, lang=lang)
                                    # Mark as sent
                                    await conn.execute("insert into escalation_daily (marker, at) values ($1, now()) on conflict (marker) do nothing", marker)
                                    logger.info("[escalation] FIRST warning (2pm) sent for %s - no reply since 6am, %s msgs missed", pname, scheduled_morning)
                    except Exception as e:
                        logger.error("[escalation] first warn check failed for %s: %s", parent_id, e, exc_info=True)

                # ---- 3) MAIN WARNING at 10pm (no reply whole day since 6am) ----
                # Trigger at 22:00-22:10 local
                if local.hour == MAIN_WARN_HOUR and local.minute < 10:
                    try:
                        marker = f"{parent_id}:{day_key}:main_warn_22h"
                        exists = await conn.fetchval("select 1 from escalation_daily where marker = $1", marker)
                        if not exists:
                            replies_since_morning = await _count_replies_since(conn, parent_id, day_start_utc)
                            if replies_since_morning == 0:
                                scheduled_today = await conn.fetchval(
                                    """select count(*) from message_logs where parent_id = $1 and day_key = $2 and created_at >= $3 and created_at < $4 and msg_type in ('checkin','reminder','escalation')""",
                                    parent_id, day_key, day_start_utc, main_warn_utc,
                                )
                                if scheduled_today and scheduled_today > 0:
                                    child_text = _MAIN_WARN_TO_CHILD.get(lang, _MAIN_WARN_TO_CHILD["en"]).format(name=pname, count=scheduled_today)
                                    await _notify_child(conn, user_id, parent, child_text, template_type="main_warn", parent_name=pname, missed_count=scheduled_today, lang=lang)
                                    await conn.execute("insert into escalation_daily (marker, at) values ($1, now()) on conflict (marker) do nothing", marker)
                                    logger.info("[escalation] MAIN warning (10pm) sent for %s - no reply whole day, %s msgs missed", pname, scheduled_today)
                    except Exception as e:
                        logger.error("[escalation] main warn check failed for %s: %s", parent_id, e, exc_info=True)

                # ---- 4) Birthday + festival (keep existing) ----
                try:
                    mmdd = local.strftime("%m-%d")
                    ymd = local.strftime("%Y-%m-%d")
                    greet = None
                    bday = (parent.get("birthday") or "").strip()
                    if bday:
                        bday_mmdd = bday[-5:] if len(bday) >= 5 else bday
                        if bday_mmdd == mmdd:
                            greet = BIRTHDAY_WISH.get(lang, BIRTHDAY_WISH["en"]).format(name=preferred)
                    if greet:
                        marker = f"{parent_id}:{day_key}:greet"
                        inserted = await conn.fetchval(
                            """insert into escalation_daily (marker, at) values ($1, now()) on conflict (marker) do nothing returning marker""",
                            marker,
                        )
                        if inserted:
                            await asyncio.to_thread(send_whatsapp, parent.get("phone") or "", greet)
                            logger.info("[escalation] birthday wish sent to %s", parent.get("name"))
                except Exception as e:
                    logger.error("[escalation] greet check failed for parent %s: %s", parent_id, e, exc_info=True)

        except Exception as exc:
            logger.error("[escalation] unhandled error for parent %s — %s", parent.get("id"), exc, exc_info=True)
            continue

