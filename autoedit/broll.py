"""The B-roll director: finds or makes the pictures and clips the plan asks for.

For every B-roll item of the plan (`ai_clips`: what to show, search words, a look), in this
order, unless the plan names one source:

    1. your own B-roll library  (a folder; files are matched by their file and folder names)
    2. free stock               (Pexels / Pixabay, only with YOUR free key; credits kept)
    3. AI generation            (WanGP with the normal tiers: draft, then final; GPU lock,
                                 fallback and per-video limits as in ai_gen.py)

Nothing is downloaded except the stock pictures/clips you asked for (never models). Every item
keeps where it came from (clip["broll"] in the project), so the editor can show the credit and
the licence, label AI-made content, and "find another" or "regenerate" it.
"""

import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import stock
from .ai_gen import generate_for_plan
from .config import project_path
from .errors import Cancelled, EditorError
from .ffmpeg_tools import VIDEO_EXTENSIONS
from .overlays import IMAGE_EXTENSIONS

STYLES = ("realistic", "cartoon", "drawing", "low_poly", "stylized_3d", "anime")
STYLE_LABELS = {"realistic": "Realistic", "cartoon": "Cartoon", "drawing": "Drawing / sketch",
                "low_poly": "Low-poly / boxy 3D", "stylized_3d": "Stylized 3D / robot",
                "anime": "Anime"}
# Added to the AI prompt, so the generated picture has the chosen look.
STYLE_PROMPTS = {
    "realistic": "photorealistic, natural light, real camera footage",
    "cartoon": "flat 2D cartoon illustration, bold outlines, bright colours",
    "drawing": "hand-drawn pencil sketch on paper, loose lines",
    "low_poly": "low-poly 3D render, simple boxy geometric shapes, soft lighting",
    "stylized_3d": "stylized 3D render, toy-like robot style, soft studio lighting",
    "anime": "anime illustration, clean cel shading",
}
# Words that mark a library file (or folder) as having a look, and extra stock search words.
STYLE_TAGS = {
    "cartoon": {"cartoon", "toon", "illustration", "vector", "2d"},
    "drawing": {"drawing", "sketch", "drawn", "pencil", "doodle"},
    "low_poly": {"lowpoly", "low_poly", "polygon", "voxel", "boxy"},
    "stylized_3d": {"3d", "robot", "render", "stylized"},
    "anime": {"anime", "manga"},
}
STOCK_WORDS = {"cartoon": "cartoon", "drawing": "drawing", "low_poly": "low poly",
               "stylized_3d": "3d", "anime": "anime"}
SOURCES = ("auto", "library", "stock", "ai")
AI_LICENSE = ("Made with AI (WanGP); see the model's licence",
              "https://github.com/deepbeepmeep/Wan2GP")
STOP_WORDS = {"a", "an", "the", "of", "with", "on", "in", "and", "or", "for", "to", "at",
              "by", "from", "is", "are", "ng", "sa", "ang", "mga", "na", "at", "si", "ni",
              "img", "image", "photo", "video", "clip", "broll", "b", "roll", "stock", "final",
              "copy", "edit", "mp4", "mov", "jpg", "png"}
MATCH_THRESHOLD = 0.5          # at least half the search words must be in the file's names
MAX_LIBRARY_FILES = 5000


