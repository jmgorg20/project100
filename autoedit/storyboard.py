"""The storyboard: the edit shown as scenes before rendering.

A storyboard is a *view* of the project, not a second copy of it: scenes are worked out from the
captions (a scene ends at the end of a sentence once it is 2 s long, or at 6 s), and every scene's
pieces are the ordinary clips on the timeline. Changing a scene changes those clips:

    lock       the scene's captions, graphics, B-roll, effects and sounds get `locked` (your main
               video clips stay editable, so cuts still work)
    text       the scene's caption words are replaced (spread over its captions, evenly timed)
    regenerate the scene's graphics get another look (or new ones, if it has none)
    replace    the scene's B-roll gets another file (the app does this with its B-roll tools)

desktop/src/shared/storyboard.ts does the same in the app (a test checks they agree).
"""

import copy
import re

from .errors import EditorError

MIN_SCENE = 2.0
MAX_SCENE = 6.0
EPS = 0.05
CTA_WORDS = ("follow", "i-follow", "subscribe", "comment", "like", "share", "link", "bio", "order",
             "bili", "bumili", "click", "i-click", "download", "sign up", "mag-sign", "dm", "message",
             "i-message", "check out", "tara")
PURPOSES = {
    "hook": ("Hook", "Pambungad"), "point": ("Point", "Punto"), "proof": ("Proof / numbers", "Patunay"),
    "question": ("Question", "Tanong"), "cta": ("Call to action", "Panawagan"), "outro": ("Ending", "Pagtatapos"),
}


class StoryboardError(EditorError):
    pass


def r4(x):
    return round(x + 0.0, 4)


def _end(c):
    return c["start"] + c["duration"]


def _caption_text(c):
    return " ".join(w["text"] for w in c.get("words") or []).strip() or str(c.get("label") or "")


def _main(project):
    return project["tracks"][0]


def timeline_end(project):
    return max((_end(c) for t in project["tracks"] for c in t["clips"]), default=0.0)


def _boundaries(project):
    """Scene start times: the frozen ones (meta.storyboard.starts), else worked out."""
    frozen = ((project.get("meta") or {}).get("storyboard") or {}).get("starts")
    if isinstance(frozen, list) and frozen and all(isinstance(x, (int, float)) for x in frozen):
        return sorted({0.0, *(r4(float(x)) for x in frozen)})
    return detect_boundaries(project)


def freeze(project):
    """Keep the current scenes as they are (so editing a scene's words does not regroup the
    scenes). Changes `project` in place and returns it."""
    project.setdefault("meta", {}).setdefault("storyboard", {})["starts"] = [s["start"] for s in scenes(project)]
    return project


def detect_boundaries(project):
    """Scene start times worked out from the captions (or the main clips)."""
    caps = sorted((c for t in project["tracks"] if t["kind"] == "caption" for c in t["clips"]),
                  key=lambda c: c["start"])
    starts = [0.0]
    if caps:
        scene_start = 0.0
        for k, c in enumerate(caps):
            nxt = caps[k + 1] if k + 1 < len(caps) else None
            if nxt is None:
                break
            text = _caption_text(c)
            length = nxt["start"] - scene_start
            sentence_end = bool(re.search(r"[.!?…]$", text))
            if (length >= MIN_SCENE and sentence_end) or length >= MAX_SCENE:
                scene_start = nxt["start"]
                starts.append(r4(scene_start))
    else:
        scene_start = 0.0
        for c in sorted(_main(project)["clips"], key=lambda c: c["start"]):
            if c["start"] - scene_start >= MIN_SCENE:
                scene_start = c["start"]
                starts.append(r4(scene_start))
    return starts


def _purpose(index, count, text):
    low = " " + text.lower() + " "
    if index == 0:
        return "hook"
    if index == count - 1 and any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in CTA_WORDS):
        return "cta"
    if re.search(r"\d|₱|\$|%|piso|peso", low):
        return "proof"
    if "?" in text:
        return "question"
    if index == count - 1:
        return "outro"
    return "point"


def scene_clips(project, scene):
    """The clips that belong to a scene: they start in it and end by its end (main video clips and
    clips spanning several scenes, like music, are not part of one scene)."""
    out = []
    for i, t in enumerate(project["tracks"]):
        if i == 0:
            continue
        for c in t["clips"]:
            if scene["start"] - EPS <= c["start"] < scene["end"] - EPS and _end(c) <= scene["end"] + EPS:
                out.append((t, c))
    return out


