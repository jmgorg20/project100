"""Accounts for the web app: sign-up, sign-in (password, Google, two-step codes), sessions, password
reset, the user's own data, organisations, members and invitations.

The session is an HttpOnly cookie; every request that changes something with it also sends the
CSRF token from GET /v1/auth/session (header X-CSRF-Token). Sign-up, sign-in and reset are limited
per address and refuse requests from other sites (Origin), and ask for a captcha when it is set up.
"""

import json
import secrets

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from . import accounts, captcha, clients, oauth, passwords, ratelimit, security
from .accounts import AccountError
from .api import ApiError, client_ip
from .deps import check_origin, clear_session_cookie, ip_limit, require_user, set_session_cookie

router = APIRouter(prefix="/v1")
OAUTH_COOKIE = "ae_oauth"


def _err(exc):
    if isinstance(exc, AccountError):
        return ApiError(exc.status, exc.code, str(exc), exc.headers)
    if isinstance(exc, passwords.PasswordError):
        return ApiError(422, "weak_password", str(exc))
    return ApiError(400, "invalid", str(exc))


def _ip(request):
    return client_ip(request, request.app.state.settings)


def _captcha(request, body, always=True):
    s = request.app.state
    if not captcha.enabled(s.settings) or not always:
        return
    if not captcha.verify(s.settings, s.http, body.get("captcha"), _ip(request)):
        raise ApiError(400, "captcha", "Please complete the check that you are not a robot.")


def _anonymous_post(request, body, name, limit, window=60):
    """Sign-up / sign-in / reset: from our own site, a JSON body, a limit per address, and a honeypot
    field that people never fill in (bots do)."""
    check_origin(request)
    if not isinstance(body, dict):
        raise ApiError(422, "invalid", "A JSON object is needed.")
    ip_limit(request, limit, name, window)
    if body.get("website"):
        raise ApiError(400, "invalid", "Please try again.")


def session_payload(t, settings, session, user):
    org = clients.get_client(t, session["client_id"]) if session["client_id"] else None
    return {"user": accounts.public_user(user), "csrf_token": session["csrf_token"],
            "organisation": ({"id": org["id"], "name": org["name"], "status": org["status"],
                              "role": accounts.role_in(t, user["id"], org["id"])} if org else None),
            "organisations": accounts.orgs_of(t, user["id"]), "mfa_verified": bool(session["mfa_verified"]),
            "session_expires_at": session["expires_at"]}


def _sign_in(request, response, t, user, mfa_verified=False):
    s = request.app.state
    token, session = accounts.create_session(t, s.settings, user, _ip(request), request.headers.get("user-agent"),
                                             mfa_verified=mfa_verified)
    set_session_cookie(response, request, token, s.settings)
    return session_payload(t, s.settings, session, user)


# ---------------------------------------------------------------- public settings for the app

@router.get("/auth/config")
def auth_config(request: Request):
    s = request.app.state
    with s.db.tx() as t:
        mode = accounts.signup_mode(t, s.settings)
    return {"signup_mode": mode, "providers": oauth.configured(s.settings), "terms_version": s.settings.terms_version,
            "captcha": {"provider": s.settings.captcha_provider or None, "site_key": s.settings.captcha_site_key or None},
            "password_min_length": passwords.MIN_LENGTH}


# ---------------------------------------------------------------- sign-up and email

@router.post("/auth/signup", status_code=202)
def signup(request: Request, body: dict):
    s = request.app.state
    _anonymous_post(request, body, "signup", s.settings.signups_per_ip_hour, 3600)
    _captcha(request, body)
    with s.db.tx() as t:
        try:
            return accounts.signup(t, s.settings, body.get("email"), body.get("password"), body.get("name"),
                                   body.get("invite_code"), _ip(request), body.get("locale"), body.get("device_id"),
                                   body.get("accept_terms"))
        except (AccountError, passwords.PasswordError) as exc:
            raise _err(exc)


