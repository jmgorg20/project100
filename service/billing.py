"""Billing for the web app's organisations (SERVICE_BILLING=on): plans, the 7-day trial, subscriptions,
the payment provider's webhooks, and the limits that follow from them.

How an organisation's limits are decided (written into its client row, so the quota checks of the
service apply them unchanged):

    trialing (until trial_ends_at)                       -> the trial limits (SERVICE_TRIAL_*)
    active, past_due (until grace_until),
    canceled (until the paid period ends)                -> the plan's limits
    none, expired                                        -> no new uploads or videos; downloads and
                                                            "delete my data" keep working

The trial goes to the first workspace of a new account, once per email (canonical form), per device
(an id the web app keeps) and per payment card (when the provider shows one): only keyed hashes are
stored. API clients (kind 'integration', e.g. JGG CITY) are never billed here.
"""

import hashlib
import json
import secrets
from pathlib import Path

from . import clients, mailer, security
from .billing_providers import Fake, ProviderError, provider
from .db import dumps, now

ACTIVE = ("trialing", "active", "past_due", "canceled")
PLAN_FIELDS = {"name", "name_tl", "description", "description_tl", "price_cents", "currency", "billing_interval",
               "monthly_minutes", "storage_mb", "concurrent_jobs", "rate_per_minute", "gpu_allowed", "retention_days",
               "provider_price_id", "active", "public", "sort"}
DEFAULT_PLANS = Path(__file__).with_name("default_plans.json")


class BillingError(Exception):
    def __init__(self, message, status=422, code="invalid"):
        super().__init__(message)
        self.status, self.code = status, code


def enabled(settings):
    return settings.billing == "on"


def webhook_secret(settings):
    if settings.billing_webhook_secret:
        return settings.billing_webhook_secret
    if settings.billing_provider == "fake":                 # development: a secret derived from the service key
        return hashlib.sha256(("fake-billing:" + settings.secret_key).encode()).hexdigest()
    return ""


# ---------------------------------------------------------------- plans

def _check_plan(values):
    out = {}
    for k, v in values.items():
        if k not in PLAN_FIELDS:
            raise BillingError(f"Unknown plan field: {k}")
        if k in ("price_cents", "storage_mb", "concurrent_jobs", "rate_per_minute", "sort"):
            v = int(v)
            if v < 0 or v > 10_000_000:
                raise BillingError(f"{k} is out of range")
        elif k in ("monthly_minutes", "retention_days"):
            v = float(v)
            if v < 0 or v > 1_000_000 or (k == "retention_days" and v > 30):
                raise BillingError(f"{k} is out of range (retention at most 30 days)")
        elif k in ("gpu_allowed", "active", "public"):
            v = 1 if v in (True, 1, "1", "true", "on", "yes") else 0
        elif k == "billing_interval" and v not in ("month", "year"):
            raise BillingError("billing_interval must be month or year")
        elif k == "currency":
            v = str(v).upper()
            if len(v) != 3 or not v.isalpha():
                raise BillingError("currency must be a 3-letter code like USD or PHP")
        elif v is not None:
            v = str(v)[:500]
        out[k] = v
    return out


def ensure_plans(t, settings):
    """Load the plans file when there are no plans yet (the owner then edits them as data)."""
    if t.value("SELECT COUNT(*) FROM plans", (), 0):
        return 0
    path = Path(settings.plans_file) if settings.plans_file else DEFAULT_PLANS
    items = json.loads(path.read_text(encoding="utf-8"))
    for item in items:
        values = _check_plan({k: v for k, v in item.items() if k != "id"})
        t.insert("plans", {"id": str(item["id"]), **{k: None for k in PLAN_FIELDS}, "gpu_allowed": 0, "active": 1,
                           "public": 1, "sort": 100, **values, "created_at": now(), "updated_at": now()})
    return len(items)


def plan_view(p):
    return {k: p[k] for k in ("id", "name", "name_tl", "description", "description_tl", "price_cents", "currency",
                              "billing_interval", "monthly_minutes", "storage_mb", "concurrent_jobs", "retention_days")} \
        | {"gpu_allowed": bool(p["gpu_allowed"])}


