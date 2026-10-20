"""After the AI plan came back, a real Windows run sat idle for good (one python process, alive,
0.44 s of CPU in 3 minutes, the app at "Planning the editorial scenes..."). These tests run the
edit as the desktop app does (tests/desktop_like.py: the app's own arguments, stdin an open pipe,
stdout / stderr read slowly, Windows-like paths with spaces, a realistic plan from a stand-in for
Groq) and prove:

- it finishes, every step logged with its start and end in work/logs/edit.log, heartbeats sent
- the engine no longer waits for the app to read its output (it used to: with the app not reading,
  nothing after the plan happened until it read again)
- a stuck step is stopped after its limit with an error naming the step and both logs, and
  work/logs/engine-stack.log shows the exact line it was stuck on
- no subprocess shares the app's stdin pipe (on Windows a child can block on a pipe another thread
  is reading)
"""

import ast
import json
import time
from pathlib import Path

import pytest

from autoedit import steplog
from tests import desktop_like as dl

ROOT = Path(__file__).resolve().parent.parent
needs_video = pytest.mark.skipif(not dl.REAL_VIDEO.exists(), reason="the user's export is not here")


def log_of(run_dir):
    return (Path(run_dir) / "work folder" / "logs" / "edit.log").read_text(encoding="utf-8")


@needs_video
def test_the_post_plan_steps_finish_like_the_app_runs_them(tmp_path):
    out = tmp_path / "Juan Dela Cruz" / "Auto Edit run"
    r = dl.run(out, render=True)
    assert r["code"] == 0, r["stderr"][-20:]
    assert len(r["requests"]) >= 1 and " " in str(r["clip"])
    types = [e.get("type") for e in r["events"]]
    assert "result" in types and "summary" in types and "error" not in types
    result = next(e for e in r["events"] if e.get("type") == "result")
    assert Path(result["output"]).is_file() and Path(result["output"]).stat().st_size > 100_000
    assert types.count("heartbeat") >= 3                       # the engine says it is alive
    log = log_of(out)
    for phase in ("AI plan", "graphics: finding the face", "graphics: scenes", "graphics: AI scene plan",
                  "graphics: building the cards", "preset: music and sound effects", "summary and saving",
                  "render"):
        assert f"start {phase}" in log and f"end {phase}" in log, phase
    assert "waiting for the AI (AI plan, try 1)" in log and log.rstrip().endswith("==== finished")
    assert "STUCK" not in log


@needs_video
def test_the_engine_does_not_wait_for_the_app_to_read(tmp_path):
    out = tmp_path / "paused app"
    started = time.time()
    r = dl.run(out, render=False, pause_after_plan=40)          # the window stops reading for 40 s
    assert r["code"] == 0
    assert any(e.get("type") == "result" for e in r["events"])  # everything arrives once it reads again
    saved = next(line for line in log_of(out).splitlines() if line.find("end summary and saving") > 0)
    stamp = time.mktime(time.strptime(saved[:19], "%Y-%m-%d %H:%M:%S"))
    assert stamp - started < 30, "the edit waited for the app to read its output"


@needs_video
def test_a_stuck_step_is_stopped_with_its_stack_and_a_clear_error(tmp_path):
    out = tmp_path / "stuck run"
    r = dl.run(out, render=False, step_timeout=5, env_extra={"AUTOEDIT_SIMULATE_STUCK": "building the cards"})
    assert r["code"] == 3 and r["seconds"] < 60
    error = next(e for e in r["events"] if e.get("type") == "error")
    assert 'stuck in the step "graphics: building the cards, looks and layout"' in error["message"]
    assert error["logs"][0].endswith("edit.log") and error["logs"][1].endswith("engine-stack.log")
    stacks = Path(error["logs"][1]).read_text(encoding="utf-8")
    assert "STUCK in step 'graphics: building the cards" in stacks
    assert "editorial.py" in stacks and "in generate" in stacks            # the exact line it was stuck on
    assert "STUCK in step" in log_of(out)


def test_waiting_for_the_ai_does_not_count_against_the_step(tmp_path, monkeypatch):
    stops = []
    monkeypatch.setattr(steplog.S, "exit", lambda code: stops.append(code))
    monkeypatch.setattr(steplog.S, "armed", True)
    steplog.start({"work_folder": str(tmp_path), "edit": {"step_timeout": 1}})
    try:
        steplog.phase("a step that asks the AI")
        with steplog.waiting("the AI"):
            time.sleep(2.5)                                      # longer than the step's limit
        time.sleep(0.5)
        assert stops == []
        time.sleep(1.6)                                          # now the step itself is too slow
        assert stops == [3]
    finally:
        steplog.finish()
    text = (tmp_path / "logs" / "edit.log").read_text()
    assert "waiting for the AI" in text and "STUCK in step 'a step that asks the AI'" in text


def test_no_subprocess_shares_the_apps_stdin():
    # every child gets its own stdin (DEVNULL, or a pipe it is fed through): none inherits the app's
    missing = []
    for path in [*sorted((ROOT / "autoedit").glob("*.py")), ROOT / "editor.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                    isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess" and \
                    node.func.attr in ("run", "Popen", "call", "check_output", "check_call"):
                if not any(k.arg == "stdin" for k in node.keywords):
                    missing.append(f"{path.name}:{node.lineno}")
    assert missing == []


def test_the_progress_writer_never_blocks_the_edit():
    from autoedit.progress import BackgroundStream, JsonReporter

    class Stuck:
        """A pipe nobody reads: every write blocks."""
        def __init__(self):
            import threading
            self.gate = threading.Event()
            self.lines = []

        def write(self, text):
            self.gate.wait()
            self.lines.append(text)

        def flush(self):
            pass
    pipe = Stuck()
    stream = BackgroundStream(pipe)
    rep = JsonReporter(stream)
    started = time.monotonic()
    for i in range(5000):
        rep.progress(i / 5000)
        rep.log(f"line {i}")
    rep.result(done=True)
    assert time.monotonic() - started < 2                         # the edit went on
    pipe.gate.set()
    stream.close(10)
    assert json.loads(pipe.lines[-1]) == {"type": "result", "done": True}   # never dropped


def test_in_process_a_slow_step_is_only_logged(tmp_path, monkeypatch):
    # tests and the service call the edit in their own process: never stopped by the watchdog
    stops = []
    monkeypatch.setattr(steplog.S, "exit", lambda code: stops.append(code))
    monkeypatch.setattr(steplog.S, "armed", False)
    steplog.start({"work_folder": str(tmp_path), "edit": {"step_timeout": 1}})
    try:
        steplog.phase("slow in a test")
        time.sleep(2.5)
    finally:
        steplog.finish()
    assert stops == []
    assert "(not run by the app: the step goes on)" in (tmp_path / "logs" / "edit.log").read_text()
