"""Iteration 22 readonly diagnostics.

These tests strengthen evidence quality (real function paths, deterministic clocks,
and explicit branch assertions) without modifying application implementation.
"""

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError


# Minimal import stubs so these diagnostics can run without live infra deps.
if "asyncpg" not in sys.modules:
    asyncpg_stub = types.ModuleType("asyncpg")

    class _UniqueViolationError(Exception):
        pass

    class _Connection:
        pass

    class _PoolType:
        pass

    async def _create_pool(*_args, **_kwargs):
        return _PoolType()

    asyncpg_stub.UniqueViolationError = _UniqueViolationError
    asyncpg_stub.Connection = _Connection
    asyncpg_stub.Pool = _PoolType
    asyncpg_stub.create_pool = _create_pool
    sys.modules["asyncpg"] = asyncpg_stub

if "redis" not in sys.modules:
    redis_stub = types.ModuleType("redis")

    class _RedisClient:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

        def set(self, *_args, **_kwargs):
            return True

    redis_stub.Redis = _RedisClient
    sys.modules["redis"] = redis_stub
    sys.modules["redis.asyncio"] = redis_stub

if "apscheduler" not in sys.modules:
    aps = types.ModuleType("apscheduler")
    aps_s = types.ModuleType("apscheduler.schedulers")
    aps_a = types.ModuleType("apscheduler.schedulers.asyncio")

    class _AsyncIOScheduler:
        def __init__(self, *args, **kwargs):
            self.running = False

        def add_job(self, *args, **kwargs):
            return None

        def get_jobs(self):
            return []

        def start(self):
            self.running = True

        def shutdown(self, wait=False):
            self.running = False

    aps_a.AsyncIOScheduler = _AsyncIOScheduler
    sys.modules["apscheduler"] = aps
    sys.modules["apscheduler.schedulers"] = aps_s
    sys.modules["apscheduler.schedulers.asyncio"] = aps_a

if "razorpay" not in sys.modules:
    razorpay_stub = types.ModuleType("razorpay")

    class _Client:
        def __init__(self, *_args, **_kwargs):
            self.order = types.SimpleNamespace(create=lambda *_a, **_k: {})
            self.payment = types.SimpleNamespace(fetch=lambda *_a, **_k: {})
            self.utility = types.SimpleNamespace(
                verify_payment_signature=lambda *_a, **_k: True,
                verify_subscription_payment_signature=lambda *_a, **_k: True,
            )
            self.plan = types.SimpleNamespace(all=lambda *_a, **_k: {"items": []}, create=lambda *_a, **_k: {"id": "plan_1"})
            self.subscription = types.SimpleNamespace(create=lambda *_a, **_k: {"id": "sub_1"}, fetch=lambda *_a, **_k: {})

    razorpay_stub.Client = _Client
    sys.modules["razorpay"] = razorpay_stub


def _run(coro):
    return asyncio.run(coro)


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Conn:
    def __init__(self, fetchrow=None, fetchval=None, fetch=None, execute=None):
        self._fetchrow = fetchrow or (lambda *a, **k: None)
        self._fetchval = fetchval or (lambda *a, **k: None)
        self._fetch = fetch or (lambda *a, **k: [])
        self._execute = execute or (lambda *a, **k: "OK")
        self.queries = []

    async def fetchrow(self, *args, **kwargs):
        self.queries.append(("fetchrow", args[0] if args else ""))
        out = self._fetchrow(*args, **kwargs)
        return await out if inspect.isawaitable(out) else out

    async def fetchval(self, *args, **kwargs):
        self.queries.append(("fetchval", args[0] if args else ""))
        out = self._fetchval(*args, **kwargs)
        return await out if inspect.isawaitable(out) else out

    async def fetch(self, *args, **kwargs):
        self.queries.append(("fetch", args[0] if args else ""))
        out = self._fetch(*args, **kwargs)
        return await out if inspect.isawaitable(out) else out

    async def execute(self, *args, **kwargs):
        self.queries.append(("execute", args[0] if args else ""))
        out = self._execute(*args, **kwargs)
        return await out if inspect.isawaitable(out) else out

    def transaction(self):
        return _Tx()


