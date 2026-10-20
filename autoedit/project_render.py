"""Render a Project (see project.py) to the final MP4, or one exact frame to PNG, with FFmpeg.

Picture:  main video track (black where empty) -> zoom effects -> colour grades
          -> overlay tracks (photos, logo) -> captions -> export size
Sound:    main video track + original/voice-over tracks -> loudness (optional)
          -> + music and sound-effect tracks -> limiter

Main-track clips that play one source file forwards without gaps are rendered as one
"run": a single decode that keeps only the wanted frames (FFmpeg `select`), like the
original editor. A new run starts when the source, direction, volume or framing changes,
and the runs are joined with `concat`.
"""

import math
import os
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import PROJECT_DIR
from .captions import ass_document, build_events, style_lines
from .errors import EditorError
from .ffmpeg_tools import check_ffmpeg, filter_script_args, run_ffmpeg_progress
from .grades import grade_filter
from .previews import copy_fonts
from .project import (check_project, clip_end, media_by_id, resolve_media_path,
                      timeline_duration)
from .render import AUDIO_RATE, H, W, fill, layout_chain, pop_scale_expression
from .styles import get_style
from .words import Word

DEFAULT_EXPORT = {"crf": 20, "encoder_speed": "medium", "audio_bitrate": "192k", "height": H}
DEFAULT_ANCHOR_Y = 0.4
DIALOG_ROLES = ("original", "voiceover")
DEFAULT_CROP = {"zoom": 1.0, "x": 0.5, "y": 0.5}


def crop_of(clip):
    """The clip's reframe as (zoom, x, y); (1, 0.5, 0.5) = fill the frame, centred."""
    c = {**DEFAULT_CROP, **(clip.get("crop") or {})}
    return (float(c["zoom"]), float(c["x"]), float(c["y"]))


def fill_chain(src, out, fps, crop):
    """Fill the 1080x1920 frame from `src`, zoomed and positioned by `crop` (zoom, x, y)."""
    if crop == (1.0, 0.5, 0.5):
        return [f"[{src}]{fill(fps)}[{out}]"]
    zoom, x, y = crop
    return [f"[{src}]setpts=PTS-STARTPTS,fps={fps},scale={math.ceil(W * zoom / 2) * 2}:"
            f"{math.ceil(H * zoom / 2) * 2}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:(iw-ow)*{x:g}:(ih-oh)*{y:g},setsar=1[{out}]"]


def atempo_chain(speed):
    """atempo filters for a speed of 0.25-4 (each atempo stage handles 0.5-2)."""
    parts, s = [], float(speed)
    while s > 2.0 + 1e-9:
        parts.append("atempo=2")
        s /= 2.0
    while s < 0.5 - 1e-9:
        parts.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-9:
        parts.append(f"atempo={s:.6g}")
    return ",".join(parts)


def fades_chain(fade_in, fade_out, length):
    """afade filters for a piece of sound `length` seconds long (empty if no fades)."""
    chain = ""
    if fade_in:
        chain += f",afade=t=in:st=0:d={fade_in:g}"
    if fade_out:
        chain += f",afade=t=out:st={max(0.0, length - fade_out):.4f}:d={fade_out:g}"
    return chain


def frame_index(seconds, fps):
    """The frame a timeline time falls on, rounding to the nearest frame edge."""
    return int(math.floor(seconds * fps + 0.5 + 1e-9))


def frames_expression(ranges, fps):
    """FFmpeg expression true on frames f0 <= n < f1 of any (f0, f1) range (by time t)."""
    half = 0.5 / fps
    return "+".join(f"gte(t,{f0 / fps - half:.4f})*lt(t,{f1 / fps - half:.4f})"
                    for f0, f1 in ranges) or "0"


def ffmpeg_color(hex_color):
    return "0x" + hex_color.lstrip("#")


@dataclass
class Segment:
    """A stretch of the main track: a run of one video, a still image, or empty (gap)."""
    kind: str                      # "run", "image" or "gap"
    frames: int = 0
    media: dict = None
    fit: str = "fill"
    layout: dict = None
    volume: float = 1.0
    sources: list = field(default_factory=list)   # [(source start s, frame count)]
    end_frame: int = 0             # timeline frame where the segment ends
    speed: float = 1.0
    crop: tuple = (1.0, 0.5, 0.5)
    fades: tuple = (0.0, 0.0)      # sound fade in / out (seconds)

    def source_end(self, fps):
        s, n = self.sources[-1]
        return s + n / fps


class Graph:
    def __init__(self):
        self.inputs = []
        self.lines = []
        self.count = 0

    def add_input(self, args):
        self.inputs += [str(a) for a in args]
        self.count += 1
        return self.count - 1

    def add(self, *lines):
        self.lines += lines


# ---------------------------------------------------------------- main track

def main_segments(project, media, fps, total_frames):
    track = next((t for t in project["tracks"] if t["kind"] == "video"), None)
    clips = sorted(track["clips"], key=lambda c: c["start"]) \
        if track and not track.get("hidden") else []
    muted = bool(track and track.get("muted"))
    segments, cursor = [], 0
    for clip in clips:
        f0 = max(frame_index(clip["start"], fps), cursor)
        f1 = min(frame_index(clip_end(clip), fps), total_frames)
        if f1 <= f0:
            continue
        if f0 > cursor:
            segments.append(Segment("gap", frames=f0 - cursor, end_frame=f0))
        n = f1 - f0
        m = media[clip["media"]]
        fit = clip.get("fit", "fill")
        crop = crop_of(clip)
        if clip["type"] == "image":
            segments.append(Segment("image", frames=n, media=m, fit=fit, end_frame=f1,
                                    crop=crop))
        else:
            speed = float(clip.get("speed", 1.0))
            fades = (float(clip.get("fade_in", 0.0)), float(clip.get("fade_out", 0.0)))
            # A sped-up/slowed clip seeks to its exact 'in' (no frame snapping needed).
            source = clip["in"] if speed != 1 else frame_index(clip["in"], fps) / fps
            volume = 0.0 if muted else float(clip.get("volume", 1.0))
            layout = clip.get("layout")
            last = segments[-1] if segments else None
            plain = speed == 1 and fades == (0.0, 0.0)
            if (plain and last is not None and last.kind == "run" and last.media is m
                    and last.speed == 1 and last.fades == (0.0, 0.0)
                    and last.fit == fit and last.layout == layout and last.volume == volume
                    and last.crop == crop
                    and last.end_frame == f0 and source >= last.source_end(fps) - 1e-6):
                last.sources.append((source, n))
                last.frames += n
                last.end_frame = f1
            else:
                segments.append(Segment("run", frames=n, media=m, fit=fit, layout=layout,
                                        volume=volume, sources=[(source, n)], end_frame=f1,
                                        speed=speed, crop=crop, fades=fades))
        cursor = f1
    if cursor < total_frames:
        segments.append(Segment("gap", frames=total_frames - cursor, end_frame=total_frames))
    return segments


def screen_seek(layout, source, length):
    """Input options that start the other video of a layout where it should be (its offset)."""
    at = source + float(layout.get("offset", 0.0))
    args = ["-ss", f"{at:.4f}"] if at > 0 else []
    if length is not None:
        args += ["-t", f"{length:.4f}"]
    return args


def screen_delay(layout, source):
    """Filters that hold back the other video when it starts later than this clip (negative offset)."""
    at = source + float(layout.get("offset", 0.0))
    return f"tpad=start_duration={-at:.4f}:start_mode=clone," if at < 0 else ""