@router.post("/auth/verify")
def verify(request: Request, body: dict, response: Response):
    s = request.app.state
    _anonymous_post(request, body, "verify", 20)
    with s.db.tx() as t:
        try:
            user = accounts.verify_email(t, s.settings, body.get("token"), body.get("device_id"))
        except AccountError as exc:
            raise _err(exc)
        if user["mfa_enabled_at"]:
            return {"mfa_required": True, "ticket": accounts.start_mfa_ticket(t, s.settings, user)}
        return _sign_in(request, response, t, user)


@router.post("/auth/resend", status_code=202)
def resend(request: Request, body: dict):
    s = request.app.state
    _anonymous_post(request, body, "resend", 5)
    _captcha(request, body)
    with s.db.tx() as t:
        return accounts.resend_verification(t, s.settings, body.get("email"))


# ---------------------------------------------------------------- sign-in

@router.post("/auth/login")
def login(request: Request, body: dict, response: Response):
    s = request.app.state
    _anonymous_post(request, body, "login", s.settings.logins_per_ip_minute)
    ip = _ip(request)
    with s.db.tx() as t:
        recent_failures = ratelimit.peek(t, f"loginfail-ip:{ip}", accounts.LOCK_WINDOW)
    _captcha(request, body, always=recent_failures >= 3)        # a captcha after a few failures
    with s.db.tx() as t:
        try:
            user, key = accounts.login(t, s.settings, body.get("email"), body.get("password"), ip)
        except AccountError as exc:
            raise _err(exc)
        if user is None:
            accounts.record_login_failure(t, key, ip=ip)
            ratelimit.hit(t, f"loginfail-ip:{ip}", 10 ** 9, window=accounts.LOCK_WINDOW)
    if user is None:
        raise ApiError(401, "bad_credentials", "Wrong email or password.")
    with s.db.tx() as t:
        if user["mfa_enabled_at"]:
            return {"mfa_required": True, "ticket": accounts.start_mfa_ticket(t, s.settings, user)}
        return _sign_in(request, response, t, user)


@router.post("/auth/mfa")
def login_mfa(request: Request, body: dict, response: Response):
    s = request.app.state
    _anonymous_post(request, body, "mfa", 20)
    with s.db.tx() as t:
        try:
            found = accounts.finish_mfa(t, s.settings, body.get("ticket"), body.get("code"))
        except AccountError as exc:
            raise _err(exc)
    if found is None:
        raise ApiError(401, "bad_code", "That code is not right.")
    with s.db.tx() as t:
        return _sign_in(request, response, t, found[0], mfa_verified=True)


@router.get("/auth/session")
def get_session(request: Request, me=Depends(require_user)):
    s = request.app.state
    with s.db.tx() as t:
        return session_payload(t, s.settings, me["session"], me["user"])


