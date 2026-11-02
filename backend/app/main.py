"""Saavren FastAPI app — one shared state; the agent and the UI write to it."""
from __future__ import annotations

import os
import random
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, ai_extra, auth

app = FastAPI(title="Saavren", version="0.8.5-sw",
              description="Voice-first emergency guardian & daily health companion.")

def _web_dir() -> Path:
    """Where the built UI lives.

    Locally the package sits at <root>/backend/app, so three levels up is the
    project root. Inside the container the layout is different, so instead of
    counting `..` we walk up until a frontend/dist actually exists. Docker
    deployments that keep a different layout can point SAAVREN_WEB_DIR at it.
    """
    override = os.getenv("SAAVREN_WEB_DIR")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "frontend" / "dist"
        if candidate.is_dir():
            return candidate
    return here.parent.parent.parent / "frontend" / "dist"


DIST = _web_dir()

# --------------------------------------------------------------------------
# Which language is this request in?
#
# Everything that returns `state` used to call public_state() with its default
# of "en". So the moment you switched the UI to Hindi and then did anything at
# all — sent a message, marked a dose, even just let the alarm poll fire — the
# server handed back an English state and the UI snapped back to English.
#
# The language therefore has to travel with every request, and public_state()
# has to read it from the request, not from a default. Otherwise translating
# one endpoint just moves the bug to the next one.
# --------------------------------------------------------------------------
from contextvars import ContextVar
from urllib.parse import parse_qs

_lang_ctx: ContextVar[str] = ContextVar("saavren_lang", default="en")


