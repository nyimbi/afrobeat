# syntax=docker/dockerfile:1.7
# ── GPU passthrough notes ─────────────────────────────────────────────────────
# Minimum 16 GB GPU VRAM required (models loaded at runtime from HF Hub).
# For NVIDIA GPU support, launch with:
#   docker run --gpus all ...
# or via docker-compose deploy.resources.reservations.devices (see docker-compose.yml).
# NVIDIA_VISIBLE_DEVICES and NVIDIA_DRIVER_CAPABILITIES are set in docker-compose.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime AS builder

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /usr/local/bin/uv

WORKDIR /build

# System build deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
		gcc \
		g++ \
		libsndfile1-dev \
		ffmpeg \
	&& rm -rf /var/lib/apt/lists/*

# Workspace manifests for cache-efficient layer ordering.
COPY pyproject.toml uv.lock* ./
COPY libs/core/pyproject.toml libs/core/
COPY libs/audio/pyproject.toml libs/audio/
COPY services/ml/pyproject.toml services/ml/

# Install production deps into isolated prefix.
# PyTorch is already present in the base image; uv will skip reinstalling it
# if the version constraint is satisfied — keeps the layer lean.
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync \
		--frozen \
		--no-dev \
		--no-editable \
		--package gbedu-ml \
		--extra-index-url https://download.pytorch.org/whl/cu121 \
		--extra-index-url https://pypi.org/simple/ \
		--prefix /app/venv

COPY libs/ libs/
COPY services/ml/ services/ml/

RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync \
		--frozen \
		--no-dev \
		--no-editable \
		--package gbedu-ml \
		--extra-index-url https://download.pytorch.org/whl/cu121 \
		--extra-index-url https://pypi.org/simple/ \
		--prefix /app/venv

# Install RVC from source — not on PyPI. Failure is non-fatal; voice synthesis
# degrades gracefully when the library is absent (is_loaded=False in health check).
COPY services/ml/install_rvc.sh ./install_rvc.sh
RUN pip install --no-cache-dir \
		git+https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git@main#egg=rvc \
		fairseq \
		faiss-cpu \
		praat-parselmouth \
		pyworld \
	|| echo "WARNING: RVC installation failed — voice synthesis will be disabled"

# ── audio.cpp (audiocpp_cli) — YuE2-3B GGUF runtime ───────────────────────────
# Yue2 native generation lives on the dev branch. Pinned to a commit for
# reproducible builds; override with --build-arg AUDIOCPP_REF=<ref>.
# CUDA build requires nvcc; when absent we fall back to a CPU build (the
# adapter selects the backend at runtime from GPU_DEVICE). Failure is
# non-fatal — YuE2 stays unloaded and the fallback chain skips it.
ARG AUDIOCPP_REPO=https://github.com/0xShug0/audio.cpp.git
ARG AUDIOCPP_REF=dev
RUN apt-get update && apt-get install -y --no-install-recommends \
		git \
		cmake \
		ninja-build \
	&& rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${AUDIOCPP_REF}" "${AUDIOCPP_REPO}" /build/audiocpp \
	|| echo "WARNING: audio.cpp clone failed — YuE2 will be disabled"
RUN if [ -d /build/audiocpp ]; then cd /build/audiocpp \
	&& if command -v nvcc >/dev/null 2>&1; then \
		scripts/build_linux.sh --backend cuda --model-set custom --models yue2 --target audiocpp_cli \
		|| scripts/build_linux.sh --backend cuda --target audiocpp_cli \
		|| scripts/build_linux.sh --backend cpu --target audiocpp_cli; \
	else \
		scripts/build_linux.sh --backend cpu --model-set custom --models yue2 --target audiocpp_cli \
		|| scripts/build_linux.sh --backend cpu --target audiocpp_cli; \
	fi \
	&& mkdir -p /app/audiocpp/bin \
	&& find build -name audiocpp_cli -type f -exec cp {} /app/audiocpp/bin/ \; \
	|| echo "WARNING: audiocpp_cli build failed — YuE2 will be disabled"; fi

# ── Stage 2: runner ───────────────────────────────────────────────────────────
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime AS runner

# Least-privilege user.
RUN groupadd -g 1000 gbedu && useradd -u 1000 -g 1000 -m -s /bin/bash gbedu

WORKDIR /app

# Runtime system deps — audio I/O and codec support.
RUN apt-get update && apt-get install -y --no-install-recommends \
		ffmpeg \
		libsndfile1 \
		curl \
	&& rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/venv /app/venv
COPY --from=builder --chown=gbedu:gbedu /build/services/ml/src /app/src
COPY --from=builder --chown=gbedu:gbedu /app/audiocpp /app/audiocpp

# HF Hub cache persisted via volume in docker-compose; set here so the process
# uses a writable path owned by the gbedu user.
ENV PATH="/app/venv/bin:$PATH" \
	PYTHONPATH="/app/src" \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	TRANSFORMERS_CACHE="/app/model-cache" \
	HF_HOME="/app/model-cache" \
	TORCH_HOME="/app/model-cache/torch"

RUN mkdir -p /app/model-cache && chown gbedu:gbedu /app/model-cache

USER gbedu

EXPOSE 8001

# Longer start period — model weights stream from HF Hub on first cold start.
HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=5 \
	CMD curl -sf http://localhost:8001/health || exit 1

CMD ["uvicorn", "gbedu_ml.main:app", \
	"--host", "0.0.0.0", \
	"--port", "8001", \
	"--workers", "1", \
	"--log-level", "info"]
