"""Tracking: where the speaker's hands, face and body are in each frame, and how to follow
those points smoothly.

Two separate jobs:

  detect    run a local detector (MediaPipe) over the video and store the points it found
            (see `detect_video`, `Track`). Needs the optional `mediapipe` package and model
            files YOU download once (this app never downloads a model by itself).
  resolve   turn the stored raw points into a clean path for one effect: short gaps are
            filled, jitter is smoothed (One Euro filter), and when the point is lost the
            effect fades out instead of jumping (`resolve`).

Only `detect` needs MediaPipe. Everything else is plain Python, so tracked effects render
(and are tested) from stored or synthetic tracks without it.

Stored in the project as `tracking[<media id>]` (see docs/tracking.md):

    {"fps": 30, "start": 0.0, "source": "mediapipe 1.1.1", "swap_hands": false,
     "points": {"right_index_tip": {"x": [...], "y": [...], "c": [...], "s": [...]}, ...}}

x and y are 0-1 across the source frame (y down), `c` is the detector's confidence (0 = not
found), `s` (optional) is a size, as a fraction of the frame width. Sample i is at time
start + i / fps in the source video.
"""

import json
import math
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import PROJECT_DIR
from .errors import Cancelled, EditorError

HANDS = ("left", "right")
HAND_PARTS = ("wrist", "palm", "thumb_tip", "index_tip", "middle_tip", "ring_tip", "pinky_tip")
FINGERTIPS = ("thumb_tip", "index_tip", "middle_tip", "ring_tip", "pinky_tip")
POINT_NAMES = tuple(f"{h}_{p}" for h in HANDS for p in HAND_PARTS) + ("face", "body")
# MediaPipe hand landmark numbers.
HAND_LANDMARKS = {"wrist": 0, "thumb_tip": 4, "index_tip": 8, "middle_tip": 12,
                  "ring_tip": 16, "pinky_tip": 20}
PALM_LANDMARKS = (0, 5, 9, 13, 17)
# The points kept in a project by default (small, and what the effects use).
DEFAULT_POINTS = tuple(f"{h}_{p}" for h in HANDS
                       for p in ("wrist", "palm", "index_tip", "thumb_tip")) + ("face", "body")

# How the path of a point is cleaned up (seconds, except confidence and smoothing).
DEFAULTS = {
    "min_confidence": 0.35,   # samples below this count as "not found"
    "gap": 0.25,              # not-found stretches up to this long are bridged
    "attack": 0.12,           # fade in after the point is found
    "release": 0.4,           # fade out after it is lost (instead of jumping)
    "settle": 0.2,            # glide to a new position if found again while still fading
}

MODEL_PAGES = {
    "hand": "https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker",
    "face": "https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector",
    "pose": "https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker",
    "segment": "https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter",
}
MODEL_URLS = {
    "hand": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/"
            "float16/1/hand_landmarker.task",
    "face": "https://storage.googleapis.com/mediapipe-models/face_detector/"
            "blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
    "pose": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
            "pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    "segment": "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/"
               "float16/latest/selfie_segmenter.tflite",
}


# ---------------------------------------------------------------- stored tracks

@dataclass
class Point:
    """One tracked point over time: samples at start + i / fps."""
    x: list
    y: list
    c: list
    s: list = None            # optional size (fraction of the frame width)

    def __len__(self):
        return len(self.x)

    def to_json(self):
        out = {"x": [round(v, 4) for v in self.x], "y": [round(v, 4) for v in self.y],
               "c": [round(v, 3) for v in self.c]}
        if self.s is not None:
            out["s"] = [round(v, 4) for v in self.s]
        return out

    @staticmethod
    def from_json(data):
        return Point(list(data["x"]), list(data["y"]), list(data["c"]),
                     list(data["s"]) if data.get("s") is not None else None)


