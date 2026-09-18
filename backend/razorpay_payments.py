"""
razorpay_payments.py — Razorpay Standard Web Checkout for AYANA.

Replaces the Stripe integration.  Uses the official `razorpay` Python SDK.
All amounts are computed server-side from pricing.py — the frontend only ever
sends {plan, billing, currency}.

Env vars:
  RAZORPAY_KEY_ID          — rzp_test_... / rzp_live_...
  RAZORPAY_KEY_SECRET      — secret from the Razorpay Dashboard
  RAZORPAY_WEBHOOK_SECRET  — (optional) webhook signature secret
"""

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import razorpay
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from database import get_pool
from pricing import PLAN_BY_ID, resolve_plan_id

logger = logging.getLogger("ayana.razorpay")

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    logger.warning("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set — payment endpoints will fail once PAYMENTS_ENABLED=true")

_client = None


def _get_client():
    """Lazily create the Razorpay client (avoids import-time failures when creds are missing)."""
    global _client
    if _client is None:
        _client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _client


# ── Helpers ──────────────────────────────────────────────────────────

# Map user-selected currency to the smallest unit multiplier.
# Razorpay amounts are always in the smallest unit (paise for INR, cents for USD, etc.).
_CURRENCY_SUBUNIT = {
    "INR": 100,
    "USD": 100,
    "GBP": 100,
    "EUR": 100,
    "AED": 100,
    "SGD": 100,
    "AUD": 100,
    "CAD": 100,
}


def _resolve_plan_price(plan_id: str, billing: str, currency: str) -> tuple[Decimal, str]:
    """
    Single source of truth for "what does this plan cost, in which currency".
    Returns (amount, resolved_currency) — resolved_currency is what the price
    was ACTUALLY looked up in, so callers never tag one currency's amount
    with another currency's code (the bug this replaces: order.amount was
    computed in USD but order.currency stayed AED, undercharging ~13x).

    Uses Decimal throughout — floats can misrepresent values like 19.99,
    which risks off-by-a-paisa amounts once multiplied into subunits.
    """
    plan = PLAN_BY_ID.get(resolve_plan_id(plan_id)) or PLAN_BY_ID["nitya"]
    currency = currency.upper()
    prices = plan["price"].get(currency)
    if not prices:
        # Fallback to USD if the requested currency isn't configured for
        # this plan. Return the RESOLVED currency alongside the amount so
        # the caller prices and tags the order consistently.
        prices = plan["price"]["USD"]
        currency = "USD"
    raw = prices.get("year") if billing == "year" else prices.get("month")
    amount = Decimal(str(raw))
    return amount, currency


