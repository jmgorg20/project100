"""The editorial planner (PREMIUM EDITORIAL VIRAL): scenes of 2-4 s, one beat per scene that suits
the words, every element timed to the spoken words, only the creator's own files, the AI's choices
checked (retry, then the rules), one scene planned again, and a full edit rendered with FFmpeg and
Chromium and checked frame by frame."""

import json
import subprocess

import numpy as np
import pytest
from PIL import Image

from autoedit import director, editorial, graphics, presets, storyboard
from autoedit.graphics_check import check_project
from autoedit.llm import LLMError
from autoedit.project import media_from_file, validate_project
from autoedit.project_render import render_frame, render_project
from tests import synthetic
from tests.director_helpers import cfg as load_cfg
from tests.director_helpers import face_tracking, make_project, make_words
from tests.gfx_helpers import needs_chromium
from tests.test_director import fake_llm

SCRIPT = ("Ito ang sikreto ng premium na video . Una , malinaw na audio , pangalawa , magandang ilaw , "
          "pangatlo , malakas na hook . Pero dati hindi ko alam ito . I-search mo lang ang premium editing "
          "tips sa YouTube . Bigyan mo ako ng 30 seconds para ipakita . Tingnan mo ang resulta sa dashboard "
          "ko . Ang kulay ng brand ko ay simple . Ang sales ng shop ko tumaas talaga . Kaya i-follow mo ako "
          "para sa mas maraming tips .").split()
COLOURS = ["blue", "lime", "magenta", "cyan"]
STYLE = "premium_editorial"


def cfg(**editorial_cfg):
    c = load_cfg()
    c["editorial"] = {"name": "", "handle": "", "brand": "", **editorial_cfg}
    return c


@pytest.fixture
def shots(tmp_path):
    """The creator's own screenshots: plain coloured pictures."""
    return [synthetic.make_image(tmp_path / f"shot{i}.png", color=c, size="900x600") for i, c in enumerate(COLOURS)]


def editorial_project(shots=(), words=None, caption_style="editorial_card"):
    p = make_project(words or make_words(SCRIPT), tracking=face_tracking(), caption_style=caption_style)
    for i, path in enumerate(shots):
        p["media"].append(media_from_file(path, f"shot{i}"))
    return p


def run(p, c=None, **kw):
    return director.generate(p, c or cfg(), "", STYLE, use_ai=kw.pop("use_ai", False), **kw)


def graphics_of(project):
    return sorted(director.graphic_clips_of(project), key=lambda c: c["start"])


def track(project, tid):
    return next((t for t in project["tracks"] if t["id"] == tid), {"clips": []})


def word_starts(project):
    return [w["start"] for w in director.timeline_words(project)]


# ---------------------------------------------------------------- scenes and beats

def test_scenes_are_two_to_four_seconds_and_cover_the_video(shots):
    r = run(editorial_project(shots))
    rows = r["scenes"]
    assert rows[0]["start"] == 0 and len(rows) >= 8
    for a, b in zip(rows, rows[1:]):
        assert a["end"] == b["start"]
    for row in rows[:-1]:
        span = row["end"] - row["start"]
        # a spoken list ("una ..., pangalawa ..., pangatlo ...") stays one scene for its checklist
        assert 1.6 <= span <= 4.8 or (row["beat"] == "checklist" and span <= 8.0), row
    assert r["project"]["meta"]["editorial"]["scenes"] == rows


def test_each_scene_gets_one_beat_that_suits_its_words_and_beats_vary(shots):
    rows = run(editorial_project(shots), cfg(name="Juan Cruz", handle="@juan"))["scenes"]
    beat = {r["text"].split()[0].strip(","): r["beat"] for r in rows}
    assert rows[0]["beat"] in ("headline", "kinetic")                         # the hook
    assert beat["Una"] == "checklist"                                          # a spoken list
    assert beat["I-search"] == "search"
    assert beat["Bigyan"] == "countdown"                                       # "30 seconds"
    assert beat["Tingnan"] in ("screenshot", "collage", "montage", "mosaic", "phone", "pip")  # "the results on my dashboard"
    assert beat["Kaya"] == "profile"                                           # "i-follow mo ako"
    kinds = [editorial.BEATS[r["beat"]][1] for r in rows]
    for a, b, ka, kb in zip(rows, rows[1:], kinds, kinds[1:]):
        assert a["beat"] != b["beat"]                                          # never twice in a row
        assert not (ka == kb == "cover")                                       # big pictures spaced out
    assert sum(k == "cover" for k in kinds) <= round(len(rows) * editorial.COVER_SHARE + 0.6)


