import pytest
import os
from unittest.mock import patch, AsyncMock
from sarvam_stt import _ext_from_content_type, stt_enabled, transcribe_voice_note
import httpx

def test_ext_from_content_type():
    assert _ext_from_content_type("audio/ogg") == "ogg"
    assert _ext_from_content_type("audio/ogg; codecs=opus") == "ogg"
    assert _ext_from_content_type("audio/mpeg") == "mp3"
    assert _ext_from_content_type("audio/mp4") == "m4a"
    assert _ext_from_content_type("audio/wav") == "wav"
    assert _ext_from_content_type("audio/webm") == "webm"
    assert _ext_from_content_type("application/json") == "ogg" # default fallback

def test_stt_enabled():
    with patch.dict(os.environ, {"SARVAM_API_KEY": "key"}):
        assert stt_enabled() is True
    with patch.dict(os.environ, {"SARVAM_API_KEY": ""}):
        assert stt_enabled() is False
    with patch.dict(os.environ, {}, clear=True):
        assert stt_enabled() is False

@pytest.mark.asyncio
async def test_transcribe_voice_note_success():
    with patch.dict(os.environ, {"SARVAM_API_KEY": "key"}):
        mock_get_resp = AsyncMock()
        mock_get_resp.status_code = 200
        mock_get_resp.content = b"a" * 1500 # > 1000 bytes
        mock_get_resp.headers = {"content-type": "audio/ogg"}
        
        mock_post_resp = AsyncMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {"transcript": "hello world"}
        
        async def mock_request(method, *args, **kwargs):
            if method == "GET":
                return mock_get_resp
            return mock_post_resp
            
        with patch("httpx.AsyncClient.request", side_effect=mock_request), \
             patch("httpx.AsyncClient.get", return_value=mock_get_resp), \
             patch("httpx.AsyncClient.post", return_value=mock_post_resp):
            
            transcript = await transcribe_voice_note("http://example.com/audio")
            assert transcript == "hello world"

@pytest.mark.asyncio
async def test_transcribe_voice_note_download_fails():
    with patch.dict(os.environ, {"SARVAM_API_KEY": "key"}):
        with patch("httpx.AsyncClient.get", side_effect=Exception("network error")):
            with patch("asyncio.sleep", new_callable=AsyncMock): # Speed up sleep
                transcript = await transcribe_voice_note("http://example.com/audio")
                assert transcript is None # 3 retries failed

@pytest.mark.asyncio
async def test_transcribe_voice_note_api_error():
    with patch.dict(os.environ, {"SARVAM_API_KEY": "key"}):
        mock_get_resp = AsyncMock()
        mock_get_resp.status_code = 200
        mock_get_resp.content = b"a" * 1500
        mock_get_resp.headers = {"content-type": "audio/ogg"}
        
        mock_post_resp = AsyncMock()
        mock_post_resp.status_code = 500
        
        with patch("httpx.AsyncClient.get", return_value=mock_get_resp), \
             patch("httpx.AsyncClient.post", return_value=mock_post_resp):
            
            transcript = await transcribe_voice_note("http://example.com/audio")
            assert transcript is None
