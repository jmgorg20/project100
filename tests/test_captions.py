import re
import subprocess

import pytest

from autoedit import PROJECT_DIR
from autoedit.captions import (HEIGHT, SAFE_LEFT, SAFE_RIGHT, WIDTH, ZONES, ass_color, ass_time,
                               build_ass, build_events, chunk_words, fonts_from_config)
from autoedit.config import DEFAULTS
from autoedit.highlight import mark_keywords
from autoedit.styles import STYLES, get_style
from autoedit.words import Word, make_word

FONTS = fonts_from_config(DEFAULTS["captions"])
FONTS_DIR = PROJECT_DIR / "assets" / "fonts"


def sample_words():
    text = "Grabe ang bilis ng internet sa Parañaque 500 pesos lang *GitHub* ko"
    words, t = [], 0.0
    for token in text.split():
        words.append(make_word(token, t, t + 0.3))
        t += 0.4
    return mark_keywords(words, DEFAULTS["highlight"])


def to_seconds(stamp):
    h, m, s = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def dialogue_lines(ass):
    return [l for l in ass.splitlines() if l.startswith("Dialogue:")]


def test_there_are_14_styles_with_unique_numbers_and_names():
    assert len(STYLES) == 14
    assert [s.number for s in STYLES] == list(range(1, 15))
    assert len({s.name for s in STYLES}) == 14


def test_get_style_by_number_or_name():
    assert get_style(4).name == "bold_caps"
    assert get_style("4").name == "bold_caps"
    assert get_style("Yellow_Pop").number == 2
    with pytest.raises(Exception):
        get_style("nope")


def test_color_and_time_helpers():
    assert ass_color("#FF8000") == "&H000080FF"
    assert ass_color("#000000", 128) == "&H80000000"
    assert ass_time(6123) == "0:01:01.23"


@pytest.mark.parametrize("style", STYLES, ids=lambda s: s.name)
def test_every_style_makes_valid_ass(style):
    ass = build_ass(sample_words(), style, FONTS, fonts_folder=FONTS_DIR)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert re.search(r"^Style: Main,", ass, re.M)
    lines = dialogue_lines(ass)
    assert lines, "no caption events"
    for line in lines:
        fields = line.split(",", 9)
        assert len(fields) == 10
        assert to_seconds(fields[1]) < to_seconds(fields[2])
        text = fields[9]
        assert text.count("{") == text.count("}")
    # Filipino character survives.
    assert "Parañaque" in ass or "PARAÑAQUE" in ass or "parañaque" in ass


@pytest.mark.parametrize("style", STYLES, ids=lambda s: s.name)
def test_every_style_stays_in_safe_area(style):
    align, x, y = ZONES[style.zone]
    assert SAFE_LEFT < x < WIDTH - SAFE_RIGHT
    assert y <= HEIGHT * 0.8   # never in the bottom 20% (app UI)
    for group in chunk_words(sample_words(), style):
        assert len(group) <= style.max_lines


def test_events_do_not_overlap_and_cover_each_word():
    style = get_style("yellow_pop")
    events = [e for e in build_events(sample_words(), style) if e[3] == "Main"]
    for a, b in zip(events, events[1:]):
        assert a[2] <= b[1]
    assert len(events) == len(sample_words())


def test_active_word_colour_and_uppercase():
    ass = build_ass(sample_words(), get_style("bold_caps"), FONTS)
    assert "&H002E2EFF" in ass           # red active word
    assert "GRABE" in ass and "Grabe" not in ass


def test_minimal_is_lowercase():
    ass = build_ass(sample_words(), get_style("minimal"), FONTS)
    assert "grabe" in ass and "Grabe" not in ass


def test_one_word_shows_single_word_per_event():
    for line in dialogue_lines(build_ass(sample_words(), get_style("one_word"), FONTS)):
        text = re.sub(r"\{[^}]*\}", "", line.split(",", 9)[9])
        assert len(text.split()) == 1


def test_typewriter_hides_words_not_yet_spoken():
    lines = dialogue_lines(build_ass(sample_words(), get_style("typewriter"), FONTS))
    assert r"\alpha&HFF&" in lines[0]                # later words hidden at first
    group_last = [l for l in lines if r"\alpha&HFF&" not in l]
    assert group_last                                 # ...and all visible at the end


