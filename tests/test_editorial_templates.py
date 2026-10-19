"""The Premium Editorial graphics: each template rendered over a video with the user's own
pictures (Chromium draws, FFmpeg lays it over), word cues that time the parts, the user's picture
lists in projects, and the Director keeping these templates for the editorial style only."""

import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from autoedit import PROJECT_DIR, director, graphics
from autoedit.project import media_from_file, new_project, validate_project
from autoedit.project_render import render_frame
from tests import synthetic
from tests.gfx_helpers import add_graphics_track, draw_stills, graphic, needs_chromium

EDITORIAL = [t for t in graphics.templates() if "premium_editorial" in (t.get("styles") or [])]
IDS = [t["id"] for t in EDITORIAL]
COLOURS = ["blue", "lime", "magenta", "cyan", "orange", "purple"]


def test_the_editorial_set_is_complete():
    assert set(IDS) == {"editorial-headline", "subtitle-card", "kinetic-words", "marker-highlight",
                        "screenshot-collage", "mosaic-grid", "search-bar", "ui-panel", "editorial-checklist",
                        "countdown-timer", "storyboard-doc", "phone-mockup", "logo-badge",
                        "screenshot-montage", "palette-card", "profile-card"}


@pytest.fixture
def video(tmp_path):
    """3 s of plain red video and six coloured "screenshots" (the user's own pictures)."""
    clip = tmp_path / "red.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=720x1280:r=30:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
    p = new_project("e", normalize_audio=False)
    p["media"] = [media_from_file(clip, "vid")]
    for i, colour in enumerate(COLOURS):
        pic = synthetic.make_image(tmp_path / f"shot{i}.png", color=colour, size="900x600")
        p["media"].append(media_from_file(pic, f"shot{i}"))
    p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "vid", "start": 0, "duration": 3,
                                "in": 0, "out": 3}]
    return tmp_path, p


def params_for(meta):
    params = dict(meta["sample"])
    keys = {i["key"] for i in meta["inputs"]}
    if "images" in keys:
        params["images"] = [f"shot{i}" for i in range(4)]
    if "image" in keys:
        params["image"] = "shot0"
    return params


@needs_chromium
@pytest.mark.parametrize("meta", EDITORIAL, ids=IDS)
def test_each_template_renders_over_the_video(video, meta):
    tmp, p = video
    d = min(2.6, meta["maxDuration"])
    add_graphics_track(p, [graphic("g1", meta["id"], 0.0, d, x=meta["anchor"]["x"], y=meta["anchor"]["y"],
                                   **params_for(meta))])
    assert validate_project(p) == []
    out = tmp / "f.png"
    render_frame(p, d * 0.7, out, base_dir=tmp)
    img = np.asarray(Image.open(out).convert("RGB")).astype(int)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    covered = ~((r > 200) & (g < 60) & (b < 60))
    assert covered.sum() > 15000, f"{meta['id']} is not visible over the video"
    if "images" in {i["key"] for i in meta["inputs"]} or "image" in {i["key"] for i in meta["inputs"]}:
        # the user's pictures are plain blue / lime / magenta / cyan: one of them is on screen
        blue = (b > 180) & (r < 80) & (g < 80)
        lime = (g > 180) & (r < 80) & (b < 80)
        magenta = (r > 180) & (b > 180) & (g < 80)
        cyan = (g > 180) & (b > 180) & (r < 80)
        assert (blue | lime | magenta | cyan).sum() > 1500, f"{meta['id']} does not show the user's picture"


def stills(folder, template, params, times, duration=3.0):
    jobs = [{"id": f"{template}-{i}", "template": template, "params": params, "duration": duration, "fps": 30,
             "frames": 0, "quality": "final", "meta": str(folder / f"{template}-{i}.json"),
             "stills": [{"t": t, "out": str(folder / f"{template}-{i}.png")}]} for i, t in enumerate(times)]
    draw_stills(jobs, folder)
    return [np.asarray(Image.open(folder / f"{template}-{i}.png").convert("RGBA")).astype(int) for i in range(len(times))]


def ink(img):
    return int((img[..., 3] > 60).sum())


@needs_chromium
def test_cues_time_the_words_to_the_speech(tmp_path):
    """Kinetic words: the second word waits for its cue (when it is spoken)."""
    early, late = stills(tmp_path, "kinetic-words", {"text": "ONE TWO", "cues": [0.1, 2.0]}, [1.5, 2.6])
    assert ink(late) > ink(early) * 1.4                 # TWO appeared at 2.0 s, not before
    even_early, = stills(tmp_path, "kinetic-words", {"text": "ONE TWO"}, [1.5])
    assert ink(even_early) > ink(early) * 1.3           # without cues both words are in by 1.5 s


@needs_chromium
def test_checklist_ticks_on_its_cues(tmp_path):
    before, after = stills(tmp_path, "editorial-checklist",
                           {"text": "Steps", "items": ["One", "Two"], "cues": [0.6, 2.2], "accent": "#ff0000"},
                           [1.6, 2.7])
    reds = [int(((a[..., 0] > 180) & (a[..., 1] < 80) & (a[..., 2] < 80) & (a[..., 3] > 200)).sum())
            for a in (before, after)]
    assert reds[1] > reds[0] * 1.5                      # the second tick fills only after 2.2 s


