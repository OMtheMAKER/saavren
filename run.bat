@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
)
echo Installing dependencies (first run takes a minute)...
".venv\Scripts\python.exe" -m pip install -q -r backend\requirements-dev.txt
start "" http://localhost:8000
echo.
echo Saavren is running. Keep this window OPEN. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --reload --port 8000
pause
