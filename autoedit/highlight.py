"""Pick KEY WORDS to colour in the captions. Free rules only, no AI service is called.

Two ways a word gets highlighted:
  1. Manual: you wrote it as *word* in the transcript JSON (always wins).
  2. Automatic rules (each can be switched off in config.yaml -> highlight):
     numbers, prices, English/tech terms, long words.
"""

import re

from .words import normalize

# Common English / tech words heard in Taglish videos. Add your own in config.yaml
# (highlight -> extra_keywords) instead of editing this list.
TECH_TERMS = {
    "ai", "app", "apps", "api", "online", "internet", "wifi", "website", "link", "upload",
    "download", "laptop", "computer", "phone", "cellphone", "android", "iphone", "code",
    "coding", "software", "hardware", "data", "cloud", "server", "github", "google",
    "youtube", "tiktok", "facebook", "instagram", "chatgpt", "gcash", "maya", "shopee",
    "lazada", "budget", "business", "money", "sale", "free", "tips", "tutorial", "hack",
    "secret", "update", "subscribe", "follow", "content", "creator", "video", "account",
    "password", "email", "bank", "invest", "savings", "salary", "income", "profit",
    "important", "problem", "solution", "best", "worst", "new", "first", "fast", "easy",
}

ENGLISH_NUMBERS = {
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
    "twelve", "twenty", "thirty", "forty", "fifty", "hundred", "thousand", "million",
    "billion", "dalawa", "tatlo", "apat", "lima", "anim", "pito", "walo", "siyam",
    "sampu", "daan", "libo", "milyon",
}

CURRENCY_WORDS = {"peso", "pesos", "piso", "php", "dollar", "dollars", "usd", "k"}

# Short, very common Tagalog/English words that should never be highlighted.
STOP_WORDS = {
    "ang", "ng", "sa", "na", "at", "ay", "mga", "si", "ni", "ko", "mo", "ka", "ako",
    "ikaw", "siya", "kami", "tayo", "kayo", "sila", "ito", "iyan", "iyon", "yung", "yun",
    "lang", "din", "rin", "pa", "po", "opo", "naman", "talaga", "kasi", "pero", "kung",
    "the", "a", "an", "and", "or", "to", "of", "is", "it", "in", "on", "so", "you", "i",
}

# Letters that native Tagalog spelling rarely uses: a hint the word is borrowed English.
LOANWORD_LETTERS = re.compile(r"[cfjqvxz]")


def has_currency(text):
    return bool(re.search(r"[₱$€£]|^php\d|^p\d", text.lower()))


def is_number(text):
    return bool(re.search(r"\d", text)) or normalize(text) in ENGLISH_NUMBERS


def score_word(word, next_word, settings):
    """Return a priority (higher = more important) or 0 if the word is not a keyword."""
    key = normalize(word.text)
    if not key or key in STOP_WORDS or key in settings.get("ignore_words", []):
        return 0
    if word.manual and settings.get("manual_markers", True):
        return 100
    if key in [normalize(k) for k in settings.get("extra_keywords", [])]:
        return 90
    if settings.get("prices", True):
        next_key = normalize(next_word.text) if next_word else ""
        if has_currency(word.text) or (is_number(word.text) and next_key in CURRENCY_WORDS):
            return 80
    if settings.get("numbers", True) and is_number(word.text):
        return 70
    if settings.get("english_terms", True):
        if key in TECH_TERMS or (word.text.isupper() and len(key) >= 2):
            return 60
        if len(key) >= 4 and LOANWORD_LETTERS.search(key):
            return 50
    if settings.get("long_words", True) and len(key) > settings.get("long_word_min_letters", 7):
        return 40
    return 0


def mark_keywords(words, settings):
    """Set `highlight=True` on the most important words.

    To keep captions readable, at most `max_per_4_words` words are highlighted in
    every run of 4 words (manual *markers* are always kept).
    """
    words_per_group = 4
    max_per_group = settings.get("max_per_4_words", 1)
    if not settings.get("enabled", True):
        for w in words:
            w.highlight = False
        return words
    scores = [score_word(w, words[i + 1] if i + 1 < len(words) else None, settings)
              for i, w in enumerate(words)]
    for group_start in range(0, len(words), words_per_group):
        indexes = range(group_start, min(group_start + words_per_group, len(words)))
        ranked = sorted((i for i in indexes if scores[i] > 0), key=lambda i: -scores[i])
        for rank, i in enumerate(ranked):
            words[i].highlight = rank < max_per_group or scores[i] >= 100
    return words
