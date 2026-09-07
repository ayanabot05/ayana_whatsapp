-- ============================================================================
-- AYANA — COMPLETE CLEAN PostgreSQL schema (Supabase)
-- Consolidates base schema + migration 002 + email_otps + manual quiet-hours
-- + 6-month retention. Drops everything first (fresh start, re-signup).
-- ============================================================================

create extension if not exists pgcrypto;   -- gen_random_uuid()
create extension if not exists pg_cron;    -- nightly purge job

-- Drop in reverse-dependency order
drop table if exists scheduler_locks cascade;
drop table if exists preferences cascade;
drop table if exists audit_logs cascade;
drop table if exists consent_logs cascade;
drop table if exists activation_state cascade;
drop table if exists template_variants_cache cascade;
drop table if exists payment_state cascade;
drop table if exists payment_transactions cascade;
drop table if exists jwt_blacklist cascade;
drop table if exists monthly_reports cascade;
drop table if exists moment_images cascade;
drop table if exists moments cascade;
drop table if exists emergency_events cascade;
drop table if exists parent_replies cascade;
drop table if exists distress_logs cascade;
drop table if exists circle_invites cascade;
drop table if exists email_otps cascade;
drop table if exists phone_otps cascade;
drop table if exists wa_sessions cascade;
drop table if exists escalation_daily cascade;
drop table if exists escalation_state cascade;
drop table if exists message_logs cascade;
drop table if exists schedules cascade;
drop table if exists parents cascade;
drop table if exists users cascade;

-- ============================================================================
-- USERS
-- ============================================================================
create table users (
    id                    uuid primary key default gen_random_uuid(),
    name                  text not null,
    email                 text not null unique,
    phone                 text not null,
    password_hash         text not null,
    role                  text not null default 'user' check (role in ('user', 'admin')),
    onboarding_complete   boolean not null default false,
    onboarding_step       integer not null default 0,
    phone_verified        boolean not null default false,
    phone_verified_number text,
    preferences           jsonb not null default '{}'::jsonb,
    password_changed_at   timestamptz,
    city                  text,
    timezone              text not null default 'Asia/Kolkata',
    household_owner_id    uuid references users(id),
    created_at            timestamptz not null default now(),
    deleted_at            timestamptz
);
create index idx_users_household_owner on users(household_owner_id);

-- ============================================================================
-- PARENTS  — quiet hours are now MANUAL only (06:00–22:00 default, no auto)
-- ============================================================================
create table parents (
    id                       uuid primary key default gen_random_uuid(),
    user_id                  uuid not null references users(id) on delete cascade,
    name                     text not null,
    preferred_name           text,
    relationship             text not null check (relationship in ('mother', 'father')),
    phone                    text not null,
    language                 text not null default 'en',
    timezone                 text not null default 'Asia/Kolkata',
    city                     text,
    other_parent_name        text,
    notes                    text,
    birthday                 text,                          -- MM-DD
    nicknames                jsonb not null default '[]',
    habits                   jsonb,
    medicine_list            jsonb not null default '[]',
    stories                  jsonb not null default '[]',
    activity_window_start    text default '06:00',
    activity_window_end      text default '22:00',
    auto_activity_detection  boolean not null default false,
    detected_language        text,
    language_suggestion      text,
    language_suggestion_at   timestamptz,
    emergency_contacts       jsonb not null default '[]',
    recovery_mode            boolean not null default false,
    recovery_until           timestamptz,
    created_at               timestamptz not null default now(),
    deleted_at               timestamptz,
    constraint chk_window_width  check (activity_window_start is null or activity_window_end is null or activity_window_start <> activity_window_end),
    constraint chk_window_format check (
        (activity_window_start is null or activity_window_start ~ '^[0-2][0-9]:[0-5][0-9]$') and
        (activity_window_end   is null or activity_window_end   ~ '^[0-2][0-9]:[0-5][0-9]$')
    )
);
create index idx_parents_phone on parents(phone);
create index idx_parents_user on parents(user_id);

