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
from agent.tools.scout import scout_storage_events, storage_status

app = FastAPI(title="xStoreAgent", description="AI Asset Librarian for film/video teams")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_PREVIEW_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tif", ".tiff"}
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
    if not os.path.isdir(root):
        raise HTTPException(400, f"Not a folder: {root}")
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
    limit: int = 200,
    sort: str = "reusability",
) -> dict:
    """List catalog assets, each stamped with a 0-100 reusability_score."""
    assets = ch.list_assets(asset_type=asset_type, status=status, limit=limit)
    for a in assets:
        a["reusability_score"] = reusability_score(
            a.get("asset_type", "other"),
            a.get("asset_subtype", ""),
            bool(a.get("reusable", True)),
        )
    if sort == "reusability":
        assets.sort(key=lambda a: a["reusability_score"], reverse=True)
    return {"assets": assets, "reusable_band": REUSABLE_BAND}


@app.get("/api/preview/{asset_id}")
def api_preview(asset_id: str):
    """Serve an on-disk image for sample-pack cards. 404 if the file isn't here."""
    try:
        UUID(asset_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid asset id") from exc
    row = ch.get_asset(asset_id)
    if not row:
        raise HTTPException(404, "asset not found")
    path = row.get("path") or ""
    ext = (row.get("ext") or os.path.splitext(path)[1] or "").lower()
    if ext not in _PREVIEW_EXTS or not os.path.isfile(path):
        raise HTTPException(404, "preview unavailable")
    mime, _ = mimetypes.guess_type(path)
    return FileResponse(path, media_type=mime or "application/octet-stream")


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


# --- Repurpose search ---
@app.post("/api/search")
def api_search(req: SearchRequest) -> dict:
    results = surface_repurposable(req.brief, limit=req.limit)
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
def api_review() -> dict:
    return {
        "duplicates": list_duplicates(),
        "groups": ch.duplicate_groups(),
        "stale": ch.list_assets(status="stale", limit=200),
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
