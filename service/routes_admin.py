"""The admin API (Authorization: Bearer <SERVICE_ADMIN_TOKEN>). Every change is written to the audit log.

Clients: create, change limits/presets/channel, suspend; keys: create, revoke, rotate.
Workers: create (token shown once), revoke. Queue: stats, jobs. Flags per channel. Releases:
register (with the test result), promote (only if the tests passed), rollback (one call).
"""

from fastapi import APIRouter, Depends, Request, Response

from . import clients, jobqueue
from .api import ApiError, client_ip
from .db import loads, now
from .deps import require_admin

router = APIRouter(prefix="/v1/admin", dependencies=[Depends(require_admin)])


def _err(exc):
    status = getattr(exc, "status", 400)
    return ApiError(status, "not_found" if status == 404 else "invalid", str(exc))


def _audit(request, t, action, target=None, details=None):
    clients.audit(t, "admin", action, target, details, client_ip(request, request.app.state.settings))


@router.get("/clients")
def list_clients(request: Request):
    with request.app.state.db.tx() as t:
        rows = t.all("SELECT * FROM clients ORDER BY created_at")
        return {"clients": [{**clients.public(c), "usage": clients.usage_this_month(t, c["id"])} for c in rows]}


@router.post("/clients", status_code=201)
def create_client(request: Request, body: dict):
    s = request.app.state
    with s.db.tx() as t:
        try:
            limits = {k: v for k, v in body.items() if k != "name"}
            c = clients.create_client(t, s.settings, body.get("name"), **limits)
            key = clients.create_key(t, s.settings, c["id"], "first key")
        except clients.ClientError as exc:
            raise _err(exc)
        _audit(request, t, "client.created", c["id"], {"name": c["name"]})
    return {"client": clients.public(c), "api_key": key["key"], "note": "Give the API key to the client; it is shown only now."}


@router.get("/clients/{client_id}")
def get_client(request: Request, client_id: str):
    with request.app.state.db.tx() as t:
        c = clients.get_client(t, client_id)
        if not c:
            raise ApiError(404, "not_found", "No such client.")
        return {"client": clients.public(c), "keys": clients.list_keys(t, client_id),
                "usage": clients.usage_this_month(t, client_id), "stored_bytes": clients.stored_bytes(t, client_id)}


@router.patch("/clients/{client_id}")
def update_client(request: Request, client_id: str, body: dict):
    with request.app.state.db.tx() as t:
        try:
            c = clients.update_client(t, client_id, body)
        except clients.ClientError as exc:
            raise _err(exc)
        _audit(request, t, "client.updated", client_id, body)
        return {"client": clients.public(c)}


@router.post("/clients/{client_id}/keys", status_code=201)
def create_key(request: Request, client_id: str, body: dict = None):
    s = request.app.state
    body = body or {}
    with s.db.tx() as t:
        try:
            key = clients.create_key(t, s.settings, client_id, body.get("name"), body.get("expires_days"))
        except clients.ClientError as exc:
            raise _err(exc)
        _audit(request, t, "key.created", key["id"], {"client": client_id})
    return key


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(request: Request, key_id: str):
    with request.app.state.db.tx() as t:
        try:
            clients.revoke_key(t, key_id)
        except clients.ClientError as exc:
            raise _err(exc)
        _audit(request, t, "key.revoked", key_id)
    return Response(status_code=204)


@router.post("/keys/{key_id}/rotate", status_code=201)
def rotate_key(request: Request, key_id: str, grace_hours: float = 24.0):
    s = request.app.state
    with s.db.tx() as t:
        try:
            new = clients.rotate_key(t, s.settings, key_id, grace_hours)
        except clients.ClientError as exc:
            raise _err(exc)
        _audit(request, t, "key.rotated", key_id, {"new_key": new["id"], "grace_hours": grace_hours})
    return new


@router.get("/workers")
def list_workers(request: Request):
    with request.app.state.db.tx() as t:
        rows = t.all("SELECT id, name, queues, channel, status, engine_version, created_at, last_seen_at, revoked_at "
                     "FROM workers ORDER BY created_at")
    for r in rows:
        r["queues"] = loads(r["queues"], [])
        r["alive"] = r["status"] == "active" and (r["last_seen_at"] or 0) > now() - 120
    return {"workers": rows}


