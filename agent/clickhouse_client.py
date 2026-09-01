"""ClickHouse data layer for ReelVault (partner integration).

This is the direct `clickhouse-connect` client used by the FastAPI server and as
the fallback behind the ClickHouse MCP toolset. It owns the `assets` catalog:
schema provisioning, inserts, vector (repurpose) search via cosineDistance, and
near-duplicate detection.
"""
from __future__ import annotations

from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from .config import get_settings

_ASSETS_COLUMNS = [
    "path", "filename", "asset_type", "ext", "size_bytes", "created_at",
    "project", "caption", "tags", "reusable", "status", "content_hash", "embedding",
]


def get_client() -> Client:
    s = get_settings()
    return clickhouse_connect.get_client(
        host=s.ch_host,
        port=s.ch_port,
        username=s.ch_user,
        password=s.ch_password,
        secure=s.ch_secure,
        database=s.ch_database,
    )


def ensure_schema(client: Client | None = None) -> None:
    """Create database + assets table if absent. Idempotent (see agent/schema.sql)."""
    s = get_settings()
    client = client or get_client()
    client.command(f"CREATE DATABASE IF NOT EXISTS {s.ch_database}")
    client.command(
        f"""
        CREATE TABLE IF NOT EXISTS {s.ch_database}.assets
        (
            id UUID DEFAULT generateUUIDv4(),
            path String, filename String,
            asset_type LowCardinality(String), ext LowCardinality(String),
            size_bytes UInt64, created_at DateTime DEFAULT now(),
            project String DEFAULT '',
            caption String DEFAULT '', tags Array(String) DEFAULT [],
            reusable Bool DEFAULT true,
            status LowCardinality(String) DEFAULT 'active',
            content_hash String DEFAULT '',
            embedding Array(Float32) DEFAULT []
        )
        ENGINE = MergeTree ORDER BY (asset_type, created_at)
        """
    )


def insert_assets(rows: list[dict[str, Any]], client: Client | None = None) -> int:
    """Insert asset rows. Missing optional fields are defaulted here so callers can
    pass partial dicts (e.g. straight from scan.py before the model pass)."""
    if not rows:
        return 0
    client = client or get_client()
    data = []
    for r in rows:
        data.append([
            r.get("path", ""),
            r.get("filename", ""),
            r.get("asset_type", "other"),
            r.get("ext", ""),
            int(r.get("size_bytes", 0)),
            r.get("created_at"),
            r.get("project", ""),
            r.get("caption", ""),
            list(r.get("tags", [])),
            bool(r.get("reusable", True)),
            r.get("status", "active"),
            r.get("content_hash", ""),
            [float(x) for x in r.get("embedding", [])],
        ])
    client.insert(
        table="assets",
        data=data,
        column_names=_ASSETS_COLUMNS,
        database=get_settings().ch_database,
    )
    return len(data)


def repurpose_search(
    brief_vec: list[float], limit: int = 12, client: Client | None = None
) -> list[dict[str, Any]]:
    """Rank non-archived assets by closeness to a project-brief embedding.

    Lower cosineDistance == closer. Returns rows with a `distance` field the UI
    turns into a match score and the agent explains with a 'why it fits' line.
    """
    client = client or get_client()
    result = client.query(
        """
        SELECT id, filename, asset_type, caption, tags, path, reusable, status,
               cosineDistance(embedding, {vec:Array(Float32)}) AS distance
        FROM assets
        WHERE status != 'archived' AND length(embedding) > 0
        ORDER BY distance ASC
        LIMIT {limit:UInt32}
        """,
        parameters={"vec": [float(x) for x in brief_vec], "limit": limit},
    )
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def find_duplicates(
    threshold: float | None = None, client: Client | None = None
) -> list[dict[str, Any]]:
    """Find near-duplicate asset pairs within the same type.

    Exact duplicates (same content_hash) are always returned; embedding pairs with
    cosineDistance below `threshold` are returned as likely-dup candidates. The
    agent proposes archiving the newer/lower-value member; a human approves.
    """
    client = client or get_client()
    thr = threshold if threshold is not None else get_settings().dup_distance_threshold
    result = client.query(
        """
        SELECT a.id AS id_a, a.filename AS file_a,
               b.id AS id_b, b.filename AS file_b,
               a.asset_type AS asset_type,
               if(a.content_hash = b.content_hash AND a.content_hash != '', 0,
                  cosineDistance(a.embedding, b.embedding)) AS distance
        FROM assets AS a
        CROSS JOIN assets AS b
        WHERE a.id < b.id
          AND a.asset_type = b.asset_type
          AND a.status != 'archived' AND b.status != 'archived'
          AND (
                (a.content_hash = b.content_hash AND a.content_hash != '')
             OR (length(a.embedding) > 0 AND length(b.embedding) > 0
                 AND cosineDistance(a.embedding, b.embedding) < {thr:Float64})
          )
        ORDER BY distance ASC
        """,
        parameters={"thr": thr},
    )
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def set_status(asset_id: str, status: str, client: Client | None = None) -> None:
    """Update an asset's lifecycle status (active | duplicate | stale | archived).

    Uses a lightweight update; never deletes rows so actions stay reversible.
    """
    client = client or get_client()
    client.command(
        "ALTER TABLE assets UPDATE status = {s:String} WHERE id = {id:UUID}",
        parameters={"s": status, "id": asset_id},
    )


def list_assets(
    asset_type: str | None = None,
    status: str | None = None,
    limit: int = 200,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    """List catalog assets for the dashboard grid, newest first.

    Optional filters by `asset_type` and lifecycle `status`. The embedding vector
    is intentionally omitted from the payload (large, not needed by the UI).
    """
    client = client or get_client()
    where = ["1"]
    params: dict[str, Any] = {"limit": limit}
    if asset_type:
        where.append("asset_type = {atype:String}")
        params["atype"] = asset_type
    if status:
        where.append("status = {status:String}")
        params["status"] = status
    result = client.query(
        f"""
        SELECT toString(id) AS id, filename, asset_type, ext, size_bytes,
               created_at, project, caption, tags, reusable, status
        FROM assets
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT {{limit:UInt32}}
        """,
        parameters=params,
    )
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def library_overview(client: Client | None = None) -> list[dict[str, Any]]:
    """Per-type counts and bytes for the dashboard roll-up."""
    client = client or get_client()
    result = client.query(
        """
        SELECT asset_type,
               count() AS count,
               sum(size_bytes) AS bytes,
               countIf(status = 'archived') AS archived,
               countIf(reusable) AS reusable
        FROM assets
        GROUP BY asset_type
        ORDER BY bytes DESC
        """
    )
    return [dict(zip(result.column_names, row)) for row in result.result_rows]
