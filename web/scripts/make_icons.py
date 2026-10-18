"""Make the web app's icons (public/icons/*.png): a play mark on the app's dark background.
Run: python web/scripts/make_icons.py (needs Pillow)."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
BG, ACCENT = (17, 19, 24), (255, 92, 92)


def icon(size, safe=1.0):
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    pad = size * (1 - 0.62 * safe) / 2                   # maskable icons keep the mark inside the safe zone
    box = [pad, pad, size - pad, size - pad]
    d.rounded_rectangle(box, radius=size * 0.12 * safe, fill=ACCENT)
    w = box[2] - box[0]
    cx, cy = size / 2 + w * 0.05, size / 2
    r = w * 0.26
    d.polygon([(cx - r * 0.8, cy - r), (cx - r * 0.8, cy + r), (cx + r, cy)], fill=BG)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192).save(OUT / "icon-192.png", optimize=True)
    icon(512).save(OUT / "icon-512.png", optimize=True)
    icon(512, safe=0.8).save(OUT / "maskable-512.png", optimize=True)
    print("icons written to", OUT)
