"""The full edit, step by step. `edit_video()` is what `python editor.py edit` runs."""

import shutil
import time
from pathlib import Path

from . import PROJECT_DIR
from .broll import broll_label
from .captions import chunk_words, group_end_times
from .config import project_path
from .cuts import (alternate_zoom, find_removals, keep_segments, remap_range, remap_time,
                   remap_words, snap_to_frames, total_length)
from .errors import EditorError
from .ffmpeg_tools import check_ffmpeg, detect_silences, probe, probe_video_with_audio
from .grades import grade_filter
from .highlight import mark_keywords
from .overlays import POSITIONS, OverlayEvent, find_trigger_events, load_triggers, schedule
from .progress import TextReporter
from .project import assign_lanes, media_from_file, new_project, save_project
from .project_render import frame_index, render_project
from .styles import get_style
from .transcribe import transcribe
from .words import load_transcript, save_transcript

LAYOUTS = ("face", "screen", "split", "pip")


def unique_output_path(folder, stem):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}_edited.mp4"
    n = 2
    while path.exists():
        path = folder / f"{stem}_edited_{n}.mp4"
        n += 1
    return path


def edit_video(video, cfg, transcript=None, plan=None, screen=None, layout=None, output=None,
               reporter=None, cancel=None):
    """Edit one video. Returns the path of the finished MP4.

    The edit is first written as a Project (saved next to the video as
    <name>.project.json when output.save_project is on), then rendered from it.
    """
    started = time.time()
    video = Path(video).resolve()
    work_root = project_path(cfg["work_folder"])
    job_dir = work_root / f"{video.stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    out_folder = project_path(cfg["output"]["folder"])
    output = Path(output).resolve() if output else unique_output_path(out_folder, video.stem)
    try:
        project = build_edit_project(video, cfg, transcript, plan, screen, layout, job_dir)
        if cfg["output"].get("save_project", True):
            saved = save_project(project, output.with_suffix(".project.json"))
            print(f"  > saved {saved.name} (open it in the app, or: python editor.py render "
                  f"{saved.name})")
        print("[6/6] Rendering")
        o = cfg["output"]
        render_project(project, output, work_dir=job_dir,
                       fonts_folder=project_path(cfg["captions"]["fonts_folder"]),
                       export={"crf": o["crf"], "encoder_speed": o["encoder_speed"],
                               "audio_bitrate": o["audio_bitrate"]},
                       reporter=reporter or TextReporter(), cancel=cancel)
    except BaseException:
        if job_dir.exists():
            print(f"  (temporary files kept for troubleshooting in {job_dir})")
        raise

    if not cfg.get("keep_work_files"):
        shutil.rmtree(job_dir, ignore_errors=True)
    minutes = (time.time() - started) / 60
    print(f"Done in {minutes:.1f} min -> {output}")
    return output


class MediaList:
    """Media entries for the project, one per file (files are probed once)."""

    def __init__(self):
        self.entries = {}

    def add(self, path):
        path = Path(path).resolve()
        if path not in self.entries:
            self.entries[path] = media_from_file(path, f"m{len(self.entries) + 1}")
        return self.entries[path]

    def as_list(self):
        return list(self.entries.values())


