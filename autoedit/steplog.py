"""Every step of an edit, with the time, in work/logs/edit.log - and a stuck engine never just waits.

A real Windows run stopped after the AI plan came back (one python process, alive, 0.44 s of CPU in
3 minutes, the app at "Planning the editorial scenes..."). So:

- `with step("name"):` writes "start name" and "end name (1.23 s)" to work/logs/edit.log, each line
  flushed to disk at once (a stuck step is the last "start" without its "end")
- a heartbeat line goes to the app every 5 s: {"type": "heartbeat", "step": ..., "seconds": ...}
- a step that takes longer than its limit (60 s; `edit: step_timeout`) is stuck: the stacks of all
  threads go to work/logs/engine-stack.log, the app gets an error naming the step and both logs, and
  the engine stops (exit code 3) so the app is never left waiting. Time spent waiting for the AI
  (`with waiting("AI request")`, which has its own limits: llm.ask_json) and drawing / rendering
  (their own progress) does not count
- faulthandler.dump_traceback_later(90, repeat=True) writes the Python stacks to engine-stack.log
  every 90 s while the edit runs (a C-level thread: it works even when Python itself is blocked)
"""

import contextlib
import faulthandler
import json
import os
import sys
import threading
import time

STEP_TIMEOUT = 60.0
HEARTBEAT = 5.0
STACK_EVERY = 90


class _State:
    def __init__(self):
        self.log_path = None
        self.stack_path = None
        self.stack_file = None
        self.reporter = None
        self.steps = []                # [(name, started, limit, paused_seconds)] - nested
        self.paused = 0                # waiting() depth
        self.pause_started = None
        self.lock = threading.RLock()
        self.thread = None
        self.beat_thread = None
        self.stop = threading.Event()
        self.timeout = STEP_TIMEOUT
        self.exit = os._exit
        self.armed = False             # stop the process when stuck: only the engine run by the app


S = _State()


def _write(line):
    if not S.log_path:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
    try:
        with open(S.log_path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} {line}\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass


def log(message):
    _write(message)


def arm():
    """The engine run by the app (editor.py --json): a stuck step stops the process (exit code 3), so
    the app is never left waiting. In-process callers (tests, the service) only get the logs."""
    S.armed = True


def start(cfg, reporter=None, what="edit"):
    """Begin logging an edit (work/logs/edit.log and engine-stack.log); starts the heartbeat, the
    step watchdog and faulthandler's stack dumps."""
    from .config import project_path
    folder = project_path((cfg or {}).get("work_folder") or "work") / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    S.log_path = folder / "edit.log"
    S.stack_path = folder / "engine-stack.log"
    if S.log_path.exists() and S.log_path.stat().st_size > 2_000_000:
        S.log_path.replace(folder / "edit.old.log")
    S.reporter = reporter
    S.timeout = float(((cfg or {}).get("edit") or {}).get("step_timeout", STEP_TIMEOUT))
    S.steps, S.paused, S.pause_started = [], 0, None
    _write(f"==== {what} (python {sys.version.split()[0]}, pid {os.getpid()})")
    try:
        if S.stack_file is not None and getattr(S.stack_file, "name", None) != str(S.stack_path):
            S.stack_file.close()
            S.stack_file = None
        if S.stack_file is None:
            S.stack_file = open(S.stack_path, "a", encoding="utf-8")
        S.stack_file.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} {what} (pid {os.getpid()}): stacks every "
                           f"{STACK_EVERY} s while it runs\n")
        S.stack_file.flush()
        faulthandler.dump_traceback_later(STACK_EVERY, repeat=True, file=S.stack_file)
    except (OSError, RuntimeError, ValueError):
        pass
    S.stop.clear()
    if S.thread is None or not S.thread.is_alive():
        S.thread = threading.Thread(target=_watch, daemon=True, name="edit-watchdog")
        S.thread.start()
    if S.beat_thread is None or not S.beat_thread.is_alive():
        S.beat_thread = threading.Thread(target=_beat, daemon=True, name="edit-heartbeat")
        S.beat_thread.start()


def finish(ok=True):
    end_phase()
    _write(f"==== {'finished' if ok else 'stopped'}")
    S.stop.set()
    try:
        faulthandler.cancel_dump_traceback_later()
    except (RuntimeError, ValueError):
        pass


