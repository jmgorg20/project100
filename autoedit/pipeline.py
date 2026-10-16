"""The full edit, step by step. `edit_video()` is what `python editor.py edit` runs."""

import shutil
import time
from pathlib import Path

from . import PROJECT_DIR
from .captions import build_ass, fonts_from_config
from .config import project_path
from .cuts import (alternate_zoom, find_removals, keep_segments, remap_range, remap_time,
                   remap_words, snap_to_frames, total_length)
from .errors import EditorError
from .ffmpeg_tools import (check_ffmpeg, detect_silences, filter_script_args, probe,
                           probe_video_with_audio, run_ffmpeg)
from .grades import grade_filter
from .highlight import mark_keywords
from .overlays import OverlayEvent, find_trigger_events, load_triggers, schedule
from .previews import copy_fonts
from .render import RenderJob, build, intro_outro_command
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


def edit_video(video, cfg, transcript=None, plan=None, screen=None, layout=None, output=None):
    """Edit one video. Returns the path of the finished MP4."""
    started = time.time()
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

    work_root = project_path(cfg["work_folder"])
    job_dir = work_root / f"{video.stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    job_dir.mkdir(parents=True, exist_ok=True)
    out_folder = project_path(cfg["output"]["folder"])
    output = Path(output).resolve() if output else unique_output_path(out_folder, video.stem)

    try:
        # 1. Transcribe (or load an existing transcript).
        print("[1/6] Transcript")
        if transcript:
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
        grade_ranges = []
        for gr in plan.get("grades", []):
            mapped = remap_range(gr["start"], gr["end"], segments)
            if mapped:
                grade_ranges.append((grade_filter(gr["grade"]), *mapped))

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
                                                   item["position"]))
        overlay_events = schedule(overlay_events, new_length, caption_zone,
                                  top_blocked=layout == "pip")
        for ev in overlay_events:
            print(f"  > {ev.file.name} at {ev.start:.1f}s ({ev.position})")
        if not overlay_events:
            print("  > none")

        # 5. Captions.
        print("[5/6] Captions")
        ass_name = None
        if cfg["captions"].get("enabled", True) and cut_words:
            copy_fonts(cfg["captions"]["fonts_folder"], job_dir / "fonts")
            ass_text = build_ass(cut_words, style, fonts_from_config(cfg["captions"]),
                                 zone=caption_zone if layout == "split" else None,
                                 fonts_folder=job_dir / "fonts")
            ass_name = "captions.ass"
            (job_dir / ass_name).write_text(ass_text, encoding="utf-8")
            print(f"  > {style.name}: {ass_text.count('Dialogue:')} caption events")
        else:
            print("  > captions off")

        # 6. Render.
        print("[6/6] Rendering")
        branding = cfg["branding"]
        watermark = None
        if branding.get("watermark"):
            wm_file = project_path(branding["watermark"])
            if not wm_file.exists():
                raise EditorError(f"Watermark file not found: {wm_file}")
            watermark = {"file": wm_file, "width": branding["watermark_width"],
                         "opacity": branding["watermark_opacity"],
                         "position": branding["watermark_position"]}
        sfx = sound_effects(cfg, zooms, overlay_events)
        intro = branding_piece(branding, "intro")
        outro = branding_piece(branding, "outro")
        main_out = job_dir / "main.mp4" if (intro or outro) else output

        job = RenderJob(
            video=screen if layout == "screen" and screen else video,
            segments=segments, output=main_out, fps=fps, layout=layout, screen=screen,
            zooms=zooms, anchor_y=float(cfg["zoom"]["anchor_y"]),
            grade=grade_filter(cfg["grade"]), grade_ranges=grade_ranges,
            overlays=overlay_events, ass_file=ass_name, watermark=watermark, sfx=sfx,
            loudness=cfg["audio"]["loudness"], true_peak=cfg["audio"]["true_peak"],
            crf=cfg["output"]["crf"], encoder_speed=cfg["output"]["encoder_speed"],
            audio_bitrate=cfg["output"]["audio_bitrate"],
        )
        inputs, graph, outputs = build(job)
        script = job_dir / "filters.txt"
        script.write_text(graph, encoding="utf-8")
        run_ffmpeg(inputs + filter_script_args(script) + outputs,
                   "rendering the edit", cwd=job_dir)

        if intro or outro:
            o = cfg["output"]
            inputs, graph, outputs = intro_outro_command(
                main_out, intro, outro, fps, o["crf"], o["encoder_speed"], o["audio_bitrate"],
                output, probe)
            script = job_dir / "concat.txt"
            script.write_text(graph, encoding="utf-8")
            run_ffmpeg(inputs + filter_script_args(script) + outputs,
                       "adding intro/outro", cwd=job_dir)
    except BaseException:
        print(f"  (temporary files kept for troubleshooting in {job_dir})")
        raise

    if not cfg.get("keep_work_files"):
        shutil.rmtree(job_dir, ignore_errors=True)
    minutes = (time.time() - started) / 60
    print(f"Done in {minutes:.1f} min -> {output}")
    return output


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
