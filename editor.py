"""Auto video editor - command line.

  python editor.py edit inbox/myvideo.mp4 --style 2
  python editor.py watch
  python editor.py styles
  python editor.py check
  python editor.py render output/myvideo_edited.project.json
  python editor.py frame output/myvideo_edited.project.json --time 3.5

Run  python editor.py edit --help  for all options.

For the desktop app: --json prints progress as JSON lines on stdout (logs go to stderr), and
--stdin-control stops the job when "cancel" is written to stdin or stdin is closed.
"""

import argparse
import contextlib
import sys
import threading
from pathlib import Path

from autoedit.config import apply_preset, load_config, project_path
from autoedit.errors import EditorError
from autoedit.grades import GRADES
from autoedit.styles import list_styles


def build_parser():
    styles = ", ".join(f"{s.number}={s.name}" for s in list_styles())
    parser = argparse.ArgumentParser(description="Auto video editor for TikTok / Facebook Reels")
    parser.add_argument("--config", help="use a different settings file (default: config.yaml)")
    parser.add_argument("--json", action="store_true",
                        help="print progress as JSON lines on stdout (for the desktop app)")
    parser.add_argument("--stdin-control", action="store_true",
                        help='stop when "cancel" is written to stdin, or stdin closes')
    sub = parser.add_subparsers(dest="command", required=True)

    edit = sub.add_parser("edit", help="edit one video")
    edit.add_argument("video", help="the raw talking video (or a screen recording with "
                                    "--layout screen)")
    edit.add_argument("--style", help=f"caption style number or name: {styles}")
    edit.add_argument("--grade", help=f"colour grade: {', '.join(GRADES)}")
    edit.add_argument("--lang", dest="language", help="speech language code (default tl)")
    edit.add_argument("--preset", help="pacing preset from config.yaml (fast, relaxed...)")
    edit.add_argument("--provider", choices=["groq", "local"], help="transcription service")
    edit.add_argument("--transcript", help="use this word-timestamp JSON instead of transcribing")
    edit.add_argument("--plan", help="extra per-video instructions (JSON, see README)")
    edit.add_argument("--screen", help="screen recording to combine with the face video")
    edit.add_argument("--layout", choices=["face", "split", "pip", "screen"],
                      help="face (default), split (screen top / face bottom), pip (face in a "
                           "corner), screen (screen recording only)")
    edit.add_argument("--silence", type=float, dest="silence_threshold",
                      help="cut pauses longer than this many seconds")
    edit.add_argument("--zoom", type=float, dest="zoom_amount", help="punch-in zoom, e.g. 1.15")
    edit.add_argument("--no-captions", action="store_true", help="do not burn in captions")
    edit.add_argument("--output", help="where to save the finished video")
    edit.add_argument("--keep-work", action="store_true", help="keep temporary files in work/")
    edit.add_argument("--project-only", action="store_true",
                      help="only make the project file (.project.json), do not render")

    sub.add_parser("watch", help="edit every new video dropped into inbox/")

    styles_cmd = sub.add_parser("styles", help="make a preview picture of every caption style")
    styles_cmd.add_argument("--video", help="use a frame from this video as the background")
    styles_cmd.add_argument("--no-guides", action="store_true",
                            help="hide the red areas that mark the app's buttons")

    sub.add_parser("check", help="check that FFmpeg and your API key are set up")

    render = sub.add_parser("render", help="render a project file (.project.json) to MP4")
    render.add_argument("project", help="the .project.json file")
    render.add_argument("--output", help="where to save the video (default: next to the "
                                         "project, <name>_render.mp4)")
    render.add_argument("--height", type=int, choices=[1920, 1280, 960],
                        help="export size: 1920 = 1080x1920 (default), 1280 = 720x1280, "
                             "960 = 540x960")
    render.add_argument("--crf", type=int, help="quality: lower = better and bigger (18-28)")
    render.add_argument("--speed", dest="encoder_speed",
                        choices=["ultrafast", "veryfast", "fast", "medium", "slow"],
                        help="encoder speed")
    render.add_argument("--fps", type=int, choices=[24, 25, 30, 50, 60],
                        help="export frame rate (default: the project's)")
    render.add_argument("--keep-work", action="store_true", help="keep temporary files")

    frame = sub.add_parser("frame", help="render the exact frame at a time to a PNG")
    frame.add_argument("project", help="the .project.json file")
    frame.add_argument("--time", type=float, required=True, help="seconds on the timeline")
    frame.add_argument("--output", help="where to save the PNG")

    validate = sub.add_parser("validate", help="check a project file and list any problems")
    validate.add_argument("project", help="the .project.json file")

    ai = sub.add_parser("ai-edit", help="AI edit: describe the finished video in plain words")
    ai.add_argument("videos", nargs="+", help="one or more videos (all get the same "
                                              "instruction, one after another)")
    ai.add_argument("-i", "--instruction", default="", help='e.g. "Fast edit, big yellow '
                    'captions, show receipt.png when I say resibo"')
    ai.add_argument("--instruction-file", help="read the instruction from a UTF-8 text file")
    ai.add_argument("--photos", nargs="*", default=[], help="photos the AI may pop in")
    ai.add_argument("--provider", choices=["groq", "anthropic"], help="AI provider")
    ai.add_argument("--model", help="AI model (default from config.yaml, ai:)")
    ai.add_argument("--transcribe-with", choices=["groq", "local"],
                    help="speech-to-text service (default from config.yaml)")
    ai.add_argument("--no-render", action="store_true",
                    help="stop after the project and plan (review before rendering)")
    ai.add_argument("--plan-file", help="use this plan (.plan.json) as is: no AI call")
    ai.add_argument("--previous-plan", help="change this plan (.plan.json) with the "
                                            "instruction (a follow-up)")
    ai.add_argument("--output", help="where to save the video (one video only)")
    ai.add_argument("--max-generation-minutes", type=float,
                    help="AI pictures/clips/voice: stop generating after this many minutes")
    ai.add_argument("--max-ai-clips", type=int, help="at most this many AI pictures/clips")
    ai.add_argument("--generation-settings", help="generation settings file "
                                                  "(default: generation.json)")
    ai.add_argument("--broll-library", help="folder with your own B-roll clips/pictures "
                                            "(default from config.yaml, broll:)")
    ai.add_argument("--no-stock", action="store_true",
                    help="do not search Pexels/Pixabay for B-roll")
    ai.add_argument("--graphics", help="motion graphics: auto (when the instruction asks), off, "
                                       "or a style: promoter, calm_documentary, meme, news, "
                                       "luxury, minimal (default from config.yaml, graphics:)")

    gx = sub.add_parser("graphics", help="add motion graphics (pop-up words, cards, counters, "
                                         "arrows, emoji) to a project with the Director")
    gx.add_argument("project", help="a .project.json (saved in place unless --output)")
    gx.add_argument("--style", default="promoter", help="promoter, calm_documentary, meme, news, "
                                                        "luxury, minimal")
    gx.add_argument("-i", "--instruction", default="", help="what you want, in plain words")
    gx.add_argument("--provider", choices=["groq", "anthropic"], help="AI provider")
    gx.add_argument("--model", help="AI model")
    gx.add_argument("--no-ai", action="store_true", help="simple rule-based graphics, no AI call")
    gx.add_argument("--output", help="save the new project here instead")
    gr = sub.add_parser("graphics-regenerate", help="give one graphic another look")
    gr.add_argument("project")
    gr.add_argument("--clip", required=True, help="the graphic's clip id")
    gr.add_argument("--template", help="use this template")
    gr.add_argument("--provider", choices=["groq", "anthropic"], help="ask the AI (default: rules)")
    gr.add_argument("--model")
    gc = sub.add_parser("graphics-check", help="before export: graphics on the face, off the "
                                               "screen, on the captions, hard to read")
    gc.add_argument("project")
    gj = sub.add_parser("graphics-jobs", help="the graphics of a project that still need drawing "
                                              "(for the desktop app)")
    gj.add_argument("project")
    gj.add_argument("--draw", action="store_true", help="draw them now (needs Node.js + a browser)")
    sub.add_parser("graphics-catalog", help="list the graphics templates")

    sub.add_parser("ui-data", help="print caption styles and layout facts for the desktop app")

    info = sub.add_parser("media-info", help="read length, size and sound of media files "
                                             "(for adding them to a project)")
    info.add_argument("files", nargs="+")
    pk = sub.add_parser("peaks", help="waveform outline of a file's sound (cached)")
    pk.add_argument("file")
    pk.add_argument("--per-second", type=int, default=50)
    rt = sub.add_parser("retranscribe", help="transcribe part of a project's timeline again and "
                                              "replace the captions there (saves the project)")
    rt.add_argument("project")
    rt.add_argument("--start", type=float, required=True, help="timeline seconds")
    rt.add_argument("--end", type=float, required=True, help="timeline seconds")
    br = sub.add_parser("broll", help="find or make one B-roll item: from your library, free "
                                      "stock, or AI. With a project: --clip ID gives that clip "
                                      "another one; --new adds a clip (saves the project)")
    br.add_argument("project", nargs="?", help="a .project.json (optional)")
    br.add_argument("--clip", help="the B-roll clip to find another for / regenerate")
    br.add_argument("--new", action="store_true", help="add a new B-roll clip")
    br.add_argument("--at", type=float, default=0.0, help="--new: timeline seconds")
    br.add_argument("--duration", type=float, help="seconds on screen (default 3)")
    br.add_argument("--kind", choices=["image", "video"])
    br.add_argument("--position", choices=["full", "top", "center"])
    br.add_argument("--prompt", help="what to show, in English")
    br.add_argument("--search", help="2-4 keywords for your library and stock sites")
    br.add_argument("--style", choices=["realistic", "cartoon", "drawing", "low_poly",
                                        "stylized_3d", "anime"])
    br.add_argument("--source", choices=["auto", "library", "stock", "ai"])
    br.add_argument("--quality", choices=["draft", "final"], default="final",
                    help="AI generation: quick draft tier, or the final tier")
    br.add_argument("--exclude", action="append", default=[],
                    help="a file or stock id (pexels-123) not to use")
    br.add_argument("--new-version", action="store_true",
                    help="AI: a different version of the same prompt")
    br.add_argument("--library", help="your B-roll folder (default from config.yaml)")
    br.add_argument("--download-folder", help="where stock downloads are kept")
    br.add_argument("--generation-settings", help="generation settings file "
                                                  "(default: generation.json)")
    trk = sub.add_parser("track", help="find your hands / face in a video, or in a project's main "
                                        "video (saves the points in the project)")
    trk.add_argument("source", help="a video, or a .project.json")
    trk.add_argument("--ranges", help='source seconds to look at, e.g. "2-5.5,9-12" (default: the '
                                      "moments the project's tracked effects need, else all)")
    trk.add_argument("--points", nargs="*", help="which points to keep (default: all, or the "
                                                 "ones the project's effects use)")
    trk.add_argument("--output", help="a video only: write the points to this .json file")
    sub.add_parser("track-status", help="can this PC track hands/face? (MediaPipe + models)")
    tm = sub.add_parser("track-models", help="the MediaPipe model files tracking needs: shows "
                                             "what they are, and downloads them only if you say so")
    tm.add_argument("--download", nargs="+", choices=["hand", "face", "pose", "segment"],
                    help="download these models into models/tracking/")
    tm.add_argument("--yes", action="store_true", help="yes, download them (you read the model pages)")
    th = sub.add_parser("thumbs", help="small pictures along a video for the timeline (cached)")
    th.add_argument("file")
    th.add_argument("--height", type=int, default=120)

    gen_common = argparse.ArgumentParser(add_help=False)
    gen_common.add_argument("--generation-settings",
                            help="generation settings file (default: generation.json)")
    hw = sub.add_parser("hardware", parents=[gen_common],
                        help="detect the GPU, VRAM, RAM and free disk space")
    hw.add_argument("--refresh", action="store_true", help="(detection always runs; kept for "
                                                           "clarity in scripts)")
    gs = sub.add_parser("gen-status", parents=[gen_common],
                        help="AI generation: hardware, WanGP models, quality tiers")
    gs.add_argument("--check-wangp", action="store_true",
                    help="start WanGP to read its model list and installed models")
    bench = sub.add_parser("benchmark", parents=[gen_common],
                           help="short test of every installed tier, one GPU job at a time")
    bench.add_argument("--type", nargs="*", choices=["image", "video", "voice"],
                       help="content types to test (default: all)")
    bench.add_argument("--tier", nargs="*", choices=["Draft", "Low", "Mid", "High"])
    comp = sub.add_parser("compare", parents=[gen_common],
                          help="same prompt and seed on every installed tier, side by side")
    comp.add_argument("--type", required=True, choices=["image", "video", "voice"])
    comp.add_argument("--prompt", required=True)
    comp.add_argument("--seed", type=int, default=1234)
    gc = sub.add_parser("gen-config", parents=[gen_common],
                        help="save the WanGP folder and WanGP's Python")
    gc.add_argument("--wangp-folder")
    gc.add_argument("--wangp-python")
    st = sub.add_parser("set-tier", parents=[gen_common],
                        help="save your default tier (after Compare) or pin a tier")
    st.add_argument("--type", required=True, choices=["image", "video", "voice"])
    group = st.add_mutually_exclusive_group(required=True)
    group.add_argument("--default", choices=["Draft", "Low", "Mid", "High"])
    group.add_argument("--pin", choices=["Draft", "Low", "Mid", "High"])
    group.add_argument("--clear-default", action="store_true")
    group.add_argument("--unpin", action="store_true")

    estimate = sub.add_parser("estimate", help="estimated API cost of an AI edit (no API call)")
    estimate.add_argument("videos", nargs="+")
    estimate.add_argument("-i", "--instruction", default="")
    estimate.add_argument("--provider", choices=["groq", "anthropic"])
    estimate.add_argument("--model")
    return parser


