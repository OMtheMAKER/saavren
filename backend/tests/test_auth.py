"""Accounts (optional sign-in). Run: pytest backend/tests -q

Every test runs against its own throwaway database, so the suite never
touches the real saavren.db and never leaves a signed-in session behind.
"""
import os
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

PW = "morningwalk2026"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Every test gets its own database.

    Only DB_PATH needs swapping: every function opens a connection through
    _conn(), which reads it at call time. main.py holds this same module
    object, so the endpoints follow along with no rebinding.
    """
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "test.db")
    yield auth


def _signup(username="shanti", role="elder", password=PW, name="Shanti Devi"):
    return auth.signup(name, username, password, role)


# --------------------------------------------------------------------------
# accounts
# --------------------------------------------------------------------------
def test_signup_returns_a_user_and_a_token():
    out = _signup()
    assert out["user"]["username"] == "shanti"
    assert out["user"]["role"] == "elder"
    assert out["token"] and len(out["token"]) > 20


def test_the_password_itself_is_never_stored():
    _signup()
    con = sqlite3.connect(str(auth.DB_PATH))
    row = con.execute("SELECT pw_hash, pw_salt FROM users").fetchone()
    con.close()
    assert PW not in row[0]
    assert len(bytes.fromhex(row[1])) == 16          # 16-byte salt


def test_the_same_password_hashes_differently_for_two_users():
    _signup("shanti")
    _signup("rohit", "family", name="Rohit Singh")
    con = sqlite3.connect(str(auth.DB_PATH))
    rows = con.execute("SELECT pw_hash FROM users ORDER BY username").fetchall()
    con.close()
    assert rows[0][0] != rows[1][0]                   # salted, not global


def test_duplicate_username_is_rejected_with_a_code():
    _signup()
    with pytest.raises(auth.AuthError) as e:
        _signup()
    assert e.value.code == "auth_username_taken"


@pytest.mark.parametrize("password,code", [
    ("short", "auth_short_password"),
    ("", "auth_short_password"),
])
def test_weak_passwords_are_rejected(password, code):
    with pytest.raises(auth.AuthError) as e:
        _signup(password=password)
    assert e.value.code == code


@pytest.mark.parametrize("username", ["ab", "a b", "way_too_long_" + "x" * 40, ""])
def test_malformed_usernames_are_rejected(username):
    with pytest.raises(auth.AuthError) as e:
        _signup(username=username)
    assert e.value.code == "auth_bad_username"


def test_usernames_are_case_insensitive():
    _signup("Shanti")
    with pytest.raises(auth.AuthError) as e:
        _signup("shanti")
    assert e.value.code == "auth_username_taken"


def test_a_role_must_be_elder_or_family():
    with pytest.raises(auth.AuthError) as e:
        _signup(role="admin")
    assert e.value.code == "auth_bad_role"


def test_a_name_is_required():
    with pytest.raises(auth.AuthError) as e:
        _signup(name="   ")
    assert e.value.code == "auth_no_name"


# --------------------------------------------------------------------------
# logging in
# --------------------------------------------------------------------------
def test_login_returns_a_new_token():
    first = _signup()["token"]
    second = auth.login("shanti", PW)["token"]
    assert first != second


def test_a_wrong_password_is_rejected():
    _signup()
    with pytest.raises(auth.AuthError) as e:
        auth.login("shanti", "not-the-password")
    assert e.value.code == "auth_bad_login"


def test_an_unknown_user_says_the_same_thing_as_a_wrong_password():
    """No user enumeration: both failures must be indistinguishable."""
    _signup()
    try:
        auth.login("ghost", PW)
        assert False, "should have raised"
    except auth.AuthError as e:
        unknown = e.code
    try:
        auth.login("shanti", "wrong-password")
        assert False, "should have raised"
    except auth.AuthError as e:
        wrong = e.code
    assert unknown == wrong == "auth_bad_login"


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------
def test_a_token_resolves_to_its_user():
    out = _signup()
    me = auth.user_for_token(out["token"])
    assert me["username"] == "shanti"
    assert "pw_hash" not in me and "pw_salt" not in me


def test_no_token_means_nobody():
    assert auth.user_for_token(None) is None
    assert auth.user_for_token("") is None


def test_a_made_up_token_resolves_to_nobody():
    _signup()
    assert auth.user_for_token("not-a-real-token") is None


def test_logout_kills_only_that_session():
    a = _signup("shanti")
    b = _signup("rohit", "family", name="Rohit Singh")
    auth.logout(a["token"])
    assert auth.user_for_token(a["token"]) is None
    assert auth.user_for_token(b["token"])["username"] == "rohit"


def test_an_expired_session_is_refused():
    out = _signup()
    con = sqlite3.connect(str(auth.DB_PATH))
    con.execute("UPDATE sessions SET expires_at = ? WHERE token = ?",
                (time.time() - 1, out["token"]))
    con.commit()
    con.close()
    assert auth.user_for_token(out["token"]) is None


def test_bearer_header_parsing():
    assert auth.bearer("Bearer abc123") == "abc123"
    assert auth.bearer("bearer abc123") == "abc123"
    assert auth.bearer("Basic abc123") is None
    assert auth.bearer(None) is None
    assert auth.bearer("garbage") is None


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
def test_signup_endpoint():
    r = client.post("/api/auth/signup",
                    json={"name": "Shanti Devi", "username": "shanti",
                          "password": PW, "role": "elder"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "elder"
    assert r.json()["token"]


def test_signup_endpoint_reports_a_code_the_ui_can_translate():
    client.post("/api/auth/signup",
                json={"name": "A", "username": "shanti",
                      "password": PW, "role": "elder"})
    r = client.post("/api/auth/signup",
                    json={"name": "B", "username": "shanti",
                          "password": PW, "role": "elder"})
    assert r.status_code == 400
    assert r.json()["detail"] == "auth_username_taken"


def test_me_is_null_when_nobody_is_signed_in():
    assert client.get("/api/auth/me").json() == {"user": None}


def test_me_returns_the_user_for_a_valid_token():
    token = _signup(role="family", name="Rohit Singh")["token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["user"]["name"] == "Rohit Singh"
    assert r.json()["user"]["role"] == "family"


def test_logout_endpoint_revokes_the_token():
    token = _signup()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=h).json()["user"]
    assert client.post("/api/auth/logout", headers=h).json() == {"ok": True}
    assert client.get("/api/auth/me", headers=h).json() == {"user": None}


def test_a_bad_login_returns_401():
    _signup()
    r = client.post("/api/auth/login",
                    json={"username": "shanti", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"] == "auth_bad_login"


@pytest.mark.parametrize("path", ["/api/state", "/api/health", "/api/board",
                                  "/api/monitor", "/api/sehat"])
def test_the_app_still_works_with_no_account(path):
    """Login is optional — this is the promise the whole feature rests on."""
    assert client.get(path).status_code == 200


def test_account_count_endpoint():
    assert client.get("/api/auth/accounts").json()["count"] == 0
    _signup()
    assert client.get("/api/auth/accounts").json()["count"] == 1