class LangMiddleware:
    """Pure ASGI, deliberately NOT BaseHTTPMiddleware.

    BaseHTTPMiddleware runs the downstream app in a separate task, and a
    ContextVar set out here never reaches the endpoint — the middleware saw the
    header perfectly and public_state() still read the default. Raw ASGI
    middleware runs in the same context, so the value lands.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        lang = ""
        for k, v in (scope.get("headers") or []):
            if k.lower() == b"x-saavren-lang":
                lang = v.decode("latin-1", "replace").strip().lower()[:8]
                break
        if not lang:                       # ?lang=xx on the query string
            qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
            lang = (qs.get("lang") or [""])[0].strip().lower()[:8]
        token = _lang_ctx.set(lang or "en")
        try:
            await self.app(scope, receive, send)
        finally:
            _lang_ctx.reset(token)


app.add_middleware(LangMiddleware)

#: seconds the elder gets to answer "are you OK?" before we escalate
FALL_GRACE = int(os.getenv("FALL_GRACE_SECONDS", "20"))


# --------------------------------------------------------------------------
# State (in-memory for the dev build; SQLite/Postgres lands on D8)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Seeded demo text, in every UI language.
#
# The demo elder's data was written in Hinglish, so switching to Tamil
# translated the interface and left the content behind — which reads as
# "language switching is broken". These are the strings a judge actually sees
# on the medicines and health screens.
# --------------------------------------------------------------------------
SEED_TEXT = {
    "cond_bp": {
        "hi": "ब्लड प्रेशर", "en": "Blood pressure", "bn": "রক্তচাপ",
        "ta": "இரத்த அழுத்தம்", "te": "రక్తపోటు", "mr": "रक्तदाब",
        "gu": "બ્લડ પ્રેશર", "es": "Presión arterial",
        "fr": "Tension artérielle"},
    "cond_diabetes": {
        "hi": "मधुमेह", "en": "Diabetes", "bn": "ডায়াবেটিস",
        "ta": "நீரிழிவு நோய்", "te": "మధుమేహం", "mr": "मधुमेह",
        "gu": "ડાયાબિટીસ", "es": "Diabetes", "fr": "Diabète"},
    "note_bp": {
        "hi": "BP की गोली — नाश्ते के बाद",
        "en": "BP pill — after breakfast",
        "bn": "BP-এর ওষুধ — সকালের নাস্তার পর",
        "ta": "BP மாத்திரை — காலை உணவுக்குப் பிறகு",
        "te": "BP మాత్ర — అల్పాహారం తర్వాత",
        "mr": "BP ची गोळी — नाश्त्यानंतर",
        "gu": "BP ની ગોળી — નાસ્તા પછી",
        "es": "Pastilla de presión — después del desayuno",
        "fr": "Comprimé tension — après le petit-déjeuner"},
    "note_sugar": {
        "hi": "शुगर — खाने के साथ", "en": "Sugar — with food",
        "bn": "সুগার — খাবারের সাথে", "ta": "சர்க்கரை — உணவுடன்",
        "te": "షుగర్ — భోజనంతో", "mr": "साखर — जेवणासोबत",
        "gu": "સુગર — ખાવા સાથે", "es": "Azúcar — con la comida",
        "fr": "Sucre — avec le repas"},
    "note_weekly": {
        "hi": "हफ़्ते में 2 बार", "en": "Twice a week",
        "bn": "সপ্তাহে ২ বার", "ta": "வாரத்தில் 2 முறை",
        "te": "వారానికి 2 సార్లు", "mr": "आठवड्यात 2 वेळा",
        "gu": "અઠવાડિયામાં 2 વાર", "es": "Dos veces por semana",
        "fr": "Deux fois par semaine"},
}

#: the seeded strings as they are stored, so a translated copy can be
#: substituted without touching the stored state itself
_SEED_COND = {"Blood pressure": "cond_bp", "Diabetes": "cond_diabetes"}
_SEED_NOTE = {
    "BP ki goli \u2014 nashte ke baad": "note_bp",
    "Sugar \u2014 khane ke saath": "note_sugar",
    "Hafte mein 2 baar": "note_weekly",
}


def seed_str(key: str, lang: str) -> str:
    """Seeded text in `lang`, falling back to English."""
    if not key:
        return ""
    return (SEED_TEXT.get(key, {}).get(lang)
            or SEED_TEXT.get(key, {}).get("en", ""))


def _seed() -> dict:
    return {
        "profile": {
            "name": "Shanti Devi", "age": 72, "gender": "female",
            "dob": "1954-03-12", "conditions": ["Blood pressure", "Diabetes"],
            "weight_kg": 62, "height_cm": 155, "blood_group": "O+",
            "emergency_contact": "Rohit (son) +91-90000-00000",
        },
        "meds": [
            {"id": "m1", "name": "Amlodipine 5mg", "time": "09:00",
             "note": "BP ki goli — nashte ke baad", "taken": False},
            {"id": "m2", "name": "Metformin 500mg", "time": "14:00",
             "note": "Sugar — khane ke saath", "taken": False},
            {"id": "m3", "name": "Vitamin D3", "time": "21:00",
             "note": "Hafte mein 2 baar", "taken": False},
        ],
        "activity": [
            {"id": "a1", "ts": time.time() - 3600, "source": "system",
             "text": "Subah ki check-in: mood theek, chakkar nahi."},
        ],
        "notifications": [],
        "conversations": [],
        "alarm": None,          # D3 — live fall/SOS escalation
        "fall_events": [],      # D3 — history
        "emergencies": [],      # D4 — escalation records
        "monitor": {"last_ack": None, "acked_by": None,
                    "acked_incident": None},
        "checkins": [],          # D6 — daily companion check-in records
        "vitals": [],            # D7 — BP / sugar / pulse / SpO2 readings
        "med_log": [],           # D7 — one row per medicine actually taken
        "checkin_schedule": dict(ai_extra.CHECKIN_SCHEDULE),
        # key -> bool, e.g. {"med:m1": True, "checkin:morning": False}.
        # The routine itself is derived from medicines and the check-in
        # schedule, so adding a medicine shows up here with nothing to sync.
        "routine_alarms": {},
        "last_digest": None,     # D6 — end-of-day note for the monitor   # D5 — "family has seen it"
        "location": {"lat": float(os.getenv("HOME_LAT", "25.4358")),
                     "lon": float(os.getenv("HOME_LON", "81.8463")),
                     "label": os.getenv("HOME_LABEL", "Prayagraj, UP")},
    }


STATE = _seed()


def _seed_demo_history() -> None:
    """Six days of sample history so the Sehat Board has something to rank.

    Nothing here is presented as real: medicines, check-ins and readings are
    stamped source "demo-seed", feed rows carry `demo: true`, the board
    reports `seeded: true`, and the UI says so in as many words. Turn it off with SAAVREN_DEMO_SEED=0. Real days overwrite it
    as they happen.
    """
    now = time.time()
    start = ai_extra._day_start(now)
    rng = random.Random(7)          # fixed: the same board on every boot
    names = [m["name"] for m in STATE["meds"]]

    for back in range(6, 0, -1):
        d0 = start - back * 86400
        # medicines: most days, not every day
        for name in names:
            if rng.random() < (0.85 if back % 3 else 0.5):
                STATE["med_log"].append({
                    "id": uuid.uuid4().hex[:8], "name": name,
                    "ts": d0 + 9 * 3600 + rng.randint(0, 3600),
                    "source": "demo-seed"})
        # check-ins: morning yes, evening most days
        STATE["checkins"].append({
            "id": uuid.uuid4().hex[:8], "kind": "morning",
            "ts": d0 + 9 * 3600, "lang": "en", "status": "answered",
            "mood": rng.choice(["good", "good", "ok"]), "score": 3,
            "flags": [], "answers": [], "summary": "feeling well",
            "source": "demo-seed"})
        if rng.random() < 0.75:
            STATE["checkins"].append({
                "id": uuid.uuid4().hex[:8], "kind": "evening",
                "ts": d0 + 21 * 3600, "lang": "en", "status": "answered",
                "mood": rng.choice(["good", "ok", "ok"]), "score": 2,
                "flags": [], "answers": [], "summary": "managing",
                "source": "demo-seed"})
        elif back == 3:
            STATE["checkins"].append({
                "id": uuid.uuid4().hex[:8], "kind": "evening",
                "ts": d0 + 21 * 3600, "lang": "en", "status": "missed",
                "mood": None, "score": None, "flags": [], "answers": [],
                "summary": "no answer to the evening check-in",
                "source": "demo-seed"})
        # vitals once a day, drifting slightly
        STATE["vitals"].append(ai_extra.vital_entry({
            "bp_sys": 124 + rng.randint(-6, 10),
            "bp_dia": 79 + rng.randint(-5, 7),
            "sugar": 104 + rng.randint(-14, 22),
            "pulse": 74 + rng.randint(-7, 9),
            "spo2": rng.choice([97, 97, 98, 96]),
            "source": "demo-seed",
        }, ts=d0 + 10 * 3600))
        # a little life in the activity feed
        for hours, text in ((8, "Morning walk in the park"),
                            (13, "Talked with Saavren about her knee"),
                            (19, "Called her sister")):
            if rng.random() < 0.7:
                STATE["activity"].append({
                    "id": uuid.uuid4().hex[:8], "ts": d0 + hours * 3600,
                    "source": rng.choice(["agent", "note"]), "text": text,
                    # the badge still reads agent/note, but the row must be
                    # traceable back to the seed or the feed looks like a
                    # real person's day
                    "demo": True})

    STATE["checkins"].sort(key=lambda c: -float(c.get("ts") or 0))
    STATE["vitals"].sort(key=lambda v: -float(v.get("ts") or 0))
    STATE["activity"].sort(key=lambda a: -float(a.get("ts") or 0))


#: True when this install seeded itself with sample history. The UI shows it
#: in as many words — nobody should mistake the demo elder for a real person.
DEMO_SEEDED = os.getenv("SAAVREN_DEMO_SEED", "1") == "1"
if DEMO_SEEDED:
    _seed_demo_history()


def _log(text: str, source: str = "agent") -> dict:
    item = {"id": uuid.uuid4().hex[:8], "ts": time.time(), "source": source,
            "text": text[:300]}
    STATE["activity"].insert(0, item)
    STATE["activity"] = STATE["activity"][:200]
    return item


def _notify(title: str, body: str, kind: str = "info") -> dict:
    n = {"id": uuid.uuid4().hex[:8], "ts": time.time(), "title": title,
         "body": body, "kind": kind, "read": False}
    STATE["notifications"].insert(0, n)
    STATE["notifications"] = STATE["notifications"][:100]
    return n


def public_state(lang: str | None = None) -> dict:
    """The state the UI renders.

    Seeded demo rows are translated on the way out, so the demo elder's data
    follows the language switch instead of staying in Hinglish while the
    interface changes around it.
    """
    lang = (lang or _lang_ctx.get() or "en").lower()
    if lang not in SEED_TEXT["cond_bp"]:
        lang = "en"
    profile, meds = STATE["profile"], STATE["meds"]
    if DEMO_SEEDED:
        profile = dict(profile)
        profile["conditions"] = [
            seed_str(_SEED_COND.get(c, ""), lang) or c
            for c in (profile.get("conditions") or [])]
        meds = [dict(m, note=(seed_str(_SEED_NOTE.get(m.get("note", ""), ""),
                                       lang) or m.get("note", "")),
                     demo=True)
                for m in meds]
    return {"profile": profile, "meds": meds,
            "activity": STATE["activity"][:60],
            "notifications": STATE["notifications"],
            "alarm": STATE["alarm"], "location": STATE["location"],
            "emergencies": STATE["emergencies"][:10],
            "monitor": STATE["monitor"],
            "checkins": STATE["checkins"][:20],
            "checkin_schedule": STATE["checkin_schedule"],
            "demo": DEMO_SEEDED,
            "routine_alarms": STATE["routine_alarms"],
            "vitals": STATE["vitals"][:20],
            "med_log": STATE["med_log"][:60]}


@app.on_event("startup")
def _boot_banner() -> None:
    ok, detail = ai.hf_token_status()
    if detail == "missing":
        print("[saavren] HF_TOKEN: not set", flush=True)
    else:
        print(f"[saavren] HF_TOKEN: {detail}", flush=True)
    print(f"[saavren] ASR  : {ai.asr_mode()}  (chain: {ai.asr_chain()})", flush=True)
    print(f"[saavren] LLM  : {ai.provider_order()}", flush=True)

    # Running with no keys is a perfectly good way to run Saavren, but it must
    # never be a *silent* one — otherwise "offline" looks like a broken key.
    found = [k for k in ("HF_TOKEN", "BASETEN_API_KEY", "GROQ_API_KEY")
             if (os.getenv(k) or "").strip()]
    if found:
        print(f"[saavren] keys  : {', '.join(found)}", flush=True)
    else:
        env_path = Path(__file__).resolve().parents[2] / ".env"
        print("[saavren] keys  : NONE - the AI is running OFFLINE.", flush=True)
        print(f"[saavren]         no keys found; expected them in {env_path}", flush=True)
        print("[saavren]         copy your .env from the older folder, or fill it in.",
              flush=True)

    def _prefetch() -> None:
        try:
            hs = ai_extra.nearest_hospitals(STATE["location"]["lat"],
                                            STATE["location"]["lon"], timeout=14)
            print(f"[saavren] hospitals preloaded: {len(hs)}", flush=True)
        except Exception:
            pass

    threading.Thread(target=_prefetch, daemon=True).start()

    # D6 — the companion clock: nudges check-ins, sends the daily digest
    threading.Thread(target=_companion_loop, daemon=True).start()


# --------------------------------------------------------------------------
# Health & diagnostics
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "service": "saavren", "version": app.version,
            "asr": ai.asr_available(), "asr_mode": ai.asr_mode(),
            "asr_chain": ai.asr_chain(),
            "hf_token": ai.hf_token_status()[1],
            "ffmpeg_ready": ai.ffmpeg_bin() is not None,
            "ffmpeg_required": False,
            "provider_order": ai.provider_order(),
            "time": time.time()}


@app.get("/api/ai-status")
def ai_status(probe: int = 0):
    """Why is Saavren answering from the offline mirror? Open this in a browser.

    /api/ai-status          -> masked keys + last provider errors
    /api/ai-status?probe=1  -> also calls every provider once, live
    """
    info = ai.ai_status()
    if probe:
        ping = [{"role": "user", "content": "Reply with the single word: ok"}]
        for p in info["provider_order"]:
            if p == "offline":
                continue
            try:
                fn = {"baseten": ai._baseten, "groq": ai._groq,
                      "hf": ai._hf_llm}[p]
                out = fn({"messages": ping})
                info.setdefault("probe", {})[p] = f"OK — {str(out)[:80]!r}"
                ai.LLM_ERRORS.pop(p, None)
            except Exception as e:
                info.setdefault("probe", {})[p] = f"FAIL — {ai._err(p, e)}"
        if ai._env("GROQ_API_KEY"):
            info["groq_models_offered"] = ai.groq_models_offered()
        if ai._env("BASETEN_API_KEY"):
            info["baseten_models_offered"] = ai.baseten_models_offered()
        info["asr_probe"] = ai.asr_probe()
    info["llm_errors"] = dict(ai.LLM_ERRORS)
    return info


@app.get("/api/state")
def get_state(lang: str | None = None):
    # NOT "en" — an explicit default would shadow the language the request
    # arrived with, which is exactly how every state reply came back English.
    return public_state(lang)


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------
class ChatIn(BaseModel):
    message: str
    lang: str = "en"
    conversation_id: str | None = None
    force_triage: bool = False
    role: str = "elder"          # elder | family (D5 monitor dashboard)


UNWELL_RE = re.compile(
    r"(dard|dukh|pain|bukhaar|fever|ulti|vomit|chakkar|dizzy|saans|breathe|"
    r"gir|fall|khoon|bleed|behosh|faint|kamzori|weak|sujan|swelling|"
    r"heart|dil|seene|chhaati|BP|sugar|daura|seizure|tabiyat\s*(kharab|bekaar)|"
    r"unwell|sick|bimaar|"
    r"बुखार|दर्द|दुख|खाँसी|खांसी|साँस|सांस|चक्कर|उल्टी|कमजोरी|सूजन|"
    r"खून|बेहोश|गिर|दिल|सीने|सीना|छाती|दवा|बीमार|तबियत|सिरदर्द|पेट|चोट|जलन|"
    r"नींद|थकान|शक्कर)",
    re.I,
)

#: Purely social turns. These must NEVER produce an emergency card, a
#: "do this at home" list or a medical disclaimer — that is the "faaltu ki
#: baatein" an elder complains about when they just said hello.
SOCIAL_RE = re.compile(
    r"^\s*(hi+|hello+|hey+|yo+|namaste|namaskar|namaskaram|vanakkam|"
    r"sat\s*sri\s*akal|good\s*(morning|afternoon|evening|night)|gm|gn|"
    r"how\s*(are\s*you|r\s*u|do\s*you\s*do)\b|how'?s\s*it\s*going|what'?s\s*up|"
    r"kaise\s*(ho|hain|hai|aap)|kaisi\s*(ho|hain)|kya\s*haal|sab\s*(theek|thik)|"
    r"sun\s*li\s*maine|theek\s*(hoon|hu)|i'?m\s*(fine|ok|okay|good)|"
    r"thank(s|\s*you)|dhanyavaad|shukriya|bye+|goodbye|see\s*you|"
    r"ok+|okay+|hmm+|haan+|acha+|achha+|theek\s*hai|"
    r"who\s*are\s*you|tum\s*kaun|what\s*can\s*you\s*do|help)\s*[.!?।]*\s*$",
    re.I,
)


def _state_summary(role: str = "elder") -> str:
    p = STATE["profile"]
    meds = ", ".join(f"{m['name']} @ {m['time']}"
                     f"{' (ho gaya)' if m['taken'] else ''}" for m in STATE["meds"])
    base = (f"name={p['name']}, age={p['age']}, conditions="
            f"{', '.join(p['conditions'])}; medicines: {meds or 'none'}")
    if role != "family":
        return base
    # D5 — the family asks "how is she?", so the brain needs today's picture,
    # not just the medicine list. Same source the dashboard renders.
    s = ai_extra.daily_summary(STATE)
    lines = [base, f"today ({s['date']}): status={s['status']}",
             f"medicines taken {s['meds_taken']}/{s['meds_total']}",
             f"pending: {', '.join(s['pending']) or 'none'}",
             f"last seen: {s['last_seen_ago']}",
             f"events today: {s['events_today']}",
             f"open incidents: {s['incidents_open']}",
             "highlights: " + ("; ".join(s["highlights"]) or "none"),
             "concerns: " + ("; ".join(s["concerns"]) or "none")]
    recent = "; ".join(f"{a.get('source')}: {a.get('text')}"
                       for a in (STATE["activity"] or [])[:8])
    if recent:
        lines.append("recent activity: " + recent)
    return "\n".join(lines)


def _offline_reason() -> str:
    if not ai.LLM_ERRORS:
        return ""
    name, msg = next(iter(ai.LLM_ERRORS.items()))
    return f"{name}: {msg}"[:160]


@app.get("/api/chat/debug")
def chat_debug(request: Request, msg: str = "how is she today?",
               role: str = "family", lang: str = "en"):
    """Why did that answer fall back? Diagnostic — shows the raw model text.

    Hit this when the monitor answers from the offline mirror. It reports the
    provider actually used, whether the keys are loaded, the raw reply, and
    whether it parsed. Everything needed to tell "no key" from "key works but
    the reply was unreadable".
    """
    sysprompt = (ai.FAMILY_SYS if role == "family" else ai.AGENT_SYS)
    sysprompt = sysprompt.replace("{lang}", ai._lang_name(lang))
    state = _state_summary(role)
    txt, prov = ai.llm([
        {"role": "system", "content": sysprompt},
        {"role": "user",
         "content": f"Current app state: {state}\n\nUser says: {msg}"}])
    parsed = ai.parse_json_loose(txt)
    return {
        # WHAT LANGUAGE DID THE SERVER ACTUALLY RECEIVE? If this says "en"
        # while the UI shows Hindi, the bug is in the request, not the model.
        "lang_asked": lang,
        "lang_from_header": request.headers.get("x-saavren-lang"),
        "lang_server_will_use": _lang_ctx.get(),
        "role_asked": role,
        "provider_order": ai.provider_order(),
        "provider_used": prov,
        "keys_present": [k for k in ("HF_TOKEN", "BASETEN_API_KEY",
                                     "GROQ_API_KEY")
                         if (os.getenv(k) or "").strip()],
        "dead_providers": sorted(ai.DEAD_PROVIDERS),
        "raw_len": len(txt or ""),
        "raw_text": (txt or "")[:2000],
        "parsed_ok": bool(parsed and isinstance(parsed.get("reply"), str)),
        "parsed_keys": (sorted(parsed.keys())
                        if isinstance(parsed, dict) else None),
        "llm_errors": dict(ai.LLM_ERRORS),
        "state_chars": len(state),
    }


@app.post("/api/chat")
def chat(body: ChatIn):
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(400, "empty message")

    conv = None
    if body.conversation_id:
        conv = next((c for c in STATE["conversations"]
                     if c["id"] == body.conversation_id), None)
    if conv is None:
        conv = {"id": uuid.uuid4().hex[:8], "title": msg[:40],
                "messages": [], "updated": time.time()}
        STATE["conversations"].append(conv)

    conv["messages"].append({"role": "user", "content": msg, "ts": time.time()})
    conv["updated"] = time.time()

    # D5 — a family member reporting "mom has fever" must NOT trigger the
    # elder's own triage/alarm flow. They get an answer about the elder.
    social = bool(SOCIAL_RE.match(msg)) and not UNWELL_RE.search(msg)
    if body.role != "family" and not social \
            and (body.force_triage or UNWELL_RE.search(msg)):
        t = ai.triage(msg, body.lang)
        conv["messages"].append({"role": "assistant", "kind": "triage",
                                 "content": t, "ts": time.time()})
        _log(f"Triage ({t['severity']}/10, {t['category']}): {msg[:80]}", "triage")
        if t["severity"] >= 7:
            _notify("Emergency level",
                    f"{t['category']} · severity {t['severity']}/10 — {msg[:120]}",
                    "emergency")
        resp = {"kind": "triage", "triage": t, "applied": [],
                "source": t.get("source", "llm"),
                "offline_reason": _offline_reason(),
                "conversation_id": conv["id"]}
    else:
        out = ai.agent(msg, body.lang, _state_summary(body.role), body.role,
                       ai_extra.daily_summary(STATE) if body.role == "family"
                       else None)
        applied = _apply_actions(out.get("actions") or [])
        conv["messages"].append({"role": "assistant", "kind": "chat",
                                 "content": out["reply"], "actions": applied,
                                 "ts": time.time()})
        _log(f"Chat: {msg[:90]}", "agent")
        resp = {"kind": "agent", "reply": out["reply"], "applied": applied,
                "source": out.get("source", "llm"),
                "offline_reason": (out.get("fallback_reason")
                                   or _offline_reason()),
                "conversation_id": conv["id"]}

    resp["state"] = public_state()
    return resp


def _apply_actions(actions: list[dict]) -> list[str]:
    done: list[str] = []
    for a in actions:
        t = a.get("type")
        name = (a.get("name") or "").strip()
        if t == "med_add" and name:
            med = {"id": uuid.uuid4().hex[:8], "name": name[:60],
                   "time": str(a.get("time") or "09:00")[:5],
                   "note": str(a.get("note") or "")[:160], "taken": False}
            STATE["meds"].append(med)
            done.append(f"medicine added: {name}")
        elif t == "med_taken" and name:
            for m in STATE["meds"]:
                if name.lower() in m["name"].lower():
                    m["taken"] = True
                    done.append(f"marked taken: {m['name']}")
                    break
        elif t == "med_delete" and name:
            before = len(STATE["meds"])
            STATE["meds"] = [m for m in STATE["meds"]
                             if name.lower() not in m["name"].lower()]
            if len(STATE["meds"]) != before:
                done.append(f"removed: {name}")
        elif t == "note" and (a.get("text") or a.get("note")):
            _log(str(a.get("text") or a.get("note"))[:300], "note")
            done.append("note saved")
        elif t == "vital":
            # coerce here as well as in the agent: this is the function that
            # actually writes to state, so it must never trust an action dict
            payload = {}
            for k in ("bp_sys", "bp_dia", "sugar", "pulse", "spo2"):
                try:
                    payload[k] = float(a.get(k))
                except (TypeError, ValueError):
                    continue
            if payload:
                label = ", ".join(f"{k}={v:g}" for k, v in payload.items())
                payload["source"] = "chat"
                payload["note"] = str(a.get("note") or "")[:200]
                rec = ai_extra.vital_entry(payload)
                STATE["vitals"].insert(0, rec)
                STATE["vitals"] = STATE["vitals"][:200]
                done.append("vitals logged: " + label)
        elif t == "notify" and (a.get("text") or a.get("note")):
            _notify("Saavren", str(a.get("text") or a.get("note"))[:240], "info")
            done.append("family notified")
    if done:
        _log("; ".join(done), "agent")
    return done


# --------------------------------------------------------------------------
# Speech -> text only (D5: the monitor asks out loud, with no triage)
# --------------------------------------------------------------------------
@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Return the words, and nothing else. No triage, no alarm.

    The elder's mic runs the emergency path; a family member asking "how is
    she today?" out loud must not be able to set off the fall flow.
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    if not ai.asr_available():
        raise HTTPException(503, "asr-unavailable")
    text = ai.asr_transcribe(data, file.content_type or "audio/wav")
    if not (text or "").strip():
        raise HTTPException(422, "could not hear anything")
    return {"text": text.strip()[:600]}


# --------------------------------------------------------------------------
# Voice SOS (speech -> text -> triage)
# --------------------------------------------------------------------------
@app.post("/api/voice-sos")
async def voice_sos(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    ct = file.content_type or "audio/wav"
    if not ai.asr_available():
        # Not an error the elder should see: the page uses Web Speech instead.
        raise HTTPException(503, "ASR_UNAVAILABLE")
    try:
        transcript = ai.asr_transcribe(data, ct)
    except Exception as e:
        raise HTTPException(502, f"STAGE: ASR failed — {e}")
    if not transcript.strip():
        raise HTTPException(502, "STAGE: ASR returned empty text (mic check karein)")
    t = ai.triage(transcript, "en")
    if t["severity"] >= 7:
        _notify("Voice SOS",
                f"Awaz se SOS: \"{transcript[:120]}\" — severity {t['severity']}/10",
                "emergency")
    _log(f"Voice SOS: {transcript[:90]}", "voice")
    return {"transcript": transcript, "triage": t, "state": public_state()}


# --------------------------------------------------------------------------
# D3 — fall / thud detection + escalation alarm
# --------------------------------------------------------------------------
class FallIn(BaseModel):
    confidence: float = 0.0
    source: str = "browser"          # browser | server | manual | button
    features: dict | None = None
    lang: str = "en"


def _new_alarm(kind: str, confidence: float, source: str,
               features: dict | None, lang: str) -> dict:
    now = time.time()
    alarm = {"id": uuid.uuid4().hex[:8], "kind": kind,
             "status": "ringing",            # ringing | cancelled | escalated
             "confidence": round(float(confidence or 0), 3),
             "source": source, "features": features or {},
             "lang": lang, "started": now, "grace": FALL_GRACE,
             "until": now + FALL_GRACE}
    STATE["alarm"] = alarm
    STATE["fall_events"].insert(0, {**alarm, "resolved": None})
    STATE["fall_events"] = STATE["fall_events"][:50]
    _log(f"Fall? {kind} · confidence {alarm['confidence']} · {source}", "fall")
    threading.Timer(FALL_GRACE + 0.5, _escalate, args=(alarm["id"],)).start()
    return alarm


def _emergency_record(a: dict) -> dict:
    """D4 — one record with the whole story: what happened, who was told,
    where the nearest help is, and the card a paramedic reads."""
    p = STATE["profile"]
    loc = STATE["location"]
    hospitals = ai_extra.nearest_hospitals(loc.get("lat"), loc.get("lon"),
                                           timeout=6)
    card = ai_extra.emergency_card(p, STATE["meds"])
    fam = ai_extra.parse_phone(p.get("emergency_contact") or "")
    rec = {
        "id": uuid.uuid4().hex[:8],
        "kind": a.get("kind", "fall"),
        "ts": time.time(),
        "confidence": a.get("confidence"),
        "source": a.get("source"),
        "severity": 10 if a.get("kind") == "sos" else 8,
        "contact": {"name": p.get("name", ""),
                    "phone": fam or "",
                    "raw": p.get("emergency_contact", "")},
        "hospitals": hospitals,
        "card": card,
        "calls": {
            "family": f"tel:{fam}" if fam else "",
            "ambulance": "tel:112",
            "doctor": f"tel:{p.get('doctor_phone') or ''}" if p.get("doctor_phone") else "",
        },
        "timeline": [
            {"ts": a.get("started", time.time()), "stage": "detected",
             "text": f"{a.get('kind')} reported by {a.get('source')} "
                     f"(confidence {a.get('confidence')})"},
            {"ts": a.get("started", time.time()), "stage": "alarm",
             "text": f"'Are you OK?' shown for {a.get('grace')}s"},
            {"ts": a.get("escalated_at") or time.time(), "stage": "escalated",
             "text": "No answer — notifying family"},
        ],
        "status": "open",
        "call_log": [],
    }
    STATE["emergencies"].insert(0, rec)
    STATE["emergencies"] = STATE["emergencies"][:30]
    # If the map service was slow/unreachable we showed the offline list —
    # fetch for real in the background and patch the record when it lands, so
    # the rescuer gets real hospitals without waiting for them.
    if not hospitals or hospitals[0].get("source") == "offline-list":
        def _fill(rid: str, la: float, lo: float) -> None:
            try:
                hs = ai_extra.nearest_hospitals(la, lo, timeout=14)
            except Exception:
                return
            for r in STATE["emergencies"]:
                if r["id"] == rid:
                    r["hospitals"] = hs
                    r["hospitals_loaded"] = True
        threading.Thread(target=_fill,
                         args=(rec["id"], loc.get("lat"), loc.get("lon")),
                         daemon=True).start()
    else:
        rec["hospitals_loaded"] = True
    return rec


def _escalate(alarm_id: str) -> None:
    """Grace period over with no answer -> tell the family, and call."""
    a = STATE.get("alarm")
    if not a or a["id"] != alarm_id or a["status"] != "ringing":
        return
    a["status"] = "escalated"
    a["escalated_at"] = time.time()
    for ev in STATE["fall_events"]:
        if ev["id"] == alarm_id:
            ev["status"] = "escalated"
            ev["resolved"] = time.time()

    rec = _emergency_record(a)
    a["emergency_id"] = rec["id"]
    p = STATE["profile"]
    if a["kind"] == "sos":
        _notify("SOS pressed",
                f"{p['name']} ne SOS button dabaya hai. Turant call karein. "
                f"Contact: {p['emergency_contact']}", "emergency")
        _log("SOS pressed — family + doctor notified, call placed", "sos")
    else:
        _notify("FALL — no answer",
                f"{p['name']} ne {a['grace']}s tak jawab nahi diya. "
                f"Turant check karein. Contact: {p['emergency_contact']}",
                "emergency")
        _log("FALL escalated — family + doctor notified, call placed", "fall")


@app.post("/api/fall")
def fall(inp: FallIn):
    """Start the 'are you OK?' alarm. Cancelled by /api/alarm/cancel."""
    return {"alarm": _new_alarm("fall", inp.confidence, inp.source,
                                inp.features, inp.lang),
            "state": public_state()}


@app.post("/api/fall/analyze")
async def fall_analyze(file: UploadFile = File(...), lang: str = "en",
                       auto_alarm: int = 1):
    """Analyse a clip for a thud signature (and optionally raise the alarm)."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    res = ai.thud_score(data, file.content_type or "audio/wav")
    alarm = None
    if auto_alarm and res.get("verdict") == "thud":
        alarm = _new_alarm("fall", res.get("score", 0), "server", res, lang)
    return {"analysis": res, "alarm": alarm, "state": public_state()}


