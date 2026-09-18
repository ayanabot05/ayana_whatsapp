# AYANA — CEO/CTO product review and messaging incident diagnosis

## Scope and evidence limits

Reviewed repository revision `2cf580a` and the recent messaging changes, including `bb2f67b`, against the founder's intended customer journey. This is a **read-only application review**, not a completed production repair, security audit, or live end-to-end certification.

- No application logic, customer records, credentials, production configuration, or messaging templates were changed by this review. No messages, OTPs, payments, account creations, or database migrations were triggered.
- Frontend and backend were stopped at initial inspection. At the final safety check they were unexpectedly running, despite no start command from this review. Both were explicitly stopped again to restore the initial state. Configuration files remained absent; do not infer live service access from local supervisor status.
- Current workspace `.env` files are absent; production database access, operational logs, deployed revision, and Meta template approval/category data were unavailable. Old PRD statements about live credentials and past fixes are historical, not current evidence.
- Initial local backend logs contained startup/shutdown only, not the family's production incident.
- Testing agent produced 14 passing offline diagnostic checks in `test_reports/iteration_18_diagnostic_test.py`. These are **source assertions and small logic simulations**, not execution of the complete application or live delivery. Passing means the checks confirmed the described defects, not that AYANA's messaging works.
- The test agent did not change application files. Existing workspace differences in test URLs, old reports, lockfile and environment tooling were observed, not used as evidence of production changes.

## Executive judgment

The problem is real and the product direction is coherent: help families stay connected when adult children live far away, without requiring older parents to learn another app. WhatsApp, local-language buttons, familiar names and voice notes fit that need.

The current repository has substantial feature coverage but a broken core chain: **configured care → scheduled parent delivery → recorded reply → delivered child update**. Paid customers buy reassurance, not a count of attempted messages. False "active" or "sent" states and missing notifications undermine the entire value proposition.

Recommendation: prioritize reliability and truthful status before adding features or increasing acquisition. The missing-child-reply problem needs its own fix; changing only silence-warning templates does not fix normal reply forwarding.

## Founder vision versus current implementation

| Founder promise | Repository evidence | Assessment |
|---|---|---|
| Overseas child signs up and verifies a number | Signup and OTP flows and international phone normalization exist; country-specific delivery was not tested | Foundation present, global receipt unverified |
| Child receives a welcome | `send_child_welcome()` explicitly returns skipped; later parent-add and activation reuse the parent opener | Does not meet welcome-after-verification expectation |
| Child selects a paid plan | Pricing/limits and checkout exist | Checkout is one-time USD, not recurring multi-currency subscriptions |
| Parent schedules/routines/medicines are honored | UI writes legacy `schedules`; worker reads separate granular tables | Critical integration gap |
| Send according to parent's location/time | Worker uses parent timezone; new parent form defaults to browser timezone | Overseas child can accidentally schedule an Indian parent in the wrong timezone |
| Send every day even if parent did not reply | Normal sender has template routing outside parent session | Correct concept, but depends on approved templates, valid schedules and safe retries |
| Child immediately learns of every parent reply | Parent reply saved, then text/audio sent directly to family | No out-of-window template route for ordinary child notifications |
| Easy buttons and voice notes | Both parsers and voice/transcription paths exist | Useful foundation; voice forwarding shares child window problem |
| Parent can pause/unsubscribe without confusion | Dashboard pause modifies legacy schedule; holiday applies only to normal delivery | Inconsistent across workers; parent-side opt-out handling not found in reviewed inbound path |
| Upgrades/downgrades reflect plan | Transition validation exists | Scheduling limits and billing lifecycle need alignment |
| Dashboard provides peace of mind | Reply history and delivery metrics exist | Unconditional activation success and missing child delivery records create false reassurance |

## The three reported incidents

### 1. Amma receives and replies; child stopped receiving updates

**Confirmed code defect:** `server.py:2875–2973` `_notify_family()` sends regular text/button updates with `send_whatsapp()`. Its voice branch sends standalone audio and plain text. It does not route through an approved child-reply template or check the child's WhatsApp session. Send results are discarded rather than persisted per recipient for retry.

