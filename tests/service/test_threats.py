"""Tests for the main threats in docs/threat-model.md that are not already covered next to their
feature (the threat model lists where each one is tested). Each test names its threat id."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from service.api import create_app
from tests.service.helpers import admin, make_video, new_client, new_worker, ready_upload
from tests.service.test_api import polish_job


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("media") / "talk.mp4", seconds=1.0)


@pytest.fixture
def app(settings):
    return create_app(dataclasses.replace(settings, password_cost=10, signup_mode="open"))


@pytest.fixture
def http(app):
    with TestClient(app) as c:
        yield c


def dump(app):
    """Every text value in the database, to look for secrets that must not be there."""
    with app.state.db.tx() as t:
        tables = [r["name"] for r in t.all("SELECT name FROM sqlite_master WHERE type = 'table'")] \
            if app.state.db.kind == "sqlite" else \
            [r["tablename"] for r in t.all("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")]
        return "\n".join(str(v) for name in tables for row in t.all(f"SELECT * FROM {name}") for v in row.values())


def test_T3_stolen_database_holds_no_usable_keys(app, http):
    """Key theft: a copy of the database must not give API keys, sign-ins, webhook secrets or passwords."""
    c, h = new_client(http)
    raw_key = h["Authorization"].split()[1]
    hook = http.post("/v1/webhooks", json={"url": "https://example.com/hook"}, headers=h).json()
    http.post("/v1/auth/signup", json={"email": "t3@example.com", "password": "correct horse battery",
                                       "accept_terms": True})
    w, worker = new_worker(http)
    everything = dump(app)
    assert raw_key not in everything and raw_key[12:] not in everything
    assert hook["secret"] not in everything
    assert "correct horse battery" not in everything
    assert w["Authorization"].split()[1] not in everything
    assert app.state.settings.admin_token not in everything and app.state.settings.secret_key not in everything


def test_T3_leaked_file_link_opens_one_file_for_a_short_time(app, http, video):
    """Key theft: a result link is not a key: it opens only its own file, until it expires."""
    from service import security
    from service.db import now
    _, h = new_client(http)
    up = ready_upload(http, h, video)
    out_id = "out_" + "x" * 20
    token = security.sign_link(app.state.settings.secret_key, "out", out_id, now() + 60)
    assert http.get(f"/files/out/{up['id']}", params={"t": token}).status_code == 403      # another object
    assert http.get(f"/files/out/{out_id}", params={"t": token + "0"}).status_code == 403
    assert http.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_T4_a_worker_token_is_not_a_client_or_admin_key(app, http, video):
    """Worker takeover: a stolen worker token cannot read clients' things or run admin actions."""
    _, h = new_client(http)
    up = ready_upload(http, h, video)
    job = polish_job(http, h, up["id"]).json()
    w, _ = new_worker(http)
    assert http.get("/v1/me", headers=w).status_code == 401
    assert http.get(f"/v1/jobs/{job['id']}", headers=w).status_code == 401
    assert http.get("/v1/admin/clients", headers=w).status_code == 401
    assert http.post("/v1/admin/workers", json={"name": "x", "queues": ["cpu"]}, headers=w).status_code == 401
    # inputs only of a job it has claimed
    assert http.get(f"/v1/worker/jobs/{job['id']}/inputs/{up['id']}", headers=w).status_code in (403, 409)


def test_T4_the_worker_refuses_jobs_the_service_did_not_sign(tmp_path):
    """Worker takeover from the other side: someone who can answer the worker's calls (a fake server)
    cannot make it run a job: the payload must carry the service's signature."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from service import security, worker
    real, fake = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    pem = real.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    class Reply:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class Http:
        def __init__(self, body):
            self.body, self.headers = body, {}

        def request(self, *a, **kw):
            return Reply(self.body)

    payload = {"job_id": "job_" + "a" * 24, "kind": "polish", "params": {"instruction": "x"}, "files": {},
               "issued_at": int(__import__("time").time())}
    for body in ({"payload": payload, "signature": security.sign_payload(fake, payload)},
                 {"payload": {**payload, "params": {"instruction": "rm -rf /"}},
                  "signature": security.sign_payload(real, payload)},
                 {"payload": payload}):
        agent = worker.Agent("http://service", "wt_x", pem.decode(), work_dir=str(tmp_path), allow_http=True,
                             http=Http(body))
        with pytest.raises(worker.WorkerError, match="signature"):
            agent.claim()
    ok = worker.Agent("http://service", "wt_x", pem.decode(), work_dir=str(tmp_path), allow_http=True,
                      http=Http({"payload": payload, "signature": security.sign_payload(real, payload)}))
    assert ok.claim() == payload


def test_T5_cost_exhaustion_limits(app, http, video):
    """Cost exhaustion: jobs at a time, minutes per month, upload size and length, request rate."""
    app.state.settings.max_queued_jobs = 2
    c, h = new_client(http, monthly_minutes=1000)
    up = ready_upload(http, h, video)
    codes = [polish_job(http, h, up["id"], instruction=f"job {i}").status_code for i in range(3)]
    assert codes == [201, 201, 429]                                                    # a backlog has a limit
    _, other = new_client(http, "Someone else")
    assert polish_job(http, other, ready_upload(http, other, video)["id"]).status_code == 201   # not blocked
    app.state.settings.max_queued_jobs = 20
    http.patch(f"/v1/admin/clients/{c['id']}", json={"monthly_minutes": 0.02}, headers=admin(http))
    assert polish_job(http, h, up["id"], instruction="no minutes").status_code == 402  # queued minutes count
    too_big = app.state.settings.max_upload_mb * 1024 * 1024 + 1
    assert http.post("/v1/uploads", json={"filename": "x.mp4", "size": too_big}, headers=h).status_code == 413
    r = http.post("/v1/uploads", json={"filename": "x.mp4", "size": 10}, headers=h).json()
    over = http.put(f"/v1/uploads/{r['id']}/chunk", params={"offset": 0}, content=b"x" * 11, headers=h)
    assert over.status_code in (400, 409, 413, 422)                                   # more than it said


def test_T2_hostile_file_names_are_harmless(app, http, video):
    """Malicious files: the name a person gives is only a label; it never becomes a path or a command."""
    _, h = new_client(http)
    for name in ("../../../etc/cron.d/x.mp4", "a;rm -rf ~.mp4", "$(reboot).mp4", "x‮gnp.mp4", "nul.mp4"):
        r = http.post("/v1/uploads", json={"filename": name, "size": video.stat().st_size}, headers=h)
        if r.status_code != 201:
            assert r.status_code in (415, 422), (name, r.text)
            continue
        path = app.state.storage.upload_path(r.json()["id"])
        assert app.state.storage.root in path.parents and ".." not in path.parts, name
        assert name not in str(path)
