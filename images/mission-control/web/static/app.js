// The app, part of app-base.js, app-tasks.js, app-runs.js, app-devices.js, app-wiki-code.js, app-memory.js, app.js (PLT-25): the Stack tab, tools, live data, offline and updates, and the start. Loaded in that order; one global scope.
// ---------- stack (system) ----------
// ---------- tools: every tool the stack runs on, its menus one tap away (APP-30; web/static/tools.json is the one list) ----------
let TOOLS = null, toolQuery = "";
const toolsHere = (d) => ({ ...d, tools: (d.tools || []).filter((x) => !("host" in x) || (x.host && !/^https?:\/\/(:|\/|$)/.test(x.host))) });   // no address in this deployment: no tile
const toolsLoad = () => (TOOLS ? Promise.resolve(TOOLS) : fetch("/static/tools.json").then((r) => r.text()).then((t) => (TOOLS = toolsHere(JSON.parse(t.replace(/\{\{(\w+)\}\}/g, (_, k) => DEPLOY[k] || ""))))).catch(() => ({ tools: [], pages: [] })));
const toolBase = (t) => (t.host.startsWith("tailnet") ? HOSTURL + t.host.slice(7) : t.host);
const toolUrl = (t, m) => toolBase(t) + m.path;
const toolAtHome = (t) => !t.host.startsWith("tailnet") && !t.host.includes("tailscale.com");   // the home network only
const toolOf = (id) => (TOOLS?.tools || []).find((t) => t.id === id);
function toolState(t) {
  if (t.status === "house" && S.house) return S.house.reachable ? ["ok", "up"] : ["err", "not reachable"];
  return null;
}
const toolLinks = (t) => t.menus.map((m) => `<a class="tag" href="${esc(toolUrl(t, m))}" target="_blank" rel="noopener">${esc(m.name)}</a>`).join("");

function stackToolsHtml() {
  if (!TOOLS) return `<div class="skeleton" style="height:120px"></div>`;
  return `<div class="wsearch gsearch">${ic.search}<input class="input" id="toolq" placeholder="Go to… people, wifi, tokens, voice, logs" value="${esc(toolQuery)}" autocomplete="off"></div>
    <div id="toolres"></div>
    <div class="grid g2 tools">${TOOLS.tools.map((t) => { const st = toolState(t);
      return `<div class="card pad tool"><div class="row between wrap" style="gap:4px 8px;align-items:baseline"><b>${esc(t.name)}</b><span class="tiny faint">${st ? `<span class="dot ${st[0]}" style="display:inline-block;margin-right:5px"></span>${esc(st[1])} · ` : ""}${toolAtHome(t) ? "home Wi-Fi" : "anywhere"}</span></div>
        <div class="small muted">${esc(t.what)}</div><div class="chips" style="margin-top:8px">${toolLinks(t)}</div></div>`; }).join("")}</div>
    ${explain("anywhere-opens-with-your", `${ic.check} “Anywhere” opens with your Tailscale login, no password. “Home Wi-Fi” tools (the NAS, the router, Home Assistant) open at home and keep their own logins.`, "Where they open")}`;
}

function toolHits(q) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length || !TOOLS) return [];
  const hit = (s) => words.every((w) => s.toLowerCase().includes(w));
  const pages = TOOLS.pages.filter(([n, , w]) => hit(`${n} ${w}`)).map(([n, href]) => ({ name: `Mission Control → ${n}`, href, ext: false }));
  const menus = TOOLS.tools.flatMap((t) => t.menus.filter((m) => hit(`${t.name} ${m.name} ${m.words || ""} ${t.what}`)).map((m) => ({ name: `${t.name} → ${m.name}`, href: toolUrl(t, m), ext: true })));
  return [...pages, ...menus];
}

function bindStackTools() {
  const q = $("#toolq"), out = $("#toolres");
  if (!q) return;
  const draw = () => {
    toolQuery = q.value;
    const hits = toolHits(q.value);
    out.innerHTML = !q.value.trim() ? "" : hits.length
      ? `<div class="card list" style="margin-bottom:10px">${hits.map((h) => `<a href="${esc(h.href)}"${h.ext ? ' target="_blank" rel="noopener"' : ""}><div class="grow"><div class="ttl">${esc(h.name)}</div></div>${ic.next}</a>`).join("")}</div>`
      : `<div class="small muted" style="margin-bottom:10px">Nothing matches “${esc(q.value)}”: try a tool's name, or words like people, wifi, logs.</div>`;
  };
  q.oninput = draw;
  q.onkeydown = (e) => {                              // Enter opens the first match
    const h = e.key === "Enter" && toolHits(q.value)[0];
    if (h) h.ext ? window.open(h.href, "_blank", "noopener") : (location.hash = h.href);
  };
  draw();
}
const HOSTURL = location.hostname.endsWith(".ts.net") ? `https://${location.hostname}` : `https://${DEPLOY.PC_TAILNET_HOST}`;