@dataclass
class Track:
    """The tracked points of one video."""
    fps: float
    start: float = 0.0
    points: dict = field(default_factory=dict)       # name -> Point
    source: str = ""
    swap_hands: bool = False
    notes: list = field(default_factory=list)

    @property
    def duration(self):
        return max((len(p) for p in self.points.values()), default=0) / self.fps

    def to_json(self, names=None):
        names = [n for n in (names or self.points) if n in self.points]
        out = {"fps": self.fps, "start": round(self.start, 4), "source": self.source,
               "points": {n: self.points[n].to_json() for n in names}}
        if self.swap_hands:
            out["swap_hands"] = True
        return out

    @staticmethod
    def from_json(data):
        return Track(float(data["fps"]), float(data.get("start", 0.0)),
                     {n: Point.from_json(p) for n, p in data["points"].items()},
                     data.get("source", ""), bool(data.get("swap_hands", False)))


def check_track_data(data):
    """Problems with a stored track (a list of messages; empty = fine). Used by the project
    validator."""
    problems = []
    if not isinstance(data, dict):
        return ["the track is not an object"]
    for name, p in (data.get("points") or {}).items():
        n = len(p.get("x", []))
        if name not in POINT_NAMES:
            problems.append(f"point '{name}' is not one of the known points")
        if not (n == len(p.get("y", [])) == len(p.get("c", []))):
            problems.append(f"point '{name}': x, y and c must be the same length")
        if p.get("s") is not None and len(p["s"]) != n:
            problems.append(f"point '{name}': s must be as long as x")
        if data.get("fps", 0) <= 0:
            problems.append("fps must be above 0")
    return problems


# ---------------------------------------------------------------- smoothing

def one_euro(values, dt, min_cutoff, beta=5.0, dcutoff=1.0):
    """The One Euro filter (Casiez et al. 2012) over evenly spaced samples: steady when the
    point rests, quick when it moves. Returns the filtered list."""
    def alpha(cutoff):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    out, prev, dprev = [], None, 0.0
    for v in values:
        if prev is None:
            out.append(v)
            prev = v
            continue
        d = (v - prev) / dt
        dhat = dprev + alpha(dcutoff) * (d - dprev)
        cutoff = min_cutoff + beta * abs(dhat)
        hat = prev + alpha(cutoff) * (v - prev)
        out.append(hat)
        prev, dprev = hat, dhat
    return out


def min_cutoff_for(smooth):
    """smooth 0 (follow the raw points) .. 1 (very steady): the filter's cutoff in Hz."""
    smooth = min(1.0, max(0.0, float(smooth)))
    return 15.0 * (0.6 / 15.0) ** smooth


def _smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


# ---------------------------------------------------------------- resolving a point

@dataclass
class Resolved:
    """The path of one point at a list of times."""
    x: list                    # 0-1 across the source frame
    y: list
    alpha: list                # 0 = not visible (lost), 1 = fully there
    size: list                 # fraction of the frame width (0 if the point has no size)


class Prepared:
    """A point with its short gaps filled and each found stretch smoothed (made once, used for
    every time asked)."""

    def __init__(self, point, fps, start, smooth=0.5, params=None):
        self.p = {**DEFAULTS, **(params or {})}
        self.fps, self.start, self.n = fps, start, len(point)
        n, dt = self.n, 1.0 / fps
        present = [c >= self.p["min_confidence"] for c in point.c]
        xs, ys = list(point.x), list(point.y)
        ss = list(point.s) if point.s is not None else [0.0] * n
        gap = max(1, int(round(self.p["gap"] * fps)))
        i = 0
        while i < n:
            if present[i]:
                i += 1
                continue
            j = i
            while j < n and not present[j]:
                j += 1
            if i > 0 and j < n and j - i <= gap:      # a short hole between two found stretches
                for k in range(i, j):
                    f = (k - i + 1) / (j - i + 1)
                    xs[k] = xs[i - 1] + (xs[j] - xs[i - 1]) * f
                    ys[k] = ys[i - 1] + (ys[j] - ys[i - 1]) * f
                    ss[k] = ss[i - 1] + (ss[j] - ss[i - 1]) * f
                    present[k] = True
            i = j
        cutoff = min_cutoff_for(smooth)
        i = 0
        while i < n:                                  # smooth every found stretch on its own
            if not present[i]:
                i += 1
                continue
            j = i
            while j < n and present[j]:
                j += 1
            xs[i:j] = one_euro(xs[i:j], dt, cutoff)
            ys[i:j] = one_euro(ys[i:j], dt, cutoff)
            if point.s is not None:
                ss[i:j] = one_euro(ss[i:j], dt, cutoff)
            i = j
        self.xs, self.ys, self.ss, self.present = xs, ys, ss, present

    def at(self, t):
        """(found?, x, y, size) at source time t (found only where samples exist)."""
        n = self.n
        u = (t - self.start) * self.fps
        if not n or u < -0.5 or u > n - 0.5:
            return False, 0.0, 0.0, 0.0
        i0 = min(n - 1, max(0, int(math.floor(u))))
        i1 = min(n - 1, i0 + 1)
        f = min(1.0, max(0.0, u - i0))
        if self.present[i0] and self.present[i1]:
            return (True, self.xs[i0] + (self.xs[i1] - self.xs[i0]) * f,
                    self.ys[i0] + (self.ys[i1] - self.ys[i0]) * f,
                    self.ss[i0] + (self.ss[i1] - self.ss[i0]) * f)
        k = i0 if f < 0.5 else i1
        if self.present[k]:
            return True, self.xs[k], self.ys[k], self.ss[k]
        return False, 0.0, 0.0, 0.0


