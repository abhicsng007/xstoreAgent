"""ingest_folder: the full ingestion pipeline (scan -> classify -> embed -> store).

This is the single agentic action the Librarian agent calls to bring a folder
into the catalog. Each file flows through:
    scan_folder        -> type, size, hash
    classify_asset     -> caption, tags, reusable verdict, refined type (Gemini)
    embed_asset        -> multimodal embedding (shared 1408-d space)
    insert_assets      -> one ClickHouse row

`ingest_folder` runs the pipeline and returns a summary. `ingest_folder_events`
runs the *same* pipeline as a generator, yielding a step-by-step reasoning trace
framed as a small crew of sub-agents (Scanner / Curator / Memory / Archivist) so
the UI can render the agent thinking in real time. `ingest_folder` is a thin
wrapper that drains the generator and returns its final summary — one pipeline,
two views, no divergence.
"""
from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

from .. import clickhouse_client as ch
from .classify import classify_asset
from .embed import EMBED_DIM, embed_asset, embed_image, embed_video
from .scan import scan_folder, summarize

# The sub-agents the pipeline is narrated as. Each maps to a real pipeline stage,
# so the reasoning trace is an honest view of the work, not theatre.
SCANNER = ("Scanner", "\U0001F50D")     # 🔍 walk + segregate by type
CURATOR = ("Curator", "\U0001F3AC")     # 🎬 Gemini caption + reusability verdict
MEMORY = ("Memory", "\U0001F9E0")       # 🧠 embed + write to ClickHouse
ARCHIVIST = ("Archivist", "\U0001F5C4")  # 🗄️ flag duplicates + stale for review


def _step(agent, status: str, title: str, detail: str = "", data: dict | None = None) -> dict:
    """One reasoning event. `status` is working | done | info | error."""
    name, icon = agent
    return {
        "type": "step",
        "agent": name,
        "icon": icon,
        "status": status,
        "title": title,
        "detail": detail,
        "data": data or {},
    }


