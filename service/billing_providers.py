"""Payment providers behind one small interface (SERVICE_BILLING_PROVIDER):

    checkout(...)  -> a URL where the customer pays (the provider's page: no card data here)
    portal(...)    -> a URL where the customer changes the card or cancels
    verify(...)    -> True when a webhook really comes from the provider (signature + time)
    parse(...)     -> the webhook as normalised events (below)

Normalised event: {"id", "type", "occurred_at", "client_id", "plan_id", "subscription": {...} | None,
"payment": {...} | None}, where type is one of
    subscription   status active | trialing | past_due | canceled | paused, period end, cancel at end
    payment_paid   amount, currency, a card fingerprint when the provider gives one
    payment_failed

Paddle (paddle.com, Paddle Billing API v1) is the real provider: a "merchant of record" (it charges
the card, handles sales tax / VAT and receipts, and pays out to sellers in the Philippines). "fake"
is a stand-in for development and tests that signs its webhooks the same way.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime


class ProviderError(Exception):
    pass


def iso_time(text):
    """Epoch seconds for an ISO 8601 time like 2026-10-18T09:00:00.123456Z (None if missing)."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _hmac(secret, data):
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


class Paddle:
    name = "paddle"
    TOLERANCE = 300

    def __init__(self, settings, http):
        self.settings, self.http = settings, http
        self.base = "https://api.paddle.com" if settings.paddle_environment == "production" else "https://sandbox-api.paddle.com"

    def _call(self, method, path, body=None):
        try:
            r = self.http.request(method, self.base + path, json=body, timeout=20, allow_redirects=False,
                                  headers={"Authorization": f"Bearer {self.settings.paddle_api_key}",
                                           "Content-Type": "application/json"})
        except Exception as exc:
            raise ProviderError(f"Could not reach the payment provider ({exc.__class__.__name__}).")
        if r.status_code >= 300:
            raise ProviderError(f"The payment provider refused the request ({r.status_code}).")
        try:
            return r.json()["data"]
        except (ValueError, KeyError, TypeError):
            raise ProviderError("The payment provider sent an unexpected answer.")

    def checkout(self, client, plan, user, return_url):
        if not plan.get("provider_price_id"):
            raise ProviderError("This plan has no Paddle price yet (service-admin plan-set ... provider_price_id=pri_...).")
        data = self._call("POST", "/transactions", {
            "items": [{"price_id": plan["provider_price_id"], "quantity": 1}],
            "custom_data": {"client_id": client["id"], "plan_id": plan["id"]},
            "collection_mode": "automatic",
        })
        url = (data.get("checkout") or {}).get("url")
        if not url or not str(url).startswith("https://"):
            raise ProviderError("Paddle gave no checkout link (set a default payment link in Paddle).")
        return url

    def portal(self, sub, return_url):
        if not sub.get("provider_customer_id"):
            raise ProviderError("There is no payment account for this workspace yet.")
        body = {"subscription_ids": [sub["provider_subscription_id"]]} if sub.get("provider_subscription_id") else {}
        data = self._call("POST", f"/customers/{sub['provider_customer_id']}/portal-sessions", body)
        url = ((data.get("urls") or {}).get("general") or {}).get("overview")
        if not url:
            raise ProviderError("Paddle gave no customer portal link.")
        return url

    def verify(self, headers, body, now=None):
        """Paddle-Signature: ts=<unix>;h1=<hex HMAC-SHA256(secret, "<ts>:<raw body>")> (several h1 while
        a secret is being rotated)."""
        header = headers.get("paddle-signature", "")
        parts = [p.split("=", 1) for p in header.split(";") if "=" in p]
        ts = next((v for k, v in parts if k == "ts"), "")
        sigs = [v for k, v in parts if k == "h1"]
        if not ts.isdigit() or not sigs or not self.settings.billing_webhook_secret:
            return False
        if abs((now or time.time()) - int(ts)) > self.TOLERANCE:
            return False                                   # an old message replayed
        want = _hmac(self.settings.billing_webhook_secret, ts.encode() + b":" + body)
        return any(hmac.compare_digest(want, s) for s in sigs)

    def parse(self, body):
        e = json.loads(body)
        kind, data = e.get("event_type", ""), e.get("data") or {}
        custom = data.get("custom_data") or {}
        base = {"id": str(e.get("event_id") or ""), "occurred_at": iso_time(e.get("occurred_at")) or time.time(),
                "client_id": custom.get("client_id"), "plan_id": custom.get("plan_id"), "subscription": None,
                "payment": None, "raw_type": kind}
        if kind.startswith("subscription."):
            items = data.get("items") or [{}]
            change = data.get("scheduled_change") or {}
            period = data.get("current_billing_period") or {}
            base["type"] = "subscription"
            base["subscription"] = {
                "id": data.get("id"), "customer_id": data.get("customer_id"), "status": data.get("status"),
                "price_id": ((items[0] or {}).get("price") or {}).get("id"),
                "period_end": iso_time(period.get("ends_at")),
                "cancel_at_period_end": change.get("action") == "cancel"}
            return [base]
        if kind in ("transaction.completed", "transaction.paid"):
            totals = (data.get("details") or {}).get("totals") or {}
            card = ((((data.get("payments") or [{}])[0] or {}).get("method_details") or {}).get("card") or {})
            base["type"] = "payment_paid"
            base["payment"] = {"id": data.get("id"), "subscription_id": data.get("subscription_id"),
                               "customer_id": data.get("customer_id"),
                               "amount_cents": int(totals.get("grand_total") or 0),
                               "currency": data.get("currency_code") or "USD",
                               # Paddle shows no card fingerprint: type + last 4 + expiry is the closest
                               "fingerprint": "|".join(str(card.get(k, "")) for k in ("type", "last4", "expiry_month",
                                                                                     "expiry_year")) if card else None}
            return [base]
        if kind == "transaction.payment_failed":
            base["type"] = "payment_failed"
            base["payment"] = {"id": data.get("id"), "subscription_id": data.get("subscription_id"),
                               "customer_id": data.get("customer_id"), "amount_cents": 0,
                               "currency": data.get("currency_code") or "USD", "fingerprint": None}
            return [base]
        return []                                          # other events are not needed


class Fake(Paddle):
    """A stand-in provider for development and tests: the same signature scheme as Paddle, and its
    own checkout page in the service (/v1/billing/fake/checkout) that "pays" when you press a button."""
    name = "fake"

    def checkout(self, client, plan, user, return_url):
        raise NotImplementedError        # handled by billing.checkout (it needs the database)

    def portal(self, sub, return_url):
        return return_url + "?billing=portal"

    @staticmethod
    def sign(secret, body, ts=None):
        ts = str(int(ts or time.time()))
        return f"ts={ts};h1={_hmac(secret, ts.encode() + b':' + body)}"

    @staticmethod
    def event(kind, data, occurred_at=None, event_id=None):
        """A webhook body in Paddle's shape (for the fake checkout and the tests)."""
        import secrets as _s
        when = datetime.fromtimestamp(occurred_at or time.time()).astimezone().isoformat()
        return json.dumps({"event_id": event_id or "evt_" + _s.token_hex(8), "event_type": kind,
                           "occurred_at": when, "data": data}).encode()


def provider(settings, http):
    if settings.billing_provider == "paddle":
        return Paddle(settings, http)
    if settings.billing_provider == "fake":
        return Fake(settings, http)
    return None
