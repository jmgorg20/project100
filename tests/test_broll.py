"""The B-roll director: your library, then free stock (with your key), then AI generation."""

import json
import os
import sys
from pathlib import Path

import pytest

from autoedit import PROJECT_DIR, ai_edit, broll, stock
from autoedit.ai_plan import preset_plan, upgrade_plan, validate_plan
from autoedit.config import load_config
from autoedit.errors import EditorError
from autoedit.generation import Paths
from autoedit.project import load_project, save_project, validate_project
from autoedit.words import load_transcript
from tests import synthetic
from tests.test_project_render import media, run_cli, tracks, vclip  # noqa: F401


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / "My B-roll"                     # a space in the path, as on Windows
    (folder / "coffee").mkdir(parents=True)
    (folder / "cartoon").mkdir()
    synthetic.make_image(folder / "coffee" / "cup_morning.jpg", color="brown")
    synthetic.make_image(folder / "coffee" / "Coffee Beans.png", color="black")
    synthetic.make_image(folder / "cartoon" / "coffee cup.png", color="yellow")
    synthetic.make_image(folder / "low_poly_city.png", color="gray")
    synthetic.make_color_video(folder / "JeepneyStreet.mp4", width=360, height=640)
    (folder / "notes.txt").write_text("not media")
    return folder


# --- matching your library ----------------------------------------------------------------

def test_tokens_drop_filler_words_and_plurals():
    assert broll.tokens("A cup of Coffees, with beans") == ["cup", "coffee", "bean"]
    assert broll.tokens("JeepneyStreet_2024") == ["jeepney", "street"]
    assert broll.tokens("mga tao sa kalye") == ["tao", "kalye"]


def test_library_index_and_matching(library):
    files = broll.index_library(library)
    names = {f.path.name: f for f in files}
    assert set(names) == {"cup_morning.jpg", "Coffee Beans.png", "coffee cup.png",
                          "low_poly_city.png", "JeepneyStreet.mp4"}
    assert names["coffee cup.png"].style == "cartoon"
    assert names["low_poly_city.png"].style == "low_poly"
    assert names["JeepneyStreet.mp4"].kind == "video"
    assert {"coffee", "cup", "morning"} <= names["cup_morning.jpg"].words   # folder words too

    match = lambda *a, **k: (broll.match_library(files, *a, **k) or None)  # noqa: E731
    assert match("coffee cup", "image").path.name == "cup_morning.jpg"
    # A cartoon look takes only a cartoon file; a realistic look never takes a cartoon.
    assert match("coffee cup", "image", "cartoon").path.name == "coffee cup.png"
    assert match("city", "image", "realistic") is None
    assert match("city", "image", "low_poly").path.name == "low_poly_city.png"
    # Videos are preferred for a video item; half the words must match.
    assert match("jeepney street traffic", "video").path.name == "JeepneyStreet.mp4"
    assert match("busy jeepney street traffic", "video").path.name == "JeepneyStreet.mp4"
    assert match("spaceship launch", "video") is None
    # "Find another": the current file is excluded.
    first = match("coffee", "image")
    second = match("coffee", "image", exclude=[first.path])
    assert second and second.path != first.path
    assert broll.index_library(library / "missing") == [] and broll.index_library("") == []


def test_the_ai_is_told_which_sources_exist(library):
    cfg = load_config()
    cfg["broll"]["library_folder"] = str(library)
    text = broll.sources_text(cfg, {"image": True, "video": False})
    assert "library: 5 files" in text and "coffee" in text and "jeepney" in text
    assert "free stock: none" in text and "AI generation: pictures" in text
    cfg["broll"]["library_folder"] = ""
    assert "leave ai_clips empty" in broll.sources_text(cfg, {})


# --- free stock (fake Pexels/Pixabay answers; no network) ----------------------------------

