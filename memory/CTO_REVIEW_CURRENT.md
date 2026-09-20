# AYANA — Current CTO functional review

**Date:** 2026-09-20. **Application baseline:** `ef0b00d`, `/app/backend` and `/app/frontend`.

## Scope and honest verdict

The founder requested a serious, read-only review beyond the reported US-child welcome/reply failures, silent parents, and repeated nudges. This report concerns the actual current source, not historical claims in `AYANA_REVIEW.md` or the PRD. It is not a security audit, production root-cause certification, or completed repair.

**Verdict: meaningful engineering improvements exist, but the core care loop still has material reliability defects. I would not sign off on dependable unattended care or seamless worldwide delivery from this evidence.** The central problem is inconsistent state: provider acceptance, delivery receipts, retry claims, reply effects, billing access and UI success do not always agree.

- No application logic, credentials, live database records, templates, or configuration were changed. No app startup, production migrations, real WhatsApp messages, emails, or payments were initiated.
- Current application `.env` files, external preview URL, live credentials, deployed revision, actual Meta template inventory, and incident receipts were unavailable. Production delivery and frontend browser behavior were not tested. Configuration absence here is not proof production lacks it.
- Added only review notes and isolated diagnostic artifacts. Database/provider boundaries are **MOCKED IN TESTS ONLY**, including infrastructure import stubs. These tests execute Python paths but do not validate PostgreSQL SQL execution, transactions, locks, actual Meta approval, or real delivery.
- Stricter diagnostic run: **17 tests passed**, including positive controls, in `backend/tests/test_iteration22_readonly_diagnostics.py`; report `test_reports/iteration_2.json`. Passing diagnostic assertions means the described behavior was reproduced, not that the application is healthy.
- Earlier `iteration_1.json` reported 26 diagnostic/unit passes. Several initial tests were shallow; the second run supersedes their stronger claims. Do not add overlapping counts and call them independent end-to-end scenarios.

## The USA friend: what code can and cannot explain

The current ordinary-reply path records recipient-specific sessions and chooses free text in-window or `ayana_parent_reply_*` / `ayana_parent_voice_*` outside it. This is a real improvement; the old report's claim that ordinary replies still use only free text is obsolete. The legacy `_notify_family` implementation remains in the file, but it is not the current `_record_reply` notification path.

However, the welcome-recovery implementation is unreachable for a normal child account:

1. `_process_meta_payload` records inbound recipient activity (`routes/webhook.py:873`). The child's hello can therefore reopen that child's service window and allow subsequent ordinary replies.
2. `_record_reply` looks up a **parent** using the child's number (`374–404`). It returns `ignored` when no parent matches.
3. Clearing the owner's `needs_inbound_click` flag and resending the welcome occur **after that return**, requiring the sender to be both parent and owner (`417–427`). Parent creation explicitly prohibits using an account-holder number (`routes/parents.py:56–93`).

**This directly explains a possible “replies started again after Hi, but still no welcome” sequence.** It does not establish why Meta first rejected this friend's welcome. A manual activation/admin resend is another possible path, so “permanently impossible to welcome” would overstate the finding.

Separately, Meta's current documentation says Marketing templates are not delivered to US numbers (+1 plus a US area code). Error `131049` also covers per-recipient marketing limits; it is **not uniquely a missing trust signal**. The code comments and activation prompt overpromise that messaging first clears the problem. A greeting does not prove a blocked Marketing template becomes eligible. Utility eligibility, category, approval, locale and exact error must be checked in Meta; a repository comment or template filename is not proof. Canada also uses +1, so this is not an all-+1 ban.

Parent and child service windows are independent. A parent's reply, SMS/email verification, receiving a template, or merely viewing a WhatsApp message does not open the child's service window. The provided screenshot shows a sent greeting, not backend recovery completion.

## Ranked findings

### F01 — P0: source/schema drift can break the reply path and checkout

**Evidence: source/schema comparison; not executed against live PostgreSQL.**

