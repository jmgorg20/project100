"""The worker agent against a real HTTP server (uvicorn on a free port), with a fast stand-in engine:
signatures, inputs, the engine command line, results without local paths, cancel, time limit,
errors, a lost worker, and one end to end run with the real engine on a generated video."""

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import requests
import uvicorn

from service import security
from service.api import create_app
from service.worker import Agent, WorkerError
from tests.service.helpers import ADMIN, make_video, sha

FAKE = [sys.executable, str(Path(__file__).with_name("fake_engine.py"))]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, settings):
        port = free_port()
        settings.public_url = f"http://127.0.0.1:{port}"
        self.app = create_app(settings)
        self.url = settings.public_url
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(10)


@pytest.fixture
def server(settings):
    settings.lease_seconds = 15
    settings.claim_wait_seconds = 1
    with Server(settings) as s:
        yield s


def api(server, method, path, key=ADMIN, **kw):
    r = requests.request(method, server.url + path, headers={"Authorization": f"Bearer {key}"}, timeout=60, **kw)
    return r


def setup_job(server, video, **job):
    r = api(server, "POST", "/v1/admin/clients", json={"name": "c", "concurrent_jobs": 5})
    key = r.json()["api_key"]
    data = video.read_bytes()
    up = api(server, "POST", "/v1/uploads", key, json={"filename": "talk.mp4", "size": len(data), "sha256": sha(data)}).json()
    step = 64 * 1024
    for off in range(0, len(data), step):
        assert api(server, "PUT", f"/v1/uploads/{up['id']}/chunk", key, params={"offset": off},
                   data=data[off:off + step]).status_code == 200
    assert api(server, "POST", f"/v1/uploads/{up['id']}/complete", key).status_code == 200
    body = {"kind": "polish", "inputs": {"main": [up["id"]]}, "preset": "podcast_clips", **job}
    j = api(server, "POST", "/v1/jobs", key, json=body)
    assert j.status_code == 201, j.text
    w = api(server, "POST", "/v1/admin/workers", json={"name": "pc", "queues": ["cpu"]}).json()
    return key, up, j.json(), w


def agent(server, w, tmp_path, monkeypatch, mode="ok", engine=FAKE, config=None):
    monkeypatch.setenv("AUTOEDIT_FAKE_ENGINE_MODE", mode)
    monkeypatch.setenv("AUTOEDIT_ENGINE_VERSION", "test-1")
    return Agent(server.url, w["token"], w["public_key"], ["cpu"], tmp_path / "work", config=config,
                 allow_http=True, wait=1, log=lambda *a: None, engine_cmd=engine)


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("v") / "talk.mp4")


def job_view(server, key, jid):
    return api(server, "GET", f"/v1/jobs/{jid}", key).json()


def test_http_only_with_permission():
    with pytest.raises(WorkerError, match="https"):
        Agent("http://example.com", "wk_x", "pem", log=lambda *a: None)


def test_a_job_runs_and_no_local_path_leaves_the_worker(server, video, tmp_path, monkeypatch):
    log = tmp_path / "argv.json"
    monkeypatch.setenv("AUTOEDIT_FAKE_ENGINE_LOG", str(log))
    key, up, job, w = setup_job(server, video, instruction="--evil; rm -rf / $(whoami)", items=["-x", "Una"])
    a = agent(server, w, tmp_path, monkeypatch)
    assert a.run_once() == job["id"]
    argv = json.loads(log.read_text())
    assert "--instruction=--evil; rm -rf / $(whoami)" in argv            # one argument, never a shell
    assert "--item=-x" in argv and "--preset=podcast_clips" in argv
    view = job_view(server, key, job["id"])
    assert view["status"] == "succeeded" and view["result"]["status"] == "ok"
    names = {o["name"] for o in view["outputs"]}
    assert names == {"video", "project", "plan", "sidecar"}
    for o in view["outputs"]:
        body = requests.get(o["url"], timeout=30).content
        if o["name"] in ("project", "sidecar", "plan"):
            text = body.decode()
            assert str(tmp_path) not in text and "/tmp" not in text and "\\\\" not in text, text[:300]
        if o["name"] == "project":
            assert json.loads(body)["media"][0]["path"] == f"upload:{up['id']}"
        if o["name"] == "video":
            assert body == video.read_bytes()
    assert not list((tmp_path / "work").glob("job_*"))                    # the job folder is gone
    usage = api(server, "GET", "/v1/usage", key).json()["usage"]
    assert usage["jobs"] == 1 and usage["transcription_usd"] == pytest.approx(0.002)


