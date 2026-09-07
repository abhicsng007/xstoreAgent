"""Connect free-tier vendors, watch folders, organize, offload, and fetch.

Vendors are connected via a *sync folder* — the local directory MEGA/Drive/
Dropbox/pCloud keep in sync. xStoreAgent organizes files into a captioned tree
inside that folder (sidecars + MANIFEST) so a later ingest is text-only.

Recommendations: delete duplicate extras, archive stale, offload reusable
evergreen media to a connected vendor, fetch offloaded files back when needed.
"""
from __future__ import annotations

import os
import shutil
from typing import Any
from uuid import uuid4

from .. import clickhouse_client as ch
from ..reusability import reusability_score
from ..sidecar import write_manifest, write_sidecar
from ..config import sample_assets_path
from .scan import scan_folder

VENDOR_PRESETS: list[dict[str, Any]] = [
    {"vendor": "mega", "name": "MEGA", "free_gb": 20, "url": "https://mega.io"},
    {"vendor": "gdrive", "name": "Google Drive", "free_gb": 15, "url": "https://drive.google.com"},
    {"vendor": "pcloud", "name": "pCloud", "free_gb": 10, "url": "https://www.pcloud.com"},
    {"vendor": "icedrive", "name": "Icedrive", "free_gb": 10, "url": "https://icedrive.net"},
    {"vendor": "internxt", "name": "Internxt", "free_gb": 10, "url": "https://internxt.com"},
    {"vendor": "onedrive", "name": "Microsoft OneDrive", "free_gb": 5, "url": "https://onedrive.live.com"},
    {"vendor": "dropbox", "name": "Dropbox", "free_gb": 2, "url": "https://www.dropbox.com"},
    {"vendor": "custom", "name": "Custom / NAS folder", "free_gb": 0, "url": ""},
]


def _safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return keep[:80] or "asset"


def rel_for(asset: dict[str, Any]) -> str:
    """Where this asset belongs in an organized cloud pack."""
    fname = _safe_name(asset.get("filename") or "file")
    reusable = bool(asset.get("reusable", True))
    status = asset.get("status") or "active"
    atype = asset.get("asset_type") or "other"
    subtype = asset.get("asset_subtype") or ""
    if status in ("stale", "duplicate") or not reusable:
        folder = "archive-candidates" if status in ("stale", "duplicate") else "project-specific"
        return f"{folder}/{atype}/{fname}"
    if subtype in ("logo", "icon") or atype in ("icon", "vector"):
        return f"reusable/brand/{fname}"
    if atype == "video":
        return f"reusable/video/{fname}"
    if atype == "audio":
        return f"reusable/audio/{fname}"
    if atype in ("image",):
        return f"reusable/images/{fname}"
    return f"reusable/{atype}/{fname}"


def _local_path(asset: dict[str, Any]) -> str | None:
    from server.preview import resolve_media_path

    return resolve_media_path(asset)


def connect_vendor(vendor: str, root: str, label: str = "",
                   free_gb: float = 0, url: str = "") -> dict[str, Any]:
    ch.ensure_schema()
    preset = next((p for p in VENDOR_PRESETS if p["vendor"] == vendor), None)
    os.makedirs(root, exist_ok=True)
    vid = ch.insert_vendor({
        "vendor": vendor or "custom",
        "label": label or (preset or {}).get("name") or vendor,
        "root": os.path.abspath(root),
        "free_gb": free_gb or (preset or {}).get("free_gb") or 0,
        "url": url or (preset or {}).get("url") or "",
        "status": "connected",
    })
    return {"id": vid, "root": os.path.abspath(root)}


def watch_folder(path: str, project: str = "") -> dict[str, Any]:
    ch.ensure_schema()
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Not a folder: {path}")
    wid = ch.insert_watched(os.path.abspath(path), project=project)
    return {"id": wid, "path": os.path.abspath(path), "project": project}


