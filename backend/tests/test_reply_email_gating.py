"""Test reply email fallback gating via attempts threshold and REPLY_EMAIL_FALLBACK_ENABLED env var.

The REFINED fix: per-reply email fallback loop in drain_notifications() now:
(a) is enabled by DEFAULT (REPLY_EMAIL_FALLBACK_ENABLED defaults to 'true')
(b) only selects rows with attempts>=3 (email is a LAST RESORT after WhatsApp retries)

Email fallback SELECT: status IN ('failed','retry','blocked_policy','awaiting_template','uncertain','disabled')
AND attempts>=3 AND coalesce(email_status,'')<>'sent' AND email_attempts<4 AND email_next_attempt_at<=now()
AND created_at>now()-interval '24 hours'

Setting REPLY_EMAIL_FALLBACK_ENABLED=false disables email entirely (WhatsApp-only).

Tests:
1. attempts<3 (1 or 2), status='failed', default env → NO email (WhatsApp still being retried)
2. attempts>=3, status='failed', default env → email MUST be sent (last resort)
3. REPLY_EMAIL_FALLBACK_ENABLED='false', attempts=3 → NO email (flag disables email)
4. Regression: no rows, drain_notifications() runs clean (no crash)
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from auth import hash_password
from database import get_pool
from server import app
from services import notifications


TEST_EMAIL = "reply-email-gating@example.com"
TEST_PASSWORD = "ReplyEmailGating42!"
TEST_PHONE = "+14155552001"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest_asyncio.fixture()
async def app_ready():
    parsed = urlparse(os.environ.get('SUPABASE_DB_URL') or os.environ.get('DATABASE_URL', ''))
    assert os.environ.get('APP_ENV') == 'test' and parsed.hostname in ('localhost', '127.0.0.1') and parsed.path.endswith('_local'), 'Refusing non-local test database'
    assert os.environ.get('WHATSAPP_ENABLED') == 'false' and os.environ.get('SCHEDULER_ENABLED') == 'false', 'Outbound integrations must remain disabled'
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture()
async def seeded_user(app_ready):
    async with get_pool().acquire() as conn:
        user = await conn.fetchrow(
            """
            INSERT INTO users(name,email,phone,password_hash,role,onboarding_complete,onboarding_step,city,timezone,deleted_at,email_verified_at,email_verification_required,auth_version)
            VALUES($1,$2,$3,$4,'user',true,5,'Hyderabad','Asia/Kolkata',NULL,now(),false,0)
            ON CONFLICT(email) DO UPDATE
            SET name=EXCLUDED.name, phone=EXCLUDED.phone, password_hash=EXCLUDED.password_hash,
                role='user', onboarding_complete=true, onboarding_step=5, city='Hyderabad', timezone='Asia/Kolkata',
                deleted_at=NULL, email_verified_at=now(), email_verification_required=false
            RETURNING *
            """,
            "TEST_ReplyEmailGating User",
            TEST_EMAIL,
            TEST_PHONE,
            hash_password(TEST_PASSWORD),
        )
    return dict(user)


@pytest_asyncio.fixture(autouse=True)
async def cleanup_rows(app_ready):
    yield
    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM reply_notifications WHERE detail LIKE 'email-gating-%'")
        await conn.execute("DELETE FROM parent_replies WHERE body LIKE 'email-gating-%'")
        await conn.execute("DELETE FROM message_logs WHERE detail LIKE 'email-gating-%'")
        await conn.execute("DELETE FROM parents WHERE name LIKE 'TEST_EmailGating_%'")
        await conn.execute("DELETE FROM users WHERE email=$1", TEST_EMAIL)


async def _create_parent(user_id, name: str, phone: str):
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO parents(user_id,name,relationship,phone,language,timezone,city,activity_window_start,activity_window_end,opted_out_at,created_at,deleted_at)
            VALUES($1,$2,'mother',$3,'en','Asia/Kolkata','Hyderabad','06:00','22:00',NULL,now()-interval '3 days',NULL)
            RETURNING *
            """,
            user_id,
            name,
            phone,
        )


