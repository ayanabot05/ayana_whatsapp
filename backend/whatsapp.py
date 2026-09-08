import hashlib
import hmac
import json
import logging
import os
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

from database import get_pool
from templates_data import (
    DEFAULT_EMERGENCY_KEYWORDS,
    STATIC_LANGUAGES,
    get_template_sid_key,
    parent_relation_label,
    render_slot_body_async,
    render_slot_buttons,
)

logger = logging.getLogger("ayana.whatsapp")

_GRAPH_VERSION = os.environ.get("META_WA_GRAPH_VERSION", "v22.0").strip()
logger.info("[wa] Using Graph API version: %s (from %s)", _GRAPH_VERSION,
            "META_WA_GRAPH_VERSION env var" if os.environ.get("META_WA_GRAPH_VERSION")
            else "code default")

_SEND_TIMEOUT = 30.0

MAX_SEND_RETRIES = int(os.environ.get("WA_MAX_SEND_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(os.environ.get("WA_RETRY_BACKOFF_SECONDS", "2"))
MAX_BUTTONS = int(os.environ.get("WA_MAX_BUTTONS", "3"))
MAX_BUTTON_TITLE_LEN = int(os.environ.get("WA_MAX_BUTTON_TITLE_LEN", "20"))
SESSION_WINDOW_HOURS = int(os.environ.get("WA_SESSION_WINDOW_HOURS", "24"))

DELIVERY_RECHECK_MIN = int(os.environ.get("WA_DELIVERY_RECHECK_MIN", "5"))
# NOTE: no longer used to gate a plain-text fallback for failed template
# sends — see _send_content_template_with_retry for why that fallback was
# removed. Kept only in case some other caller still reads this env var.
DELIVERY_FALLBACK_ENABLED = os.environ.get("WA_DELIVERY_FALLBACK", "true").strip().lower() == "true"

_CATEGORY_TEMPLATE_NAME = {
    "opener": "ayana_opener",
    "medicine": "ayana_medicine",
    "meal": "ayana_meal",
    "mood": "ayana_mood",
    "reengagement": "ayana_reengagement",
    "report_ready": "ayana_report_ready",
}

TEMPLATE_LANG_CODE_MAP = {"en": "en_US", "te": "te", "hi": "hi"}


def whatsapp_enabled() -> bool:
    """Explicit WHATSAPP_ENABLED flag always wins. When the flag is UNSET,
    auto-enable if Meta credentials are present — configuring the credentials
    is a clear signal that real sends are wanted (fixes "Simulated (test
    mode)" showing up in environments where only the creds were set)."""
    flag = os.environ.get("WHATSAPP_ENABLED", "").strip().lower()
    if flag in ("false", "0", "no", "off"):
        return False
    if flag in ("true", "1", "yes", "on"):
        return True
    token, phone_id = _creds()
    return bool(token and phone_id)


def _creds() -> Tuple[str, str]:
    return (
        os.environ.get("META_WA_ACCESS_TOKEN", "").strip(),
        os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip(),
    )


def meta_auth_header() -> Dict[str, str]:
    token, _ = _creds()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get_template_name(template_key: str, language: str = "en") -> str:
    base = _CATEGORY_TEMPLATE_NAME.get(template_key, "")
    if not base:
        return ""
    lang = language if language in STATIC_LANGUAGES else "en"
    return f"{base}_{lang}"


def _messages_url(phone_id: str) -> str:
    return f"https://graph.facebook.com/{_GRAPH_VERSION}/{phone_id}/messages"


def _extract_message_id(resp_json: Dict[str, Any]) -> str:
    try:
        return resp_json.get("messages", [{}])[0].get("id", "")
    except Exception:
        return ""


def _log_meta_error(resp: "httpx.Response", context: str) -> None:
    """Best-effort extraction + logging of Meta's structured error body.
    Call this BEFORE resp.raise_for_status() so the real reason (bad
    template name, language mismatch, disabled template, permission
    issue, etc.) is captured instead of being discarded by the exception."""
    try:
        body = resp.json()
        err = body.get("error", {})
        logger.error(
            "[wa] Meta API error (%s): http=%s code=%s subcode=%s type=%s message=%s trace_id=%s",
            context,
            resp.status_code,
            err.get("code"),
            err.get("error_subcode"),
            err.get("type"),
            err.get("message"),
            err.get("fbtrace_id"),
        )
    except Exception:
        logger.error("[wa] Meta API error (%s): http=%s body=%.500s", context, resp.status_code, resp.text)


def send_whatsapp(to_phone: str, body: str) -> Dict[str, Any]:
    token, phone_id = _creds()
    if not whatsapp_enabled() or not token or not phone_id:
        logger.info("[wa] Simulated (test mode): %s → %.60s…", to_phone, body)
        return {"status": "simulated", "detail": "WhatsApp disabled (test mode)", "to": to_phone}
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": body},
        }
        resp = httpx.post(
            _messages_url(phone_id),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=_SEND_TIMEOUT,
        )
        if resp.status_code >= 400:
            _log_meta_error(resp, f"plain_text to={to_phone}")
        resp.raise_for_status()
        msg_id = _extract_message_id(resp.json())
        logger.info("[wa] Plain text sent to %s id=%s", to_phone, msg_id)
        return {"status": "sent", "sid": msg_id, "to": to_phone}
    except Exception as e:
        logger.error("[wa] Send failed to %s: %s", to_phone, e, exc_info=True)
        return {"status": "failed", "detail": str(e), "to": to_phone}


def _build_body_params(content_variables: Dict[str, str]) -> List[Dict[str, str]]:
    ordered_keys = sorted(content_variables.keys(), key=lambda k: int(k))
    return [{"type": "text", "text": content_variables[k]} for k in ordered_keys]


def _send_content_template_once(
    to_phone: str, template_name: str, language: str, content_variables: Dict[str, str], template_key: str
) -> Optional[Dict[str, Any]]:
    token, phone_id = _creds()
    if not whatsapp_enabled() or not token or not phone_id:
        logger.info("[wa] Template %s SIMULATED (test mode) for %s -> %s vars=%s", template_key, to_phone, template_name, content_variables)
        return {"status": "simulated", "template_type": template_key, "template_name": template_name, "to": to_phone, "vars": content_variables}
    if not template_name:
        logger.warning("[wa] No template name for %s, to=%s", template_key, to_phone)
        return None
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [{"type": "body", "parameters": _build_body_params(content_variables)}],
        },
    }
    resp = httpx.post(
        _messages_url(phone_id),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=_SEND_TIMEOUT,
    )
    if resp.status_code >= 400:
        _log_meta_error(resp, f"template={template_name} lang={language} to={to_phone}")
    resp.raise_for_status()
    msg_id = _extract_message_id(resp.json())
    return {"status": "sent", "sid": msg_id, "template_type": template_key}


