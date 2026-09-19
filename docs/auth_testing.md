# AYANA authentication regression protocol

This application uses PostgreSQL/asyncpg, not MongoDB. Preserve its existing JWT,
HttpOnly cookies and CSRF contract. Do not apply generic provider examples that
switch databases, log reset links/codes, or introduce onscreen verification.

1. Read `memory/test_credentials.md` and verify APP_ENV=test and loopback
   `*_local` database before seeding or mutating any records.
2. Provider credentials are not available. Keep EMAIL_ENABLED=false and
   WHATSAPP_ENABLED=false in the running app. For real service-level tests,
   intercept email/Meta HTTP only inside pytest; record outgoing email codes in
   the test fixture, never expose them through app routes or logs.
3. Disabled email service must return the SAME 503 for known and unknown reset
   accounts. Enabled-service tests must prove generic responses, purpose/target
   binding, expiry, guessing/resend limits, one-use concurrent consumption.
4. Seed verified owner and unrelated-household fixtures with API-valid
   example.com emails. A new unverified account's 403 on profile changes is an
   intentional gate, not a reason to weaken verification.
5. Use preview URL from frontend/.env for browser/API ingress checks. Check
   login, cookies, `/auth/me`, CSRF, number change authorization and direct-profile
   bypass. Preserve an exact `/replies/:id` deep link through login.
6. Account email paths are POST `/api/profile/email/request` and
   `/api/profile/email/confirm`. Password change is POST `/api/auth/change-password`.
   Signup verification uses POST `/api/auth/email/request` and `/verify`.
7. Verify old-email challenges cannot change an account after its email changes;
   number-change proof must match the old number/email at commit time.
8. No production credentials, OTP sends, database writes, or payments permitted.