"""M3, the look: what is said turns into the editorial looks (struck-out words at "ngayon", a
timeline for a routine, a comment card, a recap mosaic, a phone for "sa phone ko", a magazine
cover for a well-filled opening, a label under a floating picture) and the serif reveal captions.
The third acceptance transcript and made-up sentences: nothing is hardcoded."""

from collections import Counter

from autoedit import PROJECT_DIR, cues, director, editorial
from autoedit.captions import build_ass, fonts_from_config
from autoedit.config import DEFAULTS
from autoedit.project import media_from_file, validate_project
from autoedit.styles import get_style
from autoedit.words import load_transcript
from tests import synthetic
from tests.director_helpers import face_tracking, make_project, make_words
from tests.test_editorial_director import cfg, graphics_of, run, track

THIRD = "tests/data/acceptance/third_words.json"


def third_words():
    return [{"text": w.text, "start": w.start, "end": w.end} for w in load_transcript(THIRD)]


def words(text):
    return make_words(text.split())


def project_with(ws, tmp_path, names=("results.png", "profile_photo.png", "tiktok_logo.png")):
    p = make_project(ws, tracking=face_tracking(), caption_style="editorial_card")
    for i, name in enumerate(names):
        path = synthetic.make_image(tmp_path / name, color=["blue", "lime", "magenta"][i % 3], size="900x600")
        p["media"].append(media_from_file(path, f"up{i}"))
    return p


# ---------------------------------------------------------------- the cues

def test_the_third_script_cues():
    got = {c.kind: c for c in cues.extract(third_words())}
    assert got["keyword"].text == "CONSISTENCY"
    # a routine said as a list is a timeline, not a checklist
    assert got["timeline"].text == "routine" and [t for _k, t in got["timeline"].items] == ["gising", "kape", "edit", "post"]
    assert got["screenshot"].phone
    # the word to comment is the comment card's, not a title of its own
    assert got["comment"].text.startswith("Comment mo") and "GUIDE" not in [c.text for c in got.values() if c.kind == "keyword"]
    # a summing-up list is the recap's tiles, not another checklist
    assert [t for _k, t in got["recap"].items] == ["plano", "routine", "pahinga"] and "checklist" not in got


def test_other_routines_comments_and_recaps():
    found = cues.extract(words("Ganito ang schedule ko linggo-linggo : shoot , edit , upload . "
                               "I-DM mo ako kung may tanong ka . Sa madaling salita , mag-plano ka ."))
    kinds = {c.kind: c for c in found}
    assert [t for _k, t in kinds["timeline"].items] == ["shoot", "edit", "upload"]
    assert kinds["comment"].text.startswith("I-DM")
    assert kinds["recap"].text.startswith("Sa madaling salita")


def test_plain_talk_still_has_no_cues():
    assert cues.extract(words("Kumusta kayo , ang ganda ng araw ngayon at masaya ako .")) == []


# ---------------------------------------------------------------- the planner

