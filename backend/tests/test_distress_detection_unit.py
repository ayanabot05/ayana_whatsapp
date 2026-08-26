import pytest
import os
from unittest.mock import patch, AsyncMock
from distress_detection import _pretrained_distress_score, assess_transcript
import httpx

@pytest.fixture
def enable_ml():
    with patch.dict(os.environ, {"DISTRESS_ML_ENABLED": "true", "SARVAM_API_KEY": "test_key"}):
        yield

@pytest.mark.asyncio
async def test_pretrained_distress_score_disabled():
    with patch.dict(os.environ, {"DISTRESS_ML_ENABLED": "false"}):
        score = await _pretrained_distress_score("test", "en")
        assert score is None

@pytest.mark.asyncio
async def test_pretrained_distress_score_success(enable_ml):
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"distress_likelihood": 0.8}'}}]
    }
    
    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        score = await _pretrained_distress_score("I feel pain", "en")
        assert score == 0.8

@pytest.mark.asyncio
async def test_pretrained_distress_score_timeout(enable_ml):
    with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("timeout")):
        score = await _pretrained_distress_score("I feel pain", "en")
        assert score is None

@pytest.mark.asyncio
async def test_pretrained_distress_score_json_error(enable_ml):
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": 'invalid json'}}]
    }
    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        score = await _pretrained_distress_score("I feel pain", "en")
        assert score is None

@pytest.mark.asyncio
async def test_assess_transcript():
    mock_db = AsyncMock()
    with patch("distress_detection._pretrained_distress_score", return_value=0.75):
        result = await assess_transcript(mock_db, "parent_1", "test", "en", [])
        
        assert result["ml_flagged"] is True
        assert result["ml_score"] == 0.75
        assert result["keyword_emergency"] is False
        mock_db.distress_logs.insert_one.assert_called_once()
        
    with patch("distress_detection._pretrained_distress_score", return_value=0.5):
        result = await assess_transcript(mock_db, "parent_1", "test", "en", ["help"])
        
        assert result["ml_flagged"] is False
        assert result["ml_score"] == 0.5
        assert result["keyword_emergency"] is True
