"""ClickHouse data layer for xStoreAgent (partner integration).

Direct `clickhouse-connect` client used by the FastAPI dashboard and for writes
(ingest / archive). Catalog *reads* from the Librarian agent go through the
official `mcp-clickhouse` server — this module is the write path and the
deterministic UI path, not the agent's query path.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from .config import get_settings
from .reusability import reusability_sql_expr


def _as_datetime(value: Any) -> datetime:
    """Coerce a created_at value (str from scan.py, or datetime) to datetime, which
    is what clickhouse-connect requires for a DateTime column."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.now()

_ASSETS_COLUMNS = [
    "id", "path", "filename", "asset_type", "asset_subtype", "ext", "size_bytes",
    "created_at", "project", "caption", "tags", "reusable", "status",
    "content_hash", "embedding", "visual_embedding",
]

_EVENT_COLUMNS = ["asset_id", "event", "project", "bytes", "detail"]
_BRIEF_COLUMNS = ["brief", "embedding"]


def get_client(database: str | None = None) -> Client:
    """Connect to ClickHouse. Pass database='default' to connect before our own
    database exists (used by ensure_schema); otherwise the configured database."""
    s = get_settings()
    return clickhouse_connect.get_client(
        host=s.ch_host,
        port=s.ch_port,
        username=s.ch_user,
        password=s.ch_password,
        secure=s.ch_secure,
        database=database if database is not None else s.ch_database,
    )


