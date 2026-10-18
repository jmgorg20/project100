"""The client API: an API key (Authorization: Bearer ak_...) or a signed-in user acting in their
organisation (the web app). A client only ever sees its own things: every query below filters by
the caller's client id, and on Postgres row-level security enforces it again (see db.py).

Signed-in members can upload and run jobs; changing presets and webhooks and deleting all data
needs an owner or admin (require_manager)."""

import asyncio
import json

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from . import SERVICE_VERSION, accounts, clients, jobqueue, jobs, media, ratelimit, security, webhooks
from .api import ApiError
from .db import dumps, loads, now
from .deps import require_client, require_manager
from .jobs import JobError

router = APIRouter(prefix="/v1")


def _err(exc):
    return ApiError(getattr(exc, "status", 400), "not_found" if getattr(exc, "status", 0) == 404 else "invalid", str(exc))


def base_url(request):
    return request.app.state.settings.public_url.rstrip("/")


@router.get("/info")
def info(request: Request):
    s = request.app.state
    return {"service": "autoedit", "version": SERVICE_VERSION, "public_key": s.public_key,
            "limits": {"max_upload_mb": s.settings.max_upload_mb, "max_duration_seconds": s.settings.max_duration_seconds,
                       "chunk_mb": s.settings.chunk_mb}}


@router.get("/me")
def me(request: Request, client=Depends(require_client)):
    s = request.app.state
    with s.db.tx() as t:
        usage = clients.usage_this_month(t, client["id"])
        stored = clients.stored_bytes(t, client["id"])
        flags = jobqueue.flags_for(t, client["channel"])
    c = clients.public(client)
    for k in ("key_id", "auth", "user_id", "role", "session_id"):
        c.pop(k, None)
    return {"client": c, "usage": usage, "stored_bytes": stored, "flags": flags, "role": client.get("role")}


@router.get("/catalog")
def catalog(request: Request, client=Depends(require_client)):
    with request.app.state.db.tx() as t:
        return jobs.catalog(client, t)


@router.get("/presets")
def my_presets(request: Request, client=Depends(require_client)):
    """Your own presets (plain preset JSON: copy one from GET /v1/catalog's ids in autoedit/presets/)."""
    with request.app.state.db.tx() as t:
        return {"presets": jobs.own_presets(t, client["id"])}


