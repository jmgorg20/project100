"""The durable job queue (in the database, so nothing is lost when the service restarts).

    queued --claim--> running --complete--> succeeded / failed
       ^                 |  (heartbeat extends the lease; a cancel request is answered on the next one)
       +--- retry -------+  fail (retryable) / lease expired (worker gone) / time limit
                                 (with a growing wait; after max_attempts: failed)

Workers pull jobs (outbound HTTPS from the worker; no inbound ports). A worker gets only jobs of its
queues (cpu / gpu) and its channel (stable / beta); a stable worker gets jobs only when it runs the
promoted engine version. A client never has more jobs running than its concurrent_jobs.
"""

import time

from . import security
from .db import dumps, loads, now

QUEUES = ("cpu", "gpu")
FINAL = ("succeeded", "failed", "cancelled")
BACKOFF = (30, 120, 600, 1800)


class QueueError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- settings, releases, flags

def get_setting(t, key, default=None):
    row = t.one("SELECT value FROM settings_kv WHERE key = ?", (key,))
    return loads(row["value"], default) if row else default


def set_setting(t, key, value):
    t.run("INSERT INTO settings_kv (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT (key) DO UPDATE SET "
          "value = excluded.value, updated_at = excluded.updated_at", (key, dumps(value), now()))


def flags_for(t, channel):
    rows = t.all("SELECT name, stable, beta FROM flags ORDER BY name")
    return sorted(r["name"] for r in rows if r["beta" if channel == "beta" else "stable"])


def set_flag(t, name, stable=None, beta=None, description=None):
    row = t.one("SELECT * FROM flags WHERE name = ?", (name,))
    if row is None:
        t.insert("flags", {"name": name, "stable": int(bool(stable)), "beta": int(beta if beta is not None else 1),
                           "description": description, "updated_at": now()})
    else:
        t.run("UPDATE flags SET stable = ?, beta = ?, description = ?, updated_at = ? WHERE name = ?",
              (int(bool(row["stable"] if stable is None else stable)), int(bool(row["beta"] if beta is None else beta)),
               description if description is not None else row["description"], now(), name))
    return t.one("SELECT * FROM flags WHERE name = ?", (name,))


def register_release(t, version, tests_passed, report=None):
    t.run("INSERT INTO releases (version, tests_passed, report, registered_at) VALUES (?, ?, ?, ?) ON CONFLICT "
          "(version) DO UPDATE SET tests_passed = excluded.tests_passed, report = excluded.report",
          (version, int(bool(tests_passed)), dumps(report), now()))


def promote(t, version):
    """Make `version` the stable engine version. Only a release whose tests passed can be promoted."""
    rel = t.one("SELECT * FROM releases WHERE version = ?", (version,))
    if not rel:
        raise QueueError(f"Version {version} is not registered (register it with its test report first).", 404)
    if not rel["tests_passed"]:
        raise QueueError(f"Version {version} did not pass its tests; it cannot be promoted.", 409)
    history = get_setting(t, "stable_history", [])
    current = get_setting(t, "stable_version")
    if current == version:
        return current
    if current:
        history.append(current)
    set_setting(t, "stable_history", history[-20:])
    set_setting(t, "stable_version", version)
    t.run("UPDATE releases SET promoted_at = ? WHERE version = ?", (now(), version))
    return version


def rollback(t):
    """Go back to the previously promoted stable version."""
    history = get_setting(t, "stable_history", [])
    if not history:
        raise QueueError("There is no earlier stable version to go back to.", 409)
    previous = history.pop()
    set_setting(t, "stable_history", history)
    set_setting(t, "stable_version", previous)
    return previous


# ---------------------------------------------------------------- workers

def create_worker(t, settings, name, queues, channel="stable"):
    queues = [q for q in queues if q in QUEUES]
    if not queues:
        raise QueueError("A worker needs at least one queue: cpu and/or gpu.")
    if channel not in ("stable", "beta"):
        raise QueueError("channel must be stable or beta")
    full, prefix, digest = security.make_key("wk", settings.secret_key)
    wid = security.new_id("wk_")
    t.insert("workers", {"id": wid, "name": str(name)[:100], "token_prefix": prefix, "token_hash": digest,
                         "queues": dumps(queues), "channel": channel, "status": "active", "engine_version": None,
                         "info": None, "created_at": now(), "last_seen_at": None, "revoked_at": None})
    return {"id": wid, "token": full, "queues": queues, "channel": channel}


