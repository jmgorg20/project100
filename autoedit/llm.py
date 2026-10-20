"""Ask a language model for a JSON answer: Groq (default) or Anthropic (your own key).

Keys come from the environment (GROQ_API_KEY / ANTHROPIC_API_KEY; the desktop app passes
them in from its encrypted store, the command line can use .env). They are never printed.

A request can never hold the edit up (a real Windows run sat at "Planning the editorial scenes"
for minutes, 0% CPU and network): each request has a hard time limit (90 s; `ai: timeout`), is
tried again up to 2 times (`ai: retries`) after a timeout, a lost connection, a server error or a
rate limit (429: after the wait Groq asks for, when it is short), and cancel works while it waits.
What is happening is said on screen (the `notify` callback). Every request is logged, with the
time, its size, the answer's status, how long it took and the tokens, to work/logs/ai-plan.log
(never the key or the words).
"""

import json
import os
import re
import threading
import time

from .errors import Cancelled, EditorError
from .transcribe import load_dotenv

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
PROVIDERS = ("groq", "anthropic")
KEY_NAMES = {"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
# Anthropic's server-side refusal fallback (re-runs a declined request on another model).
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Structured outputs do not accept these JSON Schema keywords; we check them ourselves.
UNSUPPORTED_KEYWORDS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                        "multipleOf", "minLength", "maxLength", "minItems", "maxItems",
                        "$schema", "title"}


class LLMError(EditorError):
    """The model could not be asked (no key, network, rate limit...). `status`: the HTTP status
    (None for a network problem or a timeout); `retry_after`: seconds the provider asks to wait;
    `retryable`: worth asking again; `limit` / `requested`: a too-large request's token figures."""

    def __init__(self, message, status=None, retry_after=None, retryable=False, limit=None, requested=None):
        super().__init__(message)
        self.status, self.retry_after, self.retryable = status, retry_after, retryable
        self.limit, self.requested = limit, requested


TIMEOUT = 90.0
RETRIES = 2
MAX_WAIT = 60.0          # a rate-limit wait longer than this is not waited out: the rules plan instead
BACKOFF = (3.0, 8.0)


def estimate_tokens(text):
    """A cautious token count (Taglish and JSON run to ~3 characters a token)."""
    return len(text) // 3 + 1


class RequestLog:
    """work/logs/ai-plan.log: one timestamped line per request and answer."""

    def __init__(self, cfg=None):
        from .config import project_path
        folder = project_path((cfg or {}).get("work_folder") or "work") / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "ai-plan.log"
        if self.path.exists() and self.path.stat().st_size > 1_000_000:
            self.path.replace(folder / "ai-plan.old.log")

    def step(self, message):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} {message}\n")


def api_key(provider):
    load_dotenv()
    key = os.environ.get(KEY_NAMES[provider], "").strip()
    if not key or key.startswith("your_"):
        where = "Settings -> API keys in the app" if provider == "anthropic" else \
            "Settings -> API keys in the app, or GROQ_API_KEY in .env"
        raise LLMError(f"No {provider.title()} API key. Add it in {where}.")
    return key


def strict_schema(schema):
    """Copy of a JSON Schema without the keywords structured outputs reject."""
    if isinstance(schema, dict):
        return {k: strict_schema(v) for k, v in schema.items() if k not in UNSUPPORTED_KEYWORDS}
    if isinstance(schema, list):
        return [strict_schema(v) for v in schema]
    return schema


