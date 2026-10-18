"""Helpers for the service API tests."""

import hashlib
import subprocess

ADMIN = "a" * 40


def make_video(path, seconds=2.0, size="360x640", audio=True):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f=330:r=48000:d={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path


def admin(client):
    return {"Authorization": f"Bearer {ADMIN}"}


def new_client(http, name="Client", **limits):
    r = http.post("/v1/admin/clients", json={"name": name, **limits}, headers=admin(http))
    assert r.status_code == 201, r.text
    return r.json()["client"], {"Authorization": f"Bearer {r.json()['api_key']}"}


def upload(http, headers, path, filename=None, chunk=None, sha=True):
    data = path.read_bytes() if hasattr(path, "read_bytes") else path
    body = {"filename": filename or getattr(path, "name", "file.mp4"), "size": len(data)}
    if sha:
        body["sha256"] = hashlib.sha256(data).hexdigest()
    r = http.post("/v1/uploads", json=body, headers=headers)
    assert r.status_code == 201, r.text
    up = r.json()
    step = chunk or up["chunk_size"]
    for offset in range(0, len(data), step):
        r = http.put(f"/v1/uploads/{up['id']}/chunk", params={"offset": offset}, content=data[offset:offset + step],
                     headers=headers)
        assert r.status_code == 200, r.text
    return http.post(f"/v1/uploads/{up['id']}/complete", headers=headers)


def ready_upload(http, headers, path, **kw):
    r = upload(http, headers, path, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def new_worker(http, queues=("cpu",), channel="stable"):
    r = http.post("/v1/admin/workers", json={"name": "w", "queues": list(queues), "channel": channel}, headers=admin(http))
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()


def sha(data):
    return hashlib.sha256(data).hexdigest()
