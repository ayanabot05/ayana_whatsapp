# Authentication extraction regression gate

The supplied generic authentication playbook is for a new MongoDB application. This existing application uses PostgreSQL/asyncpg and mature JWT/cookie helpers; do not replace its database, token lifetimes, or authentication semantics during extraction.

## Testing playbook

1. Database verification: validate existing password hashing and user lookup behaviour against isolated asyncpg test doubles. Live database, index and admin-seeding verification is blocked until configuration is supplied. Do not run MongoDB commands against this PostgreSQL application.
2. API testing: exercise register/login, cookies, `/api/auth/me`, refresh, logout, password changes, email OTP request/confirmation, household membership and CSRF checks through ASGI/TestClient. Preserve the existing paths, schemas, response fields and dependency identities.
3. Mock only external boundaries (database, Redis, email, WhatsApp). Keep real request validation, JWT signing/verification, bcrypt, serialization and cookie handling in regression tests.
4. Compare route manifests/OpenAPI against `/tmp/ayana-server-before-refactor.py` (also recoverable from git commit `b82a8b0`). Record pre-existing route overlaps separately; do not introduce new overlaps or reorder overlapping handlers.
5. No live credentials exist. Read `memory/test_credentials.md`. Clearly label isolated coverage and live configuration limitations in each report.