"""The Director: reads what is said and places motion graphics (pop-up words, cards, counters,
arrows, emoji...) on a Graphics track.

    words      the spoken words on the finished timeline (captions: cuts applied, corrections applied)
    plan       the AI picks template, words, text, mood and emphasis for each important phrase
               (checked against a JSON schema and the transcript; one retry; then a rule-based plan)
    rules      then plain code, the same for the AI plan and the fallback, enforces what must hold:
               - sync:     a graphic starts on the frame of the word it belongs to
               - density:  at most N graphics per 10 s, a minimum gap, no pile-ups
               - variety:  never the same template twice in a row; no template overused
               - mood:     the template suits the mood of the sentence
               - space:    never on the speaker's face, never on the captions, inside the safe area
               - reading:  text is short, large enough and has contrast
    project    the graphics become ordinary clips on "Graphics" tracks (movable, editable, lockable)
"""

import copy
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter

from . import graphics, zones
from .director_styles import (CTA_WORDS, DEFAULT_STYLE, EMOJI_FOR_MOOD, GRAPHICS_WORDS,
                              ICON_FOR_MOOD, MOOD_WORDS, STOPWORDS, STYLE_KEYWORDS, STYLES)
from .errors import Cancelled, EditorError
from .llm import LLMError, ask_json

PROMPT_VERSION = 1
MAX_ATTEMPTS = 2
FRAME_W, FRAME_H = graphics.FRAME_W, graphics.FRAME_H
COMPANION = ("pointer", "emoji")            # may sit on top of another graphic's moment
GROUPS = {"text": "text", "card": "block", "pill": "block", "banner": "block", "data": "data",
          "pointer": "pointer", "emoji": "emoji"}
MIN_SIZE = 0.6
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class DirectorError(EditorError):
    pass


# ---------------------------------------------------------------- small helpers

def frame_of(t, fps):
    return int(math.floor(t * fps + 0.5 + 1e-9))


def snap(t, fps):
    """The time of the frame nearest to t."""
    return frame_of(t, fps) / fps


def norm(text):
    text = unicodedata.normalize("NFC", str(text)).lower().replace("*", "")
    return re.sub(r"[^\w\-']+", "", text, flags=re.UNICODE).strip("-'")


