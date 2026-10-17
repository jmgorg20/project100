"""Motion graphics: the template catalog, drawing graphics to cached videos, and where they sit.

The graphics themselves are HTML/CSS/JS templates (desktop/graphics/) drawn by a Chromium: the
desktop app uses a hidden Electron window, the command line uses Playwright's Chromium (or the
Edge / Chrome on the PC). Either way each graphic becomes a lossless video with transparency
(FFV1, BGRA) plus a small json file with its size, saved under a key made from everything that
changes its pixels. FFmpeg then lays these videos over the picture (project_render.add_graphics).

    key = sha256(template, template version, parameters, fps, frames, renderer version)

so editing one graphic redraws only that graphic, and the same graphic is never drawn twice.
"""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

from . import PROJECT_DIR
from .errors import Cancelled, EditorError
from .ffmpeg_tools import find_tool

CATALOG_FILE = Path(__file__).with_name("graphics_catalog.json")
RENDER_CLI = PROJECT_DIR / "desktop" / "graphics" / "render-cli.mjs"
FRAME_W, FRAME_H = 1080, 1920

PARAM_KEYS = ("text", "text2", "items", "number", "prefix", "suffix", "image", "emoji", "icon",
              "font", "color", "accent", "bg", "size", "intensity", "align", "case", "angle",
              "dir")


# ---------------------------------------------------------------- catalog

@lru_cache(maxsize=None)
def catalog():
    """The template catalog (generated from the JS templates by desktop/graphics/build-catalog.mjs)."""
    return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))


def templates():
    return catalog()["templates"]


@lru_cache(maxsize=None)
def _by_id():
    return {t["id"]: t for t in templates()}


def template_ids():
    return list(_by_id())


def template_meta(template_id):
    meta = _by_id().get(template_id)
    if meta is None:
        raise EditorError(f"Unknown graphics template '{template_id}'.")
    return meta


def has_template(template_id):
    return template_id in _by_id()


def font_keys():
    return list(catalog()["fonts"])


def icon_names():
    return list(catalog()["icons"])


# ---------------------------------------------------------------- positions and sizes

def estimated_box(clip, meta=None, rendered=None):
    """(x0, y0, x1, y1) in frame pixels of what the graphic covers (the shapes, no soft glow).

    `rendered` is the size the drawn graphic reported ({"w", "h"}): exact. Without it the size
    is estimated from the catalog (the template's box at its size)."""
    meta = meta or template_meta(clip["template"])
    size = float((clip.get("params") or {}).get("size", 1.0))
    if rendered:
        w, h = float(rendered["w"]), float(rendered["h"])
    else:
        w, h = meta["box"]["w"] * size, meta["box"]["h"] * size
    cx, cy = clip["x"] * FRAME_W, clip["y"] * FRAME_H
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def tip_point(clip, meta=None):
    """Where a pointer (arrow / circle) points to, in frame pixels; the centre for other graphics."""
    meta = meta or template_meta(clip["template"])
    params = clip.get("params") or {}
    cx, cy = clip["x"] * FRAME_W, clip["y"] * FRAME_H
    tip = meta.get("tip")
    if not tip:
        return cx, cy
    import math
    ang = math.radians(float(params.get("angle", 0)))
    d = tip["dist"] * float(params.get("size", 1.0))
    return cx + d * math.cos(ang), cy + d * math.sin(ang)


# ---------------------------------------------------------------- keys and jobs

def cache_dir():
    override = os.environ.get("AUTOEDIT_GRAPHICS_CACHE")
    return Path(override) if override else PROJECT_DIR / "work" / "cache" / "graphics"


def _frames(clip, fps):
    from .project_render import clip_frames
    f0, f1 = clip_frames(clip, fps)
    return f0, f1


def _image_path(params, media, base_dir):
    ref = params.get("image")
    if not ref:
        return None
    from .project import resolve_media_path
    m = media.get(ref)
    if m is None:
        return None
    return resolve_media_path(m, base_dir)


def _fingerprint(path):
    try:
        st = Path(path).stat()
        return f"{st.st_size}-{int(st.st_mtime)}"
    except OSError:
        return "missing"


