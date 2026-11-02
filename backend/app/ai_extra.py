"""Saavren extras — prescription / medicine-photo scan (multimodal).

Muse Spark Open on Baseten takes text + image input, so the scan can use a real
Meta model. Without a key (or on a failure) we fall back to a rule-based parser
stamped `source: "offline-fallback"` so the UI can be honest about it.
"""
from __future__ import annotations

import base64
import os
import re
import time
import uuid

from . import ai


def vision_extract(data: bytes, content_type: str = "", lang: str = "en") -> dict:
    """Read a prescription photo -> {summary, meds[], precautions[]}."""
    if data and ai._env("BASETEN_API_KEY"):
        try:
            return _vision_baseten(data, content_type, lang)
        except Exception as e:
            print(f"[saavren] scan fail -> {type(e).__name__}: {e}", flush=True)
    return _vision_offline(data, lang)


SYS = (
    "You read Indian prescription photos for an elderly patient. Reply STRICT "
    "JSON ONLY: {\"summary\": str, \"meds\": [{\"name\": str, \"time\": "
    "\"HH:MM\", \"note\": str}], \"precautions\": [str]}. Times in 24h; when "
    "the slip just says morning/afternoon/night use 09:00/14:00/21:00. Never "
    "invent a medicine you cannot read. Language: {lang}."
)


def _vision_baseten(data: bytes, content_type: str, lang: str) -> dict:
    import httpx

    b64 = base64.b64encode(data).decode()
    mime = content_type or "image/jpeg"
    body = {
        "model": ai.BASETEN_MODEL,
        "max_tokens": 600,
        "temperature": 1.0 if "muse" in ai.BASETEN_MODEL.lower() else 0.3,
        "messages": [
            {"role": "system",
             "content": SYS.replace("{lang}", ai._lang_name(lang))},
            {"role": "user", "content": [
                {"type": "text",
                 "text": "Ye prescription padho aur dawaiyon ki list banao."},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]},
        ],
    }
    with httpx.Client(timeout=90) as c:
        r = c.post(f"{ai.BASETEN_URL}/chat/completions",
                   headers={"Authorization": f"Bearer {ai._env('BASETEN_API_KEY')}"},
                   json=body)
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    obj = ai.parse_json_loose(txt) or {}
    meds = []
    for m in (obj.get("meds") or []):
        if isinstance(m, dict) and m.get("name"):
            meds.append({"name": str(m["name"])[:60],
                         "time": str(m.get("time") or "09:00")[:5],
                         "note": str(m.get("note") or "")[:160]})
    out = {"summary": str(obj.get("summary") or "")[:400], "meds": meds,
           "precautions": [str(p)[:200] for p in (obj.get("precautions") or [])][:5],
           "source": "baseten"}
    if not meds:
        raise RuntimeError("scan: koi dawai nahi mili")
    return out


def _vision_offline(data: bytes, lang: str) -> dict:
    """No vision model: be honest and hand the elder a manual path."""
    return {
        "summary": ("Photo mil gayi, par abhi scan ke liye koi vision model "
                    "connect nahi hai. Neeche dawai ka naam khud likh kar "
                    "add kar sakte hain — ya chat mein bol dein, main add kar "
                    "dungi." if (lang or "en").lower() == "hi" else
                    "Photo received, but no vision model is connected right "
                    "now. Type the medicine name below to add it, or just tell "
                    "me in chat and I'll add it."),
        "meds": [], "precautions": [],
        "source": "offline-fallback",
    }


# --------------------------------------------------------------------------
# D4 — nearest hospitals (OpenStreetMap / Overpass: free, no API key needed)
# --------------------------------------------------------------------------
_HOSP_CACHE: dict = {}
_HOSP_TTL = 30 * 60          # half an hour is plenty


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    import math
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


#: Several public Overpass mirrors. `overpass-api.de` (the canonical one) is
#: blocked by quite a few ISPs and corporate networks, so we try them all.
OVERPASS_MIRRORS = (
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)


def nearest_hospitals(lat: float, lon: float, radius_m: int = 6000,
                      limit: int = 6, timeout: float = 12) -> list[dict]:
    """Hospitals closest to the elder. Overpass (OpenStreetMap) is free and
    needs no key; unreachable -> a small curated list flagged as approximate,
    because showing something beatable is better than showing nothing."""
    import time
    key = (round(lat, 3), round(lon, 3), radius_m)
    hit = _HOSP_CACHE.get(key)
    if hit and time.time() - hit[0] < _HOSP_TTL:
        return hit[1]

    # Two independent OSM services. Nominatim answers in ~0.5 s from almost
    # anywhere; Overpass has the phone numbers but is often slow or blocked.
    # So: patient request -> Nominatim first; boot prefetch / manual refresh
    # (timeout >= 20) -> Overpass first, since there we can afford to wait.
    if timeout >= 20:
        out = _overpass(lat, lon, radius_m, limit, timeout) or \
              _nominatim(lat, lon, radius_m, limit, min(timeout, 12))
    else:
        out = _nominatim(lat, lon, radius_m, limit, min(timeout, 10)) or \
              _overpass(lat, lon, radius_m, limit, timeout)
    # Distance first: predictable beats clever. The emergency-ward tag comes
    # from OSM and is often missing (Nominatim almost never has it), so using
    # it as a sort key could push a 2.9 km hospital above a 1.3 km one.
    out.sort(key=lambda h: h["distance_m"] or 10 ** 9)
    out = out[:limit] or _fallback_hospitals()
    _HOSP_CACHE[key] = (time.time(), out)
    return out


