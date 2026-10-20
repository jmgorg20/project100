"""Cutting a person out of a video, for "Clone yourself" and "Green screen".

Two free, local ways, plain compositing (no generative AI):

  person   MediaPipe's selfie segmenter (a small model file you download once, after you confirm,
           like the tracking models) says for every pixel how likely it is the person. That is
           cleaned up (steadied over time, edges tightened and softened, small specks removed)
           and saved as a grey "mask" video: white = keep, black = transparent.
  chroma   a real green (or blue) screen is keyed out by FFmpeg's chromakey + despill.

The renderer joins a clip with its mask (alphamerge) and lays it over the picture.
Masks are cached under a key of the video, the part used and the settings.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from . import PROJECT_DIR
from .errors import Cancelled, EditorError
from .ffmpeg_tools import find_tool, probe

SEGMENT_MODEL = "selfie_segmenter.tflite"
SEGMENT_URL = ("https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/"
               "float16/latest/selfie_segmenter.tflite")
SEGMENT_PAGE = "https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter"
SEGMENT_SIZE = "under 1 MB"
MASK_WIDTH = 540                 # masks are made at half width, then scaled up (soft edges)
VERSION = 2                      # bump when the cleanup changes


def cache_dir():
    override = os.environ.get("AUTOEDIT_MASK_CACHE")
    return Path(override) if override else PROJECT_DIR / "work" / "cache" / "masks"


def model_path(cfg=None):
    from .tracking import models_dir
    given = str(((cfg or {}).get("tracking") or {}).get("segment_model") or "")
    if given:
        return Path(given)
    return models_dir() / SEGMENT_MODEL


def status(cfg=None):
    """{"available", "installed", "model", "problems"} for person cut-outs."""
    from .tracking import import_mediapipe
    problems = []
    try:
        import_mediapipe()
        installed = True
    except EditorError as exc:
        installed = False
        problems.append(str(exc))
    path = model_path(cfg)
    have = path.is_file()
    if installed and not have:
        problems.append("No person-cutout model yet: download it once (python editor.py "
                        "track-models --download segment --yes, or in the app).")
    return {"available": installed and have, "installed": installed, "model": str(path),
            "problems": problems}


# ---------------------------------------------------------------- the mask cleanup (numpy)

def _shift_stack(a, r):
    import numpy as np
    p = np.pad(a, r, mode="edge")
    h, w = a.shape
    return [p[dy:dy + h, dx:dx + w] for dy in range(2 * r + 1) for dx in range(2 * r + 1)]


def erode(a, r=1):
    import numpy as np
    return np.minimum.reduce(_shift_stack(a, r))


def dilate(a, r=1):
    import numpy as np
    return np.maximum.reduce(_shift_stack(a, r))


def box_blur(a, r=2):
    import numpy as np
    if r <= 0:
        return a
    k = 2 * r + 1
    p = np.pad(a, r, mode="edge").astype(np.float32)
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    h, w = a.shape
    s = c[k:k + h, k:k + w] - c[:h, k:k + w] - c[k:k + h, :w] + c[:h, :w]
    return s / (k * k)


class MaskCleaner:
    """Turns raw per-frame person probabilities into a steady mask with clean, soft edges."""

    def __init__(self, steady=0.55, low=0.35, high=0.65, feather=2):
        self.steady, self.low, self.high, self.feather = steady, low, high, feather
        self.prev = None

    def __call__(self, prob):
        import numpy as np
        p = np.clip(prob.astype(np.float32), 0.0, 1.0)
        if self.prev is not None and self.prev.shape == p.shape:
            p = self.steady * self.prev + (1 - self.steady) * p     # less flicker
        self.prev = p
        x = np.clip((p - self.low) / (self.high - self.low), 0, 1)
        x = x * x * (3 - 2 * x)                                  # soft threshold
        x = dilate(erode(x, 1), 1)                               # remove specks
        x = erode(dilate(x, 1), 1)                               # fill pin holes
        return np.clip(box_blur(x, self.feather), 0, 1)          # feathered edge


# ---------------------------------------------------------------- person masks

def mask_key(video, start, end, fps, cfg=None):
    st = Path(video).stat()
    basis = {"v": VERSION, "path": str(Path(video).resolve()), "size": st.st_size,
             "mtime": int(st.st_mtime), "start": round(start, 3), "end": round(end, 3), "fps": fps,
             "model": str(model_path(cfg))}
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:24]


def person_mask(video, start, end, fps, cfg=None, cancel=None, reporter=None, folder=None):
    """A grey mask video (FFV1) of the person in `video` from `start` to `end` seconds, at
    `fps`, MASK_WIDTH wide. Cached. Raises EditorError when person cut-outs are not set up."""
    import numpy as np
    folder = Path(folder) if folder else cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{mask_key(video, start, end, fps, cfg)}.mkv"
    if out.exists():
        return out
    st = status(cfg)
    if not st["available"]:
        raise EditorError("Cutting a person out needs MediaPipe and its person-cutout model: "
                          + " ".join(st["problems"]) + " (A real green screen works without it: "
                          "the Green screen format keys it out.)")
    from .tracking import import_mediapipe
    mp, BaseOptions, vision = import_mediapipe()
    info = probe(video)
    w = MASK_WIDTH
    h = int(round(info["height"] * w / max(1, info["width"]) / 2)) * 2
    length = max(0.0, end - start)
    frames = max(1, int(round(length * fps)))
    decode = subprocess.Popen(
        [find_tool("ffmpeg"), "-v", "error", "-ss", f"{start:.4f}", "-t", f"{length + 1 / fps:.4f}",
         "-i", str(video), "-vf", f"fps={fps},scale={w}:{h}", "-frames:v", str(frames),
         "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    part = out.with_name(out.stem + ".part.mkv")
    encode = subprocess.Popen(
        [find_tool("ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}",
         "-r", str(fps), "-i", "-", "-c:v", "ffv1", "-pix_fmt", "gray", str(part)], stdin=subprocess.PIPE)
    segmenter = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(model_path(cfg))),
        running_mode=vision.RunningMode.VIDEO, output_confidence_masks=True, output_category_mask=False))
    clean = MaskCleaner()
    done = 0
    try:
        if reporter:
            reporter.stage("cutout", "Cutting you out of the video")
        while True:
            raw = decode.stdout.read(w * h * 3)
            if len(raw) < w * h * 3:
                break
            if cancel is not None and cancel.is_set():
                raise Cancelled("Cancelled.")
            frame = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
            result = segmenter.segment_for_video(image, int(done * 1000 / fps))
            prob = np.asarray(result.confidence_masks[0].numpy_view(), dtype=np.float32).reshape(h, w)
            encode.stdin.write((clean(prob) * 255 + 0.5).astype(np.uint8).tobytes())
            done += 1
            if reporter and done % 10 == 0:
                reporter.progress(min(1.0, done / frames), stage="cutout")
        # a short source: hold the last mask so the mask is never shorter than the clip
        last = (clean.prev if clean.prev is not None else np.zeros((h, w), np.float32))
        while done < frames:
            encode.stdin.write((np.clip(last, 0, 1) * 255).astype(np.uint8).tobytes())
            done += 1
        encode.stdin.close()
        if encode.wait() != 0:
            raise EditorError("FFmpeg could not write the person mask.")
        os.replace(part, out)
    finally:
        segmenter.close()
        if decode.poll() is None:
            decode.kill()
        if encode.poll() is None:
            encode.kill()
        if part.exists():
            part.unlink()
    return out


# ---------------------------------------------------------------- green screens

def looks_like_green_screen(video, at=None):
    """True when the edges of the picture are mostly one strong green (or blue): a real screen."""
    import numpy as np
    info = probe(video)
    t = at if at is not None else min(1.0, info["duration"] / 2)
    raw = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
                          "-frames:v", "1", "-vf", "scale=96:-2", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, stdin=subprocess.DEVNULL).stdout
    if not raw:
        return None
    w = 96
    h = len(raw) // (w * 3)
    img = np.frombuffer(raw[:w * h * 3], np.uint8).reshape(h, w, 3).astype(int)
    edge = np.concatenate([img[:, :6].reshape(-1, 3), img[:, -6:].reshape(-1, 3), img[:6].reshape(-1, 3)])
    r, g, b = edge[:, 0], edge[:, 1], edge[:, 2]
    green = (g > 90) & (g > r * 1.4) & (g > b * 1.3)
    blue = (b > 90) & (b > r * 1.4) & (b > g * 1.2)
    if green.mean() > 0.6:
        return "#00ff00"
    if blue.mean() > 0.6:
        return "#0000ff"
    return None


def chroma_filter(color="#00ff00", similarity=0.18, blend=0.06):
    """FFmpeg filters that make a green (or blue) screen transparent and remove its colour spill."""
    hexc = "0x" + color.lstrip("#")
    spill = "green" if color.lower() in ("#00ff00", "#00b140", "#00ff40") or color[3:5].lower() >= "a0" else "blue"
    return f"chromakey={hexc}:{similarity:g}:{blend:g},despill=type={spill}"
