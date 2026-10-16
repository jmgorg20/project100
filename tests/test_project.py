"""Project file: schema, validation messages, saving, and the timeline maths (no FFmpeg)."""

import copy
import dataclasses
import json

import pytest

from autoedit.captions import ZONES, build_ass, fonts_from_config
from autoedit.config import DEFAULTS
from autoedit.errors import EditorError
from autoedit.grades import GRADES
from autoedit.highlight import mark_keywords
from autoedit.pipeline import caption_groups
from autoedit.project import (ProjectError, assign_lanes, check_project, load_project,
                              load_schema, new_project, save_project, timeline_duration,
                              validate_project)
from autoedit.project_render import (build_project_ass, frame_index, frames_expression,
                                     main_segments, media_by_id)
from autoedit.styles import STYLES, CaptionStyle
from autoedit.words import make_word

from tests.test_captions import FONTS_DIR, sample_words


def sample_project():
    p = new_project("test")
    p["media"] = [
        {"id": "m1", "kind": "video", "path": "talk.mp4", "duration": 10.0,
         "width": 720, "height": 1280, "has_audio": True},
        {"id": "m2", "kind": "image", "path": "photo.png", "duration": 0, "width": 600,
         "height": 400},
        {"id": "m3", "kind": "audio", "path": "music.mp3", "duration": 30.0},
    ]
    tracks = {t["id"]: t for t in p["tracks"]}
    tracks["main"]["clips"] = [
        {"id": "v1", "type": "video", "media": "m1", "start": 0, "duration": 2, "in": 1, "out": 3},
        {"id": "v2", "type": "video", "media": "m1", "start": 2, "duration": 1.5, "in": 4,
         "out": 5.5, "volume": 0.8},
    ]
    tracks["photos"]["clips"] = [
        {"id": "o1", "type": "image", "media": "m2", "start": 0.5, "duration": 1, "x": 500,
         "y": 520, "width": 820, "height": 560, "animation": "pop"}]
    tracks["effects"]["clips"] = [
        {"id": "z1", "type": "zoom", "start": 1, "duration": 1, "amount": 1.2},
        {"id": "g1", "type": "grade", "start": 2, "duration": 1, "grade": "warm"}]
    tracks["captions"]["clips"] = [
        {"id": "t1", "type": "caption", "start": 0, "duration": 1.2, "style": "yellow_pop",
         "words": [{"text": "Kumusta", "start": 0, "end": 0.5},
                   {"text": "GitHub", "start": 0.6, "end": 1.0, "highlight": True}]}]
    tracks["music"]["clips"] = [
        {"id": "a1", "type": "audio", "media": "m3", "start": 0, "duration": 3.5, "in": 0,
         "out": 3.5, "volume": 0.3, "fade_in": 0.5, "fade_out": 1}]
    return p


def problems_for(change):
    p = sample_project()
    change(p)
    return validate_project(p)


def track(p, track_id):
    return next(t for t in p["tracks"] if t["id"] == track_id)


# ------------------------------------------------------------ schema and validation

def test_sample_and_empty_projects_are_valid():
    assert validate_project(sample_project()) == []
    assert validate_project(new_project()) == []
    assert timeline_duration(sample_project()) == pytest.approx(3.5)


def test_schema_lists_match_the_engine():
    """The schema (shared with the desktop app) must offer exactly what the engine supports."""
    defs = load_schema()["$defs"]
    assert defs["gradeClip"]["properties"]["grade"]["enum"] == list(GRADES)
    styles = defs["captionClip"]["properties"]["style"]["anyOf"]
    assert styles[0]["enum"] == [s.name for s in STYLES]
    assert styles[1]["maximum"] == len(STYLES)
    overrides = defs["captionClip"]["properties"]["overrides"]["properties"]
    assert overrides["zone"]["enum"] == list(ZONES)
    fields = {f.name for f in dataclasses.fields(CaptionStyle)}
    assert set(overrides) <= fields


