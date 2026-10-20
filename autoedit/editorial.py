"""The editorial planner: the Director of the PREMIUM EDITORIAL VIRAL style.

Where the other looks add a pop-up here and there, this one edits scene by scene:

    scenes   the spoken words are cut into scenes of about 2-4 seconds (sentences; long ones split
             at their longest pause, short ones joined), so the picture changes every 2-4 s
    beats    each scene gets ONE main idea (a "beat") that suits what is said in it:
               type       editorial headline, kinetic words, marker highlight, subtitle card
               card       checklist, UI panel, search bar, countdown, palette, profile, logo
               cover      your screenshots / photos: collage, montage, mosaic, phone, storyboard,
                          with the talking head dimmed, blurred and vignetted underneath
               pip        one of your clips (or photos) floating as a rounded picture-in-picture
               camera     a slow push-in or a smooth zoom-out (reframing) on the talking head
             plus, between scenes, a black-and-white transition on a turn in the story (pero,
             but, dati...), and a punch-in on the key word of a type beat
    words    every element is timed to the exact spoken words: a graphic starts on its word, and
             its parts (words, items, ticks, typed letters, pictures) appear on theirs (`cues`)
    yours    only the creator's own pictures, clips, logo and handle are used: nothing is
             downloaded, generated or invented; a beat that needs a picture is skipped without one

The AI (when there is one) chooses the beat and the words for each scene from a menu; plain code
then checks every choice against the transcript and the creator's files, keeps variety (never the
same beat twice in a row, big picture beats spaced out) and timing, and falls back to the rules
for anything that does not hold. Without an AI the rules choose the beats.

Everything it adds is ordinary, editable clips: graphics on the Graphics tracks (with a
`director` note), effect clips on "Editorial ..." effect tracks and PiP clips on an overlay track
(ids starting "pe"), so running it again replaces its own work and keeps locked clips.
"""

import copy
import json
import math
import re
from collections import Counter

from . import cues as cues_mod
from . import director, graphics, zones
from .director import Ctx, important, locate, norm, shown, snap, strip_marks
from . import steplog
from .errors import Cancelled
from .llm import LLMError, RequestLog, ask_json, estimate_tokens

STYLE = "premium_editorial"
PROMPT_VERSION = 2
MAX_ATTEMPTS = 2
SCENE_MIN, SCENE_MAX = 1.6, 4.2
LIST_MAX = 8.0
EPS = 1e-6

# id -> template (None = no graphic), kind, what it needs, what it is for (the AI's menu)
BEATS = {
    "headline": ("editorial-headline", "type", "", "a serif magazine headline of the key phrase (the hook, a big claim)"),
    "kinetic": ("kinetic-words", "type", "", "2-5 big words popping in one by one as they are said"),
    "marker": ("marker-highlight", "type", "", "the sentence on paper, a marker sweeping over its keyword"),
    "subtitle": ("subtitle-card", "type", "", "a cream card with the line being said (only without captions)"),
    "checklist": ("editorial-checklist", "card", "items", "a list that ticks each item as it is said (2-5 items)"),
    "ui_panel": ("ui-panel", "card", "items", "an app window whose switches turn on as each item is said"),
    "search": ("search-bar", "card", "query", "a search bar typing what the creator says to search"),
    "countdown": ("countdown-timer", "card", "number", "a countdown from a number of seconds / minutes said"),
    "palette": ("palette-card", "card", "palette", "colour swatches taken from the creator's picture"),
    "profile": ("profile-card", "card", "profile", "the creator's profile card with a Follow button (a follow / subscribe call)"),
    "logo": ("logo-badge", "card", "logo", "the creator's own logo with the brand name"),
    "collage": ("screenshot-collage", "cover", "images2", "2-4 of the creator's screenshots floating in"),
    "montage": ("screenshot-montage", "cover", "images3", "one card sliding through 3-6 screenshots"),
    "mosaic": ("mosaic-grid", "cover", "images4", "a grid of 4-9 of the creator's pictures"),
    "phone": ("phone-mockup", "cover", "image", "one screenshot inside a floating phone"),
    "storyboard": ("storyboard-doc", "cover", "items", "a storyboard page: the steps of a plan with pictures"),
    "pip": (None, "pip", "clip", "one of the creator's clips or photos floating as a rounded picture-in-picture"),
    "camera": (None, "camera", "", "no graphic: a slow push-in on the speaker (a quiet beat)"),
    # set only by what is said (cues.py), never chosen from the menu
    "before_after": (None, "look", "", "black and white while the past is told, colour again on 'ngayon'"),
    "screenshot": ("screenshot-collage", "cover", "image", "your screenshots, matched to what is said"),
    "platforms": ("app-tile", "card", "", "an app tile for each platform named (your logo files, else the name)"),
    "stats": ("stat-cards", "card", "", "the numbers said, each with what it counts"),
    "magazine": ("magazine-cover", "cover", "", "the opening as a magazine cover: the hook word and what is coming"),
    "recap": ("tile-mosaic", "cover", "", "a mosaic of word tiles: what was said, summed up"),
    "timeline": ("timeline-card", "card", "", "an editing timeline card for a routine / schedule"),
    "comment": ("chat-cards", "card", "", "a comment card typing the line said (a comment / DM call)"),
}
CUE_ONLY = {"before_after", "screenshot", "platforms", "stats", "magazine", "recap", "timeline", "comment"}
BIG_CARDS = {"countdown-timer", "editorial-checklist", "storyboard-doc", "search-bar", "stat-cards", "kinetic-words",
             "editorial-headline", "magazine-cover", "tile-mosaic", "timeline-card", "chat-cards", "strike-text",
             "phone-mockup"}
CUE_BEAT = {"pin": "screenshot", "countdown": "countdown", "keyword": "kinetic", "before_after": "before_after", "search": "search",
            "screenshot": "screenshot", "checklist": "checklist", "platforms": "platforms", "handle": "profile",
            "storyboard": "storyboard", "stats": "stats", "follow": "profile", "recap": "recap",
            "timeline": "timeline", "comment": "comment", "magazine": "magazine"}
TIME_WORDS = {"dati", "noon", "before", "ngayon", "now", "pero", "but", "today", "at", "and"}
MAGAZINE_MIN = 5                   # spoken cues that made a graphic before the opening becomes a cover (it
                                   # promises what is coming, so only when there is plenty)
COVER_SHARE = 0.4                  # at most this share of the scenes are big picture beats
ONCE = {"profile", "logo", "countdown", "palette", "storyboard"}
BW_GAP = 12.0
PIP_BOX = {"x": 790, "y": 560, "width": 400, "height": 620}
NOT_YOURS = {"pexels", "pixabay", "stock", "ai"}

LIST_MARKERS = {"una", "first", "pangalawa", "ikalawa", "second", "pangatlo", "ikatlo", "third", "next",
                "sunod", "susunod", "finally", "lastly", "huli", "step", "tip", "number", "isa", "dalawa",
                "tatlo", "one", "two", "three", "four", "five"}
SEARCH_WORDS = {"search", "i-search", "isearch", "google", "hanapin", "hinanap", "i-type", "type", "youtube"}
COUNT_UNITS = {"second", "seconds", "segundo", "segundos", "sec", "minute", "minutes", "minuto", "minutos",
               "hour", "hours", "oras", "day", "days", "araw"}
COUNT_WORDS = {"countdown", "bilang", "timer"}
COLOUR_WORDS = {"color", "colors", "colour", "colours", "kulay", "palette", "shade", "shades", "aesthetic"}
FOLLOW_WORDS = {"follow", "i-follow", "ifollow", "subscribe", "mag-subscribe", "sundan", "followers"}
SCREEN_WORDS = {"app", "apps", "website", "site", "screen", "screenshot", "screenshots", "dashboard", "phone",
                "cellphone", "page", "results", "resulta", "sales", "proof", "review", "reviews", "comments",
                "messages", "orders", "stats", "analytics", "photos", "pictures", "litrato", "picture", "tingnan"}
PLAN_WORDS = {"plan", "planning", "storyboard", "script", "scene", "scenes", "eksena", "outline", "structure",
              "process", "proseso"}
SETUP_WORDS = {"setup", "settings", "tools", "features", "equipment", "gamit", "steps", "hakbang", "checklist",
               "kailangan", "requirements"}
BRAND_WORDS = {"brand", "logo", "partner", "sponsor", "company", "negosyo", "business", "shop", "store"}
TURN_WORDS = {"pero", "but", "however", "dati", "before", "noon", "kaso", "instead", "imbes", "ngayon", "now"}


class Scene:
    def __init__(self, index, i0, i1, start, end):
        self.index, self.i0, self.i1, self.start, self.end = index, i0, i1, start, end

    @property
    def duration(self):
        return self.end - self.start

    def as_dict(self):
        return {"index": self.index, "start": round(self.start, 3), "end": round(self.end, 3)}


# ---------------------------------------------------------------- the creator's own files

# words that mean the same thing in a file name and in what is said (Taglish / English)
MEANING = [{"resulta", "result", "results", "outcome", "proof"}, {"benta", "sales", "sale", "sold", "orders", "order"},
           {"kita", "kinita", "income", "earnings", "profit", "kumita"}, {"larawan", "litrato", "picture", "photo", "pic"},
           {"screenshot", "screen", "ss"}, {"komento", "comment", "comments"}, {"review", "reviews", "feedback"},
           {"analytics", "stats", "insights", "dashboard", "graph", "chart"}, {"followers", "follower", "fans"},
           {"menu", "presyo", "price", "prices"}, {"produkto", "product", "products", "item"}]


def same_meaning(a, b):
    a, b = a.lower(), b.lower()
    return any(a in g and b in g for g in MEANING)


class Assets:
    """The creator's pictures and clips in the project (the main video and sound files excluded)."""

    def __init__(self, project, cfg, base_dir=None):
        main = {c.get("media") for t in project["tracks"] if t["kind"] == "video" for c in t["clips"]}
        main |= {(c.get("layout") or {}).get("screen") for t in project["tracks"] if t["kind"] == "video"
                 for c in t["clips"]}
        # free stock and AI-made B-roll are not the creator's own files
        sourced = {c.get("media") for t in project["tracks"] for c in t["clips"]
                   if str((c.get("broll") or {}).get("source") or "") in NOT_YOURS}
        self.base_dir = base_dir
        self.images, self.videos, self.logo, self.avatar = [], [], None, None
        self.platform_logos = {}          # "tiktok" -> media id of YOUR tiktok_logo.png
        self.names = {}                   # media id -> file name
        for m in project["media"]:
            if m["id"] in main or m["id"] in sourced:
                continue
            fname = m.get("name") or m["path"].replace("\\", "/").split("/")[-1]
            self.names[m["id"]] = fname
            name = fname.lower()
            if m["kind"] == "image":
                platform = next((k for k in cues_mod.PLATFORMS if len(k) > 2 and k in name), None)
                if platform and ("logo" in name or "icon" in name or re.sub(r"[^a-z]", "", name.rsplit(".", 1)[0]) == platform):
                    self.platform_logos.setdefault(cues_mod.PLATFORMS[platform].lower(), m["id"])
                elif "logo" in name and self.logo is None:
                    self.logo = m["id"]
                elif any(k in name for k in ("avatar", "profile", "headshot")) and self.avatar is None:
                    self.avatar = m["id"]
                else:
                    self.images.append(m["id"])
            elif m["kind"] == "video":
                self.videos.append(m["id"])
        ed = (cfg.get("editorial") or {}) if isinstance(cfg, dict) else {}
        self.name = str(ed.get("name") or "").strip()[:28]
        self.handle = str(ed.get("handle") or "").strip()[:28]
        self.brand = str(ed.get("brand") or "").strip()[:28]
        self.media = {m["id"]: m for m in project["media"]}

    def path(self, media_id):
        from .project import resolve_media_path
        return resolve_media_path(self.media[media_id], self.base_dir or ".")

    def summary(self):
        return {"images": list(self.images), "videos": list(self.videos), "logo": self.logo, "avatar": self.avatar,
                "platform_logos": dict(self.platform_logos)}

    def name_parts(self, mid):
        """The words of a file name ("Search Result.PNG" -> ["search", "result"])."""
        return [p for p in re.split(r"[^a-z0-9]+", self.names.get(mid, "").lower().rsplit(".", 1)[0]) if len(p) >= 3]

    def name_matches(self, mid, tokens):
        """The spoken words that match the file's name: by spelling (a shared 5-letter start:
        "resulta" ~ "result"), or by meaning in Taglish / English ("benta" ~ "sales")."""
        hits = []
        for t in tokens:
            t = norm(t)
            if len(t) < 3:
                continue
            for part in self.name_parts(mid):
                if (len(t) >= 4 and len(part) >= 4 and part[:5] == t[:5]) or same_meaning(part, t):
                    hits.append(t)
                    break
        return hits

    def matching_images(self, tokens):
        """Your screenshots, the ones whose file names match the spoken words first."""
        return sorted(self.images, key=lambda mid: (-len(self.name_matches(mid, tokens)), self.images.index(mid)))

    def satisfies(self, need, scene_info=None):
        if need == "images2":
            return len(self.images) >= 2
        if need == "images3":
            return len(self.images) >= 3
        if need == "images4":
            return len(self.images) >= 4
        if need == "image":
            return bool(self.images)
        if need == "logo":
            return self.logo is not None
        if need == "clip":
            return bool(self.videos or self.images)
        if need == "palette":
            return bool(self.images or self.logo)
        if need == "profile":
            return bool(self.name or self.handle)       # never a made-up name
        return True


