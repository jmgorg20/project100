"""The storyboard: scenes worked out from the timeline, and scene edits that change the clips."""

import copy

import pytest

from autoedit import director, storyboard
from autoedit.project import validate_project
from tests.director_helpers import cfg, make_project, make_words

SCRIPT = ("Alam niyo ba kung paano ako nakaipon? Simple lang. Una , nag-budget ako ng 500 piso "
          "kada linggo . Pangalawa , iniwasan ko ang milk tea . Tapos nag-invest ako sa index fund . "
          "Ang resulta , 50,000 sa isang taon ! I-follow niyo ako para sa part two !").split()


def project():
    return make_project(make_words(SCRIPT))


def test_scenes_follow_the_sentences_and_cover_the_video():
    p = project()
    sb = storyboard.scenes(p)
    assert len(sb) >= 4
    assert sb[0]["start"] == 0 and sb[0]["purpose"] == "hook" and sb[0]["transition"] == "start"
    for a, b in zip(sb, sb[1:]):
        assert a["end"] == b["start"]
    assert abs(sb[-1]["end"] - storyboard.timeline_end(p)) < 1e-6
    assert all(s["duration"] <= storyboard.MAX_SCENE + 3 for s in sb)
    assert sb[-1]["purpose"] == "cta"                                  # "I-follow niyo ako"
    assert any(s["purpose"] == "proof" for s in sb)                     # 500 piso, 50,000
    words = " ".join(s["text"] for s in sb).split()
    caps = [w["text"] for t in p["tracks"] if t["kind"] == "caption" for c in t["clips"] for w in c["words"]]
    assert words == caps                                                # every caption, once
    assert all(s["sources"] == ["talk.mp4"] for s in sb)


def test_scene_fields_show_graphics_music_sounds_and_colour():
    p = project()
    sb = storyboard.scenes(p)
    s2 = sb[1]
    p["tracks"].insert(2, {"id": "graphics", "kind": "graphics", "name": "Graphics", "clips": [
        {"id": "g1", "type": "graphic", "template": "stamp", "start": s2["start"] + 0.1, "duration": 1.0,
         "params": {"text": "SIMPLE"}, "x": 0.5, "y": 0.3, "attach": {"kind": "whip"}}]})
    p["media"].append({"id": "mu", "kind": "audio", "path": "C:/Music/upbeat.mp3", "duration": 60})
    p["media"].append({"id": "pop", "kind": "audio", "path": "pop.wav", "duration": 0.3})
    music = next(t for t in p["tracks"] if t.get("role") == "music")
    music["clips"] = [{"id": "m1", "type": "audio", "media": "mu", "start": 0, "duration": storyboard.timeline_end(p),
                       "in": 0, "out": storyboard.timeline_end(p), "volume": 0.1}]
    sfx = next(t for t in p["tracks"] if t.get("role") == "sfx")
    sfx["clips"] = [{"id": "x1", "type": "audio", "media": "pop", "start": s2["start"] + 0.1, "duration": 0.3,
                     "in": 0, "out": 0.3}]
    effects = next(t for t in p["tracks"] if t["kind"] == "effect")
    effects["clips"].append({"id": "gr", "type": "grade", "start": 0, "duration": 4, "grade": "warm"})
    assert validate_project(p) == []
    s2 = storyboard.scenes(p)[1]
    assert s2["graphics"] == [{"id": "g1", "template": "stamp", "text": "SIMPLE"}]
    assert s2["transition"] == "whip" and s2["sfx"] == 1 and s2["music"] == ["upbeat.mp3"]
    assert storyboard.scenes(p)[0]["mood"] == "warm"
    assert "m1" not in s2["clips"]                                      # music spans every scene


def test_lock_a_scene_and_the_editors_respect_it():
    p = project()
    s = storyboard.scenes(p)[1]
    locked = storyboard.set_locked(p, s["id"])
    assert storyboard.scenes(locked)[1]["locked"] and not storyboard.scenes(locked)[0]["locked"]
    assert validate_project(locked) == []
    with pytest.raises(storyboard.StoryboardError, match="locked"):
        storyboard.set_text(locked, s["id"], "bago")
    with pytest.raises(storyboard.StoryboardError, match="locked"):
        storyboard.regenerate(locked, s["id"], cfg())
    unlocked = storyboard.set_locked(locked, "2", False)                # by number too
    assert not storyboard.scenes(unlocked)[1]["locked"]
    assert p == project()                                               # copies, not in place