@router.put("/presets/{preset_id}")
def put_preset(request: Request, preset_id: str, body: dict, client=Depends(require_manager)):
    with request.app.state.db.tx() as t:
        try:
            saved = jobs.save_own_preset(t, client["id"], preset_id, body)
        except JobError as exc:
            raise _err(exc)
        clients.audit(t, f"client:{client['id']}", "preset.saved", preset_id)
    return saved


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(request: Request, preset_id: str, client=Depends(require_manager)):
    with request.app.state.db.tx() as t:
        if not t.run("DELETE FROM client_presets WHERE client_id = ? AND id = ?", (client["id"], preset_id)):
            raise ApiError(404, "not_found", "No such preset of yours.")
        clients.audit(t, f"client:{client['id']}", "preset.deleted", preset_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- uploads (resumable, in chunks)

def _upload_view(u, settings):
    return {"id": u["id"], "filename": u["filename"], "kind": u["kind"], "size": u["size_expected"],
            "received": u["size_received"], "status": u["status"], "error": u["error"], "duration": u["duration"],
            "media": loads(u["media"]), "expires_at": u["expires_at"], "project_id": u.get("project_id"),
            "expires_in_seconds": max(0, int(u["expires_at"] - now())), "chunk_size": settings.chunk_mb * 1024 * 1024}


def _get_upload(t, client, upload_id):
    u = t.one("SELECT * FROM uploads WHERE id = ? AND client_id = ? AND status <> 'deleted'", (upload_id, client["id"]))
    if not u:
        raise ApiError(404, "not_found", "No such upload.")
    return u


@router.post("/uploads", status_code=201)
def create_upload(request: Request, body: dict, client=Depends(require_client)):
    s = request.app.state
    filename = media.safe_filename(body.get("filename"))
    kind = media.kind_of(filename)
    if kind is None or not any(filename.lower().endswith(e) for e in s.settings.allowed_extensions):
        raise ApiError(415, "unsupported", "This kind of file is not accepted (videos, pictures, sounds, projects).")
    try:
        size = int(body.get("size"))
    except (TypeError, ValueError):
        raise ApiError(422, "invalid", "size (bytes) is required.")
    limit = s.settings.max_upload_mb * 1024 * 1024 if kind != "project" else media.MAX_PROJECT_BYTES
    if size <= 0 or size > limit:
        raise ApiError(413, "too_large", f"The file must be at most {limit // (1024 * 1024)} MB.")
    sha = body.get("sha256")
    if sha is not None and (not isinstance(sha, str) or len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha)):
        raise ApiError(422, "invalid", "sha256 must be 64 lowercase hex characters.")
    project_id = body.get("project_id")
    with s.db.tx() as t:
        if project_id is not None:
            if not isinstance(project_id, str):
                raise ApiError(422, "invalid", "project_id must be a project id.")
            try:
                accounts.get_project(t, client["id"], project_id)
            except accounts.AccountError as exc:
                raise _err(exc)
        ok, retry = ratelimit.hit(t, f"upload:{client['id']}", 60)
        if not ok:
            raise ApiError(429, "rate_limited", "Too many uploads started; wait a minute.", {"Retry-After": str(retry)})
        try:
            clients.check_storage_quota(t, client, size)
        except clients.ClientError as exc:
            raise _err(exc)
        uid = security.new_id("up_")
        t.insert("uploads", {"id": uid, "client_id": client["id"], "filename": filename, "kind": kind,
                             "size_expected": size, "size_received": 0, "sha256": sha, "status": "uploading",
                             "path": str(s.storage.upload_path(uid)), "media": None, "duration": None, "error": None,
                             "created_at": now(), "updated_at": now(),
                             "expires_at": now() + float(client["retention_days"]) * 86400, "deleted_at": None,
                             "project_id": project_id, "user_id": client.get("user_id")})
        u = t.one("SELECT * FROM uploads WHERE id = ?", (uid,))
    out = _upload_view(u, s.settings)
    out["upload_url"] = f"{base_url(request)}/v1/uploads/{uid}/chunk"
    return out


@router.get("/uploads/{upload_id}")
def get_upload(request: Request, upload_id: str, client=Depends(require_client)):
    s = request.app.state
    with s.db.tx() as t:
        u = _get_upload(t, client, upload_id)
    return _upload_view(u, s.settings)


@router.put("/uploads/{upload_id}/chunk")
async def put_chunk(request: Request, upload_id: str, offset: int, client=Depends(require_client)):
    """Send the next piece of the file, starting at `offset` (= the bytes already received; ask
    GET /v1/uploads/{id} after a broken connection and continue from there)."""
    s = request.app.state
    limit = s.settings.chunk_mb * 1024 * 1024
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data) > limit:
            raise ApiError(413, "too_large", f"A chunk can be at most {s.settings.chunk_mb} MB.")

    def write():
        with s.db.tx() as t:
            u = _get_upload(t, client, upload_id)
            if u["status"] != "uploading":
                raise ApiError(409, "conflict", f"This upload is already {u['status']}.")
        received = s.storage.append_chunk(upload_id, offset, bytes(data), u["size_expected"])
        with s.db.tx() as t:
            t.run("UPDATE uploads SET size_received = ?, updated_at = ? WHERE id = ? AND client_id = ?",
                  (received, now(), upload_id, client["id"]))
        return received, u["size_expected"]

    received, size = await run_in_threadpool(write)
    return Response(content=json.dumps({"received": received, "size": size, "complete": received == size}),
                    media_type="application/json", headers={"Upload-Offset": str(received)})