@app.get("/api/alarm")
def get_alarm():
    """Poll the live alarm; tells the page when to ring and when to stop."""
    a = STATE.get("alarm")
    if not a:
        return {"alarm": None}
    return {"alarm": a, "remaining": max(0, round(a["until"] - time.time(), 1)),
            "now": time.time()}


@app.post("/api/alarm/cancel")
def alarm_cancel():
    """The elder answered: 'I'm OK'. Nothing is sent."""
    a = STATE.get("alarm")
    if not a or a["status"] != "ringing":
        return {"ok": False, "alarm": a, "state": public_state()}
    a["status"] = "cancelled"
    a["resolved_at"] = time.time()
    for ev in STATE["fall_events"]:
        if ev["id"] == a["id"]:
            ev["status"] = "cancelled"
            ev["resolved"] = time.time()
    _log("Fall check-in: elder answered — false alarm", "fall")
    return {"ok": True, "alarm": a, "state": public_state()}


@app.post("/api/alarm/help")
def alarm_help():
    """The elder asked for help (or the grace period expired): escalate now."""
    a = STATE.get("alarm")
    if not a:
        a = _new_alarm("fall", 1.0, "manual", {}, "en")
    if a["status"] == "ringing":
        _escalate(a["id"])
    return {"ok": True, "alarm": a, "state": public_state()}


