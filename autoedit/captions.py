"""Turn timed words into an ASS subtitle file (drawn onto the video by FFmpeg/libass)."""

import re

from .styles import CaptionStyle
from .textmeasure import TextMeasurer, find_font_file

WIDTH, HEIGHT = 1080, 1920

# Safe area: keep clear of the TikTok/Reels buttons on the right and the
# caption/description text at the bottom (~20% of the screen).
SAFE_LEFT = 90
SAFE_RIGHT = 170
SAFE_WIDTH = WIDTH - SAFE_LEFT - SAFE_RIGHT
CENTER_X = SAFE_LEFT + SAFE_WIDTH // 2

# Where each zone puts the captions: (ASS alignment, x, y).
# Alignment 2 = anchored at bottom-center, 5 = middle-center, 8 = top-center.
ZONES = {
    "lower": (2, CENTER_X, 1450),   # bottom edge of text stays above the bottom 24%
    "center": (5, CENTER_X, 940),
    "top": (8, CENTER_X, 250),      # below the "Following | For You" bar
    "divider": (5, CENTER_X, 1152),  # on the line between screen recording and face
}

LEFT_X = SAFE_LEFT + 20       # x position of left-aligned captions

HOLD_AFTER_LAST_WORD = 0.25   # keep a caption on screen a moment after the last word
MERGE_GAP = 0.35              # gaps shorter than this keep the previous caption visible
NEW_GROUP_PAUSE = 0.7         # a pause longer than this starts a new caption group


