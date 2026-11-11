// The app, part of index.html's scripts (PLT-25): two of the six places (APP-69, APP-76, APP-83).
// - Agents (#/agents): the building blocks of the workflows. Its parts: the agents (each with its page), how they do (their
//   health and their measured results), who works with whom (the network), and what agents know (the memory, #/memory).
// - Ideas (#/ideas, a page of Code since APP-83): the agents' proposals; Improve leaves the menu until phase C/D gives it
//   substance, the measures are Workflows' (#/measures).
// Loaded after app-workflows.js, before app.js; one global scope with the other parts.
const AGENT_VIEWS = [["agents", "Agents"], ["team", "Health and results"], ["network", "Who works with whom"]];
// a part of a place is one of its views (drawn here) or a page of its own reached from the same row (a link)
function placeSeg(views, cur, key, links = []) {
  return `<nav class="seg placeseg" aria-label="Parts of this page">${views.map(([k, l]) => `<button type="button" data-${key}="${k}" class="${cur === k ? "on" : ""}">${esc(l)}</button>`).join("")}${links.map(([href, l]) => `<a href="${href}">${esc(l)}</a>`).join("")}</nav>`;
}

// ---------- Agents ----------
function vAgents() {
  clearInterval(netTimer);
  const v = route.q.get("v");
  tasksView = AGENT_VIEWS.some(([k]) => k === v) ? v : AGENT_VIEWS.some(([k]) => k === tasksView) ? tasksView : pref("mc-agents-view", "agents");
  if (!AGENT_VIEWS.some(([k]) => k === tasksView)) tasksView = "agents";
  if (route.q.get("p")) teamPart = TEAM_PARTS.some(([k]) => k === route.q.get("p")) ? route.q.get("p") : teamPart;
  if (route.q.get("m")) netMode = route.q.get("m") === "team" ? "team" : "tasks";
  view.innerHTML = `<div class="hero"><div class="grow" style="min-width:0"><h1>Agents</h1><p>${agentsLine()}</p></div>
    ${explain("agents-what", "An agent is a building block of the workflows: a role with its instructions, model, tools, skills, knowledge and budget. It only runs as a step of a workflow's run, and one agent can be a step of many workflows. A change to an agent is a reviewed change, tested on its past runs first.", "About agents")}</div>
    ${placeSeg(AGENT_VIEWS, tasksView, "av", [["#/memory", "What agents know"]])}
    <div id="tvbody"></div>`;
  $$("[data-av]").forEach((b) => (b.onclick = () => { tasksView = b.dataset.av; setPref("mc-agents-view", tasksView); history.replaceState(history.state, "", `#/agents?v=${tasksView}`); route.q = new URLSearchParams({ v: tasksView }); vAgents(); }));
  agentsDraw();
}
function agentsLine() {
  const n = (S?.task_agents || []).length, live = S?.running ? 1 : 0;
  return notConnected() ? `<b class="err-t">${esc(linkWords())}</b>` : `${n ? `${nf(n)} agents` : "The agents"}${live ? " · one at work now" : ""}`;
}
function agentsDraw() {
  const b = $("#tvbody");
  if (!b) return;
  if (tasksView === "team") return teamDraw(b);
  if (tasksView === "network") {
    b.innerHTML = `<div id="netbox"></div>`;
    netLoad().then(() => route.name === "agents" && tasksView === "network" && netDraw());
    netTimer = setInterval(() => (route.name === "agents" && tasksView === "network" ? netLoad(true).then(netDraw) : clearInterval(netTimer)), 30000);
    return;
  }
  b.innerHTML = `<div class="skeleton" style="height:200px"></div>`;
  swRender(b, "agents");
}