def test_every_element_starts_on_its_spoken_word_and_its_parts_follow_the_words(shots):
    r = run(editorial_project(shots), cfg(name="Juan Cruz"))
    p = r["project"]
    starts = word_starts(p)
    fps = p["settings"]["fps"]
    for c in graphics_of(p):
        assert any(abs(c["start"] - director.snap(s, fps)) < 1e-3 for s in starts) or c["start"] == 0, c
        cues = c["params"].get("cues") or []
        assert cues == sorted(cues) and all(x >= 0 and x < c["duration"] for x in cues), c
    checklist = next(c for c in graphics_of(p) if c["template"] == "editorial-checklist")
    assert checklist["params"]["items"] == ["malinaw na audio", "magandang ilaw", "malakas na hook"]
    words = director.timeline_words(p)
    said = [next(w["start"] for w in words if w["text"].lower().startswith(item.split()[0]))
            for item in checklist["params"]["items"]]
    # each item ticks on the frame its first word is said
    assert checklist["params"]["cues"] == pytest.approx([s - checklist["start"] for s in said], abs=0.02)
    search = next(c for c in graphics_of(p) if c["template"] == "search-bar")
    assert search["params"]["text"] == "premium editing tips sa YouTube"
    assert next(c for c in graphics_of(p) if c["template"] == "countdown-timer")["params"]["number"] == 30
    headline = graphics_of(p)[0]
    assert "*" in headline["params"]["text"]                                   # the keyword is highlighted


def test_the_look_effects_go_with_the_scenes(shots):
    p = run(editorial_project(shots))["project"]
    covers = [c for c in graphics_of(p) if graphics.template_meta(c["template"]).get("covers")]
    assert covers
    dims, vigs = track(p, "pe-look")["clips"], track(p, "pe-vignette")["clips"]
    for c in covers:                                    # the talking head is dimmed under the pictures
        assert any(abs(d["start"] - c["start"]) < 1e-3 and abs(d["duration"] - c["duration"]) < 1e-3 for d in dims)
        assert any(abs(v["start"] - c["start"]) < 1e-3 for v in vigs)
    bw = track(p, "pe-transitions")["clips"]
    pero = next(w for w in director.timeline_words(p) if w["text"] == "Pero")
    assert len(bw) == 1 and bw[0]["effect"] == "bw" and bw[0]["start"] < pero["start"] < bw[0]["start"] + 0.7
    zooms = track(p, "pe-camera")["clips"]
    # the scenes' camera moves are smooth; the rhythm keeper may add a punch-in between them
    assert zooms and all(z["smooth"] or "rhythm" in z.get("label", "") for z in zooms)
    assert validate_project(p) == []


def test_only_the_creators_own_files_are_used(shots, tmp_path):
    p = editorial_project(shots)
    stock = synthetic.make_image(tmp_path / "stock.png", color="yellow", size="900x600")
    p["media"].append(media_from_file(stock, "stock1"))
    overlay = next(t for t in p["tracks"] if t["kind"] == "overlay")
    overlay["clips"].append({"id": "b1", "type": "image", "media": "stock1", "start": 30.0, "duration": 1.0,
                             "broll": {"source": "pexels", "credit": "someone"}})
    r = run(p)
    used = set()
    for c in graphics_of(r["project"]):
        used |= set(c["params"].get("images") or []) | ({c["params"]["image"]} if c["params"].get("image") else set())
    for t in r["project"]["tracks"]:
        if str(t["id"]).startswith("pe-"):
            used |= {c["media"] for c in t["clips"] if c.get("media")}
    assert used and used <= {f"shot{i}" for i in range(len(shots))}
    assert len(r["project"]["media"]) == len(p["media"])                      # nothing added or made up


