# ── MirrorX ────────────────────────────────────────────────────────────────
# Multi-arch friendly: amd64 / arm64 (Railway, Fly, Koyeb, Oracle, Pi, VPS…)
FROM python:3.12-slim

# ffmpeg  → lets yt-dlp merge 1080p+ video+audio
# ca-certificates/tzdata → HTTPS + correct timestamps
# NOTE: no aria2 — the bot does not use it (yt-dlp brings its own downloader)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Kolkata

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent data lives here:
#   Railway  → attach a Volume with mount path /app/data  (see railway.toml)
#   Compose  → ./downloads:/app/downloads  and  ./data:/app/data
#   docker   → -v mirrorx-data:/app/data
# We deliberately do NOT declare `VOLUME` in this file: Railway's builder
# rejects any Dockerfile VOLUME ("dockerfile invalid: docker VOLUME … is not
# supported, use Railway Volumes") and fails the build.
RUN mkdir -p /app/downloads /app/data \
 && useradd -m -u 1000 mirrorx \
 && chown -R mirrorx:mirrorx /app

# Container starts as root ON PURPOSE: Railway mounts volumes owned by root,
# so a non-root process could not write the SQLite DB. The bootstrap below fixes
# ownership of the mounted folders, then drops to uid 1000 for the bot itself.
# (Set RUN_AS_ROOT=0 if you always mount UID-1000-owned volumes, e.g. Compose.)
#
# WHY THE SCRIPT IS GENERATED HERE INSTEAD OF `COPY`d
# ---------------------------------------------------
# A separate docker-entrypoint.sh meant the build needed one extra file in the
# repository, and when that file did not reach GitHub every build died with:
#     failed to calculate checksum of ref …: "/docker-entrypoint.sh": not found
# Generating it from an inline base64 blob keeps the Dockerfile 100% self-
# contained: the only inputs are files that are already in the repo.
RUN echo 'IyEvYmluL3NoCiMgTWlycm9yWCBjb250YWluZXIgYm9vdHN0cmFwIChnZW5lcmF0ZWQgaW5zaWRlIHRoZSBpbWFnZSDigJQgc2VlIERvY2tlcmZpbGUpCnNldCAtZQpEQVRBPSIke0RBVEFfRElSOi0vYXBwL2RhdGF9IgpETD0iJHtET1dOTE9BRF9ESVI6LS9hcHAvZG93bmxvYWRzfSIKbWtkaXIgLXAgIiREQVRBIiAiJERMIiAyPi9kZXYvbnVsbCB8fCB0cnVlCmlmIFsgIiQoaWQgLXUpIiA9ICIwIiBdICYmIFsgIiR7UlVOX0FTX1JPT1Q6LTF9IiAhPSAiMCIgXSAmJiBpZCBtaXJyb3J4ID4vZGV2L251bGwgMj4mMTsgdGhlbgogIGNob3duIC1SIG1pcnJvcng6bWlycm9yeCAiJERBVEEiICIkREwiIDI+L2Rldi9udWxsIHx8IHRydWUKICBmb3IgZCBpbiAiJERBVEEiICIkREwiOyBkbwogICAgaWYgdG91Y2ggIiRkLy53dGVzdCIgMj4vZGV2L251bGw7IHRoZW4gcm0gLWYgIiRkLy53dGVzdCI7CiAgICBlbHNlIGVjaG8gIltlbnRyeXBvaW50XSBXQVJOSU5HOiAkZCBub3Qgd3JpdGFibGUg4oCUIGNoZWNrIHRoZSB2b2x1bWUgbW91bnQiID4mMjsgZmkKICBkb25lCiAgZXhlYyBzdSBtaXJyb3J4IC1zIC9iaW4vc2ggLWMgJ2V4ZWMgIiQwIiAiJEAiJyAtLSAiJEAiCmZpCmV4ZWMgIiRAIgo=' | base64 -d > /usr/local/bin/mirrorx-entrypoint.sh \
 && chmod +x /usr/local/bin/mirrorx-entrypoint.sh \
 && sh -n /usr/local/bin/mirrorx-entrypoint.sh \
 && head -1 /usr/local/bin/mirrorx-entrypoint.sh | grep -q '^#!/bin/sh'

ENV RUN_AS_ROOT=1 \
    DOWNLOAD_DIR=/app/downloads \
    DATABASE_PATH=/app/data/mirrorx.db

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s \
  CMD python run.py --check > /dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/mirrorx-entrypoint.sh"]
CMD ["python", "run.py"]
