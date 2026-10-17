"""The Project file: one edit as JSON (media + a timeline of tracks and clips).

The Project is the single source of truth. The AI writes it, the desktop app edits it, and
`project_render.render_project()` turns it into the final MP4 with FFmpeg.

    {
      "format": "autoedit-project", "version": 2, "name": "My video",
      "settings": {"width": 1080, "height": 1920, "fps": 30, ...},
      "media":  [{"id": "m1", "kind": "video", "path": "C:/Videos/talk.mp4", "duration": 62.4}],
      "tracks": [{"id": "main", "kind": "video", "clips": [
                    {"id": "c1", "type": "video", "media": "m1", "start": 0, "duration": 2.5,
                     "in": 0.4, "out": 2.9}]}, ...]
    }

Times: `start`/`duration` are seconds on the timeline; `in`/`out` are seconds in the source
file. On the picture, a clip covers frames round(start*fps) up to (not including)
round((start+duration)*fps). Audio clips are placed sample-accurately.

The structure is checked against project.schema.json (shared with the desktop app); the
checks that JSON Schema cannot express (ids, references, overlaps, lengths) are below.
"""

import copy
import json
import os
from functools import lru_cache
from pathlib import Path

from .errors import EditorError

FORMAT = "autoedit-project"
VERSION = 2                   # 2 adds speed, video-clip fades and crop; 1 still loads
SCHEMA_FILE = Path(__file__).with_name("project.schema.json")

TRACK_KINDS = ("video", "overlay", "effect", "graphics", "caption", "audio")
AUDIO_ROLES = ("original", "voiceover", "music", "sfx")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}

TIME_TOLERANCE = 0.002        # seconds of rounding slack allowed in length checks


class ProjectError(EditorError):
    """The project file is not valid. `problems` lists every problem found."""

    def __init__(self, problems, intro="The project file has problems"):
        self.problems = list(problems)
        shown = "\n".join(f"  - {p}" for p in self.problems[:25])
        more = len(self.problems) - 25
        if more > 0:
            shown += f"\n  ... and {more} more"
        super().__init__(f"{intro}:\n{shown}")


@lru_cache(maxsize=None)
def load_schema():
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def clip_end(clip):
    return clip["start"] + clip["duration"]


def all_clips(project):
    """(track, clip) pairs for every clip in the project."""
    return [(track, clip) for track in project.get("tracks", []) for clip in track["clips"]]


def timeline_duration(project):
    """Length of the finished video: where the last clip on any track ends."""
    return max((clip_end(c) for _t, c in all_clips(project)), default=0.0)


def media_by_id(project):
    return {m["id"]: m for m in project.get("media", [])}


def resolve_media_path(media, base_dir):
    path = Path(media["path"])
    return path if path.is_absolute() else Path(base_dir) / path


# ---------------------------------------------------------------- validation

def _schema_problems(data):
    import jsonschema

    validator = jsonschema.Draft202012Validator(load_schema())
    problems = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = error.json_path.replace("$", "project", 1)
        problems.append(f"{where}: {error.message}")
    return problems


def _semantic_problems(data):
    problems = []
    fps = data["settings"]["fps"]
    frame = 1.0 / fps
    media = {}
    for i, m in enumerate(data["media"]):
        if m["id"] in media:
            problems.append(f"media[{i}]: the id '{m['id']}' is used twice")
        media[m["id"]] = m

    seen_tracks, seen_clips = set(), set()
    video_tracks = 0
    for ti, track in enumerate(data["tracks"]):
        where_t = f"tracks[{ti}] ('{track['id']}')"
        if track["id"] in seen_tracks:
            problems.append(f"{where_t}: the track id is used twice")
        seen_tracks.add(track["id"])
        video_tracks += track["kind"] == "video"

        previous = None
        for clip in sorted(track["clips"], key=lambda c: (c["start"], c["duration"])):
            where = f"{where_t} clip '{clip['id']}'"
            if clip["id"] in seen_clips:
                problems.append(f"{where}: the clip id is used twice")
            seen_clips.add(clip["id"])
            if previous is not None and clip["start"] < clip_end(previous) - TIME_TOLERANCE:
                problems.append(f"{where}: overlaps clip '{previous['id']}' on the same track "
                                f"(starts at {clip['start']:.3f}s, the other ends at "
                                f"{clip_end(previous):.3f}s)")
            previous = clip
            problems += _clip_problems(track, clip, media, frame, where)

    if video_tracks > 1:
        problems.append("tracks: only one main video track is allowed")
    from .tracking import check_track_data
    for media_id, track in (data.get("tracking") or {}).items():
        if media_id not in media:
            problems.append(f"tracking: unknown media '{media_id}'")
        elif media[media_id]["kind"] != "video":
            problems.append(f"tracking: '{media_id}' is not a video")
        problems += [f"tracking['{media_id}']: {p}" for p in check_track_data(track)]
    transcript = data.get("transcript")
    if transcript and transcript["media"] not in media:
        problems.append(f"transcript: unknown media '{transcript['media']}'")
    return problems


