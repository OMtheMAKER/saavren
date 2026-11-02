"""The demo flag and the medicine endpoints the Medicines screen drives."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import STATE, app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_meds():
    saved = list(STATE["meds"])
    yield
    STATE["meds"] = saved


# --------------------------------------------------------------------------
# the demo flag
# --------------------------------------------------------------------------
def test_state_says_whether_it_is_demo_data():
    """The UI warns about the seeded elder; it can only do that if told."""
    body = client.get("/api/state").json()
    st = body.get("state", body)
    assert "demo" in st
    assert isinstance(st["demo"], bool)


def test_the_demo_flag_matches_the_seed_setting():
    """This install runs with the seed on, so it must admit it."""
    from app.main import DEMO_SEEDED
    body = client.get("/api/state").json()
    st = body.get("state", body)
    assert st["demo"] is DEMO_SEEDED


def test_the_seeded_elder_is_visibly_labelled():
    """Anything the seed wrote should be traceable back to it."""
    body = client.get("/api/state").json()
    st = body.get("state", body)
    if not st["demo"]:
        pytest.skip("install is not seeded")
    seeded = [a for a in (st.get("activity") or []) if a.get("demo")]
    assert seeded, "seed is on but no feed row is marked as seeded"


# --------------------------------------------------------------------------
# medicines
# --------------------------------------------------------------------------
def test_adding_a_medicine_returns_the_whole_state():
    before = len(STATE["meds"])
    d = client.post("/api/meds", json={"name": "Aspirin 75mg", "time": "08:00",
                                       "note": "after breakfast"}).json()
    assert len(d["state"]["meds"]) == before + 1
    added = d["state"]["meds"][-1]
    assert added["name"] == "Aspirin 75mg"
    assert added["time"] == "08:00"
    assert added["taken"] is False


def test_a_new_medicine_starts_untaken():
    d = client.post("/api/meds", json={"name": "Aspirin 75mg", "time": "08:00"}).json()
    assert d["state"]["meds"][-1]["taken"] is False


def test_marking_a_medicine_taken_and_back():
    client.post("/api/meds", json={"name": "Aspirin 75mg", "time": "08:00"})
    name = "Aspirin 75mg"
    d = client.post("/api/meds/taken", json={"name": name}).json()
    row = next(m for m in d["state"]["meds"] if m["name"] == name)
    assert row["taken"] is True
    d = client.post("/api/meds/taken", json={"name": name}).json()
    row = next(m for m in d["state"]["meds"] if m["name"] == name)
    assert row["taken"] is False


def test_deleting_a_medicine():
    d = client.post("/api/meds", json={"name": "Aspirin 75mg", "time": "08:00"}).json()
    mid = d["state"]["meds"][-1]["id"]
    d = client.delete(f"/api/meds/{mid}").json()
    assert all(m["id"] != mid for m in d["state"]["meds"])


def test_adding_a_medicine_requires_a_name():
    assert client.post("/api/meds", json={"name": "", "time": "08:00"}).status_code == 400
