"""Colour grade presets, as FFmpeg filter chains. Add your own by adding a line to GRADES."""

from .errors import EditorError

GRADES = {
    # Slight contrast + saturation lift that keeps skin natural.
    "natural_clean": "eq=contrast=1.06:brightness=0.01:saturation=1.12",
    "none": "",
    "warm": "colorbalance=rs=0.05:gs=0.01:bs=-0.05:rm=0.04:bm=-0.04,eq=saturation=1.08",
    "black_and_white": "hue=s=0,eq=contrast=1.15",
    # Teal shadows, orange highlights.
    "orange_teal": "colorbalance=rs=-0.08:bs=0.10:rh=0.08:bh=-0.08,eq=contrast=1.05:saturation=1.15",
    "high_contrast": "eq=contrast=1.25:saturation=1.15:brightness=-0.01",
}


def grade_filter(name):
    key = str(name or "none").strip().lower()
    if key not in GRADES:
        raise EditorError(f"Unknown grade '{name}'. Choose one of: {', '.join(GRADES)}")
    return GRADES[key]
