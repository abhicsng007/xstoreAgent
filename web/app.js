// xStoreAgent dashboard — talks to the FastAPI backend in server/app.py.
const API = ""; // same origin

const TYPE_ICON = {
  video: "🎞️", image: "🖼️", icon: "◻️", vector: "✒️",
  audio: "🔊", document: "📄", other: "📦",
};
const PREVIEW_TYPES = new Set(["image", "icon", "vector"]);
const GOLDEN_PROMPT =
  "We're shooting a 30-second city product ad. What can we reuse, how much duplicate storage are we wasting, and what should I archive?";
const MCP_TOOLS = new Set([
  "list_tables", "list_databases", "run_select_query", "run_query",
]);

const fmtBytes = (b) => {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(b) / Math.log(1024));
  return `${(b / 1024 ** i).toFixed(1)} ${u[i]}`;
};

const escapeHtml = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Minimal Markdown -> HTML for the Librarian's final answer (headings, bold,
// italic, inline code, lists, tables, rules). The source is HTML-escaped first,
// so no raw markup from the model reaches the DOM.
function renderMarkdown(src) {
  const lines = escapeHtml(String(src).trim()).split(/\r?\n/);
  const inline = (t) =>
    t
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  const isTableSep = (l) =>
    /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(l);
  const splitRow = (l) =>
    l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
  const isBlockStart = (l, j) =>
    /^\s*(#{1,6})\s+/.test(l) || /^\s*[-*]\s+/.test(l) ||
    /^\s*\d+\.\s+/.test(l) || /^\s*---+\s*$/.test(l) ||
    (l.includes("|") && j + 1 < lines.length && isTableSep(lines[j + 1]));

  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    if (/^\s*---+\s*$/.test(line)) { out.push("<hr>"); i++; continue; }

    const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }

    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const th = splitRow(line).map((c) => `<th>${inline(c)}</th>`).join("");
      i += 2;
      const trs = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        trs.push(`<tr>${splitRow(lines[i]).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`);
        i++;
      }
      out.push(`<table><thead><tr>${th}</tr></thead><tbody>${trs.join("")}</tbody></table>`);
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`); i++;
      }
      out.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`); i++;
      }
      out.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    const para = [];
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i], i)) {
      para.push(lines[i]); i++;
    }
    out.push(`<p>${inline(para.join("<br>"))}</p>`);
  }
  return out.join("");
}

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

async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const chunks = buf.split("\n\n");
    buf = chunks.pop();
    for (const block of chunks) {
      const line = block.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try { onEvent(JSON.parse(line.slice(6))); } catch { /* ignore partial JSON */ }
    }
  }
}

