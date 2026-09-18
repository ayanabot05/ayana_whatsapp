"""Purpose-bound, single-use email authorization. No SMS or onscreen codes.

Invalid guesses commit independently; callers consume a valid challenge in the
same transaction as the protected change. Never log or return plaintext codes.
"""
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from database import get_pool
from email_sender import send_otp_email


def digest(challenge_id, code):
    return hmac.new(os.environ['JWT_SECRET'].encode(), f'{challenge_id}:{code}'.encode(), hashlib.sha256).hexdigest()


async def issue(user_id, email, purpose, target, context=None):
    email = email.strip().lower()
    challenge_id = uuid.uuid4()
    code = f'{secrets.randbelow(1_000_000):06d}'
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', 'email-otp:' + email)
        recent = await conn.fetchrow("SELECT count(*) AS n, max(created_at) AS last FROM verification_challenges WHERE email=$1 AND created_at > now()-interval '10 minutes'", email)
        if recent['n'] >= 3 or (recent['last'] and recent['last'] > datetime.now(timezone.utc)-timedelta(seconds=60)):
            raise HTTPException(429, 'Please wait before requesting another code.', headers={'Retry-After': '60'})
        await conn.execute("UPDATE verification_challenges SET consumed_at=now() WHERE user_id=$1 AND purpose=$2 AND consumed_at IS NULL", user_id, purpose)
        await conn.execute("INSERT INTO verification_challenges(id,user_id,purpose,email,target,code_hash,context,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8)", challenge_id, user_id, purpose, email, target, digest(challenge_id,code), json.dumps(context or {}), expires)
    result = await send_otp_email(email, code)
    delivered = result.get('status') == 'sent'
    await get_pool().execute('UPDATE verification_challenges SET delivered=$2 WHERE id=$1', challenge_id, delivered)
    if not delivered:
        raise HTTPException(503, 'Verification email could not be sent. Your account details have not changed. Please try again later.')
    return {'sent': True, 'challenge_id': str(challenge_id), 'expires_at': expires.isoformat(), 'channel': 'email', 'retry_after_seconds': 60}


async def check(challenge_id, code, user_id, purpose, target):
    """Validate and charge every guess durably, returning a proof for consume()."""
    valid = False
    async with get_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow('SELECT * FROM verification_challenges WHERE id=$1 FOR UPDATE', challenge_id)
        if row and row['user_id'] == user_id and row['purpose'] == purpose and row['target'] == target:
            if row['delivered'] and not row['consumed_at'] and row['expires_at'] > datetime.now(timezone.utc) and row['attempts'] < 5:
                await conn.execute('UPDATE verification_challenges SET attempts=attempts+1 WHERE id=$1', challenge_id)
                valid = hmac.compare_digest(row['code_hash'], digest(challenge_id,code))
    if not valid:
        raise HTTPException(400, 'Invalid, expired or already used email code.')
    return dict(row)


async def consume(conn, proof):
    consumed = await conn.fetchval("UPDATE verification_challenges SET consumed_at=now() WHERE id=$1 AND consumed_at IS NULL AND delivered AND expires_at>now() RETURNING id", proof['id'])
    if not consumed:
        raise HTTPException(409, 'This email code has expired or was already used. Request a new code.')