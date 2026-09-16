"""Single-account gifts and single-use annual discounts. Codes never grant login."""
import hashlib
import re
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
    if coupon['redeemed_by']:
        raise HTTPException(409,'This single-use coupon has already been redeemed.')
    if coupon['reserved_by'] and coupon['reserved_by']!=user['id']:
        raise HTTPException(409,'This coupon is reserved for another account.')
    if coupon['allowed_email'] and coupon['allowed_email'].lower()!=user['email'].lower():
        raise HTTPException(403,'This coupon is assigned to a different email account.')
    if coupon['kind']=='lifetime':
        if not user.get('email_verified_at'):
            raise HTTPException(403,'Verify your account email before redeeming an email-bound lifetime gift.')
        if not coupon['allowed_email']:
            raise HTTPException(400,'The owner must assign an email before enabling free access.')
        if plan!='raksha':
            raise HTTPException(400,'This lifetime code is for Raksha. Choose Raksha to redeem it.')
    else:
        if billing!='year':
            raise HTTPException(400,'This 25% coupon applies to an annual plan only.')
        used = await conn.fetchval("SELECT 1 FROM billing_coupons WHERE kind='annual_discount' AND id<>$1 AND (redeemed_by=$2 OR reserved_by=$2)",coupon['id'],user['id'])
        if used:
            raise HTTPException(409,'Only one of these annual friend offers can be used per account.')
    return dict(coupon)