class _Pool:
    def __init__(self, conn=None, fetchrow=None, execute=None, fetch=None, fetchval=None):
        self.conn = conn or _Conn()
        self._fetchrow = fetchrow
        self._execute = execute
        self._fetch = fetch
        self._fetchval = fetchval

    def acquire(self):
        return _Acquire(self.conn)

    async def fetchrow(self, *args, **kwargs):
        if self._fetchrow:
            return await self._fetchrow(*args, **kwargs)
        return await self.conn.fetchrow(*args, **kwargs)

    async def fetchval(self, *args, **kwargs):
        if self._fetchval:
            return await self._fetchval(*args, **kwargs)
        return await self.conn.fetchval(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        if self._execute:
            return await self._execute(*args, **kwargs)
        return await self.conn.execute(*args, **kwargs)

    async def fetch(self, *args, **kwargs):
        if self._fetch:
            return await self._fetch(*args, **kwargs)
        return await self.conn.fetch(*args, **kwargs)


def test_unknown_inbound_records_session_and_real_record_reply_stays_unowned(monkeypatch):
    from routes import webhook

    rec = AsyncMock()
    monkeypatch.setattr(webhook.notifications, "record_recipient_inbound", rec)

    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"id": "wam-x", "from": "+14155551111", "timestamp": "1739348400", "type": "text", "text": {"body": "hello"}}]}}]}]
    }

    pool = _Pool(conn=_Conn(fetchrow=lambda *_a, **_k: None))
    monkeypatch.setattr(webhook, "get_pool", lambda: pool)
    create_task_calls = []
    monkeypatch.setattr(webhook.asyncio, "create_task", lambda c: create_task_calls.append(c))

    _run(webhook._process_meta_payload(payload))
    assert rec.await_count == 1

    out = _run(webhook._record_reply(from_number="+14155551111", body_text="hello", wam_id="wam-y"))
    assert out["ignored"] is True
    assert out["parent_id"] is None
    assert create_task_calls == []
    assert not any("needs_inbound_click=true" in q for _, q in pool.conn.queries)


