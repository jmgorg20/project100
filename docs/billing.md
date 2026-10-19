# Billing, plans and the free trial · Bayad, plans at free trial

For the web app's workspaces only. API clients like JGG CITY are billed by your contract with them,
not here (their limits stay what you set with `client-update`).

*Para sa mga workspace ng web app lang. Ang API clients gaya ng JGG CITY ay ayon sa kontrata ninyo.*

## The switch · Ang switch

```
SERVICE_BILLING=on                 # off: no trial, no plan limits (as before)
SERVICE_BILLING_PROVIDER=paddle    # or empty: plans only by hand (service-admin grant); fake: development
```

With billing on:

| The workspace is… | It can |
|---|---|
| in its **free trial** (7 days) | the trial limits: 30 minutes, 2 GB, 1 video at a time, files kept 3 days |
| on a **plan** (paid, or given by you) | the plan's limits |
| **past due** (a payment failed) | still the plan, for the grace time (3 days), then paused |
| **canceled** | the plan until the paid period ends, then paused |
| **paused** (trial or plan ended, or never chose one) | no new uploads or videos; downloading and "delete my data" still work |

All of these are settings: `SERVICE_TRIAL_DAYS`, `SERVICE_TRIAL_MINUTES`, `SERVICE_TRIAL_STORAGE_MB`,
`SERVICE_TRIAL_CONCURRENT_JOBS`, `SERVICE_TRIAL_RETENTION_DAYS`, `SERVICE_GRACE_DAYS`.

Emails go out by themselves (English and Taglish): 2 days before the trial ends, when it ends, when a
plan starts, when a payment fails, and when a plan ends.

## The free trial, once · Isang beses lang ang trial

The trial goes to the **first workspace of a new account**, and only once per:

- **email** (the same mailbox: `Juan.Cruz+x@gmail.com` = `juancruz@gmail.com`; deleting the account
  and signing up again does not give a new trial);
- **device** (a random id the web app keeps in that browser);
- **payment card** (when the provider shows the card: Paddle shows type, last 4 digits and expiry,
  which is weaker than a real card fingerprint).

Only keyed hashes are stored, never the email, the device id or card details themselves, and they
are kept after an account is deleted (for fraud prevention). Say so in your privacy notice (step 7.5
adds the text). Invite-only sign-up (docs/accounts.md) is the strongest protection while you start.

*Isang trial lang bawat email, device at card. Hash lang ang naitatabi.*

## Plans are data · Ang plans ay data

The first start loads `service/default_plans.json` ("Creator": 9 USD a month, 300 minutes, 10 GB,
2 at a time, files kept 7 days). After that, plans are changed with commands, not code:

```
python editor.py service-admin plans
python editor.py service-admin plan-set creator price_cents=900 monthly_minutes=300 provider_price_id=pri_01...
python editor.py service-admin plan-set studio name=Studio price_cents=2900 currency=USD billing_interval=month \
    monthly_minutes=1200 storage_mb=51200 concurrent_jobs=4 rate_per_minute=240 retention_days=14 gpu_allowed=true
python editor.py service-admin plan-set studio public=false          # hide it (keep it for some customers)
python editor.py service-admin grant ORG_ID creator --days 30        # give a plan by hand (partner, refund, test)
python editor.py service-admin grant ORG_ID none                     # take it away
```

(The same in the admin API: `GET/PUT /v1/admin/plans/{id}`, `POST /v1/admin/billing/{org}/grant`,
`GET /v1/admin/subscriptions`.) Changing a plan's limits applies at once to every workspace on it.
The **price a customer pays** is the price in Paddle: change it there too.

Minutes are counted per calendar month (UTC), the same as for API clients.

## Paddle (the payment provider) · Paddle

Why Paddle: it is a "merchant of record". It takes the card, charges sales tax / VAT where needed,
sends receipts, handles refunds and chargebacks, and pays you out. Check Paddle's list of supported
seller countries and its approval rules before you start. No card data ever reaches your server.

*Si Paddle ang tumatanggap ng card, nagbabayad ng tax at nagpapadala ng resibo. Walang card data sa
server mo.*

1. Make an account at paddle.com. Start in the **sandbox** (sandbox-vendors.paddle.com), switch to
   live after Paddle approves your website (it needs your terms, privacy and refund pages: step 7.5).
2. Catalog → Products: make "AutoEdit Creator" with a monthly price of 9 USD. Copy the price id
   (`pri_...`) and run `service-admin plan-set creator provider_price_id=pri_...`.
3. Checkout settings → **Default payment link**: your web app, `https://API_DOMAIN/app/`.
4. Developer tools → Authentication: make an API key. Put it in `SERVICE_PADDLE_API_KEY`.
5. Developer tools → Notifications: new destination `https://API_DOMAIN/v1/billing/webhook/paddle`,
   with the events `subscription.*`, `transaction.completed`, `transaction.paid` and
   `transaction.payment_failed`. Put its secret key in `SERVICE_BILLING_WEBHOOK_SECRET`.
6. `SERVICE_PADDLE_ENVIRONMENT=sandbox` (then `production`), `SERVICE_BILLING=on`,
   `SERVICE_BILLING_PROVIDER=paddle`. Restart.
7. Test with Paddle's test card in the sandbox: the workspace's Account page shows the plan, the
   payment, and "Card, receipts and cancelling" (Paddle's customer portal).

Webhooks are checked: Paddle's signature with your secret, at most 5 minutes old (an old message
sent again is refused), each event applied once (Paddle sends again after a failure), and an older
event never undoes a newer one.

## Development · Para sa development

`SERVICE_BILLING_PROVIDER=fake` gives a test checkout page in the service ("Pay (test)") that sends
itself the same signed webhooks Paddle would. It is refused in production.

## What was and was not tested · Ano ang nasubukan

- **Tested here** (SQLite and Postgres with row-level security): plans from the file and as data
  (changes reach subscribers, validation); the trial and its limits; one trial per email (also after
  deleting the account, and Gmail dots / +tags) and per device; the trial reminder and end; paused
  workspaces (no uploads or videos, downloads and delete still work); checkout and payment with the
  fake provider; members cannot buy; API clients not billed; webhook signature, too-old and
  duplicate events, events out of order, failed payment → grace → paused → paid again, cancel at
  period end; billing off; plans by hand without a provider; the Paddle adapter (the documented
  signature, secret rotation, request shapes, event parsing) against a stand-in for Paddle's API;
  the production refusal of the fake provider; the commands; the web app's trial banner, plans,
  test checkout and paused state at phone size.
- **Not tested:** the real Paddle API and dashboard (sandbox or live), real cards, taxes, refunds and
  chargebacks, and Paddle's real webhook deliveries. Check them in the sandbox before going live.