def add_main_track(graph, project, media, base_dir, fps, total_frames, with_audio):
    """Add the main track to the graph. Returns the (video, audio) labels."""
    block = AUDIO_RATE // fps
    background = ffmpeg_color(project["settings"].get("background", "#000000"))
    segments = main_segments(project, media, fps, total_frames)
    half = 0.5 / fps
    labels = []
    for k, seg in enumerate(segments):
        v, a = f"mv{k}", f"ma{k}"
        n, samples = seg.frames, seg.frames * block
        exact = f"tpad=stop_mode=clone:stop=-1,trim=end_frame={n}"
        has_sound = False
        if seg.kind == "gap":
            graph.add(f"color=c={background}:s={W}x{H}:r={fps},setsar=1,trim=end_frame={n}[{v}]")
        elif seg.kind == "image":
            idx = graph.add_input(["-loop", "1", "-framerate", fps, "-t", f"{(n + 1) / fps:.4f}",
                                   "-i", resolve_media_path(seg.media, base_dir)])
            if seg.fit == "blur":
                graph.add(*layout_chain("screen", f"{idx}:v", None, f"m{k}pic", fps, f"m{k}"))
            else:
                graph.add(*fill_chain(f"{idx}:v", f"m{k}pic", fps, seg.crop))
            graph.add(f"[m{k}pic]{exact}[{v}]")
        elif seg.speed != 1:
            # Sped up or slowed down: seek to 'in', stretch the timestamps, then resample to
            # the project's frame rate. Sound: atempo keeps the pitch.
            source, _n = seg.sources[0]
            length = n / fps * seg.speed + 2 / fps        # a little extra, trimmed below
            seek = ["-ss", f"{source:.4f}", "-t", f"{length:.4f}"]
            idx = graph.add_input([*seek, "-i", resolve_media_path(seg.media, base_dir)])
            graph.add(f"[{idx}:v]setpts=(PTS-STARTPTS)/{seg.speed:g}[m{k}spd]")
            screen = None
            if seg.layout:
                mode = seg.layout["type"]
                sidx = graph.add_input([*screen_seek(seg.layout, source, length), "-i", resolve_media_path(
                    media[seg.layout["screen"]], base_dir)])
                graph.add(f"[{sidx}:v]{screen_delay(seg.layout, source)}setpts=(PTS-STARTPTS)/{seg.speed:g}"
                          f"[m{k}sspd]")
                screen = f"m{k}sspd"
                graph.add(*layout_chain(mode, f"m{k}spd", screen, f"m{k}pic", fps, f"m{k}", seg.layout))
            elif seg.fit == "blur":
                graph.add(*layout_chain("screen", f"m{k}spd", None, f"m{k}pic", fps, f"m{k}"))
            else:
                graph.add(*fill_chain(f"m{k}spd", f"m{k}pic", fps, seg.crop))
            graph.add(f"[m{k}pic]{exact}[{v}]")
            if with_audio and seg.media.get("has_audio", True) and seg.volume > 0:
                has_sound = True
                volume = f",volume={seg.volume:g}" if seg.volume != 1 else ""
                graph.add(
                    f"[{idx}:a]asetpts=PTS-STARTPTS,aresample={AUDIO_RATE},"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo,{atempo_chain(seg.speed)}"
                    f"{volume},apad=whole_len={samples},atrim=end_sample={samples}"
                    f"{fades_chain(*seg.fades, n / fps)}[{a}]")
        else:
            idx = graph.add_input(["-i", resolve_media_path(seg.media, base_dir)])
            screen = None
            if seg.layout:
                mode = seg.layout["type"]
                sidx = graph.add_input([*screen_seek(seg.layout, 0.0, None), "-i",
                                        resolve_media_path(media[seg.layout["screen"]], base_dir)])
                screen = f"{sidx}:v"
                delay = screen_delay(seg.layout, 0.0)
                if delay:
                    graph.add(f"[{screen}]{delay.rstrip(',')}[m{k}sdel]")
                    screen = f"m{k}sdel"
            else:
                mode = "screen" if seg.fit == "blur" else "face"
            keep = "+".join(f"gte(t,{s - half:.4f})*lt(t,{s + c / fps - half:.4f})"
                            for s, c in seg.sources)
            if mode == "face":
                graph.add(*fill_chain(f"{idx}:v", f"m{k}pic", fps, seg.crop))
            else:
                graph.add(*layout_chain(mode, f"{idx}:v", screen, f"m{k}pic", fps, f"m{k}",
                                        seg.layout))
            graph.add(f"[m{k}pic]select='{keep}',setpts='round(N/{fps}/TB)',{exact}[{v}]")
            if with_audio and seg.media.get("has_audio", True) and seg.volume > 0:
                has_sound = True
                volume = f",volume={seg.volume:g}" if seg.volume != 1 else ""
                graph.add(
                    f"[{idx}:a]asetpts=PTS-STARTPTS,aresample={AUDIO_RATE},"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"asetnsamples=n={block}:p=1,aselect='{keep}',asetpts='round(N/SR/TB)'{volume},"
                    f"apad=whole_len={samples},atrim=end_sample={samples}"
                    f"{fades_chain(*seg.fades, n / fps)}[{a}]")
        if with_audio and not has_sound:
            graph.add(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=end_sample={samples},"
                      f"aformat=sample_fmts=fltp:channel_layouts=stereo[{a}]")
        labels.append((v, a))

    if len(labels) == 1:
        return labels[0] if with_audio else (labels[0][0], None)
    if with_audio:
        joined = "".join(f"[{v}][{a}]" for v, a in labels)
        graph.add(f"{joined}concat=n={len(labels)}:v=1:a=1[maincat][mainaudio]")
        graph.add(f"[maincat]fps={fps}[mainvideo]")
        return "mainvideo", "mainaudio"
    joined = "".join(f"[{v}]" for v, _a in labels)
    graph.add(f"{joined}concat=n={len(labels)}:v=1:a=0[maincat]", f"[maincat]fps={fps}[mainvideo]")
    return "mainvideo", None


# ---------------------------------------------------------------- picture effects

def visible_tracks(project, kind):
    return [t for t in project["tracks"] if t["kind"] == kind and not t.get("hidden")]


def clip_frames(clip, fps):
    return frame_index(clip["start"], fps), frame_index(clip_end(clip), fps)


def effect_layers(project, fps, clip_type, key):
    """[(key value, [(f0, f1)])] in track order; one layer per distinct value per track."""
    layers = []
    for track in visible_tracks(project, "effect"):
        per_track = {}
        for clip in sorted(track["clips"], key=lambda c: c["start"]):
            if clip["type"] != clip_type:
                continue
            f0, f1 = clip_frames(clip, fps)
            if f1 > f0:
                per_track.setdefault(key(clip), []).append((f0, f1))
        layers += list(per_track.items())
    return layers


def zoom_layers(project, fps):
    """[((amount, anchor_y, ease, start, from, smooth), [(frame, frame)])]: the zoom layers, in
    render order. `from` (the zoom when an eased zoom starts) is 1 unless the clip says otherwise:
    from 1.3 to amount 1 is a smooth zoom-out."""
    def key(c):
        eased = bool(c.get("ease"))
        return (float(c["amount"]), float(c.get("anchor_y", DEFAULT_ANCHOR_Y)), float(c.get("ease", 0)),
                c["start"] if eased else 0, float(c.get("from", 1.0)) if eased else 1.0,
                bool(c.get("smooth")) if eased else False)
    layers = effect_layers(project, fps, "zoom", key)
    return [(k, r) for k, r in layers if max(k[0], k[4]) > 1.0]


