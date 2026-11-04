"""Alert copy in the reader's language, and durations a human can read.

The failure mode this file exists to prevent: the interface switches to Hindi
while the alert sitting inside it stays English, and a miss renders a bare key
instead of prose — which is exactly how 'theme_light' reached the Settings
screen. Run: pytest backend/tests -q
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app import ai_extra, auth  # noqa: E402
from app.main import STATE, _scheduler_tick, app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """The alert is written into shared in-memory STATE — put it back."""
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "test.db")
    saved = {
        "checkin_schedule": dict(STATE["checkin_schedule"]),
        "notifications": list(STATE["notifications"]),
        "checkins": list(STATE["checkins"]),
        "activity": list(STATE["activity"]),
    }
    yield
    for k, v in saved.items():
        STATE[k] = v


# --------------------------------------------------------------------------
# 3a — humanize_minutes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("minutes,en,hi", [
    (0,    "0 min",        "0 मिनट"),
    (47,   "47 min",       "47 मिनट"),
    (60,   "1 h",          "1 घंटा"),
    (587,  "9 h 47 min",   "9 घंटे 47 मिनट"),
    (1440, "1 day",        "1 दिन"),
    (1500, "1 day 1 h",    "1 दिन 1 घंटा"),
    (-5,   "0 min",        "0 मिनट"),          # never raises, never negative
])
def test_humanize_minutes(minutes, en, hi):
    assert ai_extra.humanize_minutes(minutes, "en") == en
    assert ai_extra.humanize_minutes(minutes, "hi") == hi


def test_humanize_minutes_never_raises_on_junk():
    """It runs inside a background tick; a bad value must not kill the clock."""
    for bad in (None, "x", [], 3.7):
        assert ai_extra.humanize_minutes(bad, "en")
        assert ai_extra.humanize_minutes(bad, "hi")


def test_humanize_minutes_unknown_language_falls_back_to_en():
    assert ai_extra.humanize_minutes(587, "zz") == "9 h 47 min"


# --------------------------------------------------------------------------
# 3b / 3c — the same event, two languages
# --------------------------------------------------------------------------
def _fire_missed_checkin(overdue_min=587):
    """One scheduler tick with the morning check-in well past its grace."""
    STATE["checkin_schedule"]["morning"] = "00:00"
    STATE["notifications"].clear()
    _scheduler_tick(ai_extra._day_start(time.time()) + overdue_min * 60)
    notes = client.get("/api/state?lang=en").json()["notifications"]
    assert notes, "scheduler tick produced no notification"
    return notes[0]


def test_missed_checkin_alert_is_hindi_when_the_reader_is_hindi():
    _fire_missed_checkin()
    row = client.get("/api/state?lang=hi").json()["notifications"][0]
    assert "जवाब नहीं" in row["body"]
    assert "did not answer" not in row["body"]
    assert "9 घंटे 47 मिनट" in row["body"]


def test_missed_checkin_alert_is_english_when_the_reader_is_english():
    _fire_missed_checkin()
    row = client.get("/api/state?lang=en").json()["notifications"][0]
    assert "did not answer" in row["body"]
    assert "9 h 47 min" in row["body"]
    assert "जवाब नहीं" not in row["body"]


def test_the_language_switch_moves_the_alert_not_just_the_interface():
    _fire_missed_checkin()
    hi = client.get("/api/state?lang=hi").json()["notifications"][0]["body"]
    en = client.get("/api/state?lang=en").json()["notifications"][0]["body"]
    assert hi != en, "both languages returned identical copy"


# --------------------------------------------------------------------------
# 3d — never a raw key
# --------------------------------------------------------------------------
def test_no_notification_text_is_ever_a_raw_key():
    _fire_missed_checkin()
    for lang in ("hi", "en", "bn", "ta", "te", "mr", "gu", "es", "fr", "zz"):
        for n in client.get(f"/api/state?lang={lang}").json()["notifications"]:
            for field in ("title", "body"):
                val = (n.get(field) or "").strip()
                assert val not in ai_extra.ALERT_TEXT, (
                    f"{lang}/{field} rendered the raw key {val!r}")
                assert not val.startswith("checkin_"), (
                    f"{lang}/{field} rendered the raw key {val!r}")
                assert "{" not in val, (
                    f"{lang}/{field} rendered an unformatted template: {val!r}")


def test_a_language_with_no_row_falls_back_to_english_not_to_a_key():
    _fire_missed_checkin()
    row = client.get("/api/state?lang=zz").json()["notifications"][0]
    assert "did not answer" in row["body"]
    assert row["body"]  # never empty
