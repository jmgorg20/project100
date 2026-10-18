"""Video formats: the specs, choosing one, and every step checked on real projects and rendered
pixels (layouts, cut-outs with a stand-in person segmenter, green screen keying, list items,
countdowns, wipes, A vs B, callouts, reactions, voice-over with B-roll)."""

import json
import subprocess
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from autoedit import director, formats, segment
from autoedit.config import load_config
from autoedit.llm import LLMError
from autoedit.project import media_from_file, validate_project
from autoedit.project_render import render_frame
from tests.director_helpers import make_project, make_words
from tests.gfx_helpers import needs_chromium

NS = types.SimpleNamespace


@pytest.fixture(autouse=True)
def caches(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEDIT_SFX_CACHE", str(tmp_path / "sfx"))
    monkeypatch.setenv("AUTOEDIT_MASK_CACHE", str(tmp_path / "masks"))


def cfg():
    return load_config()


def video(path, color="red", size="720x1280", seconds=3, box=None, bg=None):
    """A test video: a flat colour, or a `box` colour rectangle (the "person") on `bg`."""
    if box:
        src = (f"color=c={bg}:s={size}:r=30:d={seconds}[b];color=c={box}:s=240x600:r=30:d={seconds}[p];"
               f"[b][p]overlay=240:400[v]")
    else:
        src = f"color=c={color}:s={size}:r=30:d={seconds}[v]"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex",
                    f"{src};sine=f=440:r=48000:d={seconds}[a]", "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return Path(path)


def picture(path, color="blue", size="1080x1920"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s={size}:d=1",
                    "-frames:v", "1", str(path)], check=True)
    return Path(path)


def project_on(path, words=None, seconds=3):
    p = make_project(words=words or make_words("Hello there kumusta kayo mga kaibigan .".split(), per_word=0.35),
                     duration=seconds)
    m = media_from_file(path, "m1")
    p["media"] = [m]
    p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "m1", "start": 0, "duration": seconds,
                                "in": 0, "out": seconds}]
    return p


def frame(tmp, project, t, name="f.png"):
    out = tmp / name
    render_frame(project, t, out, base_dir=tmp)
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def is_red(px):
    return px[0] > 180 and px[1] < 70 and px[2] < 70


def is_blue(px):
    return px[2] > 180 and px[0] < 70 and px[1] < 70


# ---------------------------------------------------------------- the specs

def test_thirteen_formats_all_valid():
    specs = formats.all_formats()
    assert len(specs) >= 13
    assert {"talking_head", "yap", "screenshare", "split_screen", "reaction", "voiceover_broll", "listicle",
            "ranking", "before_after", "clone", "green_screen", "comparison", "explainer"} <= set(specs)
    for spec in specs.values():
        assert formats.spec_problems(spec) == []
        assert spec["name"] and spec["tl"] and spec["about_tl"]
        assert all(s["op"] in formats.OPS for s in spec["steps"])
        assert all(i["tl"] for i in spec["inputs"])


def test_a_bad_spec_is_refused():
    bad = json.loads(json.dumps(formats.get("reaction")))
    bad["steps"].append({"op": "explode"})
    bad["steps"].append({"op": "layout", "type": "pip", "with": "nobody"})
    problems = formats.spec_problems(bad)
    assert any("explode" in p for p in problems) and any("nobody" in p for p in problems)


