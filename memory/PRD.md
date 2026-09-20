# AYANA — PRD & Working Notes

## Implementation in progress — current status (2026-09-20)

User authorized the full eight-area repair and then comprehensive testing. Latest preference: keep sibling delivery shared with child delivery, avoid extra separate logic; welcome failures get bounded retries. User supplied a production PostgreSQL URL; it is NOT in repo or app `.env`, stored privately in `/root/ayana-private/database-url-pending.env` (0600). A trailing database-name period awaits clarification. Do not print the secret, connect, or apply production migrations without confirmation. The clarification tool returned lint/precompletion errors, not a human response.

- Implemented: exact-context shared timeline (`services/reply_linking.py`, `checkin_timeline.py`), exact button effects, selected parent-local date queries, unified CheckinsView and legacy Replies redirects, original audio player.
- Implemented: durable child/parent/sibling welcomes, existing shared ordinary reply/audio transport to users + siblings; contact-change recovery of recent eligible undelivered updates, removal cancellation/current membership checks, consent gate and known-failure bounded retries (uncertain sends not replayed).
- Implemented: shared four-section profile/medicine/activity/safety components, required cities/medicine metadata, stable medicine IDs, atomic care-plan endpoint reusing routes via request-local transaction, weekday/quotas/safety pause, independent overall schedule pause endpoint preserving recovery/vacation/profile state.
- Implemented: async receipt reconciliation, child service-window retry, independent audio/email statuses, voice retrieval recovery, night alerts independent of parent quiet hours, bounded shared nudges, recovery expiry/allowances, Supabase transaction-pooler-compatible scheduler locks.
- Implemented: checkout currency/coupon routing, credit SQL constraint/columns, valid subscription request counts, deduplicated ordered provider billing events, provider period access, future grant timing; removed unreachable old billing handler.
- Implemented: additive migration009, activation child-only WhatsApp backup, configured business phone instead of hardcoded number, explicit credentialed CORS including PATCH, operational retention moved off startup, disposable test data excluded from image.
- Independent test report `test_reports/iteration_3.json`: 17/20 backend tests passed, unified CheckinsView Jest test passed, frontend build passed. Main fixed the reported delivery compatibility/fallback issues and revised stale child-content test for durable request queue; local re-run 20/20 passed. Those latest repairs still require final independent verification. Additional `test_iteration24_acceptance_suite.py` exists but has not yet been independently reported; fixture lint fixed and scheduler clock fixture corrected. Do not claim 20 tests equal 20 fixed issues.
- Existing isolated test env: `/app/test_reports/test.env`, disposable PostgreSQL at local fixture (see `test_credentials.md`); no real provider calls. Latest user says finish all areas first, then one comprehensive test pass. Testing agent mandatory before marking final fixes verified.
- Deployment scan run once: compilation passed; production `.env`/URL/provider configuration still missing. Move boot TTL cleanup completed. Rejected unsafe advice to commit secrets or use wildcard credentialed CORS; `.gitignore` secret protections preserved. Must re-run readiness check after final repairs; cannot claim live ready without configuration.
- Remaining: comprehensive independent PostgreSQL/API + frontend component/browser tests across all eight areas, fix all findings, finalize template capability notices/operator checklist, final readiness recheck. Supplied inventory lacks proven dedicated activity approval; never substitute medicine wording. Live WhatsApp/Resend/storage/Razorpay behavior and actual Meta template inventory still unverified. No production data or customer messages modified.

---

## Latest confirmed scope — unified accurate Check-ins (2026-09-20)

**Still planning only. User explicitly requests one final updated plan before implementation.**

