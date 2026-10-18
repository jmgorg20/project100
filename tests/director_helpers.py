"""Synthetic projects for the Director tests: a talking video's words as caption clips."""

from autoedit.config import load_config
from autoedit.project import new_project

SCRIPT = (
    "Grabe ang bilis ng kita ko ngayon . Nag-start ako sa 500 pesos lang . "
    "Pero ngayon umaabot na ng 250000 pesos kada buwan . Mag-ingat sa mga scam kasi marami ang "
    "nalilinlang . Ang sikreto ko ay simple lang , gamitin ang AI para sa edit . "
    "Libre ito at madali , sobrang saya ko talaga . Tingnan mo dito ang resulta . "
    "I-follow mo ako para sa mas maraming tips . Comment mo ang salitang EDIT at ipapadala ko ang guide . "
    "Maraming salamat sa lahat ng nanood ."
).split()


def make_words(tokens=SCRIPT, start=0.4, per_word=0.42, pause=0.55):
    """Evenly timed words; a '.' or ',' token is a pause (and ends the previous word with it)."""
    words, t = [], start
    for tok in tokens:
        if tok in (".", ","):
            words[-1]["text"] += tok
            t += pause if tok == "." else pause / 3
            continue
        words.append({"text": tok, "start": round(t, 3), "end": round(t + per_word * 0.9, 3)})
        t += per_word
    return words


def make_project(words=None, duration=None, fps=30, caption_style="yellow_pop", zone=None,
                 tracking=None, width=1080, height=1920):
    words = words or make_words()
    duration = duration or round(words[-1]["end"] + 0.6, 3)
    p = new_project("director-test", fps=fps)
    p["media"] = [{"id": "m1", "kind": "video", "path": "talk.mp4", "name": "talk.mp4",
                   "duration": duration, "width": width, "height": height, "has_audio": True}]
    p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "m1", "start": 0,
                                "duration": duration, "in": 0, "out": duration}]
    caps, group = [], []
    for w in words:
        group.append(w)
        last = w["text"][-1] in ".!?"
        if len(group) >= 5 or last or w is words[-1]:
            start, end = group[0]["start"], group[-1]["end"]
            nxt = words[words.index(w) + 1]["start"] if w is not words[-1] else end + 0.25
            clip = {"id": f"c{len(caps) + 1}", "type": "caption", "start": start,
                    "duration": round(min(end + 0.25, nxt - 0.001) - start, 3), "style": caption_style,
                    "words": [{"text": g["text"], "start": round(g["start"] - start, 3),
                               "end": round(g["end"] - start, 3)} for g in group]}
            if zone:
                clip["overrides"] = {"zone": zone}
            caps.append(clip)
            group = []
    p["tracks"][3]["clips"] = caps
    if tracking:
        p["tracking"] = tracking
    return p


def face_tracking(fps=30, seconds=40, x=0.5, y=0.30, size=0.28, media="m1", moves=None):
    """A face that stays (or moves along `moves(t) -> (x, y)`) in the source picture."""
    n = int(seconds * fps)
    xs, ys = [], []
    for i in range(n):
        px, py = moves(i / fps) if moves else (x, y)
        xs.append(px)
        ys.append(py)
    return {media: {"fps": fps, "start": 0.0, "source": "synthetic",
                    "points": {"face": {"x": xs, "y": ys, "c": [1.0] * n, "s": [size] * n}}}}


def cfg():
    c = load_config()
    return c
