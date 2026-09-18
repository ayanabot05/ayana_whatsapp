"""Iteration 20 isolated service coverage on LOCAL Postgres with mocked providers."""

from __future__ import annotations

import json
import uuid
import os
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from auth import hash_password, token_still_valid
from database import get_pool
from server import app
from services import notifications, verification
from services import notification_transport as nt
from services import reply_media
import scheduler
import escalation


OWNER_EMAIL = "care-owner@example.com"
OWNER_PASSWORD = "CareOwnerTest42!"
OTHER_EMAIL = "care-other@example.com"
OTHER_PASSWORD = "CareOtherTest42!"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest_asyncio.fixture()
async def app_ready():
    parsed = urlparse(os.environ.get('SUPABASE_DB_URL') or os.environ.get('DATABASE_URL',''))
    assert os.environ.get('APP_ENV') == 'test' and parsed.hostname in ('localhost','127.0.0.1') and parsed.path.endswith('_local'), 'Refusing non-local test database'
    assert os.environ.get('WHATSAPP_ENABLED') == 'false' and os.environ.get('SCHEDULER_ENABLED') == 'false', 'Outbound integrations must remain disabled'
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture()
async def async_client(app_ready):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture()
async def seeded_users(app_ready):
    async with get_pool().acquire() as conn:
        owner = await conn.fetchrow(
            """
            INSERT INTO users(name,email,phone,password_hash,role,onboarding_complete,onboarding_step,city,timezone,deleted_at,email_verified_at,email_verification_required,auth_version)
            VALUES($1,$2,$3,$4,'user',true,5,'Hyderabad','Asia/Kolkata',NULL,now(),false,0)
            ON CONFLICT(email) DO UPDATE
            SET name=EXCLUDED.name, phone=EXCLUDED.phone, password_hash=EXCLUDED.password_hash,
                role='user', onboarding_complete=true, onboarding_step=5, city='Hyderabad', timezone='Asia/Kolkata',
                deleted_at=NULL, email_verified_at=now(), email_verification_required=false
            RETURNING *
            """,
            "TEST20 Owner",
            OWNER_EMAIL,
            "+14155550001",
            hash_password(OWNER_PASSWORD),
        )
        other = await conn.fetchrow(
            """
            INSERT INTO users(name,email,phone,password_hash,role,onboarding_complete,onboarding_step,city,timezone,deleted_at,email_verified_at,email_verification_required,auth_version)
            VALUES($1,$2,$3,$4,'user',true,5,'Austin','Asia/Kolkata',NULL,now(),false,0)
            ON CONFLICT(email) DO UPDATE
            SET name=EXCLUDED.name, phone=EXCLUDED.phone, password_hash=EXCLUDED.password_hash,
                role='user', onboarding_complete=true, onboarding_step=5, city='Austin', timezone='Asia/Kolkata',
                deleted_at=NULL, email_verified_at=now(), email_verification_required=false
            RETURNING *
            """,
            "TEST20 Other",
            OTHER_EMAIL,
            "+14155550002",
            hash_password(OTHER_PASSWORD),
        )
        await conn.execute(
            """
            INSERT INTO activation_state(user_id, whatsapp_activated, activated_at)
            VALUES($1,true,now()-interval '2 days')
            ON CONFLICT(user_id) DO UPDATE SET whatsapp_activated=true, activated_at=excluded.activated_at
            """,
            owner["id"],
        )
        await conn.execute(
            """
            INSERT INTO payment_state(user_id,status,plan,billing,updated_at)
            VALUES($1,'trial','raksha','month',now())
            ON CONFLICT(user_id) DO UPDATE SET status='trial', plan='raksha', billing='month', updated_at=now()
            """,
            owner["id"],
        )
    return {"owner": dict(owner), "other": dict(other)}


@pytest_asyncio.fixture(autouse=True)
async def cleanup_rows(app_ready):
    yield
    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM reply_notifications WHERE detail LIKE 'iter20-%'")
        await conn.execute("DELETE FROM parent_replies WHERE body LIKE 'iter20-%' OR text LIKE 'iter20-%'")
        await conn.execute("DELETE FROM message_logs WHERE detail LIKE 'iter20-%'")
        await conn.execute("DELETE FROM care_send_claims WHERE event_key LIKE 'iter20:%' OR event_key LIKE 'child-button:iter20-%'")
        await conn.execute("DELETE FROM care_watch WHERE parent_id IN (SELECT id FROM parents WHERE name LIKE 'TEST20_%')")
        await conn.execute("DELETE FROM recipient_sessions WHERE phone LIKE '+1415555%'")
        await conn.execute("DELETE FROM verification_challenges WHERE email IN ($1,$2)", OWNER_EMAIL, OTHER_EMAIL)
        await conn.execute("DELETE FROM parents WHERE name LIKE 'TEST20_%'")


