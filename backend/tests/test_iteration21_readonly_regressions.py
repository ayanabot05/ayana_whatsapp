"""Readonly regression repros for AYANA webhook/scheduler/notification edge-cases.

These tests are diagnostic: passing means the risky behavior is currently reproducible.
"""

import asyncio
import inspect
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest


# Minimal import stubs so readonly diagnostic tests can load modules without
# installing live infra dependencies.
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

    async def fetchrow(self, *args, **kwargs):
        out = self._fetchrow(*args, **kwargs)
        return await out if inspect.isawaitable(out) else out

    async def fetchval(self, *args, **kwargs):
        out = self._fetchval(*args, **kwargs)
        return await out if inspect.isawaitable(out) else out

    async def fetch(self, *args, **kwargs):
        out = self._fetch(*args, **kwargs)
        return await out if inspect.isawaitable(out) else out

    async def execute(self, *args, **kwargs):
        out = self._execute(*args, **kwargs)
        return await out if inspect.isawaitable(out) else out

    def transaction(self):
        return _Tx()


class _Pool:
    def __init__(self, conn=None, fetchrow=None, execute=None, fetch=None):
        self.conn = conn or _Conn()
        self._fetchrow = fetchrow
        self._execute = execute
        self._fetch = fetch

    def acquire(self):
        return _Acquire(self.conn)

    async def fetchrow(self, *args, **kwargs):
        if self._fetchrow:
            return await self._fetchrow(*args, **kwargs)
        return await self.conn.fetchrow(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        if self._execute:
            return await self._execute(*args, **kwargs)
        return await self.conn.execute(*args, **kwargs)

    async def fetch(self, *args, **kwargs):
        if self._fetch:
            return await self._fetch(*args, **kwargs)
        return await self.conn.fetch(*args, **kwargs)


# webhook.py + notifications.py
def test_unknown_inbound_still_records_recipient_session_but_no_recovery_path(monkeypatch):
    from routes import webhook

    # _process_meta_payload should always track recipient inbound first.
    rec = AsyncMock()
    monkeypatch.setattr(webhook.notifications, "record_recipient_inbound", rec)
    monkeypatch.setattr(webhook, "_record_reply", AsyncMock(return_value={"ignored": True, "parent_id": None}))

    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"id": "wam-1", "from": "+14155550001", "timestamp": str(int(datetime.now(timezone.utc).timestamp())), "type": "text", "text": {"body": "hello"}}]}}]}]
    }
    _run(webhook._process_meta_payload(payload))
    assert rec.await_count == 1

    # _record_reply cannot run owner recovery when no parent is matched.
    create_task_calls = []

    def _ctask(coro):
        create_task_calls.append(coro)
        return None

    monkeypatch.setattr(webhook.asyncio, "create_task", _ctask)
    pool = _Pool(conn=_Conn(fetchrow=lambda q, *_: None))
    monkeypatch.setattr(webhook, "get_pool", lambda: pool)
    out = _run(webhook._record_reply(from_number="+14155550001", body_text="hello"))
    assert out["ignored"] is True
    assert create_task_calls == []


# welcomes.py
def test_welcome_send_once_race_can_double_send(monkeypatch):
    from services import welcomes

    gate = asyncio.Event()
    seen = {"selects": 0, "sends": 0}

    async def _fetchrow(query, *_):
        if "SELECT * FROM welcome_deliveries" in query:
            seen["selects"] += 1
            if seen["selects"] == 1:
                await gate.wait()
            else:
                gate.set()
            return None
        return None

    async def _execute(*_args, **_kwargs):
        return "OK"

    async def _send(*_args, **_kwargs):
        seen["sends"] += 1
        await asyncio.sleep(0)
        return {"status": "sent", "sid": f"sid-{seen['sends']}"}

    monkeypatch.setattr(welcomes, "get_pool", lambda: _Pool(fetchrow=_fetchrow, execute=_execute))
    monkeypatch.setattr(welcomes, "whatsapp_enabled", lambda: True)
    monkeypatch.setattr(welcomes, "_send_content_template_with_retry", _send)

    async def _race():
        await asyncio.gather(
            welcomes.send_once("evt-1", "+14155550001", "Kid", "Mom", "en"),
            welcomes.send_once("evt-1", "+14155550001", "Kid", "Mom", "en"),
        )

    _run(_race())
    assert seen["sends"] == 2


