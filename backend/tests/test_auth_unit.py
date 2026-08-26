import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from bson import ObjectId

from auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    serialize,
    validate_csrf_token,
    _extract_token,
    revoke_token,
    _is_token_blacklisted,
)
from fastapi import Request, HTTPException
import jwt

def test_hash_verify_password():
    pwd = "my_secure_password"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrong", hashed) is False

@patch("auth._secret", return_value="test_secret")
def test_create_tokens(mock_secret):
    access = create_access_token("user1", "test@test.com", "user")
    payload = jwt.decode(access, "test_secret", algorithms=["HS256"])
    assert payload["sub"] == "user1"
    assert payload["email"] == "test@test.com"
    assert payload["role"] == "user"
    assert payload["type"] == "access"
    assert "jti" in payload

    refresh = create_refresh_token("user1", "test@test.com", "user")
    payload_ref = jwt.decode(refresh, "test_secret", algorithms=["HS256"])
    assert payload_ref["type"] == "refresh"
    assert "jti" in payload_ref

def test_serialize():
    oid = ObjectId()
    now = datetime.now(timezone.utc)
    doc = {
        "_id": oid,
        "password_hash": "secret",
        "created_at": now,
        "other": "value"
    }
    res = serialize(doc)
    assert res["id"] == str(oid)
    assert "_id" not in res
    assert "password_hash" not in res
    assert res["created_at"] == now.isoformat()
    assert res["other"] == "value"

@pytest.mark.asyncio
async def test_validate_csrf_token():
    # Skips GET/HEAD/OPTIONS
    req_get = MagicMock(spec=Request)
    req_get.method = "GET"
    await validate_csrf_token(req_get) # should not raise

    # Bearer bypass
    req_post_bearer = MagicMock(spec=Request)
    req_post_bearer.method = "POST"
    req_post_bearer.headers = {"Authorization": "Bearer some_token"}
    await validate_csrf_token(req_post_bearer) # should not raise

    # Enforces on POST/PUT/DELETE
    req_post = MagicMock(spec=Request)
    req_post.method = "POST"
    req_post.headers = {}
    req_post.cookies = {}
    with pytest.raises(HTTPException, match="CSRF token missing"):
        await validate_csrf_token(req_post)

    # Cookie-header mismatch
    req_post_mismatch = MagicMock(spec=Request)
    req_post_mismatch.method = "POST"
    req_post_mismatch.headers = {"X-CSRF-Token": "token1", "Authorization": ""}
    req_post_mismatch.cookies = {"csrf_token": "token2"}
    with pytest.raises(HTTPException, match="Invalid CSRF token"):
        await validate_csrf_token(req_post_mismatch)

    # Valid match
    req_post_match = MagicMock(spec=Request)
    req_post_match.method = "POST"
    req_post_match.headers = {"X-CSRF-Token": "token1", "Authorization": ""}
    req_post_match.cookies = {"csrf_token": "token1"}
    await validate_csrf_token(req_post_match) # should not raise

def test_extract_token():
    # cookie
    req_cookie = MagicMock(spec=Request)
    req_cookie.cookies = {"access_token": "token_c"}
    req_cookie.headers = {}
    assert _extract_token(req_cookie) == "token_c"

    # header
    req_header = MagicMock(spec=Request)
    req_header.cookies = {}
    req_header.headers = {"Authorization": "Bearer token_h"}
    assert _extract_token(req_header) == "token_h"

@pytest.mark.asyncio
@patch("auth.db")
async def test_revoke_token_is_blacklisted(mock_db):
    mock_db.jwt_blacklist.find_one.return_value = {"jti": "some_jti"}
    assert await _is_token_blacklisted("some_jti") is True

    mock_db.jwt_blacklist.find_one.return_value = None
    assert await _is_token_blacklisted("other_jti") is False

    await revoke_token("my_jti", datetime.now(timezone.utc))
    assert mock_db.jwt_blacklist.update_one.called
