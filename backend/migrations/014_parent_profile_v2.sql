-- 014_parent_profile_v2.sql
-- Parent profile v2 (handwritten plan, steps iv - vii):
--   (iv)  Parent details: country (drives the city dropdown + timezone),
--         nicknames collected up-front, "other parent" (Mom/Dad) name.
--   (v)   Personal details / quiet hours / family stories replaced by an
--         "Events & special dates" table (birthday, anniversary, special).
--   (vi)  Safety checks can be about the OTHER parent ("Did Dad reach home?"
--         asked to Parent 1). Stored per safety slot inside schedules.messages
--         as {"about": "self" | "other_parent"} - no column needed.
--   (vii) Vacation mode removed.
-- Idempotent: safe to run more than once.

-- ---------------------------------------------------------------- (iv)
ALTER TABLE public.parents ADD COLUMN IF NOT EXISTS country text NOT NULL DEFAULT 'IN';
ALTER TABLE public.parents DROP CONSTRAINT IF EXISTS chk_parents_country;
ALTER TABLE public.parents ADD CONSTRAINT chk_parents_country CHECK (country ~ '^[A-Z]{2}$');

-- ---------------------------------------------------------------- (v)
CREATE TABLE IF NOT EXISTS public.parent_special_dates (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    parent_id uuid NOT NULL REFERENCES public.parents(id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    kind text NOT NULL,
    title text,
    month smallint NOT NULL,
    day smallint NOT NULL,
    note text,
    send_time text NOT NULL DEFAULT '09:00',
    active boolean NOT NULL DEFAULT true,
    last_sent_year integer,
    last_sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_special_kind CHECK (kind IN ('birthday', 'anniversary', 'special')),
    CONSTRAINT chk_special_month CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT chk_special_day CHECK (day BETWEEN 1 AND 31),
    CONSTRAINT chk_special_title CHECK (title IS NULL OR char_length(title) <= 60),
    CONSTRAINT chk_special_note CHECK (note IS NULL OR char_length(note) <= 300),
    CONSTRAINT chk_special_time CHECK (send_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
);
CREATE INDEX IF NOT EXISTS idx_special_dates_parent ON public.parent_special_dates(parent_id);
CREATE INDEX IF NOT EXISTS idx_special_dates_due ON public.parent_special_dates(month, day) WHERE active;
-- Only one birthday and one anniversary per parent; "special" is unlimited (UI caps it).
CREATE UNIQUE INDEX IF NOT EXISTS uq_special_birthday ON public.parent_special_dates(parent_id) WHERE kind = 'birthday';
CREATE UNIQUE INDEX IF NOT EXISTS uq_special_anniversary ON public.parent_special_dates(parent_id) WHERE kind = 'anniversary';

-- Backfill existing MM-DD birthdays into the new table.
INSERT INTO public.parent_special_dates (parent_id, user_id, kind, month, day)
SELECT p.id, p.user_id, 'birthday', split_part(p.birthday, '-', 1)::smallint, split_part(p.birthday, '-', 2)::smallint
FROM public.parents p
WHERE p.birthday ~ '^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'
  AND NOT EXISTS (SELECT 1 FROM public.parent_special_dates s WHERE s.parent_id = p.id AND s.kind = 'birthday');

-- Family stories removed from the product.
ALTER TABLE public.parents DROP COLUMN IF EXISTS stories;

-- ---------------------------------------------------------------- (vi)
-- Existing safety slots default to "about the parent themselves".
UPDATE public.schedules s
SET messages = (
    SELECT jsonb_agg(
        CASE WHEN m->>'category' IN ('office_return','market_return','shopping_return','temple_return','outing_return')
                  AND NOT (m ? 'about')
             THEN m || '{"about":"self"}'::jsonb ELSE m END)
    FROM jsonb_array_elements(s.messages) m)
WHERE jsonb_typeof(s.messages) = 'array' AND jsonb_array_length(s.messages) > 0;

-- ---------------------------------------------------------------- (vii)
ALTER TABLE public.parents DROP CONSTRAINT IF EXISTS chk_vacation_format;
ALTER TABLE public.parents DROP COLUMN IF EXISTS vacation_start;
ALTER TABLE public.parents DROP COLUMN IF EXISTS vacation_end;
