"""Keys, tokens and signatures.

- API keys and worker tokens: `<kind>_<prefix>_<secret>`; only an HMAC of the secret (keyed with
  SERVICE_SECRET_KEY) is stored, the full key is shown once. A database leak does not reveal keys.
- Job payloads are signed with the service's Ed25519 private key; workers verify them with the
  public key before running anything (a worker never runs a job the service did not send).
- File links are signed (HMAC) and expire after SERVICE_FILE_LINK_MINUTES.
- Webhook secrets are stored encrypted (Fernet, a key derived from SERVICE_SECRET_KEY).
- Webhook bodies are signed: `X-AutoEdit-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "t.body")>`.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

KEY_KINDS = ("ak", "wk", "ss")   # ak = client API key, wk = worker token, ss = user session


class SecurityError(Exception):
    pass


def new_id(prefix=""):
    return prefix + secrets.token_hex(12)


def _mac(secret_key, data):
    return hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()


def make_key(kind, secret_key):
    """A new key: (full key to show once, prefix, hash to store)."""
    if kind not in KEY_KINDS:
        raise SecurityError(f"unknown key kind {kind}")
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return f"{kind}_{prefix}_{secret}", prefix, _mac(secret_key, f"{kind}:{prefix}:{secret}")


def parse_key(full):
    """(kind, prefix, secret) or None."""
    parts = str(full or "").strip().split("_", 2)
    if len(parts) != 3 or parts[0] not in KEY_KINDS or len(parts[1]) != 12 or len(parts[2]) < 20:
        return None
    if not all(c in "0123456789abcdef" for c in parts[1]):
        return None
    return parts[0], parts[1], parts[2]


def key_matches(full, stored_hash, secret_key):
    parsed = parse_key(full)
    if parsed is None:
        return False
    kind, prefix, secret = parsed
    return hmac.compare_digest(_mac(secret_key, f"{kind}:{prefix}:{secret}"), stored_hash or "")


def hash_token(secret_key, purpose, token):
    """The stored form of a one-time token (email links, invitations, invite codes)."""
    return _mac(secret_key, f"{purpose}:{token}")


def token_matches(given, expected):
    """Constant-time comparison of a shared token (the admin token)."""
    if not given or not expected:
        return False
    return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(expected.encode()).digest())


# ---------------------------------------------------------------- job payload signing (Ed25519)

def new_signing_key():
    """PEM text of a new Ed25519 private key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def load_signing_key(pem):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(pem.encode() if isinstance(pem, str) else pem, password=None)


def public_key_pem(private_key):
    from cryptography.hazmat.primitives import serialization
    return private_key.public_key().public_bytes(serialization.Encoding.PEM,
                                                 serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_payload(private_key, payload):
    return base64.b64encode(private_key.sign(canonical(payload))).decode()


def verify_payload(public_pem, payload, signature):
    """True when `signature` is the service's signature of `payload`."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    try:
        key = serialization.load_pem_public_key(public_pem.encode() if isinstance(public_pem, str) else public_pem)
        key.verify(base64.b64decode(signature), canonical(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# ---------------------------------------------------------------- signed file links

def sign_link(secret_key, kind, object_id, expires_at):
    exp = int(expires_at)
    return f"{exp}.{_mac(secret_key, f'link:{kind}:{object_id}:{exp}')}"


def check_link(secret_key, kind, object_id, token, now=None):
    try:
        exp_text, mac = str(token).split(".", 1)
        exp = int(exp_text)
    except ValueError:
        return False
    if exp < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(mac, _mac(secret_key, f"link:{kind}:{object_id}:{exp}"))


# ---------------------------------------------------------------- stored secrets (webhook secrets)

def _fernet(secret_key):
    from cryptography.fernet import Fernet
    raw = hashlib.sha256(("fernet:" + secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt(secret_key, text):
    return _fernet(secret_key).encrypt(text.encode()).decode()


def decrypt(secret_key, token):
    return _fernet(secret_key).decrypt(token.encode()).decode()


# ---------------------------------------------------------------- webhook signatures

def webhook_signature(secret, body, timestamp=None):
    t = int(timestamp if timestamp is not None else time.time())
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify_webhook(secret, body, header, tolerance=300, now=None):
    """For the clients receiving webhooks (documented in docs/service.md)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((now if now is not None else time.time()) - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))
