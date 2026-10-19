"""Load settings: built-in defaults <- config.yaml <- pacing preset <- command-line flags."""

import copy
from pathlib import Path

import yaml

from . import PROJECT_DIR
from .errors import EditorError

# Defaults used when config.yaml leaves something out. Keep in sync with config.yaml.
DEFAULTS = {
    "style": "yellow_pop",
    "grade": "natural_clean",
    "preset": "fast",
    "language": "tl",
    "transcription": {
        "provider": "groq",
        "groq_model": "whisper-large-v3",
        "taglish_hint": True,
        "local_model": "medium",
        "local_device": "auto",
        "vocabulary_file": "vocabulary.json",
    },
    "presets": {
        "fast": {
            "silence_threshold": 0.25,
            "remove_fillers": True,
            "zoom": True,
            "zoom_amount": 1.15,
            "zoom_min_interval": 1.5,
            "zoom_max_interval": 4.0,
        },
        "relaxed": {
            "silence_threshold": 0.6,
            "remove_fillers": True,
            "zoom": True,
            "zoom_amount": 1.10,
            "zoom_min_interval": 3.0,
            "zoom_max_interval": 7.0,
        },
    },
    "silence": {
        "padding": 0.08,
        "use_audio_detection": True,
        "noise_db": -35,
    },
    "fillers": ["ah", "uh", "um", "uhm", "eh"],
    "zoom": {"anchor_y": 0.4},
    "audio": {"loudness": -14, "true_peak": -1.5},
    "captions": {
        "enabled": True,
        "fonts_folder": "assets/fonts",
        "font_regular": "Inter",
        "font_bold": "Inter",
        "font_heavy": "Inter Black",
        "punctuation": "remove",
    },
    "highlight": {
        "enabled": True,
        "color": None,
        "manual_markers": True,
        "numbers": True,
        "prices": True,
        "english_terms": True,
        "long_words": True,
        "long_word_min_letters": 7,
        "max_per_4_words": 1,
        "extra_keywords": [],
        "ignore_words": [],
    },
    "overlays": {
        "enabled": True,
        "triggers_file": "triggers.yaml",
        "folder": "assets/overlays",
    },
    "tracking": {
        "hand_model": "",
        "face_model": "",
        "pose_model": "",
        "fps": 30,
        "min_confidence": 0.5,
        "swap_hands": False,
    },
    "graphics": {
        "style": "auto",
        "max_per_10s": None,
        "track_face": True,
        "min_font": 30,
    },
    "broll": {
        "library_folder": "",
        "use_stock": True,
    },
    "music": {"folder": "assets/music"},
    "editorial": {"name": "", "handle": "", "brand": ""},
    "presets_folder": "presets",
    "polish": {
        "inbox": "robot/inbox",
        "outbox": "robot/outbox",
        "failed": "robot/failed",
        "done": "robot/done",
        "settle_seconds": 10,
        "interval_seconds": 5,
        "max_minutes": 30,
    },
    "sfx": {
        "enabled": False,
        "volume": 0.4,
        "pop": "assets/sfx/pop.wav",
        "whoosh": "assets/sfx/whoosh.wav",
    },
    "branding": {
        "intro": "",
        "intro_duration": 2.0,
        "outro": "",
        "outro_duration": 2.0,
        "watermark": "",
        "watermark_position": "top_left",
        "watermark_width": 180,
        "watermark_opacity": 0.85,
    },
    "output": {
        "folder": "output",
        "fps": 30,
        "crf": 20,
        "encoder_speed": "medium",
        "audio_bitrate": "192k",
        "save_transcript": True,
        "save_project": True,
    },
    "ai": {
        "provider": "groq",
        "groq_model": "openai/gpt-oss-120b",
        "anthropic_model": "claude-opus-5-5",
        "anthropic_effort": "medium",
        "max_tokens": 8000,
        "cache_folder": "work/cache",
        "prices": {   # US$; see config.yaml (Groq prices not checked against groq.com)
            "whisper-large-v3": {"per_audio_hour": 0.111, "min_seconds": 10},
            "whisper-large-v3-turbo": {"per_audio_hour": 0.04, "min_seconds": 10},
            "openai/gpt-oss-120b": {"input_per_million": 0.15, "output_per_million": 0.75},
            "claude-opus-5-5": {"input_per_million": 4.00, "output_per_million": 20.00},
            "claude-sonnet-5-5": {"input_per_million": 2.00, "output_per_million": 10.00},
            "claude-haiku-5-5": {"input_per_million": 0.10, "output_per_million": 0.50},
        },
    },
    "work_folder": "work",
    "keep_work_files": False,
    "watch": {"interval_seconds": 5},
}


def deep_merge(base, extra):
    result = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path=None, overrides=None):
    """Read config.yaml and return the final settings dict.

    `overrides` holds command-line values; None values are ignored.
    The chosen pacing preset is copied into cfg["pacing"].
    """
    path = Path(path) if path else PROJECT_DIR / "config.yaml"
    user = {}
    if path.exists():
        try:
            user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise EditorError(f"config.yaml has a typo and could not be read:\n{exc}")
    elif path != PROJECT_DIR / "config.yaml":
        raise EditorError(f"Config file not found: {path}")
    cfg = deep_merge(DEFAULTS, user)
    for key, value in (overrides or {}).items():
        if value is not None:
            cfg[key] = value
    return apply_preset(cfg)


def apply_preset(cfg):
    name = str(cfg["preset"])
    if name not in cfg["presets"]:
        raise EditorError(f"Unknown preset '{name}'. Presets in config.yaml: "
                          f"{', '.join(cfg['presets'])}")
    cfg["pacing"] = deep_merge(DEFAULTS["presets"]["fast"], cfg["presets"][name])
    for key in ("silence_threshold", "zoom_amount"):
        if cfg.get(key) is not None:          # set by a command-line flag
            cfg["pacing"][key] = cfg[key]
    return cfg


def project_path(relative):
    """Turn a path from config.yaml (relative to the project folder) into a full path."""
    if not relative:
        return None
    p = Path(relative)
    return p if p.is_absolute() else PROJECT_DIR / p
