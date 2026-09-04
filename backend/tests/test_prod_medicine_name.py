"""
Live-production tests for the medicine-name substitution fix (iteration 12).

Target: https://api.ayanabott.com (override with PROD_API_BASE_URL).

Scenario built on ONE fresh account:
  * parent A: language=te, medicine_list=[{name: Amlokind, reminder_time: 09:00}]
  * parent B: language=hi, medicine_list=[]  (empty -> native placeholder)
  * parent C: language=te, medicine_list=[]  (empty -> native placeholder)

Asserts POST /api/messages/preview text and POST /api/messages/send-test
status for category=medicine, plus non-medicine regression.

Run: pytest /app/backend/tests/test_prod_medicine_name.py -v -p no:cacheprovider
"""

import os
import sys
import time

import pytest
import requests

BASE_URL = (os.environ.get("PROD_API_BASE_URL") or "https://api.ayanabott.com").rstrip("/")
API = f"{BASE_URL}/api"
PASSWORD = "TestPass!2026"
ENGLISH_LITERAL = "your medicine"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="module")
def release(session):
    r = session.get(f"{API}/health", timeout=30)
    assert r.status_code in (200, 503), f"health {r.status_code}: {r.text[:300]}"
    return r.json().get("release", "")


@pytest.fixture(scope="module")
def account(session):
    ts = int(time.time())
    email = f"qa-medname-{ts}@ayanabott.com"
    phone = f"+9195{str(ts)[-8:]}"
    r = session.post(
        f"{API}/auth/register",
        json={"name": "QA MedName", "email": email, "phone": phone, "password": PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"register failed {r.status_code}: {r.text[:400]}"
    token = r.json().get("token") or r.json().get("access_token")
    csrf = session.cookies.get("csrf_token")
    headers = {"X-CSRF-Token": csrf or ""}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # OTP (dev_code) -> verify -> child profile -> trial plan
    r = session.post(f"{API}/auth/otp/send", headers=headers, json={"phone": phone}, timeout=30)
    assert r.status_code == 200, f"otp/send {r.status_code}: {r.text[:300]}"
    dev_code = r.json().get("dev_code")
    assert dev_code, f"no dev_code: {r.text[:300]}"
    r = session.post(f"{API}/auth/otp/verify", headers=headers,
                     json={"phone": phone, "code": dev_code}, timeout=30)
    assert r.status_code == 200, f"otp/verify {r.status_code}: {r.text[:300]}"
    r = session.put(f"{API}/profile/child", headers=headers,
                    json={"name": "QA Child", "phone": phone, "city": "Hyderabad",
                          "timezone": "Asia/Kolkata"}, timeout=30)
    assert r.status_code == 200, f"profile/child {r.status_code}: {r.text[:300]}"
    r = session.post(f"{API}/payment/checkout", headers=headers,
                     json={"plan": "nitya", "billing": "month",
                           "origin_url": "https://www.ayanabott.com"}, timeout=30)
    assert r.status_code == 200, f"payment/checkout {r.status_code}: {r.text[:300]}"
    return {"email": email, "phone": phone, "headers": headers, "ts": ts}


def _add_parent(session, account, suffix, language, meds):
    payload = {
        "name": "Amma",
        "relationship": "mother",
        "phone": f"+9198{str(account['ts'])[-6:]}{suffix}",
        "language": language,
        "timezone": "Asia/Kolkata",
        "city": "Hyderabad",
        "nicknames": ["Ammmmmaaa"],
        "preferred_name": "Ammmmmaaa",
        "medicine_list": meds,
    }
    r = session.post(f"{API}/parents", headers=account["headers"], json=payload, timeout=30)
    assert r.status_code == 200, f"parents({language}) {r.status_code}: {r.text[:400]}"
    body = r.json()
    pid = body.get("id") or body.get("parent", {}).get("id")
    assert pid, f"no parent id: {r.text[:300]}"
    return str(pid)


@pytest.fixture(scope="module")
def parent_id(session, account):
    """Nitya trial allows only 1 parent, so scenarios mutate this one parent."""
    return _add_parent(session, account, "01", "te",
                       [{"name": "Amlokind", "reminder_time": "09:00"}])


def _set_parent(session, account, pid, language, meds):
    """Switch the single parent's language / medicine_list for a scenario."""
    # PUT /parents/{id} validates against ParentInput, which requires
    # name/relationship/phone even for a partial update -> send them all.
    r = session.put(f"{API}/parents/{pid}", headers=account["headers"],
                    json={"name": "Amma", "relationship": "mother",
                          "phone": f"+9198{str(account['ts'])[-6:]}01",
                          "timezone": "Asia/Kolkata", "city": "Hyderabad",
                          "nicknames": ["Ammmmmaaa"], "preferred_name": "Ammmmmaaa",
                          "language": language, "medicine_list": meds}, timeout=30)
    assert r.status_code == 200, f"PUT /parents ({language}) {r.status_code}: {r.text[:400]}"
    out = r.json()
    assert out.get("language") == language, f"language not updated: {out.get('language')}"
    got = out.get("medicine_list") or []
    if isinstance(got, str):
        import json as _j
        got = _j.loads(got)
    assert len(got) == len(meds), f"medicine_list not persisted: {got!r}"
    return out


def _todays_variant_has_medicine_slot(language):
    """/api/messages/preview rotates variants by UTC day-of-year, and only
    some medicine variants contain the {medicine} placeholder. Resolve
    today's variant locally so the assertion is not calendar-flaky."""
    import datetime
    sys.path.insert(0, "/app/backend")
    os.environ.setdefault("DATABASE_URL", "postgresql://qa:qa@127.0.0.1:5432/qa")
    from templates_data import SLOT_VARIANTS, trim_variants_for_plan
    from pricing import plan_limits
    variants = trim_variants_for_plan(
        SLOT_VARIANTS["medicine"][language], plan_limits("nitya")["variants_per_slot"])
    day = datetime.datetime.now(datetime.timezone.utc).timetuple().tm_yday
    return "{medicine}" in variants[day % len(variants)]


def _preview(session, account, pid, category="medicine"):
    r = session.post(f"{API}/messages/preview", headers=account["headers"],
                     json={"parent_id": pid, "category": category}, timeout=30)
    return r


def _send_test(session, account, pid, category="medicine"):
    r = session.post(f"{API}/messages/send-test", headers=account["headers"],
                     json={"parent_id": pid, "category": category}, timeout=90)
    return r


# ---------------- persistence sanity ----------------
def test_medicine_list_persisted(session, account, parent_id):
    r = session.get(f"{API}/parents", headers=account["headers"], timeout=30)
    assert r.status_code == 200, r.text[:300]
    items = r.json() if isinstance(r.json(), list) else r.json().get("parents", [])
    p = {str(x.get("id")): x for x in items}.get(parent_id)
    assert p, "parent not persisted"
    meds = p.get("medicine_list") or []
    assert isinstance(meds, list) and meds and meds[0].get("name") == "Amlokind", \
        f"medicine_list not persisted correctly: {meds!r}"


# ---------------- PRIMARY: /messages/preview ----------------
def test_preview_te_with_medicine_uses_real_name(session, account, parent_id, release):
    _set_parent(session, account, parent_id, "te", [{"name": "Amlokind", "reminder_time": "09:00"}])
    r = _preview(session, account, parent_id)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    text = r.json().get("text", "")
    print(f"[release={release}] preview te+med -> {text!r}")
    assert ENGLISH_LITERAL not in text, f"English literal in Telugu preview: {text!r}"
    if _todays_variant_has_medicine_slot("te"):
        assert "Amlokind" in text, f"real medicine name missing: {text!r}"
    else:
        print("today's te variant has no {medicine} slot - name check n/a")


def test_preview_te_empty_uses_telugu_placeholder(session, account, parent_id, release):
    _set_parent(session, account, parent_id, "te", [])
    r = _preview(session, account, parent_id)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    text = r.json().get("text", "")
    print(f"[release={release}] preview te+empty -> {text!r}")
    assert ENGLISH_LITERAL not in text, f"English literal in Telugu preview: {text!r}"
    assert "\u0c2e\u0c02\u0c26\u0c41" in text, f"Telugu placeholder missing: {text!r}"


def test_preview_hi_empty_uses_hindi_placeholder(session, account, parent_id, release):
    _set_parent(session, account, parent_id, "hi", [])
    r = _preview(session, account, parent_id)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    text = r.json().get("text", "")
    print(f"[release={release}] preview hi+empty -> {text!r}")
    assert ENGLISH_LITERAL not in text, f"English literal in Hindi preview: {text!r}"
    assert "\u0926\u0935\u093e\u0908" in text, f"Hindi placeholder missing: {text!r}"


def test_preview_hi_with_medicine_uses_real_name(session, account, parent_id, release):
    _set_parent(session, account, parent_id, "hi", [{"name": "Metformin", "reminder_time": "21:00"}])
    r = _preview(session, account, parent_id)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    text = r.json().get("text", "")
    print(f"[release={release}] preview hi+med -> {text!r}")
    assert ENGLISH_LITERAL not in text, f"English literal in Hindi preview: {text!r}"
    if _todays_variant_has_medicine_slot("hi"):
        assert "Metformin" in text, f"real medicine name missing: {text!r}"
    else:
        print("today's hi variant has no {medicine} slot - name check n/a")


# ---------------- PRIMARY/REGRESSION: /messages/send-test ----------------
@pytest.mark.parametrize("language,meds", [
    ("te", [{"name": "Amlokind", "reminder_time": "09:00"}]),
    ("te", []),
    ("hi", []),
])
def test_send_test_medicine_no_crash(session, account, parent_id, language, meds):
    _set_parent(session, account, parent_id, language, meds)
    r = _send_test(session, account, parent_id, "medicine")
    print(f"send-test medicine [{language}, meds={len(meds)}] -> {r.status_code} {r.text[:300]}")
    assert r.status_code == 200, f"send-test failed {r.status_code}: {r.text[:400]}"
    body = r.json()
    assert body.get("status") in ("sent", "simulated", "failed"), f"unexpected body: {body}"


@pytest.mark.parametrize("category", ["how_feeling", "morning_wish"])
def test_send_test_non_medicine_categories(session, account, parent_id, category):
    r = _send_test(session, account, parent_id, category)
    print(f"send-test {category} -> {r.status_code} {r.text[:300]}")
    assert r.status_code == 200, f"send-test {category} failed {r.status_code}: {r.text[:400]}"


# ---------------- REGRESSION: onboarding up to /schedules ----------------
def test_schedule_save_regression(session, account, parent_id):
    r = session.post(f"{API}/schedules", headers=account["headers"],
                     json={"parent_id": parent_id, "mode": "nitya", "active": True,
                           "messages": [{"time": "09:00", "category": "medicine"},
                                        {"time": "08:00", "category": "morning_wish"}]},
                     timeout=30)
    assert r.status_code == 200, f"schedules {r.status_code}: {r.text[:400]}"
