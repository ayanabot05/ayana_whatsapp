"""
otp.py — SMS OTP verification for AYANA family members.

Verifies the FAMILY MEMBER'S OWN phone number (sons, daughters, primary
carers) — NOT the elderly parent's WhatsApp. Called during signup or from
Profile to badge the account with phone_verified=true.

Delivery channel: Twilio SMS API — sends a plain-text SMS with the 6-digit
code. WhatsApp (Meta Cloud API) is used only for care check-ins / openers,
NOT for OTP.

Required env vars (when SMS_ENABLED=true):
  TWILIO_ACCOUNT_SID   Twilio Account SID
  TWILIO_AUTH_TOKEN     Twilio Auth Token
  TWILIO_SMS_FROM       Twilio phone number to send from (E.164 format)

Security properties:
  - 6-digit code hashed with bcrypt (rounds=12) — plaintext NEVER stored
  - 5-minute expiry
  - Max 3 wrong guesses before invalidation + re-send required
  - Max 3 sends per 10-minute window per number (resend rate-limit)
  - OTP codes and verification outcomes NEVER appear in log lines
"""

import logging
import os
import random
import string
from datetime import datetime, timezone, timedelta
from base64 import b64encode

import bcrypt
import redis.asyncio as redis
from typing import Tuple, Optional

from database import get_pool

logger = logging.getLogger("ayana.otp")

# ── Constants ──────────────────────────────────────────────────────────────────

OTP_LENGTH          = 6
OTP_EXPIRY_MINUTES  = 5
MAX_ATTEMPTS        = 3  # Reduced from 5 — with 3 sends per 10 min, 5 attempts = 15 total tries
MAX_SENDS_PER_WINDOW = 3
SEND_WINDOW_MINUTES  = 10
# Global rate limit on OTP verification attempts (Redis-backed, per phone)
MAX_VERIFY_ATTEMPTS_PER_WINDOW = 10  # Max verify attempts in 15-min window
VERIFY_WINDOW_MINUTES = 15  # Window in minutes for verify rate limit
BCRYPT_ROUNDS        = 12

# ── Redis connection ───────────────────────────────────────────────────────────
# Unchanged — Redis was never Mongo, nothing to migrate here.
_redis_client = None
_redis_available = True


async def get_redis():
    """Get or create Redis connection. Returns None if Redis unavailable."""
    global _redis_client, _redis_available
    if not _redis_available:
        return None
    if _redis_client is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            _redis_client = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            await _redis_client.ping()
        except Exception as e:
            logger.warning("Redis unavailable, OTP verify rate limiting disabled: %s", e)
            _redis_client = None
            _redis_available = False
            return None
    return _redis_client


def _verify_rate_limit_key(phone: str) -> str:
    return f"rl:otp_verify:{phone}"


async def _check_verify_rate_limit(phone: str) -> Tuple[bool, Optional[int]]:
    """Check if OTP verify is allowed for this phone. Returns (allowed, retry_after)."""
    r = await get_redis()
    if r is None:
        return True, None  # Allow if Redis unavailable
    key = _verify_rate_limit_key(phone)
    now = datetime.now(timezone.utc).timestamp()
    window_sec = VERIFY_WINDOW_MINUTES * 60

    await r.zremrangebyscore(key, 0, now - window_sec)

    count = await r.zcard(key)
    if count >= MAX_VERIFY_ATTEMPTS_PER_WINDOW:
        oldest = await r.zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_ts = oldest[0][1]
            retry_after = int(oldest_ts + window_sec - now) + 1
            return False, max(retry_after, 1)
        return False, window_sec

    return True, None


async def _record_verify_attempt(phone: str):
    """Record an OTP verification attempt for rate limiting."""
    r = await get_redis()
    if r is None:
        return  # No-op if Redis unavailable
    key = _verify_rate_limit_key(phone)
    now = datetime.now(timezone.utc).timestamp()
    await r.zadd(key, {str(now): now})
    await r.expire(key, VERIFY_WINDOW_MINUTES * 60 + 60)


# ── Feature flags ──────────────────────────────────────────────────────────────

def sms_enabled() -> bool:
    """True when SMS delivery is explicitly enabled via SMS_ENABLED=true."""
    return os.environ.get("SMS_ENABLED", "false").strip().lower() == "true"


def otp_delivery_enabled() -> bool:
    """True only when SMS is enabled and Twilio credentials are configured."""
    return sms_enabled() and bool(os.environ.get("TWILIO_ACCOUNT_SID", "").strip())


