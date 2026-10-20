"""Quality control: objective checks on a rendered video and its project.

Every check measures something (a size, a length, a level, a position) and passes or fails; none of
them is an opinion about whether the video is good. Opinions (the AI's notes) are kept apart, in
`opinions`, by `polish.py`.

    dimensions      the MP4's width x height is the project's
    duration        its length is the timeline's (within 2 frames + 0.1 s)
    valid_mp4       ffprobe reads it: an MP4 with an H.264 video stream and an audio stream, and
                    it decodes to the end without errors
    av_sync         the audio and video streams start together and are equally long (0.1 s)
    black_frames    no stretch of black picture longer than 0.5 s
    silence         no silence of 1.5 s or more where the captions say someone speaks
    clipping        the sound never reaches 0 dBFS (peak <= -0.1 dB)
    safe_zones      graphics stay on screen and out of the app buttons' area
    face            no graphic covers the speaker's face (the face track, else the usual face area)
    missing_assets  every file the project uses exists
    caption_timing  caption words are in order, inside their caption, on screen long enough to
                    read, and no caption runs past the end of the video

Each result: {"id", "label", "ok", "severity" ("error" | "warning"), "message", "details"}.
"""

import json
import re
import subprocess
from pathlib import Path

from .ffmpeg_tools import find_tool

BLACK_MIN = 0.5
SILENCE_MIN = 1.5
SILENCE_DB = -50
PEAK_LIMIT = -0.1
SYNC_TOLERANCE = 0.1
MIN_CAPTION = 0.3

LABELS = {
    "dimensions": "Size (width x height)", "duration": "Length", "valid_mp4": "Valid MP4",
    "av_sync": "Sound in sync with picture", "black_frames": "No black frames",
    "silence": "No unexpected silence", "clipping": "No clipping (sound too loud)",
    "safe_zones": "Text inside the safe area", "face": "Nothing on the face",
    "missing_assets": "No missing files", "caption_timing": "Caption timing",
}
SEVERITY = {"dimensions": "error", "duration": "error", "valid_mp4": "error", "av_sync": "error",
            "missing_assets": "error", "clipping": "warning", "black_frames": "warning",
            "silence": "warning", "safe_zones": "warning", "face": "warning", "caption_timing": "warning"}


def result(check, ok, message, **details):
    return {"id": check, "label": LABELS[check], "ok": bool(ok), "severity": SEVERITY[check],
            "message": message, "details": details}


# ---------------------------------------------------------------- measuring the file

