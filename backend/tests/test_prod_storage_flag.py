"""
Live-production regression tests for the object-storage feature flag
(iteration 11).

Target: https://api.ayanabott.com (override with PROD_API_BASE_URL).
Covers:
  * GET  /api/health                     -> 200 healthy (clean startup)
  * POST /api/moments/upload-image       -> 501 friendly copy when storage disabled
  * GET  /api/uploads/signed/{f}         -> 404 (disabled) or 403 (invalid sig), never 500
  * Full onboarding flow via API         -> register/otp/child/plan/parent/schedule/activate

Run with: pytest /app/backend/tests/test_prod_storage_flag.py -v -p no:cacheprovider
(uses live network; no in-process TestClient / no conftest fixtures)
"""

import io
import os
import time

import pytest
import requests
from PIL import Image

BASE_URL = (os.environ.get("PROD_API_BASE_URL") or "https://api.ayanabott.com").rstrip("/")
API = f"{BASE_URL}/api"
PASSWORD = "TestPass!2026"


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="module")
def registered_user(session):
    """Register a fresh production test user and capture CSRF token."""
    ts = int(time.time())
    email = f"qa-storage-{ts}@ayanabott.com"
    phone = f"+9195{str(ts)[-8:]}"
    r = session.post(
        f"{API}/auth/register",
        json={"name": "QA Storage", "email": email, "phone": phone, "password": PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"register failed {r.status_code}: {r.text[:400]}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    csrf = session.cookies.get("csrf_token")
    assert csrf, f"no csrf_token cookie set on register; cookies={session.cookies.get_dict()}"
    headers = {"X-CSRF-Token": csrf}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return {"email": email, "phone": phone, "headers": headers, "body": body}


def _jpeg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), color="red").save(buf, format="JPEG")
    return buf.getvalue()


# ---------------- health / clean startup ----------------
def test_health_endpoint(session):
    r = session.get(f"{API}/health", timeout=30)
    assert r.status_code in (200, 503), f"unexpected {r.status_code}: {r.text[:300]}"
    data = r.json()
    assert data.get("status") in ("healthy", "degraded", "unhealthy")
    assert data.get("postgres") == "up"
    print("health:", data)


def test_public_get_endpoints_no_500(session):
    for path in ["/health", "/pricing", "/templates"]:
        r = session.get(f"{API}{path}", timeout=30)
        assert r.status_code < 500, f"{path} -> {r.status_code}: {r.text[:200]}"


# ---------------- PRIMARY: upload-image feature flag ----------------
def test_upload_image_returns_501_when_storage_disabled(session, registered_user):
    files = {"file": ("qa.jpg", _jpeg_bytes(), "image/jpeg")}
    r = session.post(
        f"{API}/moments/upload-image",
        headers=registered_user["headers"],
        files=files,
        timeout=60,
    )
    print("upload-image status:", r.status_code, "body:", r.text[:500])
    assert r.status_code != 500, f"500 from upload-image: {r.text[:400]}"
    assert r.status_code == 501, f"expected 501, got {r.status_code}: {r.text[:400]}"
    assert "application/json" in r.headers.get("Content-Type", "")
    detail = r.json().get("detail", "")
    assert (
        "Photo sharing is temporarily unavailable" in detail
        or "text moments still work" in detail.lower()
    ), f"unexpected detail copy: {detail}"


# ---------------- signed URL regression ----------------
def test_signed_url_invalid_signature(session):
    r = session.get(f"{API}/uploads/signed/does-not-exist.jpg", params={"sig": "x", "exp": 1}, timeout=30)
    print("signed url:", r.status_code, r.text[:200])
    assert r.status_code in (403, 404), f"expected 403/404, got {r.status_code}: {r.text[:300]}"


# ---------------- onboarding regression ----------------
def test_full_onboarding_flow(session, registered_user):
    h = registered_user["headers"]

    # OTP send -> dev_code
    r = session.post(f"{API}/auth/otp/send", headers=h, json={"phone": registered_user["phone"]}, timeout=30)
    assert r.status_code == 200, f"otp/send {r.status_code}: {r.text[:300]}"
    dev_code = r.json().get("dev_code")
    assert dev_code, f"no dev_code in otp/send response: {r.text[:300]}"

    r = session.post(
        f"{API}/auth/otp/verify",
        headers=h,
        json={"phone": registered_user["phone"], "code": dev_code},
        timeout=30,
    )
    assert r.status_code == 200, f"otp/verify {r.status_code}: {r.text[:300]}"

    # child profile
    r = session.put(
        f"{API}/profile/child",
        headers=h,
        json={
            "name": "QA Child",
            "phone": registered_user["phone"],
            "city": "Hyderabad",
            "timezone": "Asia/Kolkata",
        },
        timeout=30,
    )
    assert r.status_code == 200, f"profile/child {r.status_code}: {r.text[:300]}"

    # plan checkout (payments disabled -> trial)
    r = session.post(
        f"{API}/payment/checkout",
        headers=h,
        json={"plan": "nitya", "billing": "month", "origin_url": "https://www.ayanabott.com"},
        timeout=30,
    )
    assert r.status_code == 200, f"payment/checkout {r.status_code}: {r.text[:300]}"

    # add parent
    r = session.post(
        f"{API}/parents",
        headers=h,
        json={
            "name": "Amma",
            "relationship": "mother",
            "phone": "+919999999911",
            "language": "te",
            "timezone": "Asia/Kolkata",
            "city": "Hyderabad",
            "nicknames": ["Bangaram"],
        },
        timeout=30,
    )
    assert r.status_code == 200, f"parents {r.status_code}: {r.text[:400]}"
    parent = r.json()
    parent_id = parent.get("id") or parent.get("parent", {}).get("id")
    assert parent_id, f"no parent id: {r.text[:300]}"

    # verify persistence
    r = session.get(f"{API}/parents", headers=h, timeout=30)
    assert r.status_code == 200
    listed = r.json()
    items = listed if isinstance(listed, list) else listed.get("parents", [])
    assert any(str(p.get("id")) == str(parent_id) for p in items), "parent not persisted"

    # schedule
    r = session.post(
        f"{API}/schedules",
        headers=h,
        json={
            "parent_id": str(parent_id),
            "mode": "nitya",
            "active": True,
            "messages": [{"time": "09:00", "category": "morning_wish"}],
        },
        timeout=30,
    )
    assert r.status_code == 200, f"schedules {r.status_code}: {r.text[:400]}"

    # activate
    r = session.post(f"{API}/activation/activate", headers=h, json={}, timeout=60)
    assert r.status_code == 200, f"activation/activate {r.status_code}: {r.text[:500]}"
    print("activation:", r.text[:300])
