# xStoreAgent — 3-minute hackathon demo

**Target:** 2:50–3:00. English VO (or English subtitles). Public on YouTube / Vimeo.
**Track:** ClickHouse · Gemini + Google ADK · mcp-clickhouse · Cloud Run
**Devpost truncates after 3:00.** First three minutes only.

Two money shots judges must see on screen, not just hear:

1. **Librarian → Analyst** delegation, then **MCP** chips: `list_tables` and `run_select_query` with real SQL (`GROUP BY content_hash`, `cosineDistance`).
2. **Editor Assemble** — a storyboard of real library assets mapped to beats, plus gaps still to shoot.

Spoken VO is ~430 words (~145 wpm). Pauses are built in so the UI can land. Do not ad-lib over the MCP SQL — let it sit on screen.

---

## Before you hit record

Do this on the **hosted Cloud Run URL** (the URL judges will click). Localhost is a backup only.

```bash
python scripts/fetch_demo_pack.py
python scripts/reset_library.py --yes --ingest sample_assets --project demo --seed 5000
```

Then:

1. Open `/api/health` — `mcp.ok` and `clickhouse.ok` must both be true. Badge in the UI should read **ClickHouse MCP live**.
2. Dry-run **Golden prompt** once. Confirm you see:
   - `📚 Librarian → delegates to 🔎 Analyst`
   - `MCP · list_tables`
   - `MCP · run_select_query` with `GROUP BY content_hash` and a **reclaimable GB** number
   - `embed_brief` then a `cosineDistance` query
   - a reuse slate + archive candidates
3. Dry-run **Assemble** with: `30s upbeat city product ad with a strong hook and a clear CTA`
   Confirm a storyboard with Hook / Establish / Product / CTA, a music bed, and at least one gap.
4. Click **Ingest sample pack** once in a throwaway take so you know how long the live crew trace runs. If it is >20s, skip live ingest in the take and open a pre-ingested library (the seed already did this).
5. Browser: 1920×1080, zoom 100–110%, hide bookmarks bar, dark OS chrome. Cursor large. Captions on in the editor, not burned into a busy UI.

**If MCP is slow on the take:** keep talking; do not refresh. The SQL chips are the shot. If the golden prompt errors, cut to the dry-run recording of that beat (keep one as B-roll).

---

## Teleprompter script (word-for-word)

Stage directions in `[brackets]` are not spoken. **Bold** = linger / zoom.

---

### 0:00–0:18 · The graveyard

**On screen:** full dashboard, library already loaded (thousands of rows, GB in the header). Slow push-in on the messy grid. Cursor idle.

> Every production has a graveyard of drives. B-roll, logos, sound effects — from projects nobody remembers. Teams re-shoot and re-license things they already own, and they pay to store the duplicates.
>
> xStoreAgent is a Librarian agent that gives a film team's media library a brain.

---

### 0:18–0:48 · Gemini actually watches the footage

**On screen:** click **Ingest sample pack**. Let the **🧠 Agent crew · live reasoning** card run ~12–15s. Zoom the Curator / classify step. Click one video thumbnail (e.g. neon street or aerial downtown) and **read the caption**, not the filename.

> Point it at a folder. Gemini does not read filenames. It watches the clip, hears the audio, writes a caption, and judges whether the shot is reusable.
>
> Look — this caption describes the motion on screen. The filename never said that. ClickHouse Cloud is the library's memory: metadata, a caption embedding for search, and a visual embedding that catches near-duplicates even when the encoding is different.

**Backup if ingest is already done:** skip the button. Open a video in the lightbox, read the caption, then the same VO from “Look — this caption…”

---

### 0:48–1:02 · Reusability, at scale

**On screen:** Library card. Confirm sort is **By reusability**. Point at header totals (asset count + storage). Hover logos / B-roll on top, then a dialogue/slate near the bottom.

> Sorted by reusability. Evergreen B-roll, logos, and icons float. Dialogue and slates sink. This is not a toy folder — thousands of assets, real gigabytes — so the numbers you are about to see are computed at production scale.

---

### 1:02–2:12 · Golden path — crew + MCP SQL  ★ hero 1

**On screen:** scroll to **Librarian**. Click **Golden prompt — 30s city product ad: reuse, waste, archive**.

Do not talk over the first two seconds of the trace. Then call the chips out as they appear, cursor on each:

