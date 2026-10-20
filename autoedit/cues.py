"""The cue extractor: what the creator SAYS that asks for a particular graphic, found by plain rules
in the word timestamps (Taglish and English), so the edit has its pop-ups even when no AI answers.

    countdown    spoken counting down: "tatlo... dalawa... isa!", "5, 4, 3, 2, 1"
    keyword      a word said as a heading: "Una: DISIPLINA", "Number one: CONSISTENCY", or in CAPS
    before_after "dati / noon / before ..." then "ngayon / now ...": black-and-white, then colour
    search       "sa search bar, hinanap ko: X", "i-search mo X", "i-type ninyo: X"
    screenshot   "tingnan ninyo ang screenshot / resulta / graph ..."
    checklist    a list after a colon or after "checklist / steps / gamit": "mag-post, sagutin ..., i-check ..."
    platforms    TikTok, Facebook, YouTube, Instagram... named in a sentence
    handle       a social handle: "@akosicreator"
    storyboard   "storyboard / plano / script ko: hook, kwento, call to action"
    stats        spoken numbers with what they count: "mula zero hanggang isang libong followers
                 sa tatlumpung araw" -> 0, 1,000 followers, 30 araw
    follow       "i-follow mo ako", "mag-subscribe"

Every cue keeps the indices of the words it came from (so its graphic starts on the word) and the
exact spoken text of its parts (items, query, numbers): nothing is invented.
"""

import re
from dataclasses import dataclass, field

from .director import norm, shown, strip_marks

# ---------------------------------------------------------------- numbers said in Tagalog / English

UNITS = {
    "zero": 0, "wala": None, "isa": 1, "isang": 1, "dalawa": 2, "dalawang": 2, "tatlo": 3, "tatlong": 3,
    "apat": 4, "lima": 5, "limang": 5, "anim": 6, "pito": 7, "pitong": 7, "walo": 8, "walong": 8,
    "siyam": 9, "sampu": 10, "sampung": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "hundred": 100, "thousand": 1000,
}
TENS = {"dalawampu": 20, "tatlumpu": 30, "apatnapu": 40, "limampu": 50, "animnapu": 60, "pitumpu": 70,
        "walumpu": 80, "siyamnapu": 90}
SCALES = {"daan": 100, "raan": 100, "daang": 100, "raang": 100, "libo": 1000, "libong": 1000,
          "milyon": 1_000_000, "milyong": 1_000_000, "hundred": 100, "thousand": 1000, "k": 1000,
          "million": 1_000_000}
LINKERS = {"na", "at", "and"}


def number_word(tok):
    """The value of one spoken number word ("tatlumpung" -> 30, "isang" -> 1, "1,000" -> 1000)."""
    t = norm(tok)
    digits = strip_marks(tok).strip(".,!?:;").replace(",", "")
    if re.fullmatch(r"\d+(\.\d+)?", digits):
        v = float(digits)
        return int(v) if v == int(v) else v
    if t in UNITS and UNITS[t] is not None:
        return UNITS[t]
    for stem, v in TENS.items():
        if t in (stem, stem + "ng", stem[:-1] + "ong", stem + "'t") or t.startswith(stem + "'t-"):
            return v
    if t.startswith("labing") or t.startswith("labin"):
        rest = t.split("-", 1)[-1] if "-" in t else t[6:]
        if rest in UNITS and UNITS[rest]:
            return 10 + UNITS[rest]
    return None


def read_number(words, i):
    """(value, last index) of a spoken number starting at word i: "isang libong" -> 1000,
    "dalawang daan" -> 200, "tatlumpung" -> 30, "5,000" -> 5000. None when word i is no number."""
    first = number_word(words[i]["text"])
    if first is None:
        return None
    value, j = first, i
    if j + 1 < len(words) and norm(words[j + 1]["text"]) in SCALES and isinstance(value, (int, float)):
        value *= SCALES[norm(words[j + 1]["text"])]
        j += 1
    return value, j


# ---------------------------------------------------------------- word lists

