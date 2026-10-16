"""Your vocabulary and corrections, and transcribing part of the timeline again."""

import pytest

from autoedit import transcribe
from autoedit.config import load_config
from autoedit.project import new_project, validate_project
from autoedit.retranscribe import retranscribe
from autoedit.vocabulary import (apply_corrections, clean, fix_words, load_vocabulary, prompt_for,
                                 save_vocabulary)
from autoedit.words import Word, make_word
from tests import synthetic
from autoedit.ffmpeg_tools import probe


def words(*items):
    return [make_word(t, s, e) for t, s, e in items]


def test_corrections_merge_phrases_keep_punctuation_and_are_idempotent():
    fixes = [{"from": "g cash", "to": "GCash"}, {"from": "sho pee", "to": "Shopee"},
             {"from": "g", "to": "Gee"}]
    got = apply_corrections(words(("Bayad", 0, 0.4), ("sa", 0.5, 0.6), ("G", 0.7, 0.8),
                                  ("Cash,", 0.85, 1.2), ("tapos", 1.3, 1.6), ("SHO", 1.7, 1.8),
                                  ("pee!", 1.85, 2.1)), fixes)
    assert [w.text for w in got] == ["Bayad", "sa", "GCash,", "tapos", "Shopee!"]
    assert (got[2].start, got[2].end) == (0.7, 1.2)            # spans both words
    assert [w.text for w in apply_corrections(got, fixes)] == [w.text for w in got]
    marked = apply_corrections([Word("g", 0, 1, manual=True), Word("cash", 1, 2)], fixes)
    assert marked[0].manual and marked[0].text == "GCash"


def test_vocabulary_file_is_forgiving_and_the_prompt_is_short(tmp_path):
    path = tmp_path / "vocabulary.json"
    assert load_vocabulary(path) == {"words": [], "corrections": []}        # missing
    path.write_text("{not json", encoding="utf-8")
    assert load_vocabulary(path) == {"words": [], "corrections": []}        # damaged
    save_vocabulary({"_help": "x", "words": ["GCash", " gcash ", "", "Maya"],
                     "corrections": [{"from": "g cash", "to": "GCash"}, {"from": "", "to": "x"},
                                     {"to": "y"}, "bad"]}, path)
    vocab = load_vocabulary(path)
    assert vocab == {"words": ["GCash", "Maya"], "corrections": [{"from": "g cash", "to": "GCash"}]}
    assert prompt_for(vocab) == "GCash, Maya"
    assert prompt_for({"words": ["Abcdefghij"] * 0 + [f"word{i:03d}" for i in range(200)],
                       "corrections": []}).count(",") < 100
    assert prompt_for(clean({})) is None


def test_transcribe_sends_the_vocabulary_and_handles_a_part_of_the_file(tmp_path, monkeypatch):
    import requests
    vocab = tmp_path / "vocab.json"
    save_vocabulary({"words": ["GCash"], "corrections": [{"from": "g cash", "to": "GCash"}]}, vocab)
    cfg = load_config()
    cfg["transcription"].update(provider="groq", vocabulary_file=str(vocab))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    seen = {}

    class Response:
        status_code = 200

        def json(self):
            return {"words": [{"word": "g", "start": 0.1, "end": 0.2},
                              {"word": "cash", "start": 0.25, "end": 0.5}]}

    def fake_post(url, headers, data, files, timeout):
        seen["data"] = data
        seen["audio"] = files["file"][1].read()
        return Response()

    monkeypatch.setattr(requests, "post", fake_post)
    video = synthetic.make_video(tmp_path / "talk.mp4")
    got = transcribe.transcribe(video, cfg, tmp_path, start=2.0, end=3.5)
    assert seen["data"]["prompt"] == "GCash"
    assert [(w.text, w.start) for w in got] == [("g", 2.1), ("cash", 2.25)]   # file time
    assert [w.text for w in fix_words(got, cfg)] == ["GCash"]
    assert probe(tmp_path / "speech.mp3")["duration"] == pytest.approx(1.5, abs=0.1)  # that part only


def caption(cid, start, duration, texts, style="yellow_pop"):
    step = duration / len(texts)
    return {"id": cid, "type": "caption", "start": start, "duration": duration, "style": style,
            "overrides": {"zone": "top"},
            "words": [{"text": t, "start": round(i * step, 3), "end": round((i + 0.8) * step, 3)}
                      for i, t in enumerate(texts)]}