def tokens(text):
    """Lower-case words of a name or search, without filler words; "coffees" -> "coffee"."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))          # camelCase -> camel Case
    words = re.findall(r"[^\W_]+", text.lower())
    out = []
    for w in words:
        if w in STOP_WORDS or w.isdigit():
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


@dataclass
class LibraryFile:
    path: Path
    kind: str                     # "image" or "video"
    words: frozenset
    style: str | None             # a look named in the file or folder name, else None


def file_kind(path):
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def index_library(folder):
    """Every picture and video under `folder` (sub-folders too), with its name words."""
    if not folder:
        return []
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = []
    for path in sorted(folder.rglob("*")):
        kind = file_kind(path)
        if not kind or not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(folder)
        raw = set(re.findall(r"[^\W_]+", str(rel.with_suffix("")).lower()))
        joined = str(rel.with_suffix("")).lower().replace(" ", "_").replace("-", "_")
        style = next((s for s, tags in STYLE_TAGS.items()
                      if raw & tags or any(t in joined for t in tags if "_" in t)), None)
        files.append(LibraryFile(path, kind, frozenset(tokens(rel.with_suffix(""))), style))
        if len(files) >= MAX_LIBRARY_FILES:
            break
    return files


def match_library(files, search, kind="image", style="realistic", exclude=()):
    """The library file that best fits the search words (None if none fits well enough).

    Score = the share of search words found in the file's names; ties go to the wanted kind
    (picture or clip) and the wanted look. A file marked with another look is not used.
    """
    wanted = set(tokens(search))
    if not wanted:
        return None
    exclude = {str(Path(e)) for e in exclude}
    best, best_score = None, 0.0
    for f in files:
        if str(f.path) in exclude:
            continue
        if f.style and f.style != style:
            continue
        if style != "realistic" and f.style != style:
            continue                                    # a cartoon needs a cartoon file
        coverage = len(wanted & f.words) / len(wanted)
        if coverage < MATCH_THRESHOLD:
            continue
        score = coverage + (0.1 if f.kind == kind else 0) + (0.05 if f.style == style else 0)
        if score > best_score:
            best, best_score = f, score
    return best


def library_topics(files, limit=120):
    """The most common name words in the library (told to the AI so its search words match)."""
    counts = Counter(w for f in files for w in f.words if len(w) > 2)
    return [w for w, _ in counts.most_common(limit)]


def library_folder(cfg):
    folder = (cfg.get("broll") or {}).get("library_folder") or ""
    return project_path(folder) if folder else None


def sources_text(cfg, generation_ok, library=None):
    """What the AI is told about where B-roll can come from."""
    library = index_library(library_folder(cfg)) if library is None else library
    keys = stock.available() if (cfg.get("broll") or {}).get("use_stock", True) else []
    lines = ["B-ROLL SOURCES (for ai_clips, tried in this order):"]
    if library:
        lines.append(f"- the creator's own library: {len(library)} files; their names use "
                     "these words (use them in `search` when they fit): "
                     + ", ".join(library_topics(library)))
    else:
        lines.append("- the creator's own library: none")
    lines.append("- free stock: " + (", ".join(k.title() for k in keys) + " (realistic photos "
                                     "and footage" + ("; Pixabay also has cartoons and "
                                                      "drawings" if "pixabay" in keys else "")
                                     + ")" if keys else "none"))
    gen = [label for k, label in (("image", "pictures"), ("video", "video clips"))
           if generation_ok.get(k)]
    lines.append("- AI generation: " + (" and ".join(gen) if gen else "NOT available"))
    if not (library or keys or gen):
        lines.append("No source is available: leave ai_clips empty.")
    else:
        lines.append("Only plan B-roll the creator asked for (\"lagyan ng b-roll\", \"visuals\") "
                     "or that clearly helps. `search` is 2 to 4 English keywords. A source "
                     "other than auto only when the creator asks for it.")
    return "\n".join(lines)


def ai_prompt(prompt, style):
    """The generation prompt with the look's words added."""
    words = STYLE_PROMPTS.get(style or "realistic", "")
    return f"{prompt.rstrip(' .')}, {words}" if words else prompt


def _meta(item, source, **extra):
    meta = {"source": source, "kind": item["kind"], "prompt": item.get("prompt", "")[:500],
            "search": (item.get("search") or "")[:120],
            "style": item.get("style") or "realistic", "position": item.get("position", "full"),
            "ai_generated": source == "ai"}
    meta.update({k: v for k, v in extra.items() if v not in (None, "")})
    return meta


def from_library(item, files, exclude=()):
    found = match_library(files, item.get("search") or item.get("prompt", ""), item["kind"],
                          item.get("style") or "realistic", exclude)
    if not found:
        return None
    return found.path, _meta(item, "library")


def from_stock(item, download_folder, exclude=(), notes=None):
    """Search the stock sites with a key; download the first good match (None if none)."""
    style = item.get("style") or "realistic"
    query = " ".join(filter(None, [item.get("search") or item.get("prompt", "")[:60],
                                   STOCK_WORDS.get(style)]))
    try:
        results = stock.search(query, item["kind"], style, exclude)
        if not results and item["kind"] == "video":
            results = stock.search(query, "image", style, exclude)     # a picture will do
        for r in results:
            if r.kind == "video" and r.duration and r.duration < 1.0:
                continue
            path = stock.download(r, download_folder)
            name, url = stock.LICENSES[r.provider]
            return path, _meta(item, r.provider, kind=r.kind, stock_id=f"{r.provider}-{r.id}",
                               author=r.author, page=r.page, license=name, license_url=url,
                               credit=r.credit)
    except EditorError as exc:
        if notes is not None:
            notes.append(f"Stock search for \"{query}\" did not work: {exc}")
    return None


def describe_source(meta, path):
    if meta["source"] == "library":
        return f"from your B-roll library ({Path(path).name})"
    if meta["source"] in ("pexels", "pixabay"):
        return f"free stock: {meta.get('credit')}"
    if meta["source"] == "ai":
        return "made with AI" + (f" ({meta['tier']} tier)" if meta.get("tier") else "")
    return Path(path).name