async def _login(client: httpx.AsyncClient, email: str, password: str) -> tuple[str, str]:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    csrf = client.cookies.get("csrf_token")
    assert csrf
    return r.json()["token"], csrf


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


async def _create_reply(user_id, parent_id, body: str, *, is_voice=False, media_id=None, raw_payload=None):
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO parent_replies(parent_id,user_id,text,from_phone,body,is_voice,raw_payload,media_id,created_at)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,now()-interval '5 minutes')
            RETURNING *
            """,
            parent_id,
            user_id,
            body,
            "+919900000111",
            body,
            is_voice,
            json.dumps(raw_payload or {}),
            media_id,
        )


@pytest.mark.asyncio
async def test_verification_issue_check_consume_attempts_and_replay(seeded_users, monkeypatch):
    captured = {}

    async def fake_send(email, code):
        captured["email"] = email
        captured["code"] = code
        return {"status": "sent"}

    monkeypatch.setattr(verification, "send_otp_email", fake_send)
    owner = seeded_users["owner"]

    issued = await verification.issue(owner["id"], owner["email"], "change_phone", "+14155559991")
    cid = issued["challenge_id"]
    with pytest.raises(Exception):
        await verification.check(cid, "000000", owner["id"], "change_phone", "+14155559991")

    async with get_pool().acquire() as conn:
        attempts = await conn.fetchval("SELECT attempts FROM verification_challenges WHERE id=$1", cid)
    assert attempts == 1

    with pytest.raises(Exception):
        await verification.check(cid, captured["code"], owner["id"], "verify_email", "+14155559991")

    proof = await verification.check(cid, captured["code"], owner["id"], "change_phone", "+14155559991")
    async with get_pool().acquire() as conn, conn.transaction():
        await verification.consume(conn, proof)
    async with get_pool().acquire() as conn, conn.transaction():
        with pytest.raises(Exception):
            await verification.consume(conn, proof)


@pytest.mark.asyncio
async def test_verification_resend_limit_and_provider_failure(seeded_users, monkeypatch):
    async def ok_send(email, code):
        return {"status": "sent"}

    async def bad_send(email, code):
        return {"status": "failed", "detail": "iter20-provider-fail"}

    owner = seeded_users["owner"]
    monkeypatch.setattr(verification, "send_otp_email", ok_send)
    await verification.issue(owner["id"], owner["email"], "verify_email", owner["email"])
    with pytest.raises(Exception):
        await verification.issue(owner["id"], owner["email"], "verify_email", owner["email"])

    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE verification_challenges SET created_at = now()-interval '2 minutes' WHERE user_id=$1",
            owner["id"],
        )

    monkeypatch.setattr(verification, "send_otp_email", bad_send)
    with pytest.raises(Exception):
        await verification.issue(owner["id"], owner["email"], "change_email", "iter20-new@example.com")
    async with get_pool().acquire() as conn:
        delivered = await conn.fetchval(
            "SELECT delivered FROM verification_challenges WHERE user_id=$1 AND purpose='change_email' ORDER BY created_at DESC LIMIT 1",
            owner["id"],
        )
    assert delivered is False


@pytest.mark.asyncio
async def test_forgot_password_generic_and_reset_invalidates_old_token(async_client, seeded_users, monkeypatch):
    captured = {}

    async def fake_send(email, code):
        captured[email] = code
        return {"status": "sent"}

    monkeypatch.setattr(verification, "send_otp_email", fake_send)
    monkeypatch.setenv("EMAIL_ENABLED", "true")
    monkeypatch.setenv("RESEND_API_KEY", "iter20-key")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")

    known = await async_client.post("/api/auth/forgot-password", json={"email": OWNER_EMAIL})
    unknown = await async_client.post("/api/auth/forgot-password", json={"email": "iter20-unknown@example.com"})
    assert known.status_code == 200
    assert unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"]

    old_token, _ = await _login(async_client, OWNER_EMAIL, OWNER_PASSWORD)
    reset = await async_client.post(
        "/api/auth/reset-password",
        json={
            "email": OWNER_EMAIL,
            "challenge_id": known.json()["challenge_id"],
            "code": captured[OWNER_EMAIL],
            "new_password": "CareOwnerTest43!",
        },
    )
    assert reset.status_code == 200, reset.text

    old_me = await async_client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert old_me.status_code == 401

    login2 = await async_client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": "CareOwnerTest43!"})
    assert login2.status_code == 200
    new_token = login2.json()["token"]
    back = await async_client.post(
        "/api/auth/change-password",
        json={"current_password": "CareOwnerTest43!", "new_password": OWNER_PASSWORD},
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert back.status_code == 200


@pytest.mark.asyncio
async def test_phone_change_flow_requires_confirm_conflict_and_replay_block(async_client, seeded_users, monkeypatch):
    token, _ = await _login(async_client, OWNER_EMAIL, OWNER_PASSWORD)
    auth = {"Authorization": f"Bearer {token}"}
    captured = {}

    async def fake_send(email, code):
        captured["code"] = code
        return {"status": "sent"}

    monkeypatch.setattr(verification, "send_otp_email", fake_send)

    r1 = await async_client.post(
        "/api/profile/phone/request",
        json={"phone": "+14155559996", "confirmed": False},
        headers=auth,
    )
    assert r1.status_code == 400

    conflict = await async_client.post(
        "/api/profile/phone/request",
        json={"phone": seeded_users["other"]["phone"], "confirmed": True},
        headers=auth,
    )
    assert conflict.status_code == 409

    req = await async_client.post(
        "/api/profile/phone/request",
        json={"phone": "(415) 555-9997", "confirmed": True},
        headers=auth,
    )
    assert req.status_code == 200

    bypass = await async_client.put(
        "/api/profile/child",
        json={"name": "TEST20 Owner", "phone": "+14155557770", "city": "Hyd", "timezone": "Asia/Kolkata"},
        headers=auth,
    )
    assert bypass.status_code == 409

    ok = await async_client.post(
        "/api/profile/phone/confirm",
        json={"challenge_id": req.json()["challenge_id"], "code": captured["code"]},
        headers=auth,
    )
    assert ok.status_code == 200
    updated_phone = ok.json()["user"]["phone"]
    assert updated_phone.startswith("+") and updated_phone[1:].isdigit()

    replay = await async_client.post(
        "/api/profile/phone/confirm",
        json={"challenge_id": req.json()["challenge_id"], "code": captured["code"]},
        headers=auth,
    )
    assert replay.status_code in (400, 409)


@pytest.mark.asyncio
async def test_notifications_deliver_current_phone_and_closed_child_window(seeded_users, monkeypatch):
    owner = seeded_users["owner"]
    parent = await _create_parent(owner["id"], "TEST20_N_Deliver", "+14155551001")
    reply = await _create_reply(owner["id"], parent["id"], "iter20-deliver")

    async with get_pool().acquire() as conn:
        notif_id = await conn.fetchval(
            "INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,detail) VALUES($1,'user',$2,'pending','iter20-deliver') RETURNING id",
            reply["id"],
            owner["id"],
        )
        await conn.execute("INSERT INTO recipient_sessions(phone,last_inbound_at) VALUES($1,$2)", parent["phone"], _now())
        await conn.execute("UPDATE users SET phone=$2 WHERE id=$1", owner["id"], "+14155550099")

    sent = []

    async def fake_send_update(phone, reply_obj, opened, language):
        sent.append({"phone": phone, "opened": opened})
        return {"status": "sent", "sid": "iter20-sid-1"}

    async def fake_send_email(recipient, reply_obj, notification_id):
        return {"status": "disabled"}

    monkeypatch.setattr(notifications, "send_update", fake_send_update)
    monkeypatch.setattr(notifications, "send_update_email", fake_send_email)
    await notifications.deliver(notif_id)

    assert sent[0]["phone"] == "+14155550099"
    assert sent[0]["opened"] is False


@pytest.mark.asyncio
async def test_notification_transport_template_builder_and_phone_prefix(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://distance-care-3.preview.emergentagent.com")
    monkeypatch.setenv("WA_CHILD_REPLY_TEMPLATES_ENABLED", "true")
    monkeypatch.setenv("WA_REPLY_DYNAMIC_URLS", "false")

    captured = []
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request):
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"messages": [{"id": "wamid.iter20"}]})

    transport = httpx.MockTransport(handler)

    def async_client_factory(*args, **kwargs):
        return real_async_client(transport=transport, timeout=kwargs.get("timeout", 20))

    monkeypatch.setattr(nt, "whatsapp_enabled", lambda: True)
    monkeypatch.setattr(nt, "_creds", lambda: ("token", "phone-id"))
    monkeypatch.setattr(nt, "_messages_url", lambda phone_id: "https://graph.test/messages")
    monkeypatch.setattr(nt.httpx, "AsyncClient", async_client_factory)

    base_reply = {
        "id": str(uuid.uuid4()),
        "parent_name": "Amma",
        "prompt": "care update",
        "display_time": "16 Sep, 10:00 AM IST",
        "body": "iter20-template",
        "is_voice": False,
    }
    for lang in ("en", "hi", "te"):
        res = await nt.send_update("+919876543210", base_reply, session_open=False, language=lang)
        assert res["status"] == "sent"
    voice = {**base_reply, "id": str(uuid.uuid4()), "is_voice": True}
    vres = await nt.send_update("+919876543211", voice, session_open=False, language="en")
    assert vres["status"] == "sent"

    text_templates = [p for p in captured if p["template"]["name"].startswith("ayana_parent_reply_")]
    assert len(text_templates) == 3
    for payload in text_templates:
        assert len(payload["template"]["components"][0]["parameters"]) == 4
        assert not payload["to"].startswith("+")
    voice_payload = [p for p in captured if p["template"]["name"].startswith("ayana_parent_voice_")][0]
    assert len(voice_payload["template"]["components"][0]["parameters"]) == 3


@pytest.mark.asyncio
async def test_receipt_progression_fallback_once_and_uncertain_not_retried(seeded_users, monkeypatch):
    owner = seeded_users["owner"]
    parent = await _create_parent(owner["id"], "TEST20_N_Receipt", "+14155551002")
    reply = await _create_reply(owner["id"], parent["id"], "iter20-receipt")
    reply2 = await _create_reply(owner["id"], parent["id"], "iter20-receipt-2")
    reply3 = await _create_reply(owner["id"], parent["id"], "iter20-receipt-3")

    async with get_pool().acquire() as conn:
        r1 = await conn.fetchval(
            "INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,to_phone,sid,status,detail) VALUES($1,'user',$2,$3,'iter20-sid-r1','accepted','iter20-receipt') RETURNING id",
            reply["id"],
            owner["id"],
            owner["phone"],
        )
        r2 = await conn.fetchval(
            "INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,to_phone,sid,status,detail) VALUES($1,'user',$2,$3,'iter20-sid-r2','accepted','iter20-receipt') RETURNING id",
            reply2["id"],
            owner["id"],
            owner["phone"],
        )
        r3 = await conn.fetchval(
            "INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,detail) VALUES($1,'user',$2,'pending','iter20-uncertain') RETURNING id",
            reply3["id"],
            owner["id"],
        )

    emails = []

    async def fake_email(recipient, reply_obj, nid):
        emails.append(nid)
        return {"status": "sent", "id": "iter20-email"}

    async def boom(*args, **kwargs):
        raise RuntimeError("iter20-timeout")

    monkeypatch.setattr(notifications, "send_update_email", fake_email)
    await notifications.persist_receipt({"id": "iter20-sid-r1", "status": "delivered"})
    await notifications.persist_receipt({"id": "iter20-sid-r1", "status": "read"})
    await notifications.persist_receipt({"id": "iter20-sid-r1", "status": "failed", "errors": [{"code": 131000, "title": "x"}]})
    await notifications.persist_receipt({"id": "iter20-sid-r2", "status": "failed", "errors": [{"code": 131000, "title": "x"}]})
    await notifications.persist_receipt({"id": "iter20-sid-r2", "status": "failed", "errors": [{"code": 131000, "title": "x"}]})

    monkeypatch.setattr(notifications, "send_update", boom)
    await notifications.deliver(r3)
    await notifications.drain_notifications()

    async with get_pool().acquire() as conn:
        s1 = await conn.fetchval("SELECT status FROM reply_notifications WHERE id=$1", r1)
        s2 = await conn.fetchval("SELECT email_status FROM reply_notifications WHERE id=$1", r2)
        attempts = await conn.fetchval("SELECT attempts FROM reply_notifications WHERE id=$1", r3)
        state = await conn.fetchval("SELECT status FROM reply_notifications WHERE id=$1", r3)
    assert s1 == "read"
    assert s2 == "sent"
    assert len(emails) == 1
    assert state == "uncertain"
    assert attempts == 1


@pytest.mark.asyncio
async def test_child_context_sid_authorization_and_wamid_dedup(seeded_users, monkeypatch):
    owner = seeded_users["owner"]
    parent = await _create_parent(owner["id"], "TEST20_N_Context", "+14155551004")
    reply = await _create_reply(owner["id"], parent["id"], "iter20-context")

    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,to_phone,sid,status,detail) VALUES($1,'user',$2,$3,'iter20-context-sid','accepted','iter20-context')",
            reply["id"],
            owner["id"],
            owner["phone"],
        )

    calls = 0

    async def fake_send_update(phone, reply_obj, opened, language):
        nonlocal calls
        calls += 1
        return {"status": "sent", "sid": "iter20-child"}

    monkeypatch.setattr(notifications, "send_update", fake_send_update)
    ts = _now()
    await notifications.record_recipient_inbound(owner["phone"], ts, context_id="iter20-context-sid", requested=True, wam_id="iter20-wam-1")
    await notifications.record_recipient_inbound(owner["phone"], ts, context_id="iter20-context-sid", requested=True, wam_id="iter20-wam-1")

    async with get_pool().acquire() as conn:
        await conn.execute("UPDATE users SET phone=$2 WHERE id=$1", owner["id"], "+14155550123")
    await notifications.record_recipient_inbound(owner["phone"], ts, context_id="iter20-context-sid", requested=True, wam_id="iter20-wam-2")
    assert calls == 1


@pytest.mark.asyncio
async def test_scheduler_deliver_parent_core_guards(seeded_users, monkeypatch):
    owner = seeded_users["owner"]
    parent = await _create_parent(owner["id"], "TEST20_Sched", "+14155551005")
    now = _now().replace(second=0, microsecond=0)
    local = scheduler.local_now(dict(parent), now)
    slot = local.strftime("%H:%M")

    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO schedules(parent_id,user_id,mode,messages,active,created_at) VALUES($1,$2,'raksha',$3::jsonb,true,now()-interval '2 days')",
            parent["id"],
            owner["id"],
            json.dumps([
                {"category": "medicine", "time": slot, "custom_text": "iter20-med-A"},
                {"category": "medicine", "time": slot, "custom_text": "iter20-med-B"},
            ]),
        )

    sent = []

    async def fake_send(parent_doc, category, day, variants, medicine_name=""):
        sent.append(medicine_name)
        return {"status": "sent", "sid": f"iter20-sched-{len(sent)}", "detail": "iter20-sched"}

    monkeypatch.setattr(scheduler, "send_dynamic_checkin", fake_send)
    await scheduler._deliver_parent(dict(parent), now)
    await scheduler._deliver_parent(dict(parent), now + timedelta(seconds=10))
    await scheduler._deliver_parent(dict(parent), now + timedelta(seconds=130))
    assert len(sent) == 2
    assert set(sent) == {"iter20-med-A", "iter20-med-B"}

    async with get_pool().acquire() as conn:
        await conn.execute("UPDATE parents SET opted_out_at=now() WHERE id=$1", parent["id"])
    await scheduler._deliver_parent(dict(parent), now + timedelta(seconds=300))
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_escalation_watch_parent_no_delivered_then_warn_then_reply_suppresses(seeded_users, monkeypatch):
    owner = seeded_users["owner"]
    parent = await _create_parent(owner["id"], "TEST20_Esc", "+14155551006")
    local = _now().astimezone().replace(hour=15, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(escalation, "local_now", lambda p: local)

    templates = []

    async def fake_template(phone, template, lang, params, category):
        templates.append(template)
        return {"status": "sent", "sid": f"iter20-esc-{len(templates)}", "detail": "iter20-esc"}

    monkeypatch.setattr(escalation, "_send_content_template_with_retry", fake_template)
    await escalation._watch_parent(dict(parent))
    assert templates == []

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,delivery_status,created_at,delivered_at,detail)
            VALUES($1,$2,$3,'morning','checkin','sent','delivered',$4,$4,'iter20-esc-log')
            """,
            owner["id"],
            parent["id"],
            local.strftime("%Y-%m-%d"),
            _now() - timedelta(hours=2),
        )
    await escalation._watch_parent(dict(parent))
    before = len(templates)
    assert any(t.startswith("ayana_first_warn_parent_") for t in templates)

    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO parent_replies(parent_id,user_id,text,from_phone,body,is_voice,raw_payload,created_at) VALUES($1,$2,'iter20-r','+9199','iter20-r',false,'{}'::jsonb,now())",
            parent["id"],
            owner["id"],
        )
    await escalation._watch_parent(dict(parent))
    assert len(templates) == before


