# AYANA backend — module ownership

Updated 19 September 2026. Stack: FastAPI + PostgreSQL/asyncpg; React frontend.

## Route extraction

The five requested routers now own their handlers and helper implementations;
they do **not** import `server.py`, use wildcard imports, or dynamically load it.

| Module | Responsibility |
| --- | --- |
| `routes/auth.py` | Register/login/me/logout/refresh, password change, profile email change, child profile, account deletion/audit |
| `routes/parents.py` | Parent CRUD, vacation, emergency contacts/events, language suggestions/updates, moments and signed image delivery |
| `routes/schedules.py` | Schedules, recovery mode, granular check-ins/health reminders/routines/medicines, daily check-in summaries |
| `routes/activation.py` | Activation and onboarding, consent/preferences, legacy payment state/checkout |
| `routes/webhook.py` | Meta handshake/ingress, payload processing, recording replies, button effects, receipts, legacy reply read/simulation routes |
| `routes/admin.py` | Previously extracted admin dashboards and delivery health |
| `routes/account.py` | Existing email verification/OTP recovery and contact-change endpoints |
| `routes/replies.py` | Existing newer reply/media/notification endpoints |
| `routes/care.py` | Existing care-circle sibling API |
| `routes/billing.py`, `routes/coupon_admin.py` | Subscription/billing API and admin coupons |
| `routes/sanity.py` | Admin welcome/fake-reply sanity tools |

### Wiring rules

- The five new routers have no prefix; `server.api` supplies `/api` exactly once.
- They are included where the corresponding legacy route groups were registered.
- Other self-prefixed routers retain their existing application registration order.
- `server.lifespan` explicitly gives `routes.webhook._process_meta_payload` to
  `services.inbox.configure`. The inbox worker never imports the application.
- Dashboard bootstrap explicitly imports the parent/schedule/activation/audit
  query handlers it reuses; those modules never import the dashboard.
- Existing overlaps between legacy reply routes and `routes/replies.py` are
  intentionally preserved, including their first-match precedence. Consolidating
  them is a separate API behaviour change, not part of this extraction.

## Shared modules

| Module | Purpose |
| --- | --- |
| `services/deps.py` | Household scope/membership, client IP/rate-limit adapter, asynchronous audit, plan access/usage/downgrade checks, medicine schedule synchronization |
| `auth.py` | Unchanged bcrypt, JWT, cookies, CSRF, current-user/admin dependencies, admin seed |
| `models.py`, `validation.py` | Unchanged request models and input rules |
| `database.py`, `schema.sql`, `services/migrations.py` | asyncpg pool, schema and numbered SQL migrations |
| `services/inbox.py` | Durable inbound enqueue/drain; receives processor callback at startup |
| `services/notifications.py`, `notification_transport.py` | Durable reply notifications and external delivery boundary |
| `services/welcomes.py` | Parent/child welcome language and idempotency |
| `services/delivery_stats.py` | Shared delivery funnel |
| `whatsapp.py`, `email_sender.py`, `storage.py` | Meta, Resend and object-storage adapters |
| `scheduler.py`, `medicine_sync.py`, `monthly_report.py` | Scheduled sends, reminder synchronization, reports |

## What remains in `server.py`

Application lifecycle, startup migrations, health/config/analytics, manual care
watch trigger, message logs/send-test/previews, legacy care-circle/invites,
monthly report endpoints, dashboard composition, CORS and middleware.

`server.py` has fallen from about 3,873 lines to about 1,100. It is not claimed
to be bootstrap-only: the remaining route groups are outside this five-module scope.

## Where to make common changes

- Parent added → `routes.parents.create_parent` → `services.welcomes`.
- Care activated → `routes.activation.activate` → `services.welcomes`.
- Child number changed → `routes/account.py` → `services.welcomes`.
- Parent replies → `routes.webhook._process_meta_payload` → `_record_reply`
  → `services.notifications.enqueue_reply` → notification transport.
- Add a template → `whatsapp.py`, with approval details in
  `docs/meta_approved_templates.txt`.
- Add an admin sanity action → `routes/sanity.py`.

## Regression gates

The user approved isolated, backend-only gates for each module. Tests live in
`tests/refactor/` at the repository root. Database/provider boundaries are
**MOCKED in tests only**; application integrations were not replaced.

Run from the repository root:

```bash
python -m pytest tests/refactor backend/tests/test_pricing_unit.py backend/tests/test_models_validation.py -v --tb=short
python -m pyflakes backend/server.py backend/routes/auth.py backend/routes/parents.py backend/routes/schedules.py backend/routes/activation.py backend/routes/webhook.py backend/services/deps.py
```

Durable JSON fixtures were captured from pre-extraction commit `b82a8b0`.
They cover route registration/dependencies, duplicate-route precedence, API
schema contracts and extracted handler signatures/bodies. Runtime tests do not
need the temporary original-server snapshot. Do not regenerate baselines from
the refactored implementation to hide a regression.

Reports are under `test_reports/iteration_21.json` onwards, one gate per module.
Some historical `backend/tests` files still target the retired Mongo `server.db`
interface or require live services; they are not the isolated refactor gate.

## Live configuration limitation

This fork has no application `.env` files, live database credentials, preview
URL, admin login or provider credentials. No live DB migrations, actual Meta
delivery, Resend emails, storage, or paid checkout were verified. Supply the
existing application's configuration separately for live verification; see
`memory/test_credentials.md` for the test-only fixture distinction.

Database configuration is `SUPABASE_DB_URL` or `DATABASE_URL` for the existing
PostgreSQL application, not MongoDB. JWT/admin, Meta, Resend, billing and storage
variables remain unchanged by this refactor.