"""Iteration 24 acceptance coverage for atomic care edits, timeline, receipts, welcomes, and billing.

Modules/features: /api/care-plans, /api/checkins, scheduler/receipts/notifications/welcomes, subscription_events.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

from database import get_pool
import scheduler
from services import receipts, notifications, welcomes, subscription_events
from services.button_intents import exact_button_intent
from services.schedule_source import load_schedule

pytest_plugins = ['tests.test_iteration20_service_suite']

from tests.test_iteration20_service_suite import (
    _create_parent,
    _create_reply,
    _login,
)


OWNER_EMAIL = "care-owner@example.com"
OWNER_PASSWORD = "CareOwnerTest42!"


@pytest_asyncio.fixture(autouse=True)
async def cleanup_iter24_rows(app_ready):
    yield
    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM child_content_requests WHERE wam_id LIKE 'iter24-%'")
        await conn.execute("DELETE FROM notification_attempts WHERE sid LIKE 'iter24-%'")
        await conn.execute("DELETE FROM reply_notifications WHERE detail LIKE 'iter24-%' OR sid LIKE 'iter24-%'")
        await conn.execute("DELETE FROM provider_receipts WHERE payload::text LIKE '%iter24-%'")
        await conn.execute("DELETE FROM billing_events WHERE event_id LIKE 'evt-iter24-%'")
        await conn.execute("DELETE FROM welcome_deliveries WHERE event_key LIKE 'child:%' OR sid LIKE 'iter24-w-%'")
        await conn.execute("DELETE FROM message_logs WHERE sid LIKE 'iter24-%'")
        await conn.execute("DELETE FROM care_send_claims WHERE sid LIKE 'iter24-%'")
        await conn.execute("DELETE FROM parents WHERE name LIKE 'TEST24_%'")


def _care_payload(phone: str, *, med_override: list[dict] | None = None, active: bool = True, recovery_mode: bool = False, recovery_until: str | None = None):
    medicines = med_override or [
        {
            "id": "stable-med-a",
            "name": "Metformin",
            "dose": "500mg",
            "shape": "round",
            "color": "white",
            "timing": "after_food",
            "reminder_times": ["09:00"],
            "notes": "after breakfast",
        },
        {
            "id": "stable-med-b",
            "name": "Amlodipine",
            "dose": "5mg",
            "shape": "oval",
            "color": "pink",
            "timing": "after_food",
            "reminder_times": ["09:00"],
            "notes": "after breakfast",
        },
    ]
    return {
        "parent": {
            "name": "TEST24_Parent",
            "preferred_name": "Amma",
            "relationship": "mother",
            "phone": phone,
            "language": "en",
            "timezone": "Asia/Kolkata",
            "city": "Hyderabad",
            "other_parent_name": "Nanna",
            "notes": "TEST24 parent",
            "medicine_list": medicines,
            "nicknames": ["Amma"],
            "stories": ["Story A"],
        },
        "schedule": {
            "parent_id": "new",
            "mode": "nitya",
            "messages": [
                {"time": "08:00", "category": "morning_wish", "type": "checkin", "weekdays": [0, 1, 2, 3, 4, 5, 6]},
                {"time": "13:00", "category": "lunch", "type": "checkin", "weekdays": [0, 1, 2, 3, 4, 5, 6]},
                {"time": "11:00", "category": "water", "type": "activity", "weekdays": [0, 1, 2, 3, 4, 5, 6]},
                {"time": "18:00", "category": "office_return", "type": "safety", "weekdays": [0]},
            ],
            "active": active,
            "recovery_mode": recovery_mode,
            "recovery_until": recovery_until,
            "reengagement_hours": 4,
        },
    }


@pytest.mark.asyncio
async def test_care_plan_atomic_commit_rollback_and_recovery_state(async_client, seeded_users):
    token, csrf = await _login(async_client, OWNER_EMAIL, OWNER_PASSWORD)
    auth = {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}

    create_payload = _care_payload("+14155558001")
    created = await async_client.post("/api/care-plans", json=create_payload, headers=auth)
    assert created.status_code == 200, created.text
    body = created.json()
    parent_id = body["parent"]["id"]
    schedule_id = body["schedule"]["id"]

    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow("SELECT * FROM parents WHERE id=$1::uuid", parent_id)
        schedule = await conn.fetchrow("SELECT * FROM schedules WHERE id=$1::uuid", schedule_id)
    assert parent is not None
    assert schedule is not None
    meds = [m for m in (schedule["messages"] or []) if m.get("category") == "medicine"]
    assert {m.get("medicine_id") for m in meds} == {"stable-med-a", "stable-med-b"}

    updated_payload = _care_payload("+14155558001")
    updated_payload["parent"]["medicine_list"][0]["color"] = "yellow"
    updated_payload["parent"]["medicine_list"][0]["notes"] = "with warm water"
    updated = await async_client.put(f"/api/care-plans/{parent_id}", json=updated_payload, headers=auth)
    assert updated.status_code == 200, updated.text

    async with get_pool().acquire() as conn:
        fresh_parent = await conn.fetchrow("SELECT * FROM parents WHERE id=$1::uuid", parent_id)
        _, expanded = await load_schedule(conn, dict(fresh_parent), now=datetime(2026, 2, 16, 3, 30, tzinfo=timezone.utc), day_filter=False)
    expanded_meds = [m for m in expanded if m["category"] == "medicine"]
    assert len(expanded_meds) == 2
    assert any("yellow" in m.get("medicine_name", "") and "with warm water" in m.get("medicine_name", "") for m in expanded_meds)

    async with get_pool().acquire() as conn:
        before_parent = await conn.fetchrow("SELECT phone FROM parents WHERE id=$1::uuid", parent_id)
        before_sched = await conn.fetchrow("SELECT messages FROM schedules WHERE parent_id=$1::uuid AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1", parent_id)

    invalid_meds = create_payload["parent"]["medicine_list"] + [{
        "id": "stable-med-c",
        "name": "Vitamin D",
        "dose": "1 tab",
        "shape": "round",
        "color": "white",
        "timing": "after_food",
        "reminder_times": ["20:00"],
        "notes": "after dinner",
    }]
    invalid_payload = _care_payload("123", med_override=invalid_meds)
    bad = await async_client.put(f"/api/care-plans/{parent_id}", json=invalid_payload, headers=auth)
    assert bad.status_code in (422, 400), bad.text

    async with get_pool().acquire() as conn:
        after_parent = await conn.fetchrow("SELECT phone FROM parents WHERE id=$1::uuid", parent_id)
        after_sched = await conn.fetchrow("SELECT messages FROM schedules WHERE parent_id=$1::uuid AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1", parent_id)
    assert after_parent["phone"] == before_parent["phone"]
    assert after_sched["messages"] == before_sched["messages"]

    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE schedules SET active=false,recovery_mode=true,recovery_until='2030-01-01' WHERE parent_id=$1::uuid",
            parent_id,
        )

    preserve_payload = _care_payload("+14155558001", active=False, recovery_mode=True, recovery_until="2030-01-01")
    preserve_payload["parent"]["city"] = "Secunderabad"
    preserved = await async_client.put(f"/api/care-plans/{parent_id}", json=preserve_payload, headers=auth)
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["schedule"]["active"] is False
    assert preserved.json()["schedule"]["recovery_mode"] is True


@pytest.mark.asyncio
async def test_checkins_selected_parent_local_date_and_late_reply_visibility(async_client, seeded_users):
    token, csrf = await _login(async_client, OWNER_EMAIL, OWNER_PASSWORD)
    auth = {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}
    owner = seeded_users["owner"]

    mother = await _create_parent(owner["id"], "TEST24_Mother", "+14155558002")
    father = await _create_parent(owner["id"], "TEST24_Father", "+14155558003")
    async with get_pool().acquire() as conn:
        await conn.execute("UPDATE parents SET relationship='father' WHERE id=$1", father["id"])

        log_id = await conn.fetchval(
            """
            INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,sid,created_at)
            VALUES($1,$2,'2026-02-11','medicine','reminder','sent','sid-test24-midnight','2026-02-10T18:40:00Z')
            RETURNING id
            """,
            owner["id"],
            mother["id"],
        )
        reply_id = await conn.fetchval(
            """
            INSERT INTO parent_replies(parent_id,user_id,from_phone,body,text,is_voice,context_id,association_source,message_log_id,created_at)
            VALUES($1,$2,$3,'late linked','late linked',false,'sid-test24-midnight','context',$4,'2026-02-11T19:00:00Z')
            RETURNING id
            """,
            mother["id"],
            owner["id"],
            mother["phone"],
            log_id,
        )
        await conn.execute(
            """
            INSERT INTO parent_replies(parent_id,user_id,from_phone,body,text,is_voice,created_at)
            VALUES($1,$2,$3,'general note','general note',false,'2026-02-11T19:10:00Z')
            """,
            mother["id"], owner["id"], mother["phone"],
        )
        await conn.execute(
            """
            INSERT INTO parent_replies(parent_id,user_id,from_phone,body,text,is_voice,created_at)
            VALUES($1,$2,$3,'father note','father note',true,'2026-02-11T19:15:00Z')
            """,
            father["id"], owner["id"], father["phone"],
        )

    checkins = await async_client.get(f"/api/checkins?parent_id={mother['id']}&date=2026-02-12", headers=auth)
    assert checkins.status_code == 200, checkins.text
    payload = checkins.json()
    assert len(payload["parents"]) == 1
    day = payload["parents"][0]["days"][0]
    assert day["day_key"] == "2026-02-12"
    assert any(r.get("body") == "late linked" for r in day.get("late_replies", []))
    assert any(r.get("body") == "general note" for r in day.get("general_replies", []))

    reply = await async_client.get(f"/api/replies/{reply_id}", headers=auth)
    assert reply.status_code == 200, reply.text
    reply_body = reply.json()
    assert reply_body["id"] == str(reply_id)
    assert reply_body["local_date"] == "2026-02-11"
    assert "T" in reply_body["created_at"]


@pytest.mark.asyncio
async def test_scheduler_safety_weekday_rules_and_medicine_id_no_dup(async_client, seeded_users, monkeypatch):
    owner = seeded_users["owner"]
    parent = await _create_parent(owner["id"], "TEST24_Scheduler", "+14155558004")
    now_local = datetime.now(ZoneInfo('Asia/Kolkata')).replace(hour=10, minute=0, second=0, microsecond=0)
    selected_weekday = now_local.weekday()
    slot = now_local.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE parents SET medicine_list=$2::jsonb WHERE id=$1
            """,
            parent["id"],
            json.dumps([{
                "id": "stable-med-1",
                "name": "Losartan",
                "dose": "50mg",
                "shape": "round",
                "color": "white",
                "timing": "after_food",
                "reminder_times": [slot],
                "notes": "after meal",
            }]),
        )
        await conn.execute(
            """
            INSERT INTO schedules(parent_id,user_id,mode,messages,active,recovery_mode,reengagement_hours,created_at)
            VALUES($1,$2,'nitya',$3::jsonb,true,false,4,now()-interval '1 day')
            """,
            parent["id"],
            owner["id"],
            json.dumps([
                {"time": slot, "category": "office_return", "type": "safety", "weekdays": [selected_weekday]},
                {"time": slot, "category": "water", "type": "activity", "weekdays": [0, 1, 2, 3, 4, 5, 6]},
                {"time": slot, "category": "medicine", "type": "reminder", "medicine_id": "stable-med-1", "source": "medicine_sync", "weekdays": [0, 1, 2, 3, 4, 5, 6]},
            ]),
        )

    sent_categories = []

    async def fake_send(parent_doc, category, day, variants, medicine_name=""):
        sent_categories.append(category)
        return {"status": "sent", "sid": f"iter24-{len(sent_categories)}", "detail": "iter24-send"}

    monkeypatch.setattr(scheduler, "send_dynamic_checkin", fake_send)

    await scheduler._deliver_parent(dict(parent), now_local)
    await scheduler._deliver_parent(dict(parent), now_local + timedelta(seconds=130))
    await scheduler._deliver_parent(dict(parent), now_local + timedelta(seconds=260))

    assert sent_categories.count("medicine") == 1
    assert "water" in sent_categories
    assert "office_return" in sent_categories

    assert exact_button_intent({"category": "office_return"}, "done:office_return", "On the way") == "on_way:office_return"
    assert exact_button_intent({"category": "office_return"}, "done:office_return", "Shopping done") == "activity_done:office_return"


