"""The AI edit: plan checks, providers (no network: requests and the SDK are faked),
retry and preset fallback, caching, cost, and the whole flow with FFmpeg."""

import copy
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from autoedit import PROJECT_DIR, ai_edit, llm
from autoedit.ai_plan import apply_plan, load_plan_schema, preset_plan, validate_plan
from autoedit.cache import Cache
from autoedit.config import load_config
from autoedit.costs import format_usd, plan_cost, total, transcription_cost
from autoedit.errors import EditorError
from autoedit.project import load_project
from autoedit.words import load_transcript, save_transcript
from tests import synthetic


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg["output"]["folder"] = str(tmp_path / "out")
    cfg["work_folder"] = str(tmp_path / "work")
    cfg["ai"]["cache_folder"] = str(tmp_path / "cache")
    cfg["output"]["encoder_speed"] = "ultrafast"
    cfg["overlays"]["triggers_file"] = str(tmp_path / "none.yaml")
    return cfg


def good_plan(cfg, **changes):
    plan = preset_plan(cfg)
    plan.update(changes)
    return plan


# ------------------------------------------------------------ plan checks

def test_preset_plan_is_valid(cfg):
    assert validate_plan(preset_plan(cfg), 10.0) == []


@pytest.mark.parametrize("change, message", [
    (lambda p: p.update(style="comic"), "plan.style"),
    (lambda p: p.update(extra=1), "Additional properties"),
    (lambda p: p.pop("notes"), "'notes' is a required property"),
    (lambda p: p["pacing"].update(silence_threshold=5), "silence_threshold"),
    (lambda p: p["captions"].update(size_scale=3), "size_scale"),
    (lambda p: p.update(cuts=[{"start": 3, "end": 2, "reason": ""}]), "must be after start"),
    (lambda p: p.update(zooms=[{"start": 30, "end": 31, "amount": 1.3}]), "only 10.00s long"),
    (lambda p: p.update(cuts=[{"start": 0, "end": 9.5, "reason": "all"}]), "almost the whole"),
    (lambda p: p.update(photos=[{"file": "x.png", "at": 1, "duration": 2, "position": "top",
                                 "reason": ""}]), "unknown photo 'x.png'"),
    (lambda p: p.update(photos=[{"file": "a.png", "at": 11, "duration": 2, "position": "top",
                                 "reason": ""}]), "after the end"),
])
def test_bad_plans_are_caught(cfg, change, message):
    plan = preset_plan(cfg)
    change(plan)
    problems = validate_plan(plan, 10.0, ["a.png"])
    assert any(message in p for p in problems), problems
    assert validate_plan("not a dict", 10.0) == ["the answer is not a JSON object"]


def test_apply_plan_makes_settings_without_touching_the_original(cfg, tmp_path):
    before = copy.deepcopy(cfg)
    plan = good_plan(cfg, style="bold_caps", grade="warm",
                     photos=[{"file": "a.png", "at": 2, "duration": 3, "position": "center",
                              "reason": "r"}],
                     cuts=[{"start": 1, "end": 2, "reason": "retake"}])
    plan["captions"].update(size_scale=1.5, position="top", highlight_words=["GCash", " "])
    plan["pacing"]["silence_threshold"] = 0.4
    new, pipeline_plan = apply_plan(cfg, plan, {"a.png": tmp_path / "a.png"})
    assert cfg == before
    assert new["style"] == "bold_caps" and new["grade"] == "warm"
    assert new["pacing"]["silence_threshold"] == 0.4
    assert new["highlight"]["extra_keywords"] == ["GCash"]
    assert pipeline_plan["caption_overrides"] == {"size": 123, "zone": "top"}  # 82 * 1.5
    assert pipeline_plan["overlays"][0]["file"] == tmp_path / "a.png"
    assert pipeline_plan["cuts"] == [{"start": 1, "end": 2}]


def walk_objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from walk_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from walk_objects(value)


def test_plan_schema_fits_structured_outputs():
    """Anthropic structured outputs need closed objects with every property required."""
    strict = llm.strict_schema(load_plan_schema())
    text = json.dumps(strict)
    for word in ("minimum", "maximum", "maxLength", "maxItems", "$schema"):
        assert f'"{word}"' not in text
    assert '"enum"' in text
    for obj in walk_objects(strict):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


