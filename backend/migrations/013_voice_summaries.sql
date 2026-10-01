CREATE TABLE IF NOT EXISTS voice_summaries (
    reply_id uuid NOT NULL REFERENCES parent_replies(id) ON DELETE CASCADE,
    language text NOT NULL,
    summary text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(reply_id, language)
);
