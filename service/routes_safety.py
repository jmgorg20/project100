"""Reporting a result (anyone with its link) and the staff's review of reports (admin API).

POST /v1/public/report   {"link": "<the result link>", "reason": "...", "details"?, "email"?, "captcha"?}
GET  /v1/admin/reports?status=open
POST /v1/admin/reports/<id>/resolve   {"action": "dismiss" | "remove" | "suspend", "note"?}
POST /v1/admin/reports/<id>/purge     delete the files kept as evidence
"""

from fastapi import APIRouter, Depends, Request

from . import moderation
from .api import ApiError, client_ip
from .deps import require_admin
from .routes_auth import _anonymous_post, _captcha

router = APIRouter()


def _err(exc):
    return ApiError(exc.status, exc.code, str(exc))


@router.get("/v1/public/report-reasons")
def reasons():
    return {"reasons": list(moderation.REASONS)}


@router.post("/v1/public/report", status_code=202)
def public_report(request: Request, body: dict):
    s = request.app.state
    _anonymous_post(request, body, "report", 5, 3600)          # 5 reports per address per hour
    _captcha(request, body)
    output_id = moderation.output_from_link(s.settings, body.get("link"))
    if not output_id:
        raise ApiError(422, "invalid_link", "Paste the whole link to the video (it starts with https:// and has ?t=).")
    with s.db.tx() as t:
        try:
            r = moderation.report(t, s.settings, output_id, body.get("reason"), body.get("details"), "public",
                                  body.get("email"), client_ip(request, s.settings))
        except moderation.ReportError as exc:
            raise _err(exc)
    return {"received": True, "id": r["id"]}


@router.get("/v1/admin/reports", dependencies=[Depends(require_admin)])
def list_reports(request: Request, status: str = "open", limit: int = 100):
    if status not in ("open", "dismissed", "removed", "suspended", "all"):
        raise ApiError(422, "invalid", "status must be open, dismissed, removed, suspended or all")
    with request.app.state.db.tx() as t:
        return {"reports": moderation.list_reports(t, None if status == "all" else status, limit)}


@router.post("/v1/admin/reports/{report_id}/resolve", dependencies=[Depends(require_admin)])
def resolve_report(request: Request, report_id: str, body: dict):
    s = request.app.state
    with s.db.tx() as t:
        try:
            return {"report": moderation.resolve(t, s.storage, report_id, body.get("action"), request.state.actor,
                                                 body.get("note"), client_ip(request, s.settings))}
        except moderation.ReportError as exc:
            raise _err(exc)


@router.post("/v1/admin/reports/{report_id}/purge", dependencies=[Depends(require_admin)])
def purge_report(request: Request, report_id: str):
    s = request.app.state
    with s.db.tx() as t:
        try:
            return moderation.purge(t, s.storage, report_id, request.state.actor, client_ip(request, s.settings))
        except moderation.ReportError as exc:
            raise _err(exc)
