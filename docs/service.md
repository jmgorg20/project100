# The headless service (integration API) · Ang service

**One codebase, one engine.** The service is the single API that every client uses: the partner
project (JGG CITY), the SaaS website, and future projects. Each client has its **own API keys,
presets, quotas, rate limit, webhooks, channel and usage report**. Nothing is copied per project.

*Iisang code at iisang engine. Ang service ang iisang API na ginagamit ng lahat ng client; bawat
client ay may sariling API key, preset, quota, webhook at usage report.*

```
 clients (JGG CITY, SaaS web app, ...)          workers (pull, outbound HTTPS only)
   |  Bearer ak_...                                 |  Bearer wk_...  (signed jobs)
   v                                                v
 +------------------------ API (FastAPI) ----------------------------+
 | uploads (chunked, resumable) | jobs | events (SSE) | results (signed links) |
 | webhooks (signed)  | admin (clients, keys, workers, flags, releases) |
 +------------- Postgres (queue, clients, usage, audit) ------------+
                files on the API machine's disk (deleted after a few days)
```

- **Desktop users** keep working fully on their own PC; nothing is uploaded unless they choose a
  cloud feature.
- **Workers connect out** to the API over HTTPS and pull jobs. Your Windows PC (WanGP / ComfyUI)
  can be a GPU worker **without opening any port** on your home network, and without a VPN.

## Setup on a VPS · Pag-set up sa VPS

1. A VPS with Docker (2 vCPU / 4 GB is enough for the API and one CPU worker), a domain name
   pointing at it (e.g. `api.example.com`).
