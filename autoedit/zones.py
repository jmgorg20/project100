"""Where things are on the finished 1080x1920 frame: the speaker's face, the captions, the safe area.

The Director uses it to place graphics where they do not cover the face or the captions, and
the export check uses it to warn when they do. Rectangles are (x0, y0, x1, y1) in pixels.
"""

import math

from .captions import ZONES
from .render import H, W
from .styles import get_style

# The part of the frame that apps (TikTok, Reels) do not cover with their own buttons and text.
SAFE = (40, 150, 1040, 1460)
FACE_MARGIN = 20                      # keep graphics this far (px) from the face
CAPTION_MARGIN = 18
DEFAULT_FACE = (320, 380, 760, 920)  # a speaker in the upper middle (no tracking available)
# the editorial planner's assumption when the face could not be found (it moves the speaker lower
# under its cards, so it can afford the full size): measured on a real 9:16 talking-head video,
# the head with a cap spans x 230-830, y 250-830
TALKING_HEAD_FACE = (200, 220, 880, 1020)

# How tall a caption block is for each zone (px): up to two lines of the usual sizes.
CAPTION_HEIGHT = 230
CAPTION_X = (90, 910)


def inflate(rect, by):
    return (rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by)


def overlap_area(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def intersects(a, b):
    return overlap_area(a, b) > 0


def area(rect):
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def inside(rect, outer=SAFE):
    return rect[0] >= outer[0] and rect[1] >= outer[1] and rect[2] <= outer[2] and rect[3] <= outer[3]


def off_screen_fraction(rect):
    """The share (0-1) of the rectangle that is outside the frame."""
    total = area(rect)
    if total <= 0:
        return 0.0
    return 1.0 - overlap_area(rect, (0, 0, W, H)) / total


def union(rects):
    rects = list(rects)
    if not rects:
        return None
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


# ---------------------------------------------------------------- captions

def caption_zone_rect(zone, left_aligned=False):
    """Where captions in a zone sit (a generous block, so graphics keep clear of them)."""
    align, _x, y = ZONES.get(zone, ZONES["lower"])
    if align == 2:           # anchored at the bottom
        y0, y1 = y - CAPTION_HEIGHT, y + 10
    elif align == 8:         # anchored at the top
        y0, y1 = y - 10, y + CAPTION_HEIGHT
    else:
        y0, y1 = y - CAPTION_HEIGHT // 2, y + CAPTION_HEIGHT // 2
    return (CAPTION_X[0], y0, CAPTION_X[1], y1)


def caption_rects(project, t0, t1):
    """The caption blocks visible somewhere between t0 and t1 (seconds on the timeline)."""
    rects = []
    for track in project["tracks"]:
        if track["kind"] != "caption" or track.get("hidden"):
            continue
        for clip in track["clips"]:
            if clip["start"] >= t1 or clip["start"] + clip["duration"] <= t0:
                continue
            zone = (clip.get("overrides") or {}).get("zone")
            if zone is None:
                try:
                    zone = get_style(clip["style"]).zone
                except Exception:
                    zone = "lower"
            rects.append(caption_zone_rect(zone))
    return rects


# ---------------------------------------------------------------- the face

def _main_map(project):
    """A FrameMap of the main track (cached on the project's id for the duration of a call)."""
    from .project import media_by_id, timeline_duration
    from .project_render import frame_index, main_segments, zoom_layers
    from .trackfx import FrameMap
    fps = project["settings"]["fps"]
    media = media_by_id(project)
    total = frame_index(timeline_duration(project), fps)
    return FrameMap(main_segments(project, media, fps, total), fps, zoom_layers(project, fps)), fps


class FaceMap:
    """Where the speaker's face is on the finished frame, over time.

    With saved tracking points (the project's `tracking`) the face is followed through cuts,
    reframing and zooms; without them a typical talking-head position is assumed, and `known`
    is False so callers can say so."""

    def __init__(self, project, default=None):
        from .tracking import Prepared, Track
        self.known = False
        self.default = default or DEFAULT_FACE
        self.prepared = {}
        tracking = project.get("tracking") or {}
        for media_id, data in tracking.items():
            if "face" in (data.get("points") or {}):
                track = Track.from_json(data)
                self.prepared[media_id] = (Prepared(track.points["face"], track.fps, track.start, 0.5),
                                           track)
        self.known = bool(self.prepared)
        self.fmap, self.fps = _main_map(project) if self.known else (None, project["settings"]["fps"])
        self.project = project

    def moved(self, rect, f):
        """`rect` where it is while a "speaker_low" layout has moved the speaker down."""
        from .project_render import layout_scale_at
        z = layout_scale_at(self.project, f / self.fps)
        if rect is None or z >= 0.999:
            return rect
        return (W / 2 + (rect[0] - W / 2) * z, H - (H - rect[1]) * z,
                W / 2 + (rect[2] - W / 2) * z, H - (H - rect[3]) * z)

    def rect_at_frame(self, f):
        """The face rectangle at timeline frame f, or None if it is not found there."""
        if not self.known:
            return self.moved(self.default, f)
        return self.moved(self._rect_at_frame(f), f)

    def _rect_at_frame(self, f):
        info = self.fmap.info(f)
        if info is None or info.media["id"] not in self.prepared:
            return None
        prep, _track = self.prepared[info.media["id"]]
        found, sx, sy, ssize = prep.at(info.source_time)
        if not found:
            return None
        x, y, size = self.fmap.to_frame(info, sx, sy, ssize)
        x, y, size = self.fmap.zoomed(f, x, y, size)
        width = max(size, 60.0)
        # the head around the detected face: hair above, the chin a little below
        return (x - width * 0.65, y - width * 0.78, x + width * 0.65, y + width * 0.62)

    def rect(self, t0, t1, step=0.12):
        """The face region over t0..t1 (the union of where it is, sampled every `step` s)."""
        rects = []
        n = max(1, int(math.ceil((t1 - t0) / step)))
        for k in range(n + 1):
            r = self.rect_at_frame(int(round((t0 + (t1 - t0) * k / n) * self.fps)))
            if r is not None:
                rects.append(r)
        return union(rects)   # None: the face was not found in this moment (nothing to avoid)

    def coverage(self, t0, t1, step=0.12):
        """The share of t0..t1 in which the face was found (1.0 when nothing is tracked)."""
        if not self.known:
            return 0.0
        n = max(1, int(math.ceil((t1 - t0) / step)))
        hits = sum(self.rect_at_frame(int(round((t0 + (t1 - t0) * k / n) * self.fps))) is not None
                   for k in range(n + 1))
        return hits / (n + 1)
