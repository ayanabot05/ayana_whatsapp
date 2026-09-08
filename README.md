# AYANA — WhatsApp Care Companion for Elderly Parents

**AYANA** is an automated, culturally warm care companion that sends daily check-ins to elderly Indian parents over **WhatsApp** — on behalf of their adult children living far away. Parents reply with **one tap** or a **voice note** in Telugu, Hindi, or English. Children get **instant updates** on their dashboard.

> 💛 No app to install. No typing needed. Just WhatsApp — the way your parents already chat.

**Live:** [ayanabott.com](https://www.ayanabott.com)

---

## Who It's For

| Role | Description |
|---|---|
| **Child (Account owner)** | Adult children — especially NRIs in USA, UK, UAE, Singapore, Canada, Australia — who worry about aging parents back home. Each account has one owner, who can add up to 2 siblings/cousins to the care circle by **WhatsApp number (OTP-verified)** on the Raksha plan. |
| **Parent (Recipient)** | Elderly Indian parents (60–85+) comfortable with WhatsApp. They tap buttons or hold the mic. Zero learning curve. |
| **Sibling / cousin (Care circle)** | Up to 2 phone-verified family members (Raksha) who receive the **exact same forwarded reply + voice note** the account owner gets. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11, FastAPI, PostgreSQL via Supabase (asyncpg, connection pooled), APScheduler |
| **Frontend** | React 19 (craco), Tailwind CSS, Radix UI, Recharts, Framer Motion, Three.js |
| **Messaging** | WhatsApp Cloud API (Meta) — 6 approved template families × 3 languages = 18 templates, quick-reply buttons baked into the templates |
| **AI / ML** | Sarvam AI — STT (saarika:v2.5), LLM distress classifier (sarvam-105b), translation engine |
| **Auth** | Dual JWT (access 30 min + refresh 7 day), HttpOnly cookies, bcrypt, CSRF double-submit |
| **OTP** | Twilio SMS, plus an on-screen dev mode (`OTP_MODE=onscreen`) used for sibling verification |
| **Payments** | Stripe Checkout — currently a one-time charge per plan change, **not** a recurring subscription (see Known Limitations) |
| **Email** | Resend API (transactional) |
| **Storage** | S3-compatible object storage (HMAC-signed URLs) |
| **Rate limiting** | Redis sliding-window (degrades gracefully if Redis is absent) |
| **Hosting** | Railway (backend), Vercel (frontend), Supabase (Postgres) |

---

## The WhatsApp 24-Hour Window (How Delivery Actually Works)

WhatsApp has two send modes, and AYANA uses both deliberately:

- **Approved templates** can be sent **any time**, whether or not a session is open. This is the always-available channel.
- **Free-form text and standalone interactive buttons** can only be sent **inside the 24-hour customer-service window** (within 24 h of the parent's last inbound message). Meta silently drops them when no session is open.

**AYANA's routing:**

1. **First contact is always a template.** When a parent is added, both the parent **and** the child are welcomed with the approved `ayana_opener` template (`send_welcome_for_new_parent` → `send_opener_welcome`). A brand-new (cold) number has no open session, so a template is the only thing that will deliver. The child's signup welcome is intentionally **gated** until the first parent is added.
2. **Templates carry quick-reply buttons**, so a parent can tap Good / Okay / Not-well (or Taken / Skipped) **even with the session closed** — no dead air while waiting for a session.
3. **Daily check-ins:** session closed → approved template (with buttons); session open → free interactive quick-reply buttons as a cost optimisation with richer rotating content.
4. **Out-of-session button taps** return `{id, title}`. AYANA maps them to the right intent by structured id, or — when a template button has no structured id — by matching the localised **title** the parent tapped (Good / బాగున్నా / अच्छा, Taken / వేసుకున్నా / ले लिया).

A parent who is silent, busy, or on holiday for a week still receives every scheduled check-in as a tappable template. When she taps, the 24 h session reopens and sends drop back to free interactive messages. Nobody is ever unreachable.

> ⚠️ Verify current Meta per-message / utility-template pricing before launch — the architecture above is correct regardless; only the cost math shifts.

---

## Positioning & Liability (Read Before Pitching)

AYANA is a **peace-of-mind companion that keeps family in the loop — not a medical device, and not a 911/108 replacement.** This wording belongs verbatim in the ToS, disclaimer, and pitch deck.

- **Human-in-the-loop only.** AYANA escalates a *signal* to the family; the family decides and acts. AYANA never auto-dials emergency services and never promises a guaranteed emergency response.
- **Distress detection is two honest layers:** a deterministic keyword layer (kept on) and an assistive/beta Sarvam AI voice layer (behind a flag) that *surfaces concerning signals for family review* — it does not "detect emergencies."
- The defensible product value is the **escalation engine** (no-reply → retry → alert family + care circle). Distress AI is demo magic; escalation is the moat.

---

## Complete Feature Set

### 🏠 Parent Profile & Personalization
- **Relationship model:** Mother / Father → maps to Amma / Nanna / Maa / Papa
- **Preferred name & nicknames:** up to 3 daily-rotating nicknames (Bangaram, Buji, Chinni, …)
- **Birthday auto-wishes** (MM-DD) and **festival auto-wishes** (New Year, Sankranti/Pongal, Independence Day, Holi, Diwali)
- **Seasonal greetings:** auto-adapts to winter / summer / monsoon / pleasant
- **Family stories:** up to 5 rotating memories woven into messages
- **Other-parent mention:** "Did Nanna have lunch too?"
- **Language auto-detection:** if the parent replies in a different script, AYANA suggests switching
- **Quiet hours (DND):** manual activity window (06:00–22:00 default) via `activity_window_start` / `activity_window_end`

### 📋 Daily Check-ins & Scheduling (15 categories)
| Type | Categories |
|---|---|
| **Check-ins** | Morning wish, Breakfast, Lunch, Dinner, Afternoon check-in, Tea/Coffee, Walk, How are you feeling?, Goodnight, Love note |
| **Reminders** | Medicine, Water, BP check, Sugar check, Health check |

- **Rotational message variants:** up to 7 hand-crafted variants per slot/category/language
- **First-contact welcome via template** (see the 24-Hour Window section) — reaches cold numbers reliably
- **Hybrid routing + button-title fallback** for out-of-session taps
- **Configurable re-engagement:** 1–24 h (default 4 h) silent-parent ping

### 💊 Medicine Management
- Name, dosage, shape (6 types), colour (11 colours), timing relative to food
- Custom reminder times (HH:MM) with visual pill cards
- Auto-syncs medicine times into schedule slots (`medicine_sync.py`)

### 🔔 Care Watch Escalation Engine
- Auto-retries unanswered messages every 30 min for up to 2 h (4 attempts)
- Afternoon no-reply alert (2 PM local) → notifies child + care circle + emergency contacts
- Any reply instantly cancels all retries

### 🚨 Two-Layer Emergency & Distress Detection
- **Layer 1 (Keyword):** multilingual matching — help, fell, hospital, chest pain, etc. in EN/TE/HI + custom keywords
- **Layer 2 (AI voice, beta):** Sarvam-105b analyses voice transcripts for hidden distress; off by default (`DISTRESS_ML_ENABLED=false`), needs `SARVAM_API_KEY`
- Emergency events are recorded, alert the whole family, and are never auto-purged

### 🎤 Voice Note Handling
- Downloads from Meta Graph API → transcribes via Sarvam STT (te-IN, hi-IN, en-IN) → runs through distress detection
- Child gets "🎤 Amma sent you a voice note"; the transcript + voice are forwarded to the care circle too

### 📸 Two-Way Moments (Child → Parent)
- Send warm notes + up to 2 photos to the parent's WhatsApp
- Client-side optimisation (max 1200 px, EXIF stripped), uploaded to S3 with HMAC-SHA256 signed URLs
- Monthly quota governed by plan

### 👨‍👩‍👦 Care Circle (Raksha plan)
- Add up to **2 siblings/cousins by WhatsApp number, verified with an OTP** (dev mode shows the code on screen; production uses SMS/WhatsApp)
- Each verified sibling receives the **exact same forwarded reply + voice note** the account owner gets whenever a parent replies
- Adding a sibling sends them the `ayana_opener` welcome and notifies the main child that they joined
- Billing stays with the owner; siblings count toward the plan's `family_members` limit, so a downgrade below current usage is blocked with an actionable "remove first" list
- Data model: `care_circle_siblings (owner_id, name, phone, language, relation, verified)`

### 🌴 Vacation / Holiday Mode
- Per-parent paused date range (`vacation_start` / `vacation_end`, parent-local `YYYY-MM-DD`)
- The scheduler skips **all** check-ins, reminders, and re-engagement pings while today is inside the range, then auto-resumes the day after
- Edited per parent from the Dashboard's "A Moment" tab; endpoint `PUT /parents/{id}/vacation`

### 🏥 Surgery Recovery Mode (Raksha plan)
- Enables 2–4 extra daily reminder slots for 30–90 days, auto-reverts and archives when the period ends

### 📊 Monthly Reports & Mood Analytics
- Total touches, delivered vs. skipped, voice-note count
- Daily mood graph (Good = 1.0, Okay = 0.5, Not well = 0.0), first-half vs. second-half trend analysis
- Reply attribution is **consume-once** — each parent reply is counted against exactly one message, so the Check-ins tab, dashboard stats, and monthly report all agree
- Auto-generated on the 1st of each month (`AUTO_MONTHLY_REPORTS=true`), nudged via the `ayana_report_ready` template

### 💬 What Happens When a Parent Taps Each Button
| Context | Buttons | What happens |
|---|---|---|
| **Mood / Morning** | Good 😊 / Okay 🙂 / Not well 😟 | Mood recorded, child + care circle notified instantly |
| **Medicine** | Taken ✅ / Not yet / Skipped | Tracked, retries stop on "Taken", logged in the monthly report |
| **Meal** | Yes / Not Yet / Skip | Meal tracked, child notified |
| **Re-engagement** | I'm fine / Need help / Call me | Relief / dashboard alert / urgent "call me" notification |
| **Voice note** | Hold 🎤 mic | Transcribed → distress-checked → "🎤 Amma sent a voice note" |

---

## 6 Meta-Approved WhatsApp Template Families (× en/te/hi = 18)

| Template | Used for | Variables |
|---|---|---|
| `ayana_opener` | First-contact welcome + morning_wish | `{{1}}` = name, `{{2}}` = who they're cared for/with |
| `ayana_medicine` | medicine, water, bp_check, sugar_check, health_check | `{{1}}` = name, `{{2}}` = medicine name |
| `ayana_meal` | breakfast, lunch, dinner, afternoon_checkin, tea_check, walk_check | `{{1}}` = name |
| `ayana_mood` | how_feeling, goodnight, love_note | `{{1}}` = name |
| `ayana_reengagement` | Silent-parent re-engagement | `{{1}}` = name |
| `ayana_report_ready` | Monthly report nudge | `{{1}}` = parent name |

Naming convention: `ayana_<category>_<lang>` (e.g. `ayana_opener_en`, `ayana_mood_te`, `ayana_medicine_hi`). English templates are registered as **`en`** (not `en_US`); the language code for every send is normalised through a single map in `whatsapp.py` so the welcome path and the daily path can never disagree.

**Delivery logic:** session closed → template (with quick-reply buttons); session open → free interactive buttons with rich rotating content.

---

## Pricing & Plans

> Pricing is **code-authoritative**: `backend/pricing.py` defines the values actually charged/quoted at runtime. If you change a price, change `backend/pricing.py` first, then this table and `frontend/src/lib/fallbackPlans.js`.

USD is the global anchor; INR is priced for India. Monthly or yearly (yearly ≈ 2 months free).

| Tier | Parents | Care circle | Check-ins | Medicine | Activities | Recovery | Price (USD / INR) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **Nitya** | 1 | Owner only | 3 | 3 | 1 | ❌ | $10 · ₹949 /mo |
| **Bandham** ⭐ | 2 | Owner only | 4 | 4 | 2 | ❌ | $19 · ₹1,799 /mo |
| **Raksha** | 2 | Owner + 2 siblings | 4 | 6 | 4 | ✅ 30 days | $29 · ₹2,750 /mo |

- Multi-currency: USD, GBP, EUR, AED, SGD, AUD, CAD, INR.
- Plan limits live once in `backend/pricing.py`, mirrored offline in `frontend/src/lib/fallbackPlans.js`.

---

## Plan Changes & Downgrade Protection

Plan switches go through `_validate_plan_transition()` in `server.py`, comparing current usage (parents, care-circle **siblings** + legacy members/invites, active recovery schedules, per-schedule counts) against the target plan's limits *before* the change is allowed.

- **Upgrade:** always allowed.
- **Downgrade that doesn't fit:** rejected with a structured `{message, blockers, usage}` response. The Plan tab opens a cleanup picker so the owner removes exactly what's blocking, then auto-retries the switch.
- **Phone integrity:** a parent's WhatsApp number can't collide with the owner's login number, another account's login number, or another parent record — enforced at signup, at parent create/update (`_assert_phone_role_available()`), and backstopped by a partial unique index in `schema.sql`.

---

## Data Retention

Defined in `schema.sql` as `purge_expired_data()`, scheduled nightly at 03:00 UTC via `pg_cron`:

- `message_logs` and `parent_replies` older than 6 months are deleted **only once** a `monthly_reports` row exists for that parent/period — raw history is never wiped before it's aggregated.
- Expired OTPs, invite tokens, JWT blacklist entries, and scheduler locks are cleaned in the same pass.
- **Never purged:** `emergency_events`, `distress_logs`, `moments`, `audit_logs`, `monthly_reports`.

---

## Database Schema Highlights

Core tables (see `schema.sql` + `migrations/`, all applied idempotently on startup):

- `users` — account owners and legacy household members
- `parents` — parent profiles, including `activity_window_start/end` and **`vacation_start` / `vacation_end`** (paused range, `YYYY-MM-DD`)
- `care_circle_siblings` — **phone + OTP** verified siblings (`owner_id, name, phone, language, relation, verified`); unique per `(owner_id, phone)`
- `circle_invites` — legacy email invites (kept for backward compatibility; UI now uses phone+OTP)
- `schedules`, `message_logs`, `parent_replies`, `emergency_events`, `distress_logs`, `monthly_reports`, `moments`, `payment_state`, `phone_otps`, `jwt_blacklist`, `scheduler_locks`, `audit_logs`

---

## File Map

```
backend/
  server.py                  — FastAPI app, all API routes, webhook handler
  models.py                  — Pydantic models (ParentInput incl. vacation fields, ScheduleInput, …)
  pricing.py                 — Nitya/Bandham/Raksha plans, limits, multi-currency pricing
  templates_data.py          — Message variants (7/slot), seasonal_greeting(), BUTTONS dict
  whatsapp.py                — WhatsApp Cloud API, 6 template families, lang-code map, welcome path,
                                retry + fallback, session mgmt, sibling welcome/notify
  scheduler.py               — APScheduler: delivery (1min), re-engagement (15min),
                                care-watch (5min), recovery-expiry (24h), monthly-report (24h);
                                skips sends during a parent's vacation range
  escalation.py              — Care Watch engine: 30-min retry, afternoon alert, birthday/festival
  distress_detection.py      — Two-layer keyword + Sarvam AI LLM classifier
  monthly_report.py          — Report generation, mood scoring, consume-once reply attribution
  medicine_sync.py           — Auto-syncs medicine reminder times into schedule
  translation_engine.py      — AI translation
  interactive_button_handler.py — Legacy button map; superseded by _apply_button_tap_effects() in server.py
  sarvam_stt.py              — Sarvam AI speech-to-text
  auth.py                    — Dual JWT, HttpOnly cookies, bcrypt, CSRF, token blacklisting
  database.py                — Supabase Postgres pool (asyncpg), JSONB codec
  schema.sql                 — Full Postgres schema, indexes, retention purge (pg_cron)
  migrations/                — Incremental migrations applied on top of schema.sql
  otp.py                     — SMS + on-screen OTP, bcrypt hashing, rate limiting
  email_sender.py            — Resend API (transactional; legacy Care Circle email invites)
  payments.py                — Stripe Checkout (one-time charge, see Known Limitations)
  rate_limit.py              — Redis sliding-window rate limiting
  storage.py                 — S3-compatible object storage

frontend/src/
  App.js                     — Route code-splitting, providers, suspense
  pages/
    Landing.js               — Marketing landing (EN/TE/HI)
    Login.js / Signup.js     — Auth (password fields have a show/hide toggle)
    ForgotPassword.jsx       — Phone-OTP password reset (show/hide toggle)
    Onboarding.js            — 4-step wizard: child → plan → parent → activate
    Activation.js            — WhatsApp intro + reply training
    Dashboard.js             — 7-tab command center (see Dashboard section)
    Admin.js / Legal.js
  components/
    PasswordField.jsx        — Reusable password input with eye toggle
    ParentCareForm.jsx       — Shared parent form
    ScheduleEditor.jsx       — Check-in category + time picker
    CareTab.jsx              — Moments, Vacation card, Recovery Mode, Emergency Contacts, Alerts
    PhoneInput.jsx           — Country-code phone input (used by sibling add)
    PricingCards.jsx, PhoneMockup.jsx, SecurityCards.jsx, Navbar.js, Footer.js
  context/  AuthContext.js (cookie auth, inactivity logout), LanguageContext.js (i18n)
  lib/      api.js (axios + CSRF + 401 auto-refresh), translations.js, fallbackPlans.js, …
```

---

## Dashboard (7 Tabs)

| Tab | What it does |
|---|---|
| **Parents** | List parents, inline schedule status, edit parent + schedule in one dialog, send test check-in, toggle active/pause, language-detection alert |
| **Check-ins** | Emergency banner, today's status grid per parent, 7-day history with reply viewer (consume-once attribution, 30 s auto-refresh) |
| **Reports** | Monthly mood graph (Bandham+), trend analysis, generate/regenerate, metrics grid |
| **Care Circle** | Add up to 2 siblings/cousins by WhatsApp number (OTP-verified), manage/remove members (Raksha) |
| **A Moment** | Send photos + notes to WhatsApp, **vacation/holiday mode**, recovery mode, emergency contacts (up to 5), alert history |
| **Plan** | Usage meter, upgrade/downgrade via Stripe Checkout with a cleanup picker for invalid downgrades |
| **Account** | Profile editing, change password (show/hide toggle), audit history, account deletion |

---

## Security

| Area | Implementation |
|---|---|
| **Authentication** | Dual JWT (access 30 min, refresh 7 day) in HttpOnly Secure SameSite cookies |
| **Token revocation** | JTI blacklist in Postgres (`jwt_blacklist`), checked on every authenticated request |
| **Password storage** | bcrypt (12 rounds); show/hide toggle on every password field in the UI |
| **CSRF** | Double-submit cookie pattern on all state-changing requests |
| **Rate limiting** | Redis sliding-window: OTP 5/15 min, login 10/15 min + lockout, API 100/min/IP |
| **OTP security** | bcrypt-hashed codes, 5-min expiry, max 3 attempts, atomic counter |
| **Image uploads** | HMAC-SHA256 signed URLs (1 h TTL), Pillow re-encode strips EXIF |
| **Webhook** | Verifies Meta `X-Hub-Signature-256`; always returns 200 to Meta; idempotent on `wam_id` |
| **Headers** | X-Frame-Options: DENY, X-Content-Type-Options: nosniff |
| **Scheduler locks** | Postgres row locks with TTL (`scheduler_locks`) — prevents duplicate sends across replicas |

---

## Environment Variables

Key variables (see `backend/.env.example` for the full list):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` (or `SUPABASE_DB_URL`) | — | Postgres connection string (Supabase pooler, port 6543) |
| `JWT_SECRET` | — | JWT signing secret (required — app refuses to start without it) |
| `WHATSAPP_ENABLED` | `false` | Master toggle for Meta WA sends |
| `META_WA_ACCESS_TOKEN` / `META_WA_PHONE_NUMBER_ID` | — | WhatsApp Cloud API creds |
| `META_WA_APP_SECRET` | — | Verifies inbound webhook signatures |
| `META_WA_VERIFY_TOKEN` | — | Meta webhook handshake token |
| `META_WA_GRAPH_VERSION` | `v22.0` | Graph API version |
| `OTP_MODE` | `sms` | `onscreen` returns dev OTP codes in the API response (sibling add, reset) |
| `FRONTEND_URL` / `BASE_URL` | — | CORS + deep-links / signed URL base |
| `REDIS_URL` | `redis://localhost:6379/0` | Rate limiting (optional) |
| `TWILIO_*` / `SMS_ENABLED` | — / `false` | Twilio SMS OTP |
| `STRIPE_API_KEY` / `STRIPE_WEBHOOK_SECRET` / `PAYMENTS_ENABLED` | — / — / `false` | Stripe |
| `RESEND_API_KEY` / `EMAIL_ENABLED` | — / `false` | Resend email |
| `SARVAM_API_KEY` / `DISTRESS_ML_ENABLED` | — / `false` | Sarvam AI STT + distress |
| `AUTO_MONTHLY_REPORTS` | `true` | Auto-generate reports on the 1st |
| `SCHEDULER_ENABLED` | `true` | Master toggle for APScheduler jobs |
| `SENTRY_DSN` | — | Error monitoring (no-ops if unset) |
| `DB_MIN_POOL_SIZE` / `DB_MAX_POOL_SIZE` | `10` / `20` | asyncpg pool sizing |

---

## Quick Start (Dev)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set JWT_SECRET and DATABASE_URL at minimum
# schema + migrations apply automatically on first startup
uvicorn server:app --reload --port 8001

# Frontend (uses yarn / craco — never npm)
cd frontend
yarn install
yarn start   # http://localhost:3000
```

Set `REACT_APP_BACKEND_URL=http://localhost:8001` in `frontend/.env`.

---

## Known Limitations

1. **Meta template approval required** — the 6 template families must be approved in Meta Business Manager before out-of-session messages send.
2. **Payments are a one-time charge per plan change, not a subscription** — `payments.py` uses Stripe Checkout in `mode="payment"`. No recurring subscription, proration, or billing-cycle adjustment. This is the true launch blocker for recurring SaaS; needs Stripe Subscriptions (price ID per plan, customer object, `invoice.paid` / `customer.subscription.updated` webhooks).
3. **Channel dependency** — one WhatsApp number / one Meta account. If Meta flags it, every customer goes dark at once. Add a backup number + quality-rating monitoring before scaling past the first ~50 paying users.
4. **Distress ML (Layer 2)** is off by default and beta — needs `SARVAM_API_KEY`, framed as assistive, never as emergency detection.
5. **Performance** — cross-region Railway↔Supabase latency; a region move (e.g. Singapore) and collapsing N+1 queries are pending.
6. **`server.py` is a large monolith** — a planned refactor into per-domain routers (not yet done; carries regression risk, so scheduled separately).

---

## Architecture

```
┌──────────────┐     HTTPS/API      ┌───────────────────────┐     WhatsApp     ┌──────────────┐
│   React SPA  │ ◄──────────────► │   FastAPI + Postgres   │ ◄────────────── │  Meta Cloud  │
│   (Vercel)   │    HttpOnly JWT    │  (Railway + Supabase)  │    Webhook       │     API      │
└──────────────┘                    └───────────────────────┘                   └──────────────┘
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                         APScheduler    Redis       Sarvam AI
                        (delivery,     (rate        (STT, LLM,
                         escalation,    limits)      translate)
                         reports)             +
                                        pg_cron nightly
                                        retention purge
```

---

*Built with 💛 by a developer whose parents are in Hyderabad.*
