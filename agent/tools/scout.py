"""The Scout: finds free cloud storage on the web as the library fills up.

When the catalogued library approaches its storage-plan cap, the Scout agent runs
a live Google Search (via Gemini grounding) for cloud providers with a free tier,
normalizes the results into ranked options (name, free GB, note, signup URL), and
streams its reasoning the same way ingestion does — so you watch the agent decide
it's running low, search the web, and surface where to offload.

`scout_storage_events()` yields the reasoning trace; `find_free_storage()` drains
it to the ranked list. If the grounded search is unavailable, a curated fallback
of well-known free tiers keeps the feature working (each result is tagged with its
`source` so "web" vs "fallback" is always honest).
"""
from __future__ import annotations

import functools
import json
import re
from collections.abc import Iterator

from .. import clickhouse_client as ch
from ..config import get_settings

# The Scout sub-agent (matches the ingest crew's event shape).
SCOUT = ("Scout", "\U0001F6F0")  # 🛰️

_GB = 1024 ** 3

# Well-known free tiers, used only when the live web search can't run. Ordered by
# free capacity. Kept deliberately short and generic; the live search supersedes it.
_FALLBACK: list[dict] = [
    {"name": "MEGA", "free_gb": 20, "note": "generous free tier, good for media", "url": "https://mega.io"},
    {"name": "Google Drive", "free_gb": 15, "note": "shared with Gmail/Photos", "url": "https://drive.google.com"},
    {"name": "pCloud", "free_gb": 10, "note": "media streaming, lifetime option", "url": "https://www.pcloud.com"},
    {"name": "Icedrive", "free_gb": 10, "note": "clean apps, encrypted", "url": "https://icedrive.net"},
    {"name": "Internxt", "free_gb": 10, "note": "open-source, encrypted", "url": "https://internxt.com"},
    {"name": "Microsoft OneDrive", "free_gb": 5, "note": "Office integration", "url": "https://onedrive.live.com"},
    {"name": "Dropbox", "free_gb": 2, "note": "reliable sync, small free tier", "url": "https://www.dropbox.com"},
]

_SEARCH_PROMPT = (
    "Search the web for cloud storage providers that offer a FREE tier suitable "
    "for storing media assets (video, images, audio). For each provider give its "
    "name, the free storage in GB, a short note on suitability for large media, "
    "and the signup URL. Return ONLY a JSON array of 5-7 objects with keys: "
    '"name" (string), "free_gb" (number), "note" (<=12 words), "url" (string). '
    "Prefer current, well-known providers. No prose outside the JSON."
)


@functools.lru_cache
def _client():
    from google import genai

    s = get_settings()
    if s.use_vertexai:
        return genai.Client(vertexai=True, project=s.gcp_project, location=s.gcp_location)
    return genai.Client()


def _parse_items(text: str) -> list[dict]:
    """Pull the first JSON array out of a grounded response and normalize it."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    items: list[dict] = []
    for r in raw:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        try:
            gb = float(r.get("free_gb", 0) or 0)
        except (TypeError, ValueError):
            gb = 0.0
        items.append({
            "name": str(r["name"])[:60],
            "free_gb": round(gb, 1),
            "note": str(r.get("note", ""))[:80],
            "url": str(r.get("url", ""))[:200],
            "source": "web",
        })
    items.sort(key=lambda i: i["free_gb"], reverse=True)
    return items


def _grounded_search() -> tuple[list[dict], list[str]]:
    """Run a real Google Search via Gemini grounding. Returns (items, queries)."""
    from google.genai import types

    s = get_settings()
    tools = [types.Tool(google_search=types.GoogleSearch())]
    resp = _client().models.generate_content(
        model=s.gemini_model,
        contents=[types.Content(role="user", parts=[types.Part.from_text(text=_SEARCH_PROMPT)])],
        config=types.GenerateContentConfig(tools=tools, temperature=0.2),
    )
    # Surface the actual search queries Gemini issued (proof it hit the web).
    queries: list[str] = []
    try:
        meta = resp.candidates[0].grounding_metadata
        queries = list(getattr(meta, "web_search_queries", None) or [])
    except (AttributeError, IndexError, TypeError):
        pass
    return _parse_items(resp.text or ""), queries


def storage_status() -> dict:
    """Current library usage vs the plan cap, for the storage meter."""
    s = get_settings()
    overview = ch.library_overview()
    used_bytes = sum(int(r.get("bytes", 0) or 0) for r in overview)
    plan_bytes = s.storage_plan_gb * _GB
    pct = round(used_bytes / plan_bytes * 100, 1) if plan_bytes else 0.0
    return {
        "used_bytes": used_bytes,
        "plan_gb": s.storage_plan_gb,
        "used_pct": pct,
        "warn_pct": s.storage_warn_pct,
        "over_threshold": pct >= s.storage_warn_pct,
    }


def _step(status: str, title: str, detail: str = "", data: dict | None = None) -> dict:
    name, icon = SCOUT
    return {"type": "step", "agent": name, "icon": icon, "status": status,
            "title": title, "detail": detail, "data": data or {}}


def scout_storage_events() -> Iterator[dict]:
    """Stream the Scout's reasoning while it assesses storage and searches the web."""
    yield {"type": "start"}
    st = storage_status()
    used_h = f"{st['used_bytes'] / _GB:.2f} GB of {st['plan_gb']:.0f} GB"
    yield _step("done", f"Storage at {st['used_pct']}% of plan",
                f"{used_h} used. "
                + ("Approaching the cap — time to find more room."
                   if st["over_threshold"]
                   else "Planning ahead so the library never stalls."),
                data=st)

    yield _step("working", "Searching the web for free cloud storage",
                "Running a live Google Search for providers with a free tier…")

    items: list[dict] = []
    queries: list[str] = []
    try:
        items, queries = _grounded_search()
    except Exception as exc:  # grounding unavailable — fall back, stay honest
        yield _step("info", "Live search unavailable — using known free tiers", str(exc)[:160])

    if items:
        q = (" · queries: " + "; ".join(queries[:3])) if queries else ""
        yield _step("done", f"Found {len(items)} providers on the web",
                    f"Ranked by free capacity{q}.", data={"count": len(items)})
    else:
        items = [dict(i) for i in _FALLBACK]
        for i in items:
            i["source"] = "fallback"
        yield _step("done", f"Surfaced {len(items)} known free tiers",
                    "Live search returned nothing usable; showing a curated fallback.",
                    data={"count": len(items)})

    top = items[0]
    yield _step("done", f"Recommendation: {top['name']} — {top['free_gb']:.0f} GB free",
                f"{top['note']}", data={"pick": top})

    yield {"type": "done", "status": st, "options": items,
           "queries": queries, "grounded": bool(queries or (items and items[0].get("source") == "web"))}


def find_free_storage() -> dict:
    """Non-streaming: run the Scout and return {status, options, grounded}."""
    result: dict = {"options": []}
    for ev in scout_storage_events():
        if ev.get("type") == "done":
            result = {k: v for k, v in ev.items() if k != "type"}
    return result
