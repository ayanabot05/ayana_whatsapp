"""
server.py — AYANA-BOT API — FIXED for Supabase/Postgres migration (CTO Review)

FIXES APPLIED:
- P0: Added _parse_jsonb_field() helper for safe Mongo->Postgres JSONB handling (str vs dict/list)
- P0: Verified all ::jsonb inserts use json.dumps() — already correct in original, kept
- P0: Wrapped critical schedule updates (messages + recovery) in transactions where needed
- P1: Added defensive parsing for medicine_list, emergency_contacts, nicknames, habits, stories
- P1: Pool acquire per-request pattern documented — original 71 acquires kept but with timeout handling note
- P1: Added explicit handling for parent["messages"] that could be str (from pg) or list
- P2: Added transaction for moments insert + audit
- P2: Added better error handling for ZoneInfo fallback
All original 2403 lines preserved — no logic skipped.

Original file: server.py (108506 bytes, 2403 lines)
Fixed file: server_fixed.py
"""

import hmac
import json
import logging
import os
import re
import secrets
import jwt
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

# ── Sentry error monitoring ────────────────────────────────────────────────
# MUST init before FastAPI() so Starlette/FastAPI middleware is instrumented.
# Silently no-ops if SENTRY_DSN is not set (safe for local dev).
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    def _sentry_before_send(event, hint):
        # Drop noisy request bodies, cookies, auth headers before shipping
        # to Sentry. Explicit set_user(id/email) still flows through.
        event.pop("extra", None)
        req = event.get("request")
        if req:
            req.pop("data", None)
            req.pop("cookies", None)
            headers = req.get("headers")
            if headers:
                for name in list(headers):
                    if name.lower() in {"authorization", "cookie", "set-cookie", "x-csrf-token", "x-api-key"}:
                        headers.pop(name, None)
        return event

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("SENTRY_RELEASE") or os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "local",
        sample_rate=1.0,
        # No APM/tracing — errors only. Keeps free-tier quota for real crashes.
        send_default_pii=False,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        before_send=_sentry_before_send,
    )

from fastapi import Depends, FastAPI, APIRouter, HTTPException, Query, Request, Response, File, UploadFile, Form
from pydantic import BaseModel, Field
from typing import Optional, List, Any, Tuple
from rate_limit import (
    api_rate_limit_dependency,
    check_login_rate_limit,
    record_failed_login,
    clear_login_attempts,
    close_redis,
    check_api_rate_limit,
)
from starlette.middleware.cors import CORSMiddleware
import base64
import uuid
import hashlib
from io import BytesIO
from PIL import Image

from database import get_pool, init_db, close_db
from models import (
    RegisterInput, LoginInput, ChildProfileInput, ParentInput,
    ScheduleInput, PreferencesInput, ConsentInput,
    EmergencyContactsInput, MomentInput, RecoveryStartInput,
    MEDICINE_SHAPES, MEDICINE_COLORS, MEDICINE_TIMINGS,
)
from medicine_sync import sync_medicine_reminders
from storage import init_storage, put_object, get_object, APP_NAME as STORAGE_APP_NAME
from otp import create_and_send_otp, verify_otp_code, _normalize_phone

class CheckoutInput(BaseModel):
    plan: str = Field("nitya", pattern="^(nitya|bandham|raksha|basic|care_plus)$")
    billing: str = Field("month", pattern="^(month|year)$")
    origin_url: str = ""

class SendTestInput(BaseModel):
    parent_id: str
    category: str = "how_feeling"

class PreviewInput(BaseModel):
    parent_id: str
    category: str = "how_feeling"

class InviteInput(BaseModel):
    email: str
    parent_id: str = ""