function stackChecks(sy) {
  const ci = sy.ci || [];
  const ciCls = (s) => (s === "success" ? "ok" : s === "failure" ? "err" : s === "running" || s === "waiting" ? "run" : "");
  return `<div class="card pad-l section"><div class="row between"><h2>Checks (CI)</h2>${how("stack-page")}</div><div class="list" style="margin-top:6px">${ci.map((c) => `<div style="padding:8px 2px"><span class="dot ${ciCls(c.status)}"></span><div class="grow">${esc(c.repo)}</div><span class="tiny faint">${esc(c.status)} ${esc(c.sha)}</span></div>`).join("")}</div></div>`;
}
function bar(used, total, warnAt = 0.8) {
  const r = total ? Math.min(1, used / total) : 0;
  return `<div class="meter" style="margin-top:6px"><i style="width:${(r * 100).toFixed(1)}%;${r >= warnAt ? "background:var(--warn)" : ""}${r >= 0.93 ? ";background:var(--err)" : ""}"></i></div>`;
}
function resourcesHtml(R) {
  if (!R || !R.wsl) return `<div class="card empty small">Measuring…</div>`;
  const h = R.host, w = R.wsl;
  const tiles = [];
  if (h) tiles.push(`<div class="card kpi"><div class="kpi-l">Windows RAM</div><div class="kpi-v" style="font-size:22px">${nf(h.ram_total_gb - h.ram_free_gb, 1)} <span class="muted" style="font-size:14px">/ ${nf(h.ram_total_gb, 0)} GB</span></div><div class="kpi-s">${nf(h.ram_free_gb, 1)} GB free · AI stack VM ${nf(h.wsl_vm_gb, 1)} GB</div>${bar(h.ram_total_gb - h.ram_free_gb, h.ram_total_gb)}</div>`);
  tiles.push(`<div class="card kpi"><div class="kpi-l">AI stack RAM (WSL)</div><div class="kpi-v" style="font-size:22px">${nf(w.mem_used_gb, 1)} <span class="muted" style="font-size:14px">/ ${nf(w.mem_total_gb, 1)} GB</span></div><div class="kpi-s">limit set in .wslconfig</div>${bar(w.mem_used_gb, w.mem_total_gb)}</div>`);
  tiles.push(`<div class="card kpi"><div class="kpi-l">CPU</div><div class="kpi-v" style="font-size:22px">${w.cpu_pct} %</div><div class="kpi-s">AI stack · ${w.cores} threads${h ? ` · Windows total ${h.cpu_pct} %` : ""}</div>${bar(w.cpu_pct, 100)}</div>`);
  tiles.push(`<div class="card kpi"><div class="kpi-l">Disk</div><div class="kpi-v" style="font-size:22px">${h ? nf(h.disk_c_free_gb, 0) : nf(w.disk_free_gb, 0)} GB <span class="muted" style="font-size:14px">free</span></div><div class="kpi-s">${h ? `C: ${nf(h.disk_c_total_gb, 0)} GB · ` : ""}WSL ${nf(w.disk_free_gb, 0)} of ${nf(w.disk_total_gb, 0)} GB free</div>${h ? bar(h.disk_c_total_gb - h.disk_c_free_gb, h.disk_c_total_gb, 0.85) : ""}</div>`);
  const svc = (R.services || []).map((x) => `<div class="svcrow"><span class="n">${esc(x.name)}</span><span class="tiny faint num">${nf(x.cpu, 1)} %</span><div class="grow">${bar(x.mem_mb, x.limit_mb)}</div><span class="tiny num" style="min-width:96px;text-align:right">${nf(x.mem_mb)} / ${nf(x.limit_mb)} MB</span></div>`).join("");
  return `<div class="grid g2 g4">${tiles.join("")}</div><div class="card pad" style="margin-top:12px"><div class="tiny faint" style="margin-bottom:6px">Per service: CPU · RAM against its limit</div>${svc}</div>`;
}

function bindAddVault() {
  const box = $("#addk");
  if ($("#vaddb")) $("#vaddb").onclick = () => { box.hidden = !box.hidden; if (!box.hidden) $("#k_title").focus(); };
  let kind = "text";
  $$("#addk [data-k]").forEach((b) => (b.onclick = () => {
    kind = b.dataset.k; $$("#addk [data-k]").forEach((x) => x.classList.toggle("on", x === b));
    $("#k_text").hidden = kind !== "text"; $("#k_url").hidden = kind !== "url"; $("#k_file").hidden = kind !== "file";
  }));
  $("#k_go").onclick = async () => {
    const btn = $("#k_go"), title = $("#k_title").value.trim();
    btn.disabled = true;
    try {
      if (kind === "file") {
        const f = $("#k_file").files[0];
        if (!f) return toast("Choose a file", true);
        const r = await fetch("/api/upload", { method: "POST", body: f, headers: { "X-Filename": f.name, "X-Title": title } }).then((x) => x.json());
        r.ok === false ? toast(r.error || "Upload failed", true) : toast("Added to the vault inbox");
      } else {
        const r = await act({ action: "vault_add", title, text: kind === "text" ? $("#k_text").value : "", url: kind === "url" ? $("#k_url").value.trim() : "" }, (x) => `Added as ${x.path || "a note"}: search and chat find it from now on`);
        if (r) { $("#k_text").value = ""; $("#k_url").value = ""; $("#k_title").value = ""; }
      }
    } finally { btn.disabled = false; }
  };
}

