"""`python editor.py styles` - draw every caption style on a sample frame (PNG files)."""

import shutil
from pathlib import Path

from . import PROJECT_DIR
from .captions import build_ass, fonts_from_config
from .ffmpeg_tools import check_ffmpeg, run_ffmpeg
from .highlight import mark_keywords
from .styles import list_styles, get_style
from .words import make_word

# Sample Taglish sentence with Filipino characters (ñ) and keywords.
SAMPLE = ("Grabe ang bilis ng internet dito sa Parañaque! 500 Mbps lang for 1,299 pesos "
          "per month. Check niyo sa *GitHub* ko.")
SAMPLE_ACTIVE_WORD = 4   # the word that is "being spoken" in the picture ("internet")


def sample_words():
    words, t = [], 0.2
    for text in SAMPLE.split():
        words.append(make_word(text, t, t + 0.3))
        t += 0.36
    return words


def copy_fonts(fonts_dir, dest):
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(fonts_dir)
    if not src.is_absolute():
        src = PROJECT_DIR / src
    if src.is_dir():
        for f in src.iterdir():
            if f.suffix.lower() in (".ttf", ".otf", ".ttc"):
                shutil.copy2(f, dest / f.name)


def render_previews(cfg, out_dir=None, background=None, guides=True):
    check_ffmpeg()
    out_dir = Path(out_dir or PROJECT_DIR / cfg["output"]["folder"] / "style_previews")
    out_dir.mkdir(parents=True, exist_ok=True)
    work = PROJECT_DIR / cfg["work_folder"] / "style_previews"
    work.mkdir(parents=True, exist_ok=True)
    copy_fonts(cfg["captions"]["fonts_folder"], work / "fonts")
    fonts = fonts_from_config(cfg["captions"])

    words = mark_keywords(sample_words(), cfg["highlight"])
    active = words[SAMPLE_ACTIVE_WORD]
    snapshot_time = active.start + 0.25   # after the pop animation has finished

    if background:
        bg_input = ["-ss", "1", "-i", str(Path(background).resolve())]
        bg_filter = ("scale=1080:1920:force_original_aspect_ratio=increase,"
                     "crop=1080:1920,setsar=1,fps=30")
    else:
        bg_input = ["-f", "lavfi", "-i",
                    "gradients=s=1080x1920:c0=0x4b6c8a:c1=0xc9a27e:x0=0:y0=0:x1=1080:y1=1920"
                    ":nb_colors=2:r=30:d=10"]
        # A simple "person" shape so you can judge where captions sit.
        bg_filter = ("drawbox=x=340:y=420:w=400:h=480:color=0xe0b8a0:t=fill,"
                     "drawbox=x=220:y=900:w=640:h=1020:color=0x2d3e50:t=fill")
    if guides:
        # Red = where TikTok/Reels put their buttons and text (keep captions out).
        bg_filter += (",drawbox=x=0:y=1536:w=1080:h=384:color=red@0.25:t=fill"
                      ",drawbox=x=910:y=0:w=170:h=1536:color=red@0.18:t=fill")

    made = []
    for style in list_styles():
        style = get_style(style.name, cfg["highlight"].get("color"))
        ass_name = f"{style.number:02d}_{style.name}.ass"
        (work / ass_name).write_text(build_ass(words, style, fonts, fonts_folder=work / "fonts"), encoding="utf-8")
        png = out_dir / f"{style.number:02d}_{style.name}.png"
        run_ffmpeg(
            bg_input + ["-vf", f"{bg_filter},subtitles={ass_name}:fontsdir=fonts",
                        "-ss", f"{snapshot_time:.2f}", "-frames:v", "1", str(png.resolve())],
            f"style {style.number}: {style.name}", cwd=work, show_progress=False,
        )
        made.append(png)
    return made