def list_plans(t, public_only=True):
    sql = "SELECT * FROM plans WHERE active = 1" + (" AND public = 1" if public_only else "") + " ORDER BY sort, price_cents"
    return t.all(sql) if public_only else t.all("SELECT * FROM plans ORDER BY sort, price_cents")


def get_plan(t, plan_id):
    return t.one("SELECT * FROM plans WHERE id = ?", (plan_id,))


def set_plan(t, settings, plan_id, changes):
    """Create or change a plan; organisations on it get the new limits at once."""
    if not plan_id or not str(plan_id).replace("_", "").replace("-", "").isalnum() or len(plan_id) > 40:
        raise BillingError("A plan id is letters, digits, - and _ (up to 40).")
    values = _check_plan(changes)
    if get_plan(t, plan_id):
        if values:
            t.run(f"UPDATE plans SET {', '.join(f'{k} = ?' for k in values)}, updated_at = ? WHERE id = ?",
                  [*values.values(), now(), plan_id])
    else:
        need = {"name", "price_cents", "currency", "billing_interval", "monthly_minutes", "storage_mb",
                "concurrent_jobs", "rate_per_minute", "retention_days"} - set(values)
        if need:
            raise BillingError(f"A new plan needs: {', '.join(sorted(need))}")
        t.insert("plans", {"id": plan_id, **{k: None for k in PLAN_FIELDS}, "gpu_allowed": 0, "active": 1, "public": 1,
                           "sort": 100, **values, "created_at": now(), "updated_at": now()})
    for row in t.all("SELECT client_id FROM subscriptions WHERE plan_id = ?", (plan_id,)):
        apply(t, settings, row["client_id"])
    return get_plan(t, plan_id)


# ---------------------------------------------------------------- subscriptions and the trial

def get(t, client_id):
    return t.one("SELECT * FROM subscriptions WHERE client_id = ?", (client_id,))


def claim_hash(settings, kind, value):
    return security.hash_token(settings.secret_key, f"trial:{kind}", str(value).strip().lower())


def _claims(settings, email_canonical=None, device_ids=()):
    out = []
    if email_canonical:
        out.append(("email", claim_hash(settings, "email", email_canonical)))
    for device in device_ids or ():
        if isinstance(device, str) and 16 <= len(device) <= 100:
            claim = ("device", claim_hash(settings, "device", device))
            if claim not in out:
                out.append(claim)
    return out


def trial_allowed(t, claims):
    return not any(t.one("SELECT 1 AS x FROM trial_claims WHERE kind = ? AND value_hash = ?", c) for c in claims)


def start(t, settings, org, user=None, personal=False, device_ids=()):
    """A new organisation's subscription: the trial for a new account's first workspace (once per
    email / device), otherwise none (a plan must be chosen)."""
    if org.get("kind") != "organization" or get(t, org["id"]):
        return get(t, org["id"])
    claims = _claims(settings, user and user["email_canonical"], device_ids)
    trial = enabled(settings) and personal and settings.trial_days > 0 and trial_allowed(t, claims)
    t.insert("subscriptions", {"client_id": org["id"], "plan_id": None, "status": "trialing" if trial else "none",
                               "trial_ends_at": now() + settings.trial_days * 86400 if trial else None,
                               "current_period_end": None, "grace_until": None, "cancel_at_period_end": 0,
                               "provider": None, "provider_customer_id": None, "provider_subscription_id": None,
                               "last_event_at": None, "reminded": 0, "created_at": now(), "updated_at": now()})
    if trial:
        for kind, digest in claims:
            t.run("INSERT INTO trial_claims (kind, value_hash, client_id, created_at) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT (kind, value_hash) DO NOTHING", (kind, digest, org["id"], now()))
    apply(t, settings, org["id"])
    clients.audit(t, f"user:{user['id']}" if user else "system", "billing.started", org["id"],
                  {"trial": trial, "claims": [k for k, _ in claims]})
    return get(t, org["id"])


