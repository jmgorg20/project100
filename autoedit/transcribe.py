"""Speech to text with word timestamps: Groq Whisper API (online) or faster-whisper (local)."""

import os
from pathlib import Path

from . import PROJECT_DIR
from .errors import EditorError
from .ffmpeg_tools import run_ffmpeg
from .words import words_from_data

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MAX_BYTES = 24 * 1024 * 1024   # Groq free tier accepts files up to 25 MB


def load_dotenv(path=None):
    """Read KEY=VALUE lines from .env into the environment (existing values win)."""
    path = Path(path) if path else PROJECT_DIR / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def extract_audio(video, out_path, start=None, end=None):
    """Small mono MP3 of the speech: fast to upload and enough for Whisper.

    `start`/`end` (seconds in the file): only that part.
    """
    part = []
    if start is not None:
        part += ["-ss", f"{max(0.0, start):.3f}"]
    if end is not None:
        part += ["-t", f"{max(0.05, end - (start or 0)):.3f}"]
    run_ffmpeg([*part, "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame",
                "-b:a", "32k", str(out_path)], "extracting audio for transcription",
               show_progress=False)
    return out_path


def transcribe_groq(audio_path, language, model, prompt=None):
    import requests

    load_dotenv()
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key or key.startswith("your_"):
        raise EditorError(
            "GROQ_API_KEY is missing. Create a file named .env in the project folder with:\n"
            "  GROQ_API_KEY=your-key-here\n"
            "(copy .env.example). Get a free key at https://console.groq.com/keys\n"
            "Or use the offline transcriber: set  provider: local  in config.yaml."
        )
    size = Path(audio_path).stat().st_size
    if size > GROQ_MAX_BYTES:
        raise EditorError("This video's audio is too long for the Groq free upload limit (25 MB, "
                          "about 1.5 hours). Use  provider: local  in config.yaml for long videos.")
    print(f"  > transcribing with Groq ({model}, language={language})")
    data = {
        "model": model,
        "language": language,
        "response_format": "verbose_json",
        "timestamp_granularities[]": ["word", "segment"],
        "temperature": "0",
    }
    if prompt:
        data["prompt"] = prompt          # your vocabulary: helps Whisper spell names right
    try:
        with open(audio_path, "rb") as f:
            response = requests.post(
                GROQ_URL, headers={"Authorization": f"Bearer {key}"}, data=data,
                files={"file": (Path(audio_path).name, f, "audio/mpeg")}, timeout=600,
            )
    except requests.RequestException as exc:
        raise EditorError(f"Could not reach Groq (check your internet connection): {exc}")
    if response.status_code == 401:
        raise EditorError("Groq rejected the API key (401). Check GROQ_API_KEY in your .env file.")
    if response.status_code == 429:
        raise EditorError("Groq says you hit the free usage limit (429). Wait a bit and retry, "
                          "or use  provider: local  in config.yaml.")
    if response.status_code != 200:
        # Never print the request (it contains the key); the response body is safe.
        raise EditorError(f"Groq transcription failed ({response.status_code}): "
                          f"{response.text[:300]}")
    return words_from_data(response.json())


def transcribe_local(audio_path, language, model_name, device, prompt=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise EditorError("The local transcriber is not installed. Run:\n"
                          "  pip install faster-whisper")
    print(f"  > transcribing on this PC with faster-whisper '{model_name}' "
          "(the first run downloads the model; this can take a while)")
    compute_type = "int8" if device in ("cpu", "auto") else "float16"
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as exc:  # CUDA missing, bad model name...
        raise EditorError(f"Could not load the local Whisper model '{model_name}': {exc}")
    segments, _info = model.transcribe(str(audio_path), language=language,
                                       word_timestamps=True, vad_filter=False,
                                       initial_prompt=prompt)
    words = []
    for segment in segments:
        for w in segment.words or []:
            words.append({"word": w.word, "start": w.start, "end": w.end})
    if not words:
        raise EditorError("No speech was found in the video.")
    return words_from_data({"words": words})


def transcribe(video, cfg, work_dir, start=None, end=None):
    """Word timestamps of a file's speech (or of start-end seconds of it, in file time).

    Your vocabulary (vocabulary.json) is sent as a hint; corrections are applied by the
    callers (vocabulary.fix_words), so they also reach transcripts saved earlier.
    """
    from .vocabulary import load_vocabulary, prompt_for, vocabulary_path
    audio = extract_audio(video, Path(work_dir) / "speech.mp3", start, end)
    t = cfg["transcription"]
    provider = str(t["provider"]).lower()
    prompt = prompt_for(load_vocabulary(vocabulary_path(cfg)))
    if provider == "groq":
        words = transcribe_groq(audio, cfg["language"], t["groq_model"], prompt)
    elif provider == "local":
        words = transcribe_local(audio, cfg["language"], t["local_model"], t["local_device"],
                                 prompt)
    else:
        raise EditorError(f"Unknown transcription provider '{t['provider']}'. "
                          f"Use 'groq' or 'local'.")
    if start:
        words = [w.copy(start=w.start + start, end=w.end + start) for w in words]
    return words
