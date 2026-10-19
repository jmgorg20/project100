# Going live: the owner's guide · Gabay sa paglulunsad

From "it works on my computer" to "strangers pay for it". Do the steps in order; each links to the
detailed page. Budget a weekend for steps 1–6 and a lawyer's review for step 7.

*Mula "gumagana sa computer ko" hanggang "may nagbabayad nang customer". Sundin isa-isa; may link
ang bawat hakbang sa mas detalyadong gabay. Isang weekend para sa 1–6, at kailangan ng abogado sa 7.*

## 1. Accounts you need · Mga account na kailangan

| What | Why | Cost to start |
|---|---|---|
| A VPS (e.g. Hetzner, DigitalOcean, Vultr; 2 vCPU / 4 GB) | the API, database, one CPU worker | ~US$5–25 / month |
| A domain (e.g. from Namecheap, Cloudflare) | `app.yourname.com` | ~US$10 / year |
| Cloudflare (free) | DNS, DDoS protection, Turnstile captcha | free |
| An email sender (e.g. Brevo, Postmark, Amazon SES) | sign-up and reset emails | free tier |
| Groq (and optionally Anthropic) API keys | transcription and planning | pay per use: set a spending limit |
| Paddle (seller account, verified) | payments, tax, receipts; pays out to the Philippines | % per sale |
| Optional: Supabase | managed Postgres with backups, instead of the database container | free tier |

*Kailangan: VPS, domain, Cloudflare (libre), email sender, Groq key, at Paddle account.*

## 2. Put it on the server · Ilagay sa server

Follow [service.md](service.md) "Setup on a VPS": copy `deploy/.env.example` to `deploy/.env`,
replace every `CHANGE_ME` with long random values, make the signing key, `docker compose up -d`.
Then check:

- `https://API_DOMAIN/healthz` says `ok`, and `/readyz` says `"rls": "enforced"`.
- `https://API_DOMAIN/app/` opens the web app on your phone; "Add to Home Screen" works.

*Sundin ang service.md. Tingnan na `ok` ang /healthz at `enforced` ang rls sa /readyz.*

## 3. Make yourself the boss · Gawing staff ang sarili

1. Sign up in the web app with your own email (invite-only: make a code first with
   `service-admin invite-create`).
2. `service-admin user-staff you@example.com`, then Account → turn on two-step sign-in.
3. Open Admin. Set your real prices in `deploy/.env` (`SERVICE_COST_*`, `SERVICE_FX_RATES`) — see
   [admin.md](admin.md).

*Mag-sign up, gawing staff ang sarili, i-on ang two-step sign-in, tapos buksan ang Admin.*

## 4. Payments · Bayad

Follow [billing.md](billing.md): Paddle **sandbox** first, a test purchase with Paddle's test card,
check the plan changes in Admin → Plans / Overview. Then Paddle live mode, with your real prices.
Plans, prices, minutes and the trial are settings, not code: change them in Admin → Plans and
`SERVICE_TRIAL_*`.

*Subukan muna sa Paddle sandbox gamit ang test card, bago ang totoong bayad.*

## 5. Safety switches · Mga switch pang-seguridad

- Captcha: Cloudflare Turnstile keys in `SERVICE_CAPTCHA_*`.
- Domain behind Cloudflare (orange cloud) for DDoS protection.
- Spending limits at Groq / Anthropic; billing alerts at your VPS host.
- Daily backups and a monthly restore test: [runbook.md](runbook.md) "Backups".
- An uptime monitor on `/readyz` with alerts to your phone.
- Work through [security-checklist.md](security-checklist.md) — every 🧑 line.

*I-on ang captcha, Cloudflare, spending limit, backup, at uptime monitor. Tapusin ang security
checklist.*

## 6. Test like a customer · Subukan na parang customer

On your phone, over mobile data: sign up, confirm the email, upload a 1-minute Taglish video, pick
a style, wait, watch, fix a caption, download. Report your own result from another phone
(`/app/#/report`) and handle it in Admin → Reports. Then run the load test on staging
([runbook.md](runbook.md) "Load test").

*Gamitin sa sariling phone, mobile data: sign up, upload, edit, download. I-report ang sariling video
at ayusin sa Admin → Reports.*

## 7. The legal part · Ang legal na bahagi

The pages under `web/public/` (terms, privacy, acceptable use, refunds, AI) are **drafts**. Before
real customers:

- Fill in the `[BRACKETED]` parts (your name or company, address, emails, city) and choose your refund policy.
- A Philippine lawyer reads them (Data Privacy Act, Consumer Act, e-commerce rules, RA 11930 on child
  protection online, copyright). Ask also about registering with the National Privacy Commission and
  naming a Data Protection Officer, and about the BIR / DTI / SEC registration of your business.
- Check each provider's data terms (Groq, Anthropic, Paddle, email, hosting): no training on your
  customers' data, and where the data is kept.
- Change `SERVICE_TERMS_VERSION` whenever the pages change.

*Draft lang ang mga legal na pahina. Punan ang mga [BRACKET], ipabasa sa abogado sa Pilipinas,
at alamin ang NPC registration, DPO, at BIR/DTI/SEC.*

## 8. Open the doors slowly · Dahan-dahang buksan

1. **Invite-only** (`SERVICE_SIGNUP_MODE=invite`): codes for 10–20 friends or a Facebook group.
   Watch Admin → Overview and Costs for a week or two.
2. Fix what they find. Keep the trial small until you see real costs per video.
3. Then **Open** in Admin → Sign-ups. The **Paused** switch stops new sign-ups in one click if
   anything goes wrong; existing customers keep working.

*Invite-only muna (10–20 tao). Bantayan ang gastos. Kapag ok na, i-Open. May Pause button kung may
problema.*

## 9. Every week after · Linggo-linggo

Admin → Overview (money), Costs (who costs most), Reports (handle them), System (workers online,
audit log). The routine and the "what to do when" list are in [runbook.md](runbook.md).

## What this guide cannot promise · Hindi masisiguro

These steps were written from the code and its tests; a full production launch (real domain, real
Paddle payouts, real email delivery, a real VPS network) was not done as part of building this.
Go step by step and test each one.