-- ============================================================================
-- SCHEDULES
-- ============================================================================
create table schedules (
    id                          uuid primary key default gen_random_uuid(),
    parent_id                   uuid not null references parents(id) on delete cascade,
    user_id                     uuid not null references users(id) on delete cascade,
    mode                        text not null default 'nitya' check (mode in ('nitya', 'bandham', 'raksha')),
    messages                    jsonb not null default '[]',
    active                      boolean not null default true,
    recovery_mode               boolean not null default false,
    recovery_until              text,
    reengagement_hours          integer not null default 4,
    archived_recovery_messages  jsonb not null default '[]'::jsonb,
    created_at                  timestamptz not null default now(),
    deleted_at                  timestamptz
);
create index idx_schedules_user on schedules(user_id);
create index idx_schedules_parent_active on schedules(parent_id, active, deleted_at);
create index idx_schedules_recovery on schedules(recovery_mode, recovery_until, deleted_at);

-- ============================================================================
-- MESSAGE_LOGS
-- ============================================================================
create table message_logs (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null references users(id) on delete cascade,
    parent_id      uuid not null references parents(id) on delete cascade,
    schedule_id    uuid references schedules(id) on delete set null,
    day_key        text not null,               -- 'YYYY-MM-DD', parent-local day
    message_index  integer,
    category       text,
    msg_type       text,                         -- 'checkin' | 'reminder' | 'activity' | 'escalation'
    status         text,                         -- 'sent' | 'simulated' | 'failed'
    skipped        boolean not null default false,
    escalation_of  uuid,
    attempt        integer,
    kind           text,
    body           text,
    detail         text,
    sid            text,
    reply_status   text,
    delivery_status text,                        -- Meta callback: 'sent'|'delivered'|'read'|'failed'
    delivered_at   timestamptz,
    read_at        timestamptz,
    created_at     timestamptz not null default now()
);
create index idx_msglogs_sched_idx_day on message_logs(schedule_id, message_index, day_key);
create index idx_msglogs_parent_day on message_logs(parent_id, day_key);
create index idx_msglogs_sid on message_logs(sid) where sid is not null;

-- ============================================================================
-- ESCALATION_STATE + ESCALATION_DAILY
-- ============================================================================
create table escalation_state (
    id               text primary key,
    parent_id        uuid not null references parents(id) on delete cascade,
    user_id          uuid not null references users(id) on delete cascade,
    attempts         integer not null default 0,
    last_attempt_at  timestamptz,
    kind             text,
    day_key          text,
    first_at         timestamptz not null default now()
);

create table escalation_daily (
    marker  text primary key,
    at      timestamptz not null default now()
);

-- ============================================================================
-- WA_SESSIONS
-- ============================================================================
create table wa_sessions (
    id                    uuid primary key default gen_random_uuid(),
    parent_id             uuid not null unique references parents(id) on delete cascade,
    opener_sent_at        timestamptz,
    reengagement_sent     boolean not null default false,
    reengagement_sent_at  timestamptz,
    last_inbound_at       timestamptz,
    last_outbound_at      timestamptz,
    last_activity         timestamptz,
    last_template_type    text,
    session_open          boolean not null default false,
    updated_at            timestamptz not null default now()
);
create index idx_wasessions_reeng on wa_sessions(opener_sent_at, reengagement_sent);
create index idx_wasessions_session_open on wa_sessions(session_open) where session_open = true;

-- ============================================================================
-- PHONE_OTPS  (child phone verification)
-- ============================================================================
create table phone_otps (
    phone              text primary key,
    code_hash          text not null,
    attempts           integer not null default 0,
    verified           boolean not null default false,
    verified_at        timestamptz,
    send_count         integer not null default 0,
    send_window_start  timestamptz,
    created_at         timestamptz not null default now(),
    expires_at         timestamptz not null
);

-- ============================================================================
-- EMAIL_OTPS  (login-email change confirmation)
-- ============================================================================
create table email_otps (
    email              text primary key,
    code_hash          text not null,
    attempts           integer not null default 0,
    verified           boolean not null default false,
    verified_at        timestamptz,
    send_count         integer not null default 0,
    send_window_start  timestamptz,
    created_at         timestamptz not null default now(),
    expires_at         timestamptz not null
);

-- ============================================================================
-- CIRCLE_INVITES
-- ============================================================================
create table circle_invites (
    id            uuid primary key default gen_random_uuid(),
    owner_id      uuid references users(id) on delete cascade,
    user_id       uuid references users(id) on delete cascade,   -- legacy, nullable
    member_id     uuid references users(id) on delete set null,
    parent_id     uuid references parents(id) on delete set null,
    email         text not null,
    token         text not null unique,
    inviter_name  text,
    status        text not null default 'pending' check (status in ('pending', 'accepted', 'cancelled')),
    created_at    timestamptz not null default now(),
    accepted_at   timestamptz,
    expires_at    timestamptz not null
);
create index idx_circleinvites_owner_status on circle_invites(owner_id, status);
create index idx_circleinvites_email_status on circle_invites(email, status);

