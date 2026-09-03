"""Seed the ClickHouse catalog with thousands of realistic asset rows, so the
Librarian's rollup / duplicate-waste / impact numbers are computed over real
scale (GBs, thousands of files) instead of a 13-file toy library.

    python scripts/seed_scale.py --count 5000            # add 5k rows
    python scripts/seed_scale.py --count 5000 --project archive_import

These rows are for the *analytics* story (library rollup, reclaimable duplicate
storage, ClickHouse aggregating fast at scale). They carry realistic sizes,
types, captions, and a controlled duplicate rate, but NO caption embedding — so
they stay out of the semantic brief→asset search and near-dup demos, which run on
the hand-embedded `sample_assets` rows. They are stamped with a distinct
`project` so they're always distinguishable from the real sample pack.

Writes go through the same `clickhouse_client.insert_assets` path the app uses.
Reads in the demo still go through mcp-clickhouse; this only fills the table.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import clickhouse_client as ch
from agent.reusability import reusability_score

_MB = 1024 * 1024
_GB = 1024 * _MB

# (asset_type, asset_subtype, mean size MB, reusable-by-default), with a weight.
# Sizes are what real media weighs, so sum(size_bytes) reads in real GB/TB.
_MIX = [
    ("video", "b_roll",     420.0, True,  22),
    ("video", "vfx_plate",  680.0, True,   6),
    ("video", "dialogue",   540.0, False, 10),   # takes/dailies — project-specific
    ("audio", "music",       48.0, True,   8),
    ("audio", "sfx",          6.0, True,  10),
    ("audio", "dialogue",    36.0, False,  6),
    ("image", "photo",        4.5, True,  14),
    ("image", "screenshot",   1.2, False,  6),
    ("icon",  "icon",         0.06, True,  8),
    ("vector", "logo",        0.8, True,   5),
    ("vector", "vector_art",  1.4, True,   5),
    ("document", "document",  0.3, False,  4),
]

_SUBJECTS = ["city skyline", "coastal highway", "forest canopy", "product close-up",
             "studio interview", "neon street", "mountain ridge", "office desk",
             "crowd b-roll", "sunrise timelapse", "kitchen scene", "abstract loop",
             "brand mark", "app screen", "concert stage", "drone shot"]
_MOODS = ["dusk", "golden hour", "moody", "bright", "cinematic", "high-key",
          "desaturated", "vibrant", "overcast", "warm"]
_MOTION = ["static", "slow pan", "handheld", "dolly", "orbit", "locked-off", "tracking"]


def _rand_hash(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(64))


def _caption(rng: random.Random, atype: str, subtype: str) -> tuple[str, list[str]]:
    subj = rng.choice(_SUBJECTS)
    mood = rng.choice(_MOODS)
    motion = rng.choice(_MOTION)
    caption = f"{mood} {subj} — {subtype.replace('_', ' ')} ({motion})"
    tags = list({subj.split()[0], mood, motion, subtype, atype})
    return caption, tags


def build_rows(count: int, project: str, dup_rate: float, seed: int) -> list[dict]:
    rng = random.Random(seed)
    weights = [w for *_, w in _MIX]
    now = datetime.now()
    rows: list[dict] = []
    # Pool of (hash, size, atype) we can duplicate to create real reclaimable waste.
    pool: list[tuple[str, int, str]] = []

    for i in range(count):
        atype, subtype, mean_mb, reusable_default, _ = rng.choices(_MIX, weights=weights)[0]
        # Log-normal-ish size: multiplicative jitter around the type's mean.
        size = max(1024, int(mean_mb * _MB * rng.lognormvariate(0.0, 0.6)))

        # With probability dup_rate, duplicate an earlier same-type asset exactly
        # (same content_hash + size) so GROUP BY content_hash yields true waste.
        same_type = [p for p in pool if p[2] == atype]
        if same_type and rng.random() < dup_rate:
            chash, size, _ = rng.choice(same_type)
        else:
            chash = _rand_hash(rng)
            pool.append((chash, size, atype))

        reusable = reusable_default and rng.random() > 0.08  # a little noise
        status = "active"
        if not reusable:
            status = "stale"
        if rng.random() < 0.03:
            status = "archived"

        caption, tags = _caption(rng, atype, subtype)
        created = now - timedelta(days=rng.randint(0, 540), minutes=rng.randint(0, 1440))
        ext = {"video": ".mp4", "audio": ".wav", "image": ".jpg",
               "icon": ".png", "vector": ".svg", "document": ".pdf"}.get(atype, ".bin")
        fname = f"{caption.split(' — ')[0].replace(' ', '_')}_{i:05d}{ext}"

        rows.append({
            "path": f"/archive/{project}/{fname}",
            "filename": fname,
            "asset_type": atype,
            "asset_subtype": subtype,
            "ext": ext,
            "size_bytes": size,
            "created_at": created,
            "project": project,
            "caption": caption,
            "tags": tags,
            "reusable": reusable,
            "status": status,
            "content_hash": chash,
            "embedding": [],          # bulk rows stay out of semantic search
            "visual_embedding": [],
        })
    return rows


def seed(count: int = 5000, project: str = "archive_import",
         dup_rate: float = 0.10, seed_val: int = 42, batch: int = 1000) -> int:
    ch.ensure_schema()
    rows = build_rows(count, project, dup_rate, seed_val)
    inserted = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        inserted += ch.insert_assets(chunk)
        print(f"  inserted {inserted}/{len(rows)} …")
    # Matching ingest events (gives asset_events real volume for the MCP story).
    try:
        ch.insert_events([
            {"event": "ingested", "project": project,
             "bytes": int(r["size_bytes"]), "detail": r["filename"]}
            for r in rows
        ])
    except Exception as exc:  # noqa: BLE001 — asset rows already committed
        print(f"  (asset_events skipped: {exc})")

    total_bytes = sum(r["size_bytes"] for r in rows)
    dups = sum(1 for r in rows) - len({r["content_hash"] for r in rows})
    print(f"Seeded {inserted} rows for project={project!r}: "
          f"{total_bytes / _GB:.1f} GB, ~{dups} duplicate copies.")
    return inserted


def main() -> int:
    p = argparse.ArgumentParser(description="Seed realistic asset rows at scale.")
    p.add_argument("--count", type=int, default=5000, help="rows to insert (default 5000)")
    p.add_argument("--project", default="archive_import", help="project label for the batch")
    p.add_argument("--dup-rate", type=float, default=0.10, help="fraction that are exact duplicates")
    p.add_argument("--seed", type=int, default=42, help="RNG seed (reproducible)")
    args = p.parse_args()
    seed(count=args.count, project=args.project, dup_rate=args.dup_rate, seed_val=args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
