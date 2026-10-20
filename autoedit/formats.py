"""Video formats: Talking head, Yap, Screenshare, Split screen, Reaction, Voice-over B-roll,
Listicle, Ranking, Before/after, Clone yourself, Green screen, Comparison, Explainer.

A format is DATA (autoedit/formats/<id>.json, checked against format.schema.json):

    inputs     which files it needs, by role (main video, screen recording, the video you react
               to, your other takes, a background, B-roll, items...)
    edit       pacing defaults (silence cut, zooms, or no cuts at all)
    captions   caption defaults (zone, words per line, style)
    graphics   the Director style it suggests
    instruction  a hint added to the AI planner's instruction
    steps      a list of generic operations ("op") applied to the finished Project:
               layout, broll_files, reactions, items, wipe, versus, callouts, cutouts,
               background, voiceover_broll

Adding a format = adding a JSON file that combines these operations; the renderer does not
change. Every operation produces ordinary Project clips (layouts, overlays with masks, graphics,
wipes, sound effects), so the result stays editable on the timeline.
"""

import copy
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from .errors import EditorError

FORMATS_DIR = Path(__file__).with_name("formats")
SCHEMA_FILE = FORMATS_DIR / "format.schema.json"
DEFAULT_FORMAT = "talking_head"
OPS = ("layout", "broll_files", "reactions", "items", "wipe", "versus", "callouts", "cutouts",
       "background", "voiceover_broll")


class FormatError(EditorError):
    pass


# ---------------------------------------------------------------- the specs

@lru_cache(maxsize=None)
def load_schema():
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def spec_problems(spec):
    import jsonschema
    v = jsonschema.Draft202012Validator(load_schema())
    problems = [f"{e.json_path}: {e.message}" for e in v.iter_errors(spec)]
    roles = {i["role"] for i in spec.get("inputs", [])}
    for k, step in enumerate(spec.get("steps", [])):
        for key in ("with", "role", "broll", "audio", "screenshots"):
            if key in step and step[key] not in roles:
                problems.append(f"steps[{k}]: '{key}' names the input role '{step[key]}', which "
                                f"this format does not have")
    return problems


@lru_cache(maxsize=None)
def all_formats():
    """{id: spec} of every format file (each checked)."""
    out = {}
    for path in sorted(FORMATS_DIR.glob("*.json")):
        if path.name == SCHEMA_FILE.name:
            continue
        spec = json.loads(path.read_text(encoding="utf-8"))
        problems = spec_problems(spec)
        if problems:
            raise FormatError(f"The format file {path.name} has problems:\n  - " + "\n  - ".join(problems))
        if spec["id"] != path.stem:
            raise FormatError(f"The format file {path.name} must have the id '{path.stem}'.")
        out[spec["id"]] = spec
    return out


def get(format_id):
    spec = all_formats().get(format_id)
    if spec is None:
        raise FormatError(f"Unknown format '{format_id}'. Choose one of: {', '.join(all_formats())}")
    return spec


def summary():
    """What the app shows: every format with its inputs."""
    return [{"id": s["id"], "name": s["name"], "tl": s["tl"], "about": s["about"], "about_tl": s["about_tl"],
             "inputs": s["inputs"]} for s in all_formats().values()]


# ---------------------------------------------------------------- choosing a format

def missing_inputs(spec, inputs):
    """The required input roles that were not given."""
    return [i["role"] for i in spec["inputs"] if i["required"] and not inputs.get(i["role"])]


def keyword_scores(instruction):
    text = " " + re.sub(r"\s+", " ", str(instruction or "").lower()) + " "
    scores = {}
    for fid, spec in all_formats().items():
        hits = [k for k in spec["keywords"] if re.search(r"(?<![\w-])" + re.escape(k.lower()) + r"(?![\w-])", text)]
        if hits:
            scores[fid] = max(len(k) for k in hits) + 10 * len(hits)
    return scores