def job_for_clip(clip, fps, media, base_dir, directory=None):
    """The drawing job for one graphic clip: {"key", "template", "params", "frames", "out", ...}."""
    meta = template_meta(clip["template"])
    f0, f1 = _frames(clip, fps)
    frames = max(1, f1 - f0)
    params = {k: v for k, v in (clip.get("params") or {}).items() if v is not None}
    image = _image_path(params, media, base_dir)
    drawn = dict(params)
    if image is not None:
        drawn["image"] = str(image)
    else:
        drawn.pop("image", None)
    basis = {"t": clip["template"], "tv": meta["version"], "r": catalog()["renderer"],
             "p": {**params, "image": _fingerprint(image) if image else None}, "fps": fps,
             "frames": frames}
    key = hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    directory = Path(directory) if directory else cache_dir()
    return {"key": key, "template": clip["template"], "params": drawn, "fps": fps, "frames": frames,
            "duration": frames / fps, "quality": "final", "out": str(directory / f"{key}.mkv"),
            "meta": str(directory / f"{key}.json"), "clip": clip["id"]}


def graphic_clips(project):
    """[(track, clip)] of every graphic on a visible graphics track."""
    return [(t, c) for t in project["tracks"] if t["kind"] == "graphics" and not t.get("hidden")
            for c in sorted(t["clips"], key=lambda c: c["start"]) if c["type"] == "graphic"]


def project_jobs(project, base_dir, directory=None):
    """All drawing jobs of a project, one per distinct graphic (same pixels = one job)."""
    from .project import media_by_id
    fps = project["settings"]["fps"]
    media = media_by_id(project)
    jobs, seen = [], set()
    for _track, clip in graphic_clips(project):
        job = job_for_clip(clip, fps, media, base_dir, directory)
        if job["key"] not in seen:
            seen.add(job["key"])
            jobs.append(job)
    return jobs


def is_drawn(job):
    return Path(job["out"]).exists() and Path(job["meta"]).exists()


def missing_jobs(project, base_dir, directory=None):
    return [j for j in project_jobs(project, base_dir, directory) if not is_drawn(j)]