@pytest.mark.asyncio
async def test_receipts_ingest_unknown_then_drain_and_non_regression(seeded_users):
    owner = seeded_users["owner"]
    parent = await _create_parent(owner["id"], "TEST24_Receipts", "+14155558005")

    await receipts.ingest({"id": "iter24-unknown-sid", "status": "delivered"})
    async with get_pool().acquire() as conn:
        unknown_processed = await conn.fetchval("SELECT processed_at FROM provider_receipts WHERE payload::text LIKE '%iter24-unknown-sid%'")
    assert unknown_processed is None

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,sid,created_at)
            VALUES($1,$2,'2026-02-16','medicine','reminder','sent','iter24-unknown-sid',now())
            """,
            owner["id"], parent["id"],
        )
    await receipts.drain()
    async with get_pool().acquire() as conn:
        delivered = await conn.fetchval("SELECT delivery_status FROM message_logs WHERE sid='iter24-unknown-sid'")
        processed = await conn.fetchval("SELECT processed_at IS NOT NULL FROM provider_receipts WHERE payload::text LIKE '%iter24-unknown-sid%'")
    assert delivered == "delivered"
    assert processed is True

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO message_logs(user_id,parent_id,day_key,category,msg_type,status,sid,delivery_status,created_at)
            VALUES($1,$2,'2026-02-16','medicine','reminder','sent','iter24-never-regress','delivered',now())
            """,
            owner["id"], parent["id"],
        )
    await receipts.ingest({"id": "iter24-never-regress", "status": "failed", "errors": [{"code": 131047, "title": "template closed"}]})
    async with get_pool().acquire() as conn:
        still_delivered = await conn.fetchval("SELECT delivery_status FROM message_logs WHERE sid='iter24-never-regress'")
    assert still_delivered == "delivered"


