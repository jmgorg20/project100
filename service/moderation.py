"""Abuse reports and what the staff do about them.

Anyone who has a link to a result can report it (the public form at /app/report.html, or
POST /v1/public/report with the link): the report names the file, a reason and optional details.
A report about child safety, or several reports about the same file from different addresses,
holds the file at once (downloads are refused) until a person looks at it. The staff then:

    dismiss   nothing wrong: the file is released again
    remove    the job's files are deleted now (the report and the audit log keep the record)
    suspend   the files are deleted and the workspace / client is suspended (no sign-in to it, no API)

Uploads can also be checked when they arrive (SERVICE_MODERATION_COMMAND, media.moderate); a file
the check refuses is never stored.
"""

from urllib.parse import parse_qs, urlsplit

from . import clients, security
from .db import now

REASONS = ("copyright", "child_safety", "violence", "hate", "harassment", "privacy", "illegal", "spam", "other")
ACTIONS = {"dismiss": "dismissed", "remove": "removed", "suspend": "suspended"}
HOLD_NOW = ("child_safety",)
HOLD_AFTER = 3                      # reports from different addresses about one file
MAX_DETAILS = 2000


class ReportError(Exception):
    def __init__(self, message, status=422, code="invalid"):
        super().__init__(message)
        self.status, self.code = status, code


def output_from_link(settings, link):
    """The output id of a result link (/files/out/<id>?t=...) when its signature is ours. An expired
    link still counts: it proves the person was given it."""
    try:
        parts = urlsplit(str(link or "").strip())
    except ValueError:
        return None
    segs = parts.path.rstrip("/").split("/")
    if len(segs) < 2 or segs[-2] != "out":
        return None
    output_id, token = segs[-1], (parse_qs(parts.query).get("t") or [""])[0]
    return output_id if security.check_link(settings.secret_key, "out", output_id, token, now=0) else None


def _clean(reason, details, email):
    if reason not in REASONS:
        raise ReportError(f"reason must be one of {', '.join(REASONS)}")
    if details is not None and not isinstance(details, str):
        raise ReportError("details must be text")
    details = (details or "").strip()[:MAX_DETAILS] or None
    if email is not None:
        if not isinstance(email, str) or len(email) > 254 or "@" not in email or any(c.isspace() for c in email.strip()):
            raise ReportError("Please give a valid email address (or none).")
        email = email.strip().lower() or None
    return details, email


def report(t, settings, output_id, reason, details=None, reporter="public", email=None, ip=None):
    """Record a report about a result. Returns {"id", "held"}."""
    details, email = _clean(reason, details, email)
    o = t.one("SELECT id, job_id, client_id, held_at, deleted_at FROM outputs WHERE id = ?", (output_id,))
    if not o:
        raise ReportError("That file is not known (it may have been deleted already).", 404, "not_found")
    rid = security.new_id("rep_")
    t.insert("reports", {"id": rid, "client_id": o["client_id"], "job_id": o["job_id"], "output_id": o["id"],
                         "reason": reason, "details": details, "reporter": reporter, "reporter_email": email, "ip": ip,
                         "status": "open", "resolution": None, "resolved_by": None, "created_at": now(),
                         "resolved_at": None})
    others = t.value("SELECT COUNT(DISTINCT ip) FROM reports WHERE output_id = ? AND status = 'open'", (o["id"],), 0)
    held = bool(o["held_at"])
    if not held and o["deleted_at"] is None and (reason in HOLD_NOW or others >= HOLD_AFTER):
        t.run("UPDATE outputs SET held_at = ? WHERE job_id = ? AND held_at IS NULL", (now(), o["job_id"]))
        held = True
    clients.audit(t, reporter, "report.created", rid, {"output_id": o["id"], "reason": reason, "held": held}, ip)
    return {"id": rid, "held": held}


def list_reports(t, status="open", limit=100):
    sql = ("SELECT r.*, c.name AS client_name, c.status AS client_status, o.held_at, o.deleted_at AS output_deleted_at "
           "FROM reports r LEFT JOIN clients c ON c.id = r.client_id LEFT JOIN outputs o ON o.id = r.output_id")
    params = []
    if status:
        sql += " WHERE r.status = ?"
        params.append(status)
    sql += " ORDER BY r.created_at DESC LIMIT ?"
    params.append(max(1, min(500, int(limit))))
    return t.all(sql, params)


def resolve(t, storage, report_id, action, by, note=None, ip=None):
    """Close a report (and the other open reports about the same job) with dismiss | remove | suspend."""
    if action not in ACTIONS:
        raise ReportError(f"action must be one of {', '.join(ACTIONS)}")
    if note is not None and not isinstance(note, str):
        raise ReportError("note must be text")
    r = t.one("SELECT * FROM reports WHERE id = ?", (report_id,))
    if not r:
        raise ReportError("No such report.", 404, "not_found")
    if r["status"] != "open":
        raise ReportError("This report was already handled.", 409, "conflict")
    job = t.one("SELECT * FROM jobs WHERE id = ?", (r["job_id"],)) if r["job_id"] else None
    if action == "dismiss":
        if job:
            t.run("UPDATE outputs SET held_at = NULL WHERE job_id = ?", (job["id"],))
    else:
        if job:
            clients.delete_job_files(t, storage, job)
        if action == "suspend" and r["client_id"] and clients.get_client(t, r["client_id"]):
            clients.update_client(t, r["client_id"], {"status": "suspended"})      # its keys and sign-ins stop
    status = ACTIONS[action]
    same = "job_id = ?" if r["job_id"] else "id = ?"
    t.run(f"UPDATE reports SET status = ?, resolution = ?, resolved_by = ?, resolved_at = ? WHERE status = 'open' AND "
          f"{same}", (status, (note or "").strip()[:MAX_DETAILS] or None, by, now(), r["job_id"] or r["id"]))
    clients.audit(t, by, f"report.{status}", report_id, {"job_id": r["job_id"], "client_id": r["client_id"],
                                                         "note": note}, ip)
    return t.one("SELECT * FROM reports WHERE id = ?", (report_id,))
