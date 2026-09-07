// xStoreAgent dashboard — talks to the FastAPI backend in server/app.py.
const API = ""; // same origin

const TYPE_ICON = {
  video: "🎞️", image: "🖼️", icon: "◻️", vector: "✒️",
  audio: "🔊", document: "📄", other: "📦",
};
const PREVIEW_TYPES = new Set(["image", "icon", "vector", "video"]);
const PAGE_SIZE = 24;
const REVIEW_PAGE = 8;
const GOLDEN_PROMPT =
  "We're shooting a 30-second city product ad. What can we reuse, how much duplicate storage are we wasting, and what should I archive?";
const MCP_TOOLS = new Set([
  "list_tables", "list_databases", "run_select_query", "run_query",
]);

// The Librarian crew — for badging which agent authored each trace step.
const AGENT_META = {
  librarian: { icon: "📚", label: "Librarian" },
  analyst:   { icon: "🔎", label: "Analyst" },
  archivist: { icon: "🗄️", label: "Archivist" },
  scout:     { icon: "🛰️", label: "Scout" },
  curator:   { icon: "🎬", label: "Curator" },
  editor:    { icon: "✂️", label: "Editor" },
};
const agentMeta = (name) => AGENT_META[(name || "").toLowerCase()] || null;
function agentBadge(name) {
  const m = agentMeta(name);
  return m ? `<span class="agent-badge ${(name || "").toLowerCase()}">${m.icon} ${m.label}</span>` : "";
}

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
let assetOffset = 0;
let dupOffset = 0;
let staleOffset = 0;

function thumbHtml(a) {
  const icon = TYPE_ICON[a.asset_type] || "📦";
  const kind = a.preview_kind || (PREVIEW_TYPES.has(a.asset_type) ? "image" : "none");
  const fallback = `<div class="thumb placeholder"><span class="icon">${icon}</span></div>`;
  if (a.has_preview && (kind === "image" || kind === "video") && a.id) {
    const src = `${API}/api/preview/${a.id}`;
    return `<img class="thumb" src="${src}" alt=""
      onerror="this.className='thumb placeholder';this.removeAttribute('src');this.alt='';this.outerHTML='<div class=\\'thumb placeholder\\'><span class=\\'icon\\'>${icon}</span></div>'">`;
  }
  if (a.has_preview && kind === "audio") {
    return `<div class="thumb audio-thumb"><span class="icon">${icon}</span>
      <span class="play-hint">Play</span></div>`;
  }
  return fallback;
}

function assetCard(a, { showScore = false } = {}) {
  const tags = (a.tags || []).slice(0, 5).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
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
    ? `<div class="subtype">${escapeHtml(String(a.asset_subtype).replace(/_/g, " "))}</div>` : "";
  return `<div class="asset" role="button" tabindex="0" data-asset-id="${a.id || ""}">
      ${thumbHtml(a)}
      <div class="name">${escapeHtml(a.filename || "")}</div>
      <div class="cap">${a.caption ? escapeHtml(a.caption) : "<em>uncaptioned</em>"}</div>
      ${subtype}
      <div class="tags">${tags}</div>
      ${meter}
      <div class="foot">${badge}${score}</div>
    </div>`;
}

function renderPager(el, { total, limit, offset, onChange }) {
  if (!el) return;
  const pages = Math.max(1, Math.ceil((total || 0) / limit) || 1);
  const page = Math.floor((offset || 0) / limit) + 1;
  if (!total) { el.innerHTML = ""; return; }
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  const btn = (p, label, opts = {}) => {
    const cur = p === page;
    const dis = opts.disabled || p < 1 || p > pages;
    return `<button type="button" class="pg" data-page="${p}"
      ${dis ? "disabled" : ""} ${cur ? 'aria-current="page"' : ""}>${label}</button>`;
  };
  let start = Math.max(1, page - 2);
  let end = Math.min(pages, start + 4);
  start = Math.max(1, end - 4);
  const nums = [];
  if (start > 1) {
    nums.push(btn(1, "1"));
    if (start > 2) nums.push(`<span class="pg-ellipsis">…</span>`);
  }
  for (let p = start; p <= end; p++) nums.push(btn(p, String(p)));
  if (end < pages) {
    if (end < pages - 1) nums.push(`<span class="pg-ellipsis">…</span>`);
    nums.push(btn(pages, String(pages)));
  }
  el.innerHTML = `
    <div class="pg-info">${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()}</div>
    <div class="pg-btns">
      ${btn(page - 1, "Prev", { disabled: page <= 1 })}
      ${nums.join("")}
      ${btn(page + 1, "Next", { disabled: page >= pages })}
    </div>`;
  el.querySelectorAll("button.pg").forEach((b) => {
    b.onclick = () => {
      const p = Number(b.dataset.page);
      if (!p || p < 1 || p > pages || p === page) return;
      onChange((p - 1) * limit);
    };
  });
}

