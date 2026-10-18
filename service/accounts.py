"""Accounts for the web app: users, sign-up (invite codes, the pause switch), email verification,
sign-in (with lockout and two-step codes), sessions, password reset, organisations and their
members and invitations, projects, and the user's own export / delete.

An organisation IS a client (clients.kind = 'organization'): its jobs, uploads, quotas, usage and
webhooks are the same machinery as an API client's, with the same isolation.

Nothing here tells a stranger whether an email has an account: sign-up, password reset and resend
answer the same for every email, and sign-in fails the same way (and as slowly) for a wrong
password and an unknown email.
"""

import re
import secrets

from . import billing, clients, mailer, passwords, ratelimit, security, totp
from .db import dumps, loads, now


class AccountError(Exception):
    def __init__(self, message, status=400, code="invalid", headers=None):
        super().__init__(message)
        self.status, self.code, self.headers = status, code, headers or {}


ROLES = ("owner", "admin", "member")
MANAGERS = ("owner", "admin")
MAX_OWNED_ORGS = 5
VERIFY_HOURS, RESET_MINUTES, MFA_TICKET_MINUTES, INVITE_DAYS = 24, 60, 5, 7
UNVERIFIED_DAYS = 7                 # unconfirmed sign-ups are removed after this (the email is free again)
LOCK_WINDOW = 900                   # sign-in failures are counted per 15 minutes
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                      r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
# Throwaway-mailbox services (trial abuse); add more with SERVICE_BLOCKED_EMAIL_DOMAINS.
DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "sharklasers.com", "10minutemail.com",
    "10minutemail.net", "tempmail.com", "temp-mail.org", "temp-mail.io", "yopmail.com", "yopmail.net",
    "throwawaymail.com", "trashmail.com", "getnada.com", "nada.email", "maildrop.cc", "dispostable.com",
    "fakeinbox.com", "mintemail.com", "mohmal.com", "emailondeck.com", "tempail.com", "moakt.com",
    "mailnesia.com", "spamgourmet.com", "mytemp.email", "tempmailo.com", "tmpmail.org", "tmail.ws",
    "burnermail.io", "inboxkitten.com", "mailpoof.com", "33mail.com", "discard.email", "trashmail.de",
}
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"       # no 0/O, 1/I: easy to type from a message


# ---------------------------------------------------------------- emails

def normalize_email(email, settings=None):
    """(email as stored, canonical form) or AccountError. The canonical form makes one account per
    mailbox: lower case, no +tag, and no dots for Gmail."""
    email = str(email or "").strip()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AccountError("Enter a valid email address.", 422)
    email = email.lower()
    local, domain = email.rsplit("@", 1)
    blocked = DISPOSABLE | {d.lower() for d in (getattr(settings, "blocked_email_domains", None) or [])}
    if domain in blocked or any(domain.endswith("." + d) for d in blocked):
        raise AccountError("Please use your own email address (temporary mailboxes are not accepted).", 422,
                           "email_not_accepted")
    canon_local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        canon_local, domain = canon_local.replace(".", ""), "gmail.com"
    if not canon_local:
        raise AccountError("Enter a valid email address.", 422)
    return email, f"{canon_local}@{domain}"


def _link(settings, route, token):
    return f"{settings.app_link}#/{route}/{token}"


# ---------------------------------------------------------------- one-time tokens

def new_token(t, settings, purpose, user_id, minutes, data=None):
    token = secrets.token_urlsafe(32)
    t.insert("auth_tokens", {"id": security.new_id("at_"), "user_id": user_id, "purpose": purpose,
                             "token_hash": security.hash_token(settings.secret_key, purpose, token),
                             "data": dumps(data), "created_at": now(), "expires_at": now() + minutes * 60,
                             "used_at": None})
    return token


def peek_token(t, settings, purpose, token):
    """The token's row if it is valid (not used, not expired), without using it."""
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        return None
    return t.one("SELECT * FROM auth_tokens WHERE token_hash = ? AND purpose = ? AND used_at IS NULL AND expires_at > ?",
                 (security.hash_token(settings.secret_key, purpose, token), purpose, now()))


def use_token(t, settings, purpose, token, message="This link has expired or was already used."):
    """Use a one-time token (exactly once, even with two requests at the same moment)."""
    row = peek_token(t, settings, purpose, token)
    if not row or not t.run("UPDATE auth_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL", (now(), row["id"])):
        raise AccountError(message, 400, "invalid_token")
    row["data"] = loads(row["data"], {})
    return row


def _drop_tokens(t, user_id, purpose):
    t.run("UPDATE auth_tokens SET used_at = ? WHERE user_id = ? AND purpose = ? AND used_at IS NULL",
          (now(), user_id, purpose))


# ---------------------------------------------------------------- sign-up mode and invite codes

def signup_mode(t, settings):
    row = t.one("SELECT value FROM settings_kv WHERE key = 'signup_mode'")
    return row["value"] if row and row["value"] in ("invite", "open", "closed") else settings.signup_mode


