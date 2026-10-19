"""Password hashing (scrypt, from the standard library) and the password rules.

Stored form: `scrypt$<log2 n>$<r>$<p>$<salt b64>$<hash b64>`; the cost is in the string, so it can
be raised later and old hashes still check (and are upgraded at the next sign-in).
"""

import base64
import hashlib
import hmac
import secrets

LOG_N, R, P = 15, 8, 1                    # 32 MB of memory per hash: slow for guessing, fine for sign-in
MIN_LENGTH, MAX_LENGTH = 10, 200
# The most common passwords of 10+ characters (and the obvious ones for this service).
COMMON = {
    "1234567890", "0123456789", "12345678910", "qwertyuiop", "1q2w3e4r5t", "password12", "password123",
    "password1234", "iloveyou12", "qwerty1234", "1qaz2wsx3edc", "abcdefghij", "abcd123456", "a123456789",
    "123456789a", "1234567890a", "aaaaaaaaaa", "1111111111", "0000000000", "passw0rd123", "welcome123",
    "letmein123", "football12", "baseball12", "sunshine12", "princess12", "iloveyou123", "qwertyuiop1",
    "123qweasdzxc", "zxcvbnm123", "asdfghjkl1", "michael123", "superman12", "autoedit123", "autoedit2026",
    "mahalkita12", "iloveyou143", "password143", "philippines", "pilipinas12",
}


class PasswordError(Exception):
    pass


def check_policy(password, email=""):
    """Raises PasswordError with a plain reason when the password is too weak."""
    if not isinstance(password, str):
        raise PasswordError("A password is needed.")
    if len(password) < MIN_LENGTH:
        raise PasswordError(f"Use at least {MIN_LENGTH} characters (a short sentence is easy to remember).")
    if len(password) > MAX_LENGTH:
        raise PasswordError(f"Use at most {MAX_LENGTH} characters.")
    low = password.lower()
    if low in COMMON or len(set(low)) < 4:
        raise PasswordError("This password is too common; choose another.")
    local = (email or "").split("@")[0].lower()
    if local and len(local) >= 4 and local in low:
        raise PasswordError("The password must not contain your email name.")


def hash_password(password, log_n=LOG_N):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=1 << log_n, r=R, p=P, maxmem=256 * 1024 * 1024, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()        # noqa: E731
    return f"scrypt${log_n}${R}${P}${b64(salt)}${b64(digest)}"


def verify_password(password, stored):
    """True when the password matches the stored hash."""
    try:
        algo, log_n, r, p, salt, digest = str(stored).split("$")
        if algo != "scrypt" or not 10 <= int(log_n) <= 20:
            return False
        want = base64.b64decode(digest)
        got = hashlib.scrypt(str(password).encode(), salt=base64.b64decode(salt), n=1 << int(log_n), r=int(r),
                             p=int(p), maxmem=256 * 1024 * 1024, dklen=len(want))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def needs_rehash(stored, log_n=LOG_N):
    try:
        return int(str(stored).split("$")[1]) < log_n
    except (IndexError, ValueError):
        return True


_DUMMY = None


def burn_time(password):
    """Spend the same time as a real check (no account with this email: do not reveal that)."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not-a-real-password")
    verify_password(password, _DUMMY)
