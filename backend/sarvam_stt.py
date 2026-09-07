"""
sarvam_stt.py — Sarvam AI Speech-to-Text for AYANA voice note replies.

Flow:
  Parent taps button -> ButtonPayload -> no STT, instant intent
  Parent sends voice note -> Meta media URL -> Download with Bearer Auth -> Sarvam STT -> transcript -> intent + emergency check

Unchanged from v1 except: callers (server.py's _record_reply) now also
pass the transcript through distress_detection.assess_transcript() for
the second ML layer + logging — see distress_detection.py.

Falls back gracefully when SARVAM_API_KEY missing.
"""

import logging
import os
import asyncio

import httpx

logger = logging.getLogger("ayana.stt")

_SARVAM_URL = "https://api.sarvam.ai/speech-to-text"
_TIMEOUT = 20.0

_LANG_MAP: dict[str, str] = {"en": "en-IN", "te": "te-IN", "hi": "hi-IN"}


def stt_enabled() -> bool:
    return bool(os.environ.get("SARVAM_API_KEY", "").strip())


def confidence_label(score: float | None) -> str:
    """Map a 0-1 confidence to a human-facing band the child message can use.

    Thresholds are env-tunable (STT_CONF_HIGH / STT_CONF_MEDIUM) so you can
    dial how cautiously the child's message is worded without a code change."""
    if score is None:
        return "unknown"
    try:
        high = float(os.environ.get("STT_CONF_HIGH", "0.8"))
        medium = float(os.environ.get("STT_CONF_MEDIUM", "0.55"))
    except ValueError:
        high, medium = 0.8, 0.55
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def _heuristic_confidence(transcript: str) -> float:
    """Best-effort confidence when Sarvam returns no score of its own.

    Longer, cleaner transcripts are more trustworthy; 1-word / noisy ones less
    so. This is intentionally conservative — it only gates how we *word* the
    child's message, never whether we forward the voice note."""
    if not transcript:
        return 0.0
    words = transcript.split()
    n = len(words)
    if n >= 6:
        base = 0.9
    elif n >= 3:
        base = 0.72
    elif n == 2:
        base = 0.55
    else:
        base = 0.4
    clean = sum(1 for c in transcript if c.isalnum() or c.isspace())
    ratio = clean / max(len(transcript), 1)
    return max(0.0, min(1.0, base * (0.6 + 0.4 * ratio)))


def _extract_confidence(data: dict, transcript: str) -> float:
    """Prefer a confidence Sarvam gives us; fall back to a heuristic."""
    for key in ("confidence", "confidence_score", "score"):
        v = data.get(key)
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
    metrics = data.get("metrics")
    if isinstance(metrics, dict) and isinstance(metrics.get("confidence"), (int, float)):
        return max(0.0, min(1.0, float(metrics["confidence"])))
    return _heuristic_confidence(transcript)


async def transcribe_voice_note(media_url: str, language: str = "en", auth_headers: dict | None = None) -> str | None:
    """Backward-compatible wrapper — returns just the transcript string (or None)."""
    result = await transcribe_voice_note_detailed(media_url, language, auth_headers)
    return result["transcript"] if result else None


async def transcribe_voice_note_detailed(media_url: str, language: str = "en", auth_headers: dict | None = None) -> dict | None:
    """
    Transcribe a WhatsApp voice note via Sarvam AI.

    Returns {"transcript": str, "confidence": float 0-1, "confidence_label": str}
    or None when transcription wasn't possible at all (no key, download/API
    failure, empty result). Never raises — the caller always forwards the audio
    regardless, and just words its message to the child based on confidence.
    """
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    endpoint = os.environ.get("SARVAM_STT_URL", _SARVAM_URL).strip()
    if not api_key:
        logger.info("[stt] SARVAM_API_KEY not set — skipping transcription for %s", media_url)
        return None

    headers = auth_headers or {}

    audio_bytes = None
    content_type = "audio/ogg"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                dl_resp = await client.get(media_url, headers=headers, follow_redirects=True)
            if dl_resp.status_code == 200 and len(dl_resp.content) > 1000:
                audio_bytes = dl_resp.content
                content_type = dl_resp.headers.get("content-type", "audio/ogg")
                break
            await asyncio.sleep(1 * (attempt + 1))
        except Exception as exc:
            logger.warning("[stt] Download attempt %s error: %s", attempt + 1, exc)
            await asyncio.sleep(1 * (attempt + 1))

    if not audio_bytes:
        logger.error("[stt] Failed to download audio after 3 tries: %s", media_url)
        return None

    lang_code = _LANG_MAP.get(language, "en-IN")
    ext = _ext_from_content_type(content_type)
    filename = f"voice_note.{ext}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                endpoint,
                headers={"api-subscription-key": api_key},
                files={"file": (filename, audio_bytes, content_type)},
                data={"model": "saarika:v2.5", "language_code": lang_code, "with_timestamps": "false", "with_diarization": "false", "with_disfluencies": "false"},
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            transcript = (data.get("transcript") or "").strip() or (data.get("text") or "").strip()
            if not transcript:
                return None
            confidence = _extract_confidence(data, transcript)
            logger.info("[stt] Transcribed [%s] %s chars confidence=%.2f (%s)",
                        lang_code, len(transcript), confidence, confidence_label(confidence))
            return {"transcript": transcript, "confidence": confidence, "confidence_label": confidence_label(confidence)}
        logger.error("[stt] Sarvam API error %s", resp.status_code)
        return None
    except httpx.TimeoutException:
        logger.error("[stt] Sarvam STT timed out for %s", media_url)
        return None
    except Exception as exc:
        logger.exception("[stt] Unexpected error: %s", exc)
        return None


def _ext_from_content_type(ct: str) -> str:
    ct = ct.split(";")[0].strip().lower()
    return {
        "audio/ogg": "ogg", "audio/ogg; codecs=opus": "ogg", "audio/mpeg": "mp3",
        "audio/mp4": "m4a", "audio/wav": "wav", "audio/x-wav": "wav",
        "audio/webm": "webm", "audio/amr": "amr", "audio/3gpp": "3gp", "audio/3gpp2": "3gp",
    }.get(ct, "ogg")