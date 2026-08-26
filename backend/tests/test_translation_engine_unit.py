import pytest
import os
from unittest.mock import patch, AsyncMock
from translation_engine import get_variants, _translate_variants, dynamic_translation_enabled

@pytest.fixture
def enable_translation():
    with patch.dict(os.environ, {"DYNAMIC_TRANSLATION_ENABLED": "true", "SARVAM_API_KEY": "key"}):
        yield

def test_dynamic_translation_enabled():
    with patch.dict(os.environ, {"DYNAMIC_TRANSLATION_ENABLED": "true"}):
        assert dynamic_translation_enabled() is True
    with patch.dict(os.environ, {"DYNAMIC_TRANSLATION_ENABLED": "false"}):
        assert dynamic_translation_enabled() is False

@pytest.mark.asyncio
async def test_get_variants_launch_languages(enable_translation):
    mock_db = AsyncMock()
    # Launch languages bypass API and DB
    assert await get_variants(mock_db, "morning_wish", "en") is None
    assert await get_variants(mock_db, "morning_wish", "te") is None
    assert await get_variants(mock_db, "morning_wish", "hi") is None
    assert mock_db.template_variants_cache.find_one.call_count == 0

@pytest.mark.asyncio
async def test_get_variants_cache_hit(enable_translation):
    mock_db = AsyncMock()
    mock_db.template_variants_cache.find_one.return_value = {"variants": ["v1", "v2"]}
    
    variants = await get_variants(mock_db, "morning_wish", "kn")
    assert variants == ["v1", "v2"]
    
@pytest.mark.asyncio
async def test_get_variants_cache_miss_api_success(enable_translation):
    mock_db = AsyncMock()
    mock_db.template_variants_cache.find_one.return_value = None
    
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"translated_text": "translated {nick1}"}
    
    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        variants = await get_variants(mock_db, "morning_wish", "kn")
        assert variants is not None
        assert len(variants) > 0
        mock_db.template_variants_cache.update_one.assert_called_once()

@pytest.mark.asyncio
async def test_get_variants_api_failure(enable_translation):
    mock_db = AsyncMock()
    mock_db.template_variants_cache.find_one.return_value = None
    
    mock_resp = AsyncMock()
    mock_resp.status_code = 500
    
    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        variants = await get_variants(mock_db, "morning_wish", "kn")
        assert variants is None

@pytest.mark.asyncio
async def test_translate_variants_preserves_placeholders(enable_translation):
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"translated_text": "Kannada {city}"}
    
    with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
        res = await _translate_variants(["Hello {city}"], "kn")
        assert res == ["Kannada {city}"]
        
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["preserve_formatting"] is True
