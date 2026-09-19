"""AYANA auth; extracted without changing API behaviour."""
import json
import jwt
from datetime import datetime, timezone
from fastapi import Depends, APIRouter, HTTPException, Request, Response, BackgroundTasks
from rate_limit import record_failed_login, clear_login_attempts, check_api_rate_limit
from database import get_pool
from models import RegisterInput, LoginInput, ChildProfileInput, ChangePasswordInput, EmailChangeRequestInput, EmailChangeConfirmInput
from validation import normalize_phone as _normalize_phone
from routes.account import require_email
from services import verification
from auth import token_still_valid, hash_password, verify_password, create_access_token, serialize, get_current_user, create_refresh_token, _secret, validate_csrf_token, JWT_ALGORITHM, revoke_token, set_auth_cookies, clear_auth_cookies, generate_csrf_token, set_csrf_cookie
from whatsapp import send_child_welcome
from services.deps import _get_client_ip, login_rate_check, audit


router = APIRouter()


# ---------------- Auth ----------------
@router.post("/auth/register")
async def register(request: Request, response: Response, payload: RegisterInput, background_tasks: BackgroundTasks):
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
        # Mirror _assert_phone_role_available's parent-role check here too:
        # without this, a new account can be created using a phone number
        # that's already a live parent's WhatsApp number, and the clash isn't
        # caught until the child later revisits update_child with that same
        # number (if ever).
        clash_parent = await conn.fetchrow(
            "select 1 from parents where phone = $1 and deleted_at is null", _normalize_phone(payload.phone)
        )
        if clash_parent:
            raise HTTPException(
                status_code=400,
                detail="This number is already set up as a parent receiving check-ins. Please use a different phone number for your own account.",
            )
        invite = await conn.fetchrow(
            "select * from circle_invites where email = $1 and status = 'pending'", email
        )
        household_owner_id = invite["owner_id"] if invite else None

        user_row = await conn.fetchrow(
            """
            insert into users (name, email, phone, password_hash, role, household_owner_id,
                                onboarding_complete, onboarding_step, city, timezone,
                                created_at, deleted_at, email_verification_required)
            values ($1, $2, $3, $4, 'user', $5::uuid, $6, $7, null, 'Asia/Kolkata', now(), null, true)
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
                insert into payment_state (user_id, status, plan, billing, updated_at, billing_managed)
                values ($1, 'trial', 'nitya', 'month', now(), true)
                """,
                uid,
            )

    await audit(uid, "register", {"linked_household": str(household_owner_id) if household_owner_id else None})
    # Welcome the new account owner (adult child) over WhatsApp — best-effort.
    background_tasks.add_task(send_child_welcome, dict(user_row))
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

@router.post("/auth/login")
async def login(request: Request, response: Response, payload: LoginInput):
    email = payload.email.lower()
    ip = _get_client_ip(request)

    allowed, retry_after = await login_rate_check(email, ip)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {retry_after}s.", headers={"Retry-After": str(retry_after)})

    async with get_pool().acquire() as conn:
        user = await conn.fetchrow("select * from users where email = $1", email)

    if not user or user["deleted_at"]:
        # NEW: tell them account doesn't exist
        raise HTTPException(status_code=404, detail="No account found with this email. Please create an account.")

    if not verify_password(payload.password, user["password_hash"]):
        await record_failed_login(email, ip)
        # NEW: tell them password is wrong
        raise HTTPException(status_code=401, detail="Incorrect password. Forgot your password?")

    await clear_login_attempts(email, ip)
    access_token = create_access_token(str(user["id"]), email, user["role"] or "user", user['auth_version'])
    refresh_token = create_refresh_token(str(user["id"]), email, user["role"] or "user", user['auth_version'])
    await audit(user["id"], "login")
    set_auth_cookies(response, access_token, refresh_token)
    set_csrf_cookie(response, generate_csrf_token())
    return {
        "token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": serialize(user),
    }

@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return serialize(user)

@router.post("/auth/logout")
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


@router.post("/auth/refresh")
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
        if user and not token_still_valid(payload, dict(user)):
            raise HTTPException(status_code=401, detail="Please log in again.")
        if not user or user["deleted_at"]:
            raise HTTPException(status_code=401, detail="User not found")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    new_access = create_access_token(str(user["id"]), user["email"], user["role"] or "user", user['auth_version'])
    new_refresh = create_refresh_token(str(user["id"]), user["email"], user["role"] or "user", user['auth_version'])
    await audit(user["id"], "token_refresh")
    set_auth_cookies(response, new_access, new_refresh)
    set_csrf_cookie(response, generate_csrf_token())
    return {"access_token": new_access, "refresh_token": new_refresh, "user": serialize(user)}

