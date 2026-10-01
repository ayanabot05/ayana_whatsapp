-- DESTRUCTIVE: permanently deletes ALL AYANA account, parent, billing,
-- message, reply, report and delivery data, then recreates the latest schema.
-- Export a backup first. Stop the backend/scheduler before running this file.
-- Run the ENTIRE file in the target database's SQL editor as its owner.
-- No passwords are embedded. Restart the backend afterwards to seed staff
-- accounts from ADMIN_EMAIL/ADMIN_PASSWORD and EMPLOYEE_EMAIL/EMPLOYEE_PASSWORD.
-- Only known AYANA public tables are targeted; Supabase auth/storage are untouched.
-- No CASCADE: unexpected external dependencies cause a rollback, not their deletion.
BEGIN;
SET LOCAL lock_timeout = '15s';

-- Retire the obsolete AYANA retention job if this database installed pg_cron.
DO $$ BEGIN
  IF to_regclass('cron.job') IS NOT NULL THEN
    EXECUTE 'SELECT cron.unschedule(jobid) FROM cron.job WHERE jobname = ''ayana-nightly-purge''';
  END IF;
END $$;
DROP FUNCTION IF EXISTS public.purge_expired_data();

DROP TABLE IF EXISTS
    public.access_grants,
    public.activation_state,
    public.analytics_events,
    public.app_migrations,
    public.audit_logs,
    public.billing_coupons,
    public.billing_events,
    public.billing_orders,
    public.billing_plans,
    public.billing_subscriptions,
    public.care_circle_siblings,
    public.care_send_claims,
    public.care_watch,
    public.child_content_requests,
    public.circle_invites,
    public.consent_logs,
    public.distress_logs,
    public.email_otps,
    public.emergency_events,
    public.escalation_daily,
    public.escalation_state,
    public.family_notifications,
    public.inbound_events,
    public.jwt_blacklist,
    public.medicines,
    public.message_logs,
    public.moment_images,
    public.moments,
    public.monthly_report_jobs,
    public.monthly_reports,
    public.notification_attempts,
    public.parent_checkins,
    public.parent_delivery_alerts,
    public.parent_health_reminders,
    public.parent_replies,
    public.parent_routines,
    public.parents,
    public.payment_state,
    public.payment_transactions,
    public.phone_otps,
    public.preferences,
    public.provider_receipts,
    public.recipient_sessions,
    public.reply_notifications,
    public.scheduler_locks,
    public.schedules,
    public.template_variants_cache,
    public.users,
    public.verification_challenges,
    public.wa_sessions,
    public.webhook_debug,
    public.welcome_deliveries;

DROP FUNCTION IF EXISTS public.care_schedule_effective_from();

-- PostgreSQL database dump
--


-- Dumped from database version 18.1
-- Dumped by pg_dump version 18.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: care_schedule_effective_from(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.care_schedule_effective_from() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.messages IS DISTINCT FROM OLD.messages OR (NEW.active AND NOT OLD.active) THEN
    NEW.effective_from := now();
  END IF;
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_grants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    order_id uuid NOT NULL,
    plan text NOT NULL,
    starts_at timestamp with time zone NOT NULL,
    ends_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: activation_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activation_state (
    user_id uuid NOT NULL,
    whatsapp_activated boolean DEFAULT false NOT NULL,
    activated_at timestamp with time zone
);


--
-- Name: analytics_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.analytics_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    type text,
    name text,
    page text,
    path text,
    lang text,
    session_id text,
    meta jsonb,
    ip text,
    user_agent text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: app_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_migrations (
    name text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    action text NOT NULL,
    meta jsonb,
    detail jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: billing_coupons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_coupons (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    label text NOT NULL,
    code_hash text NOT NULL,
    code_hint text NOT NULL,
    kind text NOT NULL,
    percent integer NOT NULL,
    allowed_email text,
    active boolean DEFAULT false NOT NULL,
    reserved_by uuid,
    reserved_order_id uuid,
    redeemed_by uuid,
    redeemed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT billing_coupons_kind_check CHECK ((kind = ANY (ARRAY['lifetime'::text, 'annual_discount'::text]))),
    CONSTRAINT billing_coupons_percent_check CHECK (((percent >= 1) AND (percent <= 100)))
);


--
-- Name: billing_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_events (
    event_id text NOT NULL,
    event_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    processed_at timestamp with time zone,
    detail text,
    received_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: billing_orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_orders (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    idempotency_key uuid NOT NULL,
    plan text NOT NULL,
    billing text NOT NULL,
    currency text NOT NULL,
    subtotal integer NOT NULL,
    discount integer NOT NULL,
    amount integer NOT NULL,
    coupon_id uuid,
    status text DEFAULT 'creating'::text NOT NULL,
    gateway_order_id text,
    gateway_payment_id text,
    is_test boolean NOT NULL,
    detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    verified_at timestamp with time zone,
    credit integer DEFAULT 0 NOT NULL,
    credited_grant_id uuid,
    CONSTRAINT billing_order_amount_consistent CHECK ((((subtotal - discount) - credit) = amount)),
    CONSTRAINT billing_orders_amount_check CHECK ((amount >= 0)),
    CONSTRAINT billing_orders_billing_check CHECK ((billing = ANY (ARRAY['month'::text, 'year'::text]))),
    CONSTRAINT billing_orders_credit_check CHECK ((credit >= 0)),
    CONSTRAINT billing_orders_discount_check CHECK ((discount >= 0)),
    CONSTRAINT billing_orders_subtotal_check CHECK ((subtotal >= 100))
);


--
-- Name: billing_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_plans (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    plan text NOT NULL,
    billing text NOT NULL,
    currency text NOT NULL,
    amount integer NOT NULL,
    gateway_plan_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT billing_plans_amount_check CHECK ((amount >= 100)),
    CONSTRAINT billing_plans_billing_check CHECK ((billing = ANY (ARRAY['month'::text, 'year'::text])))
);


--
-- Name: billing_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_subscriptions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    billing_plan_id uuid NOT NULL,
    gateway_subscription_id text NOT NULL,
    plan text NOT NULL,
    billing text NOT NULL,
    currency text NOT NULL,
    amount integer NOT NULL,
    coupon_id uuid,
    status text DEFAULT 'created'::text NOT NULL,
    current_period_start timestamp with time zone,
    current_period_end timestamp with time zone,
    cancel_at_period_end boolean DEFAULT false NOT NULL,
    cancelled_at timestamp with time zone,
    latest_grant_id uuid,
    is_test boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_event_at timestamp with time zone,
    CONSTRAINT billing_subscriptions_billing_check CHECK ((billing = ANY (ARRAY['month'::text, 'year'::text])))
);


--
-- Name: care_circle_siblings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.care_circle_siblings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    name text NOT NULL,
    phone text NOT NULL,
    language text DEFAULT 'en'::text NOT NULL,
    relation text DEFAULT 'sibling'::text NOT NULL,
    email text,
    email_verified_at timestamp with time zone,
    verified boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    phone_changed_at timestamp with time zone,
    contact_version integer DEFAULT 0 NOT NULL
);


--
-- Name: care_send_claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.care_send_claims (
    event_key text NOT NULL,
    parent_id uuid NOT NULL,
    status text DEFAULT 'sending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    sid text,
    detail text
);


--
-- Name: care_watch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.care_watch (
    parent_id uuid NOT NULL,
    day_key text NOT NULL,
    first_warn_sent boolean DEFAULT false NOT NULL,
    main_warn_sent boolean DEFAULT false NOT NULL,
    last_reply_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: child_content_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.child_content_requests (
    wam_id text NOT NULL,
    notification_id uuid NOT NULL,
    phone text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    sid text,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: circle_invites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.circle_invites (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid,
    user_id uuid,
    member_id uuid,
    parent_id uuid,
    email text NOT NULL,
    token text NOT NULL,
    inviter_name text,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    accepted_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    CONSTRAINT circle_invites_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'accepted'::text, 'cancelled'::text])))
);


