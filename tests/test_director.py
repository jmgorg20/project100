"""The Director: AI plan checks, retry and fallback, and the rules every plan goes through
(sync to words, density, variety, mood, face-safe, caption-safe, readable)."""

import json
import math

import pytest

from autoedit import director, graphics, zones
from autoedit.graphics_check import check_project, contrast
from autoedit.llm import LLMError
from autoedit.project import validate_project
from tests.director_helpers import cfg, face_tracking, make_project, make_words

CAT = graphics.catalog()


def clips_of(project):
    return sorted(director.graphic_clips_of(project), key=lambda c: c["start"])


def word_at(project, text):
    return next(w for w in director.timeline_words(project) if director.norm(w["text"]) == director.norm(text))


def fake_llm(answers):
    """ask_json stand-in: returns the answers in order (dicts become JSON; exceptions are raised)."""
    calls = []

    def ask(provider, model, system, prompt, schema, max_tokens=8000, effort="medium", **kw):
        calls.append({"prompt": prompt, "schema": schema})
        a = answers[min(len(calls) - 1, len(answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return (a if isinstance(a, str) else json.dumps(a)), {"input_tokens": 100, "output_tokens": 50}, model
    return ask, calls


def item(template, words, start, **kw):
    return {"template": template, "words": words, "start": start, **kw}


@pytest.fixture
def project():
    return make_project(tracking=face_tracking())


def good_plan(project):
    s = lambda t: word_at(project, t)["start"]  # noqa: E731
    return {"summary": "ok", "items": [
        item("pop-heavy", "Grabe ang bilis", s("Grabe"), text="*GRABE* ang bilis", mood="hype", importance=0.9,
             emphasis="flash"),
        item("counter-number", "500 pesos", s("500"), number=500, prefix="₱", text="simula", mood="money",
             importance=0.95),
        item("warning-banner", "Mag-ingat sa mga scam", s("Mag-ingat"), text="Mag-ingat sa scam", mood="warning",
             importance=0.8),
        item("prompt-card", "gamitin ang AI para sa edit", s("gamitin"), text="gamitin ang AI para sa edit",
             mood="tech", importance=0.7),
        item("comment-pill", "Comment mo ang salitang EDIT", s("Comment"), text="EDIT", text2="Comment",
             mood="playful", importance=0.85),
    ], "notes": []}


# ---------------------------------------------------------------- styles

@pytest.mark.parametrize("instruction, explicit, expected", [
    ("Edit this like a professional promoter", None, "promoter"),
    ("gawin mong parang documentary, kalmado", None, "calm_documentary"),
    ("make it a funny meme", None, "meme"),
    ("lagyan ng graphics", None, "promoter"),
    ("fast cuts lang", None, None),
    ("anything", "luxury", "luxury"),
    ("promoter please", "off", None),
])
def test_style_comes_from_the_choice_or_the_instruction(instruction, explicit, expected):
    assert director.resolve_style(cfg(), instruction, explicit) == expected


def test_unknown_style_is_a_clear_error():
    with pytest.raises(director.DirectorError, match="Unknown graphics style"):
        director.resolve_style(cfg(), "", "sparkly")


# ---------------------------------------------------------------- plan checks, retry, fallback

def test_a_good_ai_plan_is_used(project, monkeypatch):
    ask, calls = fake_llm([good_plan(project)])
    monkeypatch.setattr(director, "ask_json", ask)
    r = director.generate(project, cfg(), "promoter", "promoter", provider="groq", model="m")
    assert len(calls) == 1 and not r["fallback"] and r["count"] >= 4
    templates = {c["template"] for c in clips_of(r["project"])}
    assert {"counter-number", "comment-pill"} <= templates
    assert validate_project(r["project"]) == []
    # the prompt lists templates and the transcript, the schema lists only real templates
    assert "pop-heavy" in calls[0]["prompt"] and "Grabe" in calls[0]["prompt"]
    assert set(calls[0]["schema"]["properties"]["items"]["items"]["properties"]["template"]["enum"]) == \
        set(graphics.template_ids())


def test_a_bad_plan_is_retried_once_with_its_problems(project, monkeypatch):
    bad = {"items": [item("pop-heavy", "words nobody said", 3.0, text="x")]}
    ask, calls = fake_llm([bad, good_plan(project)])
    monkeypatch.setattr(director, "ask_json", ask)
    r = director.generate(project, cfg(), "promoter", "promoter", provider="groq", model="m")
    assert len(calls) == 2 and not r["fallback"]
    assert "not spoken" in calls[1]["prompt"] and r["attempts"][0]["attempt"] == 1


@pytest.mark.parametrize("answers", [
    ["not json", "{also not json"],
    [{"items": [{"template": "no-such-template", "words": "Grabe", "start": 0.4}]}] * 2,
    [{"items": [item("counter-number", "Grabe", 0.4)]}] * 2,        # a counter without a number
    [LLMError("no key")],
])
def test_after_two_failures_the_safe_preset_is_used(project, monkeypatch, answers):
    ask, calls = fake_llm(answers)
    monkeypatch.setattr(director, "ask_json", ask)
    r = director.generate(project, cfg(), "promoter", "promoter", provider="groq", model="m")
    assert r["fallback"] and r["reason"] and r["count"] > 0
    assert len(calls) <= 2
    assert validate_project(r["project"]) == []


def test_plans_are_cached(project, monkeypatch, tmp_path):
    from autoedit.cache import Cache
    cache = Cache(tmp_path / "cache")
    ask, calls = fake_llm([good_plan(project)])
    monkeypatch.setattr(director, "ask_json", ask)
    a = director.generate(project, cfg(), "promoter", "promoter", "groq", "m", cache=cache)
    b = director.generate(project, cfg(), "promoter", "promoter", "groq", "m", cache=cache)
    assert len(calls) == 1 and b["cached"]
    assert clips_of(a["project"]) == clips_of(b["project"])


def test_no_words_no_graphics():
    p = make_project()
    p["tracks"][3]["clips"] = []
    r = director.generate(p, cfg(), "promoter", "promoter", use_ai=False)
    assert r["count"] == 0


# ---------------------------------------------------------------- the rules

def all_results(project, monkeypatch):
    """The same video planned by the AI (fake) and by the fallback, in every pop-up style (the
    editorial style plans scene by scene with its own rules: tests/test_editorial_director.py)."""
    out = []
    for style in [s for s in director.STYLES if not director.STYLES[s].get("planner")]:
        out.append(director.generate(project, cfg(), "", style, use_ai=False))
        ask, _ = fake_llm([good_plan(project)])
        monkeypatch.setattr(director, "ask_json", ask)
        out.append(director.generate(project, cfg(), "", style, provider="groq", model="m"))
    return out


def test_graphics_start_on_the_frame_of_their_word(project, monkeypatch):
    plan = good_plan(project)
    for it in plan["items"]:
        it["start"] += 0.37                   # the AI's times are a little off
    ask, _ = fake_llm([plan])
    monkeypatch.setattr(director, "ask_json", ask)
    r = director.generate(project, cfg(), "", "promoter", provider="groq", model="m")
    fps = project["settings"]["fps"]
    words = director.timeline_words(project)
    for c in clips_of(r["project"]):
        first = director.norm(c["director"]["words"].split()[0])
        starts = [w["start"] for w in words if director.norm(w["text"]) == first]
        assert min(abs(c["start"] - s) for s in starts) <= 1 / fps + 1e-6, c
        # on the frame grid (times are kept to 0.1 ms)
        assert abs(c["start"] * fps - round(c["start"] * fps)) < 0.01
        assert abs((c["start"] + c["duration"]) * fps - round((c["start"] + c["duration"]) * fps)) < 0.01


def test_density_never_exceeds_the_style_limit(project, monkeypatch):
    words = director.timeline_words(project)
    flood = {"items": [item("pop-heavy", w["text"].strip(".,"), w["start"], text=w["text"].strip(".,"), importance=0.5)
                       for w in words if director.important(w["text"])]}
    ask, _ = fake_llm([flood])
    monkeypatch.setattr(director, "ask_json", ask)
    for style, spec in director.STYLES.items():
        r = director.generate(project, cfg(), "", style, provider="groq", model="m")
        starts = [c["start"] for c in clips_of(r["project"])]
        for a in starts:
            assert sum(1 for s in starts if a <= s < a + 10) <= spec["max_per_10s"], style
        main = [c for c in clips_of(r["project"]) if c["director"]["kind"] not in director.COMPANION]
        for x, y in zip(main, main[1:]):
            assert y["start"] - x["start"] >= spec["min_gap"] - 1e-6
            assert x["start"] + x["duration"] <= y["start"] + 1e-6          # main graphics never overlap


def test_never_the_same_template_twice_in_a_row(project, monkeypatch):
    words = director.timeline_words(project)
    same = {"items": [item("pop-heavy", w["text"].strip(".,"), w["start"], text=w["text"].strip(".,"))
                      for w in words if director.important(w["text"])]}
    ask, _ = fake_llm([same])
    monkeypatch.setattr(director, "ask_json", ask)
    popup = [s for s in director.STYLES if not director.STYLES[s].get("planner")]   # one tile per platform is fine
    for r in [director.generate(project, cfg(), "", s, provider="groq", model="m") for s in popup] + \
            all_results(project, monkeypatch):
        seq = [c["template"] for c in clips_of(r["project"])]
        assert all(a != b for a, b in zip(seq, seq[1:])), seq


def test_mood_and_style_are_respected(project, monkeypatch):
    for r in all_results(project, monkeypatch):
        style = director.STYLES[r["style"]]
        for c in clips_of(r["project"]):
            meta = graphics.template_meta(c["template"])
            assert c["template"] not in style["deny"]
            assert style["categories"].get(meta["category"], 0.5) > 0
            assert c["director"]["mood"] in meta["moods"] or meta["category"] in director.COMPANION, c


def face_box_at(fmap, t):
    return fmap.rect_at_frame(round(t * 30))


@pytest.mark.parametrize("moves", [
    None,                                                   # a still speaker
    lambda t: (0.3 + 0.4 * (0.5 + 0.5 * math.sin(t / 3)), 0.32),   # walking left and right
    lambda t: (0.5, 0.25 + 0.3 * (t % 8) / 8),              # moving down the frame
])
def test_graphics_never_cover_the_face(monkeypatch, moves):
    project = make_project(tracking=face_tracking(moves=moves))
    fmap = zones.FaceMap(project)
    assert fmap.known
    for r in all_results(project, monkeypatch):
        for c in clips_of(r["project"]):
            meta = graphics.template_meta(c["template"])
            box = director.est_box(meta, c["params"].get("text", ""), c["params"].get("size", 1),
                                   c["x"], c["y"], c["params"].get("angle", 0))
            t = c["start"]
            while t < c["start"] + c["duration"]:
                face = face_box_at(fmap, t)
                assert face is None or not zones.intersects(box, face), (r["style"], c["template"], t)
                t += 1 / 30


def test_without_tracking_the_usual_face_area_is_kept_clear(monkeypatch):
    project = make_project()
    for r in all_results(project, monkeypatch):
        assert any("not tracked" in n for n in r["notes"])
        for c in clips_of(r["project"]):
            meta = graphics.template_meta(c["template"])
            box = director.est_box(meta, c["params"].get("text", ""), c["params"].get("size", 1), c["x"], c["y"],
                                   c["params"].get("angle", 0))
            assert not zones.intersects(box, zones.DEFAULT_FACE)


@pytest.mark.parametrize("zone", [None, "center", "top"])
def test_graphics_never_sit_on_the_captions(monkeypatch, zone):
    project = make_project(tracking=face_tracking(), zone=zone)
    for r in all_results(project, monkeypatch):
        for c in clips_of(r["project"]):
            meta = graphics.template_meta(c["template"])
            box = director.est_box(meta, c["params"].get("text", ""), c["params"].get("size", 1), c["x"], c["y"],
                                   c["params"].get("angle", 0))
            for cap in zones.caption_rects(project, c["start"], c["start"] + c["duration"]):
                assert not zones.intersects(box, cap), (zone, c["template"])
            assert zones.inside(box, (0, 0, 1080, 1920))


def test_text_is_short_large_enough_and_has_contrast(project, monkeypatch):
    for r in all_results(project, monkeypatch):
        for c in clips_of(r["project"]):
            meta = graphics.template_meta(c["template"])
            p = c["params"]
            assert len(p.get("text", "").replace("*", "")) <= meta["maxChars"]
            assert p.get("size", 1) >= director.MIN_SIZE - 1e-9
            colors = {"color": "#ffffff", "bg": "#111827", **meta["defaults"], **p}
            if meta["bg"]:
                assert contrast(colors["color"], colors["bg"]) >= 4.5, c
            else:
                assert contrast(colors["color"], "#000000") >= 4.5, c


def test_every_result_is_a_valid_project_without_check_warnings(project, monkeypatch):
    for r in all_results(project, monkeypatch):
        assert validate_project(r["project"]) == []
        kinds = {i["kind"] for i in check_project(r["project"])}
        assert not kinds & {"face", "caption", "off-screen", "safe-area"}, kinds


def test_emphasis_transitions_are_spaced_and_follow_the_style(project, monkeypatch):
    for r in all_results(project, monkeypatch):
        style = director.STYLES[r["style"]]
        att = [c for c in clips_of(r["project"]) if c.get("attach")]
        assert all(c["attach"]["kind"] in style["attach"] for c in att)
        for a, b in zip(att, att[1:]):
            assert b["start"] - a["start"] >= style["attach_gap"] - 1e-6
            assert a["attach"]["kind"] != b["attach"]["kind"]


def test_taglish_words_and_corrections_come_from_the_captions(monkeypatch):
    words = make_words("Ang GCash ko may ₱1,500 na ngayon . Salamat sa inyong suporta mga kababayan .".split())
    project = make_project(words=words, tracking=face_tracking())
    r = director.generate(project, cfg(), "", "promoter", use_ai=False)
    counters = [c for c in clips_of(r["project"]) if c["template"] in ("counter-number", "price-tag")]
    assert counters and counters[0]["params"]["number"] == 1500 and counters[0]["params"]["prefix"] == "₱"


# ---------------------------------------------------------------- locks and one-item regenerate

def test_locked_and_own_graphics_stay_and_are_avoided(project):
    first = director.generate(project, cfg(), "", "promoter", use_ai=False)["project"]
    clips = clips_of(first)
    clips[0]["locked"] = True
    mine = {"id": "mine", "type": "graphic", "template": "sticker-label", "start": 30.0, "duration": 2,
            "x": 0.5, "y": 0.12, "params": {"text": "New!"}}
    next(t for t in first["tracks"] if t["kind"] == "graphics")["clips"].append(mine)
    again = director.generate(first, cfg(), "", "meme", use_ai=False)["project"]
    ids = {c["id"] for c in clips_of(again)}
    assert clips[0]["id"] in ids and "mine" in ids
    kept = next(c for c in clips_of(again) if c["id"] == clips[0]["id"])
    assert kept == clips[0]
    assert validate_project(again) == []


def test_regenerate_one_item_changes_only_that_one(project):
    p = director.generate(project, cfg(), "", "promoter", use_ai=False)["project"]
    before = clips_of(p)
    target = before[1]
    r = director.regenerate_item(p, target["id"], cfg())
    after = clips_of(r["project"])
    assert r["clip"]["template"] != target["template"]
    assert [c for c in after if c["id"] != target["id"]] == [c for c in before if c["id"] != target["id"]]
    seq = [c["template"] for c in after]
    assert all(a != b for a, b in zip(seq, seq[1:]))
    assert abs(r["clip"]["start"] - target["start"]) < 1e-6
    assert validate_project(r["project"]) == []


def test_a_locked_graphic_cannot_be_regenerated(project):
    p = director.generate(project, cfg(), "", "promoter", use_ai=False)["project"]
    c = clips_of(p)[0]
    c["locked"] = True
    with pytest.raises(director.DirectorError, match="locked"):
        director.regenerate_item(p, c["id"], cfg())


def test_before_after_wipe_when_asked(project):
    r = director.generate(project, cfg(), "promoter with a before/after wipe", "promoter", use_ai=False)
    wipes = [c for t in r["project"]["tracks"] for c in t["clips"] if c["type"] == "wipe"]
    assert len(wipes) == 1 and validate_project(r["project"]) == []
    r2 = director.generate(project, cfg(), "before/after", "minimal", use_ai=False)
    assert not [c for t in r2["project"]["tracks"] for c in t["clips"] if c["type"] == "wipe"]


# ---------------------------------------------------------------- the export check

def test_export_check_flags_face_offscreen_captions_and_text(project):
    g = lambda cid, tpl, x, y, **p: {"id": cid, "type": "graphic", "template": tpl, "start": 1.0,  # noqa: E731
                                     "duration": 2.0, "x": x, "y": y, "params": p}
    project["tracks"].append({"id": "graphics", "kind": "graphics", "clips": [
        g("face", "stamp", 0.5, 0.3, text="Hi"),
    ]})
    project["tracks"].append({"id": "graphics-2", "kind": "graphics", "clips": [
        g("off", "news-banner", 0.95, 0.5, text="Off the edge")]})
    project["tracks"].append({"id": "graphics-3", "kind": "graphics", "clips": [
        g("cap", "lower-third-pill", 0.5, 0.7, text="On the captions", color="#777777", bg="#888888")]})
    project["tracks"].append({"id": "graphics-4", "kind": "graphics", "clips": [
        g("long", "stamp", 0.5, 0.1, text="x" * 60)]})
    assert validate_project(project) == []
    kinds = {(i["clip"], i["kind"]) for i in check_project(project)}
    assert ("face", "face") in kinds and ("off", "off-screen") in kinds
    assert ("cap", "caption") in kinds and ("cap", "contrast") in kinds
    assert ("long", "text-long") in kinds
    assert all(i["tl"] for i in check_project(project))