def ensure_schema(client: Client | None = None) -> None:
    """Create database + assets table if absent. Idempotent (see agent/schema.sql).

    Connects to the always-present `default` database first, since our target
    database may not exist yet on a fresh instance.
    """
    s = get_settings()
    client = client or get_client(database="default")
    client.command(f"CREATE DATABASE IF NOT EXISTS {s.ch_database}")
    client.command(
        f"""
        CREATE TABLE IF NOT EXISTS {s.ch_database}.assets
        (
            id UUID DEFAULT generateUUIDv4(),
            path String, filename String,
            asset_type LowCardinality(String),
            asset_subtype LowCardinality(String) DEFAULT '',
            ext LowCardinality(String),
            size_bytes UInt64, created_at DateTime DEFAULT now(),
            project String DEFAULT '',
            caption String DEFAULT '', tags Array(String) DEFAULT [],
            reusable Bool DEFAULT true,
            status LowCardinality(String) DEFAULT 'active',
            content_hash String DEFAULT '',
            embedding Array(Float32) DEFAULT [],
            visual_embedding Array(Float32) DEFAULT []
        )
        ENGINE = MergeTree ORDER BY (asset_type, created_at)
        """
    )
    # Backfill columns on instances created before they were tracked.
    client.command(
        f"ALTER TABLE {s.ch_database}.assets "
        f"ADD COLUMN IF NOT EXISTS asset_subtype LowCardinality(String) DEFAULT ''"
    )
    # visual_embedding: true multimodal (image/video) vector for visual near-dup.
    client.command(
        f"ALTER TABLE {s.ch_database}.assets "
        f"ADD COLUMN IF NOT EXISTS visual_embedding Array(Float32) DEFAULT []"
    )
    client.command(
        f"""
        CREATE TABLE IF NOT EXISTS {s.ch_database}.asset_events
        (
            ts DateTime DEFAULT now(),
            asset_id UUID,
            event LowCardinality(String),
            project String DEFAULT '',
            bytes UInt64 DEFAULT 0,
            detail String DEFAULT ''
        )
        ENGINE = MergeTree ORDER BY (event, ts)
        """
    )
    client.command(
        f"""
        CREATE TABLE IF NOT EXISTS {s.ch_database}.brief_queries
        (
            ts DateTime DEFAULT now(),
            brief String,
            embedding Array(Float32)
        )
        ENGINE = MergeTree ORDER BY ts
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
            r.get("id") or str(uuid4()),
            r.get("path", ""),
            r.get("filename", ""),
            r.get("asset_type", "other"),
            r.get("asset_subtype", ""),
            r.get("ext", ""),
            int(r.get("size_bytes", 0)),
            _as_datetime(r.get("created_at")),
            r.get("project", ""),
            r.get("caption", ""),
            list(r.get("tags", [])),
            bool(r.get("reusable", True)),
            r.get("status", "active"),
            r.get("content_hash", ""),
            [float(x) for x in r.get("embedding", [])],
            [float(x) for x in r.get("visual_embedding", [])],
        ])
    client.insert(
        table="assets",
        data=data,
        column_names=_ASSETS_COLUMNS,
        database=get_settings().ch_database,
    )
    return len(data)


def existing_hashes(client: Client | None = None) -> set[str]:
    """Content hashes already in the catalog — ingest skips these so a folder
    can be re-pointed at without paying Gemini twice or duplicating rows."""
    client = client or get_client()
    result = client.query(
        "SELECT DISTINCT content_hash FROM assets WHERE content_hash != ''"
    )
    return {row[0] for row in result.result_rows if row[0]}


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


def duplicate_groups(client: Client | None = None) -> list[dict[str, Any]]:
    """Exact duplicates via GROUP BY content_hash (ClickHouse-idiomatic, not CROSS JOIN).

    `wasted_bytes` is reclaimable storage if every extra copy is archived
    (sum(size) - max(size) for the group).
    """
    client = client or get_client()
    result = client.query(
        """
        SELECT content_hash,
               groupArray(toString(id)) AS ids,
               groupArray(filename) AS files,
               groupArray(size_bytes) AS sizes,
               any(asset_type) AS asset_type,
               count() AS n,
               sum(size_bytes) - max(size_bytes) AS wasted_bytes
        FROM assets
        WHERE content_hash != '' AND status != 'archived'
        GROUP BY content_hash
        HAVING n > 1
        ORDER BY wasted_bytes DESC
        """
    )
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def find_duplicates(
    threshold: float | None = None, client: Client | None = None
) -> list[dict[str, Any]]:
    """Duplicate pairs for the dashboard review list.

    Exact copies come from `duplicate_groups` (hash GROUP BY), expanded into
    pairs so the existing Archive button still has an `id_b`. Near-duplicates
    (same type, embedding cosine under the threshold) are a secondary pass.
    """
    client = client or get_client()
    thr = threshold if threshold is not None else get_settings().dup_distance_threshold

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for g in duplicate_groups(client=client):
        ids = [str(x) for x in (g.get("ids") or [])]
        files = list(g.get("files") or [])
        if len(ids) < 2:
            continue
        keep_id, keep_name = ids[0], files[0] if files else ids[0]
        for i, extra_id in enumerate(ids[1:], start=1):
            key = (keep_id, extra_id)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "id_a": keep_id,
                "file_a": keep_name,
                "id_b": extra_id,
                "file_b": files[i] if i < len(files) else extra_id,
                "asset_type": g.get("asset_type", ""),
                "distance": 0.0,
                "wasted_bytes": int(g.get("wasted_bytes") or 0),
                "kind": "exact",
            })

    # Near-duplicates from the TRUE visual (multimodal) vector when present —
    # falls back to the caption vector for rows that predate visual_embedding.
    near = client.query(
        """
        WITH embedded AS (
            SELECT id, filename, asset_type,
                   if(length(visual_embedding) > 0, visual_embedding, embedding) AS vec
            FROM assets
            WHERE status != 'archived'
              AND (length(visual_embedding) > 0 OR length(embedding) > 0)
        )
        SELECT toString(a.id) AS id_a, a.filename AS file_a,
               toString(b.id) AS id_b, b.filename AS file_b,
               a.asset_type AS asset_type,
               cosineDistance(a.vec, b.vec) AS distance
        FROM embedded AS a
        CROSS JOIN embedded AS b
        WHERE a.id < b.id AND a.asset_type = b.asset_type
          AND length(a.vec) = length(b.vec)
          AND cosineDistance(a.vec, b.vec) < {thr:Float64}
        ORDER BY distance ASC
        LIMIT 50
        """,
        parameters={"thr": thr},
    )
    for row in near.result_rows:
        d = dict(zip(near.column_names, row))
        key = (str(d["id_a"]), str(d["id_b"]))
        if key in seen:
            continue
        seen.add(key)
        d["kind"] = "near"
        d["wasted_bytes"] = 0
        out.append(d)
    out.sort(key=lambda d: (0 if d.get("kind") == "exact" else 1, d["distance"]))
    return out


def set_status(asset_id: str, status: str, client: Client | None = None) -> None:
    """Update an asset's lifecycle status (active | duplicate | stale | archived).

    Uses a lightweight update; never deletes rows so actions stay reversible.
    """
    client = client or get_client()
    client.command(
        "ALTER TABLE assets UPDATE status = {s:String} WHERE id = {id:UUID}",
        parameters={"s": status, "id": asset_id},
    )


def _asset_filters(
    asset_type: str | None,
    status: str | None,
    project: str | None = None,
) -> tuple[str, dict[str, Any]]:
    where = ["1"]
    params: dict[str, Any] = {}
    if asset_type:
        where.append("asset_type = {atype:String}")
        params["atype"] = asset_type
    if status:
        where.append("status = {status:String}")
        params["status"] = status
    if project:
        where.append("project = {project:String}")
        params["project"] = project
    return " AND ".join(where), params


def count_assets(
    asset_type: str | None = None,
    status: str | None = None,
    project: str | None = None,
    client: Client | None = None,
) -> int:
    """Row count matching the dashboard list filters."""
    client = client or get_client()
    where, params = _asset_filters(asset_type, status, project)
    result = client.query(
        f"SELECT count() FROM assets WHERE {where}",
        parameters=params,
    )
    return int(result.result_rows[0][0]) if result.result_rows else 0


def list_assets(
    asset_type: str | None = None,
    status: str | None = None,
    project: str | None = None,
    limit: int = 24,
    offset: int = 0,
    sort: str = "reusability",
    client: Client | None = None,
) -> list[dict[str, Any]]:
    """List catalog assets for the dashboard grid.

    Optional filters by `asset_type` and lifecycle `status`. The embedding vector
    is intentionally omitted from the payload (large, not needed by the UI).
    `sort` is `reusability` (default) or `newest`.
    """
    client = client or get_client()
    where, params = _asset_filters(asset_type, status, project)
    params["limit"] = max(1, min(int(limit), 100))
    params["offset"] = max(0, int(offset))
    score_sql = reusability_sql_expr()
    order = (
        "reusability_score DESC, created_at DESC"
        if sort == "reusability"
        else "created_at DESC"
    )
    result = client.query(
        f"""
        SELECT toString(id) AS id, path, filename, asset_type, asset_subtype, ext,
               size_bytes, created_at, project, caption, tags, reusable, status,
               {score_sql} AS reusability_score
        FROM assets
        WHERE {where}
        ORDER BY {order}
        LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
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


def ping() -> bool:
    """True when ClickHouse accepts a trivial query."""
    get_client(database="default").command("SELECT 1")
    return True


def get_asset(asset_id: str, client: Client | None = None) -> dict[str, Any] | None:
    """Fetch one catalog row (including source path) for previews."""
    client = client or get_client()
    score_sql = reusability_sql_expr()
    result = client.query(
        f"""
        SELECT toString(id) AS id, path, filename, asset_type, asset_subtype, ext,
               size_bytes, created_at, project, caption, tags, reusable, status,
               {score_sql} AS reusability_score
        FROM assets
        WHERE toString(id) = {{id:String}}
        LIMIT 1
        """,
        parameters={"id": str(asset_id)},
    )
    if not result.result_rows:
        return None
    return dict(zip(result.column_names, result.result_rows[0]))


def insert_events(rows: list[dict[str, Any]], client: Client | None = None) -> int:
    """Append lifecycle facts (ingested / searched / archived / kept) for analytics."""
    if not rows:
        return 0
    client = client or get_client()
    data = []
    for r in rows:
        aid = r.get("asset_id") or "00000000-0000-0000-0000-000000000000"
        data.append([
            str(aid),
            r.get("event", "ingested"),
            r.get("project", ""),
            int(r.get("bytes", 0) or 0),
            str(r.get("detail", "") or "")[:500],
        ])
    client.insert(
        table="asset_events",
        data=data,
        column_names=_EVENT_COLUMNS,
        database=get_settings().ch_database,
    )
    return len(data)


def insert_brief(brief: str, embedding: list[float], client: Client | None = None) -> None:
    """Store a project-brief embedding so MCP SQL can JOIN it (no giant literals)."""
    client = client or get_client()
    client.insert(
        table="brief_queries",
        data=[[brief[:2000], [float(x) for x in embedding]]],
        column_names=_BRIEF_COLUMNS,
        database=get_settings().ch_database,
    )
