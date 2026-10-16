"""Ask a language model for a JSON answer: Groq (default) or Anthropic (your own key).

Keys come from the environment (GROQ_API_KEY / ANTHROPIC_API_KEY; the desktop app passes
them in from its encrypted store, the command line can use .env). They are never printed.
"""

import json
import os

from .errors import EditorError
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
    """The model could not be asked (no key, network, rate limit...)."""


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
             timeout=300):
    """Ask for one JSON object. Returns (text, usage, model_used).

    `usage` is {"input_tokens": n, "output_tokens": n}. The text is NOT checked here; the
    caller validates it (and may ask again).
    """
    if provider == "groq":
        return _ask_groq(model, system, prompt, schema, max_tokens, timeout)
    if provider == "anthropic":
        return _ask_anthropic(model, system, prompt, schema, max_tokens, effort, timeout)
    raise LLMError(f"Unknown AI provider '{provider}'. Choose: {', '.join(PROVIDERS)}")


def _ask_groq(model, system, prompt, schema, max_tokens, timeout):
    import requests

    key = api_key("groq")
    # JSON mode guarantees a JSON object, not the schema, so the schema goes in the prompt.
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system + "\n\nAnswer with ONE JSON object that "
             "matches this JSON Schema exactly:\n" + json.dumps(strict_schema(schema))},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_completion_tokens": max_tokens,
    }
    try:
        response = requests.post(GROQ_CHAT_URL, headers={"Authorization": f"Bearer {key}"},
                                 json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise LLMError(f"Could not reach Groq (check your internet connection): {exc}")
    if response.status_code == 401:
        raise LLMError("Groq rejected the API key (401). Check it in Settings.")
    if response.status_code == 404:
        raise LLMError(f"Groq does not know the model '{model}' (404). Choose another model "
                       f"in Settings (see console.groq.com/docs/models).")
    if response.status_code == 429:
        raise LLMError("Groq says you hit the usage limit (429). Wait a bit and try again.")
    if response.status_code != 200:
        raise LLMError(f"Groq request failed ({response.status_code}): {response.text[:300]}")
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
    client = anthropic.Anthropic(api_key=api_key("anthropic"), timeout=timeout, max_retries=2)
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
    except anthropic.RateLimitError:
        raise LLMError("Anthropic says you hit the rate limit (429). Wait a bit and try again.")
    except anthropic.BadRequestError as exc:
        raise LLMError(f"Anthropic refused the request (400): {exc.message}")
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Anthropic request failed ({exc.status_code}). Try again later.")
    except anthropic.APIConnectionError:
        raise LLMError("Could not reach Anthropic (check your internet connection).")
    usage = {"input_tokens": int(response.usage.input_tokens or 0),
             "output_tokens": int(response.usage.output_tokens or 0)}
    if response.stop_reason == "refusal":
        raise LLMError("The model declined this request.")
    if response.stop_reason == "max_tokens":
        return "", usage, response.model           # cut off: the caller asks again
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, usage, response.model
