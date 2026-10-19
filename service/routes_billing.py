"""Billing routes: the workspace's plan and usage, checkout and the customer portal (owners and
admins), the payment provider's webhook, and (SERVICE_BILLING_PROVIDER=fake, development only) a
stand-in checkout page."""

import html
import logging

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import accounts, billing, security
from .api import ApiError
from .billing_providers import Fake
from .db import loads, now
from .deps import require_client, require_manager

router = APIRouter(prefix="/v1/billing")
log = logging.getLogger("autoedit.billing")


def _err(exc):
    return ApiError(exc.status, exc.code, str(exc))


def _org(client):
    if client.get("kind") != "organization":
        raise ApiError(404, "not_found", "Billing is for web-app workspaces; API clients are billed by contract.")
    return client


@router.get("")
def my_billing(request: Request, client=Depends(require_client)):
    s = request.app.state
    with s.db.tx() as t:
        return billing.view(t, s.settings, _org(client), client.get("role"))


@router.post("/checkout")
def start_checkout(request: Request, body: dict, client=Depends(require_manager)):
    s = request.app.state
    _org(client)
    with s.db.tx() as t:
        user = accounts.get_user(t, client["user_id"]) if client.get("user_id") else None
        try:
            url = billing.checkout(t, s.settings, s.http, client, body.get("plan_id"), user)
        except billing.BillingError as exc:
            raise _err(exc)
    return {"url": url}


@router.post("/portal")
def open_portal(request: Request, client=Depends(require_manager)):
    s = request.app.state
    _org(client)
    with s.db.tx() as t:
        try:
            return {"url": billing.portal(t, s.settings, s.http, client)}
        except billing.BillingError as exc:
            raise _err(exc)


@router.post("/webhook/{provider_name}")
async def webhook(request: Request, provider_name: str):
    """The payment provider tells us about payments and subscriptions (signed; each event once)."""
    from starlette.concurrency import run_in_threadpool
    s = request.app.state
    body = await request.body()
    status, detail = await run_in_threadpool(billing.handle_webhook, s.db, s.settings, s.http, provider_name,
                                             {k.lower(): v for k, v in request.headers.items()}, body, log)
    request.state.actor = f"billing:{provider_name}"
    return JSONResponse({"ok": status == 200, "detail": detail}, status_code=status)


# ---------------------------------------------------------------- the stand-in checkout (development)

def _fake_session(request, session):
    s = request.app.state
    if s.settings.billing_provider != "fake" or s.settings.production:
        raise ApiError(404, "not_found", "Not available.")
    with s.db.tx() as t:
        row = accounts.peek_token(t, s.settings, "fake_checkout", session)
        plan = billing.get_plan(t, loads(row["data"], {}).get("plan_id")) if row else None
    if not row or not plan:
        raise ApiError(400, "invalid_token", "This checkout expired; start again from the app.")
    return row, plan


@router.get("/fake/checkout")
def fake_checkout_page(request: Request, session: str = ""):
    _, plan = _fake_session(request, session)
    price = f"{plan['price_cents'] / 100:.2f} {plan['currency']}"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Test checkout</title></head>
<body><h1>Test checkout (no real payment)</h1><p>{html.escape(plan['name'])}: {html.escape(price)} per {html.escape(plan['billing_interval'])}</p>
<form method="post" action="/v1/billing/fake/pay"><input type="hidden" name="session" value="{html.escape(session)}">
<button name="outcome" value="paid">Pay (test)</button> <button name="outcome" value="cancel">Cancel</button></form></body></html>"""
    return HTMLResponse(page, headers={"Content-Security-Policy": "default-src 'none'; form-action 'self'"})


@router.post("/fake/pay")
async def fake_pay(request: Request):
    """Act like the provider after a payment: send the signed webhooks to ourselves."""
    from starlette.concurrency import run_in_threadpool
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    return await run_in_threadpool(_fake_pay, request, form.get("session", [""])[0], form.get("outcome", ["paid"])[0])


def _fake_pay(request, session, outcome):
    s = request.app.state
    row, plan = _fake_session(request, session)
    back = s.settings.app_link + "#/account"
    if outcome != "paid":
        return RedirectResponse(back + "?billing=cancelled", status_code=303)
    with s.db.tx() as t:
        accounts.use_token(t, s.settings, "fake_checkout", session)
    cid = loads(row["data"], {})["client_id"]
    custom = {"client_id": cid, "plan_id": plan["id"]}
    from datetime import datetime, timezone
    period_end = datetime.fromtimestamp(now() + 30 * 86400, timezone.utc).isoformat()
    secret = billing.webhook_secret(s.settings)
    sub_id, customer = f"sub_fake_{cid}", f"ctm_fake_{cid}"
    bodies = [
        Fake.event("subscription.activated", {"id": sub_id, "status": "active", "customer_id": customer,
                                              "custom_data": custom, "items": [{"price": {"id": plan["provider_price_id"]}}],
                                              "current_billing_period": {"ends_at": period_end}}),
        Fake.event("transaction.completed", {"id": "txn_fake_" + security.new_id(), "subscription_id": sub_id,
                                             "customer_id": customer, "custom_data": custom,
                                             "currency_code": plan["currency"],
                                             "details": {"totals": {"grand_total": str(plan["price_cents"])}},
                                             "payments": [{"method_details": {"card": {"type": "visa", "last4": "4242",
                                                                                       "expiry_month": 12,
                                                                                       "expiry_year": 2030}}}]}),
    ]
    for body in bodies:
        status, detail = billing.handle_webhook(s.db, s.settings, s.http, "fake",
                                                {"paddle-signature": Fake.sign(secret, body)}, body, log)
        if status != 200:
            raise ApiError(500, "billing", f"The test payment failed: {detail}")
    return RedirectResponse(back + "?billing=success", status_code=303)