def cmd_edit(args, reporter=None, cancel=None):
    from autoedit.pipeline import edit_video
    from autoedit.plan import load_plan

    overrides = {k: getattr(args, k) for k in
                 ("style", "grade", "language", "preset", "silence_threshold", "zoom_amount")}
    cfg = load_config(args.config, overrides)
    if args.provider:
        cfg["transcription"]["provider"] = args.provider
    if args.no_captions:
        cfg["captions"]["enabled"] = False
    if args.keep_work:
        cfg["keep_work_files"] = True
    plan = None
    if args.plan:
        plan = load_plan(args.plan, project_path(cfg["overlays"]["folder"]))
        # The plan changes style/grade/preset unless you also typed them on the command line.
        for key in ("style", "grade", "preset"):
            if plan.get(key) and overrides.get(key) is None:
                cfg[key] = plan[key]
        apply_preset(cfg)
    if args.project_only:
        from autoedit.pipeline import build_edit_project, unique_output_path
        from autoedit.project import save_project
        video = Path(args.video).resolve()
        target = Path(args.output).resolve() if args.output else \
            unique_output_path(project_path(cfg["output"]["folder"]), video.stem)
        job_dir = project_path(cfg["work_folder"]) / f"{video.stem}-project"
        project = build_edit_project(video, cfg, transcript=args.transcript, plan=plan,
                                     screen=args.screen, layout=args.layout, job_dir=job_dir)
        if not cfg.get("keep_work_files"):
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
        saved = save_project(project, target.with_suffix(".project.json"))
        print(f"Saved {saved}")
        if reporter:
            reporter.result(project=str(saved))
        return
    output = edit_video(args.video, cfg, transcript=args.transcript, plan=plan,
                        screen=args.screen, layout=args.layout, output=args.output,
                        reporter=reporter, cancel=cancel)
    if reporter:
        reporter.result(output=str(output), project=str(output.with_suffix(".project.json"))
                        if cfg["output"].get("save_project", True) else None)


