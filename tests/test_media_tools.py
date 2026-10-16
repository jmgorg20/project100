"""Waveform peaks, filmstrip pictures and media info for the timeline editor (real FFmpeg)."""

import json
import os
import time
from pathlib import Path

import pytest

from autoedit.errors import EditorError
from autoedit.media_tools import peaks, thumbs
from autoedit.project import save_project
from tests import synthetic
from tests.test_integration import ffprobe
from tests.test_project_render import media, run_cli, tracks, vclip, write_config  # noqa: F401


def test_peaks_follow_the_sound_and_are_cached(tmp_path):
    loud = synthetic.make_tone(tmp_path / "tone.wav", duration=2.0)
    data = peaks(loud, tmp_path / "cache", per_second=50)
    assert data["has_audio"] and data["per_second"] == 50
    assert len(data["peaks"]) == pytest.approx(100, abs=1)
    assert min(data["peaks"]) > 20 and max(data["peaks"]) <= 255
    cached = list((tmp_path / "cache").glob("*.json"))
    assert len(cached) == 1
    assert peaks(loud, tmp_path / "cache", per_second=50) == data      # from the cache

    # A changed file gets new peaks (the cache key includes size and modification time).
    synthetic.make_tone(loud, duration=1.0)
    os.utime(loud, (time.time() + 5, time.time() + 5))
    assert len(peaks(loud, tmp_path / "cache", per_second=50)["peaks"]) == pytest.approx(50, abs=1)


def test_peaks_of_a_silent_part_and_of_a_file_without_sound(tmp_path):
    image = synthetic.make_image(tmp_path / "a.png")
    assert peaks(image, tmp_path / "c")["peaks"] == []
    with pytest.raises(EditorError, match="not found"):
        peaks(tmp_path / "missing.wav", tmp_path / "c")


def test_thumbs_one_picture_per_second(tmp_path):
    video = synthetic.make_color_video(tmp_path / "colors.mp4")
    data = thumbs(video, tmp_path / "cache", height=96)
    assert data["every"] == 1 and len(data["files"]) == 4
    first, last = data["files"][0], data["files"][-1]
    assert synthetic.pixels(first, [0], 10, 10)[0][0] > 180       # red second
    assert synthetic.pixels(last, [0], 10, 10)[0] == pytest.approx((255, 255, 255), abs=40)
    assert thumbs(video, tmp_path / "cache", height=96) == data     # cached
    image = synthetic.make_image(tmp_path / "p.png")
    assert len(thumbs(image, tmp_path / "cache")["files"]) == 1
    tone = synthetic.make_tone(tmp_path / "t.wav")
    assert thumbs(tone, tmp_path / "cache")["files"] == []


def test_cli_media_info_peaks_thumbs_and_render_fps(media):  # noqa: F811
    tmp, p = media
    cfg = write_config(tmp)
    proc = run_cli(["--config", str(cfg), "--json", "media-info", str(tmp / "colors.mp4"),
                    str(tmp / "tone.wav"), str(tmp / "missing.mp4")], tmp)
    out, err = proc.communicate(timeout=120)
    assert proc.returncode == 0, err
    result = json.loads(out.splitlines()[-1])
    assert [m["kind"] for m in result["media"]] == ["video", "audio"]
    assert result["media"][0]["duration"] == pytest.approx(4.0, abs=0.05)
    assert result["errors"][0]["path"].endswith("missing.mp4")

    for command in (["peaks", str(tmp / "tone.wav")], ["thumbs", str(tmp / "colors.mp4")]):
        proc = run_cli(["--config", str(cfg), "--json", *command], tmp)
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        result = json.loads(out.splitlines()[-1])
        assert result["type"] == "result"
        assert result.get("peaks") or result.get("files")
    assert (tmp / "work" / "cache" / "peaks").is_dir() and (tmp / "work" / "cache" / "thumbs").is_dir()

    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0)]
    project_file = save_project(p, tmp / "fps.project.json")
    proc = run_cli(["--config", str(cfg), "--json", "render", str(project_file), "--fps", "25",
                    "--output", str(tmp / "fps25.mp4")], tmp)
    _out, err = proc.communicate(timeout=300)
    assert proc.returncode == 0, err
    v, _a, _d = ffprobe(tmp / "fps25.mp4")
    assert int(v["nb_frames"]) == 50 and v["r_frame_rate"] == "25/1"


def test_a_browser_recording_without_a_stated_length_is_measured_and_renders(media):  # noqa: F811
    """Voice-overs recorded in the app are WebM files that do not state their length."""
    from autoedit.ffmpeg_tools import probe
    from autoedit.project import media_from_file
    from autoedit.project_render import render_project
    from tests.test_project_render import FAST
    recording = Path(__file__).with_name("data") / "browser_recording.webm"
    assert probe(recording)["duration"] == pytest.approx(1.92, abs=0.1)
    tmp, p = media
    m = media_from_file(recording, "rec")
    assert m["kind"] == "audio" and m["duration"] > 1.5
    p["media"].append(m)
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0, volume=0)]
    tracks(p)["voiceover"]["clips"] = [{"id": "vo", "type": "audio", "media": "rec", "start": 0.0,
                                        "duration": m["duration"], "in": 0.0, "out": m["duration"]}]
    out = render_project(p, tmp / "vo.mp4", base_dir=tmp, export=FAST)
    _v, a, _d = ffprobe(out)
    assert float(a[0]["duration"]) == pytest.approx(2.0, abs=0.05)
