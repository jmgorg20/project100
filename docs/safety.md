# Safety and compliance features · Kaligtasan at pagsunod sa batas

What the service does to keep people and you safe, and the settings for it. The procedures (what a
person does) are in [runbook.md](runbook.md); the reasons in [threat-model.md](threat-model.md).

## Consent to the terms · Pagpayag sa terms

- Sign-up (email or a new Google account) needs the box "I agree to the Terms and the Privacy
  notice…" ticked; the service refuses it otherwise (`terms_required`). The version accepted and the
  time are kept per user (`SERVICE_TERMS_VERSION`, now `draft-2026-10`) and are in "Download my data".
- When you change the terms, change `SERVICE_TERMS_VERSION` too, and tell users by email (the
  terms say how long before). People who signed up earlier keep their recorded version.

## The legal pages · Mga legal na pahina

`web/public/terms.html`, `privacy.html`, `acceptable-use.html`, `refund.html`, `ai.html`, linked under
the sign-in and sign-up pages. They are **DRAFTS** written for the Philippines (Data Privacy Act,
Consumer Act, RA 11930) with a Taglish summary each. Fill in every `[BRACKETED]` part and have a
lawyer read them before you open sign-ups.

## Reports · Mga report

- Anyone with a link to a result can report it at `/app/#/report` (no account needed; a few per
  address per hour; captcha when set): the link, a reason (copyright, child safety, violence, hate,
  harassment, privacy, illegal, spam, other), details and an optional email.
- **Holds:** a child-safety report, or reports from 3 different addresses about the same file,
  hold it at once: downloads answer 451, the owner sees "on hold" in the app.
- **Staff** (Admin → Reports): **Dismiss** (released), **Remove video** (deleted now), **Remove +
  suspend workspace**. For child safety, remove / suspend keep the file on hold as evidence; **Purge
  evidence files** deletes it later. A held file is never deleted by expiry, by its owner deleting
  the video, or by account deletion, until the staff decide.
- API: `POST /v1/public/report`, `GET /v1/admin/reports?status=open|dismissed|removed|suspended|all`,
  `POST /v1/admin/reports/<id>/resolve {"action", "note"}`, `POST /v1/admin/reports/<id>/purge`.
  Metrics: `autoedit_reports_open`, `autoedit_outputs_held`.

## Checking uploads · Pagsuri ng upload

- `SERVICE_SCAN_COMMAND` — a virus scanner (e.g. `clamdscan --no-summary {path}`); exit 0 = clean.
- `SERVICE_MODERATION_COMMAND` — your content check, run on every accepted video, picture and sound:
  `{path}` is the file; exit 0 = allowed; otherwise the upload is refused and the first line it
  prints is shown as the reason. Both **fail closed**: if the program cannot run, the file is refused.
  No content-check program is included (choose one that fits your users and budget, e.g. a hosted
  moderation API called from a small script); the hook is tested with a stand-in script.

## AI label · AI label

Every finished video shows "Edited automatically with AI. Check it before you post…" in the app, and
the API returns `ai_label` with the job. The AI page (`/app/ai.html`) explains what the AI does and
reminds people to use the platforms' own AI labels for realistic AI-made content.

## Keeping data only as long as needed · Retention

| Data | Kept | Setting |
|---|---|---|
| Uploads and results | 3 days; results also 24 h after the first download | `SERVICE_RETENTION_DAYS`, `SERVICE_DELETE_AFTER_DOWNLOAD_HOURS` (per client / plan) |
| Unconfirmed sign-ups | 7 days | |
| Sign-ins | 30 days, 14 days unused | `SERVICE_SESSION_DAYS`, `SERVICE_SESSION_IDLE_DAYS` |
| Audit log, handled reports | 400 days (0 = forever) | `SERVICE_AUDIT_RETENTION_DAYS` |
| Held (reported) files | until the staff decide | |
| Backups | 14 days | `BACKUP_KEEP_DAYS` |
| Accounts, payments | until the account is deleted; payments as tax law requires | |

## Model weights · Mga AI model

The service ships no AI model weights and the images download none (it uses hosted AI). CI checks
this (`scripts/check_no_weights.py`). Third-party licences: [LICENSES.md](../LICENSES.md)
(regenerate with `python scripts/licenses.py`).

## What was and was not tested · Ano ang nasubukan

- **Tested here** (SQLite and Postgres): consent on email and Google sign-up, reports by link
  (expired links too, wrong links refused), holds (child safety at once, three addresses), dismiss /
  remove / suspend / purge, evidence surviving expiry and owner deletion, the per-address limit, the
  content-check hook (refusal with reason, fail closed), the AI label, audit and report retention;
  in the browser at phone size: the report page, the held state, the AI label, the terms box on
  sign-up, the admin Reports tab; backup and restore on real Postgres.
- **Not tested:** a real content-moderation service; reports at real volume; the legal text (not
  legal advice; drafts).