def test_without_pictures_there_are_no_picture_beats():
    r = run(editorial_project())
    assert all(editorial.BEATS[x["beat"]][1] not in ("cover", "pip") for x in r["scenes"])
    assert not track(r["project"], "pe-pip")["clips"]
    assert any("No screenshots" in n for n in r["notes"])


def test_no_profile_card_without_the_creators_own_name(shots):
    assert all(c["template"] != "profile-card" for c in graphics_of(run(editorial_project(shots))["project"]))
    made = run(editorial_project(shots), cfg(name="Juan Cruz", handle="@juan"))["project"]
    card = next(c for c in graphics_of(made) if c["template"] == "profile-card")
    assert card["params"]["text"] == "Juan Cruz" and card["params"]["text2"] == "@juan"


def test_pip_floats_one_of_the_creators_clips(tmp_path):
    clip = synthetic.make_color_video(tmp_path / "broll.mp4")
    words = make_words("Ito ang sikreto ng magandang negosyo . Tingnan mo ang resulta sa app ko ngayon . "
                       "Salamat sa panonood ninyo lahat .".split())
    p = editorial_project(words=words)
    p["media"].append(media_from_file(clip, "mine"))
    r = run(p)
    assert [x["beat"] for x in r["scenes"]][:2] == ["headline", "pip"]
    pip, = track(r["project"], "pe-pip")["clips"]
    scene = r["scenes"][1]
    assert pip["media"] == "mine" and "volume" not in pip and pip["radius"] > 0 and pip["shadow"] > 0
    assert pip["enter"] == "slide_left" and pip["border"]["width"] > 0
    tingnan = next(w for w in director.timeline_words(r["project"]) if w["text"] == "Tingnan")
    assert abs(pip["start"] - tingnan["start"]) < 0.05 and pip["start"] + pip["duration"] <= scene["end"] + 1e-3
    assert validate_project(r["project"]) == []


def test_a_palette_comes_from_the_creators_picture(tmp_path):
    logo = tmp_path / "my_logo.png"
    img = Image.new("RGB", (300, 100), "#1f2a44")
    img.paste(Image.new("RGB", (150, 100), "#c8553d"), (150, 0))
    img.save(logo)
    words = make_words("Ito ang sikreto ng magandang brand . Ang kulay ng logo ko ay simple lang talaga .".split())
    p = editorial_project(words=words)
    p["media"].append(media_from_file(logo, "logo"))
    r = run(p)
    card = next((c for c in graphics_of(r["project"]) if c["template"] == "palette-card"), None)
    assert card is not None, r["scenes"]
    assert set(card["params"]["items"]) == {"#1f2a44", "#c8553d"}


def test_uploaded_files_the_edit_did_not_use_become_media(shots):
    p = editorial_project()
    r = run(p, files=[str(s) for s in shots])
    ids = {m["id"] for m in r["project"]["media"] if m["kind"] == "image"}
    assert len(ids) == 4 and all(i.startswith("pem") for i in ids)
    assert any(editorial.BEATS[x["beat"]][1] == "cover" for x in r["scenes"])
    again = run(r["project"], files=[str(s) for s in shots])
    assert len(again["project"]["media"]) == len(r["project"]["media"])         # not added twice


# ---------------------------------------------------------------- the AI's choices

def ai_answer(rows, override=None):
    """An AI answer for these scenes (the beats only cues set are never on the AI's menu)."""
    override = override or {}
    return {"summary": "ok", "scenes": [{"scene": r["index"],
                                         "beat": "camera" if r["beat"] in editorial.CUE_ONLY else r["beat"],
                                         **override.get(r["index"], {})} for r in rows]}


