# Saavren — WORKING DEFINITIONS (feature blueprint)
Status: FROZEN design v1.5 (`design/ui-rough-v15.html`) · Window: Oct 26 – Nov 4, 2026
Rule: card-free stack only · Meta open-weights models (MMS ASR + Llama on Baseten/Groq + HF Inference)

## 0. Auth (Pages 1–7)
- **Elder sign-up (8 steps)** → `POST /api/auth/signup {role:"elder", ...}`; location cascade (country/state/city dataset API), nearest 3 hospitals via OpenStreetMap Nominatim (free, no card) + haversine sort; invite `code = SVN-XXXX` generated server-side (`POST /api/invite`) or join-link `/join/SVN-XXXX`.
- **Monitor sign-up (5 fields + invite)** links via code OR link (`POST /api/invite/accept`) — code and link resolve to the same token.
- **Passwords:** bcrypt hash; session JWT (7d). **OTP login:** 6-digit, 5-min expiry, **email-first** via free SMTP (Brevo 300/day, no card); SMS optional via pluggable provider later; dev/demo mode surfaces OTP in the response.
- Same guidelines checkbox text on BOTH roles' auth screens (design-locked).

## 1. 🤖 Saavren agent (elder P8/9, monitor P10/11) — ChatGPT-style, voice-first
**Agentic powers (user-dictated):** the agent itself can operate **every icon's feature** on the user's behalf — update profile fields (wt/ht/conditions/DOB…), add or adjust medicine reminders, mark doses taken, read the weekly leaderboard & points, pull latest vitals, open/send the Emergency Card, call a family contact, read/modify alerts, guide through Settings (persona, voice speed, invite code). User speaks → agent acts → confirms aloud. **Everything is also manually controllable** — chat and hands write to the same store; latest write wins, agent always confirms both ways.
- Input modes: text / 🎙️ voice (MMS ASR via HF) / 📎 **attachment (photo or PDF)**.
- **📎 Attachment pipeline:** `POST /api/analyze` (multipart) → **Llama-4-Maverick (multimodal, Baseten)** reads image/PDF → strict JSON:
  - medicine photo ⇒ `{name, use, dose, cautions}` card
  - doctor prescription ⇒ `{meds:[{name,strength,timing,days,note}], precautions[]}` → user taps **“Set reminders”** → agent writes schedule into 💊 Medicines + fires a monitor alert summarizing it. Fallback: HF OCR → Llama text-extract. Every medical answer ends with the not-a-doctor disclaimer.
- Brain: `POST /api/chat` (Maverick; Groq `llama-3.3-70b` fallback, `LLM_PROVIDER`); system prompt = profile + today's schedule + meds + last incidents + **selected persona & tone** + target language.
- **Voice modules (personas):** Dadi 🫂 (warm & slow) · Family Doctor 🧑‍⚕️ (calm & crisp) · Yarana 😄 (cheerful) · Yogi 🧘 (soothing). Persona → TTS rate/pitch + phrasing.
- **Tones:** Caring / Professional / Cheerful / Calm (system-prompt modifier).
- **Languages:** conversation starts in app language (**default English**) and the agent speaks all 9 UI languages; switching 🌐 mid-chat moves replies + speech together.
- Voice-out: native browser `speechSynthesis` (free, no card); Settings toggle `VOICE_ON` + speed slider.
- Monitor chat: same agent, read-only over elder context (check-ins, meds, alerts, vitals).

