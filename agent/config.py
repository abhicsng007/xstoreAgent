"""Central configuration for xStoreAgent, loaded from environment / .env."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Runtime settings sourced from environment variables (see .env.example)."""

    # Google Cloud / Vertex AI
    gcp_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    # Gemini generation location. Gemini 3.x Flash is served from "global".
    gcp_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    # Embeddings need a REGIONAL endpoint — multimodalembedding@001 is not served
    # from "global" — so it has its own location, defaulting to us-central1.
    embedding_location: str = os.getenv("EMBEDDING_LOCATION", "us-central1")
    use_vertexai: bool = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true"

    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    mm_embedding_model: str = os.getenv("MULTIMODAL_EMBEDDING_MODEL", "multimodalembedding@001")
    text_embedding_model: str = os.getenv("TEXT_EMBEDDING_MODEL", "gemini-embedding-001")

    # ClickHouse (partner)
    ch_host: str = os.getenv("CLICKHOUSE_HOST", "")
    ch_port: int = int(os.getenv("CLICKHOUSE_PORT", "8443"))
    ch_user: str = os.getenv("CLICKHOUSE_USER", "default")
    ch_password: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    ch_database: str = os.getenv("CLICKHOUSE_DATABASE", "xstoreAgent")
    ch_secure: bool = os.getenv("CLICKHOUSE_SECURE", "true").lower() == "true"

    # Official ClickHouse MCP server at runtime (hackathon track requirement).
    # Default ON — hosted/demo must not silently fall back to the Python client.
    use_clickhouse_mcp: bool = os.getenv("USE_CLICKHOUSE_MCP", "true").lower() == "true"

    # Multi-agent Librarian (root orchestrator + Analyst/Archivist/Scout/Curator
    # sub-agents). Default ON. Set false to fall back to the single-agent Librarian.
    use_multi_agent: bool = os.getenv("USE_MULTI_AGENT", "true").lower() == "true"

    # Bundled sample pack (Cloud Run image copies it to /app/sample_assets).
    sample_assets_dir: str = os.getenv("SAMPLE_ASSETS_DIR", "")

    # Tuning
    dup_distance_threshold: float = float(os.getenv("DUP_DISTANCE_THRESHOLD", "0.05"))
    # Storage plan cap (GB) the Scout measures the library against; when usage
    # crosses `storage_warn_pct` it recommends web-sourced free storage. Default is
    # a 1 TB tier so the meter reads believably against a real-scale library; the
    # Scout still fires the moment usage crosses the warn threshold.
    storage_plan_gb: float = float(os.getenv("STORAGE_PLAN_GB", "1024"))
    storage_warn_pct: int = int(os.getenv("STORAGE_WARN_PCT", "80"))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def sample_assets_path() -> str:
    """Resolve the bundled sample pack for one-click hosted ingest.

    Prefer SAMPLE_ASSETS_DIR when it exists, then the Cloud Run image path,
    then the repo-root `sample_assets` folder.
    """
    s = get_settings()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        s.sample_assets_dir,
        "/app/sample_assets",
        os.path.join(here, "sample_assets"),
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    return os.path.abspath(os.path.join(here, "sample_assets"))
