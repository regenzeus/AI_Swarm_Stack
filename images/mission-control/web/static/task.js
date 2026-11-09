// APP-35, APP-36: a task's own page (#/task/<id>), like an agent's. It opens on the result and then tells how it came
// about, most important first: the answer, who worked on it (a map of the agents, their part and their hand-offs), whether
// it met its definition of done, what went wrong, what it read (its sources), what it read from and kept in memory, what
// it made, what it cost and how long it took, and the plan. Each part opens its own tab for the whole of it.
// The runner writes the task's data (public/tasks/<id>.json, ops/tasks.py publish); the run record adds the agents, their
// actions, hand-offs and memory use (runrecord.task_activity); the run's swarm map adds its sources and what it made
// (server.task_prov). A recurring task shows one run at a time: its newest, or the one you pick.
// Loaded before app.js: it uses app.js's helpers only when a page is drawn.
let taskData = {}, ttab = "overview", taskTimer = null, taskAgent = "", taskOcc = {}, taskSrc = "all", taskUnfold = false;
const TTABS = [["overview", "Overview"], ["agents", "Agents"], ["timeline", "Timeline"], ["sources", "Sources"], ["memory", "Memory"], ["runs", "Runs"]];
const TPILL = { done: "ok", failed: "failed", cancelled: "archived", running: "running", scheduled: "active", needs_answer: "paused",
  waiting_approval: "paused", waiting_owner: "paused", intake: "running", planning: "running", after: "queued" };
const TACT = { run: "started", call: "used", say: "said", error: "error", stage: "stage", propose: "proposed", read: "read", wait: "waits", end: "ended" };
const LIVE_T = ["intake", "planning", "running", "needs_answer", "waiting_approval", "waiting_owner", "after"];
// an agent's part in the task, as the map colours it (validated: blue, orange, aqua; dark and light, all pairs)
const TPART = { coord: ["var(--tp-coord)", "planned it or ran the plan"], step: ["var(--tp-step)", "did a step"], call: ["var(--tp-call)", "called in by another agent"] };
const TVERB = { started: "gave a step to", called: "called in", handed: "handed its results to", planned: "made the plan for", checked: "had the plan checked by" };
const MSTORE = { wiki: ["Wikis", "the topic's, the missions' and your vault's wiki pages"], notes: ["Your notes", "the vault: its searches and files"],
  journal: ["Journals", "the agents' work journals"], "long-term": ["Long-term memory", "Hindsight's facts about you and the stack"],
  board: ["The swarm's board", "the ledger: the ideas, findings and messages agents share"], lessons: ["Lessons", "the agents' notes to themselves"] };
const TSKIND = { page: "web page", item: "news item", job: "job ad", note: "note", memory: "memory", search: "search" };
const TMADE = { result: "The answer", report: "Reports", wiki: "Wiki pages", file: "Files written", delivery: "Delivered", finding: "Step findings" };

