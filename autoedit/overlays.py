"""Pop-in overlays (B-roll): show an image/clip when a keyword is spoken.

triggers.yaml example:

    defaults:
      duration: 2.5      # seconds on screen
      position: top      # top or center
      cooldown: 10       # seconds before the same trigger can fire again
    triggers:
      - keyword: github                # one word ...
        file: github.png               # ... file inside assets/overlays/
      - keyword: [gcash, g-cash]       # several spellings
        file: gcash_notification.png
        duration: 3
      - keyword: "visual studio code"  # or a phrase
        file: vscode.mp4
        position: center
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import EditorError
from .words import normalize

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
CLIP_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".gif", ".m4v"}

# Overlay boxes (max width, max height, centre x, centre y) on the 1080x1920 frame.
# Centre x is 500 (not 540) to stay clear of the like/comment buttons on the right.
POSITIONS = {
    "top": (820, 560, 500, 520),
    "center": (820, 560, 500, 900),
}
GAP_BETWEEN_OVERLAYS = 0.3


@dataclass
class OverlayEvent:
    file: Path
    start: float        # seconds on the cut timeline
    duration: float
    position: str       # "top" or "center"

    @property
    def is_image(self):
        return self.file.suffix.lower() in IMAGE_EXTENSIONS


def load_triggers(path, overlay_folder):
    """Read triggers.yaml. Returns a list of dicts: phrases (list of word lists), file, duration..."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EditorError(f"{path.name} has a typo and could not be read:\n{exc}")
    defaults = {"duration": 2.5, "position": "top", "cooldown": 10}
    defaults.update(data.get("defaults") or {})
    triggers = []
    for item in data.get("triggers") or []:
        if not isinstance(item, dict) or "keyword" not in item or "file" not in item:
            raise EditorError(f"{path.name}: every trigger needs 'keyword' and 'file'. Got: {item}")
        keywords = item["keyword"] if isinstance(item["keyword"], list) else [item["keyword"]]
        file = Path(overlay_folder) / item["file"]
        if not file.exists():
            print(f"  ! Overlay file not found, skipping trigger: {file}")
            continue
        triggers.append({
            "phrases": [[normalize(p) for p in str(k).split()] for k in keywords],
            "file": file,
            "duration": float(item.get("duration", defaults["duration"])),
            "position": str(item.get("position", defaults["position"])),
            "cooldown": float(item.get("cooldown", defaults["cooldown"])),
        })
    return triggers


def find_trigger_events(words, triggers):
    """Find spoken keywords in the (already cut) word list. Returns OverlayEvents."""
    keys = [normalize(w.text) for w in words]
    events, last_fired = [], {}
    for i in range(len(words)):
        for t_index, trig in enumerate(triggers):
            for phrase in trig["phrases"]:
                if phrase and keys[i:i + len(phrase)] == phrase:
                    start = words[i].start
                    if start - last_fired.get(t_index, -1e9) < trig["cooldown"]:
                        continue
                    last_fired[t_index] = start
                    events.append(OverlayEvent(trig["file"], start, trig["duration"],
                                               trig["position"]))
                    break
    return events


def schedule(events, video_length, caption_zone, top_blocked=False):
    """Keep only one overlay on screen at a time and keep them away from the captions.

    `top_blocked`: the top area is taken (picture-in-picture face), use the centre.
    """
    chosen, busy_until = [], -1.0
    for ev in sorted(events, key=lambda e: e.start):
        if ev.start < busy_until + GAP_BETWEEN_OVERLAYS or ev.start >= video_length - 0.3:
            continue
        ev.duration = min(ev.duration, video_length - ev.start)
        ev.position = "center" if top_blocked else safe_position(ev.position, caption_zone)
        chosen.append(ev)
        busy_until = ev.start + ev.duration
    return chosen


def safe_position(position, caption_zone):
    """Move an overlay if it would sit on top of the captions."""
    position = position if position in POSITIONS else "top"
    if caption_zone in ("center", "divider"):
        return "top"
    if caption_zone == "top":
        return "center"
    return position