let reusableBand = 50;

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
  const thumb = (a.id && PREVIEW_TYPES.has(a.asset_type))
    ? `<img class="thumb" src="${API}/api/preview/${a.id}" alt="" onerror="this.style.display='none'">`
    : `<div class="icon">${icon}</div>`;
  return `<div class="asset">
      ${thumb}
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

  const stats = document.getElementById("type-stats");
  if (!overview.length) {
    stats.innerHTML = `<div class="empty">Library is empty — ingest the sample pack to begin.</div>`;
  } else {
    stats.innerHTML = overview.map((r) => `
      <div class="stat">
        <div class="k">${TYPE_ICON[r.asset_type] || ""} ${r.asset_type}</div>
        <div class="v">${r.count}</div>
        <div class="sub">${fmtBytes(Number(r.bytes || 0))} · ${r.reusable} reusable</div>
      </div>`).join("");
  }

  const chips = [`<span class="chip ${!activeType ? "active" : ""}" data-t="">All</span>`]
    .concat(overview.map((r) =>
      `<span class="chip ${activeType === r.asset_type ? "active" : ""}" data-t="${r.asset_type}">${r.asset_type}</span>`));
  const filter = document.getElementById("type-filter");
  filter.innerHTML = chips.join("");
  filter.querySelectorAll(".chip").forEach((c) =>
    c.onclick = () => { activeType = c.dataset.t || null; loadLibrary(); loadAssets(); });

  loadAssets();
}

let sortMode = "reusability";

async function loadAssets() {
  const params = new URLSearchParams({ sort: sortMode });
  if (activeType) params.set("asset_type", activeType);
  const resp = await api("/api/assets?" + params.toString());
  const assets = resp.assets;
  if (resp.reusable_band != null) reusableBand = resp.reusable_band;

  const grid = document.getElementById("asset-grid");
  if (!assets.length) {
    grid.innerHTML = `<div class="empty">No assets${activeType ? " of this type" : ""} yet. Use <b>Ingest sample pack</b>.</div>`;
    return;
  }

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

// --- Ingest with live multi-agent reasoning ---
const CREW = [
  ["Scanner", "🔍"], ["Curator", "🎬"], ["Memory", "🧠"], ["Archivist", "🗄️"],
];
const SCOUT_CREW = [["Scout", "🛰️"]];
let currentCrew = CREW;
let crewState = {};

function renderCrew(activeName) {
  document.getElementById("crew").innerHTML = currentCrew.map(([name, ava]) => {
    const state = crewState[name] || "";
    const cls = name === activeName ? "active" : state;
    const tick = state === "done" ? "✓" : (name === activeName ? "▸" : "");
    return `<div class="member ${cls}">
        <span class="ava">${ava}</span><span class="nm">${name}</span>
        <span class="tick">${tick}</span>
      </div>`;
  }).join("");
}

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

function startIngestStream(url) {
  currentCrew = CREW;
  const card = document.getElementById("reasoning-card");
  const log = document.getElementById("reasoning-log");
  const status = document.getElementById("reasoning-status");
  card.hidden = false;
  log.innerHTML = "";
  crewState = {};
  renderCrew(null);
  status.textContent = "the crew is working…";
  card.scrollIntoView({ behavior: "smooth", block: "start" });

  const es = new EventSource(url);
  es.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch { return; }

    if (ev.type === "start") { status.textContent = `ingesting ${ev.root || "sample pack"}…`; return; }

    if (ev.type === "step") {
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
      log.lastChild.classList.add("summary");
      status.textContent = "done.";
      es.close();
      toast(`Ingested ${s.inserted ?? 0} assets from ${s.scanned ?? 0} files.`);
      loadLibrary(); loadStorage(); loadReview();
      return;
    }

    if (ev.type === "error") {
      reasoningStep({ agent: "System", icon: "⚠️", status: "error",
        title: "Ingest failed", detail: ev.message || "" });
      status.textContent = "failed.";
      es.close();
    }
  };
  es.onerror = () => { status.textContent = "connection closed."; es.close(); };
}

function ingestFromPath() {
  const root = document.getElementById("ingest-root").value.trim();
  const project = document.getElementById("ingest-project").value.trim();
  if (!root) {
    toast("Pick a folder path, or use Ingest sample pack.");
    return;
  }
  const qs = new URLSearchParams({ root, project }).toString();
  startIngestStream(`${API}/api/ingest/stream?${qs}`);
}

document.getElementById("ingest-form").onsubmit = (e) => {
  e.preventDefault();
  ingestFromPath();
};
document.getElementById("ingest-folder-btn").onclick = ingestFromPath;

document.getElementById("ingest-sample").onclick = () => {
  const project = document.getElementById("ingest-project").value.trim() || "demo";
  const qs = new URLSearchParams({ project }).toString();
  startIngestStream(`${API}/api/ingest/sample/stream?${qs}`);
};

// --- Librarian chat (MCP trace) ---
const chatSession = "web";

function chatAppend(html, cls = "") {
  const log = document.getElementById("chat-log");
  const row = document.createElement("div");
  row.className = `chat-row ${cls}`.trim();
  row.innerHTML = html;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return row;
}

function isMcpTool(name) {
  const n = (name || "").toLowerCase();
  return [...MCP_TOOLS].some((t) => n === t || n.endsWith("_" + t) || n.includes(t));
}

async function runChat(message) {
  const input = document.getElementById("chat-input");
  input.value = message;
  chatAppend(`<div class="bubble user">${message}</div>`, "from-user");
  const wait = chatAppend(`<div class="bubble sys">Librarian is querying ClickHouse MCP…</div>`, "from-sys");
  const askBtn = document.querySelector("#chat-form button");
  askBtn.disabled = true;
  try {
    const res = await fetch(API + "/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: chatSession }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    let replyEl = null;
    await readSSE(res, (ev) => {
      if (ev.type === "tool") {
        wait.remove();
        const mcp = isMcpTool(ev.name);
        const body = ev.status === "working" ? (ev.args || "") : (ev.result || "");
        chatAppend(
          `<div class="tool ${mcp ? "mcp" : ""} ${ev.status}">
             <span class="tname">${mcp ? "MCP" : "tool"} · ${ev.name}</span>
             ${body ? `<pre>${body}</pre>` : ""}
           </div>`,
          "from-tool",
        );
        return;
      }
      if (ev.type === "text" && ev.text) {
        wait.remove();
        if (!replyEl || ev.final) {
          replyEl = chatAppend(`<div class="bubble agent md"></div>`, "from-agent");
        }
        replyEl.querySelector(".bubble").innerHTML = renderMarkdown(ev.text);
      }
      if (ev.type === "error") {
        wait.remove();
        chatAppend(`<div class="bubble err">${ev.message || "agent error"}</div>`, "from-sys");
      }
    });
  } catch (err) {
    wait.remove();
    chatAppend(`<div class="bubble err">${err.message}</div>`, "from-sys");
  } finally {
    askBtn.disabled = false;
  }
}

document.getElementById("chat-form").onsubmit = (e) => {
  e.preventDefault();
  const msg = document.getElementById("chat-input").value.trim();
  if (!msg) return;
  runChat(msg);
};

document.getElementById("golden-prompt").onclick = () => runChat(GOLDEN_PROMPT);

async function loadHealth() {
  const badge = document.getElementById("mcp-badge");
  try {
    const h = await api("/api/health");
    const mcpOk = h.mcp && h.mcp.ok;
    const chOk = h.clickhouse && h.clickhouse.ok;
    badge.textContent = mcpOk && chOk
      ? "ClickHouse MCP live"
      : (!chOk ? "ClickHouse unreachable" : "MCP not ready");
    badge.classList.toggle("ok", mcpOk && chOk);
    badge.classList.toggle("bad", !(mcpOk && chOk));
  } catch {
    badge.textContent = "backend offline";
    badge.classList.add("bad");
  }
}

// --- Storage Scout ---
async function loadStorage() {
  const s = await api("/api/storage");
  const usedGb = (s.used_bytes / 1024 ** 3);
  const shown = Math.max(s.used_pct, s.used_pct > 0 ? 1.5 : 0);
  const warn = s.over_threshold;
  document.getElementById("storage-meter").innerHTML = `
    <div class="bar"><div class="fill ${warn ? "warn" : ""}" style="width:${Math.min(shown, 100)}%"></div></div>
    <div class="lbl">
      <b>${usedGb < 0.01 ? (s.used_bytes / 1024 ** 2).toFixed(1) + " MB" : usedGb.toFixed(2) + " GB"}</b>
      of ${s.plan_gb} GB plan used · <b>${s.used_pct}%</b>
      ${warn ? `<span class="alert">— over ${s.warn_pct}%, offload recommended</span>` : ""}
    </div>`;
}

function providerCard(p, top = false) {
  const src = p.source === "web" ? `<span class="psrc web">web</span>` : `<span class="psrc fallback">fallback</span>`;
  const link = p.url ? `<a href="${p.url}" target="_blank" rel="noopener noreferrer">${p.url}</a>` : "";
  return `<div class="provider ${top ? "top" : ""}">
      <div class="pname">${p.name} ${src}</div>
      <div><span class="gb">${p.free_gb} GB free</span></div>
      <div class="pnote">${p.note || ""}</div>
      ${link}
    </div>`;
}

function startScoutStream() {
  currentCrew = SCOUT_CREW;
  const card = document.getElementById("reasoning-card");
  const log = document.getElementById("reasoning-log");
  const status = document.getElementById("reasoning-status");
  const results = document.getElementById("scout-results");
  card.hidden = false;
  log.innerHTML = "";
  results.innerHTML = "";
  crewState = {};
  renderCrew("Scout");
  status.textContent = "the Scout is searching…";
  card.scrollIntoView({ behavior: "smooth", block: "start" });

  const es = new EventSource(`${API}/api/scout/stream`);
  es.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch { return; }
    if (ev.type === "step") { reasoningStep(ev); return; }
    if (ev.type === "done") {
      crewState["Scout"] = "done";
      renderCrew(null);
      const opts = ev.options || [];
      results.innerHTML = opts.map((p, i) => providerCard(p, i === 0)).join("");
      status.textContent = ev.grounded ? "done · sourced live from the web." : "done.";
      es.close();
      loadStorage();
      toast(`Scout found ${opts.length} free-storage options.`);
      return;
    }
    if (ev.type === "error") {
      reasoningStep({ agent: "Scout", icon: "⚠️", status: "error",
        title: "Scout failed", detail: ev.message || "" });
      status.textContent = "failed.";
      es.close();
    }
  };
  es.onerror = () => { status.textContent = "connection closed."; es.close(); };
}

document.getElementById("scout-btn").onclick = startScoutStream;

// --- Review ---
async function loadReview() {
  const { duplicates, stale } = await api("/api/review");
  const parts = [];

  parts.push(`<h3 style="margin:14px 0 8px;font-size:14px">Duplicate candidates</h3>`);
  if (duplicates.length) {
    parts.push(duplicates.map((d) => `
      <div class="dup">
        <div class="pair">
          <div>${TYPE_ICON[d.asset_type] || ""} <b>${d.file_a}</b> ↔ ${d.file_b}</div>
          <div class="dist">${d.kind === "exact" ? "exact hash" : "near"} · distance ${Number(d.distance).toFixed(3)}
            ${d.wasted_bytes ? " · " + fmtBytes(d.wasted_bytes) + " reclaimable" : ""}</div>
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
    loadLibrary(); loadStorage(); loadReview();
  } catch (err) { toast(`Action failed: ${err.message}`, 4000); }
};

document.getElementById("refresh-review").onclick = loadReview;

// --- Boot ---
(async function boot() {
  try {
    await loadHealth();
    await loadLibrary();
    await loadStorage();
    await loadReview();
  } catch (err) { toast(`Backend not reachable: ${err.message}`, 6000); }
})();
