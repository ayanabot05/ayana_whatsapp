"""
Object storage for AYANA moment-image uploads — backed by Supabase Storage.

Enabled when OBJECT_STORAGE_ENABLED=true AND SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
are set. Otherwise every function is a graceful no-op and the upload endpoint
returns a clean 501.

Bucket is private; parents receive a time-limited signed URL (Meta fetches the
image from it when delivering the WhatsApp message).
"""

import logging
import os

import requests

logger = logging.getLogger("ayana.storage")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "moments").strip() or "moments"
APP_NAME = "ayana"

_ENABLED = (
    os.environ.get("OBJECT_STORAGE_ENABLED", "false").strip().lower() == "true"
    and bool(SUPABASE_URL)
    and bool(SERVICE_KEY)
)

_STORAGE_API = f"{SUPABASE_URL}/storage/v1"
_HEADERS = {"Authorization": f"Bearer {SERVICE_KEY}", "apikey": SERVICE_KEY}
_bucket_ready = False


def is_enabled() -> bool:
    return _ENABLED


def init_storage(force: bool = False):
    """Ensure the private bucket exists. No-op when disabled."""
    global _bucket_ready
    if not _ENABLED:
        logger.info("Object storage disabled (set OBJECT_STORAGE_ENABLED=true + SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)")
        return None
    if _bucket_ready and not force:
        return BUCKET
    resp = requests.get(f"{_STORAGE_API}/bucket/{BUCKET}", headers=_HEADERS, timeout=15)
    if resp.status_code == 404 or (resp.status_code == 400 and "not found" in resp.text.lower()):
        create = requests.post(
            f"{_STORAGE_API}/bucket",
            headers={**_HEADERS, "Content-Type": "application/json"},
            json={"id": BUCKET, "name": BUCKET, "public": False, "file_size_limit": 5 * 1024 * 1024},
            timeout=15,
        )
        if create.status_code not in (200, 201) and "already exists" not in create.text.lower():
            create.raise_for_status()
        logger.info("[storage] created Supabase bucket '%s'", BUCKET)
    elif resp.status_code >= 400:
        resp.raise_for_status()
    _bucket_ready = True
    return BUCKET


def put_object(path: str, data: bytes, content_type: str) -> dict:
    if not _ENABLED:
        raise RuntimeError("object storage disabled")
    init_storage()
    resp = requests.post(
        f"{_STORAGE_API}/object/{BUCKET}/{path}",
        headers={**_HEADERS, "Content-Type": content_type, "x-upsert": "true"},
        data=data,
        timeout=60,
    )
    if resp.status_code >= 400:
        logger.error("[storage] put failed for %s: %s %s", path, resp.status_code, resp.text[:200])
        resp.raise_for_status()
    return {"path": path, "size": len(data)}


def get_object(path: str) -> tuple[bytes, str]:
    if not _ENABLED:
        raise RuntimeError("object storage disabled")
    resp = requests.get(f"{_STORAGE_API}/object/{BUCKET}/{path}", headers=_HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


def signed_url(path: str, expires_sec: int = 7 * 24 * 3600) -> str:
    """Time-limited public URL Meta can fetch the image from."""
    if not _ENABLED:
        raise RuntimeError("object storage disabled")
    resp = requests.post(
        f"{_STORAGE_API}/object/sign/{BUCKET}/{path}",
        headers={**_HEADERS, "Content-Type": "application/json"},
        json={"expiresIn": expires_sec},
        timeout=15,
    )
    resp.raise_for_status()
    rel = resp.json()["signedURL"]
    return f"{_STORAGE_API}{rel}" if rel.startswith("/") else rel
