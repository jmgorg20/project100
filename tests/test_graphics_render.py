"""Motion graphics drawn by Chromium and laid over the picture by FFmpeg: checked on the pixels."""

import numpy as np
import pytest
from PIL import Image

from autoedit import graphics
from autoedit.project import media_from_file, new_project, validate_project
from autoedit.project_render import render_frame, render_project
from tests import synthetic
from tests.gfx_helpers import add_graphics_track, graphic, needs_chromium

pytestmark = needs_chromium
FAST = {"encoder_speed": "ultrafast", "crf": 14}


@pytest.fixture
def red(tmp_path):
    """A project with 3 s of plain red (30 fps) as the main video."""
    import subprocess
    video = tmp_path / "red.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=720x1280:r=30:d=3", "-f", "lavfi", "-i",
                    "sine=f=440:r=48000:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(video)], check=True)
    p = new_project("g", normalize_audio=False)
    p["media"] = [media_from_file(video, "vid")]
    p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "vid", "start": 0,
                                "duration": 3, "in": 0, "out": 3}]
    return tmp_path, p


def frame_png(tmp_path, project, seconds, name="f.png"):
    out = tmp_path / name
    render_frame(project, seconds, out, base_dir=tmp_path)
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def not_red(img):
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    return ~((r > 200) & (g < 60) & (b < 60))


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return xs.min(), ys.min(), xs.max(), ys.max()


def test_graphic_appears_for_exactly_its_frames(red):
    tmp, p = red
    add_graphics_track(p, [graphic("g1", "icon-badge", 0.5, 1.0, text="Fast", icon="bolt")])
    assert validate_project(p) == []
    out = tmp / "out.mp4"
    render_project(p, out, base_dir=tmp, export=FAST)
    for second, expect in ((0.4, False), (1.0, True), (1.6, False)):
        n = round(second * 30)
        img = frame_png_from_video(tmp, out, n)
        assert bool(not_red(img[760:1160, 300:780]).sum() > 500) is expect, second


def frame_png_from_video(tmp, video, n):
    import subprocess
    png = tmp / f"v{n}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select='eq(n,{n})'",
                    "-frames:v", "1", "-update", "1", str(png)], check=True)
    return np.asarray(Image.open(png).convert("RGB")).astype(int)


@pytest.mark.parametrize("x,y", [(0.5, 0.5), (0.25, 0.75), (0.8, 0.2)])
def test_graphic_sits_where_x_y_say(red, x, y):
    tmp, p = red
    add_graphics_track(p, [graphic("g1", "icon-badge", 0.0, 2.0, x=x, y=y, text="Fast", icon="bolt")])
    img = frame_png(tmp, p, 1.2)
    box = bbox(not_red(img))
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    assert abs(cx - x * 1080) < 40 and abs(cy - y * 1920) < 40, (cx, cy)
    assert 150 < box[2] - box[0] < 700


def test_the_same_graphic_is_drawn_once(red):
    tmp, p = red
    add_graphics_track(p, [graphic("g1", "stamp", 0, 1, text="Approved"),
                           graphic("g2", "stamp", 1.5, 1, text="Approved")])
    jobs = graphics.project_jobs(p, tmp)
    assert len(jobs) == 1


def test_changing_text_changes_the_cache_key(red):
    tmp, p = red
    a = graphics.project_jobs(add_graphics_track(p, [graphic("g1", "stamp", 0, 1, text="A")]), tmp)
    p["tracks"][-1]["clips"][0]["params"]["text"] = "B"
    b = graphics.project_jobs(p, tmp)
    assert a[0]["key"] != b[0]["key"]
    p["tracks"][-1]["clips"][0]["params"]["text"] = "A"
    p["tracks"][-1]["clips"][0]["start"] = 0.7        # moving it does not redraw it
    assert graphics.project_jobs(p, tmp)[0]["key"] == a[0]["key"]
    p["tracks"][-1]["clips"][0]["duration"] = 1.5     # a different length does
    assert graphics.project_jobs(p, tmp)[0]["key"] != a[0]["key"]


