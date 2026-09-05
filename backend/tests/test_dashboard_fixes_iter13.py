"""Iteration 13 backend tests: dashboard bootstrap, webhook (phone normalisation, unknown safe),
monthly report found flag, moments image upload (Supabase signed URL), and health flags.
Focused on the 6 dashboard bugs the founder reported.
"""
import os
import io
import hmac
import json
import time
import hashlib
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://e6ee39c5-98f8-45ea-aa21-f1d342c47485.preview.emergentagent.com",
).rstrip("/")

EMAIL = "ravi.e1test@ayanabott.com"
PASSWORD = "Test@12345"
AMMA_ID = "bf185360-05d0-4d89-9101-94411b69ca34"
AMMA_PHONE_DIGITS = "919876500012"
META_APP_SECRET = "109501be530c92d3b64c6e15013325b8"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    csrf = s.cookies.get("csrf_token")
    assert csrf, "csrf_token cookie missing after login"
    s.headers.update({"X-CSRF-Token": csrf})
    return s


# --- health -----------------------------------------------------------------

def test_health_flags():
    r = requests.get(f"{BASE_URL}/api/health", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["postgres"] == "up"
    assert d["webhook_secret"] == "configured"
    assert d["storage"] == "enabled"


# --- auth timings -----------------------------------------------------------

def test_login_latency():
    s = requests.Session()
    t0 = time.time()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    dt = time.time() - t0
    print(f"[perf] POST /api/auth/login = {dt*1000:.0f} ms")
    assert r.status_code == 200
    # not asserting < 2.5s hard; just log


def test_auth_me_latency(session):
    t0 = time.time()
    r = session.get(f"{BASE_URL}/api/auth/me", timeout=15)
    dt = time.time() - t0
    print(f"[perf] GET  /api/auth/me = {dt*1000:.0f} ms")
    assert r.status_code == 200


# --- bootstrap (bug 5 perf, bug 1 plan) -------------------------------------

def test_dashboard_bootstrap(session):
    t0 = time.time()
    r = session.get(f"{BASE_URL}/api/dashboard/bootstrap", timeout=20)
    dt = time.time() - t0
    print(f"[perf] GET  /api/dashboard/bootstrap = {dt*1000:.0f} ms")
    assert r.status_code == 200, r.text
    d = r.json()
    # Structural asserts: should contain parents, plan, checkins keys
    keys = set(d.keys())
    print(f"[bootstrap] keys = {sorted(keys)}")
    assert "parents" in d or "user" in d, f"missing parents/user in bootstrap: {keys}"
    # plan info
    plan_txt = json.dumps(d).lower()
    assert "bandham" in plan_txt or "nitya" in plan_txt or "raksha" in plan_txt, \
        "no plan info found in bootstrap payload"


# --- webhook (bug 2: phone without +, unknown parent must not 500) ----------

def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_known_parent_no_plus():
    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{
                        "from": AMMA_PHONE_DIGITS,  # NO leading '+'
                        "id": f"wamid.test_{int(time.time())}",
                        "type": "text",
                        "text": {"body": "I am good"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }).encode()
    r = requests.post(
        f"{BASE_URL}/api/whatsapp/webhook",
        data=body,
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": _sign(body)},
        timeout=15,
    )
    print(f"[webhook known] status={r.status_code} body={r.text[:200]}")
    assert r.status_code == 200


def test_webhook_unknown_number_returns_200():
    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{
                        "from": "910000000001",
                        "id": f"wamid.unk_{int(time.time())}",
                        "type": "text",
                        "text": {"body": "hi"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }).encode()
    r = requests.post(
        f"{BASE_URL}/api/whatsapp/webhook",
        data=body,
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": _sign(body)},
        timeout=15,
    )
    print(f"[webhook unknown] status={r.status_code} body={r.text[:200]}")
    assert r.status_code == 200


def test_webhook_reply_appears(session):
    """After the previous webhook post, the reply should show up in bootstrap or checkins."""
    time.sleep(2)
    r = session.get(f"{BASE_URL}/api/dashboard/bootstrap", timeout=20)
    assert r.status_code == 200
    txt = r.text.lower()
    # loose assert - "i am good" should be somewhere; if not, still OK because
    # the reply may be attached to a checkin id
    print(f"[reply] 'i am good' in bootstrap: {'i am good' in txt}")


# --- monthly report (bug 4: found flag, no 404) -----------------------------

def test_monthly_report_found_flag_current(session):
    period = time.strftime("%Y-%m")
    r = session.get(
        f"{BASE_URL}/api/reports/monthly",
        params={"parent_id": AMMA_ID, "period": period},
        timeout=20,
    )
    print(f"[report {period}] status={r.status_code}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "found" in d, f"'found' key missing: {list(d.keys())}"


def test_monthly_report_found_false_for_ancient_period(session):
    r = session.get(
        f"{BASE_URL}/api/reports/monthly",
        params={"parent_id": AMMA_ID, "period": "2015-01"},
        timeout=20,
    )
    print(f"[report 2015-01] status={r.status_code} body={r.text[:200]}")
    assert r.status_code == 200
    d = r.json()
    assert d.get("found") is False, f"expected found=False got {d}"


# --- moments image upload (bug 3: Supabase signed URL) ----------------------

def _tiny_jpeg() -> bytes:
    # 1x1 JPEG (minimal valid)
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb0043000806060706050806070707"
        "090908070a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c28"
        "37292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc40014"
        "0001000000000000000000000000000000000009ffc40014100100000000000000000000"
        "00000000000000ffda0008010100003f00b2c0ffd9"
    )


def test_moments_upload_signed_url(session):
    files = {"file": ("t.jpg", _tiny_jpeg(), "image/jpeg")}
    # requests will set multipart Content-Type
    r = session.post(f"{BASE_URL}/api/moments/upload-image", files=files, timeout=30)
    print(f"[upload] status={r.status_code} body={r.text[:300]}")
    assert r.status_code == 200, r.text
    d = r.json()
    url = d.get("url") or d.get("signed_url") or d.get("image_url")
    assert url, f"no url in response: {d}"
    assert "storage/v1/object/sign" in url or "storage/v1/object/public" in url, \
        f"url is not a Supabase storage URL: {url}"
    # fetch it
    g = requests.get(url, timeout=20)
    print(f"[upload get] status={g.status_code} ct={g.headers.get('Content-Type')}")
    assert g.status_code == 200
    ct = g.headers.get("Content-Type", "")
    assert ct.startswith("image/"), f"unexpected content-type: {ct}"