@router.post("/uploads/{upload_id}/complete")
def complete_upload(request: Request, upload_id: str, client=Depends(require_client)):
    """All bytes sent: check the file (hash, scanner, ffprobe, limits). Ready, or rejected with the reason."""
    s = request.app.state
    with s.db.tx() as t:
        u = _get_upload(t, client, upload_id)
    if u["status"] == "ready":
        return _upload_view(u, s.settings)
    if u["status"] != "uploading":
        raise ApiError(409, "conflict", f"This upload is {u['status']}.")
    path = s.storage.upload_path(upload_id)
    size = s.storage.upload_size(upload_id)
    if size != u["size_expected"]:
        raise ApiError(409, "incomplete", f"Only {size} of {u['size_expected']} bytes arrived; send the rest first.",
                       {"Upload-Offset": str(size)})
    error, info, digest = None, None, s.storage.sha256(path)
    try:
        if u["sha256"] and digest != u["sha256"]:
            raise media.MediaError("The file arrived damaged (its checksum does not match). Upload it again.")
        media.scan(path, s.settings.scan_command)
        info = media.check(path, u["filename"], s.settings.max_duration_seconds)
    except media.MediaError as exc:
        error = str(exc)
    with s.db.tx() as t:
        if error:
            s.storage.delete(path)
            t.update("uploads", upload_id, {"status": "rejected", "error": error, "sha256": digest, "path": None,
                                            "updated_at": now()})
            webhooks.emit(t, client["id"], "upload.rejected", {"upload_id": upload_id, "error": error})
        else:
            t.update("uploads", upload_id, {"status": "ready", "kind": info["kind"], "media": dumps(info),
                                            "duration": info.get("duration"), "sha256": digest, "updated_at": now()})
            webhooks.emit(t, client["id"], "upload.ready", {"upload_id": upload_id, "kind": info["kind"]})
        u = t.one("SELECT * FROM uploads WHERE id = ?", (upload_id,))
    if error:
        raise ApiError(422, "rejected", error)
    return _upload_view(u, s.settings)


@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(request: Request, upload_id: str, client=Depends(require_client)):
    s = request.app.state
    with s.db.tx() as t:
        _get_upload(t, client, upload_id)
        s.storage.delete(s.storage.upload_path(upload_id))
        t.update("uploads", upload_id, {"status": "deleted", "deleted_at": now(), "path": None, "updated_at": now()})
        clients.audit(t, f"client:{client['id']}", "upload.deleted", upload_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- jobs

def _get_job(t, client, job_id):
    j = t.one("SELECT * FROM jobs WHERE id = ? AND client_id = ? AND deleted_at IS NULL", (job_id, client["id"]))
    if not j:
        raise ApiError(404, "not_found", "No such job.")
    return j


@router.post("/jobs", status_code=201)
def create_job(request: Request, body: dict, response: Response, client=Depends(require_client)):
    s = request.app.state
    with s.db.tx() as t:
        try:
            job, created = jobs.create(t, s.settings, client, body, request.headers.get("idempotency-key"))
        except (JobError, clients.ClientError, jobqueue.QueueError) as exc:
            raise _err(exc)
        if created:
            webhooks.emit(t, client["id"], "job.queued", webhooks.payload_for_job(job))
            clients.audit(t, f"client:{client['id']}", "job.created", job["id"], {"kind": job["kind"]})
        else:
            response.status_code = 200
        return jobs.view(t, s.settings, job, base_url(request))


@router.get("/jobs")
def list_jobs(request: Request, client=Depends(require_client), status: str = None, limit: int = 20,
              before: float = None, project_id: str = None):
    s = request.app.state
    limit = max(1, min(100, limit))
    sql = "SELECT * FROM jobs WHERE client_id = ? AND deleted_at IS NULL"
    params = [client["id"]]
    if status:
        sql += " AND status = ?"
        params.append(status)
    if before:
        sql += " AND created_at < ?"
        params.append(before)
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with s.db.tx() as t:
        rows = t.all(sql, params)
        items = [jobs.view(t, s.settings, j, base_url(request)) for j in rows]
    return {"jobs": items, "next_before": rows[-1]["created_at"] if len(rows) == limit else None}


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str, client=Depends(require_client)):
    s = request.app.state
    with s.db.tx() as t:
        return jobs.view(t, s.settings, _get_job(t, client, job_id), base_url(request))


