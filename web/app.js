// xStoreAgent dashboard — talks to the FastAPI backend in server/app.py.
const API = ""; // same origin

const TYPE_ICON = {
  video: "🎞️", image: "🖼️", icon: "◻️", vector: "✒️",
  audio: "🔊", document: "📄", other: "📦",
};
const fmtBytes = (b) => {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(b) / Math.log(1024));
  return `${(b / 1024 ** i).toFixed(1)} ${u[i]}`;
};

async function api(path, opts) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function toast(msg, ms = 3200) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}

let reusableBand = 50; // divider between repurposable and project-specific (from API)

function assetCard(a, { showScore = false } = {}) {
  const icon = TYPE_ICON[a.asset_type] || "📦";
  const tags = (a.tags || []).slice(0, 5).map((t) => `<span class="tag">${t}</span>`).join("");
  const badge = a.reusable
    ? `<span class="badge reusable">reusable</span>`
    : `<span class="badge stale">stale</span>`;
  const score = showScore && a.match_score != null
    ? `<span class="score">${a.match_score}% match</span>` : "";
  const rs = a.reusability_score;
  const meter = rs != null ? `
    <div class="reuse-meter">
      <div class="track"><div class="fill ${rs >= reusableBand ? "hi" : "lo"}" style="width:${rs}%"></div></div>
      <span class="rs">${rs}/100 reuse</span>
    </div>` : "";
  const subtype = a.asset_subtype
    ? `<div class="subtype">${a.asset_subtype.replace(/_/g, " ")}</div>` : "";
  return `<div class="asset">
      <div class="icon">${icon}</div>
      <div class="name">${a.filename || ""}</div>
      <div class="cap">${a.caption || "<em>uncaptioned</em>"}</div>
      ${subtype}
      <div class="tags">${tags}</div>
      ${meter}
      <div class="foot">${badge}${score}</div>
    </div>`;
}

// --- Library overview + grid ---
let activeType = null;

async function loadLibrary() {
  const { overview } = await api("/api/library");
  const totalBytes = overview.reduce((s, r) => s + Number(r.bytes || 0), 0);
  const totalFiles = overview.reduce((s, r) => s + Number(r.count || 0), 0);
  document.getElementById("storage-summary").textContent =
    `${totalFiles} assets · ${fmtBytes(totalBytes)}`;

  document.getElementById("type-stats").innerHTML = overview.map((r) => `
    <div class="stat">
      <div class="k">${TYPE_ICON[r.asset_type] || ""} ${r.asset_type}</div>
      <div class="v">${r.count}</div>
      <div class="sub">${fmtBytes(Number(r.bytes || 0))} · ${r.reusable} reusable</div>
    </div>`).join("") || `<div class="empty">Library is empty — ingest a folder to begin.</div>`;

  const chips = [`<span class="chip ${!activeType ? "active" : ""}" data-t="">All</span>`]
    .concat(overview.map((r) =>
      `<span class="chip ${activeType === r.asset_type ? "active" : ""}" data-t="${r.asset_type}">${r.asset_type}</span>`));
  const filter = document.getElementById("type-filter");
  filter.innerHTML = chips.join("");
  filter.querySelectorAll(".chip").forEach((c) =>
    c.onclick = () => { activeType = c.dataset.t || null; loadLibrary(); loadAssets(); });

  loadAssets();
}

let sortMode = "reusability"; // reusability | newest

async function loadAssets() {
  const params = new URLSearchParams({ sort: sortMode });
  if (activeType) params.set("asset_type", activeType);
  const resp = await api("/api/assets?" + params.toString());
  const assets = resp.assets;
  if (resp.reusable_band != null) reusableBand = resp.reusable_band;

  const grid = document.getElementById("asset-grid");
  if (!assets.length) {
    grid.innerHTML = `<div class="empty">No assets${activeType ? " of this type" : ""} yet.</div>`;
    return;
  }

  // In reusability order, split the grid into a repurposable band and a
  // project-specific band with labelled dividers; otherwise a flat grid.
  if (sortMode === "reusability") {
    const hi = assets.filter((a) => (a.reusability_score ?? 0) >= reusableBand);
    const lo = assets.filter((a) => (a.reusability_score ?? 0) < reusableBand);
    const parts = [];
    if (hi.length) {
      parts.push(`<div class="band-label reuse">♻️ Repurposable · reuse across projects</div>`);
      parts.push(hi.map((a) => assetCard(a)).join(""));
    }
    if (lo.length) {
      parts.push(`<div class="band-label unique">📌 Project-specific · unique to one video</div>`);
      parts.push(lo.map((a) => assetCard(a)).join(""));
    }
    grid.innerHTML = parts.join("");
  } else {
    grid.innerHTML = assets.map((a) => assetCard(a)).join("");
  }
}

// Sort toggle (By reusability | Newest)
document.getElementById("sort-toggle").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg");
  if (!btn || btn.dataset.sort === sortMode) return;
  sortMode = btn.dataset.sort;
  document.querySelectorAll("#sort-toggle .seg").forEach((s) =>
    s.classList.toggle("active", s.dataset.sort === sortMode));
  loadAssets();
});

// --- Repurpose search ---
document.getElementById("search-form").onsubmit = async (e) => {
  e.preventDefault();
  const brief = document.getElementById("search-brief").value.trim();
  if (!brief) return;
  const box = document.getElementById("search-results");
  box.innerHTML = `<div class="spin">Searching the library…</div>`;
  try {
    const { results } = await api("/api/search", {
      method: "POST", body: JSON.stringify({ brief, limit: 12 }),
    });
    box.innerHTML = results.map((a) => assetCard(a, { showScore: true })).join("")
      || `<div class="empty">No matching assets found. Try ingesting more, or a different brief.</div>`;
  } catch (err) { box.innerHTML = `<div class="empty">Search failed: ${err.message}</div>`; }
};