def resolve_sequence(items, dt, params=None):
    """Follow a point over consecutive output frames. `items`: one (Prepared or None, source
    time) per frame; `dt`: seconds per frame.

    Short gaps are bridged (Prepared). When the point is lost the position is held and `alpha`
    fades to 0 over `release` seconds; it fades in over `attack` seconds when found; if found
    again while still fading, the position glides to the new place over `settle` seconds. So
    the effect never jumps while visible. A frame with no Prepared (no track there) is lost.
    """
    p = {**DEFAULTS, **(params or {})}
    out = Resolved([], [], [], [])
    vis, held, was_present = 0.0, None, False
    settle_from, settle_t = None, 0.0
    for k, (prep, t) in enumerate(items):
        here, tx, ty, ts = prep.at(t) if prep is not None else (False, 0.0, 0.0, 0.0)
        now = k * dt
        if here:
            fresh = False
            if not was_present:
                if vis > 0.02 and held is not None:
                    settle_from, settle_t = held, now
                else:
                    held, settle_from, vis, fresh = None, None, 0.0, True    # starts invisible
            if not fresh:
                vis = min(1.0, vis + dt / p["attack"])
            px, py = tx, ty
            if settle_from is not None:
                f = _smoothstep((now - settle_t) / p["settle"])
                px = settle_from[0] + (tx - settle_from[0]) * f
                py = settle_from[1] + (ty - settle_from[1]) * f
                if f >= 1.0:
                    settle_from = None
            held = (px, py, ts)
        else:
            vis = max(0.0, vis - dt / p["release"])
        was_present = here
        if held is None:
            out.x.append(0.5)
            out.y.append(0.5)
            out.size.append(0.0)
            out.alpha.append(0.0)
        else:
            out.x.append(held[0])
            out.y.append(held[1])
            out.size.append(held[2])
            out.alpha.append(_smoothstep(vis))
    return out


def resolve(point, fps, start, times, smooth=0.5, params=None):
    """Follow one stored `point` (samples at start + i / fps) at the given source `times`
    (evenly spaced, like frames). See `resolve_sequence`."""
    prep = Prepared(point, fps, start, smooth, params) if len(point) else None
    dt = (times[1] - times[0]) if len(times) > 1 and times[1] > times[0] else 1.0 / fps
    return resolve_sequence([(prep, t) for t in times], dt, params)


def point_names_for(clip):
    """Every stored point name a tracked-effect clip could follow (both hands for "any")."""
    point = clip.get("point", "palm")
    if point in ("face", "body"):
        return [point]
    parts = FINGERTIPS if point == "fingertips" else (point,)
    hands = HANDS if clip.get("hand", "any") == "any" else (clip["hand"],)
    return [f"{h}_{part}" for h in hands for part in parts]