def zoom_progress(t, t0, ease, smooth):
    """0..1 progress of an eased zoom at time t (Python twin of zoom_expression)."""
    x = min(1.0, max(0.0, (t - t0) / ease))
    return x * x * (3 - 2 * x) if smooth else x


def zoom_factor(amount, ease, t0, start, smooth, t):
    return start + (amount - start) * zoom_progress(t, t0, ease, smooth)


def zoom_expression(amount, ease, t0, start, smooth):
    """FFmpeg expression (in t) of the zoom factor of an eased zoom."""
    x = f"min(1,max(0,(t-{t0:.4f})/{ease:g}))"
    curve = f"({x})*({x})*(3-2*({x}))" if smooth else x
    return f"({start:g}+{amount - start:g}*{curve})"


def add_zooms(graph, current, project, fps):
    """Zoom effects. A plain zoom (punch-in) crops at once; one with `ease` grows smoothly
    from 100% to its amount over `ease` seconds, then holds."""
    layers = zoom_layers(project, fps)
    if not layers:
        return current
    labels = [f"zsrc{i}" for i in range(len(layers) + 1)]
    graph.add(f"[{current}]split={len(labels)}" + "".join(f"[{l}]" for l in labels))
    current = labels[0]
    for i, ((amount, anchor, ease, t0, start, smooth), ranges) in enumerate(layers, start=1):
        if ease > 0:
            # Grow (or shrink) from `start` (100% unless set) to `amount` over `ease` seconds
            # (t = timeline time), keeping the 1080x1920 window centred horizontally and at
            # `anchor` vertically. The changing picture is placed with overlay (its x/y follow
            # each frame's size; a crop after a size-changing scale would keep using the first
            # frame's size).
            z = zoom_expression(amount, ease, t0, start, smooth)
            graph.add(f"[{labels[i]}]scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':"
                      f"eval=frame,setsar=1[zoomed{i}]",
                      f"[{current}][zoomed{i}]overlay=x='(W-w)/2':y='(H-h)*{anchor:g}':"
                      f"eval=frame:enable='{frames_expression(ranges, fps)}'[zoomout{i}]")
            current = f"zoomout{i}"
            continue
        graph.add(f"[{labels[i]}]crop=w=iw/{amount:g}:h=ih/{amount:g}:x=(iw-ow)/2:"
                  f"y=(ih-oh)*{anchor:g},scale={W}:{H},setsar=1[zoomed{i}]",
                  f"[{current}][zoomed{i}]overlay=0:0:enable='{frames_expression(ranges, fps)}'"
                  f"[zoomout{i}]")
        current = f"zoomout{i}"
    return current


def graded(graph, src, out, name, intensity, tag):
    """`src` with a colour grade at `intensity` (1 = full: the grade alone; 0.5 = halfway)."""
    chain = grade_filter(name) or "null"
    if intensity >= 1 or chain == "null":
        graph.add(f"[{src}]{chain}[{out}]")
    elif intensity <= 0:
        graph.add(f"[{src}]null[{out}]")
    else:
        graph.add(f"[{src}]split[{tag}o][{tag}g]", f"[{tag}g]{chain}[{tag}c]",
                  f"[{tag}o][{tag}c]blend=all_mode=normal:all_opacity={intensity:g}[{out}]")


def add_grades(graph, current, project, fps, total_frames):
    layers = effect_layers(project, fps, "grade",
                           lambda c: (c["grade"], float(c.get("intensity", 1.0))))
    if not layers:
        return current
    (first_name, first_k), first_ranges = layers[0]
    if first_ranges[0][0] <= 0 and first_ranges[-1][1] >= total_frames and len(first_ranges) == 1:
        layers = layers[1:]                            # covers everything: apply directly
        graded(graph, current, "graded0", first_name, first_k, "gb")
    else:
        graph.add(f"[{current}]null[graded0]")
    current = "graded0"
    if not layers:
        return current
    labels = [f"gsrc{i}" for i in range(len(layers) + 1)]
    graph.add(f"[{current}]split={len(labels)}" + "".join(f"[{l}]" for l in labels))
    current = labels[0]
    for i, ((name, k), ranges) in enumerate(layers, start=1):
        graded(graph, labels[i], f"gradealt{i}", name, k, f"g{i}")
        graph.add(f"[{current}][gradealt{i}]overlay=0:0:enable='{frames_expression(ranges, fps)}'"
                  f"[graded{i}]")
        current = f"graded{i}"
    return current


def wipe_expression(t0, sweep, stop, direction, divider):
    """FFmpeg `blend` expression for a before/after wipe. A = the picture as it was (first input),
    B = the graded picture. The divider travels from one edge to `stop` (a fraction of the frame)
    over `sweep` seconds, easing out, and stays there; the graded side is the one it has passed."""
    horizontal = direction in ("right", "left")
    axis, extent = ("X", "W") if horizontal else ("Y", "H")
    travel = f"{extent}*{stop:g}*ld(0)"
    pos = travel if direction in ("right", "down") else f"{extent}-{travel}"
    graded = f"lt({axis},ld(1))" if direction in ("right", "down") else f"gt({axis},ld(1))"
    pick = f"if({graded},B,A)"
    if divider:
        pick = f"if(gt(ld(0),0.001)*lt(abs({axis}-ld(1)),2.5),255,{pick})"
    return (f"st(0,1-pow(1-clip((T-{t0:.4f})/{sweep:g},0,1),3));st(1,{pos});{pick}")


def add_wipes(graph, current, project, fps):
    """Before/after wipes: one side of a moving divider shows a colour grade (see wipe_expression)."""
    k = 0
    for track in visible_tracks(project, "effect"):
        for clip in sorted(track["clips"], key=lambda c: c["start"]):
            if clip["type"] != "wipe":
                continue
            f0, f1 = clip_frames(clip, fps)
            if f1 <= f0:
                continue
            expr = wipe_expression(f0 / fps, float(clip.get("sweep", 0.8)),
                                   float(clip.get("stop", 0.5)), clip.get("direction", "right"),
                                   bool(clip.get("divider", True)))
            on = f"enable='{frames_expression([(f0, f1)], fps)}'"
            graph.add(f"[{current}]split[wipea{k}][wipeb{k}]")
            graded(graph, f"wipeb{k}", f"wipeg{k}", clip["grade"], float(clip.get("intensity", 1.0)),
                   f"wp{k}")
            # blend does not use RGB values the way "screen" does, but gbrp keeps every plane the
            # same size, so X / Y / W / H mean the same thing in all three planes
            graph.add(f"[wipea{k}]format=gbrp[wipeo{k}]", f"[wipeg{k}]format=gbrp[wipef{k}]",
                      f"[wipeo{k}][wipef{k}]blend=all_expr='{expr}':{on}[wipe{k}]")
            current = f"wipe{k}"
            k += 1
    return current


def triangle(t0, d):
    """0 at the start and end of [t0, t0 + d], 1 in the middle (FFmpeg expression in t)."""
    return f"max(0,1-abs(2*(t-{t0 + d / 2:.4f})/{d:.4f}))"