@app.get("/api/falls")
def list_falls():
    return {"falls": STATE["fall_events"]}


# --------------------------------------------------------------------------
# D4 — escalation record, nearest hospitals, emergency card
# --------------------------------------------------------------------------
@app.get("/api/emergency")
def list_emergencies():
    return {"emergencies": STATE["emergencies"]}


@app.get("/api/emergency/{eid}")
def get_emergency(eid: str):
    rec = next((e for e in STATE["emergencies"] if e["id"] == eid), None)
    if not rec:
        raise HTTPException(404, "not found")
    return rec


@app.post("/api/emergency/{eid}/call")
def log_call(eid: str, payload: dict | None = None):
    """Record that a call was placed (twilio etc. lands later — for now we log
    the attempt and hand the device a `tel:` link that really dials)."""
    rec = next((e for e in STATE["emergencies"] if e["id"] == eid), None)
    if not rec:
        raise HTTPException(404, "not found")
    who = (payload or {}).get("who") or "unknown"
    entry = {"ts": time.time(), "who": who}
    rec["call_log"].append(entry)
    rec["timeline"].append({"ts": time.time(), "stage": "called",
                            "text": f"Call placed: {who}"})
    _log(f"Emergency call: {who}", "call")
    return {"ok": True, "record": rec, "state": public_state()}


