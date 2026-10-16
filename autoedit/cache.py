"""Saved transcripts and AI plans, so re-running a video costs nothing.

Transcripts are keyed by the video's content (a SHA-256 of the file), so a renamed or moved
file still hits the cache. Plans are keyed by everything that can change the answer.
"""

import hashlib
import json
import os
from pathlib import Path


def file_fingerprint(path, chunk=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def key_for(data):
    """A stable key for any JSON-able value."""
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, folder):
        self.folder = Path(folder)
        self._fingerprints = {}

    def fingerprint(self, path):
        """Content hash of a file (remembered per path, size and modification time)."""
        path = Path(path).resolve()
        stat = path.stat()
        memo = (str(path), stat.st_size, stat.st_mtime_ns)
        if memo not in self._fingerprints:
            self._fingerprints[memo] = file_fingerprint(path)
        return self._fingerprints[memo]

    def _file(self, kind, key):
        return self.folder / kind / f"{key}.json"

    def get(self, kind, key):
        path = self._file(kind, key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None              # missing or damaged: treat as not cached

    def put(self, kind, key, data):
        path = self._file(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return path