def add_fx(graph, current, project, fps):
    """Moment effects on the main picture (also used as transitions on a cut)."""
    k = 0
    for track in visible_tracks(project, "effect"):
        for clip in sorted(track["clips"], key=lambda c: c["start"]):
            if clip["type"] != "fx":
                continue
            f0, f1 = clip_frames(clip, fps)
            if f1 <= f0:
                continue
            t0, d = f0 / fps, (f1 - f0) / fps
            i = float(clip.get("intensity", 0.6))
            on = f"enable='{frames_expression([(f0, f1)], fps)}'"
            out = f"fx{k}"
            effect = clip["effect"]
            # eq's brightness only moves the luma, so the colour fades out with it (else a dip
            # to "black" stays dark red).
            if effect in ("flash", "dip"):
                tri = triangle(t0, d)
                amount = 0.25 + 0.75 * i if effect == "flash" else -(0.3 + 0.7 * i)
                graph.add(f"[{current}]eq=brightness='{amount:g}*{tri}':"
                          f"saturation='1-{i:g}*{tri}':eval=frame:{on}[{out}]")
            elif effect == "glitch":
                shift = int(round(6 + 34 * i))
                graph.add(f"[{current}]rgbashift=rh={shift}:bh=-{shift}:gv={shift // 3}:{on},"
                          f"noise=alls={int(10 + 30 * i)}:allf=t:{on}[{out}]")
            elif effect == "bw":
                # the colour drains to black and white over the first 35%, stays, and comes
                # back over the last 35% (a B&W transition on a cut)
                ramp = max(min(float(clip["ramp"]), d / 2) if clip.get("ramp") is not None else d * 0.35, 1 / fps)
                held = f"min(1,max(0,min((t-{t0:.4f})/{ramp:.4f},({t0 + d:.4f}-t)/{ramp:.4f})))"
                graph.add(f"[{current}]eq=saturation='1-{min(1.0, 0.4 + 0.6 * i):g}*{held}':"
                          f"eval=frame:{on}[{out}]")
            elif effect == "whip":
                graph.add(f"[{current}]gblur=sigma={8 + 52 * i:g}:sigmaV=0:steps=2:{on}[{out}]")
            elif effect == "shake":
                a = int(round(8 + 40 * i))
                graph.add(f"[{current}]split[fxa{k}][fxb{k}]",
                          f"[fxb{k}]crop=w=iw-{2 * a}:h=ih-{2 * a}:x='{a}+{a}*sin(n*1.9)':"
                          f"y='{a}+{a}*cos(n*2.7)',scale={W}:{H},setsar=1[fxs{k}]",
                          f"[fxa{k}][fxs{k}]overlay=0:0:{on}[{out}]")
            else:
                continue
            current = out
            k += 1
    return current


def envelope_expression(t0, d, fade, var="t"):
    """FFmpeg expression: 0 -> 1 over `fade` seconds from t0, 1, then -> 0 over the last `fade`
    seconds of [t0, t0 + d] (1 throughout when fade is 0). Smoothstep-eased."""
    if fade <= 0:
        return "1"
    f = min(fade, d / 2)
    x = f"min(1,max(0,min(({var}-{t0:.4f})/{f:.4f},({t0 + d:.4f}-{var})/{f:.4f})))"
    return f"(({x})*({x})*(3-2*({x})))"


def add_dims(graph, current, project, fps):
    """Background dimming: the picture gets darker (and optionally blurred) so a card on top
    stands out. The darkened copy is mixed in with an eased fade (blend, per frame)."""
    k = 0
    for track in visible_tracks(project, "effect"):
        for clip in sorted(track["clips"], key=lambda c: c["start"]):
            if clip["type"] != "dim":
                continue
            f0, f1 = clip_frames(clip, fps)
            if f1 <= f0:
                continue
            t0, d = f0 / fps, (f1 - f0) / fps
            amount = float(clip.get("amount", 0.45))
            blur = float(clip.get("blur", 0))
            keep = 1 - amount
            dark = (f"lutyuv=y='val*{keep:g}':u='128+(val-128)*{keep:g}':v='128+(val-128)*{keep:g}'")
            if blur > 0:
                dark = f"gblur=sigma={blur / 2:g}:steps=2," + dark
            mix = envelope_expression(t0, d, float(clip.get("fade", 0.3)), var="T")
            on = f"enable='{frames_expression([(f0, f1)], fps)}'"
            graph.add(f"[{current}]split[dima{k}][dimb{k}]", f"[dimb{k}]{dark}[dimd{k}]",
                      f"[dima{k}][dimd{k}]blend=all_expr='A+(B-A)*{mix}':{on}[dim{k}]")
            current = f"dim{k}"
            k += 1
    return current


LAYOUT_SCALE = 0.62


def layout_clips(project):
    return sorted((c for t in visible_tracks(project, "effect") for c in t["clips"] if c["type"] == "layout"),
                  key=lambda c: c["start"])


def layout_scale_at(project, t):
    """The speaker's scale at timeline time t (1 = full frame), with its eased move (Python twin
    of the render expression; used to keep graphics off the moved face)."""
    for c in layout_clips(project):
        t0, d = c["start"], c["duration"]
        if t0 <= t < t0 + d or (c.get("stay") and t >= t0):
            fade = float(c.get("fade", 0.35))
            f = min(fade, d / 2) if fade > 0 else 0
            back = (t0 + d - t) / f if f > 0 and not c.get("stay") else 1.0
            x = 1.0 if f <= 0 else min(1.0, max(0.0, min((t - t0) / f, back)))
            env = x * x * (3 - 2 * x)
            return 1 - (1 - float(c.get("scale", LAYOUT_SCALE))) * env
    return 1.0


def add_layouts(graph, current, project, fps):
    """"speaker_low": the speaker eases down into the lower part of the frame (scaled, anchored at
    the bottom) over a blurred, darker copy of the shot, so a card can take the top without
    covering the face (the reference look)."""
    for k, clip in enumerate(layout_clips(project)):
        f0, f1 = clip_frames(clip, fps)
        if f1 <= f0:
            continue
        t0, d = f0 / fps, (f1 - f0) / fps
        scale = float(clip.get("scale", LAYOUT_SCALE))
        fade = float(clip.get("fade", 0.35))
        if clip.get("stay") and fade > 0:
            f = min(fade, d / 2)
            x = f"min(1,max(0,(t-{t0:.4f})/{f:.4f}))"
            env = f"(({x})*({x})*(3-2*({x})))"            # down, and it stays down (the video ends)
        else:
            env = envelope_expression(t0, d, fade)
        z = f"(1-{1 - scale:.4f}*{env})"
        on = f"enable='{frames_expression([(f0, f1)], fps)}'"
        graph.add(f"[{current}]split=3[lyb{k}][lyg{k}][lyf{k}]",
                  f"[lyg{k}]boxblur=22:2:{on},eq=brightness=-0.10:saturation=0.85:{on}[lyblur{k}]",
                  f"[lyf{k}]scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame,setsar=1[lysc{k}]",
                  f"[lyblur{k}][lysc{k}]overlay=x='(W-w)/2':y='H-h':eval=frame[lymix{k}]",
                  f"[lyb{k}][lymix{k}]overlay=0:0:{on}[layout{k}]")
        current = f"layout{k}"
    return current


def add_vignettes(graph, current, project, fps):
    """A dark vignette (FFmpeg's vignette filter): the edges darken; `strength` sets the angle
    of the lens fall-off, `fade` eases it in and out."""
    k = 0
    for track in visible_tracks(project, "effect"):
        for clip in sorted(track["clips"], key=lambda c: c["start"]):
            if clip["type"] != "vignette":
                continue
            f0, f1 = clip_frames(clip, fps)
            if f1 <= f0:
                continue
            t0, d = f0 / fps, (f1 - f0) / fps
            angle = 0.25 + 0.6 * float(clip.get("strength", 0.5))
            env = envelope_expression(t0, d, float(clip.get("fade", 0)))
            graph.add(f"[{current}]vignette=angle='{angle:.4f}*{env}':eval=frame:"
                      f"enable='{frames_expression([(f0, f1)], fps)}'[vig{k}]")
            current = f"vig{k}"
            k += 1
    return current