@router.post("/workers", status_code=201)
def create_worker(request: Request, body: dict):
    s = request.app.state
    with s.db.tx() as t:
        try:
            w = jobqueue.create_worker(t, s.settings, body.get("name") or "worker", body.get("queues") or ["cpu"],
                                       body.get("channel") or "stable")
        except jobqueue.QueueError as exc:
            raise _err(exc)
        _audit(request, t, "worker.created", w["id"], {"queues": w["queues"], "channel": w["channel"]})
    return {**w, "public_key": s.public_key,
            "note": "Give the token and the public key to the worker; the token is shown only now."}


@router.delete("/workers/{worker_id}", status_code=204)
def revoke_worker(request: Request, worker_id: str):
    with request.app.state.db.tx() as t:
        try:
            jobqueue.revoke_worker(t, worker_id)
        except jobqueue.QueueError as exc:
            raise _err(exc)
        _audit(request, t, "worker.revoked", worker_id)
    return Response(status_code=204)


@router.get("/queue")
def queue(request: Request):
    with request.app.state.db.tx() as t:
        return {"queues": jobqueue.queue_stats(t),
                "stable_version": jobqueue.get_setting(t, "stable_version"),
                "oldest_queued_seconds": max(0, int(now() - (t.value(
                    "SELECT MIN(created_at) FROM jobs WHERE status = 'queued'") or now())))}


@router.get("/jobs")
def jobs(request: Request, status: str = None, client_id: str = None, limit: int = 50):
    sql, params = "SELECT id, client_id, kind, queue, channel, status, attempts, stage, error, worker_id, created_at, " \
                  "started_at, finished_at, input_minutes FROM jobs WHERE 1 = 1", []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if client_id:
        sql += " AND client_id = ?"
        params.append(client_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(500, limit)))
    with request.app.state.db.tx() as t:
        return {"jobs": t.all(sql, params)}


@router.get("/flags")
def flags(request: Request):
    with request.app.state.db.tx() as t:
        return {"flags": t.all("SELECT * FROM flags ORDER BY name")}


@router.put("/flags/{name}")
def set_flag(request: Request, name: str, body: dict):
    if not name.replace("_", "").isalnum() or len(name) > 60:
        raise ApiError(422, "invalid", "A flag name is letters, digits and _.")
    with request.app.state.db.tx() as t:
        row = jobqueue.set_flag(t, name, body.get("stable"), body.get("beta"), body.get("description"))
        _audit(request, t, "flag.set", name, body)
    return row


@router.post("/releases", status_code=201)
def register_release(request: Request, body: dict):
    version = str(body.get("version") or "").strip()
    if not version or len(version) > 40:
        raise ApiError(422, "invalid", "version is required.")
    with request.app.state.db.tx() as t:
        jobqueue.register_release(t, version, bool(body.get("tests_passed")), body.get("report"))
        _audit(request, t, "release.registered", version, {"tests_passed": bool(body.get("tests_passed"))})
    return {"version": version, "tests_passed": bool(body.get("tests_passed"))}


@router.post("/releases/{version}/promote")
def promote(request: Request, version: str):
    with request.app.state.db.tx() as t:
        try:
            v = jobqueue.promote(t, version)
        except jobqueue.QueueError as exc:
            raise _err(exc)
        _audit(request, t, "release.promoted", v)
    return {"stable_version": v}


@router.post("/rollback")
def rollback(request: Request):
    with request.app.state.db.tx() as t:
        try:
            v = jobqueue.rollback(t)
        except jobqueue.QueueError as exc:
            raise _err(exc)
        _audit(request, t, "release.rollback", v)
    return {"stable_version": v}


@router.get("/usage")
def usage(request: Request, month: str = None):
    with request.app.state.db.tx() as t:
        rows = t.all("SELECT id, name FROM clients ORDER BY name")
        return {"month": month or clients.month_of(),
                "clients": [{"id": c["id"], "name": c["name"], **clients.usage_this_month(t, c["id"], month)} for c in rows]}


@router.get("/audit")
def audit_log(request: Request, limit: int = 100):
    with request.app.state.db.tx() as t:
        rows = t.all("SELECT * FROM audit_log ORDER BY at DESC LIMIT ?", (max(1, min(1000, limit)),))
    for r in rows:
        r["details"] = loads(r["details"])
    return {"entries": rows}
