"""Make the files the UI tests need, with the real engine (FFmpeg + Python, no API calls).

    python tests/ui/make_fixtures.py

Writes tests/ui/fixtures/:
  demo_talk.mp4, demo_talk_2.mp4   synthetic talking videos (colour bars + tone)
  github_logo.png                  a photo the AI may use
  demo_talk_ai.mp4                 the engine's AI edit render (from a fixed plan)
  demo.project.json / demo.plan.json   that edit's project, plan, preset plan and summary
  demo_frame.png                   an exact frame
  parity.project.json, parity.json captions/photo on black + where the engine drew them
"""

import json
import shutil
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
    shutil.rmtree(work, ignore_errors=True)
    print(f"fixtures written to {OUT}")


if __name__ == "__main__":
    main()
