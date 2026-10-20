"""Finding the speaker's face with no setup: OpenCV's built-in frontal-face detector, in its own process.

The graphics keep off the face. MediaPipe tracking (docs/tracking.md) is used when it is set up;
otherwise this light detector runs: OpenCV's Haar cascade, which ships inside the
`opencv-python-headless` package (no model download). It is in requirements.txt; when it is
missing it is installed once on first use (`tracking: auto_install: false` turns that off).

It can never stop the edit (a real Windows run hung for good at "Finding your face"):

- it runs in a separate process (autoedit/face_worker.py) with a hard time limit
  (`tracking: face_timeout`, 60 s); on a timeout, a crash or any error it is killed (with
  everything it started) and the edit goes on with the safe-zone layout, with a warning that says why
- its output goes to files, never to pipes nobody reads, and it gets no input (nothing can wait
  for an answer); pip runs the same way, with no prompts and a time limit
- the frames come from FFmpeg, not from OpenCV's own video reader (Media Foundation on Windows,
  which can hang on some MP4 files)
- after installing, a self-test loads OpenCV and runs the detector on a tiny frame in its own
  process; if that fails (a DLL / Visual C++ runtime, numpy or protobuf conflict, the wrong Python),
  the reason is kept, what was installed is removed again and the face finder is switched off until
  "Repair face finder" (Settings) or `python editor.py face-finder repair`
- every step is logged with the time to work/logs/face-finder.log; its path is in the warning
- `tracking: face_finder: off` (Settings -> Face finder: Off) never starts it

A face is looked for 4 times a second (fewer on long videos: at most 300 looks,
key frames only after 2 minutes) on a small copy of
the frame. Boxes much smaller than a talking head's face, or far from where the face is the rest of
the time (a logo on a shirt), are dropped; gaps are filled from the neighbours; the path is smoothed.
The result is the same face track MediaPipe gives (center x / y and size, as fractions of the frame),
so placement works the same way.
"""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .errors import Cancelled, EditorError

PACKAGE = "opencv-python-headless<5"      # 5.x no longer ships the cascades
DIST = "opencv-python-headless"
SAMPLE_FPS = 4.0
MAX_SAMPLES = 300               # at ~50 ms a look this stays well inside the time limit
KEYFRAMES_AFTER = 120.0        # longer videos: only key frames are decoded (fast; a talking head barely moves)
TIMEOUT = 60.0                 # the face finder's hard limit (tracking: face_timeout)
SELF_TEST_TIMEOUT = 45.0
PIP_TIMEOUT = 600.0
STATE_VERSION = 1


class FinderLog:
    """work/logs/face-finder.log: one timestamped line per step (kept under ~1 MB)."""

    def __init__(self, cfg):
        folder = Path(work_folder(cfg)) / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "face-finder.log"
        if self.path.exists() and self.path.stat().st_size > 1_000_000:
            self.path.replace(folder / "face-finder.old.log")

    def step(self, message):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        with open(self.path, "a", encoding="utf-8") as f:
            for line in str(message).rstrip().splitlines() or [""]:
                f.write(f"{stamp} {line}\n")


def work_folder(cfg):
    from .config import project_path
    return project_path((cfg or {}).get("work_folder") or "work")


def settings_of(cfg):
    s = (cfg or {}).get("tracking") or {}
    mode = str(s.get("face_finder", "auto")).lower()
    return {"mode": "off" if mode in ("off", "false", "0", "no") else "auto",
            "timeout": max(5.0, float(s.get("face_timeout", TIMEOUT) or TIMEOUT)),
            "auto_install": bool(s.get("auto_install", True))}


# ---------------------------------------------------------------- the face finder's state

def state_path(cfg):
    return Path(work_folder(cfg)) / "cache" / "face_finder.json"