def set_signup_mode(t, mode):
    if mode not in ("invite", "open", "closed"):
        raise AccountError("The sign-up mode is invite, open or closed.")
    if not t.run("UPDATE settings_kv SET value = ?, updated_at = ? WHERE key = 'signup_mode'", (mode, now())):
        t.insert("settings_kv", {"key": "signup_mode", "value": mode, "updated_at": now()})
    return mode


def _normalize_code(code):
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def create_invite_code(t, settings, max_uses=1, days=30, note=None, created_by="admin"):
    max_uses = int(max_uses)
    if not 1 <= max_uses <= 10000:
        raise AccountError("max_uses must be 1 to 10000.")
    raw = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(16))       # 80 bits
    code = "-".join(raw[i:i + 4] for i in range(0, 16, 4))
    cid = security.new_id("ic_")
    t.insert("invite_codes", {"id": cid, "code_hash": security.hash_token(settings.secret_key, "invite", raw),
                              "hint": raw[:4], "note": (str(note)[:200] if note else None), "max_uses": max_uses,
                              "uses": 0, "expires_at": now() + float(days) * 86400 if days else None,
                              "created_by": created_by, "created_at": now(), "revoked_at": None})
    return {"id": cid, "code": code, "max_uses": max_uses, "hint": raw[:4]}


def list_invite_codes(t):
    return t.all("SELECT id, hint, note, max_uses, uses, expires_at, created_by, created_at, revoked_at "
                 "FROM invite_codes ORDER BY created_at DESC")


