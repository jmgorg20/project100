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


COLOR_SECONDS = ["red", "green", "blue", "white"]   # colour of each second of make_color_video


def make_color_video(path, width=720, height=1280):
    """4 s video: red, green, blue, white (one second each), with a steady 440 Hz tone."""
    sources = "".join(f"color=c={c}:s={width}x{height}:r=30:d=1[c{i}];"
                      for i, c in enumerate(COLOR_SECONDS))
    joined = "".join(f"[c{i}]" for i in range(len(COLOR_SECONDS)))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-filter_complex",
         f"{sources}{joined}concat=n={len(COLOR_SECONDS)}:v=1:a=0[v];"
         f"sine=f=440:r=48000:d={len(COLOR_SECONDS)}[a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
        check=True,
    )
    return Path(path)


def make_tone(path, frequency=880, duration=2.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=f={frequency}:r=48000:d={duration}", str(path)], check=True)
    return Path(path)


def pixels(video, frames, x, y):
    """RGB colour of pixel (x, y) in each of the given frame numbers."""
    pick = "+".join(f"eq(n,{n})" for n in frames)
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf",
         f"select='{pick}',format=rgb24,crop=1:1:{x}:{y}", "-vsync", "0",
         "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return [tuple(out[i:i + 3]) for i in range(0, len(out), 3)]


def pcm(media, rate=8000):
    """Mono 16-bit samples of the media's sound."""
    import array
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-ac", "1", "-ar", str(rate),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return array.array("h", out)


def make_marker_video(path, width=720, height=1280, duration=4.0, marker=(0.3, 0.6), size=0.04):
    """A dark picture with one white square at `marker` (0-1 of the frame), and silence: where a
    tracked effect should land is visible in the picture."""
    mx, my = int(marker[0] * width), int(marker[1] * height)
    side = max(4, int(size * width))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"color=c=0x101018:s={width}x{height}:r=30:d={duration},"
         f"drawbox=x={mx - side // 2}:y={my - side // 2}:w={side}:h={side}:color=white:t=fill",
         "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", str(duration),
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
        check=True)
    return Path(path)
