"""Tracked effects: a glow, sparks, an aura, energy rings or your own clip that follows a
tracked point (a hand, the face, the body) of the main video.

How a render uses them (see project_render.py):

  1. For every frame of every `trackfx` clip, find which main-video clip is showing, the
     source time inside it, and so where the tracked point is in the SOURCE picture
     (tracking.py: gaps bridged, smoothed, fading out when lost).
  2. Map that point onto the finished 1080x1920 frame: through the main clip's fit/reframe
     and through any zoom effect that is active at that frame (`FrameMap`).
  3. Draw the effect for each frame with numpy on a black background at half size and write it
     as a lossless video (`prepare_layer`).
  4. The renderer adds that video on top of the picture with the "screen" blend (black = no
     change, light adds), so effects never darken the picture.

All drawing is procedural and deterministic (the same project renders the same pixels), and
local. Nothing here downloads or calls anything.
"""

import math
import random
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .errors import Cancelled, EditorError
from .project import clip_end, resolve_media_path
from .render import H, W
from .tracking import FINGERTIPS, Prepared, Track, pick_hand, resolve_sequence

SCALE = 0.5                     # the effect layer is drawn at half size, then scaled up
LW, LH = int(W * SCALE), int(H * SCALE)
DEFAULT_COLORS = {"glow": "#ffe08a", "spark": "#ffb347", "aura": "#58c8ff", "energy": "#7aa8ff",
                  "clip": "#ffffff"}
CLIP_WIDTH = 0.35               # an effect clip of size 1 is this wide (share of the frame width)
FACE_POINTS = ("face", "body")


def trackfx_clips(project):
    """Every tracked effect on a visible effect track: [(clip)], in start order."""
    clips = [c for t in project["tracks"] if t["kind"] == "effect" and not t.get("hidden")
             for c in t["clips"] if c["type"] == "trackfx"]
    return sorted(clips, key=lambda c: (c["start"], c["id"]))


def hex_rgb(color):
    color = (color or "#ffffff").lstrip("#")
    return np.array([int(color[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=np.float32)


def point_names(clip, track, t0, t1):
    """The tracked point names a clip follows (several for "fingertips")."""
    point = clip.get("point", "palm")
    if point in FACE_POINTS:
        return [point]
    hand = pick_hand(track, clip.get("hand", "any"), "index_tip" if point == "fingertips" else point,
                     t0, t1)
    side = hand.split("_", 1)[0]
    if point == "fingertips":
        return [f"{side}_{part}" for part in FINGERTIPS]
    return [f"{side}_{point}"]


# ---------------------------------------------------------------- where is the point?

@dataclass
class FrameInfo:
    media: dict
    source_time: float
    fit: str
    crop: tuple


class FrameMap:
    """Timeline frame -> (main clip, source time) and source position -> finished frame."""

    def __init__(self, segments, fps, zoom_layers):
        self.fps = fps
        self.spans = []
        for seg in segments:
            self.spans.append((seg.end_frame - seg.frames, seg.end_frame, seg))
        self.zoom_layers = zoom_layers        # [((amount, anchor, ease, t0), [(f0, f1)])]

    def info(self, f):
        for a, b, seg in self.spans:
            if a <= f < b:
                if seg.kind != "run" or seg.layout:
                    return None               # a still, a gap, or a split/picture-in-picture
                offset = f - a
                for s, count in seg.sources:
                    if offset < count:
                        t = s + (offset / self.fps) * (seg.speed if seg.speed != 1 else 1.0)
                        return FrameInfo(seg.media, t, seg.fit, seg.crop)
                    offset -= count
                return None
        return None

    @staticmethod
    def to_frame(info, u, v, s=0.0):
        """Source position (0-1) and size (share of the source width) -> 1080x1920 pixels:
        (x, y, size in pixels). Follows the main clip's fit and reframe."""
        mw, mh = info.media["width"], info.media["height"]
        if info.fit == "blur":
            k = min(W / mw, H / mh)
            sw, sh = mw * k, mh * k
            return u * sw + (W - sw) / 2, v * sh + (H - sh) / 2, s * sw
        zoom, cx, cy = info.crop
        tw, th = math.ceil(W * zoom / 2) * 2, math.ceil(H * zoom / 2) * 2
        k = max(tw / mw, th / mh)
        sw, sh = mw * k, mh * k
        return u * sw - (sw - W) * cx, v * sh - (sh - H) * cy, s * sw

    def zoomed(self, f, x, y, size):
        """The same point after the zoom effects active at frame f (same order as the render)."""
        t = f / self.fps
        for (amount, anchor, ease, t0), ranges in self.zoom_layers:
            if not any(a <= f < b for a, b in ranges):
                continue
            if ease > 0:
                z = 1 + (amount - 1) * min(1.0, max(0.0, (t - t0) / ease))
                zw, zh = math.trunc(W * z / 2) * 2, math.trunc(H * z / 2) * 2
                x, y = x * zw / W + (W - zw) / 2, y * zh / H + (H - zh) * anchor
                size *= zw / W
            else:
                x = (x - (W - W / amount) / 2) * amount
                y = (y - (H - H / amount) * anchor) * amount
                size *= amount
        return x, y, size


# ---------------------------------------------------------------- drawing

def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def blob(layer, cx, cy, sigma, color, amount):
    """Add a soft round light (gaussian) at (cx, cy) in layer pixels."""
    if amount <= 0.002 or sigma <= 0.2:
        return
    r = int(math.ceil(sigma * 3.2))
    x0, x1 = max(0, int(cx) - r), min(LW, int(cx) + r + 1)
    y0, y1 = max(0, int(cy) - r), min(LH, int(cy) + r + 1)
    if x1 <= x0 or y1 <= y0:
        return
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    g = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma * sigma))) * amount
    patch = layer[y0:y1, x0:x1]
    patch[:] = 1 - (1 - patch) * (1 - g[..., None] * color[None, None, :])


