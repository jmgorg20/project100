# Accounts and organisations (the web app) · Mga account at organisasyon

The SaaS web app's users sign up, sign in and work in **organisations**. An organisation is a
client of the same service as JGG CITY: the same queue, engine, quotas, usage reports, webhooks and
isolation. Nothing is copied for the web app.

*Ang mga user ng web app ay nag-sign up at nagtatrabaho sa loob ng "organisation". Ang bawat
organisation ay client din ng iisang service (parehong queue, engine, quota at usage report).*

## Sign-up: invite-only at first · Invite code muna

- `SERVICE_SIGNUP_MODE=invite` (the default): an **invite code** is needed to sign up.
- Make codes: `python editor.py service-admin invite-create --uses 1 --note "Juan from the FB group"`
  (shown once; `--uses 20` for a group). List: `invite-codes`. Cancel one: `invite-revoke ID`.
- **The switch:** `service-admin signups closed` pauses all new sign-ups at once (`open` lets
  anyone sign up, `invite` goes back to codes). `signups status` shows the current mode. The admin
  API has the same switch: `PUT /v1/admin/signups {"mode": "closed"}`.

*Para gumawa ng code: `service-admin invite-create`. Para i-pause ang sign-up: `service-admin
signups closed`. Para buksan ulit: `signups invite` o `signups open`.*

How sign-up works:
1. The person gives email, password (10+ characters, not a common one) and the invite code, and
   ticks "I agree to the Terms and the Privacy notice" (required; the terms version and time are
   kept: [safety.md](safety.md)). A new Google account needs the same box ticked first.
2. They get an email with a link (24 hours, once). Opening it confirms the email, signs them in and
   makes their own workspace (an organisation where they are the owner).
3. Not confirmed after 7 days: the sign-up is removed and the email is free again.

One account per mailbox: `Juan.Dela.Cruz+promo@gmail.com` and `juandelacruz@gmail.com` are the same
account. Throwaway mailboxes (mailinator and similar) are refused; add more domains with
`SERVICE_BLOCKED_EMAIL_DOMAINS=domain1.com,domain2.com`.

## Emails · Mga email

Production needs a mail server (any SMTP service: Brevo, Mailgun, Amazon SES, Gmail with an app
password for small volumes):

```
SERVICE_EMAIL_BACKEND=smtp
SERVICE_EMAIL_FROM=AutoEdit <no-reply@your-domain.com>
SERVICE_SMTP_HOST=smtp-relay.brevo.com
SERVICE_SMTP_PORT=587
SERVICE_SMTP_USER=...
SERVICE_SMTP_PASSWORD=...
```

Emails are queued and sent in the background (retried for about a day). In development
(`SERVICE_EMAIL_BACKEND=outbox`) they are written to `service-data/outbox/*.json` instead.
Every email is in English and Taglish.

## Sign in with Google · Mag-sign in gamit ang Google

1. console.cloud.google.com → APIs & Services → Credentials → Create credentials → OAuth client ID
   → Web application.
2. Authorised redirect URI: `https://API_DOMAIN/v1/auth/oauth/google/callback`.
3. Put the two values in `SERVICE_OAUTH_GOOGLE_CLIENT_ID` and `SERVICE_OAUTH_GOOGLE_CLIENT_SECRET`.

New Google users also need an invite code while sign-up is invite-only. Only emails Google marks
as verified are accepted. If someone had started a sign-up with that email but never confirmed it,
Google sign-in takes the account over and that unconfirmed password stops working.

## Bot check (optional) · Captcha

Cloudflare Turnstile (free) or hCaptcha: `SERVICE_CAPTCHA_PROVIDER=turnstile`,
`SERVICE_CAPTCHA_SITE_KEY`, `SERVICE_CAPTCHA_SECRET`. It is asked on sign-up, "forgot password",
and on sign-in after 3 failures from the same address.

## Staff (admin pages) and two-step sign-in · Staff at two-step sign-in

- Make someone staff: `service-admin user-staff you@example.com` (`--off` to undo).
- Staff must turn on **two-step sign-in** (an authenticator app such as Google Authenticator or
  Authy) before the admin pages open (`SERVICE_ADMIN_REQUIRE_MFA=true`, the default). Every admin
  action is in the audit log with the staff member's id.
- Any user can turn on two-step sign-in; they get 10 one-time recovery codes for a lost phone.
- Disable a user (signed out everywhere at once): `service-admin user-disable EMAIL`
  (`--enable` to undo).

*Ang staff ay dapat naka-on ang two-step sign-in bago makapasok sa admin pages.*

## Organisations, roles and projects · Mga organisasyon, role at project

| Role | Can |
|---|---|
| member | upload, start and see jobs, projects |
| admin | + webhooks, own presets, invite and remove members, delete all files |
| owner | + make owners, rename, delete the organisation |

- Invitations go by email and work only for that email address (7 days).
- An organisation always keeps at least one owner. Each user can own up to 5.
- **Projects** group uploads and jobs (`project_id` on `POST /v1/uploads` and `POST /v1/jobs`;
  `GET /v1/jobs?project_id=...`). API clients like JGG CITY can use projects too.
- The organisation's limits (minutes per month, storage, concurrent jobs) are the client limits:
  change them with `service-admin client-update ID monthly_minutes=600`. Plans and the 7-day trial
  come with billing (next step of Phase 7).

