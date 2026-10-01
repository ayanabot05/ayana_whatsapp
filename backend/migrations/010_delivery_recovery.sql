-- Only definitively rejected, recent notifications are eligible for replay.
-- Never replay an accepted, delivered, or uncertain submission.
UPDATE reply_notifications n
SET status='pending', attempts=0, next_attempt_at=now(), detail=NULL
FROM parent_replies r
WHERE r.id=n.reply_id AND r.created_at>now()-interval '24 hours'
  AND n.status='failed' AND n.error_code IN (132000,132001,132012);

-- A saved or resumed schedule starts from that point, never earlier in the day.
ALTER TABLE schedules ADD COLUMN IF NOT EXISTS effective_from timestamptz;
UPDATE schedules SET effective_from=created_at WHERE effective_from IS NULL;
ALTER TABLE schedules ALTER COLUMN effective_from SET DEFAULT now();

CREATE OR REPLACE FUNCTION care_schedule_effective_from() RETURNS trigger AS $$
BEGIN
  IF NEW.messages IS DISTINCT FROM OLD.messages OR (NEW.active AND NOT OLD.active) THEN
    NEW.effective_from := now();
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS care_schedule_effective_from ON schedules;
CREATE TRIGGER care_schedule_effective_from BEFORE UPDATE ON schedules
  FOR EACH ROW EXECUTE FUNCTION care_schedule_effective_from();
