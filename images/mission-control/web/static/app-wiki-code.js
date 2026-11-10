// The app, part of app-base.js, app-tasks.js, app-runs.js, app-devices.js, app-wiki-code.js, app-memory.js, app-workflows.js, app.js (PLT-25): the wiki, chart zoom, builds, ideas and the Code tab. Loaded in that order; one global scope.
// ---------- wiki (Obsidian-style: pages, links, backlinks, graph) ----------
const FOLDER_COLORS = { entities: "#2dd4bf", concepts: "#a78bfa", projects: "#fbbf24", events: "#f472b6", sources: "#94a3b8", answers: "#60a5fa", howto: "#a3e635", comparisons: "#fb923c" };
const fcolor = (f) => FOLDER_COLORS[f] || "#8e97ab";
let wikiRoots = [], wikiMode = "pages", wikiLast = "";       // wikiMode: the open wiki's tab (Pages, Graph, About)

// the New wiki form (bindWikiAdmin): a topic and what it should cover
const wikiNewForm = () => `<form class="card pad-l wnew" id="wnew" hidden><h2>New wiki</h2>
    ${explain("a-research-agent-studies", `A research agent studies the topic in depth (several research steps, with sources) and builds a linked wiki from what it finds. You can chat with Hermes about it afterwards, and run the agent again to deepen it.`, "About this")}
    <input class="input" name="topic" maxlength="70" required placeholder="Topic, e.g. Home battery storage" style="margin-top:10px">
    <textarea class="input" name="cover" rows="3" maxlength="1500" placeholder="What should it cover? (optional) e.g. technologies, prices in Germany, best brands, pitfalls" style="margin-top:8px"></textarea>
    <div class="row wrap" style="gap:8px;margin-top:10px"><button class="btn primary" type="submit">${ic.search}Research and build the wiki</button><button class="btn ghost" type="button" id="wnewx">Cancel</button></div></form>`;

// the Wiki tab: every wiki (the vault's and each agent's), each opening as pages and a graph
function wikiIndex() {
  const live = wikiRoots.filter((r) => !r.archived && !r.repo), old = wikiRoots.filter((r) => r.archived);
  const pages = live.reduce((n, r) => n + (r.pages || 0), 0);
  const row = (r) => `<a href="#/wiki?root=${encodeURIComponent(r.root)}"><div class="ic">${r.mission ? ic.target : ic.brain}</div><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(r.title)}</div>
    <div class="sub wrap">${r.pages} pages · ${r.links} links${r.mission ? "" : " · your vault"}${r.archived ? " · its mission is archived" : ""}</div><div class="sub wrap wuse" data-wuse="${esc(r.root)}"></div></div>${ic.next}</a>`;
  view.innerHTML = `${memFrame("wiki")}<div class="row between wrap" style="gap:10px;margin-bottom:10px">
    <div class="row wrap" style="gap:8px"><button class="btn sm" id="wnewb">${ic.plus}New wiki</button><button class="btn sm" id="vaddb">${ic.plus}Add to the vault</button><a class="btn sm ghost" href="#/sources">${ic.doc}Filed sources</a></div></div>
    <div class="tiny faint" style="margin-bottom:10px">${live.length} wiki${live.length === 1 ? "" : "s"} · ${pages} page${pages === 1 ? "" : "s"}</div>
    ${addVaultHtml()}
  ${wikiNewForm()}
  <div class="wgrid"><div>
  <div class="card list wikis">${live.map(row).join("") || `<div class="pad small muted">No wiki yet. New wiki starts one; every agent's results build its own.</div>`}</div>
  ${old.length ? `<details class="section"><summary class="small muted">${old.length} wiki${old.length > 1 ? "s" : ""} of archived missions (kept, not on the map)</summary><div class="card list wikis" style="margin-top:8px">${old.map(row).join("")}</div></details>` : ""}
  </div>
  <div class="card pad-l wmap"><div class="section-h" style="margin:0"><h2>How they connect</h2></div>
    <div id="wmapsvg" class="wmapsvg"><div class="skeleton" style="height:260px"></div></div><div id="wmapinfo" class="small"></div></div>
  </div>`;
  bindWikiAdmin("", {});
  bindMemFrame();
  bindAddVault();
  wikiMap();
}

// MEM-09, MEM-10: the top layer of the wikis (bubbles sized by pages, lines for shared subjects) and who reads and
// writes each (the run record, 7 days); tap a bubble or a line for the whole story
const wikiAgentName = (a) => (a.startsWith("mission:") ? (S?.missions || []).find((m) => m.slug === a.slice(8))?.title || a.slice(8) : swName(a));
const wikiShort = (t) => String(t).split(/:| \(/)[0].trim();   // cap: preview: the bubble's label; its card and the list name it whole
// Where each bubble's name goes (FND-61): below it, else above, right or left, whichever covers no other name or bubble
// and stays in the box; the biggest wiki chooses first. Returns {x, y, anchor} relative to the bubble's centre.
function wikiMapLabels(nodes, rad, W, H, label, cw = 6.4) {
  const placed = [], out = new Map();
  const hit = (a, b) => a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];
  const over = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  for (const n of [...nodes].sort((a, b) => (b.pages || 0) - (a.pages || 0))) {
    const r = rad(n), w = label(n).length * cw;
    const spots = [{ x: 0, y: r + 13, anchor: "middle" }, { x: 0, y: -r - 5, anchor: "middle" }, { x: r + 4, y: 4, anchor: "start" }, { x: -r - 4, y: 4, anchor: "end" }]
      .map((s) => { const x0 = n.x + s.x - (s.anchor === "middle" ? w / 2 : s.anchor === "end" ? w : 0); return { ...s, box: [x0, n.y + s.y - 11, x0 + w, n.y + s.y + 3] }; });
    const bubbles = nodes.filter((o) => o !== n).map((o) => [o.x - rad(o), o.y - rad(o), o.x + rad(o), o.y + rad(o)]);
    const cost = (s) => (s.box[0] < 0 || s.box[2] > W || s.box[1] < 0 || s.box[3] > H ? 1e6 : 0)
      + [...placed, ...bubbles].reduce((c, b) => c + over(s.box, b), 0);
    const best = spots.find((s) => cost(s) === 0) || spots.reduce((a, b) => (cost(b) < cost(a) ? b : a));
    placed.push(best.box);
    out.set(n, { x: best.x, y: best.y, anchor: best.anchor });
    if (cost(best)) out.clashes = (out.clashes || 0) + 1;
  }
  return out;
}
async function wikiMap() {
  const [map, acc] = await Promise.all([api("/api/wiki/map").catch(() => null), api("/api/wiki/access?hours=168").catch(() => [])]);
  const box = $("#wmapsvg");
  if (!box || !map) { if (box) box.innerHTML = `<div class="small muted">The map is not available right now.</div>`; return; }
  const byRoot = {};
  for (const x of acc || []) (byRoot[x.root] ??= []).push(x);
  for (const n of map.nodes) {
    const el = $(`[data-wuse="${CSS.escape(n.root)}"]`), use = byRoot[n.root] || [];
    const readers = use.filter((x) => x.reads).map((x) => `${n.mission && x.agent === "mission:" + n.mission ? "its agent" : wikiAgentName(x.agent)} (${x.reads})`);
    if (el) el.title = readers.join(", ");
    const times = use.reduce((k, x) => k + (x.reads || 0), 0);
    if (el) el.textContent = `${readers.length ? `read ${times} time${times === 1 ? "" : "s"} in the last 7 days by ${readers.length} agent${readers.length === 1 ? "" : "s"}` : "not read by an agent in the last 7 days"} · written by ${n.mission ? "its agent" : "the curator"}${n.changed_7d ? `, ${n.changed_7d} page${n.changed_7d > 1 ? "s" : ""} changed this week` : ""}`;
  }
  const W = box.clientWidth || 340;
  let H = Math.max(260, Math.min(380, W * 0.8));
  const col = (n) => (n.root === "wiki" ? "#a78bfa" : n.root.startsWith("topics/") ? "#2dd4bf" : "#fbbf24");
  const rad = (n) => 12 + 4 * Math.sqrt(n.pages || 0);
  const nodes = map.nodes.map((n) => ({ ...n, id: n.root })), links = map.edges.map((e) => ({ source: e.a, target: e.b, subjects: e.subjects }));
  let at;
  for (;;) {                                                   // taller, 60 px at a time, until every name has a free place
    const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance(110).strength(0.25))
      .force("charge", d3.forceManyBody().strength(-260)).force("x", d3.forceX(W / 2).strength(0.07)).force("y", d3.forceY(H / 2).strength(0.1))
      .force("collide", d3.forceCollide((d) => Math.max(rad(d) + 34, wikiShort(d.title).length * 3.2 + 8))).stop();
    for (let i = 0; i < 300; i++) sim.tick();
    for (const n of nodes) {                                   // inside the box with its whole label
      const half = Math.max(rad(n), wikiShort(n.title).length * 3.2) + 4;
      n.x = Math.max(half, Math.min(W - half, n.x)); n.y = Math.max(rad(n) + 4, Math.min(H - rad(n) - 18, n.y));
    }
    at = wikiMapLabels(nodes, rad, W, H, (d) => wikiShort(d.title));
    if (!at.clashes || H >= 520) break;                         // at most 520 px tall: still one screen on a phone
    H += 60;
  }
  const top = Math.min(...nodes.map((n) => n.y + Math.min(-rad(n), at.get(n).y - 12))) - 6;     // no empty band above or below
  H = Math.max(...nodes.map((n) => n.y + Math.max(rad(n), at.get(n).y + 4))) + 6 - top;
  for (const n of nodes) n.y -= top;
  box.innerHTML = "";
  const svg = d3.select(box).append("svg").attr("viewBox", [0, 0, W, H]).attr("class", "graph");
  svg.append("g").selectAll("line").data(links).join("line").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y)
    .attr("stroke", "var(--border-2)").attr("stroke-width", (d) => 1.5 + Math.min(6, d.subjects.length)).style("cursor", "pointer")
    .on("click", (_, d) => info(`<b>${esc(d.source.title)}</b> and <b>${esc(d.target.title)}</b> share ${d.subjects.length} subject${d.subjects.length > 1 ? "s" : ""}: ${d.subjects.map(esc).join(", ")}`));
  const g = svg.append("g").selectAll("g").data(nodes).join("g").attr("transform", (d) => `translate(${d.x},${d.y})`).style("cursor", "pointer")
    .on("click", (_, d) => (location.hash = `#/wiki?root=${encodeURIComponent(d.root)}`));      // a bubble is the wiki: tap and you are in
  g.append("title").text((d) => `${d.title}: ${d.pages} pages`);
  g.append("circle").attr("r", rad).attr("fill", (d) => col(d)).attr("fill-opacity", 0.25).attr("stroke", (d) => col(d)).attr("stroke-width", 2);
  g.append("text").attr("text-anchor", "middle").attr("dy", "0.35em").attr("class", "wmapn").text((d) => d.pages);
  g.append("text").attr("text-anchor", (d) => at.get(d).anchor).attr("x", (d) => at.get(d).x).attr("y", (d) => at.get(d).y).attr("class", "wmapl").text((d) => wikiShort(d.title));
  const info = (h) => ($("#wmapinfo").innerHTML = `<div class="wmapcard">${h}</div>`);
  info(`<span class="muted">${map.shared.length ? `${map.shared.length} subject${map.shared.length > 1 ? "s are" : " is"} in two or more wikis. Tap a bubble to open its wiki, a line for the subjects both have.` : "No subject is in two wikis yet. Tap a bubble to open its wiki."}</span>`);
}
// a summary's first sentence, marked when more follows (the whole summary heads the wiki's page)  cap: preview
// firstSentence: app-base.js (every page's scripts load it)

