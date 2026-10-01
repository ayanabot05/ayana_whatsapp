# Template readiness — 1 October 2026

The 30 daily template definitions in `daily_template_drafts.json` now match the
user's submitted names, languages, bodies and quick-reply titles. Their stored
status is PENDING, not APPROVED. Love notes take two parameters: parent name and
account-owner/child name; the other daily templates take the parent name.

Daily messages use free-form conversations inside the recipient window and
category-specific approved templates outside it. Shopping preserves the saved
`location_label`, including window-expiry fallback and safety follow-ups.
Submitted button titles are classified against the referenced outbound category.
Missing or pending approvals produce a recorded configuration error, never an
unrelated meal/medicine message. Future scheduled occurrences remain independent.

Child welcomes use `ayana_child_welcome_<language>` with one name parameter,
preserving verification, consent and deduplication gates. The 2pm parent nudge
and child warning run during 14:00–14:29 in the parent's timezone after an
unanswered morning delivery. The child warning follows successful submission of
the parent nudge. The 10pm warning runs during 22:00–22:59. Existing delivered-
message eligibility remains: these warnings are not undelivered-message alerts.
A parent reply suppresses no-reply warnings. Durable per-recipient claims prevent
repeated scheduler ticks from resending accepted warnings.

Reports use the approved dashboard notification, without an incompatible PDF
header. The monthly worker creates the previous calendar month's report from
9am on the first in the parent's timezone, with catch-up during the month.
Persistent jobs survive restarts and deduplicate generation and recipient sends.
Transient failures retry; uncertain submissions are not blindly resent.
Verified-email fallback requires the email service configuration and the
recipient's email-notification preference. Accepted WhatsApp submissions with
no delivery receipt after six hours also qualify for this fallback.

The current plan's combined family-member allowance is checked at send time
for replies, reports, warnings and welcomes. A downgrade cancels ineligible
queued notifications and blocks linked members from household data endpoints;
personal account maintenance remains available. Current verified contact details
are resolved at send time.

Two distinct scheduled slots without confirmed delivery, each at least one hour
old, create one delivery alert per parent per local day. Successful retry receipts
resolve a slot. Alerts appear separately on the dashboard and use a dedicated
family notification with email fallback. New `ayana_delivery_issue_en/te/hi`
definitions are DRAFT in `delivery_issue_templates.json`: they require submission
and Meta approval for outside-window WhatsApp delivery. They are not no-reply
warnings and must not reuse those templates.

Welcome jobs blocked by template configuration recover after the actual approved
catalog contains a matching definition. Accepted and uncertain welcomes are not
replayed. The submitted Need help buttons now produce `emergency:help` and enter
the emergency-event path.

## Approval synchronization

The latest configured Meta account returned 41 templates. The English and Telugu
morning templates are PENDING. The Hindi parent-voice template is also PENDING;
its previous approved entry was no longer returned. Warning and child-welcome
names were still absent. User-supplied warning/welcome bodies remain separately
in `supplied_warning_welcome_templates.json`; this is not a live approval catalog.

After approval, run from the project root:

```powershell
python scripts/sync_meta_templates.py
```

The script retrieves actual names, languages, statuses and components and lists
any missing approvals. A nonzero exit with a missing-approval list means the
catalog was refreshed but is not yet complete. Running workers using the updated
code reload an atomically updated catalog on their next send; no restart is
needed for subsequent catalog changes. Deploy/restart once to load code changes.
Previously failed slots are not backfilled. No background approval polling is
configured, and no production deployment was performed.

## Validation

12 message-routing tests, 10 offline regressions and 22 isolated PostgreSQL
integration tests passed. Coverage includes all submitted payloads using explicit
hypothetical approved fixtures; 31 days of 8am/1pm/8pm check-ins, 4pm walks and
Wednesday 6pm safety checks; Dmart preservation; 2pm/10pm warning deduplication;
rejected-nudge suppression; parent-reply suppression; pending-status rejection;
and catalog reload after sync. Meta responses were simulated and no live family
messages were sent. These checks do not establish production handset delivery.

```powershell
python tests/test_daily_template_routing.py
python tests/test_delivery_regressions.py
python tests/test_delivery_database.py
```

Database tests require the isolated local PostgreSQL cluster on port 55439.

13 additional launch checks passed in `tests/test_launch_readiness.py`, including
real report generation/persistence, deduplicated email fallback, plan downgrade,
contact changes, welcome recovery, delivery alerts and emergency-event creation.
The three targeted CheckinsView tests also passed, including the delivery alert.
Apply additive migration `012_family_delivery.sql` through normal backend startup
on existing databases. Fresh-install schemas include its three new tables.
Do not run the reset schema against existing customer data.
