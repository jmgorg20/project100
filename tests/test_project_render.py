"""Render synthetic Projects with FFmpeg and check the result frame by frame."""

import json
import math
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from autoedit import PROJECT_DIR
from autoedit.captions import build_ass, fonts_from_config
from autoedit.config import load_config
from autoedit.cuts import remap_words
from autoedit.errors import Cancelled, EditorError
from autoedit.ffmpeg_tools import filter_script_args, run_ffmpeg
from autoedit.grades import grade_filter
from autoedit.highlight import mark_keywords
from autoedit.pipeline import build_edit_project
from autoedit.previews import copy_fonts
from autoedit.project import load_project, media_from_file, new_project, save_project
from autoedit.project_render import render_frame, render_project
from autoedit.render import RenderJob, build
from autoedit.styles import get_style
from autoedit.words import load_transcript
from tests import synthetic
from tests.test_integration import ffprobe

FAST = {"encoder_speed": "ultrafast", "crf": 16}


def is_color(rgb, name):
    r, g, b = rgb
    return {
        "red": r > 180 and g < 70 and b < 70,
        "green": g > 100 and r < 70 and b < 70,
        "blue": b > 180 and r < 70 and g < 70,
        "white": min(rgb) > 200,
        "black": max(rgb) < 30,
        "yellow": r > 180 and g > 180 and b < 70,
        "magenta": r > 180 and b > 180 and g < 70,
        "gray": max(rgb) - min(rgb) < 20 and 40 < r < 220,
    }[name]


@pytest.fixture
def media(tmp_path):
    video = synthetic.make_color_video(tmp_path / "colors.mp4")
    yellow = synthetic.make_image(tmp_path / "yellow.png", color="yellow", size="600x400")
    magenta = synthetic.make_image(tmp_path / "magenta.png", color="magenta", size="200x200")
    tone = synthetic.make_tone(tmp_path / "tone.wav", duration=2.0)
    p = new_project("test", normalize_audio=False)
    p["media"] = [media_from_file(video, "vid"), media_from_file(yellow, "yel"),
                  media_from_file(magenta, "mag"), media_from_file(tone, "tone")]
    return tmp_path, p


def tracks(p):
    return {t["id"]: t for t in p["tracks"]}


def vclip(cid, start, src, duration=1.0, **extra):
    return {"id": cid, "type": "video", "media": "vid", "start": start, "duration": duration,
            "in": src, "out": src + duration, **extra}


def test_timeline_renders_frame_accurately(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [
        vclip("v1", 0.0, 2.0),                       # blue
        vclip("v2", 1.0, 0.0),                       # red (earlier in the source: reordered)
        # 2.0-2.5 empty: black
        {"id": "i1", "type": "image", "media": "yel", "start": 2.5, "duration": 0.5},
        vclip("v3", 3.0, 1.0),                       # green, black & white from 3.5
    ]
    t["photos"]["clips"] = [{"id": "o1", "type": "image", "media": "mag", "start": 0.5,
                             "duration": 0.5, "x": 540, "y": 960, "width": 200,
                             "height": 200, "animation": "none"}]
    t["effects"]["clips"] = [{"id": "g1", "type": "grade", "start": 3.5, "duration": 0.5,
                              "grade": "black_and_white"}]
    out = render_project(p, tmp / "out.mp4", base_dir=tmp, export=FAST)

    v, a, duration = ffprobe(out)
    assert int(v["nb_frames"]) == 120
    assert float(v["duration"]) == pytest.approx(4.0, abs=0.001)
    assert float(a[0]["duration"]) == pytest.approx(4.0, abs=0.025)   # one AAC frame
    expected = {0: "blue", 29: "blue", 30: "red", 59: "red", 60: "black", 74: "black",
                75: "yellow", 89: "yellow", 90: "green", 104: "green", 105: "gray",
                119: "gray"}
    found = synthetic.pixels(out, sorted(expected), 100, 100)
    for (n, name), rgb in zip(sorted(expected.items()), found):
        assert is_color(rgb, name), f"frame {n}: expected {name}, got {rgb}"
    # The photo is on screen for frames 15-29 only.
    centre = dict(zip([14, 15, 29, 30], synthetic.pixels(out, [14, 15, 29, 30], 540, 960)))
    assert is_color(centre[14], "blue") and is_color(centre[30], "red")
    assert is_color(centre[15], "magenta") and is_color(centre[29], "magenta")
    assert not (tmp / "out.part.mp4").exists()


def test_render_exact_frame_matches_the_video(media):
    tmp, p = media
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 2.0), vclip("v2", 1.0, 0.0)]
    # 0.999s is still frame 29 (blue); 1.0s is frame 30 (red).
    for seconds, name in ((0.999, "blue"), (1.0, "red"), (1.99, "red"), (99, "red")):
        png = render_frame(p, seconds, tmp / f"f{seconds}.png", base_dir=tmp)
        info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                               "-of", "csv=p=0", str(png)], capture_output=True, text=True)
        assert info.stdout.strip() == "1080,1920"
        assert is_color(synthetic.pixels(png, [0], 100, 100)[0], name), seconds