def read_state(cfg):
    try:
        state = json.loads(state_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # a state is about one Python: another Python (or another version of this file) checks again
    if state.get("version") != STATE_VERSION or state.get("executable") != sys.executable:
        return {}
    return state


def write_state(cfg, **state):
    path = state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.update(version=STATE_VERSION, executable=sys.executable, checked_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state


# ---------------------------------------------------------------- child processes

def kill_tree(proc):
    """Stop a child and everything it started (on Windows a plain kill leaves its children)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run_child(args, timeout, log, label, cancel=None, env=None):
    """Run a helper process with no input, its output to a file (never a pipe), a hard time limit
    and cancel. Returns {"code", "timed_out", "seconds", "output"}; its output goes to the log."""
    log.step(f"{label}: start ({timeout:g} s limit): " + " ".join(str(a) for a in args))
    out = tempfile.NamedTemporaryFile("w+b", prefix="face-", suffix=".log", delete=False,
                                      dir=str(log.path.parent))
    out.close()
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True           # its own group: the whole tree can be killed
    full_env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PIP_NO_INPUT": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "OPENCV_VIDEOIO_PRIORITY_MSMF": "0", **(env or {})}
    started = time.monotonic()
    timed_out = False
    with open(out.name, "wb") as sink:
        try:
            proc = subprocess.Popen([str(a) for a in args], stdin=subprocess.DEVNULL, stdout=sink,
                                    stderr=subprocess.STDOUT, env=full_env, cwd=str(log.path.parent), **kw)
        except OSError as exc:
            log.step(f"{label}: could not start: {exc}")
            os.unlink(out.name)
            return {"code": None, "timed_out": False, "seconds": 0.0, "output": f"could not start: {exc}"}
        try:
            while True:
                try:
                    proc.wait(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if cancel is not None and cancel.is_set():
                    kill_tree(proc)
                    log.step(f"{label}: cancelled")
                    raise Cancelled("Cancelled while finding the face.")
                if time.monotonic() - started > timeout:
                    timed_out = True
                    kill_tree(proc)
                    break
        except BaseException:
            kill_tree(proc)
            raise
    seconds = time.monotonic() - started
    try:
        output = Path(out.name).read_text(encoding="utf-8", errors="replace")
    finally:
        os.unlink(out.name)
    if output.strip():
        log.step(f"{label}: output:\n" + output.strip()[-6000:])
    log.step(f"{label}: " + (f"no answer within {timeout:g} s - stopped" if timed_out
                            else f"ended with code {proc.returncode} after {seconds:.1f} s"))
    return {"code": None if timed_out else proc.returncode, "timed_out": timed_out, "seconds": seconds,
            "output": output}


def worker(args, timeout, log, label, cancel=None, env=None):
    """Run autoedit/face_worker.py; returns (its JSON answer or None, the run)."""
    from . import PROJECT_DIR
    fd, answer = tempfile.mkstemp(prefix="face-", suffix=".json", dir=str(log.path.parent))
    os.close(fd)
    os.unlink(answer)
    env = {"PYTHONPATH": os.pathsep.join([str(PROJECT_DIR)] + [p for p in [os.environ.get("PYTHONPATH")] if p]),
           **(env or {})}
    run = run_child([sys.executable, "-m", "autoedit.face_worker", *args, answer], timeout, log, label, cancel, env)
    try:
        data = json.loads(Path(answer).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    finally:
        if os.path.exists(answer):
            os.unlink(answer)
    return data, run


# exit codes of a Windows process that died (as unsigned 32-bit)
WINDOWS_CRASHES = {0xC0000135: "a DLL it needs is missing (often the Microsoft Visual C++ runtime)",
                   0xC0000005: "it crashed (access violation)",
                   0xC000001D: "it crashed (an instruction this processor does not have)",
                   0xC0000409: "it crashed (stack buffer overrun)",
                   0xC0000139: "a DLL it needs is the wrong version (entry point not found)"}


def explain(data, run, timeout):
    """One sentence: why the face finder did not work."""
    if run["timed_out"]:
        return f"the face finder did not answer within {timeout:g} s and was stopped"
    text = ((data or {}).get("error") or run["output"] or "").strip()
    low = text.lower()
    code = run["code"]
    if code is None and run["output"].startswith("could not start"):
        return f"the face finder could not start ({run['output'][16:].strip()})"
    if "dll load failed" in low or "specified module could not be found" in low:
        return ("OpenCV could not load a DLL (" + text.splitlines()[-1][-160:] + "); the Microsoft Visual C++ "
                "runtime (vc_redist.x64.exe) is often what is missing")
    if "numpy" in low and ("compiled using numpy" in low or "_array_api" in low or "multiarray" in low
                           or "numpy.core" in low or "dtype size changed" in low):
        return "OpenCV and numpy do not match (" + text.splitlines()[-1][-160:] + ")"
    if "protobuf" in low or "descriptor" in low and "proto" in low:
        return "a protobuf version conflict stops OpenCV loading (" + text.splitlines()[-1][-160:] + ")"
    if "no module named 'cv2'" in low or "no module named cv2" in low:
        return "OpenCV is not installed for this Python (" + sys.executable + ")"
    if "simulated" in low:
        return "the face finder failed (" + text.splitlines()[-1][-160:] + ")"
    if code is not None and code < 0 or code is not None and code > 255:
        unsigned = code & 0xFFFFFFFF
        why = WINDOWS_CRASHES.get(unsigned, f"it crashed (exit code {code})")
        return f"the face finder stopped: {why}"
    if data is None:
        last = text.splitlines()[-1][-200:] if text else ""
        return f"the face finder stopped without an answer (exit code {code})" + (f": {last}" if last else "")
    return "the face finder failed (" + text.splitlines()[-1][-200:] + ")"


# ---------------------------------------------------------------- install, self-test, repair

def python_problem():
    if sys.version_info < (3, 9):
        return f"this Python is too old for the face finder ({sys.version.split()[0]} at {sys.executable})"
    if sys.maxsize <= 2 ** 32:
        return f"this Python is 32-bit; OpenCV needs 64-bit Python ({sys.executable})"
    return None


def pip(args, log, label, timeout=PIP_TIMEOUT):
    return run_child([sys.executable, "-m", "pip", *args, "--disable-pip-version-check", "--no-input"],
                     timeout, log, label)


def self_test(log, timeout=SELF_TEST_TIMEOUT, env=None):
    """(ok, reason, details) of loading OpenCV and running the detector on a tiny frame, in its own
    process."""
    data, run = worker(["--self-test"], timeout, log, "self-test", env=env)
    if data and data.get("ok"):
        return True, "", data
    return False, explain(data, run, timeout), data or {}


def has_cv2():
    try:
        return importlib.util.find_spec("cv2") is not None
    except (ImportError, ValueError):
        return False


def ensure_ready(cfg, reporter=None, log=None, env=None):
    """Make sure the face finder works on this PC (install once, self-test); raises EditorError with
    the reason when it cannot (and switches it off until a repair when it is broken)."""
    log = log or FinderLog(cfg)
    s = settings_of(cfg)
    state = read_state(cfg)
    if state.get("status") == "ok":
        log.step(f"ready (checked {state.get('checked_at')}: OpenCV {state.get('cv2')})")
        return state
    if state.get("status") == "disabled":
        log.step(f"switched off since {state.get('checked_at')}: {state.get('reason')}")
        raise EditorError(f"{state.get('reason')}; the face finder is switched off until you repair it "
                          "(Settings -> Repair face finder)")
    bad_python = python_problem()
    if bad_python:
        write_state(cfg, status="disabled", reason=bad_python)
        log.step(bad_python)
        raise EditorError(bad_python)
    installed_now = False
    if not has_cv2():
        if not s["auto_install"]:
            raise EditorError('the face finder needs OpenCV: python -m pip install "opencv-python-headless<5" '
                              "(or turn on tracking: auto_install)")
        if reporter:
            reporter.stage("tracking", "Installing the face finder (once, about 40 MB)")
        run = pip(["install", "--quiet", PACKAGE], log, "install")
        if run["code"] != 0:
            why = ("the install did not finish within " + f"{PIP_TIMEOUT:g} s" if run["timed_out"]
                   else "pip: " + (run["output"].strip().splitlines() or ["failed"])[-1][-240:])
            # not switched off: the next edit tries again (it may have been the network)
            raise EditorError(f"the face finder could not be installed ({why})")
        installed_now = True
    if reporter:
        reporter.stage("tracking", "Checking the face finder")
    ok, why, info = self_test(log, env=env)
    if ok:
        log.step(f"self-test passed: OpenCV {info.get('cv2')}, numpy {info.get('numpy')}")
        return write_state(cfg, status="ok", cv2=info.get("cv2"), numpy=info.get("numpy"),
                           installed_by_us=installed_now or state.get("installed_by_us", False))
    log.step(f"self-test failed: {why}")
    if installed_now:
        pip(["uninstall", "-y", DIST], log, "uninstall", timeout=180)
        why += " (the face finder was removed again)"
    write_state(cfg, status="disabled", reason=why)
    raise EditorError(f"{why}; the face finder is switched off until you repair it (Settings -> Repair face finder)")


def repair(cfg, reporter=None, env=None):
    """Settings -> Repair face finder: reinstall OpenCV for this Python and test it again.
    Returns {"ok", "reason", "log", "cv2"}."""
    log = FinderLog(cfg)
    log.step("---- repair")
    try:
        state_path(cfg).unlink()
    except OSError:
        pass
    bad_python = python_problem()
    if bad_python:
        write_state(cfg, status="disabled", reason=bad_python)
        return {"ok": False, "reason": bad_python, "log": str(log.path)}
    if reporter:
        reporter.stage("tracking", "Reinstalling the face finder")
    run = pip(["install", "--quiet", "--force-reinstall", PACKAGE], log, "reinstall")
    if run["code"] != 0:
        why = ("the install did not finish in time" if run["timed_out"]
               else "pip: " + (run["output"].strip().splitlines() or ["failed"])[-1][-240:])
        return {"ok": False, "reason": f"the face finder could not be installed ({why})", "log": str(log.path)}
    if reporter:
        reporter.stage("tracking", "Checking the face finder")
    ok, why, info = self_test(log, env=env)
    if ok:
        write_state(cfg, status="ok", cv2=info.get("cv2"), numpy=info.get("numpy"), installed_by_us=True)
        log.step("repair: working")
        return {"ok": True, "reason": "", "log": str(log.path), "cv2": info.get("cv2")}
    write_state(cfg, status="disabled", reason=why)
    log.step(f"repair: still not working: {why}")
    return {"ok": False, "reason": why, "log": str(log.path)}


def status(cfg):
    s = settings_of(cfg)
    state = read_state(cfg)
    return {"mode": s["mode"], "state": state.get("status") or ("not checked" if has_cv2() else "not installed"),
            "reason": state.get("reason", ""), "cv2": state.get("cv2"), "log": str(FinderLog(cfg).path)}


# ---------------------------------------------------------------- finding the face

def detect_face_track(video, cfg=None, reporter=None, cancel=None, env=None):
    """The speaker's face over the video as a tracking.Track (point "face": center x / y and size
    as fractions of the frame, confidence 0-1). Raises EditorError (with the reason and the log's
    path) when it cannot; the caller then uses the safe zones."""
    from .ffmpeg_tools import find_tool, probe
    from .tracking import Point, Track
    s = settings_of(cfg)
    if s["mode"] == "off":
        raise EditorError("the face finder is off in Settings")
    log = FinderLog(cfg)
    log.step(f"---- finding the face in {video}")
    try:
        ensure_ready(cfg, reporter, log, env=env)
        duration = 0.0
        try:
            duration = float(probe(video).get("duration") or 0)
        except EditorError:
            pass
        fps = SAMPLE_FPS if duration <= 0 else max(0.2, min(SAMPLE_FPS, MAX_SAMPLES / duration))
        fps = round(fps, 3)
        if reporter:
            reporter.stage("tracking", "Finding your face so graphics keep off it")
        args = ["--video", str(video), "--fps", str(fps), "--ffmpeg", find_tool("ffmpeg")]
        if duration > KEYFRAMES_AFTER:
            args += ["--keyframes", "1"]
        data, run = worker(args,
                           s["timeout"], log, "find", cancel,
                           env={"AUTOEDIT_FACE_FFMPEG_LOG": str(log.path.parent / "face-finder-ffmpeg.log"),
                                **(env or {})})
        if not (data and data.get("ok")):
            if not run["timed_out"]:
                # it worked before and now fails to run: check it again next time (the self-test
                # switches it off if it is broken); a timeout may be this video, so that stays
                try:
                    state_path(cfg).unlink()
                except OSError:
                    pass
            raise EditorError(explain(data, run, s["timeout"]))
        raw = [tuple(r) if r else None for r in data.get("raw") or []]
        xs, ys, cs, ss = clean_samples(raw)
    except EditorError as exc:
        log.step(f"not used: {exc}")
        raise EditorError(f"{exc}. Details: {log.path}")
    track = Track(fps, 0.0, {"face": Point(xs, ys, cs, ss)}, source="opencv-haar")
    track.notes.append(f"Face found by the built-in detector in {sum(1 for r in raw if r)} of {len(raw)} samples.")
    log.step(f"found in {sum(1 for r in raw if r)} of {len(raw)} samples ({run['seconds']:.1f} s)")
    return track


def clean_samples(raw):
    """(x, y, confidence, size) lists from the raw detections ((x, y, size) or None per sample):
    boxes that are not the speaker's face are dropped (much smaller, or far from where the face
    usually is: a logo on a shirt), short gaps filled, the path smoothed; long gaps keep the usual
    position at a lower confidence."""
    from statistics import median
    hits = [r for r in raw if r]
    if len(hits) < max(3, len(raw) // 5):
        raise EditorError("The face was not found in enough of the video.")
    mx, my, ms = (median(r[i] for r in hits) for i in range(3))
    clean = [r if r and r[2] >= ms * 0.6 and abs(r[0] - mx) < 0.3 and abs(r[1] - my) < 0.25 else None
             for r in raw]
    filled = fill_gaps(clean, max_gap=int(SAMPLE_FPS * 1.5))
    xs, ys, cs, ss = [], [], [], []
    for k, r in enumerate(filled):
        window = [v for v in filled[max(0, k - 2):k + 3] if v]
        if r is None or not window:
            # not found here for long: the speaker is assumed where they usually are (a talking
            # head barely moves), so graphics still keep off that spot
            xs.append(mx), ys.append(my), ss.append(ms), cs.append(0.55)
            continue
        xs.append(sum(v[0] for v in window) / len(window))
        ys.append(sum(v[1] for v in window) / len(window))
        ss.append(sum(v[2] for v in window) / len(window))
        cs.append(0.9 if clean[k] else 0.6)
    return xs, ys, cs, ss


def fill_gaps(samples, max_gap):
    """Short runs of misses filled by straight lines between the hits around them."""
    out = list(samples)
    k = 0
    while k < len(out):
        if out[k] is not None:
            k += 1
            continue
        j = k
        while j < len(out) and out[j] is None:
            j += 1
        before = out[k - 1] if k > 0 else None
        after = out[j] if j < len(out) else None
        if j - k <= max_gap and (before or after):
            a, b = before or after, after or before
            for m in range(k, j):
                f = (m - k + 1) / (j - k + 1)
                out[m] = tuple(a[i] + (b[i] - a[i]) * f for i in range(3))
        k = j
    return out