def choose(instruction, inputs, forced=None, cfg=None, provider=None, model=None):
    """(format id, reason). `forced` wins (and must have its files). Else: a format named by
    the instruction whose files were given, else one whose extra files were given, else the AI
    (when asked), else Talking head."""
    if forced and forced != "auto":
        spec = get(forced)
        missing = missing_inputs(spec, inputs)
        if missing:
            raise FormatError(f"The {spec['name']} format needs: "
                              + ", ".join(next(i["label"] for i in spec["inputs"] if i["role"] == r) for r in missing))
        return forced, "you chose it"
    usable = {fid: s for fid, s in all_formats().items() if not missing_inputs(s, inputs)}
    scores = {fid: sc for fid, sc in keyword_scores(instruction).items() if fid in usable}
    if scores:
        best = max(scores, key=lambda k: (scores[k], k))
        return best, "your instructions ask for it"
    # extra files say what was meant (a screen recording, your other takes, a background...)
    extra = [r for r, v in inputs.items() if v and r not in ("main",)]
    for fid, spec in usable.items():
        roles = {i["role"] for i in spec["inputs"] if i["required"]} - {"main"}
        if roles and roles <= set(extra):
            return fid, "the files you gave"
    if provider and len(usable) > 1:
        picked = ask_format(instruction, usable, cfg, provider, model)
        if picked:
            return picked
    if "main" not in inputs or not inputs.get("main"):
        if "voiceover_broll" in usable:
            return "voiceover_broll", "there is no talking video, only a voice-over"
        raise FormatError("Give a talking video (or a voice-over with B-roll).")
    return DEFAULT_FORMAT, "the usual edit"


def ask_format(instruction, usable, cfg, provider, model):
    """Ask the AI which format fits (schema: one of the usable ids). One retry; None on failure."""
    from .llm import LLMError, ask_json
    schema = {"type": "object", "additionalProperties": False, "required": ["format", "reason"],
              "properties": {"format": {"enum": sorted(usable)}, "reason": {"type": "string"}}}
    lines = "\n".join(f"{fid}: {s['about']}" for fid, s in sorted(usable.items()))
    prompt = (f"FORMATS (only these are possible with the files given):\n{lines}\n\n"
              f"INSTRUCTION FROM THE CREATOR:\n{instruction.strip() or '(none)'}\n\n"
              "Pick the format that fits best. Output the JSON object only.")
    request = prompt
    for _attempt in range(2):
        try:
            text, _usage, _m = ask_json(provider, model, "You choose the video format for a short vertical "
                                        "video.", request, schema, max_tokens=400, cfg=cfg, step="format choice")
            data = json.loads(text)
            if data.get("format") in usable:
                return data["format"], f"the AI picked it: {str(data.get('reason', ''))[:120]}"
            problem = f"'{data.get('format')}' is not one of the formats listed"
        except (LLMError, ValueError) as exc:
            problem = str(exc)
            if isinstance(exc, LLMError):
                return None
        request = prompt + f"\n\nYOUR PREVIOUS ANSWER HAD THIS PROBLEM: {problem}"
    return None


# ---------------------------------------------------------------- settings before the edit

def cfg_for(spec, cfg):
    """A copy of the settings with the format's edit and caption defaults."""
    cfg = copy.deepcopy(cfg)
    edit = spec.get("edit") or {}
    if edit.get("preset") and edit["preset"] in cfg["presets"]:
        from .config import apply_preset
        cfg["preset"] = edit["preset"]
        cfg = apply_preset(cfg)
    pacing = cfg["pacing"]
    if edit.get("cuts") is False:          # clone: every take must stay in sync
        pacing["silence_threshold"] = 30.0
        pacing["remove_fillers"] = False
        pacing["zoom"] = False
    if "silence_threshold" in edit:
        pacing["silence_threshold"] = float(edit["silence_threshold"])
    if "zoom" in edit:
        pacing["zoom"] = bool(edit["zoom"])
    caps = spec.get("captions") or {}
    if caps.get("style"):
        cfg["style"] = caps["style"]
    return cfg


def caption_overrides(spec):
    caps = spec.get("captions") or {}
    out = {}
    if caps.get("zone"):
        out["zone"] = caps["zone"]
    if caps.get("words_per_line"):
        out["words_per_line"] = int(caps["words_per_line"])
    return out


def instruction_for(spec, instruction):
    hint = spec.get("instruction") or ""
    return (instruction.rstrip() + ("\n\n" + hint if hint else "")) if hint else instruction


# ---------------------------------------------------------------- applying the steps

