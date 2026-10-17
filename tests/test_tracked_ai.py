"""The AI plan can attach effects to tracked points; the edit places them, stores the track and
says honestly what it could and could not do (synthetic tracks and a stand-in MediaPipe)."""

import json
import sys
import types

import pytest

from autoedit import ai_edit, tracking
from autoedit.ai_plan import preset_plan, upgrade_plan, validate_plan
from autoedit.config import load_config
from autoedit.generation import Paths
from autoedit.project import load_project, validate_project
from autoedit.tracking import Point, Track
from autoedit.words import load_transcript
from tests import synthetic
from tests.test_tracking import FakeLandmarker, make_fake_mediapipe  # noqa: F401  (stand-in MediaPipe)

NS = types.SimpleNamespace


@pytest.fixture
def talk(tmp_path, monkeypatch):
    video = synthetic.make_video(tmp_path / "talk.mp4", width=360, height=640)
    words = load_transcript(synthetic.make_transcript(tmp_path / "talk.json"))
    monkeypatch.setattr(ai_edit, "transcribe", lambda *a: words)
    cfg = load_config()
    cfg["output"].update(folder=str(tmp_path / "out"), encoder_speed="ultrafast")
    cfg["work_folder"] = str(tmp_path / "work")
    cfg["ai"]["cache_folder"] = str(tmp_path / "cache")
    cfg["overlays"]["triggers_file"] = str(tmp_path / "none.yaml")
    (tmp_path / "hand.task").write_bytes(b"x")
    (tmp_path / "face.tflite").write_bytes(b"y")
    cfg["tracking"] = {"hand_model": str(tmp_path / "hand.task"), "face_model": str(tmp_path / "face.tflite"),
                       "fps": 10}
    return video, cfg, Paths(tmp_path / "generation.json", tmp_path / "gen")


def tracked(**kw):
    return {"effect": "glow", "point": "index_tip", "hand": "right", "at": 5.5, "duration": 1.5, "intensity": 0.8,
            "color": "gold", "size": 1.0, "reason": "when you say GitHub", **kw}


def ask(monkeypatch, plan, prompts=None):
    def fake(provider, model, system, prompt, schema, **kw):
        if prompts is not None:
            prompts.append((system, prompt))
        return json.dumps(plan), {"input_tokens": 1, "output_tokens": 1}, model
    monkeypatch.setattr(ai_edit, "ask_json", fake)


def clips_of(project, kind):
    return [c for t in project["tracks"] if t["kind"] == "effect" for c in t["clips"] if c["type"] == kind]


def test_older_plans_get_an_empty_list_and_times_are_checked():
    cfg = load_config()
    plan = preset_plan(cfg)
    del plan["tracked_effects"]
    assert any("tracked_effects" in p for p in validate_plan(plan, 8.0))
    plan = upgrade_plan(plan)
    assert plan["tracked_effects"] == [] and validate_plan(plan, 8.0) == []
    plan["tracked_effects"] = [tracked(at=9.0)]
    assert any("after the end" in p for p in validate_plan(plan, 8.0))
    plan["tracked_effects"] = [tracked(point="elbow")]
    assert validate_plan(plan, 8.0)


def test_the_ai_is_told_whether_tracking_is_available(talk, monkeypatch, tmp_path):
    video, cfg, paths = talk
    prompts = []
    ask(monkeypatch, preset_plan(cfg), prompts)
    monkeypatch.setitem(sys.modules, "mediapipe", None)
    ai_edit.ai_edit_video(video, cfg, "x", render=False, gen_paths=paths)
    assert "TRACKED EFFECTS: NOT available" in prompts[0][1] and "tracked_effects" in prompts[0][0]
    make_fake_mediapipe(monkeypatch)
    ai_edit.ai_edit_video(video, cfg, "y", render=False, gen_paths=paths)
    assert "TRACKED EFFECTS: available for hands and face and body." in prompts[1][1]