def _overpass(lat, lon, radius_m, limit, timeout) -> list[dict]:
    """Full OSM tag query — gives phone numbers and emergency wards."""
    out: list[dict] = []
    try:
        import httpx
    except Exception:
        return out
    q = (f"[out:json][timeout:{int(max(5, min(25, timeout - 2)))}];("
         f'node["amenity"="hospital"](around:{radius_m},{lat},{lon});'
         f'way["amenity"="hospital"](around:{radius_m},{lat},{lon});'
         f");out center {limit * 4};")
    payload: list = []
    per_mirror = min(timeout, 6.0)        # never let one mirror eat the budget
    mirrors = OVERPASS_MIRRORS[:2] if timeout < 20 else OVERPASS_MIRRORS
    for url in mirrors:                   # mirrors: one is often unreachable
        try:
            with httpx.Client(timeout=per_mirror) as c:
                r = c.post(url, data={"data": q},
                           headers={"User-Agent": "Saavren/0.4 (elder-care)"})
            if r.status_code == 200:
                got = (r.json() or {}).get("elements") or []
                if got:
                    payload = got
                    break
        except Exception:
            continue
    for el in payload:
        tags = el.get("tags") or {}
        hlat = el.get("lat") or (el.get("center") or {}).get("lat")
        hlon = el.get("lon") or (el.get("center") or {}).get("lon")
        if hlat is None or hlon is None:
            continue
        name = (tags.get("name") or tags.get("name:en") or "").strip()
        if not name:                      # an unnamed hospital is useless
            continue
        out.append({
            "id": str(el.get("id")),
            "name": name[:90],
            "phone": (tags.get("phone") or tags.get("contact:phone")
                      or tags.get("emergency:phone") or "")[:40],
            "distance_m": int(haversine_m(lat, lon, hlat, hlon)),
            "lat": hlat, "lon": hlon,
            "emergency": tags.get("emergency") == "yes",
            "beds": tags.get("beds") or "",
            "map": ("https://www.google.com/maps/dir/?api=1&destination="
                    f"{hlat},{hlon}"),
            "source": "osm",
        })
    return out


def _nominatim(lat, lon, radius_m, limit, timeout) -> list[dict]:
    """Fallback when every Overpass mirror is unreachable: OSM's search API
    is a different host, so it often still works. No phone numbers, but it
    does return real, named, nearby hospitals with coordinates."""
    out: list[dict] = []
    try:
        import math

        import httpx
        dlat = radius_m / 111320.0
        dlon = radius_m / (111320.0 * max(0.2, math.cos(math.radians(lat))))
        # viewbox order: left(lon), top(lat), right(lon), bottom(lat)
        box = f"{lon - dlon:.5f},{lat + dlat:.5f},{lon + dlon:.5f},{lat - dlat:.5f}"
        url = ("https://nominatim.openstreetmap.org/search?format=json&bounded=1"
               f"&viewbox={box}&limit={limit * 3}&extratags=1&q=hospital")
        with httpx.Client(timeout=timeout) as c:
            r = c.get(url, headers={"User-Agent": "Saavren/0.4 (elder-care)"})
        if r.status_code != 200:
            return out
        for x in (r.json() or []):
            disp = (x.get("display_name") or "").split(",")
            name = (disp[0] or "").strip()
            if not name:
                continue
            try:
                hlat, hlon = float(x["lat"]), float(x["lon"])
            except Exception:
                continue
            tags = x.get("extratags") or {}
            out.append({
                "id": f"nom-{x.get('place_id') or abs(hash(name)) % 10**8}",
                "name": name[:90],
                "phone": (tags.get("phone") or tags.get("contact:phone") or "")[:40],
                "distance_m": int(haversine_m(lat, lon, hlat, hlon)),
                "lat": hlat, "lon": hlon,
                "emergency": "hospital" in (tags.get("healthcare") or ""),
                "beds": "",
                "map": ("https://www.google.com/maps/dir/?api=1&destination="
                        f"{hlat},{hlon}"),
                "source": "osm-search",
            })
    except Exception as e:
        print(f"[saavren] nominatim lookup fail -> {type(e).__name__}: {e}",
              flush=True)
    return out


def _fallback_hospitals() -> list[dict]:
    """Used only when Overpass cannot be reached; flagged `offline-list`."""
    return [
        {"id": "fb1", "name": "Swaroop Rani Nehru Hospital (Prayagraj)", "phone": "",
         "distance_m": None, "lat": None, "lon": None, "emergency": True,
         "beds": "", "map": "", "source": "offline-list"},
        {"id": "fb2", "name": "Motilal Nehru Medical College (Prayagraj)", "phone": "",
         "distance_m": None, "lat": None, "lon": None, "emergency": True,
         "beds": "", "map": "", "source": "offline-list"},
        {"id": "fb3", "name": "Ambulance / Police / Fire — dial 112", "phone": "112",
         "distance_m": None, "lat": None, "lon": None, "emergency": True,
         "beds": "", "map": "", "source": "offline-list"},
    ]


def geocode(place: str) -> tuple | None:
    """Nominatim geocoding (free; needs a descriptive User-Agent)."""
    if not place:
        return None
    try:
        import urllib.parse

        import httpx
        url = ("https://nominatim.openstreetmap.org/search?format=json&limit=1&q="
               + urllib.parse.quote(place))
        with httpx.Client(timeout=20) as c:
            r = c.get(url, headers={"User-Agent": "Saavren/0.4 (elder-care app)"})
        if r.status_code == 200:
            d = (r.json() or [{}])[0]
            return float(d["lat"]), float(d["lon"])
    except Exception as e:
        print(f"[saavren] geocode fail -> {type(e).__name__}: {e}", flush=True)
    return None


# --------------------------------------------------------------------------
# D4 — Emergency Card (what a stranger needs in 10 seconds)
# --------------------------------------------------------------------------
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{7,}\d)")


def parse_phone(text: str) -> str:
    m = _PHONE_RE.search(text or "")
    return re.sub(r"[\s\-()]", "", m.group(1)) if m else ""


def emergency_card(profile: dict, meds: list) -> dict:
    return {
        "name": profile.get("name", ""),
        "age": profile.get("age", ""),
        "gender": profile.get("gender", ""),
        "blood_group": profile.get("blood_group", ""),
        "conditions": list(profile.get("conditions") or []),
        "allergies": list(profile.get("allergies") or []),
        "weight_kg": profile.get("weight_kg", ""),
        "height_cm": profile.get("height_cm", ""),
        "medicines": [{"name": m.get("name", ""), "time": m.get("time", ""),
                       "note": m.get("note", "")} for m in (meds or [])[:8]],
        "emergency_contact": profile.get("emergency_contact", ""),
        "emergency_phone": parse_phone(profile.get("emergency_contact") or ""),
        "note": ("I'm Saavren, an AI assistant — not a doctor. This card is "
                 "prepared information, not a diagnosis."),
    }