LIST_MARKERS = {"una", "first", "pangalawa", "ikalawa", "second", "pangatlo", "ikatlo", "third", "ikaapat",
                "fourth", "huli", "lastly", "finally", "number"}
BEFORE = {"dati", "noon", "noong", "before", "dati-rati", "nakaraan"}
AFTER = {"ngayon", "now", "today", "pero ngayon"}
SEARCH_VERBS = {"hinanap", "hanapin", "hinahanap", "i-search", "isearch", "search", "i-type", "itype", "type",
                "i-google", "google", "sinearch"}
SCREEN_WORDS = {"screenshot", "screenshots", "resulta", "results", "result", "graph", "chart", "dashboard",
                "proof", "sales", "analytics", "stats", "litrato", "picture", "photo", "screen"}
LOOK_WORDS = {"tingnan", "tignan", "look", "see", "kita", "makikita"}
LIST_HEADS = {"checklist", "steps", "hakbang", "gamit", "kailangan", "listahan", "list", "tips", "routine"}
PLAN_HEADS = {"storyboard", "plano", "plan", "script", "outline", "eksena", "scenes", "flow"}
FOLLOW = {"follow", "i-follow", "ifollow", "subscribe", "mag-subscribe", "sundan", "i-like", "like"}
PLATFORMS = {"tiktok": "TikTok", "facebook": "Facebook", "fb": "Facebook", "youtube": "YouTube",
             "instagram": "Instagram", "ig": "Instagram", "twitter": "X", "threads": "Threads",
             "linkedin": "LinkedIn", "shopee": "Shopee", "lazada": "Lazada", "spotify": "Spotify",
             "snapchat": "Snapchat", "pinterest": "Pinterest", "twitch": "Twitch", "kumu": "Kumu",
             "telegram": "Telegram", "whatsapp": "WhatsApp", "viber": "Viber", "messenger": "Messenger",
             "gcash": "GCash", "canva": "Canva", "capcut": "CapCut", "chatgpt": "ChatGPT"}
RECAP = {"kaya", "recap", "tandaan", "summary", "so", "basically", "madaling", "lahat"}
SCHEDULE = {"timeline", "schedule", "routine", "araw-araw", "everyday", "linggo-linggo", "gabi-gabi",
            "umaga-umaga", "iskedyul"}
COMMENT = {"comment", "comments", "i-comment", "icomment", "mag-comment", "dm", "i-dm", "message", "i-message",
           "tanong", "tanungin", "magtanong"}
PHONE = {"phone", "cellphone", "cp", "app", "mobile", "selpon"}
STOP_ITEM = {"ang", "ng", "sa", "mga", "the", "a", "an", "my", "ko", "mo", "and", "at", "tsaka", "saka"}
STAT_STOP = {"sa", "ng", "na", "in", "of", "the", "loob"}


@dataclass
class Cue:
    kind: str
    i0: int                      # first word of the cue (the graphic starts on it)
    i1: int                      # last word
    text: str = ""               # a title, a query, a handle
    items: list = field(default_factory=list)       # [(word index, text)] in spoken order
    number: object = None
    priority: int = 5

    def as_dict(self, words):
        return {"kind": self.kind, "start": round(words[self.i0]["start"], 3), "end": round(words[self.i1]["end"], 3),
                "text": self.text, "items": [t for _i, t in self.items], "number": self.number}


GLUE = {"sa", "ng", "ang", "na", "at", "and", "mga", "the", "of", "to", "kung", "para", "si", "ni"}


def punctuated(words):
    """True when the transcript has sentence punctuation (Groq's word timestamps have none)."""
    ends = sum(1 for w in words if re.search(r"[.?!…]$", strip_marks(w["text"]).strip("\"'")))
    return ends * 25 >= len(words)


