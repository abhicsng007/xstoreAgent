# xStoreAgent

AI asset librarian for film and video teams.

Gemini watches each clip and hears each soundtrack, writes a caption and a
reusability verdict, and ClickHouse Cloud remembers the catalog. Ask in English:
a Librarian crew finds what you can reuse, how much duplicate storage you are
paying for, and what is still missing to shoot.

**Live demo:** https://xstoreagent-770223015971.us-central1.run.app  
**Demo video:** https://youtu.be/GIq-hI5dIJc  
**Health:** https://xstoreagent-770223015971.us-central1.run.app/api/health

---

## What it does

Point it at a folder (or **Ingest sample pack** on the hosted app):

1. **Segregate** files by type — video, image, icon, vector, audio, document.
2. **Caption** them with Gemini from the actual pixels and audio, not the filename, plus tags and a reusable / project-specific verdict.
3. **Store** metadata in ClickHouse Cloud, a caption embedding for search (`gemini-embedding-001`), and a visual embedding for near-duplicates (`multimodalembedding@001`).
4. **Answer in English** through a crew of agents:
   - **Librarian** — orchestrator
   - **Analyst** — catalog SQL via the official ClickHouse MCP server (`list_tables`, `run_select_query`)
   - **Archivist** — archives only after you approve
   - **Scout** — free-tier storage search; connect local sync folders to offload
   - **Curator** — why a hit belongs in the next cut
   - **Editor** — assemble an edit-ready shot list and flag gaps still to shoot
5. **Never delete** on its own.

Re-ingest of the same bytes skips Gemini (content hash). `.xstore.json` sidecars
let a later ingest catalog from text only.

---

## Architecture

```
Web UI
  ├─ dashboard REST (library / search / review / assemble)  → clickhouse-connect
  └─ Librarian chat (SSE)  → Google ADK multi-agent crew
        Librarian (root)
          ├─ Analyst   → embed_brief + official mcp-clickhouse
          │                list_databases · list_tables · run_select_query
          ├─ Archivist → archive_asset (after approval)
          ├─ Scout     → google_search
          ├─ Curator   → reuse rationale
          └─ Editor    → assemble_sequence
                    │
            ClickHouse Cloud
              assets · asset_events · brief_queries
              cloud_vendors · watched_folders · asset_locations
```

The dashboard talks to ClickHouse with `clickhouse-connect`. Agent catalog
**reads** go through **mcp-clickhouse** (read-only). Ingest and archive writes
stay on the Python client.

Search embeds captions and briefs in one text space, so a sentence can retrieve
video, a still, audio, or a logo. Visual embeddings are only used for
near-duplicate detection.

---

## Setup

**Needs:** Python 3.11+, a Google Cloud project with Vertex AI enabled, a
ClickHouse Cloud instance.

```bash
cp .env.example .env      # GCP + ClickHouse
pip install -r requirements.txt

python scripts/fetch_demo_pack.py
uvicorn server.app:app --reload
```

`ensure_schema()` creates tables on boot, or run [`agent/schema.sql`](agent/schema.sql).

Leave `USE_CLICKHOUSE_MCP=true`. Open the UI, **Ingest sample pack**, then try a
library question in the Librarian. `/api/health` should report `mcp.ok` and
`clickhouse.ok`.

Optional: `PEXELS_API_KEY` in `.env` if you want Pexels instead of Mixkit for
the sample pack.

### Cloud Run

```bash
bash scripts/deploy.sh
python scripts/reset_library.py --yes --ingest sample_assets --project demo --seed 5000
```

The seed fills analytics (rollup, duplicate waste) at thousands of rows. Details
in [`DEPLOY.md`](DEPLOY.md).

---

## Repo

| Path | Purpose |
|------|---------|
| `agent/librarian.py` | ADK crew: Librarian + Analyst / Archivist / Scout / Curator / Editor |
| `agent/clickhouse_mcp.py` | Official mcp-clickhouse toolset |
| `agent/clickhouse_client.py` | Dashboard + ingest writes |
| `agent/schema.sql` | Catalog schema |
| `agent/tools/classify.py` | Gemini caption + reusability |
| `agent/tools/embed.py` | Caption + visual embeddings |
| `agent/tools/assemble.py` | Editor shot list |
| `agent/tools/scout.py` | Storage Scout |
| `agent/tools/cloud.py` | Sync-folder connect, organize, offload |
| `server/app.py` | FastAPI |
| `web/` | Dashboard |
| `scripts/fetch_demo_pack.py` | Short Mixkit/Pexels sample pack |
| `scripts/seed_scale.py` | Scale rows for analytics |
| `demo/SCRIPT.md` | Demo walkthrough |

## License

[MIT](LICENSE).