class FakeResponse:
    def __init__(self, status=200, data=None, body=b"", text=""):
        self.status_code, self._data, self._body, self.text = status, data, body, text

    def json(self):
        return self._data

    def iter_content(self, size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


PEXELS_VIDEOS = {"videos": [
    {"id": 11, "url": "https://www.pexels.com/video/11/", "duration": 8, "user": {"name": "Ana"},
     "video_files": [
         {"link": "https://v.pexels/11-sd.mp4", "width": 540, "height": 960},
         {"link": "https://v.pexels/11-hd.mp4", "width": 1080, "height": 1920},
         {"link": "https://v.pexels/11-4k.mp4", "width": 2160, "height": 3840},
         {"link": "https://v.pexels/11-wide.mp4", "width": 1920, "height": 1080}]},
    {"id": 12, "url": "https://www.pexels.com/video/12/", "duration": 5, "user": {"name": "Ben"},
     "video_files": [{"link": "https://v.pexels/12.mp4", "width": 1920, "height": 1080}]}]}
PIXABAY_IMAGES = {"hits": [
    {"id": 7, "pageURL": "https://pixabay.com/7", "user": "carla", "imageWidth": 1000,
     "imageHeight": 1500, "largeImageURL": "https://cdn.pixabay/7.png?x=1"}]}


@pytest.fixture
def fake_requests(monkeypatch):
    import requests
    calls = []

    def get(url, timeout=None, params=None, headers=None, stream=False):
        calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        if "pexels.com/videos/search" in url:
            return FakeResponse(data=PEXELS_VIDEOS)
        if "pexels.com/v1/search" in url:
            return FakeResponse(data={"photos": []})
        if url.startswith("https://pixabay.com/api/"):
            return FakeResponse(data=PIXABAY_IMAGES if "videos" not in url else {"hits": []})
        return FakeResponse(body=b"FAKE-MEDIA-" + url.encode())
    monkeypatch.setattr(requests, "get", get)
    return calls


def test_stock_needs_your_key_and_never_prints_it(monkeypatch, fake_requests, capsys):
    assert stock.available() == []
    assert stock.search("coffee", "image") == []                 # no key, no request
    assert fake_requests == []
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-secret-123")
    monkeypatch.setenv("PIXABAY_API_KEY", "your_pixabay_api_key_here")   # the example = none
    assert stock.available() == ["pexels"]
    found = stock.search("jeepney street", "video")
    assert fake_requests[0]["headers"] == {"Authorization": "pexels-secret-123"}
    assert fake_requests[0]["params"]["orientation"] == "portrait"
    # Portrait first; of a clip's files: the smallest that is at least 1280 tall.
    assert [(f.id, f.url) for f in found] == [("11", "https://v.pexels/11-hd.mp4"),
                                              ("12", "https://v.pexels/12.mp4")]
    assert found[0].credit == "Video by Ana on Pexels (https://www.pexels.com/video/11/)"
    assert stock.search("jeepney", "video", exclude={"pexels-11"})[0].id == "12"
    # Pexels has no cartoons: a cartoon look asks only Pixabay.
    fake_requests.clear()
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-secret-456")
    found = stock.search("coffee cartoon", "image", style="cartoon")
    assert [c["url"] for c in fake_requests] == ["https://pixabay.com/api/"]
    assert fake_requests[0]["params"]["image_type"] == "illustration"
    assert found[0].credit == "Photo by carla on Pixabay (https://pixabay.com/7)"
    out = capsys.readouterr()
    assert "secret" not in out.out + out.err


def test_stock_errors_are_plain_and_do_not_show_the_key(monkeypatch):
    import requests
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-secret-123")
    for status, words in ((401, "refused the API key"), (429, "free limit"), (500, "failed")):
        monkeypatch.setattr(requests, "get", lambda *a, s=status, **k: FakeResponse(s, text="x"))
        with pytest.raises(EditorError, match=words) as info:
            stock.search("coffee", "image")
        assert "secret" not in str(info.value)

    def offline(*a, **k):
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(requests, "get", offline)
    with pytest.raises(EditorError, match="check your internet"):
        stock.search("coffee", "image")


def test_stock_download_is_kept_and_never_half_written(tmp_path, fake_requests):
    item = stock.StockItem("pixabay", "7", "image", "https://cdn.pixabay/7.png?x=1", "p", "c")
    path = stock.download(item, tmp_path / "dl")
    assert path.name == "pixabay-7.png" and path.read_bytes().startswith(b"FAKE-MEDIA-")
    n = len(fake_requests)
    assert stock.download(item, tmp_path / "dl") == path and len(fake_requests) == n   # kept
    assert not list((tmp_path / "dl").glob("*.part"))


# --- the order: library -> stock -> AI ------------------------------------------------------

def item(**kw):
    return {"kind": "image", "prompt": "a cup of coffee on a table", "search": "coffee cup",
            "style": "realistic", "source": "auto", "at": 1.0, "duration": 2.0,
            "position": "full", "reason": "", **kw}


@pytest.fixture
def fake_gen(monkeypatch, tmp_path):
    """Stands in for WanGP: records the prompts and 'makes' a picture for each."""
    made = []

    def generate(plan, passes, gen_paths=None, max_minutes=None, max_clips=None,
                 reporter=None, cancel=None, log=print, seed_salt=""):
        out = {"draft": {"ai_clips": [], "voiceovers": [None] * len(plan["voiceovers"])},
               "final": {"ai_clips": [], "voiceovers": [None] * len(plan["voiceovers"])},
               "notes": [], "done": [], "tiers": {}}
        for i, clip in enumerate(plan["ai_clips"]):
            made.append((clip["prompt"], passes, seed_salt))
            file = synthetic.make_image(tmp_path / f"ai{len(made)}.png", color="green")
            for p in ("draft", "final"):
                out[p]["ai_clips"].append(str(file) if p in passes else None)
            out["tiers"][f"ai_clips.{i}"] = "Mid"
            out["done"].append({"item": "AI picture", "tier": "Mid", "list": "ai_clips",
                                "index": i, "seconds": 1, "success": True})
        return out
    monkeypatch.setattr(broll, "generate_for_plan", generate)
    return made


def test_library_first_then_stock_then_ai(library, monkeypatch, fake_requests, fake_gen,
                                          tmp_path):
    cfg = load_config()
    cfg["broll"]["library_folder"] = str(library)
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-secret-456")
    plan = {"ai_clips": [item(), item(search="mountain sunrise", prompt="a mountain sunrise"),
                         item(search="robot dog", prompt="a robot dog", style="stylized_3d",
                              source="ai"),
                         item(search="spaceship", source="library")],
            "voiceovers": []}
    out = broll.resolve_plan(plan, cfg, ["final"], download_folder=tmp_path / "dl")
    files, metas = out["final"]["ai_clips"], out["meta"]["ai_clips"]
    assert Path(files[0]).name == "cup_morning.jpg" and metas[0]["source"] == "library"
    assert metas[0]["ai_generated"] is False
    assert Path(files[1]).name == "pixabay-7.png"
    assert metas[1].items() >= {"source": "pixabay", "author": "carla",
                                "stock_id": "pixabay-7", "license": "Pixabay Content License",
                                "license_url": "https://pixabay.com/service/license-summary/"
                                }.items()
    assert metas[2]["source"] == "ai" and metas[2]["ai_generated"] and metas[2]["tier"] == "Mid"
    assert "WanGP" in metas[2]["license"]
    # Only the AI item went to WanGP, with the look's words added; the library-only one did not.
    assert fake_gen == [("a robot dog, stylized 3D render, toy-like robot style, soft studio "
                         "lighting", ["final"], "")]
    assert files[3] is None
    assert any("nothing in your B-roll library matched \"spaceship\"" in n for n in out["notes"])
    assert out["sourced"][0].startswith("B-roll at 0:01 (coffee cup): from your B-roll library")
    assert "Photo by carla on Pixabay" in out["sourced"][1]
    # The same library file is not used twice in one video.
    two = broll.resolve_plan({"ai_clips": [item(), item(at=4)], "voiceovers": []}, cfg,
                             ["final"], download_folder=tmp_path / "dl")
    assert two["final"]["ai_clips"][0] != two["final"]["ai_clips"][1]


def test_no_sources_means_ai_and_its_notes(fake_gen, tmp_path):
    cfg = load_config()
    cfg["broll"]["library_folder"] = ""
    out = broll.resolve_plan({"ai_clips": [item()], "voiceovers": []}, cfg, ["draft"],
                             download_folder=tmp_path)
    assert out["draft"]["ai_clips"][0] and out["final"]["ai_clips"][0] is None
    assert out["meta"]["ai_clips"][0]["source"] == "ai"


def test_find_one_for_find_another_and_regenerate(library, fake_gen, tmp_path):
    cfg = load_config()
    cfg["broll"]["library_folder"] = str(library)
    file, meta, _ = broll.find_one({"search": "coffee"}, cfg, download_folder=tmp_path)
    again, _, _ = broll.find_one({"search": "coffee"}, cfg, download_folder=tmp_path,
                                 exclude=[file])
    assert again != file and again.parent.name == "coffee"
    # Regenerate an AI picture: a new seed each time.
    broll.find_one({"prompt": "a robot", "source": "ai"}, cfg, quality="draft",
                   download_folder=tmp_path, new_version=True)
    assert fake_gen[-1][1] == ["draft"] and fake_gen[-1][2].startswith("#")
    with pytest.raises(EditorError, match="Describe what to show"):
        broll.find_one({"prompt": " "}, cfg)
    with pytest.raises(EditorError, match="Unknown look"):
        broll.find_one({"prompt": "x", "style": "oil"}, cfg)


# --- plans and projects -------------------------------------------------------------------

def test_older_plans_still_load():
    cfg = load_config()
    plan = preset_plan(cfg)
    plan["ai_clips"] = [{"kind": "image", "prompt": "a steaming cup of coffee", "at": 1.0,
                         "duration": 2.0, "position": "full", "reason": ""}]
    assert validate_plan(plan, 8.0)                       # strict: the new fields are required
    new = upgrade_plan(plan)
    assert validate_plan(new, 8.0) == []
    assert new["ai_clips"][0].items() >= {"search": "a steaming cup of", "style": "realistic",
                                          "source": "auto"}.items()
    assert "search" not in plan["ai_clips"][0]           # the caller's plan is not changed


def test_project_clip_operations_keep_the_project_valid(media, library):  # noqa: F811
    tmp, p = media
    from autoedit.project import media_from_file
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=4.0)]
    meta = {"source": "library", "kind": "image", "search": "coffee", "ai_generated": False}
    pic = media_from_file(library / "coffee" / "cup_morning.jpg", "m_cup")
    first = broll.add_clip(p, pic, meta, 0.5, 2.0, "full")
    assert first["label"] == "Library: coffee" and first["broll"]["position"] == "full"
    assert (first["width"], first["height"]) == (1080, 1920)
    overlap = broll.add_clip(p, pic, meta, 1.0, 1.0, "top")     # overlaps: a new lane
    lanes = [t for t in p["tracks"] if t["kind"] == "overlay"]
    assert len(lanes) == 2 and overlap in lanes[1]["clips"]
    # Replace a picture with a 4 s video on a 2 s clip: it becomes a 2 s video clip.
    video = media_from_file(library / "JeepneyStreet.mp4", "m_jeep")
    clip = broll.replace_clip_media(p, first["id"], video, {"source": "pexels", "kind": "video",
                                                            "search": "jeepney",
                                                            "credit": "Video by A on Pexels"})
    assert clip["type"] == "video" and (clip["in"], clip["out"], clip["duration"]) == (0, 2, 2)
    assert clip["broll"]["position"] == "full"
    assert validate_project(p) == []
    lines, ai = broll.credits(p)
    assert lines == ["Video by A on Pexels"] and ai is False
    with pytest.raises(EditorError, match="not a picture"):
        broll.replace_clip_media(p, "v1", video, meta)