@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str, client=Depends(require_client)):
    """Live updates (Server-Sent Events). Reconnect with Last-Event-ID to continue."""
    s = request.app.state

    def read(after):
        with s.db.tx() as t:
            job = _get_job(t, client, job_id)
            events = t.all("SELECT * FROM job_events WHERE job_id = ? AND seq > ? ORDER BY seq LIMIT 100",
                           (job_id, after))
            return job, events

    start = int(request.headers.get("last-event-id") or request.query_params.get("since") or 0)
    await run_in_threadpool(read, start)          # 404 before streaming starts

    async def stream():
        after, quiet = start, 0.0
        for _ in range(600):                      # at most 10 minutes per connection
            if await request.is_disconnected():
                return
            job, events = await run_in_threadpool(read, after)
            for e in events:
                after = e["seq"]
                data = {"kind": e["kind"], "at": e["at"], "data": loads(e["data"])}
                yield f"id: {e['seq']}\nevent: {e['kind']}\ndata: {json.dumps(data)}\n\n"
            yield (f"event: status\ndata: {json.dumps({'status': job['status'], 'progress': job['progress'], 'stage': job['stage']})}\n\n"
                   if events or quiet >= 15 else "")
            quiet = 0.0 if events else quiet + 1
            if job["status"] in jobqueue.FINAL and not events:
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str, client=Depends(require_client)):
    s = request.app.state
    with s.db.tx() as t:
        job = _get_job(t, client, job_id)
        try:
            jobqueue.cancel(t, job)
        except jobqueue.QueueError as exc:
            raise _err(exc)
        job = t.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if job["status"] == "cancelled":
            webhooks.emit(t, client["id"], "job.cancelled", webhooks.payload_for_job(job))
        return jobs.view(t, s.settings, job, base_url(request))


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(request: Request, job_id: str, client=Depends(require_client)):
    """Delete a job's results now (a running job is cancelled first)."""
    s = request.app.state
    with s.db.tx() as t:
        job = _get_job(t, client, job_id)
        if job["status"] not in jobqueue.FINAL:
            jobqueue.cancel(t, job)
        clients.delete_job_files(t, s.storage, job)
        t.run("UPDATE jobs SET deleted_at = ?, params = '{}', result = NULL WHERE id = ?", (now(), job_id))
        clients.audit(t, f"client:{client['id']}", "job.deleted", job_id)
    return Response(status_code=204)


@router.delete("/data", status_code=200)
def delete_my_data(request: Request, client=Depends(require_manager)):
    """Delete every upload and result of this client now (jobs keep only their ids and times)."""
    s = request.app.state
    with s.db.tx() as t:
        n_up, n_jobs = clients.delete_client_files(t, s.storage, client["id"])
        clients.audit(t, f"client:{client['id']}", "data.deleted", client["id"], {"uploads": n_up, "jobs": n_jobs})
    return {"deleted_uploads": n_up, "deleted_jobs": n_jobs}


