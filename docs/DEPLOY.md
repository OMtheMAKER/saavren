# Deploying Saavren

Two deliverables, in this order:

1. **A public URL** — Hugging Face Spaces, free, no credit card.
2. **An Android APK** — built by GitHub Actions, no Android Studio on your machine.

Both need no paid account. The whole app runs in **one container on one port**:
the FastAPI server serves the built React UI from `frontend/dist`, so there is
nothing to wire together and no CORS to fight.

---

## Part 1 — the public URL (Hugging Face Spaces)

### Why Spaces

| | Spaces free tier |
|---|---|
| Cost | Free, no credit card, no trial |
| Hardware | 2 vCPU, 16 GB RAM |
| HTTPS | Yes, automatic — the microphone needs this |
| Sleeps | Yes, after a stretch of inactivity; first visit takes 30–60 s to wake |
| Disk | **Not persistent** — see "What sleep does to your data" below |

A Meta-model hackathon also reads better on Hugging Face than on a generic host.

### Step 1 — create the Space

1. Sign in at <https://huggingface.co> (free account).
2. <https://huggingface.co/new-space>
3. **Space name:** `saavren`
4. **SDK:** **Docker** — pick the blank Docker template
5. **Visibility:** Public (judges must be able to open it)
6. Create Space.

### Step 2 — put the files in

Easiest path, no git: open the Space, go to the **Files** tab, click
**Add file → Upload files**, and drag in **the entire contents of your
`saavren` folder** except these:

```
.venv/            node_modules/
saavren.db        .env
saavren-backup/   design/  docs/  d3-snapshots/
```

Uploading the folder keeps `backend/`, `frontend/`, `Dockerfile` and `README.md`
where they belong. `README.md` already carries the config block Spaces needs
(`sdk: docker`, `app_port: 7860`) — do not delete it.

Then click **Commit changes to main**. The Space builds automatically; watch the
**Logs** tab. First build takes about two minutes.

### Step 3 — add your API keys (this is what makes the AI real)

In the Space: **Settings → Variables and secrets → New secret**. Add each key
by itself:

| Name | Value |
|---|---|
| `BASETEN_API_KEY` | from baseten.co → API Keys |
| `GROQ_API_KEY` | from console.groq.com → API Keys |
| `HF_TOKEN` | optional; only for Meta MMS server-side voice |

Secrets are not visible to anyone visiting your Space. Adding a secret restarts
the Space.

**Without any key the app still works** — it falls back to the offline mirror —
but the replies are canned, and that is the one thing a judge will notice. Add
at least one key.

### Step 4 — open it

```
https://huggingface.co/spaces/<your-username>/saavren
```

Check it once yourself before you submit:

| Check | Expected |
|---|---|
| Page loads | Full UI, no blank screen |
| `https://…/api/health` | JSON, with `"keys"` listing what loaded |
| Language dropdown | Switching to Hindi keeps Hindi after an action |
| Microphone | Chrome/Android asks for permission and transcribes |

### Keeping it awake for the judges

A free Space sleeps when nobody visits. Two things help:

* Open the link yourself a few minutes before you submit, and again just before
  the judging window.
* Point a free monitor at it — UptimeRobot (free, no card) pinging
  `https://…/api/health` every 5 minutes keeps it warm.

### What sleep does to your data

The container's disk is **not** persistent: when the Space restarts, the SQLite
database goes back to its seeded demo state. For a hackathon demo that is
actually fine — the demo seed is deliberately realistic, so a judge always lands
on a populated app.

If you want accounts to survive, `SAAVREN_DEMO_SEED=0` stops the seed, and the
paid persistent-storage add-on (starts at $5/month, needs a card) is the only
way to keep the database across restarts. Do not buy it for the demo.

---

## Part 2 — the Android APK

The APK is a thin native shell that opens the live URL. It is built by GitHub
Actions, so you need nothing installed locally.

### Step 1 — push the repo

Your repo already contains `.github/workflows/android-apk.yml`. Push it:

```
git add . && git commit -m "deploy: spaces + apk" && git push
```

### Step 2 — run the workflow

1. GitHub repo → **Actions** → **Android APK** (left sidebar)
2. **Run workflow** → paste your live URL, e.g.
   `https://huggingface.co/spaces/yourname/saavren`
3. Wait about 8 minutes.

### Step 3 — download

The run finishes with an artifact named **saavren-apk**. Download it, unzip, and
you have `app-debug.apk`. Installing it on a phone needs
**Settings → allow install from unknown sources** for the app you open it with.

The APK is a debug build (unsigned with the debug key). That is correct for a
hackathon submission — a Play Store release build needs a signing keystore.

### If the APK build fails

Open the failing step in the Actions log. The two usual causes:

* **Node install** — rerun it; npm occasionally times out.
* **Gradle / Java** — the workflow pins Java 17, which Capacitor 6 needs. If you
  later bump Capacitor to a version requiring Java 21, edit
  `java-version: '17'` in the workflow.

### The back button

On a phone, the hardware back gesture closes one thing at a time — a panel
first, then the screen underneath it — instead of quitting the app. On the home
screen it deliberately does nothing, so an elder cannot back out of the app by
accident. The same code drives the browser's back button on a PC and the arrow
in the top bar. It lives in `frontend/src/lib/nav.js`.

### Note on microphone in the APK

Android WebView grants the microphone only over HTTPS and only with
`RECORD_AUDIO`. The workflow adds that permission automatically
(`mobile/add_permissions.py`). It still needs the URL to be HTTPS — which is why
the APK points at the Hugging Face Space and not at `http://localhost`.

---

## Running the same container locally

If you have Docker installed:

```
docker build -t saavren .
docker run -p 8000:7860 --env-file .env saavren
```

Then open <http://localhost:8000>.

Without Docker, `python run.py` does the same thing on your own machine.