def _plan_amount_subunit(amount: Decimal, currency: str) -> int:
    """Convert a display amount (e.g. Decimal('19.99')) to the smallest
    currency unit (e.g. 1999 cents) for Razorpay."""
    multiplier = _CURRENCY_SUBUNIT.get(currency.upper(), 100)
    subunit = (amount * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(subunit)


# ── Router ───────────────────────────────────────────────────────────

razorpay_router = APIRouter(prefix="/api")


class RazorpayOrderInput(BaseModel):
    plan: str = Field("nitya")
    billing: str = Field("month", pattern="^(month|year)$")
    currency: str = Field("INR", pattern="^(INR|USD|GBP|EUR|AED|SGD|AUD|CAD)$")


async def create_razorpay_order(user_id: str, plan_id: str, billing: str, currency: str) -> dict:
    """Create a Razorpay order for the given plan.  Called by server.py's
    /payment/checkout when PAYMENTS_ENABLED is true."""
    plan_id = resolve_plan_id(plan_id)
    plan = PLAN_BY_ID.get(plan_id) or PLAN_BY_ID["nitya"]

    # Resolve price + currency TOGETHER so the order is always created in
    # the currency the price was actually looked up in — never a currency
    # mismatch between order.amount and order.currency.
    amount_display, resolved_currency = _resolve_plan_price(plan_id, billing, currency)
    amount_subunit = _plan_amount_subunit(amount_display, resolved_currency)
    currency = resolved_currency

    if amount_subunit < 100:
        raise HTTPException(
            status_code=400,
            detail=f"Amount too small for Razorpay (minimum 100 subunits / 1 {currency}).",
        )

    receipt = f"ayana_{user_id[:8]}_{plan_id}_{billing}_{int(datetime.now(timezone.utc).timestamp())}"

    try:
        order = _get_client().order.create({
            "amount": amount_subunit,
            "currency": currency,
            "receipt": receipt,
            "notes": {
                "user_id": user_id,
                "plan": plan_id,
                "billing": billing,
            },
        })
    except Exception as e:
        logger.error("[razorpay] order creation failed: %s", e)
        raise HTTPException(status_code=502, detail="Could not start checkout. Please try again.")

    order_id = order["id"]

    # Persist the initiated transaction
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO payment_transactions
                (session_id, user_id, plan, billing, amount, currency, status, payment_status,
                 created_at, updated_at)
            VALUES ($1, $2::uuid, $3, $4, $5, $6, 'initiated', 'pending', now(), now())
            ON CONFLICT (session_id) DO NOTHING
            """,
            order_id, user_id, plan_id, billing, amount_display, currency.lower(),
        )

    return {
        "order_id": order_id,
        "amount": amount_subunit,
        "currency": currency,
        "key_id": RAZORPAY_KEY_ID,
        "plan_name": plan.get("name", plan_id),
        "billing": billing,
    }


# ── Verify Payment Signature ────────────────────────────────────────

class RazorpayVerifyInput(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@razorpay_router.post("/payments/razorpay/verify")
async def verify_razorpay_payment(payload: RazorpayVerifyInput):
    """Verify the Razorpay payment signature after the frontend checkout modal
    reports success.  HMAC-SHA256(order_id|payment_id, key_secret)."""
    expected_sig = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, payload.razorpay_signature):
        logger.warning("[razorpay] signature mismatch for order %s", payload.razorpay_order_id)
        raise HTTPException(status_code=400, detail="Payment verification failed. Signature mismatch.")

    # Signature valid — mark as paid
    async with get_pool().acquire() as conn:
        record = await conn.fetchrow(
            "SELECT * FROM payment_transactions WHERE session_id = $1",
            payload.razorpay_order_id,
        )
        if not record:
            raise HTTPException(status_code=404, detail="Order not found.")

        if record["payment_status"] == "paid":
            # Already processed (idempotent)
            return {"status": "already_paid", "plan": record["plan"]}

        await _mark_paid(conn, payload.razorpay_order_id, record, payload.razorpay_payment_id)

    return {"status": "paid", "plan": record["plan"], "billing": record["billing"]}


# ── Payment Status Poll ──────────────────────────────────────────────

@razorpay_router.get("/payments/status/{order_id}")
async def payment_status(order_id: str):
    """Unauthenticated status poll — returns only non-sensitive fields.
    Used by the PaymentReturn page as a fallback."""
    async with get_pool().acquire() as conn:
        record = await conn.fetchrow(
            "SELECT * FROM payment_transactions WHERE session_id = $1", order_id
        )
        if not record:
            raise HTTPException(status_code=404, detail="Transaction not found")

    return {
        "session_id": record["session_id"],
        "status": record["status"],
        "payment_status": record["payment_status"],
    }


# ── Mark Paid (shared by verify + webhook) ───────────────────────────

async def _mark_paid(conn, order_id: str, record, payment_id: str = "") -> None:
    """Idempotently flip a transaction to paid AND upgrade the user's plan."""
    result = await conn.execute(
        """
        UPDATE payment_transactions
        SET status = 'completed', payment_status = 'paid', updated_at = now()
        WHERE session_id = $1 AND payment_status != 'paid'
        """,
        order_id,
    )
    modified = result.split()[-1] != "0"

    if modified and record.get("user_id"):
        prev = await conn.fetchrow(
            "SELECT plan FROM payment_state WHERE user_id = $1::uuid", record["user_id"]
        )
        old_plan = (prev["plan"] if prev else None) or "nitya"
        new_plan = record.get("plan", "nitya")
        await conn.execute(
            """
            INSERT INTO payment_state (user_id, status, plan, billing, updated_at)
            VALUES ($1::uuid, 'active', $2, $3, now())
            ON CONFLICT (user_id) DO UPDATE
                SET status = 'active', plan = excluded.plan,
                    billing = excluded.billing, updated_at = now()
            """,
            record["user_id"], new_plan, record.get("billing", "month"),
        )
        logger.info(
            "[razorpay] user %s upgraded %s -> %s (order=%s, payment=%s)",
            record["user_id"], old_plan, new_plan, order_id, payment_id,
        )
        # Best-effort: notify the account owner over WhatsApp
        try:
            from whatsapp import send_plan_change
            user_row = await conn.fetchrow(
                "SELECT phone FROM users WHERE id = $1::uuid", record["user_id"]
            )
            if user_row and user_row["phone"]:
                plan_name = (PLAN_BY_ID.get(new_plan) or {}).get("name", new_plan)
                await send_plan_change(
                    user_row["phone"], "en", plan_name, _plan_direction(old_plan, new_plan)
                )
        except Exception as e:
            logger.warning("[razorpay] plan-change WhatsApp notify failed: %s", e)


_PLAN_RANK = {"nitya": 0, "bandham": 1, "raksha": 2}


def _plan_direction(old_plan: str, new_plan: str) -> str:
    o = _PLAN_RANK.get(old_plan or "nitya", 0)
    n = _PLAN_RANK.get(new_plan or "nitya", 0)
    if n > o:
        return "upgrade"
    if n < o:
        return "downgrade"
    return "same"


# ── Razorpay Webhook ─────────────────────────────────────────────────

@razorpay_router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """Handle Razorpay webhook events (payment.captured, order.paid, etc.)."""
    body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")

    if RAZORPAY_WEBHOOK_SECRET:
        expected = hmac.new(
            RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            logger.warning("[razorpay] webhook signature mismatch")
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    import json
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("event", "")
    payload = event.get("payload", {})

    if event_type in ("payment.captured", "order.paid"):
        payment_entity = payload.get("payment", {}).get("entity", {})
        order_id = payment_entity.get("order_id", "")
        payment_id = payment_entity.get("id", "")

        if order_id:
            async with get_pool().acquire() as conn:
                record = await conn.fetchrow(
                    "SELECT * FROM payment_transactions WHERE session_id = $1", order_id
                )
                if record and record["payment_status"] != "paid":
                    await _mark_paid(conn, order_id, record, payment_id)

    return {"status": "ok"}