def revoke_invite_code(t, code_id):
    if not t.run("UPDATE invite_codes SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (now(), code_id)):
        raise AccountError("No such active invite code.", 404, "not_found")


def _invite_code_row(t, settings, code):
    raw = _normalize_code(code)
    if len(raw) != 16:
        return None
    return t.one("SELECT * FROM invite_codes WHERE code_hash = ? AND revoked_at IS NULL AND uses < max_uses AND "
                 "(expires_at IS NULL OR expires_at > ?)", (security.hash_token(settings.secret_key, "invite", raw), now()))


def _take_invite_code(t, settings, code):
    row = _invite_code_row(t, settings, code)
    if not row or not t.run("UPDATE invite_codes SET uses = uses + 1 WHERE id = ? AND uses < max_uses", (row["id"],)):
        raise AccountError("This invite code is not valid (or was used up).", 403, "invite_required")
    return row["id"]


def _check_signup_allowed(t, settings, invite_code):
    mode = signup_mode(t, settings)
    if mode == "closed":
        raise AccountError("New sign-ups are paused for now. Please try again later.", 403, "signups_paused")
    if mode == "invite" and not _invite_code_row(t, settings, invite_code):
        raise AccountError("An invite code is needed to sign up for now (or this one was used up).", 403,
                           "invite_required")
    return mode


# ---------------------------------------------------------------- users

def get_user(t, user_id):
    return t.one("SELECT * FROM users WHERE id = ?", (user_id,))


def public_user(user):
    return {"id": user["id"], "email": user["email"], "name": user["name"], "locale": user["locale"],
            "email_verified": bool(user["email_verified_at"]), "mfa_enabled": bool(user["mfa_enabled_at"]),
            "has_password": bool(user["password_hash"]), "is_admin": bool(user["is_admin"]),
            "created_at": user["created_at"]}


def _clean_name(name):
    name = " ".join(str(name or "").split())
    if len(name) > 80:
        raise AccountError("The name can be at most 80 characters.", 422)
    return name or None


def _locale(value):
    return value if value in ("en", "tl") else None


def signup(t, settings, email, password, name=None, invite_code=None, ip=None, locale=None, device_id=None):
    """Start a sign-up. Always answers the same (no hint whether the email has an account); the
    email says what to do next."""
    email, canon = normalize_email(email, settings)
    passwords.check_policy(password, email)
    name = _clean_name(name)
    mode = _check_signup_allowed(t, settings, invite_code)
    existing = t.one("SELECT * FROM users WHERE email_canonical = ?", (canon,))
    if existing and existing["email_verified_at"]:
        mailer.queue(t, existing["email"], "already_registered", link=settings.app_link + "#/login")
        passwords.burn_time(password)                       # the same time as hashing a new password
        return {"status": "check_email"}
    code_id = _take_invite_code(t, settings, invite_code) if mode == "invite" else None
    pw_hash = passwords.hash_password(password, settings.password_cost)
    if existing:
        # Not confirmed yet: the newest sign-up owns it (the old password and links stop working), so
        # nobody can "reserve" someone else's email with their own password.
        t.update("users", existing["id"], {"password_hash": pw_hash, "password_changed_at": now(), "name": name,
                                           "updated_at": now(), "signup_ip": ip, "locale": _locale(locale)})
        _drop_tokens(t, existing["id"], "verify_email")
        uid = existing["id"]
    else:
        uid = security.new_id("us_")
        t.insert("users", {"id": uid, "email": email, "email_canonical": canon, "name": name, "password_hash": pw_hash,
                           "password_changed_at": now(), "email_verified_at": None, "status": "active", "is_admin": 0,
                           "mfa_secret": None, "mfa_enabled_at": None, "mfa_last_step": None, "locale": _locale(locale),
                           "invite_code_id": code_id, "signup_ip": ip, "created_at": now(), "updated_at": now(),
                           "last_login_at": None})
    token = new_token(t, settings, "verify_email", uid, VERIFY_HOURS * 60,
                      {"device": device_id} if isinstance(device_id, str) and len(device_id) <= 100 else None)
    mailer.queue(t, email, "verify_email", link=_link(settings, "verify", token))
    clients.audit(t, f"user:{uid}", "user.signup", uid, {"invite_code": code_id}, ip)
    return {"status": "check_email"}


def resend_verification(t, settings, email):
    try:
        _, canon = normalize_email(email, settings)
    except AccountError:
        return {"status": "check_email"}
    user = t.one("SELECT * FROM users WHERE email_canonical = ?", (canon,))
    if user and not user["email_verified_at"] and user["status"] == "active":
        _drop_tokens(t, user["id"], "verify_email")
        token = new_token(t, settings, "verify_email", user["id"], VERIFY_HOURS * 60)
        mailer.queue(t, user["email"], "verify_email", link=_link(settings, "verify", token))
    return {"status": "check_email"}


def verify_email(t, settings, token, device_id=None):
    """Confirm the email (the link in the sign-up email). Returns the user, who now has an
    organisation of their own (with the free trial, if this email and device never had one)."""
    row = use_token(t, settings, "verify_email", token)
    user = get_user(t, row["user_id"])
    if not user or user["status"] != "active":
        raise AccountError("This link has expired or was already used.", 400, "invalid_token")
    if not user["email_verified_at"]:
        t.update("users", user["id"], {"email_verified_at": now(), "updated_at": now()})
        clients.audit(t, f"user:{user['id']}", "user.verified", user["id"])
    ensure_personal_org(t, settings, get_user(t, user["id"]), [row["data"].get("device"), device_id])
    return get_user(t, user["id"])


def ensure_personal_org(t, settings, user, device_ids=()):
    """The user's first workspace (it gets the free trial when billing is on)."""
    if t.value("SELECT COUNT(*) FROM memberships WHERE user_id = ?", (user["id"],), 0):
        return None
    label = user["name"] or user["email"].split("@")[0]
    return create_org(t, settings, user, f"{label[:60]}'s workspace", personal=True, device_ids=device_ids)


def update_profile(t, user, changes):
    values = {}
    if "name" in changes:
        values["name"] = _clean_name(changes["name"])
    if "locale" in changes:
        values["locale"] = _locale(changes["locale"])
    unknown = set(changes) - {"name", "locale"}
    if unknown:
        raise AccountError(f"Unknown field(s): {', '.join(sorted(unknown))}", 422)
    if values:
        values["updated_at"] = now()
        t.update("users", user["id"], values)
    return get_user(t, user["id"])


# ---------------------------------------------------------------- sign-in

def _lock_keys(user_or_canon):
    return f"loginfail:{user_or_canon}"


def login(t, settings, email, password, ip=None):
    """The user for this email and password, or AccountError (the same error for an unknown email
    and a wrong password). Too many failures for one account pause its sign-in for 15 minutes."""
    try:
        _, canon = normalize_email(email, settings)
    except AccountError:
        canon = str(email or "").strip().lower()[:254]
    key = _lock_keys(security.hash_token(settings.secret_key, "login", canon))
    if ratelimit.peek(t, key, LOCK_WINDOW) >= settings.login_failures_per_account:
        passwords.burn_time(password)
        raise AccountError("Too many failed sign-ins for this account. Wait 15 minutes or reset your password.",
                           429, "account_paused", {"Retry-After": "900"})
    user = t.one("SELECT * FROM users WHERE email_canonical = ?", (canon,))
    if not user or not user["password_hash"]:
        passwords.burn_time(password)
        ok = False
    else:
        ok = passwords.verify_password(password, user["password_hash"])
    if not ok:
        return None, key
    if user["status"] != "active":
        raise AccountError("This account is disabled. Contact support.", 403, "account_disabled")
    if not user["email_verified_at"]:
        raise AccountError("Confirm your email first (we sent you a link; you can ask for a new one).", 403,
                           "email_not_verified")
    if passwords.needs_rehash(user["password_hash"], settings.password_cost):
        t.update("users", user["id"], {"password_hash": passwords.hash_password(password, settings.password_cost)})
    return user, key


def record_login_failure(t, key, user_hint=None, ip=None):
    ratelimit.hit(t, key, 10 ** 9, window=LOCK_WINDOW)
    clients.audit(t, "anonymous", "login.failed", None, None, ip)


def start_mfa_ticket(t, settings, user, data=None):
    return new_token(t, settings, "mfa_login", user["id"], MFA_TICKET_MINUTES, data or {})


def check_second_factor(t, settings, user, code):
    """True when `code` is a current authenticator code or an unused recovery code (used up now)."""
    code = str(code or "").strip()
    if not user["mfa_secret"]:
        return False
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) == totp.DIGITS and len(code.replace(" ", "")) == totp.DIGITS:
        secret = security.decrypt(settings.secret_key, user["mfa_secret"])
        step = totp.verify(secret, digits, user["mfa_last_step"])
        if step is None:
            return False
        # a code works once: remember its time step (and refuse it if another request just used it)
        return bool(t.run("UPDATE users SET mfa_last_step = ? WHERE id = ? AND (mfa_last_step IS NULL OR mfa_last_step < ?)",
                          (step, user["id"], step)))
    norm = totp.normalize_recovery(code)
    if len(norm) != 10:
        return False
    digest = security.hash_token(settings.secret_key, "recovery", norm)
    row = t.one("SELECT id FROM recovery_codes WHERE user_id = ? AND code_hash = ? AND used_at IS NULL", (user["id"], digest))
    return bool(row and t.run("UPDATE recovery_codes SET used_at = ? WHERE id = ? AND used_at IS NULL", (now(), row["id"])))


