-- ============================================================================
-- AYANA · Migration 002 · Schema-drift fix (Mongo → Supabase completion)
-- ============================================================================
-- WHY: The initial schema.sql shipped with a simplified column set from an
--      early Mongo→Postgres port. The codebase since evolved (onboarding
--      step tracking, phone verification, rich WhatsApp sessions, language
--      auto-detect, moments, care circle, emergency events, etc.), but
--      schema.sql was never resynced. Result: every /api/auth/register call
--      currently 500s on "column onboarding_step does not exist" and 12
--      other tables have downstream drift.
--
-- HOW TO RUN:
--   1. Open Supabase Dashboard → SQL Editor
--   2. Paste this ENTIRE file
--   3. Click "Run"
--   4. Scroll to the bottom — you should see "MIGRATION 002 OK" as the last row
--
-- SAFETY:
--   - Everything is IF NOT EXISTS or ALTER … ADD COLUMN IF NOT EXISTS —
--     idempotent, safe to run twice.
--   - No data is destroyed. One RENAME (phone_otps.otp_hash → code_hash)
--     is guarded with a check for the current column name.
--   - Wrapped in a transaction. Either everything applies, or nothing does.
-- ============================================================================

begin;

-- ── 1. users ────────────────────────────────────────────────────────────────
-- Adds:
--   onboarding_step        int  -- 0..5, wizard progress (used by frontend)
--   phone_verified         bool -- Twilio OTP passed
--   phone_verified_number  text -- E.164 of verified number
--   preferences            jsonb -- per-user prefs blob (email nudges, etc.)
alter table users add column if not exists onboarding_step       integer     not null default 0;
alter table users add column if not exists phone_verified        boolean     not null default false;
alter table users add column if not exists phone_verified_number text;
alter table users add column if not exists preferences           jsonb       not null default '{}'::jsonb;

