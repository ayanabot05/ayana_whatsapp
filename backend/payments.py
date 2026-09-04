"""
payments.py — Stripe checkout for AYANA, gated behind PAYMENTS_ENABLED.

Uses the official `stripe` SDK directly (Checkout Sessions, async client).
All amounts are defined server-side from pricing.py — the frontend only
ever sends {plan, billing, origin_url}.

While PAYMENTS_ENABLED != "true", server.py keeps its existing trial/test
"skip" behaviour and never calls into this module — so flipping the flag
(plus setting real STRIPE_API_KEY / STRIPE_WEBHOOK_SECRET) is the only
switch needed to go live.

Requires: pip install stripe>=7  (create_async / retrieve_async need v7+)
Env vars:
  STRIPE_API_KEY         — sk_test_... / sk_live_...
  STRIPE_WEBHOOK_SECRET   — whsec_... (from the Stripe Dashboard webhook config)
"""

import logging
import os
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from database import get_pool
from pricing import PLAN_BY_ID, resolve_plan_id

logger = logging.getLogger("ayana.payments")

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

if not STRIPE_API_KEY:
    logger.warning("STRIPE_API_KEY not set — payment endpoints will fail once PAYMENTS_ENABLED=true")

stripe.api_key = STRIPE_API_KEY


def payments_enabled() -> bool:
    return os.environ.get("PAYMENTS_ENABLED", "false").strip().lower() == "true"


def _plan_amount_cents(plan_id: str, billing: str) -> int:
    """Server-side authoritative price in USD cents (int). Never trust the client."""
    plan = PLAN_BY_ID.get(resolve_plan_id(plan_id)) or PLAN_BY_ID["nitya"]
    usd = plan["price"]["USD"]
    amount = float(usd.get("year") if billing == "year" else usd.get("month"))
    return round(amount * 100)


payments_router = APIRouter(prefix="/api")


class PaymentCheckoutInput(BaseModel):
    plan: str = Field("nitya")
    billing: str = Field("month", pattern="^(month|year)$")
    origin_url: str


async def create_stripe_checkout(user_id: str, payload: PaymentCheckoutInput, request: Request) -> dict:
    """Create a Stripe Checkout session for a plan. Called by server.py's
    /payment/checkout only when PAYMENTS_ENABLED is true."""
    plan_id = resolve_plan_id(payload.plan)
    plan = PLAN_BY_ID.get(plan_id) or PLAN_BY_ID["nitya"]
    amount_cents = _plan_amount_cents(plan_id, payload.billing)
    origin = payload.origin_url.rstrip("/")

    try:
        session = await stripe.checkout.Session.create_async(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": f"AYANA — {plan.get('name', plan_id)} ({payload.billing}ly)",
                    },
                },
                "quantity": 1,
            }],
            success_url=f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/payment/cancel",
            metadata={"user_id": user_id, "plan": plan_id, "billing": payload.billing},
        )
    except stripe.error.StripeError as e:
        logger.error("[stripe] checkout session creation failed: %s", e)
        raise HTTPException(status_code=502, detail="Could not start checkout. Please try again.")

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into payment_transactions
                (session_id, user_id, plan, billing, amount, currency, status, payment_status,
                 created_at, updated_at)
            values ($1, $2::uuid, $3, $4, $5, 'usd', 'initiated', 'pending', now(), now())
            """,
            session.id, user_id, plan_id, payload.billing, amount_cents / 100,
        )
    return {"checkout_url": session.url, "session_id": session.id}


@payments_router.get("/payments/status/{session_id}")
async def payment_status(session_id: str):
    """Unauthenticated status poll — returns only non-sensitive fields."""
    async with get_pool().acquire() as conn:
        record = await conn.fetchrow(
            "select * from payment_transactions where session_id = $1", session_id
        )
        if not record:
            raise HTTPException(status_code=404, detail="Transaction not found")

        if record["payment_status"] != "paid" and payments_enabled():
            try:
                session = await stripe.checkout.Session.retrieve_async(session_id)
                if session.payment_status == "paid" or session.status == "complete":
                    await _mark_paid(conn, session_id, record)
                    record = await conn.fetchrow(
                        "select * from payment_transactions where session_id = $1", session_id
                    )
            except stripe.error.StripeError as e:
                logger.warning("[stripe] status poll failed for %s: %s", session_id, e)

    return {
        "session_id": record["session_id"],
        "status": record["status"],
        "payment_status": record["payment_status"],
    }


async def _mark_paid(conn, session_id: str, record) -> None:
    """Idempotently flip a transaction to paid AND upgrade the user's plan.
    `conn` is passed in (rather than acquired here) so the webhook handler
    and the status-poll path can both run this inside their own connection/
    transaction — mirrors the old code's single-call convenience without
    opening a second pool connection mid-request."""
    result = await conn.execute(
        """
        update payment_transactions
        set status = 'completed', payment_status = 'paid', updated_at = now()
        where session_id = $1 and payment_status != 'paid'
        """,
        session_id,
    )
    # asyncpg's execute() returns a string like "UPDATE 1" — check the count
    modified = result.split()[-1] != "0"
    if modified and record.get("user_id"):
        await conn.execute(
            """
            insert into payment_state (user_id, status, plan, billing, updated_at)
            values ($1::uuid, 'active', $2, $3, now())
            on conflict (user_id) do update
                set status = 'active', plan = excluded.plan,
                    billing = excluded.billing, updated_at = now()
            """,
            record["user_id"], record.get("plan", "nitya"), record.get("billing", "month"),
        )


@payments_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("[stripe] STRIPE_WEBHOOK_SECRET not set — rejecting webhook")
        raise HTTPException(status_code=500, detail="Webhook not configured")

    try:
        event = stripe.Webhook.construct_event(body, sig, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.warning("[stripe] webhook verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session.get("id")
        if session.get("payment_status") == "paid" and session_id:
            async with get_pool().acquire() as conn:
                record = await conn.fetchrow(
                    "select * from payment_transactions where session_id = $1", session_id
                )
                if record:
                    await _mark_paid(conn, session_id, record)

    return {"status": "ok"}