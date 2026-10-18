"""Who is calling: client (API key), worker (worker token) or admin (admin token), with rate limits.

Wrong keys are counted per address: after AUTH_FAILURES_PER_MINUTE failures that address gets 429
for the rest of the minute, which makes guessing keys useless (keys have 256 bits anyway).
"""

from fastapi import Request

from . import clients, jobqueue, ratelimit, security
from .api import ApiError, client_ip

AUTH_FAILURES_PER_MINUTE = 20


def bearer(request):
    value = request.headers.get("authorization", "")
    if value[:7].lower() == "bearer ":
        return value[7:].strip()
    return ""


def _guard_failures(request, t):
    s = request.app.state.settings
    key = f"authfail:{client_ip(request, s)}"
    if ratelimit.peek(t, key) >= AUTH_FAILURES_PER_MINUTE:
        raise ApiError(429, "too_many_attempts", "Too many wrong keys from this address; wait a minute.",
                       {"Retry-After": "60"})
    return key


def _fail(request, key):
    with request.app.state.db.tx() as t:
        ratelimit.hit(t, key, AUTH_FAILURES_PER_MINUTE)


def require_client(request: Request):
    state = request.app.state
    token = bearer(request)
    with state.db.tx() as t:
        fail_key = _guard_failures(request, t)
        client = clients.authenticate(t, state.settings, token) if token else None
        if client is not None:
            if request.url.path.endswith("/chunk"):     # file pieces: their own, higher limit
                allowed, retry = ratelimit.hit(t, f"chunks:{client['id']}", max(600, 5 * int(client["rate_per_minute"])))
            else:
                allowed, retry = ratelimit.hit(t, f"client:{client['id']}", int(client["rate_per_minute"]))
    if client is None:
        _fail(request, fail_key)
        raise ApiError(401, "unauthorized", "A valid API key is needed (Authorization: Bearer ak_...).")
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many requests; slow down.", {"Retry-After": str(retry)})
    request.state.actor = f"client:{client['id']}"
    return client


def require_worker(request: Request):
    state = request.app.state
    token = bearer(request)
    with state.db.tx() as t:
        fail_key = _guard_failures(request, t)
        worker = jobqueue.authenticate_worker(t, state.settings, token) if token else None
    if worker is None:
        _fail(request, fail_key)
        raise ApiError(401, "unauthorized", "A valid worker token is needed (or it was revoked).")
    request.state.actor = f"worker:{worker['id']}"
    return worker


def require_admin(request: Request):
    state = request.app.state
    token = bearer(request)
    with state.db.tx() as t:
        fail_key = _guard_failures(request, t)
    if not security.token_matches(token, state.settings.admin_token):
        _fail(request, fail_key)
        raise ApiError(401, "unauthorized", "The admin token is needed.")
    request.state.actor = "admin"
    return "admin"


def ip_limit(request, limit=300):
    state = request.app.state
    with state.db.tx() as t:
        ok, retry = ratelimit.hit(t, f"ip:{client_ip(request, state.settings)}", limit)
    if not ok:
        raise ApiError(429, "rate_limited", "Too many requests; slow down.", {"Retry-After": str(retry)})