@needs_chromium
def test_search_bar_types_the_query(tmp_path):
    a, b = stills(tmp_path, "search-bar", {"text": "how to edit a premium video", "cues": [0.4, 2.0]}, [0.9, 2.3])
    dark = [int(((x[..., 0] < 90) & (x[..., 3] > 200)).sum()) for x in (a, b)]
    assert dark[1] > dark[0] * 1.5                      # more letters typed later


@needs_chromium
def test_countdown_counts_down(tmp_path):
    a, b = stills(tmp_path, "countdown-timer", {"number": 3}, [0.5, 2.7])
    assert not np.array_equal(a, b)
    meta = json.loads((tmp_path / "countdown-timer-0.json").read_text())
    assert meta["w"] <= 900 and meta["h"] <= 1100


def test_cue_times_follow_the_cues_or_spread_evenly():
    node = shutil.which("node")
    if not node:
        pytest.skip("needs Node.js")
    engine = (PROJECT_DIR / "desktop" / "graphics" / "engine.js").as_uri()
    code = (f"import('{engine}').then(m=>console.log(JSON.stringify(["
            "m.cueTimes({cues:[0.5,1.2]},2,3),"
            "m.cueTimes({cues:[]},3,3,{from:0.3,to:1.5}),"
            "m.cueTimes({cues:[0.5,1.0]},4,3),"
            "m.cueTimes({cues:[9]},1,3),"
            "m.resolveParams({defaults:{}},{cues:[2,'x',-1,1],images:['a',3,'b']}).cues,"
            "m.resolveParams({defaults:{}},{cues:[2,'x',-1,1],images:['a',3,'b']}).images])))")
    out = json.loads(subprocess.run([node, "-e", code], capture_output=True, text=True, check=True).stdout)
    assert out[0] == [0.5, 1.2]
    assert out[1] == pytest.approx([0.3, 0.9, 1.5])
    assert out[2] == pytest.approx([0.5, 1.0, 1.5, 2.0])           # parts without a cue keep the pace
    assert out[3] == pytest.approx([0.3])                           # a cue after the end is ignored
    assert out[4] == [1, 2] and out[5] == ["a", "b"]


# ---------------------------------------------------------------- projects and the Director

def test_picture_lists_are_checked_and_change_the_cache_key(video):
    tmp, p = video
    add_graphics_track(p, [graphic("g1", "mosaic-grid", 0, 2, images=["shot0", "nope"])])
    assert any("unknown image media 'nope'" in x for x in validate_project(p))
    p["tracks"][-1]["clips"][0]["params"]["images"] = ["shot0", "vid"]
    assert any("is video, not an image" in x for x in validate_project(p))
    p["tracks"][-1]["clips"][0]["params"]["images"] = ["shot0", "shot1"]
    assert validate_project(p) == []
    media = {m["id"]: m for m in p["media"]}
    job = graphics.job_for_clip(p["tracks"][-1]["clips"][0], 30, media, tmp)
    assert job["params"]["images"] == [str(tmp / "shot0.png"), str(tmp / "shot1.png")]
    synthetic.make_image(tmp / "shot1.png", color="white", size="900x601")      # the picture changed
    assert graphics.job_for_clip(p["tracks"][-1]["clips"][0], 30, media, tmp)["key"] != job["key"]


def test_cues_are_part_of_the_schema(video):
    _tmp, p = video
    add_graphics_track(p, [graphic("g1", "kinetic-words", 0, 2, text="A B", cues=[0.2, 0.9])])
    assert validate_project(p) == []
    p["tracks"][-1]["clips"][0]["params"]["cues"] = [-1]
    assert validate_project(p)


@pytest.mark.parametrize("style", ["promoter", "calm_documentary", "meme", "news", "luxury", "minimal"])
def test_other_styles_never_use_the_editorial_templates(style):
    ctx = director.Ctx.__new__(director.Ctx)
    ctx.style_name, ctx.style = style, director.STYLES[style]
    assert all(m not in director.catalog_text(ctx) for m in IDS)
    for meta in EDITORIAL:
        it = {"text": "hello world", "list": ["a", "b"], "number": 5, "image": "x", "mood": meta["moods"][0],
              "start": 1.0}
        assert director.template_score(ctx, meta, it, {}) is None


def test_palette_comes_from_the_users_picture(tmp_path):
    from PIL import Image
    img = Image.new("RGB", (300, 100), "#1f2a44")
    img.paste(Image.new("RGB", (100, 100), "#c8553d"), (100, 0))
    img.paste(Image.new("RGB", (60, 100), "#f2c46d"), (240, 0))
    img.save(tmp_path / "brand.png")
    colours = graphics.palette_from_image(tmp_path / "brand.png", 3)
    assert colours[0] == "#1f2a44" and set(colours) == {"#1f2a44", "#c8553d", "#f2c46d"}