def test_scheduler_claim_check_reached_and_blocks_resend_after_failed_receipt_only_updates_logs(monkeypatch):
    import scheduler
    from routes import webhook

    fixed_now = datetime(2026, 2, 12, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
    local_fixed = datetime(2026, 2, 12, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    persist_conn = _Conn(fetchrow=lambda *_: None)
    persist_pool = _Pool(conn=persist_conn)
    monkeypatch.setattr(webhook, "get_pool", lambda: persist_pool)
    monkeypatch.setattr(webhook.notifications, "persist_receipt", AsyncMock())
    _run(webhook._persist_delivery_status({"id": "sid-1", "status": "failed", "errors": [{"code": 131047, "title": "window closed"}]}))
    assert any("update message_logs" in q.lower() and "delivery_status = 'failed'" in q.lower() for _, q in persist_conn.queries)

    parent = {
        "id": "p1",
        "user_id": "u1",
        "timezone": "Asia/Kolkata",
        "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
    }

    claim_queries = []

    async def _fetchval(query, *_args):
        if "pg_try_advisory_xact_lock" in query:
            return True
        if "SELECT max(created_at) FROM message_logs" in query:
            return None
        if "SELECT plan FROM payment_state" in query:
            return "nitya"
        if "status='sent'" in query:
            return 0
        if "event_key IS NULL" in query:
            return None
        if "msg_type=$3" in query:
            return 0
        if "INSERT INTO care_send_claims" in query:
            claim_queries.append(query)
            return None
        return None

    async def _fetchrow(query, *_args):
        if "SELECT * FROM activation_state" in query:
            return {"whatsapp_activated": True, "activated_at": datetime(2026, 2, 2, tzinfo=timezone.utc)}
        if "SELECT * FROM care_send_claims" in query:
            claim_queries.append(query)
            return {"event_key": "k1", "status": "sent"}
        if "count(*) AS n" in query:
            return {"n": 0, "last": None}
        return None

    sent = AsyncMock()
    monkeypatch.setattr(scheduler, "send_dynamic_checkin", sent)
    monkeypatch.setattr(scheduler, "local_now", lambda *_: local_fixed)
    monkeypatch.setattr(scheduler, "eligible", lambda *_: True)
    monkeypatch.setattr(
        scheduler,
        "load_schedule",
        AsyncMock(return_value=({}, [{"category": "medicine", "type": "reminder", "time": "10:00"}])),
    )
    monkeypatch.setattr(scheduler, "get_pool", lambda: _Pool(conn=_Conn(fetchrow=_fetchrow, fetchval=_fetchval)))
    _run(scheduler._deliver_parent(parent, fixed_now))

    assert sent.await_count == 0
    assert any("SELECT * FROM care_send_claims" in q for q in claim_queries)


@pytest.mark.parametrize("code", [131047, 131016])
def test_failed_receipt_then_drain_does_not_retry_failed_status(monkeypatch, code):
    from services import notifications

    state = {
        "notification": {
            "id": "n1",
            "sid": "sid-x",
            "status": "accepted",
            "email_status": "sent",
            "reply_id": "r1",
            "recipient_kind": "user",
            "recipient_id": "u1",
        },
        "recipient_session_deleted": False,
    }

    async def _fetchrow(query, *args):
        if "SELECT * FROM reply_notifications WHERE sid=$1 FOR UPDATE" in query:
            return state["notification"]
        return None

    async def _execute(query, *args):
        if "UPDATE reply_notifications SET status=$2,error_code=$3" in query:
            state["notification"]["status"] = args[1]
            state["notification"]["error_code"] = args[2]
        if "DELETE FROM recipient_sessions" in query:
            state["recipient_session_deleted"] = True
        return "OK"

    async def _fetch(query, *_args):
        assert "status IN ('pending','retry','awaiting_template','disabled')" in query
        return []

    pool = _Pool(conn=_Conn(fetchrow=_fetchrow, execute=_execute, fetch=_fetch))
    monkeypatch.setattr(notifications, "get_pool", lambda: pool)
    monkeypatch.setattr(notifications, "deliver", AsyncMock())

    _run(notifications.persist_receipt({"id": "sid-x", "status": "failed", "errors": [{"code": code, "title": "failed"}]}))
    assert state["notification"]["status"] == "failed"
    assert state["notification"]["error_code"] == code
    assert state["recipient_session_deleted"] is False

    _run(notifications.drain_notifications())
    assert notifications.deliver.await_count == 0


def test_audio_without_resolved_url_runs_real_record_path_as_non_voice(monkeypatch):
    from routes import webhook

    insert_snapshot = {}
    parent = {
        "id": "00000000-0000-0000-0000-000000000001",
        "user_id": "u-a",
        "language": "en",
        "auto_activity_detection": False,
    }

    async def _fetchrow(query, *args):
        q = query.lower()
        if "select * from message_logs" in q and "order by created_at" in q:
            return {"msg_type": "reminder"}
        if "select * from users where id = $1" in q:
            return {"preferences": {}}
        if "insert into parent_replies" in q:
            insert_snapshot["body_text"] = args[3]
            insert_snapshot["is_voice"] = args[7]
            insert_snapshot["media_url"] = args[9]
            return {
                "id": "reply-1",
                "parent_id": parent["id"],
                "user_id": parent["user_id"],
                "from_phone": "+14155552222",
                "intent": args[5],
                "body": args[3],
                "is_voice": args[7],
                "duplicate": False,
                "created_at": datetime.now(timezone.utc),
            }
        return None

    pool = _Pool(conn=_Conn(fetchrow=_fetchrow, execute=lambda *_: "OK"))
    monkeypatch.setattr(webhook, "get_pool", lambda: pool)
    monkeypatch.setattr(webhook.notifications, "enqueue_reply", AsyncMock())
    monkeypatch.setattr(webhook.notifications, "drain_notifications", AsyncMock())
    monkeypatch.setattr(webhook, "archive_audio", AsyncMock())
    monkeypatch.setattr(webhook, "refresh_session", AsyncMock())
    monkeypatch.setattr(webhook, "detect_emergency", lambda *_: [])
    stt = AsyncMock(return_value={"transcript": "x", "confidence": 0.95})
    monkeypatch.setattr(webhook, "transcribe_voice_note_detailed", stt)

    out = _run(
        webhook._record_reply(
            from_number="+14155552222",
            body_text="",
            parent=parent,
            media_url=None,
            media_content_type="audio/ogg",
            raw_payload={"timestamp": "1739348400", "audio": {"id": "m1"}},
            wam_id="wam-a-1",
        )
    )
    assert out["is_voice"] is False
    assert insert_snapshot["is_voice"] is False
    assert insert_snapshot["body_text"] == ""
    assert insert_snapshot["media_url"] is None
    assert stt.await_count == 0


def test_button_side_effect_retry_second_apply_explicitly_skipped(monkeypatch):
    from routes import webhook

    monkeypatch.setattr(webhook.notifications, "record_recipient_inbound", AsyncMock())

    calls = {"record": 0}

    async def _record(**_kwargs):
        calls["record"] += 1
        if calls["record"] == 1:
            return {"parent_id": "p", "duplicate": False}
        return {"parent_id": "p", "duplicate": True}

    first_apply = AsyncMock(side_effect=RuntimeError("first side-effect fails"))
    second_apply = AsyncMock()

    monkeypatch.setattr(webhook, "_record_reply", _record)
    monkeypatch.setattr(webhook, "_apply_button_tap_effects", first_apply)

    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"id": "wam-btn", "from": "+14155553333", "timestamp": "1739348400", "type": "button", "button": {"payload": "done:medicine", "text": "Done"}}]}}]}]
    }

    with pytest.raises(RuntimeError, match="first side-effect fails"):
        _run(webhook._process_meta_payload(payload))
    assert first_apply.await_count == 1

    monkeypatch.setattr(webhook, "_apply_button_tap_effects", second_apply)
    _run(webhook._process_meta_payload(payload))
    assert second_apply.await_count == 0


