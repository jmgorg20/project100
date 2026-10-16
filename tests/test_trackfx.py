"""Tracked effects rendered by the real engine (FFmpeg), checked on the pixels.

The source picture has a white marker at a known place, so "the glow lands on the point" is
measured against what the renderer really draws (through fill, reframe, blur fit, zooms,
speed and cuts), not against a formula in the test. Tracks are synthetic. How well MediaPipe
finds real hands on real footage is NOT tested here."""

import subprocess

import numpy as np
import pytest
from PIL import Image

from autoedit.project import media_from_file, new_project, validate_project
from autoedit.project_render import prepare_trackfx, render_frame, render_project
from autoedit.tracking import Point, Track
from tests import synthetic
from tests.test_integration import ffprobe

FPS = 30
MARK = (0.3, 0.6)


def project_with(tmp, width=720, height=1280, duration=4.0, marker=MARK):
    video = synthetic.make_marker_video(tmp / f"src_{width}x{height}.mp4", width, height, duration, marker)
    p = new_project("t", normalize_audio=False)
    p["media"] = [media_from_file(video, "vid")]
    t = {x["id"]: x for x in p["tracks"]}
    t["main"]["clips"] = [{"id": "v1", "type": "video", "media": "vid", "start": 0.0,
                           "duration": duration, "in": 0.0, "out": duration}]
    return p


def effects(p):
    return next(t for t in p["tracks"] if t["kind"] == "effect")["clips"]


def set_track(p, points, n=150):
    p["tracking"] = {"vid": Track(FPS, 0.0, {k: v for k, v in points.items()}).to_json()}


def still(u, v, n=150, c=0.95, s=None):
    return Point([u] * n, [v] * n, [c] * n, [s] * n if s is not None else None)


def moving(f, n=150, c=0.95, y=0.5):
    """x follows the SOURCE time: x = f(t)."""
    return Point([f(i / FPS) for i in range(n)], [y] * n, [c] * n)


def fx(cid="g", start=0.0, duration=4.0, effect="glow", **extra):
    return {"id": cid, "type": "trackfx", "start": start, "duration": duration, "effect": effect, **extra}


def png(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float32)


def frame(p, t, tmp, name="f"):
    out = tmp / f"{name}.png"
    render_frame(p, t, out, base_dir=tmp, work_dir=tmp / f"w_{name}")
    return png(out)


def without_effects(p):
    q = {**p, "tracks": [dict(t, clips=[c for c in t["clips"] if c["type"] != "trackfx"]) for t in p["tracks"]]}
    return q


def added(p, t, tmp, name="f"):
    """What the tracked effects add at time t: with minus without (RGB, 1080x1920)."""
    a = frame(p, t, tmp, name)
    b = frame(without_effects(p), t, tmp, name + "_base")
    return a - b


def centroid(img, threshold=12.0):
    """(x, y, total) of the light in an image (sum over channels above the threshold)."""
    lum = img.sum(axis=2)
    lum = np.where(lum > threshold, lum, 0.0)
    total = lum.sum()
    if total == 0:
        return None
    ys, xs = np.mgrid[0:lum.shape[0], 0:lum.shape[1]]
    return float((xs * lum).sum() / total), float((ys * lum).sum() / total), float(total)


def marker_position(p, t, tmp, name="m"):
    """Where the renderer puts the white marker (no effects): the brightest square's centre."""
    base = frame(without_effects(p), t, tmp, name)
    bright = np.where(base.min(axis=2) > 200, 1.0, 0.0)
    ys, xs = np.nonzero(bright)
    assert len(xs) > 20, "the marker is not in the picture"
    return float(xs.mean()), float(ys.mean())


@pytest.fixture
def tmp(tmp_path):
    return tmp_path


# ---- the glow lands where the track says ----------------------------------------------------

