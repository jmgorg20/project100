"""Quality control: each objective check passes on a good video and fails on a video that has
exactly that problem (made on purpose with FFmpeg)."""

import subprocess

import pytest

from autoedit import qc
from autoedit.project import media_from_file, new_project


def mp4(path, seconds=3.0, size="1080x1920", audio="sine=f=330:r=48000", video=None, extra=(), container=None):
    """A test video: colour bars + a tone (or what is given)."""
    video = video or f"testsrc2=s={size}:r=30:d={seconds}"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", video]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"{audio}:d={seconds}" if "d=" not in audio else audio]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += list(extra)
    if container:
        cmd += ["-f", container]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def project_for(video, seconds=3.0, captions=()):
    p = new_project("qc")
    p["media"].append(media_from_file(video, "m1"))
    p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "m1", "start": 0, "duration": seconds,
                                "in": 0, "out": seconds}]
    for n, (start, dur, words) in enumerate(captions):
        step = dur / len(words)
        p["tracks"][3]["clips"].append({"id": f"t{n}", "type": "caption", "start": start, "duration": dur,
                                        "style": "yellow_pop",
                                        "words": [{"text": w, "start": round(k * step, 3), "end": round((k + 1) * step, 3)}
                                                  for k, w in enumerate(words)]})
    return p


def checks(report):
    return {c["id"]: c for c in report["checks"]}


@pytest.fixture
def good(tmp_path):
    video = mp4(tmp_path / "good.mp4")
    return video, project_for(video, captions=[(0.2, 1.2, ["Kumusta", "kayo"]), (1.5, 1.2, ["mga", "kaibigan"])])


def test_a_good_video_passes_every_check(good, tmp_path):
    video, project = good
    report = qc.run(video, project, tmp_path)
    by = checks(report)
    assert set(by) == set(qc.LABELS)
    assert report["passed"] and report["clean"], [c for c in report["checks"] if not c["ok"]]
    assert by["dimensions"]["details"]["width"] == 1080 and by["clipping"]["details"]["peak_db"] < 0


def test_wrong_size_and_wrong_length(tmp_path):
    video = mp4(tmp_path / "small.mp4", seconds=2.0, size="540x960")
    report = qc.run(video, project_for(video, seconds=2.0), tmp_path)
    assert checks(report)["dimensions"]["ok"] is False and "expected 1080x1920" in checks(report)["dimensions"]["message"]
    longer = project_for(video, seconds=2.0)
    longer["tracks"][0]["clips"][0]["duration"] = 2.0
    longer["tracks"][3]["clips"] = [{"id": "t1", "type": "caption", "start": 2.5, "duration": 1.0, "style": "classic",
                                     "words": [{"text": "late", "start": 0, "end": 0.5}]}]
    report = qc.run(video, longer, tmp_path)
    assert checks(report)["duration"]["ok"] is False and not report["passed"]


def test_not_a_video_and_not_an_mp4(tmp_path, good):
    _, project = good
    fake = tmp_path / "fake.mp4"
    fake.write_text("not a video")
    report = qc.run(fake, project, tmp_path)
    assert checks(report)["valid_mp4"]["ok"] is False and not report["passed"]
    mkv = mp4(tmp_path / "video.mkv", container="matroska")
    by = checks(qc.run(mkv, project_for(mkv), tmp_path))
    assert by["valid_mp4"]["ok"] is False and "not MP4" in by["valid_mp4"]["message"]
    silent = mp4(tmp_path / "nosound.mp4", audio=None)
    by = checks(qc.run(silent, project_for(silent), tmp_path))
    assert by["valid_mp4"]["ok"] is False and by["av_sync"]["ok"] is False


def test_sound_out_of_sync(tmp_path):
    video = mp4(tmp_path / "late.mp4")
    late = tmp_path / "late_sound.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-itsoffset", "0.6", "-i", str(video),
                    "-map", "0:v", "-map", "1:a", "-c", "copy", str(late)], check=True)
    by = checks(qc.run(late, project_for(late), tmp_path))
    assert by["av_sync"]["ok"] is False and by["av_sync"]["details"]["start_offset"] > 0.3


def test_black_frames(tmp_path):
    video = mp4(tmp_path / "black.mp4",
                video="testsrc2=s=1080x1920:r=30:d=3,drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,1,2)'")
    by = checks(qc.run(video, project_for(video), tmp_path))
    assert by["black_frames"]["ok"] is False
    [[a, b]] = by["black_frames"]["details"]["stretches"]
    assert abs(a - 1.0) < 0.1 and abs(b - 2.0) < 0.1


def test_silence_only_matters_where_someone_speaks(tmp_path):
    video = mp4(tmp_path / "quiet.mp4", audio="aevalsrc='0.4*sin(2*PI*330*t)*lt(t,0.8)':s=48000")
    speaking_late = project_for(video, captions=[(1.2, 1.5, ["Ito", "ang", "sinasabi", "ko"])])
    by = checks(qc.run(video, speaking_late, tmp_path))
    assert by["silence"]["ok"] is False and by["silence"]["severity"] == "warning"
    speaking_early = project_for(video, captions=[(0.0, 0.7, ["Hi"])])
    assert checks(qc.run(video, speaking_early, tmp_path))["silence"]["ok"]       # silence after: fine


def test_clipping(tmp_path):
    loud = mp4(tmp_path / "loud.mp4", audio="aevalsrc='1.4*sin(2*PI*330*t)':s=48000")
    by = checks(qc.run(loud, project_for(loud), tmp_path))
    assert by["clipping"]["ok"] is False and by["clipping"]["details"]["peak_db"] > -0.1


def test_missing_files_and_caption_timing(good, tmp_path):
    video, project = good
    project["media"].append({"id": "gone", "kind": "image", "path": str(tmp_path / "gone.png"), "duration": 0,
                             "width": 10, "height": 10})
    caps = project["tracks"][3]["clips"]
    caps[0]["words"] = list(reversed(caps[0]["words"]))
    caps.append({"id": "t9", "type": "caption", "start": 2.8, "duration": 0.2, "style": "classic",
                 "words": [{"text": "bilis", "start": 0, "end": 0.1}]})
    by = checks(qc.run(video, project, tmp_path))
    assert by["missing_assets"]["ok"] is False and by["missing_assets"]["details"]["files"] == [str(tmp_path / "gone.png")]
    assert by["caption_timing"]["ok"] is False and set(by["caption_timing"]["details"]["captions"]) == {"t0", "t9"}


def test_graphics_on_the_face_or_outside_the_safe_area(good, tmp_path):
    _, project = good
    project["tracks"].insert(2, {"id": "graphics", "kind": "graphics", "name": "Graphics", "clips": [
        {"id": "face", "type": "graphic", "template": "pop-heavy", "start": 0.2, "duration": 1.0,
         "params": {"text": "WOW"}, "x": 0.5, "y": 0.33},
        {"id": "edge", "type": "graphic", "template": "pop-heavy", "start": 1.5, "duration": 1.0,
         "params": {"text": "LABAS"}, "x": 0.98, "y": 0.12}]})
    by = {c["id"]: c for c in qc.check_project(project, tmp_path)}
    assert by["face"]["ok"] is False and by["face"]["details"]["clips"] == ["face"]
    assert by["safe_zones"]["ok"] is False and "edge" in by["safe_zones"]["details"]["clips"]
