# Launch — the public vote

The bonus pool (~$50k) is a **public vote / most-viral** award, announced around
10 Nov. Judging runs 4–8 Nov; the ceremony is Mon 9 Nov.

So: submit first, launch second. Everything below is for ~10 Nov onward, once
there is something to vote *for*.

The one rule that governs all of it: **post the scene, not the feature list.**
Everyone else will post a feature list.

---

## LinkedIn — Hinglish, one scene, ≤200 words

Post this as text, not as an image. Put the video in the first comment and the
live URL in the post body.

```
09:40. शांति जी (72) ने आज सुबह की जाँच का जवाब नहीं दिया।

किसी ने कुछ टैप नहीं किया। फ़ोन ने खुद बोलना शुरू किया —
"शांति जी, सुबह हो गई।"

हम बुज़ुर्गों के लिए ऐप बनाते हैं, और सब टाइप मांगते हैं। मेरी
नानी ने एक health app खोली, तीन मेन्यू देखे, और बंद कर दिया।
उन्हें मदद नहीं चाहिए थी — उन्हें बात चाहिए थी।

तो मैंने उल्टा बनाया। Saavren खुद शुरू करता है, हिंदी में पूछता है,
और जवाब भी आवाज़ में देता है। पढ़ना नहीं पड़ता।

जाँच का जवाब नहीं आया, तो परिवार के monitor पर एक लाइन जाती है:
"No answer to the morning check-in. Worth a call."

गिरने जैसी आवाज़ आई — 250 Hz से नीचे की थड, 60 ms में — तो पूछता है
"क्या आप ठीक हैं?", 20 सेकंड का countdown। और वो खुद cancel कर
सकती हैं।

Emergency dispatch simulated है: server से बाहर कुछ नहीं जाता। यह
मैं छिपा नहीं रहा — ऐसा ऐप अगर 1% भी झूठ बोले, बेकार है।

Live: saavren.onrender.com
90-second demo: [link]
```

---

## X / Twitter — 5 tweets, thread

**1 — the scene. Nothing else.**

```
09:40. शांति जी (72) ने आज सुबह की जाँच का जवाब नहीं दिया।

किसी ने कुछ टैप नहीं किया। फ़ोन ने खुद बोला:
"शांति जी, सुबह हो गई।"

यह Saavren है 👇
```

**2 — the problem**

```
Apps for old people assume typing.

My nani opened a health app, saw three menus, and closed it. She didn't need
help. She needed someone to talk to.

So I built it backwards: the app speaks first.
```

**3 — what it does**

```
It listens in Hindi. Asks one follow-up. Reads the answer aloud — home care
first, red flags second.

She never typed a word. She never read a menu.

(It is not a doctor. It says so on every health answer.)
```

**4 — the two moments that matter**

```
Check-in goes unanswered → the family monitor gets one line:
"No answer to the morning check-in. Worth a call."

A sub-250 Hz thud hits the mic inside 60 ms → "क्या आप ठीक हैं?", 20s
countdown, and SHE can cancel it.

The cancel is the feature.
```

**5 — the honest limits, and the links**

```
Honest limits: emergency dispatch is simulated, nothing leaves the server.
Acoustic fall detection is a safety net, not a medical device — it does not
replace a wearable or a caregiver.

It's not an AI doctor. It's someone who notices.

Live: saavren.onrender.com
Code: github.com/OMtheMAKER/saavren
```

---

## WhatsApp / community — 3 lines

For Indian dev groups *and* elder-care groups. Same message, both places.

```
Saavren — अकेले रहने वाले बुज़ुर्गों के लिए एक voice-first साथी।
हिंदी में बोलता है, कुछ टाइप नहीं करना पड़ता।

सुबह की जाँच का जवाब नहीं आया तो परिवार को सूचना; गिरने जैसी आवाज़ पर
"क्या आप ठीक हैं?" — और वो खुद cancel कर सकती हैं।

Live demo (free, no card): saavren.onrender.com · 90s video: [link] ·
Code: github.com/OMtheMAKER/saavren
```

---

## Posting order and timing

All times IST. Day = the day the public vote opens (~10 Nov).

| When | What | Why |
|---|---|---|
| **09:00–10:30** | LinkedIn | Morning commute; best Indian professional reach. |
| **+30 min** | X thread (all 5 at once) | Same-day as LinkedIn, so it reads as one push, not two stragglers. |
| **19:00–21:00** | WhatsApp + community groups | Family group chats are live in the evening; reply rate is highest. |

**Do not** lead with WhatsApp. The vote page should already be warm and have
some social proof on it before community traffic lands.

If the vote opens on a weekend, move LinkedIn to 10:00–11:00 and keep the rest.

---

## What NOT to say

Every one of these is either false or will get the project reported.

- **No medical claims.** Not "detects falls" — *"listens for the sound of a fall."*
- **Never "AI doctor".** Not in the copy, not in a hashtag, not in a reply.
- **Never imply it replaces a wearable** (a fall pendant, an Apple Watch) **or a
  caregiver.** It does not. Say so before someone else says it for you.
- **Never say it calls an ambulance, a doctor, or anyone.** Dispatch is
  simulated. Nothing leaves the server.
- **Not "monitors your parents 24/7."** It listens in one room, while the mic is
  on, when the app is open.
- **No number you didn't measure.** Don't write "229 tests" or "9 languages"
  unless it's true on the day you post.
- **Don't promise features from `docs/WORKING.md`.** That file is a blueprint;
  OTP login, invite codes and family pairing are not built.