def test_glow_follows_a_moving_point_and_only_adds_light(tmp):
    p = project_with(tmp)
    set_track(p, {"right_palm": moving(lambda t: 0.2 + 0.15 * t)})
    effects(p).append(fx(effect="glow", point="palm", hand="right", smooth=0, intensity=1.0))
    for t in (0.7, 1.5, 2.6, 3.4):
        d = added(p, t, tmp)
        x, y, total = centroid(d)
        i = round(t * FPS)
        assert x == pytest.approx((0.2 + 0.15 * i / FPS) * 1080, abs=5), t
        assert y == pytest.approx(0.5 * 1920, abs=5), t
        assert d.min() > -3 and d.max() > 120          # light only: a glow never darkens (screen)
        assert total > 2_000_000


def test_colour_intensity_and_size(tmp):
    p = project_with(tmp)
    set_track(p, {"right_palm": still(0.5, 0.5)})
    effects(p).append(fx(point="palm", hand="right", color="#ff2200", intensity=1.0, smooth=0))
    d = added(p, 2.0, tmp, "a")
    body = d[960 - 6:960 + 6, 540 + 44:540 + 56].reshape(-1, 3).mean(0)             # beside the white-hot core
    assert body[0] > 100 and body[1] < body[0] * 0.5 and body[2] < body[0] * 0.2     # red
    full = centroid(d)[2]
    effects(p)[0]["intensity"] = 0.3
    weak = centroid(added(p, 2.0, tmp, "b"))[2]
    assert 0.05 * full < weak < 0.45 * full
    effects(p)[0].update(intensity=1.0, size=2.0)
    big = added(p, 2.0, tmp, "c")
    assert (big.sum(2) > 30).sum() > 2.2 * (d.sum(2) > 30).sum()


def test_each_effect_draws_around_its_point_and_is_repeatable(tmp):
    p = project_with(tmp)
    set_track(p, {"right_palm": still(0.4, 0.4), "face": still(0.5, 0.25, s=0.25),
                  "body": still(0.5, 0.55, s=0.6)})
    results = {}
    for effect, point in (("glow", "palm"), ("spark", "palm"), ("aura", "face"), ("aura", "body"),
                          ("energy", "palm")):
        effects(p)[:] = [fx(effect=effect, point=point, hand="right", smooth=0, intensity=1.0)]
        d = added(p, 2.0, tmp, "a")
        again = added(p, 2.0, tmp, "b")
        assert np.array_equal(d, again), f"{effect} is not repeatable"
        results[(effect, point)] = d
        assert centroid(d)[2] > 300_000, effect
    # Sparks scatter around the palm; an aura is a ring: dark in the middle, light on the outline.
    cx, cy, _ = centroid(results[("spark", "palm")])
    assert cx == pytest.approx(0.4 * 1080, abs=60) and cy == pytest.approx(0.4 * 1920, abs=60)
    face = results[("aura", "face")].sum(2)
    fx_, fy_ = int(0.5 * 1080), int(0.25 * 1920)
    ring_r = int(0.58 * 0.25 * 1080)                           # rx = 0.58 * face width
    assert face[fy_, fx_ + ring_r - 6:fx_ + ring_r + 6].max() > 3 * face[fy_ - 4:fy_ + 4, fx_ - 4:fx_ + 4].max()
    body = results[("aura", "body")].sum(2)
    assert body.shape == (1920, 1080)
    assert centroid(results[("aura", "body")])[1] == pytest.approx(0.55 * 1920, abs=60)
    # Fingertips: five glows in one effect.
    effects(p)[:] = [fx(effect="glow", point="fingertips", hand="right", smooth=0, intensity=1.0)]
    set_track(p, {f"right_{k}": still(0.3 + 0.1 * i, 0.5) for i, k in
                  enumerate(("thumb_tip", "index_tip", "middle_tip", "ring_tip", "pinky_tip"))})
    d = added(p, 2.0, tmp, "tips").sum(2)
    for i in range(5):
        assert d[960 - 4:960 + 4, int((0.3 + 0.1 * i) * 1080) - 4:int((0.3 + 0.1 * i) * 1080) + 4].max() > 150


