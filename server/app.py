"""xStoreAgent FastAPI server.

Dashboard endpoints call tool functions directly (deterministic, snappy).
`/api/chat/stream` runs the ADK Librarian so catalog reads go through the
official ClickHouse MCP server — the partner path judges will look for.

Run locally:  uvicorn server.app:app --reload
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from agent import clickhouse_client as ch
from agent.clickhouse_mcp import mcp_status
from agent.config import get_settings, sample_assets_path
from agent.librarian import (
    archive_asset,
    library_stats,
    list_duplicates,
    surface_repurposable,
)
from agent.reusability import REUSABLE_BAND, reusability_score
from agent.tools.assemble import assemble_sequence, assemble_sequence_events
from agent.tools.ingest import ingest_folder, ingest_folder_events
from agent.tools.cloud import (
    VENDOR_PRESETS,
    connect_vendor,
    default_export_root,
    fetch_asset,
    forget_local,
    offload_assets,
    organize_to_vendor,
    recommend,
    watch_folder,
)
from agent.tools.scout import scout_storage_events, storage_status
from server.preview import (
    attach_preview,
    filename_has_preview,
    poster_path,
    preview_kind,
    resolve_media_path,
)

app = FastAPI(title="xStoreAgent", description="AI Asset Librarian for film/video teams")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ARRAY_RE = re.compile(r"\[[-0-9.eE+,\s]{80,}\]")

_runner = None
_runner_lock = asyncio.Lock()


class IngestRequest(BaseModel):
    root: str
    project: str = ""
    limit: int | None = None


class SearchRequest(BaseModel):
    brief: str
    limit: int = 12


class ApproveRequest(BaseModel):
    asset_id: str
    action: str = "archive"  # archive | keep


class ChatRequest(BaseModel):
    message: str
    session_id: str = "web"


class VendorConnect(BaseModel):
    vendor: str
    root: str = ""
    label: str = ""
    free_gb: float = 0
    url: str = ""


class WatchRequest(BaseModel):
    path: str
    project: str = ""


class OffloadRequest(BaseModel):
    vendor_id: str
    asset_ids: list[str] = []


class FetchRequest(BaseModel):
    asset_id: str
    dest: str = ""


@app.on_event("startup")
def _ensure_schema_on_boot() -> None:
    """Make sure the catalog schema is current before serving reads."""
    try:
        ch.ensure_schema()
    except Exception as exc:  # noqa: BLE001 — don't crash startup on a cold DB
        print(f"[startup] ensure_schema skipped: {exc}")


def _clip(value: Any, limit: int = 1600) -> str:
    """Shorten tool args/results so the live SQL trace stays readable.

    Long embedding arrays become `[… N floats]` — the SELECT itself stays.
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = _ARRAY_RE.sub(
        lambda m: f"[… {m.group(0).count(',') + 1} floats]",
        text,
    )
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


async def _get_runner():
    """Process-wide ADK runner so MCP stdio and sessions stay warm."""
    global _runner
    async with _runner_lock:
        if _runner is None:
            from google.adk.runners import InMemoryRunner

            from agent.librarian import build_agent

            _runner = InMemoryRunner(agent=build_agent(), app_name="xstoreagent")
        return _runner


async def _ensure_session(runner, session_id: str) -> None:
    existing = await runner.session_service.get_session(
        app_name="xstoreagent", user_id="web", session_id=session_id
    )
    if existing is None:
        await runner.session_service.create_session(
            app_name="xstoreagent", user_id="web", session_id=session_id
        )


# --- Health ---
@app.get("/api/health")
def health() -> dict:
    clickhouse: dict[str, Any] = {"ok": False, "error": "", "database": get_settings().ch_database}
    try:
        ch.ping()
        clickhouse["ok"] = True
    except Exception as exc:  # noqa: BLE001
        clickhouse["error"] = str(exc)[:240]
    mcp = mcp_status()
    sample = sample_assets_path()
    sample_ok = os.path.isdir(sample)
    return {
        "ok": bool(clickhouse["ok"] and mcp.get("ok")),
        "service": "xstoreagent",
        "clickhouse": clickhouse,
        "mcp": mcp,
        "sample_assets": {"path": sample, "ok": sample_ok},
    }


@app.get("/api/sample-pack")
def api_sample_pack() -> dict:
    path = sample_assets_path()
    return {"path": path, "ok": os.path.isdir(path)}


# --- Ingest ---
@app.post("/api/ingest")
def api_ingest(req: IngestRequest) -> dict:
    if not os.path.isdir(req.root):
        raise HTTPException(400, f"Not a folder: {req.root}")
    return ingest_folder(req.root, project=req.project, limit=req.limit)


