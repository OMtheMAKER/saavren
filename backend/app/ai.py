"""Saavren AI layer — everything degrades gracefully, nothing ever crashes.

Stack (card-free, Meta open-weights first):
  ASR  : Meta MMS `facebook/mms-1b-all` via the HF router (HF_TOKEN)
         -> Whisper on Groq (GROQ_API_KEY)
         -> the browser's own Web Speech engine (no key at all)
  Brain: Meta Muse Spark Open on Baseten (BASETEN_API_KEY)
         -> Groq openai/gpt-oss-120b (GROQ_API_KEY)
         -> HF router (opt-in, ENABLE_HF_LLM=1 — free accounts have no credits)
         -> a rule-based offline mirror stamped `source: "offline-fallback"`

AUDIO: the browser encodes mic audio to 16 kHz mono PCM WAV, so the elder's
machine needs no ffmpeg. ffmpeg stays optional (only for webm/ogg/mp4 uploads).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------
# .env support (repo root), loaded BEFORE any os.getenv so keys are visible.
# --------------------------------------------------------------------------
try:  # pragma: no cover - trivial
    from dotenv import load_dotenv

    _ROOT = Path(__file__).resolve().parents[2]
    load_dotenv(_ROOT / ".env", override=False)
except Exception:  # python-dotenv optional at runtime
    pass

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
#: Meta's newest open-weight model (816B-A42B MoE, Oct 2026), served by Baseten.
#: Meta's Llama 4 Maverick left Baseten's shared catalog, so this is the current
#: Meta open-weights option there — and it is multimodal (text/image/video/audio
#: in), which the prescription scan uses.
BASETEN_MODEL = os.getenv("BASETEN_MODEL", "meta-models/muse-spark-open")
BASETEN_URL = os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1").rstrip("/")

#: Groq retired llama-3.3-70b-versatile on 2026-08-16 (404 on every call).
GROQ_MODELS = [m.strip() for m in (
    os.getenv("GROQ_MODELS") or
    "openai/gpt-oss-120b,qwen/qwen3.6-27b,openai/gpt-oss-20b").split(",")
    if m.strip()]
GROQ_MODEL = GROQ_MODELS[0]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

HF_LLM_MODEL = os.getenv("HF_LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
#: OpenAI-compatible chat lives at /v1 — …/hf-inference/models/<id>/v1/... 400s.
HF_LLM_URL = os.getenv("HF_LLM_URL",
                       "https://router.huggingface.co/v1/chat/completions")

ASR_MODEL = os.getenv("ASR_MODEL", "facebook/mms-1b-all")
GROQ_ASR_MODEL = os.getenv("GROQ_ASR_MODEL", "whisper-large-v3-turbo")
#: hf-inference no longer serves MMS, so the router needs a provider that does.
ASR_MMS_PROVIDERS = [p.strip() for p in (
    os.getenv("ASR_MMS_PROVIDERS") or "fal,replicate,nebius,hf-inference"
).split(",") if p.strip()]
HF_ROUTER = "https://router.huggingface.co"

TIMEOUT = float(os.getenv("AI_TIMEOUT", "45"))

DISCLAIMER = (
    "\n\n_मैं सावरें हूँ — एक AI सहायक। मैं डॉक्टर नहीं हूँ; "
    "यह सलाह तब तक है जब तक आप अपने डॉक्टर से मिलते हैं।_"
)
DISCLAIMER_HI_LATIN = (
    "\n\n_Main Saavren hoon — ek AI sahayak. Main doctor nahi hoon; "
    "yeh salah tabtak hai jabtak aap apne doctor se milte hain._"
)
DISCLAIMER_EN = (
    "\n\n_I'm Saavren, an AI assistant — not a doctor. This is first-aid "
    "guidance until you reach a real clinician._"
)


# --------------------------------------------------------------------------
# HTTP helper
# --------------------------------------------------------------------------
def _post(url: str, *, headers: dict, data=None, files=None,
          json_body=None, timeout: float = TIMEOUT):
    import httpx

    with httpx.Client(timeout=timeout) as c:
        if files is not None:
            return c.post(url, headers=headers, data=data, files=files)
        return c.post(url, headers=headers, json=json_body)


def _env(key: str) -> str:
    """Read a key and strip stray whitespace/quotes.

    `.env` files written by hand often end up as  KEY="abc123"  — the quotes
    then travel inside the Authorization header and the provider answers 401,
    which looks exactly like "key missing".
    """
    v = (os.getenv(key) or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v


def _mask(v: str) -> str:
    if not v:
        return ""
    if len(v) <= 10:
        return v[:2] + "…" + "*" * (len(v) - 2)
    return f"{v[:4]}…{v[-3:]} (len {len(v)})"


def key_preview() -> dict:
    return {"HF_TOKEN": _mask(_env("HF_TOKEN")),
            "BASETEN_API_KEY": _mask(_env("BASETEN_API_KEY")),
            "GROQ_API_KEY": _mask(_env("GROQ_API_KEY"))}


# --------------------------------------------------------------------------
# HF token health — checked once and cached
# --------------------------------------------------------------------------
_HF_STATUS: dict = {"checked": False, "ok": False, "detail": "unchecked",
                    "credits": True}


def hf_token_status(force: bool = False) -> tuple[bool, str]:
    """(ok, detail) for HF_TOKEN."""
    tok = _env("HF_TOKEN")
    if not tok:
        return False, "missing"
    if _HF_STATUS["checked"] and not force:
        return _HF_STATUS["ok"], _HF_STATUS["detail"]
    ok, detail = True, "unverified (no network)"   # network down -> stay optimistic
    try:
        import httpx
        with httpx.Client(timeout=10) as c:
            r = c.get("https://huggingface.co/api/whoami-v2",
                      headers={"Authorization": f"Bearer {tok}"})
        if r.status_code == 200:
            ok, detail = True, "ok"
        elif r.status_code in (401, 403):
            ok, detail = False, f"invalid (HTTP {r.status_code})"
        elif r.status_code >= 500:
            ok, detail = True, f"unverified (HTTP {r.status_code})"
        else:
            ok, detail = True, f"ok (HTTP {r.status_code})"
    except Exception as e:
        ok, detail = True, f"unverified ({type(e).__name__})"
    _HF_STATUS.update(checked=True, ok=ok, detail=detail)
    return ok, detail


def hf_credits_ok() -> bool:
    """False once HF has answered 402 (no Inference Providers credits)."""
    return _HF_STATUS.get("credits", True)


def _hf_headers() -> dict:
    tok = _env("HF_TOKEN")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


# --------------------------------------------------------------------------
# Audio helpers
# --------------------------------------------------------------------------
def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def to_wav(data: bytes, content_type: str = "audio/wav") -> bytes:
    """Return 16 kHz mono PCM WAV. Browsers already send that; anything else is
    converted with ffmpeg when it happens to be installed."""
    if data[:4] == b"RIFF":
        return _resample_wav(data)
    exe = ffmpeg_bin()
    if not exe:
        return data            # let the provider try its luck
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.bin"
        dst = Path(d) / "out.wav"
        src.write_bytes(data)
        subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(src),
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                        str(dst)], check=False, capture_output=True, timeout=90)
        return dst.read_bytes() if dst.exists() else data


def decode_wav(data: bytes) -> tuple[list[int], int, int]:
    """Parse a WAV (8/16/32-bit, any channel count) -> (samples, ch, rate).

    Pure stdlib: `audioop` was deleted from Python in 3.13, so everything here
    is hand-rolled. Samples are normalised to int16.
    """
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return [], 0, 0
    pos, rate, ch, width, pcm = 12, 0, 1, 16, b""
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            ch, rate = struct.unpack("<HI", body[2:8])
            # [12:14] is block align, [14:16] is bits per sample
            width = struct.unpack("<H", body[14:16])[0]
        elif cid == b"data":
            pcm = body
        pos += 8 + size + (size & 1)
    if not pcm or not rate:
        return [], 0, 0

    if width == 16:
        vals = list(struct.unpack(f"<{len(pcm) // 2}h", pcm[:len(pcm) // 2 * 2]))
    elif width == 8:                       # 8-bit WAV is unsigned, centred on 128
        vals = [(b - 128) * 256 for b in pcm]
    elif width == 32:
        vals = [v >> 16 for v in
                struct.unpack(f"<{len(pcm) // 4}i", pcm[:len(pcm) // 4 * 4])]
    else:
        return [], 0, 0

    if ch > 1:                             # down-mix to mono
        n = len(vals) // ch
        vals = [sum(vals[i * ch:(i + 1) * ch]) // ch for i in range(n)]
        ch = 1
    return vals, ch, rate


def resample(vals: list[int], src: int, dst: int) -> list[int]:
    """Linear-interpolation resampler (no external deps)."""
    if src == dst or not vals or src <= 0:
        return vals
    n = int(len(vals) * dst / src)
    out = [0] * n
    ratio = src / dst
    last = len(vals) - 1
    for i in range(n):
        p = i * ratio
        a = int(p)
        b = a + 1 if a < last else last
        f = p - a
        out[i] = int(vals[a] + (vals[b] - vals[a]) * f)
    return out


def encode_wav(vals: list[int], rate: int = 16000) -> bytes:
    pcm = b"".join(struct.pack("<h", max(-32768, min(32767, int(v)))) for v in vals)
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
            b"data" + struct.pack("<I", len(pcm)) + pcm)


def _resample_wav(data: bytes) -> bytes:
    """Normalise a WAV to 16 kHz mono 16-bit. Returns the input unchanged when
    it cannot be parsed, so the caller still has something to send."""
    try:
        vals, ch, rate = decode_wav(data)
        if not vals or not rate:
            return data
        if rate != 16000:
            vals = resample(vals, rate, 16000)
        return encode_wav(vals, 16000)
    except Exception:
        return data


def pcm_samples(wav: bytes) -> list[int]:
    """Any WAV -> 16 kHz mono int16 samples (stdlib only)."""
    vals, ch, rate = decode_wav(wav)
    if not vals or not rate:
        return []
    return resample(vals, rate, 16000) if rate != 16000 else vals


# --------------------------------------------------------------------------
# ASR — Meta MMS -> Groq Whisper -> browser
# --------------------------------------------------------------------------
ASR_STATE: dict = {"mms": True, "groq": True, "mms_provider": None}


def asr_chain() -> list[str]:
    """Engines that are configured AND still alive."""
    custom = [p.strip().lower() for p in
              (os.getenv("ASR_ORDER") or "").split(",") if p.strip()]
    out = []
    for p in (custom or ["mms", "groq"]):
        if p == "mms" and not _env("HF_TOKEN"):
            continue
        if p == "groq" and not _env("GROQ_API_KEY"):
            continue
        if p in ("mms", "groq") and not ASR_STATE.get(p, True):
            continue
        out.append(p)
    return out


def asr_mode() -> str:
    chain = asr_chain()
    return chain[0] if chain else "browser"


def asr_available() -> bool:
    return bool(asr_chain())


def _asr_mms(data: bytes, content_type: str) -> str:
    """Meta MMS via the HF router, trying each provider until one serves it."""
    wav = to_wav(data, content_type)
    fname = "audio.wav" if wav[:4] == b"RIFF" else "audio.webm"
    last = ""
    providers = ASR_MMS_PROVIDERS[:]
    if ASR_STATE.get("mms_provider"):
        providers.insert(0, ASR_STATE["mms_provider"])
    for prov in dict.fromkeys(providers):
        url = f"{HF_ROUTER}/{prov}/models/{ASR_MODEL}"
        try:
            r = _post(url, headers=_hf_headers(),
                      files={"file": (fname, wav, content_type or "audio/wav")},
                      timeout=90)
        except Exception as e:
            last = f"{prov}: network error: {e}"
            continue
        if r.status_code in (503, 504):
            import time as _t
            _t.sleep(10)
            try:
                r = _post(url, headers=_hf_headers(),
                          files={"file": (fname, wav, content_type or "audio/wav")},
                          timeout=90)
            except Exception as e:
                last = f"{prov}: network error: {e}"
                continue
        if r.status_code == 402:
            _HF_STATUS["credits"] = False
            ASR_STATE["mms"] = False
            last = f"{prov}: HTTP 402 — HF credits khatam"
            continue
        if r.status_code in (401, 403):
            last = f"{prov}: HTTP {r.status_code} — HF_TOKEN invalid/expired"
            continue
        if r.status_code in (400, 404):
            last = f"{prov}: HTTP {r.status_code} {r.text[:80]}"
            continue
        if r.status_code == 200:
            try:
                out = r.json()
            except Exception:
                last = f"{prov}: bad JSON"
                continue
            if isinstance(out, dict):
                txt = out.get("text")
                if isinstance(txt, list):
                    txt = " ".join(txt)
                if txt:
                    ASR_STATE["mms_provider"] = prov
                    return str(txt).strip()
            last = f"{prov}: unexpected payload"
            continue
        last = f"{prov}: HTTP {r.status_code}: {r.text[:80]}"
    if "402" not in last:
        ASR_STATE["mms"] = ASR_STATE.get("mms_provider") is not None
    raise RuntimeError(f"ASR_FAILED: mms — {last}"[:300])


def _asr_groq(data: bytes, content_type: str) -> str:
    """Whisper on Groq — free tier, always available as a safety net."""
    import httpx

    wav = to_wav(data, content_type)
    fname = "audio.wav" if wav[:4] == b"RIFF" else "audio.webm"
    with httpx.Client(timeout=90) as c:
        r = c.post("https://api.groq.com/openai/v1/audio/transcriptions",
                   headers={"Authorization": f"Bearer {_env('GROQ_API_KEY')}"},
                   data={"model": GROQ_ASR_MODEL},
                   files={"file": (fname, wav, content_type or "audio/wav")})
    if r.status_code >= 400:
        if r.status_code in (401, 403):
            ASR_STATE["groq"] = False
        raise RuntimeError(f"groq ASR HTTP {r.status_code}: {r.text[:120]}")
    txt = (r.json() or {}).get("text") or ""
    if not txt.strip():
        raise RuntimeError("groq ASR returned empty text")
    return txt.strip()


def asr_transcribe(data: bytes, content_type: str = "audio/wav") -> str:
    """Speech -> text. Never fails quietly: raises RuntimeError when every
    server engine is down so the API can answer 503 ASR_UNAVAILABLE and the
    page switches to Web Speech."""
    if not _env("HF_TOKEN") and not _env("GROQ_API_KEY"):
        raise RuntimeError("ASR_FAILED: koi ASR key hi nahi (.env check karein)")
    last = "no ASR engine configured"
    for eng in asr_chain():
        try:
            return (_asr_mms(data, content_type) if eng == "mms"
                    else _asr_groq(data, content_type))
        except Exception as e:
            last = str(e)
            LLM_ERRORS[f"asr:{eng}"] = last[:160]
            print(f"[saavren] ASR '{eng}' fail -> {last[:160]}", flush=True)
            continue
    raise RuntimeError(f"ASR_FAILED: {last}")


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------
#: providers that are out of credits / unauthorised — stop asking every message
DEAD_PROVIDERS: set[str] = set()
#: why each provider failed on the last real call
LLM_ERRORS: dict[str, str] = {}


def _custom_order() -> list[str]:
    return [p.strip().lower() for p in
            (os.getenv("LLM_ORDER") or "").split(",") if p.strip()]


def provider_order() -> list[str]:
    """Meta open-weights first, Groq as the fast safety net. The HF router is
    off by default: since 2026-10-07 free accounts get no Inference Providers
    credits, so every call answers 402. Opt in with ENABLE_HF_LLM=1."""
    forced = (os.getenv("LLM_PROVIDER") or "auto").strip().lower()
    if forced in ("baseten", "groq", "hf", "offline"):
        return [forced]

    usable = {
        "baseten": bool(_env("BASETEN_API_KEY")),
        "groq": bool(_env("GROQ_API_KEY")),
        "hf": bool(_env("HF_TOKEN")) and hf_token_status()[0]
             and hf_credits_ok() and os.getenv("ENABLE_HF_LLM") == "1",
    }
    for dead in DEAD_PROVIDERS:
        usable[dead] = False

    custom = _custom_order()
    order = [p for p in custom if usable.get(p)]
    if not order:
        order = [p for p in ("baseten", "groq", "hf") if usable.get(p)]
    return order + ["offline"]


def _baseten_body(model: str, messages: list) -> dict:
    """Muse Spark is documented at temperature 1.0 / top_p 1.0; reasoning
    defaults to xhigh, far too slow for a bedside conversation."""
    # 700 was enough for a plain LLM. Muse Spark is a reasoning model: with
    # reasoning_effort=medium it can spend the entire budget thinking and
    # return an empty body. The monitor hit this hardest, because its state
    # summary is ten lines against the elder's one — more to reason over, so
    # it ran out first. Raise the ceiling and think less.
    body: dict = {"model": model, "max_tokens": 2000, "messages": messages}
    if "muse" in model.lower():
        body.update({"temperature": 1.0, "top_p": 1.0,
                     "reasoning_effort": "low"})
    else:
        body["temperature"] = 0.4
    return body


_BT_MODEL_CACHE: dict = {"ids": None}


def baseten_models_offered() -> list[str]:
    """Live model slugs from Baseten's /v1/models catalog."""
    key = _env("BASETEN_API_KEY")
    if not key:
        return []
    if _BT_MODEL_CACHE["ids"] is not None:
        return _BT_MODEL_CACHE["ids"]
    try:
        import httpx
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{BASETEN_URL}/models",
                      headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return [f"HTTP {r.status_code}: {r.text[:120]}"]
        ids = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
        _BT_MODEL_CACHE["ids"] = ids
        return ids
    except Exception as e:
        return [f"error: {type(e).__name__}: {e}"[:120]]


