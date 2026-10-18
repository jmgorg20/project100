"""`python editor.py polish-watch`: polish every video dropped into an inbox folder.

    inbox/   the workers drop videos here (and, optionally, <name>.job.json with settings)
    outbox/  <name>.mp4 + <name>.project.json + <name>.json (the sidecar, written last)
    failed/  the original, <name>.json (why) and <name>.log (what happened)
    done/    the originals of polished videos

Safe against half-copied files: a file is taken only when its size and time have not changed for
`settle_seconds`, its name is not a temporary one (.part, .tmp, .crdownload ...), and it can be
moved (Windows refuses while another program is still writing it). Taking a file moves it into
inbox/.processing/, so a restart finds it there: a finished result is kept, an unfinished one is
started again (at most 3 times, then it goes to failed/).

One job at a time: a lock file in the work folder is held for each video, across every editor
process on this PC (two watchers, or a watcher and a `polish` command, take turns).

<name>.job.json (all optional): {"preset", "format", "instruction", "inputs": {"broll": [...],
"source": [...], "items": [...]}}; relative paths are relative to the inbox.
"""

import json
import os
import shutil
import time
import traceback
from pathlib import Path

from .errors import Cancelled, EditorError
from .ffmpeg_tools import VIDEO_EXTENSIONS

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
TEMP_SUFFIXES = (".part", ".partial", ".tmp", ".crdownload", ".download", ".filepart", ".!qb", ".opdownload")
MAX_ATTEMPTS = 3
JOB_SUFFIX = ".job.json"


class LogReporter:
    """Passes everything on, and keeps a text log of it (for failed/<name>.log)."""

    def __init__(self, inner):
        self.inner, self.lines = inner, []

    def _add(self, text):
        self.lines.append(f"{time.strftime('%H:%M:%S')} {text}")

    def stage(self, key, label):
        self._add(f"[{key}] {label}")
        self.inner.stage(key, label)

    def progress(self, fraction, stage=None):
        self.inner.progress(fraction, stage)

    def log(self, message):
        self._add(message)
        self.inner.log(message)

    def event(self, kind, **data):
        if kind not in ("project",):                 # whole projects are too big for a log
            text = json.dumps(data, ensure_ascii=False, default=str)
            self._add(f"{kind}: {text[:2000]}")
        self.inner.event(kind, **data)

    def result(self, **data):
        self.inner.result(**data)

    def error(self, message):
        self._add(f"ERROR {message}")
        self.inner.error(message)

    def cancelled(self):
        self.inner.cancelled()


