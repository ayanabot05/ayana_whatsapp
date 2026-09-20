"""AYANA webhook; extracted without changing API behaviour."""
import asyncio
import asyncpg
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import Depends, APIRouter, HTTPException, Request, Response, BackgroundTasks
from database import get_pool
from models import MarkRepliesReadInput, SimulateReplyInput
from services import notifications, inbox
from services.delivery_stats import delivery_funnel as _delivery_funnel_shared
from services.reply_media import archive_audio
from auth import serialize, get_current_user, validate_csrf_token
from sarvam_stt import transcribe_voice_note_detailed, confidence_label
from distress_detection import assess_transcript
from whatsapp import detect_emergency, parse_intent, refresh_session, send_whatsapp, verify_meta_signature, resolve_meta_media_url, meta_auth_header, whatsapp_enabled
from services.deps import scope


logger = logging.getLogger("ayana")

router = APIRouter()


# ---------------- Parent replies ----------------
FEELING_MAP = {
    "good": {"emoji": "😊", "label": {"en": "Good", "te": "బాగున్నారు", "hi": "ठीक हैं"}},
    "okay": {"emoji": "😐", "label": {"en": "Okay", "te": "ఫర్వాలేదు", "hi": "ठीक-ठाक"}},
    "not_well": {"emoji": "😟", "label": {"en": "Not well", "te": "ఒంట్లో బాలేదు", "hi": "तबीयत ठीक नहीं"}},
    "done": {"emoji": "✅", "label": {"en": "Done", "te": "అయ్యింది", "hi": "हो गया"}},
}
_GOOD = ["1", "good", "fine", "great", "బాగున్నా", "బాగుంది", "ठीक हूँ", "अच्छा"]
_OKAY = ["2", "okay", "ok", "theek", "ఫర్వాలేదు", "పర్వాలేదు", "పరవాలేదు", "ठीक-ठाक", "ठीक ठाक", "ठीक है"]
_BAD = ["3", "not well", "sick", "bad", "ఒంట్లో బాలేదు", "బాలేదు", "బాగోలేదు", "तबीयत ठीक नहीं", "ठीक नहीं", "बीमार"]
_DONE = ["yes", "done", "అయ్యింది", "వేసుకున్నా", "हो गया", "ले लिया"]


def _word_in(text: str, keywords: list[str]) -> bool:
    t_lower = text.lower()
    for kw in keywords:
        if kw.isascii():
            if re.search(r"\b" + re.escape(kw) + r"\b", t_lower, re.IGNORECASE):
                return True
        else:
            if kw.lower() in t_lower:
                return True
    return False


def parse_reply(text: str) -> str | None:
    if not text:
        return None
    t = text.strip()
    if _word_in(t, _BAD):
        return "not_well"
    if _word_in(t, _GOOD):
        return "good"
    if _word_in(t, _OKAY):
        return "okay"
    if _word_in(t, _DONE):
        return "done"
    return None


# Friendly labels for what the parent was replying to (Issue #2), so the
# child sees "Amma · Morning check-in" instead of a bare "Amma replied: good".
_CATEGORY_LABEL = {
    "breakfast": "Breakfast check-in", "lunch": "Lunch check-in", "dinner": "Dinner check-in",
    "afternoon_checkin": "Afternoon check-in", "tea_check": "Tea-time check-in", "walk_check": "Walk check-in",
    "morning": "Morning check-in", "evening": "Evening check-in", "night": "Night check-in",
    "medicine": "Medicine reminder", "water": "Water reminder", "bp_check": "BP check reminder",
    "sugar_check": "Sugar check reminder", "health_check": "Health check reminder",
}


def _prompt_label(last_log) -> str:
    """Human-readable name of the check-in/reminder the parent just answered."""
    if not last_log:
        return "Check-in"
    cat = (last_log["category"] or "").strip()
    if cat in _CATEGORY_LABEL:
        return _CATEGORY_LABEL[cat]
    mtype = (last_log["msg_type"] or "").strip()
    if mtype == "reminder":
        return f"{cat.replace('_', ' ').title()} reminder" if cat else "Reminder"
    if cat:
        return f"{cat.replace('_', ' ').title()} check-in"
    return "Check-in"


def _reply_context_line(intent: str | None, pname: str, subj: str, poss: str) -> str | None:
    """Context-aware one-liner shown under each reply (Phase 2 emotional UX)."""
    if not intent:
        return None
    action, _, category = intent.partition(":")
    if action == "done" and category in _REMINDER_CATEGORIES:
        what = {
            "medicine": f"took {poss} medicine",
            "bp_check": f"did {poss} BP check",
            "sugar_check": f"did {poss} sugar check",
            "water": f"had {poss} water",
            "health_check": f"did {poss} health check",
        }.get(category, "confirmed it")
        return f"{pname} {what}. One less thing to worry about. 💊"
    if action == "skip" and category in _MEAL_CATEGORIES:
        meal = category if category in ("breakfast", "lunch", "dinner") else "this one"
        return f"{pname} skipped {meal}. Maybe give {poss} a call this evening?"
    if action == "feeling" and category == "not_well":
        return f"{pname} isn't feeling great today. {subj} might need to hear your voice."
    return None


