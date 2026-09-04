"""
escalation.py — AYANA "Care Watch" engine.

Runs on a short interval (locked, like the other scheduler jobs) and does
three things, all timezone-aware to the parent's local day:

1. RETRY unanswered check-ins / medicine reminders
     • Both check-ins and medicine reminders: resend every 30 min,
       up to 2 hours (4 tries total: original + 3 retries).
     • A reply of any kind (button tap / text / voice) after the
       original send resolves it and stops the nagging.

2. AFTERNOON no-response warning to the child
   If, by the parent's local afternoon, they haven't replied to ANY of the
   day's messages (and at least one went out), the child + Care Circle +
   emergency contacts get a gentle "they haven't replied yet" alert. Once/day.

3. BIRTHDAY + FESTIVAL auto-wishes to the parent, in their language. Once/day.

MIGRATION NOTE: Mongo's `insert_one` + catch `DuplicateKeyError` pattern
(used for the once-a-day markers) is replaced by Postgres's native
`ON CONFLICT DO NOTHING`, which reports whether a row was actually
inserted instead of relying on an exception.
"""

import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from database import get_pool
from whatsapp import send_whatsapp, send_medicine_template, send_dynamic_checkin

logger = logging.getLogger("ayana.escalation")

AFTERNOON_HOUR = 14          # local hour after which the no-reply warning fires
# Unified retry cadence: every check-in AND medicine reminder that goes
# unanswered is retried every 30 minutes for up to 2 hours.
# That means 4 sends total (original + 3 retries at +30/+60/+90/+120).
RETRY_INTERVAL_MIN = 30
RETRY_WINDOW_MIN = 120       # 2-hour window → 4 attempts total
MAX_RESEND_ATTEMPTS = RETRY_WINDOW_MIN // RETRY_INTERVAL_MIN  # = 4, but capped at 3 retries above original

BIRTHDAY_WISH = {
    "en": "🎂💛 Happy Birthday, {name}! Wishing you health, laughter and love today. Your family is thinking of you.",
    "te": "🎂💛 పుట్టినరోజు శుభాకాంక్షలు, {name}! ఈరోజు మీకు ఆరోగ్యం, ఆనందం, ప్రేమ కలగాలని కోరుకుంటున్నాం. మీ కుటుంబం మిమ్మల్ని తలచుకుంటోంది.",
    "hi": "🎂💛 जन्मदिन मुबारक हो, {name}! आज आपको सेहत, हँसी और प्यार मिले। आपका परिवार आपको याद कर रहा है।",
}

FESTIVALS = {
    "01-01": {"en": "🎉 Happy New Year, {name}! May this year be gentle and joyful for you. 💛",
              "te": "🎉 నూతన సంవత్సర శుభాకాంక్షలు, {name}! ఈ సంవత్సరం మీకు ప్రశాంతంగా, ఆనందంగా గడవాలి. 💛",
              "hi": "🎉 नववर्ष की शुभकामनाएँ, {name}! यह वर्ष आपके लिए सुखद हो। 💛"},
    "01-14": {"en": "🌾☀️ Happy Sankranti / Pongal, {name}! Wishing you warmth and sweetness today. 💛",
              "te": "🌾☀️ సంక్రాంతి శుభాకాంక్షలు, {name}! ఈ పండుగ మీకు ఆనందాన్ని తీసుకురావాలి. 💛",
              "hi": "🌾☀️ मकर संक्रांति की शुभकामनाएँ, {name}! 💛"},
    "08-15": {"en": "🇮🇳 Happy Independence Day, {name}! 💛",
              "te": "🇮🇳 స్వాతంత్ర్య దినోత్సవ శుభాకాంక్షలు, {name}! 💛",
              "hi": "🇮🇳 स्वतंत्रता दिवस की शुभकामनाएँ, {name}! 💛"},
}

_HOLI = {"en": "🌈 Happy Holi, {name}! May your days be full of colour and joy. 💛",
         "te": "🌈 హోళీ శుభాకాంక్షలు, {name}! మీ జీవితం రంగులతో నిండాలి. 💛",
         "hi": "🌈 होली की शुभकामनाएँ, {name}! आपका जीवन रंगों से भरा रहे। 💛"}
_DIWALI = {"en": "🪔✨ Happy Diwali, {name}! Wishing you light, health and happiness this festive season. 💛",
           "te": "🪔✨ దీపావళి శుభాకాంక్షలు, {name}! ఈ పండుగ మీకు వెలుగు, ఆరోగ్యం, ఆనందం తీసుకురావాలి. 💛",
           "hi": "🪔✨ दीपावली की शुभकामनाएँ, {name}! यह पर्व आपके जीवन में उजाला लाए। 💛"}
LUNAR_FESTIVALS = {
    "2025-03-14": _HOLI, "2025-10-20": _DIWALI,
    "2026-03-04": _HOLI, "2026-11-08": _DIWALI,
    "2027-03-22": _HOLI, "2027-10-28": _DIWALI,
}


def _aware(dt):
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _has_reply_since(conn, parent_id, since_dt) -> bool:
    row = await conn.fetchrow(
        "select 1 from parent_replies where parent_id = $1 and created_at >= $2 limit 1",
        parent_id, since_dt,
    )
    return row is not None


async def _notify_child(conn, user_id, parent, text: str):
    """Alert owner + Care Circle members + emergency contacts."""
    owner = await conn.fetchrow("select * from users where id = $1::uuid", user_id)
    members = await conn.fetch(
        "select * from users where household_owner_id = $1::uuid and deleted_at is null limit 20",
        user_id,
    )
    phones = []
    for r in ([owner] if owner else []) + list(members):
        if r and r["phone"]:
            phones.append(r["phone"])
    for c in (parent["emergency_contacts"] or []):
        if c.get("phone"):
            phones.append(c["phone"])
    for p in dict.fromkeys(phones):  # de-dupe, keep order
        try:
            send_whatsapp(p, text)
        except Exception as e:
            logger.warning("[escalation] notify %s failed: %s", p, e)


