"""Saavren backend tests. Run: pytest backend/tests -q"""
import json
import os
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app import ai, ai_extra  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def _wav(samples, rate=16000):
    data = b"".join(struct.pack("<h", max(-32768, min(32767, int(s))))
                    for s in samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
            b"data" + struct.pack("<I", len(data)) + data)


# --------------------------------------------------------------------------
# basics
# --------------------------------------------------------------------------
def test_health():
    r = client.get("/api/health").json()
    assert r["ok"] and r["service"] == "saavren"
    assert r["asr_mode"] in ("mms", "groq", "browser")
    assert r["ffmpeg_required"] is False


def test_state_has_profile_and_meds():
    s = client.get("/api/state").json()
    assert s["profile"]["name"] and len(s["meds"]) >= 3


# --------------------------------------------------------------------------
# triage
# --------------------------------------------------------------------------
def test_normalize_triage_clamps_severity():
    assert ai.normalize_triage({"severity": 99})["severity"] == 10
    assert ai.normalize_triage({"severity": -5})["severity"] == 1


def test_red_flag_forces_at_least_five():
    d = ai.normalize_triage({"severity": 2, "red_flags": ["chest-pain"]})
    assert d["severity"] >= 5 and d["doctor_call"] is False


def test_seven_forces_doctor_call():
    assert ai.normalize_triage({"severity": 7})["doctor_call"] is True


def test_disclaimer_added_once_on_serious_cases():
    d = ai.normalize_triage({"severity": 8, "calm_reply": "sit down"})
    assert "Saavren" in d["calm_reply"] and "doctor" in d["calm_reply"]
    again = ai.normalize_triage(d)
    assert again["calm_reply"].count("Saavren") == 1


def test_mild_triage_has_no_disclaimer_but_serious_does():
    mild = ai.normalize_triage({"severity": 3, "calm_reply": "Rest a little."})
    assert "not a doctor" not in mild["calm_reply"]
    bad = ai.normalize_triage({"severity": 8, "calm_reply": "Sit down now."})
    assert "not a doctor" in bad["calm_reply"]


def test_offline_triage_chest_pain_is_emergency():
    t = ai.offline_triage("seene mein dard ho raha hai", "hi")
    assert t["severity"] >= 8 and t["doctor_call"] is True
    assert "chest-pain" in t["red_flags"]


def test_devanagari_red_flags_are_detected():
    t = ai.offline_triage("मेरे सीने में दर्द है", "hi")
    assert t["severity"] >= 8


# --------------------------------------------------------------------------
# language
# --------------------------------------------------------------------------
def test_reply_follows_the_language_the_user_actually_typed():
    assert ai._has_devanagari(ai.triage("मुझे बुखार है", "en")["calm_reply"])
    roman = ai.triage("mujhe bukhaar hai", "en")
    assert not ai._has_devanagari(roman["calm_reply"])
    assert ai.detect_hinglish(roman["calm_reply"])
    eng = ai.triage("I have fever", "en")
    assert not ai._has_devanagari(eng["calm_reply"])
    assert not ai.detect_hinglish(eng["calm_reply"])


def test_effective_lang_and_detect_lang():
    assert ai.detect_lang("मुझे बुखार है") == "hi"
    assert ai.detect_lang("how are you") == ""
    assert ai.effective_lang("how are you", "en") == "en"
    assert ai.effective_lang("मुझे बुखार है", "en") == "hi"


def test_english_offline_reply_is_pure_english():
    assert not ai._has_devanagari(ai.offline_agent("how are you", "en")["reply"])
    t = ai.offline_triage("I feel a bit tired", "en")
    assert not ai._has_devanagari(t["calm_reply"])
    for step in t["home_care"]:
        assert not ai._has_devanagari(step)


def test_offline_replies_rotate():
    seen = {ai.offline_agent(f"message number {i}", "en")["reply"] for i in range(12)}
    assert len(seen) > 1


# --------------------------------------------------------------------------
# chat routing
# --------------------------------------------------------------------------
def test_social_message_never_becomes_a_triage_card():
    for m in ["how are you?", "hi", "Hello!", "kaise ho", "thanks",
              "good morning", "I'm fine"]:
        r = client.post("/api/chat", json={
            "message": m, "lang": "en", "force_triage": True}).json()
        assert r["kind"] == "agent", (m, r.get("kind"))
        assert "not a doctor" not in json.dumps(r).lower()


def test_unwell_message_still_triages_even_when_polite():
    r = client.post("/api/chat", json={
        "message": "hello, I have chest pain", "lang": "en"}).json()
    assert r["kind"] == "triage" and r["triage"]["severity"] >= 8


def test_devanagari_health_words_also_trigger_triage():
    for m in ["मुझे बुखार है", "मेरे सीने में दर्द हो रहा है"]:
        r = client.post("/api/chat", json={"message": m, "lang": "hi"}).json()
        assert r["kind"] == "triage", (m, r.get("kind"))
    assert ai._has_devanagari(r["triage"]["calm_reply"])


def test_agent_actions_write_to_shared_state():
    before = len(client.get("/api/state").json()["meds"])
    r = client.post("/api/chat", json={
        "message": "add medicine Paracetamol at 10:00", "lang": "en"}).json()
    assert r["kind"] == "agent"
    assert len(r["state"]["meds"]) >= before


# --------------------------------------------------------------------------
# audio + ASR
# --------------------------------------------------------------------------
def test_to_wav_resamples_to_16k_mono():
    wav = _wav([int(20000 * (1 if i % 2 else -1)) for i in range(8000)], rate=8000)
    out = ai.to_wav(wav, "audio/wav")
    assert out[:4] == b"RIFF"
    rate = struct.unpack("<I", out[24:28])[0]
    ch = struct.unpack("<H", out[22:24])[0]
    assert rate == 16000 and ch == 1


def test_pcm_samples_roundtrip():
    s = ai.pcm_samples(_wav([100, -100, 200, -200]))
    assert s[:4] == [100, -100, 200, -200]


