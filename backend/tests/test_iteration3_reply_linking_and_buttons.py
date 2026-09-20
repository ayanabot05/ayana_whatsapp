"""Regression tests for reply linking + exact button intent side effects.

Modules covered: services/reply_linking.py, services/button_intents.py,
routes/webhook.py::_apply_button_tap_effects
"""

import asyncio
from datetime import datetime, timezone

import pytest

from services.reply_linking import build_parent_days, linked_replies
from services.button_intents import exact_button_intent
import routes.webhook as webhook


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_dad_reply_association_context_preserved_and_general_not_medicine():
    dad = "11111111-1111-1111-1111-111111111111"
    mom = "22222222-2222-2222-2222-222222222222"
    logs = [
        {"id": "m1", "parent_id": dad, "sid": "sid-morning", "category": "morning", "msg_type": "checkin", "status": "sent", "created_at": _dt("2026-02-10T03:00:00Z")},
        {"id": "m2", "parent_id": dad, "sid": "sid-med", "category": "medicine", "msg_type": "reminder", "status": "sent", "created_at": _dt("2026-02-10T05:00:00Z")},
        {"id": "m3", "parent_id": dad, "sid": "sid-lunch", "category": "lunch", "msg_type": "checkin", "status": "sent", "created_at": _dt("2026-02-10T07:00:00Z")},
        {"id": "m4", "parent_id": dad, "sid": "sid-reengage", "category": "reengagement", "msg_type": "reengagement", "status": "sent", "created_at": _dt("2026-02-10T10:00:00Z")},
    ]
    replies = [
        {"id": "r1", "parent_id": dad, "context_id": "sid-lunch", "created_at": _dt("2026-02-10T07:30:00Z"), "body": "Lunch done", "is_voice": False},
        {"id": "r2", "parent_id": dad, "context_id": "sid-reengage", "created_at": _dt("2026-02-10T10:15:00Z"), "body": "I am here", "is_voice": False},
        {"id": "r3", "parent_id": dad, "context_id": None, "created_at": _dt("2026-02-10T11:00:00Z"), "body": "General voice", "is_voice": True},
        {"id": "r4", "parent_id": dad, "context_id": "sid-lunch", "created_at": _dt("2026-02-10T20:00:00Z"), "body": "Late reply", "is_voice": False},
        {"id": "r5", "parent_id": mom, "context_id": "sid-lunch", "created_at": _dt("2026-02-10T07:35:00Z"), "body": "Mom reply", "is_voice": False},
    ]

    linked, general = linked_replies(logs, replies)
    assert [r["id"] for r in linked["m3"]] == ["r1", "r4"]
    assert [r["id"] for r in linked["m4"]] == ["r2"]
    assert {r["id"] for r in general} == {"r3", "r5"}


def test_late_reply_visible_on_context_day_and_received_day():
    parent = {"id": "11111111-1111-1111-1111-111111111111", "timezone": "Asia/Kolkata", "name": "Dad", "relationship": "father"}
    logs = [
        {"id": "m1", "parent_id": parent["id"], "sid": "sid-lunch", "category": "lunch", "msg_type": "checkin", "status": "sent", "created_at": _dt("2026-02-10T07:00:00Z")},
    ]
    replies = [
        {"id": "r1", "parent_id": parent["id"], "context_id": "sid-lunch", "created_at": _dt("2026-02-10T20:00:00Z"), "body": "Late reply", "is_voice": False},
    ]

    days = build_parent_days(parent, logs, replies)
    by_day = {d["day_key"]: d for d in days}
    assert "2026-02-10" in by_day
    assert "2026-02-11" in by_day
    assert by_day["2026-02-10"]["messages"][0]["replied"] is True
    assert by_day["2026-02-11"]["late_replies"][0]["id"] == "r1"


def test_exact_button_intent_safety_titles_not_arrived_for_done_or_on_way():
    log = {"category": "temple_return", "msg_type": "safety"}
    assert exact_button_intent(log, "", "Darshan done") == "activity_done:temple_return"
    assert exact_button_intent(log, "", "On the way") == "on_way:temple_return"
    assert exact_button_intent(log, "", "Reached home safe") == "arrived:temple_return"


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Conn:
    def __init__(self):
        self.claimed = False
        self.execute_calls = []
        self.ack_count = 0

    def transaction(self):
        return _Tx()

    async def fetchval(self, query, *args):
        if "effects_applied_at" in query and not self.claimed:
            self.claimed = True
            return args[0]
        return None

    async def fetchrow(self, query, *args):
        if "select language, timezone from parents" in query.lower():
            return {"language": "en", "timezone": "Asia/Kolkata"}
        return None

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _TxAcquire(self.conn)


class _TxAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_apply_button_tap_effects_updates_only_context_row_once(monkeypatch):
    conn = _Conn()
    sent = []
    monkeypatch.setattr(webhook, "get_pool", lambda: _Pool(conn))
    monkeypatch.setattr(webhook, "send_whatsapp", lambda phone, body: sent.append((phone, body)))

    reply = {
        "id": "r-1",
        "intent": "done:medicine",
        "parent_id": "11111111-1111-1111-1111-111111111111",
        "from_phone": "+919999999999",
        "context_id": "sid-med",
        "message_log_id": "m-99",
    }

    asyncio.run(webhook._apply_button_tap_effects(reply))
    asyncio.run(webhook._apply_button_tap_effects(reply))

    updates = [c for c in conn.execute_calls if "UPDATE message_logs SET reply_status" in c[0]]
    assert len(updates) == 1
    assert updates[0][1] == ("done", "m-99", "11111111-1111-1111-1111-111111111111", "sid-med", "medicine")
    assert len(sent) == 1
