-- The headless service: clients (each with its own API keys, presets, quotas and webhooks),
-- uploads, jobs and their events and outputs, workers, usage, releases, flags and the audit log.
-- Portable SQL (Postgres and SQLite): TEXT ids, DOUBLE PRECISION epoch seconds, INTEGER 0/1.

CREATE TABLE clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',             -- active | suspended
    channel TEXT NOT NULL DEFAULT 'stable',            -- stable | beta
    rate_per_minute INTEGER NOT NULL,
    concurrent_jobs INTEGER NOT NULL,
    monthly_minutes DOUBLE PRECISION NOT NULL,
    storage_mb INTEGER NOT NULL,
    gpu_allowed INTEGER NOT NULL DEFAULT 0,
    retention_days DOUBLE PRECISION NOT NULL,
    delete_after_download_hours DOUBLE PRECISION NOT NULL,
    presets TEXT,                                      -- JSON list of allowed preset ids, NULL = all
    default_preset TEXT,
    notes TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE api_keys (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    prefix TEXT NOT NULL UNIQUE,
    key_hash TEXT NOT NULL,
    name TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    last_used_at DOUBLE PRECISION,
    expires_at DOUBLE PRECISION,
    revoked_at DOUBLE PRECISION
);
CREATE INDEX api_keys_client ON api_keys (client_id);

CREATE TABLE uploads (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    kind TEXT,                                         -- video | image | audio | project
    size_expected BIGINT NOT NULL,
    size_received BIGINT NOT NULL DEFAULT 0,
    sha256 TEXT,
    status TEXT NOT NULL,                              -- uploading | ready | rejected | deleted
    path TEXT,
    media TEXT,                                        -- JSON: what ffprobe found
    duration DOUBLE PRECISION,
    error TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    deleted_at DOUBLE PRECISION
);
CREATE INDEX uploads_client ON uploads (client_id, created_at);
CREATE INDEX uploads_expiry ON uploads (status, expires_at);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                                -- polish | render
    queue TEXT NOT NULL,                               -- cpu | gpu
    channel TEXT NOT NULL,                             -- stable | beta
    status TEXT NOT NULL,                              -- queued | running | succeeded | failed | cancelled
    priority INTEGER NOT NULL DEFAULT 100,
    params TEXT NOT NULL,                              -- JSON
    inputs TEXT NOT NULL,                              -- JSON: role -> [upload ids]
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    timeout_seconds INTEGER NOT NULL,
    worker_id TEXT,
    lease_expires_at DOUBLE PRECISION,
    not_before DOUBLE PRECISION NOT NULL DEFAULT 0,
    started_at DOUBLE PRECISION,
    finished_at DOUBLE PRECISION,
    progress DOUBLE PRECISION,
    stage TEXT,
    error TEXT,
    result TEXT,                                       -- JSON: the sidecar (status, qc, opinions...)
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    input_minutes DOUBLE PRECISION NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    expiry_warned INTEGER NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    deleted_at DOUBLE PRECISION
);
CREATE INDEX jobs_claim ON jobs (status, queue, channel, priority, created_at);
CREATE INDEX jobs_client ON jobs (client_id, created_at);
CREATE UNIQUE INDEX jobs_idempotency ON jobs (client_id, idempotency_key);

CREATE TABLE job_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    seq BIGINT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT,
    at DOUBLE PRECISION NOT NULL
);
CREATE INDEX job_events_job ON job_events (job_id, seq);

CREATE TABLE outputs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                                -- video | project | sidecar | plan
    path TEXT,
    size BIGINT NOT NULL,
    sha256 TEXT NOT NULL,
    content_type TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    first_download_at DOUBLE PRECISION,
    deleted_at DOUBLE PRECISION
);
CREATE UNIQUE INDEX outputs_job_name ON outputs (job_id, name);
CREATE INDEX outputs_expiry ON outputs (expires_at);

CREATE TABLE workers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_prefix TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL,
    queues TEXT NOT NULL,                              -- JSON list: cpu, gpu
    channel TEXT NOT NULL,                             -- stable | beta
    status TEXT NOT NULL DEFAULT 'active',             -- active | revoked
    engine_version TEXT,
    info TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    last_seen_at DOUBLE PRECISION,
    revoked_at DOUBLE PRECISION
);

CREATE TABLE webhooks (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,                              -- encrypted with the service key
    events TEXT NOT NULL,                              -- JSON list, or ["*"]
    active INTEGER NOT NULL DEFAULT 1,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX webhooks_client ON webhooks (client_id);

CREATE TABLE webhook_deliveries (
    id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL,
    event TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,                              -- pending | delivered | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at DOUBLE PRECISION NOT NULL,
    last_status INTEGER,
    last_error TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    delivered_at DOUBLE PRECISION
);
CREATE INDEX webhook_deliveries_due ON webhook_deliveries (status, next_attempt_at);

CREATE TABLE usage (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    job_id TEXT,
    month TEXT NOT NULL,                               -- YYYY-MM (UTC)
    kind TEXT NOT NULL,                                -- job | egress | storage
    input_minutes DOUBLE PRECISION NOT NULL DEFAULT 0,
    output_minutes DOUBLE PRECISION NOT NULL DEFAULT 0,
    cpu_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    gpu_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    wall_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    storage_bytes BIGINT NOT NULL DEFAULT 0,
    egress_bytes BIGINT NOT NULL DEFAULT 0,
    transcription_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    ai_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX usage_client_month ON usage (client_id, month);

CREATE TABLE rate_counters (
    key TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (key, window_start)
);

CREATE TABLE releases (
    version TEXT PRIMARY KEY,
    tests_passed INTEGER NOT NULL DEFAULT 0,
    report TEXT,
    registered_at DOUBLE PRECISION NOT NULL,
    promoted_at DOUBLE PRECISION
);

CREATE TABLE settings_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE flags (
    name TEXT PRIMARY KEY,
    stable INTEGER NOT NULL DEFAULT 0,
    beta INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE audit_log (
    id TEXT PRIMARY KEY,
    at DOUBLE PRECISION NOT NULL,
    actor TEXT NOT NULL,                               -- admin | client:<id> | worker:<id> | system
    action TEXT NOT NULL,
    target TEXT,
    details TEXT,
    ip TEXT
);
CREATE INDEX audit_log_at ON audit_log (at);