class Ctx:
    def __init__(self, project, spec, inputs, cfg, base_dir, reporter=None, cancel=None, instruction=""):
        self.project, self.spec, self.inputs, self.cfg = project, spec, inputs, cfg
        self.base_dir = Path(base_dir)
        self.reporter, self.cancel, self.instruction = reporter, cancel, instruction or ""
        self.fps = project["settings"]["fps"]
        self.notes = []
        self.graphics = []        # raw Director items to place at the end (all together)

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def files(self, role):
        return [str(x) for x in (self.inputs.get(role) or [])]

    def media_id(self, path):
        """The media id of a file (added to the project if new)."""
        from .project import media_from_file
        path = str(Path(path).resolve())
        for m in self.project["media"]:
            if str(Path(m["path"]).resolve()) == path:
                return m["id"]
        n = 1
        ids = {m["id"] for m in self.project["media"]}
        while f"f{n}" in ids:
            n += 1
        self.project["media"].append(media_from_file(path, f"f{n}"))
        return f"f{n}"

    def media(self, media_id):
        return next(m for m in self.project["media"] if m["id"] == media_id)

    def main_track(self):
        return next(t for t in self.project["tracks"] if t["kind"] == "video")

    def duration(self):
        clips = self.main_track()["clips"]
        return max((c["start"] + c["duration"] for c in clips), default=0.0)

    def words(self):
        from .director import timeline_words
        return timeline_words(self.project)

    def new_id(self, prefix):
        used = {c["id"] for t in self.project["tracks"] for c in t["clips"]} | \
               {t["id"] for t in self.project["tracks"]}
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        return f"{prefix}{n}"

    def track(self, track_id, kind, name, role=None, after_kind=None):
        t = next((t for t in self.project["tracks"] if t["id"] == track_id), None)
        if t is None:
            t = {"id": track_id, "kind": kind, "name": name, "clips": []}
            if role:
                t["role"] = role
            kinds = [i for i, x in enumerate(self.project["tracks"]) if x["kind"] == (after_kind or kind)]
            at = (kinds[-1] + 1) if kinds else len(self.project["tracks"])
            self.project["tracks"].insert(at, t)
        return t


def apply(project, format_id, inputs, cfg, base_dir=".", reporter=None, cancel=None, instruction=""):
    """Apply a format's steps to a built project. Returns (project, notes)."""
    spec = get(format_id)
    project = copy.deepcopy(project)
    ctx = Ctx(project, spec, inputs, cfg, base_dir, reporter, cancel, instruction)
    for step in spec["steps"]:
        STEP_FUNCS[step["op"]](ctx, step)
    if ctx.graphics:
        place_graphics(ctx)
    project.setdefault("meta", {})["format"] = format_id
    return ctx.project, ctx.notes


def place_graphics(ctx):
    """Place the format's graphics with the Director's rules (on time, off the face and captions,
    readable, never the same template twice in a row)."""
    from . import director
    style = (ctx.spec.get("graphics") or {}).get("style") or "minimal"
    style = style if style in director.STYLES else "minimal"
    dctx = director.Ctx(ctx.project, ctx.cfg, style, ctx.instruction,
                        fixed=director.fixed_graphics(ctx.project))
    dctx.max_per_10s = 99                  # the format decided how many
    dctx.style = dict(dctx.style, min_gap=0.3, deny=[], categories={k: 1.0 for k in director.GROUPS})
    final = director.refine_given(dctx, ctx.graphics)
    ids = director.next_ids(ctx.project, "fg")
    clips = [director.clip_from_item(dctx, it, next(ids)) for it in final]
    for c in clips:
        c["director"]["style"] = f"format:{ctx.spec['id']}"
    director.lay_out(ctx.project, clips)
    if len(clips) < len(ctx.graphics):
        ctx.note(f"{len(ctx.graphics) - len(clips)} of the format's graphics did not fit (no free space "
                 "off the face and captions).")
    ctx.notes += [n for n in dctx.notes if "not tracked" in n]


