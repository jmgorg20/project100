"""Sign in with Google (OpenID Connect, authorization code flow with PKCE).

1. /v1/auth/oauth/google/start: a one-time `state` (kept in the database, and in a short cookie in
   this browser, so nobody can finish a sign-in that this browser did not start) and a PKCE
   verifier; redirect to Google.
2. /v1/auth/oauth/google/callback: check the state and the cookie, exchange the code (with the
   client secret and the verifier) over HTTPS, read the verified email from Google's userinfo
   endpoint (fetched directly from Google over TLS with the access token, so no ID token signature
   needs checking). Only an email Google marks verified is used.

Endpoints and keys come from settings (SERVICE_OAUTH_GOOGLE_CLIENT_ID / _SECRET); more providers
can be added to PROVIDERS with the same fields.
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "settings": "oauth_google",
    },
}


class OAuthError(Exception):
    pass


def configured(settings):
    return [name for name, p in PROVIDERS.items() if getattr(settings, p["settings"] + "_client_id", "")]


def credentials(settings, provider):
    p = PROVIDERS.get(provider)
    if not p or provider not in configured(settings):
        raise OAuthError("This sign-in method is not set up.")
    return p, getattr(settings, p["settings"] + "_client_id"), getattr(settings, p["settings"] + "_client_secret")


def redirect_uri(settings, provider):
    return f"{settings.public_url.rstrip('/')}/v1/auth/oauth/{provider}/callback"


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def authorize_url(settings, provider, state, challenge):
    p, client_id, _ = credentials(settings, provider)
    return p["authorize"] + "?" + urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri(settings, provider),
        "scope": p["scope"], "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "prompt": "select_account"})


def fetch_profile(settings, http, provider, code, verifier):
    """The user's profile ({sub, email, email_verified, name}) for an authorization code."""
    p, client_id, secret = credentials(settings, provider)
    if not isinstance(code, str) or not 1 <= len(code) <= 2048:
        raise OAuthError("The sign-in did not finish.")
    try:
        r = http.post(p["token"], data={"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                        "client_secret": secret, "redirect_uri": redirect_uri(settings, provider),
                                        "code_verifier": verifier}, timeout=15, allow_redirects=False)
        if r.status_code != 200:
            raise OAuthError("The sign-in was refused by the provider.")
        access = r.json().get("access_token")
        if not access:
            raise OAuthError("The provider sent no access token.")
        r = http.get(p["userinfo"], headers={"Authorization": f"Bearer {access}"}, timeout=15, allow_redirects=False)
        if r.status_code != 200:
            raise OAuthError("The provider did not send the profile.")
        info = r.json()
    except OAuthError:
        raise
    except Exception as exc:
        raise OAuthError(f"Could not reach the sign-in provider ({exc.__class__.__name__}).")
    if not isinstance(info, dict):
        raise OAuthError("The provider sent a bad profile.")
    verified = info.get("email_verified")
    return {"sub": str(info.get("sub") or ""), "email": info.get("email"),
            "email_verified": verified is True or verified == "true", "name": info.get("name")}
