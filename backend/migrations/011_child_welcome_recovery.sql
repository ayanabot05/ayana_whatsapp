-- The former child-only template was absent from the connected catalog.
-- Only known pre-submission configuration failures can safely be retried.
UPDATE welcome_deliveries
SET status='pending', attempts=0, next_attempt_at=now(), detail=NULL
WHERE recipient_kind='user' AND payload->>'purpose'='child'
  AND status='configuration_error' AND sid IS NULL
  AND detail LIKE 'Approved WhatsApp template unavailable: ayana_child_welcome_%';
