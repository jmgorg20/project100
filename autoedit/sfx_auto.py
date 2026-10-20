"""Automatic sound effects, synced to the graphics and effects of the edit (PREMIUM EDITORIAL VIRAL):

    a card comes in            whoosh (a word / title popping in: soft pop)
    a big card goes            whoosh out (quieter)
    the search bar types       a typing click for each letter, between its two cues
    a checklist item ticks     tick (each item on its spoken word); also each countdown number,
                               each number card, each storyboard step
    a screenshot / phone       camera shutter
    the black-and-white past   a rise into it, a soft impact when the colour comes back ("ngayon")

The sounds are made by FFmpeg on your PC (autoedit/sfx_synth.py; your own files in assets/sfx win),
quiet, a little quieter still while you speak (ducking), spaced out (never two within 80 ms, at most
8 a second). Setting: `sfx: auto: auto | off` and `sfx: auto_volume` (config.yaml; the app's
Settings -> Sound effects).
"""

from .formats import Ctx, add_sfx, get as get_format

POP_IN = {"kinetic-words", "editorial-headline", "strike-text", "marker-highlight", "subtitle-card", "label-pill",
          "magazine-cover", "pop-heavy", "bounce-words"}
TICKS = {"editorial-checklist", "countdown-timer", "stat-cards", "storyboard-doc", "tile-mosaic", "timeline-card",
         "checklist"}
SHUTTER = {"screenshot-collage", "phone-mockup", "screenshot-montage", "mosaic-grid"}
BIG = {"editorial-checklist", "storyboard-doc", "screenshot-collage", "phone-mockup", "magazine-cover", "tile-mosaic",
       "stat-cards", "countdown-timer", "search-bar", "timeline-card", "chat-cards"}
MIN_GAP = 0.08
PER_SECOND = 8


def plan(project):
    """[(sound, time, loudness 0-1)] for the edit's graphics and effects, in time order."""
    out = []
    for t in project["tracks"]:
        if t.get("hidden"):
            continue
        for c in t["clips"]:
            start, end = c["start"], c["start"] + c["duration"]
            if t["kind"] == "graphics" and c.get("type") == "graphic":
                tpl = c.get("template", "")
                cues = [start + float(x) for x in ((c.get("params") or {}).get("cues") or [])]
                out.append(("soft_pop" if tpl in POP_IN else "whoosh", start, 0.8 if tpl in POP_IN else 1.0))
                if tpl == "search-bar" and len(cues) >= 2:
                    letters = max(1, len(str((c.get("params") or {}).get("text", ""))))
                    step = max(0.06, min(0.12, (cues[1] - cues[0]) / letters))
                    k = cues[0]
                    while k < cues[1] and k < end:
                        out.append(("type", k, 0.5))
                        k += step
                elif tpl in TICKS:
                    out += [("tick", x, 0.7) for x in cues if start < x < end]
                if tpl in SHUTTER:
                    out.append(("shutter", start + 0.12, 0.8))      # just after the whoosh
                if tpl in BIG and end - start > 1.0:
                    out.append(("whoosh_out", max(start, end - 0.3), 0.6))
            elif t["kind"] == "effect" and c.get("type") == "fx" and c.get("effect") == "bw" and \
                    str(c.get("label", "")).startswith("Before"):
                out.append(("rise", max(0.0, start - 0.6), 0.8))
                out.append(("impact", end - 0.15, 0.9))
    return space_out(sorted(out, key=lambda s: s[1]))


# when two sounds would come too close, the one that marks something arriving wins
RANK = {"whoosh": 0, "soft_pop": 0, "shutter": 1, "rise": 1, "impact": 1, "tick": 2, "type": 3, "whoosh_out": 4}


def space_out(sounds):
    kept = []
    for name, at, loud in sorted(sounds, key=lambda s: (RANK.get(s[0], 5), s[1])):
        if at < 0:
            continue
        if any(abs(at - k[1]) < MIN_GAP for k in kept):
            continue
        if sum(1 for k in kept if 0 <= at - k[1] < 1.0 or 0 <= k[1] - at < 1.0) >= 2 * PER_SECOND:
            continue
        kept.append((name, round(at, 4), loud))
    return sorted(kept, key=lambda s: s[1])


def add(project, cfg, base_dir="."):
    """Put the sounds on the project's sound-effects track. Returns how many were added (0 when
    `sfx: auto: off`)."""
    settings = (cfg or {}).get("sfx") or {}
    if str(settings.get("auto", "auto")).lower() == "off":
        return 0
    volume = max(0.0, min(1.0, float(settings.get("auto_volume", 0.35))))
    if volume <= 0:
        return 0
    duration = max((c["start"] + c["duration"] for t in project["tracks"] if t["kind"] == "video"
                    for c in t["clips"]), default=0.0)
    ctx = Ctx(project, get_format("talking_head"), {}, cfg, base_dir)
    n = 0
    for name, at, loud in plan(project):
        if at >= duration - 0.05:
            continue
        add_sfx(ctx, name, at, volume=round(volume * loud, 3))
        n += 1
    if n:
        audio = project["settings"].setdefault("audio", {})
        audio.setdefault("sfx_ducking", 0.5)           # a little quieter while you speak
    return n
