import os
import secrets
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from fastapi import HTTPException, Request, Response

from database import get_pool

JWT_ALGORITHM = "HS256"
ACCESS_TTL_MIN = 30       # 30 minutes access token
REFRESH_TTL_DAYS = 7      # 7 days refresh token

COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", ".ayanabott.com")
_IS_LOCAL_DEV = os.environ.get("ENV", "production").lower() in ("dev", "development", "local")


def _cookie_domain() -> str | None:
    return None if _IS_LOCAL_DEV else COOKIE_DOMAIN


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str, role: str) -> str:
    jti = secrets.token_urlsafe(16)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TTL_MIN),
        "type": "access",
        "jti": jti,
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, email: str, role: str) -> str:
    jti = secrets.token_urlsafe(16)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TTL_DAYS)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expires_at,
        "type": "refresh",
        "jti": jti,
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def serialize(record) -> dict | None:
    """
    Turns an asyncpg Record (what every query below returns) into a plain,
    JSON-safe dict for API responses — the Postgres equivalent of the old
    Mongo serialize(): drops password_hash, and converts the two Postgres
    types that don't serialize to JSON on their own (uuid.UUID -> str,
    datetime -> isoformat string). Everything else (text, int, bool, jsonb)
    already comes back JSON-safe from asyncpg.
    """
    if record is None:
        return None
    out = dict(record)
    out.pop("password_hash", None)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif hasattr(v, "hex") and not isinstance(v, (bytes, bytearray, str)):
            # uuid.UUID objects — asyncpg returns these natively for `uuid` columns
            out[k] = str(v)
    return out


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return token


async def _is_token_blacklisted(jti: str) -> bool:
    if not jti:
        return False
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("select 1 from jwt_blacklist where jti = $1", jti)
    return row is not None


async def revoke_token(jti: str, expires_at: datetime):
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into jwt_blacklist (jti, expires_at, revoked_at)
            values ($1, $2, now())
            on conflict (jti) do update
                set expires_at = excluded.expires_at,
                    revoked_at = now()
            """,
            jti, expires_at,
        )


async def get_current_user(request: Request) -> dict:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        jti = payload.get("jti")
        if await _is_token_blacklisted(jti):
            raise HTTPException(status_code=401, detail="Token has been revoked")

        async with get_pool().acquire() as conn:
            user = await conn.fetchrow(
                "select * from users where id = $1::uuid and deleted_at is null",
                payload["sub"],
            )
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(user)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_admin(request: Request) -> dict:
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def seed_admin():
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@ayana.care").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not admin_password:
        raise ValueError(
            "ADMIN_PASSWORD env var is required. Set a strong password (min 8 chars) in your .env file."
        )
    if len(admin_password) < 8:
        raise ValueError("ADMIN_PASSWORD must be at least 8 characters.")

    async with get_pool().acquire() as conn:
        existing = await conn.fetchrow("select * from users where email = $1", admin_email)
        if existing is None:
            await conn.execute(
                """
                insert into users (name, email, phone, password_hash, role,
                                    onboarding_complete, city, timezone, deleted_at)
                values ($1, $2, $3, $4, 'admin', true, null, 'Asia/Kolkata', null)
                """,
                "AYANA Admin", admin_email, "+10000000000", hash_password(admin_password),
            )
        elif not verify_password(admin_password, existing["password_hash"]):
            await conn.execute(
                "update users set password_hash = $1, role = 'admin' where email = $2",
                hash_password(admin_password), admin_email,
            )


# ── CSRF Protection ──────────────────────────────────────────────────────────
# Unchanged from before — no database involved, this is pure cookie/header logic.
_CSRF_COOKIE_NAME = "csrf_token"
_CSRF_HEADER_NAME = "X-CSRF-Token"
_CSRF_TOKEN_BYTES = 32


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(_CSRF_TOKEN_BYTES)


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=True,
        samesite="lax",
        domain=_cookie_domain(),
        path="/",
        max_age=60 * 60 * 24 * 7,
    )


# ── JWT Cookie Helpers ─────────────────────────────────────────────────────────
# Also unchanged — cookies, not database.
_ACCESS_TOKEN_COOKIE = "access_token"
_REFRESH_TOKEN_COOKIE = "refresh_token"


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, max_age_days: int = 7) -> None:
    max_age_seconds = max_age_days * 60 * 60 * 24
    for name, value in (
        (_ACCESS_TOKEN_COOKIE, access_token),
        (_REFRESH_TOKEN_COOKIE, refresh_token),
    ):
        response.set_cookie(
            key=name,
            value=value,
            httponly=True,
            secure=True,
            samesite="lax",
            domain=_cookie_domain(),
            path="/",
            max_age=max_age_seconds,
        )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key=_ACCESS_TOKEN_COOKIE, path="/", domain=_cookie_domain())
    response.delete_cookie(key=_REFRESH_TOKEN_COOKIE, path="/", domain=_cookie_domain())


def get_csrf_token_from_request(request: Request) -> str | None:
    token = request.cookies.get(_CSRF_COOKIE_NAME)
    if token:
        return token
    return request.headers.get(_CSRF_HEADER_NAME)


async def validate_csrf_token(request: Request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return

    cookie_token = request.cookies.get(_CSRF_COOKIE_NAME)
    header_token = request.headers.get(_CSRF_HEADER_NAME)

    if not cookie_token or not header_token:
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing. Please refresh the page and try again.",
        )

    if not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(
            status_code=403,
            detail="Invalid CSRF token. Please refresh the page and try again.",
        )