# ---- layout: split / picture-in-picture with another video
def op_layout(ctx, step):
    files = ctx.files(step["with"])
    if not files:
        if step.get("optional"):
            return
        raise FormatError(f"This format needs the {step['with']} file.")
    media_id = ctx.media_id(files[0])
    if ctx.media(media_id)["kind"] != "video":
        if step.get("optional"):
            ctx.note("The second file is a picture, so it is shown as a photo instead of a split screen.")
            return
        raise FormatError("A split screen or picture-in-picture needs a video.")
    layout = {"type": step["type"], "screen": media_id}
    for key in ("ratio", "corner", "size", "border", "animated"):
        if key in step:
            layout[key] = step[key]
    offset = (ctx.inputs.get("offsets") or {}).get(step["with"])
    if offset:
        layout["offset"] = float(offset)
    for clip in ctx.main_track()["clips"]:
        if clip["type"] == "video":
            clip["layout"] = dict(layout)
    if step["type"] == "split":
        for t in ctx.project["tracks"]:
            if t["kind"] == "caption":
                for c in t["clips"]:
                    c.setdefault("overrides", {})["zone"] = "divider"


# ---- B-roll files placed every few seconds (Yap)
def op_broll_files(ctx, step):
    files = ctx.files(step["role"])
    if not files:
        return
    every, seconds = float(step.get("every", 4.5)), float(step.get("seconds", 2.2))
    track = ctx.track("format-broll", "overlay", "B-roll", after_kind="overlay")
    total = ctx.duration()
    t, k = 1.5, 0
    while t + 0.8 < total:
        path = files[k % len(files)]
        mid = ctx.media_id(path)
        m = ctx.media(mid)
        d = min(seconds, total - t)
        if m["kind"] == "video":
            d = min(d, m["duration"])
        if d * ctx.fps >= 3 and all(c["start"] >= t + d or c["start"] + c["duration"] <= t for c in track["clips"]):
            clip = {"id": ctx.new_id("fb"), "type": "image" if m["kind"] == "image" else "video", "media": mid,
                    "start": round(t, 4), "duration": round(d, 4), "x": 540, "y": 960, "width": 1080,
                    "height": 1920, "animation": "none",
                    "broll": {"source": "file", "kind": "image" if m["kind"] == "image" else "video",
                              "position": "full"}}
            if m["kind"] == "video":
                clip.update({"in": 0.0, "out": round(d, 4)})
            track["clips"].append(clip)
        t += every
        k += 1


REACTION_WORDS = {"haha": "😂", "hahaha": "😂", "hahahaha": "😂", "lol": "😂", "grabe": "😱", "wow": "😮",
                  "omg": "😱", "naku": "😳", "talaga": "🤯", "what": "😳", "sheesh": "🔥", "solid": "🔥",
                  "sana": "🥹", "ganda": "😍", "nakakatawa": "🤣", "yikes": "😬", "aray": "😵"}


# ---- reaction moments: an emoji pops when you react
def op_reactions(ctx, step):
    from .director import norm
    last = -10.0
    for w in ctx.words():
        key = norm(w["text"])
        if key in REACTION_WORDS and w["start"] - last >= 2.0:
            ctx.graphics.append({"template": step.get("template", "emoji-pop"), "words": w["text"],
                                 "start": w["start"], "emoji": REACTION_WORDS[key], "importance": 0.6,
                                 "zone": "right", "mood": "funny"})
            last = w["start"]


ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "una": 1, "unang": 1, "pangalawa": 2, "ikalawa": 2,
            "pangalawang": 2, "ikalawang": 2, "pangatlo": 3, "ikatlo": 3, "pangatlong": 3, "ikatlong": 3,
            "pang-apat": 4, "ikaapat": 4, "pang-apat na": 4, "panglima": 5, "ikalima": 5, "pang-anim": 6,
            "ikaanim": 6, "pampito": 7, "ikapito": 7, "pangwalo": 8, "ikawalo": 8, "pansiyam": 9,
            "ikasiyam": 9, "pansampu": 10, "ikasampu": 10}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "isa": 1, "dalawa": 2, "tatlo": 3, "apat": 4, "lima": 5, "anim": 6,
                "pito": 7, "walo": 8, "siyam": 9, "sampu": 10}


def item_markers(words):
    """[(word index, number)] where an item starts: "first", "una", "number 3", "#2", "3."."""
    from .director import norm
    out = []
    for i, w in enumerate(words):
        tok = norm(w["text"])
        raw = w["text"].strip().lower()
        nxt = norm(words[i + 1]["text"]) if i + 1 < len(words) else ""
        n = None
        if tok in ORDINALS:
            n = ORDINALS[tok]
        elif tok in ("number", "numero", "no") and (nxt.isdigit() or nxt in NUMBER_WORDS):
            n = int(nxt) if nxt.isdigit() else NUMBER_WORDS[nxt]
        elif re.fullmatch(r"#\d{1,2}", raw) or re.fullmatch(r"\d{1,2}[.)]", raw):
            n = int(re.sub(r"\D", "", raw))
        if n is not None and 1 <= n <= 20:
            out.append((i, n))
    return out