def test_voice_sos_without_token_is_asr_unavailable(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    ai.ASR_STATE.update(mms=True, groq=True, mms_provider=None)
    r = client.post("/api/voice-sos",
                    files={"file": ("a.wav", _wav([0] * 1600), "audio/wav")})
    assert r.status_code == 503
    assert r.json()["detail"] == "ASR_UNAVAILABLE"


def test_voice_sos_error_names_the_stage(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    ai._HF_STATUS.update(checked=True, ok=True, detail="ok", credits=True)
    ai.ASR_STATE.update(mms=True, groq=False, mms_provider=None)

    def boom(*a, **k):
        raise RuntimeError("ASR_FAILED: mms — fal: HTTP 400")

    monkeypatch.setattr(ai, "asr_transcribe", boom)
    r = client.post("/api/voice-sos",
                    files={"file": ("a.wav", _wav([0] * 1600), "audio/wav")})
    assert r.status_code == 502 and "STAGE: ASR failed" in r.json()["detail"]
    ai.ASR_STATE.update(mms=True, groq=True, mms_provider=None)


def test_asr_chain_falls_from_mms_to_groq_to_browser(monkeypatch):
    monkeypatch.delenv("ASR_ORDER", raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    ai.ASR_STATE.update(mms=True, groq=True, mms_provider=None)
    assert ai.asr_chain() == ["mms", "groq"] and ai.asr_mode() == "mms"
    ai.ASR_STATE["mms"] = False
    assert ai.asr_mode() == "groq"
    ai.ASR_STATE["groq"] = False
    assert ai.asr_mode() == "browser" and ai.asr_available() is False
    ai.ASR_STATE.update(mms=True, groq=True, mms_provider=None)


def test_asr_chain_requires_keys(monkeypatch):
    monkeypatch.delenv("ASR_ORDER", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    ai.ASR_STATE.update(mms=True, groq=True, mms_provider=None)
    assert ai.asr_chain() == [] and ai.asr_mode() == "browser"


def test_asr_transcribe_uses_the_next_engine_when_mms_fails(monkeypatch):
    calls = []
    monkeypatch.delenv("ASR_ORDER", raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    ai.ASR_STATE.update(mms=True, groq=True, mms_provider=None)

    def bad(d, c):
        calls.append("mms")
        raise RuntimeError("HTTP 400 not supported")

    monkeypatch.setattr(ai, "_asr_mms", bad)
    monkeypatch.setattr(ai, "_asr_groq", lambda d, c: (calls.append("groq"),
                                                       "namaste")[1])
    assert ai.asr_transcribe(b"RIFF", "audio/wav") == "namaste"
    assert calls == ["mms", "groq"]
    ai.ASR_STATE.update(mms=True, groq=True, mms_provider=None)


# --------------------------------------------------------------------------
# LLM plumbing
# --------------------------------------------------------------------------
def test_env_reader_strips_stray_quotes(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", '  "gsk_abcdefghij"  ')
    assert ai._env("GROQ_API_KEY") == "gsk_abcdefghij"
    monkeypatch.setenv("HF_TOKEN", "'hf_x'")
    assert ai._env("HF_TOKEN") == "hf_x"


def test_key_preview_never_leaks_a_secret(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 50)
    for k, v in ai.key_preview().items():
        assert len(v) < 40 and "x" * 20 not in v


def test_llm_failure_is_recorded_not_swallowed(monkeypatch):
    def boom(payload):
        raise RuntimeError("kaboom")

    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("BASETEN_API_KEY", "bt_test")
    monkeypatch.setattr(ai, "_baseten", boom)
    monkeypatch.setattr(ai, "_groq", boom)
    ai.LLM_ERRORS.clear()
    ai.DEAD_PROVIDERS.clear()
    text, prov = ai.llm([{"role": "user", "content": "hi"}])
    assert prov == "offline" and text == ""
    assert "baseten" in ai.LLM_ERRORS and "groq" in ai.LLM_ERRORS
    ai.DEAD_PROVIDERS.clear()


def test_groq_default_is_not_the_retired_llama(monkeypatch):
    monkeypatch.delenv("GROQ_MODELS", raising=False)
    import importlib
    importlib.reload(ai)
    assert "llama-3.3-70b-versatile" not in ai.GROQ_MODELS
    assert ai.GROQ_MODELS[0].startswith("openai/gpt-oss")


def test_groq_skips_a_retired_model(monkeypatch):
    calls = []

    class R:
        def __init__(self, code, payload=None):
            self.status_code, self._p = code, payload or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._p

    def fake_post(url, headers=None, json_body=None, **kw):
        calls.append(json_body["model"])
        if json_body["model"] == "retired-model":
            return R(404)
        return R(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.setenv("GROQ_MODELS", "retired-model,openai/gpt-oss-120b")
    import importlib
    importlib.reload(ai)
    monkeypatch.setattr(ai, "_post", fake_post)
    assert ai._groq({"messages": []}) == "ok"
    assert calls == ["retired-model", "openai/gpt-oss-120b"]


def test_baseten_uses_bearer_and_retries_with_api_key(monkeypatch):
    seen = []

    class R:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, headers=None, json_body=None, **kw):
        seen.append(headers["Authorization"])
        return R(401 if "Bearer" in headers["Authorization"] else 200)

    monkeypatch.setenv("BASETEN_API_KEY", "bt_x")
    monkeypatch.setattr(ai, "_post", fake_post)
    assert ai._baseten({"messages": []}) == "ok"
    assert seen[0].startswith("Bearer ") and seen[1].startswith("Api-Key ")


def test_baseten_falls_back_to_a_live_catalog_model(monkeypatch):
    calls = []

    class R:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, headers=None, json_body=None, **kw):
        calls.append(json_body["model"])
        return R(404 if json_body["model"] == "gone-model" else 200)

    monkeypatch.setenv("BASETEN_API_KEY", "bt_x")
    monkeypatch.setattr(ai, "_post", fake_post)
    monkeypatch.setattr(ai, "baseten_models_offered",
                        lambda: ["zai-org/GLM-5.3", "meta-llama/Llama-3.3-70B"])
    monkeypatch.setattr(ai, "BASETEN_MODEL", "gone-model")
    assert ai._baseten({"messages": []}) == "ok"
    assert calls[1] == "meta-llama/Llama-3.3-70B"      # Meta slug preferred


def test_muse_spark_gets_its_documented_sampling():
    b = ai._baseten_body("meta-models/muse-spark-open", [])
    assert b["temperature"] == 1.0 and b["top_p"] == 1.0
    assert b["reasoning_effort"] == "low"
    assert ai._baseten_body("zai-org/GLM-5.3", [])["temperature"] == 0.4


def test_provider_order_meta_first_groq_as_net(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_ORDER", raising=False)
    monkeypatch.delenv("ENABLE_HF_LLM", raising=False)
    monkeypatch.setenv("BASETEN_API_KEY", "bt_x")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    ai._HF_STATUS.update(checked=True, ok=True, detail="ok", credits=True)
    ai.DEAD_PROVIDERS.clear()
    assert ai.provider_order() == ["baseten", "groq", "offline"]


def test_hf_router_off_by_default_no_credits_for_free_accounts(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_ORDER", raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    monkeypatch.setenv("BASETEN_API_KEY", "bt_x")
    ai._HF_STATUS.update(checked=True, ok=True, detail="ok", credits=True)
    ai.DEAD_PROVIDERS.clear()
    monkeypatch.delenv("ENABLE_HF_LLM", raising=False)
    assert "hf" not in ai.provider_order()
    monkeypatch.setenv("ENABLE_HF_LLM", "1")
    assert ai.provider_order() == ["baseten", "hf", "offline"]


def test_a_402_provider_is_dropped_from_the_chain(monkeypatch):
    class R:
        status_code = 402
        text = "no credits"

    def boom(payload):
        e = RuntimeError("402")
        e.response = R()
        raise e

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_ORDER", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.setattr(ai, "_groq", boom)
    ai.DEAD_PROVIDERS.clear()
    ai.LLM_ERRORS.clear()
    ai.llm([{"role": "user", "content": "hi"}])
    assert "groq" in ai.DEAD_PROVIDERS
    assert "groq" not in ai.provider_order()
    ai.DEAD_PROVIDERS.clear()


def test_provider_order_honours_llm_order_override(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_ORDER", "groq,hf")
    monkeypatch.setenv("ENABLE_HF_LLM", "1")
    monkeypatch.setenv("BASETEN_API_KEY", "bt_x")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    ai.DEAD_PROVIDERS.clear()
    ai._HF_STATUS.update(checked=True, ok=True, detail="ok", credits=True)
    assert ai.provider_order() == ["groq", "hf", "offline"]


def test_ai_status_endpoint_is_honest():
    r = client.get("/api/ai-status").json()
    for k in ("provider_order", "keys", "llm_errors", "asr"):
        assert k in r
    for v in r["keys"].values():
        assert len(v) < 40


# --------------------------------------------------------------------------
# D3 — thud detection + escalation
# --------------------------------------------------------------------------
def _thud_wav(freq=92, amp=26000, decay=500, seconds=2, quiet_ms=100):
    """A synthetic fall: a short loud low-frequency burst, then silence."""
    import math
    s = [0] * int(16000 * quiet_ms / 1000)
    s += [int(amp * math.sin(2 * math.pi * freq * (i / 16000)) *
              math.exp(-i / decay)) for i in range(1600)]
    s += [0] * int(16000 * seconds)
    return _wav(s)


def _clap_wav():
    import math
    s = [0] * 1600
    s += [int(20000 * math.exp(-i / 220) *
              (math.sin(2 * math.pi * 140 * (i / 16000)) +
               0.4 * math.sin(2 * math.pi * 60 * (i / 16000))))
          for i in range(1200)]
    s += [0] * (16000 * 2)
    return _wav(s)


def _speech_wav(seconds=2, amp=5200):
    """Voiced speech: 150 Hz f0 with real harmonics — the hard negative."""
    import math
    out = []
    for i in range(16000 * seconds):
        t = i / 16000
        env = 0.5 + 0.5 * math.sin(2 * math.pi * 3 * t)
        v = (math.sin(2 * math.pi * 150 * t)
             + 0.75 * math.sin(2 * math.pi * 450 * t)
             + 0.55 * math.sin(2 * math.pi * 900 * t)
             + 0.35 * math.sin(2 * math.pi * 1800 * t)
             + 0.18 * math.sin(2 * math.pi * 2600 * t))
        out.append(int(amp * env * v))
    return _wav(out)


def _laugh_wav(seconds=2):
    import math
    out = []
    for i in range(16000 * seconds):
        t = i / 16000
        env = abs(math.sin(2 * math.pi * 5 * t)) ** 2
        v = (math.sin(2 * math.pi * 220 * t)
             + 0.6 * math.sin(2 * math.pi * 660 * t)
             + 0.3 * math.sin(2 * math.pi * 1320 * t))
        out.append(int(8000 * env * v))
    return _wav(out)


def test_thud_detected_on_a_fall_like_clip():
    res = ai.thud_score(_thud_wav(), "audio/wav")
    assert res["verdict"] == "thud" and res["score"] >= 0.72
    assert res["checks"]["low_freq"] and res["checks"]["low_zcr"]
    assert res["checks"]["short_body"] and res["checks"]["quick_decay"]


def test_clap_is_also_a_thud():
    assert ai.thud_score(_clap_wav(), "audio/wav")["verdict"] == "thud"


def test_sustained_speech_is_not_a_thud():
    """The hard negative: speech is loud with a fast attack too."""
    res = ai.thud_score(_speech_wav(), "audio/wav")
    assert res["verdict"] != "thud"
    assert res["checks"]["short_body"] is False   # speech keeps going
    assert res["checks"]["low_zcr"] is False      # harmonics cross zero a lot
    assert res["checks"]["quick_decay"] is False  # and it does not stop


def test_loud_laughter_does_not_escalate():
    res = ai.thud_score(_laugh_wav(), "audio/wav")
    assert res["verdict"] != "thud"


def test_silence_and_room_noise_are_quiet():
    import random
    assert ai.thud_score(_wav([0] * 32000), "audio/wav")["verdict"] == "quiet"
    noise = [random.randint(-150, 150) for _ in range(32000)]
    assert ai.thud_score(_wav(noise), "audio/wav")["verdict"] == "quiet"


def test_thud_score_survives_garbage():
    res = ai.thud_score(b"not audio at all", "audio/wav")
    assert res["score"] == 0.0


def test_thud_weights_sum_to_one():
    assert abs(sum(ai.THUD_WEIGHTS.values()) - 1.0) < 1e-9


def test_fall_raises_an_alarm_then_cancels():
    r = client.post("/api/fall", json={"confidence": 0.9, "source": "browser"})
    a = r.json()["alarm"]
    assert a["status"] == "ringing" and a["kind"] == "fall"
    assert a["grace"] >= 1
    got = client.get("/api/alarm").json()
    assert got["alarm"]["id"] == a["id"] and got["remaining"] > 0
    c = client.post("/api/alarm/cancel").json()
    assert c["ok"] and c["alarm"]["status"] == "cancelled"


def test_alarm_escalates_when_nobody_answers(monkeypatch):
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    monkeypatch.setattr("app.main.FALL_GRACE", 1, raising=False)
    from app.main import _escalate, _new_alarm
    a = _new_alarm("fall", 0.9, "browser", {}, "en")
    _escalate(a["id"])
    assert STATE_ALARM(a["id"])["status"] == "escalated"
    notes = client.get("/api/state").json()["notifications"]
    assert any(n["kind"] == "emergency" for n in notes)
    client.post("/api/alarm/cancel")


def STATE_ALARM(aid):
    return client.get("/api/alarm").json()["alarm"]


def test_sos_escalates_immediately(monkeypatch):
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    r = client.post("/api/sos").json()
    assert r["alarm"]["status"] == "escalated"
    assert any(n["kind"] == "emergency"
               for n in r["state"]["notifications"])
    _clear_alarm()


def test_fall_analyze_endpoint_accepts_audio():
    r = client.post("/api/fall/analyze",
                    files={"file": ("a.wav", _thud_wav(), "audio/wav")},
                    params={"auto_alarm": 0})
    assert r.status_code == 200
    assert "analysis" in r.json()
    assert r.json()["alarm"] is None
    _clear_alarm()


def test_falls_history_is_recorded():
    client.post("/api/fall", json={"confidence": 0.5, "source": "test"})
    assert len(client.get("/api/falls").json()["falls"]) >= 1
    client.post("/api/alarm/cancel")
    _clear_alarm()


def _clear_alarm():
    from app.main import STATE
    STATE["alarm"] = None


# --------------------------------------------------------------------------
# misc endpoints
# --------------------------------------------------------------------------
def test_meds_crud():
    before = len(client.get("/api/state").json()["meds"])
    m = client.post("/api/meds", json={"name": "TestMed", "time": "08:00"}).json()
    assert len(m["state"]["meds"]) == before + 1
    client.post("/api/meds/taken", json={"name": "TestMed"})
    assert any(x["taken"] for x in
               client.get("/api/state").json()["meds"] if x["name"] == "TestMed")
    client.delete(f"/api/meds/{m['med']['id']}")
    assert len(client.get("/api/state").json()["meds"]) == before


def test_notifications_read():
    client.post("/api/notify", json={"title": "t", "body": "b", "kind": "info"})
    client.post("/api/notifications/read")
    assert all(n["read"] for n in client.get("/api/state").json()["notifications"])


def test_profile_update():
    r = client.put("/api/profile", json={"age": 73}).json()
    assert r["state"]["profile"]["age"] == 73


def test_scan_offline_is_honest():
    r = client.post("/api/scan", files={
        "file": ("p.jpg", b"\xff\xd8\xff" + b"0" * 64, "image/jpeg")})
    assert r.status_code == 200
    assert r.json()["source"] in ("offline-fallback", "baseten")


# --------------------------------------------------------------------------
# Python 3.13+ removed `audioop` — Saavren must never import it again
# --------------------------------------------------------------------------
def test_ai_module_imports_without_audioop():
    """Simulates the user's Python 3.14, where `audioop` does not exist."""
    import builtins
    import importlib

    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name == "audioop" or name.startswith("audioop."):
            raise ModuleNotFoundError("No module named 'audioop'")
        return real_import(name, *a, **k)

    for mod in [m for m in list(sys.modules) if m.startswith("app")]:
        del sys.modules[mod]
    builtins.__import__ = blocked
    try:
        m = importlib.import_module("app.ai")
        assert hasattr(m, "thud_score") and hasattr(m, "asr_transcribe")
    finally:
        builtins.__import__ = real_import
        for mod in [m for m in list(sys.modules) if m.startswith("app")]:
            del sys.modules[mod]
        # Rebind the module-level fixtures too: dropping `app.*` from
        # sys.modules and re-importing creates NEW module objects, so the
        # `client`, `ai` and `ai_extra` this file imported at the top would
        # otherwise keep pointing at the discarded state and every later test
        # would silently assert against a different app than it drives.
        globals()["ai"] = importlib.import_module("app.ai")
        globals()["ai_extra"] = importlib.import_module("app.ai_extra")
        globals()["client"] = TestClient(importlib.import_module("app.main").app)


def test_no_audioop_anywhere_in_the_source():
    """No import and no call — only prose may mention the name."""
    import re
    src = (Path(__file__).resolve().parents[1] / "app" / "ai.py").read_text("utf-8")
    assert not re.search(r"^\s*(import|from)\s+audioop", src, re.M)
    assert not re.search(r"\baudioop\s*\.", src)
    assert "import audioop" not in src


def test_resample_and_encode_roundtrip():
    vals = [int(20000 * (1 if i % 2 else -1)) for i in range(8000)]
    up = ai.resample(vals, 8000, 16000)
    assert abs(len(up) - 16000) <= 2
    down = ai.resample(up, 16000, 8000)
    assert abs(len(down) - 8000) <= 2


def test_decode_wav_handles_stereo_and_8bit():
    # stereo 16-bit -> mono
    frames = b"".join(struct.pack("<hh", 1000, 3000) for _ in range(100))
    body = (b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 2, 16000, 64000, 4, 16) +
            b"data" + struct.pack("<I", len(frames)) + frames)
    vals, ch, rate = ai.decode_wav(body)
    assert ch == 1 and rate == 16000 and len(vals) == 100
    assert abs(vals[0] - 2000) <= 2           # average of the two channels

    # 8-bit unsigned mono
    raw = bytes([128 + 40] * 50)
    body8 = (b"RIFF" + struct.pack("<I", 36 + len(raw)) + b"WAVEfmt " +
             struct.pack("<IHHIIHH", 16, 1, 1, 16000, 16000, 1, 8) +
             b"data" + struct.pack("<I", len(raw)) + raw)
    v8, _, _ = ai.decode_wav(body8)
    assert len(v8) == 50 and v8[0] > 0


def test_thud_still_works_with_the_pure_python_resampler():
    """48 kHz stereo input must resample to 16 k mono and still be detected."""
    import math
    frames = []
    for i in range(int(48000 * 0.6)):
        v = (int(24000 * math.sin(2 * math.pi * 90 * (i / 48000)) *
                 math.exp(-(i - 24000) / 900)) if 24000 <= i < 25200 else 0)
        frames.append(struct.pack("<hh", v, v))
    pcm = b"".join(frames)
    wav = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
           struct.pack("<IHHIIHH", 16, 1, 2, 48000, 192000, 4, 16) +
           b"data" + struct.pack("<I", len(pcm)) + pcm)
    res = ai.thud_score(wav, "audio/wav")
    assert res["seconds"] >= 0.5
    assert res["verdict"] in ("thud", "possible")


# --------------------------------------------------------------------------
# D4 — escalation record, hospitals, emergency card
# --------------------------------------------------------------------------
def test_emergency_record_is_built_on_escalation(monkeypatch):
    from app.main import STATE
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    ai_extra._HOSP_CACHE.clear()
    STATE["emergencies"].clear()
    r = client.post("/api/sos").json()
    eid = r["alarm"].get("emergency_id")
    assert eid, "escalation must attach an emergency record"
    rec = client.get(f"/api/emergency/{eid}").json()
    assert rec["kind"] == "sos" and rec["status"] == "open"
    assert rec["card"]["name"] == STATE["profile"]["name"]
    assert rec["hospitals"], "nearest hospitals must be attached"
    assert [s["stage"] for s in rec["timeline"]][:3] == \
        ["detected", "alarm", "escalated"]


def test_emergency_call_is_logged(monkeypatch):
    from app.main import STATE
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    STATE["emergencies"].clear()
    rec = client.post("/api/sos").json()["alarm"]
    eid = rec["emergency_id"]
    d = client.post(f"/api/emergency/{eid}/call", json={"who": "family"}).json()
    assert d["ok"] and d["record"]["call_log"][-1]["who"] == "family"
    assert d["record"]["timeline"][-1]["stage"] == "called"


def test_emergency_can_be_closed(monkeypatch):
    from app.main import STATE
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    STATE["emergencies"].clear()
    eid = client.post("/api/sos").json()["alarm"]["emergency_id"]
    d = client.post(f"/api/emergency/{eid}/close").json()
    assert d["record"]["status"] == "closed"


def test_cancelled_fall_creates_no_emergency():
    from app.main import STATE
    STATE["emergencies"].clear()
    client.post("/api/fall", json={"confidence": 0.9, "source": "test"})
    client.post("/api/alarm/cancel")
    assert STATE["emergencies"] == []


def test_hospitals_endpoint_returns_a_usable_list(monkeypatch):
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    d = client.get("/api/hospitals").json()
    assert d["hospitals"]
    for h in d["hospitals"]:
        assert h["name"]
        assert h["source"] in ("osm", "offline-list")


def test_overpass_payload_is_parsed_into_hospitals(monkeypatch):
    """The real parser, fed a canned Overpass reply (no network in tests)."""
    payload = {"elements": [
        {"type": "node", "id": 1, "lat": 25.44, "lon": 81.85,
         "tags": {"name": "Near Hospital", "phone": "0532-1234567",
                  "emergency": "yes"}},
        {"type": "way", "id": 2, "center": {"lat": 25.50, "lon": 81.90},
         "tags": {"name": "Far Hospital"}},
        {"type": "node", "id": 3, "lat": 25.44, "lon": 81.85, "tags": {}},
    ]}

    class R:
        status_code = 200

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return R()

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)
    ai_extra._HOSP_CACHE.clear()
    out = ai_extra.nearest_hospitals(25.4358, 81.8463)
    assert [h["name"] for h in out] == ["Near Hospital", "Far Hospital"]
    assert out[0]["emergency"] is True and out[0]["phone"] == "0532-1234567"
    assert out[0]["distance_m"] < out[1]["distance_m"]
    assert "google.com/maps" in out[0]["map"]


def test_fallback_hospitals_are_flagged_approximate():
    fb = ai_extra._fallback_hospitals()
    assert all(h["source"] == "offline-list" for h in fb)
    assert any("112" in h["name"] for h in fb)


def test_haversine_is_sane():
    # Prayagraj -> Lucknow is roughly 200 km
    d = ai_extra.haversine_m(25.4358, 81.8463, 26.8467, 80.9462) / 1000
    assert 150 < d < 250


def test_parse_phone_pulls_the_number_out_of_free_text():
    assert ai_extra.parse_phone("Rohit (son) +91-90000-00000") == "+919000000000"
    assert ai_extra.parse_phone("call 9839012345 now") == "9839012345"
    assert ai_extra.parse_phone("no number here") == ""


def test_ecard_contains_what_a_paramedic_needs(monkeypatch):
    card = ai_extra.emergency_card(
        {"name": "Shanti Devi", "age": 72, "gender": "female",
         "blood_group": "O+", "conditions": ["BP", "Diabetes"],
         "allergies": ["Penicillin"], "emergency_contact": "Rohit +91-90000-00000"},
        [{"name": "Amlodipine 5mg", "time": "09:00", "note": "after food"}])
    assert card["blood_group"] == "O+" and "Penicillin" in card["allergies"]
    assert card["emergency_phone"] == "+919000000000"
    txt = ai_extra.ecard_text(card, ai_extra._fallback_hospitals())
    assert "Shanti Devi" in txt and "O+" in txt and "Amlodipine" in txt
    assert "not a doctor" in txt.lower()
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    assert client.get("/api/ecard").json()["text"]


def test_location_can_be_updated_and_clears_the_cache():
    d = client.put("/api/location", json={"lat": 26.8467, "lon": 80.9462,
                                          "label": "Lucknow"}).json()
    assert d["location"]["label"] == "Lucknow"
    client.put("/api/location", json={"lat": 25.4358, "lon": 81.8463,
                                      "label": "Prayagraj, UP"})


def test_hospital_lookup_falls_through_mirrors(monkeypatch):
    """If mirror 1 is down, mirror 2 must be tried — and it must be quick."""
    calls = []

    class R:
        def __init__(self, code, payload):
            self.status_code, self._p = code, payload

        def json(self):
            return self._p

    def fake_post(self, url, data=None, headers=None, **k):
        calls.append(url)
        if "osm.ch" in url or "overpass-api.de" in url:
            raise RuntimeError("mirror unreachable")
        return R(200, {"elements": [
            {"type": "node", "id": 9, "lat": 25.436, "lon": 81.847,
             "tags": {"name": "Mirror Hospital", "emergency": "yes"}}]})

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **k):
            return fake_post(self, url, **k)

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)
    ai_extra._HOSP_CACHE.clear()
    out = ai_extra.nearest_hospitals(25.4358, 81.8463, timeout=25)
    assert len(calls) == 3, calls          # osm.ch + overpass-api.de, then kumi
    assert "kumi" in calls[2]
    assert out[0]["name"] == "Mirror Hospital"


def test_nominatim_is_used_on_the_fast_path(monkeypatch):
    """An emergency must not wait on Overpass: the search API answers first."""
    calls = []

    class R:
        status_code = 200

        def json(self):
            return [{"place_id": 1, "lat": "25.4360", "lon": "81.8470",
                     "display_name": "Fast Hospital, Civil Lines, Prayagraj",
                     "extratags": {}}]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **k):
            calls.append(("nominatim", url))
            return R()

        def post(self, url, **k):
            calls.append(("overpass", url))
            raise RuntimeError("overpass blocked")

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)
    ai_extra._HOSP_CACHE.clear()
    out = ai_extra.nearest_hospitals(25.4358, 81.8463, timeout=6)
    assert calls[0][0] == "nominatim"
    assert out[0]["name"] == "Fast Hospital"
    assert out[0]["source"] == "osm-search"
    assert out[0]["distance_m"] < 500


def test_hospital_lookup_never_blocks_long(monkeypatch):
    """An unreachable map service must fall back fast, not hang the emergency."""
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise RuntimeError("network unreachable")

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)
    ai_extra._HOSP_CACHE.clear()
    out = ai_extra.nearest_hospitals(25.4358, 81.8463, timeout=6)
    assert all(h["source"] == "offline-list" for h in out)


