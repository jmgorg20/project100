"""Cut pieces laid end to end must always touch, never "overlap" by rounding (a real run failed
with: clip 'v8' overlaps clip 'v7' (starts at 14.733s, the other ends at 14.733s))."""

import json
import random

import pytest

from autoedit import ai_edit
from autoedit.ai_plan import preset_plan
from autoedit.config import load_config
from autoedit.cuts import snap_to_frames
from autoedit.generation import Paths
from autoedit.pipeline import segment_lengths
from autoedit.project import (TIME_TOLERANCE, assign_lanes, clip_end, load_project, new_project,
                              validate_project)
from autoedit.words import load_transcript
from tests import synthetic


def project_from_segments(segments, fps):
    """The main track exactly as build_edit_project lays it out."""
    durations, total = segment_lengths(segments)
    p = new_project("t", fps=fps)
    p["media"] = [{"id": "m1", "kind": "video", "path": "talk.mp4", "name": "talk.mp4",
                   "duration": round(max(e for _, e in segments) + 1, 3), "width": 720,
                   "height": 1280, "has_audio": True}]
    main = next(t for t in p["tracks"] if t["kind"] == "video")["clips"]
    offset = 0.0
    for i, ((s, e), d) in enumerate(zip(segments, durations)):
        main.append({"id": f"v{i + 1}", "type": "video", "media": "m1", "start": round(offset, 6),
                     "duration": d, "in": round(s, 6), "out": round(e, 6), "fit": "fill"})
        offset = round(offset + d, 6)
    return p, total


def random_segments(rng, fps, count):
    """Frame-snapped pieces with gaps, like real cuts (starts and lengths in whole frames)."""
    t, out = rng.randint(0, 40) / fps, []
    for _ in range(count):
        length = rng.randint(1, 200) / fps
        out.append((t, t + length))
        t += length + rng.randint(1, 90) / fps
    return snap_to_frames(out, fps)


@pytest.mark.parametrize("fps", [24, 25, 30, 60])
def test_random_cut_lists_always_validate(fps):
    rng = random.Random(14733 + fps)
    for _ in range(1500):
        segments = random_segments(rng, fps, rng.randint(2, 40))
        p, total = project_from_segments(segments, fps)
        assert validate_project(p) == [], segments
        main = p["tracks"][0]["clips"]
        assert clip_end(main[-1]) == pytest.approx(total, abs=1e-9)
        for a, b in zip(main, main[1:]):
            assert b["start"] - clip_end(a) == pytest.approx(0, abs=1e-9)   # they touch exactly


def test_the_numbers_from_the_real_run():
    # Pieces whose lengths do not round evenly (thirds of a frame at 30 fps, seconds as
    # 4.9333333...): the old layout put v8 a microsecond before the end of v7 (14.733 s).
    seg, t = [], 0.0
    for length in [1.9, 2.1, 1.7, 2.3333333333, 1.5, 2.2666666667, 1.4, 1.5333333333]:
        seg.append((t + 0.4, t + 0.4 + length))
        t += length + 0.9
    p, total = project_from_segments(seg, 30)
    assert validate_project(p) == []
    # The OLD layout (rounding start and length separately from an unrounded running sum).
    old, offset = [], 0.0
    for s, e in seg:
        old.append({"start": round(offset, 6), "duration": round(e - s, 6)})
        offset += e - s
    drift = [b["start"] - (a["start"] + a["duration"]) for a, b in zip(old, old[1:])]
    assert any(d < 0 for d in drift)          # the old way really did produce a negative gap


def test_a_real_overlap_is_still_rejected():
    for fps in (24, 30, 60):
        p, _ = project_from_segments([(0.0, 1.0), (2.0, 3.0)], fps)
        main = p["tracks"][0]["clips"]
        for frames, rejected in ((0.01, False), (1, True), (3, True)):
            main[1]["start"] = round(main[0]["duration"] - frames / fps, 6)
            problems = validate_project(p)
            assert bool(problems) == rejected, (fps, frames, problems)
            if rejected:
                assert "overlaps clip 'v1'" in problems[0]
    assert TIME_TOLERANCE < 1 / 60 / 2 + 1e-9      # always less than half a frame


def test_touching_clips_share_a_lane():
    a = {"id": "a", "start": 0.0, "duration": 1.0}
    b = {"id": "b", "start": 0.9999995, "duration": 1.0}      # a microsecond early: touching
    c = {"id": "c", "start": 1.9, "duration": 1.0}            # really overlapping b
    assert [[x["id"] for x in lane] for lane in assign_lanes([a, b, c])] == [["a", "b"], ["c"]]


# ---- the whole AI edit, several times, with silences and fillers ---------------------------

@pytest.fixture
def talk(tmp_path, monkeypatch):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    words = load_transcript(synthetic.make_transcript(tmp_path / "talk.json"))
    monkeypatch.setattr(ai_edit, "transcribe", lambda *a, **k: words)
    cfg = load_config()
    cfg["output"].update(folder=str(tmp_path / "out"), encoder_speed="ultrafast")
    cfg["work_folder"] = str(tmp_path / "work")
    cfg["ai"]["cache_folder"] = str(tmp_path / "cache")
    cfg["overlays"]["triggers_file"] = str(tmp_path / "none.yaml")
    return video, cfg, Paths(tmp_path / "generation.json", tmp_path / "gen")


@pytest.mark.parametrize("fps", [24, 25, 30, 60])
def test_ai_edit_projects_always_validate(talk, fps):
    video, cfg, paths = talk
    cfg["output"]["fps"] = fps
    rng = random.Random(fps)
    for round_ in range(6):
        plan = preset_plan(cfg)
        plan["pacing"]["silence_threshold"] = rng.choice([0.15, 0.2, 0.25, 0.4])
        # Extra cuts at random places make many odd-sized pieces.
        plan["cuts"] = [{"start": round(a, 3), "end": round(a + rng.uniform(0.05, 0.4), 3),
                         "reason": ""} for a in sorted(rng.uniform(0.1, 7.4) for _ in range(rng.randint(0, 8)))]
        merged = []
        for c in plan["cuts"]:
            if not merged or c["start"] > merged[-1]["end"]:
                merged.append(c)
        plan["cuts"] = merged
        result = ai_edit.ai_edit_video(video, cfg, "", render=False, plan=plan, gen_paths=paths,
                                       output=video.parent / f"o{fps}_{round_}.mp4")
        project = load_project(result["project"])           # validates
        assert validate_project(project) == []
        main = sorted(next(t for t in project["tracks"] if t["kind"] == "video")["clips"],
                      key=lambda c: c["start"])
        assert len(main) >= 2
        for a, b in zip(main, main[1:]):
            assert abs(b["start"] - clip_end(a)) < 1e-9
        json.dumps(project)