def sentence_after(words, i, limit=6):
    """The words that follow a marker, up to the end of the sentence (at most `limit` words)."""
    from .director import shown, important, STOPWORDS, norm
    out = []
    j = i + 1
    if j < len(words) and (norm(words[j]["text"]).isdigit() or norm(words[j]["text"]) in NUMBER_WORDS):
        j += 1
    while j < len(words) and len(out) < limit:
        out.append(shown(words[j]))
        if re.search(r"[.?!]$", words[j]["text"]):
            break
        j += 1
    while out and norm(out[0]) in STOPWORDS:
        out.pop(0)
    return " ".join(x for x in out if x) if any(important(x) for x in out) else " ".join(out)


# ---- numbered items (Listicle) and the countdown (Ranking)
def op_items(ctx, step):
    words = ctx.words()
    given = [str(x) for x in (ctx.inputs.get("items") or [])]
    markers = item_markers(words)
    template = step["template"]
    countdown = bool(step.get("countdown"))
    picked = []
    if markers:
        for idx, n in markers:
            text = sentence_after(words, idx)
            picked.append((words[idx]["start"], n, text, words[idx]["text"]))
    elif given:
        # no spoken markers: spread the given items over the spoken part
        span_a = words[0]["start"] if words else 0.5
        span_b = words[-1]["end"] if words else ctx.duration()
        step_s = (span_b - span_a) / max(1, len(given))
        from .director import important, norm
        cursor = 0
        for k, item in enumerate(given):
            # the first time the item's words are said, after the previous item
            toks = {norm(x) for x in item.split() if important(x)}
            hit = next((q for q in range(cursor, len(words)) if norm(words[q]["text"]) in toks), None)
            if hit is not None:
                cursor = hit + 1
                at, word = words[hit]["start"], words[hit]["text"]
            else:                       # not said: spread evenly, on an important word
                at = span_a + k * step_s
                near = [q for q in range(len(words)) if important(words[q]["text"])] or list(range(len(words)))
                q = min(near, key=lambda q: abs(words[q]["start"] - at)) if near else None
                at, word = (words[q]["start"], words[q]["text"]) if q is not None else (at, item)
            n = (len(given) - k) if countdown else (k + 1)
            picked.append((at, n, item, word))
    if not picked:
        ctx.note("No list items were found: say \"first / una\", \"number 2\"... or give the items.")
        return
    if given and markers:
        picked = [(t, n, given[k] if k < len(given) else text, w) for k, (t, n, text, w) in enumerate(picked)]
    if countdown and markers and len(picked) > 1 and picked[0][1] < picked[-1][1]:
        ctx.note("The ranking was said from #1 upwards; the numbers follow what you said.")
    sfx = step.get("sfx")
    for at, n, text, word in picked:
        item = {"template": template, "words": word, "start": at, "number": n, "text": text[:60],
                "importance": 0.9, "zone": "upper" if template == "rank-number" else "auto", "mood": "hype"}
        ctx.graphics.append(item)
        if sfx:
            add_sfx(ctx, sfx, at)


def add_sfx(ctx, name, at, volume=0.6):
    """A short synthesised sound (pop, ding, whoosh...; yours from assets/sfx when there is one) on
    the sound-effects track."""
    from .sfx_synth import sound_file
    path = sound_file(name)
    mid = ctx.media_id(path)
    m = ctx.media(mid)
    d = min(m["duration"], max(0.05, ctx.duration() - at))
    track = next((t for t in ctx.project["tracks"] if t["kind"] == "audio" and t.get("role") == "sfx"), None)
    if track is None:
        track = ctx.track("sfx", "audio", "Sound effects", role="sfx")
    if any(not (c["start"] >= at + d or c["start"] + c["duration"] <= at) for c in track["clips"]):
        track = ctx.track(ctx.new_id("sfx-"), "audio", "Sound effects 2", role="sfx", after_kind="audio")
    track["clips"].append({"id": ctx.new_id("fs"), "type": "audio", "media": mid, "start": round(at, 4),
                           "duration": round(d, 4), "in": 0.0, "out": round(d, 4), "volume": volume})
    track["clips"].sort(key=lambda c: c["start"])