let wikiBack = "";                                       // where the wiki was opened from (an agent page and its tab)
async function vWiki() {
  const bk = route.q.get("back");
  if (bk && /^#\/[\w\/%?=&.:-]*$/.test(bk)) wikiBack = bk;
  if (!wikiRoots.length) wikiRoots = await api("/api/wiki/roots").catch(() => []);
  if (route.name !== "wiki") return;                                            // FND-95: you left while it loaded
  if (!route.q.get("root")) return wikiIndex();                     // the tab opens on every wiki, not on one picked for you
  const root = route.q.get("root"), pageId = route.q.get("page");
  if (root !== wikiLast) { wikiMode = "pages"; wikiLast = root; }    // another wiki opens on its pages
  const info = wikiRoots.find((r) => r.root === root) || { title: root };
  const graph = await api(`/api/wiki/graph?root=${encodeURIComponent(root)}`).catch(() => ({ nodes: [], links: [] }));
  if (route.name !== "wiki" || route.q.get("root") !== root) return;
  if (!graph.nodes) { view.innerHTML = `${memFrame("wiki")}${emptyState(`${ic.wiki}<div>This wiki is not there any more.</div>`, `<a class="btn sm" href="#/wiki">See the wikis</a>`)}`; bindMemFrame(); return; }
  const home = `#/wiki?root=${encodeURIComponent(root)}`;
  if (pageId) {                                                      // a page gets the whole screen, one step back to its wiki
    view.innerHTML = `<a class="back" href="${home}">${ic.back}${esc(info.title)}</a><div id="wbody"></div>`;
    return wikiPage($("#wbody"), root, pageId, graph);
  }
  // a wiki: its name, search, then its pages to tap (Graph and About one tap away)
  const byFolder = {};
  graph.nodes.forEach((n) => (byFolder[n.folder || "pages"] ??= []).push(n));
  Object.values(byFolder).forEach((l) => l.sort((a, b) => a.title.localeCompare(b.title)));
  const mode = ["pages", "graph", "about"].includes(wikiMode) ? wikiMode : "pages";
  const back = wikiBack ? (S?.missions || []).find((x) => wikiBack.startsWith(`#/mission/${encodeURIComponent(x.slug)}`))?.title || "Back" : "";
  const owner = info.mission ? `#/mission/${encodeURIComponent(info.mission)}` : "";
  view.innerHTML = `<a class="back" href="${back ? esc(wikiBack) : "#/wiki"}">${ic.back}${back ? esc(back) : "All wikis"}</a>
  <div class="hero heading" style="margin-bottom:14px"><h1 class="wh1">${esc(info.title)}</h1>
    <p>${graph.nodes.length} pages · ${graph.links.length} links${owner ? ` · <a class="wl" href="${owner}">its agent</a>` : info.task ? ` · <a class="wl" href="#/task/${info.task}">its task</a>` : " · your vault"}</p></div>
  <div class="row wrap wacts"><button class="btn sm primary" id="wrefb">${ic.tune}Improve this wiki</button>${owner ? `<a class="btn sm" href="${owner}">${ic.target}Its agent</a>` : ""}${info.mission ? `<button class="btn sm ghost danger" id="wdel">${ic.trash}Delete wiki</button>` : ""}</div>
  ${refineForm("wiki")}
  <div class="wsearch card">${ic.search}<input class="input" id="wq" type="search" placeholder="Search this wiki"></div>
  <div class="seg wseg">${[["pages", "Pages"], ["graph", "Graph"], ["about", "About"]].map(([k, l]) => `<button data-wm="${k}" class="${mode === k ? "on" : ""}">${l}</button>`).join("")}</div>
  <div id="wbody"></div>`;
  const body = $("#wbody"), link = (id) => `${home}&page=${encodeURIComponent(id)}`;
  const row = (n, sub) => `<a href="${link(n.id)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(n.title)}</div>${sub ? `<div class="sub wrap">${sub}</div>` : ""}</div>${ic.next}</a>`;
  const pages = () => Object.entries(byFolder).map(([f, l]) => `<div class="wfold"><span class="fdot" style="background:${fcolor(f)}"></span>${esc(f)} <span class="faint">${l.length}</span></div>
    <div class="card list">${l.map((n) => row(n, n.summary ? esc(firstSentence(n.summary)) : "")).join("")}</div>`).join("")
    || `<div class="card pad small muted">This wiki is empty. It fills up with every result of its agent.</div>`;
  const about = () => `<div class="card pad-l"><h2>About this wiki</h2>
    <p class="small" style="margin:8px 0 0">${info.summary ? esc(info.summary) : `<span class="muted">No summary yet: it is written within half an hour.</span>`}</p>
    <div class="tiny faint" style="margin-top:10px">${owner ? "Its agent adds to it with every result; Improve this wiki asks for a correction or more research now. Delete wiki removes its pages (the vault's history keeps them) and its agent stops writing one."
      : "Built from the notes and clippings in your vault by the curator, so it can't be deleted here: change or delete the notes instead. Improve this wiki still corrects or extends its pages."}</div></div>`;
  const show = () => {
    if (mode === "graph") drawGraph(body, graph, root, null);
    else body.innerHTML = mode === "about" ? about() : pages();
    bindWikiAdmin(root, info);
  };
  $$("[data-wm]").forEach((b) => (b.onclick = () => { wikiMode = b.dataset.wm; render(true); }));
  bindRefine(root, "");
  show();
  const q = $("#wq");
  q.oninput = async () => {
    const v = q.value.trim();
    if (v.length < 2) return show();
    const hits = await api(`/api/wiki/search?root=${encodeURIComponent(root)}&q=${encodeURIComponent(v)}`).catch(() => []);
    if (q.value.trim() !== v) return;                                // a newer search is on its way
    body.innerHTML = `<div class="wfold">${hits.length} found</div><div class="card list">${hits.map((h) => row(h, `…${esc(h.snippet)}…`)).join("") || `<div class="pad small muted">Nothing found.</div>`}</div>`;
  };
}

// TSK-34: improve a wiki or one page: what is wrong or what to find out becomes a task; research agents look into it,
// then the wiki's writer corrects and extends the pages (an old fact stays, marked superseded)
const REFINE = { wiki: ["Check its facts and fix the mistakes", "Research what is missing", "Bring it up to date"],
  page: ["Check its facts and fix the mistakes", "Research more about this", "Bring it up to date"] };
const refineForm = (scope) => `<form class="card pad-l wref" id="wref" hidden><h2>${scope === "page" ? "Correct or research this page" : "Improve this wiki"}</h2>
    ${explain("say-what-is-wrong-or-wha", `Say what is wrong or what to find out. It becomes a task: research agents look into it with sources, then the wiki's writer corrects ${scope === "page" ? "this page" : "the pages"} (an old fact stays, marked superseded) and adds what is new. You follow it on Tasks.`, "About this")}
    <div class="chips" style="margin-top:10px">${REFINE[scope].map((x) => `<button type="button" class="tag" data-rq="${esc(x)}">${esc(x)}</button>`).join("")}</div>
    <textarea class="input" name="text" rows="3" maxlength="3000" required placeholder="${scope === "page" ? "e.g. The capacity figure is wrong: check the newest quarterly report" : "e.g. Add the Kazakh producers and check every price"}" style="margin-top:8px"></textarea>
    <div class="row wrap" style="gap:8px;margin-top:10px"><button class="btn primary" type="submit">${ic.rocket}Do it</button><button class="btn ghost" type="button" data-rx>Cancel</button></div></form>`;
function bindRefine(root, page) {
  const f = $("#wref"), b = $("#wrefb");
  if (!f || !b) return;
  b.onclick = () => { f.hidden = !f.hidden; if (!f.hidden) { f.scrollIntoView({ block: "nearest", behavior: "smooth" }); f.text.focus({ preventScroll: true }); } };
  $("[data-rx]", f).onclick = () => (f.hidden = true);
  $$("[data-rq]", f).forEach((x) => (x.onclick = () => { f.text.value = x.dataset.rq + (f.text.value.trim() ? ". " + f.text.value.trim() : ""); f.text.focus(); }));
  f.onsubmit = async (e) => {
    e.preventDefault();
    const sub = $("[type=submit]", f);
    sub.disabled = true;
    const r = await act({ action: "task_create", text: f.text.value.trim(), kind: "research", wiki: { root, page } }, (x) => `Task #${x.task} is being planned: its steps show on Tasks`);
    sub.disabled = false;
    if (!r) return;
    location.hash = `#/task/${r.task}`;
  };
}