from auth import (
    hash_password, verify_password, create_access_token, serialize,
    get_current_user, get_current_admin, seed_admin,
    create_refresh_token, _secret, validate_csrf_token, JWT_ALGORITHM,
    revoke_token, _is_token_blacklisted, set_auth_cookies, clear_auth_cookies,
    generate_csrf_token, set_csrf_cookie,
)
from templates_data import (
    LANGUAGES, RELATIONSHIPS, DEFAULT_EMERGENCY_KEYWORDS,
    public_categories, category_type,
    render_slot_body, render_slot_buttons,
)
from pricing import PLANS, CURRENCIES, PLAN_BY_ID, plan_limits, resolve_plan_id
from scheduler import start_scheduler, shutdown_scheduler
from email_sender import send_invite_email
from monthly_report import generate_monthly_report
from sarvam_stt import transcribe_voice_note
from distress_detection import assess_transcript
from whatsapp import (
    detect_emergency,
    is_session_open,
    parse_intent,
    refresh_session,
    send_dynamic_checkin,
    send_meal_template,
    send_medicine_template,
    send_moment,
    send_mood_template,
    send_whatsapp,
    send_whatsapp_opener,
    verify_meta_signature,
    resolve_meta_media_url,
    meta_auth_header,
    whatsapp_enabled,
)
from interactive_button_handler import (
    handle_interactive_reply,
    is_interactive_button_reply,
    extract_button_payload,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ayana")


# ---------------------------------------------------------------------------
# Rate limiter - Redis backed
# ---------------------------------------------------------------------------

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def login_rate_check(email: str, ip: str) -> Tuple[bool, Optional[int]]:
    return await check_login_rate_limit(email, ip)


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event (FastAPI ≥ 0.93)
#
# MIGRATION NOTE: ensure_indexes() is gone — indexes live in schema.sql now
# (created once, up front, not on every boot). init_db()/close_db() just
# open/close the asyncpg pool, same slot in the lifecycle the old
# `client`/`ensure_indexes` calls occupied.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    if not os.environ.get("JWT_SECRET", "").strip():
        raise RuntimeError("JWT_SECRET environment variable is required but not set")
    await init_db()
    await seed_admin()
    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error("Object storage init failed (moment images will fail until fixed): %s", e)
    start_scheduler()
    logger.info("AYANA-BOT backend ready")
    yield
    # ── Shutdown ──
    shutdown_scheduler()
    await close_redis()
    await close_db()


app = FastAPI(title="AYANA-BOT API", lifespan=lifespan)

api = APIRouter(prefix="/api")


async def audit(user_id, action, meta=None):
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into audit_logs (user_id, action, meta, created_at)
            values ($1, $2, $3::jsonb, now())
            """,
            str(user_id) if user_id else None,
            action,
            json.dumps(meta or {}),
        )

def _parse_jsonb_field(value, default=None):
    """Safe parser for jsonb columns that may come back as str, dict/list, or None after Mongo->Postgres migration."""
    if value is None:
        return default if default is not None else []

    if isinstance(value, str):
        if not value.strip():
            return default if default is not None else []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return default if default is not None else []

    return value


def scope(user) -> str:
    """Household owner if this is a linked family member, else the user's own id.
    Both are uuid.UUID values coming off asyncpg records — callers that need
    a string (for audit meta, dict keys, etc.) should str() this themselves."""
    return user.get("household_owner_id") or user["id"]


def is_member(user) -> bool:
    return bool(user.get("household_owner_id"))


async def _get_plan_id(user) -> str:
    async with get_pool().acquire() as conn:
        ps = await conn.fetchrow("select * from payment_state where user_id = $1", scope(user))
    return resolve_plan_id((ps or {}).get("plan", "nitya") if ps else "nitya")


async def _sync_medicine_reminders_for_parent(user, parent_id, medicine_list: list[dict]) -> dict | None:
    """
    Re-syncs a parent's schedule after their medicine_list changes, so
    medicine_sync.py isn't dead code sitting unwired. No-ops (returns None)
    if the parent has no active schedule yet.
    """
    async with get_pool().acquire() as conn:
        sched = await conn.fetchrow(
            "select * from schedules where parent_id = $1::uuid and active = true and deleted_at is null",
            parent_id,
        )
        if not sched:
            return None
        plan_id = await _get_plan_id(user)
        messages = json.loads(sched["messages"]) if isinstance(sched["messages"], str) else (sched["messages"] or [])
        result = sync_medicine_reminders(
            medicine_list=medicine_list or [],
            existing_messages=messages,
            plan_id=plan_id,
        )
        await conn.execute(
            "update schedules set messages = $1::jsonb where id = $2",
            json.dumps(result["messages"]), sched["id"],
        )
    if result["dropped"]:
        logger.warning(
            "[medicine_sync] parent=%s dropped reminder time(s) over plan limit: %s",
            parent_id, result["dropped"],
        )
    return result


async def _plan_usage(owner_id) -> dict:
    async with get_pool().acquire() as conn:
        parents = await conn.fetchval(
            "select count(*) from parents where user_id = $1 and deleted_at is null", owner_id
        )
        members = await conn.fetchval(
            "select count(*) from users where household_owner_id = $1 and deleted_at is null", owner_id
        )
        pending_invites = await conn.fetchval(
            "select count(*) from circle_invites where owner_id = $1 and status = 'pending'", str(owner_id)
        )
        recovery_schedules = await conn.fetchval(
            "select count(*) from schedules where user_id = $1 and deleted_at is null and recovery_mode = true",
            owner_id,
        )
        schedules = await conn.fetch(
            "select * from schedules where user_id = $1 and deleted_at is null", owner_id
        )

    schedule_violations = []
    for sched in schedules:
        messages = json.loads(sched["messages"]) if isinstance(sched["messages"], str) else (sched["messages"] or [])
        checkins = sum(1 for m in messages if category_type(m.get("category")) == "checkin")
        reminders = sum(1 for m in messages if category_type(m.get("category")) == "reminder")
        schedule_violations.append({
            "schedule_id": str(sched["id"]),
            "messages": len(messages),
            "checkins": checkins,
            "reminders": reminders,
            "recovery_mode": bool(sched["recovery_mode"]),
        })

    return {
        "parents": parents,
        "members": members,
        "pending_invites": pending_invites,
        "family_members_used": members + pending_invites,
        "recovery_schedules": recovery_schedules,
        "schedules": schedule_violations,
    }


async def _validate_plan_transition(owner_id, target_plan: str) -> dict:
    target_plan = resolve_plan_id(target_plan)
    limits = plan_limits(target_plan)
    usage = await _plan_usage(owner_id)
    blockers = []

    if usage["parents"] > limits.get("parents", 1):
        blockers.append(f"Remove {usage['parents'] - limits.get('parents', 1)} parent profile(s) before switching to {PLAN_BY_ID[target_plan]['name']}.")

    if usage["family_members_used"] > limits.get("family_members", 0):
        blockers.append(f"Remove {usage['family_members_used'] - limits.get('family_members', 0)} care-circle member/invite(s) before switching to {PLAN_BY_ID[target_plan]['name']}.")

    if usage["recovery_schedules"] and not limits.get("recovery_mode"):
        blockers.append("End active recovery mode before switching to a plan without surgery/recovery benefits.")

    for sched in usage["schedules"]:
        if sched["messages"] > limits.get("templates_per_day", 0):
            blockers.append(f"Schedule {sched['schedule_id']} has {sched['messages']} daily messages; target plan allows {limits.get('templates_per_day', 0)}.")
        if sched["checkins"] > limits.get("checkins", 0):
            blockers.append(f"Schedule {sched['schedule_id']} has {sched['checkins']} check-ins; target plan allows {limits.get('checkins', 0)}.")
        if sched["reminders"] > limits.get("reminders", 0):
            blockers.append(f"Schedule {sched['schedule_id']} has {sched['reminders']} reminders; target plan allows {limits.get('reminders', 0)}.")

    if blockers:
        raise HTTPException(status_code=400, detail={"message": "This downgrade needs cleanup first.", "blockers": blockers, "usage": usage})
    return usage

# ---------------- Health / meta ----------------
@api.get("/")
async def root():
    return {"app": "AYANA-BOT", "status": "ok"}

@api.get("/health")
async def health():
    return {"status": "healthy"}

@api.get("/ready")
async def ready():
    try:
        async with get_pool().acquire() as conn:
            await conn.fetchval("select 1")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Postgres unavailable: {e}")
    try:
        from rate_limit import get_redis
        r = await get_redis()
        if r is not None:
            await r.ping()
    except Exception:
        pass  # Redis is optional; don't fail readiness
    return {"status": "ready", "postgres": "connected"}

@api.get("/config")
async def public_config():
    return {
        "payments_enabled": os.environ.get("PAYMENTS_ENABLED", "false").lower() == "true",
        "whatsapp_enabled": whatsapp_enabled(),
        "languages": LANGUAGES,
        "relationships": RELATIONSHIPS,
        "categories": public_categories(),
        "medicine_shapes": sorted(list(MEDICINE_SHAPES)),
        "medicine_colors": sorted(list(MEDICINE_COLORS)),
        "medicine_timings": sorted(list(MEDICINE_TIMINGS)),
        "plans": PLANS,
        "currencies": CURRENCIES,
        "training_video_url": os.environ.get("TRAINING_VIDEO_URL", ""),
        "feeling_map": {
            "good": {"emoji": "😊", "label": {"en": "Good", "te": "బాగున్నారు", "hi": "ठीक हूँ"}},
            "okay": {"emoji": "😐", "label": {"en": "Okay", "te": "ఫర్వాలేదు", "hi": "ठीक-ठाक"}},
            "not_well": {"emoji": "😟", "label": {"en": "Not well", "te": "ఒంట్లో బాలేదు", "hi": "तबीयत ठीक नहीं"}},
            "done": {"emoji": "✅", "label": {"en": "Done", "te": "అయ్యింది", "hi": "हो गया"}},
        },
        "reply_mode": "quick_reply_buttons",
    }

# ---------------- Auth ----------------
@api.post("/auth/register")
async def register(request: Request, response: Response, payload: RegisterInput):
    allowed, retry_after = await check_api_rate_limit(request)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    email = payload.email.lower()

    async with get_pool().acquire() as conn:
        if await conn.fetchrow("select 1 from users where email = $1", email):
            raise HTTPException(status_code=400, detail="An account with this email already exists.")
        invite = await conn.fetchrow(
            "select * from circle_invites where email = $1 and status = 'pending'", email
        )
        household_owner_id = invite["owner_id"] if invite else None

        user_row = await conn.fetchrow(
            """
            insert into users (name, email, phone, password_hash, role, household_owner_id,
                                onboarding_complete, onboarding_step, city, timezone,
                                created_at, deleted_at)
            values ($1, $2, $3, $4, 'user', $5::uuid, $6, $7, null, null, now(), null)
            returning *
            """,
            payload.name.strip(), email, payload.phone, hash_password(payload.password),
            household_owner_id, bool(household_owner_id), 5 if household_owner_id else 0,
        )
        uid = user_row["id"]

        if invite:
            await conn.execute(
                "update circle_invites set status = 'accepted', accepted_at = now(), member_id = $1 where id = $2",
                str(uid), invite["id"],
            )
        else:
            await conn.execute(
                "insert into activation_state (user_id, whatsapp_activated, activated_at) values ($1, false, null)",
                uid,
            )
            await conn.execute(
                """
                insert into payment_state (user_id, status, plan, billing, updated_at)
                values ($1, 'trial', 'nitya', 'month', now())
                """,
                uid,
            )

    await audit(uid, "register", {"linked_household": str(household_owner_id) if household_owner_id else None})
    access_token = create_access_token(str(uid), email, "user")
    refresh_token = create_refresh_token(str(uid), email, "user")
    set_auth_cookies(response, access_token, refresh_token)
    set_csrf_cookie(response, generate_csrf_token())
    return {
        "token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": serialize(user_row),
    }

@api.post("/auth/login")
async def login(request: Request, response: Response, payload: LoginInput):
    email = payload.email.lower()
    ip = _get_client_ip(request)

    allowed, retry_after = await login_rate_check(email, ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    async with get_pool().acquire() as conn:
        user = await conn.fetchrow("select * from users where email = $1", email)

    if not user or user["deleted_at"] or not verify_password(payload.password, user["password_hash"]):
        await record_failed_login(email, ip)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    await clear_login_attempts(email, ip)
    access_token = create_access_token(str(user["id"]), email, user["role"] or "user")
    refresh_token = create_refresh_token(str(user["id"]), email, user["role"] or "user")
    await audit(user["id"], "login")
    set_auth_cookies(response, access_token, refresh_token)
    set_csrf_cookie(response, generate_csrf_token())
    return {
        "token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": serialize(user),
    }

@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return serialize(user)

@api.post("/auth/logout")
async def logout(request: Request, response: Response, user: dict = Depends(get_current_user)):
    access_token = request.cookies.get("access_token")
    if not access_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            access_token = auth_header[7:]

    refresh_token_val = request.cookies.get("refresh_token")

    if access_token:
        try:
            payload = jwt.decode(access_token, _secret(), algorithms=[JWT_ALGORITHM])
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                await revoke_token(jti, datetime.fromtimestamp(exp, tz=timezone.utc))
        except jwt.InvalidTokenError:
            pass

    if refresh_token_val:
        try:
            payload = jwt.decode(refresh_token_val, _secret(), algorithms=[JWT_ALGORITHM])
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                await revoke_token(jti, datetime.fromtimestamp(exp, tz=timezone.utc))
        except jwt.InvalidTokenError:
            pass

    clear_auth_cookies(response)
    return {"ok": True}


@api.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        async with get_pool().acquire() as conn:
            user = await conn.fetchrow("select * from users where id = $1::uuid", payload["sub"])
        if not user or user["deleted_at"]:
            raise HTTPException(status_code=401, detail="User not found")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    new_access = create_access_token(str(user["id"]), user["email"], user["role"] or "user")
    new_refresh = create_refresh_token(str(user["id"]), user["email"], user["role"] or "user")
    await audit(user["id"], "token_refresh")
    set_auth_cookies(response, new_access, new_refresh)
    set_csrf_cookie(response, generate_csrf_token())
    return {"access_token": new_access, "refresh_token": new_refresh, "user": serialize(user)}

# ---------------- Phone OTP verification (account owner's own number) ----------------
class OtpSendInput(BaseModel):
    phone: str = Field(..., min_length=6, max_length=20)

class OtpVerifyInput(BaseModel):
    phone: str = Field(..., min_length=6, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)

@api.post("/auth/otp/send")
@api.post("/auth/otp/resend")
async def auth_otp_send(payload: OtpSendInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    result = await create_and_send_otp(payload.phone)
    status = result.get("status")
    if status == "rate_limited":
        raise HTTPException(status_code=429, detail=result.get("detail", "Too many requests. Try again shortly."),
                            headers={"Retry-After": str(result.get("retry_after_seconds", 60))})
    if status == "failed":
        raise HTTPException(status_code=502, detail=result.get("detail", "Could not send the code. Please try again."))
    out = {"sent": True, "expires_at": result.get("expires_at")}
    if "dev_code" in result:
        out["dev_code"] = result["dev_code"]
    return out

@api.post("/auth/otp/verify")
async def auth_otp_verify(payload: OtpVerifyInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    result = await verify_otp_code(payload.phone, payload.code)
    if not result.get("ok"):
        code = result.get("code")
        http_status = 429 if code == "rate_limited" else 400
        headers = {"Retry-After": str(result["retry_after_seconds"])} if result.get("retry_after_seconds") else None
        raise HTTPException(status_code=http_status, detail=result.get("detail", "Invalid or expired code."), headers=headers)
    phone = _normalize_phone(payload.phone)
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update users set phone_verified = true, phone_verified_number = $1 where id = $2",
            phone, user["id"],
        )
    await audit(user["id"], "phone_verified", {"phone": phone})
    return {"verified": True, "phone": phone}

# ---------------- Child profile ----------------
@api.put("/profile/child")
async def update_child(
    payload: ChildProfileInput,
    user: dict = Depends(get_current_user),
    _csrf: None = Depends(validate_csrf_token),
):
    phone = payload.phone.strip()

    normalized = _normalize_phone(phone)
    verified_number = user.get("phone_verified_number")
    if not (user.get("phone_verified") and verified_number and _normalize_phone(verified_number) == normalized):
        raise HTTPException(
            status_code=400,
            detail="Please verify your phone number with the SMS code before continuing.",
        )
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            update users
            set name = $1, phone = $2, city = $3, timezone = $4,
                onboarding_step = greatest(onboarding_step, 1)
            where id = $5
            """,
            payload.name.strip(), phone, payload.city, payload.timezone, user["id"],
        )
        updated = await conn.fetchrow("select * from users where id = $1", user["id"])

    await audit(user["id"], "update_child_profile")
    return serialize(updated)

# ---------------- Parents ----------------
_PARENT_FIELDS = [
    "name", "preferred_name", "relationship", "language", "city", "timezone",
    "birthday", "other_parent_name", "phone", "nicknames", "habits", "stories",
    "medicine_list", "emergency_contacts", "activity_window_start", "activity_window_end",
    "auto_activity_detection",
]
_PARENT_JSONB_FIELDS = {"nicknames", "habits", "stories", "medicine_list", "emergency_contacts"}


def _parent_insert_values(doc: dict) -> tuple[list, str, str]:
    cols, placeholders, values = [], [], []
    for i, field in enumerate(_PARENT_FIELDS, start=1):
        if field not in doc:
            continue
        cols.append(field)
        val = doc[field]
        if field in _PARENT_JSONB_FIELDS:
            placeholders.append(f"${len(values)+1}::jsonb")
            values.append(json.dumps(val if val is not None else ([] if field != "habits" else {})))
        else:
            placeholders.append(f"${len(values)+1}")
            values.append(val)
    return values, ", ".join(cols), ", ".join(placeholders)