def build_edit_project(video, cfg, transcript=None, plan=None, screen=None, layout=None,
                       job_dir=None, words=None):
    """Steps 1-5 of the edit: decide everything and return it as a Project (no rendering).

    Times in the project are on the finished timeline (after cutting, after the intro).
    `words`: an already-loaded transcript (list of Words), e.g. from the cache.
    Plan keys beyond the --plan file: "caption_overrides" (caption clip overrides).
    """
    video = Path(video).resolve()
    check_ffmpeg()
    info = probe_video_with_audio(video)

    layout = layout or ("split" if screen else "face")
    if layout not in LAYOUTS:
        raise EditorError(f"Unknown layout '{layout}'. Choose: {', '.join(LAYOUTS)}")
    if layout in ("split", "pip"):
        if not screen:
            raise EditorError(f"Layout '{layout}' needs a screen recording: add --screen file.mp4")
        screen = Path(screen).resolve()
        if not probe(screen)["has_video"]:
            raise EditorError(f"'{screen.name}' has no video picture.")

    plan = plan or {}
    pacing = cfg["pacing"]
    fps = int(cfg["output"]["fps"])
    style = get_style(cfg["style"], cfg["highlight"].get("color"))
    print(f"Editing {video.name}  ({info['duration']:.1f}s, style {style.number} {style.name}, "
          f"grade {cfg['grade']}, preset {cfg['preset']}, layout {layout})")

    job_dir = Path(job_dir) if job_dir else \
        project_path(cfg["work_folder"]) / f"{video.stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    job_dir.mkdir(parents=True, exist_ok=True)
    out_folder = project_path(cfg["output"]["folder"])

    # 1. Transcribe (or load an existing transcript).
    print("[1/6] Transcript")
    if words is not None:
        print(f"  > using the saved transcript ({len(words)} words)")
    elif transcript:
        words = load_transcript(transcript)
        print(f"  > using {Path(transcript).name} ({len(words)} words)")
    else:
        words = transcribe(video, cfg, job_dir)
        print(f"  > {len(words)} words")
        if cfg["output"].get("save_transcript", True):
            saved = out_folder / f"{video.stem}.transcript.json"
            out_folder.mkdir(parents=True, exist_ok=True)
            save_transcript(words, saved, cfg["language"])
            print(f"  > saved {saved.name} (edit it, add *stars* for keywords, re-run with "
                  f"--transcript)")

    from .vocabulary import fix_words
    words = fix_words(words, cfg)                     # your corrections (vocabulary.json)

    # 2. Decide what to cut.
    print("[2/6] Cutting silences and filler words")
    threshold = float(pacing["silence_threshold"])
    padding = float(cfg["silence"]["padding"])
    audio_silences = []
    if cfg["silence"].get("use_audio_detection", True):
        audio_silences = detect_silences(video, cfg["silence"]["noise_db"], threshold)
    removals = find_removals(
        words, info["duration"], threshold, padding, cfg["fillers"],
        remove_fillers=pacing["remove_fillers"], audio_silences=audio_silences,
        manual_cuts=[(c["start"], c["end"]) for c in plan.get("cuts", [])],
    )
    segments = snap_to_frames(keep_segments(removals, info["duration"]), fps)
    if not segments or total_length(segments) < 0.5:
        raise EditorError("Almost everything would be cut. Is the speech very quiet? "
                          "Try silence -> noise_db: -45 in config.yaml.")
    new_length = total_length(segments)
    cut_words = remap_words(words, segments, cfg["fillers"], pacing["remove_fillers"])
    mark_keywords(cut_words, cfg["highlight"])
    print(f"  > {info['duration']:.1f}s -> {new_length:.1f}s "
          f"({len(segments)} pieces, {len(segments) - 1} jump cuts)")

    # 3. Zooms and grades.
    print("[3/6] Zoom and colour plan")
    zooms = []
    if pacing.get("zoom", True) and plan.get("auto_zoom", True):
        auto = alternate_zoom(segments, float(pacing["zoom_min_interval"]),
                              float(pacing["zoom_max_interval"]))
        zooms.append((float(pacing["zoom_amount"]), auto))
    for z in plan.get("zooms", []):
        mapped = remap_range(z["start"], z["end"], segments)
        if mapped:
            zooms.append((z["amount"], [mapped]))
    grade_filter(cfg["grade"])   # check the name early
    grade_ranges = []
    for gr in plan.get("grades", []):
        mapped = remap_range(gr["start"], gr["end"], segments)
        if mapped:
            grade_ranges.append((gr["grade"], *mapped))

    # 4. Pop-in overlays.
    print("[4/6] Overlays")
    caption_zone = "divider" if layout == "split" else style.zone
    overlay_events = []
    if cfg["overlays"].get("enabled", True):
        folder = project_path(cfg["overlays"]["folder"])
        triggers = load_triggers(project_path(cfg["overlays"]["triggers_file"]), folder)
        overlay_events += find_trigger_events(cut_words, triggers)
    for item in plan.get("overlays", []):
        at = remap_time(item["at"], segments, side="next")
        if at is not None:
            overlay_events.append(OverlayEvent(Path(item["file"]), at, item["duration"],
                                               item["position"], item.get("broll")))
    overlay_events = schedule(overlay_events, new_length, caption_zone,
                              top_blocked=layout == "pip")
    for ev in overlay_events:
        print(f"  > {ev.file.name} at {ev.start:.1f}s ({ev.position})")
    if not overlay_events:
        print("  > none")

    # 5. Captions.
    print("[5/6] Captions")
    caption_clips = []
    if cfg["captions"].get("enabled", True) and cut_words:
        caption_clips = caption_groups(cut_words, style, new_length)
        print(f"  > {style.name}: {len(caption_clips)} captions")
    else:
        print("  > captions off")

    # Everything as a Project.
    c = cfg["captions"]
    project = new_project(
        name=video.stem, fps=fps, loudness=cfg["audio"]["loudness"],
        true_peak=cfg["audio"]["true_peak"],
        fonts={"regular": c["font_regular"], "bold": c["font_bold"], "heavy": c["font_heavy"]},
    )
    project["meta"] = {"made_by": "python editor.py edit", "source": str(video),
                       "style": style.name, "grade": cfg["grade"], "preset": cfg["preset"],
                       "layout": layout}
    tracks = {t["id"]: t for t in project["tracks"]}
    media = MediaList()
    main_media = media.add(screen if layout == "screen" and screen else video)
    project["transcript"] = {
        "media": media.add(video)["id"], "language": cfg["language"],
        "words": [{"text": f"*{w.text}*" if w.manual else w.text,
                   "start": round(w.start, 3), "end": round(w.end, 3)} for w in words],
    }
    ids = ClipIds()
    main = tracks["main"]["clips"]

    # Intro, the cut video, outro on the main track.
    branding = cfg["branding"]
    intro = branding_piece(branding, "intro")
    outro = branding_piece(branding, "outro")
    offset = 0.0
    if intro:
        offset = add_branding_clip(main, media, ids, intro, 0.0, fps)
    start = offset                               # where the cut video starts
    clip_layout = {"type": layout, "screen": media.add(screen)["id"]} \
        if layout in ("split", "pip") else None
    for s, e in segments:
        clip = {"id": ids.next("v"), "type": "video", "media": main_media["id"],
                "start": round(offset, 6), "duration": round(e - s, 6),
                "in": round(s, 6), "out": round(e, 6),
                "fit": "blur" if layout == "screen" else "fill"}
        if clip_layout:
            clip["layout"] = dict(clip_layout)
        main.append(clip)
        offset += e - s
    main_end = offset
    if outro:
        add_branding_clip(main, media, ids, outro, main_end, fps)

    # Effects: auto zoom, plan zooms, base grade, plan grades (later tracks win).
    effect_tracks = []
    zoom_lanes = []
    for amount, ranges in zooms:
        if amount <= 1.0:          # 1.0 or less means no zoom (as before)
            continue
        clips = [{"id": ids.next("z"), "type": "zoom", "start": round(start + a, 6),
                  "duration": round(b - a, 6), "amount": float(amount),
                  "anchor_y": float(cfg["zoom"]["anchor_y"])} for a, b in ranges if b > a]
        zoom_lanes += assign_lanes(clips)
    effect_tracks += [("Zoom", lane) for lane in zoom_lanes]
    if grade_filter(cfg["grade"]):
        effect_tracks.append(("Color", [{"id": ids.next("g"), "type": "grade",
                                          "start": round(start, 6),
                                          "duration": round(new_length, 6),
                                          "grade": cfg["grade"]}]))
    grade_clips = [{"id": ids.next("g"), "type": "grade", "start": round(start + a, 6),
                    "duration": round(b - a, 6), "grade": name}
                   for name, a, b in grade_ranges if b > a]
    effect_tracks += [("Color", lane) for lane in assign_lanes(grade_clips)]
    fx_clips = []
    cut_points = [sum(e - s for s, e in segments[:i]) for i in range(1, len(segments))]
    for fx in plan.get("effects", []):
        t = remap_time(fx["at"], segments, side="next")
        if t is None:
            continue
        duration = float(fx["duration"])
        if fx.get("on_cut") and cut_points:
            cut = min(cut_points, key=lambda c: abs(c - t))
            if abs(cut - t) <= 1.5:                  # a transition: centred on that jump cut
                t = max(0.0, cut - duration / 2)
        duration = min(duration, new_length - t)
        if duration * fps < 1:
            continue
        fx_clips.append({"id": ids.next("f"), "type": "fx", "start": round(start + t, 6),
                         "duration": round(duration, 6), "effect": fx["effect"],
                         "intensity": round(min(1.0, max(0.0, float(fx["intensity"]))), 4)})
    effect_tracks += [("Effects", lane) for lane in assign_lanes(fx_clips)]
    replace_track(project, "effects", "effect", effect_tracks)

    # Overlays: pop-in pictures, then the logo on its own track (drawn on top).
    photos = tracks["photos"]["clips"]
    for ev in overlay_events:
        m = media.add(ev.file)
        duration = ev.duration if ev.is_image else min(ev.duration, m["duration"])
        if duration * fps < 1:
            continue
        max_w, max_h, cx, cy = POSITIONS[ev.position]
        clip = {"id": ids.next("o"), "type": "image" if ev.is_image else "video",
                "media": m["id"], "start": round(start + ev.start, 6),
                "duration": round(duration, 6), "x": cx, "y": cy,
                "width": max_w, "height": max_h,
                "animation": "none" if ev.position == "full" else "pop"}
        if not ev.is_image:
            clip.update({"in": 0.0, "out": round(duration, 6)})
        if ev.broll:
            clip["broll"] = dict(ev.broll, position=ev.position)
            clip["label"] = broll_label(ev.broll)
        photos.append(clip)
    if branding.get("watermark"):
        wm_file = project_path(branding["watermark"])
        if not wm_file.exists():
            raise EditorError(f"Watermark file not found: {wm_file}")
        project["tracks"].insert(2, {"id": "logo", "kind": "overlay", "name": "Logo",
                                     "clips": [watermark_clip(media.add(wm_file), branding,
                                                              start, new_length, ids)]})

    # Captions: one clip per caption group, word times relative to the clip.
    for clip in caption_clips:
        clip["id"] = ids.next("t")
        clip["start"] = round(start + clip["start"], 6)
        if layout == "split":
            clip["overrides"] = {"zone": "divider"}
        if plan.get("caption_overrides"):
            clip.setdefault("overrides", {}).update(plan["caption_overrides"])
        if cfg["highlight"].get("color") and style.keyword_color:
            clip.setdefault("overrides", {})["keyword_color"] = style.keyword_color
    tracks["captions"]["clips"] = caption_clips

    # Sound effects (each sound on as many tracks as needed so none overlap).
    sfx_clips = []
    for file, times, volume in sound_effects(cfg, zooms, overlay_events):
        m = media.add(file)
        for t in times:
            at = start + t
            duration = min(m["duration"], main_end - at)
            if duration * fps < 1:
                continue
            sfx_clips.append({"id": ids.next("s"), "type": "audio", "media": m["id"],
                              "start": round(at, 6), "duration": round(duration, 6),
                              "in": 0.0, "out": round(duration, 6), "volume": float(volume)})
    # AI voice-overs (from the AI edit), placed where the plan says, on the voice-over track.
    voice_clips = []
    for line in plan.get("voiceovers", []):
        at = remap_time(line["at"], segments, side="next")
        if at is None:
            continue
        m = media.add(line["file"])
        duration = min(m["duration"], main_end - (start + at))
        if duration * fps < 1:
            continue
        voice_clips.append({"id": ids.next("a"), "type": "audio", "media": m["id"],
                            "start": round(start + at, 6), "duration": round(duration, 6),
                            "in": 0.0, "out": round(duration, 6), "volume": 1.0})
    if voice_clips:
        replace_track(project, "voiceover", "audio",
                      [("Voice-over", lane) for lane in assign_lanes(voice_clips)],
                      role="voiceover")

    sfx_lanes = assign_lanes(sfx_clips) or [[]]
    replace_track(project, "sfx", "audio", [("Sound effects", lane) for lane in sfx_lanes],
                  role="sfx")

    project["media"] = media.as_list()
    return project


