"""Public checkout contracts, authenticated order ownership and verified webhooks."""
import hashlib
import hmac
import json
import os
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from auth import get_current_user, validate_csrf_token, serialize
from database import get_pool
from rate_limit import api_rate_limit_dependency
from routes.account import require_email
from services import billing_access, checkout, razorpay_gateway as gateway

router = APIRouter(prefix='/api',tags=['Checkout'])


class QuoteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan: str
    billing: Literal['month','year']
    currency: str
    coupon_code: str = Field('',max_length=80)


class OrderInput(QuoteInput):
    idempotency_key: uuid.UUID


class VerifyInput(BaseModel):
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    razorpay_signature: str | None = None


def owner_only(user):
    if user.get('household_owner_id'):
        raise HTTPException(403,'Only the account owner can manage billing.')
    require_email(user)


@router.get('/payment/config')
async def payment_config():
    return {'provider':'razorpay','enabled':gateway.enabled(),'key_id':os.environ.get('RAZORPAY_KEY_ID'),'test_mode':gateway.test_mode(),'currencies':checkout.currencies(),'auto_renews':False,'checkout_script':'https://checkout.razorpay.com/v1/checkout.js'}


@router.post('/payment/quote',dependencies=[Depends(validate_csrf_token),Depends(api_rate_limit_dependency)])
async def quote(payload:QuoteInput,user=Depends(get_current_user)):
    owner_only(user)
    async with get_pool().acquire() as conn:
        return serialize(await checkout.quote(conn,user,payload.plan,payload.billing,payload.currency,payload.coupon_code))


@router.post('/create-order',dependencies=[Depends(validate_csrf_token),Depends(api_rate_limit_dependency)])
async def create_order(payload:OrderInput,user=Depends(get_current_user)):
    owner_only(user)
    order = await checkout.create(user,payload)
    return {**serialize(order),'local_order_id':str(order['id']),'order_id':order['gateway_order_id'],'key_id':os.environ.get('RAZORPAY_KEY_ID')}


@router.post('/verify-payment',dependencies=[Depends(validate_csrf_token),Depends(api_rate_limit_dependency)])
async def verify_payment(payload:VerifyInput,user=Depends(get_current_user)):
    owner_only(user)
    if not all((payload.razorpay_order_id,payload.razorpay_payment_id,payload.razorpay_signature)):
        raise HTTPException(400,'Payment id, order id and signature are required.')
    order = await get_pool().fetchrow('SELECT * FROM billing_orders WHERE gateway_order_id=$1 AND user_id=$2',payload.razorpay_order_id,user['id'])
    if not order:
        raise HTTPException(404,'Payment order not found for this account.')
    if not gateway.valid_signature(order['gateway_order_id'],payload.razorpay_payment_id,payload.razorpay_signature):
        raise HTTPException(400,'Invalid payment signature. Your plan has not been marked paid.')
    try:
        payment = await gateway.fetch_payment(payload.razorpay_payment_id)
        remote = await gateway.fetch_order(order['gateway_order_id'])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503,'Signature verified, but payment status is unavailable. Do not pay again; check the order status shortly.')
    return serialize(await checkout.fulfill(order['id'],payment,remote))


@router.get('/payment/orders')
async def orders(user=Depends(get_current_user)):
    owner_only(user)
    rows = await get_pool().fetch('SELECT * FROM billing_orders WHERE user_id=$1 ORDER BY created_at DESC LIMIT 30',user['id'])
    return [serialize(checkout.public_order(dict(row))) for row in rows]


@router.post('/payment/orders/{local_id}/recheck',dependencies=[Depends(validate_csrf_token),Depends(api_rate_limit_dependency)])
async def recheck(local_id:uuid.UUID,user=Depends(get_current_user)):
    owner_only(user)
    order = await get_pool().fetchrow('SELECT * FROM billing_orders WHERE id=$1 AND user_id=$2',local_id,user['id'])
    if not order:
        raise HTTPException(404,'Order not found.')
    return serialize(await checkout.reconcile(order))


@router.get('/payment/access')
async def payment_access(user=Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        return serialize(await billing_access.access(conn,user.get('household_owner_id') or user['id']))


@router.post('/payment/trial',dependencies=[Depends(validate_csrf_token)])
async def choose_trial(payload:QuoteInput,user=Depends(get_current_user)):
    owner_only(user)
    from pricing import PLAN_BY_ID
    if payload.plan not in PLAN_BY_ID or payload.coupon_code:
        raise HTTPException(400,'Choose a valid trial plan. Redeem coupons through checkout instead.')
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','billing:'+str(user['id']))
        state = await conn.fetchrow('SELECT * FROM payment_state WHERE user_id=$1 FOR UPDATE',user['id'])
        current = await billing_access.access(conn,user['id'])
        if current['status'] not in ('trial','trial_available','legacy') or (state and not state['billing_managed'] and state['status'] not in ('trial','pending','unpaid')):
            raise HTTPException(409,'Trial selection cannot replace paid or expired access.')
        await conn.execute("UPDATE payment_state SET plan=$2,billing=$3,updated_at=now() WHERE user_id=$1",user['id'],payload.plan,payload.billing)
        await conn.execute('UPDATE users SET onboarding_step=greatest(onboarding_step,2) WHERE id=$1',user['id'])
    return {'ok':True,'message':'Plan selected. Your seven-day trial starts once when you activate care; no card or automatic charge.'}


@router.post('/webhook/razorpay')
async def webhook(request:Request):
    secret = os.environ.get('RAZORPAY_WEBHOOK_SECRET')
    if not secret:
        raise HTTPException(503,'Payment webhook is not configured.')
    raw = await request.body()
    expected = hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,request.headers.get('X-Razorpay-Signature','')):
        raise HTTPException(400,'Invalid webhook signature.')
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(400,'Invalid event body.')
    entity = event.get('payload',{}).get('payment',{}).get('entity',{})
    if not entity.get('order_id'):
        return {'ok':True,'ignored':True}
    order = await get_pool().fetchrow('SELECT * FROM billing_orders WHERE gateway_order_id=$1',entity['order_id'])
    if order:
        await checkout.reconcile(order)
    return {'ok':True}