def finish_mfa(t, settings, ticket, code):
    """The second step of signing in. Five wrong codes end the ticket."""
    row = peek_token(t, settings, "mfa_login", ticket)
    if not row:
        raise AccountError("Sign in again (this step took too long).", 400, "invalid_token")
    user = get_user(t, row["user_id"])
    if not user or user["status"] != "active":
        raise AccountError("Sign in again.", 400, "invalid_token")
    if not check_second_factor(t, settings, user, code):
        allowed, _ = ratelimit.hit(t, f"mfafail:{row['id']}", 4, window=MFA_TICKET_MINUTES * 60)
        if not allowed:
            t.run("UPDATE auth_tokens SET used_at = ? WHERE id = ?", (now(), row["id"]))
        clients.audit(t, f"user:{user['id']}", "mfa.failed", user["id"])
        return None
    use_token(t, settings, "mfa_login", ticket)
    return user, loads(row["data"], {})


# ---------------------------------------------------------------- sessions

def create_session(t, settings, user, ip=None, user_agent=None, mfa_verified=False, client_id=None):
    full, prefix, digest = security.make_key("ss", settings.secret_key)
    sid = security.new_id("se_")
    if client_id is None:
        client_id = t.value("SELECT client_id FROM memberships WHERE user_id = ? ORDER BY created_at LIMIT 1",
                            (user["id"],))
    t.insert("sessions", {"id": sid, "user_id": user["id"], "prefix": prefix, "token_hash": digest,
                          "csrf_token": secrets.token_urlsafe(24), "client_id": client_id,
                          "mfa_verified": 1 if mfa_verified else 0, "ip": ip, "user_agent": (user_agent or "")[:200],
                          "created_at": now(), "last_seen_at": now(),
                          "expires_at": now() + settings.session_days * 86400, "revoked_at": None})
    t.update("users", user["id"], {"last_login_at": now()})
    clients.audit(t, f"user:{user['id']}", "login", sid, {"mfa": bool(mfa_verified)}, ip)
    return full, t.one("SELECT * FROM sessions WHERE id = ?", (sid,))


