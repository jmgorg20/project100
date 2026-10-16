"""Progress reporting: friendly text in the terminal, or JSON lines for the desktop app.

JSON mode writes one object per line on stdout, for example:

    {"type": "stage", "stage": "render", "label": "Rendering"}
    {"type": "progress", "stage": "render", "percent": 42.5}
    {"type": "log", "message": "..."}
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

    def result(self, **data):
        pass

    def error(self, message):
        pass

    def cancelled(self):
        pass


class JsonReporter:
    """Writes JSON lines to `stream` (the real stdout). Thread-safe; progress is throttled."""

    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()
        self.current = None
        self._last_percent = -1.0
        self._last_time = 0.0

    def emit(self, **data):
        line = json.dumps(data)   # ASCII-only: safe on any console encoding
        with self.lock:
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

    def result(self, **data):
        self.emit(type="result", **data)

    def error(self, message):
        self.emit(type="error", message=str(message))

    def cancelled(self):
        self.emit(type="cancelled")
