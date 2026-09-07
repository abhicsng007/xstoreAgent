"""Per-file analysis sidecars so media is never Gemini-watched twice.

After Gemini captions a clip we write `<file>.xstore.json` next to it. Organizing
for cloud copies those sidecars into a MANIFEST so a later ingest (or another
machine) can catalog from *text* — caption + tags + hash — without sending
video/audio bytes to the model.
"""
from __future__ import annotations

import json
import os
from typing import Any

SIDECAR_SUFFIX = ".xstore.json"
MANIFEST_NAME = "00-MANIFEST.json"
VERSION = 1


def sidecar_path(media_path: str) -> str:
    return media_path + SIDECAR_SUFFIX


def read_sidecar(media_path: str) -> dict[str, Any] | None:
    path = sidecar_path(media_path)
    if not os.path.isfile(path):
        # Also accept a sibling "name.xstore.json" without doubling the ext.
        alt = os.path.splitext(media_path)[0] + SIDECAR_SUFFIX
        path = alt if os.path.isfile(alt) else path
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not (data.get("caption") or "").strip():
        return None
    return data


def write_sidecar(media_path: str, record: dict[str, Any]) -> str | None:
    path = sidecar_path(media_path)
    payload = {
        "version": VERSION,
        "filename": os.path.basename(media_path),
        "content_hash": record.get("content_hash", ""),
        "asset_type": record.get("asset_type", ""),
        "asset_subtype": record.get("asset_subtype", ""),
        "caption": record.get("caption", ""),
        "tags": list(record.get("tags") or []),
        "reusable": bool(record.get("reusable", True)),
        "reason": record.get("reason", ""),
        "size_bytes": int(record.get("size_bytes", 0) or 0),
        "analyzed": record.get("analyzed", "gemini-media"),
    }
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        return path
    except OSError:
        return None


def write_manifest(folder: str, entries: list[dict[str, Any]]) -> str:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, MANIFEST_NAME)
    body = {
        "version": VERSION,
        "generator": "xStoreAgent",
        "note": (
            "Each media file has a sibling .xstore.json caption. Ingest this "
            "tree and Gemini will catalog from text — it will not re-watch video."
        ),
        "count": len(entries),
        "entries": entries,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2, ensure_ascii=False)
    readme = os.path.join(folder, "01-README.txt")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(
            "xStoreAgent organized library\n"
            "============================\n\n"
            "reusable/     evergreen B-roll, audio, stills, brand\n"
            "project-specific/  slates, rough cuts, dialogue — do not offload as stock\n"
            "archive-candidates/  stale / duplicate extras\n\n"
            "Every media file has a .xstore.json sidecar (caption, tags, sha256).\n"
            "Point Ingest folder at this tree: analysis is text-only.\n"
        )
    return path