- User's highest priority: dad replied to reengagement and lunch; mobile and Replies show those correctly, but dashboard Check-ins falsely shows morning/medicine replied. This is not just a formatting complaint.
- Confirmed source cause to fix first: `routes/schedules.py:544–596` walks outbound logs chronologically and `_find_reply` consumes the first later same-day parent reply, ignoring `message_log_id` and `context_id`. Thus later lunch/reengagement responses can be consumed by earlier morning/medicine logs. Summary also counts `reply_status=done`; existing button effects can corrupt this independently.
- Separate timezone inconsistency: summary renders send time in parent's timezone (`schedules.py:585`), but `Dashboard.js:789` renders reply time using the child's browser timezone without a matching explicit timezone. Calendar default also uses child browser date; historical selection only filters already-fetched rolling data.
- New P0-0: canonical exact-event reply association for webhook, dashboard, WhatsApp labels, reports and medicine effects. Do not greedily pair by time/category. Contextless or historically ambiguous replies remain visible as general/unlinked messages, never false medicine adherence. Preserve multiple replies, explicit old-message replies and replies across midnight. Repair historical links only with provider context evidence, preserving an audit trail and original content/time.
- User explicitly wants ONE Check-ins area; remove separate Replies navigation/page experience, embed text/button/voice replies with separate Mom/Dad views and selected-date retrieval. Keep protected reply/audio APIs and legacy `/replies/:id` links as redirects, not broken/deleted data access. New generated WhatsApp/email links go to exact parent/date/reply in unified Check-ins; existing approved fixed URL buttons may need legacy redirect or Meta update, not arbitrary payload URL replacement.
- Voice requested directly in child WhatsApp AND dashboard. In open child session send original audio automatically. Closed session requires supplied `ayana_parent_voice_*` template and inbound 'Send voice note' quick reply before audio; URL click does not open the window. No claim of unconditional out-of-window raw audio. Existing handler in `notifications.record_recipient_inbound` already exists; harden rather than claiming nonexistent implementation based on pasted old notes.
- User explicitly approved daily split (Lunch in Daily check-ins, Afternoon rest in Activities), default editable water not consuming medicines, safety across plans. Exact numerical safety allowance/default water time not explicitly chosen; use conservative visible defaults, no price changes or silently dropped accepted schedules.
- Supplied expanded template definitions include `ayana_child_welcome_{en,te,hi}` (verified/consented account onboarding, once; one name variable; 'Enable updates'), `ayana_parent_reply_*` (4 variables name/check-in/reply/time; website + 'Send full reply'), `ayana_parent_voice_*` (3 variables name/check-in/time; website + 'Send voice note'), plus prior opener/meal/mood/medicine/reengagement/report and safety/warning definitions already in `docs/meta_approved_templates.txt`. Snapshot notes at `memory/TEMPLATE_CONTRACT_NOTES.md`.
- Missing external proof: actual template approval/category/URL-button configuration in Meta; complete activity template coverage (water/tea/walk/BP/sugar/health/rest) and suitably formatted expanded medicine content. Pasted source mixes 'approved' and 'ready to submit'. Do not assume all current template options are live approved. Sending a business template DOES NOT open recipient's 24h service window; correct pasted contradictory example.
- Additional affected files: `backend/monthly_report.py`; new canonical check-in timeline service and modular frontend Check-ins components; `frontend/src/App.js` for redirect compatibility; `notification_transport.py` for new links; `services/notifications.py` for canonical prompt/audio. `DailyTimeline.jsx` is presently a static illustrative schedule, NOT the actual dashboard CheckinsTab, so do not treat modifying it as fixing real tracking.
- First acceptance scenario: morning and medicine unanswered, lunch/reengagement answered; exactly correct two events show responses, medication remains unconfirmed, Mom unchanged, provider timestamps preserved with labeled parent-local display. Include two medicines same category, multiple replies, general voice, delayed context, duplicate receipts, US-date rollover, old deep links, and selected historical dates.

---

## Active request — coordinated repairs and four-section care setup (2026-09-20)

**Status: planning only; user explicitly requests file-by-file plan and priorities before application edits.** No new runtime code changes in this turn.

User now asks to fix the review findings comprehensively across backend/frontend/database/dashboard/WhatsApp. Primary paying persona is an overseas child with Indian parents. Additional incident: existing logged-in US child changed to an Indian number and still does not receive replies. Must support child/linked-sibling number changes, sibling addition/removal, welcome and future reply delivery consistently. Do not assume moving to +91 opens a WhatsApp service window or retries previously terminal failed notifications. Current number-change code already resolves some live recipient data, so diagnose remaining paths rather than replacing blindly.

### New explicit product requirements

- Child and parent city mandatory in onboarding.
- Exactly four care sections after parent profile: Daily check-ins; Daily activities; Medicines; new Safety checks.
- Clean duplicate meal/wake/sleep controls out of activities. Proposed check-ins: Morning, Breakfast, Lunch, Dinner, Good night, Love note. Proposed generic afternoon/rest moved to Activities; founder approval pending because user said "afternoon" in daily list.
- Activities: default water for every parent; tea/coffee; walk/jog; BP; sugar; general health; afternoon rest. Recommend editable/disable-able water time and no use of medicine quota; default time and safety quota still proposals, not user-confirmed.
- Medicine name + strength/dose/quantity + time + shape + color + instructions must persist through edits and be included in actual parent reminders. Stable medicine IDs; no duplicate slot counting or silent dropped medicines. Do not fabricate missing medical details or infer dosages.
- Safety checks: weekdays Mon–Sun, parent-local return time, place (work/office/job, market, shopping, temple/mosque/church, outing/return from trip). Send only on selected days; exact occurrence reply attribution, no uncontrolled nudges. User states approved templates exist; exact bodies/names/locale/category still need validation.
- Activation completion: remove "Open Amma/parent" links; retain only child-to-business "I'm ready" as optional backup. Display truthful separate parent/child welcome states and next scheduled sends.

