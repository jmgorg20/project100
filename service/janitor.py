"""Housekeeping, run every minute by the API process (or `service-admin janitor` from a scheduler):

- jobs whose worker went quiet or that ran too long go back to the queue (jobqueue.reap);
- uploads and results past their expiry are deleted from disk and marked deleted (cloud storage is
  temporary: SERVICE_RETENTION_DAYS, and results also SERVICE_DELETE_AFTER_DOWNLOAD_HOURS after the
  first download); a "files.expiring" webhook goes out about a day before;
- unfinished uploads older than a day are removed;
- old rate counters are dropped;
- unconfirmed sign-ups (after 7 days), old one-time tokens and ended sessions are removed;
- billing: trial reminders, and the end of trials, grace periods and canceled plans.
"""

from . import accounts, billing, jobqueue, ratelimit, webhooks
from .clients import audit
from .db import now


def expire_files(db, storage, warn_hours=24):
    removed = {"uploads": 0, "outputs": 0}
    with db.tx() as t:
        uploads = t.all("SELECT id, client_id, path FROM uploads WHERE status IN ('uploading', 'ready', 'rejected') "
                        "AND (expires_at < ? OR (status = 'uploading' AND updated_at < ?))", (now(), now() - 86400))
        outputs = t.all("SELECT id, job_id, client_id, path FROM outputs WHERE deleted_at IS NULL AND expires_at < ?",
                        (now(),))
    for u in uploads:
        storage.delete(storage.upload_path(u["id"]))
        with db.tx() as t:
            t.run("UPDATE uploads SET status = 'deleted', deleted_at = ?, path = NULL WHERE id = ?", (now(), u["id"]))
        removed["uploads"] += 1
    for o in outputs:
        storage.delete(o["path"])
        with db.tx() as t:
            t.run("UPDATE outputs SET deleted_at = ?, path = NULL WHERE id = ?", (now(), o["id"]))
        removed["outputs"] += 1
    with db.tx() as t:
        # warn once, about a day before results disappear
        soon = t.all("SELECT o.job_id, o.client_id, MIN(o.expires_at) AS expires_at FROM outputs o JOIN jobs j ON "
                     "j.id = o.job_id WHERE o.deleted_at IS NULL AND o.expires_at < ? AND j.expiry_warned = 0 "
                     "GROUP BY o.job_id, o.client_id", (now() + warn_hours * 3600,))
        for s in soon:
            webhooks.emit(t, s["client_id"], "files.expiring", {"job_id": s["job_id"], "expires_at": s["expires_at"]})
            t.run("UPDATE jobs SET expiry_warned = 1 WHERE id = ?", (s["job_id"],))
        if removed["uploads"] or removed["outputs"]:
            audit(t, "system", "files.expired", details=removed)
    return removed


def run_once(db, storage, settings):
    reaped = jobqueue.reap(db)
    files = expire_files(db, storage)
    with db.tx() as t:
        ratelimit.cleanup(t)
        accounts.cleanup(t)
        billing_done = billing.tick(t, settings)
        for job_id in reaped:
            job = t.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
            if job and job["status"] in ("failed", "cancelled"):
                webhooks.emit(t, job["client_id"], f"job.{job['status']}", webhooks.payload_for_job(job))
    return {"reaped": reaped, **files, "billing": billing_done}
