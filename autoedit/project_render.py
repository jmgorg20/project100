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
from .render import AUDIO_RATE, H, W, layout_chain, pop_scale_expression
from .styles import get_style
from .words import Word

DEFAULT_EXPORT = {"crf": 20, "encoder_speed": "medium", "audio_bitrate": "192k", "height": H}
DEFAULT_ANCHOR_Y = 0.4
DIALOG_ROLES = ("original", "voiceover")


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
        if clip["type"] == "image":
            segments.append(Segment("image", frames=n, media=m, fit=fit, end_frame=f1))
        else:
            source = frame_index(clip["in"], fps) / fps
            volume = 0.0 if muted else float(clip.get("volume", 1.0))
            layout = clip.get("layout")
            last = segments[-1] if segments else None
            if (last is not None and last.kind == "run" and last.media is m
                    and last.fit == fit and last.layout == layout and last.volume == volume
                    and last.end_frame == f0 and source >= last.source_end(fps) - 1e-6):
                last.sources.append((source, n))
                last.frames += n
                last.end_frame = f1
            else:
                segments.append(Segment("run", frames=n, media=m, fit=fit, layout=layout,
                                        volume=volume, sources=[(source, n)], end_frame=f1))
        cursor = f1
    if cursor < total_frames:
        segments.append(Segment("gap", frames=total_frames - cursor, end_frame=total_frames))
    return segments


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
            mode = "screen" if seg.fit == "blur" else "face"
            graph.add(*layout_chain(mode, f"{idx}:v", None, f"m{k}pic", fps, f"m{k}"))
            graph.add(f"[m{k}pic]{exact}[{v}]")
        else:
            idx = graph.add_input(["-i", resolve_media_path(seg.media, base_dir)])
            screen = None
            if seg.layout:
                mode = seg.layout["type"]
                sidx = graph.add_input(["-i", resolve_media_path(media[seg.layout["screen"]],
                                                                  base_dir)])
                screen = f"{sidx}:v"
            else:
                mode = "screen" if seg.fit == "blur" else "face"
            keep = "+".join(f"gte(t,{s - half:.4f})*lt(t,{s + c / fps - half:.4f})"
                            for s, c in seg.sources)
            graph.add(*layout_chain(mode, f"{idx}:v", screen, f"m{k}pic", fps, f"m{k}"))
            graph.add(f"[m{k}pic]select='{keep}',setpts='round(N/{fps}/TB)',{exact}[{v}]")
            if with_audio and seg.media.get("has_audio", True) and seg.volume > 0:
                has_sound = True
                volume = f",volume={seg.volume:g}" if seg.volume != 1 else ""
                graph.add(
                    f"[{idx}:a]asetpts=PTS-STARTPTS,aresample={AUDIO_RATE},"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"asetnsamples=n={block}:p=1,aselect='{keep}',asetpts='round(N/SR/TB)'{volume},"
                    f"apad=whole_len={samples},atrim=end_sample={samples}[{a}]")
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


def add_zooms(graph, current, project, fps):
    layers = effect_layers(project, fps, "zoom",
                           lambda c: (float(c["amount"]),
                                      float(c.get("anchor_y", DEFAULT_ANCHOR_Y))))
    layers = [(k, r) for k, r in layers if k[0] > 1.0]
    if not layers:
        return current
    labels = [f"zsrc{i}" for i in range(len(layers) + 1)]
    graph.add(f"[{current}]split={len(labels)}" + "".join(f"[{l}]" for l in labels))
    current = labels[0]
    for i, ((amount, anchor), ranges) in enumerate(layers, start=1):
        graph.add(f"[{labels[i]}]crop=w=iw/{amount:g}:h=ih/{amount:g}:x=(iw-ow)/2:"
                  f"y=(ih-oh)*{anchor:g},scale={W}:{H},setsar=1[zoomed{i}]",
                  f"[{current}][zoomed{i}]overlay=0:0:enable='{frames_expression(ranges, fps)}'"
                  f"[zoomout{i}]")
        current = f"zoomout{i}"
    return current


def add_grades(graph, current, project, fps, total_frames):
    layers = effect_layers(project, fps, "grade", lambda c: c["grade"])
    if not layers:
        return current
    base = "null"
    first_name, first_ranges = layers[0]
    if first_ranges[0][0] <= 0 and first_ranges[-1][1] >= total_frames and len(first_ranges) == 1:
        base = grade_filter(first_name) or "null"     # covers everything: apply directly
        layers = layers[1:]
    if not layers:
        graph.add(f"[{current}]{base}[graded]")
        return "graded"
    labels = [f"gsrc{i}" for i in range(len(layers) + 1)]
    graph.add(f"[{current}]split={len(labels)}" + "".join(f"[{l}]" for l in labels))
    graph.add(f"[{labels[0]}]{base}[graded0]")
    current = "graded0"
    for i, (name, ranges) in enumerate(layers, start=1):
        graph.add(f"[{labels[i]}]{grade_filter(name) or 'null'}[gradealt{i}]",
                  f"[{current}][gradealt{i}]overlay=0:0:enable='{frames_expression(ranges, fps)}'"
                  f"[graded{i}]")
        current = f"graded{i}"
    return current


