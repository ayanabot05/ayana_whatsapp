"""AYANA activation; extracted without changing API behaviour."""
import asyncio
import json
import os
from datetime import datetime, timezone
from fastapi import Depends, APIRouter, HTTPException, Request, BackgroundTasks
from database import get_pool
from models import PreferencesInput, ConsentInput, CheckoutInput
from routes.account import require_email
from services import billing_access
from services.welcomes import welcome_parent_and_child
from auth import serialize, get_current_user, validate_csrf_token
from pricing import PLANS, CURRENCIES, PLAN_BY_ID, resolve_plan_id
from whatsapp import whatsapp_enabled
from services.deps import audit, scope, is_member, _plan_usage, _validate_plan_transition


router = APIRouter()


# ---------------- Consent & Preferences ----------------
@router.post("/consent")
async def log_consent(payload: ConsentInput, request: Request, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into consent_logs (user_id, consent_type, agreed, text, ip, created_at)
            values ($1, $2, $3, $4, $5, now())
            """,
            str(user["id"]), payload.consent_type, payload.agreed, payload.text,
            request.client.host if request.client else None,
        )
    await audit(user["id"], "consent", {"type": payload.consent_type, "agreed": payload.agreed})
    return {"ok": True}

@router.put("/preferences")
async def update_prefs(payload: PreferencesInput, user: dict = Depends(get_current_user)):
    # MIGRATION NOTE: Mongo's dot-notation partial $set on an embedded doc
    # (preferences.k) is replaced with a jsonb merge (`preferences || $1`).
    # exclude_unset=True still means only keys the client actually sent are
    # touched — jsonb `||` overwrites just those top-level keys and leaves
    # the rest of the preferences object untouched, same semantics as
    # before (including allowing an explicit null to be set).
    patch = payload.model_dump(exclude_unset=True)
    async with get_pool().acquire() as conn:
        if patch:
            await conn.execute(
                "update users set preferences = coalesce(preferences, '{}'::jsonb) || $1::jsonb where id = $2",
                json.dumps(patch), user["id"],
            )
        updated = await conn.fetchrow("select * from users where id = $1", user["id"])
    return serialize(updated)

# ---------------- Payment ----------------
async def _empty_usage():
    return {}

@router.get("/payment/state")
async def payment_state(user: dict = Depends(get_current_user)):
    state, usage = await asyncio.gather(
        get_pool().fetchrow("select * from payment_state where user_id = $1", scope(user)),
        _plan_usage(scope(user)) if not is_member(user) else _empty_usage(),
    )
    plan = resolve_plan_id((state["plan"] if state else "nitya") or "nitya")
    state_out = serialize(state) if state else {"status": "trial", "plan": plan, "billing": "month"}
    state_out["plan"] = plan
    return {
        "payments_enabled": os.environ.get("PAYMENTS_ENABLED", "false").lower() == "true",
        "state": state_out,
        "plans": PLANS,
        "currencies": CURRENCIES,
        "usage": usage,
    }

@router.post("/payment/checkout")
async def payment_checkout(payload: CheckoutInput, request: Request, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if os.environ.get('PAYMENT_PROVIDER') == 'razorpay':
        raise HTTPException(409,'Use the Razorpay checkout or free-trial selection. The legacy checkout cannot change paid access.')
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can change the plan.")
    plan = resolve_plan_id(payload.plan)
    billing = payload.billing
    if plan not in PLAN_BY_ID:
        plan = "nitya"
    usage = await _validate_plan_transition(user["id"], plan)
    currency = getattr(payload, "currency", "INR") or "INR"
    if os.environ.get("PAYMENTS_ENABLED", "false").lower() != "true":
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                insert into payment_state (user_id, status, plan, billing, updated_at)
                values ($1, 'trial', $2, $3, now())
                on conflict (user_id) do update
                    set status = 'trial', plan = excluded.plan, billing = excluded.billing, updated_at = now()
                """,
                user["id"], plan, billing,
            )
            await conn.execute(
                "update users set onboarding_step = greatest(onboarding_step, 2) where id = $1", user["id"]
            )
        await audit(user["id"], "payment_skipped_test_mode", {"plan": plan, "billing": billing})
        return {"skipped": True, "plan": plan, "billing": billing, "usage": usage, "message": "Payments are disabled in testing mode. Trial access granted."}
    from razorpay_payments import create_razorpay_order
    result = await create_razorpay_order(str(user["id"]), plan, billing, currency)
    await audit(user["id"], "payment_checkout_created", {"plan": plan, "billing": billing, "order_id": result.get("order_id")})
    return {"skipped": False, "plan": plan, "billing": billing, "usage": usage, **result}

# ---------------- Activation ----------------
@router.get("/activation")
async def get_activation(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        state = await conn.fetchrow("select * from activation_state where user_id = $1", scope(user))
    return serialize(state) if state else {"whatsapp_activated": False}

@router.post("/activation/activate")
async def activate(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    require_email(user)
    if is_member(user):
        raise HTTPException(403, 'Only the account owner can activate care.')
    async with get_pool().acquire() as conn:
        parents = await conn.fetch(
            "select * from parents where user_id = $1 and deleted_at is null limit 50", scope(user)
        )
        schedules = await conn.fetch(
            "select * from schedules where user_id = $1 and deleted_at is null limit 50", scope(user)
        )
    if not parents or not schedules:
        raise HTTPException(status_code=400, detail="Please add a parent and a schedule before activating.")

    configured = {str(s['parent_id']) for s in schedules if s['active']}
    if any(str(p['id']) not in configured for p in parents):
        raise HTTPException(400, 'Each parent needs an active saved schedule before activation.')
    async with get_pool().acquire() as conn,conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','billing:'+str(user['id']))
        await billing_access.begin_trial(conn,user['id'])
    results = [{'parent':p['name'],'status':'pending'} for p in parents]
    activated = True  # Scheduling configuration, NOT proof of WhatsApp delivery.

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into activation_state (user_id, whatsapp_activated, activated_at)
            values ($1, $2, $3)
            on conflict (user_id) do update
                set whatsapp_activated = excluded.whatsapp_activated, activated_at = coalesce(activation_state.activated_at,excluded.activated_at)
            """,
            scope(user), activated, datetime.now(timezone.utc) if activated else None,
        )
        await conn.execute(
            "update users set onboarding_complete = true, onboarding_step = 5 where id = $1", user["id"]
        )
    await audit(user["id"], "activate_whatsapp", {"results": results, "activated": activated, "welcome_flow": True})
    for parent in parents:
        background_tasks.add_task(welcome_parent_and_child,dict(parent),dict(user))
    return {"activated": activated, "whatsapp_enabled": whatsapp_enabled(), "results": results, "welcome_sent": False, 'welcome_status':'pending', 'message':'Care is configured. Welcome delivery is tracked separately.'}