def test_an_edit_with_a_tracked_effect_places_it_and_keeps_the_track(talk, monkeypatch):
    video, cfg, paths = talk
    make_fake_mediapipe(monkeypatch)
    FakeLandmarker.log.clear()
    plan = preset_plan(cfg)
    plan["tracked_effects"] = [tracked(), tracked(effect="aura", point="face", at=2.9, duration=2.0, color="cyan"),
                               tracked(effect="spark", point="palm", hand="any", at=7.0, duration=0.8)]
    ask(monkeypatch, plan)
    result = ai_edit.ai_edit_video(video, cfg, "glow sa kamay", render=False, gen_paths=paths)
    project = load_project(result["project"])
    assert validate_project(project) == []
    fx = {c["effect"]: c for c in clips_of(project, "trackfx")}
    assert set(fx) == {"glow", "aura", "spark"}
    glow = fx["glow"]
    assert glow["point"] == "index_tip" and glow["hand"] == "right" and glow["color"] == "#ffd24a"
    assert glow["intensity"] == 0.8 and fx["aura"]["color"] == "#58e0ff"
    # The effect is where the word is said, on the cut timeline (the same mapping as the captions).
    said = next(c["start"] + w["start"] for t in project["tracks"] if t["kind"] == "caption"
                for c in t["clips"] for w in c["words"] if w["text"].startswith("GitHub"))
    assert glow["start"] == pytest.approx(said, abs=0.15)
    # The track for the main video is stored with only the points that are used.
    main_media = next(t for t in project["tracks"] if t["kind"] == "video")["clips"][0]["media"]
    stored = project["tracking"][main_media]
    assert stored["fps"] == 10 and set(stored["points"]) >= {"right_index_tip", "face", "left_palm", "right_palm"}
    assert "left_wrist" not in stored["points"]
    # The detector only looked at the moments the plan needs.
    calls = [c for c in FakeLandmarker.log if c[1] != "closed" and c[0] == "hand"]
    assert 0 < len(calls) < 80
    details = " ".join(result["summary"]["details"])
    assert "Tracked glow on the index tip (right hand) at" in details and "Tracked aura on the face at" in details


def test_a_second_run_uses_the_saved_track(talk, monkeypatch):
    video, cfg, paths = talk
    make_fake_mediapipe(monkeypatch)
    plan = preset_plan(cfg)
    plan["tracked_effects"] = [tracked()]
    ask(monkeypatch, plan)
    ai_edit.ai_edit_video(video, cfg, "a", render=False, gen_paths=paths, output=video.parent / "one.mp4")
    first = len(FakeLandmarker.log)
    ai_edit.ai_edit_video(video, cfg, "a", render=False, gen_paths=paths, output=video.parent / "two.mp4")
    assert len(FakeLandmarker.log) == first               # nothing was detected again


def test_without_mediapipe_the_edit_still_finishes_and_says_why(talk, monkeypatch):
    video, cfg, paths = talk
    plan = preset_plan(cfg)
    plan["tracked_effects"] = [tracked()]
    ask(monkeypatch, plan)
    monkeypatch.setitem(sys.modules, "mediapipe", None)
    result = ai_edit.ai_edit_video(video, cfg, "glow", render=False, gen_paths=paths)
    project = load_project(result["project"])
    assert clips_of(project, "trackfx") == [] and "tracking" not in project
    details = " ".join(result["summary"]["details"])
    assert "Not done: tracked glow at 0:06" in details and "pip install mediapipe" in details


def test_a_point_that_is_hardly_found_is_reported(talk, monkeypatch):
    video, cfg, paths = talk
    make_fake_mediapipe(monkeypatch)
    plan = preset_plan(cfg)
    monkeypatch.setattr(FakeLandmarker, "lose_hands", True)     # the stand-in never finds a hand
    plan["tracked_effects"] = [tracked(at=1.1, duration=1.5)]
    ask(monkeypatch, plan)
    result = ai_edit.ai_edit_video(video, cfg, "glow", render=False, gen_paths=paths)
    assert "was found in only 0%" in " ".join(result["summary"]["details"])


def test_only_the_face_model_missing_drops_only_the_face_effects(talk, monkeypatch, tmp_path):
    video, cfg, paths = talk
    make_fake_mediapipe(monkeypatch)
    cfg["tracking"]["face_model"] = ""
    plan = preset_plan(cfg)
    plan["tracked_effects"] = [tracked(), tracked(effect="aura", point="face", at=2.9, duration=2.0)]
    ask(monkeypatch, plan)
    result = ai_edit.ai_edit_video(video, cfg, "glow", render=False, gen_paths=paths)
    project = load_project(result["project"])
    assert [c["effect"] for c in clips_of(project, "trackfx")] == ["glow"]
    assert "Not done: tracked aura at 0:03" in " ".join(result["summary"]["details"])
