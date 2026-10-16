"""Auto video editor - command line.

  python editor.py edit inbox/myvideo.mp4 --style 2
  python editor.py watch
  python editor.py styles
  python editor.py check

Run  python editor.py edit --help  for all options.
"""

import argparse
import sys

from autoedit.config import apply_preset, load_config, project_path
from autoedit.errors import EditorError
from autoedit.grades import GRADES
from autoedit.styles import list_styles


def build_parser():
    styles = ", ".join(f"{s.number}={s.name}" for s in list_styles())
    parser = argparse.ArgumentParser(description="Auto video editor for TikTok / Facebook Reels")
    parser.add_argument("--config", help="use a different settings file (default: config.yaml)")
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

    sub.add_parser("watch", help="edit every new video dropped into inbox/")

    styles_cmd = sub.add_parser("styles", help="make a preview picture of every caption style")
    styles_cmd.add_argument("--video", help="use a frame from this video as the background")
    styles_cmd.add_argument("--no-guides", action="store_true",
                            help="hide the red areas that mark the app's buttons")

    sub.add_parser("check", help="check that FFmpeg and your API key are set up")
    return parser


def cmd_edit(args):
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
    edit_video(args.video, cfg, transcript=args.transcript, plan=plan, screen=args.screen,
               layout=args.layout, output=args.output)


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


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "edit":
            cmd_edit(args)
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
    except EditorError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
