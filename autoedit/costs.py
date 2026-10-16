"""Estimated API cost of an AI edit, in US dollars, from the prices in config.yaml (ai.prices).

These are estimates: real bills depend on the provider's current prices, free tiers and
rounding. Unknown models give None ("no price known") rather than a guess.
"""

import math

CHARS_PER_TOKEN = 3.5          # rough average for English/Tagalog text with numbers
EXPECTED_OUTPUT_TOKENS = 1500  # a typical plan


def transcription_cost(prices, model, seconds):
    price = prices.get(model)
    if not price or "per_audio_hour" not in price:
        return None
    billed = max(float(seconds), float(price.get("min_seconds", 0)))
    return billed / 3600 * float(price["per_audio_hour"])


def plan_cost(prices, model, input_tokens, output_tokens):
    price = prices.get(model)
    if not price or "input_per_million" not in price:
        return None
    return (input_tokens * float(price["input_per_million"])
            + output_tokens * float(price["output_per_million"])) / 1e6


def estimate_tokens(text):
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


def total(*parts):
    """Sum of the known parts; None only if every part is unknown."""
    known = [p for p in parts if p is not None]
    return sum(known) if known else None


def format_usd(amount):
    if amount is None:
        return "unknown (no price set for this model)"
    if amount == 0:
        return "$0"
    if amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"
