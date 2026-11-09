// The app, part of app-base.js, app-tasks.js, app-runs.js, app-devices.js, app-wiki-code.js, app-memory.js, app.js (PLT-25): Memory, skills, Claude tasks and the repository page. Loaded in that order; one global scope.
// ---------- Memory (APP-50): what the stack knows and can look up. Each kind of knowledge has one home ----------
const MEM_TABS = [["memory", "#/memory", "All"], ["wiki", "#/wiki", "Wikis"], ["longterm", "#/longterm", "Long-term"], ["codemem", "#/codemem", "Code"], ["howto", "#/howto", "How-to"], ["journals", "#/journals", "Journals"]];
const MEM_HOW = `<ol class="memflow">${[["Before a run", "An agent is subscribed to the memory its role needs. Its opening is chosen for its task from those, within a budget; what does not fit is listed so it can open it, and other memory that matches is offered."],
  ["During a run", "One memory tool: search everything it may read, open one entry, subscribe to more, note a lesson, fact or failure. A coder gets a note on each file the first time it reads it."],
  ["After a run", "What it was given and what it used are measured. Its notes and results enter memory only after a check, each with its Undo."],
  ["Every night and week", "The memory agent retires duplicates, settles your facts by date, moves what is not about you to the wikis, splits wikis that grew too big and turns repeated work into lessons and skills. Nothing is deleted."]].map(([t, d]) => `<li><b>${t}</b><span>${d}</span></li>`).join("")}</ol>`;
function memFrame(cur) {
  return `<div class="hero heading" style="margin-bottom:10px"><div class="row between" style="gap:10px"><h1>Memory</h1>${how("knowledge")}</div></div>
    <form class="wsearch memsearch" id="memq">${ic.search}<input class="input" name="q" autocomplete="off" placeholder="What does it know about…" value="${esc(route.name === "memsearch" ? route.q.get("q") || "" : "")}"></form>
    <nav class="seg memtabs" aria-label="Kinds of memory">${MEM_TABS.map(([k, h, l]) => `<a class="${cur === k ? "on" : ""}" href="${h}">${l}</a>`).join("")}</nav>
    ${explain("memory-how", MEM_HOW, "How memory reaches an agent")}`;
}
function bindMemFrame() {
  const f = $("#memq");
  if (f) f.onsubmit = (e) => { e.preventDefault(); const q = f.q.value.trim(); if (q.length > 1) location.hash = `#/memsearch?q=${encodeURIComponent(q)}`; };
}

// Long-term: what it knows about you. Each fact whole, with its kind, where it came from and its own Forget
const FACT_KIND = { world: "Fact", experience: "Something that happened", observation: "Drawn from several" };
const factSource = (f) => (f.chat ? `<a class="memfrom" href="#/chat?c=${encodeURIComponent(f.chat)}">from a chat ${ic.next}</a>` : f.source === "agent journal" ? `<span class="tiny faint">from an agent's journal</span>` : f.type === "observation" ? `<span class="tiny faint">from other facts</span>` : `<span class="tiny faint">source not recorded</span>`);
const factRow = (f, tools = true) => `<div class="memfact" data-fact="${esc(f.id)}"><div class="row wrap" style="gap:6px"><span class="tag">${esc(FACT_KIND[f.type] || f.type)}</span><span class="tiny faint">${esc(f.date)}</span>${factSource(f)}</div>
  <div class="small wrap" style="margin-top:4px">${esc(f.text)}</div>${(f.entities || []).length ? `<div class="tiny faint wrap" style="margin-top:3px">${f.entities.map(esc).join(" · ")}</div>` : ""}
  ${tools ? `<button type="button" class="linkbtn tiny" data-forget="${esc(f.id)}">Forget</button>` : ""}</div>`;
let ltShow = "all";
async function vLongTerm() {
  view.innerHTML = `${memFrame("longterm")}<div class="skeleton" style="height:240px"></div>`;
  bindMemFrame();
  const r = await act({ action: "memory_browse" }, null);
  if (route.name !== "longterm") return;
  const facts = r?.facts || [], kinds = [["all", "All"], ["world", "Facts"], ["experience", "Happened"], ["observation", "Drawn from several"]];
  const moved = r?.move?.length ? `<a class="banner info" href="#/longterm?move=1" style="margin-bottom:12px">${ic.alert}<span class="grow"><b>${nf(r.move.length)} are not about you.</b> See them before they move to a wiki.</span>${ic.next}</a>` : "";
  if (route.q.get("move") && r?.move?.length) return memMove(r.move);
  view.innerHTML = `${memFrame("longterm")}${moved}
    ${r?.profile ? `<div class="section-h memgroup"><h3>Your profile</h3><span class="tiny faint">in every prompt</span></div><div class="card pad small wrap" style="white-space:pre-wrap">${esc(r.profile)}</div>` : ""}
    <div class="section-h memgroup"><h3>Facts · ${nf(facts.length)}</h3><a class="tiny" href="#/crew/memory">Retired, with Undo</a></div>
    <div class="agf" style="margin-bottom:10px">${kinds.map(([k, l]) => `<button class="fchip ${ltShow === k ? "on" : ""}" data-lt="${k}">${l}</button>`).join("")}</div>
    <div class="card memlist" id="ltlist"></div>`;
  bindMemFrame();
  const draw = () => {
    $("#ltlist").innerHTML = facts.filter((f) => ltShow === "all" || f.type === ltShow).map((f) => factRow(f)).join("") || `<div class="small muted" style="padding:12px 0">None of this kind.</div>`;
    $$("[data-forget]").forEach((b) => (b.onclick = async () => {
      b.disabled = true;
      if (await act({ action: "crew_memory_forget", ids: [b.dataset.forget], why: "forgotten by the owner, on the Memory tab" }, "Forgotten: it is out of recall, and can be restored under Retired")) { const i = facts.findIndex((f) => f.id === b.dataset.forget); if (i >= 0) facts.splice(i, 1); draw(); } else b.disabled = false;
    }));
  };
  draw();
  $$("[data-lt]").forEach((b) => (b.onclick = () => { ltShow = b.dataset.lt; $$("[data-lt]").forEach((x) => x.classList.toggle("on", x === b)); draw(); }));
}
// The leak (docs/MEMORY.md): what is not about the owner, shown before anything happens. Each can stay; each moved one has its Undo
function memMove(list) {
  const topics = [...new Set(list.map((x) => x.topic))].sort();
  view.innerHTML = `<a class="back" href="#/longterm">${ic.back}Long-term</a><div class="hero heading" style="margin-bottom:10px"><h1>Not about you · ${nf(list.length)}</h1></div>
    ${explain("mem-move", "These go to a wiki as filed sources, with the chat they came from, and leave long-term memory. Untick any that should stay. Each can be undone under Retired.", "What happens to these")}
    ${topics.map((t) => { const l = list.filter((x) => x.topic === t); return `<details class="card pad memtopic" style="margin-top:10px"><summary><label class="row" style="gap:10px;display:inline-flex" onclick="event.stopPropagation()"><input type="checkbox" data-mvall="${esc(t)}" checked></label> <b class="small">${esc(t)}</b> <span class="num tiny faint">${l.length}</span></summary>
      <div style="margin-top:8px">${l.map((x) => `<label class="memfact row" style="gap:10px;align-items:flex-start"><input type="checkbox" data-mv="${esc(x.id)}" data-mvt="${esc(t)}" checked style="margin-top:3px"><span class="small wrap">${esc(x.text)}</span></label>`).join("")}</div></details>`; }).join("")}
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn primary" id="mvgo">${ic.check}Move the ticked ones</button></div>`;
  $$("[data-mvall]").forEach((b) => (b.onchange = () => $$("[data-mv]").filter((x) => x.dataset.mvt === b.dataset.mvall).forEach((x) => (x.checked = b.checked))));
  $("#mvgo").onclick = async () => {
    const ids = $$("[data-mv]").filter((b) => b.checked).map((b) => b.dataset.mv), keep = $$("[data-mv]").filter((b) => !b.checked).map((b) => b.dataset.mv);
    $("#mvgo").disabled = true;
    const r = await act({ action: "memory_move", ids, keep }, (x) => `Moved ${x?.moved ?? 0}: filed for the wikis, and each can be undone under Retired`);
    if (r) location.hash = "#/longterm"; else $("#mvgo").disabled = false;
  };
}

// All (MEM-45): the catalogue. Every collection of memory by sector: what question it answers, how big, how trustworthy, how much runs got of it
const SECTOR_HREF = (c) => {
  const id = c.id;
  if (id === "owner:facts" || id === "owner:profile") return "#/longterm";
  if (id === "world:sources") return "#/sources";
  if (id.startsWith("world:")) { const [root, part] = id.slice(6).split("#"); return `#/wiki?root=${encodeURIComponent(root)}${part ? `&page=${encodeURIComponent(`parts/${part}`)}` : ""}`; }
  if (id.startsWith("code:")) return `#/repo/${encodeURIComponent(id.slice(5))}?tab=wiki`;
  if (id === "howto:skills") return "#/skills";
  if (id.startsWith("howto:lessons/")) return `#/howto?role=${encodeURIComponent(id.slice(14))}`;
  if (id.startsWith("agent:")) return journalHref(id.slice(6));
  if (id === "work:ledger") return "#/swarm";
  return "#/memory";
};
const TRUST_WORD = { exact: "exact record", compiled: "compiled from sources", extracted: "extracted by a model" };
const ACCESS_WORD = { private: "private: its mission only", own: "its agent only", owner: "you; matched recall for agents" };
const KIND_WORD = { code: "Coding steps", review: "Review steps", mission: "Missions", crew: "Crew jobs", task: "Other steps" };
function memStatusHtml(st) {
  const h = st?.health || {}, kinds = Object.keys(h);
  if (!kinds.length) return `<div class="tiny faint" style="margin-bottom:12px">Given and used are measured from the first runs after this memory went live.</div>`;
  return `<div class="memstats">${kinds.map((k) => `<div class="card pad memstat"><div class="tiny faint">${esc(KIND_WORD[k] || k)} · ${nf(h[k].runs)} run${h[k].runs === 1 ? "" : "s"} in 30 days</div>
    <div class="row wrap" style="gap:4px 12px;margin-top:4px"><span class="num"><b>${nf(h[k].given_per_run)}</b> <span class="tiny faint">characters given a run, of ${nf(h[k].budget)}</span></span>
    <span class="num"><b>${h[k].used_share == null ? "unknown" : `${Math.round(100 * h[k].used_share)} %`}</b> <span class="tiny faint">of it used</span></span></div></div>`).join("")}</div>`;
}
// The map (APP-55): each sector of memory as one box with what it holds (summed per unit), how many runs drew on it in
// 7 days and its biggest collections; the keepers' problems on top (Stack's memory inventory). A box opens its list below.
const SECTOR_WORD = { owner: "what it knows about you", world: "what it has worked out about the world", code: "how your repositories work",
  howto: "how to do a job well", agents: "each agent's own notebook", work: "ideas, findings and decisions" };