def revoke_worker(t, worker_id):
    """Revoke a worker's token; its running jobs go back to the queue at once."""
    if not t.run("UPDATE workers SET status = 'revoked', revoked_at = ? WHERE id = ? AND status = 'active'",
                 (now(), worker_id)):
        raise QueueError("No such active worker.", 404)
    for job in t.all("SELECT * FROM jobs WHERE worker_id = ? AND status = 'running'", (worker_id,)):
        _retry_or_fail(t, job, "The worker was revoked.", retryable=True)


def authenticate_worker(t, settings, token):
    parsed = security.parse_key(token)
    if parsed is None or parsed[0] != "wk":
        return None
    row = t.one("SELECT * FROM workers WHERE token_prefix = ?", (parsed[1],))
    if not row or row["status"] != "active" or not security.key_matches(token, row["token_hash"], settings.secret_key):
        return None
    row["queues"] = loads(row["queues"], [])
    return row


# ---------------------------------------------------------------- jobs

def add_event(t, job_id, kind, data=None):
    t.insert("job_events", {"id": security.new_id("ev_"), "job_id": job_id, "seq": time.time_ns() // 1000,
                            "kind": kind, "data": dumps(data), "at": now()})


def enqueue(t, settings, client, kind, params, inputs, queue="cpu", priority=100, input_minutes=0.0,
            idempotency_key=None):
    if queue not in QUEUES:
        raise QueueError("unknown queue")
    if idempotency_key:
        old = t.one("SELECT * FROM jobs WHERE client_id = ? AND idempotency_key = ?", (client["id"], idempotency_key))
        if old:
            return old, False
    waiting = t.value("SELECT COUNT(*) FROM jobs WHERE client_id = ? AND status = 'queued'", (client["id"],), 0)
    if waiting >= settings.max_queued_jobs:          # one client's backlog must not hold up everyone else
        raise QueueError(f"{waiting} jobs are already waiting; send more when some have started.", 429)
    jid = security.new_id("job_")
    row = {"id": jid, "client_id": client["id"], "kind": kind, "queue": queue, "channel": client["channel"],
           "status": "queued", "priority": int(priority), "params": dumps(params), "inputs": dumps(inputs),
           "attempts": 0, "max_attempts": settings.max_attempts, "timeout_seconds": settings.job_timeout_minutes * 60,
           "worker_id": None, "lease_expires_at": None, "not_before": 0, "started_at": None, "finished_at": None,
           "progress": 0.0, "stage": "queued", "error": None, "result": None, "cancel_requested": 0,
           "input_minutes": float(input_minutes), "idempotency_key": idempotency_key, "created_at": now(),
           "updated_at": now(), "deleted_at": None}
    t.insert("jobs", row)
    add_event(t, jid, "queued", {"queue": queue})
    return t.one("SELECT * FROM jobs WHERE id = ?", (jid,)), True


def claim(db, settings, worker, engine_version=None):
    """The next job for this worker (marked running, leased), or None."""
    with db.tx(immediate=True) as t:
        t.run("UPDATE workers SET last_seen_at = ?, engine_version = COALESCE(?, engine_version) WHERE id = ?",
              (now(), engine_version, worker["id"]))
        if worker["channel"] == "stable":
            stable = get_setting(t, "stable_version")
            if stable and engine_version != stable:
                return None              # this worker does not run the promoted version
        queues = [q for q in worker["queues"] if q in QUEUES]
        if not queues:
            return None
        marks = ", ".join("?" for _ in queues)
        row = t.one(
            f"SELECT j.id FROM jobs j JOIN clients c ON c.id = j.client_id WHERE j.status = 'queued' "
            f"AND j.not_before <= ? AND j.queue IN ({marks}) AND j.channel = ? AND j.deleted_at IS NULL "
            f"AND c.status = 'active' AND (SELECT COUNT(*) FROM jobs r WHERE r.client_id = j.client_id "
            f"AND r.status = 'running') < c.concurrent_jobs ORDER BY j.priority, j.created_at LIMIT 1"
            # Postgres: lock the job and its client row, so two workers claiming at once can neither
            # take the same job nor push a client past its concurrent_jobs.
            + t.for_update.replace(" FOR UPDATE", " FOR UPDATE OF j, c"),
            [now(), *queues, worker["channel"]])
        if row is None:
            return None
        lease = now() + settings.lease_seconds
        t.run("UPDATE jobs SET status = 'running', worker_id = ?, attempts = attempts + 1, lease_expires_at = ?, "
              "started_at = COALESCE(started_at, ?), stage = 'starting', updated_at = ?, cancel_requested = 0 "
              "WHERE id = ? AND status = 'queued'", (worker["id"], lease, now(), now(), row["id"]))
        job = t.one("SELECT * FROM jobs WHERE id = ?", (row["id"],))
        add_event(t, job["id"], "started", {"worker": worker["name"], "attempt": job["attempts"]})
        return job