def project_base_name(path):
    name = path.name
    return name[:-len(".project.json")] if name.endswith(".project.json") else path.stem


def unique_file(folder, stem, suffix):
    path = folder / f"{stem}{suffix}"
    n = 2
    while path.exists():
        path = folder / f"{stem}_{n}{suffix}"
        n += 1
    return path


def safe_output(project, project_file, output):
    """Refuse to write over one of the project's own media files."""
    from autoedit.errors import EditorError
    from autoedit.project import resolve_media_path
    import os
    output = Path(output).resolve()
    for m in project["media"]:
        source = resolve_media_path(m, project_file.parent).resolve()
        if os.path.normcase(str(source)) == os.path.normcase(str(output)):
            raise EditorError(f"The output {output.name} is one of the project's own media "
                              f"files. Choose another name.")
    return output


def cmd_render(args, reporter, cancel):
    import shutil
    import time
    from autoedit.project import load_project
    from autoedit.project_render import render_project

    cfg = load_config(args.config)
    project_file = Path(args.project).resolve()
    project = load_project(project_file)
    output = Path(args.output) if args.output else \
        unique_file(project_file.parent, project_base_name(project_file) + "_render", ".mp4")
    output = safe_output(project, project_file, output)
    o = cfg["output"]
    if args.fps and args.fps != project["settings"]["fps"]:
        project = {**project, "settings": {**project["settings"], "fps": args.fps}}
    export = {"crf": args.crf if args.crf is not None else o["crf"],
              "encoder_speed": args.encoder_speed or o["encoder_speed"],
              "audio_bitrate": o["audio_bitrate"], "height": args.height or 1920}
    work = project_path(cfg["work_folder"]) / f"render-{time.strftime('%Y%m%d-%H%M%S')}"
    print(f"Rendering {project_file.name} -> {output}")
    try:
        render_project(project, output, base_dir=project_file.parent, work_dir=work,
                       fonts_folder=project_path(cfg["captions"]["fonts_folder"]),
                       export=export, reporter=reporter, cancel=cancel)
    finally:
        if not (args.keep_work or cfg.get("keep_work_files")):
            shutil.rmtree(work, ignore_errors=True)
    print(f"Done -> {output}")
    reporter.result(output=str(output))


