"""Presets: a ready-made look for the whole edit (Viral TikTok, Cinematic Storytelling, ...).

A preset is one plain JSON file, checked against presets/preset.schema.json:

    format     a video format id, "auto" (the AI picks) or null (from your words)
    graphics   a Director style (or "off") and `density` (graphics per 10 s)
    captions   style, size, zone
    grade, pacing (a pacing preset from config.yaml), zoom
    sfx        a whoosh / pop on emphasised graphics (made on this PC by FFmpeg)
    music      a mood and volume: a file from your music folder whose name matches the mood
    broll      stock search on/off, AI clips on/off ("approved assets only")
    instruction  added to your instruction for the AI

The built-in presets are in autoedit/presets/. Your own go in the folder `presets_folder` names
(config.yaml); a file with the same id replaces a built-in one.
"""

import copy
import json
from pathlib import Path

from .errors import EditorError

PRESETS_DIR = Path(__file__).parent / "presets"
SCHEMA_FILE = PRESETS_DIR / "preset.schema.json"
AUDIO_TYPES = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus")
MOOD_WORDS = {
    "upbeat": ("upbeat", "happy", "energy", "energetic", "fun", "pop", "dance", "summer", "masaya"),
    "cinematic": ("cinematic", "epic", "drama", "dramatic", "trailer", "story", "emotional"),
    "calm": ("calm", "chill", "lofi", "lo-fi", "piano", "soft", "ambient", "relax", "acoustic"),
}
EMPHASIS_POP = ("pop-heavy", "stamp", "emoji-pop", "emoji-burst", "sticker", "bounce", "rank-number",
                "list-item")
SFX_MIN_GAP = 1.5
SFX_PER_10S = 3


class PresetError(EditorError):
    pass


def load_schema():
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def preset_problems(preset, cfg=None):
    import jsonschema
    from .director_styles import STYLES as GRAPHIC_STYLES
    from .grades import GRADES
    from .styles import STYLES
    v = jsonschema.Draft202012Validator(load_schema())
    problems = [f"{e.json_path}: {e.message}" for e in v.iter_errors(preset)]
    if problems:
        return problems
    if preset["graphics"] not in GRAPHIC_STYLES and preset["graphics"] != "off":
        problems.append(f"graphics: unknown style '{preset['graphics']}'")
    if preset["captions"]["style"] not in {s.name for s in STYLES}:
        problems.append(f"captions.style: unknown caption style '{preset['captions']['style']}'")
    if preset["grade"] not in GRADES:
        problems.append(f"grade: unknown grade '{preset['grade']}'")
    fmt_id = preset["format"]
    if fmt_id not in (None, "auto"):
        from . import formats
        if fmt_id not in formats.all_formats():
            problems.append(f"format: unknown format '{fmt_id}'")
    pacing = (cfg or {}).get("presets") or {"fast": {}, "relaxed": {}}
    if preset["pacing"] not in pacing:
        problems.append(f"pacing: unknown pacing preset '{preset['pacing']}' (config.yaml presets:)")
    return problems


def user_folder(cfg=None):
    from .config import project_path
    folder = (cfg or {}).get("presets_folder", "presets")
    return project_path(folder) if folder else None


def all_presets(cfg=None):
    """{id: preset}: the built-in ones, then yours (same id replaces). Every file is checked."""
    out = {}
    folders = [PRESETS_DIR]
    mine = user_folder(cfg)
    if mine and Path(mine).is_dir():
        folders.append(Path(mine))
    for folder in folders:
        for path in sorted(folder.glob("*.json")):
            if path.name == SCHEMA_FILE.name:
                continue
            try:
                preset = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise PresetError(f"Could not read the preset {path}: {exc}")
            problems = preset_problems(preset, cfg) if isinstance(preset, dict) else ["not a JSON object"]
            if problems:
                raise PresetError(f"The preset file {path} has problems:\n  - " + "\n  - ".join(problems))
            if preset["id"] != path.stem:
                raise PresetError(f"The preset file {path.name} must have the id '{path.stem}'.")
            out[preset["id"]] = {**preset, "builtin": folder == PRESETS_DIR}
    return out


def get(name, cfg=None):
    presets = all_presets(cfg)
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    if key not in presets:
        raise PresetError(f"Unknown preset '{name}'. Choose one of: {', '.join(presets)}")
    return presets[key]


def summary(cfg=None):
    """What the app shows."""
    keys = ("id", "name", "tl", "about", "about_tl", "format", "graphics", "builtin")
    return [{k: p.get(k) for k in keys} for p in all_presets(cfg).values()]


def cfg_for(preset, cfg):
    """A copy of the settings with the preset's pacing, captions, grade, graphics and B-roll."""
    from .config import apply_preset
    cfg = copy.deepcopy(cfg)
    cfg["preset"] = preset["pacing"]
    cfg = apply_preset(cfg)
    if "zoom" in preset:
        cfg["pacing"]["zoom"] = bool(preset["zoom"])
    cfg["style"] = preset["captions"]["style"]
    cfg["grade"] = preset["grade"]
    g = cfg.setdefault("graphics", {})
    if preset.get("density"):
        g["max_per_10s"] = int(preset["density"])
    broll = preset.get("broll") or {}
    if "use_stock" in broll:
        cfg["broll"]["use_stock"] = bool(broll["use_stock"])
    cfg["preset_name"] = preset["id"]
    return cfg


