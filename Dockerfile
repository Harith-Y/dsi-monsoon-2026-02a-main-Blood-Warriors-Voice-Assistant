# Blood Warriors voice assistant: FastAPI backend + the web UI (caregiver page, /dashboard, /teach).
#
#   docker compose up --build        (see docker-compose.yml and the README)
#
# Secrets (GROQ_API_KEY, HF_TOKEN, COORDINATOR_PASSCODE, COORDINATOR_WHATSAPP) are never baked into the image:
# they come from .env at run time. Models (LaBSE, IndicConformer) download on first start into the /models
# volume; the knowledge base, version history, coordinator requests, logs and audio live in the /data volume.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libsndfile: reading WAV (what the web pages send); ffmpeg: other formats (mp3, m4a, webm);
# libgomp: OpenMP for torch / faiss on Linux
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first (the default wheels bundle CUDA and are several GB larger), then everything else.
COPY requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.6,<3.0" "torchaudio>=2.6,<3.0" \
    && pip install -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 bw \
    && mkdir -p /data /models \
    && chown -R bw:bw /data /models \
    && chmod +x docker/entrypoint.sh

ENV HF_HOME=/models \
    BW_DATA_DIR=/data/runtime \
    BW_KB_PATH=/data/kb/entries.json \
    BW_KB_VARIANTS_PATH=/data/kb/question_variants.json \
    BW_INDEX_DIR=/data/index \
    BW_TTS_CACHE_DIR=/data/tts_cache \
    BW_LOG_PATH=/data/logs/requests.jsonl

USER bw
VOLUME ["/data", "/models"]
EXPOSE 8000

# The first start downloads the models, so give it time before the health check counts.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

ENTRYPOINT ["docker/entrypoint.sh"]
# One worker: the live search index, sign-in rate limit and clarify sessions are kept in the process.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
