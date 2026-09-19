"""Server-authoritative Orders checkout. A signed callback alone is not a receipt.

Coupon reservations do not expire while their Razorpay order remains payable:
releasing them on modal dismiss could allow two discounted captured payments.
The same account resumes its existing discounted order instead.

Prorated upgrade credit: switching to a higher-ranked plan while paid time
remains on the current one credits the unused value toward the new plan's
price (see billing_access.prorated_credit). The credited grant is revoked
only once the new order is confirmed paid, in fulfill(), so there's never a
double-access window and a failed/abandoned payment never loses the old grant.
"""
import logging
import os
import uuid
from decimal import Decimal, ROUND_HALF_UP
import requests
from fastapi import HTTPException
from database import get_pool
from pricing import PLAN_BY_ID
from services import billing_access, coupons, razorpay_gateway as gateway

logger = logging.getLogger(__name__)


def currencies():
    return [value.strip() for value in os.environ.get('RAZORPAY_CURRENCIES','').split(',') if value.strip()]


async def quote(conn,user,plan,billing,currency,code='',lock=False):
    if plan not in PLAN_BY_ID or billing not in ('month','year'):
        raise HTTPException(400,'Choose a valid plan and billing period.')
    if currency not in currencies() or currency not in PLAN_BY_ID[plan]['price']:
        raise HTTPException(400,'This checkout currency is not enabled.')
    subtotal = int((Decimal(str(PLAN_BY_ID[plan]['price'][currency][billing]))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    if subtotal<100:
        raise HTTPException(400,'The minimum payment amount is 100 currency subunits.')
    coupon = await coupons.validate(conn,code,user,plan,billing,lock)
    discount = int((Decimal(subtotal)*Decimal(coupon['percent'])/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if coupon else 0
    lifetime = bool(coupon and coupon['kind']=='lifetime')
    credit, credited_grant_id = (0, None) if lifetime else await billing_access.prorated_credit(conn, user['id'], currency)
    amount = subtotal - discount - credit
    if not lifetime and amount < 100:
        amount = 100  # never let proration zero out or go below the gateway minimum
    return {
        'plan':plan,'plan_name':PLAN_BY_ID[plan]['name'],'billing':billing,'currency':currency,
        'subtotal':subtotal,'discount':discount,'credit':credit,'amount':amount,'lifetime':lifetime,
        'coupon_id':coupon['id'] if coupon else None,'coupon_hint':coupon['code_hint'] if coupon else None,
        'credited_grant_id':credited_grant_id,'auto_renews':False,
        'terms':'Lifetime sponsored access; no payment or renewals.' if lifetime else 'One-time prepaid payment. Renew manually; no automatic charges.',
    }


def public_order(order):
    return {key:order.get(key) for key in ('id','gateway_order_id','gateway_payment_id','plan','billing','currency','subtotal','discount','credit','amount','status','is_test','detail','created_at')}


async def create(user,payload):
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','billing:'+str(user['id']))
        current = dict(await conn.fetchrow('SELECT * FROM users WHERE id=$1 FOR UPDATE',user['id']))
        existing = await conn.fetchrow('SELECT * FROM billing_orders WHERE user_id=$1 AND idempotency_key=$2',user['id'],payload.idempotency_key)
        if existing:
            prior_coupon = await conn.fetchval('SELECT code_hash FROM billing_coupons WHERE id=$1',existing['coupon_id']) if existing['coupon_id'] else None
            requested_coupon = coupons.code_hash(payload.coupon_code) if payload.coupon_code else None
            if existing['plan']!=payload.plan or existing['billing']!=payload.billing or existing['currency']!=payload.currency or prior_coupon!=requested_coupon:
                raise HTTPException(409,'This checkout request already belongs to different plan details.')
            return public_order(dict(existing))
        if (await billing_access.access(conn,user['id']))['lifetime']:
            raise HTTPException(409,'You already have lifetime access. No payment is needed.')
        price = await quote(conn,current,payload.plan,payload.billing,payload.currency,payload.coupon_code,True)
        if price['coupon_id']:
            coupon = await conn.fetchrow('SELECT * FROM billing_coupons WHERE id=$1',price['coupon_id'])
            if coupon['reserved_order_id']:
                reserved = await conn.fetchrow('SELECT * FROM billing_orders WHERE id=$1',coupon['reserved_order_id'])
                if reserved and reserved['user_id']==user['id'] and reserved['plan']==payload.plan and reserved['billing']==payload.billing and reserved['currency']==payload.currency:
                    return public_order(dict(reserved))
                raise HTTPException(409,'Resume your existing discounted checkout before changing its plan or currency.')
        if price['amount']:
            gateway.client()  # Fail before reserving anything when configuration is missing.
        order_id = uuid.uuid4()
        order = await conn.fetchrow(
            'INSERT INTO billing_orders(id,user_id,idempotency_key,plan,billing,currency,subtotal,discount,credit,amount,coupon_id,credited_grant_id,is_test) '
            'VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *',
            order_id,user['id'],payload.idempotency_key,price['plan'],price['billing'],price['currency'],
            price['subtotal'],price['discount'],price['credit'],price['amount'],price['coupon_id'],
            price['credited_grant_id'],gateway.test_mode(),
        )
        if price['coupon_id']:
            await conn.execute('UPDATE billing_coupons SET reserved_by=$2,reserved_order_id=$3 WHERE id=$1',price['coupon_id'],user['id'],order_id)
        if price['lifetime']:
            await billing_access.grant_order(conn,order,lifetime=True)
            await conn.execute("UPDATE billing_orders SET status='sponsored',verified_at=now() WHERE id=$1",order_id)
            await conn.execute('UPDATE billing_coupons SET redeemed_by=$2,redeemed_at=now() WHERE id=$1',price['coupon_id'],user['id'])
            return public_order({**dict(order),'status':'sponsored'})
    try:
        remote = await gateway.create_order(price['amount'],price['currency'],'ay_'+order_id.hex,user['id'])
        if remote.get('amount')!=price['amount'] or remote.get('currency')!=price['currency'] or not remote.get('id'):
            raise RuntimeError('Unexpected gateway order response')
    except (requests.Timeout, requests.ConnectionError, RuntimeError):
        await get_pool().execute("UPDATE billing_orders SET status='creation_unknown',detail='Order creation is uncertain; do not submit another payment.',updated_at=now() WHERE id=$1",order_id)
        return public_order(dict(await get_pool().fetchrow('SELECT * FROM billing_orders WHERE id=$1',order_id)))
    except Exception as exc:
        logger.warning('Razorpay create rejected for local order %s (%s)',order_id,type(exc).__name__)
        async with get_pool().acquire() as conn,conn.transaction():
            await conn.execute("UPDATE billing_orders SET status='failed',detail='Gateway rejected order creation.',updated_at=now() WHERE id=$1",order_id)
            await conn.execute('UPDATE billing_coupons SET reserved_by=NULL,reserved_order_id=NULL WHERE reserved_order_id=$1 AND redeemed_at IS NULL',order_id)
        raise HTTPException(500,'Could not create the payment order. Please try again; your plan has not changed.')
    await get_pool().execute("UPDATE billing_orders SET gateway_order_id=$2,status='created',updated_at=now() WHERE id=$1",order_id,remote['id'])
    return public_order(dict(await get_pool().fetchrow('SELECT * FROM billing_orders WHERE id=$1',order_id)))


async def fulfill(local_id,payment,remote_order):
    async with get_pool().acquire() as conn,conn.transaction():
        owner = await conn.fetchval('SELECT user_id FROM billing_orders WHERE id=$1',local_id)
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','billing:'+str(owner))
        order = await conn.fetchrow('SELECT * FROM billing_orders WHERE id=$1 FOR UPDATE',local_id)
        if not order:
            raise HTTPException(404,'Payment order not found.')
        if payment.get('order_id')!=order['gateway_order_id'] or remote_order.get('id')!=order['gateway_order_id'] or payment.get('amount')!=order['amount'] or payment.get('currency')!=order['currency'] or remote_order.get('amount')!=order['amount'] or remote_order.get('currency')!=order['currency']:
            raise HTTPException(400,'Payment details do not match the stored order.')
        if payment.get('amount_refunded',0)>=order['amount'] and order['amount']>0:
            await conn.execute('UPDATE access_grants SET revoked_at=now() WHERE order_id=$1 AND revoked_at IS NULL',local_id)
            await conn.execute("UPDATE billing_orders SET status='refunded',updated_at=now() WHERE id=$1",local_id)
            return {'status':'refunded'}
        if order['status']=='paid':
            return {'status':'paid','access':await billing_access.access(conn,owner)}
        if payment.get('status')!='captured' or not payment.get('captured') or remote_order.get('status')!='paid' or remote_order.get('amount_paid')!=order['amount']:
            return {'status':'payment_pending','message':'Payment is not captured yet. Your access will update after confirmation.'}
        if order['coupon_id']:
            coupon = await conn.fetchrow('SELECT * FROM billing_coupons WHERE id=$1 FOR UPDATE',order['coupon_id'])
            if coupon['reserved_order_id']!=local_id or (coupon['redeemed_by'] and coupon['redeemed_by']!=owner):
                raise HTTPException(409,'Coupon reconciliation needs review. Do not pay again.')
            await conn.execute('UPDATE billing_coupons SET redeemed_by=$2,redeemed_at=coalesce(redeemed_at,now()) WHERE id=$1',coupon['id'],owner)
        await billing_access.grant_order(conn,order,revoke_grant_id=order['credited_grant_id'])
        await conn.execute("UPDATE billing_orders SET status='paid',gateway_payment_id=$2,verified_at=now(),updated_at=now() WHERE id=$1",local_id,payment['id'])
        return {'status':'paid','access':await billing_access.access(conn,owner)}


async def reconcile(order):
    if not order['gateway_order_id'] or order['status']=='sponsored':
        return {'status':order['status']}
    try:
        remote = await gateway.fetch_order(order['gateway_order_id'])
        payments = await gateway.order_payments(order['gateway_order_id'])
        for payment in payments.get('items',[]):
            if payment.get('status') in ('captured','refunded'):
                return await fulfill(order['id'],payment,remote)
        return {'status':order['status'],'message':'No captured payment found. Do not assume access is paid.'}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503,'Payment status could not be checked. Please try again without making another payment.')