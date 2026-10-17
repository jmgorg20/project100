"""The AI edit plan: what the language model decides for one video, checked and applied.

The model never writes the Project itself. It fills in a small plan (ai_plan.schema.json):
caption style and size, pacing, extra cuts, zooms, grades and pop-in photos, with times in
the RAW video. `apply_plan()` turns it into the same settings and --plan entries the command
line uses, so the timeline is built by the normal, tested editing steps.
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

from .cuts import merge_intervals
from .styles import get_style

SCHEMA_FILE = Path(__file__).with_name("ai_plan.schema.json")
MIN_KEPT_SECONDS = 1.0
# Colour names the AI may use for tracked effects (None = the effect's own colour).
TRACK_COLORS = {"default": None, "gold": "#ffd24a", "white": "#ffffff", "blue": "#4aa3ff",
                "cyan": "#58e0ff", "purple": "#b06cff", "pink": "#ff6ec7", "red": "#ff4a4a",
                "orange": "#ff9b3d", "green": "#5cff8a"}


@lru_cache(maxsize=None)
def load_plan_schema():
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def preset_plan(cfg):
    """The plan that matches the normal preset edit (what you get without AI)."""
    pacing = cfg["pacing"]
    return {
        "summary": "Preset edit: pauses and filler words cut, jump-cut zooms, captions.",
        "style": get_style(cfg["style"]).name,
        "grade": str(cfg["grade"]),
        "pacing": {"silence_threshold": float(pacing["silence_threshold"]),
                   "remove_fillers": bool(pacing["remove_fillers"])},
        "zoom": {"enabled": bool(pacing.get("zoom", True)),
                 "amount": float(pacing["zoom_amount"])},
        "captions": {"enabled": bool(cfg["captions"].get("enabled", True)), "size_scale": 1.0,
                     "position": None, "highlight_words": []},
        "cuts": [], "zooms": [], "grades": [], "effects": [], "tracked_effects": [], "photos": [],
        "notes": [],
        "ai_clips": [], "voiceovers": [],
    }


def upgrade_plan(plan):
    """Fill in what older plans (saved before B-roll sources) do not have. Returns a copy."""
    if not isinstance(plan, dict):
        return plan
    plan = copy.deepcopy(plan)
    plan.setdefault("effects", [])
    plan.setdefault("tracked_effects", [])
    for clip in plan.get("ai_clips") or []:
        if isinstance(clip, dict):
            clip.setdefault("search", " ".join(str(clip.get("prompt", "")).split()[:4])[:80])
            clip.setdefault("style", "realistic")
            clip.setdefault("source", "auto")
    return plan


def validate_plan(plan, duration, photo_names=()):
    """Return a list of problems (empty = the plan can be used)."""
    import jsonschema

    if not isinstance(plan, dict):
        return ["the answer is not a JSON object"]
    validator = jsonschema.Draft202012Validator(load_plan_schema())
    problems = [f"{e.json_path.replace('$', 'plan', 1)}: {e.message}"
                for e in sorted(validator.iter_errors(plan), key=lambda e: list(e.absolute_path))]
    if problems:
        return problems

    def check_range(kind, i, item):
        where = f"plan.{kind}[{i}]"
        if item["end"] <= item["start"]:
            problems.append(f"{where}: end ({item['end']}) must be after start ({item['start']})")
        if item["start"] >= duration:
            problems.append(f"{where}: starts at {item['start']}s but the video is only "
                            f"{duration:.2f}s long")

    for kind in ("cuts", "zooms", "grades"):
        for i, item in enumerate(plan[kind]):
            check_range(kind, i, item)
    kept = duration - sum(e - s for s, e in merge_intervals(
        [(c["start"], min(c["end"], duration)) for c in plan["cuts"]]))
    if kept < MIN_KEPT_SECONDS:
        problems.append(f"plan.cuts: they remove almost the whole video (only {kept:.1f}s left)")
    for kind in ("ai_clips", "voiceovers", "effects", "tracked_effects"):
        for i, item in enumerate(plan[kind]):
            if item["at"] >= duration:
                problems.append(f"plan.{kind}[{i}]: at {item['at']}s is after the end of the "
                                f"video ({duration:.2f}s)")
    names = set(photo_names)
    for i, photo in enumerate(plan["photos"]):
        if photo["file"] not in names:
            choices = ", ".join(sorted(names)) or "none were given"
            problems.append(f"plan.photos[{i}]: unknown photo '{photo['file']}' "
                            f"(available: {choices})")
        if photo["at"] >= duration:
            problems.append(f"plan.photos[{i}]: at {photo['at']}s is after the end of the "
                            f"video ({duration:.2f}s)")
    return problems


def apply_plan(cfg, plan, photos, generated=None):
    """Settings and pipeline plan for a checked plan. `photos` maps file name -> path.

    `generated` holds the files found or made for the plan's B-roll and voice-overs:
    {"ai_clips": [path or None, ...], "voiceovers": [path or None, ...]} (None = not made),
    and optionally "meta": {"ai_clips": [where each came from, ...]} (see broll.py).
    Returns (cfg, pipeline_plan); `cfg` is a copy, the caller's settings are not changed.
    """
    generated = generated or {}
    cfg = copy.deepcopy(cfg)
    cfg["style"] = plan["style"]
    cfg["grade"] = plan["grade"]
    cfg["pacing"].update(silence_threshold=float(plan["pacing"]["silence_threshold"]),
                         remove_fillers=bool(plan["pacing"]["remove_fillers"]),
                         zoom=bool(plan["zoom"]["enabled"]),
                         zoom_amount=float(plan["zoom"]["amount"]))
    captions = plan["captions"]
    cfg["captions"]["enabled"] = bool(captions["enabled"])
    extra = list(cfg["highlight"].get("extra_keywords") or [])
    cfg["highlight"]["extra_keywords"] = extra + [w for w in captions["highlight_words"]
                                                  if w.strip()]
    overrides = {}
    scale = float(captions["size_scale"])
    if abs(scale - 1.0) > 1e-6:
        overrides["size"] = max(16, min(300, round(get_style(plan["style"]).size * scale)))
    if captions["position"]:
        overrides["zone"] = captions["position"]
    pipeline_plan = {
        "auto_zoom": True,
        "cuts": [{"start": c["start"], "end": c["end"]} for c in plan["cuts"]],
        "zooms": [{"start": z["start"], "end": z["end"], "amount": float(z["amount"])}
                  for z in plan["zooms"]],
        "grades": [{"start": g["start"], "end": g["end"], "grade": g["grade"]}
                   for g in plan["grades"]],
        "tracked": [{"effect": e["effect"], "point": e["point"], "hand": e["hand"],
                     "at": float(e["at"]), "duration": float(e["duration"]),
                     "intensity": float(e["intensity"]), "size": float(e["size"]),
                     "color": TRACK_COLORS[e["color"]]} for e in plan.get("tracked_effects", [])],
        "track": generated.get("track"),
        "effects": [{"effect": e["effect"], "at": float(e["at"]), "duration": float(e["duration"]),
                     "intensity": float(e["intensity"]), "on_cut": bool(e["on_cut"])}
                    for e in plan.get("effects", [])],
        "overlays": [{"file": Path(photos[p["file"]]), "at": float(p["at"]),
                      "duration": float(p["duration"]), "position": p["position"]}
                     for p in plan["photos"]],
        "caption_overrides": overrides,
        "voiceovers": [],
    }
    metas = (generated.get("meta") or {}).get("ai_clips") or []
    for i, (clip, path) in enumerate(zip(plan.get("ai_clips", []), generated.get("ai_clips", []))):
        if path:
            meta = metas[i] if i < len(metas) and metas[i] else \
                {"source": "ai", "ai_generated": True}
            pipeline_plan["overlays"].append({"file": Path(path), "at": float(clip["at"]),
                                              "duration": float(clip["duration"]),
                                              "position": clip["position"], "broll": meta})
    for line, path in zip(plan.get("voiceovers", []), generated.get("voiceovers", [])):
        if path:
            pipeline_plan["voiceovers"].append({"file": Path(path), "at": float(line["at"])})
    return cfg, pipeline_plan