@pytest.mark.asyncio
async def test_welcomes_concurrency_and_consent_gate(seeded_users, monkeypatch):
    owner = seeded_users["owner"]
    owner_id = owner["id"]
    key = f"child:{owner_id}:email-verified"

    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM welcome_deliveries WHERE event_key=$1", key)
        await conn.execute("DELETE FROM consent_logs WHERE user_id=$1 AND consent_type='child'", owner_id)

    sent_templates = []

    async def fake_send(phone, template, lang, params, category):
        sent_templates.append(template)
        await asyncio.sleep(0.01)
        return {"status": "sent", "sid": f"iter24-w-{len(sent_templates)}"}

    monkeypatch.setattr(welcomes, "whatsapp_enabled", lambda: True)
    monkeypatch.setattr(welcomes, "_send_content_template_with_retry", fake_send)

    await welcomes.queue_child(owner)
    held = await welcomes.deliver(key)
    assert held["status"] == "awaiting_consent"

    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO consent_logs(user_id,consent_type,agreed,text) VALUES($1,'child',true,'iter24')",
            owner_id,
        )
        await conn.execute("UPDATE welcome_deliveries SET status='pending',attempts=0,next_attempt_at=now() WHERE event_key=$1", key)

    await asyncio.gather(welcomes.deliver(key), welcomes.deliver(key))
    assert sent_templates.count("ayana_child_welcome_en") == 1


