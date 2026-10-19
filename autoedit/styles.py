"""Caption styles. To add a new style, copy one entry in STYLES, give it a new
number and name, and change the values. Nothing else needs editing.

Settings you can use in a style (anything left out uses the default below):

  font          "regular", "bold" or "heavy" (the actual font names are in config.yaml)
  size          text height in pixels on the 1080x1920 frame
  color         normal text colour, "#RRGGBB"
  active_color  colour of the word being spoken right now (None = no change)
  active_box    colour of a box drawn behind the word being spoken (None = no box)
  active_scale  size of the spoken word in percent (100 = same size)
  keyword_color colour for KEY WORDS (None = keywords not highlighted in this style)
  keyword_uppercase  write keywords in CAPITALS
  outline       outline thickness, outline_color its colour
  shadow        shadow distance, shadow_color its colour, shadow_alpha 0 (solid) to 255 (invisible)
  box           True = solid box behind the whole text, box_color its colour, box_padding its size
  card          colour of a rounded card behind each caption group (None = no card), with a soft
                shadow; card_radius its corner radius in pixels
  uppercase / lowercase   change the case of all text
  zone          where the captions sit: "lower", "center" or "top"
  align         "center" or "left" (lines start at the left safe margin)
  mode          "phrase"     = show a group of words, colour the spoken word
                "word"       = one word at a time
                "typewriter" = words appear as they are spoken, stay until the group ends
                "pop"        = like typewriter, and each new word pops in (scales up)
  words_per_line, max_lines   how many words fit in one caption group
  max_chars     max letters per line (None = worked out from the font size)
"""

from dataclasses import dataclass, replace
from typing import Optional

from .errors import EditorError


@dataclass
class CaptionStyle:
    number: int
    name: str
    description: str
    font: str = "bold"
    size: int = 76
    color: str = "#FFFFFF"
    active_color: Optional[str] = None
    active_box: Optional[str] = None
    active_scale: int = 100
    keyword_color: Optional[str] = None
    keyword_uppercase: bool = False
    outline: float = 5
    outline_color: str = "#000000"
    shadow: float = 0
    shadow_color: str = "#000000"
    shadow_alpha: int = 0
    box: bool = False
    box_color: str = "#000000"
    box_padding: float = 14
    card: Optional[str] = None
    card_radius: float = 30
    uppercase: bool = False
    lowercase: bool = False
    zone: str = "lower"
    align: str = "center"
    punctuation: str = "remove"   # "remove": no , . ! ? ; : or quotes on screen; "keep"
    mode: str = "phrase"
    words_per_line: int = 4
    max_lines: int = 2
    max_chars: Optional[int] = None


YELLOW = "#FFE600"

STYLES = [
    CaptionStyle(1, "classic", "White text, black outline, lower area",
                 font="bold", size=74, outline=5),
    CaptionStyle(2, "yellow_pop", "Spoken word turns yellow, rest white",
                 font="heavy", size=82, active_color=YELLOW, outline=6, words_per_line=3),
    CaptionStyle(3, "boxed", "White text on a solid black box",
                 font="bold", size=64, outline=0, box=True, box_color="#000000",
                 box_padding=16, keyword_color=YELLOW),
    CaptionStyle(4, "bold_caps", "UPPERCASE bold, spoken word in red",
                 font="heavy", size=82, uppercase=True, active_color="#FF2E2E",
                 outline=6, words_per_line=3),
    CaptionStyle(5, "minimal", "Small lowercase white text, light shadow",
                 font="regular", size=54, lowercase=True, outline=0, shadow=3,
                 shadow_alpha=110, words_per_line=5),
    CaptionStyle(6, "neon_green", "Spoken word neon green, thick outline",
                 font="heavy", size=82, active_color="#39FF14", outline=9, words_per_line=3),
    CaptionStyle(7, "one_word", "One big word at a time in the center",
                 font="heavy", size=128, uppercase=True, outline=8, zone="center",
                 mode="word", keyword_color=YELLOW, words_per_line=1, max_lines=1),
    CaptionStyle(8, "pink_highlight", "Two lines, spoken word on a pink box",
                 font="bold", size=70, active_box="#FF3EA5", outline=4, words_per_line=3),
    CaptionStyle(9, "thick_outline", "Yellow text with a very thick black outline",
                 font="heavy", size=84, color=YELLOW, outline=12, words_per_line=3),
    CaptionStyle(10, "top_banner", "Near the top, white with a soft shadow",
                 font="bold", size=64, outline=1.5, outline_color="#202020", shadow=4,
                 shadow_alpha=120, zone="top", keyword_color=YELLOW, words_per_line=5),
    CaptionStyle(11, "center_keyword", "Big bold centered text, KEY WORDS in yellow",
                 font="heavy", size=108, outline=7, zone="center", keyword_color=YELLOW,
                 keyword_uppercase=True, words_per_line=3, max_chars=12),
    CaptionStyle(12, "typewriter", "Words appear one by one as you speak",
                 font="bold", size=72, outline=5, mode="typewriter", keyword_color=YELLOW,
                 align="left"),
    CaptionStyle(13, "pop_word", "Each word pops in as it is spoken",
                 font="heavy", size=82, outline=6, mode="pop", keyword_color=YELLOW,
                 words_per_line=3),
    CaptionStyle(14, "editorial_card", "Ink text on a cream rounded card, spoken word in terracotta",
                 font="bold", size=56, color="#17140F", active_color="#C8553D",
                 keyword_color="#C8553D", outline=0, shadow=0, card="#F4EFE6", card_radius=30,
                 box_padding=26, words_per_line=4, max_lines=2),
]


def list_styles():
    return list(STYLES)


def get_style(choice, keyword_color_override=None):
    """Find a style by number (1, "1") or name ("yellow_pop")."""
    text = str(choice).strip().lower()
    for style in STYLES:
        if text == str(style.number) or text == style.name:
            if keyword_color_override and style.keyword_color:
                return replace(style, keyword_color=keyword_color_override)
            return style
    names = ", ".join(f"{s.number}={s.name}" for s in STYLES)
    raise EditorError(f"Unknown caption style '{choice}'. Choose one of: {names}")