### 1b. 🌞 Companion layer — proactive check-ins + day journal → monitor digest (user point 2)
- App stays **alive in background** (PWA + service-worker; demo runs while tab/PWA open — push keeps working when closed).
- At soft intervals (wake, noon, evening, bedtime) the agent **calls out by itself in the default language** — TTS prompt: “Namaste Mohan ji, aaj ka din kaisa ja raha hai?” — no tap needed; user just answers by voice.
- Every reply is routed through Llama with a **sentiment/state extractor** → day-journal points: `{time, mood: calm|tired|low|happy|anxious, health_note, topics[]}`.
- Through the day the agent keeps a **running log of how the elder is doing**; at 9:00 PM it composes a **daily summary** (mood trend, meals, meds adherence, walk, incidents) and pushes it to the monitor's 🔔 **Alerts feed** — the icon exists precisely for this.
- All journal rows also land in the 🕓 Activity timeline (point 1's shared event stream).

### 1c. 🩺 “Feeling unwell” mini-triage (user point 4)
- Trigger: user says/type a symptom (“sar dard ho raha hai”, “chakkar aa rahe hain”…).
- Agent → Llama strict-JSON `{questions[≤2], home_care[], red_flags[], severity 1–10}` → answers **conversationally**: asks 1–2 follow-ups, then gives safe home precautions/remedies + what to watch.
- **severity ≥ 7 OR any red_flag** ⇒ offer card: *“Aapko Dr. Sharma se baat karni chahiye. Call karun?”* → buttons **📞 Call doctor** / Later → doctor-call = the final step (call sheet in demo). Disclaimer always closes health advice.
- Every triage run logs to day-journal + (severity≥5) monitor 🔔 alert.

### 1d. 🎭 Friend mode — jokes, songs, small talk (user point 5)
- Boredom triggers (“bore ho raha hoon”, “kuch sunao”) → agent tells clean **elder-friendly jokes/shayari in the current language**, asks riddles, plays nostalgia trivia, remembers preferences in a `prefs` memory table (favorite singer, bhajans vs songs, chai time…).
- “Gana sunao” → plays a royalty-free track / narrates lyrics snippet (demo: shared free audio URL; no paid APIs). Personality defaults: **polite, warm, never clinical** (user point 7) — smiling tone baked into the system prompt and all personas.
- Problem-solving bar (point 6): the agent must reason over app state to actually finish tasks (“D3 dose dobara mat do — aaj li hai already”), not just chat.

## 2. 🩺 Health dashboard (P12)
- Profile fields editable: gender, DOB (age auto-derives), medical conditions (from sign-up), **weight, height, blood group**; **BMI auto** = `kg/(m²)` (client calc + saved via `PUT /api/profile`).
- On save → **Emergency Card auto-regenerates** (single source of truth; no stale card).
- Vitals strip (BP/sugar/HR/SpO₂): `GET /api/health/today`; values come from voice check-ins (parsed by Llama into JSON) or manual entry; in demo they're seeded per-user.
- **Weekly leaderboard**: daily points per elder; `GET /api/health/week` returns `[{pos, day, date, pts}]` + today-live row. Cohort = city + age 65+ (opt-out toggle in Settings).

## 3. 🏆 Points engine (feeds leaderboard)
| Event | Points |
|---|---|
| Morning check-in ("I'm fine") | +8 |
| Medicine on time (per dose) | +10 |
| Walk/activity detected (WiFi-CSI sim / device motion) | +5 |
| Vitals logged (BP/sugar) | +4 |
| Talked with Saavren | +3 |
| Medicine missed | −5 |
Rules: points reward **consistency, not fitness**; weekly reset Monday 00:00 local; rank among ~128 elders in city cohort.

## 4. 🚨 Emergency (SOS) — elder-only trigger
Sequence (D3/D4 code):
1. Trigger sources: SOS tile, voice "madad karo…", fall-*thud* detector (simulated layer, clearly labeled). **The detector listens in the background** (same PWA-resident layer as §1b) — the app's core job; any trigger immediately pings the monitor feed (🔔), then on no-cancel auto-escalates to **voice-call** the monitor chain and dispatch the hospital packet — nearest hospital first (that's why hospitals are stored priority-ordered at sign-up).
2. **5s on-screen alarm countdown** (full-page screen, red) — "Cancel · I'm OK" button + voice-cancel word.
3. Timeout/no-cancel → `POST /api/sos/trigger` → incident row (severity/categ. via triage JSON) → **simultaneous**: family push + SMS/email + in-app ring; **hospital packet** (Emergency Card JSON + location) to hospital #1 by priority order (1..4), retry next hospital on failure.
4. Live status screen via WebSocket `/ws/incident/{id}` (acknowledged/arrived flags). Cancel path: `POST /api/sos/cancel`.

## 5. 🔔 Alerts & messages (monitor)
- `GET /api/alerts` — feed: SOS (push+SMS+call), missed-medicine, abnormal vitals, messages from elder, check-in summaries. `POST /api/alerts/read-all`. Unread badge count on tile.
- Delivery: web-push (free) + email; SMS optional provider. SOS always multi-channel.

## 6. 🕓 Activity timeline
- `GET /api/activity/timeline` — append-only event stream (check-ins, doses, calls, vitals, SOS, walks-simulated). Same stream powers elder + monitor views.

## 7. 💊 Medicines
- Schedule seeded from sign-up medical text (Llama parses "Diabetes, High BP…" → default dose rows, editable).
- Voice reminder at dose time (agent calls elder: "Metformin le lijiye"); elder replies by voice → ASR → mark taken (`POST /api/meds/taken/{doseId}`) or manual ✓ tap.
- Missed after +30 min → monitor alert + **−5 pts**.

## 8. 📞 Family calls
- In-app voice: Phase-1 (demo) opens call sheet/dialer; Phase-2 WebRTC in-app call between linked elder ↔ monitor.

## 9. 🪪 Emergency Card
- Auto-generated from profile + hospitals: `GET /api/ecard`.
- `POST /api/ecard/send` — included in every SOS hospital packet + family notification; single source = profile (edit once, everywhere updates).

## Data model (SQLite for hackathon)
`users(elder/monitor)`, `invites(code)`, `profiles(gender,dob,conditions,wt,ht,bg)`, `contacts`, `hospitals(priority 1..4)`, `meds(schedule,taken_ts)`, `checkins`, `vitals`, `events(activity)`, `incidents(sos)`, `alerts(monitor feed)`, `messages(chats)`, `points(event, day)`, `dayjournal(ts,mood,health_note,topics)` + `prefs(key,value)` (companion memory).

## Day-map (D1–D10)
D2: triage tuning + **agent Q&A + mini-triage (§1c)** + tests · D3: alarm/countdown + thud (sim) · D4: SOS dispatch + E-Card + hospitals · D5: monitor WS dashboard + notifications · D6: **companion layer (§1b: proactive check-ins + day-journal + evening digest)** + meds · D7: Health dashboard + points/leaderboard · D8: WiFi-CSI sim + seeds + deploy (Render free) + **friend-mode polish (§1d)** · D9: demo video + README polish · D10: tests + submit (by Nov 5, 6:30 AM IST).

---

## D3 — fall / thud detection + escalation alarm (2026-10-29)