def sentence_spans(words):
    """[(first, last)] word indices of each sentence: ended by . ? ! or a long pause. Without
    punctuation (real Whisper word timestamps): also by a short pause before a capital letter, or
    a clear pause - never right after a word that needs what follows ("sa", "ng", "ang"...)."""
    out, start = [], 0
    plain = not punctuated(words)
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = nxt["start"] - w["end"] if nxt else None
        end = nxt is None or re.search(r"[.?!…]$", strip_marks(w["text"]).strip("\"'")) or gap > 0.9
        if not end and plain and norm(w["text"]) not in GLUE:
            first = strip_marks(nxt["text"]).lstrip("\"'(")
            capital = first[:1].isupper() and not first.isupper() and norm(nxt["text"]) not in PLATFORMS
            end = (capital and gap >= 0.1) or gap >= 0.35
        if end:
            out.append((start, i))
            start = i + 1
    return out


def ends_with(word, chars):
    return strip_marks(word["text"]).rstrip("\"'").endswith(tuple(chars))


def phrase(words, idx):
    return " ".join(shown(words[i]) for i in idx if shown(words[i]))


def split_items(words, lo, hi):
    """Spoken list items between word lo and hi: split at commas and at a last "at / and / tsaka"."""
    groups, cur = [], []
    for i in range(lo, hi + 1):
        tok = norm(words[i]["text"])
        if tok in ("at", "and", "tsaka", "saka") and cur:
            groups.append(cur)
            cur = []
            continue
        cur.append(i)
        if ends_with(words[i], ",;"):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    items = []
    for g in groups:
        while g and norm(words[g[0]]["text"]) in STOP_ITEM | {"ang"}:
            g = g[1:]
        if g:
            items.append((g[0], phrase(words, g)[:40]))
    return items


VERB_PREFIXES = ("mag-", "i-", "ipa-", "maki-", "pag-", "mang-", "ma-")
EN_VERBS = {"post", "check", "reply", "answer", "edit", "upload", "film", "shoot", "write", "read", "plan",
            "share", "follow", "comment", "like", "save", "open", "add", "make", "use", "try", "start", "go"}


def starts_item(word):
    """A word that starts a spoken list item: a Tagalog verb form (mag-post, i-check, sagutin,
    gawin) or an English verb."""
    t = norm(word["text"])
    return t.startswith(VERB_PREFIXES) or t in EN_VERBS or (len(t) >= 5 and t.endswith(("in", "hin")) and
                                                              t not in ("online", "admin", "begin"))


def split_spoken(words, lo, hi):
    """List items said without commas: a new item at each verb form or clear pause."""
    groups, cur = [], []
    for i in range(lo, hi + 1):
        if cur and (starts_item(words[i]) or words[i]["start"] - words[i - 1]["end"] >= 0.3):
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    items = [(g[0], phrase(words, g)[:40]) for g in groups if g]
    return items if all(len(t.split()) <= 5 for _k, t in items) else []


# ---------------------------------------------------------------- the rules

def near_number(words, i):
    """read_number, or for a word one letter off a number word ("Tatyo") its number, when the
    next word is a number too (a countdown said out loud)."""
    r = read_number(words, i)
    if r is not None or i + 1 >= len(words) or read_number(words, i + 1) is None:
        return r
    from .taglish import NUMBERS, best_match
    fix = best_match(norm(words[i]["text"]), NUMBERS)
    return (number_word(fix), i) if fix else None


def find_countdown(words):
    out, i = [], 0
    while i < len(words):
        r = near_number(words, i)
        if r is None:
            i += 1
            continue
        seq = [(i, r[0])]
        j = r[1] + 1
        while j < len(words):
            nxt = near_number(words, j)
            if nxt is None or nxt[0] != seq[-1][1] - 1 or words[j]["start"] - words[seq[-1][0]]["end"] > 1.6:
                break
            seq.append((j, nxt[0]))
            j = nxt[1] + 1
        if len(seq) >= 3 and seq[-1][1] in (0, 1):
            out.append(Cue("countdown", seq[0][0], seq[-1][0], number=int(seq[0][1]),
                           items=[(k, str(v)) for k, v in seq], priority=9))
            i = j
        else:
            i += 1
    return out


