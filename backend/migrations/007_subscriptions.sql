-- 007_subscriptions: Razorpay Subscription recurring billing.
-- Additive; existing billing_orders and access_grants are untouched.

-- Cache of Razorpay Plan IDs so we don't recreate them on every checkout.
CREATE TABLE IF NOT EXISTS billing_plans (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  plan         text        NOT NULL,                -- nitya / bandham / raksha
  billing      text        NOT NULL CHECK (billing IN ('month','year')),
  currency     text        NOT NULL,
  amount       integer     NOT NULL CHECK (amount >= 100), -- paise/cents × 100
  gateway_plan_id text     UNIQUE NOT NULL,         -- Razorpay plan_id
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS billing_plans_lookup
  ON billing_plans (plan, billing, currency);

-- One row per subscriber per plan attempt.
CREATE TABLE IF NOT EXISTS billing_subscriptions (
  id                      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                 uuid        NOT NULL REFERENCES users(id),
  billing_plan_id         uuid        NOT NULL REFERENCES billing_plans(id),
  gateway_subscription_id text        UNIQUE NOT NULL,  -- Razorpay subscription_id
  plan                    text        NOT NULL,
  billing                 text        NOT NULL CHECK (billing IN ('month','year')),
  currency                text        NOT NULL,
  amount                  integer     NOT NULL,
  coupon_id               uuid        REFERENCES billing_coupons(id),
  -- status mirrors Razorpay: created|authenticated|active|paused|halted|cancelled|completed|expired
  status                  text        NOT NULL DEFAULT 'created',
  -- updated by subscription.charged webhook:
  current_period_start    timestamptz,
  current_period_end      timestamptz,
  -- set when user cancels (access continues to current_period_end):
  cancel_at_period_end    boolean     NOT NULL DEFAULT false,
  cancelled_at            timestamptz,
  -- access_grant created on first charge:
  latest_grant_id         uuid        REFERENCES access_grants(id),
  is_test                 boolean     NOT NULL DEFAULT false,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS billing_subscriptions_user
  ON billing_subscriptions (user_id, status);
CREATE INDEX IF NOT EXISTS billing_subscriptions_gateway
  ON billing_subscriptions (gateway_subscription_id);
