# Saavren — one container, one port. Serves the API and the built UI together.
#
#   docker build -t saavren .
#   docker run -p 8000:7860 --env-file .env saavren
#
# The frontend is NOT rebuilt here: frontend/dist is committed, so the image
# needs no Node at all and builds in under a minute.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    SAAVREN_DB=/app/saavren.db \
    SAAVREN_DEMO_SEED=1

# ffmpeg keeps webm/ogg/mp4 voice uploads convertible. The app runs without it,
# it just loses that one conversion path.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY frontend/dist ./frontend/dist

# Hugging Face Spaces expects a non-root user (UID 1000) and a writable /app
# for the SQLite database.
RUN useradd -m -u 1000 saavren \
 && mkdir -p /app \
 && chown -R saavren:saavren /app
USER saavren

EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips='*'"]
