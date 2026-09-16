"""Owner/admin controls: assign the three gifts before they become redeemable."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from auth import require_admin, validate_csrf_token, serialize
from database import get_pool

router = APIRouter(prefix='/api/admin/coupons',tags=['Coupon administration'])


class Assignment(BaseModel):
    email: EmailStr | None = None
    active: bool


@router.get('')
async def list_coupons(user=Depends(require_admin)):
    rows = await get_pool().fetch('SELECT id,label,code_hint,kind,percent,allowed_email,active,reserved_by,redeemed_at FROM billing_coupons ORDER BY created_at,label')
    return [serialize(row) for row in rows]


@router.patch('/{coupon_id}',dependencies=[Depends(validate_csrf_token)])
async def assign(coupon_id:uuid.UUID,payload:Assignment,user=Depends(require_admin)):
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
        await conn.execute("INSERT INTO audit_logs(user_id,action,meta) VALUES($1,'coupon_assignment',$2::jsonb)",user['id'],__import__('json').dumps({'coupon_id':str(coupon_id),'active':payload.active}))
    return {'ok':True}