BEFORE = ("before", "dati", "bago", "noon", "dati-rati")
AFTER = ("after", "ngayon", "pagkatapos", "now", "result", "resulta")


# ---- before / after wipe with labels
def op_wipe(ctx, step):
    from .director import norm
    words = ctx.words()
    total = ctx.duration()
    at = None
    seen_before = False
    for w in words:
        k = norm(w["text"])
        if k in BEFORE:
            seen_before = True
        elif k in AFTER and (seen_before or at is None):
            at = w["start"]
            if seen_before:
                break
    if at is None:
        at = total * 0.45
        ctx.note("No \"before / after\" words found: the wipe is in the middle; move it on the timeline.")
    seconds = float(step.get("seconds", 3.0))
    start = max(0.0, min(at, total - 1.0))
    end = min(total, start + seconds)
    track = next((t for t in ctx.project["tracks"] if t["kind"] == "effect"), None) or \
        ctx.track("effects", "effect", "Effects")
    if any(not (c["start"] >= end or c["start"] + c["duration"] <= start) for c in track["clips"]):
        track = ctx.track(ctx.new_id("wipes-"), "effect", "Before / after", after_kind="effect")
    track["clips"].append({"id": ctx.new_id("fw"), "type": "wipe", "start": round(start, 4),
                           "duration": round(end - start, 4), "grade": step.get("grade", "orange_teal"),
                           "direction": "right", "sweep": 0.9, "stop": 0.5, "intensity": 1.0,
                           "label": "Before / after"})
    track["clips"].sort(key=lambda c: c["start"])
    if step.get("tags"):
        near = min(words, key=lambda w: abs(w["start"] - start))["text"] if words else "after"
        ctx.graphics.append({"template": "before-after-tag", "words": near, "start": start,
                             "text": "BEFORE", "text2": "AFTER", "importance": 0.9, "zone": "upper"})


VS = re.compile(r"([\w'’\-]+(?:\s[\w'’\-]+)?)\s+(?:vs\.?|versus|laban sa|o kaya)\s+"
                r"([\w'’\-]+(?:\s[\w'’\-]+)?)", re.I)


# ---- A vs B header
def op_versus(ctx, step):
    words = ctx.words()
    text = " ".join(w["text"] for w in words)
    m = VS.search(ctx.instruction) or VS.search(text)
    if not m:
        ctx.note("No \"A vs B\" found in your words or instructions; add the A VS B graphic yourself "
                 "(Graphics tab).")
        return
    a, b = m.group(1).split()[-1], m.group(2).split()[0]
    hit = next((w for w in words if a.lower() in w["text"].lower()), words[0] if words else None)
    at = hit["start"] if hit else 0.5
    ctx.graphics.append({"template": step.get("template", "versus-split"), "words": hit["text"] if hit else a,
                         "start": at, "text": a, "text2": b, "importance": 0.95, "zone": "upper", "mood": "hype"})


MARKERS = {"tip": "TIP", "tips": "TIP", "importante": "IMPORTANT", "important": "IMPORTANT",
           "tandaan": "TANDAAN", "remember": "REMEMBER", "note": "NOTE", "paalala": "PAALALA",
           "step": "STEP", "hakbang": "HAKBANG", "warning": "WARNING", "babala": "BABALA"}


