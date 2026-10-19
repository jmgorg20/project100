"""Numbers for the admin dashboard: sign-ups, trials, paying workspaces, monthly recurring revenue,
revenue received, what the jobs cost to run (CPU/GPU, storage, transcription, AI, downloads), the
margin, per day; and, per month, each client's cost against its revenue, and the most costly jobs.

Costs are the service's own estimates (SERVICE_COST_*: set them to your real prices); revenue is
what the payment provider reported. Prices in other currencies are turned into US dollars with
SERVICE_FX_RATES (e.g. "PHP=0.0172,EUR=1.08"); a currency without a rate is listed apart, not guessed.
"""

import time

from . import billing, clients
from .db import now

DAY = 86400


def fx_rates(settings):
    rates = {"USD": 1.0}
    for item in settings.fx_rates:
        code, _, value = item.partition("=")
        try:
            rates[code.strip().upper()] = float(value)
        except ValueError:
            continue
    return rates


def to_usd(settings, cents, currency):
    """US dollars for an amount in cents, or None when there is no rate for the currency."""
    rate = fx_rates(settings).get(str(currency or "USD").upper())
    return None if rate is None else round(cents / 100.0 * rate, 4)


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _month_bounds(month):
    import calendar
    year, mon = (int(x) for x in month.split("-"))
    start = calendar.timegm((year, mon, 1, 0, 0, 0))
    end = calendar.timegm((year + (mon == 12), mon % 12 + 1, 1, 0, 0, 0))
    return start, end


def _revenue(settings, rows):
    usd, unconverted = 0.0, {}
    for p in rows:
        value = to_usd(settings, p["amount_cents"], p["currency"])
        if value is None:
            unconverted[p["currency"]] = unconverted.get(p["currency"], 0) + p["amount_cents"]
        else:
            usd += value
    return round(usd, 2), unconverted


def mrr(t, settings):
    """Monthly recurring revenue: each workspace on a paid plan, at its plan's price per month."""
    total, unconverted, paying = 0.0, {}, 0
    for row in t.all("SELECT s.*, p.price_cents, p.currency, p.billing_interval FROM subscriptions s JOIN plans p ON "
                     "p.id = s.plan_id WHERE s.status IN ('active', 'past_due', 'canceled')"):
        mode, _ = billing.state(settings, row)
        if mode != "plan" or not row["price_cents"]:
            continue
        paying += 1
        monthly = row["price_cents"] / (12 if row["billing_interval"] == "year" else 1)
        value = to_usd(settings, monthly, row["currency"])
        if value is None:
            unconverted[row["currency"]] = unconverted.get(row["currency"], 0) + monthly
        else:
            total += value
    return round(total, 2), unconverted, paying


