"""Captions without punctuation (a setting, default remove), a better Taglish hint for Whisper,
and fixing the words before the edit."""

import json
import re
import subprocess
from argparse import Namespace

import pytest

from autoedit import ai_edit, transcribe
from autoedit.captions import build_ass, fonts_from_config, strip_punctuation
from autoedit.config import DEFAULTS, load_config
from autoedit.project import media_from_file, new_project, validate_project
from autoedit.project_render import build_project_ass, render_project
from autoedit.styles import get_style
from autoedit.words import Word, load_transcript, save_transcript
from tests import synthetic

FONTS = fonts_from_config(DEFAULTS["captions"])
CASES = [
    ("lang!", "lang"), ("DISIPLINA.", "DISIPLINA"), ("isa!", "isa"), ("ko:", "ko"), ("Una;", "Una"),
    ('"Hello,"', "Hello"), ("“Oo”", "Oo"), ("i-check,", "i-check"), ("mag-post", "mag-post"),
    ("3,600", "3,600"), ("1.5.", "1.5"), ("₱1,299!", "₱1,299"), ("it's", "it's"), ("Ma’am,", "Ma’am"),
    ("*ako!*", "*ako*"), ("follower...", "follower"), ("ngayon?!", "ngayon"), ("—", "—"), ("(ito)", "(ito)"),
]


@pytest.mark.parametrize("text, shown", CASES)
def test_punctuation_is_removed_but_words_and_numbers_stay(text, shown):
    assert strip_punctuation(text) == shown


def words(texts):
    return [Word(t, 0.4 * i, 0.4 * i + 0.3) for i, t in enumerate(texts)]


def dialogue_text(ass):
    return " ".join(re.sub(r"\{[^}]*\}", "", line.split(",", 9)[9]) for line in ass.splitlines()
                    if line.startswith("Dialogue:"))


@pytest.mark.parametrize("style", ["classic", "yellow_pop", "bold_caps", "typewriter", "one_word"])
def test_no_caption_style_shows_punctuation_unless_kept(style):
    said = words(["Teka", "lang!", "Tatlo...", "dalawa...", "isa!", "Una:", "DISIPLINA.", "3,600", "i-check,"])
    text = dialogue_text(build_ass(said, get_style(style), FONTS))
    assert not re.search(r"[!:;?]|\.\.\.|(?<!\d)[.,](?!\d)", text), text
    assert "3,600" in text and re.search(r"i-check", text, re.I)
    kept = dialogue_text(build_ass(said, get_style(style).__class__(**{**get_style(style).__dict__,
                                                                           "punctuation": "keep"}), FONTS))
    assert "!" in kept


def caption_project(punctuation=None):
    p = new_project("p", caption_punctuation=punctuation)
    p["tracks"][3]["clips"] = [{"id": "c1", "type": "caption", "start": 0.0, "duration": 2.0, "style": "classic",
                                "words": [{"text": "Teka", "start": 0, "end": 0.4},
                                          {"text": "lang!", "start": 0.5, "end": 0.9}]}]
    return p


def test_the_project_setting_decides_and_the_words_stay_as_said(tmp_path):
    default = caption_project()
    assert validate_project(default) == []
    assert "!" not in dialogue_text(build_project_ass(default, tmp_path))
    keep = caption_project("keep")
    assert validate_project(keep) == [] and "lang!" in dialogue_text(build_project_ass(keep, tmp_path))
    assert keep["tracks"][3]["clips"][0]["words"][1]["text"] == "lang!"         # the words are not changed
    bad = caption_project("keep")
    bad["settings"]["captions"]["punctuation"] = "sometimes"
    assert validate_project(bad)


def test_config_and_flag_reach_new_projects(tmp_path):
    from autoedit.formats import build_voiceover_project
    cfg = load_config()
    assert cfg["captions"]["punctuation"] == "remove"
    cfg["captions"]["punctuation"] = "keep"
    audio = synthetic.make_tone(tmp_path / "vo.wav", duration=2.0)
    pic = synthetic.make_image(tmp_path / "b.png")
    p = build_voiceover_project(audio, [pic], cfg, words(["Kumusta,", "kayo!"]), name="vo")
    assert p["settings"]["captions"]["punctuation"] == "keep"


def test_rendered_captions_have_no_exclamation_mark(tmp_path):
    """The real FFmpeg render: the same caption with and without punctuation differs only where the
    '!' was (fewer white pixels when it is removed)."""
    video = synthetic.make_color_video(tmp_path / "c.mp4")

    def white(punctuation):
        p = caption_project(punctuation)
        p["media"] = [media_from_file(video, "v")]
        p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "v", "start": 0, "duration": 2,
                                    "in": 0, "out": 2}]
        p["settings"]["audio"]["normalize"] = False
        out = render_project(p, tmp_path / f"{punctuation}.mp4", base_dir=tmp_path,
                             export={"crf": 30, "encoder_speed": "ultrafast", "audio_bitrate": "96k"})
        px = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.2", "-i", str(out), "-frames:v", "1",
                             "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        return sum(1 for b in px if b > 235)
    assert white("keep") > white("remove") + 30


