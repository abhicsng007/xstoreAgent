"""xStoreAgent FastAPI server.

Exposes the Librarian's actions as a small REST API for the web dashboard and
serves the static frontend. The dashboard endpoints call the underlying tool
functions directly (deterministic, snappy); `/chat` runs the full ADK agent for
the conversational demo.

Run locally:  uvicorn server.app:app --reload
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import clickhouse_client as ch
from agent.librarian import (
    archive_asset,
    library_stats,
    list_duplicates,
    surface_repurposable,
)
from agent.tools.ingest import ingest_folder

app = FastAPI(title="xStoreAgent", description="AI Asset Librarian for film/video teams")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request models ---
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


# --- Health ---
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "xstoreagent"}


# --- Ingest ---
@app.post("/api/ingest")
def api_ingest(req: IngestRequest) -> dict:
    if not os.path.isdir(req.root):
        raise HTTPException(400, f"Not a folder: {req.root}")
    return ingest_folder(req.root, project=req.project, limit=req.limit)


# --- Library (dashboard) ---
@app.get("/api/library")
def api_library() -> dict:
    return {"overview": library_stats()}


@app.get("/api/assets")
def api_assets(asset_type: str | None = None, status: str | None = None, limit: int = 200) -> dict:
    return {"assets": ch.list_assets(asset_type=asset_type, status=status, limit=limit)}


# --- Repurpose search ---
@app.post("/api/search")
def api_search(req: SearchRequest) -> dict:
    return {"brief": req.brief, "results": surface_repurposable(req.brief, limit=req.limit)}


# --- Review: duplicates + stale ---
@app.get("/api/review")
def api_review() -> dict:
    return {
        "duplicates": list_duplicates(),
        "stale": ch.list_assets(status="stale", limit=200),
    }


# --- Approve an action (human-in-the-loop) ---
@app.post("/api/approve")
def api_approve(req: ApproveRequest) -> dict:
    if req.action == "archive":
        return archive_asset(req.asset_id)
    if req.action == "keep":
        ch.set_status(req.asset_id, "active")
        return {"asset_id": req.asset_id, "status": "active"}
    raise HTTPException(400, f"Unknown action: {req.action}")


# --- Conversational agent (demo) ---
@app.post("/api/chat")
async def api_chat(req: ChatRequest) -> dict:
    """Run the ADK Librarian agent for one user turn. Optional: requires ADK +
    credentials. Returns the agent's final text response."""
    try:
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        from agent.librarian import build_agent

        runner = InMemoryRunner(agent=build_agent(), app_name="xstoreagent")
        await runner.session_service.create_session(
            app_name="xstoreagent", user_id="web", session_id=req.session_id
        )
        content = types.Content(role="user", parts=[types.Part.from_text(text=req.message)])
        reply = ""
        async for event in runner.run_async(
            user_id="web", session_id=req.session_id, new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                reply = "".join(p.text or "" for p in event.content.parts)
        return {"reply": reply}
    except Exception as exc:
        raise HTTPException(503, f"Agent unavailable: {exc}")


# --- Static frontend (mounted last so /api/* wins) ---
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