def organize_to_vendor(vendor_id: str, asset_ids: list[str] | None = None) -> dict[str, Any]:
    """Copy local files into a captioned tree under the vendor sync folder."""
    ch.ensure_schema()
    vendors = [v for v in ch.list_vendors() if v["id"] == vendor_id]
    if not vendors:
        raise ValueError("Unknown vendor")
    vendor = vendors[0]
    dest_root = os.path.join(vendor["root"], "xStoreAgent")
    os.makedirs(dest_root, exist_ok=True)

    if asset_ids:
        assets = [ch.get_asset(i) for i in asset_ids]
        assets = [a for a in assets if a]
    else:
        assets = ch.list_assets(project="demo", limit=100, sort="reusability")
        if len(assets) < 3:
            assets = ch.list_assets(limit=100, sort="reusability")

    copied = 0
    skipped = 0
    entries: list[dict] = []
    for a in assets:
        src = _local_path(a)
        if not src:
            skipped += 1
            continue
        rel = rel_for(a)
        dest = os.path.join(dest_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.abspath(src) != os.path.abspath(dest):
            shutil.copy2(src, dest)
        write_sidecar(dest, {
            "content_hash": a.get("content_hash", ""),
            "asset_type": a.get("asset_type"),
            "asset_subtype": a.get("asset_subtype"),
            "caption": a.get("caption"),
            "tags": a.get("tags") or [],
            "reusable": a.get("reusable", True),
            "size_bytes": a.get("size_bytes", 0),
            "analyzed": "text-sidecar",
        })
        ch.add_location(a["id"], dest, vendor=vendor.get("vendor", ""), kind="cloud")
        copied += 1
        entries.append({
            "rel": rel.replace("\\", "/"),
            "filename": a.get("filename"),
            "asset_id": a["id"],
            "caption": a.get("caption", ""),
            "asset_type": a.get("asset_type"),
            "reusable": a.get("reusable", True),
        })
    write_manifest(dest_root, entries)
    return {
        "vendor_id": vendor_id,
        "dest": dest_root,
        "copied": copied,
        "skipped": skipped,
        "entries": len(entries),
    }


def offload_assets(vendor_id: str, asset_ids: list[str]) -> dict[str, Any]:
    """Organize + mark assets as living on the vendor (keep catalog, no Gemini)."""
    result = organize_to_vendor(vendor_id, asset_ids)
    vendors = [v for v in ch.list_vendors() if v["id"] == vendor_id]
    vname = (vendors[0]["vendor"] if vendors else "") or ""
    for aid in asset_ids:
        ch.patch_asset(aid, {"location": "both", "vendor": vname})
        try:
            ch.insert_events([{"asset_id": aid, "event": "offloaded", "detail": vname}])
        except Exception:
            pass
    result["offloaded"] = len(asset_ids)
    return result


def fetch_asset(asset_id: str, dest_dir: str | None = None) -> dict[str, Any]:
    """Copy an offloaded file back to a local folder from a cloud location."""
    row = ch.get_asset(asset_id)
    if not row:
        raise ValueError("Unknown asset")
    locs = ch.list_locations(asset_id)
    cloud = next((l for l in locs if l.get("kind") == "cloud" and l.get("path")
                  and os.path.isfile(l["path"])), None)
    src = (cloud or {}).get("path") or ""
    if not src or not os.path.isfile(src):
        # Fall back to current path if it still exists.
        src = row.get("path") or ""
        if not src or not os.path.isfile(src):
            raise FileNotFoundError("No cloud/local file to fetch")
    dest_dir = dest_dir or os.path.join(sample_assets_path(), "_restored")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src).replace(".xstore.json", ""))
    shutil.copy2(src, dest)
    side = src + ".xstore.json"
    if os.path.isfile(side):
        shutil.copy2(side, dest + ".xstore.json")
    ch.add_location(asset_id, dest, kind="local")
    ch.patch_asset(asset_id, {"location": "both", "path": dest})
    try:
        ch.insert_events([{"asset_id": asset_id, "event": "fetched", "detail": dest}])
    except Exception:
        pass
    return {"asset_id": asset_id, "dest": dest}


