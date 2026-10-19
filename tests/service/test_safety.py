"""Safety: reporting a result by its link, holding it, the staff's decision (dismiss / remove /
suspend), the content check on uploads, the AI label on results, and how long records are kept."""

import dataclasses
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service import janitor, security
from service.api import create_app
from service.db import now
from tests.service.helpers import admin, make_video, new_client, new_worker, ready_upload, upload
from tests.service.test_api import polish_job, run_fake_worker


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("media") / "talk.mp4", seconds=1.0)


@pytest.fixture
def settings(settings):
    return dataclasses.replace(settings, trusted_proxies=["testclient"])      # reports come "from" X-Forwarded-For


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def http(app):
    with TestClient(app) as c:
        yield c


def finished(http, app, video):
    """A client with one finished job: (client, headers, job id, the video's output view)."""
    c, h = new_client(http)
    up = ready_upload(http, h, video)
    wh, _ = new_worker(http)
    jid, _ = run_fake_worker(http, wh, app.state.settings, app, polish_job(http, h, up["id"]).json()["id"])
    view = http.get(f"/v1/jobs/{jid}", headers=h).json()
    return c, h, jid, view


def local(app, url):
    return url.replace(app.state.settings.public_url, "")


def report(http, link, reason="copyright", ip="203.0.113.7", **extra):
    return http.post("/v1/public/report", json={"link": link, "reason": reason, **extra},
                     headers={"X-Forwarded-For": ip})


def test_results_carry_the_ai_label(http, app, video):
    _, _, _, view = finished(http, app, video)
    assert view["ai_label"]["edited_with_ai"] is True and "AI" in view["ai_label"]["text"]
    assert view["outputs"][0]["held"] is False


def test_a_report_by_link_and_the_staff_dismiss_it(http, app, video):
    c, h, jid, view = finished(http, app, video)
    out = view["outputs"][0]
    assert report(http, "https://evil.example/files/out/out_x?t=1.abc").status_code == 422
    assert report(http, out["url"], reason="nonsense").status_code == 422
    assert report(http, out["url"], email="not an email").status_code == 422
    r = report(http, out["preview_url"], details="  this is my song  ", email="Owner@Label.example")
    assert r.status_code == 202, r.text
    assert http.get(local(app, out["preview_url"])).status_code == 200           # one copyright report: not held
    reports = http.get("/v1/admin/reports", headers=admin(http)).json()["reports"]
    [rep] = [x for x in reports if x["job_id"] == jid]
    assert rep["reason"] == "copyright" and rep["details"] == "this is my song" and rep["client_id"] == c["id"]
    assert rep["reporter_email"] == "owner@label.example" and rep["ip"]
    r = http.post(f"/v1/admin/reports/{rep['id']}/resolve", json={"action": "dismiss", "note": "licensed"},
                  headers=admin(http))
    assert r.status_code == 200 and r.json()["report"]["status"] == "dismissed"
    assert http.post(f"/v1/admin/reports/{rep['id']}/resolve", json={"action": "remove"},
                     headers=admin(http)).status_code == 409
    audit = http.get("/v1/admin/audit", params={"action": "report."}, headers=admin(http)).json()["entries"]
    assert {e["action"] for e in audit} >= {"report.created", "report.dismissed"}


def test_an_expired_link_can_still_be_reported(http, app, video):
    _, _, _, view = finished(http, app, video)
    out = view["outputs"][0]
    old = security.sign_link(app.state.settings.secret_key, "out", out["id"], now() - 86400)
    assert report(http, f"https://x.example/files/out/{out['id']}?t={old}").status_code == 202


def test_child_safety_reports_hold_the_file_and_keep_it_as_evidence(http, app, video):
    _, h, jid, view = finished(http, app, video)
    out = view["outputs"][0]
    assert report(http, out["url"], reason="child_safety").status_code == 202
    assert http.get(local(app, out["url"])).status_code == 451
    assert http.get(f"/v1/jobs/{jid}", headers=h).json()["outputs"][0]["held"] is True
    [rep] = [x for x in http.get("/v1/admin/reports", headers=admin(http)).json()["reports"] if x["job_id"] == jid]
    assert rep["held_at"]
    # the uploader cannot destroy it, and neither can expiry
    assert http.delete(f"/v1/jobs/{jid}", headers=h).status_code == 204
    with app.state.db.tx() as t:
        t.run("UPDATE outputs SET expires_at = ? WHERE job_id = ?", (now() - 60, jid))
    janitor.expire_files(app.state.db, app.state.storage)
    with app.state.db.tx() as t:
        [o] = t.all("SELECT path, deleted_at FROM outputs WHERE job_id = ?", (jid,))
    assert o["deleted_at"] is None
    assert Path(o["path"]).exists()
    r = http.post(f"/v1/admin/reports/{rep['id']}/resolve", json={"action": "remove"}, headers=admin(http))
    assert r.json()["report"]["status"] == "removed" and r.json()["report"]["preserved"] is True
    assert Path(o["path"]).exists() and http.get(local(app, out["url"])).status_code == 451
    assert http.post(f"/v1/admin/reports/{rep['id']}/purge", headers=admin(http)).json() == {"purged": 1}
    assert not Path(o["path"]).exists() and http.get(local(app, out["url"])).status_code == 410
    actions = {e["action"] for e in http.get("/v1/admin/audit", params={"action": "report."},
                                              headers=admin(http)).json()["entries"]}
    assert {"report.removed", "report.purged"} <= actions