def move_to(path, folder, name=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = name or Path(path).name
    target = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    if name.endswith(JOB_SUFFIX):
        stem, suffix = name[:-len(JOB_SUFFIX)], JOB_SUFFIX
    n = 2
    while target.exists():
        target = folder / f"{stem}_{n}{suffix}"
        n += 1
    shutil.move(str(path), str(target))
    return target


class Watcher:
    def __init__(self, cfg, inbox, outbox, failed, done, preset=None, format=None, instruction="",
                 provider=None, model=None, settle=10.0, reporter=None, cancel=None, check=True,
                 retry=True, max_minutes=None, clock=time.time, polish_fn=None):
        from .progress import TextReporter
        self.cfg = cfg
        self.inbox, self.outbox, self.failed, self.done = (Path(x).resolve() for x in (inbox, outbox, failed, done))
        self.processing = self.inbox / ".processing"
        self.preset, self.format, self.instruction = preset, format, instruction or ""
        self.provider, self.model = provider, model
        self.settle, self.clock = float(settle), clock
        self.reporter = reporter or TextReporter()
        self.cancel, self.check, self.retry, self.max_minutes = cancel, check, retry, max_minutes
        self.seen = {}                     # path -> (size, mtime, first time seen unchanged)
        if polish_fn is None:
            from .polish import polish as polish_fn
        self.polish_fn = polish_fn
        for folder in (self.inbox, self.outbox, self.failed, self.done, self.processing):
            folder.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- which files
    def media_ok(self, path):
        ext = path.suffix.lower()
        return ext in VIDEO_EXTENSIONS or ext in AUDIO_EXTENSIONS

    def candidates(self):
        out = []
        for p in sorted(self.inbox.iterdir()):
            name = p.name.lower()
            if not p.is_file() or name.startswith((".", "~$")) or name.endswith(TEMP_SUFFIXES):
                continue
            if name.endswith(JOB_SUFFIX) or not self.media_ok(p):
                continue
            out.append(p)
        return out

    def ready(self, path):
        """The file stopped changing at least `settle` seconds ago."""
        try:
            st = path.stat()
        except OSError:
            return False
        key = (st.st_size, st.st_mtime_ns)
        now = self.clock()
        prev = self.seen.get(path)
        if prev is None or prev[:2] != key:
            self.seen[path] = (*key, now)
            return False
        return st.st_size > 0 and now - prev[2] >= self.settle

    def claim(self, path):
        """Move it into .processing/ (fails while another program still has it open on Windows)."""
        target = self.processing / path.name
        try:
            os.replace(path, target)
        except OSError:
            return None
        self.seen.pop(path, None)
        job = path.with_name(path.stem + JOB_SUFFIX)
        if job.exists():
            try:
                os.replace(job, self.processing / job.name)
            except OSError:
                pass
        return target

    # ---------------------------------------------------------- restart safety
    def attempts_file(self, path):
        return self.processing / (path.name + ".attempts")

    def recover(self):
        """After a restart: keep finished results, start unfinished ones again."""
        notes = []
        for p in sorted(self.processing.iterdir()):
            if not p.is_file() or not self.media_ok(p):
                continue
            sidecar = self.outbox / f"{p.stem}.json"
            if sidecar.exists():
                try:
                    data = json.loads(sidecar.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}
                if data.get("status") in ("ok", "warnings") and data.get("input") and \
                        Path(data["input"]).resolve() == p.resolve() and Path(data.get("output") or "").exists():
                    self.finish_ok(p, data)
                    notes.append(f"{p.name}: already polished before the restart")
                    continue
            n = self.attempts(p)
            if n >= MAX_ATTEMPTS:
                self.finish_failed(p, f"Stopped after {n} attempts (the editor stopped or crashed each time).", [])
                notes.append(f"{p.name}: failed after {n} attempts")
                continue
            notes.append(f"{p.name}: will be polished again")
        return notes

    def attempts(self, path):
        try:
            return int(self.attempts_file(path).read_text().strip() or 0)
        except (OSError, ValueError):
            return 0

    # ---------------------------------------------------------- one video
    def job_settings(self, path):
        job = {"preset": self.preset, "format": self.format, "instruction": self.instruction, "inputs": {}}
        file = self.processing / (path.stem + JOB_SUFFIX)
        if file.exists():
            try:
                data = json.loads(file.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise EditorError(f"Could not read {file.name}: {exc}")
            if not isinstance(data, dict):
                raise EditorError(f"{file.name} must be a JSON object.")
            for key in ("preset", "format", "instruction"):
                if key in data:
                    job[key] = data[key]
            inputs = {}
            for role, value in (data.get("inputs") or {}).items():
                values = value if isinstance(value, list) else [value]
                if role in ("items",):
                    inputs[role] = [str(v) for v in values]
                elif role == "offsets":
                    inputs[role] = dict(value)
                else:
                    inputs[role] = [str((self.inbox / v).resolve()) if not Path(v).is_absolute() else v
                                    for v in values]
            job["inputs"] = inputs
        return job

    def process(self, path):
        from .wangp import GpuLock
        from .config import project_path
        log = LogReporter(self.reporter)
        n = self.attempts(path) + 1
        self.attempts_file(path).write_text(str(n))
        lock = GpuLock(Path(project_path(self.cfg["work_folder"])) / "polish.lock")
        lock.acquire(self.cancel, on_wait=lambda: log.log("waiting for another polish job to finish"))
        try:
            job = self.job_settings(path)
            log.log(f"polishing {path.name} (attempt {n}): preset {job['preset']}, format {job['format']}")
            sidecar = self.polish_fn(path, self.cfg, preset=job["preset"], format=job["format"],
                                     out_folder=self.outbox, instruction=job["instruction"],
                                     provider=self.provider, model=self.model, inputs=job["inputs"],
                                     reporter=log, cancel=self.cancel, check=self.check, retry=self.retry,
                                     max_minutes=self.max_minutes, unique=True)
        except Cancelled:
            raise                                       # stays in .processing: taken again next start
        except Exception as exc:            # any failure: the original goes to failed/ with a log
            message = str(exc) if isinstance(exc, EditorError) else f"Unexpected error: {exc}"
            self.finish_failed(path, message, log.lines + ["", traceback.format_exc()])
            return {"status": "failed", "input": str(path), "error": message}
        finally:
            lock.release()
        if sidecar["status"] == "failed":
            # Failed the checks: nothing of it stays in the outbox (the workers would post it).
            moved = dict(sidecar)
            out = Path(sidecar["output"]) if sidecar.get("output") else None
            for key, suffix in (("output", ".rejected.mp4"), ("project", ".rejected.project.json")):
                if sidecar.get(key) and Path(sidecar[key]).exists():
                    moved[key] = str(move_to(sidecar[key], self.failed, path.stem + suffix))
            if out is not None:
                plan = out.with_suffix(".plan.json")
                if plan.exists():
                    move_to(plan, self.failed, path.stem + ".rejected.plan.json")
                (self.outbox / f"{out.stem}.json").unlink(missing_ok=True)
            return self.finish_failed(path, sidecar.get("error") or "Quality checks failed.", log.lines, moved)
        return self.finish_ok(path, sidecar)

    def finish_ok(self, path, sidecar):
        from .polish import relocate_media, write_json
        original = move_to(path, self.done)
        job = self.processing / (path.stem + JOB_SUFFIX)
        if job.exists():
            move_to(job, self.done)
        if sidecar.get("project") and Path(sidecar["project"]).exists():
            relocate_media(sidecar["project"], path, original)
        sidecar = {**sidecar, "input": str(original)}
        if sidecar.get("output"):
            write_json(Path(sidecar["output"]).with_suffix(".json"), sidecar)
        self.attempts_file(path).unlink(missing_ok=True)
        self.reporter.event("polished", **{k: sidecar.get(k) for k in ("status", "input", "output")})
        return sidecar

    def finish_failed(self, path, message, lines, sidecar=None):
        from .polish import write_json
        original = move_to(path, self.failed)
        job = self.processing / (path.stem + JOB_SUFFIX)
        if job.exists():
            move_to(job, self.failed)
        stem = original.stem
        data = {**(sidecar or {}), "status": "failed", "input": str(original), "error": message,
                "log": str(self.failed / f"{stem}.log")}
        (self.failed / f"{stem}.log").write_text("\n".join(lines + ["", f"FAILED: {message}"]) + "\n",
                                                 encoding="utf-8")
        write_json(self.failed / f"{stem}.json", data)
        self.attempts_file(path).unlink(missing_ok=True)
        self.reporter.event("polish_failed", input=str(original), error=message)
        return data

    # ---------------------------------------------------------- the loop
    def once(self):
        """Look at the inbox once; polish what is ready (and what a restart left behind)."""
        results = []
        leftovers = [p for p in sorted(self.processing.iterdir()) if p.is_file() and self.media_ok(p)]
        for p in leftovers:
            results.append(self.process(p))
        for p in self.candidates():
            if self.cancel is not None and self.cancel.is_set():
                break
            if not self.ready(p):
                continue
            taken = self.claim(p)
            if taken is not None:
                results.append(self.process(taken))
        return results

    def run(self, interval=5.0):
        from .wangp import GpuLock
        guard = GpuLock(self.inbox / ".watch.lock")
        guard.acquire(self.cancel, on_wait=lambda: self.reporter.log(
            "Another watcher is using this inbox; waiting for it to stop."))
        try:
            for note in self.recover():
                self.reporter.log(note)
            self.reporter.log(f"Watching {self.inbox} (Ctrl+C to stop).")
            while self.cancel is None or not self.cancel.is_set():
                self.once()
                if self.cancel is not None:
                    if self.cancel.wait(interval):
                        break
                else:
                    time.sleep(interval)
        finally:
            guard.release()