def test_fading_in_and_out_with_the_clip(tmp):
    p = project_with(tmp)
    set_track(p, {"right_palm": still(0.5, 0.5)})
    effects(p).append(fx(start=1.0, duration=2.0, point="palm", hand="right", intensity=1.0, fade_in=0.5, fade_out=0.5))
    totals = {t: (centroid(added(p, t, tmp, f"t{t}")) or (0, 0, 0))[2] for t in (0.9, 1.05, 1.25, 2.0, 2.75, 2.95, 3.1)}
    assert totals[0.9] == 0 and totals[3.1] == 0                # nothing outside the clip
    assert totals[1.05] < 0.45 * totals[2.0] and totals[1.25] < totals[2.0]
    assert totals[2.95] < 0.4 * totals[2.0]


# ---- losing the point: fade out, no jumping --------------------------------------------------

def layer_frames(p, tmp):
    """The drawn effect layer as arrays (one per frame), via the engine's own function."""
    layer = prepare_trackfx(p, tmp, tmp / "layer_work" if (tmp / "layer_work").mkdir(exist_ok=True) is None else tmp)
    cmd = ["ffmpeg", "-v", "error", "-i", layer["path"], "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    from autoedit.trackfx import LH, LW
    n = len(raw) // (LW * LH * 3)
    return layer, [np.frombuffer(raw[i * LW * LH * 3:(i + 1) * LW * LH * 3], np.uint8).reshape(LH, LW, 3).astype(np.float32)
                   for i in range(n)]


def test_losing_the_point_fades_the_effect_out_in_place_and_it_comes_back(tmp):
    p = project_with(tmp)
    n = 150
    pt = moving(lambda t: 0.2 + 0.1 * t, n)
    for i in range(45, 105):                                   # lost for 2 s (frames 45-104)
        pt.c[i] = 0.0
        pt.x[i], pt.y[i] = 0.97, 0.97                          # garbage while lost
    set_track(p, {"right_palm": pt})
    effects(p).append(fx(point="palm", hand="right", smooth=0, intensity=1.0, fade_in=0.0, fade_out=0.0))
    layer, frames = layer_frames(p, tmp)
    bright = [f.sum() for f in frames]
    pos = [centroid(f, 8)[:2] if f.sum() > 3000 else None for f in frames]
    top = max(bright)
    assert bright[0] == 0 and bright[3] > 0.5 * top            # fades in at the start
    before = bright[44]
    assert before > 0.8 * top
    assert bright[44 + 6] < before * 0.8 and bright[44 + 12] < 0.1 * before     # fading, gone within ~0.4 s
    assert max(bright[44 + 15:104]) == 0                       # and stays gone
    # While it fades it stays where the point was (never the garbage 0.97).
    visible = [i for i in range(45, 60) if pos[i]]
    assert visible and all(abs(pos[i][0] - pos[44][0]) < 4 and abs(pos[i][1] - pos[44][1]) < 4 for i in visible)
    # Found again: fades back in at the new place, brighter and brighter.
    assert bright[105] < 0.3 * top and bright[112] > 0.9 * top
    back = pos[115]
    assert back[0] == pytest.approx((0.2 + 0.1 * 115 / FPS) * 540, abs=4)
    # No frame-to-frame jump while visible, anywhere.
    for i in range(1, len(frames)):
        if pos[i] and pos[i - 1] and min(bright[i], bright[i - 1]) > 0.15 * top:
            assert abs(pos[i][0] - pos[i - 1][0]) < 12 and abs(pos[i][1] - pos[i - 1][1]) < 12, i


def test_nothing_drawn_without_a_track_or_with_the_hand_missing(tmp):
    p = project_with(tmp)
    effects(p).append(fx(point="palm", hand="right"))
    assert centroid(added(p, 2.0, tmp, "a")) is None           # no tracking at all: no error, no effect
    set_track(p, {"left_palm": still(0.5, 0.5)})
    assert centroid(added(p, 2.0, tmp, "b")) is None           # only the other hand was found
    effects(p)[0]["hand"] = "left"
    assert centroid(added(p, 2.0, tmp, "c")) is not None
    effects(p)[0]["hand"] = "any"                              # "any" picks the hand that was found
    assert centroid(added(p, 2.0, tmp, "d")) is not None
    # A hidden effect track draws nothing.
    next(t for t in p["tracks"] if t["kind"] == "effect")["hidden"] = True
    assert prepare_trackfx(p, tmp, tmp) is None


# ---- the point lands where the picture really is: fill, reframe, zooms, speed, cuts ----------

def lands_on_marker(p, t, tmp, tol=6, name="x"):
    mx, my = marker_position(p, t, tmp, name + "m")
    d = added(p, t, tmp, name)
    c = centroid(d)
    assert c is not None, f"no effect at {t}s"
    assert c[0] == pytest.approx(mx, abs=tol) and c[1] == pytest.approx(my, abs=tol), (t, (mx, my), c[:2])


@pytest.mark.parametrize("crop", [None, {"zoom": 1.6, "x": 0.2, "y": 0.7}, {"zoom": 2.0, "x": 0.2, "y": 0.5}])
def test_follows_the_marker_through_fill_and_reframe(tmp, crop):
    p = project_with(tmp)
    if crop:
        p["tracks"][0]["clips"][0]["crop"] = crop
    set_track(p, {"right_palm": still(*MARK)})
    effects(p).append(fx(point="palm", hand="right", smooth=0))
    lands_on_marker(p, 1.5, tmp)


def test_follows_the_marker_with_a_wide_video_filled_and_blurred(tmp):
    for fit in ("fill", "blur"):
        p = project_with(tmp, width=1280, height=720, marker=(0.55, 0.4))
        p["tracks"][0]["clips"][0]["fit"] = fit
        set_track(p, {"right_palm": still(0.55, 0.4)})
        effects(p).append(fx(point="palm", hand="right", smooth=0))
        mx, my = marker_position(p, 1.5, tmp, "m" + fit)
        if fit == "fill":                                      # the sides are cropped: the marker is inside
            assert 0 < mx < 1080
        lands_on_marker(p, 1.5, tmp, name=fit)


def test_follows_the_marker_through_zoom_effects(tmp):
    p = project_with(tmp)
    set_track(p, {"right_palm": still(*MARK)})
    zoom = {"id": "z1", "type": "zoom", "start": 1.0, "duration": 1.5, "amount": 1.5, "anchor_y": 0.3}
    smooth = {"id": "z2", "type": "zoom", "start": 3.0, "duration": 1.0, "amount": 1.4, "anchor_y": 0.5, "ease": 0.6}
    zoom_track = {"id": "zoomt", "kind": "effect", "name": "Zoom", "clips": [zoom, smooth]}
    p["tracks"].append(zoom_track)
    effects(p).append(fx(point="palm", hand="right", smooth=0, size=0.35))   # small: not cut by the edge
    for t in (0.5, 1.4, 2.2, 3.1, 3.3, 3.8):                  # before, during a punch-in, during the ease
        lands_on_marker(p, t, tmp, name=f"z{t}")


def test_follows_through_speed_changes_and_cuts(tmp):
    """The point is read at the SOURCE time of each frame: a cut, a sped-up clip."""
    p = project_with(tmp, duration=6.0)
    main = p["tracks"][0]
    main["clips"] = [
        {"id": "a", "type": "video", "media": "vid", "start": 0.0, "duration": 1.0, "in": 3.0, "out": 4.0},
        {"id": "b", "type": "video", "media": "vid", "start": 1.0, "duration": 1.0, "in": 0.0, "out": 2.0, "speed": 2.0},
        {"id": "c", "type": "video", "media": "vid", "start": 2.0, "duration": 1.0, "in": 1.0, "out": 2.0},
    ]
    set_track(p, {"right_palm": moving(lambda t: 0.3 + 0.1 * t, 200)})
    effects(p).append(fx(duration=3.0, point="palm", hand="right", smooth=0, intensity=1.0, fade_in=0,
                         fade_out=0, size=0.4))
    for t in (0.5, 1.25, 1.75, 2.5):                              # timeline seconds
        i = round(t * FPS)
        # which source frame the renderer shows at timeline frame i
        clip = next(c for c in main["clips"] if c["start"] <= i / FPS + 1e-9 < c["start"] + c["duration"])
        src_t = clip["in"] + (i / FPS - clip["start"]) * clip.get("speed", 1.0)
        x, _y, _ = centroid(added(p, t, tmp, f"s{t}"))
        assert x == pytest.approx((0.3 + 0.1 * src_t) * 1080, abs=8), (t, src_t)


# ---- a clip of your own ---------------------------------------------------------------------

def make_effect_clips(tmp):
    black = tmp / "burst.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=320x320:r=30:d=2,drawbox=x=100:y=100:w=120:h=120:color=0xffcc33:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(black)], check=True)
    alpha = tmp / "alpha.mov"          # a 120 px square that is opaque; everything else transparent
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x33ccff:s=320x320:r=30:d=2",
                    "-f", "lavfi", "-i",
                    "color=c=black:s=320x320:r=30:d=2,drawbox=x=100:y=100:w=120:h=120:color=white:t=fill,format=gray",
                    "-filter_complex", "[0:v][1:v]alphamerge", "-c:v", "qtrle", "-pix_fmt", "argb", str(alpha)],
                   check=True)
    return black, alpha