def forget_local(asset_id: str) -> dict[str, Any]:
    """Delete the local bytes after a successful offload. Catalog row stays."""
    row = ch.get_asset(asset_id)
    if not row:
        raise ValueError("Unknown asset")
    locs = ch.list_locations(asset_id)
    has_cloud = any(l.get("kind") == "cloud" and l.get("path") and os.path.isfile(l["path"])
                    for l in locs)
    path = row.get("path") or ""
    if not has_cloud:
        raise ValueError("Refusing to delete: no cloud copy on disk")
    removed = False
    if path and os.path.isfile(path):
        os.remove(path)
        side = path + ".xstore.json"
        if os.path.isfile(side):
            os.remove(side)
        removed = True
    ch.patch_asset(asset_id, {"location": "cloud"})
    ch.add_location(asset_id, path, kind="local", present=False)
    return {"asset_id": asset_id, "removed": removed}


def recommend() -> list[dict[str, Any]]:
    """Scout-style actions: delete extras, archive stale, offload, fetch."""
    ch.ensure_schema()
    recs: list[dict[str, Any]] = []
    vendors = ch.list_vendors()
    watched = ch.list_watched()

    dups = ch.find_duplicates()
    exact = [d for d in dups if d.get("kind") == "exact"][:8]
    if exact:
        recs.append({
            "action": "delete_duplicate",
            "title": f"Archive {len(exact)} exact duplicate copies",
            "detail": "Keep one file, archive extras. Nothing is deleted until you approve.",
            "count": len(exact),
            "bytes": sum(int(d.get("wasted_bytes") or 0) for d in exact[:1]) or 0,
            "asset_id": exact[0].get("id_b"),
        })

    stale_n = ch.count_assets(status="stale")
    if stale_n:
        recs.append({
            "action": "archive_stale",
            "title": f"{stale_n} project-specific / stale files",
            "detail": "Slates, rough cuts, one-off VO — archive locally; don't pay to store them in the cloud.",
            "count": stale_n,
        })

    if vendors:
        recs.append({
            "action": "offload_reusable",
            "title": f"Offload reusable B-roll to {vendors[0]['label']}",
            "detail": (
                "Organize captions + folders, copy evergreen media into the vendor "
                "sync folder. Later ingest is text-only (no Gemini watch)."
            ),
            "vendor_id": vendors[0]["id"],
            "count": 0,
        })
        recs.append({
            "action": "organize",
            "title": "Arrange + caption a cloud pack",
            "detail": "Build reusable/ and project-specific/ with .xstore.json sidecars before upload.",
            "vendor_id": vendors[0]["id"],
        })
    else:
        recs.append({
            "action": "connect_vendor",
            "title": "Connect a free-tier vendor",
            "detail": "Point MEGA / Drive / pCloud / Dropbox at their local sync folder, then offload.",
        })

    offloaded = ch.list_assets(limit=24, sort="newest")
    need_fetch = [a for a in offloaded if (a.get("location") or "") == "cloud"]
    if need_fetch:
        recs.append({
            "action": "fetch",
            "title": f"Fetch {len(need_fetch)} offloaded assets back",
            "detail": "Catalog already has captions — restore files without re-analysis.",
            "asset_id": need_fetch[0]["id"],
            "count": len(need_fetch),
        })

    new_in_watch = 0
    memory = ch.hash_index()
    for folder in watched:
        path = folder.get("path") or ""
        if not os.path.isdir(path):
            recs.append({
                "action": "missing_folder",
                "title": f"Watched folder missing: {path}",
                "detail": "Reconnect or remove it.",
                "folder_id": folder["id"],
            })
            continue
        try:
            found = scan_folder(path, compute_hash=True)
        except OSError:
            continue
        for a in found:
            if a.size_bytes and a.content_hash and a.content_hash not in memory:
                new_in_watch += 1
    if new_in_watch:
        recs.append({
            "action": "scan_watched",
            "title": f"{new_in_watch} new files in watched folders",
            "detail": "Ingest them. Known hashes reuse catalog memory; sidecars skip Gemini watch.",
            "count": new_in_watch,
        })
    elif watched:
        recs.append({
            "action": "scan_watched",
            "title": "Watched folders are in sync",
            "detail": f"{len(watched)} folder(s) tracked. Scan anyway to pick up path changes.",
            "count": 0,
        })

    return recs


def default_export_root(vendor: str) -> str:
    base = os.path.join(sample_assets_path(), "..", "cloud_exports")
    return os.path.abspath(os.path.join(base, vendor or "custom"))
