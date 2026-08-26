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

from bson import ObjectId
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

from database import db, client, ensure_indexes
from models import (
    RegisterInput, LoginInput, ChildProfileInput, ParentInput,
    ScheduleInput, PreferencesInput, ConsentInput,
    EmergencyContactsInput, MomentInput, RecoveryStartInput,
    MEDICINE_SHAPES, MEDICINE_COLORS, MEDICINE_TIMINGS,
)
from medicine_sync import sync_medicine_reminders
from storage import init_storage, put_object, get_object, APP_NAME as STORAGE_APP_NAME

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
# (Handled via api_rate_limit_dependency in individual routes or as global dependency)

def _get_client_ip(request: Request) -> str:
    """Extract client IP, considering proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Rate limiter - Redis backed (see rate_limit.py)
# ---------------------------------------------------------------------------

async def login_rate_check(email: str, ip: str) -> Tuple[bool, Optional[int]]:
    """Delegate to Redis-backed login rate limiter. Returns (allowed, retry_after)."""
    return await check_login_rate_limit(email, ip)


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event (FastAPI ≥ 0.93)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    # Fail fast if JWT_SECRET is not set
    if not os.environ.get("JWT_SECRET", "").strip():
        raise RuntimeError("JWT_SECRET environment variable is required but not set")
    await ensure_indexes()
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
    client.close()


app = FastAPI(title="AYANA-BOT API", lifespan=lifespan)

# Moment images are stored in Emergent object storage (see storage.py) and
# served back through the signed-URL endpoint below — no pod-local disk.

# Rate limiting handled via Redis (rate_limit.py) — see api_rate_limit_dependency
api = APIRouter(prefix="/api")

async def audit(user_id, action, meta=None):
    await db.audit_logs.insert_one({
        "user_id": str(user_id) if user_id else None,
        "action": action,
        "meta": meta or {},
        "created_at": datetime.now(timezone.utc),
    })

def scope(user) -> str:
    return user.get("household_owner_id") or str(user["_id"])

def is_member(user) -> bool:
    return bool(user.get("household_owner_id"))

async def _get_plan_id(user) -> str:
    ps = await db.payment_state.find_one({"user_id": scope(user)})
    return resolve_plan_id((ps or {}).get("plan", "nitya"))

async def _sync_medicine_reminders_for_parent(user, parent_id, medicine_list: list[dict]) -> dict | None:
    """
    Re-syncs a parent's schedule after their medicine_list changes, so
    medicine_sync.py isn't dead code sitting unwired. No-ops (returns None)
    if the parent has no active schedule yet — that's the normal case
    right after parent creation, before the Daily check-ins step has run.
    Returns the sync result dict ({"messages", "synced_times", "dropped"})
    when a schedule was updated, so callers can surface dropped times.
    """
    sched = await db.schedules.find_one({"parent_id": ObjectId(parent_id), "active": True, "deleted_at": None})
    if not sched:
        return None
    plan_id = await _get_plan_id(user)
    result = sync_medicine_reminders(
        medicine_list=medicine_list or [],
        existing_messages=sched.get("messages", []),
        plan_id=plan_id,
    )
    await db.schedules.update_one({"_id": sched["_id"]}, {"$set": {"messages": result["messages"]}})
    if result["dropped"]:
        logger.warning(
            "[medicine_sync] parent=%s dropped reminder time(s) over plan limit: %s",
            parent_id, result["dropped"],
        )
    return result

async def _plan_usage(owner_id: str) -> dict:
    parents = await db.parents.count_documents({"user_id": owner_id, "deleted_at": None})
    members = await db.users.count_documents({"household_owner_id": owner_id, "deleted_at": None})
    pending_invites = await db.circle_invites.count_documents({"owner_id": owner_id, "status": "pending"})
    recovery_schedules = await db.schedules.count_documents({
        "user_id": owner_id,
        "deleted_at": None,
        "recovery_mode": True,
    })

    schedule_violations = []
    schedules = await db.schedules.find({"user_id": owner_id, "deleted_at": None}).to_list(100)
    for sched in schedules:
        messages = sched.get("messages", [])
        checkins = sum(1 for m in messages if category_type(m.get("category")) == "checkin")
        reminders = sum(1 for m in messages if category_type(m.get("category")) == "reminder")
        schedule_violations.append({
            "schedule_id": str(sched["_id"]),
            "messages": len(messages),
            "checkins": checkins,
            "reminders": reminders,
            "recovery_mode": bool(sched.get("recovery_mode")),
        })

    return {
        "parents": parents,
        "members": members,
        "pending_invites": pending_invites,
        "family_members_used": members + pending_invites,
        "recovery_schedules": recovery_schedules,
        "schedules": schedule_violations,
    }

async def _validate_plan_transition(owner_id: str, target_plan: str) -> dict:
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
    """Kubernetes/Docker liveness probe — returns 200 if process is alive."""
    return {"status": "healthy"}

@api.get("/ready")
async def ready():
    """Kubernetes/Docker readiness probe — returns 200 if DB + Redis reachable."""
    # Check MongoDB
    try:
        await db.command("ping")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"MongoDB unavailable: {e}")
    # Check Redis (optional — rate limiting degrades gracefully)
    try:
        from rate_limit import get_redis
        r = await get_redis()
        if r is not None:
            await r.ping()
    except Exception:
        pass  # Redis is optional; don't fail readiness
    return {"status": "ready", "mongodb": "connected"}

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
    # Redis-backed rate limit for register
    allowed, retry_after = await check_api_rate_limit(request)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    invite = await db.circle_invites.find_one({"email": email, "status": "pending"})
    household_owner_id = invite["owner_id"] if invite else None
    doc = {
        "name": payload.name.strip(),
        "email": email,
        "phone": payload.phone,
        "password_hash": hash_password(payload.password),
        "role": "user",
        "household_owner_id": household_owner_id,
        "onboarding_complete": bool(household_owner_id),
        "onboarding_step": 5 if household_owner_id else 0,
        "city": None,
        "timezone": None,
        "created_at": datetime.now(timezone.utc),
        "deleted_at": None,
    }
    res = await db.users.insert_one(doc)
    uid = str(res.inserted_id)
    if invite:
        await db.circle_invites.update_one({"_id": invite["_id"]}, {"$set": {"status": "accepted", "accepted_at": datetime.now(timezone.utc), "member_id": uid}})
    else:
        await db.activation_state.insert_one({"user_id": uid, "whatsapp_activated": False, "activated_at": None})
        await db.payment_state.insert_one({"user_id": uid, "status": "trial", "plan": "nitya", "billing": "month", "updated_at": datetime.now(timezone.utc)})
    await audit(uid, "register", {"linked_household": household_owner_id})
    access_token = create_access_token(uid, email, "user")
    refresh_token = create_refresh_token(uid, email, "user")
    user = await db.users.find_one({"_id": res.inserted_id})
    set_auth_cookies(response, access_token, refresh_token)
    set_csrf_cookie(response, generate_csrf_token())
    return {
        "token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": serialize(user),
    }

@api.post("/auth/login")
async def login(request: Request, response: Response, payload: LoginInput):
    email = payload.email.lower()
    ip = _get_client_ip(request)

    # Check brute-force protection (Redis-backed)
    allowed, retry_after = await login_rate_check(email, ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    user = await db.users.find_one({"email": email})
    if not user or user.get("deleted_at") or not verify_password(payload.password, user["password_hash"]):
        await record_failed_login(email, ip)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Successful login — clear failed attempts
    await clear_login_attempts(email, ip)
    access_token = create_access_token(str(user["_id"]), email, user.get("role", "user"))
    refresh_token = create_refresh_token(str(user["_id"]), email, user.get("role", "user"))
    await audit(str(user["_id"]), "login")
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
    # Extract and revoke both access and refresh tokens
    access_token = request.cookies.get("access_token")
    if not access_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            access_token = auth_header[7:]

    refresh_token = request.cookies.get("refresh_token")

    # Revoke access token if present
    if access_token:
        try:
            payload = jwt.decode(access_token, _secret(), algorithms=[JWT_ALGORITHM])
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                await revoke_token(jti, datetime.fromtimestamp(exp, tz=timezone.utc))
        except jwt.InvalidTokenError:
            pass  # Token already invalid, no need to revoke

    # Revoke refresh token if present
    if refresh_token:
        try:
            payload = jwt.decode(refresh_token, _secret(), algorithms=[JWT_ALGORITHM])
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
    """Exchange a valid refresh token for new access + refresh tokens."""
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
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user or user.get("deleted_at"):
            raise HTTPException(status_code=401, detail="User not found")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Rotate: issue new access + refresh tokens
    new_access = create_access_token(str(user["_id"]), user["email"], user.get("role", "user"))
    new_refresh = create_refresh_token(str(user["_id"]), user["email"], user.get("role", "user"))
    await audit(str(user["_id"]), "token_refresh")
    set_auth_cookies(response, new_access, new_refresh)
    set_csrf_cookie(response, generate_csrf_token())
    return {"access_token": new_access, "refresh_token": new_refresh, "user": serialize(user)}

# ---------------- Child profile ----------------
@api.put("/profile/child") 
async def update_child( 
    payload: ChildProfileInput, 
    user: dict = Depends(get_current_user), 
    _csrf: None = Depends(validate_csrf_token), 
): 
    phone = payload.phone.strip() 
 
    # OTP verification removed for now — phone is saved as submitted,
    # no longer gated on a prior /auth/otp/verify call.
    await db.users.update_one( 
        {"_id": user["_id"]}, 
        {"$set": { 
            "name": payload.name.strip(), 
            "phone": phone, 
            "city": payload.city, 
            "timezone": payload.timezone, 
            "onboarding_step": max(user.get("onboarding_step", 0), 1), 
        }} 
    ) 
 
    await audit(user["_id"], "update_child_profile") 
 
    return serialize( 
        await db.users.find_one({"_id": user["_id"]}) 
    )
# ---------------- Parents ----------------
@api.get("/parents")
async def list_parents(user: dict = Depends(get_current_user)):
    docs = await db.parents.find({"user_id": scope(user), "deleted_at": None}).to_list(50)
    return [serialize(d) for d in docs]

@api.post("/parents")
async def create_parent(payload: ParentInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    uid = scope(user)
    # ── Enforce plan parent limit ──
    ps = await db.payment_state.find_one({"user_id": uid})
    plan_id = resolve_plan_id((ps or {}).get("plan", "nitya"))
    max_parents = plan_limits(plan_id).get("parents", 2)
    current_count = await db.parents.count_documents({"user_id": uid, "deleted_at": None})
    if current_count >= max_parents:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Your plan allows up to {max_parents} parent(s). "
                "Upgrade to Bandham or Raksha to add more."
            ),
        )
    doc = payload.model_dump()
    doc.update({"user_id": uid, "created_at": datetime.now(timezone.utc), "deleted_at": None})
    res = await db.parents.insert_one(doc)
    # Completing the parents step (2) advances the resume point to the schedule step (3).
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"onboarding_step": max(user.get("onboarding_step", 0), 3)}},
    )
    await audit(user["_id"], "create_parent", {"parent_id": str(res.inserted_id)})
    return serialize(await db.parents.find_one({"_id": res.inserted_id}))

@api.put("/parents/{parent_id}")
async def update_parent(parent_id: str, payload: ParentInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    # exclude_unset=True ensures only explicitly passed fields are modified in MongoDB
    update_data = payload.model_dump(exclude_unset=True)
    if update_data:
        await db.parents.update_one(
            {"_id": ObjectId(parent_id), "deleted_at": None},
            {"$set": update_data},
        )

    # Re-sync medicine reminders if medicine_list was provided in the update
    sync_result = None
    if "medicine_list" in update_data:
        sync_result = await _sync_medicine_reminders_for_parent(
            user, parent_id, [m.model_dump() for m in (payload.medicine_list or [])]
        )

    updated = serialize(await db.parents.find_one({"_id": ObjectId(parent_id)}))
    if sync_result and sync_result.get("dropped"):
        updated["medicine_reminders_dropped"] = sync_result["dropped"]

    return updated

@api.delete("/parents/{parent_id}")
async def delete_parent(parent_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    await db.parents.update_one({"_id": ObjectId(parent_id), "user_id": scope(user)},
                                {"$set": {"deleted_at": datetime.now(timezone.utc)}})
    await db.schedules.update_many({"parent_id": ObjectId(parent_id)}, {"$set": {"deleted_at": datetime.now(timezone.utc), "active": False}})
    return {"ok": True}

# ---------------- Emergency contacts (distinct from Care Circle) ----------------
@api.get("/parents/{parent_id}/emergency-contacts")
async def get_emergency_contacts(parent_id: str, user: dict = Depends(get_current_user)):
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    return {"contacts": parent.get("emergency_contacts", [])}

@api.put("/parents/{parent_id}/emergency-contacts")
async def set_emergency_contacts(parent_id: str, payload: EmergencyContactsInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    contacts = [c.model_dump() for c in payload.contacts]
    await db.parents.update_one({"_id": ObjectId(parent_id)}, {"$set": {"emergency_contacts": contacts}})
    await audit(user["_id"], "set_emergency_contacts", {"parent_id": parent_id, "count": len(contacts)})
    return {"ok": True, "contacts": contacts}

# Emergency events history for a parent
@api.get("/parents/{parent_id}/emergency-events")
async def get_emergency_events(parent_id: str, user: dict = Depends(get_current_user)):
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    events = await db.emergency_events.find({"parent_id": parent["_id"]}).sort("created_at", -1).to_list(50)
    return [serialize(e) for e in events]

class EmergencyEventUpdate(BaseModel):
    status: str = Field(..., pattern="^(open|reviewed|resolved|false_positive)$")
    resolution_note: Optional[str] = None

@api.put("/emergency-events/{event_id}")
async def update_emergency_event(event_id: str, payload: EmergencyEventUpdate, user: dict = Depends(get_current_user)):
    """Update emergency event status (user can mark as reviewed/false_positive)"""
    event = await db.emergency_events.find_one({"_id": ObjectId(event_id), "user_id": scope(user)})
    if not event:
        raise HTTPException(status_code=404, detail="Emergency event not found")
    update_data = {"status": payload.status}
    if payload.resolution_note:
        update_data["resolution_note"] = payload.resolution_note
    update_data["resolved_at"] = datetime.now(timezone.utc) if payload.status in ("resolved", "false_positive") else None
    update_data["resolved_by"] = str(user["_id"])
    await db.emergency_events.update_one({"_id": ObjectId(event_id)}, {"$set": update_data})
    await audit(user["_id"], "emergency_event_update", {"event_id": event_id, "status": payload.status})
    return {"ok": True, "event": serialize(await db.emergency_events.find_one({"_id": ObjectId(event_id)}))}

@api.put("/admin/emergency-events/{event_id}")
async def admin_update_emergency_event(event_id: str, payload: EmergencyEventUpdate, admin: dict = Depends(get_current_admin)):
    """Admin update emergency event status"""
    event = await db.emergency_events.find_one({"_id": ObjectId(event_id)})
    if not event:
        raise HTTPException(status_code=404, detail="Emergency event not found")
    update_data = {"status": payload.status}
    if payload.resolution_note:
        update_data["resolution_note"] = payload.resolution_note
    update_data["resolved_at"] = datetime.now(timezone.utc) if payload.status in ("resolved", "false_positive") else None
    update_data["resolved_by"] = str(admin["_id"])
    await db.emergency_events.update_one({"_id": ObjectId(event_id)}, {"$set": update_data})
    await audit(str(admin["_id"]), "admin_emergency_event_update", {"event_id": event_id, "status": payload.status})
    return {"ok": True, "event": serialize(await db.emergency_events.find_one({"_id": ObjectId(event_id)}))}

# ---------------- Two-way moments (child -> parent) ----------------
@api.post("/moments/upload-image")
async def upload_moment_image(file: UploadFile = File(...), user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    """Upload an image for a moment. Re-encodes with Pillow to strip metadata
    and ensure only valid image content is saved."""
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB max
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
    MAX_DIMENSION = 1200

    content_type = file.content_type or "application/octet-stream"
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="Image too large. Maximum 5 MB per image.")

    # Decode if base64 (client sends optimized JPEG via FormData blob, so this is rarely needed)
    if content_type not in ALLOWED_TYPES:
        try:
            contents = base64.b64decode(contents)
        except Exception:
            raise HTTPException(status_code=400, detail="Could not process image data.")

    # Re-encode with Pillow: validates actual image content, strips EXIF/metadata,
    # and forces max dimension + JPEG quality (matching the client-side optimizer)
    try:
        img = Image.open(BytesIO(contents))
        img.load()  # Forces full decode — rejects corrupted/malformed images

        # Convert to RGB (strips alpha channel, EXIF, etc.)
        if img.mode in ("RGBA", "P", "L"):
            # Keep RGBA as RGBA if source is PNG (for transparency), but JPEG doesn't support alpha
            # For this use case, convert everything to RGB
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if too large
        if max(img.width, img.height) > MAX_DIMENSION:
            ratio = MAX_DIMENSION / max(img.width, img.height)
            new_w = int(img.width * ratio)
            new_h = int(img.height * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Re-encode as JPEG
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=80, optimize=True)
        contents = buffer.getvalue()

        content_type = "image/jpeg"
        ext = ".jpg"

    except Exception as e:
        logger.warning("[moment] Image re-encoding failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid or corrupted image file.")

    # Final size check after re-encoding
    if len(contents) > MAX_SIZE:
        # Re-encode with lower quality
        img = Image.open(BytesIO(contents))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=60, optimize=True)
        contents = buffer.getvalue()

    # Save to Emergent object storage (survives deploys / multi-replica).
    filename = f"{uuid.uuid4().hex}{ext}"
    storage_path = f"{STORAGE_APP_NAME}/moments/{scope(user)}/{filename}"
    try:
        result = put_object(storage_path, contents, content_type)
    except Exception as e:
        logger.error("[moment] object-storage upload failed: %s", e)
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")

    await db.moment_images.insert_one({
        "filename": filename,
        "storage_path": result.get("path", storage_path),
        "content_type": content_type,
        "size": result.get("size", len(contents)),
        "user_id": scope(user),
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc),
    })

    # Generate a signed URL that expires after 1 hour
    # (WhatsApp fetches the image immediately, so 1 hour is more than enough)
    url = _build_signed_url(filename)
    return {"url": url, "filename": filename, "content_type": content_type}


def _sign_token(filename: str, expires_at: datetime) -> str:
    """Generate HMAC signature for the signed URL."""
    payload = f"{filename}:{int(expires_at.timestamp())}"
    secret = os.environ.get("JWT_SECRET", "").encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _build_signed_url(filename: str, expires_sec: int = 3600) -> str:
    """Build a time-limited signed URL for a uploaded image."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_sec)
    signature = _sign_token(filename, expires_at)
    base_url = os.environ.get("BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}/api/uploads/signed/{filename}?sig={signature}&exp={int(expires_at.timestamp())}"
    return f"/api/uploads/signed/{filename}?sig={signature}&exp={int(expires_at.timestamp())}"


@api.get("/uploads/signed/{filename}")
async def serve_uploaded_image(filename: str, sig: str = Query(...), exp: int = Query(...)):
    """Serve uploaded images via signed URL — expires after timestamp.
    This protects images from being shared or scraped without a valid signed URL."""
    # Check expiration
    now = datetime.now(timezone.utc).timestamp()
    if exp < int(now) - 300:  # Allow 5 min clock skew
        raise HTTPException(status_code=403, detail="Unsigned URL has expired")

    # Verify signature
    expected_sig = _sign_token(filename, datetime.fromtimestamp(exp, tz=timezone.utc))
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Fetch from object storage
    record = await db.moment_images.find_one({"filename": filename, "is_deleted": False})
    if not record:
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        data, content_type = get_object(record["storage_path"])
    except Exception as e:
        logger.error("[moment] object-storage fetch failed for %s: %s", filename, e)
        raise HTTPException(status_code=404, detail="Image not found")

    return Response(content=data, media_type=record.get("content_type") or content_type)

@api.post("/moments")
async def send_moment_api(payload: MomentInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    parent = await db.parents.find_one({"_id": ObjectId(payload.parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    if len(payload.image_urls) > 2:
        raise HTTPException(status_code=400, detail="Maximum 2 images allowed per moment.")
    sender_name = user.get("name") or "Your family"
    result = await send_moment(db, parent, payload.text, sender_name, payload.image_url or "", payload.image_urls)
    doc = {
        "user_id": scope(user), "parent_id": parent["_id"], "sender_name": sender_name,
        "text": payload.text, "image_url": payload.image_url, "image_urls": payload.image_urls,
        "status": (result or {}).get("status"), "created_at": datetime.now(timezone.utc),
    }
    await db.moments.insert_one(doc)
    return {"ok": True, "status": (result or {}).get("status"), "moment": serialize(doc)}

@api.get("/moments")
async def list_moments(user: dict = Depends(get_current_user)):
    docs = await db.moments.find({"user_id": scope(user)}).sort("created_at", -1).to_list(100)
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
    docs = await db.schedules.find({"user_id": scope(user), "deleted_at": None}).to_list(50)
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
    parent = await db.parents.find_one({"_id": ObjectId(payload.parent_id), "user_id": scope(user)})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    plan_id = await _validate_by_plan(user, payload.messages)
    doc = {
        "user_id": scope(user),
        "parent_id": ObjectId(payload.parent_id),
        "mode": payload.mode,
        "messages": [m.model_dump() for m in payload.messages],
        "active": payload.active,
        "recovery_mode": payload.recovery_mode,
        "recovery_until": payload.recovery_until,
        "reengagement_hours": payload.reengagement_hours,
        "created_at": datetime.now(timezone.utc),
        "deleted_at": None,
    }
    res = await db.schedules.insert_one(doc)
    # New schedule may not yet reflect this parent's medicine reminder
    # times (medicines are saved separately on the parent doc) — sync now.
    sync_result = sync_medicine_reminders(
        medicine_list=parent.get("medicine_list", []),
        existing_messages=doc["messages"],
        plan_id=plan_id,
    )
    await db.schedules.update_one({"_id": res.inserted_id}, {"$set": {"messages": sync_result["messages"]}})
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"onboarding_step": max(user.get("onboarding_step", 0), 4)}})
    await audit(user["_id"], "create_schedule", {"schedule_id": str(res.inserted_id)})
    out = serialize(await db.schedules.find_one({"_id": res.inserted_id}))
    if sync_result["dropped"]:
        out["medicine_reminders_dropped"] = sync_result["dropped"]
    return out

@api.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, payload: ScheduleInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    sched = await db.schedules.find_one({"_id": ObjectId(schedule_id), "user_id": scope(user)})
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    plan_id = await _validate_by_plan(user, payload.messages)
    parent = await db.parents.find_one({"_id": sched["parent_id"]})
    new_messages = [m.model_dump() for m in payload.messages]
    # Re-sync medicine reminders on top of whatever the user just submitted,
    # same as create_schedule — keeps the two paths consistent.
    sync_result = sync_medicine_reminders(
        medicine_list=(parent or {}).get("medicine_list", []),
        existing_messages=new_messages,
        plan_id=plan_id,
    )
    await db.schedules.update_one({"_id": ObjectId(schedule_id)}, {"$set": {
        "mode": payload.mode,
        "messages": sync_result["messages"],
        "active": payload.active,
        "recovery_mode": payload.recovery_mode,
        "recovery_until": payload.recovery_until,
        "reengagement_hours": payload.reengagement_hours,
    }})
    out = serialize(await db.schedules.find_one({"_id": ObjectId(schedule_id)}))
    if sync_result["dropped"]:
        out["medicine_reminders_dropped"] = sync_result["dropped"]
    return out

@api.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    await db.schedules.update_one({"_id": ObjectId(schedule_id), "user_id": scope(user)},
                                  {"$set": {"deleted_at": datetime.now(timezone.utc), "active": False}})
    return {"ok": True}

# ---------------- Recovery mode (Raksha) ----------------
@api.post("/schedules/{schedule_id}/recovery/start")
async def start_recovery(schedule_id: str, payload: RecoveryStartInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    sched = await db.schedules.find_one({"_id": ObjectId(schedule_id), "user_id": scope(user), "deleted_at": None})
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
    base_msgs = [m for m in sched.get("messages", []) if not m.get("is_recovery")]
    extra = [{"time": m.time, "category": m.category, "type": "reminder", "is_recovery": True} for m in payload.extra_reminders]
    await db.schedules.update_one(
        {"_id": ObjectId(schedule_id)},
        {"$set": {"messages": base_msgs + extra, "recovery_mode": True, "recovery_until": until}},
    )
    await audit(user["_id"], "recovery_start", {"schedule_id": schedule_id, "days": days, "extra": len(extra)})
    updated = await db.schedules.find_one({"_id": ObjectId(schedule_id)})
    return {"ok": True, "recovery_until": until, "schedule": serialize(updated)}

@api.post("/schedules/{schedule_id}/recovery/end")
async def end_recovery(schedule_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    sched = await db.schedules.find_one({"_id": ObjectId(schedule_id), "user_id": scope(user), "deleted_at": None})
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    active_messages = [m for m in sched.get("messages", []) if not m.get("is_recovery")]
    recovery_messages = [m for m in sched.get("messages", []) if m.get("is_recovery")]
    await db.schedules.update_one(
        {"_id": ObjectId(schedule_id)},
        {"$set": {"messages": active_messages, "recovery_mode": False, "recovery_until": None,
                  "archived_recovery_messages": recovery_messages}},
    )
    await audit(user["_id"], "recovery_end", {"schedule_id": schedule_id, "archived": len(recovery_messages)})
    return {"ok": True, "archived": len(recovery_messages)}

# ---------------- Consent & Preferences ----------------
@api.post("/consent")
async def log_consent(payload: ConsentInput, request: Request, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    await db.consent_logs.insert_one({
        "user_id": str(user["_id"]),
        "consent_type": payload.consent_type,
        "agreed": payload.agreed,
        "text": payload.text,
        "ip": request.client.host if request.client else None,
        "created_at": datetime.now(timezone.utc),
    })
    await audit(user["_id"], "consent", {"type": payload.consent_type, "agreed": payload.agreed})
    return {"ok": True}

@api.put("/preferences")
async def update_prefs(payload: PreferencesInput, user: dict = Depends(get_current_user)):
    # exclude_unset=True: only patch keys the client actually sent, using
    # MongoDB dot-notation so we never wipe the whole preferences object.
    # (Previously filtered on `v is not None`, which meant a client could
    # never explicitly clear a preference back to null — any None value,
    # intentional or not, was silently dropped instead of being applied.)
    upd = {f"preferences.{k}": v for k, v in payload.model_dump(exclude_unset=True).items()}
    if upd:
        await db.users.update_one({"_id": user["_id"]}, {"$set": upd})
    return serialize(await db.users.find_one({"_id": user["_id"]}))

# ---------------- Payment ----------------
@api.get("/payment/state")
async def payment_state(user: dict = Depends(get_current_user)):
    state = await db.payment_state.find_one({"user_id": scope(user)})
    plan = resolve_plan_id((state or {}).get("plan", "nitya"))
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
    usage = await _validate_plan_transition(str(user["_id"]), plan)
    if os.environ.get("PAYMENTS_ENABLED", "false").lower() != "true":
        await db.payment_state.update_one(
            {"user_id": str(user["_id"])},
            {"$set": {"status": "trial", "plan": plan, "billing": billing, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        # Step order is: 0 welcome, 1 plan, 2 parents, 3 schedule, 4 activate —
        # plan selection happens right after welcome/user-details, before any parent is added,
        # so completing it advances the resume point to the parents step (2).
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"onboarding_step": max(user.get("onboarding_step", 0), 2)}})
        await audit(user["_id"], "payment_skipped_test_mode", {"plan": plan, "billing": billing})
        return {"skipped": True, "plan": plan, "billing": billing, "usage": usage, "message": "Payments are disabled in testing mode. Trial access granted."}
    # ── Live payments: create a Stripe Checkout session ──
    from payments import create_stripe_checkout, PaymentCheckoutInput
    origin = payload.origin_url or os.environ.get("FRONTEND_URL", "")
    result = await create_stripe_checkout(
        str(user["_id"]),
        PaymentCheckoutInput(plan=plan, billing=billing, origin_url=origin),
        request,
    )
    await audit(user["_id"], "payment_checkout_created", {"plan": plan, "billing": billing, "session_id": result.get("session_id")})
    return {"skipped": False, "plan": plan, "billing": billing, "usage": usage, **result}

# ---------------- Activation ----------------
@api.get("/activation")
async def get_activation(user: dict = Depends(get_current_user)):
    state = await db.activation_state.find_one({"user_id": scope(user)})
    return serialize(state) if state else {"whatsapp_activated": False}

@api.post("/activation/activate")
async def activate(user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    parents = await db.parents.find({"user_id": scope(user), "deleted_at": None}).to_list(50)
    schedules = await db.schedules.find({"user_id": scope(user), "deleted_at": None}).to_list(50)
    if not parents or not schedules:
        raise HTTPException(status_code=400, detail="Please add a parent and a schedule before activating.")

    plan_id = await _get_plan_id(user)
    variants_per_slot = plan_limits(plan_id)["variants_per_slot"]
    day_index = datetime.now(timezone.utc).timetuple().tm_yday

    results = []
    for p in parents:
        r = await send_whatsapp_opener(db, p, day_index, variants_per_slot)
        results.append({"parent": p.get("name"), "status": r.get("status"), "skipped": r.get("skipped", False)})

    await db.activation_state.update_one(
        {"user_id": scope(user)},
        {"$set": {"whatsapp_activated": True, "activated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"onboarding_complete": True, "onboarding_step": 5}})
    await audit(user["_id"], "activate_whatsapp", {"results": results})
    return {"activated": True, "whatsapp_enabled": whatsapp_enabled(), "results": results}

# ---------------- Message logs / dashboard ----------------
@api.get("/messages/logs")
async def message_logs(
    user: dict = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    query = {"user_id": scope(user)}
    total = await db.message_logs.count_documents(query)
    docs = await db.message_logs.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "skip": skip, "limit": limit, "items": [serialize(d) for d in docs]}

@api.post("/whatsapp/send-test")
@api.post("/messages/send-test")
async def send_test(payload: SendTestInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token), _rl: None = Depends(api_rate_limit_dependency)):
    parent = await db.parents.find_one({"_id": ObjectId(payload.parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    slot_type = payload.category or "morning_wish"
    session_open = await is_session_open(db, parent["_id"])

    plan_id = await _get_plan_id(user)
    variants_per_slot = plan_limits(plan_id)["variants_per_slot"]
    day_index = datetime.now(timezone.utc).timetuple().tm_yday

    if session_open:
        if slot_type in ["medicine", "bp_check", "sugar_check"]:
            result = await send_dynamic_checkin(db, parent, slot_type, day_index, variants_per_slot, medicine_name="your medicine")
        else:
            result = await send_dynamic_checkin(db, parent, slot_type, day_index, variants_per_slot)
    else:
        if slot_type in ["medicine", "bp_check", "sugar_check", "water", "health_check"]:
            result = await send_medicine_template(db, parent, day_index, variants_per_slot, medicine_name="your medicine")
        elif slot_type in ["breakfast", "lunch", "dinner", "afternoon_checkin"]:
            result = await send_meal_template(db, parent, meal_type=slot_type, day_index=day_index, variants_per_slot=variants_per_slot)
        elif slot_type in ["goodnight", "love_note", "how_feeling"]:
            result = await send_mood_template(db, parent, category=slot_type, day_index=day_index, variants_per_slot=variants_per_slot)
        else:
            result = await send_whatsapp_opener(db, parent, day_index, variants_per_slot)

    msg_status = result.get("status", "failed")
    # Log this manual send as a message_log so it appears in the log history
    msg_type = "reminder" if slot_type in ["medicine", "bp_check", "sugar_check", "water", "health_check"] else "checkin"
    now_utc = datetime.now(timezone.utc)
    try:
        p_tz = ZoneInfo(parent.get("timezone", "Asia/Kolkata"))
    except Exception:
        p_tz = ZoneInfo("Asia/Kolkata")
    await db.message_logs.insert_one({
        "user_id": scope(user), "parent_id": parent["_id"],
        "category": slot_type, "msg_type": msg_type, "status": msg_status,
        "created_at": now_utc, "day_key": now_utc.astimezone(p_tz).strftime("%Y-%m-%d"),
    })
    await audit(user["_id"], "send_test", {"parent_id": str(parent["_id"]), "slot_type": slot_type, "session_open": session_open, "template_used": result.get("template_type", "dynamic")})
    return {"ok": True, "status": msg_status, "detail": result.get("detail"), "session_open": session_open, "template_type": result.get("template_type", "dynamic")}


# ── Say-hi: child can send a warm test message to a parent before full activation ──
SAY_HI_COPY = {
    "en": "💛 Hi {parent_name}! Your child has set up AYANA to stay close. You'll get gentle daily check-ins — just tap or speak, no app needed. We'll start sending tomorrow morning. Take care!",
    "te": "💛 హలో {parent_name}! మీ పిల్ల ఆయనా AYANA సెటప్ చేసారు. మీరు రోజువే సౌకర్యవంతమైన పరిశీలనలు పొందుతారు — ఒక్కసారి నొక్కి లేదా మాట్లాడండి, యాప్ అవసరం లేదు. రేపు ఉదయం మన సందేశాలు ప్రారంభమవుతాయి. జాగ్రత్తగా ఉండండి!",
    "hi": "💛 नमस्ते {parent_name}! आपका बच्चा ने AYANA सेट करवा है। आपको रोज़ाना हल्क़ी से परिचीत होने वाले संदेश मिलेंगे — बस एक टैप या बोलना, कोई ऐप नहीं चाहिए। कल सुबह से शुरू हो जाएगा। ध्यान रखना!",
}


@api.post("/parents/{parent_id}/say-hi")
async def say_hi(parent_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    """Child sends a warm greeting to a parent, so they know what's coming.
    Uses a plain text message (no template needed since the child→parent
    direction may not have session yet — this is the child initiating)."""
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    language = parent.get("language", "en")
    preferred = parent.get("preferred_name") or parent.get("name") or "Amma"
    copy = SAY_HI_COPY.get(language, SAY_HI_COPY["en"]).format(parent_name=preferred)
    result = await send_whatsapp(parent.get("phone", ""), copy)
    await audit(user["_id"], "say_hi", {"parent_id": str(parent["_id"])})
    return {"ok": True, "status": result.get("status"), "detail": result.get("detail")}


@api.post("/messages/preview")
async def preview_message(payload: PreviewInput, user: dict = Depends(get_current_user)):
    parent = await db.parents.find_one({"_id": ObjectId(payload.parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    category = payload.category
    language = parent.get("language", "en")
    plan_id = await _get_plan_id(user)
    variants_per_slot = plan_limits(plan_id)["variants_per_slot"]
    day_index = datetime.now(timezone.utc).timetuple().tm_yday
    body = render_slot_body(category, language, parent, day_index, "your medicine", variants_per_slot)
    buttons = render_slot_buttons(category, language)
    return {"text": body, "buttons": buttons, "language": language}

# ---------------- Care Circle ----------------
@api.get("/circle")
async def get_circle(user: dict = Depends(get_current_user)):
    if is_member(user):
        owner = await db.users.find_one({"_id": ObjectId(user["household_owner_id"])})
        return {"role": "member", "owner": {"name": owner.get("name") if owner else "", "email": owner.get("email") if owner else ""}}
    uid = str(user["_id"])
    plan_id = await _get_plan_id(user)
    max_members = plan_limits(plan_id).get("family_members", 1)
    members = await db.users.find({"household_owner_id": uid, "deleted_at": None}).to_list(20)
    invites = await db.circle_invites.find({"owner_id": uid, "status": "pending"}).to_list(20)
    return {
        "role": "owner",
        "plan": plan_id,
        "max_members": max_members,
        "members": [{"id": str(m["_id"]), "name": m.get("name"), "email": m.get("email")} for m in members],
        "invites": [{"id": str(i["_id"]), "email": i.get("email")} for i in invites],
    }

@api.post("/circle/invite")
async def invite_member(payload: InviteInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token), _rl: None = Depends(api_rate_limit_dependency)):
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can invite family members.")
    uid = str(user["_id"])
    plan_id = await _get_plan_id(user)
    max_members = plan_limits(plan_id).get("family_members", 1)
    if max_members < 1:
        raise HTTPException(status_code=403, detail="Family co-care requires Raksha. Upgrade to invite siblings.")
    email = (payload.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email.")
    if email == user.get("email"):
        raise HTTPException(status_code=400, detail="That's your own email 🙂")
    current = await db.users.count_documents({"household_owner_id": uid, "deleted_at": None})
    pending = await db.circle_invites.count_documents({"owner_id": uid, "status": "pending"})
    if current + pending >= max_members:
        raise HTTPException(status_code=400, detail=f"Your plan allows up to {max_members} care-circle member(s).")
    existing_member = await db.users.find_one({"email": email, "household_owner_id": uid, "deleted_at": None})
    if existing_member:
        raise HTTPException(status_code=400, detail="This person is already in your care circle.")
    if await db.circle_invites.find_one({"owner_id": uid, "email": email, "status": "pending"}):
        raise HTTPException(status_code=400, detail="You've already invited this email. Check the Care circle tab to resend.")
    import jwt as _jwt
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    invite_res = await db.circle_invites.insert_one({
        "owner_id": uid, "email": email, "status": "pending",
        "created_at": datetime.now(timezone.utc), "expires_at": expires_at,
        "inviter_name": user.get("name", "Someone"), "parent_id": payload.parent_id or None,
    })
    await audit(uid, "circle_invite", {"email": email})
    # Signed invite token — same shape /circle/invite/{token}/accept already
    # expects (type=invite, sub=invite _id). Previously this link carried no
    # token at all, so the preview page and accept endpoint had nothing valid
    # to check — every invite link 404'd or failed on click.
    invite_token = _jwt.encode(
        {"sub": str(invite_res.inserted_id), "type": "invite", "exp": expires_at},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    frontend = os.environ.get("FRONTEND_URL", "").rstrip("/")
    link = f"{frontend}/invite/{invite_token}" if frontend else f"/invite/{invite_token}"
    parent_display_name = ""
    if payload.parent_id:
        p = await db.parents.find_one({"_id": ObjectId(payload.parent_id), "user_id": uid})
        if p:
            parent_display_name = p.get("preferred_name") or p.get("name", "")
    # ── Send invite email (fires-and-forgets result; never blocks the API) ──
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
    invite = await db.circle_invites.find_one({"email": user.get("email"), "status": "pending"})
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"This invite has already been {invite.get('status')}.")
    parent_display_name = ""
    if invite.get("parent_id"):
        p = await db.parents.find_one({"_id": ObjectId(invite["parent_id"])})
        if p:
            parent_display_name = p.get("preferred_name") or p.get("name", "")
    return {
        "invite_id": str(invite["_id"]), "email": invite.get("email"),
        "inviter_name": invite.get("inviter_name", ""), "parent_display_name": parent_display_name,
        "expires_at": invite["expires_at"].isoformat() if invite.get("expires_at") else None,
        "status": invite.get("status"),
    }

@api.get("/circle/invite/{token}")
async def preview_invite_by_token(token: str):
    """Public (unauthenticated) preview for InviteClaim.js — lets someone see
    who invited them and to which parent's care circle before they log in or
    sign up. This route never existed, so every invite link 404'd on load."""
    import jwt as _jwt
    try:
        payload = _jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        if payload.get("type") != "invite":
            raise HTTPException(status_code=400, detail="Invalid invite link.")
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="This invite link has expired.")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid invite link.")
    invite = await db.circle_invites.find_one({"_id": ObjectId(payload["sub"])})
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"This invite has already been {invite.get('status')}.")
    parent_display_name = ""
    if invite.get("parent_id"):
        p = await db.parents.find_one({"_id": ObjectId(invite["parent_id"])})
        if p:
            parent_display_name = p.get("preferred_name") or p.get("name", "")
    return {
        "email": invite.get("email"),
        "inviter_name": invite.get("inviter_name", ""),
        "parent_display_name": parent_display_name,
        "expires_at": invite["expires_at"].isoformat() if invite.get("expires_at") else None,
        "status": invite.get("status"),
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
    invite = await db.circle_invites.find_one({"_id": ObjectId(payload["sub"])})
    if not invite or invite.get("status") != "pending":
        raise HTTPException(status_code=409, detail="This invite is no longer valid.")
    if invite.get("email") != user.get("email"):
        raise HTTPException(status_code=403, detail="This invite was sent to a different email address.")
    now = datetime.now(timezone.utc)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"household_owner_id": invite["owner_id"], "onboarding_complete": True}})
    await db.circle_invites.update_one({"_id": invite["_id"]}, {"$set": {"status": "accepted", "accepted_at": now, "member_id": str(user["_id"])}})
    await audit(str(user["_id"]), "circle_invite_accepted", {"invite_id": str(invite["_id"])})
    return {"ok": True, "owner_id": invite["owner_id"]}

@api.delete("/circle/member/{member_id}")
async def remove_member(member_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can remove members.")
    await db.users.update_one({"_id": ObjectId(member_id), "household_owner_id": str(user["_id"])}, {"$set": {"household_owner_id": None}})
    return {"ok": True}

@api.delete("/circle/invite/{invite_id}")
async def cancel_invite(invite_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    await db.circle_invites.update_one({"_id": ObjectId(invite_id), "owner_id": str(user["_id"])}, {"$set": {"status": "cancelled"}})
    return {"ok": True}

# ---------------- Monthly reports (NEW) ----------------
@api.get("/reports/monthly")
async def get_monthly_report(parent_id: str, period: str, user: dict = Depends(get_current_user)):
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    report = await db.monthly_reports.find_one({"user_id": scope(user), "parent_id": ObjectId(parent_id), "period": period})
    if not report:
        raise HTTPException(status_code=404, detail="No report generated for that period yet.")
    return serialize(report)

@api.post("/reports/monthly/generate")
async def generate_monthly_report_now(parent_id: str, period: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    """Manual 'generate now' action — no automatic monthly cron is wired up yet
    (see README 'Open items': report delivery channel is still undecided)."""
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    year, month = (int(x) for x in period.split("-"))
    plan_id = await _get_plan_id(user)
    report = await generate_monthly_report(scope(user), parent["_id"], plan_id, year, month)
    await audit(user["_id"], "generate_monthly_report", {"parent_id": parent_id, "period": period})
    return serialize(report)

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
    """
    Return True if any keyword appears as a whole word in text.

    Strategy:
      • ASCII keywords  → regex \\b word boundary (so "bad" won't match "badam").
      • Indic / Telugu  → plain substring match (no ASCII word boundaries exist
        in Devanagari / Telugu scripts, but the phrases are distinct enough).
    """
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
    """Parse a parent's WhatsApp reply into a structured feeling label."""
    if not text:
        return None
    t = text.strip()
    # Check worst-case first so we don't accidentally mark "bad" replies as "good"
    if _word_in(t, _BAD):
        return "not_well"
    if _word_in(t, _GOOD):
        return "good"
    if _word_in(t, _OKAY):
        return "okay"
    if _word_in(t, _DONE):
        return "done"
    return None


async def _notify_family(owner_id: str, parent, feeling: str | None, is_voice: bool, body: str, keywords: list, ml_flagged: bool = False):
    owner = await db.users.find_one({"_id": ObjectId(owner_id)})
    members = await db.users.find({"household_owner_id": owner_id, "deleted_at": None}).to_list(20)
    recipients = [owner] + members if owner else members
    pname = parent.get("name", "Your parent") if parent else "Your parent"
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
        if r and r.get("phone"):
            send_whatsapp(r["phone"], head)
    # On a real emergency, also alert the parent's dedicated emergency contacts.
    if keywords and parent:
        member_phones = {r.get("phone") for r in recipients if r}
        for c in (parent.get("emergency_contacts") or []):
            cph = c.get("phone")
            if cph and cph not in member_phones:
                send_whatsapp(cph, head)

# ── Generic-payload disambiguation ──────────────────────────────────────
# `medicine` and `meal` are each ONE approved WhatsApp template shared
# across several categories (medicine/water/bp_check/sugar_check/
# health_check all use the "medicine" template; breakfast/lunch/dinner/
# afternoon_checkin/tea_check/walk_check all use "meal"). Button
# payloads on an approved template are fixed at submission time, so
# those buttons carry a GENERIC payload (reminder_done, meal_pending,
# etc.) rather than a category-specific one like the in-session quick
# replies use (done:water, pending:lunch). This resolves the generic
# payload back to the real category by checking what was actually sent
# last — same idea as the existing last_msg_type fallback in
# parse_intent, just applied to button taps instead of numeric replies.
_GENERIC_REMINDER_PAYLOADS = {
    "reminder_done": "done", "reminder_pending": "pending", "reminder_skip": "skip",
}
_GENERIC_MEAL_PAYLOADS = {
    "meal_done": "done", "meal_pending": "pending", "meal_skip": "skip",
}
_REMINDER_CATEGORIES = {"medicine", "water", "bp_check", "sugar_check", "health_check"}
_MEAL_CATEGORIES = {"breakfast", "lunch", "dinner", "afternoon_checkin", "tea_check", "walk_check"}


async def _resolve_generic_button_intent(parent_id, button_payload: str) -> str | None:
    """Returns a resolved intent like 'done:water' for a generic template
    button payload, or None if button_payload isn't one of the generic
    ones (caller should fall back to using it as-is)."""
    if button_payload in _GENERIC_REMINDER_PAYLOADS:
        action = _GENERIC_REMINDER_PAYLOADS[button_payload]
        category_set = _REMINDER_CATEGORIES
    elif button_payload in _GENERIC_MEAL_PAYLOADS:
        action = _GENERIC_MEAL_PAYLOADS[button_payload]
        category_set = _MEAL_CATEGORIES
    else:
        return None

    last_log = await db.message_logs.find_one(
        {"parent_id": parent_id, "category": {"$in": list(category_set)}},
        sort=[("created_at", -1)],
    )
    if not last_log:
        # No matching send on record — fall back to a generic bucket
        # rather than guessing wrong, so it's at least visible/auditable.
        logger.warning("[webhook] No recent %s send found for parent %s to resolve %s", category_set, parent_id, button_payload)
        return f"{action}:generic"
    return f"{action}:{last_log['category']}"


# ── Interactive button handler callbacks ───────────────────────────────────
async def _mark_medicine_status(phone: str, taken: bool):
    """Find the most recent medicine reminder for this parent and log the status."""
    parent = await db.parents.find_one({"phone": phone, "deleted_at": None})
    if not parent:
        return
    day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = await db.message_logs.find_one(
        {"parent_id": parent["_id"], "day_key": day_key, "msg_type": "reminder",
         "category": {"$in": _REMINDER_CATEGORIES}},
        sort=[("created_at", -1)],
    )
    if log:
        await db.message_logs.update_one(
            {"_id": log["_id"]},
            {"$set": {"reply_status": "done" if taken else "skipped"}},
        )


async def _mark_meal_status(phone: str, eaten: bool):
    """Find the most recent meal check-in for this parent and log the status."""
    parent = await db.parents.find_one({"phone": phone, "deleted_at": None})
    if not parent:
        return
    day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = await db.message_logs.find_one(
        {"parent_id": parent["_id"], "day_key": day_key, "msg_type": "checkin",
         "category": {"$in": _MEAL_CATEGORIES}},
        sort=[("created_at", -1)],
    )
    if log:
        await db.message_logs.update_one(
            {"_id": log["_id"]},
            {"$set": {"reply_status": "done" if eaten else "skipped"}},
        )


async def _send_whatsapp_text(phone: str, body: str):
    return send_whatsapp(phone, body)


# ── Parent language auto-detect helper ─────────────────────────────────────
async def _detect_language(text: str) -> str:
    """Simple language detection for parent replies — returns 'en', 'te', 'hi', or None."""
    if not text or not text.strip():
        return None
    te_chars = sum(1 for c in text if 0x0C00 <= ord(c) <= 0x0C7F)
    hi_chars = sum(1 for c in text if 0x0900 <= ord(c) <= 0x097F)
    if te_chars > 0 and te_chars >= hi_chars:
        return "te"
    if hi_chars > 0 and hi_chars >= te_chars:
        return "hi"
    # Default: English if no Devanagari/Telugu script detected
    return "en"


async def _record_reply(from_number: str, body_text: str, num_media: int = 0, parent=None, button_payload: str | None = None, media_url: str | None = None, media_content_type: str | None = None, raw_payload: dict | None = None):
    if parent is None:
        parent = await db.parents.find_one({"phone": from_number, "deleted_at": None})
    if parent:
        await refresh_session(db, parent["_id"])
        # Language auto-detection: if parent has auto detection enabled and
        # they reply in a language different from configured, log a suggestion.
        if parent.get("auto_activity_detection", True) and parent.get("language"):
            detected = await _detect_language(body_text or "")
            if detected and detected != parent.get("language"):
                await db.parents.update_one(
                    {"_id": parent["_id"]},
                    {"$set": {"detected_language": detected, "language_suggestion": detected,
                              "language_suggestion_at": datetime.now(timezone.utc)}},
                )
    is_voice = False
    transcription = None
    intent = None
    lang = parent.get("language", "en") if parent else "en"
    ml_flagged = False
    if button_payload:
        resolved = await _resolve_generic_button_intent(parent["_id"], button_payload) if parent else None
        intent = resolved if resolved is not None else button_payload
    elif media_url and (media_content_type or "").startswith("audio/") or (num_media > 0):
        is_voice = True
        transcription = await transcribe_voice_note(media_url, language=lang, auth_headers=meta_auth_header())
        effective_text = transcription or "[voice note]"
        intent = parse_intent(None, effective_text)
        body_text = effective_text
    else:
        last_log = None
        if parent:
            last_log = await db.message_logs.find_one({"parent_id": parent["_id"]}, sort=[("created_at", -1)])
        last_msg_type = (last_log or {}).get("msg_type", "checkin")
        intent = parse_intent(None, body_text, last_msg_type=last_msg_type)
    user_prefs = None
    if parent:
        user_prefs = await db.preferences.find_one({"user_id": parent["user_id"]})
    extra_kw = (user_prefs or {}).get("emergency_keywords", [])
    if button_payload:
        # Structured button tap: the payload/intent is unambiguous (the
        # "Bad day 😟" button's id IS "emergency:health" in every language),
        # so emergency status is decided from intent directly rather than by
        # keyword-matching the button's display title against body_text.
        # Titles like "Some pain" (-> feeling:not_well, NOT an emergency)
        # contain words such as "pain" that would otherwise trip a false
        # alarm. Free-text and voice replies are unaffected — they still go
        # through detect_emergency() below, unchanged.
        keywords = [intent] if intent and intent.startswith("emergency:") else []
    else:
        keywords = detect_emergency(body_text, extra_kw)

    if is_voice and parent:
        assessment = await assess_transcript(db, parent["_id"], body_text, lang, keywords)
        ml_flagged = assessment.get("ml_flagged", False)

    owner_id = parent["user_id"] if parent else None
    feeling = intent.split(":")[1] if intent and ":" in intent else intent
    reply_doc = {
        "from_phone": from_number, "parent_id": parent["_id"] if parent else None,
        "user_id": owner_id, "body": body_text, "button_payload": button_payload,
        "intent": intent, "feeling": feeling, "is_voice": is_voice, "transcription": transcription,
        "media_url": media_url, "emergency_keywords": keywords, "ml_flagged": ml_flagged, "ml_score": assessment.get("ml_score") if is_voice and parent else None,
        "raw_payload": raw_payload or {}, "created_at": datetime.now(timezone.utc),
    }
    await db.parent_replies.insert_one(reply_doc)
    if keywords and parent:
        await db.emergency_events.insert_one({
            "user_id": owner_id, "parent_id": parent["_id"], "phone": from_number,
            "body": body_text, "keywords": keywords, "intent": intent,
            "is_voice": is_voice, "status": "open", "created_at": datetime.now(timezone.utc),
        })
    if parent and owner_id:
        await _notify_family(owner_id, parent, feeling, is_voice, body_text, keywords, ml_flagged)
    return reply_doc


@api.get("/parents/{parent_id}/language-suggestion")
async def get_language_suggestion(parent_id: str, user: dict = Depends(get_current_user)):
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    suggestion = parent.get("language_suggestion")
    return {
        "current_language": parent.get("language", "en"),
        "suggested_language": suggestion,
        "detected_at": parent.get("language_suggestion_at"),
        "auto_detection": parent.get("auto_activity_detection", True),
    }


@api.put("/parents/{parent_id}/language")
async def update_parent_language(parent_id: str, language: str, user: dict = Depends(get_current_user)):
    parent = await db.parents.find_one({"_id": ObjectId(parent_id), "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    from templates_data import LANGUAGES
    valid_langs = {l["code"] for l in LANGUAGES}
    if language not in valid_langs:
        raise HTTPException(status_code=400, detail=f"Language must be one of: {', '.join(sorted(valid_langs))}")
    await db.parents.update_one(
        {"_id": ObjectId(parent_id)},
        {"$set": {"language": language, "language_suggestion": None, "language_suggestion_at": None}},
    )
    await audit(user["_id"], "update_parent_language", {"parent_id": parent_id, "language": language})
    return {"ok": True, "language": language}


@api.get("/replies")
async def list_replies(user: dict = Depends(get_current_user)):
    docs = await db.parent_replies.find({"user_id": scope(user)}).sort("created_at", -1).to_list(100)
    parents = {str(p["_id"]): p.get("name") for p in await db.parents.find({"user_id": scope(user)}).to_list(50)}
    out = []
    for d in docs:
        s = serialize(d)
        s["parent_name"] = parents.get(str(d.get("parent_id")), "Parent")
        out.append(s)
    return out


class SimulateReplyInput(BaseModel):
    parent_id: str
    text: str = ""
    num_media: int = Field(0, ge=0)
    button_payload: Optional[str] = None


@api.post("/replies/simulate")
async def simulate_reply(payload: SimulateReplyInput, user: dict = Depends(get_current_user)):
    """QA / ops helper: simulate an inbound parent reply without a live
    WhatsApp session. Runs the exact same _record_reply pipeline the webhook
    uses (intent parse, emergency detection, language suggestion, family
    notify), so replies show up in the dashboard just like real ones."""
    try:
        oid = ObjectId(payload.parent_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Parent not found")
    parent = await db.parents.find_one({"_id": oid, "user_id": scope(user), "deleted_at": None})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    reply = await _record_reply(
        from_number=parent.get("phone", ""),
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
        "emergency_keywords": reply.get("emergency_keywords", []),
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
    """Merged Activity + Replies: per-parent, per-day delivery AND reply
    status in one payload. Replaces /messages/logs + /replies on the
    dashboard's Check-ins tab."""
    owner = scope(user)
    parents = await db.parents.find({"user_id": owner, "deleted_at": None}).to_list(50)
    if not parents:
        return {"parents": [], "alerts": []}

    parent_ids = [p["_id"] for p in parents]
    since = datetime.now(timezone.utc) - timedelta(days=days + 1)

    # NOTE: "escalation" (Care Watch retries) is intentionally excluded here —
    # a retry is the same logical touch resent, not a new expected reply.
    # Counting it separately would inflate "X of Y replied" totals.
    logs = await db.message_logs.find({
        "parent_id": {"$in": parent_ids},
        "msg_type": {"$in": ["checkin", "reminder", "reengagement"]},
        "created_at": {"$gte": since},
    }).sort("created_at", 1).to_list(2000)

    replies = await db.parent_replies.find({
        "parent_id": {"$in": parent_ids},
        "created_at": {"$gte": since},
    }).sort("created_at", 1).to_list(2000)
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
        pid = str(p["_id"])
        tz_name = p.get("timezone", "Asia/Kolkata")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Asia/Kolkata")

        p_logs = [l for l in logs if str(l["parent_id"]) == pid]
        by_day: dict[str, list] = {}
        for l in p_logs:
            # Prefer the log's own day_key (set at write time), but recompute
            # from created_at if missing or clearly UTC-mismatched — some
            # write paths (send_test, reengagement) previously used UTC
            # instead of the parent's local day; this keeps old rows usable.
            dk = _local_day_key(l["created_at"], tz_name)
            by_day.setdefault(dk, []).append(l)

        day_entries = []
        for dk in sorted(by_day.keys(), reverse=True):
            msgs = []
            for l in sorted(by_day[dk], key=lambda x: x["created_at"]):
                reply = _find_reply(pid, l["created_at"], dk, tz_name)
                msgs.append({
                    "id": str(l["_id"]),
                    "time": l["created_at"].astimezone(tz).strftime("%H:%M"),
                    "category": l.get("category"),
                    "msg_type": l.get("msg_type"),
                    "status": l.get("status"),
                    "reply_status": l.get("reply_status"),
                    "replied": reply is not None,
                    "reply": ({
                        "body": reply.get("transcription") or reply.get("body"),
                        "intent": reply.get("intent"),
                        "is_voice": reply.get("is_voice"),
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
            "name": p.get("name"),
            "days": day_entries[:days],
        })

    # ── Alerts: open emergencies + unacknowledged "need help" reengagement replies ──
    alerts = []
    parent_name_by_id = {str(p["_id"]): p.get("name") for p in parents}
    open_events = await db.emergency_events.find({"user_id": owner, "status": "open"}).sort("created_at", -1).to_list(20)
    for e in open_events:
        alerts.append({
            "kind": "emergency",
            "event_id": str(e["_id"]),
            "parent_id": str(e.get("parent_id")),
            "parent_name": parent_name_by_id.get(str(e.get("parent_id")), "Your parent"),
            "body": e.get("body"),
            "created_at": e["created_at"].isoformat(),
        })
    help_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for r in replies:
        if r.get("intent") == "reengagement:help" and r["created_at"] >= help_cutoff:
            alerts.append({
                "kind": "reengagement_help",
                "parent_id": str(r.get("parent_id")),
                "parent_name": parent_name_by_id.get(str(r.get("parent_id")), "Your parent"),
                "body": r.get("body"),
                "created_at": r["created_at"].isoformat(),
            })

    return {"parents": out_parents, "alerts": alerts}

# ---------------- WhatsApp webhook ----------------
@api.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    """Meta webhook verification handshake (one-time, during registration)."""
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
    # ── Signature verification ──
    if not whatsapp_enabled():
        # Dev mode only: allow WEBHOOK_DEV_TOKEN for local testing
        dev_token = os.environ.get("WEBHOOK_DEV_TOKEN", "").strip()
        if not dev_token:
            logger.warning("[webhook] WHATSAPP_ENABLED=false but WEBHOOK_DEV_TOKEN not set — webhook unprotected")
        provided = request.headers.get("X-Dev-Token", "")
        if provided != dev_token:
            raise HTTPException(status_code=403, detail="Invalid dev token")
    else:
        # Production mode: enforce Meta signature verification
        dev_token = os.environ.get("WEBHOOK_DEV_TOKEN", "").strip()
        if dev_token:
            logger.warning("[webhook] WEBHOOK_DEV_TOKEN is set but WHATSAPP_ENABLED=true — ignoring dev token, enforcing Meta signature")
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not verify_meta_signature(raw_body, signature):
            raise HTTPException(status_code=403, detail="Invalid Meta signature")

    # ── Parse JSON payload ──
    try:
        payload = json.loads(raw_body)
    except Exception:
        return Response(status_code=200, content="ok")

    # Meta sends various webhook types — we only care about messages
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            # Silently acknowledge status updates (delivery receipts)
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
                        # Was left empty before — meant emergency-keyword matching
                        # silently saw nothing for in-session button taps (e.g. the
                        # "Bad day 😟" button). Populate it from the button's own
                        # title for display/audit. Emergency detection itself is
                        # intent-based for button replies (see _record_reply), NOT
                        # keyword-matched against this text, since some button
                        # titles ("Some pain") contain emergency keywords without
                        # being an emergency (that button maps to feeling:not_well).
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
                    # Template quick-reply button tap
                    button_payload = message.get("button", {}).get("payload")
                    body_text = message.get("button", {}).get("text", "")

                logger.info(
                    "[webhook] Inbound from %s | type=%s | payload=%s | media=%s | body=%.60s",
                    from_number, msg_type, button_payload or "–", media_content_type or "–", body_text or "–",
                )

                # ── Structured quick-reply button handling ────────────────────
                # For in-template or in-session button taps, route through the
                # dedicated interactive button handler first. It updates
                # message_logs.reply_status and sends a confirmation text.
                # For generic template payloads (reminder_done / meal_yes etc.),
                # fall through to _record_reply which uses _resolve_generic_button_intent.
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
                    # Always still log the reply for audit / mood tracking
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
                    # Text, audio, and image messages — record reply for
                    # distress detection, mood tracking, voice transcription,
                    # and session refresh.
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
    uid = str(user["_id"])
    now = datetime.now(timezone.utc)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {
        "deleted_at": now, "name": "[deleted]",
        "email": f"deleted_{uid}@ayana.deleted", "phone": "[deleted]",
    }})
    await db.parents.update_many({"user_id": uid}, {"$set": {"deleted_at": now}})
    await db.schedules.update_many({"user_id": uid}, {"$set": {"deleted_at": now, "active": False}})
    await db.activation_state.update_one({"user_id": uid}, {"$set": {"whatsapp_activated": False}})
    await audit(uid, "delete_account")
    return {"ok": True}

@api.get("/account/audit")
async def get_my_audit(user: dict = Depends(get_current_user)):
    docs = await db.audit_logs.find({"user_id": str(user["_id"])}).sort("created_at", -1).limit(50).to_list(50)
    return [
        {"action": d["action"], "meta": d.get("meta", {}), "created_at": d["created_at"].isoformat() if hasattr(d.get("created_at"), "isoformat") else str(d.get("created_at"))}
        for d in docs
    ]

# ---------------- Admin ----------------
@api.get("/admin/stats")
async def admin_stats(admin: dict = Depends(get_current_admin)):
    total_users = await db.users.count_documents({"role": "user", "deleted_at": None})
    completed = await db.users.count_documents({"role": "user", "onboarding_complete": True, "deleted_at": None})
    activated = await db.activation_state.count_documents({"whatsapp_activated": True})
    parents = await db.parents.count_documents({"deleted_at": None})
    schedules = await db.schedules.count_documents({"deleted_at": None, "active": True})
    messages = await db.message_logs.count_documents({})
    emergencies = await db.emergency_events.count_documents({"status": "open"})
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
    limit = max(1, min(limit, 100))  # clamp: 1–100
    skip = max(0, skip)
    total = await db.users.count_documents({"role": "user"})
    users = (
        await db.users.find({"role": "user"})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    out = []
    for u in users:
        uid = str(u["_id"])
        act = await db.activation_state.find_one({"user_id": uid})
        pcount = await db.parents.count_documents({"user_id": uid, "deleted_at": None})
        scount = await db.schedules.count_documents({"user_id": uid, "deleted_at": None})
        s = serialize(u)
        s["activated"] = bool(act and act.get("whatsapp_activated"))
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
    limit = max(1, min(limit, 200))  # clamp: 1–200
    skip = max(0, skip)
    total = await db.message_logs.count_documents({})
    docs = (
        await db.message_logs.find({})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    return {"total": total, "skip": skip, "limit": limit, "items": [serialize(d) for d in docs]}


@api.get("/admin/emergencies")
async def admin_emergencies(admin: dict = Depends(get_current_admin)):
    docs = await db.emergency_events.find({}).sort("created_at", -1).to_list(200)
    return [serialize(d) for d in docs]


@api.get("/admin/schedules")
async def admin_schedules(
    admin: dict = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 50,
):
    limit = max(1, min(limit, 100))
    skip = max(0, skip)
    total = await db.schedules.count_documents({"deleted_at": None})
    docs = (
        await db.schedules.find({"deleted_at": None})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    # Enrich with parent and user names
    parent_ids = {str(d["parent_id"]) for d in docs}
    user_ids = {str(d["user_id"]) for d in docs}
    parents_map = {str(p["_id"]): p.get("name", "Unknown") for p in await db.parents.find({"_id": {"$in": [ObjectId(pid) for pid in parent_ids]}}).to_list(100)}
    users_map = {str(u["_id"]): u.get("name", "Unknown") for u in await db.users.find({"_id": {"$in": [ObjectId(uid) for uid in user_ids]}}).to_list(100)}
    out = []
    for d in docs:
        s = serialize(d)
        s["parent_name"] = parents_map.get(str(d["parent_id"]), "Unknown")
        s["user_name"] = users_map.get(str(d["user_id"]), "Unknown")
        s["message_count"] = len(d.get("messages", []))
        out.append(s)
    return {"total": total, "skip": skip, "limit": limit, "items": out}


app.include_router(api)

# Stripe payments router (endpoints are self-prefixed with /api). Kept in a
# separate module; only actually reachable when PAYMENTS_ENABLED=true.
from payments import payments_router
app.include_router(payments_router)

# Build a strict allowed-origins list.
# Default to localhost for dev; set CORS_ORIGINS=https://yourdomain.com in production.
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
    allow_headers=["Authorization", "Content-Type", "X-Hub-Signature-256", "X-Dev-Token", "Stripe-Signature", "X-CSRF-Token"],
)


# Startup and shutdown are handled by the lifespan context manager above.