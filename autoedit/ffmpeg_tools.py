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
    result = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True)
    if " subtitles " not in result.stdout:
        raise EditorError(
            "Your FFmpeg was built without libass, so it cannot draw captions.\n"
            "Install a 'full' build instead (winget install Gyan.FFmpeg)."
        )


@lru_cache(maxsize=None)
def ffmpeg_major_version():
    out = subprocess.run([find_tool("ffmpeg"), "-version"], capture_output=True, text=True).stdout
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


def probe(path):
    """Read basic facts about a media file: duration, size, audio/video present."""
    path = Path(path)
    if not path.exists():
        raise EditorError(f"File not found: {path}")
    cmd = [find_tool("ffprobe"), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
    info = {
        "duration": duration,
        "has_video": video is not None,
        "has_audio": audio is not None,
        "width": int(video.get("width", 0)) if video else 0,
        "height": int(video.get("height", 0)) if video else 0,
    }
    return info


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
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", result.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", result.stderr)]
    silences = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else None
        if end is None:  # silence runs to the end of the file
            end = probe(path)["duration"]
        silences.append((max(0.0, start), end))
    return silences
