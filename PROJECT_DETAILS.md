# xStoreAgent — Devpost project details

Copy each section into the matching field on
[Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/).

**Elevator pitch (Devpost tagline):**
An AI Asset Librarian for film teams — Gemini watches the footage, ClickHouse
remembers it, and a crew of agents tells you what to reuse instead of reshoot.

**Track:** ClickHouse
**Live demo:** https://xstoreagent-770223015971.us-central1.run.app
**Health:** https://xstoreagent-770223015971.us-central1.run.app/api/health (`mcp.ok` + `clickhouse.ok`)
**Repo:** https://github.com/abhicsng007/xstoreAgent
**License:** MIT (file at repo root)
**Demo video:** https://youtu.be/GIq-hI5dIJc

**Built with:** Gemini (`gemini-3.7-flash`) · Google ADK (multi-agent `sub_agents`) ·
`mcp-clickhouse` (official ClickHouse MCP server) · ClickHouse Cloud · Vertex AI
embeddings (`gemini-embedding-001`, `multimodalembedding@001`) · Google Cloud Run ·
FastAPI · Python · Server-Sent Events.

---

## Inspiration

Every production has a graveyard of drives. B-roll from last year's city shoot, a
logo export in five folders, a whoosh SFX nobody can name, a slate still labeled
`IMG_8841`. Editors hunt for hours, then the producer pays to **reshoot or
re-license** something the team already owns — and the studio keeps paying to
**store the duplicates**.

The hackathon asked for an agent that unblocks a real media workflow, not a
chatbot with a film-themed prompt. The bottleneck we kept hearing is not "write me
a script." It is **memory**: the library has no brain. Filenames lie. Folders rot.
ClickHouse is built for exactly the questions a production office asks at scale —
how much waste, what can we reuse, what should we archive — *if* an agent is
allowed to **see** the footage and **speak SQL** through ClickHouse's own MCP
server.

xStoreAgent started from that one sentence: **give the media library a Librarian.**

---

## What it does

xStoreAgent is a multi-agent Librarian for a film/video team's asset library.

**Ingest — Gemini watches and listens.** Point it at a folder (or click **Ingest
sample pack** on the hosted demo). Gemini watches each video and hears each audio
file — from the actual pixels and waveform, *not* the filename — writes a caption
and tags, and issues a **reusability verdict** (evergreen B-roll vs.
project-specific slate / rough cut / VO). ClickHouse Cloud stores the catalog:
metadata, a **caption embedding** for cross-modal search, and a separate **visual
embedding** for near-duplicate detection.

**Ask in English.** A Librarian orchestrator (Google ADK `sub_agents`) delegates
to a real crew — and you watch it happen live:

- 🔎 **Analyst** — every catalog question fires the official **`mcp-clickhouse`**
  server (`list_tables`, `run_select_query`). Duplicate waste is a
  `GROUP BY content_hash`; brief search is a `cosineDistance` JOIN against a stored
  brief vector, not a giant SQL literal pasted into the prompt.
- 🗄️ **Archivist** — archives only after you approve. Reversible. Nothing is deleted.
- 🧭 **Scout** — grounded Google Search for free-tier cloud storage when the library
  is over plan, then a **computed offload plan** (reusable footprint × the top
  provider's free tier = % of overage cleared). Connect MEGA / Drive / Dropbox
  **sync folders**, organize a captioned pack, and offload reusable media.
- 🎬 **Curator** — *why* a hit belongs in the next cut, in a creator's voice.
- ✂️ **Editor** — **Assemble a cut**: an edit-ready storyboard (hook → establish →
  product → CTA) built from assets you already own, plus **honest gaps** still to
  shoot so you don't waste a day on footage you have.

**Search.** "Surface reusable assets" streams live Analyst + Curator reasoning
(embed brief → ClickHouse rank → reuse rationale), then cards with previews.

**Memory that compounds.** Re-ingesting the same bytes skips Gemini (sha256).
`.xstore.json` sidecars mean a later ingest of an organized cloud pack is
**text-only** — no second watch/listen, no wasted credits.

**Real numbers.** The hosted demo is seeded at production-shaped scale (~5,000
rows, ~1.1 TB, ~10% duplicates), so every impact figure is **computed by a
ClickHouse query**, not mocked in the UI.

---

## How we built it

**Google Cloud + Gemini.** Gemini on Vertex AI — `gemini-3.7-flash` for the crew
and captions, `gemini-embedding-001` (3072-d) for brief/caption search, and
`multimodalembedding@001` for visual near-duplicate detection. The Librarian is a
Google ADK **root agent with specialist `sub_agents`**, so a hand-off (LLM-routed
transfer, *not* agent-as-tool) stays on the **same event stream** a judge can
watch. The whole app runs on **Cloud Run**.

**ClickHouse track (the required partner path).** Catalog **reads** from the agent
go through the official **`mcp-clickhouse`** server over stdio
(`python -m mcp_clickhouse.main`), wired in `agent/clickhouse_mcp.py`. That is
ClickHouse's own MCP server — not Grafana's, not SQL hidden inside a Python tool.
Dashboard grids and ingest/archive **writes** use `clickhouse-connect` because the
official MCP server is read-only; the split is deliberate and documented, and the
Analyst has no catalog-read tool *except* MCP so it can't bypass it.

**Product surface.** FastAPI + a single-page dashboard: live ingest crew trace,
Librarian chat with delegation and MCP tool chips, reusability-ranked library,
cross-modal reusable-asset search, an Assemble storyboard, a reclaim list, and the
Storage Scout meter — every agentic path streamed over **Server-Sent Events** so
the reasoning is visible, not hidden. Mixkit/Pexels demo media is trimmed to short
720p clips so Gemini can actually watch them without burning the credit budget.

---

## Challenges we ran into

**The partner MCP server is read-only.** Track eligibility means "`mcp-clickhouse`
must fire at runtime," but the server can't `INSERT`. We kept writes on
`clickhouse-connect` *without* letting the Analyst cheat by reading the catalog in
Python — the Analyst has no catalog-read tool except MCP.

**ADK delegation vs. "agent-as-tool."** Tool-wrapped sub-agents hide their MCP
calls. Switching to `sub_agents` transfer keeps `list_tables` / `run_select_query`
on the same event stream, so the golden prompt is honest on camera.

**The modality gap.** Raw image/video embeddings ranked poorly against a *text*
brief. We embed Gemini's **captions** for search (one text space for all
modalities) and keep visual embeddings only for dedup — dramatically better
relevance.

