# ReelVault — 3-minute demo script & storyboard

Target: ≤ 3:00, English (or English subtitles). Public on YouTube/Vimeo.
Judging maps to: **Tech implementation · Design · Impact · Idea.** Hit all four.

---

### 0:00–0:20 · The problem (hook)
> "Every production team has a graveyard of hard drives — B-roll, logos, SFX,
> music, VFX plates — from projects nobody remembers. So they re-shoot and
> re-license things they already own, and pay to store duplicates forever."

**On screen:** messy folder of mixed media files.

### 0:20–0:40 · Ingest & organize
- In the dashboard, paste a folder path → **Ingest & Organize**.
- Narrate: *"ReelVault's Gemini agent walks the folder, classifies every file by
  type, and captions each one — deciding what's reusable versus project-specific."*
- **On screen:** library fills — per-type stat cards (video/image/icon/vector/
  audio), reusable badges.

### 0:40–1:05 · The partner: ClickHouse as the memory
- Narrate: *"Every asset — metadata AND a multimodal embedding — lands in
  ClickHouse. That's the library's memory."*
- **On screen:** briefly show a ClickHouse query in the console
  (`SELECT asset_type, count() FROM assets GROUP BY asset_type`), or the MCP
  toolset call in the ADK trace. Emphasize the partner integration.

### 1:05–1:55 · The magic: repurpose search (the "wow")
- Type a new project brief: *"upbeat 30-second product ad — city b-roll, brand
  logo, energetic music bed."* → **Surface reusable assets**.
- **On screen:** ranked results with % match — a *video* clip, a *logo vector*,
  a *music* file all surface from a *text* brief.
- Narrate: *"Because images, video, audio and text share one embedding space,
  a text brief retrieves the right clip — this is a ClickHouse `cosineDistance`
  vector search under the hood."*

### 1:55–2:30 · Reclaim storage (human-in-the-loop)
- Scroll to **Reclaim storage**: duplicate candidates + stale files.
- Narrate: *"It flags duplicates and project-specific junk — but never deletes.
  You approve."* Click **Archive** on a duplicate; watch it drop from the library.

### 2:30–2:55 · Impact + close
> "ReelVault turns a creator's dead archive into a living, searchable library —
> less re-shooting, less re-licensing, less wasted storage. An asset librarian
> that actually remembers."
- **On screen:** the tidy library + the ReelVault logo. Mention: built with
  Gemini + Google ADK on Cloud Run, powered by ClickHouse.

### 2:55–3:00 · Card
- Hosted URL · GitHub repo · "ClickHouse track".

---

## Shot checklist
- [ ] Clean sample library (~40–60 assets incl. a few true duplicates + stale files)
- [ ] Run `scripts/smoke_test.py` beforehand so live search returns good matches
- [ ] Have one ClickHouse query / ADK trace ready to show the partner integration
- [ ] Record at 1080p+, steady cursor, captions on
