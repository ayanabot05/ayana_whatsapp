
"""
translation_engine.py — Dynamic, AI-assisted template variants (NEW).

Why this exists: templates_data.py's SLOT_VARIANTS is a static, hand
-written dict — 14 categories x 3 languages x up to 7 variants each,
~560 lines. That's the right choice for the launch languages (en/te/hi)
because it's free, instant, and a human reviewed every line of copy
that goes to someone's elderly parent. But it means adding language #4
(say, Kannada or Malayalam for a new user base) currently requires an
engineer to hand-write ~100 more lines before that user can even sign
up.

This module adds a fallback path, not a replacement:

  1. render_slot_body_dynamic() first checks the static SLOT_VARIANTS
     (unchanged, zero-cost, zero-latency — this is still the path for
     every en/te/hi send today).
  2. If the requested language isn't in the static set, it checks
     `template_variants_cache` in Postgres for a previously-generated
     translation of that (category, language) pair.
  3. Only on a cache MISS does it call Sarvam's translation API once,
     store the result, and serve from cache forever after. This is the
     "token optimization" — every phrase is AI-translated exactly once
     per (category, language), never per-send, never per-user. A
     household's daily messages never trigger an API call after the
     first cache warm.

This keeps the hot path (existing launch languages) exactly as fast
and free as before, while making "we're expanding to a new state /
language" a config change (add the language code) instead of an
engineering task — without silently machine-translating copy for
languages you've already hand-reviewed.

MIGRATION NOTE: previously took a Mongo `db` handle as a parameter.
Now imports the Postgres pool directly via get_pool(). Callers should
drop the `db` argument from get_variants() calls.
"""

import logging
import os
from datetime import datetime, timezone

import httpx

from database import get_pool
from templates_data import SLOT_VARIANTS

logger = logging.getLogger("ayana.translation")

_SARVAM_TRANSLATE_URL = os.environ.get("SARVAM_TRANSLATE_URL", "https://api.sarvam.ai/translate")
_TIMEOUT = 10.0

# BCP-47-ish codes Sarvam's translate API expects; extend as you add
# languages. Only languages listed here are eligible for dynamic
# generation — an unlisted code fails safe to English rather than
# guessing a code Sarvam won't recognize.
_SARVAM_LANG_CODES = {
    "kn": "kn-IN",  # Kannada
    "ml": "ml-IN",  # Malayalam
    "ta": "ta-IN",  # Tamil
    "mr": "mr-IN",  # Marathi
    "bn": "bn-IN",  # Bengali
    "gu": "gu-IN",  # Gujarati
}


def dynamic_translation_enabled() -> bool:
    return os.environ.get("DYNAMIC_TRANSLATION_ENABLED", "false").strip().lower() == "true"


async def _translate_variants(english_variants: list[str], target_lang: str) -> list[str] | None:
    """
    Translates each English template variant to `target_lang` via Sarvam.
    Placeholders like {nick1}, {city}, {season} etc. are preserved
    verbatim (Sarvam is instructed not to translate bracketed tokens),
    since render_slot_body() fills them in after translation.
    Returns None on any failure — caller falls back to English.
    """
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    lang_code = _SARVAM_LANG_CODES.get(target_lang)
    if not api_key or not lang_code:
        return None

    translated = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for text in english_variants:
                resp = await client.post(
                    _SARVAM_TRANSLATE_URL,
                    headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
                    json={
                        "input": text,
                        "source_language_code": "en-IN",
                        "target_language_code": lang_code,
                        # Keep {placeholder} tokens untranslated — filled in later.
                        "preserve_formatting": True,
                    },
                )
                if resp.status_code not in (200, 201):
                    logger.warning("[translate] Sarvam error %s for %r", resp.status_code, text[:40])
                    return None
                data = resp.json()
                out = data.get("translated_text", "").strip()
                if not out:
                    return None
                translated.append(out)
    except Exception as e:
        logger.warning("[translate] Sarvam translate failed: %s", e)
        return None
    return translated


async def get_variants(category: str, language: str) -> list[str] | None:
    """
    Returns rotational message variants for (category, language) beyond
    the static set, using a cache-first strategy. Returns None if
    dynamic translation is disabled, unsupported, or fails — callers
    should fall back to English (templates_data.py already does this).
    """
    if not dynamic_translation_enabled():
        return None
    if language in ("en", "te", "hi"):
        return None  # static set already covers these — no AI call needed

    async with get_pool().acquire() as conn:
        cached = await conn.fetchrow(
            "select variants from template_variants_cache where category = $1 and language = $2",
            category, language,
        )
        if cached and cached["variants"]:
            return cached["variants"]

        english_variants = (SLOT_VARIANTS.get(category) or {}).get("en")
        if not english_variants:
            return None

        translated = await _translate_variants(english_variants, language)
        if not translated:
            return None

        await conn.execute(
            """
            insert into template_variants_cache (category, language, variants, source, generated_at)
            values ($1, $2, $3::jsonb, 'sarvam_translate', now())
            on conflict (category, language) do update
                set variants = excluded.variants,
                    source = excluded.source,
                    generated_at = now()
            """,
            category, language, translated,
        )

    logger.info("[translate] Cached %d variants for %s/%s", len(translated), category, language)
    return translated


def supported_dynamic_languages() -> list[str]:
    """Languages eligible for on-demand AI translation, for /config to expose to the frontend."""
    return sorted(_SARVAM_LANG_CODES.keys()) if dynamic_translation_enabled() else []


# ── NEW: Voice transcript translation for child ──────────────────────────
_VOICE_LANG_MAP = {
    "en": "en-IN",
    "te": "te-IN", 
    "hi": "hi-IN",
    **_SARVAM_LANG_CODES  # kn, ml, ta, etc from above
}

async def translate_text(text: str, target_language: str, source_language: str = "en") -> str:
    """Translate free-form voice transcript to child's language - Issue #2"""
    if not text or not text.strip():
        return text
    
    # Same language = no translation needed
    if source_language == target_language:
        return text

    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not api_key:
        logger.warning("[translate] SARVAM_API_KEY missing, returning original")
        return text

    src_code = _VOICE_LANG_MAP.get(source_language, "en-IN")
    tgt_code = _VOICE_LANG_MAP.get(target_language, "en-IN")
    
    if src_code == tgt_code:
        return text

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _SARVAM_TRANSLATE_URL,
                headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
                json={
                    "input": text,
                    "source_language_code": src_code,
                    "target_language_code": tgt_code,
                },
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                translated = data.get("translated_text", "").strip()
                if translated:
                    logger.info(f"[translate] Voice {source_language}->{target_language}: {len(text)} chars -> {len(translated)} chars")
                    return translated
            logger.warning(f"[translate] Failed {resp.status_code}: {resp.text[:100]}")
            return text
    except Exception as e:
        logger.warning(f"[translate] Voice translate error: {e}")
        return text

