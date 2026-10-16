"""Talks to WanGP for the editor. Runs INSIDE WanGP's own Python environment:

    <WanGP python> wangp_bridge.py --root C:\\WanGP [--cli-args '["--profile","4"]']

It uses WanGP's documented Python API (shared/api.py: init, list_model_metadata,
submit_task, job.cancel). It never imports the editor, and the editor never imports WanGP:
they exchange JSON lines (stdin: commands, stdout: replies). Everything WanGP prints goes
to stderr, so stdout carries only JSON.

Commands (one JSON object per line):
  {"cmd": "models"}                                  -> {"type": "models", "models": [...]}
  {"cmd": "generate", "id": "j1", "settings": {...}, "output_dir": "..."}
       -> {"type": "progress", "id": ..., ...} ... {"type": "done", "id": ..., ...}
  {"cmd": "cancel", "id": "j1"}
  {"cmd": "quit"}

A generate request whose model is not fully installed is refused: WanGP would otherwise
download it, and the editor never downloads models.

This product uses WanGP (https://github.com/deepbeepmeep/Wan2GP), subject to its license
and terms.
"""

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from pathlib import Path


class Channel:
    """JSON lines on the original stdout; everything else printed goes to stderr."""

    def __init__(self):
        sys.stdout.flush()
        fd = os.dup(1)
        os.dup2(2, 1)                       # C libraries, prints, banners -> stderr
        self.out = os.fdopen(fd, "w", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()

    def send(self, **data):
        line = json.dumps(data, default=str)
        with self.lock:
            self.out.write(line + "\n")
            self.out.flush()


def wangp_version(session, root):
    try:
        return str(session._ensure_runtime().module.WanGP_version)
    except Exception:
        pass
    try:
        match = re.search(r'WanGP_version\s*=\s*"([^"]+)"',
                          (Path(root) / "wgp.py").read_text(encoding="utf-8", errors="replace"))
        return match.group(1) if match else "unknown"
    except OSError:
        return "unknown"


def http_urls(value):
    if isinstance(value, str):
        return [value] if value.startswith("http") else []
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str) and v.startswith("http")]
    return []


def list_models(session):
    urls = {}
    try:
        for model_def in session.list_model_defs():
            found = http_urls(model_def.get("URLs"))
            if not found and isinstance(model_def.get("model"), dict):
                found = http_urls(model_def["model"].get("URLs"))
            urls[model_def.get("model_type")] = found[:3]
    except Exception:
        traceback.print_exc()
    models = []
    for record in session.list_model_metadata(include_availability=True):
        availability = record.get("availability") or {}
        models.append({
            "model_type": record.get("model_type"),
            "name": record.get("name"),
            "family": record.get("family_label") or record.get("family"),
            "main_output": record.get("main_output") or [],
            "outputs": record.get("outputs") or [],
            "inputs": record.get("inputs") or [],
            "status": availability.get("status", "unknown"),
            "available": bool(availability.get("available")),
            "urls": urls.get(record.get("model_type"), []),
        })
    return models


def run_job(session, channel, request, jobs):
    job_id = request.get("id")
    settings = dict(request.get("settings") or {})
    started = time.time()
    try:
        status = session.get_model_availability(settings.get("model_type", ""))
    except Exception as exc:
        channel.send(type="done", id=job_id, success=False, files=[], cancelled=False,
                     seconds=0.0, errors=[{"message": f"Unknown model: {exc}"}])
        return
    if not status.get("available"):
        channel.send(type="done", id=job_id, success=False, files=[], cancelled=False,
                     seconds=0.0, not_installed=True,
                     errors=[{"message": f"The model {settings.get('model_type')} is not fully "
                                         f"installed ({status.get('status')}). Download it in WanGP "
                                         f"first; the editor never downloads models."}])
        return
    try:
        job = session.submit_task(settings)
    except Exception as exc:
        channel.send(type="done", id=job_id, success=False, files=[], cancelled=False,
                     seconds=time.time() - started, errors=[{"message": str(exc)}])
        return
    jobs[job_id] = job
    try:
        for event in job.events.iter(timeout=0.5):
            if event.kind == "progress":
                p = event.data
                channel.send(type="progress", id=job_id, phase=getattr(p, "phase", ""),
                             status=getattr(p, "status", ""),
                             percent=getattr(p, "progress", None),
                             step=getattr(p, "current_step", None),
                             steps=getattr(p, "total_steps", None))
        result = job.result()
        channel.send(type="done", id=job_id, success=bool(result.success),
                     files=[str(f) for f in result.generated_files],
                     cancelled=bool(getattr(result, "cancelled", False)),
                     seconds=time.time() - started,
                     errors=[{"message": str(e.message), "stage": getattr(e, "stage", None)}
                             for e in result.errors])
    except Exception as exc:
        traceback.print_exc()
        channel.send(type="done", id=job_id, success=False, files=[], cancelled=False,
                     seconds=time.time() - started, errors=[{"message": str(exc)}])
    finally:
        jobs.pop(job_id, None)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--cli-args", default="[]")
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    channel = Channel()
    root = Path(args.root).resolve()
    try:
        sys.path.insert(0, str(root))
        os.chdir(root)
        from shared.api import init
        session = init(root=root, output_dir=args.output_dir, cli_args=json.loads(args.cli_args),
                       console_output=True, console_isatty=False)
    except Exception as exc:
        traceback.print_exc()
        channel.send(type="fatal", message=f"WanGP could not start: {exc}")
        return 2
    channel.send(type="ready", version=wangp_version(session, root))

    work = queue.Queue()
    jobs = {}

    def worker():                          # one GPU job at a time, in arrival order
        while True:
            request = work.get()
            if request is None:
                return
            run_job(session, channel, request, jobs)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            channel.send(type="error", message=f"Not JSON: {line[:100]}")
            continue
        cmd = request.get("cmd")
        if cmd == "models":
            try:
                channel.send(type="models", models=list_models(session))
            except Exception as exc:
                traceback.print_exc()
                channel.send(type="error", message=f"Could not list WanGP models: {exc}")
        elif cmd == "generate":
            work.put(request)
        elif cmd == "cancel":
            job = jobs.get(request.get("id"))
            if job is not None:
                job.cancel()
        elif cmd == "quit":
            break
    for job in list(jobs.values()):
        job.cancel()
    work.put(None)
    thread.join(timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