--
-- Name: consent_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consent_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    parent_id uuid,
    consent_type text NOT NULL,
    agreed boolean NOT NULL,
    text text,
    ip text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT consent_logs_consent_type_check CHECK ((consent_type = ANY (ARRAY['child'::text, 'parent'::text])))
);


--
-- Name: distress_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.distress_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid NOT NULL,
    transcript text,
    language text,
    keyword_matches jsonb DEFAULT '[]'::jsonb NOT NULL,
    ml_score double precision,
    keyword_emergency boolean DEFAULT false NOT NULL,
    ml_flagged boolean DEFAULT false NOT NULL,
    outcome text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: email_otps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_otps (
    email text NOT NULL,
    code_hash text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    verified boolean DEFAULT false NOT NULL,
    verified_at timestamp with time zone,
    send_count integer DEFAULT 0 NOT NULL,
    send_window_start timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL
);


--
-- Name: emergency_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.emergency_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    parent_id uuid NOT NULL,
    source text,
    detail text,
    intent text,
    is_voice boolean DEFAULT false NOT NULL,
    body text,
    keywords jsonb DEFAULT '[]'::jsonb NOT NULL,
    phone text,
    status text DEFAULT 'open'::text NOT NULL,
    resolution_note text,
    resolved_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    deleted_at timestamp with time zone,
    CONSTRAINT emergency_events_status_check CHECK ((status = ANY (ARRAY['open'::text, 'resolved'::text, 'false_positive'::text])))
);


