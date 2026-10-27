# ── Stage 1: build the Vite frontend ──────────────────────────────────────────
FROM node:22-alpine AS frontend
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --prefer-offline

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

# ddddocr's OpenCV (the headless build on Linux) needs glib; nothing else does.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend source + pre-scraped data
COPY backend/ ./backend/

# Built frontend from stage 1
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Run as a normal user, not root: the app only reads its files.
RUN useradd --create-home --uid 10001 trudocs
USER trudocs

# Sane defaults — override every one of these in your hosting platform's env settings
ENV PORT=8000
ENV LOG_LEVEL=info
# Comma-separated production origins, e.g. https://yourapp.up.railway.app
ENV CORS_ORIGINS=""
# Cloud Run's proxy adds one X-Forwarded-For entry, the visitor's address, which the per-person
# limit uses. Set 2 behind a Google load balancer, 0 when nothing sits in front.
ENV TRUST_PROXY_HOPS=1

EXPOSE 8000

# exec: uvicorn itself gets Cloud Run's stop signal, so it finishes its requests before stopping.
CMD exec uvicorn backend.main:app \
        --host 0.0.0.0 \
        --port $PORT \
        --log-level $LOG_LEVEL