def cmd_media_info(args, reporter):
    """Media entries (ids m1, m2, ... in order; the app gives them its own ids)."""
    from autoedit.errors import EditorError
    from autoedit.project import media_from_file
    media, errors = [], []
    for i, f in enumerate(args.files, start=1):
        try:
            entry = media_from_file(f, f"m{i}")
            media.append(entry)
            print(f"{entry['name']}: {entry['kind']}, {entry['duration']:.2f}s")
        except EditorError as exc:
            errors.append({"path": f, "message": str(exc)})
            print(f"{f}: {exc}")
    reporter.result(media=media, errors=errors)


def cmd_peaks(args, reporter):
    from autoedit.media_tools import peaks
    cfg = load_config(args.config)
    data = peaks(args.file, project_path(cfg["work_folder"]) / "cache" / "peaks",
                 per_second=args.per_second)
    print(f"{len(data['peaks'])} values, {data['per_second']} per second")
    reporter.result(**data)


def cmd_retranscribe(args, reporter):
    import shutil
    import time
    from autoedit.project import load_project, save_project
    from autoedit.retranscribe import retranscribe
    cfg = load_config(args.config)
    project_file = Path(args.project).resolve()
    project = load_project(project_file)
    work = project_path(cfg["work_folder"]) / f"retranscribe-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        if reporter:
            reporter.stage("transcript", "Listening again")
        project, count = retranscribe(project, project_file, cfg, args.start, args.end, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    save_project(project, project_file)
    print(f"{count} words between {args.start:.2f}s and {args.end:.2f}s; saved {project_file.name}")
    reporter.result(project=str(project_file), words=count)


def cmd_broll(args, reporter, cancel):
    from autoedit import broll
    from autoedit.project import load_project, media_from_file, save_project
    cfg = load_config(args.config)
    if args.library is not None:
        cfg["broll"]["library_folder"] = args.library
    project = clip = None
    project_file = Path(args.project).resolve() if args.project else None
    item, exclude = {}, list(args.exclude)
    if project_file:
        project = load_project(project_file)
    if args.clip:
        if project is None:
            raise EditorError("--clip needs the project file.")
        _track, clip = broll.find_overlay_clip(project, args.clip)
        meta = clip.get("broll") or {}
        media = next(m for m in project["media"] if m["id"] == clip["media"])
        item = {k: meta[k] for k in ("prompt", "search", "style", "position") if meta.get(k)}
        item.update(kind=clip["type"], duration=clip["duration"],
                    prompt=item.get("prompt") or clip.get("label") or Path(media["path"]).stem)
        exclude += [media["path"]] + ([meta["stock_id"]] if meta.get("stock_id") else [])
        if meta.get("source") == "ai" and not args.source:
            item["source"] = "ai"              # regenerate an AI item with AI
    elif args.new and project is None:
        raise EditorError("--new needs the project file.")
    for key in ("kind", "position", "prompt", "search", "style", "source", "duration"):
        value = getattr(args, key)
        if value is not None:
            item[key] = value
    folder = Path(args.download_folder) if args.download_folder else (
        (project_file.parent if project_file else project_path(cfg["output"]["folder"]))
        / "broll")
    new_version = args.new_version or bool(args.clip)
    file, meta, notes = broll.find_one(item, cfg, args.quality, generation_paths(args), reporter,
                                       cancel, folder, exclude, new_version)
    for note in notes:
        print(f"  ! {note}")
    if file is None:
        raise EditorError("No B-roll found or made. " + (" ".join(notes) or
                          "Add a B-roll folder, a stock key, or set up WanGP."))
    print(f"B-roll: {broll.describe_source(meta, file)}")
    if project is None:
        entry = media_from_file(file, "broll")
        reporter.result(file=str(file), media=entry, broll=meta, notes=notes)
        return
    entry = media_from_file(file, broll._new_id(project, "m"))
    if clip is not None:
        clip = broll.replace_clip_media(project, args.clip, entry, meta)
    else:
        clip = broll.add_clip(project, entry, meta, args.at, item.get("duration", 3.0),
                              item.get("position", "full"))
    save_project(project, project_file)
    print(f"Saved {project_file.name} (clip {clip['id']})")
    reporter.result(project=str(project_file), clip=clip["id"], file=str(file), broll=meta,
                    notes=notes)


def _parse_ranges(text):
    out = []
    for part in (text or "").split(","):
        if part.strip():
            a, _, b = part.partition("-")
            try:
                out.append((float(a), float(b)))
            except ValueError:
                raise EditorError(f"Cannot read the range '{part}'. Use e.g. --ranges 2-5.5,9-12")
    return out


def _source_ranges(project, media_id, margin=0.5):
    """Source-video seconds that the project's tracked effects show (through the main clips)."""
    from autoedit.project import clip_end
    main = next((t for t in project["tracks"] if t["kind"] == "video"), None)
    out = []
    for t in project["tracks"]:
        for fx in (t["clips"] if t["kind"] == "effect" else []):
            if fx["type"] != "trackfx":
                continue
            for c in (main["clips"] if main else []):
                if c.get("media") != media_id or c["type"] != "video":
                    continue
                a, b = max(fx["start"], c["start"]), min(clip_end(fx), clip_end(c))
                if b > a:
                    speed = float(c.get("speed", 1.0))
                    out.append((c["in"] + (a - c["start"]) * speed - margin,
                                c["in"] + (b - c["start"]) * speed + margin))
    return out


def cmd_track(args, reporter, cancel):
    import json
    from autoedit import tracking
    from autoedit.cache import Cache
    from autoedit.project import load_project, resolve_media_path, save_project
    cfg = load_config(args.config)
    cache = Cache(project_path(cfg["ai"]["cache_folder"]))
    source = Path(args.source).resolve()
    ranges = _parse_ranges(args.ranges)
    names = list(args.points) if args.points else None
    project = media_id = None
    if source.suffix.lower() == ".json" or source.name.endswith(".project.json"):
        project = load_project(source)
        main = next((t for t in project["tracks"] if t["kind"] == "video"), None)
        clip = next((c for c in (main["clips"] if main else []) if c["type"] == "video"), None)
        if clip is None:
            raise EditorError("This project has no main video to track.")
        media_id = clip["media"]
        media = next(m for m in project["media"] if m["id"] == media_id)
        video = resolve_media_path(media, source.parent)
        fx = [c for t in project["tracks"] if t["kind"] == "effect" for c in t["clips"] if c["type"] == "trackfx"]
        if not ranges:
            ranges = tracking.merge_ranges(_source_ranges(project, media_id)) or []
        if names is None:
            names = sorted({n for c in fx for n in tracking.point_names_for(c)}) or list(tracking.DEFAULT_POINTS)
    else:
        video = source
        if not video.exists():
            raise EditorError(f"Video not found: {video}")
    key = None
    track = None
    use_names = names or list(tracking.POINT_NAMES)
    from autoedit.cache import key_for
    key = key_for({"k": tracking.track_cache_key(cache, video, cfg), "ranges": ranges, "names": sorted(use_names)})
    cached = cache.get("tracks", key)
    if cached:
        track = tracking.Track.from_json(cached)
        print("Using the saved track for this video.")
    else:
        reporter.stage("tracking", "Following your hands and face")
        track = tracking.detect_video(video, cfg, ranges=ranges or None, names=use_names,
                                      reporter=reporter, cancel=cancel)
        cache.put("tracks", key, track.to_json())
    found = {n: round(sum(1 for c in p.c if c >= 0.5) / max(1, len(p)), 3) for n, p in track.points.items()}
    for n, share in found.items():
        print(f"  {n}: found in {share * 100:.0f}% of the tracked time")
    if project is None:
        if args.output:
            Path(args.output).write_text(json.dumps(track.to_json(), ensure_ascii=False), encoding="utf-8")
            print(f"Saved {args.output}")
        reporter.result(track=track.to_json(), found=found)
        return
    project.setdefault("tracking", {})[media_id] = track.to_json()
    save_project(project, source)
    print(f"Saved the points in {source.name}")
    reporter.result(project=str(source), media=media_id, found=found)


def cmd_track_status(args, reporter):
    from autoedit import tracking
    cfg = load_config(args.config)
    st = tracking.status(cfg)
    for line in st["problems"]:
        print(f"!!  {line}")
    print(f"MediaPipe: {'installed' if st['installed'] else 'not installed'}   hands: {st['hands']}   "
          f"face/body: {st['face']}   pose: {st['pose']}")
    reporter.result(**st, models=tracking.model_info())


def cmd_track_models(args, reporter):
    from autoedit import tracking
    info = tracking.model_info()
    for m in info:
        print(f"{m['kind']:5} {m['file']}  ({m['size']})  {'present' if m['present'] else 'not downloaded'}")
        print(f"      from {m['url']}")
        print(f"      read the model card first: {m['page']}")
    if not args.download:
        print("\nNothing was downloaded. The models are Google's MediaPipe models, with their own terms; "
              "this app never downloads one by itself. To download: track-models --download hand face --yes")
        reporter.result(models=info, downloaded=[])
        return
    if not args.yes:
        raise EditorError("Add --yes to confirm the download (after reading the model cards above).")
    paths = tracking.download_models(args.download)
    for kind, path in paths.items():
        print(f"Saved {path}")
    reporter.result(models=tracking.model_info(), downloaded=list(paths))


def cmd_thumbs(args, reporter):
    from autoedit.media_tools import thumbs
    cfg = load_config(args.config)
    data = thumbs(args.file, project_path(cfg["work_folder"]) / "cache" / "thumbs",
                  height=args.height)
    print(f"{len(data['files'])} pictures, one every {data['every']:g}s")
    reporter.result(**data)


def cmd_frame(args, reporter, cancel):
    import shutil
    import time
    from autoedit.project import load_project
    from autoedit.project_render import render_frame

    cfg = load_config(args.config)
    project_file = Path(args.project).resolve()
    project = load_project(project_file)
    output = Path(args.output) if args.output else project_file.parent / (
        f"{project_base_name(project_file)}_frame_{args.time:.2f}s.png")
    output = safe_output(project, project_file, output)
    work = project_path(cfg["work_folder"]) / f"frame-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        render_frame(project, args.time, output, base_dir=project_file.parent, work_dir=work,
                     fonts_folder=project_path(cfg["captions"]["fonts_folder"]),
                     reporter=reporter, cancel=cancel)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"Saved {output}")
    reporter.result(output=str(output), time=args.time)