def ask_json(provider, model, system, prompt, schema, max_tokens=8000, effort="medium",
             timeout=None, retries=None, cancel=None, notify=None, cfg=None, step="AI request", options=None):
    """Ask for one JSON object. Returns (text, usage, model_used).

    `usage` is {"input_tokens": n, "output_tokens": n}. The text is NOT checked here; the
    caller validates it (and may ask again). A hard time limit, retries, a rate-limit wait and a
    log line per try (see the module's doc); `notify(message)` is told what is going on;
    `options`: extra request fields (Groq: reasoning_effort). Raises LLMError when it gives up.
    """
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown AI provider '{provider}'. Choose: {', '.join(PROVIDERS)}")
    ai = (cfg or {}).get("ai") or {}
    timeout = float(timeout or ai.get("timeout") or TIMEOUT)
    retries = int(ai.get("retries", RETRIES) if retries is None else retries)
    log = RequestLog(cfg)
    size = len(system) + len(prompt) + len(json.dumps(schema, separators=(",", ":")))
    for attempt in range(1, retries + 2):
        if cancel is not None and cancel.is_set():
            raise Cancelled(f"Cancelled while waiting for the AI ({step}).")
        log.step(f"{step}: {provider} {model} try {attempt}/{retries + 1}: request {size} characters "
                 f"(~{estimate_tokens(' ' * size)} tokens), up to {max_tokens} answer tokens, {timeout:g} s limit")
        started = time.monotonic()
        try:
            text, usage, used = _with_deadline(
                lambda: _ask(provider, model, system, prompt, schema, max_tokens, effort, timeout, options),
                timeout, cancel, step)
        except LLMError as exc:
            seconds = time.monotonic() - started
            log.step(f"{step}: status {exc.status or '-'} after {seconds:.1f} s: {exc}"
                     + (f" (retry after {exc.retry_after:g} s)" if exc.retry_after else ""))
            if not exc.retryable or attempt > retries:
                raise
            wait = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            if exc.status == 429:
                wait = exc.retry_after if exc.retry_after is not None else 10.0
                if wait > MAX_WAIT:
                    log.step(f"{step}: the wait ({wait:g} s) is too long; giving up")
                    raise
                what = f"{provider.title()} is rate limiting the requests (429)"
            elif exc.status is None and "did not answer" in str(exc):
                what = f"{provider.title()} did not answer within {timeout:g} s"
            else:
                what = f"{provider.title()} had a problem ({exc.status or 'connection'})"
            msg = f"{what}: trying again in {wait:.0f} s ({attempt} of {retries})"
            log.step(f"{step}: {msg}")
            if notify:
                notify(msg)
            _sleep(wait, cancel, step)
            continue
        seconds = time.monotonic() - started
        log.step(f"{step}: status 200 after {seconds:.1f} s, {usage['input_tokens']} in / "
                 f"{usage['output_tokens']} out tokens ({used})")
        return text, usage, used
    raise LLMError("no answer")          # not reached


def _ask(provider, model, system, prompt, schema, max_tokens, effort, timeout, options):
    if provider == "groq":
        return _ask_groq(model, system, prompt, schema, max_tokens, timeout, options)
    return _ask_anthropic(model, system, prompt, schema, max_tokens, effort, timeout)


def _with_deadline(call, timeout, cancel, step):
    """Run `call` with a hard limit: the edit stops waiting at the deadline (the request runs on in
    the background until its own socket time-out) and on cancel."""
    box = {}

    def run():
        try:
            box["value"] = call()
        except BaseException as exc:            # handed to the waiting thread
            box["error"] = exc
    worker = threading.Thread(target=run, daemon=True, name="ai-request")
    worker.start()
    deadline = time.monotonic() + timeout
    while worker.is_alive():
        worker.join(0.25)
        if cancel is not None and cancel.is_set():
            raise Cancelled(f"Cancelled while waiting for the AI ({step}).")
        if time.monotonic() > deadline and worker.is_alive():
            raise LLMError(f"the AI did not answer within {timeout:g} s", retryable=True)
    if "error" in box:
        raise box["error"]
    return box["value"]


def _sleep(seconds, cancel, step):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel is not None and cancel.is_set():
            raise Cancelled(f"Cancelled while waiting for the AI ({step}).")
        time.sleep(min(0.25, max(0.0, end - time.monotonic())))


def retry_after_of(response):
    """Seconds Groq asks to wait: the retry-after header, or "try again in 7.5s" / "in 1m2.5s"."""
    header = (getattr(response, "headers", None) or {}).get("retry-after")
    try:
        if header:
            return float(header)
    except ValueError:
        pass
    text = getattr(response, "text", "") or ""
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", text or "")
    if m:
        value = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
        return round(value + 60 * int(m.group(1) or 0), 2)
    return None