def pick_hand(track, hand, part, t0, t1, min_confidence=DEFAULTS["min_confidence"]):
    """The point name for "left", "right" or "any" hand: for "any", the hand that is found
    most (by summed confidence) between source seconds t0 and t1."""
    def name(h):
        return f"{h}_{part}"
    if hand in HANDS:
        return name(hand)
    best, best_score = name("right"), -1.0
    for h in HANDS:
        pt = track.points.get(name(h))
        if pt is None:
            continue
        a = max(0, int((t0 - track.start) * track.fps))
        b = min(len(pt), int(math.ceil((t1 - track.start) * track.fps)) + 1)
        score = sum(c for c in pt.c[a:b] if c >= min_confidence)
        if score > best_score:
            best, best_score = name(h), score
    return best


# ---------------------------------------------------------------- detection (MediaPipe)

MODEL_DIR = PROJECT_DIR / "models" / "tracking"
MODEL_FILES = {"hand": "hand_landmarker.task", "face": "blaze_face_short_range.tflite",
               "pose": "pose_landmarker_lite.task", "segment": "selfie_segmenter.tflite"}
MODEL_SIZES = {"hand": "about 8 MB", "face": "under 1 MB", "pose": "about 6 MB",
               "segment": "under 1 MB"}


def models_dir():
    """Where the model files live: models/tracking/, or the folder in AUTOEDIT_TRACKING_MODELS."""
    import os
    return Path(os.environ.get("AUTOEDIT_TRACKING_MODELS") or MODEL_DIR)


def settings_of(cfg):
    """The tracking settings: config.yaml's, with the models folder as the default place for
    the model files (`models/tracking/`), so most people need no setting at all."""
    t = dict((cfg or {}).get("tracking") or {})

    def model(kind):
        given = str(t.get(f"{kind}_model") or "")
        if given:
            return given
        default = models_dir() / MODEL_FILES[kind]
        return str(default) if default.is_file() else ""
    return {"hand_model": model("hand"), "face_model": model("face"), "pose_model": model("pose"),
            "fps": float(t.get("fps") or 30),
            "min_confidence": float(t.get("min_confidence", 0.5)),
            "swap_hands": bool(t.get("swap_hands", False))}


def import_mediapipe():
    try:
        import mediapipe  # noqa: F401
        from mediapipe.tasks.python import BaseOptions, vision
        return mediapipe, BaseOptions, vision
    except ImportError:
        raise EditorError(
            "Tracking needs the free MediaPipe package. Install it once: "
            "python -m pip install mediapipe  (see docs/tracking.md)")


def face_ready(cfg):
    """MediaPipe face tracking can run (installed and its face model set), found without importing it."""
    import importlib.util
    model = settings_of(cfg)["face_model"]
    try:
        installed = importlib.util.find_spec("mediapipe") is not None
    except (ImportError, ValueError):
        installed = False
    return installed and bool(model) and Path(model).is_file()


def status(cfg):
    """What tracking can do right now: {"available", "hands", "face", "pose", "problems"}."""
    s = settings_of(cfg)
    problems = []
    try:
        import_mediapipe()
        installed = True
    except EditorError as exc:
        installed = False
        problems.append(str(exc))
    have = {k: bool(s[f"{k}_model"]) and Path(s[f"{k}_model"]).is_file() for k in ("hand", "face", "pose")}
    for kind in ("hand", "face", "pose"):
        if s[f"{kind}_model"] and not have[kind]:
            problems.append(f"The {kind} model file was not found: {s[f'{kind}_model']}")
    if installed and not have["hand"]:
        problems.append("No hand model yet: download it once (docs/tracking.md, or "
                        "`python editor.py track-models`) and set tracking: hand_model.")
    return {"available": installed and have["hand"], "installed": installed,
            "hands": installed and have["hand"], "face": installed and have["face"],
            "pose": installed and have["pose"], "problems": problems}


def _hand_points(landmarks, label, swap):
    """{point name: (x, y)} for one hand's 21 landmarks."""
    side = label.lower()
    if swap:
        side = "left" if side == "right" else "right"
    if side not in HANDS:
        return {}
    pts = {f"{side}_{part}": (landmarks[i].x, landmarks[i].y) for part, i in HAND_LANDMARKS.items()}
    pts[f"{side}_palm"] = (sum(landmarks[i].x for i in PALM_LANDMARKS) / len(PALM_LANDMARKS),
                           sum(landmarks[i].y for i in PALM_LANDMARKS) / len(PALM_LANDMARKS))
    return pts