**Flow:** mic -> thud detector -> "Are you OK?" (20 s) -> I'm OK = *false alarm,
nothing sent* | no answer = family + doctor notified | SOS button = immediate.

**Signal features** (`ai.thud_score`, pure stdlib — no numpy):
| feature | a thud | speech (hard negative) |
|---|---|---|
| `peak` | >= 0.30 | can be just as loud |
| `low_ratio` (4-pole @ 250 Hz) | >= 0.60 | ~0.38 (harmonics sit higher) |
| `attack_ms` | <= 60 ms | can be just as fast |
| `voiced_ms` (TOTAL above half peak) | <= 400 ms | ~1100 ms — keeps going |
| `zcr` (zero crossings/s in burst) | <= 500 | ~1200 — harmonics |
| `decay_ratio` (0.5–1.0 s after vs inside) | <= 0.45 | ~0.97 — never stops |

Weighted vote: loud .25 · low_freq .20 · short_body .17 · quick_decay .15 ·
fast_attack .13 · low_zcr .10. `score >= .72` -> `thud` (alarm),
`.45–.72` -> `possible` (logged only, never escalated), else `quiet`.

**Measured** (synthetic clips, `backend/tests/test_ai.py`):
fall 1.00 thud · clap 1.00 thud · plate 0.80 thud · speech 0.38 quiet ·
laughter 0.48 possible · silence 0.23 quiet · room noise 0.13 quiet.

**Endpoints:** `POST /api/fall` (raise) · `POST /api/fall/analyze` (score a clip,
`auto_alarm=1` raises on `thud`) · `GET /api/alarm` (poll) ·
`POST /api/alarm/cancel` · `POST /api/alarm/help` · `POST /api/sos` ·
`GET /api/falls` (history). Grace period: `FALL_GRACE_SECONDS` (default 20).

**Frontend:** `lib/thud.js` mirrors the server maths in the browser (cascaded
BiquadFilters + ZCR + voiced time), `components/AlertOverlay.jsx` is the
countdown ring + generated alarm tone (no audio asset ships). Background
listening is opt-in from the sidebar; "Test thud detection" on Home runs a
synthetic clip through the real pipeline so the demo needs nobody to fall.

## D4 — escalation record, Emergency Card, nearest hospital (2026-10-29)

After "no answer" the app builds **one record** (`POST /api/sos`, fall
escalation) and opens the emergency screen with it:

* `timeline`  — detected → alarm → escalated → called → closed
* `calls`     — `tel:` links for family / ambulance (112) / doctor; they really
  dial on a phone. `POST /api/emergency/{id}/call` logs the attempt.
* `hospitals` — OpenStreetMap **Overpass** (free, no key), 3 mirrors, sorted by
  emergency-ward + distance, each with a directions link.
* `card`      — Emergency Card: name, age, blood group, conditions, allergies,
  current medicines, contact. `GET /api/ecard` also returns plain text for
  SMS/WhatsApp, and the UI can print it.

Endpoints: `GET /api/emergency` · `GET /api/emergency/{id}` ·
`POST /api/emergency/{id}/call` · `POST /api/emergency/{id}/close` ·
`GET /api/hospitals?refresh=1` · `PUT /api/location` · `GET /api/ecard`.

Perf: hospital lookup is **non-blocking** — 6 s at escalation, offline list
shown instantly, then patched in the background; prefetched at boot. Tests never
touch the network (71 tests, <1 s).

## D5 — family monitor dashboard (2026-10-30)

The second seat of the product: everything the elder's app knows, read by the
person who worries about her. It mirrors the elder's app A-to-Z (profile,
medicines, activity, notifications, alarm, incidents, Emergency Card) with one
deliberate difference, straight from the design — **the elder's SOS button
becomes the family's 🔔 Alerts bell**. Nothing rings on the monitor; it tells.

**Seat switch.** No second login in the dev build: one toggle in the topbar
(`👨‍👩‍👧 Family view` / `🧓 Elder view`) switches seats, persisted in
`localStorage.saavren.role`. Switching lands on that seat's home screen.

**One payload.** `GET /api/monitor` returns the whole picture in a single round
trip, including `summary` — the answer to "how is she today?", computed once by
`ai_extra.daily_summary(state)` and used by both the dashboard and the AI, so
there is exactly one version of "how the day went" in the product.

`daily_summary` is pure (no network, `now` injectable) and returns:
`status` (ok | attention | emergency), `meds_taken/meds_total`, `adherence`,
`pending`, `overdue` (past its wall-clock slot), `checkins`, `events_today`,
`unread`, `incidents_open`, `last_seen_ago`, `highlights[]`, `concerns[]`.

* `emergency`  — an open incident, or the alarm is ringing/escalated
* `attention`  — overdue medicine, no check-in today, unread emergency alert
* `ok`         — everything else

**The bell.** Only when something is actually wrong. It shows what happened,
when, the nearest hospital, and gives `🚑 112` + `📞 call family` + the incident
record + `✓ I've seen it`.

**Acknowledgement closes the loop.** `POST /api/monitor/ack {by}` marks the
alerts read *and* writes `ack_by` / `ack_at` plus an `ack` timeline entry onto
every open incident — so the elder's own Emergency Card shows
"✓ Priya has seen this on the family monitor", and a paramedic reading the
record can see someone is on it. The incident stays open until someone closes
it; `POST /api/emergency/{id}/close` now also stands the alarm down.

