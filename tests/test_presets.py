"""Presets: plain JSON files (built-in and your own), what they change in the settings and the
plan, and the music and sounds they add."""

import json
import subprocess

import pytest

from autoedit import presets
from autoedit.config import load_config
from autoedit.project import validate_project
from tests.director_helpers import make_project

SEVEN = {"viral_tiktok", "cinematic_storytelling", "premium_ugc_ad", "podcast_clips",
         "faceless_automation", "calm_documentary", "meme"}


@pytest.fixture(autouse=True)
def caches(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEDIT_SFX_CACHE", str(tmp_path / "sfx"))


def cfg(**extra):
    c = load_config(None)
    c["presets_folder"] = ""
    c.update(extra)
    return c


def tone(path, seconds=2.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=220:r=48000:d={seconds}",
                    str(path)], check=True)
    return path


def test_the_seven_presets_are_valid():
    found = presets.all_presets(cfg())
    assert set(found) == SEVEN
    for p in found.values():
        assert p["builtin"] and p["about"] and p["about_tl"]
    assert found["faceless_automation"]["format"] == "voiceover_broll"
    assert found["faceless_automation"]["broll"] == {"use_stock": False, "ai_clips": False}


def test_your_own_preset_is_added_or_replaces_a_built_in_one(tmp_path):
    mine = tmp_path / "presets"
    mine.mkdir()
    base = presets.get("meme", cfg())
    own = {k: v for k, v in base.items() if k != "builtin"}
    (mine / "meme.json").write_text(json.dumps({**own, "grade": "warm"}), encoding="utf-8")
    (mine / "my_shop.json").write_text(json.dumps({**own, "id": "my_shop", "name": "My shop"}),
                                       encoding="utf-8")
    found = presets.all_presets(cfg(presets_folder=str(mine)))
    assert found["meme"]["grade"] == "warm" and not found["meme"]["builtin"]
    assert "my_shop" in found and len(found) == 8
    assert presets.get("My Shop", cfg(presets_folder=str(mine)))["id"] == "my_shop"


@pytest.mark.parametrize("change, problem", [
    ({"grade": "sepia"}, "unknown grade"),
    ({"graphics": "disco"}, "unknown style"),
    ({"format": "dance"}, "unknown format"),
    ({"pacing": "turbo"}, "unknown pacing"),
    ({"captions": {"style": "comic_sans"}}, "unknown caption style"),
    ({"density": 99}, "density"),
])
def test_a_bad_preset_is_refused_with_the_reason(tmp_path, change, problem):
    mine = tmp_path / "presets"
    mine.mkdir()
    own = {k: v for k, v in presets.get("meme", cfg()).items() if k != "builtin"}
    (mine / "meme.json").write_text(json.dumps({**own, **change}), encoding="utf-8")
    with pytest.raises(presets.PresetError, match=problem):
        presets.all_presets(cfg(presets_folder=str(mine)))


def test_unknown_preset_lists_the_choices():
    with pytest.raises(presets.PresetError, match="viral_tiktok"):
        presets.get("hollywood", cfg())


def test_settings_and_plan_follow_the_preset():
    look = presets.get("cinematic_storytelling", cfg())
    c = presets.cfg_for(look, cfg())
    assert c["preset"] == "relaxed" and c["pacing"]["silence_threshold"] == 0.6
    assert c["pacing"]["zoom"] is False and c["style"] == "minimal" and c["grade"] == "orange_teal"
    assert c["graphics"]["max_per_10s"] == 1
    faceless = presets.cfg_for(presets.get("faceless_automation", cfg()), cfg())
    assert faceless["broll"]["use_stock"] is False
    plan = {"style": "classic", "grade": "warm", "captions": {"size_scale": 1.0, "position": None},
            "ai_clips": [{"at": 1}]}
    pinned = presets.pin_plan(presets.get("viral_tiktok", cfg()), plan)
    assert pinned["style"] == "pop_word" and pinned["grade"] == "high_contrast"
    assert pinned["captions"]["size_scale"] == 1.15 and pinned["ai_clips"] == [{"at": 1}]
    assert presets.pin_plan(presets.get("faceless_automation", cfg()), plan)["ai_clips"] == []
    assert plan["style"] == "classic"                      # a copy
    assert "Hook" in presets.instruction_for(presets.get("viral_tiktok", cfg()), "Mabilis")


def test_music_is_picked_by_mood_and_laid_under_the_whole_video(tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    tone(folder / "a_calm_piano.wav", 3)
    tone(folder / "b_upbeat_summer.wav", 3)
    c = cfg(music={"folder": str(folder)})
    look = presets.get("viral_tiktok", c)
    assert presets.music_file(look, c).name == "b_upbeat_summer.wav"
    p = make_project()                                     # about 9 s: the 3 s song repeats
    note = presets.add_music(p, look, c)
    assert "b_upbeat_summer.wav" in note
    music = [cl for t in p["tracks"] if t.get("role") == "music" for cl in t["clips"]]
    assert len(music) >= 3 and all(cl["volume"] == 0.12 for cl in music)
    assert music[-1]["fade_out"] > 0
    assert abs(music[-1]["start"] + music[-1]["duration"] - max(
        cl["start"] + cl["duration"] for cl in p["tracks"][0]["clips"])) < 0.01
    assert validate_project(p) == []


def test_no_music_folder_is_a_note_not_an_error(tmp_path):
    c = cfg(music={"folder": str(tmp_path / "none")})
    p = make_project()
    note = presets.add_music(p, presets.get("viral_tiktok", c), c)
    assert "No music added" in note
    assert presets.add_music(p, presets.get("meme", c), c) is None       # meme has no music


def test_emphasis_sounds_are_spaced_out():
    p = make_project()
    gfx = {"id": "graphics", "kind": "graphics", "name": "Graphics", "clips": []}
    p["tracks"].insert(2, gfx)
    for n, (at, tpl, kind) in enumerate([(0.5, "stamp", None), (1.0, "pop-heavy", "flash"),
                                         (2.5, "thin-spaced", "whip"), (4.0, "thin-spaced", None),
                                         (5.0, "emoji-pop", None)]):
        clip = {"id": f"g{n}", "type": "graphic", "template": tpl, "start": at, "duration": 0.45,
                "params": {"text": "x"}, "x": 0.5, "y": 0.3}
        if kind:
            clip["attach"] = {"kind": kind}
        gfx["clips"].append(clip)
    n = presets.add_emphasis_sounds(p, cfg())
    sounds = sorted(c["start"] for t in p["tracks"] if t.get("role") == "sfx" for c in t["clips"])
    assert n == 3 and sounds == [0.5, 2.5, 5.0]              # 1.0 is too close; 4.0 does not pop
    assert validate_project(p) == []