def strip_marks(text):
    return str(text).replace("*", "")


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def mmss(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


# ---------------------------------------------------------------- the words

def timeline_words(project):
    """Every spoken word on the finished timeline: [{"text", "start", "end", "hl"}]."""
    out = []
    for track in project["tracks"]:
        if track["kind"] != "caption" or track.get("hidden"):
            continue
        for clip in track["clips"]:
            for w in clip["words"]:
                out.append({"text": w["text"], "start": round(clip["start"] + w["start"], 4),
                            "end": round(clip["start"] + w["end"], 4),
                            "hl": bool(w.get("highlight"))})
    return sorted(out, key=lambda w: (w["start"], w["end"]))


def locate(words, phrase, near, window=2.5):
    """Find the spoken words of `phrase` close to time `near`.
    Returns (first index, last index, exact) or None. exact = every word matched in order."""
    toks = [t for t in (norm(x) for x in str(phrase).split()) if t]
    if not toks or not words:
        return None
    norms = [norm(w["text"]) for w in words]
    n = len(toks)
    best = None
    for i in range(0, len(words) - n + 1):
        if norms[i:i + n] == toks:
            cost = abs(words[i]["start"] - near)
            if cost <= window and (best is None or cost < best[0]):
                best = (cost, i, i + n - 1)
    if best:
        return best[1], best[2], True
    # the longest word of the phrase, closest to `near`
    for tok in sorted(set(toks), key=len, reverse=True):
        hits = [(abs(words[i]["start"] - near), i) for i, w in enumerate(norms) if w == tok]
        hits = [h for h in hits if h[0] <= window]
        if hits:
            _c, i = min(hits)
            return i, i, False
    return None


def important(token):
    t = norm(token)
    return bool(t) and t not in STOPWORDS and (len(t) > 2 or t.isdigit())


def word_mood(tokens):
    """The mood the words suggest (best match of the mood word lists) or None."""
    norms = [norm(t) for t in tokens]
    best, score = None, 0
    for mood, vocab in MOOD_WORDS.items():
        hits = sum(1 for t in norms if t in vocab)
        if hits > score:
            best, score = mood, hits
    return best


def sentences(words, pause=0.6):
    """Split the words into sentences: a pause or . ? ! ends one."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 99
        if gap >= pause or re.search(r"[.?!…]$", w["text"].strip("*\"'")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- styles

def style_names():
    return list(STYLES)


def resolve_style(cfg, instruction="", explicit=None):
    """The style to use, or None when no graphics are wanted.

    explicit: a style name, "off", or "auto"/None (then config graphics.style: a name, "off" or
    "auto"; auto = graphics only when the instruction asks for them or names a look)."""
    choice = str(explicit or (cfg.get("graphics") or {}).get("style") or "auto").lower()
    if choice in ("off", "none", "no", "false"):
        return None
    if choice in STYLES:
        return choice
    if choice != "auto":
        raise DirectorError(f"Unknown graphics style '{choice}'. Choose: auto, off, "
                            + ", ".join(STYLES))
    text = " " + str(instruction or "").lower() + " "
    for name in ("premium_editorial", "calm_documentary", "meme", "news", "luxury", "minimal", "promoter"):
        if any(k in text for k in STYLE_KEYWORDS[name]):
            return name
    if any(k in text for k in GRAPHICS_WORDS):
        return DEFAULT_STYLE
    return None


# ---------------------------------------------------------------- context

class Ctx:
    """Everything the rules need to know about the video."""

    def __init__(self, project, cfg, style, instruction="", face=None, words=None, fixed=None):
        self.project, self.cfg, self.style_name = project, cfg, style
        self.style = STYLES[style]
        self.instruction = instruction or ""
        self.fps = project["settings"]["fps"]
        self.words = words if words is not None else timeline_words(project)
        main = next((t for t in project["tracks"] if t["kind"] == "video"), None)
        ends = [c["start"] + c["duration"] for c in (main["clips"] if main else [])]
        self.duration = max(ends) if ends else (self.words[-1]["end"] if self.words else 0.0)
        self.face = face if face is not None else zones.FaceMap(project)
        self.fixed = list(fixed or [])        # graphics that stay (locked, or the creator's own)
        g = cfg.get("graphics") or {}
        self.max_per_10s = int(g.get("max_per_10s") or self.style["max_per_10s"])
        self.min_font = float(g.get("min_font") or 30)
        self.notes = []

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)


# ---------------------------------------------------------------- templates for an item

def meta_of(template_id):
    return graphics.template_meta(template_id)


def required_inputs(meta):
    return {i["key"] for i in meta["inputs"] if i["required"]}


def available_inputs(it):
    have = set()
    if it.get("text"):
        have.add("text")
    if it.get("number") is not None:
        have.add("number")
    if it.get("list"):
        have.add("items")
    if it.get("image"):
        have.add("image")
    if it.get("emoji"):
        have.add("emoji")
    return have


def satisfiable(meta, it):
    rng = meta.get("numRange")
    if rng and it.get("number") is not None and not rng[0] <= float(it["number"]) <= rng[1]:
        return False               # e.g. 250000 is not a star rating or a percentage
    need = required_inputs(meta)
    if "emoji" in need:       # emoji templates take their symbol from "emoji"
        need = (need - {"emoji"})
        if not it.get("emoji"):
            return False
    return need <= available_inputs(it) | {"text2"}


def group_of(meta):
    return GROUPS.get(meta["category"], meta["category"])


def style_allows(ctx, meta):
    """A template made for some styles only (`styles` in its meta, e.g. the editorial set) is never
    used by the others; templates without `styles` are open to every style."""
    only = meta.get("styles") or []
    return not only or ctx.style_name in only


def template_score(ctx, meta, it, used):
    style = ctx.style
    if meta["id"] in style["deny"] or not style_allows(ctx, meta):
        return None
    weight = style["categories"].get(meta["category"], 0.5)
    if weight <= 0:
        return None
    score = weight
    if meta["id"] in style["prefer"]:
        score += 1.5 - 0.08 * style["prefer"].index(meta["id"])
    mood = it.get("mood")
    if mood and mood in meta["moods"]:
        score += 1.2
    elif mood:
        score -= 0.6
    zone = it.get("zone")
    if zone and zone not in ("auto", None) and meta["zone"] in (zone, "any"):
        score += 0.3
    score -= 0.9 * used.get(meta["id"], 0)
    return score


def choose_template(ctx, it, group, used, exclude=()):
    """The best template of the same kind for this item (variety, mood, style), or None."""
    best = None
    for meta in graphics.templates():
        if meta["id"] in exclude or group_of(meta) != group:
            continue
        if not satisfiable(meta, it):
            continue
        score = template_score(ctx, meta, it, used)
        if score is None:
            continue
        # a stable tie-break so the same video always gets the same edit
        tie = int(hashlib.md5((meta["id"] + str(round(it["start"], 2))).encode()).hexdigest()[:6], 16) / 16 ** 6
        key = (round(score, 3), tie)
        if best is None or key > best[0]:
            best = (key, meta["id"])
    return best[1] if best else None


def shorten(text, limit):
    """Cut text to `limit` letters at a word boundary, keeping *emphasis* marks balanced."""
    words = str(text).split()
    out = []
    for w in words:
        if len(strip_marks(" ".join(out + [w]))) > limit:
            break
        out.append(w)
    if not out and words:
        out = [strip_marks(words[0])[:limit]]
    return " ".join(out)


# ---------------------------------------------------------------- raw items

def raw_item(d):
    """One planned graphic in the form the rules work with (from the AI plan or the fallback)."""
    return {
        "template": d.get("template"), "words": str(d.get("words") or "").strip(),
        "start": float(d.get("start", 0.0)), "end_hint": d.get("end"),
        "text": str(d.get("text") or "").strip(), "text2": str(d.get("text2") or "").strip(),
        "list": [str(x) for x in (d.get("list") or [])][:5], "image": str(d.get("image") or ""),
        "number": d.get("number"), "prefix": str(d.get("prefix") or ""),
        "suffix": str(d.get("suffix") or ""), "emoji": str(d.get("emoji") or ""),
        "icon": d.get("icon") or "", "zone": d.get("zone") or "auto",
        "target": d.get("target") or "none", "color": d.get("color"), "accent": d.get("accent"),
        "font": d.get("font") or "", "size": d.get("size"), "intensity": d.get("intensity"),
        "emphasis": d.get("emphasis") or "none", "mood": d.get("mood") or None,
        "importance": clamp(float(d.get("importance", 0.5)), 0.0, 1.0),
        "reason": str(d.get("reason") or "")[:160],
    }


# ---------------------------------------------------------------- the rules

def sync_items(ctx, items):
    """Step 1: anchor every item to the spoken words it belongs to; start on that word's frame."""
    out = []
    for it in items:
        hit = locate(ctx.words, it["words"] or it["text"], it["start"]) if (it["words"] or it["text"]) else None
        if hit is None and ctx.words:
            near = min(range(len(ctx.words)), key=lambda i: abs(ctx.words[i]["start"] - it["start"]))
            if abs(ctx.words[near]["start"] - it["start"]) <= 0.6:
                hit = (near, near, False)
        if hit is None:
            ctx.note(f"Skipped a graphic at {mmss(it['start'])}: the words '{(it['words'] or it['text'])[:30]}' "
                     "were not found there.")
            continue
        i0, i1, _exact = hit
        it["i0"], it["i1"] = i0, i1
        it["start"] = clamp(snap(ctx.words[i0]["start"], ctx.fps), 0.0, ctx.duration)
        it["word_end"] = ctx.words[i1]["end"]
        it["spoken"] = " ".join(strip_marks(w["text"]) for w in ctx.words[i0:i1 + 1])
        out.append(it)
    return out


def read_items(ctx, items):
    """Step 2: keep only important words, short text, a mood, a template that exists."""
    out = []
    for it in items:
        spoken = [w["text"] for w in ctx.words[it["i0"]:it["i1"] + 1]]
        if it["template"] not in graphics.template_ids():
            it["template"] = None
        meta = meta_of(it["template"]) if it["template"] else None
        # a graphic that only repeats filler words ("ang", "yung") is not worth a graphic
        carriers = [t for t in spoken if important(t)]
        if not carriers and not (meta and meta["category"] in ("emoji", "pointer")):
            ctx.note(f"Skipped a graphic at {mmss(it['start'])}: it was not on an important word.")
            continue
        if it["mood"] not in graphics.catalog()["moods"]:
            it["mood"] = None
        it["mood"] = it["mood"] or word_mood(spoken) or ("hype" if ctx.style_name == "promoter" else "serious")
        if not it["text"] and (not meta or "text" in required_inputs(meta)):
            it["text"] = " ".join(spoken[:4])
        out.append(it)
    return out


def pick_templates(ctx, items, used=None):
    """Step 3: every item gets a template that exists, fits its kind and suits its mood."""
    used = used if used is not None else Counter()
    for it in items:
        meta = meta_of(it["template"]) if it["template"] else None
        group = group_of(meta) if meta else "text"
        ok = (meta is not None and satisfiable(meta, it) and template_score(ctx, meta, it, Counter()) is not None
              and (it["mood"] in meta["moods"] or not it.get("mood")))
        if not ok:
            alt = choose_template(ctx, it, group, used)
            if alt is None and group != "text":
                alt = choose_template(ctx, it, "text", used)
            if alt is None:
                it["template"] = None
                continue
            it["template"] = alt
        used[it["template"]] += 1
    return [it for it in items if it["template"]]


def select_items(ctx, items):
    """Step 4: density and spacing. Most important first; at most N per 10 s, a minimum gap,
    and no two main graphics at the same moment."""
    n, gap = ctx.max_per_10s, ctx.style["min_gap"]
    fixed_starts = [c["start"] for c in ctx.fixed]
    accepted = []
    for it in sorted(items, key=lambda x: (-x["importance"], x["start"])):
        meta = meta_of(it["template"])
        starts = sorted([a["start"] for a in accepted] + fixed_starts + [it["start"]])
        too_dense = any(sum(1 for s in starts if a <= s < a + 10.0) > n for a in starts)
        if too_dense:
            ctx.note(f"Left out a graphic at {mmss(it['start'])}: too many graphics in 10 seconds "
                     f"(the {ctx.style['label']} style allows {n}).")
            continue
        companion = meta["category"] in COMPANION
        clash = False
        for other in accepted:
            om = meta_of(other["template"])
            if other["template"] == it["template"] and abs(other["start"] - it["start"]) < 0.01:
                clash = True
            gap_needed = 0.0 if companion or om["category"] in COMPANION else gap
            if abs(other["start"] - it["start"]) < gap_needed:
                clash = True
        for c in ctx.fixed:
            if abs(c["start"] - it["start"]) < gap and meta["category"] not in COMPANION:
                clash = True
        if clash:
            ctx.note(f"Left out a graphic at {mmss(it['start'])}: too close to another one.")
            continue
        accepted.append(it)
    return sorted(accepted, key=lambda x: (x["start"], -x["importance"]))


def vary_items(ctx, items):
    """Step 5: never the same template twice in a row (in time order), and no template overused."""
    used = Counter()
    cap = max(2, math.ceil(len(items) / 5))
    previous = None
    changed = False
    for idx, it in enumerate(items):
        meta = meta_of(it["template"])
        nxt = items[idx + 1]["template"] if idx + 1 < len(items) else None
        repeated = it["template"] == previous
        overused = used[it["template"]] >= cap and meta["category"] not in COMPANION
        if repeated or overused:
            alt = choose_template(ctx, it, group_of(meta), used, exclude={previous, it["template"], nxt})
            if alt is None:
                alt = choose_template(ctx, it, group_of(meta), used, exclude={previous, it["template"]})
            if alt is None and repeated:
                # nothing else fits this kind: try any satisfiable template at all
                alt = choose_template(ctx, it, "text", used, exclude={previous})
            if alt is not None:
                it["template"] = alt
                changed = True
        used[it["template"]] += 1
        previous = it["template"]
    return changed


def time_items(ctx, items):
    """Step 6: end times on the frame grid, long enough to read, never over the next main one."""
    fps = ctx.fps
    items = sorted(items, key=lambda x: x["start"])
    main = [it for it in items if meta_of(it["template"])["category"] not in COMPANION]
    out = []
    for it in items:
        meta = meta_of(it["template"])
        lo, hi = meta["minDuration"], meta["maxDuration"]
        want = meta["duration"] * ctx.style["duration"]
        reading = len(strip_marks(it["text"]).split()) * 0.3 + 0.9      # time to read it
        floor = max(lo, it["word_end"] - it["start"] + ctx.style["hold"], min(reading, hi))
        end = it["start"] + clamp(max(want, floor), lo, hi)
        if it.get("end_hint") is not None:
            try:
                hinted = float(it["end_hint"])
                if it["start"] + floor <= hinted <= it["start"] + hi:
                    end = hinted
            except (TypeError, ValueError):
                pass
        if meta["category"] not in COMPANION:
            later = [m["start"] for m in main if m["start"] > it["start"] + 1e-6]
            if later:
                end = min(end, later[0] - 0.08)
        end = min(end, ctx.duration)
        start = it["start"]
        end = snap(end, fps)
        if end - start < max(lo * 0.6, 3 / fps):
            ctx.note(f"Left out a graphic at {mmss(start)}: no room before the next one.")
            continue
        it["end"] = end
        out.append(it)
    return out


def estimated_params(ctx, it):
    return {"text": it.get("text") or "", "size": it.get("size_final") or 1.0}


def est_box(meta, text, size, x, y, angle=0):
    """(x0, y0, x1, y1) a graphic covers when centred at the fractions (x, y)."""
    w, h = meta["box"]["w"] * size, meta["box"]["h"] * size
    if meta["inputs"][0]["key"] == "text" and meta["category"] in ("text", "card", "pill", "banner"):
        sample = strip_marks(meta["sample"].get("text", "")) or "text"
        k = clamp(math.sqrt(max(len(strip_marks(text)), 6) / max(len(sample), 6)), 0.75, 1.5)
        h *= k
        w = min(900 * size, w * min(k, 1.2))
    if angle and meta["category"] == "pointer":
        a = math.radians(angle)
        w, h = abs(w * math.cos(a)) + abs(h * math.sin(a)), abs(w * math.sin(a)) + abs(h * math.cos(a))
    cx, cy = x * FRAME_W, y * FRAME_H
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


ZONE_ANCHOR = {"upper": (0.5, 0.17), "center": (0.5, 0.44), "lower": (0.5, 0.6),
               "left": (0.3, 0.44), "right": (0.7, 0.44)}
GRID_X = [0.5, 0.36, 0.64, 0.25, 0.75]


def candidate_points(preferred):
    px, py = preferred
    pts = []
    ys = [0.095 + 0.02 * k for k in range(0, 36)]
    for x in GRID_X:
        for y in ys:
            if y > 0.76:
                continue
            cost = math.hypot((x - px) * 0.9, (y - py) * 1.0)
            pts.append((cost, x, y))
    pts.sort()
    return [(x, y) for _c, x, y in pts]


def obstacles_for(ctx, t0, t1, face_rect):
    obs = []
    if face_rect is not None:
        obs.append(("face", zones.inflate(face_rect, zones.FACE_MARGIN)))
    for r in zones.caption_rects(ctx.project, t0, t1):
        obs.append(("caption", zones.inflate(r, zones.CAPTION_MARGIN)))
    return obs


def hand_target(ctx, which, t):
    """Where a hand is (frame pixels) at time t, from saved tracking, or None."""
    tracking = ctx.project.get("tracking") or {}
    if not tracking:
        return None
    from .tracking import Prepared, Track
    fmap = getattr(ctx.face, "fmap", None)
    if fmap is None:
        return None
    f = frame_of(t, ctx.fps)
    info = fmap.info(f)
    if info is None or info.media["id"] not in tracking:
        return None
    track = Track.from_json(tracking[info.media["id"]])
    sides = ["left", "right"] if which in ("any", "none") else [which.split("_")[0]]
    best = None
    for side in sides:
        pt = track.points.get(f"{side}_palm")
        if pt is None:
            continue
        found, u, v, _s = Prepared(pt, track.fps, track.start, 0.5).at(info.source_time)
        if found:
            x, y, _ = fmap.zoomed(f, *fmap.to_frame(info, u, v, 0.05))
            best = (x, y)
            break
    return best


def place_items(ctx, items):
    """Step 7: x / y / size for every item: off the face, off the captions, inside the safe area,
    clear of the other graphics that are on screen at the same time."""
    placed = []
    result = []
    for it in sorted(items, key=lambda x: (-x["importance"], x["start"])):
        meta = meta_of(it["template"])
        t0, t1 = it["start"], it["end"]
        face = ctx.face.rect(t0, t1)
        base_size = clamp(float(it.get("size") or ctx.style["size"]), MIN_SIZE, 1.8)
        text = it.get("text", "")
        zone = it["zone"] if it["zone"] not in (None, "auto") else None
        preferred = it.get("prefer") or (ZONE_ANCHOR.get(zone) if zone else (meta["anchor"]["x"], meta["anchor"]["y"]))
        busy = [(p["box"], p) for p in placed if p["start"] < t1 and p["end"] > t0]
        fixed_busy = [zones.inflate(graphics.estimated_box(c), 14) for c in ctx.fixed
                      if c["start"] < t1 and c["start"] + c["duration"] > t0]
        # a template made to cover the picture for a moment (a screenshot, like B-roll) may go
        # over the face; nothing goes over the captions
        obs = obstacles_for(ctx, t0, t1, None if (meta.get("covers") or it.get("covers_face")) else face)
        extra = [("graphic", zones.inflate(b, 16)) for b, _p in busy] + [("graphic", b) for b in fixed_busy]
        angle = 0
        found = None
        if meta["category"] == "pointer":
            found = place_pointer(ctx, it, meta, obs + extra, face, base_size)
        else:
            for factor in (1.0, 0.85, 0.72, 0.6):
                size = clamp(base_size * factor, MIN_SIZE, 2.0)
                if size < MIN_SIZE - 1e-9:
                    break
                for x, y in candidate_points(preferred):
                    box = est_box(meta, text, size, x, y)
                    if not zones.inside(box):
                        continue
                    if any(zones.intersects(box, r) for _k, r in obs + extra):
                        continue
                    found = (x, y, size, angle, box)
                    break
                if found:
                    break
        if not found:
            ctx.note(f"Left out a graphic at {mmss(t0)}: no free space that keeps the face and "
                     "captions clear.")
            continue
        x, y, size, angle, box = found
        it["x"], it["y"], it["size_final"] = round(x, 4), round(y, 4), round(size, 3)
        it["angle"], it["box"] = angle, box
        placed.append({"box": box, "start": t0, "end": t1})
        result.append(it)
    return sorted(result, key=lambda x: x["start"])


def place_pointer(ctx, it, meta, obstacles, face, size):
    """An arrow or circle that lands on its target (a hand, the face's edge, or a spot)."""
    t = it["start"]
    target = None
    which = it["target"]
    if which in ("left_hand", "right_hand"):
        target = hand_target(ctx, which, t)
    if which == "face" and face is not None:
        # point at the face from outside: the tip stops at the face's edge
        target = ((face[0] + face[2]) / 2, (face[1] + face[3]) / 2)
    if target is None:
        zone = it["zone"] if it["zone"] not in (None, "auto") else None
        px, py = ZONE_ANCHOR.get(zone, (0.5, 0.58))
        target = (px * FRAME_W, py * FRAME_H)
    tx, ty = target
    for factor in (1.0, 0.85, 0.7):
        s = clamp(size * factor, MIN_SIZE, 2.0)
        for gap in (60, 90, 130, 180):
            for angle in (25, 155, -25, 205, 90, -90, 0, 180, 60, 120, -60, -120):
                if meta["id"] == "circle-ring":
                    if which == "face":
                        return None
                    cx, cy = tx, ty
                    angle = 0
                else:
                    a = math.radians(angle)
                    tip = meta["tip"]["dist"] * s
                    # the tip sits `gap` px short of the target; the box centre is behind it
                    cx = tx - (gap + tip) * math.cos(a)
                    cy = ty - (gap + tip) * math.sin(a)
                box = est_box(meta, "", s, cx / FRAME_W, cy / FRAME_H, angle)
                if not zones.inside(box, (0, 0, FRAME_W, FRAME_H)) or not zones.inside(box, (20, 120, 1060, 1500)):
                    continue
                if any(zones.intersects(box, r) for _k, r in obstacles):
                    continue
                return (cx / FRAME_W, cy / FRAME_H, s, angle, box)
            if meta["id"] == "circle-ring":
                break
    return None


def contrast_ok(color, other, ratio=4.5):
    from .graphics_check import contrast
    return contrast(color, other) >= ratio


def style_items(ctx, items):
    """Step 8: colours with enough contrast, fonts, intensity, emphasis transitions."""
    from .graphics_check import contrast, readable_on
    palette = ctx.style["palette"]
    last_attach, last_kind = -99.0, None
    for idx, it in enumerate(items):
        meta = meta_of(it["template"])
        defaults = {"color": "#ffffff", "accent": "#ffd23f", "bg": "#111827", **meta["defaults"]}
        accent = it["accent"] if it.get("accent") and HEX.match(it["accent"]) else palette[idx % len(palette)]
        color = it["color"] if it.get("color") and HEX.match(it["color"]) else defaults["color"]
        bg = defaults["bg"]
        if meta["bg"]:
            if contrast(color, bg) < 4.5:
                color = readable_on(bg)
        elif contrast(color, "#000000") < 4.5:
            color = "#ffffff"
        if contrast(accent, "#000000") < 4.5 and not meta["bg"]:
            accent = palette[0] if contrast(palette[0], "#000000") >= 4.5 else "#ffd23f"
        it["p_color"], it["p_accent"] = color, accent
        it["p_font"] = it["font"] if it.get("font") in graphics.font_keys() else ""
        it["p_intensity"] = round(clamp(float(it["intensity"]) if it.get("intensity") is not None
                                        else ctx.style["intensity"], 0.0, 1.0), 2)
        kinds = ctx.style["attach"]
        want = it["emphasis"] if it["emphasis"] in kinds else None
        if want is None and kinds and it["importance"] >= ctx.style["attach_importance"]:
            want = kinds[idx % len(kinds)]
        if (want and it["start"] - last_attach >= ctx.style["attach_gap"]
                and want != last_kind and meta["category"] not in COMPANION):
            it["attach"] = want
            last_attach, last_kind = it["start"], want
        else:
            it["attach"] = None
    return items


def refine(ctx, raw, fixed_used=None):
    """Run every rule on raw items. Returns the final items (each with x, y, times, params)."""
    items = [raw_item(r) for r in raw]
    items = sync_items(ctx, items)
    items = read_items(ctx, items)
    used = Counter(fixed_used or {})
    items = pick_templates(ctx, items, used)
    items = select_items(ctx, items)
    # Timing and placement can drop items, so variety is checked on what is left, and a swapped
    # template (another length, another size) is timed and placed again.
    for _round in range(4):
        timed = place_items(ctx, time_items(ctx, items))
        if not vary_items(ctx, timed):
            break
        items = timed
    items = timed
    items = drop_repeats(ctx, items)
    items = style_items(ctx, items)
    return sorted(items, key=lambda x: x["start"])


def drop_repeats(ctx, items):
    """The last guarantee: the same template never comes twice in a row."""
    out = []
    for it in sorted(items, key=lambda x: x["start"]):
        if out and out[-1]["template"] == it["template"]:
            ctx.note(f"Left out a graphic at {mmss(it['start'])}: it would repeat the previous template.")
            continue
        out.append(it)
    return out


# ---------------------------------------------------------------- items -> clips

def params_for(ctx, it):
    meta = meta_of(it["template"])
    fields = set(meta["fields"])
    p = {}
    text = it.get("text") or ""
    if "text" in fields and text:
        p["text"] = shorten(text, meta["maxChars"])
    if "text2" in fields and it.get("text2"):
        p["text2"] = it["text2"][:60]
    if "items" in fields and it.get("list"):
        p["items"] = [x[:40] for x in it["list"]][:5]
    if "number" in fields and it.get("number") is not None:
        p["number"] = it["number"]
    if "prefix" in fields and it.get("prefix"):
        p["prefix"] = it["prefix"][:8]
    if "suffix" in fields and it.get("suffix"):
        p["suffix"] = it["suffix"][:12]
    if "image" in fields and it.get("image"):
        p["image"] = it["image"]
    if "emoji" in fields:
        p["emoji"] = it.get("emoji") or (EMOJI_FOR_MOOD.get(it.get("mood") or "hype") or ["✨"])[0]
    if "icon" in fields:
        icon = it.get("icon")
        p["icon"] = icon if icon in graphics.icon_names() else ICON_FOR_MOOD.get(it.get("mood"), "star")
    if "accent" in fields:
        p["accent"] = it["p_accent"]
    if "color" in fields and it["p_color"] != {"color": "#ffffff", **meta["defaults"]}["color"]:
        p["color"] = it["p_color"]
    if "font" in fields and it["p_font"]:
        p["font"] = it["p_font"]
    if "intensity" in fields:
        p["intensity"] = it["p_intensity"]
    if "size" in fields:
        p["size"] = it["size_final"]
    if "angle" in fields:
        p["angle"] = it["angle"]
    return p


def clip_from_item(ctx, it, clip_id):
    meta = meta_of(it["template"])
    clip = {"id": clip_id, "type": "graphic", "start": round(it["start"], 4),
            "duration": round(it["end"] - it["start"], 4), "template": it["template"],
            "x": it["x"], "y": it["y"], "params": params_for(ctx, it),
            "label": f"{meta['name']}: {strip_marks(it.get('text') or it.get('spoken', ''))}"[:120],
            "director": {"style": ctx.style_name, "mood": it["mood"], "words": it.get("spoken", ""),
                         "importance": round(it["importance"], 2), "reason": it["reason"],
                         "kind": meta["category"]}}
    if it.get("attach"):
        clip["attach"] = {"kind": it["attach"], "intensity": round(0.45 + 0.5 * it["p_intensity"], 2)}
    return clip


def next_ids(project, prefix):
    used = {c["id"] for t in project["tracks"] for c in t["clips"]} | {t["id"] for t in project["tracks"]}
    n = 1
    while True:
        cid = f"{prefix}{n}"
        if cid not in used:
            yield cid
            used.add(cid)
        n += 1


def lay_out(project, clips):
    """Put graphic clips on Graphics tracks: the first track where a clip overlaps nothing
    (locked and own graphics included), else a new "Graphics N" track."""
    from .project import TIME_TOLERANCE

    def free(track, clip):
        return all(clip["start"] >= c["start"] + c["duration"] - TIME_TOLERANCE
                   or clip["start"] + clip["duration"] <= c["start"] + TIME_TOLERANCE for c in track["clips"])

    for clip in sorted(clips, key=lambda c: c["start"]):
        tracks = [t for t in project["tracks"] if t["kind"] == "graphics"]
        track = next((t for t in tracks if not t.get("locked") and free(t, clip)), None)
        if track is None:
            n = len(tracks)
            tid = "graphics" if not any(t["id"] == "graphics" for t in project["tracks"]) \
                else next(next_ids(project, "graphics-"))
            track = {"id": tid, "kind": "graphics", "name": "Graphics" if n == 0 else f"Graphics {n + 1}",
                     "clips": []}
            index = max((k for k, t in enumerate(project["tracks"]) if t["kind"] in ("effect", "overlay", "graphics")),
                        default=0) + 1
            project["tracks"].insert(index, track)
        track["clips"].append(clip)
        track["clips"].sort(key=lambda c: c["start"])
    return project


def clear_director_clips(project):
    """Remove the graphics the Director made earlier (but keep locked ones and the creator's own)."""
    removed = 0
    for track in project["tracks"]:
        if track["kind"] != "graphics":
            continue
        keep = [c for c in track["clips"] if c["type"] != "graphic" or c.get("locked") or "director" not in c]
        removed += len(track["clips"]) - len(keep)
        track["clips"] = keep
    project["tracks"] = [t for t in project["tracks"] if t["kind"] != "graphics" or t["clips"]]
    return removed


def graphic_clips_of(project):
    return [c for t in project["tracks"] if t["kind"] == "graphics" for c in t["clips"] if c["type"] == "graphic"]


# ---------------------------------------------------------------- the AI plan

def plan_schema():
    cat = graphics.catalog()
    string = {"type": "string"}
    item = {
        "type": "object", "additionalProperties": False, "required": ["template", "words", "start"],
        "properties": {
            "template": {"enum": [t["id"] for t in cat["templates"]]},
            "words": {"type": "string",
                      "description": "The spoken words it belongs to, exactly as in the transcript."},
            "start": {"type": "number", "minimum": 0},
            "end": {"type": "number", "minimum": 0},
            "text": {"type": "string", "maxLength": 90},
            "text2": {"type": "string", "maxLength": 60},
            "list": {"type": "array", "items": string, "maxItems": 5},
            "number": {"type": "number"}, "prefix": {"type": "string", "maxLength": 8},
            "suffix": {"type": "string", "maxLength": 12}, "emoji": {"type": "string", "maxLength": 16},
            "icon": {"enum": cat["icons"]},
            "zone": {"enum": ["auto", "upper", "center", "lower", "left", "right"]},
            "target": {"enum": ["none", "face", "left_hand", "right_hand"]},
            "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "accent": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            "font": {"enum": list(cat["fonts"])},
            "size": {"type": "number", "minimum": 0.5, "maximum": 1.8},
            "intensity": {"type": "number", "minimum": 0, "maximum": 1},
            "emphasis": {"enum": ["none", "flash", "whip", "punch"]},
            "mood": {"enum": cat["moods"]},
            "importance": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string", "maxLength": 160},
        }}
    from .grades import GRADES
    return {"type": "object", "additionalProperties": False, "required": ["items"],
            "properties": {
                "summary": string,
                "items": {"type": "array", "maxItems": 60, "items": item},
                "wipe": {"type": "object", "additionalProperties": False, "required": ["start", "grade"],
                         "properties": {"start": {"type": "number", "minimum": 0},
                                        "end": {"type": "number", "minimum": 0},
                                        "grade": {"enum": [g for g in GRADES if g != "none"]},
                                        "direction": {"enum": ["right", "left", "down", "up"]}}},
                "notes": {"type": "array", "items": string, "maxItems": 10}}}


def validate_plan(plan, ctx):
    """Problems with a plan (empty = fine): schema, templates, words that are not in the transcript."""
    import jsonschema
    problems = []
    validator = jsonschema.Draft202012Validator(plan_schema())
    for error in sorted(validator.iter_errors(plan), key=lambda e: list(e.absolute_path)):
        problems.append(f"{error.json_path.replace('$', 'plan', 1)}: {error.message}")
    if problems:
        return problems[:20]
    for k, it in enumerate(plan["items"]):
        where = f"items[{k}] ({it['template']} at {it['start']:.2f}s)"
        meta = meta_of(it["template"])
        if it["start"] > ctx.duration + 0.05:
            problems.append(f"{where}: starts after the video ends ({ctx.duration:.2f}s)")
        if "end" in it and it["end"] <= it["start"]:
            problems.append(f"{where}: 'end' must be after 'start'")
        if locate(ctx.words, it["words"], it["start"], window=3.0) is None:
            problems.append(f"{where}: the words '{it['words']}' are not spoken near {it['start']:.2f}s "
                            "(copy them from the transcript)")
        have = available_inputs(it)
        if not required_inputs(meta) - {"emoji"} <= have | {"text2"}:
            need = ", ".join(sorted(required_inputs(meta) - have))
            problems.append(f"{where}: {meta['id']} needs: {need}")
        if len(strip_marks(it.get("text", ""))) > meta["maxChars"] * 1.5:
            problems.append(f"{where}: the text is too long for {meta['id']} (max {meta['maxChars']} letters)")
    return problems[:20]


def catalog_text(ctx):
    lines = []
    for m in graphics.templates():
        if m["id"] in ctx.style["deny"] or ctx.style["categories"].get(m["category"], 0.5) <= 0 \
                or not style_allows(ctx, m):
            continue
        need = ",".join(sorted(required_inputs(m) | ({"emoji"} if m["category"] == "emoji" else set())))
        lines.append(f"{m['id']} | {m['category']} | moods: {'/'.join(m['moods'])} | needs: {need} "
                     f"| max {m['maxChars']} letters | {m['name']}")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the motion-graphics director for short vertical videos (TikTok / \
Reels) of a creator talking to the camera, in Filipino, English or Taglish. A program draws the \
graphics and places them; you choose WHICH graphic goes with WHICH spoken words.

For every phrase that matters, you can add one graphic: a pop-up word or phrase (heavy, thin, \
glow, bounce, slide, underline, highlight box, stamp, typewriter, glitch...), a floating card \
(prompt card, notifications, polaroid, icon, clock), a pill (lower third, "Comment EDIT", \
follow / following), a counter, bar, price tag, checklist or star rating, an arrow or circle that \
points at something, an emoji, a warning banner, a sticker.

Rules you must follow:
- Use only the templates in TEMPLATES, with the inputs they need. `words` = the exact spoken words \
(copy them from the transcript); `start` = the time (seconds) the first of those words is said.
- Only phrases that matter: numbers, prices, key terms, claims, questions, calls to action, strong \
feelings. Not filler. Fewer, better graphics beat many.
- Match the tone: money talk -> price / counter styles; urgency -> stamp, clock, warning; \
funny -> emoji, sticker, bounce; calm -> thin, slide; serious -> clean text, quote; tech -> \
prompt card, glow, typewriter; emotion -> hearts, handwritten, polaroid. Set `mood` to one of the \
allowed moods and `importance` (0 to 1).
- Never use the same template twice in a row; use many different ones.
- text: the words to show (short: 1 to 5 words for pop-up words; write *word* around the word to \
emphasise). Keep the creator's language (Taglish stays Taglish). Counter: put the digits in \
`number` and the currency in `prefix` (e.g. "₱") or "%" in `suffix`.
- emphasis: flash / whip / punch on the biggest moments only, otherwise none.
- Arrows and circles: `target` = what they point at (face, left_hand, right_hand) when the \
creator points or says "look at this"; the program keeps them off the face itself.
- You do not choose positions or sizes: the program keeps graphics off the speaker's face and off \
the captions. `zone` only says roughly where (upper / center / lower / left / right / auto).
- wipe: a before/after wipe (one side graded) only if the creator asks for a before/after look.
- If something asked for cannot be done with these templates, add a short note to notes.
- Never invent words that were not said. Output the JSON object only."""


def build_prompt(ctx, previous=None, only=None):
    from .ai_edit import transcript_lines
    from .words import Word
    words = [Word(text=w["text"], start=w["start"], end=w["end"]) for w in ctx.words]
    s = ctx.style
    face = ctx.face
    where = ("The speaker's face is followed by tracking." if face.known else
             "The speaker's face position is not tracked: assume the upper middle of the frame.")
    parts = [f"VIDEO LENGTH: {ctx.duration:.2f} seconds",
             f"STYLE: {s['label']} - {s['about']}",
             f"LIMITS: at most {ctx.max_per_10s} graphics in any 10 seconds, at least "
             f"{s['min_gap']:g} seconds between the main ones; the style uses emphasis: "
             f"{', '.join(s['attach']) or 'none (use emphasis none)'}.",
             "MOODS: " + ", ".join(graphics.catalog()["moods"]),
             where,
             "TEMPLATES (id | kind | moods | needs | limit | name):\n" + catalog_text(ctx),
             "INSTRUCTION FROM THE CREATOR:\n" + (ctx.instruction.strip() or "(none: add fitting graphics)")]
    if only:
        parts.append("ONLY MAKE ONE ITEM, for these words:\n" + only)
    if previous:
        parts.append("YOUR PREVIOUS ANSWER HAD THESE PROBLEMS:\n" + previous)
    parts.append("TRANSCRIPT (start time in seconds, then the word; as it appears in the finished "
                 "video):\n" + transcript_lines(words))
    return "\n\n".join(parts)


class PlanResult:
    def __init__(self, items, notes=(), summary="", fallback=False, reason="", attempts=(), usage=None,
                 model=None, cached=False, cost=None, wipe=None):
        self.items, self.notes, self.summary = items, list(notes), summary
        self.fallback, self.reason, self.attempts = fallback, reason, list(attempts)
        self.usage = usage or {"input_tokens": 0, "output_tokens": 0}
        self.model, self.cached, self.cost, self.wipe = model, cached, cost, wipe


def request_plan(ctx, provider, model, cache=None, cancel=None, only=None, check_fallback=True):
    """Ask the model for the plan; check it; retry once with the problems; else the rule-based plan."""
    ai = ctx.cfg["ai"]
    key = None
    if cache is not None:
        from .cache import key_for
        key = key_for({"v": PROMPT_VERSION, "provider": provider, "model": model, "style": ctx.style_name,
                       "instruction": ctx.instruction.strip(), "words": [(w["text"], w["start"]) for w in ctx.words],
                       "max": ctx.max_per_10s, "only": only, "face": ctx.face.known})
        hit = cache.get("director", key)
        if hit and not validate_plan(hit["plan"], ctx):
            return PlanResult(hit["plan"]["items"], hit["plan"].get("notes", []), hit["plan"].get("summary", ""),
                              model=hit.get("model"), cached=True, cost=0.0, wipe=hit["plan"].get("wipe"))
    schema = plan_schema()
    attempts, usage, used_model = [], {"input_tokens": 0, "output_tokens": 0}, model
    problems_text = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled while planning the graphics.")
        try:
            text, used, used_model = ask_json(provider, model, SYSTEM_PROMPT, build_prompt(ctx, problems_text, only),
                                              schema, max_tokens=int(ai.get("max_tokens", 8000)),
                                              effort=ai.get("anthropic_effort", "medium"))
        except LLMError as exc:
            reason = f"The AI could not be asked for graphics ({exc}) - simple rule-based graphics instead."
            return fallback_result(ctx, reason, attempts, usage, used_model)
        usage = {k: usage[k] + used[k] for k in usage}
        try:
            plan = json.loads(text) if text.strip() else None
            problems = ["the answer was empty or cut off"] if plan is None else []
        except ValueError as exc:
            plan, problems = None, [f"the answer is not valid JSON ({exc})"]
        if not problems:
            problems = validate_plan(plan, ctx)
        if not problems:
            if cache is not None:
                cache.put("director", key, {"plan": plan, "model": used_model})
            from .costs import plan_cost
            cost = plan_cost(ai.get("prices") or {}, used_model, usage["input_tokens"], usage["output_tokens"])
            return PlanResult(plan["items"], plan.get("notes", []), plan.get("summary", ""), attempts=attempts,
                              usage=usage, model=used_model, cost=cost, wipe=plan.get("wipe"))
        attempts.append({"attempt": attempt, "problems": problems})
        problems_text = "\n".join(f"- {p}" for p in problems) + "\nReturn a corrected, complete JSON plan."
    first = attempts[0]["problems"][0] if attempts else "unknown problem"
    reason = (f"The AI graphics plan failed the checks twice (first problem: {first}) - simple "
              "rule-based graphics instead.")
    return fallback_result(ctx, reason, attempts, usage, used_model)


def fallback_result(ctx, reason, attempts=(), usage=None, model=None):
    from .costs import plan_cost
    ai = ctx.cfg["ai"]
    usage = usage or {"input_tokens": 0, "output_tokens": 0}
    cost = plan_cost(ai.get("prices") or {}, model, usage["input_tokens"], usage["output_tokens"]) if model else None
    return PlanResult(fallback_items(ctx), [], "", fallback=True, reason=reason, attempts=attempts, usage=usage,
                      model=model, cost=cost, wipe=fallback_wipe(ctx))


# ---------------------------------------------------------------- the safe preset (no AI)

NUMBER = re.compile(r"^[₱$€]?\d[\d,.]*%?$")
BEFORE_AFTER = re.compile(r"before\s*(/|and|at)\s*after|wipe|bago\s*(at|/)\s*pagkatapos", re.I)


def fallback_wipe(ctx):
    if ctx.style["wipe"] and BEFORE_AFTER.search(ctx.instruction) and ctx.duration > 2:
        start = round(max(0.5, ctx.duration * 0.4), 2)
        return {"start": start, "end": round(min(ctx.duration, start + 3.0), 2), "grade": "orange_teal"}
    return None


def shown(word):
    """A word as shown in a graphic: no punctuation at the edges."""
    return strip_marks(word["text"]).strip(".,!?;:\"'()")


def fallback_items(ctx):
    """Rule-based graphics: numbers, calls to action, the opening hook, highlighted words, a few
    emoji. Used when the AI cannot be asked or its plan failed the checks (twice)."""
    words = ctx.words
    items = []
    if not words:
        return items

    def add(i0, i1, **kw):
        span = words[i0:i1 + 1]
        phrase = " ".join(strip_marks(w["text"]) for w in span)
        items.append({"words": phrase, "start": span[0]["start"], "mood": word_mood([w["text"] for w in span]), **kw})

    for i, w in enumerate(words):
        tok = strip_marks(w["text"]).strip(".,!?")
        low = norm(tok)
        if NUMBER.match(tok.replace(" ", "")):
            digits = re.sub(r"[^\d.]", "", tok.replace(",", ""))
            if not digits or digits == ".":
                continue
            number = float(digits)
            number = int(number) if number == int(number) else number
            near = " ".join(norm(x["text"]) for x in words[max(0, i - 2):i + 3])
            prefix = "₱" if (tok.startswith("₱") or any(k in near for k in ("piso", "pesos", "peso"))) else \
                     "$" if tok.startswith("$") else ""
            suffix = "%" if tok.endswith("%") else ""
            label_words = [shown(x) for x in words[i + 1:i + 3]
                           if important(x["text"]) and norm(x["text"]) not in ("pesos", "peso", "piso")][:1]
            add(i, i, template="counter-number", number=number, prefix=prefix, suffix=suffix,
                text=" ".join(label_words)[:30], importance=0.92, mood="money" if prefix else "hype", zone="center")
        elif low in CTA_WORDS and CTA_WORDS[low] == "follow-pill":
            add(i, i, template="follow-pill", text="@yourhandle", text2="Follow", list=["Following"],
                importance=0.86, mood="playful", zone="lower")
        elif low in CTA_WORDS:
            ahead = words[i + 1:i + 7]
            key = next((shown(x) for x in ahead if len(shown(x)) > 1 and shown(x).isupper()), None) \
                or next((shown(x).upper() for x in ahead[:3] if important(x["text"])), "NOW")
            add(i, i, template="comment-pill", text=key, text2="Comment", importance=0.85, mood="playful", zone="lower")
    # the opening hook: the strongest word of the first sentence
    sents = sentences(words)
    if sents:
        first = sents[0]
        keys = [i for i in first if important(words[i]["text"])]
        if keys:
            def strength(k):
                tok = norm(words[k]["text"])
                moody = any(tok in vocab for vocab in MOOD_WORDS.values())
                return (words[k]["hl"], moody, len(tok))
            i = max(keys, key=strength)
            lo, hi = max(first[0], i - 1), min(first[-1], i + 2)
            marked = " ".join(f"*{shown(words[k])}*" if k == i else shown(words[k]) for k in range(lo, hi + 1))
            add(lo, hi, template="pop-heavy", text=marked, importance=0.82, mood=None, zone="center")
    # words the captions highlight
    for i, w in enumerate(words):
        if w["hl"] and important(w["text"]):
            lo, hi = max(0, i - 1), min(len(words) - 1, i + 1)
            marked = " ".join(f"*{shown(words[k])}*" if k == i else shown(words[k])
                              for k in range(lo, hi + 1) if important(words[k]["text"]) or k == i)
            add(i, i, template="highlight-box", text=marked, importance=0.6, zone="auto")
    # an emoji for the clearest moods, and a pointer when the creator points ("look", "dito")
    if ctx.style["emoji"]:
        for si in sents:
            mood = word_mood([words[k]["text"] for k in si])
            if mood in ("money", "funny", "hype", "emotion", "warning"):
                k = next((k for k in si if norm(words[k]["text"]) in MOOD_WORDS[mood]), si[0])
                add(k, k, template="emoji-pop", emoji=EMOJI_FOR_MOOD[mood][0], importance=0.45, mood=mood)
    for i, w in enumerate(words):
        pointing = norm(w["text"]) in ("look", "tingnan", "dito", "here", "ito", "this")
        if pointing and ctx.style["categories"].get("pointer", 0) > 0.5:
            add(i, i, template="arrow-point", text="", target="none", importance=0.5, mood="playful", zone="lower")
            break
    return items


# ---------------------------------------------------------------- the whole thing

def fixed_graphics(project):
    """Graphics that stay put while the Director works: locked ones and the creator's own."""
    return [c for c in graphic_clips_of(project) if c.get("locked") or "director" not in c]


def face_for(project, video, cfg, cache=None, reporter=None, cancel=None):
    """Find the face (if tracking is set up and the project has no face track yet), so graphics
    keep off it. Returns True when a face track is now in the project."""
    if not (cfg.get("graphics") or {}).get("track_face", True):
        return False
    main = next((t for t in project["tracks"] if t["kind"] == "video"), None)
    ids = [c["media"] for c in (main["clips"] if main else []) if c.get("media")]
    if not ids:
        return False
    media_id = ids[0]
    if "face" in ((project.get("tracking") or {}).get(media_id, {}).get("points") or {}):
        return True
    if video is None:
        return False
    from . import tracking as trk
    st = trk.status(cfg)
    if not st["face"]:
        return False
    key = None
    track = None
    if cache is not None:
        from .cache import key_for
        key = key_for({"k": trk.track_cache_key(cache, video, cfg), "names": ["face"], "all": True})
        data = cache.get("tracks", key)
        if data:
            track = trk.Track.from_json(data)
    try:
        if track is None:
            if reporter:
                reporter.stage("tracking", "Finding your face so graphics keep off it")
            track = trk.detect_video(video, cfg, ranges=None, names=["face"], reporter=reporter, cancel=cancel)
            if cache is not None:
                cache.put("tracks", key, track.to_json())
    except Cancelled:
        raise
    except EditorError:
        return False
    project.setdefault("tracking", {})[media_id] = track.to_json(["face"])
    return True


def generate(project, cfg, instruction="", style=None, provider=None, model=None, cache=None,
             reporter=None, cancel=None, video=None, use_ai=True, files=()):
    """Add graphics to a copy of the project. Returns a dict:
       project, count, style, notes, fallback, reason, cost, usage, plan (the items), wipe.
    Returns None when the style resolves to "off". `files`: the creator's uploaded pictures and
    clips (the editorial style shows them in its scenes)."""
    name = resolve_style(cfg, instruction, style)
    if name is None:
        return None
    if STYLES[name].get("planner") == "editorial":
        # this look is planned scene by scene (autoedit/editorial.py), not as pop-ups
        from . import editorial
        return editorial.generate(project, cfg, instruction, provider, model, cache, reporter, cancel, video,
                                  use_ai, files=files)
    project = copy.deepcopy(project)
    removed = clear_director_clips(project)
    for track in project["tracks"]:
        # the Director's own earlier wipe ("dw" ids) is redone too, unless it was locked
        track["clips"] = [c for c in track["clips"] if not (c.get("type") == "wipe" and not c.get("locked")
                                                            and str(c.get("id", "")).startswith("dw"))]
    if reporter:
        reporter.stage("graphics", "Planning the motion graphics")
    face_for(project, video, cfg, cache, reporter, cancel)
    ctx = Ctx(project, cfg, name, instruction, fixed=fixed_graphics(project))
    if not ctx.words:
        return {"project": project, "count": 0, "style": name, "notes": ["No spoken words, so no graphics."],
                "fallback": False, "reason": "", "cost": None, "usage": {}, "plan": [], "wipe": None,
                "removed": removed}
    if use_ai and provider:
        result = request_plan(ctx, provider, model, cache, cancel)
    else:                       # no AI wanted: the rule-based plan is the plan, not a failure
        result = fallback_result(ctx, "")
        result.fallback = False
    final = refine(ctx, result.items, fixed_used=Counter(c["template"] for c in ctx.fixed))
    ids = next_ids(project, "g")
    clips = [clip_from_item(ctx, it, next(ids)) for it in final]
    lay_out(project, clips)
    wipe = add_wipe(ctx, project, result.wipe)
    if not ctx.face.known:
        ctx.note("The face was not tracked, so graphics keep off the upper-middle of the frame, where a "
                 "speaker usually is. (Set up tracking, docs/tracking.md, to place them around the real face.)")
    project.setdefault("meta", {})["graphics"] = {"style": name, "count": len(clips), "fallback": result.fallback}
    return {"project": project, "count": len(clips), "style": name, "notes": result.notes + ctx.notes,
            "fallback": result.fallback, "reason": result.reason, "cost": result.cost, "usage": result.usage,
            "model": result.model, "plan": final, "wipe": wipe, "removed": removed, "summary": result.summary,
            "attempts": result.attempts, "cached": result.cached}


def add_wipe(ctx, project, wipe):
    """A before/after wipe clip (and its BEFORE / AFTER tags) when the plan asks for one."""
    if not wipe or not ctx.style["wipe"]:
        return None
    start = snap(clamp(float(wipe["start"]), 0.0, max(0.0, ctx.duration - 1.0)), ctx.fps)
    end = snap(clamp(float(wipe.get("end") or start + 3.0), start + 1.0, ctx.duration), ctx.fps)
    track = next((t for t in project["tracks"] if t["kind"] == "effect" and t["id"] == "effects"), None)
    if track is None:
        track = {"id": "effects", "kind": "effect", "name": "Effects", "clips": []}
        project["tracks"].insert(2, track)
    for c in track["clips"]:
        if c["type"] == "wipe" and c["start"] < end and c["start"] + c["duration"] > start:
            return None
    clip = {"id": next(next_ids(project, "dw")), "type": "wipe", "start": start, "duration": round(end - start, 4),
            "grade": wipe["grade"], "direction": wipe.get("direction", "right"), "sweep": 0.9, "stop": 0.5,
            "intensity": 1.0, "label": "Before / after"}
    track["clips"].append(clip)
    track["clips"].sort(key=lambda c: c["start"])
    return clip


# ---------------------------------------------------------------- one graphic again

def regenerate_item(project, clip_id, cfg, instruction="", provider=None, model=None, cache=None,
                    cancel=None, template=None):
    """Make a different graphic for the same words as one existing graphic. Other graphics (and
    locked ones) stay as they are. `template`: force this template. Returns
    {"project", "clip", "notes"}. A locked graphic is never changed."""
    project = copy.deepcopy(project)
    track = next((t for t in project["tracks"] if t["kind"] == "graphics"
                  and any(c["id"] == clip_id for c in t["clips"])), None)
    if track is None:
        raise DirectorError(f"There is no graphic '{clip_id}' in this project.")
    old = next(c for c in track["clips"] if c["id"] == clip_id)
    if old.get("locked"):
        raise DirectorError("That graphic is locked. Unlock it first (a locked graphic is never changed).")
    meta = old.get("director") or {}
    if meta.get("scene") is not None and STYLES.get(meta.get("style"), {}).get("planner") == "editorial":
        # an editorial scene's graphic: the scene gets another graphic beat
        from . import editorial
        r = editorial.regenerate_scene(project, meta["scene"], cfg, instruction, cancel=cancel, graphic_only=True)
        clip = next(c for c in graphic_clips_of(r["project"]) if c["id"] in r["clips"])
        return {"project": r["project"], "clip": clip, "notes": r["notes"]}
    style = meta.get("style") or resolve_style(cfg, instruction, None) or DEFAULT_STYLE
    if style not in STYLES:
        style = DEFAULT_STYLE
    others = [c for c in graphic_clips_of(project) if c["id"] != clip_id]
    track["clips"] = [c for c in track["clips"] if c["id"] != clip_id]
    ctx = Ctx(project, cfg, style, instruction, fixed=others)
    spoken = meta.get("words") or " ".join(w["text"] for w in ctx.words
                                          if old["start"] - 0.02 <= w["start"] <= old["start"] + old["duration"])
    if template and not graphics.has_template(template):
        raise DirectorError(f"Unknown graphics template '{template}'.")
    params = old.get("params") or {}
    raw = {"template": template, "words": spoken, "start": old["start"], "end": old["start"] + old["duration"],
           "text": params.get("text") or "", "text2": params.get("text2", ""), "list": params.get("items") or [],
           "number": params.get("number"), "prefix": params.get("prefix", ""), "suffix": params.get("suffix", ""),
           "emoji": params.get("emoji", ""), "mood": meta.get("mood"), "importance": meta.get("importance", 0.7),
           "reason": "another look"}
    if provider and not template:
        try:
            ctx2 = Ctx(project, cfg, style, instruction, fixed=others)
            only = f"words: {spoken} (at {old['start']:.2f}s); choose a template other than {old['template']}"
            res = request_plan(ctx2, provider, model, None, cancel, only=only)
            pick = next((i for i in res.items if i.get("template") != old["template"]
                         and locate(ctx.words, i["words"], old["start"]) is not None), None)
            if pick and not res.fallback:
                raw = {**raw, **pick, "start": old["start"]}
        except LLMError:
            pass
    ctx.max_per_10s = 99                         # the density was already decided; this is a swap
    exclude = {old["template"]}
    if not template:       # keep the "never the same template twice in a row" rule
        ordered = sorted(others, key=lambda c: c["start"])
        before = [c for c in ordered if c["start"] < old["start"]]
        after = [c for c in ordered if c["start"] > old["start"]]
        exclude |= {before[-1]["template"]} if before else set()
        exclude |= {after[0]["template"]} if after else set()
    final = []
    for attempt in range(6):
        if not raw.get("template") or raw["template"] in exclude and not template:
            probe = raw_item(raw)
            probe["i0"] = probe["i1"] = 0
            probe["start"] = old["start"]
            group = group_of(meta_of(old["template"]))
            alt = choose_template(ctx, {**probe, "mood": raw.get("mood")}, group, Counter(), exclude=exclude)
            if alt is None and group != "text":
                # nothing else of this kind: show the same words (or number) as pop-up text
                if not raw.get("text"):
                    num = raw.get("number")
                    raw["text"] = (f"{raw.get('prefix', '')}{num:,}{raw.get('suffix', '')}" if num is not None
                                   else spoken)
                probe = {**raw_item(raw), "start": old["start"], "mood": raw.get("mood")}
                alt = choose_template(ctx, probe, "text", Counter(), exclude=exclude)
            if alt is None:
                break
            raw["template"] = alt
        final = refine_one(ctx, raw)
        if final or template:
            break
        exclude.add(raw["template"])
        raw["template"] = None
    if not final:
        raise DirectorError("No other graphic fits there without covering the face or the captions.")
    clip = clip_from_item(ctx, final[0], clip_id)
    clip["director"]["reason"] = "another look"
    if old.get("attach") and "attach" not in clip:
        clip["attach"] = old["attach"]
    lay_out(project, [clip])
    return {"project": project, "clip": clip, "notes": ctx.notes}


def refine_one(ctx, raw):
    """The rules for one graphic that replaces another (no density or variety limits)."""
    items = [raw_item(raw)]
    items = sync_items(ctx, items)
    items = read_items(ctx, items)
    items = [it for it in items if it.get("template")] if items and items[0].get("template") else \
        pick_templates(ctx, items, Counter())
    items = time_items(ctx, items)
    items = place_items(ctx, items)
    return style_items(ctx, items)


def refine_given(ctx, raw):
    """The rules for graphics a format has already chosen (template and words fixed): sync to
    the words, timing, placement off the face and captions, readable colours. No density or
    variety changes: the format decided those."""
    items = [raw_item(r) for r in raw]
    items = sync_items(ctx, items)
    items = read_items(ctx, items)
    items = [it for it in items if it.get("template")]
    items = time_items(ctx, sorted(items, key=lambda x: x["start"]))
    items = place_items(ctx, items)
    return style_items(ctx, items)
