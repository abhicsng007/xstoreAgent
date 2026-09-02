# xStoreAgent — 3-minute demo script & storyboard

Target: ≤ 3:00, English (or English subtitles). Public on YouTube/Vimeo.
Show the **running product**, not a cinematic trailer. Hit all four judging
axes (Tech · Design · Impact · Idea). The ClickHouse-judge money shot is the
Librarian calling **mcp-clickhouse** (`list_tables` / `run_select_query`) with
SQL on screen.

Before recording:
1. `python scripts/reset_library.py --yes --ingest sample_assets --project demo`
2. Confirm `/api/health` → `mcp.ok` and `clickhouse.ok`
3. Dry-run the golden prompt once so you know the SQL lands
4. Redeploy if you changed code: `bash scripts/deploy.sh`
5. Record on the **hosted URL** (the URL judges will click)

Do **not** show Storage Scout.

---

### 0:00–0:15 · The problem
> "Every production has a graveyard of drives — B-roll, logos, SFX — from
> projects nobody remembers. Teams re-shoot and re-license things they already
> own, and pay to store the duplicates."

**On screen:** messy `sample_assets` folder (or the empty-library CTA).

### 0:15–0:40 · Ingest (keep it short)
- Click **Ingest sample pack** (or jump in if the library is already loaded).
- 10–15 seconds of the crew trace is enough: Curator captions with Gemini,
  Memory writes to ClickHouse.
- Narrate: *"Gemini captions each asset. ClickHouse is the library's memory."*

If the library is pre-loaded, skip live ingest and show the ranked grid instead.

### 0:40–0:55 · Reusability (the idea)
- Library sorted **By reusability**: logos/icons/B-roll on top, dialogue last.
> "What you can steal for the next video sits above what belongs to one shoot."

### 0:55–2:25 · Golden path — Librarian + MCP SQL  ★ hero
- Click **Golden prompt — 30s city product ad: reuse, waste, archive**
- Narrate: *"The agent doesn't guess. It plans, then queries ClickHouse through
  the official MCP server."*
- **On screen, linger on the trace:**
  - `MCP · list_tables`
  - `MCP · run_select_query` with the rollup / `GROUP BY content_hash` waste query
  - `embed_brief` then `cosineDistance` SELECT (vector array may be truncated — that's fine)
- Read the package out loud as it appears:
  1. Reuse slate (city b-roll, logo, music) and *why*
  2. Duplicate waste in bytes
  3. Archive candidates — "it waits for me to approve"
- Optional: click **Archive duplicate** on one pair.

### 2:25–2:45 · Impact
> "That's hours of hunting and a reshoot you didn't need. Heuristic: unused
> reusable B-roll is hundreds of dollars each. The catalog is live in ClickHouse
> Cloud; the agent speaks SQL."

**On screen:** tidy library + chat package.

### 2:45–3:00 · Card
Hosted URL · GitHub · **ClickHouse track** · Gemini + ADK + mcp-clickhouse.

---

## Shot checklist
- [ ] Hosted `/api/health` shows `mcp.ok: true`
- [ ] Golden prompt shows **MCP** tool chips (not only function tools)
- [ ] SQL `GROUP BY content_hash` or `cosineDistance` visible
- [ ] Sample library has duplicates (`city_broll_01` + copy, skyline dup)
- [ ] No Scout in the cut
- [ ] 1080p+, steady cursor, captions on
- [ ] First 3 minutes only — Devpost truncates after that
