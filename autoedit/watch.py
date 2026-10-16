"""`python editor.py watch` - edit every new video that appears in inbox/."""

import shutil
import time
import traceback
from pathlib import Path

from . import PROJECT_DIR
from .errors import EditorError
from .ffmpeg_tools import VIDEO_EXTENSIONS, check_ffmpeg
from .pipeline import edit_video


def move_to(path, folder):
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    n = 2
    while target.exists():
        target = folder / f"{path.stem}_{n}{path.suffix}"
        n += 1
    shutil.move(str(path), str(target))
    return target


def process_inbox_once(inbox, cfg, sizes):
    """Edit every finished video in the inbox. `sizes` remembers file sizes between checks."""
    done, failed = inbox / "done", inbox / "failed"
    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        size = path.stat().st_size
        # Only start when the file stopped growing (finished copying).
        if sizes.get(path) != size:
            sizes[path] = size
            continue
        sizes.pop(path, None)
        try:
            edit_video(path, cfg)
            print(f"Original moved to {move_to(path, done)}\n")
        except EditorError as exc:
            print(f"ERROR: {exc}")
            print(f"Moved {path.name} to {move_to(path, failed)}\n")
        except Exception:
            traceback.print_exc()
            print(f"Moved {path.name} to {move_to(path, failed)}\n")


def watch(cfg, inbox=None):
    check_ffmpeg()
    inbox = Path(inbox or PROJECT_DIR / "inbox")
    inbox.mkdir(exist_ok=True)
    interval = float(cfg["watch"].get("interval_seconds", 5))
    sizes = {}
    print(f"Watching {inbox} for new videos. Press Ctrl+C to stop.")
    while True:
        process_inbox_once(inbox, cfg, sizes)
        time.sleep(interval)