def _baseten_pick_model() -> str:
    """Prefer a Meta slug: Llama first, then any `meta-*` model (Muse Spark)."""
    ids = [i for i in baseten_models_offered() if not i.startswith(("HTTP", "error"))]
    if not ids:
        return BASETEN_MODEL
    for i in ids:
        if "llama" in i.lower():
            return i
    for i in ids:
        if i.lower().startswith("meta-") or "/meta-" in i.lower():
            return i
    return ids[0]


def _baseten(payload: dict) -> str:
    """Bearer is the documented scheme; older workspaces answer to `Api-Key`.
    A 404 means the slug left the catalog -> look up the live list and retry."""
    key = _env("BASETEN_API_KEY")
    url = f"{BASETEN_URL}/chat/completions"
    models = [BASETEN_MODEL]
    for model in models:
        body = _baseten_body(model, payload["messages"])
        r = _post(url, headers={"Authorization": f"Bearer {key}"}, json_body=body)
        if r.status_code in (401, 403):
            r2 = _post(url, headers={"Authorization": f"Api-Key {key}"},
                       json_body=body)
            if r2.status_code < 400:
                r = r2
        if r.status_code == 400 and "reasoning_effort" in body:
            body.pop("reasoning_effort", None)
            r = _post(url, headers={"Authorization": f"Bearer {key}"}, json_body=body)
        if r.status_code == 404:
            alt = _baseten_pick_model()
            if alt and alt not in models:
                models.append(alt)
                continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("no Baseten model available")