1. Delegation: **📚 Librarian → delegates to 🔎 Analyst**
2. **MCP · list_tables**
3. **MCP · run_select_query** — linger on `GROUP BY content_hash` and `wasted_bytes`. Say the **reclaimable GB** number out loud (whatever the query returns; do not invent it).
4. **embed_brief**, then the `cosineDistance` JOIN against `brief_queries`.
5. Scroll the Analyst's package: reuse slate, waste, archive candidates.
6. Click **Archive** on one duplicate pair in **Reclaim storage** (or from the chat, if it offers an id). Pause on the confirmation.

> Ask in English: we are shooting a thirty-second city product ad. What can we reuse, how much duplicate storage are we wasting, and what should I archive?
>
> *[pause — let the delegation chip land]*
>
> The Librarian does not guess. It hands the question to the Analyst. The Analyst queries ClickHouse through the official MCP server — not a Python wrapper. `list_tables`. Then `run_select_query`. This is the waste query: group by content hash. That is reclaimable storage sitting in extra copies.
>
> Then it embeds the brief and searches with cosine distance. One embedding space — so a text brief can retrieve video, a still, audio, or a logo.
>
> The package: a reuse slate, with *why* each shot fits. Duplicate waste, in gigabytes. Archive candidates. Nothing is deleted. I approve each archive.

---

### 2:12–2:42 · Assemble a cut — the Editor  ★ hero 2

**On screen:** **✂️ Assemble a cut**. Paste:

`30s upbeat city product ad with a strong hook and a clear CTA`

Click **Assemble**. Watch the Editor trace, then the storyboard. Cursor along Hook → Establish → Product → CTA. Point at duration + why. End on **🎯 Still to shoot / source**.

> Finding assets is not the job. Cutting them is. Same brief — Assemble.
>
> The Editor pulls reusable shots from ClickHouse and lays them on a storyboard: hook, establish, product, call to action. Each card is a real asset from this library, a duration, and why it fits. And the gaps — what we still have to shoot, so we do not waste a day on footage we already own.

---

### 2:42–2:55 · Impact

**On screen:** hold the storyboard; optional 1s cut back to the waste GB number.

> That is hours of hunting, and a reshoot you did not need. Unused reusable B-roll is hundreds of dollars each. The catalog is live in ClickHouse Cloud. The agents speak SQL.

---

### 2:55–3:00 · End card

**On screen:** 5-second card, high contrast, no UI chrome.

```
xStoreAgent
AI Asset Librarian for film / video teams

Gemini + Google ADK  ·  ClickHouse MCP  ·  Cloud Run

<hosted URL>
github.com/<your-org>/xStoreAgent
```

> xStoreAgent. Link in the description.

**Hard out at 3:00.** Do not keep talking.

---

## Timed VO (copy into a teleprompter)

One block, no stage directions. Pause where you see `/`.

> Every production has a graveyard of drives. B-roll, logos, sound effects — from projects nobody remembers. Teams re-shoot and re-license things they already own, and they pay to store the duplicates. xStoreAgent is a Librarian agent that gives a film team's media library a brain. /
>
> Point it at a folder. Gemini does not read filenames. It watches the clip, hears the audio, writes a caption, and judges whether the shot is reusable. Look — this caption describes the motion on screen. The filename never said that. ClickHouse Cloud is the library's memory: metadata, a caption embedding for search, and a visual embedding that catches near-duplicates even when the encoding is different. /
>
> Sorted by reusability. Evergreen B-roll, logos, and icons float. Dialogue and slates sink. This is not a toy folder — thousands of assets, real gigabytes — so the numbers you are about to see are computed at production scale. /
>
> Ask in English: we are shooting a thirty-second city product ad. What can we reuse, how much duplicate storage are we wasting, and what should I archive? /
>
> The Librarian does not guess. It hands the question to the Analyst. The Analyst queries ClickHouse through the official MCP server — not a Python wrapper. List tables. Then run select query. This is the waste query: group by content hash. That is reclaimable storage sitting in extra copies. Then it embeds the brief and searches with cosine distance. One embedding space — so a text brief can retrieve video, a still, audio, or a logo. The package: a reuse slate, with why each shot fits. Duplicate waste, in gigabytes. Archive candidates. Nothing is deleted. I approve each archive. /
>
> Finding assets is not the job. Cutting them is. Same brief — Assemble. The Editor pulls reusable shots from ClickHouse and lays them on a storyboard: hook, establish, product, call to action. Each card is a real asset from this library, a duration, and why it fits. And the gaps — what we still have to shoot, so we do not waste a day on footage we already own. /
>
> That is hours of hunting, and a reshoot you did not need. Unused reusable B-roll is hundreds of dollars each. The catalog is live in ClickHouse Cloud. The agents speak SQL. xStoreAgent. Link in the description.