def test_a_project_pointing_elsewhere_is_not_sent(server, video, tmp_path, monkeypatch):
    key, up, job, w = setup_job(server, video)
    agent(server, w, tmp_path, monkeypatch, mode="leak").run_once()
    project = next(o for o in job_view(server, key, job["id"])["outputs"] if o["name"] == "project")
    media = json.loads(requests.get(project["url"], timeout=30).content)["media"][0]["path"]
    assert media == "missing:private.mp4"


def test_a_render_job_uses_earlier_results(server, video, tmp_path, monkeypatch):
    key, up, job, w = setup_job(server, video)
    a = agent(server, w, tmp_path, monkeypatch)
    a.run_once()
    view = job_view(server, key, job["id"])
    project = json.loads(requests.get(next(o for o in view["outputs"] if o["name"] == "project")["url"], timeout=30).content)
    video_out = next(o for o in view["outputs"] if o["name"] == "video")
    project["media"][0]["path"] = f"output:{video_out['id']}"
    r = api(server, "POST", "/v1/jobs", key, json={"kind": "render", "project": project, "export": {"height": 4000}})
    assert r.status_code == 400 and "export.height" in r.text
    export = {"height": 1280, "fps": 25, "quality": "small"}                 # the web app's export choices
    r = api(server, "POST", "/v1/jobs", key, json={"kind": "render", "project": project, "export": export})
    assert r.status_code == 201, r.text
    monkeypatch.setenv("AUTOEDIT_FAKE_ENGINE_LOG", str(tmp_path / "argv.json"))
    assert a.run_once() == r.json()["id"]
    done = job_view(server, key, r.json()["id"])
    assert done["status"] == "succeeded" and [o["name"] for o in done["outputs"]] == ["video"]
    argv = json.loads((tmp_path / "argv.json").read_text())
    assert argv[-4:] == ["--height=1280", "--fps=25", "--crf=26", "--speed=fast"]


def test_cancel_stops_the_engine(server, video, tmp_path, monkeypatch):
    key, up, job, w = setup_job(server, video)
    a = agent(server, w, tmp_path, monkeypatch, mode="sleep")
    t = threading.Thread(target=a.run_once)
    t.start()
    for _ in range(100):
        if job_view(server, key, job["id"])["status"] == "running":
            break
        time.sleep(0.1)
    assert api(server, "POST", f"/v1/jobs/{job['id']}/cancel", key).status_code == 200
    t.join(60)
    assert not t.is_alive()
    assert job_view(server, key, job["id"])["status"] == "cancelled"


def test_time_limit_and_engine_errors(server, video, tmp_path, monkeypatch):
    key, up, job, w = setup_job(server, video)
    with server.app.state.db.tx() as t:
        t.run("UPDATE jobs SET timeout_seconds = 2, max_attempts = 1 WHERE id = ?", (job["id"],))
    agent(server, w, tmp_path, monkeypatch, mode="sleep").run_once()
    v = job_view(server, key, job["id"])
    assert v["status"] == "failed" and "time limit" in v["error"]
    key2, up2, job2, w2 = setup_job(server, video)
    agent(server, w2, tmp_path, monkeypatch, mode="error").run_once()
    v = job_view(server, key2, job2["id"])
    assert v["status"] == "failed" and v["error"] == "The video has no sound." and v["attempts"] == 1   # not retried


def test_a_crash_is_retried_on_another_worker(server, video, tmp_path, monkeypatch):
    key, up, job, w = setup_job(server, video)
    agent(server, w, tmp_path, monkeypatch, mode="crash").run_once()
    v = job_view(server, key, job["id"])
    assert v["status"] == "queued" and "without a result" in v["error"]
    with server.app.state.db.tx() as t:
        t.run("UPDATE jobs SET not_before = 0 WHERE id = ?", (job["id"],))
    w2 = api(server, "POST", "/v1/admin/workers", json={"name": "pc2", "queues": ["cpu"]}).json()
    agent(server, w2, tmp_path, monkeypatch).run_once()
    assert job_view(server, key, job["id"])["status"] == "succeeded"


def test_jobs_without_the_service_signature_are_refused(server, video, tmp_path, monkeypatch):
    key, up, job, w = setup_job(server, video)
    other_key = security.public_key_pem(security.load_signing_key(security.new_signing_key()))
    a = Agent(server.url, w["token"], other_key, ["cpu"], tmp_path / "work", allow_http=True, wait=1,
              log=lambda *x: None, engine_cmd=FAKE)
    with pytest.raises(WorkerError, match="signature"):
        a.run_once()
    revoked = api(server, "DELETE", f"/v1/admin/workers/{w['id']}")
    assert revoked.status_code == 204
    with pytest.raises(WorkerError, match="refused"):
        agent(server, w, tmp_path, monkeypatch).run_once()


# ---------------------------------------------------------------- the real engine, end to end

