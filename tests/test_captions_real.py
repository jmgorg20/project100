"""Captions on real Whisper words (the Windows run: "Mag-post sagutin ang comments i-check ang" /
"analytics", sentences run together): one sentence per caption, as few and as evenly filled as fit,
never ending on "ang" / "sa" / "isang"; the editorial card is bigger; the caption style can be
chosen (it wins over the preset's)."""

import argparse

import pytest

from autoedit.captions import chunk_words, sentence_breaks
from autoedit.config import load_config
from autoedit.errors import EditorError
from autoedit.styles import get_style
from autoedit.words import Word, load_transcript

REAL = "tests/data/realclip/groq_words.json"


def captions(style="editorial_card"):
    return [[" ".join(w.text for w in line) for line in g] for g in chunk_words(load_transcript(REAL), get_style(style))]


@pytest.mark.parametrize("style", ["editorial_card", "bold_caps", "yellow_pop", "minimal"])
def test_one_sentence_per_caption_and_no_lone_last_word(style):
    groups = [" ".join(g) for g in captions(style)]
    assert not any("video" in g and "Tatyo" in g for g in groups)           # two sentences never mix
    assert not any("ako" in g and "Sa" in g.split() for g in groups)
    assert "analytics" not in groups                                       # never alone


def test_the_editorial_card_reads_like_the_reference():
    got = captions()
    assert ["Mag-post sagutin", "ang comments"] in got and any(g[-1].endswith("ang analytics") for g in got)
    assert ["Ito ang screenshot", "ng resulta ko"] in got
    # no line ends on "ang" / "sa" / "ng" (narrow styles may have to, when a phrase is wider than a line)
    for g in got:
        for line in g[:-1]:
            assert line.split()[-1].lower() not in ("ang", "sa", "ng", "isang", "libong"), g
    style = get_style("editorial_card")
    assert style.size >= 68 and style.family == "Playfair Display" and style.mode == "reveal"


def test_punctuated_words_keep_their_sentences():
    words = [Word(t, i * 0.4, i * 0.4 + 0.3) for i, t in enumerate("Ito ang plano. gising kape edit.".split())]
    assert sentence_breaks(words) == {3}


def test_the_caption_style_you_choose_wins(monkeypatch):
    import editor
    cfg = load_config()
    editor.caption_punctuation(cfg, argparse.Namespace(caption_punctuation=None, caption_style="bold_caps"))
    assert cfg["captions"]["force_style"] == "bold_caps"
    with pytest.raises(EditorError):
        editor.caption_punctuation(load_config(), argparse.Namespace(caption_punctuation=None, caption_style="nope"))
