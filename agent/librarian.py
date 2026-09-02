"""The Librarian: the ADK root agent for xStoreAgent.

Writes (ingest / archive) are function tools. Catalog *reads* go through the
official ClickHouse MCP server so judges see `list_tables` / `run_select_query`
on the live path. Run interactively with `adk web` (repo root) or via `/api/chat/stream`.
"""
from __future__ import annotations

from . import clickhouse_client as ch
from .clickhouse_mcp import build_clickhouse_mcp_toolset
from .config import get_settings
from .tools.embed import embed_text
from .tools.ingest import ingest_folder as _ingest_folder


def ingest_folder(root: str, project: str = "") -> dict:
    """Ingest a local media folder into the catalog: classify every file by type,
    caption it with Gemini, judge whether it is reusable, embed it, and store it
    in ClickHouse.

    Args:
        root: absolute path to the folder to organize.
        project: name of the project these assets came from (optional label).

    Returns:
        A summary with counts of files scanned and stored, grouped by asset type.
    """
    return _ingest_folder(root, project=project)


def embed_brief(brief: str) -> dict:
    """Embed a project brief and store the vector in ClickHouse `brief_queries`.

    Do not put the floats in SQL. After this returns, search with a JOIN against
    the latest brief_queries row (see the `how_to_search` field).

    Args:
        brief: natural-language description of the new project's needs.
    """
    vec = embed_text(brief)
    if not vec:
        return {"dim": 0, "stored": False, "error": "empty embedding"}
    ch.insert_brief(brief, vec)
    db = get_settings().ch_database
    return {
        "dim": len(vec),
        "stored": True,
        "how_to_search": (
            f"WITH q AS (SELECT embedding FROM {db}.brief_queries ORDER BY ts DESC LIMIT 1) "
            f"SELECT filename, asset_type, asset_subtype, caption, tags, reusable, "
            f"toString(id) AS id, cosineDistance(a.embedding, q.embedding) AS dist "
            f"FROM {db}.assets AS a, q "
            f"WHERE status != 'archived' AND length(a.embedding) > 0 "
            f"ORDER BY dist ASC LIMIT 12"
        ),
    }


def archive_asset(asset_id: str) -> dict:
    """Mark an asset as archived (reversible). Use only after the user approves.
    Archived assets drop out of repurpose search but are never deleted."""
    ch.set_status(asset_id, "archived")
    try:
        ch.insert_events([{"asset_id": asset_id, "event": "archived"}])
    except Exception as exc:  # noqa: BLE001
        print(f"[librarian] archive event skipped: {exc}")
    return {"asset_id": asset_id, "status": "archived"}


def surface_repurposable(brief: str, limit: int = 12) -> list[dict]:
    """Dashboard helper (not an agent tool): rank assets by caption embedding."""
    vec = embed_text(brief)
    if not vec:
        return []
    results = ch.repurpose_search(vec, limit=limit)
    for r in results:
        r["match_score"] = round(max(0.0, 1.0 - float(r.get("distance", 1.0))) * 100)
    return results


def list_duplicates() -> list[dict]:
    """Dashboard helper (not an agent tool): exact + near duplicate pairs."""
    return ch.find_duplicates()


def library_stats() -> list[dict]:
    """Dashboard helper (not an agent tool): per-type roll-up."""
    return ch.library_overview()


def _instruction() -> str:
    db = get_settings().ch_database
    return f"""You are the Librarian, an AI asset manager for a film/video production team.
You organize media and tell creators what they can REUSE instead of reshooting.

The catalog lives in ClickHouse database `{db}`.
Tables:
  `{db}.assets` — one row per file (caption, tags, reusable, status, content_hash, embedding Array(Float32), size_bytes, asset_type, asset_subtype)
  `{db}.asset_events` — ingest/search/archive facts (ts, event, bytes, detail)
  `{db}.brief_queries` — latest project-brief embedding written by embed_brief

READS — you MUST use the ClickHouse MCP tools. Never invent table contents.
  1. Call list_tables (database `{db}`) before the first catalog answer in a session.
  2. Answer stats, waste, and reuse questions ONLY with run_select_query or run_query.
  3. Always qualify tables as `{db}.assets` / `{db}.asset_events`.

Canonical queries (adapt filters, keep this shape):

Library rollup:
  SELECT asset_type, count() AS n, sum(size_bytes) AS bytes, countIf(reusable) AS reusable
  FROM {db}.assets WHERE status != 'archived' GROUP BY asset_type ORDER BY bytes DESC

Exact duplicate waste (GROUP BY — do not CROSS JOIN):
  SELECT content_hash, groupArray(filename) AS files, count() AS n,
         sum(size_bytes) - max(size_bytes) AS wasted_bytes
  FROM {db}.assets
  WHERE content_hash != '' AND status != 'archived'
  GROUP BY content_hash HAVING n > 1
  ORDER BY wasted_bytes DESC

Reuse search for a brief:
  Call embed_brief(brief) first. It stores the vector in `{db}.brief_queries`.
  Then run_query using the `how_to_search` SQL it returned (JOIN the latest brief
  row — never paste thousands of floats into the query).

WRITES — function tools only:
  ingest_folder, archive_asset. Never archive unless the user explicitly approves
  a specific asset id.

How to answer a "what can we reuse / what's wasted / what should I archive" brief:
  - list_tables
  - rollup query
  - duplicate-waste query
  - embed_brief + cosineDistance query
  Then a short package:
    1. Reuse slate — each asset with WHY it fits (from caption/tags), match as 1-dist.
    2. Duplicate waste — files and wasted_bytes (human units).
    3. Archive candidates — extra copies and status='stale' rows; wait for approval.
    4. Impact heuristic (label it as a heuristic, not a quote):
       unused reusable b_roll/video ≈ $400 reshoot each;
       logo/icon/vector_art ≈ $150 relicense;
       music/sfx ≈ $80.
  Be concise and practical. Cite MCP SQL results, not guesses.
"""


def build_agent():
    """Construct the ADK root agent: write function tools + ClickHouse MCP reads."""
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    mcp = build_clickhouse_mcp_toolset()
    if mcp is None:
        raise RuntimeError(
            "ClickHouse MCP toolset is required (USE_CLICKHOUSE_MCP=true and "
            "mcp-clickhouse installed). Catalog reads must go through the official "
            "mcp-clickhouse server."
        )

    return Agent(
        name="librarian",
        model=get_settings().gemini_model,
        description="Organizes a creator's media library and surfaces reusable assets.",
        instruction=_instruction(),
        tools=[
            FunctionTool(func=ingest_folder),
            FunctionTool(func=embed_brief),
            FunctionTool(func=archive_asset),
            mcp,
        ],
    )


# ADK's `adk web` / `adk run` looks for a module-level `root_agent`.
try:
    root_agent = build_agent()
except Exception as _exc:  # allow import without ADK/credentials present
    root_agent = None
    print(f"[librarian] agent not built at import ({_exc}); build_agent() on demand")