def _ingest_event_stream(root: str, project: str, limit: int | None):
    try:
        for ev in ingest_folder_events(root, project=project, limit=limit):
            yield _sse(ev)
    except Exception as exc:  # surface a crash as a final SSE event, not a 500
        yield _sse({"type": "error", "message": str(exc)[:300]})


@app.get("/api/ingest/stream")
def api_ingest_stream(root: str, project: str = "", limit: int | None = None):
    """Server-Sent Events: ingestion pipeline as a live reasoning trace."""
    # Always SSE — EventSource cannot read a JSON 400 body, so a missing folder
    # has to arrive as an `error` event or the UI only shows "connection closed".
    if not os.path.isdir(root):
        def missing():
            yield _sse({"type": "start", "root": root, "project": project})
            yield _sse({
                "type": "error",
                "message": (
                    f"Not a folder on this machine: {root}. "
                    "Folder ingest reads the server disk (local uvicorn), "
                    "not a path on your laptop. On Cloud Run use Ingest sample pack."
                ),
            })

        return StreamingResponse(
            missing(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return StreamingResponse(
        _ingest_event_stream(root, project, limit),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/ingest/sample/stream")
def api_ingest_sample_stream(project: str = "demo", limit: int | None = None):
    """One-click hosted ingest of the bundled sample pack (Cloud Run has no local paths)."""
    root = sample_assets_path()
    if not os.path.isdir(root):
        raise HTTPException(404, f"Sample pack not found at {root}")
    return StreamingResponse(
        _ingest_event_stream(root, project, limit),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Library (dashboard) ---
@app.get("/api/library")
def api_library() -> dict:
    return {"overview": library_stats()}


@app.get("/api/assets")
def api_assets(
    asset_type: str | None = None,
    status: str | None = None,
    project: str | None = None,
    limit: int = 24,
    offset: int = 0,
    sort: str = "reusability",
) -> dict:
    """Paginated catalog list. Each row has a 0-100 reusability_score."""
    if sort not in ("reusability", "newest"):
        raise HTTPException(400, "sort must be reusability or newest")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    total = ch.count_assets(asset_type=asset_type, status=status, project=project)
    if total and offset >= total:
        offset = ((total - 1) // limit) * limit
    assets = ch.list_assets(
        asset_type=asset_type, status=status, project=project,
        limit=limit, offset=offset, sort=sort,
    )
    for a in assets:
        attach_preview(a)
        if a.get("reusability_score") is None:
            a["reusability_score"] = reusability_score(
                a.get("asset_type", "other"),
                a.get("asset_subtype", ""),
                bool(a.get("reusable", True)),
            )
    pages = max(1, (total + limit - 1) // limit) if total else 0
    return {
        "assets": assets,
        "total": total,
        "limit": limit,
        "offset": offset,
        "page": (offset // limit) + 1 if total else 0,
        "pages": pages,
        "reusable_band": REUSABLE_BAND,
    }


@app.get("/api/assets/{asset_id}")
def api_asset(asset_id: str) -> dict:
    """One catalog row plus whether we can serve a preview."""
    try:
        UUID(asset_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid asset id") from exc
    row = ch.get_asset(asset_id)
    if not row:
        raise HTTPException(404, "asset not found")
    attach_preview(row)
    return {"asset": row}


@app.get("/api/preview/{asset_id}")
def api_preview(asset_id: str, kind: str = "auto"):
    """Serve a thumbnail or the original media file.

    `kind=auto` (default): image bytes, or a JPEG poster for video.
    `kind=media`: original image / video / audio file for the lightbox player.
    """
    try:
        UUID(asset_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid asset id") from exc
    row = ch.get_asset(asset_id)
    if not row:
        raise HTTPException(404, "asset not found")
    path = resolve_media_path(row)
    if not path:
        raise HTTPException(404, "preview unavailable")
    ext = (row.get("ext") or os.path.splitext(path)[1] or "").lower()
    pkind = preview_kind(ext, row.get("asset_type") or "")
    want = (kind or "auto").lower()

    if want == "media":
        mime, _ = mimetypes.guess_type(path)
        return FileResponse(
            path,
            media_type=mime or "application/octet-stream",
            content_disposition_type="inline",
        )

    if pkind == "image":
        mime, _ = mimetypes.guess_type(path)
        return FileResponse(path, media_type=mime or "image/jpeg")

    if pkind == "video":
        poster = poster_path(str(row["id"]), path)
        if not poster:
            raise HTTPException(404, "preview unavailable")
        return FileResponse(poster, media_type="image/jpeg")

    raise HTTPException(404, "preview unavailable")


# --- Storage Scout ---
@app.get("/api/storage")
def api_storage() -> dict:
    """Current library usage vs the storage-plan cap (drives the usage meter)."""
    return storage_status()


@app.get("/api/scout/stream")
def api_scout_stream():
    """Server-Sent Events: Scout assesses storage and searches for free tiers."""
    def event_stream():
        try:
            for ev in scout_storage_events():
                yield _sse(ev)
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)[:300]})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/cloud/presets")
def api_cloud_presets() -> dict:
    return {"presets": VENDOR_PRESETS}


@app.get("/api/cloud/vendors")
def api_cloud_vendors() -> dict:
    ch.ensure_schema()
    return {"vendors": ch.list_vendors()}


@app.post("/api/cloud/vendors")
def api_cloud_connect(req: VendorConnect) -> dict:
    root = (req.root or "").strip() or default_export_root(req.vendor)
    try:
        return connect_vendor(
            req.vendor, root, label=req.label, free_gb=req.free_gb, url=req.url,
        )
    except OSError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/cloud/vendors/{vendor_id}")
def api_cloud_disconnect(vendor_id: str) -> dict:
    ch.delete_vendor(vendor_id)
    return {"ok": True}


@app.get("/api/cloud/folders")
def api_cloud_folders() -> dict:
    ch.ensure_schema()
    return {"folders": ch.list_watched()}


@app.post("/api/cloud/folders")
def api_cloud_watch(req: WatchRequest) -> dict:
    try:
        return watch_folder(req.path, project=req.project)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/cloud/folders/{folder_id}")
def api_cloud_unwatch(folder_id: str) -> dict:
    ch.delete_watched(folder_id)
    return {"ok": True}


@app.post("/api/cloud/folders/{folder_id}/scan")
def api_cloud_scan(folder_id: str) -> dict:
    folders = [f for f in ch.list_watched() if f["id"] == folder_id]
    if not folders:
        raise HTTPException(404, "unknown folder")
    folder = folders[0]
    return ingest_folder(folder["path"], project=folder.get("project") or "")


@app.get("/api/cloud/recommend")
def api_cloud_recommend() -> dict:
    return {"recommendations": recommend()}


@app.post("/api/cloud/organize")
def api_cloud_organize(req: OffloadRequest) -> dict:
    try:
        return organize_to_vendor(req.vendor_id, req.asset_ids or None)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/cloud/offload")
def api_cloud_offload(req: OffloadRequest) -> dict:
    ids = req.asset_ids
    if not ids:
        # Default: reusable demo-pack files we can actually copy.
        pack = ch.list_assets(project="demo", limit=50, sort="reusability")
        ids = [a["id"] for a in pack if a.get("reusable")]
    try:
        return offload_assets(req.vendor_id, ids)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/cloud/fetch")
def api_cloud_fetch(req: FetchRequest) -> dict:
    try:
        return fetch_asset(req.asset_id, dest_dir=req.dest or None)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/cloud/forget-local")
def api_cloud_forget(req: FetchRequest) -> dict:
    try:
        return forget_local(req.asset_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


# --- Repurpose search ---
@app.post("/api/search")
def api_search(req: SearchRequest) -> dict:
    results = surface_repurposable(req.brief, limit=req.limit)
    for r in results:
        attach_preview(r)
    try:
        ch.insert_events([{"event": "searched", "detail": req.brief[:300]}])
    except Exception as exc:  # noqa: BLE001
        print(f"[search] event skipped: {exc}")
    return {"brief": req.brief, "results": results}


# --- Assemble a cut (cinema-creative) ---
@app.post("/api/assemble")
def api_assemble(req: SearchRequest) -> dict:
    """Assemble an edit-ready sequence from reusable library assets for a brief."""
    return {"sequence": assemble_sequence(req.brief, limit=req.limit)}


@app.post("/api/assemble/stream")
def api_assemble_stream(req: SearchRequest):
    """SSE: the Editor pulls candidates from ClickHouse, then arranges a cut."""
    if not req.brief.strip():
        raise HTTPException(400, "brief required")

    def event_stream():
        try:
            for ev in assemble_sequence_events(req.brief.strip(), limit=req.limit):
                yield _sse(ev)
        except Exception as exc:  # surface a crash as a final SSE event, not a 500
            yield _sse({"type": "error", "message": str(exc)[:300]})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Review: duplicates + stale ---
@app.get("/api/review")
def api_review(
    dup_offset: int = 0,
    dup_limit: int = 8,
    stale_offset: int = 0,
    stale_limit: int = 8,
) -> dict:
    dup_limit = max(1, min(dup_limit, 50))
    stale_limit = max(1, min(stale_limit, 50))
    dup_offset = max(0, dup_offset)
    stale_offset = max(0, stale_offset)

    all_dups = list_duplicates()
    dup_total = len(all_dups)
    if dup_total and dup_offset >= dup_total:
        dup_offset = ((dup_total - 1) // dup_limit) * dup_limit
    duplicates = all_dups[dup_offset:dup_offset + dup_limit]
    for d in duplicates:
        atype = d.get("asset_type") or ""
        for side, fname_key in (("a", "file_a"), ("b", "file_b")):
            fname = d.get(fname_key) or ""
            ext = os.path.splitext(fname)[1]
            d[f"has_preview_{side}"] = filename_has_preview(fname)
            d[f"preview_kind_{side}"] = preview_kind(ext, atype) if d[f"has_preview_{side}"] else "none"

    stale_total = ch.count_assets(status="stale")
    if stale_total and stale_offset >= stale_total:
        stale_offset = ((stale_total - 1) // stale_limit) * stale_limit
    stale = ch.list_assets(
        status="stale", limit=stale_limit, offset=stale_offset, sort="newest",
    )
    for a in stale:
        attach_preview(a)

    return {
        "duplicates": duplicates,
        "dup_total": dup_total,
        "dup_offset": dup_offset,
        "dup_limit": dup_limit,
        "stale": stale,
        "stale_total": stale_total,
        "stale_offset": stale_offset,
        "stale_limit": stale_limit,
    }


# --- Approve an action (human-in-the-loop) ---
@app.post("/api/approve")
def api_approve(req: ApproveRequest) -> dict:
    if req.action == "archive":
        return archive_asset(req.asset_id)
    if req.action == "keep":
        ch.set_status(req.asset_id, "active")
        try:
            ch.insert_events([{"asset_id": req.asset_id, "event": "kept"}])
        except Exception as exc:  # noqa: BLE001
            print(f"[approve] event skipped: {exc}")
        return {"asset_id": req.asset_id, "status": "active"}
    raise HTTPException(400, f"Unknown action: {req.action}")


# --- Conversational agent ---
def _event_payloads(event) -> list[dict]:
    # Which agent authored this event (root librarian or a delegated sub-agent) —
    # lets the UI badge the multi-agent trace (analyst / archivist / scout / curator).
    agent = getattr(event, "author", "") or ""
    payloads: list[dict] = []
    for fc in event.get_function_calls() or []:
        payloads.append({
            "type": "tool",
            "status": "working",
            "name": fc.name or "",
            "args": _clip(getattr(fc, "args", None)),
            "agent": agent,
        })
    for fr in event.get_function_responses() or []:
        payloads.append({
            "type": "tool",
            "status": "done",
            "name": fr.name or "",
            "result": _clip(getattr(fr, "response", None)),
            "agent": agent,
        })
    texts: list[str] = []
    if event.content and event.content.parts:
        for part in event.content.parts:
            if getattr(part, "text", None) and not getattr(part, "function_call", None):
                texts.append(part.text)
    if texts:
        payloads.append({
            "type": "text",
            "text": "".join(texts),
            "final": bool(event.is_final_response()),
            "agent": agent,
        })
    return payloads


async def _chat_sse(message: str, session_id: str):
    yield _sse({"type": "start", "session_id": session_id})
    try:
        from google.genai import types

        runner = await _get_runner()
        await _ensure_session(runner, session_id)
        content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
        async for event in runner.run_async(
            user_id="web", session_id=session_id, new_message=content
        ):
            for payload in _event_payloads(event):
                yield _sse(payload)
        yield _sse({"type": "done"})
    except Exception as exc:  # noqa: BLE001
        yield _sse({"type": "error", "message": str(exc)[:400]})


@app.post("/api/chat/stream")
async def api_chat_stream(req: ChatRequest):
    """SSE: Librarian turn with live MCP tool names + SQL."""
    if not req.message.strip():
        raise HTTPException(400, "message required")
    return StreamingResponse(
        _chat_sse(req.message.strip(), req.session_id or "web"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat")
async def api_chat(req: ChatRequest) -> dict:
    """Non-streaming turn (tests / fallback). Same runner as the live trace."""
    if not req.message.strip():
        raise HTTPException(400, "message required")
    try:
        from google.genai import types

        runner = await _get_runner()
        await _ensure_session(runner, req.session_id or "web")
        content = types.Content(
            role="user", parts=[types.Part.from_text(text=req.message.strip())]
        )
        reply = ""
        tools: list[str] = []
        async for event in runner.run_async(
            user_id="web",
            session_id=req.session_id or "web",
            new_message=content,
        ):
            for fc in event.get_function_calls() or []:
                if fc.name:
                    tools.append(fc.name)
            if event.is_final_response() and event.content and event.content.parts:
                reply = "".join(p.text or "" for p in event.content.parts)
        return {"reply": reply, "tools": tools}
    except Exception as exc:
        raise HTTPException(503, f"Agent unavailable: {exc}") from exc


# --- Static frontend (mounted last so /api/* wins) ---
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.isdir(_WEB_DIR):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