def ingest_folder_events(
    root: str, project: str = "", limit: int | None = None
) -> Iterator[dict]:
    """Run the ingestion pipeline, yielding a live multi-agent reasoning trace.

    Yields `step` events as each sub-agent works, and a final `done` event whose
    `summary` matches exactly what `ingest_folder` returns.
    """
    yield {"type": "start", "root": root, "project": project}

    # --- Scanner: walk the folder and segregate by type -------------------------
    yield _step(SCANNER, "working", "Walking the folder",
                f"Reading every file under {root} and hashing for duplicates…")
    assets = scan_folder(root, compute_hash=True)
    skipped = [a for a in assets if a.size_bytes == 0]
    assets = [a for a in assets if a.size_bytes > 0]
    if limit:
        assets = assets[:limit]

    summary = summarize(assets)
    by_type = summary["by_type"]
    breakdown = ", ".join(f"{v['count']} {k}" for k, v in sorted(by_type.items())) or "nothing"
    yield _step(SCANNER, "done",
                f"Segregated {len(assets)} files into {len(by_type)} types",
                f"{breakdown}"
                + (f" · skipped {len(skipped)} empty" if skipped else "")
                + (f" · {summary['needs_review']} need a closer look" if summary["needs_review"] else ""),
                data={"by_type": by_type, "total_files": len(assets)})

    # --- Per-file: Curator judges, Memory embeds --------------------------------
    rows: list[dict] = []
    reusable_n = stale_n = 0
    for i, a in enumerate(assets, 1):
        yield _step(CURATOR, "working", f"Inspecting {a.filename}",
                    f"[{i}/{len(assets)}] Asking Gemini to caption it and judge reuse…")
        meta = classify_asset(a.path, a.asset_type, a.ext)
        asset_type = meta.get("refined_type", a.asset_type) if a.needs_review else a.asset_type
        caption = meta.get("caption", "")
        reusable = bool(meta.get("reusable", True))
        reusable_n += reusable
        stale_n += (not reusable)
        verdict = "reusable" if reusable else "project-specific"
        yield _step(CURATOR, "done", f"{a.filename} → {verdict}",
                    f"“{caption}” — {meta.get('reason', '')}".strip(" —"),
                    data={"filename": a.filename, "asset_type": asset_type,
                          "reusable": reusable, "caption": caption})

        yield _step(MEMORY, "working", f"Embedding {a.filename}",
                    "Projecting its meaning into the shared vector space…")
        embedding = embed_asset(asset_type, a.path, caption=caption)
        got = bool(embedding)
        # True visual (multimodal) vector for image/video — powers visual
        # near-duplicate detection. Skipped gracefully on unreadable/stub media.
        visual: list[float] = []
        if asset_type in ("image", "video"):
            try:
                visual = (embed_video if asset_type == "video" else embed_image)(
                    a.path, contextual_text=caption
                )
            except Exception as exc:  # noqa: BLE001 — caption vector still stored
                print(f"[ingest] visual embed skipped for {a.filename}: {exc}")
        yield _step(MEMORY, "done",
                    f"{a.filename} vectorized" if got else f"{a.filename} stored (no vector)",
                    (f"{len(embedding)}-d caption vector"
                     + (f" + {len(visual)}-d visual vector" if visual else "")
                     + " queued for ClickHouse") if got
                    else f"embedding unavailable — metadata still catalogued (dim {EMBED_DIM})",
                    data={"filename": a.filename, "dims": len(embedding),
                          "visual_dims": len(visual)})

        row = a.to_row()
        row.update(
            id=str(uuid4()),
            asset_type=asset_type,
            asset_subtype=meta.get("asset_subtype", ""),
            project=project,
            caption=caption,
            tags=list({*a.tags, *meta.get("tags", [])}),
            reusable=reusable,
            status="stale" if not reusable else "active",
            embedding=embedding,
            visual_embedding=visual,
        )
        rows.append(row)

    # --- Memory: commit to ClickHouse -------------------------------------------
    yield _step(MEMORY, "working", "Writing to ClickHouse",
                f"Committing {len(rows)} assets to the library's long-term memory…")
    inserted = 0
    try:
        ch.ensure_schema()
        inserted = ch.insert_assets(rows)
        try:
            ch.insert_events([
                {
                    "asset_id": r["id"],
                    "event": "ingested",
                    "project": project,
                    "bytes": int(r.get("size_bytes", 0) or 0),
                    "detail": r.get("filename", ""),
                }
                for r in rows
            ])
        except Exception as exc:  # noqa: BLE001 — catalog write already succeeded
            print(f"[ingest] asset_events skipped: {exc}")
        yield _step(MEMORY, "done", f"Remembered {inserted} assets",
                    f"{reusable_n} reusable · {stale_n} project-specific now searchable",
                    data={"inserted": inserted})
    except Exception as exc:  # ClickHouse unreachable — keep the trace alive
        yield _step(MEMORY, "error", "ClickHouse write skipped", str(exc)[:180])

    # --- Archivist: flag reclaimable storage ------------------------------------
    yield _step(ARCHIVIST, "working", "Hunting duplicates & dead weight",
                "Comparing vectors for near-duplicates and listing project-specific files…")
    try:
        dups = ch.find_duplicates()
        yield _step(ARCHIVIST, "done",
                    f"Flagged {len(dups)} duplicate pairs · {stale_n} stale",
                    "Nothing deleted — queued for your one-click approval.",
                    data={"duplicates": len(dups), "stale": stale_n})
    except Exception as exc:
        yield _step(ARCHIVIST, "info", "Duplicate scan deferred", str(exc)[:180])

    result = {
        "root": root,
        "project": project,
        "scanned": len(assets),
        "skipped_empty": len(skipped),
        "inserted": inserted,
        "summary": summary,
    }
    yield {"type": "done", "summary": result}


def ingest_folder(root: str, project: str = "", limit: int | None = None) -> dict:
    """Ingest every file under `root` into the ClickHouse catalog.

    Drives `ingest_folder_events` to completion and returns its final summary, so
    the deterministic API and the streaming trace can never drift apart.

    Args:
        root: folder to ingest.
        project: label stamped on every asset (the project it came from).
        limit: optional cap on files processed (useful for demos / cost control).

    Returns:
        Summary dict: files scanned, rows inserted, and the per-type roll-up.
    """
    result: dict = {}
    for ev in ingest_folder_events(root, project=project, limit=limit):
        if ev.get("type") == "done":
            result = ev["summary"]
    return result
