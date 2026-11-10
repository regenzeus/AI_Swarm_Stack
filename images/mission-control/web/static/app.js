// The app, part of app-base.js, app-tasks.js, app-runs.js, app-devices.js, app-wiki-code.js, app-memory.js, app-workflows.js, app.js (PLT-25): the Stack page (health, costs, tools, connections with packs and trackers, settings), live data, offline and updates, and the start. Loaded in that order; one global scope.
// ---------- stack (system) ----------
// ---------- tools: every tool the stack runs on, its menus one tap away (APP-30; web/static/tools.json is the one list) ----------
let TOOLS = null, toolQuery = "";
const toolsHere = (d) => ({ ...d, tools: (d.tools || []).filter((x) => !("host" in x) || (x.host && !/^https?:\/\/(:|\/|$)/.test(x.host))) });   // no address in this deployment: no tile
const toolsLoad = () => (TOOLS ? Promise.resolve(TOOLS) : fetch("/static/tools.json").then((r) => r.text()).then((t) => (TOOLS = toolsHere(JSON.parse(t.replace(/\{\{(\w+)\}\}/g, (_, k) => DEPLOY[k] || ""))))).catch(() => ({ tools: [], pages: [] })));
const toolBase = (t) => (t.host.startsWith("tailnet") ? HOSTURL + t.host.slice(7) : t.host);
const toolUrl = (t, m) => (t.host === "app" ? m.path : toolBase(t) + m.path);   // host "app": a page of this app (n8n inside it, WFL-13)
const toolAtHome = (t) => t.host !== "app" && !t.host.startsWith("tailnet") && !t.host.includes("tailscale.com");   // the home network only
const toolOf = (id) => (TOOLS?.tools || []).find((t) => t.id === id);
function toolState(t) {
  if (t.status === "house" && S.house) return S.house.reachable ? ["ok", "up"] : ["err", "not reachable"];
  return null;
}
const toolLinks = (t) => t.menus.map((m) => `<a class="tag" href="${esc(toolUrl(t, m))}"${t.host === "app" && m.path.startsWith("/#/") ? "" : ' target="_blank" rel="noopener"'}>${esc(m.name)}</a>`).join("");

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
  const pages = TOOLS.pages.filter(([n, , w]) => hit(`${n} ${w}`)).map(([n, href]) => ({ name: `${APPNAME()} → ${n}`, href, ext: false }));
  const menus = TOOLS.tools.flatMap((t) => t.menus.filter((m) => hit(`${t.name} ${m.name} ${m.words || ""} ${t.what}`)).map((m) => ({ name: `${t.name} → ${m.name}`, href: toolUrl(t, m), ext: !(t.host === "app" && m.path.startsWith("/#/")) })));
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

