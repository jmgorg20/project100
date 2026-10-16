import json

import pytest

from autoedit.config import DEFAULTS, load_config
from autoedit.errors import EditorError
from autoedit.grades import GRADES, grade_filter
from autoedit.highlight import mark_keywords
from autoedit.plan import load_plan
from autoedit.words import Word, load_transcript, make_word, words_from_data


def marked(texts, **settings):
    cfg = dict(DEFAULTS["highlight"], **settings)
    words = [Word(t, i, i + 0.5) for i, t in enumerate(texts)]
    return [w.text for w in mark_keywords(words, cfg) if w.highlight]


def test_manual_markers_are_parsed_and_always_highlighted():
    word = make_word("*GitHub*,", 0, 1)
    assert word.text == "GitHub," and word.manual
    words = [make_word(t, 0, 1) for t in ["*isa*", "*dalawa*", "*tatlo*"]]
    assert all(w.highlight for w in mark_keywords(words, DEFAULTS["highlight"]))


def test_numbers_prices_and_tech_terms():
    assert marked(["ang", "presyo", "500", "pesos"]) == ["500"]
    assert marked(["gamit", "ang", "laptop", "ko"]) == ["laptop"]
    assert marked(["₱1,299", "lang"]) == ["₱1,299"]


def test_rules_can_be_switched_off():
    assert marked(["ang", "laptop"], english_terms=False, long_words=False) == []
    assert marked(["ang", "laptop"], enabled=False) == []


def test_long_words_rule():
    assert marked(["napakaganda", "ito"], english_terms=False) == ["napakaganda"]
    assert marked(["napakaganda", "ito"], english_terms=False, long_words=False) == []


def test_at_most_one_keyword_per_four_words():
    assert len(marked(["laptop", "online", "website", "internet"])) == 1


def test_stop_words_never_highlighted():
    assert marked(["ang", "ng", "sa", "na"]) == []


def test_transcript_formats(tmp_path):
    ours = {"words": [{"word": "Hi", "start": 0, "end": 0.5}]}
    groq = {"segments": [{"words": [{"word": " Hi", "start": 0, "end": 0.5}]}]}
    assert words_from_data(ours)[0].text == "Hi"
    assert words_from_data(groq)[0].text == "Hi"
    assert words_from_data([{"text": "Hi", "start": 0, "end": 0.5}])[0].text == "Hi"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(EditorError):
        load_transcript(bad)
    with pytest.raises(EditorError):
        words_from_data({"words": [{"word": "x"}]})


def test_config_defaults_preset_and_overrides(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("preset: relaxed\nstyle: 3\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg["pacing"]["silence_threshold"] == 0.6
    assert cfg["style"] == 3
    cfg = load_config(cfg_file, {"style": "bold_caps", "silence_threshold": 0.4, "grade": None})
    assert cfg["style"] == "bold_caps"
    assert cfg["pacing"]["silence_threshold"] == 0.4
    assert cfg["grade"] == "natural_clean"


def test_project_config_file_loads():
    cfg = load_config()
    assert cfg["pacing"]["silence_threshold"] == 0.25
    assert cfg["fillers"] == ["ah", "uh", "um", "uhm", "eh"]


def test_bad_preset_and_grade_give_clear_errors(tmp_path):
    with pytest.raises(EditorError):
        load_config(None, {"preset": "turbo"})
    with pytest.raises(EditorError):
        grade_filter("sepia")
    assert set(GRADES) >= {"natural_clean", "none", "warm", "black_and_white",
                           "orange_teal", "high_contrast"}


def test_plan_loading(tmp_path):
    (tmp_path / "pic.png").write_bytes(b"x")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({
        "style": "one_word", "grade": "warm",
        "zooms": [{"start": 1, "end": 2, "amount": 1.3}],
        "grades": [{"start": 3, "end": 4, "grade": "black_and_white"}],
        "cuts": [{"start": 5, "end": 6}],
        "overlays": [{"file": "pic.png", "at": 2}],
    }), encoding="utf-8")
    plan = load_plan(plan_file, tmp_path)
    assert plan["zooms"][0]["amount"] == 1.3
    assert plan["overlays"][0]["file"] == tmp_path / "pic.png"
    assert plan["overlays"][0]["duration"] == 2.5

    plan_file.write_text(json.dumps({"zoomz": []}), encoding="utf-8")
    with pytest.raises(EditorError):
        load_plan(plan_file, tmp_path)
    plan_file.write_text(json.dumps({"cuts": [{"start": 5, "end": 4}]}), encoding="utf-8")
    with pytest.raises(EditorError):
        load_plan(plan_file, tmp_path)
