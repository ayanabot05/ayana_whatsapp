"""AYANA parents; extracted without changing API behaviour."""
import asyncpg
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, APIRouter, HTTPException, Query, Response, File, UploadFile, BackgroundTasks
import base64
import uuid
import hashlib
from io import BytesIO
from PIL import Image
from database import get_pool
from models import ParentInput, EmergencyContactsInput, MomentInput, VacationInput, EmergencyEventUpdate
from storage import put_object, get_object, signed_url as storage_signed_url, is_enabled as storage_enabled, APP_NAME as STORAGE_APP_NAME
from validation import normalize_phone as _normalize_phone
from services.welcomes import welcome_parent_and_child
from auth import serialize, get_current_user, get_current_admin, validate_csrf_token
from pricing import plan_limits, resolve_plan_id
from whatsapp import send_moment, send_parent_goodbye, send_parent_removed_child_notice
from services.deps import audit, scope, _sync_medicine_reminders_for_parent


logger = logging.getLogger("ayana")

router = APIRouter()


# ---------------- Parents ----------------
_PARENT_FIELDS = [
    "name", "preferred_name", "relationship", "language", "city", "timezone",
    "birthday", "other_parent_name", "phone", "nicknames", "habits", "stories",
    "medicine_list", "emergency_contacts", "activity_window_start", "activity_window_end",
    "auto_activity_detection", "vacation_start", "vacation_end",
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


async def _assert_phone_role_available(conn, acting_user: dict, phone: str, exclude_parent_id: str | None = None):
    """
    Enforce a single role per phone number so the same person can't be
    registered as both a child (account) and a parent, and so a parent's
    WhatsApp number can't be reused across households.

      1. A parent's number must differ from the account owner's own number.
      2. A parent's number must not belong to any registered account (child).
      3. A parent's number must not already be an active parent elsewhere.
    """
    norm = _normalize_phone(phone)

    owner_phone = acting_user.get("phone")
    if owner_phone and _normalize_phone(owner_phone) == norm:
        raise HTTPException(
            status_code=400,
            detail="This is your own number. A parent must be a different person — please enter your parent's WhatsApp number.",
        )

    clash_user = await conn.fetchrow(
        "select 1 from users where phone = $1 and id <> $2::uuid and deleted_at is null",
        norm, acting_user["id"],
    )
    if clash_user:
        raise HTTPException(
            status_code=400,
            detail="This number already belongs to an AYANA account holder. A parent's number can't be someone's login number.",
        )

    clash_parent = await conn.fetchrow(
        "select 1 from parents where phone = $1 and deleted_at is null and ($2::uuid is null or id <> $2::uuid)",
        norm, exclude_parent_id,
    )
    if clash_parent:
        raise HTTPException(
            status_code=400,
            detail="This number is already set up as a parent receiving check-ins. Each parent's WhatsApp number can only be used once.",
        )


def _raise_if_phone_unique_violation(exc: Exception):
    """
    Translate a idx_parents_phone_unique violation (the DB-level backstop for
    _assert_phone_role_available, hit only under a genuine race between two
    concurrent requests) into the same friendly 400 the app-layer check
    gives on the non-race path, instead of an unhandled 500.
    """
    if isinstance(exc, asyncpg.UniqueViolationError) and "idx_parents_phone_unique" in (exc.constraint_name or ""):
        raise HTTPException(
            status_code=400,
            detail="This number is already set up as a parent receiving check-ins. Each parent's WhatsApp number can only be used once.",
        ) from exc
    raise exc


@router.get("/parents")
async def list_parents(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from parents where user_id = $1 and deleted_at is null limit 50", scope(user)
        )
    return [serialize(d) for d in docs]

@router.post("/parents")
async def create_parent(payload: ParentInput, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
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
        await _assert_phone_role_available(conn, user, payload.phone)
        doc = payload.model_dump()
        doc["phone"] = _normalize_phone(doc["phone"])  # store digits in canonical +E164 form
        values, cols, placeholders = _parent_insert_values(doc)
        values.append(uid)
        try:
            row = await conn.fetchrow(
                f"""
                insert into parents (user_id, {cols}, created_at, deleted_at)
                values (${len(values)}, {placeholders}, now(), null)
                returning *
                """,
                *values,
            )
        except asyncpg.UniqueViolationError as e:
            _raise_if_phone_unique_violation(e)
        await conn.execute(
            "update users set onboarding_step = greatest(onboarding_step, 3) where id = $1", user["id"]
        )

    await audit(user["id"], "create_parent", {"parent_id": str(row["id"])})

    # Sprint fix ("welcome to mom didn't fire"): welcome fires for EVERY parent
    # added — per parent, not once per account. Both sides: warm bilingual
    # WhatsApp to the parent + setup confirmation to the child.
    background_tasks.add_task(welcome_parent_and_child, dict(row), dict(user), True)

    out = serialize(row)
    out["welcome_sent"] = True
    return out

@router.put("/parents/{parent_id}")
async def update_parent(parent_id: str, payload: ParentInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")

        update_data = payload.model_dump(exclude_unset=True)
        if "phone" in update_data:
            await _assert_phone_role_available(conn, user, update_data["phone"], exclude_parent_id=parent_id)
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
                try:
                    await conn.execute(
                        f"update parents set {', '.join(set_clauses)} where id = ${len(values)}::uuid and deleted_at is null",
                        *values,
                    )
                except asyncpg.UniqueViolationError as e:
                    _raise_if_phone_unique_violation(e)

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

@router.delete("/parents/{parent_id}")
async def delete_parent(parent_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        activation = await conn.fetchrow("select whatsapp_activated from activation_state where user_id = $1", scope(user))
        await conn.execute(
            "update parents set deleted_at = now() where id = $1::uuid and user_id = $2",
            parent_id, scope(user),
        )
        await conn.execute(
            "update schedules set deleted_at = now(), active = false where parent_id = $1::uuid",
            parent_id,
        )
    # Warm farewell to the parent (only if they were live), and always let the
    # child know check-ins for this parent have stopped.
    if parent:
        if activation and activation["whatsapp_activated"]:
            background_tasks.add_task(send_parent_goodbye, dict(parent))
        if user.get("phone"):
            background_tasks.add_task(send_parent_removed_child_notice, user.get("phone"), "en", parent["name"])
    return {"ok": True}


# ── #9 Vacation / holiday mode ──────────────────────────────────────────────



@router.put("/parents/{parent_id}/vacation")
async def set_vacation(parent_id: str, payload: VacationInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    """Pause (or clear) daily sends for a date range. The scheduler skips all
    sends while today (parent-local) is within [start, end] and auto-resumes."""
    start, end = payload.start, payload.end
    if bool(start) != bool(end):
        raise HTTPException(status_code=400, detail="Set both a start and end date, or clear both.")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="Vacation start date must be on or before the end date.")
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent not found")
        await conn.execute(
            "update parents set vacation_start = $1, vacation_end = $2 where id = $3::uuid",
            start, end, parent_id,
        )
    await audit(user["id"], "set_vacation", {"parent_id": parent_id, "start": start, "end": end})
    return {"ok": True, "vacation_start": start, "vacation_end": end}

# ---------------- Emergency contacts (distinct from Care Circle) ----------------
@router.get("/parents/{parent_id}/emergency-contacts")
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

@router.put("/parents/{parent_id}/emergency-contacts")
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

@router.get("/parents/{parent_id}/emergency-events")
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



@router.put("/emergency-events/{event_id}")
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

@router.put("/admin/emergency-events/{event_id}")
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
@router.post("/moments/upload-image")
async def upload_moment_image(file: UploadFile = File(...), user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if not storage_enabled():
        raise HTTPException(
            status_code=501,
            detail="Photo sharing is temporarily unavailable — we're setting up secure image hosting. Text moments still work.",
        )
    MAX_SIZE = int(4.5 * 1024 * 1024)  # Meta ceiling is 5MB — hard cap below it
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
    MAX_DIMENSION = 2400  # lighter compression: was 1200px

    content_type = file.content_type or "application/octet-stream"
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="Image too large. Maximum 4.5 MB per image.")

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
        img.save(buffer, format="JPEG", quality=92, optimize=True)
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

    try:
        url = storage_signed_url(result.get("path", storage_path))
    except Exception as e:
        logger.warning("[moment] signed url failed, falling back to proxy url: %s", e)
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


@router.get("/uploads/signed/{filename}")
async def serve_uploaded_image(filename: str, sig: str = Query(...), exp: int = Query(...)):
    if not storage_enabled():
        raise HTTPException(status_code=404, detail="Image not found")
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

@router.get("/moments/quota")
async def moments_quota(user: dict = Depends(get_current_user)):
    used = await _moments_used_this_month(scope(user))
    return {"used": used, "limit": MOMENTS_PER_MONTH, "remaining": max(MOMENTS_PER_MONTH - used, 0)}

@router.post("/moments")
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
            insert into moments (user_id, parent_id, sender_name, text, image_url, image_urls, status, sid, created_at)
            values ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, now())
            returning *
            """,
            scope(user), parent["id"], sender_name, payload.text, payload.image_url,
            json.dumps(payload.image_urls), (result or {}).get("status"), (result or {}).get("sid"),
        )
    remaining = max(MOMENTS_PER_MONTH - (used + 1), 0)
    return {"ok": True, "status": (result or {}).get("status"), "moment": serialize(moment_row), "remaining": remaining, "limit": MOMENTS_PER_MONTH}

@router.get("/moments")
async def list_moments(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        docs = await conn.fetch(
            "select * from moments where user_id = $1 order by created_at desc limit 100", scope(user)
        )
    return [serialize(d) for d in docs]


@router.get("/parents/{parent_id}/language-suggestion")
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


@router.put("/parents/{parent_id}/language")
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
