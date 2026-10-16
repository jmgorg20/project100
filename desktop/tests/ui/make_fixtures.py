"""Make the files the UI tests need, with the real engine (FFmpeg + Python, no API calls).

    python tests/ui/make_fixtures.py

Writes tests/ui/fixtures/:
  demo_talk.mp4, demo_talk_2.mp4   synthetic talking videos (colour bars + tone)
  github_logo.png                  a photo the AI may use
  demo_talk_ai.mp4                 the engine's AI edit render (from a fixed plan)
  demo.project.json / demo.plan.json   that edit's project, plan, preset plan and summary
  demo_frame.png                   an exact frame
  parity.project.json, parity.json captions/photo on black + where the engine drew them
  editor.media.json, thumbs_*.jpg, tone.wav
                                   the timeline editor: media info, waveform peaks and filmstrip
                                   pictures made by the engine (media-info / peaks / thumbs)
  gen.status.json, gen.compare.json, gen_*.png
                                   the "AI pictures, clips & voice" screen: the engine's status,
                                   test results and a Compare run, made with the fake WanGP in
                                   tests/fake_wangp and a fake nvidia-smi (no GPU, no real models)
  broll.json, broll_*.png          B-roll found by the engine: two from a library folder, one
                                   from "Pixabay" (its answer faked, no network) and one made
                                   by the fake WanGP
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from autoedit import ai_edit  # noqa: E402
from autoedit.ai_plan import preset_plan  # noqa: E402
from autoedit.config import load_config  # noqa: E402
from autoedit.project import media_from_file, new_project, save_project  # noqa: E402
from autoedit.project_render import render_frame  # noqa: E402
from autoedit.words import load_transcript  # noqa: E402
from tests import synthetic  # noqa: E402

OUT = HERE / "fixtures"
PARITY_TIMES = {"classic": 0.5, "top_banner": 1.5, "one_word": 2.5}


def ink_box(png):
    """Bounding box (x0, y0, x1, y1) of the non-black pixels of a 1080x1920 frame."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    width = 1080
    xs, ys = [], []
    for i, value in enumerate(raw):
        if value > 60:
            ys.append(i // width)
            xs.append(i % width)
    return [min(xs), min(ys), max(xs) + 1, max(ys) + 1]


FAKE_SMI = """#!{python}
import sys
from pathlib import Path
if "--query-gpu=memory.used" in sys.argv:   # rises while a job runs, like real VRAM use
    count = Path(__file__).with_name("calls")
    n = int(count.read_text()) + 1 if count.exists() else 0
    count.write_text(str(n))
    print(1200 + 350 * (n % 20))
else:
    print("NVIDIA GeForce RTX 3060, 12288, 555.85")
"""


def editor_fixtures(work):
    """What the engine says about the demo files, for the timeline editor's stand-in bridge."""
    from autoedit.media_tools import peaks, thumbs
    from autoedit.project import media_from_file
    tone = synthetic.make_tone(OUT / "tone.wav", frequency=440, duration=6.0)
    data = {"info": {}, "peaks": {}, "thumbs": {}}
    for i, f in enumerate([OUT / "demo_talk.mp4", OUT / "demo_talk_2.mp4", OUT / "github_logo.png", tone]):
        entry = media_from_file(f, f"m{i + 1}")
        entry["path"] = f"C:/Videos/{f.name}"
        data["info"][f.name] = entry
        if entry["kind"] != "image":
            data["peaks"][f.name] = peaks(f, work / "peaks")
        if entry["kind"] != "audio":
            th = thumbs(f, work / "thumbs", height=96)
            names = []
            for n, src in enumerate(th["files"], start=1):
                name = f"thumbs_{f.stem}_{n:03d}.jpg"
                shutil.copy(src, OUT / name)
                names.append(f"C:/cache/{name}")
            data["thumbs"][f.name] = {**th, "files": names}
    (OUT / "editor.media.json").write_text(json.dumps(data), encoding="utf-8")


def generation_fixtures(work):
    """Real engine status/benchmark/compare output, run against the fake WanGP."""
    from autoedit import generation

    root = work / "WanGP"
    shutil.copytree(REPO / "tests" / "fake_wangp", root)
    hf = "https://huggingface.co/SomeOrg/{}/resolve/main/model.safetensors"

    def model(model_type, name, kind, status="available", **extra):
        return {"model_type": model_type, "name": name, "family": "Example family",
                "main_output": [kind], "status": status, "urls": [hf.format(model_type)], **extra}

    (root / "fake_models.json").write_text(json.dumps([
        model("example_image_small", "Example Image Small", "image", seconds=0.3),
        model("example_image_large", "Example Image Large", "image", seconds=0.6,
              oom_above_pixels=1_500_000),
        model("example_video_fast", "Example Video Fast", "video", seconds=0.4),
        model("example_video_large", "Example Video Large", "video", status="missing"),
        model("example_tts", "Example Voice", "audio", seconds=0.2),
        model("example_music", "Example Music", "audio", status="missing"),
    ]))
    bin_dir = work / "bin"
    bin_dir.mkdir()
    smi = bin_dir / "nvidia-smi"
    smi.write_text(FAKE_SMI.format(python=sys.executable))
    smi.chmod(smi.stat().st_mode | stat.S_IEXEC)
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    generation.PROJECT_DIR = work / "project"

    paths = generation.Paths(work / "generation.json", work / "gen-data")
    generation.load_settings(paths)                       # created from the example
    data = json.loads(paths.settings.read_text())
    data["wangp"] = {"folder": str(root), "python": sys.executable, "cli_args": []}
    data["templates_folder"] = str(work / "templates")
    (work / "templates").mkdir()

    def template(tier, name, model_type, overrides=None, **values):
        (work / "templates" / name).write_text(json.dumps({"model_type": model_type, **values}))
        tier.update(template=name, overrides=overrides or {})

    image, video, voice = (data["tiers"][c] for c in ("image", "video", "voice"))
    template(image[0], "image_draft.json", "example_image_small", resolution="360x640",
             num_inference_steps=4)
    template(image[1], "image_low.json", "example_image_small", resolution="540x960",
             num_inference_steps=8)
    template(image[2], "image_mid.json", "example_image_large", resolution="720x1280",
             num_inference_steps=20)
    image[2]["vram_gb"] = 10
    template(image[3], "image_high.json", "example_image_large", {"resolution": "1080x1920"},
             resolution="720x1280", num_inference_steps=30)
    template(video[0], "video_draft.json", "example_video_fast", resolution="320x576",
             video_length=17)
    template(video[3], "video_high.json", "example_video_large")
    template(voice[1], "voice_low.json", "example_tts", duration_seconds=2)
    paths.settings.write_text(json.dumps(data))

    quiet = lambda *_: None                               # noqa: E731
    info = generation.status(paths, check_wangp=True, log=quiet)
    settings, _ = generation.load_settings(paths)
    generation.benchmark(paths, settings, info["hardware"]["key"], info["tiers"], log=quiet)
    compare = generation.compare(paths, settings, info["hardware"]["key"], info["tiers"],
                                 "image", settings["benchmark"]["prompts"]["image"], 1234,
                                 log=quiet)
    for r in compare["results"]:
        if r["output"]:
            name = f"gen_{r['tier'].lower()}.png"
            shutil.copy(r["output"], OUT / name)
            r["output"] = f"C:/AutoEditor/work/generation/compare/{name}"
    info = generation.status(paths, log=quiet)
    # Paths as they would look on the creator's Windows PC.
    text = json.dumps(info).replace(str(work), "C:/AutoEditor").replace(
        json.dumps(sys.executable)[1:-1], "C:/Users/you/miniconda3/envs/wan2gp/python.exe")
    (OUT / "gen.status.json").write_text(text, encoding="utf-8")
    (OUT / "gen.compare.json").write_text(json.dumps(compare).replace(str(work), "C:/AutoEditor"),
                                          encoding="utf-8")
    return paths


def broll_fixtures(work, gen_paths):
    """The engine's B-roll finder: library, stock (a faked Pixabay answer) and AI (fake WanGP)."""
    import requests

    from autoedit import broll
    library = work / "My B-roll"
    (library / "coffee").mkdir(parents=True)
    synthetic.make_image(library / "coffee" / "coffee cup.png", color="saddlebrown", size="720x1280")
    synthetic.make_image(library / "coffee" / "coffee beans.png", color="black", size="720x1280")
    synthetic.make_image(library / "jeepney street.png", color="steelblue", size="720x1280")
    cfg = load_config()
    cfg["broll"]["library_folder"] = str(library)
    downloads = work / "broll-downloads"
    found = []

    def keep(tag, file, meta):
        name = f"broll_{tag}{Path(file).suffix}"
        shutil.copy(file, OUT / name)
        media = media_from_file(OUT / name, "broll")
        media["path"] = f"C:/Videos/broll/{name}"
        found.append({"tag": tag, "file": media["path"], "media": media, "broll": meta,
                      "notes": []})

    first, meta, _ = broll.find_one({"search": "coffee cup"}, cfg, download_folder=downloads)
    keep("library1", first, meta)
    second, meta, _ = broll.find_one({"search": "coffee cup"}, cfg, download_folder=downloads,
                                     exclude=[first])
    keep("library2", second, meta)

    # Stock: the real search/download code, with Pixabay's answer faked (no network, no key).
    picture = synthetic.make_image(work / "stock.png", color="seagreen", size="720x1280")
    real_get = requests.get

    class Answer:
        status_code, text = 200, ""

        def __init__(self, data=None, body=b""):
            self.data, self.body = data, body

        def json(self):
            return self.data

        def iter_content(self, size):
            yield self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_get(url, **kw):
        if url == "https://pixabay.com/api/":
            return Answer({"hits": [{"id": 4521, "pageURL": "https://pixabay.com/photos/4521/",
                                     "user": "Maria_Santos", "imageWidth": 720,
                                     "imageHeight": 1280,
                                     "largeImageURL": "https://cdn.pixabay.com/4521.png"}]})
        return Answer(body=picture.read_bytes())
    requests.get = fake_get
    os.environ["PIXABAY_API_KEY"] = "fixture-only"
    try:
        stock_cfg = dict(cfg, broll={"library_folder": "", "use_stock": True})
        file, meta, _ = broll.find_one({"search": "mountain sunrise"}, stock_cfg,
                                       download_folder=downloads)
    finally:
        requests.get = real_get
        os.environ.pop("PIXABAY_API_KEY")
    keep("stock", file, meta)

    file, meta, _ = broll.find_one({"prompt": "a cartoon robot waving", "style": "cartoon",
                                    "source": "ai"}, cfg, quality="draft", gen_paths=gen_paths,
                                   download_folder=downloads, log=lambda *_: None)
    keep("ai", file, meta)
    # The library as the app lists it; the browser can show copies of its pictures.
    files, media = [], {}
    for n, f in enumerate(sorted(library.rglob("*.png")), start=1):
        name = f"broll_lib{n}.png"
        shutil.copy(f, OUT / name)
        path = f"C:/Videos/broll/{name}"
        files.append({"path": path, "name": f.name,
                      "group": f.parent.relative_to(library).as_posix().replace(".", "")})
        media[path] = {**media_from_file(f, "lib"), "path": path, "name": f.name}
    (OUT / "broll.json").write_text(json.dumps({"found": found, "library": files,
                                                "media": media}, indent=1), encoding="utf-8")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    work = OUT / "_work"
    work.mkdir()
    video = synthetic.make_video(OUT / "demo_talk.mp4")
    shutil.copy(video, OUT / "demo_talk_2.mp4")
    photo = synthetic.make_image(OUT / "github_logo.png")
    words = load_transcript(synthetic.make_transcript(work / "talk.json"))

    cfg = load_config()
    cfg["output"].update(folder=str(work), encoder_speed="ultrafast")
    cfg["work_folder"] = str(work)
    cfg["ai"]["cache_folder"] = str(work / "cache")
    cfg["overlays"]["triggers_file"] = str(work / "none.yaml")
    ai_edit.transcribe = lambda *a, **k: words           # no Whisper call
    plan = preset_plan(cfg)
    plan.update(style="bold_caps", summary="Mabilis na edit with big captions and the GitHub logo.",
                notes=["No music file was given, so no music was added."])
    plan["captions"].update(size_scale=1.2, highlight_words=["GitHub"])
    plan["photos"] = [{"file": "github_logo.png", "at": 5.5, "duration": 1.5, "position": "top",
                       "reason": "when you say GitHub"}]
    result = ai_edit.ai_edit_video(video, cfg, "Fast, big captions, show the GitHub logo",
                                   [photo], plan=plan, output=OUT / "demo_talk_ai.mp4")
    project = json.loads(Path(result["project"]).read_text(encoding="utf-8"))
    (OUT / "demo.project.json").write_text(json.dumps(project), encoding="utf-8")
    (OUT / "demo.plan.json").write_text(json.dumps(
        {"plan": plan, "baseline": preset_plan(cfg), "summary": result["summary"]}), encoding="utf-8")
    render_frame(project, 1.0, OUT / "demo_frame.png", work_dir=work / "frame")

    # Parity: captions in three zones and one photo, on black, rendered by the engine.
    parity = new_project("parity")
    pic = synthetic.make_image(OUT / "parity_photo.png", color="magenta", size="600x400")
    parity["media"] = [media_from_file(pic, "p1")]
    tracks = {t["id"]: t for t in parity["tracks"]}
    tracks["main"]["clips"] = []
    words_text = [{"text": "Kumusta", "start": 0.0, "end": 0.4},
                  {"text": "mga", "start": 0.45, "end": 0.6},
                  {"text": "kaibigan", "start": 0.65, "end": 0.95}]
    tracks["captions"]["clips"] = [
        {"id": f"t{i}", "type": "caption", "start": float(i), "duration": 1.0, "style": name,
         "words": words_text if name != "one_word" else words_text[:1]}
        for i, name in enumerate(PARITY_TIMES)]
    tracks["photos"]["clips"] = [{"id": "o1", "type": "image", "media": "p1", "start": 3.0,
                                  "duration": 1.0, "x": 500, "y": 520, "width": 820,
                                  "height": 560, "animation": "none"}]
    save_project(parity, OUT / "parity.project.json")
    cases = []
    for name, t in [*PARITY_TIMES.items(), ("photo", 3.5)]:
        png = render_frame(parity, t, work / f"parity_{name}.png", work_dir=work / "pf")
        cases.append({"name": name, "time": t, "box": ink_box(png)})
    (OUT / "parity.json").write_text(json.dumps({"cases": cases}, indent=1), encoding="utf-8")
    # The test browser (open-source Chromium) cannot decode H.264, so it gets WebM copies.
    for mp4 in OUT.glob("*.mp4"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-c:v", "libvpx-vp9",
                        "-b:v", "1M", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus",
                        str(mp4.with_suffix(".webm"))], check=True)
    editor_fixtures(work)
    broll_fixtures(work, generation_fixtures(work))
    shutil.rmtree(work, ignore_errors=True)
    print(f"fixtures written to {OUT}")


if __name__ == "__main__":
    main()
