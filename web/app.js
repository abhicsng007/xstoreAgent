// ReelVault dashboard — talks to the FastAPI backend in server/app.py.
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

function assetCard(a, { showScore = false } = {}) {
  const icon = TYPE_ICON[a.asset_type] || "📦";
  const tags = (a.tags || []).slice(0, 5).map((t) => `<span class="tag">${t}</span>`).join("");
  const badge = a.reusable
    ? `<span class="badge reusable">reusable</span>`
    : `<span class="badge stale">stale</span>`;
  const score = showScore && a.match_score != null
    ? `<span class="score">${a.match_score}% match</span>` : "";
  return `<div class="asset">
      <div class="icon">${icon}</div>
      <div class="name">${a.filename || ""}</div>
      <div class="cap">${a.caption || "<em>uncaptioned</em>"}</div>
      <div class="tags">${tags}</div>
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

async function loadAssets() {
  const q = activeType ? `?asset_type=${encodeURIComponent(activeType)}` : "";
  const { assets } = await api("/api/assets" + q);
  document.getElementById("asset-grid").innerHTML =
    assets.map((a) => assetCard(a)).join("") ||
    `<div class="empty">No assets${activeType ? " of this type" : ""} yet.</div>`;
}

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

// --- Ingest ---
document.getElementById("ingest-form").onsubmit = async (e) => {
  e.preventDefault();
  const root = document.getElementById("ingest-root").value.trim();
  const project = document.getElementById("ingest-project").value.trim();
  if (!root) return;
  toast("Ingesting… classifying, captioning and embedding assets.");
  try {
    const r = await api("/api/ingest", {
      method: "POST", body: JSON.stringify({ root, project }),
    });
    toast(`Ingested ${r.inserted} assets from ${r.scanned} files.`);
    loadLibrary(); loadReview();
  } catch (err) { toast(`Ingest failed: ${err.message}`, 5000); }
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