// --- Library overview + grid ---
let activeType = null;
let activeProject = null;

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

  const chips = [
    `<span class="chip ${!activeType && !activeProject ? "active" : ""}" data-t="" data-p="">All</span>`,
    `<span class="chip ${activeProject === "demo" ? "active" : ""}" data-t="" data-p="demo">Sample pack</span>`,
  ].concat(overview.map((r) =>
    `<span class="chip ${activeType === r.asset_type && !activeProject ? "active" : ""}" data-t="${r.asset_type}" data-p="">${r.asset_type}</span>`));
  const filter = document.getElementById("type-filter");
  filter.innerHTML = chips.join("");
  filter.querySelectorAll(".chip").forEach((c) =>
    c.onclick = () => {
      activeType = c.dataset.t || null;
      activeProject = c.dataset.p || null;
      assetOffset = 0;
      loadLibrary();
    });

  loadAssets();
}

let sortMode = "reusability";

async function loadAssets() {
  const params = new URLSearchParams({
    sort: sortMode, limit: String(PAGE_SIZE), offset: String(assetOffset),
  });
  if (activeType) params.set("asset_type", activeType);
  if (activeProject) params.set("project", activeProject);
  const resp = await api("/api/assets?" + params.toString());
  const assets = resp.assets || [];
  if (resp.reusable_band != null) reusableBand = resp.reusable_band;

  const grid = document.getElementById("asset-grid");
  const pager = document.getElementById("asset-pager");
  if (!assets.length && !resp.total) {
    grid.innerHTML = `<div class="empty">No assets${activeType ? " of this type" : ""} yet. Use <b>Ingest sample pack</b>.</div>`;
    pager.innerHTML = "";
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
  renderPager(pager, {
    total: resp.total || 0,
    limit: resp.limit || PAGE_SIZE,
    offset: resp.offset || 0,
    onChange: (off) => { assetOffset = off; loadAssets(); },
  });
}

document.getElementById("sort-toggle").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg");
  if (!btn || btn.dataset.sort === sortMode) return;
  sortMode = btn.dataset.sort;
  assetOffset = 0;
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

  let finished = false;
  const es = new EventSource(url);
  const stop = (label) => {
    if (finished) return;
    finished = true;
    es.close();
    status.textContent = label;
  };

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
      const skipped = s.skipped_existing
        ? ` · ${s.skipped_existing} already catalogued`
        : "";
      reasoningStep({
        agent: "Librarian", icon: "✅", status: "done", title: "Library updated",
        detail: `${s.inserted ?? 0} assets remembered from ${s.scanned ?? 0} files${skipped}.`,
      });
      if (log.lastChild) log.lastChild.classList.add("summary");
      stop("done.");
      toast(`Ingested ${s.inserted ?? 0} assets from ${s.scanned ?? 0} files.`);
      assetOffset = 0; dupOffset = 0; staleOffset = 0;
      loadLibrary(); loadStorage(); loadReview();
      return;
    }

    if (ev.type === "error") {
      reasoningStep({ agent: "System", icon: "⚠️", status: "error",
        title: "Ingest failed", detail: ev.message || "" });
      stop("failed.");
      toast(ev.message || "Ingest failed", 5000);
    }
  };
  es.onerror = () => {
    if (finished) { es.close(); return; }
    reasoningStep({
      agent: "System", icon: "⚠️", status: "error",
      title: "Connection closed",
      detail: "The ingest stream ended before finishing. Check the folder path — it must exist on the machine running the app, not only on this browser.",
    });
    stop("failed.");
  };
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
["ingest-root", "ingest-project"].forEach((id) => {
  document.getElementById(id).addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); ingestFromPath(); }
  });
});

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
        // Delegation: the root handing off to a specialist sub-agent.
        if (ev.name === "transfer_to_agent") {
          if (ev.status !== "working") return;  // show the handoff once
          let target = "";
          try { target = (JSON.parse(ev.args || "{}").agent_name) || ""; } catch { /* */ }
          chatAppend(
            `<div class="delegate">${agentBadge(ev.agent) || "📚 Librarian"}
               <span class="arrow">→ delegates to</span> ${agentBadge(target) || target}</div>`,
            "from-tool",
          );
          return;
        }
        const mcp = isMcpTool(ev.name);
        const body = ev.status === "working" ? (ev.args || "") : (ev.result || "");
        chatAppend(
          `<div class="tool ${mcp ? "mcp" : ""} ${ev.status}">
             <span class="tname">${agentBadge(ev.agent)}${mcp ? "MCP" : "tool"} · ${ev.name}</span>
             ${body ? `<pre>${body}</pre>` : ""}
           </div>`,
          "from-tool",
        );
        return;
      }
      if (ev.type === "text" && ev.text) {
        wait.remove();
        if (!replyEl || ev.final) {
          replyEl = chatAppend(
            `<div class="bubble agent md">${agentBadge(ev.agent)}<span class="md-body"></span></div>`,
            "from-agent",
          );
        }
        replyEl.querySelector(".md-body").innerHTML = renderMarkdown(ev.text);
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

// --- Assemble a cut (cinema-creative) ---
const BEAT_LABEL = {
  hook: "Hook", establish: "Establish", product: "Product",
  subject: "Subject", proof: "Proof", cta: "CTA",
};

function shotThumb(s) {
  const type = s.asset_type || "";
  if (s.asset_id && PREVIEW_TYPES.has(type)) {
    return `<img class="thumb" src="${API}/api/preview/${s.asset_id}" alt=""
      onerror="this.style.display='none'">`;
  }
  return `<div class="icon">${TYPE_ICON[type] || "📦"}</div>`;
}

function assembleStep(ev) {
  const log = document.getElementById("assemble-trace");
  const row = document.createElement("div");
  row.className = `rstep ${ev.status || "info"}`;
  row.innerHTML = `
    <span class="rdot"></span>
    <span class="ricon">${ev.icon || "•"}</span>
    <div class="rbody">
      <div class="rhead"><span class="ragent">${ev.agent || ""}</span>
        <span class="rtitle">${ev.title || ""}</span></div>
      ${ev.detail ? `<div class="rdetail">${escapeHtml(ev.detail)}</div>` : ""}
    </div>`;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function renderStoryboard(seq) {
  const board = document.getElementById("assemble-board");
  if (!seq || (!(seq.shots || []).length && !(seq.gaps || []).length)) {
    board.innerHTML = "";
    return;
  }
  const shots = (seq.shots || []).map((s, i) => `
    <div class="shot">
      <div class="beat">${BEAT_LABEL[(s.beat || "").toLowerCase()] || s.beat || `Shot ${i + 1}`}</div>
      ${shotThumb(s)}
      <div class="shot-body">
        <div class="shot-top"><span class="dur">${Math.round(s.duration_sec || 0)}s</span>
          ${s.match_score != null ? `<span class="score">${s.match_score}%</span>` : ""}</div>
        <div class="action">${escapeHtml(s.action || "")}</div>
        <div class="why">${escapeHtml(s.why || "")}</div>
        <div class="fname">${escapeHtml(s.filename || "")}</div>
      </div>
    </div>`).join(`<div class="cut">✂</div>`);
  const total = (seq.shots || []).reduce((t, s) => t + (Number(s.duration_sec) || 0), 0);
  const music = seq.music && seq.music.filename
    ? `<div class="music">🔊 <b>Music bed:</b> ${escapeHtml(seq.music.filename)} — ${escapeHtml(seq.music.why || "")}</div>`
    : "";
  const gaps = (seq.gaps || []).length
    ? `<div class="gaps"><div class="gaps-h">🎯 Still to shoot / source</div>
        ${seq.gaps.map((g) => `<div class="gap"><b>${escapeHtml(g.need)}</b> — ${escapeHtml(g.suggestion)}</div>`).join("")}
      </div>`
    : "";
  board.innerHTML = `
    <div class="seq-head">
      <div class="seq-title">${escapeHtml(seq.title || "Untitled cut")}</div>
      <div class="seq-log">${escapeHtml(seq.logline || "")}</div>
      <div class="seq-meta">${(seq.shots || []).length} shots · ~${Math.round(total)}s · from ${seq.candidates_considered || 0} candidates</div>
    </div>
    <div class="timeline">${shots || "<div class='empty'>No usable assets yet — see gaps below.</div>"}</div>
    ${music}${gaps}`;
}

async function runAssemble(brief) {
  const board = document.getElementById("assemble-board");
  const trace = document.getElementById("assemble-trace");
  const btn = document.querySelector("#assemble-form button");
  document.getElementById("assemble-brief").value = brief;
  trace.innerHTML = "";
  board.innerHTML = "";
  btn.disabled = true;
  try {
    const res = await fetch(API + "/api/assemble/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brief, limit: 16 }),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail || res.statusText);
    }
    await readSSE(res, (ev) => {
      if (ev.type === "step") assembleStep(ev);
      else if (ev.type === "done") renderStoryboard(ev.sequence);
      else if (ev.type === "error") {
        assembleStep({ status: "error", icon: "⚠️", agent: "Editor", title: "Error", detail: ev.message });
      }
    });
  } catch (err) {
    assembleStep({ status: "error", icon: "⚠️", agent: "Editor", title: "Failed", detail: err.message });
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("assemble-form").onsubmit = (e) => {
  e.preventDefault();
  const b = document.getElementById("assemble-brief").value.trim();
  if (b) runAssemble(b);
};

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
    const samplePath = (h.sample_assets && h.sample_assets.path) || "";
    const hosted = samplePath.replace(/\\/g, "/").includes("/app/sample_assets");
    const folderBtn = document.getElementById("ingest-folder-btn");
    const folderIn = document.getElementById("ingest-root");
    folderBtn.disabled = hosted;
    folderIn.disabled = hosted;
    if (hosted) {
      folderIn.placeholder = "Folder ingest is local-only";
      folderBtn.title = "Cloud Run can't see folders on your computer. Use Ingest sample pack, or run uvicorn locally.";
    }
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
function reviewThumb(id, has, type) {
  const icon = TYPE_ICON[type] || "📦";
  if (has && id) {
    return `<img src="${API}/api/preview/${id}" alt=""
      onerror="this.outerHTML='<div class=ph>${icon}</div>'">`;
  }
  return `<div class="ph">${icon}</div>`;
}

async function loadReview() {
  const qs = new URLSearchParams({
    dup_offset: String(dupOffset), dup_limit: String(REVIEW_PAGE),
    stale_offset: String(staleOffset), stale_limit: String(REVIEW_PAGE),
  });
  const data = await api("/api/review?" + qs.toString());
  const duplicates = data.duplicates || [];
  const stale = data.stale || [];

  const dupBox = document.getElementById("dup-list");
  if (duplicates.length) {
    dupBox.innerHTML = duplicates.map((d) => `
      <div class="dup clickable" data-asset-id="${d.id_a || ""}">
        <div class="thumbs">
          ${reviewThumb(d.id_a, d.has_preview_a, d.asset_type)}
          ${reviewThumb(d.id_b, d.has_preview_b, d.asset_type)}
        </div>
        <div class="pair">
          <div>${TYPE_ICON[d.asset_type] || ""} <b>${escapeHtml(d.file_a || "")}</b> ↔ ${escapeHtml(d.file_b || "")}</div>
          <div class="dist">${d.kind === "exact" ? "exact hash" : "near"} · distance ${Number(d.distance).toFixed(3)}
            ${d.wasted_bytes ? " · " + fmtBytes(d.wasted_bytes) + " reclaimable" : ""}</div>
        </div>
        <div class="actions">
          <button class="small ghost" data-open-id="${d.id_b || ""}">Preview copy</button>
          <button class="small danger" onclick="approve('${d.id_b}','archive')">Archive duplicate</button>
        </div>
      </div>`).join("");
  } else {
    dupBox.innerHTML = `<div class="empty">No duplicates found.</div>`;
  }
  renderPager(document.getElementById("dup-pager"), {
    total: data.dup_total || 0,
    limit: data.dup_limit || REVIEW_PAGE,
    offset: data.dup_offset || 0,
    onChange: (off) => { dupOffset = off; loadReview(); },
  });

  const staleBox = document.getElementById("stale-list");
  if (stale.length) {
    staleBox.innerHTML = stale.map((a) => `
      <div class="dup clickable" data-asset-id="${a.id || ""}">
        <div class="thumbs">${reviewThumb(a.id, a.has_preview, a.asset_type)}</div>
        <div class="pair">
          <div>${TYPE_ICON[a.asset_type] || ""} <b>${escapeHtml(a.filename || "")}</b></div>
          <div class="dist">${escapeHtml(a.caption || "")}</div>
        </div>
        <div class="actions">
          <button class="small ghost" onclick="approve('${a.id}','keep')">Keep</button>
          <button class="small danger" onclick="approve('${a.id}','archive')">Archive</button>
        </div>
      </div>`).join("");
  } else {
    staleBox.innerHTML = `<div class="empty">Nothing flagged as stale.</div>`;
  }
  renderPager(document.getElementById("stale-pager"), {
    total: data.stale_total || 0,
    limit: data.stale_limit || REVIEW_PAGE,
    offset: data.stale_offset || 0,
    onChange: (off) => { staleOffset = off; loadReview(); },
  });
}

window.approve = async (assetId, action) => {
  try {
    await api("/api/approve", { method: "POST", body: JSON.stringify({ asset_id: assetId, action }) });
    toast(action === "archive" ? "Archived." : "Kept.");
    loadLibrary(); loadStorage(); loadReview();
  } catch (err) { toast(`Action failed: ${err.message}`, 4000); }
};

document.getElementById("refresh-review").onclick = () => {
  dupOffset = 0; staleOffset = 0; loadReview();
};

// --- Lightbox ---
function closeLightbox() {
  const box = document.getElementById("lightbox");
  box.hidden = true;
  document.getElementById("lb-media").innerHTML = "";
  const vid = box.querySelector("video, audio");
  if (vid) { vid.pause(); }
}

async function openAsset(id) {
  if (!id) return;
  const box = document.getElementById("lightbox");
  const media = document.getElementById("lb-media");
  const meta = document.getElementById("lb-meta");
  box.hidden = false;
  media.innerHTML = `<div class="lb-empty">Loading…</div>`;
  meta.innerHTML = "";
  try {
    const { asset: a } = await api(`/api/assets/${id}`);
    const icon = TYPE_ICON[a.asset_type] || "📦";
    const kind = a.preview_kind || "none";
    if (kind === "image") {
      media.innerHTML = `<img src="${API}/api/preview/${a.id}?kind=media" alt="">`;
    } else if (kind === "video") {
      media.innerHTML = `<video controls playsinline poster="${API}/api/preview/${a.id}"
        src="${API}/api/preview/${a.id}?kind=media"></video>`;
    } else if (kind === "audio") {
      media.innerHTML = `<audio controls src="${API}/api/preview/${a.id}?kind=media"></audio>`;
    } else {
      media.innerHTML = `<div class="lb-empty"><span class="icon">${icon}</span>
        Catalog-only row — the file is not on this machine.</div>`;
    }
    const created = a.created_at ? String(a.created_at).replace("T", " ").slice(0, 19) : "—";
    meta.innerHTML = `
      <div class="name" id="lb-title">${escapeHtml(a.filename || "")}</div>
      <div class="cap">${a.caption ? escapeHtml(a.caption) : "<em>uncaptioned</em>"}</div>
      <div class="tags">${(a.tags || []).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("")}</div>
      <div class="lb-kv">
        <div><div class="k">Type</div><div class="v">${escapeHtml(a.asset_type || "")}${a.asset_subtype ? " · " + escapeHtml(a.asset_subtype) : ""}</div></div>
        <div><div class="k">Size</div><div class="v">${fmtBytes(a.size_bytes)}</div></div>
        <div><div class="k">Project</div><div class="v">${escapeHtml(a.project || "—")}</div></div>
        <div><div class="k">Reuse</div><div class="v">${a.reusable ? "reusable" : "project-specific"}${a.reusability_score != null ? " · " + a.reusability_score + "/100" : ""}</div></div>
        <div><div class="k">Status</div><div class="v">${escapeHtml(a.status || "")}</div></div>
        <div><div class="k">Created</div><div class="v">${escapeHtml(created)}</div></div>
      </div>`;
  } catch (err) {
    media.innerHTML = `<div class="lb-empty">Could not open asset: ${escapeHtml(err.message)}</div>`;
  }
}

document.getElementById("lb-close").onclick = closeLightbox;
document.querySelector("#lightbox .lb-backdrop").onclick = closeLightbox;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.getElementById("lightbox").hidden) closeLightbox();
});

document.addEventListener("click", (e) => {
  const openBtn = e.target.closest("[data-open-id]");
  if (openBtn) {
    e.preventDefault();
    e.stopPropagation();
    openAsset(openBtn.dataset.openId);
    return;
  }
  if (e.target.closest("button, a, .pager, .chips, .sort-toggle")) return;
  const hit = e.target.closest("[data-asset-id]");
  if (hit && hit.dataset.assetId) openAsset(hit.dataset.assetId);
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const hit = e.target.closest(".asset[data-asset-id]");
  if (!hit) return;
  e.preventDefault();
  openAsset(hit.dataset.assetId);
});

// --- Boot ---
(async function boot() {
  try {
    await loadHealth();
    await loadLibrary();
    await loadStorage();
    await loadReview();
  } catch (err) { toast(`Backend not reachable: ${err.message}`, 6000); }
})();
