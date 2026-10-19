"""Picture effects of the Premium Editorial style, rendered with FFmpeg and checked pixel by pixel:
vignette, background dimming, the black-and-white transition, the smooth zoom-out, and overlays
with rounded corners, a soft shadow, a border and eased entrances / exits (a floating PiP)."""

import pytest

from autoedit.project import media_from_file, validate_project
from autoedit.project_render import (fitted_size, overlay_style_assets, render_project,
                                     zoom_factor, zoom_progress)
from tests import synthetic
from tests.test_project_render import FAST, fx_render, is_color, three_bands_video, tracks, vclip


@pytest.fixture
def media(tmp_path):
    """The same synthetic media as the render tests (a red/green/blue/white video, two pictures)."""
    from autoedit.project import new_project
    video = synthetic.make_color_video(tmp_path / "colors.mp4")
    yellow = synthetic.make_image(tmp_path / "yellow.png", color="yellow", size="600x400")
    magenta = synthetic.make_image(tmp_path / "magenta.png", color="magenta", size="200x200")
    p = new_project("test", normalize_audio=False)
    p["media"] = [media_from_file(video, "vid"), media_from_file(yellow, "yel"),
                  media_from_file(magenta, "mag")]
    return tmp_path, p


def brightness(rgb):
    return sum(rgb) / 3


# ---------------------------------------------------------------- vignette

def test_vignette_darkens_the_edges_only_while_it_is_on(media):
    tmp, p = media
    out = fx_render(tmp, p, "vig", [{"id": "v", "type": "vignette", "start": 1.0, "duration": 1.0,
                                     "strength": 1.0}])
    before_corner, = synthetic.pixels(out, [15], 30, 40)
    corner, centre = synthetic.pixels(out, [45], 30, 40)[0], synthetic.pixels(out, [45], 540, 960)[0]
    assert is_color(before_corner, "red")                        # not yet on: the corner is as it was
    assert is_color(centre, "green")                             # the middle keeps its colour
    assert brightness(corner) < brightness(centre) * 0.6         # the corner is dark


def test_vignette_fades_in(media):
    tmp, p = media
    out = fx_render(tmp, p, "vigfade", [{"id": "v", "type": "vignette", "start": 0.0, "duration": 2.0,
                                         "strength": 1.0, "fade": 0.6}])
    first, later = synthetic.pixels(out, [0, 27], 30, 40)
    assert brightness(first) > brightness(later) * 1.3


# ---------------------------------------------------------------- dimming

def test_dimming_darkens_the_picture_with_a_fade(media):
    tmp, p = media
    out = fx_render(tmp, p, "dim", [{"id": "d", "type": "dim", "start": 0.5, "duration": 1.2,
                                     "amount": 0.6, "fade": 0.3}])
    before, fading, full, after = synthetic.pixels(out, [5, 19, 36, 58], 540, 960)
    assert is_color(before, "red") and is_color(after, "green")
    assert full[1] < 0.5 * after[1] and full[1] > 0.25 * after[1]          # green, 60% darker
    assert full[0] < 40 and full[2] < 40
    assert 0.5 * 255 < fading[0] < 0.9 * 255                                  # part-way through the fade


def test_dimming_can_blur(media):
    tmp, p = media
    p["media"].append(media_from_file(three_bands_video(tmp / "bands.mp4"), "bands"))
    bands = [{"id": "b", "type": "video", "media": "bands", "start": 0.0, "duration": 2.0, "in": 0.0,
              "out": 2.0}]
    sharp = fx_render(tmp, p, "sharp", [{"id": "d", "type": "dim", "start": 0, "duration": 2,
                                         "amount": 0.1, "fade": 0}], main=bands)
    soft = fx_render(tmp, p, "soft", [{"id": "d", "type": "dim", "start": 0, "duration": 2,
                                       "amount": 0.1, "blur": 30, "fade": 0}], main=bands)
    edge_sharp, = synthetic.pixels(sharp, [30], 366, 960)
    edge_soft, = synthetic.pixels(soft, [30], 366, 960)
    assert edge_sharp[0] < 30                       # just inside the green band: no red
    assert edge_soft[0] > 40                        # blurred: the red band bleeds over the edge


# ---------------------------------------------------------------- black-and-white transition

def test_bw_transition_drains_the_colour_and_brings_it_back(media):
    tmp, p = media
    out = fx_render(tmp, p, "bw", [{"id": "b", "type": "fx", "effect": "bw", "start": 0.5,
                                    "duration": 1.0, "intensity": 1.0}])
    before, middle, after = synthetic.pixels(out, [10, 30, 59], 540, 960)
    assert is_color(before, "red")
    assert max(middle) - min(middle) < 25           # grey in the middle of the transition
    assert is_color(after, "green")                 # colour is back after it


# ---------------------------------------------------------------- zoom-out

def test_smooth_zoom_out_returns_to_the_wide_shot(media):
    tmp, p = media
    p["media"].append(media_from_file(three_bands_video(tmp / "bands.mp4"), "bands"))
    bands = [{"id": "b", "type": "video", "media": "bands", "start": 0.0, "duration": 2.0, "in": 0.0,
              "out": 2.0}]
    out = fx_render(tmp, p, "zoomout", [{"id": "z", "type": "zoom", "start": 0, "duration": 2,
                                         "amount": 1, "from": 2, "ease": 1.0, "smooth": True,
                                         "anchor_y": 0.5}], main=bands)
    start, end = synthetic.pixels(out, [0, 45], 330, 960)
    assert is_color(start, "green")                 # zoomed in 2x at first: the middle band
    assert is_color(end, "red")                     # back to the wide shot: the left band