@pytest.fixture
def talk(tmp_path, monkeypatch):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    words = load_transcript(synthetic.make_transcript(tmp_path / "talk.json"))
    monkeypatch.setattr(ai_edit, "transcribe", lambda *a, **k: words)
    cfg = load_config()
    cfg["output"].update(folder=str(tmp_path / "out"), encoder_speed="ultrafast")
    cfg["work_folder"] = str(tmp_path / "work")
    cfg["ai"]["cache_folder"] = str(tmp_path / "cache")
    cfg["overlays"]["triggers_file"] = str(tmp_path / "none.yaml")
    return video, cfg, Paths(tmp_path / "generation.json", tmp_path / "gen")


def test_ai_edit_puts_library_broll_on_the_timeline_with_its_source(talk, library,
                                                                    monkeypatch):
    video, cfg, paths = talk
    cfg["broll"]["library_folder"] = str(library)
    plan = preset_plan(cfg)
    plan["ai_clips"] = [item(at=2.9, search="coffee cup", reason="kape"),
                        item(at=5.5, search="robot", prompt="a robot waving", source="ai",
                             style="cartoon")]
    prompts = []

    def ask(provider, model, system, prompt, schema, **kw):
        prompts.append((system, prompt))
        return json.dumps(plan), {"input_tokens": 1, "output_tokens": 1}, model
    monkeypatch.setattr(ai_edit, "ask_json", ask)
    result = ai_edit.ai_edit_video(video, cfg, "lagyan ng b-roll ng kape", render=False,
                                   gen_paths=paths)
    system, prompt = prompts[0]
    assert "B-ROLL SOURCES" in prompt and "library: 5 files" in prompt
    assert "style: realistic unless" in system
    project = load_project(result["project"])
    shown = [c for t in project["tracks"] if t["kind"] == "overlay" for c in t["clips"]]
    assert len(shown) == 1                    # the AI one: WanGP is not set up here
    assert shown[0]["broll"]["source"] == "library" and shown[0]["label"] == "Library: coffee cup"
    details = " ".join(result["summary"]["details"])
    assert "from your B-roll library (cup_morning.jpg)" in details
    assert "WanGP is not set up" in details


