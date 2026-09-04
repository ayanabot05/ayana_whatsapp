-- ============================================================================
-- AYANA — Postgres schema for Supabase - FIXED
-- ============================================================================

create extension if not exists pgcrypto;

-- Drop existing if you are re-running (reverse dependency order)
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
    id                  uuid primary key default gen_random_uuid(),
    name                text not null,
    email               text not null unique,
    phone               text not null,
    password_hash       text not null,
    role                text not null default 'user' check (role in ('user', 'admin')),
    onboarding_complete boolean not null default false,
    city                text,
    timezone            text not null default 'Asia/Kolkata',
    household_owner_id  uuid references users(id),
    created_at          timestamptz not null default now(),
    deleted_at          timestamptz
);
create index idx_users_household_owner on users(household_owner_id);

-- ============================================================================
-- PARENTS
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
    birthday                 text,
    nicknames                jsonb not null default '[]',
    habits                   jsonb,
    medicine_list            jsonb not null default '[]',
    stories                  jsonb not null default '[]',
    activity_window_start    text,
    activity_window_end      text,
    auto_activity_detection  boolean not null default true,
    emergency_contacts       jsonb not null default '[]',
    recovery_mode            boolean not null default false,
    recovery_until           timestamptz,
    created_at               timestamptz not null default now(),
    deleted_at               timestamptz
);
create index idx_parents_phone on parents(phone);
create index idx_parents_user on parents(user_id);

-- ============================================================================
-- SCHEDULES
-- ============================================================================
create table schedules (
    id                   uuid primary key default gen_random_uuid(),
    parent_id            uuid not null references parents(id) on delete cascade,
    user_id              uuid not null references users(id) on delete cascade,
    mode                 text not null default 'nitya' check (mode in ('nitya', 'bandham', 'raksha')),
    messages             jsonb not null default '[]',
    active               boolean not null default true,
    recovery_mode        boolean not null default false,
    recovery_until       text,
    reengagement_hours   integer not null default 4,
    created_at           timestamptz not null default now(),
    deleted_at           timestamptz
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
    day_key        text not null,
    message_index  integer,
    category       text,
    msg_type       text,
    status         text,
    skipped        boolean not null default false,
    escalation_of  uuid,
    attempt        integer,
    kind           text,
    created_at     timestamptz not null default now()
);
create index idx_msglogs_sched_idx_day on message_logs(schedule_id, message_index, day_key);
create index idx_msglogs_parent_day on message_logs(parent_id, day_key);

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
    id                  uuid primary key default gen_random_uuid(),
    parent_id           uuid not null unique references parents(id) on delete cascade,
    opener_sent_at       timestamptz,
    reengagement_sent    boolean not null default false,
    updated_at           timestamptz not null default now()
);
create index idx_wasessions_reeng on wa_sessions(opener_sent_at, reengagement_sent);

-- ============================================================================
-- PHONE_OTPS + CIRCLE_INVITES
-- ============================================================================
create table phone_otps (
    phone        text primary key,
    otp_hash     text not null,
    attempts     integer not null default 0,
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null
);

create table circle_invites (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references users(id) on delete cascade,
    email        text not null,
    token        text not null unique,
    status       text not null default 'pending' check (status in ('pending', 'accepted', 'cancelled')),
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null
);
create index idx_circleinvites_user on circle_invites(user_id);

-- ============================================================================
-- DISTRESS_LOGS + PARENT_REPLIES + EMERGENCY_EVENTS
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

create table parent_replies (
    id           uuid primary key default gen_random_uuid(),
    parent_id    uuid not null references parents(id) on delete cascade,
    intent       text,
    text         text,
    is_voice     boolean not null default false,
    created_at   timestamptz not null default now()
);
create index idx_parentreplies_parent_created on parent_replies(parent_id, created_at);
create index idx_parentreplies_intent on parent_replies(parent_id, intent);

create table emergency_events (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references users(id) on delete cascade,
    parent_id    uuid not null references parents(id) on delete cascade,
    source       text,
    detail       text,
    status       text not null default 'open' check (status in ('open', 'resolved', 'false_positive')),
    created_at   timestamptz not null default now(),
    resolved_at  timestamptz
);
create index idx_emergencyevents_parent on emergency_events(parent_id, created_at desc);

