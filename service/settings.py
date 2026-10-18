"""Service settings, all from environment variables (never from files in the repo).

Required in production (SERVICE_ENV=production):
    SERVICE_DATABASE_URL     postgresql://... (Supabase / any Postgres)
    SERVICE_SECRET_KEY       a long random string: signs file links and hashes API keys
    SERVICE_ADMIN_TOKEN      a long random string for the admin API (its hash is compared)
    SERVICE_SIGNING_KEY_FILE a file holding the Ed25519 private key that signs job payloads
                             (`python editor.py service-admin signing-key` makes one)
    SERVICE_PUBLIC_URL       https://api.example.com (links in webhooks and results)

Optional: see Settings below (each field's env name is SERVICE_ + the field name in capitals).
"""

import os
from dataclasses import dataclass, field, fields
from pathlib import Path


class SettingsError(Exception):
    pass


def _bool(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _list(v):
    return [x.strip() for x in str(v).split(",") if x.strip()]


@dataclass
class Settings:
    env: str = "development"                 # development | test | staging | production
    database_url: str = ""                   # empty: SQLite file in data_dir
    data_dir: str = "service-data"           # SQLite file and stored files (uploads, results)
    secret_key: str = ""
    admin_token: str = ""
    signing_key_file: str = ""
    public_url: str = "http://127.0.0.1:8787"
    require_https: bool = False              # refuse plain http (behind a proxy: X-Forwarded-Proto)
    trusted_proxies: list = field(default_factory=lambda: ["127.0.0.1", "::1"])
    cors_origins: list = field(default_factory=list)
    # uploads
    max_upload_mb: int = 1024
    max_duration_seconds: int = 900
    chunk_mb: int = 8
    allowed_extensions: list = field(default_factory=lambda: [
        ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".3gp", ".jpg", ".jpeg", ".png", ".webp",
        ".wav", ".mp3", ".m4a", ".aac", ".json"])
    scan_command: str = ""                   # e.g. "clamdscan --no-summary {path}" (exit 0 = clean)
    # retention
    retention_days: float = 3.0              # uploads and results are deleted after this
    delete_after_download_hours: float = 24.0  # results: also this long after the first download
    file_link_minutes: int = 15              # signed download links expire after this
    # jobs
    job_timeout_minutes: int = 45
    lease_seconds: int = 120                 # a worker must send a heartbeat within this
    max_attempts: int = 3
    claim_wait_seconds: int = 20             # long-poll for workers
    # limits (defaults for new clients)
    rate_per_minute: int = 120
    concurrent_jobs: int = 2
    monthly_minutes: float = 300.0
    storage_mb: int = 5120
    # webhooks
    allow_private_webhooks: bool = False     # development only: webhooks to localhost / LAN
    webhook_attempts: int = 8
    # costs (USD) for the per-job cost estimate; set these to your real prices
    cost_cpu_second: float = 0.00002
    cost_gpu_second: float = 0.0004
    cost_gb_month: float = 0.021
    cost_gb_egress: float = 0.09
    # accounts (the SaaS web app)
    app_url: str = ""                        # the web app; empty: PUBLIC_URL + /app/
    web_dir: str = ""                        # the built web app; empty: web/dist next to the code
    signup_mode: str = "invite"              # invite (an invite code is needed) | open | closed; the
                                             # admin switch (service-admin signups ...) overrides it
    email_backend: str = "outbox"            # outbox (files in DATA_DIR/outbox: development) | smtp
    email_from: str = "AutoEdit <no-reply@example.com>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: str = "starttls"               # starttls | ssl
    session_days: float = 30.0               # a sign-in lasts at most this long
    session_idle_days: float = 14.0          # ... and ends after this long unused
    password_cost: int = 15                  # scrypt cost (log2 n); 15 = 32 MB per check
    captcha_provider: str = ""               # "" | turnstile | hcaptcha (sign-up, password reset, login after failures)
    captcha_secret: str = ""
    captcha_site_key: str = ""
    oauth_google_client_id: str = ""         # Google sign-in (both empty: off)
    oauth_google_client_secret: str = ""
    blocked_email_domains: list = field(default_factory=list)   # on top of the built-in disposable list
    signups_per_ip_hour: int = 5
    logins_per_ip_minute: int = 10
    login_failures_per_account: int = 10     # then that account's sign-in pauses for 15 minutes
    admin_require_mfa: bool = True           # staff need two-step sign-in for the admin pages
    require_rls: bool = False                # refuse to start unless Postgres row-level security applies
                                             # (always on in production)
    # background loops in the API process (the janitor and the webhook sender)
    background: bool = True
    log_json: bool = True

    @property
    def production(self):
        return self.env in ("production", "staging")

    @property
    def app_link(self):
        return (self.app_url or self.public_url.rstrip("/") + "/app/").rstrip("/") + "/"

    @property
    def data_path(self):
        return Path(self.data_dir).resolve()

    @classmethod
    def from_env(cls, environ=None, **overrides):
        env = os.environ if environ is None else environ
        values = {}
        for f in fields(cls):
            key = "SERVICE_" + f.name.upper()
            if key not in env:
                continue
            raw = env[key]
            try:
                if f.type is bool:
                    values[f.name] = _bool(raw)
                elif f.type is int:
                    values[f.name] = int(raw)
                elif f.type is float:
                    values[f.name] = float(raw)
                elif f.type is list:
                    values[f.name] = _list(raw)
                else:
                    values[f.name] = raw
            except ValueError:
                raise SettingsError(f"{key} must be a {f.type.__name__}, not {raw!r}")
        values.update(overrides)
        s = cls(**values)
        s.check()
        return s

    def check(self):
        problems = []
        if self.production:
            if not self.database_url.startswith(("postgres://", "postgresql://")):
                problems.append("SERVICE_DATABASE_URL must be a Postgres URL in production")
            if len(self.secret_key) < 32:
                problems.append("SERVICE_SECRET_KEY must be at least 32 characters")
            if len(self.admin_token) < 32:
                problems.append("SERVICE_ADMIN_TOKEN must be at least 32 characters")
            if not self.signing_key_file or not Path(self.signing_key_file).exists():
                problems.append("SERVICE_SIGNING_KEY_FILE must point to the job signing key")
            if not self.public_url.startswith("https://"):
                problems.append("SERVICE_PUBLIC_URL must start with https:// in production")
            if not self.require_https:
                problems.append("SERVICE_REQUIRE_HTTPS must be on in production")
            if self.allow_private_webhooks:
                problems.append("SERVICE_ALLOW_PRIVATE_WEBHOOKS must be off in production")
            if "*" in self.cors_origins:
                problems.append("SERVICE_CORS_ORIGINS must list the sites, not *")
            if self.signup_mode != "closed" and self.email_backend != "smtp":
                problems.append("SERVICE_EMAIL_BACKEND must be smtp in production (sign-up emails), or "
                                "SERVICE_SIGNUP_MODE=closed")
            if self.app_url and not self.app_url.startswith("https://"):
                problems.append("SERVICE_APP_URL must start with https:// in production")
        if self.signup_mode not in ("invite", "open", "closed"):
            problems.append("SERVICE_SIGNUP_MODE must be invite, open or closed")
        if self.email_backend not in ("outbox", "smtp"):
            problems.append("SERVICE_EMAIL_BACKEND must be outbox or smtp")
        if self.email_backend == "smtp" and not self.smtp_host:
            problems.append("SERVICE_SMTP_HOST is needed for SERVICE_EMAIL_BACKEND=smtp")
        if self.smtp_tls not in ("starttls", "ssl"):
            problems.append("SERVICE_SMTP_TLS must be starttls or ssl")
        if self.captcha_provider not in ("", "turnstile", "hcaptcha"):
            problems.append("SERVICE_CAPTCHA_PROVIDER must be empty, turnstile or hcaptcha")
        if self.captcha_provider and not self.captcha_secret:
            problems.append("SERVICE_CAPTCHA_SECRET is needed with SERVICE_CAPTCHA_PROVIDER")
        if bool(self.oauth_google_client_id) != bool(self.oauth_google_client_secret):
            problems.append("Google sign-in needs both SERVICE_OAUTH_GOOGLE_CLIENT_ID and _SECRET")
        if not 10 <= self.password_cost <= 20:
            problems.append("SERVICE_PASSWORD_COST must be between 10 and 20")
        if problems:
            raise SettingsError("Service settings problems:\n  - " + "\n  - ".join(problems))
