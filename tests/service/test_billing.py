"""Billing: plans as data, the 7-day trial (once per email / device / card), the access rules, the
fake provider's checkout, the webhooks (signature, replay, duplicates, order), grace periods,
cancellation, the Paddle adapter, admin and CLI. SQLite and Postgres (row-level security on)."""

import dataclasses
import json
import time

import pytest
from fastapi.testclient import TestClient

from service import billing, mailer
from service.api import create_app
from service.billing_providers import Fake, Paddle, iso_time
from service.db import now
from tests.service.helpers import admin, make_video, new_client, ready_upload
from tests.service.test_accounts import PASSWORD, csrf, last_email, link_token

DEVICE = "device-0123456789abcdef"


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("media") / "v.mp4", seconds=1.0)


def make_app(settings, **changes):
    changes = {"password_cost": 10, "signups_per_ip_hour": 1000, "logins_per_ip_minute": 1000, "signup_mode": "open",
               "billing": "on", "billing_provider": "fake", **changes}
    return create_app(dataclasses.replace(settings, **changes))


@pytest.fixture
def app(settings):
    return make_app(settings)


@pytest.fixture
def http(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


def join(app, http, email, device=DEVICE):
    """Sign up and confirm on `http`; returns the session payload."""
    assert http.post("/v1/auth/signup", json={"email": email, "password": PASSWORD, "device_id": device}).status_code == 202
    token = link_token(last_email(app, email, "verify_email"), "verify")
    r = http.post("/v1/auth/verify", json={"token": token, "device_id": device})
    assert r.status_code == 200, r.text
    return r.json()


def sub_of(app, client_id):
    with app.state.db.tx() as t:
        return billing.get(t, client_id)


def client_of(app, client_id):
    with app.state.db.tx() as t:
        return t.one("SELECT * FROM clients WHERE id = ?", (client_id,))


def secret(app):
    return billing.webhook_secret(app.state.settings)


def send(http, app, kind, data, ts=None, occurred_at=None, event_id=None, sign_secret=None):
    body = Fake.event(kind, data, occurred_at=occurred_at, event_id=event_id)
    sig = Fake.sign(sign_secret or secret(app), body, ts)
    return http.post("/v1/billing/webhook/fake", content=body, headers={"Paddle-Signature": sig,
                                                                        "Content-Type": "application/json"})


def iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def sub_event(cid, status, period_end=None, cancel=False, plan="creator"):
    return {"id": f"sub_{cid}", "status": status, "customer_id": f"ctm_{cid}",
            "custom_data": {"client_id": cid, "plan_id": plan}, "items": [{"price": {"id": None}}],
            "current_billing_period": {"ends_at": iso(period_end or now() + 30 * 86400)},
            "scheduled_change": {"action": "cancel"} if cancel else None}


# ---------------------------------------------------------------- plans

def test_plans_are_data_and_limits_follow(app, http):
    plans = http.get("/v1/admin/plans", headers=admin(http)).json()["plans"]
    assert [p["id"] for p in plans] == ["creator"] and plans[0]["price_cents"] == 900
    s = join(app, http, "planner@example.com")
    cid = s["organisation"]["id"]
    with app.state.db.tx() as t:
        billing.grant(t, app.state.settings, cid, "creator")
    assert client_of(app, cid)["monthly_minutes"] == 300
    r = http.put("/v1/admin/plans/creator", json={"monthly_minutes": 450, "price_cents": 1200}, headers=admin(http))
    assert r.status_code == 200
    assert client_of(app, cid)["monthly_minutes"] == 450                     # subscribers get the change
    assert http.put("/v1/admin/plans/creator", json={"retention_days": 90}, headers=admin(http)).status_code == 422
    assert http.put("/v1/admin/plans/studio", json={"name": "Studio"}, headers=admin(http)).status_code == 422
    new = {"name": "Studio", "price_cents": 2900, "currency": "usd", "billing_interval": "month", "monthly_minutes": 1200,
           "storage_mb": 51200, "concurrent_jobs": 4, "rate_per_minute": 240, "retention_days": 14, "gpu_allowed": True}
    assert http.put("/v1/admin/plans/studio", json=new, headers=admin(http)).json()["plan"]["currency"] == "USD"
    view = http.get("/v1/billing").json()
    assert [p["id"] for p in view["plans"]] == ["creator", "studio"]
    http.put("/v1/admin/plans/studio", json={"public": False}, headers=admin(http))
    assert [p["id"] for p in http.get("/v1/billing").json()["plans"]] == ["creator"]


def test_a_plans_file(settings, tmp_path):
    f = tmp_path / "plans.json"
    f.write_text(json.dumps([{"id": "php_basic", "name": "Basic", "price_cents": 49900, "currency": "PHP",
                              "billing_interval": "month", "monthly_minutes": 200, "storage_mb": 5120,
                              "concurrent_jobs": 1, "rate_per_minute": 60, "retention_days": 5}]))
    app = make_app(settings, plans_file=str(f))
    with app.state.db.tx() as t:
        assert [(p["id"], p["currency"]) for p in billing.list_plans(t)] == [("php_basic", "PHP")]


# ---------------------------------------------------------------- the trial

def test_a_new_account_gets_the_trial_and_its_limits(app, http, video):
    s = join(app, http, "trial@example.com")
    cid = s["organisation"]["id"]
    view = http.get("/v1/billing").json()
    assert view["mode"] == "trial" and view["status"] == "trialing" and 6.9 <= view["trial_days_left"] <= 7
    c = client_of(app, cid)
    assert (c["monthly_minutes"], c["storage_mb"], c["concurrent_jobs"]) == (30, 2048, 1)
    assert ready_upload(http, csrf(s), video)["status"] == "ready"
    # a second workspace has no trial: it needs a plan
    http.post("/v1/orgs", json={"name": "Second"}, headers=csrf(s))
    r = http.post("/v1/uploads", json={"filename": "a.mp4", "size": 100}, headers=csrf(s))
    assert r.status_code == 402 and r.json()["error"]["code"] == "payment_required"
    assert http.get("/v1/billing").json()["reason"] == "no_plan"


def test_one_trial_per_email_and_per_device(app, settings, video):
    with TestClient(app) as a:
        s = join(app, a, "Once.Only+x@gmail.com")
        a.post("/v1/account/delete", json={"password": PASSWORD}, headers=csrf(s))
    with TestClient(app) as b:                                     # the same mailbox signs up again
        join(app, b, "onceonly@gmail.com", device="another-device-0000001")
        assert b.get("/v1/billing").json()["mode"] == "locked"
    with TestClient(app) as c:                                     # a new email on the same phone
        join(app, c, "fresh@example.com", device=DEVICE)
        assert c.get("/v1/billing").json()["mode"] == "locked"
    with TestClient(app) as d:
        join(app, d, "other@example.com", device="brand-new-device-00002")
        assert d.get("/v1/billing").json()["mode"] == "trial"
    with app.state.db.tx() as t:
        stored = [r["value_hash"] for r in t.all("SELECT value_hash FROM trial_claims")]
    assert stored and not any("@" in h or "device" in h for h in stored)       # only keyed hashes


def test_the_trial_ends(app, http, video):
    s = join(app, http, "ending@example.com")
    cid = s["organisation"]["id"]
    up = ready_upload(http, csrf(s), video)
    job = http.post("/v1/jobs", json={"inputs": {"main": [up["id"]]}, "preset": "viral_tiktok"}, headers=csrf(s))
    assert job.status_code == 201
    with app.state.db.tx() as t:
        t.run("UPDATE subscriptions SET trial_ends_at = ? WHERE client_id = ?", (now() + 86400, cid))
        assert billing.tick(t, app.state.settings)["reminded"] == 1
        assert billing.tick(t, app.state.settings)["reminded"] == 0                 # once
    assert last_email(app, "ending@example.com", "trial_ending") is not None
    with app.state.db.tx() as t:
        t.run("UPDATE subscriptions SET trial_ends_at = ? WHERE client_id = ?", (now() - 1, cid))
        assert billing.tick(t, app.state.settings)["expired"] == 1
    assert sub_of(app, cid)["status"] == "expired"
    assert last_email(app, "ending@example.com", "trial_ended") is not None
    r = http.post("/v1/jobs", json={"inputs": {"main": [up["id"]]}, "preset": "viral_tiktok"}, headers=csrf(s))
    assert r.status_code == 402 and "trial has ended" in r.json()["error"]["message"]
    assert "Tapos na" in r.json()["error"]["message"]
    assert http.get(f"/v1/jobs/{job.json()['id']}").status_code == 200          # their things stay reachable
    assert http.delete("/v1/data", headers=csrf(s)).status_code == 200
    assert client_of(app, cid)["monthly_minutes"] == 0


# ---------------------------------------------------------------- paying

def test_checkout_with_the_fake_provider(app, http, video):
    s = join(app, http, "payer@example.com")
    cid = s["organisation"]["id"]
    assert http.post("/v1/billing/checkout", json={"plan_id": "nope"}, headers=csrf(s)).status_code == 404
    r = http.post("/v1/billing/checkout", json={"plan_id": "creator"}, headers=csrf(s))
    url = r.json()["url"]
    assert "/v1/billing/fake/checkout?session=" in url
    page = http.get(url.split("8787")[-1] if "8787" in url else url)
    assert page.status_code == 200 and "9.00 USD" in page.text and page.headers["content-security-policy"].startswith("default-src 'none'")
    session = url.split("session=")[1]
    r = http.post("/v1/billing/fake/pay", data={"session": session, "outcome": "paid"})
    assert r.status_code == 303 and r.headers["location"].endswith("#/account?billing=success")
    assert http.post("/v1/billing/fake/pay", data={"session": session}).status_code == 400   # once
    view = http.get("/v1/billing").json()
    assert view["mode"] == "plan" and view["status"] == "active" and view["plan"]["id"] == "creator"
    assert view["payments"][0]["amount_cents"] == 900 and view["has_portal"]
    assert client_of(app, cid)["monthly_minutes"] == 300
    assert last_email(app, "payer@example.com", "subscribed") is not None
    assert "billing=portal" in http.post("/v1/billing/portal", headers=csrf(s)).json()["url"]
    assert ready_upload(http, csrf(s), video)["status"] == "ready"
    with app.state.db.tx() as t:
        assert t.value("SELECT COUNT(*) FROM trial_claims WHERE kind = 'card'") == 1


def test_members_cannot_buy_and_api_clients_are_not_billed(app, http, video):
    s = join(app, http, "boss2@example.com")
    with TestClient(app) as m:
        member = join(app, m, "member2@example.com", device="member-device-00000003")
        http.post("/v1/org/invites", json={"email": "member2@example.com"}, headers=csrf(s))
        token = link_token(last_email(app, "member2@example.com", "org_invite"), "invite")
        m.post("/v1/invites/accept", json={"token": token}, headers=csrf(member))
        assert m.post("/v1/billing/checkout", json={"plan_id": "creator"}, headers=csrf(member)).status_code == 403
        assert m.get("/v1/billing").json()["mode"] == "trial"                    # members can see it
    _, key = new_client(http, "JGG CITY")
    assert http.get("/v1/billing", headers=key).status_code == 404
    assert ready_upload(http, key, video)["status"] == "ready"                  # contracts, not plans


# ---------------------------------------------------------------- webhooks

def test_webhooks_are_signed_fresh_and_applied_once(app, http):
    s = join(app, http, "hooks@example.com")
    cid = s["organisation"]["id"]
    data = sub_event(cid, "active")
    assert send(http, app, "subscription.activated", data, sign_secret="wrong-secret-xxxxxxxx").status_code == 401
    assert send(http, app, "subscription.activated", data, ts=time.time() - 3600).status_code == 401   # replayed
    r = http.post("/v1/billing/webhook/fake", content=b"{}", headers={"Paddle-Signature": "nonsense"})
    assert r.status_code == 401
    assert http.post("/v1/billing/webhook/paddle", content=b"{}").status_code == 404     # not the provider in use
    assert send(http, app, "subscription.activated", data, event_id="evt_1").json()["detail"] == "applied"
    assert sub_of(app, cid)["status"] == "active"
    pay = {"id": "txn_1", "subscription_id": f"sub_{cid}", "customer_id": f"ctm_{cid}", "custom_data": {"client_id": cid},
           "currency_code": "USD", "details": {"totals": {"grand_total": "900"}}}
    assert send(http, app, "transaction.completed", pay, event_id="evt_2").status_code == 200
    assert send(http, app, "transaction.completed", pay, event_id="evt_2").json()["detail"] == "duplicate"
    assert send(http, app, "transaction.completed", pay, event_id="evt_3").status_code == 200   # same payment, new id
    with app.state.db.tx() as t:
        assert t.value("SELECT COUNT(*) FROM payments WHERE client_id = ?", (cid,)) == 1
    stranger = sub_event("cl_doesnotexist", "active")
    assert "ignored" in send(http, app, "subscription.activated", stranger).json()["detail"]


def test_late_events_do_not_undo_newer_ones(app, http):
    s = join(app, http, "order@example.com")
    cid = s["organisation"]["id"]
    later = now()
    send(http, app, "subscription.canceled", sub_event(cid, "canceled", period_end=now() - 1), occurred_at=later)
    assert sub_of(app, cid)["status"] == "expired"
    r = send(http, app, "subscription.activated", sub_event(cid, "active"), occurred_at=later - 600)
    assert "older" in r.json()["detail"] and sub_of(app, cid)["status"] == "expired"


def test_failed_payment_grace_then_lock_then_recovery(app, http, video):
    s = join(app, http, "grace@example.com")
    cid = s["organisation"]["id"]
    send(http, app, "subscription.activated", sub_event(cid, "active"))
    fail = {"id": "txn_f", "subscription_id": f"sub_{cid}", "customer_id": f"ctm_{cid}", "currency_code": "USD"}
    send(http, app, "transaction.payment_failed", fail)
    sub = sub_of(app, cid)
    assert sub["status"] == "past_due" and sub["grace_until"] > now() + 2.9 * 86400
    assert last_email(app, "grace@example.com", "payment_failed") is not None
    view = http.get("/v1/billing").json()
    assert view["mode"] == "plan" and view["reason"] == "payment_failed"
    assert ready_upload(http, csrf(s), video)["status"] == "ready"               # still works during the grace
    with app.state.db.tx() as t:
        t.run("UPDATE subscriptions SET grace_until = ? WHERE client_id = ?", (now() - 1, cid))
        billing.tick(t, app.state.settings)
    assert http.post("/v1/uploads", json={"filename": "b.mp4", "size": 10}, headers=csrf(s)).status_code == 402
    paid = {"id": "txn_ok", "subscription_id": f"sub_{cid}", "customer_id": f"ctm_{cid}", "currency_code": "USD",
            "details": {"totals": {"grand_total": "900"}}}
    send(http, app, "subscription.updated", sub_event(cid, "active"))
    send(http, app, "transaction.completed", paid)
    assert sub_of(app, cid)["status"] == "active"
    assert http.post("/v1/uploads", json={"filename": "b.mp4", "size": 10}, headers=csrf(s)).status_code == 201


def test_cancel_keeps_the_paid_period(app, http):
    s = join(app, http, "cancel@example.com")
    cid = s["organisation"]["id"]
    send(http, app, "subscription.activated", sub_event(cid, "active"))
    send(http, app, "subscription.updated", sub_event(cid, "canceled", period_end=now() + 5 * 86400, cancel=True))
    view = http.get("/v1/billing").json()
    assert view["mode"] == "plan" and view["reason"] == "canceling" and view["cancel_at_period_end"]
    with app.state.db.tx() as t:
        t.run("UPDATE subscriptions SET current_period_end = ? WHERE client_id = ?", (now() - 1, cid))
        billing.tick(t, app.state.settings)
    assert http.get("/v1/billing").json()["mode"] == "locked"
    assert last_email(app, "cancel@example.com", "plan_ended") is not None


def test_billing_off_changes_nothing(settings, video):
    app = make_app(settings, billing="off", billing_provider="")
    with TestClient(app) as http:
        s = join(app, http, "free@example.com")
        assert http.get("/v1/billing").json()["mode"] == "off"
        assert ready_upload(http, csrf(s), video)["status"] == "ready"
        assert http.post("/v1/billing/checkout", json={"plan_id": "creator"}, headers=csrf(s)).status_code == 404
        assert http.post("/v1/billing/webhook/fake", content=b"{}").status_code == 404


def test_without_a_provider_the_admin_gives_plans(settings, video):
    app = make_app(settings, billing_provider="")
    with TestClient(app) as http:
        s = join(app, http, "manual@example.com")
        cid = s["organisation"]["id"]
        r = http.post("/v1/billing/checkout", json={"plan_id": "creator"}, headers=csrf(s))
        assert r.status_code == 503 and r.json()["error"]["code"] == "no_provider"
        r = http.post(f"/v1/admin/billing/{cid}/grant", json={"plan_id": "creator", "days": 30}, headers=admin(http))
        assert r.status_code == 200 and r.json()["subscription"]["status"] == "canceled"
        assert http.get("/v1/billing").json()["mode"] == "plan"
        assert client_of(app, cid)["monthly_minutes"] == 300
        assert http.get("/v1/admin/subscriptions", headers=admin(http)).json()["subscriptions"][0]["organisation"]
        http.post(f"/v1/admin/billing/{cid}/grant", json={"plan_id": None}, headers=admin(http))
        assert http.get("/v1/billing").json()["mode"] == "locked"


# ---------------------------------------------------------------- the Paddle adapter

class FakePaddleHTTP:
    def __init__(self):
        self.calls = []

    class R:
        def __init__(self, status, data):
            self.status_code, self._data = status, data

        def json(self):
            return self._data

    def request(self, method, url, json=None, headers=None, **kw):
        self.calls.append((method, url, json, headers))
        if url.endswith("/transactions"):
            return self.R(201, {"data": {"id": "txn_01", "checkout": {"url": "https://pay.example.com/checkout?_ptxn=txn_01"}}})
        if "/portal-sessions" in url:
            return self.R(201, {"data": {"urls": {"general": {"overview": "https://customer-portal.paddle.com/x"}}}})
        return self.R(404, {"error": {}})


def test_paddle_adapter(settings):
    s = dataclasses.replace(settings, billing="on", billing_provider="paddle", paddle_api_key="pdl_test_key",
                            billing_webhook_secret="pdl_ntfset_" + "s" * 30)
    http = FakePaddleHTTP()
    p = Paddle(s, http)
    assert p.base == "https://sandbox-api.paddle.com"
    plan = {"id": "creator", "provider_price_id": "pri_01abc"}
    url = p.checkout({"id": "cl_1"}, plan, None, "https://app/#/account")
    method, called, body, headers = http.calls[0]
    assert (method, called) == ("POST", "https://sandbox-api.paddle.com/transactions")
    assert body["items"] == [{"price_id": "pri_01abc", "quantity": 1}] and body["custom_data"]["client_id"] == "cl_1"
    assert headers["Authorization"] == "Bearer pdl_test_key" and url.startswith("https://pay.example.com/")
    with pytest.raises(Exception, match="no Paddle price"):
        p.checkout({"id": "cl_1"}, {"id": "creator", "provider_price_id": None}, None, "x")
    assert p.portal({"provider_customer_id": "ctm_1", "provider_subscription_id": "sub_1"}, "x").startswith("https://")
    # the signature exactly as Paddle documents it: ts=...;h1=HMAC-SHA256(secret, "ts:body")
    body = b'{"event_id":"evt_01","event_type":"subscription.created","occurred_at":"2026-10-18T09:00:00.000000Z","data":{}}'
    ts = int(time.time())
    import hashlib
    import hmac
    h1 = hmac.new(s.billing_webhook_secret.encode(), f"{ts}:".encode() + body, hashlib.sha256).hexdigest()
    assert p.verify({"paddle-signature": f"ts={ts};h1={h1}"}, body)
    assert p.verify({"paddle-signature": f"ts={ts};h1={'0' * 64};h1={h1}"}, body)          # secret rotation
    assert not p.verify({"paddle-signature": f"ts={ts};h1={h1}"}, body + b" ")
    assert not p.verify({"paddle-signature": f"ts={ts - 400};h1={h1}"}, body)
    # events in Paddle's shape become normalised events
    sub = json.dumps({"event_id": "evt_02", "event_type": "subscription.updated", "occurred_at": "2026-10-18T09:00:00Z",
                      "data": {"id": "sub_01", "status": "past_due", "customer_id": "ctm_01",
                               "custom_data": {"client_id": "cl_1", "plan_id": "creator"},
                               "items": [{"price": {"id": "pri_01abc"}}],
                               "current_billing_period": {"starts_at": "2026-10-01T00:00:00Z", "ends_at": "2026-11-01T00:00:00Z"},
                               "scheduled_change": {"action": "cancel", "effective_at": "2026-11-01T00:00:00Z"}}}).encode()
    [ev] = p.parse(sub)
    assert ev["type"] == "subscription" and ev["client_id"] == "cl_1" and ev["subscription"]["status"] == "past_due"
    assert ev["subscription"]["price_id"] == "pri_01abc" and ev["subscription"]["cancel_at_period_end"]
    assert ev["subscription"]["period_end"] == iso_time("2026-11-01T00:00:00Z")
    txn = json.dumps({"event_id": "evt_03", "event_type": "transaction.completed", "occurred_at": "2026-10-18T09:00:00Z",
                      "data": {"id": "txn_01", "subscription_id": "sub_01", "customer_id": "ctm_01", "currency_code": "USD",
                               "details": {"totals": {"grand_total": "900"}},
                               "payments": [{"method_details": {"type": "card", "card": {"type": "visa", "last4": "4242",
                                                                                         "expiry_month": 1, "expiry_year": 2030}}}]}}).encode()
    [ev] = p.parse(txn)
    assert ev["type"] == "payment_paid" and ev["payment"]["amount_cents"] == 900 and ev["payment"]["fingerprint"] == "visa|4242|1|2030"
    assert p.parse(json.dumps({"event_id": "e", "event_type": "address.created", "data": {}}).encode()) == []


def test_production_refuses_the_fake_provider():
    from service.settings import Settings, SettingsError
    with pytest.raises(SettingsError, match="fake is for development"):
        Settings(billing="on", billing_provider="fake", env="production").check()
    with pytest.raises(SettingsError, match="Paddle needs"):
        Settings(billing="on", billing_provider="paddle").check()


def test_cli_plans_and_grant(settings, monkeypatch, capsys):
    from service import cli
    app = make_app(settings)
    with TestClient(app) as http:
        cid = join(app, http, "cli@example.com")["organisation"]["id"]
    env = {"SERVICE_ENV": "test", "SERVICE_DATABASE_URL": settings.database_url, "SERVICE_DATA_DIR": settings.data_dir,
           "SERVICE_SECRET_KEY": settings.secret_key, "SERVICE_ADMIN_TOKEN": settings.admin_token, "SERVICE_BILLING": "on"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert cli.main(["service-admin", "plan-set", "creator", "provider_price_id=pri_live_123"]) == 0
    assert "pri_live_123" in capsys.readouterr().out
    assert cli.main(["service-admin", "grant", cid, "creator", "--days", "14"]) == 0
    assert '"status": "canceled"' in capsys.readouterr().out
    assert cli.main(["service-admin", "grant", cid, "nope"]) == 1


def test_mail_templates_have_both_languages():
    for name in ("trial_ending", "trial_ended", "plan_ended", "subscribed", "payment_failed"):
        subject, body = mailer.TEMPLATES[name]
        assert "·" in subject and "---" in body
