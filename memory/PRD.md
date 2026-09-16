# AYANA — PRD & Working Notes

## Current task — founder review and production messaging incident diagnosis

**Scope:** Read-only review first, respecting the founder's request to discuss before making production changes. Latest user instruction: "Start the task now". The clarification tool was invoked but returned a pre-completion lint gate instead of user choices; do not treat it as approval for live writes.

### Original problem statement

> be carefull, my app is in production. Act as a CEO and give me a complete app review of my app vs my raw idea. And coming to child template, I used to get the replies but suddenly they were stopped.
>
> See, my main target is to help the user(children) who have settled abroad/outside of India. I personally saw many people abroad who won't call their parents, that means not intentionally but due to work stress, deadlines, meetings, etc. But on the other side, parents will wait all day just to talk with their children, think they did not get a call from their children on that day, the next day, and they feel alone and depressed. To solve all these, Ayana helps them, as the user (child) will signup/login and then set up the account by entering his/her details and verifying their mobile number with otp; then select the payment plan, and they will enter their parents' details, check-in time, daily routines, and medicines. Once they setup account from that day, as per the parents' location and time, we will send them WhatsApp messages; when they reply, the child will get notified that Amma/Dad replied. At least the parents will have satisfaction that their children are sending messages, as well children will be ok by seeing their message. Parents can easily handle it just by clicking the button or sending the voice note. Children can upgrade/downgrade according to the plan.
>
> Currently, I have these issues.
> I have issues.
> 1. My mom is getting messages; she was replying, but I have not been getting the replies since 4 days.
> 2. My dad is not even getting the messages at all. The first day he got messages, but my mom did not get them. Then I typed "hi" on her phone, and then she was continuously getting messages, but coming to my day, he got messages on the first day, and then the next day he did not reply, and after no replies, I could see a flooding of messages—the same messages again and again, no reply for those messages. Then I tried to fix that flooding message, and then the next day he was not even getting messages at all.
> 3. My friend was in the USA, and he tried to log in and verified his number and added parents. Parents are getting the replies but were not even getting the messages, not even welcome???. Check the template, because all over the world my clients are present, so
>
> Discuss before you start working. Act as a CTO and CEO of my company. See main I have most of the paid users outside India, so as the user/child signs up/login, doesn't matter the location they have to get the welcome message and seamless messages everyday from their parents

### Current architecture and safety decisions

- Actual stack: React 19/craco, FastAPI, asyncpg/Postgres (Supabase), APScheduler, direct Meta WhatsApp, Twilio OTP, Stripe, Sarvam voice, object storage. Preserve it; no migration to template-default MongoDB.
- Reviewed revision `2cf580a`; most recent messaging change `bb2f67b`.
- Both services were stopped initially. A final safety check found them unexpectedly running without a start command from this review; both were explicitly stopped again. Current `.env` files remained absent. No intentional customer sends, external app/database calls or migrations performed; do not equate supervisor RUNNING with successful live connectivity.
- Current `.env` files absent and production logs/Meta inventory unavailable. Historical live-credential/fix statements below are **not current proof**; several documented fixes are absent from current code.

### Completed in this phase

- Comprehensive product/CTO review: `memory/AYANA_REVIEW.md` with source references, incident hypotheses versus confirmed code defects, template audit, CEO recommendations, metrics and staged repair plan.
- Testing agent report `test_reports/iteration_18.json`: 14 source assertions / small offline simulations passed, confirming code defects. Not live E2E or complete function-execution regression.
- No runtime application fixes implemented. No current authentication credentials created; see `memory/test_credentials.md`.

### Prioritized backlog

