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
    render.add_argument("--keep-work", action="store_true", help="keep temporary files")

    frame = sub.add_parser("frame", help="render the exact frame at a time to a PNG")
    frame.add_argument("project", help="the .project.json file")
    frame.add_argument("--time", type=float, required=True, help="seconds on the timeline")
    frame.add_argument("--output", help="where to save the PNG")

    validate = sub.add_parser("validate", help="check a project file and list any problems")
    validate.add_argument("project", help="the .project.json file")
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