def test_end_to_end_with_the_real_engine(server, tmp_path, monkeypatch):
    """Upload a generated talking video, polish it with the real engine through the worker, download
    and check the result; then fix a caption and render the project again."""
    from autoedit.cache import Cache
    from autoedit.words import load_transcript, save_transcript
    from tests import synthetic
    talk = synthetic.make_video(tmp_path / "talk.mp4")
    transcript = synthetic.make_transcript(tmp_path / "talk.json")
    cache = Cache(tmp_path / "cache")                     # the worker's transcript cache (no network here)
    entry = cache.folder / "transcripts" / f"{cache.fingerprint(talk)}-groq-whisper-large-v3-tl-taglish1.json"
    entry.parent.mkdir(parents=True, exist_ok=True)
    save_transcript(load_transcript(transcript), entry)
    cfg = tmp_path / "worker.yaml"
    cfg.write_text(f"work_folder: '{(tmp_path / 'ework').as_posix()}'\n"
                   f"output: {{folder: '{(tmp_path / 'eout').as_posix()}', encoder_speed: ultrafast}}\n"
                   f"ai: {{cache_folder: '{(tmp_path / 'cache').as_posix()}'}}\n"
                   f"overlays: {{triggers_file: '{(tmp_path / 'none.yaml').as_posix()}'}}\n", encoding="utf-8")
    for k in ("GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "")
    key, up, job, w = setup_job(server, talk)
    a = agent(server, w, tmp_path, monkeypatch, engine=[sys.executable, str(Path(__file__).parents[2] / "editor.py")],
              config=cfg)
    logs = []
    a.log = logs.append
    assert a.run_once() == job["id"]
    view = job_view(server, key, job["id"])
    assert view.get("status") == "succeeded", (view, logs)
    assert view["result"]["status"] in ("ok", "warnings") and view["result"]["qc"]["passed"]
    out = {o["name"]: o for o in view["outputs"]}
    assert {"video", "project", "sidecar"} <= set(out)
    mp4 = tmp_path / "result.mp4"
    mp4.write_bytes(requests.get(out["video"]["url"], timeout=60).content)
    from autoedit.qc import ffprobe
    info, _ = ffprobe(mp4)
    vs = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (vs["width"], vs["height"]) == (1080, 1920)
    project = json.loads(requests.get(out["project"]["url"], timeout=60).content)
    paths = [m["path"] for m in project["media"]]
    assert f"upload:{up['id']}" in paths and all(p.split(":")[0] in ("upload", "output") for p in paths), paths
    for t in project["tracks"]:                          # fix a caption, then render again
        for c in t["clips"]:
            if c.get("type") == "caption":
                c["words"][0]["text"] = "Kumusta!"
                break
    r = api(server, "POST", "/v1/jobs", key, json={"kind": "render", "project": project})
    assert r.status_code == 201, r.text
    assert a.run_once() == r.json()["id"]
    again = job_view(server, key, r.json()["id"])
    assert again["status"] == "succeeded", again


def test_a_clients_own_preset_reaches_the_engine(server, video, tmp_path, monkeypatch):
    import yaml
    from autoedit import presets
    log = tmp_path / "argv.json"
    monkeypatch.setenv("AUTOEDIT_FAKE_ENGINE_LOG", str(log))
    key, up, job, w = setup_job(server, video)
    mine = {k: v for k, v in presets.get("meme", {"presets_folder": ""}).items() if k != "builtin"}
    mine.update({"id": "jgg_promo", "name": "JGG promo"})
    assert api(server, "PUT", "/v1/presets/jgg_promo", key, json=mine).status_code == 200
    j = api(server, "POST", "/v1/jobs", key, json={"inputs": {"main": [up["id"]]}, "preset": "jgg_promo"}).json()
    base = tmp_path / "base.yaml"
    base.write_text("output: {encoder_speed: ultrafast}\n")
    a = agent(server, w, tmp_path, monkeypatch, config=base)
    seen = {}
    real = a.job_config

    def spy(folder, params):
        path = real(folder, params)
        if not params.get("preset_body"):
            return path
        seen["cfg"] = yaml.safe_load(path.read_text())
        seen["preset"] = json.loads((Path(seen["cfg"]["presets_folder"]) / "jgg_promo.json").read_text())
        return path
    a.job_config = spy
    assert a.run_once() == job["id"]               # the first job (no preset of its own)
    assert job_view(server, key, job["id"])["status"] == "succeeded"
    assert a.run_once() == j["id"]
    assert seen["cfg"]["output"]["encoder_speed"] == "ultrafast" and seen["preset"]["name"] == "JGG promo"
    assert "--preset=jgg_promo" in json.loads(log.read_text())