def test_ai_choices_are_used_when_they_check_out(shots, monkeypatch):
    rows = run(editorial_project(shots))["scenes"]
    wanted = [dict(r) for r in rows]
    wanted[0]["beat"] = "kinetic"
    ask, calls = fake_llm([ai_answer(wanted, {0: {"words": "sikreto ng premium", "keyword": "premium"}})])
    monkeypatch.setattr(editorial, "ask_json", ask)
    r = run(editorial_project(shots), use_ai=True, provider="groq", model="m")
    assert len(calls) == 1 and not r["fallback"]
    assert r["scenes"][0]["beat"] == "kinetic"
    first = graphics_of(r["project"])[0]
    assert first["template"] == "kinetic-words" and "*premium*" in first["params"]["text"]
    assert "SCENES:" in calls[0]["prompt"] and "shot0" in calls[0]["prompt"]


def test_bad_ai_choices_are_retried_then_the_good_scenes_are_kept(shots, monkeypatch):
    """One bad scene no longer throws the whole AI plan away (the real Windows run used none of
    it): the retry lists the problems; then every scene that checks out is used, a scene whose
    choice is broken is planned by the rules, and words that were never said are dropped."""
    rows = run(editorial_project(shots))["scenes"]
    free = next(r["index"] for r in rows if r["index"] and r["beat"] not in editorial.CUE_BEAT.values())
    bad = ai_answer(rows, {0: {"words": "this was never said"}, free: {"beat": "collage", "images": ["stock99"]}})
    ask, calls = fake_llm([bad, bad])
    monkeypatch.setattr(editorial, "ask_json", ask)
    r = run(editorial_project(shots), use_ai=True, provider="groq", model="m")
    assert len(calls) == 2 and not r["fallback"]
    assert "never said" in calls[1]["prompt"] and "stock99" in calls[1]["prompt"]
    note = next(n for n in r["notes"] if "AI scene plan was used for" in n)
    assert "stock99" in note or "never said" in note                          # why some were not
    assert r["scenes"][free]["beat"] != "collage" or "stock99" not in json.dumps(r["project"])
    assert "this was never said" not in json.dumps(r["project"])


def test_an_ai_answer_with_nothing_usable_falls_back_with_its_reason(shots, monkeypatch):
    ask, calls = fake_llm(['{"scenes": "none"}', "not json"])
    monkeypatch.setattr(editorial, "ask_json", ask)
    r = run(editorial_project(shots), use_ai=True, provider="groq", model="m")
    assert len(calls) == 2 and r["fallback"] and "not JSON" in r["reason"]


def test_an_ai_error_falls_back_to_the_rules(shots, monkeypatch):
    ask, calls = fake_llm([LLMError("no key")])
    monkeypatch.setattr(editorial, "ask_json", ask)
    r = run(editorial_project(shots), use_ai=True, provider="groq", model="m")
    assert r["fallback"] and "no key" in r["reason"] and r["count"] > 0


def test_the_ai_cannot_put_a_beat_where_the_rules_forbid_it(shots, monkeypatch):
    rows = run(editorial_project(shots))["scenes"]
    forced = ai_answer([{**r, "beat": "collage"} for r in rows])          # every scene a collage
    ask, _calls = fake_llm([forced])
    monkeypatch.setattr(editorial, "ask_json", ask)
    r = run(editorial_project(shots), use_ai=True, provider="groq", model="m")
    beats = [x["beat"] for x in r["scenes"]]
    assert all(a != b for a, b in zip(beats, beats[1:]))


def test_ai_choices_are_cached(shots, monkeypatch, tmp_path):
    from autoedit.cache import Cache
    rows = run(editorial_project(shots))["scenes"]
    ask, calls = fake_llm([ai_answer(rows)])
    monkeypatch.setattr(editorial, "ask_json", ask)
    cache = Cache(tmp_path / "cache")
    first = run(editorial_project(shots), use_ai=True, provider="groq", model="m", cache=cache)
    second = run(editorial_project(shots), use_ai=True, provider="groq", model="m", cache=cache)
    assert len(calls) == 1 and second["cached"] and second["cost"] == 0.0
    assert first["scenes"] == second["scenes"]


# ---------------------------------------------------------------- editing the result

def test_running_again_replaces_its_own_work_and_keeps_locked_clips(shots):
    first = run(editorial_project(shots))["project"]
    g = graphics_of(first)[2]
    g["locked"] = True
    again = run(first)["project"]
    assert any(c["id"] == g["id"] and c.get("locked") for c in graphics_of(again))
    assert len(graphics_of(again)) <= len(graphics_of(first)) + 1
    ids = [c["id"] for t in again["tracks"] for c in t["clips"]]
    assert len(ids) == len(set(ids)) and validate_project(again) == []


