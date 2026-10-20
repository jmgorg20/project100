"""Taglish post-correction: words Whisper nearly got right, put right.

Whisper often hears a Taglish word one letter off ("Tatlo" -> "Tatyo", "hinanap" -> "hinanat").
After transcription each word that is not itself a known word and is exactly one letter away
(one letter changed, added or dropped) from a word of the lexicon becomes that word:

    numbers   isa ... sampu, dalawampu ... siyamnapu (and their -ng forms), daan, libo
    Taglish   the words creators say on camera (follow, followers, checklist, screenshot...)
    yours     the words of your instruction and of your photo / file names

Only words of 5+ letters (4+ for numbers) are touched, the first letter must match, and a word that is close to
two different lexicon words is left alone. Your own corrections (vocabulary.json) still come
first. The transcript file is not changed; the edit and its captions use the corrected words.
"""

import re

from .cues import TENS, UNITS

NUMBERS = {w for w, v in UNITS.items() if v is not None and w.isalpha()} | \
    {f for t in TENS for f in (t, t + "ng")} | {"daan", "daang", "raan", "libo", "libong", "milyon"}
TAGLISH = {
    # what creators say on camera
    "teka", "lang", "sikreto", "viral", "video", "follow", "i-follow", "followers", "follower", "subscribe",
    "mag-subscribe", "comment", "comments", "i-comment", "share", "i-share", "like", "i-like", "search",
    "i-search", "hinanap", "hanapin", "i-type", "screenshot", "screenshots", "resulta", "results",
    "checklist", "storyboard", "analytics", "i-check", "mag-post", "post", "upload", "i-upload", "content",
    "sagutin", "disiplina", "pasensya", "tiyaga", "consistency", "ngayon", "dati", "noon", "pangalawa",
    "pangatlo", "ikalawa", "ikatlo", "tingnan", "tignan", "online", "kumita", "negosyo", "araw", "linggo",
    "buwan", "taon", "minuto", "segundo", "oras", "phone", "cellphone", "editing", "edit", "i-edit",
    "hook", "kwento", "tiktok", "facebook", "youtube", "instagram", "views", "likes", "sales", "benta",
}
# everyday words that are never "corrected" (they are close to a lexicon word but right as heard)
KNOWN = set("""wala walang sana dito diyan doon nito niyan noon iyan iyon ganito ganyan ganoon talaga
siguro pero kasi tapos muna naman lamang lahat dalawa marami konti mabuti maganda masaya salamat
alam gusto ayaw kailangan pwede puwede hindi oo opo meron mayroon walo wari bakit paano saan kailan
sino ano anong ito iyo ikaw kayo sila tayo kami namin natin nila niya akin amin atin kanila kanya
share shame sharing post posts likes lines line time times vibe vibes view video views bigger better
there their these those where which while white write wrote world would could should sales scale""".split())
WORD = re.compile(r"[a-z][a-z'-]*")


def lexicon(extra_texts=()):
    words = NUMBERS | TAGLISH
    for text in extra_texts:
        for tok in WORD.findall(str(text).lower().replace("_", " ")):
            if len(tok) >= 4:
                words.add(tok)
    return words


def one_edit(a, b):
    """True when a and b differ by exactly one letter changed, added or dropped."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1:] == short:
            return True
    return False


def best_match(tok, words):
    """The one lexicon word `tok` is one letter away from (numbers: 4+ letters, others: 5+), or None.
    A plural / singular ("posts", "comment") is a word of its own, never a slip."""
    if len(tok) < 4 or tok in words or tok in KNOWN:
        return None
    hits = {w for w in words if w[0] == tok[0] and one_edit(tok, w) and (len(tok) >= 5 or w in NUMBERS)
            and w + "s" != tok and tok + "s" != w}
    return hits.pop() if len(hits) == 1 else None


def match_case(original, word):
    core = original.strip(".,!?;:\"'()")
    if core.isupper() and len(core) > 1:
        return word.upper()
    if core[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def correct_words(words, extra_texts=(), enabled=True):
    """(words, [(heard, corrected)]). `words`: autoedit.words.Word objects."""
    if not enabled:
        return list(words), []
    lex = lexicon(extra_texts)
    out, changes = [], []
    for w in words:
        m = re.fullmatch(r"([^A-Za-z]*)([A-Za-z][A-Za-z'-]*)([^A-Za-z]*)", w.text)
        fix = best_match(m.group(2).lower(), lex) if m else None
        if fix is None:
            out.append(w)
            continue
        new = m.group(1) + match_case(m.group(2), fix) + m.group(3)
        changes.append((w.text, new))
        out.append(w.copy(text=new))
    return out, changes


def changes_text(changes, limit=8):
    if not changes:
        return ""
    shown = ", ".join(f"'{a}' -> '{b}'" for a, b in changes[:limit])
    more = f" (+{len(changes) - limit} more)" if len(changes) > limit else ""
    return f"Fixed {len(changes)} misheard Taglish word(s): {shown}{more}."
