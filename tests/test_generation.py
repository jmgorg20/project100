"""AI generation with WanGP: hardware detection, the bridge, quality tiers, benchmark, compare.

No GPU or real WanGP here: tests/fake_wangp is a stand-in with WanGP's documented API
surface, and a fake nvidia-smi reports a GPU. Real speed and quality are NOT tested.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from autoedit import PROJECT_DIR, generation, hardware
from autoedit.errors import Cancelled
from autoedit.wangp import Bridge, GenResult, GpuLock, WanGPError, check_setup, model_links

FAKE = Path(__file__).with_name("fake_wangp")
HF = "https://huggingface.co/SomeOrg/{}/resolve/main/model.safetensors"


@pytest.fixture
def fake_smi(tmp_path, monkeypatch):
    """A fake nvidia-smi on PATH: one 12 GB GPU; memory.used rises on every call."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "smi_state.json"
    state.write_text(json.dumps({"vram": 12288, "used": 1000, "fail": False}))
    script = bin_dir / "nvidia-smi"
    script.write_text(f"""#!{sys.executable}
import json, sys
state = json.load(open({str(state)!r}))
if state["fail"]:
    sys.exit(9)
if "--query-gpu=memory.used" in sys.argv:
    state["used"] += 500
    json.dump(state, open({str(state)!r}, "w"))
    print(state["used"])
else:
    print(f"NVIDIA GeForce RTX 3060, {{state['vram']}}, 555.85")
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return state


def make_wangp(tmp_path, models):
    root = tmp_path / "WanGP"
    shutil.copytree(FAKE, root)
    (root / "fake_models.json").write_text(json.dumps(models), encoding="utf-8")
    return root


def model(model_type, kind, status="available", **extra):
    return {"model_type": model_type, "name": model_type.replace("_", " ").title(),
            "family": kind.title() + " family", "main_output": [kind], "status": status,
            "urls": [HF.format(model_type)], **extra}


STANDARD_MODELS = [
    model("img_small", "image", seconds=0.1),
    model("img_big", "image", seconds=0.2, oom_above_pixels=600_000),
    model("vid_fast", "video", seconds=0.2),
    model("vid_huge", "video", status="missing"),
    model("vid_partial", "video", status="partial"),
    model("tts_one", "audio", seconds=0.1),
    model("music_x", "audio", status="missing"),
]


@pytest.fixture
def setup(tmp_path):
    """A generation.json with tiers pointing at exported templates, and a fake WanGP."""
    root = make_wangp(tmp_path, STANDARD_MODELS)
    paths = generation.Paths(tmp_path / "generation.json", tmp_path / "data")
    generation.load_settings(paths)                       # creates it from the example
    data = json.loads(paths.settings.read_text())
    data["wangp"] = {"folder": str(root), "python": sys.executable, "cli_args": []}
    templates = tmp_path / "generation_templates"
    templates.mkdir()

    def export(name, model_type, **values):
        (templates / name).write_text(json.dumps({"model_type": model_type, "prompt": "x",
                                                  "seed": -1, **values}))
        return name

    tiers = data["tiers"]
    tiers["image"][0]["template"] = export("i_draft.json", "img_small", resolution="320x576",
                                           num_inference_steps=2)
    tiers["image"][2]["template"] = export("i_mid.json", "img_big", resolution="480x832",
                                           num_inference_steps=4)
    tiers["image"][3]["template"] = "i_mid.json"            # same model, bigger: runs out of memory
    tiers["image"][3]["overrides"] = {"resolution": "1080x1920"}
    tiers["video"][0]["template"] = export("v_draft.json", "vid_fast", resolution="320x576",
                                           video_length=17)
    tiers["video"][3]["template"] = export("v_high.json", "vid_huge")
    tiers["video"][2]["template"] = export("v_mid.json", "vid_partial")
    tiers["voice"][1]["template"] = export("a_low.json", "tts_one", duration_seconds=2)
    paths.settings.write_text(json.dumps(data))
    return paths, root


def status(paths, check=True):
    return generation.status(paths, check_wangp=check, log=lambda *_: None)


# ------------------------------------------------------------ hardware

def test_hardware_with_nvidia_smi(tmp_path, fake_smi):
    profile = hardware.detect([str(tmp_path)])
    assert profile["gpus"] == [{"name": "NVIDIA GeForce RTX 3060", "vram_mb": 12288,
                                "driver": "555.85", "source": "nvidia-smi"}]
    assert profile["ram_mb"] and profile["disk_free_mb"][str(tmp_path)] > 0
    assert hardware.describe(profile).startswith("NVIDIA GeForce RTX 3060 (12 GB VRAM), ")


def test_hardware_change_is_noticed(tmp_path, fake_smi):
    store = tmp_path / "hw.json"
    first, changed, _ = hardware.load_profile(store)
    assert not changed
    again, changed, _ = hardware.load_profile(store)
    assert not changed and again["key"] == first["key"]
    data = json.loads(fake_smi.read_text())
    data["vram"] = 24576                                     # a new GPU
    fake_smi.write_text(json.dumps(data))
    new, changed, previous = hardware.load_profile(store)
    assert changed and new["key"] != first["key"] and previous["key"] == first["key"]


def test_hardware_never_blocks_without_nvidia_smi(tmp_path, monkeypatch, fake_smi):
    data = json.loads(fake_smi.read_text())
    data["fail"] = True
    fake_smi.write_text(json.dumps(data))
    profile = hardware.detect()
    assert profile["gpus"] == [] and any("did not answer" in n for n in profile["notes"])
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    profile = hardware.detect()
    assert profile["gpus"] == [] and "no GPU detected" in hardware.describe(profile)
    with hardware.VramSampler() as sampler:
        pass
    assert sampler.job_peak_mb is None                     # no nvidia-smi: unknown, no error


def test_vram_sampler_measures_a_peak(fake_smi):
    import time
    with hardware.VramSampler(interval=0.05) as sampler:
        time.sleep(0.4)
    assert sampler.job_peak_mb and sampler.job_peak_mb >= 500


# ------------------------------------------------------------ the bridge

def bridge_cfg(root, **extra):
    return {"wangp": {"folder": str(root), "python": sys.executable, "cli_args": [], **extra}}


def test_bridge_lists_models_with_wangps_own_installed_status(tmp_path):
    root = make_wangp(tmp_path, STANDARD_MODELS)
    logs = []
    with Bridge(bridge_cfg(root), tmp_path / "out", log=logs.append) as bridge:
        assert bridge.version == "99.1-test"
        models = {m["model_type"]: m for m in bridge.models()}
    assert models["img_small"]["available"] is True
    assert models["vid_huge"]["status"] == "missing" and not models["vid_huge"]["available"]
    assert models["vid_partial"]["status"] == "partial"
    assert models["img_small"]["urls"] == [HF.format("img_small")]
    assert any("Powered by WanGP" in line for line in logs)   # banner kept off the JSON channel
    assert model_links(models["img_small"])[0] == "https://huggingface.co/SomeOrg/img_small"


def test_bridge_generates_and_never_runs_models_that_are_not_installed(tmp_path):
    root = make_wangp(tmp_path, [model("img", "image", noisy=True), model("gone", "image", status="missing"),
                                 model("half", "image", status="partial")])
    progress = []
    with Bridge(bridge_cfg(root), tmp_path / "out", log=lambda *_: None) as bridge:
        ok = bridge.generate({"model_type": "img", "prompt": "p", "seed": 3, "num_inference_steps": 4},
                             tmp_path / "out", on_progress=progress.append)
        refused = bridge.generate({"model_type": "gone", "prompt": "p"}, tmp_path / "out")
        partial = bridge.generate({"model_type": "half", "prompt": "p"}, tmp_path / "out")
    assert ok.success and Path(ok.files[0]).exists() and ok.reason == "ok"
    assert [p["percent"] for p in progress] == [25, 50, 75, 100]
    assert refused.not_installed and partial.not_installed and "never downloads" in refused.errors[0]
    calls = [json.loads(l)["model_type"] for l in (root / "calls.jsonl").read_text().splitlines()]
    assert calls == ["img"]                                # WanGP never saw the other two


def test_bridge_reports_out_of_memory_and_timeouts(tmp_path):
    root = make_wangp(tmp_path, [model("big", "image", oom_above_pixels=100_000),
                                 model("slow", "image", seconds=30)])
    with Bridge(bridge_cfg(root), tmp_path / "out", log=lambda *_: None) as bridge:
        oom = bridge.generate({"model_type": "big", "prompt": "p", "resolution": "1080x1920"},
                              tmp_path / "out")
        slow = bridge.generate({"model_type": "slow", "prompt": "p", "num_inference_steps": 30},
                               tmp_path / "out", timeout=1.5)
        after = bridge.generate({"model_type": "big", "prompt": "p", "resolution": "256x256"},
                                tmp_path / "out")
    assert not oom.success and oom.out_of_memory and oom.reason == "out of GPU memory"
    assert slow.timed_out and not slow.success and slow.reason == "took too long"
    assert slow.seconds < 10
    assert after.success                                     # the bridge is still usable


def test_bridge_setup_and_start_problems_are_clear(tmp_path):
    assert "Set the WanGP folder" in check_setup({"wangp": {"folder": "", "python": ""}})[0]
    assert "wgp.py was not found" in check_setup({"wangp": {"folder": str(tmp_path),
                                                             "python": sys.executable}})[0]
    with pytest.raises(WanGPError, match="Set WanGP's Python"):
        Bridge({"wangp": {"folder": str(make_wangp(tmp_path, [])), "python": ""}}, tmp_path)
    root = tmp_path / "WanGP"
    with pytest.raises(WanGPError, match="CUDA driver not found"):
        with Bridge(bridge_cfg(root, cli_args=["--fail-start"]), tmp_path, log=lambda *_: None):
            pass


def test_gen_result_reasons():
    assert GenResult(False, errors=["RuntimeError: CUDA error: out of memory"]).out_of_memory
    assert GenResult(False, errors=["torch.OutOfMemoryError: ..."]).reason == "out of GPU memory"
    assert GenResult(False, errors=["boom"]).reason == "failed"


def test_one_gpu_job_at_a_time_across_processes(tmp_path):
    lock_file = tmp_path / "gpu.lock"
    holder = subprocess.Popen([sys.executable, "-c", f"""
import sys, time
sys.path.insert(0, {str(PROJECT_DIR)!r})
from autoedit.wangp import GpuLock
lock = GpuLock({str(lock_file)!r}); lock.acquire(); print("held", flush=True); time.sleep(30)
"""], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        cancel = threading.Event()
        waited = []
        threading.Timer(1.5, cancel.set).start()
        with pytest.raises(Cancelled, match="waiting for the GPU"):
            GpuLock(lock_file).acquire(cancel, on_wait=lambda: waited.append(True))
        assert waited == [True]
    finally:
        holder.kill()
        holder.wait()
    lock = GpuLock(lock_file)
    lock.acquire()                                          # free again once the holder exits
    lock.release()


# ------------------------------------------------------------ settings and tiers

def test_settings_file_is_created_and_checked(tmp_path):
    paths = generation.Paths(tmp_path / "generation.json", tmp_path / "data")
    settings, problems = generation.load_settings(paths)
    assert problems == [] and paths.settings.exists()
    assert [t["name"] for t in settings["tiers"]["video"]] == ["Draft", "Low", "Mid", "High"]
    data = json.loads(paths.settings.read_text())
    data["tiers"]["image"] = [
        {"name": "High", "template": "h.json", "overrides": {"resolution": "720x1280", "guidance_scale": 9}},
        {"name": "Ultra", "template": "u.json"},
        {"name": "Draft", "template": "d.json"},
    ]
    data["pinned_tier"]["video"] = "Best"
    paths.settings.write_text(json.dumps(data))
    settings, problems = generation.load_settings(paths)
    assert [t["name"] for t in settings["tiers"]["image"]] == ["Draft", "High"]
    assert settings["tiers"]["image"][1]["overrides"] == {"resolution": "720x1280"}
    assert any("guidance_scale are not allowed" in p for p in problems)
    assert any("Ultra" not in p and "entries need a name" in p for p in problems)
    assert settings["pinned_tier"]["video"] is None
    paths.settings.write_text("{broken")
    settings, problems = generation.load_settings(paths)    # never blocks
    assert "could not be read" in problems[0] and settings["limits"]["max_ai_clips"] == 6


def test_example_settings_name_no_models():
    """Tier definitions must not hardcode model names: templates come from the user."""
    example = json.loads((PROJECT_DIR / "generation.example.json").read_text())
    for rows in example["tiers"].values():
        assert all(row["template"] == "" for row in rows)
    source = (PROJECT_DIR / "autoedit" / "generation.py").read_text()
    for name in ("ltx", "flux", "hunyuan", "qwen", "kandinsky", "t2v_", "i2v_"):
        assert name not in source.lower()


def test_tier_table_shows_what_is_installed(setup, fake_smi):
    paths, root = setup
    info = status(paths, check=False)
    assert info["tiers"]["image"][0]["status"] == "not checked"     # WanGP not asked yet
    info = status(paths)
    assert info["wangp"]["version"] == "99.1-test"
    image, video, voice = (info["tiers"][c] for c in ("image", "video", "voice"))
    assert [r["status"] for r in image] == ["installed", "not set up", "installed", "installed"]
    assert "Export Settings" in image[1]["disabled_reason"]
    assert video[3]["status"] == "not installed" and "license" in video[3]["disabled_reason"]
    assert video[2]["status"] == "partly downloaded"
    assert voice[1]["installed"] and voice[1]["model_name"] == "Tts One"
    assert video[3]["links"][0] == "https://huggingface.co/SomeOrg/vid_huge"
    assert info["hardware_summary"].startswith("NVIDIA GeForce RTX 3060")
    could = info["recommendations"]["voice"]["could_download"]
    assert [m["model_type"] for m in could] == ["music_x"]           # not installed, not in a tier
    assert info["choices"]["video"] == {"preview": "Draft", "order": ["Draft"]}


def test_choose_pinned_default_benchmark_and_fallback():
    def row(name, installed=True, passed=None):
        return {"name": name, "installed": installed,
                "benchmark": None if passed is None else {"success": passed}}
    settings = {"pinned_tier": {"video": None}, "default_tier": {"video": None}}
    rows = [row("Draft"), row("Low", passed=True), row("Mid", passed=True), row("High", passed=False)]
    assert generation.choose(rows, settings, "video") == ("Draft", ["Mid", "Low", "Draft"])
    settings["default_tier"]["video"] = "Low"
    assert generation.choose(rows, settings, "video") == ("Draft", ["Low", "Draft"])
    settings["pinned_tier"]["video"] = "High"
    assert generation.choose(rows, settings, "video") == ("Draft", ["High", "Mid", "Low", "Draft"])
    rows = [row("Draft", installed=False), row("Mid"), row("High")]   # nothing benchmarked
    settings = {"pinned_tier": {"video": None}, "default_tier": {"video": None}}
    assert generation.choose(rows, settings, "video") == ("Mid", ["High", "Mid"])
    assert generation.choose([row("Low", installed=False)], settings, "video") == (None, [])


def test_benchmark_records_success_out_of_memory_time_and_vram(setup, fake_smi):
    paths, root = setup
    info = status(paths)
    settings, _ = generation.load_settings(paths)
    events = []

    class Rec:
        def event(self, kind, **data):
            events.append((kind, data))

    results = generation.benchmark(paths, settings, info["hardware"]["key"], info["tiers"],
                                   reporter=Rec(), log=lambda *_: None)
    got = {(r["content_type"], r["tier"]): r for r in results}
    assert set(got) == {("image", "Draft"), ("image", "Mid"), ("image", "High"),
                        ("video", "Draft"), ("voice", "Low")}          # installed tiers only
    assert got[("image", "High")]["out_of_memory"] and not got[("image", "High")]["success"]
    assert all(got[k]["success"] for k in got if k != ("image", "High"))
    assert all(r["peak_vram_mb"] is not None for r in results)         # measured via nvidia-smi
    calls = [json.loads(l) for l in (root / "calls.jsonl").read_text().splitlines()]
    assert {c["prompt"] for c in calls} == set(settings["benchmark"]["prompts"].values())
    assert next(c for c in calls if c["model_type"] == "vid_fast")["video_length"] == "2s"
    assert [k for k, _ in events].count("benchmark_result") == 5
    # Saved per hardware, WanGP version and model; Auto mode now skips the failed High tier.
    saved = json.loads(paths.benchmarks.read_text())
    assert all(key.startswith(info["hardware"]["key"] + "|99.1-test|") for key in saved)
    info = status(paths)
    assert info["choices"]["image"] == {"preview": "Draft", "order": ["Mid", "Draft"]}
    assert info["recommendations"]["image"]["tier"] == "Mid"


def test_compare_runs_the_same_prompt_and_seed_on_every_installed_tier(setup, fake_smi):
    paths, root = setup
    info = status(paths)
    settings, _ = generation.load_settings(paths)
    result = generation.compare(paths, settings, info["hardware"]["key"], info["tiers"], "image",
                                "Isang tasa ng kape", 77, log=lambda *_: None)
    assert [r["tier"] for r in result["results"]] == ["Draft", "Mid", "High"]
    assert [r["success"] for r in result["results"]] == [True, True, False]
    assert all(Path(r["output"]).exists() for r in result["results"] if r["success"])
    calls = [json.loads(l) for l in (root / "calls.jsonl").read_text().splitlines()]
    assert {(c["prompt"], c["seed"]) for c in calls} == {("Isang tasa ng kape", 77)}
    assert calls[2]["resolution"] == "1080x1920"                       # the High override
    info = status(paths)
    draft = info["tiers"]["image"][0]
    assert draft["runs"] == 1 and draft["avg_seconds"] > 0                # measured on this PC
    generation.save_choice(paths, "default_tier", "image", "Draft")
    assert status(paths)["choices"]["image"]["order"] == ["Draft"]
    assert json.loads(paths.settings.read_text())["default_tier"]["image"] == "Draft"


def test_cli_status_and_set_tier(setup, fake_smi):
    paths, root = setup
    run = subprocess.run([sys.executable, str(PROJECT_DIR / "editor.py"), "--json", "gen-status",
                          "--check-wangp", "--generation-settings", str(paths.settings)],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.splitlines()[-1])
    assert result["type"] == "result" and result["wangp"]["version"] == "99.1-test"
    assert result["tiers"]["voice"][1]["status"] == "installed"
    run = subprocess.run([sys.executable, str(PROJECT_DIR / "editor.py"), "set-tier", "--type",
                          "video", "--pin", "Draft", "--generation-settings", str(paths.settings)],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and "pinned Draft" in run.stdout


# ------------------------------------------------------------ inside the AI edit

from autoedit import ai_edit  # noqa: E402
from autoedit.ai_plan import preset_plan  # noqa: E402
from autoedit.config import load_config  # noqa: E402
from autoedit.project import load_project  # noqa: E402
from autoedit.words import load_transcript  # noqa: E402
from tests import synthetic  # noqa: E402


class Recorder:
    def __init__(self):
        self.stages, self.events = [], []

    def stage(self, key, label):
        self.stages.append(key)

    def progress(self, fraction, stage=None):
        pass

    def event(self, kind, **data):
        self.events.append((kind, data))

    def log(self, message):
        pass

    def result(self, **data):
        pass


@pytest.fixture
def talk(setup, tmp_path, monkeypatch):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    words = load_transcript(synthetic.make_transcript(tmp_path / "talk.json"))
    monkeypatch.setattr(ai_edit, "transcribe", lambda *a: words)
    cfg = load_config()
    cfg["output"].update(folder=str(tmp_path / "out"), encoder_speed="ultrafast")
    cfg["work_folder"] = str(tmp_path / "work")
    cfg["ai"]["cache_folder"] = str(tmp_path / "cache")
    cfg["overlays"]["triggers_file"] = str(tmp_path / "none.yaml")
    return setup[0], setup[1], video, cfg


def gen_plan(cfg):
    plan = preset_plan(cfg)
    plan["ai_clips"] = [
        {"kind": "image", "prompt": "a steaming cup of coffee", "at": 2.9, "duration": 1.0,
         "position": "full", "reason": "when you talk about coffee"},
        {"kind": "video", "prompt": "a busy jeepney street", "at": 5.5, "duration": 1.0,
         "position": "top", "reason": ""},
    ]
    plan["voiceovers"] = [{"text": "Tara na!", "at": 0.6, "reason": "intro"}]
    return plan


def fake_ai(monkeypatch, plan):
    prompts = []

    def ask(provider, model, system, prompt, schema, **kw):
        prompts.append(prompt)
        return json.dumps(plan), {"input_tokens": 10, "output_tokens": 10}, model
    monkeypatch.setattr(ai_edit, "ask_json", ask)
    return prompts


def calls(root):
    path = root / "calls.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def test_auto_mode_drafts_then_renders_the_final_tier_with_fallback(talk, monkeypatch, fake_smi):
    paths, root, video, cfg = talk
    status(paths)                                   # WanGP checked once (as the app does)
    prompts = fake_ai(monkeypatch, gen_plan(cfg))
    rec = Recorder()
    result = ai_edit.ai_edit_video(video, cfg, "add a coffee picture", reporter=rec,
                                   gen_paths=paths)
    assert "AI GENERATION: pictures available; video clips available; voice-over available" \
        in prompts[0]
    assert rec.stages[:2] == ["transcript", "plan"] and "ai_draft" in rec.stages \
        and "ai_final" in rec.stages and rec.stages[-1] == "render"
    made = [(c["model_type"], c.get("resolution")) for c in calls(root)]
    # Draft pass: Draft tiers. Final: image High ran out of memory -> Mid; video and voice
    # have one tier each, so their drafts are kept.
    assert made == [("img_small", "320x576"), ("vid_fast", "320x576"), ("tts_one", None),
                    ("img_big", "1080x1920"), ("img_big", "480x832")]
    gens = [d for k, d in rec.events if k == "generation"]
    assert [(g["pass"], g["tier"], g["success"]) for g in gens][-2:] == \
        [("final", "High", False), ("final", "Mid", True)]
    assert any(k == "project" and d["stage"] == "ai_draft" for k, d in rec.events)
    project = load_project(result["project"])
    overlays = [c for t in project["tracks"] if t["kind"] == "overlay" for c in t["clips"]]
    full = next(c for c in overlays if c["type"] == "image")
    assert (full["width"], full["height"], full["animation"]) == (1080, 1920, "none")
    assert any(c["type"] == "video" for c in overlays)
    voice = [c for t in project["tracks"] if t.get("role") == "voiceover" for c in t["clips"]]
    assert len(voice) == 1
    details = " ".join(result["summary"]["details"])
    assert "the High tier out of GPU memory, so the Mid tier was used instead" in details
    assert "AI picture at 0:03: Mid tier" in details
    assert Path(result["output"]).exists()


def test_review_mode_drafts_only_and_apply_runs_only_the_final_tier(talk, monkeypatch, fake_smi):
    paths, root, video, cfg = talk
    status(paths)
    plan = gen_plan(cfg)
    fake_ai(monkeypatch, plan)
    review = ai_edit.ai_edit_video(video, cfg, "x", render=False, reporter=Recorder(),
                                   gen_paths=paths)
    assert [c["model_type"] for c in calls(root)] == ["img_small", "vid_fast", "tts_one"]
    assert any("final tier is used when you apply" in d for d in review["summary"]["details"])
    (root / "calls.jsonl").unlink()
    generation.save_choice(paths, "default_tier", "image", "Mid")       # chosen after Compare
    ai_edit.ai_edit_video(video, cfg, "x", plan=plan, reporter=Recorder(), gen_paths=paths)
    assert [(c["model_type"], c.get("resolution")) for c in calls(root)] == \
        [("img_big", "480x832"), ("vid_fast", "320x576"), ("tts_one", None)]


def test_limits_per_video(talk, monkeypatch, fake_smi):
    paths, root, video, cfg = talk
    status(paths)
    fake_ai(monkeypatch, gen_plan(cfg))
    result = ai_edit.ai_edit_video(video, cfg, "x", render=False, reporter=Recorder(),
                                   gen_paths=paths, max_ai_clips=1)
    assert "1 AI picture(s)/clip(s) over this video's limit of 1" in " ".join(
        result["summary"]["details"])
    assert [c["model_type"] for c in calls(root)] == ["img_small", "tts_one"]
    (root / "calls.jsonl").unlink()
    result = ai_edit.ai_edit_video(video, cfg, "x", render=False, reporter=Recorder(),
                                   gen_paths=paths, max_gen_minutes=0.01)
    assert calls(root) == []
    assert "limit of 0.01 minutes was reached" in " ".join(result["summary"]["details"])


def test_without_wangp_the_edit_still_finishes_and_says_why(talk, monkeypatch):
    paths, root, video, cfg = talk
    data = json.loads(paths.settings.read_text())
    data["wangp"]["folder"] = ""
    paths.settings.write_text(json.dumps(data))
    prompts = fake_ai(monkeypatch, gen_plan(cfg))
    result = ai_edit.ai_edit_video(video, cfg, "x", reporter=Recorder(), gen_paths=paths)
    assert "pictures NOT available" in prompts[0]
    assert Path(result["output"]).exists()
    assert any("WanGP is not set up" in d for d in result["summary"]["details"])


def test_cli_gen_config_saves_wangp_paths(tmp_path):
    settings = tmp_path / "generation.json"
    run = subprocess.run([sys.executable, str(PROJECT_DIR / "editor.py"), "--json", "gen-config",
                          "--wangp-folder", str(tmp_path), "--wangp-python", sys.executable,
                          "--generation-settings", str(settings)],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    data = json.loads(settings.read_text())
    assert data["wangp"]["folder"] == str(tmp_path) and data["wangp"]["python"] == sys.executable
    result = json.loads(run.stdout.splitlines()[-1])
    assert "wgp.py was not found" in result["problems"][0]