def add_trackfx(graph, current, layer, fps, total_frames):
    """Add the tracked-effect video (drawn by trackfx.py, black background) with the screen
    blend: black changes nothing, light adds. Both sides are converted to RGB first, because
    "screen" on YUV planes would shift the colours."""
    idx = graph.add_input(["-i", layer["path"]])
    before = layer["f0"] / fps
    after = max(0.0, (total_frames - layer["f1"]) / fps)
    graph.add(f"[{idx}:v]scale={W}:{H}:flags=bicubic,format=gbrp,setsar=1,"
              f"tpad=start_mode=add:start_duration={before:.5f}:stop_mode=add:"
              f"stop_duration={after:.5f}:color=black,fps={fps}[tfx]",
              f"[{current}]format=gbrp[tfxbase]",
              "[tfxbase][tfx]blend=all_mode=screen:eof_action=pass[tfxout]")
    return "tfxout"


def add_graphics(graph, current, layers, fps):
    """Lay the drawn graphics (videos with transparency) over the picture, each for its frames."""
    for k, layer in enumerate(layers):
        idx = graph.add_input(["-i", layer["path"]])
        f0, f1 = layer["f0"], layer["f1"]
        graph.add(f"[{idx}:v]setpts=PTS-STARTPTS+{f0 / fps:.5f}/TB,format=rgba[gfx{k}]",
                  f"[{current}][gfx{k}]overlay=x={layer['x']}:y={layer['y']}:eof_action=pass:"
                  f"enable='{frames_expression([(f0, f1)], fps)}'[gfxout{k}]")
        current = f"gfxout{k}"
    return current


MOTION_DEFAULT = 0.35
SLIDE = {"slide_up": (0, 1), "slide_down": (0, -1), "slide_left": (1, 0), "slide_right": (-1, 0)}


def smooth01(expr):
    """Smoothstep of an expression already clipped to 0..1 (FFmpeg)."""
    return f"(({expr})*({expr})*(3-2*({expr})))"


def overlay_motion(clip, start, d):
    """Entrance / exit of an overlay: (alpha fade filters, scale filter, dx expr, dy expr).
    Times inside the filters are the clip's own (from 0); dx / dy are in timeline time t."""
    enter, leave = clip.get("enter", "none"), clip.get("exit", "none")
    if enter == "none" and leave == "none":
        return "", "", "0", "0"
    md = min(float(clip.get("motion", MOTION_DEFAULT)), d / 2)
    fades = ""
    if enter != "none":
        fades += f",fade=t=in:st=0:d={md:.3f}:alpha=1"
    if leave != "none":
        fades += f",fade=t=out:st={max(0.0, d - md):.3f}:d={md:.3f}:alpha=1"
    e_in = smooth01(f"min(1,max(0,t/{md:.4f}))")
    e_out = smooth01(f"min(1,max(0,(t-{d - md:.4f})/{md:.4f}))")
    scale = ""
    if "scale" in (enter, leave):
        k_in = f"(0.82+0.18*{e_in})" if enter == "scale" else "1"
        k_out = f"(1-0.18*{e_out})" if leave == "scale" else "1"
        scale = f",scale=w='trunc(iw*{k_in}*{k_out}/2)*2':h=-2:eval=frame"
    dist = 160
    g_in = smooth01(f"min(1,max(0,(t-{start:.4f})/{md:.4f}))")
    g_out = smooth01(f"min(1,max(0,(t-{start + d - md:.4f})/{md:.4f}))")
    dx, dy = ["0"], ["0"]
    if enter in SLIDE:
        sx, sy = SLIDE[enter]
        dx.append(f"{sx * dist}*(1-{g_in})")
        dy.append(f"{sy * dist}*(1-{g_in})")
    if leave in SLIDE:
        sx, sy = SLIDE[leave]                 # leaves the way it travels: slide_up goes up
        dx.append(f"{-sx * dist}*{g_out}")
        dy.append(f"{-sy * dist}*{g_out}")
    return fades, scale, "+".join(dx), "+".join(dy)


def fitted_size(src_w, src_h, box_w, box_h):
    """Size (even numbers) of a src_w x src_h picture scaled to fit inside box_w x box_h."""
    k = min(box_w / src_w, box_h / src_h)
    return max(2, int(round(src_w * k / 2)) * 2), max(2, int(round(src_h * k / 2)) * 2)


def has_overlay_style(clip):
    return not clip.get("mask") and bool(clip.get("radius") or clip.get("shadow") or clip.get("border"))


def _rounded_mask(w, h, radius, scale=4):
    from PIL import Image, ImageDraw
    big = Image.new("L", (w * scale, h * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * scale - 1, h * scale - 1),
                                          radius=max(0, radius) * scale, fill=255)
    return big.resize((w, h), Image.LANCZOS)