def test_removing_a_reported_video_deletes_it(http, app, video):
    _, h, jid, view = finished(http, app, video)
    out = view["outputs"][0]
    report(http, out["url"], reason="copyright")
    [rep] = [x for x in http.get("/v1/admin/reports", headers=admin(http)).json()["reports"] if x["job_id"] == jid]
    assert http.post(f"/v1/admin/reports/{rep['id']}/purge", headers=admin(http)).status_code == 409   # still open
    r = http.post(f"/v1/admin/reports/{rep['id']}/resolve", json={"action": "remove"}, headers=admin(http))
    assert r.json()["report"]["preserved"] is False
    assert http.get(local(app, out["url"])).status_code == 410
    assert http.get(f"/v1/jobs/{jid}", headers=h).json()["outputs"] == []


def test_a_dismissed_report_finishes_a_deletion_the_owner_asked_for(http, app, video):
    _, h, jid, view = finished(http, app, video)
    out = view["outputs"][0]
    report(http, out["url"], reason="child_safety")
    http.delete(f"/v1/jobs/{jid}", headers=h)
    [rep] = [x for x in http.get("/v1/admin/reports", headers=admin(http)).json()["reports"] if x["job_id"] == jid]
    http.post(f"/v1/admin/reports/{rep['id']}/resolve", json={"action": "dismiss"}, headers=admin(http))
    assert http.get(local(app, out["url"])).status_code == 410


def test_several_reports_from_different_addresses_hold_the_file(http, app, video):
    _, _, _, view = finished(http, app, video)
    link = view["outputs"][0]["url"]
    for i, ip in enumerate(("198.51.100.1", "198.51.100.2", "198.51.100.1", "198.51.100.3")):
        assert report(http, link, reason="spam", ip=ip).status_code == 202
        held = http.get(local(app, view["outputs"][0]["preview_url"])).status_code == 451
        assert held == (i == 3), i                                         # the third different address


def test_suspend_stops_the_workspace(http, app, video):
    c, h, jid, view = finished(http, app, video)
    report(http, view["outputs"][0]["url"], reason="illegal")
    [rep] = [x for x in http.get("/v1/admin/reports", headers=admin(http)).json()["reports"] if x["job_id"] == jid]
    http.post(f"/v1/admin/reports/{rep['id']}/resolve", json={"action": "suspend"}, headers=admin(http))
    assert http.get("/v1/me", headers=h).status_code in (401, 403)
    assert http.get(f"/v1/admin/clients/{c['id']}", headers=admin(http)).json()["client"]["status"] == "suspended"
    assert http.get("/v1/admin/reports", params={"status": "suspended"}, headers=admin(http)).json()["reports"]


def test_reports_are_limited_per_address_and_need_no_account(settings, video):
    with TestClient(create_app(settings)) as http:
        app = http.app
        _, _, _, view = finished(http, app, video)
        codes = [report(http, view["outputs"][0]["url"], ip="192.0.2.9").status_code for _ in range(6)]
        assert codes == [202] * 5 + [429]
        assert http.post("/v1/public/report", json={"link": "x", "reason": "spam"},
                         headers={"Origin": "https://evil.example"}).status_code == 403
        assert http.get("/v1/admin/reports").status_code == 401


def test_the_content_check_refuses_uploads(settings, video, tmp_path):
    check = tmp_path / "check.py"
    check.write_text("import sys\nprint('nudity score 0.97')\nsys.exit(3)\n")
    s = dataclasses.replace(settings, moderation_command=f'"{sys.executable}" "{check}" {{path}}')
    with TestClient(create_app(s)) as http:
        _, h = new_client(http)
        r = upload(http, h, video)
        assert r.status_code == 422 and "nudity score 0.97" in r.json()["error"]["message"]
    s = dataclasses.replace(settings, moderation_command="/no/such/checker {path}")       # fails closed
    with TestClient(create_app(s)) as http:
        _, h = new_client(http)
        assert upload(http, h, video).status_code == 422


def test_old_audit_entries_and_handled_reports_are_removed(app, http, video):
    _, _, jid, view = finished(http, app, video)
    report(http, view["outputs"][0]["url"])
    s = dataclasses.replace(app.state.settings, audit_retention_days=30)
    with app.state.db.tx() as t:
        t.run("UPDATE audit_log SET at = ?", (now() - 31 * 86400,))
        t.run("UPDATE reports SET status = 'dismissed', resolved_at = ? WHERE job_id = ?", (now() - 31 * 86400, jid))
        assert janitor.trim_records(t, s) >= 2
        assert t.value("SELECT COUNT(*) FROM audit_log", (), 0) == 0
        assert t.value("SELECT COUNT(*) FROM reports WHERE job_id = ?", (jid,), 0) == 0
        assert janitor.trim_records(t, dataclasses.replace(s, audit_retention_days=0)) == 0