async def _notify_family(owner_id, parent, feeling: str | None, is_voice: bool, body: str, keywords: list, ml_flagged: bool = False, media_url: str = None, transcription: str | None = None, stt_confidence: float | None = None, intent: str | None = None, context_id: str | None = None):
    async with get_pool().acquire() as conn:
        owner = await conn.fetchrow("select * from users where id = $1::uuid", owner_id)
        members = await conn.fetch(
            "select * from users where household_owner_id = $1::uuid and deleted_at is null limit 20", owner_id
        )
        # #11: phone-verified care-circle siblings receive the EXACT same
        # forwarded reply + voice note the account owner gets.
        siblings = await conn.fetch(
            "select name, phone, language from care_circle_siblings where owner_id = $1::uuid and verified = true limit 5",
            owner_id,
        )
        last_log = None
        if parent:
            # LABEL FIX: tie the reply to the EXACT message the parent tapped.
            # Meta sends context.id = the wam id of the message being replied
            # to; our outbound sends store that same id in message_logs.sid.
            # Resolving by it prevents mislabelling (e.g. a lunch tap showing
            # as "morning Wish check-in" when several check-ins went out close
            # together). Falls back to the latest log only if we can't match.
            if context_id:
                last_log = await conn.fetchrow(
                    "select category, msg_type, body from message_logs where parent_id = $1::uuid and sid = $2 order by created_at desc limit 1",
                    parent["id"], context_id,
                )
            if last_log is None:
                last_log = await conn.fetchrow(
                    "select category, msg_type, body from message_logs where parent_id = $1::uuid order by created_at desc limit 1",
                    parent["id"],
                )
    recipients = ([owner] if owner else []) + list(members) + list(siblings)
    pname = parent["name"] if parent else "Your parent"
    prompt = _prompt_label(last_log)
    prompt_l = prompt[:1].lower() + prompt[1:]
    subj, poss = ("He", "his") if parent and (parent.get("relationship") or "") == "father" else ("She", "her")
    try:
        tz = ZoneInfo((parent.get("timezone") if parent else None) or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    when = datetime.now(timezone.utc).astimezone(tz).strftime("%I:%M %p").lstrip("0")
    city = (parent.get("city") if parent else "") or ""
    where = f"{when} · {city}" if city else when

    # --- VOICE FORWARD LOGIC with confidence (Issue #1 + #2) ---
    if is_voice and media_url:
        from whatsapp import send_audio_link, download_and_host_voice_note
        hosted_audio_url = await download_and_host_voice_note(media_url, str(parent["id"]) if parent else "unknown")

        is_clear = bool(transcription and transcription.strip() and transcription.strip() != "[voice note]" and len(transcription.strip()) > 2)
        conf_label = confidence_label(stt_confidence) if stt_confidence is not None else ("high" if is_clear else "unknown")
        translated_text = transcription

        # Translate if clear and languages differ
        if is_clear and owner:
            child_lang = (owner.get("language") or "en").lower()[:2]
            parent_lang = (parent.get("language") if parent else "en").lower()[:2]
            if child_lang != parent_lang:
                try:
                    from translation_engine import translate_text
                    translated_text = await translate_text(transcription, target_language=child_lang, source_language=parent_lang)
                except Exception as e:
                    logger.warning(f"[voice] Translation failed: {e}")

        pct = f" (≈{round((stt_confidence or 0) * 100)}% confident)" if stt_confidence is not None else ""
        for r in recipients:
            if not r or not r["phone"]:
                continue
            if hosted_audio_url:
                await send_audio_link(r["phone"], hosted_audio_url)
            if is_clear and conf_label == "high":
                text = f"🎤 {pname} sent you a voice note · {prompt}\n\nTranscript: “{translated_text}”"
            elif is_clear and conf_label == "medium":
                text = f"🎤 {pname} sent you a voice note · {prompt}\n\nWe think {subj.lower()} said{pct} — please listen to confirm:\n“{translated_text}”"
            elif is_clear:  # low confidence but we got some words
                text = f"🎤 {pname} sent you a voice note · {prompt}\n\nRough transcription{pct}, may be inaccurate — please listen:\n“{translated_text}”"
            else:
                text = f"🎤 {pname} sent you a voice note · {prompt}\n\nWe couldn't transcribe it clearly — please listen 💛"
            send_whatsapp(r["phone"], text)
        return

    # --- Text / button replies (Phase 2: emotional, contextual format) ---
    if keywords:
        head = f"🚨 {pname} replied to your {prompt_l} — “{body}”\nMay need attention.\n{where}"
    elif ml_flagged:
        head = f"💛 {pname} sent you a voice note\nWorth checking in — something in it stood out.\n{where}"
    elif is_voice:
        head = f"🎤 {pname} sent you a voice note — transcript: “{body}”\n{where}"
    elif feeling:
        f = FEELING_MAP.get(feeling, {})
        reply_txt = f"{f.get('emoji','')} {f.get('label',{}).get('en', feeling)}".strip()
        head = f"💛 {pname} replied to your {prompt_l} — “{reply_txt}”\n{where}"
    else:
        head = f"💛 {pname} replied to your {prompt_l} — “{body}”\n{where}"
    ctx = _reply_context_line(intent or (f"feeling:{feeling}" if feeling else None), pname, subj, poss)
    if ctx:
        head = f"{head}\n{ctx}"
    for r in recipients:
        if r and r["phone"]:
            send_whatsapp(r["phone"], head)

# ── Generic-payload disambiguation ──────────────────────────────────────
_GENERIC_REMINDER_PAYLOADS = {
    "reminder_done": "done", "reminder_pending": "pending", "reminder_skip": "skip",
}
_GENERIC_MEAL_PAYLOADS = {
    "meal_done": "done", "meal_pending": "pending", "meal_skip": "skip",
}
_REMINDER_CATEGORIES = {"medicine", "water", "bp_check", "sugar_check", "health_check"}
_MEAL_CATEGORIES = {"breakfast", "lunch", "dinner", "afternoon_checkin", "tea_check", "walk_check"}


async def _resolve_generic_button_intent(parent_id, button_payload: str) -> str | None:
    if button_payload in _GENERIC_REMINDER_PAYLOADS:
        action = _GENERIC_REMINDER_PAYLOADS[button_payload]
        category_set = list(_REMINDER_CATEGORIES)
    elif button_payload in _GENERIC_MEAL_PAYLOADS:
        action = _GENERIC_MEAL_PAYLOADS[button_payload]
        category_set = list(_MEAL_CATEGORIES)
    else:
        return None

    async with get_pool().acquire() as conn:
        last_log = await conn.fetchrow(
            """
            select * from message_logs
            where parent_id = $1::uuid and category = any($2::text[])
            order by created_at desc limit 1
            """,
            parent_id, category_set,
        )
    if not last_log:
        logger.warning("[webhook] No recent %s send found for parent %s to resolve %s", category_set, parent_id, button_payload)
        return f"{action}:generic"
    return f"{action}:{last_log['category']}"


# ── #2c: approved-template quick-reply button → intent by TITLE ─────────────
# Meta returns {id, title} for a tapped quick-reply. Our in-session buttons
# carry structured ids ("feeling:good", "done:rest"), but the APPROVED
# TEMPLATE buttons (ayana_mood/medicine/meal) may come back with a non-
# structured id — or an empty id — depending on how they were registered in
# Meta. When that happens we map the localized title the parent actually
# tapped (Good/బాగున్నాను/अच्छा, Taken/వేసుకున్నా/ले लिया, …) to the right
# intent using the SAME multilingual keyword lists the free-text path uses.
_STRUCTURED_INTENT_PREFIXES = ("feeling:", "done:", "pending:", "skip:", "emergency:")

# Localized quick-reply TITLES for reminder confirmations, in en/te/hi — used
# when a tapped template button carries no structured id (#2c). Kept explicit
# (not reusing the free-text lists) because button titles are short and fixed.
_TITLE_DONE_WORDS = [
    "taken", "done", "did it", "వేసుకున్నా", "వేసుకున్నాను", "తీసుకున్నా",
    "తీసుకున్నాను", "అయింది", "ले लिया", "लिया", "ले ली", "हो गया", "कर लिया",
]
_TITLE_SKIP_WORDS = [
    "skip", "not yet", "later", "వద్దు", "లేదు", "ఇంకా లేదు",
    "नहीं", "अभी नहीं", "बाद में", "छोड़",
]


async def _resolve_action_for_category_set(parent_id, action: str, category_set: list[str]) -> str:
    async with get_pool().acquire() as conn:
        last_log = await conn.fetchrow(
            "select category from message_logs where parent_id = $1::uuid and category = any($2::text[]) order by created_at desc limit 1",
            parent_id, category_set,
        )
    return f"{action}:{last_log['category']}" if last_log else f"{action}:generic"


async def _resolve_button_title_intent(parent_id, title: str) -> str:
    t = (title or "").strip()
    if not t:
        return "text"
    tl = t.lower()
    if any(w in tl for w in _TITLE_DONE_WORDS):
        return await _resolve_action_for_category_set(parent_id, "done", list(_REMINDER_CATEGORIES))
    if any(w in tl for w in _TITLE_SKIP_WORDS):
        return await _resolve_action_for_category_set(parent_id, "skip", list(_REMINDER_CATEGORIES))
    fr = parse_reply(t)  # 'good' | 'okay' | 'not_well' | 'done' | None
    if fr in ("good", "okay", "not_well"):
        return f"feeling:{fr}"
    if fr == "done":
        return await _resolve_action_for_category_set(parent_id, "done", list(_REMINDER_CATEGORIES))
    return parse_intent(None, t)


# ── Interactive button handler callbacks ───────────────────────────────────
async def _mark_medicine_status(phone: str, taken: bool):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(_PARENT_BY_PHONE_SQL, phone)
        if not parent:
            return
        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log = await conn.fetchrow(
            """
            select * from message_logs
            where parent_id = $1::uuid and day_key = $2 and msg_type = 'reminder'
              and category = any($3::text[])
            order by created_at desc limit 1
            """,
            parent["id"], day_key, list(_REMINDER_CATEGORIES),
        )
        if log:
            await conn.execute(
                "update message_logs set reply_status = $1 where id = $2",
                "done" if taken else "skipped", log["id"],
            )


async def _mark_meal_status(phone: str, eaten: bool):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(_PARENT_BY_PHONE_SQL, phone)
        if not parent:
            return
        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log = await conn.fetchrow(
            """
            select * from message_logs
            where parent_id = $1::uuid and day_key = $2 and msg_type = 'checkin'
              and category = any($3::text[])
            order by created_at desc limit 1
            """,
            parent["id"], day_key, list(_MEAL_CATEGORIES),
        )
        if log:
            await conn.execute(
                "update message_logs set reply_status = $1 where id = $2",
                "done" if eaten else "skipped", log["id"],
            )


async def _send_whatsapp_text(phone: str, body: str):
    return send_whatsapp(phone, body)


# ── Parent language auto-detect helper ─────────────────────────────────────
async def _detect_language(text: str) -> str:
    if not text or not text.strip():
        return None
    te_chars = sum(1 for c in text if 0x0C00 <= ord(c) <= 0x0C7F)
    hi_chars = sum(1 for c in text if 0x0900 <= ord(c) <= 0x097F)
    if te_chars > 0 and te_chars >= hi_chars:
        return "te"
    if hi_chars > 0 and hi_chars >= te_chars:
        return "hi"
    return "en"


# Meta delivers `from` as bare digits ("919xxxxxxxxx"); parents are stored as "+91…".
# Compare digits-only on both sides so replies always link to the right parent.
_PARENT_BY_PHONE_SQL = """
    select * from parents
    where deleted_at is null
      and regexp_replace(phone, '\\D', '', 'g') = regexp_replace($1, '\\D', '', 'g')
    order by created_at desc limit 1
"""


async def _record_reply(from_number: str, body_text: str, num_media: int = 0, parent=None, button_payload: str | None = None, media_url: str | None = None, media_content_type: str | None = None, raw_payload: dict | None = None, wam_id: str | None = None, context_id: str | None = None):
    if wam_id:
        existing = await get_pool().fetchrow('SELECT * FROM parent_replies WHERE wam_id=$1', wam_id)
        if existing:
            return {**dict(existing), 'duplicate': True}
    async with get_pool().acquire() as conn:
        if parent is None:
            parent = await conn.fetchrow(_PARENT_BY_PHONE_SQL, from_number)
        if parent:
            raw_stamp = (raw_payload or {}).get('timestamp')
            received_at = datetime.fromtimestamp(int(raw_stamp),timezone.utc) if raw_stamp and str(raw_stamp).isdigit() else datetime.now(timezone.utc)
            await refresh_session(parent["id"], received_at=received_at)
            if parent["auto_activity_detection"] if parent["auto_activity_detection"] is not None else True and parent["language"]:
                detected = await _detect_language(body_text or "")
                if detected and detected != parent["language"]:
                    await conn.execute(
                        """
                        update parents
                        set detected_language = $1, language_suggestion = $1, language_suggestion_at = now()
                        where id = $2
                        """,
                        detected, parent["id"],
                    )

    is_voice = False
    transcription = None
    stt_confidence = None
    intent = None
    if parent is None:
        logger.warning("[webhook] Inbound from unknown number %s — no matching parent, ignoring", from_number)
        return {"from_phone": from_number, "parent_id": None, "intent": None, "ignored": True}
    lang = parent["language"] if parent and parent["language"] else "en"
    ml_flagged = False
    ml_score = None

    owner_id = parent["user_id"] if parent else None

    async with get_pool().acquire() as conn:
        exact_log = await conn.fetchrow('SELECT * FROM message_logs WHERE parent_id=$1 AND sid=$2 ORDER BY created_at LIMIT 1', parent['id'], context_id) if context_id else None
        if button_payload:
            from services.button_intents import exact_button_intent
            intent = exact_button_intent(dict(exact_log) if exact_log else None, button_payload, body_text)
        elif (raw_payload or {}).get('type') == 'audio' or (media_content_type or '').startswith('audio/'):
            is_voice = True
            try:
                stt = await transcribe_voice_note_detailed(media_url, language=lang, auth_headers=meta_auth_header()) if media_url else None
            except Exception as exc:
                logger.warning('Voice transcription unavailable; keeping the original audio (%s)', type(exc).__name__)
                stt = None
            transcription = stt.get("transcript") if stt else None
            stt_confidence = stt.get("confidence") if stt else None
            effective_text = transcription or "[voice note]"
            intent = parse_intent(None, effective_text)
            body_text = effective_text
        else:
            last_log = exact_log
            last_msg_type = (last_log["msg_type"] if last_log else "checkin") or "checkin"
            intent = parse_intent(None, body_text, last_msg_type=last_msg_type)

        user_prefs = None
        if parent:
            user_prefs = await conn.fetchrow("select * from users where id = $1", parent["user_id"])
    extra_kw = []
    if user_prefs:
        prefs = user_prefs["preferences"]
        prefs = json.loads(prefs) if isinstance(prefs, str) else (prefs or {})
        extra_kw = prefs.get("emergency_keywords", [])

    if button_payload:
        keywords = [intent] if intent and intent.startswith("emergency:") else []
    else:
        keywords = detect_emergency(body_text, extra_kw)

    if is_voice and parent:
        assessment = await assess_transcript(parent["id"], body_text, lang, keywords)
        ml_flagged = assessment.get("ml_flagged", False)
        ml_score = assessment.get("ml_score")

    feeling = intent.split(":")[1] if intent and ":" in intent else intent

    async with get_pool().acquire() as conn, conn.transaction():
        try:
            reply_row = await conn.fetchrow(
                """
                insert into parent_replies
                    (from_phone, parent_id, user_id, body, button_payload, intent, feeling,
                     is_voice, transcription, media_url, emergency_keywords, ml_flagged, ml_score,
                     stt_confidence, raw_payload, wam_id, context_id, media_id, media_content_type, message_log_id, created_at)
                values ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14, $15::jsonb, $16, $17, $18, $19,
                  (SELECT id FROM message_logs WHERE parent_id=$2::uuid AND sid=$17 LIMIT 1), $20)
                ON CONFLICT DO NOTHING
                returning *
                """,
                from_number, parent["id"] if parent else None, owner_id, body_text, button_payload,
                intent, feeling, is_voice, transcription, media_url, json.dumps(keywords),
                ml_flagged, ml_score, stt_confidence, json.dumps(raw_payload or {}), wam_id or None,
                context_id, ((raw_payload or {}).get('audio') or {}).get('id'), media_content_type,
                min(datetime.fromtimestamp(int((raw_payload or {})['timestamp']),timezone.utc),datetime.now(timezone.utc)) if str((raw_payload or {}).get('timestamp','')).isdigit() else datetime.now(timezone.utc),
            )
        except asyncpg.UniqueViolationError:
            # Meta retries deliveries — the wam_id unique index makes this idempotent.
            logger.info("[webhook] Duplicate Meta delivery ignored (wam_id=%s)", wam_id)
            return {"ignored": True, "duplicate": True, "wam_id": wam_id, "from_phone": from_number,
                    "parent_id": str(parent["id"]) if parent else None, "intent": None}
        if not reply_row:
            return {'duplicate': True, 'parent_id': str(parent['id'])}
        if context_id and reply_row['message_log_id']:
            await conn.execute("UPDATE parent_replies SET association_source='context' WHERE id=$1", reply_row['id'])
        await notifications.enqueue_reply(conn, reply_row)
        if keywords and parent:
            await conn.execute(
                """
                insert into emergency_events (user_id, parent_id, phone, body, keywords, intent, is_voice, status, created_at)
                values ($1, $2::uuid, $3, $4, $5::jsonb, $6, $7, 'open', now())
                """,
                owner_id, parent["id"], from_number, body_text, json.dumps(keywords), intent, is_voice,
            )
    await archive_audio(dict(reply_row))
    await notifications.drain_notifications()
    return dict(reply_row)


# ── Button-tap effects (replaces the old interactive_button_handler.py wiring) ──
# _resolve_generic_button_intent() (and the pass-through above for specific
# in-session payloads) already leaves `intent` on the recorded reply in a
# uniform "<action>:<category>" shape — e.g. "done:medicine", "pending:lunch",
# "skip:dinner", "feeling:good". This reads that back instead of re-matching
# raw payload ids against interactive_button_handler.BUTTON_ACTION_MAP, whose
# 4 hardcoded ids (medicine_done/medicine_skip/meal_yes/meal_not_yet) don't
# match ANY currently-approved template button or in-session button, so every
# real tap fell through to its "Sorry, I didn't recognize that" reply — and
# message_logs.reply_status was never updated for a real tap, since
# mark_medicine_status/mark_meal_status were only ever called from inside
# that handler's unreachable matched branches.
_BUTTON_ACK_TEXT = {
    "done":    {"en": "Marked as done. 💛",                      "te": "పూర్తయినట్టు నమోదు చేశాను. 💛",              "hi": "पूरा हो गया, दर्ज कर दिया। 💛"},
    "pending": {"en": "Got it — I'll check again a bit later.",  "te": "సరే, కాసేపు తర్వాత మళ్ళీ అడుగుతాను.",        "hi": "ठीक है, थोड़ी देर बाद फिर पूछूंगी।"},
    "skip":    {"en": "Okay, noted as skipped for now.",         "te": "సరే, ఇప్పటికి స్కిప్ చేసినట్టు నమోదు చేశాను.", "hi": "ठीक है, अभी के लिए छोड़ा हुआ दर्ज कर दिया।"},
    "feeling": {"en": "Thanks for letting me know 💛",           "te": "చెప్పినందుకు ధన్యవాదాలు 💛",                  "hi": "बताने के लिए धन्यवाद 💛"},
}

# Some in-session BUTTONS payloads (templates_data.py) use a shortened
# category name that doesn't match the real category string stored in
# message_logs.category — e.g. "done:tea" for the "tea_check" category.
# Without this alias, the reply_status update below would silently find
# no matching row for these 3 categories.
_BUTTON_CATEGORY_ALIASES = {
    "bp": "bp_check",
    "sugar": "sugar_check",
    "tea": "tea_check",
    "walk": "walk_check",
    "rest": "afternoon_checkin",
}


async def _apply_button_tap_effects(reply: dict) -> None:
    """Runs once after _record_reply() for any tap that carried a button_payload."""
    intent = reply.get("intent") or ""
    action, _, category = intent.partition(":")
    if action not in ("done", "pending", "skip", "feeling", "arrived", "on_way", "activity_done"):
        return  # emergency:*, or an unresolved payload — leave to the existing emergency/family-notify flow

    parent_id = reply.get("parent_id")
    from_number = reply.get("from_phone")
    if not parent_id or not from_number:
        return

    category = _BUTTON_CATEGORY_ALIASES.get(category, category)

    async with get_pool().acquire() as conn, conn.transaction():
        claimed = await conn.fetchval('UPDATE parent_replies SET effects_applied_at=now() WHERE id=$1 AND effects_applied_at IS NULL RETURNING id', reply['id'])
        if not claimed:
            return
        p = await conn.fetchrow("select language, timezone from parents where id = $1::uuid", parent_id)
        language = (p["language"] if p and p["language"] else "en")

        if action != 'feeling' and reply.get('context_id'):
            await conn.execute('UPDATE message_logs SET reply_status=$1 WHERE id=$2 AND parent_id=$3 AND sid=$4 AND category=$5', action, reply.get('message_log_id'), parent_id, reply['context_id'], category)

    ack_text = _BUTTON_ACK_TEXT.get(action, {}).get(language) or _BUTTON_ACK_TEXT.get(action, {}).get("en")
    if ack_text:
        send_whatsapp(from_number, ack_text)


@router.get("/replies")
async def list_replies(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from parent_replies where user_id = $1 order by created_at desc limit 100", scope(user)
        )
        parent_rows = await conn.fetch("select * from parents where user_id = $1", scope(user))
    parents = {str(p["id"]): p["name"] for p in parent_rows}
    out = []
    for d in docs:
        s = serialize(d)
        s["parent_name"] = parents.get(str(d["parent_id"]), "Parent")
        out.append(s)
    return out


@router.get("/replies/unread-count")
async def replies_unread_count(user: dict = Depends(get_current_user)):
    """Badge count for the dashboard — replies the child hasn't seen yet, plus
    the most recent unread one so a poll can raise a live toast."""
    async with get_pool().acquire() as conn:
        count = await conn.fetchval(
            "select count(*) from parent_replies where user_id = $1 and read_at is null", scope(user)
        )
        latest = await conn.fetchrow(
            """
            select r.id, r.created_at, r.feeling, r.body, r.is_voice, p.name as parent_name
            from parent_replies r
            left join parents p on p.id = r.parent_id
            where r.user_id = $1 and r.read_at is null
            order by r.created_at desc limit 1
            """,
            scope(user),
        )
    latest_out = None
    if latest:
        latest_out = {
            "id": str(latest["id"]),
            "parent_name": latest["parent_name"] or "Parent",
            "feeling": latest["feeling"],
            "body": latest["body"],
            "is_voice": latest["is_voice"],
            "created_at": latest["created_at"].isoformat(),
        }
    return {"unread": count or 0, "latest": latest_out}


@router.post("/replies/read")
async def mark_replies_read(payload: MarkRepliesReadInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        if payload.ids:
            result = await conn.execute(
                "update parent_replies set read_at = now() where user_id = $1 and read_at is null and id = any($2::uuid[])",
                scope(user), payload.ids,
            )
        else:
            result = await conn.execute(
                "update parent_replies set read_at = now() where user_id = $1 and read_at is null",
                scope(user),
            )
    marked = 0
    if result and result.startswith("UPDATE "):
        try:
            marked = int(result.split(" ")[1])
        except (IndexError, ValueError):
            marked = 0
    return {"ok": True, "marked": marked}


@router.post("/replies/simulate")
async def simulate_reply(payload: SimulateReplyInput, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            payload.parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    reply = await _record_reply(
        from_number=parent["phone"] or "",
        body_text=payload.text,
        num_media=payload.num_media,
        parent=parent,
        button_payload=payload.button_payload,
    )
    return {
        "ok": True,
        "feeling": reply.get("feeling"),
        "is_voice": reply.get("is_voice"),
        "intent": reply.get("intent"),
        "emergency_keywords": json.loads(reply["emergency_keywords"]) if isinstance(reply.get("emergency_keywords"), str) else (reply.get("emergency_keywords") or []),
    }


# ---------------- WhatsApp webhook ----------------
# ── Delivery health funnel (Issue #4) ──────────────────────────────────────
# Meta sends status callbacks (sent -> delivered -> read, or failed) referencing
# the message SID we stored on message_logs.sid. We persist the furthest state
# reached so the dashboard/admin can show a real delivery funnel.
async def _persist_delivery_status(status: dict) -> None:
    from services.receipts import ingest
    await ingest(status)


async def _legacy_delivery_status(status: dict) -> None:
    await notifications.persist_receipt(status)
    sid = status.get("id")
    st = status.get("status")
    if not sid or not st:
        return
    fail_detail = None
    fail_code = None
    try:
        async with get_pool().acquire() as conn:
            if st == "sent":
                await conn.execute(
                    "update message_logs set delivery_status = coalesce(delivery_status, 'sent') where sid = $1",
                    sid,
                )
            elif st == "delivered":
                await conn.execute(
                    """update message_logs
                       set delivery_status = 'delivered', delivered_at = coalesce(delivered_at, now())
                       where sid = $1 and (delivery_status is distinct from 'read')""",
                    sid,
                )
            elif st == "read":
                await conn.execute(
                    """update message_logs
                       set delivery_status = 'read', read_at = coalesce(read_at, now()),
                           delivered_at = coalesce(delivered_at, now())
                       where sid = $1""",
                    sid,
                )
            elif st == "failed":
                errors = status.get("errors") or []
                fail_detail = (errors[0].get("title") if errors and isinstance(errors[0], dict) else None) or "delivery failed"
                fail_code = errors[0].get("code") if errors and isinstance(errors[0], dict) else None
                await conn.execute(
                    """update message_logs
                       set delivery_status = 'failed', status = 'failed', detail = coalesce(detail, $2)
                       where sid = $1 and delivery_status IS DISTINCT FROM 'read' and delivery_status IS DISTINCT FROM 'delivered'""",
                    sid, fail_detail,
                )
                # Meta code 131049: "not delivered to maintain healthy
                # ecosystem engagement" — a cold-outbound trust rejection,
                # not a transient failure. Flag the ACCOUNT OWNER only (not
                # parents — they build trust naturally via the normal
                # check-in/reply cycle) so the frontend can prompt them to
                # message us first, and so _record_reply() above knows to
                # auto-resend the welcome the moment they do.
                if fail_code == 131049:
                    recipient = status.get("recipient_id", "")
                    if recipient:
                        await conn.execute(
                            "UPDATE users SET needs_inbound_click=true WHERE regexp_replace(phone,'\\D','','g')=regexp_replace($1,'\\D','','g')",
                            recipient,
                        )
                        logger.warning("[webhook] 131049 ecosystem-engagement block for %s — flagged needs_inbound_click", recipient)
            # welcome_deliveries has no message_logs row of its own (welcome
            # sends aren't scheduler-driven check-ins), so this is the only
            # place its failure reason is ever recorded.
            if st in ('delivered','read','failed'):
                await conn.execute(
                    "UPDATE welcome_deliveries SET status=$2,detail=coalesce($3,detail),updated_at=now() WHERE sid=$1 AND status NOT IN ('delivered','read')",
                    sid, st, fail_detail,
                )
            # Phase 4: "Amma got your photo 📸" — moment delivery confirmation.
            if st in ("sent", "delivered", "read", "failed"):
                moment = await conn.fetchrow("select * from moments where sid = $1", sid)
                if moment:
                    await conn.execute("update moments set delivery_status = $2 where id = $1", moment["id"], st)
                    if st in ("delivered", "read") and not moment["delivery_notified"]:
                        await conn.execute("update moments set delivery_notified = true where id = $1", moment["id"])
                        parent = await conn.fetchrow("select * from parents where id = $1", moment["parent_id"])
                        owner = await conn.fetchrow("select * from users where id = $1", moment["user_id"])
                        if owner and owner["phone"]:
                            pname = (parent["name"] if parent else None) or "your parent"
                            send_whatsapp(owner["phone"], f"📸 {pname} got your photo 💛")
    except Exception as e:
        logger.warning("[webhook] Failed to persist delivery status %s for %s: %s", st, sid, e)


async def _delivery_funnel(conn, user_id: str | None = None) -> dict:
    """Thin wrapper preserved for in-file callers; the shared implementation
    lives in services/delivery_stats.py and is imported here as
    _delivery_funnel_shared."""
    return await _delivery_funnel_shared(conn, user_id)


@router.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    verify_token = os.environ.get("META_WA_VERIFY_TOKEN", "").strip()
    if mode == "subscribe" and hmac.compare_digest(token or "", verify_token):
        logger.info("[webhook] Meta verification handshake succeeded")
        return Response(content=challenge, media_type="text/plain")
    logger.warning("[webhook] Meta verification handshake failed")
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    if not whatsapp_enabled():
        dev_token = os.environ.get("WEBHOOK_DEV_TOKEN", "").strip()
        if not dev_token:
            raise HTTPException(403, 'Webhook disabled without a configured test secret.')
        provided = request.headers.get("X-Dev-Token", "")
        if provided != dev_token:
            raise HTTPException(status_code=403, detail="Invalid dev token")
    else:
        dev_token = os.environ.get("WEBHOOK_DEV_TOKEN", "").strip()
        if dev_token:
            logger.warning("[webhook] WEBHOOK_DEV_TOKEN is set but WHATSAPP_ENABLED=true — ignoring dev token, enforcing Meta signature")
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not verify_meta_signature(raw_body, signature):
            logger.warning("[webhook] Rejected inbound: bad/missing Meta signature (header present=%s, body=%d bytes). Check META_WA_APP_SECRET matches the Meta App Secret.", bool(signature), len(raw_body))
            raise HTTPException(status_code=403, detail="Invalid Meta signature")

    try:
        payload = json.loads(raw_body)
    except Exception:
        return Response(status_code=200, content="ok")

    # Never guess again: persist every raw Meta webhook payload (2-week TTL —
    # purged at startup in _run_startup_migrations and by nightly retention).
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                "insert into webhook_debug (direction, payload, created_at) values ('inbound', $1::jsonb, now())",
                json.dumps(payload),
            )
    except Exception as e:
        logger.warning("[webhook] webhook_debug persist failed: %s", e)

    # If durable storage fails return 503 so Meta retries. Once stored, process
    # asynchronously; retries of the same event cannot enqueue duplicate replies.
    try:
        await inbox.enqueue(payload)
    except Exception:
        raise HTTPException(503, 'Could not durably accept webhook.')
    background_tasks.add_task(inbox.drain)

    return Response(status_code=200, content="ok")


async def _process_meta_payload(payload: dict) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if value.get("statuses"):
                for status in value["statuses"]:
                    st = status.get("status")
                    if st == "failed":
                        logger.warning(
                            "[webhook] Delivery FAILED for message %s to %s: %s",
                            status.get("id"), status.get("recipient_id"), status.get("errors", []),
                        )
                    else:
                        logger.info(
                            "[webhook] Status update: message %s to %s -> %s",
                            status.get("id"), status.get("recipient_id"), st,
                        )
                    await _persist_delivery_status(status)
            for message in value.get("messages", []):
                from_number = message.get("from", "")
                wam_id = message.get("id", "")
                context_id = (message.get("context") or {}).get("id")
                try:
                    stamp = datetime.fromtimestamp(int(message.get('timestamp', '0')), timezone.utc)
                except (ValueError, TypeError, OverflowError):
                    stamp = datetime.fromtimestamp(0, timezone.utc)
                await notifications.record_recipient_inbound(from_number, stamp, context_id, message.get('type') in ('button','interactive'), wam_id)
                msg_type = message.get("type", "")
                body_text = ""
                button_payload = None
                media_url = None
                media_content_type = None
                num_media = 0

                if msg_type == "text":
                    body_text = (message.get("text", {}).get("body", "") or "").strip()
                elif msg_type == "interactive":
                    interactive = message.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        btn = interactive.get("button_reply", {})
                        button_payload = btn.get("id")
                        body_text = btn.get("title", "") or ""
                    elif interactive.get("type") == "list_reply":
                        lst = interactive.get("list_reply", {})
                        button_payload = lst.get("id")
                        body_text = lst.get("title", "") or ""
                elif msg_type == "audio":
                    num_media = 1
                    media_content_type = message.get("audio", {}).get("mime_type", "audio/ogg")
                    audio_id = message.get("audio", {}).get("id", "")
                    if audio_id:
                        media_url = await resolve_meta_media_url(audio_id)
                elif msg_type == "image":
                    num_media = 1
                    media_content_type = message.get("image", {}).get("mime_type", "image/jpeg")
                elif msg_type == "button":
                    button_payload = message.get("button", {}).get("payload")
                    body_text = message.get("button", {}).get("text", "")

                logger.info(
                    "[webhook] Inbound from %s | type=%s | payload=%s | media=%s | body=%.60s",
                    from_number, msg_type, button_payload or "–", media_content_type or "–", body_text or "–",
                )

                try:
                    reply = await _record_reply(
                        from_number=from_number,
                        body_text=body_text,
                        num_media=num_media,
                        button_payload=button_payload,
                        media_url=media_url,
                        media_content_type=media_content_type,
                        raw_payload=message,
                        wam_id=wam_id,
                        context_id=context_id,
                    )
                    if body_text.strip().lower() in ('stop', 'ఆపు', 'ఆపండి', 'बंद', 'रोकें') and reply.get('parent_id'):
                        await get_pool().execute('UPDATE parents SET opted_out_at=now() WHERE id=$1::uuid',reply['parent_id'])
                    if button_payload and reply.get("parent_id") and reply.get('id'):
                        await _apply_button_tap_effects(reply)
                except Exception as e:
                    # Always 200 to Meta — a 5xx makes Meta retry the same
                    # message for hours and never delivers newer replies.
                    logger.error("[webhook] Failed to process inbound from %s: %s", from_number, e, exc_info=True)
                    raise