def find_keywords(words, spans):
    out = []
    for a, b in spans:
        toks = [norm(words[k]["text"]) for k in range(a, b + 1)]
        # "Una: DISIPLINA" / "Number one: X" - the words after a list marker and a colon
        for k in range(a, b):
            if toks[k - a] in LIST_MARKERS and any(ends_with(words[m], ":") for m in range(k, min(k + 2, b))):
                colon = next(m for m in range(k, min(k + 2, b)) if ends_with(words[m], ":"))
                head = [m for m in range(colon + 1, min(colon + 4, b + 1))]
                if head:
                    out.append(Cue("keyword", k, head[-1], text=phrase(words, head), priority=8))
                break
        else:
            # "Una disiplina" (no colon, no caps: real Whisper words) - a list marker, then 1-2 words
            if toks[0] in LIST_MARKERS - {"number", "huli"} and 1 <= b - a <= 2 and \
                    all(len(t) >= 3 and t not in STOP_ITEM for t in toks[1:]):
                out.append(Cue("keyword", a, b, text=phrase(words, range(a + 1, b + 1)).upper(), priority=8))
                continue
            caps = [k for k in range(a, b + 1) if len(shown(words[k])) >= 4 and shown(words[k]).isupper()
                    and not shown(words[k]).isdigit()]
            if caps:
                out.append(Cue("keyword", caps[0], caps[-1], text=phrase(words, caps), priority=7))
    return out


def find_before_after(words, spans):
    out = []
    for n, (a, b) in enumerate(spans):
        first = norm(words[a]["text"])
        if first not in BEFORE:
            continue
        for a2, b2 in spans[n + 1:n + 3]:
            if norm(words[a2]["text"]) in AFTER or norm(words[min(a2 + 1, b2)]["text"]) in AFTER:
                if words[a2]["start"] - words[a]["start"] <= 10:
                    out.append(Cue("before_after", a, a2 - 1, text=phrase(words, range(a, b + 1)),
                                   items=[(a2, phrase(words, range(a2, b2 + 1)))], priority=8))
                break
    return out


def find_search(words, spans):
    out = []
    for a, b in spans:
        toks = [norm(words[k]["text"]) for k in range(a, b + 1)]
        verbs = [a + k for k, t in enumerate(toks) if t in SEARCH_VERBS]
        if not verbs:
            continue
        v = verbs[-1]
        start = v + 1
        colon = next((m for m in range(v, b + 1) if ends_with(words[m], ":")), None)
        if colon is not None:
            start = colon + 1
        while start <= b and norm(words[start]["text"]) in {"mo", "ko", "lang", "ninyo", "nyo", "ang", "sa", "the",
                                                             "for", "na", "natin"}:
            start += 1
        query = list(range(start, min(b, start + 7) + 1))
        if query:
            out.append(Cue("search", a, query[-1], text=phrase(words, query)[:60], items=[(query[0], "")],
                           priority=9))
    return out


def find_screenshots(words, spans):
    out = []
    for a, b in spans:
        toks = {norm(words[k]["text"]) for k in range(a, b + 1)}
        if toks & SCREEN_WORDS and (toks & LOOK_WORDS or toks & {"screenshot", "screenshots"}):
            key = next(k for k in range(a, b + 1) if norm(words[k]["text"]) in SCREEN_WORDS)
            cue = Cue("screenshot", a, b, text=phrase(words, range(a, b + 1)),
                      items=[(k, norm(words[k]["text"])) for k in range(a, b + 1)
                             if len(norm(words[k]["text"])) > 2], number=key, priority=7)
            cue.phone = bool(toks & PHONE)          # "sa phone / app ko": in a phone frame
            out.append(cue)
    return out