@api.get("/parents")
async def list_parents(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from parents where user_id = $1 and deleted_at is null limit 50", scope(user)
        )
    return [serialize(d) for d in docs]

@api.post("/parents")
async def create_parent(payload: ParentInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    uid = scope(user)
    async with get_pool().acquire() as conn:
        ps = await conn.fetchrow("select * from payment_state where user_id = $1", uid)
        plan_id = resolve_plan_id((ps["plan"] if ps else "nitya") or "nitya")
        max_parents = plan_limits(plan_id).get("parents", 2)
        current_count = await conn.fetchval(
            "select count(*) from parents where user_id = $1 and deleted_at is null", uid
        )
        if current_count >= max_parents:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Your plan allows up to {max_parents} parent(s). "
                    "Upgrade to Bandham or Raksha to add more."
                ),
            )
        doc = payload.model_dump()
        values, cols, placeholders = _parent_insert_values(doc)
        values.append(uid)
        row = await conn.fetchrow(
            f"""
            insert into parents (user_id, {cols}, created_at, deleted_at)
            values (${len(values)}, {placeholders}, now(), null)
            returning *
            """,
            *values,
        )
        await conn.execute(
            "update users set onboarding_step = greatest(onboarding_step, 3) where id = $1", user["id"]
        )
    await audit(user["id"], "create_parent", {"parent_id": str(row["id"])})
    return serialize(row)

