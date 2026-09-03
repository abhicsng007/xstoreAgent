"""Reset the xStoreAgent library to a clean state — for a tidy demo recording.

TRUNCATEs the ClickHouse `assets` table (keeps the schema, drops every row), then
optionally re-ingests a folder so you start from a known, duplicate-free library.

DESTRUCTIVE: it deletes every catalogued asset row on the configured ClickHouse
instance. It refuses to run without an explicit --yes so you can't wipe the table
by accident.

    # wipe only:
    python scripts/reset_library.py --yes

    # wipe, then re-ingest a clean sample library in one shot:
    python scripts/reset_library.py --yes --ingest sample_assets --project demo

    # …and top up with 5k realistic rows so the analytics run at real scale:
    python scripts/reset_library.py --yes --ingest sample_assets --project demo --seed 5000

Reads the same .env as the app (GCP + ClickHouse settings).
"""
from __future__ import annotations

import argparse
import os
import sys

# Allow running as `python scripts/reset_library.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import clickhouse_client as ch
from agent.config import get_settings


def _count(client) -> int:
    try:
        return int(client.query("SELECT count() FROM assets").result_rows[0][0])
    except Exception:
        return 0


def reset(ingest_root: str | None = None, project: str = "", seed_count: int = 0) -> None:
    settings = get_settings()
    db = settings.ch_database

    # Make sure the table (and the asset_subtype column) exists before we touch it.
    ch.ensure_schema()
    client = ch.get_client()

    before = _count(client)
    print(f"Library: {before} assets in {db}.assets")

    client.command(f"TRUNCATE TABLE {db}.assets")
    after = _count(client)
    print(f"Truncated → {after} assets remaining.")

    if ingest_root:
        print(f"Re-ingesting {ingest_root!r} (project={project or '—'}) …")
        # Import here so a wipe-only run never needs the model/embedding stack.
        from agent.tools.ingest import ingest_folder

        result = ingest_folder(ingest_root, project=project)
        by_type = result.get("summary", {}).get("by_type", {})
        breakdown = ", ".join(f"{v['count']} {k}" for k, v in sorted(by_type.items()))
        print(f"Ingested {result.get('inserted', 0)} assets "
              f"from {result.get('scanned', 0)} files: {breakdown}")

    if seed_count > 0:
        print(f"Seeding {seed_count} realistic rows for scale …")
        from seed_scale import seed  # scripts/ is on sys.path via this file

        seed(count=seed_count, project="archive_import")

    print("Done. Library is clean.")


def main() -> int:
    p = argparse.ArgumentParser(description="Reset (truncate) the xStoreAgent library.")
    p.add_argument("--yes", action="store_true",
                   help="Required. Confirms you want to DELETE all asset rows.")
    p.add_argument("--ingest", metavar="FOLDER", default=None,
                   help="After wiping, re-ingest this folder for a clean library.")
    p.add_argument("--project", default="", help="Project label for the re-ingest.")
    p.add_argument("--seed", type=int, default=0, metavar="N",
                   help="After ingest, add N realistic rows (scale) via seed_scale.")
    args = p.parse_args()

    if not args.yes:
        print("Refusing to wipe the library without --yes.\n"
              "This deletes EVERY asset row on the configured ClickHouse instance.\n"
              "Re-run with --yes (optionally --ingest sample_assets) to proceed.")
        return 2

    reset(ingest_root=args.ingest, project=args.project, seed_count=args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
