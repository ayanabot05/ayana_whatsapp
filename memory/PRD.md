# AYANA — Product Requirements Document

> Last refreshed 2026-09-05 (dashboard bug-fix sprint). Older history below.

## 2026-09-05 · Dashboard bug sprint (6 founder-reported bugs + extras)

**Root causes found & fixed**
1. **Plan limits not in sync / "We hit a snag" on Add parent** — Dashboard never read plan
   limits; `ParentDialog` had an infinite `useEffect` loop (`schedules=[]` default prop in
   deps → "Maximum update depth exceeded"). Now: `canAddParent` gating with upgrade CTA,
   `parent-limit-note`, real plan/status badge, per-tab `ErrorBoundary`, recovery/care-circle
   gating from `plan.limits`, optimistic plan update after checkout. Add-parent save is
   idempotent (remembers created parent id on schedule failure).
2. **WhatsApp replies never showed** — `parent_replies` table was EMPTY in prod: Meta sends
   `from=919…` (no `+`), lookup `phone = $1` missed → `parent_id NULL` → NOT NULL violation
   → webhook **500** on every real reply. Fixed with digits-only match
   (`_PARENT_BY_PHONE_SQL`), unknown numbers ignored (200), per-message try/except (always
   200 to Meta), startup backfill of orphan replies, dashboard polls every 30s + on focus.
3. **Photo Moment 501** — storage.py rewritten for **Supabase Storage** (private bucket
   `moments`, 7-day signed URLs Meta can fetch). Needs Railway env:
   `OBJECT_STORAGE_ENABLED=true`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
   Startup migration made `moment_images.moment_id` nullable.
4. **Monthly report** — `monthly_report.py` now stores `details` jsonb (per-day/per-category
   breakdown, feelings, medicine, emergencies, reply rate). New `MonthlyReportView.jsx`:
   header w/ logo, stat cards, mood graph (Bandham+), tables, **logo watermark**,
   **disclaimer footer**, **Download PDF** (print CSS). GET returns `{found:false}` not 404.
5. **Slowness** — Railway (Amsterdam) ↔ Supabase (Sydney) ≈ 280ms/RTT; every request did
   4–10 sequential RTTs; asyncpg ran a RESET query on every pool release (extra RTT each).
   Fixes: `reset=_noop_reset`, warm pool (min 10, 30-min idle), auth in 1 query, audit writes
   in background, `GET /api/dashboard/bootstrap` (1 call replaces ~10), parallel queries
   (`asyncio.gather`) in checkins/payment_state/circle/_plan_usage. Bootstrap 3.2s → 0.87s
   from preview pod; founder to move Railway → **Southeast Asia (Singapore)**.
6. **Navbar** — How it works · What parents see · Safety · Our promise · Pricing · FAQ (en/te/hi).

**Extras:** INR added as first currency (default when browser tz is Asia/Kolkata);
`SCHEDULER_ENABLED` flag (preview runs with scheduler off to avoid double sends);
`/api/health` reports webhook secret, storage, last inbound reply; `META_APP_SECRET`
accepted as alias; mobile tab strip scrolls; language-suggestion label humanised.

**Verified:** testing_agent iteration 13 (backend 10/10; frontend all flows green after
re-verifying plan-switch timing manually). Unit tests updated (pricing, storage, Dashboard,
CareTab).