### Proposed priority / file map

1. P0 source/schema prerequisites and durable recipient outcomes: additive `backend/migrations/009+`, `services/migrations.py`, `services/welcomes.py`, `services/notifications.py`, `notification_transport.py`, `inbox.py`, `routes/webhook.py`, `whatsapp.py`. Atomic claims, error-specific synchronous/asynchronous handling, per-contact versions and controlled recovery of eligible unsent notifications.
2. P0 contact/sibling sync: `routes/account.py`, `services/verification.py`, existing sibling handlers in `server.py` (NOT current `routes/care.py`, which owns readiness), shared recipient service if extracted, `PhoneChangeDialog.jsx`, `AuthContext.js`, account/circle sections of `Dashboard.js`. Preserve historical delivery destinations; no unbounded historical replay or recall of already submitted sends. Integration/auth playbooks required before writing these changes.
3. P0 unified care-plan persistence and medicines: `models.py`, `routes/parents.py`, `routes/schedules.py`, `medicine_sync.py`, `services/schedule_source.py`, `templates_data.py`, `scheduler.py`, shared transactional care-plan/medicine services if added. Frontend shared `ParentCareForm.jsx`, `ScheduleEditor.jsx` plus small Medicine/Activity/Safety editor components; both `Onboarding.js` and `Dashboard.js` use same payload/validation. Parent + medicine + schedules should save atomically, not two requests leaving half-saved state.
4. P1 (same agreed batch) section reclassification/safety weekdays/recovery/alerts: `pricing.py`, `templates_data.py`, `models.py`, `scheduler.py`, `escalation.py`, new safety route/service if appropriate, `CareTab.jsx`, fallbackConfig/Plans, schedule editors. Reconcile section budgets with global spacing/caps; prevent silent suppression and preserve paid entitlements.
5. P1 truthful activation/dashboard/replies: `routes/activation.py`, `routes/care.py`, `routes/replies.py`, `services/reply_media.py`, `services/delivery_stats.py`, `Activation.js`, `WhatsAppActivatePrompt.jsx`, `CareStatus.jsx`, `DailyTimeline.jsx`, `Replies.js`, `ReplyDetail.jsx`; query invalidation after saves/contact changes.
6. P1 complete billing repairs: `services/checkout.py`, `billing_access.py`, `subscription_gateway.py`, `routes/billing.py`, billing schema, `features/billing/{PlanPanel,CheckoutDialog,SubscribeDialog,SubscriptionStatus,BillingStatus}.jsx`, `PricingCards.jsx`. Currency, subscription API contract, event ordering/idempotency, authoritative periods, entitlement consistency; preserve legacy access and paid time.

### Constraints and release evidence

- Preserve existing Postgres/React/FastAPI app and production data. No destructive schema reset, fabricated cities/medicine details, unscheduled flood, or duplicate welcome as shortcut.
- Current application .env/production access absent. Before live verification need existing app configuration through secure settings, exact Meta approved template inventory and explicit permission for opted-in test recipients. Cannot guarantee provider delivery to blocked/unregistered numbers or override US Marketing-template restrictions.
- Required tests: real isolated Postgres plus mocked provider fault injection; international numbers/open-closed recipient windows; US→India and reverse number changes including pending/failed events and linked sibling identities; no sends to removed siblings; medicine edit at quota, two same-time meds, no changed adherence history; selected weekday safety scheduling; 22:00 child alerts; pause/vacation/expired recovery; billing stale/duplicate events; matching displayed and actual message content; desktop/mobile onboarding/dashboard.
- User-facing plan to be presented before edits; template contract, default-water timing and safety plan limits remain unconfirmed. Clarification tool attempted but returned lint engine error, not user decisions.

---

## Current task — 2026-09-20 read-only CTO functional review (supersedes historical status below)

User asked: "Now, based on my idea, go to my code and tell me where it is failing. Act as a CTO ... outside India numbers like the USA ... parents got all their welcome messages and daily check-ins, but he did not get the welcome message or replies ... Don't stick to my issues explained; explore ... code files." Follow-up: "Credits Recharged. Please Continue."