def ecard_text(card: dict, hospitals: list | None = None) -> str:
    """Plain text — for SMS / WhatsApp / printing."""
    L = ["SAAVREN EMERGENCY CARD", "=" * 42,
         f"Name       : {card.get('name')}  ({card.get('age')} / {card.get('gender')})",
         f"Blood group: {card.get('blood_group') or '-'}",
         f"Conditions : {', '.join(card.get('conditions') or []) or '-'}",
         f"Allergies  : {', '.join(card.get('allergies') or []) or '-'}",
         "", "Current medicines:"]
    for m in card.get("medicines") or []:
        L.append(f"  - {m.get('name')} @ {m.get('time')}"
                 + (f" ({m.get('note')})" if m.get("note") else ""))
    L += ["", f"Contact    : {card.get('emergency_contact') or '-'}"]
    if hospitals:
        L += ["", "Nearest hospitals:"]
        for h in hospitals[:3]:
            d = f"{h['distance_m']} m" if h.get("distance_m") else "?"
            L.append(f"  - {h['name']} ({d})"
                     + (f"  tel {h['phone']}" if h.get("phone") else ""))
    L += ["", card.get("note", "")]
    return "\n".join(L)


# --------------------------------------------------------------------------
# Fall / thud wording used by the escalation flow
# --------------------------------------------------------------------------
def fall_question(lang: str = "en") -> str:
    lang = (lang or "en").lower()
    if lang in ("hi", "mr"):
        return "क्या आप ठीक हैं? गिरने की आवाज़ सुनी गई।"
    return "Are you OK? I heard a fall."


FALL_STRINGS = {
    "en": {"title": "Are you OK?", "sub": "I heard a thud — a possible fall.",
           "ok": "I'm OK", "help": "I need help", "checking": "Checking in…",
           "escalated": "No answer — your family and doctor have been alerted.",
           "cancelled": "Good — glad you're fine. Nothing was sent."},
    "hi": {"title": "क्या आप ठीक हैं?", "sub": "गिरने जैसी आवाज़ आई है।",
           "ok": "मैं ठीक हूँ", "help": "मुझे मदद चाहिए",
           "checking": "जाँच रहे हैं…",
           "escalated": "कोई जवाब नहीं मिला — परिवार और डॉक्टर को सूचित कर दिया है।",
           "cancelled": "अच्छा — आप ठीक हैं, कुछ नहीं भेजा गया।"},
}


# --------------------------------------------------------------------------
# D5 — the family monitor: one honest picture of the elder's day
# --------------------------------------------------------------------------
def ago(ts: float | None, now: float | None = None) -> str:
    """'just now' / '12 min ago' / '3 h ago' / '2 d ago'. Never raises."""
    if not ts:
        return "never"
    now = now if now is not None else time.time()
    s = max(0, int(now - float(ts)))
    if s < 45:
        return "just now"
    if s < 90:
        return "1 min ago"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 7200:
        return "1 h ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    d = s // 86400
    return "1 d ago" if d == 1 else f"{d} d ago"


def _day_start(now: float) -> float:
    """Midnight of `now`'s local day, as an epoch timestamp."""
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                        0, 0, 0, 0, 0, lt.tm_isdst))


#: activity sources that mean "the elder actually checked in today"
CHECKIN_SOURCES = ("checkin", "check-in", "voice", "triage", "agent", "note")


def daily_summary(state: dict, now: float | None = None) -> dict:
    """Turn raw app state into the answer to 'how is she today?'.

    Pure function — no network, no clock surprises (pass `now` in tests).
    The monitor and the LLM both read this, so there is exactly one version
    of "how the day went" in the product.
    """
    now = now if now is not None else time.time()
    start = _day_start(now)

    meds = list(state.get("meds") or [])
    activity = [a for a in (state.get("activity") or []) if isinstance(a, dict)]
    notifs = [n for n in (state.get("notifications") or []) if isinstance(n, dict)]
    emergencies = [e for e in (state.get("emergencies") or []) if isinstance(e, dict)]
    alarm = state.get("alarm") or {}

    today = [a for a in activity if float(a.get("ts") or 0) >= start]
    taken = [m for m in meds if m.get("taken")]
    pending = [m for m in meds if not m.get("taken")]

    # a medicine is "overdue" once its wall-clock slot has passed today
    hhmm = time.strftime("%H:%M", time.localtime(now))
    overdue = [m for m in pending if str(m.get("time") or "")[:5] <= hhmm
               and len(str(m.get("time") or "")) >= 4]

    unread = [n for n in notifs if not n.get("read")]
    open_inc = [e for e in emergencies if e.get("status") == "open"]
    today_inc = [e for e in emergencies if float(e.get("ts") or 0) >= start]

    last_seen = max((float(a.get("ts") or 0) for a in activity), default=None)

    highlights: list[str] = []
    concerns: list[str] = []

    if meds:
        highlights.append(f"{len(taken)} of {len(meds)} medicines taken today")
    if today:
        highlights.append(f"{len(today)} thing{'' if len(today) == 1 else 's'} "
                          f"logged today")
    # D6 — a real check-in record beats anything inferred from the feed
    todays_checkins = [c for c in (state.get("checkins") or [])
                       if isinstance(c, dict) and float(c.get("ts") or 0) >= start]
    missed = [c for c in todays_checkins if c.get("status") == "missed"]
    answered = [c for c in todays_checkins if c.get("status") == "answered"]
    checkins = [a for a in today
                if str(a.get("source") or "").lower() in CHECKIN_SOURCES]
    if answered:
        highlights.append(f"{len(answered)} check-in(s) answered")
    elif checkins:
        highlights.append(f"{len(checkins)} check-in(s) — she responded")
    if not today:
        highlights.append("nothing logged yet today")

    for m in overdue:
        concerns.append(f"{m.get('name')} was due at {m.get('time')} and is still pending")
    for c in missed:
        concerns.append(f"did not answer the {c.get('kind')} check-in")
    for c in answered:
        if c.get("mood") == "bad":
            concerns.append(f"reported feeling unwell at the {c.get('kind')} check-in")
        symptoms = [f for f in (c.get("flags") or []) if f in SYMPTOM_FLAGS]
        if symptoms:
            concerns.append(f"{c.get('kind')} check-in flagged: "
                            f"{', '.join(symptoms)}")
    if not checkins and today:
        concerns.append("no check-in from them yet today")
    if not today and not checkins:
        concerns.append("no activity at all today — worth a call")
    for e in open_inc:
        kind = "SOS" if e.get("kind") == "sos" else "fall"
        concerns.append(f"an unresolved {kind} incident from {ago(e.get('ts'), now)}")
    for n in unread:
        if n.get("kind") == "emergency":
            concerns.append(f"unread emergency alert: {n.get('title')}")
            break

    # ---- one word a family member can read at a glance -------------------
    if alarm.get("status") in ("ringing", "escalated") or open_inc:
        status = "emergency"
    elif concerns:
        status = "attention"
    else:
        status = "ok"

    return {
        "date": time.strftime("%Y-%m-%d", time.localtime(now)),
        "generated_at": now,
        "status": status,
        "meds_total": len(meds),
        "meds_taken": len(taken),
        "adherence": round(100 * len(taken) / len(meds)) if meds else None,
        "pending": [m.get("name") for m in pending],
        "overdue": [m.get("name") for m in overdue],
        "checkins": [
            {"ts": c.get("ts"), "kind": c.get("kind"), "mood": c.get("mood"),
             "score": c.get("score"), "flags": c.get("flags") or [],
             "status": c.get("status"), "text": c.get("summary")}
            for c in todays_checkins[:6]]
            + [{"ts": a.get("ts"), "kind": None, "mood": None, "score": None,
                "flags": [], "status": "answered", "text": a.get("text")}
               for a in checkins[:6] if not todays_checkins],
        "events_today": len(today),
        "unread": len(unread),
        "incidents_today": len(today_inc),
        "incidents_open": len(open_inc),
        "last_seen": last_seen,
        "last_seen_ago": ago(last_seen, now),
        "checkins_answered": len(answered),
        "checkins_missed": len(missed),
        "mood": (sorted(answered, key=lambda c: float(c.get("ts") or 0))[-1]
                 .get("mood") if answered else None),
        "flags": sorted({f for c in answered for f in (c.get("flags") or [])}),
        "highlights": highlights,
        "concerns": concerns,
    }