# ------------------------------------------------------------ providers (no network)

class FakeResponse:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data


def test_groq_request(monkeypatch, capsys):
    import requests
    secret = "gsk_secret_value_123"
    monkeypatch.setenv("GROQ_API_KEY", secret)
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return FakeResponse(200, {"model": "m", "choices": [{"message": {"content": "{}"}}],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 3}})

    monkeypatch.setattr(requests, "post", fake_post)
    text, usage, model = llm.ask_json("groq", "openai/gpt-oss-120b", "SYS", "PROMPT",
                                      load_plan_schema())
    assert (text, usage) == ("{}", {"input_tokens": 10, "output_tokens": 3})
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["headers"] == {"Authorization": f"Bearer {secret}"}
    body = seen["body"]
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system" and "JSON Schema" in body["messages"][0]["content"]
    assert body["messages"][1] == {"role": "user", "content": "PROMPT"}
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize("status, message", [(401, "rejected the API key"),
                                             (404, "does not know the model"),
                                             (429, "usage limit"), (500, r"failed \(500\)")])
def test_groq_errors_are_clear(monkeypatch, status, message):
    import requests
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(status, text="err"))
    with pytest.raises(llm.LLMError, match=message):
        llm.ask_json("groq", "m", "s", "p", {})


def test_missing_key_is_clear(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm, "load_dotenv", lambda path=None: None)
    with pytest.raises(llm.LLMError, match="No Anthropic API key"):
        llm.ask_json("anthropic", "claude-opus-5-5", "s", "p", {})


def fake_anthropic(monkeypatch, stop_reason="end_turn", text='{"ok": true}', error=None):
    """Replace anthropic.Anthropic with a fake that records the request."""
    import anthropic
    seen = {}

    class Messages:
        def create(self, **kwargs):
            seen.update(kwargs)
            if error:
                raise error
            return types.SimpleNamespace(
                stop_reason=stop_reason, model=kwargs["model"],
                content=[types.SimpleNamespace(type="text", text=text)],
                usage=types.SimpleNamespace(input_tokens=1200, output_tokens=300))

    class Client:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.beta = types.SimpleNamespace(messages=Messages())

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    return seen


def test_anthropic_request(monkeypatch):
    seen = fake_anthropic(monkeypatch)
    text, usage, model = llm.ask_json("anthropic", "claude-opus-5-5", "SYS", "PROMPT",
                                      load_plan_schema(), effort="medium")
    assert text == '{"ok": true}' and usage == {"input_tokens": 1200, "output_tokens": 300}
    assert seen["client"]["api_key"] == "sk-ant-test"
    assert seen["model"] == "claude-opus-5-5" and seen["system"] == "SYS"
    assert seen["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert seen["output_config"]["effort"] == "medium"
    fmt = seen["output_config"]["format"]
    assert fmt["type"] == "json_schema" and '"minimum"' not in json.dumps(fmt["schema"])
    assert seen["betas"] == ["server-side-fallback-2026-07-01"]
    assert seen["fallbacks"] == "default"


def test_anthropic_refusal_and_cut_off_answers(monkeypatch):
    fake_anthropic(monkeypatch, stop_reason="refusal")
    with pytest.raises(llm.LLMError, match="declined"):
        llm.ask_json("anthropic", "claude-opus-5-5", "s", "p", {})
    fake_anthropic(monkeypatch, stop_reason="max_tokens", text='{"cut')
    assert llm.ask_json("anthropic", "claude-opus-5-5", "s", "p", {})[0] == ""


def test_anthropic_errors_are_clear(monkeypatch):
    import anthropic
    import httpx2
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=request),
                                          body=None)
    fake_anthropic(monkeypatch, error=error)
    with pytest.raises(llm.LLMError, match="rejected the API key"):
        llm.ask_json("anthropic", "claude-opus-5-5", "s", "p", {})


# ------------------------------------------------------------ retry, fallback, cache

