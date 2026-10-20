"""Small sound effects made on your PC with FFmpeg (no downloads, nobody else's sounds, so they are
safe to ship and to post): pop, soft pop, ding, whoosh in / out, tick, typing click, camera
shutter, rise and impact - for cards coming in and going, list items ticking, a search bar typing,
screenshots, countdowns and the black-and-white "before" moment.

Your own sounds win: a file named like the sound in assets/sfx (whoosh.wav, tick.mp3, shutter.ogg...)
is used instead of the made one."""

import os
import subprocess
from pathlib import Path

from . import PROJECT_DIR
from .errors import EditorError
from .ffmpeg_tools import find_tool

VERSION = 3            # bump when a sound's recipe changes (the made files are cached)
# name: (FFmpeg aevalsrc expression in t, seconds, extra audio filters)
SOUNDS = {
    # a short rising blip
    "pop": ("0.6*sin(2*PI*(400+1800*t)*t)*exp(-28*t)", 0.18, ""),
    # a rounder, quieter pop for words popping in
    "soft_pop": ("0.5*sin(2*PI*(260+700*t)*t)*exp(-32*t)", 0.16, ",lowpass=f=3000"),
    # two bell-like partials
    "ding": ("0.45*(sin(2*PI*1320*t)+0.6*sin(2*PI*1980*t))*exp(-6*t)", 0.9, ""),
    # filtered noise that swells and fades (a card coming in)
    "whoosh": ("0.8*(random(0)*2-1)*sin(PI*t/0.45)", 0.45, ",lowpass=f=2500,highpass=f=300"),
    # a shorter, darker whoosh (a card going)
    "whoosh_out": ("1.0*(random(0)*2-1)*sin(PI*t/0.32)*(1-t/0.32)", 0.32, ",lowpass=f=1600,highpass=f=250"),
    "tick": ("0.7*sin(2*PI*2400*t)*exp(-90*t)", 0.06, ""),
    # one key of a keyboard
    "type": ("0.55*(random(0)*2-1)*exp(-160*t)+0.25*sin(2*PI*3100*t)*exp(-220*t)", 0.04, ",highpass=f=1200"),
    # a camera shutter: two quick clicks
    "shutter": ("0.75*(random(0)*2-1)*(exp(-140*t)+0.8*exp(-140*(t-0.09))*gte(t,0.09))", 0.22,
                ",highpass=f=900,lowpass=f=7000"),
    # a rising swell into the black-and-white moment
    "rise": ("(0.35*(random(0)*2-1)+0.25*sin(2*PI*(180+500*t)*t))*pow(t/0.9,2)", 0.9,
             ",lowpass=f=4000,highpass=f=120"),
    # a low, soft impact when the colour comes back
    "impact": ("0.85*sin(2*PI*(70-30*t)*t)*exp(-7*t)+0.3*(random(0)*2-1)*exp(-35*t)", 0.6, ",lowpass=f=900"),
}
OWN_EXTENSIONS = (".wav", ".mp3", ".ogg", ".m4a", ".flac")


def folder():
    override = os.environ.get("AUTOEDIT_SFX_CACHE")
    return Path(override) if override else PROJECT_DIR / "work" / "cache" / "sfx"


def own_folder():
    override = os.environ.get("AUTOEDIT_OWN_SFX")
    return Path(override) if override else PROJECT_DIR / "assets" / "sfx"


def own_sound(name):
    """Your own file for a sound (assets/sfx/<name>.wav / .mp3 ...), or None."""
    base = own_folder()
    for ext in OWN_EXTENSIONS:
        path = base / f"{name}{ext}"
        if path.is_file():
            return path
    return None


def sound_file(name, own=True):
    """The file of a sound: yours from assets/sfx when there is one, else the made one (made the
    first time it is needed)."""
    if name not in SOUNDS:
        raise EditorError(f"Unknown sound '{name}'. Choose: {', '.join(SOUNDS)}")
    if own:
        mine = own_sound(name)
        if mine:
            return mine
    out = folder() / f"{name}-v{VERSION}.wav"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    expr, seconds, extra = SOUNDS[name]
    part = out.with_name(out.stem + ".part.wav")
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=48000:d={seconds}", "-af", f"afade=t=out:st={seconds * 0.8:.3f}:"
                    f"d={seconds * 0.2:.3f}{extra}", "-ac", "2", str(part)], check=True)
    os.replace(part, out)
    return out