**Video is the bill.** Watching every clip costs credits. We cap inline media,
skip known content hashes, write sidecars for text-only re-ingest, and seed ~5k
*analytics* rows without embeddings so waste queries run at TB scale without
recaptioning a whole archive.

**EventSource vs. HTTP 400.** Folder ingest used to fail as JSON and the UI only
showed "connection closed." Missing folders now stream as SSE errors, and a
successful ingest no longer gets clobbered by `onerror`.

**Cloud Run can't see `C:\`.** "Connect MEGA/Drive" is a **local sync folder**,
not OAuth from the container. The hosted UI is honest about that limit; the
Librarian and the full MCP path still run entirely on Cloud Run.

**A meter that told the truth.** Seeded at ~1.1 TB against an old 15 GB plan, the
storage bar pinned at an absurd 7,405%. We moved to a realistic 1 TB tier and made
the Scout emit a genuine **offload plan** that quantifies how much of the overage a
free provider tier actually clears.

---

## Accomplishments that we're proud of

- A **complete product**, not a notebook: ingest → memory → English Q&A → reuse
  search → assemble a cut → reclaim — with **live reasoning traces on every
  agentic path**.
- **ClickHouse track eligibility visible on screen:** Librarian → Analyst
  delegation, then real MCP SQL (`GROUP BY content_hash`, `cosineDistance`) — not a
  screenshot of a grid. `/api/health` proves `mcp.ok`.
- **Gemini that watches and hears** the sample clips; captions describe on-screen
  motion, not the filename.
- **Human-gated archive** — the agent never deletes on its own.
- **Memory that compounds:** hash + sidecars so the library gets smarter without
  paying to re-watch.
- **Impact computed at scale** — reclaimable GB and offload plans from real
  queries over ~1.1 TB of seeded catalog, not hard-coded UI numbers.
- A tight **3-minute story** that maps onto all four judging axes (see
  `demo/SCRIPT.md`).

---

## What we learned

An agent for media is only as good as what it is allowed to **see** and **query**.
Filenames are a lie; Gemini on the pixels and the waveform is the difference
between a search box and a Librarian.

And "we use ClickHouse" is not a track submission — **`mcp-clickhouse` has to fire
inside the agent loop**, with `list_tables` visible, or Stage One can fail you in
thirty seconds. We learned to separate **product reads** (fast dashboard SQL) from
**agent reads** (official MCP), and to store brief vectors in a table so cosine
search is a JOIN instead of pasting a 3072-float literal into a prompt.

Finally: honesty reads better than theatre. Streaming the *real* pipeline as agent
reasoning — including the gaps it still can't fill — is more convincing than a
scripted demo.

---

## What's next for xStoreAgent

- OAuth / official APIs for Drive, Dropbox, and MEGA so Cloud Run can offload
  without a desktop sync folder.
- Background watchers on connected folders (hash + sidecar only — no re-watching).
- Restore-from-cloud straight into an edit when the Editor's brief needs an
  offloaded shot.
- Per-show libraries and role-based archive rights for a real post house.
- Keep the ClickHouse Cloud service extended through the judging window so the
  hosted URL stays queryable.

Built for the crews who already shot the footage — they just can't find it.