The recently added `ayana_first_warn_child_*` and `ayana_main_warn_child_*` functions are used by silence escalation, not by normal parent-reply forwarding. A warning-template fix therefore leaves normal updates broken.

**Strong incident hypothesis, not proven production RCA:** the child's 24-hour service window expired. The parent's reply reopens the parent's window only; it does not reopen the child's window. This fits "used to work, then stopped" without any change in Amma's behavior.

**Evidence needed:** one recent Amma inbound WhatsApp message ID and timestamp, corresponding `parent_replies` row, and the outbound child message's API response / delivery webhook error. If replies also disappear from the app, investigate inbound webhook/DB processing as well—not just outbound templates.

### 2. Dad received initially, then bursts, then nothing

There are several separate failure mechanisms; a single definitive cause cannot be assigned without his records.

1. **Schedules split:** new setup and edits can never reach the worker's source tables (details below).
2. **Open versus closed session:** typing "hi" permits free-form parent messages for 24 hours. A parent who never replies needs valid templates; no-reply is not a reason to permanently suppress scheduled care.
3. **Catch-up bursts:** the worker treats every earlier same-day slot as due; there is no activation-day cutoff in current code despite a historical PRD claiming one.
4. **Escalation bursts:** the three-per-day retry cap is checked once before the loop, not after each send. More than three due logs can be resent in one run.
5. **Overbroad suppression:** failed attempts consume the daily total, and failures of one category block later times of that same category for the day.
6. **First-warning parent nudge remains plain text:** a template helper exists but is not called by the escalation path.

The current daily counters reset by day. They alone do **not** prove why Dad stopped for multiple days. Check whether schedules are empty, the medicines table is missing, templates fail on every day, jobs error, or receipt statuses consume the retry budgets.

### 3. USA friend completed setup but welcome/delivery is missing

**Confirmed:** signup welcome is intentionally skipped; activation reports success even on failed sends; UI scheduling and worker scheduling disagree; parent timezone inherits the browser unless changed.

**Conditional country-specific risk:** Meta currently pauses Marketing-template delivery to US recipients. A template named "opener" or a local file marked "Utility" is not proof that Meta has approved it as Utility. Actual category, language, approval and quality status must be checked. This restriction is not a blanket block on every `+1` number or all transactional WhatsApp messages; Canada also uses `+1`.

The friend's wording is ambiguous about whether the child, the parents, or both missed messages. Confirm recipient(s) before attributing all missing messages to US policy. SMS OTP success does not establish WhatsApp deliverability or open a WhatsApp service window.

## Technical findings and prioritized repairs

### P0 — restore the paid core experience

**F01 — Normal child notifications cannot reliably cross the service window.**
- Evidence: `server.py:2875–2973`, `whatsapp.py:116–141,511–529`; child/non-parent inbound ignored at `server.py:3154–3156`.
- Repair: track recipient sessions independently (owner, siblings and parents); send approved event-specific Utility notifications when eligible outside the window, free-form within it. Voice should remain accessible through an authenticated app view or supported approved template interaction; don't assume standalone audio works outside the window. Persist notification event, recipient, message ID and outcome with idempotency.

**F02 — Setup, pause and worker have different schedule sources.**
- Evidence: `Onboarding.js:249–258`, `Dashboard.js:311,912–914`, `server.py:1595–1673` write legacy `schedules`; `scheduler.py:115–163` reads `parent_checkins`, `parent_health_reminders`, `parent_routines`, `medicines` instead. No bridging SQL trigger/migration was found in repository files.
- Impact: displayed schedules can look correct while no daily work exists; dashboard pause can fail to pause granular sends; recovery mode writes to the old source too.
- Repair: choose one source with an explicit compatibility boundary. For production, first dry-run a comparison for affected accounts; reconcile non-destructively with conflict reporting and rollback data. Preserve existing parent choices. Do not blindly overwrite both representations or revive deleted schedules.
- Additional schema risk: `_get_parent_schedule` always queries `medicines`, but no `CREATE TABLE medicines` was found in checked-in schema/startup/migration files. If not created manually in production, it aborts each parent's scheduling pass. Verify the live schema read-only.