def test_watch_parent_after_window_end_2201_ist_suppresses_warning(monkeypatch):
    import escalation

    parent = {
        "id": "p2",
        "user_id": "u2",
        "timezone": "Asia/Kolkata",
        "activity_window_start": "06:00",
        "activity_window_end": "21:00",
    }
    local_after_end = datetime(2026, 2, 12, 22, 1, tzinfo=ZoneInfo("Asia/Kolkata"))

    async def _fetchval(query, *_):
        if "pg_try_advisory_xact_lock" in query:
            return True
        if "SELECT whatsapp_activated" in query:
            return True
        return None

    monkeypatch.setattr(escalation, "local_now", lambda *_: local_after_end)
    monkeypatch.setattr(escalation, "load_schedule", AsyncMock(return_value=({}, [])))
    monkeypatch.setattr(escalation, "get_pool", lambda: _Pool(conn=_Conn(fetchval=_fetchval)))
    warn = AsyncMock()
    monkeypatch.setattr(escalation, "_notify_family_warning", warn)
    _run(escalation._watch_parent(parent))
    assert warn.await_count == 0


def test_watch_parent_inside_extended_window_2205_ist_hits_warning_path(monkeypatch):
    import escalation

    parent = {
        "id": "p3",
        "user_id": "u3",
        "timezone": "Asia/Kolkata",
        "activity_window_start": "06:00",
        "activity_window_end": "23:00",
        "phone": "+14155554444",
        "language": "en",
        "name": "Amma",
    }
    now_local = datetime(2026, 2, 12, 22, 5, tzinfo=ZoneInfo("Asia/Kolkata"))
    morning_delivery = now_local.replace(hour=9, minute=0)

    async def _fetchval(query, *_args):
        if "pg_try_advisory_xact_lock" in query:
            return True
        if "SELECT whatsapp_activated" in query:
            return True
        if "SELECT EXISTS(SELECT 1 FROM parent_replies" in query:
            return False
        if "SELECT max(created_at) FROM message_logs" in query:
            return now_local - timedelta(hours=5)
        if "SELECT count(*) FROM message_logs" in query:
            return 1
        return None

    async def _fetch(query, *_args):
        if "FROM message_logs" in query and "delivery_status IN ('delivered','read')" in query:
            return [{"created_at": morning_delivery, "delivered_at": morning_delivery - timedelta(minutes=1)}]
        return []

    async def _fetchrow(query, *_args):
        if "SELECT * FROM care_watch" in query:
            return {"first_warn_sent": False, "main_warn_sent": False}
        return None

    monkeypatch.setattr(escalation, "local_now", lambda *_: now_local)
    monkeypatch.setattr(escalation, "load_schedule", AsyncMock(return_value=({}, [])))
    monkeypatch.setattr(escalation, "_send_claimed", AsyncMock(return_value={"status": "sent"}))
    warn = AsyncMock(return_value=True)
    monkeypatch.setattr(escalation, "_notify_family_warning", warn)
    monkeypatch.setattr(
        escalation,
        "get_pool",
        lambda: _Pool(conn=_Conn(fetchval=_fetchval, fetch=_fetch, fetchrow=_fetchrow, execute=lambda *_: "OK")),
    )

    _run(escalation._watch_parent(parent))
    assert warn.await_count == 1