def scripted(answers):
    """A fake ask_json that returns the given answers in order and records the prompts."""
    calls = []

    def fake(provider, model, system, prompt, schema, **kw):
        calls.append(prompt)
        answer = answers[min(len(calls) - 1, len(answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return text, {"input_tokens": 1000, "output_tokens": 200}, model
    return fake, calls


def ask(cfg, monkeypatch, answers, tmp_path, check=None, words=None):
    fake, calls = scripted(answers)
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    words = words or load_transcript(synthetic.make_transcript(tmp_path / "t.json"))
    result = ai_edit.request_plan(cfg, "groq", "openai/gpt-oss-120b", "make it fast", words,
                                  8.0, ["a.png"], Cache(tmp_path / "cache"), check=check)
    return result, calls


def test_good_plan_first_time(cfg, monkeypatch, tmp_path):
    plan = good_plan(cfg, style="one_word")
    result, calls = ask(cfg, monkeypatch, [plan], tmp_path)
    assert result.plan == plan and not result.fallback and len(calls) == 1
    assert "INSTRUCTION FROM THE CREATOR:\nmake it fast" in calls[0]
    assert "0.50 Kumusta" in calls[0] and "PHOTOS (file names you may use): a.png" in calls[0]
    assert result.cost == pytest.approx((1000 * 0.15 + 200 * 0.75) / 1e6)


def test_one_retry_with_the_problems_listed(cfg, monkeypatch, tmp_path):
    bad = good_plan(cfg, style="comic")
    result, calls = ask(cfg, monkeypatch, [bad, good_plan(cfg)], tmp_path)
    assert not result.fallback and len(calls) == 2
    assert "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS" in calls[1] and "plan.style" in calls[1]
    assert result.usage == {"input_tokens": 2000, "output_tokens": 400}


def test_two_bad_plans_fall_back_to_the_preset(cfg, monkeypatch, tmp_path):
    result, calls = ask(cfg, monkeypatch, ["not json at all", good_plan(cfg, style="x")],
                        tmp_path)
    assert result.fallback and len(calls) == 2
    assert result.plan == preset_plan(cfg)
    assert "failed the checks twice" in result.reason and "not valid JSON" in result.reason
    assert [a["attempt"] for a in result.attempts] == [1, 2]


def test_provider_error_falls_back_and_says_why(cfg, monkeypatch, tmp_path):
    result, calls = ask(cfg, monkeypatch, [llm.LLMError("Groq rejected the API key (401).")],
                        tmp_path)
    assert result.fallback and len(calls) == 1
    assert "rejected the API key" in result.reason and "preset edit" in result.reason


def test_project_check_problems_trigger_the_retry(cfg, monkeypatch, tmp_path):
    seen = []

    def check(plan):
        seen.append(plan["style"])
        return ["the edit could not be built"] if plan["style"] == "classic" else []

    result, calls = ask(cfg, monkeypatch, [good_plan(cfg, style="classic"),
                                           good_plan(cfg, style="boxed")], tmp_path, check)
    assert seen == ["classic", "boxed"] and result.plan["style"] == "boxed"
    assert "could not be built" in calls[1]


def test_plans_are_cached(cfg, monkeypatch, tmp_path):
    plan = good_plan(cfg, style="minimal")
    first, calls = ask(cfg, monkeypatch, [plan], tmp_path)
    second, calls2 = ask(cfg, monkeypatch, [good_plan(cfg, style="classic")], tmp_path)
    assert second.cached and second.plan == plan and calls2 == [] and second.cost == 0.0
    # A different instruction is a different plan.
    fake, calls3 = scripted([good_plan(cfg)])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    words = load_transcript(tmp_path / "t.json")
    ai_edit.request_plan(cfg, "groq", "openai/gpt-oss-120b", "make it slow", words, 8.0,
                         ["a.png"], Cache(tmp_path / "cache"))
    assert len(calls3) == 1


# ------------------------------------------------------------ cost

def test_cost_maths():
    prices = load_config()["ai"]["prices"]
    assert transcription_cost(prices, "whisper-large-v3", 3600) == pytest.approx(0.111)
    assert transcription_cost(prices, "whisper-large-v3", 2) == pytest.approx(0.111 * 10 / 3600)
    assert plan_cost(prices, "claude-opus-5-5", 10000, 1000) == pytest.approx(0.06)
    assert plan_cost(prices, "unknown-model", 10, 10) is None
    assert total(None, None) is None and total(0.01, None) == 0.01
    assert format_usd(None).startswith("unknown") and format_usd(0.0016) == "$0.0016"
    assert format_usd(0.123) == "$0.12" and format_usd(0) == "$0"


# ------------------------------------------------------------ the whole AI edit (FFmpeg)

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
def talk(tmp_path, cfg, monkeypatch):
    """Synthetic talking video, a photo, and a fake Whisper (counts its calls)."""
    video = synthetic.make_video(tmp_path / "talk.mp4")
    transcript = synthetic.make_transcript(tmp_path / "talk.json")
    photo = synthetic.make_image(tmp_path / "github_logo.png")
    calls = []

    def fake_transcribe(video_path, cfg_, job_dir):
        calls.append(video_path)
        return load_transcript(transcript)

    monkeypatch.setattr(ai_edit, "transcribe", fake_transcribe)
    return tmp_path, video, photo, calls


def photo_plan(cfg):
    plan = good_plan(cfg, style="bold_caps", summary="Mabilis na edit.",
                     notes=["No music file was given."])
    plan["captions"]["size_scale"] = 1.3
    plan["photos"] = [{"file": "github_logo.png", "at": 5.5, "duration": 1.5,
                       "position": "top", "reason": "when you say GitHub"}]
    return plan


def test_ai_edit_end_to_end(talk, cfg, monkeypatch):
    tmp, video, photo, whisper = talk
    fake, calls = scripted([photo_plan(cfg)])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    rec = Recorder()
    result = ai_edit.ai_edit_video(video, cfg, "fast, show the logo", [photo], reporter=rec)

    assert rec.stages == ["transcript", "plan", "cuts", "zooms", "captions", "photos", "render"]
    kinds = [k for k, _ in rec.events]
    assert kinds == ["transcript", "plan", "project", "project", "project", "project", "summary"]
    staged = [d["project"] for k, d in rec.events if k == "project"]
    assert all(not t["clips"] for t in staged[0]["tracks"] if t["kind"] != "video")
    assert any(t["clips"] for t in staged[3]["tracks"] if t["kind"] == "overlay")

    assert Path(result["output"]).exists() and not result["fallback"]
    project = load_project(result["project"])
    photos = [c for t in project["tracks"] if t["kind"] == "overlay" for c in t["clips"]]
    assert len(photos) == 1 and photos[0]["start"] == pytest.approx(3.5)
    captions = [c for t in project["tracks"] if t["kind"] == "caption" for c in t["clips"]]
    assert captions[0]["overrides"]["size"] == 107
    summary = result["summary"]
    assert summary["headline"] == "Mabilis na edit."
    assert any("github_logo.png" in d for d in summary["details"])
    assert any("Not done: No music" in d for d in summary["details"])
    saved = json.loads(Path(result["plan"]).read_text(encoding="utf-8"))
    assert saved["plan"] == photo_plan(cfg) and saved["instruction"] == "fast, show the logo"
    assert not (tmp / "work").exists() or not any((tmp / "work").iterdir())


def test_auto_off_then_accepted_plan_and_cached_transcript(talk, cfg, monkeypatch):
    tmp, video, photo, whisper = talk
    fake, calls = scripted([photo_plan(cfg)])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    review = ai_edit.ai_edit_video(video, cfg, "x", [photo], render=False,
                                   output=tmp / "out" / "v1.mp4", reporter=Recorder())
    assert review["output"] is None and Path(review["project"]).exists()
    assert not (tmp / "out" / "v1.mp4").exists()
    # The creator rejects the photo and applies the rest: no AI call, no transcription.
    accepted = photo_plan(cfg)
    accepted["photos"] = []
    final = ai_edit.ai_edit_video(video, cfg, "x", [photo], plan=accepted,
                                  output=tmp / "out" / "v2.mp4", reporter=Recorder())
    assert len(calls) == 1 and len(whisper) == 1           # transcript came from the cache
    assert Path(final["output"]).exists()
    project = load_project(final["project"])
    assert not [c for t in project["tracks"] if t["kind"] == "overlay" for c in t["clips"]]
    assert any("Photos not used: github_logo.png" in d for d in final["summary"]["details"])


def test_follow_up_sends_the_current_plan(talk, cfg, monkeypatch):
    tmp, video, photo, _ = talk
    current = photo_plan(cfg)
    bigger = copy.deepcopy(current)
    bigger["captions"]["size_scale"] = 1.6
    fake, calls = scripted([bigger])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    result = ai_edit.ai_edit_video(video, cfg, "mas malaki pa ang captions", [photo],
                                   previous_plan=current, render=False, reporter=Recorder())
    assert "CURRENT PLAN" in calls[0] and "CHANGE REQUEST FROM THE CREATOR:\nmas malaki" in calls[0]
    assert "60% bigger" in " ".join(result["summary"]["details"])


def test_plan_that_breaks_the_edit_falls_back_to_the_preset(talk, cfg, monkeypatch):
    tmp, video, photo, _ = talk
    # Passes the plan checks (1.1 s left) but the pause cutting then leaves almost nothing.
    greedy = good_plan(cfg, cuts=[{"start": 0.0, "end": 6.9, "reason": "?"}])
    fake, calls = scripted([greedy])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    rec = Recorder()
    result = ai_edit.ai_edit_video(video, cfg, "x", [], render=False, reporter=rec)
    assert len(calls) == 2 and result["fallback"]
    assert "could not be built" in result["reason"]
    plan_event = dict(rec.events)["plan"]
    assert plan_event["fallback"] and plan_event["plan"] == preset_plan(cfg)
    assert plan_event["baseline"] == preset_plan(cfg)
    assert result["summary"]["headline"].startswith("Heads up:")


def test_given_plan_with_problems_is_refused(talk, cfg):
    tmp, video, photo, _ = talk
    with pytest.raises(EditorError, match="unknown photo"):
        ai_edit.ai_edit_video(video, cfg, "", [], plan=photo_plan(cfg), render=False,
                              reporter=Recorder())


# ------------------------------------------------------------ command line (as the app uses it)

def cli(args, cwd):
    return subprocess.run([sys.executable, str(PROJECT_DIR / "editor.py"), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=600)


def seed_transcript(cfg_file_dir, video, transcript):
    """Put the transcript in the cache so the CLI does not call Whisper."""
    cache = Cache(cfg_file_dir / "cache")
    key = f"{cache.fingerprint(video)}-groq-whisper-large-v3-tl"
    path = cache.folder / "transcripts" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    save_transcript(load_transcript(transcript), path)


def write_cfg(tmp):
    path = tmp / "cfg.yaml"
    path.write_text(f"output: {{folder: '{(tmp / 'out').as_posix()}', encoder_speed: ultrafast}}\n"
                    f"work_folder: '{(tmp / 'work').as_posix()}'\n"
                    f"ai: {{cache_folder: '{(tmp / 'cache').as_posix()}'}}\n"
                    f"overlays: {{triggers_file: '{(tmp / 'none.yaml').as_posix()}'}}\n",
                    encoding="utf-8")
    return path


def test_cli_ai_edit_batch_with_a_plan_file(tmp_path, cfg):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    other = synthetic.make_video(tmp_path / "talk2.mp4")
    transcript = synthetic.make_transcript(tmp_path / "talk.json")
    photo = synthetic.make_image(tmp_path / "github_logo.png")
    seed_transcript(tmp_path, video, transcript)
    seed_transcript(tmp_path, other, transcript)
    plan_file = tmp_path / "accepted.plan.json"
    plan_file.write_text(json.dumps({"plan": photo_plan(cfg)}), encoding="utf-8")
    broken = tmp_path / "broken.mp4"
    broken.write_text("not a video")
    run = cli(["--config", str(write_cfg(tmp_path)), "--json", "ai-edit", str(video),
               str(broken), str(other), "--photos", str(photo), "--plan-file", str(plan_file)],
              tmp_path)
    assert run.returncode == 1, run.stderr               # one of three failed
    events = [json.loads(line) for line in run.stdout.splitlines()]
    kinds = [e["type"] for e in events]
    assert kinds.count("item") == 3 and kinds.count("item_error") == 1
    assert kinds.count("summary") == 2 and "cancelled" not in kinds
    result = next(e for e in events if e["type"] == "result")
    assert [i["ok"] for i in result["items"]] == [True, False, True]
    assert all(Path(i["output"]).exists() for i in result["items"] if i["ok"])
    assert events[-1]["type"] == "error" and "1 of 3 videos failed" in events[-1]["message"]


def test_cli_estimate(tmp_path):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    run = cli(["--config", str(write_cfg(tmp_path)), "--json", "estimate", str(video),
               "--provider", "anthropic"], tmp_path)
    assert run.returncode == 0, run.stderr
    item = json.loads(run.stdout.splitlines()[-1])["items"][0]
    assert item["model"] == "claude-opus-5-5" and item["paid_provider"] is True
    assert 0 < item["total"] < 0.1 and item["text"].startswith("$")


def test_config_yaml_and_defaults_agree_on_ai_settings():
    import yaml
    from autoedit.config import DEFAULTS
    on_disk = yaml.safe_load((PROJECT_DIR / "config.yaml").read_text(encoding="utf-8"))["ai"]
    assert on_disk == DEFAULTS["ai"]


def test_ai_edit_with_motion_graphics_end_to_end(talk, cfg, monkeypatch):
    """"Edit this like a professional promoter": the Director adds graphics (its own AI call,
    here failing twice so the rule-based plan is used), and the video renders with them."""
    from autoedit import director
    from tests.gfx_helpers import chromium_available
    tmp, video, photo, whisper = talk
    fake, calls = scripted([photo_plan(cfg)])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    gfake, gcalls = scripted(["not json"])
    monkeypatch.setattr(director, "ask_json", gfake)
    rec = Recorder()
    render = chromium_available()
    result = ai_edit.ai_edit_video(video, cfg, "Edit this like a professional promoter", [photo],
                                   reporter=rec, render=render)
    assert "graphics" in rec.stages and len(gcalls) == 2
    event = next(d for k, d in rec.events if k == "graphics")
    assert event["style"] == "promoter" and event["fallback"]
    project = load_project(result["project"])
    gfx = [c for t in project["tracks"] if t["kind"] == "graphics" for c in t["clips"]]
    assert gfx and all(c["director"]["style"] == "promoter" for c in gfx)
    assert any(d.startswith("Motion graphics (Professional promoter)") for d in result["summary"]["details"])
    if render:
        assert Path(result["output"]).exists()


def test_ai_edit_without_graphics_is_unchanged(talk, cfg, monkeypatch):
    tmp, video, photo, whisper = talk
    fake, calls = scripted([photo_plan(cfg)])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    rec = Recorder()
    result = ai_edit.ai_edit_video(video, cfg, "fast", [photo], reporter=rec, render=False)
    assert "graphics" not in rec.stages
    project = load_project(result["project"])
    assert not [t for t in project["tracks"] if t["kind"] == "graphics"]


# ------------------------------------------------------------ video formats in the AI edit

def test_ai_edit_with_a_forced_format(talk, cfg, monkeypatch):
    """--format reaction: the other video fills the screen, you in a corner window."""
    tmp, video, photo, whisper = talk
    source = synthetic.make_video(tmp / "source.mp4")
    fake, calls = scripted([photo_plan(cfg)])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    rec = Recorder()
    result = ai_edit.ai_edit_video(video, cfg, "fast", [photo], reporter=rec, render=True,
                                   format="reaction",
                                   inputs={"source": [source], "offsets": {"source": "0.5"}})
    assert "format" in rec.stages
    event = next(d for k, d in rec.events if k == "format")
    assert event["format"] == "reaction"
    project = load_project(result["project"])
    assert project["meta"]["format"] == "reaction"
    layout = project["tracks"][0]["clips"][0]["layout"]
    assert layout["type"] == "pip" and layout["offset"] == 0.5
    assert result["summary"]["format"] == "reaction"
    assert result["summary"]["details"][0].startswith("Format: Reaction")
    assert Path(result["output"]).exists()


def test_ai_edit_format_without_its_files_is_refused(talk, cfg):
    tmp, video, photo, _ = talk
    with pytest.raises(EditorError, match="video you react to"):
        ai_edit.ai_edit_video(video, cfg, "", [], format="reaction", render=False,
                              reporter=Recorder())


def test_ai_edit_picks_a_format_from_the_instruction(talk, cfg, monkeypatch):
    tmp, video, photo, _ = talk
    screen = synthetic.make_video(tmp / "screen.mp4")
    fake, calls = scripted([photo_plan(cfg)])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    result = ai_edit.ai_edit_video(video, cfg, "screenshare tutorial", [photo], render=False,
                                   reporter=Recorder(), inputs={"screen": [screen]})
    assert result["summary"]["format"] == "screenshare"
    assert len(calls) == 1                               # no extra AI call to pick the format


def test_voiceover_edit_end_to_end(tmp_path, cfg, monkeypatch):
    from autoedit.words import Word
    vo = tmp_path / "vo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=300:r=48000:d=4",
                    str(vo)], check=True)
    clip = synthetic.make_video(tmp_path / "b1.mp4")
    pic = synthetic.make_image(tmp_path / "b2.png")
    words = [Word(text=t, start=s, end=s + 0.3) for t, s in
             (("Ang", 0.2), ("ganda", 0.6), ("dito.", 1.0), ("Tara", 2.0), ("na!", 2.4))]
    monkeypatch.setattr(ai_edit, "load_words", lambda *a, **k: (words, False, 0.0))
    rec = Recorder()
    result = ai_edit.voiceover_edit(vo, [clip, pic], cfg, "", reporter=rec, render=True,
                                    output=tmp_path / "out" / "vo.mp4")
    assert rec.stages[:2] == ["transcript", "format"]
    project = load_project(result["project"])
    assert project["meta"]["format"] == "voiceover_broll"
    assert any(t["kind"] == "caption" and t["clips"] for t in project["tracks"])
    assert Path(result["output"]).exists()
    assert result["summary"]["format"] == "voiceover_broll"


def test_voiceover_edit_missing_broll_is_clear(tmp_path, cfg):
    vo = tmp_path / "vo.wav"
    vo.write_bytes(b"x")
    with pytest.raises(EditorError, match="B-roll file not found"):
        ai_edit.voiceover_edit(vo, [tmp_path / "nope.mp4"], cfg, render=False,
                               reporter=Recorder())


def test_cli_formats_list(tmp_path):
    run = cli(["--json", "formats"], tmp_path)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.splitlines()[-1])
    assert len(result["formats"]) == 13
    assert {f["id"] for f in result["formats"]} >= {"reaction", "clone", "green_screen", "listicle"}


def test_cli_ai_edit_with_a_format_and_inputs(tmp_path, cfg):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    other = synthetic.make_video(tmp_path / "second.mp4")
    transcript = synthetic.make_transcript(tmp_path / "talk.json")
    photo = synthetic.make_image(tmp_path / "github_logo.png")
    seed_transcript(tmp_path, video, transcript)
    plan_file = tmp_path / "accepted.plan.json"
    plan_file.write_text(json.dumps({"plan": photo_plan(cfg)}), encoding="utf-8")
    run = cli(["--config", str(write_cfg(tmp_path)), "--json", "ai-edit", str(video),
               "--photos", str(photo), "--plan-file", str(plan_file), "--no-render",
               "--format", "split_screen", "--input", f"second={other}",
               "--offset", "second=-0.25"], tmp_path)
    assert run.returncode == 0, run.stderr
    events = [json.loads(line) for line in run.stdout.splitlines()]
    assert any(e["type"] == "format" and e["format"] == "split_screen" for e in events)
    result = next(e for e in events if e["type"] == "result")
    project = load_project(result["project"])
    layout = project["tracks"][0]["clips"][0]["layout"]
    assert layout["type"] == "split" and layout["offset"] == -0.25


@pytest.mark.parametrize("flag", [["--input", "nofile"], ["--offset", "second=soon"]])
def test_cli_bad_format_inputs_are_explained(tmp_path, flag):
    video = synthetic.make_video(tmp_path / "talk.mp4")
    run = cli(["--config", str(write_cfg(tmp_path)), "ai-edit", str(video), *flag], tmp_path)
    assert run.returncode != 0
    assert "ROLE=" in run.stderr
