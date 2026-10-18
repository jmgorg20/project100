"""Webhooks: each client registers its own URLs and gets signed POSTs when its jobs change.

Events: job.queued, job.started, job.succeeded, job.failed, job.cancelled, upload.ready,
upload.rejected, files.expiring. A delivery is retried with a growing wait (up to
SERVICE_WEBHOOK_ATTEMPTS times). Every body is signed (see security.webhook_signature).

SSRF protection: the target's address is checked right before each send (after DNS): loopback,
private, link-local, multicast and reserved addresses are refused (unless
SERVICE_ALLOW_PRIVATE_WEBHOOKS in development), redirects are not followed, and the connection
goes to the address that was checked (no second DNS lookup an attacker could change).
"""

import http.client
import ipaddress
import secrets
import socket
import ssl
from urllib.parse import urlparse

from . import security
from .db import dumps, loads, now

EVENTS = ("job.queued", "job.started", "job.succeeded", "job.failed", "job.cancelled", "upload.ready",
          "upload.rejected", "files.expiring")
RETRY_WAITS = (10, 30, 120, 600, 1800, 3600, 7200, 14400)
MAX_PER_CLIENT = 10


class WebhookError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def check_url(url, settings):
    p = urlparse(str(url or ""))
    if p.scheme not in ("https", "http") or not p.hostname:
        raise WebhookError("The webhook URL must be an https:// address.")
    if p.scheme != "https" and not settings.allow_private_webhooks:
        raise WebhookError("The webhook URL must use https://.")
    if p.username or p.password:
        raise WebhookError("The webhook URL must not contain a user name or password.")
    if len(url) > 2000:
        raise WebhookError("The webhook URL is too long.")
    return url


def address_allowed(ip, settings):
    addr = ipaddress.ip_address(ip)
    if settings.allow_private_webhooks:
        return True
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved
                or addr.is_unspecified or (addr.version == 6 and addr.ipv4_mapped is not None
                                           and not address_allowed(str(addr.ipv4_mapped), settings)))