#: What a family member actually asks the monitor. Answered from the summary
#: so the dashboard still tells the truth when every LLM provider is down.
_FAMILY_Q = (
    (("how is", "kaisi", "kaise", "kaifi", "today", "aaj", "हाल", "कैसी",
      "कैसे"), "day"),
    (("medicine", "med", "dawa", "dawai", "goli", "tablet",
      "दवाई", "दवा"), "meds"),
    (("alert", "notification", "bell", "anything wrong", "kuch hua",
      "सूचना", "अलर्ट"), "alerts"),
    (("incident", "fell", "fall", "sos", "emergency", "gir",
      "घटना"), "incidents"),
    (("eat", "food", "khana", "meal", "breakfast", "lunch", "dinner",
      "खाना"), "meals"),
)


def offline_family(message: str, lang: str, summary: dict) -> str:
    """Answer 'how is she?' from the day summary, with no model involved."""
    t = (message or "").lower()
    topic = next((kind for keys, kind in _FAMILY_Q
                  if any(k in t for k in keys)), "day")

    name_bits = {
        "ok": "All normal today.", "attention": "Needs a little attention.",
        "emergency": "There is an emergency open right now.",
    }
    status_line = name_bits.get(summary.get("status"), "")

    if topic == "meds":
        if not summary.get("meds_total"):
            return "No medicines are on the list yet."
        taken, total = summary["meds_taken"], summary["meds_total"]
        body = f"{taken} of {total} medicines taken today."
        if summary.get("overdue"):
            body += " Still pending: " + ", ".join(summary["overdue"]) + "."
        elif summary.get("pending"):
            body += " Not due yet: " + ", ".join(summary["pending"]) + "."
        return body

    if topic == "alerts":
        n = summary.get("unread", 0)
        if not n:
            return "No new alerts. " + status_line
        # name the urgent thing first — an overdue pill is not why they asked
        urgent = next((c for c in (summary.get("concerns") or [])
                       if "alert" in c or "incident" in c), None)
        return f"{n} unread alert(s). " + \
            (urgent or (summary["concerns"][0] if summary.get("concerns")
                        else ""))

    if topic == "incidents":
        if summary.get("incidents_open"):
            inc = [c for c in summary["concerns"] if "incident" in c]
            return "Yes - " + (inc[0] if inc else "an incident is still open.")
        if summary.get("incidents_today"):
            return (f"{summary['incidents_today']} incident(s) today, "
                    "all resolved.")
        return "No falls or SOS today."

    if topic == "meals":
        return ("I don't track meals yet. I can see medicines, activity and "
                "incidents, so ask me about those." if lang == "en" else
                "Khana abhi track nahi karta — dawai, activity aur incidents "
                "dikha sakta hoon.")

    # ---- the default: the whole day in three lines ----------------------
    lines = [status_line]
    if summary.get("meds_total"):
        lines.append(f"{summary['meds_taken']}/{summary['meds_total']} "
                     "medicines taken.")
    lines.append(f"Last seen {summary.get('last_seen_ago') or 'a while ago'}.")
    if summary.get("concerns"):
        lines.append(summary["concerns"][0].capitalize() + ".")
    elif summary.get("highlights"):
        lines.append(summary["highlights"][-1].capitalize() + ".")
    return " ".join(x for x in lines if x)


# --------------------------------------------------------------------------
# D6 — the daily companion: proactive check-ins
#
# The elder never has to remember to report; Saavren asks. Two short scripts
# a day, in her own language, spoken aloud and answered by voice. The answers
# become structured notes the family can read on the monitor — and a check-in
# that never comes is itself a signal.
# --------------------------------------------------------------------------

