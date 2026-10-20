"""Run an AI edit the way the desktop app does: `python -u editor.py --json --stdin-control ai-edit ...`
with the app's own arguments (desktop/src/main/jobArgs.ts), stdin an open pipe nobody writes to (the
app keeps it for "cancel"), stdout and stderr read line by line, slowly, the transcript taken from the
engine's cache (the app does not pass one), Groq answered by a local stand-in, and a video whose path
has spaces. Used by tests/test_post_plan.py; also handy by hand:

    python -m tests.desktop_like OUT_FOLDER [--video PATH] [--slow 0.05]
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# the user's export here; on your PC: set AUTOEDIT_TEST_VIDEO to a video of yours (e.g. "test 2.mp4")
REAL_VIDEO = Path(os.environ.get("AUTOEDIT_TEST_VIDEO") or "/home/user/realtest/export.mp4")
PLAN_ANSWER = ROOT / "tests" / "data" / "realclip" / "groq_plan_answer.json"
WORDS = ROOT / "tests" / "data" / "realclip" / "groq_words.json"


def groq_answers(body):
    """The stand-in's answer: the realistic plan for the main plan, a valid scene plan for the editorial one."""
    system = body["messages"][0]["content"]
    if "PREMIUM EDITORIAL VIRAL short video" in system:
        prompt = body["messages"][1]["content"]
        todo = []
        if "SCENES TO PLAN" in prompt:
            part = prompt.split("SCENES TO PLAN (plan exactly these):\n")[1].split("\n\n")[0]
            todo = [int(line.split(" ")[0]) for line in part.splitlines() if line[:1].isdigit()]
        return json.dumps({"summary": "ok", "scenes": [{"scene": i, "beat": "camera"} for i in todo]})
    if "choose the video format" in system:
        return json.dumps({"format": "talking_head", "reason": "one person talking"})
    return PLAN_ANSWER.read_text(encoding="utf-8")


def prepare(out, video=REAL_VIDEO):
    """A folder like the user's: 'My Videos/test 2.mp4', the config, the transcript in the cache."""
    from autoedit.cache import Cache
    from autoedit.config import load_config
    from autoedit.ai_edit import transcript_key
    out = Path(out)
    videos = out / "My Videos"
    videos.mkdir(parents=True, exist_ok=True)
    clip = videos / "test 2.mp4"
    shutil.copyfile(video, clip)
    cfg = load_config()
    cfg["work_folder"] = str(out / "work folder")
    cfg["ai"]["cache_folder"] = str(out / "work folder" / "cache")
    conf = out / "config.yaml"
    conf.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    cache = Cache(cfg["ai"]["cache_folder"])
    cache.put("transcripts", transcript_key(clip, cfg, cache), json.loads(WORDS.read_text(encoding="utf-8")))
    (out / "instruction.txt").write_text((ROOT / "tests/data/realclip/instruction.txt").read_text(encoding="utf-8"),
                                         encoding="utf-8")
    return clip, conf, cfg


def job_args(clip, out, render=True):
    """desktop/src/main/jobArgs.ts for: Groq free tier, PREMIUM EDITORIAL VIRAL + Premium editorial
    graphics, format auto, auto mode (render) on."""
    args = ["ai-edit", str(clip), "--output", str(Path(out) / "Auto Edit output" / "test 2 (AI edit).mp4"),
            "--provider", "groq", "--model", "openai/gpt-oss-120b", "--transcribe-with", "groq",
            "--caption-punctuation", "remove", "--instruction-file", str(Path(out) / "instruction.txt"),
            "--no-stock", "--preset", "premium_editorial_viral", "--graphics", "premium_editorial",
            "--format", "auto"]
    return args if render else args + ["--no-render"]


def run(out, video=REAL_VIDEO, render=True, slow=0.05, timeout=900, env_extra=None, pause_after_plan=0.0,
        step_timeout=None):
    """Run the edit like the app; returns {"code", "seconds", "events", "stderr", "requests"}."""
    sys.path.insert(0, str(ROOT))
    from tests.test_ai_timeout import FakeGroq
    clip, conf, cfg = prepare(out, video)
    if step_timeout is not None:
        cfg["edit"] = {"step_timeout": step_timeout}
        conf.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    (Path(out) / "Auto Edit output").mkdir(exist_ok=True)
    groq = FakeGroq([("ok", groq_answers)])
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "GROQ_API_KEY": "gsk_test",
           "AUTOEDIT_GROQ_URL": groq.url, **(env_extra or {})}
    cmd = [sys.executable, "-u", str(ROOT / "editor.py"), "--json", "--stdin-control", "--config", str(conf),
           *job_args(clip, out, render)]
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    events, errs = [], []

    paused = {"done": False}

    def read(stream, sink, parse):
        # like the app's readline: one line at a time, and slowly (a busy window)
        for raw in iter(stream.readline, b""):
            if parse and pause_after_plan and not paused["done"] and b'"type": "plan"' in raw:
                paused["done"] = True
                time.sleep(pause_after_plan)          # the window stops reading for a while
            line = raw.decode("utf-8", "replace").strip()
            if parse and line.startswith("{"):
                try:
                    sink.append(json.loads(line))
                except ValueError:
                    sink.append({"type": "log", "message": line})
            elif line:
                sink.append(line)
            if slow:
                time.sleep(slow)
    readers = [threading.Thread(target=read, args=(proc.stdout, events, True), daemon=True),
               threading.Thread(target=read, args=(proc.stderr, errs, False), daemon=True)]
    for r in readers:
        r.start()
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = None
    finally:
        groq.close()
    for r in readers:
        r.join(150)                                   # what is left in the pipes, read to the end
    # stdin stays open until the end, as in the app (never written: no cancel)
    try:
        proc.stdin.close()
    except OSError:
        pass
    return {"code": code, "seconds": time.monotonic() - started, "events": events, "stderr": errs,
            "requests": groq.requests, "clip": clip}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--video", default=str(REAL_VIDEO))
    ap.add_argument("--slow", type=float, default=0.05)
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    r = run(a.out, Path(a.video), not a.no_render, a.slow)
    stages = [e.get("label") for e in r["events"] if e.get("type") == "stage"]
    print(f"exit {r['code']} after {r['seconds']:.0f} s, {len(r['requests'])} AI request(s)")
    print("stages:", " | ".join(stages))
    errors = [e for e in r["events"] if e.get("type") == "error"]
    if errors:
        print("errors:", errors)