def state(settings, sub, at=None):
    """('off' | 'trial' | 'plan' | 'locked', reason)."""
    at = at or now()
    if not enabled(settings) or sub is None:
        return "off", None
    s = sub["status"]
    if s == "trialing":
        return ("trial", None) if (sub["trial_ends_at"] or 0) > at else ("locked", "trial_ended")
    if s == "active":
        return "plan", None
    if s == "past_due":
        return ("plan", "payment_failed") if (sub["grace_until"] or 0) > at else ("locked", "payment_failed")
    if s == "canceled":
        return ("plan", "canceling") if (sub["current_period_end"] or 0) > at else ("locked", "canceled")
    if s == "expired":
        return "locked", "trial_ended" if not sub["plan_id"] and sub["trial_ends_at"] else "expired"
    return "locked", "no_plan"


def apply(t, settings, client_id):
    """Write the limits that follow from the subscription into the organisation's client row."""
    client = clients.get_client(t, client_id)
    sub = get(t, client_id)
    if not client or client["kind"] != "organization" or not enabled(settings) or not sub:
        return
    mode, _ = state(settings, sub)
    plan = get_plan(t, sub["plan_id"]) if sub["plan_id"] else None
    if mode == "trial":
        limits = {"monthly_minutes": settings.trial_minutes, "storage_mb": settings.trial_storage_mb,
                  "concurrent_jobs": settings.trial_concurrent_jobs, "gpu_allowed": False,
                  "retention_days": settings.trial_retention_days}
    elif mode == "plan" and plan:
        limits = {k: plan[k] for k in ("monthly_minutes", "storage_mb", "concurrent_jobs", "rate_per_minute",
                                       "retention_days")} | {"gpu_allowed": bool(plan["gpu_allowed"])}
    else:
        limits = {"monthly_minutes": 0, "concurrent_jobs": 0, "gpu_allowed": False}
    clients.update_client(t, client_id, limits)


LOCKED_MESSAGES = {
    "trial_ended": ("Your free trial has ended. Choose a plan to make more videos; your finished videos can still be "
                    "downloaded.", "Tapos na ang free trial mo. Pumili ng plan para gumawa pa ng video; puwede pa ring "
                    "i-download ang mga natapos na."),
    "payment_failed": ("The last payment did not go through. Update your card to keep making videos.",
                       "Hindi pumasok ang huling bayad. I-update ang card para makagawa pa ng video."),
    "canceled": ("Your plan has ended. Choose a plan to make more videos.",
                 "Natapos na ang plan mo. Pumili ng plan para makagawa pa ng video."),
    "expired": ("Your plan has ended. Choose a plan to make more videos.",
                "Natapos na ang plan mo. Pumili ng plan para makagawa pa ng video."),
    "no_plan": ("Choose a plan for this workspace to make videos.", "Pumili ng plan para sa workspace na ito."),
}


def gate(t, settings, client):
    """None when the organisation may upload and start videos, else the reason (shown to the user)."""
    if client.get("kind") != "organization" or not enabled(settings):
        return None
    mode, reason = state(settings, get(t, client["id"]))
    if mode != "locked":
        return None
    en, tl = LOCKED_MESSAGES.get(reason, LOCKED_MESSAGES["no_plan"])
    return f"{en} · {tl}"


def _owners(t, client_id):
    return [r["email"] for r in t.all("SELECT u.email FROM memberships m JOIN users u ON u.id = m.user_id "
                                      "WHERE m.client_id = ? AND m.role = 'owner'", (client_id,))]


def _notify(t, settings, client_id, template, **values):
    for email in _owners(t, client_id):
        mailer.queue(t, email, template, link=settings.app_link + "#/account", **values)