def _owned(t, job_id, worker):
    job = t.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job or job["worker_id"] != worker["id"] or job["status"] != "running":
        raise QueueError("This job is not running on this worker (it may have been given to another).", 409)
    return job


def heartbeat(db, settings, worker, job_id, progress=None, stage=None, message=None):
    """Extend the lease. Returns {"cancel": bool}."""
    with db.tx() as t:
        job = _owned(t, job_id, worker)
        values = {"lease_expires_at": now() + settings.lease_seconds, "updated_at": now()}
        if progress is not None:
            values["progress"] = max(0.0, min(1.0, float(progress)))
        if stage:
            values["stage"] = str(stage)[:60]
        t.update("jobs", job_id, values)
        t.run("UPDATE workers SET last_seen_at = ? WHERE id = ?", (now(), worker["id"]))
        if stage and stage != job["stage"]:
            add_event(t, job_id, "stage", {"stage": values["stage"], "label": (message or "")[:200],
                                           "progress": values.get("progress")})
        return {"cancel": bool(job["cancel_requested"])}


def _retry_or_fail(t, job, error, retryable):
    if retryable and job["attempts"] < job["max_attempts"] and not job["cancel_requested"]:
        wait = BACKOFF[min(job["attempts"] - 1, len(BACKOFF) - 1)] if job["attempts"] else BACKOFF[0]
        t.update("jobs", job["id"], {"status": "queued", "worker_id": None, "lease_expires_at": None,
                                     "not_before": now() + wait, "stage": "waiting to retry", "error": error[:2000],
                                     "updated_at": now()})
        add_event(t, job["id"], "retry", {"error": error[:500], "in_seconds": wait, "attempt": job["attempts"]})
        return "queued"
    status = "cancelled" if job["cancel_requested"] else "failed"
    t.update("jobs", job["id"], {"status": status, "lease_expires_at": None, "finished_at": now(),
                                 "error": error[:2000], "updated_at": now(), "stage": status})
    add_event(t, job["id"], status, {"error": error[:500]})
    return status


def complete(db, worker, job_id, result):
    """The worker finished. `result` is the polish sidecar (or the render result)."""
    with db.tx() as t:
        _owned(t, job_id, worker)
        status = "failed" if (result or {}).get("status") == "failed" else "succeeded"
        t.update("jobs", job_id, {"status": status, "result": dumps(result), "finished_at": now(), "progress": 1.0,
                                  "stage": status, "lease_expires_at": None, "updated_at": now(),
                                  "error": (result or {}).get("error") if status == "failed" else None})
        add_event(t, job_id, status, {"status": (result or {}).get("status")})
        return t.one("SELECT * FROM jobs WHERE id = ?", (job_id,))


def fail(db, worker, job_id, error, retryable=True):
    with db.tx() as t:
        job = _owned(t, job_id, worker)
        _retry_or_fail(t, job, error, retryable)
        return t.one("SELECT * FROM jobs WHERE id = ?", (job_id,))


def cancel(t, job):
    if job["status"] in FINAL:
        raise QueueError(f"The job already {job['status']}.", 409)
    if job["status"] == "queued":
        t.update("jobs", job["id"], {"status": "cancelled", "finished_at": now(), "stage": "cancelled",
                                     "cancel_requested": 1, "updated_at": now()})
        add_event(t, job["id"], "cancelled", {})
    else:
        t.update("jobs", job["id"], {"cancel_requested": 1, "updated_at": now()})
        add_event(t, job["id"], "cancel_requested", {})


def reap(db, grace_seconds=60):
    """Jobs whose worker went quiet (lease expired) or that ran past their time limit go back to the
    queue (or fail after max_attempts). Returns the job ids handled."""
    done = []
    with db.tx(immediate=True) as t:
        rows = t.all("SELECT * FROM jobs WHERE status = 'running' AND (lease_expires_at < ? OR started_at + "
                     "timeout_seconds + ? < ?)" + t.for_update, (now(), grace_seconds, now()))
        for job in rows:
            if job["lease_expires_at"] is not None and job["lease_expires_at"] < now():
                _retry_or_fail(t, job, "The worker stopped answering; the job was given back to the queue.", True)
            else:
                _retry_or_fail(t, job, f"The job ran past its time limit ({job['timeout_seconds'] // 60} min).", True)
            done.append(job["id"])
    return done


def queue_stats(t):
    rows = t.all("SELECT queue, channel, status, COUNT(*) AS n FROM jobs WHERE deleted_at IS NULL GROUP BY queue, "
                 "channel, status")
    out = {}
    for r in rows:
        out.setdefault(f"{r['queue']}/{r['channel']}", {})[r["status"]] = int(r["n"])
    return out
