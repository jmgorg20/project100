"""Small sound effects made on your PC with FFmpeg (no downloads, nobody else's sounds):
pop, ding, whoosh and tick, for list items, countdowns and transitions."""

import os
import subprocess
from pathlib import Path

from . import PROJECT_DIR
from .errors import EditorError
from .ffmpeg_tools import find_tool

SOUNDS = {
    # a short rising blip
    "pop": ("0.6*sin(2*PI*(400+1800*t)*t)*exp(-28*t)", 0.18),
    # two bell-like partials
    "ding": ("0.45*(sin(2*PI*1320*t)+0.6*sin(2*PI*1980*t))*exp(-6*t)", 0.9),
    # filtered noise that swells and fades
    "whoosh": ("0.5*(random(0)*2-1)*sin(PI*t/0.45)", 0.45),
    "tick": ("0.7*sin(2*PI*2400*t)*exp(-90*t)", 0.06),
}


def folder():
    override = os.environ.get("AUTOEDIT_SFX_CACHE")
    return Path(override) if override else PROJECT_DIR / "work" / "cache" / "sfx"


def sound_file(name):
    """The WAV file of a built-in sound (made the first time it is needed)."""
    if name not in SOUNDS:
        raise EditorError(f"Unknown sound '{name}'. Choose: {', '.join(SOUNDS)}")
    out = folder() / f"{name}.wav"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    expr, seconds = SOUNDS[name]
    extra = ",lowpass=f=2500,highpass=f=300" if name == "whoosh" else ""
    part = out.with_name(out.stem + ".part.wav")
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=48000:d={seconds}", "-af", f"afade=t=out:st={seconds * 0.8:.3f}:"
                    f"d={seconds * 0.2:.3f}{extra}", "-ac", "2", str(part)], check=True)
    os.replace(part, out)
    return out
