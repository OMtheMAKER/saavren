"""Saavren launcher — one command, no batch file, no special characters.

    python run.py        (agar 'python' na chale toh:  py run.py)

* creates .venv if missing, installs dependencies once
* creates .env from .env.example if it does not exist
* prints which API keys were found (so you know instantly what will work)
* picks the first free port (8000, then 8001, ...) so a stale old server can
  never keep serving old code
* opens the browser on the right URL

Press Ctrl+C in this window to stop.
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(ROOT, ".venv")
VPY = os.path.join(VENV, "Scripts", "python.exe")
if not os.path.exists(VPY):  # linux/mac layout
    VPY = os.path.join(VENV, "bin", "python")
BACKEND = os.path.join(ROOT, "backend")
REQS = os.path.join(ROOT, "backend", "requirements-dev.txt")
ENV = os.path.join(ROOT, ".env")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")

KEYS = [
    ("HF_TOKEN", "ASR  (Meta MMS voice, optional)"),
    ("BASETEN_API_KEY", "LLM  (Muse Spark Open)"),
    ("GROQ_API_KEY", "LLM fallback + live ASR (Groq whisper)"),
]


def ensure_env() -> None:
    """Make sure a .env exists — without it no API key can ever load."""
    if not os.path.exists(ENV):
        if os.path.exists(ENV_EXAMPLE):
            shutil.copyfile(ENV_EXAMPLE, ENV)
            print("[saavren] .env nahi thi — .env.example se bana di")


def key_report() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV, override=False)
    except Exception:
        pass
    found = []
    missing = []
    for key, label in KEYS:
        val = os.getenv(key, "").strip()
        (found if val else missing).append(f"{label}")
    print("-" * 58)
    print("[saavren] keys mili : " + (", ".join(found) if found else "koi nahi"))
    if missing:
        print("[saavren] keys nahi : " + ", ".join(missing))
    # HF_TOKEN is the one that can be present AND dead -> verify it for real.
    hf = os.getenv("HF_TOKEN", "").strip()
    if hf:
        ok, detail = hf_token_ok(hf)
        if ok:
            print("[saavren] HF_TOKEN  : sahi hai -> awaz server MMS se")
        else:
            print(f"[saavren] HF_TOKEN  : {detail} -> awaz BROWSER ASR se chalegi")
            print("[saavren]            (chat par koi farq nahi; sirf mic browser sunega)")
            print("[saavren]            naya token: huggingface.co > Settings > Access Tokens")
            print("[saavren]            ya .env se HF_TOKEN line hata dein")
    else:
        print("[saavren] HF_TOKEN  : nahi hai -> awaz BROWSER ASR se chalegi")
    print("-" * 58)


def hf_token_ok(token: str) -> tuple:
    """(ok, detail) — one cheap call so a dead token is caught before launch."""
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return (True, "sahi hai") if r.status == 200 else (True, f"HTTP {r.status}")
    except Exception as e:
        code = getattr(e, "code", None)
        if code in (401, 403):
            return False, f"GALAT / expired (HTTP {code})"
        return True, f"verify nahi ho paya ({code or type(e).__name__})"


def free_port(start: int = 8000, tries: int = 8) -> int:
    for p in range(start, start + tries):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return start


def inside_venv() -> bool:
    try:
        return os.path.samefile(os.path.dirname(sys.executable), os.path.dirname(VPY))
    except Exception:
        return False


def main() -> int:
    print("[saavren] folder:", ROOT)
    ensure_env()

    if not os.path.exists(VPY):
        print("[saavren] creating virtual environment ...")
        subprocess.check_call([sys.executable, "-m", "venv", VENV])

    if not inside_venv():
        try:
            subprocess.check_call([VPY, "-c", "import uvicorn, fastapi, httpx, dotenv"])
        except Exception:
            print("[saavren] installing dependencies (first run takes about a minute) ...")
            subprocess.check_call([VPY, "-m", "pip", "install", "-q", "-r", REQS])
        print("[saavren] starting server ...")
        return subprocess.call([VPY, os.path.abspath(__file__)])

    # inside the venv now -> make 'app' importable no matter where we were started
    os.chdir(BACKEND)
    sys.path.insert(0, BACKEND)
    os.environ["PYTHONPATH"] = BACKEND + os.pathsep + os.environ.get("PYTHONPATH", "")

    key_report()

    import uvicorn  # noqa: E402

    port = free_port()
    url = f"http://localhost:{port}"
    print("=" * 58)
    print(f"[saavren] NEW BUILD running on {url}")
    print("[saavren] is window ko band mat karna. Stop = Ctrl+C")
    print("=" * 58)

    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    return uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False) or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[saavren] stopped.")
        sys.exit(0)