async def _send_content_template_with_retry(
    to_phone: str, template_name: str, language: str, content_variables: Dict[str, str], template_key: str
) -> Optional[Dict[str, Any]]:
    token, phone_id = _creds()
    if not whatsapp_enabled() or not token or not phone_id:
        return _send_content_template_once(to_phone, template_name, language, content_variables, template_key)

    last_error = None
    for attempt in range(1, MAX_SEND_RETRIES + 1):
        try:
            res = _send_content_template_once(to_phone, template_name, language, content_variables, template_key)
            if res and res.get("sid"):
                return res
            if res and res.get("status") == "simulated":
                return res
        except Exception as e:
            last_error = e
            logger.warning("[wa] Send attempt %s/%s failed (type=%s) to %s: %s", attempt, MAX_SEND_RETRIES, template_key, to_phone, e)
            if attempt < MAX_SEND_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

    # NOTE: we deliberately do NOT fall back to plain text here anymore.
    # _send_content_template_with_retry is only ever called when the 24h
    # session is CLOSED (send_template_for_category routes to the quick-reply
    # path instead whenever the session is open) — and Meta rejects plain
    # text outside that same window for the exact reason templates exist.
    # The old fallback returned a fake "sent" status (Meta's /messages
    # endpoint accepts the HTTP call with 200 OK) while the actual delivery
    # silently failed later via webhook (131047 Re-engagement message),
    # which nobody was watching in real time. Paying customers rely on this
    # arriving every day, so an honest "failed" here — which the scheduler
    # now retries every minute until it succeeds (see scheduler.py) — beats
    # a comforting lie that quietly drops the message.
    logger.error(
        "[wa] All %s template send attempts failed (type=%s) to %s: %s — "
        "will be retried automatically by the scheduler",
        MAX_SEND_RETRIES, template_key, to_phone, last_error,
    )
    try:
        import sentry_sdk
        sentry_sdk.capture_message(
            f"WhatsApp template delivery failed after retries: {template_key} to {to_phone}: {last_error}",
            level="error",
        )
    except Exception:
        pass  # Sentry not configured — logging above is still the source of truth
    return {"status": "failed", "detail": str(last_error), "template_type": template_key}


MIC_HINT = {
    "en": "💛 Want to talk? Press & hold the 🎤 mic below and speak — anytime.",
    "te": "💛 మాట్లాడాలనుకుంటున్నారా? కింద ఉన్న 🎤 మైక్ను నొక్కి పట్టుకుని మాట్లాడండి — ఎప్పుడైనా.",
    "hi": "💛 बात करनी है? नीचे 🎤 माइक दबाकर बोलें — कभी भी।",
}

MOMENT_INTRO = {
    "en": "💛 {sender} sent you a little something:",
    "te": "💛 {sender} మీ కోసం ఒక చిన్న సందేశం పంపారు:",
    "hi": "💛 {sender} ने आपके लिए कुछ भेजा है:",
}


