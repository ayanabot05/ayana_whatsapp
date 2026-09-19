"""Two coupon families, both hashed and never stored as plaintext:

- kind='lifetime': the three founder/friend gifts. Single-use, email-bound,
  assigned via /admin/coupons PATCH before they become redeemable.
- kind='annual_discount': self-service percent-off codes created via
  /admin/coupons POST, with an expiry date and a redemption limit shared
  across up to N different accounts (tracked in billing_coupon_redemptions
  so the same account can't redeem twice).
"""
import hashlib
import re
from datetime import datetime, timezone
from fastapi import HTTPException


def normalize(code):
    return re.sub(r'\s+','',code or '').upper()


def code_hash(code):
    return hashlib.sha256(normalize(code).encode()).hexdigest()


async def validate(conn,code,user,plan,billing,lock=False):
    if not code:
        return None
    coupon = await conn.fetchrow('SELECT * FROM billing_coupons WHERE code_hash=$1'+(' FOR UPDATE' if lock else ''),code_hash(code))
    if not coupon or not coupon['active']:
        raise HTTPException(400,'This coupon is invalid or has not been activated by the account owner.')

    if coupon['kind']=='lifetime':
        if coupon['redeemed_by']:
            raise HTTPException(409,'This single-use coupon has already been redeemed.')
        if coupon['reserved_by'] and coupon['reserved_by']!=user['id']:
            raise HTTPException(409,'This coupon is reserved for another account.')
        if coupon['allowed_email'] and coupon['allowed_email'].lower()!=user['email'].lower():
            raise HTTPException(403,'This coupon is assigned to a different email account.')
        if not user.get('email_verified_at'):
            raise HTTPException(403,'Verify your account email before redeeming an email-bound lifetime gift.')
        if not coupon['allowed_email']:
            raise HTTPException(400,'The owner must assign an email before enabling free access.')
        if plan!='raksha':
            raise HTTPException(400,'This lifetime code is for Raksha. Choose Raksha to redeem it.')
        return dict(coupon)

    # kind == 'annual_discount' — multi-use, expiring, percent-off
    if coupon['expires_at'] and coupon['expires_at']<datetime.now(timezone.utc):
        raise HTTPException(400,'This coupon has expired.')
    if coupon['redeemed_count']>=coupon['max_redemptions']:
        raise HTTPException(400,'This coupon has reached its usage limit.')
    already = await conn.fetchval(
        'SELECT 1 FROM billing_coupon_redemptions WHERE coupon_id=$1 AND user_id=$2',coupon['id'],user['id'],
    )
    if already:
        raise HTTPException(409,'You have already used this coupon.')
    if billing!='year':
        raise HTTPException(400,'This coupon applies to an annual plan only.')
    return dict(coupon)