function taskAgentHref(a) {                       // a run's agent -> its page in the app, where it has one
  const s = String(a || "");
  if (s.startsWith("mission:")) return `#/mission/${encodeURIComponent(s.slice(8))}`;
  if (s.startsWith("crew:")) return `#/crew/${encodeURIComponent(s.slice(5))}`;
  const id = { "claude-builder": "builder", "claude-task": "claude", "ai-phone": "phone" }[s] || s;
  return typeof swAgentHref === "function" ? swAgentHref(id) : "";
}
const taskWho = (a) => (typeof agentName === "function" && agentName(a)) || a;
// a tool's name without its server's prefix: mcp__vault__swarm_swarm_context -> swarm_context
const taskTool = (t) => String(t || "").split("__").pop().replace(/^([a-z]+)_\1_/, "$1_");
const TKEYS = ["query", "q", "question", "path", "url", "text", "summary", "title", "message", "command", "file_path"];
function taskDetail(d) {                          // a call's arguments as words: its main field first, then the rest as key: value
  const s = String(d || "").trim();
  if (!s.startsWith("{")) return s;
  try {
    const o = JSON.parse(s), k = TKEYS.find((x) => typeof o[x] === "string" && o[x]);
    const rest = Object.entries(o).filter(([x, v]) => x !== k && v !== "" && v != null && x !== "idem");
    return [k ? o[k] : "", ...rest.map(([x, v]) => `${x}: ${typeof v === "string" ? v : JSON.stringify(v)}`)].filter(Boolean).join(" · ") || "no arguments";
  } catch (_) { return s; }                       // the record keeps a long one cut: shown as it is
}
function taskRow(e, what) {
  const label = TACT[e.kind] || e.kind, title = e.kind === "call" ? taskTool(e.title) : e.title || "", det = taskDetail(e.detail);
  return `<a class="tact k-${esc(e.kind)}" href="#/live/${encodeURIComponent(e.run)}"><div class="tact-h"><span class="tiny faint mono">${esc(clock(new Date(e.ts * 1000).toISOString(), true))}</span>
    <span class="tag">${esc(taskWho(e.agent))}</span><b>${esc(what || (title.toLowerCase() === label ? label : `${label} ${title}`))}</b></div>${det ? `<div class="tact-d tiny faint wrap">${esc(det)}</div>` : ""}</a>`;
}
const taskMemHref = (p) => (/^[\w.-]+(\/[\w.-]+)*\.md$/.test(p || "") ? `#/read?path=${encodeURIComponent(p)}` : "");
const taskSrcHref = (s) => (/^https?:/.test(s.uri) ? s.uri : s.uri.startsWith("vault:") ? taskMemHref(s.uri.slice(6)) : "");
const taskLink = (href, html) => (!href ? html : /^https?:/.test(href) ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${html}</a>` : `<a href="${esc(href)}">${html}</a>`);

async function vTask() {
  clearTimeout(taskTimer);
  const id = +route.args[0];
  if (!id) { view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div class="card empty">No task named. <a href="#/tasks">All tasks</a></div>`; return; }
  if (route.q.get("tab")) { ttab = TTABS.some(([k]) => k === route.q.get("tab")) ? route.q.get("tab") : "overview"; route.q.delete("tab"); }
  if (+route.q.get("o")) { taskOcc[id] = +route.q.get("o"); route.q.delete("o"); }
  if (!taskData[id]) view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div class="stack"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:320px"></div></div>`;
  const d = await api(`/api/task/${id}${taskOcc[id] ? `?o=${taskOcc[id]}` : ""}`).catch((e) => ({ error: e.message }));
  if (route.name !== "task" || +route.args[0] !== id) return;
  if (d.error && !d.id) {                                 // the API's error; a failed task has an error of its own and is drawn
    view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div class="card empty">${esc(d.error)} <a href="#/tasks">All tasks</a></div>`; return;
  }
  const sig = JSON.stringify([d.status, d.updated, d.occ, d.activity?.actions_total, d.prov?.numbers, (d.runs || []).map((r) => [r.status, r.verdict]), ttab, taskAgent, taskSrc]);
  if (taskData[id]?.sig !== sig || !$("#taskpage")) {
    taskData[id] = { ...d, sig };
    const y = window.scrollY, redraw = !!$("#taskpage");
    taskPage(d);
    if (redraw) window.scrollTo(0, y);                    // a live update keeps your place
  }
  if (LIVE_T.includes(d.status)) taskTimer = setTimeout(() => route.name === "task" && +route.args[0] === id && vTask(), 5000);
}

function taskPage(t) {
  const a = t.activity || { agents: [], actions: [], memory: { read: [], write: [] }, lanes: [], edges: [], errors: [] };
  const run = (t.runs || []).find((r) => r.occ === t.occ) || t.runs?.[0];
  const steps = (t.steps || {})[String(run?.occ || 1)] || [];
  const done = steps.filter((s) => s.status === "done").length;
  const secs = run?.started ? ((run.ended ? Date.parse(run.ended) : Date.now()) - Date.parse(run.started)) / 1000 : null;
  const verdict = (t.runs || []).length > 1 ? run?.verdict : t.verdict, v = verdict && (VWORD[verdict] || [verdict, ""]);
  const blocked = steps.find((s) => (s.error || "").startsWith("blocked:"));
  const n = t.prov?.numbers || {};
  t.numbers = [[nf(a.agents.length), "agents worked on it"], [steps.length ? `${done} of ${steps.length}` : "–", "steps done"],   // the Overview shows them under the answer
    [secs != null ? dur(secs) : "–", run?.ended ? "from start to end" : run ? "running so far" : "time"], [tok(a.agents.reduce((x, g) => x + g.tokens, 0)), `tokens${n.cost != null ? ` · ${ifPaid(n.cost)}` : t.cost != null && (t.runs || []).length <= 1 ? ` · ${ifPaid(t.cost)}` : ""}`],
    ...(t.prov ? [[`${nf(n.read || 0)} · ${nf(n.cited || 0)}`, "sources read · cited"]] : []),
    [`${a.memory.read.length} · ${a.memory.write.length}`, "memory read · kept"], [v ? v[0] : t.status === "done" ? "not judged yet" : "–", "against done when"]];
  const tabs = TTABS.filter(([k]) => (k !== "runs" || (t.runs || []).length > 1) && (k !== "sources" || t.prov));
  if (!tabs.some(([k]) => k === ttab)) ttab = "overview";
  const many = (t.runs || []).length > 1;
  view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div id="taskpage">
  <div class="aghead h-${["failed", "cancelled"].includes(t.status) ? "bad" : t.status === "done" ? "ok" : "warn"}"><div class="agic lg">${ic.target}</div><div class="grow" style="min-width:0">
    <h1 class="agh1">${esc(t.title)}</h1>
    <div class="row wrap small muted" style="gap:4px 8px;margin-top:6px"><span class="pill ${TPILL[t.status] || ""}">${LIVE_T.includes(t.status) && t.status !== "needs_answer" ? '<span class="dot run"></span>' : ""}${esc(tstat(t))}</span>
      <span>#${t.id} · ${t.owner === "stack" ? "the stack's task" : "your task"}${t.kind ? ` · ${esc(TKINDS[t.kind] || t.kind)}` : ""} · ${esc(rhythmText(t.rhythm, t.after))}</span><span>${ic.clock}given ${rel(t.created)}${t.source === "app" ? " by you" : t.source ? ` · from ${esc(t.source)}` : ""}</span></div>
    ${t.goal && t.goal !== t.title ? `<div class="small muted agwhat">${prose(t.goal)}</div>` : ""}
    <div data-tideas="${t.id}"></div>${(queueMicrotask(() => fillTaskIdeas($(`[data-tideas="${t.id}"]`), t.id)), "")}
  </div></div>
  ${many ? `<label class="row small" style="gap:8px;margin-top:12px"><span class="muted">Showing</span><select class="input sm" id="tocc" style="width:auto;max-width:100%;min-width:0;flex:1 1 auto">${t.runs.map((r) => `<option value="${r.occ}" ${r.occ === run.occ ? "selected" : ""}>Run ${r.occ} of ${t.runs.length} · ${esc(day(r.started))}${r.verdict ? ` · ${esc((VWORD[r.verdict] || [r.verdict])[0])}` : r.status ? ` · ${esc(r.status)}` : ""}</option>`).join("")}</select></label>` : ""}
  ${blocked ? `<div class="banner" style="margin-top:12px">${ic.alert}<span class="grow wrap"><b>Not done: step ${blocked.idx} (${esc(taskWho(blocked.agent))}) was blocked.</b> ${esc(blocked.error.slice(9))}</span></div>`
    : t.error ? `<div class="banner" style="margin-top:12px">${ic.alert}<span class="grow wrap">${esc(t.error)}</span></div>` : ""}
  ${changeHtml(t)}
  ${t.status === "needs_answer" ? `<form class="card pad tans" data-tans="${t.id}" style="margin-top:12px"><b>It asks you</b>${(t.questions || []).map((q, i) => `<label><span>${esc(q)}</span><input class="input" name="a${i}" required></label>`).join("")}<div class="row" style="justify-content:flex-end"><button class="btn sm primary">${ic.check}Answer</button></div></form>` : ""}
  <div class="actions">${String(t.source || "").startsWith("trial:") ? `<a class="btn" href="#/trials?t=${encodeURIComponent(t.source.slice(6))}">${ic.target}Trial scoreboard</a>` : ""}
    ${t.door === "plan" && (t.runs || []).length ? `<a class="btn" href="#/taskmap?t=${t.id}${many ? `&o=${run.occ}` : ""}">${ic.wiki}Swarm map</a><a class="btn" href="#/live/${encodeURIComponent(`task:${t.id}${run && run.occ > 1 ? `.${run.occ}` : ""}`)}">${ic.pulse}Live trace</a>` : ""}
    ${t.door && t.ref && TDOOR[t.door] && t.door !== "plan" ? (([h, l]) => `<a class="btn" href="${h}">${ic.next}${esc(l)}</a>`)(TDOOR[t.door](t.ref)) : ""}
    ${t.status === "waiting_approval" && t.kind !== "change" ? `<button class="btn primary" data-tok="${t.id}">${ic.check}Start it</button>` : ""}
    ${t.door === "plan" && t.kind !== "change" && ["scheduled", "done", "failed"].includes(t.status) && (t.runs || []).length ? `<button class="btn" data-trun="${t.id}">${ic.play}Run again now</button>` : ""}
    ${["failed", "cancelled"].includes(t.status) && t.door === "plan" && t.kind !== "change" ? `<button class="btn" data-tretry="${t.id}">${ic.repeat}Plan it again</button>` : ""}
    ${!["done", "failed", "cancelled"].includes(t.status) && (t.door === "plan" || !t.ref) ? `<button class="btn ghost danger" data-tcancel="${t.id}">${ic.x}Cancel</button>` : ""}</div>
  <div class="seg agtabs">${tabs.map(([k, l]) => `<button data-tt="${k}" class="${ttab === k ? "on" : ""}">${l}${k === "agents" ? ` · ${a.agents.length}` : k === "memory" ? ` · ${a.memory.read.length + a.memory.write.length}` : k === "sources" ? ` · ${(t.prov?.sources || []).filter((s) => s.kind !== "search").length}` : k === "runs" ? ` · ${t.runs.length}` : ""}</button>`).join("")}</div>
  <div id="ttbody" class="section" style="margin-top:14px"></div></div>`;
  const go = (k) => { ttab = k; history.replaceState(history.state, "", `#/task/${t.id}?tab=${ttab}`); taskPage(t); window.scrollTo(0, $("#ttbody").offsetTop - 80); };
  $$("[data-tt]").forEach((b) => (b.onclick = () => { ttab = b.dataset.tt; history.replaceState(history.state, "", `#/task/${t.id}?tab=${ttab}`); taskPage(t); }));
  if ($("#tocc")) $("#tocc").onchange = (e) => { taskOcc[t.id] = +e.target.value; vTask(); };
  if (typeof bindTasks === "function") bindTasks();
  changeBind(t);
  const body = $("#ttbody");
  ({ overview: taskOverview, timeline: taskTimeline, agents: taskAgents, sources: taskSources, memory: taskMemory, runs: taskRuns })[ttab](body, t, a, steps);
  $$("[data-tab-go]", body).forEach((b) => (b.onclick = (e) => { e.preventDefault(); go(b.dataset.tabGo); }));
}

