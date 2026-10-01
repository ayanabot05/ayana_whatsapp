CREATE TABLE IF NOT EXISTS family_notifications (
    event_key text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    kind text NOT NULL,
    recipient_kind text NOT NULL,
    recipient_id uuid NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    sid text,
    to_phone text,
    detail text,
    email_status text,
    email_attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS family_notifications_sid ON family_notifications(sid) WHERE sid IS NOT NULL;
CREATE TABLE IF NOT EXISTS monthly_report_jobs (
    parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    period text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    detail text,
    PRIMARY KEY(parent_id, period)
);
CREATE TABLE IF NOT EXISTS parent_delivery_alerts (
    parent_id uuid NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    day_key text NOT NULL,
    failures integer NOT NULL,
    detail text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(parent_id, day_key)
);
