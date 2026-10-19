"""The cue extractor: what is said that asks for a graphic, from the words alone (Taglish and
English). Both acceptance transcripts and made-up sentences: nothing is hardcoded."""

import pytest

from autoedit import cues
from autoedit.words import load_transcript
from tests.director_helpers import make_words


def words(text):
    return make_words(text.split())


def kinds(found):
    return [(c.kind, c.text, [t for _k, t in c.items], c.number) for c in found]


@pytest.mark.parametrize("said, value", [
    ("isa", 1), ("tatlo", 3), ("tatlong", 3), ("sampu", 10), ("tatlumpung", 30), ("dalawampu", 20),
    ("1,000", 1000), ("5.5", 5.5), ("five", 5), ("zero", 0), ("labing-isa", 11),
])
def test_numbers_said_in_tagalog_english_or_digits(said, value):
    assert cues.number_word(said) == value


@pytest.mark.parametrize("text, value", [("isang libong followers", 1000), ("dalawang daan na", 200),
                                         ("limang libong views", 5000), ("tatlumpung araw", 30)])
def test_scaled_numbers(text, value):
    assert cues.read_number(words(text), 0)[0] == value


def test_the_base_script():
    ws = [{"text": w.text, "start": w.start, "end": w.end} for w in load_transcript("tests/data/acceptance/base_words.json")]
    got = {c.kind: c for c in cues.extract(ws)}
    assert got["countdown"].number == 3 and [t for _k, t in got["countdown"].items] == ["3", "2", "1"]
    assert got["keyword"].text == "DISIPLINA"
    assert got["search"].text == "paano kumita online"
    assert [t for _k, t in got["checklist"].items] == ["mag-post", "sagutin ang comments", "i-check ang analytics"]
    assert [t for _k, t in got["platforms"].items] == ["TikTok", "Facebook", "YouTube"]
    assert got["handle"].text == "@akosicreator"
    assert [t for _k, t in got["storyboard"].items] == ["hook", "kwento", "call to action"]
    assert [t for _k, t in got["stats"].items] == ["0", "1,000 followers", "30 araw"]
    assert "before_after" in got and "follow" in got and "screenshot" in got


def test_other_words_other_cues():
    found = cues.extract(words("Sampung minuto lang . Lima apat tatlo dalawa isa . Pangatlo: TIYAGA . "
                               "Noon, mahirap . Ngayon, madali na . Sa search bar, i-type mo: best budget phone 2025 . "
                               "Ang listahan ko: tubig, tinapay at itlog . Nasa Instagram at Shopee kami: @tindahan.ni.aling . "
                               "Script ko: intro, demo, presyo . Mula 50 hanggang 2,500 orders sa loob ng dalawang buwan . "
                               "Mag-subscribe ka na ."))
    got = {c.kind: c for c in found}
    assert got["countdown"].number == 5
    assert got["keyword"].text == "TIYAGA"
    assert got["search"].text == "best budget phone 2025"
    assert [t for _k, t in got["checklist"].items] == ["tubig", "tinapay", "itlog"]
    assert [t for _k, t in got["platforms"].items] == ["Instagram", "Shopee"]
    assert got["handle"].text == "@tindahan.ni.aling"
    assert [t for _k, t in got["storyboard"].items] == ["intro", "demo", "presyo"]
    assert [t for _k, t in got["stats"].items] == ["50", "2,500 orders", "2 buwan"]
    assert "follow" in got and "before_after" in got


def test_plain_talk_has_no_cues():
    assert cues.extract(words("Kumusta kayo mga kaibigan . Masaya ako ngayong araw .")) == []


def test_a_platform_inside_a_search_query_is_part_of_the_query():
    got = {c.kind: c for c in cues.extract(words("I-search mo lang ang premium editing tips sa YouTube ."))}
    assert got["search"].text == "premium editing tips sa YouTube" and "platforms" not in got


def test_every_cue_starts_on_a_word_that_was_said():
    ws = words("Tatlo dalawa isa . Una: GALING . Hinanap ko: murang laptop .")
    for c in cues.extract(ws):
        assert 0 <= c.i0 <= c.i1 < len(ws)
