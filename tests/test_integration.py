"""End-to-end tests: make a synthetic video with FFmpeg, run the whole editor, check the result."""

import json
import subprocess

import pytest

from autoedit.config import load_config
from autoedit.errors import EditorError
from autoedit.pipeline import edit_video
from tests import synthetic


def ffprobe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                          "-show_format", str(path)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    return video, audio, float(data["format"]["duration"])


@pytest.fixture
def setup(tmp_path):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    transcript = synthetic.make_transcript(tmp_path / "talk.json")
    cfg = load_config()
    cfg["output"]["folder"] = str(tmp_path / "output")
    cfg["work_folder"] = str(tmp_path / "work")
    cfg["output"]["encoder_speed"] = "ultrafast"
    cfg["overlays"]["triggers_file"] = str(tmp_path / "no_triggers.yaml")
    return tmp_path, video, transcript, cfg


def check_output(path, expected_length=None):
    video, audio, duration = ffprobe(path)
    assert (video["width"], video["height"]) == (1080, 1920)
    assert video["codec_name"] == "h264"
    assert video["r_frame_rate"] == "30/1"
    assert audio and audio[0]["codec_name"] == "aac"
    if expected_length:
        assert duration == pytest.approx(expected_length, abs=0.25)
    return duration


def test_full_pipeline(setup):
    tmp, video, transcript, cfg = setup
    out = edit_video(video, cfg, transcript=transcript)
    assert out.parent == tmp / "output" and out.name == "talk_edited.mp4"
    duration = check_output(out)
    # Silences (0.9s + ~1.1s incl. "uhm" + edges) were cut from the 8s video.
    assert 4.5 < duration < 6.0
    # Video and audio streams have the same length (in sync).
    v, a, _ = ffprobe(out)
    assert float(v["duration"]) == pytest.approx(float(a[0]["duration"]), abs=0.1)
    # Work folder is cleaned up.
    assert not any((tmp / "work").iterdir())


def test_overlays_plan_sfx_and_branding(setup):
    tmp, video, transcript, cfg = setup
    overlays = tmp / "overlays"
    overlays.mkdir()
    synthetic.make_image(overlays / "github.png")
    synthetic.make_image(overlays / "plan.png", color="blue")
    (tmp / "triggers.yaml").write_text(
        "triggers:\n  - keyword: github\n    file: github.png\n    duration: 1.5\n",
        encoding="utf-8")
    cfg["overlays"].update(folder=str(overlays), triggers_file=str(tmp / "triggers.yaml"))
    sfx = tmp / "pop.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=900:d=0.2",
                    str(sfx)], check=True)
    cfg["sfx"].update(enabled=True, pop=str(sfx), whoosh=str(sfx))
    logo = synthetic.make_image(tmp / "logo.png", color="white", size="200x80")
    intro = synthetic.make_image(tmp / "intro.png", color="purple", size="1080x1920")
    cfg["branding"].update(watermark=str(logo), intro=str(intro), intro_duration=1.0)
    plan = {
        "auto_zoom": True, "cuts": [], "overlays": [],
        "zooms": [{"start": 3.0, "end": 4.0, "amount": 1.4}],
        "grades": [{"start": 0.5, "end": 1.5, "grade": "black_and_white"}],
    }
    out = edit_video(video, cfg, transcript=transcript, plan=plan)
    duration = check_output(out)
    assert 5.5 < duration < 7.0   # ~1s intro + ~5s edit


def test_split_screen_layout(setup):
    tmp, video, transcript, cfg = setup
    screen = synthetic.make_video(tmp / "screen.mp4", width=1280, height=720, duration=6.0)
    out = edit_video(video, cfg, transcript=transcript, screen=screen, layout="split")
    check_output(out)


def test_pip_and_screen_only_layouts(setup):
    tmp, video, transcript, cfg = setup
    screen = synthetic.make_video(tmp / "screen.mp4", width=1280, height=720)
    check_output(edit_video(video, cfg, transcript=transcript, screen=screen, layout="pip"))
    check_output(edit_video(screen, cfg, transcript=transcript, layout="screen"))


def test_clear_errors(setup):
    tmp, video, transcript, cfg = setup
    silent = tmp / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:d=2",
                    "-pix_fmt", "yuv420p", str(silent)], check=True)
    with pytest.raises(EditorError, match="no audio"):
        edit_video(silent, cfg, transcript=transcript)
    text_file = tmp / "notes.txt"
    text_file.write_text("hello")
    with pytest.raises(EditorError, match="does not look like a video"):
        edit_video(text_file, cfg, transcript=transcript)
    with pytest.raises(EditorError, match="needs a screen recording"):
        edit_video(video, cfg, transcript=transcript, layout="split")
