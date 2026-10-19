"""Quality tiers for AI images, video clips and voice-over made with WanGP.

Tiers (Draft, Low, Mid, High) are defined per content type in generation.json, each
pointing to a settings file the user exported from WanGP, plus a few allowed overrides.
No model name is written in this code: models come from the user's templates and from
WanGP's own model list.

Everything measured (run times, benchmark results, peak VRAM) is stored per PC
(hardware key), WanGP version and model, in work/generation/.

This product uses WanGP (https://github.com/deepbeepmeep/Wan2GP), subject to its license.
"""

import copy
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from . import PROJECT_DIR
from .errors import Cancelled, EditorError
from .wangp import Bridge, GpuLock, WanGPError, check_setup, model_links

CONTENT_TYPES = ("image", "video", "voice")
TIER_NAMES = ("Draft", "Low", "Mid", "High")
ALLOWED_OVERRIDES = {"resolution", "num_inference_steps", "video_length", "duration_seconds"}
MAIN_OUTPUT = {"image": "image", "video": "video", "voice": "audio"}
EXAMPLE = PROJECT_DIR / "generation.example.json"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


class Paths:
    """Where the settings and measurements live. AUTOEDIT_GENERATION_HOME (if set) holds
    both generation.json and the data folder (used by the desktop app's tests)."""

    def __init__(self, settings_file=None, data_dir=None):
        home = os.environ.get("AUTOEDIT_GENERATION_HOME")
        if home:
            settings_file = settings_file or Path(home) / "generation.json"
            data_dir = Path(home) / "data"
        self.settings = Path(settings_file or PROJECT_DIR / "generation.json")
        self.data = Path(data_dir or PROJECT_DIR / "work" / "generation")
        self.hardware = self.data / "hardware.json"
        self.models = self.data / "models.json"
        self.benchmarks = self.data / "benchmarks.json"
        self.runs = self.data / "runs.jsonl"
        self.lock = self.data / "gpu.lock"
        self.outputs = self.data / "outputs"


# ---------------------------------------------------------------- settings file

def load_settings(paths):
    """The generation settings, created from the example on first use.

    Never raises for a bad file: problems are returned so the app can show them.
    Returns (settings, problems).
    """
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    problems = []
    if not paths.settings.exists():
        try:
            paths.settings.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(EXAMPLE, paths.settings)
        except OSError as exc:
            problems.append(f"Could not create {paths.settings}: {exc}")
        data = copy.deepcopy(example)
    else:
        try:
            data = json.loads(paths.settings.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{paths.settings.name} could not be read ({exc}); using the "
                            f"built-in defaults until it is fixed.")
            data = copy.deepcopy(example)
    settings = copy.deepcopy(example)
    for key in ("wangp", "limits", "benchmark", "default_tier", "pinned_tier"):
        if isinstance(data.get(key), dict):
            settings[key].update(data[key])
    if isinstance(data.get("templates_folder"), str):
        settings["templates_folder"] = data["templates_folder"]
    tiers = data.get("tiers") if isinstance(data.get("tiers"), dict) else {}
    for ctype in CONTENT_TYPES:
        given = tiers.get(ctype)
        if not isinstance(given, list):
            continue
        clean = []
        for tier in given:
            if not isinstance(tier, dict) or tier.get("name") not in TIER_NAMES:
                problems.append(f"tiers.{ctype}: entries need a name of {', '.join(TIER_NAMES)}")
                continue
            overrides = tier.get("overrides") if isinstance(tier.get("overrides"), dict) else {}
            bad = sorted(set(overrides) - ALLOWED_OVERRIDES)
            if bad:
                problems.append(f"tiers.{ctype}.{tier['name']}: overrides {', '.join(bad)} are "
                                f"not allowed and were ignored (allowed: "
                                f"{', '.join(sorted(ALLOWED_OVERRIDES))})")
            clean.append({"name": tier["name"], "label": str(tier.get("label") or tier["name"]),
                          "template": str(tier.get("template") or ""),
                          "overrides": {k: v for k, v in overrides.items()
                                        if k in ALLOWED_OVERRIDES},
                          "vram_gb": tier.get("vram_gb")})
        clean.sort(key=lambda t: TIER_NAMES.index(t["name"]))
        settings["tiers"][ctype] = clean
    for key in ("default_tier", "pinned_tier"):
        for ctype in CONTENT_TYPES:
            if settings[key].get(ctype) not in (None, *TIER_NAMES):
                problems.append(f"{key}.{ctype}: '{settings[key][ctype]}' is not a tier name")
                settings[key][ctype] = None
    return settings, problems


