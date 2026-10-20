"""The editor's side of WanGP: starts wangp_bridge.py with WanGP's own Python, lists its
models (with WanGP's own "installed" status), and runs one generation at a time.

Nothing here downloads a model: the bridge refuses jobs for models that are not fully
installed, and the editor only offers installed ones.

This product uses WanGP (https://github.com/deepbeepmeep/Wan2GP), subject to its license.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .errors import Cancelled, EditorError
from .hardware import VramSampler

BRIDGE = Path(__file__).with_name("wangp_bridge.py")
OOM_PATTERN = re.compile(r"out of memory|outofmemory|not enough vram|cuda error: out of", re.I)
WANGP_HOME = "https://github.com/deepbeepmeep/Wan2GP"
WANGP_MODELS_DOC = "https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/MODELS.md"


class WanGPError(EditorError):
    """WanGP is not set up, did not start, or stopped answering."""


@dataclass
class GenResult:
    success: bool
    files: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    seconds: float = 0.0
    timed_out: bool = False
    cancelled: bool = False
    not_installed: bool = False
    peak_vram_mb: int = None

    @property
    def out_of_memory(self):
        return any(OOM_PATTERN.search(e) for e in self.errors)

    @property
    def reason(self):
        if self.success:
            return "ok"
        if self.timed_out:
            return "took too long"
        if self.cancelled:
            return "cancelled"
        if self.not_installed:
            return "model not installed"
        if self.out_of_memory:
            return "out of GPU memory"
        return "failed"


def check_setup(gen_cfg):
    """Problems with the WanGP settings, in plain words (empty list = looks usable)."""
    w = gen_cfg.get("wangp") or {}
    problems = []
    folder, python = w.get("folder") or "", w.get("python") or ""
    if not folder:
        problems.append("Set the WanGP folder (where wgp.py is) in the generation settings.")
    elif not (Path(folder) / "wgp.py").exists():
        problems.append(f"wgp.py was not found in {folder}. Is this the WanGP folder?")
    if not python:
        problems.append("Set WanGP's Python (in a terminal: conda activate wan2gp, then "
                        "'where python' on Windows or 'which python', and paste the path).")
    elif not Path(python).exists() and os.sep in python:
        problems.append(f"WanGP's Python was not found: {python}")
    return problems


class GpuLock:
    """One GPU job at a time on this PC, across all editor processes (a lock file)."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self, cancel=None, on_wait=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+b")
        told = False
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if not told and on_wait:
                    on_wait()
                    told = True
                if cancel is not None and cancel.wait(1.0):
                    self.release()
                    raise Cancelled("Cancelled while waiting for the GPU.")
                if cancel is None:
                    time.sleep(1.0)

    def release(self):
        if not self.handle:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


