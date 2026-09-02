"""End-to-end smoke test: run once your .env (GCP + ClickHouse) is configured.

    python scripts/smoke_test.py [folder]   # defaults to sample_assets

Exercises connectivity, MCP eligibility, ingest, stats, search, and duplicates.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import clickhouse_client as ch
from agent.clickhouse_mcp import mcp_status
from agent.config import sample_assets_path
from agent.librarian import list_duplicates, surface_repurposable
from agent.tools.ingest import ingest_folder


def stage(name: str, fn):
    try:
        out = fn()
        print(f"  PASS  {name}")
        return out
    except Exception as exc:
        print(f"  FAIL  {name}: {exc}")
        raise


def main() -> int:
    folder = sys.argv[1] if len(sys.argv) > 1 else sample_assets_path()
    print("xStoreAgent smoke test\n" + "-" * 40)

    stage("ClickHouse connectivity", ch.ping)
    stage("schema provisioned", ch.ensure_schema)

    mcp = stage("mcp-clickhouse installed + enabled", mcp_status)
    if not mcp.get("ok"):
        raise SystemExit(
            f"  FAIL  MCP not ready: {mcp}. "
            "Install mcp-clickhouse and keep USE_CLICKHOUSE_MCP=true."
        )
    print(f"        command={mcp.get('command')}")

    result = stage(f"ingest '{folder}'", lambda: ingest_folder(folder, project="smoke"))
    print(f"        scanned={result['scanned']} inserted={result['inserted']}")

    overview = stage("library stats", ch.library_overview)
    for row in overview:
        print(f"        {row['asset_type']:9} count={row['count']} bytes={row['bytes']}")

    groups = stage("duplicate GROUP BY", ch.duplicate_groups)
    print(f"        {len(groups)} exact-hash group(s)")

    results = stage(
        "repurpose search",
        lambda: surface_repurposable("city b-roll and brand logo for an upbeat ad", limit=5),
    )
    for r in results[:5]:
        print(f"        {r.get('match_score', '?')}%  {r['filename']}  ({r['asset_type']})")

    dups = stage("duplicate detection", list_duplicates)
    print(f"        {len(dups)} duplicate candidate(s)")

    try:
        from agent.librarian import build_agent

        stage("ADK agent + MCP toolset constructs", build_agent)
    except Exception as exc:
        print(f"  FAIL  ADK agent: {exc}")
        raise

    print("-" * 40 + "\nAll stages passed. Ready to demo.")
    print("Next: uvicorn server.app:app --reload  →  Golden prompt in the UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
