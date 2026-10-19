"""Your own words and corrections for Taglish transcripts (vocabulary.json, kept between runs).

    {
      "words": ["GCash", "Shopee", "Lazada"],              # names Whisper should spell right
      "corrections": [{"from": "g cash", "to": "GCash"},   # fix what it still gets wrong
                      {"from": "sho pee", "to": "Shopee"}]
    }

`words` (and every correction's "to") are sent to the transcriber as a hint ("prompt").
`corrections` are applied to every transcript: case does not matter, punctuation after the
last word is kept, and a phrase of several words becomes one ("g cash" -> "GCash").
"""

import json
import os
import re
from pathlib import Path

from . import PROJECT_DIR
from .words import normalize

PROMPT_LIMIT = 600          # characters; Whisper only reads a short hint


def vocabulary_path(cfg=None):
    name = ((cfg or {}).get("transcription") or {}).get("vocabulary_file", "vocabulary.json")
    path = Path(name)
    return path if path.is_absolute() else PROJECT_DIR / path


def clean(data):
    """Keep only well-formed entries (the file is edited by hand and by the app)."""
    data = data if isinstance(data, dict) else {}
    words, seen = [], set()
    for w in data.get("words") or []:
        w = str(w).strip()
        if w and w.lower() not in seen:
            seen.add(w.lower())
            words.append(w)
    corrections = []
    for c in data.get("corrections") or []:
        if isinstance(c, dict) and str(c.get("from", "")).strip() and str(c.get("to", "")).strip():
            corrections.append({"from": str(c["from"]).strip(), "to": str(c["to"]).strip()})
    return {"words": words, "corrections": corrections}


def load_vocabulary(path=None):
    """The vocabulary (empty if the file is missing or damaged: transcription still works)."""
    path = Path(path) if path else vocabulary_path()
    try:
        return clean(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        return clean({})


def save_vocabulary(vocab, path=None):
    path = Path(path) if path else vocabulary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(clean(vocab), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# Whisper copies the spelling and the mix of languages of its prompt. A short Taglish line with
# words it often mishears ("tatlo" heard as "tatyo", "hinanap" as "hinanat") steers it.
TAGLISH_STYLE = ("Taglish, Tagalog at English: teka lang, tatlo, dalawa, isa, una, pangalawa, pangatlo, "
                 "hinanap ko, hanapin, tingnan ninyo, dati, ngayon, kumita, sagutin, i-check, mag-post, "
                 "i-follow, talaga, kasi, pero, diba, grabe, sobrang, ganito.")
HINT_STOP = {"the", "and", "for", "with", "this", "that", "ang", "mga", "png", "jpg", "jpeg", "mp4", "mov",
             "img", "image", "photo", "video", "final", "copy", "edit", "fast", "make", "gawin", "lang"}


def hint_words(texts, limit=40):
    """Distinctive words from your instruction and file names (e.g. "search_results.png" ->
    search, results), for the transcriber's hint."""
    out, seen = [], set()
    for text in texts or ():
        for tok in re.split(r"[\s_\-.,;:!?/\\()\[\]\"']+", str(text)):
            low = tok.lower()
            if len(tok) < 3 or low in HINT_STOP or low.isdigit() or low in seen:
                continue
            seen.add(low)
            out.append(tok)
            if len(out) >= limit:
                return out
    return out


def prompt_for(vocab, hints=(), taglish=False):
    """The hint for the transcriber (short): your words first, then words from your instruction
    and file names, then (taglish) a Taglish line that steers spelling."""
    names = list(vocab.get("words", []))
    for c in vocab.get("corrections", []):
        if c["to"] not in names:
            names.append(c["to"])
    known = {n.lower() for n in names}
    names += [h for h in hints or () if h.lower() not in known]
    text = ""
    budget = PROMPT_LIMIT - (len(TAGLISH_STYLE) + 1 if taglish else 0)
    for n in names:
        extra = (", " if text else "") + n
        if len(text) + len(extra) > budget:
            break
        text += extra
    if taglish:
        text = (text + ". " if text else "") + TAGLISH_STYLE
    return text or None


def _tokens(text):
    return [t for t in (normalize(x) for x in str(text).split()) if t]


def apply_corrections(words, corrections):
    """Words (autoedit.words.Word) with every correction applied. Longest phrases first."""
    rules = sorted(((_tokens(c["from"]), c["to"]) for c in corrections if _tokens(c["from"])),
                   key=lambda r: -len(r[0]))
    if not rules:
        return list(words)
    plain = [normalize(w.text) for w in words]
    out, i = [], 0
    while i < len(words):
        for tokens, to in rules:
            n = len(tokens)
            if plain[i:i + n] == tokens:
                last = words[i + n - 1]
                tail = re.search(r"[.,!?;:]*$", last.text).group(0)
                group = words[i:i + n]
                out.append(words[i].copy(text=to + tail, end=last.end,
                                         manual=any(w.manual for w in group),
                                         highlight=any(w.highlight for w in group)))
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return out


def fix_words(words, cfg=None):
    """Apply the saved corrections to a transcript."""
    return apply_corrections(words, load_vocabulary(vocabulary_path(cfg))["corrections"])