def ass_color(hex_color, alpha=0):
    """'#RRGGBB' -> ASS '&HAABBGGRR'."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(centiseconds):
    cs = max(0, int(centiseconds))
    h, rest = divmod(cs, 360000)
    m, rest = divmod(rest, 6000)
    s, cs = divmod(rest, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def escape(text):
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").strip()


STRIP_MARKS = set(",.!?;:…")
QUOTES = set('"“”„«»‘’‚`\'¡¿')


def strip_punctuation(text):
    """A word as shown without punctuation: , . ! ? ; : and quotes go; an apostrophe or a hyphen
    inside a word stays (i-check, mag-post, it's), and so do numbers (3,600, 1.5). The *marks*
    of a keyword stay. A word that is only punctuation (a dash) is kept as it is."""
    out = []
    n = len(text)
    for i, ch in enumerate(text):
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < n else ""
        if ch in STRIP_MARKS:
            if ch in ",." and prev.isdigit() and nxt.isdigit():
                out.append(ch)                   # 3,600 / 1.5
            continue
        if ch in QUOTES:
            if ch in "'’" and prev.isalpha() and nxt.isalpha():
                out.append(ch)                   # it's, Ma'am
            continue
        out.append(ch)
    cleaned = "".join(out).strip()
    return cleaned if cleaned.replace("*", "") else text


def display_text(word, style):
    text = escape(word.text)
    if getattr(style, "punctuation", "remove") != "keep":
        text = strip_punctuation(text)
    if style.uppercase:
        text = text.upper()
    elif style.lowercase:
        text = text.lower()
    if word.highlight and style.keyword_color and style.keyword_uppercase:
        text = text.upper()
    return text


def max_chars_per_line(style):
    if style.max_chars:
        return style.max_chars
    width_per_char = {"regular": 0.55, "bold": 0.58, "heavy": 0.64}.get(style.font, 0.6)
    if style.uppercase:
        width_per_char += 0.08
    return max(6, int(SAFE_WIDTH / (style.size * width_per_char)))


GLUE = {"sa", "ng", "ang", "na", "at", "and", "mga", "the", "of", "to", "kung", "para", "si", "ni", "a", "an",
        "in", "on", "for", "with", "nang", "ay", "yung"}


# number words that lead into what they count ("isang libong followers"): never split after them
LINKED = {"isang", "dalawang", "tatlong", "limang", "pitong", "walong", "sampung", "libong", "daang",
          "milyong", "isa't", "ilang"}


def _norm(text):
    return re.sub(r"[^\w'-]", "", text.lower())


def _glue(word):
    t = _norm(word.text)
    return t in GLUE or t in LINKED


def sentence_breaks(words):
    """Indexes i where a new caption sentence starts before words[i]: at . ? ! or a long pause; for
    words without punctuation (real Whisper word timestamps) also at a short pause before a capital
    letter or a clear pause - never right after "sa", "ng", "ang"... (the next word belongs to it)."""
    ends = sum(1 for w in words if re.search(r"[.?!…]$", w.text.strip("\"'")))
    plain = ends * 25 < len(words)
    out = set()
    for i in range(1, len(words)):
        prev, w = words[i - 1], words[i]
        gap = w.start - prev.end
        if gap > NEW_GROUP_PAUSE or prev.text.rstrip()[-1:] in ".?!":
            out.add(i)
        elif plain and _norm(prev.text) not in GLUE:
            first = w.text.lstrip("\"'(")
            if (first[:1].isupper() and not first.isupper() and gap >= 0.1) or gap >= 0.35:
                out.add(i)
    return out


def _fits(line, style, limit):
    return len(line) <= style.words_per_line and len(" ".join(display_text(w, style) for w in line)) <= limit


def _splits(n, parts):
    """Every way to cut n words into `parts` non-empty lines (as lists of lengths)."""
    if parts == 1:
        yield [n]
        return
    for first in range(1, n - parts + 2):
        for rest in _splits(n - first, parts - 1):
            yield [first] + rest


def _lines_of(group, style, limit):
    """The lines of one caption: as few as fit; the cut with no line ending on "ang" / "isang"...
    and the most even lengths."""
    for n in range(1, style.max_lines + 1):
        best = None
        for sizes in _splits(len(group), n):
            lines, k = [], 0
            for size in sizes:
                lines.append(group[k:k + size])
                k += size
            if not all(_fits(line, style, limit) for line in lines):
                continue
            cost = sum(20 for line in lines[:-1] if _glue(line[-1])) + (max(sizes) - min(sizes))
            if best is None or cost < best[0]:
                best = (cost, lines)
        if best:
            return best[1], best[0]
    return None


def chunk_words(words, style):
    """Group words into caption groups. Each group is a list of lines; each line a list of words.
    A caption never mixes two sentences; a sentence is split into as few, evenly filled captions
    as fit (no lone last word: "... i-check ang" / "analytics"); lines are balanced and never end on
    "ang", "sa", "ng"..."""
    limit = max_chars_per_line(style)
    breaks = sentence_breaks(words)
    sentences, cur = [], []
    for i, w in enumerate(words):
        if i in breaks and cur:
            sentences.append(cur)
            cur = []
        cur.append(w)
    if cur:
        sentences.append(cur)
    groups = []
    for sent in sentences:
        groups += _split_sentence(sent, style, limit)
    return groups


def _split_sentence(sent, style, limit):
    """The captions of one sentence: as few as fit, then the split points with the lowest cost
    (none ending on a glue word, no word alone, lengths as even as possible), trying every split."""
    n = len(sent)
    span = style.words_per_line * style.max_lines
    fits = {}

    def lines(j, i):
        if (j, i) not in fits:
            fits[(j, i)] = _lines_of(sent[j:i], style, limit) if i - j <= span else None    # (lines, cost)
        return fits[(j, i)]

    found = None
    for k in range(1, n + 1):
        if found is not None and k > found[0] + 1:
            break                                  # one caption more than needed, at most
        target = n / k
        best = {0: (0.0, [])}
        for _step in range(k):
            nxt = {}
            for j, (cost, acc) in best.items():
                for i in range(j + 1, n + 1):
                    got = lines(j, i)
                    if got is None:
                        continue
                    laid, line_cost = got
                    c = cost + (i - j - target) ** 2 + line_cost
                    if i < n and _glue(sent[i - 1]):
                        c += 20
                    if i - j == 1 and n > 1:
                        c += 8
                    if i not in nxt or c < nxt[i][0]:
                        nxt[i] = (c, acc + [laid])
            best = nxt
        if n in best:
            total = best[n][0] + 15 * k
            if found is None or total < found[1]:
                found = (k if found is None else found[0], total, best[n][1])
    return found[2] if found else [[[w]] for w in sent]


def word_tags(word, index, active, style, box_layer=False):
    """ASS override tags for one word, given which word is being spoken."""
    hidden = style.mode in ("typewriter", "pop") and index > active
    later = style.mode == "reveal" and index > active        # not said yet: faint, then ink on its word
    if box_layer:
        # Box layer: everything invisible except the box behind the spoken word.
        return r"\1a&HFF&\3a&H00&" if index == active and not hidden else r"\alpha&HFF&"
    if hidden:
        return r"\alpha&HFF&"
    tags = r"\alpha&HA8&" if later else ""
    if word.highlight and style.keyword_color:
        tags += rf"\c{ass_color(style.keyword_color)}"
    if index == active:
        if style.active_color:
            tags += rf"\c{ass_color(style.active_color)}"
        if style.active_scale != 100:
            tags += rf"\fscx{style.active_scale}\fscy{style.active_scale}"
        if style.mode == "pop":
            tags += r"\fscx55\fscy55\t(0,90,\fscx112\fscy112)\t(90,160,\fscx100\fscy100)"
    return tags


def render_group(lines, active, style, box_layer=False):
    parts, index = [], 0
    for line in lines:
        words_out = []
        for word in line:
            tags = word_tags(word, index, active, style, box_layer)
            text = display_text(word, style)
            words_out.append(f"{{{tags}}}{text}{{\\r}}" if tags else text)
            index += 1
        parts.append(" ".join(words_out))
    return r"\N".join(parts)


def placement(style, zone):
    """(ASS alignment, x, y) for a style in a zone, honouring left alignment."""
    align, x, y = ZONES[zone]
    if style.align == "left":
        return align - 1, LEFT_X, y      # 2->1, 5->4, 8->7: same row, left-anchored
    return align, x, y


def rounded_box(x0, y0, x1, y1, r):
    """ASS vector drawing commands for a rectangle with rounded corners."""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    p = lambda v: f"{v:.0f}"
    return (f"m {p(x0 + r)} {p(y0)} l {p(x1 - r)} {p(y0)} b {p(x1)} {p(y0)} {p(x1)} {p(y0)} {p(x1)} {p(y0 + r)} "
            f"l {p(x1)} {p(y1 - r)} b {p(x1)} {p(y1)} {p(x1)} {p(y1)} {p(x1 - r)} {p(y1)} "
            f"l {p(x0 + r)} {p(y1)} b {p(x0)} {p(y1)} {p(x0)} {p(y1)} {p(x0)} {p(y1 - r)} "
            f"l {p(x0)} {p(y0 + r)} b {p(x0)} {p(y0)} {p(x0)} {p(y0)} {p(x0 + r)} {p(y0)}")


def word_boxes(lines, style, zone, measurer):
    """Pixel rectangle (x0, y0, x1, y1) of every word in a caption group, in reading order."""
    align, x, y = placement(style, zone)
    size = style.size
    block = len(lines) * size            # libass line height == font size
    top = {1: y - block, 2: y - block, 4: y - block / 2, 5: y - block / 2,
           7: y, 8: y}[align]
    pad_x = style.box_padding
    boxes = []
    for row, line in enumerate(lines):
        texts = [display_text(w, style) for w in line]
        left = x if style.align == "left" else x - measurer.width(" ".join(texts)) / 2
        line_top = top + row * size
        for i, text in enumerate(texts):
            offset = measurer.width(" ".join(texts[:i]) + " ") if i else 0
            x0 = left + offset - pad_x
            x1 = left + offset + measurer.width(text) + pad_x
            boxes.append((x0, line_top + 0.10 * size, x1, line_top + 1.02 * size))
    return boxes


def card_events(lines, style, zone, measurer, start_cs, end_cs, box_name):
    """A rounded card (and its soft shadow) behind a whole caption group, for its whole time."""
    boxes = word_boxes(lines, style, zone, measurer)
    pad_y = style.size * 0.28
    x0 = min(b[0] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y0 = min(b[1] for b in boxes) - pad_y
    y1 = max(b[3] for b in boxes) + pad_y
    shape = rounded_box(x0, y0, x1, y1, style.card_radius)
    drop = style.size * 0.12
    shadow = rounded_box(x0, y0 + drop, x1, y1 + drop, style.card_radius)
    return [
        (0, start_cs, end_cs, box_name,
         rf"{{\an7\pos(0,0)\bord0\shad0\blur{style.size * 0.35:.0f}\1c&H140F0B&\1a&H9A&\p1}}{shadow}"),
        (0, start_cs, end_cs, box_name, rf"{{\an7\pos(0,0)\bord0\shad0\p1}}{shape}"),
    ]


def group_end_times(groups, last_end=None):
    """When each caption group leaves the screen (seconds).

    A group stays a moment after its last word, or until the next group starts.
    `last_end` fixes the end of the final group (a caption clip's end on the timeline).
    """
    ends = []
    for gi, lines in enumerate(groups):
        last_word = lines[-1][-1]
        end = last_word.end + HOLD_AFTER_LAST_WORD
        if gi + 1 < len(groups):
            next_start = groups[gi + 1][0][0].start
            if next_start - last_word.end < MERGE_GAP:
                end = next_start
            end = min(end, next_start)
        elif last_end is not None:
            end = last_end
        ends.append(end)
    return ends


def build_events(words, style, zone=None, measurer=None, names=("Main", "Box"), last_end=None):
    """Return a list of (layer, start_cs, end_cs, style_name, text).

    `names` are the ASS style names for the text and the word box; `last_end` (seconds)
    fixes when the final group disappears (see group_end_times).
    """
    zone = zone or style.zone
    align, x, y = placement(style, zone)
    prefix = rf"{{\an{align}\pos({x},{y})}}"
    groups = chunk_words(words, style)
    events = []
    for lines, end in zip(groups, group_end_times(groups, last_end)):
        flat = [w for line in lines for w in line]
        # Each word gets its own event, from when it is spoken until the next word.
        edges = [flat[0].start] + [w.start for w in flat[1:]] + [end]
        cs = []
        for t in edges:
            cs.append(max(int(round(t * 100)), cs[-1] if cs else 0))
        for i in range(len(flat)):
            if cs[i + 1] <= cs[i]:
                continue
            text = prefix + render_group(lines, i, style)
            events.append((1, cs[i], cs[i + 1], names[0], text))
            if style.card and measurer and i == 0:
                events += card_events(lines, style, zone, measurer, cs[0], cs[-1], names[1])
            if style.active_box and measurer:
                x0, y0, x1, y1 = word_boxes(lines, style, zone, measurer)[i]
                shape = rounded_box(x0, y0, x1, y1, style.size * 0.18)
                box_text = rf"{{\an7\pos(0,0)\bord0\shad0\p1}}{shape}"
                events.append((0, cs[i], cs[i + 1], names[1], box_text))
            elif style.active_box:
                # Font file not found for measuring: let libass draw the box per letter.
                box_text = prefix + render_group(lines, i, style, box_layer=True)
                events.append((0, cs[i], cs[i + 1], names[1], box_text))
    return events


def font_of(style, fonts):
    """(family, bold) of a caption style: its own family (e.g. a serif) or the project's font for
    its weight (regular / bold / heavy)."""
    family, bold = fonts[style.font]
    return (style.family, bold) if getattr(style, "family", None) else (family, bold)


def style_line(name, style: CaptionStyle, fonts, box=False, box_color=None, padding=None):
    font_name, bold = font_of(style, fonts)
    if box:
        border_style, outline = 3, padding
        outline_color = ass_color(box_color)
        shadow = 0
    else:
        border_style, outline = 1, style.outline
        outline_color = ass_color(style.outline_color)
        shadow = style.shadow
    back = ass_color(style.shadow_color, style.shadow_alpha)
    return (
        f"Style: {name},{font_name},{style.size},{ass_color(style.color)},&H000000FF,"
        f"{outline_color},{back},{-1 if bold else 0},0,0,0,100,100,0,0,"
        f"{border_style},{outline},{shadow},2,{SAFE_LEFT},{SAFE_RIGHT},0,1"
    )


def style_lines(style, fonts, fonts_folder=None, names=("Main", "Box")):
    """ASS [V4+ Styles] lines for one caption style, plus the text measurer for word boxes."""
    measurer = None
    if style.card:
        family, bold = font_of(style, fonts)
        font_file = find_font_file(family, bold, fonts_folder or "")
        if font_file:
            measurer = TextMeasurer(font_file, style.size)
            card_style = CaptionStyle(0, "card", "", color=style.card, outline=0)
            return [style_line(names[0], style, fonts),
                    style_line(names[1], card_style, fonts)], measurer
        # no font file to measure with: a square card drawn by libass behind the text
        return [style_line(names[0], style, fonts, box=True, box_color=style.card,
                           padding=style.box_padding)], None
    lines = [style_line(names[0], style, fonts, box=style.box,
                        box_color=style.box_color, padding=style.box_padding)]
    if style.active_box:
        family, bold = font_of(style, fonts)
        font_file = find_font_file(family, bold, fonts_folder or "")
        if font_file:
            measurer = TextMeasurer(font_file, style.size)
            box_style = CaptionStyle(0, "box", "", color=style.active_box, outline=0)
            lines.append(style_line(names[1], box_style, fonts))
        else:
            lines.append(style_line(names[1], style, fonts, box=True,
                                    box_color=style.active_box, padding=style.box_padding))
    return lines, measurer


def ass_document(styles, events):
    """Full .ass file text from style lines and (layer, start_cs, end_cs, style, text) events."""
    header = "\n".join([
        "[Script Info]",
        "; Made by the auto video editor",
        "ScriptType: v4.00+",
        f"PlayResX: {WIDTH}",
        f"PlayResY: {HEIGHT}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    lines = [
        f"Dialogue: {layer},{ass_time(s)},{ass_time(e)},{name},,0,0,0,,{text}"
        for layer, s, e, name, text in events
    ]
    return header + "\n" + "\n".join(lines) + "\n"


def build_ass(words, style, fonts, zone=None, fonts_folder=None):
    """Return the full text of an .ass subtitle file.

    `fonts` maps "regular"/"bold"/"heavy" to (font family name, bold flag).
    """
    styles, measurer = style_lines(style, fonts, fonts_folder)
    return ass_document(styles, build_events(words, style, zone, measurer))


def fonts_from_config(captions_cfg):
    return {
        "regular": (captions_cfg.get("font_regular", "Inter"), False),
        "bold": (captions_cfg.get("font_bold", "Inter"), True),
        "heavy": (captions_cfg.get("font_heavy", "Inter Black"), True),
    }
