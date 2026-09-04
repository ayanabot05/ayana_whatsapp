import hashlib
import hmac
import json
import logging
import os
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

from database import get_pool
from templates_data import (
    DEFAULT_EMERGENCY_KEYWORDS,
    get_template_sid_key,
    parent_relation_label,
    render_slot_body_async,
    render_slot_buttons,
)

logger = logging.getLogger("ayana.whatsapp")

_GRAPH_VERSION = os.environ.get("META_WA_GRAPH_VERSION", "v22.0").strip()
_SEND_TIMEOUT = 30.0

# ── Tunables (env-overridable, sensible defaults) ───────────────────────
# MAX_BUTTONS and SESSION_WINDOW_HOURS are real WhatsApp/Meta platform
# limits, not preferences — don't change these, Meta will reject sends
# that violate them regardless of what's set here.
MAX_SEND_RETRIES = int(os.environ.get("WA_MAX_SEND_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(os.environ.get("WA_RETRY_BACKOFF_SECONDS", "2"))
MAX_BUTTONS = int(os.environ.get("WA_MAX_BUTTONS", "3"))                     # WhatsApp quick-reply cap
MAX_BUTTON_TITLE_LEN = int(os.environ.get("WA_MAX_BUTTON_TITLE_LEN", "20"))  # WhatsApp button label cap
SESSION_WINDOW_HOURS = int(os.environ.get("WA_SESSION_WINDOW_HOURS", "24")) # Meta's 24h customer-service window

# ── Delivery fallback & recheck ───────────────────────────────────────────
DELIVERY_RECHECK_MIN = int(os.environ.get("WA_DELIVERY_RECHECK_MIN", "5"))
DELIVERY_FALLBACK_ENABLED = os.environ.get("WA_DELIVERY_FALLBACK", "true").strip().lower() == "true"

# ── Map each template category → the approved Meta template's literal name ──
_CATEGORY_TEMPLATE_NAME = {
    "opener": "ayana_opener",
    "medicine": "ayana_medicine",
    "meal": "ayana_meal",
    "mood": "ayana_mood",
    "reengagement": "ayana_reengager",
    "report_ready": "ayana_report_ready",
}


def whatsapp_enabled() -> bool:
    return os.environ.get("WHATSAPP_ENABLED", "false").strip().lower() == "true"


def _creds() -> Tuple[str, str]:
    """Returns (access_token, phone_number_id)."""
    return (
        os.environ.get("META_WA_ACCESS_TOKEN", "").strip(),
        os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip(),
    )


def meta_auth_header() -> Dict[str, str]:
    """Bearer header for authenticated GETs against Meta's API (e.g. media download)."""
    token, _ = _creds()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get_template_name(template_key: str) -> str:
    return _CATEGORY_TEMPLATE_NAME.get(template_key, "")


def _messages_url(phone_id: str) -> str:
    return f"https://graph.facebook.com/{_GRAPH_VERSION}/{phone_id}/messages"


def _extract_message_id(resp_json: Dict[str, Any]) -> str:
    try:
        return resp_json.get("messages", [{}])[0].get("id", "")
    except Exception:
        return ""


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
        resp.raise_for_status()
        msg_id = _extract_message_id(resp.json())
        logger.info("[wa] Plain text sent to %s id=%s", to_phone, msg_id)
        return {"status": "sent", "sid": msg_id, "to": to_phone}
    except Exception as e:
        logger.error("[wa] Send failed to %s: %s", to_phone, e, exc_info=True)
        return {"status": "failed", "detail": str(e), "to": to_phone}


def _build_body_params(content_variables: Dict[str, str]) -> List[Dict[str, str]]:
    """Meta template body params are positional — sort by the {{n}} index."""
    ordered_keys = sorted(content_variables.keys(), key=lambda k: int(k))
    return [{"type": "text", "text": content_variables[k]} for k in ordered_keys]


def _send_content_template_once(
    to_phone: str, template_name: str, language: str, content_variables: Dict[str, str], template_key: str
) -> Optional[Dict[str, Any]]:
    token, phone_id = _creds()
    if not whatsapp_enabled() or not token or not phone_id:
        logger.info("[wa] Template %s skipped (test mode) for %s", template_key, to_phone)
        return None
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
    resp.raise_for_status()
    msg_id = _extract_message_id(resp.json())
    return {"status": "sent", "sid": msg_id, "template_type": template_key}


async def _send_content_template_with_retry(
    to_phone: str, template_name: str, language: str, content_variables: Dict[str, str], template_key: str
) -> Optional[Dict[str, Any]]:
    """Retry on failure with fallback to plain text if template fails."""
    token, phone_id = _creds()
    if not whatsapp_enabled() or not token or not phone_id:
        return _send_content_template_once(to_phone, template_name, language, content_variables, template_key)

    last_error = None
    for attempt in range(1, MAX_SEND_RETRIES + 1):
        try:
            res = _send_content_template_once(to_phone, template_name, language, content_variables, template_key)
            if res and res.get("sid"):
                return res
        except Exception as e:
            last_error = e
            logger.warning("[wa] Send attempt %s/%s failed (type=%s) to %s: %s", attempt, MAX_SEND_RETRIES, template_key, to_phone, e)
            if attempt < MAX_SEND_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

    if DELIVERY_FALLBACK_ENABLED:
        logger.warning("[wa] Template %s failed for %s — falling back to plain text send", template_key, to_phone)
        body_text = content_variables.get("2") or content_variables.get("1") or "Hello from AYANA 💛"
        return send_whatsapp(to_phone, body_text)

    logger.error("[wa] All %s send attempts failed (type=%s) to %s: %s", MAX_SEND_RETRIES, template_key, to_phone, last_error)
    return {"status": "failed", "detail": str(last_error), "template_type": template_key}


MIC_HINT = {
    "en": "💛 Want to talk? Press & hold the 🎤 mic below and speak — anytime.",
    "te": "💛 మాట్లాడాలనుకుంటున్నారా? కింద ఉన్న 🎤 మైక్‌ను నొక్కి పట్టుకుని మాట్లాడండి — ఎప్పుడైనా.",
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
    """
    Meta interactive button messages are sent inline every time — no
    pre-registered Content resource needed.
    """
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
        resp.raise_for_status()
        msg_id = _extract_message_id(resp.json())
        return {"status": "sent", "sid": msg_id, "context": context}
    except Exception as e:
        logger.warning("[wa] Quick-reply API failed (%s), fallback to plain text: %s", context, e)
        btn_text = " ".join(f"{i+1}) {label}" for i, (label, _) in enumerate(safe_buttons))
        return send_whatsapp(to_phone, f"{body}\n\n👉 {btn_text}")


# ── Session state ────────────────────────────────────────────────────────
# MIGRATION NOTE: dropped the `db` parameter from every function in this
# section (get_session, is_session_open, refresh_session, mark_opener_sent,
# mark_reengagement_sent) — same "import get_pool directly" pattern used
# throughout this migration. Update any call sites accordingly.

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


# ── Approved-template variable resolver ─────────────────────────────────
_NON_MEDICINE_REMINDER_LABELS = {
    "water": "water",
    "bp_check": "BP check",
    "sugar_check": "sugar check",
    "health_check": "health check",
}


def _language_native_medicine_placeholder(language: str) -> str:
    """When medicine_name is empty (no meds set on parent), fall back
    to a placeholder in the parent's language so the Meta template
    doesn't stuff English 'your medicine' into a Telugu/Hindi sentence."""
    lang = (language or "en").lower()
    return {"en": "your medicine", "te": "మందు", "hi": "दवाई"}.get(lang, "your medicine")


def _build_approved_template_vars(
    template_key: str, category: str, preferred: str, parent: Dict[str, Any], language: str, medicine_name: str
) -> Dict[str, str]:
    if template_key == "opener":
        return {"1": preferred, "2": parent_relation_label(parent, language)}
    if template_key == "medicine":
        if category == "medicine":
            name = medicine_name or _language_native_medicine_placeholder(language)
            label = f"{name} tablet" if not name.lower().endswith("tablet") else name
        else:
            label = _NON_MEDICINE_REMINDER_LABELS.get(category, medicine_name or _language_native_medicine_placeholder(language))
        return {"1": preferred, "2": label}
    return {"1": preferred}  # mood, meal, reengagement


# ── Public sending API ───────────────────────────────────────────────────
# MIGRATION NOTE: dropped `db` from every function below too — parent
# records now come in as plain dicts keyed by "id" (Postgres uuid),
# not Mongo's "_id". render_slot_body_async's signature also needs to
# drop `db` when templates_data.py is converted next — that file is
# the one remaining piece these functions depend on.

async def send_template_for_category(parent: Dict[str, Any], category: str, day_index: int, variants_per_slot: int, medicine_name: str = "") -> Dict[str, Any]:
    """
    Unified entry point: resolves category -> one of the approved
    templates, renders the {{2}} body via render_slot_body (nicknames,
    season, habits, stories all applied), sends with retry.
    """
    parent_id = parent["id"]
    phone = parent.get("phone", "")
    language = parent.get("language", "en")
    preferred = parent.get("preferred_name") or parent.get("name", "") or "Amma"

    if await is_session_open(parent_id):
        return await send_dynamic_checkin(parent, category, day_index, variants_per_slot, medicine_name)

    template_key = get_template_sid_key(category)
    template_name = _get_template_name(template_key)
    body = await render_slot_body_async(category, language, parent, day_index, medicine_name or _language_native_medicine_placeholder(language), variants_per_slot)

    if template_name and whatsapp_enabled():
        content_vars = _build_approved_template_vars(template_key, category, preferred, parent, language, medicine_name)
        result = await _send_content_template_with_retry(phone, template_name, language, content_vars, template_key)
    else:
        result = send_whatsapp(phone, body)

    if result and result.get("status") in ("sent", "simulated"):
        await mark_opener_sent(parent_id, template_key)
    return result or {"status": "failed", "detail": "No result from template send"}


# Back-compat named wrappers (used by scheduler / API for explicit sends)
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
    """FREE in-session quick-reply — no approval needed while session is open."""
    parent_id = parent["id"]
    phone = parent.get("phone", "")
    language = parent.get("language", "en")

    if not await is_session_open(parent_id):
        return await send_template_for_category(parent, category, day_index, variants_per_slot, medicine_name)

    body = await render_slot_body_async(category, language, parent, day_index, medicine_name or _language_native_medicine_placeholder(language), variants_per_slot)
    buttons = render_slot_buttons(category, language)
    return await _send_quick_reply(phone, body, buttons, context=category, language=language)


async def send_reengagement(parent: Dict[str, Any], reengagement_hours: int = 4) -> Dict[str, Any]:
    """Fires after `reengagement_hours` (user-configurable per schedule, not a static tier constant)."""
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

    template_name = _get_template_name("reengagement")
    if template_name and whatsapp_enabled():
        result = await _send_content_template_with_retry(phone, template_name, language, {"1": preferred}, "reengagement")
    else:
        body = f"{preferred}, we miss hearing from you 💛\n\nJust checking — are you alright?"
        result = send_whatsapp(phone, body)

    if result and result.get("status") in ("sent", "simulated"):
        await mark_reengagement_sent(parent_id)
    return result or {"status": "failed", "detail": "No result"}


async def send_moment(parent: Dict[str, Any], text: str, sender_name: str, image_url: str = "", image_urls: List[str] = None) -> Dict[str, Any]:
    """Two-way moment: a child pushes a warm message/photo, delivered to the
    parent on WhatsApp with a gentle intro. Available on all plans.

    Supports up to 2 images via image_urls. If image_url (single) is provided, it is
    appended to image_urls for backward compatibility."""
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
    """Notify a child/family member that a monthly report is ready."""
    template_name = _get_template_name("report_ready")
    content_vars = {"1": parent_display or "your parent"}
    return await _send_content_template_with_retry(to_phone, template_name, language, content_vars, "report_ready")


# ── Media resolution ─────────────────────────────────────────────────────
async def resolve_meta_media_url(media_id: str) -> Optional[str]:
    """Meta only gives you a media ID in the webhook payload — you have to
    look up the actual (temporary, ~5min-lived) CDN URL separately, then
    download it with the same Bearer auth header."""
    token, _ = _creds()
    if not token or not media_id:
        return None
    try:
        url = f"https://graph.facebook.com/{_GRAPH_VERSION}/{media_id}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return resp.json().get("url")
    except Exception as e:
        logger.error("[wa] Failed to resolve media URL for %s: %s", media_id, e)
        return None


# ── Signature validation ─────────────────────────────────────────────────
def verify_meta_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verify inbound Meta webhook signature (X-Hub-Signature-256 header,
    format 'sha256=<hex>'), computed as HMAC-SHA256 of the raw request
    body using the Meta app's secret (META_WA_APP_SECRET).
    """
    app_secret = os.environ.get("META_WA_APP_SECRET", "").strip()
    if not app_secret:
        logger.warning("[wa] META_WA_APP_SECRET not set — cannot verify webhook signature")
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Emergency keyword layer (fast-path fail-safe; see distress_detection.py for layer 2) ──
def detect_emergency(text: str, extra_keywords: Optional[List[str]] = None) -> List[str]:
    if not text:
        return []
    keywords = list(DEFAULT_EMERGENCY_KEYWORDS) + (extra_keywords or [])
    low = text.lower()
    matched = [k for k in keywords if k.lower() in low]
    if matched:
        logger.warning("[wa] Emergency keyword(s) matched in inbound text")
    return matched


# ── Intent routing ───────────────────────────────────────────────────────
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
    """Return a feeling state if *text* contains a known local-language phrase."""
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