function taskStepList(steps) {
  return `<ol class="tplan">${steps.map((s) => { const h = taskAgentHref(s.agent); return `<li><b>${esc(s.title)}</b> ${h ? `<a class="agent" href="${h}">${esc(taskWho(s.agent))}</a>` : `<span class="agent">${esc(taskWho(s.agent))}</span>`} <span class="tiny faint">${esc(s.harness)}</span>
    <div class="sub ${s.status === "failed" ? "err-t" : s.status === "done" ? "" : "warn-t"}">${esc(SSTATE[s.status] || s.status)}${s.after?.length ? ` · after step ${s.after.join(", ")}` : ""}${s.started ? ` · ${clock(s.started)}${s.ended ? `–${clock(s.ended)}` : ""}` : ""}${s.waiting_for ? ` · ${esc(s.waiting_for)}` : ""}${s.attempts > 1 ? ` · attempt ${s.attempts}` : ""}</div>
    ${s.error && s.status !== "done" ? `<div class="${s.error.startsWith("blocked:") ? "err-t" : "faint"}">${esc(s.error)}</div>` : ""}
    ${s.output ? `<details class="tiny"><summary>Its result</summary><div class="md">${md(s.output)}</div></details>` : ""}
    <a class="tiny" href="#/live/${encodeURIComponent(`task:${s.task}${(s.occ || 1) > 1 ? "." + s.occ : ""}:step:${s.idx}`)}">how it ran</a></li>`; }).join("")}</ol>`;
}

// ---------- who worked on it: the agents as bubbles, their part as colour, their own tokens as size ----------
function taskPart(g) {
  const r = g.roles || [];
  if (r.some((x) => x.startsWith("step") || x === "did it")) return "step";
  if (r.some((x) => ["planned it", "ran the plan", "checked the plan between waves"].includes(x))) return "coord";
  return "call";
}
function taskLinks(a, steps) {                    // who worked with whom: the run record's starts and calls, and the plan's hand-offs
  const by = {}, ids = new Set(a.agents.map((g) => g.agent));
  const put = (from, to, kind, n, what) => {
    if (!from || !to || from === to || !ids.has(from) || !ids.has(to)) return;
    const e = (by[`${from}>${to}>${kind}`] = by[`${from}>${to}>${kind}`] || { from, to, kind, n: 0, what: [] });
    e.n += n;
    if (what) e.what.push(what);
  };
  for (const e of a.edges || []) put(e.from, e.to, e.kind, e.n);
  const ag = Object.fromEntries(steps.map((s) => [s.idx, s]));
  for (const s of steps) for (const i of s.after || []) if (ag[i]) put(ag[i].agent, s.agent, "handed", 1, `step ${i} (${ag[i].title}) → step ${s.idx} (${s.title})`);
  return Object.values(by);
}
const taskLinkWords = (l) => `${taskWho(l.from)} ${TVERB[l.kind] || l.kind} ${taskWho(l.to)}${l.n > 1 ? ` · ${l.n} times` : ""}`;

function taskAgentCard(g, t, a) {
  const h = taskAgentHref(g.agent), b = t.prov?.by_agent?.[g.agent], part = taskPart(g);
  const [r, w] = ["read", "write"].map((k) => a.memory[k].filter((m) => m.agent === g.agent).length);
  const src = (t.prov?.sources || []).filter((s) => s.kind !== "search" && s.agents.includes(g.agent)).length;
  const tools = Object.entries(g.tools || {});
  return `<div class="card pad"><div class="row between wrap" style="gap:8px"><b class="row" style="gap:6px"><i class="tsw" style="background:${TPART[part][0]}"></i>${h ? `<a href="${h}">${esc(taskWho(g.agent))}</a>` : esc(taskWho(g.agent))}</b>
      <span class="tiny faint">${esc(Object.entries(g.states).map(([k, n]) => `${n} ${k}`).join(" · "))}</span></div>
    <div class="small">${esc(g.roles.join(" · ") || "worked on it")}</div>
    <div class="tiny faint" style="margin-top:4px">${[`${nf(g.runs)} run${g.runs === 1 ? "" : "s"}`, `${nf(g.calls)} tool calls`, `${nf(g.model_calls)} model calls`, `${tok(g.tokens)} tokens`,
      b?.cost ? ifPaid(b.cost) : "", `${clock(new Date(g.first * 1000).toISOString())}–${clock(new Date(g.last * 1000).toISOString())} · ${dur(g.last - g.first)}`].filter(Boolean).map(esc).join(" · ")}</div>
    ${b?.models?.length ? `<div class="tiny faint">${esc(b.models.join(", "))}</div>` : ""}
    <div class="tiny faint">memory: read ${r} · kept ${w}${t.prov ? ` · sources read ${src}` : ""}</div>
    ${tools.length ? `<div class="chips" style="margin-top:6px">${tools.map(([k, n]) => `<span class="tag">${esc(k)} ${n}</span>`).join("")}</div>` : ""}
    <div class="row wrap" style="gap:6px;margin-top:8px"><button class="btn sm ghost" data-tsee="${esc(g.agent)}">${ic.pulse}Its actions here</button>${h ? `<a class="btn sm ghost" href="${h}">${ic.next}Its page</a>` : ""}</div></div>`;
}
function taskBindSee(box, t) {
  $$("[data-tsee]", box).forEach((b) => (b.onclick = () => { taskAgent = b.dataset.tsee; ttab = "timeline"; history.replaceState(history.state, "", `#/task/${t.id}?tab=timeline`); taskPage(t); }));
}