- `routes/webhook.py:419–425,750–765` reads/writes `users.needs_inbound_click`. No definition or additive migration for it exists in `schema.sql`, checked-in migrations, startup migrations, or scripts searched. The read runs for each resolved parent before inserting a new reply. On a database built only from checked-in definitions, it fails before recording/forwarding replies. The 131049 receipt handler can also fail before updating welcome status.
- `services/checkout.py:82–87,135` requires `billing_orders.credit` and `credited_grant_id`. `migrations/006_checkout_coupons.sql:19–28` defines neither, and retains `CHECK(subtotal-discount=amount)`, incompatible with nonzero credit. No checked-in later migration adds the columns or corrects that invariant.
- `services/migrations.py:10` only applies numbered migrations 004–008. Production may have manual alterations; that remains unverified. Historical tests using fake rows cannot certify this schema.

**Repair:** inspect production columns/constraints read-only, add versioned non-destructive migrations and schema-contract tests. Do not run `backend/schema.sql`: it contains destructive DROP statements.

### F02 — P0: child greeting cannot trigger intended welcome recovery

**Evidence: executed real webhook/record path with mocked database boundary**, strict test `test_unknown_inbound_records_session_and_real_record_reply_stays_unowned`.

Sources: `routes/webhook.py:374–427,865–873`; `services/welcomes.py:36–47`. Child sessions work, but owner flag clearing/welcome retry is behind parent-only lookup. Signup itself still queues `send_child_welcome`, which intentionally returns skipped (`whatsapp.py:732–733`; `routes/auth.py:86`). Welcomes actually depend on later activation/parent setup.

**Repair:** dispatch parent/owner/sibling inbound separately; use session-aware, purpose-appropriate child welcome delivery. Do not treat 131049 as universally fixable by asking for Hi.

### F03 — P0: asynchronous send failures fall outside retry handling

**Evidence: executed receipt and worker paths at mocked DB boundaries**, including `131047` and `131016` child receipt cases.

- Parent scheduler leaves `care_send_claims.status='sent'` after API acceptance (`scheduler.py:69–70,89–94`). A later failed receipt updates `message_logs` but not the claim (`routes/webhook.py:733–765`). A subsequent due tick sees the claim and skips that slot even with retry budget remaining. New days have different keys; this alone does not prove a multiday permanent outage.
- Child notifications handle synchronous retryable errors (`services/notifications.py:94–99`), but `persist_receipt` changes asynchronous errors to terminal `failed` (`147–166`). `drain_notifications` selects only pending/retry/awaiting_template/disabled (`111–115`). A `131047` receipt does not invalidate the stale child session or schedule a template attempt.
- Email fallback is attempted, but a failed email on a terminal failed notification has no independent retry worker. Do not assume email guarantees recovery.
- Family-warning claims similarly record API send results, but the receipt handler does not reconcile their `care_send_claims` records. A warning accepted then rejected can remain treated as sent (`escalation.py:24–58`).

**Repair:** shared receipt-to-event state transitions; error-specific, bounded retry/template rerouting; independent fallback outcomes. Never retry all failures indiscriminately or blindly replay uncertain submissions.

### F04 — P0: the 10 PM silence alert can never run under common quiet hours

**Evidence: executed suppressed and positive-control warning paths.**

`escalation.py:65–88` applies parent's sending activity window before the child's main-warning decision at 22:00. Default parent window ends 22:00 (`ParentCareForm.jsx:43–44`); eligibility uses HH:MM comparison (`schedule_source.py:25–27`). The five-minute interval job (`scheduler.py:158`) must land in the single 22:00 minute to pass. At 22:01 onward it is suppressed. With user-selected end=21:00 the main-warning branch is unreachable. The interval is not aligned to local 22:00.

**Repair:** separate parent quiet hours from child alert eligibility, while honoring pause/vacation/consent. Evaluate a durable due warning over a bounded interval, not one minute.

### F05 — P0: a button can mark the wrong medicine/reminder as done

**Evidence: executed `_apply_button_tap_effects` with an older `message_log_id`; it updated the newest log instead.**

Reply insertion records exact `context_id`/`message_log_id` (`routes/webhook.py:485–498`), but generic intent lookup uses latest category (`228–250,276–282`) and effects select the latest matching category on today's local day (`554–592`). A delayed response to a morning medicine prompt can mark the evening one done; a yesterday button can affect today. Exact notification attribution being saved does not make the effects correct.