@pytest.mark.asyncio
async def test_notifications_audio_failure_does_not_downgrade_main_status(seeded_users, monkeypatch):
    owner = seeded_users["owner"]
    parent = await _create_parent(owner["id"], "TEST24_Audio", "+14155558006")
    reply = await _create_reply(owner["id"], parent["id"], "iter24-voice", is_voice=True, media_id="iter24-media")

    async with get_pool().acquire() as conn:
        notif_id = await conn.fetchval(
            """
            INSERT INTO reply_notifications(reply_id,recipient_kind,recipient_id,status,to_phone,audio_status)
            VALUES($1,'user',$2,'accepted',$3,'pending') RETURNING id
            """,
            reply["id"], owner["id"], owner["phone"],
        )
        await conn.execute(
            "INSERT INTO recipient_sessions(phone,last_inbound_at) VALUES($1,$2) ON CONFLICT(phone) DO UPDATE SET last_inbound_at=excluded.last_inbound_at",
            owner["phone"], datetime.now(timezone.utc),
        )
        row = await conn.fetchrow("SELECT * FROM reply_notifications WHERE id=$1", notif_id)

    async def fake_send_audio(phone, reply_obj):
        return {"status": "failed", "detail": "iter24-audio-fail"}

    monkeypatch.setattr(notifications, "send_audio", fake_send_audio)
    await notifications.deliver_audio(row)

    async with get_pool().acquire() as conn:
        status = await conn.fetchrow("SELECT status,audio_status FROM reply_notifications WHERE id=$1", notif_id)
    assert status["status"] == "accepted"
    assert status["audio_status"] in ("retry", "failed")