def test_your_own_clip_is_screen_blended_at_the_point(tmp):
    black, alpha = make_effect_clips(tmp)
    p = project_with(tmp)
    p["media"] += [media_from_file(black, "burst"), media_from_file(alpha, "alpha")]
    set_track(p, {"right_palm": still(0.4, 0.4)})
    effects(p).append(fx(effect="clip", media="burst", duration=2.0, point="palm", hand="right", smooth=0,
                         intensity=1.0, fade_in=0, fade_out=0))
    d = added(p, 1.0, tmp, "a")
    x, y, total = centroid(d)
    assert x == pytest.approx(0.4 * 1080, abs=6) and y == pytest.approx(0.4 * 1920, abs=6)
    assert d.min() > -3
    patch = d[int(0.4 * 1920) - 5:int(0.4 * 1920) + 5, int(0.4 * 1080) - 5:int(0.4 * 1080) + 5].reshape(-1, 3).mean(0)
    assert patch[0] > 200 and 150 < patch[1] < 230 and patch[2] < 90          # the clip's 0xffcc33
    # The black around the square adds nothing: the square is about 0.35 * 1080 * (120 / 320) wide.
    side = 0.35 * 1080 * 120 / 320
    lit = (d.sum(2) > 60)
    ys, xs = np.nonzero(lit)
    assert (xs.max() - xs.min()) == pytest.approx(side, abs=14) and (ys.max() - ys.min()) == pytest.approx(side, abs=14)
    # It ends when the clip ends (the clip is 2 s, the effect runs to 3 s): nothing after.
    effects(p)[0]["duration"] = 3.0
    assert centroid(added(p, 2.5, tmp, "b")) is None
    # With a colour, the clip is tinted.
    effects(p)[0]["color"] = "#00ff00"
    tinted = added(p, 1.0, tmp, "c")
    tp = tinted[int(0.4 * 1920) - 5:int(0.4 * 1920) + 5, int(0.4 * 1080) - 5:int(0.4 * 1080) + 5].reshape(-1, 3).mean(0)
    assert tp[1] > 150 and tp[0] < 5 and tp[2] < 5
    # A clip with its own alpha: only the opaque square adds light.
    effects(p)[0].update(media="alpha", blend="alpha", duration=2.0)
    effects(p)[0].pop("color")
    d2 = added(p, 1.0, tmp, "d")
    lit = d2.sum(2) > 60
    ys, xs = np.nonzero(lit)
    assert (xs.max() - xs.min()) == pytest.approx(side, abs=14)
    patch = d2[int(0.4 * 1920) - 5:int(0.4 * 1920) + 5, int(0.4 * 1080) - 5:int(0.4 * 1080) + 5].reshape(-1, 3).mean(0)
    assert patch[2] > 200 and patch[0] < 90


