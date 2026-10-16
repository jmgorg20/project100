"""The track, track-status and track-models commands (in-process, with a stand-in MediaPipe and
a faked download: no network, no real models)."""

import json
import sys

import pytest

import editor
from autoedit import tracking
from autoedit.project import load_project, media_from_file, new_project, save_project
from tests import synthetic
from tests.test_tracking import make_fake_mediapipe


def run(args, capsys):
    code = editor.main(["--json", *args])
    out, err = capsys.readouterr()
    lines = [json.loads(x) for x in out.splitlines() if x.strip().startswith("{")]
    return code, lines, err


@pytest.fixture
def setup(tmp_path, monkeypatch):
    (tmp_path / "hand.task").write_bytes(b"x")
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        f"tracking: {{hand_model: '{(tmp_path / 'hand.task').as_posix()}', fps: 10}}\n"
        f"work_folder: '{(tmp_path / 'work').as_posix()}'\n"
        f"ai: {{cache_folder: '{(tmp_path / 'cache').as_posix()}'}}\n", encoding="utf-8")
    video = synthetic.make_video(tmp_path / "talk.mp4", width=360, height=640, duration=4.0)
    make_fake_mediapipe(monkeypatch)
    return tmp_path, cfg, video


def test_track_status_and_model_listing(setup, capsys, monkeypatch):
    tmp, cfg, _video = setup
    code, lines, _ = run(["--config", str(cfg), "track-status"], capsys)
    assert code == 0 and lines[-1]["available"] and lines[-1]["hands"] and not lines[-1]["face"]
    assert {m["kind"] for m in lines[-1]["models"]} == {"hand", "face", "pose"}
    monkeypatch.setitem(sys.modules, "mediapipe", None)
    code, lines, _ = run(["--config", str(cfg), "track-status"], capsys)
    assert not lines[-1]["available"] and "pip install mediapipe" in lines[-1]["problems"][0]


def test_track_a_video_writes_the_points(setup, capsys):
    tmp, cfg, video = setup
    code, lines, _ = run(["--config", str(cfg), "track", str(video), "--points", "right_palm", "--ranges", "0.5-2",
                          "--output", str(tmp / "t.json")], capsys)
    assert code == 0 and lines[-1]["found"]["right_palm"] > 0.5
    data = json.loads((tmp / "t.json").read_text())
    assert list(data["points"]) == ["right_palm"] and data["start"] == 0.5
    code, lines, _ = run(["--config", str(cfg), "track", str(video), "--ranges", "bad"], capsys)
    assert code != 0 and "Cannot read the range" in lines[-1]["message"]


def test_track_a_project_follows_what_its_effects_need_and_is_cached(setup, capsys):
    tmp, cfg, video = setup
    p = new_project("t", normalize_audio=False)
    p["media"] = [media_from_file(video, "vid")]
    t = {x["id"]: x for x in p["tracks"]}
    t["main"]["clips"] = [{"id": "v1", "type": "video", "media": "vid", "start": 0.0, "duration": 2.0, "in": 1.0, "out": 3.0}]
    t["effects"]["clips"] = [{"id": "k1", "type": "trackfx", "start": 0.5, "duration": 1.0, "effect": "glow",
                              "point": "index_tip", "hand": "right"}]
    file = save_project(p, tmp / "p.project.json")
    code, lines, _ = run(["--config", str(cfg), "track", str(file)], capsys)
    assert code == 0, lines
    saved = load_project(file)                                    # still valid
    track = saved["tracking"]["vid"]
    assert set(track["points"]) == {"right_index_tip"} and track["fps"] == 10
    # The effect shows timeline 0.5-1.5 = source 1.5-2.5, plus 0.5 s each side.
    assert track["start"] == pytest.approx(1.0)
    assert track["points"]["right_index_tip"]["c"][0] > 0
    first = len(tracking.status({}))                              # (just to touch the module)
    from tests.test_tracking import FakeLandmarker
    calls = len(FakeLandmarker.log)
    code, lines, _ = run(["--config", str(cfg), "track", str(file)], capsys)
    assert code == 0 and len(FakeLandmarker.log) == calls         # the saved track was used
    assert first >= 0


def test_models_are_listed_but_only_downloaded_when_you_say_so(setup, capsys, monkeypatch, tmp_path):
    _tmp, cfg, _video = setup
    code, lines, _ = run(["--config", str(cfg), "track-models"], capsys)
    assert code == 0 and lines[-1]["downloaded"] == []
    code, lines, _ = run(["--config", str(cfg), "track-models", "--download", "hand"], capsys)
    assert code != 0 and "--yes" in lines[-1]["message"]            # asks you to confirm first
    import requests

    class Answer:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_content(self, n):
            yield b"MODEL" * 400

    seen = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: seen.append(url) or Answer())
    monkeypatch.setattr(tracking, "MODEL_DIR", tmp_path / "models")
    code, lines, _ = run(["--config", str(cfg), "track-models", "--download", "face", "--yes"], capsys)
    assert code == 0 and lines[-1]["downloaded"] == ["face"]
    assert seen == [tracking.MODEL_URLS["face"]]
    assert (tmp_path / "models" / "blaze_face_short_range.tflite").read_bytes().startswith(b"MODEL")
    assert not list((tmp_path / "models").glob("*.part"))
    # A bad answer leaves nothing behind and says so plainly.
    Answer.status_code = 404
    code, lines, _ = run(["--config", str(cfg), "track-models", "--download", "pose", "--yes"], capsys)
    assert code != 0 and "could not be downloaded (404)" in lines[-1]["message"]
    assert not (tmp_path / "models" / "pose_landmarker_lite.task").exists()