@pytest.mark.asyncio
async def test_subscription_events_idempotency_and_terminal_stale_guard(seeded_users):
    owner = seeded_users["owner"]
    start = datetime(2026, 2, 1, tzinfo=timezone.utc)
    end = datetime(2026, 3, 1, tzinfo=timezone.utc)

    async with get_pool().acquire() as conn:
        plan_id = await conn.fetchval(
            """
            INSERT INTO billing_plans(plan,billing,currency,amount,gateway_plan_id)
            VALUES('raksha','month','INR',99900,'plan_iter24')
            ON CONFLICT(plan,billing,currency) DO UPDATE SET amount=excluded.amount
            RETURNING id
            """,
        )
        await conn.execute(
            """
            INSERT INTO billing_subscriptions(user_id,billing_plan_id,gateway_subscription_id,plan,billing,currency,amount,status,current_period_start,current_period_end,provider_event_at)
            VALUES($1,$2,'sub_iter24','raksha','month','INR',99900,'active',$3,$4,$4)
            ON CONFLICT(gateway_subscription_id) DO UPDATE SET status='active',current_period_start=$3,current_period_end=$4,provider_event_at=$4
            """,
            owner["id"], plan_id, start, end,
        )

    charged = {
        "event": "subscription.charged",
        "created_at": int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp()),
        "payload": {
            "subscription": {"entity": {"id": "sub_iter24", "current_start": int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp()), "current_end": int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp())}},
            "payment": {"entity": {"status": "captured", "subscription_id": "sub_iter24"}},
            "count": 1,
        },
    }
    first = await subscription_events.ingest(charged, "evt-iter24-1")
    second = await subscription_events.ingest(charged, "evt-iter24-1")
    assert first["ok"] is True
    assert second.get("duplicate") is True

    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE billing_subscriptions SET status='cancelled',provider_event_at=$1 WHERE gateway_subscription_id='sub_iter24'",
            datetime(2026, 4, 2, tzinfo=timezone.utc),
        )

    stale = {
        "event": "subscription.charged",
        "created_at": int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()),
        "payload": {
            "subscription": {"entity": {"id": "sub_iter24", "current_start": int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()), "current_end": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())}},
            "payment": {"entity": {"status": "captured", "subscription_id": "sub_iter24"}},
        },
    }
    ignored = await subscription_events.ingest(stale, "evt-iter24-2")
    assert ignored.get("ignored") is True

    async with get_pool().acquire() as conn:
        status = await conn.fetchval("SELECT status FROM billing_subscriptions WHERE gateway_subscription_id='sub_iter24'")
    assert status == "cancelled"
