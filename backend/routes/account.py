"""Email verification, recovery and explicitly authorized contact changes."""
import json
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from auth import get_current_user, validate_csrf_token, hash_password, clear_auth_cookies, serialize
from database import get_pool
from rate_limit import api_rate_limit_dependency
from services import verification
from services.welcomes import welcome_parent_and_child
from validation import validate_phone

router = APIRouter(prefix='/api', tags=['Account verification'])


class CodeInput(BaseModel):
    challenge_id: uuid.UUID
    code: str = Field(pattern=r'^\d{6}$')


class PhoneRequest(BaseModel):
    phone: str
    confirmed: bool


class EmailInput(BaseModel):
    email: EmailStr


class ResetInput(CodeInput, EmailInput):
    new_password: str = Field(min_length=8, max_length=128)


def require_email(user):
    # Legacy customers retain access; never mark their unverified inbox verified.
    if user.get('email_verification_required') and not user.get('email_verified_at'):
        raise HTTPException(403, 'Please verify your email before completing care setup.')


@router.post('/auth/email/request', dependencies=[Depends(validate_csrf_token), Depends(api_rate_limit_dependency)])
async def request_verification(user=Depends(get_current_user)):
    return await verification.issue(user['id'], user['email'], 'verify_email', user['email'])


@router.post('/auth/email/verify', dependencies=[Depends(validate_csrf_token)])
async def verify_email(payload: CodeInput, user=Depends(get_current_user)):
    proof = await verification.check(payload.challenge_id, payload.code, user['id'], 'verify_email', user['email'])
    async with get_pool().acquire() as conn, conn.transaction():
        await verification.consume(conn, proof)
        updated = await conn.fetchrow("UPDATE users SET email_verified_at=now(), email_verification_required=false WHERE id=$1 AND email=$2 RETURNING *", user['id'], proof['email'])
        if not updated:
            raise HTTPException(409, 'Your email changed. Request a new verification code.')
    return {'verified': True, 'user': serialize(updated)}


@router.post('/profile/phone/request', dependencies=[Depends(validate_csrf_token), Depends(api_rate_limit_dependency)])
async def request_phone_change(payload: PhoneRequest, user=Depends(get_current_user)):
    if not payload.confirmed:
        raise HTTPException(400, 'Please confirm that this is your WhatsApp number and future updates should go there.')
    try:
        phone = validate_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if phone == validate_phone(user['phone']):
        raise HTTPException(400, 'That is already your WhatsApp number.')
    await assert_phone_available(get_pool(), phone, user['id'])
    return await verification.issue(user['id'], user['email'], 'change_phone', phone, {'old_phone': user['phone'], 'email': user['email']})


async def assert_phone_available(conn, phone, user_id):
    digits = phone.replace('+', '')
    clash = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM users WHERE regexp_replace(phone,'[^0-9]','','g')=$1 AND id<>$2 AND deleted_at IS NULL) OR EXISTS(SELECT 1 FROM parents WHERE regexp_replace(phone,'[^0-9]','','g')=$1 AND deleted_at IS NULL)", digits, user_id)
    if clash:
        raise HTTPException(409, 'That number is already used by another account or parent.')


