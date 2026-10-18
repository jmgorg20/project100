"""The worker API (Authorization: Bearer wk_...). Workers connect out to the service over HTTPS: the
owner's PC, a cloud GPU machine or a CPU server never needs an open inbound port.

    POST /v1/worker/claim                      the next job (signed), or 204 after a long poll
    POST /v1/worker/jobs/{id}/heartbeat        progress; the answer says if the client cancelled
    GET  /v1/worker/jobs/{id}/inputs/{upload}  an input file of that job (only while it runs here)
    GET  /v1/worker/jobs/{id}/media/{output}   an earlier result a render job uses
    PUT  /v1/worker/jobs/{id}/outputs/{name}   a result file (video, project, sidecar, plan, asset-N)
    POST /v1/worker/jobs/{id}/complete         the result and the usage (CPU/GPU seconds, AI costs)
    POST /v1/worker/jobs/{id}/fail             what went wrong, and whether trying again may help
"""

import asyncio
import hashlib
import re

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from . import clients, jobqueue, jobs, security, webhooks
from .api import ApiError
from .db import loads, now
from .deps import require_worker

router = APIRouter(prefix="/v1/worker")
ASSET = re.compile(r"^asset-(\d{1,3})(\.[a-z0-9]{1,5})?$")
MAX_OUTPUT_BYTES = 4 * 1024 ** 3


def _running_job(t, worker, job_id):
    job = t.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job or job["worker_id"] != worker["id"] or job["status"] != "running":
        raise ApiError(409, "not_yours", "This job is not running on this worker.")
    return job


@router.post("/claim")
async def claim(request: Request, body: dict, worker=Depends(require_worker)):
    s = request.app.state
    version = str(body.get("engine_version") or "")[:40] or None
    wanted = [q for q in (body.get("queues") or worker["queues"]) if q in worker["queues"]]
    me = {**worker, "queues": wanted}
    wait = max(0, min(int(body.get("wait", s.settings.claim_wait_seconds)), s.settings.claim_wait_seconds))
    deadline = now() + wait
    while True:
        job = await run_in_threadpool(jobqueue.claim, s.db, s.settings, me, version)
        if job is not None:
            def finish():
                with s.db.tx() as t:
                    webhooks.emit(t, job["client_id"], "job.started", webhooks.payload_for_job(job))
                    return jobs.worker_payload(t, job, s.signing_key, s.settings.lease_seconds)
            return await run_in_threadpool(finish)
        if now() >= deadline or await request.is_disconnected():
            return Response(status_code=204)
        await asyncio.sleep(1.0)


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(request: Request, job_id: str, body: dict, worker=Depends(require_worker)):
    s = request.app.state
    try:
        return jobqueue.heartbeat(s.db, s.settings, worker, job_id, body.get("progress"), body.get("stage"),
                                  body.get("message"))
    except jobqueue.QueueError as exc:
        raise ApiError(exc.status, "not_yours", str(exc))


@router.get("/jobs/{job_id}/inputs/{upload_id}")
def get_input(request: Request, job_id: str, upload_id: str, worker=Depends(require_worker)):
    s = request.app.state
    with s.db.tx() as t:
        job = _running_job(t, worker, job_id)
        inputs = loads(job["inputs"], {})
        ids = [i for v in inputs.values() for i in v] if job["kind"] == "polish" else inputs.get("uploads", [])
        if upload_id not in ids:
            raise ApiError(403, "forbidden", "That file is not an input of this job.")
        u = t.one("SELECT * FROM uploads WHERE id = ? AND client_id = ? AND status = 'ready'", (upload_id, job["client_id"]))
    if not u:
        raise ApiError(410, "gone", "The input file was deleted.")
    return FileResponse(s.storage.upload_path(upload_id), media_type="application/octet-stream")


@router.get("/jobs/{job_id}/media/{output_id}")
def get_media(request: Request, job_id: str, output_id: str, worker=Depends(require_worker)):
    s = request.app.state
    with s.db.tx() as t:
        job = _running_job(t, worker, job_id)
        if job["kind"] != "render" or output_id not in loads(job["inputs"], {}).get("outputs", []):
            raise ApiError(403, "forbidden", "That file is not used by this job.")
        o = t.one("SELECT * FROM outputs WHERE id = ? AND client_id = ? AND deleted_at IS NULL", (output_id, job["client_id"]))
    if not o:
        raise ApiError(410, "gone", "That file was deleted.")
    return FileResponse(o["path"], media_type="application/octet-stream")


