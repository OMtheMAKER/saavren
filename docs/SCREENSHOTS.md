# Deep test + screenshot shot-list

Two things in here: a sweep of every feature so nothing goes untested, and the
list of screenshots worth taking for the submission.

---

## Part 1 — deep test sweep

Tick as you go. Anything that fails, note whether it **crashes**, **shows
wrong data**, or **looks wrong** — they have different fixes.

### Emergency
- [ ] 🆘 SOS → countdown starts
- [ ] Cancel during the countdown → stops cleanly
- [ ] Let it escalate → alert reaches the monitor
- [ ] Nearest three hospitals appear, sorted by distance
- [ ] Voice SOS — say "main gir gaya"
- [ ] "Test thud detection" → countdown opens, and you can cancel it
- [ ] Emergency Card opens, and 🖨 Print shows a print preview
- [ ] Card carries blood group, conditions, medicines, contacts

### Medicines
- [ ] 💊 opens its own screen (not the health dashboard)
- [ ] Add a medicine → appears **sorted by time**
- [ ] Mark taken → counter moves, and it survives a reload
- [ ] Delete one → list and counter both update
- [ ] The daily routine picks up the new medicine with no second entry

### Health
- [ ] ❤️ Sehat Board — BMI, vitals, weekly points
- [ ] Add a reading (BP / sugar / SpO₂ / pulse / weight / temperature)
- [ ] Numbers land in the right units and the right place
- [ ] Triage: "my head is hurting" → **one or two** follow-ups, not five
- [ ] Triage ends with home care + red flags + the not-a-doctor disclaimer

### Companion
- [ ] Start a check-in by hand → three questions, one at a time
- [ ] Answer by voice → accepted, advances
- [ ] "Not now" → dismisses, comes back later
- [ ] The check-in lands in 🕘 Activity
- [ ] Switch to family → the check-in is visible there too

### Family monitor
- [ ] 👨‍👩‍👧 switch works both directions
- [ ] Dashboard shows today's picture
- [ ] 🔔 Alerts feed populated
- [ ] 🕘 Activity from the monitor side
- [ ] Acknowledge an alert → names who acknowledged it
- [ ] "How is she?" chip → **a real model answer**, not the offline mirror
- [ ] Force a fallback and confirm the reason it prints is now truthful:
      `set LLM_PROVIDER=offline` → says *no API keys configured* or similar,
      not the old blanket "no working LLM key"

### Agent
- [ ] Type `hello` → short greeting. **No emergency card, no home-care list.**
- [ ] Ask "how are you" → still social, still short
- [ ] 🎙️ speak in Hindi → transcribed by MMS, answered in Hindi
- [ ] Ask "did I take my medicine today?" → answers from your **actual** meds
- [ ] 📎 upload a medicine photo → returns a medicine card
- [ ] Ask it to add a medicine → it adds it **and says so**
- [ ] Switch 🌐 mid-chat → reply and voice both follow

### Settings & account
- [ ] All 9 languages render, no missing strings, no crash
- [ ] Theme toggle
- [ ] Voice-out toggle
- [ ] Check-in schedule edits save immediately
- [ ] Sign up, log out, log back in
- [ ] Change password → other sessions are revoked
- [ ] Dates and numbers follow the app language, not the browser's

### Diagnostics
- [ ] `/api/ai-status?probe=1` — `dead_providers` and `llm_errors` both empty
- [ ] `/api/chat/debug?role=family` — `parsed_ok: true`
- [ ] `/api/chat/debug?role=elder` — `parsed_ok: true`

---

## Part 2 — screenshots worth taking

Judges skim images before they read anything. Six strong shots beat twenty
mediocre ones. These six are the ones that carry the submission:

| # | Shot | Why this one |
|---|---|---|
| 1 | **Elder home screen** | The hero. Greeting, four tiles, sidebar. Shows the whole product at a glance. |
| 2 | **A Hindi voice conversation** | The money shot. One image proves MMS ASR + a live Meta model + Hindi output + voice-first design. Nothing else does as much work. |
| 3 | **Medicines screen** | A real screen with a dose counter — shows it's an app, not a chat window. |
| 4 | **Family monitor dashboard** | Proves the two-seat design: the same day seen from the daughter's side. |
| 5 | **SOS with the nearest three hospitals** | The stakes. This is why the product exists. |
| 6 | **Hindi and Tamil side by side** | Proves the multilingual claim instantly, in one glance. |

**Take these if you have time:**

| # | Shot | Why |
|---|---|---|
| 7 | Sehat Board | BMI, vitals, adherence points — the health depth |
| 8 | Prescription scan | The multimodal differentiator; very few entries will have this |
| 9 | Alerts feed with the 9 PM digest | Shows the companion → monitor loop closing |
| 10 | `ai-status` showing the provider chain | Proves graceful degradation is real and inspectable |
| 11 | Emergency Card | Printable one-pager for a paramedic |
| 12 | Triage with home care + red flags | Shows it does more than chat |

### How to take them

- Full browser window, **1280×800 or larger** — a cramped screenshot reads as amateur.
- **Close the seeded-data banner** (sign in first) on shots 1–6, or it looks like placeholder content.
- Use a real elder name. Sign in as the account you created so the greeting reads naturally.
- Keep the browser chrome out of it if you can; the app should fill the frame.
- Do **one feature per shot** — a busy screen communicates nothing.
- Name them in order (`01-home.png`, `02-hindi-voice.png`, …) so assembling the submission is mechanical.

### Do not screenshot

- The `ai-status` page with real key names visible — it echoes which keys are set.
- Anything with your `.env` contents.
- The offline banner if you're claiming live AI in that shot.