# scheduler.py
def test_scheduler_skips_when_claim_not_failed_even_if_delivery_failed_elsewhere(monkeypatch):
    import scheduler

    parent = {
        "id": "p1",
        "user_id": "u1",
        "timezone": "Asia/Kolkata",
        "created_at": datetime.now(timezone.utc) - timedelta(days=2),
    }
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    async def _fetchval(query, *_args):
        if "pg_try_advisory_xact_lock" in query:
            return True
        if "SELECT max(created_at) FROM message_logs" in query:
            return None
        if "SELECT plan FROM payment_state" in query:
            return "raksha"
        if "status='sent'" in query:
            return 0
        if "event_key IS NULL" in query:
            return None
        if "msg_type=$3" in query:
            return 0
        return None

    async def _fetchrow(query, *_args):
        if "SELECT * FROM activation_state" in query:
            return {"whatsapp_activated": True, "activated_at": now - timedelta(days=1)}
        if "SELECT * FROM care_send_claims" in query:
            return {"event_key": "k1", "status": "sent"}
        if "count(*) AS n" in query:
            return {"n": 0, "last": None}
        return None

    sent = []

    async def _send_dynamic(*_args, **_kwargs):
        sent.append(True)
        return {"status": "sent", "sid": "x"}

    monkeypatch.setattr(scheduler, "load_schedule", AsyncMock(return_value=({"recovery_mode": True}, [{"category": "medicine", "type": "reminder", "time": "10:00"}])))
    monkeypatch.setattr(scheduler, "eligible", lambda *_: True)
    monkeypatch.setattr(scheduler, "local_now", lambda *_: now.astimezone())
    monkeypatch.setattr(scheduler, "send_dynamic_checkin", _send_dynamic)
    monkeypatch.setattr(scheduler, "get_pool", lambda: _Pool(conn=_Conn(fetchrow=_fetchrow, fetchval=_fetchval)))
    _run(scheduler._deliver_parent(parent, now))
    assert sent == []


# notifications.py
def test_failed_receipts_are_not_selected_by_drain_retry_queue(monkeypatch):
    from services import notifications

    executed = []

    async def _execute(query, *_):
        executed.append(query)
        return "OK"

    async def _fetch(query, *_):
        # Current drain query excludes 'failed'.
        assert "status IN ('pending','retry','awaiting_template','disabled')" in query
        return []

    deliver = AsyncMock()
    monkeypatch.setattr(notifications, "get_pool", lambda: _Pool(conn=_Conn(execute=_execute, fetch=_fetch)))
    monkeypatch.setattr(notifications, "deliver", deliver)
    _run(notifications.drain_notifications())
    assert deliver.await_count == 0
    assert any("status='sending'" in q for q in executed)


# escalation.py
def test_main_warning_suppressed_after_window_end_due_to_eligible_gate(monkeypatch):
    import escalation

    parent = {
        "id": "p2",
        "user_id": "u2",
        "timezone": "Asia/Kolkata",
        "activity_window_start": "06:00",
        "activity_window_end": "22:00",
    }
    local_after_end = datetime(2026, 2, 12, 22, 5, tzinfo=timezone.utc)

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


# whatsapp.py
def test_uncertain_reengagement_is_not_marked_and_can_resend(monkeypatch):
    import whatsapp

    session = {
        "reengagement_sent": False,
        "opener_sent_at": datetime.now(timezone.utc) - timedelta(hours=10),
        "last_inbound_at": None,
    }
    calls = []

    async def _send(*_args, **_kwargs):
        calls.append(1)
        return {"status": "uncertain", "detail": "provider timeout"}

    monkeypatch.setattr(whatsapp, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(whatsapp, "_send_content_template_with_retry", _send)
    monkeypatch.setattr(whatsapp, "whatsapp_enabled", lambda: True)
    marker = AsyncMock()
    monkeypatch.setattr(whatsapp, "mark_reengagement_sent", marker)

    parent = {"id": "p3", "phone": "+14155550003", "language": "en", "name": "Mom"}
    _run(whatsapp.send_reengagement(parent, reengagement_hours=4))
    _run(whatsapp.send_reengagement(parent, reengagement_hours=4))
    assert len(calls) == 2
    assert marker.await_count == 0


def test_mark_opener_sent_always_resets_reengagement_flag(monkeypatch):
    import whatsapp

    seen = {}

    async def _execute(query, *args):
        seen["query"] = query
        seen["args"] = args
        return "OK"

    monkeypatch.setattr(whatsapp, "get_pool", lambda: _Pool(conn=_Conn(execute=_execute)))
    _run(whatsapp.mark_opener_sent("parent-x", template_type="medicine"))
    assert "reengagement_sent = false" in seen["query"]


def test_scheduleinput_recovery_mode_extra_reminders_blocked_by_field_order_bug():
    from models import ScheduleInput

    msgs = [{"time": f"0{i}:00", "category": "medicine"} for i in range(1, 9)]
    with pytest.raises(Exception):
        ScheduleInput(parent_id="p", mode="raksha", messages=msgs, recovery_mode=True)


# schedule_source.py
def test_load_schedule_keeps_recovery_rows_even_if_recovery_until_expired():
    from services import schedule_source

    parent = {"id": "p4", "medicine_list": []}
    legacy = {
        "active": True,
        "deleted_at": None,
        "recovery_mode": True,
        "recovery_until": "2020-01-01",
        "messages": [{"time": "09:00", "category": "medicine", "is_recovery": True}],
    }

    conn = _Conn(fetchrow=lambda *_: legacy)
    sched, items = _run(schedule_source.load_schedule(conn, parent))
    assert sched["recovery_mode"] is True
    assert any(i.get("category") == "medicine" for i in items)


def test_load_schedule_expands_single_medicine_slot_into_multiple_named_sends():
    from services import schedule_source

    parent = {
        "id": "p5",
        "medicine_list": [
            {"name": "Med A", "reminder_time": "09:00"},
            {"name": "Med B", "reminder_time": "09:00"},
        ],
    }
    legacy = {
        "active": True,
        "deleted_at": None,
        "messages": [{"time": "09:00", "category": "medicine"}],
    }
    conn = _Conn(fetchrow=lambda *_: legacy)
    _, items = _run(schedule_source.load_schedule(conn, parent))
    meds = [i for i in items if i["category"] == "medicine" and i["time"] == "09:00"]
    assert len(meds) == 2


# webhook.py reply association
def test_apply_button_tap_effects_updates_latest_category_not_exact_message_log(monkeypatch):
    from routes import webhook

    updates = []

    async def _fetchrow(query, *args):
        if "select language, timezone from parents" in query:
            return {"language": "en", "timezone": "Asia/Kolkata"}
        if "select id from message_logs" in query:
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
        "from_phone": "+14155550006",
        "message_log_id": "older-log-id",
    }
    _run(webhook._apply_button_tap_effects(reply))
    assert any("update message_logs set reply_status" in q.lower() and a[1] == "latest-log" for q, a in updates)


