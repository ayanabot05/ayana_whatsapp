import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
import os
import hashlib
import hmac
from bson import ObjectId

from whatsapp import (
    verify_meta_signature,
    is_session_open,
    parse_intent,
    detect_emergency,
    _match_feeling,
    send_reengagement,
    send_moment
)

FAKE_OID = str(ObjectId())

def test_verify_meta_signature():
    # Setup test secret and payload
    secret = "test_secret"
    body = b'{"test": "payload"}'
    
    with patch.dict(os.environ, {"META_WA_APP_SECRET": secret}):
        expected_sig = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        
        # Valid HMAC
        assert verify_meta_signature(body, expected_sig) is True
        
        # Tampered body
        tampered_body = b'{"test": "tampered"}'
        assert verify_meta_signature(tampered_body, expected_sig) is False
        
        # Missing signature
        assert verify_meta_signature(body, "") is False
        assert verify_meta_signature(body, None) is False

@pytest.mark.asyncio
async def test_is_session_open():
    mock_db = MagicMock()
    
    # Within 24h
    recent = datetime.now(timezone.utc) - timedelta(hours=10)
    mock_db.wa_sessions.find_one = AsyncMock(return_value={"last_inbound_at": recent})
    assert await is_session_open(mock_db, FAKE_OID) is True
    
    # Expired
    expired = datetime.now(timezone.utc) - timedelta(hours=25)
    mock_db.wa_sessions.find_one = AsyncMock(return_value={"last_inbound_at": expired})
    assert await is_session_open(mock_db, FAKE_OID) is False

def test_parse_intent():
    # Button payload
    assert parse_intent("medicine_done", None) == "medicine_done"
    
    # Free-text feeling matching
    assert parse_intent(None, "గుడ్") == "feeling:good"
    assert parse_intent(None, "मुझे खराब") == "feeling:not_well"
    
    # Numeric responses
    assert parse_intent(None, "1", "checkin") == "feeling:good"
    assert parse_intent(None, "2", "reminder") == "pending:generic"

def test_detect_emergency():
    # Keyword matching
    assert len(detect_emergency("i feel dizzy")) > 0
    # Custom extra keywords
    assert "helpme" in detect_emergency("helpme please", ["helpme"])

def test_match_feeling():
    assert _match_feeling("చాలా బాగుంది") == "good"
    assert _match_feeling("ठीक है") == "good"
    assert _match_feeling("ఒంట్లో బాలేదు") == "not_well"
    assert _match_feeling("unknown string") is None

@pytest.mark.asyncio
@patch("whatsapp._send_content_template_with_retry")
@patch("whatsapp.send_whatsapp")
async def test_send_reengagement(mock_send_wa, mock_send_template):
    mock_db = MagicMock()
    parent = {"_id": FAKE_OID, "phone": "+919876543210", "language": "en"}
    
    # No session
    mock_db.wa_sessions.find_one = AsyncMock(return_value=None)
    assert (await send_reengagement(mock_db, parent))["reason"] == "no_session"
    
    # Already sent
    mock_db.wa_sessions.find_one = AsyncMock(return_value={"reengagement_sent": True})
    assert (await send_reengagement(mock_db, parent))["reason"] == "already_sent"
    
    # No opener sent
    mock_db.wa_sessions.find_one = AsyncMock(return_value={"reengagement_sent": False})
    assert (await send_reengagement(mock_db, parent))["reason"] == "no_opener_sent"
    
    # Time < threshold
    recent_opener = datetime.now(timezone.utc) - timedelta(hours=2)
    mock_db.wa_sessions.find_one = AsyncMock(return_value={
        "reengagement_sent": False,
        "opener_sent_at": recent_opener
    })
    assert "too_soon" in (await send_reengagement(mock_db, parent, 4))["reason"]
    
    # Parent replied
    old_opener = datetime.now(timezone.utc) - timedelta(hours=5)
    recent_inbound = datetime.now(timezone.utc) - timedelta(hours=1)
    mock_db.wa_sessions.find_one = AsyncMock(return_value={
        "reengagement_sent": False,
        "opener_sent_at": old_opener,
        "last_inbound_at": recent_inbound
    })
    assert (await send_reengagement(mock_db, parent, 4))["reason"] == "parent_replied"

@pytest.mark.asyncio
@patch("whatsapp.httpx.post")
@patch("whatsapp._creds")
@patch("whatsapp.whatsapp_enabled")
async def test_send_moment(mock_wa_enabled, mock_creds, mock_post):
    mock_wa_enabled.return_value = True
    mock_creds.return_value = ("token", "phone_id")
    mock_db = MagicMock()
    parent = {"phone": "+123", "language": "en"}
    
    # Mock HTTP response
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"messages": [{"id": "msg_id"}]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp
    
    # 2 images
    res2 = await send_moment(mock_db, parent, "Hello", "Child", image_urls=["http://img1", "http://img2"])
    assert res2["status"] == "sent"
    assert mock_post.call_count == 2
    
    mock_post.reset_mock()
    
    # 1 image
    res1 = await send_moment(mock_db, parent, "Hello", "Child", image_url="http://img1")
    assert res1["status"] == "sent"
    assert mock_post.call_count == 1
    
    # Text-only
    with patch("whatsapp.send_whatsapp") as mock_send_wa:
        mock_send_wa.return_value = {"status": "sent"}
        res0 = await send_moment(mock_db, parent, "Hello", "Child")
        assert res0["status"] == "sent"
        assert mock_send_wa.called