def read_plan_file(path):
    import json
    from autoedit.errors import EditorError
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EditorError(f"Could not read the plan file {path}: {exc}")
    return data["plan"] if isinstance(data, dict) and "plan" in data else data


def cmd_ai_edit(args, reporter, cancel):
    from autoedit.ai_edit import ai_edit_video
    from autoedit.errors import Cancelled, EditorError

    cfg = load_config(args.config)
    if args.transcribe_with:
        cfg["transcription"]["provider"] = args.transcribe_with
    if args.broll_library is not None:
        cfg["broll"]["library_folder"] = args.broll_library
    if args.no_stock:
        cfg["broll"]["use_stock"] = False
    if args.output and len(args.videos) > 1:
        raise EditorError("--output works with one video only.")
    instruction = args.instruction
    if args.instruction_file:
        instruction = Path(args.instruction_file).read_text(encoding="utf-8-sig")
    plan = read_plan_file(args.plan_file) if args.plan_file else None
    previous = read_plan_file(args.previous_plan) if args.previous_plan else None
    results, failed = [], 0
    for index, video in enumerate(args.videos):
        reporter.event("item", index=index, total=len(args.videos), video=str(Path(video)))
        try:
            item = ai_edit_video(video, cfg, instruction, args.photos, args.provider,
                                 args.model, render=not args.no_render, output=args.output,
                                 previous_plan=previous, plan=plan, reporter=reporter,
                                 cancel=cancel, gen_paths=generation_paths(args),
                                 max_gen_minutes=args.max_generation_minutes,
                                 max_ai_clips=args.max_ai_clips, graphics=args.graphics)
            item.update(video=str(video), ok=True)
        except Cancelled:
            raise
        except EditorError as exc:
            if len(args.videos) == 1:
                raise
            failed += 1
            print(f"\nERROR ({Path(video).name}): {exc}", file=sys.stderr)
            item = {"video": str(video), "ok": False, "error": str(exc)}
            reporter.event("item_error", index=index, video=str(video), message=str(exc))
        results.append(item)
    if len(results) == 1:
        reporter.result(**results[0])
    else:
        reporter.result(items=results)
        print(f"\n{len(results) - failed} of {len(results)} videos done.")
    if failed:
        raise EditorError(f"{failed} of {len(results)} videos failed (see above).")


