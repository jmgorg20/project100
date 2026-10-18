"""The service API: auth, tenant isolation, uploads, jobs, the worker protocol, files, webhooks and
security headers. Every test runs on SQLite and on real Postgres."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from service import security
from service.api import create_app
from service.db import now
from tests.service.helpers import (ADMIN, admin, make_video, new_client, new_worker, ready_upload, sha, upload)


@pytest.fixture(scope="session")
def video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("media") / "talk.mp4")


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def http(app):
    with TestClient(app) as c:
        yield c


def polish_job(http, headers, upload_id, **extra):
    return http.post("/v1/jobs", json={"kind": "polish", "inputs": {"main": [upload_id]}, "preset": "viral_tiktok", **extra},
                     headers=headers)


# ---------------------------------------------------------------- auth and keys

def test_keys_are_needed_and_checked(http):
    _, h = new_client(http)
    assert http.get("/v1/me").status_code == 401
    assert http.get("/v1/me", headers={"Authorization": "Bearer ak_000000000000_" + "x" * 40}).status_code == 401
    assert http.get("/v1/me", headers=h).status_code == 200
    assert http.get("/v1/admin/clients", headers=h).status_code == 401           # a client key is not admin
    assert http.get("/v1/admin/clients", headers={"Authorization": "Bearer " + "b" * 40}).status_code == 401


def test_wrong_keys_are_slowed_down(http):
    bad = {"Authorization": "Bearer ak_000000000000_" + "y" * 40}
    codes = [http.get("/v1/me", headers=bad).status_code for _ in range(22)]
    assert codes[:20] == [401] * 20 and codes[-1] == 429


def test_revoke_rotate_suspend(http):
    c, h = new_client(http)
    r = http.post("/v1/keys/rotate", headers=h, params={"grace_hours": 0})
    new_h = {"Authorization": f"Bearer {r.json()['key']}"}
    assert http.get("/v1/me", headers=new_h).status_code == 200
    time.sleep(0.01)
    assert http.get("/v1/me", headers=h).status_code == 401                      # no grace: old key off
    key_id = r.json()["id"]
    assert http.delete(f"/v1/admin/keys/{key_id}", headers=admin(http)).status_code == 204
    assert http.get("/v1/me", headers=new_h).status_code == 401
    k = http.post(f"/v1/admin/clients/{c['id']}/keys", json={"name": "second"}, headers=admin(http)).json()
    h2 = {"Authorization": f"Bearer {k['key']}"}
    http.patch(f"/v1/admin/clients/{c['id']}", json={"status": "suspended"}, headers=admin(http))
    assert http.get("/v1/me", headers=h2).status_code == 401
    entries = [e["action"] for e in http.get("/v1/admin/audit", headers=admin(http)).json()["entries"]]
    assert {"client.created", "key.revoked", "client.updated"} <= set(entries)


def test_per_client_rate_limit(http):
    _, h = new_client(http, rate_per_minute=5)
    codes = [http.get("/v1/me", headers=h).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    assert http.get("/v1/me", headers=h).headers.get("retry-after")


# ---------------------------------------------------------------- uploads

def test_resumable_upload_survives_a_lost_reply(http, video):
    _, h = new_client(http)
    data = video.read_bytes()
    r = http.post("/v1/uploads", json={"filename": "talk.mp4", "size": len(data), "sha256": sha(data)}, headers=h)
    up = r.json()
    half = len(data) // 2
    assert http.put(f"/v1/uploads/{up['id']}/chunk", params={"offset": 0}, content=data[:half], headers=h).status_code == 200
    # the reply was "lost": the phone asks how much arrived and sends the same chunk again
    assert http.get(f"/v1/uploads/{up['id']}", headers=h).json()["received"] == half
    assert http.put(f"/v1/uploads/{up['id']}/chunk", params={"offset": 0}, content=data[:half], headers=h).status_code == 200
    gap = http.put(f"/v1/uploads/{up['id']}/chunk", params={"offset": half + 10}, content=data[half + 10:], headers=h)
    assert gap.status_code == 400 and "missing data" in gap.json()["error"]["message"]
    early = http.post(f"/v1/uploads/{up['id']}/complete", headers=h)
    assert early.status_code == 409 and early.headers["upload-offset"] == str(half)
    r = http.put(f"/v1/uploads/{up['id']}/chunk", params={"offset": half}, content=data[half:], headers=h)
    assert r.json()["complete"] and r.headers["upload-offset"] == str(len(data))
    done = http.post(f"/v1/uploads/{up['id']}/complete", headers=h).json()
    assert done["status"] == "ready" and done["kind"] == "video" and 1.5 < done["duration"] < 2.5
    assert done["expires_in_seconds"] > 2 * 86400


def test_bad_files_are_rejected(http, tmp_path, video, settings):
    _, h = new_client(http)
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"MZ\x90\x00 this is not a video" * 100)
    r = upload(http, h, fake)
    assert r.status_code == 422 and "not a readable" in r.json()["error"]["message"]
    assert http.post("/v1/uploads", json={"filename": "virus.exe", "size": 10}, headers=h).status_code == 415
    assert http.post("/v1/uploads", json={"filename": "big.mp4", "size": 10 ** 12}, headers=h).status_code == 413
    data = video.read_bytes()
    r = http.post("/v1/uploads", json={"filename": "t.mp4", "size": len(data), "sha256": "0" * 64}, headers=h)
    http.put(f"/v1/uploads/{r.json()['id']}/chunk", params={"offset": 0}, content=data, headers=h)
    bad = http.post(f"/v1/uploads/{r.json()['id']}/complete", headers=h)
    assert bad.status_code == 422 and "damaged" in bad.json()["error"]["message"]
    silent_pic = make_video(tmp_path / "long.mp4", seconds=4.0)
    settings.max_duration_seconds = 3
    r = upload(http, h, silent_pic)
    assert r.status_code == 422 and "too long" in r.json()["error"]["message"]


def test_storage_quota(http, video):
    _, h = new_client(http, storage_mb=0)
    r = http.post("/v1/uploads", json={"filename": "talk.mp4", "size": 1000}, headers=h)
    assert r.status_code == 413 and "Storage limit" in r.json()["error"]["message"]


# ---------------------------------------------------------------- tenant isolation

def test_clients_never_see_each_others_things(http, video):
    _, ha = new_client(http, "A")
    _, hb = new_client(http, "B")
    up = ready_upload(http, ha, video)
    job = polish_job(http, ha, up["id"]).json()
    hook = http.post("/v1/webhooks", json={"url": "https://example.com/hook"}, headers=ha).json()
    assert http.get(f"/v1/uploads/{up['id']}", headers=hb).status_code == 404
    assert http.delete(f"/v1/uploads/{up['id']}", headers=hb).status_code == 404
    assert http.get(f"/v1/jobs/{job['id']}", headers=hb).status_code == 404
    assert http.get(f"/v1/jobs/{job['id']}/events", headers=hb).status_code == 404
    assert http.post(f"/v1/jobs/{job['id']}/cancel", headers=hb).status_code == 404
    assert http.delete(f"/v1/jobs/{job['id']}", headers=hb).status_code == 404
    assert http.get("/v1/jobs", headers=hb).json()["jobs"] == []
    assert polish_job(http, hb, up["id"]).status_code == 404                      # A's upload in B's job
    assert http.delete(f"/v1/webhooks/{hook['id']}", headers=hb).status_code == 404
    assert http.get("/v1/webhooks", headers=hb).json()["webhooks"] == []
    assert http.delete("/v1/data", headers=hb).json() == {"deleted_uploads": 0, "deleted_jobs": 0}
    assert http.get(f"/v1/jobs/{job['id']}", headers=ha).status_code == 200      # A still has everything


# ---------------------------------------------------------------- jobs

def test_job_validation_and_quotas(http, video):
    c, h = new_client(http, monthly_minutes=0.02)
    up = ready_upload(http, h, video)
    cases = [({"preset": "hollywood"}, 400, "Unknown preset"), ({"format": "dance"}, 400, "Unknown format"),
             ({"inputs": {"main": []}}, 400, "exactly one"), ({"inputs": {"main": [up["id"]], "evil": []}}, 400, "role"),
             ({"instruction": "x" * 3000}, 400, "too long"), ({"provider": "openai"}, 400, "provider"),
             ({"gpu": True}, 403, "GPU"), ({"kind": "shell"}, 400, "kind")]
    for extra, status, text in cases:
        r = polish_job(http, h, up["id"], **extra)
        assert r.status_code == status and text in r.json()["error"]["message"], (extra, r.text)
    r = polish_job(http, h, up["id"])
    assert r.status_code == 402 and "Monthly minutes" in r.json()["error"]["message"]
    http.patch(f"/v1/admin/clients/{c['id']}", json={"monthly_minutes": 100, "presets": ["meme"]}, headers=admin(http))
    r = polish_job(http, h, up["id"])
    assert r.status_code == 403 and "not enabled" in r.json()["error"]["message"]
    r = polish_job(http, h, up["id"], preset="meme", instruction="Mabilis, maraming emoji")
    assert r.status_code == 201 and r.json()["status"] == "queued" and 0.03 < r.json()["input_minutes"] < 0.05


def test_flags_hold_back_features_until_promoted(http, video):
    _, h = new_client(http)
    up = ready_upload(http, h, video)
    http.put("/v1/admin/flags/formats", json={"stable": False, "beta": True}, headers=admin(http))
    r = polish_job(http, h, up["id"], format="listicle")
    assert r.status_code == 403 and "Not available yet" in r.json()["error"]["message"]
    assert polish_job(http, h, up["id"]).status_code == 201                       # without a format: fine
    http.put("/v1/admin/flags/formats", json={"stable": True}, headers=admin(http))
    assert polish_job(http, h, up["id"], format="listicle").status_code == 201


def test_idempotency_and_listing(http, video):
    _, h = new_client(http, concurrent_jobs=5)
    up = ready_upload(http, h, video)
    a = http.post("/v1/jobs", json={"inputs": {"main": [up["id"]]}}, headers={**h, "Idempotency-Key": "k1"})
    b = http.post("/v1/jobs", json={"inputs": {"main": [up["id"]]}}, headers={**h, "Idempotency-Key": "k1"})
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    for _ in range(3):
        polish_job(http, h, up["id"])
    page = http.get("/v1/jobs", params={"limit": 2}, headers=h).json()
    assert len(page["jobs"]) == 2 and page["next_before"]
    rest = http.get("/v1/jobs", params={"limit": 10, "before": page["next_before"]}, headers=h).json()
    assert len(rest["jobs"]) == 2


def test_cancel_a_queued_job_and_events(http, video):
    _, h = new_client(http)
    up = ready_upload(http, h, video)
    job = polish_job(http, h, up["id"]).json()
    assert http.post(f"/v1/jobs/{job['id']}/cancel", headers=h).json()["status"] == "cancelled"
    assert http.post(f"/v1/jobs/{job['id']}/cancel", headers=h).status_code == 409
    with http.stream("GET", f"/v1/jobs/{job['id']}/events", headers=h) as r:
        text = "".join(r.iter_text())
    assert "event: queued" in text and "event: cancelled" in text and "id: " in text


def test_render_job_media_must_be_the_clients_own(http, video):
    _, ha = new_client(http, "A")
    _, hb = new_client(http, "B")
    up = ready_upload(http, ha, video)
    project = {"format": "autoedit-project", "version": 2, "name": "x",
               "settings": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
               "media": [{"id": "m1", "kind": "video", "path": f"upload:{up['id']}", "duration": 2.0, "width": 360,
                          "height": 640, "has_audio": True}],
               "tracks": [{"id": "main", "kind": "video", "clips": [{"id": "v1", "type": "video", "media": "m1",
                                                                     "start": 0, "duration": 2.0, "in": 0, "out": 2.0}]}]}
    assert http.post("/v1/jobs", json={"kind": "render", "project": project}, headers=hb).status_code == 404
    bad = json.loads(json.dumps(project))
    bad["media"][0]["path"] = "/etc/passwd"
    r = http.post("/v1/jobs", json={"kind": "render", "project": bad}, headers=ha)
    assert r.status_code == 400 and "upload:<id>" in r.json()["error"]["message"]
    assert http.post("/v1/jobs", json={"kind": "render", "project": project}, headers=ha).status_code == 201


# ---------------------------------------------------------------- the worker protocol, results, files

def run_fake_worker(http, wh, settings, app, job_id=None):
    """Claim, check the signature, fetch inputs, upload a result, complete (what service/worker.py does)."""
    r = http.post("/v1/worker/claim", json={"engine_version": "dev", "wait": 0}, headers=wh)
    assert r.status_code == 200, r.text
    data = r.json()
    payload = data["payload"]
    assert security.verify_payload(app.state.public_key, payload, data["signature"])
    tampered = {**payload, "params": {**payload["params"], "instruction": "rm -rf /"}}
    assert not security.verify_payload(app.state.public_key, tampered, data["signature"])
    jid = payload["job_id"]
    assert job_id is None or jid == job_id
    for uid in payload["files"]:
        assert http.get(f"/v1/worker/jobs/{jid}/inputs/{uid}", headers=wh).status_code == 200
    assert http.post(f"/v1/worker/jobs/{jid}/heartbeat", json={"progress": 0.5, "stage": "render"},
                     headers=wh).json() == {"cancel": False}
    video = b"\x00\x00\x00\x18ftypmp42" + b"x" * 5000
    assert http.put(f"/v1/worker/jobs/{jid}/outputs/video", params={"sha256": "0" * 64}, content=video,
                    headers=wh).status_code == 422
    assert http.put(f"/v1/worker/jobs/{jid}/outputs/../../etc", params={"sha256": sha(video)}, content=video,
                    headers=wh).status_code in (404, 422)
    assert http.put(f"/v1/worker/jobs/{jid}/outputs/video", params={"sha256": sha(video)}, content=video,
                    headers=wh).status_code == 200
    r = http.post(f"/v1/worker/jobs/{jid}/complete",
                  json={"result": {"status": "ok", "qc": {"passed": True, "failed": []}, "cost": {"transcription": 0.01}},
                        "usage": {"cpu_seconds": 30, "wall_seconds": 35}}, headers=wh)
    assert r.status_code == 200 and r.json()["cost_usd"] > 0.01
    return jid, video


def test_full_flow_with_signed_links(http, video, settings, app):
    c, h = new_client(http)
    up = ready_upload(http, h, video)
    job = polish_job(http, h, up["id"]).json()
    wh, _ = new_worker(http)
    assert http.get(f"/v1/worker/jobs/{job['id']}/inputs/{up['id']}", headers=wh).status_code == 409  # not claimed yet
    jid, content = run_fake_worker(http, wh, settings, app, job["id"])
    view = http.get(f"/v1/jobs/{jid}", headers=h).json()
    assert view["status"] == "succeeded" and view["result"]["status"] == "ok"
    [out] = view["outputs"]
    assert out["name"] == "video" and out["expires_in_seconds"] > 86400
    r = http.get(out["url"].replace(settings.public_url, ""))
    assert r.status_code == 200 and r.content == content and "attachment" in r.headers["content-disposition"]
    after = http.get(f"/v1/jobs/{jid}", headers=h).json()["outputs"][0]
    assert after["expires_in_seconds"] <= settings.delete_after_download_hours * 3600 + 5   # download clock
    egress_before = http.get("/v1/usage", headers=h).json()["usage"]["egress_bytes"]
    assert egress_before == len(content)
    bad = out["url"].replace(settings.public_url, "").replace("?t=", "?t=1")
    assert http.get(bad).status_code == 403
    expired = security.sign_link(settings.secret_key, "out", out["id"], now() - 1)
    assert http.get(f"/files/out/{out['id']}", params={"t": expired}).status_code == 403
    usage = http.get("/v1/usage", headers=h).json()["usage"]
    assert usage["jobs"] == 1 and usage["cpu_seconds"] == 30 and usage["egress_bytes"] == len(content)
    assert usage["transcription_usd"] == pytest.approx(0.01)
    assert http.delete(f"/v1/jobs/{jid}", headers=h).status_code == 204
    assert http.get(out["url"].replace(settings.public_url, "")).status_code == 410
    assert http.get(f"/v1/jobs/{jid}", headers=h).status_code == 404


def test_preview_links_play_inline_and_count_only_the_bytes_sent(http, video, settings, app):
    _, h = new_client(http)
    up = ready_upload(http, h, video)
    wh, _ = new_worker(http)
    jid, content = run_fake_worker(http, wh, settings, app, polish_job(http, h, up["id"]).json()["id"])
    [out] = http.get(f"/v1/jobs/{jid}", headers=h).json()["outputs"]
    preview = out["preview_url"].replace(settings.public_url, "")
    r = http.get(preview, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.content == content[:100] and r.headers["content-disposition"].startswith("inline")
    r = http.get(preview, headers={"Range": f"bytes=-{len(content) // 2}"})
    assert r.status_code == 206
    usage = http.get("/v1/usage", headers=h).json()["usage"]
    assert usage["egress_bytes"] == 100 + len(content) // 2                       # not the whole file each time
    after = http.get(f"/v1/jobs/{jid}", headers=h).json()["outputs"][0]
    assert after["expires_in_seconds"] > 86400                                    # watching is not downloading


def test_worker_can_only_touch_its_running_job(http, video, settings, app):
    _, h = new_client(http, concurrent_jobs=2)
    a = ready_upload(http, h, video)
    b = ready_upload(http, h, video)
    ja = polish_job(http, h, a["id"]).json()
    jb = polish_job(http, h, b["id"]).json()
    w1, _ = new_worker(http)
    w2, _ = new_worker(http)
    p1 = http.post("/v1/worker/claim", json={"wait": 0}, headers=w1).json()["payload"]
    other = jb["id"] if p1["job_id"] == ja["id"] else ja["id"]
    other_upload = b["id"] if p1["job_id"] == ja["id"] else a["id"]
    assert http.get(f"/v1/worker/jobs/{p1['job_id']}/inputs/{other_upload}", headers=w1).status_code == 403
    assert http.post(f"/v1/worker/jobs/{other}/heartbeat", json={}, headers=w1).status_code == 409
    assert http.post(f"/v1/worker/jobs/{p1['job_id']}/complete", json={"result": {}}, headers=w2).status_code == 409
    p2 = http.post("/v1/worker/claim", json={"wait": 0}, headers=w2).json()["payload"]
    assert p2["job_id"] == other
    wid = [w for w in http.get("/v1/admin/workers", headers=admin(http)).json()["workers"]][0]["id"]
    assert http.delete(f"/v1/admin/workers/{wid}", headers=admin(http)).status_code == 204
    assert http.post("/v1/worker/claim", json={"wait": 0}, headers=w1).status_code == 401


def test_retention_and_delete_my_data(http, video, settings, app):
    _, h = new_client(http)
    up = ready_upload(http, h, video)
    polish_job(http, h, up["id"])
    wh, _ = new_worker(http)
    jid, _ = run_fake_worker(http, wh, settings, app)
    storage = app.state.storage
    path = storage.upload_path(up["id"])
    assert path.exists()
    with app.state.db.tx() as t:
        t.run("UPDATE uploads SET expires_at = ? WHERE id = ?", (now() - 1, up["id"]))
    from service import janitor
    out = janitor.run_once(app.state.db, storage, settings)
    assert out["uploads"] == 1 and not path.exists()
    assert http.get(f"/v1/uploads/{up['id']}", headers=h).status_code == 404
    result = http.delete("/v1/data", headers=h).json()
    assert result["deleted_jobs"] == 1
    assert not any((storage.root / "outputs").rglob("*.bin"))


# ---------------------------------------------------------------- webhooks

def test_webhooks_are_signed_and_retried(http, video, app, settings):
    _, h = new_client(http)
    r = http.post("/v1/webhooks", json={"url": "https://hooks.example.com/x", "events": ["job.queued"]}, headers=h)
    secret = r.json()["secret"]
    assert http.post("/v1/webhooks", json={"url": "ftp://x"}, headers=h).status_code == 400
    assert http.post("/v1/webhooks", json={"url": "https://x", "events": ["nope"]}, headers=h).status_code == 400
    up = ready_upload(http, h, video)
    polish_job(http, h, up["id"])
    sent, answers = [], [500, 200]

    def sender(url, body, signature, s):
        sent.append((url, body, signature))
        return answers.pop(0)

    from service import webhooks
    assert webhooks.deliver_due(app.state.db, settings, sender=sender) == 0      # 500: retried later
    with app.state.db.tx() as t:
        t.run("UPDATE webhook_deliveries SET next_attempt_at = 0")
    assert webhooks.deliver_due(app.state.db, settings, sender=sender) == 1
    url, body, signature = sent[-1]
    assert security.verify_webhook(secret, body, signature)
    assert not security.verify_webhook(secret, body + b"x", signature)
    assert json.loads(body)["event"] == "job.queued"


def test_webhook_addresses_are_checked(settings):
    from service import webhooks
    settings.allow_private_webhooks = False
    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254", "::1", "::ffff:127.0.0.1", "0.0.0.0"):
        assert not webhooks.address_allowed(ip, settings), ip
    assert webhooks.address_allowed("93.184.216.34", settings)
    with pytest.raises(webhooks.WebhookError, match="https"):
        webhooks.check_url("http://example.com/x", settings)
    with pytest.raises(webhooks.WebhookError, match="private or local"):
        webhooks.resolve_safe("localhost", 443, settings)


# ---------------------------------------------------------------- transport security

def test_security_headers_https_and_body_limits(settings):
    settings.require_https = True
    with TestClient(create_app(settings)) as http:
        r = http.get("/v1/info")
        assert r.status_code == 403 and r.json()["error"]["code"] == "https_required"
        r = http.get("/v1/info", headers={"X-Forwarded-Proto": "https"})     # not from a trusted proxy: ignored
        assert r.status_code == 403
    settings.trusted_proxies = ["testclient"]
    with TestClient(create_app(settings)) as http:
        r = http.get("/v1/info", headers={"X-Forwarded-Proto": "https"})     # from the trusted proxy
        assert r.status_code == 200
        for name in ("x-content-type-options", "x-frame-options", "referrer-policy", "content-security-policy",
                     "strict-transport-security"):
            assert name in r.headers
    settings.require_https = False
    with TestClient(create_app(settings)) as http:
        r = http.post("/v1/admin/clients", content=b"{" + b" " * (2 * 1024 * 1024) + b"}",
                      headers={"Authorization": f"Bearer {ADMIN}", "Content-Type": "application/json"})
        assert r.status_code == 413


def test_production_settings_refuse_weak_configuration():
    from service.settings import Settings, SettingsError
    with pytest.raises(SettingsError) as exc:
        Settings(env="production", secret_key="short", admin_token="x", public_url="http://x").check()
    text = str(exc.value)
    for problem in ("Postgres", "SECRET_KEY", "ADMIN_TOKEN", "SIGNING_KEY", "https://", "REQUIRE_HTTPS"):
        assert problem in text


def test_admin_release_gate_and_metrics(http):
    assert http.get("/metrics").status_code == 401
    http.post("/v1/admin/releases", json={"version": "1.2.0", "tests_passed": False}, headers=admin(http))
    r = http.post("/v1/admin/releases/1.2.0/promote", headers=admin(http))
    assert r.status_code == 409 and "did not pass" in r.json()["error"]["message"]
    http.post("/v1/admin/releases", json={"version": "1.1.0", "tests_passed": True}, headers=admin(http))
    assert http.post("/v1/admin/releases/1.1.0/promote", headers=admin(http)).json() == {"stable_version": "1.1.0"}
    m = http.get("/metrics", headers=admin(http)).text
    assert "autoedit_requests_total" in m and "autoedit_workers_alive" in m


def test_each_client_has_its_own_presets(http, video, app):
    _, ha = new_client(http, "A")
    _, hb = new_client(http, "B")
    from autoedit import presets
    mine = {k: v for k, v in presets.get("meme", {"presets_folder": ""}).items() if k != "builtin"}
    mine.update({"id": "jgg_city_promo", "name": "JGG City promo", "grade": "warm"})
    assert http.put("/v1/presets/jgg_city_promo", json={**mine, "grade": "sepia"}, headers=ha).status_code == 400
    assert http.put("/v1/presets/other_id", json=mine, headers=ha).status_code == 400
    assert http.put("/v1/presets/jgg_city_promo", json=mine, headers=ha).status_code == 200
    ids_a = {p["id"] for p in http.get("/v1/catalog", headers=ha).json()["presets"]}
    ids_b = {p["id"] for p in http.get("/v1/catalog", headers=hb).json()["presets"]}
    assert "jgg_city_promo" in ids_a and "jgg_city_promo" not in ids_b
    assert http.get("/v1/presets", headers=hb).json()["presets"] == {}
    up_b = ready_upload(http, hb, video)
    r = polish_job(http, hb, up_b["id"], preset="jgg_city_promo")
    assert r.status_code == 400 and "Unknown preset" in r.json()["error"]["message"]      # B cannot use A's preset
    up = ready_upload(http, ha, video)
    job = polish_job(http, ha, up["id"], preset="jgg_city_promo").json()
    wh, _ = new_worker(http)
    payload = http.post("/v1/worker/claim", json={"wait": 0}, headers=wh).json()["payload"]
    assert payload["job_id"] == job["id"] and payload["params"]["preset_body"]["grade"] == "warm"
    assert http.delete("/v1/presets/jgg_city_promo", headers=hb).status_code == 404
    assert http.delete("/v1/presets/jgg_city_promo", headers=ha).status_code == 204
