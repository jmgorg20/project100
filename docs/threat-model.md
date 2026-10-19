# Threat model · Mga banta at panlaban

What could go wrong with the cloud service (the API, the web app, the workers, billing), what stops
it, where that is tested, and what is left for you to do. Ids (T1…) are used in the tests
(`tests/service/test_threats.py`) and in [security-checklist.md](security-checklist.md).

*Sa madaling salita: bawat banta, ano ang pumipigil dito, saan ito sinubukan, at ano pa ang dapat
mong gawin bilang may-ari.*

## What we protect

| Asset | Why it matters |
|---|---|
| Customers' videos and results | private; may show people and places |
| Accounts, sessions, API keys, the admin token | whoever has them acts as that person / client / you |
| `SERVICE_SECRET_KEY`, the job signing key, database password, Paddle and AI keys | they unlock everything above, or cost money |
| Money: AI services, CPU / GPU time, storage, bandwidth | each video costs you; abuse costs more |
| The database (accounts, billing, audit log) and its backups | business records, personal data |
| Trust: what is made and shared with the service | illegal content, copyright, deepfakes |

## Who might attack

Someone after free use (trial farming), a customer trying to see another customer's files, a bot
filling sign-ups or uploads, someone with a stolen key, a hostile file built to break FFmpeg or the
browser that renders graphics, a person who gets into a worker machine (for example your own PC),
someone sharing illegal material through result links, and a careless or rogue staff member.

## Threats, mitigations, tests

### T1 · Abuse of free trials

- **Mitigations:** sign-up is invite-only at first (`SERVICE_SIGNUP_MODE=invite`) and can be paused
  in one click (Admin → Sign-ups, or `service-admin signups closed`); one trial per person: the
  email in its canonical form (Gmail dots and `+tags` removed), the browser's device id, and the
  card (type, last 4, expiry) are kept only as keyed hashes in `trial_claims`, and a match gives no
  trial; disposable email domains are refused; sign-up per address is limited
  (`SERVICE_SIGNUPS_PER_IP_HOUR`); captcha (Turnstile / hCaptcha) on sign-up; the email must be
  confirmed before anything runs; trial limits are small and configurable (`SERVICE_TRIAL_*`).
- **Tests:** `test_billing.py::test_one_trial_per_email_and_per_device`,
  `test_accounts.py::test_signup_needs_an_invite_code_and_can_be_paused`,
  `::test_sign_in_and_sign_up_are_limited_per_address`, `::test_captcha_on_signup_reset_and_after_failed_sign_ins`,
  `::test_email_rules` (disposable domains).
- **Left:** a determined person with many emails, browsers and cards can still get several trials.
  Watch Admin → Overview (sign-ups, trials) and keep invite-only until you see the pattern.

### T2 · Malicious files

- **Mitigations:** only listed file types; size (`SERVICE_MAX_UPLOAD_MB`) and length
  (`SERVICE_MAX_DURATION_SECONDS`) limits; the checksum must match; every file is read by ffprobe
  and refused if it is not really a video / picture / sound; an optional virus scan
  (`SERVICE_SCAN_COMMAND`) and content check (`SERVICE_MODERATION_COMMAND`) that refuse the file
  when they cannot run (fail closed); files are stored under random ids, never under the name the
  person gave; programs are run with argument lists, never through a shell; project files are
  checked against the schema and may only point to the same client's uploads and results; the
  worker runs in a read-only container with no Linux capabilities, `no-new-privileges`, no open
  ports and its own network (no route to the database).
- **Tests:** `test_api.py::test_bad_files_are_rejected`, `::test_render_job_media_must_be_the_clients_own`,
  `test_threats.py::test_T2_hostile_file_names_are_harmless`, `test_safety.py::test_the_content_check_refuses_uploads`,
  `test_containers.py` (the real images, with the real engine; run with `AUTOEDIT_CONTAINER_TEST=1`).
- **Left:** a new FFmpeg or Chromium bug could still be exploited by a crafted file. Keep the images
  updated (CI scans them with Grype and fails on fixable critical issues); rebuild monthly.

### T3 · Key theft

- **Mitigations:** API keys, sign-in tokens, worker tokens and the admin token are stored only as
  keyed hashes (a copy of the database gives no working key); API keys are shown once, can expire,
  be revoked, or rotated with a grace period; wrong keys are slowed down per address; webhook
  secrets are encrypted at rest; sign-in cookies are HttpOnly, SameSite, `__Host-` over HTTPS, with
  a CSRF token and an Origin check; staff need two-step sign-in for the admin pages; result links
  are signed, open one file, and expire (`SERVICE_FILE_LINK_MINUTES`); secrets come only from the
  environment / secret files (never the repository: gitleaks checks every push); the job signing
  private key stays on the API, workers have only the public key.
- **Tests:** `test_threats.py::test_T3_stolen_database_holds_no_usable_keys`,
  `::test_T3_leaked_file_link_opens_one_file_for_a_short_time`, `test_api.py::test_revoke_rotate_suspend`,
  `::test_wrong_keys_are_slowed_down`, `::test_full_flow_with_signed_links`, `test_accounts.py` (sessions, CSRF,
  two-step sign-in), `test_admin.py::test_only_admins_see_the_money`.
- **Left:** whoever controls the API server has every secret. Keep the server patched, SSH by key
  only, and follow [runbook.md](runbook.md) "A secret leaked".

