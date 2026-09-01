"""Central configuration for ReelVault, loaded from environment / .env."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Runtime settings sourced from environment variables (see .env.example)."""

    # Google Cloud / Vertex AI
    gcp_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    gcp_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    use_vertexai: bool = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true"

    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    mm_embedding_model: str = os.getenv("MULTIMODAL_EMBEDDING_MODEL", "multimodalembedding@001")
    text_embedding_model: str = os.getenv("TEXT_EMBEDDING_MODEL", "gemini-embedding-001")

    # ClickHouse (partner)
    ch_host: str = os.getenv("CLICKHOUSE_HOST", "")
    ch_port: int = int(os.getenv("CLICKHOUSE_PORT", "8443"))
    ch_user: str = os.getenv("CLICKHOUSE_USER", "default")
    ch_password: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    ch_database: str = os.getenv("CLICKHOUSE_DATABASE", "reelvault")
    ch_secure: bool = os.getenv("CLICKHOUSE_SECURE", "true").lower() == "true"

    # Tuning
    dup_distance_threshold: float = float(os.getenv("DUP_DISTANCE_THRESHOLD", "0.05"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
