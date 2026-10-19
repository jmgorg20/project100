"""End to end in containers: Postgres + the API image + the worker image (the real engine) polish a
generated talking video. Opt-in, because it needs Docker and the images:

    docker build -f deploy/Dockerfile.api -t autoedit-api:test .
    docker build -f deploy/Dockerfile.worker -t autoedit-worker:test .
    AUTOEDIT_CONTAINER_TEST=1 python -m pytest tests/service/test_containers.py

AUTOEDIT_TEST_POSTGRES_IMAGE picks the Postgres image (default postgres:16).
"""

import json
import os
import shutil
import socket
import subprocess
import time
import uuid

import pytest
import requests

from service import security
from tests.service.helpers import sha

pytestmark = pytest.mark.skipif(os.environ.get("AUTOEDIT_CONTAINER_TEST") != "1",
                                reason="container test is opt-in: AUTOEDIT_CONTAINER_TEST=1 (needs Docker + images)")
ADMIN = "c" * 48
SECRET = "s" * 48


def docker(*args, check=True, timeout=600):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=check)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def stack(tmp_path):
    tag = uuid.uuid4().hex[:8]
    net, db, api = f"ae-net-{tag}", f"ae-db-{tag}", f"ae-api-{tag}"
    keys = tmp_path / "keys"
    keys.mkdir()
    pem = security.new_signing_key()
    (keys / "signing-key.pem").write_text(pem)
    (keys / "signing-key.pem.pub").write_text(security.public_key_pem(security.load_signing_key(pem)))
    os.chmod(keys / "signing-key.pem", 0o644)                  # readable by the container's app user
    port = free_port()
    docker("network", "create", net)
    started = []
    try:
        init = os.path.join(os.path.dirname(__file__), "..", "..", "deploy", "postgres-init.sh")
        docker("run", "-d", "--name", db, "--network", net, "-e", "POSTGRES_PASSWORD=pw", "-e", "POSTGRES_USER=ae",
               "-e", "POSTGRES_DB=ae", "-e", "APP_DB_PASSWORD=apppw",
               "-v", f"{os.path.abspath(init)}:/docker-entrypoint-initdb.d/10-app-role.sh:ro",
               os.environ.get("AUTOEDIT_TEST_POSTGRES_IMAGE", "postgres:16"))
        started.append(db)
        for _ in range(60):
            ready = docker("exec", db, "psql", "-h", "127.0.0.1", "-U", "ae", "-d", "ae", "-tAc",   # TCP: after init
                           "SELECT 1 FROM pg_roles WHERE rolname = 'autoedit_app'", check=False)
            if ready.returncode == 0 and ready.stdout.strip() == "1":
                break
            time.sleep(1)
        docker("run", "-d", "--name", api, "--network", net, "-p", f"127.0.0.1:{port}:8787", "--read-only",
               "--tmpfs", "/tmp", "--tmpfs", "/data:uid=999,gid=999", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
               "-e", "SERVICE_ENV=development", "-e", "SERVICE_DATABASE_URL=postgresql://autoedit_app:apppw@" + db + ":5432/ae",
               "-e", "SERVICE_REQUIRE_RLS=true",
               "-e", f"SERVICE_SECRET_KEY={SECRET}", "-e", f"SERVICE_ADMIN_TOKEN={ADMIN}",
               "-e", "SERVICE_SIGNING_KEY_FILE=/keys/signing-key.pem", "-e", f"SERVICE_PUBLIC_URL=http://127.0.0.1:{port}",
               "-e", "SERVICE_LEASE_SECONDS=60", "-v", f"{keys}:/keys:ro", "autoedit-api:test")
        started.append(api)
        url = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                if requests.get(url + "/readyz", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            logs = docker("logs", api, check=False)
            raise RuntimeError((logs.stdout + logs.stderr)[-3000:])
        yield {"url": url, "net": net, "api": api, "keys": keys, "tmp": tmp_path, "started": started}
    finally:
        for name in started:
            docker("rm", "-f", name, check=False)
        docker("network", "rm", net, check=False)


def call(stack, method, path, key=ADMIN, **kw):
    return requests.request(method, stack["url"] + path, headers={"Authorization": f"Bearer {key}"}, timeout=120, **kw)


def test_the_service_user_is_held_by_row_level_security(stack):
    assert requests.get(stack["url"] + "/readyz", timeout=10).json()["rls"] == "enforced"


def test_the_web_app_is_served(stack):
    r = requests.get(stack["url"] + "/app/", timeout=10)
    assert r.status_code == 200 and '<div id="root">' in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    sw = requests.get(stack["url"] + "/app/sw.js", timeout=10)
    assert sw.status_code == 200 and sw.headers["content-type"].startswith("text/javascript")


def test_polish_in_containers(stack):
    from autoedit.cache import Cache
    from autoedit.words import load_transcript, save_transcript
    from tests import synthetic
    tmp = stack["tmp"]
    talk = synthetic.make_video(tmp / "talk.mp4")
    work = tmp / "work"
    cache = Cache(work / "cache")                            # the worker has no network: a saved transcript
    entry = cache.folder / "transcripts" / f"{cache.fingerprint(talk)}-groq-whisper-large-v3-tl-taglish1.json"
    entry.parent.mkdir(parents=True, exist_ok=True)
    save_transcript(load_transcript(synthetic.make_transcript(tmp / "talk.json")), entry)
    for p in [work, *work.rglob("*")]:
        os.chmod(p, 0o777 if p.is_dir() else 0o666)

    client = call(stack, "POST", "/v1/admin/clients", json={"name": "JGG CITY"}).json()
    key = client["api_key"]
    data = talk.read_bytes()
    up = call(stack, "POST", "/v1/uploads", key, json={"filename": "talk.mp4", "size": len(data), "sha256": sha(data)}).json()
    for off in range(0, len(data), 1 << 20):
        assert call(stack, "PUT", f"/v1/uploads/{up['id']}/chunk", key, params={"offset": off},
                    data=data[off:off + (1 << 20)]).status_code == 200
    assert call(stack, "POST", f"/v1/uploads/{up['id']}/complete", key).json()["status"] == "ready"
    job = call(stack, "POST", "/v1/jobs", key, json={"inputs": {"main": [up["id"]]}, "preset": "podcast_clips"}).json()
    worker = call(stack, "POST", "/v1/admin/workers", json={"name": "cpu-1", "queues": ["cpu"]}).json()

    name = f"ae-worker-{uuid.uuid4().hex[:8]}"
    stack["started"].append(name)
    run = docker("run", "--name", name, "--network", stack["net"], "--read-only", "--tmpfs", "/tmp",
                 "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "-v", f"{work}:/work",
                 "-v", f"{stack['keys']}:/keys:ro", "-e", f"AUTOEDIT_SERVER=http://{stack['api']}:8787",
                 "-e", f"AUTOEDIT_WORKER_TOKEN={worker['token']}", "-e", "AUTOEDIT_SERVICE_PUBLIC_KEY=/keys/signing-key.pem.pub",
                 "-e", "AUTOEDIT_ENGINE_VERSION=container-test", "-e", "GROQ_API_KEY=",
                 "autoedit-worker:test", "python", "editor.py", "worker", "--once", "--allow-http",
                 "--work-dir", "/work/jobs", "--config", "/app/deploy/worker.yaml", check=False, timeout=1200)
    view = call(stack, "GET", f"/v1/jobs/{job['id']}", key).json()
    assert view["status"] == "succeeded", (view, run.stdout[-3000:], run.stderr[-3000:])
    assert view["result"]["qc"]["passed"]
    video = next(o for o in view["outputs"] if o["name"] == "video")
    out = tmp / "result.mp4"
    out.write_bytes(requests.get(video["url"], timeout=120).content)
    probe = json.loads(subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_streams", "-print_format", "json",
                                       str(out)], capture_output=True, text=True, check=True).stdout)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert not list((work / "jobs").glob("job_*"))           # the worker cleaned up after itself