**F03 — False activation success and repeated welcomes.**
- Evidence: `server.py:2153–2199` queues welcomes, sends another opener, sets `activated = True` regardless of failures, returns `welcome_sent: True`. Parent creation already queued a welcome at line 1192. `whatsapp.py:721–722` skips signup welcome.
- Repair: idempotent child welcome after verified contact and consent; idempotent parent welcome when ready; separate configuration-ready, queued, accepted, delivered and failed states per recipient. Do not label API acceptance as delivery or block valid ongoing schedules merely because a welcome receipt is delayed.

**F04 — Flood prevention can also silence valid reminders.**
- Evidence: `scheduler.py:304–381`; `escalation.py:236–278`.
- Repair: durable slot identity, activation cutoff, bounded catch-up with spacing, separate safety attempt budget versus successful-send quota, per-slot error handling and retry bounds, in-loop/global per-parent caps shared by all workers. Never remove all safety caps as a shortcut. Treat provider timeout acceptance as uncertain, not an unconditional safe resend. Existing unique Meta SID does not prevent two distinct sends for one care slot.
- Concurrency risk: delivery lock TTL is 55 seconds, while synchronous 30-second network calls and retries can outlast it. Renew leases / fence ownership or atomically claim individual jobs; a second instance can otherwise acquire an expired lock while the first still sends.

**F05 — Medicine and non-medicine meaning must be safe.**
- Evidence: `scheduler.py:286–297,319–327` drops medicine identity when deduplicating; two medicines at the same time can collapse into one. `whatsapp.py:334–356` fills water/BP/sugar/health checks into the medicine template; `meta_approved_templates.txt:19–21` explicitly describes taking a tablet.
- Impact: missed medicine reminders or nonsensical/wrong tablet instructions such as "Time for a water check tablet."
- Repair: stable per-medicine reminder ID or an explicit grouped-medication message; dedicated content and correct button meaning for water, BP and other checks. Verify actual approved template body before enabling those mappings.

### P1 — trust, recoverability and international readiness

**F06 — Reply can be saved but its notification lost.** `server.py:3214–3244` inserts a reply before notification. Retried inbound is skipped as duplicate; no notification outbox can recover a failed child send. Webhook handler acknowledges even when processing fails (`3717–3838`). Raw debug archive is not an automatically retried work queue. Persist inbound work durably before acknowledgment and process idempotently; do not merely change to endless webhook retries.

**F07 — Welcome/child warning delivery is not fully observable.** Normal welcome and family-notification send results are not persisted in `message_logs`. Receipt handler matches by SID, so these messages cannot reliably appear in the delivery funnel. Store recipient and event IDs plus Meta code/details, callback timestamps and matched/unmatched receipts. Numeric error codes matter, not just free-text titles.

**F08 — Pause and holiday rules diverge.** `_check_reengagement_impl()` and `run_care_watch_impl()` lack vacation guards. Reengagement uses a hard-coded 2 hours, not the configured value, and lacks the normal activity-window check. A single shared eligibility rule should govern all sending paths. Add parent-side opt-out and re-enable behavior with multilingual recognition and consent records; do not tell a user pause worked while another worker continues sending.

**F09 — Default parent timezone is the child's browser timezone.** `ParentCareForm.jsx:30–35`. Require parent-location confirmation, show a server-derived next-send time in both timezones, and validate IANA timezone names. Onboarding hard-codes "tomorrow at 8:00 AM IST" (`Onboarding.js:260`) instead of reflecting configured schedule. Do not silently overwrite existing timezones.

