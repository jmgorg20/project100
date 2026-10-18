"""Two-step sign-in with an authenticator app (TOTP, RFC 6238: 6 digits, 30 seconds, SHA-1, the
format every authenticator app reads), and one-time recovery codes."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP, DIGITS, WINDOW = 30, 6, 1          # accept the previous and next code too (clock drift)


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def code_at(secret, at=None):
    return _code(secret, int((time.time() if at is None else at) // STEP))


def verify(secret, code, last_step=None, at=None):
    """The time step the code belongs to, or None. A step at or before `last_step` is refused (a
    code works only once)."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = int((time.time() if at is None else at) // STEP)
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if last_step is not None and step <= int(last_step):
            continue
        if hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def provisioning_uri(secret, account, issuer="AutoEdit"):
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def recovery_codes(n=10):
    """One-time codes for when the phone is lost: xxxxx-xxxxx (lower case letters and digits)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(5)) + "-" + "".join(secrets.choice(alphabet) for _ in range(5))
            for _ in range(n)]


def normalize_recovery(code):
    return "".join(ch for ch in str(code or "").lower() if ch.isalnum())