// --- Ingest with live multi-agent reasoning (Server-Sent Events) ---
const CREW = [
  ["Scanner", "🔍"], ["Curator", "🎬"], ["Memory", "🧠"], ["Archivist", "🗄️"],
];

function renderCrew(activeName) {
  document.getElementById("crew").innerHTML = CREW.map(([name, ava]) => {
    const state = crewState[name] || "";
    const cls = name === activeName ? "active" : state;
    const tick = state === "done" ? "✓" : (name === activeName ? "▸" : "");
    return `<div class="member ${cls}">
        <span class="ava">${ava}</span><span class="nm">${name}</span>
        <span class="tick">${tick}</span>
      </div>`;
  }).join("");
}

let crewState = {};

function reasoningStep(ev) {
  const log = document.getElementById("reasoning-log");
  const row = document.createElement("div");
  row.className = `rstep ${ev.status || "info"}`;
  row.innerHTML = `
    <span class="rdot"></span>
    <span class="ricon">${ev.icon || "•"}</span>
    <div class="rbody">
      <div class="rhead"><span class="ragent">${ev.agent || ""}</span>
        <span class="rtitle">${ev.title || ""}</span></div>
      ${ev.detail ? `<div class="rdetail">${ev.detail}</div>` : ""}
    </div>`;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function startIngestStream(root, project) {
  const card = document.getElementById("reasoning-card");
  const log = document.getElementById("reasoning-log");
  const status = document.getElementById("reasoning-status");
  card.hidden = false;
  log.innerHTML = "";
  crewState = {};
  renderCrew(null);
  status.textContent = "the crew is working…";
  card.scrollIntoView({ behavior: "smooth", block: "start" });

  const qs = new URLSearchParams({ root, project }).toString();
  const es = new EventSource(`${API}/api/ingest/stream?${qs}`);

  es.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch { return; }

    if (ev.type === "start") { status.textContent = `ingesting ${ev.root}…`; return; }

    if (ev.type === "step") {
      // A "done" step retires that agent; anything else marks it active.
      if (ev.status === "done") crewState[ev.agent] = "done";
      renderCrew(ev.status === "done" ? null : ev.agent);
      reasoningStep(ev);
      return;
    }

    if (ev.type === "done") {
      const s = ev.summary || {};
      CREW.forEach(([n]) => (crewState[n] = "done"));
      renderCrew(null);
      reasoningStep({
        agent: "Librarian", icon: "✅", status: "done", title: "Library updated",
        detail: `${s.inserted ?? 0} assets remembered from ${s.scanned ?? 0} files.`,
      });
      // Flag the closing line as the amber summary card.
      log.lastChild.classList.add("summary");
      status.textContent = "done.";
      es.close();
      toast(`Ingested ${s.inserted ?? 0} assets from ${s.scanned ?? 0} files.`);
      loadLibrary(); loadReview();
      return;
    }

    if (ev.type === "error") {
      reasoningStep({ agent: "System", icon: "⚠️", status: "error",
        title: "Ingest failed", detail: ev.message || "" });
      status.textContent = "failed.";
      es.close();
    }
  };

  es.onerror = () => {
    status.textContent = "connection closed.";
    es.close();
  };
}

document.getElementById("ingest-form").onsubmit = (e) => {
  e.preventDefault();
  const root = document.getElementById("ingest-root").value.trim();
  const project = document.getElementById("ingest-project").value.trim();
  if (!root) return;
  startIngestStream(root, project);
};

// --- Review: duplicates + stale ---
async function loadReview() {
  const { duplicates, stale } = await api("/api/review");
  const parts = [];

  parts.push(`<h3 style="margin:14px 0 8px;font-size:14px">Duplicate candidates</h3>`);
  if (duplicates.length) {
    parts.push(duplicates.map((d) => `
      <div class="dup">
        <div class="pair">
          <div>${TYPE_ICON[d.asset_type] || ""} <b>${d.file_a}</b> ↔ ${d.file_b}</div>
          <div class="dist">distance ${Number(d.distance).toFixed(3)} · same ${d.asset_type}</div>
        </div>
        <div class="actions">
          <button class="small danger" onclick="approve('${d.id_b}','archive')">Archive duplicate</button>
        </div>
      </div>`).join(""));
  } else parts.push(`<div class="empty">No duplicates found.</div>`);

  parts.push(`<h3 style="margin:18px 0 8px;font-size:14px">Stale / project-specific</h3>`);
  if (stale.length) {
    parts.push(stale.map((a) => `
      <div class="dup">
        <div class="pair">
          <div>${TYPE_ICON[a.asset_type] || ""} <b>${a.filename}</b></div>
          <div class="dist">${a.caption || ""}</div>
        </div>
        <div class="actions">
          <button class="small ghost" onclick="approve('${a.id}','keep')">Keep</button>
          <button class="small danger" onclick="approve('${a.id}','archive')">Archive</button>
        </div>
      </div>`).join(""));
  } else parts.push(`<div class="empty">Nothing flagged as stale.</div>`);

  document.getElementById("review-list").innerHTML = parts.join("");
}

window.approve = async (assetId, action) => {
  try {
    await api("/api/approve", { method: "POST", body: JSON.stringify({ asset_id: assetId, action }) });
    toast(action === "archive" ? "Archived." : "Kept.");
    loadLibrary(); loadReview();
  } catch (err) { toast(`Action failed: ${err.message}`, 4000); }
};

document.getElementById("refresh-review").onclick = loadReview;

// --- Boot ---
(async function boot() {
  try { await loadLibrary(); await loadReview(); }
  catch (err) { toast(`Backend not reachable: ${err.message}`, 6000); }
})();