async def _send_quick_reply(
    to_phone: str, body: str, buttons: List[Tuple[str, str]], context: str = "dynamic", language: str = "en",
) -> Dict[str, Any]:
    token, phone_id = _creds()
    buttons = buttons[:MAX_BUTTONS]
    hint = MIC_HINT.get(language, MIC_HINT["en"])
    if hint and hint not in body:
        body = f"{body}\n\n{hint}"
    safe_buttons = [(l[:MAX_BUTTON_TITLE_LEN] if len(l) > MAX_BUTTON_TITLE_LEN else l, p) for l, p in buttons]

    if not whatsapp_enabled() or not token or not phone_id:
        btn_text = " ".join(f"{i+1}) {label}" for i, (label, _) in enumerate(safe_buttons))
        full_body = f"{body}\n\n👉 {btn_text} — or 🎤 voice reply"
        logger.info("[wa] Simulated quick-reply %s to %s", context, to_phone)
        return send_whatsapp(to_phone, full_body)

    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": payload_id, "title": label}}
                    for label, payload_id in safe_buttons
                ]},
            },
        }
        resp = httpx.post(
            _messages_url(phone_id),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=_SEND_TIMEOUT,
        )
        if resp.status_code >= 400:
            _log_meta_error(resp, f"quick_reply context={context} to={to_phone}")
        resp.raise_for_status()
        msg_id = _extract_message_id(resp.json())
        return {"status": "sent", "sid": msg_id, "context": context}
    except Exception as e:
        logger.warning("[wa] Quick-reply API failed (%s), fallback to plain text: %s", context, e)
        btn_text = " ".join(f"{i+1}) {label}" for i, (label, _) in enumerate(safe_buttons))
        return send_whatsapp(to_phone, f"{body}\n\n👉 {btn_text}")


async def get_session(parent_id) -> Optional[Dict[str, Any]]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("select * from wa_sessions where parent_id = $1", parent_id)
    return dict(row) if row else None


async def is_session_open(parent_id) -> bool:
    session = await get_session(parent_id)
    if not session:
        return False
    last_inbound = session.get("last_inbound_at")
    if not last_inbound:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SESSION_WINDOW_HOURS)
    if last_inbound.tzinfo is None:
        last_inbound = last_inbound.replace(tzinfo=timezone.utc)
    return last_inbound >= cutoff


async def refresh_session(parent_id) -> None:
    now = datetime.now(timezone.utc)
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into wa_sessions (parent_id, last_inbound_at, session_open, last_activity, updated_at)
            values ($1, $2, true, $2, now())
            on conflict (parent_id) do update
                set last_inbound_at = excluded.last_inbound_at,
                    session_open = true,
                    last_activity = excluded.last_activity,
                    updated_at = now()
            """,
            parent_id, now,
        )


async def mark_opener_sent(parent_id, template_type: str = "opener") -> None:
    now = datetime.now(timezone.utc)
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into wa_sessions (parent_id, opener_sent_at, last_template_type,
                                      reengagement_sent, last_outbound_at, updated_at)
            values ($1, $2, $3, false, $2, now())
            on conflict (parent_id) do update
                set opener_sent_at = excluded.opener_sent_at,
                    last_template_type = excluded.last_template_type,
                    reengagement_sent = false,
                    last_outbound_at = excluded.last_outbound_at,
                    updated_at = now()
            """,
            parent_id, now, template_type,
        )