def read_meta(job):
    try:
        return json.loads(Path(job["meta"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- drawing

def renderer_command():
    """The command that draws jobs: AUTOEDIT_GRAPHICS_RENDERER, else Node + the bundled script."""
    override = os.environ.get("AUTOEDIT_GRAPHICS_RENDERER")
    if override:
        return shlex.split(override, posix=(os.name != "nt"))
    node = shutil.which("node")
    if node and RENDER_CLI.exists():
        return [node, str(RENDER_CLI)]
    return None


NO_RENDERER = ("The graphics (pop-up words, cards, arrows...) have not been drawn yet, and this "
               "computer cannot draw them from the command line: install Node.js "
               "(https://nodejs.org) and Microsoft Edge or Chrome, or use the desktop app, which "
               "draws them itself.")


def draw_jobs(jobs, reporter=None, cancel=None):
    """Draw jobs to their files with the renderer command. Raises EditorError if it cannot."""
    if not jobs:
        return
    cmd = renderer_command()
    if cmd is None:
        raise EditorError(NO_RENDERER)
    from .project import ProjectError  # noqa: F401  (keeps import order stable)
    directory = Path(jobs[0]["out"]).parent
    directory.mkdir(parents=True, exist_ok=True)
    spec = directory / f"jobs-{os.getpid()}-{threading.get_ident()}.json"
    spec.write_text(json.dumps({"ffmpeg": find_tool("ffmpeg"), "jobs": jobs}), encoding="utf-8")
    if reporter:
        reporter.stage("graphics", "drawing the graphics")
    try:
        proc = subprocess.Popen(cmd + [str(spec)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                errors="replace")
        stop = threading.Event()
        err = []

        def watch():
            while proc.poll() is None and not stop.is_set():
                if cancel is not None and cancel.wait(0.2):
                    proc.terminate()
                    return

        def read_err():
            for line in proc.stderr:
                err.append(line.rstrip())
                del err[:-20]

        threading.Thread(target=watch, daemon=True).start()
        threading.Thread(target=read_err, daemon=True).start()
        failure = None
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "progress" and reporter and event.get("total"):
                reporter.progress(event["done"] / event["total"], stage="graphics")
            elif event.get("type") == "error":
                failure = event.get("message")
        proc.wait()
        stop.set()
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled while drawing the graphics.")
        if proc.returncode != 0:
            raise EditorError("Could not draw the graphics: "
                              + (failure or " ".join(err[-3:]) or f"exit code {proc.returncode}"))
    finally:
        try:
            spec.unlink()
        except OSError:
            pass
    still_missing = [j for j in jobs if not is_drawn(j)]
    if still_missing:
        raise EditorError(f"The graphics renderer finished but {len(still_missing)} graphic(s) "
                          "were not written.")


def ensure_assets(project, base_dir, reporter=None, cancel=None, mode="require", directory=None):
    """Make sure every graphic of the project is drawn. Returns the jobs that could not be drawn.

    mode "require": draw what is missing, raise EditorError if that is not possible.
    mode "skip":    draw what is possible; return the missing jobs instead of raising."""
    missing = missing_jobs(project, base_dir, directory)
    if not missing:
        return []
    try:
        draw_jobs(missing, reporter, cancel)
    except EditorError:
        if mode == "skip":
            return [j for j in missing if not is_drawn(j)]
        raise
    return []


def render_layers(project, base_dir, directory=None):
    """The drawn graphics for project_render: [{"path", "f0", "f1", "x", "y", "tw", "th"}]."""
    from .project import media_by_id
    fps = project["settings"]["fps"]
    media = media_by_id(project)
    layers = []
    for _track, clip in graphic_clips(project):
        job = job_for_clip(clip, fps, media, base_dir, directory)
        meta = read_meta(job)
        if meta is None or not Path(job["out"]).exists():
            continue
        f0, f1 = _frames(clip, fps)
        tw, th = int(meta["tileW"]), int(meta["tileH"])
        layers.append({"path": job["out"], "f0": f0, "f1": f1, "tw": tw, "th": th,
                       "x": round(clip["x"] * FRAME_W - tw / 2), "y": round(clip["y"] * FRAME_H - th / 2),
                       "clip": clip["id"]})
    return layers


# ---------------------------------------------------------------- emphasis transitions

ATTACH_KINDS = ("flash", "whip", "punch")


def attach_clips(project):
    """Synthetic effect clips for the graphics' `attach` transitions (flash / whip / punch-in at
    the graphic's start). They are not saved in the project: the renderer and the editor's
    preview both add them, so the transition follows the graphic when it is moved."""
    fps = project["settings"]["fps"]
    out = []
    for _track, clip in graphic_clips(project):
        attach = clip.get("attach")
        if not attach:
            continue
        kind = attach["kind"]
        k = float(attach.get("intensity", 0.6))
        start = clip["start"]
        frame = 1.0 / fps
        if kind == "flash":
            out.append({"id": f"att-{clip['id']}", "type": "fx", "effect": "flash", "start": start,
                        "duration": max(3 * frame, 0.14), "intensity": k})
        elif kind == "whip":
            out.append({"id": f"att-{clip['id']}", "type": "fx", "effect": "whip", "start": start,
                        "duration": max(4 * frame, 0.2), "intensity": k})
        elif kind == "punch":
            out.append({"id": f"att-{clip['id']}", "type": "zoom", "start": start,
                        "duration": min(clip["duration"], 0.5), "amount": round(1.04 + 0.12 * k, 3),
                        "ease": 0.12})
    return out


def expand_attachments(project):
    """The project plus a hidden-from-the-user effects track holding the synthetic transitions."""
    extra = attach_clips(project)
    if not extra:
        return project
    expanded = dict(project)
    expanded["tracks"] = list(project["tracks"]) + [
        {"id": "attach-fx", "kind": "effect", "name": "Graphic transitions", "clips": extra}]
    return expanded
