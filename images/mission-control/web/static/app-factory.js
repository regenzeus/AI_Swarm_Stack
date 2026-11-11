// The app, part of index.html's scripts (PLT-25): the Workflows place (APP-71 to APP-73; the factory design's phase A).
// - #/workflows: every workflow of the site in one list, grouped by factory (home, the platform) and area; each card
//   says its name, area, trigger, last run, next run, open Asks and result, one line each.
// - #/workflow/<id>: its diagram (always: drawn here from n8n's nodes and connections, the AI Stack step's kind and
//   agent on each node), Run now, its runs, its result, its agents and its settings; "Edit in n8n" on the desk.
// - #/run/<workflow>/<run>: the diagram with the path the run took, each step's state, its Asks, cost and result.
// The old sources without an n8n workflow (requests in a sentence, Claude questions, chat requests, builds, briefings)
// are runs of the standard workflows Request, Change and Briefing, each drawn from its template (server.workflows.py).
let FV = null, fvAt = 0, wfArea = "", wfQuery = "";
async function factoryView(fresh = false) {            // one read serves the list and the agents' "used in" (APP-76)
  if (!fresh && FV && Date.now() - fvAt < 15000) return FV;
  FV = await api("/api/factory").catch(() => FV || { workflows: [], factories: {}, areas: {} });
  fvAt = Date.now();
  return FV;
}
const RUN_STATE = { running: ["running", "running"], waiting: ["paused", "waits for you"], done: ["ok", "done"], failed: ["failed", "failed"],
  refused: ["failed", "refused"], cancelled: ["archived", "cancelled"] };
const runPill = (s) => (([c, l]) => `<span class="pill ${c}">${s === "running" ? '<span class="dot run"></span>' : ""}${esc(l)}</span>`)(RUN_STATE[s] || ["", s || "–"]);
// who started a run, in the owner's words (a run on a schedule never says "you asked")
const RUN_BY = { schedule: "on its schedule", owner: "you started it", start: "you asked", n8n: "on its schedule", event: "on an event", restart: "again after a restart" };
const ASKED_BY = { you: "you asked", rule: "a trigger of yours", agent: "an outside agent", stack: "on its schedule", flow: "on its schedule" };
function runBy(r) { return RUN_BY[r.trigger] || ASKED_BY[r.asked] || ""; }
// a card's line of text: its first sentence, whole when short, else its start with a visible "…" (the page has all of it)
function oneLine(s, n = 140) {
  const t = firstSentence(String(s || "").replace(/\s+/g, " "));
  return t.length <= n ? t : `${t.slice(0, n).replace(/\s+\S*$/, "")} …`;   /* cap: preview: the card opens the workflow's page, which shows the whole result */
}
const wfHref = (w) => `#/workflow/${encodeURIComponent(w.id)}`;
const runHref = (wid, rid) => `#/run/${encodeURIComponent(wid)}/${encodeURIComponent(rid)}`;
const triggerWords = (w) => (w.source === "standard" ? w.trigger : w.trigger === "when called" ? "Run now or when called" : w.trigger || "by hand");