-- ============================================================================
-- DISTRESS_LOGS
-- ============================================================================
create table distress_logs (
    id                 uuid primary key default gen_random_uuid(),
    parent_id          uuid not null references parents(id) on delete cascade,
    transcript         text,
    language           text,
    keyword_matches    jsonb not null default '[]',
    ml_score           double precision,
    keyword_emergency  boolean not null default false,
    ml_flagged         boolean not null default false,
    outcome            text,
    created_at         timestamptz not null default now()
);
create index idx_distresslogs_parent_created on distress_logs(parent_id, created_at desc);

-- ============================================================================
-- PARENT_REPLIES
-- ============================================================================
create table parent_replies (
    id                  uuid primary key default gen_random_uuid(),
    parent_id           uuid not null references parents(id) on delete cascade,
    user_id             uuid references users(id) on delete cascade,
    intent              text,                 -- 'feeling:good' etc.
    text                text,
    from_phone          text,
    body                text,
    button_payload      text,
    feeling             text,
    media_url           text,
    transcription       text,
    is_voice            boolean not null default false,
    emergency_keywords  jsonb not null default '[]'::jsonb,
    ml_flagged          boolean not null default false,
    ml_score            double precision,
    stt_confidence      double precision,
    raw_payload         jsonb not null default '{}'::jsonb,
    created_at          timestamptz not null default now()
);
create index idx_parentreplies_parent_created on parent_replies(parent_id, created_at);
create index idx_parentreplies_intent on parent_replies(parent_id, intent);
create index idx_parentreplies_user_created on parent_replies(user_id, created_at desc);

-- ============================================================================
-- EMERGENCY_EVENTS
-- ============================================================================
create table emergency_events (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null references users(id) on delete cascade,
    parent_id        uuid not null references parents(id) on delete cascade,
    source           text,                 -- 'keyword' | 'ml' | 'manual'
    detail           text,
    intent           text,
    is_voice         boolean not null default false,
    body             text,
    keywords         jsonb not null default '[]'::jsonb,
    phone            text,
    status           text not null default 'open' check (status in ('open', 'resolved', 'false_positive')),
    resolution_note  text,
    resolved_by      uuid references users(id) on delete set null,
    created_at       timestamptz not null default now(),
    resolved_at      timestamptz,
    deleted_at       timestamptz
);
create index idx_emergencyevents_parent on emergency_events(parent_id, created_at desc);
create index idx_emergencyevents_open on emergency_events(status, created_at desc) where status = 'open';

-- ============================================================================
-- MOMENTS + MOMENT_IMAGES  (child -> parent)
-- ============================================================================
create table moments (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references users(id) on delete cascade,
    parent_id    uuid not null references parents(id) on delete cascade,
    text         text,
    image_url    text,
    image_urls   jsonb not null default '[]'::jsonb,
    sender_name  text,
    status       text not null default 'pending',
    created_at   timestamptz not null default now()
);
create index idx_moments_parent on moments(parent_id, created_at desc);

create table moment_images (
    id           uuid primary key default gen_random_uuid(),
    moment_id    uuid not null references moments(id) on delete cascade,
    user_id      uuid references users(id) on delete cascade,
    storage_path text not null,
    filename     text,
    size         bigint,
    content_type text,
    is_deleted   boolean not null default false,
    created_at   timestamptz not null default now()
);

-- ============================================================================
-- MONTHLY_REPORTS  (kept forever — aggregated summaries)
-- ============================================================================
create table monthly_reports (
    id                      uuid primary key default gen_random_uuid(),
    user_id                 uuid not null references users(id) on delete cascade,
    parent_id               uuid not null references parents(id) on delete cascade,
    plan                    text,
    period                  text not null,        -- 'YYYY-MM'
    total_touches           integer not null default 0,
    delivered               integer not null default 0,
    skipped                 integer not null default 0,
    voice_replies           integer not null default 0,
    mood_graph              jsonb,
    trend_note              text,
    shared_with_care_circle boolean not null default false,
    generated_at            timestamptz not null default now(),
    details                 jsonb,
    unique (user_id, parent_id, period)
);