// New wiki = a deep research task whose results compile into its wiki; delete = two taps (the vault keeps the history)
function bindWikiAdmin(root, info) {
  const f = $("#wnew");
  if (f) bindWikiNew(f);
  const d = $("#wdel");
  if (!d) return;
  d.onclick = async () => {
    if (!d.dataset.armed) {
      d.dataset.armed = "1"; d.innerHTML = `${ic.trash}Tap again to delete ${info.pages || 0} pages`;
      setTimeout(() => { if (d.isConnected) { delete d.dataset.armed; d.innerHTML = `${ic.trash}Delete wiki`; } }, 5000);
      return;
    }
    d.disabled = true;
    const r = await act({ action: "wiki_delete", root }, (x) => x.detail);
    if (!r) { d.disabled = false; return; }
    wikiRoots = [];
    location.hash = "#/wiki";
  };
}

function bindWikiNew(f) {
  $("#wnewb").onclick = () => { f.hidden = !f.hidden; if (!f.hidden) f.topic.focus(); };
  $("#wnewx").onclick = () => (f.hidden = true);
  if (route.q.get("new") && f.hidden) { f.hidden = false; f.topic.focus(); }
  f.onsubmit = async (e) => {
    e.preventDefault();
    const topic = f.topic.value.trim(), cover = f.cover.value.trim();
    if (topic.length < 3) return toast("Name the topic (3 characters or more)", true);
    f.querySelector("[type=submit]").disabled = true;
    const r = await act({ action: "create", type: "task", title: `Wiki: ${topic}`.slice(0, 80) /* cap: id: the topic is in its description */, depth: "deep", deliver: ["app"], schedule: "manual",
      description: `Research "${topic}" in depth and build a knowledge wiki about it: the key entities, concepts, projects and events, with dated facts and sources.${cover ? ` Cover: ${cover}` : ""} Write a clear report of the findings; the wiki is compiled from it.` },
      (x) => (x.duplicate ? x.detail : "Research started: the wiki appears with its first result"));
    f.querySelector("[type=submit]").disabled = false;
    if (!r) return;
    wikiRoots = [];
    location.hash = `#/mission/${encodeURIComponent(r.slug)}`;
  };
}

