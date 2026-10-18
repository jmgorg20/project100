"""`python editor.py polish`: edit one video with a preset and a format, render it, check it, and
write a JSON sidecar for the workers that post it. No publishing happens here.

    polish(input) -> AI edit (preset, format) -> render -> quality checks (qc.py)
                  -> if a check failed and it can be fixed: fix, render again (once, within the
                     time limit) -> <name>.mp4 + <name>.project.json + <name>.json (the sidecar)

The sidecar is written last, so a worker that sees it can take the video. Its `qc` part is
objective (measured); `opinions` holds the AI's own description and is marked as not checked.
"""

import json
import os
import shutil
import time
from pathlib import Path

from .errors import Cancelled, EditorError

SIDECAR_VERSION = 1
FIXABLE = {"clipping", "safe_zones", "face", "dimensions", "duration", "valid_mp4", "av_sync"}
RERENDER = {"dimensions", "duration", "valid_mp4", "av_sync"}


class PolishError(EditorError):
    pass


def write_json(path, data):
    """Write atomically: a worker never reads a half-written sidecar."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def fix_for_retry(project, checks):
    """A fixed copy of the project for the failed checks that can be fixed, and what was done.
    Returns (project, actions) or (None, []) when nothing can be fixed."""
    import copy
    failed = {c["id"]: c for c in checks if not c["ok"]}
    fixable = set(failed) & FIXABLE
    if not fixable:
        return None, []
    project = copy.deepcopy(project)
    actions = []
    if "clipping" in fixable:
        audio = project["settings"].setdefault("audio", {})
        audio["normalize"] = True
        audio["true_peak"] = min(-2.0, float(audio.get("true_peak", -1.5)) - 0.5)
        for t in project["tracks"]:
            if t["kind"] == "audio" and t.get("role") in ("music", "sfx"):
                for c in t["clips"]:
                    c["volume"] = round(float(c.get("volume", 1.0)) * 0.7, 4)
        actions.append(f"sound: limit lowered to {audio['true_peak']} dB, music and sounds 30% quieter")
    bad = set()
    for check in ("safe_zones", "face"):
        if check in fixable:
            bad |= set(failed[check]["details"].get("clips") or [])
    if bad:
        removed = []
        for t in project["tracks"]:
            keep = []
            for c in t["clips"]:
                if c["id"] in bad and not c.get("locked"):
                    removed.append(c["id"])
                else:
                    keep.append(c)
            t["clips"] = keep
        if removed:
            actions.append(f"removed {len(removed)} graphic(s) on the face or outside the safe area: "
                           + ", ".join(removed))
    if fixable & RERENDER:
        actions.append("rendered again (" + ", ".join(sorted(fixable & RERENDER)) + ")")
    return (project, actions) if actions else (None, [])


def output_names(out_folder, stem, unique=True):
    out_folder = Path(out_folder)
    out_folder.mkdir(parents=True, exist_ok=True)
    name, n = stem, 2
    while unique and ((out_folder / f"{name}.mp4").exists() or (out_folder / f"{name}.json").exists()):
        name = f"{stem}_{n}"
        n += 1
    return {"video": out_folder / f"{name}.mp4", "project": out_folder / f"{name}.project.json",
            "sidecar": out_folder / f"{name}.json", "name": name}


def polish(input_path, cfg, preset=None, format=None, out_folder=None, instruction="", provider=None,
           model=None, inputs=None, reporter=None, cancel=None, check=True, retry=True,
           max_minutes=None, unique=True, name=None):
    """Polish one video (or, for Faceless / Voice-over with B-roll, one voice-over). Returns the
    sidecar dict (also written next to the video)."""
    from . import presets as pre
    from . import qc
    from .ai_edit import ai_edit_video, voiceover_edit
    from .config import project_path
    from .project import load_project, save_project
    from .project_render import render_project
    from .progress import TextReporter
    reporter = reporter or TextReporter()
    started = time.time()
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise PolishError(f"Not found: {input_path}")
    look = pre.get(preset, cfg) if preset else None
    out_folder = Path(out_folder or project_path(cfg["output"]["folder"]))
    names = output_names(out_folder, name or input_path.stem, unique)
    work = out_folder / ".polishing" / names["name"]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    limit = float(max_minutes if max_minutes is not None else (cfg.get("polish") or {}).get("max_minutes", 30))
    inputs = {k: v for k, v in (inputs or {}).items() if v}
    fmt_id = format if format is not None else (look["format"] if look else None)
    sidecar = {"tool": "Auto Video Editor polish", "version": SIDECAR_VERSION, "status": "failed",
               "input": str(input_path), "output": None, "project": None,
               "preset": look["id"] if look else None, "format": fmt_id, "instruction": instruction,
               "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
               "qc": None, "retries": [], "opinions": None, "error": None}
    try:
        reporter.stage("polish", f"Polishing {input_path.name}")
        draft = work / f"{names['name']}.mp4"
        if fmt_id == "voiceover_broll":
            broll = inputs.get("broll") or []
            item = voiceover_edit(input_path, broll, cfg, instruction, provider, model, render=True,
                                  output=draft, reporter=reporter, cancel=cancel, preset=preset)
        else:
            item = ai_edit_video(input_path, cfg, instruction, inputs.get("photos") or [], provider, model,
                                 render=True, output=draft, reporter=reporter, cancel=cancel, preset=preset,
                                 format=fmt_id, inputs={k: v for k, v in inputs.items() if k != "photos"})
        project_file = Path(item["project"])
        project = load_project(project_file)
        summary = item.get("summary") or {}
        sidecar["format"] = summary.get("format", fmt_id)
        sidecar["opinions"] = {
            "note": "The AI's own description of its edit. Not checked: opinions, not measurements.",
            "headline": summary.get("headline"), "details": summary.get("details") or []}
        sidecar["cost"] = summary.get("cost")
        report = None
        if check:
            reporter.stage("qc", "Checking the video")
            report = qc.run(draft, project, project_file.parent, cfg)
            reporter.event("qc", **report)
            first_render = time.time() - started
            if retry and not report["clean"]:
                fixed, actions = fix_for_retry(project, report["checks"])
                elapsed = (time.time() - started) / 60
                budget_ok = elapsed + first_render / 60 * 0.6 <= limit
                if fixed is not None and budget_ok:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled("Cancelled.")
                    reporter.stage("retry", "Fixing and rendering again: " + "; ".join(actions))
                    save_project(fixed, project_file)
                    o = cfg["output"]
                    render_project(fixed, draft, work_dir=work / "render",
                                   fonts_folder=project_path(cfg["captions"]["fonts_folder"]),
                                   export={"crf": o["crf"], "encoder_speed": o["encoder_speed"],
                                           "audio_bitrate": o["audio_bitrate"]},
                                   reporter=reporter, cancel=cancel)
                    project = fixed
                    before = report["failed"]
                    report = qc.run(draft, project, project_file.parent, cfg)
                    reporter.event("qc", **report)
                    sidecar["retries"].append({"failed": before, "actions": actions,
                                               "still_failed": report["failed"]})
                elif fixed is not None:
                    sidecar["retries"].append({"failed": report["failed"], "actions": [],
                                               "skipped": f"no time left (limit {limit:g} min)"})
            sidecar["qc"] = report
        # Move the results into place; the sidecar last.
        os.replace(draft, names["video"])
        save_project(project, names["project"])
        plan = draft.with_suffix(".plan.json")
        if plan.exists():
            os.replace(plan, names["video"].with_suffix(".plan.json"))
        sidecar["output"] = str(names["video"])
        sidecar["project"] = str(names["project"])
        if report is None:
            sidecar["status"] = "ok"
        else:
            sidecar["status"] = "failed" if not report["passed"] else "ok" if report["clean"] else "warnings"
            if not report["passed"]:
                sidecar["error"] = "Quality checks failed: " + ", ".join(report["errors"])
    except Cancelled:
        raise
    except EditorError as exc:
        sidecar["error"] = str(exc)
        raise
    finally:
        sidecar["seconds"] = round(time.time() - started, 1)
        sidecar["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        shutil.rmtree(work, ignore_errors=True)
        try:
            (out_folder / ".polishing").rmdir()
        except OSError:
            pass
        if sidecar["output"]:
            write_json(names["sidecar"], sidecar)
    return sidecar


def relocate_media(project_file, old, new):
    """After the original was moved (watch folder: inbox -> done), point the project at it."""
    from .project import load_project, save_project
    project = load_project(project_file)
    old, new = str(Path(old).resolve()), str(Path(new).resolve())
    changed = False
    for m in project.get("media", []):
        if str(Path(m["path"]).resolve()) == old:
            m["path"] = new
            changed = True
    if changed:
        save_project(project, project_file)
    return changed
