"""A slow, rate-limited or failing AI never holds the edit up (a real Windows run sat at "Planning the
editorial scenes" for minutes): each request has a hard time limit and up to 2 retries, a 429 is
waited out when the wait is short (and said on screen), every request is logged to
work/logs/ai-plan.log, the editorial plan is sent compact and split to fit the free tier's
per-minute limit, and when the AI cannot be asked the rules plan the scenes, with the reason in
"What the AI did". Tested against a local stand-in for Groq's API."""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from autoedit import editorial, llm
from autoedit.errors import Cancelled
from tests.test_editorial_director import cfg as editorial_cfg
from tests.test_editorial_director import COLOURS, editorial_project, run

ROOT = Path(__file__).resolve().parent.parent
REAL_VIDEO = Path("/home/user/realtest/export.mp4")
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


class FakeGroq:
    """A local stand-in for Groq's chat endpoint: `script` is a list of answers, one per request
    (the last one repeats): ("ok", text) | ("sleep", seconds) | (status, body, headers)."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                step = fake.script[min(len(fake.requests) - 1, len(fake.script) - 1)]
                if step[0] == "sleep":
                    time.sleep(step[1])
                    step = ("ok", '{"ok": true}')
                if step[0] == "ok":
                    text = step[1](body) if callable(step[1]) else step[1]
                    data = json.dumps({"choices": [{"message": {"content": text}}], "model": body["model"],
                                       "usage": {"prompt_tokens": 100, "completion_tokens": 20}}).encode()
                    status, headers = 200, {}
                else:
                    status, data, headers = step[0], step[1].encode(), step[2] if len(step) > 2 else {}
                try:
                    self.send_response(status)
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/openai/v1/chat/completions"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def shots(tmp_path):
    from tests import synthetic
    return [synthetic.make_image(tmp_path / f"shot{i}.png", color=c, size="900x600") for i, c in enumerate(COLOURS)]


@pytest.fixture
def groq(monkeypatch):
    servers = []

    def make(script):
        s = FakeGroq(script)
        servers.append(s)
        monkeypatch.setenv("AUTOEDIT_GROQ_URL", s.url)
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        return s
    monkeypatch.setattr(llm, "BACKOFF", (0.1, 0.1))
    yield make
    for s in servers:
        s.close()


def ask(c, **kw):
    notes = []
    out = llm.ask_json("groq", "openai/gpt-oss-120b", "system", "prompt", SCHEMA, max_tokens=500, cfg=c,
                       notify=notes.append, step="test", **kw)
    return out, notes


def log_of(tmp_path):
    return (tmp_path / "work" / "logs" / "ai-plan.log").read_text()


def c_for(tmp_path, **ai):
    return {"work_folder": str(tmp_path / "work"), "ai": ai}


def test_a_slow_answer_is_given_up_on_after_the_limit_and_two_retries(tmp_path, groq):
    server = groq([("sleep", 30)])
    started = time.monotonic()
    with pytest.raises(llm.LLMError) as err:
        ask(c_for(tmp_path, timeout=1, retries=2))
    assert time.monotonic() - started < 6 and len(server.requests) == 3     # 3 tries of 1 s, never 30 s
    assert "did not answer within 1 s" in str(err.value)
    log = log_of(tmp_path)
    assert log.count("try ") == 3 and "trying again in 0 s (1 of 2)" in log and "(2 of 2)" in log
    assert "request" in log and "characters" in log and "gsk_test" not in log and "prompt" not in log.split("request")[0]


def test_a_rate_limit_is_waited_out_and_said_on_screen(tmp_path, groq):
    server = groq([(429, '{"error": {"message": "Rate limit reached ... Please try again in 1.2s"}}'),
                   ("ok", '{"ok": true}')])
    (text, usage, _m), notes = ask(c_for(tmp_path))
    assert json.loads(text) == {"ok": True} and len(server.requests) == 2
    assert notes == ["Groq is rate limiting the requests (429): trying again in 1 s (1 of 2)"]
    log = log_of(tmp_path)
    assert "status 429" in log and "retry after 1.2 s" in log and "status 200" in log and "100 in / 20 out" in log


def test_a_long_rate_limit_wait_is_not_waited_out(tmp_path, groq):
    groq([(429, "{}", {"retry-after": "300"})])
    started = time.monotonic()
    with pytest.raises(llm.LLMError) as err:
        ask(c_for(tmp_path))
    assert time.monotonic() - started < 3 and "it asks to wait 300 s" in str(err.value)
    assert "too long; giving up" in log_of(tmp_path)


def test_a_request_too_large_for_the_per_minute_limit_says_so(tmp_path, groq):
    groq([(413, '{"error": {"message": "Request too large for model ... tokens per minute (TPM): Limit 8000, '
                'Requested 9334, please reduce your message size"}}')])
    with pytest.raises(llm.LLMError) as err:
        ask(c_for(tmp_path))
    assert err.value.limit == 8000 and err.value.requested == 9334 and not err.value.retryable


def test_cancel_works_while_waiting_for_the_ai(tmp_path, groq):
    groq([("sleep", 30)])
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        ask(c_for(tmp_path, timeout=20), cancel=cancel)
    assert time.monotonic() - started < 3


# ---------------------------------------------------------------- the editorial scene plan

def ed_cfg(tmp_path, **ai):
    c = editorial_cfg()
    c["work_folder"] = str(tmp_path / "work")
    c["ai"] = {**c["ai"], **ai}
    return c


class Rep:
    def __init__(self):
        self.labels = []

    def stage(self, key, label):
        self.labels.append(label)

    def log(self, m):
        pass

    def progress(self, *a, **k):
        pass


def test_a_hanging_ai_falls_back_to_the_rules_with_the_reason(tmp_path, groq, shots):
    groq([("sleep", 30)])
    rep = Rep()
    started = time.monotonic()
    r = run(editorial_project(shots), ed_cfg(tmp_path, timeout=1, retries=2), use_ai=True, provider="groq",
            model="openai/gpt-oss-120b", reporter=rep)
    assert time.monotonic() - started < 30
    assert r["fallback"] and "did not answer within 1 s" in r["reason"] and "ai-plan.log" in r["reason"]
    assert r["count"] > 0 and all(s["beat"] for s in r["scenes"])          # planned by the rules
    assert any("did not answer within 1 s: trying again" in label for label in rep.labels)


def test_the_plan_is_compact_and_split_to_fit_the_per_minute_limit(tmp_path, groq, shots):
    def answer(body):
        prompt = body["messages"][1]["content"]
        todo = [int(line.split(" ")[0]) for line in prompt.split("SCENES TO PLAN (plan exactly these):\n")[1]
                .split("\n\n")[0].splitlines() if line[:1].isdigit()]
        return json.dumps({"summary": "ok", "scenes": [{"scene": i, "beat": "camera"} for i in todo]})
    server = groq([("ok", answer)])
    c = ed_cfg(tmp_path, groq_tpm=4000)
    r = run(editorial_project(shots), c, use_ai=True, provider="groq", model="openai/gpt-oss-120b")
    asked = [b for b in server.requests]
    assert len(asked) >= 2 and not r["fallback"]
    for body in asked:
        size = llm.estimate_tokens(body["messages"][0]["content"] + body["messages"][1]["content"])
        assert size + body["max_completion_tokens"] <= 4000 * 0.85 + 50        # each fits the budget
        assert body.get("reasoning_effort") == "low" and body["max_completion_tokens"] < 3000
    planned = [int(x) for b in asked for x in
               [line.split(" ")[0] for line in b["messages"][1]["content"].split("SCENES TO PLAN (plan exactly these):\n")[1]
                .split("\n\n")[0].splitlines() if line[:1].isdigit()]]
    assert len(planned) == len(set(planned))                                    # every scene asked once
    assert "in 2 requests" in log_of(tmp_path) or "requests (per-minute limit)" in log_of(tmp_path)


def test_a_too_large_answer_splits_the_request(tmp_path, groq, shots):
    def answer(body):
        return json.dumps({"summary": "ok", "scenes": []})
    too_big = (413, '{"error": {"message": "Request too large: Limit 8000, Requested 9000"}}')
    server = groq([too_big, ("ok", answer)])
    r = run(editorial_project(shots), ed_cfg(tmp_path), use_ai=True, provider="groq", model="openai/gpt-oss-120b")
    assert len(server.requests) >= 3 and "split in two" in log_of(tmp_path) and r["count"] > 0


def test_no_ai_request_when_what_is_said_sets_every_scene(tmp_path, groq, monkeypatch):
    server = groq([("ok", '{"scenes": []}')])
    monkeypatch.setattr(editorial, "cue_scenes", lambda ctx, made, scenes: {s.index: "headline" for s in scenes})
    from tests.director_helpers import make_project
    from tests.test_editorial_director import SCRIPT, make_words
    r = run(make_project(make_words(SCRIPT), caption_style="editorial_card"), ed_cfg(tmp_path), use_ai=True,
            provider="groq", model="openai/gpt-oss-120b")
    assert server.requests == [] and any("no AI scene plan was needed" in n for n in r["notes"])


@pytest.mark.skipif(not REAL_VIDEO.exists(), reason="the user's export is not here")
def test_the_real_app_command_finishes_when_groq_hangs(tmp_path):
    # editor.py ai-edit as the desktop app runs it, with Groq made to hang: the whole edit still ends
    import yaml
    from autoedit.config import load_config
    # the plan is given (as when the AI plan was saved), so the editorial scene plan is the step that hangs
    server = FakeGroq([("sleep", 60)])
    c = load_config()
    c["work_folder"] = str(tmp_path / "work")
    c["ai"]["cache_folder"] = str(tmp_path / "cache")
    c["ai"]["timeout"] = 2
    c["ai"]["retries"] = 1
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    env = {**os.environ, "AUTOEDIT_GROQ_URL": server.url, "GROQ_API_KEY": "gsk_test", "AUTOEDIT_FACE_SIMULATE": ""}
    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, str(ROOT / "editor.py"), "--json", "--config", str(conf), "ai-edit",
                               str(REAL_VIDEO), "--output", str(tmp_path / "edit.mp4"), "--provider", "groq",
                               "--transcribe-with", "groq", "--transcript", str(ROOT / "tests/data/realclip/groq_words.json"),
                               "--no-stock", "--preset", "premium_editorial_viral", "--format", "auto", "--no-render",
                               "--plan-file", str(ROOT / "tests/data/realclip/plan.json"),
                               "--instruction-file", str(ROOT / "tests/data/realclip/instruction.txt")],
                              capture_output=True, text=True, cwd=str(ROOT), stdin=subprocess.DEVNULL, timeout=600, env=env)
    finally:
        server.close()
    assert proc.returncode == 0, proc.stderr[-2000:]
    took = time.monotonic() - started
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    labels = [e.get("label", "") for e in events if e.get("type") == "stage"]
    assert any("did not answer within 2 s: trying again" in label for label in labels)
    summary = next(e for e in reversed(events) if e.get("type") == "summary")
    text = " ".join(summary.get("details", [])) + " " + summary.get("headline", "")
    assert "did not answer within 2 s" in text and "ai-plan.log" in text
    assert len(server.requests) >= 2 and took < 240
    log = (tmp_path / "work" / "logs" / "ai-plan.log").read_text()
    assert "editorial plan" in log and "no answer" not in log.split("\n")[0]