async function wikiPage(el, root, id, graph) {
  el.innerHTML = `<div class="skeleton"></div>`;
  const p = await api(`/api/wiki/page?root=${encodeURIComponent(root)}&id=${encodeURIComponent(id)}`);
  if (p.error) { el.innerHTML = `<div class="card empty">${esc(p.error)}</div>`; return; }
  const meta = p.meta || {};
  const local = { nodes: graph.nodes.filter((n) => n.id === id || graph.links.some((l) => (l.source === id && l.target === n.id) || (l.target === id && l.source === n.id))), links: graph.links.filter((l) => l.source === id || l.target === id) };
  el.innerHTML = `${refineForm("page")}<div class="wpage">
    <article class="card pad-l md reader">
      ${(meta.reverify || []).length ? `<div class="card pad warn-b small wrap" style="margin-bottom:10px"><b>To check:</b> the code this page cites changed since it was written (${meta.reverify.slice(0, 6).map(esc).join(", ")}${meta.reverify.length > 6 ? "…" : ""}). The Scribe checks it on its next pass; until then read it with the code.</div>` : ""}
      <div class="chips" style="margin-bottom:10px">${p.type ? `<span class="tag"><span class="fdot" style="background:${fcolor(id.split("/")[0])}"></span>${esc(p.type)}</span>` : ""}${meta.last_validated ? `<span class="tag">updated ${esc(meta.last_validated)}</span>` : ""}${meta.trust ? `<span class="tag">${esc(meta.trust)}</span>` : ""}${(meta.sources || []).length ? `<span class="tag">${meta.sources.length} source${meta.sources.length > 1 ? "s" : ""}</span>` : ""}</div>
      <div class="row wrap wtitle"><h1>${esc(p.title)}</h1><button type="button" class="btn sm primary" id="wrefb">${ic.tune}Correct or research</button><button type="button" class="btn sm" data-copy-markdown>${ic.doc}Copy markdown</button></div>
      ${md(p.body.replace(/^#\s+.*\n/, ""), { root, links: p.links })}
      ${(meta.sources || []).length ? `<h2>Sources</h2><ul>${meta.sources.slice(-12).reverse().map((s) => `<li><a class="wl" href="#/read?path=${encodeURIComponent(String(s).endsWith(".md") ? s : s + ".md")}">${esc(s)}</a></li>`).join("")}</ul>` : ""}
    </article>
    <aside class="stack">
      <div class="card pad"><h2>Linked mentions · ${p.backlinks.length}</h2><div class="stack" style="margin-top:10px">${p.backlinks.map((b) => `<a class="witem" href="#/wiki?root=${encodeURIComponent(root)}&page=${encodeURIComponent(b.id)}">${esc(b.title)}</a>`).join("") || `<div class="small muted">No page links here yet.</div>`}</div></div>
      <div class="card pad"><h2>Local graph</h2><div id="lgraph" class="lgraph"></div></div>
    </aside></div>`;
  const copy = $("[data-copy-markdown]", el);
  copy.onclick = async () => {
    copy.disabled = true;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(p.markdown);
      toast("Copied");
    } catch (e) { toast("Could not copy: " + e.message, true); }
    finally { copy.disabled = false; }
  };
  bindRefine(root, id);
  drawGraph($("#lgraph"), local, root, id, true);
}

// ---------- charts: one way to move, zoom and name the dots (every zoomable chart; the owner's review of 2026-10-30) ----------
// One finger or the mouse moves the view, two fingers (or ctrl + wheel, a trackpad pinch) zoom, the + − and fit buttons
// do both; a plain wheel scrolls the page. Every dot has a name: a name that would cover another gives way to the busier
// dot's and comes back as you zoom in, like the names on a map. (Before, one chart moved with one finger, another only
// with two, and dots carried no name until zoomed.)
const CHART_HINT = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches ? "Two fingers to move or zoom · tap a dot" : "Drag to move · Ctrl + wheel or + − to zoom · tap a dot";
function chartZoom(host, svg, root, { min = 0.2, max = 8, onZoom, fit } = {}) {
  svg.style("touch-action", "pan-y").style("cursor", "grab");          // one finger scrolls the page, as on any phone map
  const zoom = d3.zoom().scaleExtent([min, max])
    .filter((e) => (e.type === "wheel" ? e.ctrlKey || e.metaKey : e.type.startsWith("touch") ? e.touches.length > 1 : !e.button))
    .on("zoom", (e) => { root.attr("transform", e.transform); onZoom?.(e.transform); });
  svg.call(zoom).on("dblclick.zoom", null);
  if (getComputedStyle(host).position === "static") host.style.position = "relative";
  host.insertAdjacentHTML("beforeend", `<div class="chartbtns"><button type="button" data-z="in" aria-label="Zoom in">+</button><button type="button" data-z="out" aria-label="Zoom out">−</button><button type="button" data-z="fit" aria-label="Fit everything in">⤢</button></div>`);
  host.lastElementChild.onclick = (e) => {
    const z = e.target.closest("[data-z]")?.dataset.z;
    if (z === "fit") (fit ? fit(true) : svg.transition().duration(250).call(zoom.transform, d3.zoomIdentity));
    else if (z) svg.transition().duration(200).call(zoom.scaleBy, z === "in" ? 1.6 : 1 / 1.6);
  };
  return zoom;
}
// The transform that fits every point into a w x h box (at most `most` times bigger), `right` screen pixels kept free
// on the right for the names of the dots there
// `least`: never start smaller than this (a dense chart then opens at a readable size around its middle; drag for the rest)
function chartFit(pts, w, h, pad = 30, most = 1.5, right = 60, least = 0) {
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  const k = Math.max(least, Math.min((w - right) / (x1 - x0), h / (y1 - y0), most));
  return d3.zoomIdentity.translate((w - right) / 2 - k * (x0 + x1) / 2, h / 2 - k * (y0 + y1) / 2).scale(k);
}
// Show the names that fit at zoom k, busiest first; items: {x, y, r (data units) or rs (screen px), text, prio, el}.
// A name never covers another name, nor a dot that ranks as high as its own (an agent's name may cover a small idea's dot).
function placeLabels(items, k, px = 11) {
  const dots = items.map((it) => { const r = it.rs ? it.rs / k : it.r; return [it.x - r, it.y - r, it.x + r, it.y + r, it.prio, it]; });
  const names = [], h = (px + 3) / k, cw = (px * 0.58) / k;
  const hit = (b, x0, y0, x1, y1) => x0 < b[2] && x1 > b[0] && y0 < b[3] && y1 > b[1];
  for (const it of [...items].sort((a, b) => b.prio - a.prio)) {
    const r = it.rs ? it.rs / k : it.r, x0 = it.x + r + 3 / k, y0 = it.y - h / 2, x1 = x0 + it.text.length * cw, y1 = y0 + h;
    const free = !names.some((b) => hit(b, x0, y0, x1, y1)) && !dots.some((b) => b[5] !== it && b[4] >= it.prio && hit(b, x0, y0, x1, y1));
    if (free) names.push([x0, y0, x1, y1]);
    Object.assign(it.el.style, { display: free ? "" : "none", fontSize: `${px / k}px`, strokeWidth: `${3 / k}px` });
    it.el.setAttribute("x", r + 3 / k);
    it.el.setAttribute("y", (px * 0.36) / k);
  }
}

