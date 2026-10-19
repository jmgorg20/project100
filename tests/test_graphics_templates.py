"""The template library: its catalog, and every template drawn by a real Chromium."""

import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from autoedit import PROJECT_DIR, graphics
from tests.gfx_helpers import draw_stills, needs_chromium

CAT = graphics.catalog()
TEMPLATES = CAT["templates"]
IDS = [t["id"] for t in TEMPLATES]


# ---------------------------------------------------------------- the catalog (no browser)

def test_the_library_has_at_least_thirty_templates():
    assert len(TEMPLATES) >= 30 and len(set(IDS)) == len(IDS)


def test_catalog_matches_the_template_files():
    """graphics_catalog.json is generated: regenerate it with `npm run graphics-catalog`."""
    node = shutil.which("node")
    if not node:
        pytest.skip("needs Node.js")
    script = (PROJECT_DIR / "desktop" / "graphics" / "build-catalog.mjs").as_uri()
    out = subprocess.run([node, "-e", f"import('{script}').then(m=>console.log(JSON.stringify(m.catalog())))"],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == CAT


@pytest.mark.parametrize("meta", TEMPLATES, ids=IDS)
def test_every_template_declares_what_it_needs(meta):
    assert meta["name"] and meta["tl"] and meta["category"]
    assert meta["moods"] and set(meta["moods"]) <= set(CAT["moods"])
    assert meta["inputs"] and all(i["type"] in ("text", "number", "image", "images", "list") for i in meta["inputs"])
    assert meta["minDuration"] <= meta["duration"] <= meta["maxDuration"]
    assert 0 <= meta["anchor"]["x"] <= 1 and 0 <= meta["anchor"]["y"] <= 1
    assert meta["zone"] in ("any", "center", "lower", "upper", "side")
    assert set(meta["fields"]) <= set(graphics.PARAM_KEYS)
    assert {"color", "size", "intensity"} <= set(meta["fields"]) or meta["id"].startswith("emoji")
    for need in meta["inputs"]:
        if need["required"]:
            assert need["key"] in meta["sample"], f"sample is missing {need['key']}"
    assert meta["box"]["w"] <= 900 and meta["maxChars"] > 0
    if meta["defaults"].get("font"):
        assert meta["defaults"]["font"] in CAT["fonts"]


def test_every_mood_has_templates_and_variety():
    for mood in CAT["moods"]:
        assert sum(mood in t["moods"] for t in TEMPLATES) >= 3, mood
    assert len({t["category"] for t in TEMPLATES}) >= 6


# ---------------------------------------------------------------- drawn by Chromium

def draw_matrix(folder):
    jobs = []
    for t in TEMPLATES:
        d = t["duration"]
        times = [0.0, d * 0.45, 0.1, d * 0.45, d - 0.04]
        jobs.append({"id": t["id"], "template": t["id"], "params": t["sample"], "duration": d,
                     "fps": 30, "frames": 0, "quality": "final",
                     "meta": str(folder / f"{t['id']}.json"),
                     "stills": [{"t": tt, "out": str(folder / f"{t['id']}_{i}.png")}
                                for i, tt in enumerate(times)]})
    return folder, draw_stills(jobs, folder)


@pytest.fixture(scope="module")
def drawn(tmp_path_factory):
    return draw_matrix(tmp_path_factory.mktemp("matrix"))


@pytest.fixture(scope="module")
def drawn_again(tmp_path_factory):
    return draw_matrix(tmp_path_factory.mktemp("matrix2"))


def png(folder, tid, i):
    return np.asarray(Image.open(folder / f"{tid}_{i}.png").convert("RGBA")).astype(int)


@needs_chromium
@pytest.mark.parametrize("meta", TEMPLATES, ids=IDS)
def test_template_draws_a_non_empty_well_placed_frame(drawn, meta):
    folder, metas = drawn
    info = metas[meta["id"]]
    img = png(folder, meta["id"], 1)
    assert img.shape[1] == info["tileW"] and img.shape[0] == info["tileH"]
    assert info["tileW"] == info["w"] + 2 * info["pad"]
    opaque = img[..., 3] > 40
    assert opaque.sum() >= 300, "the middle of the graphic is (nearly) empty"
    ys, xs = np.nonzero(opaque)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    # what it draws is centred in its tile (so x/y place its centre); pointers / bursts less so
    slack = 0.42 if meta["category"] in ("pointer", "emoji") else 0.3
    assert abs(cx - info["tileW"] / 2) <= slack * info["tileW"], (cx, info["tileW"])
    assert abs(cy - info["tileH"] / 2) <= slack * info["tileH"], (cy, info["tileH"])
    # the declared box (used to plan placement) is close to the real size
    for real, declared in ((info["w"], meta["box"]["w"]), (info["h"], meta["box"]["h"])):
        assert 0.4 * declared <= real <= 1.8 * declared, (meta["id"], real, declared)
    assert info["w"] <= 900 and info["h"] <= 1100


@needs_chromium
@pytest.mark.parametrize("meta", TEMPLATES, ids=IDS)
def test_template_draws_the_same_pixels_every_time(drawn, drawn_again, meta):
    """The same project gives the same frames: two separate runs match (templates use no random
    numbers, timers or CSS transitions). Chromium's anti-aliasing may differ by a level or two on
    a handful of edge pixels between runs, so that much is allowed."""
    for i in range(5):
        a, b = png(drawn[0], meta["id"], i), png(drawn_again[0], meta["id"], i)
        diff = np.abs(a - b).max(axis=2)
        assert a.shape == b.shape and (diff > 8).sum() == 0 and (diff > 0).sum() <= max(20, a.size // 4000)


@needs_chromium
@pytest.mark.parametrize("meta", TEMPLATES, ids=IDS)
def test_template_animates_in_and_out(drawn, meta):
    folder, _ = drawn
    start, mid = png(folder, meta["id"], 0), png(folder, meta["id"], 1)
    end = png(folder, meta["id"], 4)
    amount = lambda a: int((a[..., 3] > 40).sum())  # noqa: E731
    assert amount(mid) > amount(start) * 1.0 or not np.array_equal(start, mid)
    assert amount(end) <= amount(mid) * 1.05 + 50     # it has gone / is going out at the end


# ---------------------------------------------------------------- Taglish text

TAGLISH = ["Pinakamagandang pagkakataon para sa mga kababayan natin ngayon",
           "Ñoño at Niño: ang mga pangalang may ñ ay tama",
           "Magkano ang kikitain mo? 🔥💸 Alamin dito!",
           "Kapaligiran-pangkalikasan-at-pangkabuhayan-programa"]


@pytest.fixture(scope="module")
def taglish(tmp_path_factory):
    folder = tmp_path_factory.mktemp("taglish")
    text_templates = [t for t in TEMPLATES if t["inputs"][0]["key"] == "text"
                      and t["id"] not in ("emoji-pop", "emoji-burst", "heart-like")]
    jobs = []
    for t in text_templates:
        for k, text in enumerate(TAGLISH):
            tid = f"{t['id']}__{k}"
            jobs.append({"id": tid, "template": t["id"], "params": {**t["sample"], "text": text},
                         "duration": t["duration"], "fps": 30, "frames": 0, "quality": "final",
                         "meta": str(folder / f"{tid}.json"),
                         "stills": [{"t": t["duration"] * 0.5, "out": str(folder / f"{tid}.png")}]})
    return folder, draw_stills(jobs, folder), text_templates


@needs_chromium
def test_taglish_and_long_words_always_fit_the_frame(taglish):
    folder, metas, text_templates = taglish
    for t in text_templates:
        for k in range(len(TAGLISH)):
            info = metas[f"{t['id']}__{k}"]
            assert info["w"] <= 900 and info["h"] <= 1100, (t["id"], k, info["w"], info["h"])
            img = np.asarray(Image.open(folder / f"{t['id']}__{k}.png").convert("RGBA"))
            assert (img[..., 3] > 40).sum() > 200, (t["id"], k)


@needs_chromium
def test_normal_sentences_are_never_broken_inside_a_word(taglish):
    """Words only break when one single word cannot fit even at the smallest size."""
    _folder, metas, text_templates = taglish
    for t in (t for t in text_templates if t["maxChars"] >= 40):
        for k in (0, 1, 2):
            assert metas[f"{t['id']}__{k}"]["report"]["broke"] is False, (t["id"], k)


@needs_chromium
def test_text_never_shrinks_below_the_readable_minimum_unless_reported(taglish):
    _folder, metas, text_templates = taglish
    for t in text_templates:
        for k in range(len(TAGLISH)):
            rep = metas[f"{t['id']}__{k}"]["report"]
            if rep["fontPx"] is not None:
                assert rep["fontPx"] >= t["minFont"] - 0.6 or rep["broke"] or rep["shrunk"]
