# xStoreAgent — AI Asset Librarian for Film/Video Teams

> **Agentic Cinema: The Blockbuster Hackathon** — **ClickHouse track**
> **Gemini** + **Google ADK** on **Cloud Run**, catalog queries through the official
> **ClickHouse Cloud** **mcp-clickhouse** server.
>
> 🔗 **Live demo:** `<paste your Cloud Run URL here>` · 🎬 **Video:** `<paste your 3-min video URL here>`

Production teams drown in assets — B-roll, VFX plates, logos, SFX, music stems —
scattered across projects with no memory. They re-shoot, re-license, and pay to
store duplicates of files they already own. **xStoreAgent is a Librarian agent
that gives a creator's media library a brain.**

Point it at a folder (or click **Ingest sample pack** on the hosted demo) and it:

1. **Ingests & segregates** every file by type (video / image / icon / vector / audio / document).
2. **Understands** each asset with Gemini — it *watches* the video and *hears* the audio (not just the filename) to write a caption, tags, and a *reusability verdict*.
3. **Remembers** it in **ClickHouse Cloud** — metadata, a caption embedding (`gemini-embedding-001`) for cross-modal search, plus a true visual embedding (`multimodalembedding@001`) for near-duplicate detection.
4. **Answers in English** via a **crew of agents** — a Librarian orchestrator that delegates to an Analyst (runs **SQL through mcp-clickhouse**: `list_tables`, `run_select_query`), an Archivist, a Scout, and a Curator.
5. **Assembles a cut** — the Editor agent turns your library into an edit-ready shot list for a brief and flags what's still missing to shoot.
6. **Never deletes** on its own. You approve each archive.

## Architecture

```
Web UI
  ├─ dashboard REST (library / search / review / assemble)  → clickhouse-connect
  └─ Librarian chat (SSE)  → Google ADK multi-agent crew
        Librarian (root orchestrator) — routes, holds ingest_folder
          ├─ Analyst   → embed_brief + MCP toolset (ALL catalog reads)
          │                official mcp-clickhouse
          │                  list_databases · list_tables · run_query / run_select_query
          ├─ Archivist → archive_asset (only after you approve)
          ├─ Scout     → google_search (grounded free-storage search)
          ├─ Curator   → creative reuse rationale
          └─ Editor    → assemble_sequence (edit-ready shot list)
                    │
            ClickHouse Cloud
              assets          catalog + caption embedding + visual embedding
              asset_events    ingest / search / archive / assemble facts
              brief_queries   latest brief vector (JOIN, not a giant SQL literal)
```

Delegation uses ADK `sub_agents` (LLM-routed transfer), not agent-as-tool, so a
delegated agent runs on the **same event stream** — the Analyst's `list_tables` /
`run_select_query` MCP calls stay visible in the live trace judges will look for.

Partner requirement: catalog questions are answered by the **official ClickHouse
MCP server**, not by wrapping SQL in Python on the agent. The dashboard still
uses `clickhouse-connect` so the grid stays snappy; writes (ingest/archive) stay
on that client because mcp-clickhouse is read-only.

Search is **caption-text in one embedding space**: Gemini looks at the asset and
writes a caption; `gemini-embedding-001` embeds that caption and every project
brief. A text brief can retrieve video, image, audio, or a logo because the
captions already describe every modality. Separately, image/video assets also get
a **true visual embedding** (`multimodalembedding@001`) stored in
`assets.visual_embedding`, which powers visual near-duplicate detection (two
different encodings of the same shot) without skewing the text-brief search.

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
# Generate the sample pack: real images + real short clips (Gemini watches these).
python scripts/make_sample_pack.py
python scripts/make_media_samples.py
uvicorn server.app:app --reload
```

Open the UI, click **Ingest sample pack**, then **Golden prompt**. You should see
`list_tables` and `run_select_query` in the Librarian trace. `/api/health` must
report `mcp.ok` and `clickhouse.ok`.

### 5. Deploy to Cloud Run
```bash
bash scripts/deploy.sh
```

Then pre-load the same ClickHouse instance so the hosted URL is never empty — and
top it up with realistic rows so the analytics (rollup / duplicate waste / impact)
run at real scale (GBs, thousands of files):

```bash
python scripts/reset_library.py --yes --ingest sample_assets --project demo --seed 5000
```

Keep the ClickHouse Cloud service alive through judging (trial credits expire in
30 days). Details in [`DEPLOY.md`](DEPLOY.md).

## Repo layout
| Path | Purpose |
|------|---------|
| `agent/clickhouse_mcp.py` | Official `mcp-clickhouse` ADK toolset (partner path) |
| `agent/librarian.py` | ADK multi-agent crew: Librarian + Analyst/Archivist/Scout/Curator/Editor |
| `agent/clickhouse_client.py` | Dashboard + ingest writes (`clickhouse-connect`) |
| `agent/schema.sql` | `assets` (+ `visual_embedding`) + `asset_events` + `brief_queries` |
| `agent/tools/classify.py` | Gemini caption + reusability verdict (watches video, hears audio) |
| `agent/tools/embed.py` | Caption embeddings (search) + visual embeddings (dedup) |
| `agent/tools/assemble.py` | Editor: assemble an edit-ready shot list from the library |
| `server/app.py` | FastAPI: ingest, library, chat SSE, assemble SSE, health |
| `web/` | Dashboard + multi-agent chat trace + storyboard |
| `scripts/make_media_samples.py` | Generate real sample video/audio clips |
| `scripts/seed_scale.py` | Seed thousands of realistic rows for scale analytics |
| `demo/SCRIPT.md` | 3-minute demo storyboard |

## Devpost blurb (paste)

xStoreAgent is a Gemini + Google ADK **multi-agent** Librarian on Cloud Run that
gives a film team's media library a brain. Gemini **watches every video and hears
every audio file** to caption it and judge whether it's reusable; ClickHouse Cloud
remembers it. Ask in English and a Librarian orchestrator delegates to specialist
agents — an **Analyst** that answers reuse / duplicate-waste / archive questions by
running SQL through the official **mcp-clickhouse** server (`list_tables`,
`run_select_query`), an **Archivist** (you approve every archive), a **Scout** that
Google-searches free storage, a **Curator**, and an **Editor** that assembles an
**edit-ready shot list** from what you already own and flags what's still missing
to shoot. Caption embeddings power cross-modal brief→asset search; a separate
visual embedding catches near-duplicate footage. Built for filmmakers, editors, and
solo creators who already paid for B-roll they can no longer find.

## License
[MIT](LICENSE).
