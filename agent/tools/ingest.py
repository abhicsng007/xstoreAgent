"""ingest_folder: the full ingestion pipeline (scan -> classify -> embed -> store).

This is the single agentic action the Librarian agent calls to bring a folder
into the catalog. Each file flows through:
    scan_folder        -> type, size, hash
    classify_asset     -> caption, tags, reusable verdict, refined type (Gemini)
    embed_asset        -> multimodal embedding (shared 1408-d space)
    insert_assets      -> one ClickHouse row
"""
from __future__ import annotations

from .. import clickhouse_client as ch
from .classify import classify_asset
from .embed import embed_asset
from .scan import scan_folder, summarize


def ingest_folder(root: str, project: str = "", limit: int | None = None) -> dict:
    """Ingest every file under `root` into the ClickHouse catalog.

    Args:
        root: folder to ingest.
        project: label stamped on every asset (the project it came from).
        limit: optional cap on files processed (useful for demos / cost control).

    Returns:
        Summary dict: files scanned, rows inserted, and the per-type roll-up.
    """
    assets = scan_folder(root, compute_hash=True)
    # Skip empty files (0-byte placeholders / broken exports) — nothing to caption
    # or embed, and they only add noise to the catalog.
    skipped = [a for a in assets if a.size_bytes == 0]
    assets = [a for a in assets if a.size_bytes > 0]
    if limit:
        assets = assets[:limit]

    rows: list[dict] = []
    for a in assets:
        meta = classify_asset(a.path, a.asset_type, a.ext)
        # A flagged image may be refined into an icon/vector by the model.
        asset_type = meta.get("refined_type", a.asset_type) if a.needs_review else a.asset_type
        caption = meta.get("caption", "")
        embedding = embed_asset(asset_type, a.path, caption=caption)

        row = a.to_row()
        row.update(
            asset_type=asset_type,
            project=project,
            caption=caption,
            tags=list({*a.tags, *meta.get("tags", [])}),
            reusable=bool(meta.get("reusable", True)),
            status="stale" if not meta.get("reusable", True) else "active",
            embedding=embedding,
        )
        rows.append(row)

    ch.ensure_schema()
    inserted = ch.insert_assets(rows)
    return {
        "root": root,
        "project": project,
        "scanned": len(assets),
        "skipped_empty": len(skipped),
        "inserted": inserted,
        "summary": summarize(assets),
    }
