"""End-to-end smoke test: run once your .env (GCP + ClickHouse) is configured.

    python scripts/smoke_test.py [folder]   # defaults to sample_assets

Exercises the real pipeline: connectivity -> ingest -> library stats ->
repurpose search -> duplicate detection. Prints a PASS/FAIL line per stage so
you can confirm the whole system before recording the demo.
"""
from __future__ import annotations

import os
import sys

# Allow running as `python scripts/smoke_test.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import clickhouse_client as ch
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
    folder = sys.argv[1] if len(sys.argv) > 1 else "sample_assets"
    print("xStoreAgent smoke test\n" + "-" * 40)

    stage("ClickHouse connectivity", lambda: ch.get_client().command("SELECT 1"))
    stage("schema provisioned", ch.ensure_schema)

    result = stage(f"ingest '{folder}'", lambda: ingest_folder(folder, project="smoke"))
    print(f"        scanned={result['scanned']} inserted={result['inserted']}")

    overview = stage("library stats", ch.library_overview)
    for row in overview:
        print(f"        {row['asset_type']:9} count={row['count']} bytes={row['bytes']}")

    results = stage(
        "repurpose search",
        lambda: surface_repurposable("city b-roll and brand logo for an upbeat ad", limit=5),
    )
    for r in results[:5]:
        print(f"        {r.get('match_score','?')}%  {r['filename']}  ({r['asset_type']})")

    dups = stage("duplicate detection", list_duplicates)
    print(f"        {len(dups)} duplicate candidate(s)")

    print("-" * 40 + "\nAll stages passed. Ready to demo. ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