**F10 — False no-reply warnings / inconsistent family coverage.** Escalation counts attempted logs without requiring delivered status, then can tell a child the parent missed check-ins that never reached them (`escalation.py:299–332`). It marks warning sent without verifying recipient outcomes. Care-watch `_notify_child` queries legacy users/emergency contacts, not `care_circle_siblings`. Distinguish "delivery failed" from "no reply to delivered check-in" and use shared per-recipient notification handling.

**F11 — Incoming child buttons are ignored.** `_record_reply` only resolves parents. New child warning buttons are declared in the template draft, but no child acknowledgment handling is present in the reviewed path. Proper child session tracking and intended "I'll call" actions need separate dispatch, not recording the child as a parent.

**F12 — Reports and automation claims drift.** Current `start_scheduler()` registers delivery, reengagement and care-watch only, not automatic monthly reports or recovery-expiry jobs promised in README. The check-in summary allocates replies by time, while the notification label may use exact `context.id`; consume-once prevents double counting but is not proof of correct message attribution. Preserve replied-to ID as first-class data. Backend PDF uses `reportlab`, absent from checked-in requirements; runtime availability is unverified.

**F13 — Billing is not the advertised recurring multi-currency lifecycle.** `payments.py:71–86` uses `mode="payment"`, `currency="usd"`; the checkout request carries no chosen currency. No recurring renewal, cancellation, proration, scheduled downgrade or failed-renewal handling was found. `pricing.py:41` has Nitya INR monthly 949 versus yearly 950; verify intent before changing any price. Current displayed currencies are not evidence of charging in those currencies. Payment plan application also needs transaction/event ordering protection for repeated/concurrent checkout flows.

### P2 — maintainability after recovery

**F14 — Documentation and baseline code hygiene are stale.** README/old PRD assert fixes/features absent from current worker and call drafted templates approved. `monthly_report.py` duplicates its import/helper block and contains four bare `except` blocks; `server.py` shadows imported `CHECKIN_CATEGORIES` and defines the same delete-routine route twice. These baseline lint findings were not changed during this read-only phase and are not established causes of the four-day incident. A JavaScript lint engine issue was also reported by the workspace gate, not independently diagnosed here.

Reduce duplicate sources after reliability fixes; don't combine a broad router/UI rewrite with the emergency repair.

## WhatsApp template audit

1. `ayana_opener_{en,te,hi}` is reused for parents and children; it is not a purpose-specific child account welcome.
2. `ayana_first_warn_child_*` and `ayana_main_warn_child_*` handle silence warnings, not "Amma replied" events.
3. No event-specific ordinary child reply/voice-notification template routing was found.
4. Parent first-warning helper exists but is unused in its actual escalation path.
5. `meta_approved_templates.txt` mixes a purported existing inventory with a section explicitly "Ready to submit to Meta Dashboard". File names/category comments are not approval evidence.
6. The file incorrectly says sending a template opens the 24-hour service window. The recipient's inbound reply opens/refreshes that window; receiving a business template alone does not.
7. Language codes are centrally mapped to `en`, `te`, `hi`. Compare against the actual approved locale, component parameters, and button definitions; do not blindly change `en` to `en_US`.

Candidate child service templates to discuss (NOT submitted or approved):
- Verified account welcome: "Hi {{1}}, your AYANA account is ready. You can now add your parent and choose their check-in times."
- Parent reply notice: "AYANA update: {{1}} replied to the {{2}} check-in at {{3}}. View their reply in your account."
- Parent voice notice: "AYANA update: {{1}} sent a voice note at {{2}}. Open your account to listen."

Keep transactional notices tied to the service the user requested, with explicit consent and correct Meta categorization. Do not relabel promotional content as Utility to evade restrictions. These drafts need policy review and actual Meta approval.

## CEO product recommendations

