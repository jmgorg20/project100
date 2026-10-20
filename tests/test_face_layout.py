"""Cards never on the face (the real Windows run had cards over it): a built-in face finder with no
setup, the "speaker lower" layout (the speaker eases into the lower part of the frame while a card
takes the top, as in the reference) and placement that keeps every card off the moved face."""

import json

import pytest

from autoedit import director, editorial, face_detect, graphics, zones
from autoedit.errors import EditorError
from autoedit.project_render import layout_scale_at
from autoedit.tracking import Point, Track
from autoedit.words import load_transcript
from tests import synthetic
from tests.director_helpers import make_project
from tests.test_editorial_director import cfg, graphics_of, run
from tests.test_project_render import fx_render
from tests.test_editorial_effects import brightness, media  # noqa: F401  (fixture)

REAL = "tests/data/realclip/groq_words.json"


def test_speaker_low_moves_the_picture_down_over_a_blurred_darker_copy(media):  # noqa: F811
    tmp, p = media
    out = fx_render(tmp, p, "layout", [{"id": "l", "type": "layout", "mode": "speaker_low", "start": 0.8,
                                        "duration": 1.0, "scale": 0.62, "fade": 0.2}])
    (before_side,), = [synthetic.pixels(out, [5], 20, 1500)]
    side, speaker, top = (synthetic.pixels(out, [40], x, y)[0] for x, y in [(20, 1500), (540, 1500), (540, 200)])
    assert brightness(before_side) > 0.9 * brightness(speaker)   # before: the full shot
    assert brightness(side) < 0.9 * brightness(speaker)           # the edge beside the moved speaker: darker copy
    assert brightness(top) < 0.9 * brightness(speaker)            # the top: the darker copy, free for a card


def test_the_layout_scale_eases_down_and_back():
    p = {"tracks": [{"id": "fx", "kind": "effect", "clips": [
        {"id": "l", "type": "layout", "mode": "speaker_low", "start": 1.0, "duration": 2.0, "scale": 0.6, "fade": 0.4}]}]}
    assert layout_scale_at(p, 0.5) == 1.0 and layout_scale_at(p, 2.0) == pytest.approx(0.6)
    assert 0.6 < layout_scale_at(p, 1.2) < 1.0 and layout_scale_at(p, 3.5) == 1.0


def real_words():
    return [{"text": w.text, "start": w.start, "end": w.end} for w in load_transcript(REAL)]


def face_track(duration, x=0.5, y=0.3, size=0.45):
    n = int(duration * 4) + 2
    return Track(4.0, 0.0, {"face": Point([x] * n, [y] * n, [0.9] * n, [size] * n)},
                 source="opencv-haar").to_json(["face"])


@pytest.mark.parametrize("known", [True, False])
def test_no_card_covers_the_face_on_the_real_words(tmp_path, known):
    """The real run's words: every card, from the countdown to the profile card, is placed off the
    face (where the face finder saw it, or where a talking head's face is when it found nothing)."""
    words = real_words()
    p = make_project(words, caption_style="editorial_card")
    if known:
        p["tracking"] = {p["tracks"][0]["clips"][0]["media"]: face_track(words[-1]["end"] + 1)}
    shots = [synthetic.make_image(tmp_path / n, color="blue", size="900x600") for n in ("search_results.png",
                                                                                      "profile_photo.png")]
    from autoedit.project import media_from_file
    for i, path in enumerate(shots):
        p["media"].append(media_from_file(path, f"up{i}"))
    r = run(p, cfg())
    out = r["project"]
    layouts = [c for t in out["tracks"] for c in t["clips"] if c["type"] == "layout"]
    assert layouts and all(c["mode"] == "speaker_low" for c in layouts)
    face = zones.FaceMap(out)
    assert face.known is known
    shown = graphics_of(out)
    assert {"countdown-timer", "editorial-checklist", "stat-cards", "search-bar"} <= {c["template"] for c in shown}
    for c in shown:
        box = graphics.estimated_box(c)
        assert not zones.intersects(box, face.rect(c["start"], c["start"] + c["duration"])), (c["template"], box)
        # while a card is up the speaker is lower (a layout covers the card's whole time)
        if c["template"] != "label-pill":
            assert any(l["start"] <= c["start"] + 1e-3 and c["start"] + c["duration"] <= l["start"] + l["duration"] + 1e-3
                       for l in layouts), (c["template"], c["start"], c["duration"], [(l["start"], l["duration"]) for l in layouts])


def test_the_face_finder_keeps_the_speaker_and_drops_a_logo_on_the_shirt():
    face = (0.5, 0.3, 0.45)
    raw = [face] * 6 + [None, None] + [(0.65, 0.6, 0.15)] + [face] * 6 + [None] * 12 + [face] * 3
    xs, ys, cs, ss = face_detect.clean_samples(raw)
    assert len(xs) == len(raw)
    assert all(abs(x - 0.5) < 1e-6 and abs(y - 0.3) < 1e-6 for x, y in zip(xs, ys))   # the logo is not the face
    assert cs[7] == 0.6 and cs[8] == 0.6                      # a short gap is filled from its neighbours
    assert min(cs) >= 0.55                                    # a long one keeps the usual place
    with pytest.raises(EditorError):
        face_detect.clean_samples([None] * 20 + [face])


def test_without_mediapipe_the_built_in_face_finder_is_used(monkeypatch):
    words = real_words()
    p = make_project(words)
    calls = []

    def fake(video, cfg=None, reporter=None, cancel=None):
        calls.append(video)
        return Track.from_json(face_track(30))
    monkeypatch.setattr(face_detect, "detect_face_track", fake)
    assert director.face_for(p, "talking.mp4", cfg()) and calls == ["talking.mp4"]
    assert zones.FaceMap(p).known


def test_when_the_face_cannot_be_found_safe_zones_are_used_and_said(monkeypatch):
    words = real_words()
    p = make_project(words)

    def fails(*a, **k):
        raise EditorError("The face was not found in enough of the video.")
    monkeypatch.setattr(face_detect, "detect_face_track", fails)
    r = editorial.generate(p, cfg(), video="talking.mp4", use_ai=False)
    assert any("face was not found (The face was not found" in n and "safe zones" in n for n in r["notes"])
    assert json.dumps(zones.TALKING_HEAD_FACE) == "[200, 220, 880, 1020]"
