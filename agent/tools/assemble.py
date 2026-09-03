"""assemble_sequence: turn the reusable library into an edit-ready cut.

This is the creator-facing step — not "here's a list of assets" but "here's a
sequence." Given a brief, we retrieve the best-matching reusable assets from
ClickHouse (caption-embedding search, the same path the dashboard uses) and ask
Gemini to arrange them into an ordered shot list mapped to story beats
(hook → establish → product → proof → CTA), each shot with a suggested duration,
what happens on screen, and WHY that asset fits — plus the gaps the team still
needs to shoot. It only ever references assets that are actually in the library.

`assemble_sequence(brief)` returns the finished sequence (used as the Editor
agent's tool). `assemble_sequence_events(brief)` streams the same work as a live
reasoning trace for the UI, matching the ingest/scout event shape.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

from .. import clickhouse_client as ch
from ..config import get_settings
from .classify import _client  # reuse the lazy Vertex GenAI client
from .embed import embed_text

# The Editor sub-agent (matches the ingest/scout event shape for the UI).
EDITOR = ("Editor", "✂️")  # ✂️

_SEQUENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "beat": {"type": "string"},
                    "asset_id": {"type": "string"},
                    "duration_sec": {"type": "number"},
                    "action": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["order", "beat", "asset_id", "duration_sec", "action", "why"],
            },
        },
        "music": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string"},
                "why": {"type": "string"},
            },
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "need": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["need", "suggestion"],
            },
        },
    },
    "required": ["title", "logline", "shots", "gaps"],
}

_SYSTEM = """You are the Editor for a film/video team. You cut a short video from a
library of REUSABLE assets the team already owns. You are given a brief and a list
of candidate assets (each with an id, type, caption, tags, and a match score).

Build a tight, watchable sequence:
- Order shots into story beats: hook, establish, product/subject, proof, cta
  (use the beats that fit; a 20-40s ad rarely needs all of them).
- For each shot pick ONE candidate by its exact asset_id, give a duration in
  seconds, one line of on-screen action, and WHY that asset fits (cite its caption).
- Pick a music/audio bed from the candidates if one fits (music object).
- Only reference asset_id values from the candidate list. Never invent assets.
- gaps: what the brief still needs that the library does NOT cover — each with a
  concrete shoot/source suggestion. Be honest; an empty library is mostly gaps."""


def _candidates(brief: str, limit: int = 16) -> list[dict]:
    """Best-matching reusable assets for the brief (ClickHouse caption search)."""
    vec = embed_text(brief)
    if not vec:
        return []
    rows = ch.repurpose_search(vec, limit=limit)
    for r in rows:
        r["match_score"] = round(max(0.0, 1.0 - float(r.get("distance", 1.0))) * 100)
    return rows


def _prompt(brief: str, candidates: list[dict]) -> str:
    lines = [
        f"[{c['match_score']}%] id={c.get('id')} · {c.get('asset_type')} · "
        f"{c.get('caption') or c.get('filename')} · tags={','.join(c.get('tags') or [])}"
        for c in candidates
    ]
    catalog = "\n".join(lines) if lines else "(the library is empty)"
    return f"Brief: {brief}\n\nCandidate assets:\n{catalog}\n\nAssemble the sequence."


def _enrich(seq: dict, candidates: list[dict]) -> dict:
    """Join model output back to real asset rows by id (filename, type, caption)."""
    by_id = {str(c.get("id")): c for c in candidates}
    for shot in seq.get("shots", []) or []:
        c = by_id.get(str(shot.get("asset_id", "")))
        if c:
            shot["filename"] = c.get("filename", "")
            shot["asset_type"] = c.get("asset_type", "")
            shot["caption"] = c.get("caption", "")
            shot["match_score"] = c.get("match_score")
    music = seq.get("music") or {}
    if music.get("asset_id"):
        c = by_id.get(str(music["asset_id"]))
        if c:
            music["filename"] = c.get("filename", "")
            music["asset_type"] = c.get("asset_type", "")
            music["caption"] = c.get("caption", "")
    # Keep shots ordered and drop any that failed to resolve to a real asset.
    seq["shots"] = sorted(
        [s for s in (seq.get("shots") or []) if s.get("filename")],
        key=lambda s: s.get("order", 0),
    )
    return seq


def assemble_sequence(brief: str, limit: int = 16) -> dict:
    """Assemble an edit-ready sequence from reusable library assets for a brief.

    Args:
        brief: what the creator is making (e.g. "30s upbeat city product ad").
        limit: how many candidate assets to consider.

    Returns:
        A dict with title, logline, ordered shots (each mapped to a real asset and
        a story beat), an optional music bed, and honest gaps to still shoot.
    """
    from google.genai import types

    candidates = _candidates(brief, limit=limit)
    resp = _client().models.generate_content(
        model=get_settings().gemini_model,
        contents=[types.Content(role="user", parts=[types.Part.from_text(text=_prompt(brief, candidates))])],
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
            response_schema=_SEQUENCE_SCHEMA,
            temperature=0.4,
        ),
    )
    try:
        seq = json.loads(resp.text)
    except (json.JSONDecodeError, TypeError):
        seq = {"title": "", "logline": "", "shots": [], "gaps": []}
    seq = _enrich(seq, candidates)
    seq["brief"] = brief
    seq["candidates_considered"] = len(candidates)
    try:
        ch.insert_events([{"event": "assembled", "detail": brief[:300],
                           "bytes": len(seq.get("shots", []))}])
    except Exception as exc:  # noqa: BLE001 — non-critical analytics write
        print(f"[assemble] event skipped: {exc}")
    return seq


def _step(status: str, title: str, detail: str = "", data: dict | None = None) -> dict:
    name, icon = EDITOR
    return {"type": "step", "agent": name, "icon": icon, "status": status,
            "title": title, "detail": detail, "data": data or {}}


def assemble_sequence_events(brief: str, limit: int = 16) -> Iterator[dict]:
    """Stream the Editor assembling a cut (candidate retrieval → arrange → sequence)."""
    yield {"type": "start", "brief": brief}
    yield _step("working", "Pulling candidates from ClickHouse",
                "Ranking reusable assets against the brief by caption embedding…")
    candidates = _candidates(brief, limit=limit)
    yield _step("done", f"Found {len(candidates)} candidate assets",
                "Top matches: " + ", ".join(c.get("filename", "") for c in candidates[:4])
                if candidates else "Library is empty — the cut will be mostly gaps.",
                data={"count": len(candidates)})

    yield _step("working", "Arranging a sequence with Gemini",
                "Mapping shots to beats — hook, establish, product, proof, CTA…")
    seq = assemble_sequence(brief, limit=limit)
    yield _step("done", f"Cut assembled: {len(seq.get('shots', []))} shots",
                seq.get("logline", ""), data={"shots": len(seq.get("shots", [])),
                                               "gaps": len(seq.get("gaps", []))})
    yield {"type": "done", "sequence": seq}