// The Stack tab is one page: how the stack works (live map, guide chapters, search) and how it is doing (status),
// each status section linked to the chapter that explains it. Chapters open as #/guide/<id> (guide.js).
// MEM-01, MEM-07: every memory the stack keeps (ops/memory.py, refreshed hourly): kind, size, growth, limit, who tidies it, problems
function memUse(m) {                                          // how full it is against its limit: [value, limit, label]
  const [n, unit] = m.limit || [];
  const v = unit === "MB" ? m.bytes / 1e6 : unit === "orphaned share" ? m.orphaned_share || 0 : /per wiki|per journal|lines each/.test(unit || "") ? m.largest || 0 : m.count;
  return n ? [v, n, unit === "orphaned share" ? `${Math.round(100 * v)} % orphaned of ${Math.round(100 * n)} %` : `${nf(Math.round(v))} of ${nf(n)} ${unit}`] : null;
}
// Stack → Health: each memory store's figures; reading them is the Memory tab's (APP-50)
function memoryHtml() {
  const st = S.memory?.stores || [];
  if (!st.length) return `<div class="section-h section"><h2>Memory</h2></div><div class="card pad small muted">The figures come within the hour.</div>`;
  const row = (m) => {
    const u = m.error ? null : memUse(m), g = m.growth_7d, pct = u ? Math.min(100, (100 * u[0]) / u[1]) : 0;
    const count = m.error ? "" : `${nf(m.count)} ${esc(m.count_label ? `${m.unit} in ${m.count_label}` : m.unit)}`;
    const moved = g?.count ? ` · ${g.count > 0 ? "+" : ""}${nf(g.count)} in 7 days` : "";
    return `<div class="memrow"><div class="row between wrap" style="gap:6px"><b class="small">${esc(m.name)}</b><span class="small num">${count}${moved}${m.used?.n ? ` · ${esc(m.used.verb)} ${nf(m.used.n)} times in ${m.used.days} days` : ""}</span></div>
      ${u && pct >= 70 ? `<div class="meter" title="${esc(u[2])}"><i style="width:${pct}%;${pct > 90 ? "background:var(--err)" : "background:var(--warn)"}"></i></div><div class="tiny faint">${esc(u[2])}</div>` : ""}
      ${m.over_since ? `<div class="tiny warn-t wrap">Over its limit since ${day(m.over_since)}; after 8 days its curator gets an alert</div>` : ""}
      ${(m.problems || []).map((p) => `<div class="tiny err-t wrap">${ic.alert} ${esc(p)}</div>`).join("")}</div>`;
  };
  const ms = S.memory?.stack || {};
  const stack = `<div class="section-h memgroup"><h3>Memory given to runs</h3><span class="tiny faint">budgets in config/memory.yaml</span></div>${memStatusHtml(ms)}
    ${ms.gate ? `<div class="tiny ${ms.gate.open ? "faint" : "warn-t"} wrap" style="margin-bottom:8px">${ms.gate.open ? ic.check : ic.alert} ${esc(ms.gate.why)}</div>` : ""}${ms.error ? `<div class="tiny err-t wrap">${ic.alert} ${esc(ms.error)}</div>` : ""}`;
  return `<div class="section-h section"><h2>Memory</h2><a class="tiny" href="#/memory">Open Memory</a></div>${stack}<div class="card memlist">${st.map(row).join("")}</div>`;
}

// MEM-08: the Librarian's last pass over the wikis and the search index (public/librarian.json, via memory.json)
const LIB_KIND = { "broken-link": ["broken link", "broken links"], orphan: ["page no other page links to", "pages no other page links to"], duplicate: ["possible duplicate", "possible duplicates"],
  contradiction: ["page with a marked contradiction", "pages with a marked contradiction"], stale: ["page not confirmed for 90 days", "pages not confirmed for 90 days"], "over-limit": ["over the page limit", "over the page limit"] };
