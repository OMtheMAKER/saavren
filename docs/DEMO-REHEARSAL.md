# Demo rehearsal — run this before you record

Everything in this repo has been verified on my machine, and my machine has
**no API keys at all** — it runs the offline mirror and browser ASR. Yours has
`HF_TOKEN`, Baseten and Groq. That means the entire live-AI path — real model
text, MMS transcription, prescription scanning — has **never been executed**.

That is the point of this document. Do not record the video until every box
below is ticked. Budget an hour.

---

## 0. Confirm the stack is actually live (2 min)

```powershell
taskkill /F /IM python.exe ; cd "C:\Users\Om Pratap Singh\OneDrive\Desktop\saavren\saavren-d2" ; python run.py
```

Read the banner it prints. On your machine it must say:

```
[saavren] HF_TOKEN: ok
[saavren] ASR  : mms  (chain: ['mms', 'groq'])
[saavren] LLM  : ['baseten', 'groq', 'offline']
```

- [ ] HF_TOKEN `ok`, not `not set`
- [ ] ASR is `mms`, not `browser`
- [ ] LLM starts with `baseten`, not `['offline']`

If any of those fail, **stop here** — the rest of the rehearsal is meaningless.
The keys are in `.env` next to `run.py`; `run.py` creates that file from
`.env.example` if it is missing, so check you filled in the real one.

Now hit the diagnostic that actually calls each provider and reports back:

```
http://localhost:8000/api/ai-status?probe=1
```

- [ ] `dead_providers` is empty
- [ ] `llm_errors` is empty
- [ ] `asr.mode` is `mms`, and `asr.mms_provider` names one (fal / replicate / nebius)

Write down what this page says. If the demo goes wrong later, this is the first
thing you will want to compare against.

---

## 1. Create the accounts now — not on camera (10 min)

There are **no accounts in the database** (`GET /api/auth/accounts` returns
`{"count":0}`). Elder sign-up is eight steps. If you discover that while
recording, you have just spent four minutes of a five-minute video filling in
forms.

- [ ] Sign up the elder now (8 steps). Write the username and password down.
- [ ] Sign up the family monitor now, and link the two with the invite code.
- [ ] Log out.

Now the video can show **one** login, which is what you asked for.

---

## 2. The live-AI smoke test — the part nobody has run (20 min)

Do these in the browser, in English first, then again in Hindi. You are not
checking whether the app works; you are checking whether **a real model's
output** lands correctly on screen.

| # | Do this | It passes when |
|---|---|---|
| 1 | Type `hello` | A short warm greeting. **No emergency card, no home-care list, no medical disclaimer.** A greeting is not a medical event. |
| 2 | Type `how are you` | Same. Short and social. |
| 3 | Speak in Hindi: *"aaj mera sir dard kar raha hai"* | MMS transcribes it; the agent asks **one or two** follow-ups, not five. |
| 4 | Answer the follow-up | Gives home care + red flags, then the not-a-doctor disclaimer. |
| 5 | Say *"mujhe bore ho raha hai, kuch sunao"* | Friend mode — a joke or shayari, in Hindi. |
| 6 | Upload a photo of a medicine strip (📎) | Returns a medicine card. If it returns garbage, the multimodal path needs work. |
| 7 | Switch 🌐 to Tamil mid-chat, then ask something | The reply **and** the spoken voice come back in Tamil. |
| 8 | Ask *"aaj ki dawai hui?"* | It answers from your actual medicines — it should reason over app state, not make something up. |

- [ ] All eight ticked

**Watch for these specifically**, because they are the failure modes a live
model introduces and the offline mirror cannot:

- an answer that reads like the *end* of a longer answer (model got cut off)
- literal markdown (`**bold**`, `#`, `|`) visible in the chat bubble
- the agent claiming it did something it did not (confirming an action it never took)
- English answers while the UI is in Hindi

