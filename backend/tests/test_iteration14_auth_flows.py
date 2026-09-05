"""Iteration 14: forgot/reset password, change password, change email, webhook button-tap.

Runs against the public preview backend so cookies + CSRF flow through Kubernetes ingress
the same way the browser sees them.
"""
import os
import hmac
import json
import time
import uuid
import hashlib
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://e6ee39c5-98f8-45ea-aa21-f1d342c47485.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

TEST_USER_EMAIL = "ravi.e1test2@ayanabott.com"
TEST_USER_PASSWORD = "Test@12345"
TEST_USER_PHONE = "+919876500011"

META_APP_SECRET = "109501be530c92d3b64c6e15013325b8"


# ---------- helpers ----------

def _sess():
    s = requests.Session()
    return s


def login(session, email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD):
    r = session.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r


def csrf(session):
    return session.cookies.get("csrf_token") or ""


def sign_meta(body_bytes: bytes) -> str:
    mac = hmac.new(META_APP_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


# ---------- health / regression ----------

def test_health_200():
    r = requests.get(f"{API}/health", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") in ("ok", "healthy", "up") or "status" in body


# ---------- forgot password ----------

def test_forgot_password_unknown_phone_still_200_without_dev_code():
    r = requests.post(f"{API}/auth/forgot-password", json={"phone": "+919000000001"}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("sent") is True
    assert "dev_code" not in body, "must not leak dev_code for unknown phones (enumeration)"


def test_forgot_password_short_phone_422():
    r = requests.post(f"{API}/auth/forgot-password", json={"phone": "+9198765"}, timeout=30)
    assert r.status_code == 422
    assert "10 digits" in r.text


@pytest.fixture(scope="module")
def dev_code_for_test_user():
    # respect 60s cooldown from prior runs
    for attempt in range(4):
        r = requests.post(f"{API}/auth/forgot-password", json={"phone": TEST_USER_PHONE}, timeout=30)
        if r.status_code == 200 and r.json().get("dev_code"):
            return r.json()["dev_code"]
        if r.status_code == 429:
            time.sleep(65)
            continue
        # Might be rate-limited via out-of-band call earlier
        time.sleep(65)
    pytest.skip(f"Could not obtain dev_code (last: {r.status_code} {r.text[:200]})")


def test_forgot_password_known_phone_returns_dev_code(dev_code_for_test_user):
    assert len(dev_code_for_test_user) == 6 and dev_code_for_test_user.isdigit()


def test_reset_password_wrong_code_400():
    r = requests.post(f"{API}/auth/reset-password", json={
        "phone": TEST_USER_PHONE,
        "code": "000000",
        "new_password": "Test@12345",
    }, timeout=30)
    assert r.status_code == 400, r.text


def test_reset_password_correct_code_invalidates_old_session_and_reissues(dev_code_for_test_user):
    # 1. Login → have a valid cookie session
    old = _sess()
    login(old)
    me1 = old.get(f"{API}/auth/me", timeout=30)
    assert me1.status_code == 200

    # 2. Reset password (same value, so account stays usable)
    r = requests.post(f"{API}/auth/reset-password", json={
        "phone": TEST_USER_PHONE,
        "code": dev_code_for_test_user,
        "new_password": TEST_USER_PASSWORD,
    }, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True

    # 3. Old session must now be invalid (password_changed_at moved forward)
    me2 = old.get(f"{API}/auth/me", timeout=30)
    assert me2.status_code == 401, f"old session should be revoked, got {me2.status_code}"

    # 4. Fresh login works again
    fresh = _sess()
    login(fresh)
    me3 = fresh.get(f"{API}/auth/me", timeout=30)
    assert me3.status_code == 200


# ---------- signup validation ----------

def test_register_short_phone_422_mentions_10_digits():
    r = requests.post(f"{API}/auth/register", json={
        "name": "TEST short",
        "email": f"e1test-{uuid.uuid4().hex[:6]}@ayanabott.com",
        "phone": "+91987654321",  # 9 digits
        "password": "Abcdefg1",
    }, timeout=30)
    assert r.status_code == 422, r.text
    assert "10 digits" in r.text


def test_register_weak_password_422_mentions_uppercase():
    r = requests.post(f"{API}/auth/register", json={
        "name": "TEST weak",
        "email": f"e1test-{uuid.uuid4().hex[:6]}@ayanabott.com",
        "phone": "+919876500123",
        "password": "abcdefgh",
    }, timeout=30)
    assert r.status_code == 422, r.text
    assert "uppercase" in r.text.lower()


# ---------- change password ----------

def test_change_password_same_current_and_new_400():
    s = _sess()
    login(s)
    r = s.post(
        f"{API}/auth/change-password",
        json={"current_password": TEST_USER_PASSWORD, "new_password": TEST_USER_PASSWORD},
        headers={"X-CSRF-Token": csrf(s)},
        timeout=30,
    )
    assert r.status_code == 400, r.text
    assert "different" in r.text.lower()


def test_change_password_wrong_current_400():
    s = _sess()
    login(s)
    r = s.post(
        f"{API}/auth/change-password",
        json={"current_password": "WrongPass1", "new_password": "SomeNewPass1"},
        headers={"X-CSRF-Token": csrf(s)},
        timeout=30,
    )
    assert r.status_code == 400
    assert "incorrect" in r.text.lower()


def test_change_password_round_trip_reissues_cookies():
    s = _sess()
    login(s)
    # change to new
    r = s.post(
        f"{API}/auth/change-password",
        json={"current_password": TEST_USER_PASSWORD, "new_password": "Test@12345x"},
        headers={"X-CSRF-Token": csrf(s)},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    # cookies re-issued: /auth/me should still work on this session
    me = s.get(f"{API}/auth/me", timeout=30)
    assert me.status_code == 200
    # change back
    r2 = s.post(
        f"{API}/auth/change-password",
        json={"current_password": "Test@12345x", "new_password": TEST_USER_PASSWORD},
        headers={"X-CSRF-Token": csrf(s)},
        timeout=30,
    )
    assert r2.status_code == 200, r2.text


# ---------- change email ----------

def test_change_email_wrong_password_400():
    s = _sess()
    login(s)
    r = s.post(
        f"{API}/profile/email/request",
        json={"new_email": "ravi.e1test-nope@ayanabott.com", "password": "WrongPass1"},
        headers={"X-CSRF-Token": csrf(s)},
        timeout=30,
    )
    assert r.status_code == 400
    assert "password is incorrect" in r.text.lower()


def test_change_email_already_taken_400():
    s = _sess()
    login(s)
    # ravi.e1test@ayanabott.com is a throwaway that already exists (per test_credentials.md)
    # If it doesn't exist yet, this will 200; skip in that case.
    r = s.post(
        f"{API}/profile/email/request",
        json={"new_email": "ravi.e1test@ayanabott.com", "password": TEST_USER_PASSWORD},
        headers={"X-CSRF-Token": csrf(s)},
        timeout=30,
    )
    if r.status_code == 429:
        pytest.skip("OTP cooldown; skip 'already used' assertion this round")
    assert r.status_code == 400, f"expected 400 already used, got {r.status_code} {r.text}"
    assert "already used" in r.text.lower() or "already" in r.text.lower()


# ---------- webhook ----------

def _post_webhook(payload: dict):
    body = json.dumps(payload).encode()
    sig = sign_meta(body)
    return requests.post(
        f"{API}/whatsapp/webhook",
        data=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        timeout=30,
    )


def test_webhook_signed_inbound_text_200():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "wa-entry",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "0", "phone_number_id": "1359255640597884"},
                    "messages": [{
                        "from": "919876500012",
                        "id": f"wamid.text.{uuid.uuid4().hex[:8]}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": "I am good"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    r = _post_webhook(payload)
    assert r.status_code == 200, r.text


def test_webhook_button_reply_with_timezone_does_not_crash():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "wa-entry",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "0", "phone_number_id": "1359255640597884"},
                    "messages": [{
                        "from": "919876500012",
                        "id": f"wamid.btn.{uuid.uuid4().hex[:8]}",
                        "timestamp": str(int(time.time())),
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": "done:medicine", "title": "Done"},
                        },
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    r = _post_webhook(payload)
    assert r.status_code == 200, r.text


# ---------- dashboard regression ----------

def test_dashboard_bootstrap_regression():
    s = _sess()
    login(s)
    r = s.get(f"{API}/dashboard/bootstrap", timeout=45)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ["parents", "checkins", "moments", "schedules"]:
        assert key in body, f"missing key {key} in bootstrap"
