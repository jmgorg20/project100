"""Emails (verification, password reset, invitations, notices). They are queued in the database
and sent by the API's background loop (so a slow mail server never slows a request, and an email
about an existing account takes as long to "send" as one about a new account).

SERVICE_EMAIL_BACKEND=smtp sends through SERVICE_SMTP_* (TLS always); `outbox` (development) writes
each email as a JSON file in DATA_DIR/outbox instead. Each email is in English and Taglish.
"""

import json
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import security
from .db import now

RETRY = (60, 300, 1800, 7200, 21600)

TEMPLATES = {
    "verify_email": (
        "Confirm your email · Kumpirmahin ang email mo",
        "Hello,\n\nConfirm your email to finish signing up for AutoEdit:\n{link}\n\nThe link works for 24 hours, "
        "once. If you did not sign up, ignore this email.\n\n---\n\nHello,\n\nI-click ang link para matapos ang "
        "pag-sign up sa AutoEdit:\n{link}\n\nGagana ang link nang 24 oras, isang beses lang. Kung hindi ikaw ang "
        "nag-sign up, huwag pansinin ang email na ito.\n"),
    "already_registered": (
        "You already have an account · May account ka na",
        "Hello,\n\nSomeone (maybe you) tried to sign up with this email, but it already has an AutoEdit account. "
        "Sign in here: {link}\nForgot the password? Use \"Forgot password\" on that page.\n\nIf it was not you, "
        "nothing changed and you can ignore this email.\n\n---\n\nMay nag-sign up gamit ang email na ito pero may "
        "account na ito. Mag-sign in dito: {link}\nNakalimutan ang password? Pindutin ang \"Forgot password\". "
        "Kung hindi ikaw, walang nabago.\n"),
    "reset_password": (
        "Reset your password · I-reset ang password",
        "Hello,\n\nChoose a new password here:\n{link}\n\nThe link works for 1 hour, once. If you did not ask for "
        "this, ignore this email: your password stays the same.\n\n---\n\nPumili ng bagong password dito:\n{link}"
        "\n\nGagana ang link nang 1 oras, isang beses lang. Kung hindi ikaw ang humingi nito, huwag pansinin.\n"),
    "password_changed": (
        "Your password was changed · Napalitan ang password mo",
        "Hello,\n\nThe password of your AutoEdit account was changed and every device was signed out. If this was "
        "not you, reset your password now: {link}\n\n---\n\nNapalitan ang password ng AutoEdit account mo at "
        "na-sign out ang lahat ng device. Kung hindi ikaw, i-reset agad: {link}\n"),
    "org_invite": (
        "You are invited to {org} · Inimbitahan ka sa {org}",
        "Hello,\n\n{inviter} invited you to the organisation \"{org}\" on AutoEdit (role: {role}).\nAccept here: "
        "{link}\n\nThe invitation works for 7 days.\n\n---\n\nInimbitahan ka ni {inviter} sa \"{org}\" sa AutoEdit "
        "(role: {role}).\nTanggapin dito: {link}\n\nGagana ang imbitasyon nang 7 araw.\n"),
    "mfa_changed": (
        "Two-step sign-in {state} · Two-step sign-in {state}",
        "Hello,\n\nTwo-step sign-in was {state} on your AutoEdit account. If this was not you, reset your "
        "password now: {link}\n\n---\n\nAng two-step sign-in ng account mo ay {state}. Kung hindi ikaw, i-reset "
        "agad ang password: {link}\n"),
    "account_deleted": (
        "Your account was deleted · Nabura na ang account mo",
        "Hello,\n\nYour AutoEdit account and its files were deleted, as you asked. Thank you for trying "
        "AutoEdit.\n\n---\n\nNabura na ang AutoEdit account mo at ang mga file nito, gaya ng hiniling mo. "
        "Salamat!\n"),
}


def queue(t, to_addr, template, **values):
    subject, body = TEMPLATES[template]
    t.insert("email_outbox", {"id": security.new_id("em_"), "to_addr": to_addr, "subject": subject.format(**values),
                              "body": body.format(**values), "template": template, "status": "pending",
                              "attempts": 0, "next_attempt_at": now(), "last_error": None, "created_at": now(),
                              "sent_at": None})


def _message(settings, row):
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = row["to_addr"]
    msg["Subject"] = row["subject"]
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=settings.email_from.rsplit("@", 1)[-1].strip("> ") or "localhost")
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(row["body"] or "")
    return msg


def deliver(settings, row):
    """Send one email (raises on failure)."""
    if settings.email_backend == "outbox":
        folder = settings.data_path / "outbox"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{row['id']}.json").write_text(json.dumps({"to": row["to_addr"], "subject": row["subject"],
                                                              "body": row["body"], "template": row["template"]}))
        return
    context = ssl.create_default_context()
    if settings.smtp_tls == "ssl":
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=context)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        server.starttls(context=context)              # never send a password or a link in clear text
    try:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(_message(settings, row))
    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_due(db, settings, limit=20, sender=deliver):
    """Send the queued emails that are due. Returns how many were sent."""
    sent = 0
    with db.tx(immediate=True) as t:
        rows = t.all("SELECT * FROM email_outbox WHERE status = 'pending' AND next_attempt_at <= ? ORDER BY "
                     "next_attempt_at LIMIT ?" + t.for_update, (now(), limit))
        # claim them (another API process skips them while we send)
        for r in rows:
            t.run("UPDATE email_outbox SET next_attempt_at = ? WHERE id = ?", (now() + 300, r["id"]))
    for r in rows:
        try:
            sender(settings, r)
            error = None
        except Exception as exc:                   # the reason is kept, the email retried later
            error = f"{exc.__class__.__name__}: {exc}"[:300]
        with db.tx() as t:
            if error is None:
                t.run("UPDATE email_outbox SET status = 'sent', sent_at = ?, body = NULL, attempts = attempts + 1, "
                      "last_error = NULL WHERE id = ?", (now(), r["id"]))
                sent += 1
            elif r["attempts"] + 1 >= len(RETRY):
                t.run("UPDATE email_outbox SET status = 'failed', body = NULL, attempts = attempts + 1, last_error = ? "
                      "WHERE id = ?", (error, r["id"]))
            else:
                t.run("UPDATE email_outbox SET attempts = attempts + 1, last_error = ?, next_attempt_at = ? WHERE id = ?",
                      (error, now() + RETRY[r["attempts"]], r["id"]))
    with db.tx() as t:
        t.run("DELETE FROM email_outbox WHERE status <> 'pending' AND created_at < ?", (now() - 7 * 86400,))
        t.run("UPDATE email_outbox SET body = NULL, status = 'failed', last_error = 'expired' WHERE status = 'pending' "
              "AND created_at < ?", (now() - 86400,))
    return sent