def overlay_style_assets(clip, src_w, src_h, out_dir):
    """Draw the pictures a styled overlay needs (Pillow): the rounded-corner mask, the soft
    shadow under it and the border on top, on a canvas with a margin for the shadow.
    Returns {"w", "h", "margin", "mask", "under", "over"} (paths or None)."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = fitted_size(src_w, src_h, float(clip["width"]), float(clip["height"]))
    radius = min(float(clip.get("radius", 0)), min(w, h) / 2)
    shadow = float(clip.get("shadow", 0))
    border = clip.get("border")
    margin = int(round(24 + 56 * shadow)) if shadow > 0 else (int(border["width"]) + 2 if border else 0)
    margin += margin % 2
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"ovstyle-{clip['id']}"
    info = {"w": w, "h": h, "margin": margin, "mask": None, "under": None, "over": None}
    if radius > 0:
        _rounded_mask(w, h, radius).save(f"{base}-mask.png")
        info["mask"] = f"{base}-mask.png"
    cw, ch = w + 2 * margin, h + 2 * margin
    under = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    if shadow > 0:
        blur = 10 + 26 * shadow
        drop = int(round(6 + 18 * shadow))
        shape = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(shape).rounded_rectangle((margin, margin + drop, margin + w - 1, margin + h - 1 + drop),
                                                radius=radius, fill=int(255 * (0.35 + 0.4 * shadow)))
        under.putalpha(shape.filter(ImageFilter.GaussianBlur(blur)))
    under.save(f"{base}-under.png")
    info["under"] = f"{base}-under.png"
    if border:
        color = border["color"].lstrip("#")
        rgb = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
        bw = float(border["width"])
        big = 4
        ring = Image.new("RGBA", (cw * big, ch * big), (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle(
            ((margin - bw / 2) * big, (margin - bw / 2) * big, (margin + w + bw / 2) * big - 1,
             (margin + h + bw / 2) * big - 1),
            radius=(radius + bw / 2) * big, outline=(*rgb, 255), width=int(round(bw * big)))
        ring.resize((cw, ch), Image.LANCZOS).save(f"{base}-over.png")
        info["over"] = f"{base}-over.png"
    return info


def prepare_overlay_styles(project, base_dir, work_dir):
    """{clip id: overlay_style_assets(...)} for every overlay with rounded corners, a shadow or
    a border (the source size comes from the media entry, or from the file)."""
    from .ffmpeg_tools import probe
    media = media_by_id(project)
    out = {}
    for track in visible_tracks(project, "overlay"):
        for clip in track["clips"]:
            if not has_overlay_style(clip):
                continue
            m = media[clip["media"]]
            w, h = m.get("width"), m.get("height")
            if not w or not h:
                info = probe(resolve_media_path(m, base_dir))
                w, h = info["width"], info["height"]
            if not w or not h:
                raise EditorError(f"The size of '{m.get('name') or m['id']}' is not known.")
            out[clip["id"]] = overlay_style_assets(clip, w, h, Path(work_dir) / "overlay-styles")
    return out


def add_overlays(graph, current, project, media, base_dir, fps, masks=None, styles=None):
    """Photos, B-roll and cut-outs over the picture. A clip with `mask` is cut out first: a
    green/blue screen keyed out (chroma), or a person mask video (masks[clip id], see segment.py).
    `styles` (prepare_overlay_styles): rounded corners, a soft shadow and a border, drawn as
    pictures and composed here; `enter` / `exit` move the overlay in and out smoothly."""
    from .segment import chroma_filter
    masks = masks or {}
    styles = styles or {}
    k = 0
    for track in visible_tracks(project, "overlay"):
        for clip in sorted(track["clips"], key=lambda c: c["start"]):
            f0, f1 = clip_frames(clip, fps)
            if f1 <= f0:
                continue
            start, d = f0 / fps, (f1 - f0) / fps
            path = resolve_media_path(media[clip["media"]], base_dir)
            if clip["type"] == "image":
                idx = graph.add_input(["-loop", "1", "-framerate", fps, "-t", f"{d:.4f}",
                                       "-i", path])
            else:
                speed = float(clip.get("speed", 1.0))
                idx = graph.add_input(["-ss", f"{clip['in']:.4f}", "-t", f"{d * speed:.4f}",
                                       "-i", path])
            speed = float(clip.get("speed", 1.0)) if clip["type"] == "video" else 1.0
            pts = "PTS-STARTPTS" if speed == 1 else f"(PTS-STARTPTS)/{speed:g}"
            src = f"[{idx}:v]setpts={pts},fps={fps},trim=duration={d:.4f},"
            mask = clip.get("mask")
            if mask and mask["type"] == "chroma":
                src += chroma_filter(mask.get("color", "#00ff00"), mask.get("similarity", 0.18),
                                     mask.get("blend", 0.06)) + ","
            elif mask and mask["type"] == "person" and clip["id"] in masks:
                m = media[clip["media"]]
                midx = graph.add_input(["-i", masks[clip["id"]]])
                graph.add(f"[{midx}:v]setpts={pts},fps={fps},trim=duration={d:.4f},"
                          f"scale={m.get('width') or W}:{m.get('height') or H},format=gray[ovm{k}]",
                          f"{src}format=yuv420p,scale={m.get('width') or W}:{m.get('height') or H}"
                          f"[ovs{k}]",
                          f"[ovs{k}][ovm{k}]alphamerge[ova{k}]")
                src = f"[ova{k}]"
            elif mask and mask["type"] == "person":
                raise EditorError(f"The cut-out of clip '{clip['id']}' has no person mask yet.")
            style = styles.get(clip["id"]) if has_overlay_style(clip) else None
            if style:
                chain = self_styled(graph, src, style, d, fps, k)
            else:
                chain = (f"{src}scale=w={round(clip['width'])}:h={round(clip['height'])}:"
                         f"force_original_aspect_ratio=decrease,format=rgba")
            if clip.get("animation", "none") == "pop":
                chain += (f",scale=w='trunc(iw*({pop_scale_expression(d)})/2)*2':h=-2:eval=frame,"
                          f"fade=t=in:st=0:d=0.15:alpha=1,"
                          f"fade=t=out:st={max(0.0, d - 0.2):.3f}:d=0.2:alpha=1")
            fades, scale, dx, dy = overlay_motion(clip, start, d)
            chain += scale + fades
            opacity = float(clip.get("opacity", 1.0))
            if opacity < 1:
                chain += f",colorchannelmixer=aa={opacity:g}"
            graph.add(f"{chain},setpts=PTS+{start:.4f}/TB[ovl{k}]",
                      f"[{current}][ovl{k}]overlay=x='{clip['x']:g}-w/2+{dx}':"
                      f"y='{clip['y']:g}-h/2+{dy}':"
                      f"eval=frame:eof_action=pass:"
                      f"enable='{frames_expression([(f0, f1)], fps)}'[ovout{k}]")
            current = f"ovout{k}"
            k += 1
    return current


def self_styled(graph, src, style, d, fps, k):
    """The filter chain (a label to continue from) of a styled overlay: the picture scaled to its
    fitted size, its corners rounded (mask), laid on the shadow canvas, the border on top."""
    def still(path, tag):
        idx = graph.add_input(["-loop", "1", "-framerate", fps, "-t", f"{d:.4f}", "-i", path])
        graph.add(f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS,fps={fps},trim=duration={d:.4f}[{tag}]")
        return tag
    w, h, m = style["w"], style["h"], style["margin"]
    graph.add(f"{src}scale=w={w}:h={h},setsar=1,format=rgba[ovp{k}]")
    pic = f"ovp{k}"
    if style["mask"]:
        mask = still(style["mask"], f"ovmk{k}")
        graph.add(f"[{mask}]format=gray[ovmg{k}]", f"[{pic}][ovmg{k}]alphamerge[ovr{k}]")
        pic = f"ovr{k}"
    under = still(style["under"], f"ovu{k}")
    graph.add(f"[{under}][{pic}]overlay=x={m}:y={m}:format=auto:eof_action=pass[ovc{k}]")
    canvas = f"ovc{k}"
    if style["over"]:
        over = still(style["over"], f"ovb{k}")
        graph.add(f"[{canvas}][{over}]overlay=0:0:format=auto[ovcb{k}]")
        canvas = f"ovcb{k}"
    return f"[{canvas}]format=rgba"


# ---------------------------------------------------------------- captions

def project_fonts(project):
    f = project["settings"].get("fonts", {})
    return {"regular": (f.get("regular", "Inter"), False),
            "bold": (f.get("bold", "Inter"), True),
            "heavy": (f.get("heavy", "Inter Black"), True)}


def caption_style(clip, project=None):
    style = get_style(clip["style"])
    overrides = dict(clip.get("overrides") or {})
    punctuation = (((project or {}).get("settings") or {}).get("captions") or {}).get("punctuation")
    if punctuation:
        overrides["punctuation"] = punctuation          # the project's setting, for every caption
    return replace(style, **overrides) if overrides else style


def caption_words(clip):
    """The clip's words on the timeline (seconds), as caption Words."""
    use_highlight = clip.get("highlight_keywords", True)
    return [Word(text=w["text"], start=round(clip["start"] + w["start"], 3),
                 end=round(clip["start"] + w["end"], 3),
                 highlight=bool(use_highlight and w.get("highlight")))
            for w in clip["words"]]


def build_project_ass(project, fonts_folder):
    """The .ass subtitle text for every visible caption clip, or None if there are none."""
    fonts = project_fonts(project)
    styles, lines, events = {}, [], []
    for track in visible_tracks(project, "caption"):
        for clip in sorted(track["clips"], key=lambda c: c["start"]):
            style = caption_style(clip, project)
            key = repr(style)
            if key not in styles:
                n = len(styles) + 1
                names = ("Main", "Box") if n == 1 else (f"Main{n}", f"Box{n}")
                new_lines, measurer = style_lines(style, fonts, fonts_folder, names)
                styles[key] = (names, measurer)
                lines += new_lines
            names, measurer = styles[key]
            events += build_events(caption_words(clip), style, None, measurer, names,
                                   last_end=round(clip_end(clip), 3))
    return ass_document(lines, events) if events else None


# ---------------------------------------------------------------- sound

