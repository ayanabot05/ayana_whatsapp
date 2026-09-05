p = '/app/backend/server.py'
s = open(p).read()

anchor = '@api.put("/profile/child")\nasync def update_child('
assert s.count(anchor) == 1
block = '''# ---------------- Password reset / change (phone OTP) ----------------
_DIGITS_SQL = "regexp_replace(phone, '\\\\D', '', 'g') = regexp_replace($1, '\\\\D', '', 'g')"


async def _user_by_phone(phone: str):
    return await get_pool().fetchrow(
        f"select * from users where {_DIGITS_SQL} and deleted_at is null order by created_at asc limit 1", phone
    )


@api.post("/auth/forgot-password")
async def forgot_password(payload: ForgotPasswordInput, request: Request):
    allowed, retry_after = await check_api_rate_limit(request)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {retry_after}s.")
    user = await _user_by_phone(payload.phone)
    # Always answer the same way so phone numbers can't be enumerated.
    out = {"sent": True, "message": "If an account exists for this number, a 6-digit code has been sent on SMS."}
    if user:
        result = await create_and_send_otp(user["phone"])
        if result.get("status") == "rate_limited":
            raise HTTPException(status_code=429, detail=f"Please wait {result.get('retry_after', 60)}s before requesting another code.")
        if result.get("dev_code"):
            out["dev_code"] = result["dev_code"]
        await audit(user["id"], "password_reset_requested", {})
    return out


@api.post("/auth/reset-password")
async def reset_password(payload: ResetPasswordInput, response: Response):
    user = await _user_by_phone(payload.phone)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid code or phone number.")
    result = await verify_otp_code(user["phone"], payload.code)
    if not result.get("verified"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Invalid or expired code.")
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update users set password_hash = $1, password_changed_at = now(), phone_verified = true where id = $2",
            hash_password(payload.new_password), user["id"],
        )
    clear_auth_cookies(response)
    await audit(user["id"], "password_reset_completed", {})
    return {"ok": True, "message": "Password updated. Please log in with your new password."}


@api.post("/auth/change-password")
async def change_password(payload: ChangePasswordInput, response: Response, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one.")
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update users set password_hash = $1, password_changed_at = now() where id = $2",
            hash_password(payload.new_password), user["id"],
        )
    access = create_access_token(str(user["id"]), user["email"], user["role"])
    refresh = create_refresh_token(str(user["id"]), user["email"], user["role"])
    set_auth_cookies(response, access, refresh)
    await audit(user["id"], "password_changed", {})
    return {"ok": True}


# ---------------- Email change (password + phone OTP) ----------------
@api.post("/profile/email/request")
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
    result = await create_and_send_otp(user["phone"])
    if result.get("status") == "rate_limited":
        raise HTTPException(status_code=429, detail=f"Please wait {result.get('retry_after', 60)}s before requesting another code.")
    out = {"sent": True, "pending_email": new_email, "phone_hint": f"…{(user.get('phone') or '')[-4:]}"}
    if result.get("dev_code"):
        out["dev_code"] = result["dev_code"]
    return out


@api.post("/profile/email/confirm")
async def confirm_email_change(payload: EmailChangeConfirmInput, response: Response, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    pending = user.get("pending_email")
    if not pending:
        raise HTTPException(status_code=400, detail="No email change is pending.")
    result = await verify_otp_code(user["phone"], payload.code)
    if not result.get("verified"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Invalid or expired code.")
    old_email = user["email"]
    async with get_pool().acquire() as conn:
        taken = await conn.fetchrow("select 1 from users where lower(email) = $1 and id <> $2", pending, user["id"])
        if taken:
            raise HTTPException(status_code=400, detail="That email was just taken by another account.")
        await conn.execute("update users set email = $1, pending_email = null where id = $2", pending, user["id"])
        # Pending care-circle invites addressed to the old email follow the user.
        await conn.execute("update circle_invites set email = $1 where email = $2 and status = 'pending'", pending, old_email)
        updated = await conn.fetchrow("select * from users where id = $1", user["id"])
    # Tokens embed the email — reissue them.
    access = create_access_token(str(user["id"]), pending, user["role"])
    refresh = create_refresh_token(str(user["id"]), pending, user["role"])
    set_auth_cookies(response, access, refresh)
    await audit(user["id"], "email_changed", {"from": old_email, "to": pending})
    return {"ok": True, "user": serialize(updated)}


'''
s = s.replace(anchor, block + anchor)

# startup migration columns
a = '''        await conn.execute("alter table monthly_reports add column if not exists details jsonb")'''
b = a + '''
        await conn.execute("alter table users add column if not exists password_changed_at timestamptz")
        await conn.execute("alter table users add column if not exists pending_email text")'''
assert s.count(a) == 1
s = s.replace(a, b)
open(p, 'w').write(s)

# auth.py: iat in tokens + reject tokens issued before password change
p = '/app/backend/auth.py'
s = open(p).read()
s = s.replace('''        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TTL_MIN),
        "type": "access",''', '''        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TTL_MIN),
        "type": "access",''')
s = s.replace('''        "exp": expires_at,
        "type": "refresh",''', '''        "iat": datetime.now(timezone.utc),
        "exp": expires_at,
        "type": "refresh",''')
a = '''        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user = dict(user)
        user.pop("_revoked", None)'''
b = '''        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user = dict(user)
        user.pop("_revoked", None)
        if not token_still_valid(payload, user):
            raise HTTPException(status_code=401, detail="Session expired after password change. Please log in again.")'''
assert s.count(a) == 1
s = s.replace(a, b)
a = '''async def get_current_user(request: Request) -> dict:'''
b = '''def token_still_valid(payload: dict, user: dict) -> bool:
    """Tokens minted before the user's last password change are dead."""
    changed = user.get("password_changed_at")
    iat = payload.get("iat")
    if not changed or iat is None:
        return True
    return int(iat) >= int(changed.timestamp())


async def get_current_user(request: Request) -> dict:'''
s = s.replace(a, b, 1)
open(p, 'w').write(s)

# refresh endpoint: honour password_changed_at
p = '/app/backend/server.py'
s = open(p).read()
i = s.index('async def refresh_token(')
j = s.index('@api.', i)
seg = s[i:j]
old = '''            user = await conn.fetchrow("select * from users where id = $1::uuid", payload["sub"])'''
assert seg.count(old) == 1
seg2 = seg.replace(old, old + '''
        if user and not token_still_valid(payload, dict(user)):
            raise HTTPException(status_code=401, detail="Please log in again.")''')
s = s[:i] + seg2 + s[j:]
s = s.replace("from auth import (", "from auth import (\n    token_still_valid,", 1) if "from auth import (" in s else s
open(p, 'w').write(s)
print("ok")
