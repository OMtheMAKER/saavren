# The 90-second demo

One continuous take. Three beats. No feature tour.

The video currently on YouTube is 164 seconds and shows nine screens. Nobody
remembers nine screens. This script shows one person, one morning, and one
thing going wrong — and it is built around what the code actually does, so
nothing in it has to be faked in the edit.

**Shoot rules**

- Phone in a fixed stand. Do not move it, do not zoom.
- No cuts, no speed-ramp, no music. Real pauses are the point.
- Film the live app (`https://saavren.onrender.com`), not a mockup.
- If a beat breaks, reshoot the beat. Do not patch it in editing.
- The seeded profile is **Shanti Devi, 72** — use it, so the name matches.

---

## BEAT 1 — 0:00–0:25 · Absence

**Shot.** Phone on a table, elder view. Nobody is touching it. On-screen clock reads 09:40.

**Spoken (the app, unprompted — this is the morning check-in prompt):**

> शांति जी, सुबह हो गई। आज आपकी जाँच और दवाई का समय हो गया है।

Subtitle: *"Good morning, Shanti ji. It's time for your check-in."*

**UI state.** Home view, Hindi. The check-in card is live and speaking. No tap
has happened — the app initiated this, the companion clock did.

**The one caption.**

> कोई टैप नहीं किया — ऐप ने खुद शुरू किया
> *Nobody tapped. The app started this.*

**Failure mode to rehearse.** The prompt fires but nothing is spoken, because
the phone has no Hindi TTS voice. The beat is then dead and you will not notice
until playback. Set the UI to Hindi and test speech **before** you record.

---

## BEAT 2 — 0:25–0:55 · Voice triage, hands off

**Shot.** Same framing. She leans toward the phone. Nothing is typed, ever.

**Spoken (her):**

> मुझे चक्कर आ रहे हैं।

**Spoken (app — one follow-up, then it answers):**

> कब से? और उठते समय, या बैठे-बैठे?

**Spoken (her):**

> सुबह से। उठते समय।

**UI state.** Composer — microphone only, no keyboard in frame. Then the reply:
home care first, red flags second, both **read aloud**. Then the offer button
`डॉक्टर से पूछें?`. Under the reply, always: `AI सहायक — डॉक्टर नहीं।`

**The one caption.**

> उसने एक शब्द नहीं टाइप किया। एक मेन्यू नहीं पढ़ा।
> *She never typed a word. She never read a menu.*

**Failure mode to rehearse.** The agent answers in English because the request
lost its `lang`. That kills the entire point of the beat. Run it once in Hindi
end-to-end before recording; if it replies in English, fix the language and
reshoot — do not dub over it.

---

## BEAT 3 — 0:55–1:20 · The fall, and the cancel

**Shot.** Same framing. Drop a heavy hardcover book on a hard floor beside the
phone. Off-screen is fine — we only need the sound.

**Spoken (app, after the thud):**

> क्या आप ठीक हैं? गिरने जैसी आवाज़ आई है। 20 सेकंड में जवाब न मिले तो परिवार को बता दूँगी।

**UI state.** Full-screen alert `क्या आप ठीक हैं?`, countdown
`जवाब के लिए 20 सेकंड`, one big button `मैं ठीक हूँ`.

**Spoken (her, before the countdown ends):**

> हाँ, ठीक हूँ।

**UI state.** Alarm cancels. The app says:

> अच्छा — आप ठीक हैं। किसी को कुछ नहीं भेजा गया।

**The one caption.**

> आवाज़ से पहचाना — 250 Hz से नीचे की थड, 60 ms में
> *Detected by sound — a sub-250 Hz thud, inside 60 ms.*

**Failure mode to rehearse.** Two, and both are fatal:

1. **The thud doesn't register.** No alert, beat collapses. Rehearse the drop
   three or four times first. A soft bag on carpet will not trigger it — hard
   cover, hard floor, close to the mic.
2. **You let the 20 seconds run out.** Do not. This beat exists to show the
   **cancelled** path. A fall detector that only ever escalates is a different
   and less honest product. If the countdown expires, reshoot.

---

## CLOSE — 1:20–1:30

One card. No voiceover. Hold it for ten seconds.

```
        Saavren — you are not alone.

   Fall detection is a safety net, not a medical device.

            saavren.onrender.com
```

---

## YouTube title

`Saavren — she never typed a word (voice-first elder care, in Hindi)`

## Description

```
A 90-second demo of Saavren: a voice-first companion for elderly people who
live alone, built in Hindi and eight other languages.

0:00  Nobody tapped. The app started talking.
0:25  "मुझे चक्कर आ रहे हैं" — triage by voice, hands off
0:55  A fall, and the alarm she cancels herself
1:20  Saavren — you are not alone

Live demo: https://saavren.onrender.com
Code: https://github.com/OMtheMAKER/saavren

Honest limits: emergency dispatch is simulated — nothing leaves the server, no
call is placed and no SMS is sent. Fall detection is acoustic, tuned for the
thud of a fall; it is a safety net, not a medical device, and it does not
replace a wearable. The medical guidance is explicitly not a doctor's advice.
The demo store is shared between sessions and resets when the server restarts.
Built for the Meta Global AI Developer Hackathon 2026.
```

## Tags

`saavren` · `elderly care` · `voice AI` · `Hindi AI` · `Meta AI Developer Hackathon`
