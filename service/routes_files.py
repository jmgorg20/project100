"""Signed download links for results: /files/out/<output id>?t=<expiry>.<signature>.

No header needed (so a phone can open the link), but the link expires after
SERVICE_FILE_LINK_MINUTES and only works for that one file. The first download starts the
"delete after download" clock; every download is counted for the egress cost.
"""

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from . import SERVICE_VERSION, clients, security
from .api import ApiError
from .db import now
from .deps import ip_limit, require_admin

router = APIRouter()


@router.get("/files/out/{output_id}")
def download(request: Request, output_id: str, t: str = ""):
    s = request.app.state
    ip_limit(request)
    if not security.check_link(s.settings.secret_key, "out", output_id, t):
        raise ApiError(403, "link_expired", "This link expired or is not valid; ask the API for a new one.")
    with s.db.tx() as tx:
        o = tx.one("SELECT o.*, c.delete_after_download_hours FROM outputs o JOIN clients c ON c.id = o.client_id "
                   "WHERE o.id = ? AND o.deleted_at IS NULL", (output_id,))
        if not o or not o["path"]:
            raise ApiError(410, "gone", "This file was deleted (files are kept only for a few days).")
        if o["first_download_at"] is None:
            later = now() + float(o["delete_after_download_hours"]) * 3600
            tx.run("UPDATE outputs SET first_download_at = ?, expires_at = CASE WHEN expires_at > ? THEN ? ELSE "
                   "expires_at END WHERE id = ?", (now(), later, later, output_id))
        clients.record_usage(tx, o["client_id"], o["job_id"], "egress", egress_bytes=o["size"],
                             cost_usd=clients.estimate_cost(s.settings, egress_bytes=o["size"]))
    ext = {"video/mp4": ".mp4", "application/json": ".json"}.get(o["content_type"], "")
    name = f"{o['job_id']}-{o['name']}{ext if not o['name'].endswith(ext) else ''}"
    return FileResponse(o["path"], media_type=o["content_type"], filename=name,
                        headers={"Cache-Control": "private, max-age=0, no-store"})


@router.get("/healthz")
def healthz():
    return {"ok": True, "version": SERVICE_VERSION}


@router.get("/readyz")
def readyz(request: Request):
    s = request.app.state
    problems = []
    try:
        s.db.ping()
    except Exception as exc:
        problems.append(f"database: {exc.__class__.__name__}")
    try:
        probe = s.storage.tmp_path("ready_probe")
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        problems.append(f"storage: {exc.__class__.__name__}")
    return JSONResponse({"ok": not problems, "problems": problems}, status_code=200 if not problems else 503)


@router.get("/metrics")
def metrics(request: Request):
    """Prometheus text format (admin token needed)."""
    require_admin(request)
    s = request.app.state
    from .jobqueue import queue_stats
    lines = [f"autoedit_requests_total {s.metrics['requests']}", f"autoedit_errors_total {s.metrics['errors']}",
             f"autoedit_uptime_seconds {int(now() - s.started)}"]
    with s.db.tx() as tx:
        for key, statuses in queue_stats(tx).items():
            queue, channel = key.split("/")
            for status, n in statuses.items():
                lines.append(f'autoedit_jobs{{queue="{queue}",channel="{channel}",status="{status}"}} {n}')
        workers = tx.all("SELECT status, last_seen_at FROM workers")
        alive = sum(1 for w in workers if w["status"] == "active" and (w["last_seen_at"] or 0) > now() - 120)
        lines.append(f"autoedit_workers_alive {alive}")
        pending = tx.value("SELECT COUNT(*) FROM webhook_deliveries WHERE status = 'pending'", (), 0)
        lines.append(f"autoedit_webhooks_pending {pending}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