If the chat misbehaves, force the offline path and compare —
`LLM_PROVIDER=offline python run.py`. If offline is clean and live is not, it
is a parsing problem in `backend/app/ai.py`, not a model problem, and I can fix
it from the answer text you send me.

---

## 3. The walkthrough in order (20 min)

Run this top to bottom **without restarting**, exactly as you will record it.
Time it.

| # | Step | Expected | ✓ |
|---|---|---|---|
| 1 | Cold open, fresh browser | **The home screen is visible.** Greeting, four tiles, sidebar. No overlay. | ☐ |
| 2 | Point out the seeded-data banner | Reads "Sample data — Shanti is a demo profile. Sign in to use your own." | ☐ |
| 3 | 💊 Medicines | Its own screen: dose counter, time-sorted rows | ☐ |
| 4 | Add a medicine | Appears in the list, sorted by time | ☐ |
| 5 | Mark it taken | Counter moves, and it sticks after a reload | ☐ |
| 6 | ❤️ Health | Sehat Board — BMI, vitals, weekly points. **Different screen from Medicines.** | ☐ |
| 7 | 🎙️ Speak a question | Transcribed and answered **aloud** | ☐ |
| 8 | Start a check-in by hand | Three questions, one at a time | ☐ |
| 9 | Answer by voice | Accepted, moves to the next question | ☐ |
| 10 | 🆘 SOS | Escalation chain starts, three nearest hospitals | ☐ |
| 11 | Emergency Card | Opens and prints | ☐ |
| 12 | 🕘 Activity | The check-in you just did appears in the timeline | ☐ |
| 13 | Switch to 👨‍👩‍👧 Family view | Monitor shows the elder's day | ☐ |
| 14 | 🔔 Alerts | The check-in and any alerts are there | ☐ |
| 15 | Switch back to 🧓 Elder view | | ☐ |
| 16 | **Log in once** | Name in the greeting becomes the account's own, banner disappears | ☐ |
| 17 | Test thud detection | Countdown appears, and you can cancel it | ☐ |
| 18 | Switch 🌐 through a few languages | Whole UI changes, nothing breaks, no crash | ☐ |

- [ ] Every step ticked, in one continuous run

---

## 4. Traps that have already bitten

**The home screen must be visible the instant the app opens.** It was not,
two versions ago — a full-screen check-in overlay covered everything and it
looked exactly like "nothing loaded". It is fixed; step 1 above is there purely
to confirm the fix on your machine.

**The family monitor used to crash on load.** `MonitorView` used a variable
that was never declared, and it only crashed on the monitor — which is why my
tests missed it, because they all cleared storage first and landed on the elder
home. Step 13 is there to confirm it on your machine.

**Browser microphone permission.** The first voice action triggers a prompt.
Grant it *before* recording, or the prompt lands in the middle of take one.

**Windows TTS voices.** Voice output uses the OS `speechSynthesis`. If Hindi is
not installed as a Windows voice, Hindi replies will be spoken by an English
voice or not at all. Check this in step 7 — it is not a code problem and I
cannot check it from here.

**Old server, old code.** `run.py` picks the first free port, so a stale server
on 8000 will keep serving an old bundle. The `taskkill` at the start of the
command is not optional.

---

## 5. If something breaks

| Symptom | Do this |
|---|---|
| Blank or broken screen | The error boundary now shows the exception instead of a white page. Send me that text. |
| App runs but AI is wrong | `http://localhost:8000/api/ai-status?probe=1`, then send me that JSON plus the bad answer |
| Need to prove the offline path on camera | `set LLM_PROVIDER=offline` then `python run.py` — demonstrates graceful degradation |
| Demo data got messy | Stop the server, delete `saavren.db` **in the project root** (not `backend/`), restart — it reseeds |
| Want a genuinely empty install | `set SAAVREN_DEMO_SEED=0` then `python run.py` |

---

## When you are done

Tell me what failed and what the timings were. Anything that broke in section 2
is code I can fix from the answer text alone; anything that broke in section 4
is environmental and we work around it in the script.