function taskBubbles(box, t, a, steps, H) {
  if (!a.agents.length) { box.innerHTML = `<div class="small muted">No agent has worked on it yet${LIVE_T.includes(t.status) ? ": they show here as they start" : ""}.</div>`; return; }
  const links = taskLinks(a, steps);
  const words = `<details class="swmapwords" style="margin-top:10px"><summary class="small"><b>Who did what, in words</b> <span class="muted">${a.agents.length} agents · ${links.length} connections</span></summary>
    <div class="list" style="margin-top:6px">${a.agents.map((g) => `<div><div class="grow"><div class="ttl row" style="gap:6px"><i class="tsw" style="background:${TPART[taskPart(g)][0]}"></i>${esc(taskWho(g.agent))}</div><div class="sub">${esc(g.roles.join(" · ") || "worked on it")} · ${tok(g.tokens)} tokens · ${nf(g.calls)} tool calls</div></div></div>`).join("")}</div>
    ${links.length ? `<ul class="small" style="margin-top:8px">${links.map((l) => `<li>${esc(taskLinkWords(l))}${l.what.length ? `<div class="tiny faint">${l.what.map(esc).join("<br>")}</div>` : ""}</li>`).join("")}</ul>` : `<div class="small muted" style="margin-top:6px">No agent started, called in or handed results to another.</div>`}</details>`;
  box.innerHTML = `<div class="tbub" style="height:${H}px"></div><div class="tiny faint" style="margin-top:4px">${CHART_HINT} or a line</div>
    <div class="tkey tiny faint">${Object.values(TPART).map(([c, l]) => `<span><i class="tsw" style="background:${c}"></i>${l}</span>`).join("")}
      <span><i class="tline" style="border-color:var(--accent)"></i>handed its results on</span><span><i class="tline"></i>called in</span><span><i class="tline dash"></i>gave a step, planned, checked</span>
      <span>a bubble's size: the tokens of its own model calls</span></div><div class="tbsel"></div>${words}`;
  const el = $(".tbub", box), sel = $(".tbsel", box);
  if (!window.d3) { el.innerHTML = `<div class="small muted pad">The chart library did not load: the agents are listed in words below.</div>`; return; }
  const W = el.clientWidth || 340, max = Math.max(1, ...a.agents.map((g) => g.tokens));
  const nodes = a.agents.map((g) => ({ id: g.agent, g, r: 9 + 22 * Math.sqrt(g.tokens / max), part: taskPart(g) }));
  const L = links.map((l) => ({ ...l, source: l.from, target: l.to }));
  const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(L).id((d) => d.id).distance((l) => l.source.r + l.target.r + 52).strength(0.5))
    .force("charge", d3.forceManyBody().strength(-340)).force("x", d3.forceX(W / 2).strength(0.06)).force("y", d3.forceY(H / 2).strength(0.1))
    .force("collide", d3.forceCollide((d) => d.r + 26)).stop();
  for (let i = 0; i < 400; i++) sim.tick();                // laid out once: nothing drifts under a finger
  const svg = d3.select(el).append("svg").attr("width", W).attr("height", H), root = svg.append("g");
  const look = (l) => (l.kind === "handed" ? ["var(--accent)", null] : l.kind === "called" ? ["var(--muted)", null] : ["var(--border-2)", "5 5"]);
  const end = (l) => { const dx = l.target.x - l.source.x, dy = l.target.y - l.source.y, d = Math.hypot(dx, dy) || 1;
    return { x: l.target.x - (dx / d) * (l.target.r + 5), y: l.target.y - (dy / d) * (l.target.r + 5), a: (Math.atan2(dy, dx) * 180) / Math.PI }; };
  root.append("g").selectAll("line").data(L).join("line").attr("x1", (l) => l.source.x).attr("y1", (l) => l.source.y).attr("x2", (l) => end(l).x).attr("y2", (l) => end(l).y)
    .attr("stroke", (l) => look(l)[0]).attr("stroke-dasharray", (l) => look(l)[1]).attr("stroke-width", (l) => Math.min(6, 1.5 + Math.log2(l.n))).attr("stroke-linecap", "round").attr("vector-effect", "non-scaling-stroke");
  root.append("g").selectAll("path").data(L).join("path").attr("d", "M-7,-4.5 L1,0 L-7,4.5 Z").attr("fill", (l) => look(l)[0])
    .attr("transform", (l) => { const e = end(l); return `translate(${e.x},${e.y}) rotate(${e.a})`; }).style("pointer-events", "none");
  const showLink = (l) => {
    sel.innerHTML = `<div class="card pad"><b>${esc(taskLinkWords(l))}</b>${l.what.length ? `<ul class="tiny" style="margin:6px 0 0">${l.what.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      <div class="row wrap" style="gap:6px;margin-top:8px">${[l.from, l.to].map((x) => `<button class="btn sm ghost" data-tsee="${esc(x)}">${ic.pulse}${esc(taskWho(x))}'s actions</button>`).join("")}</div></div>`;
    taskBindSee(sel, t);
  };
  root.append("g").selectAll("line").data(L).join("line").attr("x1", (l) => l.source.x).attr("y1", (l) => l.source.y).attr("x2", (l) => l.target.x).attr("y2", (l) => l.target.y)
    .attr("stroke", "transparent").attr("stroke-width", 18).attr("vector-effect", "non-scaling-stroke").style("cursor", "pointer")
    .on("click", (_, l) => showLink(l)).append("title").text(taskLinkWords);
  const node = root.append("g").selectAll("g").data(nodes).join("g").attr("transform", (d) => `translate(${d.x},${d.y})`).style("cursor", "pointer")
    .on("click", (_, d) => { sel.innerHTML = taskAgentCard(d.g, t, a); taskBindSee(sel, t); });
  node.append("title").text((d) => `${taskWho(d.id)}: ${d.g.roles.join(", ") || "worked on it"} · ${tok(d.g.tokens)} tokens`);
  node.filter((d) => d.g.states.failed || d.g.states.stalled || d.g.states.running).append("circle").attr("r", (d) => d.r + 4).attr("fill", "none")
    .attr("stroke", (d) => (d.g.states.failed || d.g.states.stalled ? "var(--err)" : "var(--run)")).attr("stroke-width", 2.5).attr("vector-effect", "non-scaling-stroke")
    .attr("class", (d) => (d.g.states.running ? "swlive" : ""));
  node.append("circle").attr("r", (d) => d.r).attr("fill", (d) => TPART[d.part][0]).attr("stroke", "var(--surface-2)").attr("stroke-width", 2).attr("vector-effect", "non-scaling-stroke");
  node.append("text").attr("class", "tblbl").attr("y", (d) => d.r + 13).text((d) => taskWho(d.id));
  node.append("text").attr("class", "tblbl tbsub").attr("y", (d) => d.r + 25).text((d) => (d.g.tokens ? `${tok(d.g.tokens)} tokens` : d.g.roles[0] || ""));
  const pts = nodes.flatMap((d) => [{ x: d.x - d.r - 34, y: d.y - d.r }, { x: d.x + d.r + 34, y: d.y + d.r + 28 }]);
  const fit = (anim) => (anim ? svg.transition().duration(250) : svg).call(zoom.transform, chartFit(pts, W, H, 8, 1.3, 0));
  const zoom = chartZoom(el, svg, root, { fit });
  fit(false);
}

// ---------- CHG-16: a change request: its specification, the evidence per criterion, the branch and your review ----------
function changeCrit(x, st) {
  const s = st[x.id] || {}, met = s.after === "passes" && s.before !== "passes";
  const word = met ? "met" : !s.after || s.after === "not run" ? "no test run yet" : "not met";
  return `<li class="${met ? "" : s.after === "fails" ? "err-t" : ""}">${met ? "✓" : s.after === "fails" ? "✗" : "·"} <b>${esc(x.id)}</b> ${esc(x.text)}<div class="tiny faint wrap">${esc(word)}${s.test ? ` · ${esc(s.test)}: before ${esc(s.before || "not run")}, after ${esc(s.after || "not run")}` : ""}</div></li>`;
}
function changeHtml(t) {
  const ch = t.change || {};
  if (!(ch.criteria || []).length) return "";
  const st = ch.acceptance || {}, j = ch.judge || {}, rv = ch.review || {}, pr = ch.probe, go = t.status === "waiting_approval";
  const words = (k, label) => ((ch[k] || []).length ? `<div class="small" style="margin-top:6px"><b>${label}</b><ul class="tiny" style="margin:2px 0 0">${ch[k].map((x) => `<li class="wrap">${esc(x)}</li>`).join("")}</ul></div>` : "");
  const budget = t.budget ? `${nf(t.budget.tokens || 0)} tokens` : "";
  const rounds = Object.entries(ch.rounds || {}).filter(([, n]) => n).map(([k, n]) => `${taskWho(k)} ${n}`).join(", ");
  return `<div class="card pad-l section" id="tchange"><div class="row between wrap" style="gap:8px"><h2>The change · ${esc(ch.size || "")}</h2>
      <span class="row wrap" style="gap:6px">${ch.carrier ? `<a class="btn sm primary" href="#/build/${ch.carrier}">${ic.next}Review it</a>` : ""}</span></div>
    <div class="tiny faint wrap">${[t.repo, ch.branch, budget && `budget ${budget}`, rounds && `fix rounds: ${rounds}`, ch.outcome].filter(Boolean).map(esc).join(" · ")}</div>
    ${go ? `<form id="chgo" style="margin-top:10px"><label class="small"><b>Acceptance criteria</b><textarea class="input" name="criteria" rows="${Math.min(12, ch.criteria.length + 2)}">${esc(ch.criteria.map((x) => x.text).join("\n"))}</textarea></label>
        <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn primary sm">${ic.check}Go</button></div></form>`
      : `<ul class="tjudge" style="margin-top:8px">${ch.criteria.map((x) => changeCrit(x, st)).join("")}</ul>`}
    ${words("scope", "In scope")}${words("out_of_scope", "Out of scope")}${words("files", "Files it expects to touch")}${words("risks", "Risks")}${words("assumptions", "Assumptions")}
    ${ch.judge ? `<div class="small" style="margin-top:8px"><b>The suite</b> <span class="${j.ok ? "" : "err-t"}">${j.ok ? "passes against the baseline" : "does not pass"}</span>${(j.known || []).length ? ` <span class="tiny faint">· ${nf(j.known.length)} failed already before it</span>` : ""}${(j.flaky || []).length ? ` <span class="tiny faint">· ${nf(j.flaky.length)} flaky</span>` : ""}</div>` : ""}
    ${rv.verdict ? `<div class="small"><b>Reviewers</b> ${esc(rv.verdict)}${(rv.findings || []).length ? ` · ${nf(rv.findings.length)} findings` : ""}</div>` : ""}
    ${pr ? `<div class="small"><b>Tried for real</b> ${pr.ok ? "it works" : pr.ran ? '<span class="err-t">it did not work</span>' : "it could not be tried"}<div class="tiny faint wrap">${esc(pr.notes || "")}</div>
        ${(pr.evidence || []).map((n) => (/\.(png|jpg)$/.test(n) ? `<a href="/api/change/${t.id}/${encodeURIComponent(n)}" target="_blank" rel="noopener"><img src="/api/change/${t.id}/${encodeURIComponent(n)}" alt="${esc(n)}" style="max-width:100%;margin-top:6px;border-radius:8px"></a>` : `<a class="tiny" href="/api/change/${t.id}/${encodeURIComponent(n)}" target="_blank" rel="noopener">${esc(n)}</a> `)).join("")}</div>` : ""}
    ${t.status === "failed" && t.door === "plan" ? `<div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn sm" id="chres">${ic.repeat}Go on, with its budget doubled</button></div>` : ""}
  </div>`;
}
function changeBind(t) {
  const f = $("#chgo");
  if (f) f.onsubmit = (e) => { e.preventDefault(); act({ action: "change_go", id: t.id, criteria: f.criteria.value }, "Started: its steps show here as they run"); };
  const r = $("#chres");
  if (r) r.onclick = () => act({ action: "change_resume", id: t.id }, "It goes on from the step that stopped");
}

// ---------- the overview: the result first, then how it came about ----------
function taskProblems(t, a, steps) {             // what went wrong, each with where to look
  const out = [], j = t.judgement;
  for (const s of steps.filter((x) => x.status === "failed" && !(x.error || "").startsWith("blocked:")))
    out.push([`Step ${s.idx} (${taskWho(s.agent)}) failed${s.error ? `: ${s.error}` : ""}`, `#/live/${encodeURIComponent(`task:${t.id}${(s.occ || 1) > 1 ? "." + s.occ : ""}:step:${s.idx}`)}`]);
  for (const s of steps.filter((x) => x.attempts > 1)) out.push([`Step ${s.idx} (${taskWho(s.agent)}) took ${s.attempts} attempts`, ""]);
  for (const l of (a.lanes || []).filter((x) => ["failed", "stalled"].includes(x.state)))
    out.push([`${taskWho(l.agent)}'s run (${l.role}) ${l.state === "stalled" ? "went silent and was closed" : "failed"}`, `#/live/${encodeURIComponent(l.run)}`]);
  if (a.errors_total) out.push([`${nf(a.errors_total)} error${a.errors_total === 1 ? "" : "s"} in its agents' runs: ${[...new Set(a.errors.map((e) => e.title))].join("; ")}`, ""]);
  const unmet = (j?.points || []).filter((p) => !p.met);
  if (unmet.length) out.push([`${unmet.length} of ${j.points.length} points of done when not met`, ""]);
  return out;
}
function taskMem(t, a) {                         // every memory use, by store: [{store, read: [...], kept: [...]}], each grouped by what
  const g = {};
  const add = (store, op, target, agent, ts, run, note) => {
    const s = (g[store] = g[store] || { read: {}, kept: {} }), k = target || "(not named)";
    const x = (s[op][k] = s[op][k] || { target: k, n: 0, agents: new Set(), last: 0, run: "", note: "" });
    x.n++; x.agents.add(agent);
    if (ts >= x.last) { x.last = ts; x.run = run || x.run; }
    if (note) x.note = note;
  };
  for (const m of a.memory.read) add(m.store || "notes", "read", m.target, m.agent, m.ts, m.run);
  for (const m of a.memory.write) add(m.store || "notes", "kept", m.target, m.agent, m.ts, m.run);
  if (t.wiki?.root) add("wiki", "read", t.wiki.page ? `${t.wiki.root}/${t.wiki.page}.md` : t.wiki.root, "conductor", 0, "", "given to its research steps as it stood");
  for (const x of (t.prov?.made || []).filter((y) => y.kind === "wiki")) add("wiki", "kept", x.uri.replace(/^vault:/, ""), x.agents[0] || "conductor", 0, "", "updated from its findings");
  if (t.result && t.answer) add("notes", "kept", t.result, "conductor", 0, "", "the answer, where search finds it");
  return Object.keys(MSTORE).filter((k) => g[k]).map((k) => ({ store: k, read: Object.values(g[k].read), kept: Object.values(g[k].kept) }));
}
function taskBars(rows, fmt) {                    // [label, value, extra] as horizontal bars, longest first
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return `<div class="tbars">${rows.map(([l, x, extra]) => `<div class="tbar"><span class="wrap">${l}</span><span class="tr-b"><span class="tr" style="width:${Math.max(1, (100 * x) / max).toFixed(1)}%"></span></span><span class="tv">${esc(fmt(x))}${extra ? ` · ${esc(extra)}` : ""}</span></div>`).join("")}</div>`;
}
const taskSites = (src) => Object.entries(src.filter((s) => s.kind !== "search").reduce((o, s) => ((o[s.site || "?"] = (o[s.site || "?"] || 0) + 1), o), {})).sort((x, y) => y[1] - x[1]);

function taskOverview(box, t, a, steps) {
  const j = t.judgement, n = t.prov?.numbers || {}, mem = taskMem(t, a), probs = taskProblems(t, a, steps), links = taskLinks(a, steps);
  const src = t.prov?.sources || [], sites = taskSites(src), made = t.prov?.made || [];
  const words = (s) => (s.match(/\S+/g) || []).length;
  const body = (t.answer || "").replace(/^---[\s\S]*?---\s*/, "");
  const SITES = 6;                                 // cap: preview (the Sources tab lists every site and every source)
  box.innerHTML = `${t.answer ? `<div class="card pad-l" id="tanswer"><div class="row between wrap" style="gap:8px"><h2>The answer${(t.runs || []).length > 1 ? ` · run ${t.occ}` : ""}</h2><a class="btn sm ghost" href="#/read?path=${encodeURIComponent(t.result)}">${ic.doc}Open as a page</a></div>
        <div class="tfold${taskUnfold ? " open" : ""}" id="tfold"><div class="md" style="margin-top:8px">${md(body)}</div></div>
        <button class="btn sm ghost" id="tunfold" hidden>${taskUnfold ? "Fold it again" : `Show the whole answer · ${nf(words(body))} words`}</button></div>`
      : `<div class="card pad small muted">${LIVE_T.includes(t.status) ? "No answer yet: it comes when the last step is done." : t.status === "failed" ? "No answer: the task did not finish. Its problems and steps below say why." : "This task has no written answer."}</div>`}
    <div class="tmnums section">${(t.numbers || []).map(([x, l]) => `<div class="card pad tmnum"><b>${esc(x)}</b><span class="tiny faint">${esc(l)}</span></div>`).join("")}</div>
    ${t.text && t.text !== t.goal ? `<p class="faint small wrap section">You wrote: “${esc(t.text)}”</p>` : ""}
    <div class="card pad-l section"><div class="row between wrap" style="gap:8px"><h2>Who worked on it</h2><a class="tiny" href="#" data-tab-go="agents">Each agent in full</a></div>
      <div class="tiny faint">${[`${a.agents.length} agent${a.agents.length === 1 ? "" : "s"}`, steps.length && `${steps.length} step${steps.length === 1 ? "" : "s"}`, n.parallel > 1 && `${n.parallel} at once at most`,
        links.filter((l) => l.kind === "handed").length && `${links.filter((l) => l.kind === "handed").reduce((x, l) => x + l.n, 0)} hand-offs`,
        links.filter((l) => l.kind === "called").length && `${links.filter((l) => l.kind === "called").reduce((x, l) => x + l.n, 0)} called in`].filter(Boolean).join(" · ")}. Tap a bubble or a line for its part.</div>
      <div id="tbubs"></div></div>
    <div class="card pad section"><h2>Done when</h2>${j?.points?.length ? `<div class="tiny faint">judged ${esc(t.verdict || "")}${j.run && (t.runs || []).length > 1 ? `, run ${j.run}` : ""}: each point against the answer and what the stack measured</div><ul class="tjudge">${j.points.map((p) => `<li class="${p.met ? "" : "err-t"}">${p.met ? "✓" : "✗"} ${esc(p.point)}<div class="faint">${esc(p.why)}</div></li>`).join("")}</ul>`
      : (t.done || []).length ? `<ul>${t.done.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : `<div class="small muted">No definition of done.</div>`}</div>
    ${probs.length ? `<div class="card pad section"><h2>What went wrong · ${probs.length}</h2><ul class="tjudge">${probs.map(([x, h]) => `<li class="warn-t">${h ? `<a href="${esc(h)}">${esc(x)}</a>` : esc(x)}</li>`).join("")}</ul></div>`
      : a.agents.length ? `<div class="tiny faint section">No failed step, retry, failed run or error.</div>` : ""}
    <div class="tgrid3 section">
      ${t.prov ? `<div class="card pad"><div class="row between" style="gap:8px"><h2>What it read</h2><a class="tiny" href="#" data-tab-go="sources">All sources</a></div>
        <div class="small">${nf(n.read || 0)} sources read · <b>${nf(n.cited || 0)}</b> cited in the answer · ${nf(src.filter((s) => s.kind === "search").length)} searches</div>
        ${sites.length ? taskBars(sites.slice(0, SITES /* cap: preview: Sources lists every site */).map(([s, x]) => [esc(s), x]), (x) => `${x} read`) + (sites.length > SITES ? `<div class="tiny faint" style="margin-top:4px">and ${sites.length - SITES} more sites, <a href="#" data-tab-go="sources">all in Sources</a></div>` : "") : `<div class="small muted" style="margin-top:6px">It read no web page, note or job ad.</div>`}</div>` : ""}
      <div class="card pad"><div class="row between" style="gap:8px"><h2>Memory</h2><a class="tiny" href="#" data-tab-go="memory">What exactly</a></div>
        ${mem.length ? `<div class="tbars">${mem.map((m) => `<div class="row between small" style="gap:8px"><span>${esc(MSTORE[m.store][0])}</span><span class="muted">read ${m.read.length} · kept ${m.kept.length}</span></div>`).join("")}</div>` : `<div class="small muted">Its agents read nothing from memory and kept nothing there.</div>`}</div>
      <div class="card pad"><h2>What it made</h2>${taskMadeHtml(t, made, steps)}</div>
    </div>
    ${a.agents.some((g) => g.tokens) ? `<div class="card pad section"><h2>Cost and time</h2><div class="tiny faint">${[taskSecs(t) != null && `${dur(taskSecs(t))} from start to end`, n.parallel && `${n.parallel} agent${n.parallel === 1 ? "" : "s"} at once at most`, n.cost != null && ifPaid(n.cost)].filter(Boolean).join(" · ")}</div>
      ${taskBars(a.agents.filter((g) => g.tokens).sort((x, y) => y.tokens - x.tokens).map((g) => [esc(taskWho(g.agent)), g.tokens, (t.prov?.by_agent?.[g.agent]?.models || []).join(", ")]), (x) => `${tok(x)} tokens`)}
      <div class="tiny faint" style="margin-top:6px">the tokens of each agent's own model calls; an agent that hands its work to Claude Code shows none, the run it called in carries them</div></div>` : ""}
    ${(t.checkpoints || []).length ? `<div class="card pad section"><h2>The Orchestrator's checkpoints · ${t.checkpoints.length}</h2><div class="tiny faint">after each wave of steps it reads what they found and keeps or changes the rest of the plan</div>
      <ul class="tjudge">${t.checkpoints.map((k) => `<li class="${k.kept ? "" : "warn-t"}">${k.kept ? "Kept the plan" : "Changed the plan"} after step ${esc(k.after.join(", "))} <span class="tiny faint">${rel(k.at)}${(t.runs || []).length > 1 ? ` · run ${k.occ}` : ""}</span>
        ${k.changes.length ? `<ul>${k.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}${k.why ? `<div class="faint">${esc(k.why)}</div>` : ""}</li>`).join("")}</ul></div>` : ""}
    ${steps.length ? `<div class="card pad section"><h2>Plan and steps${(t.runs || []).length > 1 ? ` · run ${t.occ}` : ""}</h2>${taskStepList(steps.map((s) => ({ ...s, task: t.id })))}</div>`
      : (t.plan || []).length ? `<div class="card pad section"><h2>Plan</h2><ol class="tplan">${t.plan.map((p) => `<li><b>${esc(p.step)}</b> <span class="agent">${esc(p.agent)}</span><div class="faint">${esc(p.why || "")}</div></li>`).join("")}</ol></div>` : ""}
    <div class="tiny faint section">${t.door === "plan" ? `<a href="#/live/${encodeURIComponent(`task-intake:${t.id}-${(t.answers || []).length}`)}">How it was planned</a> · ` : ""}updated ${rel(t.updated)}</div>`;
  const f = $("#tfold", box), u = $("#tunfold", box);
  if (f && u) {
    if (f.scrollHeight > f.clientHeight + 40 || taskUnfold) u.hidden = false; else f.classList.add("open");
    u.onclick = () => { taskUnfold = !taskUnfold; f.classList.toggle("open", taskUnfold); u.textContent = taskUnfold ? "Fold it again" : `Show the whole answer · ${nf(words(body))} words`; if (!taskUnfold) $("#tanswer").scrollIntoView({ block: "start" }); };
  }
  taskBubbles($("#tbubs", box), t, a, steps, Math.max(280, Math.min(380, 80 + 46 * a.agents.length)));
}
function taskSecs(t) {
  const r = (t.runs || []).find((x) => x.occ === t.occ) || t.runs?.[0];
  return r?.started ? ((r.ended ? Date.parse(r.ended) : Date.now()) - Date.parse(r.started)) / 1000 : null;
}
function taskMadeHtml(t, made, steps) {
  const by = {};
  for (const x of made) (by[x.kind] = by[x.kind] || []).push(x);
  if (t.answer && !by.result) by.result = [{ kind: "result", title: "The answer", uri: `vault:${t.result}`, steps: [], agents: [] }];
  const rows = Object.keys(TMADE).filter((k) => by[k]).map((k) => {
    const xs = by[k];
    if (k === "delivery") return `<div class="small"><b>${TMADE[k]}:</b> ${xs.map((x) => esc(x.title)).join(" · ")}</div>`;
    if (k === "finding") return `<details class="small"><summary><b>${xs.length} step finding${xs.length === 1 ? "" : "s"}</b></summary><ul class="tiny">${xs.map((x) => `<li>${esc(x.title)}</li>`).join("")}</ul></details>`;
    return `<div class="small"><b>${TMADE[k]}${xs.length > 1 ? ` · ${xs.length}` : ""}</b><ul class="tiny" style="margin:2px 0 0">${xs.map((x) => `<li class="wrap">${taskLink(taskSrcHref(x), esc(x.uri.replace(/^vault:/, "")))}</li>`).join("")}</ul></div>`;
  });
  const outs = steps.filter((s) => s.output).length;
  return rows.length ? `<div class="stack" style="gap:6px;margin-top:6px">${rows.join("")}</div>` : outs ? `<div class="small muted">${outs} step result${outs === 1 ? "" : "s"}, under Plan and steps.</div>` : `<div class="small muted">Nothing yet.</div>`;
}

function taskTimeline(box, t, a) {
  const lanes = (a.lanes || []).filter((l) => l.started);
  const who = [...new Set(a.actions.map((x) => x.agent))];
  const acts = a.actions.filter((x) => !taskAgent || x.agent === taskAgent);
  if (!lanes.length && !acts.length) { box.innerHTML = `<div class="card pad small muted">Nothing is recorded for this task yet: its agents' work shows here as they run.</div>`; return; }
  const nowS = Date.now() / 1000, t0 = Math.min(...lanes.map((l) => l.started)), t1 = Math.max(...lanes.map((l) => l.ended || nowS), t0 + 1);
  const LW = 130, W = Math.max((box.clientWidth || 340) - 24, 300), LH = 24, LL = lanes.map((l) => wrapWords(`${l.depth ? "↳ " : ""}${taskWho(l.agent)}`, (s) => svgTextWidth(s, l.depth ? "tms" : "tml", box) <= LW - (l.depth ? 10 * Math.min(l.depth, 3) : 0) - 6)),
    RH = LL.map((ls) => Math.max(LH, ls.length * 13 + 6)), RT = RH.reduce((o, h, i) => (o.push(i ? o[i - 1] + RH[i - 1] : 20), o), []), H = 22 + RH.reduce((s, h) => s + h, 0), x = (s) => LW + (s - t0) / (t1 - t0) * (W - LW - 10);
  box.innerHTML = `${lanes.length ? `<div class="card pad section"><h2>When each agent worked</h2><div class="tmap-wrap"><svg class="tmapsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="When each agent worked">
      <text x="${LW}" y="12" class="tmcol">${esc(clock(new Date(t0 * 1000).toISOString()))}</text><text x="${W - 10}" y="12" class="tmcol" text-anchor="end">${dur(t1 - t0)}</text>
      ${lanes.map((l, i) => { const y = RT[i] + (RH[i] - LH) / 2; return `<g><title>${esc(`${taskWho(l.agent)} · ${l.role} · ${dur((l.ended || nowS) - l.started)} · ${l.state || "running"}`)}</title>
        <text class="${l.depth ? "tms" : "tml"}">${svgTspans(LL[i], l.depth ? 10 * Math.min(l.depth, 3) : 0, y + 14 - (LL[i].length - 1) * 6.5, 13)}</text>
        <rect x="${x(l.started)}" y="${y + 4}" width="${Math.max(3, x(l.ended || nowS) - x(l.started))}" height="${LH - 10}" rx="4" class="tmbar ${l.state === "failed" ? "bad" : l.ended ? "" : "live"}"/></g>`; }).join("")}
    </svg></div><div class="tiny faint" style="margin-top:6px">A bar is an agent at work; indented, an agent another one called in. Hover or hold a bar for its role and time.</div></div>` : ""}
    <div class="card pad section"><div class="row between wrap" style="gap:8px"><h2>What they did · ${nf(a.actions_total)}</h2>${a.actions_total > a.actions.length ? `<span class="tiny faint">the newest ${nf(a.actions.length)}; the live trace has all</span>` : ""}</div>
      ${who.length > 1 ? `<div class="chips" style="margin:8px 0"><button class="tag${!taskAgent ? " on" : ""}" data-tag="">Everyone</button>${who.map((w) => `<button class="tag${taskAgent === w ? " on" : ""}" data-tag="${esc(w)}">${esc(taskWho(w))}</button>`).join("")}</div>` : ""}
      <div class="tacts-list">${acts.map((e) => taskRow(e)).join("") || `<div class="small muted">No actions for this agent.</div>`}</div></div>`;
  $$("[data-tag]", box).forEach((b) => (b.onclick = () => { taskAgent = b.dataset.tag; taskTimeline(box, t, a); }));
}

function taskAgents(box, t, a, steps) {
  box.innerHTML = a.agents.length ? `<div class="card pad-l section"><h2>Who worked with whom</h2><div id="tbubs"></div></div>
    <div class="stack section">${a.agents.map((g) => taskAgentCard(g, t, a)).join("")}</div>`
    : `<div class="card pad small muted">No agent has worked on it yet.</div>`;
  if (a.agents.length) taskBubbles($("#tbubs", box), t, a, steps, Math.max(340, Math.min(480, 100 + 52 * a.agents.length)));
  taskBindSee(box, t);
}

function taskSources(box, t) {
  const all = t.prov?.sources || [], sites = taskSites(all);
  const F = [["all", "Everything", () => true], ["cited", "Cited in the answer", (s) => s.cited], ["unused", "Read, not cited", (s) => !s.cited && s.kind !== "search"], ["search", "Searches", (s) => s.kind === "search"]];
  const xs = all.filter((F.find(([k]) => k === taskSrc) || F[0])[2]).sort((x, y) => y.cited - x.cited || y.steps.length - x.steps.length || String(x.title).localeCompare(String(y.title)));
  box.innerHTML = `<div class="card pad section"><h2>Its sources · ${nf(all.filter((s) => s.kind !== "search").length)}</h2>
      <div class="tiny faint">every web page, news item, job ad, note and memory its agents read, and every search they made${(t.runs || []).length > 1 ? `, in run ${t.occ}` : ""}; cited: the answer links to it</div>
      <div class="chips" style="margin:8px 0">${F.map(([k, l, f]) => `<button class="tag${taskSrc === k ? " on" : ""}" data-tsf="${k}">${l} ${all.filter(f).length}</button>`).join("")}</div>
      <div class="tacts-list tsrc">${xs.map((s) => { const h = taskSrcHref(s);
        return `<div class="tact"><div class="tact-h"><span class="tag">${esc(TSKIND[s.kind] || s.kind)}</span>${s.cited ? `<span class="tag ok">cited</span>` : ""}<b>${taskLink(h, esc(s.title || s.uri))}</b></div>
          <div class="tact-d tiny faint wrap">${[s.site && s.site !== s.kind ? s.site : "", s.steps.length ? `step ${s.steps.join(", ")}` : "", s.agents.map(taskWho).join(", ")].filter(Boolean).map(esc).join(" · ")}</div></div>`; }).join("") || `<div class="small muted">None of this kind.</div>`}</div></div>
    ${sites.length ? `<div class="card pad section"><h2>By site · ${sites.length}</h2>${taskBars(sites.map(([s, x]) => [esc(s), x]), (x) => `${x} read`)}</div>` : ""}`;
  $$("[data-tsf]", box).forEach((b) => (b.onclick = () => { taskSrc = b.dataset.tsf; taskSources(box, t); }));
}

function taskMemory(box, t, a) {
  const mem = taskMem(t, a);
  const item = (x) => `<li class="wrap">${taskLink(taskMemHref(x.target), esc(x.target))}<div class="tiny faint">${[x.n > 1 ? `${x.n} times` : "", [...x.agents].map(taskWho).join(", "), x.last ? clock(new Date(x.last * 1000).toISOString(), true) : "", x.note].filter(Boolean).map(esc).join(" · ")}</div></li>`;
  const list = (xs, empty) => (xs.length ? `<ul class="tjudge">${xs.map(item).join("")}</ul>` : `<div class="tiny faint">${empty}</div>`);
  box.innerHTML = `${mem.length ? mem.map((m) => `<div class="card pad section"><h2>${esc(MSTORE[m.store][0])} <span class="hcount">read ${m.read.length} · kept ${m.kept.length}</span></h2><div class="tiny faint">${esc(MSTORE[m.store][1])}</div>
      <div class="tgrid2" style="margin-top:8px"><div><b class="small">Read</b>${list(m.read, "nothing read here")}</div><div><b class="small">Kept</b>${list(m.kept, "nothing kept here")}</div></div></div>`).join("")
      : `<div class="card pad small muted">Its agents read nothing from memory and kept nothing there.</div>`}
    ${a.memory.read.length + a.memory.write.length ? `<details class="card pad section"><summary><b>Every memory call · ${a.memory.read.length + a.memory.write.length}</b> <span class="tiny faint">as the agents made them, oldest first</span></summary>
      <div class="tacts-list">${[...a.memory.read.map((e) => ({ ...e, op: "read" })), ...a.memory.write.map((e) => ({ ...e, op: "kept" }))].sort((x, y) => x.ts - y.ts)
        .map((e) => taskRow({ ...e, kind: "call", title: e.tool }, `${e.op === "read" ? "read" : "kept"} · ${taskTool(e.tool)}`)).join("")}</div></details>` : ""}`;
}

function taskRuns(box, t) {
  box.innerHTML = `<div class="stack">${(t.runs || []).map((r) => { const v = r.verdict && (VWORD[r.verdict] || [r.verdict, ""]);
    return `<details class="card pad"${r.occ === t.occ ? " open" : ""}><summary><b>Run ${r.occ}</b>${r.occ === t.occ ? ` <span class="tag on">shown</span>` : ""} <span class="tiny faint">${esc(HOW?.[r.trigger] || r.trigger || "")} · ${rel(r.started)} · ${esc(r.status || "")}${v ? ` · <span class="${v[1]}">${esc(v[0])}</span>` : ""}${r.tokens ? ` · ${tok(r.tokens)} tokens` : ""}</span></summary>
      ${r.event ? `<div class="small faint">${esc(r.event.trigger || "an event")}: ${esc(r.event.summary || "")}</div>` : ""}
      ${taskStepList(((t.steps || {})[String(r.occ)] || []).map((s) => ({ ...s, task: t.id })))}
      <div class="row wrap" style="gap:6px">${r.occ !== t.occ ? `<button class="btn sm primary" data-tocc="${r.occ}">${ic.target}Show this run</button>` : ""}${r.result?.startsWith?.("tasks/") ? `<a class="btn sm" href="#/read?path=${encodeURIComponent(r.result)}">${ic.doc}Its answer</a>` : ""}<a class="btn sm ghost" href="#/taskmap?t=${t.id}&o=${r.occ}">${ic.wiki}Its swarm map</a></div></details>`; }).join("")}</div>`;
  $$("[data-tocc]", box).forEach((b) => (b.onclick = () => { taskOcc[t.id] = +b.dataset.tocc; ttab = "overview"; vTask(); }));
}

// TRL-09: the trials' scoreboard (#/trials): every run of every trial side by side, newest first, with what changed
// since the run before it (score, time, tokens), so a change to an agent or the code shows as a better or worse run.
async function vTrials() {
  const d = await api("/api/trials").catch((e) => ({ error: e.message, trials: {}, runs: [] }));
  if (route.name !== "trials") return;
  const pick = route.q.get("t") || "";
  const names = [...new Set([...Object.keys(d.trials || {}), ...(d.runs || []).map((r) => r.trial)])].filter((n) => !pick || n === pick);
  const pctOf = (r) => (r.total ? Math.round((100 * r.passed) / r.total) : 0);
  const delta = (a, b, f, unit) => (a == null || b == null || a === b ? "" : `${a > b ? "+" : "−"}${f(Math.abs(a - b))}${unit}`);
  const runRow = (r, prev) => { const v = r.verdict && (VWORD[r.verdict] || [r.verdict, ""]), keyOk = r.total && r.passed === r.total;
    const judgeOff = (r.verdict === "met" && !keyOk) || (["not met", "partly"].includes(r.verdict) && keyOk);
    return `<div class="card pad"><div class="row between wrap" style="gap:8px"><b>${esc(r.started || r.run)}</b><span class="tiny faint">${r.version ? `code ${esc(r.version)} · ` : ""}${r.task ? `<a href="#/task/${r.task}">task #${r.task}</a>` : ""}</span></div>
      <div class="tmnums" style="margin-top:8px">${[[r.total ? `${r.passed} of ${r.total}` : "–", r.total ? `${pctOf(r)} % of the key's cases${prev ? ` · ${delta(r.passed, prev.passed, (x) => x, " cases") || "same"}` : ""}` : esc(r.error || "no score")],
        [r.clean == null ? "–" : r.clean ? "clean" : `${r.forbidden} forbidden`, "clean room"], [r.similarity == null ? "–" : `${Math.round(100 * r.similarity)} %`, "like upstream"],
        [r.minutes != null ? dur(60 * r.minutes) : "–", prev ? delta(r.minutes, prev.minutes, (x) => dur(60 * x), "") || "time" : "time"],
        [r.tokens != null ? tok(r.tokens) : "–", prev ? delta(r.tokens, prev.tokens, tok, " tokens") || "tokens" : "tokens"],
        [v ? v[0] : "–", judgeOff ? "the model judge, against the key" : "the model judge"]]
        .map(([x, l]) => `<div class="card pad tmnum"><b>${esc(String(x))}</b><span class="tiny faint">${esc(l)}</span></div>`).join("")}</div>
      ${Object.keys(r.areas || {}).length ? `<div class="chips" style="margin-top:8px">${Object.entries(r.areas).sort().map(([a, [p, n]]) => `<span class="tag${p === n ? "" : " warn"}">${esc(a)} ${p}/${n}</span>`).join("")}</div>` : ""}
      <div class="tiny faint" style="margin-top:6px">${[r.agents != null && `${r.agents} agent${r.agents === 1 ? "" : "s"}, ${r.parallel} at once at most`, r.read ? `${r.read} sources read, ${r.cited} cited` : "", r.steps != null && `${r.steps} step${r.steps === 1 ? "" : "s"}`, r.builds && `${r.builds} build${r.builds === 1 ? "" : "s"}`, r.asked && `${r.asked} question${r.asked === 1 ? "" : "s"} asked`, r.over_budget && "stopped at its budget", r.review && `${r.review} gap${r.review === 1 ? "" : "s"} beyond the key, for review`, r.rescored && `rescored ${r.rescored}`, judgeOff && "the model judge disagrees with the answer key"].filter(Boolean).map(esc).join(" · ")}</div>
      <div class="row wrap" style="gap:6px;margin-top:8px"><a class="btn sm" href="#/read?path=${encodeURIComponent(r.report)}">${ic.doc}The report</a>${r.task ? `<a class="btn sm ghost" href="#/task/${r.task}">${ic.target}Its task</a>` : ""}</div></div>`; };
  view.innerHTML = `<a class="back" href="#/telemetry">${ic.back}Telemetry</a>
  <div class="hero heading"><h1>Trials</h1><p>Practice runs for the swarm: each trial gives it a real job and scores the result against an answer key no agent can read. Runs of a trial stand side by side, so a change to an agent or to the code shows as a better or worse run.</p></div>
  ${d.error ? `<div class="card pad small muted">${esc(d.error)}</div>` : ""}
  ${pick ? `<div class="chips" style="margin-bottom:10px"><a class="tag" href="#/trials">All trials</a></div>` : ""}
  ${names.map((n) => { const rs = (d.runs || []).filter((r) => r.trial === n);
    return `<div class="section"><h2 class="wrap" style="margin-bottom:8px">${esc(d.trials?.[n] || n)} <span class="hcount">${rs.length}</span></h2>
      <div class="stack">${rs.slice().reverse().map((r) => runRow(r, rs[rs.indexOf(r) - 1])).join("") || `<div class="card pad small muted">Not run yet. It runs at night, one trial at a time (make trial NAME=${esc(n)}).</div>`}</div></div>`; }).join("")
    || `<div class="card empty">No trials yet.</div>`}
  <div class="tiny faint section">Each run's record is in /srv/ai/trials/runs; the answer keys live outside every agent's reach. ${typeof how === "function" ? how("telemetry") : ""}</div>`;
}