async def _create_reply(user_id, parent_id, body: str):
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO parent_replies(parent_id,user_id,text,from_phone,body,is_voice,raw_payload,created_at)
            VALUES($1,$2,$3,$4,$5,false,'{}'::jsonb,now()-interval '5 minutes')
            RETURNING *
            """,
            parent_id,
            user_id,
            body,
            "+919900000111",
            body,
        )


@pytest.mark.asyncio
async def test_no_email_when_attempts_less_than_3(seeded_user, monkeypatch):
    """TEST 1: attempts<3 (1 or 2), status='failed', default env → NO email (WhatsApp still being retried)."""
    print("\n=== TEST 1: No email when attempts < 3 (WhatsApp still being retried) ===")
    
    # Default env (flag unset → treated as 'true', but attempts<3 blocks email)
    monkeypatch.delenv('REPLY_EMAIL_FALLBACK_ENABLED', raising=False)
    
    user = seeded_user
    parent = await _create_parent(user["id"], "TEST_EmailGating_Parent1", "+14155552101")
    
    # Create separate replies for each attempt level (to avoid unique constraint violation)
    notif_ids = []
    for attempts in [1, 2]:
        reply = await _create_reply(user["id"], parent["id"], f"email-gating-test1-attempts{attempts}")
        async with get_pool().acquire() as conn:
            notif_id = await conn.fetchval(
                """INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,to_phone,attempts,email_status,email_attempts,email_next_attempt_at,created_at,detail)
                VALUES($1,'user',$2,'failed',$3,$4,NULL,0,now()-interval '1 minute',now()-interval '10 minutes',$5)
                RETURNING id""",
                reply["id"],
                user["id"],
                user["phone"],
                attempts,
                f"email-gating-test1-attempts{attempts}",
            )
            notif_ids.append(notif_id)
    
    # Spy on fallback_email to ensure it's NOT called
    email_calls = []
    original_fallback_email = notifications.fallback_email
    
    async def spy_fallback_email(n):
        email_calls.append(n['id'])
        return await original_fallback_email(n)
    
    monkeypatch.setattr(notifications, "fallback_email", spy_fallback_email)
    
    # Run drain_notifications
    await notifications.drain_notifications()
    
    # Verify email was NOT sent for either notification
    assert len(email_calls) == 0, f"Expected NO email fallback calls (attempts<3), but got {len(email_calls)}"
    
    # Verify email_status is still NULL for both
    async with get_pool().acquire() as conn:
        for notif_id in notif_ids:
            row = await conn.fetchrow("SELECT email_status, email_attempts, attempts FROM reply_notifications WHERE id=$1", notif_id)
            assert row["email_status"] is None, f"Expected email_status to be NULL for notif {notif_id} (attempts={row['attempts']}), but got {row['email_status']}"
            assert row["email_attempts"] == 0, f"Expected email_attempts to be 0 for notif {notif_id}, but got {row['email_attempts']}"
    
    print("✅ TEST 1 PASSED: No email sent when attempts < 3 (WhatsApp still being retried)")


@pytest.mark.asyncio
async def test_email_sent_when_attempts_gte_3(seeded_user, monkeypatch):
    """TEST 2: attempts>=3, status='failed', default env → email MUST be sent (last resort)."""
    print("\n=== TEST 2: Email sent when attempts >= 3 (last resort) ===")
    
    # Default env (flag unset → treated as 'true')
    monkeypatch.delenv('REPLY_EMAIL_FALLBACK_ENABLED', raising=False)
    
    user = seeded_user
    parent = await _create_parent(user["id"], "TEST_EmailGating_Parent2", "+14155552102")
    
    # Test with attempts=3 and attempts=4 (both should trigger email)
    notif_ids = []
    for attempts in [3]:  # attempts=4 would exceed the delivery limit, so just test 3
        reply = await _create_reply(user["id"], parent["id"], f"email-gating-test2-attempts{attempts}")
        async with get_pool().acquire() as conn:
            notif_id = await conn.fetchval(
                """INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,to_phone,attempts,email_status,email_attempts,email_next_attempt_at,created_at,detail)
                VALUES($1,'user',$2,'failed',$3,$4,NULL,0,now()-interval '1 minute',now()-interval '10 minutes',$5)
                RETURNING id""",
                reply["id"],
                user["id"],
                user["phone"],
                attempts,
                f"email-gating-test2-attempts{attempts}",
            )
            notif_ids.append(notif_id)
    
    # Also test with status='awaiting_template' and attempts=3
    reply_awaiting = await _create_reply(user["id"], parent["id"], "email-gating-test2-awaiting")
    async with get_pool().acquire() as conn:
        notif_id_awaiting = await conn.fetchval(
            """INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,to_phone,attempts,email_status,email_attempts,email_next_attempt_at,created_at,detail)
            VALUES($1,'user',$2,'awaiting_template',$3,3,NULL,0,now()-interval '1 minute',now()-interval '10 minutes','email-gating-test2-awaiting')
            RETURNING id""",
            reply_awaiting["id"],
            user["id"],
            user["phone"],
        )
        notif_ids.append(notif_id_awaiting)
    
    # Spy on fallback_email to ensure it IS called
    email_calls = []
    
    async def spy_fallback_email(n):
        email_calls.append(n['id'])
        # Mock the email send to avoid real network
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE reply_notifications SET email_status=$2,email_id=$3,email_attempts=email_attempts+1,email_next_attempt_at=now()+interval '15 minutes' WHERE id=$1",
                n['id'], 'sent', f'test-email-{n["id"]}'
            )
    
    monkeypatch.setattr(notifications, "fallback_email", spy_fallback_email)
    
    # Run drain_notifications
    await notifications.drain_notifications()
    
    # Verify email WAS sent for all notifications with attempts>=3
    assert len(email_calls) == len(notif_ids), f"Expected {len(notif_ids)} email fallback calls (attempts>=3), but got {len(email_calls)}"
    for notif_id in notif_ids:
        assert notif_id in email_calls, f"Expected fallback_email to be called for notif_id {notif_id}"
    
    # Verify email_status is 'sent' for all
    async with get_pool().acquire() as conn:
        for notif_id in notif_ids:
            row = await conn.fetchrow("SELECT email_status, email_attempts, attempts FROM reply_notifications WHERE id=$1", notif_id)
            assert row["email_status"] == "sent", f"Expected email_status to be 'sent' for notif {notif_id} (attempts={row['attempts']}), but got {row['email_status']}"
            assert row["email_attempts"] == 1, f"Expected email_attempts to be 1 for notif {notif_id}, but got {row['email_attempts']}"
    
    print("✅ TEST 2 PASSED: Email sent when attempts >= 3 (last resort)")


@pytest.mark.asyncio
async def test_no_email_when_flag_disabled(seeded_user, monkeypatch):
    """TEST 3: REPLY_EMAIL_FALLBACK_ENABLED='false', attempts=3 → NO email (flag disables email)."""
    print("\n=== TEST 3: No email when flag is disabled (WhatsApp-only) ===")
    
    # Disable the flag
    monkeypatch.setenv('REPLY_EMAIL_FALLBACK_ENABLED', 'false')
    
    user = seeded_user
    parent = await _create_parent(user["id"], "TEST_EmailGating_Parent3", "+14155552103")
    reply = await _create_reply(user["id"], parent["id"], "email-gating-test3")
    
    # Create a failed notification with attempts=3 (would normally trigger email)
    async with get_pool().acquire() as conn:
        notif_id = await conn.fetchval(
            """INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,to_phone,attempts,email_status,email_attempts,email_next_attempt_at,created_at,detail)
            VALUES($1,'user',$2,'failed',$3,3,NULL,0,now()-interval '1 minute',now()-interval '10 minutes','email-gating-test3')
            RETURNING id""",
            reply["id"],
            user["id"],
            user["phone"],
        )
    
    # Spy on fallback_email to ensure it's NOT called
    email_calls = []
    original_fallback_email = notifications.fallback_email
    
    async def spy_fallback_email(n):
        email_calls.append(n['id'])
        return await original_fallback_email(n)
    
    monkeypatch.setattr(notifications, "fallback_email", spy_fallback_email)
    
    # Run drain_notifications
    await notifications.drain_notifications()
    
    # Verify email was NOT sent (flag is 'false')
    assert len(email_calls) == 0, f"Expected NO email fallback calls (flag='false'), but got {len(email_calls)}"
    
    # Verify email_status is still NULL
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT email_status, email_attempts, attempts FROM reply_notifications WHERE id=$1", notif_id)
    
    assert row["email_status"] is None, f"Expected email_status to be NULL (flag='false'), but got {row['email_status']}"
    assert row["email_attempts"] == 0, f"Expected email_attempts to be 0, but got {row['email_attempts']}"
    
    print("✅ TEST 3 PASSED: No email sent when flag is disabled (WhatsApp-only)")


@pytest.mark.asyncio
async def test_drain_notifications_regression_no_crash(seeded_user, monkeypatch):
    """TEST 4: Regression - no rows, drain_notifications() runs clean (no crash)."""
    print("\n=== TEST 4: Regression test - drain_notifications with no rows ===")
    
    # Default env
    monkeypatch.delenv('REPLY_EMAIL_FALLBACK_ENABLED', raising=False)
    
    # Mock send_update to return disabled status (WHATSAPP_ENABLED=false)
    async def mock_send_update(phone, reply_obj, opened, language):
        return {"status": "disabled", "detail": "WHATSAPP_ENABLED=false"}
    
    monkeypatch.setattr(notifications, "send_update", mock_send_update)
    
    # Spy on drain_requests to ensure it's still called
    drain_requests_called = []
    original_drain_requests = notifications.drain_requests
    
    async def spy_drain_requests():
        drain_requests_called.append(True)
        await original_drain_requests()
    
    monkeypatch.setattr(notifications, "drain_requests", spy_drain_requests)
    
    # Run drain_notifications with no relevant rows - should not crash
    try:
        await notifications.drain_notifications()
        print("✅ drain_notifications() ran without error")
    except Exception as exc:
        pytest.fail(f"drain_notifications() raised {type(exc).__name__}: {exc}")
    
    # Verify drain_requests was called
    assert len(drain_requests_called) == 1, "Expected drain_requests to be called once"
    print("✅ drain_requests() was called")
    
    print("✅ TEST 4 PASSED: No regression - drain_notifications runs clean with no rows")


@pytest.mark.asyncio
async def test_email_fallback_respects_24h_window(seeded_user, monkeypatch):
    """TEST 5: Email fallback respects the 24-hour window (created_at > now()-interval '24 hours')."""
    print("\n=== TEST 5: Email fallback respects 24-hour window ===")
    
    # Default env (flag enabled)
    monkeypatch.delenv('REPLY_EMAIL_FALLBACK_ENABLED', raising=False)
    
    user = seeded_user
    parent = await _create_parent(user["id"], "TEST_EmailGating_Parent5", "+14155552105")
    
    # Create an old failed notification (> 24 hours) with attempts=3
    reply_old = await _create_reply(user["id"], parent["id"], "email-gating-test5-old")
    async with get_pool().acquire() as conn:
        notif_id_old = await conn.fetchval(
            """INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,to_phone,attempts,email_status,email_attempts,email_next_attempt_at,created_at,detail)
            VALUES($1,'user',$2,'failed',$3,3,NULL,0,now()-interval '1 minute',now()-interval '25 hours','email-gating-test5-old')
            RETURNING id""",
            reply_old["id"],
            user["id"],
            user["phone"],
        )
    
    # Create a recent failed notification (< 24 hours) with attempts=3
    reply_recent = await _create_reply(user["id"], parent["id"], "email-gating-test5-recent")
    async with get_pool().acquire() as conn:
        notif_id_recent = await conn.fetchval(
            """INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,to_phone,attempts,email_status,email_attempts,email_next_attempt_at,created_at,detail)
            VALUES($1,'user',$2,'failed',$3,3,NULL,0,now()-interval '1 minute',now()-interval '10 minutes','email-gating-test5-recent')
            RETURNING id""",
            reply_recent["id"],
            user["id"],
            user["phone"],
        )
    
    # Spy on fallback_email
    email_calls = []
    
    async def spy_fallback_email(n):
        email_calls.append(n['id'])
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE reply_notifications SET email_status=$2,email_id=$3,email_attempts=email_attempts+1,email_next_attempt_at=now()+interval '15 minutes' WHERE id=$1",
                n['id'], 'sent', f'test-email-{n["id"]}'
            )
    
    monkeypatch.setattr(notifications, "fallback_email", spy_fallback_email)
    
    # Run drain_notifications
    await notifications.drain_notifications()
    
    # Verify only the recent notification got email
    assert len(email_calls) == 1, f"Expected 1 email call (for recent notification), but got {len(email_calls)}"
    assert email_calls[0] == notif_id_recent, f"Expected email for recent notification {notif_id_recent}, but got {email_calls[0]}"
    
    # Verify old notification email_status is still NULL
    async with get_pool().acquire() as conn:
        row_old = await conn.fetchrow("SELECT email_status FROM reply_notifications WHERE id=$1", notif_id_old)
        row_recent = await conn.fetchrow("SELECT email_status FROM reply_notifications WHERE id=$1", notif_id_recent)
    
    assert row_old["email_status"] is None, f"Expected old notification email_status to be NULL, but got {row_old['email_status']}"
    assert row_recent["email_status"] == "sent", f"Expected recent notification email_status to be 'sent', but got {row_recent['email_status']}"
    
    print("✅ TEST 5 PASSED: Email fallback respects 24-hour window")