@router.get("/usage")
def usage(request: Request, client=Depends(require_client), month: str = None):
    s = request.app.state
    if month is not None and (len(month) != 7 or month[4] != "-"):
        raise ApiError(422, "invalid", "month must look like 2026-10.")
    with s.db.tx() as t:
        used = clients.usage_this_month(t, client["id"], month)
        reserved = clients.reserved_minutes(t, client["id"])
    return {"month": month or clients.month_of(), "usage": used, "reserved_minutes": reserved,
            "limits": {"monthly_minutes": client["monthly_minutes"], "storage_mb": client["storage_mb"],
                       "concurrent_jobs": client["concurrent_jobs"], "rate_per_minute": client["rate_per_minute"],
                       "gpu_allowed": bool(client["gpu_allowed"])}}


# ---------------------------------------------------------------- webhooks and keys

@router.get("/webhooks")
def list_webhooks(request: Request, client=Depends(require_manager)):
    with request.app.state.db.tx() as t:
        return {"webhooks": webhooks.list_for(t, client["id"])}


@router.post("/webhooks", status_code=201)
def add_webhook(request: Request, body: dict, client=Depends(require_manager)):
    s = request.app.state
    with s.db.tx() as t:
        try:
            hook = webhooks.register(t, s.settings, client["id"], body.get("url"), body.get("events"))
        except webhooks.WebhookError as exc:
            raise _err(exc)
        clients.audit(t, f"client:{client['id']}", "webhook.created", hook["id"], {"url": hook["url"]})
    return {**hook, "note": "Keep the secret: it is shown only now. Check X-AutoEdit-Signature with it."}


@router.delete("/webhooks/{webhook_id}", status_code=204)
def delete_webhook(request: Request, webhook_id: str, client=Depends(require_manager)):
    with request.app.state.db.tx() as t:
        try:
            webhooks.delete(t, client["id"], webhook_id)
        except webhooks.WebhookError as exc:
            raise _err(exc)
        clients.audit(t, f"client:{client['id']}", "webhook.deleted", webhook_id)
    return Response(status_code=204)


@router.post("/keys/rotate", status_code=201)
def rotate_my_key(request: Request, client=Depends(require_client), grace_hours: float = 24.0):
    """A new key for you; the one you used keeps working for `grace_hours` (0-168)."""
    s = request.app.state
    if client["auth"] != "key":
        raise ApiError(400, "invalid", "Only an API key can rotate itself.")
    with s.db.tx() as t:
        new = clients.rotate_key(t, s.settings, client["key_id"], max(0.0, min(168.0, grace_hours)))
        clients.audit(t, f"client:{client['id']}", "key.rotated", client["key_id"])
    return {**new, "note": "Keep the new key: it is shown only now."}


# ---------------------------------------------------------------- projects

def _project_view(p):
    return {"id": p["id"], "name": p["name"], "created_at": p["created_at"], "updated_at": p["updated_at"],
            "jobs": p.get("jobs")}


@router.get("/projects")
def list_projects(request: Request, client=Depends(require_client)):
    with request.app.state.db.tx() as t:
        return {"projects": [_project_view(p) for p in accounts.list_projects(t, client["id"])]}


@router.post("/projects", status_code=201)
def create_project(request: Request, body: dict, client=Depends(require_client)):
    with request.app.state.db.tx() as t:
        try:
            p = accounts.create_project(t, client["id"], body.get("name"), client.get("user_id"))
        except accounts.AccountError as exc:
            raise _err(exc)
        clients.audit(t, f"client:{client['id']}", "project.created", p["id"])
        return _project_view(p)


@router.patch("/projects/{project_id}")
def rename_project(request: Request, project_id: str, body: dict, client=Depends(require_client)):
    with request.app.state.db.tx() as t:
        try:
            return _project_view(accounts.rename_project(t, client["id"], project_id, body.get("name")))
        except accounts.AccountError as exc:
            raise _err(exc)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(request: Request, project_id: str, client=Depends(require_client)):
    with request.app.state.db.tx() as t:
        try:
            accounts.delete_project(t, client["id"], project_id)
        except accounts.AccountError as exc:
            raise _err(exc)
        clients.audit(t, f"client:{client['id']}", "project.deleted", project_id)
    return Response(status_code=204)
