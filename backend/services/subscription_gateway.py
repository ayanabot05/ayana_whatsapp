"""Razorpay Subscription API gateway — server-only, key never leaves backend.

Razorpay subscription lifecycle:
  created → authenticated (mandate signed) → active (first charge captured)
  → halted (payment failed after retries) / cancelled / completed / expired

We create one Razorpay Plan per (plan, billing, currency) combination and
cache the gateway plan ID in billing_plans to avoid duplicates.
"""
import asyncio
import hashlib
import hmac
import os
from decimal import Decimal, ROUND_HALF_UP

import razorpay
from fastapi import HTTPException


def enabled() -> bool:
    return os.environ.get('RAZORPAY_ENABLED', '').lower() == 'true'


def test_mode() -> bool:
    return os.environ.get('RAZORPAY_KEY_ID', '').startswith('rzp_test_')


def client() -> razorpay.Client:
    key = os.environ.get('RAZORPAY_KEY_ID')
    secret = os.environ.get('RAZORPAY_KEY_SECRET')
    if not enabled() or not key or not secret:
        raise HTTPException(503, 'Subscription checkout is not configured yet.')
    if test_mode() and os.environ.get('APP_ENV') != 'test':
        raise HTTPException(503, 'Test subscription keys cannot be used in production.')
    return razorpay.Client(auth=(key, secret), timeout=20)


# ── Plan management ───────────────────────────────────────────────────────────

def _interval(billing: str) -> tuple[str, int]:
    """Return (period, interval) for Razorpay plan creation."""
    # 'month' → period=monthly, interval=1
    # 'year'  → period=yearly,  interval=1  (charges once a year, auto-renews)
    if billing == 'year':
        return 'yearly', 1
    return 'monthly', 1


async def get_or_create_plan(conn, plan: str, billing: str, currency: str, amount: int) -> dict:
    """Return billing_plans row, creating the Razorpay plan on first call."""
    row = await conn.fetchrow(
        'SELECT * FROM billing_plans WHERE plan=$1 AND billing=$2 AND currency=$3',
        plan, billing, currency,
    )
    if row:
        return dict(row)

    # Create the Razorpay plan via API
    period, interval = _interval(billing)
    label = f'AYANA {plan.capitalize()} — {billing}ly ({currency})'
    try:
        remote = await asyncio.to_thread(
            client().plan.create,
            {
                'period': period,
                'interval': interval,
                'item': {
                    'name': label,
                    'amount': amount,
                    'currency': currency,
                    'description': f'AYANA {plan} care plan — billed {billing}ly',
                },
            },
        )
    except Exception as exc:
        raise HTTPException(500, f'Could not create subscription plan: {exc}') from exc

    local = await conn.fetchrow(
        '''INSERT INTO billing_plans (plan, billing, currency, amount, gateway_plan_id)
           VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT (plan, billing, currency) DO UPDATE
               SET gateway_plan_id = EXCLUDED.gateway_plan_id
           RETURNING *''',
        plan, billing, currency, amount, remote['id'],
    )
    return dict(local)


# ── Subscription creation ─────────────────────────────────────────────────────

async def create_subscription(gateway_plan_id: str, user_id, notes: dict | None = None) -> dict:
    """Create a Razorpay Subscription. Returns the full Razorpay subscription object."""
    try:
        return await asyncio.to_thread(
            client().subscription.create,
            {
                'plan_id': gateway_plan_id,
                # total_count=0 → infinite recurring until cancelled
                # Razorpay uses 0 for unlimited; for yearly this means renews every year.
                'total_count': 0,
                'quantity': 1,
                'notify_info': {
                    'notify_phone': 0,
                    'notify_email': 1,
                },
                'notes': notes or {},
            },
        )
    except Exception as exc:
        raise HTTPException(500, f'Could not create subscription: {exc}') from exc


# ── Subscription operations ───────────────────────────────────────────────────

async def fetch_subscription(subscription_id: str) -> dict:
    try:
        return await asyncio.to_thread(client().subscription.fetch, subscription_id)
    except Exception as exc:
        raise HTTPException(503, f'Could not fetch subscription: {exc}') from exc


async def cancel_subscription(subscription_id: str, cancel_at_cycle_end: bool = True) -> dict:
    """Cancel immediately (cancel_at_cycle_end=False) or at end of current period."""
    try:
        return await asyncio.to_thread(
            client().subscription.cancel,
            subscription_id,
            {'cancel_at_cycle_end': 1 if cancel_at_cycle_end else 0},
        )
    except Exception as exc:
        raise HTTPException(503, f'Could not cancel subscription: {exc}') from exc


# ── Signature verification ────────────────────────────────────────────────────

def valid_subscription_signature(subscription_id: str, payment_id: str, signature: str) -> bool:
    """Verify the HMAC returned by Razorpay after the customer authorises the mandate."""
    secret = os.environ.get('RAZORPAY_KEY_SECRET', '')
    if not secret:
        raise HTTPException(503, 'Payment verification is not configured.')
    payload = f'{payment_id}|{subscription_id}'
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)