def cli_env(tmp_path):
    return {**os.environ, "AUTOEDIT_GENERATION_HOME": str(tmp_path / "genhome"),
            "PEXELS_API_KEY": "", "PIXABAY_API_KEY": ""}


def test_cli_broll_find_add_and_find_another(media, library):  # noqa: F811
    tmp, p = media
    tracks(p)["main"]["clips"] = [vclip("v1", 0.0, 0.0, duration=4.0)]
    project_file = save_project(p, tmp / "my video.project.json")
    base = [sys.executable, str(PROJECT_DIR / "editor.py"), "--json", "broll",
            "--library", str(library)]
    import subprocess

    def run(*args):
        proc = subprocess.run([*base, *args], capture_output=True, text=True, timeout=120,
                              env=cli_env(tmp), cwd=tmp)
        lines = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
        return proc.returncode, lines[-1], proc.stderr

    code, last, err = run("--search", "jeepney street", "--kind", "video")
    assert code == 0, err
    assert last["type"] == "result" and last["media"]["kind"] == "video"
    assert last["broll"]["source"] == "library" and last["file"].endswith("JeepneyStreet.mp4")

    code, last, err = run(str(project_file), "--new", "--at", "1", "--duration", "2",
                          "--search", "coffee", "--position", "top")
    assert code == 0, err
    clip_id = last["clip"]
    saved = load_project(project_file)
    clip = next(c for t in saved["tracks"] for c in t["clips"] if c["id"] == clip_id)
    first_media = clip["media"]
    assert clip["start"] == 1 and clip["animation"] == "pop" and clip["broll"]["position"] == "top"

    code, last, err = run(str(project_file), "--clip", clip_id)          # find another
    assert code == 0, err
    saved = load_project(project_file)
    clip = next(c for t in saved["tracks"] for c in t["clips"] if c["id"] == clip_id)
    assert clip["media"] != first_media and clip["broll"]["source"] == "library"
    assert validate_project(saved) == []

    code, last, err = run("--search", "spaceship", "--source", "library")
    assert code != 0 and last["type"] == "error" and "No B-roll found" in last["message"]


