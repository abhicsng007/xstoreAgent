# xStoreAgent — container for Cloud Run
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# uv/uvx as fallback; mcp-clickhouse is also pip-installed (see requirements.txt)
RUN pip install --no-cache-dir uv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import mcp_clickhouse"

ENV USE_CLICKHOUSE_MCP=true \
    SAMPLE_ASSETS_DIR=/app/sample_assets

COPY agent ./agent
COPY server ./server
COPY web ./web
# Bundle the sample pack + scripts so the hosted demo is self-contained: the
# "Ingest & Organize" button can ingest /app/sample_assets on Cloud Run.
COPY sample_assets ./sample_assets
COPY scripts ./scripts

# Real Mixkit B-roll (6s 720p) so Gemini watches genuine footage. Video is
# gitignored; this step downloads + trims at build time. Falls back to the
# generated pack if Mixkit is unreachable.
RUN python scripts/fetch_demo_pack.py --mixkit-only \
    || (python scripts/make_sample_pack.py && python scripts/make_media_samples.py)

# Cloud Run sets $PORT; bind to it.
CMD exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT}