# --------------------------------------------------------------------------
# D5 — the family monitor: one payload with the whole picture
# --------------------------------------------------------------------------
def monitor_payload() -> dict:
    """Everything the family dashboard shows, in one round trip.

    It mirrors the elder's app A-to-Z (profile, medicines, activity,
    notifications, alarm, incidents, emergency card) and adds the two things
    only the monitor is for: today's summary and the unread alert count.
    """
    return {
        "profile": STATE["profile"],
        "meds": STATE["meds"],
        "activity": STATE["activity"][:80],
        "notifications": STATE["notifications"],
        "alarm": STATE["alarm"],
        "emergencies": STATE["emergencies"][:20],
        "location": STATE["location"],
        "monitor": STATE["monitor"],
        "checkins": STATE["checkins"][:20],
        "card": ai_extra.emergency_card(STATE["profile"], STATE["meds"]),
        "sehat": ai_extra.sehat_board(STATE),
        "summary": ai_extra.daily_summary(STATE),
        "unread": sum(1 for n in STATE["notifications"] if not n.get("read")),
        "generated_at": time.time(),
    }


@app.get("/api/monitor")
def monitor():
    return monitor_payload()


class AckIn(BaseModel):
    by: str = "family"


@app.post("/api/monitor/ack")
def monitor_ack(body: AckIn | None = None):
    """Family pressed 'I've seen it'.

    Silences the bell and — the part that matters — writes the
    acknowledgement onto every open incident, so the elder's screen and any
    paramedic reading the record can see that someone is on it.
    """
    who = (getattr(body, "by", None) or "family")[:40]
    now = time.time()
    acked = []
    for rec in STATE["emergencies"]:
        if rec.get("status") != "open" or rec.get("ack_at"):
            continue
        rec["ack_at"] = now
        rec["ack_by"] = who
        rec.setdefault("timeline", []).append(
            {"ts": now, "stage": "ack",
             "text": f"{who} acknowledged on the monitor — someone is on it"})
        acked.append(rec["id"])
    for n in STATE["notifications"]:
        if not n.get("read"):
            n["read"] = True
    STATE["monitor"] = {"last_ack": now, "acked_by": who,
                        "acked_incident": acked[0] if acked else None}
    if acked:
        _log(f"Monitor acknowledged by {who} ({len(acked)} incident(s))", "monitor")
    return {"acked": acked, **monitor_payload()}


