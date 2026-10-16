"""Measure how wide caption text will be, so boxes can be drawn behind single words.

libass sizes fonts so that (ascent + descent) equals the ASS font size, and we copy
that rule here using Pillow. Used only by styles with an `active_box`.
"""

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

SYSTEM_FONT_DIRS = [
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path(os.environ.get("LOCALAPPDATA", "~")) / "Microsoft/Windows/Fonts",
    Path("/usr/share/fonts"),
    Path("~/.fonts").expanduser(),
    Path("/Library/Fonts"),
]


@lru_cache(maxsize=None)
def _font_table(folders):
    """[(family, style, path)] for every font file found in the folders."""
    table = []
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                family, style = ImageFont.truetype(str(path), 10).getname()
            except OSError:
                continue
            table.append((family or "", style or "", str(path)))
    return table


def find_font_file(family, bold, fonts_folder):
    """Find the font file libass would most likely use for this family name."""
    wanted = family.strip().lower()
    folders = (str(fonts_folder),) + tuple(str(d) for d in SYSTEM_FONT_DIRS)
    exact, same_family = [], []
    for fam, style, path in _font_table(folders):
        if f"{fam} {style}".lower() == wanted:
            exact.append(path)
        elif fam.lower() == wanted:
            same_family.append((style.lower(), path))
    if exact:
        return exact[0]
    if not same_family:
        return None
    preferred = ["bold"] if bold else ["regular", "normal", "book"]
    for name in preferred:
        for style, path in same_family:
            if style == name:
                return path
    return same_family[0][1]


class TextMeasurer:
    def __init__(self, font_path, size):
        probe = ImageFont.truetype(font_path, 1000)
        ascent, descent = probe.getmetrics()
        self.scale = size / (ascent + descent)
        self.font = probe

    def width(self, text):
        return self.font.getlength(text) * self.scale
