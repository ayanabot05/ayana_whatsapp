# AYANA — WhatsApp Care Companion for Elderly Parents

**AYANA** is an automated, culturally warm care companion that sends daily check-ins to elderly Indian parents over WhatsApp — on behalf of their adult children living far away. Parents reply with **one tap** or a **voice note** in Telugu, Hindi, or English. Children get **instant updates** on their dashboard.

> 💛 No app to install. No typing needed. Just WhatsApp — the way your parents already chat.

**Live:** [ayanabott.com](https://www.ayanabott.com)

---

## Who It's For

| Role | Description |
|---|---|
| **Child (Account owner)** | Adult children — especially NRIs in USA, UK, UAE, Singapore, Canada, Australia — who worry about aging parents back home. Each account has one owner, who can invite up to 2 siblings as care-circle members on the Raksha plan. |
| **Parent (Recipient)** | Elderly Indian parents (60-85+) comfortable with WhatsApp. They tap buttons or hold the mic. Zero learning curve. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11, FastAPI, PostgreSQL via Supabase (asyncpg, connection pooled), APScheduler |
| **Frontend** | React 19, Tailwind CSS, Radix UI, Recharts, Framer Motion, Three.js |
| **Messaging** | WhatsApp Cloud API (Meta), 6 approved message templates |
| **AI / ML** | Sarvam AI — STT (saarika:v2.5), LLM distress classifier (sarvam-105b), translation engine |
| **Auth** | Dual JWT (access 30min + refresh 7day), HttpOnly cookies, bcrypt, CSRF |
| **SMS OTP** | Twilio |
| **Payments** | Stripe Checkout — currently one-time charge per plan change, not a recurring subscription (see Known Limitations) |
| **Email** | Resend API |
| **Storage** | S3-compatible object storage (signed URLs) |
| **Rate Limiting** | Redis sliding-window |
| **Hosting** | Railway (backend), Vercel (frontend) |

---

## Complete Feature Set

### 🏠 Parent Profile & Personalization
- **Relationship model:** Mother / Father → maps to Amma / Nanna / Maa / Papa
- **Preferred name & nicknames:** Up to 3 daily-rotating nicknames (Bangaram, Buji, Chinni, etc.)
- **Birthday auto-wishes:** Culturally rich greetings on parent's birthday (MM-DD)
- **Festival auto-wishes:** New Year, Sankranti/Pongal, Independence Day, Holi, Diwali
- **Seasonal greetings:** Auto-adapts to winter/summer/monsoon/pleasant
- **Family stories:** Up to 5 rotating memories woven into messages
- **Other parent mention:** "Did Nanna have lunch too?"
- **Language auto-detection:** Detects if parent replies in a different script, suggests switching
- **Quiet hours (DND):** Manual activity window only (06:00–22:00 default) — auto-detection from reply patterns was removed; see `activity_window_start`/`end` on the parent record

### 📋 Daily Check-ins & Scheduling (14 Categories)
| Type | Categories |
|---|---|
| **Check-ins** | Morning wish, Breakfast, Lunch, Dinner, Afternoon check-in, Tea/Coffee, Walk, How are you feeling?, Goodnight, Love note |
| **Reminders** | Medicine, Water, BP check, Sugar check, Health check |

- **Rotational message variants:** Up to 7 hand-crafted variants per slot/category/language
- **Hybrid WhatsApp routing:** Meta templates outside 24h window → Free interactive buttons inside open session
- **Configurable re-engagement:** 1-24 hours (default 4h) silent ping

### 💊 Medicine Management
- Name, dosage, shape (6 types), color (11 colors), timing relative to food
- Custom reminder times (HH:MM) with visual pill cards
- Auto-syncs medicine times into schedule slots (`medicine_sync.py`)

### 🔔 Care Watch Escalation Engine
- Auto-retries unanswered messages every 30 min for up to 2 hours (4 attempts)
- Afternoon no-reply alert (2 PM local) → notifies child + Care Circle + emergency contacts
- Any reply instantly cancels all retries

### 🚨 Two-Layer Emergency & Distress Detection
- **Layer 1 (Keyword):** Multilingual word matching — help, fell, hospital, chest pain, etc. in EN/TE/HI + custom keywords
- **Layer 2 (AI Voice):** Sarvam-105b LLM analyzes voice transcripts for hidden distress even when parent says "I'm fine" — off by default (`DISTRESS_ML_ENABLED=false`), needs `SARVAM_API_KEY`
- Emergency events recorded + instant WhatsApp alerts to entire family, and never auto-purged (see Data Retention below)

### 🎤 Voice Note Handling
- Downloads from Meta Graph API
- Transcribes via Sarvam AI STT (saarika:v2.5) — supports te-IN, hi-IN, en-IN
- Routes transcript through distress detection pipeline
- Child gets notification: "🎤 Amma sent you a voice note"

### 📸 Two-Way Moments (Child → Parent)
- Send warm notes + up to 2 photos to parent's WhatsApp
- Client-side optimization (max 1200px, EXIF stripped)
- Uploaded to S3 with HMAC-SHA256 signed URLs
- Monthly quota governed by plan

### 👨‍👩‍👦 Care Circle (Raksha Plan)
- Invite up to 2 siblings/family members via email
- Signed 7-day JWT invite tokens
- Shared visibility of parent logs, replies, alerts
- Billing stays with owner
- Downgrading below current care-circle usage is blocked with a specific, actionable list of what to remove first (see Plan Changes & Downgrade Protection below)

### 🏥 Surgery Recovery Mode (Raksha Plan)
- Enables 2-4 extra daily reminder slots for 30-90 days
- Auto-reverts and archives when period ends

### 📊 Monthly Reports & Mood Analytics
- Total touches, delivered vs. skipped, voice notes count
- Daily mood graph (Good=1.0, Okay=0.5, Not well=0.0)
- Trend analysis: first-half vs. second-half mood comparison
- Auto-generated on the 1st of each month (`AUTO_MONTHLY_REPORTS=true` by default) and fed into the data retention purge (below)
- WhatsApp nudge via `ayana_report_ready` template

### 💬 What Happens When Parent Taps Each Button

| Context | Buttons | What Happens |
|---|---|---|
| **Mood / Morning** | Good 😊 / Okay 🙂 / Not well 😟 | Mood recorded, child notified instantly |
| **Medicine** | Taken ✅ / Not yet / Skipped | Tracked, retries stop on "Taken", logged in monthly report |
| **Meal** | Yes / Not Yet / Skip | Meal tracked, child notified |
| **Re-engagement** | I'm fine / Need help / Call me | Relief / Dashboard alert / Urgent notify to call |
| **Voice note** | Hold 🎤 mic | Transcribed → distress-checked → child gets "🎤 Amma sent a voice note" |

---

## 6 Meta-Approved WhatsApp Templates

| Template | Used For | Variables |
|---|---|---|
| `ayana_opener` (en/te/hi) | morning_wish | `{{1}}` = name, `{{2}}` = relation |
| `ayana_medicine` (en/te/hi) | medicine, water, bp_check, sugar_check, health_check | `{{1}}` = name, `{{2}}` = medicine name |
| `ayana_meal` (en/te/hi) | breakfast, lunch, dinner, afternoon_checkin, tea_check, walk_check | `{{1}}` = name |
| `ayana_mood` (en/te/hi) | how_feeling, goodnight, love_note | `{{1}}` = name |
| `ayana_reengagement` (en/te/hi) | Re-engagement (silent parent) | `{{1}}` = name |
| `ayana_report_ready` (en/te/hi) | Monthly report nudge | `{{1}}` = parent name |

**Delivery logic:** Session closed → Meta template (costs per message). Session open (parent replied within 24h) → Free interactive quick-reply buttons with rich rotating content.

---

## Pricing & Plans

> ⚠️ **Not yet finalized.** `backend/pricing.py` (the values actually charged/quoted at runtime) currently defines ₹949 / ₹1,799 / ₹2,750 per month. The table below uses those code-authoritative numbers. A lower INR set (₹749 / ₹1,499 / ₹1,999) was also under consideration for better India price-anchoring — whichever is decided, update `backend/pricing.py` first and this table second, since the code is the source of truth for what's actually charged.

USD prices are the global anchor; INR is priced for the Indian market. All plans are monthly or yearly (yearly ≈ 2 months free).

| Tier | Parents | Household | Check-ins | Medicine | Activities | Recovery | Price (USD / INR) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **Nitya** | 1 | Owner only | 3 | 3 | 1 | ❌ | $10 · ₹949 /mo |
| **Bandham** ⭐ | 2 | Owner only | 4 | 4 | 2 | ❌ | $19 · ₹1,799 /mo |
| **Raksha** | 2 | Owner + 2 siblings | 4 | 6 | 4 | ✅ 30 days | $29 · ₹2,750 /mo |

- **Check-ins** — morning, meals, afternoon, goodnight, love note.
- **Medicine reminders** — medicine, BP, sugar, general health.
- **Daily activities** — walk, tea/coffee, water, "how are you feeling?".
- Multi-currency: USD, GBP, EUR, AED, SGD, AUD, CAD, INR.
- Plan limits are defined once in `backend/pricing.py` and mirrored for offline use in `frontend/src/lib/fallbackPlans.js` — if you change one, change both.

---

## Plan Changes & Downgrade Protection

Switching plans goes through `_validate_plan_transition()` in `server.py`, which compares current usage (parents, care-circle members/invites, active recovery schedules, per-schedule check-in/reminder counts) against the target plan's limits *before* the change is allowed.

- **Upgrade:** always allowed.
- **Downgrade that doesn't fit:** rejected with a structured `{message, blockers, usage}` response. The Dashboard's Plan tab catches this and opens a cleanup picker — real parents and care-circle members/invites are listed with checkboxes, so the owner can remove exactly what's blocking the change in one flow, which then automatically retries the plan switch. Blockers that need editing rather than deleting (an active recovery mode, a schedule with too many daily messages) are shown as plain instructions pointing at the tab that handles them.
- **Phone number integrity:** a parent's WhatsApp number can't collide with the account owner's own login number, another registered account's login number, or another parent record anywhere on the platform — enforced at signup (`register()`), at parent create/update (`_assert_phone_role_available()`), and backstopped at the database level by a partial unique index (`idx_parents_phone_unique` in `schema.sql`) so a race between two simultaneous requests can't create a silent duplicate.

---

## Data Retention

Defined in `schema.sql` as `purge_expired_data()`, scheduled nightly at 03:00 UTC via `pg_cron`:

- `message_logs` and `parent_replies` older than 6 months are deleted **only once** a `monthly_reports` row exists for that parent/period — so raw chat history is never wiped before it's been aggregated into a report.
- Expired OTPs, invite tokens, JWT blacklist entries, and scheduler locks are cleaned up in the same pass.
- **Never purged:** `emergency_events`, `distress_logs`, `moments`, `audit_logs`, and `monthly_reports` themselves — kept indefinitely.
- Reports are generated automatically by `scheduler.py`'s `_run_monthly_reports` job (daily check, only fires on the 1st of the month, gated by `AUTO_MONTHLY_REPORTS`), so the report → purge sequence runs end-to-end without manual intervention.

---

## File Map

\`\`\`
backend/
  server.py                  — FastAPI app, all API routes, webhook handler (~3070 lines)
  models.py                  — Pydantic models (ParentInput, ScheduleInput, etc.)
  pricing.py                 — Nitya/Bandham/Raksha plans, limits, multi-currency pricing
  templates_data.py          — Message variants (7 per slot), seasonal_greeting(), BUTTONS dict
  whatsapp.py                — WhatsApp Cloud API, 6 template names, retry+fallback, session mgmt
  scheduler.py               — APScheduler: delivery (1min), re-engagement (15min),
                                care-watch (5min), recovery-expiry (24h), monthly-report (24h)
  escalation.py              — Care Watch engine: 30-min retry, afternoon alert, birthday/festival
  distress_detection.py      — Two-layer: keyword matching + Sarvam AI LLM classifier
  monthly_report.py          — Report generation, mood scoring, trend analysis
  medicine_sync.py           — Auto-syncs medicine reminder times into schedule
  translation_engine.py      — AI translation
  interactive_button_handler.py — Legacy button-tap map; superseded by _apply_button_tap_effects() in server.py (kept for reference — see comment in server.py on why the old handler's payload ids never matched real templates)
  sarvam_stt.py               — Sarvam AI speech-to-text
  auth.py                    — Dual JWT, HttpOnly cookies, bcrypt, token blacklisting
  database.py                — Supabase Postgres connection pool (asyncpg), JSONB codec
  schema.sql                 — Full Postgres schema, indexes, retention purge job (pg_cron)
  migrations/                — Incremental schema migrations applied on top of schema.sql
  otp.py                     — Twilio SMS OTP, bcrypt hashing, rate limiting
  email_sender.py             — Resend API for Care Circle invites
  payments.py                — Stripe Checkout integration (one-time charge, see Known Limitations)
  rate_limit.py               — Redis sliding-window rate limiting
  storage.py                  — S3-compatible object storage
  tests/                      — pytest suite covering auth, circle/invite flows, emergency events,
                                moments, payments webhook, distress detection, medicine sync, and
                                multiple end-to-end onboarding/care-circle flows

frontend/src/
  App.js                     — Route code-splitting, providers, suspense
  pages/
    Landing.js               — Marketing landing page (multilingual EN/TE/HI)
    Login.js                 — Split-screen login
    Signup.js                — Registration with invite auto-linking
    Onboarding.js            — 4-step wizard: child details → plan → parent setup → activate
    Activation.js            — Post-onboarding WhatsApp intro + reply training
    Dashboard.js             — 7-tab command center (Parents, Check-ins, Reports,
                                Care Circle, A Moment, Plan, Account)
    Admin.js                 — Platform metrics + data tables (admin only)
    Legal.js                 — Privacy, Terms, Disclaimer, Data Deletion
  components/
    ParentCareForm.jsx       — Shared parent form (details, nicknames, birthday, stories,
                                habits, DND, medicines, schedule) — used by both Onboarding & Dashboard
    ScheduleEditor.jsx       — Check-in category + time picker
    CareTab.jsx              — Moments (photos), Recovery Mode, Emergency Contacts, Alert History
    PricingCards.jsx          — Plan selector with currency & billing toggle
    PhoneMockup.jsx          — Animated WhatsApp conversation preview
    InteractivePhoneDemo.jsx — Interactive WhatsApp simulation
    Navbar.js, Footer.js     — Shared navigation and footer
  context/
    AuthContext.js           — Auth state, HttpOnly cookies, 5-min inactivity auto-logout
    LanguageContext.js       — Global i18n (en/te/hi) with localStorage sync
  lib/
    api.js                   — Axios with CSRF, 401 auto-refresh queue, downgrade-blocker error formatting
    translations.js          — Full translation dictionary (EN/TE/HI)
    formHelpers.js           — cleanHabits(), cleanOptionalString() sanitizers
    fallbackPlans.js         — Client-side pricing tier mirror
    fallbackConfig.js        — Fallback data for languages, categories, medicines
\`\`\`

---

## Dashboard (7 Tabs)

| Tab | What It Does |
|---|---|
| **Parents** | List parents, inline schedule status, edit parent+schedule in one dialog, send test check-in, toggle active/pause, language detection alert |
| **Check-ins** | Emergency alert banner, today's status grid per parent, 7-day history accordion with hidden-by-default reply viewer |
| **Reports** | Monthly mood graph (Bandham+), trend analysis, generate/regenerate, metrics grid |
| **Care Circle** | Invite siblings by email, manage members, cancel invites (Raksha plan) |
| **A Moment** | Send photos+notes to parent's WhatsApp, recovery mode, emergency contacts (up to 5), alert history with resolve/false-positive |
| **Plan** | Usage meter, upgrade/downgrade via Stripe Checkout, with a cleanup picker that blocks and guides invalid downgrades (see Plan Changes & Downgrade Protection) |
| **Account** | Profile editing (name, city, timezone), audit history, account deletion |

---

## Security

| Area | Implementation |
|---|---|
| **Authentication** | Dual JWT (access 30min, refresh 7day) in HttpOnly Secure SameSite=Strict cookies |
| **Token revocation** | JTI-based blacklist in Postgres (`jwt_blacklist` table), checked on every authenticated request |
| **Password storage** | bcrypt (12 rounds) |
| **CSRF** | Double-submit cookie pattern (skipped for Bearer auth) |
| **Rate limiting** | Redis sliding-window: OTP 5/15min, login 10/15min + lockout, API 100/min/IP |
| **OTP security** | bcrypt-hashed codes, 5-min expiry, max 3 attempts, atomic counter |
| **Image uploads** | HMAC-SHA256 signed URLs (1h TTL), Pillow re-encode strips EXIF |
| **Auto-logout** | 5-min inactivity + page refresh detection |
| **Headers** | X-Frame-Options: DENY, X-Content-Type-Options: nosniff, strict CSP |
| **Scheduler locks** | Postgres row-based locks with TTL (`scheduler_locks` table) — prevents duplicate sends across replicas |
| **Phone uniqueness** | Application-level checks plus a database-level partial unique index — see Plan Changes & Downgrade Protection above |

---

## Environment Variables

See `backend/.env.example` for the full list. Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `SUPABASE_DB_URL` (or `DATABASE_URL`) | — | Postgres connection string (Supabase pooler, transaction mode, port 6543) |
| `JWT_SECRET` | — | Secret for JWT token signing (required — app refuses to start without it) |
| `WHATSAPP_ENABLED` | `false` | Master toggle for Meta WA sends |
| `META_WA_ACCESS_TOKEN` | — | WhatsApp Cloud API access token |
| `META_WA_PHONE_NUMBER_ID` | — | WhatsApp phone number ID |
| `META_WA_APP_SECRET` | — | Verifies inbound webhook signatures (`X-Hub-Signature-256`) |
| `META_WA_VERIFY_TOKEN` | — | Meta webhook handshake verification token |
| `FRONTEND_URL` | — | Frontend URL for CORS and report/invite deep-links |
| `BASE_URL` | — | Backend public URL for signed image URLs |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for rate limiting |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_SMS_FROM` | — | Twilio SMS for OTP |
| `SMS_ENABLED` | `false` | Master toggle for Twilio OTP sends |
| `STRIPE_API_KEY` | — | Stripe payments |
| `STRIPE_WEBHOOK_SECRET` | — | Verifies Stripe webhook signatures |
| `RESEND_API_KEY` | — | Resend email API |
| `EMAIL_ENABLED` | `false` | Master toggle for Resend email sends |
| `SARVAM_API_KEY` | — | Sarvam AI (STT + translation + distress) |
| `DISTRESS_ML_ENABLED` | `false` | Enable AI voice distress classifier |
| `AUTO_MONTHLY_REPORTS` | `true` | Auto-generate reports on 1st of month |
| `PAYMENTS_ENABLED` | `false` | Enable Stripe payments (currently one-time checkout, not a subscription — see Known Limitations) |
| `SCHEDULER_ENABLED` | `true` | Master toggle for the APScheduler jobs (delivery, escalation, reports) |
| `SENTRY_DSN` | — | Error monitoring; no-ops if unset |
| `DB_MIN_POOL_SIZE` / `DB_MAX_POOL_SIZE` | `10` / `20` | asyncpg connection pool sizing |

---

## Quick Start (Dev)

\`\`\`bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in JWT_SECRET, SUPABASE_DB_URL at minimum
# Apply schema.sql to your Supabase Postgres instance before first run:
#   psql "$SUPABASE_DB_URL" -f schema.sql
uvicorn server:app --reload --port 8000

# Frontend
cd frontend
npm install
npm start
# Opens http://localhost:3000
\`\`\`

Set `REACT_APP_BACKEND_URL=http://localhost:8000` in `frontend/.env`.

---

## Known Limitations

1. **Meta template approval required** — 6 templates must be approved in Meta Business Manager before out-of-session messages send.
2. **Payments are a one-time charge per plan change, not a subscription** — `payments.py` uses Stripe Checkout in `mode="payment"`. There's no recurring Stripe Subscription object, no proration, and no automatic "next month's invoice reflects the new plan" behavior. A live downgrade or upgrade today would prompt an immediate one-off charge, not a billing-cycle adjustment. Needed before charging real subscriptions: Stripe Subscriptions with a price ID per plan, a customer object, and webhook handling for `invoice.paid` / `customer.subscription.updated`.
3. **Distress ML (Layer 2)** is off by default (`DISTRESS_ML_ENABLED=false`) — needs a `SARVAM_API_KEY`.
4. **Payments are off entirely by default** (`PAYMENTS_ENABLED=false`) — free/trial mode during testing; plan changes apply instantly with no charge.
5. **Leftover MongoDB dependencies** — `motor` and `pymongo` are still listed in `requirements.txt` from the pre-migration codebase even though nothing in the app imports them anymore (all data access goes through `asyncpg`/Supabase). Safe to remove once confirmed unused.
6. **Pricing not finalized** — see the note under Pricing & Plans above; the INR figures need a final decision before launch.

---

## Architecture

\`\`\`
┌──────────────┐     HTTPS/API      ┌───────────────────────┐     WhatsApp      ┌─────────────┐
│   React SPA  │ ◄──────────────► │   FastAPI + Postgres   │ ◄────────────── │  Meta Cloud  │
│   (Vercel)   │    HttpOnly JWT    │   (Railway + Supabase)  │    Webhook       │     API      │
└──────────────┘                    └───────────────────────┘                   └─────────────┘
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                         APScheduler    Redis       Sarvam AI
                        (delivery,    (rate        (STT, LLM,
                         escalation,   limits)      translate)
                         reports)             +
                                        pg_cron nightly
                                        retention purge
\`\`\`

---

*Built with 💛 by a developer whose parents are in Hyderabad.*