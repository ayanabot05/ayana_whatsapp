"""Regression coverage for three specific claimed fixes, run against a real
local Postgres (schema.sql + migrations/001-009), matching the conventions
of test_iteration20_service_suite.py.

    1. Sibling welcomes should go through the durable welcome_deliveries
       queue instead of a best-effort BackgroundTasks send.
    2. Removing a sibling should cancel pending notifications immediately.
    3. A phone-number change should re-point recent undelivered replies at
       the new number without replaying anything already submitted.

Run with a local test DB configured exactly like the other iteration-20/21
style suites (APP_ENV=test, DATABASE_URL ending in _local, WHATSAPP_ENABLED
and SCHEDULER_ENABLED both false):

    python -m pytest backend/tests/test_sibling_and_contact_fixes.py -v

Tests 1, 2 and 4 currently FAIL against the committed code — that is the
point of this file. Test 3 (the number-change fix) should PASS.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import os

import httpx
import pytest
import pytest_asyncio

from auth import hash_password
from database import get_pool
from server import app
from services import verification, welcomes, notifications

OWNER_EMAIL = "sibfix-owner@example.com"
OWNER_PASSWORD = "SibFixOwner42!"
OWNER_PHONE = "+14155561001"
SIBLING_PHONE = "+14155561002"


@pytest_asyncio.fixture()
async def app_ready():
    parsed = urlparse(os.environ.get('SUPABASE_DB_URL') or os.environ.get('DATABASE_URL', ''))
    assert os.environ.get('APP_ENV') == 'test' and parsed.hostname in ('localhost', '127.0.0.1') and parsed.path.endswith('_local'), \
        'Refusing to run against anything but a local test database'
    assert os.environ.get('WHATSAPP_ENABLED') == 'false' and os.environ.get('SCHEDULER_ENABLED') == 'false', \
        'Outbound integrations must remain disabled for this suite'
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture()
async def async_client(app_ready):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture()
async def owner(app_ready):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users(name,email,phone,password_hash,role,onboarding_complete,onboarding_step,
                               city,timezone,deleted_at,email_verified_at,email_verification_required,auth_version)
            VALUES($1,$2,$3,$4,'user',true,5,'Hyderabad','Asia/Kolkata',NULL,now(),false,0)
            ON CONFLICT(email) DO UPDATE
                SET name=EXCLUDED.name, phone=EXCLUDED.phone, password_hash=EXCLUDED.password_hash,
                    deleted_at=NULL, email_verified_at=now(), email_verification_required=false
            RETURNING *
            """,
            "TEST_SibFix Owner", OWNER_EMAIL, OWNER_PHONE, hash_password(OWNER_PASSWORD),
        )
        # Raksha-tier access (family_members > 0) via the "legacy, not billing-managed" path —
        # avoids needing a real billing_orders/access_grants chain just to unlock sibling routes.
        await conn.execute(
            """
            INSERT INTO payment_state(user_id,status,plan,billing,billing_managed,updated_at)
            VALUES($1,'legacy','raksha','month',false,now())
            ON CONFLICT(user_id) DO UPDATE SET status='legacy',plan='raksha',billing_managed=false,updated_at=now()
            """,
            row["id"],
        )
    return dict(row)


@pytest_asyncio.fixture(autouse=True)
async def cleanup(app_ready):
    yield
    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM reply_notifications WHERE detail LIKE 'sibfix-%'")
        await conn.execute("DELETE FROM parent_replies WHERE body LIKE 'sibfix-%'")
        await conn.execute("DELETE FROM welcome_deliveries WHERE phone LIKE '+1415556%'")
        await conn.execute("DELETE FROM care_circle_siblings WHERE phone LIKE '+1415556%'")
        await conn.execute("DELETE FROM parents WHERE name LIKE 'TEST_SibFix%'")
        await conn.execute("DELETE FROM recipient_sessions WHERE phone LIKE '+1415556%'")
        await conn.execute("DELETE FROM verification_challenges WHERE email=$1", OWNER_EMAIL)
        await conn.execute("DELETE FROM payment_state WHERE user_id IN (SELECT id FROM users WHERE email=$1)", OWNER_EMAIL)
        await conn.execute("DELETE FROM users WHERE email=$1", OWNER_EMAIL)