# ---- the whole export ------------------------------------------------------------------------

def test_the_export_has_the_effect_and_the_same_length_and_sound(tmp):
    p = project_with(tmp, duration=3.0)
    set_track(p, {"right_palm": still(0.5, 0.5)})
    effects(p).append(fx(start=0.5, duration=2.0, point="palm", hand="right", smooth=0, intensity=1.0))
    plain = render_project(without_effects(p), tmp / "plain.mp4", base_dir=tmp, work_dir=tmp / "w1",
                           export={"encoder_speed": "ultrafast", "crf": 18})
    full = render_project(p, tmp / "full.mp4", base_dir=tmp, work_dir=tmp / "w2",
                          export={"encoder_speed": "ultrafast", "crf": 18})
    v1, a1, d1 = ffprobe(plain)
    v2, a2, d2 = ffprobe(full)
    assert int(v2["nb_frames"]) == int(v1["nb_frames"]) == 90
    assert (v2["width"], v2["height"]) == (1080, 1920)
    assert float(a2[0]["duration"]) == pytest.approx(float(a1[0]["duration"]), abs=0.05)
    pix = synthetic.pixels(full, [10, 45, 80], 540, 960)         # before, during, after
    assert max(pix[0]) < 60 and pix[1][0] > 150 and max(pix[2]) < 60
    # The same picture as the single-frame render, within video compression.
    exact = frame(p, 45 / FPS, tmp, "exact")
    sample = np.asarray(Image.open(_frame_png(full, 45, tmp)).convert("RGB")).astype(np.float32)
    assert np.abs(sample - exact).mean() < 4