def scenes(project):
    """The storyboard: a list of scenes (dicts) in time order."""
    media = {m["id"]: m for m in project.get("media", [])}

    def name(mid):
        m = media.get(mid) or {}
        return m.get("name") or str(m.get("path", mid)).replace("\\", "/").split("/")[-1]

    end = timeline_end(project)
    starts = [s for s in _boundaries(project) if s < end - EPS] or [0.0]
    out = []
    for k, a in enumerate(starts):
        b = starts[k + 1] if k + 1 < len(starts) else end
        scene = {"id": f"s{k + 1}", "index": k + 1, "start": r4(a), "end": r4(b), "duration": r4(b - a)}
        own = scene_clips(project, scene)
        caps = [c for t, c in own if t["kind"] == "caption"]
        text = " ".join(_caption_text(c) for c in sorted(caps, key=lambda c: c["start"])).strip()
        main = [c for c in _main(project)["clips"] if c["start"] < b - EPS and _end(c) > a + EPS]
        sources = []
        for c in main:
            n = name(c.get("media")) if c.get("media") else c["type"]
            if n not in sources:
                sources.append(n)
        broll = []
        for t, c in own:
            if t["kind"] == "overlay" and c.get("media") and name(c["media"]) not in broll:
                broll.append(name(c["media"]))
        graphics = [{"id": c["id"], "template": c["template"],
                     "text": str((c.get("params") or {}).get("text") or "")}
                    for t, c in own if c.get("type") == "graphic"]
        transition = "start" if k == 0 else "cut"
        for t, c in sorted(own, key=lambda tc: tc[1]["start"]):
            if c["start"] > a + 0.4:
                continue
            if c.get("type") == "wipe":
                transition = "wipe"
                break
            kind = (c.get("attach") or {}).get("kind")
            if kind:
                transition = kind
                break
            if c.get("type") == "fx" and c.get("effect") in ("flash", "whip", "shake", "glitch"):
                transition = c["effect"]
                break
        mid = (a + b) / 2
        music = []
        sfx = 0
        for t in project["tracks"]:
            if t["kind"] != "audio":
                continue
            for c in t["clips"]:
                if t.get("role") == "music" and c["start"] < b - EPS and _end(c) > a + EPS:
                    if name(c["media"]) not in music:
                        music.append(name(c["media"]))
                if t.get("role") == "sfx" and a - EPS <= c["start"] < b - EPS:
                    sfx += 1
        mood = "none"
        for t in project["tracks"]:
            for c in t["clips"]:
                if c.get("type") == "grade" and c["start"] <= mid < _end(c):
                    mood = c["grade"]
        lockable = [c for t, c in own]
        purpose = _purpose(k, len(starts), text)
        scene.update({
            "purpose": purpose, "purpose_label": PURPOSES[purpose][0], "purpose_tl": PURPOSES[purpose][1],
            "text": text, "sources": sources, "broll": broll, "graphics": graphics, "transition": transition,
            "music": music, "sfx": sfx, "mood": mood,
            "locked": bool(lockable) and all(c.get("locked") for c in lockable),
            "clips": [c["id"] for c in lockable],
        })
        out.append(scene)
    return out


def find_scene(project, scene_id):
    for s in scenes(project):
        if s["id"] == scene_id or str(s["index"]) == str(scene_id):
            return s
    raise StoryboardError(f"There is no scene '{scene_id}' (the storyboard has {len(scenes(project))}).")


def set_locked(project, scene_id, locked=True):
    """Lock (or unlock) every clip of a scene. Returns a copy."""
    project = freeze(copy.deepcopy(project))
    scene = find_scene(project, scene_id)
    ids = set(scene["clips"])
    for t in project["tracks"]:
        for c in t["clips"]:
            if c["id"] in ids:
                if locked:
                    c["locked"] = True
                else:
                    c.pop("locked", None)
    return project


def _spread(counts, total):
    """Split `total` words over captions that had `counts` words (largest remainder, >= 1 each)."""
    n = len(counts)
    if total <= n:
        return [1] * total + [0] * (n - total)
    weight = sum(counts) or n
    exact = [total * c / weight for c in counts]
    out = [max(1, int(x)) for x in exact]
    while sum(out) > total:
        i = max(range(n), key=lambda j: (out[j] - exact[j], j))
        out[i] -= 1
    order = sorted(range(n), key=lambda j: (-(exact[j] - out[j]), j))
    k = 0
    while sum(out) < total:
        out[order[k % n]] += 1
        k += 1
    return out


