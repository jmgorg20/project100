"""Accounts for the web app: sign-up (invite codes, the pause switch), email verification, sign-in,
lockout, sessions and CSRF, password reset, two-step sign-in, staff access, organisations, members,
invitations, projects, Google sign-in, captcha, export and delete. Every test runs on SQLite and on
real Postgres (as an ordinary user, so row-level security applies)."""

import dataclasses
import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from service import accounts, mailer, totp
from service.api import create_app
from service.db import now
from tests.service.helpers import admin, make_video, new_client, ready_upload

PASSWORD = "correct horse battery"


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("media") / "talk.mp4", seconds=1.0)


def make_app(settings, **changes):
    changes = {"password_cost": 10, "signups_per_ip_hour": 1000, "logins_per_ip_minute": 1000, **changes}
    return create_app(dataclasses.replace(settings, **changes))


@pytest.fixture
def app(settings):
    return make_app(settings)


@pytest.fixture
def http(app):
    with TestClient(app) as c:
        yield c


def browser(app):
    """Another browser (its own cookies)."""
    return TestClient(app)


def last_email(app, to, template=None):
    sql = "SELECT * FROM email_outbox WHERE to_addr = ?" + (" AND template = ?" if template else "")
    with app.state.db.tx() as t:
        rows = t.all(sql + " ORDER BY created_at DESC", (to.lower(), template) if template else (to.lower(),))
    return rows[0] if rows else None


def link_token(email_row, route):
    return re.search(rf"#/{route}/(\S+)", email_row["body"]).group(1)


def invite_code(http, uses=1):
    r = http.post("/v1/admin/invite-codes", json={"max_uses": uses}, headers=admin(http))
    assert r.status_code == 201, r.text
    return r.json()["code"]


def signup(http, email, password=PASSWORD, code=None, **extra):
    body = {"email": email, "password": password, "invite_code": code if code is not None else invite_code(http),
            "accept_terms": True, **extra}
    return http.post("/v1/auth/signup", json=body)


def verified_user(app, http, email, password=PASSWORD):
    """A confirmed user, signed in on `http`. Returns the session payload."""
    assert signup(http, email, password).status_code == 202
    r = http.post("/v1/auth/verify", json={"token": link_token(last_email(app, email, "verify_email"), "verify")})
    assert r.status_code == 200, r.text
    return r.json()


def csrf(payload):
    return {"X-CSRF-Token": payload["csrf_token"]}


# ---------------------------------------------------------------- sign-up

