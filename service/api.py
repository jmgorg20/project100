"""The HTTP API (FastAPI). `python editor.py serve` runs it; see docs/service.md for every endpoint.

Three kinds of caller, each with its own credentials:
    clients  Authorization: Bearer ak_...   (their own jobs, uploads, webhooks and usage only)
    workers  Authorization: Bearer wk_...   (pull jobs, send progress and results)
    admin    Authorization: Bearer <SERVICE_ADMIN_TOKEN>
Signed file links (/files/...) need no header; they expire after a few minutes.
"""

import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from . import SERVICE_VERSION, janitor, security, webhooks
from .clients import ClientError
from .db import open_database
from .jobqueue import QueueError
from .media import MediaError
from .settings import Settings
from .storage import LocalStorage, StorageError
from .webhooks import WebhookError

log = logging.getLogger("autoedit.service")
MAX_JSON_BODY = 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, code, message, headers=None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def error_response(status, code, message, headers=None):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers or {})


def trusted_proxy(peer, settings):
    """True when the direct peer is one of SERVICE_TRUSTED_PROXIES (addresses or CIDR ranges)."""
    import ipaddress
    for entry in settings.trusted_proxies:
        if peer == entry:
            return True
        try:
            if ipaddress.ip_address(peer) in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request, settings):
    peer = request.client.host if request.client else ""
    if trusted_proxy(peer, settings):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer


def is_https(request, settings):
    peer = request.client.host if request.client else ""
    if trusted_proxy(peer, settings) and request.headers.get("x-forwarded-proto"):
        return request.headers["x-forwarded-proto"].split(",")[0].strip() == "https"
    return request.url.scheme == "https"


def load_signing_key(settings):
    if settings.signing_key_file and Path(settings.signing_key_file).exists():
        return security.load_signing_key(Path(settings.signing_key_file).read_text())
    if settings.production:
        raise RuntimeError("SERVICE_SIGNING_KEY_FILE is required in production")
    # development / tests: a key kept in the data folder (made on first start)
    path = settings.data_path / "signing-key.pem"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(security.new_signing_key())
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return security.load_signing_key(path.read_text())


def background_loop(app, stop):
    """The janitor and the webhook sender, while the API runs."""
    s = app.state
    last_janitor = 0.0
    while not stop.wait(2.0):
        try:
            webhooks.deliver_due(s.db, s.settings)
            if time.time() - last_janitor > 60:
                janitor.run_once(s.db, s.storage, s.settings)
                last_janitor = time.time()
        except Exception:                      # keep going; logged for the operator
            log.exception("background loop error")


def create_app(settings=None, storage=None):
    settings = settings or Settings.from_env()
    settings.check()

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()
        thread = None
        if settings.background:
            thread = threading.Thread(target=background_loop, args=(app, stop), daemon=True)
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(5)
        app.state.db.close()

    app = FastAPI(title="Auto Video Editor service", version=SERVICE_VERSION, lifespan=lifespan,
                  docs_url=None if settings.production else "/docs", redoc_url=None,
                  openapi_url=None if settings.production else "/openapi.json")
    app.state.settings = settings
    app.state.db = open_database(settings)
    app.state.storage = storage or LocalStorage(settings.data_path / "files")
    app.state.signing_key = load_signing_key(settings)
    app.state.public_key = security.public_key_pem(app.state.signing_key)
    app.state.started = time.time()
    app.state.metrics = {"requests": 0, "errors": 0}

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                           allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Upload-Offset"],
                           expose_headers=["Upload-Offset", "Retry-After"], max_age=600)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        started = time.time()
        rid = uuid.uuid4().hex[:16]
        request.state.request_id = rid
        request.state.actor = "anonymous"
        app.state.metrics["requests"] += 1
        if settings.require_https and not is_https(request, settings) and request.url.path not in ("/healthz",):
            return error_response(403, "https_required", "Use https://.")
        length = request.headers.get("content-length")
        streaming = request.url.path.endswith("/chunk") or "/outputs/" in request.url.path
        if length and not streaming:
            try:
                if int(length) > MAX_JSON_BODY:
                    return error_response(413, "too_large", "The request is too large.")
            except ValueError:
                return error_response(400, "bad_request", "Bad Content-Length.")
        try:
            response = await call_next(request)
        except Exception:
            app.state.metrics["errors"] += 1
            log.exception("unhandled error")
            response = error_response(500, "server_error", f"Something went wrong (request {rid}).")
        h = response.headers
        h["X-Request-Id"] = rid
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Cross-Origin-Resource-Policy"] = "same-site" if not request.url.path.startswith("/files/") else "cross-origin"
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        h.setdefault("Cache-Control", "no-store")
        if settings.require_https:
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if response.status_code >= 500:
            app.state.metrics["errors"] += 1
        line = {"at": round(started, 3), "rid": rid, "method": request.method, "path": request.url.path,
                "status": response.status_code, "ms": round((time.time() - started) * 1000, 1),
                "actor": request.state.actor, "ip": client_ip(request, settings)}
        log.info(json.dumps(line) if settings.log_json else " ".join(f"{k}={v}" for k, v in line.items()))
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return error_response(exc.status, exc.code, exc.message, exc.headers)

    for cls, code in ((ClientError, "client_error"), (QueueError, "queue_error"), (WebhookError, "webhook_error"),
                      (MediaError, "media_error"), (StorageError, "storage_error")):
        def handler(request, exc, code=code):
            status = getattr(exc, "status", 400)
            return error_response(status, "not_found" if status == 404 else code, str(exc))
        app.add_exception_handler(cls, handler)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        problems = [f"{'.'.join(str(p) for p in e.get('loc', [])[1:])}: {e.get('msg')}" for e in exc.errors()][:5]
        return error_response(422, "invalid", "Invalid request: " + "; ".join(problems))

    from .routes_admin import router as admin_router
    from .routes_client import router as client_router
    from .routes_files import router as files_router
    from .routes_worker import router as worker_router
    app.include_router(client_router)
    app.include_router(worker_router)
    app.include_router(admin_router)
    app.include_router(files_router)
    return app