def test_pop_word_animates_scale():
    ass = build_ass(sample_words(), get_style("pop_word"), FONTS)
    assert r"\t(0,90,\fscx112\fscy112)" in ass


def test_center_keyword_highlights_and_capitalises_keywords():
    style = get_style("center_keyword")
    ass = build_ass(sample_words(), style, FONTS)
    assert ass_color(style.keyword_color) in ass
    assert "GITHUB" in ass                            # manual *marker* keyword
    for group in chunk_words(sample_words(), style):
        for line in group:
            assert 1 <= len(line) <= 3


def test_pink_highlight_draws_a_box_behind_the_spoken_word():
    ass = build_ass(sample_words(), get_style("pink_highlight"), FONTS, fonts_folder=FONTS_DIR)
    assert re.search(r"^Style: Box,", ass, re.M)
    boxes = [l for l in dialogue_lines(ass) if ",Box," in l]
    assert boxes and all(r"\p1}m " in l for l in boxes)


def test_boxed_style_uses_opaque_box():
    ass = build_ass(sample_words(), get_style("boxed"), FONTS)
    main = next(l for l in ass.splitlines() if l.startswith("Style: Main"))
    assert main.split(",")[15] == "3"     # BorderStyle 3 = box


def test_long_pause_starts_new_caption_group():
    words = [Word("isa", 0, 0.3), Word("dalawa", 2.0, 2.3)]
    assert len(chunk_words(words, get_style("classic"))) == 2


def test_special_characters_are_escaped():
    ass = build_ass([Word("{bad}\\word", 0, 1)], get_style("classic"), FONTS)
    assert "(bad)/word" in ass


@pytest.mark.parametrize("style", STYLES, ids=lambda s: s.name)
def test_every_style_renders_with_ffmpeg(style, tmp_path):
    """libass really draws something for every style (text pixels appear on a black frame)."""
    ass = build_ass(sample_words(), style, FONTS, fonts_folder=FONTS_DIR)
    (tmp_path / "c.ass").write_text(ass, encoding="utf-8")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    for f in FONTS_DIR.glob("*.otf"):
        (fonts / f.name).write_bytes(f.read_bytes())
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=1080x1920:d=2:r=10",
         "-vf", "subtitles=c.ass:fontsdir=fonts", "-ss", "1.65", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        cwd=tmp_path, capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    pixels = result.stdout
    assert len(pixels) == 1080 * 1920
    bright = sum(1 for p in pixels[::7] if p > 100)
    assert bright > 200, "no caption text visible"


def test_editorial_card_draws_a_cream_rounded_card_behind_each_group(tmp_path):
    """Style 14: one cream card (with a soft shadow) behind the whole caption group, ink text on it,
    rounded corners (the card's own corner stays the background colour)."""
    style = get_style("editorial_card")
    ass = build_ass(sample_words(), style, FONTS, fonts_folder=FONTS_DIR)
    assert r"\p1" in ass and "E6EFF4" in ass.upper()               # a drawn card in the cream colour
    (tmp_path / "c.ass").write_text(ass, encoding="utf-8")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    for f in FONTS_DIR.glob("*.otf"):
        (fonts / f.name).write_bytes(f.read_bytes())
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=0x2040a0:s=1080x1920:d=2:r=10",
         "-vf", "subtitles=c.ass:fontsdir=fonts", "-ss", "0.45", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        cwd=tmp_path, capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    import numpy as np
    img = np.frombuffer(result.stdout, np.uint8).reshape(1920, 1080, 3).astype(int)
    cream = (abs(img[..., 0] - 0xF4) < 8) & (abs(img[..., 1] - 0xEF) < 8) & (abs(img[..., 2] - 0xE6) < 8)
    assert cream.sum() > 20000, "no cream card"
    ys, xs = np.nonzero(cream)
    corner = img[ys.min(), xs.min()]
    assert not (abs(corner - [0xF4, 0xEF, 0xE6]) < 8).all()       # the corner is rounded off
    inside = img[ys.min():ys.max(), xs.min():xs.max()]
    ink = (inside.max(axis=2) < 60).sum()
    assert ink > 500, "no dark text on the card"
