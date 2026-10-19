# Runbook: running the service day to day · Gabay sa pagpapatakbo

What to look at, and what to do when something goes wrong. Commands assume the docker-compose
setup in `deploy/` on one VPS (see [service.md](service.md)); `admin` below means
`docker compose -f deploy/docker-compose.yml exec api python editor.py service-admin`.

*Bawat seksyon: ano ang makikita, ano ang gagawin. Kung hindi sigurado, i-pause muna ang sign-ups
(Admin → Sign-ups → Paused): hindi nito ginagalaw ang mga kasalukuyang customer.*

## Environments · Mga environment

| | Development | Staging | Production |
|---|---|---|---|
| `SERVICE_ENV` | `development` | `production` (same checks) | `production` |
| Database | SQLite (automatic) | its own Postgres / Supabase project | Postgres / Supabase |
| Billing | `fake` | Paddle **sandbox** | Paddle **production** |
| Email | `outbox` (files) | SMTP to your own address | SMTP |
| Data | test data | test data only, never customers' videos | real |

Each has its own `deploy/.env` and its own secrets: never copy production secrets to staging.

## What to watch · Ano ang binabantayan

| Signal | Where | Normal |
|---|---|---|
| Alive | `GET /healthz` | `{"ok": true}` |
| Ready | `GET /readyz` | `ok: true`, `"rls": "enforced"` (503 = database or disk problem) |
| Metrics | `GET /metrics` (admin token), Prometheus format | `autoedit_workers_alive` ≥ 1; `autoedit_jobs{status="queued"}` goes down; `autoedit_reports_open` 0; `autoedit_webhooks_pending` small |
| Logs | `docker compose logs api worker-cpu` (one line per request: method, path, status, time, client; JSON with `SERVICE_LOG_JSON=true`) | few 5xx |
| Money | Admin → Overview / Costs | margin positive; no client far above its revenue |
| Abuse | Admin → Reports | handled within a day; child safety within hours |

A free uptime monitor (e.g. UptimeRobot, Better Stack) on `/readyz` every 5 minutes, with an alert
to your phone, is enough to start.

## Routine · Regular na gawain

- **Daily:** backups run (cron below); glance at Admin → Overview and Reports.
- **Weekly:** `docker compose logs --since 168h api | grep ' 5[0-9][0-9] '`; disk space (`df -h`).
- **Monthly:** `deploy/restore.sh --check` on the newest backup; rebuild and redeploy (security
  updates); the monthly items in [security-checklist.md](security-checklist.md).

### Backups · Backup

```
# /etc/cron.d/autoedit-backup  (as root; BACKUP_DATABASE_URL = the database ADMIN user, not autoedit_app)
15 3 * * * root cd /opt/autoedit && BACKUP_DATABASE_URL=postgresql://pgadmin:PASSWORD@127.0.0.1:5432/autoedit BACKUP_GPG_RECIPIENT=you@example.com deploy/backup.sh /var/backups/autoedit >> /var/log/autoedit-backup.log 2>&1
```

With the database in docker-compose, publish it to the host only (`127.0.0.1:5432:5432` under `db:`),
or run the script inside the db container. With Supabase, use its connection string for the
`postgres` user (Supabase also keeps its own daily backups on paid plans). Copy
`/var/backups/autoedit` somewhere else (another provider, or download weekly). Back up
`deploy/.env` and `deploy/secrets/` separately, encrypted (a password manager), never in git.

Videos are not backed up: they are temporary by design.

## When something goes wrong · Kapag may problema

### The site is down / `/healthz` does not answer
1. `docker compose ps` — is `api` running? `docker compose logs --tail 100 api`.
2. Settings error at start (it lists the problems): fix `deploy/.env`, `docker compose up -d`.
3. Disk full: `df -h`; old Docker images: `docker image prune -a`; logs are capped (20 MB × 5).
4. Certificate problems: `docker compose logs proxy` (ports 80 and 443 must be open; the domain
   must point to the server).

### `/readyz` says 503
- `database:` — `docker compose ps db`, `docker compose logs db`; Supabase status page. The API
  retries; nothing is lost while it waits.
- `storage:` — the data volume is full or read-only: free space.
- `"rls": "bypassed"` — the service connects as a superuser / BYPASSRLS user: fix
  `SERVICE_DATABASE_URL` to `autoedit_app` (production refuses to start this way).

### Videos wait forever (queue grows)
1. `curl -H "Authorization: Bearer $ADMIN" https://API/v1/admin/workers` — any worker `alive`?
2. Worker offline: `docker compose logs worker-cpu`; on your PC, is the worker window running?
3. Its token was revoked or the engine version is not promoted: `admin workers`, `admin status`.
4. Jobs that keep failing go to `failed` after their retries; the person sees why and can try again.

### Many errors after an update · Rollback
`admin rollback` sends new jobs back to the previous stable engine version (workers on the old
version take them). For the API itself: `git checkout <previous tag>` and
`docker compose up -d --build`. Migrations only add tables and columns, so the previous version
runs on the newer database. Take a backup before every update (`deploy/backup.sh`).