**Word count:** ~430 · **Target duration:** 2:50 plus end card.

---

## Shot list (edit order)

| # | Time    | Picture                                      | Audio                         | Must-see |
|---|---------|----------------------------------------------|-------------------------------|----------|
| 1 | 0:00    | Library grid, header GB/count                | Problem VO                    | Scale    |
| 2 | 0:18    | Ingest crew trace **or** video lightbox      | Gemini watches / hears        | Caption ≠ filename |
| 3 | 0:48    | Library · By reusability                     | Evergreen floats              | Sort toggle |
| 4 | 1:02    | Golden prompt click                          | Ask in English                | Button   |
| 5 | 1:10    | Delegation chip Librarian → Analyst          | “does not guess”              | ★        |
| 6 | 1:18    | MCP `list_tables`                            | “official MCP server”         | ★        |
| 7 | 1:25    | MCP SQL `GROUP BY content_hash` + GB         | Say the GB number             | ★        |
| 8 | 1:40    | `embed_brief` + `cosineDistance`             | Cross-modal search            | ★        |
| 9 | 1:52    | Reuse slate + Archive click                  | “I approve each archive”      | Human-in-loop |
|10 | 2:12    | Assemble button + Editor trace               | “Cutting them is”             |          |
|11 | 2:22    | Storyboard beats + gap row                   | Gaps to shoot                 | ★        |
|12 | 2:42    | Hold storyboard / cut to waste GB            | Impact                        |          |
|13 | 2:55    | End card                                     | Name + link                   | URL      |

---

## Judging axes — make sure each is visible

| Axis   | Where it lands in the video |
|--------|-----------------------------|
| **Idea**   | 0:00–0:18 library with a brain; reuse vs reshoot |
| **Tech**   | 1:02–2:12 ADK sub-agent transfer, official mcp-clickhouse, caption + visual embeddings |
| **Design** | Live crew trace, golden prompt, storyboard beats, lightbox |
| **Impact** | Reclaimable GB at seeded scale; archive-with-approval; “hours of hunting / a reshoot you didn’t need” |

ClickHouse track eligibility on camera: **MCP tool chips**, not just the dashboard grid. The grid uses `clickhouse-connect`; judges need to see `list_tables` / `run_select_query`.

---

## Recording notes

- 1080p60 screen + separate VO if you can. If one take, speak slightly slower than you think.
- Cursor: click, then **stop moving** for 1s so the chip is readable.
- Zoom 125–150% on the chat trace for shots 5–8. Zoom back out for the storyboard.
- Never show `.env`, passwords, or a failed `/api/health`.
- If the Analyst names a dollar figure, it is a **heuristic** (the prompt already labels it). Do not present it as a quote from a customer.
- Captions/subtitles: burn them in the editor for sound-off judges.
- Music: none, or a bed under 12 dB. Do not drown the VO.
- Export H.264, 16:9, under whatever Devpost file-size cap is. Put the **hosted URL in the video description and on the end card**.

---

## Shot checklist (tick before upload)

- [ ] Hosted `/api/health` shows `mcp.ok: true` and `clickhouse.ok: true`
- [ ] Ingest or lightbox shows a **video caption that describes on-screen content**, not the filename
- [ ] Golden prompt shows **Librarian → Analyst** delegation chip
- [ ] **MCP** tool chips + `GROUP BY content_hash` / `cosineDistance` SQL visible and readable
- [ ] Duplicate-waste query returns **real GB** (library seeded at ~5000 rows)
- [ ] Archive is an explicit click — nothing auto-deletes
- [ ] Assemble renders a **storyboard with beats + gaps**
- [ ] End card has hosted URL + GitHub + **ClickHouse track**
- [ ] 1080p+, steady cursor, captions on
- [ ] Runtime ≤ 3:00 — Devpost truncates after that