def test_zoom_curves():
    assert zoom_progress(0.5, 0, 1, smooth=True) == pytest.approx(0.5)
    assert zoom_progress(0.25, 0, 1, smooth=True) < zoom_progress(0.25, 0, 1, smooth=False)
    assert zoom_factor(1, 1.0, 0, 1.4, True, 0) == pytest.approx(1.4)
    assert zoom_factor(1, 1.0, 0, 1.4, True, 2) == pytest.approx(1.0)


# ---------------------------------------------------------------- styled overlays

def styled_photo(**extra):
    return {"id": "o1", "type": "image", "media": "yel", "start": 0.0, "duration": 2.0,
            "x": 540, "y": 960, "width": 600, "height": 400, **extra}


def test_rounded_corners_shadow_and_border(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0)]
    t["photos"]["clips"] = [styled_photo(radius=80, shadow=1.0, border={"color": "#ffffff", "width": 8})]
    assert validate_project(p) == []
    out = render_project(p, tmp / "styled.mp4", base_dir=tmp, export=FAST)
    centre, corner, border, shadow, background = (synthetic.pixels(out, [10], x, y)[0] for x, y in
                                                  [(540, 960), (246, 766), (540, 758), (540, 1200),
                                                   (1000, 300)])
    assert is_color(centre, "yellow")
    assert not is_color(corner, "yellow")           # the corner is cut round
    assert min(border) > 200                        # a white line on the edge
    assert is_color(background, "red")
    assert brightness(shadow) < brightness(background) * 0.85    # a soft shadow below the picture


def test_overlay_slides_up_in_and_fades_out(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0)]
    t["photos"]["clips"] = [styled_photo(start=0.4, duration=1.6, enter="slide_up", exit="fade",
                                         motion=0.5)]
    out = render_project(p, tmp / "slide.mp4", base_dir=tmp, export=FAST)
    # t=0.8: 80% through the entrance, still ~17 px low (smoothstep), 80% opaque
    early_top, = synthetic.pixels(out, [24], 540, 768)       # above its (lowered) top edge
    early_low, = synthetic.pixels(out, [24], 540, 1170)      # below where its bottom will settle
    settled_top, = synthetic.pixels(out, [36], 540, 768)     # t=1.2: in place
    fading, = synthetic.pixels(out, [56], 540, 960)          # t=1.87: half faded out
    assert not is_color(early_top, "yellow") and is_color(early_low, "yellow")
    assert is_color(settled_top, "yellow")
    assert not is_color(fading, "yellow") and fading[1] > 120  # between yellow and the green background


def test_overlay_scales_in(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=2.0)]
    t["photos"]["clips"] = [styled_photo(enter="scale", motion=0.6)]
    out = render_project(p, tmp / "scale.mp4", base_dir=tmp, export=FAST)
    first, later = synthetic.pixels(out, [1, 30], 245, 960)  # near the left edge of the picture
    assert not is_color(first, "yellow") and is_color(later, "yellow")


def test_floating_video_pip_with_rounded_corners(media):
    tmp, p = media
    t = tracks(p)
    t["main"]["clips"] = [{"id": "m", "type": "video", "media": "vid", "start": 0.0, "duration": 1.0,
                           "in": 2.0, "out": 3.0}]                              # blue background
    t["photos"]["clips"] = [{"id": "pip", "type": "video", "media": "vid", "start": 0.0, "duration": 1.0,
                             "in": 0.0, "out": 1.0, "x": 760, "y": 520, "width": 400, "height": 700,
                             "radius": 48, "shadow": 0.6, "border": {"color": "#ffffff", "width": 6},
                             "enter": "slide_left", "exit": "fade", "motion": 0.3}]
    assert validate_project(p) == []
    out = render_project(p, tmp / "pip.mp4", base_dir=tmp, export=FAST)
    inside, = synthetic.pixels(out, [15], 760, 520)
    outside, = synthetic.pixels(out, [15], 200, 1500)
    assert is_color(inside, "red") and is_color(outside, "blue")


def test_style_assets_and_sizes(tmp_path):
    assert fitted_size(1920, 1080, 600, 600) == (600, 338)
    info = overlay_style_assets({"id": "x", "width": 600, "height": 400, "radius": 40, "shadow": 0.5},
                                600, 400, tmp_path)
    from PIL import Image
    mask = Image.open(info["mask"])
    assert mask.size == (600, 400) and mask.getpixel((0, 0)) == 0 and mask.getpixel((300, 200)) == 255
    under = Image.open(info["under"])
    assert under.size == (600 + 2 * info["margin"], 400 + 2 * info["margin"])
    assert info["over"] is None


@pytest.mark.parametrize("bad", [{"radius": -1}, {"shadow": 2}, {"enter": "spin"}, {"motion": 5},
                                 {"border": {"color": "white", "width": 2}}])
def test_bad_overlay_styles_are_refused(media, bad):
    _tmp, p = media
    tracks(p)["photos"]["clips"] = [styled_photo(**bad)]
    assert validate_project(p)


def test_bad_effect_values_are_refused(media):
    _tmp, p = media
    tracks(p)["effects"]["clips"] = [{"id": "d", "type": "dim", "start": 0, "duration": 1, "amount": 2}]
    assert validate_project(p)
    tracks(p)["effects"]["clips"] = [{"id": "v", "type": "vignette", "start": 0, "duration": 1, "strength": 3}]
    assert validate_project(p)
