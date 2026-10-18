-- Billing for the web app's organisations: plans (prices and limits are data, not code), one
-- subscription per organisation (trial, active, past due, canceled, expired), the payment
-- provider's webhook events (each applied once), payments (kept for the accounts, also after an
-- organisation is deleted) and trial claims (hashes of email / device / payment card, so a trial is
-- given once; kept after an account is deleted, for fraud prevention). No card data is stored.

CREATE TABLE plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_tl TEXT,
    description TEXT,
    description_tl TEXT,
    price_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    billing_interval TEXT NOT NULL,                    -- month | year
    monthly_minutes DOUBLE PRECISION NOT NULL,
    storage_mb INTEGER NOT NULL,
    concurrent_jobs INTEGER NOT NULL,
    rate_per_minute INTEGER NOT NULL,
    gpu_allowed INTEGER NOT NULL DEFAULT 0,
    retention_days DOUBLE PRECISION NOT NULL,
    provider_price_id TEXT,                            -- the payment provider's price id
    active INTEGER NOT NULL DEFAULT 1,
    public INTEGER NOT NULL DEFAULT 1,                 -- shown to users (private plans: given by the admin)
    sort INTEGER NOT NULL DEFAULT 100,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE subscriptions (
    client_id TEXT PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
    plan_id TEXT,
    status TEXT NOT NULL,                              -- none | trialing | active | past_due | canceled | expired
    trial_ends_at DOUBLE PRECISION,
    current_period_end DOUBLE PRECISION,
    grace_until DOUBLE PRECISION,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    provider TEXT,
    provider_customer_id TEXT,
    provider_subscription_id TEXT,
    last_event_at DOUBLE PRECISION,                    -- older provider events never undo newer ones
    reminded INTEGER NOT NULL DEFAULT 0,               -- "trial ends soon" email sent
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX subscriptions_status ON subscriptions (status);
CREATE INDEX subscriptions_provider ON subscriptions (provider, provider_subscription_id);

CREATE TABLE billing_events (
    id TEXT PRIMARY KEY,                               -- provider:event id (a repeated delivery is ignored)
    provider TEXT NOT NULL,
    event_type TEXT NOT NULL,
    client_id TEXT,
    occurred_at DOUBLE PRECISION,
    received_at DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,                              -- applied | ignored | failed
    detail TEXT
);
CREATE INDEX billing_events_client ON billing_events (client_id, received_at);

CREATE TABLE payments (
    id TEXT PRIMARY KEY,                               -- provider:transaction id
    client_id TEXT NOT NULL,                           -- no foreign key: the accounts keep it
    provider TEXT NOT NULL,
    plan_id TEXT,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,                              -- paid | failed | refunded
    occurred_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX payments_client ON payments (client_id, occurred_at);
CREATE INDEX payments_time ON payments (occurred_at);

CREATE TABLE trial_claims (
    kind TEXT NOT NULL,                                -- email | device | card
    value_hash TEXT NOT NULL,
    client_id TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (kind, value_hash)
);
