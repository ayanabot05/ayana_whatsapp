-- ============================================================================
-- 003_lifecycle_and_delivery.sql
-- Adds: WhatsApp delivery-status tracking (funnel), STT confidence, and the
-- monthly_reports.details column the report generator already writes to.
-- Idempotent — safe to run repeatedly.
-- ============================================================================

-- ── Delivery health funnel: persist Meta status callbacks per message ───────
-- message_logs.status stays 'sent'|'simulated'|'failed' (what WE did);
-- delivery_status tracks what META reported back: 'sent'|'delivered'|'read'|'failed'.
alter table message_logs add column if not exists delivery_status text;
alter table message_logs add column if not exists delivered_at    timestamptz;
alter table message_logs add column if not exists read_at         timestamptz;
create index if not exists idx_msglogs_delivery_status
    on message_logs(delivery_status) where delivery_status is not null;

-- ── Voice STT confidence (0.0-1.0) so the child sees how reliable the transcript is ──
alter table parent_replies add column if not exists stt_confidence double precision;

-- ── monthly_reports.details: per-day / per-category breakdown JSON ──────────
alter table monthly_reports add column if not exists details jsonb;