# ---- explainer callouts and screenshots
def op_callouts(ctx, step):
    from .director import norm
    words = ctx.words()
    last = -10.0
    for i, w in enumerate(words):
        k = norm(w["text"])
        if k in MARKERS and w["start"] - last >= 4.0:
            text = sentence_after(words, i, limit=9)
            if not text:
                continue
            ctx.graphics.append({"template": step.get("template", "callout-box"), "words": w["text"],
                                 "start": w["start"], "text": text, "text2": MARKERS[k], "importance": 0.8,
                                 "mood": "warning" if MARKERS[k] in ("WARNING", "BABALA") else "serious",
                                 "icon": "warning" if MARKERS[k] in ("WARNING", "BABALA") else "check"})
            last = w["start"]
    shots = ctx.files(step.get("screenshots", "screenshots")) if step.get("screenshots") else []
    if not shots:
        return
    total = words[-1]["end"] if words else ctx.duration()
    for k, path in enumerate(shots):
        name_words = [x for x in re.split(r"[\W_]+", Path(path).stem.lower()) if len(x) > 2]
        hit = next((w for w in words if norm(w["text"]) in name_words), None)
        at = hit["start"] if hit else total * (k + 1) / (len(shots) + 1)
        near = hit or (min(words, key=lambda w: abs(w["start"] - at)) if words else None)
        mid = ctx.media_id(path)
        ctx.graphics.append({"template": "screenshot-frame", "words": near["text"] if near else Path(path).stem,
                             "start": near["start"] if near else at, "image": mid,
                             "text": Path(path).stem.replace("_", " ")[:36], "importance": 0.85, "mood": "tech"})


# ---- clone yourself: your other takes, cut out, over the first one
def op_cutouts(ctx, step):
    takes = ctx.files(step["role"])[:2]
    if not takes:
        raise FormatError("Clone yourself needs your other takes (same camera position).")
    main = ctx.main_track()["clips"]
    total = ctx.duration()
    mains = {c["media"] for c in main if c.get("media")}
    for k, path in enumerate(takes):
        mid = ctx.media_id(path)
        m = ctx.media(mid)
        if mid in mains:
            raise FormatError("The other takes must be different files from the main video.")
        length = min(total, m["duration"])
        if length * ctx.fps < 2:
            continue
        track = ctx.track(f"clone{k + 2}", "overlay", f"Clone {k + 2}", after_kind="overlay")
        track["clips"] = [{"id": ctx.new_id("fc"), "type": "video", "media": mid, "start": 0.0,
                           "duration": round(length, 4), "in": 0.0, "out": round(length, 4), "x": 540,
                           "y": 960, "width": 1080, "height": 1920, "animation": "none",
                           "mask": {"type": step.get("mask", "person")}, "label": f"You, take {k + 2}"}]
        if m.get("has_audio"):
            audio = ctx.track(f"clone{k + 2}-sound", "audio", f"Take {k + 2} sound", role="original",
                              after_kind="audio")
            audio["clips"] = [{"id": ctx.new_id("fa"), "type": "audio", "media": mid, "start": 0.0,
                               "duration": round(length, 4), "in": 0.0, "out": round(length, 4)}]
    ctx.note("Clone yourself: keep the camera still for every take; anything that moves in the "
             "background shows as a ghost.")


# ---- green screen: a new background behind you
def op_background(ctx, step):
    from .segment import looks_like_green_screen
    files = ctx.files(step["role"])
    if not files:
        raise FormatError("Green screen needs a background picture or video.")
    bg = ctx.media_id(files[0])
    bgm = ctx.media(bg)
    main = ctx.main_track()
    total = ctx.duration()
    you = [c for c in main["clips"] if c["type"] == "video"]
    if not you:
        raise FormatError("Green screen needs your talking video on the main track.")
    mask = {"type": "person"}
    if step.get("mask", "auto") in ("auto", "chroma"):
        src = Path(ctx.media(you[0]["media"])["path"])
        color = looks_like_green_screen(src if src.is_absolute() else ctx.base_dir / src)
        if color:
            mask = {"type": "chroma", "color": color}
        elif step.get("mask") == "chroma":
            mask = {"type": "chroma", "color": "#00ff00"}
    track = ctx.track("you", "overlay", "You (cut out)", after_kind="overlay")
    sound = ctx.track("you-sound", "audio", "Your voice", role="original", after_kind="audio")
    for c in you:
        moved = {k: v for k, v in c.items() if k in ("id", "type", "media", "start", "duration", "in", "out", "speed",
                                                      "label")}
        moved.update({"x": 540, "y": 960, "width": 1080, "height": 1920, "animation": "none", "mask": dict(mask)})
        track["clips"].append(moved)
        audio = {k: v for k, v in c.items() if k in ("media", "start", "duration", "in", "out", "speed", "volume",
                                                      "fade_in", "fade_out")}
        audio.update({"id": ctx.new_id("fv"), "type": "audio"})
        sound["clips"].append(audio)
    # the background fills the main track (a video repeats as needed)
    clips, t = [], 0.0
    while t < total - 1e-6:
        d = total - t if bgm["kind"] == "image" else min(total - t, bgm["duration"])
        if d * ctx.fps < 1:
            break
        clip = {"id": ctx.new_id("fbg"), "type": "image" if bgm["kind"] == "image" else "video",
                "media": bg, "start": round(t, 4), "duration": round(d, 4)}
        if bgm["kind"] == "video":
            clip.update({"in": 0.0, "out": round(d, 4), "volume": 0.0})
        clips.append(clip)
        t += d
    main["clips"] = clips
    ctx.note("Green screen: " + ("your green screen is keyed out." if mask["type"] == "chroma"
                                 else "you are cut out with person detection (needs its model)."))


