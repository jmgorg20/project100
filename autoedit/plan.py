"""Optional per-video edit plan (--plan plan.json). All times are in seconds of the RAW video.

{
  "style": "center_keyword",
  "grade": "warm",
  "auto_zoom": true,
  "cuts":     [{"start": 41.0, "end": 47.5}],
  "zooms":    [{"start": 12.0, "end": 15.5, "amount": 1.3}],
  "grades":   [{"start": 30.0, "end": 36.0, "grade": "black_and_white"}],
  "overlays": [{"file": "receipt.png", "at": 20.0, "duration": 3, "position": "center"}]
}
"""

import json
from pathlib import Path

from .errors import EditorError
from .grades import grade_filter

ALLOWED_KEYS = {"style", "grade", "auto_zoom", "cuts", "zooms", "grades", "overlays", "preset"}


def _ranges(items, name, extra=()):
    result = []
    for item in items or []:
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            raise EditorError(f"Plan '{name}' entries need numeric 'start' and 'end': {item}")
        if end <= start:
            raise EditorError(f"Plan '{name}' entry ends before it starts: {item}")
        entry = {"start": start, "end": end}
        for key in extra:
            entry[key] = item.get(key)
        result.append(entry)
    return result


def load_plan(path, overlay_folder):
    path = Path(path)
    if not path.exists():
        raise EditorError(f"Plan file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EditorError(f"Plan '{path.name}' is not valid JSON: {exc}")
    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        raise EditorError(f"Plan has unknown settings: {', '.join(sorted(unknown))}. "
                          f"Allowed: {', '.join(sorted(ALLOWED_KEYS))}")
    plan = {
        "style": data.get("style"),
        "grade": data.get("grade"),
        "preset": data.get("preset"),
        "auto_zoom": data.get("auto_zoom", True),
        "cuts": _ranges(data.get("cuts"), "cuts"),
        "zooms": _ranges(data.get("zooms"), "zooms", extra=("amount",)),
        "grades": _ranges(data.get("grades"), "grades", extra=("grade",)),
        "overlays": [],
    }
    for z in plan["zooms"]:
        z["amount"] = float(z["amount"] or 1.3)
        if not 1.0 <= z["amount"] <= 3.0:
            raise EditorError(f"Plan zoom amount must be between 1.0 and 3.0: {z}")
    for g in plan["grades"]:
        grade_filter(g["grade"])  # validates the name
    for item in data.get("overlays") or []:
        if "file" not in item or "at" not in item:
            raise EditorError(f"Plan overlays need 'file' and 'at': {item}")
        file = Path(item["file"])
        if not file.is_absolute():
            file = Path(overlay_folder) / file
        if not file.exists():
            raise EditorError(f"Plan overlay file not found: {file}")
        plan["overlays"].append({
            "file": file, "at": float(item["at"]),
            "duration": float(item.get("duration", 2.5)),
            "position": item.get("position", "top"),
        })
    return plan