def test_retranscribe_replaces_only_the_captions_in_the_range(tmp_path):
    cfg = load_config()
    vocab = tmp_path / "v.json"
    save_vocabulary({"words": [], "corrections": [{"from": "g cash", "to": "GCash"}]}, vocab)
    cfg["transcription"]["vocabulary_file"] = str(vocab)
    p = new_project("t")
    p["media"] = [{"id": "m1", "kind": "video", "path": "talk.mp4", "duration": 20,
                   "width": 720, "height": 1280, "has_audio": True}]
    t = {x["id"]: x for x in p["tracks"]}
    t["main"]["clips"] = [
        {"id": "v1", "type": "video", "media": "m1", "start": 0, "duration": 2, "in": 0, "out": 2},
        {"id": "v2", "type": "video", "media": "m1", "start": 2, "duration": 2, "in": 6, "out": 10,
         "speed": 2},
    ]
    t["captions"]["clips"] = [caption("c1", 0, 1.0, ["Kumusta", "kayo"]),
                              caption("c2", 1.2, 1.6, ["mali", "na", "caption", "dito"]),
                              caption("c3", 3.0, 0.9, ["huling", "linya"])]
    calls = []

    def fake_transcribe(path, cfg_, job, a, b):
        calls.append((path.name, round(a, 3), round(b, 3)))
        # Source-time words: in v1 (source 1.5-2) and in v2 (sped up, source 6-8).
        heard = {0: [("Bayad", 1.55, 1.8)], 1: [("sa", 6.2, 6.6), ("g", 6.8, 7.0),
                                                 ("cash", 7.1, 7.6)]}
        return [make_word(*x) for x in heard[len(calls) - 1]]

    new, count = retranscribe(p, tmp_path / "x.project.json", cfg, 1.5, 3.0, tmp_path / "w",
                              transcribe_fn=fake_transcribe)
    assert calls == [("talk.mp4", 1.5, 2.0), ("talk.mp4", 6.0, 8.0)]   # sped-up part: 2x source
    assert validate_project(new) == []
    caps = sorted((c for c in new["tracks"][3]["clips"]), key=lambda c: c["start"])
    texts = [" ".join(w["text"] for w in c["words"]) for c in caps]
    assert texts[0] == "Kumusta kayo"                                   # before: untouched
    assert texts[1] == "mali"                       # crossing: cut at 1.5 ("na" is at 1.76 s)
    assert caps[1]["start"] + caps[1]["duration"] <= 1.5 + 1e-6
    redone = [c for c in caps if c["id"].startswith("rt")]
    assert " ".join(w["text"] for c in redone for w in c["words"]) == "Bayad sa GCash"
    assert all(c["style"] == "yellow_pop" and c["overrides"] == {"zone": "top"} for c in redone)
    assert redone[0]["start"] == pytest.approx(1.55)                     # timeline time
    gcash = next(w for c in redone for w in c["words"] if w["text"] == "GCash")
    assert gcash["start"] + next(c for c in redone if gcash in c["words"])["start"] == \
        pytest.approx(2 + (6.8 - 6) / 2)                                # mapped through 2x speed
    assert texts[-1] == "huling linya"                                  # after: untouched
    assert count == 3


def test_corrections_also_fix_transcripts_saved_before(tmp_path):
    from autoedit.ai_edit import load_words
    from autoedit.cache import Cache
    cfg = load_config()
    vocab = tmp_path / "v.json"
    cfg["transcription"]["vocabulary_file"] = str(vocab)
    cache = Cache(tmp_path / "cache")
    video = synthetic.make_video(tmp_path / "talk.mp4")
    t = cfg["transcription"]
    key = f"{cache.fingerprint(video)}-{t['provider']}-{t['groq_model']}-{cfg['language']}"
    cache.put("transcripts", key, {"language": "tl", "words": [
        {"word": "sa", "start": 0, "end": 0.2}, {"word": "g", "start": 0.3, "end": 0.4},
        {"word": "cash", "start": 0.45, "end": 0.8}]})
    got, cached, cost = load_words(video, cfg, cache, tmp_path, 8.0)
    assert cached and cost == 0 and [w.text for w in got] == ["sa", "g", "cash"]
    save_vocabulary({"corrections": [{"from": "g cash", "to": "GCash"}]}, vocab)
    got, _cached, _cost = load_words(video, cfg, cache, tmp_path, 8.0)
    assert [w.text for w in got] == ["sa", "GCash"]
