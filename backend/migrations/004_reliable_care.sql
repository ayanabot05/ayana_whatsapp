-- Additive only. Existing accounts, schedules, payments and replies are retained.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_required boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_changed_at timestamptz;
ALTER TABLE care_circle_siblings ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE care_circle_siblings ADD COLUMN IF NOT EXISTS email_verified_at timestamptz;
ALTER TABLE parents ADD COLUMN IF NOT EXISTS opted_out_at timestamptz;
ALTER TABLE message_logs ADD COLUMN IF NOT EXISTS event_key text;
CREATE INDEX IF NOT EXISTS idx_logs_event ON message_logs(event_key);
ALTER TABLE message_logs ADD COLUMN IF NOT EXISTS delivery_status text;
ALTER TABLE message_logs ADD COLUMN IF NOT EXISTS delivered_at timestamptz;
ALTER TABLE message_logs ADD COLUMN IF NOT EXISTS read_at timestamptz;
ALTER TABLE message_logs ADD COLUMN IF NOT EXISTS failed_at timestamptz;
CREATE TABLE IF NOT EXISTS care_watch (
  parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE, day_key text NOT NULL,
  first_warn_sent boolean NOT NULL DEFAULT false, main_warn_sent boolean NOT NULL DEFAULT false,
  last_reply_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(parent_id,day_key)
);
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS context_id text;
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS media_id text;
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS media_storage_path text;
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS media_content_type text;
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS message_log_id uuid REFERENCES message_logs(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS verification_challenges (
  id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose text NOT NULL, email text NOT NULL, target text NOT NULL,
  code_hash text NOT NULL, context jsonb NOT NULL DEFAULT '{}',
  attempts integer NOT NULL DEFAULT 0, delivered boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
  consumed_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_verification_rate ON verification_challenges(email, created_at);

CREATE TABLE IF NOT EXISTS recipient_sessions (
  phone text PRIMARY KEY, last_inbound_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS reply_notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reply_id uuid NOT NULL REFERENCES parent_replies(id) ON DELETE CASCADE,
  recipient_kind text NOT NULL CHECK (recipient_kind IN ('user','sibling')),
  recipient_id uuid NOT NULL, to_phone text, sid text,
  status text NOT NULL DEFAULT 'pending', detail text, error_code integer,
  attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
  email_status text, email_id text, audio_sid text, audio_status text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(reply_id, recipient_kind, recipient_id)
);
CREATE INDEX IF NOT EXISTS idx_notification_pending ON reply_notifications(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_notification_sid ON reply_notifications(sid);
CREATE TABLE IF NOT EXISTS inbound_events (
  wam_id text PRIMARY KEY, payload jsonb NOT NULL, status text NOT NULL DEFAULT 'pending',
  attempts integer NOT NULL DEFAULT 0, detail text, received_at timestamptz NOT NULL DEFAULT now(),
  next_attempt_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS welcome_deliveries (
  event_key text PRIMARY KEY, phone text NOT NULL, status text NOT NULL DEFAULT 'pending',
  sid text, detail text, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS care_send_claims (
  event_key text PRIMARY KEY, parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'sending', created_at timestamptz NOT NULL DEFAULT now(),
  attempts integer NOT NULL DEFAULT 0, sid text, detail text
);
-- Required for granular-only households. No bulk schedule backfill is performed.
CREATE TABLE IF NOT EXISTS parent_checkins (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
  category text NOT NULL, time text NOT NULL, is_active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS parent_health_reminders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
  category text NOT NULL, time text NOT NULL, is_active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS parent_routines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
  category text NOT NULL, time text NOT NULL, is_active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS medicines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
  name text NOT NULL, dosage text, shape text, colour text, food_timing text,
  reminder_times jsonb NOT NULL DEFAULT '[]', is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);