def resolve_safe(host, port, settings):
    """The first address of `host` that is allowed; raises WebhookError if none is."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise WebhookError("The webhook host could not be found.")
    for family, _, _, _, sockaddr in infos:
        if address_allowed(sockaddr[0], settings):
            return sockaddr[0]
    raise WebhookError("The webhook address is a private or local address; it is not allowed.")


def register(t, settings, client_id, url, events=None):
    check_url(url, settings)
    events = list(events or ["*"])
    bad = [e for e in events if e != "*" and e not in EVENTS]
    if bad:
        raise WebhookError(f"Unknown event(s): {', '.join(bad)}. Events: {', '.join(EVENTS)}")
    if int(t.value("SELECT COUNT(*) FROM webhooks WHERE client_id = ?", (client_id,), 0)) >= MAX_PER_CLIENT:
        raise WebhookError(f"At most {MAX_PER_CLIENT} webhooks per client.")
    secret = "whsec_" + secrets.token_urlsafe(32)
    wid = security.new_id("wh_")
    t.insert("webhooks", {"id": wid, "client_id": client_id, "url": url, "secret": security.encrypt(settings.secret_key, secret),
                          "events": dumps(events), "active": 1, "created_at": now()})
    return {"id": wid, "url": url, "events": events, "secret": secret}


def list_for(t, client_id):
    rows = t.all("SELECT id, url, events, active, created_at FROM webhooks WHERE client_id = ? ORDER BY created_at",
                 (client_id,))
    for r in rows:
        r["events"] = loads(r["events"], [])
        r["active"] = bool(r["active"])
    return rows


def delete(t, client_id, webhook_id):
    if not t.run("DELETE FROM webhooks WHERE id = ? AND client_id = ?", (webhook_id, client_id)):
        raise WebhookError("No such webhook.", 404)


def emit(t, client_id, event, data):
    """Queue a delivery to each of the client's webhooks that wants this event."""
    body = {"id": security.new_id("evt_"), "event": event, "created_at": now(), "data": data}
    n = 0
    for hook in t.all("SELECT id, events FROM webhooks WHERE client_id = ? AND active = 1", (client_id,)):
        wanted = loads(hook["events"], [])
        if "*" in wanted or event in wanted:
            t.insert("webhook_deliveries", {"id": security.new_id("whd_"), "webhook_id": hook["id"],
                                            "client_id": client_id, "event": event, "payload": dumps(body),
                                            "status": "pending", "attempts": 0, "next_attempt_at": now(),
                                            "last_status": None, "last_error": None, "created_at": now(),
                                            "delivered_at": None})
            n += 1
    return n


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to an address that was already checked, verifying the certificate for the real host."""

    def __init__(self, ip, port, hostname, timeout):
        super().__init__(ip, port, timeout=timeout, context=ssl.create_default_context())
        self._ip, self._hostname = ip, hostname

    def connect(self):
        raw = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self._hostname)


def send(url, body, signature, settings, timeout=10):
    """POST to `url` at a checked address (no redirects followed). Returns the HTTP status code."""
    p = urlparse(url)
    port = p.port or (443 if p.scheme == "https" else 80)
    ip = resolve_safe(p.hostname, port, settings)
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    headers = {"Content-Type": "application/json", "User-Agent": "AutoEditService-Webhooks/1",
               "X-AutoEdit-Signature": signature, "Host": p.netloc}
    if p.scheme == "https":
        conn = _PinnedHTTPS(ip, port, p.hostname, timeout)
    else:
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        resp.read(65536)
        return resp.status
    finally:
        conn.close()


def deliver_due(db, settings, limit=20, sender=None):
    """Send the deliveries that are due. Returns how many were sent successfully."""
    sender = sender or send
    with db.tx(immediate=True) as t:
        due = t.all("SELECT d.*, w.url, w.secret FROM webhook_deliveries d JOIN webhooks w ON w.id = d.webhook_id "
                    "WHERE d.status = 'pending' AND d.next_attempt_at <= ? ORDER BY d.next_attempt_at LIMIT ?"
                    + t.for_update.replace(" FOR UPDATE", " FOR UPDATE OF d"), (now(), limit))
        for d in due:          # take them, so a second sender does not send them too
            t.run("UPDATE webhook_deliveries SET next_attempt_at = ? WHERE id = ?", (now() + 300, d["id"]))
    ok = 0
    for d in due:
        body = d["payload"].encode()
        status, error = None, None
        try:
            secret = security.decrypt(settings.secret_key, d["secret"])
            status = sender(d["url"], body, security.webhook_signature(secret, body), settings)
        except Exception as exc:          # network errors, refused addresses: retried later
            error = str(exc)[:500]
        attempts = d["attempts"] + 1
        with db.tx() as t:
            if status is not None and 200 <= status < 300:
                t.run("UPDATE webhook_deliveries SET status = 'delivered', attempts = ?, last_status = ?, delivered_at = ?, "
                      "last_error = NULL WHERE id = ?", (attempts, status, now(), d["id"]))
                ok += 1
            elif attempts >= settings.webhook_attempts:
                t.run("UPDATE webhook_deliveries SET status = 'failed', attempts = ?, last_status = ?, last_error = ? "
                      "WHERE id = ?", (attempts, status, error or f"HTTP {status}", d["id"]))
            else:
                wait = RETRY_WAITS[min(attempts - 1, len(RETRY_WAITS) - 1)]
                t.run("UPDATE webhook_deliveries SET attempts = ?, last_status = ?, last_error = ?, next_attempt_at = ? "
                      "WHERE id = ?", (attempts, status, error or f"HTTP {status}", now() + wait, d["id"]))
    return ok


def payload_for_job(job):
    result = loads(job.get("result"), None) or {}
    return {"job_id": job["id"], "status": job["status"], "kind": job["kind"], "error": job.get("error"),
            "result_status": result.get("status"), "qc_failed": (result.get("qc") or {}).get("failed")}