# webhook.py audio resolver failure path
def test_audio_without_resolved_media_url_reaches_non_voice_record_branch(monkeypatch):
    from routes import webhook

    captured = {}
    monkeypatch.setattr(webhook.notifications, "record_recipient_inbound", AsyncMock())

    async def _record(**kwargs):
        captured.update(kwargs)
        return {"parent_id": "p", "duplicate": False}

    monkeypatch.setattr(webhook, "_record_reply", _record)
    monkeypatch.setattr(webhook, "resolve_meta_media_url", AsyncMock(return_value=None))
    monkeypatch.setattr(webhook, "_apply_button_tap_effects", AsyncMock())

    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"id": "wam-a", "from": "+14155550007", "timestamp": str(int(datetime.now(timezone.utc).timestamp())), "type": "audio", "audio": {"id": "media-1", "mime_type": "audio/ogg"}}]}}]}]
    }
    _run(webhook._process_meta_payload(payload))
    assert captured["media_url"] is None
    assert captured["media_content_type"].startswith("audio/")
    assert captured["body_text"] == ""


# whatsapp.py health reminder outside 24h is blocked template
def test_health_check_outside_session_is_blocked_template(monkeypatch):
    import whatsapp

    monkeypatch.setattr(whatsapp, "is_session_open", AsyncMock(return_value=False))
    result = _run(whatsapp.send_dynamic_checkin(
        {"id": "p6", "phone": "+14155550008", "language": "en", "name": "Mom"},
        "water",
        day_index=1,
        variants_per_slot=3,
    ))
    assert result["status"] == "blocked_template"


# webhook retry side-effects
def test_button_side_effect_failure_then_retry_causes_permanent_bypass(monkeypatch):
    from routes import webhook

    monkeypatch.setattr(webhook.notifications, "record_recipient_inbound", AsyncMock())

    first = {"n": 0}

    async def _record(**_kwargs):
        first["n"] += 1
        if first["n"] == 1:
            return {"parent_id": "p", "duplicate": False}
        return {"parent_id": "p", "duplicate": True}

    apply_calls = []

    async def _apply(_reply):
        apply_calls.append(1)
        raise RuntimeError("side effect failed")

    monkeypatch.setattr(webhook, "_record_reply", _record)
    monkeypatch.setattr(webhook, "_apply_button_tap_effects", _apply)

    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"id": "wam-btn", "from": "+14155550009", "timestamp": str(int(datetime.now(timezone.utc).timestamp())), "type": "button", "button": {"payload": "done:medicine", "text": "Done"}}]}}]}]
    }

    with pytest.raises(RuntimeError):
        _run(webhook._process_meta_payload(payload))

    # Meta retry, now duplicate path: side-effect callback is bypassed.
    monkeypatch.setattr(webhook, "_apply_button_tap_effects", AsyncMock())
    _run(webhook._process_meta_payload(payload))
    assert len(apply_calls) == 1