def test_audio_tracks_volume_mute_and_timing(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=3.0, volume=0)]
    t["music"]["clips"] = [{"id": "a1", "type": "audio", "media": "tone", "start": 1.5,
                            "duration": 1.0, "in": 0.5, "out": 1.5, "volume": 0.5}]
    out = render_project(p, tmp / "a.mp4", base_dir=tmp, export=FAST)
    samples = synthetic.pcm(out)
    rate = 8000

    def rms(a, b):
        part = samples[int(a * rate):int(b * rate)]
        return math.sqrt(sum(x * x for x in part) / len(part))

    assert rms(0.1, 1.4) < 50                 # main video muted (volume 0)
    # The tone (FFmpeg's sine is 1/8 full scale: RMS 2896) at volume 0.5, spread from mono
    # to stereo at -3 dB as usual: about 1024.
    assert 850 < rms(1.6, 2.4) < 1250         # the tone, from 1.5s
    assert rms(2.6, 2.9) < 50                 # tone clip ended at 2.5s
    _v, a, _d = ffprobe(out)
    assert float(a[0]["duration"]) == pytest.approx(3.0, abs=0.025)


def test_volume_and_fades_change_loudness(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0, volume=0.25)]
    t["sfx"]["clips"] = [{"id": "a1", "type": "audio", "media": "tone", "start": 0.0,
                          "duration": 2.0, "in": 0.0, "out": 2.0, "fade_in": 1.0}]
    t["main"]["muted"] = True
    out = render_project(p, tmp / "f.mp4", base_dir=tmp, export=FAST)
    samples = synthetic.pcm(out)
    early = max(abs(x) for x in samples[0:800])          # first 0.1 s: fading in
    late = max(abs(x) for x in samples[12000:16000])     # 1.5-2.0 s: full
    assert early < late / 3


def test_export_height_scales_the_video(media):
    tmp, p = media
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0)]
    out = render_project(p, tmp / "small.mp4", base_dir=tmp,
                         export={**FAST, "height": 1280})
    v, _a, _d = ffprobe(out)
    assert (v["width"], v["height"]) == (720, 1280)


def test_clear_errors_for_empty_or_missing(media):
    tmp, p = media
    with pytest.raises(EditorError, match="timeline is empty"):
        render_project(p, tmp / "x.mp4", base_dir=tmp)
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0)]
    (tmp / "colors.mp4").unlink()
    with pytest.raises(EditorError, match="missing"):
        render_project(p, tmp / "x.mp4", base_dir=tmp)
    assert not (tmp / "x.mp4").exists()


def test_cancel_stops_render_and_leaves_no_file(media):
    tmp, p = media
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=4.0)]
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    with pytest.raises(Cancelled):
        render_project(p, tmp / "c.mp4", base_dir=tmp, export={"encoder_speed": "veryslow"},
                       cancel=cancel)
    assert not (tmp / "c.mp4").exists() and not (tmp / "c.part.mp4").exists()


# ------------------------------------------------------------ the auto edit as a project

@pytest.fixture
def talk(tmp_path):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    transcript = synthetic.make_transcript(tmp_path / "talk.json")
    cfg = load_config()
    cfg["output"]["folder"] = str(tmp_path / "output")
    cfg["work_folder"] = str(tmp_path / "work")
    cfg["output"]["encoder_speed"] = "ultrafast"
    cfg["overlays"]["triggers_file"] = str(tmp_path / "no_triggers.yaml")
    return tmp_path, video, transcript, cfg