# ---------------------------------------------------------------- scenes

def make_scenes(words, duration):
    """Scenes of about 2-4 s on sentence boundaries: long sentences split at their longest pause,
    short ones joined to the next."""
    if not words:
        return []
    groups = []
    for sent in director.sentences(words):
        pending = [sent]
        while pending:
            g = pending.pop(0)
            span = words[g[-1]]["end"] - words[g[0]]["start"]
            # a spoken list stays one scene (its checklist ticks every item), up to LIST_MAX
            listed = sum(1 for i in g if norm(words[i]["text"]) in LIST_MARKERS) >= 2 and span <= LIST_MAX
            if span > SCENE_MAX and len(g) >= 4 and not listed:
                # split near the middle, at the biggest gap between words
                mid_t = words[g[0]]["start"] + span / 2
                cuts = range(1, len(g))
                k = max(cuts, key=lambda c: (words[g[c]]["start"] - words[g[c - 1]]["end"])
                        - 0.25 * abs(words[g[c]]["start"] - mid_t))
                pending[:0] = [g[:k], g[k:]]
            else:
                groups.append(g)
    merged = []
    for g in groups:
        if merged:
            prev = merged[-1]
            prev_span = words[prev[-1]]["end"] - words[prev[0]]["start"]
            both = words[g[-1]]["end"] - words[prev[0]]["start"]
            if prev_span < SCENE_MIN and both <= SCENE_MAX + 0.6:
                merged[-1] = prev + g
                continue
        merged.append(g)
    if len(merged) > 1:
        last = merged[-1]
        if words[last[-1]]["end"] - words[last[0]]["start"] < SCENE_MIN * 0.75:
            merged[-2] = merged[-2] + last
            merged.pop()
    scenes = []
    for k, g in enumerate(merged):
        start = words[g[0]]["start"] if k else 0.0
        end = words[merged[k + 1][0]]["start"] if k + 1 < len(merged) else max(duration, words[g[-1]]["end"])
        scenes.append(Scene(k, g[0], g[-1], start, end))
    return scenes


def scene_tokens(ctx, scene):
    return [norm(w["text"]) for w in ctx.words[scene.i0:scene.i1 + 1]]


def scene_text(ctx, scene):
    return " ".join(strip_marks(w["text"]) for w in ctx.words[scene.i0:scene.i1 + 1])


# ---------------------------------------------------------------- what is said (rules)

def keyword_index(ctx, scene):
    """The strongest word of a scene: a highlighted / mood / number word, else the longest."""
    idx = [i for i in range(scene.i0, scene.i1 + 1) if important(ctx.words[i]["text"])]
    if not idx:
        return None

    def strength(i):
        tok = norm(ctx.words[i]["text"])
        moody = any(tok in vocab for vocab in director.MOOD_WORDS.values())
        return (ctx.words[i]["hl"], tok.isdigit(), moody, len(tok))
    return max(idx, key=strength)


def phrase_around(ctx, scene, k, max_words=6, max_chars=48):
    """Word indices of a short phrase of the scene around word k (in spoken order)."""
    lo, hi = k, k
    while hi - lo + 1 < max_words:
        grew = False
        if hi < scene.i1:
            hi += 1
            grew = True
        if hi - lo + 1 < max_words and lo > scene.i0:
            lo -= 1
            grew = True
        if not grew:
            break
        if len(" ".join(shown(ctx.words[i]) for i in range(lo, hi + 1))) > max_chars:
            break
    # drop filler at the edges
    while lo < k and not important(ctx.words[lo]["text"]):
        lo += 1
    while hi > k and not important(ctx.words[hi]["text"]):
        hi -= 1
    return list(range(lo, hi + 1))


def numbers_in(ctx, scene):
    out = []
    for i in range(scene.i0, scene.i1 + 1):
        tok = strip_marks(ctx.words[i]["text"]).strip(".,!?").replace(",", "")
        if re.fullmatch(r"\d+(\.\d+)?", tok):
            out.append((i, float(tok)))
    return out


def list_items(ctx, scene, limit=5):
    """Items of a spoken list: the words after each list marker ("una ..., pangalawa ...")."""
    toks = scene_tokens(ctx, scene)
    marks = [scene.i0 + j for j, t in enumerate(toks) if t in LIST_MARKERS]
    if len(marks) < 2:
        # "X, Y at Z" - three or more comma-separated chunks
        chunks, cur = [], []
        for i in range(scene.i0, scene.i1 + 1):
            cur.append(i)
            if ctx.words[i]["text"].rstrip().endswith(",") or norm(ctx.words[i]["text"]) in ("at", "and", "tsaka"):
                if any(important(ctx.words[j]["text"]) for j in cur):
                    chunks.append(cur)
                cur = []
        if cur and any(important(ctx.words[j]["text"]) for j in cur):
            chunks.append(cur)
        if len(chunks) < 3:
            return []
        groups = chunks
    else:
        groups = [list(range(m + 1, (marks[n + 1] if n + 1 < len(marks) else scene.i1 + 1)))
                  for n, m in enumerate(marks)]
    items = []
    for g in groups:
        keep = [i for i in g if important(ctx.words[i]["text"]) and norm(ctx.words[i]["text"]) not in LIST_MARKERS]
        if keep:
            # the words as said, from the first to the last important one (at most 5 words)
            span = list(range(keep[0], min(keep[-1], keep[0] + 4) + 1))
            items.append((keep[0], " ".join(shown(ctx.words[i]) for i in span)[:40]))
    return items[:limit] if len(items) >= 2 else []


def search_query(ctx, scene):
    toks = scene_tokens(ctx, scene)
    for j, t in enumerate(toks):
        if t in SEARCH_WORDS:
            rest = list(range(scene.i0 + j + 1, scene.i1 + 1))
            # skip "mo", "lang", "the", "for"... then take up to 6 words
            while rest and not important(ctx.words[rest[0]]["text"]):
                rest.pop(0)
            rest = rest[:6]
            if rest:
                return rest
    return []


def countdown_number(ctx, scene):
    toks = scene_tokens(ctx, scene)
    nums = numbers_in(ctx, scene)
    for i, n in nums:
        nxt = norm(ctx.words[i + 1]["text"]) if i + 1 <= scene.i1 else ""
        if nxt in COUNT_UNITS and 1 <= n <= 5999:
            unit = 60 if nxt.startswith(("min", "minuto")) else 1
            return i, int(min(5999, n * unit)) if n * unit <= 5999 else None
    if COUNT_WORDS & set(toks) and nums:
        i, n = nums[0]
        return (i, int(n)) if 1 <= n <= 5999 else None
    return None


def signals(ctx, scene, assets):
    toks = set(scene_tokens(ctx, scene))
    out = {}
    items = list_items(ctx, scene)
    if items:
        out["checklist"] = 5.0
        if SETUP_WORDS & toks:
            out["ui_panel"] = 5.2
        if PLAN_WORDS & toks and assets.images:
            out["storyboard"] = 5.1
    if search_query(ctx, scene):
        out["search"] = 5.0
    if countdown_number(ctx, scene):
        out["countdown"] = 5.0
    if COLOUR_WORDS & toks and assets.satisfies("palette"):
        out["palette"] = 4.6
    if FOLLOW_WORDS & toks:
        out["profile"] = 4.6
    if BRAND_WORDS & toks and assets.logo:
        out["logo"] = 4.4
    if SCREEN_WORDS & toks:
        for beat, s in (("collage", 3.9), ("montage", 3.7), ("mosaic", 3.5), ("phone", 3.8)):
            out[beat] = s
        if assets.videos:
            out["pip"] = 3.6
    return out


# ---------------------------------------------------------------- choosing the beats

def allowed(beat, ctx, scene, assets, chosen, captions_on, after=None):
    """Can `beat` go on `scene`, given what earlier scenes got (and `after`, the next scene's beat
    when that one is already decided)?"""
    template, kind, need, _about = BEATS[beat]
    if beat in CUE_ONLY or not assets.satisfies(need):
        return False
    if need == "items" and not list_items(ctx, scene):
        return False
    if need == "query" and not search_query(ctx, scene):
        return False
    if need == "number" and not countdown_number(ctx, scene):
        return False
    if beat == "subtitle" and captions_on:
        return False                                  # the captions already are the cream cards
    if template and not graphics.has_template(template):
        return False
    prev = chosen[-1] if chosen else None
    if prev and prev["beat"] == beat:
        return False
    if prev and kind == "cover" and BEATS[prev["beat"]][1] == "cover":
        return False
    if after and (after == beat or (kind == "cover" and BEATS[after][1] == "cover")):
        return False
    if beat in ONCE and any(c["beat"] == beat for c in chosen):
        return False
    covers = sum(1 for c in chosen if BEATS[c["beat"]][1] == "cover")
    if kind == "cover" and covers + 1 > max(1, COVER_SHARE * (scene.index + 1) + 0.6):
        return False
    if beat == "pip" and sum(1 for c in chosen if c["beat"] == "pip") >= max(1, len(chosen) // 4 + 1):
        return False
    if kind == "type":
        kw = keyword_index(ctx, scene)
        if kw is None:
            return False
    if kind in ("cover", "pip") and overlay_busy(ctx.project, scene.start, scene.end):
        return False                                  # a photo / B-roll of the edit is already on screen
    return True


def overlay_busy(project, start, end):
    """True when a picture of the edit itself (an overlay or B-roll clip, not this planner's)
    is on screen between start and end."""
    return any(c["start"] < end - EPS and c["start"] + c["duration"] > start + EPS
               for t in project["tracks"] if t["kind"] == "overlay" and not str(t["id"]).startswith("pe-")
               for c in t["clips"])


def rule_beat(ctx, scene, assets, chosen, captions_on, n_scenes, exclude=(), after=None):
    """The rules' choice for one scene: the strongest signal that is allowed, else a type beat,
    else a quiet camera beat. Pictures come back every few scenes when the creator gave some.
    `exclude`: beats not wanted here (another look for the scene)."""
    scores = dict(signals(ctx, scene, assets))
    kw = keyword_index(ctx, scene)
    if scene.index == 0:
        scores["headline"] = 6.0
    base = {"headline": 2.0, "kinetic": 2.15, "marker": 2.1 + (0.4 if kw is not None and ctx.words[kw]["hl"] else 0),
            "subtitle": 1.2, "camera": 1.0}
    for b, s in base.items():
        scores.setdefault(b, s)
    since_pictures = next((len(chosen) - k for k in range(len(chosen) - 1, -1, -1)
                           if BEATS[chosen[k]["beat"]][1] in ("cover", "pip")), len(chosen) + 1)
    if assets.images and since_pictures >= 3:
        for b in ("collage", "montage", "mosaic", "phone"):
            scores[b] = max(scores.get(b, 0), 3.0 + 0.1 * len(assets.images))
    if (assets.videos or assets.images) and since_pictures >= 3:
        scores["pip"] = max(scores.get("pip", 0), 2.8)
    if scene.index == n_scenes - 1 and "profile" in scores:
        scores["profile"] += 1.0
    used = Counter(c["beat"] for c in chosen)
    for b in scores:
        scores[b] -= 0.45 * used[b]                 # variety: a beat used before is a little less likely
    # a stable tie-break: the scene number, so the same video gets the same edit
    order = sorted(scores, key=lambda b: (-scores[b], (hash_of(b) + scene.index) % 7))
    for beat in order:
        if beat not in exclude and allowed(beat, ctx, scene, assets, chosen, captions_on, after):
            return beat
    for beat in BEATS:                      # anything else that fits, before giving up
        if beat not in exclude and allowed(beat, ctx, scene, assets, chosen, captions_on, after):
            return beat
    return "camera"


def hash_of(text):
    return sum(ord(c) * (k + 1) for k, c in enumerate(text))


# ---------------------------------------------------------------- the AI's choice

def plan_schema():
    return {
        "type": "object", "additionalProperties": False, "required": ["scenes"],
        "properties": {
            "summary": {"type": "string"},
            "scenes": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["scene", "beat"],
                "properties": {
                    "scene": {"type": "integer", "minimum": 0},
                    "beat": {"enum": [b for b in BEATS if b not in CUE_ONLY]},
                    "words": {"type": "string", "description": "exact spoken words the main element shows / starts on"},
                    "keyword": {"type": "string", "description": "the one spoken word to emphasise"},
                    "items": {"type": "array", "maxItems": 5, "items": {"type": "string"},
                              "description": "list / checklist / storyboard items, each copied from the spoken words"},
                    "images": {"type": "array", "maxItems": 9, "items": {"type": "string"},
                               "description": "ids of the creator's pictures, from ASSETS"},
                    "clip": {"type": "string", "description": "pip: id of the creator's clip or photo, from ASSETS"},
                    "bw": {"type": "boolean", "description": "a black-and-white transition into this scene"},
                    "reason": {"type": "string"},
                }}},
        },
    }