def too_large_of(text):
    """(limit, requested) from Groq's "Request too large ... Limit 8000, Requested 9334"."""
    m = re.search(r"Limit\s*(\d+)\D+Requested\s*(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _ask_groq(model, system, prompt, schema, max_tokens, timeout, options=None):
    import requests

    key = api_key("groq")
    # JSON mode guarantees a JSON object, not the schema, so the schema goes in the prompt.
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system + "\n\nAnswer with ONE JSON object that "
             "matches this JSON Schema exactly:\n" + json.dumps(strict_schema(schema), separators=(",", ":"))},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_completion_tokens": max_tokens,
        **(options or {}),
    }
    try:
        # connect within 15 s; the answer within the limit (the caller also stops waiting then)
        url = os.environ.get("AUTOEDIT_GROQ_URL") or GROQ_CHAT_URL     # tests: a local stand-in
        response = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                                 json=body, timeout=(15, timeout + 5))
    except requests.Timeout:
        raise LLMError(f"the AI did not answer within {timeout:g} s", retryable=True)
    except requests.RequestException as exc:
        raise LLMError(f"Could not reach Groq (check your internet connection): {exc}", retryable=True)
    status = response.status_code
    if status == 401:
        raise LLMError("Groq rejected the API key (401). Check it in Settings.", status)
    if status == 404:
        raise LLMError(f"Groq does not know the model '{model}' (404). Choose another model "
                       f"in Settings (see console.groq.com/docs/models).", status)
    if status == 413 or (status == 429 and "Request too large" in response.text):
        limit, requested = too_large_of(response.text)
        raise LLMError(f"the request is too large for Groq's free per-minute limit ({status}"
                       + (f": {requested} tokens asked, the limit is {limit}" if limit else "") + ")",
                       status, limit=limit, requested=requested)
    if status == 429:
        wait = retry_after_of(response)
        raise LLMError("Groq says you hit the usage limit (429)"
                       + (f"; it asks to wait {wait:g} s" if wait is not None else "") + ".",
                       status, retry_after=wait, retryable=True)
    if status != 200:
        raise LLMError(f"Groq request failed ({status}): {response.text[:300]}", status,
                       retryable=status >= 500)
    data = response.json()
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError("Groq sent an answer in an unexpected shape.")
    usage = data.get("usage") or {}
    return text, {"input_tokens": int(usage.get("prompt_tokens", 0)),
                  "output_tokens": int(usage.get("completion_tokens", 0))}, data.get("model", model)


def _ask_anthropic(model, system, prompt, schema, max_tokens, effort, timeout):
    try:
        import anthropic
    except ImportError:
        raise LLMError("The Anthropic provider needs its library. Run:\n"
                       "  python -m pip install anthropic")
    # the retries and the time limit are ask_json's (one place, one log)
    client = anthropic.Anthropic(api_key=api_key("anthropic"), timeout=timeout + 5, max_retries=0)
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": strict_schema(schema)}},
            betas=[ANTHROPIC_FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        raise LLMError("Anthropic rejected the API key (401). Check it in Settings.")
    except anthropic.PermissionDeniedError:
        raise LLMError("This Anthropic API key may not use this model (403).")
    except anthropic.NotFoundError:
        raise LLMError(f"Anthropic does not know the model '{model}' (404). Choose another "
                       f"model in Settings.")
    except anthropic.RateLimitError as exc:
        wait = retry_after_of(getattr(exc, "response", None))
        raise LLMError("Anthropic says you hit the rate limit (429).", 429, retry_after=wait, retryable=True)
    except anthropic.BadRequestError as exc:
        raise LLMError(f"Anthropic refused the request (400): {exc.message}")
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Anthropic request failed ({exc.status_code}). Try again later.", exc.status_code,
                       retryable=exc.status_code >= 500)
    except anthropic.APITimeoutError:
        raise LLMError(f"the AI did not answer within {timeout:g} s", retryable=True)
    except anthropic.APIConnectionError:
        raise LLMError("Could not reach Anthropic (check your internet connection).", retryable=True)
    usage = {"input_tokens": int(response.usage.input_tokens or 0),
             "output_tokens": int(response.usage.output_tokens or 0)}
    if response.stop_reason == "refusal":
        raise LLMError("The model declined this request.")
    if response.stop_reason == "max_tokens":
        return "", usage, response.model           # cut off: the caller asks again
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, usage, response.model
