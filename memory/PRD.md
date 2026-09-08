# AYANA — PRD & Working Notes

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
