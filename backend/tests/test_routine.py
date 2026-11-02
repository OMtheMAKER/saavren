"""Routine planner and password change. Run: pytest backend/tests -q

The routine is *derived* from medicines and the check-in schedule rather than
stored, so these tests pin that behaviour down: edit a medicine and the
routine follows with nothing to sync.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.main import STATE, app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """Give the accounts their own database, and put back anything a test
    disturbs in STATE — both are shared and in-memory."""
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "test.db")
    saved_meds = list(STATE["meds"])
    saved_sched = dict(STATE["checkin_schedule"])
    saved_alarms = dict(STATE["routine_alarms"])
    saved_checkins = list(STATE["checkins"])
    yield
    STATE["meds"] = saved_meds
    STATE["checkin_schedule"] = saved_sched
    STATE["routine_alarms"] = saved_alarms
    STATE["checkins"] = saved_checkins


def _items():
    return client.get("/api/routine").json()["items"]


def _by_key(items):
    return {i["key"]: i for i in items}


# --------------------------------------------------------------------------
# the planner itself
# --------------------------------------------------------------------------
def test_every_medicine_shows_up_as_a_row():
    keys = [i["key"] for i in _items()]
    for m in STATE["meds"]:
        assert "med:" + m["id"] in keys


def test_built_in_rows_come_as_i18n_keys_not_display_text():
    """The UI translates these, so they must not arrive as English."""
    row = _by_key(_items())["checkin:morning"]
    assert row["label"] == "routine_checkin_morning"
    assert row["label"] != "Morning check-in"


def test_rows_are_sorted_by_time():
    times = [i["time"] for i in _items() if i["time"]]
    assert times == sorted(times)


def test_every_row_has_a_time_to_ring_at():
    for i in _items():
        assert i["time"], f"{i['key']} has no time — its alarm could never fire"


def test_alarms_default_to_on():
    assert all(i["alarm"] for i in _items())


def test_toggling_an_alarm_persists():
    client.post("/api/routine/alarm", json={"key": "med:m1", "alarm": False})
    assert _by_key(_items())["med:m1"]["alarm"] is False
    # and back
    client.post("/api/routine/alarm", json={"key": "med:m1", "alarm": True})
    assert _by_key(_items())["med:m1"]["alarm"] is True


def test_only_the_toggled_row_changes():
    before = _by_key(_items())
    client.post("/api/routine/alarm", json={"key": "med:m2", "alarm": False})
    after = _by_key(_items())
    for key in before:
        if key != "med:m2":
            assert before[key]["alarm"] == after[key]["alarm"]


def test_adding_a_medicine_appears_in_the_routine_without_syncing():
    before = len(_items())
    d = client.post("/api/meds", json={"name": "Aspirin 75mg", "time": "08:00",
                                       "note": "heart"}).json()
    assert len(_items()) == before + 1
    labels = [i["label"] for i in _items()]
    assert "Aspirin 75mg" in labels
    # tidy up
    STATE["meds"] = [m for m in STATE["meds"] if m["id"] != d["state"]["meds"][-1]["id"]]


def test_disabling_check_ins_removes_their_rows():
    client.put("/api/checkin/schedule", json={"enabled": False})
    keys = [i["key"] for i in _items()]
    assert "checkin:morning" not in keys
    assert "checkin:evening" not in keys


def test_a_medicine_marked_taken_shows_as_done():
    STATE["meds"][0]["taken"] = True
    assert _by_key(_items())["med:" + STATE["meds"][0]["id"]]["done"] is True


# --------------------------------------------------------------------------
# changing a password
# --------------------------------------------------------------------------
def _signup(username="shanti", password="morningwalk2026"):
    return client.post("/api/auth/signup",
                       json={"name": "Shanti Devi", "username": username,
                             "password": password, "role": "elder"}).json()["token"]


def test_changing_the_password_lets_the_new_one_in():
    token = _signup()
    r = client.post("/api/auth/password",
                    json={"password": "newpassword123", "confirm": "newpassword123"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.post("/api/auth/login",
                       json={"username": "shanti",
                             "password": "newpassword123"}).status_code == 200
    assert client.post("/api/auth/login",
                       json={"username": "shanti",
                             "password": "morningwalk2026"}).status_code == 401


def test_a_mismatch_is_refused_and_changes_nothing():
    token = _signup()
    r = client.post("/api/auth/password",
                    json={"password": "newpassword123", "confirm": "different123"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert r.json()["detail"] == "auth_mismatch"
    assert client.post("/api/auth/login",
                       json={"username": "shanti",
                             "password": "morningwalk2026"}).status_code == 200


def test_a_short_password_is_refused():
    token = _signup()
    r = client.post("/api/auth/password", json={"password": "abc", "confirm": "abc"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert r.json()["detail"] == "auth_short_password"


def test_changing_a_password_requires_a_session():
    r = client.post("/api/auth/password",
                    json={"password": "newpassword123", "confirm": "newpassword123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "auth_not_signed_in"


def test_changing_a_password_signs_out_other_devices():
    """The reason New+Confirm is acceptable: a leaked token stops working."""
    phone = _signup()
    laptop = client.post("/api/auth/login",
                         json={"username": "shanti",
                               "password": "morningwalk2026"}).json()["token"]
    client.post("/api/auth/password",
                json={"password": "newpassword123", "confirm": "newpassword123"},
                headers={"Authorization": f"Bearer {laptop}"})
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {phone}"}).json() == {"user": None}
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {laptop}"}).json()["user"]