def _groq(payload: dict) -> str:
    """Groq, walking its current model list — retired ids answer 404."""
    key = _env("GROQ_API_KEY")
    last: Exception | None = None
    for model in GROQ_MODELS:
        body = {"model": model, "temperature": 0.4, "max_tokens": 700,
                "messages": payload["messages"]}
        try:
            r = _post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                      json_body=body)
        except Exception as e:
            last = e
            continue
        if r.status_code == 404:
            last = RuntimeError(f"HTTP 404 — model retired: {model}")
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise last or RuntimeError("no Groq model available")


def groq_models_offered() -> list[str]:
    key = _env("GROQ_API_KEY")
    if not key:
        return []
    try:
        import httpx
        with httpx.Client(timeout=15) as c:
            r = c.get("https://api.groq.com/openai/v1/models",
                      headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return [f"HTTP {r.status_code}: {r.text[:120]}"]
        return [m.get("id") for m in (r.json().get("data") or [])]
    except Exception as e:
        return [f"error: {type(e).__name__}: {e}"[:120]]


def _hf_llm(payload: dict) -> str:
    r = _post(HF_LLM_URL, headers=_hf_headers(),
              json_body={"model": HF_LLM_MODEL, "temperature": 0.4,
                         "max_tokens": 700, "messages": payload["messages"]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _err(provider: str, e: Exception) -> str:
    status = getattr(getattr(e, "response", None), "status_code", None)
    body = ""
    try:
        body = (getattr(e, "response", None).text or "")[:180]
    except Exception:
        body = ""
    msg = f"HTTP {status} — {body.strip()[:160]}" if status else \
        f"{type(e).__name__}: {e}"[:200]
    LLM_ERRORS[provider] = msg
    return msg


def llm(messages: list[dict]) -> tuple[str, str]:
    """(text, provider_used). Falls back to offline, and records every failure."""
    for p in provider_order():
        if p == "offline":
            break
        try:
            if p == "baseten":
                txt = _baseten({"messages": messages})
            elif p == "groq":
                txt = _groq({"messages": messages})
            elif p == "hf":
                txt = _hf_llm({"messages": messages})
            else:
                continue
            if txt and txt.strip():
                return txt, p
            # An empty reply is a FAILURE, not a success. A reasoning model
            # that spends its whole token budget on thinking answers with
            # nothing at all and still reports HTTP 200 — so without this the
            # chain stops here, never tries Groq, and the user just sees the
            # offline fallback with no explanation.
            print(f"[saavren] LLM '{p}' returned EMPTY -> trying next", flush=True)
            continue
        except Exception as e:
            msg = _err(p, e)
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 402, 403):
                DEAD_PROVIDERS.add(p)
            print(f"[saavren] LLM '{p}' fail -> {msg}", flush=True)
            continue
    return "", "offline"


# --------------------------------------------------------------------------
# Text utils
# --------------------------------------------------------------------------
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2190-\u21FF]",
    flags=re.UNICODE,
)