def cmd_estimate(args, reporter):
    from autoedit.ai_edit import estimate_cost
    cfg = load_config(args.config)
    items = []
    for video in args.videos:
        cost = estimate_cost(video, cfg, args.instruction, provider=args.provider,
                             model=args.model)
        print(f"{Path(video).name}: about {cost['text']} ({cost['provider']}, {cost['model']}"
              f"{', transcript saved' if cost['transcript_cached'] else ''})")
        items.append(dict(cost, video=str(video)))
    reporter.result(items=items)


def generation_paths(args):
    from autoedit.generation import Paths
    cfg = load_config(args.config)
    return Paths(args.generation_settings, project_path(cfg["work_folder"]) / "generation")


def cmd_hardware(args, reporter):
    from autoedit.hardware import describe, load_profile
    paths = generation_paths(args)
    profile, changed, previous = load_profile(paths.hardware, [str(paths.data)])
    print(describe(profile))
    for note in profile["notes"]:
        print(f"  note: {note}")
    if changed:
        print(f"  The hardware changed since last time (was: {describe(previous)}).")
    reporter.result(hardware=profile, summary=describe(profile), changed=changed)


def cmd_gen_status(args, reporter):
    from autoedit import generation
    info = generation.status(generation_paths(args), check_wangp=args.check_wangp)
    print(f"Hardware: {info['hardware_summary']}")
    for problem in info["setup_problems"] + info["problems"]:
        print(f"  ! {problem}")
    if info["wangp"]["error"]:
        print(f"  ! {info['wangp']['error']}")
    if info["wangp"]["version"]:
        print(f"WanGP {info['wangp']['version']} (models checked {info['wangp']['checked_at']})")
    for ctype, rows in info["tiers"].items():
        print(f"{ctype}:")
        for row in rows:
            avg = f", about {row['avg_seconds']:.0f}s here" if row["avg_seconds"] else ""
            print(f"  {row['name']:<5} {row['status']:<17} {row['model_name'] or '-'}{avg}")
    reporter.result(**info)