## The user's own data · Sariling data ng user

- `GET /v1/account/export`: everything kept about them, as a JSON file.
- `POST /v1/account/delete` (password, and a two-step code if on): deletes the account. Their own
  organisations (where they are the only owner) are deleted **with all files**; in shared ones they
  just leave.
- `DELETE /v1/data` (an owner or admin): deletes all the organisation's uploads and results now.

## Security (what is in place) · Seguridad

- Passwords: scrypt (32 MB per check), never stored or logged in clear; common passwords refused.
- Sessions: an HttpOnly, Secure, SameSite=Lax cookie (`__Host-` on https), 30 days at most, ended
  after 14 days unused; users see their devices and can sign out the others; a password change
  signs out everything else.
- Every change made with the cookie needs the session's CSRF token, and requests from other sites
  (Origin header) are refused, including sign-in.
- No user enumeration: sign-up, "forgot password" and "resend" answer the same for every email;
  a wrong password and an unknown email fail the same way, as slowly.
- Limits: 5 sign-ups per hour and 10 sign-ins per minute per address; 10 failed sign-ins pause an
  account's sign-in for 15 minutes; a two-step ticket ends after 5 wrong codes; a code works once.
- One-time links (confirm, reset, invitation) are stored as hashes, work once and expire; sent
  emails are not kept with their links.
- **Tenant isolation, twice:** every query filters by the caller's organisation, and on Postgres
  **row-level security** blocks other organisations' rows even if a query forgot that filter. It
  only works when the service connects as an ordinary database user: `deploy/docker-compose.yml`
  makes one (`deploy/postgres-init.sh`); for Supabase run `deploy/postgres-app-role.sql` in the SQL
  editor and use that user in `SERVICE_DATABASE_URL` (direct connection or the session pooler, port
  5432). In production the service refuses to start otherwise; `/readyz` shows `"rls": "enforced"`.

## Endpoints · Mga endpoint

| | |
|---|---|
| `GET /v1/auth/config` | sign-up mode, Google on/off, captcha site key |
| `POST /v1/auth/signup` `{email, password, name?, invite_code, captcha?}` | 202 always |
| `POST /v1/auth/verify` `{token}` | confirm the email and sign in |
| `POST /v1/auth/resend` `{email}` | a new confirmation link |
| `POST /v1/auth/login` `{email, password, captcha?}` | signed in, or `{mfa_required, ticket}` |
| `POST /v1/auth/mfa` `{ticket, code}` | the second step |
| `GET /v1/auth/session` | the user, the CSRF token, the organisation and the list of them |
| `POST /v1/auth/logout`, `GET /v1/auth/sessions`, `DELETE /v1/auth/sessions/{id}`, `POST /v1/auth/sessions/end-others` | |
| `POST /v1/auth/password/forgot` `{email}`, `POST /v1/auth/password/reset` `{token, password}`, `POST /v1/auth/password/change` | |
| `POST /v1/auth/mfa/setup`, `POST /v1/auth/mfa/enable` `{code}`, `POST /v1/auth/mfa/disable` `{password, code}` | |
| `GET /v1/auth/oauth/google/start?invite_code=`, `.../callback` | Google sign-in |
| `PATCH /v1/account`, `GET /v1/account/export`, `POST /v1/account/delete` | |
| `GET/POST /v1/orgs`, `POST /v1/orgs/{id}/switch`, `PATCH /v1/org`, `POST /v1/org/delete` | |
| `GET /v1/org/members`, `PATCH/DELETE /v1/org/members/{user_id}` | |
| `GET/POST /v1/org/invites`, `DELETE /v1/org/invites/{id}`, `POST /v1/invites/accept` `{token}` | |
| `GET/POST /v1/projects`, `PATCH/DELETE /v1/projects/{id}` | |
| `GET /v1/admin/users`, `PATCH /v1/admin/users/{id}`, `GET/POST /v1/admin/invite-codes`, `DELETE /v1/admin/invite-codes/{id}`, `GET/PUT /v1/admin/signups` | staff |

Every `/v1` client endpoint in [docs/service.md](service.md) works with the session cookie too
(acting in the current organisation).

## What was and was not tested · Ano ang nasubukan

- **Tested here** (SQLite and Postgres 16 as an ordinary user, so row-level security applied):
  sign-up with invite codes and the pause switch, no account enumeration, email rules, password
  rules, verification, an unconfirmed sign-up taken over by the real owner, sign-in, lockout,
  limits per address, CSRF and Origin checks, sessions, reset and change of password, two-step
  sign-in (codes once, recovery codes, ticket limits), staff needing two-step, members, roles and
  invitations, projects, export and delete, Google sign-in against a stand-in for Google (state,
  browser binding, PKCE, unverified emails, two-step), captcha against a stand-in, the email
  outbox, cleanup; row-level security with queries that forget the tenant filter, through the API
  for a key and a signed-in user; the production refusal; and the containers (Postgres with
  `postgres-init.sh`, the API as the ordinary user, `"rls": "enforced"`, a real polish job).
- **Not tested:** real Google, real Turnstile / hCaptcha, a real mail server, real Supabase,
  real phones and browsers (the web app and its browser tests: [web-app.md](web-app.md)).