def phase(name, limit=None):
    """Move on to the next top-level step of the edit (the previous one is logged as ended)."""
    end_phase()
    with S.lock:
        S.steps.insert(0, [name, time.monotonic(), S.timeout if limit is None else limit, 0.0, "phase"])
    _write(f"start {name}")
    simulate = os.environ.get("AUTOEDIT_SIMULATE_STUCK")
    if simulate and simulate in name:
        # tests: stuck as the real Windows run was (alive, no CPU, waiting on something that never comes)
        _write("  (simulating a stuck step)")
        threading.Event().wait()


def end_phase():
    with S.lock:
        old = S.steps.pop(0) if S.steps and len(S.steps[0]) > 4 else None
    if old:
        _write(f"end {old[0]} ({time.monotonic() - old[1]:.2f} s)")


@contextlib.contextmanager
def step(name, limit=None):
    """A step of the edit: logged at its start and end; stuck after `limit` s (default 60 s; None =
    the default, 0 = no limit: rendering, drawing and transcribing report their own progress)."""
    with S.lock:
        S.steps.append([name, time.monotonic(), S.timeout if limit is None else limit, 0.0])
    _write(f"start {name}")
    t = time.monotonic()
    ok = False
    try:
        yield
        ok = True
    finally:
        with S.lock:
            if S.steps and S.steps[-1][0] == name:
                S.steps.pop()
        _write(f"{'end' if ok else 'failed'} {name} ({time.monotonic() - t:.2f} s)")


@contextlib.contextmanager
def waiting(what):
    """Waiting for something with its own time limit (the AI): not counted against the step."""
    with S.lock:
        S.paused += 1
        if S.paused == 1:
            S.pause_started = time.monotonic()
    _write(f"  waiting for {what}")
    try:
        yield
    finally:
        with S.lock:
            S.paused -= 1
            if S.paused == 0 and S.pause_started is not None:
                gone = time.monotonic() - S.pause_started
                for s in S.steps:
                    s[3] += gone
                S.pause_started = None
        _write(f"  done waiting for {what}")


def _current():
    with S.lock:
        if not S.steps:
            return None, 0.0, (0.0, 0)
        name, started, limit, paused = S.steps[-1][:4]
        now = time.monotonic()
        live_pause = (now - S.pause_started) if S.pause_started is not None else 0.0
        return name, now - started, (now - started - paused - live_pause, limit)


def _watch():
    """The step watchdog: never writes to the app (a blocked pipe must not block it)."""
    while not S.stop.wait(1.0):
        name, _total, (busy, limit) = _current()
        if name is not None and limit and busy > limit and S.paused == 0:
            stuck(name, busy)


def _beat():
    """The heartbeat: a line to the app every 5 s while a step runs (its own thread: if the app does
    not read, only this thread waits)."""
    while not S.stop.wait(HEARTBEAT):
        name, total, _ = _current()
        if name is not None and S.reporter is not None and hasattr(S.reporter, "emit"):
            try:
                S.reporter.emit(type="heartbeat", step=name, seconds=round(total, 1))
            except Exception:                    # the app stopped reading: nothing to tell it
                pass


def stuck(name, seconds):
    """A step went over its limit: dump every thread's stack, tell the app, stop the engine."""
    _write(f"STUCK in step '{name}' for {seconds:.0f} s: the stacks of all threads are in {S.stack_path}")
    try:
        S.stack_file.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} STUCK in step '{name}' for "
                           f"{seconds:.0f} s\n")
        S.stack_file.flush()
        faulthandler.dump_traceback(file=S.stack_file, all_threads=True)
        S.stack_file.flush()
    except (OSError, AttributeError, ValueError):
        pass
    message = (f"The editor got stuck in the step \"{name}\" (nothing finished for {seconds:.0f} s) and was "
               f"stopped. Steps: {S.log_path}  Where it was stuck: {S.stack_path}")
    def tell():
        try:
            if S.reporter is not None and hasattr(S.reporter, "emit"):
                S.reporter.emit(type="error", message=message, logs=[str(S.log_path), str(S.stack_path)])
                stream = getattr(S.reporter, "stream", None)
                if hasattr(stream, "close"):
                    stream.close(1.8)          # written before the engine stops
            else:
                print(json.dumps({"type": "error", "message": message}), file=sys.stderr, flush=True)
        except Exception:
            pass
    if not S.armed:
        _write("  (not run by the app: the step goes on)")
        with S.lock:
            if S.steps:
                S.steps[-1][2] = 0             # reported once
        return
    # if the pipe to the app is what is blocked, the message cannot get through: stop anyway
    teller = threading.Thread(target=tell, daemon=True)
    teller.start()
    teller.join(2.0)
    S.stop.set()
    S.exit(3)
