"""Public checkout contracts, authenticated order ownership and verified webhooks."""
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from auth import get_current_user, validate_csrf_token, serialize
from database import get_pool
from rate_limit import api_rate_limit_dependency
from routes.account import require_email
from services import billing_access, checkout, razorpay_gateway as gateway
from services import subscription_gateway as sub_gateway

router = APIRouter(prefix='/api', tags=['Checkout'])


class QuoteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan: str
    billing: Literal['month', 'year']
    currency: str
    coupon_code: str = Field('', max_length=80)


class OrderInput(QuoteInput):
    idempotency_key: uuid.UUID


class SubscribeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan: str
    billing: Literal['month', 'year']
    currency: str
    coupon_code: str = Field('', max_length=80)


class VerifyInput(BaseModel):
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    razorpay_signature: str | None = None


class VerifySubscriptionInput(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


def owner_only(user):
    if user.get('role') != 'admin' and user.get('household_owner_id'):
        raise HTTPException(403, 'Only the account owner can manage billing.')
    require_email(user)


# ── Config ────────────────────────────────────────────────────────────────────

@router.get('/payment/config')
async def payment_config():
    return {
        'provider': 'razorpay',
        'enabled': gateway.enabled(),
        'key_id': os.environ.get('RAZORPAY_KEY_ID'),
        'test_mode': gateway.test_mode(),
        'currencies': checkout.currencies(),
        'auto_renews': False,
        'checkout_script': 'https://checkout.razorpay.com/v1/checkout.js',
    }


# ── One-time checkout ──────────────────────────────────────────────────────────

@router.post('/payment/quote', dependencies=[Depends(validate_csrf_token), Depends(api_rate_limit_dependency)])
async def quote(payload: QuoteInput, user=Depends(get_current_user)):
    owner_only(user)
    async with get_pool().acquire() as conn:
        return serialize(await checkout.quote(conn, user, payload.plan, payload.billing, payload.currency, payload.coupon_code))


@router.post('/create-order', dependencies=[Depends(validate_csrf_token), Depends(api_rate_limit_dependency)])
async def create_order(payload: OrderInput, user=Depends(get_current_user)):
    owner_only(user)
    order = await checkout.create(user, payload)
    return {**serialize(order), 'local_order_id': str(order['id']), 'order_id': order['gateway_order_id'], 'key_id': os.environ.get('RAZORPAY_KEY_ID')}


@router.post('/verify-payment', dependencies=[Depends(validate_csrf_token), Depends(api_rate_limit_dependency)])
async def verify_payment(payload: VerifyInput, user=Depends(get_current_user)):
    owner_only(user)
    if not all((payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature)):
        raise HTTPException(400, 'Payment id, order id and signature are required.')
    order = await get_pool().fetchrow('SELECT * FROM billing_orders WHERE gateway_order_id=$1 AND user_id=$2', payload.razorpay_order_id, user['id'])
    if not order:
        raise HTTPException(404, 'Payment order not found for this account.')
    if not gateway.valid_signature(order['gateway_order_id'], payload.razorpay_payment_id, payload.razorpay_signature):
        raise HTTPException(400, 'Invalid payment signature. Your plan has not been marked paid.')
    try:
        payment = await gateway.fetch_payment(payload.razorpay_payment_id)
        remote = await gateway.fetch_order(order['gateway_order_id'])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Signature verified, but payment status is unavailable. Do not pay again; check the order status shortly.')
    return serialize(await checkout.fulfill(order['id'], payment, remote))


@router.get('/payment/orders')
async def orders(user=Depends(get_current_user)):
    owner_only(user)
    rows = await get_pool().fetch('SELECT * FROM billing_orders WHERE user_id=$1 ORDER BY created_at DESC LIMIT 30', user['id'])
    return [serialize(checkout.public_order(dict(row))) for row in rows]


@router.post('/payment/orders/{local_id}/recheck', dependencies=[Depends(validate_csrf_token), Depends(api_rate_limit_dependency)])
async def recheck(local_id: uuid.UUID, user=Depends(get_current_user)):
    owner_only(user)
    order = await get_pool().fetchrow('SELECT * FROM billing_orders WHERE id=$1 AND user_id=$2', local_id, user['id'])
    if not order:
        raise HTTPException(404, 'Order not found.')
    return serialize(await checkout.reconcile(order))


# ── Subscription checkout ──────────────────────────────────────────────────────

@router.post('/subscribe', dependencies=[Depends(validate_csrf_token), Depends(api_rate_limit_dependency)])
async def create_subscription(payload: SubscribeInput, user=Depends(get_current_user)):
    """Create a Razorpay Subscription. Returns subscription_id + key_id for the frontend modal."""
    owner_only(user)
    from pricing import PLAN_BY_ID
    if payload.plan not in PLAN_BY_ID or payload.billing not in ('month', 'year'):
        raise HTTPException(400, 'Choose a valid plan and billing period.')
    if payload.currency not in checkout.currencies():
        raise HTTPException(400, 'This currency is not enabled for subscriptions.')
    if payload.currency not in PLAN_BY_ID[payload.plan]['price']:
        raise HTTPException(400, 'No price defined for this plan and currency.')

    price_float = PLAN_BY_ID[payload.plan]['price'][payload.currency][payload.billing]
    amount = int((Decimal(str(price_float)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if amount < 100:
        raise HTTPException(400, 'The subscription amount is below the minimum supported.')

    # Prevent creating a new subscription if one is already active for this plan+billing
    async with get_pool().acquire() as conn:
        existing = await conn.fetchrow(
            """SELECT id FROM billing_subscriptions
               WHERE user_id=$1 AND plan=$2 AND billing=$3 AND currency=$4
                 AND status IN ('created','authenticated','active')""",
            user['id'], payload.plan, payload.billing, payload.currency,
        )
        if existing:
            raise HTTPException(409, 'You already have an active or pending subscription for this plan. Cancel it first if you want to change.')

        # Get or create the Razorpay Plan
        billing_plan = await sub_gateway.get_or_create_plan(conn, payload.plan, payload.billing, payload.currency, amount)

    # Create the Razorpay Subscription (outside transaction — remote call)
    remote_sub = await sub_gateway.create_subscription(
        billing_plan['gateway_plan_id'],
        user['id'],
        notes={'ayana_user_id': str(user['id']), 'plan': payload.plan, 'billing': payload.billing},
    )

    # Store in local DB
    async with get_pool().acquire() as conn:
        local_sub = await conn.fetchrow(
            """INSERT INTO billing_subscriptions
                   (user_id, billing_plan_id, gateway_subscription_id, plan, billing,
                    currency, amount, status, is_test)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING id""",
            user['id'], billing_plan['id'], remote_sub['id'],
            payload.plan, payload.billing, payload.currency, amount,
            remote_sub.get('status', 'created'), sub_gateway.test_mode(),
        )

    return {
        'local_subscription_id': str(local_sub['id']),
        'subscription_id': remote_sub['id'],       # Razorpay subscription_id for modal
        'key_id': os.environ.get('RAZORPAY_KEY_ID'),
        'plan': payload.plan,
        'billing': payload.billing,
        'currency': payload.currency,
        'amount': amount,
        'status': remote_sub.get('status', 'created'),
    }


@router.post('/verify-subscription', dependencies=[Depends(validate_csrf_token), Depends(api_rate_limit_dependency)])
async def verify_subscription(payload: VerifySubscriptionInput, user=Depends(get_current_user)):
    """Called after the user authorises the subscription mandate in the Razorpay modal."""
    owner_only(user)
    if not sub_gateway.valid_subscription_signature(
        payload.razorpay_subscription_id, payload.razorpay_payment_id, payload.razorpay_signature
    ):
        raise HTTPException(400, 'Invalid subscription signature. Your subscription has not been activated.')

    sub = await get_pool().fetchrow(
        'SELECT * FROM billing_subscriptions WHERE gateway_subscription_id=$1 AND user_id=$2',
        payload.razorpay_subscription_id, user['id'],
    )
    if not sub:
        raise HTTPException(404, 'Subscription not found for this account.')

    # Fetch live status from Razorpay to confirm
    try:
        remote = await sub_gateway.fetch_subscription(payload.razorpay_subscription_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Signature verified, but subscription status could not be confirmed. Check status shortly; do not subscribe again.')

    new_status = remote.get('status', sub['status'])
    now = datetime.now(timezone.utc)

    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE billing_subscriptions SET status=$2, updated_at=now() WHERE id=$1",
            sub['id'], new_status,
        )
        # Update payment_state so dashboard plan reflects subscription
        await conn.execute(
            """INSERT INTO payment_state (user_id, status, plan, billing, billing_managed)
               VALUES ($1, 'active', $2, $3, true)
               ON CONFLICT (user_id) DO UPDATE
                   SET status='active', plan=EXCLUDED.plan, billing=EXCLUDED.billing,
                       billing_managed=true, updated_at=now()""",
            user['id'], sub['plan'], sub['billing'],
        )
        await conn.execute('UPDATE users SET onboarding_step=greatest(onboarding_step,2) WHERE id=$1', user['id'])

    return {
        'status': new_status,
        'plan': sub['plan'],
        'billing': sub['billing'],
        'message': 'Subscription activated. Care access auto-renews each period.' if new_status in ('authenticated', 'active') else f'Subscription status: {new_status}.',
    }


@router.get('/subscriptions')
async def list_subscriptions(user=Depends(get_current_user)):
    """List the current user's subscriptions (most recent first)."""
    owner_only(user)
    rows = await get_pool().fetch(
        """SELECT * FROM billing_subscriptions WHERE user_id=$1
           ORDER BY created_at DESC LIMIT 10""",
        user['id'],
    )
    return [serialize(dict(r)) for r in rows]


@router.post('/subscriptions/{local_id}/cancel', dependencies=[Depends(validate_csrf_token)])
async def cancel_subscription(local_id: uuid.UUID, user=Depends(get_current_user)):
    """Cancel at end of current billing period (access continues until then)."""
    owner_only(user)
    sub = await get_pool().fetchrow(
        'SELECT * FROM billing_subscriptions WHERE id=$1 AND user_id=$2',
        local_id, user['id'],
    )
    if not sub:
        raise HTTPException(404, 'Subscription not found.')
    if sub['status'] not in ('authenticated', 'active'):
        raise HTTPException(409, f'Subscription is already {sub["status"]}; nothing to cancel.')
    if sub['cancel_at_period_end']:
        raise HTTPException(409, 'Cancellation is already scheduled at the end of the billing period.')

    await sub_gateway.cancel_subscription(sub['gateway_subscription_id'], cancel_at_cycle_end=True)
    now = datetime.now(timezone.utc)
    await get_pool().execute(
        'UPDATE billing_subscriptions SET cancel_at_period_end=true, cancelled_at=$2, updated_at=now() WHERE id=$1',
        sub['id'], now,
    )
    return {
        'ok': True,
        'message': 'Your subscription will not renew. Access continues until the end of the current billing period.',
        'expires_at': sub['current_period_end'],
    }


# ── Access & payment history ──────────────────────────────────────────────────

@router.get('/payment/access')
async def payment_access(user=Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        return serialize(await billing_access.access(conn, user.get('household_owner_id') or user['id']))


@router.post('/payment/trial', dependencies=[Depends(validate_csrf_token)])
async def choose_trial(payload: QuoteInput, user=Depends(get_current_user)):
    owner_only(user)
    from pricing import PLAN_BY_ID
    if payload.plan not in PLAN_BY_ID or payload.coupon_code:
        raise HTTPException(400, 'Choose a valid trial plan. Redeem coupons through checkout instead.')
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'billing:' + str(user['id']))
        state = await conn.fetchrow('SELECT * FROM payment_state WHERE user_id=$1 FOR UPDATE', user['id'])
        current = await billing_access.access(conn, user['id'])
        if current['status'] not in ('trial', 'trial_available', 'legacy') or (state and not state['billing_managed'] and state['status'] not in ('trial', 'pending', 'unpaid')):
            raise HTTPException(409, 'Trial selection cannot replace paid or expired access.')
        await conn.execute("UPDATE payment_state SET plan=$2,billing=$3,updated_at=now() WHERE user_id=$1", user['id'], payload.plan, payload.billing)
        await conn.execute('UPDATE users SET onboarding_step=greatest(onboarding_step,2) WHERE id=$1', user['id'])
    return {'ok': True, 'message': 'Plan selected. Your seven-day trial starts once when you activate care; no card or automatic charge.'}


# ── Webhooks ──────────────────────────────────────────────────────────────────

@router.post('/webhook/razorpay')
async def webhook(request: Request):
    secret = os.environ.get('RAZORPAY_WEBHOOK_SECRET')
    if not secret:
        raise HTTPException(503, 'Payment webhook is not configured.')
    raw = await request.body()
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get('X-Razorpay-Signature', '')):
        raise HTTPException(400, 'Invalid webhook signature.')
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(400, 'Invalid event body.')

    event_type = event.get('event', '')
    payload_data = event.get('payload', {})

    # ── One-time payment events ────────────────────────────────────────────────
    if event_type in ('payment.captured', 'order.paid'):
        entity = payload_data.get('payment', {}).get('entity', {})
        if entity.get('order_id'):
            order = await get_pool().fetchrow('SELECT * FROM billing_orders WHERE gateway_order_id=$1', entity['order_id'])
            if order:
                await checkout.reconcile(order)
        return {'ok': True}

    # ── Subscription events ────────────────────────────────────────────────────
    sub_entity = payload_data.get('subscription', {}).get('entity', {})
    gateway_sub_id = sub_entity.get('id') or payload_data.get('payment', {}).get('entity', {}).get('subscription_id')
    if not gateway_sub_id:
        return {'ok': True, 'ignored': True}

    from services.subscription_events import ingest
    return await ingest(event, request.headers.get('x-razorpay-event-id'))