const MEM_TOP = 3;                                            // the biggest collections on a box; its list below has every one
const memProbsHtml = () => (S?.memory?.stores || []).flatMap((m) => (m.problems || []).map((p) => `<div class="banner warn">${ic.alert}<span class="grow small wrap"><b>${esc(m.name)}:</b> ${esc(p)}</span></div>`)).join("");
function memMapHtml(cs, sectors) {
  const box = ([k, l]) => {
    const xs = cs.filter((c) => c.sector === k && !c.parent);
    if (!xs.length) return "";
    const units = {};
    for (const c of xs) if (c.size != null) units[c.unit || ""] = (units[c.unit || ""] || 0) + c.size;
    const runs = xs.reduce((n, c) => n + ((c.given_7d || {}).runs || 0), 0);
    const top = [...xs].sort((x, y) => (y.size || 0) - (x.size || 0)).slice(0, MEM_TOP);   /* cap: top: the biggest few; the list below has every one */
    return `<div class="card memsec" data-msec="${k}"><a class="memsec-h" href="#memsec-${k}"><b>${esc(l)}</b><span class="tiny faint">${esc(SECTOR_WORD[k] || "")}</span></a>
      <div class="memsec-n">${Object.entries(units).map(([u, n]) => `<span><b>${nf(n)}</b> ${esc(u)}</span>`).join("") || `<span><b>${nf(xs.length)}</b> collections</span>`}</div>
      <div class="tiny ${runs ? "" : "faint"}">${runs ? `drawn on by ${nf(runs)} run${runs === 1 ? "" : "s"} this week` : "no run drew on it this week"} · ${nf(xs.length)} collection${xs.length === 1 ? "" : "s"}</div>
      <div class="memsec-top">${top.map((c) => `<a class="tag" href="${SECTOR_HREF(c)}">${esc(c.title)}${c.size != null ? ` · ${nf(c.size)}` : ""}</a>`).join("")}</div></div>`;
  };
  return `<div class="memprobs" id="memprobs">${memProbsHtml()}</div><div class="memmap">${sectors.map(box).join("")}</div>`;
}
async function vMemory() {
  view.innerHTML = `${memFrame("memory")}<div class="skeleton" style="height:240px"></div>`;
  bindMemFrame();
  const d = await api("/api/memory/catalogue").catch((e) => ({ collections: [], error: e.message }));
  if (route.name !== "memory") return;
  const cs = d.collections || [], st = d.status || {};
  const sectors = (d.sectors || [["owner", "You"], ["world", "World"], ["code", "Code"], ["howto", "How-to"], ["agents", "Agents"], ["work", "Work"]]);
  const row = (c) => {
    const g = c.given_7d || {};
    const meta = [c.size != null && `${nf(c.size)} ${c.unit || ""}`.trim(), TRUST_WORD[c.trust] || c.trust, c.id === "owner:profile" ? "your assistant only" : ACCESS_WORD[c.access], g.runs ? `given to ${nf(g.runs)} run${g.runs === 1 ? "" : "s"} in 7 days, ${nf(g.chars)} characters` : "not given to a run in 7 days",
      c.changed && `changed ${rel(new Date(c.changed * 1000).toISOString())}`, c.archived && `${nf(c.archived)} archived`, c.error && `could not be measured: ${c.error}`].filter(Boolean);
    return `<a href="${SECTOR_HREF(c)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(c.title)}</div><div class="sub wrap">${esc(c.answers)}</div>
      <div class="tiny faint wrap" style="margin-top:3px">${meta.map(esc).join(" · ")}</div><div class="tiny faint mono wrap">${esc(c.id)}</div></div>${ic.next}</a>`;
  };
  view.innerHTML = `${memFrame("memory")}${d.error ? `<div class="banner" style="margin-bottom:12px">${ic.alert}<span class="small">${esc(d.error)}</span></div>` : ""}
    ${st.gate && !st.gate.open ? `<a class="banner warn" href="#/crew/memory" style="margin-bottom:12px">${ic.alert}<span class="grow small">The memory agent's changes wait: ${esc(st.gate.why)}</span>${ic.next}</a>` : ""}
    ${cs.length ? memMapHtml(cs, sectors) : ""}
    ${cs.length ? `<details class="card pad section memuse"><summary class="small"><b>How much runs get from memory</b> <span class="faint">per kind of step, the last 30 days</span></summary><div style="margin-top:10px">${memStatusHtml(st)}</div></details>` : ""}
    ${sectors.map(([k, l]) => { const xs = cs.filter((c) => c.sector === k && !c.parent); return xs.length ? `<div class="section-h memgroup" id="memsec-${k}"><h3>${esc(l)} · ${nf(xs.length)}</h3></div>
      <div class="card list skills">${xs.map((c) => row(c) + cs.filter((p) => p.parent === c.id).map((p) => row(p).replace("<a ", `<a class="mempart" `)).join("")).join("")}</div>` : ""; }).join("")
      || emptyState(`${ic.wiki}<div>The catalogue comes within the hour.</div>`, `<a class="btn sm" href="#/wiki">See the wikis</a>`)}`;
  bindMemFrame();
}

// How-to (MEM-38): each role's lessons, with their evidence and tally; the skills are their own list
async function vHowto() {
  view.innerHTML = `${memFrame("howto")}<div class="skeleton" style="height:240px"></div>`;
  bindMemFrame();
  const l = await api("/api/memory/lessons").catch(() => []);
  if (route.name !== "howto") return;
  const want = route.q.get("role");
  const list = want ? l.filter((x) => x.role === want) : l;
  view.innerHTML = `${memFrame("howto")}
    <div class="card list skills" style="margin-bottom:12px"><a href="#/skills"><div class="grow"><div class="ttl">Skills</div><div class="sub">How the assistant does a particular job: what came with Hermes, what it wrote, what the memory agent distilled</div></div>${ic.next}</a></div>
    ${want ? `<a class="back" href="#/howto">${ic.back}All roles</a>` : ""}
    ${list.map((r) => `<div class="section-h memgroup"><h3>Lessons for ${esc(r.role)} · ${nf(r.lessons.length)}</h3>${r.retired ? `<span class="tiny faint">${nf(r.retired)} retired</span>` : ""}</div>
      <div class="card memlist">${r.lessons.map((x) => `<div class="memfact"><div class="small wrap">${esc(x.text)}</div><div class="tiny faint wrap" style="margin-top:3px">tally ${esc(x.tally)} · since ${esc(x.since || "?")} · ${esc(x.id)} · evidence: ${esc(x.ev)}</div></div>`).join("")
        || `<div class="small muted" style="padding:12px 0">No lesson yet.</div>`}</div>`).join("")
      || emptyState(`${ic.doc}<div>No lesson yet: they come from agents' notes and from how their runs ended.</div>`, `<a class="btn sm" href="#/skills">See the skills</a>`)}`;
  bindMemFrame();
}

// Code: what it knows about each repository
function vCodeMem() {
  const repos = (S?.code?.repos || []).filter((r) => !isTrial(r.name));
  view.innerHTML = `${memFrame("codemem")}<div class="card list skills">${repos.map((r) => `<a href="#/wiki?root=${encodeURIComponent(`repos/${r.name}/wiki`)}"><div class="grow" style="min-width:0"><div class="ttl wrap skname">${esc(r.name)}</div>
      <div class="tiny faint wrap" style="margin-top:3px">${[r.codemap ? "code map" : "no code map", r.graph ? `graph of ${nf(r.graph.nodes)} nodes` : "no graph yet", r.files && `${nf(r.files)} files`, r.last && `changed ${rel(r.last.ts)}`].filter(Boolean).map(esc).join(" · ")}</div></div>${ic.next}</a>`).join("") || emptyState(`${ic.code}<div>No repository yet.</div>`, `<a class="btn sm" href="#/build?add=1">Add a repository</a>`)}</div>`;
  bindMemFrame();
}

// Journals: each agent's own notebook; its agent page keeps the reading of it
const journalHref = (id) => (id.startsWith("crew-") ? `#/crew/${encodeURIComponent(id.slice(5))}?tab=memory` : id.startsWith("mission-") ? `#/mission/${encodeURIComponent(id.slice(8))}?tab=memory` : `#/swarm/agent/${encodeURIComponent(id)}`);
async function vJournals() {
  view.innerHTML = `${memFrame("journals")}<div class="skeleton" style="height:240px"></div>`;
  bindMemFrame();
  const l = await api("/api/journals").catch(() => []);
  if (route.name !== "journals") return;
  view.innerHTML = `${memFrame("journals")}<div class="card list skills">${l.map((j) => `<a href="${journalHref(j.id)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(j.name)}</div><div class="sub wrap">${esc(j.last || "")}</div>
      <div class="tiny faint" style="margin-top:3px">${[j.entries != null && `${nf(j.entries)} entries`, fsize(j.bytes), j.at && `written ${rel(new Date(j.at * 1000).toISOString())}`].filter(Boolean).join(" · ")}</div></div>${ic.next}</a>`).join("") || emptyState(`${ic.doc}<div>No journal yet: an agent writes one after its first run.</div>`, `<a class="btn sm" href="#/missions">See the agents</a>`)}</div>`;
  bindMemFrame();
}

// Filed sources: what the vault's wiki is compiled from, as it came
async function vSources() {
  view.innerHTML = `<a class="back" href="#/wiki">${ic.back}Wikis</a><div class="hero heading" style="margin-bottom:10px"><h1>Filed sources</h1></div><div class="skeleton" style="height:240px"></div>`;
  const l = await api("/api/sources").catch(() => []);
  if (route.name !== "sources") return;
  view.innerHTML = `<a class="back" href="#/wiki">${ic.back}Wikis</a><div class="hero heading" style="margin-bottom:10px"><h1>Filed sources · ${nf(l.length)}</h1></div>
    <div class="card list skills">${l.map((x) => `<a href="#/read?path=${encodeURIComponent(x.path)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(x.title)}</div><div class="tiny faint" style="margin-top:3px">${esc(x.kind)} · ${esc(x.date)}</div></div>${ic.next}</a>`).join("") || emptyState(`${ic.doc}<div>Nothing filed yet.</div>`, `<a class="btn sm" href="#/wiki">Add to the vault</a>`)}</div>`;
}

// One search over all of it, grouped by where each result lives
async function vMemSearch() {
  const q = route.q.get("q") || "";
  view.innerHTML = `${memFrame("")}<div class="skeleton" style="height:240px"></div>`;
  bindMemFrame();
  const [r, pages, skills, journals] = await Promise.all([act({ action: "memory_search", q }, null), api(`/api/wiki/search_all?q=${encodeURIComponent(q)}`).catch(() => []), api("/api/skills").catch(() => ({ skills: [] })), api(`/api/journals?q=${encodeURIComponent(q)}`).catch(() => [])]);
  if (route.name !== "memsearch" || route.q.get("q") !== q) return;
  const facts = r?.facts || [], low = q.toLowerCase(), sk = (skills.skills || []).filter((x) => !x.archived && `${x.name} ${x.description}`.toLowerCase().includes(low));
  const head = (t, n) => `<div class="section-h memgroup"><h3>${t} · ${nf(n)}</h3></div>`;
  view.innerHTML = `${memFrame("")}
    ${pages.length ? `${head("Wikis", pages.length)}<div class="card list skills">${pages.map((p) => `<a href="#/wiki?root=${encodeURIComponent(p.root)}&page=${encodeURIComponent(p.id)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(p.title)}</div><div class="sub wrap">${esc(p.wiki)}</div></div>${ic.next}</a>`).join("")}</div>` : ""}
    ${facts.length ? `${head("Long-term", facts.length)}<div class="card memlist">${facts.map((f) => factRow(f, false)).join("")}</div>` : ""}
    ${sk.length ? `${head("Skills", sk.length)}<div class="card list skills">${sk.map((x) => `<a href="#/skills?s=${encodeURIComponent(x.path)}"><div class="grow" style="min-width:0"><div class="ttl wrap skname">${esc(x.name)}</div><div class="sub wrap">${esc(x.description)}</div></div>${ic.next}</a>`).join("")}</div>` : ""}
    ${journals.length ? `${head("Journals", journals.length)}<div class="card list skills">${journals.map((j) => `<a href="${journalHref(j.id)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(j.name)}</div><div class="sub wrap">${esc(j.hit || "")}</div></div>${ic.next}</a>`).join("")}</div>` : ""}
    ${!pages.length && !facts.length && !sk.length && !journals.length ? emptyState(`${ic.search}<div>Nothing found for “${esc(q)}”.</div>`, `<a class="btn sm" href="#/wiki">See the wikis</a>`) : ""}`;
  bindMemFrame();
}

// Add to the vault, with the wikis it feeds
function addVaultHtml() {
  return `<div class="card pad-l" id="addk" hidden style="margin-bottom:12px">
    <div class="seg sm">${[["text", "Note"], ["url", "Web page"], ["file", "File"]].map(([k, l], i) => `<button type="button" data-k="${k}" class="${i ? "" : "on"}">${l}</button>`).join("")}</div>
    <input class="input" id="k_title" placeholder="Title (optional)" style="margin-top:10px">
    <textarea class="input" id="k_text" rows="4" placeholder="Paste or write a note…" style="margin-top:8px"></textarea>
    <input class="input" id="k_url" placeholder="https://…" style="margin-top:8px" hidden>
    <input class="input" id="k_file" type="file" accept=".pdf,.docx,.md,.txt,.html,.pptx,.xlsx,.csv" style="margin-top:8px" hidden>
    <button class="btn primary" id="k_go" style="margin-top:10px">${ic.plus}Add</button></div>`;
}

// ---------- Skills (APP-48): what the assistant can look up, each readable ----------
let skillQ = "", skillF = "all", skillList = null;
const SKILL_F = [["all", "All"], ["here", "Made here"], ["used", "Used"], ["archived", "Archived"]];
const skillNeeds = (x) => { const p = x.platforms || []; return p.length && !p.includes("linux") ? `Needs ${p.map((n) => ({ macos: "a Mac", windows: "Windows" })[n] || n).join(" or ")}` : ""; };
async function vSkills() {
  const want = route.q.get("s");
  if (want) return vSkillOne(want);
  view.innerHTML = `${memFrame("howto")}<div class="skeleton" style="height:240px"></div>`;
  bindMemFrame();
  const d = await api("/api/skills").catch((e) => ({ skills: [], error: e.message }));
  if (route.name !== "skills" || route.q.get("s")) return;
  skillList = d.skills || [];
  const live = skillList.filter((x) => !x.archived), used = live.filter((x) => x.opened_30d).length, here = live.filter((x) => !x.bundled).length;
  view.innerHTML = `${memFrame("howto")}<div class="tiny faint" style="margin-bottom:10px">${nf(live.length)} your assistant can look up · ${nf(here)} made here · ${nf(used)} used in the last 30 days</div>
    ${d.error ? `<div class="banner" style="margin-bottom:12px">${ic.alert}<span class="small">${esc(d.error)}</span></div>` : ""}
    <div class="wsearch" style="margin-bottom:10px">${ic.search}<input class="input" id="skq" placeholder="Find a skill: mail, video, research…" value="${esc(skillQ)}"></div>
    <div class="agf" style="margin-bottom:12px">${SKILL_F.map(([k, l]) => `<button class="fchip ${skillF === k ? "on" : ""}" data-skf="${k}">${l}</button>`).join("")}</div>
    <div id="sklist"></div>`;
  const draw = () => {
    const q = skillQ.toLowerCase();
    const l = skillList.filter((x) => (skillF === "archived" ? x.archived : !x.archived) && (skillF !== "here" || !x.bundled) && (skillF !== "used" || x.opened_30d)
      && (!q || `${x.name} ${x.description} ${x.category}`.toLowerCase().includes(q)));
    const usedIn = (c) => l.filter((x) => x.category === c).reduce((n, x) => n + (x.opened_30d || 0), 0);
    const cats = [...new Set(l.map((x) => x.category))].sort((a, b) => usedIn(b) - usedIn(a) || a.localeCompare(b));   // what is used first
    l.sort((a, b) => (b.opened_30d || 0) - (a.opened_30d || 0) || a.name.localeCompare(b.name));
    $("#sklist").innerHTML = cats.map((c) => `<div class="section-h memgroup"><h3>${esc(c.replace(/-/g, " "))}</h3><span class="num tiny faint">${l.filter((x) => x.category === c).length}</span></div>
      <div class="card list skills">${l.filter((x) => x.category === c).map((x) => `<a href="#/skills?s=${encodeURIComponent(x.path)}"><div class="grow" style="min-width:0"><div class="ttl wrap skname">${esc(x.name)}</div>
        <div class="sub wrap">${esc(x.description)}</div>
        <div class="tiny faint wrap" style="margin-top:3px">${[x.bundled ? "Came with Hermes" : "Made here", x.opened_30d ? `opened ${nf(x.opened_30d)} time${x.opened_30d === 1 ? "" : "s"} in 30 days` : "", skillNeeds(x)].filter(Boolean).map(esc).join(" · ")}</div></div>${ic.next}</a>`).join("")}</div>`).join("")
      || emptyState(`${ic.search}<div>No skill matches this.</div>`, `<button type="button" class="btn sm" id="skclear">Show all skills</button>`);
    if ($("#skclear")) $("#skclear").onclick = () => { skillQ = ""; skillF = "all"; $("#skq").value = ""; $$("[data-skf]").forEach((x) => x.classList.toggle("on", x.dataset.skf === "all")); draw(); };
  };
  bindMemFrame();
  draw();
  $("#skq").oninput = (e) => { skillQ = e.target.value; draw(); };
  $$("[data-skf]").forEach((b) => (b.onclick = () => { skillF = b.dataset.skf; $$("[data-skf]").forEach((x) => x.classList.toggle("on", x === b)); draw(); }));
}
async function vSkillOne(path) {
  const back = `<a class="back" href="#/skills">${ic.back}Skills</a>`;
  view.innerHTML = `${back}<div class="skeleton" style="height:240px"></div>`;
  const x = await api(`/api/skills/one?path=${encodeURIComponent(path)}`).catch(() => null);
  if (route.name !== "skills") return;
  if (!x || x.error) { view.innerHTML = `${back}<div class="card pad small muted">This skill is not there any more.</div>`; return; }
  view.innerHTML = `${back}<div class="hero heading" style="margin-bottom:10px"><h1 class="skname">${esc(x.name)}</h1><p>${esc(x.description)}</p></div>
    <div class="tiny faint wrap" style="margin-bottom:12px">${[x.category.replace(/-/g, " "), x.bundled ? "Came with Hermes" : "Made here", x.version && `version ${x.version}`, x.author, x.opened_30d ? `opened ${nf(x.opened_30d)} time${x.opened_30d === 1 ? "" : "s"} in 30 days` : "not opened in the last 30 days", skillNeeds(x), x.archived && "Archived"].filter(Boolean).map(esc).join(" · ")}</div>
    <div class="card pad-l md">${md(x.body)}</div>
    ${(x.files || []).length ? `<div class="section-h section"><h2>Files with it · ${x.files.length}</h2></div><div class="card pad"><div class="tiny wrap" style="font-family:var(--mono);line-height:1.8">${x.files.map(esc).join("<br>")}</div></div>` : ""}`;
}

// ---------- Claude tasks (ops/claude_tasks.py): Hermes' questions to Claude Code, with Claude's steps and thinking ----------
const CT_STATUS = { queued: ["queued", "Queued"], running: ["running", "Working"], done: ["ok", "Answered"], failed: ["failed", "Failed"], waiting: ["paused", "Waits for Claude's limit"] };
function ctRow(t) {
  const [cls, label] = CT_STATUS[t.status] || ["queued", t.status];
  return `<details class="ctask" data-ct="${t.id}" style="display:block;padding:10px 12px"><summary style="list-style:none;cursor:pointer">
    <div class="row between" style="gap:8px"><b class="small wrap">#${t.id} ${esc(ctTitle(t))}</b><span class="tiny faint" style="white-space:nowrap">${rel(t.ended || t.started || t.created)}</span></div>
    <div class="row wrap tiny muted" style="gap:6px;margin-top:3px"><span class="pill ${cls}" style="padding:1px 7px">${label}</span>${esc(t.mode)}${t.repo ? " · " + esc(t.repo) : ""}${t.turns ? ` · ${t.turns} steps` : ""}${t.tokens ? ` · ${tok(t.tokens)} tokens${t.cached ? ` (${Math.round(100 * t.cached / t.tokens)} % cached)` : ""}` : ""}</div></summary>
    ${ctTitle(t) !== t.question ? `<details style="margin-top:10px"><summary class="small muted">The whole question${/^crew:/.test(t.source || "") ? ` the ${esc(ctAsker(t))} asked` : ""}</summary><div class="small wrap" style="white-space:pre-wrap;margin-top:6px">${esc(t.question)}</div></details>` : ""}
    <div class="ctbody" id="ct-${t.id}" style="margin-top:10px"><div class="skeleton" style="height:40px"></div></div></details>`;
}
// an answer in JSON (the Health doctor's diagnoses) is shown as findings, any other as Markdown; nothing is left out
function ctAnswer(a) {
  let j;
  try { j = JSON.parse(a.trim().replace(/^```(?:json)?\s*|\s*```$/g, "")); } catch { return `<div class="md small">${md(a)}</div>`; }
  const { diagnoses, ...rest } = j && typeof j === "object" ? j : { diagnoses: null };
  const more = Object.keys(rest).length ? `<pre class="small" style="white-space:pre-wrap;margin-top:8px">${esc(JSON.stringify(rest, null, 2))}</pre>` : "";
  if (!Array.isArray(diagnoses)) return `<pre class="small" style="white-space:pre-wrap">${esc(JSON.stringify(j, null, 2))}</pre>`;
  return diagnoses.map((x) => {
    const { issue, class: kind, cause, fix, evidence, confidence, ...other } = x || {};
    return `<div class="card pad ctdiag"><div class="row wrap" style="gap:6px"><b class="small">Issue ${esc(issue ?? "")}</b>${kind ? `<span class="tag">${esc(kind)}</span>` : ""}${confidence ? `<span class="tag">${esc(confidence)} confidence</span>` : ""}</div>
      ${cause ? `<p class="small wrap" style="margin:6px 0 0">${esc(cause)}</p>` : ""}${fix ? `<p class="small wrap" style="margin:6px 0 0"><b>Fix:</b> ${esc(fix)}</p>` : ""}
      ${(evidence || []).length ? `<details style="margin-top:6px"><summary class="tiny muted">Evidence · ${evidence.length}</summary><ul class="small" style="margin:6px 0 0;padding-left:18px">${evidence.map((e) => `<li class="wrap">${esc(e)}</li>`).join("")}</ul></details>` : ""}
      ${Object.keys(other).length ? `<pre class="tiny" style="white-space:pre-wrap;margin-top:6px">${esc(JSON.stringify(other, null, 2))}</pre>` : ""}</div>`;
  }).join("") + more;
}
document.addEventListener("toggle", async (e) => {                   // load a task when it is opened (toggle doesn't bubble)
  const d = e.target;
  if (!d.matches?.("details.ctask") || !d.open) return;
  const T = await api(`/api/claude/${d.dataset.ct}`).catch(() => null), el = $(`#ct-${d.dataset.ct}`);
  if (!el) return;
  if (!T || T.error) { el.innerHTML = `<div class="small muted">Not available.</div>`; return; }
  tlLevel = tlLevel || pref("mc-tl", "steps");
  el.innerHTML = `<div class="row" style="margin-bottom:8px">${liveLink("claude-task:" + d.dataset.ct)}</div>${T.answer ? ctAnswer(T.answer) : T.error ? `<div class="banner" style="padding:8px 12px">${ic.alert}<span class="small">${esc(T.error)}</span></div>` : ""}
    ${obsBlocks(T.files, T.detail)}
    <details style="margin-top:10px"><summary class="small muted">What Claude did · ${T.steps.length} steps${T.steps.some((s) => s.kind === "think") ? " · with its thinking" : ""}</summary>
      <div style="margin-top:6px">${T.steps.length ? logHtml(T.steps, { level: "all" }) : `<div class="small muted">No steps yet.</div>`}</div></details>`;
}, true);

const reviewOpen = (r) => !!r && !!(r.pending || r.missing?.length || (r.error && !r.verdict));   // QA-26: as ops/builds.py review_open
function readyAll(list) {
  return list.filter((b) => b.checks_ok && (!["ai-stack", "TestRepo"].includes(b.repo) || b.ci === "success") && b.ai_review?.verdict !== "block" && !reviewOpen(b.ai_review)).length;
}

function buildRow(b) {
  const cls = bcls(b.status);
  return `<a href="#/build/${b.id}"><div class="ic ${cls === "ok" ? "ok" : cls === "failed" ? "err" : cls === "running" ? "run" : ""}">${b.status === "review" ? ic.search : ["deployed", "merged"].includes(b.status) ? ic.check : ["failed", "rolled_back"].includes(b.status) ? ic.alert : ic.rocket}</div>
    <div class="grow"><div class="ttl wrap">#${b.id} ${esc(b.title)}</div><div class="sub">${esc(b.repo)}${b.engine === "claude" ? " · Claude Code" : ""} · <span class="pill ${cls}" style="padding:1px 7px">${BSTATUS[b.status] || b.status}</span>${b.ci && b.status === "review" ? ` · CI ${esc(b.ci)}` : ""}${b.status === "review" && b.ai_review?.verdict ? ` · ${VERDICT[b.ai_review.verdict]?.[1] || ""}` : ""}${b.tokens ? ` · ${tok(b.tokens)} tokens` : ""}</div></div>
    <div class="tiny faint">${rel(b.updated)}</div></a>`;
}

function bindAddRepo() {
  $$("[data-ark]").forEach((b) => (b.onclick = () => $$("[data-ark]").forEach((x) => x.classList.toggle("on", x === b))));
  $$("[data-ar]").forEach((b) => (b.onclick = () => {
    $$("[data-ar]").forEach((x) => x.classList.toggle("on", x === b));
    $("#ar-study").hidden = b.dataset.ar !== "study"; $("#ar-new").hidden = b.dataset.ar !== "new";
  }));
  $("#ar-go").onclick = async () => {
    const v = $("#ar-url").value.trim();
    const kind = $("[data-ark].on")?.dataset.ark || "own";
    if (v && (await act({ action: "understand", repo: v, kind }, "Onboarding started: it shows in your repositories, step by step"))) $("#ar-url").value = "";
  };
  $("#ar-create").onclick = async () => {
    const name = $("#ar-name").value.trim().toLowerCase();
    if (!name) return toast("Give it a name", true);
    $("#ar-create").disabled = true;
    const r = await act({ action: "repo_create", name, description: $("#ar-desc").value.trim() }, `Created ${name}: it shows in your repositories`);
    $("#ar-create").disabled = false;
    if (r?.repo) location.hash = `#/repo/${encodeURIComponent(r.repo)}`;
  };
}

// the code map viewer: on the tailnet through its gate (8446); off it (a work PC with no tailnet) the viewer's own local port
const viewerUrl = () => (location.hostname.endsWith(".ts.net") || DEPLOY.PC_TAILNET_HOST ? `${HOSTURL}:8446/` : `http://${location.hostname}:5173/`);
// BLD-26, DEC-48: onboarding a repository, the whole package. The checklist shows every step with its record: when it last ran,
// how long, which model, calls and tokens, and its quality in words; a weak step is said to be weak. Each step can run again.
const ONB_LIVE = ["queued", "running", "waiting"];
const ONB_WORD = { done: "done", weak: "weak", failed: "failed", running: "running", waiting: "waiting", pending: "not yet", queued: "queued" };
function onbStep(s, live) {
  const llm = s.model && s.model !== "no model (a program)";             // a deterministic step says nothing about models (the owner, 9 Nov)
  const meta = [s.ended ? `ran ${rel(s.ended)}` : "", s.seconds ? dur(s.seconds) : "", llm ? s.model : "", llm && s.calls != null ? `${nf(s.calls)} call${s.calls === 1 ? "" : "s"}` : "",
    s.tokens ? `${tok(s.tokens)} tokens` : s.model && s.model !== "no model (a program)" && s.ended ? "tokens not recorded" : ""].filter(Boolean).join(" · ");
  const age = s.sha ? `made at ${esc(s.sha.slice(0, 7))}${s.behind ? ` · <b>${nf(s.behind)} commit${s.behind === 1 ? "" : "s"} behind</b>` : s.behind === 0 ? " · the latest code" : ""}` : "";
  const mark = s.state === "done" ? ic.check : s.state === "weak" || s.state === "failed" ? ic.alert : s.state === "pending" ? "" : `<span class="dot run"></span>`;
  return `<li class="${esc(s.state)}"><span class="onb-mark">${mark}</span><div class="grow" style="min-width:0"><div class="row between wrap" style="gap:6px"><span class="${s.state === "pending" ? "muted" : ""}">${esc(s.title)}</span>
      <span class="row" style="gap:6px"><span class="tiny ${s.state === "weak" || s.state === "failed" ? "warn-t" : "faint"}">${esc(ONB_WORD[s.state] || s.state)}</span>${live || s.state === "pending" ? "" : `<button class="linkbtn tiny" data-onbstep="${esc(s.id)}">Run again</button>`}</span></div>
      ${s.quality ? `<div class="tiny ${s.ok === false ? "warn-t" : "muted"} wrap onb-q">${esc(s.quality)}</div>` : ""}${meta ? `<div class="tiny faint wrap">${esc(meta)}</div>` : ""}
      ${age ? `<div class="tiny wrap ${s.behind ? "warn-t" : "faint"}">${age}</div>` : ""}
      ${s.note ? `<div class="tiny muted wrap onb-note">${esc(s.note)}</div>` : ""}</div></li>`;
}
let onbSeen = "";
function onboardLabel(r) {
  const o = r.onboard;
  if (o && ONB_LIVE.includes(o.status)) return `onboarding, step ${o.index} of ${o.total}`;
  if (o?.status === "failed") return "onboarding stopped";
  return r.codemap ? "code map" : "no code map";
}
function onboardHtml(r) {
  const o = r.onboard;
  if (!o) return "";
  const live = ONB_LIVE.includes(o.status), failed = o.status === "failed", cur = o.steps.find((s) => s.id === o.step), weak = o.steps.filter((s) => s.state === "weak").length;
  const late = o.behind ? ` · <b>${nf(o.behind)} commit${o.behind === 1 ? "" : "s"} behind the code</b>` : "";
  const head = live ? `Step ${o.index} of ${o.total}: ${esc(cur?.title || "starting")}`
    : failed ? `Stopped at ${esc(cur?.title || "a step")}` : o.status === "done" ? `All ${o.total} steps done${late}` : weak ? `${weak} weak step${weak === 1 ? "" : "s"}: its result is too thin to work from${late}` : `${o.total - o.index} of ${o.total} steps still to do${late}`;
  return `<div class="card pad-l section onb"><div class="row between wrap" style="gap:8px"><h2>Onboarding</h2><span class="row" style="gap:8px">${live ? "" : `<button class="btn sm ${o.behind ? "primary" : "ghost"}" id="ronbup" title="Copy, graph, facts, code map, explanations and search from the latest code; the map keeps what did not change">${ic.repeat}Update${o.behind ? ` · ${nf(o.behind)} new commit${o.behind === 1 ? "" : "s"}` : ""}</button>`}${explain("onboarding-gives-every-repository", `Onboarding gives every repository the whole package: a copy of the code, its code graph, a code map with every file explained, a place in the search, a written analysis and its wiki. Every step is checked for quality, not just for being there: a hollow result is weak, never done. Each step says when it ran, how long it took, which model it used, its calls and tokens, and the commit it was made at with how many commits the code has moved on since. <b>Update</b> brings the steps that follow the code to the latest commit (the map explains only what changed); the written analysis and the wiki keep their age shown and have their own <b>Run again</b>. The analysis is a guide to the code for your own repositories, and a review for an outside project.`, "About this")}</span></div>
    <div class="small ${failed || weak || o.behind ? "warn-t" : "muted"} wrap">${head}</div>
    ${(failed || o.status === "queued") && o.why ? `<div class="small wrap" style="margin-top:6px">${esc(o.why)}</div>` : ""}
    <ol class="onb-steps">${o.steps.map((s) => onbStep(s, live)).join("")}</ol>
    ${live || o.status === "done" ? "" : `<button class="btn primary" id="ronb" style="margin-top:12px">${ic.repeat}${failed ? "Try again" : weak ? "Do the weak steps again" : "Finish onboarding"}</button>`}</div>`;
}
function bindOnboard(name) {
  const go = async (b, step) => { b.disabled = true; const ok = await act({ action: "understand", repo: name, ...(step ? { step } : {}) }, step ? "Started from that step: the checklist shows it" : "Onboarding started: the steps show under Overview"); if (!ok) b.disabled = false; };
  [$("#ronb"), $("#rstudy"), ...$$("[data-rstudy]")].forEach((b) => { if (b) b.onclick = () => go(b); });
  $$("[data-onbstep]").forEach((b) => (b.onclick = () => go(b, b.dataset.onbstep)));
  const up = $("#ronbup");
  if (up) up.onclick = async () => { up.disabled = true; if (!(await act({ action: "understand", repo: name, update: true }, "Updating to the latest code: the checklist shows each step"))) up.disabled = false; };
}
function repoLive() {                                          // a state update: only the card changes; the end of a job redraws the page
  const name = route.args[0], r = name && repoOf(name), el = $("#ronboard");
  if (!r || !el) return;
  const sig = JSON.stringify(r.onboard || {});
  if (sig === onbSeen) return;
  const was = (() => { try { return JSON.parse(onbSeen).status; } catch (_) { return ""; } })();
  onbSeen = sig;
  if (ONB_LIVE.includes(was) && !ONB_LIVE.includes(r.onboard?.status)) return repoRedraw();
  el.innerHTML = onboardHtml(r);
  const b = $("#rstudy"); if (b) b.hidden = r.onboard?.status !== "done";
  bindOnboard(name);
}

// ---------- the repo page's tabs that only draw what they are given (APP-51; tests/test_repo_tabs.py runs these) ----------
const repoHref = (name, tab) => `#/repo/${encodeURIComponent(name)}?tab=${tab}`;
// what to do when a tab has nothing yet: the page's Re-analyse, or while onboarding runs, where its steps show
const repoNext = (name, r) => (ONB_LIVE.includes(r?.onboard?.status) ? `<a class="btn" href="${repoHref(name, "overview")}">${ic.repeat}See the onboarding</a>` : `<button class="btn primary" data-rstudy>${ic.repeat}Re-analyse</button>`);
const rfN = (n, one, many = `${one}s`) => `${nf(n)} ${n === 1 ? one : many}`;
const rfTimes = (n) => (n === 1 ? "once" : `${nf(n)} times`);
const rfRead = (c) => (c == null ? "" : c >= 50 ? "very hard to read" : c >= 25 ? "hard to read" : c >= 15 ? "takes effort to read" : "easy to read");
// how widely the changes to a file are spread: 0 is one person, near 1 is many (1 / (1 - value) people with an equal share)
const rfSpread = (f) => (f == null ? "" : f < 0.2 ? "one" : f < 0.5 ? "by two or three people" : f < 0.8 ? "by a few people" : "by many people");
const rfAge = (days) => (days == null ? "" : days < 1 ? "today" : days < 2 ? "yesterday" : days < 60 ? `${nf(days)} days ago` : days < 730 ? `${nf(Math.round(days / 30.44))} months ago` : `${nf(Math.round(days / 365.25))} years ago`);
const rfPath = (name, p) => `<a class="rfpath wrap" href="#/chat?prompt=${encodeURIComponent(`In the repository ${name}, about ${p}: `)}">${esc(p)}</a>`;
const rfRow = (body, why, tag = "") => `<div><div class="grow" style="min-width:0">${body}${why ? `<div class="sub wrap">${why}</div>` : ""}</div>${tag ? `<span class="tag">${esc(tag)}</span>` : ""}</div>`;
// the most telling rows first; the rest are in the page, one tap away (.rflist: nothing is cut)
const RF_FIRST = 8;
const rfList = (rows, none) => (rows.length ? `<div class="card list rflist">${rows.join("")}</div>${rows.length > RF_FIRST ? `<button type="button" class="btn sm rfmore" data-rfall>Show all ${nf(rows.length)}</button>` : ""}` : `<div class="card pad small muted">${none}</div>`);
const rfSection = (key, title, how, body) => `<div class="section rfsec"><div class="section-h"><h2>${title}</h2></div>${explain(key, how, "What this means")}${body}</div>`;
const hasFacts = (d) => !!d && typeof d === "object" && !d.error && ["at", "commit", "hotspots", "health", "errors"].some((k) => d[k] !== undefined);
const rfErrors = (d, part) => (d?.errors || []).map((e) => (typeof e === "string" ? e : [e.tool || e.step || e.name, e.error || e.message || e.reason].filter(Boolean).join(": ") || JSON.stringify(e)))
  .filter((e) => { const h = /codelore|hotspot|coupling|ownership|code.?age|git|clone/i.test(e), w = /repowise|assess|health/i.test(e); return part === "history" ? h || !w : w || !h; });
const rfFailed = (name, r, errs) => (errs.length ? `<div class="card pad-l rffail"><b class="err-t">What failed</b><ul class="small wrap">${errs.map((e) => `<li>${esc(e)}</li>`).join("")}</ul><div class="empty-a">${repoNext(name, r)}</div></div>` : "");
const rfFrom = (d) => { const b = [d.commits != null ? `From ${rfN(d.commits, "commit")}` : "", d.commit ? `at ${esc(String(d.commit).slice(0, 7))}` : "", d.at ? rel(d.at) : ""].filter(Boolean).join(" · "); return b ? `<div class="tiny faint wrap">${b}</div>` : ""; };

function repoHistoryHtml(name, r, d) {
  if (!hasFacts(d)) return emptyState("This repository has not got its history facts yet.", repoNext(name, r), "card");
  const errs = rfErrors(d, "history"), hot = d.hotspots || [], pairs = d.coupling || [], own = d.ownership || [], age = d.code_age || [];
  if (!errs.length && d.commits != null && d.commits <= 1 && !hot.length && !pairs.length && !own.length && !age.length) return emptyState("This copy of the repository holds one commit, so it has no history to read.", repoNext(name, r), "card");
  const rows = {
    hot: [...hot].sort((a, b) => (b.hotspot_score || 0) - (a.hotspot_score || 0)).map((h) => rfRow(rfPath(name, h.path), [`changed ${rfTimes(h.revisions)}`, rfRead(h.cognitive)].filter(Boolean).join(", "))),
    pairs: [...pairs].sort((a, b) => (b.shared || 0) * (b.degree || 0) - (a.shared || 0) * (a.degree || 0)).map((c) => rfRow(`${rfPath(name, c.a ?? c.entity_a)}${rfPath(name, c.b ?? c.entity_b)}`, `changed together ${rfTimes(c.shared)}${c.degree != null ? `, ${nf(Math.round(c.degree))} % of their changes` : ""}`)),
    own: [...own].sort((a, b) => (b.total_revs || 0) * (1 - (b.fractal_value || 0)) - (a.total_revs || 0) * (1 - (a.fractal_value || 0))).map((o) => {
      const s = rfSpread(o.fractal_value), who = esc(o.main_author || "");
      return rfRow(rfPath(name, o.path), s === "one" ? `changed ${rfTimes(o.total_revs)}, almost all by ${who}` : `changed ${rfTimes(o.total_revs)}${s ? ` ${s}` : ""}, most often ${who}`);
    }),
    age: [...age].sort((a, b) => (b.age_days || 0) - (a.age_days || 0)).map((f) => rfRow(rfPath(name, f.path), `last changed ${rfAge(f.age_days)}${f.last_modified ? `, ${day(f.last_modified)}` : ""}`)),
  };
  const part = (key, title, how, list, none) => (!list.length && errs.length ? "" : rfSection(key, title, how, rfList(list, none)));   // beside a failure, an empty part is not a finding
  return `${rfFailed(name, r, errs)}${rfFrom(d)}
    ${part("rf-hot", "Changed often, hard to read", "A file that changes often and is hard to read is where a change most often goes wrong. Hard to read means its logic branches and nests a lot. The riskiest mix of the two comes first.", rows.hot, "No file stands out.")}
    ${part("rf-pairs", "What changes together", "Two files that keep changing in the same commit probably depend on each other, even when the code does not show it. Changing one, look at the other. The pairs changed together most come first.", rows.pairs, "No two files change together often enough to show.")}
    ${part("rf-own", "Who knows it", "Who made the most changes to a file, and how many people share them. Busy files that few people know come first.", rows.own, "No file has a main author yet.")}
    ${part("rf-age", "How old it is", "How long since each file last changed. An old file is settled or forgotten. The oldest come first.", rows.age, "No file's age is known yet.")}`;
}

// repowise's assessment in plain words: each check becomes rows [what it found, why], from its figures; a check this does not know says its own reason
const rfEach = (c, fn) => Object.entries(c.data?.components || {}).map(([n, v]) => fn(esc(n), v));
const DEAD_KIND = { unreachable_file: ["file nothing refers to", "files nothing refers to"], unused_export: ["export nothing uses", "exports nothing uses"], unused_package: ["package nothing imports", "packages nothing imports"] };
const HEALTH_SAY = {
  "component-map": (c) => { const x = c.data; return x && [[`${rfN((x.declared || 0) + (x.derived || 0), "part")} found`, [x.declared ? `${nf(x.declared)} declared by the repository` : "", x.derived ? `${nf(x.derived)} worked out from its folders` : "", x.unassigned_files ? `${rfN(x.unassigned_files, "file")} in none of them` : ""].filter(Boolean).join("; ")]]; },
  components: (c) => c.data?.components && rfEach(c, (n, v) => {
    const h = v.health || {}, o = v.ownership || {}, recent = o.recent;
    return [`${n}: health ${h.average != null ? `${nf(h.average, 1)} of 10` : "not known"}`, [rfN(v.file_count || 0, "file"), h.worst_path ? `weakest ${esc(h.worst_path)} at ${nf(h.worst_score, 1)} of 10` : "", recent ? `${rfN(recent.commits || 0, "commit")} by ${rfN(recent.contributors || 0, "person", "people")} in the ${nf(recent.window_days)} days to ${day(recent.as_of)}` : "", o.files_with_declared_owner ? `${nf(o.files_with_declared_owner)} with a declared owner` : "no declared owner"].filter(Boolean).join("; "), h.average];
  }).sort((a, b) => (a[2] ?? 11) - (b[2] ?? 11)),
  "dead-code": (c) => c.data?.by_kind && [[Object.entries(c.data.by_kind).map(([k, n]) => { const w = DEAD_KIND[k]; return w ? rfN(n, w[0], w[1]) : `${nf(n)} ${esc(k.replace(/_/g, " "))}`; }).join(", ") || "Nothing found", c.data.lines ? `${nf(c.data.lines)} lines where counted` : ""]],
  "dead-code:high": (c) => c.data && (c.data.count ? [[`${nf(c.data.count)} clear to remove, after a look`, "No references found in the code. Look first at whole files and files loaded at run time."]] : []),
  "dead-code:medium": (c) => c.data && (c.data.count ? [[`${nf(c.data.count)} probably unused`, "Something may use them indirectly. Look before deleting."]] : []),
  "dead-code:low": (c) => c.data && (c.data.count ? [[`${nf(c.data.count)} possibly used`, "Perhaps through dynamic imports or reflection. Look into it first."]] : []),
  "bus-factor": (c) => c.data?.components && rfEach(c, (n, v) => [`${n}: ${v.value === 1 ? "one person holds" : `${nf(v.value)} people hold`} over half of its files`, `${nf(v.owned_files)} of ${rfN(v.file_count || 0, "file")} have an owner; ${v.single_owner_files ? `${rfN(v.single_owner_files, "file")} with a single owner` : "none with a single owner"}`, v.value]).sort((a, b) => a[2] - b[2]),
  "test-reach": (c) => { const x = c.data; return x?.production_files != null && [[`${nf(x.reached_files)} of ${rfN(x.production_files, "file")} reached by a test`, `${nf(Math.round((x.share || 0) * 100))} %, worked out from imports and calls, not from running them`]]; },
  "line-coverage": (c) => (c.score == null || c.score < 0) && [["Lines the tests really run: not measured", "This repository has no coverage report."]],
  "test-reach:components": (c) => c.data?.components && rfEach(c, (n, v) => [`${n}: ${nf(v.reached_files)} of ${rfN(v.production_files || 0, "file")} reached`, "", v.share]).sort((a, b) => (a[2] ?? 2) - (b[2] ?? 2)),
};
const rfPlain = (s) => String(s || "").replace(/(\d[\d,]*) ([a-z-]+)\(s\)/gi, (_, n, w) => `${n} ${w}${n === "1" ? "" : "s"}`).replace(/;?\s*`[^`]*`[^;]*/g, "").replace(/_/g, " ");
const BASIS = { measured: "measured", inferred: "inferred", declared: "as declared", unresolved: "not known" };
function healthRows(c) {
  const known = HEALTH_SAY[c.name] && HEALTH_SAY[c.name](c);
  const rows = known || [[esc(rfPlain(c.reason)) + (c.score != null && c.score >= 0 ? ` (${nf(c.score, 1)} of 10)` : ""), (c.details || []).map((x) => esc(rfPlain(x))).join("; ")]];
  return rows.map(([lead, why]) => rfRow(`<div class="ttl wrap">${lead}</div>`, why, BASIS[c.basis] || ""));
}
// what the tab asks of the assessment, in this order; the rest of it is other tabs' business (hotspots: History) or needs a workspace the stack does not have
const HEALTH_SECTIONS = {
  components: ["Parts of the code", "A part is a service or a top-level folder treated as one piece. Its health is a score from 1 to 10 for how easy its files are to change, weighted by their size."],
  "dead-code": ["Dead code", "Found by following references through the code, so code that is loaded at run time can look unused."],
  "bus-factor": ["Who it depends on", "The fewest people who together are the main owners of over half of the files. Counted, never named."],
  "test-reach": ["What the tests reach", "A file counts as reached when a test imports it, is named for it, or reaches it through calls. That is not the same as the lines a test really runs."],
};
const HEALTH_NOT_SHOWN = new Set(["inventory", "hotspots", "contracts", "decisions", "provenance", "trend"]);
function repoHealthHtml(name, r, d) {
  if (!hasFacts(d)) return emptyState("This repository has not got its health findings yet.", repoNext(name, r), "card");
  const errs = rfErrors(d, "health"), sections = d.health?.sections || [];
  if (!sections.length && !errs.length) return emptyState("This repository has not got its health findings yet.", repoNext(name, r), "card");
  const byId = Object.fromEntries(sections.map((s) => [s.id, s]));
  const known = Object.entries(HEALTH_SECTIONS).filter(([id]) => byId[id]).map(([id, [title, how]]) => rfSection(`rf-${id}`, title, how, rfList((byId[id].checks || []).flatMap(healthRows), "Nothing to report.")));
  const other = sections.filter((s) => !HEALTH_SECTIONS[s.id] && !HEALTH_NOT_SHOWN.has(s.id)).map((s) => rfSection(`rf-${esc(s.id)}`, esc(s.title || s.id), esc(s.summary || ""), rfList((s.checks || []).flatMap(healthRows), "Nothing to report.")));
  return `${rfFailed(name, r, errs)}${rfFrom(d)}${healthBars(byId)}${known.join("")}${other.join("")}`;
}
// the owner, 9 Nov 2026: "In health could we visualize more?" Each part's health as a bar on its 1 to 10 scale, weakest first,
// its tests' reach beside it; the colour says the band and the words say it too (never colour alone)
function healthBars(byId) {
  const checks = (id, n) => (byId[id]?.checks || []).find((c) => c.name === n)?.data?.components || {};
  const comps = checks("components", "components"), reach = checks("test-reach", "test-reach:components");
  const rows = Object.entries(comps).filter(([, v]) => v.health?.average != null).map(([n, v]) => ({ n, h: v.health.average, files: v.file_count || 0, r: reach[n]?.share }))
    .sort((a, b) => a.h - b.h);
  if (!rows.length) return "";
  const band = (h) => (h < 4 ? ["err", "weak"] : h < 7 ? ["warn", "fair"] : ["ok", "good"]);
  return `<div class="section"><div class="section-h"><h2>Each part's health</h2><span class="tiny faint">1 to 10, weakest first</span></div>
    <div class="card pad hbars">${rows.map((x) => { const [c, w] = band(x.h); return `<div class="hbar" title="${esc(x.n)}: health ${nf(x.h, 1)} of 10 (${w}), ${rfN(x.files, "file")}${x.r != null ? `, tests reach ${nf(x.r * 100)} %` : ""}">
      <div class="hbar-l small wrap">${esc(x.n)}</div><div class="hbar-t"><i class="hbar-f ${c}" style="width:${Math.max(4, x.h * 10)}%"></i></div>
      <div class="hbar-v tiny"><b>${nf(x.h, 1)}</b> ${w}<span class="faint"> · ${rfN(x.files, "file")}${x.r != null ? ` · tests ${nf(x.r * 100)} %` : ""}</span></div></div>`; }).join("")}</div></div>`;
}

function repoWikiHtml(name, r, g) {
  const nodes = g?.nodes || [], root = encodeURIComponent(`repos/${name}/wiki`), home = `#/wiki?root=${root}&back=${encodeURIComponent(repoHref(name, "wiki"))}`;
  if (!nodes.length) return emptyState("This repository has no wiki pages yet.", repoNext(name, r), "card");
  const byFolder = {};
  nodes.forEach((n) => (byFolder[n.folder || "pages"] ??= []).push(n));
  return `<div class="row between wrap" style="gap:8px;margin-bottom:12px"><span class="small muted">${rfN(nodes.length, "page")} · ${rfN((g.links || []).length, "link")}</span><a class="btn sm" href="${home}">${ic.wiki}Open the wiki</a></div>
    ${Object.entries(byFolder).map(([f, l]) => `<div class="wfold"><span class="fdot" style="background:${fcolor(f)}"></span>${esc(f)} <span class="faint">${l.length}</span></div>
    <div class="card list">${l.sort((a, b) => a.title.localeCompare(b.title)).map((n) => `<a href="${home}&page=${encodeURIComponent(n.id)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(n.title)}${n.stale ? ` <span class="pill warn" title="The code this page cites changed since it was written">to check</span>` : ""}</div>${n.summary ? `<div class="sub wrap">${esc(firstSentence(n.summary))}</div>` : ""}</div>${ic.next}</a>`).join("")}</div>`).join("")}`;
}
// DEC-49: the card a coding agent gets first, the owner's hand on it, and what else it can reach (never pushed)
const CARD_KINDS = [["command", "Commands"], ["rule", "Rules that are not obvious"], ["fragile", "Fragile areas"], ["module", "Where things are"], ["start", "Where to start"]];
const CARD_PER_KIND = { command: 6, rule: 10, fragile: 5, module: 12, start: 3 };   // = ops/repocard.py PER_KIND: lines of a part an agent gets
function repoCardHtml(name, r, c) {
  const card = c.card, e = c.edits, pinned = new Set(e.pinned), struck = new Set(e.struck);
  const step = (r.onboard?.steps || []).find((s) => s.id === "card");
  const lines = [...(card?.lines || []), ...e.added];
  if (!lines.length) return emptyState("This repository has no card yet. Onboarding makes it as its last step.", repoNext(name, r), "card");
  const row = (x, given) => {
    const own = x.source === "the owner", off = struck.has(x.id), pin = pinned.has(x.id);
    return `<div class="cardline${off ? " off" : ""}${pin ? " pin" : ""}${!off && !given ? " spare" : ""}"><div class="grow" style="min-width:0"><div class="small wrap">${esc(x.text)}</div>
      <div class="tiny faint wrap">${!off && !given ? `<b>not given</b>: this part keeps its first ${CARD_PER_KIND[x.kind]} lines; pin it to give it · ` : ""}${esc(x.source)}${x.files?.length ? ` · ${x.files.map(esc).join(", ")}` : ""}</div></div>
      <span class="row" style="gap:4px;flex:none">${own ? `<button class="btn sm ghost" data-card="remove" data-id="${x.id}">Remove</button>`
        : off ? `<button class="btn sm ghost" data-card="unstrike" data-id="${x.id}">Bring back</button>`
        : `<button class="btn sm ghost${pin ? " on" : ""}" data-card="${pin ? "unpin" : "pin"}" data-id="${x.id}" title="${pin ? "Unpin" : "Pin: always given, first in its part"}">${pin ? "Pinned" : "Pin"}</button><button class="btn sm ghost" data-card="strike" data-id="${x.id}" title="Never give this line to an agent">Strike</button>`}</span></div>`;
  };
  const reach = c.reach || {};
  const can = [reach.guide && `the written guide (<a href="${repoHref(name, "analysis")}">Analysis</a>)`, reach.wiki && `${rfN(reach.wiki, "wiki page")}${reach.stale?.length ? `, <b class="warn-t">${reach.stale.length} to check</b>` : ""} (<a href="${repoHref(name, "wiki")}">Wiki</a>)`,
    reach.files && `one line per file from the code map (<a href="${repoHref(name, "map")}">Map</a>)`, reach.facts && `the facts (<a href="${repoHref(name, "history")}">History</a>)`].filter(Boolean);
  return `<div class="card pad-l"><div class="row between wrap" style="gap:8px"><h2>What a coding agent gets first</h2>
      <button class="btn sm ghost" id="rcardmake">${ic.repeat}Make again</button></div>${explain("the-repository-card", `Every coding run on ${esc(name)} starts with this card and nothing longer: the few things the code does not say. It is made from what onboarding learned, without a model, and made again on <b>Update</b>. <b>Pin</b> keeps a line always given, first in its part; <b>Strike</b> never gives it; a line you add is always given. Everything else stays where it is and an agent can read it when it wants: the guide, the wiki, the code map's line per file, the facts. The first time it reads a file it is told what the stack knows about that file, and after each edit the repository's linter runs on it.`, "How the card works")}
    <div class="tiny ${step?.behind ? "warn-t" : "faint"} wrap" style="margin-top:4px">${card ? `made ${card.made ? rel(card.made) : ""}${card.commit ? ` at ${esc(card.commit.slice(0, 7))}` : ""}${step?.behind ? ` · <b>${nf(step.behind)} commit${step.behind === 1 ? "" : "s"} behind</b>` : step?.behind === 0 ? " · the latest code" : ""}` : "only your own lines so far"}</div>
    ${CARD_KINDS.map(([k, t]) => {
      const mine = lines.filter((x) => x.kind === k), first = (x) => pinned.has(x.id) || x.source === "the owner";
      const on = [...mine.filter((x) => !struck.has(x.id) && first(x)), ...mine.filter((x) => !struck.has(x.id) && !first(x))];   // the order an agent gets them
      const given = new Set(on.slice(0, Math.max(CARD_PER_KIND[k], on.filter(first).length)).map((x) => x.id));
      const spare = on.filter((x) => !given.has(x.id)), off = mine.filter((x) => struck.has(x.id));
      const fold = (list, what) => list.length ? `<details class="cardfold"><summary class="tiny faint">${list.length} ${what} · show</summary><div class="stack">${list.map((x) => row(x, given.has(x.id))).join("")}</div></details>` : "";
      return mine.length ? `<div class="section-h" style="margin-top:14px"><h3 class="small">${t}</h3><span class="tiny faint">${given.size} given</span></div><div class="stack">${on.filter((x) => given.has(x.id)).map((x) => row(x, true)).join("")}</div>
        ${fold(spare, `more line${spare.length === 1 ? "" : "s"} this part does not give`)}${fold(off, `struck line${off.length === 1 ? "" : "s"}`)}` : "";
    }).join("")}
    <form class="cardadd" id="rcardadd"><select class="input" name="kind" aria-label="The part of the card">${CARD_KINDS.map(([k, t]) => `<option value="${k}"${k === "rule" ? " selected" : ""}>${t}</option>`).join("")}</select>
      <textarea class="input" name="text" rows="2" placeholder="A line every agent should know" minlength="4" required></textarea><button class="btn sm primary">Add</button></form></div>
  ${can.length ? `<div class="card pad section"><div class="small"><b>An agent can also read</b>, when it wants to: ${can.join("; ")}.</div></div>` : ""}`;
}
function bindCard(name, r, el, c) {
  const again = () => { if (rp) rp.loaded?.delete?.("card"); RP_LOAD.card(name, r, el); };
  $$("[data-card]", el).forEach((b) => (b.onclick = async () => { b.disabled = true; if (await act({ action: "card_edit", repo: name, act: b.dataset.card, id: b.dataset.id }, "")) again(); else b.disabled = false; }));
  const f = $("#rcardadd", el);
  if (f) f.onsubmit = async (ev) => { ev.preventDefault(); const t = f.text.value.trim(); if (t.length < 4) return; if (await act({ action: "card_edit", repo: name, act: "add", text: t, kind: f.kind.value }, "Added: every agent gets it")) again(); };
  const m = $("#rcardmake", el);
  if (m) m.onclick = async () => { m.disabled = true; if (!(await act({ action: "understand", repo: name, step: "card" }, "Making the card again: the checklist shows it"))) m.disabled = false; };
}
// ---------- end of the repo page's tabs that only draw ----------