def test_hospitals_are_sorted_nearest_first(monkeypatch):
    """Nearest first, always — an emergency ward 1.6 km away must not outrank
    a plain hospital 300 m away."""
    ai_extra._HOSP_CACHE.clear()
    monkeypatch.setattr(ai_extra, "_nominatim", lambda *a, **k: [
        {"id": "a", "name": "Far (emergency ward)", "phone": "", "distance_m": 2900,
         "lat": 1.0, "lon": 1.0, "emergency": True, "beds": "", "map": "",
         "source": "osm-search"},
        {"id": "b", "name": "Near", "phone": "", "distance_m": 400,
         "lat": 1.0, "lon": 1.0, "emergency": False, "beds": "", "map": "",
         "source": "osm-search"},
    ])
    out = ai_extra.nearest_hospitals(25.4358, 81.8463, timeout=6)
    assert [h["name"] for h in out] == ["Near", "Far (emergency ward)"]


# --------------------------------------------------------------------------
# D5 — family monitor dashboard
# --------------------------------------------------------------------------
def _mk_state(meds=None, activity=None, notifs=None, emergencies=None,
              alarm=None):
    return {"profile": {"name": "Shanti Devi", "age": 72,
                        "conditions": ["Blood pressure"]},
            "meds": meds if meds is not None
                    else [{"id": "m1", "name": "Amlodipine 5mg", "time": "09:00",
                           "taken": True},
                          {"id": "m2", "name": "Metformin 500mg", "time": "14:00",
                           "taken": False}],
            "activity": activity or [], "notifications": notifs or [],
            "emergencies": emergencies or [], "alarm": alarm or {}}