async def run_care_watch_impl():
    now = datetime.now(timezone.utc)

    async with get_pool().acquire() as conn:
        schedules = await conn.fetch(
            "select * from schedules where active = true and deleted_at is null"
        )

        for sched in schedules:
            parent = await conn.fetchrow(
                "select * from parents where id = $1", sched["parent_id"]
            )
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
            local = now.astimezone(tz)
            day_key = local.strftime("%Y-%m-%d")
            day_index = local.timetuple().tm_yday
            user_id = sched["user_id"]
            parent_id = parent["id"]
            lang = parent["language"] or "en"
            preferred = parent["preferred_name"] or parent["name"] or "Amma"

            # ---- 1) Retry unanswered check-ins / medicine reminders ----
            logs = await conn.fetch(
                """
                select * from message_logs
                where parent_id = $1 and day_key = $2
                  and msg_type in ('checkin', 'reminder')
                  and status in ('sent', 'simulated')
                limit 200
                """,
                parent_id, day_key,
            )
            for log in logs:
                base = _aware(log["created_at"])
                if not base:
                    continue
                interval = RETRY_INTERVAL_MIN
                window = RETRY_WINDOW_MIN
                max_attempts = MAX_RESEND_ATTEMPTS
                elapsed_min = (now - base).total_seconds() / 60
                if elapsed_min > window:
                    continue  # 2-hour window closed — give up
                if await _has_reply_since(conn, parent_id, base):
                    continue  # answered — stop nagging
                state = await conn.fetchrow(
                    "select * from escalation_state where id = $1", str(log["id"])
                )
                attempts = state["attempts"] if state else 0
                if attempts >= max_attempts:
                    continue
                due_at = base + timedelta(minutes=interval * (attempts + 1))
                if now < due_at:
                    continue

                category = log["category"] or "how_feeling"
                msg_type = log["msg_type"] or "checkin"
                kind = "medicine" if msg_type == "reminder" else "checkin"

                if kind == "medicine":
                    result = await send_medicine_template(parent, day_index, 7, "")
                else:
                    result = await send_dynamic_checkin(parent, category, day_index, 7, "")

                await conn.execute(
                    """
                    insert into escalation_state (id, parent_id, user_id, attempts,
                                                   last_attempt_at, kind, day_key, first_at)
                    values ($1, $2, $3, $4, $5, $6, $7, now())
                    on conflict (id) do update
                        set attempts = excluded.attempts,
                            last_attempt_at = excluded.last_attempt_at,
                            kind = excluded.kind,
                            day_key = excluded.day_key
                    """,
                    str(log["id"]), parent_id, user_id, attempts + 1, now, kind, day_key,
                )
                await conn.execute(
                    """
                    insert into message_logs (user_id, parent_id, schedule_id, day_key, category,
                                               msg_type, status, escalation_of, attempt, kind, created_at)
                    values ($1, $2, $3, $4, $5, 'escalation', $6, $7, $8, $9, $10)
                    """,
                    user_id, parent_id, sched["id"], day_key, category,
                    (result or {}).get("status"), log["id"], attempts + 1, kind, now,
                )
                logger.info("[escalation] %s retry #%d -> %s (%s)", kind, attempts + 1, parent["name"], category)

            # ---- 2) Afternoon no-response warning ----
            if local.hour >= AFTERNOON_HOUR:
                day_start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
                day_start_utc = day_start_local.astimezone(timezone.utc)
                sent_today = await conn.fetchval(
                    """
                    select count(*) from message_logs
                    where parent_id = $1 and day_key = $2 and status in ('sent', 'simulated')
                    """,
                    parent_id, day_key,
                )
                if sent_today > 0 and not await _has_reply_since(conn, parent_id, day_start_utc):
                    marker = f"{parent_id}:{day_key}:noreply"
                    inserted = await conn.fetchval(
                        """
                        insert into escalation_daily (marker, at) values ($1, now())
                        on conflict (marker) do nothing
                        returning marker
                        """,
                        marker,
                    )
                    if inserted:
                        pname = parent["name"] or "your parent"
                        await _notify_child(
                            conn, user_id, parent,
                            f"⚠️ {pname} hasn't replied to any of today's check-ins yet. "
                            f"You may want to give them a call to make sure all is well. — AYANA 💛",
                        )
                        logger.info("[escalation] afternoon no-reply warning sent for %s", pname)

            # ---- 3) Birthday + festival auto-wish ----
            mmdd = local.strftime("%m-%d")
            ymd = local.strftime("%Y-%m-%d")
            greet = None
            if parent["birthday"] == mmdd:
                greet = BIRTHDAY_WISH.get(lang, BIRTHDAY_WISH["en"]).format(name=preferred)
            elif ymd in LUNAR_FESTIVALS:
                greet = LUNAR_FESTIVALS[ymd].get(lang, LUNAR_FESTIVALS[ymd]["en"]).format(name=preferred)
            elif mmdd in FESTIVALS:
                greet = FESTIVALS[mmdd].get(lang, FESTIVALS[mmdd]["en"]).format(name=preferred)
            if greet:
                marker = f"{parent_id}:{day_key}:greet"
                inserted = await conn.fetchval(
                    """
                    insert into escalation_daily (marker, at) values ($1, now())
                    on conflict (marker) do nothing
                    returning marker
                    """,
                    marker,
                )
                if inserted:
                    send_whatsapp(parent["phone"] or "", greet)
                    logger.info("[escalation] festival/birthday wish sent to %s", parent["name"])