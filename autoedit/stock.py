"""Free stock pictures and videos (Pexels, Pixabay) with YOUR free API key.

Keys come from the environment (PEXELS_API_KEY, PIXABAY_API_KEY): the desktop app keeps them
encrypted and hands them to the engine; on the command line put them in .env. They are never
printed. No key = this source is skipped.

Every result carries who made it, the page to credit, and the licence. Downloads are kept in
work/broll/stock, so the same file is fetched once.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import EditorError
from .transcribe import load_dotenv

TIMEOUT = 30
LICENSES = {
    "pexels": ("Pexels License", "https://www.pexels.com/license/"),
    "pixabay": ("Pixabay Content License", "https://pixabay.com/service/license-summary/"),
}


@dataclass
class StockItem:
    provider: str
    id: str
    kind: str                 # "image" or "video"
    url: str                  # the file to download
    page: str                 # the page to credit
    author: str
    width: int = 0
    height: int = 0
    duration: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def credit(self):
        name = "Pexels" if self.provider == "pexels" else "Pixabay"
        what = "Video" if self.kind == "video" else "Photo"
        return f"{what} by {self.author} on {name} ({self.page})"


def key_for(provider):
    load_dotenv()
    name = {"pexels": "PEXELS_API_KEY", "pixabay": "PIXABAY_API_KEY"}[provider]
    key = os.environ.get(name, "").strip()
    return key if key and not key.startswith("your_") else None


def available():
    """Which stock sources have a key."""
    return [p for p in ("pexels", "pixabay") if key_for(p)]


def _get(url, provider, **kwargs):
    import requests
    try:
        r = requests.get(url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise EditorError(f"Could not reach {provider.title()} (check your internet): {exc}")
    if r.status_code in (401, 403):
        raise EditorError(f"{provider.title()} refused the API key ({r.status_code}). "
                          "Check it in Settings.")
    if r.status_code == 429:
        raise EditorError(f"{provider.title()} says you hit its free limit (429). Try again later.")
    if r.status_code != 200:
        raise EditorError(f"{provider.title()} search failed ({r.status_code}): {r.text[:200]}")
    return r.json()


def _vertical_first(items):
    """Portrait files first (they fill a 9:16 frame), then the rest."""
    return sorted(items, key=lambda i: (not (i.height > i.width), -(i.height or 0)))


def search_pexels(query, kind, key, per_page=10):
    if kind == "video":
        data = _get("https://api.pexels.com/videos/search", "pexels",
                    params={"query": query, "orientation": "portrait", "per_page": per_page},
                    headers={"Authorization": key})
        out = []
        for v in data.get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("link") and f.get("height")]
            portrait = [f for f in files if f["height"] >= f.get("width", 0)] or files
            # The smallest file that is still at least 1280 tall (else the biggest there is).
            big = sorted((f for f in portrait if f["height"] >= 1280), key=lambda f: f["height"])
            pick = big[0] if big else max(portrait, key=lambda f: f["height"], default=None)
            if pick:
                out.append(StockItem("pexels", str(v["id"]), "video", pick["link"],
                                     v.get("url", ""), (v.get("user") or {}).get("name", "unknown"),
                                     pick.get("width", 0), pick["height"],
                                     float(v.get("duration", 0))))
        return _vertical_first(out)
    data = _get("https://api.pexels.com/v1/search", "pexels",
                params={"query": query, "orientation": "portrait", "per_page": per_page},
                headers={"Authorization": key})
    return _vertical_first([
        StockItem("pexels", str(p["id"]), "image", (p.get("src") or {}).get("portrait")
                  or (p.get("src") or {}).get("large2x") or (p.get("src") or {}).get("original"),
                  p.get("url", ""), p.get("photographer", "unknown"), p.get("width", 0),
                  p.get("height", 0))
        for p in data.get("photos", []) if p.get("src")])


def search_pixabay(query, kind, key, per_page=10, illustration=False):
    if kind == "video":
        data = _get("https://pixabay.com/api/videos/", "pixabay",
                    params={"key": key, "q": query, "per_page": per_page, "safesearch": "true",
                            "video_type": "animation" if illustration else "film"})
        out = []
        for h in data.get("hits", []):
            vids = h.get("videos") or {}
            pick = next((vids[s] for s in ("large", "medium", "small")
                         if (vids.get(s) or {}).get("url")), None)
            if pick:
                out.append(StockItem("pixabay", str(h["id"]), "video", pick["url"],
                                     h.get("pageURL", ""), h.get("user", "unknown"),
                                     pick.get("width", 0), pick.get("height", 0),
                                     float(h.get("duration", 0))))
        return _vertical_first(out)
    data = _get("https://pixabay.com/api/", "pixabay",
                params={"key": key, "q": query, "per_page": per_page, "safesearch": "true",
                        "orientation": "vertical",
                        "image_type": "illustration" if illustration else "photo"})
    return _vertical_first([
        StockItem("pixabay", str(h["id"]), "image", h.get("largeImageURL") or h.get("webformatURL"),
                  h.get("pageURL", ""), h.get("user", "unknown"), h.get("imageWidth", 0),
                  h.get("imageHeight", 0))
        for h in data.get("hits", []) if h.get("largeImageURL") or h.get("webformatURL")])


def search(query, kind, style="realistic", exclude=()):
    """Stock results for `query`, from every source with a key (nothing without keys).

    Pexels only has photos and real footage, so it is used for the "realistic" style; Pixabay
    also has illustrations (cartoon, sketch...) and animations.
    """
    illustration = style not in ("realistic", None, "")
    results = []
    for provider in available():
        if provider == "pexels" and illustration:
            continue
        key = key_for(provider)
        found = search_pexels(query, kind, key) if provider == "pexels" else \
            search_pixabay(query, kind, key, illustration=illustration)
        results += [r for r in found if f"{r.provider}-{r.id}" not in exclude]
    return results


def download(item, folder):
    """Download a stock file once (kept in `folder`). Returns its path."""
    import requests
    ext = Path(re.sub(r"[?#].*$", "", item.url)).suffix.lower()
    if ext not in (".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp"):
        ext = ".mp4" if item.kind == "video" else ".jpg"
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{item.provider}-{item.id}{ext}"
    if path.exists() and path.stat().st_size > 0:
        return path
    part = path.with_name(path.name + ".part")
    try:
        with requests.get(item.url, stream=True, timeout=TIMEOUT) as r:
            if r.status_code != 200:
                raise EditorError(f"Could not download from {item.provider.title()} "
                                  f"({r.status_code}).")
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        os.replace(part, path)
    except requests.RequestException as exc:
        raise EditorError(f"Could not download from {item.provider.title()}: {exc}")
    finally:
        if part.exists():
            part.unlink()
    return path