**Repair:** resolve both intent and effects from the exact replied-to message and medicine/slot identity. Do not silently interpret an old reply as current adherence.

### F06 — P0: medicine capacity is measured differently at setup and sending

**Evidence: executed sync → schedule expansion → later scheduler quota branch.**

`medicine_sync.py:100–132` counts distinct reminder times. `schedule_source.py:50–54` expands each time into individual medicine names. `scheduler.py:79–83` counts actual sends. Example: Nitya has Med A and B at 09:00, water at noon, Med C at 20:00. Setup reports three slots and `dropped=[]`; execution has four sends, so after A/B/water, C is suppressed by the three-reminder budget.

**Repair:** one consistent capacity model, explicit grouping or per-medicine identity, and confirmation that every accepted medicine has a deliverable slot. Silent medication suppression is not an acceptable quota policy.

### F07 — P1: anti-flood rules are improved, but not shared by all paths

**Evidence: executed welcome race and uncertain nudge/welcome behavior; reset operation checked at SQL boundary.**

- Concurrent `welcomes.send_once` calls both SELECT, both UPSERT, and both send (`services/welcomes.py:15–28`). A unique event row is not an atomic send claim. An existing uncertain welcome is resendable, unlike the safety rule used by normal notifications.
- `whatsapp.send_reengagement:431–462` does not mark uncertain acceptance as consumed. The scheduler logs it and delays sends, but a later tick can resubmit a possibly accepted nudge. `mark_opener_sent:299–315` resets `reengagement_sent=false` for every successful closed-window category template, not just a once-daily opener (`359–379`). Later scheduled templates can therefore re-enable nudges that day.
- There is no durable welcome drain worker. API background tasks, rows recording outcomes, and automatic crash recovery are different things.

The old same-evening backfill burst is mitigated by activation cutoff, 30-minute lateness cutoff, per-slot claims and two-minute spacing. **Do not remove those protections to fix missing messages.** Current remaining defects do not prove every historical flood had this cause.

**Repair:** atomic per-recipient welcome claims, durable welcome jobs, shared per-parent nudge budget, and uncertain-state reconciliation. Never bulk replay missed historical care messages.

### F08 — P1: voice API failure converts a voice reply into blank text

**Evidence: executed actual `_record_reply` insertion path with `media_url=None`.**

`resolve_meta_media_url` returns None on errors (`whatsapp.py:563–576`). Webhook passes audio MIME/media ID but no URL (`routes/webhook.py:893–898`); classification requires a resolved URL (`442–449`). The reply is saved `is_voice=false` with blank body; STT/archive/voice-template paths are skipped. A transient media lookup failure therefore becomes a misclassified durable reply, rather than a recoverable media task.

**Repair:** classify from WhatsApp message type first, persist media ID, retry retrieval/transcription independently, and show unavailable/pending audio honestly.

### F09 — P1: duplicate protection skips unfinished button effects

**Evidence: executed webhook orchestration with first effect failure and second invocation explicitly skipped.**

Reply/outbox commit occurs before `_apply_button_tap_effects` (`webhook.py:481–518,925–926`). If effects fail, retry returns the existing reply as duplicate (`375–378`) and avoids the effect forever. Reply stored is not proof every required effect completed.

**Repair:** track idempotent effect completion or commit pure database effects with the reply; dispatch acknowledgments as durable outbound events.

### F10 — P1: recovery-mode promises do not match scheduling/validation

**Evidence: executed validator rejection, expired schedule loading and six-reminder worker quota.**

Raksha advertises two additional recovery reminders (`pricing.py:103–110`). Start API appends them (`routes/schedules.py:131–159`), but worker caps reminders at six without recovery allowance (`scheduler.py:79–83`). `models.ScheduleInput.messages` validator reads `recovery_mode` before that later field has been parsed (`254–286`), so an eight-reminder update is rejected even when recovery is true. Dashboard pause submits that same schedule; pausing can fail validation. No automatic expiry process is registered, and `load_schedule` ignores `recovery_until`.

**Repair:** cross-field validation after parsing, matching quota accounting, parent-local expiry, and pause independent of editing/validating the complete schedule.

