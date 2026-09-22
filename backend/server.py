"""AYANA-BOT application composition, lifecycle and remaining dashboard routes.

See backend/SERVER_MAP.md for module ownership and regression test commands.

Extracted modules (do NOT add new routes here for these areas):
  - Authentication + profile .... routes/auth.py
  - Parents + moments ........... routes/parents.py
  - Schedules + check-ins ....... routes/schedules.py
  - Activation + preferences .... routes/activation.py
  - WhatsApp webhook + replies .. routes/webhook.py
  - Admin dashboards ............ routes/admin.py
  - Email OTP + phone/email change ... routes/account.py
  - Replies list / read ......... routes/replies.py
  - Care circle siblings ........ routes/care.py
  - Billing + subscriptions ..... routes/billing.py
  - Coupons (admin) ............. routes/coupon_admin.py
  - Sanity smoke tests .......... routes/sanity.py

Shared request/domain helpers live in services/deps.py. Extracted routers
never import this composition root. Existing /api prefixes, dependency
objects and overlapping-route precedence are retained deliberately.

Section markers below are also grep-able:
    # ---------------- <SectionName> ----------------
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

# ── Sentry error monitoring ────────────────────────────────────────────────
# MUST init before FastAPI() so Starlette/FastAPI middleware is instrumented.
# Silently no-ops if SENTRY_DSN is not set (safe for local dev).
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    def _sentry_before_send(event, hint):
        # Drop noisy request bodies, cookies, auth headers before shipping
        # to Sentry. Explicit set_user(id/email) still flows through.
        event.pop("extra", None)
        req = event.get("request")
        if req:
            req.pop("data", None)
            req.pop("cookies", None)
            headers = req.get("headers")
            if headers:
                for name in list(headers):
                    if name.lower() in {"authorization", "cookie", "set-cookie", "x-csrf-token", "x-api-key"}:
                        headers.pop(name, None)
        return event

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("SENTRY_RELEASE") or os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "local",
        sample_rate=1.0,
        # No APM/tracing — errors only. Keeps free-tier quota for real crashes.
        send_default_pii=False,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        before_send=_sentry_before_send,
    )

from fastapi import Depends, FastAPI, APIRouter, HTTPException, Query, Request, Response, BackgroundTasks
from rate_limit import api_rate_limit_dependency, close_redis
from starlette.middleware.cors import CORSMiddleware

from database import get_pool, init_db, close_db
from services.deps import _get_client_ip, audit, scope, is_member, _get_plan_id
from models import MEDICINE_SHAPES, MEDICINE_COLORS, MEDICINE_TIMINGS, SendTestInput, PreviewInput, InviteInput, AnalyticsEventInput, SiblingOtpInput, SiblingVerifyInput
from storage import init_storage, is_enabled as storage_enabled
from validation import normalize_phone as _normalize_phone
from routes.account import router as account_router
from routes.care_plan import router as care_plan_router
from services import verification, welcomes, notifications
from services.migrations import apply_care_migration
from services import inbox
from services.delivery_stats import delivery_funnel as _delivery_funnel_shared
from routes.replies import router as replies_router
from routes.care import router as care_router
from routes.billing import router as billing_router
from routes.coupon_admin import router as coupon_router
from routes.admin import router as admin_router
from routes.webhook import router as webhook_router, _process_meta_payload
from routes.activation import router as activation_router, get_activation, payment_state
from routes.schedules import router as schedules_router, checkins_summary, list_schedules
from routes.parents import router as parents_router, list_moments, list_parents, moments_quota
from routes.auth import router as auth_router, get_my_audit

from auth import serialize, get_current_user, get_current_admin, seed_admin, validate_csrf_token
from templates_data import LANGUAGES, RELATIONSHIPS, public_categories, render_slot_body, render_slot_buttons
from pricing import PLANS, CURRENCIES, plan_limits
from scheduler import start_scheduler, shutdown_scheduler
from email_sender import send_invite_email
from monthly_report import generate_monthly_report
from whatsapp import is_session_open, send_dynamic_checkin, send_meal_template, send_medicine_template, send_mood_template, send_whatsapp, send_whatsapp_opener, whatsapp_enabled, send_member_removed_notice, send_sibling_welcome, send_sibling_added_notice

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ayana")


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event (FastAPI ≥ 0.93)
#
# MIGRATION NOTE: ensure_indexes() is gone — indexes live in schema.sql now
# (created once, up front, not on every boot). init_db()/close_db() just
# open/close the asyncpg pool, same slot in the lifecycle the old
# `client`/`ensure_indexes` calls occupied.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    if not os.environ.get("JWT_SECRET", "").strip():
        raise RuntimeError("JWT_SECRET environment variable is required but not set")
    await init_db()
    await seed_admin()
    try:
        await _run_startup_migrations()
    except Exception as e:
        logger.error("Startup migrations failed: %s", e)
    await apply_care_migration()
    inbox.configure(_process_meta_payload)
    if storage_enabled():
        try:
            init_storage()
            logger.info("Object storage initialized")
        except Exception as e:
            logger.error("Object storage init failed (moment images will fail until fixed): %s", e)
    else:
        logger.info("Object storage disabled — /moments photo upload will return 501 until enabled")
    if os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() == "true":
        start_scheduler()
    else:
        logger.info("Scheduler disabled on this instance (SCHEDULER_ENABLED=false)")
    logger.info("AYANA-BOT backend ready")
    yield
    # ── Shutdown ──
    shutdown_scheduler()
    await close_redis()
    await close_db()


app = FastAPI(title="AYANA-BOT API", lifespan=lifespan)

api = APIRouter(prefix="/api")


async def _run_startup_migrations():
    """Idempotent, cheap fixes that must hold on every boot."""
    async with get_pool().acquire() as conn:
        await conn.execute("""
            create table if not exists email_otps (
                email text primary key,
                code_hash text not null,
                expires_at timestamptz not null,
                attempts int not null default 0,
                verified boolean not null default false,
                created_at timestamptz not null default now(),
                verified_at timestamptz,
                send_count int not null default 0,
                send_window_start timestamptz
            )
        """)
        await conn.execute("alter table monthly_reports add column if not exists details jsonb")
        await conn.execute("alter table users add column if not exists password_changed_at timestamptz")
        await conn.execute("alter table users add column if not exists pending_email text")
        # Sprint Phase 1: raw webhook archive (2-week TTL) + wam_id idempotency
        await conn.execute("""
            create table if not exists webhook_debug (
                id uuid primary key default gen_random_uuid(),
                direction text not null default 'inbound',
                payload jsonb not null,
                created_at timestamptz not null default now()
            )
        """)
        await conn.execute("delete from webhook_debug where created_at < now() - interval '14 days'")
        await conn.execute("alter table parent_replies add column if not exists wam_id text")
        await conn.execute("create unique index if not exists idx_parent_replies_wam on parent_replies(wam_id) where wam_id is not null")
        await conn.execute("create unique index if not exists idx_msglogs_sid_uniq on message_logs(sid) where sid is not null")
        await conn.execute("alter table moments add column if not exists sid text")
        await conn.execute("alter table moments add column if not exists delivery_status text")
        await conn.execute("alter table moments add column if not exists delivery_notified boolean not null default false")
        await conn.execute("create index if not exists idx_moments_sid on moments(sid) where sid is not null")
        # Images are uploaded before the moment row exists, so moment_id must be nullable.
        await conn.execute("alter table moment_images alter column moment_id drop not null")
        # Link replies that arrived from Meta as '91xxxxxxxxxx' to parents stored as '+91xxxxxxxxxx'.
        linked = await conn.execute(
            """
            update parent_replies r
            set parent_id = p.id, user_id = p.user_id
            from parents p
            where r.parent_id is null and p.deleted_at is null
              and regexp_replace(p.phone, '\\D', '', 'g') = regexp_replace(r.from_phone, '\\D', '', 'g')
            """
        )
        if linked and not linked.endswith(" 0"):
            logger.info("[migrate] backfilled orphan parent replies: %s", linked)
        # Lightweight product analytics sink (frontend src/lib/analytics.js beacons here).
        await conn.execute("""
            create table if not exists analytics_events (
                id uuid primary key default gen_random_uuid(),
                type text,
                name text,
                page text,
                path text,
                lang text,
                session_id text,
                meta jsonb,
                ip text,
                user_agent text,
                created_at timestamptz not null default now()
            )
        """)
        await conn.execute("create index if not exists idx_analytics_events_created on analytics_events(created_at)")
        await conn.execute("delete from analytics_events where created_at < now() - interval '90 days'")
        # Reply Alerts: track which parent replies the child has seen in-app.
        await conn.execute("alter table parent_replies add column if not exists read_at timestamptz")
        await conn.execute("create index if not exists idx_parentreplies_user_unread on parent_replies(user_id) where read_at is null")
        # #9 Vacation / holiday mode: a paused date range (YYYY-MM-DD, parent-local)
        # during which the scheduler skips ALL sends and auto-resumes after.
        await conn.execute("alter table parents add column if not exists vacation_start text")
        await conn.execute("alter table parents add column if not exists vacation_end text")
        # Anti-flood fix: slot_time lets the scheduler dedup by exact time
        # slot so the same category at a given hour is sent only once.
        await conn.execute("alter table message_logs add column if not exists slot_time text")
        # #11 Care-circle siblings: phone + OTP verified, forwarded the exact same
        # replies/voice the account owner receives (max 2, plan-gated). Replaces
        # the email-invite path in the UI (email delivery was the crash source).
        await conn.execute("""
            create table if not exists care_circle_siblings (
                id          uuid primary key default gen_random_uuid(),
                owner_id    uuid not null references users(id) on delete cascade,
                name        text not null,
                phone       text not null,
                language    text not null default 'en',
                relation    text not null default 'sibling',
                verified    boolean not null default false,
                created_at  timestamptz not null default now()
            )
        """)
        await conn.execute("create index if not exists idx_ccsiblings_owner on care_circle_siblings(owner_id)")
        await conn.execute("create unique index if not exists idx_ccsiblings_owner_phone on care_circle_siblings(owner_id, phone)")

        # ─── NEW: Granular user‑configured schedules ───────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS parent_checkins (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                parent_id UUID NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                time TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_parent_checkins_parent ON parent_checkins(parent_id)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS parent_health_reminders (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                parent_id UUID NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                time TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_parent_health_reminders_parent ON parent_health_reminders(parent_id)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS parent_routines (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                parent_id UUID NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                time TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_parent_routines_parent ON parent_routines(parent_id)")

# ---------------- Health / meta ----------------
@api.get("/debug/sentry-canary")
async def sentry_canary(user: dict = Depends(get_current_admin)):
    """Admin-only: intentionally raises so Sentry can capture a test error.

    Curl after setting SENTRY_DSN on Railway:
      curl -H "Authorization: Bearer $ADMIN_TOKEN" \
           https://api.ayanabott.com/api/debug/sentry-canary
    Check Sentry.io within 30s — event should be there. Delete this
    endpoint or leave it (harmless: admin-only, no side effects).
    """
    raise RuntimeError("Sentry canary: this error is intentional. If you see this in Sentry, monitoring works.")


@api.get("/")
async def root():
    return {"app": "AYANA-BOT", "status": "ok"}

@api.get("/health")
async def health():
    """Self-observability (Phase 5): DB latency, Redis reachability, scheduler
    heartbeat, last inbound webhook, last outbound WhatsApp send.

    200 when Postgres is reachable; 503 only when the DB is down (WhatsApp
    disabled in test mode is reported, not treated as unhealthy).
    """
    problems = []

    # 1. Postgres reachability + latency + activity timestamps
    last_inbound = None
    last_outbound = None
    db_latency_ms = None
    try:
        t0 = datetime.now(timezone.utc)
        async with get_pool().acquire() as conn:
            await conn.fetchval("select 1")
            db_latency_ms = round((datetime.now(timezone.utc) - t0).total_seconds() * 1000, 1)
            last_inbound = await conn.fetchval("select max(created_at) from webhook_debug")
            if not last_inbound:
                last_inbound = await conn.fetchval("select max(created_at) from parent_replies")
            last_outbound = await conn.fetchval(
                "select max(created_at) from message_logs where status in ('sent','simulated')"
            )
        pg_ok = True
    except Exception as e:
        problems.append(f"postgres:{type(e).__name__}")
        pg_ok = False

    # 2. Meta WhatsApp credentials sanity (presence + shape, not a live send)
    meta_token = os.environ.get("META_WA_ACCESS_TOKEN", "").strip()
    meta_phone_id = os.environ.get("META_WA_PHONE_NUMBER_ID", "").strip()
    if whatsapp_enabled():
        meta_state = "configured" if (meta_token and meta_phone_id) else "missing_creds"
        if meta_state != "configured":
            problems.append("meta:missing_creds")
    else:
        meta_state = "disabled"
    webhook_secret_ok = bool((os.environ.get("META_WA_APP_SECRET") or os.environ.get("META_APP_SECRET") or "").strip())
    if whatsapp_enabled() and not webhook_secret_ok:
        problems.append("webhook:app_secret_missing (inbound WhatsApp replies will be rejected)")

    # 3. Redis reachability (optional — rate limits degrade gracefully)
    redis_ok = False
    try:
        from rate_limit import get_redis
        r = await get_redis()
        if r is not None:
            await r.ping()
            redis_ok = True
    except Exception:
        pass

    # 4. APScheduler heartbeat
    from scheduler import scheduler_heartbeat
    sched = scheduler_heartbeat()
    if os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() == "true" and not sched["running"]:
        problems.append("scheduler:not_running")

    body = {
        "status": "healthy" if not problems else "unhealthy",
        "postgres": "up" if pg_ok else "down",
        "db_latency_ms": db_latency_ms,
        "redis": "up" if redis_ok else "down",
        "scheduler": sched,
        "meta": meta_state,
        "webhook_secret": "configured" if webhook_secret_ok else "missing",
        "last_inbound_webhook_at": last_inbound.isoformat() if last_inbound else None,
        "last_outbound_send_at": last_outbound.isoformat() if last_outbound else None,
        "storage": "enabled" if storage_enabled() else "disabled",
        "otp_mode": 'email',
        "problems": problems,
        "release": os.environ.get("SENTRY_RELEASE") or os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "local",
    }
    if not pg_ok:
        raise HTTPException(status_code=503, detail=body)
    return body

@api.get("/ready")
async def ready():
    try:
        async with get_pool().acquire() as conn:
            await conn.fetchval("select 1")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Postgres unavailable: {e}")
    try:
        from rate_limit import get_redis
        r = await get_redis()
        if r is not None:
            await r.ping()
    except Exception:
        pass  # Redis is optional; don't fail readiness
    return {"status": "ready", "postgres": "connected"}

@api.get("/config")
async def public_config():
    return {
        "payments_enabled": os.environ.get("PAYMENTS_ENABLED", "false").lower() == "true",
        "whatsapp_enabled": whatsapp_enabled(),
        "languages": LANGUAGES,
        "relationships": RELATIONSHIPS,
        "categories": public_categories(),
        "medicine_shapes": sorted(list(MEDICINE_SHAPES)),
        "medicine_colors": sorted(list(MEDICINE_COLORS)),
        "medicine_timings": sorted(list(MEDICINE_TIMINGS)),
        "plans": PLANS,
        "currencies": CURRENCIES,
        "training_video_url": os.environ.get("TRAINING_VIDEO_URL", ""),
        "feeling_map": {
            "good": {"emoji": "😊", "label": {"en": "Good", "te": "బాగున్నారు", "hi": "ठीक हूँ"}},
            "okay": {"emoji": "😐", "label": {"en": "Okay", "te": "ఫర్వాలేదు", "hi": "ठीक-ठाक"}},
            "not_well": {"emoji": "😟", "label": {"en": "Not well", "te": "ఒంట్లో బాలేదు", "hi": "तबीयत ठीक नहीं"}},
            "done": {"emoji": "✅", "label": {"en": "Done", "te": "అయ్యింది", "hi": "हो गया"}},
        },
        "reply_mode": "quick_reply_buttons",
    }

# ---------------- Product analytics (public beacon) ----------------

@api.post("/analytics/event")
async def analytics_event(request: Request):
    """Fire-and-forget product analytics sink for the frontend beacon
    (src/lib/analytics.js). Public + best-effort: never blocks the UI and
    never fails the request — a bad body is simply ignored with a 204."""
    try:
        raw = await request.json()
    except Exception:
        return Response(status_code=204)
    if not isinstance(raw, dict):
        return Response(status_code=204)
    try:
        ev = AnalyticsEventInput(**{k: raw.get(k) for k in AnalyticsEventInput.model_fields})
        ua = request.headers.get("User-Agent", "")[:400]
        ip = _get_client_ip(request)
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                insert into analytics_events
                    (type, name, page, path, lang, session_id, meta, ip, user_agent, created_at)
                values ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, now())
                """,
                ev.type, ev.name, ev.page, ev.path, ev.lang, ev.session_id,
                json.dumps(ev.meta or {}), ip, ua,
            )
    except Exception as e:
        logger.debug("[analytics] event ignored: %s", e)
    return Response(status_code=204)