-- ============================================================================
-- MOMENTS
-- ============================================================================
create table moments (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references users(id) on delete cascade,
    parent_id    uuid not null references parents(id) on delete cascade,
    text         text,
    created_at   timestamptz not null default now()
);
create index idx_moments_parent on moments(parent_id, created_at desc);

create table moment_images (
    id           uuid primary key default gen_random_uuid(),
    moment_id    uuid not null references moments(id) on delete cascade,
    storage_path text not null,
    created_at   timestamptz not null default now()
);

-- ============================================================================
-- MONTHLY_REPORTS + JWT_BLACKLIST + PAYMENTS
-- ============================================================================
create table monthly_reports (
    id                      uuid primary key default gen_random_uuid(),
    user_id                 uuid not null references users(id) on delete cascade,
    parent_id               uuid not null references parents(id) on delete cascade,
    plan                    text,
    period                  text not null,
    total_touches           integer not null default 0,
    delivered               integer not null default 0,
    skipped                 integer not null default 0,
    voice_replies           integer not null default 0,
    mood_graph              jsonb,
    trend_note              text,
    shared_with_care_circle boolean not null default false,
    generated_at            timestamptz not null default now(),
    unique (user_id, parent_id, period)
);

create table jwt_blacklist (
    jti          text primary key,
    expires_at   timestamptz not null,
    revoked_at   timestamptz not null default now()
);

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

create table template_variants_cache (
    id            uuid primary key default gen_random_uuid(),
    category      text not null,
    language      text not null,
    variants      jsonb not null,
    source        text,
    generated_at  timestamptz not null default now(),
    unique (category, language)
);

create table activation_state (
    user_id            uuid primary key references users(id) on delete cascade,
    whatsapp_activated boolean not null default false,
    activated_at       timestamptz
);

create table consent_logs (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid references users(id) on delete cascade,
    parent_id     uuid references parents(id) on delete cascade,
    consent_type  text not null check (consent_type in ('child', 'parent')),
    agreed        boolean not null,
    text          text,
    created_at    timestamptz not null default now()
);

-- FIXED: server.py uses meta, not detail
create table audit_logs (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid references users(id) on delete set null,
    action       text not null,
    meta         jsonb,
    detail       jsonb,
    created_at   timestamptz not null default now()
);
create index idx_auditlogs_user on audit_logs(user_id, created_at desc);

create table preferences (
    user_id             uuid primary key references users(id) on delete cascade,
    emergency_keywords  jsonb not null default '[]',
    daily_summary       boolean not null default true,
    email_notifications boolean not null default true,
    whatsapp_reports    boolean not null default true
);

create table scheduler_locks (
    lock_name    text primary key,
    holder       text,
    acquired_at  timestamptz not null default now(),
    expires_at   timestamptz not null
);

-- ============================================================================
-- PURGE FUNCTION - run nightly via Dashboard > pg_cron
-- ============================================================================
create or replace function purge_expired_data() returns void as $$
begin
    delete from phone_otps      where expires_at < now();
    delete from circle_invites  where expires_at < now();
    delete from jwt_blacklist   where expires_at < now();
    delete from scheduler_locks where expires_at < now();

    delete from message_logs
    where created_at < now() - interval '45 days'
      and exists (
          select 1 from monthly_reports mr
          where mr.parent_id = message_logs.parent_id
            and mr.period = to_char(message_logs.created_at, 'YYYY-MM')
      );

    delete from parent_replies
    where created_at < now() - interval '45 days'
      and exists (
          select 1 from monthly_reports mr
          where mr.parent_id = parent_replies.parent_id
            and mr.period = to_char(parent_replies.created_at, 'YYYY-MM')
      );
end;
$$ language plpgsql;

-- After enabling pg_cron in Supabase Dashboard > Extensions, run this separately:
-- select cron.schedule('ayana-nightly-purge', '0 3 * * *', $$select purge_expired_data();$$);