@pytest.mark.parametrize("change, message", [
    (lambda p: p.update(format="something"), "not a project file"),
    (lambda p: p.update(version=2), "newer version"),
    (lambda p: p.pop("tracks"), "'tracks' is a required property"),
    (lambda p: p.update(extra=1), "Additional properties"),
    (lambda p: p["settings"].update(fps=29.97), "settings.fps"),
    (lambda p: p["settings"].update(width=1920), "settings.width"),
    (lambda p: track(p, "main")["clips"][0].update(media="nope"), "unknown media 'nope'"),
    (lambda p: track(p, "main")["clips"][0].update(media="m2"), "needs video media"),
    (lambda p: track(p, "main")["clips"][1].update(start=1.5), "overlaps clip 'v1'"),
    (lambda p: track(p, "main")["clips"][0].update(out=4), "must equal the duration"),
    (lambda p: track(p, "main")["clips"][0].update({"in": 9, "out": 11}), "past the end"),
    (lambda p: track(p, "main")["clips"][0].update(out=0.5), "must be after 'in'"),
    (lambda p: track(p, "main")["clips"][0].update(volume=9), "volume"),
    (lambda p: track(p, "main")["clips"][0].update(duration=0), "duration"),
    (lambda p: track(p, "photos")["clips"][0].update(id="v1"), "clip id is used twice"),
    (lambda p: p["media"].append(dict(p["media"][0])), "id 'm1' is used twice"),
    (lambda p: p["tracks"].append({"id": "main2", "kind": "video", "clips": []}),
     "only one main video track"),
    (lambda p: track(p, "captions")["clips"][0]["words"][1].update(end=2.0),
     "ends after the caption clip"),
    (lambda p: track(p, "captions")["clips"][0]["words"].reverse(), "time order"),
    (lambda p: track(p, "captions")["clips"][0].update(style="comic_sans"), "style"),
    (lambda p: track(p, "captions")["clips"][0].update(overrides={"size": 5}), "size"),
    (lambda p: track(p, "effects")["clips"][1].update(grade="sepia"), "grade"),
    (lambda p: track(p, "effects")["clips"][0].update(amount=6), "amount"),
    (lambda p: track(p, "photos")["clips"][0].update(width=0.4), "width"),
    (lambda p: track(p, "music")["clips"][0].update(fade_in=3), "fade in + fade out"),
    (lambda p: track(p, "music").pop("role"), "'role' is a required property"),
    (lambda p: track(p, "main").update(role="music"), "should not be valid"),
    (lambda p: track(p, "photos")["clips"][0].update(type="video"), "'in' is a required"),
    (lambda p: track(p, "main")["clips"][0].update(layout={"type": "split", "screen": "m2"}),
     "is not a video"),
    (lambda p: p.update(transcript={"media": "zz", "language": "tl", "words": []}),
     "transcript: unknown media"),
])
def test_validation_finds_problems(change, message):
    problems = problems_for(change)
    assert problems, "expected a problem"
    assert any(message in prob for prob in problems), problems


def test_check_project_raises_with_every_problem():
    p = sample_project()
    track(p, "main")["clips"][0]["media"] = "nope"
    track(p, "music")["clips"][0]["fade_in"] = 3
    with pytest.raises(ProjectError) as info:
        check_project(p)
    assert len(info.value.problems) == 2
    assert "unknown media" in str(info.value) and "fade in" in str(info.value)
    assert isinstance(info.value, EditorError)


def test_save_and_load_round_trip(tmp_path):
    p = sample_project()
    path = save_project(p, tmp_path / "sub" / "my.project.json")
    assert load_project(path) == p
    assert not list((tmp_path / "sub").glob("*.tmp"))
    bad = copy.deepcopy(p)
    bad["tracks"][0]["clips"][0]["media"] = "nope"
    with pytest.raises(ProjectError):
        save_project(bad, path)                     # an invalid project is never written
    assert load_project(path) == p
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(EditorError, match="not valid JSON"):
        load_project(path)
    with pytest.raises(EditorError, match="not found"):
        load_project(tmp_path / "missing.project.json")


def test_schema_file_is_valid_json_schema():
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(load_schema())


# ------------------------------------------------------------ timeline maths

def test_frame_index_and_expressions():
    assert frame_index(1.5, 30) == 45
    assert frame_index(0.0166, 30) == 0 and frame_index(0.0167, 30) == 1
    assert frame_index(4.1, 30) == 123
    # Frames 45..59 are on: t >= 1.4833 and t < 1.9833.
    assert frames_expression([(45, 60)], 30) == "gte(t,1.4833)*lt(t,1.9833)"
    assert frames_expression([], 30) == "0"


def test_assign_lanes_keeps_overlaps_apart():
    items = [{"start": 0, "duration": 2}, {"start": 1, "duration": 1},
             {"start": 2, "duration": 1}, {"start": 1.5, "duration": 1}]
    lanes = assign_lanes(items)
    assert [[i["start"] for i in lane] for lane in lanes] == [[0, 2], [1], [1.5]]


def segments_for(clips, media_kind="video", total=None):
    p = new_project()
    p["media"] = [{"id": "m1", "kind": media_kind, "path": "a.mp4", "duration": 100.0},
                  {"id": "m2", "kind": "image", "path": "b.png", "duration": 0}]
    p["tracks"][0]["clips"] = clips
    check_project(p)
    fps = 30
    total = total or frame_index(timeline_duration(p), fps)
    return main_segments(p, media_by_id(p), fps, total)