def ring(layer, cx, cy, radius, width, color, amount):
    """Add a thin glowing ring."""
    if amount <= 0.002 or radius <= 0.5:
        return
    r = int(math.ceil(radius + width * 3.2))
    x0, x1 = max(0, int(cx) - r), min(LW, int(cx) + r + 1)
    y0, y1 = max(0, int(cy) - r), min(LH, int(cy) + r + 1)
    if x1 <= x0 or y1 <= y0:
        return
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    g = np.exp(-(((d - radius) ** 2) / (2 * width * width))) * amount
    patch = layer[y0:y1, x0:x1]
    patch[:] = 1 - (1 - patch) * (1 - g[..., None] * color[None, None, :])


def draw_glow(layer, x, y, alpha, intensity, size, color, t, seed):
    """A bright core with a wide soft halo, flickering a little."""
    a = alpha * intensity
    if a <= 0:
        return
    flicker = 1 + 0.07 * math.sin(2 * math.pi * 7.0 * t + seed % 7) + 0.04 * math.sin(2 * math.pi * 13 * t)
    r = 46.0 * size * SCALE * (0.7 + 0.5 * intensity) * flicker
    hot = 0.55 * color + 0.45
    blob(layer, x, y, r * 2.6, color, 0.42 * a)          # halo
    blob(layer, x, y, r * 1.2, color, 0.8 * a)           # body
    blob(layer, x, y, r * 0.45, hot, 1.0 * a)            # white-hot core


def draw_energy(layer, x, y, alpha, intensity, size, color, t, seed):
    """A pulsing core with rings that expand and fade."""
    a = alpha * intensity
    if a <= 0:
        return
    r = 40.0 * size * SCALE
    blob(layer, x, y, r * 1.4, color, 0.55 * a)
    blob(layer, x, y, r * 0.5, 0.5 * color + 0.5, 0.95 * a)
    period = 0.9
    for k in range(3):
        phase = ((t / period) + k / 3.0) % 1.0
        ring(layer, x, y, r * (0.6 + 3.2 * phase), max(1.2, r * 0.09), color, 0.85 * a * (1 - phase) ** 1.5)


