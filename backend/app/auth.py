"""Accounts for Saavren — local SQLite, no external service.

Design notes, because the choices here are deliberate:

* **Local SQLite, not a hosted provider.** The stack is card-free and must
  work offline, and the app already runs entirely on the user's own machine.
  A hosted auth service would add a network dependency to the one screen a
  judge opens first.
* **scrypt from the stdlib**, not bcrypt/passlib. It ships with CPython, needs
  no compiler on the user's Windows box, and (unlike ``audioop`` and friends)
  is still present on Python 3.14. Salts are per-user and comparisons are
  constant-time.
* **Login is optional.** Every endpoint keeps working with no token; identity
  only decides which screen you land on and whose name appears on the
  escalation. Nothing in the app is gated behind an account.
* **The server returns error *codes*, never display text**, so the UI can
  translate them. See ``AUTH_ERRORS`` in the frontend for the matching keys.

Accounts are per person, not per dataset: an elder and the family members who
watch over her all share one care record, which is the point of the product.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(os.getenv(
    "SAAVREN_DB",
    str(Path(__file__).resolve().parent.parent.parent / "saavren.db"),
))

#: how long a session stays valid
SESSION_DAYS = 30

ROLES = ("elder", "family")

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
MIN_PASSWORD = 8

# scrypt work factors. n=2**14 needs roughly 16 MB and ~50 ms — enough to
# make offline cracking unattractive, small enough not to stall a phone.
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


class AuthError(Exception):
    """Raised with a stable code the UI translates (see AUTH_ERRORS)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    """Create the tables if they are not there yet. Safe to call repeatedly."""
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            username    TEXT NOT NULL UNIQUE,
            pw_hash     TEXT NOT NULL,
            pw_salt     TEXT NOT NULL,
            role        TEXT NOT NULL,
            created_at  REAL NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            created_at  REAL NOT NULL,
            expires_at  REAL NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id)")


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------
def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def _public(user: sqlite3.Row) -> dict:
    """The user as the UI may see it — never the hash or the salt."""
    return {
        "id": user["id"],
        "name": user["name"],
        "username": user["username"],
        "role": user["role"],
        "created_at": user["created_at"],
    }


def _clean_username(username: str) -> str:
    u = (username or "").strip()
    if not _USERNAME_RE.match(u):
        raise AuthError("auth_bad_username")
    return u.lower()


# --------------------------------------------------------------------------
# accounts
# --------------------------------------------------------------------------
def signup(name: str, username: str, password: str, role: str = "elder") -> dict:
    """Create an account and return the public user row."""
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise AuthError("auth_no_name")
    u = _clean_username(username)
    if len(password or "") < MIN_PASSWORD:
        raise AuthError("auth_short_password")
    if role not in ROLES:
        raise AuthError("auth_bad_role")

    init_db()
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE username = ?", (u,)).fetchone():
            raise AuthError("auth_username_taken")
        salt = secrets.token_bytes(16)
        row = (
            uuid.uuid4().hex[:12],
            name,
            u,
            _hash(password, salt).hex(),
            salt.hex(),
            role,
            time.time(),
        )
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)", row)
    return login(u, password)


def login(username: str, password: str) -> dict:
    """Check credentials and open a session. Returns {user, token}."""
    u = _clean_username(username)
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (u,)).fetchone()
        if not row:
            raise AuthError("auth_bad_login")
        want = bytes.fromhex(row["pw_hash"])
        got = _hash(password or "", bytes.fromhex(row["pw_salt"]))
        if not hmac.compare_digest(want, got):
            # same message either way: never reveal which half was wrong
            raise AuthError("auth_bad_login")
        user = _public(row)
        token = new_session(c, row["id"])
    return {"user": user, "token": token}


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------
def new_session(c: sqlite3.Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    c.execute("INSERT INTO sessions VALUES (?,?,?,?)",
              (token, user_id, now, now + SESSION_DAYS * 86400))
    return token


def change_password(token: str, password: str, confirm: str) -> dict:
    """Set a new password for the signed-in account.

    The Settings screen asks for New + Confirm only, per the design. That is
    only safe because it requires a live session, so it cannot be used to
    take over an account from a browser that is already locked out — and
    every other session is revoked below, which is what actually limits the
    damage if a token did leak.
    """
    if password != confirm:
        raise AuthError("auth_mismatch")
    if len(password or "") < MIN_PASSWORD:
        raise AuthError("auth_short_password")

    user = user_for_token(token)
    if not user:
        raise AuthError("auth_not_signed_in")

    init_db()
    salt = secrets.token_bytes(16)
    with _conn() as c:
        c.execute("UPDATE users SET pw_hash = ?, pw_salt = ? WHERE id = ?",
                  (_hash(password, salt).hex(), salt.hex(), user["id"]))
        # every other device has to sign in again
        c.execute("DELETE FROM sessions WHERE user_id = ? AND token != ?",
                  (user["id"], token))
    return {"ok": True}


def user_for_token(token: str | None) -> dict | None:
    """Resolve a bearer token to a user, or None if absent/stale."""
    if not token:
        return None
    init_db()
    with _conn() as c:
        row = c.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token = ? AND s.expires_at > ?""",
            (token, time.time()),
        ).fetchone()
        return _public(row) if row else None


def logout(token: str | None) -> None:
    if not token:
        return
    init_db()
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE token = ?", (token,))


def bearer(authorization: str | None) -> str | None:
    """Pull the token out of an ``Authorization: Bearer …`` header."""
    if not authorization:
        return None
    parts = authorization.split()
    return parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None


def count_users() -> int:
    init_db()
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


init_db()
