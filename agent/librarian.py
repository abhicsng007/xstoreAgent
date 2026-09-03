"""The Librarian: the ADK root agent for xStoreAgent.

Writes (ingest / archive) are function tools. Catalog *reads* go through the
official ClickHouse MCP server so judges see `list_tables` / `run_select_query`
on the live path. Run interactively with `adk web` (repo root) or via `/api/chat/stream`.
"""
from __future__ import annotations

from . import clickhouse_client as ch
from .clickhouse_mcp import build_clickhouse_mcp_toolset
from .config import get_settings
from .tools.assemble import assemble_sequence
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


def _analyst_instruction() -> str:
    db = get_settings().ch_database
    return f"""You are the Analyst, the catalog/data specialist for a film/video
production team's asset library. You answer what's in the library, what to REUSE
instead of reshooting, how much duplicate storage is wasted, and what to archive.

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

Your only write tool is embed_brief (for search). You do NOT ingest or archive —
if the user wants to archive, tell them to approve and the Librarian will route it.

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

Answer the user directly and completely. Do not transfer back to the Librarian.
"""


def _archivist_instruction() -> str:
    return """You are the Archivist. You archive an asset ONLY when the Librarian
routes an explicit, user-approved request naming a specific asset id. Call
archive_asset(asset_id) for that id, confirm what you archived (it is reversible —
nothing is deleted), and stop. Never archive without an explicit approved id.
Answer directly; do not transfer back."""


def _scout_instruction() -> str:
    return """You are the Scout. When the library is running low on storage or the
user asks where to offload media, use Google Search to find cloud-storage
providers with a FREE tier suitable for large media (video/images/audio). Return
5-7 options ranked by free capacity: name, free GB, a short suitability note, and
the signup URL. Prefer current, well-known providers. Answer directly; do not
transfer back."""


def _curator_instruction() -> str:
    return """You are the Curator, the creative-reuse specialist. Given a set of
assets (captions, tags, types) the Analyst surfaced, explain in a creator's voice
WHY each fits the brief and how it could be used in the edit. Keep it vivid and
practical — you shape raw matches into a reuse rationale a director would read.
Answer directly; do not transfer back."""


def _editor_instruction() -> str:
    return """You are the Editor. When the user wants a cut, an edit, a shot list,
a sequence, or "assemble something" from the library for a brief, call
assemble_sequence(brief) and present the result as a storyboard: the title and
logline, the ordered shots (beat, asset, duration, on-screen action, why it fits),
the music bed, and the honest gaps still to shoot. Answer directly; do not
transfer back."""


def _root_instruction() -> str:
    db = get_settings().ch_database
    return f"""You are the Librarian, the orchestrator for a film/video production
team's asset library (catalog in ClickHouse `{db}`). You give a media library a
brain: organize assets and tell creators what to REUSE instead of reshooting.

You lead a small crew of specialists — delegate, don't answer catalog questions
yourself, and never invent catalog contents:
  • analyst  — the data expert. For ANYTHING about what's in the library, what to
    reuse, duplicate waste, storage stats, or brief→asset search, transfer to analyst.
    The analyst queries ClickHouse through the official MCP server.
  • archivist — executes archiving. ONLY after the user explicitly approves
    archiving a specific asset id, transfer to archivist with that id.
  • scout    — finds free cloud storage on the web when storage is tight or asked.
  • curator  — writes the creative "why reuse / how to use" rationale on request.
  • editor   — assembles an edit-ready cut / shot list / sequence from the library
    for a brief. Transfer here when the user wants to "assemble", "cut", "edit",
    build a "shot list", or "make a video" from what they own.

You also hold one tool yourself: ingest_folder, to bring a new folder into the catalog.

Routing: pick the right specialist and transfer. For the common
"what can we reuse / what's wasted / what should I archive" brief, transfer to the
analyst — it returns the full package. For "assemble/cut/edit a sequence", transfer
to the editor. Only handle ingest requests yourself."""


def _build_single_agent(mcp):
    """Fallback: the original single-agent Librarian (USE_MULTI_AGENT=false)."""
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    return Agent(
        name="librarian",
        model=get_settings().gemini_model,
        description="Organizes a creator's media library and surfaces reusable assets.",
        instruction=_analyst_instruction(),
        tools=[
            FunctionTool(func=ingest_folder),
            FunctionTool(func=embed_brief),
            FunctionTool(func=archive_asset),
            mcp,
        ],
    )


def build_agent():
    """Construct the ADK Librarian.

    Multi-agent (default): a root orchestrator that delegates to Analyst (owns the
    ClickHouse MCP reads + brief embedding), Archivist (approved archives), Scout
    (grounded web search for storage), and Curator (creative reuse rationale). We
    use ADK `sub_agents` (LLM-routed transfer) rather than agent-as-tool so a
    delegated agent runs on the SAME event stream — the Analyst's `list_tables` /
    `run_select_query` MCP calls stay visible in the live trace.
    """
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    mcp = build_clickhouse_mcp_toolset()
    if mcp is None:
        raise RuntimeError(
            "ClickHouse MCP toolset is required (USE_CLICKHOUSE_MCP=true and "
            "mcp-clickhouse installed). Catalog reads must go through the official "
            "mcp-clickhouse server."
        )

    if not get_settings().use_multi_agent:
        return _build_single_agent(mcp)

    model = get_settings().gemini_model

    # Analyst owns the MCP read path + brief embedding (the partner integration).
    analyst = Agent(
        name="analyst",
        model=model,
        description="Queries the ClickHouse catalog via mcp-clickhouse: reuse, waste, search.",
        instruction=_analyst_instruction(),
        tools=[FunctionTool(func=embed_brief), mcp],
        disallow_transfer_to_peers=True,
    )
    archivist = Agent(
        name="archivist",
        model=model,
        description="Archives a specific asset id after explicit user approval (reversible).",
        instruction=_archivist_instruction(),
        tools=[FunctionTool(func=archive_asset)],
        disallow_transfer_to_peers=True,
    )
    # Scout uses the built-in Google Search tool (must be its only tool).
    from google.adk.tools import google_search

    scout = Agent(
        name="scout",
        model=model,
        description="Finds free-tier cloud storage on the web when storage is tight.",
        instruction=_scout_instruction(),
        tools=[google_search],
        disallow_transfer_to_peers=True,
    )
    curator = Agent(
        name="curator",
        model=model,
        description="Writes the creative 'why reuse / how to use' rationale for assets.",
        instruction=_curator_instruction(),
        disallow_transfer_to_peers=True,
    )
    editor = Agent(
        name="editor",
        model=model,
        description="Assembles an edit-ready cut / shot list from reusable library assets.",
        instruction=_editor_instruction(),
        tools=[FunctionTool(func=assemble_sequence)],
        disallow_transfer_to_peers=True,
    )

    return Agent(
        name="librarian",
        model=model,
        description="Orchestrates a media-library crew: organize, reuse, dedup, archive.",
        instruction=_root_instruction(),
        tools=[FunctionTool(func=ingest_folder)],
        sub_agents=[analyst, archivist, scout, curator, editor],
    )


# ADK's `adk web` / `adk run` looks for a module-level `root_agent`.
try:
    root_agent = build_agent()
except Exception as _exc:  # allow import without ADK/credentials present
    root_agent = None
    print(f"[librarian] agent not built at import ({_exc}); build_agent() on demand")