function drawGraph(el, g, root, focus, small = false, opts = {}) {
  if (!window.d3) { el.innerHTML = `<div class="card empty">Graph library not loaded.</div>`; return; }
  if (!g.nodes.length) { el.innerHTML = `<div class="card empty">${ic.wiki}<div>No pages yet.</div></div>`; return; }
  const W = el.clientWidth || 600, H = small ? 240 : Math.max(420, Math.min(window.innerHeight - 260, 720));
  el.innerHTML = small ? "" : `<div class="card graphcard"></div>`;
  const host = small ? el : $(".graphcard", el);
  const nodes = g.nodes.map((n) => ({ ...n })), links = g.links.map((l) => ({ ...l }));
  const svg = d3.select(host).append("svg").attr("viewBox", [0, 0, W, H]).attr("class", "graph");
  const zoomG = svg.append("g");
  const link = zoomG.append("g").attr("class", "glinks").selectAll("line").data(links).join("line");
  const node = zoomG.append("g").selectAll("g").data(nodes).join("g").attr("class", (d) => "gnode" + (d.id === focus ? " focus" : ""))
    .style("cursor", "pointer").on("click", (_, d) => { if (opts.click) return opts.click(d); location.hash = `#/wiki?root=${encodeURIComponent(root)}&page=${encodeURIComponent(d.id)}`; });
  const r = (d) => 4 + Math.min(Math.sqrt(d.degree || 0) * 2.6, opts.still ? 12 : 99) + (d.id === focus ? 3 : 0);
  node.append("circle").attr("r", r).attr("fill", (d) => (opts.color ? opts.color(d) : fcolor(d.folder)));
  node.append("title").text((d) => `${d.title}${d.summary ? "\n" + d.summary : ""}`);
  const lbl = zoomG.append("g").attr("class", "glabels").selectAll("g").data(nodes).join("g");      // names above every dot
  const text = lbl.append("text").text((d) => d.title).attr("class", "lbl");
  const items = nodes.map((d, i) => ({ get x() { return d.x; }, get y() { return d.y; }, r: r(d), text: String(d.title || ""), el: text.nodes()[i],
    prio: (d.id === focus ? 1e6 : 0) + (d.degree || 0) }));
  let k = 1;
  const place = () => placeLabels(items, k);
  const adj = new Set(links.map((l) => `${l.source}|${l.target}`));
  node.on("mouseenter", (_, d) => {
    node.classed("dim", (o) => o.id !== d.id && !adj.has(`${d.id}|${o.id}`) && !adj.has(`${o.id}|${d.id}`));
    link.classed("hot", (l) => l.source.id === d.id || l.target.id === d.id);
  }).on("mouseleave", () => { node.classed("dim", false); link.classed("hot", false); });
  const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance(small ? 50 : 70))
    .force("charge", d3.forceManyBody().strength(small ? -160 : -220)).force("center", d3.forceCenter(W / 2, H / 2))
    .force("collide", d3.forceCollide().radius((d) => r(d) + 6)).force("x", d3.forceX(W / 2).strength(0.04)).force("y", d3.forceY(H / 2).strength(0.06))
    .on("tick", () => {
      link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
      lbl.attr("transform", (d) => `translate(${d.x},${d.y})`);
    }).on("end", place);
  sim.stop(); for (let i = 0; i < 260; i++) sim.tick(); sim.on("tick")();     // lay out once, draw once: nothing drifts under a finger
  const fit = (animate) => { const t = chartFit(nodes, W, H, 30, small ? 1.2 : 1.5, small ? 30 : 60, small ? 0 : 0.55); (animate ? svg.transition().duration(250) : svg).call(zoom.transform, t); };
  const zoom = chartZoom(host, svg, zoomG, { onZoom: (t) => { k = t.k; place(); }, fit });
  fit(false);
  const legend = opts.legend || [...new Set(nodes.map((n) => n.folder || "pages"))].map((f) => [f, fcolor(f)]);
  if (!small) host.insertAdjacentHTML("beforeend", `<div class="legend">${legend.map(([f, col]) => `<span><span class="fdot" style="background:${col}"></span>${esc(f)}</span>`).join("")}<span class="faint">${CHART_HINT} ${opts.click ? "for its details" : "to open it"}</span></div>`);
}

// ---------- build: assignments for the sandboxed builder, review, tap-to-deploy ----------
const BSTEPS = [["queued", "Queued"], ["working", "Building"], ["review", "Review"], ["deploying", "Deploying"], ["deployed", "Live"]];
const BSTATUS = { waiting: "Waiting for ChatGPT", queued: "Queued", working: "Building", review: "Ready for review", approved: "Approved", deploying: "Deploying",
  deployed: "Deployed", merged: "Merged", rolled_back: "Rolled back", failed: "Failed", rejected: "Rejected", recheck: "Checks queued", checking: "Checking",
  planning: "Being planned", planned: "Waits for its dependencies", cancelled: "Cancelled", reverting: "Being reverted", reverted: "Reverted" };
const bcls = (s) => ({ deployed: "ok", merged: "ok", review: "running", working: "running", deploying: "running", approved: "running",
  queued: "queued", waiting: "paused", failed: "failed", rolled_back: "failed", rejected: "archived", planning: "running", planned: "queued", cancelled: "archived",
  reverting: "running", reverted: "archived" }[s] || "queued");

function stepper(st) {
  const idx = { queued: 0, waiting: 1, working: 1, review: 2, approved: 3, deploying: 3, deployed: 4, merged: 4 }[st] ?? -1;
  const bad = ["failed", "rolled_back", "rejected"].includes(st);
  return `<div class="stepper">${BSTEPS.map(([k, l], i) => `<div class="st ${i < idx || (i === idx && ["deployed", "merged"].includes(st)) ? "done" : i === idx ? (bad ? "bad" : "cur") : ""}"><span></span>${l}</div>`).join("")}</div>`;
}

// The stack's own improvement ideas: the swarm's Ledger (ops/swarm_client.publish -> S.swarm.board). Agents propose by
// identity key and refine instead of copying; open ideas are ranked by impact, confidence, recurrence and effort.
// the owner taps "Build it" (the idea becomes a builder assignment, review and tap-to-deploy still follow) or "Dismiss".
const IDEA_STATE = { active: ["run", "building"], checking: ["ok", "shipped, being checked"], done: ["ok", "proved"], declined: ["archived", "dismissed"],
  merged: ["archived", "merged"], gone: ["archived", "gone"], blocked: ["warn", "blocked"], snoozed: ["archived", "snoozed"] };
