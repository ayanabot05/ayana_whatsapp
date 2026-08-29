"""
Redis-backed distributed rate limiting for AYANA.

Replaces in-memory slowapi limiter and _login_attempts dict with
Redis atomic operations for horizontal scaling support.

Limits (configurable via env):
- OTP send: 5 requests / 15 min (per phone)
- Login: 10 attempts / 15 min (per email + IP)
- API general: 100 requests / minute (per IP)

Gracefully degrades to allow-all if Redis is unavailable (logs warning).
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import redis.asyncio as redis
from fastapi import Request, HTTPException, Depends

logger = logging.getLogger("ayana.rate_limit")

# ── Redis connection ────────────────────────────────────────────────────────────

_redis_client: Optional[redis.Redis] = None
_redis_available = True  # Track if Redis is reachable


async def get_redis() -> Optional[redis.Redis]:
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
                max_connections=int(os.environ.get("REDIS_MAX_CONNECTIONS", "20")),
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # Test connection
            await _redis_client.ping()
        except Exception as e:
            logger.warning("Redis unavailable, rate limiting disabled: %s", e)
            _redis_client = None
            _redis_available = False
            return None
    return _redis_client


async def close_redis():
    """Close Redis connection (for shutdown)."""
    global _redis_client, _redis_available
    if _redis_client:
        try:
            await _redis_client.close()
        except Exception:
            pass
        _redis_client = None
        _redis_available = True  # Reset for potential reconnect


# ── Rate limit configuration ────────────────────────────────────────────────────

# OTP send rate limit: 5 requests per 15 minutes per phone
OTP_SEND_LIMIT = int(os.environ.get("RL_OTP_SEND_LIMIT", "5"))
OTP_SEND_WINDOW_SEC = int(os.environ.get("RL_OTP_SEND_WINDOW_SEC", str(15 * 60)))

# Login brute-force: 10 attempts per 15 minutes per (email, IP)
LOGIN_ATTEMPT_LIMIT = int(os.environ.get("RL_LOGIN_ATTEMPT_LIMIT", "10"))
LOGIN_WINDOW_SEC = int(os.environ.get("RL_LOGIN_WINDOW_SEC", str(15 * 60)))
LOGIN_LOCKOUT_SEC = int(os.environ.get("RL_LOGIN_LOCKOUT_SEC", str(15 * 60)))

# General API rate limit: 100 requests per minute per IP
API_LIMIT = int(os.environ.get("RL_API_LIMIT", "100"))
API_WINDOW_SEC = int(os.environ.get("RL_API_WINDOW_SEC", "60"))


# ── Redis keys ────────────────────────────────────────────────────────────────

def _otp_send_key(phone: str) -> str:
    return f"rl:otp_send:{phone}"


def _login_attempt_key(email: str, ip: str) -> str:
    return f"rl:login:{email.lower()}:{ip}"


def _api_key(ip: str) -> str:
    return f"rl:api:{ip}"


# ── OTP Send Rate Limit (replaces in-window check in otp.py) ───────────────────

async def check_otp_send_rate_limit(phone: str) -> Tuple[bool, Optional[int]]:
    """
    Check if OTP send is allowed for this phone number.
    Returns (allowed, retry_after_seconds).
    """
    r = await get_redis()
    if r is None:
        return True, None  # Allow if Redis unavailable
    key = _otp_send_key(phone)
    now = datetime.now(timezone.utc).timestamp()

    # Use a sliding window with sorted set (member=timestamp, score=timestamp)
    # Remove expired entries
    cutoff = now - OTP_SEND_WINDOW_SEC
    await r.zremrangebyscore(key, 0, cutoff)

    # Count current requests in window
    count = await r.zcard(key)

    if count >= OTP_SEND_LIMIT:
        # Get oldest entry to calculate retry-after
        oldest = await r.zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_ts = oldest[0][1]
            retry_after = int(oldest_ts + OTP_SEND_WINDOW_SEC - now) + 1
            return False, max(retry_after, 1)
        return False, OTP_SEND_WINDOW_SEC

    return True, None


async def record_otp_send(phone: str):
    """Record an OTP send attempt."""
    r = await get_redis()
    if r is None:
        return  # No-op if Redis unavailable
    key = _otp_send_key(phone)
    now = datetime.now(timezone.utc).timestamp()

    # Add current timestamp to sorted set
    await r.zadd(key, {str(now): now})
    # Set TTL on the key to auto-expire after window + buffer
    await r.expire(key, OTP_SEND_WINDOW_SEC + 60)


# ── Login Brute-Force Protection (replaces _login_attempts dict) ───────────────

async def check_login_rate_limit(email: str, ip: str) -> Tuple[bool, Optional[int]]:
    """
    Check if login attempt is allowed.
    Returns (allowed, retry_after_seconds).
    """
    r = await get_redis()
    if r is None:
        return True, None  # Allow if Redis unavailable
    key = _login_attempt_key(email, ip)

    # Get current count and lockout info
    pipe = r.pipeline()
    pipe.get(f"{key}:count")
    pipe.get(f"{key}:lockout")
    results = await pipe.execute()

    count = int(results[0]) if results[0] else 0
    lockout_until = float(results[1]) if results[1] else 0
    now_ts = datetime.now(timezone.utc).timestamp()

    # Check if currently locked out
    if lockout_until and now_ts < lockout_until:
        retry_after = int(lockout_until - now_ts)
        return False, max(retry_after, 1)

    # Check if within window and over limit
    if count >= LOGIN_ATTEMPT_LIMIT:
        # Lock out
        lockout_until = now_ts + LOGIN_LOCKOUT_SEC
        await r.set(f"{key}:lockout", str(lockout_until), ex=LOGIN_LOCKOUT_SEC + 60)
        retry_after = int(lockout_until - now_ts)
        return False, max(retry_after, 1)

    return True, None


async def record_failed_login(email: str, ip: str):
    """Record a failed login attempt."""
    r = await get_redis()
    if r is None:
        return  # No-op if Redis unavailable
    key = _login_attempt_key(email, ip)
    now_ts = datetime.now(timezone.utc).timestamp()

    # Use a Lua script for atomic increment with window reset
    lua_script = """
    local count_key = KEYS[1] .. ':count'
    local first_key = KEYS[1] .. ':first'
    local window = tonumber(ARGV[1])
    local limit = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local lockout = tonumber(ARGV[4])

    local first = redis.call('GET', first_key)
    if first then
        first = tonumber(first)
        if now - first > window then
            -- Window expired, reset
            redis.call('SET', count_key, '1', 'EX', window + 60)
            redis.call('SET', first_key, tostring(now), 'EX', window + 60)
            return {1, 0}
        end
    else
        -- First attempt in window
        redis.call('SET', count_key, '1', 'EX', window + 60)
        redis.call('SET', first_key, tostring(now), 'EX', window + 60)
        return {1, 0}
    end

    -- Increment count
    local new_count = redis.call('INCR', count_key)
    if new_count >= limit then
        local lockout_until = now + lockout
        redis.call('SET', KEYS[1] .. ':lockout', tostring(lockout_until), 'EX', lockout + 60)
    end
    return {new_count, 0}
    """
    await r.eval(lua_script, 1, key, LOGIN_WINDOW_SEC, LOGIN_ATTEMPT_LIMIT, now_ts, LOGIN_LOCKOUT_SEC)


async def clear_login_attempts(email: str, ip: str):
    """Clear login attempts on successful login."""
    r = await get_redis()
    if r is None:
        return  # No-op if Redis unavailable
    key = _login_attempt_key(email, ip)
    await r.delete(key, f"{key}:count", f"{key}:first", f"{key}:lockout")


# ── General API Rate Limit (replaces slowapi in-memory) ────────────────────────

async def check_api_rate_limit(request: Request) -> Tuple[bool, Optional[int]]:
    """
    Check if API request is allowed (general rate limit per IP).
    Returns (allowed, retry_after_seconds).
    """
    # Extract client IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"

    r = await get_redis()
    if r is None:
        return True, None  # Allow if Redis unavailable
    key = _api_key(ip)
    now_ts = datetime.now(timezone.utc).timestamp()

    # Sliding window using sorted set
    cutoff = now_ts - API_WINDOW_SEC
    await r.zremrangebyscore(key, 0, cutoff)

    count = await r.zcard(key)

    if count >= API_LIMIT:
        oldest = await r.zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_ts = oldest[0][1]
            retry_after = int(oldest_ts + API_WINDOW_SEC - now_ts) + 1
            return False, max(retry_after, 1)
        return False, API_WINDOW_SEC

    return True, None


async def record_api_request(request: Request):
    """Record an API request for rate limiting."""
    r = await get_redis()
    if r is None:
        return  # No-op if Redis unavailable
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"

    key = _api_key(ip)
    now_ts = datetime.now(timezone.utc).timestamp()

    await r.zadd(key, {str(now_ts): now_ts})
    await r.expire(key, API_WINDOW_SEC + 60)


# ── FastAPI Dependencies ──────────────────────────────────────────────────────

async def api_rate_limit_dependency(request: Request):
    """FastAPI dependency for general API rate limiting."""
    allowed, retry_after = await check_api_rate_limit(request)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    await record_api_request(request)


# ── Optional: SlowAPI-compatible interface for gradual migration ───────────────

class RedisRateLimiter:
    """Drop-in replacement interface for slowapi's Limiter (partial)."""

    def __init__(self, key_func=None, default_limits=None):
        self.key_func = key_func or self._default_key
        self.default_limits = default_limits or []

    def _default_key(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def is_rate_limited(self, request: Request, limit: int = API_LIMIT, window: int = API_WINDOW_SEC) -> bool:
        """Check if request should be rate limited."""
        allowed, _ = await check_api_rate_limit(request)
        return not allowed


# Export for backward compatibility if needed
__all__ = [
    "get_redis",
    "close_redis",
    "check_otp_send_rate_limit",
    "record_otp_send",
    "check_login_rate_limit",
    "record_failed_login",
    "clear_login_attempts",
    "check_api_rate_limit",
    "record_api_request",
    "api_rate_limit_dependency",
    "RedisRateLimiter",
]