"""Helpers for the timeline editor: waveform peaks and filmstrip thumbnails, cached on disk.

Both are keyed by the file's full path, size and modification time, so an edited or replaced
file gets fresh ones. Cached files live in work/cache/peaks and work/cache/thumbs.
"""

import array
import hashlib
import json
import os
import subprocess
from pathlib import Path

from .errors import EditorError
from .ffmpeg_tools import find_tool, probe
from .project import media_kind

PEAK_RATE = 8000           # samples per second decoded for the waveform (mono)


def file_key(path, *extra):
    path = Path(path).resolve()
    stat = path.stat()
    raw = f"{path}|{stat.st_size}|{stat.st_mtime_ns}|" + "|".join(str(e) for e in extra)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def peaks(path, cache_dir, per_second=50):
    """Loudness outline of a file's sound: {"duration", "per_second", "peaks": [0-255]}.

    Each value is the highest sample level in 1/per_second of a second (255 = full scale).
    A file without sound gives an empty list.
    """
    path = Path(path)
    if not path.exists():
        raise EditorError(f"File not found: {path}")
    cache = Path(cache_dir) / f"{file_key(path, per_second)}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass                                    # damaged cache file: make it again
    info = probe(path)
    result = {"duration": info["duration"], "per_second": per_second, "peaks": [],
              "has_audio": info["has_audio"]}
    if info["has_audio"]:
        run = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-vn",
                              "-ac", "1", "-ar", str(PEAK_RATE), "-f", "s16le", "-"],
                             capture_output=True, stdin=subprocess.DEVNULL)
        if run.returncode != 0:
            raise EditorError(f"Could not read the sound of '{path.name}': "
                              f"{run.stderr.decode('utf-8', 'replace').strip()[-300:]}")
        samples = array.array("h", run.stdout[: len(run.stdout) // 2 * 2])
        window = max(1, PEAK_RATE // per_second)
        out = []
        for i in range(0, len(samples), window):
            chunk = samples[i:i + window]
            level = max(max(chunk), -min(chunk))
            out.append(min(255, level * 255 // 32767))
        result["peaks"] = out
    _write_json(cache, result)
    return result


def thumbs(path, cache_dir, height=120, max_count=300):
    """Small pictures along a video, for the timeline: {"every", "files": [...]}.

    One picture every `every` seconds (at least 1 s; longer videos get fewer, at most
    `max_count`). An image gives one picture; a sound file gives none.
    """
    path = Path(path)
    if not path.exists():
        raise EditorError(f"File not found: {path}")
    kind = media_kind(path)
    if kind == "audio":
        return {"every": 0, "height": height, "files": []}
    info = probe(path)
    if kind == "video" and not info["has_video"]:
        return {"every": 0, "height": height, "files": []}
    duration = info["duration"] if kind == "video" else 0
    every = max(1.0, round(duration / max_count + 0.4999)) if duration else 0
    folder = Path(cache_dir) / file_key(path, height, max_count)
    index = folder / "thumbs.json"
    if index.exists():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            if all(Path(f).exists() for f in data["files"]):
                return data
        except (ValueError, KeyError):
            pass
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("t*.jpg"):
        old.unlink()
    scale = f"scale=-2:{height}:flags=bilinear"
    if kind == "image":
        args = ["-i", str(path), "-vf", scale, "-frames:v", "1", str(folder / "t00001.jpg")]
    else:
        # Picture n shows the moment n * every (+ half a frame so it is not the previous one).
        args = ["-i", str(path), "-an", "-vf", f"fps=1/{every:g}:start_time=0:round=down,{scale}",
                "-q:v", "6", str(folder / "t%05d.jpg")]
    run = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *args],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if run.returncode != 0:
        raise EditorError(f"Could not make pictures of '{path.name}': {run.stderr.strip()[-300:]}")
    files = sorted(str(f) for f in folder.glob("t*.jpg"))
    data = {"every": every, "height": height, "files": files}
    _write_json(index, data)
    return data


def noise_floor_db(path, window=0.05, percentile=10):
    """Level of the quiet parts of a file's sound (dBFS): the background noise in the pauses.

    The `percentile`-th quietest 50 ms window, measured at the file's own sample rate (all of
    the hiss counts). None if the file has no sound.
    """
    run = subprocess.run(
        [find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "48000",
         "-af", f"asetnsamples=n={int(48000 * window)},astats=metadata=1:reset=1,"
                "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-",
         "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    levels = []
    for line in run.stdout.splitlines():
        if line.startswith("lavfi.astats.Overall.RMS_level="):
            value = line.split("=", 1)[1]
            levels.append(-120.0 if value in ("-inf", "inf", "nan") else float(value))
    if not levels:
        return None
    levels.sort()
    return levels[min(len(levels) - 1, len(levels) * percentile // 100)]