// ---------- ideas (the Ledger): the stack's own fixes (crew, self-review, doctor) in one list with the Coach's agent
// changes, under Agents → Ideas (swarm.js swIdeas). These are its parts. ----------
function stackIdeaCard(p, n) {
  return `<div class="prop card pad-l section" data-kind="stack">
        <div class="row" style="gap:8px;flex-wrap:wrap"><span class="tag">#${n + 1}</span><span class="tag kind">The stack</span><span class="tag">${esc(p.owner || "")}</span><span class="tag">${esc(p.effort || "small")}</span>${p.state === "ready" ? `<span class="tag">ready</span>` : ""}<span class="tiny faint">${p.created ? rel(new Date(p.created * 1000).toISOString()) : ""}</span><span class="tiny mono faint" title="priority: impact × confidence × recurrence ÷ effort" style="margin-left:auto">${nf(+p.priority, 2)}</span></div>
        <b class="ptitle">${esc(p.title)}</b>
        <div class="tiny faint" data-iorig="${p.id}"></div>
        <div class="tiny faint psig">${ic.radar}${prose(p.signal || "")}${p.evidence > 1 ? ` · ${p.evidence} sightings` : ""}${p.merged_from ? ` · ${p.merged_from} duplicate${p.merged_from > 1 ? "s" : ""} merged in` : ""}${p.recurrence ? ` · came back ${p.recurrence}×` : ""}</div>
        <details class="pdesc"><summary class="small muted">What the builder will do</summary><div class="small" style="white-space:pre-wrap;margin-top:6px">${esc(p.body || "")}</div></details>
        <div class="row" style="justify-content:flex-end;gap:8px"><button class="btn sm ghost" data-pdismiss="${p.id}">${ic.x}Dismiss</button>${S.engines?.claude ? `<button class="btn sm" data-paccept="${p.id}" data-engine="claude" title="Build it with Claude Code">Claude</button>` : ""}<button class="btn sm primary" data-paccept="${p.id}">${ic.rocket}Build it</button></div>
      </div>`;
}
function stackDecidedRow(p) {
      const [cls, label] = IDEA_STATE[p.state] || ["archived", p.state], build = (p.refs || []).find((r) => r.system === "build");
      const prog = p.state === "checking" ? (S.swarm?.checks || {})[String(p.id)] : "";
      return `<div style="padding:7px 2px;flex-wrap:wrap"><span class="pill ${cls}" style="padding:1px 7px">${esc(label)}</span><div class="grow small">${esc(p.title)}${p.decision?.reason ? ` <span class="faint">· ${esc(p.decision.reason)}</span>` : ""}${prog ? `<div class="tiny faint">Checker: ${esc(prog)}</div>` : ""}</div>${build ? `<a class="tiny" href="#/build/${esc(build.ref)}">#${esc(build.ref)}</a>` : ""}
        ${p.state === "checking" ? `<div class="row" style="gap:6px;width:100%;justify-content:flex-end">${p.check?.type === "owner_confirms" ? `<button class="btn sm" data-sconfirm="${p.id}">It works</button>` : ""}<button class="btn sm ghost" data-sreopen="${p.id}">Still broken</button></div>` : ""}</div>`;
    }
function ideaRulesHtml() {
  const paused = S.swarm?.paused || [];
  return `<div class="card pad-l section"><h2>Rules</h2>
    ${(S.swarm?.autonomy || []).length ? `<div class="hsub" style="margin-top:8px">Autonomy</div>${explain("a-rule-lets-an-agent-sta", `A rule lets an agent start building an idea without your tap. The deploy always waits for your tap; you can stop any build. Off unless you switch it on.`, "About this")}
      <div class="list" style="margin-top:6px">${S.swarm.autonomy.map((r) => `<div style="padding:7px 2px"><div class="grow small">${esc(r.title)}</div><button class="btn sm ${r.on ? "" : "ghost"}" data-sauto="${esc(r.id)}" data-on="${r.on ? "0" : "1"}">${r.on ? "On · switch off" : "Off · switch on"}</button></div>`).join("")}</div>` : ""}
    <div class="row between wrap" style="margin-top:12px;gap:8px"><span class="tiny faint">${paused.length ? `Paused: ${paused.map((x) => (x === "*" ? "all agents" : esc(x))).join(", ")}` : "No agent is paused"}</span>
      <button class="btn sm ghost" data-swpause="*" data-on="${paused.includes("*") ? "0" : "1"}">${paused.includes("*") ? "Resume all agents" : "Pause all agents"}</button></div></div>`;
}
// what waits for a tap: the stack's open ideas and the agent changes that passed their experiment
const ideasWaiting = () => (S?.swarm?.board?.open || []).length
  + (S?.swarm?.changes || []).filter((a) => a.state === "ready" && a.experiment?.passed && a.experiment.version === a.version).length;

function bindSwarmIdeas() {
  $$("[data-sconfirm]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (await act({ action: "swarm_confirm", id: +b.dataset.sconfirm }, "Thanks: the Checker marks it proved")) chrome(); }));
  $$("[data-sreopen]").forEach((b) => (b.onclick = async () => {
    const reason = prompt("What is still broken?", "");
    if (reason === null) return;
    b.disabled = true;
    if (await act({ action: "swarm_reopen", id: +b.dataset.sreopen, reason }, "Back on the list")) chrome();
  }));
  $$("[data-sauto]").forEach((b) => (b.onclick = async () => {
    const on = b.dataset.on === "1";
    if (on && !confirm("Switch this rule on? The agent may start such builds by itself; every deploy still waits for your tap.")) return;
    b.disabled = true;
    if (await act({ action: "swarm_autonomy", template: b.dataset.sauto, on }, on ? "Rule on: ideas it allows start by themselves" : "Rule off: its unfinished builds wait for you")) chrome();
  }));
}

function bindSwarmPause() {
  $$("[data-swpause]").forEach((b) => (b.onclick = async () => {
    const on = b.dataset.on === "1", who = b.dataset.swpause;
    if (on && !confirm(who === "*" ? "Pause every agent? None runs or writes until you resume." : `Pause ${who}? It does not run or write until you resume it.`)) return;
    b.disabled = true;
    if (await act({ action: "swarm_pause", agent: who, on }, on ? "Paused: it starts no new runs until you resume it" : "Resumed: it runs at its next time")) chrome(); else b.disabled = false;
  }));
}

function bindProposals() {
  bindSwarmPause();
  bindSwarmIdeas();
  const sc = $("#iscan");
  if (sc) sc.onclick = async () => { sc.disabled = true; if (await act({ action: "improve_scan" }, "Self-review started: proposals arrive in a minute or two")) chrome(); };
  $$("[data-paccept]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    const r = await act({ action: "proposal_accept", id: +b.dataset.paccept, engine: b.dataset.engine || "hermes" }, (x) => (x?.build ? `Build #${x.build} queued: follow it on its page` : ""));
    if (r?.build) { location.hash = `#/build/${r.build}`; } else b.disabled = false;
  }));
  $$("[data-pdismiss]").forEach((b) => (b.onclick = async () => {
    const reason = prompt("Why not? (optional: the agent that proposed it learns from your reason)", "");
    if (reason === null) return;
    b.disabled = true;
    await act({ action: "proposal_dismiss", id: +b.dataset.pdismiss, reason }, "Dismissed: the agent that proposed it learns from your reason");
  }));
}

// ---------- code tab: repositories (study, code graph, code map), the stack's proposals, builds ----------
const repoOf = (name) => (S.code?.repos || []).find((r) => r.name === name);

function repoActivity(name) {
  const bs = (S.builds || []).filter((b) => b.repo === name);
  return { review: bs.filter((b) => b.status === "review").length, busy: bs.filter((b) => ["queued", "working", "checking", "waiting", "deploying"].includes(b.status)).length };
}