@router.post("/auth/logout", status_code=204)
def logout(request: Request, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        accounts.revoke_session(t, me["user"]["id"], me["session"]["id"])
    response = Response(status_code=204)
    clear_session_cookie(response, request.app.state.settings)
    return response


@router.get("/auth/sessions")
def sessions(request: Request, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        rows = accounts.list_sessions(t, me["user"]["id"])
    return {"sessions": [{**r, "current": r["id"] == me["session"]["id"]} for r in rows]}


@router.delete("/auth/sessions/{session_id}", status_code=204)
def end_session(request: Request, session_id: str, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        try:
            accounts.revoke_session(t, me["user"]["id"], session_id)
        except AccountError as exc:
            raise _err(exc)
    return Response(status_code=204)


@router.post("/auth/sessions/end-others")
def end_other_sessions(request: Request, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        return {"ended": accounts.revoke_all_sessions(t, me["user"]["id"], me["session"]["id"])}


# ---------------------------------------------------------------- passwords

@router.post("/auth/password/forgot", status_code=202)
def forgot(request: Request, body: dict):
    s = request.app.state
    _anonymous_post(request, body, "forgot", 5)
    _captcha(request, body)
    with s.db.tx() as t:
        return accounts.request_password_reset(t, s.settings, body.get("email"))


@router.post("/auth/password/reset", status_code=204)
def reset(request: Request, body: dict):
    s = request.app.state
    _anonymous_post(request, body, "reset", 10)
    with s.db.tx() as t:
        try:
            accounts.reset_password(t, s.settings, body.get("token"), body.get("password"), _ip(request))
        except (AccountError, passwords.PasswordError) as exc:
            raise _err(exc)
    return Response(status_code=204)


@router.post("/auth/password/change", status_code=204)
def change_password(request: Request, body: dict, me=Depends(require_user)):
    s = request.app.state
    ip_limit(request, 10, "pwchange")
    with s.db.tx() as t:
        try:
            accounts.change_password(t, s.settings, me["user"], body.get("current_password"), body.get("new_password"),
                                     me["session"]["id"], _ip(request))
        except (AccountError, passwords.PasswordError) as exc:
            raise _err(exc)
    return Response(status_code=204)


# ---------------------------------------------------------------- two-step sign-in

@router.post("/auth/mfa/setup")
def mfa_setup(request: Request, me=Depends(require_user)):
    s = request.app.state
    with s.db.tx() as t:
        try:
            return accounts.mfa_setup(t, s.settings, me["user"])
        except AccountError as exc:
            raise _err(exc)


@router.post("/auth/mfa/enable")
def mfa_enable(request: Request, body: dict, me=Depends(require_user)):
    s = request.app.state
    ip_limit(request, 10, "mfaenable")
    with s.db.tx() as t:
        try:
            codes = accounts.mfa_enable(t, s.settings, me["user"], body.get("code"))
        except AccountError as exc:
            raise _err(exc)
        t.run("UPDATE sessions SET mfa_verified = 1 WHERE id = ?", (me["session"]["id"],))
    return {"recovery_codes": codes, "note": "Keep these codes somewhere safe: each works once if you lose your phone."}


@router.post("/auth/mfa/disable", status_code=204)
def mfa_disable(request: Request, body: dict, me=Depends(require_user)):
    s = request.app.state
    ip_limit(request, 10, "mfadisable")
    with s.db.tx() as t:
        try:
            accounts.mfa_disable(t, s.settings, me["user"], me["session"], body.get("password"), body.get("code"))
        except AccountError as exc:
            raise _err(exc)
    return Response(status_code=204)


# ---------------------------------------------------------------- Google sign-in

@router.get("/auth/oauth/{provider}/start")
def oauth_start(request: Request, provider: str, invite_code: str = None, device_id: str = None,
                accept_terms: int = 0):
    s = request.app.state
    ip_limit(request, 20, "oauth")
    try:
        oauth.credentials(s.settings, provider)
    except oauth.OAuthError as exc:
        raise ApiError(404, "not_found", str(exc))
    verifier, challenge = oauth.pkce_pair()
    binding = secrets.token_urlsafe(24)
    with s.db.tx() as t:
        state = accounts.new_token(t, s.settings, "oauth_state", None, 10,
                                   {"provider": provider, "verifier": verifier, "invite_code": invite_code,
                                    "device": device_id if device_id and len(device_id) <= 100 else None,
                                    "terms": accept_terms == 1,
                                    "binding": security.hash_token(s.settings.secret_key, "oauth_binding", binding)})
    response = RedirectResponse(oauth.authorize_url(s.settings, provider, state, challenge), status_code=302)
    response.set_cookie(OAUTH_COOKIE, binding, max_age=600, path="/v1/auth/oauth/", httponly=True,
                        secure=s.settings.public_url.startswith("https://"), samesite="lax")
    return response


def _back_to_app(settings, route):
    return RedirectResponse(f"{settings.app_link}#/{route}", status_code=302)


@router.get("/auth/oauth/{provider}/callback")
def oauth_callback(request: Request, provider: str, state: str = "", code: str = "", error: str = ""):
    s = request.app.state
    ip_limit(request, 20, "oauth")
    with s.db.tx() as t:
        row = accounts.peek_token(t, s.settings, "oauth_state", state)
        if row:
            accounts.use_token(t, s.settings, "oauth_state", state)
    data = json.loads(row["data"] or "{}") if row else {}
    binding = request.cookies.get(OAUTH_COOKIE, "")
    if (not row or data.get("provider") != provider or not binding
            or not security.token_matches(security.hash_token(s.settings.secret_key, "oauth_binding", binding),
                                          data.get("binding"))):
        return _back_to_app(s.settings, "login?error=oauth_state")
    if error or not code:
        return _back_to_app(s.settings, "login?error=oauth_cancelled")
    try:
        profile = oauth.fetch_profile(s.settings, s.http, provider, code, data["verifier"])
    except oauth.OAuthError:
        return _back_to_app(s.settings, "login?error=oauth_failed")
    with s.db.tx() as t:
        try:
            user, _created = accounts.oauth_login(t, s.settings, provider, profile, data.get("invite_code"), _ip(request),
                                                  data.get("device"), data.get("terms") is True)
        except AccountError as exc:
            return _back_to_app(s.settings, f"login?error={exc.code}")
        if user["mfa_enabled_at"]:
            ticket = accounts.start_mfa_ticket(t, s.settings, user)
            response = _back_to_app(s.settings, f"mfa/{ticket}")
        else:
            response = _back_to_app(s.settings, "")
            token, _session = accounts.create_session(t, s.settings, user, _ip(request), request.headers.get("user-agent"))
            set_session_cookie(response, request, token, s.settings)
    response.delete_cookie(OAUTH_COOKIE, path="/v1/auth/oauth/")
    return response


# ---------------------------------------------------------------- the account

@router.patch("/account")
def update_account(request: Request, body: dict, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        try:
            return {"user": accounts.public_user(accounts.update_profile(t, me["user"], body))}
        except AccountError as exc:
            raise _err(exc)


@router.get("/account/export")
def export_account(request: Request, me=Depends(require_user)):
    ip_limit(request, 10, "export")
    with request.app.state.db.tx() as t:
        data = accounts.export_account(t, me["user"])
    return Response(content=json.dumps(data, indent=1, default=str), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="autoedit-my-data.json"'})


@router.post("/account/delete")
def delete_account(request: Request, body: dict, me=Depends(require_user)):
    """Delete my account (password, and a two-step code when it is on). Organisations where I am the
    only owner are deleted with all their files."""
    s = request.app.state
    ip_limit(request, 5, "deleteacct")
    with s.db.tx() as t:
        try:
            accounts.reauthenticate(t, s.settings, me["user"], me["session"], body.get("password"), body.get("code"))
        except AccountError as exc:
            raise _err(exc)
    with s.db.tx() as t:
        result = accounts.delete_account(t, s.settings, s.storage, me["user"])
    response = Response(content=json.dumps(result), media_type="application/json")
    clear_session_cookie(response, s.settings)
    return response


# ---------------------------------------------------------------- organisations

def _active_org(t, me, roles=None):
    session = me["session"]
    if not session["client_id"]:
        raise ApiError(409, "no_organisation", "Choose an organisation first.")
    role = accounts.role_in(t, me["user"]["id"], session["client_id"])
    org = clients.get_client(t, session["client_id"]) if role else None
    if not org:
        raise ApiError(409, "no_organisation", "You are no longer in that organisation; choose another.")
    if roles and role not in roles:
        raise ApiError(403, "forbidden", "Only an owner or admin of the organisation can do this.")
    return org, role


@router.get("/orgs")
def list_orgs(request: Request, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        return {"organisations": accounts.orgs_of(t, me["user"]["id"]), "current": me["session"]["client_id"]}


@router.post("/orgs", status_code=201)
def create_org(request: Request, body: dict, me=Depends(require_user)):
    s = request.app.state
    with s.db.tx() as t:
        try:
            org = accounts.create_org(t, s.settings, me["user"], body.get("name"))
        except AccountError as exc:
            raise _err(exc)
        accounts.switch_org(t, me["session"], org["id"])
    return {"id": org["id"], "name": org["name"], "role": "owner"}


@router.post("/orgs/{client_id}/switch")
def switch_org(request: Request, client_id: str, me=Depends(require_user)):
    s = request.app.state
    with s.db.tx() as t:
        try:
            accounts.switch_org(t, me["session"], client_id)
        except AccountError as exc:
            raise _err(exc)
        session = t.one("SELECT * FROM sessions WHERE id = ?", (me["session"]["id"],))
        return session_payload(t, s.settings, session, me["user"])


@router.patch("/org")
def rename_org(request: Request, body: dict, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        org, _ = _active_org(t, me, accounts.MANAGERS)
        try:
            org = clients.update_client(t, org["id"], {"name": body.get("name")})
        except clients.ClientError as exc:
            raise ApiError(422, "invalid", str(exc))
        clients.audit(t, f"user:{me['user']['id']}", "org.renamed", org["id"])
        return {"id": org["id"], "name": org["name"]}


@router.post("/org/delete")
def delete_org(request: Request, body: dict, me=Depends(require_user)):
    """Delete the current organisation with all its files (owners only; password needed)."""
    s = request.app.state
    ip_limit(request, 5, "deleteorg")
    with s.db.tx() as t:
        org, _ = _active_org(t, me, ("owner",))
        try:
            accounts.reauthenticate(t, s.settings, me["user"], me["session"], body.get("password"), body.get("code"))
        except AccountError as exc:
            raise _err(exc)
    with s.db.tx() as t:
        accounts.delete_org(t, s.storage, org["id"])
        clients.audit(t, f"user:{me['user']['id']}", "org.deleted", org["id"], {"name": org["name"]}, _ip(request))
    return {"deleted": org["id"]}


@router.get("/org/members")
def list_members(request: Request, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        org, role = _active_org(t, me)
        return {"members": accounts.members(t, org["id"]), "your_role": role}


@router.patch("/org/members/{user_id}")
def change_member(request: Request, user_id: str, body: dict, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        org, role = _active_org(t, me, accounts.MANAGERS)
        try:
            accounts.change_role(t, org["id"], role, user_id, body.get("role"))
        except AccountError as exc:
            raise _err(exc)
        clients.audit(t, f"user:{me['user']['id']}", "member.role", user_id, {"org": org["id"], "role": body.get("role")})
        return {"members": accounts.members(t, org["id"])}


@router.delete("/org/members/{user_id}", status_code=204)
def remove_member(request: Request, user_id: str, me=Depends(require_user)):
    """Remove a member (owners and admins), or leave the organisation (your own id)."""
    with request.app.state.db.tx() as t:
        org, role = _active_org(t, me)
        try:
            accounts.remove_member(t, org["id"], role, me["user"]["id"], user_id)
        except AccountError as exc:
            raise _err(exc)
        clients.audit(t, f"user:{me['user']['id']}", "member.removed", user_id, {"org": org["id"]})
    return Response(status_code=204)


@router.get("/org/invites")
def list_invites(request: Request, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        org, _ = _active_org(t, me, accounts.MANAGERS)
        return {"invites": accounts.list_invites(t, org["id"])}


@router.post("/org/invites", status_code=201)
def invite(request: Request, body: dict, me=Depends(require_user)):
    s = request.app.state
    ip_limit(request, 20, "invite")
    with s.db.tx() as t:
        org, _ = _active_org(t, me, accounts.MANAGERS)
        try:
            out = accounts.invite_member(t, s.settings, org, me["user"], body.get("email"), body.get("role", "member"))
        except AccountError as exc:
            raise _err(exc)
        clients.audit(t, f"user:{me['user']['id']}", "member.invited", out["id"], {"org": org["id"], "role": out["role"]})
    return out


@router.delete("/org/invites/{invite_id}", status_code=204)
def revoke_invite(request: Request, invite_id: str, me=Depends(require_user)):
    with request.app.state.db.tx() as t:
        org, _ = _active_org(t, me, accounts.MANAGERS)
        try:
            accounts.revoke_invite(t, org["id"], invite_id)
        except AccountError as exc:
            raise _err(exc)
    return Response(status_code=204)


@router.post("/invites/accept")
def accept_invite(request: Request, body: dict, me=Depends(require_user)):
    s = request.app.state
    ip_limit(request, 20, "accept")
    with s.db.tx() as t:
        try:
            org = accounts.accept_invite(t, s.settings, me["user"], body.get("token"))
        except AccountError as exc:
            raise _err(exc)
        accounts.switch_org(t, me["session"], org["id"])
        session = t.one("SELECT * FROM sessions WHERE id = ?", (me["session"]["id"],))
        return session_payload(t, s.settings, session, me["user"])