class ClipIds:
    def __init__(self):
        self.n = 0

    def next(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"


def replace_track(project, track_id, kind, lanes, role=None):
    """Replace the track `track_id` with one track per lane (same position in the list)."""
    index = next(i for i, t in enumerate(project["tracks"]) if t["id"] == track_id)
    new = []
    for n, (name, clips) in enumerate(lanes):
        track = {"id": track_id if n == 0 else f"{track_id}{n + 1}", "kind": kind,
                 "name": name, "clips": clips}
        if role:
            track["role"] = role
        new.append(track)
    if not new:
        new = [dict(project["tracks"][index])]
    project["tracks"][index:index + 1] = new


def caption_groups(words, style, video_length):
    """Caption clips (times relative to the cut video) exactly as the captions show them."""
    groups = chunk_words(words, style)
    clips = []
    for lines, end in zip(groups, group_end_times(groups)):
        flat = [w for line in lines for w in line]
        start = flat[0].start
        end = min(end, video_length)
        if end - start < 0.01:
            continue
        clips.append({
            "type": "caption", "start": start, "duration": round(end - start, 6),
            "style": style.name, "highlight_keywords": True,
            "words": [{"text": w.text, "start": round(w.start - start, 3),
                       "end": round(min(w.end, end) - start, 3), "highlight": w.highlight}
                      for w in flat],
        })
    return clips


def add_branding_clip(main, media, ids, piece, at, fps):
    """Put an intro/outro (image or clip) on the main track at `at`. Returns where it ends."""
    path, seconds = piece
    m = media.add(path)
    if m["kind"] == "image":
        duration = frame_index(seconds, fps) / fps
        main.append({"id": ids.next("v"), "type": "image", "media": m["id"],
                     "start": round(at, 6), "duration": round(duration, 6)})
    else:
        duration = int(m["duration"] * fps + 1e-6) / fps
        main.append({"id": ids.next("v"), "type": "video", "media": m["id"],
                     "start": round(at, 6), "duration": round(duration, 6),
                     "in": 0.0, "out": round(duration, 6), "fit": "fill"})
    return at + duration


def watermark_clip(m, branding, start, length, ids):
    """The logo as an overlay clip over the cut video (same place as before: corner margins)."""
    width = float(branding["watermark_width"])
    height = round(width * m["height"] / m["width"]) if m.get("width") else width
    position = branding.get("watermark_position", "top_left")
    if position not in ("top_left", "top_right", "bottom_left", "bottom_right"):
        position = "top_left"
    left = 40 if position.endswith("left") else 1080 - width - 40 - 170
    top = 170 if position.startswith("top") else 1920 * 0.8 - height - 30
    return {"id": ids.next("o"), "type": "image", "media": m["id"],
            "start": round(start, 6), "duration": round(length, 6),
            "x": round(left + width / 2, 2), "y": round(top + height / 2, 2),
            "width": width, "height": max(1.0, float(height)),
            "opacity": float(branding["watermark_opacity"]), "animation": "none"}


def branding_piece(branding, name):
    value = branding.get(name)
    if not value:
        return None
    path = project_path(value)
    if not path.exists():
        raise EditorError(f"{name} file not found: {path}")
    return (path, float(branding.get(f"{name}_duration", 2.0)))


def sound_effects(cfg, zooms, overlay_events):
    """[(file, [times], volume)] for the pop and whoosh sounds (if switched on and present)."""
    s = cfg["sfx"]
    if not s.get("enabled"):
        return []
    result = []
    volume = float(s.get("volume", 0.4))
    whoosh_times = sorted({t for _amount, ranges in zooms[:1] for r in ranges for t in r})
    for key, times in (("whoosh", whoosh_times), ("pop", [e.start for e in overlay_events])):
        if not s.get(key):
            continue
        path = project_path(s[key])
        if not path.exists():
            print(f"  ! sound effect not found, skipping: {path}")
            continue
        # Start the whoosh slightly before the cut so it peaks on it.
        offset = 0.12 if key == "whoosh" else 0.0
        result.append((path, [max(0.0, t - offset) for t in times if t > 0.05], volume))
    return result