def strip_emoji(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", _EMOJI_RE.sub(" ", text)).strip()


def _balanced_objects(text: str) -> list[str]:
    """Every {...} region in `text` whose braces actually balance, outermost
    first. Walks the string honouring string literals, so a brace inside a
    quoted reply does not end the object early."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, j, instr, esc = 0, i, False, False
        while j < n:
            c = text[j]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
            elif c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j < n and depth == 0:
            out.append(text[i:j + 1])
            i = j + 1
        else:
            i += 1
    return out


def strip_think(text: str) -> str:
    """Reasoning models narrate before they answer. Drop that narration."""
    t = re.sub(r"<think>.*?</think>", " ", text or "", flags=re.S | re.I)
    t = re.sub(r"<reasoning>.*?</reasoning>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<\|.*?\|>", " ", t, flags=re.S)
    return t.strip()


def parse_json_loose(text: str) -> dict | None:
    r"""Best-effort JSON extraction from an LLM reply.

    The old version tried the whole string, then a single greedy `\{.*\}`.
    That breaks the moment a reasoning model adds a sentence of preamble or a
    note after the object — the greedy match swallows the surrounding prose and
    `json.loads` rejects it, so a perfectly good answer was thrown away and the
    user saw the offline mirror. Now: strip the reasoning, then try every
    balanced object, preferring one that actually carries a `reply`.
    """
    if not text:
        return None
    t = strip_think(text).strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*", "", t).strip().rstrip("`").strip()

    candidates = [t] + _balanced_objects(t)
    fallback = None
    for c in candidates:
        if not c:
            continue
        try:
            obj = json.loads(c)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("reply"), str):
            return obj
        fallback = fallback or obj
    return fallback


#: The script each language is written in, so we can tell whether a reply
#: actually came back in the language the app is set to.
_LANG_SCRIPT = {
    "hi": "\u0900-\u097F",   # Devanagari
    "mr": "\u0900-\u097F",   # Devanagari
    "bn": "\u0980-\u09FF",
    "ta": "\u0B80-\u0BFF",
    "te": "\u0C00-\u0C7F",
    "gu": "\u0A80-\u0AFF",
}


def reply_in_lang(text: str, lang: str) -> str:
    """Guarantee the reply is in `lang`, instead of hoping the model agrees.

    Four attempts at phrasing the instruction still produced English replies
    with the app set to Hindi, because a model will happily mirror the language
    it was addressed in. So: check what actually came back, and translate it
    when it is wrong. Asking is not enforcement.

    Only fires when the reply is genuinely in the wrong script, so a correct
    answer costs nothing extra.
    """
    text = (text or "").strip()
    lang = (lang or "en").lower()
    if not text or lang not in _LANG_SCRIPT:
        return text

    rng = _LANG_SCRIPT[lang]
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return text
    right = sum(1 for c in letters if "\u0900" <= c <= "\u097F" or
                "\u0980" <= c <= "\u09FF" or "\u0B80" <= c <= "\u0BFF" or
                "\u0C00" <= c <= "\u0C7F" or "\u0A80" <= c <= "\u0AFF")
    # already in an Indic script -> good enough (Hinglish romanisation is
    # common and legitimate, but a fully Latin reply with the app in Hindi
    # is the failure we are correcting)
    if right / len(letters) >= 0.15:
        return text
    if not _looks_latin(text):
        return text

    out, _prov = llm([
        {"role": "system",
         "content": ("You are a translator. Translate the text into "
                     f"{_lang_name(lang)}. Reply with the translation only — "
                     "no preamble, no quotation marks, no explanation.")},
        {"role": "user", "content": text[:2000]}])
    out = strip_think(out or "").strip().strip('"').strip()
    return out or text


def _looks_latin(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters) > 0.6


def _has_devanagari(s: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", s or ""))


_SCRIPTS = [("\u0900-\u097F", "hi"), ("\u0980-\u09FF", "bn"),
            ("\u0B80-\u0BFF", "ta"), ("\u0C00-\u0C7F", "te"),
            ("\u0A80-\u0AFF", "gu"), ("\u0D00-\u0D7F", "ml"),
            ("\u0C80-\u0CFF", "kn"), ("\u0B00-\u0B7F", "or"),
            ("\u0A00-\u0A7F", "pa"), ("\u0600-\u06FF", "ar"),
            ("\u0400-\u04FF", "ru")]

_HINGLISH = (
    r"\b(mujhe|mujhko|mera|meri|mere|humko|hamko|tumhara|aapka|"
    r"hai|hain|hoon|hu|hun|tha|thi|the|nahi|nahin|nhi|haan|acha|achha|"
    r"kya|kyun|kyu|kaise|kaisa|kaisi|kab|kahan|kaun|kitna|kitni|"
    r"dard|dukh|bukhar|bukhaar|ulti|chakkar|saans|kamzori|thakan|dawai|dawa|"
    r"goli|paani|khana|khane|sona|uthna|tabiyat|bimar|bimaar|theek|thik|"
    r"batao|bataiye|bolo|boliye|karo|karna|kijiye|lijiye|"
    r"bahut|bohot|thoda|zyada|abhi|kal|aaj|subah|shaam|raat|"
    r"main|mein|me|hum|aap|tum|usko|isko|aur|lekin|agar|toh|bhi|jab|phir)\b"
)


def detect_hinglish(text: str) -> bool:
    s = text or ""
    if _has_devanagari(s):
        return False
    return len(re.findall(_HINGLISH, s, flags=re.I)) >= 2


def detect_lang(text: str) -> str:
    """What the user actually WROTE — the dropdown can be wrong."""
    s = text or ""
    best, hits = "", 0
    for rng, code in _SCRIPTS:
        n = len(re.findall(f"[{rng}]", s))
        if n > hits:
            best, hits = code, n
    if hits >= 2:
        return best
    return "hi" if detect_hinglish(s) else ""


def effective_lang(message: str, lang: str) -> str:
    return detect_lang(message) or (lang or "en").lower()


def _lang_name(lang: str) -> str:
    return {"hi": "Hindi (Devanagari)", "en": "English", "bn": "Bengali",
            "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "gu": "Gujarati",
            "es": "Spanish", "fr": "French"}.get(
        (lang or "en").lower(),
        "Hinglish (Latin script) if the user writes that way, else English")


# --------------------------------------------------------------------------
# Triage
# --------------------------------------------------------------------------
RED_FLAGS = [
    (r"chest pain|chest hurt|seene?\s*mein\s*dard|chhaati\s*mein\s*dard|"
     r"seene?\s*(me|mein|mai)\s*.{0,12}(dard|dukh)", "chest-pain"),
    (r"can'?t breathe|saans\s*(nahi|nahin|nhi)|breathless|"
     r"behosh|unconscious|faint(ed)?", "breathless-unconscious"),
    (r"सीने\s*(में|मे)?\s*(दर्द|दुख|जलन)|छाती\s*(में|मे)?\s*(दर्द|दुख)"
     r"|दिल\s*(का|की)?\s*दौरा", "chest-pain"),
    (r"साँस\s*(नहीं|नहि)|सांस\s*(नहीं|नहि)|दम\s*घुट|बेहोश|लकवा",
     "breathless-unconscious"),
]

CATEGORY_HINTS = [
    (r"(sir|head)\s*(mein|me|mai)?\s*(dard|dukh)|headache|migraine"
     r"|सिर\s*(में|मे)?\s*(दर्द|दुख)|सिरदर्द", "headache", 3),
    (r"bukhaar|fever|tap\s*chadha|temperature|बुखार|तापमान|ज्वर", "fever", 4),
    (r"ulti|vomit|chakkar|dizzy|giddy|उल्टी|चक्कर|वमन", "dizzy-vomit", 4),
    (r"pet|stomach|tummy|abdominal|पेट|उदर", "stomach", 4),
    (r"blood pressure|bp\b|sugar|diabet|ब्लड\s*प्रेशर|शुगर|मधुमेह",
     "bp-sugar", 5),
    (r"kamzori|weak|thakan|fatigue|कमजोरी|थकान|थकावट", "weakness", 3),
    (r"neend|sleep|insomnia|नींद|अनिद्रा", "sleep", 3),
    (r"joint|knee|ghutne|pair\s*dard|back pain|kamar"
     r"|जोड़|घुटने|घुटना|कमर|पैर\s*दर्द", "pain-joints", 3),
]


def normalize_triage(d: dict, user_text: str = "") -> dict:
    """Clamp + hard-gate a triage object so it is always safe to show."""
    out = {"severity": 3, "category": "general",
           "summary_en": (user_text or "")[:200],
           "first_question": "यह कब से हो रहा है?",
           "calm_reply": "मैं यहीं हूँ — आराम से साँस लीजिए।",
           "home_care": [], "red_flags": [], "doctor_call": False,
           "source": (d or {}).get("source", "llm")}
    d = d or {}
    try:
        out["severity"] = max(1, min(10, int(d.get("severity", 3))))
    except Exception:
        pass
    for k in ("category", "summary_en", "first_question", "calm_reply"):
        if isinstance(d.get(k), str) and d[k].strip():
            out[k] = d[k].strip()[:400]
    hc = d.get("home_care") or []
    if isinstance(hc, list):
        out["home_care"] = [str(x)[:180] for x in hc if str(x).strip()][:3]
    rf = d.get("red_flags") or []
    if isinstance(rf, list):
        out["red_flags"] = [str(x)[:120] for x in rf if str(x).strip()][:5]

    if out["red_flags"] and out["severity"] < 5:
        out["severity"] = 5
    if out["severity"] >= 7:
        out["doctor_call"] = True
    if isinstance(d.get("doctor_call"), bool) and d["doctor_call"]:
        out["doctor_call"] = True

    # The disclaimer belongs on real health answers only — on a mild complaint
    # it is noise (and TTS used to spell it out aloud).
    if out["severity"] >= 4 or out["red_flags"]:
        if _has_devanagari(out["calm_reply"]):
            dis = DISCLAIMER
        elif detect_hinglish(out["calm_reply"]):
            dis = DISCLAIMER_HI_LATIN
        else:
            dis = DISCLAIMER_EN
        already = ("सावरें" in out["calm_reply"]
                   or "_Main Saavren" in out["calm_reply"]
                   or "_I'm Saavren" in out["calm_reply"])
        if not already:
            out["calm_reply"] = out["calm_reply"].rstrip() + dis
    return out


def offline_triage(message: str, lang: str = "en") -> dict:
    text = (message or "").lower()
    flags, cat, sev = [], "general", 3
    for pat, name in RED_FLAGS:
        if re.search(pat, text):
            flags.append(name)
    for pat, name, s in CATEGORY_HINTS:
        if re.search(pat, text):
            cat, sev = name, max(sev, s)
            break
    if flags:
        sev = max(sev, 8 if ("chest-pain" in flags
                             or "breathless-unconscious" in flags) else 7)
    lang = effective_lang(message, lang)
    hindi = lang in ("hi", "mr", "bn", "ta", "te", "gu")
    roman = hindi and not _has_devanagari(message or "")
    if hindi and not roman:
        calm = ("आपकी बात सुन कर लगता है यह गंभीर हो सकता है। मैं अभी आपके "
                "डॉक्टर और परिवार को सूचित करने की तैयारी में हूँ।"
                if sev >= 7 else "समझ गई। छोटी सी बात लगती है — थोड़ा आराम कीजिए।")
        care = ["आराम से बैठ कर धीरे साँस लीजिए।",
                "पानी छोटे छोटे घूँट में पीजिए।",
                "कोई भी नया लक्षण आए तो मुझे तुरंत बताइए।"]
        q = "यह तकलीफ़ कब शुरू हुई?"
    elif hindi:
        calm = ("Aapki baat sun kar lagta hai ye serious ho sakta hai. Main "
                "abhi aapke doctor aur parivaar ko suchit karne ki taiyaari "
                "mein hoon." if sev >= 7 else
                "Samajh gayi. Chhoti si baat lagti hai — thoda aaram kijiye.")
        care = ["Aaram se baith kar dheere saans lijiye.",
                "Paani chhote chhote ghunt mein pijiye.",
                "Koi bhi naya lakshan aaye toh mujhe turant bataiye."]
        q = "Ye takleef kab shuru hui?"
    else:
        calm = ("This sounds like it could be serious — I'm getting your "
                "doctor and family ready to be informed." if sev >= 7 else
                "Understood — this sounds mild. Let's take it easy.")
        care = ["Sit down and breathe slowly.",
                "Sip water in small amounts.",
                "Tell me right away if anything new appears."]
        q = "When did this start?"
    return normalize_triage({
        "severity": sev, "category": cat, "summary_en": message[:200],
        "first_question": q, "calm_reply": calm, "home_care": care,
        "red_flags": flags, "doctor_call": sev >= 7,
        "source": "offline-fallback"}, message)


def triage(message: str, lang: str = "en") -> dict:
    """Section 1c mini-triage. Never raises."""
    lang = effective_lang(message, lang)
    sys = (
        "You are Saavren, a calm first-aid triage assistant for an elderly "
        "person living alone. Reply with STRICT JSON ONLY, no prose:\n"
        '{"severity":int 1-10,"category":short,"summary_en":short,'
        '"first_question":str,"calm_reply":str,"home_care":["<=3 short steps"],'
        '"red_flags":[str],"doctor_call":bool}\n'
        "Rules: red_flags non-empty => severity>=5. severity>=7 => doctor_call "
        "true. Never diagnose. Reply in the user's language: "
        f"{_lang_name(lang)}. Keep calm_reply under 40 words, warm and simple."
    )
    txt, prov = llm([{"role": "system", "content": sys},
                     {"role": "user", "content": f"User says: {message}"}])
    parsed = parse_json_loose(txt)
    if not parsed:
        return offline_triage(message, lang)
    parsed["source"] = prov
    return normalize_triage(parsed, message)


# --------------------------------------------------------------------------
# Agent — operates the whole app from chat
# --------------------------------------------------------------------------
AGENT_SYS = (
    "You are Saavren, a warm friend-companion AND the operator of this health "
    "app. You act on the app through JSON actions; every action also shows up "
    "in the app's panels (single shared state, latest write wins).\n"
    "Reply STRICT JSON ONLY:\n"
    '{"reply": "<your reply, written in {lang}>", '
    '"actions": [{"type": '
    '"med_add|med_taken|med_delete|note|notify|vital", '
    '"name": str, "time": "HH:MM", "note": str, "text": str, '
    '"bp_sys": num, "bp_dia": num, "sugar": num, "pulse": num, '
    '"spo2": num]}\n'
    "Actions: med_add (need name, optional time/note), med_taken (name), "
    "med_delete (name), note (text -> activity feed), notify (text -> family "
    "monitor), vital (the elder just told you a reading: fill bp_sys, bp_dia, "
    "sugar, pulse and/or spo2 — 'mera BP 130/85 hai' gives bp_sys=130, "
    "bp_dia=85). Never invent a number she did not say.\n"
    "If the user just wants to chat, actions may be []. If they report feeling "
    "unwell, keep the reply short and reassuring — the triage engine answers "
    "separately.\n"
    "LENGTH — match it to the question, this matters:\n"
    "* Greeting or small talk ('hello', 'how are you', 'I'm bored'): one or two "
    "short sentences. No lists, no health advice, no disclaimer. Just be "
    "present.\n"
    "* A real question ('what is diabetes?', 'how do I bring my blood pressure "
    "down?', 'why do I feel dizzy in the morning?'): answer it properly. Explain "
    "plainly, give the practical steps, use short paragraphs so it is easy to "
    "read aloud. Be complete — a real question deserves a real answer.\n"
    "* Reporting feeling unwell: short and calm; the triage engine handles the "
    "detail.\n"
    "Never pad, but never be terse with a real question either. Warm, plain, "
    "and never clinical.\n"
    "LANGUAGE RULE - reply in {lang}. Always. The app is set to {lang}, so "
    "that is what she reads and hears. If she writes in some other language, "
    "still answer in {lang}; do not mirror her. Language: {lang}."
)

#: D5 — the same brain, answering the family from the monitor dashboard.
FAMILY_SYS = (
    "You are Saavren, speaking to a FAMILY MEMBER who watches over an elder "
    "through the monitor dashboard. They ask things like 'how is she today?', "
    "'did she take her medicines?', 'any alerts?'.\n"
    "Answer from the app state you are given. Speak about the elder in the "
    "third person ('she', 'he', or her name) — never as 'you'. Be concrete "
    "and honest: if a medicine is pending, say which one; if nothing happened "
    "today, say so plainly instead of inventing reassurance.\n"
    "You may act on the app through JSON actions:\n"
    '{"reply": "<your reply, written in {lang}>", '
    '"actions": [{"type": "med_add|med_taken|med_delete|note|notify", '
    '"name": str, "time": "HH:MM", "note": str, "text": str}]}\n'
    "Prefer no actions unless the family member asks you to change something.\n"
    "LENGTH — a quick check-in ('any alerts?') gets one or two sentences. A "
    "real question ('how has her week been?', 'should I be worried about her "
    "blood pressure?') gets a proper answer with the reasoning. Never pad, but "
    "give them what they actually asked for.\n"
    "LANGUAGE RULE - reply in {lang}. Always. The monitor is set to {lang}, "
    "so answer in {lang} even when they write in another language.\n"
    "Always polite, warm and clear. Language: {lang}."
)


def offline_agent(message: str, lang: str = "en") -> dict:
    t = (message or "").lower()
    lang = effective_lang(message, lang)
    actions: list[dict] = []
    m = re.search(r"(?:add|jodo|daal|start)\s+(?:medicine|med|dawa|dawai)\s+([\w\s]+)", t)
    if m:
        actions.append({"type": "med_add",
                        "name": m.group(1).strip().title()[:40],
                        "time": "09:00", "note": "chat se judi"})
    m = re.search(r"([\w\s]+?)\s+(?:kha\s*li|le\s*liya|taken|done|ho\s*gaya)", t)
    if m and ("dawa" in t or "med" in t or "tablet" in t or "goli" in t):
        actions.append({"type": "med_taken",
                        "name": m.group(1).strip().title()[:40]})
    hi_deva = ["समझ गई। मैं यहीं हूँ — और बताइए, मैं सुन रही हूँ।",
               "अच्छा। आपकी बात नोट कर ली। कुछ और है जो बताना चाहें?",
               "हाँ, समझ में आया। आज का दिन कैसा जा रहा है आपका?",
               "ठीक है। मैं लिख लेती हूँ। पानी पिया आपने आज?",
               "सुन ली मैंने। और कोई बात? मैं यहीं हूँ आपके साथ।"]
    hi_chat = ["Samajh gayi. Main yahin hoon — aur bataiye, main sun rahi hoon.",
               "Achha. Aapki baat note kar li. Kuch aur hai jo bataana chahein?",
               "Haan, samajh mein aaya. Aaj ka din kaisa ja raha hai aapka?",
               "Theek hai. Main likh leti hoon. Paani piya aapne aaj?",
               "Sun li maine. Aur koi baat? Main yahin hoon aapke saath."]
    en_chat = ["Got it — I'm listening. Tell me more if you like.",
               "Understood. I've noted that. How is your day going?",
               "Alright. Anything else you'd like to add?",
               "I hear you. Have you had water and your medicines today?",
               "Noted. I'm right here whenever you want to talk."]
    idx = sum(ord(c) for c in (message or "")) % 5
    hindi = lang in ("hi", "mr", "bn", "ta", "te", "gu")
    roman = hindi and not _has_devanagari(message or "")
    if hindi and not roman:
        reply = ("ठीक है, मैं याद रखूँगी। आपकी दवाइयों की सूची अपडेट कर दी है।"
                 if actions else hi_deva[idx])
    elif hindi:
        reply = ("Theek hai, main yaad rakhungi. Aapki medicine list update "
                 "kar di hai." if actions else hi_chat[idx])
    else:
        reply = ("Got it — I've updated your medicine list."
                 if actions else en_chat[idx])
    return {"reply": reply, "actions": actions, "source": "offline-fallback"}


def agent(message: str, lang: str = "en", state: str = "",
          role: str = "elder", summary: dict | None = None) -> dict:
    """`_agent_inner`, with the reply language guaranteed.

    The guard has to sit here, wrapping every exit — not inside the success
    path. The offline mirror and the "model answered in prose" path both
    return too, and those are exactly the replies that came back in English,
    so a guard that only ran after a successful JSON parse never fired for
    them.
    """
    out = _agent_inner(message, lang, state, role, summary) or {}
    try:
        out["reply"] = reply_in_lang(out.get("reply") or "", lang)
    except Exception:
        pass                      # never lose an answer over a translation
    return out


def _agent_inner(message: str, lang: str = "en", state: str = "",
                 role: str = "elder", summary: dict | None = None) -> dict:
    """Chat agent with app actions. Never raises.

    `role` is who is talking: the elder herself, or a family member watching
    her from the monitor. Same brain, different chair — the family member is
    answered in the third person ('she took her BP pill at 9') and is NEVER
    offered the elder's own emergency flow.
    """
    lang = effective_lang(message, lang)
    sysprompt = AGENT_SYS.replace("{lang}", _lang_name(lang))
    if role == "family":
        sysprompt = FAMILY_SYS.replace("{lang}", _lang_name(lang))
    txt, prov = llm([
        {"role": "system", "content": sysprompt},
        {"role": "user",
         "content": f"Current app state: {state}\n\nUser says: {message}"}])
    parsed = parse_json_loose(txt)
    if not parsed or not isinstance(parsed.get("reply"), str):
        # A real model spoke, it just ignored our JSON envelope. Throwing that
        # away and showing the offline mirror is strictly worse than showing
        # what it actually said — the answer is right there.
        if prov != "offline" and (txt or "").strip():
            plain = strip_think(txt).strip()
            if plain.startswith("```"):
                plain = re.sub(r"^```[a-zA-Z]*", "", plain)
                plain = plain.strip().rstrip("`").strip()
            if plain:
                return {"reply": plain[:1200], "actions": [],
                        "source": prov}
        # The UI says why, so name the reason honestly. Every fallback used to
        # be reported as "no working LLM key", which sent people to check keys
        # that were working fine — the real cause was usually the reply shape.
        if not any(p != "offline" for p in provider_order()):
            reason = "no API keys configured"
        elif not (txt or "").strip():
            reason = ("model returned an empty reply "
                      "(reasoning budget exhausted)")
        elif parsed is None:
            reason = "model reply was not JSON"
        else:
            reason = ("model JSON had no 'reply' string "
                      f"(keys: {sorted(parsed.keys())})")
        # D5 — with no model reachable the monitor must still answer the
        # questions a family member actually asks, straight from the summary.
        if role == "family" and summary:
            from . import ai_extra
            return {"reply": ai_extra.offline_family(message, lang, summary),
                    "actions": [], "source": "offline-fallback",
                    "fallback_reason": reason}
        out = offline_agent(message, lang)
        out["fallback_reason"] = reason
        return out
    acts = parsed.get("actions") or []
    clean = []
    for a in acts:
        if not isinstance(a, dict):
            continue
        t = str(a.get("type") or "")
        if t in ("med_add", "med_taken", "med_delete", "note", "notify",
                 "vital"):
            item = {"type": t, "name": str(a.get("name") or "")[:60],
                    "time": str(a.get("time") or "09:00")[:5],
                    "note": str(a.get("note") or "")[:200],
                    "text": str(a.get("text") or "")[:300]}
            if t == "vital":
                for k in ("bp_sys", "bp_dia", "sugar", "pulse", "spo2"):
                    try:
                        item[k] = float(a.get(k))
                    except (TypeError, ValueError):
                        pass
            clean.append(item)
    return {"reply": str(parsed["reply"])[:1200], "actions": clean,
            "source": prov}


# --------------------------------------------------------------------------
# D3 — fall / thud detection
# --------------------------------------------------------------------------
#: A fall "thud" is a sudden, loud, LOW-frequency impulse with a fast attack, a
#: short body and a quick decay, followed by quiet.
#:
#: Speech is the hard negative: it is loud and can have a fast attack too, but
#: it is (a) harmonically rich, so most energy sits ABOVE 250 Hz and its
#: zero-crossing rate is high, and (b) SUSTAINED — it keeps going for seconds.
#: Both of those are measured here, which is what keeps a loud "hello" from
#: being read as a fall.
THUD = {
    "peak_min": 0.30,         # 0..1 of full scale
    "low_ratio_min": 0.60,    # energy below ~250 Hz (4-pole) vs total
    "attack_ms_max": 60,      # 10% -> 90% of peak
    "voiced_ms_max": 400,     # TOTAL time above half the peak
    "decay_ratio_max": 0.45,  # energy 0.5-1.0 s after the burst vs in it
    "zcr_max": 500,           # zero crossings / second inside the burst
}

#: Each check votes with a weight; `score` is the sum of the ones that pass.
THUD_WEIGHTS = {"loud": 0.25, "low_freq": 0.20, "fast_attack": 0.13,
                "short_body": 0.17, "quick_decay": 0.15, "low_zcr": 0.10}


def thud_score(data: bytes, content_type: str = "audio/wav",
               sample_rate: int = 16000) -> dict:
    """Score a clip for a fall/thud signature. Pure stdlib.

    Returns {score, verdict, peak, low_ratio, attack_ms, burst_ms,
             decay_ratio, rms, seconds}. `verdict` is one of
    "thud" | "possible" | "quiet".
    """
    try:
        s = pcm_samples(data)
    except Exception as e:
        return {"score": 0.0, "verdict": "quiet", "error": str(e)[:120]}
    if len(s) < sample_rate // 4:
        return {"score": 0.0, "verdict": "quiet", "seconds": len(s) / sample_rate,
                "error": "clip too short"}

    peak = max(max(s), -min(s)) / 32768.0
    rms = math.sqrt(sum((x / 32768.0) ** 2 for x in s) / len(s))

    # 4 cascaded one-pole sections at ~250 Hz -> ~-24 dB/octave, steep enough
    # that speech harmonics above 400 Hz stop counting as "low".
    a = 1 - math.exp(-2 * math.pi * 250 / sample_rate)
    st = [0.0, 0.0, 0.0, 0.0]
    lows = []
    for x in s:
        v = x / 32768.0
        for k in range(4):
            st[k] += a * (v - st[k])
            v = st[k]
        lows.append(v)
    low_rms = math.sqrt(sum(v * v for v in lows) / len(lows))
    low_ratio = (low_rms / rms) if rms > 1e-6 else 0.0

    # --- locate the loudest impulse -------------------------------------
    win = int(sample_rate * 0.02)          # 20 ms sliding peak
    env = []
    for i in range(0, len(s) - win, win):
        seg = s[i:i + win]
        env.append(max(max(seg), -min(seg)) / 32768.0)
    if not env:
        return {"score": 0.0, "verdict": "quiet", "peak": peak}
    pi = max(range(len(env)), key=lambda i: env[i])
    ppeak = env[pi]
    half = ppeak * 0.5
    start = int(pi * win)

    # attack: first frame reaching 10% -> first frame reaching 90%
    def first_at(frac):
        for i in range(len(env)):
            if env[i] >= ppeak * frac:
                return i
        return len(env)
    attack_ms = max(0, (first_at(0.9) - first_at(0.1))) * 20

    # body: TOTAL time above half the peak. A thud is over in ~100 ms; speech
    # keeps crossing that line for seconds even when the envelope dips.
    above = sum(1 for v in env if v >= half)
    voiced_ms = above * 20
    run, burst = 0, 0
    for v in env:
        run = run + 1 if v >= half else 0
        burst = max(burst, run)
    burst_ms = burst * 20

    # zero-crossing rate inside the burst — a 90 Hz thud barely crosses zero,
    # voiced speech with harmonics crosses hundreds of times a second.
    b0, b1 = start, min(len(s), start + max(win, int(sample_rate * 0.25)))
    zc = 0
    for i in range(b0 + 1, b1):
        if (s[i - 1] < 0) != (s[i] < 0):
            zc += 1
    zcr = int(zc / max(1e-6, (b1 - b0) / sample_rate))

    # decay: energy 0.5-1.0 s after the burst vs inside it
    mid = min(len(s), start + int(sample_rate * 0.5))
    end = min(len(s), mid + int(sample_rate * 0.5))
    in_e = sum((x / 32768.0) ** 2 for x in s[start:mid]) or 1e-9
    out_e = sum((x / 32768.0) ** 2 for x in s[mid:end]) or 1e-9
    decay_ratio = min(1.0, out_e / in_e)

    checks = {
        "loud": ppeak >= THUD["peak_min"],
        "low_freq": low_ratio >= THUD["low_ratio_min"],
        "fast_attack": attack_ms <= THUD["attack_ms_max"],
        "short_body": voiced_ms <= THUD["voiced_ms_max"],
        "quick_decay": decay_ratio <= THUD["decay_ratio_max"],
        "low_zcr": zcr <= THUD["zcr_max"],
    }
    score = round(sum(w for k, w in THUD_WEIGHTS.items() if checks[k]), 3)
    verdict = "thud" if score >= 0.72 else "possible" if score >= 0.45 else "quiet"
    return {"score": score, "verdict": verdict, "peak": round(ppeak, 3),
            "rms": round(rms, 4), "low_ratio": round(low_ratio, 3),
            "attack_ms": attack_ms, "voiced_ms": voiced_ms, "burst_ms": burst_ms,
            "zcr": zcr, "decay_ratio": round(decay_ratio, 3),
            "seconds": round(len(s) / sample_rate, 2), "checks": checks}


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------
def ai_status() -> dict:
    return {
        "provider_order": provider_order(),
        "keys": key_preview(),
        "llm_errors": dict(LLM_ERRORS),
        "dead_providers": sorted(DEAD_PROVIDERS),
        "asr": {"mode": asr_mode(), "chain": asr_chain(),
                "hf_token": hf_token_status()[1], "hf_credits": hf_credits_ok(),
                "mms_provider": ASR_STATE.get("mms_provider"),
                "groq_asr_model": GROQ_ASR_MODEL},
        "baseten_model": BASETEN_MODEL, "baseten_base_url": BASETEN_URL,
        "groq_models": GROQ_MODELS, "hf_llm_model": HF_LLM_MODEL,
        "hf_llm_url": HF_LLM_URL,
    }


def _silence_wav(ms: int = 300, rate: int = 16000) -> bytes:
    n = int(rate * ms / 1000)
    data = b"\x00\x00" * n
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
            b"data" + struct.pack("<I", len(data)) + data)


def asr_probe() -> str:
    """Does speech-to-text actually work? Walks the chain with a tiny WAV."""
    if not asr_chain():
        return ("koi server ASR available nahi (na HF_TOKEN, na GROQ_API_KEY) "
                "-> browser ASR")
    wav = _silence_wav()
    for eng in asr_chain():
        try:
            if eng == "mms":
                _asr_mms(wav, "audio/wav")
            else:
                _asr_groq(wav, "audio/wav")
            return f"{eng}: OK — server ASR chal raha hai"
        except Exception as e:
            if "402" in str(e):
                return (f"{eng}: HTTP 402 — HF Inference Providers credits "
                        "khatam. Chain ka agla engine try hoga, warna browser ASR.")
            continue
    detail = "; ".join(f"{k}={v}" for k, v in LLM_ERRORS.items()
                       if k.startswith("asr:")) or "unknown"
    return f"saare server ASR fail -> browser ASR chalega. ({detail[:220]})"