def test_ago_reads_naturally():
    now = 1_000_000.0
    assert ai_extra.ago(now, now) == "just now"
    assert ai_extra.ago(now - 60, now) == "1 min ago"
    assert ai_extra.ago(now - 600, now) == "10 min ago"
    assert ai_extra.ago(now - 7200, now) == "2 h ago"
    assert ai_extra.ago(now - 3 * 86400, now) == "3 d ago"
    assert ai_extra.ago(None, now) == "never"


def test_daily_summary_counts_medicines():
    s = ai_extra.daily_summary(_mk_state(), now=1_700_000_000.0)
    assert s["meds_total"] == 2 and s["meds_taken"] == 1
    assert s["adherence"] == 50
    assert s["pending"] == ["Metformin 500mg"]


def test_daily_summary_marks_overdue_only_after_its_slot():
    meds = [{"id": "a", "name": "Morning pill", "time": "08:00", "taken": False},
            {"id": "b", "name": "Night pill", "time": "23:00", "taken": False}]
    # 10:00 local on a fixed day -> only the 08:00 slot is overdue
    lt = (2026, 10, 30, 10, 0, 0, 0, 0, -1)
    now = time.mktime(lt)
    s = ai_extra.daily_summary(_mk_state(meds=meds), now=now)
    assert s["overdue"] == ["Morning pill"]
    assert "Night pill" in s["pending"]


def test_daily_summary_flags_a_silent_day():
    s = ai_extra.daily_summary(_mk_state(), now=time.time())
    assert s["status"] == "attention"
    assert any("no activity" in c for c in s["concerns"])


def test_daily_summary_is_ok_when_the_day_went_fine():
    now = time.time()
    act = [{"ts": now - 600, "source": "checkin", "text": "mood theek hai"}]
    meds = [{"id": "m1", "name": "Amlodipine", "time": "00:01", "taken": True}]
    s = ai_extra.daily_summary(_mk_state(meds=meds, activity=act), now=now)
    assert s["status"] == "ok"
    assert s["events_today"] == 1
    assert s["checkins"][0]["text"] == "mood theek hai"


def test_daily_summary_escalates_status_for_an_open_incident():
    now = time.time()
    emg = [{"id": "e1", "kind": "sos", "ts": now - 60, "status": "open"}]
    s = ai_extra.daily_summary(_mk_state(emergencies=emg), now=now)
    assert s["status"] == "emergency"
    assert s["incidents_open"] == 1
    assert any("unresolved" in c for c in s["concerns"])