def draw_aura(layer, x, y, alpha, intensity, size, color, t, seed, width_px, tall):
    """A glowing outline around a face or a body, wobbling like a flame."""
    a = alpha * intensity
    if a <= 0:
        return
    rx = max(20.0, 0.58 * width_px * size)
    ry = rx * (1.45 if tall else 1.2)
    pad = int(max(rx, ry) * 1.9)
    x0, x1 = max(0, int(x) - pad), min(LW, int(x) + pad + 1)
    y0, y1 = max(0, int(y) - pad), min(LH, int(y) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        return
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dx, dy = (xs - x) / rx, (ys - y) / ry
    d = np.sqrt(dx * dx + dy * dy)
    theta = np.arctan2(dy, dx)
    wobble = (1 + 0.05 * np.sin(3 * theta + 2 * math.pi * 0.8 * t + seed % 5)
              + 0.03 * np.sin(5 * theta - 2 * math.pi * 1.3 * t)).astype(np.float32)
    edge = np.exp(-(((d / wobble) - 1.0) ** 2) / (2 * 0.2 ** 2))           # bright at the outline
    fill = 0.1 * np.exp(-(d * d) / 0.8)                                   # a faint glow inside
    g = np.clip((0.9 * edge + fill) * a, 0, 1)
    patch = layer[y0:y1, x0:x1]
    patch[:] = 1 - (1 - patch) * (1 - g[..., None] * color[None, None, :])


class Sparks:
    """Particles thrown off the point; each is placed from where the point was when it was
    emitted, so the trail follows the motion. Deterministic per clip."""

    LIFE = 0.55

    def __init__(self, clip, fps):
        self.fps = fps
        self.seed = zlib.crc32(clip["id"].encode())
        self.emitted = []            # per frame: [(x, y, alpha)] for the emitter(s)

    def add_frame(self, emitters):
        self.emitted.append(emitters)

    def draw(self, layer, k, intensity, size, color):
        life_frames = int(self.LIFE * self.fps)
        per_second = 70 + 170 * intensity
        for e in range(max(0, k - life_frames), k + 1):
            for ei, (ex, ey, ea) in enumerate(self.emitted[e]):
                if ea <= 0.01:
                    continue
                rng = random.Random(self.seed * 1000003 + e * 31 + ei)
                n = per_second * ea / self.fps
                count = int(n) + (1 if rng.random() < n - int(n) else 0)
                for _ in range(count):
                    angle = rng.uniform(0, 2 * math.pi)
                    speed = rng.uniform(160, 520) * size * SCALE
                    age = (k - e) / self.fps
                    life = rng.uniform(0.6, 1.0) * self.LIFE
                    if age >= life:
                        continue
                    px = ex + math.cos(angle) * speed * age
                    py = ey + math.sin(angle) * speed * age - 40 * SCALE * age     # drift up
                    fade = (1 - age / life) ** 1.6
                    blob(layer, px, py, rng.uniform(1.2, 2.6) * max(0.6, size) , color,
                         min(1.0, 1.15 * ea * fade * (0.6 + 0.4 * intensity)))


def resize_rgb(frame, width):
    """Resize a float RGB(A) frame to `width` pixels wide, keeping its shape."""
    from PIL import Image
    h, w = frame.shape[:2]
    height = max(1, int(round(h * width / w)))
    img = Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8))
    return np.asarray(img.resize((max(1, int(width)), height), Image.BILINEAR), dtype=np.float32) / 255.0


def paste_screen(layer, frame, cx, cy, amount, alpha_channel=None, tint=None):
    """Screen-blend `frame` (h x w x 3, 0-1) onto the layer, centred at (cx, cy)."""
    h, w = frame.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    dx1, dy1 = min(LW, x0 + w), min(LH, y0 + h)
    if dx1 <= dx0 or dy1 <= dy0:
        return
    src = frame[sy0:sy0 + (dy1 - dy0), sx0:sx0 + (dx1 - dx0)] * amount
    if alpha_channel is not None:
        src = src * alpha_channel[sy0:sy0 + (dy1 - dy0), sx0:sx0 + (dx1 - dx0), None]
    if tint is not None:
        src = src * tint[None, None, :]
    patch = layer[dy0:dy1, dx0:dx1]
    patch[:] = 1 - (1 - patch) * (1 - np.clip(src, 0, 1))


