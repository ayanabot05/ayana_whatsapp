"""Graceful Redis read-through cache with per-user versioned invalidation.

Design goals:
- NEVER break a request. If REDIS_URL is unset or Redis is unreachable, every
  helper degrades to a direct loader() call (i.e. behaves like no cache).
- ONE-SYNC: every cached read is namespaced by a per-user version counter.
  Any write (a new reply, a care-plan save, a contact/sibling change, ...) calls
  bump_version(user_id), which atomically invalidates ALL of that user's cached
  reads at once, so dashboard / check-ins / replies / parent / child views can
  never show stale, out-of-sync data after a change.
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

_client = None
_unavailable = False


def _redis():
    global _client, _unavailable
    if _unavailable:
        return None
    if _client is None:
        url = os.environ.get("REDIS_URL")
        if not url:
            _unavailable = True
            return None
        try:
            import redis.asyncio as aioredis

            _client = aioredis.from_url(
                url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
                retry_on_timeout=False,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Redis unavailable, caching disabled: %s", exc)
            _unavailable = True
            return None
    return _client


async def get_version(user_id) -> str:
    """Current cache-namespace version for a user (defaults to '0')."""
    r = _redis()
    if not r:
        return "0"
    try:
        v = await r.get(f"ver:{user_id}")
        return v if v is not None else "0"
    except Exception as exc:
        logger.debug("cache get_version failed: %s", exc)
        return "0"


async def bump_version(user_id) -> None:
    """Invalidate every cached read for this user in one atomic step."""
    if not user_id:
        return
    r = _redis()
    if not r:
        return
    try:
        await r.incr(f"ver:{user_id}")
    except Exception as exc:
        logger.debug("cache bump_version failed: %s", exc)


async def cached_json(key: str, ttl: int, loader):
    """Return cached JSON for key, or call async loader() and cache its result.

    Any Redis error transparently falls back to loader() so the request still
    succeeds. loader() must return a JSON-serialisable value.
    """
    r = _redis()
    if not r:
        return await loader()
    try:
        hit = await r.get(key)
        if hit is not None:
            return json.loads(hit)
    except Exception as exc:
        logger.debug("cache read miss/error for %s: %s", key, exc)
        return await loader()
    data = await loader()
    try:
        await r.set(key, json.dumps(data, default=str), ex=ttl)
    except Exception as exc:
        logger.debug("cache write failed for %s: %s", key, exc)
    return data