def test_signup_needs_an_invite_code_and_can_be_paused(http, app):
    r = http.post("/v1/auth/signup", json={"email": "a@example.com", "password": PASSWORD, "accept_terms": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "invite_required"
    assert signup(http, "a@example.com", code="AAAA-BBBB-CCCC-DDDD").status_code == 403
    code = invite_code(http)
    assert signup(http, "a@example.com", code=code.lower().replace("-", " ")).status_code == 202   # forgiving to type
    assert signup(http, "b@example.com", code=code).json()["error"]["code"] == "invite_required"  # used up
    assert http.put("/v1/admin/signups", json={"mode": "closed"}, headers=admin(http)).json() == {"mode": "closed"}
    r = signup(http, "c@example.com")
    assert r.status_code == 403 and r.json()["error"]["code"] == "signups_paused"
    assert http.get("/v1/auth/config").json()["signup_mode"] == "closed"
    http.put("/v1/admin/signups", json={"mode": "open"}, headers=admin(http))
    assert http.post("/v1/auth/signup", json={"email": "c@example.com", "password": PASSWORD, "accept_terms": True}).status_code == 202
    with app.state.db.tx() as t:
        codes = accounts.list_invite_codes(t)
        audit = [r["action"] for r in t.all("SELECT action FROM audit_log")]
    assert sorted(c["uses"] for c in codes) == [0, 1] and "code_hash" not in codes[0]
    assert "signups.mode" in audit and "invite_code.created" in audit


def test_signup_does_not_reveal_whether_an_email_has_an_account(http, app):
    verified_user(app, http, "taken@example.com")
    code = invite_code(http)
    r1 = signup(http, "taken@example.com", code=code)
    r2 = signup(http, "free@example.com", code=invite_code(http))
    assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json() == {"status": "check_email"}
    assert last_email(app, "taken@example.com")["template"] == "already_registered"
    assert last_email(app, "free@example.com")["template"] == "verify_email"
    assert signup(http, "other@example.com", code=code).status_code == 202      # the code was not used up by r1
    assert http.post("/v1/auth/resend", json={"email": "nobody@example.com"}).json() == {"status": "check_email"}


def test_email_rules(http, app):
    for bad in ("not-an-email", "a@b", "x" * 250 + "@example.com", "a b@example.com"):
        assert signup(http, bad).status_code == 422, bad
    r = signup(http, "me@mailinator.com")
    assert r.status_code == 422 and r.json()["error"]["code"] == "email_not_accepted"
    blocked = make_app(app.state.settings, blocked_email_domains=["spam.example"])
    with TestClient(blocked) as c:
        assert signup(c, "a@spam.example").status_code == 422
    # one account per mailbox: Gmail ignores dots, +tags go to the same mailbox
    verified_user(app, http, "Juan.Dela.Cruz+promo@Gmail.com")
    signup(http, "juandelacruz@gmail.com")
    assert last_email(app, "juan.dela.cruz+promo@gmail.com")["template"] == "already_registered"   # the account's address
    with app.state.db.tx() as t:
        assert t.value("SELECT COUNT(*) FROM users") == 1
        assert t.value("SELECT email FROM users") == "juan.dela.cruz+promo@gmail.com"


def test_password_rules(http):
    for bad, word in (("short", "at least"), ("1234567890", "common"), ("aaaaaaaaaaaa", "common"),
                      ("maria-rosa-2026!", "email name")):
        r = signup(http, "maria-rosa@example.com", password=bad)
        assert r.status_code == 422 and word in r.json()["error"]["message"], (bad, r.text)


def test_sign_up_needs_the_terms_accepted_and_keeps_the_version(http, app):
    for value in (None, False, "yes", 1):
        r = signup(http, "terms@example.com", accept_terms=value)
        assert r.status_code == 422 and r.json()["error"]["code"] == "terms_required", value
    assert signup(http, "terms@example.com").status_code == 202
    with app.state.db.tx() as t:
        row = t.one("SELECT terms_version, terms_accepted_at FROM users WHERE email = 'terms@example.com'")
    assert row["terms_version"] == app.state.settings.terms_version and row["terms_accepted_at"]
    assert http.get("/v1/auth/config").json()["terms_version"] == app.state.settings.terms_version


def test_verify_then_sign_in(http, app):
    assert signup(http, "ana@example.com").status_code == 202
    r = http.post("/v1/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"
    token = link_token(last_email(app, "ana@example.com", "verify_email"), "verify")
    r = http.post("/v1/auth/verify", json={"token": token})
    assert r.status_code == 200
    s = r.json()
    assert s["user"]["email"] == "ana@example.com" and s["user"]["email_verified"]
    assert s["organisation"]["role"] == "owner" and "workspace" in s["organisation"]["name"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert http.post("/v1/auth/verify", json={"token": token}).status_code == 400   # once only
    # the session acts as the organisation on the client API
    me = http.get("/v1/me")
    assert me.status_code == 200 and me.json()["role"] == "owner" and me.json()["client"]["kind"] == "organization"
    assert "session_id" not in me.json()["client"]
    assert http.get("/v1/auth/session").json()["user"]["id"] == s["user"]["id"]
    # a new browser signs in with the password
    with browser(app) as b:
        assert b.get("/v1/me").status_code == 401
        assert b.post("/v1/auth/login", json={"email": "ANA@example.com", "password": PASSWORD}).status_code == 200
        assert b.get("/v1/me").status_code == 200


def test_an_unconfirmed_signup_cannot_reserve_someone_elses_email(http, app):
    signup(http, "victim@example.com", password="attacker password 1")
    old = link_token(last_email(app, "victim@example.com", "verify_email"), "verify")
    signup(http, "victim@example.com", password="the real owner pw")
    new = link_token(last_email(app, "victim@example.com", "verify_email"), "verify")
    assert http.post("/v1/auth/verify", json={"token": old}).status_code == 400
    assert http.post("/v1/auth/verify", json={"token": new}).status_code == 200
    with browser(app) as b:
        assert b.post("/v1/auth/login", json={"email": "victim@example.com", "password": "attacker password 1"}).status_code == 401
        assert b.post("/v1/auth/login", json={"email": "victim@example.com", "password": "the real owner pw"}).status_code == 200


# ---------------------------------------------------------------- sign-in, lockout, sessions, CSRF

def test_wrong_password_and_unknown_email_look_the_same_and_lock(settings):
    app = make_app(settings, login_failures_per_account=3, logins_per_ip_minute=1000)
    with TestClient(app) as http:
        verified_user(app, http, "lock@example.com")
        with browser(app) as b:
            r1 = b.post("/v1/auth/login", json={"email": "lock@example.com", "password": "wrong password 1"})
            r2 = b.post("/v1/auth/login", json={"email": "ghost@example.com", "password": "wrong password 1"})
            assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()
            for _ in range(2):
                b.post("/v1/auth/login", json={"email": "lock@example.com", "password": "wrong password 1"})
                b.post("/v1/auth/login", json={"email": "ghost@example.com", "password": "wrong password 1"})
            r1 = b.post("/v1/auth/login", json={"email": "lock@example.com", "password": PASSWORD})   # right, but paused
            r2 = b.post("/v1/auth/login", json={"email": "ghost@example.com", "password": PASSWORD})
            assert r1.status_code == r2.status_code == 429 and r1.json() == r2.json()
            assert r1.json()["error"]["code"] == "account_paused"


def test_sign_in_and_sign_up_are_limited_per_address(settings):
    app = make_app(settings, logins_per_ip_minute=3, signups_per_ip_hour=2)
    with TestClient(app) as http:
        codes = [http.post("/v1/auth/login", json={"email": "x@example.com", "password": "x" * 12}).status_code
                 for _ in range(4)]
        assert codes == [401, 401, 401, 429]
        http.put("/v1/admin/signups", json={"mode": "open"}, headers=admin(http))
        codes = [http.post("/v1/auth/signup", json={"email": f"s{i}@example.com", "password": PASSWORD,
                                                           "accept_terms": True}).status_code
                 for i in range(3)]
        assert codes == [202, 202, 429]
        # a bot that fills the hidden field gets nothing
        r = http.post("/v1/auth/resend", json={"email": "s0@example.com", "website": "http://spam"})
        assert r.status_code == 400


def test_csrf_origin_logout_and_sessions(http, app):
    s = verified_user(app, http, "csrf@example.com")
    assert http.post("/v1/projects", json={"name": "No token"}).json()["error"]["code"] == "csrf"
    assert http.post("/v1/projects", json={"name": "Wrong"}, headers={"X-CSRF-Token": "x" * 32}).status_code == 403
    assert http.post("/v1/projects", json={"name": "Ok"}, headers=csrf(s)).status_code == 201
    evil = {**csrf(s), "Origin": "https://evil.example"}
    assert http.post("/v1/projects", json={"name": "Evil"}, headers=evil).json()["error"]["code"] == "bad_origin"
    ours = {**csrf(s), "Origin": "http://127.0.0.1:8787"}
    assert http.post("/v1/projects", json={"name": "Ours"}, headers=ours).status_code == 201
    # nobody can sign a visitor in from another site (login CSRF)
    assert http.post("/v1/auth/login", json={"email": "csrf@example.com", "password": PASSWORD},
                     headers={"Origin": "https://evil.example"}).status_code == 403
    assert http.get("/v1/projects").status_code == 200                          # reading needs no token
    with browser(app) as b:
        b.post("/v1/auth/login", json={"email": "csrf@example.com", "password": PASSWORD})
        listed = http.get("/v1/auth/sessions").json()["sessions"]
        assert len(listed) == 2 and sum(x["current"] for x in listed) == 1
        assert http.post("/v1/auth/sessions/end-others", headers=csrf(s)).json() == {"ended": 1}
        assert b.get("/v1/me").status_code == 401
    assert http.post("/v1/auth/logout", headers=csrf(s)).status_code == 204
    assert http.get("/v1/me").status_code == 401
    assert http.get("/v1/auth/session").status_code == 401


def test_password_reset_and_change(http, app):
    s = verified_user(app, http, "reset@example.com")
    assert http.post("/v1/auth/password/forgot", json={"email": "nobody@example.com"}).status_code == 202
    assert last_email(app, "nobody@example.com") is None
    assert http.post("/v1/auth/password/forgot", json={"email": "reset@example.com"}).status_code == 202
    token = link_token(last_email(app, "reset@example.com", "reset_password"), "reset")
    with browser(app) as b:
        r = b.post("/v1/auth/password/reset", json={"token": token, "password": "short"})
        assert r.status_code == 422                                              # the link still works after this
        assert b.post("/v1/auth/password/reset", json={"token": token, "password": "a brand new secret"}).status_code == 204
        assert b.post("/v1/auth/password/reset", json={"token": token, "password": "another new secret"}).status_code == 400
        assert b.post("/v1/auth/login", json={"email": "reset@example.com", "password": PASSWORD}).status_code == 401
        assert b.post("/v1/auth/login", json={"email": "reset@example.com", "password": "a brand new secret"}).status_code == 200
    assert http.get("/v1/me").status_code == 401                                 # every session ended
    assert last_email(app, "reset@example.com")["template"] == "password_changed"
    s = http.post("/v1/auth/login", json={"email": "reset@example.com", "password": "a brand new secret"}).json()
    r = http.post("/v1/auth/password/change", json={"current_password": "wrong one!!", "new_password": "x" * 12},
                  headers=csrf(s))
    assert r.status_code == 403
    r = http.post("/v1/auth/password/change", json={"current_password": "a brand new secret",
                                                     "new_password": "the third secret"}, headers=csrf(s))
    assert r.status_code == 204 and http.get("/v1/me").status_code == 200     # this session stays


# ---------------------------------------------------------------- two-step sign-in and staff

def enable_mfa(http, s):
    setup = http.post("/v1/auth/mfa/setup", headers=csrf(s)).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    assert http.post("/v1/auth/mfa/enable", json={"code": "000000"}, headers=csrf(s)).status_code in (422, 200)
    r = http.post("/v1/auth/mfa/enable", json={"code": totp.code_at(setup["secret"])}, headers=csrf(s))
    if r.status_code == 409 or "000000" == totp.code_at(setup["secret"]):     # (one in a million)
        pytest.skip("the random code was right")
    assert r.status_code == 200, r.text
    return setup["secret"], r.json()["recovery_codes"]


def test_two_step_sign_in(http, app):
    s = verified_user(app, http, "mfa@example.com")
    secret, recovery = enable_mfa(http, s)
    assert len(recovery) == 10 and last_email(app, "mfa@example.com")["template"] == "mfa_changed"
    with browser(app) as b:
        r = b.post("/v1/auth/login", json={"email": "mfa@example.com", "password": PASSWORD})
        assert r.json()["mfa_required"] and "set-cookie" not in r.headers
        ticket = r.json()["ticket"]
        assert b.get("/v1/me").status_code == 401
        assert b.post("/v1/auth/mfa", json={"ticket": ticket, "code": "123456" if totp.code_at(secret) != "123456"
                                            else "654321"}).status_code == 401
        code = totp.code_at(secret, now() + 30)                                  # the next code (the current one was used)
        r = b.post("/v1/auth/mfa", json={"ticket": ticket, "code": code})
        assert r.status_code == 200 and r.json()["mfa_verified"]
        assert b.post("/v1/auth/mfa", json={"ticket": ticket, "code": code}).status_code == 400   # ticket used
    with browser(app) as b:
        ticket = b.post("/v1/auth/login", json={"email": "mfa@example.com", "password": PASSWORD}).json()["ticket"]
        assert b.post("/v1/auth/mfa", json={"ticket": ticket, "code": code}).status_code == 401   # a code works once
        assert b.post("/v1/auth/mfa", json={"ticket": ticket, "code": recovery[0].upper()}).status_code == 200
    with browser(app) as b:
        ticket = b.post("/v1/auth/login", json={"email": "mfa@example.com", "password": PASSWORD}).json()["ticket"]
        assert b.post("/v1/auth/mfa", json={"ticket": ticket, "code": recovery[0]}).status_code == 401   # used up
        for _ in range(4):
            b.post("/v1/auth/mfa", json={"ticket": ticket, "code": "999999"})
        assert b.post("/v1/auth/mfa", json={"ticket": ticket, "code": recovery[1]}).status_code == 400   # ticket ended
    # turning it off needs the password and a code
    assert http.post("/v1/auth/mfa/disable", json={"password": PASSWORD}, headers=csrf(s)).status_code == 403
    r = http.post("/v1/auth/mfa/disable", json={"password": PASSWORD, "code": recovery[2]}, headers=csrf(s))
    assert r.status_code == 204
    assert http.post("/v1/auth/login", json={"email": "mfa@example.com", "password": PASSWORD}).json().get("mfa_required") is None


def test_staff_need_two_step_sign_in_for_the_admin_pages(http, app):
    s = verified_user(app, http, "staff@example.com")
    assert http.get("/v1/admin/clients").json()["error"]["code"] == "forbidden"
    uid = s["user"]["id"]
    assert http.patch(f"/v1/admin/users/{uid}", json={"is_admin": True}, headers=admin(http)).status_code == 200
    assert http.get("/v1/admin/clients").json()["error"]["code"] == "mfa_required"
    secret, _ = enable_mfa(http, s)
    assert http.get("/v1/admin/clients").status_code == 200       # this session just proved the code
    with browser(app) as b:
        assert b.post("/v1/auth/login", json={"email": "staff@example.com", "password": PASSWORD}).json()["mfa_required"]
    with browser(app) as b:
        ticket = b.post("/v1/auth/login", json={"email": "staff@example.com", "password": PASSWORD}).json()["ticket"]
        s2 = b.post("/v1/auth/mfa", json={"ticket": ticket, "code": totp.code_at(secret, now() + 30)}).json()
        assert b.get("/v1/admin/clients").status_code == 200
        assert b.post("/v1/admin/invite-codes", json={}).json()["error"]["code"] == "csrf"
        r = b.post("/v1/admin/invite-codes", json={}, headers=csrf(s2))
        assert r.status_code == 201
        with app.state.db.tx() as t:
            actor = t.value("SELECT actor FROM audit_log WHERE action = 'invite_code.created' ORDER BY at DESC LIMIT 1")
        assert actor == f"admin:{uid}"
        assert b.post("/v1/auth/mfa/disable", json={"password": PASSWORD, "code": "x"}, headers=csrf(s2)).status_code == 403
    # a disabled user is signed out everywhere
    http.patch(f"/v1/admin/users/{uid}", json={"status": "disabled"}, headers=admin(http))
    assert http.get("/v1/me").status_code == 401
    r = http.post("/v1/auth/login", json={"email": "staff@example.com", "password": PASSWORD})
    assert r.json()["error"]["code"] == "account_disabled"


# ---------------------------------------------------------------- organisations

def test_members_roles_and_invitations(http, app, video):
    owner = verified_user(app, http, "owner@example.com")
    org = owner["organisation"]["id"]
    with browser(app) as bob_b, browser(app) as eve_b:
        bob = verified_user(app, bob_b, "bob@example.com")
        eve = verified_user(app, eve_b, "eve@example.com")
        r = http.post("/v1/org/invites", json={"email": "bob@example.com", "role": "member"}, headers=csrf(owner))
        assert r.status_code == 201
        token = link_token(last_email(app, "bob@example.com", "org_invite"), "invite")
        # the invitation is for Bob only, even if Eve gets the link
        r = eve_b.post("/v1/invites/accept", json={"token": token}, headers=csrf(eve))
        assert r.status_code == 403 and r.json()["error"]["code"] == "wrong_account"
        r = bob_b.post("/v1/invites/accept", json={"token": token}, headers=csrf(bob))
        assert r.status_code == 200 and r.json()["organisation"]["id"] == org and r.json()["organisation"]["role"] == "member"
        assert bob_b.post("/v1/invites/accept", json={"token": token}, headers=csrf(bob)).status_code == 400
        # a member uploads and runs jobs, but cannot change presets, webhooks, roles, or delete all data
        up = ready_upload(bob_b, csrf(bob), video)
        r = bob_b.post("/v1/jobs", json={"inputs": {"main": [up["id"]]}, "preset": "viral_tiktok"}, headers=csrf(bob))
        assert r.status_code == 201
        with app.state.db.tx() as t:
            assert t.value("SELECT user_id FROM jobs WHERE id = ?", (r.json()["id"],)) == bob["user"]["id"]
        assert bob_b.get("/v1/webhooks").status_code == 403
        assert bob_b.delete("/v1/data", headers=csrf(bob)).status_code == 403
        assert bob_b.post("/v1/org/invites", json={"email": "x@example.com"}, headers=csrf(bob)).status_code == 403
        assert bob_b.patch(f"/v1/org/members/{bob['user']['id']}", json={"role": "owner"}, headers=csrf(bob)).status_code == 403
        assert bob_b.post("/v1/keys/rotate", headers=csrf(bob)).status_code == 400
        # the owner sees the job; Eve (another organisation) does not
        assert http.get(f"/v1/jobs/{r.json()['id']}").status_code == 200
        assert eve_b.get(f"/v1/jobs/{r.json()['id']}").status_code == 404
        assert eve_b.get(f"/v1/uploads/{up['id']}").status_code == 404
        assert eve_b.post(f"/v1/orgs/{org}/switch", headers=csrf(eve)).status_code == 404
        # roles: the owner makes Bob an admin; the last owner cannot step down or leave
        r = http.patch(f"/v1/org/members/{bob['user']['id']}", json={"role": "admin"}, headers=csrf(owner))
        assert r.status_code == 200
        assert bob_b.get("/v1/webhooks").status_code == 200
        assert bob_b.patch(f"/v1/org/members/{owner['user']['id']}", json={"role": "member"},
                           headers=csrf(bob)).status_code == 403                 # an admin cannot demote an owner
        oid = owner["user"]["id"]
        assert http.patch(f"/v1/org/members/{oid}", json={"role": "admin"}, headers=csrf(owner)).status_code == 409
        assert http.delete(f"/v1/org/members/{oid}", headers=csrf(owner)).status_code == 409
        # removed: Bob's session no longer reaches the organisation
        assert http.delete(f"/v1/org/members/{bob['user']['id']}", headers=csrf(owner)).status_code == 204
        assert bob_b.get("/v1/me").json()["error"]["code"] == "no_organisation"
        orgs = bob_b.get("/v1/orgs").json()["organisations"]
        assert [o["role"] for o in orgs] == ["owner"]                            # Bob's own workspace remains
        assert bob_b.post(f"/v1/orgs/{orgs[0]['id']}/switch", headers=csrf(bob)).status_code == 200
        assert bob_b.get("/v1/me").status_code == 200
        # invitations can be listed and revoked
        http.post("/v1/org/invites", json={"email": "carol@example.com", "role": "admin"}, headers=csrf(owner))
        inv = http.get("/v1/org/invites").json()["invites"]
        open_ = [i for i in inv if not i["accepted_at"]][0]
        assert http.delete(f"/v1/org/invites/{open_['id']}", headers=csrf(owner)).status_code == 204
        assert http.delete(f"/v1/org/invites/{open_['id']}", headers=csrf(owner)).status_code == 404


def test_new_organisations_and_switching(http, app):
    s = verified_user(app, http, "multi@example.com")
    r = http.post("/v1/orgs", json={"name": "Second shop"}, headers=csrf(s))
    assert r.status_code == 201
    assert http.get("/v1/me").json()["client"]["name"] == "Second shop"
    assert http.patch("/v1/org", json={"name": "Renamed"}, headers=csrf(s)).json()["name"] == "Renamed"
    for i in range(3):
        http.post("/v1/orgs", json={"name": f"Shop {i}"}, headers=csrf(s))
    assert http.post("/v1/orgs", json={"name": "Too many"}, headers=csrf(s)).status_code == 403
    first = http.get("/v1/orgs").json()["organisations"][0]["id"]
    assert http.post(f"/v1/orgs/{first}/switch", headers=csrf(s)).json()["organisation"]["id"] == first


def test_projects_belong_to_their_organisation(http, app, video):
    s = verified_user(app, http, "proj@example.com")
    p = http.post("/v1/projects", json={"name": "  Summer   ads "}, headers=csrf(s)).json()
    assert p["name"] == "Summer ads"
    up = http.post("/v1/uploads", json={"filename": "a.mp4", "size": 10, "project_id": p["id"]}, headers=csrf(s))
    assert up.status_code == 201 and up.json()["project_id"] == p["id"]
    up = ready_upload(http, csrf(s), video)
    job = http.post("/v1/jobs", json={"inputs": {"main": [up["id"]]}, "preset": "viral_tiktok", "project_id": p["id"]},
                    headers=csrf(s)).json()
    assert job["project_id"] == p["id"]
    assert [j["id"] for j in http.get("/v1/jobs", params={"project_id": p["id"]}).json()["jobs"]] == [job["id"]]
    assert http.get("/v1/projects").json()["projects"][0]["jobs"] == 1
    # an API client cannot use or see another tenant's project
    _, key = new_client(http)
    r = http.post("/v1/jobs", json={"inputs": {"main": [up["id"]]}, "preset": "viral_tiktok", "project_id": p["id"]},
                  headers=key)
    assert r.status_code in (400, 404, 422)
    assert http.get("/v1/projects", headers=key).json()["projects"] == []
    assert http.patch(f"/v1/projects/{p['id']}", json={"name": "x"}, headers=key).status_code == 404
    kp = http.post("/v1/projects", json={"name": "Partner batch"}, headers=key)
    assert kp.status_code == 201                                                 # API clients have projects too
    assert http.patch(f"/v1/projects/{p['id']}", json={"name": "Autumn"}, headers=csrf(s)).json()["name"] == "Autumn"
    assert http.delete(f"/v1/projects/{p['id']}", headers=csrf(s)).status_code == 204
    assert http.get(f"/v1/jobs/{job['id']}").json()["project_id"] is None      # the job stays


# ---------------------------------------------------------------- my data

def test_export_and_delete_my_account(http, app, video):
    s = verified_user(app, http, "leaving@example.com")
    org = s["organisation"]["id"]
    up = ready_upload(http, csrf(s), video)
    path = app.state.storage.upload_path(up["id"])
    assert path.exists()
    r = http.get("/v1/account/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["user"]["email"] == "leaving@example.com" and data["organisations"][0]["id"] == org
    assert "password_hash" not in json.dumps(data) and "mfa_secret" not in json.dumps(data)
    # a shared organisation with another owner survives; my own workspace goes
    with browser(app) as other_b:
        other = verified_user(app, other_b, "stays@example.com")
        other_org = other["organisation"]["id"]
        other_b.post("/v1/org/invites", json={"email": "leaving@example.com", "role": "member"}, headers=csrf(other))
        token = link_token(last_email(app, "leaving@example.com", "org_invite"), "invite")
        http.post("/v1/invites/accept", json={"token": token}, headers=csrf(s))
        assert http.post("/v1/account/delete", json={"password": "wrong password"}, headers=csrf(s)).status_code == 403
        r = http.post("/v1/account/delete", json={"password": PASSWORD}, headers=csrf(s))
        assert r.status_code == 200 and r.json()["deleted_organisations"] == [org]
        assert not path.exists()
        with app.state.db.tx() as t:
            assert t.one("SELECT id FROM clients WHERE id = ?", (org,)) is None
            assert t.one("SELECT id FROM clients WHERE id = ?", (other_org,)) is not None
            assert t.value("SELECT COUNT(*) FROM memberships WHERE client_id = ?", (other_org,)) == 1
            assert t.value("SELECT COUNT(*) FROM users WHERE email = 'leaving@example.com'") == 0
        assert [m["email"] for m in other_b.get("/v1/org/members").json()["members"]] == ["stays@example.com"]
    assert http.get("/v1/me").status_code == 401
    assert last_email(app, "leaving@example.com")["template"] == "account_deleted"
    assert http.post("/v1/auth/login", json={"email": "leaving@example.com", "password": PASSWORD}).status_code == 401


def test_delete_an_organisation(http, app, video):
    s = verified_user(app, http, "boss@example.com")
    second = http.post("/v1/orgs", json={"name": "Old brand"}, headers=csrf(s)).json()["id"]
    up = ready_upload(http, csrf(s), video)
    assert http.post("/v1/org/delete", json={"password": "nope nope nope"}, headers=csrf(s)).status_code == 403
    assert http.post("/v1/org/delete", json={"password": PASSWORD}, headers=csrf(s)).json() == {"deleted": second}
    assert not app.state.storage.upload_path(up["id"]).exists()
    assert http.get("/v1/me").json()["error"]["code"] == "no_organisation"
    assert len(http.get("/v1/orgs").json()["organisations"]) == 1


# ---------------------------------------------------------------- Google sign-in

class FakeHTTP:
    """Stands in for Google's token and userinfo endpoints (and captcha providers)."""

    def __init__(self, profile=None, captcha_ok=True):
        self.profile = profile or {}
        self.captcha_ok = captcha_ok
        self.calls = []

    class R:
        def __init__(self, status, data):
            self.status_code, self._data = status, data

        def json(self):
            return self._data

    def post(self, url, data=None, **kw):
        self.calls.append(("POST", url, data))
        if "siteverify" in url:
            return self.R(200, {"success": self.captcha_ok and data.get("response") == "human"})
        assert data["code_verifier"] and data["client_secret"] == "google-secret"
        return self.R(200 if data["code"] == "good-code" else 400, {"access_token": "at-123"})

    def get(self, url, headers=None, **kw):
        self.calls.append(("GET", url, headers))
        assert headers["Authorization"] == "Bearer at-123"
        return self.R(200, self.profile)


@pytest.fixture
def google(settings):
    app = make_app(settings, oauth_google_client_id="google-id", oauth_google_client_secret="google-secret")
    app.state.http = FakeHTTP({"sub": "g-1", "email": "Pia@Example.com", "email_verified": True, "name": "Pia"})
    return app


def google_round(c, code="good-code", invite=None, state=None, terms=True):
    params = {"invite_code": invite} if invite else {}
    if terms:
        params["accept_terms"] = 1
    r = c.get("/v1/auth/oauth/google/start", params=params, follow_redirects=False)
    assert r.status_code == 302
    url = urlsplit(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com" and q["code_challenge_method"] == ["S256"] and q["client_id"] == ["google-id"]
    return c.get("/v1/auth/oauth/google/callback", params={"state": state or q["state"][0], "code": code},
                 follow_redirects=False)


def test_google_sign_in(google):
    with TestClient(google) as c:
        assert "google" in c.get("/v1/auth/config").json()["providers"]
        r = google_round(c)                                                      # invite-only: no code
        assert r.status_code == 302 and "error=invite_required" in r.headers["location"]
        code = invite_code(c)
        assert "error=oauth_state" in google_round(c, state="forged-state-" + "x" * 30).headers["location"]
        assert "error=oauth_failed" in google_round(c, code="bad-code", invite=code).headers["location"]
        r = google_round(c, invite=code)
        assert r.status_code == 302 and r.headers["location"].endswith("/app/#/")
        assert c.get("/v1/me").status_code == 200
        me = c.get("/v1/auth/session").json()["user"]
        assert me["email"] == "pia@example.com" and me["email_verified"] and not me["has_password"]
        # the same Google account signs in again without a code
        with browser(google) as b:
            assert google_round(b).headers["location"].endswith("/app/#/")
            assert b.get("/v1/me").status_code == 200
        # a callback this browser did not start is refused (no state cookie)
        with browser(google) as b:
            r = b.get("/v1/auth/oauth/google/start", follow_redirects=False)
            state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
        with browser(google) as other:
            r = other.get("/v1/auth/oauth/google/callback", params={"state": state, "code": "good-code"},
                          follow_redirects=False)
            assert "error=oauth_state" in r.headers["location"] and other.get("/v1/me").status_code == 401


def test_a_new_google_account_needs_the_terms_accepted(google):
    with TestClient(google) as c:
        c.put("/v1/admin/signups", json={"mode": "open"}, headers=admin(c))
        assert "error=terms_required" in google_round(c, terms=False).headers["location"]
        assert c.get("/v1/me").status_code == 401
        assert google_round(c).headers["location"].endswith("/app/#/")
        with browser(google) as b:                      # an existing account signs in without it
            assert google_round(b, terms=False).headers["location"].endswith("/app/#/")


def test_google_unverified_email_and_takeover_of_unconfirmed_signups(google):
    with TestClient(google) as c:
        c.put("/v1/admin/signups", json={"mode": "open"}, headers=admin(c))
        google.state.http.profile = {"sub": "g-2", "email": "nov@example.com", "email_verified": False}
        assert "error=email_not_verified" in google_round(c).headers["location"]
        # someone signed up with Pia's email and their own password but never confirmed it
        c.post("/v1/auth/signup", json={"email": "pia@example.com", "password": "squatter password",
                                         "accept_terms": True})
        google.state.http.profile = {"sub": "g-1", "email": "pia@example.com", "email_verified": True}
        with browser(google) as pia:
            assert google_round(pia).headers["location"].endswith("/app/#/")
        r = c.post("/v1/auth/login", json={"email": "pia@example.com", "password": "squatter password",
                                         "accept_terms": True})
        assert r.status_code == 401                                               # their password was removed


def test_google_respects_two_step_sign_in(google):
    with TestClient(google) as c:
        google_round(c, invite=invite_code(c))
        s = c.get("/v1/auth/session").json()
        secret, _ = enable_mfa(c, s)
    with browser(google) as b:
        r = google_round(b)
        loc = r.headers["location"]
        assert "#/mfa/" in loc and b.get("/v1/me").status_code == 401
        ticket = loc.rsplit("/", 1)[1]
        assert b.post("/v1/auth/mfa", json={"ticket": ticket, "code": totp.code_at(secret, now() + 30)}).status_code == 200


# ---------------------------------------------------------------- captcha, email, cleanup

def test_captcha_on_signup_reset_and_after_failed_sign_ins(settings):
    app = make_app(settings, captcha_provider="turnstile", captcha_secret="cs", signup_mode="open")
    app.state.http = FakeHTTP()
    with TestClient(app) as c:
        assert c.get("/v1/auth/config").json()["captcha"]["provider"] == "turnstile"
        body = {"email": "bot@example.com", "password": PASSWORD, "accept_terms": True}
        assert c.post("/v1/auth/signup", json=body).json()["error"]["code"] == "captcha"
        assert c.post("/v1/auth/signup", json={**body, "captcha": "robot"}).status_code == 400
        assert c.post("/v1/auth/signup", json={**body, "captcha": "human"}).status_code == 202
        assert c.post("/v1/auth/password/forgot", json={"email": "bot@example.com"}).status_code == 400
        # sign-in asks for it only after a few failures from the same address
        bad = {"email": "bot@example.com", "password": "wrong password!"}
        assert [c.post("/v1/auth/login", json=bad).status_code for _ in range(4)] == [401, 401, 401, 400]
        assert c.post("/v1/auth/login", json={**bad, "captcha": "human"}).status_code == 401
        app.state.http.captcha_ok = False                                        # the provider says no / is down
        assert c.post("/v1/auth/signup", json={**body, "captcha": "human"}).status_code == 400


def test_emails_are_sent_from_the_outbox(app):
    with app.state.db.tx() as t:
        mailer.queue(t, "x@example.com", "reset_password", link="https://app/#/reset/abc")
    calls = []

    def flaky(settings, row):
        calls.append(row["id"])
        if len(calls) == 1:
            raise OSError("mail server down")
    assert mailer.send_due(app.state.db, app.state.settings, sender=flaky) == 0
    with app.state.db.tx() as t:
        row = t.one("SELECT * FROM email_outbox")
        assert row["status"] == "pending" and row["attempts"] == 1 and "down" in row["last_error"]
        t.run("UPDATE email_outbox SET next_attempt_at = 0")
    assert mailer.send_due(app.state.db, app.state.settings) == 1               # the outbox folder (development)
    files = list((app.state.settings.data_path / "outbox").glob("*.json"))
    assert len(files) == 1 and "reset/abc" in json.loads(files[0].read_text())["body"]
    with app.state.db.tx() as t:
        row = t.one("SELECT * FROM email_outbox")
        assert row["status"] == "sent" and row["body"] is None                   # the one-time link is not kept


def test_unconfirmed_signups_are_removed(http, app):
    signup(http, "ghost@example.com")
    verified_user(app, http, "real@example.com")
    with app.state.db.tx() as t:
        t.run("UPDATE users SET created_at = ?", (now() - 8 * 86400,))
        assert accounts.cleanup(t) == 1
        assert [r["email"] for r in t.all("SELECT email FROM users")] == ["real@example.com"]


def test_admin_lists_users_and_codes(http, app):
    verified_user(app, http, "listed@example.com")
    users = http.get("/v1/admin/users", params={"q": "listed"}, headers=admin(http)).json()["users"]
    assert len(users) == 1 and users[0]["organisations"][0]["role"] == "owner" and "password_hash" not in users[0]
    code = http.post("/v1/admin/invite-codes", json={"max_uses": 3, "note": "Facebook group"}, headers=admin(http)).json()
    listed = http.get("/v1/admin/invite-codes", headers=admin(http)).json()["invite_codes"]
    assert any(c["id"] == code["id"] and c["note"] == "Facebook group" for c in listed)
    assert http.delete(f"/v1/admin/invite-codes/{code['id']}", headers=admin(http)).status_code == 204
    assert signup(http, "late@example.com", code=code["code"]).status_code == 403
    assert http.get("/v1/admin/users", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_cli_users_invites_and_signups(settings, monkeypatch, capsys):
    from service import cli
    env = {"SERVICE_ENV": "test", "SERVICE_DATABASE_URL": settings.database_url, "SERVICE_DATA_DIR": settings.data_dir,
           "SERVICE_SECRET_KEY": settings.secret_key, "SERVICE_ADMIN_TOKEN": settings.admin_token}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert cli.main(["service-admin", "signups", "closed"]) == 0
    assert "closed" in capsys.readouterr().out
    assert cli.main(["service-admin", "invite-create", "--uses", "2", "--note", "beta testers"]) == 0
    assert re.search(r'"code": "[A-Z2-9]{4}-', capsys.readouterr().out)
    assert cli.main(["service-admin", "user-staff", "nobody@example.com"]) == 1