def find_lists(words, spans):
    out = []
    plain = not punctuated(words)
    for n, (a, b) in enumerate(spans):
        toks = [norm(words[k]["text"]) for k in range(a, b + 1)]
        colon = next((k for k in range(a, b) if ends_with(words[k], ":")), None)
        head = {t for t in toks[:max(1, (colon - a + 1) if colon is not None else len(toks))]}
        kind = "storyboard" if head & PLAN_HEADS else "checklist" if (head & LIST_HEADS or colon is not None) else None
        if kind is None:
            continue
        lo = colon + 1 if colon is not None else a + next(k for k, t in enumerate(toks) if t in PLAN_HEADS | LIST_HEADS) + 1
        items = split_items(words, lo, b)
        head_end = None
        if len(items) < 2 and plain and n + 1 < len(spans) and \
                words[spans[n + 1][0]]["start"] - words[b]["end"] <= 1.5:
            # "Ito ang checklist ko sa phone" / "Mag-post sagutin ang comments i-check ang analytics"
            a2, b2 = spans[n + 1]
            nxt = split_items(words, a2, b2)
            if len(nxt) < 2:
                nxt = split_spoken(words, a2, b2)
            if len(nxt) >= 2:
                items, head_end, b = nxt, b, b2
        if len(items) >= 2 and all(len(t.split()) <= 5 for _i, t in items):
            head_idx = list(range(a, lo if head_end is None else head_end + 1))
            while head_idx and norm(words[head_idx[0]]["text"]) in STOP_ITEM | {"ito", "eto", "heto", "here", "is",
                                                                                 "this", "ang", "mga"}:
                head_idx = head_idx[1:]
            title = phrase(words, head_idx[:5])[:30]
            out.append(Cue(kind, a, b, text=title, items=items[:5], priority=8))
    return out


def find_platforms(words, spans):
    out = []
    for a, b in spans:
        found, seen = [], set()
        for k in range(a, b + 1):
            name = PLATFORMS.get(norm(words[k]["text"]))
            if name and name not in seen:
                seen.add(name)
                found.append((k, name))
        if found:
            out.append(Cue("platforms", found[0][0], b, items=found, priority=8))
    return out


def find_handles(words):
    out = []
    for k, w in enumerate(words):
        tok = strip_marks(w["text"]).strip(".,!?:;\"'()")
        if re.fullmatch(r"@[A-Za-z0-9_.]{2,30}", tok):
            out.append(Cue("handle", k, k, text=tok.rstrip("."), priority=8))
    return out


def find_stats(words, spans):
    """Sentences with two or more spoken numbers (not a countdown): each number with the word that
    says what it counts ("isang libong followers" -> 1,000 followers)."""
    out = []
    for a, b in spans:
        vals, k = [], a
        while k <= b:
            r = read_number(words, k)
            if r is None or (norm(words[k]["text"]) in ("isa", "isang") and r[1] == k and
                             not (k + 1 <= b and norm(words[k + 1]["text"]) not in STAT_STOP)):
                k += 1
                continue
            label_at = r[1] + 1
            while label_at <= b and norm(words[label_at]["text"]) in STAT_STOP:
                label_at += 1
            label = shown(words[label_at]) if label_at <= b and read_number(words, label_at) is None and \
                norm(words[label_at]["text"]) not in ("hanggang", "to", "until", "at") else ""
            vals.append((k, r[0], label))
            k = r[1] + 1
        if len(vals) >= 2:
            items = [(k, f"{fmt_number(v)} {label}".strip()) for k, v, label in vals]
            out.append(Cue("stats", vals[0][0], b, items=items[:4], priority=7))
    return out


def fmt_number(v):
    if isinstance(v, float) and v != int(v):
        return f"{v:g}"
    return f"{int(v):,}"


def find_follow(words, spans):
    out = []
    for a, b in spans:
        hit = next((k for k in range(a, b + 1) if norm(words[k]["text"]) in FOLLOW), None)
        if hit is not None:
            out.append(Cue("follow", a, b, text=phrase(words, range(a, b + 1)), number=hit, priority=7))
    return out


def find_recap(words, spans):
    """A sentence that sums up ("Kaya tandaan...", "In short...", "Sa madaling salita..."): a mosaic of
    what was said before it."""
    out = []
    for a, b in spans[1:]:
        first = {norm(words[k]["text"]) for k in range(a, min(a + 3, b + 1))}
        if first & RECAP and (first & {"tandaan", "recap", "summary", "madaling", "lahat"} or "in" in first):
            out.append(Cue("recap", a, b, text=phrase(words, range(a, b + 1)), priority=6))
    return out