// APP-47: the repositories are a directory of their own, never one more list among the work: always in view on a desktop, one tap on a phone
const isTrial = (name) => /^trial-/.test(name);
function repoRow(r) {
  const a = repoActivity(r.name), o = r.onboard;
  const line = o && ONB_LIVE.includes(o.status) ? onboardLabel(r) : o?.status === "failed" ? "onboarding stopped" : [r.last && rel(r.last.ts), r.files && `${nf(r.files)} file${r.files === 1 ? "" : "s"}`].filter(Boolean).join(" · ");
  return `<a class="rrow ${r.buildable ? "mine" : ""}" href="#/repo/${encodeURIComponent(r.name)}" title="${esc(r.last?.subject || r.source || r.name)}">
    <span class="rrow-n">${esc(r.name)}</span><span class="rrow-s">${esc(line)}</span>
    ${a.review ? `<span class="rrow-c" title="${a.review} to review">${a.review}</span>` : a.busy ? `<span class="rrow-live" title="${a.busy} being worked on"></span>` : ""}</a>`;
}
function repoDir(repos) {
  const real = repos.filter((r) => !isTrial(r.name)), mine = real.filter((r) => r.buildable), studied = real.filter((r) => !r.buildable), trials = repos.filter((r) => isTrial(r.name));
  const group = (label, list) => (list.length ? `<div class="rgroup">${label}</div>${list.map(repoRow).join("")}` : "");
  return `<aside class="repodir" aria-label="Repositories"><div class="repodir-h"><h2>Repositories</h2><span class="num">${real.length}</span></div>
    ${mine.map(repoRow).join("")}${group("Studied", studied)}
    ${real.length ? "" : `<div class="small muted" style="padding:8px">None yet. Add repository brings the first one in.</div>`}
    ${trials.length ? `<details class="rtrials" data-keep="rtrials"><summary class="rgroup">Exam trials · ${trials.length}</summary>${trials.map(repoRow).join("")}</details>` : ""}</aside>`;
}

// A change is one row here, however many builds its steps are: its task page has them all
const CHANGE_ASKS = ["needs_answer", "waiting_approval"], CHANGE_WORKS = ["intake", "planning", "running"];
const CHANGE_LABEL = { intake: "Writing the specification", planning: "Planning", running: "Working", needs_answer: "Has a question", waiting_approval: "Waits for your Go", failed: "Stopped" };
const STEP_BUILD = /^(builder|tester|breaker): /;
function changeRow(t) {
  const st = t.steps || [], i = st.findIndex((x) => !["done", "skipped"].includes(x.status)), cur = st[i];
  const cls = t.status === "failed" ? "failed" : t.status === "running" ? "running" : "paused";
  const line = t.status === "failed" ? (t.error || "") : cur ? `step ${i + 1} of ${st.length} · ${cur.agent}${cur.waiting_for ? ` · ${cur.waiting_for}` : ""}` : "";
  return `<a href="#/task/${t.id}"><div class="ic ${t.status === "failed" ? "err" : t.status === "running" ? "run" : ""}">${t.status === "failed" ? ic.alert : ic.target}</div>
    <div class="grow"><div class="ttl wrap">Change #${t.id} ${esc(t.title)}</div><div class="sub wrap"><span class="pill ${cls}" style="padding:1px 7px">${CHANGE_LABEL[t.status] || esc(t.status)}</span>${line ? ` · ${esc(line)}` : ""}</div></div>
    <div class="tiny faint">${rel(t.updated)}</div></a>`;
}

function forgejoCard() {
  if (S.code?.forgejo_token) return "";
  return `<details class="card pad-l fjcard" ${route.q.get("forgejo") ? "open" : ""}><summary><b>Connect Forgejo once</b> <span class="small muted">· 2 minutes · lets the stack create repositories, let the builder change studied ones, and open pull requests</span></summary>
    <ol class="small" style="margin:10px 0 0;padding-left:20px;line-height:1.75">
      <li>At home (Forgejo is on your NAS), open <a href="${DEPLOY.FORGEJO_URL}/user/settings/applications" target="_blank" rel="noopener"><b>Forgejo → Settings → Applications</b></a> and sign in if asked.</li>
      <li>Under <b>Generate new token</b>: name <code>mission-control</code>; permissions <b>repository: Read and write</b>, <b>user: Read</b>. Tap <b>Generate token</b> and copy the long code it shows (only shown once).
        <div class="tiny faint">Your existing token <i>ai-stack-status</i> can only read, and Forgejo can't add rights to a token later. This one replaces it for everything; you can delete the old one afterwards.</div></li>
      <li>Paste it here: <div class="row wrap" style="gap:8px;margin-top:6px"><input class="input" id="fjtok" type="password" autocomplete="off" spellcheck="false" placeholder="paste the token" style="flex:1;min-width:200px"><button class="btn primary" id="fjgo">${ic.check}Connect</button></div>
        <div class="tiny faint" style="margin-top:4px">The runner checks it with Forgejo, stores it encrypted with your other secrets and restarts itself. It never goes to Hermes or any AI.</div></li>
    </ol></details>`;
}

function claudeCard() {
  if (S.engines?.claude) return "";
  return `<details class="card pad-l fjcard"><summary><b>Connect Claude Code once</b> <span class="small muted">a second builder engine, on your Claude subscription</span></summary>
    <ol class="small" style="margin:10px 0 0;padding-left:20px;line-height:1.7">
      <li>In Windows PowerShell: <code>wsl -d Ubuntu-24.04 -u ${DEPLOY.DEPLOY_USER} --cd ${DEPLOY.STACK_DIR} make claude-connect</code></li>
      <li>Open the link it shows, sign in to Claude, paste the code back.</li>
      <li>Paste the token it then prints (starts with <code>sk-ant-oat</code>) when it asks. It stays hidden and is saved encrypted.</li>
      <li>That's it: this card disappears, and <b>Claude Code</b> becomes an engine choice for builds.</li>
    </ol>
    ${explain("claude-builds-run-in-the", `Claude builds run in the same sandbox, with the same checks, review and tap-to-deploy. That repository's code is sent to Anthropic for those builds; usage counts against your Claude plan.`, "About this")}</details>`;
}

