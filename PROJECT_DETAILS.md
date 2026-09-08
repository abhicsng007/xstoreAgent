# xStoreAgent — Devpost project details

Paste each section into the matching field on
[Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/).

**Track:** ClickHouse  
**Live demo:** https://xstoreagent-wgfn3j35ia-uc.a.run.app  
**Health:** https://xstoreagent-wgfn3j35ia-uc.a.run.app/api/health (`mcp.ok` + `clickhouse.ok`)  
**Repo:** https://github.com/abhicsng007/xstoreAgent  
**License:** MIT (file at repo root)  
**Demo video:** `<paste public YouTube/Vimeo URL — running product, ≤3:00, English>`

---

## Inspiration

Every production has a graveyard of drives. B-roll from last year’s city shoot,
a logo export in five folders, a whoosh SFX nobody can name, a slate still
labeled `IMG_8841`. Editors hunt for hours, then the producer pays to reshoot or
re-license something the team already owns — and the studio keeps paying to
store the duplicates.

The hackathon asked for an agent that unblocks a real media workflow, not a
chatbot with a film-themed prompt. The bottleneck we kept hearing is not
“write me a script.” It is **memory**: the library has no brain. Filenames lie.
Folders rot. ClickHouse is built for exactly the questions a production office
asks at scale — how much waste, what can we reuse, what should we archive —
if an agent is allowed to *see* the footage and *speak SQL* through ClickHouse’s
own MCP server.

xStoreAgent started from that sentence: give the media library a Librarian.

---

## What it does

xStoreAgent is a multi-agent Librarian for a film/video team’s asset library.

**Ingest.** Point it at a folder (or **Ingest sample pack** on the hosted demo).
Gemini watches each video and hears each audio file, writes a caption and tags,
and issues a reusability verdict (evergreen B-roll vs project-specific slate /
rough cut / VO). ClickHouse Cloud stores the catalog: metadata, a caption
embedding for search, and a separate visual embedding for near-duplicate
detection.

**Ask in English.** A Librarian orchestrator (Google ADK `sub_agents`) delegates:

- **Analyst** — every catalog question goes through the official
  **mcp-clickhouse** server (`list_tables`, `run_select_query`). Duplicate waste
  is a `GROUP BY content_hash`; brief search is `cosineDistance` against a stored
  brief vector, not a giant SQL literal.
- **Archivist** — archives only after you approve. Nothing is deleted.
- **Scout** — grounded Google Search for free-tier cloud storage when the library
  is over plan; you can connect MEGA / Drive / Dropbox **sync folders**, organize
  a captioned pack, and offload reusable media.
- **Curator** — why a hit belongs in the next cut.
- **Editor** — **Assemble a cut**: an edit-ready storyboard (hook → establish →
  product → CTA) from assets you already own, plus honest gaps still to shoot.

**Search.** “Surface reusable assets” streams live Analyst + Curator reasoning
(embed brief → ClickHouse rank → reuse rationale), then cards with previews.

**Memory.** Re-ingest of the same bytes skips Gemini (sha256). `.xstore.json`
sidecars mean a later ingest of an organized cloud pack is **text-only** — no
second watch/listen.

The hosted demo is seeded at production-shaped scale (thousands of rows, real
reclaimable GB) so impact numbers are computed, not mocked in the UI.

---

## How we built it

**Google Cloud.** Gemini on Vertex (`gemini-3.7-flash` for the crew and
captions; `gemini-embedding-001` for brief/caption search;
`multimodalembedding@001` for visual near-dup). The Librarian is a Google ADK
root agent with specialist `sub_agents` so a hand-off stays on the same SSE
trace judges can watch. The app runs on **Cloud Run**.

**ClickHouse track (required path).** Catalog *reads* from the agent use the
official **mcp-clickhouse** server over stdio (`python -m mcp_clickhouse.main`),
wired in `agent/clickhouse_mcp.py`. That is ClickHouse’s MCP, not Grafana’s, and
not SQL hidden in Python tools. Dashboard grids and ingest writes use
`clickhouse-connect` because the official MCP server is read-only — the split is
intentional and documented.

**Product surface.** FastAPI + a single-page dashboard: ingest crew, Librarian
chat, reusable-asset search, assemble storyboard, reclaim list, Storage Scout.
Human-in-the-loop on archive. Mixkit/Pexels demo media is trimmed to short 720p
clips so Gemini can actually watch them without burning the credit budget.

---

## Challenges we ran into

**Partner MCP is read-only.** The eligibility rule is “use mcp-clickhouse at
runtime.” The server cannot insert. We had to keep writes on `clickhouse-connect`
without letting the Analyst cheat by reading the catalog in Python. The agent
has no catalog-read tools except MCP.

**ADK delegation vs “agent as tool.”** Tool-wrapped sub-agents hide MCP calls.
`sub_agents` transfer keeps `list_tables` / `run_select_query` on the same event
stream so the golden prompt is honest on camera.

**Modality gap.** Raw image embeddings vs a text brief ranked poorly. We embed
Gemini’s *captions* for search and keep visual embeddings only for dedup.

**Video cost.** Watching every clip is the bill. We cap inline media, skip known
hashes, write sidecars, and seed 5k *analytics* rows without embeddings so waste
queries run at GB scale without recaptioning a whole archive.

**EventSource vs HTTP 400.** Folder ingest used to fail as JSON; the UI only
showed “connection closed.” Missing folders now stream as SSE errors, and a
successful ingest no longer gets overwritten by `onerror`.

**Cloud Run cannot see `C:\`.** “Connect MEGA/Drive” is a **local sync folder**,
not OAuth from the container. The hosted UI is honest about that; the Librarian
and MCP path still run fully on Cloud Run.

---

## Accomplishments that we're proud of

- A **complete product**, not a notebook: ingest → memory → English Q&A → reuse
  search → assemble a cut → reclaim, with live traces on every agentic path.
- **ClickHouse track eligibility on screen:** Librarian → Analyst, then real MCP
  SQL (`GROUP BY content_hash`, `cosineDistance`), not a screenshot of a grid.
- Gemini that **watches and hears** sample clips; captions describe motion, not
  filenames.
- Human-gated archive. The agent never deletes.
- Hash memory + sidecars so the library gets smarter without paying to re-watch.
- A 3-minute story that maps onto all four judging axes (see `demo/SCRIPT.md`).

---

## What we learned

An agent for media is only as good as what it is allowed to **see** and **query**.
Filenames are a lie; Gemini on the pixels and waveform is the difference between
a search box and a Librarian. And “we use ClickHouse” is not a track submission —
**mcp-clickhouse has to fire in the agent loop**, with `list_tables` visible,
or Stage One can fail you in thirty seconds.

We also learned to separate **product reads** (fast dashboard SQL) from **agent
reads** (official MCP), and to put brief vectors in a table so cosine search is a
JOIN instead of pasting a 1408-float literal into the prompt.

---

## What's next for xStore Agent

- OAuth / official APIs for Drive, Dropbox, and MEGA so Cloud Run can offload
  without a desktop sync folder.
- Background watchers on connected folders (hash + sidecar only).
- Restore-from-cloud into an edit from the Editor when a brief needs an
  offloaded shot.
- Per-show libraries and role-based archive rights for a real post house.
- Keep the ClickHouse Cloud service extended through the October judging window
  so the hosted URL stays queryable.

Built for the crews who already shot the footage — they just can’t find it.