def ffprobe(path):
    cmd = [find_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
           str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        return None, (r.stderr or "ffprobe could not read the file").strip()[-500:]
    try:
        return json.loads(r.stdout), None
    except ValueError as exc:
        return None, str(exc)


def scan(path):
    """One decoding pass: errors, black stretches, silences and the sound's peak level."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostats", "-v", "info", "-xerror", "-i", str(path),
           "-vf", f"blackdetect=d={BLACK_MIN}:pix_th=0.10",
           "-af", f"silencedetect=n={SILENCE_DB}dB:d={SILENCE_MIN},astats=measure_perchannel=none",
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    log = r.stderr or ""
    black = [(float(a), float(b)) for a, b in
             re.findall(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", log)]
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", log)]
    silences = list(zip(starts, ends))
    if len(starts) > len(ends):                     # silent until the end
        silences.append((starts[-1], None))
    peaks = [float(x) for x in re.findall(r"Peak level dB:\s*(-?[\d.]+|-inf)", log) if x != "-inf"]
    errors = [line for line in log.splitlines()
              if re.search(r"error|invalid|corrupt", line, re.I) and "silence" not in line]
    return {"ok": r.returncode == 0, "black": black, "silences": silences,
            "peak": max(peaks) if peaks else None, "errors": errors[:5]}


# ---------------------------------------------------------------- the checks

def check_file(path, project):
    """The checks that need the rendered MP4."""
    from .project import timeline_duration
    out = []
    path = Path(path)
    if not path.exists():
        return [result("valid_mp4", False, f"There is no video at {path}.")]
    info, problem = ffprobe(path)
    if info is None:
        return [result("valid_mp4", False, f"The file cannot be read as a video: {problem}")]
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = info.get("format", {})
    settings = project["settings"]
    fps = float(settings.get("fps", 30))

    # dimensions
    want = (int(settings["width"]), int(settings["height"]))
    got = (int(video.get("width", 0)), int(video.get("height", 0))) if video else (0, 0)
    out.append(result("dimensions", got == want,
                      f"{got[0]}x{got[1]}" + ("" if got == want else f", expected {want[0]}x{want[1]}"),
                      width=got[0], height=got[1], expected=list(want)))

    # duration
    length = float(fmt.get("duration") or 0)
    expected = timeline_duration(project)
    tolerance = 2 / fps + 0.1
    out.append(result("duration", abs(length - expected) <= tolerance,
                      f"{length:.2f} s" + ("" if abs(length - expected) <= tolerance
                                           else f", the timeline is {expected:.2f} s"),
                      seconds=round(length, 3), expected=round(expected, 3)))

    # valid MP4 (container, codecs, decodes to the end)
    scanned = scan(path)
    problems = []
    if "mp4" not in str(fmt.get("format_name", "")):
        problems.append(f"the container is {fmt.get('format_name')}, not MP4")
    if not video or video.get("codec_name") != "h264":
        problems.append("no H.264 video stream")
    if not audio:
        problems.append("no sound stream")
    if not scanned["ok"] or scanned["errors"]:
        problems.append("it does not decode cleanly: " + "; ".join(scanned["errors"][:2]))
    out.append(result("valid_mp4", not problems, "OK: MP4, H.264 + sound, decodes to the end"
                      if not problems else "Problems: " + ", ".join(problems), problems=problems))

    # A/V sync
    if video and audio:
        v0, a0 = float(video.get("start_time") or 0), float(audio.get("start_time") or 0)
        vd, ad = float(video.get("duration") or length), float(audio.get("duration") or length)
        offset, gap = abs(v0 - a0), abs(vd - ad)
        ok = offset <= SYNC_TOLERANCE and gap <= SYNC_TOLERANCE + 1 / fps
        out.append(result("av_sync", ok, "In sync" if ok else
                          f"Sound starts {a0 - v0:+.2f} s from the picture and is {ad - vd:+.2f} s longer",
                          start_offset=round(a0 - v0, 3), length_difference=round(ad - vd, 3)))
    else:
        out.append(result("av_sync", False, "Cannot check: the video has no sound stream."))

    # black frames
    black = [(a, b) for a, b in scanned["black"] if b - a >= BLACK_MIN]
    out.append(result("black_frames", not black, "None" if not black else
                      f"{len(black)} black stretch(es): " + ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in black[:4]),
                      stretches=[[round(a, 2), round(b, 2)] for a, b in black]))

    # unexpected silence: silent while the captions say someone speaks
    speech = speech_ranges(project)
    unexpected = []
    for a, b in scanned["silences"]:
        b = length if b is None else b
        talk = sum(max(0.0, min(b, y) - max(a, x)) for x, y in speech)
        if talk >= 0.5:
            unexpected.append((a, b))
    out.append(result("silence", not unexpected, "None" if not unexpected else
                      "Silent while the captions show words: " +
                      ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in unexpected[:4]),
                      stretches=[[round(a, 2), round(b, 2)] for a, b in unexpected]))

    # clipping
    peak = scanned["peak"]
    if peak is None:
        out.append(result("clipping", audio is None, "No sound to measure."))
    else:
        out.append(result("clipping", peak <= PEAK_LIMIT, f"Peak {peak:.1f} dB" +
                          ("" if peak <= PEAK_LIMIT else ": the sound is clipping (too loud)"), peak_db=peak))
    return out


def speech_ranges(project):
    """When someone speaks, from the caption words (timeline seconds)."""
    out = []
    for t in project["tracks"]:
        if t["kind"] != "caption":
            continue
        for c in t["clips"]:
            for w in c.get("words") or []:
                out.append((c["start"] + w["start"], c["start"] + w["end"]))
    return out


def check_project(project, base_dir=".", cfg=None):
    """The checks that need only the project: safe zones, face, missing files, caption timing."""
    from .graphics_check import check_project as graphics_issues
    from .project import timeline_duration
    out = []
    issues = graphics_issues(project, base_dir, cfg)
    unsafe = [i for i in issues if i["kind"] in ("off-screen", "safe-area")]
    out.append(result("safe_zones", not unsafe, "All graphics inside the safe area" if not unsafe else
                      "; ".join(i["message"] for i in unsafe[:3]), clips=[i["clip"] for i in unsafe]))
    face = [i for i in issues if i["kind"] == "face"]
    out.append(result("face", not face, "No graphic on the face" if not face else
                      "; ".join(i["message"] for i in face[:3]), clips=[i["clip"] for i in face]))

    base = Path(base_dir)
    missing = []
    for m in project.get("media", []):
        p = Path(m["path"])
        if not p.is_absolute():
            p = base / p
        if not p.exists():
            missing.append(m["path"])
    out.append(result("missing_assets", not missing, "All files found" if not missing else
                      f"{len(missing)} file(s) missing: " + ", ".join(missing[:3]), files=missing))

    end = timeline_duration(project)
    bad = []
    for t in project["tracks"]:
        if t["kind"] != "caption":
            continue
        for c in t["clips"]:
            words = c.get("words") or []
            last = 0.0
            for w in words:
                if not (0 - 1e-6 <= w["start"] <= w["end"] <= c["duration"] + 1e-6) or w["start"] < last - 1e-6:
                    bad.append((c["id"], "words out of order or outside the caption"))
                    break
                last = w["start"]
            if c["duration"] < MIN_CAPTION:
                bad.append((c["id"], f"on screen only {c['duration']:.2f} s"))
            if c["start"] + c["duration"] > end + 1e-3:
                bad.append((c["id"], "runs past the end of the video"))
    out.append(result("caption_timing", not bad, "OK" if not bad else
                      "; ".join(f"caption {cid}: {why}" for cid, why in bad[:3]),
                      captions=[cid for cid, _ in bad]))
    return out


def run(video, project, base_dir=".", cfg=None):
    """All checks. Returns {"passed": bool (no failed error), "checks": [...], "failed": [ids]}."""
    checks = check_file(video, project) + check_project(project, base_dir, cfg)
    failed = [c["id"] for c in checks if not c["ok"]]
    errors = [c["id"] for c in checks if not c["ok"] and c["severity"] == "error"]
    return {"passed": not errors, "clean": not failed, "checks": checks, "failed": failed, "errors": errors}