#: Morning and evening scripts. Three questions each, plain words, no medical
#: jargon — this is a grandchild asking, not a form.
CHECKIN_SCRIPT = {
    "morning": {
        "en": ("Good morning, {name}. How did you sleep last night?",
               "I see. Any pain, dizziness or weakness this morning?",
               "Understood. Have you taken your morning medicine?"),
        "hi": ("सुप्रभात {name}। रात की नींद कैसी रही?",
               "अच्छा। आज सुबह कोई दर्द, चक्कर या कमज़ोरी तो नहीं?",
               "समझ गया। सुबह की दवा हो गई?"),
        "bn": ("সুপ্রভাত {name}। রাতে ঘুম কেমন হয়েছে?",
               "বুঝেছি। আজ সকালে কোনো ব্যথা, মাথা ঘোরা বা দুর্বলতা?",
               "বুঝেছি। সকালের ওষুধ খেয়েছেন?"),
        "ta": ("காலை வணக்கம் {name}। நேற்று இரவு தூக்கம் எப்படி இருந்தது?",
               "சரி. இன்று காலை ஏதும் வலி, தலைச்சுற்றல் அல்லது பலவீனம்?",
               "புரிந்தது. காலை மருந்து எடுத்துவிட்டீர்களா?"),
        "te": ("శుభోదయం {name}। రాత్రి నిద్ర ఎలా ఉంది?",
               "అర్థమైంది. ఈ ఉదయం ఏదైనా నొప్పి, తలతిరగడం లేదా బలహీనత?",
               "అర్థమైంది. ఉదయం మందు తీసుకున్నారా?"),
        "mr": ("सुप्रभात {name}। रात्रीची झोप कशी झाली?",
               "समजले. आज सकाळी काही दुखणे, चक्कर येणे किंवा अशक्तपणा?",
               "समजले. सकाळचे औषध झाले का?"),
        "gu": ("સુપ્રભાત {name}। રાતની ઊંઘ કેવી રહી?",
               "સમજાયું. આજે સવારે કોઈ દુખાવો, ચક્કર કે નબળાઈ?",
               "સમજાયું. સવારની દવા થઈ ગઈ?"),
        "es": ("Buenos días, {name}. ¿Cómo durmió anoche?",
               "Entiendo. ¿Algún dolor, mareo o debilidad esta mañana?",
               "Entendido. ¿Ya tomó su medicina de la mañana?"),
        "fr": ("Bonjour {name}. Comment avez-vous dormi cette nuit ?",
               "Je vois. Des douleurs, des vertiges ou une faiblesse ce matin ?",
               "Compris. Avez-vous pris votre médicament du matin ?"),
    },
    "evening": {
        "en": ("Good evening, {name}. How was your day?",
               "Any pain or discomfort right now?",
               "And your evening medicine — did you take it?"),
        "hi": ("नमस्ते {name}। आज का दिन कैसा रहा?",
               "अभी कोई दर्द या बेचैनी तो नहीं?",
               "और शाम की दवा — हो गई?"),
        "bn": ("শুভ সন্ধ্যা {name}। আজকের দিন কেমন কাটল?",
               "এখন কোনো ব্যথা বা অস্বস্তি আছে?",
               "আর সন্ধ্যার ওষুধ — খেয়েছেন?"),
        "ta": ("மாலை வணக்கம் {name}. இன்றைய நாள் எப்படி இருந்தது?",
               "இப்போது ஏதும் வலி அல்லது சங்கடம் இருக்கிறதா?",
               "மாலை மருந்து — எடுத்துவிட்டீர்களா?"),
        "te": ("శుభ సాయంత్రం {name}। ఈ రోజు ఎలా గడిచింది?",
               "ఇప్పుడు ఏదైనా నొప్పి లేదా అసౌకర్యం ఉందా?",
               "సాయంత్రం మందు — తీసుకున్నారా?"),
        "mr": ("नमस्कार {name}। आजचा दिवस कसा गेला?",
               "आत्ता काही दुखणे किंवा अस्वस्थता आहे का?",
               "आणि संध्याकाळचे औषध — झाले का?"),
        "gu": ("સાંજે નમસ્તે {name}। આજનો દિવસ કેવો ગયો?",
               "અત્યારે કોઈ દુખાવો કે અગવડ છે?",
               "અને સાંજની દવા — થઈ ગઈ?"),
        "es": ("Buenas tardes, {name}. ¿Cómo le fue hoy?",
               "¿Tiene algún dolor o molestia ahora mismo?",
               "¿Y la medicina de la noche, la tomó?"),
        "fr": ("Bonsoir {name}. Comment s'est passée votre journée ?",
               "Une douleur ou une gêne en ce moment ?",
               "Et votre médicament du soir, l'avez-vous pris ?"),
    },
}

CHECKIN_KINDS = ("morning", "evening")

#: Default times. Configurable per elder (PUT /api/checkin/schedule).
# digest is the end-of-day note the monitor receives; it needs a default
# time or the routine row has nothing to ring at
CHECKIN_SCHEDULE = {"morning": "09:00", "evening": "21:00",
                    "digest": "21:30", "enabled": True}

#: How long a check-in stays on screen before it counts as unanswered.
CHECKIN_GRACE_MIN = 45

#: Words that carry the answer. Deliberately broad — an elder says "theek
#: hai" (fine) far more often than she says "I am well, thank you".
MOOD_GOOD = (
    "good", "great", "fine", "well", "better", "happy", "nice", "perfect",
    "theek", "thik", "achha", "acha", "achchha", "badhiya", "badiya", "sahi",
    "khush", "maja", "majja", "aram", "aaram", "bien", "bien", "bon",
    "thik ache", "bhalo", "bhal", "nalla", "nallathu", "bagundi", "bagunde",
    "chan", "chhan", "thik aahe", "barobar", "sarvas", "majama",
)
MOOD_BAD = (
    # NB: never list a bare "bad" — it hides inside "badhiya" (very good).
    "bad", "bura", "ganda", "worse", "worst", "awful", "terrible",
    "not good",
    "not well", "not fine", "pain", "hurt", "sick", "weak", "dizzy", "fever",
    "tired", "sore", "fall", "fell", "gir ", "gira", "giri", "gire",
    "unwell", "dard", "dukh", "bukhaar", "bukhar", "chakkar", "kamzori",
    "kamjori", "thaka", "thakan", "bimaar", "beemar", "tabiyat kharab",
    "theek nahi", "thik nahi", "acha nahi", "achha nahi", "pareshan",
    "kharaab", "kharab", "bishi", "byatha", "jwor", "jhoka", "durbol",
    "vali", "valikk", "noppi", "badha", "dukhate", "dolo", "mal", "douleur",
    "mareo", "debil", "cansado", "malo", "fatigue", "faible",
)

#: A "sleep" mention is a topic; a "pain" mention is a symptom. Only symptoms
#: raise a concern on the monitor — otherwise "I slept well" pings the family.
SYMPTOM_FLAGS = ("pain", "dizziness", "fever", "breath")