### F11 — P1: selectable health reminders deliberately stop outside the parent window

**Evidence: executed `send_dynamic_checkin` closed-session water case.**

`whatsapp.py:406–408` returns `blocked_template` for water/BP/sugar/health. This correctly avoids the old dangerous tablet-template substitution, but it is an incomplete feature. Users can configure these reminders and they stop when the parent stops replying. Claims then keep the slot blocked for that day even if the session later opens.

**Repair:** approved purpose-correct templates or disable unsupported scheduling with clear capability status. Never restore tablet wording for non-medicine checks.

### F12 — P0: dashboard subscription checkout loses required currency

**Evidence: source-traced frontend/API contract; not browser-tested.**

`PricingCards.jsx:121` calls `onSelect(plan,billing,currency)`. `PlanPanel.jsx:37,73` defaults to subscription but stores only plan and billing. `SubscribeDialog.jsx:71,79` forwards that selection without adding currency, while `routes/billing.py:22–39` requires it. Normal dashboard subscription selection produces an invalid quote request, leaving preview/pay disabled. The free-access-code button (`PlanPanel.jsx:96`) also opens the currently selected subscription dialog, which has no coupon entry. The pay-once dialog supplies its own currency and is a separate path.

**Repair:** carry selected currency through both dialogs; route code redemption to the coupon-capable flow; test default purchase and renewal paths, not backend endpoints alone.

### F13 — P0/P1: subscription provider contract and lifecycle need repair

**Evidence: provider documentation/source comparison for creation; executed signed webhook functions with fake DB for replay.**

- `subscription_gateway.py:91–108` sends `total_count:0`, described as infinite, and integer flags in `notify_info.notify_phone/notify_email`. Razorpay documents a positive billing-cycle count; notification info represents customer contact values, not booleans. This payload needs correction before asserting recurring checkout works. No real gateway response was collected.
- `routes/billing.py:350–387` computes subscription periods from webhook receipt time, ignores provider period boundaries, and has no event/payment idempotency or stale-transition guard. Replaying the same charge later moves the paid-through date; a stale charge after cancellation can set the **local subscription** active. This does not prove another customer charge occurs or that the provider subscription is reactivated.
- `services/billing_access.py:24–43` permits authenticated/active subscriptions with null period end. Verification only updates local status, not remote period dates (`routes/billing.py:216–232`). Missing charge/lifecycle events can leave access unbounded until reconciliation.

**Repair:** correct provider request contract; provider-authoritative periods; durable deduplicated event processing; monotonic state/reconciliation; explicit mandate-authorized vs captured-paid states.

### F14 — P1: scheduled care ignores actual paid-access eligibility

**Evidence: executed access resolver denied an expired account while scheduler still sent.**

`scheduler.py:46–57` checks activation and reads only `payment_state.plan`; it never consults `billing_access.access`. `_get_plan_id` elsewhere reads the resolver but ignores `allowed` (`services/deps.py:80–87`). A future downgrade grant can also immediately write a lower plan to payment_state (`billing_access.py:115–137`) while the access resolver still honors higher unexpired access. Care quotas and billing entitlement diverge.

**Repair:** one entitlement source with an explicit grace/pause policy, including protected legacy paid users. Do not abruptly suspend elderly-parent care as an unannounced side effect of a billing fix.

### F15 — P1/P2: operational visibility and tests still create false confidence

**Evidence: source inspection, not full UI validation.**

- `routes/parents.py:162–166` says `welcome_sent=true` before the activation-gated background task runs. Activation endpoint is more truthful now, but this other response still lies.
- Main activation page does not fetch per-recipient welcome outcomes; ordinary user care-status endpoint exposes only the parent's welcome (`routes/care.py:22–24`). Admin sanity tools can view both.
- Admin fake-reply bypasses actual inbound parsing and directly inserts replies (`routes/sanity.py:85–129`), so it can pass while the real parent webhook fails, including missing `needs_inbound_click` schema.
- Monthly reporting exists manually, but scheduler registers only delivery, reengagement, care-watch, inbox and notifications (`scheduler.py:153–159`). No automatic report/recovery-expiry job was found. An external cron could exist; not verified.
- `SERVER_MAP.md` references `tests/refactor`, absent from this workspace. Legacy `backend/tests/conftest.py` expects token-in-JSON/bearer flows and uses a password violating current input policy. It starts full app lifespan; running broad legacy tests against production config is unsafe.
- JS tooling reported an engine error through the workspace check. This was not investigated or misrepresented as a production UI bug.