// ---------- an agent's page (APP-76): what it does, its model, tools, knowledge and budget, every workflow it is used in,
// its recent steps and (from phase C) its scores; its health, runs and who it works with below, as before ----------
const KNOW = { memory: "your memory (wikis, facts, how-to)", memorypublic: "the memory without your own facts", qmd: "your vault (notes and wiki)", research: "web research" };
function agentUsedIn(w, a, id) {                       // a workflow uses an agent when a step names it or one of its jobs
  const jobs = new Set((a?.jobs || []).flatMap((j) => [j, String(j).replace(/^crew-/, "")]));
  return (w.agents || []).includes(id) || (w.jobs || []).some((j) => jobs.has(j)) || (w.graph?.nodes || []).some((n) => n.agent === id || (n.job && jobs.has(n.job)));
}
async function vAgentOne() {
  const id = route.args[0] || "";
  const back = `<a class="back" href="#/agents">${ic.back}Agents</a>`;
  view.innerHTML = `${back}<div class="stack"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:240px"></div></div>`;
  const [cards, fv] = await Promise.all([swWhoCards(), factoryView()]);
  if (route.name !== "agent" || route.args[0] !== id) return;
  const a = (cards || []).find((c) => c.id === id), used = (fv.workflows || []).filter((w) => agentUsedIn(w, a, id));
  const tools = a?.tools || [], know = tools.filter((t) => KNOW[t]).map((t) => KNOW[t]);
  const b = a?.budgets || {}, budget = [b.wakes_per_day != null ? `${nf(b.wakes_per_day)} wakes a day` : "", b.messages_per_hour != null ? `${nf(b.messages_per_hour)} messages an hour` : ""].filter(Boolean).join(" · ");
  const steps = (S?.tasks || []).flatMap((t) => (t.steps || []).filter((s) => s.agent === id).map((s) => ({ t, s })))
    .sort((x, y) => String(y.s.started || y.t.updated || "").localeCompare(String(x.s.started || x.t.updated || ""))).slice(0, 10);   /* cap: list: its 10 newest steps; each run's page has every one */
  const fact = (k, v) => `<div class="agfact"><span class="tiny faint">${esc(k)}</span><div class="small wrap">${v}</div></div>`;
  view.innerHTML = `${back}
    <div class="hero"><div class="grow" style="min-width:0"><h1 class="wrap">${esc(swName(id))}</h1><p class="wrap">${esc(a?.purpose || "A tool or a service the agents use; it has no card of its own.")}</p></div></div>
    <div class="card pad agfacts">${fact("Model", esc(a?.model || "–"))}${fact("Runs as", esc(a ? swHarness(a) : "–"))}
      ${fact("Tools", tools.length ? tools.map((t) => `<span class="tag">${esc(SW_REACH[t] || t)}</span>`).join(" ") : "none of its own")}
      ${fact("Knowledge", know.length ? esc(know.join(", ")) : "only what each step hands it")}
      ${fact("Skills", `<a href="#/howto">the how-to it may look up</a>`)}${fact("Budget", esc(budget || "no limit of its own"))}</div>
    <div class="section-h section"><h2>Used in <span class="hcount">${nf(used.length)}</span></h2>${explain("agent-used-in", "Every workflow with a step this agent does. An agent only runs as a step of a workflow's run; one agent can be a step of many workflows.", "About used in")}</div>
    ${used.length ? `<div class="wf-cards">${used.map(wfCardHtml).join("")}</div>` : `<div class="card pad small muted">No workflow has a step for it yet.</div>`}
    <div class="section-h section"><h2>Recent steps <span class="hcount">${nf(steps.length)}</span></h2></div>
    ${steps.length ? `<div class="card list">${steps.map(({ t, s }) => `<a href="#/task/${t.id}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(s.title)}</div>
      <div class="sub wrap">${runPill(s.status === "done" ? "done" : s.status === "failed" ? "failed" : ["running", "waiting"].includes(s.status) ? s.status : s.status || "")} ${esc(t.title)}${s.started ? ` · ${esc(when(s.started))}` : ""}</div></div>${ic.next}</a>`).join("")}</div>`
      : `<div class="card pad small muted">No recent step in the open runs or those of the last 7 days.</div>`}
    <div class="section-h section"><h2>Scores</h2></div>
    <div class="card pad small muted">Scorers grade a sample of its runs from phase C of the factory design; until then each run's own verdict shows on its page.</div>
    <div id="swagent" class="section"></div>`;
  swAgentPanel($("#swagent"), id, false, false);
}

// ---------- Ideas (APP-83): the agents' proposals, a page of Code ----------
function vIdeas() {
  clearInterval(swTimer);
  tasksView = "ideas";
  view.innerHTML = `<a class="back" href="#/build">${ic.back}Code</a><div class="hero"><div class="grow"><h1>Ideas</h1><p>${ideasLine()}</p></div>
    ${explain("ideas-what", "What the agents propose to make the stack and themselves better, each with its evidence; nothing changes without your tap. The measures of your records are under Workflows, the benchmarks under Stack → Costs.", "About ideas")}</div>
    <div id="tvbody"><div class="skeleton" style="height:200px"></div></div>`;
  swRender($("#tvbody"), "improve", route.q.get("at") || "");
}
function ideasLine() {
  const open = (S?.swarm?.board?.open || []).length + (S?.swarm?.changes || []).filter((a) => a.state === "ready").length;
  return open ? `${nf(open)} idea${open === 1 ? "" : "s"} open` : "No idea waits";
}