def test_welcome_send_once_uncertain_resends_but_accepted_does_not(monkeypatch):
    from services import welcomes

    async def _scenario(existing_status):
        send = AsyncMock(return_value={"status": "sent", "sid": "sid-1"})

        async def _fetchrow(query, *_args):
            if "SELECT * FROM welcome_deliveries" in query:
                return {"status": existing_status} if existing_status else None
            return None

        pool = _Pool(conn=_Conn(fetchrow=_fetchrow, execute=lambda *_: "OK"))
        monkeypatch.setattr(welcomes, "get_pool", lambda: pool)
        monkeypatch.setattr(welcomes, "whatsapp_enabled", lambda: True)
        monkeypatch.setattr(welcomes, "_send_content_template_with_retry", send)
        await welcomes.send_once("evt-1", "+14155555555", "Kid", "Mom", "en")
        return send.await_count

    assert _run(_scenario("uncertain")) == 1
    assert _run(_scenario("accepted")) == 0


def test_notification_transport_send_update_open_text_closed_template_and_plus_stripped(monkeypatch):
    from services import notification_transport

    posted = []

    class _Resp:
        is_success = True

        @staticmethod
        def json():
            return {"messages": [{"id": "sid-ntf"}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, _url, headers=None, json=None):
            posted.append(json)
            return _Resp()

    monkeypatch.setattr(notification_transport, "whatsapp_enabled", lambda: True)
    monkeypatch.setattr(notification_transport, "_creds", lambda: ("token", "phone-id"))
    monkeypatch.setattr(notification_transport, "_messages_url", lambda _p: "https://meta.local/messages")
    monkeypatch.setattr(notification_transport.httpx, "AsyncClient", _Client)
    monkeypatch.setenv("FRONTEND_URL", "https://frontend.test")
    monkeypatch.setenv("WA_CHILD_REPLY_TEMPLATES_ENABLED", "true")

    reply = {
        "id": "r1",
        "parent_name": "Amma",
        "prompt": "medicine",
        "display_time": "12 Feb, 09:00 PM IST",
        "body": "Taken",
        "is_voice": False,
    }

    _run(notification_transport.send_update("+14155556666", reply, True, "en"))
    _run(notification_transport.send_update("+14155556666", reply, False, "en"))

    assert posted[0]["type"] == "text"
    assert posted[0]["to"] == "14155556666"
    assert posted[1]["type"] == "template"
    assert posted[1]["template"]["name"] == "ayana_parent_reply_en"


def test_medicine_sync_and_schedule_loader_expand_four_sends_but_scheduler_quota_skips_med_c(monkeypatch):
    import scheduler
    from medicine_sync import sync_medicine_reminders
    from services import schedule_source

    parent = {
        "id": "p-med",
        "user_id": "u-med",
        "timezone": "Asia/Kolkata",
        "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
        "medicine_list": [
            {"name": "Med A", "reminder_time": "09:00"},
            {"name": "Med B", "reminder_time": "09:00"},
            {"name": "Med C", "reminder_time": "20:00"},
        ],
    }
    existing = [{"time": "12:00", "category": "water", "type": "reminder", "source": None}]
    merged = sync_medicine_reminders(parent["medicine_list"], existing, "nitya")
    assert merged["synced_times"] == ["09:00", "20:00"]
    assert merged["dropped"] == []

    legacy = {"active": True, "deleted_at": None, "messages": merged["messages"]}
    conn = _Conn(fetchrow=lambda *_: legacy)
    _, items = _run(schedule_source.load_schedule(conn, parent))
    meds = [i for i in items if i["category"] == "medicine"]
    assert len(items) == 4
    assert sorted((m.get("medicine_name") for m in meds)) == ["Med A", "Med B", "Med C"]

    fixed_now = datetime(2026, 2, 12, 14, 30, tzinfo=timezone.utc)  # 20:00 IST
    local_fixed = datetime(2026, 2, 12, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parent_sched = {k: v for k, v in parent.items() if k != "medicine_list"}

    quota_queries = []

    async def _fetchval(query, *_args):
        if "pg_try_advisory_xact_lock" in query:
            return True
        if "SELECT max(created_at) FROM message_logs" in query:
            return None
        if "SELECT plan FROM payment_state" in query:
            return "nitya"
        if "status='sent'" in query and "msg_type=$3" not in query:
            return 0
        if "event_key IS NULL" in query:
            return None
        if "msg_type=$3" in query:
            quota_queries.append(query)
            return 3
        return None

    async def _fetchrow(query, *_args):
        if "SELECT * FROM activation_state" in query:
            return {"whatsapp_activated": True, "activated_at": datetime(2026, 2, 2, tzinfo=timezone.utc)}
        if "SELECT * FROM care_send_claims" in query:
            return None
        if "count(*) AS n" in query:
            return {"n": 0, "last": None}
        return None

    send = AsyncMock(return_value={"status": "sent", "sid": "sid-1"})
    monkeypatch.setattr(scheduler, "local_now", lambda *_: local_fixed)
    monkeypatch.setattr(scheduler, "eligible", lambda *_: True)
    monkeypatch.setattr(scheduler, "load_schedule", AsyncMock(return_value=({}, items)))
    monkeypatch.setattr(scheduler, "send_dynamic_checkin", send)
    monkeypatch.setattr(scheduler, "get_pool", lambda: _Pool(conn=_Conn(fetchrow=_fetchrow, fetchval=_fetchval, execute=lambda *_: "OK")))

    _run(scheduler._deliver_parent(parent_sched, fixed_now))
    assert send.await_count == 0
    assert len(quota_queries) >= 1


def test_button_effect_uses_latest_category_row_even_when_reply_has_older_context_id(monkeypatch):
    from routes import webhook

    updates = []

    async def _fetchrow(query, *args):
        q = query.lower()
        if "select language, timezone from parents" in q:
            return {"language": "en", "timezone": "Asia/Kolkata"}
        if "select id from message_logs" in q:
            return {"id": "latest-log"}
        return None

    async def _execute(query, *args):
        updates.append((query, args))
        return "OK"

    monkeypatch.setattr(webhook, "get_pool", lambda: _Pool(conn=_Conn(fetchrow=_fetchrow, execute=_execute)))
    monkeypatch.setattr(webhook, "send_whatsapp", lambda *_: {"status": "sent"})

    reply = {
        "intent": "done:medicine",
        "parent_id": "parent-1",
        "from_phone": "+14155557777",
        "message_log_id": "older-log-id",
    }
    _run(webhook._apply_button_tap_effects(reply))
    assert any("update message_logs set reply_status" in q.lower() and a[1] == "latest-log" for q, a in updates)


def test_recovery_mode_extra_over_quota_raises_validationerror_with_quota_message():
    from models import ScheduleInput

    msgs = [{"time": f"{i:02d}:00", "category": "medicine"} for i in range(1, 9)]
    with pytest.raises(ValidationError) as ex:
        ScheduleInput(parent_id="p", mode="raksha", messages=msgs, recovery_mode=True)
    text = str(ex.value)
    assert "allows up to" in text
    assert "reminders" in text


def test_scheduler_recovery_mode_still_skips_when_reminders_already_six(monkeypatch):
    import scheduler

    parent = {
        "id": "p-r",
        "user_id": "u-r",
        "timezone": "Asia/Kolkata",
        "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
    }
    fixed_now = datetime(2026, 2, 12, 14, 30, tzinfo=timezone.utc)
    local_fixed = datetime(2026, 2, 12, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    async def _fetchval(query, *_args):
        if "pg_try_advisory_xact_lock" in query:
            return True
        if "SELECT max(created_at) FROM message_logs" in query:
            return None
        if "SELECT plan FROM payment_state" in query:
            return "raksha"
        if "status='sent'" in query and "msg_type=$3" not in query:
            return 0
        if "event_key IS NULL" in query:
            return None
        if "msg_type=$3" in query:
            return 6
        return None

    async def _fetchrow(query, *_args):
        if "SELECT * FROM activation_state" in query:
            return {"whatsapp_activated": True, "activated_at": datetime(2026, 2, 2, tzinfo=timezone.utc)}
        if "SELECT * FROM care_send_claims" in query:
            return None
        if "count(*) AS n" in query:
            return {"n": 0, "last": None}
        return None

    send = AsyncMock()
    monkeypatch.setattr(scheduler, "send_dynamic_checkin", send)
    monkeypatch.setattr(scheduler, "eligible", lambda *_: True)
    monkeypatch.setattr(scheduler, "local_now", lambda *_: local_fixed)
    monkeypatch.setattr(
        scheduler,
        "load_schedule",
        AsyncMock(return_value=({"recovery_mode": True}, [{"category": "medicine", "type": "reminder", "time": "20:00", "is_recovery": True}])),
    )
    monkeypatch.setattr(scheduler, "get_pool", lambda: _Pool(conn=_Conn(fetchrow=_fetchrow, fetchval=_fetchval, execute=lambda *_: "OK")))

    _run(scheduler._deliver_parent(parent, fixed_now))
    assert send.await_count == 0


def test_billing_subscription_charged_replay_uses_receipt_time_and_overwrites_period(monkeypatch):
    from routes import billing

    class Req:
        def __init__(self, body, headers):
            self._body = body
            self.headers = headers

        async def body(self):
            return self._body

    sub = {"id": "sub-local-1", "user_id": "u1", "plan": "nitya", "billing": "month", "status": "active"}
    updates = []

    async def _fetchrow(query, *args):
        if "SELECT * FROM billing_subscriptions" in query:
            return sub
        return None

    async def _execute(query, *args):
        if "UPDATE billing_subscriptions" in query and "current_period_start" in query:
            updates.append((args[1], args[2]))
        return "OK"

    pool = _Pool(conn=_Conn(fetchrow=_fetchrow, execute=_execute), fetchrow=_fetchrow, execute=_execute)
    monkeypatch.setattr(billing, "get_pool", lambda: pool)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "secret")

    event = {
        "event": "subscription.charged",
        "payload": {
            "subscription": {"entity": {"id": "sub_gw_1"}},
            "payment": {"entity": {"id": "pay_1"}},
        },
    }
    body = json.dumps(event).encode()
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    class _DT1(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)

    class _DT2(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(billing, "datetime", _DT1)
    _run(billing.webhook(Req(body, {"X-Razorpay-Signature": sig})))
    monkeypatch.setattr(billing, "datetime", _DT2)
    _run(billing.webhook(Req(body, {"X-Razorpay-Signature": sig})))

    assert len(updates) == 2
    assert updates[1][0] > updates[0][0]
    assert updates[1][1] > updates[0][1]


def test_billing_subscription_charged_can_reactivate_cancelled_subscription(monkeypatch):
    from routes import billing

    class Req:
        def __init__(self, body, headers):
            self._body = body
            self.headers = headers

        async def body(self):
            return self._body

    sub = {"id": "sub-local-2", "user_id": "u2", "plan": "bandham", "billing": "month", "status": "cancelled"}
    seen = {"active_set": False}

    async def _fetchrow(query, *args):
        if "SELECT * FROM billing_subscriptions" in query:
            return sub
        return None

    async def _execute(query, *args):
        if "UPDATE billing_subscriptions" in query and "status='active'" in query:
            seen["active_set"] = True
        return "OK"

    pool = _Pool(conn=_Conn(fetchrow=_fetchrow, execute=_execute), fetchrow=_fetchrow, execute=_execute)
    monkeypatch.setattr(billing, "get_pool", lambda: pool)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "secret")

    event = {"event": "subscription.charged", "payload": {"subscription": {"entity": {"id": "sub_gw_2"}}}}
    body = json.dumps(event).encode()
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    _run(billing.webhook(Req(body, {"X-Razorpay-Signature": sig})))
    assert seen["active_set"] is True


def test_scheduler_sends_even_when_access_resolver_would_deny_and_never_calls_it(monkeypatch):
    import scheduler
    from services import billing_access

    now = datetime(2026, 2, 12, 4, 30, tzinfo=timezone.utc)
    local = datetime(2026, 2, 12, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    class _AccessConn:
        async def fetchval(self, query, *_):
            if "SELECT role FROM users" in query:
                return "member"
            return None

        async def fetchrow(self, query, *_):
            if "SELECT * FROM payment_state" in query:
                return {
                    "billing_managed": True,
                    "trial_ends_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    "trial_started_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                    "plan": "nitya",
                    "legacy_paid_plan": None,
                }
            return None

        async def fetch(self, *_):
            return []

    access_out = _run(billing_access.access(_AccessConn(), "u-expired"))
    assert access_out["allowed"] is False

    parent = {
        "id": "p-ent",
        "user_id": "u-expired",
        "timezone": "Asia/Kolkata",
        "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
    }

    access_probe = AsyncMock(return_value={"allowed": False})
    monkeypatch.setattr(scheduler, "billing_access", types.SimpleNamespace(access=access_probe), raising=False)

    async def _fetchval(query, *_args):
        if "pg_try_advisory_xact_lock" in query:
            return True
        if "SELECT max(created_at) FROM message_logs" in query:
            return None
        if "SELECT plan FROM payment_state" in query:
            return "nitya"
        if "status='sent'" in query and "msg_type=$3" not in query:
            return 0
        if "event_key IS NULL" in query:
            return None
        if "msg_type=$3" in query:
            return 0
        if "INSERT INTO care_send_claims" in query:
            return "won"
        return None

    async def _fetchrow(query, *_args):
        if "SELECT * FROM activation_state" in query:
            return {"whatsapp_activated": True, "activated_at": datetime(2026, 2, 2, tzinfo=timezone.utc)}
        if "SELECT * FROM care_send_claims" in query:
            return None
        if "count(*) AS n" in query:
            return {"n": 0, "last": None}
        return None

    send = AsyncMock(return_value={"status": "sent", "sid": "sid-ent"})
    monkeypatch.setattr(scheduler, "send_dynamic_checkin", send)
    monkeypatch.setattr(scheduler, "eligible", lambda *_: True)
    monkeypatch.setattr(scheduler, "local_now", lambda *_: local)
    monkeypatch.setattr(
        scheduler,
        "load_schedule",
        AsyncMock(return_value=({}, [{"category": "water", "type": "reminder", "time": "10:00"}])),
    )
    monkeypatch.setattr(scheduler, "get_pool", lambda: _Pool(conn=_Conn(fetchrow=_fetchrow, fetchval=_fetchval, execute=lambda *_: "OK"), fetchval=_fetchval))

    _run(scheduler._deliver_parent(parent, now))
    assert send.await_count == 1
    assert access_probe.await_count == 0
