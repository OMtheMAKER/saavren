"""D8 — i18n coverage guards.

The dictionary can be 100% complete while the UI still shows English, and a
`t('key')` call is only correct if that key actually exists. These tests are
the permanent guard against both failure modes — they parse the real source
files, so no fixture can drift out of sync.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
I18N = ROOT / 'frontend' / 'src' / 'lib' / 'i18n.js'
SRC = ROOT / 'frontend' / 'src'

LANGS = ['hi', 'en', 'bn', 'ta', 'te', 'mr', 'gu', 'es', 'fr']

KEY_LINE = re.compile(r'^  ([a-z][a-z0-9_]*):\s*\{(.*)\}\s*,?\s*$')
# a JS string literal, single or double quoted (French uses " ... " when the
# value holds an apostrophe, e.g. fr:"Aujourd'hui")
QSTR = r'''(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')'''
LANG_VAL = re.compile(r'(\w{2}):(' + QSTR + r')')
# t('key') / t("key") / t(`key`) / tr(lang, 'key', ...)
T_CALL = re.compile(r"\bt\(\s*['\"`]([a-z][a-z0-9_]*)['\"`]")
TR_CALL = re.compile(r"\btr\(\s*[\w.]+\s*,\s*['\"`]([a-z][a-z0-9_]*)['\"`]")
# any lowercase snake_case string literal, used for the reachability check
LITERAL = re.compile(r"'([a-z][a-z0-9_]*)'")


def _unquote(raw):
    """Turn a JS literal into its value: 'a' -> a, "J'ai" -> J'ai."""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1].replace("\\'", "'").replace('\\"', '"')
    return raw


def _dictionary():
    """Parse i18n.js -> {key: {lang: value}}. No JS toolchain needed."""
    out = {}
    for line in I18N.read_text(encoding='utf-8').splitlines():
        m = KEY_LINE.match(line)
        if not m:
            continue
        key, body = m.group(1), m.group(2)
        out[key] = {lang: _unquote(val)
                    for lang, val in LANG_VAL.findall(body)}
    return out


D = _dictionary()


def test_dictionary_parses():
    assert len(D) > 100, f'only {len(D)} keys parsed — regex is broken'
    assert 'hi' in D[next(iter(D))], 'language codes not parsed'


def test_every_language_present_and_non_empty():
    bad = [f'{key}.{lang}' for key, row in D.items() for lang in LANGS
           if not (row.get(lang) or '').strip()]
    assert not bad, f'missing/empty strings: {bad}'


def test_no_key_call_is_undefined():
    """Every t('x') in the UI must resolve to a real dictionary key.

    A prefix counts as reachable: t('mood_' + x) is how the mood and band
    tables are dispatched at runtime.
    """
    calls = {}
    for path in list(SRC.rglob('*.jsx')) + list(SRC.rglob('*.js')):
        if path.name == 'i18n.js':
            continue
        text = path.read_text(encoding='utf-8')
        for m in list(T_CALL.finditer(text)) + list(TR_CALL.finditer(text)):
            calls.setdefault(m.group(1), []).append(path.name)

    def reachable(key):
        return key in D or any(k.startswith(key) for k in D)

    missing = {k: sorted(set(v)) for k, v in calls.items() if not reachable(k)}
    assert not missing, f't() calls with no dictionary entry: {missing}'


PREFIX_CALL = re.compile(r"\bt\(\s*['\"`]([a-z][a-z0-9_]*_)\s*['\"`]\s*\+")

# Keys kept for UI that is specified but not built yet. Each entry names the
# screen it belongs to, so this shrinks as the app grows — it is not a place
# to park mistakes.
# Keys the backend sends as i18n keys instead of display text, so the UI can
# render them in the elder's language. They are built by string, not literal,
# so the scanner cannot see them — they must be listed here deliberately.
FROM_SERVER = {
    'badge_star': 'weekly_board() badge when the weekly target is met',
    'routine_checkin_morning': '_routine() row label',
    'routine_checkin_evening': '_routine() row label',
    'routine_digest': '_routine() row label',
}

