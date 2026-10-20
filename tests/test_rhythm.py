"""The look's rhythm (the real Windows run: B&W on "dati" lasted ~1 s; long stretches with nothing
changing): the past stays black and white until "ngayon", and something visibly changes at least
every 4 seconds."""

import pytest

from autoedit import editorial
from autoedit.words import load_transcript
from tests import synthetic
from tests.director_helpers import make_project, make_words
from tests.test_editorial_director import cfg, run
from tests.test_project_render import fx_render
from tests.test_editorial_effects import media  # noqa: F401  (fixture)

REAL = "tests/data/realclip/groq_words.json"


def saturation(rgb):
    return max(rgb) - min(rgb)


def test_bw_with_a_short_ramp_stays_grey_almost_the_whole_time(media):  # noqa: F811
    tmp, p = media
    out = fx_render(tmp, p, "bwramp", [{"id": "b", "type": "fx", "effect": "bw", "start": 0.0, "duration": 2.0,
                                        "intensity": 1.0, "ramp": 0.2}])
    early, middle, late = synthetic.pixels(out, [9, 30, 51], 540, 960)
    assert all(saturation(px) < 40 for px in (early, middle, late))       # grey at 0.3 s and at 1.7 s
    old = fx_render(tmp, p, "bwold", [{"id": "b", "type": "fx", "effect": "bw", "start": 0.0, "duration": 2.0,
                                       "intensity": 1.0}])
    assert saturation(synthetic.pixels(old, [9], 540, 960)[0]) > 60       # the default ramp is still colour then


def real_words():
    return [{"text": w.text, "start": w.start, "end": w.end} for w in load_transcript(REAL)]


def test_the_past_is_black_and_white_until_ngayon():
    words = real_words()
    out = run(make_project(words, caption_style="editorial_card"), cfg())["project"]
    dati = next(w["start"] for w in words if w["text"] == "Dati")
    ngayon = next(w["start"] for w in words if w["text"] == "Ngayon")
    bw = next(c for t in out["tracks"] for c in t["clips"] if c.get("effect") == "bw" and c["start"] <= dati)
    assert bw["start"] <= dati - 0.2 and bw["start"] + bw["duration"] >= ngayon + 0.2
    assert bw["duration"] >= 2.0 and bw["ramp"] == pytest.approx(0.3)


@pytest.mark.parametrize("script", ["real", "plain"])
def test_something_changes_at_least_every_four_seconds(script):
    if script == "real":
        words = real_words()
    else:   # plain talk: few cues, the rules and the rhythm keep it moving
        words = make_words(("Kumusta kayo lahat ngayong araw na ito masaya ako na nandito kayo ulit "
                            "gusto ko lang ikwento kung paano ako nagsimula sa maliit na kwarto namin "
                            "walang ilaw walang camera pero tuloy lang ako hanggang ngayon salamat sa inyo").split())
    r = run(make_project(words, caption_style="editorial_card"), cfg())
    out = r["project"]
    duration = max(c["start"] + c["duration"] for c in out["tracks"][0]["clips"])
    marks = sorted(set([words[0]["start"]] + editorial.visible_changes(out) + [min(duration, words[-1]["end"])]))
    marks = [m for m in marks if m <= words[-1]["end"]]
    gaps = [round(b - a, 2) for a, b in zip(marks, marks[1:])]
    assert max(gaps) <= editorial.MAX_GAP + 0.05, gaps
