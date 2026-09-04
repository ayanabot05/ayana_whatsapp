"""
Object storage wrapper for AYANA moment-image uploads.

Feature-flagged: init only runs when OBJECT_STORAGE_ENABLED=true AND
EMERGENT_LLM_KEY is set. In every other case (e.g. production on Railway
where Emergent's preview-only object store isn't reachable) the module
is a graceful no-op — is_enabled() returns False and the /moments upload
endpoint returns a clean 501 instead of crashing with a 500 or spamming
Sentry.

Note: the flag is evaluated at import time, so changing
OBJECT_STORAGE_ENABLED on Railway requires a redeploy (or a Railway
"Restart" click on the service) to take effect.

Post-launch, swap this for Cloudinary / Supabase Storage / S3 by
implementing the same three functions (is_enabled, put_object,
get_object).
"""

import logging
import os

import requests

logger = logging.getLogger("ayana.storage")

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY", "").strip()
APP_NAME = "ayana"

# Explicit opt-in: production must set OBJECT_STORAGE_ENABLED=true AND
# provide EMERGENT_LLM_KEY to reach the Emergent object store. Anything
# else -> module is a no-op (no init call, no Sentry error).
_ENABLED = (
    os.environ.get("OBJECT_STORAGE_ENABLED", "false").strip().lower() == "true"
    and bool(EMERGENT_KEY)
)

_storage_key = None


def is_enabled() -> bool:
    return _ENABLED


def init_storage(force: bool = False):
    """Call once at startup. No-op (returns None) when the module is disabled."""
    global _storage_key
    if not _ENABLED:
        logger.info("Object storage disabled (set OBJECT_STORAGE_ENABLED=true + EMERGENT_LLM_KEY to enable)")
        return None
    if _storage_key and not force:
        return _storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload bytes. Raises RuntimeError if storage is disabled — the
    caller is expected to gate on is_enabled() first and return a 501."""
    if not _ENABLED:
        raise RuntimeError("object storage disabled")
    key = init_storage()
    try:
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data,
            timeout=120,
        )
        if resp.status_code == 404:
            key = init_storage(force=True)
            resp = requests.put(
                f"{STORAGE_URL}/objects/{path}",
                headers={"X-Storage-Key": key, "Content-Type": content_type},
                data=data,
                timeout=120,
            )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("[storage] put failed for %s: %s", path, e)
        raise


def get_object(path: str) -> tuple[bytes, str]:
    """Download bytes. Raises RuntimeError if storage is disabled."""
    if not _ENABLED:
        raise RuntimeError("object storage disabled")
    key = init_storage()
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key},
        timeout=60,
    )
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.get(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")