SYSTEM_PROMPT = """You are the editor of a PREMIUM EDITORIAL VIRAL short video (vertical 9:16): a \
creator talking to the camera in Filipino, English or Taglish, edited like a premium magazine: \
serif headlines, cream cards, keyword highlights, floating screenshots, UI panels, checklists, \
soft shadows, dimmed backgrounds, smooth zooms. Calm and expensive-looking, never cluttered.

The video is already cut into SCENES of 2-4 seconds. For EVERY scene choose ONE beat from BEATS \
(the main idea on screen for that scene) and the spoken words it uses. Rules:
- Match the beat to what is said: a list -> checklist / ui_panel / storyboard; "search ..." -> \
search; a number of seconds/minutes -> countdown; colours -> palette; follow / subscribe -> \
profile; the brand -> logo; an app, results, proof, photos -> collage / montage / mosaic / phone \
or pip (only with the creator's ASSETS); a strong claim -> headline / kinetic / marker; a quiet \
moment -> camera.
- Use ONLY ids from ASSETS for images and clip. Never ask for pictures that are not there. A \
beat that needs pictures cannot be used without them.
- Never the same beat in two scenes in a row. Picture beats (collage, montage, mosaic, phone, \
storyboard) never in two scenes in a row. Scene 0 is the hook: headline or kinetic.
- words, keyword and items are copied exactly from that scene's spoken words (keep Taglish \
as said). Never invent words.
- bw: true only on a turn in the story ("pero", "but", "dati"...), at most once every 12 seconds.
- Output the JSON object only."""


SCENE_WORDS = 40          # a scene's words sent to the AI (a 2-4 s scene has fewer)
INSTRUCTION_CHARS = 600


def build_prompt(ctx, scenes, assets, captions_on, problems=None, fixed=None, only=None):
    """The scene-plan request, kept compact (Groq's free tier counts tokens per minute): only the
    beats the creator's files allow, only the scenes still to plan (`only`; the ones already set by
    what is said are listed by their beat), each scene's words, a short instruction."""
    only = set(s.index for s in scenes) - set(fixed or {}) if only is None else set(only)
    lines = ["BEATS:"]
    for b, (template, kind, need, about) in BEATS.items():
        if (b == "subtitle" and captions_on) or b in CUE_ONLY or not assets.satisfies(need):
            continue
        lines.append(f"- {b} ({kind}{', needs ' + need if need else ''}): {about}")
    lines.append("")
    lines.append("ASSETS (the creator's own files):")
    for mid in assets.images:
        lines.append(f"- {mid}: picture '{assets.media[mid].get('name') or mid}'")
    for mid in assets.videos:
        lines.append(f"- {mid}: clip '{assets.media[mid].get('name') or mid}'")
    if assets.logo:
        lines.append(f"- {assets.logo}: logo")
    if not (assets.images or assets.videos or assets.logo):
        lines.append("- none (no picture beats, no pip, no logo)")
    lines.append("")
    set_by_words = [f"{i} {fixed[i]}" for i in sorted(fixed or {})]
    if set_by_words:
        lines.append("ALREADY SET BY WHAT IS SAID (do not plan these; avoid repeating their beat next to "
                     "them): " + ", ".join(set_by_words))
    lines.append("SCENES TO PLAN (plan exactly these):")
    for s in scenes:
        if s.index in only:
            words = scene_text(ctx, s).split()
            text = " ".join(words[:SCENE_WORDS]) + (" ..." if len(words) > SCENE_WORDS else "")
            lines.append(f"{s.index} [{s.start:.1f}-{s.end:.1f}s]: {text}")
    if ctx.instruction.strip():
        lines.append("")
        lines.append("CREATOR'S INSTRUCTIONS: " + ctx.instruction.strip()[:INSTRUCTION_CHARS])
    if problems:
        lines.append("")
        lines.append("YOUR PREVIOUS ANSWER HAD THESE PROBLEMS:\n" + problems)
    return "\n".join(lines)


def check_choice(ctx, scene, choice, assets):
    """Problems with the AI's choice for one scene (empty = usable)."""
    problems = []
    beat = choice["beat"]
    _t, kind, need, _a = BEATS[beat]
    where = f"scene {scene.index} ({beat})"
    if not assets.satisfies(need):
        problems.append(f"{where}: needs {need}, which the creator did not give")
    for mid in choice.get("images") or []:
        if mid not in assets.images:
            problems.append(f"{where}: '{mid}' is not one of the creator's pictures")
    clip = choice.get("clip")
    if clip and clip not in assets.videos + assets.images:
        problems.append(f"{where}: '{clip}' is not one of the creator's clips or pictures")
    for key in ("words", "keyword"):
        text = choice.get(key)
        if text and locate(ctx.words[scene.i0:scene.i1 + 1], text, scene.start, window=SCENE_MAX + 1) is None:
            problems.append(f"{where}: '{text}' is not said in this scene")
    for item in choice.get("items") or []:
        if locate(ctx.words[scene.i0:scene.i1 + 1], item, scene.start, window=SCENE_MAX + 1) is None:
            problems.append(f"{where}: the item '{item}' is not said in this scene")
    return problems


GROQ_TPM = 8000          # Groq's free-tier tokens per minute for the default model (ai: groq_tpm)
ANSWER_BASE = 1200       # answer tokens: room for the model's reasoning ...
ANSWER_PER_SCENE = 160   # ... and per scene planned


def answer_tokens(ai, n):
    return min(int(ai.get("max_tokens", 8000)), ANSWER_BASE + ANSWER_PER_SCENE * n)


def plan_chunks(ctx, scenes, assets, captions_on, fixed, provider, ai):
    """The scenes to plan, in groups whose request (words + room for the answer) fits the
    provider's tokens-per-minute budget: one request when it fits, several when it does not."""
    todo = [s for s in scenes if s.index not in (fixed or {})]
    if provider != "groq" or not todo:
        return [todo] if todo else []
    budget = int(float(ai.get("groq_tpm", GROQ_TPM)) * 0.85)
    fixed_cost = estimate_tokens(SYSTEM_PROMPT + json.dumps(plan_schema(), separators=(",", ":")))

    def cost(group):
        return fixed_cost + estimate_tokens(build_prompt(ctx, scenes, assets, captions_on, None, fixed,
                                                         {s.index for s in group})) + answer_tokens(ai, len(group))
    chunks, current = [], []
    for s in todo:
        if current and cost(current + [s]) > budget:
            chunks.append(current)
            current = []
        current.append(s)
    chunks.append(current)
    return chunks


def request_choices(ctx, scenes, assets, captions_on, provider, model, cache=None, cancel=None, fixed=None,
                    reporter=None):
    """{scene index: choice} from the AI (checked; one retry for a bad answer), plus usage / notes.
    Only the scenes not already set by what is said are asked for, in as few requests as fit the
    free tier's per-minute limit; a slow, rate-limited or failing AI never holds the edit up (see
    llm.ask_json): what was not planned by the AI is planned by the rules."""
    ai = ctx.cfg.get("ai") or {}
    key = None
    if cache is not None:
        from .cache import key_for
        key = key_for({"v": PROMPT_VERSION, "provider": provider, "model": model, "style": STYLE,
                       "instruction": ctx.instruction.strip(), "words": [(w["text"], w["start"]) for w in ctx.words],
                       "assets": assets.summary(), "captions": captions_on})
        hit = cache.get("editorial", key)
        if hit and isinstance(hit.get("choices"), list):
            return ({ch["scene"]: ch for ch in hit["choices"]}, {"input_tokens": 0, "output_tokens": 0},
                    hit.get("model"), [], True)
    usage = {"input_tokens": 0, "output_tokens": 0}
    attempts, used_model = [], model
    by_index = {s.index: s for s in scenes}
    best = {}
    log = RequestLog(ctx.cfg)

    def notify(message):
        if reporter:
            reporter.stage("graphics", f"Planning the editorial scenes - {message}")
    options = {"reasoning_effort": "low"} if provider == "groq" and "gpt-oss" in str(model) else None
    queue = plan_chunks(ctx, scenes, assets, captions_on, fixed, provider, ai)
    if len(queue) > 1:
        log.step(f"editorial plan: {sum(len(c) for c in queue)} scenes in {len(queue)} requests (per-minute limit)")
        notify(f"asking in {len(queue)} parts to stay inside the free per-minute limit")
    complete = True
    while queue:
        group = queue.pop(0)
        only = {s.index for s in group}
        part = f"editorial plan (scenes {min(only)}-{max(only)})"
        problems_text = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if cancel is not None and cancel.is_set():
                raise Cancelled("Cancelled while planning the editorial scenes.")
            prompt = build_prompt(ctx, scenes, assets, captions_on, problems_text, fixed, only)
            try:
                text, used, used_model = ask_json(provider, model, SYSTEM_PROMPT, prompt, plan_schema(),
                                                  max_tokens=answer_tokens(ai, len(group)),
                                                  effort=ai.get("anthropic_effort", "medium"), cancel=cancel,
                                                  notify=notify, cfg=ctx.cfg, step=part, options=options)
            except LLMError as exc:
                if exc.status == 400 and options and "reasoning" in str(exc):
                    options = None                      # this model takes no reasoning_effort
                    continue
                if exc.limit and len(group) > 1:
                    # still too large for the per-minute limit: ask for each half on its own
                    half = len(group) // 2
                    queue[:0] = [group[:half], group[half:]]
                    log.step(f"{part}: too large ({exc.requested} of {exc.limit} tokens): split in two")
                    break
                attempts.append({"attempt": attempt, "problems": [f"the AI could not be asked: {exc}"]})
                complete = False
                queue = []                              # no more waiting: the rules plan the rest
                break
            usage = {k: usage[k] + used[k] for k in usage}
            choices, problems = salvage(ctx, text, {i: by_index[i] for i in only}, assets, fixed)
            if len(choices) > len(best.get(part, {})):
                best[part] = choices
            if not problems:
                break
            attempts.append({"attempt": attempt, "problems": problems[:20], "kept": len(choices)})
            problems_text = "\n".join(f"- {p}" for p in problems[:20])
            complete = False if attempt == MAX_ATTEMPTS else complete
    merged = {}
    for part_choices in best.values():
        merged.update(part_choices)
    if complete and cache is not None and merged:
        cache.put("editorial", key, {"choices": list(merged.values()), "model": used_model})
    # what checked out is used, scene by scene; the rest is planned by the rules
    return merged, usage, used_model, attempts, False


SCENE_SCHEMA = None


def salvage(ctx, text, by_index, assets, fixed):
    """({scene index: usable choice}, [problems]) from the AI's answer. A scene whose choice is
    broken is dropped (the rules plan it); words / keyword / items that are not said are dropped
    from a choice that is otherwise fine. Any problem is reported (for the retry and the summary)."""
    import jsonschema
    global SCENE_SCHEMA
    if SCENE_SCHEMA is None:
        SCENE_SCHEMA = jsonschema.Draft202012Validator(plan_schema()["properties"]["scenes"]["items"])
    try:
        plan = json.loads(text) if text.strip() else None
    except ValueError as exc:
        return {}, [f"the answer is not JSON ({exc})"]
    if not isinstance(plan, dict) or not isinstance(plan.get("scenes"), list):
        return {}, ["the answer is not a JSON object with a scenes list"]
    choices, problems = {}, []
    for ch in plan["scenes"]:
        errors = [e.message for e in SCENE_SCHEMA.iter_errors(ch)] if isinstance(ch, dict) else ["not an object"]
        if errors:
            problems.append(f"scene {ch.get('scene', '?') if isinstance(ch, dict) else '?'}: {errors[0]}")
            continue
        if ch["scene"] in (fixed or {}):
            continue                        # what is said already decides this scene
        if ch["scene"] not in by_index:
            problems.append(f"scene {ch['scene']} is not one of the scenes to plan")
            continue
        found = check_choice(ctx, by_index[ch["scene"]], ch, assets)
        soft = [p for p in found if "is not said" in p]
        hard = [p for p in found if p not in soft]
        problems += found
        if hard:
            continue
        if soft:
            ch = {k: v for k, v in ch.items() if k not in ("words", "keyword", "items")}
            if BEATS[ch["beat"]][2] == "items":
                continue                    # a list beat without its spoken items
        choices[ch["scene"]] = ch
    return choices, problems


