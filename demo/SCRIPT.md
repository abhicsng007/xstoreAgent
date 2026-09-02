# xStoreAgent — 3-minute demo script & storyboard

Target: ≤ 3:00, English (or English subtitles). Public on YouTube/Vimeo.
Judging maps to: **Tech implementation · Design · Impact · Idea.** Hit all four —
and because this is *Agentic Cinema*, make the agent's reasoning **visible**: the
live multi-agent crew and the Scout's web search are the beats that read as
"agentic," so give them screen time.

Before recording: `python scripts/reset_library.py --yes` for a clean start, then
run the ingest live on camera (the reasoning stream is the point). Re-run the
reset+ingest until the Gemini verdicts land how you like.

---

### 0:00–0:18 · The problem (hook)
> "Every production team has a graveyard of hard drives — B-roll, logos, SFX,
> music, VFX plates — from projects nobody remembers. So they re-shoot and
> re-license things they already own, and pay to store duplicates forever."

**On screen:** a messy folder of mixed media files.

### 0:18–0:50 · Ingest — watch the agent crew think (the agentic centerpiece)
- Paste a folder path → **Ingest & Organize**.
- Narrate: *"xStoreAgent isn't a black box. Watch its crew work in real time."*
- **On screen:** the live reasoning console — the crew strip lighting up as work
  hands off, color-coded steps streaming:
  - **Scanner 🔍** segregates every file by type (video/image/icon/vector/audio).
  - **Curator 🎬** captions each asset with Gemini and judges *reusable vs
    project-specific*, with its reasoning shown per file.
  - **Memory 🧠** embeds each caption and writes it to ClickHouse.
  - **Archivist 🗄️** flags duplicates and stale files for review.
- Let 2–3 real steps play out on camera — this is the "agentic" money shot.

### 0:50–1:08 · The partner: ClickHouse as the library's memory
- Narrate: *"Every asset — metadata AND a multimodal embedding — lands in
  ClickHouse. That's the library's long-term memory."*
- **On screen:** the Memory step committing to ClickHouse; optionally cut to a
  quick console query (`SELECT asset_type, count() FROM assets GROUP BY asset_type`)
  or the ClickHouse MCP toolset call in the ADK trace. Emphasize the partner.

### 1:08–1:35 · Sorted by reusability (a line straight from the idea)
- Narrate: *"The library ranks itself by reusability — what you can repurpose sits
  on top; what belongs to one video sinks to the bottom."*
- **On screen:** the **♻️ Repurposable** band (logos 96, icons 93, B-roll, music
  beds) with green reuse meters; scroll to the **📌 Project-specific** band where
  `voiceover_host_scene4.wav` ranks dead last (12/100, dialogue). Toggle
  **By reusability / Newest** once to show the sort is live.

### 1:35–2:08 · The magic: repurpose search (the cross-modal "wow")
- Type a new brief: *"upbeat 30-second product ad — city b-roll, brand logo,
  energetic music bed."* → **Surface reusable assets**.
- **On screen:** ranked results with % match — a *video* clip, a *logo vector*,
  and a *music* file all surface from a *text* brief.
- Narrate: *"Images, video, audio and text share one embedding space, so a text
  brief retrieves the right clip — a ClickHouse `cosineDistance` vector search."*

### 2:08–2:35 · The Storage Scout searches the web (second agentic beat)
- Narrate: *"As the library grows and your storage plan fills, a Scout agent goes
  and finds you room."* → click **Scout free storage**.
- **On screen:** the Scout's reasoning streams — *assesses usage → runs a live
  Google Search → surfaces ranked free-tier providers.* Point out the **actual
  search queries** in the trace (proof it hit the web) and the provider cards
  (MEGA 20 GB, Drive 15 GB…) tagged **web**.
- *(Optional: set `STORAGE_PLAN_GB` small in `.env` beforehand so the meter shows
  "approaching the cap" and the Scout reads as reactive.)*

### 2:35–2:48 · Reclaim storage (human-in-the-loop)
- Narrate: *"It flags duplicates and project-specific junk — but never deletes.
  You approve."* Click **Archive** on a duplicate; watch it drop from the library.

### 2:48–2:58 · Impact + close
> "xStoreAgent turns a creator's dead archive into a living, searchable library —
> less re-shooting, less re-licensing, less wasted storage. An asset librarian
> that actually reasons out loud."
- **On screen:** the tidy, reusability-ranked library. Mention: built with
  Gemini + Google ADK on Cloud Run, powered by ClickHouse.

### 2:58–3:00 · Card
- Hosted URL · GitHub repo · "ClickHouse track".

---

## Shot checklist
- [ ] `python scripts/reset_library.py --yes` then ingest `sample_assets` **live**
      on camera (the reasoning stream is the hero shot)
- [ ] Confirm the reusability bands look right (logos/icons top, voiceover bottom);
      re-run reset+ingest if a stock still lands in the wrong band
- [ ] Run `scripts/smoke_test.py` beforehand so live repurpose search returns good matches
- [ ] Pre-run the Scout once so you know the live queries return cleanly on the day
- [ ] Have one ClickHouse query / ADK trace ready to show the partner integration
- [ ] **Redeploy first:** `bash scripts/deploy.sh` — the hosted URL must run the
      current build (reasoning stream + reusability view + Scout)
- [ ] Record at 1080p+, steady cursor, captions on