#: Specific things worth telling the family about, whatever the mood is.
HEALTH_FLAGS = (
    ("pain", ("pain", "dard", "dukh", "hurt", "sore", "vali", "noppi",
              "dukhate", "byatha", "douleur", "dolor")),
    ("dizziness", ("dizzy", "chakkar", "ghuma", "jhoka", "vertig", "mareo",
                   "talachural")),
    ("fever", ("fever", "bukhaar", "bukhar", "jor", "jwor", "taapam",
               "jwara", "fiebre", "fièvre", "kaychi")),
    ("breath", ("breath", "saans", "sans", "dam", "huff", "respir",
                "moochu", "shwas")),
    ("appetite", ("khana", "bhookh", "bhukh", "eat", "appetite", "meal",
                  "food", "comida", "manger", "saapaadu", "bhojan")),
    ("sleep", ("sleep", "neend", "nind", "nidra", "slept", "dormir",
               "dormi", "thoong", "nidura")),
    ("mobility", ("walk", "chal", "gir", "fall", "slip", "stairs",
                  "seedhi", "chalu", "nadappu")),
)

#: A "no" that flips the word it sits next to. "dard nahi hai" is good news,
#: but "bukhaar hai, theek nahi" is not — so negation is judged in a small
#: window around each word, never across the whole sentence.
NEGATIONS = ("nahi", "nahin", "nhi", "not ", "no ", "nope", "na ", "illa",
             "ledu", "naahi", "nathi", "kadha", "aucun", "ningun",
             "ning\u00fan", "pas de", "koi nahi", "bina")


#: Negation is judged inside a clause, not across the sentence: in
#: "dard nahi hai, sab theek hai" the "nahi" belongs to "dard" only, and in
#: "theek nahi, bukhaar hai" it belongs to "theek" only.
_CLAUSE = re.compile(r"[,.;!?\n\u0964]")


_RX: dict = {}


def _rx(word: str):
    """Word-boundary matcher for one keyword (substring matching is what let
    "bad" hide inside "badhiya", which means the exact opposite)."""
    w = word.strip()
    if not w:
        return None
    r = _RX.get(w)
    if r is None:
        r = re.compile(r"(?<!\w)" + re.escape(w) + r"(?!\w)")
        _RX[w] = r
    return r


def _hits(t: str, words) -> list[str]:
    """Words she actually said she HAS, minus the ones she denied.

    A word counts if there is at least one clause where it appears with no
    negation next to it.
    """
    out = []
    for w in words:
        rx = _rx(w)
        if rx is None:
            continue
        if any(rx.search(c) and not any(n in c for n in NEGATIONS)
               for c in _CLAUSE.split(t)):
            out.append(w)
    return out


def checkin_script(kind: str, lang: str = "en", name: str = "") -> list[str]:
    """The questions for one check-in, in the elder's language."""
    table = CHECKIN_SCRIPT.get(kind) or CHECKIN_SCRIPT["morning"]
    qs = table.get((lang or "en").lower()) or table["en"]
    return [q.replace("{name}", name or "") for q in qs]


def extract_mood(text: str, lang: str = "en") -> dict:
    """Read one spoken answer -> {mood, score, flags, negative}.

    Pure keyword work, so it still functions with every model offline. The
    LLM is asked for a nicer summary only when one is reachable.
    """
    t = " " + (text or "").lower().strip() + " "
    good = len(_hits(t, MOOD_GOOD))
    bad = len(_hits(t, MOOD_BAD))

    if bad > good:
        mood, score = ("bad", 1)
    elif good > bad:
        mood, score = ("good", 3)
    elif good or bad:
        mood, score = ("ok", 2)
    else:
        mood, score = ("unknown", None)

    # only report a symptom she actually said she has
    flags = [name for name, words in HEALTH_FLAGS if _hits(t, words)]
    return {"mood": mood, "score": score, "flags": flags,
            "negative": any(n in t for n in NEGATIONS),
            "text": (text or "").strip()[:400]}


def checkin_record(kind: str, lang: str, answers: list[dict],
                   now: float | None = None) -> dict:
    """Fold the answers of one check-in into a single stored note."""
    now = now if now is not None else time.time()
    reads = [extract_mood(a.get("a") or "", lang) for a in answers]
    scored = [r for r in reads if r["score"] is not None]
    score = round(sum(r["score"] for r in scored) / len(scored), 2) if scored \
        else None
    if score is None:
        mood = "unknown"
    elif score >= 2.5:
        mood = "good"
    elif score >= 1.6:
        mood = "ok"
    else:
        mood = "bad"

    flags = sorted({f for r in reads for f in r["flags"]})
    return {
        "id": uuid.uuid4().hex[:8],
        "kind": kind, "ts": now, "lang": lang,
        "status": "answered",
        "mood": mood, "score": score,
        "flags": flags,
        "answers": [{"q": a.get("q"), "a": a.get("a")} for a in answers],
        "summary": _checkin_summary(mood, flags, lang),
    }


def _checkin_summary(mood: str, flags: list[str], lang: str) -> str:
    words = {
        "good": {"en": "feeling well", "hi": "tabiyat achhi",
                 "bn": "bhalo achen", "ta": "nallam irukkirar",
                 "te": "bagunnaru", "mr": "tabyet changli",
                 "gu": "tabiyat sari", "es": "se encuentra bien",
                 "fr": "se sent bien"},
        "ok": {"en": "managing, not her best", "hi": "theek-thaak",
               "bn": "more-mori bhalo", "ta": "sariyaga irukkirar",
               "te": "parledu anukonandi", "mr": "thodya bara",
               "gu": "thodu barabar", "es": "regular", "fr": "comme ci comme ça"},
        "bad": {"en": "not feeling well", "hi": "tabiyat theek nahi",
                "bn": "shorir bhalo nei", "ta": "udalnalam illamai",
                "te": "bagoledandi", "mr": "tabyet bari nahi",
                "gu": "tabiyat barabar nathi", "es": "no se encuentra bien",
                "fr": "ne se sent pas bien"},
        "unknown": {"en": "answered, unclear", "hi": "jawab mila, saaf nahi",
                    "bn": "uttar pelam, spasto noi",
                    "ta": "pathil kidaithathu, thelivillai",
                    "te": "samadhanam vachindi, spashtam ledu",
                    "mr": "uttar milale, spasht nahi",
                    "gu": "javab madyo, spasht nathi",
                    "es": "respondió, poco claro",
                    "fr": "a répondu, peu clair"},
    }
    base = (words.get(mood) or words["unknown"]).get(lang) or \
        words.get(mood, words["unknown"])["en"]
    if flags:
        return f"{base} · {', '.join(flags)}"
    return base