def test_daily_summary_ignores_yesterdays_activity():
    now = time.time()
    act = [{"ts": now - 2 * 86400, "source": "agent", "text": "old news"}]
    s = ai_extra.daily_summary(_mk_state(activity=act), now=now)
    assert s["events_today"] == 0


def test_monitor_endpoint_mirrors_the_whole_app():
    r = client.get("/api/monitor")
    assert r.status_code == 200
    d = r.json()
    for key in ("profile", "meds", "activity", "notifications", "alarm",
                "emergencies", "location", "card", "summary", "monitor"):
        assert key in d, f"/api/monitor is missing {key}"
    assert d["card"]["name"] == "Shanti Devi"
    assert d["summary"]["status"] in ("ok", "attention", "emergency")
    assert isinstance(d["unread"], int)


def test_monitor_ack_writes_onto_the_open_incident(monkeypatch):
    from app.main import STATE
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    STATE["emergencies"].clear()
    eid = client.post("/api/sos").json()["alarm"]["emergency_id"]

    d = client.post("/api/monitor/ack", json={"by": "Priya"}).json()
    assert eid in d["acked"]

    rec = client.get(f"/api/emergency/{eid}").json()
    assert rec["ack_by"] == "Priya"
    assert rec["ack_at"]
    assert rec["timeline"][-1]["stage"] == "ack"
    assert "Priya" in rec["timeline"][-1]["text"]
    # the incident stays open until someone actually closes it
    assert rec["status"] == "open"


def test_monitor_ack_clears_the_unread_bell():
    from app.main import STATE
    STATE["notifications"].clear()
    STATE["monitor"] = {"last_ack": None, "acked_by": None,
                        "acked_incident": None}
    client.post("/api/sos")
    assert client.get("/api/monitor").json()["unread"] > 0

    d = client.post("/api/monitor/ack", json={"by": "Rohit"}).json()
    assert d["unread"] == 0
    assert d["monitor"]["acked_by"] == "Rohit"
    assert d["monitor"]["last_ack"]


def test_monitor_ack_with_no_open_incident_is_harmless():
    from app.main import STATE
    for e in STATE["emergencies"]:
        e["status"] = "closed"
    r = client.post("/api/monitor/ack", json={"by": "Priya"})
    assert r.status_code == 200 and r.json()["acked"] == []


def test_family_chat_does_not_fire_the_elder_triage_flow(monkeypatch):
    """'mom has fever' from the monitor must answer, not ring the alarm."""
    from app.main import STATE
    STATE["alarm"] = None
    seen = {}

    def fake_agent(message, lang="en", state="", role="elder", summary=None):
        seen["role"] = role
        seen["state"] = state
        seen["summary"] = summary
        return {"reply": "She has no fever logged today.", "actions": [],
                "source": "test"}

    monkeypatch.setattr(ai, "agent", fake_agent)
    d = client.post("/api/chat",
                    json={"message": "mom has fever", "role": "family"}).json()
    assert d["kind"] == "agent", "family chat must not return a triage card"
    assert seen["role"] == "family"
    assert "status=" in seen["state"], "family brain needs today's summary"
    assert seen["summary"] and "status" in seen["summary"]
    assert STATE["alarm"] is None


def test_elder_chat_still_triages_normally(monkeypatch):
    monkeypatch.setattr(ai, "triage",
                        lambda m, l: {"severity": 5, "category": "fever",
                                      "summary_en": "f", "first_question": "?",
                                      "calm_reply": "ok", "home_care": [],
                                      "red_flags": [], "doctor_call": False,
                                      "source": "test"})
    d = client.post("/api/chat", json={"message": "mujhe bukhaar hai"}).json()
    assert d["kind"] == "triage"


def test_family_agent_prompt_speaks_about_the_elder_in_third_person():
    assert "third person" in ai.FAMILY_SYS
    assert "{lang}" in ai.FAMILY_SYS
    d = ai.agent("how is she today?", "en", "name=Shanti Devi",
                 role="family")
    assert isinstance(d["reply"], str) and d["reply"]


def test_offline_family_answers_medicines_from_the_summary():
    s = ai_extra.daily_summary(_mk_state(), now=time.time())
    out = ai_extra.offline_family("did she take her medicines?", "en", s)
    assert "1 of 2" in out
    assert "Metformin" in out


def test_offline_family_answers_how_is_she():
    now = time.time()
    act = [{"ts": now - 300, "source": "checkin", "text": "mood theek hai"}]
    meds = [{"id": "m1", "name": "Amlodipine", "time": "00:01", "taken": True}]
    s = ai_extra.daily_summary(_mk_state(meds=meds, activity=act), now=now)
    out = ai_extra.offline_family("how is she today?", "en", s)
    assert "normal" in out.lower() or "attention" in out.lower()
    assert "1/1" in out


def test_offline_family_reports_an_open_incident():
    now = time.time()
    emg = [{"id": "e1", "kind": "fall", "ts": now - 60, "status": "open"}]
    s = ai_extra.daily_summary(_mk_state(emergencies=emg), now=now)
    out = ai_extra.offline_family("any incidents?", "en", s)
    assert "incident" in out.lower() and "unresolved" in out.lower()


def test_offline_family_admits_what_it_does_not_track():
    s = ai_extra.daily_summary(_mk_state(), now=time.time())
    out = ai_extra.offline_family("did she eat lunch?", "en", s)
    assert "meals" in out.lower()


def test_family_chat_falls_back_to_the_summary_when_no_llm(monkeypatch):
    """No keys at all: the monitor still gives a real answer, not a shrug."""
    monkeypatch.setattr(ai, "llm", lambda messages: ("not json", "offline"))
    d = client.post("/api/chat",
                    json={"message": "did she take her medicines?",
                          "role": "family"}).json()
    assert d["kind"] == "agent"
    assert d["source"] == "offline-fallback"
    assert "medicines" in d["reply"].lower()


def test_closing_an_incident_stands_the_alarm_down(monkeypatch):
    from app.main import STATE
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    STATE["emergencies"].clear()
    STATE["alarm"] = None
    STATE["notifications"].clear()
    STATE["monitor"] = {"last_ack": None, "acked_by": None,
                        "acked_incident": None}
    eid = client.post("/api/sos").json()["alarm"]["emergency_id"]
    assert STATE["alarm"]["status"] == "escalated"

    client.post(f"/api/emergency/{eid}/close")
    assert STATE["alarm"]["status"] == "resolved"
    # ...and the monitor stops screaming
    assert client.get("/api/monitor").json()["summary"]["status"] != "emergency"


def test_client_and_state_are_the_same_app(monkeypatch):
    """Guard: the fixtures must drive the same app object the tests import.

    The audioop test drops `app.*` from sys.modules and re-imports; if the
    rebind there is ever lost, every later test would drive one app while
    asserting against another and quietly stop testing anything.
    """
    from app.main import STATE
    monkeypatch.setattr(ai_extra, "nearest_hospitals",
                        lambda *a, **k: ai_extra._fallback_hospitals())
    before = len(STATE["emergencies"])
    client.post("/api/sos")
    assert len(STATE["emergencies"]) == before + 1


# --------------------------------------------------------------------------
# D6 — daily companion: proactive check-ins
# --------------------------------------------------------------------------
def _ck_state(checkins=None, sched=None):
    return {"checkins": checkins if checkins is not None else [],
            "checkin_schedule": sched or dict(ai_extra.CHECKIN_SCHEDULE)}


def _at(hour, minute=0, day=30):
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


def test_checkin_script_is_in_the_elder_language():
    en = ai_extra.checkin_script("morning", "en", "Shanti")
    hi = ai_extra.checkin_script("morning", "hi", "Shanti")
    assert len(en) == 3 and "Shanti" in en[0]
    assert hi != en, "Hindi must not come back as English"
    assert all(ai_extra.checkin_script(k, l, "X")
               for k in ai_extra.CHECKIN_KINDS for l in
               ("en", "hi", "bn", "ta", "te", "mr", "gu", "es", "fr"))


def test_unknown_language_falls_back_to_english():
    assert ai_extra.checkin_script("morning", "xx", "X") == \
        ai_extra.checkin_script("morning", "en", "X")


def test_mood_reads_a_good_answer():
    assert ai_extra.extract_mood("I slept well, feeling fine", "en")["mood"] \
        == "good"


def test_mood_reads_a_bad_answer_and_flags_symptoms():
    r = ai_extra.extract_mood("mujhe bukhaar aur chakkar hai", "hi")
    assert r["mood"] == "bad"
    assert "fever" in r["flags"] and "dizziness" in r["flags"]


def test_denied_symptoms_are_not_reported():
    """'dard nahi hai, sab theek hai' is good news, not a pain report."""
    r = ai_extra.extract_mood("dard nahi hai, sab theek hai", "hi")
    assert r["mood"] == "good"
    assert r["flags"] == []


def test_negation_stays_in_its_own_clause():
    """'theek nahi, bukhaar hai' — the denial belongs to 'theek', not fever."""
    r = ai_extra.extract_mood("theek nahi, bukhaar hai", "hi")
    assert r["mood"] == "bad" and "fever" in r["flags"]


def test_bad_does_not_hide_inside_badhiya():
    assert ai_extra.extract_mood("sab badhiya hai", "hi")["mood"] == "good"
    assert ai_extra.extract_mood("I feel bad", "en")["mood"] == "bad"


