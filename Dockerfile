# Vyuha web console.
#
# Deliberately slim: the risk engine needs numpy/scipy/pandas, but nothing here
# needs a GPU or a local model. Inference goes to an OpenAI-compatible endpoint
# serving open-weight models, configured by environment variable. That is what
# lets the same image run on a free 512MB instance.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build deps for scientific wheels, removed again in the same layer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip \
 && pip install ".[api]" \
 && apt-get purge -y build-essential \
 && apt-get autoremove -y

COPY scripts ./scripts
COPY docs ./docs

# Writable paths for the cache and DuckDB file. Most free tiers have an
# ephemeral filesystem, so treat anything here as disposable.
RUN mkdir -p /app/data/cache /app/council_runs
ENV VYUHA_DATA_DIR=/app/data \
    VYUHA_CACHE_DIR=/app/data/cache \
    VYUHA_DB_PATH=/app/data/vyuha.duckdb \
    VYUHA_COUNCIL_LOG_DIR=/app/council_runs

# Hosts inject PORT; default to 8601 for local `docker run`.
ENV PORT=8601
EXPOSE 8601

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8601)}/api/health').read()" || exit 1

CMD ["sh", "-c", "uvicorn vyuha.api.server:app --host 0.0.0.0 --port ${PORT:-8601}"]
