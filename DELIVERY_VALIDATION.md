# Delivery and dashboard regression checks

Update verified on 1 October 2026: 12 daily-routing tests, 10 offline regressions,
22 existing PostgreSQL integration tests, 13 new launch-readiness integration
tests and 3 targeted CheckinsView frontend tests passed (60 total). Fresh-schema
and disposable-reset validation passed for all 52 tables. Meta and email sends
were mocked; no production sends or deployment were performed for these checks.

The five launch fixes cover persistent monthly generation and report-ready
notifications, current-plan family eligibility and household API access,
undelivered-message dashboard/family alerts, approved-template welcome recovery,
and Need help emergency routing. New delivery-alert template drafts are in
`docs/delivery_issue_templates.json`; actual Meta approval remains required.
Monthly WhatsApp notifications link to the dashboard rather than attaching a PDF.
Email fallback requires configured credentials, verified email and enabled
recipient preferences. See `docs/daily-template-routing.md` for deployment and
catalog-refresh instructions.

Verified on 30 September 2026: 10 offline backend tests, 16 PostgreSQL integration
tests and 17 targeted frontend tests passed. The production frontend build
completed successfully. Fresh-schema restoration and the
safe second-run refusal also passed. This is targeted regression coverage, not
a claim that every existing test in the repository has passed.

## Scope

Tests exercise the real scheduler, durable delivery records, inbound webhook,
reply association, notification worker, receipts, dashboard timeline and monthly
summary against an isolated local PostgreSQL database. Meta HTTP responses are
simulated. Passing tests do not establish real handset delivery or deployment.

Backend tests cover:

- Both recipients silent for more than 24 hours: scheduled parent templates
  continue over three days without requiring an inbound message.
- Parent and child welcome templates, scheduled check-in, exact parent reply,
  child reply template outside the service window, and delivery receipts.
- Repeated/concurrent scheduler ticks, no pre-activation catch-up, bounded
  rejected-send retries, and no duplicate retry after an uncertain submission.
- One unanswered medicine/safety follow-up; no daily check-in/activity follow-up.
- Late replies retain the original morning message; dashboard and report counts
  use that association. Duplicate inbound webhooks forward only once.
- Contact-change welcome recovery and latest-consent checks.
- Parent deletion requires ownership before modifying the parent or schedule.

Frontend tests cover parent display, cancellation, refresh without deletion,
initial request failure, retained data after a failed refresh, late-reply cards,
notification status, and confirmation dialog pending/success/failure behavior.

## Run in the project terminal

```powershell
python tests/test_delivery_regressions.py
python tests/test_delivery_database.py
python scripts/validate_complete_schema.py
Set-Location frontend
$env:CI='true'
node node_modules/@craco/craco/dist/bin/craco.js test --watchAll=false --runInBand --runTestsByPath src/pages/Dashboard.test.js src/components/checkins/CheckinsView.iter3.test.jsx src/components/ui/ConfirmDialog.test.js
npm run build
```

Database checks require the isolated local PostgreSQL cluster on port 55439,
role `ayana_test`, and database `ayana_delivery_local`. These scripts do not use
the production database. The schema validator creates a separate temporary test
database on that local cluster; it leaves it available for inspection.

## SQL schema

`backend/schema.sql` and `backend/schema_complete.sql` now contain the same
complete fresh-install schema, with 49
tables, keys, indexes, and the schedule effective-time trigger. It contains no
customer data, DROP TABLE operations or automatic data-purge jobs. Its transaction
refuses an existing AYANA schema before creating anything.

Six tables absent from the pasted base schema are included: `analytics_events`,
`app_migrations`, `billing_events`, `child_content_requests`,
`notification_attempts`, and `provider_receipts`.

Use this SQL only for a new empty database. Existing installations use the
startup DDL and versioned additive migrations through
`backend/services/migrations.py`, including migrations 010 and 011. Do not run
either fresh-install file against existing customer data. The old destructive
bootstrap has been replaced; existing tables and migrations are preserved.

Validation restores the fresh schema, compares every column and constraint
against the migrated local schema, and verifies a second run refuses safely.

## Production verification still required

The database reached through the local environment did not contain the supplied
account. Its contents therefore cannot establish that
account's verification, phone number, welcome or reply delivery history. The
correct Railway service/database must be identified before deploying or
repairing that account. No live family messages were sent by these tests.

The inspected Meta catalog differed from the pasted template descriptions.
Payload generation uses actual approved names, language codes and button
indexes in `backend/approved_templates.json`. In particular the inspected child
text-reply templates had no buttons. The child welcome templates were absent;
the current welcome implementation uses the available approved opener.

Templates do not open a 24-hour service window; an inbound recipient message
does. Approved templates can be submitted outside that window, but provider
delivery failures still need receipt handling. A successful submission alone
is never proof of delivery.

## Staff logins

Set `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `EMPLOYEE_EMAIL`, and `EMPLOYEE_PASSWORD`
in `backend/.env` locally, or in Railway service Variables in production.
Passwords are never stored in SQL or source files. Startup seeds/updates bcrypt
hashes and invalidates existing sessions when the password or role changes.
Restart/redeploy after changing variables. Startup also preserves deleted staff
accounts as deleted; restoring one requires an explicit separate action.

Environment values are authoritative: manually changing a hash in Supabase
will be overridden on the next startup if it differs from these values.
Never put a plain-text password in the `password_hash` column.

Admin uses `/admin`. Employee uses `/worker` with the existing `support` role.
Employee access is limited server-side to aggregate delivery status and their
own session information/logout. The worker page contains no customer names,
phone numbers, message contents, or write actions.

Staff credentials have been configured locally. Railway variables and production
accounts have not been changed because the production service is unidentified.

Staff validation: five backend access/password tests and the worker-page test
passed. Run `python tests/test_staff_access.py` and include
`src/pages/Worker.test.js` in the frontend test command above.