2. `cp deploy/.env.example deploy/.env` and replace every `CHANGE_ME` (long random values:
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Set `API_DOMAIN`.
   With Supabase: put Supabase's Postgres connection string in `SERVICE_DATABASE_URL` and remove
   the `db` service from `deploy/docker-compose.yml`.
3. `python editor.py service-admin signing-key deploy/secrets/signing-key.pem` (keep the `.pem`
   secret; the `.pem.pub` goes to workers).
4. `docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build`
   Caddy gets the HTTPS certificate by itself. Check `https://api.example.com/healthz`.
5. Make a client and its key (shown once):
   `docker compose -f deploy/docker-compose.yml exec api python editor.py service-admin client-create "JGG CITY" --minutes 600`
6. Make the CPU worker's token: `... service-admin worker-create cpu-1 --queues cpu`, put it in
   `AUTOEDIT_WORKER_TOKEN` in `deploy/.env`, and `docker compose ... up -d worker-cpu`.

*Kailangan: VPS na may Docker at domain. Kopyahin ang `.env.example`, palitan lahat ng CHANGE_ME,
gumawa ng signing key, tapos `docker compose up`. Ang mga key at token ay ipinapakita isang beses lang.*

### A worker on your PC · Worker sa sarili mong PC (GPU)

On the Windows PC that has WanGP (and ComfyUI, if you use it):

1. On the server: `python editor.py service-admin worker-create my-pc --queues gpu` and copy the
   token it prints (shown once) and the server's `signing-key.pem.pub` to the PC.
2. On the PC:

```
python -m pip install -r requirements-worker.txt
setx AUTOEDIT_WORKER_TOKEN wk_...
python editor.py worker --server https://api.example.com --public-key signing-key.pem.pub --queues gpu
```

- Only outgoing HTTPS to your API (and to Groq / stock sites if used). **No port forwarding.**
- The token can be revoked at any time (`service-admin worker-revoke ID`); its running job goes back
  to the queue at once. If the PC sleeps or loses the internet, the job goes back to the queue
  when its lease runs out (2 minutes by default) and another worker takes it.
- Jobs are **signed**: the PC runs only jobs signed with the service's key.
- For a *beta* worker (new engine versions before customers get them):
  `worker-create my-pc --queues gpu --channel beta`.
- To keep it running: Windows Task Scheduler "At log on" (or NSSM as a service) with the command
  above; `AUTOEDIT_WORKER_TOKEN` as a user environment variable, not in a file in the repo.

## Using the API · Paggamit ng API

Every request: `Authorization: Bearer ak_...`. Errors are `{"error": {"code", "message"}}`.

| | |
|---|---|
| `GET /v1/me` | your limits, this month's usage, enabled features |
| `GET /v1/catalog` | the presets (built-in and your own) and formats you can use |
| `GET /v1/presets`, `PUT /v1/presets/{id}`, `DELETE /v1/presets/{id}` | **your own presets** (plain preset JSON, the same format as `autoedit/presets/*.json`; a preset with a built-in id replaces it for you only; other clients never see yours) |
| `POST /v1/uploads` `{filename, size, sha256?}` | start an upload; answers `chunk_size` |
| `PUT /v1/uploads/{id}/chunk?offset=N` (raw bytes) | send the next piece; `Upload-Offset` = bytes received |
| `GET /v1/uploads/{id}` | how much arrived (to resume after a broken connection) |
| `POST /v1/uploads/{id}/complete` | check the file: `ready`, or `422` with the reason |
| `POST /v1/jobs` | start a job (below); `Idempotency-Key` header makes retries safe |
| `GET /v1/jobs/{id}` | status, progress, result, files with **signed links** and their **expiry countdown** |
| `GET /v1/jobs/{id}/events` | live updates (Server-Sent Events; reconnect with `Last-Event-ID`) |
| `POST /v1/jobs/{id}/cancel`, `DELETE /v1/jobs/{id}` | stop; delete the results now |
| `DELETE /v1/data` | delete all your uploads and results now |
| `GET /v1/usage?month=2026-10` | minutes, CPU/GPU seconds, storage, egress, AI costs, estimated cost |
| `GET/POST /v1/webhooks`, `DELETE /v1/webhooks/{id}` | your webhooks (the secret is shown once) |
| `POST /v1/keys/rotate?grace_hours=24` | a new key; the old one keeps working for the grace time |

**A polish job:**
```json
{"kind": "polish", "inputs": {"main": ["up_..."], "broll": ["up_..."]}, "preset": "viral_tiktok",
 "format": "auto", "instruction": "Mabilis, malalaking caption", "items": [], "offsets": {},
 "provider": "groq", "qc": true, "retry": true, "gpu": false}
```
The result (`GET /v1/jobs/{id}`) has `result.status` (`ok` / `warnings` / `failed`), `result.qc`
(the objective checks), `result.opinions` (the AI's description, marked *not checked*), and
`outputs`: `video`, `project`, `sidecar`, `plan`, each with a link valid for 15 minutes (ask again
for a fresh one) and `expires_in_seconds` (files are kept 3 days by default, and 24 hours after the
first download).

**A render job** (after fixing captions or approving a storyboard): `{"kind": "render", "project":
{...}}`; the project's media paths are `upload:<id>` or `output:<id>` (as the polish job's project
already has them).

**Webhooks:** `POST` with `X-AutoEdit-Signature: t=<unix>,v1=<hex>`; check it:
```python
from service.security import verify_webhook
ok = verify_webhook(secret, request_body_bytes, request.headers["X-AutoEdit-Signature"])
```
Events: `job.queued`, `job.started`, `job.succeeded`, `job.failed`, `job.cancelled`,
`upload.ready`, `upload.rejected`, `files.expiring`. Failed deliveries are retried for about a day.

## Admin · Pamamahala

Command line on the server (`python editor.py service-admin --help`) or the admin API with
`Authorization: Bearer <SERVICE_ADMIN_TOKEN>`. Every change goes to the audit log.

- Clients: `client-create`, `client-update ID status=suspended`, `channel=beta`, limits
  (`monthly_minutes`, `concurrent_jobs`, `rate_per_minute`, `storage_mb`, `gpu_allowed`,
  `retention_days`, `presets=["meme","viral_tiktok"]`).
- Keys: `key-create`, `key-revoke`, `key-rotate --grace-hours 24`.
- Workers: `worker-create NAME --queues cpu,gpu --channel stable|beta`, `worker-revoke`, `workers`.
- `status`, `janitor`, `flags`, `flag NAME --stable on|off --beta on|off`.

### Releases: beta, stable, rollback · Paglabas ng bagong version

1. The owner's PC worker runs the new engine on the **beta** channel (`--channel beta`); beta
   clients (e.g. your own test client) get it first.
2. CI runs the tests and saves `pytest-report.xml`:
   `service-admin release-register <version> --junit pytest-report.xml` (failed tests: refused).
3. `service-admin promote <version>`: stable workers take jobs only when they run the promoted
   version, so customers get it only now. Only a release whose tests passed can be promoted.
4. Something wrong? `service-admin rollback` (one command) goes back to the previous version;
   stable workers on the old version take jobs again immediately.
5. **Feature flags** hold back a feature (e.g. `formats`, `gpu`, `ai_planner`) per channel:
   `service-admin flag formats --stable off --beta on`, then `--stable on` when ready.

The engine version a worker reports is `AUTOEDIT_ENGINE_VERSION`, or the git commit.

## Security (what is in place) · Seguridad

- **HTTPS only** in production (`SERVICE_REQUIRE_HTTPS`, HSTS; Caddy terminates TLS); the service
  refuses to start in production with weak or missing secrets, http URLs, `*` CORS or private
  webhooks allowed.
- **Secrets only from the environment** / secret files; API keys and worker tokens are stored as
  HMACs (a database leak does not reveal them) and shown once; webhook secrets are encrypted.
- **Rate limits** per client, per address for wrong keys (key guessing blocked), separate limits for
  upload chunks; a body size limit on every request.
- **Uploads are checked before use:** extension allowlist, size and duration limits, optional
  scanner (`SERVICE_SCAN_COMMAND`, e.g. ClamAV), checksum, and ffprobe with the demuxer fixed by the
  extension and only the `file` protocol (a text file posing as a video cannot become a playlist
  that reads other files or URLs), codec allowlist. Files are stored under random ids, served as
  downloads with `nosniff`. Nothing uploaded is ever executed.
- **Tenant isolation:** every query is scoped to the caller's client; tests try every endpoint with
  another client's ids.
- **Workers:** signed job payloads (Ed25519), revocable tokens, heartbeats, jobs returned when a
  worker disappears; the engine runs with no shell, a fixed argument list, a minimal environment,
  a time limit, in a private folder that is deleted; results are scrubbed of local paths.
- **Webhooks:** https only, private / local / cloud-metadata addresses refused after DNS, no
  redirects, signed bodies.
- **Containers:** non-root user, read-only filesystem, all capabilities dropped,
  `no-new-privileges`; the worker needs no inbound port.
- **Retention:** uploads and results are deleted after `SERVICE_RETENTION_DAYS` (default 3; at most
  30), results also 24 hours after the first download; users can delete everything at once.
- **Audit log** of admin and client actions; `/metrics` (admin token) for monitoring.
- **CI:** tests on Postgres, `pip-audit`, `npm audit`, gitleaks (secrets in the history), Trivy (files
  and images), and the container end-to-end test.

## What was and was not tested · Ano ang nasubukan

- **Tested here (Linux):** every database test on SQLite **and on a real Postgres 16**; the queue
  (one job to exactly one worker under concurrency, client concurrency, channels and the promoted
  version, heartbeats, retries with backoff, lost workers, time limits, revoked workers); the API
  (auth, key rotation and revocation, rate limits, resumable uploads with a lost reply, bad files,
  quotas, tenant isolation on every endpoint, idempotency, cancel, SSE events, signed links and
  their expiry, retention, delete-my-data, webhook signatures and retries, SSRF address checks,
  HTTPS and proxy handling, security headers, production settings checks, the release gate); the
  worker agent against a real HTTP server (signatures, the engine command line with hostile text,
  no local paths in results, render jobs, cancel, time limit, engine errors, crash and retry on
  another worker, refused tokens); and **one end to end run with the real engine** (upload, polish,
  download a 1080x1920 MP4, fix a caption, render again).
- **Container images:** see the PR for what was built and run here.
- **Not tested:** a real VPS, real Supabase, real HTTPS certificates, real Windows GPU workers with
  WanGP / ComfyUI, real phones, real load, and real costs (the cost figures are estimates from the
  prices you set: `SERVICE_COST_*`).