# ---------------- Verification is email-only (Resend) ----------------
# Phone OTP was removed. All verification flows use email codes via
# services/verification.py and routes/account.py.

# Email-based recovery routes live in routes/account.py.
@router.post("/auth/change-password")
async def change_password(payload: ChangePasswordInput, response: Response, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one.")
    async with get_pool().acquire() as conn:
        version = await conn.fetchval(
            "update users set password_hash = $1, password_changed_at = now(),auth_version=auth_version+1 where id = $2 RETURNING auth_version",
            hash_password(payload.new_password), user["id"],
        )
    access = create_access_token(str(user["id"]), user["email"], user["role"], version)
    refresh = create_refresh_token(str(user["id"]), user["email"], user["role"], version)
    set_auth_cookies(response, access, refresh)
    await audit(user["id"], "password_changed", {})
    return {"ok": True}


# ---------------- Email change (password + new-email OTP) ----------------
@router.post("/profile/email/request")
async def request_email_change(payload: EmailChangeRequestInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    new_email = payload.new_email.lower().strip()
    if new_email == (user.get("email") or "").lower():
        raise HTTPException(status_code=400, detail="That is already your email.")
    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    async with get_pool().acquire() as conn:
        taken = await conn.fetchrow("select 1 from users where lower(email) = $1 and id <> $2", new_email, user["id"])
        if taken:
            raise HTTPException(status_code=400, detail="That email is already used by another account.")
        await conn.execute("update users set pending_email = $1 where id = $2", new_email, user["id"])
    # Code goes to the NEW email itself — completing this proves the user
    # controls that inbox, which is the actual thing being changed.
    result = await verification.issue(user['id'], new_email, 'change_email', new_email, {'old_email': user['email']})
    return {**result, 'pending_email': new_email}


@router.post("/profile/email/confirm")
async def confirm_email_change(payload: EmailChangeConfirmInput, response: Response, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    pending = user.get("pending_email")
    if not pending:
        raise HTTPException(status_code=400, detail="No email change is pending.")
    proof = await verification.check(payload.challenge_id, payload.code, user['id'], 'change_email', pending)
    old_email = user["email"]
    async with get_pool().acquire() as conn, conn.transaction():
        current = await conn.fetchrow('SELECT * FROM users WHERE id=$1 FOR UPDATE',user['id'])
        context = json.loads(proof['context']) if isinstance(proof['context'],str) else proof['context']
        if current['email'] != context['old_email'] or current['pending_email'] != proof['target']:
            raise HTTPException(409,'Your contact details changed. Request a fresh email code.')
        await verification.consume(conn, proof)
        taken = await conn.fetchrow("select 1 from users where lower(email) = $1 and id <> $2", pending, user["id"])
        if taken:
            raise HTTPException(status_code=400, detail="That email was just taken by another account.")
        await conn.execute("update users set email = $1, pending_email = null, email_verified_at=now(), email_verification_required=false,auth_version=auth_version+1 where id = $2", pending, user["id"])
        await conn.execute("update circle_invites set email = $1 where email = $2 and status = 'pending'", pending, old_email)
        updated = await conn.fetchrow("select * from users where id = $1", user["id"])
    access = create_access_token(str(user["id"]), pending, user["role"], updated['auth_version'])
    refresh = create_refresh_token(str(user["id"]), pending, user["role"], updated['auth_version'])
    set_auth_cookies(response, access, refresh)
    await audit(user["id"], "email_changed", {"from": old_email, "to": pending})
    return {"ok": True, "user": serialize(updated)}


@router.put("/profile/child")
async def update_child(
    payload: ChildProfileInput,
    user: dict = Depends(get_current_user),
    _csrf: None = Depends(validate_csrf_token),
):
    phone = payload.phone.strip()

    normalized = _normalize_phone(phone)
    require_email(user)
    if _normalize_phone(user['phone']) != normalized:
        raise HTTPException(
            status_code=409,
            detail="Confirm this WhatsApp-number change through email in Account settings first.",
        )
    async with get_pool().acquire() as conn:
        clash_parent = await conn.fetchrow(
            "select 1 from parents where phone = $1 and deleted_at is null", normalized
        )
        if clash_parent:
            raise HTTPException(
                status_code=400,
                detail="This number is already set up as a parent receiving check-ins. Your own login number must be different from your parent's.",
            )
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


# ---------------- Account ----------------
@router.delete("/account")
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

@router.get("/account/audit")
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