def frame_points(hand_result, face_result, pose_result, width, height, swap=False):
    """Turn one frame's MediaPipe results into {point name: (x, y, confidence, size)}.

    Pure (no MediaPipe import): works on the result objects' attributes, so it is tested with
    stand-ins. A body is taken from the pose model if there is one, else estimated from the
    face (below it, 2.8 face widths wide).
    """
    found = {}
    if hand_result is not None:
        best = {}                                     # side -> (score, its points)
        for marks, hands in zip(hand_result.hand_landmarks, hand_result.handedness):
            cat = hands[0]
            pts = _hand_points(marks, cat.category_name, swap)
            for side in {n.split("_", 1)[0] for n in pts}:
                if side not in best or cat.score > best[side][0]:
                    best[side] = (float(cat.score), pts)
        for score, pts in best.values():
            for name, (x, y) in pts.items():
                found[name] = (x, y, score, 0.0)
    if face_result is not None and face_result.detections:
        d = max(face_result.detections, key=lambda d: d.categories[0].score)
        b = d.bounding_box
        found["face"] = ((b.origin_x + b.width / 2) / width, (b.origin_y + b.height / 2) / height,
                         float(d.categories[0].score), b.width / width)
        if pose_result is None or not pose_result.pose_landmarks:
            fw = b.width / width
            found["body"] = (found["face"][0], found["face"][1] + 1.9 * b.height / height,
                             found["face"][2] * 0.6, fw * 2.8)
    if pose_result is not None and pose_result.pose_landmarks:
        m = pose_result.pose_landmarks[0]
        pts = [m[i] for i in (11, 12, 23, 24)]
        vis = min(float(getattr(q, "visibility", 1.0) or 0.0) for q in pts)
        shoulder = abs(m[11].x - m[12].x)
        found["body"] = (sum(q.x for q in pts) / 4, sum(q.y for q in pts) / 4, vis, shoulder * 1.4)
    return found


def read_frames(video, start, duration, fps, height=960, cancel=None):
    """(width, height, an iterator of RGB frames as bytes) from FFmpeg, `fps` per second."""
    from .ffmpeg_tools import probe
    info = probe(video)
    h = int(height)
    w = int(round(info["width"] * h / info["height"] / 2) * 2)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.4f}", "-t", f"{duration:.4f}", "-i", str(video),
           "-an", "-vf", f"fps={fps:g},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    size = w * h * 3

    def frames():
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("Cancelled.")
                buf = proc.stdout.read(size)
                if len(buf) < size:
                    break
                yield buf
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
    return w, h, frames()