- **P0:** ordinary child reply/voice notifications need session-aware approved-template routing plus durable recipient outcomes; recent child warning helpers do not cover ordinary replies.
- **P0:** reconcile legacy UI `/schedules` with granular scheduler tables without destructive overwrites; verify missing checked-in `medicines` table migration against live schema.
- **P0:** truthful per-recipient activation/welcome state and welcome idempotency; signup welcome currently no-op.
- **P0:** durable per-slot send identity, activation cutoff, safe catch-up, category-vs-slot retry correction, in-loop escalation caps, cross-worker safeguards; medicine identity and inappropriate tablet template mappings.
- **P1:** inbox/outbox recovery, all-recipient receipt tracking, shared vacation/pause/opt-out controls, child inbound handling, correct parent timezone, warnings based on actual delivery, complete care-circle recipients.
- **P1:** recurring billing/currency behavior and suspicious INR annual price; report/recovery scheduler wiring and report dependency; exact reply attribution.
- **P2:** baseline lint duplicates/bare excepts and stale docs; modularize only after stabilization.

### Next task

Discuss findings; request affected-account identifiers/timezones, whether replies are missing in dashboard too, actual Meta template category/approval/body/buttons, redacted error logs and current production revision. Seek approval for narrow local fixes before any customer-facing or production writes. Do not bulk replay missed historical messages. `backend/schema.sql` contains destructive DROP statements—never run against production.

---
## Historical notes below — retain for context, reverify before relying on them