# ---------------------------------------------------------------- one scene's elements

class Plan:
    """What gets added: graphics items (for the Director's placement), effect clips, PiP clips."""

    def __init__(self):
        self.items, self.effects, self.pips, self.notes = [], [], [], []


def word_cues(ctx, indices, start):
    return [round(max(0.0, ctx.words[i]["start"] - start), 3) for i in indices]


def marked_text(ctx, indices, keyword):
    return " ".join(f"*{shown(ctx.words[i])}*" if i == keyword else shown(ctx.words[i]) for i in indices
                    if shown(ctx.words[i]))


def pick_images(assets, n, used):
    """n of the creator's pictures, the least used first (the same picture is not shown twice in a
    row when there are others)."""
    order = sorted(assets.images, key=lambda m: (used[m], assets.images.index(m)))
    picked = order[:n]
    for m in picked:
        used[m] += 1
    return picked


def spread_indices(ctx, scene, n):
    """n word indices spread over the important words of a scene (times for pictures to arrive)."""
    imp = [i for i in range(scene.i0, scene.i1 + 1) if important(ctx.words[i]["text"])] or \
        list(range(scene.i0, scene.i1 + 1))
    if n <= 0:
        return []
    if len(imp) >= n:
        step = len(imp) / n
        return [imp[int(k * step)] for k in range(n)]
    return [imp[min(k, len(imp) - 1)] for k in range(n)]