async def mark_reengagement_sent(parent_id) -> None:
    now = datetime.now(timezone.utc)
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into wa_sessions (parent_id, reengagement_sent, reengagement_sent_at, updated_at)
            values ($1, true, $2, now())
            on conflict (parent_id) do update
                set reengagement_sent = true,
                    reengagement_sent_at = excluded.reengagement_sent_at,
                    updated_at = now()
            """,
            parent_id, now,
        )


_NON_MEDICINE_REMINDER_LABELS = {
    "water": "water",
    "bp_check": "BP check",
    "sugar_check": "sugar check",
    "health_check": "health check",
}


def _language_native_medicine_placeholder(language: str) -> str:
    lang = (language or "en").lower()
    return {"en": "your medicine", "te": "మందు", "hi": "दवाई"}.get(lang, "your medicine")


def _build_approved_template_vars(
    template_key: str, category: str, preferred: str, parent: Dict[str, Any], language: str, medicine_name: str
) -> Dict[str, str]:
    if template_key == "opener":
        return {"1": preferred, "2": parent_relation_label(parent, language)}
    if template_key == "medicine":
        if category == "medicine":
            label = medicine_name or _language_native_medicine_placeholder(language)
        else:
            label = _NON_MEDICINE_REMINDER_LABELS.get(category, medicine_name or _language_native_medicine_placeholder(language))
        return {"1": preferred, "2": label}
    return {"1": preferred}


async def send_template_for_category(parent: Dict[str, Any], category: str, day_index: int, variants_per_slot: int, medicine_name: str = "") -> Dict[str, Any]:
    parent_id = parent["id"]
    phone = parent.get("phone", "")
    language = parent.get("language", "en")
    preferred = parent.get("preferred_name") or parent.get("name", "") or "Amma"

    if await is_session_open(parent_id):
        return await send_dynamic_checkin(parent, category, day_index, variants_per_slot, medicine_name)

    template_key = get_template_sid_key(category)
    template_name = _get_template_name(template_key, language)
    body = await render_slot_body_async(category, language, parent, day_index, medicine_name or _language_native_medicine_placeholder(language), variants_per_slot)

    if template_name and whatsapp_enabled():
        content_vars = _build_approved_template_vars(template_key, category, preferred, parent, language, medicine_name)
        result = await _send_content_template_with_retry(phone, template_name, language, content_vars, template_key)
    else:
        result = send_whatsapp(phone, body)

    if result and result.get("status") in ("sent", "simulated"):
        await mark_opener_sent(parent_id, template_key)
    return result or {"status": "failed", "detail": "No result from template send"}


async def send_whatsapp_opener(parent, day_index: int = 0, variants_per_slot: int = 7):
    if await is_session_open(parent["id"]):
        return {"skipped": True, "reason": "session_open"}
    return await send_template_for_category(parent, "morning_wish", day_index, variants_per_slot)


async def send_medicine_template(parent, day_index: int = 0, variants_per_slot: int = 7, medicine_name: str = ""):
    return await send_template_for_category(parent, "medicine", day_index, variants_per_slot, medicine_name)


async def send_meal_template(parent, meal_type: str = "lunch", day_index: int = 0, variants_per_slot: int = 7):
    return await send_template_for_category(parent, meal_type, day_index, variants_per_slot)


async def send_mood_template(parent, category: str = "goodnight", day_index: int = 0, variants_per_slot: int = 7):
    return await send_template_for_category(parent, category, day_index, variants_per_slot)


async def send_dynamic_checkin(parent: Dict[str, Any], category: str, day_index: int, variants_per_slot: int, medicine_name: str = "") -> Dict[str, Any]:
    parent_id = parent["id"]
    phone = parent.get("phone", "")
    language = parent.get("language", "en")

    if not await is_session_open(parent_id):
        return await send_template_for_category(parent, category, day_index, variants_per_slot, medicine_name)

    body = await render_slot_body_async(category, language, parent, day_index, medicine_name or _language_native_medicine_placeholder(language), variants_per_slot)
    buttons = render_slot_buttons(category, language)
    return await _send_quick_reply(phone, body, buttons, context=category, language=language)


async def send_reengagement(parent: Dict[str, Any], reengagement_hours: int = 4) -> Dict[str, Any]:
    parent_id = parent["id"]
    phone = parent.get("phone", "")
    language = parent.get("language", "en")
    preferred = parent.get("preferred_name") or parent.get("name", "") or "Amma"

    session = await get_session(parent_id)
    if not session:
        return {"skipped": True, "reason": "no_session"}
    if session.get("reengagement_sent"):
        return {"skipped": True, "reason": "already_sent"}

    opener_sent_at = session.get("opener_sent_at")
    last_inbound = session.get("last_inbound_at")
    if not opener_sent_at:
        return {"skipped": True, "reason": "no_opener_sent"}
    if opener_sent_at.tzinfo is None:
        opener_sent_at = opener_sent_at.replace(tzinfo=timezone.utc)

    hours_since = (datetime.now(timezone.utc) - opener_sent_at).total_seconds() / 3600
    if hours_since < reengagement_hours:
        return {"skipped": True, "reason": f"too_soon ({hours_since:.1f}h < {reengagement_hours}h)"}

    if last_inbound:
        if last_inbound.tzinfo is None:
            last_inbound = last_inbound.replace(tzinfo=timezone.utc)
        if last_inbound > opener_sent_at:
            return {"skipped": True, "reason": "parent_replied"}

    template_name = _get_template_name("reengagement", language)
    if template_name and whatsapp_enabled():
        result = await _send_content_template_with_retry(phone, template_name, language, {"1": preferred}, "reengagement")
    else:
        body = f"{preferred}, we miss hearing from you 💛\n\nJust checking — are you alright?"
        result = send_whatsapp(phone, body)

    if result and result.get("status") in ("sent", "simulated"):
        await mark_reengagement_sent(parent_id)
    return result or {"status": "failed", "detail": "No result"}


async def send_moment(parent: Dict[str, Any], text: str, sender_name: str, image_url: str = "", image_urls: List[str] = None) -> Dict[str, Any]:
    language = parent.get("language", "en")
    phone = parent.get("phone", "")
    intro = MOMENT_INTRO.get(language, MOMENT_INTRO["en"]).format(sender=sender_name or "Your family")
    body = f"{intro}\n\n{text}".strip()

    urls = list(image_urls or [])
    if image_url and image_url not in urls:
        urls.append(image_url)
    if len(urls) > 2:
        urls = urls[:2]

    token, phone_id = _creds()
    last_result = None
    any_sent = False

    if urls and whatsapp_enabled() and token and phone_id:
        for idx, url in enumerate(urls):
            caption = body if idx == 0 else ""
            try:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "image",
                    "image": {"link": url, "caption": caption},
                    }
                resp = httpx.post(
                    _messages_url(phone_id),
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=_SEND_TIMEOUT,
                )
                if resp.status_code >= 400:
                    _log_meta_error(resp, f"moment_image idx={idx} to={phone}")
                resp.raise_for_status()
                msg_id = _extract_message_id(resp.json())
                last_result = {"status": "sent", "sid": msg_id, "context": "moment"}
                any_sent = True
            except Exception as e:
                logger.warning("[wa] Moment media send failed for image %d: %s", idx, e)
                last_result = {"status": "failed", "detail": str(e)}
    else:
        last_result = send_whatsapp(phone, body)
        any_sent = last_result.get("status") == "sent"

    if not any_sent and last_result is None:
        last_result = send_whatsapp(phone, body)
    return last_result


async def send_report_ready(to_phone: str, language: str, parent_display: str) -> Dict[str, Any]:
    template_name = _get_template_name("report_ready", language)
    content_vars = {"1": parent_display or "your parent"}
    return await _send_content_template_with_retry(to_phone, template_name, language, content_vars, "report_ready")


# ── NEW: Voice note forwarding (Issue #2) ─────────────────────────────────
async def send_audio_link(to_phone: str, audio_link: str) -> Dict[str, Any]:
    """Send a voice note as audio by link (S3 signed URL)"""
    token, phone_id = _creds()
    if not whatsapp_enabled() or not token or not phone_id:
        logger.info("[wa] Simulated audio to %s link=%.80s", to_phone, audio_link)
        return {"status": "simulated", "to": to_phone, "type": "audio", "link": audio_link}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "audio",
        "audio": {"link": audio_link}
    }
    try:
        resp = httpx.post(
            _messages_url(phone_id),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=_SEND_TIMEOUT,
        )
        if resp.status_code >= 400:
            _log_meta_error(resp, f"audio to={to_phone}")
        resp.raise_for_status()
        msg_id = _extract_message_id(resp.json())
        logger.info("[wa] Audio sent to %s id=%s", to_phone, msg_id)
        return {"status": "sent", "sid": msg_id, "type": "audio"}
    except Exception as e:
        logger.error("[wa] Audio send failed to %s: %s", to_phone, e)
        return {"status": "failed", "detail": str(e), "to": to_phone}


async def download_and_host_voice_note(meta_cdn_url: str, parent_id: str) -> Optional[str]:
    """Download Meta's temporary voice URL and re-host on S3 for forwarding to child"""
    if not meta_cdn_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(meta_cdn_url, headers=meta_auth_header(), follow_redirects=True)
            resp.raise_for_status()
            audio_bytes = resp.content
            if len(audio_bytes) < 1000:
                logger.warning("[wa] Voice note too small: %d bytes", len(audio_bytes))
                return None

        from storage import put_object, signed_url as storage_signed_url, is_enabled as storage_enabled, APP_NAME as STORAGE_APP_NAME
        if not storage_enabled():
            logger.warning("[wa] Storage disabled, cannot host voice note - will try direct link")
            return meta_cdn_url  # Fallback: try direct Meta link

        filename = f"voice_{parent_id}_{uuid.uuid4().hex}.ogg"
        storage_path = f"{STORAGE_APP_NAME}/voice_notes/{filename}"
        put_object(storage_path, audio_bytes, "audio/ogg")
        url = storage_signed_url(storage_path)
        logger.info("[wa] Voice note hosted: %s -> %.80s", parent_id, url)
        return url
    except Exception as e:
        logger.error("[wa] Failed to host voice note for %s: %s", parent_id, e, exc_info=True)
        return None


