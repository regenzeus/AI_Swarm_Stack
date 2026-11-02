// APP-35: a task's own page (#/task/<id>), like an agent's: what it is and where it stands, its answer, who worked on
// it and what each of them did, what they read from and kept in memory, and every run. The runner writes the task's
// data (public/tasks/<id>.json, ops/tasks.py publish); the run record adds the agents, their actions and memory use.
// Loaded before app.js: it uses app.js's helpers only when a page is drawn.
let taskData = {}, ttab = "overview", taskTimer = null, taskAgent = "";
const TTABS = [["overview", "Overview"], ["timeline", "Timeline"], ["agents", "Agents"], ["memory", "Memory"], ["runs", "Runs"]];
const TPILL = { done: "ok", failed: "failed", cancelled: "archived", running: "running", scheduled: "active", needs_answer: "paused",
  waiting_approval: "paused", waiting_owner: "paused", intake: "running", planning: "running", after: "queued" };
const TACT = { run: "started", call: "used", say: "said", error: "error", stage: "stage", propose: "proposed", read: "read", wait: "waits", end: "ended" };
const LIVE_T = ["intake", "planning", "running", "needs_answer", "waiting_approval", "waiting_owner", "after"];

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

async function vTask() {
  clearTimeout(taskTimer);
  const id = +route.args[0];
  if (!id) { view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div class="card empty">No task named. <a href="#/tasks">All tasks</a></div>`; return; }
  if (route.q.get("tab")) { ttab = TTABS.some(([k]) => k === route.q.get("tab")) ? route.q.get("tab") : "overview"; route.q.delete("tab"); }
  if (!taskData[id]) view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div class="stack"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:320px"></div></div>`;
  const d = await api(`/api/task/${id}`).catch((e) => ({ error: e.message }));
  if (route.name !== "task" || +route.args[0] !== id) return;
  if (d.error && !d.id) {                                 // the API's error; a failed task has an error of its own and is drawn
    view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div class="card empty">${esc(d.error)} <a href="#/tasks">All tasks</a></div>`; return;
  }
  const sig = JSON.stringify([d.status, d.updated, d.activity?.actions_total, (d.runs || []).map((r) => [r.status, r.verdict]), ttab, taskAgent]);
  if (taskData[id]?.sig !== sig || !$("#taskpage")) {
    taskData[id] = { ...d, sig };
    const y = window.scrollY, redraw = !!$("#taskpage");
    taskPage(d);
    if (redraw) window.scrollTo(0, y);                    // a live update keeps your place
  }
  if (LIVE_T.includes(d.status)) taskTimer = setTimeout(() => route.name === "task" && +route.args[0] === id && vTask(), 5000);
}

function taskPage(t) {
  const a = t.activity || { agents: [], actions: [], memory: { read: [], write: [] }, lanes: [] };
  const steps = (t.steps || {})[String(t.runs?.[0]?.occ || 1)] || [];
  const done = steps.filter((s) => s.status === "done").length;
  const occ = t.runs?.[0];
  const secs = occ?.started ? ((occ.ended ? Date.parse(occ.ended) : Date.now()) - Date.parse(occ.started)) / 1000 : null;
  const v = t.verdict && (VWORD[t.verdict] || [t.verdict, ""]);
  const blocked = steps.find((s) => (s.error || "").startsWith("blocked:"));
  const tabs = TTABS.filter(([k]) => k !== "runs" || (t.runs || []).length > 1);
  if (!tabs.some(([k]) => k === ttab)) ttab = "overview";
  view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div id="taskpage">
  <div class="aghead h-${["failed", "cancelled"].includes(t.status) ? "bad" : t.status === "done" ? "ok" : "warn"}"><div class="agic lg">${ic.target}</div><div class="grow" style="min-width:0">
    <h1 class="agh1">${esc(t.title)}</h1>
    <div class="row wrap small muted" style="gap:4px 8px;margin-top:6px"><span class="pill ${TPILL[t.status] || ""}">${LIVE_T.includes(t.status) && t.status !== "needs_answer" ? '<span class="dot run"></span>' : ""}${esc(tstat(t))}</span>
      <span>#${t.id}${t.kind ? ` · ${esc(TKINDS[t.kind] || t.kind)}` : ""} · ${esc(rhythmText(t.rhythm, t.after))}</span><span>${ic.clock}given ${rel(t.created)}${t.source === "app" ? " by you" : t.source ? ` · from ${esc(t.source)}` : ""}</span></div>
    ${t.goal && t.goal !== t.title ? `<div class="small muted agwhat">${esc(t.goal)}</div>` : ""}
  </div></div>
  ${blocked ? `<div class="banner" style="margin-top:12px">${ic.alert}<span class="grow wrap"><b>Not done: step ${blocked.idx} (${esc(taskWho(blocked.agent))}) was blocked.</b> ${esc(blocked.error.slice(9))}</span></div>`
    : t.error ? `<div class="banner" style="margin-top:12px">${ic.alert}<span class="grow wrap">${esc(t.error)}</span></div>` : ""}
  ${t.status === "needs_answer" ? `<form class="card pad tans" data-tans="${t.id}" style="margin-top:12px"><b>It asks you</b>${(t.questions || []).map((q, i) => `<label><span>${esc(q)}</span><input class="input" name="a${i}" required></label>`).join("")}<div class="row" style="justify-content:flex-end"><button class="btn sm primary">${ic.check}Answer</button></div></form>` : ""}
  <div class="tmnums" style="margin-top:14px">${[[nf(a.agents.length), "agents worked on it"], [steps.length ? `${done} of ${steps.length}` : "–", "steps done"],
    [secs != null ? dur(secs) : "–", occ?.ended ? "from start to end" : "running so far"], [t.tokens ? tok(t.tokens) : tok(a.agents.reduce((n, x) => n + x.tokens, 0)), t.cost != null ? `tokens · ${ifPaid(t.cost)}` : "tokens"],
    [`${a.memory.read.length} · ${a.memory.write.length}`, "memory read · kept"], [v ? v[0] : t.status === "done" ? "not judged yet" : "–", "against done when"]]
    .map(([x, l]) => `<div class="card pad tmnum"><b>${esc(x)}</b><span class="tiny faint">${esc(l)}</span></div>`).join("")}</div>
  <div class="actions">${t.answer ? `<button class="btn primary" data-tgo="answer">${ic.doc}The answer</button>` : ""}
    ${String(t.source || "").startsWith("trial:") ? `<a class="btn" href="#/trials?t=${encodeURIComponent(t.source.slice(6))}">${ic.target}Trial scoreboard</a>` : ""}
    ${t.door === "plan" && (t.runs || []).length ? `<a class="btn" href="#/taskmap?t=${t.id}">${ic.wiki}Swarm map</a><a class="btn" href="#/live/${encodeURIComponent(`task:${t.id}`)}">${ic.pulse}Live trace</a>` : ""}
    ${t.door && t.ref && TDOOR[t.door] && t.door !== "plan" ? (([h, l]) => `<a class="btn" href="${h}">${ic.next}${esc(l)}</a>`)(TDOOR[t.door](t.ref)) : ""}
    ${t.status === "waiting_approval" ? `<button class="btn primary" data-tok="${t.id}">${ic.check}Start it</button>` : ""}
    ${["failed", "cancelled"].includes(t.status) && t.door === "plan" ? `<button class="btn" data-tretry="${t.id}">${ic.repeat}Plan it again</button>` : ""}
    ${!["done", "failed", "cancelled"].includes(t.status) && (t.door === "plan" || !t.ref) ? `<button class="btn ghost danger" data-tcancel="${t.id}">${ic.x}Cancel</button>` : ""}</div>
  <div class="seg agtabs">${tabs.map(([k, l]) => `<button data-tt="${k}" class="${ttab === k ? "on" : ""}">${l}${k === "agents" ? ` · ${a.agents.length}` : k === "memory" ? ` · ${a.memory.read.length + a.memory.write.length}` : k === "runs" ? ` · ${t.runs.length}` : ""}</button>`).join("")}</div>
  <div id="ttbody" class="section" style="margin-top:14px"></div></div>`;
  $$("[data-tt]").forEach((b) => (b.onclick = () => { ttab = b.dataset.tt; history.replaceState(history.state, "", `#/task/${t.id}?tab=${ttab}`); taskPage(t); }));
  $$("[data-tgo]").forEach((b) => (b.onclick = () => { ttab = "overview"; taskPage(t); $("#tanswer")?.scrollIntoView({ block: "start" }); }));
  if (typeof bindTasks === "function") bindTasks();
  ({ overview: taskOverview, timeline: taskTimeline, agents: taskAgents, memory: taskMemory, runs: taskRuns })[ttab]($("#ttbody"), t, a, steps);
}

function taskStepList(steps) {
  return `<ol class="tplan">${steps.map((s) => { const h = taskAgentHref(s.agent); return `<li><b>${esc(s.title)}</b> ${h ? `<a class="agent" href="${h}">${esc(taskWho(s.agent))}</a>` : `<span class="agent">${esc(taskWho(s.agent))}</span>`} <span class="tiny faint">${esc(s.harness)}</span>
    <div class="sub ${s.status === "failed" ? "err-t" : s.status === "done" ? "" : "warn-t"}">${esc(SSTATE[s.status] || s.status)}${s.after?.length ? ` · after step ${s.after.join(", ")}` : ""}${s.started ? ` · ${clock(s.started)}${s.ended ? `–${clock(s.ended)}` : ""}` : ""}${s.waiting_for ? ` · ${esc(s.waiting_for)}` : ""}${s.attempts > 1 ? ` · attempt ${s.attempts}` : ""}</div>
    ${s.error && s.status !== "done" ? `<div class="${s.error.startsWith("blocked:") ? "err-t" : "faint"}">${esc(s.error)}</div>` : ""}
    ${s.output ? `<details class="tiny"><summary>Its result</summary><div class="md">${md(s.output)}</div></details>` : ""}
    <a class="tiny" href="#/live/${encodeURIComponent(`task:${s.task}${(s.occ || 1) > 1 ? "." + s.occ : ""}:step:${s.idx}`)}">how it ran</a></li>`; }).join("")}</ol>`;
}

function taskOverview(box, t, a, steps) {
  const j = t.judgement;
  box.innerHTML = `${t.text && t.text !== t.goal ? `<p class="faint small">You wrote: “${esc(t.text)}”</p>` : ""}
    ${t.answer ? `<div class="card pad-l section" id="tanswer"><div class="row between wrap" style="gap:8px"><h2>The answer</h2><a class="btn sm ghost" href="#/read?path=${encodeURIComponent(t.result)}">${ic.doc}Open as a page</a></div><div class="md" style="margin-top:8px">${md(t.answer.replace(/^---[\s\S]*?---\s*/, ""))}</div></div>`
      : `<div class="card pad small muted section">${LIVE_T.includes(t.status) ? "No answer yet: it comes when the last step is done." : t.status === "failed" ? "No answer: the task did not finish. The steps below say why." : "This task has no written answer."}</div>`}
    <div class="card pad section"><h2>Done when</h2>${j?.points?.length ? `<div class="tiny faint">judged ${esc(t.verdict || "")}${j.run && (t.runs || []).length > 1 ? `, run ${j.run}` : ""}: each point against the answer and what the stack measured</div><ul class="tjudge">${j.points.map((p) => `<li class="${p.met ? "" : "err-t"}">${p.met ? "✓" : "✗"} ${esc(p.point)}<div class="faint">${esc(p.why)}</div></li>`).join("")}</ul>`
      : (t.done || []).length ? `<ul>${t.done.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : `<div class="small muted">No definition of done.</div>`}</div>
    ${(t.checkpoints || []).length ? `<div class="card pad section"><h2>The Orchestrator's checkpoints · ${t.checkpoints.length}</h2><div class="tiny faint">after each wave of steps it reads what they found and keeps or changes the rest of the plan</div>
      <ul class="tjudge">${t.checkpoints.map((k) => `<li class="${k.kept ? "" : "warn-t"}">${k.kept ? "Kept the plan" : "Changed the plan"} after step ${esc(k.after.join(", "))} <span class="tiny faint">${rel(k.at)}${(t.runs || []).length > 1 ? ` · run ${k.occ}` : ""}</span>
        ${k.changes.length ? `<ul>${k.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}${k.why ? `<div class="faint">${esc(k.why)}</div>` : ""}</li>`).join("")}</ul></div>` : ""}
    ${steps.length ? `<div class="card pad section"><h2>Plan and steps${(t.runs || []).length > 1 ? ` · run ${t.runs[0].occ}` : ""}</h2>${taskStepList(steps.map((s) => ({ ...s, task: t.id })))}</div>`
      : (t.plan || []).length ? `<div class="card pad section"><h2>Plan</h2><ol class="tplan">${t.plan.map((p) => `<li><b>${esc(p.step)}</b> <span class="agent">${esc(p.agent)}</span><div class="faint">${esc(p.why || "")}</div></li>`).join("")}</ol></div>` : ""}
    <div class="tiny faint section">${t.door === "plan" ? `<a href="#/live/${encodeURIComponent(`task-intake:${t.id}-${(t.answers || []).length}`)}">How it was planned</a> · ` : ""}updated ${rel(t.updated)}</div>`;
}

function taskTimeline(box, t, a) {
  const lanes = (a.lanes || []).filter((l) => l.started);
  const who = [...new Set(a.actions.map((x) => x.agent))];
  const acts = a.actions.filter((x) => !taskAgent || x.agent === taskAgent);
  if (!lanes.length && !acts.length) { box.innerHTML = `<div class="card pad small muted">Nothing is recorded for this task yet: its agents' work shows here as they run.</div>`; return; }
  const nowS = Date.now() / 1000, t0 = Math.min(...lanes.map((l) => l.started)), t1 = Math.max(...lanes.map((l) => l.ended || nowS), t0 + 1);
  const LW = 130, W = Math.max((box.clientWidth || 340) - 24, 300), LH = 24, H = 22 + lanes.length * LH, x = (s) => LW + (s - t0) / (t1 - t0) * (W - LW - 10);
  box.innerHTML = `${lanes.length ? `<div class="card pad section"><h2>When each agent worked</h2><div class="tmap-wrap"><svg class="tmapsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="When each agent worked">
      <text x="${LW}" y="12" class="tmcol">${esc(clock(new Date(t0 * 1000).toISOString()))}</text><text x="${W - 10}" y="12" class="tmcol" text-anchor="end">${dur(t1 - t0)}</text>
      ${lanes.map((l, i) => { const y = 20 + i * LH; return `<g><title>${esc(`${taskWho(l.agent)} · ${l.role} · ${dur((l.ended || nowS) - l.started)} · ${l.state || "running"}`)}</title>
        <text x="${l.depth ? 10 * Math.min(l.depth, 3) : 0}" y="${y + 14}" class="${l.depth ? "tms" : "tml"}">${esc(tmShort(`${l.depth ? "↳ " : ""}${taskWho(l.agent)}`, 20))}</text>
        <rect x="${x(l.started)}" y="${y + 4}" width="${Math.max(3, x(l.ended || nowS) - x(l.started))}" height="${LH - 10}" rx="4" class="tmbar ${l.state === "failed" ? "bad" : l.ended ? "" : "live"}"/></g>`; }).join("")}
    </svg></div><div class="tiny faint" style="margin-top:6px">A bar is an agent at work; indented, an agent another one called in. Hover or hold a bar for its role and time.</div></div>` : ""}
    <div class="card pad section"><div class="row between wrap" style="gap:8px"><h2>What they did · ${nf(a.actions_total)}</h2>${a.actions_total > a.actions.length ? `<span class="tiny faint">the newest ${nf(a.actions.length)}; the live trace has all</span>` : ""}</div>
      ${who.length > 1 ? `<div class="chips" style="margin:8px 0"><button class="tag${!taskAgent ? " on" : ""}" data-tag="">Everyone</button>${who.map((w) => `<button class="tag${taskAgent === w ? " on" : ""}" data-tag="${esc(w)}">${esc(taskWho(w))}</button>`).join("")}</div>` : ""}
      <div class="tacts-list">${acts.map((e) => taskRow(e)).join("") || `<div class="small muted">No actions for this agent.</div>`}</div></div>`;
  $$("[data-tag]", box).forEach((b) => (b.onclick = () => { taskAgent = b.dataset.tag; taskTimeline(box, t, a); }));
}

function taskAgents(box, t, a) {
  box.innerHTML = a.agents.length ? `<div class="stack">${a.agents.map((g) => { const h = taskAgentHref(g.agent); return `<div class="card pad">
      <div class="row between wrap" style="gap:8px"><b>${h ? `<a href="${h}">${esc(taskWho(g.agent))}</a>` : esc(taskWho(g.agent))}</b><span class="tiny faint">${esc(Object.entries(g.states).map(([k, n]) => `${n} ${k}`).join(" · "))}</span></div>
      <div class="small">${esc(g.roles.join(" · ") || "worked on it")}</div>
      <div class="tiny faint" style="margin-top:4px">${nf(g.runs)} run${g.runs === 1 ? "" : "s"} · ${nf(g.calls)} tool calls · ${nf(g.model_calls)} model calls · ${tok(g.tokens)} tokens · ${clock(new Date(g.first * 1000).toISOString())}–${clock(new Date(g.last * 1000).toISOString())}</div>
      <div class="row wrap" style="gap:6px;margin-top:8px"><button class="btn sm ghost" data-tsee="${esc(g.agent)}">${ic.pulse}Its actions here</button>${h ? `<a class="btn sm ghost" href="${h}">${ic.next}Its page</a>` : ""}</div></div>`; }).join("")}</div>`
    : `<div class="card pad small muted">No agent has worked on it yet.</div>`;
  $$("[data-tsee]", box).forEach((b) => (b.onclick = () => { taskAgent = b.dataset.tsee; ttab = "timeline"; taskPage(t); }));
}

function taskMemory(box, t, a) {
  const list = (xs, empty) => xs.length ? `<div class="tacts-list">${xs.map((e) => taskRow({ ...e, kind: "call", title: e.tool }, taskTool(e.tool))).join("")}</div>` : `<div class="small muted">${empty}</div>`;
  box.innerHTML = `<div class="card pad section"><h2>Read from memory · ${a.memory.read.length}</h2><div class="tiny faint" style="margin-bottom:6px">searches of your notes and the wikis, journals, long-term memory and the swarm's ledger</div>${list(a.memory.read, "Its agents read nothing from memory.")}</div>
    <div class="card pad section"><h2>Kept in memory · ${a.memory.write.length}</h2><div class="tiny faint" style="margin-bottom:6px">journal entries, lessons, ledger entries, wiki and vault writes</div>${list(a.memory.write, "Its agents kept nothing in memory.")}</div>
    ${t.answer && t.result ? `<div class="tiny faint section">The answer itself is in the vault (${esc(t.result)}), where search finds it.</div>` : ""}`;
}

function taskRuns(box, t) {
  box.innerHTML = `<div class="stack">${(t.runs || []).map((r) => { const v = r.verdict && (VWORD[r.verdict] || [r.verdict, ""]);
    return `<details class="card pad"${r.occ === t.runs[0].occ ? " open" : ""}><summary><b>Run ${r.occ}</b> <span class="tiny faint">${esc(HOW?.[r.trigger] || r.trigger || "")} · ${rel(r.started)} · ${esc(r.status || "")}${v ? ` · <span class="${v[1]}">${esc(v[0])}</span>` : ""}${r.tokens ? ` · ${tok(r.tokens)} tokens` : ""}</span></summary>
      ${r.event ? `<div class="small faint">${esc(r.event.trigger || "an event")}: ${esc(r.event.summary || "")}</div>` : ""}
      ${taskStepList(((t.steps || {})[String(r.occ)] || []).map((s) => ({ ...s, task: t.id })))}
      <div class="row wrap" style="gap:6px">${r.result?.startsWith?.("tasks/") ? `<a class="btn sm" href="#/read?path=${encodeURIComponent(r.result)}">${ic.doc}Its answer</a>` : ""}<a class="btn sm ghost" href="#/taskmap?t=${t.id}&o=${r.occ}">${ic.wiki}Its swarm map</a></div></details>`; }).join("")}</div>`;
}

// the agent's side (APP-35): the tasks it worked on, on its page
async function agentTasksInto(box, aid) {
  box.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
  const rows = await api(`/api/agent/${encodeURIComponent(aid)}/tasks`).catch((e) => ({ error: e.message }));
  if (!box.isConnected) return;
  if (rows.error) { box.innerHTML = `<div class="card pad small muted">${esc(rows.error)}</div>`; return; }
  box.innerHTML = rows.length ? `<div class="card list">${rows.map((r) => `<a href="#/task/${r.task}"><div class="ic ${r.status === "failed" ? "err" : r.status === "done" ? "ok" : ""}">${ic.target}</div>
      <div class="grow" style="min-width:0"><div class="ttl wrap">${esc(r.title)}</div><div class="sub">#${r.task} · ${esc(r.roles.join(" · "))} · ${nf(r.runs)} run${r.runs === 1 ? "" : "s"} · ${rel(new Date(r.last * 1000).toISOString())}${r.verdict ? ` · ${esc((VWORD[r.verdict] || [r.verdict])[0])}` : ""}</div></div>${ic.next}</a>`).join("")}</div>
      <div class="tiny faint section">The tasks of the last 90 days it did a step of, planned, or was called into by another agent.</div>`
    : `<div class="card pad small muted">It has not worked on a task in the last 90 days.</div>`;
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
  <div class="tiny faint section">Each run's record is in /srv/ai/trials/runs; the answer keys live outside every agent's reach. ${typeof how === "function" ? how("tasks") : ""}</div>`;
}

