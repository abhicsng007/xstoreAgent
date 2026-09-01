"""classify_asset: Gemini multimodal captioning + reusability verdict.

For each asset we ask Gemini for a compact JSON record: a one-line caption,
searchable tags, a refined sub-type (disambiguating icon vs image vs vector),
and a *reusability verdict* — the judgement that drives the archive/keep flow.

Design notes:
  - Only image/vector/icon files are sent as inline image bytes. Video is
    described from its filename + a caption we get cheaply (a full video pass is
    reserved for embed.py's sampled segment) to keep latency bounded.
  - Audio/document assets are classified from filename + light context only.
  - The call uses structured output (response_schema) so we always get valid JSON.
"""
from __future__ import annotations

import functools
import json
import mimetypes
import os

from ..config import get_settings

# Assets we send to Gemini as actual pixels for a visual verdict.
_VISUAL = {"image", "icon", "vector"}
# Vector formats we can't rasterize inline (ai/eps) fall back to filename-only.
_INLINE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

_SCHEMA = {
    "type": "object",
    "properties": {
        "caption": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "asset_subtype": {
            "type": "string",
            "enum": ["photo", "icon", "logo", "vector_art", "screenshot",
                     "b_roll", "vfx_plate", "sfx", "music", "dialogue",
                     "document", "other"],
        },
        "reusable": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["caption", "tags", "asset_subtype", "reusable", "reason"],
}

_SYSTEM = """You are an asset librarian for a film/video production team.
Given a media asset, return JSON describing it for a reusable-asset catalog.

Set `reusable` = true for GENERIC, repurposable material: stock/B-roll, logos,
icons, reusable SFX, music beds, background plates, brand vectors.
Set `reusable` = false for PROJECT-SPECIFIC or throwaway material: clapper/slate
frames, rough cuts, dailies, on-set reference photos, versioned exports (v1/v2),
screen recordings of one-off reviews.

`caption`: one vivid line describing the content (what a searcher would type to
find it). `tags`: 3-8 lowercase keywords (subject, mood, setting, color, motion).
`reason`: one short clause justifying the reusable verdict."""


@functools.lru_cache
def _client():
    """Lazy GenAI client (Vertex-backed). No credentials needed just to import."""
    from google import genai

    s = get_settings()
    if s.use_vertexai:
        return genai.Client(vertexai=True, project=s.gcp_project, location=s.gcp_location)
    return genai.Client()


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def classify_asset(path: str, asset_type: str, ext: str) -> dict:
    """Return a classification dict merged onto the scan.py record.

    Keys: caption, tags, asset_subtype, reusable, reason. On any failure returns
    safe defaults (empty caption, reusable=True) so ingestion never blocks.
    """
    from google.genai import types

    filename = os.path.basename(path)
    parts: list = []

    send_pixels = asset_type in _VISUAL and ext.lower() in _INLINE_IMAGE_EXTS
    if send_pixels:
        try:
            with open(path, "rb") as fh:
                parts.append(types.Part.from_bytes(data=fh.read(), mime_type=_guess_mime(path)))
        except OSError:
            send_pixels = False

    hint = (
        f"Asset filename: {filename}\n"
        f"Coarse type: {asset_type}\n"
        + ("The image bytes are attached." if send_pixels
           else "No pixels available; infer from filename and type.")
    )
    parts.append(types.Part.from_text(text=hint))

    try:
        from ..retry import with_retry

        resp = with_retry(lambda: _client().models.generate_content(
            model=get_settings().gemini_model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                temperature=0.2,
            ),
        ))
        data = json.loads(resp.text)
    except Exception as exc:
        print(f"[classify] fallback for {filename}: {exc}")
        return {
            "caption": os.path.splitext(filename)[0].replace("_", " "),
            "tags": [asset_type],
            "asset_subtype": "other",
            "reusable": True,
            "reason": "classification unavailable; defaulted to reusable",
        }

    # Refine coarse type for flagged files: an "image" that is really an icon/logo.
    subtype = data.get("asset_subtype", "other")
    data["refined_type"] = {
        "icon": "icon", "logo": "vector", "vector_art": "vector",
    }.get(subtype, asset_type)
    return data


if __name__ == "__main__":
    import sys

    p = sys.argv[1]
    print(json.dumps(classify_asset(p, "image", os.path.splitext(p)[1]), indent=2))
