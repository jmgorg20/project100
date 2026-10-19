"""The admin dashboard and the cost report: revenue, MRR, costs, margin per day and per client,
currencies, the CSV export, and access (admin token or staff with two-step sign-in)."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from service import admin_stats, billing, clients, security
from service.api import create_app
from service.db import now
from tests.service.helpers import admin, new_client


@pytest.fixture
def app(settings):
    return create_app(dataclasses.replace(settings, billing="on", billing_provider="fake", password_cost=10,
                                          fx_rates=["PHP=0.02", "EUR=1.1"]))


@pytest.fixture
def http(app):
    with TestClient(app) as c:
        yield c


def org(t, settings, name):
    c = clients.create_client(t, settings, name, kind="organization")
    billing.start(t, settings, c)
    return c


def pay(t, client_id, cents, currency="USD", status="paid", at=None):
    t.insert("payments", {"id": security.new_id("pay_"), "client_id": client_id, "provider": "fake", "plan_id": "creator",
                          "amount_cents": cents, "currency": currency, "status": status, "occurred_at": at or now()})


def job_usage(t, client_id, minutes, cost, cpu=10.0, gpu=0.0):
    clients.record_usage(t, client_id, security.new_id("job_"), "job", input_minutes=minutes, cpu_seconds=cpu,
                         gpu_seconds=gpu, cost_usd=cost)


def test_dashboard_money_and_jobs(app, http):
    s = app.state.settings
    with app.state.db.tx() as t:
        a, b, c = org(t, s, "Paying A"), org(t, s, "Paying B"), org(t, s, "Trial C")
        billing.grant(t, s, a["id"], "creator")
        billing.grant(t, s, b["id"], "creator")
        t.run("UPDATE subscriptions SET status = 'trialing', trial_ends_at = ? WHERE client_id = ?", (now() + 86400, c["id"]))
        pay(t, a["id"], 900)
        pay(t, b["id"], 45000, "PHP")                              # 450 PHP = 9.00 USD at 0.02
        pay(t, b["id"], 900, "JPY")                                # no rate: listed apart
        pay(t, a["id"], 900, status="failed")
        pay(t, a["id"], 900, at=now() - 60 * 86400)                # outside the window
        job_usage(t, a["id"], 2.0, 0.30)
        job_usage(t, b["id"], 4.0, 0.50)
        partner = clients.create_client(t, s, "JGG CITY")
        job_usage(t, partner["id"], 10.0, 1.00)                     # an API client: its cost, no web revenue
    d = http.get("/v1/admin/dashboard", params={"days": 30}, headers=admin(http)).json()
    m = d["money"]
    assert m["revenue_usd"] == 18.0 and m["not_converted"] == {"JPY": 900}
    assert m["mrr_usd"] == 18.0 and d["workspaces"]["paying"] == 2 and d["workspaces"]["trialing"] == 1
    assert m["cost_usd"] == 1.8 and m["web_app_cost_usd"] == 0.8 and m["api_clients_cost_usd"] == 1.0
    assert m["margin_usd"] == 17.2 and m["margin_pct"] == 95.6 and m["failed_payments"] == 1
    assert d["jobs"]["minutes"] == 16.0 and d["jobs"]["cost_per_job_usd"] == 0.6 and d["jobs"]["cost_per_minute_usd"] == 0.1125
    today = d["series"][-1]
    assert len(d["series"]) == 30 and today["revenue_usd"] == 18.0 and today["cost_usd"] == 1.8 and today["jobs"] == 3
    assert http.get("/v1/admin/dashboard", params={"days": 1000}, headers=admin(http)).json()["days"] == 366


def test_yearly_plans_count_per_month_in_mrr(app, http):
    s = app.state.settings
    with app.state.db.tx() as t:
        billing.set_plan(t, s, "yearly", {"name": "Yearly", "price_cents": 9600, "currency": "USD", "billing_interval": "year",
                                          "monthly_minutes": 300, "storage_mb": 1024, "concurrent_jobs": 1,
                                          "rate_per_minute": 60, "retention_days": 7})
        billing.grant(t, s, org(t, s, "Annual")["id"], "yearly")
        billing.grant(t, s, org(t, s, "Free friend")["id"], "creator")
        t.run("UPDATE plans SET price_cents = 0 WHERE id = 'creator'")      # a free plan is not revenue
    assert http.get("/v1/admin/dashboard", headers=admin(http)).json()["money"]["mrr_usd"] == 8.0


def test_cost_report_per_client_and_csv(app, http):
    s = app.state.settings
    with app.state.db.tx() as t:
        a = org(t, s, "=HYPERLINK(\"http://evil\")")              # a hostile name typed by a customer
        job_usage(t, a["id"], 3.0, 0.40, cpu=100, gpu=20)
        clients.record_usage(t, a["id"], None, "egress", egress_bytes=10 ** 9, cost_usd=0.09)
        pay(t, a["id"], 900)
        pay(t, "cl_gone", 900)                                     # a deleted workspace: still in the accounts
    month = clients.month_of()
    r = http.get("/v1/admin/costs", params={"month": month}, headers=admin(http)).json()
    row = next(c for c in r["clients"] if c["client_id"] == a["id"])
    assert row["jobs"] == 1 and row["cost_usd"] == 0.49 and row["egress_usd"] == 0.09 and row["margin_usd"] == 8.51
    assert any(c["name"] == "(deleted)" and c["revenue_usd"] == 9.0 for c in r["clients"])
    assert r["top_jobs"][0]["gpu_seconds"] == 20 and r["totals"]["revenue_usd"] == 18.0
    assert r["prices"]["cost_gpu_second"] == s.cost_gpu_second
    csv = http.get("/v1/admin/costs.csv", params={"month": month}, headers=admin(http))
    assert csv.headers["content-type"].startswith("text/csv") and "attachment" in csv.headers["content-disposition"]
    assert "'=HYPERLINK" in csv.text and ',=HYPERLINK' not in csv.text            # not a formula in a spreadsheet
    assert http.get("/v1/admin/costs", params={"month": "2026/10"}, headers=admin(http)).status_code == 422


def test_only_admins_see_the_money(app, http):
    _, key = new_client(http)
    assert http.get("/v1/admin/dashboard", headers=key).status_code == 401
    assert http.get("/v1/admin/dashboard").status_code == 401
    assert http.get("/v1/admin/costs.csv", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_audit_filters(app, http):
    new_client(http, "Audited")
    entries = http.get("/v1/admin/audit", params={"action": "client."}, headers=admin(http)).json()["entries"]
    assert entries and all(e["action"].startswith("client.") for e in entries)
    assert isinstance(entries[0]["details"], dict)


def test_currency_conversion(settings):
    s = dataclasses.replace(settings, fx_rates=["php=0.02", "bad", "EUR=x"])
    assert admin_stats.to_usd(s, 1000, "PHP") == 0.2 and admin_stats.to_usd(s, 1000, "usd") == 10.0
    assert admin_stats.to_usd(s, 1000, "EUR") is None and admin_stats.to_usd(s, 1000, "GBP") is None
