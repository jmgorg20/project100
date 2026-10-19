# The admin pages: money, costs, users · Ang admin pages

For you and your staff: **https://API_DOMAIN/app/#/admin** (or Account → Admin).

1. Make yourself staff once, on the server:
   `python editor.py service-admin user-staff you@example.com`
2. In the web app: Account → **Turn on two-step sign-in** (an authenticator app). Staff cannot open
   the admin pages without it, and every admin action is in the audit log with your id.

*Gawin munang staff ang sarili (`user-staff`), tapos i-on ang two-step sign-in sa Account.*

## What is on them · Ano ang makikita

| Tab | |
|---|---|
| **Overview** | monthly recurring revenue (MRR) and paying workspaces; revenue, running cost (web app and API clients apart) and margin for the last 30 days; cost per video and per minute; videos and failures; free trials now; sign-ups; a chart of revenue and running cost per day (tap a day for its numbers; "Show table" lists them) |
| **Costs** | one month, per client: videos, minutes, cost, revenue, margin (API clients show "contract"); the most costly videos with their CPU / GPU seconds; **Download CSV** for your accountant |
| **Users** | search by email; disable (signs them out everywhere) / enable; make or remove staff |
| **Sign-ups** | the switch (invite code needed / open / paused) and invite codes (make one: shown once; see uses; revoke) |
| **Plans** | change a plan's price (in cents), minutes, storage, videos at a time, days files are kept, Paddle price id, shown or hidden; workspaces on the plan get the new limits at once |
| **Reports** | abuse reports from the "Report a video" page: dismiss (release), remove the video, remove and suspend the workspace; purge evidence kept for child-safety reports ([safety.md](safety.md), [runbook.md](runbook.md)) |
| **System** | videos waiting and editing now, workers online (and their engine version), the audit log |

The same numbers are in the admin API (`GET /v1/admin/dashboard?days=30`, `GET /v1/admin/costs?month=2026-10`,
`GET /v1/admin/costs.csv?month=…`, `GET /v1/admin/audit?action=plan.`), with the admin token.

## Where the numbers come from · Saan galing ang mga numero

- **Revenue** is what the payment provider reported (each payment once). Payments of a workspace
  that was later deleted stay in the accounts.
- **MRR** counts each workspace on a paid plan at the plan's price per month (a yearly plan / 12);
  free plans and trials are not counted.
- **Running cost** is an estimate made when each video finishes, from the prices you set:

  ```
  SERVICE_COST_CPU_SECOND=0.00002     # your VPS: monthly price / (CPUs x seconds in a month)
  SERVICE_COST_GPU_SECOND=0.0004      # your PC or a GPU server: electricity + wear, or the rental price
  SERVICE_COST_GB_MONTH=0.021         # storage per GB per month
  SERVICE_COST_GB_EGRESS=0.09         # downloads per GB (your provider's bandwidth price)
  ```

  plus what the AI services charged for that video (transcription, planning: the engine's own cost
  report), plus downloads as they happen (only the bytes sent). **Set these to your real prices**:
  the defaults are rough examples.
- **Other currencies** (e.g. a plan in pesos) are turned into dollars with your rates:
  `SERVICE_FX_RATES=PHP=0.0172,EUR=1.08`. A currency without a rate is shown apart, never guessed.
- Months and days are in UTC.
- The CSV is safe to open in Excel or Google Sheets: a name that starts like a formula is written as
  plain text.

*Tantiya ang gastos mula sa presyong inilagay mo (SERVICE_COST_*): ilagay ang totoong presyo mo.*

## What was and was not tested · Ano ang nasubukan

- **Tested here** (SQLite and Postgres): revenue in several currencies, unknown currencies apart,
  failed payments, MRR with monthly / yearly / free plans, cost split between the web app and API
  clients, margin, cost per video and per minute, the daily series, the per-client month report with
  downloads and deleted workspaces, the most costly videos, the CSV (formula-safe), month checks,
  only admins see it, the audit filters; in the browser at phone size: becoming staff and turning on
  two-step sign-in, every tab (numbers, chart values on tap, table view, CSV, the sign-up switch, a
  new invite code, a plan change, users, audit log), no sideways scrolling, and non-staff kept out.
- **Not tested:** real money over real months, and whether the default cost prices match your
  servers (they are examples: set your own).
- The admin pages are in English only (they are for you and your staff); the guide is in both.
