# xStoreAgent — 3-minute demo script & storyboard

Target: ≤ 3:00, English (or English subtitles). Public on YouTube/Vimeo.
Show the **running product**. Hit all four judging axes (Tech · Design · Impact ·
Idea). Two money shots: (1) the Librarian **delegating to the Analyst**, which
calls **mcp-clickhouse** (`list_tables` / `run_select_query`) with SQL on screen;
(2) the **Editor assembling a cut** — a storyboard built from the library.

Before recording:
1. `python scripts/fetch_demo_pack.py` — real Mixkit/Pexels B-roll, 6s 720p (optional `PEXELS_API_KEY`).
2. `python scripts/reset_library.py --yes --ingest sample_assets --project demo --seed 5000`
3. Confirm `/api/health` → `mcp.ok` and `clickhouse.ok`
4. Dry-run the golden prompt + an Assemble once so you know they land
5. Record on the **hosted URL** (the URL judges will click)

---

### 0:00–0:15 · The problem
> "Every production has a graveyard of drives — B-roll, logos, SFX — from projects
> nobody remembers. Teams re-shoot and re-license things they already own, and pay
> to store the duplicates."

**On screen:** the messy library, or the empty-library CTA.

### 0:15–0:45 · Ingest — Gemini actually watches the footage
- Click **Ingest sample pack**. Let the live crew trace run ~15s.
- **Linger on a video caption** in the Curator step and read it aloud — point out
  it describes what's *on screen* (motion, subject), which the filename never says.
> "Gemini doesn't read filenames — it watches the clip and hears the audio, writes
> a caption, and judges whether it's reusable. ClickHouse becomes the library's memory."

### 0:45–1:00 · Reusability, at scale
- Library sorted **By reusability**: logos/icons/B-roll on top, dialogue last.
- Point at the header totals — **thousands of assets, GBs**.
> "Evergreen material you can steal for the next video floats above what belongs to
> one shoot — across a real, full-size library."

### 1:00–2:05 · Golden path — the crew + MCP SQL  ★ hero 1
- Click **Golden prompt — 30s city product ad: reuse, waste, archive**
- **On screen, linger on the trace:**
  - the **delegation chip**: 📚 Librarian → 🔎 Analyst
  - `MCP · list_tables`
  - `MCP · run_select_query` with the `GROUP BY content_hash` waste query — call out
    the **reclaimable GB** (real, because the library is at scale)
  - `embed_brief` then the `cosineDistance` search
> "The Librarian doesn't guess. It hands the question to the Analyst, which queries
> ClickHouse through the official MCP server."
- Read the package: reuse slate (with *why*), duplicate waste in GB, archive
  candidates. Click **Archive** on one pair — "it waits for my approval."

### 2:05–2:40 · Assemble a cut — the Editor  ★ hero 2
- Scroll to **Assemble a cut**, enter the same brief, click **Assemble**.
- Watch the Editor pull candidates from ClickHouse, then render a **storyboard**:
  ordered shots mapped to beats (hook → establish → product → CTA), each with a
  real asset, duration, and *why it fits* — plus **gaps** to still shoot.
> "It doesn't just find assets — it cuts them into a sequence, and tells me exactly
> what I still need to shoot."

### 2:40–2:55 · Impact
> "That's hours of hunting and a reshoot you didn't need. Heuristic: unused reusable
> B-roll is hundreds of dollars each; the catalog shows real reclaimable storage.
> The library is live in ClickHouse Cloud; the agents speak SQL."

### 2:55–3:00 · Card
Hosted URL · GitHub · **ClickHouse track** · Gemini + ADK + mcp-clickhouse.

---

## Shot checklist
- [ ] Hosted `/api/health` shows `mcp.ok: true`
- [ ] Ingest shows a **video caption that describes on-screen content**, not the filename
- [ ] Golden prompt shows the **Librarian → Analyst** delegation chip
- [ ] **MCP** tool chips + `GROUP BY content_hash` / `cosineDistance` SQL visible
- [ ] Duplicate-waste query returns **real GB** (seeded at scale)
- [ ] Assemble renders a **storyboard with beats + gaps**
- [ ] 1080p+, steady cursor, captions on
- [ ] First 3 minutes only — Devpost truncates after that
