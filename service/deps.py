"""Who is calling: a client (API key, or a signed-in user acting in one of their organisations), a
worker (worker token) or an admin (admin token, or a staff user signed in with two-step sign-in),
with rate limits.

Wrong keys are counted per address: after AUTH_FAILURES_PER_MINUTE failures that address gets 429
for the rest of the minute, which makes guessing keys useless (keys have 256 bits anyway).

Signed-in users (the web app) carry a session cookie (HttpOnly, Secure, SameSite=Lax). A request
that changes something with that cookie must also send the session's CSRF token in X-CSRF-Token,
and when the browser says where the request comes from (Origin), it must be the service's own site
or a listed one: another site cannot act with the user's cookie.

Requests acting for a client run with that client's id as the database tenant (row-level
security on Postgres, see db.py).
"""

from urllib.parse import urlsplit

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from . import accounts, clients, jobqueue, ratelimit, security
from .api import ApiError, client_ip, is_https
from .db import TENANT

AUTH_FAILURES_PER_MINUTE = 20
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def bearer(request):
    value = request.headers.get("authorization", "")
    if value[:7].lower() == "bearer ":
        return value[7:].strip()
    return ""


def session_cookie_name(settings):
    # __Host- cookies are only accepted over https, for this exact host and path /
    return "__Host-ae_session" if settings.public_url.startswith("https://") else "ae_session"


def set_session_cookie(response, request, token, settings):
    response.set_cookie(session_cookie_name(settings), token, max_age=int(settings.session_days * 86400), path="/",
                        httponly=True, secure=settings.public_url.startswith("https://") or is_https(request, settings),
                        samesite="lax")


def clear_session_cookie(response, settings):
    response.delete_cookie(session_cookie_name(settings), path="/", httponly=True,
                           secure=settings.public_url.startswith("https://"), samesite="lax")


def _origin(url):
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else ""


def allowed_origins(settings):
    return {o for o in [_origin(settings.public_url), _origin(settings.app_link),
                        *(_origin(c) for c in settings.cors_origins)] if o}


def check_origin(request):
    """A browser request from another site (Origin header) is refused for cookie actions and sign-in."""
    origin = request.headers.get("origin")
    if origin and origin.lower() != "null" and _origin(origin) in allowed_origins(request.app.state.settings):
        return
    if origin:
        raise ApiError(403, "bad_origin", "This request must come from the AutoEdit web app.")


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


def _session(request, t, fail_key):
    """(session, user) from the cookie, with the CSRF and origin checks; None without a cookie."""
    settings = request.app.state.settings
    token = request.cookies.get(session_cookie_name(settings))
    if not token:
        return None
    found = accounts.authenticate_session(t, settings, token)
    if found is None:
        return "invalid"
    session, user = found
    if request.method not in SAFE_METHODS:
        check_origin(request)
        if not security.token_matches(request.headers.get("x-csrf-token", ""), session["csrf_token"]):
            raise ApiError(403, "csrf", "Missing or wrong X-CSRF-Token (reload the app).")
    return session, user


def _rate(t, client, request, who):
    if request.url.path.endswith("/chunk"):             # file pieces: their own, higher limit
        return ratelimit.hit(t, f"chunks:{who}", max(600, 5 * int(client["rate_per_minute"])))
    return ratelimit.hit(t, f"client:{who}", int(client["rate_per_minute"]))


def _require_client(request, roles=None):
    state = request.app.state
    token = bearer(request)
    with state.db.tx() as t:
        fail_key = _guard_failures(request, t)
        if token:
            client = clients.authenticate(t, state.settings, token)
            if client is not None:
                client.update(auth="key", user_id=None, role=None, session_id=None)
                allowed, retry = _rate(t, client, request, client["id"])
        else:
            client = None
            found = _session(request, t, fail_key)
            if found is None:
                raise ApiError(401, "unauthorized", "Sign in, or send an API key (Authorization: Bearer ak_...).")
            if found != "invalid":
                session, user = found
                if not session["client_id"]:
                    raise ApiError(409, "no_organisation", "Choose an organisation first (POST /v1/orgs/{id}/switch).")
                role = accounts.role_in(t, user["id"], session["client_id"])
                row = clients.get_client(t, session["client_id"]) if role else None
                if row is None:
                    raise ApiError(409, "no_organisation", "You are no longer in that organisation; choose another.")
                if row["status"] != "active":
                    raise ApiError(403, "suspended", "This organisation is suspended. Contact support.")
                client = {**row, "key_id": None, "auth": "session", "user_id": user["id"], "role": role,
                          "session_id": session["id"]}
                # each person has their own rate limit inside the organisation's
                allowed, retry = _rate(t, client, request, f"{client['id']}:{user['id']}")
    if client is None:
        _fail(request, fail_key)
        raise ApiError(401, "unauthorized", "A valid API key or sign-in is needed.")
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many requests; slow down.", {"Retry-After": str(retry)})
    if roles and client["auth"] == "session" and client["role"] not in roles:
        raise ApiError(403, "forbidden", "Only an owner or admin of the organisation can do this.")
    request.state.actor = f"client:{client['id']}" + (f"/user:{client['user_id']}" if client["user_id"] else "")
    return client


async def require_client(request: Request):
    """The client (an API key's, or the signed-in user's organisation). Everything after this runs
    as that tenant in the database."""
    client = await run_in_threadpool(_require_client, request)
    TENANT.set(client["id"])
    return client


async def require_manager(request: Request):
    """Like require_client, but a signed-in user must be an owner or admin of the organisation (API
    keys can do everything their client can)."""
    client = await run_in_threadpool(_require_client, request, accounts.MANAGERS)
    TENANT.set(client["id"])
    return client


def require_user(request: Request):
    """The signed-in user (account pages): {"user", "session"}."""
    state = request.app.state
    with state.db.tx() as t:
        fail_key = _guard_failures(request, t)
        found = _session(request, t, fail_key)
    if found is None or found == "invalid":
        if found == "invalid":
            _fail(request, fail_key)
        raise ApiError(401, "unauthorized", "Please sign in.")
    session, user = found
    request.state.actor = f"user:{user['id']}"
    return {"user": user, "session": session}


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
    """The admin token (scripts, the command line), or a staff user signed in with two-step sign-in
    (the admin pages)."""
    state = request.app.state
    token = bearer(request)
    with state.db.tx() as t:
        fail_key = _guard_failures(request, t)
        found = None if token else _session(request, t, fail_key)
    if token:
        if security.token_matches(token, state.settings.admin_token):
            request.state.actor = "admin"
            return "admin"
    elif found not in (None, "invalid"):
        session, user = found
        if user["is_admin"]:
            if state.settings.admin_require_mfa and not (user["mfa_enabled_at"] and session["mfa_verified"]):
                raise ApiError(403, "mfa_required", "Staff must sign in with two-step sign-in to use the admin pages.")
            request.state.actor = f"admin:{user['id']}"
            return f"admin:{user['id']}"
        raise ApiError(403, "forbidden", "This is for the service's staff only.")
    _fail(request, fail_key)
    raise ApiError(401, "unauthorized", "The admin token is needed.")


def ip_limit(request, limit=300, name="ip", window=60):
    state = request.app.state
    with state.db.tx() as t:
        ok, retry = ratelimit.hit(t, f"{name}:{client_ip(request, state.settings)}", limit, window=window)
    if not ok:
        raise ApiError(429, "rate_limited", "Too many requests; slow down.", {"Retry-After": str(retry)})
