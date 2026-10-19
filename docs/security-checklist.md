# Security checklist · Listahan ng seguridad

Each item of the security requirements, where it is in the code, how it is checked, and what **you**
(the owner) still have to do before and after going live. ✅ = built and tested here; 🧑 = your job.
The reasons behind them are in [threat-model.md](threat-model.md).

*✅ = gawa na at nasubukan; 🧑 = ikaw ang gagawa.*

## Before you open sign-ups · Bago buksan ang sign-up

| | Item | Where / how | Check |
|---|---|---|---|
| ✅ | HTTPS only | Caddy gets certificates (`deploy/Caddyfile`); production refuses `SERVICE_REQUIRE_HTTPS=false` and an `http://` public URL; HSTS header | `test_api.py::test_production_settings_refuse_weak_configuration` |
| 🧑 | | point the domain, open ports 80/443 only, check `https://API_DOMAIN/healthz` | [going-live.md](going-live.md) step 2 |
| ✅ | Secrets from env / secret store | `service/settings.py` reads only the environment; the signing key is a mounted file; production refuses short secrets; gitleaks in CI | `test_api.py::test_production_settings_refuse_weak_configuration`, CI "security" job |
| 🧑 | | make every `CHANGE_ME` in `deploy/.env` a long random value; never commit `deploy/.env` or `deploy/secrets/` | |
| ✅ | Password hashing | scrypt (`service/passwords.py`), password policy | `test_accounts.py::test_password_rules` |
| ✅ | Email verification | nothing runs before the email is confirmed | `test_accounts.py::test_verify_then_sign_in` |
| 🧑 | | an SMTP provider with SPF / DKIM for your domain (emails land in spam otherwise) | |
| ✅ | MFA for admin | staff need two-step sign-in (TOTP) for the admin pages; recovery codes | `test_accounts.py::test_staff_need_two_step_sign_in_for_the_admin_pages` |
| 🧑 | | turn it on for yourself and every staff member; keep the recovery codes offline | |
| ✅ | Rate limiting and bot protection on sign-up / sign-in / upload | per address and per client limits, a honeypot field, captcha (Turnstile / hCaptcha) | `test_accounts.py::test_sign_in_and_sign_up_are_limited_per_address`, `::test_captcha_…`, `test_api.py::test_per_client_rate_limit` |
| 🧑 | | create a Turnstile site key and set `SERVICE_CAPTCHA_*` | |
| ✅ | Strict input validation | every route checks its JSON (types, lengths, allowed values); project files against the schema | `test_api.py::test_job_validation_and_quotas`, `test_safety.py` |
| ✅ | Signed URLs with short expiry | result links: one file, `SERVICE_FILE_LINK_MINUTES` (15) | `test_api.py::test_full_flow_with_signed_links`, `test_threats.py::test_T3_leaked_file_link…` |
| ✅ | Per-tenant isolation tests | filters + Postgres row-level security | `test_rls.py`, `test_api.py::test_clients_never_see_each_others_things` |
| 🧑 | | after deploying, `/readyz` must say `"rls": "enforced"` | |
| ✅ | Upload scanning, size and duration limits | type allowlist, ffprobe, `SERVICE_MAX_UPLOAD_MB`, `SERVICE_MAX_DURATION_SECONDS`, `SERVICE_SCAN_COMMAND`, `SERVICE_MODERATION_COMMAND` (fail closed) | `test_api.py::test_bad_files_are_rejected`, `test_safety.py::test_the_content_check_refuses_uploads` |
| 🧑 | | optional: install ClamAV and set `SERVICE_SCAN_COMMAND=clamdscan --no-summary {path}` | |
| ✅ | Sandboxed workers | read-only container, all capabilities dropped, `no-new-privileges`, no ports, its own network (no database), no shell from user data (argument lists only), signed jobs | `test_threats.py::test_T4_…`, `deploy/docker-compose.yml` |
| 🧑 | | a worker on your PC: run it as a normal Windows user; revoke its token if the PC is lost | [service.md](service.md) |
| ✅ | Dependency and container vulnerability scanning in CI | pip-audit, npm audit (desktop, web), Grype on both images (critical, fixable), gitleaks; no model weights | `.github/workflows/ci.yml` |
| ✅ | Security headers | CSP (the API: `default-src 'none'`; the web app its own strict CSP), HSTS, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy` | `test_api.py::test_security_headers_https_and_body_limits`, `::test_the_web_app_route` |
| ✅ | CORS allowlist | `SERVICE_CORS_ORIGINS` (production refuses `*`) | `test_api.py::test_production_settings_refuse_weak_configuration` |
| ✅ | Audit logs | every admin and account action, with who and from where; kept `SERVICE_AUDIT_RETENTION_DAYS` | `test_admin.py::test_audit_filters`, `test_safety.py::test_old_audit_entries…` |
| ✅ | Backups with a restore test | `deploy/backup.sh`, `deploy/restore.sh --check` | `test_backup.py` (real Postgres) |
| 🧑 | | schedule `backup.sh` daily, copy backups off the server, run `restore.sh --check` monthly | [runbook.md](runbook.md) |
| ✅ | DDoS / abuse limits | rate limits, quotas, max waiting jobs, body size limits | `test_threats.py::test_T5_cost_exhaustion_limits` |
| 🧑 | | put the domain behind Cloudflare (or your host's DDoS protection); spending alerts at Groq / Anthropic / your host | |
| ✅ | Admin actions logged | `service/routes_admin.py` writes each change; staff appear as `admin:<user id>` | `web/tests/admin.spec.ts` |
| ✅ | Threat model, with tests for the main threats | [threat-model.md](threat-model.md), `tests/service/test_threats.py` | |
| 🧑 | Legal | replace the DRAFT pages (terms, privacy, acceptable use, refunds, AI) after a lawyer reads them; register with the National Privacy Commission if required; name a DPO | `web/public/*.html` |

## Every month · Buwan-buwan

- 🧑 Rebuild and redeploy the images (security updates), after CI is green.
- 🧑 `deploy/restore.sh --check` on the latest backup.
- 🧑 Look at Admin → System → audit log for actions you do not recognise; Admin → Reports is empty or handled.
- 🧑 Check Admin → Costs against your real bills (Groq, Anthropic, host) and adjust `SERVICE_COST_*`.
- 🧑 Remove staff who left (Admin → Users) and revoke unused API keys and worker tokens.

## Every year, or when someone leaves or a server is compromised

- 🧑 Rotate the admin token, the database password, the Paddle and AI keys, and the SMTP password
  ([runbook.md](runbook.md) "A secret leaked").

## Not verified here

No penetration test by an outside party was done. The production deployment (real domain, Caddy
certificates, Cloudflare, real SMTP, Paddle live mode, a real VPS network) was not run in this
repository's tests; the container tests run the images locally with Postgres.