**The monitor can ask.** `POST /api/chat {role: "family"}` uses a separate
system prompt (`FAMILY_SYS`): it answers from the day summary, speaks about the
elder in the third person, and — importantly — **never enters the elder's
triage flow**. "mom has fever" from a family member returns an answer, not a
triage card and not an alarm. Voice on the monitor goes through
`POST /api/transcribe` (speech to text only, no triage) for the same reason.
With every LLM provider down, `ai_extra.offline_family` answers the four
questions families actually ask (how is she / medicines / alerts / incidents)
straight from the summary, and admits what it does not track.

Endpoints: `GET /api/monitor` · `POST /api/monitor/ack` ·
`POST /api/chat {role:"family"}` · `POST /api/transcribe`.

**Frontend:** `components/MonitorView.jsx` — watch-over header with live status
pill, bell bar, ask bar with suggestion chips, four stat tiles, and four tabs
(Today / Alerts / Activity / Incidents). Polls every 5 s **only while the
family seat is open**. New CSS: `.monhead .alertbar .stat .tabs .nrow .pbul
.pill` — all token-driven, verified in both themes.

**Tests:** 94 passing (was 73), suite still offline and < 1 s. New coverage:
`daily_summary` status/overdue/silent-day/yesterday, monitor payload shape, ack
semantics, family chat isolation, offline family answers, alarm stand-down.
Also fixed a latent suite bug — the audioop test deletes `app.*` from
`sys.modules` and re-imports, which left the shared `TestClient` driving one
app while later tests asserted against another; it now rebinds `client`, `ai`
and `ai_extra`, guarded by `test_client_and_state_are_the_same_app`.

**Verified in a real browser (headless Chromium, zero console errors):** elder
SOS → monitor bell with 112 + nearest hospital; no SOS button on the family
screen; all four tabs render; a family question gets an answer and fires no
emergency card; acknowledgement appears on the elder's Emergency Card.

## D6 — daily companion: proactive check-ins (2026-10-30)

The elder never has to remember to report; **Saavren asks first**. Twice a day
it opens three plain questions in her own language, speaks them aloud, listens
to the answer, and turns what she said into notes the family can read on the
monitor. A check-in nobody answers is itself a signal.

**The script.** `ai_extra.CHECKIN_SCRIPT` — morning and evening, three
questions each, hand-written in all nine languages (EN HI BN TA TE MR GU ES
FR). `due_checkin(state, now)` returns the check-in that should be on screen
right now, or None. Schedule lives in `STATE["checkin_schedule"]`
(`morning 09:00`, `evening 21:00`, `digest 21:30`, `enabled`) and is editable
via `PUT /api/checkin/schedule`.

**Reading the answer.** `extract_mood(text, lang)` is pure keyword work, so it
still functions with every model offline. It returns
`{mood: good|ok|bad|unknown, score, flags[], negative}`. Three details that
matter more than they sound:

* **Negation is per clause, not per sentence.** Splitting on `,.;!?` and the
  Devanagari danda means "dard nahi hai, sab theek hai" reads as *good* and
  "theek nahi, bukhaar hai" reads as *bad*. A whole-sentence check gets both
  backwards.
* **Matching is on word boundaries.** Substring matching let the word "bad"
  hide inside "badhiya" (Hindi for *very good*) — the exact opposite reading.
* **Topics are not symptoms.** `sleep`, `appetite` and `mobility` are recorded
  but never raised as concerns; only `SYMPTOM_FLAGS` (`pain`, `dizziness`,
  `fever`, `breath`) ring the monitor. Otherwise "I slept well" would alarm
  the family.

A fall mention ("gir gayi") is never neutral — it forces `bad` + `mobility`.

**What it becomes.** `checkin_record()` folds the three answers into one
stored note (`{kind, ts, mood, score, flags, answers, summary}`). A `bad` mood
or any symptom posts an **emergency-kind** notification, which is what raises
the bell on the family monitor — so the check-in feeds the same alert path the
fall detector does.

**The companion clock.** A daemon thread runs `_scheduler_tick()` every 60 s.
It is deliberately pure (no threads, `now` injectable) so the whole clock is
testable. Two jobs:

1. A check-in unanswered past `CHECKIN_GRACE_MIN` (45) is recorded as
   `missed` and rings the monitor: "did not answer the morning check-in —
   worth a call". It is recorded once, so it cannot nag.
2. Past the digest hour it builds `daily_digest()` and pushes it to the
   monitor once per day (`STATE["last_digest"]["date"]` gates it).

**The digest.** `ai_extra.daily_digest(state, now)` reuses `daily_summary`
and adds the check-in story plus a plain-text `text` field, so the same
summary can go to the monitor, an SMS or WhatsApp.