function librarianHtml(lib) {
  if (!lib) return `<div class="card pad small muted" style="margin-top:10px"><b>The Librarian</b> tidies every wiki and the search index once a week (Wednesdays). Its first pass has not run yet.</div>`;
  const ws = lib.wikis || [], ix = lib.index || {}, h = lib.hubs || {};
  const n = (k) => ws.reduce((a, w) => a + (w[k] || []).length, 0);
  const wrow = (w) => {
    const kinds = {};
    (w.issues || []).forEach((i) => (kinds[i.kind] = (kinds[i.kind] || 0) + 1));
    const did = [["merged", "merged"], ["contradictions", "contradictions marked"], ["stale", "marked stale"]].filter(([k]) => (w[k] || []).length).map(([k, t]) => `${w[k].length} ${t}`);
    return `<div class="memrow"><div class="row between wrap" style="gap:6px"><b>${esc(w.title)}</b><span class="tiny faint">${nf(w.pages || 0)} pages</span></div>
      ${did.length ? `<div class="small">${esc(did.join(" · "))}</div>` : ""}
      <div class="tiny faint wrap">${Object.keys(kinds).length ? Object.entries(kinds).map(([k, c]) => `${c} ${esc((LIB_KIND[k] || [k, k])[c === 1 ? 0 : 1])}`).join(" · ") : "nothing to report"}${w.waits ? ` · ${nf(w.waits)} wait for the next pass` : ""}</div>
      ${(w.merged || []).map((x) => `<div class="tiny wrap">${ic.check} ${esc(x.drop)} merged into ${esc(x.keep)}: ${esc(x.why)}</div>`).join("")}
      ${(w.refused || []).map((x) => `<div class="tiny warn-t wrap">Kept apart ${esc(x.drop)} and ${esc(x.keep)}: ${esc(x.why)}</div>`).join("")}
      ${w.error || w.not_judged ? `<div class="tiny err-t wrap">${ic.alert} ${esc(w.error || `not judged: ${w.not_judged}`)}</div>` : ""}</div>`;
  };
  return `<div class="section-h section"><h2>The Memory Keeper's wiki tidy</h2><span class="tiny faint">last pass ${rel(new Date(lib.at * 1000).toISOString())} · ${nf(lib.seconds || 0)} s${lib.commit ? ` · vault commit ${esc(lib.commit)}` : " · nothing changed"}</span></div>
    ${explain("weekly-merges-duplicate-", `Weekly: merges duplicate pages, marks contradictions and stale pages, writes the hub pages that join the wikis, cleans the search index. It adds no facts, and everything it changes can be restored from the vault's history.
      ${n("merged")} merged · ${n("contradictions")} contradictions marked · ${n("stale")} marked stale · ${nf(h.hubs || 0)} hub pages${ix.before ? ` · search index: ${nf(ix.before.orphaned)} → ${nf(ix.after.orphaned)} orphaned chunks` : ix.error ? ` · <span class="err-t">search index cleanup failed: ${esc(ix.error)}</span>` : ""}`, "About this")}
    <div class="card memlist">${ws.map(wrow).join("")}</div>`;
}

// OBS-16: the one notification path: what goes where, quiet hours, and what it did lately (Stack → Notifications)
const NDOT = { sent: "ok", held: "warn", failed: "err" };
function notifyHtml(sy) {
  const n = S.notify || { prefs: { telegram: {}, push: {}, quiet: null }, categories: {}, recent: [] }, q = n.prefs.quiet;
  const box = (ch, c) => `<input type="checkbox" data-np="${ch}" data-cat="${esc(c)}" aria-label="${esc(ch)}: ${esc(c)}"${n.prefs[ch]?.[c] !== false ? " checked" : ""}${c === "approval" ? ` disabled title="Approvals always go out: they expire when nobody sees them"` : ""}>`;
  const name = (r) => r.title || (n.categories[r.category] || r.category).split(":")[0];
  return `<div class="card pad small">
    <div class="row"><span class="dot ok"></span>Telegram with buttons, and push to this app</div>
    <div class="row" style="margin-top:8px"><span class="dot ${sy.email_ready ? "ok" : "warn"}"></span>${sy.email_ready ? "E-mail ready" : "E-mail not set up: on the PC, run <code>make email-setup</code> once"}</div>
    <table class="ntable"><thead><tr><th>What</th><th>Telegram</th><th>Push</th></tr></thead><tbody>
      ${Object.entries(n.categories).map(([c, d]) => { const [what, ...more] = d.split(": "); return `<tr><td><b>${esc(what)}</b>${more.length ? `<div class="tiny faint">${esc(more.join(": "))}</div>` : ""}</td><td>${box("telegram", c)}</td><td>${box("push", c)}</td></tr>`; }).join("")}</tbody></table>
    <div class="nquiet"><label><input type="checkbox" id="nquiet"${q ? " checked" : ""}> Quiet hours from</label>
      <input class="input" type="time" id="nfrom" value="${esc(q?.from || "22:00")}"> <span>to</span> <input class="input" type="time" id="nto" value="${esc(q?.to || "07:00")}"></div>
    ${n.quiet_now ? `<div class="tiny faint" style="margin-top:6px"><b>Quiet hours now${n.held ? `: ${n.held} waiting` : ""}.</b></div>` : ""}${explain("quiet-hours-", "In quiet hours only approvals reach you; the Telegram messages wait and come as one message when they end.", "What quiet hours do")}
    <div class="row" style="justify-content:flex-end;margin-top:10px"><button class="btn sm primary" id="nsave">${ic.check}Save</button></div>
  </div>
  <details class="card pad small nrecent" data-keep="nrecent" style="margin-top:10px"><summary>What the stack sent lately · ${n.recent.length}</summary>
    <div class="list">${n.recent.map((r) => `<div><span class="dot ${NDOT[r.decision] || ""}"></span><div class="grow"><div class="ttl">${esc(name(r))}</div><div class="sub">${prose(r.text || "")}</div></div>
      <div class="tiny faint" style="white-space:nowrap;text-align:right">${esc(r.channel)} · ${esc(r.decision)}<br>${rel(new Date(r.ts * 1000).toISOString())}</div></div>`).join("") || `<div class="muted small">Nothing sent yet</div>`}</div></details>`;
}