def tick(t, settings):
    """Run by the janitor: trial reminders, the end of trials, grace periods and canceled periods."""
    if not enabled(settings):
        return {}
    done = {"reminded": 0, "expired": 0}
    soon = now() + 2 * 86400
    for sub in t.all("SELECT * FROM subscriptions WHERE status = 'trialing' AND reminded = 0 AND trial_ends_at < ? "
                     "AND trial_ends_at > ?", (soon, now())):
        _notify(t, settings, sub["client_id"], "trial_ending",
                days=max(1, round((sub["trial_ends_at"] - now()) / 86400)))
        t.run("UPDATE subscriptions SET reminded = 1 WHERE client_id = ?", (sub["client_id"],))
        done["reminded"] += 1
    ended = t.all("SELECT * FROM subscriptions WHERE (status = 'trialing' AND trial_ends_at <= ?) OR (status = 'past_due' "
                  "AND grace_until <= ?) OR (status = 'canceled' AND current_period_end <= ?)", (now(), now(), now()))
    for sub in ended:
        t.run("UPDATE subscriptions SET status = 'expired', updated_at = ? WHERE client_id = ?", (now(), sub["client_id"]))
        apply(t, settings, sub["client_id"])
        _notify(t, settings, sub["client_id"], "trial_ended" if sub["status"] == "trialing" else "plan_ended")
        clients.audit(t, "system", "billing.expired", sub["client_id"], {"was": sub["status"]})
        done["expired"] += 1
    return done


def grant(t, settings, client_id, plan_id, days=None, actor="admin"):
    """The admin gives a plan (a partner, a refund, a test): active for `days` (or until changed)."""
    client = clients.get_client(t, client_id)
    if not client or client["kind"] != "organization":
        raise BillingError("No such organisation.", 404, "not_found")
    if plan_id and not get_plan(t, plan_id):
        raise BillingError("No such plan.", 404, "not_found")
    if not get(t, client_id):
        start(t, settings, client)
    status = "canceled" if days else "active"            # canceled = ends when the period ends
    t.run("UPDATE subscriptions SET plan_id = ?, status = ?, current_period_end = ?, cancel_at_period_end = ?, "
          "grace_until = NULL, updated_at = ? WHERE client_id = ?",
          (plan_id, status if plan_id else "none", now() + float(days) * 86400 if days else None, 1 if days else 0,
           now(), client_id))
    apply(t, settings, client_id)
    clients.audit(t, actor, "billing.granted", client_id, {"plan": plan_id, "days": days})
    return get(t, client_id)


# ---------------------------------------------------------------- checkout, portal

def checkout(t, settings, http, client, plan_id, user):
    if not enabled(settings):
        raise BillingError("Billing is not on.", 404, "not_found")
    plan = get_plan(t, plan_id)
    if not plan or not plan["active"] or not plan["public"]:
        raise BillingError("No such plan.", 404, "not_found")
    sub = get(t, client["id"]) or start(t, settings, client)
    if sub["status"] in ("active", "past_due") and sub["plan_id"] == plan_id:
        raise BillingError("This workspace already has this plan (use Manage billing).", 409, "conflict")
    prov = provider(settings, http)
    if prov is None:
        raise BillingError("Online payment is not set up yet. Contact us to get a plan.", 503, "no_provider")
    back = settings.app_link + "#/account"
    if isinstance(prov, Fake):
        token = secrets.token_urlsafe(24)
        t.insert("auth_tokens", {"id": security.new_id("at_"), "user_id": user["id"] if user else None,
                                 "purpose": "fake_checkout", "token_hash": security.hash_token(settings.secret_key,
                                                                                               "fake_checkout", token),
                                 "data": dumps({"client_id": client["id"], "plan_id": plan_id}),
                                 "created_at": now(), "expires_at": now() + 1800, "used_at": None})
        return f"{settings.public_url.rstrip('/')}/v1/billing/fake/checkout?session={token}"
    try:
        return prov.checkout(client, plan, user, back)
    except ProviderError as exc:
        raise BillingError(str(exc), 502, "provider_error")


def portal(t, settings, http, client):
    sub = get(t, client["id"])
    prov = provider(settings, http)
    if not enabled(settings) or prov is None or not sub or not sub["provider_customer_id"]:
        raise BillingError("There is no payment account for this workspace yet.", 404, "not_found")
    try:
        return prov.portal(sub, settings.app_link + "#/account")
    except ProviderError as exc:
        raise BillingError(str(exc), 502, "provider_error")


