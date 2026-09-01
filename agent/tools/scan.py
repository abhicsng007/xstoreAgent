"""scan_folder: walk a local folder and classify each file by asset type.

Fast path is extension-based (no model call). Files whose type is ambiguous
(e.g. a .png that could be a photo, an icon, or a flat vector export) are marked
`needs_review=True` so a later Gemini multimodal pass in classify.py can refine
them. This keeps ingestion cheap and only spends model calls where they matter.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Extension -> coarse asset type. Kept explicit so the mapping is auditable.
EXT_MAP: dict[str, str] = {
    # video
    ".mp4": "video", ".mov": "video", ".mkv": "video", ".avi": "video",
    ".webm": "video", ".m4v": "video", ".mxf": "video", ".prores": "video",
    # audio
    ".wav": "audio", ".mp3": "audio", ".aac": "audio", ".flac": "audio",
    ".ogg": "audio", ".aiff": "audio", ".m4a": "audio",
    # vector
    ".svg": "vector", ".ai": "vector", ".eps": "vector", ".pdf": "vector",
    # image (raster)
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".tif": "image",
    ".tiff": "image", ".webp": "image", ".bmp": "image", ".heic": "image",
    ".exr": "image", ".dpx": "image", ".psd": "image", ".gif": "image",
    # document
    ".txt": "document", ".md": "document", ".docx": "document",
    ".rtf": "document", ".fdx": "document", ".csv": "document",
}

# Types that a Gemini multimodal pass should refine. A raster image may actually
# be a UI icon or a flat logo; a .pdf may be a document rather than artwork.
AMBIGUOUS_TYPES: set[str] = {"image", "vector"}

# Icon heuristic: small square raster images are very likely icons.
ICON_MAX_DIM = 512


@dataclass
class Asset:
    path: str
    filename: str
    ext: str
    asset_type: str
    size_bytes: int
    created_at: str
    content_hash: str
    needs_review: bool = False
    tags: list[str] = field(default_factory=list)

    def to_row(self) -> dict:
        """Shape matching the ClickHouse `assets` table (minus model-filled fields)."""
        return {
            "path": self.path,
            "filename": self.filename,
            "ext": self.ext,
            "asset_type": self.asset_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "content_hash": self.content_hash,
            "tags": self.tags,
        }


def _sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def _classify_ext(ext: str) -> str:
    return EXT_MAP.get(ext.lower(), "other")


def scan_folder(root: str, compute_hash: bool = True) -> list[Asset]:
    """Recursively walk `root`, returning a classified Asset per file.

    Args:
        root: folder to ingest.
        compute_hash: sha256 each file for exact-duplicate detection. Disable for
            very large libraries where a size+name pre-filter is preferred.

    Returns:
        List of Asset records. Hidden files and our own `organized/` output are skipped.
    """
    if not os.path.isdir(root):
        raise NotADirectoryError(f"Not a folder: {root}")

    assets: list[Asset] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden dirs and prior organize output.
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "organized"]
        for name in filenames:
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            ext = os.path.splitext(name)[1].lower()
            asset_type = _classify_ext(ext)
            needs_review = asset_type in AMBIGUOUS_TYPES
            assets.append(
                Asset(
                    path=os.path.abspath(full),
                    filename=name,
                    ext=ext,
                    asset_type=asset_type,
                    size_bytes=stat.st_size,
                    created_at=datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                    content_hash=_sha256(full) if compute_hash else "",
                    needs_review=needs_review,
                )
            )
    return assets


def summarize(assets: list[Asset]) -> dict[str, object]:
    """Quick roll-up for the dashboard: counts and bytes per asset_type."""
    by_type: dict[str, dict[str, int]] = {}
    for a in assets:
        bucket = by_type.setdefault(a.asset_type, {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += a.size_bytes
    return {
        "total_files": len(assets),
        "total_bytes": sum(a.size_bytes for a in assets),
        "by_type": by_type,
        "needs_review": sum(1 for a in assets if a.needs_review),
    }


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "sample_assets"
    found = scan_folder(target, compute_hash=False)
    print(json.dumps(summarize(found), indent=2))
    for asset in found[:20]:
        print(f"  {asset.asset_type:9} {asset.filename}")
