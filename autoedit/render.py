"""Build the FFmpeg command that does the whole edit in one pass.

The editor now renders through a Project (see project_render.py), which reuses the helpers
in this file. `build()` is the original single-video renderer, kept as a reference: the
tests render the same edit both ways and compare the pictures.

Picture:  layout/fit to 1080x1920 -> keep only the chosen segments -> punch-in zooms
          -> colour grade -> pop-in overlays -> watermark -> captions
Sound:    keep the same segments -> loudness normalisation -> sound effects
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .overlays import POSITIONS

W, H = 1080, 1920
AUDIO_RATE = 48000


@dataclass
class RenderJob:
    video: Path                          # face video (or the screen recording in "screen" layout)
    segments: list                       # [(start, end)] kept parts, original time
    output: Path
    fps: int = 30
    layout: str = "face"                 # face, screen, split, pip
    screen: Optional[Path] = None        # screen recording for split / pip
    zooms: list = field(default_factory=list)       # [(amount, [(start, end), ...])] cut time
    anchor_y: float = 0.4
    grade: str = ""                      # FFmpeg filter text
    grade_ranges: list = field(default_factory=list)  # [(filter, start, end)] cut time
    overlays: list = field(default_factory=list)    # OverlayEvent list (cut time)
    ass_file: Optional[str] = None       # file name inside the work folder
    fonts_dir: str = "fonts"
    watermark: Optional[dict] = None     # {"file", "width", "opacity", "position"}
    sfx: list = field(default_factory=list)         # [(file, [times], volume)]
    loudness: float = -14
    true_peak: float = -1.5
    crf: int = 20
    encoder_speed: str = "medium"
    audio_bitrate: str = "192k"


def keep_expression(segments, fps):
    """FFmpeg expression that is true for frames inside the kept segments.

    Edges sit half a frame early so each segment keeps exactly round(len*fps) frames.
    """
    half = 0.5 / fps
    return "+".join(f"gte(t,{s - half:.4f})*lt(t,{e - half:.4f})" for s, e in segments)


def time_expression(ranges, fps):
    half = 0.5 / fps
    return "+".join(f"gte(t,{s - half:.4f})*lt(t,{e - half:.4f})" for s, e in ranges) or "0"


def fill(fps):
    return (f"setpts=PTS-STARTPTS,fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1")


def fit_over_blur(src, out, width, height, fps, tag):
    """Fit `src` inside width x height, on top of a blurred, zoomed copy of itself."""
    return [
        f"[{src}]setpts=PTS-STARTPTS,fps={fps},setsar=1,split[{tag}a][{tag}b]",
        f"[{tag}a]scale={width // 4}:{height // 4}:force_original_aspect_ratio=increase,"
        f"crop={width // 4}:{height // 4},boxblur=12:2,eq=brightness=-0.08,"
        f"scale={width}:{height},setsar=1[{tag}bg]",
        f"[{tag}b]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[{tag}fg]",
        f"[{tag}bg][{tag}fg]overlay=(W-w)/2:(H-h)/2[{out}]",
    ]


def layout_filters(job):
    """Filters that turn the input(s) into one 1080x1920 picture labelled [base]."""
    return layout_chain(job.layout, "0:v", "1:v", "base", job.fps, "scr")


def layout_chain(layout, face, screen, out, fps, tag):
    """Filters that turn `face` (and `screen`) into one 1080x1920 picture labelled [out].

    `tag` keeps the intermediate labels unique when several chains share one graph.
    """
    if layout == "face":
        return [f"[{face}]{fill(fps)}[{out}]"]
    if layout == "screen":
        return fit_over_blur(face, out, W, H, fps, tag)
    if layout == "split":
        top_h = 1152                      # screen recording: top 60%
        face_h = H - top_h
        return [
            # tpad: if the recording is shorter than the face video, hold its last frame
            f"[{screen}]tpad=stop_mode=clone:stop=-1[{tag}src]",
            *fit_over_blur(f"{tag}src", f"{tag}top", W, top_h, fps, tag),
            f"[{face}]setpts=PTS-STARTPTS,fps={fps},scale={W}:{face_h}:force_original_aspect_ratio="
            f"increase,crop={W}:{face_h}:(iw-ow)/2:(ih-oh)*0.3,setsar=1,"
            f"pad={W}:{H}:0:{top_h}[{tag}facecanvas]",
            f"[{tag}facecanvas][{tag}top]overlay=0:0:shortest=1[{out}]",
        ]
    if layout == "pip":
        return [
            f"[{screen}]tpad=stop_mode=clone:stop=-1[{tag}src]",
            *fit_over_blur(f"{tag}src", f"{tag}full", W, H, fps, tag),
            f"[{face}]setpts=PTS-STARTPTS,fps={fps},scale=360:480:force_original_aspect_ratio="
            f"increase,crop=360:480,setsar=1,pad=372:492:6:6:white[{tag}pip]",
            # Face top-left, below the app's top bar and away from the right-side buttons.
            f"[{tag}full][{tag}pip]overlay=40:190:shortest=1[{out}]",
        ]
    raise ValueError(f"unknown layout {layout}")


def pop_scale_expression(duration):
    """Overlay size over time: grow in with a small overshoot, shrink a bit on the way out."""
    d = duration
    return (f"if(lt(t,0.15),0.5+0.6*t/0.15,if(lt(t,0.25),1.1-0.1*(t-0.15)/0.1,"
            f"if(gt(t,{d - 0.2:.3f}),1-0.2*(t-{d - 0.2:.3f})/0.2,1)))")


def build(job: RenderJob):
    """Return (input_args, filter_graph_text, output_args)."""
    inputs = ["-i", str(job.video)]
    count = 1
    if job.layout in ("split", "pip"):
        inputs += ["-i", str(job.screen)]
        count += 1
    g = layout_filters(job)
    fps = job.fps
    keep = keep_expression(job.segments, fps)
    g.append(f"[base]select='{keep}',setpts='round(N/{fps}/TB)'[cut]")
    current = "cut"

    # Punch-in zooms: a zoomed copy is laid over the picture only while zoomed.
    zooms = [(a, r) for a, r in job.zooms if r and a > 1.0]
    if zooms:
        labels = [f"zsrc{i}" for i in range(len(zooms) + 1)]
        g.append(f"[{current}]split={len(labels)}" + "".join(f"[{l}]" for l in labels))
        current = labels[0]
        for i, (amount, ranges) in enumerate(zooms, start=1):
            g.append(f"[{labels[i]}]crop=w=iw/{amount}:h=ih/{amount}:x=(iw-ow)/2:"
                     f"y=(ih-oh)*{job.anchor_y},scale={W}:{H},setsar=1[zoomed{i}]")
            g.append(f"[{current}][zoomed{i}]overlay=0:0:enable='{time_expression(ranges, fps)}'"
                     f"[zoomout{i}]")
            current = f"zoomout{i}"

    # Colour grade (plus optional different grades for parts of the video).
    main_grade = job.grade or "null"
    if job.grade_ranges:
        labels = [f"gsrc{i}" for i in range(len(job.grade_ranges) + 1)]
        g.append(f"[{current}]split={len(labels)}" + "".join(f"[{l}]" for l in labels))
        g.append(f"[{labels[0]}]{main_grade}[graded0]")
        current = "graded0"
        for i, (flt, start, end) in enumerate(job.grade_ranges, start=1):
            g.append(f"[{labels[i]}]{flt or 'null'}[gradealt{i}]")
            g.append(f"[{current}][gradealt{i}]overlay=0:0:enable='"
                     f"{time_expression([(start, end)], fps)}'[graded{i}]")
            current = f"graded{i}"
    else:
        g.append(f"[{current}]{main_grade}[graded]")
        current = "graded"

    # Pop-in overlays (B-roll).
    for i, ev in enumerate(job.overlays):
        if ev.is_image:
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{ev.duration:.3f}",
                       "-i", str(ev.file)]
        else:
            inputs += ["-t", f"{ev.duration:.3f}", "-i", str(ev.file)]
        max_w, max_h, cx, cy = POSITIONS[ev.position]
        d = ev.duration
        g.append(
            f"[{count}:v]setpts=PTS-STARTPTS,fps={fps},trim=duration={d:.3f},"
            f"scale=w={max_w}:h={max_h}:force_original_aspect_ratio=decrease,format=rgba,"
            f"scale=w='trunc(iw*({pop_scale_expression(d)})/2)*2':h=-2:eval=frame,"
            f"fade=t=in:st=0:d=0.15:alpha=1,fade=t=out:st={max(0.0, d - 0.2):.3f}:d=0.2:alpha=1,"
            f"setpts=PTS+{ev.start:.3f}/TB[ovl{i}]"
        )
        g.append(f"[{current}][ovl{i}]overlay=x='{cx}-w/2':y='{cy}-h/2':eval=frame:"
                 f"eof_action=pass:enable='between(t,{ev.start:.3f},{ev.start + d:.3f})'[ovout{i}]")
        current = f"ovout{i}"
        count += 1

    # Logo watermark.
    if job.watermark:
        wm = job.watermark
        inputs += ["-i", str(wm["file"])]
        pos = {
            "top_left": ("40", "170"),
            "top_right": (f"W-w-{40 + 170}", "170"),
            "bottom_left": ("40", "H*0.8-h-30"),
            "bottom_right": (f"W-w-{40 + 170}", "H*0.8-h-30"),
        }.get(wm.get("position", "top_left"), ("40", "170"))
        g.append(f"[{count}:v]scale={int(wm['width'])}:-1,format=rgba,"
                 f"colorchannelmixer=aa={float(wm['opacity'])}[wm]")
        g.append(f"[{current}][wm]overlay=x={pos[0]}:y={pos[1]}[wmout]")
        current = "wmout"
        count += 1

    # Captions last, so nothing covers them.
    if job.ass_file:
        g.append(f"[{current}]subtitles={job.ass_file}:fontsdir={job.fonts_dir}[capout]")
        current = "capout"
    g.append(f"[{current}]format=yuv420p[vout]")

    # Sound: same cuts as the picture, cut in 1-frame blocks so they stay in sync.
    block = AUDIO_RATE // fps
    g.append(
        f"[0:a]asetpts=PTS-STARTPTS,aresample={AUDIO_RATE},"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo,asetnsamples=n={block}:p=1,"
        f"aselect='{keep}',asetpts='round(N/SR/TB)',"
        f"loudnorm=I={job.loudness}:TP={job.true_peak}:LRA=11,aresample={AUDIO_RATE}[speech]"
    )
    audio = "speech"
    sfx_labels = []
    for k, (file, times, volume) in enumerate(job.sfx):
        if not times:
            continue
        inputs += ["-i", str(file)]
        split = "".join(f"[sfx{k}_{j}]" for j in range(len(times)))
        g.append(f"[{count}:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:"
                 f"channel_layouts=stereo,volume={volume},asplit={len(times)}{split}")
        for j, t in enumerate(times):
            ms = max(0, int(t * 1000))
            g.append(f"[sfx{k}_{j}]adelay={ms}:all=1[sfxd{k}_{j}]")
            sfx_labels.append(f"sfxd{k}_{j}")
        count += 1
    if sfx_labels:
        ins = f"[{audio}]" + "".join(f"[{l}]" for l in sfx_labels)
        g.append(f"{ins}amix=inputs={len(sfx_labels) + 1}:duration=first:normalize=0,"
                 f"alimiter=limit=0.95[aout]")
    else:
        g.append(f"[{audio}]anull[aout]")

    outputs = [
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", job.encoder_speed, "-crf", str(job.crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(fps),
        "-c:a", "aac", "-b:a", job.audio_bitrate, "-ar", str(AUDIO_RATE),
        "-movflags", "+faststart", str(job.output),
    ]
    return inputs, ";\n".join(g) + "\n", outputs


def intro_outro_command(main, intro, outro, fps, crf, encoder_speed, audio_bitrate, output,
                        probe):
    """FFmpeg arguments that glue an intro and/or outro (image or clip) around the edit.

    `intro` / `outro` are (path, seconds_for_images) or None. `probe` is ffmpeg_tools.probe.
    """
    inputs, parts, g = [], [], []
    index = 0
    pieces = ([intro] if intro else []) + [(main, None)] + ([outro] if outro else [])
    for path, seconds in pieces:
        is_image = Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        if is_image:
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{seconds}", "-i", str(path)]
            inputs += ["-f", "lavfi", "-t", f"{seconds}", "-i",
                       f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
            v, a = f"{index}:v", f"{index + 1}:a"
            index += 2
        else:
            info = probe(path)
            inputs += ["-i", str(path)]
            v, a = f"{index}:v", f"{index}:a"
            index += 1
            if not info["has_audio"]:
                inputs += ["-f", "lavfi", "-t", f"{info['duration']:.3f}", "-i",
                           f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
                a = f"{index}:a"
                index += 1
        n = len(parts)
        g.append(f"[{v}]{fill(fps)},format=yuv420p[cv{n}]")
        g.append(f"[{a}]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
                 f"[ca{n}]")
        parts.append(n)
    joined = "".join(f"[cv{n}][ca{n}]" for n in parts)
    g.append(f"{joined}concat=n={len(parts)}:v=1:a=1[vout][aout]")
    outputs = [
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", encoder_speed, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(fps),
        "-c:a", "aac", "-b:a", audio_bitrate, "-ar", str(AUDIO_RATE),
        "-movflags", "+faststart", str(output),
    ]
    return inputs, ";\n".join(g) + "\n", outputs
