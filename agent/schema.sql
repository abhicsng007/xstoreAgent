-- xStoreAgent ClickHouse schema (partner integration)
-- Run once against your ClickHouse Cloud instance to provision the asset catalog.

CREATE DATABASE IF NOT EXISTS xstoreagent;

CREATE TABLE IF NOT EXISTS xstoreagent.assets
(
    id            UUID DEFAULT generateUUIDv4(),
    path          String,                         -- absolute source path
    filename      String,
    asset_type    LowCardinality(String),         -- video | image | icon | vector | audio | document | other
    ext           LowCardinality(String),
    size_bytes    UInt64,
    created_at     DateTime DEFAULT now(),
    project       String DEFAULT '',              -- project the asset originated from
    caption       String DEFAULT '',              -- Gemini multimodal caption
    tags          Array(String) DEFAULT [],
    reusable      Bool DEFAULT true,              -- generic/repurposable vs project-specific
    status        LowCardinality(String) DEFAULT 'active',  -- active | duplicate | stale | archived
    content_hash  String DEFAULT '',              -- sha256 for exact-dup guard
    embedding     Array(Float32) DEFAULT []       -- multimodal embedding vector
)
ENGINE = MergeTree
ORDER BY (asset_type, created_at);

-- Repurpose search (brief -> assets), lower cosineDistance = closer match:
--   SELECT id, filename, asset_type, caption, cosineDistance(embedding, {vec:Array(Float32)}) AS dist
--   FROM xstoreagent.assets
--   WHERE status != 'archived' AND length(embedding) > 0
--   ORDER BY dist ASC
--   LIMIT 12;

-- Near-duplicate detection uses pairwise cosineDistance(embedding_a, embedding_b) < 0.05.