@router.put("/jobs/{job_id}/outputs/{name}")
async def put_output(request: Request, job_id: str, name: str, sha256: str, worker=Depends(require_worker)):
    s = request.app.state
    if name not in jobs.OUTPUT_NAMES:
        m = ASSET.match(name)
        if not m or int(m.group(1)) >= jobs.MAX_ASSETS:
            raise ApiError(422, "invalid", "Output name must be video, project, sidecar, plan or asset-N.")

    def begin():
        with s.db.tx() as t:
            job = _running_job(t, worker, job_id)
            client = clients.get_client(t, job["client_id"])
            return job, client
    job, client = await run_in_threadpool(begin)
    oid = security.new_id("out_")
    path = s.storage.output_path(job_id, oid)
    digest, size = hashlib.sha256(), 0
    try:
        with open(path, "wb") as f:
            async for part in request.stream():
                size += len(part)
                if size > MAX_OUTPUT_BYTES:
                    raise ApiError(413, "too_large", "The result file is too large.")
                digest.update(part)
                f.write(part)
        if digest.hexdigest() != sha256:
            raise ApiError(422, "checksum", "The file arrived damaged (checksum mismatch); send it again.")
    except BaseException:
        s.storage.delete(path)
        raise

    def save():
        with s.db.tx() as t:
            _running_job(t, worker, job_id)
            old = t.one("SELECT * FROM outputs WHERE job_id = ? AND name = ?", (job_id, name))
            if old:                                   # sent again (a retry): replace it
                s.storage.delete(old["path"])
                t.run("DELETE FROM outputs WHERE id = ?", (old["id"],))
            ext = name.rsplit(".", 1)[-1] if "." in name else ""
            ctype = jobs.CONTENT_TYPES.get(name) or {"mp4": "video/mp4", "png": "image/png", "jpg": "image/jpeg",
                                                      "wav": "audio/wav", "mp3": "audio/mpeg"}.get(ext, "application/octet-stream")
            t.insert("outputs", {"id": oid, "job_id": job_id, "client_id": job["client_id"], "name": name,
                                 "path": str(path), "size": size, "sha256": sha256, "content_type": ctype,
                                 "created_at": now(), "expires_at": now() + float(client["retention_days"]) * 86400,
                                 "first_download_at": None, "deleted_at": None})
    await run_in_threadpool(save)
    return {"id": oid, "name": name, "size": size}


@router.post("/jobs/{job_id}/complete")
def complete(request: Request, job_id: str, body: dict, worker=Depends(require_worker)):
    s = request.app.state
    result = body.get("result") or {}
    usage = body.get("usage") or {}
    if not isinstance(result, dict) or not isinstance(usage, dict):
        raise ApiError(422, "invalid", "result and usage must be objects.")
    try:
        job = jobqueue.complete(s.db, worker, job_id, result)
    except jobqueue.QueueError as exc:
        raise ApiError(exc.status, "not_yours", str(exc))
    with s.db.tx() as t:
        client = clients.get_client(t, job["client_id"])
        stored = int(t.value("SELECT COALESCE(SUM(size), 0) FROM outputs WHERE job_id = ?", (job_id,), 0) or 0)
        cost = (result.get("cost") or {}) if isinstance(result.get("cost"), dict) else {}

        def num(v, cap):
            try:
                return max(0.0, min(float(v or 0), cap))
            except (TypeError, ValueError):
                return 0.0
        amounts = {"input_minutes": job["input_minutes"],
                   "output_minutes": num(usage.get("output_seconds"), 86400) / 60.0,
                   "cpu_seconds": num(usage.get("cpu_seconds"), 864000), "gpu_seconds": num(usage.get("gpu_seconds"), 864000),
                   "wall_seconds": num(usage.get("wall_seconds"), 864000), "storage_bytes": stored,
                   "transcription_usd": num(cost.get("transcription"), 100), "ai_usd": num(cost.get("plan"), 100)
                   + num(cost.get("graphics"), 100)}
        amounts["cost_usd"] = clients.estimate_cost(
            s.settings, amounts["cpu_seconds"], amounts["gpu_seconds"], stored, float(client["retention_days"]), 0,
            amounts["transcription_usd"], amounts["ai_usd"])
        clients.record_usage(t, job["client_id"], job_id, "job", **amounts)
        webhooks.emit(t, job["client_id"], f"job.{job['status']}", webhooks.payload_for_job(job))
    return {"status": job["status"], "cost_usd": amounts["cost_usd"]}


@router.post("/jobs/{job_id}/fail")
def fail(request: Request, job_id: str, body: dict, worker=Depends(require_worker)):
    s = request.app.state
    error = str(body.get("error") or "The worker could not finish the job.")[:2000]
    try:
        job = jobqueue.fail(s.db, worker, job_id, error, retryable=body.get("retryable", True) is not False)
    except jobqueue.QueueError as exc:
        raise ApiError(exc.status, "not_yours", str(exc))
    if job["status"] in ("failed", "cancelled"):
        with s.db.tx() as t:
            webhooks.emit(t, job["client_id"], f"job.{job['status']}", webhooks.payload_for_job(job))
    return {"status": job["status"]}
