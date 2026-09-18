-- Additive billing ledger. Existing Stripe transactions/access are preserved.
ALTER TABLE payment_state ADD COLUMN IF NOT EXISTS billing_managed boolean NOT NULL DEFAULT false;
ALTER TABLE payment_state ADD COLUMN IF NOT EXISTS trial_started_at timestamptz;
ALTER TABLE payment_state ADD COLUMN IF NOT EXISTS trial_ends_at timestamptz;
ALTER TABLE payment_state ADD COLUMN IF NOT EXISTS legacy_paid_plan text;
UPDATE payment_state SET legacy_paid_plan=plan WHERE legacy_paid_plan IS NULL AND status IN ('active','paid','trialing');

CREATE TABLE IF NOT EXISTS billing_coupons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), label text UNIQUE NOT NULL,
  code_hash text UNIQUE NOT NULL, code_hint text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('lifetime','annual_discount')),
  percent integer NOT NULL CHECK (percent BETWEEN 1 AND 100),
  allowed_email text, active boolean NOT NULL DEFAULT false,
  reserved_by uuid REFERENCES users(id), reserved_order_id uuid,
  redeemed_by uuid REFERENCES users(id), redeemed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_lifetime_gift_per_email ON billing_coupons(lower(allowed_email)) WHERE kind='lifetime' AND allowed_email IS NOT NULL;
CREATE TABLE IF NOT EXISTS billing_orders (
  id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
  idempotency_key uuid NOT NULL, plan text NOT NULL, billing text NOT NULL CHECK (billing IN ('month','year')),
  currency text NOT NULL, subtotal integer NOT NULL CHECK (subtotal>=100),
  discount integer NOT NULL CHECK (discount>=0), amount integer NOT NULL CHECK (amount>=0),
  coupon_id uuid REFERENCES billing_coupons(id), status text NOT NULL DEFAULT 'creating',
  gateway_order_id text UNIQUE, gateway_payment_id text UNIQUE,
  is_test boolean NOT NULL, detail text, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), verified_at timestamptz,
  UNIQUE(user_id,idempotency_key), CHECK (subtotal-discount=amount)
);
CREATE INDEX IF NOT EXISTS billing_orders_pending ON billing_orders(status,created_at);
CREATE TABLE IF NOT EXISTS access_grants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id),
  order_id uuid UNIQUE NOT NULL REFERENCES billing_orders(id), plan text NOT NULL,
  starts_at timestamptz NOT NULL, ends_at timestamptz,
  revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS access_grants_owner ON access_grants(user_id,starts_at,ends_at);