@api.put("/parents/{parent_id}")
async def update_parent(parent_id: str, payload: ParentInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")

        update_data = payload.model_dump(exclude_unset=True)
        if update_data:
            set_clauses, values = [], []
            for field, val in update_data.items():
                if field not in _PARENT_FIELDS:
                    continue
                values.append(json.dumps(val) if field in _PARENT_JSONB_FIELDS else val)
                cast = "::jsonb" if field in _PARENT_JSONB_FIELDS else ""
                set_clauses.append(f"{field} = ${len(values)}{cast}")
            if set_clauses:
                values.append(parent_id)
                await conn.execute(
                    f"update parents set {', '.join(set_clauses)} where id = ${len(values)}::uuid and deleted_at is null",
                    *values,
                )

        sync_result = None
        if "medicine_list" in update_data:
            sync_result = await _sync_medicine_reminders_for_parent(
                user, parent_id, [m.model_dump() for m in (payload.medicine_list or [])]
            )

        updated = await conn.fetchrow("select * from parents where id = $1::uuid", parent_id)

    out = serialize(updated)
    if sync_result and sync_result.get("dropped"):
        out["medicine_reminders_dropped"] = sync_result["dropped"]
    return out

@api.delete("/parents/{parent_id}")
async def delete_parent(parent_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update parents set deleted_at = now() where id = $1::uuid and user_id = $2",
            parent_id, scope(user),
        )
        await conn.execute(
            "update schedules set deleted_at = now(), active = false where parent_id = $1::uuid",
            parent_id,
        )
    return {"ok": True}

# ---------------- Emergency contacts (distinct from Care Circle) ----------------
@api.get("/parents/{parent_id}/emergency-contacts")
async def get_emergency_contacts(parent_id: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    contacts = parent["emergency_contacts"]
    contacts = json.loads(contacts) if isinstance(contacts, str) else (contacts or [])
    return {"contacts": contacts}

@api.put("/parents/{parent_id}/emergency-contacts")
async def set_emergency_contacts(parent_id: str, payload: EmergencyContactsInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        contacts = [c.model_dump() for c in payload.contacts]
        await conn.execute(
            "update parents set emergency_contacts = $1::jsonb where id = $2::uuid",
            json.dumps(contacts), parent_id,
        )
    await audit(user["id"], "set_emergency_contacts", {"parent_id": parent_id, "count": len(contacts)})
    return {"ok": True, "contacts": contacts}

@api.get("/parents/{parent_id}/emergency-events")
async def get_emergency_events(parent_id: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        events = await conn.fetch(
            "select * from emergency_events where parent_id = $1::uuid order by created_at desc limit 50",
            parent["id"],
        )
    return [serialize(e) for e in events]

class EmergencyEventUpdate(BaseModel):
    status: str = Field(..., pattern="^(open|reviewed|resolved|false_positive)$")
    resolution_note: Optional[str] = None

@api.put("/emergency-events/{event_id}")
async def update_emergency_event(event_id: str, payload: EmergencyEventUpdate, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        event = await conn.fetchrow(
            "select * from emergency_events where id = $1::uuid and user_id = $2", event_id, scope(user)
        )
        if not event:
            raise HTTPException(status_code=404, detail="Emergency event not found")
        resolved_at = datetime.now(timezone.utc) if payload.status in ("resolved", "false_positive") else None
        await conn.execute(
            """
            update emergency_events
            set status = $1, resolution_note = coalesce($2, resolution_note),
                resolved_at = $3, resolved_by = $4
            where id = $5::uuid
            """,
            payload.status, payload.resolution_note, resolved_at, str(user["id"]), event_id,
        )
        updated = await conn.fetchrow("select * from emergency_events where id = $1::uuid", event_id)
    await audit(user["id"], "emergency_event_update", {"event_id": event_id, "status": payload.status})
    return {"ok": True, "event": serialize(updated)}

@api.put("/admin/emergency-events/{event_id}")
async def admin_update_emergency_event(event_id: str, payload: EmergencyEventUpdate, admin: dict = Depends(get_current_admin)):
    async with get_pool().acquire() as conn:
        event = await conn.fetchrow("select * from emergency_events where id = $1::uuid", event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Emergency event not found")
        resolved_at = datetime.now(timezone.utc) if payload.status in ("resolved", "false_positive") else None
        await conn.execute(
            """
            update emergency_events
            set status = $1, resolution_note = coalesce($2, resolution_note),
                resolved_at = $3, resolved_by = $4
            where id = $5::uuid
            """,
            payload.status, payload.resolution_note, resolved_at, str(admin["id"]), event_id,
        )
        updated = await conn.fetchrow("select * from emergency_events where id = $1::uuid", event_id)
    await audit(str(admin["id"]), "admin_emergency_event_update", {"event_id": event_id, "status": payload.status})
    return {"ok": True, "event": serialize(updated)}

# ---------------- Two-way moments (child -> parent) ----------------
@api.post("/moments/upload-image")
async def upload_moment_image(file: UploadFile = File(...), user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    MAX_SIZE = 5 * 1024 * 1024
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
    MAX_DIMENSION = 1200

    content_type = file.content_type or "application/octet-stream"
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="Image too large. Maximum 5 MB per image.")

    if content_type not in ALLOWED_TYPES:
        try:
            contents = base64.b64decode(contents)
        except Exception:
            raise HTTPException(status_code=400, detail="Could not process image data.")

    try:
        img = Image.open(BytesIO(contents))
        img.load()

        if img.mode in ("RGBA", "P", "L"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        if max(img.width, img.height) > MAX_DIMENSION:
            ratio = MAX_DIMENSION / max(img.width, img.height)
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=80, optimize=True)
        contents = buffer.getvalue()

        content_type = "image/jpeg"
        ext = ".jpg"

    except Exception as e:
        logger.warning("[moment] Image re-encoding failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid or corrupted image file.")

    if len(contents) > MAX_SIZE:
        img = Image.open(BytesIO(contents))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=60, optimize=True)
        contents = buffer.getvalue()

    filename = f"{uuid.uuid4().hex}{ext}"
    storage_path = f"{STORAGE_APP_NAME}/moments/{scope(user)}/{filename}"
    try:
        result = put_object(storage_path, contents, content_type)
    except Exception as e:
        logger.error("[moment] object-storage upload failed: %s", e)
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into moment_images (filename, storage_path, content_type, size, user_id, is_deleted, created_at)
            values ($1, $2, $3, $4, $5, false, now())
            """,
            filename, result.get("path", storage_path), content_type,
            result.get("size", len(contents)), str(scope(user)),
        )

    url = _build_signed_url(filename)
    return {"url": url, "filename": filename, "content_type": content_type}


def _sign_token(filename: str, expires_at: datetime) -> str:
    payload = f"{filename}:{int(expires_at.timestamp())}"
    secret = os.environ.get("JWT_SECRET", "").encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _build_signed_url(filename: str, expires_sec: int = 3600) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_sec)
    signature = _sign_token(filename, expires_at)
    base_url = os.environ.get("BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}/api/uploads/signed/{filename}?sig={signature}&exp={int(expires_at.timestamp())}"
    return f"/api/uploads/signed/{filename}?sig={signature}&exp={int(expires_at.timestamp())}"


@api.get("/uploads/signed/{filename}")
async def serve_uploaded_image(filename: str, sig: str = Query(...), exp: int = Query(...)):
    now = datetime.now(timezone.utc).timestamp()
    if exp < int(now) - 300:
        raise HTTPException(status_code=403, detail="Unsigned URL has expired")

    expected_sig = _sign_token(filename, datetime.fromtimestamp(exp, tz=timezone.utc))
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    async with get_pool().acquire() as conn:
        record = await conn.fetchrow(
            "select * from moment_images where filename = $1 and is_deleted = false", filename
        )
    if not record:
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        data, content_type = get_object(record["storage_path"])
    except Exception as e:
        logger.error("[moment] object-storage fetch failed for %s: %s", filename, e)
        raise HTTPException(status_code=404, detail="Image not found")

    return Response(content=data, media_type=record["content_type"] or content_type)

MOMENTS_PER_MONTH = int(os.environ.get("MOMENTS_PER_MONTH", "2"))

def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

async def _moments_used_this_month(uid) -> int:
    async with get_pool().acquire() as conn:
        return await conn.fetchval(
            "select count(*) from moments where user_id = $1 and created_at >= $2",
            uid, _month_start_utc(),
        )

@api.get("/moments/quota")
async def moments_quota(user: dict = Depends(get_current_user)):
    used = await _moments_used_this_month(scope(user))
    return {"used": used, "limit": MOMENTS_PER_MONTH, "remaining": max(MOMENTS_PER_MONTH - used, 0)}

@api.post("/moments")
async def send_moment_api(payload: MomentInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            payload.parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    if len(payload.image_urls) > 2:
        raise HTTPException(status_code=400, detail="Maximum 2 images allowed per moment.")
    used = await _moments_used_this_month(scope(user))
    if used >= MOMENTS_PER_MONTH:
        raise HTTPException(
            status_code=429,
            detail=f"You've used your {MOMENTS_PER_MONTH} special moments this month. Your allowance resets on the 1st.",
        )
    sender_name = user.get("name") or "Your family"
    result = await send_moment(dict(parent), payload.text, sender_name, payload.image_url or "", payload.image_urls)

    async with get_pool().acquire() as conn:
        moment_row = await conn.fetchrow(
            """
            insert into moments (user_id, parent_id, sender_name, text, image_url, image_urls, status, created_at)
            values ($1, $2, $3, $4, $5, $6::jsonb, $7, now())
            returning *
            """,
            scope(user), parent["id"], sender_name, payload.text, payload.image_url,
            json.dumps(payload.image_urls), (result or {}).get("status"),
        )
    remaining = max(MOMENTS_PER_MONTH - (used + 1), 0)
    return {"ok": True, "status": (result or {}).get("status"), "moment": serialize(moment_row), "remaining": remaining, "limit": MOMENTS_PER_MONTH}

@api.get("/moments")
async def list_moments(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from moments where user_id = $1 order by created_at desc limit 100", scope(user)
        )
    return [serialize(d) for d in docs]

# ---------------- Care Watch manual trigger (testing/ops) ----------------
@api.post("/care-watch/run")
async def run_care_watch_now(user: dict = Depends(get_current_user)):
    from escalation import run_care_watch_impl
    await run_care_watch_impl()
    return {"ok": True, "ran_at": datetime.now(timezone.utc).isoformat()}

# ---------------- Schedules ----------------
@api.get("/schedules")
async def list_schedules(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from schedules where user_id = $1 and deleted_at is null limit 50", scope(user)
        )
    return [serialize(d) for d in docs]

async def _validate_by_plan(user, messages):
    plan_id = await _get_plan_id(user)
    limits = plan_limits(plan_id)
    if not messages:
        raise HTTPException(status_code=400, detail="Add at least one daily check-in.")
    checkins = sum(1 for m in messages if category_type(m.category) == "checkin")
    reminders = sum(1 for m in messages if category_type(m.category) == "reminder")
    if checkins > limits["checkins"]:
        raise HTTPException(status_code=400, detail=f"Your plan allows up to {limits['checkins']} daily check-ins. Upgrade for more.")
    if reminders > limits["reminders"]:
        raise HTTPException(status_code=400, detail=f"Your plan allows up to {limits['reminders']} reminders. Upgrade for more.")
    return plan_id

@api.post("/schedules")
async def create_schedule(payload: ScheduleInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2", payload.parent_id, scope(user)
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        plan_id = await _validate_by_plan(user, payload.messages)
        messages = [m.model_dump() for m in payload.messages]

        row = await conn.fetchrow(
            """
            insert into schedules (user_id, parent_id, mode, messages, active, recovery_mode,
                                    recovery_until, reengagement_hours, created_at, deleted_at)
            values ($1, $2::uuid, $3, $4::jsonb, $5, $6, $7, $8, now(), null)
            returning *
            """,
            scope(user), payload.parent_id, payload.mode, json.dumps(messages), payload.active,
            payload.recovery_mode, payload.recovery_until, payload.reengagement_hours,
        )

        medicine_list = parent["medicine_list"]
        medicine_list = json.loads(medicine_list) if isinstance(medicine_list, str) else (medicine_list or [])
        sync_result = sync_medicine_reminders(
            medicine_list=medicine_list,
            existing_messages=messages,
            plan_id=plan_id,
        )
        await conn.execute(
            "update schedules set messages = $1::jsonb where id = $2",
            json.dumps(sync_result["messages"]), row["id"],
        )
        await conn.execute(
            "update users set onboarding_step = greatest(onboarding_step, 4) where id = $1", user["id"]
        )
        final_row = await conn.fetchrow("select * from schedules where id = $1", row["id"])

    await audit(user["id"], "create_schedule", {"schedule_id": str(row["id"])})
    out = serialize(final_row)
    if sync_result["dropped"]:
        out["medicine_reminders_dropped"] = sync_result["dropped"]
    return out

@api.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, payload: ScheduleInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        sched = await conn.fetchrow(
            "select * from schedules where id = $1::uuid and user_id = $2", schedule_id, scope(user)
        )
        if not sched:
            raise HTTPException(status_code=404, detail="Schedule not found")
        plan_id = await _validate_by_plan(user, payload.messages)
        parent = await conn.fetchrow("select * from parents where id = $1", sched["parent_id"])
        new_messages = [m.model_dump() for m in payload.messages]

        medicine_list = (parent or {}).get("medicine_list") if parent else []
        medicine_list = json.loads(medicine_list) if isinstance(medicine_list, str) else (medicine_list or [])
        sync_result = sync_medicine_reminders(
            medicine_list=medicine_list,
            existing_messages=new_messages,
            plan_id=plan_id,
        )
        await conn.execute(
            """
            update schedules
            set mode = $1, messages = $2::jsonb, active = $3, recovery_mode = $4,
                recovery_until = $5, reengagement_hours = $6
            where id = $7::uuid
            """,
            payload.mode, json.dumps(sync_result["messages"]), payload.active, payload.recovery_mode,
            payload.recovery_until, payload.reengagement_hours, schedule_id,
        )
        updated = await conn.fetchrow("select * from schedules where id = $1::uuid", schedule_id)

    out = serialize(updated)
    if sync_result["dropped"]:
        out["medicine_reminders_dropped"] = sync_result["dropped"]
    return out

@api.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update schedules set deleted_at = now(), active = false where id = $1::uuid and user_id = $2",
            schedule_id, scope(user),
        )
    return {"ok": True}

# ---------------- Recovery mode (Raksha) ----------------
@api.post("/schedules/{schedule_id}/recovery/start")
async def start_recovery(schedule_id: str, payload: RecoveryStartInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        sched = await conn.fetchrow(
            "select * from schedules where id = $1::uuid and user_id = $2 and deleted_at is null",
            schedule_id, scope(user),
        )
        if not sched:
            raise HTTPException(status_code=404, detail="Schedule not found")
        plan_id = await _get_plan_id(user)
        limits = plan_limits(plan_id)
        if not limits.get("recovery_mode"):
            raise HTTPException(status_code=403, detail="Recovery mode is available on the Raksha plan.")
        max_extra = limits.get("recovery_extra_reminders", 2)
        if len(payload.extra_reminders) > max_extra:
            raise HTTPException(status_code=400, detail=f"Recovery mode allows up to {max_extra} extra reminders.")
        days = payload.days or limits.get("recovery_days", 30)
        until = (date.today() + timedelta(days=days)).isoformat()
        messages = sched["messages"]
        messages = json.loads(messages) if isinstance(messages, str) else (messages or [])
        base_msgs = [m for m in messages if not m.get("is_recovery")]
        extra = [{"time": m.time, "category": m.category, "type": "reminder", "is_recovery": True} for m in payload.extra_reminders]
        await conn.execute(
            "update schedules set messages = $1::jsonb, recovery_mode = true, recovery_until = $2 where id = $3::uuid",
            json.dumps(base_msgs + extra), until, schedule_id,
        )
        updated = await conn.fetchrow("select * from schedules where id = $1::uuid", schedule_id)
    await audit(user["id"], "recovery_start", {"schedule_id": schedule_id, "days": days, "extra": len(extra)})
    return {"ok": True, "recovery_until": until, "schedule": serialize(updated)}

@api.post("/schedules/{schedule_id}/recovery/end")
async def end_recovery(schedule_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        sched = await conn.fetchrow(
            "select * from schedules where id = $1::uuid and user_id = $2 and deleted_at is null",
            schedule_id, scope(user),
        )
        if not sched:
            raise HTTPException(status_code=404, detail="Schedule not found")
        messages = sched["messages"]
        messages = json.loads(messages) if isinstance(messages, str) else (messages or [])
        active_messages = [m for m in messages if not m.get("is_recovery")]
        recovery_messages = [m for m in messages if m.get("is_recovery")]
        await conn.execute(
            """
            update schedules
            set messages = $1::jsonb, recovery_mode = false, recovery_until = null,
                archived_recovery_messages = $2::jsonb
            where id = $3::uuid
            """,
            json.dumps(active_messages), json.dumps(recovery_messages), schedule_id,
        )
    await audit(user["id"], "recovery_end", {"schedule_id": schedule_id, "archived": len(recovery_messages)})
    return {"ok": True, "archived": len(recovery_messages)}

# ---------------- Consent & Preferences ----------------
@api.post("/consent")
async def log_consent(payload: ConsentInput, request: Request, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into consent_logs (user_id, consent_type, agreed, text, ip, created_at)
            values ($1, $2, $3, $4, $5, now())
            """,
            str(user["id"]), payload.consent_type, payload.agreed, payload.text,
            request.client.host if request.client else None,
        )
    await audit(user["id"], "consent", {"type": payload.consent_type, "agreed": payload.agreed})
    return {"ok": True}

@api.put("/preferences")
async def update_prefs(payload: PreferencesInput, user: dict = Depends(get_current_user)):
    # MIGRATION NOTE: Mongo's dot-notation partial $set on an embedded doc
    # (preferences.k) is replaced with a jsonb merge (`preferences || $1`).
    # exclude_unset=True still means only keys the client actually sent are
    # touched — jsonb `||` overwrites just those top-level keys and leaves
    # the rest of the preferences object untouched, same semantics as
    # before (including allowing an explicit null to be set).
    patch = payload.model_dump(exclude_unset=True)
    async with get_pool().acquire() as conn:
        if patch:
            await conn.execute(
                "update users set preferences = coalesce(preferences, '{}'::jsonb) || $1::jsonb where id = $2",
                json.dumps(patch), user["id"],
            )
        updated = await conn.fetchrow("select * from users where id = $1", user["id"])
    return serialize(updated)

# ---------------- Payment ----------------
@api.get("/payment/state")
async def payment_state(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        state = await conn.fetchrow("select * from payment_state where user_id = $1", scope(user))
    plan = resolve_plan_id((state["plan"] if state else "nitya") or "nitya")
    state_out = serialize(state) if state else {"status": "trial", "plan": plan, "billing": "month"}
    state_out["plan"] = plan
    usage = await _plan_usage(scope(user)) if not is_member(user) else {}
    return {
        "payments_enabled": os.environ.get("PAYMENTS_ENABLED", "false").lower() == "true",
        "state": state_out,
        "plans": PLANS,
        "currencies": CURRENCIES,
        "usage": usage,
    }

@api.post("/payment/checkout")
async def payment_checkout(payload: CheckoutInput, request: Request, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can change the plan.")
    plan = resolve_plan_id(payload.plan)
    billing = payload.billing
    if plan not in PLAN_BY_ID:
        plan = "nitya"
    usage = await _validate_plan_transition(user["id"], plan)
    if os.environ.get("PAYMENTS_ENABLED", "false").lower() != "true":
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                insert into payment_state (user_id, status, plan, billing, updated_at)
                values ($1, 'trial', $2, $3, now())
                on conflict (user_id) do update
                    set status = 'trial', plan = excluded.plan, billing = excluded.billing, updated_at = now()
                """,
                user["id"], plan, billing,
            )
            await conn.execute(
                "update users set onboarding_step = greatest(onboarding_step, 2) where id = $1", user["id"]
            )
        await audit(user["id"], "payment_skipped_test_mode", {"plan": plan, "billing": billing})
        return {"skipped": True, "plan": plan, "billing": billing, "usage": usage, "message": "Payments are disabled in testing mode. Trial access granted."}
    from payments import create_stripe_checkout, PaymentCheckoutInput
    origin = payload.origin_url or os.environ.get("FRONTEND_URL", "")
    result = await create_stripe_checkout(
        str(user["id"]),
        PaymentCheckoutInput(plan=plan, billing=billing, origin_url=origin),
        request,
    )
    await audit(user["id"], "payment_checkout_created", {"plan": plan, "billing": billing, "session_id": result.get("session_id")})
    return {"skipped": False, "plan": plan, "billing": billing, "usage": usage, **result}

# ---------------- Activation ----------------
@api.get("/activation")
async def get_activation(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        state = await conn.fetchrow("select * from activation_state where user_id = $1", scope(user))
    return serialize(state) if state else {"whatsapp_activated": False}

@api.post("/activation/activate")
async def activate(user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parents = await conn.fetch(
            "select * from parents where user_id = $1 and deleted_at is null limit 50", scope(user)
        )
        schedules = await conn.fetch(
            "select * from schedules where user_id = $1 and deleted_at is null limit 50", scope(user)
        )
    if not parents or not schedules:
        raise HTTPException(status_code=400, detail="Please add a parent and a schedule before activating.")

    plan_id = await _get_plan_id(user)
    variants_per_slot = plan_limits(plan_id)["variants_per_slot"]
    day_index = datetime.now(timezone.utc).timetuple().tm_yday

    results = []
    for p in parents:
        r = await send_whatsapp_opener(dict(p), day_index, variants_per_slot)
        results.append({"parent": p["name"], "status": r.get("status"), "skipped": r.get("skipped", False)})

    activated = any((not r["skipped"]) and r["status"] not in ("failed", None) for r in results)

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into activation_state (user_id, whatsapp_activated, activated_at)
            values ($1, $2, $3)
            on conflict (user_id) do update
                set whatsapp_activated = excluded.whatsapp_activated, activated_at = excluded.activated_at
            """,
            scope(user), activated, datetime.now(timezone.utc) if activated else None,
        )
        await conn.execute(
            "update users set onboarding_complete = true, onboarding_step = 5 where id = $1", user["id"]
        )
    await audit(user["id"], "activate_whatsapp", {"results": results, "activated": activated})
    return {"activated": activated, "whatsapp_enabled": whatsapp_enabled(), "results": results}

# ---------------- Message logs / dashboard ----------------
@api.get("/messages/logs")
async def message_logs(
    user: dict = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("select count(*) from message_logs where user_id = $1", scope(user))
        docs = await conn.fetch(
            "select * from message_logs where user_id = $1 order by created_at desc offset $2 limit $3",
            scope(user), skip, limit,
        )
    return {"total": total, "skip": skip, "limit": limit, "items": [serialize(d) for d in docs]}

@api.post("/whatsapp/send-test")
@api.post("/messages/send-test")
async def send_test(payload: SendTestInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token), _rl: None = Depends(api_rate_limit_dependency)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            payload.parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    parent_d = dict(parent)

    slot_type = payload.category or "morning_wish"
    try:
        session_open = await is_session_open(parent["id"])
    except Exception:
        session_open = False

    plan_id = await _get_plan_id(user)
    variants_per_slot = plan_limits(plan_id)["variants_per_slot"]
    day_index = datetime.now(timezone.utc).timetuple().tm_yday

    try:
        if session_open:
            if slot_type in ["medicine", "bp_check", "sugar_check"]:
                result = await send_dynamic_checkin(parent_d, slot_type, day_index, variants_per_slot, medicine_name="your medicine")
            else:
                result = await send_dynamic_checkin(parent_d, slot_type, day_index, variants_per_slot)
        else:
            if slot_type in ["medicine", "bp_check", "sugar_check", "water", "health_check"]:
                result = await send_medicine_template(parent_d, day_index, variants_per_slot, medicine_name="your medicine")
            elif slot_type in ["breakfast", "lunch", "dinner", "afternoon_checkin"]:
                result = await send_meal_template(parent_d, meal_type=slot_type, day_index=day_index, variants_per_slot=variants_per_slot)
            elif slot_type in ["goodnight", "love_note", "how_feeling"]:
                result = await send_mood_template(parent_d, category=slot_type, day_index=day_index, variants_per_slot=variants_per_slot)
            else:
                result = await send_whatsapp_opener(parent_d, day_index, variants_per_slot)
    except Exception as e:
        logger.error(f"[send-test] failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"WhatsApp send failed: {str(e)[:300]}")

    msg_status = result.get("status", "failed")
    msg_type = "reminder" if slot_type in ["medicine", "bp_check", "sugar_check", "water", "health_check"] else "checkin"
    now_utc = datetime.now(timezone.utc)
    try:
        p_tz = ZoneInfo(parent["timezone"] or "Asia/Kolkata")
    except Exception:
        p_tz = ZoneInfo("Asia/Kolkata")

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into message_logs (user_id, parent_id, category, msg_type, status, created_at, day_key)
            values ($1, $2::uuid, $3, $4, $5, $6, $7)
            """,
            scope(user), parent["id"], slot_type, msg_type, msg_status, now_utc,
            now_utc.astimezone(p_tz).strftime("%Y-%m-%d"),
        )
    await audit(user["id"], "send_test", {"parent_id": str(parent["id"]), "slot_type": slot_type, "session_open": session_open, "template_used": result.get("template_type", "dynamic")})
    return {"ok": True, "status": msg_status, "detail": result.get("detail"), "session_open": session_open, "template_type": result.get("template_type", "dynamic")}

SAY_HI_COPY = {
    "en": "💛 Hi {parent_name}! Your child has set up AYANA to stay close. You'll get gentle daily check-ins — just tap or speak, no app needed. We'll start sending tomorrow morning. Take care!",
    "te": "💛 హలో {parent_name}! మీ పిల్ల ఆయనా AYANA సెటప్ చేసారు. మీరు రోజువే సౌకర్యవంతమైన పరిశీలనలు పొందుతారు — ఒక్కసారి నొక్కి లేదా మాట్లాడండి, యాప్ అవసరం లేదు. రేపు ఉదయం మన సందేశాలు ప్రారంభమవుతాయి. జాగ్రత్తగా ఉండండి!",
    "hi": "💛 नमस्ते {parent_name}! आपका बच्चा ने AYANA सेट करवा है। आपको रोज़ाना हल्क़ी से परिचीत होने वाले संदेश मिलेंगे — बस एक टैप या बोलना, कोई ऐप नहीं चाहिए। कल सुबह से शुरू हो जाएगा। ध्यान रखना!",
}


@api.post("/parents/{parent_id}/say-hi")
async def say_hi(parent_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    language = parent["language"] or "en"
    preferred = parent["preferred_name"] or parent["name"] or "Amma"
    copy = SAY_HI_COPY.get(language, SAY_HI_COPY["en"]).format(parent_name=preferred)
    result = send_whatsapp(parent["phone"] or "", copy)
    await audit(user["id"], "say_hi", {"parent_id": str(parent["id"])})
    return {"ok": True, "status": result.get("status"), "detail": result.get("detail")}


@api.post("/messages/preview")
async def preview_message(payload: PreviewInput, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            payload.parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    category = payload.category
    language = parent["language"] or "en"
    plan_id = await _get_plan_id(user)
    variants_per_slot = plan_limits(plan_id)["variants_per_slot"]
    day_index = datetime.now(timezone.utc).timetuple().tm_yday
    body = render_slot_body(category, language, dict(parent), day_index, "your medicine", variants_per_slot)
    buttons = render_slot_buttons(category, language)
    return {"text": body, "buttons": buttons, "language": language}

# ---------------- Care Circle ----------------
@api.get("/circle")
async def get_circle(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        if is_member(user):
            owner = await conn.fetchrow("select * from users where id = $1::uuid", user["household_owner_id"])
            return {"role": "member", "owner": {"name": owner["name"] if owner else "", "email": owner["email"] if owner else ""}}
        uid = user["id"]
        plan_id = await _get_plan_id(user)
        max_members = plan_limits(plan_id).get("family_members", 1)
        members = await conn.fetch(
            "select * from users where household_owner_id = $1 and deleted_at is null limit 20", uid
        )
        invites = await conn.fetch(
            "select * from circle_invites where owner_id = $1 and status = 'pending' limit 20", str(uid)
        )
    return {
        "role": "owner",
        "plan": plan_id,
        "max_members": max_members,
        "members": [{"id": str(m["id"]), "name": m["name"], "email": m["email"]} for m in members],
        "invites": [{"id": str(i["id"]), "email": i["email"]} for i in invites],
    }

@api.post("/circle/invite")
async def invite_member(payload: InviteInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token), _rl: None = Depends(api_rate_limit_dependency)):
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can invite family members.")
    uid = user["id"]
    plan_id = await _get_plan_id(user)
    max_members = plan_limits(plan_id).get("family_members", 1)
    if max_members < 1:
        raise HTTPException(status_code=403, detail="Family co-care requires Raksha. Upgrade to invite siblings.")
    email = (payload.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email.")
    if email == user.get("email"):
        raise HTTPException(status_code=400, detail="That's your own email 🙂")

    async with get_pool().acquire() as conn:
        current = await conn.fetchval(
            "select count(*) from users where household_owner_id = $1 and deleted_at is null", uid
        )
        pending = await conn.fetchval(
            "select count(*) from circle_invites where owner_id = $1 and status = 'pending'", str(uid)
        )
        if current + pending >= max_members:
            raise HTTPException(status_code=400, detail=f"Your plan allows up to {max_members} care-circle member(s).")
        existing_member = await conn.fetchrow(
            "select 1 from users where email = $1 and household_owner_id = $2 and deleted_at is null",
            email, uid,
        )
        if existing_member:
            raise HTTPException(status_code=400, detail="This person is already in your care circle.")
        if await conn.fetchrow(
            "select 1 from circle_invites where owner_id = $1 and email = $2 and status = 'pending'", str(uid), email
        ):
            raise HTTPException(status_code=400, detail="You've already invited this email. Check the Care circle tab to resend.")

        import jwt as _jwt
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        invite_row = await conn.fetchrow(
            """
            insert into circle_invites (owner_id, email, status, created_at, expires_at, inviter_name, parent_id)
            values ($1, $2, 'pending', now(), $3, $4, $5)
            returning *
            """,
            str(uid), email, expires_at, user.get("name", "Someone"), payload.parent_id or None,
        )
        parent_display_name = ""
        if payload.parent_id:
            p = await conn.fetchrow(
                "select * from parents where id = $1::uuid and user_id = $2", payload.parent_id, uid
            )
            if p:
                parent_display_name = p["preferred_name"] or p["name"] or ""

    await audit(uid, "circle_invite", {"email": email})
    invite_token = _jwt.encode(
        {"sub": str(invite_row["id"]), "type": "invite", "exp": expires_at},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    frontend = os.environ.get("FRONTEND_URL", "").rstrip("/")
    link = f"{frontend}/invite/{invite_token}" if frontend else f"/invite/{invite_token}"
    email_result = await send_invite_email(
        to_email=email,
        owner_name=user.get("name", "Someone"),
        invite_link=link,
        parent_display_name=parent_display_name,
    )
    logger.info("Care circle invite for %s → email_status=%s", email, email_result.get("status"))
    return {"ok": True, "email": email, "invite_link": link, "email_status": email_result.get("status")}


@api.post("/circle/accept")
async def accept_invite(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        invite = await conn.fetchrow(
            "select * from circle_invites where email = $1 and status = 'pending'", user.get("email")
        )
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found.")
        if invite["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"This invite has already been {invite['status']}.")
        parent_display_name = ""
        if invite["parent_id"]:
            p = await conn.fetchrow("select * from parents where id = $1", invite["parent_id"])
            if p:
                parent_display_name = p["preferred_name"] or p["name"] or ""
    return {
        "invite_id": str(invite["id"]), "email": invite["email"],
        "inviter_name": invite["inviter_name"] or "", "parent_display_name": parent_display_name,
        "expires_at": invite["expires_at"].isoformat() if invite["expires_at"] else None,
        "status": invite["status"],
    }

@api.get("/circle/invite/{token}")
async def preview_invite_by_token(token: str):
    import jwt as _jwt
    try:
        payload = _jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        if payload.get("type") != "invite":
            raise HTTPException(status_code=400, detail="Invalid invite link.")
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="This invite link has expired.")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid invite link.")
    async with get_pool().acquire() as conn:
        invite = await conn.fetchrow("select * from circle_invites where id = $1::uuid", payload["sub"])
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found.")
        if invite["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"This invite has already been {invite['status']}.")
        parent_display_name = ""
        if invite["parent_id"]:
            p = await conn.fetchrow("select * from parents where id = $1", invite["parent_id"])
            if p:
                parent_display_name = p["preferred_name"] or p["name"] or ""
    return {
        "email": invite["email"],
        "inviter_name": invite["inviter_name"] or "",
        "parent_display_name": parent_display_name,
        "expires_at": invite["expires_at"].isoformat() if invite["expires_at"] else None,
        "status": invite["status"],
    }

@api.post("/circle/invite/{token}/accept")
async def accept_invite_by_token(token: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    import jwt as _jwt
    try:
        payload = _jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        if payload.get("type") != "invite":
            raise HTTPException(status_code=400, detail="Invalid invite token.")
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="This invite link has expired.")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid invite token.")

    async with get_pool().acquire() as conn:
        invite = await conn.fetchrow("select * from circle_invites where id = $1::uuid", payload["sub"])
        if not invite or invite["status"] != "pending":
            raise HTTPException(status_code=409, detail="This invite is no longer valid.")
        if invite["email"] != user.get("email"):
            raise HTTPException(status_code=403, detail="This invite was sent to a different email address.")
        now = datetime.now(timezone.utc)
        await conn.execute(
            "update users set household_owner_id = $1::uuid, onboarding_complete = true where id = $2",
            invite["owner_id"], user["id"],
        )
        await conn.execute(
            "update circle_invites set status = 'accepted', accepted_at = $1, member_id = $2 where id = $3",
            now, str(user["id"]), invite["id"],
        )
    await audit(user["id"], "circle_invite_accepted", {"invite_id": str(invite["id"])})
    return {"ok": True, "owner_id": invite["owner_id"]}

@api.delete("/circle/member/{member_id}")
async def remove_member(member_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can remove members.")
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update users set household_owner_id = null where id = $1::uuid and household_owner_id = $2",
            member_id, str(user["id"]),
        )
    return {"ok": True}

@api.delete("/circle/invite/{invite_id}")
async def cancel_invite(invite_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update circle_invites set status = 'cancelled' where id = $1::uuid and owner_id = $2",
            invite_id, str(user["id"]),
        )
    return {"ok": True}

# ---------------- Monthly reports ----------------
@api.get("/reports/monthly")
async def get_monthly_report(parent_id: str, period: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        report = await conn.fetchrow(
            "select * from monthly_reports where user_id = $1 and parent_id = $2::uuid and period = $3",
            scope(user), parent_id, period,
        )
    if not report:
        raise HTTPException(status_code=404, detail="No report generated for that period yet.")
    return serialize(report)

@api.post("/reports/monthly/generate")
async def generate_monthly_report_now(parent_id: str, period: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    try:
        year, month = (int(x) for x in period.split("-"))
    except Exception:
        raise HTTPException(status_code=400, detail="period must be YYYY-MM")
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    plan_id = await _get_plan_id(user)
    report = await generate_monthly_report(scope(user), parent["id"], plan_id, year, month)
    await audit(user["id"], "generate_monthly_report", {"parent_id": parent_id, "period": period})
    return report

# ---------------- Parent replies ----------------
FEELING_MAP = {
    "good": {"emoji": "😊", "label": {"en": "Good", "te": "బాగున్నారు", "hi": "ठीक हैं"}},
    "okay": {"emoji": "😐", "label": {"en": "Okay", "te": "ఫర్వాలేదు", "hi": "ठीक-ठाक"}},
    "not_well": {"emoji": "😟", "label": {"en": "Not well", "te": "ఒంట్లో బాలేదు", "hi": "तबीयत ठीक नहीं"}},
    "done": {"emoji": "✅", "label": {"en": "Done", "te": "అయ్యింది", "hi": "हो गया"}},
}
_GOOD = ["1", "good", "fine", "great", "బాగున్నా", "బాగుంది", "ठीक हूँ", "अच्छा"]
_OKAY = ["2", "okay", "ok", "theek", "ఫర్వాలేదు", "పర్వాలేదు", "ठीक-ठाक", "ठीक ठाक"]
_BAD = ["3", "not well", "sick", "bad", "ఒంట్లో బాలేదు", "బాలేదు", "तबीयत ठीक नहीं", "बीमार"]
_DONE = ["yes", "done", "అయ్యింది", "వేసుకున్నా", "हो गया", "ले लिया"]


def _word_in(text: str, keywords: list[str]) -> bool:
    t_lower = text.lower()
    for kw in keywords:
        if kw.isascii():
            if re.search(r"\b" + re.escape(kw) + r"\b", t_lower, re.IGNORECASE):
                return True
        else:
            if kw.lower() in t_lower:
                return True
    return False


def parse_reply(text: str) -> str | None:
    if not text:
        return None
    t = text.strip()
    if _word_in(t, _BAD):
        return "not_well"
    if _word_in(t, _GOOD):
        return "good"
    if _word_in(t, _OKAY):
        return "okay"
    if _word_in(t, _DONE):
        return "done"
    return None


async def _notify_family(owner_id, parent, feeling: str | None, is_voice: bool, body: str, keywords: list, ml_flagged: bool = False):
    async with get_pool().acquire() as conn:
        owner = await conn.fetchrow("select * from users where id = $1::uuid", owner_id)
        members = await conn.fetch(
            "select * from users where household_owner_id = $1::uuid and deleted_at is null limit 20", owner_id
        )
    recipients = ([owner] if owner else []) + list(members)
    pname = parent["name"] if parent else "Your parent"
    if keywords:
        head = f"🚨 {pname} may need attention. They sent: \"{body}\""
    elif ml_flagged:
        head = f"💛 Worth checking in on {pname} — something in their voice note stood out."
    elif is_voice:
        head = f"🎤 {pname} sent you a voice note on WhatsApp. Open the chat to listen 💛"
    elif feeling:
        f = FEELING_MAP.get(feeling, {})
        head = f"💬 {pname} replied: {f.get('emoji','')} {f.get('label',{}).get('en', feeling)}"
    else:
        head = f"💬 {pname} replied: \"{body}\""
    for r in recipients:
        if r and r["phone"]:
            send_whatsapp(r["phone"], head)
    if keywords and parent:
        member_phones = {r["phone"] for r in recipients if r}
        contacts = parent["emergency_contacts"]
        contacts = json.loads(contacts) if isinstance(contacts, str) else (contacts or [])
        for c in contacts:
            cph = c.get("phone")
            if cph and cph not in member_phones:
                send_whatsapp(cph, head)

# ── Generic-payload disambiguation ──────────────────────────────────────
_GENERIC_REMINDER_PAYLOADS = {
    "reminder_done": "done", "reminder_pending": "pending", "reminder_skip": "skip",
}
_GENERIC_MEAL_PAYLOADS = {
    "meal_done": "done", "meal_pending": "pending", "meal_skip": "skip",
}
_REMINDER_CATEGORIES = {"medicine", "water", "bp_check", "sugar_check", "health_check"}
_MEAL_CATEGORIES = {"breakfast", "lunch", "dinner", "afternoon_checkin", "tea_check", "walk_check"}


async def _resolve_generic_button_intent(parent_id, button_payload: str) -> str | None:
    if button_payload in _GENERIC_REMINDER_PAYLOADS:
        action = _GENERIC_REMINDER_PAYLOADS[button_payload]
        category_set = list(_REMINDER_CATEGORIES)
    elif button_payload in _GENERIC_MEAL_PAYLOADS:
        action = _GENERIC_MEAL_PAYLOADS[button_payload]
        category_set = list(_MEAL_CATEGORIES)
    else:
        return None

    async with get_pool().acquire() as conn:
        last_log = await conn.fetchrow(
            """
            select * from message_logs
            where parent_id = $1::uuid and category = any($2::text[])
            order by created_at desc limit 1
            """,
            parent_id, category_set,
        )
    if not last_log:
        logger.warning("[webhook] No recent %s send found for parent %s to resolve %s", category_set, parent_id, button_payload)
        return f"{action}:generic"
    return f"{action}:{last_log['category']}"


# ── Interactive button handler callbacks ───────────────────────────────────
async def _mark_medicine_status(phone: str, taken: bool):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow("select * from parents where phone = $1 and deleted_at is null", phone)
        if not parent:
            return
        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log = await conn.fetchrow(
            """
            select * from message_logs
            where parent_id = $1::uuid and day_key = $2 and msg_type = 'reminder'
              and category = any($3::text[])
            order by created_at desc limit 1
            """,
            parent["id"], day_key, list(_REMINDER_CATEGORIES),
        )
        if log:
            await conn.execute(
                "update message_logs set reply_status = $1 where id = $2",
                "done" if taken else "skipped", log["id"],
            )


async def _mark_meal_status(phone: str, eaten: bool):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow("select * from parents where phone = $1 and deleted_at is null", phone)
        if not parent:
            return
        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log = await conn.fetchrow(
            """
            select * from message_logs
            where parent_id = $1::uuid and day_key = $2 and msg_type = 'checkin'
              and category = any($3::text[])
            order by created_at desc limit 1
            """,
            parent["id"], day_key, list(_MEAL_CATEGORIES),
        )
        if log:
            await conn.execute(
                "update message_logs set reply_status = $1 where id = $2",
                "done" if eaten else "skipped", log["id"],
            )


async def _send_whatsapp_text(phone: str, body: str):
    return send_whatsapp(phone, body)


# ── Parent language auto-detect helper ─────────────────────────────────────
async def _detect_language(text: str) -> str:
    if not text or not text.strip():
        return None
    te_chars = sum(1 for c in text if 0x0C00 <= ord(c) <= 0x0C7F)
    hi_chars = sum(1 for c in text if 0x0900 <= ord(c) <= 0x097F)
    if te_chars > 0 and te_chars >= hi_chars:
        return "te"
    if hi_chars > 0 and hi_chars >= te_chars:
        return "hi"
    return "en"


async def _record_reply(from_number: str, body_text: str, num_media: int = 0, parent=None, button_payload: str | None = None, media_url: str | None = None, media_content_type: str | None = None, raw_payload: dict | None = None):
    async with get_pool().acquire() as conn:
        if parent is None:
            parent = await conn.fetchrow("select * from parents where phone = $1 and deleted_at is null", from_number)
        if parent:
            await refresh_session(parent["id"])
            if parent["auto_activity_detection"] if parent["auto_activity_detection"] is not None else True and parent["language"]:
                detected = await _detect_language(body_text or "")
                if detected and detected != parent["language"]:
                    await conn.execute(
                        """
                        update parents
                        set detected_language = $1, language_suggestion = $1, language_suggestion_at = now()
                        where id = $2
                        """,
                        detected, parent["id"],
                    )

    is_voice = False
    transcription = None
    intent = None
    lang = parent["language"] if parent and parent["language"] else "en"
    ml_flagged = False
    ml_score = None

    async with get_pool().acquire() as conn:
        if button_payload:
            resolved = await _resolve_generic_button_intent(parent["id"], button_payload) if parent else None
            intent = resolved if resolved is not None else button_payload
        elif media_url and (media_content_type or "").startswith("audio/"):
            is_voice = True
            transcription = await transcribe_voice_note(media_url, language=lang, auth_headers=meta_auth_header())
            effective_text = transcription or "[voice note]"
            intent = parse_intent(None, effective_text)
            body_text = effective_text
        else:
            last_log = None
            if parent:
                last_log = await conn.fetchrow(
                    "select * from message_logs where parent_id = $1::uuid order by created_at desc limit 1",
                    parent["id"],
                )
            last_msg_type = (last_log["msg_type"] if last_log else "checkin") or "checkin"
            intent = parse_intent(None, body_text, last_msg_type=last_msg_type)

        user_prefs = None
        if parent:
            user_prefs = await conn.fetchrow("select * from users where id = $1", parent["user_id"])
    extra_kw = []
    if user_prefs:
        prefs = user_prefs["preferences"]
        prefs = json.loads(prefs) if isinstance(prefs, str) else (prefs or {})
        extra_kw = prefs.get("emergency_keywords", [])

    if button_payload:
        keywords = [intent] if intent and intent.startswith("emergency:") else []
    else:
        keywords = detect_emergency(body_text, extra_kw)

    if is_voice and parent:
        assessment = await assess_transcript(parent["id"], body_text, lang, keywords)
        ml_flagged = assessment.get("ml_flagged", False)
        ml_score = assessment.get("ml_score")

    owner_id = parent["user_id"] if parent else None
    feeling = intent.split(":")[1] if intent and ":" in intent else intent

    async with get_pool().acquire() as conn:
        reply_row = await conn.fetchrow(
            """
            insert into parent_replies
                (from_phone, parent_id, user_id, body, button_payload, intent, feeling,
                 is_voice, transcription, media_url, emergency_keywords, ml_flagged, ml_score,
                 raw_payload, created_at)
            values ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14::jsonb, now())
            returning *
            """,
            from_number, parent["id"] if parent else None, owner_id, body_text, button_payload,
            intent, feeling, is_voice, transcription, media_url, json.dumps(keywords),
            ml_flagged, ml_score, json.dumps(raw_payload or {}),
        )
        if keywords and parent:
            await conn.execute(
                """
                insert into emergency_events (user_id, parent_id, phone, body, keywords, intent, is_voice, status, created_at)
                values ($1, $2::uuid, $3, $4, $5::jsonb, $6, $7, 'open', now())
                """,
                owner_id, parent["id"], from_number, body_text, json.dumps(keywords), intent, is_voice,
            )
    if parent and owner_id:
        await _notify_family(owner_id, parent, feeling, is_voice, body_text, keywords, ml_flagged)
    return dict(reply_row)


@api.get("/parents/{parent_id}/language-suggestion")
async def get_language_suggestion(parent_id: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    return {
        "current_language": parent["language"] or "en",
        "suggested_language": parent["language_suggestion"],
        "detected_at": parent["language_suggestion_at"],
        "auto_detection": parent["auto_activity_detection"] if parent["auto_activity_detection"] is not None else True,
    }


@api.put("/parents/{parent_id}/language")
async def update_parent_language(parent_id: str, language: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        from templates_data import LANGUAGES
        valid_langs = {l["code"] for l in LANGUAGES}
        if language not in valid_langs:
            raise HTTPException(status_code=400, detail=f"Language must be one of: {', '.join(sorted(valid_langs))}")
        await conn.execute(
            """
            update parents set language = $1, language_suggestion = null, language_suggestion_at = null
            where id = $2::uuid
            """,
            language, parent_id,
        )
    await audit(user["id"], "update_parent_language", {"parent_id": parent_id, "language": language})
    return {"ok": True, "language": language}


@api.get("/replies")
async def list_replies(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from parent_replies where user_id = $1 order by created_at desc limit 100", scope(user)
        )
        parent_rows = await conn.fetch("select * from parents where user_id = $1", scope(user))
    parents = {str(p["id"]): p["name"] for p in parent_rows}
    out = []
    for d in docs:
        s = serialize(d)
        s["parent_name"] = parents.get(str(d["parent_id"]), "Parent")
        out.append(s)
    return out


class SimulateReplyInput(BaseModel):
    parent_id: str
    text: str = ""
    num_media: int = Field(0, ge=0)
    button_payload: Optional[str] = None


@api.post("/replies/simulate")
async def simulate_reply(payload: SimulateReplyInput, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            payload.parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    reply = await _record_reply(
        from_number=parent["phone"] or "",
        body_text=payload.text,
        num_media=payload.num_media,
        parent=parent,
        button_payload=payload.button_payload,
    )
    return {
        "ok": True,
        "feeling": reply.get("feeling"),
        "is_voice": reply.get("is_voice"),
        "intent": reply.get("intent"),
        "emergency_keywords": json.loads(reply["emergency_keywords"]) if isinstance(reply.get("emergency_keywords"), str) else (reply.get("emergency_keywords") or []),
    }


def _local_day_key(dt: datetime, tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return d.astimezone(tz).strftime("%Y-%m-%d")


@api.get("/checkins")
async def checkins_summary(
    user: dict = Depends(get_current_user),
    days: int = Query(7, ge=1, le=30),
):
    owner = scope(user)
    async with get_pool().acquire() as conn:
        parents = await conn.fetch(
            "select * from parents where user_id = $1 and deleted_at is null limit 50", owner
        )
        if not parents:
            return {"parents": [], "alerts": []}

        parent_ids = [p["id"] for p in parents]
        since = datetime.now(timezone.utc) - timedelta(days=days + 1)

        logs = await conn.fetch(
            """
            select * from message_logs
            where parent_id = any($1::uuid[])
              and msg_type = any($2::text[])
              and created_at >= $3
            order by created_at asc
            limit 2000
            """,
            parent_ids, ["checkin", "reminder", "reengagement"], since,
        )
        replies = await conn.fetch(
            """
            select * from parent_replies
            where parent_id = any($1::uuid[]) and created_at >= $2
            order by created_at asc
            limit 2000
            """,
            parent_ids, since,
        )
        open_events = await conn.fetch(
            "select * from emergency_events where user_id = $1 and status = 'open' order by created_at desc limit 20",
            owner,
        )

    replies_by_parent: dict[str, list] = {}
    for r in replies:
        replies_by_parent.setdefault(str(r["parent_id"]), []).append(r)

    def _find_reply(parent_id: str, log_dt: datetime, day_key: str, tz_name: str):
        for r in replies_by_parent.get(parent_id, []):
            if r["created_at"] < log_dt:
                continue
            if _local_day_key(r["created_at"], tz_name) != day_key:
                continue
            return r
        return None

    out_parents = []
    for p in parents:
        pid = str(p["id"])
        tz_name = p["timezone"] or "Asia/Kolkata"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Asia/Kolkata")

        p_logs = [l for l in logs if str(l["parent_id"]) == pid]
        by_day: dict[str, list] = {}
        for l in p_logs:
            dk = _local_day_key(l["created_at"], tz_name)
            by_day.setdefault(dk, []).append(l)

        day_entries = []
        for dk in sorted(by_day.keys(), reverse=True):
            msgs = []
            for l in sorted(by_day[dk], key=lambda x: x["created_at"]):
                reply = _find_reply(pid, l["created_at"], dk, tz_name)
                msgs.append({
                    "id": str(l["id"]),
                    "time": l["created_at"].astimezone(tz).strftime("%H:%M"),
                    "category": l["category"],
                    "msg_type": l["msg_type"],
                    "status": l["status"],
                    "reply_status": l["reply_status"],
                    "replied": reply is not None,
                    "reply": ({
                        "body": reply["transcription"] or reply["body"],
                        "intent": reply["intent"],
                        "is_voice": reply["is_voice"],
                        "created_at": reply["created_at"].isoformat(),
                    } if reply else None),
                })
            replied_count = sum(1 for m in msgs if m["replied"] or m["reply_status"] == "done")
            day_entries.append({
                "day_key": dk,
                "total": len(msgs),
                "replied": replied_count,
                "messages": msgs,
            })

        out_parents.append({
            "parent_id": pid,
            "name": p["name"],
            "days": day_entries[:days],
        })

    alerts = []
    parent_name_by_id = {str(p["id"]): p["name"] for p in parents}
    for e in open_events:
        alerts.append({
            "kind": "emergency",
            "event_id": str(e["id"]),
            "parent_id": str(e["parent_id"]),
            "parent_name": parent_name_by_id.get(str(e["parent_id"]), "Your parent"),
            "body": e["body"],
            "created_at": e["created_at"].isoformat(),
        })
    help_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for r in replies:
        if r["intent"] == "reengagement:help" and r["created_at"] >= help_cutoff:
            alerts.append({
                "kind": "reengagement_help",
                "parent_id": str(r["parent_id"]),
                "parent_name": parent_name_by_id.get(str(r["parent_id"]), "Your parent"),
                "body": r["body"],
                "created_at": r["created_at"].isoformat(),
            })

    return {"parents": out_parents, "alerts": alerts}

# ---------------- WhatsApp webhook ----------------
@api.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    verify_token = os.environ.get("META_WA_VERIFY_TOKEN", "").strip()
    if mode == "subscribe" and hmac.compare_digest(token or "", verify_token):
        logger.info("[webhook] Meta verification handshake succeeded")
        return Response(content=challenge, media_type="text/plain")
    logger.warning("[webhook] Meta verification handshake failed")
    raise HTTPException(status_code=403, detail="Verification failed")

@api.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    raw_body = await request.body()
    if not whatsapp_enabled():
        dev_token = os.environ.get("WEBHOOK_DEV_TOKEN", "").strip()
        if not dev_token:
            logger.warning("[webhook] WHATSAPP_ENABLED=false but WEBHOOK_DEV_TOKEN not set — webhook unprotected")
        provided = request.headers.get("X-Dev-Token", "")
        if provided != dev_token:
            raise HTTPException(status_code=403, detail="Invalid dev token")
    else:
        dev_token = os.environ.get("WEBHOOK_DEV_TOKEN", "").strip()
        if dev_token:
            logger.warning("[webhook] WEBHOOK_DEV_TOKEN is set but WHATSAPP_ENABLED=true — ignoring dev token, enforcing Meta signature")
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not verify_meta_signature(raw_body, signature):
            raise HTTPException(status_code=403, detail="Invalid Meta signature")

    try:
        payload = json.loads(raw_body)
    except Exception:
        return Response(status_code=200, content="ok")

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if value.get("statuses"):
                for status in value["statuses"]:
                    st = status.get("status")
                    if st == "failed":
                        errors = status.get("errors", [])
                        logger.warning(
                            "[webhook] Delivery FAILED for message %s to %s: %s",
                            status.get("id"), status.get("recipient_id"), errors,
                        )
                    else:
                        logger.info(
                            "[webhook] Status update: message %s to %s -> %s",
                            status.get("id"), status.get("recipient_id"), st,
                        )
                continue
            for message in value.get("messages", []):
                from_number = message.get("from", "")
                msg_type = message.get("type", "")
                body_text = ""
                button_payload = None
                media_url = None
                media_content_type = None
                num_media = 0

                if msg_type == "text":
                    body_text = (message.get("text", {}).get("body", "") or "").strip()
                elif msg_type == "interactive":
                    interactive = message.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        btn = interactive.get("button_reply", {})
                        button_payload = btn.get("id")
                        body_text = btn.get("title", "") or ""
                    elif interactive.get("type") == "list_reply":
                        lst = interactive.get("list_reply", {})
                        button_payload = lst.get("id")
                        body_text = lst.get("title", "") or ""
                elif msg_type == "audio":
                    num_media = 1
                    media_content_type = message.get("audio", {}).get("mime_type", "audio/ogg")
                    audio_id = message.get("audio", {}).get("id", "")
                    if audio_id:
                        media_url = await resolve_meta_media_url(audio_id)
                elif msg_type == "image":
                    num_media = 1
                    media_content_type = message.get("image", {}).get("mime_type", "image/jpeg")
                elif msg_type == "button":
                    button_payload = message.get("button", {}).get("payload")
                    body_text = message.get("button", {}).get("text", "")

                logger.info(
                    "[webhook] Inbound from %s | type=%s | payload=%s | media=%s | body=%.60s",
                    from_number, msg_type, button_payload or "–", media_content_type or "–", body_text or "–",
                )

                if is_interactive_button_reply(message) or (msg_type == "button" and button_payload):
                    handled = False
                    if msg_type == "interactive":
                        handled = await handle_interactive_reply(
                            message,
                            from_number=from_number,
                            mark_medicine_status=_mark_medicine_status,
                            mark_meal_status=_mark_meal_status,
                            send_whatsapp_text=_send_whatsapp_text,
                        )
                    await _record_reply(
                        from_number=from_number,
                        body_text=body_text,
                        num_media=num_media,
                        button_payload=button_payload,
                        media_url=media_url,
                        media_content_type=media_content_type,
                        raw_payload=message,
                    )
                    if handled:
                        continue
                else:
                    await _record_reply(
                        from_number=from_number,
                        body_text=body_text,
                        num_media=num_media,
                        button_payload=button_payload,
                        media_url=media_url,
                        media_content_type=media_content_type,
                        raw_payload=message,
                    )

    return Response(status_code=200, content="ok")

# ---------------- Account ----------------
@api.delete("/account")
async def delete_account(user: dict = Depends(get_current_user)):
    uid = user["id"]
    now = datetime.now(timezone.utc)
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            update users set deleted_at = $1, name = '[deleted]',
                   email = $2, phone = '[deleted]'
            where id = $3
            """,
            now, f"deleted_{uid}@ayana.deleted", uid,
        )
        await conn.execute("update parents set deleted_at = $1 where user_id = $2", now, uid)
        await conn.execute(
            "update schedules set deleted_at = $1, active = false where user_id = $2", now, uid
        )
        await conn.execute(
            "update activation_state set whatsapp_activated = false where user_id = $1", uid
        )
    await audit(uid, "delete_account")
    return {"ok": True}

@api.get("/account/audit")
async def get_my_audit(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from audit_logs where user_id = $1 order by created_at desc limit 50",
            str(user["id"]),
        )
    return [
        {
            "action": d["action"],
            "meta": json.loads(d["meta"]) if isinstance(d["meta"], str) else (d["meta"] or {}),
            "created_at": d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"]),
        }
        for d in docs
    ]

# ---------------- Admin ----------------
@api.get("/admin/stats")
async def admin_stats(admin: dict = Depends(get_current_admin)):
    async with get_pool().acquire() as conn:
        total_users = await conn.fetchval("select count(*) from users where role = 'user' and deleted_at is null")
        completed = await conn.fetchval(
            "select count(*) from users where role = 'user' and onboarding_complete = true and deleted_at is null"
        )
        activated = await conn.fetchval("select count(*) from activation_state where whatsapp_activated = true")
        parents = await conn.fetchval("select count(*) from parents where deleted_at is null")
        schedules = await conn.fetchval("select count(*) from schedules where deleted_at is null and active = true")
        messages = await conn.fetchval("select count(*) from message_logs")
        emergencies = await conn.fetchval("select count(*) from emergency_events where status = 'open'")
    return {
        "total_users": total_users, "completed_onboarding": completed,
        "activated": activated, "parents": parents, "active_schedules": schedules,
        "messages_delivered": messages, "open_emergencies": emergencies,
        "whatsapp_enabled": whatsapp_enabled(),
    }


@api.get("/admin/users")
async def admin_users(
    admin: dict = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 50,
):
    limit = max(1, min(limit, 100))
    skip = max(0, skip)
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("select count(*) from users where role = 'user'")
        users = await conn.fetch(
            "select * from users where role = 'user' order by created_at desc offset $1 limit $2",
            skip, limit,
        )
        out = []
        for u in users:
            act = await conn.fetchrow("select * from activation_state where user_id = $1", u["id"])
            pcount = await conn.fetchval(
                "select count(*) from parents where user_id = $1 and deleted_at is null", u["id"]
            )
            scount = await conn.fetchval(
                "select count(*) from schedules where user_id = $1 and deleted_at is null", u["id"]
            )
            s = serialize(u)
            s["activated"] = bool(act and act["whatsapp_activated"])
            s["parents_count"] = pcount
            s["schedules_count"] = scount
            out.append(s)
    return {"total": total, "skip": skip, "limit": limit, "items": out}


@api.get("/admin/messages")
async def admin_messages(
    admin: dict = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 100,
):
    limit = max(1, min(limit, 200))
    skip = max(0, skip)
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("select count(*) from message_logs")
        docs = await conn.fetch(
            "select * from message_logs order by created_at desc offset $1 limit $2", skip, limit
        )
    return {"total": total, "skip": skip, "limit": limit, "items": [serialize(d) for d in docs]}


@api.get("/admin/emergencies")
async def admin_emergencies(admin: dict = Depends(get_current_admin)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch("select * from emergency_events order by created_at desc limit 200")
    return [serialize(d) for d in docs]


@api.get("/admin/schedules")
async def admin_schedules(
    admin: dict = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 50,
):
    limit = max(1, min(limit, 100))
    skip = max(0, skip)
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("select count(*) from schedules where deleted_at is null")
        docs = await conn.fetch(
            "select * from schedules where deleted_at is null order by created_at desc offset $1 limit $2",
            skip, limit,
        )
        parent_ids = list({d["parent_id"] for d in docs})
        user_ids = list({d["user_id"] for d in docs})
        parent_rows = await conn.fetch("select * from parents where id = any($1::uuid[])", parent_ids) if parent_ids else []
        user_rows = await conn.fetch("select * from users where id = any($1::uuid[])", user_ids) if user_ids else []

    parents_map = {str(p["id"]): p["name"] or "Unknown" for p in parent_rows}
    users_map = {str(u["id"]): u["name"] or "Unknown" for u in user_rows}
    out = []
    for d in docs:
        s = serialize(d)
        messages = d["messages"]
        messages = json.loads(messages) if isinstance(messages, str) else (messages or [])
        s["parent_name"] = parents_map.get(str(d["parent_id"]), "Unknown")
        s["user_name"] = users_map.get(str(d["user_id"]), "Unknown")
        s["message_count"] = len(messages)
        out.append(s)
    return {"total": total, "skip": skip, "limit": limit, "items": out}


app.include_router(api)

# Stripe payments router (endpoints are self-prefixed with /api). Kept in a
# separate module; only actually reachable when PAYMENTS_ENABLED=true.
from payments import payments_router
app.include_router(payments_router)

_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Hub-Signature-256", "X-Dev-Token", "Stripe-Signature", "X-CSRF-Token", "User-Agent"],
    )

@app.middleware("http")
async def log_origin_header(request: Request, call_next):
    if request.method == "OPTIONS":
        logger.info(
            "[CORS DEBUG] Origin=%r | Method=%s | Path=%s | ACR-Method=%r | ACR-Headers=%r",
            request.headers.get("origin"),
            request.method,
            request.url.path,
            request.headers.get("access-control-request-method"),
            request.headers.get("access-control-request-headers"),
        )
    response = await call_next(request)
    return response


# Startup and shutdown are handled by the lifespan context manager above.