def element(ctx, scene, beat, assets, choice, used_images, captions_on):
    """The graphic item (or None) and the extra clips for one scene's beat. Returns
    (item or None, [effect clip specs], [pip clip specs])."""
    template, kind, need, _about = BEATS[beat]
    choice = choice or {}
    sw = ctx.words
    kw = keyword_index(ctx, scene)
    if choice.get("keyword"):
        hit = locate(sw[scene.i0:scene.i1 + 1], choice["keyword"], scene.start, window=SCENE_MAX + 1)
        if hit:
            kw = scene.i0 + hit[0]
    effects, pips = [], []
    it = None

    def base(trigger, **kw_args):
        start = snap(max(scene.start, sw[trigger]["start"]), ctx.fps)
        return {"template": template, "words": " ".join(strip_marks(sw[i]["text"]) for i in [trigger]),
                "start": start, "i0": trigger, "i1": trigger, "word_end": sw[trigger]["end"],
                "spoken": strip_marks(sw[trigger]["text"]), "mood": director.word_mood([sw[i]["text"] for i in range(scene.i0, scene.i1 + 1)]),
                "importance": 0.8, "zone": None, "reason": f"scene {scene.index + 1}: {beat}", "beat": beat,
                "scene": scene.index, **kw_args}

    if beat in ("headline", "kinetic", "marker", "subtitle"):
        if kw is None:
            return None, [], []
        if choice.get("words"):
            hit = locate(sw[scene.i0:scene.i1 + 1], choice["words"], scene.start, window=SCENE_MAX + 1)
            idx = list(range(scene.i0 + hit[0], scene.i0 + hit[1] + 1)) if hit else phrase_around(ctx, scene, kw)
        elif beat == "kinetic":
            idx = [i for i in phrase_around(ctx, scene, kw, max_words=5, max_chars=40) if important(sw[i]["text"])][:4] or [kw]
        elif beat == "subtitle":
            idx = list(range(scene.i0, scene.i1 + 1))[:12]
        else:
            idx = phrase_around(ctx, scene, kw, max_words=7 if beat == "headline" else 8)
        if kw not in idx:
            kw = idx[len(idx) // 2]
        it = base(idx[0], text=marked_text(ctx, idx, kw))
        it["i1"] = idx[-1]
        it["word_end"] = sw[idx[-1]]["end"]
        shown_idx = [i for i in idx if shown(sw[i])]
        it["cues"] = word_cues(ctx, [kw] if beat == "marker" else shown_idx, it["start"])
        it["zone"] = "upper" if beat in ("headline", "marker") else "center"
        if beat in ("headline", "kinetic", "marker") and sw[kw]["start"] < scene.end - 0.3:
            # a punch-in on the key word (smooth, short)
            effects.append({"type": "zoom", "start": snap(sw[kw]["start"], ctx.fps),
                            "end": min(scene.end, sw[kw]["start"] + 1.4), "amount": 1.1, "ease": 0.18,
                            "smooth": True, "anchor_y": 0.4})
    elif beat in ("checklist", "ui_panel", "storyboard"):
        items = list_items(ctx, scene)
        if choice.get("items"):
            given = []
            for text in choice["items"]:
                hit = locate(sw[scene.i0:scene.i1 + 1], text, scene.start, window=SCENE_MAX + 1)
                if hit:
                    given.append((scene.i0 + hit[0], strip_marks(text)[:40]))
            items = given if len(given) >= 2 else items
        if len(items) < 2:
            return None, [], []
        title_idx = [i for i in range(scene.i0, items[0][0])
                     if important(sw[i]["text"]) and norm(sw[i]["text"]) not in LIST_MARKERS][:4]
        title = " ".join(shown(sw[i]) for i in title_idx)[:30]
        it = base(scene.i0 if title_idx else items[0][0], text=title, list=[t for _i, t in items])
        it["cues"] = word_cues(ctx, [i for i, _t in items], it["start"])
        it["zone"] = "center"
        if beat == "storyboard":
            it["images"] = pick_images(assets, min(3, len(items), len(assets.images)), used_images)
            it["text"] = title or "Storyboard"
        if beat == "ui_panel":
            it["text"] = title or "Setup"
    elif beat == "search":
        q = search_query(ctx, scene)
        if not q:
            return None, [], []
        it = base(q[0], text=" ".join(shown(sw[i]) for i in q)[:48])
        it["cues"] = [0.15, round(max(0.6, sw[q[-1]]["end"] - it["start"]), 3)]
        it["zone"] = "upper"
    elif beat == "countdown":
        found = countdown_number(ctx, scene)
        if not found:
            return None, [], []
        i, number = found
        it = base(i, number=number, text="")
        it["zone"] = "center"
    elif beat == "palette":
        source = assets.logo or ([m for m in (choice.get("images") or []) if m in assets.images]
                                 + assets.images)[0]
        try:
            colours = graphics.palette_from_image(assets.path(source), 5)
        except OSError:
            return None, [], []
        if len(colours) < 2:
            return None, [], []
        trigger = next((i for i in range(scene.i0, scene.i1 + 1) if norm(sw[i]["text"]) in COLOUR_WORDS),
                       kw if kw is not None else scene.i0)
        it = base(trigger, text="", list=colours)
        it["cues"] = [0.2 + 0.18 * k for k in range(len(colours))]
        it["zone"] = "center"
    elif beat == "profile":
        follow = next((i for i in range(scene.i0, scene.i1 + 1) if norm(sw[i]["text"]) in FOLLOW_WORDS), scene.i0)
        it = base(scene.i0, text=assets.name or assets.handle, text2=assets.handle if assets.name else "")
        if assets.avatar:
            it["image"] = assets.avatar
        it["cues"] = word_cues(ctx, [follow], it["start"])
        it["zone"] = "upper"
    elif beat == "logo":
        brand = next((i for i in range(scene.i0, scene.i1 + 1) if norm(sw[i]["text"]) in BRAND_WORDS), scene.i0)
        it = base(brand, image=assets.logo, text=assets.brand or "")
        it["zone"] = "upper"
    elif beat in ("collage", "montage", "mosaic", "phone"):
        want = {"collage": min(4, len(assets.images)), "montage": min(6, len(assets.images)),
                "mosaic": min(9, len(assets.images)), "phone": 1}[beat]
        chosen = [m for m in (choice.get("images") or []) if m in assets.images][:want]
        images = chosen if (len(chosen) >= 1 if beat == "phone" else len(chosen) >= 2) else pick_images(assets, want, used_images)
        it = base(scene.i0, text="")
        if beat == "phone":
            it["image"] = images[0]
        else:
            it["images"] = images
            it["cues"] = word_cues(ctx, spread_indices(ctx, scene, len(images)), it["start"])
        it["zone"] = "center"
    elif beat == "pip":
        clip_id = choice.get("clip") if choice.get("clip") in assets.videos + assets.images else \
            (assets.videos[scene.index % len(assets.videos)] if assets.videos else pick_images(assets, 1, used_images)[0])
        start = snap(sw[scene.i0]["start"] if scene.index else scene.start, ctx.fps)
        pips.append({"media": clip_id, "start": start, "end": scene.end})
        if kw is not None:
            # a label under the floating picture: the words it goes with
            idx = phrase_around(ctx, scene, kw, max_words=4, max_chars=30)
            it = {**base(idx[0]), "template": "label-pill",
                  "text": " ".join(shown(sw[i]) for i in idx).strip(" .,!?:;"),
                  "prefer": ((PIP_BOX["x"] + PIP_BOX["width"] / 2) / 1080,
                             (PIP_BOX["y"] + PIP_BOX["height"] + 60) / 1920),
                  "start": snap(max(start + 0.4, sw[idx[0]]["start"]), ctx.fps), "importance": 0.7}
    elif beat == "camera":
        start = snap(scene.start, ctx.fps)
        effects.append({"type": "zoom", "start": start, "end": scene.end, "amount": 1.12, "from": 1.0,
                        "ease": max(0.5, min(scene.duration, 3.0)), "smooth": True, "anchor_y": 0.42})
    if it is not None and kind == "cover":
        it["importance"] = 0.9
    return it, effects, pips


# ---------------------------------------------------------------- what is said asks for it (cues.py)

def scene_of(scenes, t):
    return next((s for s in reversed(scenes) if s.start <= t + EPS), scenes[0])


def cue_item(ctx, cue, template, beat, start_i, end_t, scene, **kw):
    """A graphic item for a spoken cue: it starts on its word and stays until end_t."""
    sw = ctx.words
    start = snap(sw[start_i]["start"], ctx.fps)
    meta = graphics.template_meta(template)
    end = snap(min(ctx.duration, start + meta["maxDuration"], max(end_t, start + max(meta["minDuration"], 1.6))), ctx.fps)
    return {"template": template, "words": " ".join(strip_marks(sw[i]["text"]) for i in range(cue.i0, cue.i1 + 1)),
            "start": start, "end": end, "i0": cue.i0, "i1": cue.i1, "word_end": sw[cue.i1]["end"],
            "spoken": " ".join(strip_marks(sw[i]["text"]) for i in range(cue.i0, cue.i1 + 1)),
            "mood": None, "importance": 0.95, "zone": "upper", "reason": f"said: {cue.kind}", "beat": beat,
            "scene": scene.index, "cue": cue.kind, "timed": True,
            # never on the face: the speaker moves lower while the card is up (add_layouts)
            "covers_face": False, **kw}


def rel(ctx, idx, start):
    return [round(max(0.0, ctx.words[i]["start"] - start), 3) for i in idx]


PIN = re.compile(r"(?:show|put|add|ipakita|ilagay|lagyan(?: ng)?)\s+(?:the\s+|ang\s+|yung\s+)?(?P<photo>[\w .'-]+?)\s+"
                 r"(?:when i say|when i mention|kapag sinabi ko|pag sinabi ko|pagsabi ko ng|pagsabi ko|sa salitang|on the word)"
                 r"\s+[\"'“]?(?P<word>[\w-]+(?: [\w-]+)?)", re.I)


def photo_by_name(assets, text):
    """The picture of yours a few words name ("tiktok logo" -> TikTok logo.png), or None."""
    want = [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 3 and t not in ("the", "ang", "yung", "ko", "my")]
    best, score = None, 0
    for mid in list(assets.names):
        parts = assets.name_parts(mid)
        hit = sum(1 for w in want if any(p[:5] == w[:5] or same_meaning(p, w) for p in parts))
        if hit > score:
            best, score = mid, hit
    return best


def pinned_cues(ctx, assets):
    """Cues for the pictures your instruction pins to a word: one on each time the word is said
    (a word one letter off counts: "TikTok" heard as "Tiktak"). Notes for pins that cannot be done."""
    from .taglish import one_edit
    out, notes = [], []
    for m in PIN.finditer(ctx.instruction or ""):
        mid = photo_by_name(assets, m.group("photo"))
        word = m.group("word").strip()
        if mid is None:
            notes.append(f"You asked to show \"{m.group('photo').strip()}\" on \"{word}\", but none of your files "
                         "has that name.")
            continue
        toks = [norm(t) for t in word.split()]
        def same(heard, t):          # the word, or one letter off it (not its plural / singular)
            return heard == t or (len(t) >= 5 and one_edit(heard, t) and heard + "s" != t and t + "s" != heard)
        hits = [i for i in range(len(ctx.words) - len(toks) + 1)
                if all(same(norm(ctx.words[i + k]["text"]), t) for k, t in enumerate(toks))]
        if not hits:
            notes.append(f"You asked to show {assets.names[mid]} when you say \"{word}\", but \"{word}\" is not "
                         "said in the video.")
            continue
        for i in hits[:3]:
            cue = cues_mod.Cue("pin", i, i + len(toks) - 1, text=" ".join(shown(ctx.words[i + k]) for k in range(len(toks))),
                               number=mid, priority=10)
            out.append(cue)
    return out, notes


def asset_report(project, assets, ctx):
    """One line per picture of yours: where it was used and why, or why not."""
    by_mid = {}
    for t in project["tracks"]:
        for c in t["clips"]:
            why = ((c.get("director") or {}).get("assets") or {})
            mids = set(why) | ({c["params"].get("image")} if c.get("params", {}).get("image") else set()) | \
                set((c.get("params") or {}).get("images") or [])
            if t["kind"] == "overlay" and c.get("media"):
                mids.add(c["media"])
            for mid in mids:
                if mid in assets.names:
                    what = c.get("template") or ("a floating picture" if "picture-in-picture" in c.get("label", "")
                                                 else "a picture")
                    by_mid.setdefault(mid, []).append((c["start"], what, why.get(mid, "")))
    lines = []
    tokens = [(w["start"], norm(w["text"])) for w in ctx.words]
    for mid, name in assets.names.items():
        uses = sorted(by_mid.get(mid, []))
        if uses:
            where = "; ".join(f"{director.mmss(t)} as {tpl}" + (f" ({why})" if why else "") for t, tpl, why in uses[:3])
            lines.append(f"{name}: used at {where}.")
            continue
        said = [(t, w) for t, w in tokens if assets.name_matches(mid, [w])]
        platform = next((p for p, m in assets.platform_logos.items() if m == mid), None)
        if platform and not any(w == platform for _t, w in tokens):
            why = f"{cues_mod.PLATFORMS.get(platform, platform.title())} is never said"
        elif mid == assets.avatar:
            why = "no @handle, \"i-follow\" or comment call is said"
        elif said:
            t, w = said[0]
            why = (f"its name matches \"{w}\" at {director.mmss(t)}, but no picture card was made there (another card "
                   "was on screen, or it did not fit)")
        else:
            parts = ", ".join(assets.name_parts(mid)) or name
            why = f"no spoken word matches its name ({parts})"
        lines.append(f"{name}: not used - {why}. To use it, say what it shows or pin it in the instruction "
                     f"(\"show {name.rsplit('.', 1)[0]} when I say ...\").")
    return lines


def cue_elements(ctx, found, scenes, assets, used_images, handle=None):
    """Graphic items and effect specs for the spoken cues. Returns (items, effects, notes, used): `used`
    = the cues that made something (a cue with nothing to show leaves its scene to the beats)."""
    sw = ctx.words
    items, effects, notes, used = [], [], [], []
    heads = []                     # one line per card (for a recap and the cover)
    hold = 0.9
    profile_photo = assets.avatar
    for cue in found:
        made, made_items = len(items) + len(effects), len(items)
        s = scene_of(scenes, sw[cue.i0]["start"])
        last_end = sw[cue.i1]["end"]
        beat = CUE_BEAT[cue.kind]
        if cue.kind == "countdown":
            idx = [k for k, _v in cue.items]
            it = cue_item(ctx, cue, "countdown-timer", beat, idx[0], last_end + 0.7, s, number=cue.number, text="")
            it["cues"] = rel(ctx, idx, it["start"])
            it["zone"] = "center"
            items.append(it)
        elif cue.kind == "keyword":
            it = cue_item(ctx, cue, "kinetic-words", beat, cue.i0, last_end + 1.4, s,
                          text=" ".join(f"*{w}*" for w in cue.text.split()))
            it["cues"] = rel(ctx, range(cue.i1 - len(cue.text.split()) + 1, cue.i1 + 1), it["start"])
            it["zone"] = "upper"
            items.append(it)
            effects.append({"type": "zoom", "start": sw[cue.i1]["start"], "end": min(ctx.duration, last_end + 1.2),
                            "amount": 1.12, "ease": 0.2, "smooth": True, "anchor_y": 0.4})
        elif cue.kind == "before_after":
            after_i = cue.items[0][0]
            # the whole past in black and white (it was ~1 s on the real run): grey from just before
            # "dati", held, colour back right on "ngayon"
            effects.append({"type": "look", "start": sw[cue.i0]["start"] - 0.25, "end": sw[after_i]["start"] + 0.3})
            before = [k for k in range(cue.i0, after_i) if norm_word(sw[k]) not in TIME_WORDS]
            # the "ngayon" sentence as the cue engine found it (with or without punctuation)
            end_after = min(len(sw) - 1, after_i + max(0, len(cue.items[0][1].split()) - 1), after_i + 6)
            after = [k for k in range(after_i, end_after + 1) if norm_word(sw[k]) not in TIME_WORDS]
            if before and after:
                it = cue_item(ctx, cue, "strike-text", beat, cue.i0, sw[end_after]["end"] + 1.0, s,
                              text=director.shorten(" ".join(shown(sw[k]) for k in before), 48),
                              text2=director.shorten(" ".join(shown(sw[k]) for k in after), 40))
                it["cues"] = rel(ctx, [before[-1], after_i], it["start"])          # struck; then "ngayon"
                it["zone"] = "upper"
                items.append(it)
        elif cue.kind == "search":
            q0 = next(i for i in range(cue.i0, cue.i1 + 1) if strip_marks(sw[i]["text"]).strip(".,!?:") and
                      " ".join(shown(sw[k]) for k in range(i, cue.i1 + 1)).startswith(cue.text.split()[0]))
            it = cue_item(ctx, cue, "search-bar", beat, cue.i0, last_end + hold + 0.6, s, text=cue.text)
            it["cues"] = [round(max(0.1, sw[q0]["start"] - it["start"]), 3),
                          round(max(0.6, last_end - it["start"]), 3)]
            items.append(it)
        elif cue.kind == "screenshot":
            pics = assets.matching_images([t for _k, t in cue.items])[:4]
            if not pics:
                notes.append(f"You talk about a screenshot at {director.mmss(sw[cue.i0]['start'])}, but no picture "
                             "of yours was given, so none is shown. Add your screenshot (e.g. results.png) to show it.")
                continue
            for m in pics:
                used_images[m] += 1
            said = [t for _k, t in cue.items]
            why = {m: (f"matched '{', '.join(dict.fromkeys(assets.name_matches(m, said)))}' in \"{cue.text[:40]}\""
                       if assets.name_matches(m, said) else f"your screenshot for \"{cue.text[:40]}\" (no word of its name was said)")
                   for m in pics}
            if getattr(cue, "phone", False):
                # "sa phone / app ko": the first screenshot inside a floating phone
                it = cue_item(ctx, cue, "phone-mockup", "phone", cue.number if cue.number is not None else cue.i0,
                              last_end + hold + 0.6, s, image=pics[0], text="")
                it["zone"] = "center"
                it["asset_why"] = {pics[0]: why[pics[0]]}
                items.append(it)
                continue
            it = cue_item(ctx, cue, "screenshot-collage", beat, cue.number if cue.number is not None else cue.i0,
                          last_end + hold + 0.6, s, images=pics, text="")
            it["cues"] = rel(ctx, [cue.number if cue.number is not None else cue.i0] * len(pics), it["start"])
            it["cues"] = [round(c + 0.35 * k, 3) for k, c in enumerate(it["cues"])]
            it["zone"] = "center"
            it["asset_why"] = why
            items.append(it)
        elif cue.kind in ("checklist", "storyboard"):
            template = "editorial-checklist" if cue.kind == "checklist" else "storyboard-doc"
            it = cue_item(ctx, cue, template, beat, cue.i0, last_end + hold + 0.8, s, text=cue.text,
                          list=[t for _k, t in cue.items])
            it["cues"] = rel(ctx, [k for k, _t in cue.items], it["start"])
            it["zone"] = "upper" if cue.kind == "checklist" else "center"
            items.append(it)
        elif cue.kind == "platforms":
            n = len(cue.items[:4])
            xs = {1: [0.5], 2: [0.34, 0.66], 3: [0.22, 0.5, 0.78], 4: [0.15, 0.38, 0.62, 0.85]}[n]
            for (k, name), x in zip(cue.items[:4], xs):
                logo = assets.platform_logos.get(name.lower())
                it = cue_item(ctx, cue, "app-tile", beat, k, last_end + hold + 0.4, s, text=name,
                              **({"image": logo} if logo else {}))
                it["prefer"] = (x, 0.16)
                it["importance"] = 0.97
                if logo:
                    it["asset_why"] = {logo: f"you said \"{shown(sw[k])}\""}
                items.append(it)
                if not logo:
                    notes.append(f"No logo file of yours for {name}, so its tile shows the name (add e.g. "
                                 f"{name.lower()}_logo.png to use your logo).")
        elif cue.kind in ("handle", "follow"):
            who = cue.text if cue.kind == "handle" else (handle or assets.handle)
            title = assets.name or who
            if not title and profile_photo:
                # no name / handle set, but your photo: the card shows the words you said with it
                title = " ".join(shown(sw[k]) for k in range(cue.i0, cue.i1 + 1))[:30]
                who = ""
            if not title:
                it = cue_item(ctx, cue, "kinetic-words", "kinetic", cue.i0, last_end + 1.0, s,
                              text=" ".join(shown(sw[k]) for k in range(cue.i0, cue.i1 + 1)))
                it["cues"] = rel(ctx, range(cue.i0, cue.i1 + 1), it["start"])
                items.append(it)
                used.append(cue)
                cue.used_beat = "kinetic"
                continue
            press = cue.number if cue.kind == "follow" else cue.i1
            it = cue_item(ctx, cue, "profile-card", beat, cue.i0, last_end + hold + 0.8, s, text=title,
                          text2=who if (assets.name and who) else "", **({"image": profile_photo} if profile_photo else {}))
            it["cues"] = rel(ctx, [press], it["start"])
            it["cues"] = [round(it["cues"][0] + (0.25 if cue.kind == "follow" else 0.9), 3)]
            if cue.kind == "handle":
                it["prefer"] = (0.5, 0.36)
            if profile_photo:
                it["asset_why"] = {profile_photo: f"your profile photo, for \"{director.shorten(cue.text or who, 40)}\""}
            items.append(it)
        elif cue.kind == "stats":
            it = cue_item(ctx, cue, "stat-cards", beat, cue.i0, last_end + hold + 0.8, s,
                          list=[t for _k, t in cue.items])
            it["cues"] = rel(ctx, [k for k, _t in cue.items], it["start"])
            items.append(it)
        elif cue.kind == "recap":
            # what was said, summed up: a tile for each thing shown so far (else the sentence's words)
            # what the cards showed comes in at once, then each item said here on its word
            spoken_items = [t for _k, t in cue.items]
            earlier = [t for t in dict.fromkeys(heads) if t and t not in spoken_items][:max(0, 8 - len(spoken_items))]
            tiles = earlier + spoken_items
            if len(tiles) < 3:
                tiles = [shown(sw[k]) for k in range(cue.i0, cue.i1 + 1)
                         if norm_word(sw[k]) not in cues_mod.STOP_ITEM | cues_mod.RECAP][:8]
            if len(tiles) >= 2:
                it = cue_item(ctx, cue, "tile-mosaic", beat, cue.i0, last_end + hold + 0.6, s, list=tiles)
                spoken = [round(max(0.0, sw[k]["start"] - snap(sw[cue.i0]["start"], ctx.fps)), 3)
                          for k, t in cue.items if t in tiles]
                it["cues"] = [round(0.1 + 0.1 * k, 3) for k in range(len(tiles) - len(spoken))] + spoken
                it["zone"] = "center"
                items.append(it)
        elif cue.kind == "timeline":
            it = cue_item(ctx, cue, "timeline-card", beat, cue.i0, last_end + hold + 0.6, s,
                          text=cue.text[:1].upper() + cue.text[1:], list=[t for _k, t in cue.items])
            items.append(it)
        elif cue.kind == "comment":
            who = handle or assets.handle or assets.name or ""
            it = cue_item(ctx, cue, "chat-cards", beat, cue.i0, last_end + hold + 0.8, s, text=who,
                          list=[director.shorten(cue.text, 80)], **({"image": profile_photo} if profile_photo else {}))
            it["cues"] = [0.15]
            if profile_photo:
                it["asset_why"] = {profile_photo: "your profile photo, on the comment card"}
            items.append(it)
        elif cue.kind == "pin":
            # "show tiktok logo when I say TikTok": your picture on that word, as you asked
            mid = cue.number
            logo = mid in assets.platform_logos.values() or mid == assets.logo
            it = cue_item(ctx, cue, "app-tile" if logo else "screenshot-collage", "screenshot", cue.i0,
                          last_end + hold + 0.6, s, text=cue.text if logo else "",
                          **({"image": mid} if logo else {"images": [mid]}))
            if not logo:
                it["cues"] = [0.0]
            it["zone"] = "upper" if logo else "center"
            it["importance"] = 0.99
            it["asset_why"] = {mid: f"pinned in your instruction to \"{shown(sw[cue.i0])}\""}
            used_images[mid] += 1
            items.append(it)
        if len(items) > made_items:
            heads.append(head_of(items[-1]))
        if len(items) + len(effects) > made and cue not in used:
            used.append(cue)
            cue.used_beat = items[-1]["beat"] if len(items) > made_items else beat
    # one spoken cue's card gives way to the next one's (a few tiles of one sentence stay together)
    order = sorted(items, key=lambda x: x["start"])
    for k, it in enumerate(order):
        nxt = next((o for o in order[k + 1:] if o["i0"] != it["i0"] and (o["cue"] != it["cue"] or o["cue"] == "pin")),
                   None)
        if nxt is not None and it["end"] > nxt["start"] - 0.08:
            it["end"] = snap(max(it["start"] + 1.2, nxt["start"] - 0.08), ctx.fps)
    cover = magazine_cover(ctx, found, used, order, heads, scenes)
    if cover is not None:
        items.insert(0, cover[0])
        used.insert(0, cover[1])
    return items, effects, notes, used


OPENERS = {"teka", "lang", "wait", "uy", "hoy", "guys", "okay", "ok", "so", "alam", "niyo", "nyo", "ba"}



def norm_word(w):
    return cues_mod.norm(w["text"])


def head_of(it):
    """One short line for a card: its title or query, else its first item."""
    text = strip_marks(it.get("text2") if it["template"] == "strike-text" else it.get("text") or "").replace("*", "")
    return text.strip() or next(iter(it.get("list") or []), "")


def magazine_cover(ctx, found, used, order, heads, scenes):
    """The opening as a magazine cover when the video has enough to show: the hook word as the
    masthead, the first sentence as the kicker, three things that come later as cover lines. Only
    when the first spoken card leaves it room. Returns (item, its pseudo cue) or None."""
    sw = ctx.words
    if len(used) < MAGAZINE_MIN or not sw:
        return None
    first = order[0]["start"] if order else ctx.duration
    # the first sentence that says something (a "Teka lang!" is not the hook), punctuated or not
    def says(a, b):
        return [k for k in range(a, b + 1) if shown(sw[k]) and norm_word(sw[k]) not in OPENERS]
    spans = cues_mod.sentence_spans(sw)
    i0, end_i = next(((a, b) for a, b in spans if len(says(a, b)) >= 3), spans[0])
    i0 = (says(i0, end_i) or [i0])[0]
    hook = [k for k in range(i0, end_i + 1)]
    start = snap(sw[hook[0]]["start"], ctx.fps)                  # on the hook's first word
    if first - start < 1.2:
        return None
    # the masthead: what a "number + thing" hook counts ("Tatlong SIKRETO..."), else a word said as a
    # title in or just after the hook, else the hook's strongest word
    counted = next((hook[n + 1] for n, k in enumerate(hook[:-1]) if cues_mod.number_word(sw[k]["text"]) is not None
                    and len(norm_word(sw[hook[n + 1]])) > 3 and norm_word(sw[hook[n + 1]]) not in cues_mod.STOP_ITEM),
                   None)
    keyword = shown(sw[counted]) if counted is not None else \
        next((c.text for c in found if c.kind == "keyword" and sw[c.i0]["start"] < sw[end_i]["end"] + 4), None)
    if keyword is None:
        cands = [k for k in hook if len(norm_word(sw[k])) > 3 and norm_word(sw[k]) not in cues_mod.STOP_ITEM
                 and cues_mod.number_word(sw[k]["text"]) is None]
        if not cands:
            return None
        keyword = shown(sw[max(cands, key=lambda k: (len(norm_word(sw[k])) >= 6, sw[k]["end"] - sw[k]["start"]))])
    lines = [t for t in dict.fromkeys(heads) if t and t.lower() != keyword.lower()][:3]
    cue = cues_mod.Cue("magazine", hook[0], hook[-1], text=keyword, priority=10)
    cue.used_beat = "magazine"
    # the cover holds the opening scene(s) the hook is said in, never into a spoken card
    scene = scene_of(scenes, sw[end_i]["start"])
    first = min(first, max(scene.end, start + 2.6) + 0.08)
    it = cue_item(ctx, cue, "magazine-cover", "magazine", hook[0], first - 0.08, scene,
                  text=keyword.upper(), text2=director.shorten(" ".join(shown(sw[k]) for k in hook), 60),
                  list=lines, number=1)
    it["end"] = snap(min(it["end"], first - 0.08), ctx.fps)
    it["start"] = start
    it["cues"] = [round(max(0.0, sw[hook[0]]["start"] - start), 3)] + \
        [round(max(0.0, sw[hook[0]]["start"] - start) + 0.5 + 0.35 * k, 3) for k in range(len(lines))]
    it["zone"] = "center"
    it["reason"] = "the opening: a magazine cover of what is coming"
    return it, cue


def cue_scenes(ctx, found, scenes):
    """{scene index: beat} for the scenes that a spoken cue decides."""
    out = {}
    for cue in sorted(found, key=lambda c: -c.priority):
        s = scene_of(scenes, ctx.words[cue.i0]["start"])
        out.setdefault(s.index, getattr(cue, "used_beat", None) or CUE_BEAT[cue.kind])
    return out


# ---------------------------------------------------------------- the whole thing

def captions_present(project):
    return any(t["kind"] == "caption" and not t.get("hidden") and t["clips"] for t in project["tracks"])


def clear_own(project):
    """Remove the clips this planner made earlier (ids "pe..." on "pe-..." tracks), except locked."""
    removed = 0
    for t in project["tracks"]:
        if str(t["id"]).startswith("pe-"):
            keep = [c for c in t["clips"] if c.get("locked")]
            removed += len(t["clips"]) - len(keep)
            t["clips"] = keep
    project["tracks"] = [t for t in project["tracks"] if not str(t["id"]).startswith("pe-") or t["clips"]]
    return removed


def own_track(project, tid, kind, name):
    track = next((t for t in project["tracks"] if t["id"] == tid), None)
    if track is None:
        track = {"id": tid, "kind": kind, "name": name, "clips": []}
        anchor = max((k for k, t in enumerate(project["tracks"]) if t["kind"] in ("video", "effect", "overlay")),
                     default=0)
        project["tracks"].insert(anchor + 1, track)
    return track


def free_on(track, start, end):
    return all(end <= c["start"] + EPS or start >= c["start"] + c["duration"] - EPS for c in track["clips"])


def zoom_busy(project, start, end):
    """True when a zoom the edit already has (jump-cut zooms, the creator's own) covers this time."""
    return any(c.get("type") == "zoom" and c["start"] < end - EPS and c["start"] + c["duration"] > start + EPS
               for t in project["tracks"] if t["kind"] == "effect" and not str(t["id"]).startswith("pe-")
               for c in t["clips"])


def add_effect_clips(project, ctx, ids, items, effects, pips, scenes):
    """Dimming + vignette under the big picture beats, the camera moves, the B&W transitions and
    the floating PiP clips, on the planner's own tracks."""
    look = own_track(project, "pe-look", "effect", "Editorial look")
    vig = own_track(project, "pe-vignette", "effect", "Editorial vignette")
    cam = own_track(project, "pe-camera", "effect", "Editorial camera")
    trans = own_track(project, "pe-transitions", "effect", "Editorial transitions")
    pipt = own_track(project, "pe-pip", "overlay", "Editorial picture-in-picture")
    fps = ctx.fps

    def put(track, clip):
        if clip["duration"] < 2 / fps or not free_on(track, clip["start"], clip["start"] + clip["duration"]):
            return False
        track["clips"].append(clip)
        return True

    for it in items:
        card = it.get("covers_face") and it["template"] not in ("kinetic-words", "editorial-headline")
        if BEATS[it["beat"]][1] != "cover" and not card:
            continue
        d = round(it["end"] - it["start"], 4)
        amount, blur = (0.35, 8) if card else (0.5, 14)
        put(look, {"id": next(ids), "type": "dim", "start": round(it["start"], 4), "duration": d, "amount": amount,
                   "blur": blur, "fade": 0.3, "label": "Dim behind the card" if card else "Dim behind the pictures"})
        put(vig, {"id": next(ids), "type": "vignette", "start": round(it["start"], 4), "duration": d, "strength": 0.65,
                  "fade": 0.3, "label": "Vignette"})
    for e in effects:
        if e["type"] == "zoom":
            start, end = snap(e["start"], fps), snap(e["end"], fps)
            if end - start < 0.3 or zoom_busy(project, start, end):
                continue
            clip = {"id": next(ids), "type": "zoom", "start": start, "duration": round(end - start, 4),
                    "amount": e["amount"], "anchor_y": e.get("anchor_y", 0.4), "ease": e["ease"],
                    "smooth": bool(e.get("smooth")), "label": "Punch-in" if e["amount"] > 1.0 and e.get("from", 1.0) <= 1 and e["ease"] < 0.5 else "Camera move"}
            if e.get("from", 1.0) != 1.0:
                clip["from"] = e["from"]
            put(cam, clip)
        elif e["type"] == "bw":
            put(trans, {"id": next(ids), "type": "fx", "effect": "bw", "start": snap(e["start"], fps),
                        "duration": round(e["duration"], 4), "intensity": 1.0, "label": "B&W transition"})
        elif e["type"] == "look":
            # the past told in black and white, dimmed and vignetted; colour again on "ngayon"
            start, end = snap(max(0.0, e["start"]), fps), snap(e["end"], fps)
            d = round(end - start, 4)
            put(trans, {"id": next(ids), "type": "fx", "effect": "bw", "start": start, "duration": d,
                        "intensity": 1.0, "ramp": 0.3, "label": "Before: black and white"})
            put(look, {"id": next(ids), "type": "dim", "start": start, "duration": d, "amount": 0.3, "blur": 0,
                       "fade": 0.2, "label": "Before: dimmed"})
            put(vig, {"id": next(ids), "type": "vignette", "start": start, "duration": d, "strength": 0.85,
                      "fade": 0.2, "label": "Before: vignette"})
    for p in pips:
        m = next(x for x in project["media"] if x["id"] == p["media"])
        start, end = snap(p["start"], fps), snap(p["end"], fps)
        clip = {"id": next(ids), "type": m["kind"], "media": m["id"], "start": start, "duration": round(end - start, 4),
                **PIP_BOX, "radius": 34, "shadow": 0.7, "border": {"color": "#f4efe6", "width": 6},
                "enter": "slide_left", "exit": "fade", "motion": 0.4, "label": "Floating picture-in-picture"}
        if m["kind"] == "video":
            length = min(end - start, max(0.0, float(m.get("duration") or 0)))
            if length < 0.5:
                continue
            clip["duration"] = round(length, 4)
            clip["in"], clip["out"] = 0.0, round(length, 4)          # overlays are silent
        put(pipt, clip)
    for t in (look, vig, cam, trans, pipt):
        t["clips"].sort(key=lambda c: c["start"])
    project["tracks"] = [t for t in project["tracks"] if not str(t["id"]).startswith("pe-") or t["clips"]]


MAX_GAP = 4.0              # never longer than this without something changing on screen


def visible_changes(project):
    """The times something visibly changes: a graphic or an effect starts or ends, a cut, the
    speaker moving lower or back."""
    times = set()
    for t in project["tracks"]:
        if t.get("hidden"):
            continue
        for c in t["clips"]:
            if t["kind"] in ("graphics", "effect", "overlay") or (t["kind"] == "video" and c is not t["clips"][0]):
                times.add(round(c["start"], 3))
            if t["kind"] in ("graphics", "overlay") or c.get("type") == "layout":
                times.add(round(c["start"] + c["duration"], 3))
    return sorted(times)


def keep_the_rhythm(project, ctx, ids, window=None):
    """A camera move (a slow push or a punch-in, alternating) wherever more than MAX_GAP seconds
    pass with nothing changing, on a spoken word (only inside `window` (start, end) when given: a
    regenerated scene). Returns how many were added."""
    cam = own_track(project, "pe-camera", "effect", "Editorial camera")
    words = [w["start"] for w in ctx.words]
    if not words:
        return 0
    added, flip = 0, False
    for _ in range(40):
        times = [t for t in visible_changes(project) if t <= ctx.duration]
        marks = sorted(set([words[0]] + times + [ctx.duration]))
        gap = next(((a, b) for a, b in zip(marks, marks[1:]) if b - a > MAX_GAP and a < words[-1]), None)
        if gap is None:
            break
        a, b = gap
        at = next((w for w in words if a + 2.0 <= w <= a + 3.5), None) or min(a + 3.0, b - 0.5)
        at = snap(at, ctx.fps)
        if window and not (window[0] - EPS <= at < window[1] - EPS):
            break
        d = round(min(1.6, max(0.8, b - at - 0.1)), 4)
        clip = {"id": next(ids), "type": "zoom", "start": at, "duration": d, "anchor_y": 0.4,
                "label": "Camera move (keeps the rhythm)"}
        clip.update({"amount": 1.12, "ease": 0.0, "smooth": False} if flip else {"amount": 1.08, "ease": 0.6, "smooth": True})
        if not free_on(cam, at, at + d):
            cam["clips"] = [c for c in cam["clips"] if not (c["start"] < at + d and c["start"] + c["duration"] > at)]
        cam["clips"].append(clip)
        cam["clips"].sort(key=lambda c: c["start"])
        added += 1
        flip = not flip
    return added


def bw_transitions(ctx, scenes, chosen):
    """A B&W transition into the scenes that turn the story (and those the AI asked for), at most
    one every BW_GAP seconds, never on the first scene."""
    out, last = [], -99.0
    for s, c in zip(scenes, chosen):
        if s.index == 0:
            continue
        first = [norm(w["text"]) for w in ctx.words[s.i0:min(s.i1, s.i0 + 2) + 1]]
        wanted = c.get("bw") if c.get("bw") is not None else bool(TURN_WORDS & set(first))
        if wanted and s.start - last >= BW_GAP:
            d = 0.7
            out.append({"type": "bw", "start": max(0.0, s.start - d / 2), "duration": d})
            last = s.start
    return out


def time_item(ctx, it, scene, next_start):
    """End time of a graphic: through its scene (at least long enough to take in), never into the
    next graphic, never past the video."""
    meta = graphics.template_meta(it["template"])
    lo, hi = meta["minDuration"], meta["maxDuration"]
    want_end = max(scene.end, it["start"] + max(lo, 1.6))
    end = min(it["start"] + hi, want_end, ctx.duration)
    if next_start is not None:
        end = min(end, next_start - 0.08)
    end = snap(end, ctx.fps)
    if end - it["start"] < max(lo * 0.6, 0.5):
        return False
    it["end"] = end
    return True


def build_params(it, meta, dctx):
    fields = set(meta["fields"]) | {i["key"] for i in meta["inputs"]}
    p = {}
    if "text" in fields and it.get("text"):
        p["text"] = director.shorten(it["text"], meta["maxChars"])
    if "text2" in fields:
        p["text2"] = (it.get("text2") or "")[:60]     # empty, never the template's sample ("@yourhandle")
    if "items" in fields and it.get("list"):
        p["items"] = [x[:40] for x in it["list"]][:8 if meta["id"] == "tile-mosaic" else 5]
    if "number" in fields and it.get("number") is not None:
        p["number"] = it["number"]
    if "image" in fields and it.get("image"):
        p["image"] = it["image"]
    if "images" in fields and it.get("images"):
        p["images"] = list(it["images"])[:9]
    if "cues" in fields and it.get("cues"):
        p["cues"] = sorted(round(float(x), 3) for x in it["cues"] if x >= 0)[:24]
    if "size" in fields and it.get("size_final"):
        p["size"] = it["size_final"]
    return p


def choose_beats(ctx, scenes, assets, captions_on, choices, kept=None, exclude=None):
    """One entry per scene: {"beat", "choice", "bw"} (or {"beat", "kept": True} for a scene that
    keeps what it has). The AI's choice when it is allowed here, else the rules'."""
    kept, exclude = kept or {}, exclude or {}
    chosen = []
    for k, s in enumerate(scenes):
        if s.index in kept:
            chosen.append({"beat": kept[s.index], "kept": True})
            continue
        after = kept.get(scenes[k + 1].index) if k + 1 < len(scenes) else None
        ex = exclude.get(s.index, set())
        ch = choices.get(s.index)
        if ch and ch["beat"] not in ex and allowed(ch["beat"], ctx, s, assets, chosen, captions_on, after):
            beat = ch["beat"]
        else:
            ch = None
            beat = rule_beat(ctx, s, assets, chosen, captions_on, len(scenes), ex, after)
        chosen.append({"beat": beat, "choice": ch or {}, "bw": (ch or {}).get("bw")})
    return chosen


LAYOUT_LEAD = 0.35          # the speaker is already down when the card arrives
NO_LAYOUT = {"label-pill"}


def add_layouts(project, ctx, items):
    """"speaker_low" layout clips under the cards: the speaker eases into the lower part of the
    frame a moment before a card arrives and back up after it, so the card takes the top and never
    covers the face (the reference look). Cards close together share one move."""
    if not (ctx.cfg.get("graphics") or {}).get("speaker_low", True):
        for it in items:
            it["respect_face"] = True
        return
    for it in items:
        it["respect_face"] = True
    spans = sorted((it["start"], min(ctx.duration, it["end"] + LAYOUT_LEAD))
                   for it in items if it["template"] not in NO_LAYOUT)
    merged = []
    for first, b in spans:
        a = max(0.0, math.floor((first - LAYOUT_LEAD) * ctx.fps) / ctx.fps)    # down before the card
        if merged and a <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b, first])
    track = own_track(project, "pe-layout", "effect", "Editorial layout (speaker lower)")
    ids = director.next_ids(project, "pel")
    for a, b, first in merged:
        b = snap(b, ctx.fps)
        fade = max(0.0, min(LAYOUT_LEAD, first - a - 0.5 / ctx.fps))   # a card at the very start: a quicker move
        if b - a < 0.8:
            continue
        # a move already there (another scene's card, a regenerated scene) grows to cover this one
        near = [c for c in track["clips"] if not c.get("locked") and c["start"] <= b + 1.0 and
                c["start"] + c["duration"] >= a - 1.0]
        if near:
            c = near[0]
            end = max(c["start"] + c["duration"], b)
            c["start"] = min(c["start"], a)
            c["duration"] = round(end - c["start"], 4)
            clip = c
        elif free_on(track, a, b):
            clip = {"id": next(ids), "type": "layout", "mode": "speaker_low", "start": round(a, 4),
                    "duration": round(b - a, 4), "scale": 0.62, "fade": round(fade, 4),
                    "label": "Speaker lower (card on top)"}
            track["clips"].append(clip)
        else:
            continue
        if clip["start"] + clip["duration"] >= ctx.duration - 0.05:
            clip["stay"] = True              # the video ends with the card: no move back up
    track["clips"].sort(key=lambda c: c["start"])
    project["tracks"] = [t for t in project["tracks"] if t["id"] != "pe-layout" or t["clips"]]