-- ── 2. circle_invites ───────────────────────────────────────────────────────
-- Code uses `owner_id` (the inviter's user_id) alongside the invited email.
-- The original `user_id` column is now redundant with `owner_id` but harmless
-- to keep; we make it nullable so new invites can populate `owner_id` only.
alter table circle_invites add column if not exists owner_id     uuid references users(id) on delete cascade;
alter table circle_invites add column if not exists accepted_at  timestamptz;
alter table circle_invites add column if not exists member_id    uuid references users(id) on delete set null;
alter table circle_invites add column if not exists inviter_name text;
alter table circle_invites add column if not exists parent_id    uuid references parents(id) on delete set null;
-- Existing rows (if any) — copy user_id -> owner_id so they don't orphan.
update circle_invites set owner_id = user_id where owner_id is null and user_id is not null;
alter table circle_invites alter column user_id drop not null;
create index if not exists idx_circleinvites_owner_status on circle_invites(owner_id, status);
create index if not exists idx_circleinvites_email_status on circle_invites(email, status);

-- ── 3. phone_otps ───────────────────────────────────────────────────────────
-- Code uses `code_hash`, `verified`, `verified_at`, `send_count`,
-- `send_window_start`. Original schema had `otp_hash` only.
do $$
begin
    if exists (select 1 from information_schema.columns
                where table_name = 'phone_otps' and column_name = 'otp_hash')
       and not exists (select 1 from information_schema.columns
                        where table_name = 'phone_otps' and column_name = 'code_hash') then
        alter table phone_otps rename column otp_hash to code_hash;
    end if;
end $$;
alter table phone_otps add column if not exists code_hash          text;
alter table phone_otps add column if not exists verified           boolean     not null default false;
alter table phone_otps add column if not exists verified_at        timestamptz;
alter table phone_otps add column if not exists send_count         integer     not null default 0;
alter table phone_otps add column if not exists send_window_start  timestamptz;

-- ── 4. parents ──────────────────────────────────────────────────────────────
-- Language auto-detect writes these when parent's reply script differs from
-- their configured language, so the child can suggest switching.
alter table parents add column if not exists detected_language        text;
alter table parents add column if not exists language_suggestion      text;
alter table parents add column if not exists language_suggestion_at   timestamptz;

-- ── 5. schedules ────────────────────────────────────────────────────────────
-- Raksha recovery-mode auto-expiry archives the extra reminders here instead
-- of deleting them, so child can review after recovery period ends.
alter table schedules add column if not exists archived_recovery_messages jsonb not null default '[]'::jsonb;

-- ── 6. wa_sessions ──────────────────────────────────────────────────────────
-- Rich session tracking: know when 24h Meta window last opened, what was
-- last sent (template vs interactive), when reengagement fired.
alter table wa_sessions add column if not exists last_inbound_at      timestamptz;
alter table wa_sessions add column if not exists last_outbound_at     timestamptz;
alter table wa_sessions add column if not exists last_activity        timestamptz;
alter table wa_sessions add column if not exists last_template_type   text;
alter table wa_sessions add column if not exists session_open         boolean not null default false;
alter table wa_sessions add column if not exists reengagement_sent_at timestamptz;
create index if not exists idx_wasessions_session_open on wa_sessions(session_open) where session_open = true;

-- ── 7. message_logs ─────────────────────────────────────────────────────────
-- Scheduler writes body text + Meta message SID for correlation + reply
-- status (delivered/read/failed) as callbacks arrive.
alter table message_logs add column if not exists body         text;
alter table message_logs add column if not exists detail       text;
alter table message_logs add column if not exists sid          text;
alter table message_logs add column if not exists reply_status text;
create index if not exists idx_msglogs_sid on message_logs(sid) where sid is not null;

-- ── 8. parent_replies ───────────────────────────────────────────────────────
-- This table gets the biggest catch-up: every field the webhook handler
-- needs to persist a reply (raw payload for audit, button payload, voice
-- transcription, ML distress score, matched keywords, etc.).
alter table parent_replies add column if not exists user_id             uuid references users(id) on delete cascade;
alter table parent_replies add column if not exists from_phone          text;
alter table parent_replies add column if not exists body                text;
alter table parent_replies add column if not exists button_payload      text;
alter table parent_replies add column if not exists feeling             text;
alter table parent_replies add column if not exists media_url           text;
alter table parent_replies add column if not exists transcription       text;
alter table parent_replies add column if not exists emergency_keywords  jsonb not null default '[]'::jsonb;
alter table parent_replies add column if not exists ml_flagged          boolean not null default false;
alter table parent_replies add column if not exists ml_score            double precision;
alter table parent_replies add column if not exists raw_payload         jsonb not null default '{}'::jsonb;
create index if not exists idx_parentreplies_user_created on parent_replies(user_id, created_at desc);

-- ── 9. emergency_events ─────────────────────────────────────────────────────
-- Child triage flow: intent, matched keywords, resolution notes, who
-- resolved it, soft-delete.
alter table emergency_events add column if not exists intent           text;
alter table emergency_events add column if not exists is_voice         boolean not null default false;
alter table emergency_events add column if not exists body             text;
alter table emergency_events add column if not exists keywords         jsonb not null default '[]'::jsonb;
alter table emergency_events add column if not exists phone            text;
alter table emergency_events add column if not exists resolution_note  text;
alter table emergency_events add column if not exists resolved_by      uuid references users(id) on delete set null;
alter table emergency_events add column if not exists deleted_at       timestamptz;
create index if not exists idx_emergencyevents_open on emergency_events(status, created_at desc) where status = 'open';

-- ── 10. moments (child → parent) ────────────────────────────────────────────
-- Legacy single image_url + new plural image_urls, plus who sent it and
-- delivery status.
alter table moments add column if not exists image_url    text;
alter table moments add column if not exists image_urls   jsonb  not null default '[]'::jsonb;
alter table moments add column if not exists sender_name  text;
alter table moments add column if not exists status       text   not null default 'pending';

-- ── 11. moment_images ───────────────────────────────────────────────────────
alter table moment_images add column if not exists user_id      uuid references users(id) on delete cascade;
alter table moment_images add column if not exists filename     text;
alter table moment_images add column if not exists size         bigint;
alter table moment_images add column if not exists content_type text;
alter table moment_images add column if not exists is_deleted   boolean not null default false;

-- ── 12. consent_logs ────────────────────────────────────────────────────────
-- Audit compliance: capture IP at consent capture for DPDP-style traceability.
alter table consent_logs add column if not exists ip text;

-- ── 13. audit_logs ──────────────────────────────────────────────────────────
-- schema.sql already has both `meta` and `detail` — nothing to add, just
-- confirm the index exists.
create index if not exists idx_auditlogs_action on audit_logs(action, created_at desc);

-- ── VALIDATION ──────────────────────────────────────────────────────────────
-- If any of these fail, the transaction rolls back and nothing is applied.
do $$
declare
    missing text;
begin
    -- Sample the most critical additions
    select string_agg(t || '.' || c, ', ')
    into   missing
    from   (values
        ('users','onboarding_step'),
        ('users','phone_verified'),
        ('circle_invites','owner_id'),
        ('phone_otps','code_hash'),
        ('phone_otps','verified'),
        ('wa_sessions','session_open'),
        ('wa_sessions','last_inbound_at'),
        ('schedules','archived_recovery_messages'),
        ('parent_replies','user_id'),
        ('parent_replies','raw_payload'),
        ('emergency_events','intent'),
        ('moments','image_urls')
    ) as required(t, c)
    where not exists (
        select 1 from information_schema.columns
        where table_name = required.t and column_name = required.c
    );
    if missing is not null then
        raise exception 'MIGRATION 002 FAILED — still missing: %', missing;
    end if;
end $$;

commit;

-- ── Sanity readback ─────────────────────────────────────────────────────────
select 'MIGRATION 002 OK · ' || now()::text as status;
