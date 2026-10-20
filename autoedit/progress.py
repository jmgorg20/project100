"""Progress reporting: friendly text in the terminal, or JSON lines for the desktop app.

JSON mode writes one object per line on stdout, for example:

    {"type": "stage", "stage": "render", "label": "Rendering"}
    {"type": "progress", "stage": "render", "percent": 42.5}
    {"type": "log", "message": "..."}
    {"type": "transcript" / "plan" / "project" / "summary", ...}   (AI edit steps)
    {"type": "result", "output": "C:/.../video.mp4"}
    {"type": "error", "message": "..."}
    {"type": "cancelled"}
"""

import json
import sys
import threading
import time


class TextReporter:
    def __init__(self, stream=None):
        self.stream = stream or sys.stderr
        self._last = -1

    def stage(self, key, label):
        print(f"  > {label}")
        self._last = -1

    def progress(self, fraction, stage=None):
        percent = int(fraction * 100)
        if percent != self._last:
            self._last = percent
            self.stream.write(f"\r    {percent:3d}%")
            if percent >= 100:
                self.stream.write("\n")
            self.stream.flush()

    def log(self, message):
        print(message)

    def event(self, kind, **data):
        """A result of one step (transcript, plan, summary...). Shown by the app."""
        if kind == "summary":
            print("\n" + data.get("headline", ""))
            for line in data.get("details", []):
                print(f"  - {line}")
        elif kind == "plan" and data.get("fallback"):
            print(f"  ! {data.get('reason')}")

    def result(self, **data):
        pass

    def error(self, message):
        pass

    def cancelled(self):
        pass


class BackgroundStream:
    """Writes to `stream` on its own thread, so the edit never waits for whoever reads the pipe (a
    busy or stuck app window must not stop the engine). Lines marked droppable (progress, heartbeat,
    log) are dropped while too many are waiting; the others never are. close() waits for the rest
    (up to a limit)."""

    MAX_PENDING = 2000

    def __init__(self, stream):
        import collections
        self.stream = stream
        self.pending = collections.deque()
        self.cond = threading.Condition()
        self.closed = False
        self.dropped = 0
        self.thread = threading.Thread(target=self._run, daemon=True, name="pipe-writer")
        self.thread.start()

    def write(self, text, droppable=False):
        if not text:
            return 0
        with self.cond:
            if droppable and len(self.pending) >= self.MAX_PENDING:
                self.dropped += 1
                return len(text)
            self.pending.append(text)
            self.cond.notify()
        return len(text)

    def flush(self):
        pass

    def _run(self):
        while True:
            with self.cond:
                while not self.pending and not self.closed:
                    self.cond.wait()
                if not self.pending and self.closed:
                    return
                text = self.pending.popleft()
                self.cond.notify_all()
            try:
                self.stream.write(text)
                self.stream.flush()
            except (OSError, ValueError):       # the reader is gone: nothing more to say
                with self.cond:
                    self.pending.clear()
                    self.closed = True
                return

    def close(self, timeout=10.0):
        """Write what is waiting (at most `timeout` s), then stop."""
        import time as _time
        end = _time.monotonic() + timeout
        with self.cond:
            self.closed = True
            self.cond.notify_all()
            while self.pending and _time.monotonic() < end:
                self.cond.wait(0.1)
        self.thread.join(max(0.0, end - _time.monotonic()))

    # what io.TextIOBase offers, for print() / tracebacks redirected here
    def isatty(self):
        return False

    @property
    def encoding(self):
        return getattr(self.stream, "encoding", "utf-8")


DROPPABLE = {"progress", "heartbeat", "log"}


class JsonReporter:
    """Writes JSON lines to `stream` (the real stdout). Thread-safe; progress is throttled. With a
    BackgroundStream the edit never waits for the reader (progress / log lines may be dropped when
    the reader falls far behind; results and errors are not)."""

    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()
        self.current = None
        self._last_percent = -1.0
        self._last_time = 0.0

    def emit(self, **data):
        line = json.dumps(data)   # ASCII-only: safe on any console encoding
        with self.lock:
            if isinstance(self.stream, BackgroundStream):
                self.stream.write(line + "\n", droppable=data.get("type") in DROPPABLE)
            else:
                self.stream.write(line + "\n")
                self.stream.flush()

    def stage(self, key, label):
        self.current = key
        self._last_percent = -1.0
        self.emit(type="stage", stage=key, label=label)

    def progress(self, fraction, stage=None):
        percent = round(fraction * 100, 1)
        now = time.monotonic()
        if percent >= 100 or (percent - self._last_percent >= 0.5
                              and now - self._last_time >= 0.1):
            self._last_percent, self._last_time = percent, now
            self.emit(type="progress", stage=stage or self.current, percent=percent)

    def log(self, message):
        self.emit(type="log", message=str(message))

    def event(self, kind, **data):
        self.emit(type=kind, **data)

    def result(self, **data):
        self.emit(type="result", **data)

    def error(self, message):
        self.emit(type="error", message=str(message))

    def cancelled(self):
        self.emit(type="cancelled")
