# xStoreAgent — AI Asset Librarian for Film/Video Teams

> **Agentic Cinema: The Blockbuster Hackathon** · **ClickHouse track**
>
> A **Gemini + Google ADK** multi-agent Librarian on **Cloud Run**. Catalog
> questions are answered at runtime through the official **ClickHouse Cloud**
> **mcp-clickhouse** server (`list_tables`, `run_select_query`) — not a Python
> SQL wrapper and not Grafana’s MCP.
>
> | | |
> |---|---|
> | **Live demo** | https://xstoreagent-770223015971.us-central1.run.app/ |
> | **Health (must be green)** | https://xstoreagent-770223015971.us-central1.run.app/api/health |
> | **Source** | https://github.com/abhicsng007/xstoreAgent |
> | **License** | [MIT](LICENSE) (repo root) |
> | **3-min demo** | `https://youtu.be/GIq-hI5dIJc` |
> | **Devpost story** | [PROJECT_DETAILS.md](PROJECT_DETAILS.md) |

Production teams drown in assets — B-roll, VFX plates, logos, SFX, music stems —
scattered across projects with no memory. They re-shoot, re-license, and pay to
store duplicates of files they already own. **xStoreAgent is a Librarian agent
that gives a creator’s media library a brain.**

Point it at a folder (or click **Ingest sample pack** on the hosted demo) and it:

1. **Ingests & segregates** every file by type (video / image / icon / vector / audio / document).
2. **Understands** each asset with Gemini — it *watches* the video and *hears* the audio (not just the filename) to write a caption, tags, and a *reusability verdict*.
3. **Remembers** it in **ClickHouse Cloud** — metadata, a caption embedding (`gemini-embedding-001`) for cross-modal search, plus a true visual embedding (`multimodalembedding@001`) for near-duplicate detection.
4. **Answers in English** via a **crew of agents** — a Librarian orchestrator that delegates to an Analyst (SQL through **mcp-clickhouse**), an Archivist, a Scout, a Curator, and an Editor.
5. **Assembles a cut** — the Editor turns the library into an edit-ready shot list for a brief and flags what’s still missing to shoot.
6. **Never deletes** on its own. You approve each archive.

Audience: filmmakers, editors, and studio/post crews — the media workflow the
hackathon asks for.

---

## Hackathon eligibility (Stage One)

Judges screen pass/fail before scoring. Proof is **in the running product and
the code**, not this paragraph.

| Requirement | How xStoreAgent meets it |
|---|---|
| Functional agent, not a deck | Hosted Cloud Run app + live multi-agent traces |
| Powered by Gemini | `google-genai` / Vertex: caption, embeddings, crew LLMs |
| Google Cloud Agent Builder / ADK | `google.adk.Agent` crew in [`agent/librarian.py`](agent/librarian.py) — `sub_agents` transfer, not agent-as-tool |
| Hosted URL | Cloud Run (link above) |
| Public repo + complete OSS license | GitHub + [MIT](LICENSE) at repo root |
| Instructions to run | This README |
| **ClickHouse track:** official **mcp-clickhouse** at runtime | [`agent/clickhouse_mcp.py`](agent/clickhouse_mcp.py) starts `python -m mcp_clickhouse.main`; Analyst catalog reads go through `list_tables` / `run_select_query`. `/api/health` → `mcp.ok` + `clickhouse.ok` |
| Partner use in **code**, not README-only | `mcp-clickhouse` in [`requirements.txt`](requirements.txt); imported and spawned at runtime |
| Media / entertainment workflow | Ingest → reuse search → duplicate waste → assemble a cut |
| No banned agent stacks | No LangChain / LangGraph / CrewAI agent loop |

**ClickHouse track note:** dashboard grids use `clickhouse-connect` so the UI
stays snappy; **agent catalog questions** use the official MCP server (read-only).
Writes (ingest/archive) stay on `clickhouse-connect` because mcp-clickhouse cannot
write. Do not turn `USE_CLICKHOUSE_MCP` off for judging.

### Judge in two minutes (hosted)

1. Open the **live demo**. Confirm the badge **ClickHouse MCP live**.
2. Hit **Golden prompt** (30s city product ad). In the chat trace you must see:
   - `Librarian → delegates to Analyst`
   - `MCP · list_tables`
   - `MCP · run_select_query` with `GROUP BY content_hash` / `cosineDistance`
