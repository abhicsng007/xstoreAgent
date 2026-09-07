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
from .cloud import VENDOR_PRESETS


def _vendor_key(name: str) -> str:
    n = (name or "").lower().replace(" ", "")
    for p in VENDOR_PRESETS:
        key = p["vendor"]
        label = p["name"].lower().replace(" ", "")
        if key in n or label in n or n in label:
            return key
    if "google" in n or "drive" in n:
        return "gdrive"
    if "one" in n:
        return "onedrive"
    return "custom"

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
            "vendor": _vendor_key(str(r["name"])),
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
    """Current library usage vs the plan cap, for the storage meter.

    Resilient: if the catalog is briefly unreachable the meter (and the Scout's
    web search) degrade gracefully instead of crashing — `available` says which.
    """
    s = get_settings()
    plan_bytes = s.storage_plan_gb * _GB
    try:
        overview = ch.library_overview()
        used_bytes = sum(int(r.get("bytes", 0) or 0) for r in overview)
        available = True
    except Exception:  # noqa: BLE001 — catalog offline; keep the feature usable
        used_bytes = 0
        available = False
    pct = round(used_bytes / plan_bytes * 100, 1) if plan_bytes else 0.0
    over_bytes = max(used_bytes - plan_bytes, 0)
    return {
        "used_bytes": used_bytes,
        "plan_gb": s.storage_plan_gb,
        "used_pct": pct,
        "over_bytes": over_bytes,
        "warn_pct": s.storage_warn_pct,
        "over_threshold": available and pct >= s.storage_warn_pct,
        "available": available,
    }


def _gb(nbytes: float) -> str:
    """Human GB/TB label."""
    gb = nbytes / _GB
    return f"{gb / 1024:.2f} TB" if gb >= 1024 else f"{gb:.1f} GB"


def _offload_plan(status: dict, provider: dict) -> dict:
    """Tie the top web result back to the catalog: what offloading actually clears.

    Reads the reusable, still-local footprint from ClickHouse and measures the
    provider's free tier against the real overage — the Scout's concrete proposal.
    """
    try:
        foot = ch.reusable_footprint()
    except Exception:  # noqa: BLE001
        foot = {"count": 0, "bytes": 0}
    free_bytes = float(provider.get("free_gb") or 0) * _GB
    movable = min(foot["bytes"], free_bytes) if free_bytes else foot["bytes"]
    over = status.get("over_bytes", 0)
    clears_pct = round(min(movable / over * 100, 100), 0) if over else 0
    plan = {
        "provider": provider.get("name", ""),
        "free_gb": provider.get("free_gb", 0),
        "reusable_count": foot["count"],
        "reusable_bytes": foot["bytes"],
        "movable_bytes": int(movable),
        "over_bytes": int(over),
        "clears_pct": clears_pct,
    }
    if not status.get("available"):
        plan["headline"] = (
            f"When the catalog is back, offload reusable media into "
            f"{plan['provider']}'s {plan['free_gb']:.0f} GB free tier."
        )
    elif over > 0:
        tail = (" Connect more free tiers to clear the rest."
                if clears_pct < 100 else "")
        plan["headline"] = (
            f"Move ~{_gb(movable)} of your {_gb(foot['bytes'])} reusable pool "
            f"({foot['count']} assets) into {plan['provider']}'s "
            f"{plan['free_gb']:.0f} GB free tier — clears {clears_pct:.0f}% of your "
            f"{_gb(over)} overage.{tail}"
        )
    else:
        plan["headline"] = (
            f"{_gb(foot['bytes'])} across {foot['count']} reusable assets could move "
            f"to {plan['provider']} to stay ahead of the cap."
        )
    return plan


def _step(status: str, title: str, detail: str = "", data: dict | None = None) -> dict:
    name, icon = SCOUT
    return {"type": "step", "agent": name, "icon": icon, "status": status,
            "title": title, "detail": detail, "data": data or {}}


def scout_storage_events() -> Iterator[dict]:
    """Stream the Scout's reasoning while it assesses storage and searches the web."""
    yield {"type": "start"}
    st = storage_status()
    plan_h = _gb(st["plan_gb"] * _GB)
    if not st.get("available"):
        yield _step("info", "Catalog usage unavailable",
                    "Couldn't read the library right now — searching the web for "
                    "free storage anyway so you have options ready.", data=st)
    else:
        used_h = f"{_gb(st['used_bytes'])} of {plan_h}"
        yield _step("done", f"Storage at {st['used_pct']:.0f}% of plan",
                    f"{used_h} used. "
                    + ("Over the safety threshold — time to find more room."
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
            i["vendor"] = _vendor_key(i.get("name", ""))
        yield _step("done", f"Surfaced {len(items)} known free tiers",
                    "Live search returned nothing usable; showing a curated fallback.",
                    data={"count": len(items)})

    top = items[0]
    yield _step("done", f"Recommendation: {top['name']} — {top['free_gb']:.0f} GB free",
                f"{top['note']}", data={"pick": top})

    plan = _offload_plan(st, top)
    yield _step("done", "Offload plan ready", plan["headline"], data={"plan": plan})

    yield {"type": "done", "status": st, "options": items, "plan": plan,
           "queries": queries, "grounded": bool(queries or (items and items[0].get("source") == "web"))}


def find_free_storage() -> dict:
    """Non-streaming: run the Scout and return {status, options, grounded}."""
    result: dict = {"options": []}
    for ev in scout_storage_events():
        if ev.get("type") == "done":
            result = {k: v for k, v in ev.items() if k != "type"}
    return result