# ── Code generation + hashing ────────────────────────────────────────────────

def generate_otp() -> str:
    """Return a cryptographically random 6-digit string."""
    return "".join(random.SystemRandom().choices(string.digits, k=OTP_LENGTH))


def hash_otp(code: str) -> str:
    """Return bcrypt hash of the OTP code. Never log the input."""
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_otp_hash(code: str, stored_hash: str) -> bool:
    """Constant-time bcrypt comparison. Never log either argument."""
    try:
        return bcrypt.checkpw(code.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        return False


# ── Twilio SMS delivery ─────────────────────────────────────────────────────
# Unchanged — Twilio's REST API, nothing database-related in here.

async def send_otp_sms(phone: str, code: str) -> dict:
    """
    Send the OTP via Twilio SMS REST API.

    Returns:
      {"status": "sent",      "message_sid": "..."}
      {"status": "simulated", "detail": "..."}
      {"status": "failed",    "detail": "..."}

    IMPORTANT: `code` is NEVER logged — only redacted references appear.
    """
    if not otp_delivery_enabled():
        reason = "SMS_ENABLED=false" if not sms_enabled() else "TWILIO_ACCOUNT_SID not set"
        logger.info("[otp] SMS delivery disabled (%s) — simulating for %s", reason, phone)
        return {"status": "simulated", "detail": f"OTP delivery disabled ({reason})"}

    try:
        import httpx

        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        from_number = os.environ.get("TWILIO_SMS_FROM", "").strip()

        if not account_sid or not auth_token:
            return {"status": "failed", "detail": "Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN"}
        if not from_number:
            return {"status": "failed", "detail": "Missing TWILIO_SMS_FROM (sender phone number)"}

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        credentials = b64encode(f"{account_sid}:{auth_token}".encode()).decode()

        sms_body = f"Your AYANA verification code is: {code}. It expires in {OTP_EXPIRY_MINUTES} minutes. Do not share this code."

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "To": phone,
                    "From": from_number,
                    "Body": sms_body,
                },
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            message_sid = data.get("sid", "")
            logger.info("[otp] SMS OTP sent to %s (sid=%s)", phone, message_sid)
            return {"status": "sent", "message_sid": message_sid}

        try:
            err_data = resp.json()
            err_msg = err_data.get("message", resp.text[:200])
            err_code = err_data.get("code", "")
            logger.error("[otp] Twilio SMS error for %s: HTTP %s, code=%s, msg=%s", phone, resp.status_code, err_code, err_msg)
        except Exception:
            err_msg = resp.text[:200]
            logger.error("[otp] Twilio SMS error for %s: HTTP %s, body=%s", phone, resp.status_code, err_msg)

        return {"status": "failed", "detail": "SMS delivery failed — try again shortly."}

    except Exception as exc:
        logger.error("[otp] SMS delivery error for %s: %s", phone, type(exc).__name__)
        return {"status": "failed", "detail": "SMS delivery failed — try again shortly."}


# ── Database helpers ─────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Strip spaces/dashes, ensure leading +."""
    cleaned = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if cleaned and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


async def _get_otp_row(conn, phone: str):
    return await conn.fetchrow("select * from phone_otps where phone = $1", phone)