3. **Assemble a cut** with the same brief → storyboard + gaps still to shoot.
4. Optional: **Surface reusable assets** → Analyst + Curator live reasoning.

Demo storyboard: [`demo/SCRIPT.md`](demo/SCRIPT.md) (≤ 3:00, English, **the running app**, not a cinematic trailer).

### Judging axes (Stage Two)

| Axis | Where it shows up |
|---|---|
| **Tech** | ADK multi-agent transfer, official mcp-clickhouse SQL on screen, Gemini watches/hears media, caption + visual embeddings, Cloud Run |
| **Design** | Full dashboard: ingest crew, library, search, reclaim, assemble storyboard, Scout — not a chat toy |
| **Impact** | Reuse instead of reshoot; reclaimable duplicate GB at seeded production scale (~5k rows) |
| **Idea** | A Librarian for the media *library* itself — memory, verdicts, and a cut from files you already paid for |

---

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
              cloud_vendors / watched_folders / asset_locations
```

Delegation uses ADK `sub_agents` (LLM-routed transfer). A delegated agent runs
on the **same event stream**, so the Analyst’s MCP calls stay visible in the
trace.

Search is **caption-text in one embedding space**: Gemini looks at the asset and
writes a caption; `gemini-embedding-001` embeds that caption and every project
brief. A text brief can retrieve video, image, audio, or a logo. Image/video
assets also get a **visual embedding** (`multimodalembedding@001`) for
near-duplicate detection without skewing brief search.

Known content hashes skip Gemini on re-ingest. `.xstore.json` sidecars let a
later ingest catalog from **text only** (no second watch/listen).

---

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
`ensure_schema()` creates catalog tables on boot, or run
[`agent/schema.sql`](agent/schema.sql) yourself.

### 4. Run
```bash
# Real Mixkit (or Pexels) B-roll, trimmed to 6s 720p so Gemini ingest stays cheap.
# Optional: set PEXELS_API_KEY (free at pexels.com/api) to prefer Pexels over Mixkit.
python scripts/fetch_demo_pack.py
uvicorn server.app:app --reload
```

Open the UI, click **Ingest sample pack**, then **Golden prompt**. You should see
`list_tables` and `run_select_query` in the Librarian trace. `/api/health` must
report `mcp.ok` and `clickhouse.ok`.

### 5. Deploy to Cloud Run
```bash
bash scripts/deploy.sh
```

Pre-load the same ClickHouse instance so the hosted URL is never empty — and
top it up so analytics (rollup / duplicate waste / impact) run at real scale:

```bash
python scripts/reset_library.py --yes --ingest sample_assets --project demo --seed 5000
```

Keep the ClickHouse Cloud service alive through judging (trial credits expire in
30 days). Details in [`DEPLOY.md`](DEPLOY.md).

---

## Repo layout
| Path | Purpose |
|------|---------|
| `agent/clickhouse_mcp.py` | Official `mcp-clickhouse` ADK toolset (partner path) |
| `agent/librarian.py` | ADK multi-agent crew: Librarian + Analyst/Archivist/Scout/Curator/Editor |
| `agent/clickhouse_client.py` | Dashboard + ingest writes (`clickhouse-connect`) |
| `agent/schema.sql` | Catalog + events + brief vectors + cloud/watch tables |
| `agent/tools/classify.py` | Gemini caption + reusability verdict (watches video, hears audio) |
| `agent/tools/embed.py` | Caption embeddings (search) + visual embeddings (dedup) |
| `agent/tools/assemble.py` | Editor: assemble an edit-ready shot list |
| `agent/tools/scout.py` | Storage Scout: grounded free-tier search |
| `agent/tools/cloud.py` | Connect sync folders, organize/offload with sidecars |
| `server/app.py` | FastAPI: ingest, library, chat SSE, assemble SSE, health |
| `web/` | Dashboard + multi-agent traces + storyboard |
| `scripts/fetch_demo_pack.py` | Mixkit/Pexels demo pack, trimmed for cheap Gemini ingest |
| `scripts/seed_scale.py` | Thousands of realistic rows for scale analytics |
| `demo/SCRIPT.md` | 3-minute demo storyboard (hackathon trailer rules) |
| `PROJECT_DETAILS.md` | Devpost project story (paste into the form) |

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

## Built with
Python · FastAPI · Gemini · Vertex AI · Google ADK · Cloud Run · ClickHouse Cloud · official mcp-clickhouse · Mixkit/Pexels (demo media)

## License
[MIT](LICENSE).
