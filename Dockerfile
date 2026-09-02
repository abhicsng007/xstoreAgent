# xStoreAgent — container for Cloud Run
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# uv/uvx so the ClickHouse MCP server (`uvx mcp-clickhouse`) is available at runtime
RUN pip install --no-cache-dir uv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent ./agent
COPY server ./server
COPY web ./web
# Bundle the sample pack + scripts so the hosted demo is self-contained: the
# "Ingest & Organize" button can ingest /app/sample_assets on Cloud Run.
COPY sample_assets ./sample_assets
COPY scripts ./scripts

# Cloud Run sets $PORT; bind to it.
CMD exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT}
