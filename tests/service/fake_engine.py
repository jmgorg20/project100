"""A stand-in for `editor.py` used by the worker tests: it speaks the same JSON lines and writes the
same files, fast. AUTOEDIT_FAKE_ENGINE_MODE: ok | sleep (runs until stopped) | error (the engine refuses the
input) | crash (dies without a result) | leak (writes a project that points at a local file)."""

import json
import os
import shutil
import sys
import time
from pathlib import Path


def emit(**data):
    print(json.dumps(data), flush=True)


def main(argv):
    mode = os.environ.get("AUTOEDIT_FAKE_ENGINE_MODE", "ok")
    Path(os.environ.get("AUTOEDIT_FAKE_ENGINE_LOG", os.devnull)).write_text(json.dumps(argv)) if os.environ.get("AUTOEDIT_FAKE_ENGINE_LOG") else None
    args = [a for a in argv if a not in ("--json", "--stdin-control")]
    if "--config" in args:
        i = args.index("--config")
        del args[i:i + 2]
    command = args[0]
    emit(type="stage", stage="transcript", label="Listening")
    if mode == "sleep":
        for line in sys.stdin:                      # the worker closes stdin to stop us
            pass
        emit(type="cancelled")
        return 130
    if mode == "error":
        emit(type="error", message="The video has no sound.")
        return 1
    if mode == "crash":
        os._exit(3)
    emit(type="progress", stage="render", percent=50.0)
    if command == "render":
        out = Path(args[args.index("--output") + 1])
        project = json.loads(Path(args[1]).read_text())
        shutil.copy(project["media"][0]["path"], out)
        emit(type="result", output=str(out))
        return 0
    source = Path(args[1])
    out_dir = Path(args[args.index("--out") + 1])
    out_dir.mkdir(parents=True, exist_ok=True)
    video = out_dir / f"{source.stem}.mp4"
    shutil.copy(source, video)
    media_path = str(source) if mode != "leak" else "/home/secret/private.mp4"
    project = {"format": "autoedit-project", "version": 2, "name": source.stem, "meta": {"source": str(source)},
               "settings": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
               "media": [{"id": "m1", "kind": "video", "path": media_path, "duration": 2.0, "width": 360,
                          "height": 640, "has_audio": True}],
               "tracks": [{"id": "main", "kind": "video", "clips": [{"id": "v1", "type": "video", "media": "m1",
                                                                     "start": 0, "duration": 2.0, "in": 0, "out": 2.0}]}]}
    pfile = out_dir / f"{source.stem}.project.json"
    pfile.write_text(json.dumps(project))
    (out_dir / f"{source.stem}.plan.json").write_text(json.dumps({"plan": {}, "photos": {"a.png": str(source)}}))
    side = {"status": "ok", "input": str(source), "output": str(video), "project": str(pfile),
            "qc": {"passed": True, "clean": True, "failed": [], "checks": [{"id": "duration", "details": {"seconds": 2.0}}]},
            "opinions": {"note": "Not checked", "headline": "x"}, "cost": {"transcription": 0.002, "plan": 0.001},
            "args": argv}
    (out_dir / f"{source.stem}.json").write_text(json.dumps(side))
    time.sleep(0.2)
    emit(type="result", **side)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