def test_frozen_scenes_are_kept_and_cleaned():
    p = project()
    p["meta"] = {"storyboard": {"starts": [0, 3.0, 999]}}
    sb = storyboard.scenes(p)
    assert [s["start"] for s in sb] == [0.0, 3.0] and sb[-1]["end"] == storyboard.timeline_end(p)


def test_edit_a_scenes_text():
    p = project()
    s = storyboard.scenes(p)[2]
    out = storyboard.set_text(p, s["id"], "Una, mag-budget ng *500* kada linggo")
    s_new = next(x for x in storyboard.scenes(out) if x["start"] == s["start"])
    assert s_new["text"] == "Una, mag-budget ng *500* kada linggo"
    assert validate_project(out) == []
    assert [x["start"] for x in storyboard.scenes(out)] == [x["start"] for x in storyboard.scenes(p)]
    assert out["meta"]["storyboard"]["starts"][0] == 0                  # scenes are kept as they were
    short = storyboard.set_text(p, s["id"], "Budget")
    assert next(x for x in storyboard.scenes(short) if x["start"] == s["start"])["text"] == "Budget"
    assert validate_project(short) == []
    with pytest.raises(storyboard.StoryboardError, match="Type the words"):
        storyboard.set_text(p, s["id"], "  ")


def test_spread_words_over_captions():
    assert storyboard._spread([5, 5], 4) == [2, 2]
    assert storyboard._spread([2, 6], 4) == [1, 3]
    assert storyboard._spread([3, 3, 3], 2) == [1, 1, 0]
    assert sum(storyboard._spread([1, 7, 2], 13)) == 13


def test_regenerate_one_scene_changes_only_its_graphics():
    p = project()
    made = director.generate(p, cfg(), "like a professional promoter", "promoter", use_ai=False)
    p = made["project"]
    sb = storyboard.scenes(p)
    target = next(s for s in sb if s["graphics"])
    before = {c["id"]: c["template"] for c in director.graphic_clips_of(p)}
    out = storyboard.regenerate(p, target["id"], cfg())
    after = {c["id"]: c["template"] for c in director.graphic_clips_of(out["project"])}
    assert out["changed"]
    for gid, tpl in before.items():
        if gid in {g["id"] for g in target["graphics"]}:
            assert after[gid] != tpl
        else:
            assert after[gid] == tpl                                   # other scenes untouched
    assert validate_project(out["project"]) == []


def test_regenerate_a_scene_without_graphics_adds_some_there_only():
    p = project()
    sb = storyboard.scenes(p)
    target = next(s for s in sb if s["purpose"] == "proof")
    out = storyboard.regenerate(copy.deepcopy(p), target["id"], cfg())
    new = director.graphic_clips_of(out["project"])
    assert new and out["changed"] == [c["id"] for c in new]
    assert all(target["start"] - 0.05 <= c["start"] < target["end"] for c in new)
    assert validate_project(out["project"]) == []


def test_unknown_scene():
    with pytest.raises(storyboard.StoryboardError, match="no scene"):
        storyboard.set_locked(project(), "s99")


def test_storyboard_cli(tmp_path, capsys):
    import json
    import editor
    from autoedit.project import load_project, save_project
    path = tmp_path / "p.project.json"
    save_project(project(), path)
    assert editor.main(["--json", "storyboard", str(path)]) in (0, None)
    scenes = json.loads(capsys.readouterr().out.splitlines()[-1])["scenes"]
    assert scenes[0]["purpose"] == "hook"
    editor.main(["--json", "storyboard-edit", str(path), "--scene", "2", "--lock"])
    out = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert out["scenes"][1]["locked"] and storyboard.scenes(load_project(path))[1]["locked"]
    editor.main(["--json", "storyboard-edit", str(path), "--scene", "s1", "--text", "Alam niyo ba?"])
    assert storyboard.scenes(load_project(path))[0]["text"] == "Alam niyo ba?"
    code = editor.main(["--json", "storyboard-edit", str(path), "--scene", "2", "--text", "x"])
    assert code not in (0, None) and "locked" in capsys.readouterr().out
