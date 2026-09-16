"""Iteration 19 regression: auth/email-phone/replies/webhook critical paths.

These tests hit the public preview API URL from frontend/.env to validate
real route behavior through ingress.
"""

import json
import os
import time
import uuid

import pytest
import requests


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL is required", allow_module_level=True)
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"
WEBHOOK_DEV_TOKEN = os.environ.get("WEBHOOK_DEV_TOKEN")
if not WEBHOOK_DEV_TOKEN:
    env_path = "/app/backend/.env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("WEBHOOK_DEV_TOKEN="):
                    WEBHOOK_DEV_TOKEN = line.strip().split("=", 1)[1]
                    break


def _session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _register_and_login(email=None, password="TestUserCare42!", phone=None):
    s = _session()
    uid = uuid.uuid4().hex[:8]
    payload = {
        "name": f"TEST_User_{uid}",
        "email": email or f"test_{uid}@example.com",
        "phone": phone or f"+1415{int(time.time() * 1000) % 10000000:07d}",
        "password": password,
    }
    reg = s.post(f"{API}/auth/register", json=payload, timeout=30)
    assert reg.status_code == 200, f"register failed: {reg.status_code} {reg.text}"

    login = s.post(
        f"{API}/auth/login",
        json={"email": payload["email"], "password": password},
        timeout=30,
    )
    assert login.status_code == 200, f"login failed: {login.status_code} {login.text}"
    csrf = s.cookies.get("csrf_token")
    assert csrf and len(csrf) >= 8
    return s, payload, csrf


def _create_parent(s, csrf, suffix="A"):
    parent_payload = {
        "name": f"TEST_Parent_{suffix}",
        "relationship": "mother",
        "phone": f"+1202555{int(time.time() * 1000) % 10000:04d}",
        "language": "en",
        "timezone": "Asia/Kolkata",
    }
    r = s.post(
        f"{API}/parents",
        json=parent_payload,
        headers={"X-CSRF-Token": csrf},
        timeout=30,
    )
    assert r.status_code == 200, f"create parent failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["name"] == parent_payload["name"]
    assert data["phone"] == parent_payload["phone"]
    assert isinstance(data.get("id"), str)
    return data


# Auth/health baseline
def test_health_reports_expected_modes():
    r = requests.get(f"{API}/health", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["otp_mode"] == "email"
    assert data["meta"] in ("disabled", "configured")


def test_mobile_otp_endpoints_return_410():
    s, payload, csrf = _register_and_login()
    send = s.post(
        f"{API}/auth/otp/send",
        json={"phone": payload["phone"]},
        headers={"X-CSRF-Token": csrf},
        timeout=30,
    )
    verify = s.post(
        f"{API}/auth/otp/verify",
        json={"phone": payload["phone"], "code": "123456"},
        headers={"X-CSRF-Token": csrf},
        timeout=30,
    )
    assert send.status_code == 410
    assert verify.status_code == 410
    assert "retired" in send.text.lower()
    assert "retired" in verify.text.lower()


def test_forgot_password_unknown_email_generic_response_contract():
    unknown = f"unknown_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/forgot-password", json={"email": unknown}, timeout=30)
    if r.status_code == 503:
        # Globally disabled delivery must fail truthfully, not pretend a code was
        # sent. Provider-enabled generic responses are exercised in unit tests.
        assert 'not available' in r.text.lower()
        assert 'challenge_id' not in r.json()
        return
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("challenge_id"), str)
    assert "if this email belongs" in data.get("message", "").lower()


def test_phone_change_requires_explicit_checkbox():
    s, payload, csrf = _register_and_login()
    new_phone = "+12025558888"
    r = s.post(
        f"{API}/profile/phone/request",
        json={"phone": new_phone, "confirmed": False},
        headers={"X-CSRF-Token": csrf},
        timeout=30,
    )
    assert r.status_code == 400
    assert "confirm" in r.text.lower()