function bindNotify() {
  const save = $("#nsave");
  if (!save) return;
  save.onclick = async () => {
    const prefs = { telegram: {}, push: {}, quiet: $("#nquiet").checked ? { from: $("#nfrom").value, to: $("#nto").value } : null };
    $$("[data-np]").forEach((b) => (prefs[b.dataset.np][b.dataset.cat] = b.checked));
    save.disabled = true;
    await act({ action: "notify_prefs", prefs }, "Notification settings saved");
    save.disabled = false;
  };
}

// the subscriptions' load: tokens in the last 5 hours (ChatGPT's usage window) and 24 hours, and whether one is at its
// limit now (a build or mission waiting on it, as the runner sees it) and until when
const SUB_WAIT = { ChatGPT: "ChatGPT", Claude: "Claude" };
function subLimit(eng) {
  const until = [...(S?.builds || []).filter((b) => b.status === "waiting" && (b.error || "").includes(SUB_WAIT[eng]) && b.retry_at).map((b) => b.retry_at),
    ...(eng === "ChatGPT" ? (S?.queue || []).filter((q) => q.status === "waiting").map((q) => q.retry_at || "") : [])].filter((x) => x === "" || Date.parse(x) > Date.now());
  return until.length ? until.sort().at(-1) || "soon" : null;
}
async function subsInto(box) {
  const u = await api("/api/usage").catch(() => null);
  if (!box.isConnected || !u) return;
  const rows = ["ChatGPT", "Claude"].map((eng) => ({ engine: eng, tokens_5h: 0, calls_5h: 0, tokens_24h: 0, calls_24h: 0, top: [], ...(u.find((x) => x.engine === eng) || {}) }));
  box.innerHTML = `<div class="card pad"><div class="row between wrap" style="gap:8px"><h2>Subscriptions</h2><span class="tiny faint">what they carried · ChatGPT counts its limit in 5-hour windows</span></div>
    <div class="list" style="margin-top:6px">${rows.map((r) => { const lim = subLimit(r.engine);
      return `<div><div class="ic ${lim ? "warn" : "ok"}">${lim ? ic.clock : ic.check}</div><div class="grow" style="min-width:0"><div class="ttl">${r.engine} <span class="pill ${lim ? "paused" : "ok"}" style="padding:1px 8px">${lim ? `at its limit${lim === "soon" ? "" : ` until ${clock(lim)}`}` : "available"}</span></div>
        <div class="sub wrap">${tok(r.tokens_5h)} tokens in the last 5 h (${nf(r.calls_5h)} calls) · ${tok(r.tokens_24h)} in 24 h${r.top.length ? ` · most: ${r.top.map(([a, n]) => `${esc(a === "claude" ? "Claude Code" : agentName(a) || a)} ${tok(n)}`).join(", ")}` : ""}</div></div></div>`; }).join("")}</div></div>`;
}