def test_a_fall_mention_is_never_neutral():
    r = ai_extra.extract_mood("neecha gir gayi", "hi")
    assert r["mood"] == "bad" and "mobility" in r["flags"]


def test_unclear_answers_stay_unknown():
    assert ai_extra.extract_mood("hmm", "hi")["mood"] == "unknown"


def test_checkin_record_folds_three_answers():
    rec = ai_extra.checkin_record("morning", "en", [
        {"q": "How did you sleep?", "a": "slept well"},
        {"q": "Any pain?", "a": "no pain at all"},
        {"q": "Medicine?", "a": "yes, taken"},
    ], now=_at(9))
    assert rec["status"] == "answered" and rec["kind"] == "morning"
    assert rec["mood"] == "good"
    assert rec["flags"] == ["sleep"] or rec["flags"] == []
    assert len(rec["answers"]) == 3


def test_checkin_record_reports_symptoms_plainly():
    rec = ai_extra.checkin_record("evening", "hi", [
        {"q": "kaisa din?", "a": "pair mein dard hai"},
    ], now=_at(21))
    assert rec["mood"] == "bad" and "pain" in rec["flags"]


def test_due_checkin_appears_after_its_slot():
    d = ai_extra.due_checkin(_ck_state(), now=_at(10))
    assert d and d["kind"] == "morning" and d["overdue_min"] == 60


def test_due_checkin_stays_quiet_before_the_slot():
    assert ai_extra.due_checkin(_ck_state(), now=_at(7)) is None


def test_due_checkin_does_not_repeat_once_answered():
    st = _ck_state([{"kind": "morning", "ts": _at(9), "status": "answered"}])
    assert ai_extra.due_checkin(st, now=_at(10)) is None


def test_due_checkin_does_not_repeat_once_missed():
    st = _ck_state([{"kind": "morning", "ts": _at(9), "status": "missed"}])
    assert ai_extra.due_checkin(st, now=_at(10)) is None


def test_checkins_can_be_switched_off():
    st = _ck_state(sched={"morning": "09:00", "evening": "21:00",
                          "enabled": False})
    assert ai_extra.due_checkin(st, now=_at(22)) is None


def test_checkin_due_endpoint_serves_the_script():
    from app.main import STATE
    STATE["checkins"] = []
    STATE["checkin_schedule"] = dict(ai_extra.CHECKIN_SCHEDULE)
    d = client.get("/api/checkin/due?lang=hi").json()
    # depends on the wall clock: either nothing is due, or a script comes back
    if d["due"]:
        assert len(d["questions"]) == 3
        assert d["kind"] in ai_extra.CHECKIN_KINDS


def test_checkin_answer_is_stored_and_shown_on_the_monitor():
    from app.main import STATE
    STATE["checkins"] = []
    STATE["notifications"] = []
    d = client.post("/api/checkin/answer", json={
        "kind": "morning", "lang": "en",
        "answers": [{"q": "sleep?", "a": "slept well"},
                    {"q": "pain?", "a": "no pain"}],
    }).json()
    assert d["record"]["status"] == "answered"
    assert d["record"]["mood"] == "good"
    assert STATE["checkins"][0]["id"] == d["record"]["id"]
    assert any(a["source"] == "checkin" for a in STATE["activity"])


def test_a_bad_checkin_alerts_the_family():
    from app.main import STATE
    STATE["checkins"] = []
    STATE["notifications"] = []
    client.post("/api/checkin/answer", json={
        "kind": "evening", "lang": "hi",
        "answers": [{"q": "kaisa din?", "a": "pair mein dard hai"}],
    })
    urgent = [n for n in STATE["notifications"] if n["kind"] == "emergency"]
    assert urgent, "feeling unwell must ring the monitor bell"
    assert "dard" in urgent[0]["body"] or "pain" in urgent[0]["body"]


def test_skipping_a_checkin_stops_the_nagging():
    from app.main import STATE
    STATE["checkins"] = []
    d = client.post("/api/checkin/skip", json={"kind": "morning"}).json()
    assert d["record"]["status"] == "skipped"
    st = {"checkins": STATE["checkins"],
          "checkin_schedule": STATE["checkin_schedule"]}
    assert ai_extra.due_checkin(st, now=_at(10)) is None


def test_schedule_can_be_changed():
    from app.main import STATE
    d = client.put("/api/checkin/schedule",
                   json={"morning": "08:30", "evening": "20:00",
                         "digest": "20:30", "enabled": True}).json()
    assert d["schedule"]["morning"] == "08:30"
    assert d["schedule"]["digest"] == "20:30"
    client.put("/api/checkin/schedule",
               json={"morning": "09:00", "evening": "21:00", "digest": "21:30"})


def test_daily_digest_reads_like_a_note_to_the_family():
    from app.main import STATE
    STATE["checkins"] = [ai_extra.checkin_record(
        "morning", "en", [{"q": "sleep?", "a": "slept well"}], now=time.time())]
    d = ai_extra.daily_digest(STATE)
    assert d["answered"] == 1 and d["mood"] == "good"
    assert "Shanti" in d["text"]
    assert "Medicines:" in d["text"]
    assert isinstance(d["checkins"], list)


def test_daily_digest_endpoint_works():
    r = client.get("/api/summary/daily")
    assert r.status_code == 200
    assert "text" in r.json() and "date" in r.json()


def test_digest_can_be_pushed_to_the_monitor():
    from app.main import STATE
    STATE["last_digest"] = None
    STATE["notifications"] = []
    r = client.post("/api/summary/daily/push").json()
    assert r["digest"]["text"]
    assert STATE["last_digest"]["date"] == r["digest"]["date"]
    assert any("Daily summary" in n["title"] for n in STATE["notifications"])


def test_scheduler_marks_an_unanswered_checkin_as_missed():
    from app.main import STATE, _scheduler_tick
    STATE["checkins"] = []
    STATE["notifications"] = []
    STATE["checkin_schedule"] = {"morning": "09:00", "evening": "21:00",
                                 "digest": "23:59", "enabled": True}
    did = _scheduler_tick(now=_at(12))          # 3 h past the morning slot
    assert did == ["missed:morning"]
    assert STATE["checkins"][0]["status"] == "missed"
    urgent = [n for n in STATE["notifications"] if n["kind"] == "emergency"]
    assert urgent and "did not answer" in urgent[0]["body"]


def test_scheduler_waits_out_the_grace_period():
    from app.main import STATE, _scheduler_tick
    STATE["checkins"] = []
    STATE["notifications"] = []
    STATE["checkin_schedule"] = {"morning": "09:00", "evening": "21:00",
                                 "digest": "23:59", "enabled": True}
    assert _scheduler_tick(now=_at(9, 10)) == []     # only 10 min late
    assert STATE["checkins"] == []


def test_scheduler_sends_the_digest_once_a_day():
    from app.main import STATE, _scheduler_tick
    STATE["checkins"] = [
        {"id": "m", "kind": "morning", "ts": _at(9), "status": "answered",
         "mood": "good", "score": 3, "flags": [], "answers": [],
         "summary": "fine"},
        {"id": "e", "kind": "evening", "ts": _at(21), "status": "answered",
         "mood": "good", "score": 3, "flags": [], "answers": [],
         "summary": "fine"},
    ]
    STATE["notifications"] = []
    STATE["last_digest"] = None
    STATE["checkin_schedule"] = {"morning": "09:00", "evening": "21:00",
                                 "digest": "21:30", "enabled": True}

    did = _scheduler_tick(now=_at(22))
    assert any(x.startswith("digest:") for x in did), did
    assert not any(x.startswith("missed:") for x in did), \
        "answered check-ins must not be marked missed"

    before = len(STATE["notifications"])
    # an hour later: the digest must not go out a second time
    again = _scheduler_tick(now=_at(23))
    assert not any(x.startswith("digest:") for x in again), again
    assert len(STATE["notifications"]) == before


def test_missed_checkin_shows_up_as_a_concern_on_the_monitor():
    now = time.time()
    start = ai_extra._day_start(now)
    st = _mk_state()
    st["checkins"] = [{"kind": "morning", "ts": start + 60,
                       "status": "missed", "flags": [], "mood": None}]
    s = ai_extra.daily_summary(st, now=now)
    assert s["checkins_missed"] == 1
    assert any("did not answer" in c for c in s["concerns"])
    assert s["status"] == "attention"


def test_a_mentioned_topic_is_not_a_concern():
    """'I slept well' must not ping the family — only symptoms do."""
    now = time.time()
    start = ai_extra._day_start(now)
    st = _mk_state()
    st["checkins"] = [{
        "id": "c1", "kind": "morning", "ts": start + 60, "status": "answered",
        "mood": "good", "score": 3, "flags": ["sleep", "appetite"],
        "answers": [], "summary": "feeling well · sleep, appetite"}]
    s = ai_extra.daily_summary(st, now=now)
    assert not any("flagged" in c for c in s["concerns"]), s["concerns"]
    assert s["status"] != "emergency"


def test_a_symptom_raises_a_concern():
    now = time.time()
    start = ai_extra._day_start(now)
    st = _mk_state()
    st["checkins"] = [{
        "id": "c1", "kind": "evening", "ts": start + 60, "status": "answered",
        "mood": "bad", "score": 1, "flags": ["pain", "sleep"],
        "answers": [], "summary": "not well · pain, sleep"}]
    s = ai_extra.daily_summary(st, now=now)
    assert any("flagged" in c and "pain" in c for c in s["concerns"])
    assert all("sleep" not in c for c in s["concerns"])
    assert s["status"] == "attention"


