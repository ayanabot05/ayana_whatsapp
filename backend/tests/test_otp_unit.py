import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from otp import (
    generate_otp,
    hash_otp,
    verify_otp_hash,
    _normalize_phone,
    create_and_send_otp,
    verify_otp_code,
    send_otp_sms
)

def test_generate_otp():
    otp1 = generate_otp()
    otp2 = generate_otp()
    assert len(otp1) == 6
    assert otp1.isdigit()
    assert otp1 != otp2

def test_hash_verify_otp():
    code = "123456"
    hashed = hash_otp(code)
    assert verify_otp_hash(code, hashed) is True
    assert verify_otp_hash("654321", hashed) is False

def test_normalize_phone():
    assert _normalize_phone(" 987 654-3210 ") == "+9876543210"
    assert _normalize_phone("+1 (234) 567 89") == "+123456789"
    assert _normalize_phone("1234") == "+1234"

@pytest.mark.asyncio
@patch("otp.db")
async def test_create_and_send_otp_rate_limit(mock_db):
    phone = "+1234567890"
    now = datetime.now(timezone.utc)
    mock_db.phone_otps.find_one = AsyncMock(return_value={
        "send_count": 3,
        "send_window_start": now
    })
    
    res = await create_and_send_otp(phone)
    assert res["status"] == "rate_limited"

@pytest.mark.asyncio
@patch("otp.db")
@patch("otp._check_verify_rate_limit", return_value=(True, None))
@patch("otp._record_verify_attempt", new_callable=AsyncMock)
async def test_verify_otp_max_attempts(mock_record, mock_check, mock_db):
    phone = "+1234567890"
    
    # 3 failed -> too_many_attempts
    # We need to simulate find_one_and_update returning None because attempts >= 3
    mock_db.phone_otps.find_one_and_update = AsyncMock(return_value=None)
    mock_db.phone_otps.find_one = AsyncMock(return_value={
        "attempts": 3,
        "verified": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5)
    })
    
    res = await verify_otp_code(phone, "123456")
    assert res["ok"] is False
    assert res["code"] == "too_many_attempts"

@pytest.mark.asyncio
@patch("otp.db")
@patch("otp._check_verify_rate_limit", return_value=(True, None))
async def test_verify_otp_expiration(mock_check, mock_db):
    phone = "+1234567890"
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    
    mock_db.phone_otps.find_one = AsyncMock(return_value={
        "expires_at": past,
        "verified": False
    })
    
    res = await verify_otp_code(phone, "123456")
    assert res["ok"] is False
    assert res["code"] == "expired"

@pytest.mark.asyncio
@patch("otp.httpx.AsyncClient")
@patch("otp.otp_delivery_enabled", return_value=True)
@patch("otp.os.environ.get")
async def test_send_otp_sms_error_handling(mock_env, mock_enabled, mock_client):
    def env_side_effect(k, default=""):
        return "val" if k in ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM"] else default
    mock_env.side_effect = env_side_effect
    
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"message": "Invalid number", "code": "21211"}
    
    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_resp
    mock_client.return_value.__aenter__.return_value = mock_client_instance
    
    res = await send_otp_sms("+123", "123456")
    assert res["status"] == "failed"
    assert "delivery failed" in res["detail"]