def cmd_benchmark(args, reporter, cancel):
    from autoedit import generation
    paths = generation_paths(args)
    info = generation.status(paths, check_wangp=True)
    if info["setup_problems"] or info["wangp"]["error"]:
        raise EditorError(" ".join(info["setup_problems"]) or info["wangp"]["error"])
    settings, _ = generation.load_settings(paths)
    types = args.type or list(generation.CONTENT_TYPES)
    results = generation.benchmark(paths, settings, info["hardware"]["key"], info["tiers"],
                                   types, args.tier, reporter=reporter, cancel=cancel)
    if not results:
        print("No installed tier to test.")
    for r in results:
        vram = f", peak VRAM about {r['peak_vram_mb']} MB" if r["peak_vram_mb"] else ""
        print(f"{r['content_type']} {r['tier']}: {r['reason']} in {r['seconds']:.1f}s{vram}")
    reporter.result(results=results)


def cmd_compare(args, reporter, cancel):
    from autoedit import generation
    paths = generation_paths(args)
    info = generation.status(paths, check_wangp=True)
    if info["setup_problems"] or info["wangp"]["error"]:
        raise EditorError(" ".join(info["setup_problems"]) or info["wangp"]["error"])
    settings, _ = generation.load_settings(paths)
    result = generation.compare(paths, settings, info["hardware"]["key"], info["tiers"],
                                args.type, args.prompt, args.seed, reporter=reporter,
                                cancel=cancel)
    for r in result["results"]:
        print(f"{r['tier']}: {r['reason']} in {r['seconds']:.1f}s -> {r['output'] or '-'}")
    print(f"Saved in {result['folder']}")
    reporter.result(**result)


def cmd_gen_config(args, reporter):
    from autoedit import generation
    from autoedit.wangp import check_setup
    paths = generation_paths(args)
    generation.save_wangp(paths, args.wangp_folder, args.wangp_python)
    settings, _ = generation.load_settings(paths)
    problems = check_setup(settings)
    print("Saved." + ("" if not problems else " " + " ".join(problems)))
    reporter.result(saved=True, problems=problems, settings_file=str(paths.settings))


def cmd_set_tier(args, reporter):
    from autoedit import generation
    paths = generation_paths(args)
    if args.default or args.clear_default:
        generation.save_choice(paths, "default_tier", args.type, args.default)
    else:
        generation.save_choice(paths, "pinned_tier", args.type, args.pin)
    settings, _ = generation.load_settings(paths)
    print(f"{args.type}: default {settings['default_tier'][args.type]}, "
          f"pinned {settings['pinned_tier'][args.type]}")
    reporter.result(default_tier=settings["default_tier"], pinned_tier=settings["pinned_tier"])


def cmd_graphics(args, reporter, cancel):
    from autoedit import director
    from autoedit.ai_edit import provider_settings
    from autoedit.cache import Cache
    from autoedit.project import load_project, save_project
    cfg = load_config(args.config)
    path = Path(args.project).resolve()
    project = load_project(path)
    provider = model = None
    if not args.no_ai:
        provider, model = provider_settings(cfg, args.provider, args.model)
    cache = Cache(project_path(cfg["ai"]["cache_folder"]))
    result = director.generate(project, cfg, args.instruction, args.style, provider, model, cache,
                               reporter, cancel, use_ai=not args.no_ai)
    if result is None:
        raise EditorError("Graphics are off (style 'off').")
    out = save_project(result["project"], Path(args.output).resolve() if args.output else path)
    print(f"{result['count']} graphics ({result['style']})" + (" - " + result["reason"] if result["reason"] else ""))
    for note in result["notes"]:
        print(f"  - {note}")
    reporter.result(project=str(out), count=result["count"], style=result["style"],
                    fallback=result["fallback"], reason=result["reason"], notes=result["notes"],
                    cost=result["cost"])


def cmd_graphics_regenerate(args, reporter, cancel):
    from autoedit import director
    from autoedit.ai_edit import provider_settings
    from autoedit.project import load_project, save_project
    cfg = load_config(args.config)
    path = Path(args.project).resolve()
    provider, model = provider_settings(cfg, args.provider, args.model) if args.provider else (None, None)
    result = director.regenerate_item(load_project(path), args.clip, cfg, provider=provider, model=model,
                                      cancel=cancel, template=args.template)
    save_project(result["project"], path)
    print(f"{args.clip}: now {result['clip']['template']}")
    reporter.result(project=str(path), clip=result["clip"], notes=result["notes"])


def cmd_graphics_check(args, reporter):
    from autoedit.graphics_check import check_project
    from autoedit.project import load_project
    path = Path(args.project).resolve()
    issues = check_project(load_project(path), path.parent, load_config(args.config))
    for i in issues:
        print(f"!!  {i['message']}")
    if not issues:
        print("OK  no problems found with the graphics")
    reporter.result(issues=issues)


def cmd_graphics_jobs(args, reporter, cancel):
    from autoedit import graphics
    from autoedit.project import load_project
    path = Path(args.project).resolve()
    project = load_project(path)
    if args.draw:
        graphics.ensure_assets(project, path.parent, reporter, cancel)
    jobs = graphics.missing_jobs(project, path.parent)
    print(f"{len(jobs)} graphic(s) still to draw")
    reporter.result(jobs=jobs, folder=str(graphics.cache_dir()))


def cmd_graphics_catalog(args, reporter):
    from autoedit import director, graphics
    cat = graphics.catalog()
    for t in cat["templates"]:
        print(f"{t['id']:20} {t['category']:8} {', '.join(t['moods'])}")
    reporter.result(catalog=cat, styles={k: {"label": v["label"], "tl": v["tl"], "about": v["about"]}
                                         for k, v in director.STYLES.items()})