// GEN-21, GEN-25: packs and trackers, one section of the Stack page. A pack is a domain kept outside the repository (its
// agents, skills, commands, n8n workflows and exams), pinned by commit: a new commit runs only after Approve, and the
// commit approved before keeps running meanwhile. A tracker is an issue tracker the stack reads; what it would write back
// stays in shadow per kind of write until that kind goes live. The runner publishes both (ops/domain: packs.view, trackers.view).
let PK_SIG = "";
const packSig = () => JSON.stringify([S?.packs || null, S?.trackers || null]);
const pkShort = (sha) => String(sha || "").slice(0, 12);   /* cap: id: a commit's short name; the diff and the record keep it whole */
function packBrings(p) {
  const n = (xs, one, many) => (xs?.length ? `${nf(xs.length)} ${xs.length === 1 ? one : many}` : "");
  return [n(p.agents, "agent", "agents"), n(p.skills, "skill", "skills"), n(p.workflows, "workflow", "workflows"),
    n(p.jobs, "command", "commands"), n(p.exams, "exam set", "exam sets")].filter(Boolean).join(" · ") || "nothing yet";
}
function packCard(name, L, open) {
  const run = L.packs.find((p) => p.name === name), wait = L.pending.find((p) => p.name === name), no = L.refused.filter((r) => r.name === name);
  const agents = (xs) => xs.map((a) => `<details class="pk-item"><summary><b>${esc(a.id)}</b>${a.purpose ? ` · ${esc(a.purpose)}` : ""}${a.harness ? ` <span class="tiny faint">${esc(a.harness)}${a.model ? ` · ${esc(a.model)}` : ""}</span>` : ""}</summary><pre class="wrap small">${esc(a.prompt || "")}</pre></details>`).join("");
  const jobs = (xs) => xs.map((j) => `<details class="pk-item"><summary><b>${esc(j.kind)}</b>${j.about ? ` · ${esc(j.about)}` : ""}</summary><pre class="wrap small">${esc(JSON.stringify(j.spec, null, 2))}</pre></details>`).join("");
  const list = (label, xs) => (xs?.length ? `<div class="small wrap"><b>${label}</b> ${xs.map(esc).join(", ")}</div>` : "");
  const state = wait ? `<span class="pill paused">waits for you</span>` : run ? `<span class="pill ok">runs ${esc(pkShort(run.commit))}</span>` : `<span class="pill failed">refused</span>`;
  return `<details class="card pad pk${wait ? " pk-wait" : ""}" id="pack-${esc(name)}" data-keep="pack-${esc(name)}"${open ? " open" : ""}><summary>
      <div class="row between wrap" style="gap:4px 8px"><b class="wrap">${esc(name)}${run?.version ? ` ${esc(run.version)}` : ""}</b>${state}</div>
      <div class="small muted wrap">${esc((run || wait)?.about || "")}${(run || wait)?.about ? " · " : ""}${esc(packBrings(wait || run || {}))}</div></summary>
    ${wait ? `<div class="pk-decide"><div class="row between wrap" style="gap:8px"><b class="wrap">${wait.runs ? `Update from ${esc(pkShort(wait.runs))} to ${esc(pkShort(wait.commit))}?` : `Run its first commit, ${esc(pkShort(wait.commit))}?`}</b>
        <span class="row" style="gap:6px"><button class="btn sm ghost danger" data-pk="pack_refuse" data-name="${esc(name)}" data-commit="${esc(wait.commit)}">${ic.x}Refuse</button><button class="btn sm primary" data-pk="pack_approve" data-name="${esc(name)}" data-commit="${esc(wait.commit)}">${ic.check}Approve</button></span></div>
      ${wait.problems.length ? `<div class="small err-t wrap">${wait.problems.map(esc).join("<br>")}</div>` : ""}
      ${agents(wait.agents)}${jobs(wait.jobs)}${list("Workflows", wait.workflows)}${list("Skills", wait.skills)}
      <details class="pk-item" data-keep="pkdiff-${esc(name)}"><summary>What changed${wait.runs ? ` since ${esc(pkShort(wait.runs))}` : ": the whole pack"}</summary><pre class="wrap small pk-diff">${esc(wait.diff || "")}</pre></details></div>` : ""}
    ${run ? `<div class="pk-runs">${wait ? `<div class="tiny faint">Runs now, at ${esc(pkShort(run.commit))}:</div>` : ""}${agents(run.agents)}${jobs(run.jobs)}
      ${list("Workflows", run.workflows)}${list("Skills", run.skills)}${list("Exam sets", run.exams)}${list("MCP servers", run.mcp)}
      ${run.problems.length ? `<div class="small err-t wrap">${run.problems.map(esc).join("<br>")}</div>` : ""}</div>` : ""}
    ${no.map((r) => `<div class="small err-t wrap">${r.commit ? `${esc(pkShort(r.commit))}: ` : ""}${esc(r.why)}</div>`).join("")}</details>`;
}
function trackersHtml(T) {
  const need = T.shadow_needed || 0;
  return `${T.trackers.map((t) => `<div class="card pad"><div class="row between wrap" style="gap:4px 8px"><b class="wrap">${esc(t.name)}</b><span class="pill">${esc(t.kind)}</span></div>
      <div class="small muted wrap">starts ${t.workflow ? `<a href="#/workflows">${esc(t.workflow)}</a>` : "no workflow"} · read up to ${t.cursor ? esc(dt(t.cursor)) : "nothing yet"}</div></div>`).join("")}
    ${T.kinds.map((k) => `<div class="card pad tk-kind"><div class="row between wrap" style="gap:6px 8px"><b>${esc(k.kind)}</b>
        <span class="row wrap" style="gap:6px"><span class="pill ${k.live ? "ok" : ""}">${k.live ? "live" : "in shadow"}</span>${k.live ? `<button class="btn sm" data-tk-live="0" data-kind="${esc(k.kind)}">Back to shadow</button>`
          : `<button class="btn sm${k.approved >= need ? " primary" : ""}" data-tk-live="1" data-kind="${esc(k.kind)}"${k.approved >= need ? "" : " disabled"}>Go live</button>`}</span></div>
      <div class="small muted">${nf(k.approved)} of ${nf(need)} judged right${k.pending ? ` · <b>${nf(k.pending)} waiting for you</b>` : ""}</div>
      ${(k.items || []).filter((i) => i.status === "pending").map((i) => `<div class="tk-item"><div class="tiny faint">${esc(i.tracker)}/${esc(i.key)} · ${esc(dt(i.at))}</div>
        <pre class="wrap small">${esc(i.body)}</pre><div class="row" style="gap:6px;justify-content:flex-end"><button class="btn sm ghost" data-tk="tracker_shadow_reject" data-kind="${esc(k.kind)}" data-id="${esc(i.id)}">${ic.x}Wrong</button><button class="btn sm primary" data-tk="tracker_shadow_approve" data-kind="${esc(k.kind)}" data-id="${esc(i.id)}">${ic.check}Right</button></div></div>`).join("")}</div>`).join("")}`;
}
function packsHtml() {
  PK_SIG = packSig();
  const L = S?.packs || { packs: [], pending: [], refused: [] }, T = S?.trackers || { trackers: [], kinds: [], shadow_needed: 0 };
  const names = [...new Set([...L.pending, ...L.packs, ...L.refused].map((p) => p.name))], want = route.q.get("pack");
  const head = `<div class="section-h section" id="packs"><h2>Packs and trackers</h2>${explain("packs-what", `A pack brings agents, skills, commands, n8n workflows and exams from a repository of its own, pinned by commit in the deployment's packs.txt. A new commit runs only after you approve it here; until then the commit you approved before keeps running, and each of its commands is approved again where it runs. A tracker is an issue tracker the stack reads (trackers.yaml): what it would write back stays in shadow, kept here and in Needs you, until you judged ${nf(T.shadow_needed || 0)} writes of a kind right and let that kind go live. ${how("workflows")}`, "About packs and trackers")}</div>`;
  if (!names.length && !T.trackers.length) return `${head}${emptyState("No packs or trackers: this deployment's packs.txt and trackers.yaml list none.", `<a class="btn sm" href="#/guide/workflows">${ic.doc}How packs come in</a>`, "card pad")}`;
  return `${head}<div class="stack">${names.map((n) => packCard(n, L, n === want || L.pending.some((p) => p.name === n))).join("")}${trackersHtml(T)}</div>`;
}
function bindPacks() {
  $$("[data-pk]").forEach((b) => (b.onclick = async () => {
    const why = b.dataset.pk === "pack_refuse" ? prompt("Why not? It is kept with the refusal.", "") : "";
    if (why === null) return;
    b.disabled = true;
    const r = await act({ action: b.dataset.pk, name: b.dataset.name, commit: b.dataset.commit, why }, b.dataset.pk === "pack_approve" ? "Approved: this commit runs from now on" : "Refused: the commit that ran keeps running");
    if (!r) b.disabled = false;
  }));
  $$("[data-tk]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    if (!(await act({ action: b.dataset.tk, kind: b.dataset.kind, id: b.dataset.id }, b.dataset.tk === "tracker_shadow_approve" ? "Judged right: it counts toward going live" : "Judged wrong: it does not count, and this kind stays in shadow"))) b.disabled = false;
  }));
  $$("[data-tk-live]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    const live = b.dataset.tkLive === "1";
    if (!(await act({ action: "tracker_live", kind: b.dataset.kind, live }, live ? "Live: this kind of write now reaches the tracker" : "Back in shadow: nothing of this kind leaves the stack"))) b.disabled = false;
  }));
}