// ---------- the list ----------
async function vWorkflows() {
  const open = route.q.get("open") || "";
  if (open === "executions") return location.replace("#/n8n?open=executions");
  if (open) return location.replace(`#/workflow/${encodeURIComponent(open)}`);
  if (route.q.has("area")) wfArea = route.q.get("area") || "";
  if (route.q.get("new") === "1") tnewOpen = true;
  if (!FV) view.innerHTML = `<h1>Workflows</h1><div class="stack"><div class="skeleton" style="height:96px"></div><div class="skeleton" style="height:96px"></div></div>`;
  const v = await factoryView();
  if (route.name !== "workflows") return;
  const ws = v.workflows || [], running = ws.reduce((n, w) => n + (w.running || (["running", "waiting"].includes(w.last_run?.state) ? 1 : 0)), 0);
  const asks = ws.reduce((n, w) => n + (w.asks || 0), 0), failed = ws.filter((w) => w.last_run?.state === "failed").length;
  view.innerHTML = `<div class="hero"><div class="grow"><h1>Workflows</h1><p id="wfhead">${nf(ws.length)} workflows${running ? ` · <span class="run-t">${nf(running)} running</span>` : ""}${asks ? ` · <b class="warn-t">${nf(asks)} Ask${asks === 1 ? "" : "s"} open</b>` : ""}${failed ? ` · <span class="err-t">${nf(failed)} failed last time</span>` : ""}</p></div>
      <div class="row gap-2">${wfDesk() ? `<a class="btn sm" href="#/n8n">${ic.edit}Edit in n8n</a>` : ""}<button class="btn primary" id="tnewb">${ic.plus}New request</button></div>
      ${explain("wf-what", `Everything the stack does is a workflow: a trigger, steps and a result. n8n decides when each one starts and in what order; the agents do its steps. Each workflow's page shows its diagram, its runs and its result. ${how("workflows")}`, "About workflows")}</div>
    <div id="tnewbox">${tnewOpen ? newTaskHtml() : ""}</div>
    <div class="tfil"><div class="chips tareas" role="group" aria-label="Areas">${wfAreas(ws).map(([k, l, n]) => `<button type="button" class="fchip ${wfArea === k ? "on" : ""}" data-warea="${esc(k)}">${esc(l)}<span>${nf(n)}</span></button>`).join("")}</div></div>
    <div class="wsearch tq">${ic.search}<input class="input" id="wfq" placeholder="Find a workflow" value="${esc(wfQuery)}" autocomplete="off"></div>
    <div id="wflist">${wfListHtml(v)}</div>
    ${wfTriggersHtml()}
    <div class="chips section"><a class="tag" href="#/measures">${ic.pulse}Measures of your records</a><a class="tag" href="#/trials">${ic.target}Benchmarks</a></div>`;
  $$("[data-warea]").forEach((b) => (b.onclick = () => { wfArea = wfArea === b.dataset.warea ? "" : b.dataset.warea; $$("[data-warea]").forEach((x) => x.classList.toggle("on", x.dataset.warea === wfArea)); $("#wflist").innerHTML = wfListHtml(v); }));
  $("#wfq").oninput = (e) => { wfQuery = e.target.value; $("#wflist").innerHTML = wfListHtml(v); };
  wfBindForms();
}
function wfAreas(ws) {
  const n = {};
  for (const w of ws) n[w.area] = (n[w.area] || 0) + 1;
  return Object.keys(n).sort((a, b) => (a === "standard" ? -1 : b === "standard" ? 1 : (FV?.areas?.[a] || a).localeCompare(FV?.areas?.[b] || b))).map((k) => [k, FV?.areas?.[k] || k, n[k]]);
}
function wfListHtml(v) {
  const q = wfQuery.trim().toLowerCase();
  const ws = (v.workflows || []).filter((w) => (!wfArea || w.area === wfArea) && (!q || `${w.name} ${w.trigger} ${w.result || ""}`.toLowerCase().includes(q)));
  if (!ws.length) return (v.workflows || []).length ? `<div class="card pad small muted">No workflow matches.</div>`
    : emptyState("Workflows come from the factories' n8n folders: each deploy brings them in.", `<a class="btn sm" href="#/guide/workflows">${ic.doc}How workflows come in</a>`);
  const facs = Object.keys(v.factories || {}).filter((f) => ws.some((w) => w.factory === f));
  return facs.map((f) => {
    const mine = ws.filter((w) => w.factory === f), areas = [...new Set(mine.map((w) => w.area))].sort((a, b) => (a === "standard" ? -1 : b === "standard" ? 1 : (v.areas[a] || a).localeCompare(v.areas[b] || b)));
    return `<div class="wf-factory"><div class="section-h"><h2>${esc(v.factories[f])} <span class="hcount">${nf(mine.length)}</span></h2>${f === "platform" ? `<span class="tiny faint">the stack's own upkeep</span>` : ""}</div>
      ${areas.map((a) => `<div class="hsub">${esc(v.areas[a] || a)}</div><div class="wf-cards">${mine.filter((w) => w.area === a).sort(wfOrder).map(wfCardHtml).join("")}</div>`).join("")}</div>`;
  }).join("");
}
const wfRank = (w) => (w.asks ? 0 : w.last_run?.state === "failed" ? 1 : ["running", "waiting"].includes(w.last_run?.state) || w.running ? 2 : 3);
const wfOrder = (a, b) => wfRank(a) - wfRank(b) || String(b.last_run?.started || "").localeCompare(String(a.last_run?.started || "")) || a.name.localeCompare(b.name);
function wfCardHtml(w) {
  const r = w.last_run, h = w.asks ? "needs" : r?.state === "failed" ? "bad" : ["running", "waiting"].includes(r?.state) || w.running ? "live" : "idle";
  const next = w.next_run ? `next ${when(typeof w.next_run === "number" ? w.next_run : w.next_run)}` : "";
  return `<a class="card agcard wfcard h-${h}" href="${wfHref(w)}"><div class="agic">${w.source === "standard" ? ic.layers : ic.flow}</div><div class="agbody">
    <div class="agrow"><b class="agt">${esc(w.name)}</b>${w.source === "n8n" && !w.active ? `<span class="tchip">off</span>` : ""}</div>
    <div class="tmeta"><span class="tchip area a-${esc(w.area)}">${esc(FV?.areas?.[w.area] || w.area)}</span><span class="tchip">${ic.clock}${esc(triggerWords(w))}</span>${w.asks ? `<span class="tchip warn">${nf(w.asks)} Ask${w.asks === 1 ? "" : "s"} open</span>` : ""}</div>
    <div class="small wfline">${r ? `${runPill(r.state)} <span class="muted">${w.source === "standard" ? `${nf(w.runs_total)} runs · ` : ""}last ${esc(when(r.started))}</span>` : `<span class="muted">no run yet</span>`}${next ? ` <span class="muted">· ${esc(next)}</span>` : ""}</div>
    ${w.result ? `<div class="small agres ${r?.state === "failed" ? "err-t" : ""}">${prose(oneLine(w.result))}</div>` : ""}</div></a>`;
}

// ---------- the diagram (APP-72): nodes and connections as n8n has them, laid out in layers, readable on a phone ----------
const NODE_WORD = { scheduleTrigger: "Trigger", webhook: "Trigger", manualTrigger: "Trigger", trigger: "Trigger", if: "If", switch: "Switch", merge: "Merge",
  set: "Set values", code: "Code", httpRequest: "Web call", wait: "Wait", noOp: "Nothing", aistackStep: "Step" };
const STEP_KIND = { agent: "Agent step", crew: "Scheduled job", task: "Agent steps", ask: "Ask", notify: "Message to you", tracker: "Ticket write", wait_item: "Waits for a reply" };
// APP-81: a node's name in the owner's words: a trigger with when it fires ("On its schedule · Mondays 08:00", never its
// cron), a step by what it does (the server names a step that holds a request's own steps)
const nodeTitle = (n) => { const t = n.title || n.name; return n.trigger && n.trigger !== t ? `${t} · ${n.trigger}` : t; };
function nodeSub(n) {
  if (n.trigger) return "Trigger";
  if (n.type === "aistackStep") {
    const who = n.agent ? agentName(n.agent) : n.job ? (S?.crew || []).find((c) => c.id === n.job)?.name || n.job : "";
    return [STEP_KIND[n.kind] || "Step", who].filter(Boolean).join(" · ");
  }
  return NODE_WORD[n.type] || n.type;
}
function graphLayout(g) {                                   // each node's layer: its longest way from a trigger
  const names = g.nodes.map((n) => n.name), into = Object.fromEntries(names.map((n) => [n, []])), out = Object.fromEntries(names.map((n) => [n, []]));
  for (const [a, b] of g.edges) { if (out[a] && into[b]) { out[a].push(b); into[b].push(a); } }
  const layer = {};
  for (const n of names.filter((x) => !into[x].length)) layer[n] = 0;
  for (let pass = 0; pass < names.length; pass++) {             // the longest way, at most one pass a node: a loop back cannot run forever
    let moved = false;
    for (const [a, b] of g.edges) if (layer[a] != null && (layer[b] == null || layer[b] < layer[a] + 1) && layer[a] + 1 < names.length) { layer[b] = layer[a] + 1; moved = true; }
    if (!moved) break;
  }
  for (const n of names) if (layer[n] == null) layer[n] = 0;
  const byL = [];
  for (const n of g.nodes) (byL[layer[n.name]] ??= []).push(n);
  for (const l of byL) l?.sort((a, b) => (a.at?.[1] ?? 0) - (b.at?.[1] ?? 0) || (a.at?.[0] ?? 0) - (b.at?.[0] ?? 0));
  return byL.filter(Boolean);
}
// path: {step title or node name: state} for a run (null: the workflow itself, no state)
function diagramInto(box, g, path = null, onPick = null) {
  if (!box) return;
  if (!g?.nodes?.length) { box.innerHTML = `<div class="card pad small muted">Its diagram comes with the runner's next view of the workflows.</div>`; return; }
  const cs = getComputedStyle(box), W = Math.max(260, (box.clientWidth || 340) - parseFloat(cs.paddingLeft || 0) - parseFloat(cs.paddingRight || 0) - 4);
  const layers = graphLayout(g), wide = Math.min(210, (W - 40 * (layers.length - 1) - 8) / layers.length);   // the desk: every layer side by side when each gets 130 px
  const vertical = W < 640 || wide < 130, LH = 13, PAD = 10, GAPL = vertical ? 34 : 40, GAPN = 12, NW = vertical ? Math.min(300, W - 8) : wide;
  const fits = (cls, w) => (s) => svgTextWidth(s, cls, box) <= w - 2 * PAD;
  const at = {};
  const stateOf = (n) => (path ? path[n.title || n.name] ?? path[n.name] : null);
  const ran = new Set(g.nodes.filter((n) => stateOf(n)).map((n) => n.name));
  if (path) {                                                 // what led to a step that ran was on its path too
    let grew = true;
    while (grew) { grew = false; for (const [a, b] of g.edges) if (ran.has(b) && !ran.has(a)) { ran.add(a); grew = true; } }
  }
  const lines = (n, w) => {                                    // a node's lines at its width, and its height for all of them
    n._w = w; n._t = wrapWords(nodeTitle(n), fits("tml", w)); n._s = wrapWords(nodeSub(n), fits("tms", w));
    n._h = PAD * 2 + n._t.length * LH + n._s.length * (LH - 1) + 2;
  };
  for (const n of g.nodes) lines(n, NW);
  let H = 0, Wd = 0;
  if (vertical) {                                             // top to bottom, a layer's nodes side by side when they fit
    let y = 4;
    for (const l of layers) {
      const per = Math.max(1, Math.min(l.length, Math.floor((W + GAPN) / (Math.min(NW, (W - GAPN * (l.length - 1)) / l.length) + GAPN))));
      const nw = l.length > 1 ? Math.max(130, Math.min(NW, (W - GAPN * (Math.min(l.length, per) - 1)) / Math.min(l.length, per))) : NW;
      for (let i = 0; i < l.length; i += per) {
        const row = l.slice(i, i + per);
        if (nw !== NW) row.forEach((n) => lines(n, nw));   // narrower side by side: wrapped again, as tall as its lines need
        const rh = Math.max(...row.map((n) => n._h)), rw = row.length * nw + (row.length - 1) * GAPN;
        row.forEach((n, j) => { at[n.name] = { x: (W - rw) / 2 + j * (nw + GAPN), y, h: n._h }; });
        y += rh + (i + per < l.length ? GAPN : GAPL);
      }
    }
    H = y - GAPL + 6; Wd = W;
  } else {                                                    // left to right, a layer a column
    let x = 4;
    for (const l of layers) {
      let y = 4;
      for (const n of l) { n._w = NW; at[n.name] = { x, y, h: n._h }; y += n._h + GAPN; }
      H = Math.max(H, y); x += NW + GAPL;
    }
    Wd = x - GAPL + 6;
  }
  const cls = (n) => { const s = stateOf(n); return `wfn${n.trigger ? " trig" : n.type === "aistackStep" ? ` k-${esc(n.kind || "agent")}` : " own"}${path ? (s ? ` st-${esc(s)}` : ran.has(n.name) ? " st-done" : " st-off") : ""}`; };
  const edge = ([a, b, i]) => {
    const p = at[a], q = at[b];
    if (!p || !q) return "";
    const A = g.nodes.find((n) => n.name === a), B = g.nodes.find((n) => n.name === b), on = path && ran.has(a) && ran.has(b);
    const ifWord = A?.type === "if" ? (i === 0 ? "yes" : "no") : "";
    let d, lx, ly;
    if (vertical) { const x1 = p.x + A._w / 2, y1 = p.y + p.h, x2 = q.x + B._w / 2, y2 = q.y, m = (y1 + y2) / 2; d = `M${x1},${y1} C${x1},${m} ${x2},${m} ${x2},${y2 - 4}`; lx = x1 + 6; ly = y1 + 12; }
    else { const x1 = p.x + A._w, y1 = p.y + p.h / 2, x2 = q.x, y2 = q.y + q.h / 2, m = (x1 + x2) / 2; d = `M${x1},${y1} C${m},${y1} ${m},${y2} ${x2 - 4},${y2}`; lx = x1 + 4; ly = y1 - 5; }
    return `<path d="${d}" class="wfe${on ? " on" : path ? " off" : ""}" marker-end="url(#wfarrow${on ? "on" : ""})"/>${ifWord ? `<text x="${lx}" y="${ly}" class="tms wfel">${ifWord}</text>` : ""}`;
  };
  box.innerHTML = `<div class="wfd-wrap"><svg class="wfd tmapsvg" viewBox="0 0 ${Wd} ${H}" width="${Wd}" height="${H}" role="img" aria-label="The workflow's diagram">
    <defs><marker id="wfarrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 Z" class="wfah"/></marker>
      <marker id="wfarrowon" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 Z" class="wfah on"/></marker></defs>
    ${g.edges.map(edge).join("")}
    ${g.nodes.map((n) => { const p = at[n.name]; return `<g class="${cls(n)}" data-wfn="${esc(n.name)}" tabindex="0" role="button" transform="translate(${p.x},${p.y})"><title>${esc(nodeTitle(n))}</title>
      <rect width="${n._w}" height="${p.h}" rx="10"/><text class="tml">${svgTspans(n._t, PAD, PAD + 10, LH)}</text><text class="tms">${svgTspans(n._s, PAD, PAD + 10 + n._t.length * LH, LH - 1)}</text></g>`; }).join("")}
  </svg></div>`;
  $$("[data-wfn]", box).forEach((el) => (el.onclick = el.onkeydown = (e) => {
    if (e.type === "keydown" && e.key !== "Enter") return;
    $$("[data-wfn]", box).forEach((x) => x.classList.toggle("pick", x === el));
    onPick?.(g.nodes.find((n) => n.name === el.dataset.wfn));
  }));
}
// a node's facts under the diagram: what it is, who does it, and (on a run's page) how it went
function nodeInfoHtml(n, step = null) {
  if (!n) return "";
  const who = n.agent ? `<a href="${agentHref(n.agent)}">${esc(agentName(n.agent))}</a>` : n.job ? `<a href="#/crew/${encodeURIComponent(n.job)}">${esc((S?.crew || []).find((c) => c.id === n.job)?.name || n.job)}</a>` : "";
  return `<div class="card pad wfinfo"><div class="tiny faint">${esc(nodeSub(n))}</div><div class="ttl wrap" style="margin-top:4px">${esc(nodeTitle(n))}</div>${n.inside ? `<div class="small muted" style="margin-top:4px">Its own steps (work out the steps, research, write, check) run inside this one step until phase B moves them onto n8n; its run's record shows each of them.</div>` : ""}
    ${who ? `<div class="small" style="margin-top:4px">Done by ${who}</div>` : ""}
    ${step ? `<div class="small row wrap gap-2" style="margin-top:6px">${runPill(step.state)}${step.started ? `<span class="muted">${esc(clock(step.started))}${step.ended ? `–${esc(clock(step.ended))}` : ""}</span>` : ""}</div>` : ""}</div>`;
}
const agentHref = (id) => `#/agent/${encodeURIComponent(id)}`;

// ---------- a workflow's page (APP-72) ----------
async function vWorkflow() {
  const wid = route.args[0] || "";
  view.innerHTML = `<a class="back" href="#/workflows">${ic.back}Workflows</a><div class="stack"><div class="skeleton" style="height:96px"></div><div class="skeleton" style="height:280px"></div></div>`;
  const d = await api(`/api/factory/workflow/${encodeURIComponent(wid)}`).catch((e) => ({ error: e.message }));
  if (route.name !== "workflow" || route.args[0] !== wid) return;
  if (!d || d.error || !d.workflow) { view.innerHTML = `<a class="back" href="#/workflows">${ic.back}Workflows</a>${emptyState(esc(d?.error || "No such workflow."), `<a class="btn sm" href="#/workflows">${ic.flow}All workflows</a>`)}`; return; }
  const w = d.workflow, runs = d.runs || [], fac = FV?.factories?.[w.factory] || w.factory, area = FV?.areas?.[w.area] || w.area;
  view.innerHTML = `<a class="back" href="#/workflows">${ic.back}Workflows</a>
    <div class="hero"><div class="grow" style="min-width:0"><h1 class="wrap">${esc(w.name)}</h1><p>${esc(fac)} · ${esc(area)} · ${esc(triggerWords(w))}${w.source === "n8n" ? ` · ${w.active ? "on" : "off"}` : ""}${w.asks ? ` · <b class="warn-t">${nf(w.asks)} Ask${w.asks === 1 ? "" : "s"} open</b>` : ""}</p></div>
      <div class="row gap-2 wrap">${wfRunNow(w)}</div></div>
    <div class="agstrip" id="wfagents">${wfAgentsHtml(w)}</div>
    <div id="tnewbox"></div>
    <div class="section-h"><h2>Diagram</h2>${w.source === "n8n" && wfDesk() ? `<button class="btn sm" id="wfedit">${ic.edit}Edit</button>` : ""}${explain("wf-diagram", w.source === "standard" ? "A standard workflow of the platform: its steps as its template has them. The runs below came in through the stack's older ways in (a sentence, a Claude question, a chat request, a build); each will start through this workflow on n8n." : "Its nodes and connections as n8n has them: a trigger starts it, each AI Stack step hands its work to an agent or a scheduled job and waits for the answer. Tap a node for what it is.", "About the diagram")}</div>
    <div class="card pad wfdcard" id="wfdiagram"></div><div id="wfinfo"></div>
    ${wfResultHtml(w, runs)}
    <div class="section-h section"><h2>Runs <span class="hcount">${nf(d.runs_total || runs.length)}</span></h2></div>
    ${runs.length ? `<div class="card list">${runs.map((r) => wfRunRow(w, r)).join("")}</div>${moreOf(d.runs_total || runs.length, runs.length)}` : `<div class="card pad small muted">No run yet: ${w.source === "standard" ? "each new request of this kind shows here." : "its first run shows here as it starts."}</div>`}
    <div class="section-h section"><h2>Settings</h2>${w.source === "n8n" ? explain("wf-settings", "Its schedule and its on/off switch are n8n's: change them on its canvas (its schedule trigger, its Active switch), on the desk under Edit in n8n. Each change is exported to git like every other.", "Where to change it") : ""}</div>${wfSettingsHtml(w)}`;
  if (w.source === "n8n") canvasInto($("#wfdiagram"), w); else diagramInto($("#wfdiagram"), w.graph, null, (n) => { $("#wfinfo").innerHTML = nodeInfoHtml(n); });
  wfBindRunNow(w);
  if ($("#wfedit")) $("#wfedit").onclick = () => editInto($("#wfdiagram"), w);
  swWhoCards().then((cards) => { const el = $("#wfagents"); if (el && route.name === "workflow") el.innerHTML = wfAgentsHtml(w, cards); }).catch(() => {});
  if (w.result_view === "tax" && typeof taxViewInto === "function") taxViewInto($("#wfresult"), { id: (runs[0] || {}).task });
}
// APP-84: "Agents in this workflow", right under its title: every agent a step names, and the agent whose card holds a
// scheduled job a step runs (known once the agents' cards are read), each one tap from its page
function wfAgentsHtml(w, cards = []) {
  const ids = new Set([...(w.agents || []), ...(w.graph?.nodes || []).map((n) => n.agent).filter(Boolean)]);
  const jobs = [...(w.jobs || []), ...(w.graph?.nodes || []).map((n) => n.job).filter(Boolean)];
  for (const j of jobs) { const c = (cards || []).find((x) => (x.jobs || []).some((k) => k === j || k === `crew-${j}`)); if (c) ids.add(c.id); }
  if (!ids.size) return "";
  return `<span class="small muted">Agents in this workflow</span>${[...ids].map((a) => `<a class="agchip" href="${agentHref(a)}">${ic.brain}${esc(agentName(a))}</a>`).join("")}`;
}
function wfRunNow(w) {
  if (w.source === "standard") return w.id === "change" ? `<a class="btn primary" href="#/build">${ic.plus}Request a change</a>` : `<button class="btn primary" data-wfnew="${w.id === "briefing" ? "briefing" : ""}">${ic.plus}${w.id === "briefing" ? "New briefing" : "New request"}</button>`;
  const [k, key] = String((w.page || "").replace(/^#\//, "")).split("/");
  if (k === "crew") return `<button class="btn primary" data-crun="${esc(decodeURIComponent(key))}">${ic.play}Run now</button>`;
  if (k === "task") return `<button class="btn primary" data-trun="${esc(key)}">${ic.play}Run now</button>`;
  return "";
}
function wfBindRunNow(w) {
  $$("[data-wfnew]").forEach((b) => (b.onclick = () => {
    tnewOpen = true; route.q = new URLSearchParams(b.dataset.wfnew ? { kind: b.dataset.wfnew } : {});
    $("#tnewbox").innerHTML = newTaskHtml(); tnewClose = () => { $("#tnewbox").innerHTML = ""; }; bindNewTask(); $("#tnew")?.scrollIntoView({ block: "start" });
  }));
  bindCrew(); bindTasks();
}
// ---------- a run's page (APP-73): the diagram with the path it took, its steps, its Asks, its cost and its result ----------
async function vRun() {
  const [wid, rid] = route.args;
  const back = `<a class="back" href="#/workflow/${encodeURIComponent(wid || "")}">${ic.back}Its workflow</a>`;
  view.innerHTML = `${back}<div class="stack"><div class="skeleton" style="height:96px"></div><div class="skeleton" style="height:280px"></div></div>`;
  const d = await api(`/api/factory/run/${encodeURIComponent(wid || "")}/${encodeURIComponent(rid || "")}`).catch((e) => ({ error: e.message }));
  if (route.name !== "run" || route.args[1] !== rid) return;
  if (!d || d.error || !d.run) { view.innerHTML = `${back}${emptyState(esc(d?.error || "No such run."), `<a class="btn sm" href="#/workflows">${ic.flow}All workflows</a>`)}`; return; }
  const w = d.workflow, r = d.run, by = runBy(r), open = (d.asks || []).filter((a) => ["open", "escalated"].includes(a.status));
  const steps = w.source === "standard" ? (w.graph.nodes || []).filter((n) => !n.trigger).map((n) => ({ title: n.name, agent: n.agent, state: r.path?.[n.name] }))
    : (r.steps || []).length ? r.steps.map((s) => ({ ...s, state: s.state }))
    : (w.graph.nodes || []).filter((n) => n.type === "aistackStep").map((n) => ({ title: n.title || n.name, agent: n.agent, state: r.path?.[n.title || n.name] }));   // APP-80: a run only its record holds
  const cost = [r.tokens ? `${tok(r.tokens)} tokens` : "", r.cost ? ifPaid(r.cost) : ""].filter(Boolean).join(" · ");
  view.innerHTML = `${back}
    <div class="hero"><div class="grow" style="min-width:0"><h1 class="wrap">${esc(w.source === "standard" ? r.title || w.name : w.name)}</h1>
      <p>${runPill(r.state)} ${esc(w.source === "standard" ? `a run of ${w.name}` : `run ${r.occ || r.id}`)} · started ${esc(dt(r.started))}${r.ended ? ` · ended ${esc(clock(r.ended))}` : ""}${by ? ` · ${esc(by)}` : ""}</p></div></div>
    ${open.length ? `<div class="section-h"><h2>Needs you <span class="hcount">${nf(open.length)}</span></h2></div><div class="stack">${open.map((a) => askCard(a)).join("")}</div>` : ""}
    <div class="section-h${open.length ? " section" : ""}"><h2>The path it took</h2>${explain("run-path", "The workflow's diagram with this run on it: what it did is lit, what runs or waits for you is marked, what it never reached is faded. Tap a node for its step.", "About the path")}</div>
    <div class="card pad wfdcard" id="wfdiagram"></div><div id="wfinfo"></div>
    <div class="section-h section"><h2>Steps</h2></div>
    ${steps.length ? `<div class="card list">${steps.map((s) => `<div><div class="ic ${s.state === "failed" ? "err" : ["running", "waiting"].includes(s.state) ? "run" : ""}">${s.state === "done" ? ic.check : s.state === "failed" ? ic.x : ic.clock}</div>
      <div class="grow" style="min-width:0"><div class="ttl wrap">${esc(s.title)}</div><div class="sub wrap">${s.state ? runPill(s.state) : `<span class="muted">not reached</span>`}${s.agent ? ` · <a href="${agentHref(s.agent)}">${esc(agentName(s.agent))}</a>` : ""}${s.started ? ` · ${esc(clock(s.started))}${s.ended ? `–${esc(clock(s.ended))}` : ""}` : ""}</div></div></div>`).join("")}</div>`
      : `<div class="card pad small muted">No step has reached the stack yet.</div>`}
    ${r.result ? `<div class="section-h section"><h2>Result</h2></div><div class="card pad"><div class="small md">${md(youText(r.result))}</div></div>` : ""}
    <div class="row wrap gap-2 section">${cost ? `<span class="small muted">${esc(cost)}</span>` : ""}${r.href ? `<a class="btn sm" href="${r.href}">${ic.history}Its whole record: each step's log, what it read</a>` : ""}${wfDesk() && r.execution ? `<a class="btn sm ghost" href="#/n8n?open=${encodeURIComponent(w.id)}">${ic.edit}In n8n</a>` : ""}</div>`;
  const ours = () => diagramInto($("#wfdiagram"), w.graph, r.path || {}, (n) => { $("#wfinfo").innerHTML = nodeInfoHtml(n, steps.find((s) => s.title === (n.title || n.name))); });
  if (w.source === "n8n" && /^\d+$/.test(r.execution || "")) executionInto($("#wfdiagram"), w, r, ours); else ours();
  bindAsks();
}
function wfRunRow(w, r) {
  const by = runBy(r);
  return `<a href="${runHref(w.id, r.id)}"><div class="ic ${r.state === "failed" ? "err" : ["running", "waiting"].includes(r.state) ? "run" : ""}">${r.state === "failed" ? ic.x : ["running", "waiting"].includes(r.state) ? ic.pulse : ic.check}</div>
    <div class="grow" style="min-width:0"><div class="ttl wrap">${esc(w.source === "standard" ? r.title || w.name : r.occ ? `Run ${r.occ}` : r.execution ? `Run ${r.execution}` : "A run on its schedule")}</div>
      <div class="sub wrap">${runPill(r.state)} ${esc(when(r.started))}${by ? ` · ${esc(by)}` : ""}${r.asks ? ` · <b class="warn-t">${nf(r.asks)} Ask${r.asks === 1 ? "" : "s"}</b>` : ""}</div>
      ${r.result ? `<div class="sub wrap">${prose(oneLine(r.result))}</div>` : ""}</div>${ic.next}</a>`;
}
function wfResultHtml(w, runs) {                            // its result view: the taxes, the mail, a briefing's report, or its newest result
  if (w.source === "standard") return "";                   // a template's runs are each their own request: each run's page has its result
  if (w.result_view === "tax") return `<div class="section-h section"><h2>Your taxes</h2></div><div id="wfresult"><div class="skeleton" style="height:160px"></div></div>`;
  const mail = ["mail-sort", "postmaster", "inbox"].some((j) => (w.jobs || []).includes(j));
  const last = runs.find((r) => r.state === "done" && r.result);
  if (!mail && !last && !w.page) return "";
  return `<div class="section-h section"><h2>Result</h2></div><div class="card pad">${last ? `<div class="small">${prose(oneLine(last.result, 400))}</div><div class="tiny faint" style="margin-top:4px">${esc(when(last.ended || last.started))}</div>` : `<div class="small muted">No result yet.</div>`}
    <div class="row wrap gap-2" style="margin-top:8px">${mail ? `<a class="btn sm" href="#/mail">${ic.wiki}Your mail</a>` : ""}${last ? `<a class="btn sm" href="${runHref(w.id, last.id)}">${ic.next}Its run</a>` : ""}${w.page ? `<a class="btn sm ghost" href="${w.page}">${ic.history}Its records and files</a>` : ""}</div></div>`;
}
function wfSettingsHtml(w) {
  if (w.source === "standard") return `<div class="card pad small muted">A template of the platform: its steps change with the platform, and a factory can adopt it as it is or override it with its own version.</div>`;
  return `<div class="card pad"><div class="row between wrap gap-2"><div><b class="small">${esc(triggerWords(w))}</b><div class="tiny muted">${w.next_run ? `next ${esc(when(w.next_run))}` : w.active ? "no run comes on a schedule" : "switched off: it does not run until it is switched on"}</div></div>
      <span class="pill ${w.active ? "ok" : "archived"}">${w.active ? "on" : "off"}</span></div></div>`;
}

// the Workflows page's forms: a new request (Run now of Request) and the triggers that start one on an event (TSK-10)
function wfTriggersHtml() {
  return `<details class="section card pad" data-keep="trules"><summary class="row between" style="gap:8px"><b>Triggers · ${(S?.bus?.rules || []).length}</b><span class="tiny faint">a new request each time something happens</span></summary>
    <div id="trigboard" style="margin-top:10px">${S ? trigBoardHtml() : ""}</div>${S ? ruleFormHtml() : ""}</details>`;
}
function wfBindForms() {
  const open = () => { tnewOpen = true; $("#tnewbox").innerHTML = newTaskHtml(); bindNewTask(); $("#tnew")?.scrollIntoView({ block: "start" }); };
  tnewClose = () => { const b = $("#tnewbox"); if (b) b.innerHTML = ""; };
  $("#tnewb").onclick = open;
  if (tnewOpen) bindNewTask();
  if (S) bindTriggers();
}

// ---------- n8n's own canvas (APP-86; the factory design v3, §4 B) ----------
// Read mode: n8n's read-only demo canvas (/n8n/workflows/demo), on the app's own address, so it is this page's own
// document: the app hands it the workflow (n8n's published version, read with the app's session, APP-85) by
// postMessage once it says n8nReady. On a phone the frame is wider than the screen and pans sideways at a readable size
// instead of fitting a small picture. Edit: n8n's editor on the workflow's draft in the same frame; its Publish and
// Execute are hidden here and refused by the app (a draft goes live through the factory); Done comes back. A run with
// an n8n execution shows n8n's own view of it. When n8n cannot be reached the app draws the diagram itself.
// The live layer (phase B, §4 B) attaches through CANVAS_LAYERS: each fn(doc, {workflow, run}) runs once n8n drew.
const CANVAS_LAYERS = [canvasAgentLinks];
const N8N_HIDE = `[data-test-id="workflow-open-publish-modal-button"], [data-test-id="workflow-open-publish-modal-button"] + button,
  [data-test-id^="execute-workflow-button"], [data-test-id="execute-node-button"], [data-test-id="workflow-menu"],
  [data-test-id="execution-preview-delete-button"], [data-test-id="execution-debug-button"] { display: none !important; }`;
const N8N_PHONE_W = 150;                                 // a node's room on a phone, so a workflow reads at its size and pans sideways
function canvasFallback(box, w, why) {
  box.innerHTML = `<div class="tiny faint">${esc(why)}</div><div id="wfdraw"></div>`;
  diagramInto($("#wfdraw", box), w.graph, null, (n) => { const i = $("#wfinfo"); if (i) i.innerHTML = nodeInfoHtml(n); });
}
async function canvasInto(box, w, run = null) {
  if (!box) return;
  box.innerHTML = `<div class="skeleton" style="height:260px"></div>`;
  const d = await api(`/api/factory/workflow/${encodeURIComponent(w.id)}/canvas`).catch((e) => ({ error: e.message, fallback: true }));
  if (!box.isConnected) return;
  if (!d || d.fallback || !d.workflow) return canvasFallback(box, w, d?.login ? "n8n's own canvas shows once its login is stored (make n8n-login on the PC); until then the app draws it." : `n8n's canvas is not there (${d?.error || "no answer"}); the app draws it for now.`);
  const wide = wfDesk() ? 0 : Math.max(box.clientWidth || 0, (d.workflow.nodes || []).length * N8N_PHONE_W);
  box.innerHTML = `<div class="n8n-wrap"><iframe class="n8n-canvas" src="/n8n/workflows/demo" title="${esc(w.name)}: n8n's canvas"${wide ? ` style="width:${wide}px"` : ""}></iframe></div>
    ${d.draft_differs ? `<div class="tiny faint" style="margin-top:6px">A saved draft differs from what runs; this is what runs.</div>` : ""}`;
  const f = $("iframe", box);
  let sent = false;
  const send = () => {
    if (sent || !f.isConnected) return;
    sent = true;
    window.removeEventListener("message", ready);
    f.contentWindow.postMessage(JSON.stringify({ command: "openWorkflow", workflow: d.workflow }), "*");
    afterDraw(f, w, run);
  };
  const ready = (e) => { if (e.source !== f.contentWindow) return; try { if (JSON.parse(e.data).command === "n8nReady") send(); } catch (_) { /* not n8n's */ } };
  window.addEventListener("message", ready);
  setTimeout(send, 8000);                                  // an n8n that said nothing: hand it over all the same
}
function afterDraw(f, w, run, tries = 0) {                 // once n8n drew its nodes: the layers (the agents' links; later the live run)
  const doc = f.contentDocument;
  if (!doc?.querySelector(".vue-flow__node")) { if (tries < 40) setTimeout(() => afterDraw(f, w, run, tries + 1), 300); return; }
  for (const fn of CANVAS_LAYERS) { try { fn(doc, { workflow: w, run }); } catch (_) { /* a layer that cannot attach leaves the canvas as n8n drew it */ } }
}
function canvasAgentLinks(doc) {                          // an AI Stack step's subtitle "Agent: <id>" opens that agent's page in the app
  for (const el of doc.querySelectorAll('[class*="_subtitle_"]')) {
    const m = /^Agent: ([\w-]+)/.exec((el.textContent || "").trim());
    if (!m || el.dataset.agentLink) continue;
    el.dataset.agentLink = m[1];
    el.style.textDecoration = "underline";
    el.style.cursor = "pointer";
    el.title = "Open this agent's page";
    el.addEventListener("click", (e) => { e.stopPropagation(); location.hash = agentHref(m[1]); }, true);
  }
}
function n8nHide(f) {                                     // Publish and Execute are the factory's, not the editor's (the app refuses them too)
  const quiet = (d) => {                                   // n8n's own "Production Checklist" popover (no selector of its own) points at publishing
    for (const el of d.body?.children || []) if (/^Production Checklist/.test((el.innerText || "").trim())) el.style.display = "none";
  };
  const put = () => {
    const d = f.contentDocument;
    if (!d?.head || d.getElementById("aistack-hide")) return;
    d.head.insertAdjacentHTML("beforeend", `<style id="aistack-hide">${N8N_HIDE}</style>`);
    new (f.contentWindow.MutationObserver)(() => quiet(d)).observe(d.body, { childList: true });
    quiet(d);
  };
  f.addEventListener("load", put);
  put();
}
function editInto(box, w) {                               // the workflow's draft in n8n's editor, in the same frame
  box.innerHTML = `<div class="row between wrap gap-2" style="margin-bottom:8px"><span class="small muted">You edit a draft. It goes live through the factory: as a change in git, with its checks and your approval; publishing from here is off.</span>
      <button class="btn sm primary" id="wfdone">${ic.check}Done</button></div>
    <iframe class="n8n-canvas edit" src="/n8n/workflow/${encodeURIComponent(w.id)}" title="${esc(w.name)}: its draft in n8n's editor"></iframe>`;
  n8nHide($("iframe", box));
  $("#wfdone").onclick = () => canvasInto(box, w);
  if (typeof APP_PROMOTE === "function") APP_PROMOTE(box, w);   // the promote path (draft -> change -> checks -> gate -> publish) attaches here, after its own design
}
async function executionInto(box, w, r, fallback) {        // a run's page: n8n's own view of its execution, each node's input and output
  const d = await api(`/api/factory/workflow/${encodeURIComponent(w.id)}/canvas`).catch(() => null);
  if (!box.isConnected) return;
  if (!d || d.fallback) return fallback();
  box.innerHTML = `<iframe class="n8n-canvas run" src="/n8n/workflow/${encodeURIComponent(w.id)}/executions/${encodeURIComponent(r.execution)}" title="Run ${esc(r.execution)} in n8n"></iframe>`;
  n8nHide($("iframe", box));
}
const APP_PROMOTE = null;

