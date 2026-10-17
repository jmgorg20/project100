"""Shared helpers for the motion-graphics tests."""

import functools
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from autoedit import PROJECT_DIR

CLI = PROJECT_DIR / "desktop" / "graphics" / "render-cli.mjs"


@functools.lru_cache(maxsize=None)
def chromium_available():
    """True when Node + Playwright's Chromium can draw graphics here."""
    node = shutil.which("node")
    if not node or not CLI.exists() or not (PROJECT_DIR / "desktop" / "node_modules"
                                            / "playwright-core").exists():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "jobs.json"
        spec.write_text(json.dumps({"jobs": []}), encoding="utf-8")
        done = subprocess.run([node, str(CLI), str(spec)], capture_output=True, text=True,
                              timeout=120)
    return done.returncode == 0


needs_chromium = pytest.mark.skipif(not chromium_available(),
                                    reason="needs Node.js with Playwright's Chromium")


def graphic(clip_id, template, start, duration, x=0.5, y=0.5, **params):
    clip = {"id": clip_id, "type": "graphic", "start": start, "duration": duration,
            "template": template, "x": x, "y": y}
    if params:
        clip["params"] = params
    return clip


def add_graphics_track(project, clips, track_id="graphics"):
    project["tracks"].append({"id": track_id, "kind": "graphics", "name": "Graphics",
                              "clips": list(clips)})
    return project


def draw_stills(jobs, folder):
    """Draw jobs (with `stills`) with the command-line renderer; returns the sidecar dicts."""
    spec = Path(folder) / "jobs.json"
    spec.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    done = subprocess.run([shutil.which("node"), str(CLI), str(spec)], capture_output=True,
                          text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-500:] + done.stderr[-500:]
    return {j["id"]: json.loads(Path(j["meta"]).read_text(encoding="utf-8")) for j in jobs}