- Position AYANA as **care arranged by the child, delivered by AYANA**, not deception that the child personally typed each automated message. Preserve family warmth and transparency.
- Promise connection and activity updates, not prevention of depression, medical monitoring, guaranteed safety or emergency response. A missed reply alone does not prove distress.
- Keep onboarding focused: verified child → transparent plan → parent consent/contact/location → a few useful times → separate welcome/delivery status for each person → first reply notification. Logins should not repeatedly welcome existing users.
- Put "Last message delivered", "Last reply", "Child notified" and "Next check-in" ahead of decorative analytics. Display delivery failure separately from no reply.
- Offer fewer well-timed, meaningful messages rather than making message volume the main plan benefit. Consider a configurable daily summary alongside urgent notifications so children are not overloaded.
- Audit unit economics using recipient-specific template costs: parent sends, owner notifications, siblings, warning retries, voice processing, storage and support. Existing cost helper counts only some parent scheduled messages and underestimates the complete service.
- Align renewal, downgrade timing, currency and refunds with clear customer-facing terms before broadening sales.
- Long-term differentiator: dependable delivery and a useful nudge to actually call—not more unattended reminders.

## Proposed success metrics (targets to agree, not measured performance)

1. Percentage of new paying households reaching first parent delivery + first reply + child notification within 24 hours.
2. Eligible on-time parent send rate, with separate provider acceptance and delivery metrics.
3. Parent-reply-to-child-notification delivery rate and median/p95 delay.
4. Duplicate sends per scheduled event and missed-notification incidents per household/week.
5. Share of delivery failures with a visible reason and successful bounded recovery.
6. Seven-/thirty-day household retention and parent opt-outs, not just raw messages sent.
7. Gross margin by plan and destination country including child notifications.

## Production-safe repair sequence — pending approval

1. **Preserve evidence first:** deployed revision; relevant scheduler/webhook errors; actual Meta inventory; read-only records for the three affected households. Raw webhook debug retention in code is only 14 days.
2. **Establish the exact broken hop:** compare parent inbound event → saved reply → child outbound attempt → Meta receipt. Compare displayed schedule → worker-readable schedule → slot claim → receipt for Dad.
3. **Agree narrow changes:** ordinary child notification routing, truthful activation, schedule compatibility and unified send/anti-flood rules. Confirm transactional template names and approved statuses before use.
4. **Prepare isolated regression environment:** fake numbers, non-production database, all outbound integrations blocked except specifically opted-in test recipients. No production startup or `schema.sql` execution; that file contains `DROP TABLE` statements.
5. **Controlled verification after explicit consent:** one known parent-child test pair; then an eligible US recipient and other target countries. Compare open/closed recipient windows, multiple silent days, webhook duplicates, two medicines at one time, both parents, pauses, local midnight/DST, retries and failed templates.
6. **No historical-message flood:** do not bulk replay the missing four days. If recovery is approved, send a clearly dated summary and resume only valid future/current events according to agreed policy.

## Information needed from founder

- Whether the missing Amma replies are absent only from child WhatsApp or also the dashboard; affected account emails/IDs and approximate last successful timestamps/timezones.
- For USA friend, whether welcome/daily messages are missing for child, parents, or both.
- Meta template screenshots/export showing **exact name, language, actual category, approval/quality state, body and buttons**, especially opener and child templates.
- Redacted production logs with WhatsApp message IDs, error codes/details and timestamps; deployed code revision. No passwords, OTPs or access tokens needed for this discussion.
- Approval to prepare narrowly scoped local repairs, with no customer messaging or production data changes until separately authorized.

## References

- Meta: https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes (page updated June 18, 2026). `131047`: service window expired; `131049`: engagement-related delivery restriction (not alone proof of US restriction); `132001`: template missing/unapproved/incorrect locale; `132000`: parameter count; `132015`/`132016`: paused/disabled; `131056`: too many messages to same recipient. Both synchronous responses and asynchronous webhooks must be monitored.
- Twilio's documentation of Meta's US marketing pause: https://www.twilio.com/docs/api/errors/63049 . Used as policy evidence only; AYANA uses Meta directly, so Twilio's numeric code is not AYANA's runtime code. US marketing pause is not a basis to promise universal Utility delivery.
- Offline review artifacts: `test_reports/iteration_18.json`, `test_reports/iteration_18_diagnostic_test.py`.