def due_checkin(state: dict, now: float | None = None) -> dict | None:
    """Which check-in should be on screen right now, if any.

    Returns None when nothing is due. `kind` is morning/evening; `overdue_min`
    is how long it has been waiting unanswered.
    """
    now = now if now is not None else time.time()
    sched = state.get("checkin_schedule") or CHECKIN_SCHEDULE
    if not sched.get("enabled", True):
        return None
    start = _day_start(now)
    done = {c.get("kind") for c in (state.get("checkins") or [])
            if float(c.get("ts") or 0) >= start
            and c.get("status") in ("answered", "skipped")}
    missed = {c.get("kind") for c in (state.get("checkins") or [])
              if float(c.get("ts") or 0) >= start
              and c.get("status") == "missed"}

    for kind in CHECKIN_KINDS:
        if kind in done or kind in missed:
            continue
        hh, mm = (str(sched.get(kind) or "09:00").split(":") + ["0"])[:2]
        try:
            slot = start + int(hh) * 3600 + int(mm) * 60
        except ValueError:
            continue
        if now >= slot:
            return {"kind": kind, "due_at": slot,
                    "overdue_min": int((now - slot) // 60)}
    return None


def daily_digest(state: dict, now: float | None = None) -> dict:
    """D6 — the end-of-day note the family wakes up to.

    Everything the monitor already shows, plus the check-in story: what she
    said, how she sounded, what to keep an eye on. `text` is plain, so it can
    go straight to the monitor, an SMS or a WhatsApp message.
    """
    now = now if now is not None else time.time()
    s = daily_summary(state, now)
    start = _day_start(now)
    p = state.get("profile") or {}
    name = (p.get("name") or "She").split(" ")[0]

    todays = [c for c in (state.get("checkins") or [])
              if isinstance(c, dict) and float(c.get("ts") or 0) >= start]
    answered = [c for c in todays if c.get("status") == "answered"]
    missed = [c for c in todays if c.get("status") == "missed"]

    moods = [c.get("mood") for c in answered if c.get("mood") != "unknown"]
    flags = sorted({f for c in answered for f in (c.get("flags") or [])})

    if not moods:
        mood = "unknown"
    elif "bad" in moods:
        mood = "bad"
    elif "ok" in moods:
        mood = "ok"
    else:
        mood = "good"

    lines = [f"{name} — {s['date']}"]
    if answered:
        lines.append(f"Check-ins: {len(answered)} answered, {len(missed)} missed.")
        for c in answered:
            lines.append(f"  {c.get('kind')}: {c.get('summary')}")
    else:
        lines.append("No check-ins answered today.")
    if missed:
        lines.append("Missed: " + ", ".join(c.get("kind") for c in missed))
    lines.append(f"Medicines: {s['meds_taken']}/{s['meds_total']} taken.")
    if s.get("overdue"):
        lines.append("Still pending: " + ", ".join(s["overdue"]))
    if flags:
        lines.append("Mentioned: " + ", ".join(flags))
    lines.append(f"Last active: {s['last_seen_ago']}.")

    return {
        "date": s["date"], "generated_at": now,
        "status": s["status"], "mood": mood, "flags": flags,
        "checkins": todays,
        "answered": len(answered), "missed": len(missed),
        "missed_kinds": [c.get("kind") for c in missed],
        "meds_taken": s["meds_taken"], "meds_total": s["meds_total"],
        "overdue": s["overdue"],
        "highlights": s["highlights"], "concerns": s["concerns"],
        "last_seen_ago": s["last_seen_ago"],
        "text": "\n".join(lines),
    }


# --------------------------------------------------------------------------
# D7 — Sehat Board: the body, the week, the trend
# --------------------------------------------------------------------------
#: Points reward consistency, not fitness — anyone can climb the board.
POINTS = {
    "checkin": 8,      # answered a check-in
    "med": 10,         # a medicine taken on time
    "activity": 5,     # walked / did something
    "vitals": 4,       # logged a reading
    "chat": 3,         # talked with Saavren
    "med_missed": -5,  # a medicine left untaken that day
    "checkin_missed": -5,
}
POINTS_CAP = {"activity": 6, "chat": 8}     # no gaming by chattering

#: Asian-Indian cut-offs (ICMR / WHO Asia-Pacific) — the Western 25.0
#: "overweight" line under-flags risk in Indian adults by a wide margin.
BMI_BANDS = ((18.5, "underweight"), (23.0, "normal"),
             (25.0, "overweight"), (99.0, "obese"))

#: [high, high, ...] boundaries -> band name, per reading type.
VITAL_BANDS = {
    "bp_sys": ((120, "normal"), (130, "elevated"), (140, "high"),
               (180, "very high"), (9999, "critical")),
    "bp_dia": ((80, "normal"), (90, "high"), (120, "very high"),
               (9999, "critical")),
    "sugar": ((140, "normal"), (200, "high"), (9999, "very high")),
    "pulse": ((60, "low"), (101, "normal"), (9999, "high")),
    "spo2": ((95, "critical"), (9999, "normal")),   # inverted: low is bad
}

VITAL_META = {
    "bp_sys": {"label": "BP systolic", "unit": "mmHg", "icon": "🩺"},
    "bp_dia": {"label": "BP diastolic", "unit": "mmHg", "icon": "🩺"},
    "sugar": {"label": "Sugar", "unit": "mg/dL", "icon": "🍬"},
    "pulse": {"label": "Pulse", "unit": "bpm", "icon": "❤️"},
    "spo2": {"label": "SpO2", "unit": "%", "icon": "🫁"},
}


def bmi(weight_kg, height_cm) -> dict | None:
    """Body mass index + the Asian-Indian band it falls in."""
    try:
        w, h = float(weight_kg), float(height_cm)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    val = round(w / (h / 100) ** 2, 1)
    band = next(name for limit, name in BMI_BANDS if val < limit)
    return {"bmi": val, "band": band}


def vital_band(kind: str, value) -> str | None:
    """Which band a single reading falls in — the same words the UI and the
    monitor both use, so a number never gets described two ways."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    bands = VITAL_BANDS.get(kind)
    if not bands:
        return None
    if kind == "spo2":          # low is the danger, not high
        return "normal" if v >= 95 else ("low" if v >= 92 else "critical")
    return next(name for limit, name in bands if v < limit)


def vital_entry(payload: dict, ts: float | None = None) -> dict:
    """Normalise one vitals reading into a stored record."""
    keys = ("bp_sys", "bp_dia", "sugar", "pulse", "spo2")
    rec = {"id": uuid.uuid4().hex[:8], "ts": ts or time.time(),
           "source": str(payload.get("source") or "manual")[:20],
           "note": str(payload.get("note") or "")[:200]}
    for k in keys:
        v = payload.get(k)
        try:
            rec[k] = round(float(v), 1) if v is not None and v != "" else None
        except (TypeError, ValueError):
            rec[k] = None
    rec["bands"] = {k: vital_band(k, rec[k]) for k in keys if rec[k] is not None}
    return rec


def latest_vitals(vitals: list[dict]) -> dict:
    """The newest value for each reading, with how long ago it was taken."""
    out = {}
    for kind in VITAL_META:
        hits = [v for v in (vitals or [])
                if isinstance(v, dict) and v.get(kind) is not None]
        if not hits:
            continue
        newest = max(hits, key=lambda v: float(v.get("ts") or 0))
        out[kind] = {"value": newest[kind], "ts": newest["ts"],
                     "band": vital_band(kind, newest[kind]),
                     "ago": ago(newest["ts"])}
    return out


def vitals_series(vitals: list[dict], days: int = 14,
                  now: float | None = None) -> dict:
    """Per-reading series for sparklines, oldest first."""
    now = now if now is not None else time.time()
    cutoff = now - days * 86400
    rows = [v for v in (vitals or [])
            if isinstance(v, dict) and float(v.get("ts") or 0) >= cutoff]
    rows.sort(key=lambda v: float(v.get("ts") or 0))
    out = {}
    for kind in VITAL_META:
        pts = [{"t": v["ts"], "v": v[kind]}
               for v in rows if v.get(kind) is not None]
        if pts:
            out[kind] = pts
    return out


def day_points(state: dict, start: float, end: float) -> dict:
    """Points earned inside one [start, end) window, from real events only."""
    in_day = lambda ts: start <= float(ts or 0) < end        # noqa: E731

    checkins = [c for c in (state.get("checkins") or []) if in_day(c.get("ts"))]
    answered = [c for c in checkins if c.get("status") == "answered"]
    ck_missed = [c for c in checkins if c.get("status") == "missed"]
    meds = [m for m in (state.get("med_log") or []) if in_day(m.get("ts"))]
    vitals = [v for v in (state.get("vitals") or []) if in_day(v.get("ts"))]

    acts = [a for a in (state.get("activity") or [])
            if in_day(a.get("ts")) and a.get("source") not in
            ("system", "monitor", "checkin")]
    # one event, one score: a chat turn is a chat, not also a walk
    chats = [a for a in acts if a.get("source") in ("agent", "triage", "voice")]
    moved = [a for a in acts if a.get("source") not in
             ("agent", "triage", "voice")]

    def capped(n, key):
        return min(n, POINTS_CAP.get(key, 10 ** 6))

    total = (
        len(answered) * POINTS["checkin"]
        + len(meds) * POINTS["med"]
        + capped(len(moved), "activity") * POINTS["activity"]
        + len(vitals) * POINTS["vitals"]
        + capped(len(chats), "chat") * POINTS["chat"]
        + len(ck_missed) * POINTS["checkin_missed"]
    )
    seeded = any(x.get("source") == "demo-seed"
                 for x in (checkins + meds + vitals))
    return {
        "points": total,
        "checkins": len(answered),
        "checkins_missed": len(ck_missed),
        "meds": len(meds),
        "vitals": len(vitals),
        "activity": len(moved),
        "chats": len(chats),
        "seeded": seeded,
    }


def weekly_board(state: dict, now: float | None = None) -> dict:
    """Seven days, scored and ranked against each other.

    Ranked against HER OWN week, not against strangers: there are no other
    users in this build, and inventing a peer leaderboard would be a lie the
    family might act on.
    """
    now = now if now is not None else time.time()
    start = _day_start(now)
    days = []
    for back in range(6, -1, -1):
        d0 = start - back * 86400
        d1 = d0 + 86400
        lt = time.localtime(d0)
        scored = day_points(state, d0, d1)
        days.append({
            "date": time.strftime("%Y-%m-%d", lt),
            "day": time.strftime("%A", lt),
            "short": time.strftime("%a %d", lt),
            # locale-independent weekday; the UI translates dow_<mon..sun>
            # so the board reads in the elder's language, not the server's
            "dow": time.strftime("%a", lt).lower(),
            "today": back == 0,
            **scored,
        })

    ranked = sorted((d for d in days), key=lambda d: -d["points"])
    for i, d in enumerate(ranked):
        d["rank"] = i + 1
    today = days[-1]

    active = [d for d in days if d["points"] > 0]
    streak = 0
    for d in reversed(days):
        if d["points"] > 0:
            streak += 1
        elif not d["today"]:
            break

    total = sum(d["points"] for d in days)
    target = 300
    return {
        "days": days, "today": today, "ranked": ranked,
        "total": total, "target": target,
        "streak": streak,
        "best": ranked[0] if ranked and ranked[0]["points"] > 0 else None,
        "pct": min(100, round(100 * max(0, total) / target)),
        "seeded": any(d.get("seeded") for d in days),
        "badge": "badge_star" if total >= target else None,
    }


def sehat_board(state: dict, now: float | None = None) -> dict:
    """D7 — one payload for the whole health board."""
    now = now if now is not None else time.time()
    p = state.get("profile") or {}
    vitals = state.get("vitals") or []
    b = bmi(p.get("weight_kg"), p.get("height_cm"))
    latest = latest_vitals(vitals)
    flags = [k for k, v in latest.items()
             if v.get("band") in ("high", "very high", "critical", "low")]
    wk = weekly_board(state, now)
    return {
        "profile": p,
        "bmi": b,
        "vitals_latest": latest,
        "vitals_series": vitals_series(vitals, 14, now),
        "vitals_count": len(vitals),
        "alerts": flags,
        "board": wk,
        "points_today": wk["today"]["points"],
        "generated_at": now,
    }