def test_mood_reports_the_latest_checkin_not_the_oldest():
    """Records are stored newest-first, so "last" must mean latest in time."""
    now = time.time()
    start = ai_extra._day_start(now)
    st = _mk_state()
    st["checkins"] = [
        {"id": "e", "kind": "evening", "ts": start + 3600, "status": "answered",
         "mood": "bad", "score": 1, "flags": ["pain"], "answers": [],
         "summary": "not well"},
        {"id": "m", "kind": "morning", "ts": start + 60, "status": "answered",
         "mood": "good", "score": 3, "flags": [], "answers": [],
         "summary": "fine"},
    ]
    assert ai_extra.daily_summary(st, now=now)["mood"] == "bad"


# --------------------------------------------------------------------------
# D7 — Sehat Board
# --------------------------------------------------------------------------
def _sehat_state(**kw):
    st = _mk_state()
    st.update({"vitals": [], "med_log": []})
    st.update(kw)
    return st


def test_bmi_uses_asian_indian_cutoffs():
    assert ai_extra.bmi(62, 165)["band"] == "normal"
    assert ai_extra.bmi(64, 165)["band"] == "overweight"   # 23.5
    assert ai_extra.bmi(85, 165)["band"] == "obese"
    assert ai_extra.bmi(45, 165)["band"] == "underweight"


def test_bmi_survives_missing_or_bad_numbers():
    assert ai_extra.bmi(None, None) is None
    assert ai_extra.bmi("abc", 0) is None
    assert ai_extra.bmi(0, 170) is None


def test_vital_bands_match_clinical_ranges():
    assert ai_extra.vital_band("bp_sys", 118) == "normal"
    assert ai_extra.vital_band("bp_sys", 125) == "elevated"
    assert ai_extra.vital_band("bp_sys", 135) == "high"
    assert ai_extra.vital_band("bp_sys", 150) == "very high"
    assert ai_extra.vital_band("bp_sys", 190) == "critical"
    assert ai_extra.vital_band("sugar", 105) == "normal"
    assert ai_extra.vital_band("sugar", 210) == "very high"
    assert ai_extra.vital_band("pulse", 72) == "normal"
    assert ai_extra.vital_band("pulse", 45) == "low"
    # low oxygen is the danger, not high
    assert ai_extra.vital_band("spo2", 98) == "normal"
    assert ai_extra.vital_band("spo2", 93) == "low"
    assert ai_extra.vital_band("spo2", 88) == "critical"
    assert ai_extra.vital_band("spo2", None) is None


def test_vital_entry_keeps_only_real_numbers():
    e = ai_extra.vital_entry({"bp_sys": "132", "sugar": "", "pulse": None})
    assert e["bp_sys"] == 132.0
    assert e["sugar"] is None and e["pulse"] is None
    assert e["bands"]["bp_sys"] == "high"
    assert "sugar" not in e["bands"]


def test_latest_vitals_takes_the_newest_of_each():
    now = time.time()
    st = _sehat_state(vitals=[
        ai_extra.vital_entry({"bp_sys": 120}, ts=now - 3600),
        ai_extra.vital_entry({"bp_sys": 150, "spo2": 94}, ts=now - 60),
    ])
    v = ai_extra.latest_vitals(st["vitals"])
    assert v["bp_sys"]["value"] == 150 and v["bp_sys"]["band"] == "very high"
    assert v["spo2"]["value"] == 94 and v["spo2"]["band"] == "low"
    assert "ago" in v["bp_sys"]


def test_vitals_series_is_oldest_first_and_windowed():
    now = time.time()
    st = _sehat_state(vitals=[
        ai_extra.vital_entry({"sugar": 100}, ts=now - 20 * 86400),
        ai_extra.vital_entry({"sugar": 110}, ts=now - 3 * 86400),
        ai_extra.vital_entry({"sugar": 120}, ts=now - 3600),
    ])
    s = ai_extra.vitals_series(st["vitals"], 14, now)
    assert [p["v"] for p in s["sugar"]] == [110.0, 120.0]


def test_points_reward_the_things_the_design_says():
    now = time.time()
    start = ai_extra._day_start(now)
    st = _sehat_state(
        checkins=[{"status": "answered", "ts": start + 3600},
                  {"status": "answered", "ts": start + 7200}],
        med_log=[{"name": "a", "ts": start + 3600},
                 {"name": "b", "ts": start + 3600}],
        vitals=[{"ts": start + 5000}],
        activity=[{"ts": start + 6000, "source": "note"}],
    )
    d = ai_extra.day_points(st, start, start + 86400)
    # 2 check-ins x8 + 2 meds x10 + 1 activity x5 + 1 vitals x4 = 45
    assert d["points"] == 45
    assert d["checkins"] == 2 and d["meds"] == 2


def test_points_punish_a_missed_checkin():
    now = time.time()
    start = ai_extra._day_start(now)
    st = _sehat_state(checkins=[{"status": "missed", "ts": start + 100}])
    assert ai_extra.day_points(st, start, start + 86400)["points"] == -5


def test_points_are_capped_so_chatter_cannot_farm_them():
    now = time.time()
    start = ai_extra._day_start(now)
    st = _sehat_state(activity=[{"ts": start + i, "source": "agent"}
                                for i in range(50)])
    d = ai_extra.day_points(st, start, start + 86400)
    assert d["points"] == ai_extra.POINTS_CAP["chat"] * ai_extra.POINTS["chat"]
    assert d["activity"] == 0, "a chat turn must not also score as a walk"


def test_weekly_board_covers_seven_days_and_ranks_them():
    b = ai_extra.weekly_board(_sehat_state())
    assert len(b["days"]) == 7
    assert b["days"][-1]["today"] is True
    assert [d["rank"] for d in b["ranked"]] == [1, 2, 3, 4, 5, 6, 7] or \
        len({d["rank"] for d in b["ranked"]}) == 7
    assert b["today"]["date"] == b["days"][-1]["date"]


def test_weekly_board_ranks_her_own_week_not_strangers():
    """There are no other users in this build; the board must not invent any."""
    now = time.time()
    start = ai_extra._day_start(now)
    st = _sehat_state(med_log=[{"name": "a", "ts": start - 86400}
                               for _ in range(4)])
    b = ai_extra.weekly_board(st, now)
    assert b["best"]["date"] == time.strftime(
        "%Y-%m-%d", time.localtime(start - 86400))
    assert all("peer" not in str(d) for d in b["days"])


def test_streak_counts_consecutive_active_days():
    now = time.time()
    start = ai_extra._day_start(now)
    st = _sehat_state(med_log=[
        {"name": "a", "ts": start - i * 86400} for i in range(3)])
    assert ai_extra.weekly_board(st, now)["streak"] == 3


def test_sehat_board_bundles_body_vitals_and_week():
    st = _sehat_state(profile={"name": "Shanti Devi", "age": 72,
                               "weight_kg": 62, "height_cm": 155,
                               "conditions": ["BP"]},
                      vitals=[ai_extra.vital_entry({"bp_sys": 150})])
    b = ai_extra.sehat_board(st)
    assert b["bmi"]["band"] == "obese"
    assert b["vitals_latest"]["bp_sys"]["band"] == "very high"
    assert "bp_sys" in b["alerts"], "an out-of-range reading must be flagged"
    assert b["board"]["total"] >= 0


def test_vitals_endpoint_rejects_an_empty_payload():
    r = client.post("/api/vitals", json={})
    assert r.status_code == 400


def test_vitals_endpoint_stores_a_reading():
    from app.main import STATE
    STATE["vitals"] = []
    STATE["notifications"] = []
    d = client.post("/api/vitals", json={"bp_sys": 118, "bp_dia": 78,
                                         "pulse": 72}).json()
    assert d["record"]["bp_sys"] == 118.0
    assert STATE["vitals"][0]["id"] == d["record"]["id"]
    assert not any(n["kind"] == "emergency" for n in STATE["notifications"])


def test_an_out_of_range_reading_alerts_the_family():
    from app.main import STATE
    STATE["vitals"] = []
    STATE["notifications"] = []
    client.post("/api/vitals", json={"bp_sys": 185, "bp_dia": 122})
    urgent = [n for n in STATE["notifications"] if n["kind"] == "emergency"]
    assert urgent, "a crisis reading must ring the monitor"
    assert "185" in urgent[0]["body"]


def test_ticking_a_medicine_leaves_a_dated_row():
    from app.main import STATE
    STATE["med_log"] = []
    name = STATE["meds"][0]["name"]
    client.post("/api/meds/taken", json={"name": name})
    assert any(e["name"] == name for e in STATE["med_log"])
    # unticking removes only today's row
    client.post("/api/meds/taken", json={"name": name})
    assert not any(e["name"] == name for e in STATE["med_log"])


def test_the_agent_can_log_a_reading_from_chat():
    from app.main import STATE, _apply_actions
    STATE["vitals"] = []
    done = _apply_actions([{"type": "vital", "bp_sys": 130, "bp_dia": 85}])
    assert done and "130" in done[0]
    assert STATE["vitals"][0]["bp_sys"] == 130.0
    assert STATE["vitals"][0]["bands"]["bp_sys"] == "high"


