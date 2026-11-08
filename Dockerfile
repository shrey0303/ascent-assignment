# Stage 1: build the web app (frontend/dist)
FROM node:22.11.0-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm test && npm run build

# Stage 2: the API, which also serves the built web app
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Same layout as the repo: config.ROOT is /app
COPY backend/app backend/app
COPY data data
COPY cache cache
COPY --from=frontend /build/dist frontend/dist

# Run as a normal user; it may write only the label caches and the database (var/)
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p var \
    && chown -R appuser:appuser cache var
USER appuser

WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"
# Hosts such as Render set PORT; locally it defaults to 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
