"""Engine facts the desktop app's preview needs (caption styles, safe areas, positions).

`python editor.py ui-data` prints them; the app keeps a copy in
desktop/src/shared/engine-data.json, and a test checks the copy is up to date.
"""

import dataclasses

from . import captions, formats, overlays, render
from .grades import GRADES
from .styles import STYLES


def ui_data():
    return {
        "canvas": {"width": render.W, "height": render.H},
        "safe": {"left": captions.SAFE_LEFT, "right": captions.SAFE_RIGHT,
                 "bottom_reserved": 0.2},
        "zones": {name: {"align": a, "x": x, "y": y} for name, (a, x, y) in captions.ZONES.items()},
        "left_x": captions.LEFT_X,
        "caption_timing": {"hold": captions.HOLD_AFTER_LAST_WORD,
                           "merge_gap": captions.MERGE_GAP},
        "overlay_positions": {name: {"width": w, "height": h, "x": x, "y": y}
                              for name, (w, h, x, y) in overlays.POSITIONS.items()},
        "styles": [dataclasses.asdict(s) for s in STYLES],
        "grades": list(GRADES),
        "fps": [24, 25, 30, 50, 60],
        "formats": formats.summary(),
    }