async def resolve_meta_media_url(media_id: str) -> Optional[str]:
    token, _ = _creds()
    if not token or not media_id:
        return None
    try:
        url = f"https://graph.facebook.com/{_GRAPH_VERSION}/{media_id}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            _log_meta_error(resp, f"resolve_media id={media_id}")
        resp.raise_for_status()
        return resp.json().get("url")
    except Exception as e:
        logger.error("[wa] Failed to resolve media URL for %s: %s", media_id, e)
        return None


def verify_meta_signature(raw_body: bytes, signature: str) -> bool:
    app_secret = (os.environ.get("META_WA_APP_SECRET") or os.environ.get("META_APP_SECRET") or "").strip()
    if not app_secret:
        logger.warning("[wa] META_WA_APP_SECRET not set — cannot verify webhook signature")
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def detect_emergency(text: str, extra_keywords: Optional[List[str]] = None) -> List[str]:
    if not text:
        return []
    keywords = list(DEFAULT_EMERGENCY_KEYWORDS) + (extra_keywords or [])
    low = text.lower()
    matched = [k for k in keywords if k.lower() in low]
    if matched:
        logger.warning("[wa] Emergency keyword(s) matched in inbound text")
    return matched


NUMERIC_CHECKIN_MAP = {"1": "feeling:good", "2": "feeling:okay", "3": "feeling:not_well"}
NUMERIC_REMINDER_MAP = {"1": "done:generic", "2": "pending:generic", "3": "skip:generic"}