def test_regenerate_one_scene_changes_only_that_scene(shots):
    p = run(editorial_project(shots))["project"]
    rows = p["meta"]["editorial"]["scenes"]
    k = 3
    r = editorial.regenerate_scene(p, k, cfg())
    after = r["project"]["meta"]["editorial"]["scenes"]
    assert r["before"] == rows[k]["beat"] and r["beat"] != rows[k]["beat"]
    assert after[k]["beat"] == r["beat"]
    assert [x["beat"] for i, x in enumerate(after) if i != k] == [x["beat"] for i, x in enumerate(rows) if i != k]
    s, e = rows[k]["start"], rows[k]["end"]

    def outside(project):
        return sorted((c["id"], c.get("template") or c.get("type"), c["start"]) for t in project["tracks"]
                      for c in t["clips"] if not (s - 1e-6 <= c["start"] < e - 1e-6))
    assert outside(r["project"]) == outside(p)
    assert r["beat"] != after[k - 1]["beat"] and r["beat"] != after[k + 1]["beat"]
    assert validate_project(r["project"]) == []


def test_a_locked_scene_is_not_planned_again(shots):
    p = run(editorial_project(shots))["project"]
    graphics_of(p)[1]["locked"] = True
    k = graphics_of(p)[1]["director"]["scene"]
    with pytest.raises(director.DirectorError, match="locked"):
        editorial.regenerate_scene(p, k, cfg())


def test_regenerating_a_graphic_or_a_storyboard_scene_uses_the_scene_planner(shots):
    p = run(editorial_project(shots))["project"]
    g = graphics_of(p)[1]
    r = director.regenerate_item(p, g["id"], cfg())
    assert r["clip"]["template"] != g["template"] and r["clip"]["director"]["style"] == STYLE
    sb = storyboard.scenes(p)
    out = storyboard.regenerate(p, sb[1]["id"], cfg())
    assert out["changed"] and any("->" in n for n in out["notes"])
    assert validate_project(out["project"]) == []


def test_without_a_plan_a_scene_cannot_be_planned_again(shots):
    with pytest.raises(director.DirectorError, match="no editorial scene plan"):
        editorial.regenerate_scene(editorial_project(shots), 0, cfg())


# ---------------------------------------------------------------- the preset and the style

def test_the_preset_and_the_style():
    c = load_cfg()
    c["presets_folder"] = ""
    preset = presets.get("premium_editorial_viral", c)
    assert preset["name"] == "PREMIUM EDITORIAL VIRAL" and preset["tl"] and preset["about_tl"]
    assert preset["graphics"] == STYLE and preset["captions"]["style"] == "editorial_card"
    assert preset["broll"] == {"use_stock": False, "ai_clips": False}
    pc = presets.cfg_for(preset, c)
    assert pc["style"] == "editorial_card" and pc["pacing"]["zoom"] and not pc["broll"]["use_stock"]
    assert director.resolve_style(c, "gawin mong parang magazine, editorial") == STYLE
    assert director.resolve_style(c, "make it look premium and elegant") == "luxury"     # unchanged
    assert any(p["id"] == "premium_editorial_viral" for p in presets.summary(c))


def test_the_result_is_valid_and_passes_the_export_check(shots, tmp_path):
    p = run(editorial_project(shots), cfg(name="Juan Cruz"))["project"]
    assert validate_project(p) == []
    issues = [i for i in check_project(p, tmp_path, load_cfg()) if i.get("kind") != "missing_media"]
    assert not [i for i in issues if "face" in i["message"] or "caption" in i["message"]], issues


# ---------------------------------------------------------------- a real render

def saturation(img):
    return float((img.max(axis=2) - img.min(axis=2)).mean())