PLANNED = {
    'highlights': 'monitor daily-summary heading',
    'profile': 'health profile card heading',
    'readings_logged': 'toast after logging vitals',
    'saved': 'profile saved confirmation',
    'checkin_retry': 'check-in retry after a failed recording',
}


def test_every_key_is_reachable():
    """Catch typos the other way round: a key no code can ever look up.

    Three ways a key is reached:
      * a literal call, t('key')
      * prefix dispatch, t('band_' + band) — every band_* key counts
      * a lookup table, e.g. VITAL_LABEL_KEY maps bp_sys -> 'v_bp'
    """
    used, prefixes = set(), set()
    for path in SRC.rglob('*.js*'):
        if path.name == 'i18n.js':
            continue
        text = path.read_text(encoding='utf-8')
        used |= set(T_CALL.findall(text)) | set(TR_CALL.findall(text))
        used |= set(LITERAL.findall(text))
        prefixes |= set(PREFIX_CALL.findall(text))

    # maps exported from i18n.js itself (e.g. VITAL_LABEL_KEY -> 'v_bp')
    src = I18N.read_text(encoding='utf-8')
    tail = src[src.index('VITAL_LABEL_KEY'):] if 'VITAL_LABEL_KEY' in src else ''
    used |= set(LITERAL.findall(tail))

    for pre in prefixes:
        used |= {k for k in D if k.startswith(pre)}

    dead = sorted(set(D) - used - set(PLANNED) - set(FROM_SERVER))
    assert not dead, f'dictionary keys no code can reach: {dead}'
    # fail if PLANNED lists a key that is now reachable, so the list shrinks
    stale = sorted(set(PLANNED) & used)
    assert not stale, f'PLANNED keys are now wired up, drop them: {stale}'


def test_seeded_demo_text_follows_the_language_switch():
    """The demo elder's data was Hinglish, so switching the UI to Tamil moved
    the interface and left the content behind — which reads as broken language
    switching. Seeded conditions and medicine notes must translate too."""
    from app import main as m
    for lang, cond, note in (
        ("hi", "ब्लड प्रेशर", "नाश्ते"),
        ("ta", "இரத்த அழுத்தம்", "உணவு"),
        ("te", "రక్తపోటు", "అల్పాహారం"),
        ("es", "Presión arterial", "desayuno"),
        ("fr", "Tension artérielle", "déjeuner"),
    ):
        st = m.public_state(lang)
        assert cond in st["profile"]["conditions"], f"{lang}: conditions"
        assert any(note in (med.get("note") or "") for med in st["meds"]), \
            f"{lang}: medicine note"


def test_unknown_language_falls_back_to_english_seed():
    from app import main as m
    st = m.public_state("xx")
    assert st["profile"]["conditions"] == ["Blood pressure", "Diabetes"]


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_language_header_reaches_every_state_reply():
    client = _client()
    """Every endpoint that returns `state` must answer in the language the
    request arrived with. They used to default to English, so switching the UI
    to Hindi and then doing anything at all snapped the whole screen back."""
    for lang, marker in (("hi", "नाश्ते"), ("ta", "உணவு"), ("es", "desayuno")):
        r = client.get("/api/state", headers={"X-Saavren-Lang": lang})
        assert r.status_code == 200
        assert any(marker in (m.get("note") or "") for m in r.json()["meds"]), \
            f"{lang}: state came back in the wrong language"


def test_state_survives_an_action_without_reverting():
    client = _client()
    """The exact snap-back: switch language, act, and the reply must not drag
    the UI back to English."""
    r = client.post("/api/meds/taken", json={"name": "Amlodipine 5mg"},
                    headers={"X-Saavren-Lang": "hi"})
    assert r.status_code == 200
    assert "नाश्ते" in (r.json()["state"]["meds"][0]["note"] or "")