def test_profile_put_cannot_bypass_phone_change_flow():
    s, payload, csrf = _register_and_login()
    bypass_payload = {
        "name": payload["name"],
        "phone": "+12025559999",
        "city": "Austin",
        "timezone": "Asia/Kolkata",
    }
    r = s.put(
        f"{API}/profile/child",
        json=bypass_payload,
        headers={"X-CSRF-Token": csrf},
        timeout=30,
    )
    assert r.status_code in (403, 409)
    assert 'verify your email' in r.text.lower() or 'confirm this whatsapp-number change' in r.text.lower()
    current = s.get(f'{API}/auth/me', timeout=30)
    assert current.status_code == 200
    assert current.json()['phone'] == payload['phone']


# Replies access and private-data protection
def test_reply_detail_authorization_and_no_private_tokens():
    sa, _, csrfa = _register_and_login()
    parent = _create_parent(sa, csrfa, suffix="A")

    sim = sa.post(
        f"{API}/replies/simulate",
        json={"parent_id": parent["id"], "text": "I am fine"},
        timeout=30,
    )
    assert sim.status_code == 200
    assert sim.json()["ok"] is True

    replies = sa.get(f"{API}/replies", timeout=30)
    assert replies.status_code == 200
    rows = replies.json()
    assert isinstance(rows, list) and len(rows) >= 1
    reply_id = rows[0]["id"]

    detail = sa.get(f"{API}/replies/{reply_id}", timeout=30)
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == reply_id
    assert isinstance(body.get("notifications"), list)
    serialized = json.dumps(body).lower()
    assert "meta_wa_access_token" not in serialized
    assert "authorization" not in serialized

    sb, _, _ = _register_and_login()
    forbidden = sb.get(f"{API}/replies/{reply_id}", timeout=30)
    assert forbidden.status_code == 404


# Webhook durability + auth boundary
def test_webhook_rejects_missing_dev_secret_when_whatsapp_disabled():
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"id": f"wamid.{uuid.uuid4().hex[:8]}", "from": "12025550101", "type": "text", "text": {"body": "hello"}}]}}]}]
    }
    r = requests.post(f"{API}/whatsapp/webhook", json=payload, timeout=30)
    assert r.status_code == 403
    assert "token" in r.text.lower() or "signature" in r.text.lower()


@pytest.mark.skipif(not WEBHOOK_DEV_TOKEN, reason="WEBHOOK_DEV_TOKEN not configured")
def test_webhook_duplicate_wamid_does_not_duplicate_replies():
    s, _, csrf = _register_and_login()
    parent = _create_parent(s, csrf, suffix="W")
    wam_id = f"wamid.iter19.{uuid.uuid4().hex[:8]}"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "messages": [{
                        "id": wam_id,
                        "from": parent["phone"].lstrip("+"),
                        "type": "text",
                        "text": {"body": "duplicate check"},
                        "timestamp": str(int(time.time())),
                    }]
                },
            }]
        }],
    }
    headers = {"X-Dev-Token": WEBHOOK_DEV_TOKEN, "Content-Type": "application/json"}

    r1 = requests.post(f"{API}/whatsapp/webhook", json=payload, headers=headers, timeout=30)
    r2 = requests.post(f"{API}/whatsapp/webhook", json=payload, headers=headers, timeout=30)
    assert r1.status_code == 200
    assert r2.status_code == 200

    count = 0
    for _ in range(8):
        rr = s.get(f"{API}/replies", timeout=30)
        assert rr.status_code == 200
        rows = rr.json()
        count = len([x for x in rows if (x.get("body") or "") == "duplicate check"])
        if count >= 1:
            break
        time.sleep(1)
    assert count == 1


def test_sibling_send_otp_requires_email_and_challenge_fields():
    s, _, csrf = _register_and_login()
    r = s.post(
        f"{API}/circle/sibling/send-otp",
        json={"name": "Sis", "phone": "+12025557777", "language": "en", "relation": "sibling"},
        headers={"X-CSRF-Token": csrf},
        timeout=30,
    )
    assert r.status_code in (422, 403)
    if r.status_code == 422:
        assert "email" in r.text.lower()