def build(ctx, project, scenes, chosen, assets, captions_on, extra=(), used_images=None):
    """The clips for the scenes that are not kept: graphics (timed and placed by the Director's
    rules: off the face unless made to cover it, never on the captions, inside the safe area),
    effect specs and PiP specs. `extra`: items already timed (the spoken cues). Changes `chosen`
    when a beat cannot be built (camera instead)."""
    by_index = {s.index: s for s in scenes}
    used_images = used_images if used_images is not None else Counter()
    items, effects, pips = [], [], []
    for s, c in zip(scenes, chosen):
        if c.get("kept"):
            continue
        it, eff, pip = element(ctx, s, c["beat"], assets, c.get("choice"), used_images, captions_on)
        if it is None and BEATS[c["beat"]][0] is not None:
            # the beat could not be built here: a quiet camera move keeps the rhythm
            c["beat"] = "camera"
            it, eff, pip = element(ctx, s, "camera", assets, {}, used_images, captions_on)
        if it is not None:
            items.append(it)
        effects += eff
        pips += pip
    starts = sorted([x["start"] for x in items] + [x["start"] for x in extra] + [c["start"] for c in ctx.fixed])
    timed = list(extra)
    for it in sorted(items, key=lambda x: x["start"]):
        nxt = next((t for t in starts if t > it["start"] + EPS), None)
        inside = any(x["start"] - EPS <= it["start"] < x["end"] - EPS for x in extra)   # a spoken card is on
        if not inside and time_item(ctx, it, by_index[it["scene"]], nxt):
            timed.append(it)
        elif it["template"] == "label-pill":
            continue                    # the PiP stays, without its label
        else:
            chosen_for(scenes, chosen, it["scene"])["beat"] = "camera"
            effects += element(ctx, by_index[it["scene"]], "camera", assets, {}, used_images, captions_on)[1]
    add_layouts(project, ctx, timed)
    placed = director.place_items(ctx, timed)
    kept_ids = {id(x) for x in placed}
    for it in timed:
        if id(it) not in kept_ids:
            if it.get("cue"):
                ctx.note(f"The {it['cue']} graphic at {director.mmss(it['start'])} was left out: no free space "
                         "that keeps the face and captions clear.")
                continue
            if it["template"] == "label-pill":
                continue
            chosen_for(scenes, chosen, it["scene"])["beat"] = "camera"
            effects += element(ctx, by_index[it["scene"]], "camera", assets, {}, used_images, captions_on)[1]
    ids = director.next_ids(project, "g")
    clips = []
    for it in placed:
        meta = graphics.template_meta(it["template"])
        clips.append({"id": next(ids), "type": "graphic", "start": round(it["start"], 4),
                      "duration": round(it["end"] - it["start"], 4), "template": it["template"],
                      "x": it["x"], "y": it["y"], "params": build_params(it, meta, ctx),
                      "label": f"{meta['name']}: {strip_marks(it.get('text') or it.get('spoken', ''))}"[:120],
                      "director": {"style": STYLE, "beat": it["beat"], "scene": it["scene"], "mood": it.get("mood"),
                                   "words": scene_text(ctx, by_index[it["scene"]])[:200],
                                   "importance": it["importance"], "reason": it["reason"],
                                   "kind": meta["category"],
                                   **({"covers_face": True, "cue": it["cue"]} if it.get("covers_face") else
                                      ({"cue": it["cue"]} if it.get("cue") else {})),
                                   **({"assets": it["asset_why"]} if it.get("asset_why") else {})}})
    return clips, placed, effects, pips