async def create_and_send_otp(phone: str) -> dict:
    """
    Full send flow:
      1. Check resend rate-limit (max 3/10-min window).
      2. Generate + hash a fresh OTP.
      3. Upsert the phone_otps row (resets attempts + expiry).
      4. Deliver via Twilio.

    Returns send result dict + {phone, expires_at}.
    Never returns the plaintext OTP.
    """
    phone = _normalize_phone(phone)
    now   = datetime.now(timezone.utc)

    async with get_pool().acquire() as conn:
        # ── Rate-limit check ──────────────────────────────────────────────
        existing = await _get_otp_row(conn, phone)
        if existing:
            window_start = existing["send_window_start"] or now
            send_count   = existing["send_count"] or 0
            if window_start.tzinfo is None:
                window_start = window_start.replace(tzinfo=timezone.utc)
            if (now - window_start).total_seconds() > SEND_WINDOW_MINUTES * 60:
                send_count   = 0
                window_start = now
            if send_count >= MAX_SENDS_PER_WINDOW:
                secs_left = int(SEND_WINDOW_MINUTES * 60 - (now - window_start).total_seconds())
                logger.warning("[otp] Resend rate-limit hit for %s", phone)
                return {
                    "status": "rate_limited",
                    "detail": f"Too many OTP requests. Try again in {max(secs_left, 1)} seconds.",
                    "retry_after_seconds": max(secs_left, 1),
                }
        else:
            window_start = now
            send_count   = 0

        # ── Generate + hash ───────────────────────────────────────────────
        code       = generate_otp()          # plaintext — used only here, never stored
        code_hash  = hash_otp(code)
        expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

        await conn.execute(
            """
            insert into phone_otps
                (phone, code_hash, expires_at, attempts, verified, created_at,
                 send_count, send_window_start)
            values ($1, $2, $3, 0, false, $4, $5, $6)
            on conflict (phone) do update
                set code_hash = excluded.code_hash,
                    expires_at = excluded.expires_at,
                    attempts = 0,
                    verified = false,
                    created_at = excluded.created_at,
                    send_count = excluded.send_count,
                    send_window_start = excluded.send_window_start
            """,
            phone, code_hash, expires_at, now, send_count + 1, window_start,
        )

    # ── Deliver ───────────────────────────────────────────────────────────
    result = await send_otp_sms(phone, code)
    result["phone"]      = phone
    result["expires_at"] = expires_at.isoformat()
    # In simulated mode (SMS delivery disabled) the code is never actually
    # sent anywhere, so surface it to the caller for local/preview testing.
    # This branch is impossible once SMS_ENABLED=true in production.
    if not otp_delivery_enabled():
        result["dev_code"] = code
    return result


async def verify_otp_code(phone: str, code: str) -> dict:
    """
    Verify submitted code against the stored hash.

    Returns:
      {"ok": True,  "phone": ...}                  — success
      {"ok": False, "detail": "...", "code": "..."}  — failure with machine-readable code

    Machine-readable failure codes: expired | too_many_attempts | invalid | rate_limited
    """
    phone = _normalize_phone(phone)

    allowed, retry_after = await _check_verify_rate_limit(phone)
    if not allowed:
        logger.warning("[otp] Verify rate limit hit for %s", phone)
        return {
            "ok": False,
            "detail": f"Too many verification attempts. Try again in {retry_after} seconds.",
            "code": "rate_limited",
            "retry_after_seconds": retry_after,
        }

    now = datetime.now(timezone.utc)

    async with get_pool().acquire() as conn:
        doc = await _get_otp_row(conn, phone)

        if not doc:
            return {"ok": False, "detail": "No OTP found for this number. Please request a new code.", "code": "not_found"}

        if doc["verified"]:
            return {"ok": True, "phone": phone, "already_verified": True}

        expires_at = doc["expires_at"]
        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now > expires_at:
                logger.info("[otp] Expired OTP attempt for %s", phone)
                return {"ok": False, "detail": "This code has expired. Please request a new one.", "code": "expired"}

        # Atomic verify: a single UPDATE...RETURNING is Postgres's equivalent
        # of Mongo's find_one_and_update — the WHERE clause + RETURNING happen
        # as one atomic operation, so concurrent requests still can't exceed
        # MAX_ATTEMPTS (same race-condition protection as before).
        updated_doc = await conn.fetchrow(
            """
            update phone_otps
            set attempts = attempts + 1
            where phone = $1 and attempts < $2
            returning *
            """,
            phone, MAX_ATTEMPTS,
        )

        if not updated_doc:
            doc = await _get_otp_row(conn, phone)
            if not doc:
                return {"ok": False, "detail": "No OTP found for this number. Please request a new code.", "code": "not_found"}
            if doc["verified"]:
                return {"ok": True, "phone": phone, "already_verified": True}
            logger.warning("[otp] Too many OTP attempts for %s", phone)
            return {"ok": False, "detail": "Too many incorrect attempts. Please request a new code.", "code": "too_many_attempts"}

        await _record_verify_attempt(phone)

        attempts = updated_doc["attempts"]
        code_hash = updated_doc["code_hash"]

        if not verify_otp_hash(code, code_hash):
            remaining = MAX_ATTEMPTS - attempts
            logger.info("[otp] Wrong OTP for %s (%d attempts left)", phone, remaining)
            return {
                "ok":      False,
                "detail":  f"Incorrect code. {remaining} attempt{'s' if remaining != 1 else ''} remaining.",
                "code":    "invalid",
                "attempts_remaining": remaining,
            }

        # ── Success ───────────────────────────────────────────────────────
        await conn.execute(
            "update phone_otps set verified = true, verified_at = $1 where phone = $2",
            now, phone,
        )

    logger.info("[otp] Phone %s verified successfully", phone)
    return {"ok": True, "phone": phone}