// APP-47: five parts, one at a time: the page was 21 sections and 13,000 pixels long
const STACK_TABS = [["tools", "Tools"], ["health", "Health"], ["guide", "Guide"], ["settings", "Settings"]];
let stackTab = "";
function vSystem() {
  const sy = S.system || {};
  const asked = route.q.get("conn") ? "tools" : scrollToLearn ? "guide" : route.q.get("tab");
  if (STACK_TABS.some(([k]) => k === asked)) stackTab = asked;
  const tab = stackTab || (stackTab = pref("mc-stack-tab", "tools"));
  const svc = sy.services || [];
  const down = svc.filter((s) => s.state !== "running");
  view.innerHTML = `
  <div class="hero stackhero"><div class="grow"><h1>Stack</h1><p>
    ${notConnected() || !svc.length ? `<b class="err-t">not connected: its state is not known</b>` : down.length ? `<b class="err-t">${down.length} service${down.length > 1 ? "s" : ""} not running</b>` : "all services running"}${notConnected() || !svc.length ? "" : " · "}${notConnected() || !svc.length ? "" : sy.failed?.length ? `<b class="err-t">failed: ${sy.failed.map((u) => {                // which one, one tap to it (UX review 2026-10-30)
      const c = (S.crew || []).find((x) => `${x.unit}.service` === u);
      return c ? `<a class="err-t" href="#/crew/${encodeURIComponent(c.id)}">${esc(c.name)}</a>` : esc(u.replace(/\.service$/, ""));
    }).join(", ")}</b>` : "no errors"}${sy.boot ? ` · last start ${rel(new Date(sy.boot.boot * 1000).toISOString())}, online in ${dur(sy.boot.ready_s)}` : ""}</p></div>
    <a class="btn sm" href="#/files" title="What your missions made, the space it takes, the trash">${ic.doc}Files · ${fsize(S.files?.usage?.used || 0)}${(S.files?.usage?.pct || 0) >= 80 ? ` <b class="err-t">${S.files.usage.pct} %</b>` : ""}</a></div>
  <nav class="seg stackseg" aria-label="Parts of this page">${STACK_TABS.map(([k, l]) => `<button type="button" data-st="${k}" class="${tab === k ? "on" : ""}">${l}</button>`).join("")}</nav>
  <div data-sp="tools" ${tab === "tools" ? "" : "hidden"}>
  ${phoneBanner()}
  <div class="section-h"><h2>Tools</h2></div>
  <div id="toolsbox" style="margin-bottom:14px">${stackToolsHtml()}</div>
  ${S.house ? `<a class="banner info" href="#/house" style="margin-bottom:14px">${ic.house}<span class="grow"><b>House</b> · ${S.house.connected ? `${(S.house.things || []).length} things, ${(S.house.echos || []).length} Echos` : S.house.reachable ? "setup not finished" : "Home Assistant not reachable"}</span>${ic.next}</a>` : ""}
  ${a2aCardHtml()}
  <div id="subs" style="margin-bottom:14px"></div>
  <div class="section-h"><h2>Connections</h2></div>
  <div id="conncard" class="stack" style="margin-bottom:14px"><div class="skeleton" style="height:90px"></div></div>
  </div>
  <div data-sp="health" ${tab === "health" ? "" : "hidden"}>
  <div class="section-h"><h2>Health and costs</h2>${how("safety")}</div>
  <div class="grid g2 g4">
    <div class="card kpi"><div class="kpi-l">Paid today</div><div class="kpi-v">${usd(sy.spend_today)}</div><div class="kpi-s">30 days: ${usd(sy.spend_30d)}</div></div>
    <div class="card kpi"><div class="kpi-l">Credit used</div><div class="kpi-v">${usd(sy.spend_total)}</div><div class="kpi-s">of $${nf(sy.budget_total || 10)}</div><div class="meter"><i style="width:${Math.min(100, ((sy.spend_total || 0) / (sy.budget_total || 10)) * 100).toFixed(1)}%"></i></div></div>
    <div class="card kpi"><div class="kpi-l">Long-term memory</div><div class="kpi-v">${nf(sy.memory?.facts)}</div><div class="kpi-s">facts · ${nf(sy.memory?.observations)} observations</div></div>
    <div class="card kpi"><div class="kpi-l">Last backup</div><div class="kpi-v" style="font-size:20px">${sy.backup ? rel(new Date(sy.backup.ts * 1000).toISOString()) : "–"}</div><div class="kpi-s">${sy.drill ? "restore test: " + esc(sy.drill.result) : ""}</div></div>
  </div>
  <div class="section-h section"><h2>Resources</h2>${how("stack-page")}</div>
  <div id="rescard">${resourcesHtml(S.resources)}</div>
  <div class="split section">
    <div>
      <div class="section-h"><h2>Agents today</h2>${how("technology")}</div>
      <div class="card list">${(sy.agents_today || []).map((a) => { const max = Math.max(...sy.agents_today.map((x) => x.tokens)) || 1; return `<div style="align-items:center"><span class="agent ${esc(a.agent)}">${esc(a.agent)}</span><div class="grow"><div class="meter" style="margin:0"><i style="width:${((a.tokens / max) * 100).toFixed(1)}%"></i></div></div><div class="small num" style="min-width:110px;text-align:right">${nf(a.calls)} · ${tok(a.tokens)}</div></div>`; }).join("") || `<div class="muted small">No calls today</div>`}</div>
      <div class="section-h section"><h2>Services</h2>${how("stack-page")}</div>
      <div class="card grid g2" style="gap:0">${svc.map((s) => `<div class="svc"><span class="dot ${s.state === "running" ? (/unhealthy/.test(s.status) ? "warn" : "ok") : "err"}"></span><span class="n">${esc(s.name)}</span><span class="tiny faint">${esc(s.status.replace(/^Up /, "").replace(/ \(healthy\)/, ""))}</span></div>`).join("")}</div>
    </div>
    <div>
      <div class="section-h"><h2>Scheduled jobs</h2>${how("stack-page")}</div>
      <div class="card list">${(sy.timers || []).map((t) => { const failed = (sy.failed || []).some((f) => f.startsWith(t.unit + ".")); return `<div><div class="ic ${failed ? "err" : ""}">${failed ? ic.alert : ic.clock}</div><div class="grow"><div class="ttl">${esc((S.crew || []).find((c) => c.unit === t.unit)?.name || t.unit)}</div><div class="sub">last ${t.last ? rel(new Date(t.last / 1000).toISOString()) : "–"}</div></div><div class="tiny faint" style="white-space:nowrap">${t.next ? rel(new Date(t.next / 1000).toISOString()) : "–"}</div></div>`; }).join("")}</div>
    </div>
  </div>
  ${stackChecks(sy)}
  ${(sy.pending_memory || []).length ? `<div class="section-h section"><h2>Waiting for you</h2>${how("knowledge")}</div>
    <div class="card list">${sy.pending_memory.map((p) => `<div style="flex-direction:column;gap:8px"><div class="row"><div class="ic warn">${ic.brain}</div><div class="grow small">${esc(p.text)}</div></div>
      <div class="row" style="justify-content:flex-end"><button class="btn sm ghost danger" data-mem="reject" data-id="${esc(p.id)}">${ic.x}Discard</button><button class="btn sm primary" data-mem="approve" data-id="${esc(p.id)}">${ic.check}Remember</button></div></div>`).join("")}</div>` : ""}
  ${memoryHtml()}
  ${S.memory?.stores?.length ? librarianHtml(S.memory.librarian) : ""}
  <a class="banner info" href="#/telemetry" style="margin-bottom:14px">${ic.pulse}<span class="grow"><b>Telemetry</b> · how each agent did, day by day: runs, verdicts, tokens, time, cost if paid</span>${ic.next}</a>
  </div>
  <div data-sp="guide" ${tab === "guide" ? "" : "hidden"}>
  <div class="wsearch gsearch">${ic.search}<input class="input" id="gq" placeholder="How do I…? Search the guide: triggers, memory, deploy…" value="${esc(guideQuery)}"></div>
  <div id="gresults"></div>
  ${startHereHtml()}
  <div class="section"><div class="section-h"><h2>How it fits together</h2></div>
    <div class="card pad-l"><div class="glive" data-live="architecture"></div></div></div>
  <div class="section" id="learn">${learnHtml()}</div>
  </div>
  <div data-sp="settings" ${tab === "settings" ? "" : "hidden"}>
      <div class="section-h"><h2>Appearance</h2></div>
      <div class="card pad">
        <div class="row between wrap" style="gap:10px"><b class="small">Theme</b><div class="seg sm" id="themeseg">${[["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([k, l]) => `<button type="button" data-theme-pick="${k}" class="${pref("mc-theme", "system") === k ? "on" : ""}">${l}</button>`).join("")}</div></div>
        <div class="row between wrap" style="gap:10px;margin-top:12px"><b class="small">Opens on</b><select class="input" id="startpick" style="width:auto">${[["", "Home"], ["#/build", "Code"], ["#/missions", "Agents"], ["#/wiki", "Wiki"], ["#/chat", "Chat"], ["#/system", "Stack"]].map(([k, l]) => `<option value="${k}" ${pref("mc-start", "") === k ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      </div>
      <div class="section-h section"><h2>Notifications</h2>${how("delivery")}</div>
      ${notifyHtml(sy)}
      <div class="section-h section"><h2>This device</h2>${how("first-ten-minutes")}</div>
      <div class="card pad" id="device"></div>
  </div>`;
  subsInto($("#subs"));
  $$("[data-theme-pick]").forEach((b) => (b.onclick = () => {
    const v = b.dataset.themePick;
    try { localStorage.setItem("mc-theme", v); } catch (_) { /* then it holds until the page reloads */ }
    window.applyTheme?.(v);
    $$("[data-theme-pick]").forEach((x) => x.classList.toggle("on", x === b));
  }));
  if ($("#startpick")) $("#startpick").onchange = (e) => { try { localStorage.setItem("mc-start", e.target.value); } catch (_) { /* nothing to keep it in */ } };
  $$("[data-st]").forEach((b) => (b.onclick = () => {
    stackTab = b.dataset.st;
    try { localStorage.setItem("mc-stack-tab", stackTab); } catch (_) { /* a remembered tab is a convenience */ }
    $$("[data-st]").forEach((x) => x.classList.toggle("on", x === b));
    $$("[data-sp]").forEach((p) => (p.hidden = p.dataset.sp !== stackTab));
    scrollTo(0, 0);
  }));
  bindA2a();                                            // TSK-19: outside agents
  bindStackTools();
  if (!TOOLS) toolsLoad().then(() => { const b = $("#toolsbox"); if (b) { b.innerHTML = stackToolsHtml(); bindStackTools(); } });
  bindLearn();
  fillLive();
  $$("[data-mem]").forEach((b) => (b.onclick = async () => { b.disabled = true; await act({ action: "memory", id: b.dataset.id, decision: b.dataset.mem }, b.dataset.mem === "approve" ? "Remembered: Hermes knows it from the next chat" : "Discarded: it is not remembered"); }));
  deviceCard();
  bindNotify();
  if (scrollToLearn) { scrollToLearn = false; setTimeout(() => $("#learn")?.scrollIntoView({ block: "start" }), 30); }
}

async function deviceCard() {
  const el = $("#device");
  if (!el) return;
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const ios = /iphone|ipad/i.test(navigator.userAgent);
  let sub = null;
  const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.ready.catch(() => null) : null;
  if (reg && "pushManager" in reg) sub = await reg.pushManager.getSubscription().catch(() => null);
  const canPush = reg && "PushManager" in window && (!ios || standalone);
  el.innerHTML = `
    ${standalone ? `<div class="row small"><span class="dot ok"></span>Installed as an app</div>` : `<div class="small muted">${ios ? "Install: Share → “Add to Home Screen”." : "Install: browser menu → “Install app” / “Add to Home screen”."}</div>`}
    <label class="switch" style="margin-top:6px"><span><b>Push notifications</b><div class="small muted">${canPush ? "Finished runs, events, errors, new missions" : ios ? "On iPhone only after installing the app" : "Not supported by this browser"}</div></span><input type="checkbox" id="pushsw" ${sub ? "checked" : ""} ${canPush ? "" : "disabled"}></label>
    ${sub ? `<button class="btn sm" id="pushtest" style="margin-top:4px">${ic.bell}Send a test</button>` : ""}`;
  const sw = $("#pushsw");
  if (sw) sw.onchange = async () => {
    try {
      if (sw.checked) {
        if ((await Notification.requestPermission()) !== "granted") { sw.checked = false; return toast("Notifications not allowed", true); }
        const { key } = await api("/api/push/key");
        const pad = "=".repeat((4 - (key.length % 4)) % 4), raw = atob((key + pad).replace(/-/g, "+").replace(/_/g, "/"));
        const s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: Uint8Array.from(raw, (c) => c.charCodeAt(0)) });
        await api("/api/push/subscribe", { method: "POST", body: JSON.stringify(s.toJSON()) });
        toast("Push on");
      } else {
        const s = await reg.pushManager.getSubscription();
        if (s) { await api("/api/push/unsubscribe", { method: "POST", body: JSON.stringify(s.toJSON()) }); await s.unsubscribe(); }
        toast("Push off");
      }
    } catch (e) { sw.checked = !sw.checked; toast("Push: " + e.message, true); }
    deviceCard();
  };
  const t = $("#pushtest");
  if (t) t.onclick = async () => { await api("/api/push/test", { method: "POST" }); toast("Test sent"); };
}

// ---------- live data ----------
function onState(s) {
  const wasRunning = S?.running?.id, first = !S;
  S = s;
  lastState = Date.now();
  if (first && ["mission", "chat", "wiki", "new", "system", "build", "repo", "guide", "crew", "house", "tasks", "files", "file"].includes(route.name)) return render(true);
  if (route.name === "tasks" && !first) { tasksUpdate(); chrome(); return; }
  if (first && route.name === "swarm" && ["improve", "agents"].includes(swTab)) return render(true);   // FND-36: they read S
  if (route.name === "house" && !first) { houseUpdate(); chrome(); return; }
  if (route.name === "memory" && $("#memprobs")) { const p = $("#memprobs"), h = memProbsHtml(); if (p.innerHTML !== h) p.innerHTML = h; }   // the map's problems, as the keepers report them
  if (route.name === "guide") { guideOnState(); chrome(); return; }
  if (route.name === "home" && !first && $("#homefeed")) { homeUpdate(); chrome(); return; }
  if (route.name === "system" && $("#rescard") && !first) { $("#rescard").innerHTML = resourcesHtml(S.resources); guideOnState(); chrome(); return; }
  if (wasRunning && S.running?.id === wasRunning && $("#livelog") && (route.name === "home" || (route.name === "mission" && tab === "overview"))) {
    $("#livelog").textContent = (S.running.tail || []).join("\n") || "Starting…";        // update in place, no flicker
    const st = $(".runcard .steps"); if (st && S.running.steps) st.outerHTML = stepsHtml(S.running.steps);
    chrome(); return;
  }
  render();
}
// ---------- no connection: say why instead of loading forever (the shell itself comes from the phone's cache) ----------
const bootAt = Date.now();
let lastState = 0;
const noLink = () => !S && Date.now() - bootAt > 8000;
function offlineHtml() {
  return `<div class="card pad-l" id="offline"><h2>Can't reach your AI stack</h2>
    <div class="small" style="margin-top:8px;line-height:1.6">This device gets no answer from the PC. Usually <b>Tailscale is off on this device</b>: open the Tailscale app and switch it on. Otherwise the PC is asleep or off.</div>
    <div class="small muted" style="margin-top:8px">This page connects by itself as soon as it can.</div></div>`;
}
setInterval(() => { if (noLink() && !$("#offline") && $("#view .skeleton")) render(true); chrome(); }, 4000);

function connect() {
  let es;
  try { es = new EventSource("/api/stream"); } catch (_) { return poll(); }
  es.onmessage = (e) => { try { onState(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => { es.close(); setTimeout(connect, 4000); poll(true); };
}
async function poll(once) {
  try { onState(await api("/api/state")); } catch (_) {}
  if (!once) setTimeout(poll, 5000);
}
setInterval(() => $$("[data-since]").forEach((el) => {
  const s = Math.max(0, (Date.now() - new Date(el.dataset.since)) / 1000);
  el.textContent = `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}), 1000);

// ---------- updates: an open app (an installed one stays open for days) notices a new version and reloads itself ----------
// The version the page was served with (APP-R15): an app opened from the offline cache took the server's first answer as its
// own and ran old code against a new server for good.
let bootVersion = window.APP_VERSION || null, updateReady = false;
async function checkVersion() {
  try {
    const { version } = await api("/api/version");
    if (!bootVersion) bootVersion = version;
    else if (version !== bootVersion && !updateReady) {
      updateReady = true;                                 // the next screen change loads the new version
      navigator.serviceWorker?.getRegistration().then((r) => r?.update()).catch(() => {});
      if (document.hidden || (!typing() && !streaming && route.name !== "new")) return location.reload();
      chrome();
    }
  } catch (_) {}
}
setInterval(checkVersion, 60000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) checkVersion(); });
checkVersion();

parseRoute();
render(true);
countView();
connect();
loadGuide().then(() => { chrome(); const l = $("#learn"); if (l) { l.innerHTML = learnHtml(); bindLearn(); } });   // chapters: each page's "How this page works", Stack page
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