## Changelog — 2026-06 (live-bug fixes from real WhatsApp screenshots)
Reported by user (Guna/Amma live run):
- **Flood of check-ins minutes after welcome** → FIXED in `scheduler.py` `_deliver_due_messages_impl`: added activation-day gate — slots whose scheduled parent-local time is before `activation_state.activated_at` are skipped (no backfill). Set up at 8 PM ⇒ only slots at/after 8 PM fire; earlier ones wait for their real time next day.
- **Reply mislabeled (lunch tap shown as "morning Wish check-in")** → FIXED in `server.py`: webhook now captures Meta `context.id` (the replied-to message's wam id) → threaded through `_record_reply` → `_notify_family`, which resolves the prompt from `message_logs.sid = context_id` instead of "latest log". Falls back to latest only if unmatched.
- **False "hasn't replied in 24h" alert within minutes** → FIXED in `escalation.py`: silence ping now requires `been_active_24h` (parent's first sent message ≥24h old) before firing.
- **Vacation UI "invisible"** → FIXED in `Dashboard.js`/`CareTab.jsx`: `VacationCard` moved out of the buried "A Moment" tab into a visible "Holiday / vacation mode" section on the **Parents** tab, plus a "🌴 On holiday until DD Mon" badge on each parent card.
- **Thumbs-up / tappable BUTTON on welcome (opener)** → RESOLVED IN CODE: no new template needed. The parent welcome already routes through the approved `ayana_opener` template (which carries Good/Okay/Not-well quick-reply buttons) via `send_welcome_for_new_parent`→`send_opener_welcome`. Removed the dead `_PARENT_WELCOME_TEXT`/`_CHILD_PARENT_SETUP_TEXT` free-text "reply 👍" constants (whatsapp.py) that the OLD deployed app was still sending. Also fixed button-title→intent matching (`server.py` `_GOOD/_OKAY/_BAD`, `whatsapp.py` FEELING_PATTERNS) to recognise the user's exact Meta titles (Telugu పరవాలేదు/బాగోలేదు, Hindi ठीक है/ठीक नहीं हूँ) — verified all 9 en/te/hi titles classify correctly. User must REDEPLOY (their live app is behind repo).

Env note: preview shares the LIVE Supabase DB and LIVE Meta WhatsApp — do NOT add parents / trigger sends during testing here. Messaging fixes verified by code review + parse/lint; full e2e needs user redeploy to Railway.


## Original problem statement (this session)
Bug-fix + hardening batch of 6 on the existing AYANA app (React + FastAPI + Supabase/Postgres, WhatsApp companion). Imported the real repo from GitHub (ayanabot05/ayana_whatsapp) into the Emergent workspace, then fixed 6 items, verified them together, and updated the README.

## Architecture
- Backend: FastAPI (`/app/backend/server.py` ~3.8k lines), asyncpg → Supabase Postgres, APScheduler, Meta WhatsApp Cloud API (`whatsapp.py`), pricing (`pricing.py`), scheduler (`scheduler.py`), OTP (`otp.py`).
- Frontend: React 19 + craco + Tailwind + Radix. Dashboard tabs in `pages/Dashboard.js`; `components/CareTab.jsx`.
- Auth: cookie-based dual JWT + CSRF double-submit. OTP_MODE=onscreen in this env (dev codes on screen).

## User personas
- Child (account owner, NRI) — manages parents, care circle, plans.
- Parent (elderly) — taps buttons / voice notes on WhatsApp.
- Sibling/cousin (care-circle, Raksha) — phone+OTP verified, receives forwarded replies.

## Batch of 6 — implemented & verified (session 2026-09-08)
1. **#2 Welcome path** — `send_welcome_for_new_parent()` now welcomes BOTH parent and child via the approved `ayana_opener` template (was plain `send_whatsapp` → rejected on cold numbers). `send_child_welcome()` gated to a no-op until first parent added.
2. **#2b Language code** — `TEMPLATE_LANG_CODE_MAP = {en:en, te:te, hi:hi}`; all template sends normalized centrally in `_send_content_template_once` (was en→en_US mismatch).
3. **#2c Button-tap title mapping** — webhook `_record_reply` falls back to matching localized button TITLE (Good/Taken + te/hi) via `_resolve_button_title_intent` when a template button id isn't structured.
4. **#13 Dashboard reply sync** — `checkins_summary` now attributes each reply to at most ONE message (consume-once), matching the monthly report.
5. **#11 Care-circle siblings** — replaced email invite with phone+OTP flow: `care_circle_siblings` table; `/circle/sibling/send-otp|verify`, `DELETE /circle/sibling/{id}`; max 2, Raksha-gated; siblings get the exact same forwarded reply+voice (`_notify_family`); counted in plan usage for downgrade protection; new CircleTab UI.
6. **#9 Vacation/holiday mode** — `parents.vacation_start/end` (text YYYY-MM-DD); scheduler skips delivery + re-engagement inside range and auto-resumes; `PUT /parents/{id}/vacation`; per-parent VacationCard in "A Moment" tab.
- Also: password show/hide toggle (`PasswordField.jsx`) on Login/Signup/ForgotPassword/Account; removed stray Vite `main.jsx` tag from `public/index.html`.

## Verification
- Backend: 25/25 checks (script, since removed) — all 6 confirmed.
- Frontend: testing_agent 6/6 passed (password toggles, sibling phone+OTP flow, vacation card).
- README updated (Postgres, phone+OTP care circle, vacation mode, welcome-via-template, pricing ₹949/₹1,799/₹2,750). `motor`/`pymongo` removed from requirements.txt.

## Env notes
- `backend/.env`: DATABASE_URL (Supabase), Meta WA creds LIVE (`WHATSAPP_ENABLED=true`), OTP_MODE=onscreen, JWT_SECRET, admin seed. Redis not configured (rate-limit degrades gracefully).
- Demo Raksha account: demo_raksha@ayana.care / DemoRaksha#2026 (has 1 parent). Admin: admin@ayana.care / AyanaAdmin#2026.

## Explicitly NOT in this batch (deferred)
server.py refactor (#3), test-data wipe (#4), Railway→Singapore (#1), landing copy (#12), reviews widget (#10), report-to-WhatsApp (#A), discounts (#B), email→WhatsApp sibling invites (superseded by phone+OTP), graceful token refresh (#8).

## Backlog / next
- P1: graceful token-refresh UX (#8).
- P1: sibling delete confirm prompt (testing agent note).
- P2: split Dashboard.js into per-tab component files.