@pytest.mark.asyncio
async def test_replies_audio_endpoint_owner_only_and_missing_media(async_client, seeded_users, monkeypatch):
    owner_token, _ = await _login(async_client, OWNER_EMAIL, OWNER_PASSWORD)
    other_token, _ = await _login(async_client, OTHER_EMAIL, OTHER_PASSWORD)

    parent = await _create_parent(seeded_users["owner"]["id"], "TEST20_Audio", "+14155551007")
    good = await _create_reply(
        seeded_users["owner"]["id"],
        parent["id"],
        "iter20-voice",
        is_voice=True,
        media_id="iter20-media-1",
        raw_payload={"audio": {"id": "iter20-media-1"}},
    )
    missing = await _create_reply(
        seeded_users["owner"]["id"],
        parent["id"],
        "iter20-missing",
        is_voice=True,
        media_id=None,
        raw_payload={},
    )

    wav = b"RIFF$\x00\x00\x00WAVEfmt "
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request):
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=wav)

    transport = httpx.MockTransport(handler)

    def async_client_factory(*args, **kwargs):
        return real_async_client(transport=transport, timeout=kwargs.get("timeout", 20))

    async def fake_resolve(media_id):
        return "https://meta.local/audio.wav"

    monkeypatch.setattr(reply_media, "resolve_meta_media_url", fake_resolve)
    monkeypatch.setattr(reply_media, "meta_auth_header", lambda: {"Authorization": "Bearer x"})
    monkeypatch.setattr(reply_media.httpx, "AsyncClient", async_client_factory)

    ok = await async_client.get(f"/api/replies/{good['id']}/audio", headers={"Authorization": f"Bearer {owner_token}"})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("audio/")

    wrong = await async_client.get(f"/api/replies/{good['id']}/audio", headers={"Authorization": f"Bearer {other_token}"})
    assert wrong.status_code == 404

    missing_resp = await async_client.get(f"/api/replies/{missing['id']}/audio", headers={"Authorization": f"Bearer {owner_token}"})
    assert missing_resp.status_code == 410