### A secret leaked · Na-leak ang isang secret

| Secret | Do this | Effect |
|---|---|---|
| A client's API key | `admin key-revoke <key id>` (or `key-rotate --grace-hours 0`), give them a new one | only that client |
| A worker token | `admin worker-revoke <id>`, `admin worker-create` a new one | that worker stops at once |
| `SERVICE_ADMIN_TOKEN` | set a new value in `deploy/.env`, `docker compose up -d api` | scripts using it need the new one |
| A staff account | Admin → Users → disable (signs out everywhere); new password and two-step sign-in | |
| Database password | `ALTER ROLE autoedit_app PASSWORD '...'`, update `SERVICE_DATABASE_URL`, restart | short downtime |
| Paddle / Groq / Anthropic / SMTP key | make a new key in their dashboard, delete the old one, update `.env`, restart | |
| Job signing key | `python editor.py service-admin signing-key deploy/secrets/signing-key.pem` (new pair), restart the API, give every worker the new `.pub` | jobs signed with the old key are refused by updated workers |
| `SERVICE_SECRET_KEY` (only if the server was broken into) | new value, restart | **every** API key, sign-in, result link and stored webhook secret stops working: make new API keys for clients, everyone signs in again, webhooks must be re-added; the one-trial check starts fresh |

If a server was broken into: take it offline, rotate **all** of the above, rebuild from a clean
image, restore the newest backup from before the break-in, and treat it as a data breach (below).

### A data breach · Data breach
Under the Data Privacy Act, tell the National Privacy Commission and the affected people within
**72 hours** of knowing about a breach that puts personal data at risk (NPC Circular 16-03; check the
current rules). Write down what happened, when, what data, what you did. The audit log
(Admin → System, or `/v1/admin/audit`) shows who did what.

### A video was reported · May na-report na video
Admin → Reports. Look only as much as you need to decide.
- **Copyright / privacy / harassment / spam:** if it breaks the rules, **Remove video** (or
  **Remove + suspend workspace** for repeat or serious abuse); else **Dismiss**. Copyright owners
  who send a notice get the same handling.
- **Child safety** (the file is already held, nobody can download it):
  1. Do **not** download, copy, forward or delete it. Do not contact the uploader about it.
  2. Report it to the authorities: in the Philippines, the PNP Women and Children Protection Center
     or the NBI (Anti-Child Abuse / cybercrime), and the IACAT / NCC-OSAEC-CSAEM hotline 1343. RA 11930
     gives platforms duties to report quickly (within 24 hours for some of them) and to preserve the
     evidence: confirm the exact duties with your lawyer **before** you go live.
  3. **Remove + suspend workspace**: the file stays on hold as evidence (it is not deleted by expiry
     or by the uploader), the workspace is blocked.
  4. When the authorities say they have what they need: **Purge evidence files**.
- Every action is in the audit log.

### A customer asks for their data or to be deleted
They can do both themselves: Account → Download my data / Delete account. Payment records stay as
tax law requires (Paddle keeps its own).

### Payments do not update plans
Paddle → Developer tools → Notifications: deliveries to `https://API/v1/billing/webhook/paddle` must
answer 200. 401 = `SERVICE_BILLING_WEBHOOK_SECRET` differs from Paddle's. Paddle retries; each event
is applied once. A person can be given a plan by hand: `admin grant <client id> creator`.

### Too many sign-ups / a bot wave
Admin → Sign-ups → **Paused** (existing users are not affected). Turn on the captcha. Lower
`SERVICE_SIGNUPS_PER_IP_HOUR`. Check Admin → Users for patterns and disable the accounts.

### Costs too high
Admin → Costs → the clients and videos that cost most. Lower the plan's minutes (Admin → Plans:
applies at once), suspend an abusive client (`admin client-update <id> status=suspended`), check
the AI providers' dashboards. Set spending limits there.

## Load test · Load test
Before launch and after big changes, on **staging**:

```
python scripts/loadtest.py --url https://staging.example.com --scenario health --users 20 --seconds 60 --i-own-this
python scripts/loadtest.py --url https://staging.example.com --scenario read   --key ak_... --users 20 --seconds 60 --i-own-this --max-p95-ms 500
python scripts/loadtest.py --url https://staging.example.com --scenario upload --key ak_... --users 5  --seconds 60 --i-own-this
```

Use a test client with a high `rate_per_minute` (the limits otherwise answer 429, which is them
working). It prints p50 / p95 / p99 and errors per request kind; exit 1 above the limits. It does
not run video edits (those are limited by your workers: one CPU worker edits one video at a time).

## Upgrading · Pag-update
1. Read the PR / release notes. 2. `deploy/backup.sh`. 3. `git pull`, `docker compose up -d --build`
(migrations run on start). 4. `/readyz`, one test video. 5. Register and promote the new engine
version for workers (`admin release-register`, `admin promote`) after its tests pass.