def legacy_render(project, video, transcript, cfg, out, work):
    """The original single-video renderer (render.build) fed the same decisions."""
    main = next(t for t in project["tracks"] if t["kind"] == "video")["clips"]
    segments = [(c["in"], c["out"]) for c in main]
    zooms = {}
    for track in project["tracks"]:
        for c in track["clips"]:
            if c["type"] == "zoom":
                zooms.setdefault(c["amount"], []).append((c["start"], c["start"] + c["duration"]))
    pacing = cfg["pacing"]
    words = remap_words(load_transcript(transcript), segments, cfg["fillers"],
                        pacing["remove_fillers"])
    mark_keywords(words, cfg["highlight"])
    copy_fonts(cfg["captions"]["fonts_folder"], work / "fonts")
    style = get_style(cfg["style"])
    (work / "captions.ass").write_text(
        build_ass(words, style, fonts_from_config(cfg["captions"]), fonts_folder=work / "fonts"),
        encoding="utf-8")
    job = RenderJob(video=video, segments=segments, output=out, zooms=list(zooms.items()),
                    anchor_y=cfg["zoom"]["anchor_y"], grade=grade_filter(cfg["grade"]),
                    ass_file="captions.ass", crf=16, encoder_speed="ultrafast")
    inputs, graph, outputs = build(job)
    (work / "filters.txt").write_text(graph, encoding="utf-8")
    run_ffmpeg(inputs + filter_script_args(work / "filters.txt") + outputs, "legacy render",
               cwd=work, show_progress=False)
    return out


def test_project_render_matches_the_original_renderer(talk):
    """The auto edit rendered through its Project gives the same picture and sound as the
    original one-video renderer."""
    tmp, video, transcript, cfg = talk
    project = build_edit_project(video, cfg, transcript=transcript, job_dir=tmp / "job")
    new = render_project(project, tmp / "new.mp4", export=FAST)
    (tmp / "legacy").mkdir()
    old = legacy_render(project, video, transcript, cfg, tmp / "old.mp4", tmp / "legacy")

    v_new, a_new, _ = ffprobe(new)
    v_old, a_old, _ = ffprobe(old)
    assert v_new["nb_frames"] == v_old["nb_frames"]
    stats = tmp / "psnr.log"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(old), "-i", str(new), "-lavfi",
                    f"[0:v][1:v]psnr=stats_file={stats.name}", "-f", "null", "-"],
                   cwd=tmp, check=True)
    worst = min(float(line.split("psnr_avg:")[1].split()[0].replace("inf", "99"))
                for line in stats.read_text().splitlines())
    assert worst > 50, f"a frame differs (PSNR {worst} dB)"
    old_pcm, new_pcm = synthetic.pcm(old), synthetic.pcm(new)
    assert len(old_pcm) == len(new_pcm)
    assert max(abs(x - y) for x, y in zip(old_pcm, new_pcm)) <= 2


def test_edit_saves_a_project_that_renders_again(talk):
    from autoedit.pipeline import edit_video
    tmp, video, transcript, cfg = talk
    out = edit_video(video, cfg, transcript=transcript)
    project_file = out.with_suffix(".project.json")
    project = load_project(project_file)
    kinds = [t["kind"] for t in project["tracks"]]
    assert kinds[0] == "video" and "caption" in kinds and "effect" in kinds
    assert project["transcript"]["words"][9]["text"] == "*GitHub*"
    again = render_project(project, tmp / "again.mp4", base_dir=project_file.parent,
                           export=FAST)
    assert ffprobe(again)[0]["nb_frames"] == ffprobe(out)[0]["nb_frames"]


# ------------------------------------------------------------ command line, as the app uses it

def run_cli(args, cwd, **kw):
    return subprocess.Popen([sys.executable, str(PROJECT_DIR / "editor.py"), *args], cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)


def write_config(tmp):
    cfg = tmp / "cfg.yaml"
    cfg.write_text(f"output: {{folder: '{(tmp / 'out').as_posix()}', encoder_speed: ultrafast}}\n"
                   f"work_folder: '{(tmp / 'work').as_posix()}'\n", encoding="utf-8")
    return cfg


