# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────
# Zenvyrolabs Voice Studio — one-command, cross-platform container image.
# Default build is CPU-only so it runs anywhere with no NVIDIA drivers.
# (GPU instructions are in DOCKER.md.)
# Python is pinned to 3.11 because the AI libraries break on 3.12+.
# ─────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    IN_DOCKER=1 \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860 \
    HF_HOME=/app/hf_cache \
    NUMBA_DISABLE_JIT=1

# System dependencies:
#   ffmpeg     — audio decode/encode used by pydub (mp3/wav)
#   libsndfile1 — backend for the `soundfile` package
#   git, build-essential — required to build a few Python wheels
#   curl       — used by the container HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        git \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU PyTorch first so pip does not pull the large CUDA wheels.
# Pinned to 2.5.1: newer torchaudio (2.8+) drops its native audio backends in
# favour of 'torchcodec', which fails to load its shared library and breaks
# F5-TTS. 2.5.1 keeps the soundfile backend and satisfies transformers + f5-tts.
# For GPU, swap the index URL (see DOCKER.md).
RUN pip install --upgrade pip && \
    pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu

# Install the remaining Python dependencies (cached unless requirements change).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the application source.
COPY . .

# Data directories that are persisted via docker-compose volumes so nothing
# is lost when the container stops (saved voices, models, datasets, HF cache).
RUN mkdir -p /app/saved_voices /app/rvc_models /app/training_data /app/hf_cache /app/temp

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS "http://localhost:${GRADIO_SERVER_PORT}/" || exit 1

CMD ["python", "app.py"]
