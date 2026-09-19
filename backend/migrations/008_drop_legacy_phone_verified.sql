-- 008_drop_legacy_phone_verified.sql
-- Drops legacy phone-OTP columns that are no longer read anywhere in the codebase.
-- AYANA switched to email-only verification via services/verification.py; the
-- users.phone_verified / users.phone_verified_number columns remained as
-- zombie fields that are always false / NULL. Dropping them eliminates schema
-- drift between the codebase and the database.
--
-- Safe to run repeatedly: DROP COLUMN IF EXISTS is a no-op after the first run.
-- No data preserved because the values were never read.

ALTER TABLE users DROP COLUMN IF EXISTS phone_verified;
ALTER TABLE users DROP COLUMN IF EXISTS phone_verified_number;
