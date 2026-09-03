"""Embeddings for xStoreAgent.

Search vector (embed_text / embed_asset): the dedicated `gemini-embedding-001`
text model embeds each asset's Gemini caption and every project brief into one
consistent space. Because Gemini's vision already described each asset in its
caption, a text brief retrieves the right video / image / audio / vector by
MEANING — cross-modal search without the multimodal "modality gap" that skews
raw image-vs-text distances.

Dedup vector (embed_image / embed_video): Vertex `multimodalembedding@001`
(1408-dim) gives true visual-similarity embeddings used for near-duplicate
detection. Both embedding families run from a regional endpoint (EMBEDDING_LOCATION),
since neither is served from Gemini's "global" location.
"""
from __future__ import annotations

import functools

from ..config import get_settings

EMBED_DIM = 1408  # multimodalembedding@001 output dimensionality (image/video, dedup)


@functools.lru_cache
def _model():
    """Lazy-load the Vertex multimodal model (image/video embeddings for dedup)."""
    import vertexai
    from vertexai.vision_models import MultiModalEmbeddingModel

    s = get_settings()
    # Regional endpoint — multimodalembedding@001 is not served from "global".
    vertexai.init(project=s.gcp_project, location=s.embedding_location)
    return MultiModalEmbeddingModel.from_pretrained(s.mm_embedding_model)


@functools.lru_cache
def _text_client():
    """Lazy GenAI client for the dedicated text embedder (gemini-embedding-001)."""
    from google import genai

    s = get_settings()
    if s.use_vertexai:
        # gemini-embedding-001 is served regionally, not from "global".
        return genai.Client(vertexai=True, project=s.gcp_project, location=s.embedding_location)
    return genai.Client()


def embed_text(text: str) -> list[float]:
    """Embed free text (a project brief, or an asset caption) for semantic search.

    Uses the dedicated gemini-embedding-001 text model — much stronger at
    discriminating short descriptive text than the multimodal model's text tower,
    so briefs match the right captions sharply. This is the vector stored for every
    asset (its caption) and computed for every brief, keeping both sides in one
    consistent space.
    """
    if not text.strip():
        return []
    from ..retry import with_retry

    resp = with_retry(lambda: _text_client().models.embed_content(
        model=get_settings().text_embedding_model,
        contents=text[:2048],
    ))
    return list(resp.embeddings[0].values or [])


def embed_image(path: str, contextual_text: str = "") -> list[float]:
    from vertexai.vision_models import Image

    from ..retry import with_retry

    embeddings = with_retry(lambda: _model().get_embeddings(
        image=Image.load_from_file(path),
        contextual_text=contextual_text[:1024] or None,
        dimension=EMBED_DIM,
    ))
    return list(embeddings.image_embedding or [])


def embed_video(path: str, contextual_text: str = "") -> list[float]:
    """Embed a video. multimodalembedding returns per-segment vectors; we take the
    first segment as the asset-level embedding (sample cost stays bounded)."""
    from vertexai.vision_models import Video, VideoSegmentConfig

    from ..retry import with_retry

    embeddings = with_retry(lambda: _model().get_embeddings(
        video=Video.load_from_file(path),
        video_segment_config=VideoSegmentConfig(end_offset_sec=8),
        contextual_text=contextual_text[:1024] or None,
        dimension=EMBED_DIM,
    ))
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