- Actual application baseline is `ef0b00d` in `/app/backend` and `/app/frontend`; `/app/ayana_repo` does not exist. React 19/FastAPI/PostgreSQL architecture preserved. Current `.env` files, preview URL, live credentials and production receipts unavailable.
- Completed read-only source/functional review; detailed source references, confidence labels, priorities and repair plan: `memory/CTO_REVIEW_CURRENT.md`. Historical review/implementation notes below are not current evidence or implementation permission.
- No application logic/auth/config/provider changes, migrations, customer messages, live payments or account creations. Added only notes and isolated tests. Initial clarification tool returned a lint-engine gate, not user choices.
- Testing: strict 17-test diagnostic run passed; `test_reports/iteration_2.json`, `backend/tests/test_iteration22_readonly_diagnostics.py`, test-only `_stubs/`. DB/provider boundaries MOCKED IN TESTS ONLY. Positive results reproduce defects/controls, not successful live delivery. Earlier iteration 1's 26 diagnostic/unit checks included weaker tests; do not aggregate or call them E2E. Frontend browser/real SQL/provider behavior untested.
- Confirmed current improvements: durable inbox/notification queue and child template/session routing, legacy schedule compatibility, activation cutoff/spacing, parent timezone default fixed, medicines migration now present. Do not repeat old blanket missing-template/schedule/timezone findings.
- **P0:** missing checked-in `users.needs_inbound_click` and billing credit migrations; unreachable child welcome recovery; async receipt vs parent claims/child retry divergence; 22:00 child alert blocked by parent quiet hours; wrong-slot button effects; medicine slot/send quota mismatch; dashboard subscription missing currency and invalid provider request contract; billing charge replay/stale transition behavior.
- **P1:** welcome race/uncertain resends and remaining reengagement duplicate paths; voice lookup failure classification; non-replayed button effects; recovery extra/expiry/pause validation; out-of-window health reminders blocked; scheduler ignores true entitlements; truthful per-recipient UI outcomes.
- **P2:** stale/refactor-test documentation, legacy test harness and duplicate code paths, automatic report wiring, shared household care-delivery ledger (parent received → parent replied → child received).
- Next: discuss findings and authorize narrow repairs. Production diagnosis requires deployed revision, redacted Meta receipts/template inventory and read-only schema comparison; no production credentials needed in the review report. Do not bulk replay missing messages or execute destructive `schema.sql`.
- No auth credentials created/modified. Current test-environment limitations documented in `memory/test_credentials.md`.

---

## Active follow-up — implementation approved, integration details pending

User confirmed parent replies ARE visible in the dashboard; overseas children, including the USA friend, miss WhatsApp reply notifications while their Indian parents receive messages. User states all pasted Meta templates approved. No ordinary parent-reply notification template appears in that list (only opener, mood/meal/medicine, reengagement, report-ready, safety returns, and silence warnings).

New explicit requirements: "Do it"; replace mobile OTP with email verification; Razorpay is ready; safe confirmed child WhatsApp-number changes must redirect future notifications to the new number with all records/flows synchronized; user requests file-by-file repair plan and candid completion estimate. Public site https://www.ayanabott.com/ fetched read-only. Current app roughly 70% of intended feature scope as an engineering estimate, NOT a measured reliability/delivery percentage.

- Plan communicated: child session-aware notification service/outcomes and email fallback; purpose-bound email OTP for signup/recovery/number change; remove mobile OTP across account and care-circle flows; atomic confirmed number changes; schedule/anti-flood repairs; truthful activation; Razorpay purchase/webhook lifecycle preserving existing paid access.
- Await essential choices/credentials: Resend API key + verified EMAIL_FROM; Razorpay key ID/secret/webhook secret and recurring-vs-prepaid product choice/international account capabilities; missing parent-reply/voice-update template approval or existing exact matching template details. `.env` files absent. No live services or new integrations started.
- Initial ask_human was blocked by 22 pre-existing lint errors rather than returning human choices. Do not interpret that tool response as user answers.
- Local baseline cleanup now authorized/performed: removed identical repeated import/helper block in `monthly_report.py`, replaced four bare except handlers with Exception; renamed local granular category set to avoid shadowing imported CHECKIN_CATEGORIES; removed identical duplicate delete_routine route in `server.py`. No messaging/payment behavior changed.
- Verified edited files parse and `ruff check ... --select F811,E722` passes. This is not verification of the pending notification/auth/payment repairs. No customer sends, charges or production migrations performed.
- Integration expert consulted for Resend and Razorpay. Resend existing HTTP adapter uses EMAIL_FROM; preserve its env convention. Razorpay returned a generic split-payment/Mongo example despite constraints: DO NOT implement unrelated transfers, trust client amounts, migrate DB or follow its npm instruction. Obtain corrected Orders/Subscriptions playbook before billing work.

---

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