def decode_effect_clip(path, seconds, fps, alpha, width=256):
    """The frames of a user's effect clip: a list of float arrays (h x w x 3, or x4 with alpha)."""
    from .ffmpeg_tools import probe
    info = probe(path)
    w = width
    h = max(2, int(round(info["height"] * w / info["width"] / 2) * 2))
    pix = "rgba" if alpha else "rgb24"
    chans = 4 if alpha else 3
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-t", f"{seconds:.4f}", "-an",
           "-vf", f"fps={fps:g},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", pix, "-"]
    raw = subprocess.run(cmd, capture_output=True, check=False)
    if raw.returncode != 0 and not raw.stdout:
        raise EditorError(f"Could not read the effect clip {Path(path).name}: "
                          f"{raw.stderr.decode(errors='replace')[-200:]}")
    size = w * h * chans
    return [np.frombuffer(raw.stdout[i:i + size], np.uint8).reshape(h, w, chans).astype(np.float32) / 255.0
            for i in range(0, len(raw.stdout) - size + 1, size)]


# ---------------------------------------------------------------- per clip

def clip_path(project, media, base_dir, clip):
    return resolve_media_path(media[clip["media"]], base_dir)


def envelope(k, n, fps, fade_in, fade_out):
    """Clip-level fade: 0 -> 1 over fade_in, 1 -> 0 over fade_out (seconds)."""
    a = 1.0
    if fade_in > 0:
        a = min(a, (k + 0.5) / (fade_in * fps))
    if fade_out > 0:
        a = min(a, (n - k - 0.5) / (fade_out * fps))
    return smoothstep(a)


def resolve_clip(project, fmap, tracks, clip, fps, f0, f1):
    """Per frame, for each followed point: where it is on the finished frame, how visible and
    how big. Returns (names or None, list per frame of [(x, y, alpha, size_px)])."""
    n = f1 - f0
    infos = [fmap.info(f) for f in range(f0, f1)]
    first = next((i for i in infos if i is not None), None)
    if first is None:
        return [[] for _ in range(n)]
    media_id = first.media["id"]
    track = tracks.get(media_id)
    if track is None:
        return [[] for _ in range(n)]
    times = [i.source_time for i in infos if i is not None]
    names = point_names(clip, track, min(times), max(times))
    out = [[] for _ in range(n)]
    for name in names:
        items = []
        for info in infos:
            tr = tracks.get(info.media["id"]) if info is not None else None
            pt = tr.points.get(name) if tr is not None else None
            prep = None
            if pt is not None:
                key = (info.media["id"], name, round(float(clip.get("smooth", 0.5)), 3))
                prep = PREPARED.get(key)
                if prep is None:
                    prep = PREPARED[key] = Prepared(pt, tr.fps, tr.start, float(clip.get("smooth", 0.5)))
            items.append((prep, info.source_time if info is not None else 0.0))
        res = resolve_sequence(items, 1.0 / fps)
        for k in range(n):
            info = infos[k]
            if info is None:
                out[k].append((0.0, 0.0, 0.0, 0.0))
                continue
            x, y, size = fmap.to_frame(info, res.x[k], res.y[k], res.size[k])
            x, y, size = fmap.zoomed(f0 + k, x, y, size)
            out[k].append((x * SCALE, y * SCALE, res.alpha[k], size * SCALE))
    return out


PREPARED = {}          # (media id, point, smooth) -> Prepared; cleared at the start of each render