def broll_label(meta):
    """Short clip name on the timeline, e.g. "AI: coffee cup" or "Pexels: jeepney street"."""
    what = (meta.get("search") or meta.get("prompt") or "B-roll").strip()[:60]
    source = {"library": "Library", "pexels": "Pexels", "pixabay": "Pixabay", "ai": "AI",
              "file": "B-roll"}.get(meta.get("source"), "B-roll")
    return f"{source}: {what}"


def mmss(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def resolve_plan(plan, cfg, passes, gen_paths=None, max_minutes=None, max_clips=None,
                 reporter=None, cancel=None, download_folder=None, log=print, seed_salt="",
                 exclude=()):
    """Find or make every B-roll item and voice-over of the plan.

    Returns the same dict as ai_gen.generate_for_plan ({"draft", "final", "notes", "done"}),
    plus "meta": {"ai_clips": [clip["broll"] dict or None, ...]} and "sourced" (lines for the
    summary). Library and stock items are the same in the draft and the final pass.
    """
    clips = plan.get("ai_clips") or []
    settings = cfg.get("broll") or {}
    library = index_library(library_folder(cfg))
    use_stock = settings.get("use_stock", True)
    download_folder = Path(download_folder or project_path(cfg["output"]["folder"]) / "broll")
    found = [None] * len(clips)
    notes, sourced, used = [], [], set(str(e) for e in exclude)
    if clips and reporter:
        reporter.stage("broll", "Finding B-roll")
    for i, item in enumerate(clips):
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled.")
        source = item.get("source") or "auto"
        hit = None
        if source in ("auto", "library"):
            hit = from_library(item, library, used)
        if hit is None and source in ("auto", "stock") and use_stock:
            hit = from_stock(item, download_folder, used, notes)
        if hit:
            found[i] = hit
            used.add(str(hit[0]))
            if hit[1].get("stock_id"):
                used.add(hit[1]["stock_id"])
            what = item.get("search") or item["prompt"]
            sourced.append(f"B-roll at {mmss(item['at'])} ({what}): "
                           + describe_source(hit[1], hit[0]))
            if reporter:
                reporter.event("broll", index=i, source=hit[1]["source"], file=str(hit[0]))
        elif source in ("library", "stock"):
            where = "your B-roll library" if source == "library" else "free stock"
            notes.append(f"Not done: B-roll at {mmss(item['at'])} - nothing in {where} matched "
                         f"\"{item.get('search') or item['prompt']}\".")

    # What is left goes to AI generation, with the look's words in the prompt.
    to_make = [i for i, item in enumerate(clips)
               if found[i] is None and (item.get("source") or "auto") in ("auto", "ai")]
    sub = {"ai_clips": [dict(clips[i], prompt=ai_prompt(clips[i]["prompt"], clips[i].get("style")))
                        for i in to_make],
           "voiceovers": list(plan.get("voiceovers") or [])}
    generated = generate_for_plan(sub, passes, gen_paths, max_minutes, max_clips, reporter,
                                  cancel, log=log, seed_salt=seed_salt)
    outcome = {p: {"ai_clips": [None] * len(clips), "voiceovers": generated[p]["voiceovers"]}
               for p in ("draft", "final")}
    outcome.update({"notes": notes + generated["notes"], "done": [], "sourced": sourced,
                    "meta": {"ai_clips": [None] * len(clips)}})
    for i, hit in enumerate(found):
        if hit:
            for p in ("draft", "final"):
                outcome[p]["ai_clips"][i] = str(hit[0])
            outcome["meta"]["ai_clips"][i] = hit[1]
    for k, i in enumerate(to_make):
        for p in ("draft", "final"):
            outcome[p]["ai_clips"][i] = generated[p]["ai_clips"][k]
        if any(outcome[p]["ai_clips"][i] for p in ("draft", "final")):
            outcome["meta"]["ai_clips"][i] = _meta(
                clips[i], "ai", tier=generated["tiers"].get(f"ai_clips.{k}"),
                license=AI_LICENSE[0], license_url=AI_LICENSE[1])
    for event in generated["done"]:
        if event.get("list") == "ai_clips":
            event = {**event, "index": to_make[event["index"]]}
        outcome["done"].append(event)
    return outcome


def credits(project):
    """Plain-text credits for the stock items in a project, and whether any item is AI-made."""
    lines, ai = [], False
    for track in project["tracks"]:
        for clip in track["clips"]:
            meta = clip.get("broll")
            if not meta:
                continue
            ai = ai or bool(meta.get("ai_generated"))
            if meta.get("credit") and meta["credit"] not in lines:
                lines.append(meta["credit"])
    return lines, ai


def now_salt():
    return f"#{int(time.time() * 1000)}"


def find_one(item, cfg, quality="final", gen_paths=None, reporter=None, cancel=None,
             download_folder=None, exclude=(), new_version=False, log=print):
    """Find or make ONE B-roll item (the editor's "find another" / "regenerate").

    `item`: kind, prompt, search, style, source, duration (and position). `exclude`: files and
    stock ids not to use again. `new_version`: a different AI seed for the same prompt.
    Returns (file or None, broll meta or None, notes).
    """
    item = {"kind": "image", "prompt": "", "search": "", "style": "realistic",
            "source": "auto", "at": 0.0, "duration": 3.0, "position": "full", **item}
    if not (item["prompt"].strip() or item["search"].strip()):
        raise EditorError("Describe what to show (or give search words).")
    if item["style"] not in STYLES:
        raise EditorError(f"Unknown look '{item['style']}'. Choose: {', '.join(STYLES)}")
    if item["source"] not in SOURCES:
        raise EditorError(f"Unknown source '{item['source']}'. Choose: {', '.join(SOURCES)}")
    item["prompt"] = item["prompt"].strip() or item["search"]
    outcome = resolve_plan({"ai_clips": [item], "voiceovers": []}, cfg, [quality], gen_paths,
                           reporter=reporter, cancel=cancel, download_folder=download_folder,
                           log=log, seed_salt=now_salt() if new_version else "",
                           exclude=exclude)
    path = outcome[quality]["ai_clips"][0]
    meta = outcome["meta"]["ai_clips"][0]
    if meta and quality == "draft" and meta["source"] == "ai":
        meta["tier"] = meta.get("tier") or "Draft"
    return (Path(path) if path else None), meta, outcome["notes"]


def _all_ids(project):
    ids = {m["id"] for m in project["media"]} | {t["id"] for t in project["tracks"]}
    return ids | {c["id"] for t in project["tracks"] for c in t["clips"]}


def _new_id(project, prefix):
    taken, n = _all_ids(project), 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def _fit(clip, media):
    """Make an overlay clip show `media` (keeps its place, size and timing where it can)."""
    clip["media"] = media["id"]
    clip["type"] = "image" if media["kind"] == "image" else "video"
    if clip["type"] == "video":
        speed = clip.get("speed", 1.0)
        length = media["duration"] / speed if media["duration"] else clip["duration"]
        clip["duration"] = round(min(clip["duration"], length), 6)
        clip["in"] = 0.0
        clip["out"] = round(clip["duration"] * speed, 6)
    else:
        clip.pop("in", None)
        clip.pop("out", None)
        clip.pop("speed", None)


def find_overlay_clip(project, clip_id):
    for track in project["tracks"]:
        for clip in track["clips"]:
            if clip["id"] == clip_id:
                if track["kind"] != "overlay":
                    raise EditorError(f"Clip {clip_id} is not a picture/B-roll clip.")
                return track, clip
    raise EditorError(f"No clip with id {clip_id} in this project.")


def replace_clip_media(project, clip_id, media, meta):
    """Put another file on an existing B-roll clip. Returns the clip."""
    _track, clip = find_overlay_clip(project, clip_id)
    if not any(m["id"] == media["id"] for m in project["media"]):
        project["media"].append(media)
    _fit(clip, media)
    clip["broll"] = dict(meta, position=(clip.get("broll") or {}).get("position")
                         or meta.get("position", "full"))
    clip["label"] = broll_label(meta)
    return clip


def add_clip(project, media, meta, at, duration, position="full"):
    """A new B-roll clip at `at` (timeline seconds), on a free overlay lane. Returns it."""
    from .overlays import POSITIONS
    from .project import clip_end
    if not any(m["id"] == media["id"] for m in project["media"]):
        project["media"].append(media)
    max_w, max_h, cx, cy = POSITIONS.get(position, POSITIONS["full"])
    clip = {"id": _new_id(project, "b"), "type": "image", "media": media["id"],
            "start": round(max(0.0, at), 6), "duration": round(duration, 6), "x": cx, "y": cy,
            "width": max_w, "height": max_h, "animation": "none" if position == "full" else "pop"}
    _fit(clip, media)
    clip["broll"] = dict(meta, position=position)
    clip["label"] = broll_label(meta)
    end = clip["start"] + clip["duration"]
    overlays = [t for t in project["tracks"] if t["kind"] == "overlay" and t["id"] != "logo"]
    for track in overlays:
        if all(clip_end(c) <= clip["start"] + 1e-6 or c["start"] >= end - 1e-6
               for c in track["clips"]):
            track["clips"].append(clip)
            track["clips"].sort(key=lambda c: c["start"])
            return clip
    track = {"id": _new_id(project, "broll"), "kind": "overlay",
             "name": f"B-roll {len(overlays) + 1}", "clips": [clip]}
    last = max((i for i, t in enumerate(project["tracks"]) if t["kind"] == "overlay"),
               default=0)
    project["tracks"].insert(last + 1, track)
    return clip