def save_choice(paths, kind, content_type, tier):
    """Save the default (after Compare) or pinned tier for a content type."""
    if kind not in ("default_tier", "pinned_tier") or content_type not in CONTENT_TYPES:
        raise EditorError("Unknown setting.")
    if tier is not None and tier not in TIER_NAMES:
        raise EditorError(f"Unknown tier '{tier}'.")
    load_settings(paths)                         # creates the file if needed
    try:
        data = json.loads(paths.settings.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EditorError(f"{paths.settings.name} could not be read, so the choice was not "
                          f"saved: {exc}")
    data.setdefault(kind, {})[content_type] = tier
    tmp = paths.settings.with_name(paths.settings.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(paths.settings)


def templates_dir(paths, settings):
    folder = Path(settings["templates_folder"])
    return folder if folder.is_absolute() else paths.settings.parent / folder


def save_wangp(paths, folder=None, python=None):
    """Save the WanGP folder and/or WanGP's Python in the settings file."""
    load_settings(paths)                         # creates the file if needed
    try:
        data = json.loads(paths.settings.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EditorError(f"{paths.settings.name} could not be read, so nothing was saved: {exc}")
    w = data.setdefault("wangp", {})
    if folder is not None:
        w["folder"] = folder.strip()
    if python is not None:
        w["python"] = python.strip()
    tmp = paths.settings.with_name(paths.settings.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(paths.settings)


def template_path(paths, settings, tier):
    return templates_dir(paths, settings) / tier["template"]


def read_template(paths, settings, tier):
    """(template dict, problem). The template is a WanGP 'Export Settings' file."""
    if not tier["template"]:
        return None, ("No WanGP settings file yet. In WanGP, choose the model and settings, "
                      "click Export Settings and save the file in the templates folder. Then "
                      "put that file name in this tier's \"template\" (Edit settings file).")
    path = template_path(paths, settings, tier)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, f"Settings file not found: {path}"
    except ValueError as exc:
        return None, f"Settings file {path.name} is not valid JSON: {exc}"
    if not isinstance(data, dict) or not data.get("model_type"):
        return None, f"{path.name} has no model_type. Export it again from WanGP."
    return data, None


def tier_fingerprint(template, tier):
    text = json.dumps({"t": template, "o": tier["overrides"]}, sort_keys=True, default=str)
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def job_settings(template, tier, prompt, seed, extra=None):
    """The settings sent to WanGP: template + tier overrides + this job's prompt and seed."""
    settings = copy.deepcopy(template)
    settings.update(tier["overrides"])
    settings["prompt"] = prompt
    settings["seed"] = int(seed)
    settings.update(extra or {})
    return settings


# ---------------------------------------------------------------- measurements

def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def record_run(paths, **run):
    paths.runs.parent.mkdir(parents=True, exist_ok=True)
    run.setdefault("time", time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(paths.runs, "a", encoding="utf-8") as f:
        f.write(json.dumps(run) + "\n")


def read_runs(paths):
    runs = []
    try:
        for line in paths.runs.read_text(encoding="utf-8").splitlines():
            try:
                runs.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return runs


def average_seconds(runs, hardware_key, content_type, tier, model_type):
    times = [r["seconds"] for r in runs
             if r.get("success") and r.get("hardware_key") == hardware_key
             and r.get("content_type") == content_type and r.get("tier") == tier
             and r.get("model_type") == model_type and r.get("purpose") != "benchmark"]
    return (sum(times) / len(times), len(times)) if times else (None, 0)


def benchmark_key(hardware_key, version, model_type, content_type, tier, fingerprint):
    return f"{hardware_key}|{version}|{model_type}|{content_type}|{tier}|{fingerprint}"


# ---------------------------------------------------------------- WanGP model list

def cached_models(paths):
    """The last model list read from WanGP: {"version", "models", "checked_at"} or None."""
    return read_json(paths.models, None)


def refresh_models(paths, settings, log=print):
    """Ask WanGP for its models and their installed status (WanGP's own check)."""
    with Bridge(settings, paths.outputs, log=log) as bridge:
        models = bridge.models()
        data = {"version": bridge.version, "models": models,
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    write_json(paths.models, data)
    return data


# ---------------------------------------------------------------- the tier table

def tier_table(paths, settings, hardware_key, models_info):
    """Every tier with what the app shows: installed or not, measured time, VRAM, benchmark."""
    models = {m["model_type"]: m for m in (models_info or {}).get("models", [])}
    version = (models_info or {}).get("version")
    runs = read_runs(paths)
    benchmarks = read_json(paths.benchmarks, {})
    table = {}
    for ctype in CONTENT_TYPES:
        rows = []
        for tier in settings["tiers"][ctype]:
            template, problem = read_template(paths, settings, tier)
            row = {"name": tier["name"], "label": tier["label"], "template": tier["template"],
                   "vram_gb": tier["vram_gb"], "overrides": tier["overrides"],
                   "model_type": None, "model_name": None, "installed": False,
                   "status": "not set up", "disabled_reason": problem, "links": [],
                   "avg_seconds": None, "runs": 0, "benchmark": None}
            if template:
                model_type = template["model_type"]
                model = models.get(model_type)
                row.update(model_type=model_type,
                           model_name=(model or {}).get("name") or model_type)
                if model is not None:
                    row["links"] = model_links(model)
                if not models_info:
                    row.update(status="not checked",
                               disabled_reason="WanGP has not been checked yet (set it up, then "
                                               "click 'Check WanGP models').")
                elif model is None:
                    row.update(status="unknown model",
                               disabled_reason=f"This WanGP does not know the model "
                                               f"'{model_type}'. Export the settings again.")
                elif model.get("available"):
                    row.update(installed=True, status="installed", disabled_reason=None)
                elif model.get("status") == "partial":
                    row.update(status="partly downloaded",
                               disabled_reason="Some files of this model are missing. Finish "
                                               "the download in WanGP (the editor never "
                                               "downloads models).")
                else:
                    row.update(status="not installed",
                               disabled_reason="Not installed. Download it in WanGP if you "
                                               "want it, after reading its license (links "
                                               "below). The editor never downloads models.")
                avg, count = average_seconds(runs, hardware_key, ctype, tier["name"], model_type)
                row.update(avg_seconds=avg, runs=count)
                key = benchmark_key(hardware_key, version, model_type, ctype, tier["name"],
                                    tier_fingerprint(template, tier))
                row["benchmark"] = benchmarks.get(key)
            rows.append(row)
        table[ctype] = rows
    return table


def usable(rows):
    return [r for r in rows if r["installed"]]


def choose(rows, settings, content_type):
    """(preview tier, [final tier, then fallbacks in order]) by name, or (None, [])."""
    ok = usable(rows)
    if not ok:
        return None, []
    names = [r["name"] for r in ok]
    pinned = settings["pinned_tier"].get(content_type)
    default = settings["default_tier"].get(content_type)
    passed = [r["name"] for r in ok if (r["benchmark"] or {}).get("success")]
    if pinned in names:
        final = pinned
    elif default in names:
        final = default
    elif passed:
        final = passed[-1]
    else:
        final = names[-1]
    order = [final] + [n for n in reversed(names) if TIER_NAMES.index(n) < TIER_NAMES.index(final)]
    preview = "Draft" if "Draft" in names else names[0]
    return preview, order


def recommendations(table, models_info):
    """Per content type: the highest tier that passed its benchmark here, and other WanGP
    models of that kind that are not installed (with official links), without ranking them."""
    models = (models_info or {}).get("models", [])
    result = {}
    for ctype in CONTENT_TYPES:
        rows = table[ctype]
        passed = [r for r in rows if r["installed"] and (r["benchmark"] or {}).get("success")]
        used = {r["model_type"] for r in rows if r["model_type"]}
        others = [{"model_type": m["model_type"], "name": m.get("name") or m["model_type"],
                   "family": m.get("family"), "status": m.get("status"),
                   "links": model_links(m)}
                  for m in models
                  if MAIN_OUTPUT[ctype] in (m.get("main_output") or [])
                  and not m.get("available") and m["model_type"] not in used]
        result[ctype] = {"tier": passed[-1]["name"] if passed else None,
                         "tier_seconds": (passed[-1]["benchmark"] or {}).get("seconds")
                         if passed else None,
                         "could_download": sorted(others, key=lambda m: (m["family"] or "",
                                                                          m["name"]))}
    return result


# ---------------------------------------------------------------- running jobs

def output_kind(path):
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return "other"


class Generator:
    """Runs tier jobs through one WanGP bridge, one GPU job at a time, and records them."""

    def __init__(self, paths, settings, hardware_key, log=print, cancel=None):
        self.paths, self.settings = paths, settings
        self.hardware_key = hardware_key
        self.log, self.cancel = log, cancel
        self.bridge = None
        self.lock = GpuLock(paths.lock)

    def __enter__(self):
        self.lock.acquire(self.cancel, on_wait=lambda: self.log(
            "  > waiting for another GPU job on this PC to finish"))
        try:
            self.bridge = Bridge(self.settings, self.paths.outputs, log=self.log).__enter__()
        except BaseException:
            self.lock.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self.bridge:
                self.bridge.close()
        finally:
            self.lock.release()

    @property
    def version(self):
        return self.bridge.version if self.bridge else None

    def run(self, content_type, tier_row, prompt, seed, purpose, extra=None, timeout=None,
            on_progress=None):
        """Generate with one tier. Returns (GenResult, output file or None)."""
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled("Cancelled.")
        tier = next(t for t in self.settings["tiers"][content_type]
                    if t["name"] == tier_row["name"])
        template, problem = read_template(self.paths, self.settings, tier)
        if problem:
            raise EditorError(problem)
        if not tier_row["installed"]:
            raise EditorError(f"{content_type} tier {tier['name']} is not installed.")
        if self.bridge is None or not self.bridge.alive:          # restarted after a hang
            self.bridge = Bridge(self.settings, self.paths.outputs, log=self.log).__enter__()
        out_dir = self.paths.outputs / time.strftime("%Y%m%d")
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{content_type}_{tier['name']}_{int(time.time() * 1000)}"
        settings = job_settings(template, tier, prompt, seed,
                                {"output_filename": stamp, **(extra or {})})
        result = self.bridge.generate(settings, out_dir, timeout=timeout, cancel=self.cancel,
                                      on_progress=on_progress)
        output = result.files[0] if result.success and result.files else None
        record_run(self.paths, hardware_key=self.hardware_key, wangp_version=self.version,
                   content_type=content_type, tier=tier["name"],
                   model_type=template["model_type"], purpose=purpose,
                   success=result.success, reason=result.reason, seconds=round(result.seconds, 2),
                   peak_vram_mb=result.peak_vram_mb, out_of_memory=result.out_of_memory,
                   fingerprint=tier_fingerprint(template, tier))
        if result.cancelled and self.cancel is not None and self.cancel.is_set():
            raise Cancelled("Cancelled.")
        return result, output


def benchmark(paths, settings, hardware_key, table, content_types=CONTENT_TYPES, tiers=None,
              reporter=None, cancel=None, log=print):
    """A short test per installed tier. Results are saved per PC, WanGP version and model."""
    bench = settings["benchmark"]
    results = []
    todo = [(c, r) for c in content_types for r in table[c]
            if r["installed"] and (not tiers or r["name"] in tiers)]
    if not todo:
        return results
    with Generator(paths, settings, hardware_key, log=log, cancel=cancel) as gen:
        saved = read_json(paths.benchmarks, {})
        for i, (ctype, row) in enumerate(todo):
            if reporter:
                reporter.event("benchmark_start", content_type=ctype, tier=row["name"],
                               index=i, total=len(todo))
            extra = {}
            if ctype == "video":
                extra["video_length"] = f"{int(bench['video_seconds'])}s"
            elif ctype == "voice":
                extra["duration_seconds"] = bench["voice_seconds"]
            timeout = settings["limits"]["job_timeout_minutes"] * 60
            result, output = gen.run(ctype, row, bench["prompts"][ctype], bench["seed"],
                                     "benchmark", extra, timeout=timeout)
            tier = next(t for t in settings["tiers"][ctype] if t["name"] == row["name"])
            template, _ = read_template(paths, settings, tier)
            entry = {"success": result.success, "reason": result.reason,
                     "seconds": round(result.seconds, 2), "peak_vram_mb": result.peak_vram_mb,
                     "out_of_memory": result.out_of_memory, "error": "; ".join(result.errors)[:500],
                     "wangp_version": gen.version, "model_type": row["model_type"],
                     "output": output, "date": time.strftime("%Y-%m-%d %H:%M")}
            saved[benchmark_key(hardware_key, gen.version, row["model_type"], ctype, row["name"],
                                tier_fingerprint(template, tier))] = entry
            write_json(paths.benchmarks, saved)
            results.append({"content_type": ctype, "tier": row["name"], **entry})
            if reporter:
                reporter.event("benchmark_result", content_type=ctype, tier=row["name"], **entry)
    return results


def compare(paths, settings, hardware_key, table, content_type, prompt, seed, reporter=None,
            cancel=None, log=print):
    """The same prompt and seed with every installed tier, one GPU job at a time."""
    rows = usable(table[content_type])
    if not rows:
        raise EditorError(f"No {content_type} tier is installed, so there is nothing to compare.")
    folder = paths.data / "compare" / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    with Generator(paths, settings, hardware_key, log=log, cancel=cancel) as gen:
        for i, row in enumerate(rows):
            if reporter:
                reporter.event("compare_start", content_type=content_type, tier=row["name"],
                               index=i, total=len(rows))
            result, output = gen.run(content_type, row, prompt, seed, "compare",
                                     timeout=settings["limits"]["job_timeout_minutes"] * 60)
            kept = None
            if output:
                from .graphics import safe_filename
                kept = folder / f"{safe_filename(row['name'])}{Path(output).suffix}"
                shutil.copy(output, kept)
            entry = {"tier": row["name"], "label": row["label"], "model_name": row["model_name"],
                     "success": result.success, "reason": result.reason,
                     "seconds": round(result.seconds, 2), "peak_vram_mb": result.peak_vram_mb,
                     "error": "; ".join(result.errors)[:500],
                     "output": str(kept) if kept else None}
            results.append(entry)
            if reporter:
                reporter.event("compare_result", content_type=content_type, **entry)
    (folder / "results.json").write_text(json.dumps({
        "content_type": content_type, "prompt": prompt, "seed": seed, "results": results},
        indent=1), encoding="utf-8")
    return {"folder": str(folder), "prompt": prompt, "seed": seed, "results": results}


def status(paths, refresh_hardware=False, check_wangp=False, log=print):
    """Everything the app's 'AI models' screen shows. Never raises."""
    from .hardware import describe, load_profile

    settings, problems = load_settings(paths)
    setup = check_setup(settings)
    w = settings["wangp"]
    profile, _, _ = load_profile(paths.hardware,
                                              [w.get("folder"), str(PROJECT_DIR)])
    models_info = cached_models(paths)
    wangp_error = None
    if check_wangp and not setup:
        try:
            models_info = refresh_models(paths, settings, log=log)
        except (WanGPError, EditorError) as exc:
            wangp_error = str(exc)
    table = tier_table(paths, settings, profile["key"], models_info)
    tested_here = any(k.startswith(profile["key"] + "|")
                      for k in (read_json(paths.benchmarks, {}) or {}))
    changed_from = None if tested_here else profile.get("changed_from")
    choices = {c: dict(zip(("preview", "order"), choose(table[c], settings, c)))
               for c in CONTENT_TYPES}
    return {
        "settings_file": str(paths.settings),
        "templates_folder": str(templates_dir(paths, settings)),
        "problems": problems,
        "setup_problems": setup,
        "wangp": {"folder": w.get("folder"), "python": w.get("python"),
                  "version": (models_info or {}).get("version"),
                  "checked_at": (models_info or {}).get("checked_at"),
                  "error": wangp_error},
        "hardware": profile, "hardware_summary": describe(profile),
        # Pointed out until a test has run on this hardware (old results are kept, per PC).
        "hardware_changed": bool(changed_from),
        "previous_hardware": changed_from,
        "tiers": table, "choices": choices,
        "recommendations": recommendations(table, models_info),
        "default_tier": settings["default_tier"], "pinned_tier": settings["pinned_tier"],
        "limits": settings["limits"],
    }
