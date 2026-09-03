"""classify_asset: Gemini multimodal captioning + reusability verdict.

For each asset we ask Gemini for a compact JSON record: a one-line caption,
searchable tags, a refined sub-type (disambiguating icon vs image vs vector),
and a *reusability verdict* — the judgement that drives the archive/keep flow.

Design notes:
  - Image/vector/icon files are sent as inline image bytes.
  - Video and audio are sent as inline media bytes too, so Gemini actually WATCHES
    the clip / HEARS the audio and captions from content — not from the filename.
    Gemini natively samples video frames and the audio track. Short sample clips
    fit inline; a file above the inline cap (or unreadable, or a byte-stub) falls
    back to filename-only so ingest never blocks and stays cheap at scale.
  - Document assets are classified from filename + light context only.
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
# Time-based media we send to Gemini so it watches/hears the real content.
_TIME_MEDIA = {"video", "audio"}
# Inline request cap. Vertex accepts media inline up to ~20 MB total; stay under it.
# Larger files fall back to filename-only (rare for short sample clips).
_INLINE_MEDIA_MAX = 18 * 1024 * 1024
# Below this a file is a placeholder byte-stub, not real media — don't send it.
_MEDIA_MIN_BYTES = 1024

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

When video or audio bytes are attached, describe what you actually SEE and HEAR
(motion, subject, setting, and for audio the sound itself) — not the filename.

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

    # Send real video/audio bytes so Gemini watches/hears the clip. Only for
    # readable, non-stub files under the inline cap — otherwise filename fallback.
    send_media = False
    if not send_pixels and asset_type in _TIME_MEDIA:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if _MEDIA_MIN_BYTES <= size <= _INLINE_MEDIA_MAX:
            try:
                with open(path, "rb") as fh:
                    parts.append(types.Part.from_bytes(data=fh.read(), mime_type=_guess_mime(path)))
                send_media = True
            except OSError:
                send_media = False

    if send_pixels:
        attached = "The image bytes are attached."
    elif send_media:
        kind = "video" if asset_type == "video" else "audio"
        attached = f"The {kind} bytes are attached — describe what you see/hear."
    else:
        attached = "No media available; infer from filename and type."
    hint = f"Asset filename: {filename}\nCoarse type: {asset_type}\n{attached}"
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
