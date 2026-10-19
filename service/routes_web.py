"""The web app (PWA) at /app/: the files built from web/ (`npm run build` there), served by the API
so it shares the API's origin (the session cookie never leaves this site, no CORS needed).

Its Content-Security-Policy allows only this site (plus the captcha provider when one is set);
hashed files under /app/assets/ are cached for a year, everything else is checked every time
(index.html, the service worker and the manifest).
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from .api import ApiError

router = APIRouter()
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"
CAPTCHA_ORIGINS = {"turnstile": "https://challenges.cloudflare.com",
                   "hcaptcha": "https://hcaptcha.com https://*.hcaptcha.com"}
TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml",
         ".png": "image/png", ".webmanifest": "application/manifest+json", ".json": "application/json",
         ".woff2": "font/woff2", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8"}


def web_dir(settings):
    return Path(settings.web_dir).resolve() if settings.web_dir else DEFAULT_DIR


def csp(settings):
    extra = CAPTCHA_ORIGINS.get(settings.captcha_provider, "")
    return ("default-src 'self'; "
            f"script-src 'self' {extra}; frame-src {extra or chr(39) + 'none' + chr(39)}; "
            f"connect-src 'self' {extra}; img-src 'self' data: blob:; media-src 'self' blob:; "
            "style-src 'self'; font-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'").replace("  ", " ")


@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/", status_code=302)


@router.get("/app", include_in_schema=False)
def app_no_slash():
    return RedirectResponse("/app/", status_code=301)


@router.get("/app/{path:path}", include_in_schema=False)
def app_file(request: Request, path: str = ""):
    s = request.app.state.settings
    root = web_dir(s)
    index = root / "index.html"
    if not index.exists():
        raise ApiError(404, "not_built", "The web app is not built (run npm ci && npm run build in web/).")
    target = (root / path).resolve() if path else index
    if not target.is_relative_to(root) or not target.is_file():
        if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
            raise ApiError(404, "not_found", "No such file.")
        target = index                                   # an app page: the app finds its way from the URL
    headers = {"Content-Security-Policy": csp(s),
               "Cache-Control": "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"}
    if target.name == "sw.js":
        headers["Service-Worker-Allowed"] = "/app/"
    return FileResponse(target, media_type=TYPES.get(target.suffix, "application/octet-stream"), headers=headers)