# ---------------------------------------------------------------- webhooks

def _find_subscription(t, settings, provider_name, ev):
    """The subscription an event is about: the workspace we put in the checkout (custom data, set by
    the service, signed by the provider), else the provider's subscription or customer id."""
    if ev.get("client_id"):
        client = clients.get_client(t, str(ev["client_id"]))
        if client and client["kind"] == "organization":
            return get(t, client["id"]) or start(t, settings, client)
    s, p = ev.get("subscription") or {}, ev.get("payment") or {}
    for col, value in (("provider_subscription_id", s.get("id") or p.get("subscription_id")),
                       ("provider_customer_id", s.get("customer_id") or p.get("customer_id"))):
        if value:
            row = t.one(f"SELECT * FROM subscriptions WHERE provider = ? AND {col} = ?", (provider_name, value))
            if row:
                return row
    return None


def _plan_for(t, ev):
    price = (ev.get("subscription") or {}).get("price_id")
    if price:
        row = t.one("SELECT id FROM plans WHERE provider_price_id = ?", (price,))
        if row:
            return row["id"]
    plan_id = ev.get("plan_id")
    return plan_id if plan_id and get_plan(t, plan_id) else None


def apply_event(t, settings, provider_name, ev):
    """Apply one normalised event. Returns 'applied' or 'ignored: <why>'."""
    sub = _find_subscription(t, settings, provider_name, ev)
    if sub is None:
        return "ignored: no matching workspace"
    cid = sub["client_id"]
    if ev["type"] == "subscription":
        s = ev["subscription"]
        if sub["last_event_at"] and ev["occurred_at"] < sub["last_event_at"]:
            return "ignored: older than the last change"
        status = {"active": "active", "trialing": "active", "past_due": "past_due", "canceled": "canceled",
                  "paused": "expired"}.get(s.get("status"), None)
        if status is None:
            return f"ignored: status {s.get('status')}"
        period_end = s.get("period_end") or sub["current_period_end"]
        if status == "canceled" and not (period_end and period_end > now()):
            status = "expired"
        grace = sub["grace_until"]
        if status == "past_due" and not (grace and sub["status"] == "past_due"):
            grace = now() + settings.grace_days * 86400
        if status != "past_due":
            grace = None
        was_active = sub["status"] in ("active",)
        t.run("UPDATE subscriptions SET plan_id = COALESCE(?, plan_id), status = ?, current_period_end = ?, grace_until = ?, "
              "cancel_at_period_end = ?, provider = ?, provider_customer_id = COALESCE(?, provider_customer_id), "
              "provider_subscription_id = COALESCE(?, provider_subscription_id), last_event_at = ?, updated_at = ? "
              "WHERE client_id = ?",
              (_plan_for(t, ev), status, period_end, grace, 1 if s.get("cancel_at_period_end") else 0, provider_name,
               s.get("customer_id"), s.get("id"), ev["occurred_at"], now(), cid))
        if status == "active" and not was_active:
            _notify(t, settings, cid, "subscribed")
        if status == "past_due" and sub["status"] != "past_due":
            _notify(t, settings, cid, "payment_failed", days=int(settings.grace_days))
    elif ev["type"] in ("payment_paid", "payment_failed"):
        p = ev["payment"]
        pid = f"{provider_name}:{p.get('id')}:{'paid' if ev['type'] == 'payment_paid' else 'failed'}"
        t.run("INSERT INTO payments (id, client_id, provider, plan_id, amount_cents, currency, status, occurred_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
              (pid, cid, provider_name, sub["plan_id"] or ev.get("plan_id"), int(p.get("amount_cents") or 0),
               str(p.get("currency") or "USD")[:3], "paid" if ev["type"] == "payment_paid" else "failed",
               ev["occurred_at"]))
        if p.get("customer_id") and not sub["provider_customer_id"]:
            t.run("UPDATE subscriptions SET provider = ?, provider_customer_id = ? WHERE client_id = ?",
                  (provider_name, p["customer_id"], cid))
        if ev["type"] == "payment_paid":
            if p.get("fingerprint"):
                t.run("INSERT INTO trial_claims (kind, value_hash, client_id, created_at) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT (kind, value_hash) DO NOTHING",
                      ("card", claim_hash(settings, "card", p["fingerprint"]), cid, now()))
            if sub["status"] == "past_due":
                t.run("UPDATE subscriptions SET status = 'active', grace_until = NULL WHERE client_id = ?", (cid,))
        elif sub["status"] == "active":
            t.run("UPDATE subscriptions SET status = 'past_due', grace_until = ? WHERE client_id = ?",
                  (now() + settings.grace_days * 86400, cid))
            _notify(t, settings, cid, "payment_failed", days=int(settings.grace_days))
    apply(t, settings, cid)
    clients.audit(t, f"billing:{provider_name}", f"billing.{ev['type']}", cid, {"event": ev.get("id")})
    return "applied"


