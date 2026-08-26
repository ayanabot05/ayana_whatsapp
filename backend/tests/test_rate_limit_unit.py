import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from rate_limit import (
    check_otp_send_rate_limit,
    check_login_rate_limit,
    check_api_rate_limit,
    clear_login_attempts,
    OTP_SEND_LIMIT,
    LOGIN_ATTEMPT_LIMIT,
    API_LIMIT
)
import rate_limit

@pytest.fixture
def mock_redis():
    mock_r = AsyncMock()
    with patch("rate_limit.get_redis", return_value=mock_r):
        yield mock_r

@pytest.mark.asyncio
async def test_check_otp_send_rate_limit_under_limit(mock_redis):
    mock_redis.zcard.return_value = OTP_SEND_LIMIT - 1
    allowed, retry_after = await check_otp_send_rate_limit("+1234567890")
    assert allowed is True
    assert retry_after is None

@pytest.mark.asyncio
async def test_check_otp_send_rate_limit_at_limit(mock_redis):
    mock_redis.zcard.return_value = OTP_SEND_LIMIT
    mock_redis.zrange.return_value = [("timestamp", 1000000.0)]
    with patch("rate_limit.datetime") as mock_dt:
        mock_dt.now.return_value.timestamp.return_value = 1000010.0
        allowed, retry_after = await check_otp_send_rate_limit("+1234567890")
        assert allowed is False
        assert retry_after > 0

@pytest.mark.asyncio
async def test_check_login_rate_limit_under_limit(mock_redis):
    pipe_mock = AsyncMock()
    mock_redis.pipeline.return_value = pipe_mock
    pipe_mock.execute.return_value = [str(LOGIN_ATTEMPT_LIMIT - 1), None]
    
    allowed, retry_after = await check_login_rate_limit("test@example.com", "127.0.0.1")
    assert allowed is True
    assert retry_after is None

@pytest.mark.asyncio
async def test_check_login_rate_limit_lockout(mock_redis):
    pipe_mock = AsyncMock()
    mock_redis.pipeline.return_value = pipe_mock
    pipe_mock.execute.return_value = [str(LOGIN_ATTEMPT_LIMIT), None]
    
    allowed, retry_after = await check_login_rate_limit("test@example.com", "127.0.0.1")
    assert allowed is False
    assert retry_after > 0
    mock_redis.set.assert_called_once() # Sets lockout

@pytest.mark.asyncio
async def test_check_api_rate_limit_under_limit(mock_redis):
    mock_redis.zcard.return_value = API_LIMIT - 1
    request = MagicMock()
    request.headers.get.return_value = "127.0.0.1"
    
    allowed, retry_after = await check_api_rate_limit(request)
    assert allowed is True
    assert retry_after is None

@pytest.mark.asyncio
async def test_check_api_rate_limit_over_limit(mock_redis):
    mock_redis.zcard.return_value = API_LIMIT
    mock_redis.zrange.return_value = [("ts", 1000000.0)]
    request = MagicMock()
    request.headers.get.return_value = "127.0.0.1"
    
    with patch("rate_limit.datetime") as mock_dt:
        mock_dt.now.return_value.timestamp.return_value = 1000010.0
        allowed, retry_after = await check_api_rate_limit(request)
        assert allowed is False
        assert retry_after > 0

@pytest.mark.asyncio
async def test_graceful_degradation():
    with patch("rate_limit.get_redis", return_value=None):
        request = MagicMock()
        request.headers.get.return_value = "127.0.0.1"
        
        allowed, retry_after = await check_otp_send_rate_limit("+1234567890")
        assert allowed is True
        
        allowed, retry_after = await check_login_rate_limit("test@example.com", "127.0.0.1")
        assert allowed is True
        
        allowed, retry_after = await check_api_rate_limit(request)
        assert allowed is True

@pytest.mark.asyncio
async def test_clear_login_attempts(mock_redis):
    await clear_login_attempts("test@example.com", "127.0.0.1")
    mock_redis.delete.assert_called_once()