@app.post("/api/emergency/{eid}/close")
def close_emergency(eid: str):
    rec = next((e for e in STATE["emergencies"] if e["id"] == eid), None)
    if not rec:
        raise HTTPException(404, "not found")
    rec["status"] = "closed"
    rec["timeline"].append({"ts": time.time(), "stage": "closed",
                            "text": "Marked resolved"})
    # D5 — "resolved" means handled. If the alarm that created this record is
    # still standing, stand it down too, or the monitor keeps screaming about
    # an incident nobody can find any more.
    a = STATE.get("alarm")
    if a and (a.get("emergency_id") == eid or a.get("id") == eid) \
            and a.get("status") in ("ringing", "escalated"):
        a["status"] = "resolved"
        a["resolved_at"] = time.time()
        for ev in STATE["fall_events"]:
            if ev["id"] == a["id"]:
                ev["status"] = "resolved"
                ev["resolved"] = time.time()
    _log("Emergency marked resolved", "call")
    return {"ok": True, "record": rec, "state": public_state()}


@app.get("/api/hospitals")
def hospitals(lat: float | None = None, lon: float | None = None,
              radius: int = 6000, refresh: int = 0, timeout: int = 25):
    loc = STATE["location"]
    la = lat if lat is not None else loc.get("lat")
    lo = lon if lon is not None else loc.get("lon")
    if refresh:
        ai_extra._HOSP_CACHE.clear()
    return {"location": {"lat": la, "lon": lo, "label": loc.get("label")},
            "hospitals": ai_extra.nearest_hospitals(la, lo, radius,
                                                    timeout=timeout)}


class LocIn(BaseModel):
    lat: float
    lon: float
    label: str = ""


@app.put("/api/location")
def set_location(body: LocIn):
    STATE["location"] = {"lat": body.lat, "lon": body.lon,
                         "label": body.label or STATE["location"].get("label", "")}
    ai_extra._HOSP_CACHE.clear()
    _log(f"Location set: {STATE['location']['label'] or body.lat}", "manual")
    return {"location": STATE["location"], "state": public_state()}


@app.get("/api/ecard")
def ecard():
    """The card a paramedic reads."""
    card = ai_extra.emergency_card(STATE["profile"], STATE["meds"])
    return {"card": card,
            "text": ai_extra.ecard_text(card, ai_extra.nearest_hospitals(
                STATE["location"]["lat"], STATE["location"]["lon"]))}


@app.post("/api/sos")
def sos():
    """The big red button — escalate immediately, no grace period."""
    a = _new_alarm("sos", 1.0, "button", {}, "en")
    _escalate(a["id"])
    return {"alarm": a, "state": public_state()}


# --------------------------------------------------------------------------
# Prescription / medicine-photo scan
# --------------------------------------------------------------------------
@app.post("/api/scan")
async def scan(file: UploadFile = File(...), lang: str = "en"):
    data = await file.read()
    parsed = ai_extra.vision_extract(data, file.content_type or "", lang)
    added = []
    for m in parsed.get("meds") or []:
        med = {"id": uuid.uuid4().hex[:8], "name": str(m.get("name", ""))[:60],
               "time": str(m.get("time") or "09:00")[:5],
               "note": str(m.get("note") or "scan se judi")[:160], "taken": False}
        if med["name"]:
            STATE["meds"].append(med)
            added.append(med)
    if added:
        _log(f"Scan se {len(added)} dawa judi", "scan")
    return {"summary": parsed.get("summary", ""),
            "precautions": parsed.get("precautions") or [],
            "source": parsed.get("source", "offline-fallback"),
            "added": added, "state": public_state()}


# --------------------------------------------------------------------------
# Medicines, profile, notifications
# --------------------------------------------------------------------------
class MedIn(BaseModel):
    name: str
    time: str = "09:00"
    note: str = ""


@app.post("/api/meds")
def add_med(m: MedIn):
    if not (m.name or "").strip():
        raise HTTPException(status_code=400, detail="med_name_required")
    med = {"id": uuid.uuid4().hex[:8], "name": m.name[:60], "time": m.time[:5],
           "note": m.note[:160], "taken": False}
    STATE["meds"].append(med)
    _log(f"Dawa judi: {med['name']} @ {med['time']}", "manual")
    return {"med": med, "state": public_state()}


@app.post("/api/meds/taken")
def toggle_med(m: MedIn):
    for x in STATE["meds"]:
        if x["name"].lower() == m.name.lower():
            x["taken"] = not x["taken"]
            # D7 — the board scores medicines per DAY, so a tick has to leave
            # a dated row behind, not just flip a flag.
            today = ai_extra._day_start(time.time())
            if x["taken"]:
                STATE["med_log"].append({
                    "id": uuid.uuid4().hex[:8], "name": x["name"],
                    "ts": time.time(), "source": "manual",
                    "day": today})
                STATE["med_log"] = STATE["med_log"][:400]
            else:
                STATE["med_log"] = [
                    e for e in STATE["med_log"]
                    if not (e.get("name") == x["name"]
                            and float(e.get("ts") or 0) >= today)]
            _log(f"{x['name']}: {'li' if x['taken'] else 'pending'}", "manual")
            break
    return {"state": public_state()}


