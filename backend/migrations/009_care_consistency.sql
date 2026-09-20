-- Additive repair only. Never infer historic medicine adherence from timestamps.
ALTER TABLE users ADD COLUMN IF NOT EXISTS needs_inbound_click boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS contact_version integer NOT NULL DEFAULT 0;
ALTER TABLE care_circle_siblings ADD COLUMN IF NOT EXISTS phone_changed_at timestamptz;
ALTER TABLE care_circle_siblings ADD COLUMN IF NOT EXISTS contact_version integer NOT NULL DEFAULT 0;
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS association_source text;
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS effects_applied_at timestamptz;
CREATE INDEX IF NOT EXISTS replies_context_parent ON parent_replies(parent_id,context_id);
CREATE INDEX IF NOT EXISTS logs_sid_parent ON message_logs(parent_id,sid);
UPDATE parent_replies r SET message_log_id=l.id,association_source='context'
  FROM message_logs l WHERE r.parent_id=l.parent_id AND r.context_id=l.sid
  AND r.context_id IS NOT NULL AND r.association_source IS DISTINCT FROM 'context';
ALTER TABLE message_logs ADD COLUMN IF NOT EXISTS medicine_id text;
ALTER TABLE welcome_deliveries ADD COLUMN IF NOT EXISTS payload jsonb NOT NULL DEFAULT '{}';
ALTER TABLE welcome_deliveries ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
ALTER TABLE welcome_deliveries ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE welcome_deliveries ADD COLUMN IF NOT EXISTS recipient_id uuid;
ALTER TABLE welcome_deliveries ADD COLUMN IF NOT EXISTS recipient_kind text;
ALTER TABLE welcome_deliveries ADD COLUMN IF NOT EXISTS contact_version integer NOT NULL DEFAULT 0;
ALTER TABLE reply_notifications ADD COLUMN IF NOT EXISTS audio_attempts integer NOT NULL DEFAULT 0;
ALTER TABLE reply_notifications ADD COLUMN IF NOT EXISTS audio_next_attempt_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE reply_notifications ADD COLUMN IF NOT EXISTS email_attempts integer NOT NULL DEFAULT 0;
ALTER TABLE reply_notifications ADD COLUMN IF NOT EXISTS email_next_attempt_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS media_attempts integer NOT NULL DEFAULT 0;
ALTER TABLE parent_replies ADD COLUMN IF NOT EXISTS media_next_attempt_at timestamptz NOT NULL DEFAULT now();
CREATE TABLE IF NOT EXISTS child_content_requests (
  wam_id text PRIMARY KEY, notification_id uuid NOT NULL REFERENCES reply_notifications(id) ON DELETE CASCADE,
  phone text NOT NULL, status text NOT NULL DEFAULT 'pending', attempts integer NOT NULL DEFAULT 0,
  sid text, next_attempt_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS notification_attempts (
  sid text PRIMARY KEY, notification_id uuid NOT NULL REFERENCES reply_notifications(id) ON DELETE CASCADE,
  phone text NOT NULL, status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO notification_attempts(sid,notification_id,phone,status)
  SELECT sid,id,to_phone,status FROM reply_notifications WHERE sid IS NOT NULL AND to_phone IS NOT NULL ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS provider_receipts (
  event_key text PRIMARY KEY, payload jsonb NOT NULL, processed_at timestamptz,
  received_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS billing_events (
  event_id text PRIMARY KEY, event_type text NOT NULL, payload jsonb NOT NULL DEFAULT '{}',
  processed_at timestamptz, detail text, received_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE billing_subscriptions ADD COLUMN IF NOT EXISTS provider_event_at timestamptz;
ALTER TABLE billing_orders ADD COLUMN IF NOT EXISTS credit integer NOT NULL DEFAULT 0 CHECK(credit>=0);
ALTER TABLE billing_orders ADD COLUMN IF NOT EXISTS credited_grant_id uuid REFERENCES access_grants(id);
DO $$ DECLARE c record; BEGIN
  FOR c IN SELECT conname FROM pg_constraint WHERE conrelid='billing_orders'::regclass AND contype='c'
    AND pg_get_constraintdef(oid) LIKE '%subtotal%discount%amount%'
  LOOP EXECUTE format('ALTER TABLE billing_orders DROP CONSTRAINT %I',c.conname); END LOOP;
END $$;
ALTER TABLE billing_orders ADD CONSTRAINT billing_order_amount_consistent CHECK(subtotal-discount-credit=amount);