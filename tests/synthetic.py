"""Make a short fake 'talking' video + matching transcript for tests (no camera or API needed)."""

import json
import subprocess
from pathlib import Path

# Tone bursts stand in for speech; the gaps between them are silences.
SPEECH = [(0.5, 2.0), (2.9, 4.2), (4.35, 4.65), (5.3, 7.2)]
WORDS = [
    ("Kumusta", 0.5, 0.9), ("kayo", 0.95, 1.3), ("mga", 1.35, 1.5), ("kaibigan!", 1.55, 2.0),
    ("Ngayon", 2.9, 3.3), ("pag-usapan", 3.35, 3.8), ("natin", 3.85, 4.2),
    ("uhm", 4.35, 4.65),
    ("ang", 5.3, 5.45), ("*GitHub*", 5.5, 6.0), ("for", 6.05, 6.3), ("500", 6.35, 6.7),
    ("pesos.", 6.75, 7.2),
]
DURATION = 8.0


def make_video(path, width=720, height=1280, duration=DURATION):
    volume = "+".join(f"between(t,{s},{e})" for s, e in SPEECH)
    audio = f"aevalsrc='0.5*sin(2*PI*220*t)*({volume})':s=48000:d={duration}"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=s={width}x{height}:r=30:d={duration}",
         "-f", "lavfi", "-i", audio,
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return Path(path)


def make_transcript(path):
    data = {"language": "tl",
            "words": [{"word": w, "start": s, "end": e} for w, s, e in WORDS]}
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return Path(path)


def make_image(path, color="orange", size="600x400"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color={color}:s={size}:d=1", "-frames:v", "1", str(path)], check=True)
    return Path(path)