# --- effects the AI plans (the "VFX director") ---------------------------------------------

def test_planned_effects_land_on_the_cut_timeline(talk, monkeypatch):
    video, cfg, paths = talk
    plan = preset_plan(cfg)
    plan["effects"] = [
        {"effect": "shake", "at": 6.4, "duration": 0.4, "intensity": 0.8, "on_cut": False,
         "reason": "500 pesos!"},
        {"effect": "flash", "at": 5.0, "duration": 0.3, "intensity": 1.0, "on_cut": True,
         "reason": "new topic"},
        {"effect": "glitch", "at": 4.8, "duration": 0.3, "intensity": 0.5, "on_cut": False,
         "reason": "inside a cut part: moves to the next kept part"},
    ]
    result = ai_edit.ai_edit_video(video, cfg, "", render=False, plan=plan, gen_paths=paths)
    project = load_project(result["project"])
    assert validate_project(project) == []
    main = sorted(next(t for t in project["tracks"] if t["kind"] == "video")["clips"],
                  key=lambda c: c["start"])
    cuts = [c["start"] for c in main[1:]]
    fx = {c["effect"]: c for t in project["tracks"] if t["kind"] == "effect"
          for c in t["clips"] if c["type"] == "fx"}
    assert set(fx) == {"shake", "flash", "glitch"}
    # The shake is where "500" is said (raw 6.35 s; the shake is 0.05 s later), on the cut
    # timeline: the same mapping as the caption words.
    said = next(c["start"] + w["start"] for t in project["tracks"] if t["kind"] == "caption"
                for c in t["clips"] for w in c["words"] if w["text"].startswith("500"))
    assert fx["shake"]["start"] == pytest.approx(said + 0.05, abs=0.02)
    # The flash is a transition: centred on a jump cut.
    assert any(abs(fx["flash"]["start"] + 0.15 - cut) < 0.01 for cut in cuts)
    assert fx["flash"]["intensity"] == 1.0 and fx["shake"]["duration"] == 0.4
    details = " ".join(result["summary"]["details"])
    assert "Added 3 effects:" in details and "shake at" in details


def test_plans_without_effects_still_work():
    cfg = load_config()
    plan = preset_plan(cfg)
    del plan["effects"]
    assert any("effects" in p for p in validate_plan(plan, 8.0))
    assert validate_plan(upgrade_plan(plan), 8.0) == []
    late = upgrade_plan(plan)
    late["effects"] = [{"effect": "flash", "at": 9.0, "duration": 0.3, "intensity": 1,
                        "on_cut": False, "reason": ""}]
    assert any("after the end" in p for p in validate_plan(late, 8.0))