def cmd_validate(args, reporter):
    from autoedit.project import load_project, timeline_duration
    project = load_project(args.project)
    clips = sum(len(t["clips"]) for t in project["tracks"])
    duration = timeline_duration(project)
    print(f"OK  {Path(args.project).name}: {len(project['tracks'])} tracks, {clips} clips, "
          f"{duration:.2f}s, {len(project['media'])} media files")
    reporter.result(valid=True, duration=duration, clips=clips)


def cmd_check(args):
    import os
    from autoedit.ffmpeg_tools import check_ffmpeg, ffmpeg_major_version
    from autoedit.transcribe import load_dotenv

    cfg = load_config(args.config)
    check_ffmpeg()
    print(f"OK  FFmpeg {ffmpeg_major_version()} found, with caption (libass) support")
    load_dotenv()
    provider = cfg["transcription"]["provider"]
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY", "")
        if key and not key.startswith("your_"):
            print(f"OK  GROQ_API_KEY is set (ends with ...{key[-4:]})")
        else:
            print("!!  GROQ_API_KEY is missing: create .env from .env.example")
    else:
        try:
            import faster_whisper  # noqa: F401
            print("OK  faster-whisper is installed (local transcription)")
        except ImportError:
            print("!!  faster-whisper is not installed: pip install faster-whisper")
    print(f"Style: {cfg['style']}   Grade: {cfg['grade']}   Preset: {cfg['preset']}   "
          f"Transcription: {provider}")


def watch_stdin(cancel):
    """Set `cancel` when the app writes "cancel" or closes stdin (so no render is orphaned)."""
    def run():
        try:
            for line in sys.stdin:
                if line.strip().lower() == "cancel":
                    break
        except (OSError, ValueError):
            pass
        cancel.set()
    threading.Thread(target=run, daemon=True).start()


def main(argv=None):
    args = build_parser().parse_args(argv)
    from autoedit.errors import Cancelled
    from autoedit.progress import JsonReporter, TextReporter

    cancel = threading.Event()
    if args.stdin_control:
        watch_stdin(cancel)
    if not args.json:
        return run_command(args, TextReporter(), cancel)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    reporter = JsonReporter(sys.stdout)
    # Ordinary messages go to stderr so stdout carries only JSON lines.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            return run_command(args, reporter, cancel, json_mode=True)
        except Cancelled:
            reporter.cancelled()
            return 130
        except Exception as exc:      # unexpected bug: still tell the app, with a traceback
            import traceback
            traceback.print_exc()
            reporter.error(f"Unexpected error: {exc}")
            return 1


def run_command(args, reporter, cancel, json_mode=False):
    from autoedit.errors import Cancelled
    try:
        if args.command == "edit":
            cmd_edit(args, reporter if json_mode else None, cancel)
        elif args.command == "render":
            cmd_render(args, reporter, cancel)
        elif args.command == "frame":
            cmd_frame(args, reporter, cancel)
        elif args.command == "validate":
            cmd_validate(args, reporter)
        elif args.command == "ai-edit":
            cmd_ai_edit(args, reporter, cancel)
        elif args.command == "estimate":
            cmd_estimate(args, reporter)
        elif args.command == "hardware":
            cmd_hardware(args, reporter)
        elif args.command == "gen-status":
            cmd_gen_status(args, reporter)
        elif args.command == "benchmark":
            cmd_benchmark(args, reporter, cancel)
        elif args.command == "compare":
            cmd_compare(args, reporter, cancel)
        elif args.command == "gen-config":
            cmd_gen_config(args, reporter)
        elif args.command == "set-tier":
            cmd_set_tier(args, reporter)
        elif args.command == "media-info":
            cmd_media_info(args, reporter)
        elif args.command == "peaks":
            cmd_peaks(args, reporter)
        elif args.command == "thumbs":
            cmd_thumbs(args, reporter)
        elif args.command == "graphics":
            cmd_graphics(args, reporter, cancel)
        elif args.command == "graphics-regenerate":
            cmd_graphics_regenerate(args, reporter, cancel)
        elif args.command == "graphics-check":
            cmd_graphics_check(args, reporter)
        elif args.command == "graphics-jobs":
            cmd_graphics_jobs(args, reporter, cancel)
        elif args.command == "graphics-catalog":
            cmd_graphics_catalog(args, reporter)
        elif args.command == "track":
            cmd_track(args, reporter, cancel)
        elif args.command == "track-status":
            cmd_track_status(args, reporter)
        elif args.command == "track-models":
            cmd_track_models(args, reporter)
        elif args.command == "retranscribe":
            cmd_retranscribe(args, reporter)
        elif args.command == "broll":
            cmd_broll(args, reporter, cancel)
        elif args.command == "ui-data":
            import json
            from autoedit.ui_data import ui_data
            sys.stdout.write(json.dumps(ui_data(), indent=1) + "\n")
        elif args.command == "watch":
            from autoedit.watch import watch
            watch(load_config(args.config))
        elif args.command == "styles":
            from autoedit.previews import render_previews
            made = render_previews(load_config(args.config), background=args.video,
                                   guides=not args.no_guides)
            print(f"Saved {len(made)} previews in {made[0].parent}")
        elif args.command == "check":
            cmd_check(args)
    except Cancelled:
        if json_mode:
            raise
        print("\nCancelled.")
        return 130
    except EditorError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        reporter.error(str(exc))
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
