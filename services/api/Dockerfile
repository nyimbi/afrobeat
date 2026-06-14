# syntax=docker/dockerfile:1.7
# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv — the workspace-aware package installer used in this monorepo.
COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /usr/local/bin/uv

WORKDIR /build

# System build deps (gcc needed for some C extensions).
RUN apt-get update && apt-get install -y --no-install-recommends \
		gcc \
		libpq-dev \
	&& rm -rf /var/lib/apt/lists/*

# Copy workspace manifests first — maximise layer cache hits.
COPY pyproject.toml uv.lock* ./
COPY libs/core/pyproject.toml libs/core/
COPY libs/audio/pyproject.toml libs/audio/
COPY services/api/pyproject.toml services/api/

# Install only production deps into an isolated prefix; no editable installs.
# --no-dev skips workspace dev-dependencies.
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync \
		--frozen \
		--no-dev \
		--no-editable \
		--package gbedu-api \
		--extra-index-url https://pypi.org/simple/ \
		--prefix /app/venv

# Copy the full source tree (needed for hatchling to locate packages).
COPY libs/ libs/
COPY services/api/ services/api/

# Build and install all workspace libs + the api package into the venv.
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync \
		--frozen \
		--no-dev \
		--no-editable \
		--package gbedu-api \
		--prefix /app/venv

# ── Stage 2: runner ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS runner

# Least-privilege: non-root user gbedu (uid/gid 1000).
RUN groupadd -g 1000 gbedu && useradd -u 1000 -g 1000 -m -s /bin/bash gbedu

WORKDIR /app

# Runtime system libs only (libpq for asyncpg psycopg compat layer).
RUN apt-get update && apt-get install -y --no-install-recommends \
		libpq5 \
		curl \
	&& rm -rf /var/lib/apt/lists/*

# Pull the pre-built venv from builder — no pip, no compiler in the runner.
COPY --from=builder /app/venv /app/venv

# Structured log config consumed by uvicorn's --log-config flag.
COPY --chown=gbedu:gbedu services/api/log-config.json /app/log-config.json

# Application source (only what uvicorn needs at runtime).
COPY --from=builder --chown=gbedu:gbedu /build/services/api/src /app/src

ENV PATH="/app/venv/bin:$PATH" \
	PYTHONPATH="/app/src" \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

USER gbedu

EXPOSE 8000

# Liveness probe: curl the /health endpoint every 30 s.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
	CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "gbedu_api.main:app", \
	"--host", "0.0.0.0", \
	"--port", "8000", \
	"--workers", "4", \
	"--log-config", "/app/log-config.json"]