def _frame_png(video, n, tmp):
    out = tmp / f"vid{n}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select=eq(n\\,{n})", "-frames:v", "1", str(out)],
                   check=True)
    return out


# ---- the project file ------------------------------------------------------------------------

def test_the_project_format_accepts_and_checks_tracked_effects(tmp):
    p = project_with(tmp)
    set_track(p, {"right_palm": still(0.5, 0.5), "face": still(0.5, 0.3, s=0.2)})
    effects(p).append(fx(point="fingertips", hand="left", intensity=0.5, color="#33ccff", size=1.5, smooth=0.3,
                         fade_in=0.1, fade_out=0.2))
    assert validate_project(p) == []
    bad = fx("b", effect="clip")                                  # a clip effect needs a clip
    effects(p).append(bad)
    assert any("media" in x for x in validate_project(p))
    effects(p)[-1] = fx("b", effect="glow", media="vid")          # others must not have one
    assert validate_project(p)
    effects(p)[-1] = fx("b", effect="glow", point="elbow")
    assert validate_project(p)
    effects(p).pop()
    p["tracking"]["nope"] = p["tracking"]["vid"]
    assert any("unknown media 'nope'" in x for x in validate_project(p))
    del p["tracking"]["nope"]
    p["tracking"]["vid"]["points"]["face"]["y"] = [0.1]
    assert any("same length" in x for x in validate_project(p))
    # Old projects (no tracking at all) still validate and render.
    q = project_with(tmp)
    assert "tracking" not in q and validate_project(q) == []