**Founder actions for production (Railway env):** move region to Singapore; add
`OBJECT_STORAGE_ENABLED=true`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`; redeploy.

**Backlog after this sprint**
- Per-request user cache (saves 1 RTT/request) once profile-update invalidation is wired
- Move Supabase project to ap-south-1 (Mumbai) for India users (needs new project + restore)
- Async `/activation/activate` with status polling
- Stripe live mode (PAYMENTS_ENABLED) — plan-change UI already handles `checkout_url`
- `_apply_button_tap_effects` day_key uses UTC; use parent timezone
- Medicine reminder sync ignored a medicine with `time: 09:00` in test data — verify field name


## 2026-09-04 · Day 1 completion — Sentry monitoring + storage feature flag

**Day 1 fully closed.** Beyond the migration + auth + activation fixes
earlier today, added:

6. **Sentry error monitoring** — frontend (`@sentry/react`) + backend
   (`sentry-sdk[fastapi]`). Silent no-op without DSN so local/CI stays
   quiet. `ErrorBoundary` wraps the whole React app with a friendly
   "We hit a snag" fallback. `AuthContext.setSentryUser` tags every
   authenticated event with `{id, email}`; `get_current_user` does the
   same on the backend per-request. Both scrub cookies/CSRF/Authorization
   before send. Founder must set `REACT_APP_SENTRY_DSN` on Vercel and
   `SENTRY_DSN` on Railway; canary at `/api/debug/sentry-canary`
   (admin-only) fires an intentional error for verification.

7. **Deep `/api/health`** — returns 503 if either Postgres query fails
   OR Meta creds missing/disabled. Railway auto-rollback hook. Also
   surfaces the current release hash for correlating errors with
   deploys.

8. **Object storage feature flag** — `backend/storage.py` was calling
   Emergent's preview-only object store on every Railway startup,
   spamming Sentry with a 400 and breaking any moment-image upload
   with a 500. Now gated on `OBJECT_STORAGE_ENABLED=true` +
   `EMERGENT_LLM_KEY`. When disabled (production default): startup
   logs "Object storage disabled", `/moments/upload-image` returns a
   clean 501 with friendly copy ("Photo sharing temporarily
   unavailable — text moments still work"), `/uploads/signed/*`
   returns 404. Post-launch swap to Cloudinary or Supabase Storage by
   reimplementing the same 3 functions (is_enabled, put_object,
   get_object).

**All 8 fixes verified by testing_agent iterations 8-11 (100% pass on
functional flow; upload-image 501 pending deploy).**

## Day 2 plan (starts tomorrow)

- Invite 5–10 personal contacts as beta users
- `PAYMENTS_ENABLED=false` stays as-is
- Watch Sentry + Railway + Supabase logs live
- Track completion in a spreadsheet
- Gate D2: 5+ users completed activation, ≥3 parents replied, zero P0
  bugs, error rate <2%

## Post-launch backlog (surfaced during Day 1 audit)

- Split `server.py` (2,534 lines) into `routes/*.py` modules
- Split `Dashboard.js` (1,112 lines) by tab
- Remove `swr` OR `@tanstack/react-query` (both installed today)
- GitHub Actions CI (pytest + eslint + smoke test on Supabase branch DB)
- Backend test suite green (currently stale post-migration)
- Scheduler perf — index on `next_send_at`, dead-letter queue for Meta
  5xx, dedupe webhook by message_id
- Async activation with status polling (currently 16.5s synchronous)
- Real image storage (Cloudinary or Supabase Storage) so photo Moments
  work — remove the 501 gate
- Frontend gracefully handles 501 from `/moments/upload-image` with a
  friendly copy instead of a generic toast

## 2026-09-04 · Migration completion & pre-launch unblock

**Reported by founder:** "Since the Mongo→Supabase migration I cannot log in
or sign up. I want to make it live in 6 days."

**Root causes uncovered and fixed (in order of discovery):**

1. **Schema drift on 12 tables** — `schema.sql` was an early port; the
   codebase evolved past it. Fix shipped as
   `backend/migrations/002_schema_drift_fix.sql` (idempotent ALTER TABLE
   ADD COLUMN IF NOT EXISTS for `users.onboarding_step/phone_verified/…`,
   `circle_invites.owner_id/…`, `phone_otps.code_hash/verified/…`,
   `parents.detected_language/…`, `schedules.archived_recovery_messages`,
   `wa_sessions.last_inbound_at/session_open/…`, `message_logs.body/sid/…`,
   `parent_replies.user_id/raw_payload/ml_score/…`,
   `emergency_events.intent/keywords/resolved_by/…`,
   `moments.image_urls/status`, `moment_images.user_id/…`,
   `consent_logs.ip`). Ran once in Supabase — signup 500 gone.

2. **`users.timezone NOT NULL` conflict with the register INSERT** — the
   INSERT passes literal `null` for timezone which overrides the DB
   DEFAULT and hits the NOT NULL constraint. Fixed via
   `migrations/003_users_timezone_nullable.sql` — `ALTER TABLE users
   ALTER COLUMN timezone DROP NOT NULL`. Timezone is set later in
   onboarding Step 1 via `PUT /profile/child`.

3. **JSONB fields returning as raw JSON strings** — no codec on the
   asyncpg pool meant `parent["nicknames"]` came back as `"[\"Bangaram\"]"`
   instead of `["Bangaram"]`. `render_slot_body` crashed on
   `habits.get(...)` → `/activation/activate` returned 500. Fixed in
   `backend/database.py` — registered a jsonb/json codec with a
   forward-compatible encoder (pass-through for already-stringified
   values, `json.dumps` for raw dicts/lists) and `json.loads` decoder.
   One 40-line change fixed every JSONB read across every table.

4. **CSRF cookie invisible to frontend** — backend at
   `api.ayanabott.com` set `csrf_token` with `Domain=None` (scoped to
   api subdomain only). Frontend on `www.ayanabott.com` couldn't read
   it → `X-CSRF-Token` header missing → 403 on every mutating call →
   "Something went wrong" toast on plan selection. Fixed by setting
   Railway env `COOKIE_DOMAIN=.ayanabott.com` (no code change).

5. **Axios timeout too short for post-migration cold-pool latency** —
   `frontend/src/lib/api.js` had `timeout: 6000` while production
   latency for `/payment/checkout` is 7.4s, `/schedules` 6.7s,
   `/activation/activate` 16.5s. Axios aborted client-side,
   `error.response` was `undefined`, `formatApiError(undefined)`
   returned the generic "Something went wrong" toast — even though
   the server had already committed the change (WhatsApp actually
   sent). Fixed by (a) raising global timeout to 30s, (b) overriding
   to 60s per-request for `/activation/activate`, (c) adding
   `formatAxiosError()` that distinguishes timeout / network / server
   errors with actionable copy, (d) swapping all Onboarding.js
   catches to use it.

**Verified working (testing_agent iteration 8, full frontend E2E):**
- Register + login + `/auth/me`
- OTP send (returns `dev_code` when Twilio unset) + verify
- Onboarding Step 1 (child profile) + Step 2 (plan) + Step 3
  (parent + schedule) + Step 4 (activation → real Meta WhatsApp send)
- Dashboard renders parents with nicknames as human-readable arrays

**Follow-up items surfaced by testing_agent (not blocking launch):**
- Backend per-request latency 2.8–3.7s for trivial GETs, 7.4s for a
  payments-disabled checkout suggests per-request DB connection
  handshake OR Railway↔Supabase cross-region. Investigate.
- `/activation/activate` 16.5s should be made async with a status poll.
- INR should be pre-selected on the plan card when the child timezone is
  Asia/Kolkata (currently defaults to USD).
- Dashboard shows a bare spinner for 20-30s on initial load — needs
  skeleton loading state.
- `Onboarding.js::saveParentForm` isn't idempotent — if `/parents`
  succeeds but `/schedules` fails, the created parent stays and retries
  can hit the parent-limit. Refactor to keep the parent id and retry
  only the schedule.

## 6-day launch plan (agreed with founder)

- **Day 1 (done):** unblock signup/login/onboarding/activation
- **Day 2:** live beta with 5–10 real users (no payments, `PAYMENTS_ENABLED=false`)
- **Day 3:** fix D2 bugs + webhook idempotency + Sarvam STT fallback + Supabase backups
- **Day 4:** Twilio SMS OTP live + Stripe test mode
- **Day 5:** Stripe live-mode + full regression + real card charge
- **Day 6:** final audit + Sentry + support inbox + LAUNCH

## Original Problem Statement
A web-based family-care communication platform helping children living
away from parents stay emotionally connected via scheduled WhatsApp
check-ins, multilingual messaging (English/Telugu/Hindi), and trust-first
onboarding. Emotionally warm, privacy-first, timezone-safe.

## Architecture (as built, post-migration)
- Frontend: React 19 + Tailwind + shadcn/ui (Vercel · www.ayanabott.com)
- Backend: FastAPI (Railway · api.ayanabott.com) — modular files:
  server, auth, models, whatsapp, scheduler, templates_data, database,
  escalation, distress_detection, monthly_report, translation_engine
- DB: **Supabase Postgres via asyncpg** (motor/pymongo still in
  requirements.txt as dead deps — remove during Day 3 cleanup)
- Auth: dual JWT (30-min access + 7-day refresh) in HttpOnly cookies
  scoped to `.ayanabott.com`, CSRF double-submit
- WhatsApp: Meta Cloud API — **LIVE** (6 approved templates)
- Twilio SMS OTP: **not configured** — dev_code returned in response
  and displayed as a toast (works for beta, activate for Day 4)
- Payments: Stripe checkout — **DISABLED** (`PAYMENTS_ENABLED=false`)
- Scheduler jobs: delivery (1min), re-engagement (15min), care-watch
  (5min), recovery-expiry (24h), monthly-report (24h, gated)

## Pricing (current)
Nitya $10 / Bandham $19 / Raksha $29 — multi-currency (USD, GBP, EUR,
AED, SGD, AUD, CAD, INR). See `backend/pricing.py` for full limits.

---

## History (pre-2026-09-04 entries, unverified against current code)



## Pricing (current)
Nitya $10 / Bandham $19 / Raksha $29 — USD-first currency list, INR
removed. See `pricing.py` for full limits table.

## Implemented and in code today
- Auth, onboarding wizard, dashboard (parents/schedules/replies/activity/
  reports/circle/care/account tabs), admin, legal pages
- Personalization: nicknames, habits, stories, city, other_parent_name,
  birthday (Onboarding only — not yet editable in Dashboard for
  nicknames/habits/stories; city/other_parent_name/birthday were added to
  the Dashboard edit dialog in this pass)
- Two-layer distress detection: keyword (always on) + Sarvam AI advisory
  classifier on voice transcripts (off by default)
- Monthly reports with mood graph (Bandham/Raksha)
- Emergency contacts (separate from Care Circle, max 5, E.164-validated)
- Two-way moments (child → parent WhatsApp note/photo)
- Care Watch escalation engine: unanswered-message retries, afternoon
  no-reply warning, birthday + festival auto-wishes
- Recovery mode (Raksha): extra reminder slots, archived (not deleted) on
  expiry

## Known gaps as of this refresh
1. Never tested against real WhatsApp — Twilio creds unset, flag off
2. 9 of 15 Twilio template SIDs were undocumented in `.env.example`
   (fixed) and none are submitted for Meta approval yet
3. CareTab.jsx (emergency contacts/moments/recovery UI) never click-tested
4. Dashboard parent-edit dialog still can't set nicknames/habits/stories
   for an existing parent
5. `backend/tests/test_ayana_api.py` has stale assertions against old
   plan ids / relationship casing — needs a full re-sync pass
6. Distress ML Layer 2 never exercised with a real API key + transcript
7. Monthly report → WhatsApp push (vs. dashboard-only) still undecided

See `README.md` for the fuller breakdown and file map.

---

## History (pre-2026-08-11 entries, unverified against current code)

### Implemented (2026-07-08)
- Auth: register/login/me/logout, admin seeding, JWT bearer
- Onboarding 5-step wizard, parents/schedules CRUD, consent logs
- Payment state (trial/test flag), Activation + WhatsApp instructions
- Multilingual static templates, WhatsApp inbound webhook + emergency detection
- Legal pages
- Verified: 24/24 backend pytest + full frontend E2E (100%) — at the time

### Iteration 2 (2026-07-08)
- Country-code phone inputs, conversational templates, two-pack pricing
  (Basic/Care+, since replaced by Nitya/Bandham/Raksha)
- WhatsApp LIVE via Twilio sandbox (verified real delivery at the time —
  current `.env` shows Twilio creds now blank again, status unclear)

### Iteration 4 (2026-07-08)
- Instant reply notifications, send-test check-in, family co-care invite
- Multilingual 3D landing rewrite
- Next (as of that entry): WhatsApp interactive template buttons, Meta
  Cloud API vs Twilio pricing decision, Sarvam AI, rotate Twilio token