**Frontend.** `components/CheckInOverlay.jsx` — deliberately calmer than the
fall alarm (this is a grandchild asking, not an emergency). It speaks each
question on appearance, takes the answer by voice (server ASR via
`/api/transcribe` when available, otherwise the browser's Web Speech) or by
typing, and closes with what was recorded. Nothing in the overlay can raise an
alarm; only the *answer* does, server-side, once, in her words.

The home screen shows today's check-in card with a **"Start now"** button that
works at any hour (`GET /api/checkin/due?force=1`) — she can report how she
feels whenever she likes, and a demo does not have to wait for nine o'clock.
"Not now" persists per day in `localStorage`, so dismissing does not ambush
her again on the next reload.

The monitor's Today tab gained a check-in block: the day's mood pill, each
check-in with its time, and missed ones called out.

Endpoints: `GET /api/checkin/due[?force=1]` · `POST /api/checkin/answer` ·
`POST /api/checkin/skip` · `GET /api/checkins` · `PUT /api/checkin/schedule` ·
`GET /api/summary/daily` · `POST /api/summary/daily/push`.

**Tests:** 125 passing (was 94), still offline and < 1 s. New coverage: the
script in all nine languages, negation-in-clause, the badhiya/bad trap,
symptoms vs topics, due/skip/missed scheduling, the digest, the scheduler tick
(missed after grace, silent inside grace, digest once a day), and the endpoints.

**Verified in a real browser (headless Chromium, zero console errors):** the
check-in card on the elder's home; the overlay asking question 1 of 3 and
speaking it; three typed answers recorded and confirmed; the check-in
appearing on the monitor with her mood; a worrying answer raising the bell;
and the D5 suite still passing unchanged.

## D7 — Sehat Board (2026-10-30)

The elder's own health page, built to the design's page 12: her body, today's
readings, and her week scored day by day. Three tabs — **Board**, **You**,
**Vitals**.

**Body, editable.** Gender chips, DOB (age recalculates), conditions,
weight / height / blood group, and a BMI box that recalculates **as you type**
before you save. BMI uses the **Asian-Indian cut-offs** (ICMR / WHO
Asia-Pacific: <18.5 underweight, 18.5–22.9 normal, 23–24.9 overweight, ≥25
obese). The Western 25.0 line under-flags risk in Indian adults by a wide
margin, so using it here would have been quietly wrong.

**Vitals.** `POST /api/vitals` logs BP systolic / diastolic, sugar, pulse and
SpO2 — by hand from the board, **or by the agent from plain chat** ("mera BP
130/85 hai" now produces a `vital` action; the number is only ever what she
actually said, never inferred). Each reading is bucketed server-side by
`ai_extra.vital_band()` against clinical ranges, so a number is described the
same way on her screen, on the monitor and in a notification. A reading in
`high` / `very high` / `critical` / `low` band rings the monitor bell.
`GET /api/vitals` returns a windowed series; the UI draws it with a small
inline SVG sparkline (no chart library, works offline in the preview iframe).

**Weekly board.** Points follow the design exactly: check-in answered +8, each
medicine on time +10, walk/activity +5, vitals logged +4, talked with Saavren
+3, medicine missed −5. Activity and chat are **mutually exclusive** (one
event, one score) and both are capped, so chattering cannot farm points.

Two deliberate calls here:

* **It ranks her own seven days against each other, not against strangers.**
  The design's caption spoke of "128 Saavren users aged 65+ in Lucknow" —
  there are no other users in this build, and a fabricated peer leaderboard is
  exactly the kind of number a family might act on. The board says so
  ("ranked against your own days this week").
* **The six days of history this build ships are labelled as sample data.**
  `_seed_demo_history()` (env `SAAVREN_DEMO_SEED`, default on) stamps every row
  `source: "demo-seed"`, never touches today, `weekly_board()` reports
  `seeded: true`, and the UI prints the disclosure in plain words. Real days
  overwrite it as they happen.

Ticks now leave a dated row in `STATE["med_log"]`, because the board scores
medicines **per day** — a boolean flag cannot answer "how many did she take on
Tuesday".

Endpoints: `GET /api/sehat` · `POST /api/vitals` · `GET /api/vitals?days=N` ·
`GET /api/board` (also exposes the scoring rules).

The monitor's Today tab gained a health strip (BMI, latest readings with their
bands, weekly points, streak) so the family sees the same numbers she does.

**Tests:** 148 passing (was 146... 125 before D7), still offline and < 1.5 s.
New coverage: BMI bands and bad input, every vital band including inverted
SpO2, series windowing, the points arithmetic and its caps, chat-vs-walk
double counting, streak, seeded disclosure, empty payload rejection, crisis
readings alerting the family, dated medicine rows, and the agent logging a
reading (plus refusing a non-number).

**Verified in a real browser (headless Chromium, zero console errors):** board
with seven ranked rows and the sample-data disclosure; four vitals tiles with
bands; BMI recalculating live as weight changes; five sparklines and the
five-field logging form; and the monitor mirroring BMI and weekly points. D5
and D6 suites still pass unchanged.

---

## D8 (part 1 of 4) — i18n pass · v0.7.1

The language switch changed the words that had been wired up, but a lot of
text was still hardcoded English. This pass closes that gap and — more
importantly — adds a permanent guard so it cannot silently reopen.

### What changed

