import io
from unittest.mock import patch

import pytest


# We need to test upload-image which uses put_object from storage
@pytest.fixture
def mock_storage():
    with patch("server.put_object") as m_put:
        m_put.return_value = {"path": "mocked/path.jpg", "size": 1024}
        with patch("server.get_object") as m_get:
            m_get.return_value = (b"fake_image_data", "image/jpeg")
            yield m_put, m_get

def test_upload_image_success(api_client, api_url, fresh_user, mock_storage):
    m_put, _m_get = mock_storage
    h = fresh_user["headers"]
    
    # Create a small valid valid-ish image (or just bytes that Pillow can decode)
    # Actually, the server parses with Pillow. We should provide a valid 1x1 JPEG.
    from PIL import Image
    img_byte_arr = io.BytesIO()
    img = Image.new('RGB', (10, 10), color = 'red')
    img.save(img_byte_arr, format='JPEG')
    img_bytes = img_byte_arr.getvalue()
    
    files = {"file": ("test.jpg", img_bytes, "image/jpeg")}
    r = api_client.post(f"{api_url}/moments/upload-image", headers=h, files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "url" in data
    assert "filename" in data
    assert m_put.called

def test_upload_image_invalid_type(api_client, api_url, fresh_user, mock_storage):
    h = fresh_user["headers"]
    files = {"file": ("test.txt", b"not an image", "text/plain")}
    r = api_client.post(f"{api_url}/moments/upload-image", headers=h, files=files)
    assert r.status_code == 400

def test_upload_image_oversized(api_client, api_url, fresh_user, mock_storage):
    h = fresh_user["headers"]
    # 6MB of data
    large_data = b"0" * (6 * 1024 * 1024)
    files = {"file": ("test.jpg", large_data, "image/jpeg")}
    r = api_client.post(f"{api_url}/moments/upload-image", headers=h, files=files)
    assert r.status_code == 413

def test_signed_url(api_client, api_url, fresh_user, mock_storage):
    _m_put, _m_get = mock_storage
    h = fresh_user["headers"]
    
    from PIL import Image
    img_byte_arr = io.BytesIO()
    img = Image.new('RGB', (10, 10), color = 'red')
    img.save(img_byte_arr, format='JPEG')
    files = {"file": ("test.jpg", img_byte_arr.getvalue(), "image/jpeg")}
    
    r = api_client.post(f"{api_url}/moments/upload-image", headers=h, files=files)
    assert r.status_code == 200
    
    url = r.json()["url"]
    
    # Valid signature
    r2 = api_client.get(url)
    assert r2.status_code == 200
    assert r2.content == b"fake_image_data"
    
    # Tampered signature
    tampered_url = url.replace("sig=", "sig=tampered")
    r3 = api_client.get(tampered_url)
    assert r3.status_code == 403
    
    # Expired url logic testing - manually construct expired url
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    urllib.parse.parse_qs(parsed.query)
    filename = r.json()["filename"]
    
    from server import _build_signed_url
    expired_url = _build_signed_url(filename, expires_sec=-100)
    
    r4 = api_client.get(expired_url)
    assert r4.status_code == 403

@patch("server.send_moment")
def test_post_moments(mock_send, api_client, api_url, fresh_user):
    mock_send.return_value = {"status": "sent"}
    h = fresh_user["headers"]
    
    # Create parent
    r = api_client.post(f"{api_url}/parents", json={
        "name": "Mom", "relationship": "mother", "phone": "+919000000000",
        "language": "en", "timezone": "Asia/Kolkata"
    }, headers=h)
    pid = r.json()["id"]
    
    # Text only
    r = api_client.post(f"{api_url}/moments", json={
        "parent_id": pid,
        "text": "Hello mom",
        "image_urls": []
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "sent"
    
    # 1 image
    r = api_client.post(f"{api_url}/moments", json={
        "parent_id": pid,
        "text": "Hello mom",
        "image_urls": ["url1"]
    }, headers=h)
    assert r.status_code == 200
    
    # 2 images
    r = api_client.post(f"{api_url}/moments", json={
        "parent_id": pid,
        "text": "Hello mom",
        "image_urls": ["url1", "url2"]
    }, headers=h)
    assert r.status_code == 200
    
    # Invalid parent
    r = api_client.post(f"{api_url}/moments", json={
        "parent_id": "000000000000000000000000",
        "text": "Hello mom",
        "image_urls": []
    }, headers=h)
    assert r.status_code == 404