def find_schedule(words, spans, taken):
    out = []
    for a, b in spans:
        if any(a <= k <= b for k in taken):
            continue
        hit = next((k for k in range(a, b + 1) if norm(words[k]["text"]) in SCHEDULE), None)
        if hit is not None:
            colon = next((k for k in range(a, b) if ends_with(words[k], ":")), None)
            items = split_items(words, colon + 1, b) if colon is not None else []
            out.append(Cue("timeline", a, b, text=shown(words[hit]), items=items[:4] if len(items) >= 2 else [],
                           priority=6))
    return out


def find_comments(words, spans, taken):
    out = []
    for a, b in spans:
        if any(a <= k <= b for k in taken):
            continue
        hit = next((k for k in range(a, b + 1) if norm(words[k]["text"]) in COMMENT), None)
        if hit is not None:
            out.append(Cue("comment", a, b, text=phrase(words, range(a, b + 1)), number=hit, priority=6))
    return out


def extract(words):
    """Every cue in the words, in spoken order. Overlapping cues of the same sentence are kept (the
    planner decides which become graphics)."""
    if not words:
        return []
    spans = sentence_spans(words)
    countdowns = find_countdown(words)
    counted = {k for c in countdowns for k in range(c.i0, c.i1 + 1)}
    cues = countdowns + find_keywords(words, spans) + find_before_after(words, spans) + \
        find_search(words, spans) + find_screenshots(words, spans) + find_lists(words, spans) + \
        find_platforms(words, spans) + find_handles(words) + \
        [c for c in find_stats(words, spans) if not counted & set(range(c.i0, c.i1 + 1))] + \
        find_follow(words, spans) + find_recap(words, spans)
    # a list of what is done every day ("Ang routine ko araw-araw: gising, kape, edit") is a timeline
    for c in cues:
        if c.kind == "checklist" and any(norm(words[k]["text"]) in SCHEDULE for k in range(c.i0, c.items[0][0])):
            hit = next(k for k in range(c.i0, c.items[0][0]) if norm(words[k]["text"]) in SCHEDULE)
            c.kind, c.text = "timeline", shown(words[hit]).strip(".,!?:;")
    # a summing-up sentence with a list ("Kaya tandaan: plano, routine, at pahinga") is a recap of those
    for r in [c for c in cues if c.kind == "recap"]:
        lst = next((c for c in cues if c.kind == "checklist" and c.i0 <= r.i1 and r.i0 <= c.i1), None)
        if lst is not None:
            r.items = lst.items
            cues.remove(lst)
    # schedules and comments only where nothing else was said (a list, a before / after...)
    taken = {k for c in cues if c.kind in ("checklist", "storyboard", "before_after", "search", "follow", "timeline", "recap")
             for k in range(c.i0, (c.items[-1][0] if c.kind == "before_after" else c.i1) + 1)}
    cues += find_schedule(words, spans, taken) + find_comments(words, spans, taken)
    # the word to comment ("Comment mo ang salitang GUIDE") is the comment card's, not a title of its own
    asked = [(c.i0, c.i1) for c in cues if c.kind == "comment"]
    cues = [c for c in cues if not (c.kind == "keyword" and any(a <= c.i0 <= b for a, b in asked))]
    # a platform named inside a search query ("i-search mo ... sa YouTube") is part of the query
    queried = [(c.items[0][0], c.i1) for c in cues if c.kind == "search"]
    for c in cues:
        if c.kind == "platforms":
            c.items = [(k, n) for k, n in c.items if not any(a <= k <= b for a, b in queried)]
    cues = [c for c in cues if c.kind != "platforms" or c.items]
    # a list sentence is not also a search / stats cue
    listed = {(c.i0, c.i1) for c in cues if c.kind in ("checklist", "storyboard", "timeline")}
    cues = [c for c in cues if not (c.kind in ("stats",) and any(a <= c.i0 <= b for a, b in listed))]
    return sorted(cues, key=lambda c: (words[c.i0]["start"], -c.priority))