def detect_video(video, cfg, ranges=None, names=None, reporter=None, cancel=None):
    """Run the detector over the video (or just `ranges`, a list of (start, end) seconds) and
    return a Track with the wanted point names (default: all of them).

    Needs `mediapipe` and the model files named in config.yaml (tracking:). Runs on the CPU.
    """
    import numpy as np
    s = settings_of(cfg)
    st = status(cfg)
    if not st["installed"]:
        raise EditorError(st["problems"][0])
    if not st["hands"] and not st["face"]:
        raise EditorError(" ".join(st["problems"]) or "No tracking model is set up.")
    mp, BaseOptions, vision = import_mediapipe()
    from .ffmpeg_tools import probe
    info = probe(video)
    duration = info["duration"]
    fps = s["fps"]
    ranges = [(max(0.0, a), min(duration, b)) for a, b in (ranges or [(0.0, duration)])]
    ranges = [(a, b) for a, b in ranges if b > a]
    if not ranges:
        raise EditorError("Nothing to track: the time range is empty.")
    lo = min(a for a, _ in ranges)
    hi = max(b for _, b in ranges)
    n = int(math.ceil((hi - lo) * fps)) + 1
    wanted = list(names or POINT_NAMES)
    track = Track(fps, lo, {k: Point([0.0] * n, [0.0] * n, [0.0] * n,
                                     [0.0] * n if k in ("face", "body") else None)
                            for k in wanted},
                  f"mediapipe {getattr(mp, '__version__', '?')}", s["swap_hands"])
    total = sum(b - a for a, b in ranges)
    done = 0.0
    started = time.time()
    for a, b in ranges:
        hand = face = pose = None
        try:
            run = vision.RunningMode.VIDEO
            if st["hands"] and any(k.split("_")[0] in HANDS for k in wanted):
                hand = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=s["hand_model"]), running_mode=run,
                    num_hands=2, min_hand_detection_confidence=s["min_confidence"],
                    min_hand_presence_confidence=s["min_confidence"],
                    min_tracking_confidence=s["min_confidence"]))
            if st["face"] and any(k in ("face", "body") for k in wanted):
                face = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
                    base_options=BaseOptions(model_asset_path=s["face_model"]), running_mode=run,
                    min_detection_confidence=s["min_confidence"]))
            if st["pose"] and "body" in wanted:
                pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=s["pose_model"]), running_mode=run,
                    num_poses=1, min_pose_detection_confidence=s["min_confidence"],
                    min_pose_presence_confidence=s["min_confidence"],
                    min_tracking_confidence=s["min_confidence"]))
            w, h, frames = read_frames(video, a, b - a, fps, cancel=cancel)
            for k, raw in enumerate(frames):
                image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                 data=np.frombuffer(raw, np.uint8).reshape(h, w, 3))
                ts = int(round(k * 1000.0 / fps))
                found = frame_points(hand.detect_for_video(image, ts) if hand else None,
                                     face.detect_for_video(image, ts) if face else None,
                                     pose.detect_for_video(image, ts) if pose else None,
                                     w, h, s["swap_hands"])
                idx = int(round((a - lo) * fps)) + k
                if idx >= n:
                    break
                for name, (x, y, c, size) in found.items():
                    pt = track.points.get(name)
                    if pt is None:
                        continue
                    pt.x[idx], pt.y[idx], pt.c[idx] = x, y, c
                    if pt.s is not None:
                        pt.s[idx] = size
                if reporter and k % 15 == 0:
                    reporter.progress(min(0.99, (done + k / fps) / total))
        except (OSError, RuntimeError, ValueError) as exc:
            raise EditorError(
                f"MediaPipe could not start: {exc}. On Linux it may need `sudo apt install libegl1 "
                "libgles2`; on Windows the Microsoft Visual C++ Redistributable. Also check that "
                "the model files are the ones from docs/tracking.md. Nothing else was changed.")
        finally:
            for d in (hand, face, pose):
                if d is not None:
                    d.close()
        done += b - a
    track.notes.append(f"tracked {total:.1f}s in {time.time() - started:.1f}s")
    if reporter:
        reporter.progress(1.0)
    return track


def track_cache_key(cache, video, cfg):
    """Cache key: this video's content, the models and the sample rate."""
    s = settings_of(cfg)
    models = [(k, Path(s[f"{k}_model"]).name, Path(s[f"{k}_model"]).stat().st_size
               if Path(s[f"{k}_model"]).is_file() else 0) for k in ("hand", "face", "pose")]
    return f"{cache.fingerprint(video)}-{json.dumps(models)}-{s['fps']}-{s['swap_hands']}"


def merge_ranges(ranges, gap=0.5):
    out = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


# ---------------------------------------------------------------- tracking for an AI plan

def tracking_text(cfg):
    """What the AI is told about tracked effects."""
    st = status(cfg)
    if not st["available"] and not st["face"]:
        return ("TRACKED EFFECTS: NOT available (tracking is not set up on this PC). Leave "
                "tracked_effects empty.")
    what = " and ".join(k for k, ok in (("hands", st["hands"]), ("face and body", st["face"])) if ok)
    return (f"TRACKED EFFECTS: available for {what}. Plan tracked_effects (a glow, sparks, an aura "
            "or energy that follows them) only when the creator asks for such an effect; "
            "otherwise leave it empty. Use only points marked available here"
            + ("" if st["hands"] else "; hands are NOT available")
            + ("" if st["face"] else "; face and body are NOT available") + ".")


def coverage(track, names, t0, t1, min_confidence=DEFAULTS["min_confidence"]):
    """The share (0-1) of source seconds t0..t1 in which the best of these points was found."""
    best = 0.0
    for name in names:
        pt = track.points.get(name)
        if pt is None:
            continue
        a = max(0, int((t0 - track.start) * track.fps))
        b = min(len(pt), int(math.ceil((t1 - track.start) * track.fps)))
        if b > a:
            best = max(best, sum(1 for c in pt.c[a:b] if c >= min_confidence) / (b - a))
    return best


