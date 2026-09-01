"""embed_asset / embed_text: multimodal embeddings in one shared vector space.

Uses Vertex AI `multimodalembedding@001` (1408-dim), which maps images, video,
and text into the SAME space. That is the core trick behind repurpose search: a
plain-text project brief embeds into the same space as the media, so
`cosineDistance(brief_vec, asset_vec)` retrieves a *video clip* from a *text*
query.

Audio and document assets have no native multimodal embedding, so we embed their
Gemini-generated caption/text as contextual text — still landing in the shared
1408-d space, so cross-modal search keeps working.
"""
from __future__ import annotations

import functools

from ..config import get_settings

EMBED_DIM = 1408  # multimodalembedding@001 default output dimensionality


@functools.lru_cache
def _model():
    """Lazy-load the Vertex model so importing this module needs no credentials."""
    import vertexai
    from vertexai.vision_models import MultiModalEmbeddingModel

    s = get_settings()
    # Regional endpoint — multimodalembedding@001 is not served from "global".
    vertexai.init(project=s.gcp_project, location=s.embedding_location)
    return MultiModalEmbeddingModel.from_pretrained(s.mm_embedding_model)


def embed_text(text: str) -> list[float]:
    """Embed free text (a project brief, or an asset caption) into the shared space."""
    if not text.strip():
        return []
    embeddings = _model().get_embeddings(contextual_text=text[:1024], dimension=EMBED_DIM)
    return list(embeddings.text_embedding or [])


def embed_image(path: str, contextual_text: str = "") -> list[float]:
    from vertexai.vision_models import Image

    embeddings = _model().get_embeddings(
        image=Image.load_from_file(path),
        contextual_text=contextual_text[:1024] or None,
        dimension=EMBED_DIM,
    )
    return list(embeddings.image_embedding or [])


def embed_video(path: str, contextual_text: str = "") -> list[float]:
    """Embed a video. multimodalembedding returns per-segment vectors; we take the
    first segment as the asset-level embedding (sample cost stays bounded)."""
    from vertexai.vision_models import Video, VideoSegmentConfig

    embeddings = _model().get_embeddings(
        video=Video.load_from_file(path),
        video_segment_config=VideoSegmentConfig(end_offset_sec=8),
        contextual_text=contextual_text[:1024] or None,
        dimension=EMBED_DIM,
    )
    segments = embeddings.video_embeddings or []
    if segments:
        return list(segments[0].embedding)
    # Fall back to the caption/text embedding if no video vector came back.
    return embed_text(contextual_text) if contextual_text else []


def embed_asset(asset_type: str, path: str, caption: str = "") -> list[float]:
    """Embed an asset's Gemini caption for search.

    We embed the *caption text* (not raw pixels) uniformly for every asset type.
    Gemini's vision already looked at the asset and wrote a rich caption, so the
    caption carries the visual meaning into text. Embedding captions keeps every
    asset in ONE consistent text region of the space, avoiding the multimodal
    "modality gap" where a text brief unfairly favours text-caption assets over
    image-embedding assets. Result: a text brief retrieves the right video, image,
    audio or vector by meaning, ranked intuitively.

    (embed_image / embed_video remain available for visual-similarity dedup.)

    Returns [] if embedding is unavailable; the caller stores the row anyway so
    metadata/type filters still work.
    """
    try:
        return embed_text(caption or asset_type)
    except Exception as exc:  # keep ingestion resilient to one bad file
        print(f"[embed] skipped {path}: {exc}")
        return []