@router.post('/profile/phone/confirm', dependencies=[Depends(validate_csrf_token)])
async def confirm_phone_change(payload: CodeInput, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    row = await get_pool().fetchrow('SELECT target FROM verification_challenges WHERE id=$1 AND user_id=$2', payload.challenge_id, user['id'])
    if not row:
        raise HTTPException(400, 'Invalid email code request.')
    proof = await verification.check(payload.challenge_id, payload.code, user['id'], 'change_phone', row['target'])
    context = json.loads(proof['context']) if isinstance(proof['context'], str) else proof['context']
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'recipient:' + str(user['id']))
        current = await conn.fetchrow('SELECT * FROM users WHERE id=$1 FOR UPDATE', user['id'])
        if current['phone'] != context['old_phone'] or current['email'] != context['email']:
            raise HTTPException(409, 'Your contact details changed. Request a fresh code.')
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'phone:' + proof['target'])
        await assert_phone_available(conn, proof['target'], user['id'])
        await verification.consume(conn, proof)
        updated = await conn.fetchrow("UPDATE users SET phone=$2,phone_changed_at=now(),email_verified_at=now(),email_verification_required=false WHERE id=$1 RETURNING *", user['id'], proof['target'])
        # Sibling records with a verified matching email represent the same person.
        await conn.execute('UPDATE care_circle_siblings SET phone=$2 WHERE lower(email)=lower($1) AND email_verified_at IS NOT NULL', current['email'], proof['target'])
        await conn.execute("INSERT INTO audit_logs(user_id,action,meta) VALUES($1,'phone_changed',$2::jsonb)", user['id'], json.dumps({'old_last4':current['phone'][-4:], 'new_last4':proof['target'][-4:]}))
        # Re-send the WhatsApp opener to the child's NEW number for every active
        # parent so the 24h window opens on the new phone. welcome_deliveries
        # keys on (child_id + new_phone_hash), so old-phone welcomes are not
        # short-circuited by idempotency.
        active_parents = await conn.fetch(
            "SELECT p.* FROM parents p JOIN activation_state a ON a.user_id=p.user_id "
            "WHERE p.user_id=$1 AND p.deleted_at IS NULL AND a.whatsapp_activated=true",
            user['id'],
        )
    updated_dict = dict(updated)
    for parent in active_parents:
        background_tasks.add_task(welcome_parent_and_child, dict(parent), updated_dict, True)
    return {'ok': True, 'user': serialize(updated), 'message': 'Future notifications will use your new WhatsApp number. Messages already submitted cannot be recalled.'}


@router.post('/auth/forgot-password', dependencies=[Depends(api_rate_limit_dependency)])
async def forgot_password(payload: EmailInput):
    from email_sender import email_enabled
    import os
    if not email_enabled() or not os.environ.get('RESEND_API_KEY') or not os.environ.get('EMAIL_FROM'):
        raise HTTPException(503, 'Email verification is not available right now. Please try again later.')
    user = await get_pool().fetchrow('SELECT * FROM users WHERE lower(email)=$1 AND deleted_at IS NULL', payload.email.lower())
    result = {'challenge_id': str(uuid.uuid4())}
    if user:
        try:
            result = await verification.issue(user['id'], user['email'], 'reset_password', user['email'])
        except HTTPException:
            # Do not reveal account existence via delivery or per-inbox rate errors.
            pass
    return {'challenge_id': result['challenge_id'], 'message': 'If this email belongs to an account, check its inbox for a verification code.'}


@router.post('/auth/reset-password', dependencies=[Depends(api_rate_limit_dependency)])
async def reset_password(payload: ResetInput, response: Response):
    from validation import validate_password
    try:
        password = validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    user = await get_pool().fetchrow('SELECT * FROM users WHERE lower(email)=$1 AND deleted_at IS NULL', payload.email.lower())
    if not user:
        raise HTTPException(400, 'Invalid or expired email code.')
    proof = await verification.check(payload.challenge_id, payload.code, user['id'], 'reset_password', user['email'])
    async with get_pool().acquire() as conn, conn.transaction():
        await verification.consume(conn, proof)
        updated = await conn.fetchval('UPDATE users SET password_hash=$2,password_changed_at=now(),auth_version=auth_version+1,email_verified_at=now(),email_verification_required=false WHERE id=$1 AND email=$3 RETURNING id', user['id'], hash_password(password), proof['email'])
        if not updated:
            raise HTTPException(409,'Your email changed. Request a fresh password-reset code.')
    clear_auth_cookies(response)
    return {'ok': True, 'message': 'Password changed. Please log in again.'}