* **Dictionary:** 146 → **192 keys × 9 languages = 1728 strings**, 0 missing,
  0 empty. New keys cover the emergency card (blood group, conditions, doctor,
  ambulance, log call, nearest hospitals, timeline, call family, print, and
  the card's own fields), the alarm banner (severity, started, seconds to
  answer, pending), theme and voice toggles, the five vital labels, unsaved
  changes, the tagline, the print `<title>`, and relative time
  (`ago_now/min/h/d`, which go through `tr()`'s `{n}` interpolation).
* **Every screen wired.** `EmergencyView`, `MonitorView`, `Panels`,
  `HealthView` and `App` now call `t()` for text they used to hardcode.
* **`agoText(ts, t)`** is exported from `MonitorView` so relative time is
  translated even where no `t` is in scope, with an English fallback.
* **`VITAL_LABEL_KEY`** moved into `lib/i18n.js`. `HealthView` and
  `MonitorView` each had their own copy of BP / Sugar / Pulse / SpO2 — they now
  share one map, so the two screens can never drift apart on labels.
* **Two backend leaks fixed.** `weekly_board()` was formatting weekdays with
  `strftime("%A")`, i.e. the *server's* locale, and returning the badge as the
  literal string `Consistency Star`. It now emits a locale-independent `dow`
  (`mon`…`sun`) and the key `badge_star`; the UI renders both through `t()`.

### The guard: `backend/tests/test_i18n.py`

Four tests that parse the real source files, so no fixture can drift:

1. the dictionary parses and every key has all nine languages;
2. every `t('key')` in the UI resolves to a real key (prefix dispatch like
   `t('band_' + band)` counts as reaching every `band_*` key);
3. no key is reachable by nothing — with an explicit, shrinking `PLANNED` list
   for keys whose screen is not built yet, and a `FROM_SERVER` list for keys
   the backend sends instead of display text;
4. the dictionary itself is complete and non-empty.

This is not theoretical. Writing these tests caught three real bugs that a
"the dictionary is 100% complete" audit had reported as clean:
`VITAL_LABEL_KEY` was referenced but never defined (a runtime crash the build
did not catch), `HealthView` had a hardcoded `unsaved changes`, and the
`Directions` / `emergency ward` strings sat on lines that already contained a
`t()` call — which is exactly why the first sweep skipped them.

**Tests: 152 passing** (148 → 152), still offline and ~1.2 s.

### Verified in a real browser

Headless Chromium, language switched to **Tamil**, walking home → chat →
health → emergency card: **no untranslated UI text, zero console errors**. A
scanner collected every Latin-script word on each screen; the only two classes
that remain are correct by design — the word "English" (the language dropdown
shows each language's own name, as it should) and the **seeded demo data**
(medicine notes like "nashte ke baad", activity text like "Morning walk in the
park"), which is sample content rather than UI. The default English build was
re-checked afterwards and is unchanged.

**Known limit:** the seeded demo history is still romanised Hindi/English. It
is content a real user would type, so it is not localised — but a per-language
seed is the honest fix if the demo needs to look native in another language.

---

## Accounts — optional sign-in in Settings · v0.7.2

Saavren had no concept of a person: state lives in memory and the two seats
(elder / family monitor) are a local toggle. This adds real accounts without
turning the app into something that needs a login to be useful.

**Decisions (asked and confirmed before building):**

| | |
|---|---|
| Storage | local SQLite (`saavren.db`), not a hosted provider — the stack is card-free and must work offline |
| Gating | **optional** — every endpoint works with no token, so a judge lands straight in the product |
| Roles | accounts carry `elder` or `family`, and signing in puts you in that seat |

### Backend — `backend/app/auth.py`

* **scrypt from the stdlib**, per-user 16-byte salts, `hmac.compare_digest`
  for comparison. Not bcrypt/passlib: no compiler needed on the user's Windows
  box, and (unlike `audioop` and the other PEP 594 removals) it still exists on
  Python 3.14.
* Sessions are `secrets.token_urlsafe(32)`, stored with an expiry (30 days),
  sent as `Authorization: Bearer …`.
* Endpoints: `POST /api/auth/signup`, `POST /api/auth/login`,
  `POST /api/auth/logout`, `GET /api/auth/me`, `GET /api/auth/accounts`.
* **The server returns error codes, never display text** (`auth_bad_login`,
  `auth_username_taken`, `auth_short_password`, `auth_bad_username`,
  `auth_bad_role`, `auth_no_name`). The UI translates them, so a Tamil user
  sees a Tamil error. A wrong password and an unknown user return the *same*
  code, so the endpoint cannot be used to enumerate accounts.

The DB is gitignored — it holds password hashes.

### Frontend

* Settings gained an **Account** section (with a divider): signed out it is a
  sign-in form that toggles to sign-up, signed in it shows your name, username
  and role with a Sign out button.
* The token lives in `localStorage['saavren.token']`; `api.js` attaches it to
  every account call. On startup the app asks the server who the token belongs
  to rather than trusting it — an expired or stale token is dropped.
* Signing in as family switches the app to the monitor dashboard; as elder, to
  the elder home. The monitor's acknowledgement now attributes the
  signed-in person by name.

### One bug this surfaced

The sidebar — and therefore the Settings button — is only rendered for the
elder. A family member who signed in could reach the monitor and then had **no
way to sign out**. The topbar is shared by both seats, so the gear now appears
there for the family view only, which keeps the elder's design (extra icons
live in the sidebar) exactly as specified.

**Tests: 186 passing** (152 → 186; 34 new), ~3 s, still offline. Coverage
includes: salted hashes differing for identical passwords, the plaintext
password never being stored, duplicate usernames, weak and malformed input,
case-insensitive usernames, session expiry, logout killing only that session,
bearer-header parsing, no user enumeration, and an explicit check that
`/api/state`, `/api/health`, `/api/board`, `/api/monitor` and `/api/sehat` all
still answer 200 with **no account at all** — the promise the feature rests on.

**Verified in a real browser** (headless Chromium, zero console errors):
nobody-signed-in → create a family account → role switches to the monitor →
reload keeps the session → Settings shows the name → sign out clears the token
and `me()` returns null → sign back in with the same account → a wrong
password shows the translated message. The whole panel was re-checked in Tamil
and every account string follows the language.

**Scope limit, stated plainly:** accounts identify *people*, they do not
partition *data*. One elder's record is shared with the family who watch over
her, which is the point of the product — so there is one care record, not one
per login. Per-elder partitioning would mean reworking every endpoint.

---

## Settings and Activity finished · v0.7.3

Closing the three gaps left in the original icon/screen spec.

### Settings is now six sections

1. **Language** — 9 languages
2. **Theme** — dark / light
3. **Voice replies** — on / off
4. **Check-in times** — morning, evening, daily summary, plus an on/off
5. **Password** — New + Confirm only
6. **Account** — sign in, sign up, sign out

Check-in times save on edit, not behind a Save button: a schedule you have to
remember to save is a schedule that never sticks. `digest` had no default
time in `CHECKIN_SCHEDULE`, which meant its routine row could never ring, so
it now defaults to 21:30.

**On "New + Confirm only":** that is the design as specified, and it is
implemented that way. It is only defensible because the endpoint requires a
live session and revokes *every other* session afterwards — a leaked token
stops working the moment the password changes. Both behaviours are tested.

### Activity is now three parts

* **Today's routine** — every medicine and check-in, sorted by time, with a
  bell on each row you can turn off. The routine is **derived** from the
  medicines and the check-in schedule rather than stored separately, so
  adding a medicine shows up here with nothing to sync. The built-in rows
  arrive as i18n keys, so they follow the language; medicine names are the
  elder's own data and pass through untouched.
* **This week** — the seven days ranked, reusing the D7 board.
* **The feed** — time-stamped and source-badged, as before.

### Two i18n bugs this surfaced

Walking the new screens in Tamil found leaks the earlier pass had missed:

1. **Source badges were raw values** — the chip printed `a.source` verbatim,
   so a Tamil screen said "system", "agent", "note". Eleven `src_*` keys were
   added, with a fallback that shows the raw value rather than a bare key if
   a source ever appears that has no string yet.
2. **Dates used the browser locale, not the app language** — every
   `toLocaleString([])` rendered in English regardless of the chosen
   language. `lang` is now threaded into `ActivityPanel`, `NotifyPanel`,
   `EmergencyView` and `MonitorView`, so dates and times follow the switch.

**Tests: 201 passing** (186 → 201; 15 new). The new ones pin down the parts
most likely to rot: the routine follows an added medicine with no syncing,
rows are sorted and every row has a time its alarm could actually fire at,
only the toggled row changes, check-in rows disappear when check-ins are
disabled, labels arrive as keys and not English, and the password rules above.

**Verified in a real browser** (headless Chromium, zero console errors):
Settings shows six sections; the password section is locked with "Sign in to
change your password" until you sign in and then shows exactly two fields;
changing the password confirms and the new one logs in; check-in times save
on edit (09:00 → 07:30 persisted); Activity shows the routine, the ranking
and the feed; toggling a bell persists. Re-checked in Tamil — all six section
names, the routine rows and the badges follow the language.

**Still open, and unchanged from the D8 note:** the seeded demo data is
English and romanised Hindi (medicine notes like "nashte ke baad", activity
lines like "Morning walk in the park"). That is sample content rather than UI,
so it is not translated. A per-language seed is the fix if the demo needs to
read natively in another language.

---

## Medicines gets its own screen; the demo elder is labelled · v0.7.4

Two things were wrong, both spotted by using the app rather than reading it.

### 1. Health and Medicines opened the same page

The elder home has four tiles, but the router collapsed two of them:

```js
onGo={(v) => (v === 'meds' || v === 'health') ? setView('health') : setPanel(v)}
```

Both tiles landed on the Sehat Board, and the board does not show medicines
at all — so the Medicines tile led to a screen with no medicines on it.

**Medicines is now its own view** (`MedicinesView.jsx`), deliberately split
from Health:

* **Health** is the Sehat Board — body profile, BMI, vitals, weekly points.
* **Medicines** is the cabinet — today's doses sorted by time, how many of
  how many are taken, a taken/untaken toggle on each row, a delete button,
  and an add form (name, time, note).

Both `add_med` and `delete` had been sitting in the i18n `PLANNED` list as
"specified but not built" since D8. They are now wired, and the test that
guards that list made me take them off it.

### 2. It ran as Shanti Devi with nobody signed in

Shanti Devi is **seeded demo data**, not an account: `STATE` starts with a
demo elder and six days of sample history so the app is not empty on first
open. Nothing about that involved logging in — which is exactly why it was
confusing.

Three changes, so nobody mistakes the demo elder for a real person:

1. **`/api/state` now reports `demo: true`** when the install seeded itself.
2. **A banner says so in as many words** while nobody is signed in:
   *"Sample data — Shanti is a demo profile. Sign in to use your own."*
   It disappears the moment an account exists.
3. **Signing in as the elder takes over the profile** — the seeded name is
   replaced with the account's own name.

Turn the seed off entirely with `SAAVREN_DEMO_SEED=0` for a genuinely empty
install.

### Two further bugs found while testing this

* **Seeded feed rows were not traceable to the seed.** `_seed_demo_history`
  promised in its docstring that *every* row carries `source: "demo-seed"`,
  but the activity rows were tagged `agent` / `note` — so a fabricated
  "Called her sister" looked exactly like something a real person had done.
  They now carry `demo: true` (the badge still reads agent/note, which is
  about the *kind* of entry, not whether it is real).
* **`POST /api/meds` accepted an empty name.** The form blocks it with
  `required`, but the API took it and created a nameless medicine. It now
  returns 400 `med_name_required`.

**Tests: 209 passing** (201 → 209; 8 new). The new ones cover the demo flag
being reported and matching the seed setting, seeded feed rows being
traceable, and the medicine add / mark-taken / delete round trip including
the empty-name rejection.

**Verified in a real browser** (headless Chromium, zero console errors): the
banner names the demo profile; the Medicines tile and the Health tile render
*different* pages; adding a medicine goes 3 → 4, marking one taken sticks,
deleting goes back to 3; signing in as an elder renames the profile to the
account's name and the banner disappears. Re-checked in Tamil — the whole
screen follows the language.

---

## The app opened into a full-screen overlay · v0.7.5

Reported as "screen is blank, it hasn't loaded anything". The server log
showed every request answering 200 — including `/api/state`, `/api/board` and
`/api/monitor`, which only fire from React — so the app had clearly mounted
and was running. It was rendering, just not visible.

### Cause

The D6 check-in is a full-screen overlay:

```css
.checkin { position: fixed; z-index: 110; background: rgba(8,10,13,.72) }
```

and `look()` runs **immediately** on mount. So on every fresh boot the
companion demanded a check-in before anyone had seen a single pixel of the
home screen. What you get is a 72%-opaque scrim over an app you cannot see —
which reads exactly as "nothing loaded".

Worth noting: my own browser scripts never caught this, because they all
*dismissed* the overlay first — Playwright reported it as "intercepts pointer
events" and I worked around it instead of asking why it was there.

### Fix

The companion no longer interrupts the first moments:

* **45-second grace period** after boot before it may open itself.
* **Never while a chat is open** (`view === 'chat'`) — no talking over a
  conversation.
* Still never during an alarm or an emergency, as before.
* `ckDue` is still set during the grace period, so the home card shows the
  check-in is waiting and the elder can start it by hand.

Starting it by hand (the "Start now" button) still opens it instantly — the
grace period only governs the companion asking unprompted.

### A blank screen should never be silent again

`main.jsx` now wraps `<App />` in an error boundary. Any exception thrown
while rendering used to unmount the whole tree and leave an empty page,
indistinguishable from "the app never loaded". It now shows the error, says
the app is running and the page failed to draw, and offers a Reload button.
This does not change behaviour when nothing is wrong.

**Tests: 209 passing**, unchanged — this was a timing and layering bug, not
one a unit test would have caught.

**Verified in a real browser:** on load, zero `.checkin` overlays and the home
screen is visible (greeting, demo banner, sidebar, four tiles). Tapping
"Start now" still opens the check-in with its three questions. Console clean.

---

## `ReferenceError: lang is not defined` on the monitor · v0.7.6

The error boundary added in v0.7.5 earned its place immediately: it turned
"screen is blank" into the actual exception.

```
ReferenceError: lang is not defined
    at MonitorView ...
```

### Cause

v0.7.3 threaded `lang` into the date formatters so dates would follow the
language switch. `MonitorView` got the value in the JSX — `dayTime(e.ts, lang)`
and `clock(c.ts, lang)` — but **never got it in its props**:

```js
export default function MonitorView({
  t, data, onAsk, onOpenIncident, onAck, onCall, live,   // no lang
}) {
```

Vite does not care. esbuild bundles it happily, because `lang` resolves at
runtime, and at runtime it is undefined — but only on the code paths that
actually reach those two calls. The monitor crashed; the elder home did not.

### Why it reached him

`saavren.role` was persisted as `family` in his browser, so the app opened
straight into the monitor. Every verification script I had written starts with
`localStorage.clear()`, so all of them landed on the elder home and none of
them ever rendered the broken path. That is the whole story: the bug was only
reachable from state my tests kept deleting.

### Fix

`lang` is now in `MonitorView`'s props.

### The guard: lint runs as part of the build

An undeclared variable is invisible to a bundler and fatal at runtime, so it
needs a different tool. `frontend/eslint.config.js` turns on `no-undef`, and:

```json
"build": "eslint src && vite build"
```

means `npm run build` now **fails** on an undefined variable instead of
shipping it. Confirmed by reverting the fix:

```
MonitorView.jsx
  122:44  error  'lang' is not defined   no-undef
  268:60  error  'lang' is not defined   no-undef
```

This is the same class of mistake as the `VITAL_LABEL_KEY` crash on D8 —
referenced but never declared, invisible to the build. That one was caught by
a hand-written scanner; this one is now caught by the toolchain on every
build, whatever the code.

### Also fixed

`no-misleading-character-class` in the emoji-stripping regex: `\uFE0F` is a
variation selector, and inside a character class it does not match the way it
reads. It is now its own alternation branch, which is what was intended for
TTS cleaning.

**Tests: 209 passing.** Verified across a matrix of persisted states — family
role, light theme, Hindi, a stale token, fall-watch on, a dismissed check-in —
plus a walk through every view. The monitor renders, nothing crashes.