def track_for_plan(plan, video, cfg, cache=None, reporter=None, cancel=None):
    """Find the points the plan's tracked effects need. Returns
    {"track": Track or None, "notes": [...]}: notes say what could not be done and how well the
    points were found. Never raises for a missing MediaPipe/model: the edit goes on without."""
    items = plan.get("tracked_effects") or []
    out = {"track": None, "notes": []}
    if not items:
        return out
    st = status(cfg)
    usable = []
    for e in items:
        face = e["point"] in ("face", "body")
        ok = st["face"] if face else st["hands"]
        if ok:
            usable.append(e)
        else:
            out["notes"].append(
                f"Not done: tracked {e['effect']} at {_mmss(e['at'])} ("
                + ("; ".join(st["problems"]) if st["problems"] else
                   f"no {'face' if face else 'hand'} model is set up") + ")")
    if not usable:
        return out
    names = sorted({n for e in usable for n in point_names_for(e)})
    ranges = merge_ranges([(max(0.0, e["at"] - 0.5), e["at"] + e["duration"] + 0.5) for e in usable])
    key = None
    track = None
    if cache is not None:
        from .cache import key_for
        key = key_for({"k": track_cache_key(cache, video, cfg), "ranges": ranges, "names": names})
        data = cache.get("tracks", key)
        if data:
            track = Track.from_json(data)
    if track is None:
        if reporter:
            reporter.stage("tracking", "Following your hands and face")
        track = detect_video(video, cfg, ranges=ranges, names=names, reporter=reporter, cancel=cancel)
        if cache is not None:
            cache.put("tracks", key, track.to_json())
    out["track"] = track
    for e in usable:
        c = coverage(track, point_names_for(e), e["at"], e["at"] + e["duration"])
        if c < 0.25:
            out["notes"].append(
                f"Tracked {e['effect']} at {_mmss(e['at'])}: the {'hand' if e['point'] not in ('face', 'body') else e['point']} "
                f"was found in only {c * 100:.0f}% of that moment, so the effect will mostly not "
                "show. Good light and an open, visible hand help.")
    return out


def _mmss(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


# ---------------------------------------------------------------- model files (you choose)

def model_info():
    """What each model is, where it comes from and where it would be saved."""
    return [{"kind": k, "file": MODEL_FILES[k], "url": MODEL_URLS[k], "page": MODEL_PAGES[k],
             "size": MODEL_SIZES[k], "path": str(models_dir() / MODEL_FILES[k]),
             "present": (models_dir() / MODEL_FILES[k]).is_file()} for k in MODEL_FILES]


def download_models(kinds, folder=None, cancel=None, log=print):
    """Download the chosen models. Only ever called because YOU asked (the command line
    `track-models --download ... --yes`, or the confirm button in the app); the app never
    fetches a model by itself."""
    import os
    import requests
    folder = Path(folder or models_dir())
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind in kinds:
        if kind not in MODEL_URLS:
            raise EditorError(f"Unknown model '{kind}'. Choose: {', '.join(MODEL_URLS)}")
        path = folder / MODEL_FILES[kind]
        part = path.with_name(path.name + ".part")
        log(f"Downloading the {kind} model from {MODEL_URLS[kind]} ...")
        try:
            with requests.get(MODEL_URLS[kind], stream=True, timeout=60) as r:
                if r.status_code != 200:
                    raise EditorError(f"The {kind} model could not be downloaded ({r.status_code}). "
                                      f"Download it by hand from {MODEL_PAGES[kind]}")
                with open(part, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        if cancel is not None and cancel.is_set():
                            raise Cancelled("Cancelled.")
                        f.write(chunk)
            if part.stat().st_size < 1000:
                raise EditorError(f"The downloaded {kind} model looks wrong (too small).")
            os.replace(part, path)
        except requests.RequestException as exc:
            raise EditorError(f"Could not download the {kind} model (check your internet): {exc}")
        finally:
            if part.exists():
                part.unlink()
        paths[kind] = str(path)
    return paths