### T4 · Worker takeover

- **Mitigations:** a worker token works only on the worker API (not the client or admin API); a
  worker can read only the inputs of the job it holds, and only while it holds it; it cannot finish
  someone else's job; revoked workers stop at once; every job is signed by the service and the
  worker refuses unsigned, re-signed or tampered jobs (so a fake server cannot make your PC run
  commands); job ids are checked before they become folder names; the worker container is
  hardened as in T2 and has no database credentials.
- **Tests:** `test_api.py::test_worker_can_only_touch_its_running_job`,
  `test_threats.py::test_T4_a_worker_token_is_not_a_client_or_admin_key`,
  `::test_T4_the_worker_refuses_jobs_the_service_did_not_sign`, `test_worker.py` (the real agent).
- **Left:** a taken-over worker sees the videos of the jobs it runs and could return a bad result.
  Run workers only on machines you control; on your Windows PC, run the worker as a normal user
  (not administrator) and revoke its token if the PC is lost (`service-admin worker-revoke`).

### T5 · Cost-exhaustion attacks

- **Mitigations:** per-client request rate (`rate_per_minute`) and per-address limits; minutes per
  month (queued and running jobs count before they finish); jobs at a time; at most
  `SERVICE_MAX_QUEUED_JOBS` waiting per client (so one backlog cannot hold up others); storage
  quota; upload size and length; jobs that run too long are stopped (lease / timeout); download
  bytes are counted per client; the trial is small; the admin pages show cost against revenue per
  client; request bodies are size-limited.
- **Tests:** `test_api.py::test_per_client_rate_limit`, `::test_storage_quota`, `::test_job_validation_and_quotas`,
  `::test_security_headers_https_and_body_limits`, `test_threats.py::test_T5_cost_exhaustion_limits`,
  `test_billing.py` (plan limits, the trial ending).
- **Left:** a flood from many addresses (DDoS) must be stopped before it reaches the server: put the
  domain behind Cloudflare (free plan) or your host's protection. Set spending limits / alerts at
  Groq, Anthropic and your host.

### T6 · One customer reaching another's data

- **Mitigations:** every query filters by the client; on Postgres, row-level security is a second
  wall (the service connects as an ordinary user and refuses to start in production if the policies
  would not apply); ids are random.
- **Tests:** `test_api.py::test_clients_never_see_each_others_things`, `test_rls.py` (every tenant table),
  `test_accounts.py` (organisation membership and roles).

### T7 · Account takeover

- **Mitigations:** scrypt password hashes and a password policy; captcha after failed sign-ins;
  email confirmation; single-use, short-lived reset links; changing the password signs out other
  devices; two-step sign-in with recovery codes; Google sign-in with PKCE, a state bound to the
  browser, and only verified Google emails; an unconfirmed sign-up cannot reserve someone's email.
- **Tests:** `test_accounts.py`.

### T8 · Illegal or harmful content

- **Mitigations:** consent to the terms at sign-up (the version is kept); the acceptable-use rules;
  anyone with a link can report a result; child-safety reports, or reports from three addresses,
  hold the file at once; staff dismiss / remove / suspend; child-safety evidence is kept on hold
  (not deleted by expiry or by its owner) until purged; an optional content check on uploads;
  results are labelled "Edited with AI". See [safety.md](safety.md).
- **Tests:** `test_safety.py`, `web/tests/safety.spec.ts`.
- **Left:** a person must review reports quickly (see the runbook); the legal pages are drafts.

### T9 · The service used to reach private addresses (SSRF)

- **Mitigations:** webhook addresses must be public (private / local addresses refused, and the
  connection goes to the address that was checked); redirects are not followed.
- **Tests:** `test_api.py::test_webhook_addresses_are_checked`.

### T10 · Forged or replayed payment messages

- **Mitigations:** Paddle webhooks need a valid signature made within 5 minutes; each event is
  applied once; an older event cannot undo a newer one; production refuses the test provider.
- **Tests:** `test_billing.py::test_webhooks_are_signed_fresh_and_applied_once`, `::test_late_events_do_not_undo_newer_ones`,
  `::test_production_refuses_the_fake_provider`.

### T11 · A bad dependency or image (supply chain)

- **Mitigations:** lockfiles; CI runs pip-audit, npm audit, gitleaks, and Grype on both images
  (actions pinned to commits); no model weights are shipped or downloaded by the images
  (`scripts/check_no_weights.py` in CI).
- **Left:** update dependencies regularly; read the CI security job when it fails.

### T12 · Staff misuse and mistakes

- **Mitigations:** staff need two-step sign-in; every admin action is in the audit log with who did
  it; the audit log is kept `SERVICE_AUDIT_RETENTION_DAYS`; destructive admin actions ask first.
- **Tests:** `test_admin.py::test_audit_filters`, `web/tests/admin.spec.ts`.

### T13 · Losing the database

- **Mitigations:** `deploy/backup.sh` (daily, optionally encrypted) and `deploy/restore.sh --check`
  (the restore test); the restore keeps row-level security.
- **Tests:** `test_backup.py` (a real backup and restore on Postgres).
- **Left:** schedule the backup, copy it off the server, run the restore test monthly.

## Not covered here

The desktop app (it runs on the person's own PC with their own keys), physical security of your
PC, and your hosting provider's own security.