def handle_webhook(db, settings, http, provider_name, headers, body, log=None):
    """Check and apply a webhook. Returns (http status, detail). Each event is applied once (its id is
    kept); a failure rolls back and answers 500, so the provider sends it again."""
    prov = provider(_with_secret(settings), http)
    if not enabled(settings) or prov is None or prov.name != provider_name:
        return 404, "billing provider not enabled"
    if not prov.verify(headers, body):
        return 401, "bad signature"
    try:
        events = prov.parse(body)
    except (ValueError, TypeError, KeyError, AttributeError):
        return 400, "unreadable event"
    results = []
    for ev in events:
        if not ev.get("id"):
            continue
        key = f"{provider_name}:{ev['id']}"
        try:
            with db.tx() as t:
                if t.one("SELECT 1 AS x FROM billing_events WHERE id = ?", (key,)):
                    results.append("duplicate")
                    continue
                outcome = apply_event(t, settings, provider_name, ev)
                t.insert("billing_events", {"id": key, "provider": provider_name,
                                            "event_type": ev.get("raw_type", ev["type"]), "client_id": ev.get("client_id"),
                                            "occurred_at": ev["occurred_at"], "received_at": now(),
                                            "status": outcome.split(":")[0], "detail": outcome[:300]})
                results.append(outcome)
        except Exception:
            if log:
                log.exception("billing webhook failed")
            return 500, "could not apply the event; send it again"
    return 200, ", ".join(results) or "nothing to do"


def _with_secret(settings):
    import dataclasses
    return dataclasses.replace(settings, billing_webhook_secret=webhook_secret(settings))


# ---------------------------------------------------------------- what the workspace sees

def view(t, settings, client, role=None):
    sub = get(t, client["id"])
    mode, reason = state(settings, sub)
    plan = get_plan(t, sub["plan_id"]) if sub and sub["plan_id"] else None
    usage = clients.usage_this_month(t, client["id"])
    return {
        "enabled": enabled(settings), "mode": mode, "reason": reason,
        "status": sub["status"] if sub else None, "plan": plan_view(plan) if plan else None,
        "trial_ends_at": sub and sub["trial_ends_at"], "current_period_end": sub and sub["current_period_end"],
        "grace_until": sub and sub["grace_until"], "cancel_at_period_end": bool(sub and sub["cancel_at_period_end"]),
        "trial_days_left": max(0, round(((sub["trial_ends_at"] or 0) - now()) / 86400, 1)) if sub and mode == "trial" else None,
        "usage": {"minutes": round(usage["input_minutes"], 2), "minutes_limit": client["monthly_minutes"],
                  "jobs": usage["jobs"], "stored_bytes": clients.stored_bytes(t, client["id"]),
                  "storage_mb": client["storage_mb"]},
        "plans": [plan_view(p) for p in list_plans(t)],
        "payments": t.all("SELECT amount_cents, currency, status, occurred_at FROM payments WHERE client_id = ? "
                          "ORDER BY occurred_at DESC LIMIT 12", (client["id"],)),
        "can_manage": role in (None, "owner", "admin"),
        "has_portal": bool(sub and sub["provider_customer_id"]),
        "online_payment": settings.billing_provider in ("paddle", "fake"),
    }