--
-- Name: escalation_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.escalation_daily (
    marker text NOT NULL,
    at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: escalation_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.escalation_state (
    id text NOT NULL,
    parent_id uuid NOT NULL,
    user_id uuid NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_attempt_at timestamp with time zone,
    kind text,
    day_key text,
    first_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: family_notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.family_notifications (
    event_key text NOT NULL,
    user_id uuid NOT NULL,
    parent_id uuid NOT NULL,
    kind text NOT NULL,
    recipient_kind text NOT NULL,
    recipient_id uuid NOT NULL,
    payload jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    sid text,
    to_phone text,
    detail text,
    email_status text,
    email_attempts integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: inbound_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inbound_events (
    wam_id text NOT NULL,
    payload jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    detail text,
    received_at timestamp with time zone DEFAULT now() NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: jwt_blacklist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jwt_blacklist (
    jti text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: medicines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.medicines (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid NOT NULL,
    name text NOT NULL,
    dosage text,
    shape text,
    colour text,
    food_timing text,
    reminder_times jsonb DEFAULT '[]'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: message_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    parent_id uuid NOT NULL,
    schedule_id uuid,
    day_key text NOT NULL,
    message_index integer,
    category text,
    msg_type text,
    status text,
    skipped boolean DEFAULT false NOT NULL,
    escalation_of uuid,
    attempt integer,
    kind text,
    body text,
    detail text,
    sid text,
    reply_status text,
    delivery_status text,
    delivered_at timestamp with time zone,
    read_at timestamp with time zone,
    failed_at timestamp with time zone,
    event_key text,
    slot_time text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    medicine_id text
);


--
-- Name: moment_images; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.moment_images (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    moment_id uuid,
    user_id uuid,
    storage_path text NOT NULL,
    filename text,
    size bigint,
    content_type text,
    is_deleted boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: moments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.moments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    parent_id uuid NOT NULL,
    text text,
    image_url text,
    image_urls jsonb DEFAULT '[]'::jsonb NOT NULL,
    sender_name text,
    status text DEFAULT 'pending'::text NOT NULL,
    sid text,
    delivery_status text,
    delivery_notified boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: monthly_report_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.monthly_report_jobs (
    parent_id uuid NOT NULL,
    period text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    detail text
);


--
-- Name: monthly_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.monthly_reports (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    parent_id uuid NOT NULL,
    plan text,
    period text NOT NULL,
    total_touches integer DEFAULT 0 NOT NULL,
    delivered integer DEFAULT 0 NOT NULL,
    skipped integer DEFAULT 0 NOT NULL,
    voice_replies integer DEFAULT 0 NOT NULL,
    mood_graph jsonb,
    trend_note text,
    shared_with_care_circle boolean DEFAULT false NOT NULL,
    generated_at timestamp with time zone DEFAULT now() NOT NULL,
    details jsonb,
    pdf_url text
);


--
-- Name: notification_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_attempts (
    sid text NOT NULL,
    notification_id uuid NOT NULL,
    phone text NOT NULL,
    status text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: parent_checkins; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parent_checkins (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid NOT NULL,
    category text NOT NULL,
    "time" text NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: parent_delivery_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parent_delivery_alerts (
    parent_id uuid NOT NULL,
    day_key text NOT NULL,
    failures integer NOT NULL,
    detail text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: parent_health_reminders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parent_health_reminders (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid NOT NULL,
    category text NOT NULL,
    "time" text NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: parent_replies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parent_replies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid NOT NULL,
    user_id uuid,
    intent text,
    text text,
    from_phone text,
    body text,
    button_payload text,
    feeling text,
    media_url text,
    transcription text,
    is_voice boolean DEFAULT false NOT NULL,
    emergency_keywords jsonb DEFAULT '[]'::jsonb NOT NULL,
    ml_flagged boolean DEFAULT false NOT NULL,
    ml_score double precision,
    stt_confidence double precision,
    raw_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    wam_id text,
    context_id text,
    media_id text,
    media_storage_path text,
    media_content_type text,
    message_log_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone,
    association_source text,
    effects_applied_at timestamp with time zone,
    media_attempts integer DEFAULT 0 NOT NULL,
    media_next_attempt_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: parent_routines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parent_routines (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid NOT NULL,
    category text NOT NULL,
    "time" text NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: parents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name text NOT NULL,
    preferred_name text,
    relationship text NOT NULL,
    phone text NOT NULL,
    language text DEFAULT 'en'::text NOT NULL,
    timezone text DEFAULT 'Asia/Kolkata'::text NOT NULL,
    city text,
    other_parent_name text,
    notes text,
    birthday text,
    nicknames jsonb DEFAULT '[]'::jsonb NOT NULL,
    habits jsonb,
    medicine_list jsonb DEFAULT '[]'::jsonb NOT NULL,
    stories jsonb DEFAULT '[]'::jsonb NOT NULL,
    activity_window_start text DEFAULT '06:00'::text,
    activity_window_end text DEFAULT '22:00'::text,
    auto_activity_detection boolean DEFAULT false NOT NULL,
    detected_language text,
    language_suggestion text,
    language_suggestion_at timestamp with time zone,
    emergency_contacts jsonb DEFAULT '[]'::jsonb NOT NULL,
    recovery_mode boolean DEFAULT false NOT NULL,
    recovery_until timestamp with time zone,
    vacation_start text,
    vacation_end text,
    opted_out_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT chk_vacation_format CHECK ((((vacation_start IS NULL) OR (vacation_start ~ '^\d{4}-\d{2}-\d{2}$'::text)) AND ((vacation_end IS NULL) OR (vacation_end ~ '^\d{4}-\d{2}-\d{2}$'::text)))),
    CONSTRAINT chk_window_format CHECK ((((activity_window_start IS NULL) OR (activity_window_start ~ '^[0-2][0-9]:[0-5][0-9]$'::text)) AND ((activity_window_end IS NULL) OR (activity_window_end ~ '^[0-2][0-9]:[0-5][0-9]$'::text)))),
    CONSTRAINT chk_window_width CHECK (((activity_window_start IS NULL) OR (activity_window_end IS NULL) OR (activity_window_start <> activity_window_end))),
    CONSTRAINT parents_relationship_check CHECK ((relationship = ANY (ARRAY['mother'::text, 'father'::text])))
);


--
-- Name: payment_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_state (
    user_id uuid NOT NULL,
    status text,
    plan text,
    billing text,
    billing_managed boolean DEFAULT false NOT NULL,
    trial_started_at timestamp with time zone,
    trial_ends_at timestamp with time zone,
    legacy_paid_plan text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: payment_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_transactions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id text NOT NULL,
    user_id uuid NOT NULL,
    plan text,
    billing text,
    amount numeric(10,2),
    currency text,
    status text,
    payment_status text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: phone_otps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.phone_otps (
    phone text NOT NULL,
    code_hash text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    verified boolean DEFAULT false NOT NULL,
    verified_at timestamp with time zone,
    send_count integer DEFAULT 0 NOT NULL,
    send_window_start timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL
);


--
-- Name: preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.preferences (
    user_id uuid NOT NULL,
    emergency_keywords jsonb DEFAULT '[]'::jsonb NOT NULL,
    daily_summary boolean DEFAULT true NOT NULL,
    email_notifications boolean DEFAULT true NOT NULL,
    whatsapp_reports boolean DEFAULT true NOT NULL
);


--
-- Name: provider_receipts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.provider_receipts (
    event_key text NOT NULL,
    payload jsonb NOT NULL,
    processed_at timestamp with time zone,
    received_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: recipient_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recipient_sessions (
    phone text NOT NULL,
    last_inbound_at timestamp with time zone NOT NULL
);


--
-- Name: reply_notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reply_notifications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    reply_id uuid NOT NULL,
    recipient_kind text NOT NULL,
    recipient_id uuid NOT NULL,
    to_phone text,
    sid text,
    status text DEFAULT 'pending'::text NOT NULL,
    detail text,
    error_code integer,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    email_status text,
    email_id text,
    audio_sid text,
    audio_status text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    audio_attempts integer DEFAULT 0 NOT NULL,
    audio_next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    email_attempts integer DEFAULT 0 NOT NULL,
    email_next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT reply_notifications_recipient_kind_check CHECK ((recipient_kind = ANY (ARRAY['user'::text, 'sibling'::text])))
);


--
-- Name: scheduler_locks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduler_locks (
    lock_name text NOT NULL,
    holder text,
    acquired_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL
);


--
-- Name: schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schedules (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid NOT NULL,
    user_id uuid NOT NULL,
    mode text DEFAULT 'nitya'::text NOT NULL,
    messages jsonb DEFAULT '[]'::jsonb NOT NULL,
    active boolean DEFAULT true NOT NULL,
    recovery_mode boolean DEFAULT false NOT NULL,
    recovery_until text,
    reengagement_hours integer DEFAULT 4 NOT NULL,
    archived_recovery_messages jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    effective_from timestamp with time zone DEFAULT now(),
    CONSTRAINT schedules_mode_check CHECK ((mode = ANY (ARRAY['nitya'::text, 'bandham'::text, 'raksha'::text])))
);


--
-- Name: template_variants_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.template_variants_cache (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    category text NOT NULL,
    language text NOT NULL,
    variants jsonb NOT NULL,
    source text,
    generated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    email text NOT NULL,
    phone text NOT NULL,
    password_hash text NOT NULL,
    role text DEFAULT 'user'::text NOT NULL,
    onboarding_complete boolean DEFAULT false NOT NULL,
    onboarding_step integer DEFAULT 0 NOT NULL,
    preferences jsonb DEFAULT '{}'::jsonb NOT NULL,
    password_changed_at timestamp with time zone,
    pending_email text,
    city text,
    timezone text DEFAULT 'Asia/Kolkata'::text NOT NULL,
    household_owner_id uuid,
    email_verified_at timestamp with time zone,
    email_verification_required boolean DEFAULT false NOT NULL,
    phone_changed_at timestamp with time zone,
    auth_version integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    needs_inbound_click boolean DEFAULT false NOT NULL,
    contact_version integer DEFAULT 0 NOT NULL,
    CONSTRAINT users_role_check CHECK ((role = ANY (ARRAY['user'::text, 'admin'::text, 'support'::text])))
);


--
-- Name: verification_challenges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.verification_challenges (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    purpose text NOT NULL,
    email text NOT NULL,
    target text NOT NULL,
    code_hash text NOT NULL,
    context jsonb DEFAULT '{}'::jsonb NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    delivered boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone
);


--
-- Name: wa_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wa_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid NOT NULL,
    opener_sent_at timestamp with time zone,
    reengagement_sent boolean DEFAULT false NOT NULL,
    reengagement_sent_at timestamp with time zone,
    last_inbound_at timestamp with time zone,
    last_outbound_at timestamp with time zone,
    last_activity timestamp with time zone,
    last_template_type text,
    session_open boolean DEFAULT false NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: webhook_debug; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_debug (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    direction text DEFAULT 'inbound'::text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: welcome_deliveries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.welcome_deliveries (
    event_key text NOT NULL,
    phone text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    sid text,
    detail text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    recipient_id uuid,
    recipient_kind text,
    contact_version integer DEFAULT 0 NOT NULL
);


--
-- Name: access_grants access_grants_order_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_order_id_key UNIQUE (order_id);


--
-- Name: access_grants access_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_pkey PRIMARY KEY (id);


--
-- Name: activation_state activation_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activation_state
    ADD CONSTRAINT activation_state_pkey PRIMARY KEY (user_id);


--
-- Name: analytics_events analytics_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analytics_events
    ADD CONSTRAINT analytics_events_pkey PRIMARY KEY (id);


--
-- Name: app_migrations app_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_migrations
    ADD CONSTRAINT app_migrations_pkey PRIMARY KEY (name);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: billing_coupons billing_coupons_code_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_coupons
    ADD CONSTRAINT billing_coupons_code_hash_key UNIQUE (code_hash);


--
-- Name: billing_coupons billing_coupons_label_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_coupons
    ADD CONSTRAINT billing_coupons_label_key UNIQUE (label);


--
-- Name: billing_coupons billing_coupons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_coupons
    ADD CONSTRAINT billing_coupons_pkey PRIMARY KEY (id);


--
-- Name: billing_events billing_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_events
    ADD CONSTRAINT billing_events_pkey PRIMARY KEY (event_id);


--
-- Name: billing_orders billing_orders_gateway_order_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_orders
    ADD CONSTRAINT billing_orders_gateway_order_id_key UNIQUE (gateway_order_id);


--
-- Name: billing_orders billing_orders_gateway_payment_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_orders
    ADD CONSTRAINT billing_orders_gateway_payment_id_key UNIQUE (gateway_payment_id);


--
-- Name: billing_orders billing_orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_orders
    ADD CONSTRAINT billing_orders_pkey PRIMARY KEY (id);


--
-- Name: billing_orders billing_orders_user_id_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_orders
    ADD CONSTRAINT billing_orders_user_id_idempotency_key_key UNIQUE (user_id, idempotency_key);


--
-- Name: billing_plans billing_plans_gateway_plan_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_plans
    ADD CONSTRAINT billing_plans_gateway_plan_id_key UNIQUE (gateway_plan_id);


--
-- Name: billing_plans billing_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_plans
    ADD CONSTRAINT billing_plans_pkey PRIMARY KEY (id);


--
-- Name: billing_subscriptions billing_subscriptions_gateway_subscription_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_subscriptions
    ADD CONSTRAINT billing_subscriptions_gateway_subscription_id_key UNIQUE (gateway_subscription_id);


--
-- Name: billing_subscriptions billing_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_subscriptions
    ADD CONSTRAINT billing_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: care_circle_siblings care_circle_siblings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.care_circle_siblings
    ADD CONSTRAINT care_circle_siblings_pkey PRIMARY KEY (id);


--
-- Name: care_send_claims care_send_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.care_send_claims
    ADD CONSTRAINT care_send_claims_pkey PRIMARY KEY (event_key);


--
-- Name: care_watch care_watch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.care_watch
    ADD CONSTRAINT care_watch_pkey PRIMARY KEY (parent_id, day_key);


--
-- Name: child_content_requests child_content_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.child_content_requests
    ADD CONSTRAINT child_content_requests_pkey PRIMARY KEY (wam_id);


--
-- Name: circle_invites circle_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.circle_invites
    ADD CONSTRAINT circle_invites_pkey PRIMARY KEY (id);


--
-- Name: circle_invites circle_invites_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.circle_invites
    ADD CONSTRAINT circle_invites_token_key UNIQUE (token);


--
-- Name: consent_logs consent_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_logs
    ADD CONSTRAINT consent_logs_pkey PRIMARY KEY (id);


--
-- Name: distress_logs distress_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distress_logs
    ADD CONSTRAINT distress_logs_pkey PRIMARY KEY (id);


--
-- Name: email_otps email_otps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_otps
    ADD CONSTRAINT email_otps_pkey PRIMARY KEY (email);


--
-- Name: emergency_events emergency_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.emergency_events
    ADD CONSTRAINT emergency_events_pkey PRIMARY KEY (id);


--
-- Name: escalation_daily escalation_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escalation_daily
    ADD CONSTRAINT escalation_daily_pkey PRIMARY KEY (marker);


--
-- Name: escalation_state escalation_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escalation_state
    ADD CONSTRAINT escalation_state_pkey PRIMARY KEY (id);


--
-- Name: family_notifications family_notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.family_notifications
    ADD CONSTRAINT family_notifications_pkey PRIMARY KEY (event_key);


--
-- Name: inbound_events inbound_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inbound_events
    ADD CONSTRAINT inbound_events_pkey PRIMARY KEY (wam_id);


--
-- Name: jwt_blacklist jwt_blacklist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jwt_blacklist
    ADD CONSTRAINT jwt_blacklist_pkey PRIMARY KEY (jti);


--
-- Name: medicines medicines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.medicines
    ADD CONSTRAINT medicines_pkey PRIMARY KEY (id);


--
-- Name: message_logs message_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_logs
    ADD CONSTRAINT message_logs_pkey PRIMARY KEY (id);


--
-- Name: moment_images moment_images_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.moment_images
    ADD CONSTRAINT moment_images_pkey PRIMARY KEY (id);


--
-- Name: moments moments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.moments
    ADD CONSTRAINT moments_pkey PRIMARY KEY (id);


--
-- Name: monthly_report_jobs monthly_report_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_report_jobs
    ADD CONSTRAINT monthly_report_jobs_pkey PRIMARY KEY (parent_id, period);


--
-- Name: monthly_reports monthly_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_reports
    ADD CONSTRAINT monthly_reports_pkey PRIMARY KEY (id);


--
-- Name: monthly_reports monthly_reports_user_id_parent_id_period_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_reports
    ADD CONSTRAINT monthly_reports_user_id_parent_id_period_key UNIQUE (user_id, parent_id, period);


--
-- Name: notification_attempts notification_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_attempts
    ADD CONSTRAINT notification_attempts_pkey PRIMARY KEY (sid);


--
-- Name: parent_checkins parent_checkins_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_checkins
    ADD CONSTRAINT parent_checkins_pkey PRIMARY KEY (id);


--
-- Name: parent_delivery_alerts parent_delivery_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_delivery_alerts
    ADD CONSTRAINT parent_delivery_alerts_pkey PRIMARY KEY (parent_id, day_key);


--
-- Name: parent_health_reminders parent_health_reminders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_health_reminders
    ADD CONSTRAINT parent_health_reminders_pkey PRIMARY KEY (id);


--
-- Name: parent_replies parent_replies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_replies
    ADD CONSTRAINT parent_replies_pkey PRIMARY KEY (id);


--
-- Name: parent_routines parent_routines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_routines
    ADD CONSTRAINT parent_routines_pkey PRIMARY KEY (id);


--
-- Name: parents parents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parents
    ADD CONSTRAINT parents_pkey PRIMARY KEY (id);


--
-- Name: payment_state payment_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_state
    ADD CONSTRAINT payment_state_pkey PRIMARY KEY (user_id);


--
-- Name: payment_transactions payment_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_transactions
    ADD CONSTRAINT payment_transactions_pkey PRIMARY KEY (id);


--
-- Name: payment_transactions payment_transactions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_transactions
    ADD CONSTRAINT payment_transactions_session_id_key UNIQUE (session_id);


--
-- Name: phone_otps phone_otps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phone_otps
    ADD CONSTRAINT phone_otps_pkey PRIMARY KEY (phone);


--
-- Name: preferences preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preferences
    ADD CONSTRAINT preferences_pkey PRIMARY KEY (user_id);


--
-- Name: provider_receipts provider_receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_receipts
    ADD CONSTRAINT provider_receipts_pkey PRIMARY KEY (event_key);


--
-- Name: recipient_sessions recipient_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recipient_sessions
    ADD CONSTRAINT recipient_sessions_pkey PRIMARY KEY (phone);


--
-- Name: reply_notifications reply_notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reply_notifications
    ADD CONSTRAINT reply_notifications_pkey PRIMARY KEY (id);


--
-- Name: reply_notifications reply_notifications_reply_id_recipient_kind_recipient_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reply_notifications
    ADD CONSTRAINT reply_notifications_reply_id_recipient_kind_recipient_id_key UNIQUE (reply_id, recipient_kind, recipient_id);


--
-- Name: scheduler_locks scheduler_locks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler_locks
    ADD CONSTRAINT scheduler_locks_pkey PRIMARY KEY (lock_name);


--
-- Name: schedules schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules
    ADD CONSTRAINT schedules_pkey PRIMARY KEY (id);


--
-- Name: template_variants_cache template_variants_cache_category_language_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_variants_cache
    ADD CONSTRAINT template_variants_cache_category_language_key UNIQUE (category, language);


--
-- Name: template_variants_cache template_variants_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_variants_cache
    ADD CONSTRAINT template_variants_cache_pkey PRIMARY KEY (id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: verification_challenges verification_challenges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verification_challenges
    ADD CONSTRAINT verification_challenges_pkey PRIMARY KEY (id);


--
-- Name: wa_sessions wa_sessions_parent_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wa_sessions
    ADD CONSTRAINT wa_sessions_parent_id_key UNIQUE (parent_id);


--
-- Name: wa_sessions wa_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wa_sessions
    ADD CONSTRAINT wa_sessions_pkey PRIMARY KEY (id);


--
-- Name: webhook_debug webhook_debug_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_debug
    ADD CONSTRAINT webhook_debug_pkey PRIMARY KEY (id);


--
-- Name: welcome_deliveries welcome_deliveries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.welcome_deliveries
    ADD CONSTRAINT welcome_deliveries_pkey PRIMARY KEY (event_key);


--
-- Name: access_grants_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX access_grants_owner ON public.access_grants USING btree (user_id, starts_at, ends_at);


--
-- Name: billing_orders_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX billing_orders_pending ON public.billing_orders USING btree (status, created_at);


--
-- Name: billing_plans_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX billing_plans_lookup ON public.billing_plans USING btree (plan, billing, currency);


--
-- Name: billing_subscriptions_gateway; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX billing_subscriptions_gateway ON public.billing_subscriptions USING btree (gateway_subscription_id);


--
-- Name: billing_subscriptions_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX billing_subscriptions_user ON public.billing_subscriptions USING btree (user_id, status);


--
-- Name: family_notifications_sid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX family_notifications_sid ON public.family_notifications USING btree (sid) WHERE (sid IS NOT NULL);


--
-- Name: idx_analytics_events_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_analytics_events_created ON public.analytics_events USING btree (created_at);


--
-- Name: idx_auditlogs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auditlogs_action ON public.audit_logs USING btree (action, created_at DESC);


--
-- Name: idx_auditlogs_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auditlogs_user ON public.audit_logs USING btree (user_id, created_at DESC);


--
-- Name: idx_ccsiblings_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ccsiblings_owner ON public.care_circle_siblings USING btree (owner_id);


--
-- Name: idx_ccsiblings_owner_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_ccsiblings_owner_phone ON public.care_circle_siblings USING btree (owner_id, phone);


--
-- Name: idx_circleinvites_email_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_circleinvites_email_status ON public.circle_invites USING btree (email, status);


--
-- Name: idx_circleinvites_owner_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_circleinvites_owner_status ON public.circle_invites USING btree (owner_id, status);


--
-- Name: idx_distresslogs_parent_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distresslogs_parent_created ON public.distress_logs USING btree (parent_id, created_at DESC);


--
-- Name: idx_emergencyevents_open; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_emergencyevents_open ON public.emergency_events USING btree (status, created_at DESC) WHERE (status = 'open'::text);


--
-- Name: idx_emergencyevents_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_emergencyevents_parent ON public.emergency_events USING btree (parent_id, created_at DESC);


--
-- Name: idx_logs_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_logs_event ON public.message_logs USING btree (event_key);


--
-- Name: idx_moments_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_moments_parent ON public.moments USING btree (parent_id, created_at DESC);


--
-- Name: idx_moments_sid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_moments_sid ON public.moments USING btree (sid) WHERE (sid IS NOT NULL);


--
-- Name: idx_msglogs_delivery_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_msglogs_delivery_status ON public.message_logs USING btree (delivery_status) WHERE (delivery_status IS NOT NULL);


--
-- Name: idx_msglogs_parent_day; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_msglogs_parent_day ON public.message_logs USING btree (parent_id, day_key);


--
-- Name: idx_msglogs_sched_idx_day; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_msglogs_sched_idx_day ON public.message_logs USING btree (schedule_id, message_index, day_key);


--
-- Name: idx_msglogs_sid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_msglogs_sid ON public.message_logs USING btree (sid) WHERE (sid IS NOT NULL);


--
-- Name: idx_msglogs_sid_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_msglogs_sid_uniq ON public.message_logs USING btree (sid) WHERE (sid IS NOT NULL);


--
-- Name: idx_notification_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_pending ON public.reply_notifications USING btree (status, next_attempt_at);


--
-- Name: idx_notification_sid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_sid ON public.reply_notifications USING btree (sid);


--
-- Name: idx_parent_checkins_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parent_checkins_parent ON public.parent_checkins USING btree (parent_id);


--
-- Name: idx_parent_health_reminders_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parent_health_reminders_parent ON public.parent_health_reminders USING btree (parent_id);


--
-- Name: idx_parent_replies_wam; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_parent_replies_wam ON public.parent_replies USING btree (wam_id) WHERE (wam_id IS NOT NULL);


--
-- Name: idx_parent_routines_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parent_routines_parent ON public.parent_routines USING btree (parent_id);


--
-- Name: idx_parentreplies_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parentreplies_intent ON public.parent_replies USING btree (parent_id, intent);


--
-- Name: idx_parentreplies_parent_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parentreplies_parent_created ON public.parent_replies USING btree (parent_id, created_at);


--
-- Name: idx_parentreplies_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parentreplies_user_created ON public.parent_replies USING btree (user_id, created_at DESC);


--
-- Name: idx_parentreplies_user_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parentreplies_user_unread ON public.parent_replies USING btree (user_id) WHERE (read_at IS NULL);


--
-- Name: idx_parents_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parents_phone ON public.parents USING btree (phone);


--
-- Name: idx_parents_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parents_user ON public.parents USING btree (user_id);


--
-- Name: idx_schedules_parent_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_schedules_parent_active ON public.schedules USING btree (parent_id, active, deleted_at);


--
-- Name: idx_schedules_recovery; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_schedules_recovery ON public.schedules USING btree (recovery_mode, recovery_until, deleted_at);


--
-- Name: idx_schedules_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_schedules_user ON public.schedules USING btree (user_id);


--
-- Name: idx_users_household_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_household_owner ON public.users USING btree (household_owner_id);


--
-- Name: idx_verification_rate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_verification_rate ON public.verification_challenges USING btree (email, created_at);


--
-- Name: idx_wasessions_reeng; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wasessions_reeng ON public.wa_sessions USING btree (opener_sent_at, reengagement_sent);


--
-- Name: idx_wasessions_session_open; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wasessions_session_open ON public.wa_sessions USING btree (session_open) WHERE (session_open = true);


--
-- Name: idx_webhook_debug_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_webhook_debug_created ON public.webhook_debug USING btree (created_at DESC);


--
-- Name: logs_sid_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX logs_sid_parent ON public.message_logs USING btree (parent_id, sid);


--
-- Name: one_lifetime_gift_per_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX one_lifetime_gift_per_email ON public.billing_coupons USING btree (lower(allowed_email)) WHERE ((kind = 'lifetime'::text) AND (allowed_email IS NOT NULL));


--
-- Name: replies_context_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX replies_context_parent ON public.parent_replies USING btree (parent_id, context_id);


--
-- Name: schedules care_schedule_effective_from; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER care_schedule_effective_from BEFORE UPDATE ON public.schedules FOR EACH ROW EXECUTE FUNCTION public.care_schedule_effective_from();


--
-- Name: access_grants access_grants_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.billing_orders(id);


--
-- Name: access_grants access_grants_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: activation_state activation_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activation_state
    ADD CONSTRAINT activation_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: billing_coupons billing_coupons_redeemed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_coupons
    ADD CONSTRAINT billing_coupons_redeemed_by_fkey FOREIGN KEY (redeemed_by) REFERENCES public.users(id);


--
-- Name: billing_coupons billing_coupons_reserved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_coupons
    ADD CONSTRAINT billing_coupons_reserved_by_fkey FOREIGN KEY (reserved_by) REFERENCES public.users(id);


--
-- Name: billing_orders billing_orders_coupon_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_orders
    ADD CONSTRAINT billing_orders_coupon_id_fkey FOREIGN KEY (coupon_id) REFERENCES public.billing_coupons(id);


--
-- Name: billing_orders billing_orders_credited_grant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_orders
    ADD CONSTRAINT billing_orders_credited_grant_id_fkey FOREIGN KEY (credited_grant_id) REFERENCES public.access_grants(id);


--
-- Name: billing_orders billing_orders_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_orders
    ADD CONSTRAINT billing_orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: billing_subscriptions billing_subscriptions_billing_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_subscriptions
    ADD CONSTRAINT billing_subscriptions_billing_plan_id_fkey FOREIGN KEY (billing_plan_id) REFERENCES public.billing_plans(id);


--
-- Name: billing_subscriptions billing_subscriptions_coupon_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_subscriptions
    ADD CONSTRAINT billing_subscriptions_coupon_id_fkey FOREIGN KEY (coupon_id) REFERENCES public.billing_coupons(id);


--
-- Name: billing_subscriptions billing_subscriptions_latest_grant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_subscriptions
    ADD CONSTRAINT billing_subscriptions_latest_grant_id_fkey FOREIGN KEY (latest_grant_id) REFERENCES public.access_grants(id);


--
-- Name: billing_subscriptions billing_subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_subscriptions
    ADD CONSTRAINT billing_subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: care_circle_siblings care_circle_siblings_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.care_circle_siblings
    ADD CONSTRAINT care_circle_siblings_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: care_send_claims care_send_claims_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.care_send_claims
    ADD CONSTRAINT care_send_claims_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: care_watch care_watch_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.care_watch
    ADD CONSTRAINT care_watch_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: child_content_requests child_content_requests_notification_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.child_content_requests
    ADD CONSTRAINT child_content_requests_notification_id_fkey FOREIGN KEY (notification_id) REFERENCES public.reply_notifications(id) ON DELETE CASCADE;


--
-- Name: circle_invites circle_invites_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.circle_invites
    ADD CONSTRAINT circle_invites_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.parents(id) ON DELETE SET NULL;


--
-- Name: circle_invites circle_invites_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.circle_invites
    ADD CONSTRAINT circle_invites_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: circle_invites circle_invites_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.circle_invites
    ADD CONSTRAINT circle_invites_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE SET NULL;


--
-- Name: circle_invites circle_invites_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.circle_invites
    ADD CONSTRAINT circle_invites_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: consent_logs consent_logs_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_logs
    ADD CONSTRAINT consent_logs_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: consent_logs consent_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consent_logs
    ADD CONSTRAINT consent_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: distress_logs distress_logs_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distress_logs
    ADD CONSTRAINT distress_logs_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: emergency_events emergency_events_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.emergency_events
    ADD CONSTRAINT emergency_events_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: emergency_events emergency_events_resolved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.emergency_events
    ADD CONSTRAINT emergency_events_resolved_by_fkey FOREIGN KEY (resolved_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: emergency_events emergency_events_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.emergency_events
    ADD CONSTRAINT emergency_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: escalation_state escalation_state_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escalation_state
    ADD CONSTRAINT escalation_state_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: escalation_state escalation_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escalation_state
    ADD CONSTRAINT escalation_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: family_notifications family_notifications_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.family_notifications
    ADD CONSTRAINT family_notifications_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: family_notifications family_notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.family_notifications
    ADD CONSTRAINT family_notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: medicines medicines_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.medicines
    ADD CONSTRAINT medicines_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: message_logs message_logs_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_logs
    ADD CONSTRAINT message_logs_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: message_logs message_logs_schedule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_logs
    ADD CONSTRAINT message_logs_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES public.schedules(id) ON DELETE SET NULL;


--
-- Name: message_logs message_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_logs
    ADD CONSTRAINT message_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: moment_images moment_images_moment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.moment_images
    ADD CONSTRAINT moment_images_moment_id_fkey FOREIGN KEY (moment_id) REFERENCES public.moments(id) ON DELETE CASCADE;


--
-- Name: moment_images moment_images_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.moment_images
    ADD CONSTRAINT moment_images_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: moments moments_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.moments
    ADD CONSTRAINT moments_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: moments moments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.moments
    ADD CONSTRAINT moments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: monthly_report_jobs monthly_report_jobs_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_report_jobs
    ADD CONSTRAINT monthly_report_jobs_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: monthly_reports monthly_reports_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_reports
    ADD CONSTRAINT monthly_reports_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: monthly_reports monthly_reports_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_reports
    ADD CONSTRAINT monthly_reports_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: notification_attempts notification_attempts_notification_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_attempts
    ADD CONSTRAINT notification_attempts_notification_id_fkey FOREIGN KEY (notification_id) REFERENCES public.reply_notifications(id) ON DELETE CASCADE;


--
-- Name: parent_checkins parent_checkins_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_checkins
    ADD CONSTRAINT parent_checkins_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: parent_delivery_alerts parent_delivery_alerts_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_delivery_alerts
    ADD CONSTRAINT parent_delivery_alerts_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: parent_health_reminders parent_health_reminders_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_health_reminders
    ADD CONSTRAINT parent_health_reminders_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: parent_replies parent_replies_message_log_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_replies
    ADD CONSTRAINT parent_replies_message_log_id_fkey FOREIGN KEY (message_log_id) REFERENCES public.message_logs(id) ON DELETE SET NULL;


--
-- Name: parent_replies parent_replies_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_replies
    ADD CONSTRAINT parent_replies_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: parent_replies parent_replies_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_replies
    ADD CONSTRAINT parent_replies_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: parent_routines parent_routines_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parent_routines
    ADD CONSTRAINT parent_routines_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: parents parents_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parents
    ADD CONSTRAINT parents_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: payment_state payment_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_state
    ADD CONSTRAINT payment_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: payment_transactions payment_transactions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_transactions
    ADD CONSTRAINT payment_transactions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: preferences preferences_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preferences
    ADD CONSTRAINT preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: reply_notifications reply_notifications_reply_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reply_notifications
    ADD CONSTRAINT reply_notifications_reply_id_fkey FOREIGN KEY (reply_id) REFERENCES public.parent_replies(id) ON DELETE CASCADE;


--
-- Name: schedules schedules_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules
    ADD CONSTRAINT schedules_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- Name: schedules schedules_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules
    ADD CONSTRAINT schedules_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_household_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_household_owner_id_fkey FOREIGN KEY (household_owner_id) REFERENCES public.users(id);


--
-- Name: verification_challenges verification_challenges_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verification_challenges
    ADD CONSTRAINT verification_challenges_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: wa_sessions wa_sessions_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wa_sessions
    ADD CONSTRAINT wa_sessions_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.parents(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


INSERT INTO public.app_migrations(name) VALUES ('004_reliable_care');
INSERT INTO public.app_migrations(name) VALUES ('005_account_sessions');
INSERT INTO public.app_migrations(name) VALUES ('006_checkout_coupons');
INSERT INTO public.app_migrations(name) VALUES ('007_subscriptions');
INSERT INTO public.app_migrations(name) VALUES ('008_drop_legacy_phone_verified');
INSERT INTO public.app_migrations(name) VALUES ('009_care_consistency');
INSERT INTO public.app_migrations(name) VALUES ('010_delivery_recovery');
INSERT INTO public.app_migrations(name) VALUES ('011_child_welcome_recovery');
INSERT INTO public.app_migrations(name) VALUES ('012_family_delivery');
COMMIT;
