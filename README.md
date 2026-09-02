# xStoreAgent — AI Asset Librarian for Film/Video Teams

> **Agentic Cinema: The Blockbuster Hackathon** — **ClickHouse track**
> **Gemini** + **Google ADK** on **Cloud Run**, catalog queries through the official
> **ClickHouse Cloud** **mcp-clickhouse** server.

Production teams drown in assets — B-roll, VFX plates, logos, SFX, music stems —
scattered across projects with no memory. They re-shoot, re-license, and pay to
store duplicates of files they already own. **xStoreAgent is a Librarian agent
that gives a creator's media library a brain.**

Point it at a folder (or click **Ingest sample pack** on the hosted demo) and it:

1. **Ingests & segregates** every file by type (video / image / icon / vector / audio / document).
2. **Understands** each asset with Gemini — a caption, tags, and a *reusability verdict*.
3. **Remembers** it in **ClickHouse Cloud** — metadata plus a caption embedding (`gemini-embedding-001`).
4. **Answers in English** via the Librarian: reuse slate, duplicate waste, archive candidates — by running **SQL through mcp-clickhouse** (`list_tables`, `run_query` / `run_select_query`).
5. **Never deletes** on its own. You approve each archive.

## Architecture

```
Web UI
  ├─ dashboard REST (library / search / review)  → clickhouse-connect
  └─ Librarian chat (SSE)  → Google ADK agent
        Function tools (writes only): ingest_folder, embed_brief, archive_asset
        MCP toolset (ALL catalog reads):
          official mcp-clickhouse
            list_databases · list_tables · run_query / run_select_query
                    │
            ClickHouse Cloud
              assets          catalog + Array(Float32) caption embeddings
              asset_events    ingest / search / archive facts
              brief_queries   latest brief vector (JOIN, not a giant SQL literal)
```

Partner requirement: catalog questions are answered by the **official ClickHouse
MCP server**, not by wrapping SQL in Python on the agent. The dashboard still
uses `clickhouse-connect` so the grid stays snappy; writes (ingest/archive) stay
on that client because mcp-clickhouse is read-only.

Search is **caption-text in one embedding space**: Gemini looks at the asset and
writes a caption; `gemini-embedding-001` embeds that caption and every project
brief. A text brief can retrieve video, image, audio, or a logo because the
captions already describe every modality.

## Setup

### 1. Prerequisites
- A **Google Cloud project** with the **Vertex AI API** enabled.
- A **ClickHouse Cloud** instance (hackathon credits: $400). Note host / user / password.
- Python 3.11+.

### 2. Configure
```bash
cp .env.example .env      # fill in GCP + ClickHouse values
pip install -r requirements.txt
```

Keep `USE_CLICKHOUSE_MCP=true` (the ClickHouse track default).

### 3. Provision schema
`ensure_schema()` creates `assets` + `asset_events` on boot, or run
[`agent/schema.sql`](agent/schema.sql) yourself.

### 4. Run
```bash
python agent/tools/scan.py sample_assets
uvicorn server.app:app --reload
```

Open the UI, click **Ingest sample pack**, then **Golden prompt**. You should see
`list_tables` and `run_select_query` in the Librarian trace. `/api/health` must
report `mcp.ok` and `clickhouse.ok`.

### 5. Deploy to Cloud Run
```bash
bash scripts/deploy.sh
```

Then pre-load the same ClickHouse instance so the hosted URL is never empty:

```bash
python scripts/reset_library.py --yes --ingest sample_assets --project demo
```

Keep the ClickHouse Cloud service alive through judging (trial credits expire in
30 days). Details in [`DEPLOY.md`](DEPLOY.md).

## Repo layout
| Path | Purpose |
|------|---------|
| `agent/clickhouse_mcp.py` | Official `mcp-clickhouse` ADK toolset (partner path) |
| `agent/librarian.py` | ADK root agent — writes as functions, reads via MCP |
| `agent/clickhouse_client.py` | Dashboard + ingest writes (`clickhouse-connect`) |
| `agent/schema.sql` | `assets` + `asset_events` |
| `agent/tools/classify.py` | Gemini caption + reusability verdict |
| `agent/tools/embed.py` | Caption embeddings for search |
| `server/app.py` | FastAPI: ingest, library, chat SSE, health |
| `web/` | Dashboard + Librarian chat with SQL trace |
| `demo/SCRIPT.md` | 3-minute demo storyboard |

## Devpost blurb (paste)

xStoreAgent is a Gemini + Google ADK Librarian on Cloud Run that turns a messy
media folder into a reusable asset catalog in ClickHouse Cloud. The agent plans
a reuse package for a new shoot — what to reuse, how much duplicate storage is
wasted, what to archive — by calling the official **mcp-clickhouse** server
(`list_tables`, `run_select_query`) against `assets` and `asset_events`. Gemini
captions each file; caption embeddings in ClickHouse power brief→asset search.
Humans approve every archive. Built for filmmakers, editors, and solo creators
who already paid for B-roll they can no longer find.

## License
[MIT](LICENSE).