FEELING_PATTERNS = {
    "good": [
        "బాగున్నా", "బాగుంది", "బాగుందాం", "చాలా బాగుంది", "గుడ్", "సుఖంగా",
        "बाग हूँ", "बहुत अच्छा", "ठीक हूँ", "ठीक है", "अच्छा", "सुखद",
    ],
    "okay": [
        "సాధారణం", "ఫర్వాలేదు", "సరే", "ఓకే", "సాధారణంగా",
        "ठीक-ठाक", "त्यार हूँ", "बिना मुद्दत के",
    ],
    "not_well": [
        "ఒంట్లో బాలేదు", "కాలు నొప్పి", "నొప్పి", "చెడ్గా", "హృద్యం మరీయు",
        "मुझे खराब", "पीड़हट", "बहुत खराब", "असहज", "नहीं हूँ",
    ],
}


def _match_feeling(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip().lower()
    for feeling, phrases in FEELING_PATTERNS.items():
        for phrase in phrases:
            if phrase.lower() in t:
                return feeling
    return None


def parse_intent(button_payload: Optional[str], body: Optional[str], last_msg_type: str = "checkin") -> str:
    if button_payload:
        return button_payload
    text = (body or "").strip()
    if not text:
        return "text"
    numeric_map = NUMERIC_CHECKIN_MAP if last_msg_type == "checkin" else NUMERIC_REMINDER_MAP
    if text in numeric_map:
        return numeric_map[text]
    if last_msg_type == "checkin":
        feeling = _match_feeling(text)
        if feeling:
            return f"feeling:{feeling}"
    return "text"


# ── Care Circle Activation Welcome (Issue #1) ──────────────────────────────
async def send_opener_welcome(
    to_phone: str,
    recipient_name: str,
    checking_for_name: str,
    language: str = "en",
) -> Dict[str, Any]:
    template_name = _get_template_name("opener", language)
    lang_code = TEMPLATE_LANG_CODE_MAP.get(language, "en_US")
    content_vars = {"1": recipient_name[:20], "2": checking_for_name[:20]}
    logger.info(f"[welcome] {template_name} -> {to_phone} : {recipient_name} for {checking_for_name}")
    return await _send_content_template_with_retry(
        to_phone, template_name, lang_code, content_vars, "opener"
    )


async def send_care_circle_activation_welcome(
    child_user: Dict[str, Any],
    parents: List[Dict[str, Any]],
) -> Dict[str, List]:
    child_name = (child_user.get("name") or child_user.get("full_name") or child_user.get("fullName") or child_user.get("email") or "there").split()[0]
    child_phone = child_user.get("phone") or child_user.get("whatsapp_number") or child_user.get("phone_number") or child_user.get("whatsappNumber")
    child_lang = child_user.get("language") or child_user.get("preferred_language") or "en"
    results = {"child": [], "parents": []}
    if child_phone and parents:
        for p in parents:
            parent_display = p.get("preferred_name") or p.get("name") or "your parent"
            res = await send_opener_welcome(child_phone, child_name, parent_display, child_lang)
            results["child"].append(res)
    for p in parents:
        p_phone = p.get("phone")
        if not p_phone:
            continue
        p_name = p.get("preferred_name") or p.get("name") or "there"
        p_lang = p.get("language") or child_lang
        res = await send_opener_welcome(p_phone, p_name, child_name, p_lang)
        results["parents"].append(res)
    return results


# ── Per-parent welcome (Phase 2): fires for EVERY parent added, both sides ──
_PARENT_WELCOME_TEXT = {
    "en": "Namaste {parent_name} 💛 This is Ayana. Your child {child_name} asked me to check on you every day. Reply 👍 to say hi.",
    "te": "నమస్తే {parent_name} 💛 నేను Ayana. మీ పిల్లవాడు {child_name} ప్రతిరోజూ మీ గురించి అడగమన్నారు. హాయ్ చెప్పడానికి 👍 తో రిప్లై చేయండి.",
    "hi": "नमस्ते {parent_name} 💛 मैं Ayana हूँ। आपके बच्चे {child_name} ने मुझसे हर दिन आपका हाल पूछने को कहा है। हाय कहने के लिए 👍 से जवाब दीजिए।",
}

_CHILD_PARENT_SETUP_TEXT = "✅ {parent_name} is set up. First check-in tomorrow at 8:00 AM IST. 💛"


async def send_welcome_for_new_parent(
    child_user: Dict[str, Any],
    new_parent: Dict[str, Any],
) -> Dict[str, Any]:
    """Welcome BOTH sides when a parent is added — per parent, not per account."""
    child_name = (child_user.get("name") or child_user.get("full_name") or "there").split()[0]
    child_phone = child_user.get("phone") or child_user.get("whatsapp_number") or child_user.get("phone_number")
    p_phone = new_parent.get("phone")
    p_name = new_parent.get("preferred_name") or new_parent.get("name") or "there"
    p_lang = _lang2(new_parent.get("language"))
    results: Dict[str, Any] = {}
    if p_phone:
        body = _PARENT_WELCOME_TEXT.get(p_lang, _PARENT_WELCOME_TEXT["en"]).format(
            parent_name=p_name, child_name=child_name,
        )
        logger.info("[welcome] parent welcome -> %s (%s)", p_phone, p_name)
        results["parent"] = send_whatsapp(p_phone, body)
    if child_phone:
        logger.info("[welcome] child confirmation -> %s for %s", child_phone, p_name)
        results["child"] = send_whatsapp(child_phone, _CHILD_PARENT_SETUP_TEXT.format(parent_name=p_name))
    return results


# ── Farewell when a parent is removed (e.g. on plan downgrade) ─────────────
_GOODBYE_TEXT = {
    "en": "Namaste {name} 💛 AYANA's daily check-ins are being paused for now. It's been a joy checking in on you. Take good care — your family loves you.",
    "te": "నమస్తే {name} 💛 ప్రస్తుతానికి AYANA రోజువారీ పలకరింపులు ఆపుతున్నాం. మిమ్మల్ని పలకరించడం చాలా సంతోషంగా ఉంది. జాగ్రత్తగా ఉండండి — మీ కుటుంబం మిమ్మల్ని ఎంతో ప్రేమిస్తోంది.",
    "hi": "नमस्ते {name} 💛 अभी के लिए AYANA की रोज़ की बातचीत रोकी जा रही है। आपका हाल पूछना बहुत अच्छा लगा। अपना ख्याल रखिए — आपका परिवार आपसे बहुत प्यार करता है।",
}


async def send_parent_goodbye(parent: Dict[str, Any]) -> Dict[str, Any]:
    """Warm free-text farewell to a parent whose check-ins are stopping."""
    phone = parent.get("phone")
    if not phone:
        return {"status": "skipped", "detail": "no phone"}
    name = parent.get("preferred_name") or parent.get("name") or "there"
    lang = parent.get("language") or "en"
    body = _GOODBYE_TEXT.get(lang, _GOODBYE_TEXT["en"]).format(name=name)
    logger.info("[goodbye] -> %s (%s)", phone, name)
    return send_whatsapp(phone, body)



# ── Lifecycle notifications (Issue #3) ─────────────────────────────────────
# Warm, plain-text WhatsApp nudges sent on account/plan/care-circle lifecycle
# events. All are best-effort: they use send_whatsapp() which returns a
# 'simulated' result when WhatsApp is disabled, and never raise. On cold
# numbers (no open 24h session and no template) Meta may reject free text —
# that's acceptable here; these are courtesy messages, not the OTP path.

_CHILD_WELCOME_TEXT = {
    "en": "Welcome to AYANA, {name}! 💛 We'll help you stay close to your parents with gentle daily check-ins. Add a parent and activate WhatsApp check-ins from your dashboard to begin.",
    "te": "AYANAకి స్వాగతం, {name}! 💛 రోజువారీ ఆప్యాయమైన పలకరింపులతో మీ తల్లిదండ్రులకు దగ్గరగా ఉండేందుకు మేము సహాయం చేస్తాం. మొదలుపెట్టడానికి మీ డాష్‌బోర్డ్ నుండి ఒక పేరెంట్‌ను జోడించి WhatsApp పలకరింపులను యాక్టివేట్ చేయండి.",
    "hi": "AYANA में आपका स्वागत है, {name}! 💛 रोज़ की स्नेहभरी बातचीत से हम आपको अपने माता-पिता के करीब रखने में मदद करेंगे। शुरू करने के लिए अपने डैशबोर्ड से एक पैरेंट जोड़ें और WhatsApp चेक-इन चालू करें।",
}

_PLAN_CHANGE_TEXT = {
    "en": {
        "upgrade": "🌟 Your AYANA plan is now {plan}! Thank you — your family's care just got even better. 💛",
        "downgrade": "Your AYANA plan has been changed to {plan}. Some features may have changed; you can upgrade anytime from your dashboard. 💛",
        "same": "Your AYANA {plan} plan is active. 💛",
    },
    "te": {
        "upgrade": "🌟 మీ AYANA ప్లాన్ ఇప్పుడు {plan}! ధన్యవాదాలు — మీ కుటుంబ సంరక్షణ మరింత మెరుగైంది. 💛",
        "downgrade": "మీ AYANA ప్లాన్ {plan}కి మార్చబడింది. కొన్ని ఫీచర్లు మారి ఉండవచ్చు; మీ డాష్‌బోర్డ్ నుండి ఎప్పుడైనా అప్‌గ్రేడ్ చేసుకోవచ్చు. 💛",
        "same": "మీ AYANA {plan} ప్లాన్ యాక్టివ్‌గా ఉంది. 💛",
    },
    "hi": {
        "upgrade": "🌟 आपका AYANA प्लान अब {plan} है! धन्यवाद — आपके परिवार की देखभाल और भी बेहतर हो गई। 💛",
        "downgrade": "आपका AYANA प्लान {plan} में बदल दिया गया है। कुछ सुविधाएँ बदल सकती हैं; आप अपने डैशबोर्ड से कभी भी अपग्रेड कर सकते हैं। 💛",
        "same": "आपका AYANA {plan} प्लान सक्रिय है। 💛",
    },
}

_PARENT_REMOVED_CHILD_TEXT = {
    "en": "AYANA daily check-ins for {parent} have been stopped. You can add them again anytime from your dashboard. 💛",
    "te": "{parent} కోసం AYANA రోజువారీ పలకరింపులు ఆపబడ్డాయి. మీ డాష్‌బోర్డ్ నుండి ఎప్పుడైనా మళ్ళీ జోడించవచ్చు. 💛",
    "hi": "{parent} के लिए AYANA की रोज़ की बातचीत रोक दी गई है। आप उन्हें अपने डैशबोर्ड से कभी भी दोबारा जोड़ सकते हैं। 💛",
}

_MEMBER_REMOVED_TEXT = {
    "en": "You've been removed from an AYANA Care Circle. You'll no longer receive updates for that family. 💛",
    "te": "మిమ్మల్ని ఒక AYANA కేర్ సర్కిల్ నుండి తొలగించారు. ఆ కుటుంబం కోసం ఇకపై అప్‌డేట్‌లు అందవు. 💛",
    "hi": "आपको एक AYANA केयर सर्कल से हटा दिया गया है। अब आपको उस परिवार के अपडेट नहीं मिलेंगे। 💛",
}


def _lang2(language: str | None) -> str:
    return (language or "en").strip().lower()[:2] or "en"


async def send_child_welcome(user: Dict[str, Any]) -> Dict[str, Any]:
    """Welcome the account owner (adult child) right after they sign up."""
    phone = user.get("phone") or user.get("whatsapp_number") or user.get("phone_number")
    if not phone:
        return {"status": "skipped", "detail": "no phone"}
    name = (user.get("name") or user.get("full_name") or "there").split()[0]
    lang = _lang2(user.get("language"))
    body = _CHILD_WELCOME_TEXT.get(lang, _CHILD_WELCOME_TEXT["en"]).format(name=name)
    logger.info("[welcome] child welcome -> %s", phone)
    return send_whatsapp(phone, body)


async def send_plan_change(phone: str, language: str, plan_name: str, direction: str) -> Dict[str, Any]:
    """Notify the account owner their subscription plan changed."""
    if not phone:
        return {"status": "skipped", "detail": "no phone"}
    lang = _lang2(language)
    tset = _PLAN_CHANGE_TEXT.get(lang, _PLAN_CHANGE_TEXT["en"])
    body = tset.get(direction, tset["same"]).format(plan=plan_name)
    logger.info("[plan] %s notice (%s) -> %s", direction, plan_name, phone)
    return send_whatsapp(phone, body)


async def send_parent_removed_child_notice(child_phone: str, language: str, parent_name: str) -> Dict[str, Any]:
    """Let the child know check-ins for a removed parent have stopped."""
    if not child_phone:
        return {"status": "skipped", "detail": "no phone"}
    lang = _lang2(language)
    body = _PARENT_REMOVED_CHILD_TEXT.get(lang, _PARENT_REMOVED_CHILD_TEXT["en"]).format(parent=parent_name or "your parent")
    logger.info("[lifecycle] parent-removed child notice -> %s", child_phone)
    return send_whatsapp(child_phone, body)


async def send_member_removed_notice(member_phone: str, language: str = "en") -> Dict[str, Any]:
    """Let a removed Care Circle member know they've been removed."""
    if not member_phone:
        return {"status": "skipped", "detail": "no phone"}
    lang = _lang2(language)
    body = _MEMBER_REMOVED_TEXT.get(lang, _MEMBER_REMOVED_TEXT["en"])
    logger.info("[lifecycle] member-removed notice -> %s", member_phone)
    return send_whatsapp(member_phone, body)