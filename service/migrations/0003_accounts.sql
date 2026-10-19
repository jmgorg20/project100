-- Accounts for the SaaS web app: users (email + password and/or Google), sessions, email
-- verification and password reset tokens, MFA, organisations (an organisation IS a client, so it
-- gets the same quotas, queue, usage, webhooks and isolation as an API client), memberships and
-- roles, invitations, sign-up invite codes and projects.

ALTER TABLE clients ADD COLUMN kind TEXT NOT NULL DEFAULT 'integration';   -- integration | organization
ALTER TABLE uploads ADD COLUMN project_id TEXT;
ALTER TABLE uploads ADD COLUMN user_id TEXT;
ALTER TABLE jobs ADD COLUMN project_id TEXT;
ALTER TABLE jobs ADD COLUMN user_id TEXT;

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,                               -- as given (lower case)
    email_canonical TEXT NOT NULL UNIQUE,              -- one account per mailbox (dots / +tags removed)
    name TEXT,
    password_hash TEXT,                                -- NULL: signs in with Google only
    password_changed_at DOUBLE PRECISION,
    email_verified_at DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'active',             -- active | disabled
    is_admin INTEGER NOT NULL DEFAULT 0,               -- the service owner's staff (admin pages)
    mfa_secret TEXT,                                   -- encrypted TOTP secret
    mfa_enabled_at DOUBLE PRECISION,
    mfa_last_step BIGINT,                              -- a TOTP code works once
    locale TEXT,
    invite_code_id TEXT,
    signup_ip TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    last_login_at DOUBLE PRECISION
);

CREATE TABLE recovery_codes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    used_at DOUBLE PRECISION
);
CREATE INDEX recovery_codes_user ON recovery_codes (user_id);

CREATE TABLE user_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    email TEXT,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX user_identities_subject ON user_identities (provider, subject);
CREATE INDEX user_identities_user ON user_identities (user_id);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    prefix TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    client_id TEXT,                                    -- the organisation in use
    mfa_verified INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    user_agent TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    last_seen_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    revoked_at DOUBLE PRECISION
);
CREATE INDEX sessions_user ON sessions (user_id);

CREATE TABLE auth_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,                             -- verify_email | reset_password | mfa_login | oauth_state
    token_hash TEXT NOT NULL UNIQUE,
    data TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    used_at DOUBLE PRECISION
);
CREATE INDEX auth_tokens_expiry ON auth_tokens (expires_at);

CREATE TABLE memberships (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                                -- owner | admin | member
    created_at DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX memberships_pair ON memberships (client_id, user_id);
CREATE INDEX memberships_user ON memberships (user_id);

CREATE TABLE org_invites (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    email_canonical TEXT NOT NULL,
    role TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    invited_by TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    accepted_at DOUBLE PRECISION,
    revoked_at DOUBLE PRECISION
);
CREATE INDEX org_invites_client ON org_invites (client_id);

CREATE TABLE invite_codes (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    hint TEXT NOT NULL,                                -- the first characters, to recognise it
    note TEXT,
    max_uses INTEGER NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    expires_at DOUBLE PRECISION,
    created_by TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    revoked_at DOUBLE PRECISION
);

CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_by TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX projects_client ON projects (client_id, created_at);
CREATE INDEX jobs_project ON jobs (client_id, project_id);

CREATE TABLE email_outbox (
    id TEXT PRIMARY KEY,
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT,                                         -- cleared once sent (it can hold a one-time link)
    template TEXT NOT NULL,
    status TEXT NOT NULL,                              -- pending | sent | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at DOUBLE PRECISION NOT NULL,
    last_error TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    sent_at DOUBLE PRECISION
);
CREATE INDEX email_outbox_due ON email_outbox (status, next_attempt_at);
