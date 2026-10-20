"""Small helpers around the ffmpeg / ffprobe command line programs."""

import json
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from .errors import EditorError

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".3gp"}

INSTALL_HINT = (
    "Install FFmpeg and make sure it is on your PATH.\n"
    "  Windows: open PowerShell and run:  winget install Gyan.FFmpeg\n"
    "  then close and reopen the terminal. See README.md, step 2."
)


@lru_cache(maxsize=None)
def find_tool(name):
    """Return the full path of ffmpeg or ffprobe, or raise a friendly error."""
    path = shutil.which(name)
    if not path:
        raise EditorError(f"Could not find '{name}'. {INSTALL_HINT}")
    return path


def check_ffmpeg():
    """Make sure ffmpeg + ffprobe exist and ffmpeg can burn in subtitles."""
    ffmpeg = find_tool("ffmpeg")
    find_tool("ffprobe")
    result = tool_run([ffmpeg, "-hide_banner", "-filters"], 60, "FFmpeg (-filters)")
    if " subtitles " not in result.stdout:
        raise EditorError(
            "Your FFmpeg was built without libass, so it cannot draw captions.\n"
            "Install a 'full' build instead (winget install Gyan.FFmpeg)."
        )


@lru_cache(maxsize=None)
def ffmpeg_major_version():
    out = tool_run([find_tool("ffmpeg"), "-version"], 60, "FFmpeg (-version)").stdout
    match = re.search(r"ffmpeg version n?(\d+)\.", out)
    return int(match.group(1)) if match else 7  # git builds have no number: assume new


def filter_script_args(script_path):
    """Arguments that make ffmpeg read the filter graph from a file.

    Using a file avoids the Windows command-line length limit when the
    graph is long (many cuts).
    """
    if ffmpeg_major_version() >= 7:
        return ["-/filter_complex", str(script_path)]
    return ["-filter_complex_script", str(script_path)]


PROBE_TIMEOUT = 60


def tool_run(cmd, timeout, what):
    """A short FFmpeg / ffprobe call: no input (it never shares the app's stdin pipe), its output
    captured, and a time limit (a stuck tool is an error that says which, never a silent wait)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise EditorError(f"{what} did not finish within {timeout} s and was stopped.")


def probe(path):
    """Read basic facts about a media file: duration, size, audio/video present."""
    path = Path(path)
    if not path.exists():
        raise EditorError(f"File not found: {path}")
    cmd = [find_tool("ffprobe"), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    result = tool_run(cmd, PROBE_TIMEOUT, f"ffprobe ({path.name})")
    if result.returncode != 0:
        raise EditorError(
            f"FFmpeg cannot read '{path.name}'. It may be damaged or not a video/image file.\n"
            f"Details: {result.stderr.strip()[-300:]}"
        )
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0 and (video or audio):
        duration = decoded_duration(path)
    info = {
        "duration": duration,
        "has_video": video is not None,
        "has_audio": audio is not None,
        "width": int(video.get("width", 0)) if video else 0,
        "height": int(video.get("height", 0)) if video else 0,
    }
    return info


def decoded_duration(path):
    """Length found by decoding the file, for files that do not state it (e.g. a voice-over
    recorded in the app: browsers write WebM without a duration). 0 if it cannot be read."""
    import re
    result = tool_run([find_tool("ffmpeg"), "-nostdin", "-v", "info", "-nostats", "-i", str(path),
                       "-progress", "pipe:1", "-f", "null", "-"], 300, f"FFmpeg (length of {Path(path).name})")
    times = re.findall(r"out_time_us=(\d+)", result.stdout)
    return int(times[-1]) / 1e6 if times else 0.0


def probe_video_with_audio(path):
    """Probe a talking video and complain clearly if it is not usable."""
    path = Path(path)
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise EditorError(
            f"'{path.name}' does not look like a video file. "
            f"Supported: {', '.join(sorted(VIDEO_EXTENSIONS))}"
        )
    info = probe(path)
    if not info["has_video"]:
        raise EditorError(f"'{path.name}' has no video picture.")
    if not info["has_audio"]:
        raise EditorError(
            f"'{path.name}' has no audio track, so there is no speech to transcribe or cut."
        )
    if info["duration"] <= 0.5:
        raise EditorError(f"'{path.name}' is too short ({info['duration']:.1f}s).")
    return info


def run_ffmpeg(args, description, cwd=None, show_progress=True):
    """Run ffmpeg with the given arguments. Shows progress; raises EditorError on failure."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-y", "-loglevel", "error"]
    if show_progress:
        cmd.append("-stats")
    cmd += [str(a) for a in args]
    print(f"  > {description}")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    tail = b""
    while True:
        chunk = proc.stderr.read(256)
        if not chunk:
            break
        tail = (tail + chunk)[-4000:]
        if show_progress:
            sys.stderr.write(chunk.decode("utf-8", errors="replace"))
            sys.stderr.flush()
    proc.wait()
    if show_progress:
        sys.stderr.write("\n")
    if proc.returncode != 0:
        message = tail.decode("utf-8", errors="replace")
        # Keep only real error lines, not the progress counter.
        lines = [l for l in re.split(r"[\r\n]+", message) if l.strip() and not l.startswith("frame=")]
        raise EditorError(f"FFmpeg failed while: {description}\n" + "\n".join(lines[-12:]))


def detect_silences(path, noise_db, min_duration):
    """Use ffmpeg's silencedetect to find quiet parts of the audio. Returns [(start, end)]."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-vn",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}", "-f", "null", "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", result.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", result.stderr)]
    silences = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else None
        if end is None:  # silence runs to the end of the file
            end = probe(path)["duration"]
        silences.append((max(0.0, start), end))
    return silences


def run_ffmpeg_progress(args, description, total_seconds, on_progress=None, cwd=None,
                        cancel=None):
    """Run ffmpeg, calling on_progress(fraction 0..1) as it goes.

    `cancel` is a threading.Event: when it is set, ffmpeg is stopped and Cancelled is raised.
    Raises EditorError (with FFmpeg's own error lines) if ffmpeg fails.
    """
    import threading

    from .errors import Cancelled

    cmd = [find_tool("ffmpeg"), "-hide_banner", "-y", "-loglevel", "error", "-nostats",
           "-progress", "pipe:1"] + [str(a) for a in args]
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    tail = []

    def read_errors():
        for raw in proc.stderr:
            tail.append(raw.decode("utf-8", errors="replace").rstrip())
            del tail[:-40]

    def watch_cancel():
        while proc.poll() is None:
            if cancel.wait(0.2):
                proc.terminate()
                return

    threads = [threading.Thread(target=read_errors, daemon=True)]
    if cancel is not None:
        threads.append(threading.Thread(target=watch_cancel, daemon=True))
    for t in threads:
        t.start()
    try:
        for raw in proc.stdout:
            key, _, value = raw.decode("utf-8", errors="replace").strip().partition("=")
            # out_time_us is microseconds (out_time_ms is too, despite its name).
            if key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit() \
                    and on_progress and total_seconds > 0:
                on_progress(min(1.0, max(0.0, int(value) / 1e6 / total_seconds)))
        proc.wait()
    finally:
        if proc.poll() is None:          # interrupted (Ctrl+C, error in a callback)
            proc.kill()
            proc.wait()
        threads[0].join(timeout=5)
    if cancel is not None and cancel.is_set():
        raise Cancelled(f"Cancelled while {description}.")
    if proc.returncode != 0:
        lines = [l for l in tail if l.strip()]
        raise EditorError(f"FFmpeg failed while: {description}\n" + "\n".join(lines[-12:]))
    if on_progress:
        on_progress(1.0)
