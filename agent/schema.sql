-- xStoreAgent ClickHouse schema (partner integration)
-- Run once against your ClickHouse Cloud instance to provision the catalog.
-- ensure_schema() also applies this on boot.

CREATE DATABASE IF NOT EXISTS xstoreAgent;

CREATE TABLE IF NOT EXISTS xstoreAgent.assets
(
    id            UUID DEFAULT generateUUIDv4(),
    path          String,                         -- absolute source path
    filename      String,
    asset_type    LowCardinality(String),         -- video | image | icon | vector | audio | document | other
    asset_subtype LowCardinality(String) DEFAULT '', -- logo | icon | b_roll | music | sfx | dialogue | ...
    ext           LowCardinality(String),
    size_bytes    UInt64,
    created_at    DateTime DEFAULT now(),
    project       String DEFAULT '',
    caption       String DEFAULT '',              -- Gemini caption (search side of the embedding)
    tags          Array(String) DEFAULT [],
    reusable      Bool DEFAULT true,
    status        LowCardinality(String) DEFAULT 'active',  -- active | duplicate | stale | archived
    content_hash  String DEFAULT '',              -- sha256 for exact-dup GROUP BY
    embedding     Array(Float32) DEFAULT [],      -- gemini-embedding-001 of the caption (search)
    visual_embedding Array(Float32) DEFAULT []    -- multimodalembedding@001 of image/video pixels (visual near-dup)
)
ENGINE = MergeTree
ORDER BY (asset_type, created_at);

CREATE TABLE IF NOT EXISTS xstoreAgent.asset_events
(
    ts       DateTime DEFAULT now(),
    asset_id UUID,
    event    LowCardinality(String),  -- ingested | searched | archived | kept
    project  String DEFAULT '',
    bytes    UInt64 DEFAULT 0,
    detail   String DEFAULT ''
)
ENGINE = MergeTree
ORDER BY (event, ts);

CREATE TABLE IF NOT EXISTS xstoreAgent.brief_queries
(
    ts        DateTime DEFAULT now(),
    brief     String,
    embedding Array(Float32)
)
ENGINE = MergeTree
ORDER BY ts;

-- Library rollup (agent: run_select_query):
--   SELECT asset_type, count() AS n, sum(size_bytes) AS bytes, countIf(reusable) AS reusable
--   FROM xstoreAgent.assets WHERE status != 'archived' GROUP BY asset_type;

-- Exact duplicate waste (agent: run_select_query) — GROUP BY, not CROSS JOIN:
--   SELECT content_hash, groupArray(filename) AS files, count() AS n,
--          sum(size_bytes) - max(size_bytes) AS wasted_bytes
--   FROM xstoreAgent.assets
--   WHERE content_hash != '' AND status != 'archived'
--   GROUP BY content_hash HAVING n > 1;

-- Repurpose search: embed_brief writes brief_queries, then MCP JOIN:
--   WITH q AS (SELECT embedding FROM xstoreAgent.brief_queries ORDER BY ts DESC LIMIT 1)
--   SELECT filename, asset_type, caption, tags,
--          cosineDistance(a.embedding, q.embedding) AS dist
--   FROM xstoreAgent.assets AS a, q
--   WHERE status != 'archived' AND length(a.embedding) > 0
--   ORDER BY dist ASC LIMIT 12;