def speech_noise_floor(project, media, base_dir):
    """The background noise level (dBFS) of the speech: main video and voice-over files."""
    from .media_tools import noise_floor_db
    ids = set()
    for track in project["tracks"]:
        if track.get("muted"):
            continue
        if track["kind"] == "video" or (track["kind"] == "audio" and track["role"] in DIALOG_ROLES):
            ids |= {c["media"] for c in track["clips"] if c.get("media")}
    floors = [noise_floor_db(resolve_media_path(media[i], base_dir)) for i in sorted(ids)
              if media[i]["kind"] != "image" and media[i].get("has_audio", True)]
    floors = [f for f in floors if f is not None]
    return max(floors) if floors else None


def add_audio_tracks(graph, project, media, base_dir, fps, dialog):
    """Mix the audio tracks with the main track's sound. Returns the final audio label."""
    clips = {"dialog": [], "music": [], "sfx": []}
    for track in project["tracks"]:
        if track["kind"] != "audio" or track.get("muted"):
            continue
        bus = "dialog" if track["role"] in DIALOG_ROLES else track["role"]
        clips[bus] += [c for c in track["clips"] if float(c.get("volume", 1.0)) > 0]
    everything = clips["dialog"] + clips["music"] + clips["sfx"]
    by_media = {}
    for clip in everything:
        by_media.setdefault(clip["media"], []).append(clip)
    branch = {}
    for mid, users in by_media.items():
        idx = graph.add_input(["-i", resolve_media_path(media[mid], base_dir)])
        names = [f"src{idx}_{j}" for j in range(len(users))]
        graph.add(f"[{idx}:a]asetpts=PTS-STARTPTS,aresample={AUDIO_RATE},"
                  f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                  f"asplit={len(users)}" + "".join(f"[{n}]" for n in names))
        for clip, name in zip(users, names):
            branch[clip["id"]] = name

    def clip_chain(clip, j):
        d = clip["duration"]
        speed = float(clip.get("speed", 1.0))
        chain = (f"[{branch[clip['id']]}]atrim=start={clip['in']:.4f}:"
                 f"end={clip['in'] + d * speed:.4f},asetpts=PTS-STARTPTS")
        if speed != 1:
            chain += f",{atempo_chain(speed)},atrim=end={d:.4f}"
        if float(clip.get("volume", 1.0)) != 1:
            chain += f",volume={float(clip['volume']):g}"
        if clip.get("fade_in"):
            chain += f",afade=t=in:st=0:d={clip['fade_in']:g}"
        if clip.get("fade_out"):
            chain += f",afade=t=out:st={max(0.0, d - clip['fade_out']):.4f}:d={clip['fade_out']:g}"
        delay = int(round(clip["start"] * AUDIO_RATE))
        graph.add(f"{chain},adelay={delay}S:all=1[ac{j}]")
        return f"ac{j}"

    counter = iter(range(len(everything)))
    dialog_parts = [clip_chain(c, next(counter)) for c in clips["dialog"]]
    music_parts = [clip_chain(c, next(counter)) for c in clips["music"]]
    sfx_parts = [clip_chain(c, next(counter)) for c in clips["sfx"]]

    if dialog_parts:
        ins = f"[{dialog}]" + "".join(f"[{p}]" for p in dialog_parts)
        graph.add(f"{ins}amix=inputs={len(dialog_parts) + 1}:duration=first:normalize=0[dialogmix]")
        dialog = "dialogmix"
    audio = project["settings"].get("audio", {})
    denoise = float(audio.get("denoise", 0))
    if denoise > 0:
        # FFT noise reduction. Its noise floor must be near the real noise level, so it is
        # measured in the pauses of the speech files.
        floor = speech_noise_floor(project, media, base_dir)
        nf = min(-20.0, max(-80.0, (floor if floor is not None else -50.0) + 5))
        graph.add(f"[{dialog}]afftdn=nr={10 + 30 * denoise:g}:nf={nf:.1f}[denoised]")
        dialog = "denoised"
    if audio.get("normalize"):
        graph.add(f"[{dialog}]loudnorm=I={audio.get('loudness', -14):g}:"
                  f"TP={audio.get('true_peak', -1.5):g}:LRA=11,aresample={AUDIO_RATE}[speech]")
        dialog = "speech"
    post = []
    ducking = float(audio.get("ducking", 0))
    if music_parts:
        ins = "".join(f"[{p}]" for p in music_parts)
        if len(music_parts) > 1:
            graph.add(f"{ins}amix=inputs={len(music_parts)}:duration=longest:normalize=0[musicmix]")
            music = "musicmix"
        else:
            music = music_parts[0]
        if ducking > 0:
            # Lower the music while someone speaks: the speech is the compressor's key.
            graph.add(f"[{dialog}]asplit=2[speechout][speechkey]",
                      f"[{music}][speechkey]sidechaincompress=threshold=0.015:"
                      f"ratio={2 + 18 * ducking:g}:attack=15:release=350:makeup=1[ducked]")
            dialog, music = "speechout", "ducked"
        post.append(music)
    sfx_ducking = float(audio.get("sfx_ducking", 0))
    if sfx_parts and sfx_ducking > 0:
        # sound effects a little quieter while you speak (they sit under the voice): about 5 dB at
        # 0.5 for a normal voice, never buried (a strong ratio took ~19 dB off and hid them)
        ins = "".join(f"[{p}]" for p in sfx_parts)
        if len(sfx_parts) > 1:
            graph.add(f"{ins}amix=inputs={len(sfx_parts)}:duration=longest:normalize=0[sfxmix]")
            sfx = "sfxmix"
        else:
            sfx = sfx_parts[0]
        graph.add(f"[{dialog}]asplit=2[sfxspeech][sfxkey]",
                  f"[{sfx}][sfxkey]sidechaincompress=threshold=0.02:ratio={1 + 0.6 * sfx_ducking:g}:"
                  f"attack=10:release=250:makeup=1[sfxducked]")
        dialog = "sfxspeech"
        sfx_parts = ["sfxducked"]
    post += sfx_parts
    if post:
        ins = f"[{dialog}]" + "".join(f"[{p}]" for p in post)
        graph.add(f"{ins}amix=inputs={len(post) + 1}:duration=first:normalize=0,"
                  f"alimiter=limit=0.95[aout]")
    else:
        graph.add(f"[{dialog}]anull[aout]")
    return "aout"


# ---------------------------------------------------------------- the command