def draw_clip(layer, clip, k, n, fps, points, sparks, frames):
    """Draw frame k of one tracked effect onto the layer."""
    effect = clip["effect"]
    intensity = float(clip.get("intensity", 0.8))
    size = float(clip.get("size", 1.0))
    color = hex_rgb(clip.get("color") or DEFAULT_COLORS[effect])
    env = envelope(k, n, fps, float(clip.get("fade_in", 0.15)), float(clip.get("fade_out", 0.2)))
    seed = zlib.crc32(clip["id"].encode())
    t = (clip["start"] * fps + k) / fps
    for (x, y, alpha, width) in points:
        a = alpha * env
        if a <= 0:
            continue
        if effect == "glow":
            draw_glow(layer, x, y, a, intensity, size, color, t, seed)
        elif effect == "energy":
            draw_energy(layer, x, y, a, intensity, size, color, t, seed)
        elif effect == "aura":
            tall = clip.get("point") == "body"
            draw_aura(layer, x, y, a, intensity, size, color, t, seed, width or 300 * SCALE, tall)
        elif effect == "clip" and frames and k < len(frames):
            frame = frames[k]
            base = CLIP_WIDTH * LW * size
            tint = color if clip.get("color") else None
            if clip.get("blend", "screen") == "alpha" and frame.shape[2] == 4:
                full = resize_rgba(frame, base)
                paste_screen(layer, full[..., :3], x, y, intensity * a, alpha_channel=full[..., 3],
                             tint=tint)
            else:
                paste_screen(layer, resize_rgb(frame[..., :3], base), x, y, intensity * a, tint=tint)
    if effect == "spark":
        sparks.add_frame([(x, y, alpha * env) for (x, y, alpha, _w) in points])
        sparks.draw(layer, k, intensity, size, color)


def resize_rgba(frame, width):
    """Resize an RGBA float frame (straight alpha) to `width` pixels wide."""
    from PIL import Image
    h, w = frame.shape[:2]
    height = max(1, int(round(h * width / w)))
    img = Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8), "RGBA")
    return np.asarray(img.resize((max(1, int(width)), height), Image.BILINEAR), dtype=np.float32) / 255.0


# ---------------------------------------------------------------- the layer video

def tracks_of(project):
    return {mid: Track.from_json(t) for mid, t in (project.get("tracking") or {}).items()}


def prepare_layer(project, media, base_dir, fps, total_frames, segments, zoom_layers, work_dir,
                  last_frame=None, cancel=None):
    """Draw every tracked effect to one lossless black-background video in `work_dir`.

    Returns {"path", "f0", "f1"} (the timeline frames the video covers), or None if there is
    nothing to draw. `last_frame`: stop after this frame (for a single-frame render).
    """
    clips = trackfx_clips(project)
    spans = []
    for c in clips:
        f0 = int(round(c["start"] * fps + 1e-9))
        f1 = min(total_frames, int(round(clip_end(c) * fps + 1e-9)))
        draw_to = min(f1, last_frame + 1) if last_frame is not None else f1   # a single frame
        if draw_to > f0:
            spans.append((c, f0, f1, draw_to))
    if not spans:
        return None
    PREPARED.clear()
    lo, hi = min(s[1] for s in spans), max(s[3] for s in spans)
    fmap = FrameMap(segments, fps, zoom_layers)
    tracks = tracks_of(project)
    drawn = []
    for c, f0, f1, draw_to in spans:
        points = resolve_clip(project, fmap, tracks, c, fps, f0, draw_to)
        frames = None
        if c["effect"] == "clip":
            path = clip_path(project, media, base_dir, c)
            frames = decode_effect_clip(path, (draw_to - f0) / fps, fps, c.get("blend") == "alpha")
        drawn.append((c, f0, f1, draw_to, points, frames, Sparks(c, fps)))
    path = Path(work_dir) / "trackfx.mkv"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{LW}x{LH}",
           "-r", f"{fps:g}", "-i", "-", "-c:v", "ffv1", "-pix_fmt", "gbrp", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in range(lo, hi):
            if cancel is not None and cancel.is_set():
                raise Cancelled("Cancelled.")
            layer = np.zeros((LH, LW, 3), dtype=np.float32)
            for c, f0, f1, draw_to, points, frames, sparks in drawn:
                if f0 <= f < draw_to:
                    draw_clip(layer, c, f - f0, f1 - f0, fps, points[f - f0], sparks, frames)
            proc.stdin.write((np.clip(layer, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes())
        proc.stdin.close()
        err = proc.stderr.read()
        if proc.wait() != 0:
            raise EditorError(f"Could not write the tracked effects: {err.decode(errors='replace')[-300:]}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return {"path": str(path), "f0": lo, "f1": hi}
