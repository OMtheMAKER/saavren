# Demo video script — 3 minutes  (SUPERSEDED)

> **Use `docs/VIDEO-90S.md` instead.** This script produced the 164-second
> video now on YouTube and is kept for reference only. It contains one line
> that is no longer true — "Meta MMS for speech". MMS has never run on the
> live deployment; see "Honest limits" in the README.

Two rules I've built this around, because you asked for both: **no laptop
intro** (we open on the product, not on a person), and **the narration always
describes what is on screen at that second** — never a voiceover talking about
something the viewer cannot see yet.

The single login is at 1:45. It is the only one in the video, and it is framed
as a deliberate beat that also demonstrates accounts.

Narration in English; the app is driven in Hindi. That contrast is the point —
an international judge can follow the explanation while seeing the thing that
actually matters, an elder using her own language.

---

## 0:00 – 0:12 · The hook

| On screen | Narration |
|---|---|
| Saavren home screen, morning. The greeting and the four tiles. No banner yet. | "Shanti is seventy-two, and she lives alone. Her daughter is in another city. This is her morning." |

## 0:12 – 0:28 · Voice first

| On screen | Narration |
|---|---|
| Tap the mic. Speak in Hindi: *"Saavren, aaj main thik nahi hoon."* The transcript appears, then the Hindi reply, then it speaks aloud. | "She doesn't type — she talks. Meta's MMS turns her Hindi into text, and Muse Spark, Meta's open-weight model, answers her in Hindi and says it out loud." |

## 0:28 – 0:42 · It asks first

| On screen | Narration |
|---|---|
| The check-in opening by itself. Three questions, one at a time. Answer the first one by voice. | "And she never has to start the conversation. Saavren asks first — morning, evening — and it just listens." *(SUPERSEDED: the shipped build runs two slots, morning 09:00 and evening 21:00. The recorded 164-second video says "four times a day"; `CHECKIN_KINDS` is `("morning", "evening")`. See Honest limits in README.)* |

## 0:42 – 1:02 · Medicines and triage

| On screen | Narration |
|---|---|
| 💊 Medicines: dose counter, time-sorted rows. Mark one taken. Then in chat, *"sir dard ho raha hai"* → two follow-ups → home care, red flags, disclaimer. | "Every answer becomes a journal entry. Her medicines live here, with a dose counter. And when she says she's unwell, it asks two questions and gives safe home care — plus the red flags to watch, and it always says it isn't a doctor." |

## 1:02 – 1:22 · The prescription

| On screen | Narration |
|---|---|
| 📎 attach a photograph of a prescription. The medicine card comes back. Tap Set reminders. It lands in Medicines. | "That's her prescription. She photographs it and the model reads the medicines straight off the strip — it's multimodal, so there's no separate OCR service. One tap and the reminders are set." |

## 1:22 – 1:45 · Emergency

| On screen | Narration |
|---|---|
| 🆘 SOS → countdown → let it escalate → three nearest hospitals → 🖨 Emergency Card, show the print preview. | "If she falls — or simply stops answering — Saavren escalates. The three nearest hospitals, sorted by distance, and a one-page card with her blood group and medicines that a paramedic can read. Print it and hand it over." |

## 1:45 – 2:05 · The one login

| On screen | Narration |
|---|---|
| Sign in. The sample-data banner disappears; the greeting changes to the account's own name. Do this once, then never again. | "So far that was sample data, and the app says so on screen. I'll sign in now — this is the only time you'll see me do it. Accounts are local SQLite: no cloud, no card, and the app works completely without one." |

## 2:05 – 2:30 · The daughter's seat

| On screen | Narration |
|---|---|
| Switch to 👨‍👩‍👧 Family view. Dashboard. 🔔 Alerts with the 9 PM digest. Tap a suggested question — *"How is she?"* — and get a real model answer. | "Same day, from her daughter's side. The check-ins, the doses, the alerts — and the nine PM digest Saavren writes itself. She can just ask, and it answers about her mother, not to her." |

## 2:30 – 2:45 · Nine languages

| On screen | Narration |
|---|---|
| Switch 🌐 Hindi → Tamil → Bengali. Each time the UI, the reply and the spoken voice all move together. | "Nine languages. The interface, the answers and the spoken voice move together — Tamil, Bengali, Marathi, and six more." |

## 2:45 – 3:00 · Honest failure, then close

| On screen | Narration |
|---|---|
| `ai-status?probe=1` showing the live provider chain. Then force `LLM_PROVIDER=offline` and show it still answers, labelled as offline. | "And it fails honestly. Take the keys away and it keeps working — every offline answer is labelled as offline, so nobody mistakes it for the model. Meta MMS for speech, Muse Spark Open for reasoning, Groq behind it. Built in nine days, for the person who needs it most." |

---

## Production notes

**Length.** Three minutes. If you run long, cut the prescription segment
before you cut anything else — it is the most impressive and the least
essential.

**Recording.** Windows: Xbox Game Bar (`Win + G`) is enough and needs no
install. OBS if you want a proper microphone track. Record at 1920×1080.

**Microphone.** Narrate on a separate take and lay it under, rather than
talking live over the clicking. Live narration always drifts out of sync with
the screen and breaks the one rule that matters here.

**Pace.** Let each Hindi reply finish speaking before you move on. Silence
while the app talks reads as confidence; cutting it off reads as a rush.

**Before you press record:**
- sign in once so the sample-data banner is gone from every shot
- clear the day's test data, or the timeline will show your rehearsal, not Shanti's morning
- close every other window
- turn off notifications
- check the mic permission is already granted

**The three things a judge looks for, all in the first 30 seconds:** that a
real person could use it (0:12, she speaks), that the AI is doing real work
(0:12, live model replying in Hindi), and that it is finished, not mocked
(0:42, real screens with real data). If the opening lands, the rest is
confirmation.