def test_the_third_script_makes_each_look_on_its_words(tmp_path):
    ws = third_words()
    p = run(project_with(ws, tmp_path), cfg(handle="@akosicreator"))["project"]
    g = {c["template"]: c for c in graphics_of(p)}
    at = {strip(w["text"]): w["start"] for w in ws}
    fps = p["settings"]["fps"]

    strike = g["strike-text"]
    assert "puyat" in strike["params"]["text"] and "Dati" not in strike["params"]["text"]
    assert strike["params"]["text2"].startswith("tulog na ako")
    # the line strikes as the past ends; the new words land on "Ngayon"
    assert abs(strike["start"] + strike["params"]["cues"][1] - at["Ngayon"]) < 2 / fps
    bw = [c for c in track(p, "pe-transitions")["clips"] if c.get("effect") == "bw"]
    assert any(c["start"] <= at["Dati"] and c["start"] + c["duration"] >= at["Ngayon"] - 0.2 for c in bw)

    assert g["timeline-card"]["params"]["items"] == ["gising", "kape", "edit", "post"]
    assert g["chat-cards"]["params"]["text"] == "@akosicreator"
    assert g["chat-cards"]["params"]["items"][0].startswith("Comment mo ang salitang GUIDE")
    assert g["chat-cards"]["params"]["image"] == "up1"                   # profile_photo.png
    tiles = g["tile-mosaic"]["params"]["items"]
    # what the cards showed first (at once), then the items said here, each on its word
    assert tiles[-3:] == ["plano", "routine", "pahinga"] and "CONSISTENCY" in tiles[:-3]
    cues_at = g["tile-mosaic"]["params"]["cues"]
    assert cues_at[0] < 0.5 and abs(g["tile-mosaic"]["start"] + cues_at[-1] - at["pahinga"]) < 2 / fps
    assert g["phone-mockup"]["params"]["image"] == "up0"                 # results.png, in a phone
    # a well-filled opening is a magazine cover: the hook word as the masthead, never into a spoken card
    cover = g["magazine-cover"]
    assert abs(cover["start"] - director.snap(ws[0]["start"], fps)) < 1e-6           # on the hook's first word
    assert cover["params"]["text"] == "CONSISTENCY" and cover["params"]["text2"].startswith("Bago ka mag-post")
    later = [c for c in graphics_of(p) if c is not cover]
    assert all(c["start"] >= cover["start"] + cover["duration"] - 1e-6 for c in later)
    assert p["meta"]["editorial"]["scenes"][0]["beat"] == "magazine"
    assert validate_project(p) == []


def strip(t):
    return t.strip(".,!?:")


def test_a_counting_hook_names_the_cover():
    ws = words("Teka lang ! Tatlong sikreto ng viral na video . Una : DISIPLINA .")
    from autoedit.cues import Cue
    ctx = type("C", (), {"words": ws, "fps": 30, "duration": 30.0})()
    made = [Cue("keyword", 11, 11, text="DISIPLINA")] * editorial.MAGAZINE_MIN
    scenes = editorial.make_scenes(ws, 30.0)
    it, cue = editorial.magazine_cover(ctx, made, made, [{"start": 20.0}], ["DISIPLINA", "hook"], scenes)
    assert it["text"] == "SIKRETO"                                          # what "Tatlong" counts
    assert it["text2"] == "Tatlong sikreto ng viral na video" and it["list"] == ["DISIPLINA", "hook"]
    assert abs(it["start"] - director.snap(ws[3]["start"], 30)) < 1e-6 and cue.kind == "magazine"


def test_a_short_opening_is_not_a_cover(tmp_path):
    p = run(project_with(words("Tingnan ninyo ang results ko sa phone . Comment mo ang GUIDE ."), tmp_path),
            cfg())["project"]
    assert "magazine-cover" not in {c["template"] for c in graphics_of(p)}


def test_a_floating_picture_gets_a_label_of_its_words(tmp_path):
    ws = words("Ito ang sikreto ng premium na video . Ang ganda ng kulay ng setup ko dito sa bahay .")
    p = project_with(ws, tmp_path, names=("shot.png",))
    c = cfg()
    ctx = director.Ctx(p, c, editorial.STYLE, "")
    scenes = editorial.make_scenes(ctx.words, ctx.duration)
    assets = editorial.Assets(p, c)
    it, _effects, pips = editorial.element(ctx, scenes[1], "pip", assets, {}, Counter(), True)
    assert len(pips) == 1 and it["template"] == "label-pill"
    assert it["text"] and it["text"].lower() in " ".join(w["text"].lower() for w in ws)
    assert it["start"] >= pips[0]["start"]
    px, py = it["prefer"]
    box = editorial.PIP_BOX
    assert box["x"] / 1080 < px < (box["x"] + box["width"]) / 1080 and py * 1920 > box["y"] + box["height"]


# ---------------------------------------------------------------- the captions

def test_editorial_captions_are_a_serif_reveal_on_a_cream_card():
    style = get_style("editorial_card")
    assert style.family == "Playfair Display" and style.mode == "reveal"
    ws = load_transcript(THIRD)[:6]
    ass = build_ass(ws, style, fonts_from_config(DEFAULTS["captions"]),
                    fonts_folder=PROJECT_DIR / "assets" / "fonts")
    assert "Playfair Display" in ass
    assert r"\alpha&HA8&" in ass                       # the words not said yet are faint
    assert "mag-post" in ass and "mag-post," not in ass  # no end punctuation by default