def dashboard(t, settings, days=30):
    days = max(1, min(366, int(days)))
    since = now() - days * DAY
    usage = t.all("SELECT client_id, job_id, kind, created_at, input_minutes, cost_usd FROM usage WHERE created_at >= ?",
                  (since,))
    payments = t.all("SELECT client_id, amount_cents, currency, status, occurred_at FROM payments WHERE occurred_at >= ?",
                     (since,))
    paid = [p for p in payments if p["status"] == "paid"]
    jobs = t.all("SELECT status, kind, input_minutes, started_at, finished_at FROM jobs WHERE created_at >= ?", (since,))
    signups = t.all("SELECT created_at, email_verified_at FROM users WHERE created_at >= ?", (since,))
    kinds = {r["id"]: r["kind"] for r in t.all("SELECT id, kind FROM clients")}

    revenue_usd, unconverted = _revenue(settings, paid)
    cost = round(sum(u["cost_usd"] for u in usage), 4)
    org_cost = round(sum(u["cost_usd"] for u in usage if kinds.get(u["client_id"]) == "organization"), 4)
    done = [j for j in jobs if j["status"] == "succeeded"]
    minutes = round(sum(u["input_minutes"] for u in usage if u["kind"] == "job"), 2)
    job_rows = [u for u in usage if u["kind"] == "job"]
    mrr_usd, mrr_unconverted, paying = mrr(t, settings)
    subs = {r["status"]: r["n"] for r in t.all("SELECT status, COUNT(*) AS n FROM subscriptions GROUP BY status")}
    trials_now = t.value("SELECT COUNT(*) FROM subscriptions WHERE status = 'trialing' AND trial_ends_at > ?", (now(),), 0)

    series = {}
    for i in range(days):
        series[_day(now() - (days - 1 - i) * DAY)] = {"revenue_usd": 0.0, "cost_usd": 0.0, "jobs": 0, "minutes": 0.0,
                                                    "signups": 0}
    for u in usage:
        d = series.get(_day(u["created_at"]))
        if d is not None:
            d["cost_usd"] += u["cost_usd"]
            if u["kind"] == "job":
                d["jobs"] += 1
                d["minutes"] += u["input_minutes"]
    for p in paid:
        d, value = series.get(_day(p["occurred_at"])), to_usd(settings, p["amount_cents"], p["currency"])
        if d is not None and value is not None:
            d["revenue_usd"] += value
    for s in signups:
        d = series.get(_day(s["created_at"]))
        if d is not None:
            d["signups"] += 1

    queue = {r["status"]: r["n"] for r in t.all("SELECT status, COUNT(*) AS n FROM jobs WHERE status IN ('queued', "
                                                 "'running') GROUP BY status")}
    alive = t.value("SELECT COUNT(*) FROM workers WHERE status = 'active' AND last_seen_at > ?", (now() - 120,), 0)
    return {
        "days": days, "currency": "USD",
        "users": {"total": t.value("SELECT COUNT(*) FROM users", (), 0), "signups": len(signups),
                  "verified": sum(1 for s in signups if s["email_verified_at"])},
        "workspaces": {"total": sum(1 for k in kinds.values() if k == "organization"), "trialing": trials_now,
                       "paying": paying, "by_status": subs},
        "money": {"mrr_usd": mrr_usd, "revenue_usd": revenue_usd, "cost_usd": round(cost, 2),
                  "web_app_cost_usd": round(org_cost, 2), "api_clients_cost_usd": round(cost - org_cost, 2),
                  "margin_usd": round(revenue_usd - org_cost, 2),
                  "margin_pct": round((revenue_usd - org_cost) / revenue_usd * 100, 1) if revenue_usd else None,
                  "failed_payments": sum(1 for p in payments if p["status"] == "failed"),
                  "not_converted": {**unconverted, **{f"mrr_{k}": v for k, v in mrr_unconverted.items()}}},
        "jobs": {"total": len(jobs), "succeeded": len(done), "failed": sum(1 for j in jobs if j["status"] == "failed"),
                 "minutes": minutes,
                 "cost_per_job_usd": round(sum(u["cost_usd"] for u in job_rows) / len(job_rows), 4) if job_rows else None,
                 "cost_per_minute_usd": round(sum(u["cost_usd"] for u in job_rows) / minutes, 4) if minutes else None,
                 "avg_seconds": round(sum(j["finished_at"] - j["started_at"] for j in done if j["started_at"] and
                                          j["finished_at"]) / len(done), 1) if done else None},
        "system": {"queued": queue.get("queued", 0), "running": queue.get("running", 0), "workers_alive": alive},
        "series": [{"day": day, **{k: round(v, 4) if isinstance(v, float) else v for k, v in values.items()}}
                   for day, values in series.items()],
    }