# ---- voice-over over B-roll (no face)
def op_voiceover_broll(ctx, step):
    # done by build_voiceover_project before the steps run; nothing left to do here
    return


STEP_FUNCS = {"layout": op_layout, "broll_files": op_broll_files, "reactions": op_reactions,
              "items": op_items, "wipe": op_wipe, "versus": op_versus, "callouts": op_callouts,
              "cutouts": op_cutouts, "background": op_background, "voiceover_broll": op_voiceover_broll}


# ---------------------------------------------------------------- voice-over + B-roll projects

def build_voiceover_project(audio, broll, cfg, words, name="Voice-over"):
    """A project with no face: the voice-over on its track, the B-roll files on the main track
    cut to the sentences (in the order given, repeating), and captions of the voice-over."""
    from .captions import chunk_words  # noqa: F401  (keeps caption rules in one place)
    from .director import sentences
    from .pipeline import caption_groups
    from .project import media_from_file, new_project
    from .styles import get_style
    if not broll:
        raise FormatError("Voice-over with B-roll needs B-roll clips or pictures.")
    p = new_project(name, fps=int(cfg["output"]["fps"]),
                    caption_punctuation=(cfg.get("captions") or {}).get("punctuation", "remove"))
    voice = media_from_file(audio, "vo")
    p["media"].append(voice)
    total = voice["duration"]
    files = []
    for k, f in enumerate(broll):
        m = media_from_file(f, f"b{k + 1}")
        p["media"].append(m)
        files.append(m)
    wd = [{"text": w.text, "start": w.start, "end": w.end, "hl": bool(getattr(w, "highlight", False))} for w in words]
    cuts = [0.0]
    for sent in sentences(wd) if wd else []:
        end = wd[sent[-1]]["end"]
        if end - cuts[-1] >= 1.2 and end < total - 0.5:
            cuts.append(end)
    if len(cuts) == 1:
        n = max(1, int(total // 3))
        cuts = [total * k / n for n in [n] for k in range(n)]
    cuts.append(total)
    main = p["tracks"][0]
    k = 0
    for a, b in zip(cuts, cuts[1:]):
        t = a
        while b - t > 1 / 30:
            m = files[k % len(files)]
            d = b - t if m["kind"] == "image" else min(b - t, m["duration"])
            if d * 30 < 1:
                k += 1
                continue
            clip = {"id": f"v{len(main['clips']) + 1}", "type": "image" if m["kind"] == "image" else "video",
                    "media": m["id"], "start": round(t, 4), "duration": round(d, 4)}
            if m["kind"] == "video":
                clip.update({"in": 0.0, "out": round(d, 4), "volume": 0.0})
            main["clips"].append(clip)
            t += d
        k += 1
    vo = next(t for t in p["tracks"] if t["id"] == "voiceover")
    vo["clips"] = [{"id": "vo1", "type": "audio", "media": "vo", "start": 0.0, "duration": round(total, 4),
                    "in": 0.0, "out": round(total, 4)}]
    style = get_style(cfg["style"])
    caps = caption_groups(words, style, total)
    for n, c in enumerate(caps):
        c["id"] = f"t{n + 1}"
    p["tracks"][3]["clips"] = caps
    if cfg.get("grade") and cfg["grade"] != "none":
        p["tracks"][2]["clips"].append({"id": "g1", "type": "grade", "start": 0.0, "duration": round(total, 4),
                                        "grade": str(cfg["grade"])})
    return p


def frame_snap(t, fps):
    return math.floor(t * fps + 0.5) / fps
