"""The Librarian: the ADK root agent for ReelVault.

Registers the ingestion, search, dedup, and archive actions as function tools and
(when available) the ClickHouse MCP toolset. The agent reasons over a creator's
media library: it ingests folders, surfaces repurposable assets from a project
brief, flags duplicates/stale files, and archives them on approval.

Run interactively with the ADK dev UI:  `adk web`  (from the repo root),
or import `root_agent` from the FastAPI server for programmatic calls.
"""
from __future__ import annotations

from . import clickhouse_client as ch
from .clickhouse_mcp import build_clickhouse_mcp_toolset
from .config import get_settings
from .tools.embed import embed_text
from .tools.ingest import ingest_folder as _ingest_folder

# --- Tool functions (ADK wraps these; docstrings become the tool descriptions) ---


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


def surface_repurposable(brief: str, limit: int = 12) -> list[dict]:
    """Given a new project brief, return existing assets worth reusing, ranked by
    relevance. Works cross-modal: a text brief can surface matching video, images,
    audio, or vectors because everything shares one embedding space.

    Args:
        brief: a description of the new project's needs.
        limit: max number of assets to return.

    Returns:
        Ranked assets, each with filename, asset_type, caption, and a match score.
    """
    vec = embed_text(brief)
    if not vec:
        return []
    results = ch.repurpose_search(vec, limit=limit)
    for r in results:
        # Turn cosine distance into an intuitive 0-100 match score for the UI/agent.
        r["match_score"] = round(max(0.0, 1.0 - float(r.get("distance", 1.0))) * 100)
    return results


def list_duplicates() -> list[dict]:
    """Find near-duplicate and exact-duplicate asset pairs in the catalog so the
    user can reclaim storage. Returns candidate pairs; nothing is deleted."""
    return ch.find_duplicates()


def archive_asset(asset_id: str) -> dict:
    """Mark an asset as archived (reversible). Use only after the user approves.
    Archived assets drop out of repurpose search but are never deleted."""
    ch.set_status(asset_id, "archived")
    return {"asset_id": asset_id, "status": "archived"}


def library_stats() -> list[dict]:
    """Per-type roll-up of the library: file counts, bytes, reusable and archived
    counts. Use for the dashboard and for reporting storage usage."""
    return ch.library_overview()


_INSTRUCTION = """You are the Librarian, an AI asset manager for a film/video
production team. You help creators organize, understand, and REUSE their media.

You can:
  - ingest_folder: bring a folder of media into the catalog.
  - surface_repurposable: given a new project brief, recommend assets to reuse.
  - list_duplicates: find duplicate/near-duplicate files to reclaim storage.
  - archive_asset: archive a file — ONLY after the user explicitly approves.
  - library_stats: report what's in the library.

Rules:
  - Never archive or delete anything without explicit user approval. Propose, then
    wait for confirmation.
  - When surfacing repurposable assets, briefly say WHY each fits the brief.
  - Be concise and practical; you are a working tool for busy creators."""


def build_agent():
    """Construct the ADK root agent with function tools + ClickHouse MCP toolset."""
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    tools = [
        FunctionTool(func=ingest_folder),
        FunctionTool(func=surface_repurposable),
        FunctionTool(func=list_duplicates),
        FunctionTool(func=archive_asset),
        FunctionTool(func=library_stats),
    ]
    mcp = build_clickhouse_mcp_toolset()
    if mcp is not None:
        tools.append(mcp)

    return Agent(
        name="librarian",
        model=get_settings().gemini_model,
        description="Organizes a creator's media library and surfaces reusable assets.",
        instruction=_INSTRUCTION,
        tools=tools,
    )


# ADK's `adk web` / `adk run` looks for a module-level `root_agent`.
try:
    root_agent = build_agent()
except Exception as _exc:  # allow import without ADK/credentials present
    root_agent = None
    print(f"[librarian] agent not built at import ({_exc}); build_agent() on demand")