def chosen_for(scenes, chosen, index):
    return next(c for s, c in zip(scenes, chosen) if s.index == index)


def plan_rows(ctx, scenes, chosen):
    return [{**s.as_dict(), "beat": c["beat"], "text": scene_text(ctx, s)[:120]} for s, c in zip(scenes, chosen)]


def add_files(project, files):
    """The creator's uploaded pictures and clips as project media (those the edit has not used
    yet), so the scenes can show them."""
    from pathlib import Path

    from .project import media_from_file
    have = {str(Path(m["path"]).resolve()) for m in project["media"] if Path(m["path"]).is_absolute()}
    ids = director.next_ids(project, "pem")
    for f in files or ():
        path = Path(f).resolve()
        if str(path) in have or not path.is_file():
            continue
        m = media_from_file(path, next(ids))
        if m["kind"] in ("image", "video"):
            project["media"].append(m)
            have.add(str(path))


def generate(project, cfg, instruction="", provider=None, model=None, cache=None, reporter=None, cancel=None,
             video=None, use_ai=True, base_dir=None, files=()):
    """Plan and add the whole editorial edit to a copy of the project. Returns the same dict as
    director.generate (project, count, style, notes, fallback, reason, cost, usage, plan...), plus
    `scenes` (the plan, scene by scene, also saved in meta.editorial). `files`: the creator's
    uploaded pictures / clips (added to the project's media when the edit has not used them)."""
    project = copy.deepcopy(project)
    add_files(project, files)
    removed = director.clear_director_clips(project) + clear_own(project)
    if reporter:
        reporter.stage("graphics", "Planning the editorial scenes")
    steplog.phase("graphics: finding the face (its own time limit)", limit=0)
    director.face_for(project, video, cfg, cache, reporter, cancel)
    steplog.phase("graphics: scenes, what is said, your files")
    ctx = Ctx(project, cfg, STYLE, instruction, fixed=director.fixed_graphics(project),
              face=zones.FaceMap(project, zones.TALKING_HEAD_FACE))
    empty = {"project": project, "count": 0, "style": STYLE, "fallback": False, "reason": "", "cost": None,
             "usage": {}, "plan": [], "wipe": None, "removed": removed, "scenes": []}
    if not ctx.words:
        return {**empty, "notes": ["No spoken words, so no editorial scenes."]}
    scenes = make_scenes(ctx.words, ctx.duration)
    assets = Assets(project, cfg, base_dir)
    captions_on = captions_present(project)
    # what is said decides its scenes (a countdown, a search, a list...); the others get beats
    found = cues_mod.extract(ctx.words)
    pins, pin_notes = pinned_cues(ctx, assets)
    found = sorted(found + pins, key=lambda c: (ctx.words[c.i0]["start"], -c.priority))
    handle = next((c.text for c in found if c.kind == "handle"), None)
    used_images = Counter()
    cue_items, cue_effects, cue_notes, made = cue_elements(ctx, found, scenes, assets, used_images, handle)
    fixed_scenes = cue_scenes(ctx, made, scenes)
    steplog.phase("graphics: AI scene plan (the AI's own time limits)")
    choices, usage, used_model, attempts, cached = {}, {"input_tokens": 0, "output_tokens": 0}, model, [], False
    fallback, reason = False, ""
    open_scenes = len(scenes) - len(fixed_scenes)
    if use_ai and provider and not open_scenes:
        ctx.note(f"All {len(scenes)} scenes are set by what you say, so no AI scene plan was needed.")
    elif use_ai and provider:
        choices, usage, used_model, attempts, cached = request_choices(ctx, scenes, assets, captions_on, provider,
                                                                       model, cache, cancel, fixed_scenes, reporter)
        if not choices and attempts:
            fallback = True
            first = attempts[-1]["problems"][0] if attempts[-1]["problems"] else "no answer"
            reason = (f"The AI scene plan could not be used ({first}) - the scenes were planned by the "
                      "editorial rules instead; what you say still sets its graphics. "
                      f"Log: {RequestLog(cfg).path}")
        elif attempts:
            ctx.note(f"The AI scene plan was used for {len(choices)} of {open_scenes} scenes; the others were "
                     f"planned by the rules ({attempts[-1]['problems'][0]}).")
    steplog.phase("graphics: building the cards, looks and layout")
    chosen = choose_beats(ctx, scenes, assets, captions_on, choices, kept=fixed_scenes)
    clips, placed, effects, pips = build(ctx, project, scenes, chosen, assets, captions_on, extra=cue_items,
                                         used_images=used_images)
    for c in chosen:
        c.pop("kept", None)
    looks = [e for e in cue_effects if e["type"] == "look"]
    effects += cue_effects + [b for b in bw_transitions(ctx, scenes, chosen)
                              if all(abs(b["start"] - lk["start"]) > 3 for lk in looks)]
    director.lay_out(project, clips)
    add_effect_clips(project, ctx, director.next_ids(project, "pe"), placed, effects, pips, scenes)
    moves = keep_the_rhythm(project, ctx, director.next_ids(project, "per"))
    if moves:
        ctx.note(f"Added {moves} camera move(s) so something changes every 2-4 seconds.")
    rows = plan_rows(ctx, scenes, chosen)
    meta = project.setdefault("meta", {})
    meta["editorial"] = {"scenes": rows}
    meta["graphics"] = {"style": STYLE, "count": len(clips), "fallback": fallback}
    from .costs import plan_cost
    ai = cfg.get("ai") or {}
    cost = plan_cost(ai.get("prices") or {}, used_model, usage["input_tokens"], usage["output_tokens"]) \
        if (used_model and usage["input_tokens"]) else (0.0 if cached else None)
    notes = list(ctx.notes) + [n for n in cue_notes if n not in ctx.notes]
    made = [(it["cue"], it["start"], it.get("spoken") or it.get("text") or "") for it in placed if it.get("cue")]
    made += [("before_after", e["start"], "") for e in cue_effects if e["type"] == "look"]
    notes = requested_lines(instruction, made) + pin_notes + notes
    if not (assets.images or assets.videos or assets.logo):
        notes.append("No screenshots, photos or clips of yours were given, so the picture beats "
                     "(collage, montage, phone, PiP...) were left out. Add your own files to use them.")
    if not ctx.face.known:
        why = (project.get("meta") or {}).get("face_problem")
        notes.append("The face was not found" + (f" ({why})" if why else "") + ", so cards keep to safe zones: "
                     "the speaker moves lower while a card is up and cards stay off where a face usually is.")
    else:
        src = {d.get("source") for d in (project.get("tracking") or {}).values()}
        if "opencv-haar" in src:
            notes.append("Your face was found by the built-in face finder; cards keep off it (the speaker "
                         "moves lower while a card is up).")
    return {"project": project, "count": len(clips), "style": STYLE, "notes": notes, "fallback": fallback,
            "reason": reason, "cost": cost, "usage": usage, "model": used_model, "plan": placed, "wipe": None,
            "removed": removed, "summary": f"{len(scenes)} scenes", "attempts": attempts, "cached": cached,
            "scenes": rows, "assets": asset_report(project, assets, ctx)}