function vBuild() {
  const id = route.args[0];
  if (id) return vBuildOne(+id);
  const bs = S.builds || [], repos = S.code?.repos || [], buildable = repos.filter((r) => r.buildable && !isTrial(r.name)).map((r) => r.name);
  const pre = route.q.get("repo") || "ai-stack";
  const changes = (S.tasks || []).filter((t) => t.kind === "change" && !/^trial/.test(t.source || ""));
  const inReview = (t) => (t.steps || []).some((x) => x.harness === "change-deliver" && x.status === "waiting");      // its carrier build is the row
  const asks = changes.filter((t) => CHANGE_ASKS.includes(t.status)), working = changes.filter((t) => CHANGE_WORKS.includes(t.status) && !inReview(t)), stoppedChanges = changes.filter((t) => t.status === "failed");
  const review = bs.filter((b) => b.status === "review");
  const stepOfChange = (b) => STEP_BUILD.test(b.title || "");
  const busy = bs.filter((b) => ["queued", "working", "checking", "waiting", "deploying", "recheck"].includes(b.status) && !(stepOfChange(b) && working.length));
  const stopped = bs.filter((b) => b.status === "failed" && !stepOfChange(b) && !isTrial(b.repo));
  const done = bs.filter((b) => !review.includes(b) && !busy.includes(b) && !stopped.includes(b) && !["queued", "working", "checking", "waiting", "deploying", "recheck"].includes(b.status));
  const asking = review.length + asks.length;
  const pane = pref("mc-code-pane", "repos");
  view.innerHTML = `
  <div class="hero codehero"><div class="grow"><h1>Code</h1></div>
    <div class="row wrap" style="gap:8px;justify-content:flex-end"><button class="btn" id="addbtn">${ic.plus}Add repository</button><button class="btn primary" id="newbtn">${ic.rocket}New build</button></div></div>
  <div class="card repo addrepo" id="addrepo" ${route.q.get("add") ? "" : "hidden"} style="margin-bottom:14px">
      <div class="row between"><b class="repo-n" style="margin:0">Add a repository</b><button class="icon-btn" id="addclose" title="Close">${ic.x}</button></div>
      <div class="seg sm" style="margin-top:8px"><button type="button" data-ar="study" class="on">Study GitHub repo</button><button type="button" data-ar="new">New repo</button></div>
      <div id="ar-study"><input class="input" id="ar-url" placeholder="https://github.com/owner/name" style="margin-top:8px">
        <div class="seg sm" style="margin-top:8px" title="Your own work gets an engineer's guide (entry points, module map, how to extend it); something to evaluate gets a review (what it is, what the stack could take from it)"><button type="button" data-ark="own" class="on">My own work</button><button type="button" data-ark="evaluate">Something to evaluate</button></div>
        <button class="btn sm primary" id="ar-go" style="margin-top:8px">${ic.search}Study it</button>
        </div>
      <div id="ar-new" hidden><input class="input" id="ar-name" placeholder="name (lowercase)" style="margin-top:8px"><input class="input" id="ar-desc" placeholder="What is it for? (optional)" style="margin-top:6px">
        <button class="btn sm primary" id="ar-create" style="margin-top:8px" ${S.code?.forgejo_token ? "" : "disabled"}>${ic.plus}Create on Forgejo</button>
        ${S.code?.forgejo_token ? "" : `<div class="tiny faint" style="margin-top:6px">Needs the Forgejo connection (below, one time).</div>`}</div>
      
  </div>
  <div class="card pad-l newbuild" id="nb" ${route.q.get("new") ? "" : "hidden"} style="margin-bottom:14px">
    <div class="row between"><b>${ic.rocket} New build</b><button class="icon-btn" id="nbclose" title="Close">${ic.x}</button></div>
    <form id="bf" autocomplete="off" style="margin-top:12px">
    <div class="row wrap" style="gap:10px">
      <label class="field" style="margin:0;flex:1;min-width:140px"><span>Repository</span><select class="input" name="repo">${(buildable.length ? buildable : ["ai-stack"]).map((r) => `<option ${r === pre ? "selected" : ""}>${esc(r)}</option>`).join("")}</select></label>
      <label class="field" style="margin:0;flex:3;min-width:200px"><span>Title</span><input class="input" name="title" maxlength="100" placeholder="e.g. Show the next run time in the mission cards"></label>
      <label class="field" style="margin:0;flex:1;min-width:150px"><span>Engine</span><select class="input" name="engine"><option value="claude" ${S.engines?.claude ? "selected" : "disabled"}>Claude Code${S.engines?.claude ? "" : " (connect first)"}</option><option value="hermes" ${S.engines?.claude ? "" : "selected"}>ChatGPT · Hermes</option></select></label>
    </div>
    <label class="field"><span>What should it do?</span><textarea class="input" name="desc" rows="4" placeholder="Describe the change and how you'll know it works."></textarea></label>
    <button class="btn primary" type="submit">${ic.rocket}Assign to the builder</button>
  </form></div>
  <div class="seg codeseg" role="tablist"><button type="button" data-cp="repos" class="${pane === "repos" ? "on" : ""}">Repositories · ${repos.filter((r) => !isTrial(r.name)).length}</button><button type="button" data-cp="work" class="${pane === "work" ? "on" : ""}">Work${asking ? ` · ${asking}` : ""}</button></div>
  <div class="codegrid" data-pane="${pane}">
    ${repoDir(repos)}
    <div class="codework">
      <div class="section-h codeask"><h2>Waiting for you${asking ? ` · ${asking}` : ""}</h2>${readyAll(review) ? `<button class="btn sm primary" id="appall">${ic.check}Approve all ready (${readyAll(review)})</button>` : ""}</div>
      ${asking ? `${typeof explain === "function" && review.length ? explain("approve-all-", "Tap one to see the change. <i>Approve all</i> deploys every build whose checks and CI passed and whose AI review finished without a block, one after another; a conflict goes back to you.", "How Approve all works") : ""}
        <div class="card list waiting">${asks.map(changeRow).join("")}${review.map(buildRow).join("")}</div>` : `<div class="card pad small muted">Nothing waits for your review.</div>`}
      ${working.length || busy.length ? `<div class="section-h section"><h2>Working · ${working.length + busy.length}</h2>${how("builder")}</div><div class="card list">${working.map(changeRow).join("")}${busy.map(buildRow).join("")}</div>` : ""}
      ${stoppedChanges.length || stopped.length ? `<div class="section-h section"><h2>Stopped · ${stoppedChanges.length + stopped.length}</h2></div><div class="card list">${stoppedChanges.map(changeRow).join("")}${stopped.map(buildRow).join("")}</div>` : ""}
      ${forgejoCard()}${claudeCard()}
      <a class="banner info section" href="#/tasks?v=ideas">${ic.radar}<span class="grow">${ideasWaiting() ? `<b>${ideasWaiting()} idea${ideasWaiting() > 1 ? "s" : ""} wait for your tap</b>` : "No open ideas"} · the stack's own fixes, in Agents → Ideas</span>${ic.next}</a>
      ${done.length ? `<details class="section codehist" data-keep="builds"><summary class="section-h"><h2>Earlier builds · ${done.length}</h2></summary><div class="card list">${done.map(buildRow).join("")}</div></details>` : ""}
      ${(S.claude_tasks || []).length ? `<details class="section codehist" data-keep="questions"><summary class="section-h"><h2>Questions to Claude Code · ${S.claude_tasks.length}</h2></summary>
        <div class="card list">${S.claude_tasks.map(ctRow).join("")}</div></details>` : ""}
    </div>
  </div>`;
  $$("[data-cp]").forEach((b) => (b.onclick = () => {
    try { localStorage.setItem("mc-code-pane", b.dataset.cp); } catch (_) { /* a remembered pane is a convenience */ }
    $$("[data-cp]").forEach((x) => x.classList.toggle("on", x === b));
    $(".codegrid").dataset.pane = b.dataset.cp;
  }));
  bindAddRepo();
  if ($("#appall")) $("#appall").onclick = async (e) => {
    e.target.disabled = true;
    const r = await act({ action: "build_approve_all" }, (x) => (x?.approved ? `${x.approved.length} approved: deploying one after another` : ""));
    if (!r?.approved) e.target.disabled = false;
  };
  $("#addbtn").onclick = () => { $("#addrepo").hidden = !$("#addrepo").hidden; if (!$("#addrepo").hidden) $("#ar-url").focus(); };
  $("#addclose").onclick = () => ($("#addrepo").hidden = true);
  $("#newbtn").onclick = () => { $("#nb").hidden = !$("#nb").hidden; if (!$("#nb").hidden) $("#bf").title.focus(); };
  $("#nbclose").onclick = () => ($("#nb").hidden = true);
  if ($("#fjgo")) $("#fjgo").onclick = async () => {
    const t = $("#fjtok").value.trim();
    if (!t) return toast("Paste the token first", true);
    $("#fjgo").disabled = true;
    const r = await api("/api/forgejo/connect", { method: "POST", body: JSON.stringify({ token: t }) }).catch((e) => ({ ok: false, error: e.message }));
    $("#fjtok").value = ""; $("#fjgo").disabled = false;
    if (r.ok) toast(`Forgejo connected as ${r.user}. The card disappears in a minute.`); else toast(r.error || "Could not connect", true);
  };
  const f = $("#bf");
  f.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("button[type=submit]", f); btn.disabled = true;
    const r = await act({ action: "build_assign", repo: f.repo.value, title: f.title.value.trim(), description: f.desc.value.trim(), engine: f.engine.value }, (x) => (x?.id ? `Build #${x.id} queued: follow it on its page` : ""));
    btn.disabled = false;
    if (r?.id) { location.hash = `#/build/${r.id}`; }
  };
}