def authenticate_session(t, settings, token):
    """(session, user) for a session token, or None (unknown, revoked, expired, idle too long, or the
    user was disabled)."""
    parsed = security.parse_key(token)
    if parsed is None or parsed[0] != "ss":
        return None
    s = t.one("SELECT * FROM sessions WHERE prefix = ?", (parsed[1],))
    if not s or not security.key_matches(token, s["token_hash"], settings.secret_key):
        return None
    if s["revoked_at"] or s["expires_at"] < now() or s["last_seen_at"] < now() - settings.session_idle_days * 86400:
        return None
    user = get_user(t, s["user_id"])
    if not user or user["status"] != "active":
        return None
    if now() - s["last_seen_at"] > 60:
        t.run("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now(), s["id"]))
    return s, user


def list_sessions(t, user_id):
    return t.all("SELECT id, ip, user_agent, created_at, last_seen_at, expires_at, mfa_verified FROM sessions "
                 "WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ? ORDER BY last_seen_at DESC",
                 (user_id, now()))


def revoke_session(t, user_id, session_id):
    if not t.run("UPDATE sessions SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
                 (now(), session_id, user_id)):
        raise AccountError("No such session.", 404, "not_found")


def revoke_all_sessions(t, user_id, except_id=None):
    return t.run("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND id <> ?",
                 (now(), user_id, except_id or ""))


# ---------------------------------------------------------------- passwords

def request_password_reset(t, settings, email):
    try:
        _, canon = normalize_email(email, settings)
    except AccountError:
        return {"status": "check_email"}
    user = t.one("SELECT * FROM users WHERE email_canonical = ?", (canon,))
    if user and user["status"] == "active":
        allowed, _ = ratelimit.hit(t, f"reset:{user['id']}", 3, window=3600)
        if allowed:
            token = new_token(t, settings, "reset_password", user["id"], RESET_MINUTES)
            mailer.queue(t, user["email"], "reset_password", link=_link(settings, "reset", token))
    return {"status": "check_email"}


def reset_password(t, settings, token, new_password, ip=None):
    row = peek_token(t, settings, "reset_password", token)
    if not row:
        raise AccountError("This link has expired or was already used.", 400, "invalid_token")
    user = get_user(t, row["user_id"])
    passwords.check_policy(new_password, user["email"] if user else "")
    use_token(t, settings, "reset_password", token)
    _set_password(t, settings, user, new_password, ip)
    # the link proved the mailbox: the email counts as confirmed
    if not user["email_verified_at"]:
        t.update("users", user["id"], {"email_verified_at": now()})
        ensure_personal_org(t, settings, get_user(t, user["id"]))
    return get_user(t, user["id"])


def change_password(t, settings, user, current, new_password, session_id, ip=None):
    if user["password_hash"] and not passwords.verify_password(current, user["password_hash"]):
        raise AccountError("The current password is wrong.", 403, "bad_password")
    passwords.check_policy(new_password, user["email"])
    _set_password(t, settings, user, new_password, ip, keep_session=session_id)


def _set_password(t, settings, user, new_password, ip, keep_session=None):
    t.update("users", user["id"], {"password_hash": passwords.hash_password(new_password, settings.password_cost),
                                   "password_changed_at": now(), "updated_at": now()})
    _drop_tokens(t, user["id"], "reset_password")
    revoke_all_sessions(t, user["id"], keep_session)
    mailer.queue(t, user["email"], "password_changed", link=settings.app_link + "#/forgot")
    clients.audit(t, f"user:{user['id']}", "password.changed", user["id"], None, ip)


def reauthenticate(t, settings, user, session, password=None, code=None):
    """For dangerous actions (delete the account or an organisation, turn off two-step sign-in): the
    password, or for a Google-only account a sign-in in the last 10 minutes; plus a two-step code
    when that is on."""
    if user["password_hash"]:
        if not passwords.verify_password(password or "", user["password_hash"]):
            raise AccountError("The password is wrong.", 403, "bad_password")
    elif now() - session["created_at"] > 600:
        raise AccountError("Sign in again (with Google) first, then try within 10 minutes.", 403, "reauth_needed")
    if user["mfa_enabled_at"] and not check_second_factor(t, settings, user, code):
        raise AccountError("Enter a code from your authenticator app (or a recovery code).", 403, "mfa_code_needed")


# ---------------------------------------------------------------- two-step sign-in (TOTP)

def mfa_setup(t, settings, user):
    if user["mfa_enabled_at"]:
        raise AccountError("Two-step sign-in is already on.", 409, "conflict")
    secret = totp.new_secret()
    _drop_tokens(t, user["id"], "mfa_setup")
    new_token(t, settings, "mfa_setup", user["id"], 15, {"secret": security.encrypt(settings.secret_key, secret)})
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, user["email"])}


def mfa_enable(t, settings, user, code):
    row = t.one("SELECT * FROM auth_tokens WHERE user_id = ? AND purpose = 'mfa_setup' AND used_at IS NULL AND "
                "expires_at > ? ORDER BY created_at DESC LIMIT 1", (user["id"], now()))
    if not row:
        raise AccountError("Start the setup again (it took too long).", 400, "invalid_token")
    secret = security.decrypt(settings.secret_key, loads(row["data"])["secret"])
    step = totp.verify(secret, code)
    if step is None:
        raise AccountError("That code is not right; check the time on your phone and try the next code.", 422,
                           "bad_code")
    t.run("UPDATE auth_tokens SET used_at = ? WHERE id = ?", (now(), row["id"]))
    t.update("users", user["id"], {"mfa_secret": security.encrypt(settings.secret_key, secret), "mfa_enabled_at": now(),
                                   "mfa_last_step": step, "updated_at": now()})
    codes = _new_recovery_codes(t, settings, user["id"])
    mailer.queue(t, user["email"], "mfa_changed", state="turned on", link=settings.app_link + "#/forgot")
    clients.audit(t, f"user:{user['id']}", "mfa.enabled", user["id"])
    return codes


