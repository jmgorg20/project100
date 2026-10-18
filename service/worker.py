"""The worker agent: `python editor.py worker --server https://api.example.com --token wk_... --public-key service.pub`.

It connects OUT to the service over HTTPS and pulls jobs: the owner's Windows PC (WanGP / ComfyUI),
a cloud GPU box or a CPU server never needs an open inbound port or a VPN.

For each job:
  1. the job payload's signature is checked with the service's public key (a job the service did
     not sign is never run, even if someone took over the connection);
  2. the inputs are downloaded into a fresh private folder and their checksums checked;
  3. the engine runs as a separate process (`editor.py polish` / `render`): no shell, a fixed list of
     arguments, user text only as argument values, a minimal environment, a time limit, and stdin
     open so that closing it (worker stopped, job cancelled) stops the engine and its FFmpeg;
  4. a heartbeat keeps the job's lease and brings back the client's cancel;
  5. the results are uploaded with checksums; local paths are never sent; the folder is deleted.
If this worker disappears, the service gives the job to another worker when the lease runs out.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import security
from .media import AUDIO, IMAGE, PROJECT, VIDEO

PROJECT_DIR = Path(__file__).resolve().parent.parent
SAFE_EXT = VIDEO | IMAGE | AUDIO | PROJECT
ENV_PASS = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL",
            "PYTHONIOENCODING", "PLAYWRIGHT_BROWSERS_PATH", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA")
ENV_PREFIXES = ("AUTOEDIT_", "GROQ_", "ANTHROPIC_", "PEXELS_", "PIXABAY_", "WANGP_", "COMFYUI_")


RESULT_KEYS = ("status", "qc", "retries", "opinions", "preset", "format", "instruction", "cost", "seconds",
               "error", "started", "finished", "version", "tool")


def scrub(value, folders):
    """`value` with every mention of these folders replaced by "<worker>" (JSON round trip)."""
    text = json.dumps(value, ensure_ascii=False)
    for folder in folders:
        for form in {str(folder), str(Path(folder).resolve()), str(folder).replace("\\", "/")}:
            if form and len(form) > 3:
                text = text.replace(json.dumps(form)[1:-1], "<worker>")
    return json.loads(text)


class WorkerError(Exception):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def engine_version():
    """The engine version this worker runs: AUTOEDIT_ENGINE_VERSION, else the git commit."""
    if os.environ.get("AUTOEDIT_ENGINE_VERSION"):
        return os.environ["AUTOEDIT_ENGINE_VERSION"]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=PROJECT_DIR, capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def child_cpu_seconds():
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_CHILDREN)
        return r.ru_utime + r.ru_stime
    except (ImportError, AttributeError):          # Windows: not available (wall time is reported)
        return None


class Agent:
    def __init__(self, server, token, public_key_pem, queues=("cpu",), work_dir=None, config=None, http=None,
                 allow_http=False, wait=20, log=print, engine_cmd=None):
        server = server.rstrip("/")
        if not server.startswith("https://") and not allow_http:
            raise WorkerError("The service address must start with https:// (or use --allow-http for local tests).",
                              retryable=False)
        self.server, self.token, self.public_key = server, token, public_key_pem
        self.queues, self.wait, self.log = list(queues), wait, log
        self.work_dir = Path(work_dir or Path(tempfile.gettempdir()) / "autoedit-worker")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.version = engine_version()
        self.engine_cmd = engine_cmd or [sys.executable, str(PROJECT_DIR / "editor.py")]
        if http is None:
            import requests
            http = requests.Session()
        self.http = http
        self.http.headers.update({"Authorization": f"Bearer {token}", "User-Agent": f"AutoEditWorker/{self.version}"})
        self.cleanup_stale()

    # ---------------------------------------------------------- talking to the service
    def url(self, path):
        return f"{self.server}{path}"

    def call(self, method, path, **kw):
        kw.setdefault("timeout", 60)
        r = self.http.request(method, self.url(path), **kw)
        if r.status_code == 401:
            raise WorkerError("The worker token was refused (revoked?).", retryable=False)
        return r

    def cleanup_stale(self):
        """Folders left by a crash (older than a day) are removed at start."""
        for p in self.work_dir.glob("job_*"):
            try:
                if time.time() - p.stat().st_mtime > 86400:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass

    def claim(self):
        r = self.call("POST", "/v1/worker/claim", json={"engine_version": self.version, "queues": self.queues,
                                                        "wait": self.wait}, timeout=self.wait + 30)
        if r.status_code == 204:
            return None
        if r.status_code != 200:
            raise WorkerError(f"claim failed: HTTP {r.status_code} {r.text[:200]}")
        data = r.json()
        payload, signature = data.get("payload"), data.get("signature")
        if not payload or not signature or not security.verify_payload(self.public_key, payload, signature):
            raise WorkerError("A job arrived without a valid service signature; it was not run.", retryable=False)
        if not re.fullmatch(r"job_[0-9a-f]{24}", str(payload.get("job_id"))):
            raise WorkerError("A job with a bad id arrived; it was not run.", retryable=False)
        if abs(time.time() - int(payload.get("issued_at", 0))) > 600:
            raise WorkerError("A stale job payload arrived (clock or replay); it was not run.", retryable=False)
        return payload

    # ---------------------------------------------------------- one job
    def run_once(self):
        """Claim and process one job. Returns the job id, or None when there was none."""
        try:
            payload = self.claim()
        except WorkerError as exc:
            if not exc.retryable:
                raise
            self.log(f"! {exc}")
            return None
        if payload is None:
            return None
        self.process(payload)
        return payload["job_id"]

    def process(self, payload):
        job_id = payload["job_id"]
        folder = Path(tempfile.mkdtemp(prefix=f"{job_id}-", dir=self.work_dir))
        state = {"stage": "starting", "progress": 0.0, "cancel": False, "message": ""}
        stop = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(job_id, state, stop, payload), daemon=True)
        beat.start()
        started, cpu0 = time.time(), child_cpu_seconds()
        try:
            self.log(f"> job {job_id} ({payload['kind']}, attempt {payload.get('attempt')})")
            local = self.download_inputs(payload, folder)
            result, files = self.run_engine(payload, folder, local, state)
            if state["cancel"]:
                raise WorkerError("Cancelled by the client.", retryable=False)
            # never send local paths: only known sidecar fields, and any path of this machine is hidden
            result = scrub({k: v for k, v in result.items() if k in RESULT_KEYS}, [folder, self.work_dir, PROJECT_DIR])
            if files.get("sidecar"):
                public = folder / "sidecar.public.json"
                public.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                files["sidecar"] = str(public)
            uploaded = self.upload_outputs(job_id, files, local, payload, [folder, self.work_dir, PROJECT_DIR])
            cpu1 = child_cpu_seconds()
            wall = time.time() - started
            checks = {c.get("id"): c for c in (result.get("qc") or {}).get("checks", []) if isinstance(c, dict)}
            usage = {"wall_seconds": round(wall, 2),
                     # Windows has no per-child CPU time: the wall time is reported instead
                     "cpu_seconds": round(cpu1 - cpu0, 2) if cpu0 is not None and cpu1 is not None else round(wall, 2),
                     # a GPU job holds the GPU for its whole run
                     "gpu_seconds": round(wall, 2) if payload.get("queue") == "gpu" else 0.0,
                     "output_seconds": ((checks.get("duration") or {}).get("details") or {}).get("seconds")}
            result["outputs"] = uploaded
            r = self.call("POST", f"/v1/worker/jobs/{job_id}/complete", json={"result": result, "usage": usage})
            if r.status_code != 200:
                raise WorkerError(f"The service did not take the result: HTTP {r.status_code} {r.text[:200]}")
            self.log(f"< job {job_id}: {result.get('status')}")
        except WorkerError as exc:
            self._fail(job_id, str(exc), exc.retryable and not state["cancel"])
        except Exception as exc:                          # a bug or a network error: try again elsewhere
            self._fail(job_id, f"Worker error: {exc.__class__.__name__}: {exc}", True)
        finally:
            stop.set()
            beat.join(5)
            shutil.rmtree(folder, ignore_errors=True)

    def _fail(self, job_id, message, retryable):
        self.log(f"! job {job_id}: {message}")
        try:
            self.call("POST", f"/v1/worker/jobs/{job_id}/fail", json={"error": message[:2000], "retryable": retryable})
        except Exception as exc:
            self.log(f"! could not report the failure ({exc}); the lease will run out and the job will be retried")

    def _heartbeat(self, job_id, state, stop, payload):
        every = max(5, int(payload.get("lease_seconds", 120)) // 3)
        while not stop.wait(every):
            try:
                r = self.call("POST", f"/v1/worker/jobs/{job_id}/heartbeat",
                              json={"progress": state["progress"], "stage": state["stage"], "message": state["message"]},
                              timeout=30)
                if r.status_code == 200 and r.json().get("cancel"):
                    state["cancel"] = True
                elif r.status_code == 409:                # the job was taken away (lease ran out)
                    state["cancel"] = True
            except Exception:
                pass

    # ---------------------------------------------------------- files
    def download_inputs(self, payload, folder):
        """{upload_id or output_id: local path}"""
        inputs_dir = folder / "inputs"
        inputs_dir.mkdir()
        local = {}
        for uid, info in (payload.get("files") or {}).items():
            ext = Path(str(info.get("filename", ""))).suffix.lower()
            path = inputs_dir / f"{uid}{ext if ext in SAFE_EXT else '.bin'}"
            self._download(f"/v1/worker/jobs/{payload['job_id']}/inputs/{uid}", path, info.get("sha256"))
            local[uid] = path
        for oid, info in (payload.get("outputs") or {}).items():
            m = re.search(r"(\.[a-z0-9]{1,5})$", str(info.get("name", "")))
            path = inputs_dir / f"{oid}{m.group(1) if m and m.group(1) in SAFE_EXT else '.bin'}"
            self._download(f"/v1/worker/jobs/{payload['job_id']}/media/{oid}", path, info.get("sha256"))
            local[oid] = path
        return local

    def _download(self, path, dest, sha):
        with self.call("GET", path, stream=True, timeout=300) as r:
            if r.status_code != 200:
                raise WorkerError(f"Could not get an input file (HTTP {r.status_code}).", retryable=r.status_code >= 500)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        if sha and sha256_of(dest) != sha:
            raise WorkerError("An input file arrived damaged (checksum); will try again.")

    def upload_outputs(self, job_id, files, local, payload, folders=()):
        """Upload the result files. The project's media paths become references the service knows
        (upload:<id> for the client's files, output:<id> for files made here), never local paths."""
        sent = {}
        project = files.get("project")
        if project is not None:
            data = json.loads(Path(project).read_text(encoding="utf-8"))
            by_path = {str(Path(p).resolve()): f"upload:{uid}" if uid.startswith("up_") else f"output:{uid}"
                       for uid, p in local.items()}
            n = 0
            for m in data.get("media", []):
                p = str(Path(m.get("path", "")).resolve())
                if p in by_path:
                    m["path"] = by_path[p]
                elif Path(p).exists() and n < 200:
                    ext = Path(p).suffix.lower()
                    name = f"asset-{n}{ext if ext in SAFE_EXT else ''}"
                    out = self._upload(job_id, name, Path(p))
                    m["path"] = f"output:{out['id']}"
                    n += 1
                else:
                    m["path"] = f"missing:{Path(p).name}"
            project = Path(project).with_name("project.public.json")
            project.write_text(json.dumps(scrub(data, folders), ensure_ascii=False), encoding="utf-8")
            files = {**files, "project": project}
        if files.get("plan") and Path(files["plan"]).exists():
            plan = Path(files["plan"]).with_name("plan.public.json")
            plan.write_text(json.dumps(scrub(json.loads(Path(files["plan"]).read_text(encoding="utf-8")), folders),
                                       ensure_ascii=False), encoding="utf-8")
            files = {**files, "plan": plan}
        for name in ("video", "project", "plan", "sidecar"):
            if files.get(name) is not None and Path(files[name]).exists():
                sent[name] = self._upload(job_id, name, Path(files[name]))["id"]
        return sent

    def _upload(self, job_id, name, path):
        digest = sha256_of(path)
        for attempt in range(3):
            with open(path, "rb") as f:
                r = self.call("PUT", f"/v1/worker/jobs/{job_id}/outputs/{name}", params={"sha256": digest}, data=f,
                              timeout=600)
            if r.status_code == 200:
                return r.json()
            if r.status_code < 500 and r.status_code != 422:
                raise WorkerError(f"The service refused the result {name}: HTTP {r.status_code} {r.text[:200]}")
            time.sleep(2 * (attempt + 1))
        raise WorkerError(f"Could not upload the result {name}.")

    # ---------------------------------------------------------- the engine
    def engine_env(self):
        env = {k: v for k, v in os.environ.items() if k in ENV_PASS or k.startswith(ENV_PREFIXES)}
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def command(self, payload, folder, local):
        p = payload.get("params") or {}
        out = folder / "out"
        base = list(self.engine_cmd) + ["--json", "--stdin-control"]
        config = self.job_config(folder, p)
        if config:
            base += ["--config", str(config)]
        if payload["kind"] == "polish":
            inputs = payload["inputs"]
            main = local[inputs["main"][0]]
            cmd = base + ["polish", str(main), "--out", str(out)]
            for flag, value in (("--preset", p.get("preset")), ("--format", p.get("format")),
                                ("--provider", p.get("provider"))):
                if value:
                    cmd.append(f"{flag}={value}")
            if p.get("instruction"):
                cmd.append(f"--instruction={p['instruction']}")
            for role, ids in inputs.items():
                if role in ("main", "photos"):
                    continue
                for uid in ids:
                    cmd.append(f"--input={role}={local[uid]}")
            for uid in inputs.get("photos", []):
                cmd.append(f"--input=photos={local[uid]}")
            for item in p.get("items") or []:
                cmd.append(f"--item={item}")
            for role, seconds in (p.get("offsets") or {}).items():
                cmd.append(f"--offset={role}={float(seconds)}")
            if p.get("qc") is False:
                cmd.append("--no-qc")
            if p.get("retry") is False:
                cmd.append("--no-retry")
            return cmd, out
        project = json.loads(json.dumps(p["project"]))
        for m in project.get("media", []):
            kind, _, rid = str(m.get("path", "")).partition(":")
            if kind in ("upload", "output") and rid in local:
                m["path"] = str(local[rid])
            else:
                raise WorkerError(f"The project refers to a file that is not available: {m.get('path')}", retryable=False)
        out.mkdir()
        pfile = folder / "project.json"
        pfile.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
        cmd = base + ["render", str(pfile), "--output", str(out / "video.mp4")]
        export = p.get("export") or {}
        quality = {"high": (18, "medium"), "standard": (21, "medium"), "small": (26, "fast"),
                   "draft": (28, "veryfast")}.get(export.get("quality"))
        if export.get("height") in (1920, 1280, 960):
            cmd.append(f"--height={int(export['height'])}")
        if export.get("fps") in (24, 25, 30, 50, 60):
            cmd.append(f"--fps={int(export['fps'])}")
        if quality:
            cmd += [f"--crf={quality[0]}", f"--speed={quality[1]}"]
        return cmd, out

    def job_config(self, folder, params):
        """The engine config for this job: the worker's own, plus the client's preset if the job
        uses one (written into this job's folder as a presets folder of one file)."""
        body = params.get("preset_body")
        if not body:
            return self.config
        import yaml
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(body.get("id", ""))):
            raise WorkerError("The job's preset has a bad id.", retryable=False)
        presets_dir = folder / "presets"
        presets_dir.mkdir()
        (presets_dir / f"{body['id']}.json").write_text(json.dumps(body), encoding="utf-8")
        cfg = {}
        if self.config:
            cfg = yaml.safe_load(Path(self.config).read_text(encoding="utf-8")) or {}
        cfg["presets_folder"] = str(presets_dir)
        path = folder / "config.yaml"
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        return path

    def run_engine(self, payload, folder, local, state):
        cmd, out = self.command(payload, folder, local)
        timeout = int(payload.get("timeout_seconds") or 2700)
        proc = subprocess.Popen(cmd, cwd=folder, env=self.engine_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        lines, err_tail = [], []
        threading.Thread(target=lambda: err_tail.extend(proc.stderr.read().splitlines()[-40:]), daemon=True).start()
        deadline = time.time() + timeout
        watcher = threading.Thread(target=self._watch, args=(proc, state, deadline), daemon=True)
        watcher.start()
        for raw in proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            lines.append(msg)
            if msg.get("type") == "stage":
                state["stage"], state["message"] = msg.get("stage", ""), msg.get("label", "")
            elif msg.get("type") == "progress" and isinstance(msg.get("percent"), (int, float)):
                state["progress"] = max(0.0, min(0.99, msg["percent"] / 100.0))
        proc.wait()
        if state.get("timed_out"):
            raise WorkerError(f"The job ran past its time limit ({timeout // 60} min).")
        if state["cancel"]:
            raise WorkerError("Cancelled by the client.", retryable=False)
        result = next((m for m in reversed(lines) if m.get("type") == "result"), None)
        error = next((m.get("message") for m in reversed(lines) if m.get("type") == "error"), None)
        if payload["kind"] == "polish":
            if result is None:
                raise WorkerError(error or "The engine stopped without a result: " + " | ".join(err_tail[-3:]),
                                  retryable=error is None)
            files = {"video": result.get("output"), "project": result.get("project"),
                     "plan": str(Path(result["output"]).with_suffix(".plan.json")) if result.get("output") else None}
            side = Path(result["output"]).with_suffix(".json") if result.get("output") else None
            files["sidecar"] = str(side) if side and side.exists() else None
            return {k: v for k, v in result.items() if k != "type"}, files
        if proc.returncode != 0 or not (out / "video.mp4").exists():
            raise WorkerError(error or "The render failed: " + " | ".join(err_tail[-3:]), retryable=error is None)
        return {"status": "ok"}, {"video": str(out / "video.mp4")}

    def _watch(self, proc, state, deadline):
        """Stop the engine on cancel or time limit: close stdin (a clean stop), then terminate."""
        while proc.poll() is None:
            if state["cancel"] or time.time() > deadline:
                state["timed_out"] = not state["cancel"]
                try:
                    proc.stdin.close()
                except OSError:
                    pass
                try:
                    proc.wait(20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return
            time.sleep(0.5)

    # ---------------------------------------------------------- the loop
    def run_forever(self, stop=None):
        stop = stop or threading.Event()
        self.log(f"Worker {self.version} pulling {', '.join(self.queues)} jobs from {self.server}")
        failures = 0
        while not stop.is_set():
            try:
                self.run_once()
                failures = 0
            except WorkerError as exc:
                if not exc.retryable:
                    self.log(f"! {exc}")
                    if "token" in str(exc):
                        return
                failures += 1
            except Exception as exc:                  # the service is unreachable: wait and try again
                failures += 1
                self.log(f"! {exc.__class__.__name__}: {exc}")
            if failures:
                stop.wait(min(60, 2 ** min(failures, 6)))