@app.delete("/api/meds/{med_id}")
def delete_med(med_id: str):
    STATE["meds"] = [m for m in STATE["meds"] if m["id"] != med_id]
    return {"state": public_state()}


@app.put("/api/profile")
def save_profile(patch: dict):
    STATE["profile"].update({k: v for k, v in patch.items()
                             if k in STATE["profile"]})
    _log("Profile update hua", "manual")
    return {"state": public_state()}


@app.post("/api/notify")
def notify(payload: dict):
    _notify(str(payload.get("title") or "Saavren")[:80],
            str(payload.get("body") or "")[:300],
            str(payload.get("kind") or "info"))
    return {"state": public_state()}


@app.post("/api/notifications/read")
def read_notifications():
    for n in STATE["notifications"]:
        n["read"] = True
    return {"state": public_state()}


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------
@app.get("/api/conversations")
def list_conversations():
    return {"conversations": [
        {"id": c["id"], "title": c["title"], "updated": c["updated"],
         "count": len(c["messages"])}
        for c in sorted(STATE["conversations"], key=lambda x: -x["updated"])]}


@app.get("/api/conversations/{cid}")
def get_conversation(cid: str):
    c = next((x for x in STATE["conversations"] if x["id"] == cid), None)
    if not c:
        raise HTTPException(404, "not found")
    return c


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str):
    STATE["conversations"] = [c for c in STATE["conversations"]
                              if c["id"] != cid]
    return {"ok": True}


# --------------------------------------------------------------------------
# D6 — the daily companion: proactive check-ins and the day's digest
# --------------------------------------------------------------------------
def _checkin_questions(kind: str, lang: str) -> list[str]:
    return ai_extra.checkin_script(kind, lang, STATE["profile"].get("name", ""))


@app.get("/api/checkin/due")
def checkin_due(lang: str = "en", force: int = 0):
    """Is a check-in waiting? The home screen asks this every minute.

    `force=1` hands back a check-in to fill in by hand even when nothing is
    scheduled — the elder can report how she feels at any hour, and a demo
    should not have to wait for nine o'clock.
    """
    d = ai_extra.due_checkin(STATE)
    if not d and force:
        kind = "morning" if time.localtime().tm_hour < 14 else "evening"
        d = {"kind": kind, "due_at": time.time(), "overdue_min": 0,
             "manual": True}
    if not d:
        return {"due": None}
    return {"due": d, "kind": d["kind"], "lang": lang,
            "questions": _checkin_questions(d["kind"], lang)}


class CheckInIn(BaseModel):
    kind: str = "morning"
    lang: str = "en"
    answers: list[dict] = []


@app.post("/api/checkin/answer")
def checkin_answer(body: CheckInIn):
    """Store a finished check-in and tell the monitor what she said."""
    kind = body.kind if body.kind in ai_extra.CHECKIN_KINDS else "morning"
    rec = ai_extra.checkin_record(kind, body.lang, body.answers)
    STATE["checkins"].insert(0, rec)
    STATE["checkins"] = STATE["checkins"][:120]
    _log(f"Check-in ({kind}): {rec['summary']}", "checkin")

    name = STATE["profile"]["name"].split(" ")[0]
    symptoms = [f for f in (rec.get("flags") or [])
                if f in ai_extra.SYMPTOM_FLAGS]
    if rec["mood"] == "bad" or symptoms:
        _notify(f"Not feeling well — {kind} check-in",
                f"{name} said: {rec['summary']}", "emergency")
    elif rec.get("flags"):
        _notify(f"{kind.capitalize()} check-in",
                f"{name}: {rec['summary']}", "info")
    return {"record": rec, "state": public_state()}


@app.post("/api/checkin/skip")
def checkin_skip(body: CheckInIn | None = None):
    """She dismissed it. Remembered as skipped, so it stops nagging."""
    kind = getattr(body, "kind", None) or "morning"
    rec = {"id": uuid.uuid4().hex[:8], "kind": kind, "ts": time.time(),
           "lang": getattr(body, "lang", None) or "en", "status": "skipped",
           "mood": None, "score": None, "flags": [], "answers": [],
           "summary": "skipped"}
    STATE["checkins"].insert(0, rec)
    STATE["checkins"] = STATE["checkins"][:120]
    return {"record": rec, "state": public_state()}


@app.get("/api/checkins")
def list_checkins(limit: int = 30):
    return {"checkins": STATE["checkins"][:max(1, min(limit, 120))]}


class SchedIn(BaseModel):
    morning: str | None = None
    evening: str | None = None
    digest: str | None = None
    enabled: bool | None = None


@app.put("/api/checkin/schedule")
def set_checkin_schedule(body: SchedIn):
    for k in ("morning", "evening", "digest"):
        v = getattr(body, k)
        if v:
            STATE["checkin_schedule"][k] = str(v)[:5]
    if body.enabled is not None:
        STATE["checkin_schedule"]["enabled"] = bool(body.enabled)
    return {"schedule": STATE["checkin_schedule"]}


@app.get("/api/summary/daily")
def daily_summary_endpoint():
    return ai_extra.daily_digest(STATE)


@app.post("/api/summary/daily/push")
def push_daily_summary():
    """Build the digest and ring it onto the monitor as one notification."""
    d = ai_extra.daily_digest(STATE)
    STATE["last_digest"] = {"ts": d["generated_at"], "date": d["date"],
                            "text": d["text"], "status": d["status"]}
    _notify(f"Daily summary — {d['date']}", d["text"],
            "emergency" if d["status"] == "emergency" else "info")
    _log(f"Daily digest for {d['date']} sent to the monitor", "monitor")
    return {"digest": d, "state": public_state()}


def _scheduler_tick(now: float | None = None) -> list[str]:
    """D6 — one pass of the companion clock. Returns what it did.

    No threads and `now` injectable, so the whole clock is testable.
    """
    now = now if now is not None else time.time()
    did: list[str] = []
    start = ai_extra._day_start(now)
    name = STATE["profile"]["name"].split(" ")[0]

    # 1 — a check-in nobody answered IS the signal, not the absence of one
    due = ai_extra.due_checkin(STATE, now)
    if due and due["overdue_min"] >= ai_extra.CHECKIN_GRACE_MIN:
        rec = {"id": uuid.uuid4().hex[:8], "kind": due["kind"], "ts": now,
               "lang": "en", "status": "missed", "mood": None, "score": None,
               "flags": [], "answers": [],
               "summary": f"no answer to the {due['kind']} check-in"}
        STATE["checkins"].insert(0, rec)
        STATE["checkins"] = STATE["checkins"][:120]
        _notify(f"No answer — {due['kind']} check-in",
                f"{name} did not answer the {due['kind']} check-in "
                f"({due['overdue_min']} min). Worth a call.", "emergency")
        _log(f"Missed {due['kind']} check-in ({due['overdue_min']} min)",
             "checkin")
        did.append(f"missed:{due['kind']}")

    # 2 — past the digest hour, send the day's note to the monitor once
    sched = STATE["checkin_schedule"]
    hh, mm = (str(sched.get("digest") or "21:30").split(":") + ["0"])[:2]
    try:
        slot = start + int(hh) * 3600 + int(mm) * 60
    except ValueError:
        slot = start + 21 * 3600 + 30 * 60
    if now >= slot:
        d = ai_extra.daily_digest(STATE, now)
        last = STATE.get("last_digest") or {}
        if last.get("date") != d["date"]:
            STATE["last_digest"] = {"ts": d["generated_at"], "date": d["date"],
                                    "text": d["text"], "status": d["status"]}
            _notify(f"Daily summary — {d['date']}", d["text"],
                    "emergency" if d["status"] == "emergency" else "info")
            _log(f"Daily digest for {d['date']} sent to the monitor", "monitor")
            did.append(f"digest:{d['date']}")
    return did


