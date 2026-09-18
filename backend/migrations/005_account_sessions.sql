-- Existing tokens have implicit version zero and remain valid until an
-- account-specific password reset/change or verified email change occurs.
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version integer NOT NULL DEFAULT 0;