@pytest.mark.asyncio
async def test_auth_regression_versionless_and_change_password_invalidates_same_second(async_client, seeded_users):
    payload = {
        "sub": str(seeded_users["owner"]["id"]),
        "email": OWNER_EMAIL,
        "role": "user",
        "iat": int(_now().timestamp()),
        "type": "access",
    }
    assert token_still_valid(payload, {"auth_version": 0, "password_changed_at": None}) is True

    old_token, _ = await _login(async_client, OWNER_EMAIL, OWNER_PASSWORD)
    changed = await async_client.post(
        "/api/auth/change-password",
        json={"current_password": OWNER_PASSWORD, "new_password": "CareOwnerTest44!"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert changed.status_code == 200

    old_me = await async_client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert old_me.status_code == 401

    relog_after_change = await async_client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": "CareOwnerTest44!"})
    assert relog_after_change.status_code == 200
    access_new = relog_after_change.json()["access_token"]
    refresh_new = relog_after_change.json()["refresh_token"]

    me = await async_client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_new}"})
    assert me.status_code == 200

    ref = await async_client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {refresh_new}"})
    assert ref.status_code == 200

    token2 = relog_after_change.json()["token"]
    back = await async_client.post(
        "/api/auth/change-password",
        json={"current_password": "CareOwnerTest44!", "new_password": OWNER_PASSWORD},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert back.status_code == 200