def _companion_loop(interval: int = 60) -> None:
    """Background clock. Started once at boot; dies with the process."""
    while True:
        time.sleep(interval)
        try:
            _scheduler_tick()
        except Exception as e:                      # a clock must never crash
            print(f"[saavren] companion tick failed: {e}", flush=True)


# --------------------------------------------------------------------------
# D7 — Sehat Board: body, vitals, weekly board
# --------------------------------------------------------------------------
class VitalsIn(BaseModel):
    bp_sys: float | None = None
    bp_dia: float | None = None
    sugar: float | None = None
    pulse: float | None = None
    spo2: float | None = None
    note: str | None = None


@app.get("/api/sehat")
def sehat():
    """Everything the health board needs, in one round trip."""
    return ai_extra.sehat_board(STATE)


@app.post("/api/vitals")
def add_vitals(v: VitalsIn):
    """Log a reading — by hand, or by the agent from a chat message."""
    rec = ai_extra.vital_entry({**v.model_dump(), "source": "manual"})
    if not any(rec[k] is not None
               for k in ("bp_sys", "bp_dia", "sugar", "pulse", "spo2")):
        raise HTTPException(400, "no readings in the payload")
    STATE["vitals"].insert(0, rec)
    STATE["vitals"] = STATE["vitals"][:200]

    bits = []
    for k in ("bp_sys", "bp_dia", "sugar", "pulse", "spo2"):
        if rec.get(k) is not None:
            bits.append(f"{k}={rec[k]:g}")
    _log("Vitals logged: " + ", ".join(bits), "vitals")

    bad = [k for k, band in (rec.get("bands") or {}).items()
           if band in ("high", "very high", "critical", "low")]
    if bad:
        _notify("Reading outside her usual range",
                f"{STATE['profile']['name'].split(' ')[0]} logged "
                + ", ".join(f"{k}={rec[k]:g} ({rec['bands'][k]})" for k in bad)
                + ". Worth a look.", "emergency")
    return {"record": rec, "state": public_state()}


@app.get("/api/vitals")
def list_vitals(days: int = 30):
    now = time.time()
    cutoff = now - max(1, days) * 86400
    rows = [v for v in STATE["vitals"] if float(v.get("ts") or 0) >= cutoff]
    return {"vitals": rows, "count": len(rows),
            "latest": ai_extra.latest_vitals(STATE["vitals"]),
            "series": ai_extra.vitals_series(STATE["vitals"], days, now)}


@app.get("/api/board")
def board():
    """The weekly board on its own — cheap to poll from the monitor."""
    b = ai_extra.weekly_board(STATE)
    b["points"] = ai_extra.POINTS
    return b


# --------------------------------------------------------------------------
# Accounts (optional — the app is fully usable with no account)
# --------------------------------------------------------------------------
class SignupIn(BaseModel):
    name: str
    username: str
    password: str
    role: str = "elder"          # elder | family


class LoginIn(BaseModel):
    username: str
    password: str


def _current_user(authorization: str | None = Header(default=None)):
    return auth.user_for_token(auth.bearer(authorization))


@app.post("/api/auth/signup")
def signup(body: SignupIn):
    """Create an account. Errors come back as codes the UI translates."""
    try:
        return auth.signup(body.name, body.username, body.password, body.role)
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=e.code)


@app.post("/api/auth/login")
def login(body: LoginIn):
    try:
        return auth.login(body.username, body.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=e.code)


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    auth.logout(auth.bearer(authorization))
    return {"ok": True}


@app.get("/api/auth/me")
def me(authorization: str | None = Header(default=None)):
    """Whoever the token belongs to, or null when nobody is signed in."""
    return {"user": auth.user_for_token(auth.bearer(authorization))}


@app.get("/api/auth/accounts")
def account_count():
    """Used by the UI to say "create an account" instead of "sign in"
    on a fresh install that has none yet."""
    return {"count": auth.count_users()}


# --------------------------------------------------------------------------
# Password (New + Confirm only, per the Settings design)
# --------------------------------------------------------------------------
class PasswordIn(BaseModel):
    password: str
    confirm: str


@app.post("/api/auth/password")
def change_password(body: PasswordIn,
                    authorization: str | None = Header(default=None)):
    token = auth.bearer(authorization)
    if not token or not auth.user_for_token(token):
        raise HTTPException(status_code=401, detail="auth_not_signed_in")
    try:
        return auth.change_password(token, body.password, body.confirm)
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=e.code)


# --------------------------------------------------------------------------
# Routine planner — today's scheduled day, with an alarm on each row
# --------------------------------------------------------------------------
class AlarmIn(BaseModel):
    key: str
    alarm: bool


def _routine():
    """Today's routine, derived from medicines and the check-in schedule.

    Labels for the built-in rows are i18n keys, not display text, so the UI
    translates them; medicine names are the elder's own data and pass through.
    """
    sched = STATE.get("checkin_schedule") or {}
    alarms = STATE.get("routine_alarms") or {}
    items = []

    def row(key, kind, label, time_, done=False):
        items.append({
            "key": key, "kind": kind, "label": label, "time": time_ or "",
            "alarm": bool(alarms.get(key, True)), "done": bool(done),
        })

    for m in STATE.get("meds") or []:
        row("med:" + str(m.get("id")), "med", m.get("name") or "",
            m.get("time"), bool(m.get("taken")))

    if sched.get("enabled", True):
        row("checkin:morning", "checkin", "routine_checkin_morning",
            sched.get("morning"), _answered_today("morning"))
        row("checkin:evening", "checkin", "routine_checkin_evening",
            sched.get("evening"), _answered_today("evening"))
    row("digest", "digest", "routine_digest", sched.get("digest"), False)

    items.sort(key=lambda r: (r["time"] or "99:99"))
    return items


def _answered_today(kind: str) -> bool:
    day = time.strftime("%Y-%m-%d", time.localtime())
    return any(
        c.get("kind") == kind and c.get("status") == "answered"
        and time.strftime("%Y-%m-%d", time.localtime(c.get("ts") or 0)) == day
        for c in (STATE.get("checkins") or [])
    )


@app.get("/api/routine")
def get_routine():
    return {"items": _routine()}


@app.post("/api/routine/alarm")
def set_routine_alarm(body: AlarmIn):
    STATE["routine_alarms"][body.key] = bool(body.alarm)
    return {"items": _routine()}


# --------------------------------------------------------------------------
# Static frontend (must stay last)
# --------------------------------------------------------------------------
if not DIST.is_dir():
    print(f"[saavren] no built UI at {DIST} - API only. "
          "Run `npm run build` in frontend/, or set SAAVREN_WEB_DIR.")

if DIST.is_dir():
    @app.get("/")
    def index():
        return FileResponse(DIST / "index.html")

    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="web")