@needs_chromium
def test_a_full_editorial_edit_renders_every_layer(tmp_path, shots):
    """A synthetic talking video (FFmpeg test pattern + tone) with the creator's four screenshots:
    the whole edit is planned, rendered to MP4 and checked frame by frame."""
    words = make_words("Ito ang sikreto ng premium na video . Una , malinaw na audio , pangalawa , magandang "
                       "ilaw , pangatlo , malakas na hook . Pero dati hindi ko alam ito . Tingnan mo ang resulta "
                       "sa dashboard ko .".split())
    seconds = round(words[-1]["end"] + 0.6, 2)
    video = synthetic.make_video(tmp_path / "talk.mp4", duration=seconds)
    p = editorial_project(shots, words=words)
    p["media"][0] = {**media_from_file(video, "m1")}
    p["tracks"][0]["clips"][0].update({"duration": p["media"][0]["duration"], "out": p["media"][0]["duration"]})
    r = run(p)
    p = r["project"]
    assert validate_project(p) == []
    rows = {x["beat"]: x for x in r["scenes"]}
    assert {"checklist"} <= set(rows) and any(editorial.BEATS[b][1] == "cover" for b in rows)

    def frame(project, t, name):
        out = tmp_path / f"{name}.png"
        render_frame(project, t, out, base_dir=tmp_path, work_dir=tmp_path / "work")
        return np.asarray(Image.open(out).convert("RGB")).astype(int)

    def without(project, tid):
        q = json.loads(json.dumps(project))
        q["tracks"] = [t for t in q["tracks"] if t["id"] != tid]
        return q

    # a big picture beat: the creator's screenshots are on screen and the speaker is dimmed under them
    cover = next(c for c in graphics_of(p) if graphics.template_meta(c["template"]).get("covers"))
    t = cover["start"] + cover["duration"] * 0.7
    on, plain = frame(p, t, "cover"), frame(without(p, "pe-look"), t, "cover-nodim")
    user = np.zeros(on.shape[:2], bool)
    for rgb in ((0, 0, 255), (0, 255, 0), (255, 0, 255), (0, 255, 255)):
        user |= (np.abs(on - rgb) < 60).all(axis=2)
    assert user.sum() > 3000, "the creator's screenshots are not on screen"
    edge = (slice(1500, 1700), slice(0, 120))                 # the talking head at the left edge
    assert on[edge].mean() < plain[edge].mean() * 0.8, "the background is not dimmed"

    # the B&W transition into "Pero": colour drains from the picture, then comes back
    bw = track(p, "pe-transitions")["clips"][0]
    mid = bw["start"] + bw["duration"] / 2
    grey, colour = frame(p, mid, "bw"), frame(without(p, "pe-transitions"), mid, "bw-off")
    assert saturation(grey[1450:1700]) < saturation(colour[1450:1700]) * 0.6

    # the checklist ticks with the words; the cream caption card is under the words
    check = next(c for c in graphics_of(p) if c["template"] == "editorial-checklist")
    bare = json.loads(json.dumps(p))
    bare["tracks"] = [t for t in bare["tracks"] if t["kind"] != "graphics"]

    def ticks(t, name):
        """Terracotta pixels the graphics add (the test pattern has reds of its own)."""
        def accent(im):
            return (np.abs(im - (0xC8, 0x55, 0x3D)) < 40).all(axis=2)
        return int((accent(frame(p, t, name)) & ~accent(frame(bare, t, name + "-bare"))).sum())
    early = ticks(check["start"] + 0.25, "check-early")
    late_t = check["start"] + check["params"]["cues"][-1] + 0.5
    assert ticks(late_t, "check-late") > early + 400
    late = frame(p, late_t, "check-late")
    cream = (np.abs(late - (0xF4, 0xEF, 0xE6)) < 10).all(axis=2)
    assert cream.sum() > 20000

    # and the whole thing renders to a playable MP4 of the right length
    out = render_project(p, tmp_path / "edit.mp4", base_dir=tmp_path, work_dir=tmp_path / "w2",
                         export={"crf": 30, "encoder_speed": "ultrafast", "audio_bitrate": "96k"})
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                          capture_output=True, text=True, check=True)
    assert abs(float(info.stdout) - p["tracks"][0]["clips"][0]["duration"]) < 0.2