-- ============================================================================
-- JWT_BLACKLIST
-- ============================================================================
create table jwt_blacklist (
    jti          text primary key,
    expires_at   timestamptz not null,
    revoked_at   timestamptz not null default now()
);

-- ============================================================================
-- PAYMENTS
-- ============================================================================
create table payment_transactions (
    id               uuid primary key default gen_random_uuid(),
    session_id       text not null unique,
    user_id          uuid not null references users(id) on delete cascade,
    plan             text,
    billing          text,
    amount           numeric(10,2),
    currency         text,
    status           text,
    payment_status   text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create table payment_state (
    user_id      uuid primary key references users(id) on delete cascade,
    status       text,
    plan         text,
    billing      text,
    updated_at   timestamptz not null default now()
);

-- ============================================================================
-- TEMPLATE_VARIANTS_CACHE
-- ============================================================================
create table template_variants_cache (
    id            uuid primary key default gen_random_uuid(),
    category      text not null,
    language      text not null,
    variants      jsonb not null,
    source        text,
    generated_at  timestamptz not null default now(),
    unique (category, language)
);

-- ============================================================================
-- ACTIVATION_STATE
-- ============================================================================
create table activation_state (
    user_id            uuid primary key references users(id) on delete cascade,
    whatsapp_activated boolean not null default false,
    activated_at       timestamptz
);

-- ============================================================================
-- CONSENT_LOGS
-- ============================================================================
create table consent_logs (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid references users(id) on delete cascade,
    parent_id     uuid references parents(id) on delete cascade,
    consent_type  text not null check (consent_type in ('child', 'parent')),
    agreed        boolean not null,
    text          text,
    ip            text,
    created_at    timestamptz not null default now()
);

-- ============================================================================
-- AUDIT_LOGS  (server writes `meta`; `detail` kept for compatibility)
-- ============================================================================
create table audit_logs (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid references users(id) on delete set null,
    action       text not null,
    meta         jsonb,
    detail       jsonb,
    created_at   timestamptz not null default now()
);
create index idx_auditlogs_user on audit_logs(user_id, created_at desc);
create index idx_auditlogs_action on audit_logs(action, created_at desc);

-- ============================================================================
-- PREFERENCES
-- ============================================================================
create table preferences (
    user_id             uuid primary key references users(id) on delete cascade,
    emergency_keywords  jsonb not null default '[]',
    daily_summary       boolean not null default true,
    email_notifications boolean not null default true,
    whatsapp_reports    boolean not null default true
);

-- ============================================================================
-- SCHEDULER_LOCKS
-- ============================================================================
create table scheduler_locks (
    lock_name    text primary key,
    holder       text,
    acquired_at  timestamptz not null default now(),
    expires_at   timestamptz not null
);

-- ============================================================================
-- PURGE JOB — retention: reports kept FOREVER; raw chat purged after 6 months
-- (only once that month's report exists); distress/emergency never purged.
-- ============================================================================
create or replace function purge_expired_data() returns void as $$
begin
    delete from phone_otps      where expires_at < now();
    delete from email_otps      where expires_at < now();
    delete from circle_invites  where expires_at < now();
    delete from jwt_blacklist   where expires_at < now();
    delete from scheduler_locks where expires_at < now();

    delete from message_logs
    where created_at < now() - interval '6 months'
      and exists (
          select 1 from monthly_reports mr
          where mr.parent_id = message_logs.parent_id
            and mr.period = to_char(message_logs.created_at, 'YYYY-MM')
      );

    delete from parent_replies
    where created_at < now() - interval '6 months'
      and exists (
          select 1 from monthly_reports mr
          where mr.parent_id = parent_replies.parent_id
            and mr.period = to_char(parent_replies.created_at, 'YYYY-MM')
      );
end;
$$ language plpgsql;

-- Nightly at 03:00 UTC (safe to re-run; unschedule the old one first)
select cron.unschedule('ayana-nightly-purge')
where exists (select 1 from cron.job where jobname = 'ayana-nightly-purge');

select cron.schedule('ayana-nightly-purge', '0 3 * * *', $$select purge_expired_data();$$);

select 'AYANA CLEAN SCHEMA OK · ' || now()::text as status;