def costs(t, settings, month=None):
    """One month: each client's minutes, jobs, cost, revenue and margin; and the 20 most costly jobs."""
    month = month or clients.month_of()
    start, end = _month_bounds(month)
    rows = {}
    for c in t.all("SELECT c.id, c.name, c.kind, s.status, s.plan_id FROM clients c LEFT JOIN subscriptions s ON "
                   "s.client_id = c.id"):
        rows[c["id"]] = {"client_id": c["id"], "name": c["name"], "kind": c["kind"], "plan": c["plan_id"],
                         "status": c["status"], "minutes": 0.0, "jobs": 0, "cost_usd": 0.0, "egress_usd": 0.0,
                         "revenue_usd": 0.0, "revenue_not_converted": {}}
    for u in t.all("SELECT client_id, kind, input_minutes, cost_usd FROM usage WHERE month = ?", (month,)):
        r = rows.get(u["client_id"])
        if r is None:
            continue
        r["cost_usd"] += u["cost_usd"]
        if u["kind"] == "job":
            r["jobs"] += 1
            r["minutes"] += u["input_minutes"]
        elif u["kind"] == "egress":
            r["egress_usd"] += u["cost_usd"]
    for p in t.all("SELECT client_id, amount_cents, currency FROM payments WHERE status = 'paid' AND occurred_at >= ? "
                   "AND occurred_at < ?", (start, end)):
        r = rows.get(p["client_id"])
        if r is None:                                   # a deleted workspace: its payments stay in the accounts
            r = rows.setdefault(p["client_id"], {"client_id": p["client_id"], "name": "(deleted)", "kind": "organization",
                                                 "plan": None, "status": None, "minutes": 0.0, "jobs": 0,
                                                 "cost_usd": 0.0, "egress_usd": 0.0, "revenue_usd": 0.0,
                                                 "revenue_not_converted": {}})
        value = to_usd(settings, p["amount_cents"], p["currency"])
        if value is None:
            r["revenue_not_converted"][p["currency"]] = r["revenue_not_converted"].get(p["currency"], 0) + p["amount_cents"]
        else:
            r["revenue_usd"] += value
    out = []
    for r in rows.values():
        if not (r["jobs"] or r["cost_usd"] or r["revenue_usd"] or r["revenue_not_converted"]):
            continue
        for k in ("minutes", "cost_usd", "egress_usd", "revenue_usd"):
            r[k] = round(r[k], 4)
        r["margin_usd"] = round(r["revenue_usd"] - r["cost_usd"], 4) if r["kind"] == "organization" else None
        out.append(r)
    out.sort(key=lambda r: r["cost_usd"], reverse=True)
    top = t.all("SELECT u.job_id, u.client_id, c.name, j.kind, u.input_minutes, u.cpu_seconds, u.gpu_seconds, "
                "u.transcription_usd, u.ai_usd, u.cost_usd, u.created_at FROM usage u JOIN clients c ON c.id = u.client_id "
                "LEFT JOIN jobs j ON j.id = u.job_id WHERE u.month = ? AND u.kind = 'job' ORDER BY u.cost_usd DESC LIMIT 20",
                (month,))
    totals = {k: round(sum(r[k] for r in out), 2) for k in ("minutes", "cost_usd", "revenue_usd")}
    totals["jobs"] = sum(r["jobs"] for r in out)
    return {"month": month, "clients": out, "top_jobs": top, "totals": totals,
            "prices": {k: getattr(settings, k) for k in ("cost_cpu_second", "cost_gpu_second", "cost_gb_month",
                                                         "cost_gb_egress")}}


def costs_csv(report):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["month", "client_id", "name", "kind", "plan", "status", "jobs", "minutes", "cost_usd", "revenue_usd",
                "margin_usd", "revenue_not_converted"])
    for r in report["clients"]:
        w.writerow([report["month"], r["client_id"], _csv_safe(r["name"]), r["kind"], r["plan"] or "", r["status"] or "",
                    r["jobs"], r["minutes"], r["cost_usd"], r["revenue_usd"],
                    "" if r["margin_usd"] is None else r["margin_usd"],
                    ";".join(f"{k} {v / 100:.2f}" for k, v in r["revenue_not_converted"].items())])
    return buf.getvalue()


def _csv_safe(text):
    """Names typed by customers must not run as formulas when the file is opened in a spreadsheet."""
    text = str(text or "")
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
