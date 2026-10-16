"""Transcribe one part of the timeline again and replace the captions there.

For a bad stretch of captions: the main video's sound between `start` and `end` (timeline
seconds) is sent to the transcriber again (with your vocabulary), your corrections are applied,
and the captions in that range are replaced. Captions outside the range are not touched; a
caption that crosses the edge is cut at it. The new captions take the style of the nearest
existing caption.
"""

import copy
from pathlib import Path

from .captions import chunk_words, group_end_times
from .errors import EditorError
from .highlight import mark_keywords
from .project import clip_end, media_by_id, resolve_media_path
from .styles import get_style
from .vocabulary import fix_words

EPS = 1e-6


def speech_pieces(project, start, end):
    """The parts of the main video in [start, end): (clip, media, source a, source b)."""
    main = next((t for t in project["tracks"] if t["kind"] == "video"), None)
    media = media_by_id(project)
    pieces = []
    for clip in sorted(main["clips"] if main else [], key=lambda c: c["start"]):
        if clip["type"] != "video":
            continue
        a, b = max(start, clip["start"]), min(end, clip_end(clip))
        if b - a <= EPS:
            continue
        speed = float(clip.get("speed", 1.0))
        src_a = clip["in"] + (a - clip["start"]) * speed
        src_b = clip["in"] + (b - clip["start"]) * speed
        pieces.append((clip, media[clip["media"]], src_a, src_b))
    return pieces


def to_timeline(clip, words, lo, hi):
    """Source-time words of one main clip -> timeline-time words inside [lo, hi)."""
    speed = float(clip.get("speed", 1.0))
    out = []
    for w in words:
        s = clip["start"] + (w.start - clip["in"]) / speed
        e = clip["start"] + (w.end - clip["in"]) / speed
        if lo - EPS <= (s + e) / 2 < hi:
            out.append(w.copy(start=max(lo, s), end=min(hi, max(s, e))))
    return out


def _cut_caption(clip, start, end, ids):
    """What is left of a caption clip outside [start, end) (0, 1 or 2 clips)."""
    left, right = [], []
    for w in clip["words"]:
        mid = clip["start"] + (w["start"] + w["end"]) / 2
        (left if mid < start else right if mid >= end else []).append(w)
    out = []
    if left and clip["start"] < start:
        c = copy.deepcopy(clip)
        c["duration"] = round(min(clip_end(clip), start) - clip["start"], 6)
        c["words"] = [{**w, "end": min(w["end"], c["duration"])} for w in left]
        out.append(c)
    if right and clip_end(clip) > end:
        c = copy.deepcopy(clip)
        shift = max(0.0, end - clip["start"])
        c["start"] = round(clip["start"] + shift, 6)
        c["duration"] = round(clip_end(clip) - c["start"], 6)
        c["words"] = [{**w, "start": max(0.0, w["start"] - shift), "end": max(0.0, w["end"] - shift)}
                      for w in right]
        if out:
            n = 2
            while f"{clip['id']}_{n}" in ids:
                n += 1
            c["id"] = f"{clip['id']}_{n}"
            ids.add(c["id"])
        out.append(c)
    return out


def retranscribe(project, project_file, cfg, start, end, work_dir, transcribe_fn=None):
    """Return (new project, number of words) with the captions in [start, end) redone."""
    if end - start < 0.2:
        raise EditorError("Choose at least a fifth of a second to transcribe again.")
    if transcribe_fn is None:
        from .transcribe import transcribe as transcribe_fn
    base = Path(project_file).parent
    words = []
    for n, (clip, media, a, b) in enumerate(speech_pieces(project, start, end)):
        if not media.get("has_audio", True):
            continue
        job = Path(work_dir) / f"piece{n}"
        job.mkdir(parents=True, exist_ok=True)
        got = transcribe_fn(resolve_media_path(media, base), cfg, job, a, b)
        words += to_timeline(clip, got, max(start, clip["start"]), min(end, clip_end(clip)))
    words = fix_words(words, cfg)
    project = copy.deepcopy(project)
    tracks = [t for t in project["tracks"] if t["kind"] == "caption"]
    track = next((t for t in tracks if not t.get("locked")), None)
    if track is None:
        if tracks:
            raise EditorError("The caption track is locked. Unlock it first.")
        track = {"id": "captions", "kind": "caption", "name": "Captions", "clips": []}
        project["tracks"].append(track)
    # The style of the nearest caption (else the settings' style).
    near = sorted(track["clips"], key=lambda c: min(abs(c["start"] - start), abs(clip_end(c) - end)))
    template = {k: copy.deepcopy(near[0][k]) for k in ("style", "overrides", "highlight_keywords")
                if k in near[0]} if near else {"style": cfg["style"], "highlight_keywords": True}
    ids = {c["id"] for t in project["tracks"] for c in t["clips"]}
    kept = []
    for clip in track["clips"]:
        kept += _cut_caption(clip, start, end, ids) if clip["start"] < end and clip_end(clip) > start else [clip]
    mark_keywords(words, cfg["highlight"])
    style = get_style(template["style"])
    groups = chunk_words(words, style) if words else []
    n = 1
    for lines, group_end in zip(groups, group_end_times(groups)):
        flat = [w for line in lines for w in line]
        s, e = flat[0].start, min(group_end, end)
        if e - s < 0.01:
            continue
        while f"rt{n}" in ids:
            n += 1
        ids.add(f"rt{n}")
        kept.append({"id": f"rt{n}", "type": "caption", "start": round(s, 6),
                     "duration": round(e - s, 6), **copy.deepcopy(template),
                     "words": [{"text": w.text, "start": round(w.start - s, 3),
                                "end": round(min(w.end, e) - s, 3), "highlight": w.highlight}
                               for w in flat]})
    track["clips"] = sorted(kept, key=lambda c: c["start"])
    return project, len(words)
