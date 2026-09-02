# xStoreAgent — AI Asset Librarian for Film/Video Teams

> **Agentic Cinema: The Blockbuster Hackathon** submission — **ClickHouse track**
> Built with **Gemini + Google Agent Development Kit (ADK)** and **ClickHouse Cloud**.

Production teams drown in assets — B-roll, VFX plates, logos, icons, SFX, music
stems — scattered across projects with no memory. When a new project starts, the
reusable material is invisible, so teams re-shoot, re-license, and pay to store
stale duplicates. **xStoreAgent is an agent that gives a creator's media library a
brain.**

Point it at a folder and it:

1. **Ingests & segregates** every file by type (video / image / icon / vector / audio / document).
2. **Understands** each asset with Gemini multimodal — a caption, tags, and a
   *reusability verdict* (generic B-roll & logos = reusable; project slates &
   rough cuts = stale/archive).
3. **Remembers** it in **ClickHouse** — metadata plus a multimodal **embedding**.
4. **Flags near-duplicates & stale files** for archive/compress — you approve; it
   never deletes on its own.
5. **Surfaces repurposable assets** the moment you paste a new project brief, via
   ClickHouse vector search — a *text* brief can retrieve a *video* clip because
   all modalities share one embedding space.

## Architecture

```
Web UI  ──HTTP──►  FastAPI (Cloud Run)
                     └─ ADK agent "Librarian"
                          • scan_folder()          local walk + type classify
                          • classify_asset()       Gemini multimodal caption/verdict
                          • embed_asset()          Vertex multimodal embeddings
                          • ClickHouse MCP toolset  insert / vector query  ◄── PARTNER
                          • find_duplicates()       cosineDistance
                          • surface_repurposable()  brief → vector search
                                    │
                            ClickHouse Cloud  (assets + Array(Float32) embeddings)
```

The partner integration is the **ClickHouse MCP server** wired into the ADK agent
as a toolset, backed by the direct `clickhouse-connect` client in
[`agent/clickhouse_client.py`](agent/clickhouse_client.py).

## Setup

### 1. Prerequisites (manual, one-time)
- A **Google Cloud project** with the **Vertex AI API** enabled. Request the
  hackathon's $100 credit or use the free trial.
- A **ClickHouse Cloud** instance (free trial). Note host / user / password.
- Python 3.11+.

### 2. Configure
```bash
cp .env.example .env      # fill in GCP + ClickHouse values
pip install -r requirements.txt
```

### 3. Provision the ClickHouse schema
Run [`agent/schema.sql`](agent/schema.sql) against your instance, or let the app
create it on first run (`ensure_schema()`).

### 4. Run
```bash
# ingest a folder and print a per-type summary (no cloud needed):
python agent/tools/scan.py sample_assets

# full server (once .env is configured):
uvicorn server.app:app --reload
```

### 5. Deploy to Cloud Run
One command (reads your `.env`), or follow the manual steps — see
[`DEPLOY.md`](DEPLOY.md):
```bash
bash scripts/deploy.sh
```

## Repo layout
| Path | Purpose |
|------|---------|
| `agent/tools/scan.py` | Walk a folder, classify by type, hash for dedup |
| `agent/tools/classify.py` | Gemini multimodal caption + reusability verdict |
| `agent/tools/embed.py` | Multimodal embeddings for assets & briefs |
| `agent/clickhouse_client.py` | ClickHouse catalog: insert, vector search, dedup |
| `agent/clickhouse_mcp.py` | ClickHouse MCP toolset wiring for the ADK agent |
| `agent/librarian.py` | ADK root agent + tool registration |
| `server/app.py` | FastAPI: `/ingest /library /search /review /approve` |
| `web/` | Dashboard: library grid, brief search, dedup review |

## Future work (out of hackathon MVP scope)
Web search for free cloud storage, automatic cloud upload/fetch, and a public
"collaborate" library for creators sharing non-confidential approved assets.

## License
[MIT](LICENSE).