def test_agent_vitals_ignore_numbers_that_are_not_numbers():
    from app.main import STATE, _apply_actions
    STATE["vitals"] = []
    done = _apply_actions([{"type": "vital", "sugar": "not-a-number"},
                           {"type": "vital", "pulse": 80}])
    rec = STATE["vitals"][0]
    assert rec["pulse"] == 80.0
    assert rec["sugar"] is None, "never record a reading nobody said"
    assert rec["bands"] == {"pulse": "normal"}
    assert done == ["vitals logged: pulse=80"]


def test_sehat_endpoint_serves_the_whole_board():
    r = client.get("/api/sehat")
    assert r.status_code == 200
    d = r.json()
    for key in ("profile", "bmi", "vitals_latest", "vitals_series",
                "alerts", "board", "points_today"):
        assert key in d, f"/api/sehat missing {key}"


def test_board_endpoint_exposes_the_scoring_rules():
    r = client.get("/api/board").json()
    assert r["points"]["checkin"] == 8 and r["points"]["med"] == 10
    assert len(r["days"]) == 7


def test_the_board_says_so_when_its_history_is_sample_data():
    """Six days of shipped sample data must be labelled, not passed off."""
    now = time.time()
    start = ai_extra._day_start(now)
    st = _sehat_state(checkins=[
        {"status": "answered", "ts": start - 86400, "source": "demo-seed"}])
    assert ai_extra.weekly_board(st, now)["seeded"] is True

    real = _sehat_state(checkins=[
        {"status": "answered", "ts": start - 86400, "source": "voice"}])
    assert ai_extra.weekly_board(real, now)["seeded"] is False


def test_seeded_history_is_stamped_so_it_can_never_be_mistaken_for_real():
    from app.main import STATE
    rows = [c for c in STATE.get("checkins", []) if c.get("source") == "demo-seed"]
    if rows:                       # only meaningful with the seed enabled
        assert all(c["ts"] < ai_extra._day_start(time.time()) for c in rows), \
            "sample data must never land on today"


def test_empty_llm_reply_falls_through_to_the_next_provider(monkeypatch):
    """A reasoning model that spends its budget thinking answers with an empty
    body and still returns HTTP 200. That must count as a failure — otherwise
    the chain stops at Baseten, Groq is never tried, and the user just sees
    the offline fallback with nothing in the log to explain it."""
    calls = []
    monkeypatch.setattr(ai, "provider_order",
                        lambda: ["baseten", "groq", "offline"])
    monkeypatch.setattr(ai, "_baseten",
                        lambda body: (calls.append("baseten"), "")[1])
    monkeypatch.setattr(ai, "_groq",
                        lambda body: (calls.append("groq"), "answer from groq")[1])

    text, prov = ai.llm([{"role": "user", "content": "how is she today?"}])

    assert calls == ["baseten", "groq"], "empty reply must not end the chain"
    assert prov == "groq"
    assert text == "answer from groq"


def test_baseten_leaves_room_for_reasoning(monkeypatch):
    """Muse Spark thinks in tokens too. 700 was enough for a plain model; the
    monitor's ten-line state summary made it run out, so the ceiling is higher
    and the effort is lower."""
    import os
    monkeypatch.setenv("BASETEN_MODEL", "meta-models/muse-spark-open")
    body = ai._baseten_body("meta-models/muse-spark-open", [])
    assert body["max_tokens"] >= 2000
    assert body["reasoning_effort"] == "low"


def test_prompts_have_real_line_breaks_not_literal_backslash_n():
    """FAMILY_SYS once used `\\\\n`, which is a literal backslash-n, not a
    newline. The whole JSON spec collapsed onto one run-on line, the model
    answered in prose instead of JSON, and the monitor silently fell back to
    the offline mirror — while the elder, whose prompt was fine, worked
    perfectly. Nothing crashed, so only this assertion catches it."""
    for name in ("AGENT_SYS", "FAMILY_SYS"):
        prompt = getattr(ai, name)
        assert "\\n" not in prompt, (
            f"{name} contains a literal backslash-n; its formatting is "
            f"collapsed into one line and the model will not return JSON")
        assert prompt.count("\n") >= 3, (
            f"{name} has only {prompt.count(chr(10))} real newlines")


def test_family_and_elder_prompts_are_both_well_formed():
    """The two prompts differ in wording, never in structural quality. If one
    is well formed and the other is not, only one seat of the app works."""
    for name in ("AGENT_SYS", "FAMILY_SYS"):
        prompt = getattr(ai, name)
        assert '"reply"' in prompt, f"{name} does not ask for a reply field"
        assert '"actions"' in prompt, f"{name} does not describe actions"
        assert "{lang}" in prompt, f"{name} lost its language placeholder"


def test_parse_json_loose_handles_a_preamble():
    """A reasoning model that says 'Sure!' first used to defeat the greedy
    `\\{.*\\}` match and lose a perfectly good answer."""
    got = ai.parse_json_loose(
        'Sure! Here you go: {"reply": "she took her BP pill", "actions": []} '
        'Hope that helps.')
    assert got and got["reply"] == "she took her BP pill"


def test_parse_json_loose_strips_reasoning_blocks():
    got = ai.parse_json_loose(
        '<think>she is 72, check the meds list</think>'
        '{"reply": "all doses taken today", "actions": []}')
    assert got and got["reply"] == "all doses taken today"


def test_parse_json_loose_survives_a_brace_inside_the_reply():
    got = ai.parse_json_loose('{"reply": "use { and } carefully", "actions": []}')
    assert got and got["reply"] == "use { and } carefully"


def test_prose_answer_is_used_not_thrown_away(monkeypatch):
    """If the model answers in plain prose, showing the offline mirror is
    strictly worse than showing what it actually said."""
    monkeypatch.setattr(ai, "provider_order", lambda: ["baseten", "offline"])
    monkeypatch.setattr(ai, "_baseten",
                        lambda body: "She took all three medicines today.")
    out = ai.agent("how is she?", "en", "name=Shanti", "family", None)
    assert out["source"] == "baseten"
    assert "three medicines" in out["reply"]
    assert "offline" not in out["source"]


def test_replies_are_pinned_to_the_app_language_not_the_users():
    """The JSON spec used to say "in their language", which the model read as
    'mirror whatever the user typed'. With the app in Hindi and the elder
    writing English, she got English back. The spec and the closing rule must
    both name the app's language."""
    for name in ("AGENT_SYS", "FAMILY_SYS"):
        prompt = getattr(ai, name)
        # the reply field names the language explicitly
        assert "written in {lang}" in prompt, f"{name}: reply field is ambiguous"
        # and there is an explicit rule not to mirror the user
        assert "LANGUAGE RULE" in prompt, f"{name}: no explicit language rule"
        assert "do not mirror" in prompt or "even when they write" in prompt, \
            f"{name}: does not forbid mirroring the user's language"
        # and the language appears more than once, so it cannot be dropped
        assert prompt.count("{lang}") >= 3, \
            f"{name}: language mentioned only {prompt.count('{lang}')} times"


def test_a_wrong_language_reply_is_translated_not_shipped(monkeypatch):
    """Asking the model to reply in Hindi was not enough — it mirrored the
    English it was addressed in. Once the reply is wrong it must be corrected,
    because the elder cannot read it."""
    seen = []
    monkeypatch.setattr(ai, "llm", lambda msgs: (
        seen.append(msgs), "आज उन्होंने तीनों दवाइयाँ ले ली हैं", "baseten")[1:])
    out = ai.reply_in_lang("She has taken all three medicines today.", "hi")
    assert len(seen) == 1, "a wrong-language reply must trigger a translation"
    assert "आज" in out


def test_a_correct_language_reply_costs_nothing(monkeypatch):
    """No extra model call when the answer is already in the right script."""
    seen = []
    monkeypatch.setattr(ai, "llm", lambda msgs: (
        seen.append(msgs), "x", "baseten")[1:])
    out = ai.reply_in_lang("आज आप तीनों गोलियाँ ले चुकी हैं", "hi")
    assert seen == [], "correct reply must not be re-translated"
    assert "तीनों" in out


def test_guard_also_covers_the_offline_mirror(monkeypatch):
    """The guard used to sit after a successful JSON parse, so the offline
    mirror — the path that actually produced the English replies — skipped it
    entirely. Every exit has to be wrapped."""
    seen = []

    def smart(msgs):
        sys_txt = " ".join(m.get("content", "") for m in msgs)
        if "translator" in sys_txt.lower():
            seen.append("TRANSLATE")
            return "आज आप ठीक हैं", "baseten"
        seen.append("ANSWER")
        return "", "offline"          # force the mirror

    monkeypatch.setattr(ai, "llm", smart)
    out = ai.agent("how is she", "hi", "name=Shanti", "elder", None)
    assert out["source"] == "offline-fallback"
    assert "TRANSLATE" in seen, "offline reply must be language-corrected too"


def test_a_hindi_answer_costs_no_second_call(monkeypatch):
    calls = []

    def hindi(msgs):
        calls.append(1)
        return ('{"reply": "आज आप तीनों गोलियाँ ले चुकी हैं",'
                ' "actions": []}'), "baseten"

    monkeypatch.setattr(ai, "llm", hindi)
    ai.agent("how is she", "hi", "name=Shanti", "elder", None)
    assert len(calls) == 1, "an already-correct reply must not be re-translated"