// The repo page, one question per tab (APP-51). A tab's data loads when it is first opened and stays, so going back to a
// tab is instant; a tab change touches the tab row and the panels, never the page. The link holds the tab, the session remembers it.
const REPO_TABS = [["overview", "Overview"], ["map", "Map"], ["card", "Card"], ["history", "History"], ["health", "Health"], ["analysis", "Analysis"], ["wiki", "Wiki"]];
const isRepoTab = (t) => REPO_TABS.some(([k]) => k === t);
let rp = null;                                                 // the repo page on screen: its name, which tabs have loaded, what they share
function repoTabNow(name) {
  const asked = route.q.get("tab");
  if (isRepoTab(asked)) return asked;
  try { const t = sessionStorage.getItem(`mc-repo-tab:${name}`); if (isRepoTab(t)) return t; } catch (_) { /* a remembered tab is a convenience */ }
  return "overview";
}
function showRepoTab(t) {
  rp.tab = t;
  try { sessionStorage.setItem(`mc-repo-tab:${rp.name}`, t); } catch (_) { /* a remembered tab is a convenience */ }
  if (route.q.get("tab") !== t) {                              // this history entry holds its tab, so Back returns to it
    route.q.set("tab", t);
    history.replaceState(history.state, "", `#/repo/${repoEnc(rp.name)}?${route.q}`);
  }
  $$(".repotabs a").forEach((a) => { const on = a.dataset.rt === t; a.classList.toggle("on", on); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  const a = $(".repotabs a.on"), row = a?.parentElement;       // a very narrow phone: only the row moves, never the page (FND-96)
  if (row && row.scrollWidth > row.clientWidth) row.scrollLeft = a.offsetLeft - (row.clientWidth - a.offsetWidth) / 2;
  const el = $(`[data-rp="${t}"]`);
  $$("[data-rp]").forEach((p) => (p.hidden = p !== el));
  if (!rp.loaded.has(t)) { rp.loaded.add(t); RP_LOAD[t](rp.name, repoOf(rp.name), el); }
  if (el.rpWhenShown) { const f = el.rpWhenShown; el.rpWhenShown = null; f(); }
}
function repoTabSwitch() {                                     // the same page's tab link: true when it was handled here, with no redraw
  if (route.name !== "repo" || rp?.name !== route.args[0] || !$(".repotabs")) return false;
  showRepoTab(repoTabNow(rp.name));
  if (restoreTo) { restoreScroll(restoreTo); restoreTo = null; }
  return true;
}
function repoRedraw() {                                        // the end of a job: new content, the same tab, the same place on the page, your words kept
  const y = window.scrollY, text = $("#rchform")?.text.value, open = $("#rchange")?.open;
  view.style.minHeight = `${view.offsetHeight}px`;             // as long as the old page until the new one's parts are in
  vRepo();
  const f = $("#rchform");
  if (f) { f.text.value = text || ""; $("#rchange").open = !!open; }
  window.scrollTo(0, y);
  setTimeout(() => (view.style.minHeight = ""), 3000);
}
const repoEnc = (name) => encodeURIComponent(name);
const rpOverview = (name) => rp.ov || (rp.ov = api(`/api/repo/${repoEnc(name)}/overview`));
const rpFacts = (name) => rp.facts || (rp.facts = api(`/api/repo/${repoEnc(name)}/facts`));
function repoFill(el, name, html) {
  el.innerHTML = html;
  if (el.isConnected) bindOnboard(name);                       // you may have moved on to another repository meanwhile
  $$("[data-rfall]", el).forEach((b) => (b.onclick = () => { b.previousElementSibling.classList.add("all"); b.hidden = true; }));
}
function repoFailed(name, r, el, e, again, shared) {
  repoFill(el, name, emptyState(`This did not load: ${esc(e.message)}`, `<button type="button" class="btn" data-rretry>Try again</button>`, "card"));
  const b = $("[data-rretry]", el);
  if (b) b.onclick = () => { if (shared && rp) rp[shared] = null; again(name, r, el); };
}
const RP_WAIT = `<div class="skeleton" style="height:240px"></div>`;
const RP_LOAD = {
  overview(name, r, el) {
    rpOverview(name).then((o) => {
      const [intro, rest] = repoIntro(o.markdown || "");
      $("#rover", el).innerHTML = intro ? md(intro) + (rest ? `<a class="tiny" href="${repoHref(name, "map")}">Its layers, guided tour and files: Map</a>` : "") : `<div class="small muted">No README and no code map yet.</div>`;
      $("#rsrc", el).textContent = o.source || "";
    }).catch((e) => { $("#rover", el).innerHTML = `<div class="small err-t wrap">This did not load: ${esc(e.message)}</div>`; });
  },
  map: repoLoadMap,
  history: (name, r, el) => repoLoadFacts(name, r, el, repoHistoryHtml),
  health: (name, r, el) => repoLoadFacts(name, r, el, repoHealthHtml),
  analysis(name, r, el) {
    el.innerHTML = RP_WAIT;
    rpOverview(name).then((o) => repoFill(el, name, o.analysis ? `<div class="card pad-l"><div class="md">${md(o.analysis)}</div></div>` : emptyState("This repository has no written analysis yet.", repoNext(name, r), "card")))
      .catch((e) => repoFailed(name, r, el, e, RP_LOAD.analysis, "ov"));
  },
  card(name, r, el) {
    el.innerHTML = RP_WAIT;
    api(`/api/repo/${repoEnc(name)}/card`).then((c) => { repoFill(el, name, repoCardHtml(name, r, c)); bindCard(name, r, el, c); })
      .catch((e) => repoFailed(name, r, el, e, RP_LOAD.card));
  },
  wiki(name, r, el) {
    el.innerHTML = RP_WAIT;
    api(`/api/wiki/graph?root=${encodeURIComponent(`repos/${name}/wiki`)}`).then((g) => repoFill(el, name, repoWikiHtml(name, r, g)))
      .catch((e) => repoFailed(name, r, el, e, RP_LOAD.wiki));
  },
};
function repoLoadFacts(name, r, el, draw) {
  el.innerHTML = RP_WAIT;
  rpFacts(name).then((d) => repoFill(el, name, draw(name, r, d)))
    .catch((e) => repoFailed(name, r, el, e, (n, rr, p) => repoLoadFacts(n, rr, p, draw), "facts"));
}

let cmSwitching = "";                                          // the repo the code map viewer is switching to (one switch at a time)
async function repoSwitchMap(name) {                           // the viewer shows one repo at a time: switch it to this one, then show it inside the page
  if (S.code?.codemap !== name) {
    if (cmSwitching === name) return;
    cmSwitching = name;
    const ok = await act({ action: "codemap", repo: name }, null);   // the viewer opens in place
    cmSwitching = "";
    if (!ok) {
      const w = $("#rframewait");
      if (w) w.innerHTML = `<div class="small err-t">The code map viewer did not start. <button class="btn sm" id="rframeb">${ic.refresh || ""}Try again</button></div>`;
      const again = $("#rframeb");
      if (again) again.onclick = () => { again.disabled = true; repoSwitchMap(name); };
      return;
    }
    if (S.code) S.code.codemap = name;
    await new Promise((res) => setTimeout(res, 2500));          // the viewer restarts on the new repo
  }
  if (rp?.name !== name) return;
  const f = $("#rframe");
  if (f && !f.querySelector("iframe")) f.innerHTML = `<iframe src="${viewerUrl()}" title="Code map of ${esc(name)}"></iframe>`;
  const full = $("#rframefull"); if (full) full.hidden = false;
}
function repoLoadMap(name, r, el) {                            // the heavy tab: the viewer, the code map and the graph start only here
  const g = r.graph;
  el.innerHTML = `${r.codemap ? `<div id="rframesec"><div class="section-h"><h2>Interactive code map</h2><a class="tiny" href="${viewerUrl()}" target="_blank" rel="noopener" id="rframefull" ${S.code?.codemap === name ? "" : "hidden"}>Full screen</a></div>
    <div class="card cmframe" id="rframe">${S.code?.codemap === name ? `<iframe src="${viewerUrl()}" title="Code map of ${esc(name)}" loading="lazy"></iframe>`
      : `<div class="pad-l" id="rframewait"><div class="small muted">Opening the code map of ${esc(name)}…</div></div>`}</div></div>`
    : emptyState("This repository has no code map.", repoNext(name, r), "card")}
  <div id="rcodemap"></div>
  <div class="section"><div class="section-h"><h2>Code graph</h2><span class="tiny faint" id="rgnote"></span></div>
    <div class="rgwrap"><div id="rgraph">${g ? `<div class="skeleton" style="height:420px"></div>` : r.no_code ? emptyState("This repository has no code the graph tool reads: web pages or documents.", `<a class="btn" href="#/chat?prompt=${encodeURIComponent(`In the repository ${name}: `)}">${ic.chat}Ask about it</a>`, "card") : emptyState("This repository has no code graph yet.", repoNext(name, r), "card")}</div>
      <aside class="card pad-l rnode" id="rnode" ${g ? "" : "hidden"}>${explain("tap-a-node-in-the-graph-", `Tap a node in the graph to see what it is, its source code, what it calls and what calls it${r.codemap ? ", and what the code map says about it" : ""}.`, "How to read this")}</aside></div></div>`;
  bindOnboard(name);
  if (r.codemap) {
    repoSwitchMap(name);
    api(`/api/repo/${repoEnc(name)}/map`).then((m) => { const c = $("#rcodemap", el); if (c && !m.error) { c.innerHTML = codeMapHtml(m); bindCodeMap(c, m); } }).catch(() => {});
  }
  if (g) api(`/api/repo/${repoEnc(name)}/graph`).then((d) => {
    const draw = () => {
      $("#rgnote", el).textContent = d.shown < d.total ? `${nf(d.shown)} best-connected of ${nf(d.total)} nodes` : rfN(d.total, "node");
      const colors = {}; (d.communities || []).forEach(([c], i) => (colors[c] = d3.schemeTableau10[i % 10]));
      const groupName = (c) => {                       // a group by its best-connected member, not its number
        const top = d.nodes.filter((n) => n.folder === c).sort((x, y) => (y.degree || 0) - (x.degree || 0))[0];
        return top ? `around ${top.title}` : "other";
      };
      drawGraph($("#rgraph", el), d, "", null, false, {
        color: (n) => colors[n.folder] || "#8e97ab", click: (n) => showNode(name, n.id),
        legend: (d.communities || []).map(([c, k]) => [groupName(c), colors[c], k]), still: true, labels: 25,
      });
    };
    if (el.hidden) el.rpWhenShown = draw; else draw();        // a hidden panel has no size to draw into
  }).catch(() => ($("#rgraph", el).innerHTML = `<div class="card empty small">Graph not available.</div>`));
}
function repoOverviewHtml(name, r, bs) {
  const g = r.graph, mapHref = repoHref(name, "map");
  return `<div class="row wrap small muted" style="gap:8px"><span class="pill ${r.buildable ? "ok" : "archived"}">${r.buildable ? "builder can change it" : "studied only"}</span>
      ${r.source ? `<span class="wrap" style="max-width:340px">${esc(r.source)}</span>` : ""}${r.last ? `<span>· last commit ${rel(r.last.ts)}</span>` : ""}</div>
    <div class="row wrap" style="gap:8px;margin-top:12px">
      ${r.codemap ? `<a class="btn primary" id="rmap" href="${mapHref}">${ic.layers}Interactive code map</a>` : ""}
      <a class="btn" href="#/chat?prompt=${encodeURIComponent(`In the repository ${name}: `)}">${ic.chat}Ask about it</a>
      ${r.buildable ? `<a class="btn" href="#/build?repo=${encodeURIComponent(name)}&new=1">${ic.rocket}New build</a>` : ""}
      <button class="btn ghost" id="rstudy" title="Make the facts, the code map and the analysis anew (the graph updates by itself)" ${r.onboard?.status === "done" ? "" : "hidden"}>${ic.repeat}Re-analyse</button>
      ${!r.buildable && name !== "ai-stack" ? `<button class="btn ghost" id="rbuildable" ${S.code?.forgejo_token ? "" : "disabled title='Needs the Forgejo connection (Code tab)'"}>${ic.rocket}Let the builder change it</button>` : ""}
    </div>
  ${bs.some((b) => b.status === "review") ? `<div class="section"><div class="section-h"><h2>Waiting for you</h2></div><div class="card list waiting">${bs.filter((b) => b.status === "review").map(buildRow).join("")}</div></div>` : ""}
  ${r.buildable ? `<details class="card pad-l section" id="rchange"><summary><b>Request a change</b></summary>
    <form id="rchform" class="stack" style="margin-top:10px"><textarea class="input" name="text" rows="3" required minlength="8" placeholder="What should change"></textarea>
      <div class="row between wrap" style="gap:8px">${explain("request-a-change-", "The swarm writes a specification, then tests and code in this repository's way, checks them against the suite as it was before, and comes back with one branch, the evidence and a pull request. A medium or large change waits for your Go on the specification. Nothing lands without your tap.", "How a change request works")}<button class="btn primary sm">${ic.rocket}Send</button></div></form></details>` : ""}
  <div id="ronboard">${onboardHtml(r)}</div>
  <div class="grid g2 g4 section">
    <div class="card kpi" data-href="${mapHref}"><div class="kpi-l">Code graph</div><div class="kpi-v">${g ? nf(g.nodes) : "–"}</div><div class="kpi-s">${g ? `${nf(g.links)} links · ${g.communities} groups` : r.no_code ? "no code to graph" : "not built yet"}</div></div>
    <div class="card kpi" data-href="${mapHref}"><div class="kpi-l">Code map</div><div class="kpi-v" style="font-size:20px">${r.codemap ? "ready" : "–"}</div><div class="kpi-s">${!r.codemap ? "not built yet" : r.explained?.files ? `${r.explained.status === "running" ? "explaining… " : ""}${nf(r.explained.explained || 0)} of ${nf(r.explained.files)} files explained${r.explained.status === "limit" ? " · resumes later" : ""}` : "explained"}</div></div>
    <div class="card kpi"><div class="kpi-l">Files</div><div class="kpi-v">${r.files ? nf(r.files) : "–"}</div><div class="kpi-s">${r.last ? esc(r.last.sha) : ""}</div></div>
    <div class="card kpi"><div class="kpi-l">Builds</div><div class="kpi-v">${bs.length}</div><div class="kpi-s">${bs.filter((b) => b.status === "deployed" || b.status === "merged").length} merged</div></div>
  </div>
  <div class="split section">
    <div class="card pad-l"><div class="row between"><h2>What it is</h2><span class="tiny faint" id="rsrc"></span></div><div class="md" id="rover" style="margin-top:8px"><div class="skeleton" style="height:120px"></div></div></div>
    <div><div class="section-h"><h2>Builds</h2></div><div class="card list">${bs.map(buildRow).join("") || `<div class="muted small">${r.buildable ? "No builds yet." : "The builder can only change repositories on your Forgejo."}</div>`}</div>
      ${name !== "ai-stack" ? `<details class="card pad-l danger-zone" style="margin-top:14px"><summary class="small"><b>Remove from the stack</b></summary>
        <div class="small muted" style="margin-top:8px">Deletes the stack's copy of ${esc(name)}: its clone, code graph, code map and the builder's working copy. ${r.buildable ? "<b>It stays on your Forgejo</b>: delete it there if you want it gone." : "You can study it again any time."}</div>
        <button class="btn sm ghost danger" id="rremove" style="margin-top:10px">${ic.trash}Remove ${esc(name)}</button></details>` : ""}</div>
  </div>`;
}
// the first part of a digest or README, up to its second heading: what the repository is (the rest lives on the Map tab)
function repoIntro(text) {
  const heads = [...text.matchAll(/^#{1,3} /gm)].map((x) => x.index);
  const cut = heads.length > 1 ? heads[1] : -1;
  return cut > 0 ? [text.slice(0, cut), text.slice(cut)] : [text, ""];
}
function vRepo() {
  const name = route.args[0], r = repoOf(name);
  if (!name) { location.hash = "#/build"; return; }          // no repository named: the list of them (U4)
  if (!r) { view.innerHTML = `<a class="back" href="#/build">${ic.back}Code</a><div class="card empty">${ic.code}<div>No repository called ${esc(name)}. <a href="#/build">All repositories</a></div></div>`; return; }
  const bs = (S.builds || []).filter((b) => b.repo === name), open = repoTabNow(name);
  rp = { name, tab: open, loaded: new Set() };
  view.innerHTML = `
  <a class="back" href="#/build">${ic.back}Code</a>
  <h1 style="font-size:26px">${esc(name)}</h1>${fromChat("repo:" + name)}
  <nav class="seg repotabs" aria-label="Parts of this repository">${REPO_TABS.map(([k, l]) => `<a data-rt="${k}" href="${repoHref(name, k)}">${l}</a>`).join("")}</nav>
  <div data-rp="overview">${repoOverviewHtml(name, r, bs)}</div>
  ${REPO_TABS.filter(([k]) => k !== "overview").map(([k]) => `<div data-rp="${k}" hidden></div>`).join("")}`;
  const rch = $("#rchform");
  if (rch) rch.onsubmit = async (e) => {
    e.preventDefault();
    const res = await act({ action: "change_request", repo: name, text: rch.text.value.trim() }, "The intake writes its specification");
    if (res?.task) location.hash = `#/task/${res.task}`;
  };
  bindOnboard(name);
  onbSeen = JSON.stringify(r.onboard || {});
  const rb = $("#rbuildable");
  if (rb) rb.onclick = async () => { if (!confirm(`Copy ${name} to your Forgejo so the builder can change it? The original stays as "upstream".`)) return; rb.disabled = true; await act({ action: "repo_buildable", repo: name }, `${name} is on Forgejo now`); };
  const rr = $("#rremove");
  if (rr) rr.onclick = async () => {
    if (prompt(`Type ${name} to remove it from the stack:`) !== name) return toast("Not removed", true);
    rr.disabled = true;
    const res = await act({ action: "repo_remove", repo: name }, (x) => (x?.removed ? `${name} removed from the stack${x.still_on_forgejo ? "; it stays on Forgejo" : ""}` : ""));
    if (res?.removed) { location.hash = "#/build"; } else rr.disabled = false;
  };
  showRepoTab(open);
}

// one code graph node: what it is, its source, what it calls / what calls it, and what the code map says
async function showNode(repo, id) {
  const el = $("#rnode");
  if (!el) return;
  el.hidden = false;
  el.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
  const n = await api(`/api/repo/${encodeURIComponent(repo)}/node?id=${encodeURIComponent(id)}`).catch(() => null);
  if (!n || n.error) { el.innerHTML = `<div class="small muted">Nothing more known about this node.</div>`; return; }
  const peers = (list, dir) => {
    const groups = {};
    list.forEach((p) => (groups[p.relation || "linked"] = groups[p.relation || "linked"] || []).push(p));
    return Object.entries(groups).map(([rel, ps]) => `<div class="tiny faint" style="margin-top:8px">${esc(dir === "out" ? relOut[rel] || rel : relIn[rel] || rel)} · ${ps.length}</div>
      <div class="chips rn-peers" style="margin-top:4px">${ps.map((p, i) => `<button class="tag peer${p.text ? " rn-doc" : ""}" data-node="${esc(p.id)}" title="${esc(p.file)}${p.inferred ? " (inferred)" : ""}"${i >= 14 ? " hidden" : ""}>${esc(p.text || p.label)}</button>`).join("")}${ps.length > 14 ? `<button class="linkbtn tiny" data-rnmore>show all ${nf(ps.length)}</button>` : ""}</div>`).join("");
  };
  const ua = n.about || n.about_file;
  el.innerHTML = `
    <div class="row between" style="gap:8px;align-items:flex-start"><div style="min-width:0"><b class="rn-t">${esc(n.label)}</b>
      <div class="row wrap tiny muted" style="gap:6px;margin-top:4px"><span class="tag">${esc(n.kind)}</span>${n.group ? `<span class="tag">${esc(n.group)}</span>` : ""}${n.external ? `<span class="tag">outside this repo</span>` : ""}</div></div>
      <a class="btn sm ghost" href="#/chat?prompt=${encodeURIComponent(`In the repository ${repo}, explain ${n.label}${n.file ? ` (${n.file}${n.line ? `:${n.line}` : ""})` : ""}: what it does, who uses it, and what to watch out for when changing it.`)}" title="Ask Hermes about it">${ic.chat}Ask</a></div>
    ${n.file ? `<div class="small mono" style="margin-top:8px">${esc(n.file)}${n.line ? `:${n.line}` : ""}</div>` : ""}
    ${n.about ? `<div class="rn-ua"><div class="tiny faint">Code map</div><div class="small">${esc(n.about.summary || "")}</div>${n.about.tags?.length ? `<div class="chips" style="margin-top:4px">${n.about.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}${n.about.complexity ? `<span class="tag">${esc(n.about.complexity)}</span>` : ""}</div>` : ""}</div>` : ""}
    ${n.about_file ? `<div class="rn-ua"><div class="tiny faint">Its file, in the code map</div><div class="small">${esc(n.about_file.summary || "")}</div></div>` : ""}
    ${n.note ? `<details class="rn-ua"><summary class="tiny faint">What a coding agent is told on first reading this file</summary><div class="small wrap" style="white-space:pre-wrap;margin-top:6px">${esc(n.note)}</div></details>` : ""}
    ${!ua && !S.code?.repos?.find((x) => x.name === repo)?.codemap ? `<div class="tiny faint" style="margin-top:8px">Build the code map for plain-language explanations of each file and function.</div>` : ""}
    ${peers(n.outgoing, "out")}${peers(n.incoming, "in")}
    ${n.code ? `<details class="rn-code" open><summary class="tiny faint" id="rnsrc">Source · ${nf(n.code.total)} lines, its own ${nf(n.line || n.code.start)} to ${nf(n.code.end)} marked</summary><pre class="code" id="rncode">${esc(n.code.text)}</pre></details>` : ""}`;
  $$(".peer", el).forEach((b) => (b.onclick = () => showNode(repo, b.dataset.node)));
  $$("[data-rnmore]", el).forEach((b) => (b.onclick = () => { b.parentElement.querySelectorAll(".peer[hidden]").forEach((x) => (x.hidden = false)); b.remove(); }));
  if (n.code && n.file) {                                    // the source shown is the whole file (the owner, 9 Nov): its lines marked, in view
    api(`/api/repo/${encodeURIComponent(repo)}/file?path=${encodeURIComponent(n.file)}`).then((f) => {
      const pre = $("#rncode", el);
      if (!pre || !f || f.error) return;
      const lines = f.text.split("\n"), a = Math.max(0, (n.line || n.code.start) - 1), b = Math.min(lines.length, n.code.end);   // from its own first line
      pre.innerHTML = `${esc(lines.slice(0, a).join("\n"))}${a ? "\n" : ""}<mark class="rn-hl" id="rnhl">${esc(lines.slice(a, b).join("\n"))}</mark>${b < lines.length ? "\n" : ""}${esc(lines.slice(b).join("\n"))}`;
      const hl = $("#rnhl", el);
      if (hl) pre.scrollTop = Math.max(0, hl.offsetTop - pre.offsetTop - 24);
    }).catch(() => {});
  }
  if (matchMedia("(max-width: 959px)").matches) el.scrollIntoView({ behavior: "smooth", block: "start" });
}
const relOut = { calls: "Calls", contains: "Contains", imports: "Imports", imports_from: "Imports from", references: "References", inherits: "Inherits from", defines: "Defines", method: "Methods", indirect_call: "Calls indirectly", rationale_for: "Explains" };
const relIn = { calls: "Called by", contains: "Part of", imports: "Imported by", imports_from: "Imported by", references: "Referenced by", inherits: "Inherited by", defines: "Defined by", method: "Method of", indirect_call: "Called indirectly by", rationale_for: "Explained by" };

// the code map (Understand Anything) in the app: project, guided tour, layers, every file and function
function codeMapHtml(m) {
  const p = m.project || {}, nodes = m.nodes || [], byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const item = (id) => { const n = byId[id]; return n ? `<li><b>${esc(n.name || n.filePath)}</b>${n.filePath && n.name !== n.filePath ? ` <span class="tiny faint mono">${esc(n.filePath)}</span>` : ""}<div class="small muted">${esc(n.summary || "")}</div></li>` : ""; };
  return `<div class="section"><div class="section-h"><h2>Code map</h2><span class="tiny faint">Understand Anything${p.analyzedAt ? ` · analysed ${rel(p.analyzedAt)}` : ""}</span></div>
  <div class="card pad-l cmap">
    ${p.description ? `<div class="cm-desc">${esc(p.description)}</div>` : ""}
    <div class="chips" style="margin-top:8px">${(p.languages || []).map((l) => `<span class="tag">${esc(l)}</span>`).join("")}${(p.frameworks || []).map((l) => `<span class="tag">${esc(l)}</span>`).join("")}</div>
    <div class="seg sm" style="margin-top:14px"><button type="button" data-cm="tour" class="on">Guided tour · ${(m.tour || []).length}</button><button type="button" data-cm="layers">Layers · ${(m.layers || []).length}</button><button type="button" data-cm="files">Files & symbols · ${nodes.length}</button></div>
    <div data-cmp="tour"><ol class="cm-tour">${(m.tour || []).sort((a, b) => a.order - b.order).map((t) => `<li><b>${esc(t.title)}</b><div class="small">${esc(t.description)}</div>${(t.nodeIds || []).length ? `<details class="cm-more"><summary class="tiny faint">Its files · ${t.nodeIds.length}</summary><ul class="cm-list">${t.nodeIds.map(item).join("")}</ul></details>` : ""}</li>`).join("")}</ol></div>
    <div data-cmp="layers" hidden>${(m.layers || []).map((l) => `<div class="cm-layer"><b>${esc(l.name)}</b><div class="small muted">${esc(l.description || "")}</div>${(l.nodeIds || []).length ? `<details class="cm-more"><summary class="tiny faint">Its files · ${l.nodeIds.length}</summary><ul class="cm-list">${l.nodeIds.map(item).join("")}</ul></details>` : ""}</div>`).join("")}</div>
    <div data-cmp="files" hidden><div class="wsearch" style="margin-top:10px">${ic.search}<input class="input" id="cmq" placeholder="Filter files and symbols"></div>
      <div class="cm-files">${nodes.map((n) => `<div class="cm-file" data-q="${esc(`${n.name} ${n.filePath} ${n.summary} ${(n.tags || []).join(" ")}`.toLowerCase())}"><div class="row wrap" style="gap:6px"><span class="tag">${esc(n.type)}</span><b>${esc(n.name || n.filePath)}</b>${n.complexity ? `<span class="tiny faint">${esc(n.complexity)}</span>` : ""}</div>
        ${n.filePath && n.name !== n.filePath ? `<div class="tiny faint mono">${esc(n.filePath)}${n.lineRange ? `:${n.lineRange[0]}-${n.lineRange[1]}` : ""}</div>` : ""}<div class="small muted">${esc(n.summary || "")}</div></div>`).join("")}</div></div>
  </div></div>`;
}
function bindCodeMap(el) {
  $$("[data-cm]", el).forEach((b) => (b.onclick = () => {
    $$("[data-cm]", el).forEach((x) => x.classList.toggle("on", x === b));
    $$("[data-cmp]", el).forEach((p) => (p.hidden = p.dataset.cmp !== b.dataset.cm));
  }));
  const q = $("#cmq", el);
  if (q) q.oninput = () => { const v = q.value.trim().toLowerCase(); $$(".cm-file", el).forEach((f) => (f.hidden = v && !f.dataset.q.includes(v))); };
}

// the second pair of eyes (ops/builds.py ai_review): the other engine's verdict on the diff
const VERDICT = { approve: ["ok", "Fine to deploy"], changes: ["paused", "Improve first"], block: ["failed", "Do not deploy"], incomplete: ["paused", "Review incomplete"] };
const LENS = { requirements: "Requirements and correctness", security: "Security and data flow", agents: "Agents rule (no agent rewrites itself)" };
function findingsHtml(fs) {
  return fs?.length ? `<ul class="findings">${fs.map((f) => `<li class="${f.severity}"><div class="row wrap" style="gap:6px"><span class="tag sev">${esc(f.severity)}</span>${f.file ? `<span class="mono tiny">${esc(f.file)}${f.line ? `:${f.line}` : ""}</span>` : ""}</div>
      <div class="small" style="margin-top:4px">${esc(f.issue)}</div>${f.fix ? `<div class="tiny muted" style="margin-top:2px">Fix: ${esc(f.fix)}</div>` : ""}</li>`).join("")}</ul>` : `<div class="small muted" style="margin-top:6px">No problems found.</div>`;
}
function aiReviewHtml(b) {
  const r = b.ai_review;
  if (!r) return "";
  const who = (e) => (e === "claude" ? "Claude Code" : e === "rule" ? "a rule, no model" : "ChatGPT");
  if (r.pending) return `<div class="card pad-l"><h2>AI review</h2><div class="small muted" style="margin-top:8px"><span class="spin" style="width:12px;height:12px;vertical-align:-1px"></span> ${who(r.engine)} reviews the change${r.lenses ? ` with ${r.lenses.length} lenses (${r.lenses.map((l) => LENS[l] || l).join(", ")})` : ""}…</div></div>`;
  if (r.error && !r.verdict) return `<div class="card pad-l"><h2>AI review</h2><div class="small muted" style="margin-top:8px">${esc(r.error)} (${who(r.engine)}). Re-run checks to try again.</div></div>`;
  const [cls, label] = VERDICT[r.verdict] || VERDICT.changes;
  const lenses = r.reviews || [];                        // SWM-95: one reviewer per lens, each with its own verdict
  return `<div class="card pad-l aireview"><div class="row between wrap" style="gap:8px"><h2>AI review</h2><span class="tiny faint">${lenses.length ? `${lenses.length} reviewers` : `by ${who(r.engine)}`} · ${rel(r.at)}</span></div>
    <div class="row wrap" style="gap:8px;margin-top:8px;align-items:center"><span class="pill ${cls}">${label}</span>${lenses.length ? `<span class="small muted">the strictest verdict counts${b.override ? `; you overrode the block: “${esc(b.override.reason)}”` : ""}</span>` : `<span class="small">${esc(r.summary)}</span>`}</div>
    ${r.missing?.length ? `<div class="small err-t wrap" style="margin-top:6px">Not reviewed: ${r.missing.map((l) => esc(LENS[l] || l)).join(", ")}. It stays out of Approve all; Re-run checks to try again.</div>` : ""}
    ${r.note ?`<div class="tiny muted" style="margin-top:6px">${esc(r.note)}${r.same_engine ? " Same engine as the builder, so less independent." : ""}</div>` : ""}
    ${lenses.length ? lenses.map((x) => { const [c2, l2] = VERDICT[x.verdict] || ["queued", "not done"]; return `<div class="lens" style="margin-top:12px;border-top:1px solid var(--border);padding-top:10px">
      <div class="row between wrap" style="gap:6px"><b class="small">${esc(LENS[x.lens] || x.lens)}</b><span class="tiny faint">${who(x.engine)}${x.same_engine ? " (same engine as the builder)" : ""}</span></div>
      <div class="row wrap" style="gap:8px;margin-top:6px;align-items:center"><span class="pill ${c2}">${l2}</span><span class="small">${esc(x.summary || x.error || "")}</span></div>${x.verdict ? findingsHtml(x.findings) : ""}</div>`; }).join("")
    : findingsHtml(r.findings)}
  </div>`;
}

// the plan behind a build (SWM-91, SWM-92, SWM-94, SWM-96): its task and idea, its files and lease, the merge queue,
// the requirements it names and their proof, and the code graph's blast radius
function planHtml(b) {
  const lease = (S.swarm?.leases || []).filter((l) => l.holder === `build:${b.id}`);
  const board = [...(S.swarm?.board?.open || []), ...(S.swarm?.board?.recent || [])];   // builds from before phase 4: the Ledger's ref
  const idea = b.idea || board.find((x) => (x.refs || []).some((r) => r.system === "build" && r.ref === String(b.id)))?.id;
  return `<div class="card pad-l" id="bplan"><h2>Plan, files and blast radius</h2>
    <div class="small" style="margin-top:8px">${b.task ? `Task <a href="#/swarm/artifact/${b.task}">#${b.task}</a> of idea <a href="#/swarm/artifact/${idea}">#${idea}</a>` : idea ? `For idea <a href="#/swarm/artifact/${idea}">#${idea}</a>` : "A direct assignment (no idea behind it)"}${b.note ? ` · ${esc(b.note)}` : ""}${b.slot ? ` · slot ${b.slot}` : ""}${b.queue_pos ? ` · <b>merge queue: ${b.queue_pos === 1 ? "next" : "#" + b.queue_pos}</b>` : ""}</div>
    ${b.files_plan?.length ? `<div class="tiny faint" style="margin-top:6px">Its files: ${b.files_plan.map((f) => `<span class="mono">${esc(f)}</span>`).join(", ")}${lease.length ? " · held for this build" : ""}</div>` : ""}
    ${b.proof ? `<details class="tools" style="margin-top:8px" ${/NOT PROVEN/.test(b.proof) ? "open" : ""}><summary>Requirements it names: ${b.requirements?.length ? b.requirements.map(esc).join(", ") : "none"} · ${/REQUIREMENTS PROVEN/.test(b.proof) ? "proven" : "not proven"}</summary><div class="log">${esc(b.proof)}</div></details>` : ""}
    <div id="bblast" style="margin-top:10px"><div class="small muted">Loading the blast radius…</div></div></div>`;
}
function blastHtml(ctx) {
  const p = ctx?.changed?.files && Object.keys(ctx.changed.files).length ? ctx.changed : ctx?.planned;
  if (!p?.files || !Object.keys(p.files).length) return `<div class="small muted">No blast radius yet (it is drawn from the files a build names or changes).</div>`;
  return `<div class="tiny faint">${p === ctx.changed ? "Of the files it changed" : "Of the files it plans to change"}, from the code graph of main:</div><div class="list" style="margin-top:4px">${Object.entries(p.files).map(([f, d]) => `<div style="padding:6px 2px;display:block">
    <div class="mono small">${esc(f)}</div><div class="tiny faint">${d.callers.length ? `used by ${d.callers.map(esc).join(", ")}${d.more_callers ? ` +${d.more_callers}` : ""}` : "no callers in the graph"}${d.callees.length ? ` · uses ${d.callees.map(esc).join(", ")}` : ""}</div>
    <div class="tiny">tests: ${d.tests.length ? d.tests.map(esc).join(", ") : "<b>none found</b>"}${d.requirements.length ? ` · requirements: ${d.requirements.map(esc).join(", ")}` : ""}</div></div>`).join("")}</div>`;
}

function stepsList(steps) {                             // the builder's steps, drawn as the agent log
  if (!steps.length) return `<div class="small muted">No steps yet.</div>`;
  return (steps.length > 400 ? `<div class="small muted">${steps.length - 400} earlier steps are in the Full log below.</div>` : "") + logHtml(steps.slice(-400) /* cap: list */, { level: "all" });
}

function diffHtml(text) {
  if (!text) return `<div class="small muted">No diff.</div>`;
  const files = text.split(/^diff --git /m).filter(Boolean);
  return files.map((f) => {
    const name = (f.match(/ b\/(.+)\n/) || [])[1] || "file";
    const lines = f.split("\n").slice(1);
    const adds = lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length, dels = lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length;
    const body = lines.filter((l) => !/^(index |--- |\+\+\+ |new file|deleted file|similarity|rename )/.test(l))
      .map((l) => `<div class="dl ${l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : ""}">${esc(l) || " "}</div>`).join("");
    return `<details class="dfile" ${files.length <= 8 ? "open" : ""}><summary><span class="wrap">${esc(name)}</span><span class="tiny"><b style="color:var(--ok)">+${adds}</b> <b style="color:var(--err)">−${dels}</b></span></summary><div class="dcode">${body}</div></details>`;
  }).join("");
}

function vBuildOne(id) {
  const b = (S.builds || []).find((x) => x.id === id);
  if (!b) { view.innerHTML = `<a class="back" href="#/build">${ic.back}Code</a><div class="card empty">Build not found.</div>`; return; }
  const review = b.status === "review";
  const other = b.engine === "claude" ? "hermes" : "claude", otherName = other === "claude" ? "Claude Code" : "ChatGPT";
  const canSwitch = ["queued", "waiting", "review", "failed"].includes(b.status) && (other !== "claude" || S.engines?.claude);
  const ciNeeded = ["ai-stack", "TestRepo"].includes(b.repo), ciOk = !ciNeeded || b.ci === "success";
  const canApprove = review && b.checks_ok && b.ci !== "failure" && !b.approve_on_ci;   // CI running: approve now, deploys when it passes
  view.innerHTML = `
  <a class="back" href="#/build">${ic.back}Code</a>
  <h1 style="font-size:23px">#${b.id} ${esc(b.title)}</h1>${fromChat("build:" + b.id)}
  <div class="row wrap small muted" style="gap:8px;margin-top:6px"><span class="pill ${bcls(b.status)}">${BSTATUS[b.status] || b.status}</span><span>${esc(b.repo)}</span><span>· ${b.engine === "claude" ? "Claude Code" : "ChatGPT · Hermes"}</span><span>· ${esc(b.branch || "")}</span>${b.tokens ? `<span>· ${tok(b.tokens)} tokens${b.cached ? ` (${Math.round(100 * b.cached / b.tokens)} % cached)` : ""}, $0</span>` : ""}</div>
  <div class="row wrap" style="gap:6px;margin-top:10px">${liveLink("build:" + b.id)}</div>
  ${stepper(b.status)}
  ${b.error ? `<div class="banner" style="margin-top:12px;background:var(--err-bg);color:var(--err)">${ic.alert}<span class="grow">${esc(b.error)}</span></div>` : ""}
  ${b.status === "waiting" ? `<div class="banner" style="margin-top:12px">${ic.clock}<span class="grow">Waiting for the usage limit to reset${b.retry_at ? ` (${clock(b.retry_at)})` : ""}${canSwitch ? `, or switch to ${otherName}` : ""}.</span></div>` : ""}
  ${canSwitch ? `<div class="row wrap" style="margin-top:12px"><button class="btn sm ghost" id="bswitch" title="Run this build with the other engine, continuing from its branch">${ic.repeat}Switch to ${otherName}</button></div>` : ""}
  ${review ? `<div class="card pad" style="margin-top:14px">
      <div class="row wrap" style="gap:8px">
        <button class="btn primary" id="bapprove" ${canApprove ? "" : "disabled"}>${ic.check}${b.approve_on_ci ? "Approved · deploys when CI passes" : ciOk ? "Approve & deploy" : "Approve · deploy when CI passes"}</button>
        <button class="btn" id="bchanges">${ic.tune}Request changes</button>
        <button class="btn ghost" id="brecheck" title="Run the checks again on today's main, without the builder">${ic.repeat}Re-run checks</button>
        <button class="btn ghost danger" id="breject">${ic.x}Reject</button>
      </div>
      <div class="small muted" style="margin-top:8px">${b.approve_on_ci ? `Approved. CI on Forgejo is ${esc(b.ci || "pending")}; it merges and deploys by itself the moment CI passes (and stays here if CI fails).` : !b.checks_ok ? "Checks failed: request changes." : b.ci === "failure" ? "CI failed: request changes." : ciOk ? "Approving merges into the main branch and deploys; if the smoke test fails it rolls back by itself." : `CI on Forgejo is ${esc(b.ci || "pending")} (usually 1–3 minutes). You can approve now: it deploys by itself when CI passes.`}</div>
      ${b.sensitive?.length ? `<div class="banner" style="margin-top:10px">${ic.alert}<span class="grow">Touches sensitive files: ${b.sensitive.map(esc).join(", ")}. Read the diff carefully.</span></div>` : ""}
      <div id="chbox" hidden style="margin-top:10px"><textarea class="input" id="chtext" rows="3" placeholder="What should the builder change?"></textarea><button class="btn sm primary" id="chsend" style="margin-top:8px">Send to the builder</button></div>
    </div>` : ""}
  <div class="card pad-l section"><div class="row between wrap" style="gap:8px"><h2>The change · ${b.files?.length || 0} file${b.files?.length === 1 ? "" : "s"}</h2><span class="tiny faint mono">git diff main…${esc(b.branch || "")}</span></div>
    ${b.files?.length ? `<div id="diff" style="margin-top:10px"><div class="skeleton" style="height:60px"></div></div>` : `<div class="small muted" style="margin-top:8px">${["review", "merged", "rolled_back"].includes(b.status) ? "This build changed no files." : "No change yet: the builder is still working."}</div>`}</div>
  <div class="split section">
    <div class="stack">
      <div class="card pad-l" id="bfiles"><h2>Files the builder read and changed</h2><div class="small muted" style="margin-top:6px">Loading…</div></div>
      <div class="card pad-l"><h2>Assignment</h2><div class="md small" style="margin-top:8px">${md(b.description)}</div>${b.feedback ? `<h2 style="margin-top:14px">Changes requested</h2><div class="small" style="margin-top:6px">${esc(b.feedback)}</div>` : ""}</div>
      ${aiReviewHtml(b)}
      ${planHtml(b)}
      ${b.summary ? `<div class="card pad-l"><h2>Builder's summary</h2><div class="md" style="margin-top:8px">${md(b.summary)}</div></div>` : ""}
    </div>
    <div class="stack">
      <div class="card pad"><h2>Checks</h2><div class="row" style="margin-top:8px"><span class="dot ${b.checks ? (b.checks_ok ? "ok" : "err") : ""}"></span><span class="small">${b.checks ? (b.checks_ok ? "Passed in the sandbox" : "Failed") : "Not run yet"}</span></div>${b.checks ? `<details class="tools" style="margin-top:8px"><summary>Output</summary><div class="log">${esc(b.checks)}</div></details>` : ""}
        <h2 style="margin-top:14px">CI (Forgejo)</h2><div class="row" style="margin-top:8px"><span class="dot ${b.ci === "success" ? "ok" : b.ci === "failure" ? "err" : b.ci ? "run" : ""}"></span><span class="small">${esc(b.ci || "not pushed yet")}</span></div>
        ${b.pr ? `<a class="btn sm" style="margin-top:12px" href="${esc(b.pr)}" target="_blank" rel="noopener">${ic.next}Pull request on Forgejo</a>` : ""}</div>
      ${b.status === "deployed" && b.repo === "ai-stack" && b.merged ? `<div class="card pad"><h2>Undo</h2><div class="small muted" style="margin-top:6px">One tap reverts this change on main and deploys the revert, next in the merge queue.${b.idea ? ` Its ${esc((S.swarm?.changes || []).some((x) => x.id === b.idea) ? "agent change" : "idea")} <a href="#/swarm/artifact/${b.idea}">#${b.idea}</a> opens again.` : ""}</div>
        <button class="btn sm" id="brevert" style="margin-top:8px">Revert</button></div>` : ""}
      ${b.deploy ? `<div class="card pad"><h2>Deploy</h2><div class="log" style="margin-top:8px;max-height:320px">${esc(b.deploy)}</div></div>` : ""}
      <div class="card pad"><div class="row between"><h2>What the builder did</h2><span class="tiny faint">${["working", "checking"].includes(b.status) ? "live" : ""}</span></div><div id="bsteps" class="bsteps" style="margin-top:8px"><div class="small muted">Loading…</div></div>
        <button class="btn sm ghost" id="blog" style="margin-top:8px">Full log</button><div class="log" id="blogbox" hidden style="max-height:400px"></div></div>
    </div>
  </div>`;
  api(`/api/build/${b.id}/files`).then((t) => { const el = $("#bfiles"); if (el) { const F = typeof t === "string" ? JSON.parse(t || "{}") : t; el.innerHTML = `<h2>Files the builder read and changed</h2><div style="margin-top:8px">${filesHtml(F.files)}</div><details class="obsb"><summary class="small"><b>Statistics</b></summary>${statsHtml(F.stats)}</details>`; } })
    .catch(() => { const el = $("#bfiles"); if (el) el.innerHTML = `<h2>Files</h2><div class="small muted" style="margin-top:6px">Recorded for builds from 28 October on.</div>`; });
  api(`/api/build/${b.id}/steps`).then((t) => { const el = $("#bsteps"); if (el) el.innerHTML = stepsList(JSON.parse(t || "[]")); }).catch(() => { const el = $("#bsteps"); if (el) el.innerHTML = `<div class="small muted">No steps recorded for this build yet (they appear while the builder works).</div>`; });
  if (b.files?.length) api(`/api/build/${b.id}/diff`).then((t) => ($("#diff").innerHTML = diffHtml(t))).catch(() => ($("#diff").textContent = "Diff not available."));
  api(`/api/build/${b.id}/context`).then((t) => { const el = $("#bblast"); if (el) el.innerHTML = blastHtml(typeof t === "string" ? JSON.parse(t || "{}") : t); })
    .catch(() => { const el = $("#bblast"); if (el) el.innerHTML = blastHtml(null); });
  if ($("#brevert")) $("#brevert").onclick = async () => {            // SWM-18: the one-step revert
    if (!confirm(`Revert build #${b.id} "${b.title}"? A revert commit lands on main and is deployed.`)) return;
    $("#brevert").disabled = true;
    if (!(await act({ action: "build_revert", id: b.id }, `#${b.id}: the revert is next in the merge queue`))) $("#brevert").disabled = false;
  };
  $("#blog").onclick = async () => { const box = $("#blogbox"); box.hidden = !box.hidden; if (!box.hidden) { box.textContent = (await api(`/api/build/${b.id}/log`).catch(() => "")) || "No log yet."; box.scrollTop = box.scrollHeight; } };
  if (canSwitch) $("#bswitch").onclick = async () => {
    if (review && !confirm(`Switch build #${b.id} to ${otherName}? It goes back to the builder for a second attempt from the current branch.`)) return;
    $("#bswitch").disabled = true;
    if (!(await act({ action: "build_switch_engine", id: b.id, engine: other }, `#${b.id} switched to ${otherName}`))) $("#bswitch").disabled = false;
  };
  if (review) {
    $("#bapprove").onclick = async () => {               // one tap; a reviewer's block needs your reason to override (SWM-95)
      let override;
      if (b.ai_review?.verdict === "block") {
        override = prompt(`A reviewer says build #${b.id} must NOT be deployed. To deploy it anyway, write why the block is wrong:`);
        if (!override || override.trim().length < 10) return;
      }
      $("#bapprove").disabled = true;
      if (await act({ action: "build_approve", id: b.id, ...(override ? { override } : {}) }, `#${b.id} approved: in the merge queue`)) location.hash = prevHash.startsWith("#/build/") ? "#/build" : prevHash;
    };
    $("#breject").onclick = async () => { if (confirm(`Reject build #${b.id}? Its branch is deleted.`)) await act({ action: "build_reject", id: b.id }, "Rejected: its branch is deleted"); };
    $("#bchanges").onclick = () => { $("#chbox").hidden = false; $("#chtext").focus(); };
    $("#brecheck").onclick = async () => { $("#brecheck").disabled = true; await act({ action: "build_recheck", id: b.id }, "Checks re-run on today's main"); };
    $("#chsend").onclick = async () => { const t = $("#chtext").value.trim(); if (t && (await act({ action: "build_revise", id: b.id, feedback: t }, "Sent: the builder continues"))) $("#chbox").hidden = true; };
  }
}