def _clip_problems(track, clip, media, frame, where):
    problems = []
    kind, ctype = track["kind"], clip["type"]

    ref = clip.get("media")
    m = media.get(ref) if ref else None
    if ref and m is None:
        return [f"{where}: unknown media '{ref}'"]
    if m is not None:
        wanted = {("video", "video"): ("video",), ("video", "image"): ("image",),
                  ("overlay", "video"): ("video",), ("overlay", "image"): ("image",),
                  ("audio", "audio"): ("audio", "video"),
                  ("effect", "trackfx"): ("video", "image")}[(kind, ctype)]
        if m["kind"] not in wanted:
            problems.append(f"{where}: needs {' or '.join(wanted)} media, but "
                            f"'{ref}' is {m['kind']}")
        if kind == "audio" and m["kind"] == "video" and m.get("has_audio") is False:
            problems.append(f"{where}: media '{ref}' has no sound")

    if ctype == "graphic":
        problems += _graphic_problems(clip, media, where)

    if "in" in clip and "out" in clip:
        length = clip["out"] - clip["in"]
        speed = float(clip.get("speed", 1.0))
        if length <= 0:
            problems.append(f"{where}: 'out' ({clip['out']}) must be after 'in' ({clip['in']})")
        elif abs(length - clip["duration"] * speed) > TIME_TOLERANCE * max(1.0, speed):
            if speed == 1:
                problems.append(f"{where}: out - in ({length:.3f}s) must equal the duration "
                                f"({clip['duration']:.3f}s)")
            else:
                problems.append(f"{where}: out - in ({length:.3f}s) must equal the duration "
                                f"times the speed ({clip['duration']:.3f}s x {speed:g})")
        if m is not None and m["kind"] != "image" and m["duration"] > 0 \
                and clip["out"] > m["duration"] + frame + TIME_TOLERANCE:
            problems.append(f"{where}: 'out' ({clip['out']:.3f}s) is past the end of the media "
                            f"({m['duration']:.3f}s)")

    layout = clip.get("layout")
    if layout:
        screen = media.get(layout["screen"])
        if screen is None:
            problems.append(f"{where}: unknown screen recording media '{layout['screen']}'")
        elif screen["kind"] != "video":
            problems.append(f"{where}: the screen recording '{layout['screen']}' is not a video")

    if clip.get("mask") and kind == "overlay" and clip["mask"]["type"] == "person" and ctype != "video":
        problems.append(f"{where}: a person cut-out needs a video clip")

    if ctype in ("audio", "video"):
        if clip.get("fade_in", 0) + clip.get("fade_out", 0) > clip["duration"] + TIME_TOLERANCE:
            problems.append(f"{where}: fade in + fade out are longer than the clip")

    if ctype == "caption":
        last_start = 0.0
        for wi, word in enumerate(clip["words"]):
            if word["end"] < word["start"]:
                problems.append(f"{where} word {wi} ('{word['text']}'): ends before it starts")
            if word["end"] > clip["duration"] + TIME_TOLERANCE:
                problems.append(f"{where} word {wi} ('{word['text']}'): ends after the caption "
                                f"clip ({word['end']:.3f}s > {clip['duration']:.3f}s)")
            if word["start"] < last_start - TIME_TOLERANCE:
                problems.append(f"{where} word {wi} ('{word['text']}'): words must be in "
                                f"time order")
            last_start = word["start"]
    return problems


