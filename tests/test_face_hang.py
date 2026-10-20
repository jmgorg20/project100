"""The face finder can never stop the edit (a real Windows run hung for good at "Finding your face so
graphics keep off it"): it runs in its own process with a hard time limit, is killed with everything it
started, and the edit goes on with the safe zones and a warning that says why and where the log is. A
face finder whose self-test fails is removed again and switched off until it is repaired."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from autoedit import face_detect
from autoedit.errors import EditorError

ROOT = Path(__file__).resolve().parent.parent
REAL_VIDEO = Path("/home/user/realtest/export.mp4")


def cfg(tmp_path, **tracking):
    return {"work_folder": str(tmp_path / "work"), "tracking": {"face_timeout": 5, **tracking}}


@pytest.fixture
def video(tmp_path):
    from tests import synthetic
    return synthetic.make_video(tmp_path / "talk.mp4", duration=3)


def workers_left():
    out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if "autoedit.face_worker" in line and "ps -eo" not in line]


def test_a_hanging_face_finder_is_stopped_in_time_and_says_why(tmp_path, video, monkeypatch):
    monkeypatch.setenv("AUTOEDIT_FACE_SIMULATE", "hang")
    c = cfg(tmp_path)
    started = time.monotonic()
    with pytest.raises(EditorError) as err:
        face_detect.detect_face_track(video, c)
    took = time.monotonic() - started
    assert took < 5 + 8                                        # the limit plus the self-test, never for ever
    assert "did not answer within 5 s" in str(err.value) and "face-finder.log" in str(err.value)
    assert not workers_left()                                  # killed, with what it started
    log = (tmp_path / "work" / "logs" / "face-finder.log").read_text()
    assert "self-test passed" in log and "simulating a hang" in log and "no answer within 5 s - stopped" in log


def test_a_crashing_face_finder_is_reported_with_its_exit_code(tmp_path, video, monkeypatch):
    monkeypatch.setenv("AUTOEDIT_FACE_SIMULATE", "crash")
    with pytest.raises(EditorError) as err:
        face_detect.detect_face_track(video, cfg(tmp_path))
    assert "exit code 3" in str(err.value)
    assert face_detect.read_state(cfg(tmp_path)) == {}          # checked again next time
    monkeypatch.setenv("AUTOEDIT_FACE_SIMULATE", "error")
    with pytest.raises(EditorError) as err:
        face_detect.detect_face_track(video, cfg(tmp_path))
    assert "simulated failure" in str(err.value)


def test_the_face_finder_runs_with_no_input_and_output_to_files(tmp_path):
    # nothing it runs can wait for an answer on the edit's stdin, or block on a full pipe
    log = face_detect.FinderLog({"work_folder": str(tmp_path)})
    run = face_detect.run_child([sys.executable, "-c", "import sys; print(repr(sys.stdin.read())); "
                                 "sys.stdout.write('x' * 200000)"], 10, log, "probe")
    assert run["code"] == 0 and run["output"].startswith("''") and len(run["output"]) > 200000


def test_a_failed_self_test_after_installing_removes_it_and_switches_it_off(tmp_path, video, monkeypatch):
    calls = []

    def fake_pip(args, log, label, timeout=None):
        calls.append(args[:2])
        return {"code": 0, "timed_out": False, "seconds": 0.1, "output": ""}
    monkeypatch.setattr(face_detect, "has_cv2", lambda: False)
    monkeypatch.setattr(face_detect, "pip", fake_pip)
    monkeypatch.setenv("AUTOEDIT_FACE_SIMULATE", "error:selftest")
    c = cfg(tmp_path)
    with pytest.raises(EditorError) as err:
        face_detect.detect_face_track(video, c)
    assert calls == [["install", "--quiet"], ["uninstall", "-y"]]
    assert "removed again" in str(err.value) and "Repair face finder" in str(err.value)
    state = json.loads(face_detect.state_path(c).read_text())
    assert state["status"] == "disabled" and "simulated failure" in state["reason"]
    # the next edit does not try again (no process, no install): it goes straight to the safe zones
    calls.clear()
    monkeypatch.setattr(face_detect, "worker", lambda *a, **k: pytest.fail("the face finder ran"))
    started = time.monotonic()
    with pytest.raises(EditorError) as err:
        face_detect.detect_face_track(video, c)
    assert time.monotonic() - started < 2 and calls == [] and "switched off" in str(err.value)


def test_repair_reinstalls_tests_and_switches_it_back_on(tmp_path, video, monkeypatch):
    c = cfg(tmp_path)
    face_detect.write_state(c, status="disabled", reason="OpenCV could not load a DLL")
    calls = []
    monkeypatch.setattr(face_detect, "pip", lambda args, log, label, timeout=None: calls.append(args)
                        or {"code": 0, "timed_out": False, "seconds": 0.1, "output": ""})
    r = face_detect.repair(c)
    assert r["ok"] and calls[0][:3] == ["install", "--quiet", "--force-reinstall"] and r["log"].endswith("face-finder.log")
    assert face_detect.read_state(c)["status"] == "ok"
    monkeypatch.setenv("AUTOEDIT_FACE_SIMULATE", "crash:selftest")
    r = face_detect.repair(c)
    assert not r["ok"] and "exit code 3" in r["reason"] and face_detect.read_state(c)["status"] == "disabled"


@pytest.mark.parametrize("text,code,expect", [
    ("ImportError: DLL load failed while importing cv2: The specified module could not be found.", 1,
     "Visual C++ runtime"),
    ("A module that was compiled using NumPy 1.x cannot be run in NumPy 2.0.0", 1, "numpy do not match"),
    ("TypeError: Descriptors cannot be created directly. ... protobuf", 1, "protobuf"),
    ("ModuleNotFoundError: No module named 'cv2'", 1, "not installed for this Python"),
    ("", 0xC0000135, "Visual C++ runtime"),
    ("", 0xC0000005, "access violation"),
])
def test_why_it_failed_is_said_plainly(text, code, expect):
    why = face_detect.explain({"ok": False, "error": text} if text else None,
                              {"code": code, "timed_out": False, "output": text}, 60)
    assert expect in why


def test_off_never_starts_it_and_says_nothing(tmp_path, video, monkeypatch):
    from autoedit import director
    from tests.director_helpers import make_project
    monkeypatch.setattr(face_detect, "worker", lambda *a, **k: pytest.fail("the face finder ran"))
    p = make_project([{"text": "hi", "start": 0.1, "end": 0.4}])
    events = []

    class Rep:
        def stage(self, *a): pass
        def log(self, m): events.append(m)
        def emit(self, **e): events.append(e)
    assert director.face_without_mediapipe(p, "m1", video, cfg(tmp_path, face_finder="off"), None, Rep()) is False
    assert "off in Settings" in p["meta"]["face_problem"] and events == []


def test_the_edit_goes_on_with_a_warning_when_the_face_finder_hangs(tmp_path, video, monkeypatch):
    from autoedit import director
    from tests.director_helpers import make_project
    monkeypatch.setenv("AUTOEDIT_FACE_SIMULATE", "hang")
    p = make_project([{"text": "hi", "start": 0.1, "end": 0.4}])
    events = []

    class Rep:
        def stage(self, *a): pass
        def log(self, m): events.append(m)
        def emit(self, **e): events.append(e)
    assert director.face_without_mediapipe(p, "m1", video, cfg(tmp_path), None, Rep()) is False
    warning = next(e for e in events if isinstance(e, dict) and e.get("type") == "warning")
    assert "did not answer within 5 s" in warning["message"] and warning["path"].endswith("face-finder.log")


@pytest.mark.skipif(not REAL_VIDEO.exists(), reason="the user's export is not here")
def test_the_real_app_command_finishes_with_a_hanging_face_finder(tmp_path):
    # editor.py ai-edit exactly as the desktop app runs it, with the face finder made to hang
    import yaml
    from autoedit.config import load_config
    c = load_config()
    c["work_folder"] = str(tmp_path / "work")
    c["ai"]["cache_folder"] = str(tmp_path / "cache")
    c["tracking"]["face_timeout"] = 30            # the real finder needs ~8 s here: only the hang hits it
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    env = {**os.environ, "AUTOEDIT_FACE_SIMULATE": "hang"}
    started = time.monotonic()
    proc = subprocess.run([sys.executable, str(ROOT / "editor.py"), "--json", "--config", str(conf), "ai-edit",
                           str(REAL_VIDEO), "--output", str(tmp_path / "edit.mp4"), "--transcribe-with", "groq",
                           "--transcript", str(ROOT / "tests/data/realclip/groq_words.json"), "--no-stock",
                           "--preset", "premium_editorial_viral", "--format", "auto", "--no-render",
                           "--instruction-file", str(ROOT / "tests/data/realclip/instruction.txt")],
                          capture_output=True, text=True, cwd=str(ROOT), stdin=subprocess.DEVNULL, timeout=600, env=env)
    assert proc.returncode == 0, proc.stderr[-2000:]
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    warning = next(e for e in events if e.get("type") == "warning" and e.get("stage") == "tracking")
    assert "did not answer within 30 s" in warning["message"] and warning["path"].endswith("face-finder.log")
    stages = [e.get("stage") for e in events if e.get("type") == "stage"]
    assert stages.index("tracking") < len(stages) - 1             # the next steps ran
    summary = next(e for e in reversed(events) if e.get("type") == "summary")
    assert any("safe zones" in d for d in summary.get("details", []))
    assert time.monotonic() - started < 300 and not workers_left()
