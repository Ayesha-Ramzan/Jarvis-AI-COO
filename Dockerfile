# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: builder - compiles all wheels so the runner needs no toolchain
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip wheel --wheel-dir=/wheels --requirement requirements.txt


# ---------------------------------------------------------------------------
# Stage 2: runner - minimal runtime image, non-root, health-checked
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production

WORKDIR /app

RUN groupadd --system jarvis \
    && useradd --system --gid jarvis --home-dir /app jarvis

COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
        --requirement requirements.txt \
    && rm -rf /wheels

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN chown -R jarvis:jarvis /app
USER jarvis

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

# Migrations run before the server starts so the image is self-initializing.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