api.include_router(auth_router)

api.include_router(parents_router)

# ---------------- Care Watch manual trigger (testing/ops) ----------------
@api.post("/care-watch/run")
async def run_care_watch_now(user: dict = Depends(get_current_user)):
    from escalation import run_care_watch_impl
    await run_care_watch_impl()
    return {"ok": True, "ran_at": datetime.now(timezone.utc).isoformat()}

api.include_router(schedules_router)

api.include_router(activation_router)

# ---------------- Message logs / dashboard ----------------
@api.get("/messages/logs")
async def message_logs(
    user: dict = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("select count(*) from message_logs where user_id = $1", scope(user))
        docs = await conn.fetch(
            "select * from message_logs where user_id = $1 order by created_at desc offset $2 limit $3",
            scope(user), skip, limit,
        )
    return {"total": total, "skip": skip, "limit": limit, "items": [serialize(d) for d in docs]}


# Language-native fallback when a parent has no medicines set — avoids
# stuffing English "your medicine" into a Telugu/Hindi Meta template.
_MEDICINE_FALLBACK = {
    "en": "your medicine",
    "te": "మందు",
    "hi": "दवाई",
}

_SHAPE_LABELS = {
    "en": {"round": "round", "oval": "oval", "capsule": "capsule", "oblong": "oblong", "diamond": "diamond", "square": "square"},
    "te": {"round": "గుండ్రటి", "oval": "ఓవల్", "capsule": "క్యాప్సూల్", "oblong": "పొడవాటి", "diamond": "డైమండ్", "square": "చతురస్రపు"},
    "hi": {"round": "गोल", "oval": "अंडाकार", "capsule": "कैप्सूल", "oblong": "लंबी", "diamond": "हीरा-आकार", "square": "चौकोर"},
}

_COLOR_LABELS = {
    "en": {"white": "white", "cream": "cream", "yellow": "yellow", "orange": "orange", "pink": "pink", "red": "red", "purple": "purple", "blue": "blue", "green": "green", "brown": "brown", "beige": "beige"},
    "te": {"white": "తెల్ల", "cream": "క్రీమ్ రంగు", "yellow": "పసుపు", "orange": "నారింజ", "pink": "గులాబీ", "red": "ఎర్ర", "purple": "ఊదా", "blue": "నీలం", "green": "ఆకుపచ్చ", "brown": "గోధుమ", "beige": "బేజ్"},
    "hi": {"white": "सफ़ेद", "cream": "क्रीम रंग की", "yellow": "पीली", "orange": "नारंगी", "pink": "गुलाबी", "red": "लाल", "purple": "बैंगनी", "blue": "नीली", "green": "हरी", "brown": "भूरी", "beige": "बेज"},
}

_TABLET_WORD = {"en": "tablet", "te": "మాత్ర", "hi": "गोली"}


def _resolve_medicine_name(parent: dict, target_time: str = "") -> str:
    """Pick a real medicine from parent.medicine_list and describe it as
    "<color> <shape> <name> <tablet-word>" in the parent's language
    (e.g. "white round sugar tablet"), so the WhatsApp message helps them
    identify the right pill, not just its name.

    Mirrors scheduler.py: if target_time is provided, look for the med
    whose reminder_time matches (HH:MM); else use the first med. Falls
    back to a language-native placeholder if the list is empty or the
    matched med has no name.
    """
    meds = parent.get("medicine_list") or []
    if isinstance(meds, str):
        try:
            meds = json.loads(meds) or []
        except Exception:
            meds = []

    lang = (parent.get("language") or "en").lower()
    if lang not in _SHAPE_LABELS:
        lang = "en"

    chosen = None
    if isinstance(meds, list) and meds:
        if target_time:
            for m in meds:
                if isinstance(m, dict) and m.get("reminder_time") == target_time:
                    chosen = m
                    break
        if chosen is None and isinstance(meds[0], dict):
            chosen = meds[0]

    if chosen:
        name = (chosen.get("name") or "").strip()
        if name:
            shape = _SHAPE_LABELS[lang].get(chosen.get("shape"), "")
            color = _COLOR_LABELS[lang].get(chosen.get("color"), "")
            descriptors = " ".join(d for d in (color, shape) if d)
            tablet_word = _TABLET_WORD[lang]
            return f"{descriptors} {name} {tablet_word}" if descriptors else f"{name} {tablet_word}"

    return _MEDICINE_FALLBACK.get(lang, _MEDICINE_FALLBACK["en"])

@api.post("/whatsapp/send-test")
@api.post("/messages/send-test")
async def send_test(payload: SendTestInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token), _rl: None = Depends(api_rate_limit_dependency)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            payload.parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    parent_d = dict(parent)

    slot_type = payload.category or "morning_wish"
    try:
        session_open = await is_session_open(parent["id"])
    except Exception:
        session_open = False

    plan_id = await _get_plan_id(user)
    variants_per_slot = plan_limits(plan_id)["variants_per_slot"]
    day_index = datetime.now(timezone.utc).timetuple().tm_yday
    # Resolve a real medicine name from the parent's medicine_list so
    # Meta template {{2}} isn't the literal English word "your medicine"
    # awkwardly injected mid-Telugu/Hindi sentence. Falls back to a
    # language-native placeholder when the parent has no medicines set.
    med_name = _resolve_medicine_name(parent_d)

    try:
        if session_open:
            if slot_type in ["medicine", "bp_check", "sugar_check"]:
                result = await send_dynamic_checkin(parent_d, slot_type, day_index, variants_per_slot, medicine_name=med_name)
            else:
                result = await send_dynamic_checkin(parent_d, slot_type, day_index, variants_per_slot)
        else:
            if slot_type in ["medicine", "bp_check", "sugar_check", "water", "health_check"]:
                result = await send_medicine_template(parent_d, day_index, variants_per_slot, medicine_name=med_name)
            elif slot_type in ["breakfast", "lunch", "dinner", "afternoon_checkin"]:
                result = await send_meal_template(parent_d, meal_type=slot_type, day_index=day_index, variants_per_slot=variants_per_slot)
            elif slot_type in ["goodnight", "love_note", "how_feeling"]:
                result = await send_mood_template(parent_d, category=slot_type, day_index=day_index, variants_per_slot=variants_per_slot)
            else:
                result = await send_whatsapp_opener(parent_d, day_index, variants_per_slot)
    except Exception as e:
        logger.error(f"[send-test] failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"WhatsApp send failed: {str(e)[:300]}")

    msg_status = result.get("status", "failed")
    msg_type = "reminder" if slot_type in ["medicine", "bp_check", "sugar_check", "water", "health_check"] else "checkin"
    now_utc = datetime.now(timezone.utc)
    try:
        p_tz = ZoneInfo(parent["timezone"] or "Asia/Kolkata")
    except Exception:
        p_tz = ZoneInfo("Asia/Kolkata")

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            insert into message_logs (user_id, parent_id, category, msg_type, status, created_at, day_key)
            values ($1, $2::uuid, $3, $4, $5, $6, $7)
            """,
            scope(user), parent["id"], slot_type, msg_type, msg_status, now_utc,
            now_utc.astimezone(p_tz).strftime("%Y-%m-%d"),
        )
    await audit(user["id"], "send_test", {"parent_id": str(parent["id"]), "slot_type": slot_type, "session_open": session_open, "template_used": result.get("template_type", "dynamic")})
    return {"ok": True, "status": msg_status, "detail": result.get("detail"), "session_open": session_open, "template_type": result.get("template_type", "dynamic")}

SAY_HI_COPY = {
    "en": "💛 Hi {parent_name}! Your child has set up AYANA to stay close. You'll get gentle daily check-ins — just tap or speak, no app needed. We'll start sending tomorrow morning. Take care!",
    "te": "💛 హలో {parent_name}! మీ పిల్ల ఆయనా AYANA సెటప్ చేసారు. మీరు రోజువే సౌకర్యవంతమైన పరిశీలనలు పొందుతారు — ఒక్కసారి నొక్కి లేదా మాట్లాడండి, యాప్ అవసరం లేదు. రేపు ఉదయం మన సందేశాలు ప్రారంభమవుతాయి. జాగ్రత్తగా ఉండండి!",
    "hi": "💛 नमस्ते {parent_name}! आपका बच्चा ने AYANA सेट करवा है। आपको रोज़ाना हल्क़ी से परिचीत होने वाले संदेश मिलेंगे — बस एक टैप या बोलना, कोई ऐप नहीं चाहिए। कल सुबह से शुरू हो जाएगा। ध्यान रखना!",
}


@api.post("/parents/{parent_id}/say-hi")
async def say_hi(parent_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    language = parent["language"] or "en"
    preferred = parent["preferred_name"] or parent["name"] or "Amma"
    copy = SAY_HI_COPY.get(language, SAY_HI_COPY["en"]).format(parent_name=preferred)
    result = send_whatsapp(parent["phone"] or "", copy)
    await audit(user["id"], "say_hi", {"parent_id": str(parent["id"])})
    return {"ok": True, "status": result.get("status"), "detail": result.get("detail")}


@api.post("/messages/preview")
async def preview_message(payload: PreviewInput, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            payload.parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    category = payload.category
    language = parent["language"] or "en"
    plan_id = await _get_plan_id(user)
    variants_per_slot = plan_limits(plan_id)["variants_per_slot"]
    day_index = datetime.now(timezone.utc).timetuple().tm_yday
    body = render_slot_body(category, language, dict(parent), day_index, _resolve_medicine_name(dict(parent)), variants_per_slot)
    buttons = render_slot_buttons(category, language)
    return {"text": body, "buttons": buttons, "language": language}

# ---------------- Care Circle ----------------
@api.get("/circle")
async def get_circle(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        if is_member(user):
            owner = await conn.fetchrow("select * from users where id = $1::uuid", user["household_owner_id"])
            return {"role": "member", "owner": {"name": owner["name"] if owner else "", "email": owner["email"] if owner else ""}}
        uid = user["id"]
        plan_id, members, invites = await asyncio.gather(
            _get_plan_id(user),
            get_pool().fetch(
                "select * from users where household_owner_id = $1 and deleted_at is null limit 20", uid
            ),
            get_pool().fetch(
                "select * from circle_invites where owner_id = $1 and status = 'pending' limit 20", str(uid)
            ),
        )
        max_members = plan_limits(plan_id).get("family_members", 1)
        siblings = await get_pool().fetch(
            "select * from care_circle_siblings where owner_id = $1 order by created_at", str(uid)
        )
    return {
        "role": "owner",
        "plan": plan_id,
        "max_members": max_members,
        "members": [{"id": str(m["id"]), "name": m["name"], "email": m["email"]} for m in members],
        "invites": [{"id": str(i["id"]), "email": i["email"]} for i in invites],
        "siblings": [
            {"id": str(s["id"]), "name": s["name"], "phone": s["phone"],
             "language": s["language"], "relation": s["relation"], "verified": s["verified"]}
            for s in siblings
        ],
    }

@api.post("/circle/invite")
async def invite_member(payload: InviteInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token), _rl: None = Depends(api_rate_limit_dependency)):
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can invite family members.")
    uid = user["id"]
    plan_id = await _get_plan_id(user)
    max_members = plan_limits(plan_id).get("family_members", 1)
    if max_members < 1:
        raise HTTPException(status_code=403, detail="Family co-care requires Raksha. Upgrade to invite siblings.")
    email = (payload.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email.")
    if email == user.get("email"):
        raise HTTPException(status_code=400, detail="That's your own email 🙂")

    async with get_pool().acquire() as conn:
        current = await conn.fetchval(
            "select count(*) from users where household_owner_id = $1 and deleted_at is null", uid
        )
        pending = await conn.fetchval(
            "select count(*) from circle_invites where owner_id = $1 and status = 'pending'", str(uid)
        )
        if current + pending >= max_members:
            raise HTTPException(status_code=400, detail=f"Your plan allows up to {max_members} care-circle member(s).")
        existing_member = await conn.fetchrow(
            "select 1 from users where email = $1 and household_owner_id = $2 and deleted_at is null",
            email, uid,
        )
        if existing_member:
            raise HTTPException(status_code=400, detail="This person is already in your care circle.")
        if await conn.fetchrow(
            "select 1 from circle_invites where owner_id = $1 and email = $2 and status = 'pending'", str(uid), email
        ):
            raise HTTPException(status_code=400, detail="You've already invited this email. Check the Care circle tab to resend.")

        import jwt as _jwt
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        invite_row = await conn.fetchrow(
            """
            insert into circle_invites (owner_id, email, status, created_at, expires_at, inviter_name, parent_id)
            values ($1, $2, 'pending', now(), $3, $4, $5)
            returning *
            """,
            str(uid), email, expires_at, user.get("name", "Someone"), payload.parent_id or None,
        )
        parent_display_name = ""
        if payload.parent_id:
            p = await conn.fetchrow(
                "select * from parents where id = $1::uuid and user_id = $2", payload.parent_id, uid
            )
            if p:
                parent_display_name = p["preferred_name"] or p["name"] or ""

    await audit(uid, "circle_invite", {"email": email})
    invite_token = _jwt.encode(
        {"sub": str(invite_row["id"]), "type": "invite", "exp": expires_at},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    frontend = os.environ.get("FRONTEND_URL", "").rstrip("/")
    link = f"{frontend}/invite/{invite_token}" if frontend else f"/invite/{invite_token}"
    try:
        email_result = await send_invite_email(
            to_email=email,
            owner_name=user.get("name", "Someone"),
            invite_link=link,
            parent_display_name=parent_display_name,
        )
    except Exception as e:
        logger.error("[circle] send_invite_email raised for %s: %s", email, e, exc_info=True)
        email_result = {"status": "failed", "detail": str(e)[:200]}
    logger.info("Care circle invite for %s → email_status=%s", email, email_result.get("status"))
    return {"ok": True, "email": email, "invite_link": link, "email_status": email_result.get("status")}

@api.post("/circle/accept")
async def accept_invite(user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        invite = await conn.fetchrow(
            "select * from circle_invites where email = $1 and status = 'pending'", user.get("email")
        )
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found.")
        if invite["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"This invite has already been {invite['status']}.")
        parent_display_name = ""
        if invite["parent_id"]:
            p = await conn.fetchrow("select * from parents where id = $1", invite["parent_id"])
            if p:
                parent_display_name = p["preferred_name"] or p["name"] or ""
    return {
        "invite_id": str(invite["id"]), "email": invite["email"],
        "inviter_name": invite["inviter_name"] or "", "parent_display_name": parent_display_name,
        "expires_at": invite["expires_at"].isoformat() if invite["expires_at"] else None,
        "status": invite["status"],
    }

@api.get("/circle/invite/{token}")
async def preview_invite_by_token(token: str):
    import jwt as _jwt
    try:
        payload = _jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        if payload.get("type") != "invite":
            raise HTTPException(status_code=400, detail="Invalid invite link.")
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="This invite link has expired.")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid invite link.")
    async with get_pool().acquire() as conn:
        invite = await conn.fetchrow("select * from circle_invites where id = $1::uuid", payload["sub"])
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found.")
        if invite["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"This invite has already been {invite['status']}.")
        parent_display_name = ""
        if invite["parent_id"]:
            p = await conn.fetchrow("select * from parents where id = $1", invite["parent_id"])
            if p:
                parent_display_name = p["preferred_name"] or p["name"] or ""
    return {
        "email": invite["email"],
        "inviter_name": invite["inviter_name"] or "",
        "parent_display_name": parent_display_name,
        "expires_at": invite["expires_at"].isoformat() if invite["expires_at"] else None,
        "status": invite["status"],
    }

@api.post("/circle/invite/{token}/accept")
async def accept_invite_by_token(token: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    import jwt as _jwt
    try:
        payload = _jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        if payload.get("type") != "invite":
            raise HTTPException(status_code=400, detail="Invalid invite token.")
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="This invite link has expired.")
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid invite token.")

    async with get_pool().acquire() as conn:
        invite = await conn.fetchrow("select * from circle_invites where id = $1::uuid", payload["sub"])
        if not invite or invite["status"] != "pending":
            raise HTTPException(status_code=409, detail="This invite is no longer valid.")
        if invite["email"] != user.get("email"):
            raise HTTPException(status_code=403, detail="This invite was sent to a different email address.")
        now = datetime.now(timezone.utc)
        await conn.execute(
            "update users set household_owner_id = $1::uuid, onboarding_complete = true where id = $2",
            invite["owner_id"], user["id"],
        )
        await conn.execute(
            "update circle_invites set status = 'accepted', accepted_at = $1, member_id = $2 where id = $3",
            now, str(user["id"]), invite["id"],
        )
    await audit(user["id"], "circle_invite_accepted", {"invite_id": str(invite["id"])})
    return {"ok": True, "owner_id": invite["owner_id"]}

@api.delete("/circle/member/{member_id}")
async def remove_member(member_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can remove members.")
    async with get_pool().acquire() as conn:
        member = await conn.fetchrow(
            "select phone from users where id = $1::uuid and household_owner_id = $2",
            member_id, str(user["id"]),
        )
        await conn.execute(
            "update users set household_owner_id = null where id = $1::uuid and household_owner_id = $2",
            member_id, str(user["id"]),
        )
    # Let the removed Care Circle member know — best-effort.
    if member and member["phone"]:
        background_tasks.add_task(send_member_removed_notice, member["phone"], "en")
    return {"ok": True}

@api.delete("/circle/invite/{invite_id}")
async def cancel_invite(invite_id: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    async with get_pool().acquire() as conn:
        await conn.execute(
            "update circle_invites set status = 'cancelled' where id = $1::uuid and owner_id = $2",
            invite_id, str(user["id"]),
        )
    return {"ok": True}


# ── #11 Care-circle siblings (phone + OTP, no email) ────────────────────────



async def _sibling_guard(user: dict) -> tuple[str, int]:
    """Shared checks for sibling add: owner-only + Raksha plan gate. Returns
    (owner_uid, max_members)."""
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can add siblings.")
    plan_id = await _get_plan_id(user)
    max_members = plan_limits(plan_id).get("family_members", 0)
    if max_members < 1:
        raise HTTPException(status_code=403, detail="Family co-care requires Raksha. Upgrade to add siblings.")
    return str(user["id"]), max_members


@api.post("/circle/sibling/send-otp")
async def sibling_send_otp(payload: SiblingOtpInput, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token), _rl: None = Depends(api_rate_limit_dependency)):
    uid, max_members = await _sibling_guard(user)
    phone = _normalize_phone(payload.phone)
    if user.get("phone") and _normalize_phone(user["phone"]) == phone:
        raise HTTPException(status_code=400, detail="That's your own number 🙂")
    async with get_pool().acquire() as conn:
        current = await conn.fetchval(
            "select count(*) from care_circle_siblings where owner_id = $1 and verified = true", uid
        )
        if current >= max_members:
            raise HTTPException(status_code=400, detail=f"Your plan allows up to {max_members} sibling(s). Remove one first.")
        dup = await conn.fetchrow(
            "select 1 from care_circle_siblings where owner_id = $1 and regexp_replace(phone, '\\D', '', 'g') = regexp_replace($2, '\\D', '', 'g') and verified = true",
            uid, phone,
        )
        if dup:
            raise HTTPException(status_code=400, detail="This person is already in your care circle.")
    return await verification.issue(user['id'], payload.email.lower(), 'add_sibling', phone, {'email': payload.email.lower(), 'name': payload.name.strip(), 'language': payload.language})


@api.post("/circle/sibling/verify")
async def sibling_verify(payload: SiblingVerifyInput, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    uid, max_members = await _sibling_guard(user)
    phone = _normalize_phone(payload.phone)
    proof = await verification.check(payload.challenge_id, payload.code, user['id'], 'add_sibling', phone)
    proof_context = json.loads(proof['context']) if isinstance(proof['context'], str) else proof['context']
    if proof_context['email'] != payload.email.lower() or proof_context['name'] != payload.name.strip() or proof_context['language'] != payload.language:
        raise HTTPException(409, 'Sibling details changed. Request a fresh code.')
    lang = (payload.language or "en").strip().lower()[:2] or "en"
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'circle:' + uid)
        await verification.consume(conn, proof)
        current = await conn.fetchval(
            "select count(*) from care_circle_siblings where owner_id = $1 and verified = true", uid
        )
        if current >= max_members:
            raise HTTPException(status_code=400, detail=f"Your plan allows up to {max_members} sibling(s).")
        try:
            sib = await conn.fetchrow(
                """
                insert into care_circle_siblings (owner_id, name, phone, language, relation, verified, created_at, email, email_verified_at)
                values ($1, $2, $3, $4, $5, true, now(), $6, now())
                on conflict (owner_id, phone) do update
                    set name = excluded.name, language = excluded.language,
                        relation = excluded.relation, verified = true, email=excluded.email, email_verified_at=now()
                returning *
                """,
                uid, payload.name.strip(), phone, lang, (payload.relation or "sibling").strip(), payload.email.lower(),
            )
        except Exception as e:
            logger.error("[circle] sibling insert failed for %s: %s", uid, e, exc_info=True)
            raise HTTPException(status_code=500, detail="Could not add sibling. Please try again.")
        parent_rows = await conn.fetch("select name, preferred_name from parents where user_id = $1 and deleted_at is null", uid)
    parent_names = [ (p["preferred_name"] or p["name"]) for p in parent_rows ]
    owner_name = (user.get("name") or "your family").split()[0]
    checking_for = (", ".join([p for p in parent_names if p]) or owner_name or "your family")[:20]
    # Durable: retried by welcomes.drain() on failure, not lost like the
    # old background_tasks.add_task(send_sibling_welcome, ...) call.
    background_tasks.add_task(welcomes.welcome_sibling, dict(sib), checking_for)
    if user.get("phone"):
        background_tasks.add_task(send_sibling_added_notice, user["phone"], payload.name.strip(), lang)
    await audit(user["id"], "sibling_added", {"phone": phone, "name": payload.name.strip()})
    return {
        "ok": True,
        "sibling": {"id": str(sib["id"]), "name": sib["name"], "phone": sib["phone"],
                    "language": sib["language"], "relation": sib["relation"], "verified": sib["verified"]},
    }


@api.delete("/circle/sibling/{sibling_id}")
async def remove_sibling(sibling_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    if is_member(user):
        raise HTTPException(status_code=403, detail="Only the account owner can remove siblings.")
    async with get_pool().acquire() as conn, conn.transaction():
        sib = await conn.fetchrow(
            "select * from care_circle_siblings where id = $1::uuid and owner_id = $2 for update", sibling_id, str(user["id"])
        )
        if sib:
            await notifications.cancel_pending(conn, 'sibling', sib['id'])
            await welcomes.cancel_recipient(conn, 'sibling', sib['id'])
        await conn.execute(
            "delete from care_circle_siblings where id = $1::uuid and owner_id = $2", sibling_id, str(user["id"])
        )
    if sib and sib["phone"]:
        background_tasks.add_task(send_member_removed_notice, sib["phone"], sib["language"] or "en")
    await audit(user["id"], "sibling_removed", {"sibling_id": sibling_id})
    return {"ok": True}

# ---------------- Monthly reports ----------------
@api.get("/reports/monthly")
async def get_monthly_report(parent_id: str, period: str, user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
        report = await conn.fetchrow(
            "select * from monthly_reports where user_id = $1 and parent_id = $2::uuid and period = $3",
            scope(user), parent_id, period,
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    # "Month so far" must be live: the current month's report is a snapshot
    # that goes stale the moment a check-in goes out or a reply lands (a
    # parent replying at 21:44 was invisible in a report generated at 21:28).
    # Auto-regenerate the CURRENT period when missing or older than 15 min.
    current_period = datetime.now(timezone.utc).strftime("%Y-%m")
    if period == current_period:
        gen_at = report["generated_at"] if report else None
        if gen_at is not None and gen_at.tzinfo is None:
            gen_at = gen_at.replace(tzinfo=timezone.utc)
        is_stale = gen_at is None or gen_at < datetime.now(timezone.utc) - timedelta(minutes=15)
        if is_stale:
            try:
                year, month = (int(x) for x in period.split("-"))
                plan_id = await _get_plan_id(user)
                fresh = await generate_monthly_report(scope(user), parent["id"], plan_id, year, month)
                fresh["found"] = True
                return fresh
            except Exception as e:
                logger.error("[reports] current-month auto-refresh failed: %s", e, exc_info=True)
                # fall through to the stored snapshot rather than failing the view

    if not report:
        return {"found": False, "parent_id": parent_id, "period": period}
    out = serialize(report)
    out["found"] = True
    return out

@api.post("/reports/monthly/generate")
async def generate_monthly_report_now(parent_id: str, period: str, user: dict = Depends(get_current_user), _csrf: None = Depends(validate_csrf_token)):
    try:
        year, month = (int(x) for x in period.split("-"))
    except Exception:
        raise HTTPException(status_code=400, detail="period must be YYYY-MM")
    async with get_pool().acquire() as conn:
        parent = await conn.fetchrow(
            "select * from parents where id = $1::uuid and user_id = $2 and deleted_at is null",
            parent_id, scope(user),
        )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    plan_id = await _get_plan_id(user)
    report = await generate_monthly_report(scope(user), parent["id"], plan_id, year, month)
    await audit(user["id"], "generate_monthly_report", {"parent_id": parent_id, "period": period})
    return report

@api.post("/reports/generate")
async def trigger_monthly_reports(
    year: int = Query(..., description="Year e.g. 2025"),
    month: int = Query(..., description="Month 1-12"),
    user: dict = Depends(get_current_admin),
):
    """Admin bulk trigger: generate reports for ALL parents for given month and WhatsApp PDF to child + siblings"""
    from monthly_report import generate_reports_for_month
    await generate_reports_for_month(year, month)
    return {"status": "started", "period": f"{year:04d}-{month:02d}", "note": "Reports generating + WhatsApp sending to child + siblings in background"}


api.include_router(webhook_router)

# ---------------- Dashboard bootstrap (one round-trip for the whole dashboard) ----------------
@api.get("/dashboard/bootstrap")
async def dashboard_bootstrap(user: dict = Depends(get_current_user)):
    parents, schedules, checkins, activation, payment, circle, audit_logs, quota, moments = await asyncio.gather(
        list_parents(user),
        list_schedules(user),
        checkins_summary(user, days=7),
        get_activation(user),
        payment_state(user),
        get_circle(user),
        get_my_audit(user),
        moments_quota(user),
        list_moments(user),
    )
    async with get_pool().acquire() as conn:
        funnel = await _delivery_funnel_shared(conn, str(scope(user)))
        unread_replies = await conn.fetchval(
            "select count(*) from parent_replies where user_id = $1 and read_at is null", scope(user)
        )
    return {
        "parents": parents,
        "schedules": schedules,
        "checkins": checkins,
        "activation": activation,
        "payment": payment,
        "circle": circle,
        "audit": audit_logs,
        "moments_quota": quota,
        "moments": moments,
        "delivery_funnel": funnel,
        "unread_replies": unread_replies or 0,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


app.include_router(api)
app.include_router(account_router)
app.include_router(care_plan_router)
app.include_router(replies_router)
app.include_router(care_router)
app.include_router(billing_router)
app.include_router(coupon_router)
app.include_router(admin_router)
from routes.sanity import router as sanity_router
app.include_router(sanity_router)

# Razorpay payments router (endpoints are self-prefixed with /api). Kept in a
# separate module; only actually reachable when PAYMENTS_ENABLED=true.
from razorpay_payments import razorpay_router
app.include_router(razorpay_router)

_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Hub-Signature-256", "X-Dev-Token", "X-Razorpay-Signature", "X-CSRF-Token", "User-Agent"],
    )

@app.middleware("http")
async def log_origin_header(request: Request, call_next):
    if request.method == "OPTIONS":
        logger.info(
            "[CORS DEBUG] Origin=%r | Method=%s | Path=%s | ACR-Method=%r | ACR-Headers=%r",
            request.headers.get("origin"),
            request.method,
            request.url.path,
            request.headers.get("access-control-request-method"),
            request.headers.get("access-control-request-headers"),
        )
    response = await call_next(request)
    return response


# Startup and shutdown are handled by the lifespan context manager above.