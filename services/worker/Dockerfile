# syntax=docker/dockerfile:1.7
# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /usr/local/bin/uv

WORKDIR /build

# Build deps: gcc for C extensions, libsndfile-dev for audio libs.
RUN apt-get update && apt-get install -y --no-install-recommends \
		gcc \
		libsndfile1-dev \
		ffmpeg \
	&& rm -rf /var/lib/apt/lists/*

# Workspace manifests — cached layer before source copy.
COPY pyproject.toml uv.lock* ./
COPY libs/core/pyproject.toml libs/core/
COPY libs/audio/pyproject.toml libs/audio/
COPY services/worker/pyproject.toml services/worker/

RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync \
		--frozen \
		--no-dev \
		--no-editable \
		--package gbedu-worker \
		--extra-index-url https://pypi.org/simple/ \
		--prefix /app/venv

COPY libs/ libs/
COPY services/worker/ services/worker/

RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync \
		--frozen \
		--no-dev \
		--no-editable \
		--package gbedu-worker \
		--extra-index-url https://pypi.org/simple/ \
		--prefix /app/venv

# ── Stage 2: runner ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS runner

RUN groupadd -g 1000 gbedu && useradd -u 1000 -g 1000 -m -s /bin/bash gbedu

WORKDIR /app

# Runtime deps: ffmpeg and libsndfile1 for audio processing in tasks.
RUN apt-get update && apt-get install -y --no-install-recommends \
		ffmpeg \
		libsndfile1 \
		curl \
	&& rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/venv /app/venv
COPY --from=builder --chown=gbedu:gbedu /build/services/worker/src /app/src

ENV PATH="/app/venv/bin:$PATH" \
	PYTHONPATH="/app/src" \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	# Celery worker sends metrics on :9090/metrics via prometheus_client.
	WORKER_METRICS_PORT=9090

USER gbedu

# Expose Celery Prometheus metrics port.
EXPOSE 9090

# No HTTP server here — health is inferred from Celery's own inspect ping;
# docker-compose worker has no healthcheck (use flower or celery inspect).

CMD ["celery", \
	"-A", "gbedu_worker.celery_app", \
	"worker", \
	"--loglevel=info", \
	"--concurrency=4", \
	"-Q", "high,default,low"]