def _graphic_problems(clip, media, where):
    """A graphic must use a template of the catalog, with fonts, icons and images that exist."""
    from . import graphics
    problems = []
    if not graphics.has_template(clip["template"]):
        ids = graphics.template_ids()
        problems.append(f"{where}: unknown graphics template '{clip['template']}' "
                        f"(there are {len(ids)}: {', '.join(ids[:6])}, ...)")
        return problems
    params = clip.get("params") or {}
    font = params.get("font")
    if font and font not in graphics.font_keys():
        problems.append(f"{where}: unknown font '{font}' (use one of: "
                        f"{', '.join(graphics.font_keys())})")
    icon = params.get("icon")
    if icon and icon not in graphics.icon_names():
        problems.append(f"{where}: unknown icon '{icon}'")
    image = params.get("image")
    if image:
        m = media.get(image)
        if m is None:
            problems.append(f"{where}: unknown image media '{image}'")
        elif m["kind"] != "image":
            problems.append(f"{where}: the picture '{image}' is {m['kind']}, not an image")
    return problems


def validate_project(data):
    """Return a list of problems (empty = valid)."""
    if not isinstance(data, dict):
        return ["the file does not contain a project (expected a JSON object)"]
    if data.get("format") != FORMAT:
        return [f"this is not a project file ('format' must be '{FORMAT}')"]
    version = data.get("version")
    if isinstance(version, int) and not isinstance(version, bool) and version > VERSION:
        return [f"the project was made by a newer version of the editor (project version "
                f"{version}, this editor reads up to {VERSION}). Please update the editor."]
    problems = _schema_problems(data)
    if problems:
        return problems       # the deeper checks assume the structure is right
    return _semantic_problems(data)


def check_project(data):
    problems = validate_project(data)
    if problems:
        raise ProjectError(problems)
    return data


# ---------------------------------------------------------------- files

def load_project(path):
    path = Path(path)
    if not path.exists():
        raise EditorError(f"Project file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EditorError(f"Project '{path.name}' is not valid JSON: {exc}")
    return check_project(data)


def save_project(data, path):
    """Validate, then write atomically (a crash mid-save never leaves a half-written file)."""
    check_project(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- building

def new_project(name="Untitled", fps=30, normalize_audio=True, loudness=-14, true_peak=-1.5,
                fonts=None):
    """An empty project with the standard tracks."""
    fonts = fonts or {"regular": "Inter", "bold": "Inter", "heavy": "Inter Black"}
    return {
        "format": FORMAT,
        "version": VERSION,
        "name": name,
        "settings": {
            "width": 1080, "height": 1920, "fps": fps, "background": "#000000",
            "audio": {"normalize": normalize_audio, "loudness": loudness, "true_peak": true_peak},
            "fonts": dict(fonts),
        },
        "media": [],
        "tracks": [
            {"id": "main", "kind": "video", "name": "Video", "clips": []},
            {"id": "photos", "kind": "overlay", "name": "Photos", "clips": []},
            {"id": "effects", "kind": "effect", "name": "Effects", "clips": []},
            {"id": "captions", "kind": "caption", "name": "Captions", "clips": []},
            {"id": "voiceover", "kind": "audio", "role": "voiceover", "name": "Voice-over",
             "clips": []},
            {"id": "music", "kind": "audio", "role": "music", "name": "Music", "clips": []},
            {"id": "sfx", "kind": "audio", "role": "sfx", "name": "Sound effects", "clips": []},
        ],
    }


def media_kind(path):
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return "video"


def media_from_file(path, media_id, probe=None):
    """A media entry for a file, with its length and size read by ffprobe."""
    if probe is None:
        from .ffmpeg_tools import probe
    path = Path(path).resolve()
    info = probe(path)
    kind = media_kind(path)
    if kind == "video" and not info["has_video"]:
        kind = "audio" if info["has_audio"] else kind
    if kind == "video" and not info["has_video"]:
        raise EditorError(f"'{path.name}' has no picture or sound.")
    if kind == "audio" and not info["has_audio"]:
        raise EditorError(f"'{path.name}' has no sound.")
    entry = {"id": media_id, "kind": kind, "path": str(path), "name": path.name,
             "duration": 0.0 if kind == "image" else round(info["duration"], 3)}
    if kind != "audio":
        entry["width"], entry["height"] = info["width"], info["height"]
    if kind == "video":
        entry["has_audio"] = info["has_audio"]
    return entry


def assign_lanes(items, start=lambda x: x["start"], end=clip_end):
    """Split items into lanes so that no two items in a lane overlap (first fit, by start)."""
    lanes = []
    for item in sorted(items, key=start):
        for lane in lanes:
            if start(item) >= end(lane[-1]) - TIME_TOLERANCE:
                lane.append(item)
                break
        else:
            lanes.append([item])
    return lanes


def copy_project(project):
    return copy.deepcopy(project)
