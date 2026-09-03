# AYANA — WhatsApp Care Companion for Elderly Parents

**AYANA** is an automated, culturally warm care companion that sends daily check-ins to elderly Indian parents over WhatsApp — on behalf of their adult children living far away. Parents reply with **one tap** or a **voice note** in Telugu, Hindi, or English. Children get **instant updates** on their dashboard.

> 💛 No app to install. No typing needed. Just WhatsApp — the way your parents already chat.

**Live:** [ayanabott.com](https://www.ayanabott.com)

---

## Who It's For

| Role | Description |
|---|---|
| **Child (User)** | Adult children — especially NRIs in USA, UK, UAE, Singapore, Canada, Australia — who worry about aging parents back home |
| **Parent (Recipient)** | Elderly Indian parents (60-85+) comfortable with WhatsApp. They tap buttons or hold the mic. Zero learning curve. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11, FastAPI, MongoDB (Motor async), APScheduler |
| **Frontend** | React 19, Tailwind CSS, Radix UI, Recharts, Framer Motion, Three.js |
| **Messaging** | WhatsApp Cloud API (Meta), 6 approved message templates |
| **AI / ML** | Sarvam AI — STT (saarika:v2.5), LLM distress classifier (sarvam-105b), translation engine |
| **Auth** | Dual JWT (access 30min + refresh 7day), HttpOnly cookies, bcrypt, CSRF |
| **SMS OTP** | Twilio |
| **Payments** | Stripe Checkout |
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
- **Quiet hours (DND):** Manual or auto-learned from reply patterns — no messages during sleep/prayer

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
- **Layer 2 (AI Voice):** Sarvam-105b LLM analyzes voice transcripts for hidden distress even when parent says "I'm fine"
- Emergency events recorded + instant WhatsApp alerts to entire family

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

### 🏥 Surgery Recovery Mode (Raksha Plan)
- Enables 2-4 extra daily reminder slots for 30-90 days
- Auto-reverts and archives when period ends

### 📊 Monthly Reports & Mood Analytics
- Total touches, delivered vs. skipped, voice notes count
- Daily mood graph (Good=1.0, Okay=0.5, Not well=0.0)
- Trend analysis: first-half vs. second-half mood comparison
- WhatsApp nudge via `ayana_report_ready` template on 1st of each month

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

## Pricing Tiers

| Tier | Parents | Care Circle | Daily Touches | Recovery | Report | Price |
|---|:---:|:---:|:---:|:---:|:---:|---|
| **Nitya** | 1 | — | 4 (2+2) | ❌ | Basic | ₹149/mo · $10/mo |
| **Bandham** ⭐ | 2 | — | 6 (3+3) | ❌ | + Mood Graph | ₹299/mo · $19/mo |
| **Raksha** | 2 | 2 members | 8 (4+4) | ✅ 30-90 days | Full + Shared | ₹429/mo · $29/mo |

Multi-currency: USD, GBP, EUR, AED, SGD, AUD, CAD, INR

---

## File Map

```
backend/
  server.py                  — FastAPI app, all API routes, webhook handler (~2175 lines)
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
  translation_engine.py      — AI translation with MongoDB caching
  interactive_button_handler.py — Structured button tap router
  sarvam_stt.py              — Sarvam AI speech-to-text
  auth.py                    — Dual JWT, HttpOnly cookies, bcrypt, token blacklisting
  database.py                — MongoDB (Motor async) connection + indexes
  otp.py                     — Twilio SMS OTP, bcrypt hashing, rate limiting
  email_sender.py            — Resend API for Care Circle invites
  payments.py                — Stripe Checkout integration
  rate_limit.py              — Redis sliding-window rate limiting
  storage.py                 — S3-compatible object storage

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
    api.js                   — Axios with CSRF, 401 auto-refresh queue
    translations.js          — Full translation dictionary (EN/TE/HI)
    formHelpers.js           — cleanHabits(), cleanOptionalString() sanitizers
    fallbackPlans.js         — Client-side pricing tier mirror
    fallbackConfig.js        — Fallback data for languages, categories, medicines
```

---

## Dashboard (7 Tabs)

| Tab | What It Does |
|---|---|
| **Parents** | List parents, inline schedule status, edit parent+schedule in one dialog, send test check-in, toggle active/pause, language detection alert |
| **Check-ins** | Emergency alert banner, today's status grid per parent, 7-day history accordion with hidden-by-default reply viewer |
| **Reports** | Monthly mood graph (Bandham+), trend analysis, generate/regenerate, metrics grid |
| **Care Circle** | Invite siblings by email, manage members, cancel invites (Raksha plan) |
| **A Moment** | Send photos+notes to parent's WhatsApp, recovery mode, emergency contacts (up to 5), alert history with resolve/false-positive |
| **Plan** | Usage meter, upgrade/downgrade with Stripe |
| **Account** | Profile editing (name, city, timezone), audit history, account deletion |

---

## Security

| Area | Implementation |
|---|---|
| **Authentication** | Dual JWT (access 30min, refresh 7day) in HttpOnly Secure SameSite=Strict cookies |
| **Token revocation** | JTI-based blacklist in MongoDB with TTL auto-expiry |
| **Password storage** | bcrypt (12 rounds) |
| **CSRF** | Double-submit cookie pattern (skipped for Bearer auth) |
| **Rate limiting** | Redis sliding-window: OTP 5/15min, login 10/15min + lockout, API 100/min/IP |
| **OTP security** | bcrypt-hashed codes, 5-min expiry, max 3 attempts, atomic counter |
| **Image uploads** | HMAC-SHA256 signed URLs (1h TTL), Pillow re-encode strips EXIF |
| **Auto-logout** | 5-min inactivity + page refresh detection |
| **Headers** | X-Frame-Options: DENY, X-Content-Type-Options: nosniff, strict CSP |
| **Scheduler locks** | MongoDB atomic upsert with TTL — prevents duplicate sends across replicas |

---

## Environment Variables

See `backend/.env.example` for the full list. Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `MONGODB_URI` | — | MongoDB connection string |
| `JWT_SECRET` | — | Secret for JWT token signing |
| `WHATSAPP_ENABLED` | `false` | Master toggle for Meta WA sends |
| `META_WA_ACCESS_TOKEN` | — | WhatsApp Cloud API access token |
| `META_WA_PHONE_NUMBER_ID` | — | WhatsApp phone number ID |
| `FRONTEND_URL` | — | Frontend URL for CORS and report deep-links |
| `BASE_URL` | — | Backend public URL for signed image URLs |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for rate limiting |
| `TWILIO_ACCOUNT_SID` | — | Twilio SMS for OTP |
| `STRIPE_SECRET_KEY` | — | Stripe payments |
| `RESEND_API_KEY` | — | Resend email API |
| `SARVAM_API_KEY` | — | Sarvam AI (STT + translation + distress) |
| `DISTRESS_ML_ENABLED` | `false` | Enable AI voice distress classifier |
| `AUTO_MONTHLY_REPORTS` | `true` | Auto-generate reports on 1st of month |
| `PAYMENTS_ENABLED` | `false` | Enable Stripe payments |

---

## Quick Start (Dev)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in JWT_SECRET, MONGODB_URI at minimum
uvicorn server:app --reload --port 8000

# Frontend
cd frontend
npm install
npm start
# Opens http://localhost:3000
```

Set `REACT_APP_BACKEND_URL=http://localhost:8000` in `frontend/.env`.

---

## Known Limitations

1. **Meta template approval required** — 6 templates must be approved in Meta Business Manager before out-of-session messages send
2. **`ayana_meal` template says "Lunchtime!"** but is shared across breakfast/tea/walk categories — minor edge case when session is closed
3. **Distress ML (Layer 2)** is off by default (`DISTRESS_ML_ENABLED=false`) — needs Sarvam API key
4. **Payments** are off by default (`PAYMENTS_ENABLED=false`) — free trial mode during testing
5. **Backend tests** (`backend/tests/test_ayana_api.py`) need re-sync with current models

---

## Architecture

```
┌──────────────┐     HTTPS/API      ┌───────────────────┐     WhatsApp      ┌─────────────┐
│   React SPA  │ ◄──────────────► │   FastAPI + Mongo  │ ◄────────────── │  Meta Cloud  │
│   (Vercel)   │    HttpOnly JWT    │    (Railway)       │    Webhook       │     API      │
└──────────────┘                    └───────────────────┘                   └─────────────┘
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                         APScheduler    Redis       Sarvam AI
                        (delivery,    (rate        (STT, LLM,
                         escalation,   limits)      translate)
                         reports)
```

---

*Built with 💛 by a developer whose parents are in Hyderabad.*