# what an instruction can ask for -> (cue kinds that make it, a name, what to say to get it)
REQUESTS = [
    ("countdown", re.compile(r"count ?down|bilang pababa", re.I), {"countdown"},
     "say the numbers down, e.g. \"Tatlo, dalawa, isa!\""),
    ("big word title", re.compile(r"big word|malaking (word|salita)|word card|title|kinetic", re.I), {"keyword", "magazine"},
     "say \"Una: DISIPLINA\" (a word after Una / Pangalawa)"),
    ("search bar", re.compile(r"search ?bar|search box|nagta-?type|typing", re.I), {"search"},
     "say \"sa search bar, hinanap ko ...\""),
    ("screenshot", re.compile(r"screenshot|resulta", re.I), {"screenshot"},
     "say \"tingnan ninyo ang screenshot / resulta ko\" with a picture whose name matches"),
    ("checklist", re.compile(r"check ?list|listahan", re.I), {"checklist"},
     "say \"checklist ko: a, b, c\""),
    ("logo cards", re.compile(r"logos?\b", re.I), {"platforms"},
     "name the apps (\"Nasa TikTok, Facebook at YouTube ako\")"),
    ("profile card", re.compile(r"profile", re.I), {"handle", "follow"},
     "say your @handle or \"i-follow mo ako\""),
    ("storyboard card", re.compile(r"storyboard", re.I), {"storyboard"},
     "say \"Storyboard ko: hook, kwento, call to action\""),
    ("number cards", re.compile(r"stats?\b|number cards?|numbers", re.I), {"stats"},
     "say two numbers with what they count (\"mula zero hanggang isang libong followers\")"),
    ("black and white", re.compile(r"black.and.white|b ?& ?w|itim at puti", re.I), {"before_after"},
     "say \"Dati ...\" then \"Ngayon ...\""),
]


def requested_lines(instruction, made):
    """One line per kind of card the instruction asks for: where it was made, or why not.
    `made`: [(cue kind, start, words)]."""
    lines = []
    for name, pattern, kinds, how in REQUESTS:
        if not pattern.search(instruction or ""):
            continue
        hits, seen = [], set()
        for k, t, w in sorted(made, key=lambda m: (m[1], not m[2])):
            if k in kinds and round(t) not in seen:
                seen.add(round(t))
                hits.append((t, w))
        if hits:
            where = ", ".join(director.mmss(t) + (f" (\"{w[:40]}\")" if w else "") for t, w in hits[:3])
            lines.append(f"You asked for {name}: made at {where}.")
        else:
            lines.append(f"You asked for {name}: nothing in what you said asks for it, so none was "
                         f"made (to get one, {how}).")
    return lines


def remove_scene_elements(project, scene):
    """Remove this planner's unlocked clips that start inside a scene (its graphics, dimming,
    vignette, camera move and PiP; the B&W transitions belong to the cuts between scenes and stay)."""
    for t in project["tracks"]:
        inside = [c for c in t["clips"] if scene.start - EPS <= c["start"] < scene.end - EPS and not c.get("locked")]
        if t["kind"] == "graphics":
            inside = [c for c in inside if (c.get("director") or {}).get("style") == STYLE]
        elif not str(t["id"]).startswith("pe-") or t["id"] == "pe-transitions":
            continue
        drop = {c["id"] for c in inside}
        t["clips"] = [c for c in t["clips"] if c["id"] not in drop]
    project["tracks"] = [t for t in project["tracks"] if not (str(t["id"]).startswith("pe-") and not t["clips"])]


def saved_scenes(project, words):
    """The scenes of the saved plan (meta.editorial), with their words; None without a plan."""
    rows = ((project.get("meta") or {}).get("editorial") or {}).get("scenes") or []
    if not rows:
        return None, {}
    scenes, beats = [], {}
    for r in sorted(rows, key=lambda r: r["start"]):
        idx = [i for i, w in enumerate(words) if r["start"] - EPS <= w["start"] < r["end"] - EPS]
        if idx:
            scenes.append(Scene(r["index"], idx[0], idx[-1], r["start"], r["end"]))
            beats[r["index"]] = r["beat"]
    return scenes, beats


def regenerate_scene(project, scene_index, cfg, instruction="", cache=None, cancel=None, base_dir=None,
                     graphic_only=False):
    """Another beat for one scene (not the one it has now); the other scenes stay as they are.
    graphic_only: the new beat must be a graphic (not PiP or a camera move).
    Returns {"project", "beat", "before", "clips" (ids of the new clips), "notes"}."""
    project = copy.deepcopy(project)
    words = director.timeline_words(project)
    scenes, beats = saved_scenes(project, words)
    if scenes is None:
        raise director.DirectorError("This video has no editorial scene plan yet. Make the edit with the "
                                     "PREMIUM EDITORIAL VIRAL preset (or the premium_editorial style) first.")
    scene = next((s for s in scenes if s.index == scene_index), None)
    if scene is None:
        raise director.DirectorError(f"There is no editorial scene {scene_index + 1} with words in this video.")
    locked = [c for t in project["tracks"] if t["kind"] == "graphics" or str(t["id"]).startswith("pe-")
              for c in t["clips"] if c.get("locked") and scene.start - EPS <= c["start"] < scene.end - EPS]
    if locked:
        raise director.DirectorError("This scene has a locked graphic or effect. Unlock it first.")
    before = beats.get(scene_index)
    remove_scene_elements(project, scene)
    ctx = Ctx(project, cfg, STYLE, instruction, words=words, fixed=director.graphic_clips_of(project),
              face=zones.FaceMap(project, zones.TALKING_HEAD_FACE))
    assets = Assets(project, cfg, base_dir)
    captions_on = captions_present(project)
    kept = {i: b for i, b in beats.items() if i != scene_index}
    exclude = {before} | {b for b in kept.values() if b in ONCE}
    if graphic_only:
        exclude |= {b for b, spec in BEATS.items() if spec[0] is None}
    chosen = choose_beats(ctx, scenes, assets, captions_on, {}, kept, {scene_index: exclude - {None}})
    clips, placed, effects, pips = build(ctx, project, scenes, chosen, assets, captions_on)
    beat = chosen_for(scenes, chosen, scene_index)["beat"]
    if graphic_only and not clips:
        raise director.DirectorError("No other graphic fits this scene without covering the face or the captions.")
    before_ids = {c["id"] for t in project["tracks"] for c in t["clips"]}
    director.lay_out(project, clips)
    add_effect_clips(project, ctx, director.next_ids(project, "pe"), placed, effects, pips, scenes)
    moves = keep_the_rhythm(project, ctx, director.next_ids(project, "per"), window=(scene.start, scene.end))
    if moves:
        ctx.note(f"Added {moves} camera move(s) so something changes every 2-4 seconds.")
    rows = plan_rows(ctx, scenes, chosen)
    old_rows = {r["index"]: r for r in project["meta"]["editorial"]["scenes"]}
    for r in rows:
        if r["index"] != scene_index and r["index"] in old_rows:
            r["beat"] = old_rows[r["index"]]["beat"]
    project["meta"]["editorial"]["scenes"] = rows
    new_ids = [c["id"] for t in project["tracks"] for c in t["clips"] if c["id"] not in before_ids]
    return {"project": project, "beat": beat, "before": before, "clips": new_ids, "notes": list(ctx.notes)}