def test_second_render_uses_the_cache(red, monkeypatch):
    tmp, p = red
    add_graphics_track(p, [graphic("g1", "emoji-pop", 0, 1, emoji="🔥")])
    graphics.ensure_assets(p, tmp)
    calls = []
    monkeypatch.setattr(graphics, "draw_jobs", lambda jobs, *a, **k: calls.append(jobs))
    assert graphics.ensure_assets(p, tmp) == [] and calls == []


def test_missing_renderer_is_a_clear_error_or_skipped(red, monkeypatch, tmp_path):
    tmp, p = red
    add_graphics_track(p, [graphic("g1", "emoji-pop", 0, 1, emoji="💥")])
    monkeypatch.setenv("AUTOEDIT_GRAPHICS_CACHE", str(tmp_path / "empty-cache"))
    monkeypatch.setattr(graphics, "renderer_command", lambda: None)
    with pytest.raises(Exception, match="graphics"):
        graphics.ensure_assets(p, tmp)
    left = graphics.ensure_assets(p, tmp, mode="skip")
    assert len(left) == 1


def test_image_param_is_drawn(red):
    tmp, p = red
    pic = synthetic.make_image(tmp / "blue.png", color="blue", size="400x400")
    p["media"].append(media_from_file(pic, "pic"))
    add_graphics_track(p, [graphic("g1", "polaroid-card", 0, 2, image="pic", text="hi")])
    assert validate_project(p) == []
    img = frame_png(tmp, p, 1.0)
    blue = (img[..., 2] > 180) & (img[..., 0] < 60) & (img[..., 1] < 60)
    assert blue.sum() > 20000          # the photo area is blue


def test_before_after_wipe_grades_one_side(red):
    tmp, p = red
    p["tracks"][2]["clips"].append({"id": "w1", "type": "wipe", "start": 0.5, "duration": 2.0,
                                    "grade": "black_and_white", "sweep": 0.5, "stop": 0.5})
    assert validate_project(p) == []
    before = frame_png(tmp, p, 0.3)
    after = frame_png(tmp, p, 1.5)
    assert before[960, 100, 0] > 200 and before[960, 100, 1] < 60        # still red
    left, right = after[960, 100], after[960, 900]
    assert abs(left[0] - left[1]) < 25 and abs(left[1] - left[2]) < 25   # graded side is gray
    assert right[0] > 200 and right[1] < 60                              # the other side is red
    line = after[960, 535:545]
    assert (line.min(axis=1) > 230).any()                                # the white divider


def test_attached_flash_brightens_the_start_frames(red):
    tmp, p = red
    clip = graphic("g1", "icon-badge", 1.0, 1.0, text="Hi", icon="bolt")
    clip["attach"] = {"kind": "flash", "intensity": 1.0}
    add_graphics_track(p, [clip])
    assert validate_project(p) == []
    during = frame_png(tmp, p, 1.0 + 1 / 30, "a.png")
    later = frame_png(tmp, p, 1.8, "b.png")
    corner = (slice(20, 60), slice(20, 60))
    assert during[corner][..., 1].mean() > later[corner][..., 1].mean() + 30


def test_attached_punch_zooms_the_picture(red):
    tmp, p = red
    video = synthetic.make_video(tmp / "talk.mp4", duration=3)
    p["media"].append(media_from_file(video, "talk"))
    p["tracks"][0]["clips"][0].update({"media": "talk"})
    clip = graphic("g1", "stamp", 1.0, 1.0, x=0.5, y=0.9, text="Hi")
    clip["attach"] = {"kind": "punch", "intensity": 1.0}
    add_graphics_track(p, [clip])
    assert validate_project(p) == []
    with_punch = frame_png(tmp, p, 1.3, "a.png")
    del p["tracks"][-1]["clips"][0]["attach"]
    without = frame_png(tmp, p, 1.3, "b.png")
    assert np.abs(with_punch[:1000] - without[:1000]).mean() > 3
