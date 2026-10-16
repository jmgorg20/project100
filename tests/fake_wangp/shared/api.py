"""A stand-in for WanGP's shared/api.py with the same public surface the editor uses
(init, list_model_defs, list_model_metadata(include_availability=True),
get_model_availability, submit_task -> job.events / job.result() / job.cancel()).

Models come from fake_models.json next to wgp.py. Each can set:
  seconds (job length), oom_above_pixels (fail like a CUDA OOM above this resolution),
  fail (error message), noisy (print junk to stdout, as real libraries do).
Outputs are real small files made with FFmpeg.
"""

import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CALLS = ROOT / "calls.jsonl"          # every submitted task, for the tests to inspect


@dataclass
class SessionEvent:
    kind: str
    data: object = None


@dataclass
class ProgressUpdate:
    phase: str
    status: str
    progress: int
    current_step: int = None
    total_steps: int = None


@dataclass
class GenerationError:
    message: str
    stage: str = None


@dataclass
class GenerationResult:
    success: bool
    generated_files: list
    errors: list = field(default_factory=list)
    cancelled: bool = False


class Stream:
    def __init__(self):
        self.q = queue.Queue()

    def iter(self, timeout=None):
        while True:
            try:
                item = self.q.get(timeout=timeout)
            except queue.Empty:
                continue
            if item is None:
                return
            yield item


class Job:
    def __init__(self):
        self.events = Stream()
        self._done = threading.Event()
        self._cancel = threading.Event()
        self._result = None

    def cancel(self):
        self._cancel.set()

    def result(self, timeout=None):
        self._done.wait(timeout)
        return self._result


def models():
    return json.loads((ROOT / "fake_models.json").read_text(encoding="utf-8"))


class Session:
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir) if output_dir else ROOT / "outputs"

    def list_model_defs(self, **filters):
        return [{"model_type": m["model_type"], "name": m["name"], "URLs": m.get("urls", []),
                 "metadata": {}} for m in models()]

    def list_model_metadata(self, include_availability=False, **filters):
        out = []
        for m in models():
            record = {"model_type": m["model_type"], "name": m["name"], "family": m["family"],
                      "family_label": m["family"], "main_output": m["main_output"],
                      "outputs": m["main_output"], "inputs": ["text"]}
            if include_availability:
                record["availability"] = self.get_model_availability(m["model_type"])
            out.append(record)
        return out

    def get_model_availability(self, model_type):
        m = next((m for m in models() if m["model_type"] == model_type), None)
        if m is None:
            raise ValueError(f"Unknown model_type: {model_type}")
        return {"model_type": model_type, "status": m["status"],
                "available": m["status"] == "available"}

    def submit_task(self, settings):
        with open(CALLS, "a", encoding="utf-8") as f:
            f.write(json.dumps(settings) + "\n")
        job = Job()
        threading.Thread(target=self._run, args=(job, settings), daemon=True).start()
        return job

    def _run(self, job, settings):
        m = next(m for m in models() if m["model_type"] == settings["model_type"])
        if m.get("noisy"):
            print("Loading model... 100%|##########| junk on stdout")
            sys.stdout.flush()
        width, height = (int(v) for v in settings.get("resolution", "320x576").split("x"))
        steps = int(settings.get("num_inference_steps", 4))
        errors, files = [], []
        if m.get("oom_above_pixels") and width * height > m["oom_above_pixels"]:
            errors.append(GenerationError("CUDA out of memory. Tried to allocate 2.00 GiB"))
        elif m.get("fail"):
            errors.append(GenerationError(m["fail"]))
        else:
            for step in range(steps):
                if job._cancel.is_set():
                    break
                time.sleep(float(m.get("seconds", 0.2)) / steps)
                job.events.q.put(SessionEvent("progress", ProgressUpdate(
                    "Denoising", "", int((step + 1) * 100 / steps), step + 1, steps)))
            if job._cancel.is_set():
                errors.append(GenerationError("Cancelled"))
            else:
                files.append(self._make(m, settings, width, height))
        job._result = GenerationResult(not errors, files, errors,
                                       cancelled=job._cancel.is_set())
        job.events.q.put(None)
        job._done.set()

    def _make(self, m, settings, width, height):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        name = settings.get("output_filename") or f"out_{int(time.time() * 1000)}"
        kind = m["main_output"][0]
        if kind == "image":
            out = self.output_dir / f"{name}.png"
            src = ["-f", "lavfi", "-i", f"color=c=teal:s={width}x{height}", "-frames:v", "1"]
        elif kind == "video":
            length = settings.get("video_length", 33)
            seconds = float(str(length)[:-1]) if str(length).endswith("s") else int(length) / 16
            out = self.output_dir / f"{name}.mp4"
            src = ["-f", "lavfi", "-i", f"testsrc2=s={width}x{height}:r=16:d={seconds}",
                   "-pix_fmt", "yuv420p"]
        else:
            out = self.output_dir / f"{name}.wav"
            src = ["-f", "lavfi", "-i",
                   f"sine=f=330:d={settings.get('duration_seconds', 2)}"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *src, str(out)], check=True)
        return str(out)


def init(root=None, output_dir=None, cli_args=(), console_output=True, console_isatty=True,
         **kwargs):
    # Like the real banner: printed straight to the process's stdout.
    sys.__stdout__.write("Powered by WanGP (test stand-in)\n")
    sys.__stdout__.flush()
    if "--fail-start" in cli_args:
        raise RuntimeError("CUDA driver not found")
    return Session(output_dir)