// APP-47, DEC-53: the Stack page is the stack's own, one part at a time: Health (services, resources, jobs, checks,
// backups), Costs (what was paid, the subscriptions, the agents day by day), Tools, Connections (Gmail, outside agents,
// packs and trackers) and Settings. The guide has its own page (#/guide), one tap from the title row.
const STACK_TABS = [["health", "Health"], ["costs", "Costs"], ["tools", "Tools"], ["connections", "Connections"], ["settings", "Settings"]];
const START_PAGES = [["", "Home"], ["#/tasks", "Tasks"], ["#/workflows", "Workflows"], ["#/memory", "Memory"], ["#/build", "Code"], ["#/chat", "Chat"], ["#/system", "Stack"]];   // APP-49: where the app opens, the menu's names
const OLD_START = { "#/missions": "#/tasks", "#/wiki": "#/memory" };   // a choice kept from before DEC-46 and the Memory tab
let stackTab = "";
function stackHealthHtml(sy, svc) {
  return `<a class="banner info mb-3" href="#/traces">${ic.search}<span class="grow"><b>Traces</b> · every model call with its prompt and answer (Phoenix)</span>${ic.next}</a>
  <div class="grid g2">
    <div class="card kpi"><div class="kpi-l">Last backup</div><div class="kpi-v" style="font-size:20px">${sy.backup ? rel(new Date(sy.backup.ts * 1000).toISOString()) : "–"}</div><div class="kpi-s">${sy.drill ? "restore test: " + esc(sy.drill.result) : ""}</div></div>
    <div class="card kpi"><div class="kpi-l">Long-term memory</div><div class="kpi-v">${nf(sy.memory?.facts)}</div><div class="kpi-s">facts · ${nf(sy.memory?.observations)} observations</div></div>
  </div>
  <div class="section-h section"><h2>Resources</h2>${how("stack-page")}</div>
  <div id="rescard">${resourcesHtml(S.resources)}</div>
  <div class="split section">
    <div>
      <div class="section-h"><h2>Services</h2>${how("stack-page")}</div>
      <div class="card grid g2" style="gap:0">${svc.map((s) => `<div class="svc"><span class="dot ${s.state === "running" ? (/unhealthy/.test(s.status) ? "warn" : "ok") : "err"}"></span><span class="n">${esc(s.name)}</span><span class="tiny faint">${esc(s.status.replace(/^Up /, "").replace(/ \(healthy\)/, ""))}</span></div>`).join("")}</div>
    </div>
    <div>
      <div class="section-h"><h2>Scheduled jobs</h2>${how("stack-page")}</div>
      <div class="card list">${(sy.timers || []).map((t) => { const failed = (sy.failed || []).some((f) => f.startsWith(t.unit + ".")); return `<div><div class="ic ${failed ? "err" : ""}">${failed ? ic.alert : ic.clock}</div><div class="grow"><div class="ttl">${esc((S.crew || []).find((c) => c.unit === t.unit)?.name || t.unit)}</div><div class="sub">last ${t.last ? rel(new Date(t.last / 1000).toISOString()) : "–"}</div></div><div class="tiny faint" style="white-space:nowrap">${t.next ? rel(new Date(t.next / 1000).toISOString()) : "–"}</div></div>`; }).join("")}</div>
    </div>
  </div>
  ${stackChecks(sy)}`;
}
function stackCostsHtml(sy) {
  const today = sy.agents_today || [], max = Math.max(1, ...today.map((x) => x.tokens));
  return `<div class="grid g2">
    <div class="card kpi"><div class="kpi-l">Paid today</div><div class="kpi-v">${usd(sy.spend_today)}</div><div class="kpi-s">30 days: ${usd(sy.spend_30d)}</div></div>
    <div class="card kpi"><div class="kpi-l">Credit used</div><div class="kpi-v">${usd(sy.spend_total)}</div><div class="kpi-s">of $${nf(sy.budget_total || 10)}</div><div class="meter"><i style="width:${Math.min(100, ((sy.spend_total || 0) / (sy.budget_total || 10)) * 100).toFixed(1)}%"></i></div></div>
  </div>
  <div id="subs" class="section"></div>
  <div class="section-h section"><h2>Agents today</h2>${how("technology")}</div>
  <div class="card list">${today.map((a) => `<div style="align-items:center"><span class="agent ${esc(a.agent)}">${esc(a.agent)}</span><div class="grow"><div class="meter" style="margin:0"><i style="width:${((a.tokens / max) * 100).toFixed(1)}%"></i></div></div><div class="small num" style="min-width:110px;text-align:right">${nf(a.calls)} · ${tok(a.tokens)}</div></div>`).join("") || `<div class="muted small">No calls today</div>`}</div>
  <div id="telbox"><div class="skeleton section" style="height:200px"></div></div>`;
}
function stackLine(sy, svc) {                              // the title's line: how the stack is, whichever part is open
  if (notConnected()) return `<b class="err-t">${esc(linkWords())}</b>: its state is not known`;
  if (!svc.length) return "the services' state comes with the runner's next report";
  const down = svc.filter((s) => s.state !== "running");
  const failed = (sy.failed || []).map((u) => {             // which one, one tap to it (UX review 2026-10-30)
    const c = (S.crew || []).find((x) => `${x.unit}.service` === u);
    return c ? `<a class="err-t" href="#/crew/${encodeURIComponent(c.id)}">${esc(c.name)}</a>` : esc(u.replace(/\.service$/, ""));
  });
  return `${down.length ? `<b class="err-t">${down.length} service${down.length > 1 ? "s" : ""} not running</b>` : "all services running"} · ${failed.length ? `<b class="err-t">failed: ${failed.join(", ")}</b>` : "no errors"}${sy.boot ? ` · last start ${rel(new Date(sy.boot.boot * 1000).toISOString())}, online in ${dur(sy.boot.ready_s)}` : ""}`;
}
function vSystem() {
  const sy = S.system || {}, svc = sy.services || [];
  if (route.q.get("tab") === "guide") { location.replace("#/guide"); return; }       // the guide has its own page (DEC-53)
  const asked = route.q.get("conn") ? "connections" : route.q.get("tab");
  if (STACK_TABS.some(([k]) => k === asked)) stackTab = asked;
  if (!stackTab) stackTab = pref("mc-stack-tab", "health");
  if (!STACK_TABS.some(([k]) => k === stackTab)) stackTab = "health";               // a part remembered from before
  const tab = stackTab, part = (k, html) => `<div data-sp="${k}" ${tab === k ? "" : "hidden"}>${html}</div>`;
  view.innerHTML = `
  <div class="hero stackhero"><div class="grow"><h1>Stack</h1><p>${stackLine(sy, svc)}</p></div>
    <div class="row wrap stackact"><a class="btn sm" href="#/guide">${ic.doc}Guide</a><a class="btn sm" href="#/files" title="What your tasks made, the space it takes, the trash">${ic.archive}Files · ${fsize(S.files?.usage?.used || 0)}${(S.files?.usage?.pct || 0) >= 80 ? ` <b class="err-t">${S.files.usage.pct} %</b>` : ""}</a></div></div>
  <nav class="seg stackseg" aria-label="Parts of this page">${STACK_TABS.map(([k, l]) => `<button type="button" data-st="${k}" class="${tab === k ? "on" : ""}">${l}</button>`).join("")}</nav>
  ${part("health", stackHealthHtml(sy, svc))}
  ${part("costs", stackCostsHtml(sy))}
  ${part("tools", `${phoneBanner()}<div id="toolsbox">${stackToolsHtml()}</div>`)}
  ${part("connections", `<div class="section-h"><h2>Accounts and agents</h2>${how("connections")}</div>
    <div id="conncard" class="stack mb-3"><div class="skeleton" style="height:90px"></div></div>
    ${a2aCardHtml()}
    <div id="packsbox">${packsHtml()}</div>`)}
  ${part("settings", `<div class="section-h"><h2>Appearance</h2></div>
    <div class="card pad">
      <div class="row between wrap" style="gap:10px"><b class="small">Theme</b><div class="seg sm" id="themeseg">${[["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([k, l]) => `<button type="button" data-theme-pick="${k}" class="${pref("mc-theme", "system") === k ? "on" : ""}">${l}</button>`).join("")}</div></div>
      <div class="row between wrap" style="gap:10px;margin-top:12px"><b class="small">Opens on</b><select class="input" id="startpick" style="width:auto">${START_PAGES.map(([k, l]) => `<option value="${k}" ${(OLD_START[pref("mc-start", "")] || pref("mc-start", "")) === k ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    </div>
    <div class="section-h section"><h2>Notifications</h2>${how("delivery")}</div>
    ${notifyHtml(sy)}
    <div class="section-h section"><h2>This device</h2>${how("first-ten-minutes")}</div>
    <div class="card pad" id="device"></div>`)}`;
  $$("[data-theme-pick]").forEach((b) => (b.onclick = () => {
    const v = b.dataset.themePick;
    try { localStorage.setItem("mc-theme", v); } catch (_) { /* then it holds until the page reloads */ }
    window.applyTheme?.(v);
    $$("[data-theme-pick]").forEach((x) => x.classList.toggle("on", x === b));
  }));
  if ($("#startpick")) $("#startpick").onchange = (e) => { try { localStorage.setItem("mc-start", e.target.value); } catch (_) { /* nothing to keep it in */ } };
  const opened = (k) => { if (k === "costs") { subsInto($("#subs")); telInto($("#telbox")); } };   // a part's slower data loads when it opens
  $$("[data-st]").forEach((b) => (b.onclick = () => {
    stackTab = b.dataset.st;
    setPref("mc-stack-tab", stackTab);                    // a remembered part is a convenience
    history.replaceState(history.state, "", `#/system?tab=${stackTab}`);
    $$("[data-st]").forEach((x) => x.classList.toggle("on", x === b));
    $$("[data-sp]").forEach((p) => (p.hidden = p.dataset.sp !== stackTab));
    opened(stackTab);
    scrollTo(0, 0);
  }));
  opened(tab);
  bindA2a();                                            // TSK-19: outside agents
  bindPacks();                                          // GEN-21, GEN-25
  bindStackTools();
  if (!TOOLS) toolsLoad().then(() => { const b = $("#toolsbox"); if (b) { b.innerHTML = stackToolsHtml(); bindStackTools(); } });
  deviceCard();
  bindNotify();
  const at = route.q.get("pack") ? `pack-${route.q.get("pack")}` : route.q.get("at");   // a pack's decision in Needs you opens its card
  if (at) setTimeout(() => document.getElementById(at)?.scrollIntoView({ block: "start" }), 30);
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
  lastAlive = Date.now();
  LINK = s.link || LINK;                                 // APP-65: how the runner is, as the app sees it
  if (first && ["mission", "chat", "wiki", "new", "system", "build", "repo", "guide", "crew", "house", "tasks", "files", "file", "task"].includes(route.name)) return render(true);   // a task page opened cold: its Where it runs needs the state (WFL-11)
  if (route.name === "tasks" && !first) { tasksUpdate(); chrome(); return; }
  if (first && route.name === "swarm" && ["improve", "agents"].includes(swTab)) return render(true);   // FND-36: they read S
  if (route.name === "house" && !first) { houseUpdate(); chrome(); return; }
  if (route.name === "memory" && $("#memprobs")) { const p = $("#memprobs"), h = memProbsHtml(); if (p.innerHTML !== h) p.innerHTML = h; }   // the map's problems, as the keepers report them
  if (route.name === "guide") { guideOnState(); chrome(); return; }
  if (route.name === "home" && !first && $("#homefeed")) { homeUpdate(); chrome(); return; }
  if (route.name === "system" && $("#rescard") && !first) {
    $("#rescard").innerHTML = resourcesHtml(S.resources);
    if (packSig() !== PK_SIG && !typing()) {             // GEN-21: redrawn only when the packs or trackers change, keeping what you opened
      const box = $("#packsbox"), open = $$("details[open][data-keep]", box).map((d) => d.dataset.keep);
      box.innerHTML = packsHtml();
      open.forEach((k) => { const d = box.querySelector(`details[data-keep="${CSS.escape(k)}"]`); if (d) d.open = true; });
      bindPacks();
    }
    chrome(); return;
  }
  if (wasRunning && S.running?.id === wasRunning && $("#livelog") && (route.name === "home" || (route.name === "mission" && tab === "overview"))) {
    $("#livelog").textContent = (S.running.tail || []).join("\n") || "Starting…";        // update in place, no flicker
    const st = $(".runcard .steps"); if (st && S.running.steps) st.outerHTML = stepsHtml(S.running.steps);
    chrome(); return;
  }
  render();
}
// ---------- no connection: say why instead of loading forever (the shell itself comes from the phone's cache) ----------
const bootAt = Date.now();
let lastAlive = 0, LINK = null;                            // when the app last answered, and what it said of the runner
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
  es.addEventListener("alive", (e) => {                     // APP-65: every 15 s, also while the runner writes nothing
    try { const l = JSON.parse(e.data); LINK = { ...l, ready_s: l.ready_s ?? LINK?.ready_s }; lastAlive = Date.now(); chrome(); } catch (_) {}
  });
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
loadGuide().then(() => { chrome(); const l = $("#learn"); if (l) { l.innerHTML = learnHtml(); bindLearn(); } });   // chapters: each page's "How this page works", the guide's index
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