def add_overlays(graph, current, project, media, base_dir, fps):
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
                idx = graph.add_input(["-ss", f"{clip['in']:.4f}", "-t", f"{d:.4f}", "-i", path])
            chain = (f"[{idx}:v]setpts=PTS-STARTPTS,fps={fps},trim=duration={d:.4f},"
                     f"scale=w={round(clip['width'])}:h={round(clip['height'])}:"
                     f"force_original_aspect_ratio=decrease,format=rgba")
            if clip.get("animation", "none") == "pop":
                chain += (f",scale=w='trunc(iw*({pop_scale_expression(d)})/2)*2':h=-2:eval=frame,"
                          f"fade=t=in:st=0:d=0.15:alpha=1,"
                          f"fade=t=out:st={max(0.0, d - 0.2):.3f}:d=0.2:alpha=1")
            opacity = float(clip.get("opacity", 1.0))
            if opacity < 1:
                chain += f",colorchannelmixer=aa={opacity:g}"
            graph.add(f"{chain},setpts=PTS+{start:.4f}/TB[ovl{k}]",
                      f"[{current}][ovl{k}]overlay=x='{clip['x']:g}-w/2':y='{clip['y']:g}-h/2':"
                      f"eval=frame:eof_action=pass:"
                      f"enable='{frames_expression([(f0, f1)], fps)}'[ovout{k}]")
            current = f"ovout{k}"
            k += 1
    return current


# ---------------------------------------------------------------- captions

def project_fonts(project):
    f = project["settings"].get("fonts", {})
    return {"regular": (f.get("regular", "Inter"), False),
            "bold": (f.get("bold", "Inter"), True),
            "heavy": (f.get("heavy", "Inter Black"), True)}


def caption_style(clip):
    style = get_style(clip["style"])
    overrides = clip.get("overrides") or {}
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
            style = caption_style(clip)
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

def add_audio_tracks(graph, project, media, base_dir, fps, dialog):
    """Mix the audio tracks with the main track's sound. Returns the final audio label."""
    clips = {"dialog": [], "post": []}
    for track in project["tracks"]:
        if track["kind"] != "audio" or track.get("muted"):
            continue
        bus = "dialog" if track["role"] in DIALOG_ROLES else "post"
        clips[bus] += [c for c in track["clips"] if float(c.get("volume", 1.0)) > 0]
    everything = clips["dialog"] + clips["post"]
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
        chain = (f"[{branch[clip['id']]}]atrim=start={clip['in']:.4f}:end={clip['in'] + d:.4f},"
                 f"asetpts=PTS-STARTPTS")
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
    post_parts = [clip_chain(c, next(counter)) for c in clips["post"]]

    if dialog_parts:
        ins = f"[{dialog}]" + "".join(f"[{p}]" for p in dialog_parts)
        graph.add(f"{ins}amix=inputs={len(dialog_parts) + 1}:duration=first:normalize=0[dialogmix]")
        dialog = "dialogmix"
    audio = project["settings"].get("audio", {})
    if audio.get("normalize"):
        graph.add(f"[{dialog}]loudnorm=I={audio.get('loudness', -14):g}:"
                  f"TP={audio.get('true_peak', -1.5):g}:LRA=11,aresample={AUDIO_RATE}[speech]")
        dialog = "speech"
    if post_parts:
        ins = f"[{dialog}]" + "".join(f"[{p}]" for p in post_parts)
        graph.add(f"{ins}amix=inputs={len(post_parts) + 1}:duration=first:normalize=0,"
                  f"alimiter=limit=0.95[aout]")
    else:
        graph.add(f"[{dialog}]anull[aout]")
    return "aout"


# ---------------------------------------------------------------- the command

def build_command(project, base_dir, output, ass_name=None, export=None, frame=None):
    """Return (input_args, filter_graph_text, output_args).

    `frame`: render only this frame number (0-based) to `output` as a picture.
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
    current = add_grades(graph, current, project, fps, total_frames)
    current = add_overlays(graph, current, project, media, base_dir, fps)
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


def _run(project, output, base_dir, work_dir, fonts_folder, export, reporter, cancel,
         keep_work, frame, description):
    check_ffmpeg()
    check_project(project)
    base_dir = Path(base_dir or ".").resolve()
    check_media_files(project, base_dir)
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
        inputs, graph, outputs = build_command(project, base_dir, part, ass_name, export, frame)
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
