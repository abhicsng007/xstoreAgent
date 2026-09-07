"""Resolve on-disk media for dashboard previews.

Catalog rows store the path from ingest time. On Cloud Run that is often a
Windows path from a local ingest, while the files live under SAMPLE_ASSETS_DIR.
We resolve by existing path first, then by filename under the bundled pack.
"""
from __future__ import annotations

import functools
import os
import subprocess
import tempfile

from agent.config import sample_assets_path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXTS = {".wav", ".mp3", ".aac", ".flac", ".ogg", ".aiff", ".m4a"}


def preview_kind(ext: str, asset_type: str = "") -> str:
    e = (ext or "").lower()
    if e in IMAGE_EXTS or asset_type in {"image", "icon", "vector"}:
        return "image"
    if e in VIDEO_EXTS or asset_type == "video":
        return "video"
    if e in AUDIO_EXTS or asset_type == "audio":
        return "audio"
    return "none"


@functools.lru_cache(maxsize=1)
def _sample_index() -> dict[str, str]:
    """filename (and lowercase) -> absolute path under the bundled pack."""
    root = sample_assets_path()
    out: dict[str, str] = {}
    if not os.path.isdir(root):
        return out
    for dirpath, _, files in os.walk(root):
        for name in files:
            full = os.path.abspath(os.path.join(dirpath, name))
            out[name] = full
            out[name.lower()] = full
    return out


def resolve_media_path(row: dict) -> str | None:
    """Return an on-disk file for this catalog row, or None."""
    path = (row.get("path") or "").strip()
    if path and os.path.isfile(path):
        return os.path.abspath(path)
    fname = (row.get("filename") or os.path.basename(path) or "").strip()
    if not fname:
        return None
    idx = _sample_index()
    return idx.get(fname) or idx.get(fname.lower())


def has_preview(row: dict) -> bool:
    return resolve_media_path(row) is not None


def filename_has_preview(filename: str) -> bool:
    if not filename:
        return False
    idx = _sample_index()
    return filename in idx or filename.lower() in idx


def attach_preview(row: dict, strip_path: bool = True) -> dict:
    """Stamp has_preview / preview_kind; drop filesystem path for the UI."""
    kind = preview_kind(row.get("ext") or "", row.get("asset_type") or "")
    row["preview_kind"] = kind if has_preview(row) else "none"
    row["has_preview"] = row["preview_kind"] != "none"
    if strip_path:
        row.pop("path", None)
    return row


def poster_path(asset_id: str, src: str) -> str | None:
    """Extract (and cache) a JPEG still from a video. None if ffmpeg fails."""
    cache_dir = os.path.join(tempfile.gettempdir(), "xstoreagent-posters")
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, f"{asset_id}.jpg")
    if os.path.isfile(dest) and os.path.getsize(dest) > 256:
        return dest
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", "1", "-i", src, "-frames:v", "1",
        "-vf", "scale=640:-2", "-q:v", "5", dest,
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=20)
    if proc.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) < 256:
        # Try t=0 for very short clips.
        cmd[cmd.index("-ss") + 1] = "0"
        proc = subprocess.run(cmd, capture_output=True, timeout=20)
    if os.path.isfile(dest) and os.path.getsize(dest) > 256:
        return dest
    return None
