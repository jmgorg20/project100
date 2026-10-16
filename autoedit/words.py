"""The Word type and reading/writing word-timestamp transcript files.

Transcript JSON format (what we save and what --transcript accepts):

    {
      "language": "tl",
      "words": [
        {"word": "Hello", "start": 0.00, "end": 0.42},
        {"word": "*GitHub*", "start": 0.50, "end": 0.95}
      ]
    }

A word wrapped in *stars* is a manual keyword: it gets highlighted in the captions.
Groq/OpenAI "verbose_json" output (words at the top level or inside segments) is accepted too.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import EditorError


@dataclass
class Word:
    text: str
    start: float
    end: float
    manual: bool = False      # marked with *stars* in the transcript
    highlight: bool = False   # will be drawn in the keyword colour

    def copy(self, **changes):
        values = dict(text=self.text, start=self.start, end=self.end,
                      manual=self.manual, highlight=self.highlight)
        values.update(changes)
        return Word(**values)


def normalize(text):
    """Lower-case a word and strip punctuation, for comparing words ("Uhm," -> "uhm")."""
    return re.sub(r"[^\w'-]+", "", text.lower()).strip("'-")


def collapse_repeats(text):
    """'ummm' -> 'um', 'ahhh' -> 'ah'. Used only for filler comparison."""
    return re.sub(r"(.)\1+", r"\1", text)


def make_word(text, start, end):
    text = str(text).strip()
    manual = False
    match = re.fullmatch(r"\*+(.+?)\*+([.,!?;:]*)", text)
    if match:
        text = match.group(1) + match.group(2)
        manual = True
    start, end = float(start), float(end)
    if end < start:
        end = start
    return Word(text=text, start=start, end=end, manual=manual)


def words_from_data(data):
    """Turn parsed JSON (our format, a plain list, or Groq verbose_json) into Words."""
    if isinstance(data, dict):
        raw = data.get("words")
        if not raw and data.get("segments"):
            raw = [w for seg in data["segments"] for w in seg.get("words", [])]
    elif isinstance(data, list):
        raw = data
    else:
        raw = None
    if not raw:
        raise EditorError("The transcript has no words with timestamps.")
    words = []
    for item in raw:
        try:
            text = item.get("word", item.get("text"))
            word = make_word(text, item["start"], item["end"])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise EditorError(f"Bad word entry in transcript: {item!r}. "
                              "Each word needs 'word', 'start' and 'end'.")
        if word.text:
            words.append(word)
    words.sort(key=lambda w: w.start)
    return words


def load_transcript(path):
    path = Path(path)
    if not path.exists():
        raise EditorError(f"Transcript file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EditorError(f"Transcript '{path.name}' is not valid JSON: {exc}")
    return words_from_data(data)


def save_transcript(words, path, language="tl"):
    data = {
        "language": language,
        "words": [
            {"word": f"*{w.text}*" if w.manual else w.text,
             "start": round(w.start, 3), "end": round(w.end, 3)}
            for w in words
        ],
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