def test_adding_a_format_needs_only_a_json_file(tmp_path, monkeypatch):
    """A new format made from the existing steps, without touching any code."""
    folder = tmp_path / "formats"
    folder.mkdir()
    for f in formats.FORMATS_DIR.glob("*.json"):
        (folder / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    new = {"id": "tutorial_pip", "name": "Tutorial with your face small", "tl": "Tutorial", "about": "x",
           "about_tl": "x", "keywords": ["tutorial pip"],
           "inputs": [{"role": "main", "kinds": ["video"], "required": True, "label": "You", "tl": "Ikaw"},
                      {"role": "screen", "kinds": ["video"], "required": True, "label": "Screen", "tl": "Screen"}],
           "steps": [{"op": "layout", "type": "pip", "with": "screen", "corner": "bottom_right", "size": 0.3}]}
    (folder / "tutorial_pip.json").write_text(json.dumps(new), encoding="utf-8")
    monkeypatch.setattr(formats, "FORMATS_DIR", folder)
    monkeypatch.setattr(formats, "SCHEMA_FILE", folder / "format.schema.json")
    formats.all_formats.cache_clear()
    try:
        assert formats.choose("make a tutorial pip", {"main": ["a"], "screen": ["b"]})[0] == "tutorial_pip"
    finally:
        formats.all_formats.cache_clear()


# ---------------------------------------------------------------- choosing

@pytest.mark.parametrize("instruction, inputs, expected", [
    ("Edit this like a listicle, 5 tips", {"main": ["v"]}, "listicle"),
    ("top 5 countdown", {"main": ["v"]}, "ranking"),
    ("make it a reaction video", {"main": ["v"], "source": ["s"]}, "reaction"),
    ("make it a reaction video", {"main": ["v"]}, "talking_head"),          # no video to react to
    ("", {"main": ["v"], "screen": ["s"]}, "screenshare"),                  # the file says it
    ("", {"main": ["v"], "takes": ["t"]}, "clone"),
    ("", {"main": ["v"], "background": ["b"]}, "green_screen"),
    ("", {"voiceover": ["a"], "broll": ["b"]}, "voiceover_broll"),
    ("before and after ng kwarto ko", {"main": ["v"]}, "before_after"),
    ("iPhone vs Android", {"main": ["v"]}, "comparison"),
    ("just clean it up", {"main": ["v"]}, "talking_head"),
])
def test_choose_a_format(instruction, inputs, expected):
    assert formats.choose(instruction, inputs)[0] == expected


def test_a_forced_format_needs_its_files():
    assert formats.choose("listicle", {"main": ["v"], "screen": ["s"]}, forced="screenshare")[0] == "screenshare"
    with pytest.raises(formats.FormatError, match="Screen recording"):
        formats.choose("", {"main": ["v"]}, forced="screenshare")


def test_the_ai_can_pick_when_nothing_else_decides(monkeypatch):
    import autoedit.llm as llm
    answers = [json.dumps({"format": "nonsense", "reason": "x"}),
               json.dumps({"format": "explainer", "reason": "teaching"})]
    calls = []

    def fake(provider, model, system, prompt, schema, **kw):
        calls.append(prompt)
        return answers[len(calls) - 1], {"input_tokens": 1, "output_tokens": 1}, model
    monkeypatch.setattr(llm, "ask_json", fake)
    fid, reason = formats.choose("gawin mong maganda", {"main": ["v"]}, provider="groq", model="m")
    assert fid == "explainer" and "teaching" in reason and len(calls) == 2

    def broken(*a, **k):
        raise LLMError("offline")
    monkeypatch.setattr(llm, "ask_json", broken)
    assert formats.choose("gawin mong maganda", {"main": ["v"]}, provider="groq", model="m")[0] == "talking_head"


def test_format_settings():
    c = formats.cfg_for(formats.get("clone"), cfg())
    assert c["pacing"]["silence_threshold"] >= 30 and not c["pacing"]["remove_fillers"]
    y = formats.cfg_for(formats.get("yap"), cfg())
    assert y["pacing"]["silence_threshold"] == 0.15
    assert formats.caption_overrides(formats.get("yap")) == {"zone": "center", "words_per_line": 3}


# ---------------------------------------------------------------- steps, on rendered pixels

def test_split_screen_ratio_and_offset(tmp_path):
    main = video(tmp_path / "me.mp4", "red")
    other = tmp_path / "other.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex",
                    "color=c=blue:s=720x1280:r=30:d=2[a];color=c=green:s=720x1280:r=30:d=4[b];[a][b]concat=n=2:v=1[v]",
                    "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(other)], check=True)
    p = project_on(main)
    out, _ = formats.apply(p, "split_screen", {"main": [main], "second": [other]}, cfg(), tmp_path)
    assert validate_project(out) == []
    img = frame(tmp_path, out, 1.0)
    assert is_blue(img[400, 540]) and is_red(img[1500, 540])          # 50 / 50
    # the other video started 2 s earlier: an offset shows its later (green) part
    out2, _ = formats.apply(p, "split_screen", {"main": [main], "second": [other], "offsets": {"second": 2.0}},
                            cfg(), tmp_path)
    img2 = frame(tmp_path, out2, 1.0, "g.png")
    assert img2[400, 540][1] > 100 and img2[400, 540][2] < 90


def test_reaction_pip_corner_and_moving_border(tmp_path):
    main = video(tmp_path / "me.mp4", "red")
    src = video(tmp_path / "src.mp4", "blue")
    p = project_on(main, words=make_words("Grabe ang galing nito wow .".split(), per_word=0.4))
    out, notes = formats.apply(p, "reaction", {"main": [main], "source": [src]}, cfg(), tmp_path)
    assert validate_project(out) == []
    layout = out["tracks"][0]["clips"][0]["layout"]
    assert layout["type"] == "pip" and layout["corner"] == "top_left" and layout["animated"]
    a = frame(tmp_path, out, 0.2, "a.png")
    b = frame(tmp_path, out, 1.5, "b.png")
    assert is_blue(a[1500, 900])                    # the reacted-to video fills the screen
    assert is_red(a[400, 200])                      # you, small, top left
    # the border colour moves (hue changes over time)
    edge = (190 + 2, 40 + 120)
    assert np.abs(a[edge] - b[edge]).sum() > 40
    emojis = [c for c in director.graphic_clips_of(out) if c["template"] == "emoji-pop"]
    assert emojis and emojis[0]["params"]["emoji"]


def fake_segmenter(monkeypatch):
    """A stand-in for MediaPipe's person segmenter: red pixels are "the person"."""
    from autoedit import tracking

    class Seg:
        @classmethod
        def create_from_options(cls, options):
            return cls()

        def segment_for_video(self, image, ts):
            d = image.data.astype(np.float32)
            prob = ((d[..., 0] > 150) & (d[..., 1] < 100)).astype(np.float32)
            return NS(confidence_masks=[NS(numpy_view=lambda: prob)])

        def close(self):
            pass

    mp = NS(Image=lambda image_format, data: NS(data=data), ImageFormat=NS(SRGB="SRGB"))
    vision = NS(RunningMode=NS(VIDEO="VIDEO"), ImageSegmenter=Seg, ImageSegmenterOptions=lambda **kw: NS(**kw))
    monkeypatch.setattr(tracking, "import_mediapipe", lambda: (mp, lambda **kw: NS(**kw), vision))
    monkeypatch.setattr(segment, "status", lambda cfg=None: {"available": True, "installed": True,
                                                              "model": "x", "problems": []})


def test_clone_yourself_cuts_out_the_other_take(tmp_path, monkeypatch):
    fake_segmenter(monkeypatch)
    take1 = video(tmp_path / "take1.mp4", box="red", bg="gray")
    take2 = tmp_path / "take2.mp4"            # the same room, the person on the other side
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex",
                    "color=c=gray:s=720x1280:r=30:d=3[b];color=c=red:s=160x500:r=30:d=3[p];[b][p]overlay=60:300[v];"
                    "sine=f=330:r=48000:d=3[a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(take2)], check=True)
    p = project_on(take1)
    out, notes = formats.apply(p, "clone", {"main": [take1], "takes": [take2]}, cfg(), tmp_path)
    assert validate_project(out) == []
    clone = next(t for t in out["tracks"] if t["id"] == "clone2")["clips"][0]
    assert clone["mask"] == {"type": "person"}
    assert any(t["kind"] == "audio" and t.get("role") == "original" for t in out["tracks"])
    img = frame(tmp_path, out, 1.0)
    # 720 -> 1080: the first take's person at x 240-480 -> 360-720; the clone at 60-220 -> 90-330
    assert is_red(img[1100, 540])                   # you (take 1)
    assert is_red(img[1000, 200])                   # you again (take 2, cut out)
    assert img[300, 900][0] < 160                   # the background stays the room (gray), not red


def test_green_screen_with_a_real_green_screen_is_keyed(tmp_path):
    me = video(tmp_path / "me.mp4", box="red", bg="0x00FF00")
    bg = picture(tmp_path / "beach.png", "blue")
    p = project_on(me)
    out, notes = formats.apply(p, "green_screen", {"main": [me], "background": [bg]}, cfg(), tmp_path)
    assert validate_project(out) == []
    you = next(t for t in out["tracks"] if t["id"] == "you")["clips"][0]
    assert you["mask"]["type"] == "chroma"
    assert any("keyed out" in n for n in notes)
    img = frame(tmp_path, out, 1.0)
    assert is_blue(img[200, 200])                   # the green is gone: the new background shows
    assert is_red(img[1000, 540])                   # you stay


def test_green_screen_without_a_green_screen_uses_person_detection(tmp_path, monkeypatch):
    fake_segmenter(monkeypatch)
    me = video(tmp_path / "me.mp4", box="red", bg="gray")
    bg = picture(tmp_path / "city.png", "blue")
    p = project_on(me)
    out, _ = formats.apply(p, "green_screen", {"main": [me], "background": [bg]}, cfg(), tmp_path)
    assert next(t for t in out["tracks"] if t["id"] == "you")["clips"][0]["mask"] == {"type": "person"}
    img = frame(tmp_path, out, 1.0)
    assert is_blue(img[200, 200]) and is_red(img[1000, 540])


def test_person_cutout_without_the_model_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(segment, "status", lambda cfg=None: {"available": False, "installed": False,
                                                              "model": "x", "problems": ["no mediapipe"]})
    me = video(tmp_path / "me.mp4", box="red", bg="gray")
    with pytest.raises(Exception, match="person-cutout model|MediaPipe"):
        segment.person_mask(me, 0, 1, 30)


def test_mask_cleanup_removes_specks_and_softens_edges():
    m = np.zeros((40, 40), np.float32)
    m[10:30, 10:30] = 1.0
    m[2, 2] = 1.0                                   # a speck
    out = segment.MaskCleaner(steady=0)(m)
    assert out[2, 2] < 0.1 and out[20, 20] > 0.95
    assert 0.05 < out[20, 10] < 0.95                # a soft edge


SPOKEN_LIST = ("Tatlong tips para sa inyo . Una , mag-ipon araw-araw . Pangalawa , iwasan ang utang . "
               "Pangatlo , mag-invest sa sarili .").split()


def test_listicle_items_on_the_words_with_numbers_and_sounds(tmp_path):
    p = make_project(words=make_words(SPOKEN_LIST), tracking=None)
    out, notes = formats.apply(p, "listicle", {"main": ["x"]}, cfg(), tmp_path)
    items = [c for c in director.graphic_clips_of(out) if c["template"] == "list-item"]
    assert [c["params"]["number"] for c in items] == [1, 2, 3]
    words = director.timeline_words(out)
    for c, w in zip(items, ("Una", "Pangalawa", "Pangatlo")):
        start = next(x["start"] for x in words if x["text"].startswith(w))
        assert abs(c["start"] - start) <= 1 / 30 + 1e-6
    assert "mag-ipon" in items[0]["params"]["text"]
    sfx = [c for t in out["tracks"] if t.get("role") == "sfx" for c in t["clips"]]
    assert len(sfx) == 3
    assert validate_project(out) == []


def test_ranking_counts_down_given_items(tmp_path):
    words = make_words("Ito ang mga paborito ko . Ang mura . Ang maganda . Ang pinakamaganda sa lahat .".split())
    p = make_project(words=words)
    out, _ = formats.apply(p, "ranking", {"main": ["x"], "items": ["Mura", "Maganda", "Pinakamaganda"]}, cfg(),
                           tmp_path)
    ranks = sorted((c for c in director.graphic_clips_of(out) if c["template"] == "rank-number"),
                   key=lambda c: c["start"])
    assert [c["params"]["number"] for c in ranks] == [3, 2, 1]
    assert [c["params"]["text"] for c in ranks] == ["Mura", "Maganda", "Pinakamaganda"]
    assert validate_project(out) == []


def test_before_after_wipe_starts_on_the_after_word(tmp_path):
    words = make_words("Ito ang kwarto ko dati . Ngayon tingnan ninyo ang ganda .".split())
    p = make_project(words=words)
    out, _ = formats.apply(p, "before_after", {"main": ["x"]}, cfg(), tmp_path)
    wipe = next(c for t in out["tracks"] for c in t["clips"] if c["type"] == "wipe")
    after = next(w for w in director.timeline_words(out) if w["text"] == "Ngayon")
    assert abs(wipe["start"] - after["start"]) < 0.01
    assert any(c["template"] == "before-after-tag" for c in director.graphic_clips_of(out))
    assert validate_project(out) == []


def test_comparison_finds_a_vs_b(tmp_path):
    words = make_words("Alin ang mas maganda iPhone vs Android para sa inyo .".split())
    p = make_project(words=words)
    out, _ = formats.apply(p, "comparison", {"main": ["x"]}, cfg(), tmp_path)
    vs = [c for c in director.graphic_clips_of(out) if c["template"] == "versus-split"]
    assert vs and vs[0]["params"]["text"] == "iPhone" and vs[0]["params"]["text2"] == "Android"
    assert validate_project(out) == []


def test_explainer_callouts_and_screenshots(tmp_path):
    shot = picture(tmp_path / "export_button.png", "white", "800x500")
    words = make_words(("Simple lang ito . Tip , i-save muna bago mag-export . Tapos pindutin ang export "
                        "button sa itaas .").split())
    p = make_project(words=words)
    out, _ = formats.apply(p, "explainer", {"main": ["x"], "screenshots": [shot]}, cfg(), tmp_path)
    g = director.graphic_clips_of(out)
    call = [c for c in g if c["template"] == "callout-box"]
    frame_ = [c for c in g if c["template"] == "screenshot-frame"]
    assert call and call[0]["params"]["text2"] == "TIP" and "i-save" in call[0]["params"]["text"]
    assert frame_ and frame_[0]["params"]["image"]
    export_word = next(w for w in director.timeline_words(out) if w["text"] == "export")
    assert abs(frame_[0]["start"] - export_word["start"]) <= 1 / 30 + 1e-6
    assert validate_project(out) == []


def test_yap_places_your_broll_every_few_seconds(tmp_path):
    clip = video(tmp_path / "b1.mp4", "green", seconds=4)
    pic = picture(tmp_path / "b2.png")
    p = make_project(words=make_words(SPOKEN_LIST * 2))
    out, _ = formats.apply(p, "yap", {"main": ["x"], "broll": [clip, pic]}, cfg(), tmp_path)
    broll = next(t for t in out["tracks"] if t["id"] == "format-broll")["clips"]
    starts = [c["start"] for c in broll]
    assert len(broll) >= 3 and all(b - a >= 4.4 for a, b in zip(starts, starts[1:]))
    assert validate_project(out) == []


def test_voiceover_with_broll_builds_a_project_with_no_face(tmp_path):
    from autoedit.words import Word
    vo = tmp_path / "vo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:r=48000:d=6", str(vo)], check=True)
    b1, b2 = video(tmp_path / "b1.mp4", "red", seconds=2), picture(tmp_path / "b2.png", "blue")
    words = [Word(text=t, start=s, end=s + 0.3) for t, s in
             (("Ang", 0.2), ("Pilipinas.", 0.6), ("Maganda", 2.1), ("dito.", 2.5), ("Tara", 4.0), ("na!", 4.4))]
    p = formats.build_voiceover_project(vo, [b1, b2], cfg(), words)
    assert validate_project(p) == []
    main = p["tracks"][0]["clips"]
    assert abs(sum(c["duration"] for c in main) - 6.0) < 0.01
    assert main[0]["start"] == 0 and {c["media"] for c in main} == {"b1", "b2"}
    assert next(t for t in p["tracks"] if t["id"] == "voiceover")["clips"][0]["media"] == "vo"
    assert p["tracks"][3]["clips"]


@needs_chromium
def test_listicle_renders_with_its_graphics(tmp_path):
    me = video(tmp_path / "me.mp4", "gray", seconds=4)
    words = make_words("Una , mag-ipon . Pangalawa , mag-invest .".split(), per_word=0.5)
    p = project_on(me, words=words, seconds=4)
    out, _ = formats.apply(p, "listicle", {"main": [me]}, cfg(), tmp_path)
    first = min(c["start"] for c in director.graphic_clips_of(out))
    img = frame(tmp_path, out, first + 0.8)
    plain = frame(tmp_path, project_on(me, words=words, seconds=4), first + 0.8, "p.png")
    assert np.abs(img - plain).sum(axis=2).astype(bool).sum() > 5000