def _new_recovery_codes(t, settings, user_id):
    t.run("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
    codes = totp.recovery_codes()
    for c in codes:
        t.insert("recovery_codes", {"id": security.new_id("rc_"), "user_id": user_id, "used_at": None,
                                    "code_hash": security.hash_token(settings.secret_key, "recovery",
                                                                     totp.normalize_recovery(c))})
    return codes


def mfa_disable(t, settings, user, session, password=None, code=None):
    if not user["mfa_enabled_at"]:
        raise AccountError("Two-step sign-in is not on.", 409, "conflict")
    if user["is_admin"] and settings.admin_require_mfa:
        raise AccountError("Staff accounts must keep two-step sign-in.", 403, "mfa_required")
    reauthenticate(t, settings, user, session, password, code)
    t.update("users", user["id"], {"mfa_secret": None, "mfa_enabled_at": None, "mfa_last_step": None, "updated_at": now()})
    t.run("DELETE FROM recovery_codes WHERE user_id = ?", (user["id"],))
    mailer.queue(t, user["email"], "mfa_changed", state="turned off", link=settings.app_link + "#/forgot")
    clients.audit(t, f"user:{user['id']}", "mfa.disabled", user["id"])


# ---------------------------------------------------------------- Google (and other OpenID) sign-in

def oauth_login(t, settings, provider, profile, invite_code=None, ip=None, device_id=None):
    """The user for a verified identity from `provider` (profile: sub, email, email_verified, name).
    Links to an account with the same email, or makes a new account (sign-up rules apply)."""
    subject, email = str(profile.get("sub") or ""), profile.get("email")
    if not subject or not email or profile.get("email_verified") is not True:
        raise AccountError("Your Google account's email is not verified, so it cannot be used here.", 403,
                           "email_not_verified")
    ident = t.one("SELECT * FROM user_identities WHERE provider = ? AND subject = ?", (provider, subject))
    if ident:
        user = get_user(t, ident["user_id"])
        if not user or user["status"] != "active":
            raise AccountError("This account is disabled. Contact support.", 403, "account_disabled")
        return user, False
    email, canon = normalize_email(email, settings)
    user = t.one("SELECT * FROM users WHERE email_canonical = ?", (canon,))
    created = False
    if user:
        if user["status"] != "active":
            raise AccountError("This account is disabled. Contact support.", 403, "account_disabled")
        if not user["email_verified_at"]:
            # never confirmed: whoever signed up with this email did not prove the mailbox, Google did.
            # Their password is removed so they cannot share the account.
            t.update("users", user["id"], {"password_hash": None, "email_verified_at": now(), "updated_at": now()})
            _drop_tokens(t, user["id"], "verify_email")
            revoke_all_sessions(t, user["id"])
    else:
        mode = _check_signup_allowed(t, settings, invite_code)
        code_id = _take_invite_code(t, settings, invite_code) if mode == "invite" else None
        uid = security.new_id("us_")
        t.insert("users", {"id": uid, "email": email, "email_canonical": canon, "name": _clean_name(profile.get("name")),
                           "password_hash": None, "password_changed_at": None, "email_verified_at": now(),
                           "status": "active", "is_admin": 0, "mfa_secret": None, "mfa_enabled_at": None,
                           "mfa_last_step": None, "locale": None, "invite_code_id": code_id, "signup_ip": ip,
                           "created_at": now(), "updated_at": now(), "last_login_at": None})
        user = get_user(t, uid)
        created = True
        clients.audit(t, f"user:{uid}", "user.signup", uid, {"provider": provider, "invite_code": code_id}, ip)
    t.insert("user_identities", {"id": security.new_id("id_"), "user_id": user["id"], "provider": provider,
                                 "subject": subject, "email": email, "created_at": now()})
    ensure_personal_org(t, settings, get_user(t, user["id"]), [device_id])
    return get_user(t, user["id"]), created


# ---------------------------------------------------------------- organisations

def create_org(t, settings, user, name, personal=False, device_ids=()):
    owned = t.value("SELECT COUNT(*) FROM memberships WHERE user_id = ? AND role = 'owner'", (user["id"],), 0)
    if owned >= MAX_OWNED_ORGS:
        raise AccountError(f"You can own at most {MAX_OWNED_ORGS} organisations.", 403, "limit")
    try:
        org = clients.create_client(t, settings, name, kind="organization")
    except clients.ClientError as exc:
        raise AccountError(str(exc), 422)
    t.insert("memberships", {"id": security.new_id("mb_"), "client_id": org["id"], "user_id": user["id"],
                             "role": "owner", "created_at": now()})
    clients.audit(t, f"user:{user['id']}", "org.created", org["id"])
    billing.start(t, settings, org, user, personal=personal, device_ids=device_ids)
    return clients.get_client(t, org["id"])


def role_in(t, user_id, client_id):
    return t.value("SELECT role FROM memberships WHERE user_id = ? AND client_id = ?", (user_id, client_id))


def orgs_of(t, user_id):
    return t.all("SELECT c.id, c.name, c.status, m.role FROM memberships m JOIN clients c ON c.id = m.client_id "
                 "WHERE m.user_id = ? ORDER BY m.created_at", (user_id,))


def switch_org(t, session, client_id):
    if not role_in(t, session["user_id"], client_id):
        raise AccountError("You are not a member of that organisation.", 404, "not_found")
    t.run("UPDATE sessions SET client_id = ? WHERE id = ?", (client_id, session["id"]))


def members(t, client_id):
    return t.all("SELECT u.id AS user_id, u.email, u.name, m.role, m.created_at FROM memberships m JOIN users u ON "
                 "u.id = m.user_id WHERE m.client_id = ? ORDER BY m.created_at", (client_id,))


def _owners(t, client_id):
    return t.value("SELECT COUNT(*) FROM memberships WHERE client_id = ? AND role = 'owner'", (client_id,), 0)


def change_role(t, client_id, actor_role, target_user_id, role):
    if role not in ROLES:
        raise AccountError("role must be owner, admin or member.", 422)
    current = role_in(t, target_user_id, client_id)
    if not current:
        raise AccountError("No such member.", 404, "not_found")
    if actor_role != "owner" and ("owner" in (role, current)):
        raise AccountError("Only an owner can make or change owners.", 403, "forbidden")
    if current == "owner" and role != "owner" and _owners(t, client_id) <= 1:
        raise AccountError("An organisation needs at least one owner.", 409, "conflict")
    t.run("UPDATE memberships SET role = ? WHERE client_id = ? AND user_id = ?", (role, client_id, target_user_id))


def remove_member(t, client_id, actor_role, actor_id, target_user_id):
    current = role_in(t, target_user_id, client_id)
    if not current:
        raise AccountError("No such member.", 404, "not_found")
    if target_user_id != actor_id and (actor_role not in MANAGERS or (current == "owner" and actor_role != "owner")):
        raise AccountError("You cannot remove this member.", 403, "forbidden")
    if current == "owner" and _owners(t, client_id) <= 1:
        raise AccountError("An organisation needs at least one owner (delete the organisation instead).", 409,
                           "conflict")
    t.run("DELETE FROM memberships WHERE client_id = ? AND user_id = ?", (client_id, target_user_id))
    t.run("UPDATE sessions SET client_id = NULL WHERE user_id = ? AND client_id = ?", (target_user_id, client_id))


def invite_member(t, settings, org, inviter, email, role="member"):
    if role not in ("admin", "member"):
        raise AccountError("role must be admin or member.", 422)
    email, canon = normalize_email(email, settings)
    if t.value("SELECT COUNT(*) FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.client_id = ? AND "
               "u.email_canonical = ?", (org["id"], canon), 0):
        raise AccountError("This person is already a member.", 409, "conflict")
    if t.value("SELECT COUNT(*) FROM org_invites WHERE client_id = ? AND accepted_at IS NULL AND revoked_at IS NULL "
               "AND expires_at > ?", (org["id"], now()), 0) >= 50:
        raise AccountError("Too many open invitations; revoke some first.", 429, "limit")
    token = secrets.token_urlsafe(32)
    iid = security.new_id("oi_")
    t.insert("org_invites", {"id": iid, "client_id": org["id"], "email": email, "email_canonical": canon, "role": role,
                             "token_hash": security.hash_token(settings.secret_key, "org_invite", token),
                             "invited_by": inviter["id"], "created_at": now(),
                             "expires_at": now() + INVITE_DAYS * 86400, "accepted_at": None, "revoked_at": None})
    mailer.queue(t, email, "org_invite", org=org["name"], inviter=inviter["name"] or inviter["email"], role=role,
                 link=_link(settings, "invite", token))
    return {"id": iid, "email": email, "role": role}


def list_invites(t, client_id):
    return t.all("SELECT id, email, role, created_at, expires_at, accepted_at, revoked_at FROM org_invites WHERE "
                 "client_id = ? ORDER BY created_at DESC", (client_id,))


def revoke_invite(t, client_id, invite_id):
    if not t.run("UPDATE org_invites SET revoked_at = ? WHERE id = ? AND client_id = ? AND accepted_at IS NULL AND "
                 "revoked_at IS NULL", (now(), invite_id, client_id)):
        raise AccountError("No such open invitation.", 404, "not_found")


def accept_invite(t, settings, user, token):
    """Join the organisation. The invitation is for one email: it works only for that person."""
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        raise AccountError("This invitation has expired or was already used.", 400, "invalid_token")
    row = t.one("SELECT * FROM org_invites WHERE token_hash = ? AND accepted_at IS NULL AND revoked_at IS NULL AND "
                "expires_at > ?", (security.hash_token(settings.secret_key, "org_invite", token), now()))
    if not row:
        raise AccountError("This invitation has expired or was already used.", 400, "invalid_token")
    if row["email_canonical"] != user["email_canonical"]:
        raise AccountError(f"This invitation is for another email address. Sign in as {row['email']}.", 403,
                           "wrong_account")
    if not t.run("UPDATE org_invites SET accepted_at = ? WHERE id = ? AND accepted_at IS NULL", (now(), row["id"])):
        raise AccountError("This invitation was already used.", 400, "invalid_token")
    if not role_in(t, user["id"], row["client_id"]):
        t.insert("memberships", {"id": security.new_id("mb_"), "client_id": row["client_id"], "user_id": user["id"],
                                 "role": row["role"], "created_at": now()})
    clients.audit(t, f"user:{user['id']}", "org.joined", row["client_id"], {"role": row["role"]})
    return clients.get_client(t, row["client_id"])


def delete_org(t, storage, client_id):
    """Delete an organisation with all its files and records."""
    clients.delete_client_files(t, storage, client_id)
    t.run("UPDATE sessions SET client_id = NULL WHERE client_id = ?", (client_id,))
    t.run("DELETE FROM clients WHERE id = ?", (client_id,))


# ---------------------------------------------------------------- projects

def _project_name(name):
    name = " ".join(str(name or "").split())
    if not name or len(name) > 100:
        raise AccountError("A project needs a name (up to 100 characters).", 422)
    return name


def create_project(t, client_id, name, user_id=None):
    if t.value("SELECT COUNT(*) FROM projects WHERE client_id = ?", (client_id,), 0) >= 500:
        raise AccountError("At most 500 projects; delete some first.", 429, "limit")
    pid = security.new_id("pj_")
    t.insert("projects", {"id": pid, "client_id": client_id, "name": _project_name(name), "created_by": user_id,
                          "created_at": now(), "updated_at": now()})
    return t.one("SELECT * FROM projects WHERE id = ?", (pid,))


def get_project(t, client_id, project_id):
    row = t.one("SELECT * FROM projects WHERE id = ? AND client_id = ?", (project_id, client_id))
    if not row:
        raise AccountError("No such project.", 404, "not_found")
    return row


def list_projects(t, client_id):
    return t.all("SELECT p.*, (SELECT COUNT(*) FROM jobs j WHERE j.client_id = p.client_id AND j.project_id = p.id AND "
                 "j.deleted_at IS NULL) AS jobs FROM projects p WHERE p.client_id = ? ORDER BY p.created_at DESC",
                 (client_id,))


def rename_project(t, client_id, project_id, name):
    get_project(t, client_id, project_id)
    t.run("UPDATE projects SET name = ?, updated_at = ? WHERE id = ? AND client_id = ?",
          (_project_name(name), now(), project_id, client_id))
    return get_project(t, client_id, project_id)


def delete_project(t, client_id, project_id):
    """The project goes; its jobs and files stay (no longer in a project)."""
    get_project(t, client_id, project_id)
    t.run("UPDATE jobs SET project_id = NULL WHERE client_id = ? AND project_id = ?", (client_id, project_id))
    t.run("UPDATE uploads SET project_id = NULL WHERE client_id = ? AND project_id = ?", (client_id, project_id))
    t.run("DELETE FROM projects WHERE id = ? AND client_id = ?", (project_id, client_id))


# ---------------------------------------------------------------- the user's own data

def export_account(t, user):
    """Everything kept about the user (not the files themselves: those are downloaded from the jobs)."""
    orgs = orgs_of(t, user["id"])
    out = {"user": public_user(user), "signup_ip": user["signup_ip"], "last_login_at": user["last_login_at"],
           "identities": t.all("SELECT provider, email, created_at FROM user_identities WHERE user_id = ?", (user["id"],)),
           "sessions": list_sessions(t, user["id"]), "organisations": [], "exported_at": now()}
    for o in orgs:
        entry = {"id": o["id"], "name": o["name"], "role": o["role"]}
        if o["role"] in MANAGERS:
            entry["projects"] = t.all("SELECT id, name, created_at FROM projects WHERE client_id = ?", (o["id"],))
            entry["jobs"] = t.all("SELECT id, kind, status, project_id, input_minutes, created_at, finished_at FROM jobs "
                                  "WHERE client_id = ? AND deleted_at IS NULL ORDER BY created_at", (o["id"],))
            entry["usage"] = clients.usage_this_month(t, o["id"])
        else:
            entry["jobs"] = t.all("SELECT id, kind, status, project_id, input_minutes, created_at, finished_at FROM jobs "
                                  "WHERE client_id = ? AND user_id = ? AND deleted_at IS NULL ORDER BY created_at",
                                  (o["id"], user["id"]))
        out["organisations"].append(entry)
    out["audit"] = t.all("SELECT at, action, target, ip FROM audit_log WHERE actor = ? ORDER BY at DESC LIMIT 500",
                         (f"user:{user['id']}",))
    return out


def delete_account(t, settings, storage, user):
    """Delete the user. Organisations where they are the only owner are deleted with all their files;
    in the others they are removed as a member (what they made there stays, without their name)."""
    deleted_orgs = []
    for o in orgs_of(t, user["id"]):
        if o["role"] == "owner" and _owners(t, o["id"]) <= 1:
            delete_org(t, storage, o["id"])
            deleted_orgs.append(o["id"])
    t.run("UPDATE jobs SET user_id = NULL WHERE user_id = ?", (user["id"],))
    t.run("UPDATE uploads SET user_id = NULL WHERE user_id = ?", (user["id"],))
    t.run("UPDATE projects SET created_by = NULL WHERE created_by = ?", (user["id"],))
    t.run("UPDATE org_invites SET invited_by = NULL WHERE invited_by = ?", (user["id"],))
    t.run("DELETE FROM users WHERE id = ?", (user["id"],))
    mailer.queue(t, user["email"], "account_deleted")
    clients.audit(t, f"user:{user['id']}", "user.deleted", user["id"], {"organisations_deleted": deleted_orgs})
    return {"deleted_organisations": deleted_orgs}


def cleanup(t):
    """Housekeeping: unconfirmed sign-ups after UNVERIFIED_DAYS, old tokens and sessions."""
    gone = t.run("DELETE FROM users WHERE email_verified_at IS NULL AND created_at < ? AND id NOT IN "
                 "(SELECT user_id FROM memberships)", (now() - UNVERIFIED_DAYS * 86400,))
    t.run("DELETE FROM auth_tokens WHERE expires_at < ?", (now() - 86400,))
    t.run("DELETE FROM sessions WHERE expires_at < ? OR (revoked_at IS NOT NULL AND revoked_at < ?)",
          (now() - 86400, now() - 30 * 86400))
    return gone