async def _login(client: httpx.AsyncClient) -> dict:
    r = await client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert r.status_code == 200, r.text
    csrf = client.cookies.get("csrf_token")
    return {"Authorization": f"Bearer {r.json()['token']}", "X-CSRF-Token": csrf}


async def _add_sibling(client, headers, monkeypatch, *, phone=SIBLING_PHONE, name="TEST_SibFix Sibling"):
    """Drives the real /circle/sibling/send-otp + /verify flow, capturing the
    emailed OTP the way test_iteration20_service_suite.py does, so this
    exercises the exact code path a real sibling-add would take."""
    captured = {}

    async def fake_send(email, code):
        captured["code"] = code
        return {"status": "sent"}

    monkeypatch.setattr(verification, "send_otp_email", fake_send)

    r = await client.post(
        "/api/circle/sibling/send-otp",
        json={"email": "sibfix-sibling@example.com", "name": name, "phone": phone, "language": "en"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    challenge_id = r.json()["challenge_id"]

    r = await client.post(
        "/api/circle/sibling/verify",
        json={
            "email": "sibfix-sibling@example.com", "name": name, "phone": phone, "language": "en",
            "challenge_id": challenge_id, "code": captured["code"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["sibling"]


async def _create_parent(user_id, name, phone=OWNER_PHONE.replace("1001", "9001")):
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO parents(user_id,name,relationship,phone,language,timezone,city,
                                 activity_window_start,activity_window_end,opted_out_at,created_at,deleted_at)
            VALUES($1,$2,'mother',$3,'en','Asia/Kolkata','Hyderabad','06:00','22:00',NULL,now()-interval '3 days',NULL)
            RETURNING *
            """,
            user_id, name, phone,
        )


async def _create_reply(user_id, parent_id, body, *, minutes_ago=5, from_phone="+919900000111"):
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO parent_replies(parent_id,user_id,text,from_phone,body,is_voice,raw_payload,created_at)
            VALUES($1,$2,$3,$4,$5,false,'{}'::jsonb,now()-make_interval(mins=>$6))
            RETURNING *
            """,
            parent_id, user_id, body, from_phone, body, minutes_ago,
        )


# ---------------------------------------------------------------------------
# Bug found while checking claim 1: welcomes.drain() can't run at all on the
# schema these migrations actually produce, independent of siblings.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_welcomes_drain_runs_without_error(app_ready):
    """welcome_deliveries has no created_at column in schema.sql or any of
    migrations/001-009, but services/welcomes.py:drain() orders by it. This
    should simply not raise. Currently it raises UndefinedColumnError on
    every call, which means no queued welcome (parent, child, or sibling)
    can ever be delivered or retried."""
    try:
        await welcomes.drain()
    except Exception as exc:  # noqa: BLE001 — we want to see exactly what breaks
        pytest.fail(f"welcomes.drain() raised {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Claim 1 — sibling welcomes via the durable queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sibling_welcome_is_enqueued_durably(async_client, owner, monkeypatch):
    """After a sibling is added, there should be a welcome_deliveries row for
    them (recipient_kind='sibling'), the same durable mechanism used for
    parent/child welcomes — not just a best-effort BackgroundTasks send that
    leaves no record and can't be retried if it fails."""
    headers = await _login(async_client)
    sibling = await _add_sibling(async_client, headers, monkeypatch)

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM welcome_deliveries WHERE recipient_id=$1 AND recipient_kind='sibling'",
            uuid.UUID(sibling["id"]),
        )
    assert row is not None, (
        "No welcome_deliveries row was created for the new sibling — sibling welcomes are still "
        "sent only via the legacy background_tasks.add_task(send_sibling_welcome, ...) path in "
        "server.py's sibling_verify(), not through services.welcomes.enqueue()."
    )


# ---------------------------------------------------------------------------
# Claim 2 — sibling removal cancels pending notifications immediately
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_removing_sibling_cancels_pending_notifications(async_client, owner, monkeypatch):
    """A sibling who is owed a pending reply notification, then removed,
    should have that notification explicitly cancelled right away — not
    left 'pending' and only skipped later, lazily, the next time a drain
    happens to run and finds the row gone."""
    headers = await _login(async_client)
    sibling = await _add_sibling(async_client, headers, monkeypatch)
    sibling_id = uuid.UUID(sibling["id"])

    parent = await _create_parent(owner["id"], "TEST_SibFix Amma")
    reply = await _create_reply(owner["id"], parent["id"], "sibfix-reply-1")

    async with get_pool().acquire() as conn:
        await notifications.enqueue_reply(conn, dict(reply))
        before = await conn.fetchrow(
            "SELECT * FROM reply_notifications WHERE reply_id=$1 AND recipient_kind='sibling' AND recipient_id=$2",
            reply["id"], sibling_id,
        )
    assert before is not None, "Setup problem: no sibling reply_notifications row was created to test against."
    assert before["status"] == "pending"

    r = await async_client.delete(f"/api/circle/sibling/{sibling_id}", headers=headers)
    assert r.status_code == 200, r.text

    async with get_pool().acquire() as conn:
        after = await conn.fetchrow(
            "SELECT * FROM reply_notifications WHERE reply_id=$1 AND recipient_kind='sibling' AND recipient_id=$2",
            reply["id"], sibling_id,
        )
    assert after["status"] == "cancelled", (
        f"Expected the pending notification to be cancelled immediately on removal, "
        f"but its status is still {after['status']!r}. remove_sibling() in server.py only "
        f"deletes the care_circle_siblings row — nothing there updates reply_notifications."
    )


# ---------------------------------------------------------------------------
# Claim 3 — phone change re-points undelivered replies, doesn't replay sent ones
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phone_change_recovers_pending_but_not_delivered(async_client, owner, monkeypatch):
    parent = await _create_parent(owner["id"], "TEST_SibFix Amma2")
    reply_pending = await _create_reply(owner["id"], parent["id"], "sibfix-reply-pending")
    reply_sent = await _create_reply(owner["id"], parent["id"], "sibfix-reply-sent")

    old_phone = OWNER_PHONE
    async with get_pool().acquire() as conn:
        await notifications.enqueue_reply(conn, dict(reply_pending))
        await notifications.enqueue_reply(conn, dict(reply_sent))
        await conn.execute(
            "UPDATE reply_notifications SET status='pending',to_phone=$2 WHERE reply_id=$1 AND recipient_kind='user'",
            reply_pending["id"], old_phone,
        )
        await conn.execute(
            "UPDATE reply_notifications SET status='accepted',to_phone=$2,sid='sibfix-sent-sid' WHERE reply_id=$1 AND recipient_kind='user'",
            reply_sent["id"], old_phone,
        )

    headers = await _login(async_client)
    captured = {}

    async def fake_send(email, code):
        captured["code"] = code
        return {"status": "sent"}

    monkeypatch.setattr(verification, "send_otp_email", fake_send)

    new_phone = "+14155569999"
    r = await async_client.post(
        "/api/profile/phone/request", json={"phone": new_phone, "confirmed": True}, headers=headers,
    )
    assert r.status_code == 200, r.text
    challenge_id = r.json()["challenge_id"]

    r = await async_client.post(
        "/api/profile/phone/confirm",
        json={"challenge_id": challenge_id, "code": captured["code"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    async with get_pool().acquire() as conn:
        pending_row = await conn.fetchrow(
            "SELECT * FROM reply_notifications WHERE reply_id=$1 AND recipient_kind='user'", reply_pending["id"],
        )
        sent_row = await conn.fetchrow(
            "SELECT * FROM reply_notifications WHERE reply_id=$1 AND recipient_kind='user'", reply_sent["id"],
        )

    assert pending_row["to_phone"] == new_phone, "An undelivered reply should be redirected to the new number."
    assert pending_row["status"] == "pending"
    assert sent_row["to_phone"] == old_phone, "An already-accepted/sent reply must never be replayed to the new number."
    assert sent_row["status"] == "accepted"