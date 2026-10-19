"""Bot protection for sign-up, password reset and repeated failed sign-ins: Cloudflare Turnstile or
hCaptcha (SERVICE_CAPTCHA_PROVIDER + SERVICE_CAPTCHA_SECRET; off when empty). The web app shows
the widget with SERVICE_CAPTCHA_SITE_KEY and sends its answer as `captcha`."""

VERIFY_URLS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "hcaptcha": "https://api.hcaptcha.com/siteverify",
}


def enabled(settings):
    return bool(settings.captcha_provider)


def verify(settings, http, answer, ip=None):
    """True when the captcha answer is good (always True when the captcha is off). A provider that
    cannot be reached counts as a failure (fail closed)."""
    if not enabled(settings):
        return True
    if not isinstance(answer, str) or not answer or len(answer) > 4096:
        return False
    data = {"secret": settings.captcha_secret, "response": answer}
    if ip:
        data["remoteip"] = ip
    try:
        r = http.post(VERIFY_URLS[settings.captcha_provider], data=data, timeout=10)
        return r.status_code == 200 and r.json().get("success") is True
    except Exception:
        return False