# ---------------------------------------------------------------- Taglish transcription

def test_the_hint_has_your_words_your_file_names_and_a_taglish_line(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["transcription"]["vocabulary_file"] = str(tmp_path / "vocab.json")
    (tmp_path / "vocab.json").write_text(json.dumps({"words": ["GCash"]}), encoding="utf-8")
    prompt = transcribe.transcription_prompt(cfg, ["Ipakita ang search_results.png", "tiktok_logo.png"])
    assert prompt.startswith("GCash, Ipakita, search, results, tiktok")
    assert "tatlo" in prompt and "hinanap" in prompt and len(prompt) <= 600
    cfg["transcription"]["taglish_hint"] = False
    assert "tatlo" not in (transcribe.transcription_prompt(cfg, []) or "")
    cfg["transcription"]["taglish_hint"] = True
    cfg["language"] = "en"
    assert "tatlo" not in (transcribe.transcription_prompt(cfg, []) or "")


def test_groq_gets_the_best_model_tagalog_and_the_hint(tmp_path, monkeypatch):
    import requests
    cfg = load_config()
    cfg["transcription"]["vocabulary_file"] = str(tmp_path / "none.json")
    assert cfg["transcription"]["groq_model"] == "whisper-large-v3" and cfg["language"] == "tl"
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    seen = {}

    class Response:
        status_code = 200

        def json(self):
            return {"words": [{"word": "Tatlo", "start": 0.1, "end": 0.4}]}

    def fake_post(url, headers, data, files, timeout):
        seen.update(data)
        return Response()
    monkeypatch.setattr(requests, "post", fake_post)
    video = synthetic.make_video(tmp_path / "talk.mp4")
    transcribe.transcribe(video, cfg, tmp_path, hints=["hinanap ko ang paano kumita online"])
    assert seen["model"] == "whisper-large-v3" and seen["language"] == "tl"
    assert "hinanap" in seen["prompt"] and "kumita" in seen["prompt"] and "Taglish" in seen["prompt"]


def test_the_saved_transcript_is_reused_when_only_the_instruction_changes(tmp_path):
    """Changing the instruction and editing again must not transcribe (and pay) again; turning the
    Taglish hint on or off is a different transcript."""
    from autoedit.cache import Cache
    cfg = load_config()
    video = synthetic.make_video(tmp_path / "talk.mp4")
    cache = Cache(tmp_path / "cache")
    key = ai_edit.transcript_key(video, cfg, cache)
    assert key.endswith("-groq-whisper-large-v3-tl-taglish1")
    cfg["transcription"]["taglish_hint"] = False
    assert ai_edit.transcript_key(video, cfg, cache) == key.replace("-taglish1", "")


def test_fix_the_words_then_edit_with_them(tmp_path, monkeypatch):
    """`transcribe` saves the words to a file; after fixing it, ai-edit --transcript uses it as is."""
    import editor
    video = synthetic.make_video(tmp_path / "talk.mp4")
    calls = []

    def fake_transcribe(v, cfg, job_dir, start=None, end=None, hints=()):
        calls.append(list(hints))
        return [Word("Tatyo", 0.5, 0.9), Word("sikreto", 1.0, 1.5)]
    monkeypatch.setattr(ai_edit, "transcribe", fake_transcribe)
    conf = tmp_path / "config.yaml"
    conf.write_text(f"ai:\n  cache_folder: {tmp_path / 'cache'}\n", encoding="utf-8")
    out = tmp_path / "t.json"

    class Rep:
        def stage(self, *a, **k): pass
        def result(self, **data): self.data = data
    rep = Rep()
    editor.cmd_transcribe(Namespace(config=str(conf), video=str(video), output=str(out), instruction="hinanap",
                                    photos=["search_results.png"], transcribe_with=None), rep)
    assert calls == [["hinanap", "search_results.png"]] and [w["text"] for w in rep.data["words"]] == ["Tatyo", "sikreto"]
    fixed = load_transcript(out)
    fixed[0] = fixed[0].copy(text="Tatlo")
    save_transcript(fixed, out)
    words_used = []
    monkeypatch.setattr(ai_edit, "load_words", lambda *a, **k: pytest.fail("transcribed again"))

    def stop_after_transcript(*a, **k):
        raise RuntimeError("stop")
    monkeypatch.setattr(ai_edit, "request_plan", stop_after_transcript)

    class Reporter:
        def stage(self, *a, **k): pass

        def event(self, kind, **data):
            if kind == "transcript":
                words_used.append(data["text"])
        def progress(self, *a, **k): pass
    with pytest.raises(RuntimeError, match="stop"):
        ai_edit.ai_edit_video(video, load_config(), "x", [], provider="groq", model="m", render=False,
                              reporter=Reporter(), transcript=str(out))
    assert words_used == ["Tatlo sikreto"]