def build_command(project, base_dir, output, ass_name=None, export=None, frame=None,
                  trackfx=None, graphics=None, masks=None, styles=None):
    """Return (input_args, filter_graph_text, output_args).

    `frame`: render only this frame number (0-based) to `output` as a picture.
    `trackfx`: the drawn tracked-effect video {"path", "f0", "f1"} (see trackfx.prepare_layer).
    `graphics`: the drawn motion graphics (graphics.render_layers), laid over the picture.
    `styles`: the drawn overlay shapes (prepare_overlay_styles): rounded corners, shadows, borders.
    """
    export = {**DEFAULT_EXPORT, **(export or {})}
    fps = project["settings"]["fps"]
    media = media_by_id(project)
    total_frames = frame_index(timeline_duration(project), fps)
    if total_frames <= 0:
        raise EditorError("The timeline is empty: add a clip first.")
    with_audio = frame is None
    graph = Graph()
    current, dialog = add_main_track(graph, project, media, base_dir, fps, total_frames,
                                     with_audio)
    current = add_zooms(graph, current, project, fps)
    current = add_layouts(graph, current, project, fps)
    current = add_grades(graph, current, project, fps, total_frames)
    current = add_wipes(graph, current, project, fps)
    current = add_fx(graph, current, project, fps)
    current = add_dims(graph, current, project, fps)
    current = add_vignettes(graph, current, project, fps)
    if trackfx:
        current = add_trackfx(graph, current, trackfx, fps, total_frames)
    current = add_overlays(graph, current, project, media, base_dir, fps, masks, styles)
    if graphics:
        current = add_graphics(graph, current, graphics, fps)
    if ass_name:
        graph.add(f"[{current}]subtitles={ass_name}:fontsdir=fonts[capout]")
        current = "capout"
    if frame is not None:
        graph.add(f"[{current}]select='eq(n,{int(frame)})'[vout]")
        outputs = ["-map", "[vout]", "-frames:v", "1", "-update", "1", str(output)]
        return graph.inputs, ";\n".join(graph.lines) + "\n", outputs

    height = int(export["height"])
    scale = f"scale=-2:{height}:flags=lanczos," if height != H else ""
    graph.add(f"[{current}]{scale}format=yuv420p[vout]")
    audio = add_audio_tracks(graph, project, media, base_dir, fps, dialog)
    outputs = [
        "-map", "[vout]", "-map", f"[{audio}]",
        "-c:v", "libx264", "-preset", str(export["encoder_speed"]), "-crf", str(export["crf"]),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(fps),
        "-c:a", "aac", "-b:a", str(export["audio_bitrate"]), "-ar", str(AUDIO_RATE),
        "-movflags", "+faststart", str(output),
    ]
    return graph.inputs, ";\n".join(graph.lines) + "\n", outputs


def prepare_trackfx(project, base_dir, job, frame=None, cancel=None, reporter=None):
    """Draw the tracked effects (if the project has any) to a video in `job`.
    Returns {"path", "f0", "f1"} or None."""
    if not any(c["type"] == "trackfx" for t in visible_tracks(project, "effect")
               for c in t["clips"]):
        return None
    from . import trackfx
    fps = project["settings"]["fps"]
    media = media_by_id(project)
    total_frames = frame_index(timeline_duration(project), fps)
    if reporter:
        reporter.stage("trackfx", "drawing the tracked effects")
    return trackfx.prepare_layer(
        project, media, Path(base_dir), fps, total_frames,
        main_segments(project, media, fps, total_frames), zoom_layers(project, fps), job,
        last_frame=frame, cancel=cancel)


def check_media_files(project, base_dir):
    used = {c["media"] for _t in project["tracks"] for c in _t["clips"] if "media" in c}
    used |= {c["layout"]["screen"] for t in project["tracks"] for c in t["clips"]
             if c.get("layout")}
    missing = [f"{m.get('name') or m['id']}: {resolve_media_path(m, base_dir)}"
               for m in project["media"]
               if m["id"] in used and not resolve_media_path(m, base_dir).exists()]
    if missing:
        raise EditorError("These media files are missing (moved or deleted?):\n  "
                          + "\n  ".join(missing))


def prepare_masks(project, base_dir, reporter=None, cancel=None, cfg=None):
    """Person masks for the cut-out clips ({clip id: mask video}), made and cached by segment.py."""
    from . import segment
    fps = project["settings"]["fps"]
    media = media_by_id(project)
    out = {}
    for track in visible_tracks(project, "overlay"):
        for clip in track["clips"]:
            if (clip.get("mask") or {}).get("type") != "person" or clip["type"] != "video":
                continue
            path = resolve_media_path(media[clip["media"]], base_dir)
            speed = float(clip.get("speed", 1.0))
            out[clip["id"]] = str(segment.person_mask(path, clip["in"], clip["out"], fps * speed if speed != 1
                                                      else fps, cfg, cancel, reporter))
    return out


def prepare_graphics(project, base_dir, reporter=None, cancel=None, mode="require"):
    """Make sure the project's motion graphics are drawn; return their layers for build_command."""
    from . import graphics
    if not graphics.graphic_clips(project):
        return []
    graphics.ensure_assets(project, base_dir, reporter, cancel, mode)
    return graphics.render_layers(project, base_dir)


def _run(project, output, base_dir, work_dir, fonts_folder, export, reporter, cancel,
         keep_work, frame, description, graphics_mode="require"):
    check_ffmpeg()
    check_project(project)
    base_dir = Path(base_dir or ".").resolve()
    check_media_files(project, base_dir)
    from . import graphics as graphics_mod
    gfx_layers = prepare_graphics(project, base_dir, reporter, cancel, graphics_mode)
    masks = prepare_masks(project, base_dir, reporter, cancel)
    # flash / whip / punch-in transitions that belong to graphics are real effect clips here
    project = graphics_mod.expand_attachments(project)
    fonts_folder = Path(fonts_folder or PROJECT_DIR / "assets" / "fonts")
    own_work = work_dir is None
    job = Path(tempfile.mkdtemp(prefix="render-") if own_work else work_dir)
    job.mkdir(parents=True, exist_ok=True)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_name(f"{output.stem}.part{output.suffix}")
    try:
        copy_fonts(fonts_folder, job / "fonts")
        ass_text = build_project_ass(project, job / "fonts")
        ass_name = None
        if ass_text:
            ass_name = "captions.ass"
            (job / ass_name).write_text(ass_text, encoding="utf-8")
        layer = prepare_trackfx(project, base_dir, job, frame, cancel, reporter)
        styles = prepare_overlay_styles(project, base_dir, job)
        inputs, graph, outputs = build_command(project, base_dir, part, ass_name, export, frame,
                                               trackfx=layer, graphics=gfx_layers, masks=masks,
                                               styles=styles)
        script = job / "filters.txt"
        script.write_text(graph, encoding="utf-8")
        fps = project["settings"]["fps"]
        total = (frame + 1) / fps if frame is not None else \
            frame_index(timeline_duration(project), fps) / fps
        if reporter:
            reporter.stage("render", description)
        run_ffmpeg_progress(inputs + filter_script_args(script) + outputs, description, total,
                            on_progress=reporter.progress if reporter else None, cwd=job,
                            cancel=cancel)
        if not part.exists():
            raise EditorError(f"FFmpeg finished but did not write {part.name}.")
        os.replace(part, output)
        return output
    finally:
        if part.exists():
            part.unlink()
        if own_work and not keep_work:
            shutil.rmtree(job, ignore_errors=True)


def render_project(project, output, base_dir=None, work_dir=None, fonts_folder=None, export=None,
                   reporter=None, cancel=None, keep_work=False):
    """Render the whole project to an MP4. Returns the output path.

    `base_dir`: folder that relative media paths start from (normally the project file's).
    `work_dir`: folder for temporary files (a fresh temp folder if None, removed afterwards).
    `export`:   {"crf", "encoder_speed", "audio_bitrate", "height"} (height 1920 = full size).
    `cancel`:   threading.Event; set it to stop (raises Cancelled).
    The file appears at `output` only when the render finished; a failed or cancelled render
    leaves nothing behind.
    """
    return _run(project, output, base_dir, work_dir, fonts_folder, export, reporter, cancel,
                keep_work, None, "rendering the video")


def render_frame(project, seconds, output, base_dir=None, work_dir=None, fonts_folder=None,
                 reporter=None, cancel=None):
    """Render the exact frame shown at `seconds` (full quality, 1080x1920) to a PNG."""
    fps = project["settings"]["fps"]
    total = frame_index(timeline_duration(project), fps)
    frame = min(max(0, int(math.floor(seconds * fps + 1e-6))), max(0, total - 1))
    return _run(project, output, base_dir, work_dir, fonts_folder, None, reporter, cancel,
                False, frame, f"rendering frame {frame}")