def test_cli_json_render_frame_and_validate(media):
    tmp, p = media
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0)]
    project_file = save_project(p, tmp / "demo.project.json")
    cfg = write_config(tmp)

    proc = run_cli(["--config", str(cfg), "--json", "render", str(project_file)], tmp)
    out, err = proc.communicate(timeout=300)
    assert proc.returncode == 0, err
    events = [json.loads(line) for line in out.splitlines()]      # stdout is only JSON
    assert events[0]["type"] == "stage"
    assert any(e["type"] == "progress" for e in events)
    assert events[-1] == {"type": "result", "output": str(tmp / "demo_render.mp4")}
    assert (tmp / "demo_render.mp4").exists()

    proc = run_cli(["--config", str(cfg), "--json", "frame", str(project_file), "--time", "1.5"],
                   tmp)
    out, err = proc.communicate(timeout=300)
    assert proc.returncode == 0, err
    result = json.loads(out.splitlines()[-1])
    assert result["type"] == "result" and Path(result["output"]).exists()

    proc = run_cli(["--json", "validate", str(project_file)], tmp)
    out, _err = proc.communicate(timeout=60)
    assert json.loads(out.splitlines()[-1])["valid"] is True

    bad = tmp / "bad.project.json"
    p["tracks"][0]["clips"][0]["media"] = "nope"
    bad.write_text(json.dumps(p), encoding="utf-8")
    proc = run_cli(["--json", "validate", str(bad)], tmp)
    out, _err = proc.communicate(timeout=60)
    assert proc.returncode == 1
    error = json.loads(out.splitlines()[-1])
    assert error["type"] == "error" and "unknown media 'nope'" in error["message"]


def test_cli_refuses_to_overwrite_a_source_file(media):
    tmp, p = media
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0)]
    project_file = save_project(p, tmp / "demo.project.json")
    proc = run_cli(["--config", str(write_config(tmp)), "render", str(project_file),
                    "--output", str(tmp / "colors.mp4")], tmp)
    _out, err = proc.communicate(timeout=60)
    assert proc.returncode == 1 and "one of the project's own media files" in err


@pytest.mark.parametrize("how", ["cancel", "close"])
def test_cli_cancel_from_the_app(media, how):
    """The app cancels by writing "cancel", or by going away (stdin closes): FFmpeg stops."""
    tmp, p = media
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=4.0)]
    project_file = save_project(p, tmp / "demo.project.json")
    proc = run_cli(["--config", str(write_config(tmp)), "--json", "--stdin-control", "render",
                    str(project_file), "--speed", "slow", "--output", str(tmp / "c.mp4")],
                   tmp, stdin=subprocess.PIPE)
    first = json.loads(proc.stdout.readline())
    assert first["type"] == "stage"
    if how == "cancel":
        proc.stdin.write("cancel\n")
        proc.stdin.flush()
    # "close": communicate() closes stdin (the app went away); closing it here first makes
    # communicate() fail on Python 3.12 when it flushes the closed pipe
    out, _err = proc.communicate(timeout=60)
    assert proc.returncode == 130
    assert json.loads(out.splitlines()[-1]) == {"type": "cancelled"}
    assert not (tmp / "c.mp4").exists() and not (tmp / "c.part.mp4").exists()
    if os.name != "nt":
        left = subprocess.run(["pgrep", "-f", str(tmp / "c.part.mp4")], capture_output=True)
        assert left.returncode == 1, "ffmpeg is still running"


# ---------------------------------------------------------------- version 2: speed, crop, fades