**Repair:** show parent delivered / reply recorded / each child notified separately; monitor pending/uncertain/failed ages and unmatched receipts; test real webhook-to-recipient paths with nonproduction PostgreSQL and provider sandbox boundaries.

## Things already improved — do not regress them

- Ordinary child replies are durably queued, independently session-aware, and template-routed when closed.
- Child inbound sessions are recorded before parent-only dispatch; missing welcome recovery is narrower than missing all child handling.
- The dashboard legacy schedule now wins through an explicit compatibility loader. The old blanket “UI schedules are never read” finding is obsolete, though granular edits are ignored when a legacy schedule exists.
- New parent timezone default is Asia/Kolkata and backend validates IANA names. Do not repeat the previous browser-timezone-default criticism.
- `medicines` now has an additive table migration; the previous missing-table claim is obsolete.
- Activation cutoff, bounded lateness, per-slot claims, spacing and common vacation/opt-out eligibility are present.
- INR annual price typo is corrected; recurring billing code exists, but existence is not proof of correctness.

## Repair order and release gate

1. Read-only production evidence: deployed commit, affected recipient's welcome/reply event chain, raw numeric Meta errors, actual template category/name/locale, and schema columns/constraints. No passwords or tokens needed in a report.
2. Fix schema drift, separate child welcome dispatch, and reconcile parent/child async receipt retry states. Test one opted-in US child/Indian parent pair with open AND closed recipient windows only after approval.
3. Fix quiet-hour child alerts, exact reminder effects, medicine capacity and remaining duplicate/nudge risks. Never replay days of missed reminders.
4. Repair checkout currency and provider contract, then billing event ordering/idempotency and shared entitlements. Preserve paid time and existing legacy access.
5. Complete voice recovery, recovery-mode expiry/quotas, unsupported template capabilities, and user-visible recipient outcomes.
6. Backlog: consolidate legacy paths, repair test/document drift, automate reports only after agreeing behavior; measure reliable care rather than adding message volume.

Acceptance matrix must include: India/US recipients; both sides open/closed windows; duplicate webhook and delayed failed receipt; clock crossing 22:00; delayed old-button reply; two medicines same time; expired recovery/trial; cancelled/stale payment events; uncertain timeout; two worker submissions; pause/vacation; media resolver outage. Offline mocks do not replace a nonproduction PostgreSQL/controlled-provider pass.

**Suggested product improvement:** a household care-delivery ledger: **Parent received → Parent replied → Child received** with exact time and failure reason. This makes reassurance verifiable and shortens support incidents.

## References and reproduction

- Meta per-user limits and US restriction: https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/marketing-templates/per-user-limits (retrieved during review; updated June 17, 2026).
- Razorpay create-subscription contract: https://razorpay.com/docs/api/payments/subscriptions/create-subscription/ and official SDK subscription examples. Contract review only; no provider account tested.
- `docs/meta_approved_templates.txt` mixes inventory and “Ready to submit” drafts; it is not live approval evidence. Its claim that sending a template opens the 24-hour service window is incorrect.
- Strict test command recorded by testing: `DATABASE_URL=postgresql://u:p@localhost:5432/db PYTHONPATH=/app/backend/tests/_stubs:/app/backend pytest -v --noconftest /app/backend/tests/test_iteration22_readonly_diagnostics.py --tb=short --junitxml=/app/test_reports/pytest/pytest_results.xml`. The URL is a dummy test import setting, NOT a production credential; DB calls are fake. Run only in the isolated test process, not with live config.
- Keep the test-only stubs off production PYTHONPATH. They do not emulate transactional/locking/provider guarantees. Early diagnostics are supplementary; strict iteration 2 plus explicit source evidence are the review basis.

**All listed product issues remain unfixed in this review.** Application repair requires a separate scoped implementation step.