def vclip(cid, start, duration, src, **extra):
    return {"id": cid, "type": "video", "media": "m1", "start": start, "duration": duration,
            "in": src, "out": src + duration, **extra}


def test_forward_cuts_of_one_video_are_one_run():
    """What the auto edit makes (cut pieces in order) renders in a single pass."""
    segs = segments_for([vclip("a", 0, 1, 0.5), vclip("b", 1, 2, 3.0), vclip("c", 3, 1, 7.25)])
    assert [s.kind for s in segs] == ["run"]
    assert segs[0].frames == 120
    # Source starts snap to whole frames: 7.25s is frame 217.5, so it plays from frame 218.
    assert segs[0].sources == [(0.5, 30), (3.0, 60), (pytest.approx(218 / 30), 30)]


def test_runs_split_on_reorder_gap_volume_and_image():
    segs = segments_for([
        vclip("a", 0, 1, 5.0),
        vclip("b", 1, 1, 2.0),                     # goes back in the source: new run
        vclip("c", 2, 1, 3.0, volume=0.5),         # different volume: new run
        vclip("d", 3.5, 1, 4.0, volume=0.5),       # after a gap: new run
        {"id": "e", "type": "image", "media": "m2", "start": 4.5, "duration": 0.5},
    ], total=frame_index(6.0, 30))
    assert [(s.kind, s.frames) for s in segs] == [
        ("run", 30), ("run", 30), ("run", 30), ("gap", 15), ("run", 30), ("image", 15),
        ("gap", 30)]
    assert sum(s.frames for s in segs) == 180


def test_muted_main_track_silences_runs():
    p_clips = [vclip("a", 0, 1, 0)]
    p = new_project()
    p["media"] = [{"id": "m1", "kind": "video", "path": "a.mp4", "duration": 5.0}]
    p["tracks"][0]["clips"] = p_clips
    p["tracks"][0]["muted"] = True
    assert main_segments(p, media_by_id(p), 30, 30)[0].volume == 0.0


# ------------------------------------------------------------ captions conversion

@pytest.mark.parametrize("style", STYLES, ids=lambda s: s.name)
def test_caption_clips_render_exactly_like_the_original_captions(style):
    """Turning captions into clips (one per group) must not change a single subtitle line."""
    words = sample_words()
    length = words[-1].end + 1
    clips = caption_groups(words, style, length)
    for i, clip in enumerate(clips):
        clip["id"] = f"t{i}"
    p = new_project()
    p["tracks"][3]["clips"] = clips
    check_project(p)
    fonts = fonts_from_config(DEFAULTS["captions"])
    assert build_project_ass(p, FONTS_DIR) == build_ass(words, style, fonts,
                                                        fonts_folder=FONTS_DIR)


def test_caption_overrides_and_keyword_toggle():
    words = mark_keywords([make_word(t, i * 0.4, i * 0.4 + 0.3)
                           for i, t in enumerate("presyo 500 pesos lang".split())],
                          DEFAULTS["highlight"])
    style = next(s for s in STYLES if s.name == "boxed")
    clip = caption_groups(words, style, 5)[0]
    clip.update(id="t1", overrides={"size": 99, "zone": "top"})
    p = new_project()
    p["tracks"][3]["clips"] = [clip]
    check_project(p)
    ass = build_project_ass(p, FONTS_DIR)
    assert "Style: Main,Inter,99," in ass and r"\an8" in ass       # bigger, at the top
    assert "&H0000E6FF" in ass                                     # keyword colour used
    clip["highlight_keywords"] = False
    assert "&H0000E6FF" not in build_project_ass(p, FONTS_DIR)


def test_two_caption_styles_get_separate_ass_styles():
    p = new_project()
    word = [{"text": "Hello", "start": 0, "end": 0.5}]
    p["tracks"][3]["clips"] = [
        {"id": "t1", "type": "caption", "start": 0, "duration": 1, "style": "classic",
         "words": word},
        {"id": "t2", "type": "caption", "start": 1, "duration": 1, "style": 4, "words": word}]
    ass = build_project_ass(p, FONTS_DIR)
    assert "Style: Main," in ass and "Style: Main2," in ass
    assert ",Main2,,0,0,0,,{" in ass and "HELLO" in ass             # bold_caps is uppercase


def test_no_caption_clips_means_no_subtitle_file():
    assert build_project_ass(new_project(), FONTS_DIR) is None


def test_project_json_is_plain_json():
    p = sample_project()
    assert json.loads(json.dumps(p)) == p


def test_example_project_in_the_docs_is_valid():
    from autoedit import PROJECT_DIR
    assert load_project(PROJECT_DIR / "examples" / "project.json")["name"] == "Example"
