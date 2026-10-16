import os

import pytest

from autoedit import transcribe, watch
from autoedit.errors import EditorError


def test_watch_waits_for_copy_to_finish_then_edits_and_moves(tmp_path, monkeypatch):
    edited = []
    monkeypatch.setattr(watch, "edit_video", lambda path, cfg: edited.append(path.name))
    (tmp_path / "a.mp4").write_bytes(b"123")
    (tmp_path / "notes.txt").write_text("ignored")
    sizes = {}
    watch.process_inbox_once(tmp_path, {}, sizes)   # first look: remember the size
    assert edited == []
    watch.process_inbox_once(tmp_path, {}, sizes)   # size unchanged: edit it
    assert edited == ["a.mp4"]
    assert (tmp_path / "done" / "a.mp4").exists()
    assert (tmp_path / "notes.txt").exists()


def test_watch_moves_failures_aside(tmp_path, monkeypatch):
    def boom(path, cfg):
        raise EditorError("bad video")
    monkeypatch.setattr(watch, "edit_video", boom)
    (tmp_path / "b.mov").write_bytes(b"1")
    sizes = {}
    watch.process_inbox_once(tmp_path, {}, sizes)
    watch.process_inbox_once(tmp_path, {}, sizes)
    assert (tmp_path / "failed" / "b.mov").exists()


def test_groq_missing_key_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(transcribe, "load_dotenv", lambda path=None: None)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    with pytest.raises(EditorError, match="GROQ_API_KEY is missing"):
        transcribe.transcribe_groq(audio, "tl", "whisper-large-v3")


def test_groq_request_is_built_correctly(tmp_path, monkeypatch, capsys):
    """No network: a fake requests.post checks what would be sent to Groq."""
    import requests

    secret = "gsk_test_secret_123456"
    monkeypatch.setenv("GROQ_API_KEY", secret)
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"words": [{"word": "Kumusta", "start": 0.0, "end": 0.5}]}

    def fake_post(url, headers, data, files, timeout):
        seen.update(url=url, headers=headers, data=data, filename=files["file"][0])
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    audio = tmp_path / "speech.mp3"
    audio.write_bytes(b"x")
    words = transcribe.transcribe_groq(audio, "tl", "whisper-large-v3")
    assert words[0].text == "Kumusta"
    assert seen["url"].endswith("/audio/transcriptions")
    assert seen["headers"]["Authorization"] == f"Bearer {secret}"
    assert seen["data"]["language"] == "tl"
    assert seen["data"]["model"] == "whisper-large-v3"
    assert "word" in seen["data"]["timestamp_granularities[]"]
    assert secret not in capsys.readouterr().out      # key never printed


def test_dotenv_loader(tmp_path, monkeypatch):
    monkeypatch.delenv("SOME_TEST_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text('# comment\nSOME_TEST_KEY="abc"\n', encoding="utf-8")
    transcribe.load_dotenv(env)
    assert os.environ["SOME_TEST_KEY"] == "abc"