class Bridge:
    """A running wangp_bridge.py. Use as a context manager."""

    STOP_GRACE = 60

    def __init__(self, gen_cfg, output_dir, log=print, start_timeout=600):
        problems = check_setup(gen_cfg)
        if problems:
            raise WanGPError(" ".join(problems))
        w = gen_cfg["wangp"]
        self.cmd = [w["python"], str(BRIDGE), "--root", str(w["folder"]),
                    "--cli-args", json.dumps(list(w.get("cli_args") or [])),
                    "--output-dir", str(output_dir)]
        self.log = log
        self.start_timeout = start_timeout
        self.proc = None
        self.messages = queue.Queue()
        self.version = None
        self.counter = 0

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self):
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise WanGPError(f"Could not start WanGP's Python ({self.cmd[0]}): {exc}")

        def read_out():
            for line in self.proc.stdout:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        self.messages.put(json.loads(line))
                        continue
                    except ValueError:
                        pass
                if line:
                    self.log(f"  [WanGP] {line}")
            self.messages.put({"type": "exit"})

        def read_err():
            for line in self.proc.stderr:
                if line.strip():
                    self.log(f"  [WanGP] {line.rstrip()}")

        threading.Thread(target=read_out, daemon=True).start()
        threading.Thread(target=read_err, daemon=True).start()
        message = self._wait(lambda m: m["type"] in ("ready", "fatal", "exit"), self.start_timeout)
        if message is None:
            self.close()
            raise WanGPError("WanGP did not start in time.")
        if message["type"] != "ready":
            self.close()
            raise WanGPError(message.get("message") or "WanGP stopped while starting. See the log.")
        self.version = message.get("version") or "unknown"

    def _wait(self, match, timeout):
        end = time.monotonic() + timeout if timeout else None
        while True:
            remaining = None if end is None else end - time.monotonic()
            if remaining is not None and remaining <= 0:
                return None
            try:
                message = self.messages.get(timeout=min(1.0, remaining) if remaining else 1.0)
            except queue.Empty:
                continue
            if match(message):
                return message
            if message["type"] == "exit":
                return message

    def send(self, **data):
        try:
            self.proc.stdin.write(json.dumps(data) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            raise WanGPError("WanGP stopped answering.")

    def models(self, timeout=300):
        self.send(cmd="models")
        message = self._wait(lambda m: m["type"] in ("models", "error"), timeout)
        if not message or message["type"] != "models":
            raise WanGPError((message or {}).get("message") or "WanGP did not list its models.")
        return message["models"]

    def generate(self, settings, output_dir, timeout=None, cancel=None, on_progress=None):
        """Run one job. Returns a GenResult (never raises for a failed generation).

        Past `timeout` seconds, or when `cancel` is set, WanGP is asked to stop the job; if
        it has not stopped STOP_GRACE seconds later, the bridge process is closed.
        """
        self.counter += 1
        job_id = f"j{self.counter}"
        started = time.monotonic()
        stop_reason, stop_at = None, None
        with VramSampler() as vram:
            self.send(cmd="generate", id=job_id, settings=settings, output_dir=str(output_dir))
            while True:
                message = self._wait(lambda m: m.get("id") == job_id or m["type"] == "exit", 1.0)
                elapsed = time.monotonic() - started
                if message and message["type"] == "progress":
                    if on_progress:
                        on_progress(message)
                elif message and message["type"] == "done":
                    break
                elif message and message["type"] == "exit":
                    return GenResult(False, errors=["WanGP stopped during the job."],
                                     seconds=elapsed, peak_vram_mb=vram.job_peak_mb,
                                     timed_out=stop_reason == "timeout",
                                     cancelled=stop_reason == "cancel")
                if stop_reason is None:
                    if timeout and elapsed > timeout:
                        stop_reason = "timeout"
                    elif cancel is not None and cancel.is_set():
                        stop_reason = "cancel"
                    if stop_reason:
                        stop_at = elapsed
                        self.send(cmd="cancel", id=job_id)
                elif elapsed > stop_at + self.STOP_GRACE:
                    self.close(force=True)
                    return GenResult(False, errors=["WanGP did not stop the job, so it was closed."],
                                     seconds=elapsed, peak_vram_mb=vram.job_peak_mb,
                                     timed_out=stop_reason == "timeout",
                                     cancelled=stop_reason == "cancel")
        files = list(message.get("files") or [])
        errors = [e.get("message", "") for e in message.get("errors") or []]
        if message.get("success") and not files:
            errors.append("WanGP finished without an output file.")
        return GenResult(
            success=bool(message.get("success")) and bool(files) and stop_reason is None,
            files=files, errors=errors,
            seconds=float(message.get("seconds") or time.monotonic() - started),
            timed_out=stop_reason == "timeout",
            cancelled=stop_reason == "cancel" or bool(message.get("cancelled")),
            not_installed=bool(message.get("not_installed")),
            peak_vram_mb=vram.job_peak_mb)

    @property
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def close(self, force=False):
        if not self.proc:
            return
        if self.proc.poll() is None and not force:
            try:
                self.send(cmd="quit")
                self.proc.wait(timeout=30)
            except (WanGPError, subprocess.TimeoutExpired):
                pass
        if self.proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/pid", str(self.proc.pid), "/T", "/F"],
                               capture_output=True, stdin=subprocess.DEVNULL)
            else:
                self.proc.kill()
            self.proc.wait(timeout=30)


@contextmanager
def gpu_turn(lock_path, cancel=None, log=print):
    """Hold the GPU lock for a block of jobs."""
    lock = GpuLock(lock_path)
    lock.acquire(cancel, on_wait=lambda: log("  > waiting for another GPU job to finish"))
    try:
        yield
    finally:
        lock.release()


def model_links(model):
    """Official pages to read about (and the license of) a model before downloading it."""
    links = []
    for url in model.get("urls") or []:
        match = re.match(r"https://huggingface\.co/([^/]+/[^/]+)", url)
        if match:
            page = f"https://huggingface.co/{match.group(1)}"
            if page not in links:
                links.append(page)
    links.append(WANGP_MODELS_DOC)
    return links