def two_halves_video(path, width=720, height=1280, seconds=2):
    """Left half red, right half blue (to see which part a crop keeps)."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-filter_complex",
         f"color=c=red:s={width}x{height}:r=30:d={seconds}[l];"
         f"color=c=blue:s={width // 2}x{height}:r=30:d={seconds}[r];"
         f"[l][r]overlay=x={width // 2}:y=0[v]",
         "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         str(path)], check=True)
    return Path(path)


def test_speed_changes_how_fast_the_source_plays(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [
        vclip("fast", 0.0, 0.0, duration=1.0, speed=2.0, out=2.0),   # red + green in 1 s
        vclip("slow", 1.0, 2.0, duration=1.0, speed=0.5, out=2.5),   # half a second of blue
    ]
    out = render_project(p, tmp / "speed.mp4", base_dir=tmp, export=FAST)
    v, a, _d = ffprobe(out)
    assert int(v["nb_frames"]) == 60
    assert float(a[0]["duration"]) == pytest.approx(2.0, abs=0.025)
    expected = {0: "red", 13: "red", 16: "green", 29: "green", 30: "blue", 59: "blue"}
    for (n, name), rgb in zip(sorted(expected.items()),
                              synthetic.pixels(out, sorted(expected), 100, 100)):
        assert is_color(rgb, name), f"frame {n}: expected {name}, got {rgb}"
    samples = synthetic.pcm(out)
    assert max(abs(x) for x in samples[2000:6000]) > 1500        # sound kept (atempo)
    assert max(abs(x) for x in samples[10000:14000]) > 1500


def test_crop_reframes_the_picture(media):
    tmp, p = media
    p["media"].append(media_from_file(two_halves_video(tmp / "halves.mp4"), "halves"))
    t = tracks(p)

    def clip(cid, start, crop=None):
        c = {"id": cid, "type": "video", "media": "halves", "start": start, "duration": 0.5,
             "in": 0.0, "out": 0.5}
        return {**c, "crop": crop} if crop else c
    t["main"]["clips"] = [clip("plain", 0.0), clip("left", 0.5, {"zoom": 2, "x": 0, "y": 0}),
                          clip("right", 1.0, {"zoom": 2, "x": 1, "y": 1})]
    out = render_project(p, tmp / "crop.mp4", base_dir=tmp, export=FAST)
    left_edge = synthetic.pixels(out, [5, 20, 35], 60, 960)
    right_edge = synthetic.pixels(out, [5, 20, 35], 1020, 960)
    assert is_color(left_edge[0], "red") and is_color(right_edge[0], "blue")      # whole frame
    assert is_color(left_edge[1], "red") and is_color(right_edge[1], "red")       # zoomed left
    assert is_color(left_edge[2], "blue") and is_color(right_edge[2], "blue")     # zoomed right


def test_video_clip_sound_fades_and_speed_on_overlay_and_audio(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0, fade_in=1.0)]
    t["photos"]["clips"] = [{"id": "o1", "type": "video", "media": "vid", "start": 0.0,
                             "duration": 1.0, "in": 0.0, "out": 2.0, "speed": 2.0,
                             "x": 540, "y": 960, "width": 400, "height": 400}]
    out = render_project(p, tmp / "fade.mp4", base_dir=tmp, export=FAST)
    samples = synthetic.pcm(out)
    assert max(abs(x) for x in samples[0:800]) < max(abs(x) for x in samples[12000:16000]) / 3
    centre = synthetic.pixels(out, [5, 25], 540, 960)
    assert is_color(centre[0], "red") and is_color(centre[1], "green")   # 2x: green by 0.5 s

    # A sound effect at double speed lasts half as long.
    t["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0, volume=0)]
    t["photos"]["clips"] = []
    t["sfx"]["clips"] = [{"id": "a1", "type": "audio", "media": "tone", "start": 0.0,
                          "duration": 1.0, "in": 0.0, "out": 2.0, "speed": 2.0}]
    out = render_project(p, tmp / "sfx.mp4", base_dir=tmp, export=FAST)
    samples = synthetic.pcm(out)
    assert max(abs(x) for x in samples[2000:6000]) > 3000
    assert max(abs(x) for x in samples[10000:16000]) < 300


# ---------------------------------------------------------------- effects (phase 2)

def fx_render(tmp, p, name, effects, main=None):
    t = tracks(p)
    t["main"]["clips"] = main or [vclip("v1", 0.0, 0.0, duration=2.0)]   # red then green
    t["effects"]["clips"] = effects
    return render_project(p, tmp / f"{name}.mp4", base_dir=tmp, export=FAST)


def test_flash_dip_and_whip_change_the_picture_only_in_their_moment(media):
    tmp, p = media
    p["media"].append(media_from_file(two_halves_video(tmp / "halves.mp4"), "halves"))
    halves = [{"id": "h", "type": "video", "media": "halves", "start": 0.0, "duration": 2.0,
               "in": 0.0, "out": 2.0}]
    out = fx_render(tmp, p, "flash", [{"id": "f", "type": "fx", "effect": "flash", "start": 0.5,
                                       "duration": 0.4, "intensity": 1}])
    before, peak, after = synthetic.pixels(out, [10, 21, 40], 300, 960)
    assert is_color(before, "red") and is_color(after, "green")
    assert min(peak) > 180                                  # the red frame flashes to white

    out = fx_render(tmp, p, "dip", [{"id": "d", "type": "fx", "effect": "dip", "start": 0.5,
                                     "duration": 0.4, "intensity": 1}])
    before, peak, after = synthetic.pixels(out, [10, 21, 40], 300, 960)
    assert is_color(before, "red") and max(peak) < 40 and is_color(after, "green")

    out = fx_render(tmp, p, "whip", [{"id": "w", "type": "fx", "effect": "whip", "start": 0.5,
                                      "duration": 0.5, "intensity": 1}], main=halves)
    sharp, blurred = synthetic.pixels(out, [5, 22], 520, 960)   # just left of the red|blue edge
    assert is_color(sharp, "red")
    assert blurred[2] > 60 and blurred[0] < 220              # mixed with the blue side


def test_shake_and_glitch_move_the_picture(media):
    tmp, p = media
    p["media"].append(media_from_file(two_halves_video(tmp / "halves.mp4"), "halves"))
    halves = [{"id": "h", "type": "video", "media": "halves", "start": 0.0, "duration": 2.0,
               "in": 0.0, "out": 2.0}]
    plain = fx_render(tmp, p, "plain", [], main=halves)
    for effect in ("shake", "glitch"):
        out = fx_render(tmp, p, effect, [{"id": "e", "type": "fx", "effect": effect,
                                          "start": 0.5, "duration": 1.0, "intensity": 1}],
                        main=halves)
        frames = [16, 20, 25, 30]
        moved = [a != b for a, b in zip(synthetic.pixels(out, frames, 540, 960),
                                         synthetic.pixels(plain, frames, 540, 960))]
        assert any(moved), effect                           # the edge pixel changes
        before = zip(synthetic.pixels(out, [5], 540, 960)[0], synthetic.pixels(plain, [5], 540, 960)[0])
        assert all(abs(a - b) < 16 for a, b in before), effect   # untouched before it starts


def test_grade_intensity_and_smooth_zoom(media):
    tmp, p = media
    p["media"].append(media_from_file(two_halves_video(tmp / "halves.mp4"), "halves"))
    full = fx_render(tmp, p, "bw", [{"id": "g", "type": "grade", "grade": "black_and_white",
                                     "start": 0, "duration": 2}])
    half = fx_render(tmp, p, "bw_half", [{"id": "g", "type": "grade", "grade": "black_and_white",
                                          "start": 0, "duration": 2, "intensity": 0.5}])
    r_full = synthetic.pixels(full, [10], 300, 960)[0]
    r_half = synthetic.pixels(half, [10], 300, 960)[0]
    assert max(r_full) - min(r_full) < 20                   # grey
    assert 40 < r_half[0] - r_half[1] < 200                 # halfway: still reddish

    # Zoom 2x, eased over 1 s from t=0, centred: at x=330 the frame shows the red band at
    # 100% and the green band once zoomed past ~117% (frame 5). A plain zoom is green at once.
    p["media"].append(media_from_file(three_bands_video(tmp / "bands.mp4"), "bands"))
    bands = [{"id": "b", "type": "video", "media": "bands", "start": 0.0, "duration": 2.0,
              "in": 0.0, "out": 2.0}]
    zoom = {"id": "z", "type": "zoom", "amount": 2, "anchor_y": 0.5, "start": 0, "duration": 2}
    eased = fx_render(tmp, p, "ease", [{**zoom, "ease": 1.0}], main=bands)
    punch = fx_render(tmp, p, "punch", [zoom], main=bands)
    e0, e15, e45 = synthetic.pixels(eased, [0, 15, 45], 330, 960)
    assert is_color(e0, "red") and is_color(e15, "green") and is_color(e45, "green")
    assert is_color(synthetic.pixels(punch, [0], 330, 960)[0], "green")
    centre = synthetic.pixels(eased, [0, 15, 45], 540, 960)
    assert all(is_color(c, "green") for c in centre)          # zooms towards the centre


def three_bands_video(path, width=720, height=1280, seconds=2):
    """Red, green and blue vertical bands, a third of the width each."""
    third = width // 3
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-filter_complex",
         f"color=c=red:s={width}x{height}:r=30:d={seconds}[a];"
         f"color=c=0x00c000:s={third}x{height}:r=30:d={seconds}[g];"
         f"color=c=blue:s={third}x{height}:r=30:d={seconds}[b];"
         f"[a][g]overlay=x={third}[ag];[ag][b]overlay=x={2 * third}[v]",
         "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         str(path)], check=True)
    return Path(path)


# ---------------------------------------------------------------- audio (phase 2)

def band_rms(media, af, start, end, rate=16000):
    """Loudness (RMS) of the sound between start and end seconds, after the filter `af`."""
    import array
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-af", af, "-ac", "1",
                          "-ar", str(rate), "-f", "s16le", "-"], capture_output=True,
                         check=True).stdout
    samples = array.array("h", out)[int(start * rate):int(end * rate)]
    return math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))


def test_music_ducks_under_speech(media):
    tmp, p = media
    t = tracks(p)
    # Speech (the video's 440 Hz tone) in the first second only; music (880 Hz) throughout.
    t["main"]["clips"] = [vclip("v1", 0.0, 0.0), vclip("v2", 1.0, 1.0, volume=0)]
    t["music"]["clips"] = [{"id": "m", "type": "audio", "media": "tone", "start": 0.0,
                            "duration": 2.0, "in": 0.0, "out": 2.0, "volume": 0.5}]
    music = "bandpass=f=880:width_type=h:w=120,bandpass=f=880:width_type=h:w=120"
    levels = {}
    for ducking in (0, 1):
        p["settings"]["audio"]["ducking"] = ducking
        out = render_project(p, tmp / f"duck{ducking}.mp4", base_dir=tmp, export=FAST)
        levels[ducking] = (band_rms(out, music, 0.4, 0.9), band_rms(out, music, 1.4, 1.9))
    plain_speech, plain_quiet = levels[0]
    ducked_speech, ducked_quiet = levels[1]
    assert plain_speech == pytest.approx(plain_quiet, rel=0.25)       # no ducking: steady
    assert ducked_speech < ducked_quiet / 2.5                          # ducked while speaking
    assert ducked_quiet == pytest.approx(plain_quiet, rel=0.3)         # back up afterwards


def test_noise_reduction_lowers_hiss_and_keeps_the_voice(media):
    tmp, p = media
    noisy = tmp / "noisy.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex",
                    "color=c=gray:s=720x1280:r=30:d=3[v];"
                    # "Speech" with pauses (on 0.5 s, off 0.25 s) over steady hiss.
                    "sine=f=440:r=48000:d=3,volume='lt(mod(t,0.75),0.5)':eval=frame[s];"
                    "anoisesrc=d=3:c=white:a=0.05:r=48000[n];"
                    "[s][n]amix=inputs=2:normalize=0[a]",
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(noisy)], check=True)
    p["media"].append(media_from_file(noisy, "noisy"))
    tracks(p)["main"]["clips"] = [{"id": "n", "type": "video", "media": "noisy", "start": 0,
                                   "duration": 3, "in": 0, "out": 3}]
    hiss, voice = {}, {}
    for denoise in (0, 1):
        p["settings"]["audio"]["denoise"] = denoise
        out = render_project(p, tmp / f"dn{denoise}.mp4", base_dir=tmp, export=FAST)
        hiss[denoise] = band_rms(out, "highpass=f=3000,highpass=f=3000", 1.0, 2.8)
        voice[denoise] = band_rms(out, "bandpass=f=440:width_type=h:w=60", 1.0, 2.8)
    assert hiss[1] < hiss[0] / 5
    assert voice[1] > voice[0] * 0.6