def instruction_for(preset, instruction):
    hint = preset.get("instruction") or ""
    return (instruction.rstrip() + "\n\n" + hint).strip() if hint else instruction


def pin_plan(preset, plan):
    """The preset's look wins over the AI's choice of caption style, grade and size (the AI still
    decides the cuts, zooms, photos and B-roll). Returns a copy."""
    plan = copy.deepcopy(plan)
    plan["style"] = preset["captions"]["style"]
    plan["grade"] = preset["grade"]
    caps = plan.setdefault("captions", {})
    if "size_scale" in preset["captions"]:
        caps["size_scale"] = float(preset["captions"]["size_scale"])
    if preset["captions"].get("zone"):
        caps["position"] = preset["captions"]["zone"]
    if (preset.get("broll") or {}).get("ai_clips") is False:
        plan["ai_clips"] = []
    if preset.get("graphics") == "premium_editorial":
        plan["photos"] = []           # the editorial scenes show your pictures (floating, timed to your words)
    return plan


# ---------------------------------------------------------------- music and sounds

def music_file(preset, cfg):
    """A file from your music folder for the preset's mood (its name says the mood), or None."""
    from .config import project_path
    music = preset.get("music")
    folder = project_path(((cfg or {}).get("music") or {}).get("folder") or "")
    if not music or not folder or not Path(folder).is_dir():
        return None
    files = sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in AUDIO_TYPES)
    if not files:
        return None
    words = MOOD_WORDS.get(music["mood"], (music["mood"],))
    matching = [f for f in files if any(w in f.stem.lower() for w in words)]
    return (matching or files)[0]


def add_music(project, preset, cfg):
    """Put the preset's music under the whole video (repeated if short; the renderer lowers it
    while you speak). Returns a note for the summary."""
    from .formats import Ctx, get as get_format
    from .project import timeline_duration
    if not preset.get("music"):
        return None
    path = music_file(preset, cfg)
    if path is None:
        return (f"No music added: put music you may use in {cfg['music']['folder']} "
                f"(a name with '{preset['music']['mood']}' is picked first).")
    ctx = Ctx(project, get_format("talking_head"), {}, cfg, ".")
    mid = ctx.media_id(path)
    length = ctx.media(mid)["duration"]
    total = timeline_duration(project)
    track = next((t for t in project["tracks"] if t["kind"] == "audio" and t.get("role") == "music"
                  and not t["clips"]), None)
    if track is None:
        track = ctx.track(ctx.new_id("music-"), "audio", "Music", role="music", after_kind="audio")
    at = 0.0
    while at < total - 0.05 and length > 0.5:
        d = round(min(length, total - at), 4)
        track["clips"].append({"id": ctx.new_id("mu"), "type": "audio", "media": mid, "start": round(at, 4),
                               "duration": d, "in": 0.0, "out": d,
                               "volume": float(preset["music"]["volume"])})
        at += d
    if track["clips"]:
        track["clips"][-1]["fade_out"] = round(min(1.5, track["clips"][-1]["duration"] / 2), 4)
        audio = project["settings"].setdefault("audio", {})
        if not audio.get("ducking"):
            audio["ducking"] = 0.6                     # quieter while you speak
    return f"Music: {path.name} ({preset['music']['mood']}), quieter while you speak."


def add_emphasis_sounds(project, cfg):
    """A whoosh on flash/whip graphics and a pop on popping ones, spaced out. Returns the count."""
    from .formats import Ctx, add_sfx, get as get_format
    graphics = sorted((c for t in project["tracks"] if t["kind"] == "graphics" for c in t["clips"]
                       if c.get("type") == "graphic"), key=lambda c: c["start"])
    ctx = Ctx(project, get_format("talking_head"), {}, cfg, ".")
    taken = sorted(c["start"] for t in project["tracks"] if t["kind"] == "audio" and t.get("role") == "sfx"
                   for c in t["clips"])
    added = []
    for g in graphics:
        kind = (g.get("attach") or {}).get("kind")
        sound = "whoosh" if kind in ("flash", "whip") else "pop" if g.get("template") in EMPHASIS_POP else None
        at = g["start"]
        if sound is None or any(abs(at - x) < SFX_MIN_GAP for x in taken + added):
            continue
        if sum(1 for x in added if at - 10 < x <= at) >= SFX_PER_10S:
            continue
        add_sfx(ctx, sound, at)
        added.append(at)
    return len(added)


def finish(project, preset, cfg):
    """After the edit: the preset's music and sounds. Returns notes."""
    notes = []
    note = add_music(project, preset, cfg)
    if note:
        notes.append(note)
    if preset.get("sfx"):
        n = add_emphasis_sounds(project, cfg)
        if n:
            notes.append(f"{n} whoosh/pop sound(s) on the emphasised graphics.")
    return notes
