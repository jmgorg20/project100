"""Checking uploaded files before anything uses them.

A file is accepted only if: its extension is allowed, its size is within the limit, an optional
scanner (e.g. ClamAV) says it is clean, and ffprobe (with a time limit, never a shell) reads it as
the kind its extension says: a video has a video stream and a duration within the limit, a picture
is one image frame, a sound has an audio stream. Project files (.json) must be valid projects.
Nothing in an upload is ever executed.
"""

import json
import shlex
import subprocess
from pathlib import Path

VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".3gp"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO = {".wav", ".mp3", ".m4a", ".aac"}
PROJECT = {".json"}
MAX_PROJECT_BYTES = 2 * 1024 * 1024
# The demuxer is chosen from the extension, never guessed from the content: a text file named
# .mp4 cannot be read as a playlist (HLS / concat) that would make FFmpeg open other files or URLs.
DEMUXER = {".mp4": "mov", ".mov": "mov", ".m4v": "mov", ".3gp": "mov", ".m4a": "mov", ".mkv": "matroska",
           ".webm": "matroska", ".jpg": "image2", ".jpeg": "image2", ".png": "image2", ".webp": "image2",
           ".wav": "wav", ".mp3": "mp3", ".aac": "aac"}
VIDEO_CODECS = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4", "prores", "mjpeg"}
AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "flac", "alac", "ac3"}
IMAGE_CODECS = {"mjpeg", "png", "webp"}


class MediaError(Exception):
    pass


def kind_of(filename):
    ext = Path(filename).suffix.lower()
    for kind, exts in (("video", VIDEO), ("image", IMAGE), ("audio", AUDIO), ("project", PROJECT)):
        if ext in exts:
            return kind
    return None


def safe_filename(name):
    """A display name only (never used in a path)."""
    name = Path(str(name or "file")).name
    cleaned = "".join(c for c in name if c.isprintable() and c not in '<>:"/\\|?*')
    return cleaned[:120] or "file"


def ffprobe(path, timeout=60, demuxer=None):
    from autoedit.ffmpeg_tools import find_tool
    cmd = [find_tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file"]
    if demuxer:
        cmd += ["-f", demuxer] + (["-pattern_type", "none"] if demuxer == "image2" else [])
    cmd += ["-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise MediaError("The file took too long to read; it may be damaged.")
    if r.returncode != 0:
        raise MediaError("This is not a readable video, picture or sound file.")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise MediaError("This is not a readable video, picture or sound file.")


def scan(path, command):
    """Run the configured scanner on the file (exit code 0 = clean)."""
    if not command:
        return
    args = [a.replace("{path}", str(path)) for a in shlex.split(command)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"The file could not be scanned ({exc}); it was not accepted.")
    if r.returncode != 0:
        raise MediaError("The file did not pass the safety scan.")


def moderate(path, command):
    """Your content check (SERVICE_MODERATION_COMMAND): exit 0 = allowed. Its first output line is
    the reason shown when a file is refused. Fails closed: if the check cannot run, the file is refused."""
    if not command:
        return
    args = [a.replace("{path}", str(path)) for a in shlex.split(command)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"The file could not be checked ({exc.__class__.__name__}); it was not accepted.")
    if r.returncode != 0:
        reason = (r.stdout or "").strip().splitlines()[:1]
        raise MediaError("The file was not accepted by the content check" + (f": {reason[0][:200]}" if reason else "."))


def check(path, filename, max_duration):
    """What the file is: {"kind", "duration", "width", "height", "has_audio", "format"}.
    Raises MediaError with a message for the user."""
    kind = kind_of(filename)
    if kind is None:
        raise MediaError("This kind of file is not accepted. Use a video (mp4, mov, webm...), a picture "
                         "(jpg, png, webp) or a sound (wav, mp3, m4a).")
    if kind == "project":
        if Path(path).stat().st_size > MAX_PROJECT_BYTES:
            raise MediaError("The project file is too big.")
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise MediaError("The project file is not valid JSON.")
        from autoedit.project import validate_project
        problems = validate_project(data) if isinstance(data, dict) else ["not a project"]
        if problems:
            raise MediaError("The project file has problems: " + "; ".join(problems[:3]))
        return {"kind": "project", "duration": None}
    info = ffprobe(path, demuxer=DEMUXER.get(Path(filename).suffix.lower()))
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = info.get("format", {})
    duration = float(fmt.get("duration") or 0) or None
    if kind == "video":
        moving = [s for s in video if (s.get("disposition") or {}).get("attached_pic") != 1]
        if not moving:
            raise MediaError("This file has no video picture.")
        if moving[0].get("codec_name") not in VIDEO_CODECS:
            raise MediaError(f"This video's format ({moving[0].get('codec_name')}) is not supported; use H.264 MP4.")
        if audio and audio[0].get("codec_name") not in AUDIO_CODECS:
            raise MediaError(f"This video's sound format ({audio[0].get('codec_name')}) is not supported.")
        if not duration:
            raise MediaError("The video's length could not be read.")
        if duration > max_duration:
            raise MediaError(f"The video is too long ({duration / 60:.1f} min); the limit is {max_duration / 60:.0f} min.")
        v = moving[0]
        return {"kind": "video", "duration": duration, "width": v.get("width"), "height": v.get("height"),
                "has_audio": bool(audio), "format": fmt.get("format_name")}
    if kind == "image":
        if not video or video[0].get("codec_name") not in IMAGE_CODECS:
            raise MediaError("This is not a picture.")
        v = video[0]
        if (v.get("width") or 0) * (v.get("height") or 0) > 80_000_000:
            raise MediaError("The picture is too big (more than 80 megapixels).")
        return {"kind": "image", "duration": None, "width": v.get("width"), "height": v.get("height"),
                "format": fmt.get("format_name")}
    if not audio or audio[0].get("codec_name") not in AUDIO_CODECS:
        raise MediaError("This file has no sound in a supported format.")
    if duration and duration > max_duration:
        raise MediaError(f"The sound is too long; the limit is {max_duration / 60:.0f} min.")
    return {"kind": "audio", "duration": duration, "format": fmt.get("format_name")}
