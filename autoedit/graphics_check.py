"""Checks on the graphics of a project before export: on the face, off the screen, on the
captions, unreadable text. Warnings only: the creator decides."""

from pathlib import Path

from . import graphics, zones

MIN_FONT = 30                 # px on the 1080x1920 frame
MIN_CONTRAST = 3.0            # WCAG "large text" level (graphics text is big)
FACE_OVERLAP = 0.04           # share of the face covered before we warn
CAPTION_OVERLAP = 0.10        # share of the graphic on the captions before we warn


def luminance(hex_color):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    """WCAG contrast ratio (1 to 21) between two #rrggbb colours."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_on(bg):
    return "#ffffff" if contrast("#ffffff", bg) >= contrast("#111111", bg) else "#111111"


def _issue(clip, kind, message, tl, severity="warn"):
    return {"clip": clip["id"], "kind": kind, "severity": severity, "time": clip["start"],
            "message": message, "tl": tl}


def check_project(project, base_dir=".", cfg=None):
    """Problems with the project's graphics: a list of {"clip", "kind", "message", "tl", ...}."""
    clips = graphics.graphic_clips(project)
    if not clips:
        return []
    fps = project["settings"]["fps"]
    from .project import media_by_id
    media = media_by_id(project)
    min_font = float(((cfg or {}).get("graphics") or {}).get("min_font") or MIN_FONT)
    face = zones.FaceMap(project)
    end_of_video = max((c["start"] + c["duration"] for t in project["tracks"] if t["kind"] == "video"
                        for c in t["clips"]), default=0.0)
    issues = []
    for _track, clip in clips:
        meta = graphics.template_meta(clip["template"])
        params = clip.get("params") or {}
        job = graphics.job_for_clip(clip, fps, media, base_dir)
        side = graphics.read_meta(job) if Path(job["out"]).exists() else None
        box = graphics.estimated_box(clip, meta, side)
        exact = side is not None
        t0, t1 = clip["start"], clip["start"] + clip["duration"]
        what = f"'{clip.get('label') or meta['name']}' at {t0:.1f}s"
        approx = "" if exact else " (estimated size)"

        if zones.off_screen_fraction(box) > 0.02:
            issues.append(_issue(clip, "off-screen", f"{what} runs off the screen{approx}.",
                                 f"Lumalabas sa screen ang {what}."))
        elif not zones.inside(box):
            issues.append(_issue(clip, "safe-area", f"{what} is where the app's buttons or text will cover it{approx}.",
                                 f"Natatakpan ng buttons ng app ang {what}."))
        frect = face.rect(t0, t1)
        if frect is not None:
            covered = zones.overlap_area(box, frect) / max(1.0, zones.area(frect))
            if covered > FACE_OVERLAP and meta["category"] != "pointer" and not meta.get("covers"):
                tag = "" if face.known else " (the face was not tracked: a typical position was assumed)"
                issues.append(_issue(clip, "face", f"{what} covers the speaker's face{approx}{tag}.",
                                     f"Natatakpan ng {what} ang mukha{approx}."))
        for r in zones.caption_rects(project, t0, t1):
            if zones.overlap_area(box, r) / max(1.0, zones.area(box)) > CAPTION_OVERLAP:
                issues.append(_issue(clip, "caption", f"{what} sits on top of the captions{approx}.",
                                     f"Nakapatong sa captions ang {what}."))
                break
        if t1 > end_of_video + 1.0 / fps and end_of_video > 0:
            issues.append(_issue(clip, "past-end", f"{what} runs past the end of the video.",
                                 f"Lampas sa dulo ng video ang {what}."))
        issues += _readability(clip, meta, params, side, what, min_font)
    return issues


def _readability(clip, meta, params, side, what, min_font):
    out = []
    defaults = {"color": "#ffffff", "bg": "#111827", **meta["defaults"]}
    color = params.get("color", defaults["color"])
    bg = params.get("bg", defaults["bg"])
    text = str(params.get("text", ""))
    plain = text.replace("*", "")
    if len(plain) > meta["maxChars"]:
        out.append(_issue(clip, "text-long", f"{what}: the text is longer than this graphic is made for "
                          f"({len(plain)} > {meta['maxChars']} letters); it will be cut.",
                          f"Masyadong mahaba ang text ng {what}; puputulin ito."))
    if side:
        rep = side.get("report") or {}
        px = rep.get("fontPx")
        if px is not None and px < min_font:
            out.append(_issue(clip, "unreadable", f"{what}: the text had to shrink to {px:.0f}px, which is hard "
                              "to read on a phone. Use fewer words or a different graphic.",
                              f"Masyadong liit ang text ng {what} ({px:.0f}px). Paikliin ito."))
        if rep.get("broke"):
            out.append(_issue(clip, "unreadable", f"{what}: a very long word had to be broken across lines.",
                              f"Napilitang putulin ang napakahabang salita sa {what}."))
    if meta["bg"]:
        if contrast(color, bg) < MIN_CONTRAST:
            out.append(_issue(clip, "contrast", f"{what}: the text colour is hard to read on its background "
                              f"(contrast {contrast(color, bg):.1f}:1).",
                              f"Mahirap basahin ang kulay ng text sa {what}."))
    elif plain and contrast(color, "#000000") < MIN_CONTRAST and contrast(color, "#ffffff") < MIN_CONTRAST:
        out.append(_issue(clip, "contrast", f"{what}: the text colour is too dull to read on video.",
                          f"Masyadong malabo ang kulay ng text sa {what}."))
    elif plain and contrast(color, "#000000") < MIN_CONTRAST:
        out.append(_issue(clip, "contrast", f"{what}: the text is dark; it can vanish on dark footage.",
                          f"Madilim ang text ng {what}; baka mawala sa madilim na video."))
    return out
