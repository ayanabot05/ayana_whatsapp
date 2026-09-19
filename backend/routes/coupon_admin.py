"""Owner/admin controls: assign the three lifetime gifts before they become
redeemable, and create/manage multi-use percent-off coupons (percent, days
valid, user limit)."""
import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from auth import require_admin, validate_csrf_token, serialize
from database import get_pool

router = APIRouter(prefix='/api/admin/coupons',tags=['Coupon administration'])


def _normalize(code):
    return re.sub(r'\s+','',code or '').upper()


def _code_hash(code):
    return hashlib.sha256(_normalize(code).encode()).hexdigest()


def _gen_code():
    return secrets.token_hex(4).upper()


class Assignment(BaseModel):
    email: EmailStr | None = None
    active: bool


class CreateCoupon(BaseModel):
    label: str
    percent: int
    days_valid: int | None = None
    max_redemptions: int = 1
    code: str | None = None


@router.get('')
async def list_coupons(user=Depends(require_admin)):
    rows = await get_pool().fetch(
        'SELECT id,label,code_hint,kind,percent,allowed_email,active,reserved_by,redeemed_at,'
        'expires_at,max_redemptions,redeemed_count,created_at '
        'FROM billing_coupons ORDER BY created_at,label'
    )
    return [serialize(row) for row in rows]


@router.post('',dependencies=[Depends(validate_csrf_token)])
async def create_coupon(payload:CreateCoupon,user=Depends(require_admin)):
    """Creates a multi-use, self-service annual_discount coupon: you set the
    percent off, how many days it stays valid, and how many different
    accounts may redeem it. The plaintext code is returned once, here, and
    never stored — copy it before leaving this response."""
    if not (1<=payload.percent<=100):
        raise HTTPException(400,'Percent must be between 1 and 100.')
    if payload.max_redemptions<1:
        raise HTTPException(400,'User limit must be at least 1.')
    plaintext = payload.code or _gen_code()
    expires_at = (datetime.now(timezone.utc)+timedelta(days=payload.days_valid)) if payload.days_valid else None
    coupon_id = uuid.uuid4()
    async with get_pool().acquire() as conn:
        existing = await conn.fetchval('SELECT 1 FROM billing_coupons WHERE code_hash=$1',_code_hash(plaintext))
        if existing:
            raise HTTPException(409,'That code already exists — choose another.')
        await conn.execute(
            """INSERT INTO billing_coupons
               (id,code_hash,code_hint,label,kind,percent,active,expires_at,max_redemptions,redeemed_count,created_at)
               VALUES ($1,$2,$3,$4,'annual_discount',$5,true,$6,$7,0,now())""",
            coupon_id,_code_hash(plaintext),plaintext[-4:],payload.label,payload.percent,expires_at,payload.max_redemptions,
        )
        await conn.execute(
            "INSERT INTO audit_logs(user_id,action,meta) VALUES($1,'coupon_created',$2::jsonb)",
            user['id'],json.dumps({'coupon_id':str(coupon_id),'label':payload.label,'percent':payload.percent}),
        )
    return {
        'ok':True,'coupon_id':str(coupon_id),'code':plaintext,'percent':payload.percent,
        'expires_at':expires_at.isoformat() if expires_at else None,'max_redemptions':payload.max_redemptions,
    }


@router.patch('/{coupon_id}',dependencies=[Depends(validate_csrf_token)])
async def assign(coupon_id:uuid.UUID,payload:Assignment,user=Depends(require_admin)):
    """Unchanged: assigns/activates the three single-use lifetime gift codes.
    Only applies to kind='lifetime' coupons — multi-use percent coupons from
    /admin/coupons POST above don't need this step, they're active on creation."""
    async with get_pool().acquire() as conn,conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('coupon-assignments',0))")
        coupon = await conn.fetchrow('SELECT * FROM billing_coupons WHERE id=$1 FOR UPDATE',coupon_id)
        if not coupon:
            raise HTTPException(404,'Coupon not found.')
        if coupon['reserved_by'] or coupon['redeemed_at']:
            raise HTTPException(409,'A reserved or redeemed coupon cannot be reassigned.')
        email = str(payload.email).lower() if payload.email else None
        if coupon['kind']=='lifetime' and payload.active and not email:
            raise HTTPException(400,'Assign the recipient email before activating lifetime access.')
        if coupon['kind']=='lifetime' and email and await conn.fetchval("SELECT 1 FROM billing_coupons WHERE kind='lifetime' AND lower(allowed_email)=$1 AND id<>$2",email,coupon_id):
            raise HTTPException(409,'That email already has a lifetime gift assigned.')
        await conn.execute('UPDATE billing_coupons SET allowed_email=$2,active=$3 WHERE id=$1',coupon_id,email,payload.active)
        await conn.execute("INSERT INTO audit_logs(user_id,action,meta) VALUES($1,'coupon_assignment',$2::jsonb)",user['id'],json.dumps({'coupon_id':str(coupon_id),'active':payload.active}))
    return {'ok':True}