def set_text(project, scene_id, text):
    """Replace a scene's caption words (evenly timed inside each caption). Returns a copy."""
    project = freeze(copy.deepcopy(project))
    scene = find_scene(project, scene_id)
    ids = set(scene["clips"])
    caps = sorted((c for t in project["tracks"] if t["kind"] == "caption" for c in t["clips"] if c["id"] in ids),
                  key=lambda c: c["start"])
    if not caps:
        raise StoryboardError("This scene has no captions to change.")
    if any(c.get("locked") for c in caps):
        raise StoryboardError("This scene is locked. Unlock it first.")
    words = str(text).split()
    if not words:
        raise StoryboardError("Type the words for this scene (to remove its captions, delete them on the timeline).")
    counts = _spread([len(c.get("words") or []) for c in caps], len(words))
    at = 0
    drop = set()
    for c, n in zip(caps, counts):
        if n == 0:
            drop.add(c["id"])
            continue
        step = c["duration"] / n
        c["words"] = [{"text": w, "start": r4(i * step), "end": r4((i + 1) * step)}
                      for i, w in enumerate(words[at:at + n])]
        at += n
    for t in project["tracks"]:
        t["clips"] = [c for c in t["clips"] if c["id"] not in drop]
    return project


def regenerate(project, scene_id, cfg, provider=None, model=None, cache=None, cancel=None):
    """Another look for a scene's graphics (or new ones, if it has none). Locked graphics stay.
    Returns {"project", "changed", "notes"}."""
    from . import director
    project = freeze(copy.deepcopy(project))
    scene = find_scene(project, scene_id)
    if scene["locked"]:
        raise StoryboardError("This scene is locked. Unlock it first.")
    instruction = str((project.get("meta") or {}).get("instruction") or "")
    notes, changed = [], []
    if ((project.get("meta") or {}).get("editorial") or {}).get("scenes"):
        return _regenerate_editorial(project, scene, cfg, instruction, cancel)
    todo = [g["id"] for g in scene["graphics"]]
    locked = {c["id"] for t in project["tracks"] for c in t["clips"] if c.get("locked")}
    todo = [i for i in todo if i not in locked]
    if todo:
        for gid in todo:
            r = director.regenerate_item(project, gid, cfg, instruction, provider, model, cache, cancel)
            project = r["project"]
            changed.append(r["clip"]["id"])
            notes += r["notes"]
        return {"project": project, "changed": changed, "notes": notes}
    styles = [((c.get("director") or {}).get("style") or "") for c in director.graphic_clips_of(project)]
    style = next((s for s in styles if s in director.STYLES), None)
    if style is None:
        preset = (project.get("meta") or {}).get("preset")
        if preset:
            from . import presets
            try:
                g = presets.get(preset, cfg)["graphics"]
                style = g if g in director.STYLES else None
            except EditorError:
                style = None
    style = style or director.DEFAULT_STYLE
    made = director.generate(project, cfg, instruction, style, provider, model, cache, None, cancel,
                             use_ai=provider is not None)
    if made is None:
        return {"project": project, "changed": [], "notes": ["No graphics for this style."]}
    out = copy.deepcopy(project)
    existing = {c["id"] for c in director.graphic_clips_of(out)}
    new = [c for c in director.graphic_clips_of(made["project"])
           if c["id"] not in existing and scene["start"] - EPS <= c["start"] < scene["end"] - EPS
           and _end(c) <= scene["end"] + EPS]
    if new:
        taken = {c["id"] for t in out["tracks"] for c in t["clips"]}
        for n, c in enumerate(new):
            cid = c["id"]
            while cid in taken:
                cid = f"{c['id']}s{n}"
                n += 1
            c["id"] = cid
            taken.add(cid)
        director.lay_out(out, new)
        changed = [c["id"] for c in new]
    else:
        notes.append("The Director found nothing in this scene worth a graphic (no key words); "
                     "add one from the Graphics tab.")
    return {"project": out, "changed": changed, "notes": notes + list(made.get("notes") or [])}


def _regenerate_editorial(project, scene, cfg, instruction, cancel):
    """A video planned scene by scene (PREMIUM EDITORIAL VIRAL): every editorial scene that starts
    in this storyboard scene gets another beat; the rest of the edit stays as it is."""
    from . import editorial
    rows = project["meta"]["editorial"]["scenes"]
    todo = [r["index"] for r in rows if scene["start"] - EPS <= r["start"] < scene["end"] - EPS]
    if not todo:
        return {"project": project, "changed": [], "notes": ["No editorial scene starts here."]}
    changed, notes = [], []
    for index in todo:
        r = editorial.regenerate_scene(project, index, cfg, instruction, cancel=cancel)
        project = r["project"]
        changed += r["clips"]
        notes += [f"Scene {index + 1}: {r['before'] or 'nothing'} -> {r['beat']}."] + r["notes"]
    return {"project": project, "changed": changed, "notes": notes}
