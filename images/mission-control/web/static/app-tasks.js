// The app, part of app-base.js, app-tasks.js, app-runs.js, app-devices.js, app-wiki-code.js, app-memory.js, app.js (PLT-25): the Tasks tab, triggers, Home, the crew, agents and the agent page. Loaded in that order; one global scope.
// ---------- the Tasks tab (DEC-46, 8 Nov 2026): what needs doing, and who does it ----------
// Five views, one question each: Tasks (what am I having done?), Activity (what is happening now?), Team (who does the
// work, and how well?), Network (which agents work on which tasks?) and Ideas (what could be better?). A task's When
// (once, repeats, on an event, after another task) is a setting, never a kind of its own. A task is yours or the
// stack's (TSK-40): the crew's duties are the stack's tasks, a filter away, never hidden. Agents show through their
// work: on each task's row, who works on it (TSK-43).
const TVIEWS = [["tasks", "Tasks"], ["activity", "Activity"], ["team", "Team"], ["network", "Network"], ["ideas", "Ideas"]];
const TLISTS = [["active", "Active"], ["repeating", "Repeating"], ["done", "Done"]];
const TEAM_PARTS = [["tasks", "On your tasks"], ["crew", "Crew"], ["measured", "Measured"]];
const TNEW_KINDS = [["", "The stack decides", "radar"], ["briefing", "Briefing", "news"], ["research", "Research", "doc"], ["shopping", "Shopping", "coin"], ["cleanup", "Cleanup", "trash"]];
const TNEW_WHEN = [["schedule", "Repeats"], ["event", "On event"], ["after", "After a task"], ["once", "Once"]];
const OLD_NEW_KIND = { briefing: "briefing", task: "research", shopping: "shopping", cleanup: "cleanup" };   // #/new?type= from before
let tasksView = null, tasksList = "active", tasksOwner = "all", tasksQuery = "", teamPart = "tasks", netMode = "tasks", netOwner = "all", netDays = 7, netPick = null;
let netData = null, netAt = 0, netMap = new Map(), netTimer = null, tnewOpen = false, tasksSig = "";
const NEEDS_T = ["needs_answer", "waiting_approval", "waiting_owner"], BUSY_T = ["intake", "planning", "planned", "running"];
const tRepeats = (t) => ["schedule", "event"].includes(t.rhythm?.type);
const tOver = (t) => ["done", "failed", "cancelled"].includes(t.status);
function taskAgentOf(t) {                    // a mission's or a duty's own state (needs, live, health), as its page shows it
  if (t.door === "mission") { const m = (S.missions || []).find((x) => x.slug === t.ref); return m ? missionAgent(m) : null; }
  if (t.door === "crew") { const c = (S.crew || []).find((x) => x.id === t.ref); return c ? crewAgent(c) : null; }
  return null;
}
const tNeeds = (t, A) => NEEDS_T.includes(t.status) || !!A?.needs.length;
const tLive = (t, A) => !!A?.live || !!netMap.get(t.id)?.live || (BUSY_T.includes(t.status) && Date.now() - Date.parse(t.updated || 0) < 6 * 3600e3);   // APP-38: a leftover is not at work
const tRepeating = (t, A) => tRepeats(t) && !["cancelled", "done"].includes(t.status) && !A?.archived;
const T_IN = { active: (t, A) => !tOver(t) && (!tRepeating(t, A) || tNeeds(t, A) || tLive(t, A)), repeating: tRepeating, done: (t, A) => tOver(t) && !tRepeating(t, A) };
const tHref = (t) => (t.door === "mission" && t.ref ? `#/mission/${encodeURIComponent(t.ref)}` : t.door === "crew" && t.ref ? `#/crew/${encodeURIComponent(t.ref)}` : `#/task/${t.id}`);
const tMine = (t) => t.door !== "chat" && (tasksOwner === "all" || (tasksOwner === "stack") === (t.owner === "stack"));   // a chat is a task too: it lives on Chat; All (the default) is yours and the stack's
const tNext = (t, A) => t.next_run ? Date.parse(t.next_run) : A?.next ? A.next * 1000 : 9e15;
const tRank = (t, A) => (tNeeds(t, A) ? 0 : tLive(t, A) ? 1 : BUSY_T.includes(t.status) || t.status === "after" ? 2 : 3);
const KIND_IC = { briefing: "news", research: "doc", analysis: "doc", shopping: "coin", cleanup: "trash", change: "code", coding: "code", code_question: "code", watching: "radar", errand: "target" };
const tIcon = (t, A) => A?.icon || ic[KIND_IC[t.kind] || (["build", "claude"].includes(t.door) ? "code" : t.door === "chat" ? "chat" : "target")];

function whenChip(t) {
  const r = t.rhythm || {};
  if (r.type === "schedule") return `<span class="tchip">${ic.repeat}${esc(r.schedule)}</span>`;
  if (r.type === "event") return `<span class="tchip" title="${esc(rhythmText(r))}">${ic.bolt}${esc(rhythmText(r).replace(/^on /, ""))}</span>`;
  if (r.type === "after" || t.after) return `<span class="tchip">after #${esc(String(r.task || t.after))}</span>`;
  return `<span class="tchip">once</span>`;
}
function stateChip(t, A) {
  const st = t.steps || [];
  if (tNeeds(t, A)) return `<span class="tchip warn">${esc(A?.needs[0] || TSTATUS[t.status] || t.status)}</span>`;
  if (tLive(t, A)) return `<span class="tchip run"><span class="dot run"></span>${st.length ? `step ${Math.min(st.length, st.filter((s) => s.status === "done").length + 1)} of ${st.length}` : esc(A?.step || TSTATUS[t.status] || "working")}</span>`;
  if (t.status === "failed") return `<span class="tchip err">failed</span>`;
  if (t.status === "cancelled") return `<span class="tchip">cancelled</span>`;
  if (tRepeating(t, A)) { const nx = tNext(t, A); return A?.off ? `<span class="tchip">paused</span>` : nx < 9e15 ? `<span class="tchip">next ${esc(rel(new Date(nx).toISOString()))}</span>` : ""; }
  if (t.status === "done") return `<span class="tchip ok">done ${esc(rel(t.updated))}</span>`;
  return `<span class="tchip">${esc(TSTATUS[t.status] || t.status)}</span>`;
}
function avatars(t) {                        // who works on it this week: its agents, a ring on the one at work now
  const n = netMap.get(t.id);
  if (!n?.agents.length) return "";
  const who = n.agents.map((g) => taskWho(g.agent));
  return `<span class="tavs" title="${esc(who.join(", "))}">${n.agents.slice(0, 4).map((g, i) => `<i class="${g.live ? "live" : ""}">${esc((who[i][0] || "?").toUpperCase())}</i>`).join("")}${n.agents.length > 4 ? `<i class="more">+${n.agents.length - 4}</i>` : ""}</span>`;   /* cap: preview: the task's page lists every agent */
}
function tRow(t) {
  const A = taskAgentOf(t), h = tNeeds(t, A) ? "needs" : tLive(t, A) ? "live" : t.status === "failed" ? "bad" : t.status === "done" ? "ok" : A && agentHealth(A) === "bad" ? "bad" : "idle";
  const said = t.status === "failed" && t.error ? t.error : t.last_run?.summary || A?.result || "";
  const line = [TSTATUS[t.status], t.status, "running", "done"].includes(String(said).trim().toLowerCase()) ? "" : said;   // the chip says it already
  return `<a class="card agcard tkrow h-${h}" href="${tHref(t)}"><div class="agic">${tIcon(t, A)}</div><div class="agbody">
    <div class="agrow"><b class="agt">${esc(t.title)}</b></div>
    <div class="tmeta">${stateChip(t, A)}${whenChip(t)}${avatars(t)}</div>
    ${line ? `<div class="small agres ${t.status === "failed" ? "err-t" : ""}">${prose(firstLine(line))}</div>` : ""}</div></a>`;
}
function tasksHeadHtml() {
  const mine = (S.tasks || []).filter(tMine).map((t) => [t, taskAgentOf(t)]);   // the same tasks the list shows, yours or the stack's (a work site, 9 Nov 2026: "0 repeating" over a list with one)
  const need = mine.filter(([t, A]) => tNeeds(t, A)).length, run = mine.filter(([t, A]) => tLive(t, A)).length, rep = mine.filter(([t, A]) => tRepeating(t, A)).length;
  return `<p class="agtop" id="thead">${notConnected() ? `<b class="err-t">Not connected</b>` : need ? `<b class="warn-t">${need} need${need > 1 ? "" : "s"} you</b>` : "Nothing needs you"}${run ? ` · <span class="run-t">${run} running</span>` : ""} · ${rep} repeating${netData?.agents?.length ? ` · ${netData.agents.length} agents this week` : ""}</p>`;
}
function tasksListHtml() {
  const all = (S.tasks || []).filter(tMine).map((t) => [t, taskAgentOf(t)]);
  const by = Object.fromEntries(TLISTS.map(([k]) => [k, all.filter(([t, A]) => T_IN[k](t, A))]));
  const q = tasksQuery.trim().toLowerCase();
  const list = by[tasksList].filter(([t]) => !q || `${t.title} ${t.goal || ""}`.toLowerCase().includes(q))
    .sort(([a, A], [b, B]) => tasksList === "done" ? Date.parse(b.updated || 0) - Date.parse(a.updated || 0)
      : tRank(a, A) - tRank(b, B) || tNext(a, A) - tNext(b, B) || Date.parse(b.updated || 0) - Date.parse(a.updated || 0)).map(([t]) => t);
  const empty = q ? "No task matches." : tasksList === "active" ? (tasksOwner !== "stack" ? "Nothing is going on right now. Say what to do in New task, on Home or in Chat." : "The stack's duties are all waiting for their time.")
    : tasksList === "repeating" ? "No task repeats yet: give one a When (daily, weekly, on news)." : "Nothing finished in the last 7 days.";
  return `<div class="aglist" id="tlist">${list.map(tRow).join("") || `<div class="card pad small muted">${empty}</div>`}</div>
    ${tasksList === "done" && list.length ? `<div class="tiny faint" style="margin-top:6px">Done in the last 7 days; every task keeps its page.</div>` : ""}`;
}
function tasksBodyHtml() {
  const all = (S.tasks || []).filter(tMine).map((t) => [t, taskAgentOf(t)]);
  const n = (k) => all.filter(([t, A]) => T_IN[k](t, A)).length;
  const rules = tasksList === "repeating" && tasksOwner !== "stack";
  return `${tasksOwner !== "stack" ? phoneBanner() : ""}
    ${tnewOpen ? newTaskHtml() : ""}
    <div class="tfil"><div class="chips">${TLISTS.map(([k, l]) => `<button type="button" class="fchip ${tasksList === k ? "on" : ""}" data-tl="${k}">${l}<span>${n(k)}</span></button>`).join("")}</div>
      <div class="seg tow">${[["you", "User"], ["stack", "Stack"], ["all", "All"]].map(([k, l]) => `<button type="button" class="${tasksOwner === k ? "on" : ""}" data-to="${k}">${l}</button>`).join("")}</div></div>
    <div class="wsearch tq">${ic.search}<input class="input" id="tq" placeholder="Find a task" value="${esc(tasksQuery)}" autocomplete="off"></div>
    <div id="tlistbox">${tasksListHtml()}</div>
    ${rules ? `<details class="section card pad" data-keep="trules"><summary class="row between" style="gap:8px"><b>Rules · ${(S.bus?.rules || []).length}</b><span class="tiny faint">a new task each time something happens</span></summary>
      <div id="trigboard" style="margin-top:10px">${trigBoardHtml()}</div>${ruleFormHtml()}</details>` : ""}`;
}

// New task: one form for every task (the old mission wizard's kinds and options included). Only what you set is
// decided: no When picked, the stack reads it from your words ("every morning"); no kind picked, it decides the kind.
function newTaskHtml() {
  const k = OLD_NEW_KIND[route.q.get("kind")] || route.q.get("kind") || "";
  return `<form class="card pad-l tnew" id="tnew" autocomplete="off">
    <div class="row between" style="gap:8px"><b>New task</b><button type="button" class="icon-btn" id="tnewx" title="Close">${ic.x}</button></div>
    <textarea class="input" name="text" rows="2" placeholder="What should the stack do? One sentence is enough." required style="margin-top:8px">${esc(route.q.get("text") || "")}</textarea>
    <div class="tlbl">Kind</div>
    <div class="tkinds">${TNEW_KINDS.map(([v, l, i]) => `<label class="tk${v ? "" : " wide"}"><input type="radio" name="kind" value="${v}" ${k === v ? "checked" : ""}><span>${ic[i] || ""}${l}</span></label>`).join("")}</div>
    <div class="tlbl">When</div>
    <div class="twhen">${TNEW_WHEN.map(([v, l]) => `<label><input type="radio" name="rtype" value="${v}"><span>${l}</span></label>`).join("")}</div>
    <div data-w="schedule" hidden>${schedHtml("daily 07:00")}</div>
    <div data-w="event" hidden>${trigEditor([{ type: "news" }])}</div>
    <label class="field" data-w="after" hidden><span>After task #</span><input class="input" name="after" type="number" min="1"></label>
    <div class="tlbl">Results to</div>
    <div class="tdeliver">${[["telegram", "Telegram"], ["app", "App"], ["email", "E-mail"]].map(([k2, l]) => `<label class="tk"${k2 === "email" && !S?.system?.email_ready ? ' title="Not set up yet: make email-setup on the PC, once"' : ""}><input type="checkbox" name="d_${k2}" ${k2 !== "email" ? "checked" : ""}><span>${l}</span></label>`).join("")}</div>
    <details class="tmore"><summary class="small">More: effort, agents, done when, model</summary><div class="tgrid">
      <label>Effort<select class="input" name="effort"><option value="">The stack decides</option><option value="light">Light: a quick look</option><option value="standard">Standard</option><option value="deep">Deep: thorough</option></select></label>
      <label>Before it starts<select class="input" name="autonomy"><option value="auto">Start right away</option><option value="ask">Show me the plan first</option></select></label>
      <label>Deadline<input class="input" name="deadline" type="date"></label>
      <label>Model for one-call steps<select class="input" name="model"><option value="">The stack decides</option>${Object.entries(S?.prices || {}).map(([k2, p]) => `<option value="${esc(k2)}">${esc(k2)} (${esc(p.model)})</option>`).join("")}</select></label>
      <div class="wide"><div class="small">Agents <span class="tiny faint">none ticked: the stack picks them for each step; ticked: only these do the steps</span></div>
        <div class="chips tagents">${tAgents().map((a) => `<label class="tag" title="${esc(a.purpose || "")}"><input type="checkbox" name="agents" value="${esc(a.id)}"> ${esc(taskWho(a.id))}</label>`).join("")}</div></div>
      <label class="wide">Done when (one point per line; empty: the stack writes it)<textarea class="input" name="done" rows="2"></textarea></label></div></details>
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn primary">${ic.rocket}Start</button></div></form>`;
}
function bindNewTask() {
  const f = $("#tnew");
  if (!f || f.dataset.bound) return;
  f.dataset.bound = 1;
  $("#tnewx").onclick = () => { tnewOpen = false; tasksDraw(true); };
  f.smode.querySelector('option[value="manual"]')?.remove();      // "Repeats" with no schedule is "On event"
  const sync = () => { const w = f.querySelector("[name=rtype]:checked")?.value; $$("[data-w]", f).forEach((el) => (el.hidden = el.dataset.w !== w)); };
  $$("[name=rtype]", f).forEach((r) => (r.onchange = sync));
  sync(); bindSched(f); bindTrig(f);
  const watch = (r) => {                        // a price watch checks daily unless you pick another When, as the mission form did
    if (r.value === "shopping" && r.checked && !f.querySelector("[name=rtype]:checked")) {
      f.querySelector('[name=rtype][value="schedule"]').checked = true; f.smode.value = "daily"; f.stime.value = "08:00"; bindSched(f); sync();
    }
  };
  $$("[name=kind]", f).forEach((r) => (r.onchange = () => watch(r)));
  $$("[name=kind]:checked", f).forEach(watch);
  f.text.focus();
  f.onsubmit = async (e) => {
    e.preventDefault();
    const req = { action: "task_create", text: f.text.value.trim(), autonomy: f.autonomy.value };
    const kind = f.querySelector("[name=kind]:checked")?.value, w = f.querySelector("[name=rtype]:checked")?.value, dl = readDeliver(f);
    if (kind) req.kind = kind;
    if (w === "schedule") { const s = readSched(f); if (!s) return toast("Choose at least one day", true); req.rhythm = { type: "schedule", schedule: s }; }
    else if (w === "event") { const tr = readTrig(f); if (!tr.length) return toast("Say what starts it: news on a subject, a price move or a filing", true); req.rhythm = { type: "event", triggers: tr }; }
    else if (w === "after") { if (!+f.after.value) return toast("Which task should it wait for?", true); req.rhythm = { type: "after", task: f.after.value }; }
    else if (w === "once") req.rhythm = { type: "once" };
    if (dl.join() !== "telegram,app") req.deliver = dl;                 // untouched: the app and Telegram (and e-mail if you ask for it)
    if (f.effort.value) req.effort = f.effort.value;
    if (f.deadline.value) req.deadline = f.deadline.value;
    if (f.model.value) req.model = f.model.value;
    const done = lines(f.done.value), picked = [...f.querySelectorAll("[name=agents]:checked")].map((x) => x.value);   // TSK-30
    if (done.length) req.done = done;
    if (picked.length) req.agents = picked;
    const btn = $("button.primary", f);
    btn.disabled = true;
    const r = await act(req, "The stack is planning it");
    btn.disabled = false;
    if (r?.task) { tnewOpen = false; f.reset(); location.hash = `#/task/${r.task}`; }
  };
}

function vTasks() {
  if (+route.q.get("t")) return location.replace(`#/task/${+route.q.get("t")}`);   // APP-35: a task has its own page
  clearInterval(netTimer);
  const v = route.q.get("v");
  tasksView = TVIEWS.some(([k]) => k === v) ? v : tasksView || pref("mc-tasks-view", "tasks");
  if (route.q.get("new") === "1") { tnewOpen = true; tasksView = "tasks"; tasksList = "active"; tasksOwner = "you"; }
  if (route.q.get("p")) teamPart = TEAM_PARTS.some(([k]) => k === route.q.get("p")) ? route.q.get("p") : teamPart;
  if (route.q.get("m")) netMode = route.q.get("m") === "team" ? "team" : "tasks";
  view.innerHTML = `<div class="hero"><div class="grow" style="min-width:0"><h1>Tasks</h1>${tasksHeadHtml()}</div><button class="btn primary" id="tnewb">${ic.plus}New task</button></div>
    <nav class="seg tviews" aria-label="Parts of Tasks">${TVIEWS.map(([k, l]) => `<button type="button" data-tv="${k}" class="${tasksView === k ? "on" : ""}">${l}</button>`).join("")}</nav>
    <div id="tvbody"></div>`;
  $("#tnewb").onclick = () => {
    tnewOpen = true; tasksView = "tasks"; tasksList = "active"; tasksOwner = "you"; setPref("mc-tasks-view", "tasks");
    history.replaceState(history.state, "", "#/tasks?v=tasks"); route.q = new URLSearchParams({ v: "tasks" });
    vTasks(); $("#tnew")?.scrollIntoView({ block: "start" });
  };
  $$("[data-tv]").forEach((b) => (b.onclick = () => { tasksView = b.dataset.tv; setPref("mc-tasks-view", tasksView); history.replaceState(history.state, "", `#/tasks?v=${tasksView}`); route.q = new URLSearchParams({ v: tasksView }); vTasks(); }));
  tasksDraw(true);
  netLoad().then(() => { if (route.name !== "tasks") return; const h = $("#thead"); if (h) h.outerHTML = tasksHeadHtml(); if (tasksView === "tasks") tasksDraw(); else if (tasksView === "network") netDraw(); });
  if (tasksView === "network" || tasksView === "tasks") netTimer = setInterval(() => (route.name === "tasks" && ["network", "tasks"].includes(tasksView) ? netLoad(true).then(() => (tasksView === "network" ? netDraw() : tasksDraw())) : clearInterval(netTimer)), 30000);
}
function tasksDraw(force = false) {           // the open view; a live update redraws the list only when it changed, never under your fingers
  const b = $("#tvbody");
  if (!b) return;
  if (tasksView === "tasks") {
    const sig = JSON.stringify([tasksList, tasksOwner, tasksQuery, tnewOpen, (S.tasks || []).map((t) => [t.id, t.status, t.updated, t.next_run, t.owner]), [...netMap.values()].map((x) => [x.id, x.live, x.agents.length]),
      (S.missions || []).map((m) => [m.slug, m.status, m.awaits, S.running?.slug === m.slug]), (S.crew || []).map((c) => [c.id, c.state]), S.bus?.rules]);
    if (!force && sig === tasksSig) return;
    if (!force && ((typing() && b.contains(document.activeElement)) || $("#tnew"))) {         // writing a task or searching: only the list
      if (!$("#tnew") || !typing()) { const lb = $("#tlistbox"); if (lb && sig !== tasksSig) lb.innerHTML = tasksListHtml(); }
      return;
    }
    tasksSig = sig;
    const open = [...b.querySelectorAll("details[open][data-keep]")].map((d) => d.dataset.keep);
    b.innerHTML = tasksBodyHtml();
    for (const k of open) { const d = b.querySelector(`details[data-keep="${CSS.escape(k)}"]`); if (d) d.open = true; }
    $$("[data-tl]", b).forEach((x) => (x.onclick = () => { tasksList = x.dataset.tl; tasksDraw(true); }));
    $$("[data-to]", b).forEach((x) => (x.onclick = () => { tasksOwner = x.dataset.to; tasksDraw(true); }));
    const q = $("#tq", b);
    q.oninput = () => { tasksQuery = q.value; $("#tlistbox").innerHTML = tasksListHtml(); };
    bindNewTask();
    bindTriggers();
    return;
  }
  if (!force) return;                          // the other views keep themselves current
  if (tasksView === "activity") { b.innerHTML = `<div id="ovnow"></div><div id="tvsw"><div class="skeleton" style="height:200px"></div></div>`; swOverview(); swRender($("#tvsw"), "activity"); return; }
  if (tasksView === "ideas") { b.innerHTML = `<div class="skeleton" style="height:200px"></div>`; swRender(b, "improve", route.q.get("at") || ""); return; }
  if (tasksView === "team") return teamDraw(b);
  if (tasksView === "network") { b.innerHTML = `<div id="netbox"></div>`; return netDraw(); }
}
function tasksUpdate() {                      // the state changed: the head, the list (only when it changed), the crew
  const h = $("#thead");
  if (h) h.outerHTML = tasksHeadHtml();
  if (tasksView === "tasks") tasksDraw();
  else if (tasksView === "team" && teamPart !== "tasks" && !$("#tvbody details[open]")) teamDraw($("#tvbody"), true);
}

// Team: who does the work and how well. On your tasks: the agents (cards, roles, scorecards: SWM-17); Crew: the
// stack's duties with their health (OBS-10); Measured: the daily results per agent and kind, Telemetry and Trials.
function teamDraw(b, live = false) {
  if (!b) return;
  if (!live) b.innerHTML = `<div class="chips" style="margin-bottom:10px">${TEAM_PARTS.map(([k, l]) => `<button type="button" class="fchip ${teamPart === k ? "on" : ""}" data-tp="${k}">${l}</button>`).join("")}</div><div id="teambody"></div>`;
  $$("[data-tp]", b).forEach((x) => (x.onclick = () => { teamPart = x.dataset.tp; history.replaceState(history.state, "", `#/tasks?v=team&p=${teamPart}`); teamDraw(b); }));
  const box = $("#teambody", b);
  if (teamPart === "tasks") { if (!live) { box.innerHTML = `<div class="skeleton" style="height:200px"></div>`; swRender(box, "agents"); } return; }
  if (teamPart === "measured") {
    box.innerHTML = `<div class="row wrap" style="gap:8px;margin-bottom:10px"><a class="btn sm" href="#/telemetry">${ic.pulse}Telemetry: every agent, day by day</a><a class="btn sm" href="#/trials">${ic.target}Trials</a></div>
      <div id="staffboard">${staffHtml()}</div>`;
    return;
  }
  const cur = [...(S.crew || []).map(crewAgent), ...(S.health?.items || []).filter((h) => h.kind === "engine" && h.issues?.length).map(engineAgent)].sort(byUrgency);
  const keys = issueKeys(cur), bad = cur.filter((a) => agentHealth(a) === "bad").length;
  box.innerHTML = `<div class="small muted" style="margin-bottom:8px">${cur.length} duties${bad ? ` · <span class="err-t">${bad} with problems</span>` : ""}${keys.length ? ` · <button class="linkbtn" id="ackall" ${SEEN_TIP}>mark all ${keys.length} seen</button>` : ""}</div>
    <div class="aglist">${cur.map(agentCard).join("")}</div>`;
  if ($("#ackall")) $("#ackall").onclick = (e) => confirm(`Mark all ${keys.length} open issues seen? They leave this list and the Health doctor's until each happens again; nothing is fixed.`) && ackIssues(keys, e.target);
  $$("[data-ack]", box).forEach((x) => (x.onclick = (e) => { e.preventDefault(); e.stopPropagation(); ackIssues(x.dataset.ack.split(" "), x); }));
  $$(".agcard[data-href]", box).forEach((c) => (c.onclick = c.onkeydown = (e) => {   // the whole card opens its page; its own links and buttons stay theirs
    if ((e.type === "keydown" && e.key !== "Enter") || e.target.closest("a, button")) return;
    location.hash = c.dataset.href;
  }));
}

// Network (TSK-43): your tasks on the left, the agents that worked on them on the right, a line for every pair with
// runs in the period: thicker for more runs, blue while it runs. Tap a task or an agent to see its part. "Agents
// together" is the team map: who works with whom (DEC-28).
const NET_TASKS = 14;                         // the busiest tasks first; every one is drawn (the owner, 9 Nov 2026: all, by default)
let netAll = true;
async function netLoad(force = false) {
  if (!force && netData && netData.days === netDays && Date.now() - netAt < 30000) return netData;
  try { netData = await api(`/api/tasks/network?days=${netDays}`); } catch (_) { netData = netData || { tasks: [], agents: [], outside: {}, days: netDays }; }
  netAt = Date.now();
  netMap = new Map((netData.tasks || []).map((x) => [x.id, x]));
  if (!ideaOrig.d) ideaOrigins().then(() => netMode === "tasks" && $("#netbox") && netDraw());   // the ideas' dots, once known
  return netData;
}
function netDraw() {
  const box = $("#netbox");
  if (!box) return;
  const head = `<div class="netctl"><div class="seg">${[["tasks", "Tasks and agents"], ["team", "Agents together"]].map(([k, l]) => `<button type="button" data-nm="${k}" class="${netMode === k ? "on" : ""}">${l}</button>`).join("")}</div>
    ${netMode === "tasks" ? `<div class="netctl2"><div class="seg">${[["you", "User"], ["stack", "Stack"], ["all", "All"]].map(([k, l]) => `<button type="button" data-no="${k}" class="${netOwner === k ? "on" : ""}">${l}</button>`).join("")}</div>
      <select class="input" id="netdays" aria-label="Period">${[[1, "Today"], [7, "7 days"], [30, "30 days"], [90, "90 days"]].map(([d, l]) => `<option value="${d}" ${netDays === d ? "selected" : ""}>${l}</option>`).join("")}</select></div>` : ""}</div>`;
  if (netMode === "team") {
    box.innerHTML = head + `<div id="netteam"></div>`;
    netBind(box);
    swRender($("#netteam"), "map");
    return;
  }
  const byId = new Map((S?.tasks || []).map((t) => [t.id, t]));
  const rows = (netData?.tasks || []).filter((n) => byId.has(n.id) && n.agents.length && (netOwner === "all" || (netOwner === "stack") === (byId.get(n.id).owner === "stack")));
  const shown = netAll ? rows : rows.slice(0, NET_TASKS);   /* cap: list: the busiest tasks; "Show all" names how many and draws every one */
  const ag = new Map();
  for (const n of shown) for (const g of n.agents) { const x = ag.get(g.agent) || { agent: g.agent, tasks: 0, runs: 0, live: false }; x.tasks++; x.runs += g.runs; x.live ||= g.live; ag.set(g.agent, x); }
  const agents = [...ag.values()].sort((a, b) => b.tasks - a.tasks || b.runs - a.runs);
  const W = Math.max(300, Math.min(1200, (box.clientWidth || 340) - 28)), RH = 38, TW = Math.min(360, Math.round(W * 0.46)), AX = TW + Math.max(56, Math.round(W * 0.14));   // APP-56: the width it has
  const cT = (l) => svgTextWidth(l, "tml", box) <= TW - 18, cM = (l) => svgTextWidth(l, "tms", box) <= TW - 18, cA = (l) => svgTextWidth(l, "tml", box) <= W - AX - 20;
  const tL = shown.map((n) => { const t = byId.get(n.id); return [wrapWords(t.title, cT), wrapWords(`${TKINDS[t.kind] || ""}${t.kind ? " · " : ""}${rhythmText(t.rhythm, t.after)}`, cM)]; });
  const tH = tL.map(([a, b]) => 9 + a.length * 15 + b.length * 13), GAP = 8, aL = agents.map((a) => wrapWords(taskWho(a.agent), cA));
  const tTop = tH.reduce((o, h, i) => (o.push(i ? o[i - 1] + tH[i - 1] + GAP : 4), o), []), TH = tH.reduce((s, h) => s + h + GAP, 0);
  const aTop = aL.reduce((o, l, i) => (o.push(i ? o[i - 1] + Math.max(RH, aL[i - 1].length * 15 + 16) : 4), o), []), AH = aL.reduce((s, l) => s + Math.max(RH, l.length * 15 + 16), 0);
  const H = Math.max(TH, AH) + 8;
  const ty = (i) => tTop[i] + tH[i] / 2 + (AH > TH ? (AH - TH) / 2 : 0);            // a task's middle: its box grows with its name
  const ay = (i) => aTop[i] + Math.max(RH, aL[i].length * 15 + 16) / 2 + (TH > AH ? (TH - AH) / 2 : 0);
  const aIdx = new Map(agents.map((a, i) => [a.agent, i]));
  const pickT = netPick?.t, pickA = netPick?.a;
  const hot = (tid, a) => pickT === tid || pickA === a;          // the tapped one's lines: their own colour, on top
  const lit = new Set(shown.flatMap((n) => n.agents.filter((g) => hot(n.id, g.agent)).flatMap((g) => [`t${n.id}`, `a${g.agent}`])));
  const line = (n, i, g) => {
    const y1 = ty(i), y2 = ay(aIdx.get(g.agent)), m = (TW + AX) / 2, h = hot(n.id, g.agent);
    return `<path d="M${TW},${y1} C${m},${y1} ${m},${y2} ${AX - 10},${y2}" class="netl${g.live ? " live" : ""}${h ? " hot" : pickT || pickA ? " dim" : ""}" stroke-width="${(0.8 + Math.log2(1 + g.runs) * 0.45 + (h ? 1 : 0)).toFixed(2)}"><title>${esc(`${taskWho(g.agent)} · ${byId.get(n.id).title} · ${g.runs} run${g.runs === 1 ? "" : "s"}`)}</title></path>`;
  };
  const pairs = shown.flatMap((n, i) => n.agents.map((g) => [n, i, g]));
  const lines = pairs.filter(([n, , g]) => !hot(n.id, g.agent)).map((x) => line(...x)).join("") + pairs.filter(([n, , g]) => hot(n.id, g.agent)).map((x) => line(...x)).join("");
  const tDim = (n) => (pickT ? pickT !== n.id : pickA ? !n.agents.some((g) => g.agent === pickA) : false);
  const tspans = (ls, x, y, lh) => ls.map((l, k) => `<tspan x="${x}" ${k ? `dy="${lh}"` : `y="${y}"`}>${esc(l)}</tspan>`).join("");
  const tnodes = shown.map((n, i) => { const t = byId.get(n.id), [tl, ml] = tL[i], y = ty(i) - tH[i] / 2;
    return `<g class="netn${tDim(n) ? " dim" : ""}${pickT === n.id ? " on" : lit.has(`t${n.id}`) ? " lit" : ""}" data-nt="${n.id}" tabindex="0" role="button" transform="translate(0,${y})"><title>${esc(t.title)}</title>
      <rect width="${TW}" height="${tH[i]}" rx="8" class="${n.live ? "live" : ""}"/>${(() => { const k = ideasOfTask(ideaOrig.d, n.id).length; return k ? `<circle cx="${TW - 9}" cy="9" r="3.5" class="netidea"><title>${k} idea${k === 1 ? "" : "s"} from its runs</title></circle>` : ""; })()}<text class="tml">${tspans(tl, 9, 15, 15)}</text>
      <text class="tms">${tspans(ml, 9, 15 + tl.length * 15 - 2, 13)}</text></g>`; }).join("");
  const anodes = agents.map((a, i) => { const y = ay(i), dim = pickT ? !byId.get(pickT) || !netMap.get(pickT)?.agents.some((g) => g.agent === a.agent) : pickA && pickA !== a.agent;
    return `<g class="neta${dim ? " dim" : ""}${pickA === a.agent ? " on" : lit.has(`a${a.agent}`) ? " lit" : ""}" data-na="${esc(a.agent)}" tabindex="0" role="button" transform="translate(${AX},${y})"><title>${esc(`${taskWho(a.agent)} · ${a.tasks} task${a.tasks === 1 ? "" : "s"} · ${a.runs} runs`)}</title>
      <circle r="10" class="${a.live ? "live" : ""}"/><text y="4" text-anchor="middle" class="netini">${esc((taskWho(a.agent)[0] || "?").toUpperCase())}</text><text class="tml">${tspans(aL[i], 16, 4 - (aL[i].length - 1) * 7.5, 15)}</text></g>`; }).join("");
  const out = Object.entries(netData?.outside || {}), outN = out.reduce((x, [, n]) => x + n, 0);
  box.innerHTML = head + (shown.length ? `<div class="card pad netcard"><svg class="netsvg tmapsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Which agents worked on which tasks">${lines}${tnodes}${anodes}</svg>
</div><div id="netinfo" style="margin-top:10px"></div>`
      : `<div class="card pad small muted">No agent worked on ${netOwner === "stack" ? "the stack's" : netOwner === "all" ? "any" : "your"} tasks in this period.</div>`)
    + (outN ? `<details class="card pad section"><summary class="small muted">Not on any task · ${nf(outN)} runs</summary><div class="tiny faint" style="margin-top:6px">${out.map(([a, n]) => `${esc(taskWho(a))} ${nf(n)}`).join(" · ")}</div></details>` : "");
  netBind(box);
  $$("[data-nt]", box).forEach((g) => (g.onclick = g.onkeydown = (e) => { if (e.type === "keydown" && e.key !== "Enter") return; const id = +g.dataset.nt; netPick = pickT === id ? null : { t: id }; netDraw(); }));
  $$("[data-na]", box).forEach((g) => (g.onclick = g.onkeydown = (e) => { if (e.type === "keydown" && e.key !== "Enter") return; const a = g.dataset.na; netPick = pickA === a ? null : { a }; netDraw(); }));
  netInfo(byId);
}
function netBind(box) {
  $$("[data-nm]", box).forEach((b) => (b.onclick = () => { netMode = b.dataset.nm; netDraw(); }));
  $$("[data-no]", box).forEach((b) => (b.onclick = () => { netOwner = b.dataset.no; netPick = null; netDraw(); }));
  const d = $("#netdays", box);
  if (d) d.onchange = async () => { netDays = +d.value; netPick = null; await netLoad(true); netDraw(); };
}
function netInfo(byId) {                       // the picked task's agents and the order they worked in, or the picked agent's tasks
  const el = $("#netinfo");
  if (!el || !netPick) { if (el) el.innerHTML = ""; return; }
  if (netPick.t) {
    const t = byId.get(netPick.t), n = netMap.get(netPick.t);
    if (!t || !n) { el.innerHTML = ""; return; }
    const steps = t.steps?.length ? t.steps.map((s) => [s.agent, s.title, s.status]) : (t.plan || []).map((p) => [p.agent, p.step, ""]);
    el.innerHTML = `<div class="card pad"><div class="row between wrap" style="gap:8px"><b class="wrap">${esc(t.title)}</b><a class="btn sm" href="${tHref(t)}">${ic.next}Open the task</a></div>
      ${steps.length ? `<div class="netflow">${steps.map(([a, s, st]) => `<span class="${st === "running" ? "run" : st === "done" ? "ok" : ""}">${esc(taskWho(a))} · ${esc(s)}</span>`).join("<i>→</i>")}</div>` : ""}
      <div class="tiny faint" style="margin-top:6px">${n.agents.map((g) => `${esc(taskWho(g.agent))} ${g.runs} run${g.runs === 1 ? "" : "s"}${g.live ? " (now)" : ""}`).join(" · ")}${Object.keys(n.tools || {}).length ? ` · used ${Object.entries(n.tools).map(([k, x]) => `${esc(taskWho(k))} ${x}`).join(", ")}` : ""}</div></div>`;
    return;
  }
  const a = (netData?.agents || []).find((x) => x.agent === netPick.a);
  if (!a) { el.innerHTML = ""; return; }
  const h = taskAgentHref(a.agent);
  el.innerHTML = `<div class="card pad"><div class="row between wrap" style="gap:8px"><b>${esc(taskWho(a.agent))}</b>${h ? `<a class="btn sm" href="${h}">${ic.next}Its page</a>` : ""}</div>
    <div class="tiny faint">${a.tasks.length} task${a.tasks.length === 1 ? "" : "s"} · ${nf(a.runs)} runs in ${netDays === 1 ? "today" : `${netDays} days`}</div>
    <div class="list" style="margin-top:6px">${a.tasks.map((id) => byId.get(id)).filter(Boolean).map((t) => `<a href="${tHref(t)}"><div class="grow wrap">${esc(t.title)}</div>${ic.next}</a>`).join("")}</div></div>`;
}

// a task's buttons wherever they are drawn (its page): answer, start, plan again, run again, move under the Conductor, cancel
function bindTasks() {
  $$("[data-tans]").forEach((fm) => (fm.onsubmit = async (e) => { e.preventDefault(); await act({ action: "task_answer", id: +fm.dataset.tans, answers: [...fm.querySelectorAll("input")].map((x) => x.value) }, "Answered: it plans again"); }));
  $$("[data-tok]").forEach((b) => (b.onclick = () => act({ action: "task_approve", id: +b.dataset.tok }, "Started: its steps show here as they run")));
  $$("[data-tretry]").forEach((b) => (b.onclick = () => act({ action: "task_retry", id: +b.dataset.tretry }, "Planning it again: the new plan shows here")));
  $$("[data-trun]").forEach((b) => (b.onclick = () => act({ action: "task_run", id: +b.dataset.trun }, "Running it again now: its steps show here as they go")));
  $$("[data-tcancel]").forEach((b) => (b.onclick = () => act({ action: "task_cancel", id: +b.dataset.tcancel }, "Cancelled: nothing more of it runs")));
}

// ---------- Triggers (TSK-10 to TSK-12): the event bus's sources, the owner's rules, breaking stories ----------
const PARAM = { news: ["Search for", "copper supply"], breaking: ["Subject to watch", "Acme Mining"], feed: ["Feed address", "https://example.com/feed.xml"],
  github: ["Repository (owner/name)", "regenzeus/AI_Swarm_Stack"], price: ["Symbol:percent", "ACME:8"], filing: ["US ticker", "ACME"],
  forgejo: ["Repository (empty: all)", "ai-stack"], mail: ["Sender or words (empty: any)", "invoice"], house: ["Thing or room (empty: any)", "front door"],
  file: ["File name part (empty: any)", ".pdf"], schedule: ["When", "weekdays 07:00"], task: ["Task # or words (empty: any)", ""], mission: ["Mission (empty: any)", ""],
  calendar: ["When: 60 before, start, end or 15 after", "60 before"] };
function trigBoardHtml() {
  const b = S.bus || { sources: {}, rules: [], events: [], breaking: [], ratings: {} };
  const src = Object.entries(b.sources).map(([k, s]) => `<div class="row tsrc"><span class="dot ${s.error ? "err" : s.off ? "" : "ok"}"></span><b>${esc(k)}</b><span class="grow tiny faint">${esc(s.what)}</span>
    <span class="tiny ${s.error ? "err-t" : "faint"}">${s.error ? esc(s.error) : s.off ? esc(s.off) : `${s.found} new · ${rel(s.at)}`}</span></div>`).join("");
  const rule = (r) => `<div class="card pad small trule"><div class="row" style="gap:8px"><b class="grow">${esc(r.name)}</b>
      <button class="btn sm ghost" data-rtog="${r.id}" data-on="${r.enabled ? 0 : 1}">${r.enabled ? "Pause" : "Resume"}</button><button class="btn sm ghost danger" data-rdel="${r.id}">${ic.x}Delete</button></div>
    <div class="faint">When ${esc(b.sources[r.source]?.what || r.source)}${r.param ? `: <b>${esc(r.param)}</b>` : ""}${r.words ? ` · with “${esc(r.words)}”` : ""} · then: ${esc(r.task)}</div>
    <div class="tiny faint">${r.enabled ? "" : "paused · "}at most once every ${r.cooldown_min} min${r.check_text ? ` · checked: “${esc(r.check_text)}”` : ""}${r.last_fired ? ` · last fired ${rel(r.last_fired)}` : ""}</div>
    ${r.firings.length ? `<ul class="tiny">${r.firings.map((f) => `<li>${rel(f.ts)}: ${esc(f.decision)}${f.task ? ` → <a href="#/task/${f.task}">task #${f.task}</a>` : ""}${f.why ? ` · ${esc(f.why)}` : ""}</li>`).join("")}</ul>` : ""}</div>`;
  const story = (e) => `<div class="card pad small"><div class="row" style="gap:8px;align-items:flex-start"><div class="grow"><b>${esc(e.title)}</b><div class="tiny faint">${esc(e.param)} · ${rel(e.ts)}</div></div>
      <button class="btn sm ${e.rating === 1 ? "primary" : "ghost"}" data-rate="${e.id}" data-v="${e.rating === 1 ? 0 : 1}">Right</button><button class="btn sm ${e.rating === -1 ? "primary" : "ghost"}" data-rate="${e.id}" data-v="${e.rating === -1 ? 0 : -1}">Not news</button></div>
    <details class="tiny"><summary>The reports</summary><div class="md">${md(e.detail || "")}</div></details></div>`;
  const cal = `<form class="row wrap tcal" id="calform" style="gap:6px;margin-top:8px">${b.calendar ? `<span class="small grow">Calendar: <b>${esc(b.calendar)}</b> (the address is kept private)</span><button class="btn sm ghost" type="button" data-calclear>Remove</button>`
    : `<input class="input grow" name="url" type="url" placeholder="Your calendar's secret iCal address (https://…ics)" style="min-width:200px"><button class="btn sm">Add calendar</button>`}</form>
    ${explain("read-only-every-minutes-", `Read only, every 15 minutes while a rule asks for it. Google: Settings → your calendar → Secret address in iCal format. Outlook: Calendar → Shared calendars → Publish → ICS.`, "Where to find the address")}`;
  return `<details class="card pad small" data-keep="tsrcs"><summary>Sources · ${Object.values(b.sources).filter((s) => !s.off && !s.error).length} looking, ${Object.values(b.sources).filter((s) => s.error).length} with an error</summary>${src}${cal}</details>
    <div class="stack" style="margin-top:10px">${b.rules.map(rule).join("") || `<div class="muted small">No rules yet: add one below.</div>`}</div>
    ${b.breaking.length ? `<div class="section-h section"><h2>Breaking stories · ${b.breaking.length}</h2><span class="tiny faint">rated right ${b.ratings.right} · not news ${b.ratings.not_news}</span></div><div class="stack">${b.breaking.map(story).join("")}</div>` : ""}
    <details class="card pad small" data-keep="tevents" style="margin-top:10px"><summary>Newest events · ${b.events.length}</summary><div class="list">${b.events.map((e) => `<div><span class="agent">${esc(e.source)}</span><div class="grow"><div class="ttl">${e.url ? `<a href="${esc(safeUrl(e.url))}" target="_blank" rel="noopener">${esc(e.title)}</a>` : esc(e.title)}</div></div><div class="tiny faint" style="white-space:nowrap">${rel(e.ts)}</div></div>`).join("") || `<div class="muted small">Nothing yet</div>`}</div></details>`;
}

// TSK-13, TSK-15, TSK-16: measured results per agent and kind, and the temporary agents' archive
function staffHtml() {
  const s = S.staffing || { abilities: [], designs: [] };
  const row = (a) => `<tr><td><span class="agent">${esc(a.agent)}</span> <span class="tiny faint">${esc(a.harness)}</span></td><td>${esc(TKINDS[a.kind] || a.kind)}</td><td class="num">${a.tasks}</td>
    <td class="num">${Math.round(a.success * 100)} %</td><td class="num">${a.seconds >= 60 ? Math.round(a.seconds / 60) + " min" : a.seconds + " s"}</td><td class="num">${tok(a.tokens)}</td></tr>`;
  const design = (d) => `<div class="card pad small"><b>${esc(d.name)}</b> <span class="tiny faint">${esc(d.model)} · written ${rel(d.created)}</span><div class="faint">${esc(d.purpose)}</div>
    <div class="tiny">${d.uses} task${d.uses === 1 ? "" : "s"} · met ${d.met}, partly ${d.partly}, not ${d.not_met}${d.proposed ? ` · proposed as a permanent agent ${rel(d.proposed)} (Agents → Ideas)` : ""}</div></div>`;
  return `${s.abilities.length ? `<div class="card pad small" style="overflow-x:auto"><table class="ntable"><thead><tr><th>Agent</th><th>Kind</th><th>Tasks</th><th>Done</th><th>Time</th><th>Tokens</th></tr></thead><tbody>${s.abilities.map(row).join("")}</tbody></table>
    ${explain("done-the-share-of-judged", `Done: the share of judged tasks that met their definition of done (partly counts half). From 3 tasks of a kind on, the Conductor gives a step to the agent that does that kind best.`, "How it is counted")}</div>`
    : `<div class="muted small">No judged tasks yet: each task you give is judged against its definition of done when it finishes.</div>`}
    ${s.designs.length ? `<div class="section-h section"><h2>Temporary agents · ${s.designs.length}</h2><span class="tiny faint">written for a step no agent fitted</span></div><div class="stack">${s.designs.map(design).join("")}</div>` : ""}`;
}

function ruleFormHtml() {
  const src = Object.entries(S.bus?.sources || {});
  return `<form class="card pad tform" id="ruleform" style="margin-top:12px"><b>New rule</b><div class="tgrid">
    <label>Name<input class="input" name="name" placeholder="Acme Mining breaking news" required></label>
    <label>When<select class="input" name="source">${src.map(([k, s]) => `<option value="${k}">${esc(s.what)}</option>`).join("")}</select></label>
    <label id="rparam"><span>${PARAM[src[0]?.[0]]?.[0] || "Parameter"}</span><input class="input" name="param" placeholder="${esc(PARAM[src[0]?.[0]]?.[1] || "")}"></label>
    <label>Only with these words (optional)<input class="input" name="words" placeholder="contract, copper"></label>
    <label class="wide">Then the stack should<input class="input" name="task" placeholder="Read {title} and tell me in three lines what it means for my copper positions" required></label>
    <label>At most once every (minutes)<input class="input" name="cooldown_min" type="number" min="0" value="60"></label>
    <label class="wide">Check first (optional: a model decides if the event really is this)<input class="input" name="check" placeholder="a new supply contract, not a rumour or an old story"></label></div>
    <div class="tiny faint" style="margin-top:6px">{title}, {detail}, {url} and {source} in the task are filled in from the event.</div>
    <div class="row" style="justify-content:flex-end;margin-top:10px"><button class="btn primary">${ic.check}Save the rule</button></div></form>`;
}

function bindCalendar() {                              // TSK-33: the owner's ICS address, sent once, kept on the PC
  const f = $("#calform");
  if (!f) return;
  f.onsubmit = async (e) => { e.preventDefault(); if (await act({ action: "calendar_set", url: f.url.value.trim() }, "Calendar added: rules on it fire from the next look")) f.reset(); };
  const x = $("[data-calclear]", f);
  if (x) x.onclick = () => confirm("Remove the calendar address? Rules on the calendar stop firing.") && act({ action: "calendar_clear" }, "Calendar removed: rules on it stop firing");
}

function bindTriggers() {
  bindCalendar();
  const f = $("#ruleform");
  if (f && !f.dataset.bound) {
    f.dataset.bound = 1;
    f.source.onchange = () => { const p = PARAM[f.source.value] || ["Parameter", ""]; $("#rparam span").textContent = p[0]; f.param.placeholder = p[1]; };
    f.onsubmit = async (e) => {
      e.preventDefault();
      const r = await act({ action: "rule_save", name: f.elements.name.value, when: f.source.value, param: f.param.value, words: f.words.value, task: f.task.value,
        cooldown_min: +f.cooldown_min.value, check: f.check.value }, "Rule saved: it looks from now on");
      if (r) f.reset();
    };
  }
  $$("[data-rtog]").forEach((b) => (b.onclick = () => act({ action: "rule_toggle", id: +b.dataset.rtog, on: +b.dataset.on }, +b.dataset.on ? "Rule on: it fires at its next match" : "Rule paused: it fires again when you turn it on")));
  $$("[data-rdel]").forEach((b) => (b.onclick = () => confirm("Delete this rule? Its past firings stay in the log.") && act({ action: "rule_delete", id: +b.dataset.rdel }, "Rule deleted: it fires no more; its past firings stay in the log")));
  $$("[data-rate]").forEach((b) => (b.onclick = () => act({ action: "event_rate", id: +b.dataset.rate, rating: +b.dataset.v }, "Rated: kept for tuning the breaking-news alerts")));
}

// ---------- Home (redesigned 28 Oct 2026) ----------
// Three questions, in this order: does anything need me (decisions only, each one tap away), what is happening right now,
// and what did my agents produce (a live feed of results, newest first). Live updates replace only the parts that changed
// (homeUpdate), so nothing twitches. Starting things is the ask bar at the top: Hermes can start agents itself.
let homeFilter = "all", homeShow = 12;                  // the feed opens on 12 (U2: 40 made Home 13 phone screens); "Show older" adds 40
// a long text's first line, marked when more follows (the rest is on its page)
const firstLine = (s) => { const l = String(s || "").split("\n"); return l[0] + (l.slice(1).join("").trim() ? " …" : ""); };
// who asked Claude: a crew agent's task is named after it (its question is a long standing prompt, shown when opened)
const ctAsker = (t) => { const c = /^crew:(.+)/.exec(t.source || ""); return c ? (S?.crew || []).find((x) => x.id === c[1])?.name || c[1] : t.source === "chat" ? "your chat" : "Hermes"; };
// APP-57: whole
const ctTitle = (t) => /^crew:/.test(t.source || "") ? `Asked by the ${ctAsker(t)}` : firstSentence(t.question);
const homeEx = new Map();                                // result file -> its first lines (fetched once per file)
const homeLast = {};
const toIso = (x) => (x == null ? "" : typeof x === "number" ? new Date(x > 1e12 ? x : x * 1000).toISOString() : String(x));

// GEN-02: Home draws the queue and builds no list of its own. S.decisions (ops/decisions.py and server.py owner_decisions) is
// the one list; these are its rows in its order. A kind with many items is one row with its count, so Home stays short and
// nothing is hidden: the rows always add up to the list.
const HOME_ICON = { coding: "code", "coding-low-risk": "code", "shopping-buy": "coin", "phone-routine": "trash", memory: "brain", setup: "house", access: "lock",
  "task-start": "target", "task-questions": "target", research: "target", "agent-request": "chat", ideas: "rocket", "agent-change": "rocket", "owner-confirm": "check" };
const homeMany = (kin) => kin.length > 3 || (kin.length > 1 && kin.every((d) => d.routine));
// the stack's ideas about itself wait in the one list (AUT-05) as one quiet row; the count says what is yours (DEC-46 on DEC-09)
const IDEA_CLS = new Set(["ideas", "agent-change"]);
const yoursN = () => (S.decisions || []).filter((d) => !IDEA_CLS.has(d.cls)).length;
const ideasN = () => (S.decisions || []).filter((d) => IDEA_CLS.has(d.cls)).length;
function needsRows() {
  const ds = S.decisions || [], cls = S.decide?.classes || {}, kinds = new Map(), out = [];
  for (const d of ds) kinds.set(d.cls, [...(kinds.get(d.cls) || []), d]);
  for (const d of ds) {
    const kin = kinds.get(d.cls);
    if (!homeMany(kin)) out.push({ d, kind: d.cls, n: 1, href: d.href, title: d.what, sub: d.why });
    else if (!out.some((x) => x.kind === d.cls)) out.push({ kind: d.cls, n: kin.length, href: new Set(kin.map((x) => x.href)).size === 1 ? d.href : "#/decide",
      title: `${cls[d.cls]?.title || d.cls} · ${kin.length} waiting`, sub: `first: ${d.what}` });
  }
  return out;
}

function needsRow(x) {
  const build = x.d && (S.builds || []).find((b) => `build:${b.id}` === x.d.id);    // a build's row shows its checks, CI and AI review
  return build ? workBuildRow(build) : `<a href="${esc(x.href)}"${IDEA_CLS.has(x.kind) ? ' class="quiet"' : ""}><div class="ic ${IDEA_CLS.has(x.kind) ? "" : x.kind === "phone" ? "err" : "warn"}">${ic[HOME_ICON[x.kind]] || ic.alert}</div><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(x.title)}</div><div class="sub wrap">${prose(x.sub || "")}</div></div>${ic.next}</a>`;
}

function needsHtml() {
  const n = (S.decisions || []).length;
  if (!n) return notConnected() ? `<div id="homeneeds" class="needs-calm off">${ic.alert}<span>Not connected: what needs you can't be read now.</span></div>`
    : `<div id="homeneeds" class="needs-calm">${ic.check}<span>Nothing needs you right now.</span></div>`;
  return `<div id="homeneeds"><div class="section-h"><h2>Needs you <span class="hcount">${yoursN()}</span></h2><a class="tiny" href="#/decide">All</a></div>
    <div class="card list hneeds">${needsRows().map(needsRow).join("")}</div></div>`;
}

// AUT-05, AUT-07: every decision that waits for you in one ranked list (ops/decisions.py and the server's), each
// with what, why, what the stack would decide, what happens without an answer, and its answers; routine ones of a
// class are answered together. Under it, the queue's numbers against the target and the shadow's agreement per class.
function decideGroups(ds) {
  const out = [], routine = new Map();
  for (const d of ds) {
    if (!d.routine) { out.push({ one: d }); continue; }
    if (!routine.has(d.cls)) { routine.set(d.cls, { cls: d.cls, items: [] }); out.push(routine.get(d.cls)); }
    routine.get(d.cls).items.push(d);
  }
  return out.map((g) => (g.items && g.items.length === 1 ? { one: g.items[0] } : g));
}

// routine items whose first answer takes a list of ids are answered together with one tap
function decideAll(items) {
  const acts = items.map((d) => (d.answers || [])[0]), first = acts[0]?.act;
  if (!first?.ids || !acts.every((a) => a?.act?.ids && a.act.action === first.action)) return null;
  return { label: acts[0].label, act: { action: first.action, ids: acts.flatMap((a) => a.act.ids) } };
}

function decideCard(d, cls) {
  const r = d.recommend, c = cls[d.cls] || {};
  return `<div class="card pad dcard"><div class="row between" style="gap:8px"><span class="tiny faint">${esc(c.title || d.cls)}${c.floor ? " · always yours" : ""}</span>${d.expires ? `<span class="tiny">answer by ${dt(d.expires)}</span>` : ""}</div>
    <div class="ttl wrap" style="margin-top:4px">${esc(d.what)}</div>${d.why ? `<div class="sub wrap">${prose(d.why)}</div>` : ""}
    ${r ? `<div class="small" style="margin-top:6px">The stack would say <b>${r.answer === "yes" ? "yes" : "no"}</b>${r.why ? `: ${esc(r.why)}` : ""}</div>` : ""}
    ${d.unanswered ? `<div class="tiny muted">Without an answer: ${esc(d.unanswered)}</div>` : ""}
    <div class="row wrap" style="gap:8px;margin-top:10px">${(d.answers || []).map((a, i) => a.act ? `<button class="btn sm${i ? " ghost" : ""}" data-dact='${esc(JSON.stringify(a.act))}'${a.ask ? ` data-dask="${esc(a.ask)}" data-dinto="${esc(a.into)}"` : ""}>${esc(a.label)}</button>` : `<a class="btn sm${i ? " ghost" : ""}" href="${esc(a.href)}">${esc(a.label)}</a>`).join("")}</div></div>`;
}

function vDecide() {
  const ds = S.decisions || [], st = S.decide || {}, cls = st.classes || {}, tg = st.target || {};
  const groups = decideGroups(ds);
  const agree = Object.entries(st.agreement || {});
  view.innerHTML = `<div class="hero heading"><h1>Needs you</h1></div>
  <div class="card pad small"><b id="dcount">${nf(ds.length)}</b> waiting · ${st.per_day ?? "–"} a day (target at most ${tg.per_day ?? 5}) · answered in ${st.median_h != null ? `${st.median_h} h` : "–"} at the median (target ${tg.answer_h ?? 12} h) · ${nf(st.expired || 0)} expired, over ${st.days ?? 0} day${st.days === 1 ? "" : "s"}</div>
  ${groups.length ? `<div class="stack" style="margin-top:12px">${groups.map((g) => g.one ? decideCard(g.one, cls) : `<div class="card pad dcard"><div class="tiny faint">${esc((cls[g.cls] || {}).title || g.cls)} · routine, answered together</div>
      <details data-keep="dg-${esc(g.cls)}"><summary class="ttl">${g.items.length} ${esc(((cls[g.cls] || {}).title || g.cls).toLowerCase())} decisions</summary><div class="stack" style="margin-top:8px">${g.items.map((d) => decideCard(d, cls)).join("")}</div></details>
      ${decideAll(g.items) ? `<button class="btn sm" style="margin-top:10px" data-dact='${esc(JSON.stringify(decideAll(g.items).act))}'>${esc(decideAll(g.items).label)} all ${g.items.length}</button>` : ""}</div>`).join("")}</div>`
    : `<div class="needs-calm" style="margin-top:12px">${ic.check}<span>Nothing needs you right now.</span></div>`}
  <div class="section-h" style="margin-top:18px"><h2>The shadow</h2></div>
  <div class="card pad small">For every yes-or-no decision the stack records what it would have decided, then what you decided. A kind of action may only ever act on its own after it agreed with you on 20 decisions in a row (at least 90 %), passed its exam, and you allowed it; money, people, deleting and security never do.
    ${agree.length ? `<div class="list" style="margin-top:8px">${agree.map(([k, a]) => `<div class="row between"><span>${esc((cls[k] || {}).title || k)}</span><span class="tiny">${a.agreed} of ${a.n} agreed${a.unsafe ? ` · <span class="err-t">${a.unsafe} said yes where you said no</span>` : ""}</span></div>`).join("")}</div>` : `<div class="tiny muted" style="margin-top:8px">No answers recorded yet: the shadow started on 2 Nov 2026.</div>`}</div>`;
  $$("[data-dact]").forEach((b) => (b.onclick = async () => {
    const req = JSON.parse(b.dataset.dact);
    if (b.dataset.dask) {                               // an answer in words: "Still broken" says what is
      const said = prompt(b.dataset.dask, "");
      if (said === null) return;
      req[b.dataset.dinto] = said;
    }
    b.disabled = true;
    if (!(await act(req, "Done: it leaves the list once the stack has it"))) b.disabled = false;
  }));
}

// each agent with a health alert, named, with its first alert and its page
function healthAlerts() {
  return (S.health?.items || []).map((h) => [h, (h.issues || []).find((i) => i.severity === "alert")]).filter(([, i]) => i).map(([h, i]) => {
    const m = h.kind === "mission" && (S.missions || []).find((x) => x.slug === h.slug), c = h.kind === "crew" && (S.crew || []).find((x) => x.id === h.id);
    return { name: m?.title || c?.name || h.name || h.id || h.slug || "an agent", text: i.text || i.kind || "",
      href: m ? `#/mission/${encodeURIComponent(m.slug)}` : c ? `#/crew/${encodeURIComponent(c.id)}` : "#/tasks?v=team&p=crew" };
  });
}

// GEN-02: what the owner reads but cannot answer: states, not decisions (health alerts the doctor looks at, the AI phone
// being down). They are not in the queue; ideas and agent changes are, so they are under Needs you.
function upkeepHtml() {
  const alerts = S.health?.alerts || 0, down = (S.health?.items || []).some((it) => (it.issues || []).some((i) => i.kind === "phone-down"));
  if (!alerts && !down) return "";
  const bad = healthAlerts();                         // the owner's review of 2 Nov: the row opened the Agents overview, not the problem
  const href = bad.length === 1 ? bad[0].href : "#/tasks?v=team&p=crew";
  return `<div class="hsub">Stack upkeep</div><div class="card list">
    ${down ? `<a href="#/phone"><div class="ic err">${ic.alert}</div><div class="grow" style="min-width:0"><div class="ttl">The AI phone is not connected</div><div class="sub wrap">tap to see why and fix it</div></div>${ic.next}</a>` : ""}
    ${alerts ? `<a href="${href}"><div class="ic">${ic.pulse}</div><div class="grow" style="min-width:0"><div class="ttl">${alerts} health alert${alerts > 1 ? "s" : ""}</div><div class="sub wrap">${prose(bad.map((b) => `${b.name}: ${b.text}`).join(" · ") || "the Health doctor looks at them")}</div></div>${ic.next}</a>` : ""}</div>`;
}

function nowHtml() {
  const builds = (S.builds || []).filter((b) => ["working", "queued", "checking", "deploying", "approved", "recheck"].includes(b.status));
  const queued = (S.queue || []).filter((q) => q.status === "queued").map((q) => (S.missions || []).find((m) => m.slug === q.slug)).filter(Boolean);
  const tasks = (S.claude_tasks || []).filter((t) => ["running", "queued"].includes(t.status));
  const next = (S.missions || []).filter((m) => m.status === "active" && m.next_run).sort((a, b) => a.next_run.localeCompare(b.next_run)).slice(0, 3);
  const working = (S.tasks || []).filter((t) => ["running", "planning", "intake"].includes(t.status) && Date.now() - Date.parse(t.updated || 0) < 6 * 3600e3);   // APP-38: a task at work (a leftover is not)
  const busy = S.running || builds.length || tasks.length || working.length;
  const rows = [...working.map((t) => { const st = t.steps || [], on = st.filter((s) => s.status === "running");
      return `<a href="#/task/${t.id}"><div class="ic run">${ic.target}</div><div class="grow"><div class="ttl wrap">${esc(t.title)}</div><div class="sub wrap">Task #${t.id} · ${t.status === "running" ? `${st.filter((s) => s.status === "done").length} of ${st.length} steps done${on.length ? ` · ${on.map((s) => esc(taskWho(s.agent))).join(", ")} at work` : ""}` : "being planned"}</div></div><span class="pill running"><span class="dot run"></span>${t.status === "running" ? "Working" : "Planning"}</span></a>`; }),
    ...builds.map(workBuildRow),
    ...queued.map((m) => `<a href="#/mission/${encodeURIComponent(m.slug)}"><div class="ic">${typeIcon(m.type)}</div><div class="grow"><div class="ttl wrap">${esc(m.title)}</div><div class="sub">waits for the run slot</div></div><span class="pill queued">Queued</span></a>`),
    ...tasks.map((t) => `<a href="#/build"><div class="ic ${t.status === "running" ? "run" : ""}">${ic.code}</div><div class="grow"><div class="ttl wrap">Claude task #${t.id}</div><div class="sub wrap">${esc(ctTitle(t))}</div></div><span class="pill ${t.status === "running" ? "running" : "queued"}">${t.status === "running" ? "Running" : "Queued"}</span></a>`)];
  return `<div id="homenow"><div class="section-h"><h2>Now</h2><span class="row" style="gap:10px">${busy ? `<span class="pill running"><span class="dot run"></span>working</span>` : `<span class="tiny faint">${typeof notConnected === "function" && notConnected() ? "not known" : "all quiet"}</span>`}<a class="tiny" href="#/tasks">All tasks</a></span></div>
    ${S.running ? runningCard() : ""}
    ${rows.length ? `<div class="card list" ${S.running ? 'style="margin-top:10px"' : ""}>${rows.join("")}</div>` : S.running ? "" : `<div class="card pad small muted">No agent is working right now.</div>`}
    ${upkeepHtml()}
    ${next.length ? `<div class="hsub">Up next</div><div class="card list">${next.map((m) => `<a href="#/mission/${encodeURIComponent(m.slug)}"><div class="ic">${typeIcon(m.type)}</div><div class="grow"><div class="ttl wrap">${esc(m.title)}</div><div class="sub">${dt(m.next_run)}</div></div><div class="tiny faint">${rel(m.next_run)}</div></a>`).join("")}</div>` : ""}</div>`;
}

// APP-38: Home's Results: one card per outcome you asked for or your rules started (a briefing, a task's answer, an
// alert's answer, research, a shopping step), named by what it is about: its headline first, a kind, who made it, the
// first lines, one tap to its page. A rule that fires and the task it starts are one Alert card; a running task is on
// Now and becomes a result when it ends. The stack's own machinery is not here: health in Now's Stack upkeep, deploys
// under Code, the Ledger and the crew under Agents, trials and probes on their own pages (the owner's review of 2 Nov:
// "Tasks", "Triggers" and "Agent health" cards, two cards for one outcome, and what is what hard to tell).
const RKIND = { briefing: ["Briefing", "doc"], alert: ["Alert", "bolt"], task: ["Task", "target"], research: ["Research", "doc"],
  shopping: ["Shopping", "coin"], failed: ["Failed", "x"] };
// a task the stack gave itself (a trial, a probe, a crew job, a gate): on its own pages, not in your results
const NOT_YOURS = /^(trial|probe|crew|gate)/;
function feedItems() {
  const out = [];
  for (const m of S.missions || []) for (const r of m.runs || []) {
    const ts = r.ended || r.started, kind = m.type === "shopping" ? "shopping" : m.type === "briefing" ? "briefing" : "research";
    const fr = S.files?.missions?.[m.slug]?.runs?.[r.id] || {};          // MIS-23: the files it made come first, then the report
    if (r.status === "ok" && r.summary) out.push({ id: `m:${m.slug}:${r.id || ts}`, ts, kind, agent: m.title, head: r.summary, path: fr.saved?.length ? "" : r.output, big: true,
      files: fr.saved || [], missing: fr.missing || [],
      href: fr.saved?.length || fr.missing?.length ? `#/mission/${encodeURIComponent(m.slug)}?tab=payoff` : r.output ? `#/read?path=${encodeURIComponent(r.output)}&m=${encodeURIComponent(m.slug)}` : `#/mission/${encodeURIComponent(m.slug)}`,
      meta: [r.trigger === "event" ? "after an event" : r.trigger === "schedule" ? "scheduled" : "on request", dur(r.seconds), r.calls ? `${r.calls} model calls` : ""] });
    else if (r.status === "failed") out.push({ id: `m:${m.slug}:${r.id || ts}`, ts, kind: "failed", agent: m.title, tone: "err", head: `Did not finish${r.summary ? `: ${r.summary}` : ""}`,
      href: `#/mission/${encodeURIComponent(m.slug)}?tab=history` });
  }
  for (const p of typeof shopProposals === "function" ? shopProposals() : [])
    if (["proposed", "needs_owner", "approved", "buying", "bought", "shipped", "delivered", "failed"].includes(p.status))
      out.push({ id: `p:${p.id}`, ts: p.updated || p.created, kind: "shopping", agent: p.mission || "Shopping", tone: p.status === "failed" ? "err" : "",
        head: `${p.item}: ${eur(p.total_eur)} · ${(SHOP_STATE[p.status] || [, p.status])[1]}`, href: `#/mission/${encodeURIComponent(p.slug)}?shop=${p.id}` });
  for (const t of S.tasks || []) {
    if (t.door === "mission" || NOT_YOURS.test(t.source || "") || /^You are the Health doctor/.test(t.text || t.title || "")) continue;
    const run = (t.runs || [])[0], failed = t.status === "failed" || run?.status === "failed";
    if (!["done", "failed"].includes(t.status) && !(t.status === "scheduled" && run?.ended)) continue;   // still going: on Now
    const kind = failed ? "failed" : /^rule:/.test(t.source || "") ? "alert" : t.kind === "briefing" ? "briefing" : t.kind === "research" ? "research" : "task";
    out.push({ id: `t:${t.id}:${run?.occ || 1}`, ts: run?.ended || t.updated, kind, agent: `Task #${t.id}${(t.runs || []).length > 1 ? ` · run ${run.occ}` : ""}`,
      head: t.title, path: !failed && String(t.result || "").startsWith("tasks/") ? t.result : "", big: !failed, tone: failed ? "err" : "",
      sub: failed ? t.error || "" : "", href: `#/task/${t.id}` });
  }
  return out.filter((x) => x.ts).sort((a, b) => new Date(toIso(b.ts)) - new Date(toIso(a.ts)));
}

function dayOf(iso) {
  const d = new Date(iso), t = new Date(), y = new Date(t);
  y.setDate(t.getDate() - 1);
  return d.toDateString() === t.toDateString() ? "Today" : d.toDateString() === y.toDateString() ? "Yesterday" : day(d, true);
}
const clockOf = clock;

function feedHtml() {
  const all = feedItems();
  const kinds = [["all", "All"], ["briefing", "Briefings"], ["alert", "Alerts"], ["task", "Tasks"], ["research", "Research"], ["shopping", "Shopping"], ["failed", "Failed"]]
    .filter(([k]) => k === "all" || all.some((x) => x.kind === k));
  if (!kinds.some(([k]) => k === homeFilter)) homeFilter = "all";
  const mine = all.filter((x) => homeFilter === "all" || x.kind === homeFilter), items = mine.slice(0, homeShow);   /* cap: list: "Show older" shows the rest */
  let day = "";
  const rows = items.map((x) => {
    const d = dayOf(toIso(x.ts)), head = d !== day ? `<div class="fday">${esc((day = d))}</div>` : "";
    const ex = x.path ? homeEx.get(x.path) : "", [label, icon] = RKIND[x.kind] || RKIND.task;
    return `${head}<a class="fitem ${x.big ? "big" : ""} ${x.tone || ""}" href="${x.href}" data-fid="${esc(x.id)}"><div class="fi-ic k-${x.kind}">${ic[icon] || ic.doc}</div>
      <div class="grow" style="min-width:0"><div class="fi-top"><span class="fkind k-${x.kind}">${label}</span><span class="tiny faint wrap grow">${esc(x.agent)}</span><span class="tiny faint">${clockOf(toIso(x.ts))}</span></div>
        <div class="fi-h">${esc(x.head)}</div>${x.sub ? `<div class="fi-x small muted wrap">${prose(x.sub)}</div>` : ""}
        ${x.files?.length || x.missing?.length ? `<div class="small wrap" style="margin-top:4px">${x.files.length ? `${ic.doc} ${x.files.map(esc).join(" · ")}` : ""}${x.missing.length ? `${x.files.length ? " · " : ""}<span class="err-t">not delivered: ${x.missing.map(esc).join(", ")}</span>` : ""}</div>` : ""}${x.path ? `<div class="fi-x small muted" data-ex="${esc(x.path)}">${ex ? esc(ex) : ""}</div>` : ""}
        ${(x.meta || []).filter((v) => v && v !== "–").length ? `<div class="tiny faint" style="margin-top:4px">${x.meta.filter((v) => v && v !== "–").map(esc).join(" · ")}</div>` : ""}</div></a>`;
  }).join("");
  return `<div id="homefeed"><div class="section-h"><h2>Results</h2></div>
    <div class="chips scroll-x" style="margin-bottom:6px">${kinds.map(([k, l]) => `<button type="button" class="tag hf ${homeFilter === k ? "on" : ""}" data-hf="${k}">${l}</button>`).join("")}</div>
    ${rows || `<div class="card empty small">Nothing here yet. A result shows up the moment an agent finishes.</div>`}
    ${mine.length > items.length ? `<button type="button" class="btn sm ghost" id="hfmore" style="margin-top:8px">Show older (${mine.length - items.length} more)</button>` : ""}
    ${typeof explain === "function" ? explain("what-is-not-here-", `The stack's own work is not here: its health under Now, deploys under <a href="#/build">Code</a>, the agents' activity under <a href="#/swarm?tab=activity">Agents</a>.`, "What is not here") : ""}</div>`;
}

// the first lines of a result under its headline, fetched once per file
function loadExcerpts() {
  const want = [...new Set($$("[data-ex]").map((el) => el.dataset.ex))].filter((p) => !homeEx.has(p)).slice(0, 8);
  for (const p of want) {
    homeEx.set(p, "");
    api(`/api/file?path=${encodeURIComponent(p)}`).then((t) => {
      const body = String(t).replace(/^---\n[\s\S]*?\n---\n?/, "").split("\n").map((l) => l.trim())
        .filter((l) => l && !/^(#|\||---|>|!\[|_.*_$|\*\*Sources)/.test(l)).join(" ").replace(/\[\[([^\]|]+\|)?([^\]]+)\]\]/g, "$2").replace(/[*_`]/g, "");
      homeEx.set(p, body.length > 320 ? body.slice(0, 320).replace(/\s+\S*$/, "") + " …" : body);   /* cap: preview: the item opens the whole result */
      $$("[data-ex]").filter((el) => el.dataset.ex === p).forEach((el) => (el.textContent = homeEx.get(p)));
    }).catch(() => {});
  }
}

function homeHeadHtml() {
  const n = yoursN(), ideas = ideasN(), next = (S.missions || []).filter((m) => m.status === "active" && m.next_run).sort((a, b) => a.next_run.localeCompare(b.next_run))[0];
  const busy = (S.running ? 1 : 0) + (S.builds || []).filter((b) => ["working", "checking", "deploying"].includes(b.status)).length + (S.claude_tasks || []).filter((t) => t.status === "running").length;
  if (notConnected()) return `<p id="homehead">${day(new Date(), true)} · <b class="err-t">not connected</b>: what you see may be out of date</p>`;
  return `<p id="homehead">${day(new Date(), true)} · ${n ? `<b class="warn-t">${n} thing${n > 1 ? "s need" : " needs"} you</b>` : "nothing needs you"}${ideas ? ` · ${ideas} idea${ideas > 1 ? "s" : ""}` : ""} · ${busy ? `${busy} working now` : "all quiet"}${next ? ` · next: ${esc(next.title)} ${rel(next.next_run)}` : ""}</p>`;
}

function homeStatsHtml() {
  const sy = S.system || {}, today = new Date().toDateString();
  const runs = (S.missions || []).reduce((a, m) => a + (m.runs || []).filter((r) => r.started && new Date(r.started).toDateString() === today).length, 0);
  const pages = (S.missions || []).reduce((a, m) => a + (m.wiki_pages || 0), 0), active = (S.missions || []).filter((m) => m.status === "active").length;
  return `<div id="homestats" class="card pad hstats">
    <div><b>${active}</b><span>agents of yours</span></div><div><b>${runs}</b><span>runs today</span></div>
    <div><b>${tok(sy.tokens_today || 0)}</b><span>tokens today</span></div><div><b>${usd(sy.spend_total)}</b><span>paid, all time</span></div>
    <div><b>${pages}</b><span>wiki pages</span></div><div><b>${nf(sy.calls_today || 0)}</b><span>model calls today</span></div></div>`;
}

const HOME_TABS = [["today", "Today"], ["results", "Results"], ["overview", "Overview"]];
let homeTab = null;
function vHome() {
  const tab = homeTab || (homeTab = pref("mc-home-tab", "today"));
  view.innerHTML = `<div class="home">
  <div class="home-head">
    <div class="hero" style="margin-bottom:6px"><div><h1>${greet()}${S.viewer_name ? ", " + esc(String(S.viewer_name).split(" ")[0]) : ""}</h1>${homeHeadHtml()}</div></div>
    ${!Object.keys(gp.read).length && !Object.keys(gp.tried).length && !gp.hideTour ? `<div class="banner info tour" style="margin-bottom:10px">${ic.doc}<a class="grow" href="#/guide/first-ten-minutes"><b>New here?</b> Take the ten-minute tour of everything your stack can do.</a><button class="icon-btn" id="hidetour" title="Hide">${ic.x}</button></div>` : ""}
    <form class="askbar" id="askbar"><input class="input" name="q" autocomplete="off" placeholder="Ask anything, or say what to do"><button class="btn primary" type="submit" aria-label="Send">${ic.send || ic.next}<span>Send</span></button></form>
  </div>
  <nav class="seg homeseg" aria-label="Parts of Home">${HOME_TABS.map(([k, l]) => `<button type="button" data-ht="${k}" class="${tab === k ? "on" : ""}">${l}</button>`).join("")}</nav>
  <div class="home-pane home-today" data-hp="today" ${tab === "today" ? "" : "hidden"}>${needsHtml()}${nowHtml()}</div>
  <div class="home-pane" data-hp="results" ${tab === "results" ? "" : "hidden"}>${feedHtml()}</div>
  <div class="home-pane home-overview" data-hp="overview" ${tab === "overview" ? "" : "hidden"}>${devicesHtml()}${homeStatsHtml()}</div>
  </div>`;
  for (const id of ["homehead", "homeneeds", "homenow", "homedev", "homestats", "homefeed"]) homeLast[id] = document.getElementById(id)?.outerHTML;
  bindHome();
}

function bindHome() {
  const ht = $("#hidetour"); if (ht) ht.onclick = () => { gp.hideTour = 1; gsave(); ht.closest(".banner").remove(); };
  $$("[data-ht]").forEach((b) => (b.onclick = () => {     // the tab is remembered on this device, like the Stack page's
    homeTab = b.dataset.ht;
    setPref("mc-home-tab", homeTab);
    $$("[data-ht]").forEach((x) => x.classList.toggle("on", x === b));
    $$("[data-hp]").forEach((p) => (p.hidden = p.dataset.hp !== homeTab));
  }));
  const f = $("#askbar");
  if (f) f.onsubmit = (e) => {                            // TSK-02: one box: the assistant answers a question and starts a job as a task
    e.preventDefault();
    const v = f.q.value.trim();
    if (v) location.hash = `#/chat?prompt=${encodeURIComponent(v)}&send=1`;
  };
  $$("[data-hf]").forEach((b) => (b.onclick = () => { homeFilter = b.dataset.hf; homeShow = 12; const el = $("#homefeed"); el.outerHTML = feedHtml(); homeLast.homefeed = $("#homefeed").outerHTML; bindHome(); }));
  if ($("#hfmore")) $("#hfmore").onclick = () => { homeShow += 40; const el = $("#homefeed"); el.outerHTML = feedHtml(); homeLast.homefeed = $("#homefeed").outerHTML; bindHome(); };
  loadExcerpts();
}

// a live update on Home: only the parts whose content changed are replaced (no full redraw, no twitch)
// APP-38: Home never moves under your finger. While you are scrolled down or touching it, its updates wait, with no
// button and no message; back at the top of the page they come in (2 Nov: a new card came in above the one tapped and
// the tap opened another; 7 Nov: the owner found the button that announced them nonsense)
let homeTouch = 0, homeHeld = false;
window.addEventListener("touchstart", () => { homeTouch = Date.now(); }, { passive: true });
window.addEventListener("scroll", () => {                 // back at the top: what waited comes in
  if (window.scrollY < 60 && homeHeld) { homeHeld = false; if (route.name === "home") homeUpdate(true); }
}, { passive: true });
function homeUpdate(force) {
  const parts = [["homehead", homeHeadHtml], ["homeneeds", needsHtml], ["homenow", nowHtml], ["homedev", devicesHtml], ["homestats", homeStatsHtml], ["homefeed", feedHtml]];
  const hold = !force && (window.scrollY > 120 || Date.now() - homeTouch < 2500);
  let held = false;
  for (const [id, fn] of parts) {
    const el = document.getElementById(id), html = fn();
    if (!el || homeLast[id] === html) continue;
    if (hold) { held = true; continue; }
    el.outerHTML = html;
    homeLast[id] = html;
  }
  homeHeld = held;
  bindHome();
}

// ---------- the crew (ops/crew.py): the stack's housekeeping agents ----------
const CREW_AREAS = [["memory", "Memory"], ["skills", "Skills"], ["code", "Code and tests"], ["phone", "AI phone"], ["ops", "Operations"]];
const CREW_STATE = { ok: ["ok", "OK"], failed: ["failed", "Failed"], running: ["running", "Running"], never: ["archived", "Not run yet"], waiting: ["paused", "Waiting"] };
// Phone cleanup (ops/phone_agents.py): one step per item, each run on the AI phone only after its own Approve
function phoneStepsHtml(c) {
  const gbs = gb;
  const open = c.actions.filter((s) => s.status === "open" || s.status === "failed" || s.status === "approved");
  const done = c.actions.filter((s) => s.status === "done");
  const fresh = open.filter((s) => s.status !== "approved"), freshSize = fresh.reduce((a, s) => a + (s.size || 0), 0);
  const phoneUp = !!S.phone?.connected, approved = open.filter((s) => s.status === "approved" && !s.started).length;
  const waitLine = (s) => (phoneUp ? "Approved. It runs when its turn comes." : `Approved. It runs when the AI phone connects${s.expires ? `, if that is before ${clock(s.expires)}` : ""}.`);
  const row = (s) => `<li><div class="row between wrap" style="gap:8px;align-items:flex-start"><div style="flex:1 1 240px;min-width:0"><div class="small"><b>${esc(s.title)}</b> · ${gbs(s.size)}</div>
      <div class="tiny muted">${esc(s.why || "")}</div>${s.status === "approved" && !s.started ? `<div class="tiny muted">${esc(waitLine(s))}</div>` : s.result ? (phoneUp && /wireless debugging/i.test(s.result) ? `<div class="tiny muted">The AI phone was not connected then. It is now, so this can run.</div>` : `<div class="tiny ${s.status === "failed" ? "bad" : "muted"}">${esc(s.result)}</div>`) : ""}</div>
      ${s.status === "approved" ? (s.started ? `<span class="pill running"><span class="dot run"></span>On the AI phone…</span>` : `<div class="row" style="gap:6px;align-items:center"><span class="pill ok">${ic.check}Approved</span><button class="btn sm ghost" data-pundo="${esc(s.id)}">Undo</button></div>`)
        : s.status === "done" ? `<span class="pill ok">${ic.check}${gbs(s.freed || 0)} freed</span>`
        : `<div class="row" style="gap:6px"><button class="btn sm primary" data-pdo="${esc(s.id)}">${ic.check}${s.status === "failed" ? "Try again" : "Approve"}</button><button class="btn sm ghost" data-pdis="${esc(s.id)}">Dismiss</button></div>`}</div></li>`;
  return `<div class="card pad-l crews" style="margin-bottom:12px"><div class="row between wrap" style="gap:6px"><h2>${open.length ? `${open.length} cleanup step${open.length > 1 ? "s" : ""} for the AI phone` : "Cleanup steps"}</h2>
      ${c.free ? `<span class="tiny muted">${gbs(c.free)} free of ${gbs(c.total)}${c.freed_total ? ` · ${gbs(c.freed_total)} freed so far` : ""}</span>` : ""}</div>
    ${open.length && S.phone && !phoneUp ? `<a class="banner" href="#/phone" style="margin-top:10px">${ic.alert}<span class="grow"><b>The AI phone is not connected, so nothing runs yet.</b>${approved ? ` ${approved} approved step${approved > 1 ? "s" : ""} wait${approved > 1 ? "" : "s"} for it.` : ""} Fix it on its page.</span>${ic.next}</a>` : ""}
    ${fresh.length > 1 ? `<div class="row wrap" style="gap:8px;margin-top:10px;align-items:center"><button class="btn primary" data-pdoall="${esc(fresh.map((s) => s.id).join(","))}" data-n="${fresh.length}" data-size="${esc(gbs(freshSize))}">${ic.check}Approve all ${fresh.length} · ${gbs(freshSize)}</button><span class="tiny faint">${phoneUp ? "The AI phone does them one after another." : "They wait for the AI phone, then run one after another."}</span></div>` : ""}
    ${open.length ? `<ul class="crewf">${open.map(row).join("")}</ul>` : `<div class="small muted" style="margin-top:6px">Nothing waiting. The next weekly run looks again.</div>`}
    ${done.length ? `<details class="obsb"><summary class="small"><b>Done</b> <span class="muted">· ${done.length}</span></summary><ul class="crewf">${done.slice(-10).reverse().map(row).join("")}</ul></details>` : ""}
    ${explain("each-approve-runs-exactl", `Each Approve runs exactly that step once on the AI phone, with its block list and path checks. If the phone is not connected it waits up to 4 hours, then lapses. Undo works until the phone starts the step. Nothing is deleted without an Approve; you can't approve from the AI phone itself.`, "About this")}
    <a class="small" href="#/phone" style="display:inline-block;margin-top:8px">AI phone page ${ic.next}</a></div>`;
}
function bindCrew() {
  const nextUp = () => (S.phone?.connected ? "the AI phone does it when its turn comes" : "it waits for the AI phone to connect");
  const steps = (ids, patch) => {                                      // the row changes at once; the next state confirms it
    for (const s of (S.crew || []).find((a) => a.id === "phone-cleanup")?.actions || []) if (ids.includes(s.id)) Object.assign(s, patch);
    render();
  };
  const APPROVED = () => ({ status: "approved", started: false, result: "", expires: Date.now() / 1000 + 4 * 3600 });
  $$("[data-pundo]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (await act({ action: "phone_cleanup_undo", id: b.dataset.pundo }, "Undone: nothing ran, and the step is open again")) steps([b.dataset.pundo], { status: "open", result: "" }); else b.disabled = false; }));
  $$("[data-pdo]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (await act({ action: "phone_cleanup_do", id: b.dataset.pdo }, `Approved: ${nextUp()}. Undo stays until it starts`)) steps([b.dataset.pdo], APPROVED()); else b.disabled = false; }));
  $$("[data-pdis]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (await act({ action: "phone_cleanup_dismiss", id: b.dataset.pdis }, "Dismissed: the phone keeps it as it is")) steps([b.dataset.pdis], { status: "dismissed" }); else b.disabled = false; }));
  $$("[data-pdoall]").forEach((b) => (b.onclick = async () => {        // it deletes a lot at once: a second tap confirms, in place
    if (!b.dataset.armed) {
      b.dataset.armed = "1"; b.innerHTML = `${ic.check}Tap again: delete and uninstall all ${b.dataset.n} (${b.dataset.size})`;
      setTimeout(() => { if (b.isConnected && !b.disabled) { delete b.dataset.armed; b.innerHTML = `${ic.check}Approve all ${b.dataset.n} · ${b.dataset.size}`; } }, 6000);
      return;
    }
    b.disabled = true;
    if (!(await act({ action: "phone_cleanup_do_all", ids: b.dataset.pdoall.split(",") }, `Approved ${b.dataset.n} steps: ${S.phone?.connected ? "the AI phone works through them one after another" : "they wait for the AI phone to connect"}. Each has Undo until it starts`))) { b.disabled = false; return; }
    steps(b.dataset.pdoall.split(","), APPROVED());
  }));
  $$("[data-crun]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (!(await act({ action: "crew_run", id: b.dataset.crun }, "Started: it shows as running here until it is done"))) b.disabled = false; }));
  const forget = async (ids, btn) => { btn.disabled = true; const r = await act({ action: "crew_memory_forget", ids }, (x) => (x?.forgotten !== undefined ? `${x.forgotten} forgotten (reversible): no agent recalls them now` : "")); if (r?.forgotten === undefined) btn.disabled = false; };
  $$("[data-cforget]").forEach((b) => (b.onclick = () => forget([b.dataset.cforget], b)));
  $$("[data-cforgetall]").forEach((b) => (b.onclick = () => forget((S.crew.find((a) => a.id === "memory")?.suggestions || []).map((s) => s.id), b)));
  $$("[data-wundo]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (await act({ action: "mem_undo", id: b.dataset.wundo }, "Undone: memory is as it was before this write")) b.replaceWith(document.createTextNode("undone")); else b.disabled = false; }));
  $$("[data-kundo]").forEach((b) => (b.onclick = async () => { b.disabled = true; const r = await act({ action: "crew_memory_undo", change: b.dataset.kundo }, (x) => (x?.undone ? "Undone: the fact is as it was" : "")); if (!r?.undone) b.disabled = false; }));
}

const CREW_PRESETS = [["every", "5min", "every 5 minutes"], ["every", "10min", "every 10 minutes"], ["every", "1h", "every hour"],
  ["calendar", "*-*-* 03:30", "daily 03:30"], ["calendar", "*-*-* 07:30", "daily 07:30"], ["calendar", "Mon *-*-* 04:30", "Mondays 04:30"],
  ["calendar", "Sun *-*-* 04:00", "Sundays 04:00"], ["calendar", "*-*-01 09:00", "monthly, the 1st, 09:00"]];

// ---------- Agents (design "Agents in Mission Control", 28 Oct 2026): one list, one page for every agent ----------
// An agent is anything that works by itself on a schedule, an event or your request: a mission you gave the stack
// ("Yours") or a crew job that keeps it in shape ("Housekeeping"). "Mission" stays the word for the job; health is a
// colour on the card, not a second list. #/mission/<slug> and #/crew/<id> both open the same agent page.
let atab = "now";
const AGENT_TABS = [["now", "Overview"], ["history", "Runs"], ["memory", "Memory"], ["payoff", "Results"], ["settings", "Settings"]];   // a task's page's words (DEC-46)
// a mission's or a crew duty's page is its task's page (DEC-46): its task, when there is one, adds who worked on it
const taskOfPage = (kind, id) => (S?.tasks || []).find((t) => t.door === kind && t.ref === id);
const OLD_TAB = { overview: "now", outputs: "history", runs: "history", tasks: "agents" };            // links from before the agent page
const CREW_IC = { memory: "brain", skills: "tune", code: "code", ops: "pulse" };

function missionAgent(m) {
  const h = (S.health?.items || []).find((i) => i.kind === "mission" && i.slug === m.slug);
  const live = S.running?.slug === m.slug, q = (S.queue || []).find((x) => x.slug === m.slug);
  const needs = (m.needs || []).map((n) => n.split(":")).filter(([c, sc]) => !S.connections?.[c]?.grants?.[sc]).map(([c]) => `needs access to ${CONN_NAME[c] || c}`);
  if (m.awaits) needs.push(m.awaits);                                 // a proposal or an approval that waits for you
  if (live && S.phone?.pending) needs.push("waits for your OK on the phone");
  const last = (m.runs || []).find((r) => r.status !== "queued"), steps = live ? S.running.steps : null;
  return { key: `mission:${m.slug}`, kind: "mission", id: m.slug, href: `#/mission/${encodeURIComponent(m.slug)}`, group: "yours", title: m.title,
    icon: typeIcon(m.type), what: typeName(m.type) + (m.depth === "deep" ? " · deep research" : ""), live, queued: q?.status === "queued",
    waiting: q?.status === "waiting" ? q.retry_at || "" : null, parked: q?.status === "parked" ? q.waiting_for || "a slow step" : null, off: m.status !== "active", archived: m.status === "archived", status: m.status,
    schedule: m.schedule_text, next: m.status === "active" && m.next_run ? Date.parse(m.next_run) / 1000 : null,
    last: last?.started ? Date.parse(last.started) / 1000 : null, lastOk: last ? last.status !== "failed" : null,
    step: steps?.length ? `step ${Math.min(steps.length, steps.filter((s) => s.status === "done").length + 1)}/${steps.length}` : "",
    result: last ? last.summary || STATUS[last.status] || last.status : "", issues: h?.issues || [], success: h?.success_7d, needs };
}
function crewAgent(a) {
  const n = a.suggestions?.length || 0;
  return { key: `crew:${a.id}`, kind: "crew", id: a.id, href: `#/crew/${a.id}`, group: "housekeeping", title: a.name, icon: ic[CREW_IC[a.area]] || ic.layers,
    what: (CREW_AREAS.find(([k]) => k === a.area) || [0, "Crew"])[1], live: a.state === "running", queued: false,
    waiting: a.state === "waiting" ? "" : null, off: a.enabled === false, archived: false, status: a.state,
    schedule: (a.schedule || "on request") + (a.custom ? " (yours)" : ""), next: a.next || null, last: a.last || null,
    lastOk: a.state === "failed" ? false : a.last ? true : null, step: "", result: a.result || "", issues: a.issues || [], success: a.success_7d,
    often: !!(a.next && a.last && a.next - a.last <= 1800),            // every few minutes: its "next run" says nothing
    needs: n ? [`${n} memor${n > 1 ? "ies" : "y"} to look at`] : [] };
}
function agentHealth(a) {
  if (a.needs.length) return "needs";
  if (a.live) return "live";
  if (a.issues.some((i) => i.severity === "alert") || a.lastOk === false) return "bad";
  if (a.issues.length) return "warn";
  return a.off ? "off" : a.last ? "ok" : "never";
}
const agentRank = (a) => (a.needs.length ? 0 : a.live ? 1 : a.queued || a.parked || a.waiting != null ? 2 : a.off ? 5 : a.often ? 4 : 3);
const byUrgency = (x, y) => agentRank(x) - agentRank(y) || (x.next ?? 9e12) - (y.next ?? 9e12) || x.title.localeCompare(y.title);
const SEEN_TIP = 'title="Hides it here, from its count and from the Health doctor until it happens again. Nothing is fixed or deleted."';   // what Seen does, one hover or long-press away
// an engine's page: its agent's where it is one (Hermes (chat) is main, intake is intake), else Stack -> Health
const engineAgentOf = (name) => Object.entries(SW_ENGINE).find(([, v]) => v === name)?.[0];   // read on use: swarm.js defines SW_ENGINE
const engineHref = (h) => swAgentHref(engineAgentOf(h.name) || h.id) || "#/system?tab=health";
function engineAgent(h) {                             // an engine with open issues (its sessions roll up into it)
  return { key: `engine:${h.id}`, kind: "engine", id: h.id, href: engineHref(h), run: h.run, group: "housekeeping", title: h.name,
    icon: ic.layers, what: "Engine", live: false, queued: false, waiting: null, off: false, archived: false, status: "issues", schedule: "", next: null, last: null,
    lastOk: null, step: "", result: "", issues: h.issues || [], success: null, needs: [] };
}
const issueKeys = (as) => as.flatMap((a) => a.issues.map((i) => i.key)).filter(Boolean);
async function ackIssues(keys, btn) {
  if (!keys.length) return;
  if (btn) btn.disabled = true;
  const r = await act({ action: "health_ack", keys }, (x) => `${x.acknowledged} marked seen: hidden until it happens again`);
  if (r) render(true); else if (btn) btn.disabled = false;
}

// #/missions was the Agents tab: its missions are tasks now, its crew is Team's, its live part is Activity (DEC-46)
function vMissionsGo() {
  const f = route.q.get("f");
  location.replace(["housekeeping", "problems"].includes(f) ? "#/tasks?v=team&p=crew" : f === "live" ? "#/tasks?v=activity" : "#/tasks?v=tasks");
}
// #/new was the mission wizard: New task on the Tasks tab, with the kind it was opened for
function vNewGo() { const k = OLD_NEW_KIND[route.q.get("type")]; location.replace(`#/tasks?new=1${k ? `&kind=${k}` : ""}`); }
function agentCard(a) {
  const h = agentHealth(a);
  const chip = a.needs.length ? `<span class="achip needs">${esc(a.needs[0])}</span>`
    : a.live ? `<span class="achip live"><span class="dot run"></span>live${a.step ? " · " + esc(a.step) : ""}</span>`
    : a.parked ? `<span class="achip wait">waiting · ${esc(a.parked)}</span>`
    : a.waiting != null ? `<span class="achip wait">waiting${a.waiting ? " · retry " + clock(a.waiting) : ""}</span>`
    : a.queued ? `<span class="achip wait">queued</span>`
    : a.off ? `<span class="achip off">${a.archived ? "archived" : a.kind === "crew" ? "switched off" : "paused"}</span>`
    : a.often ? `<span class="achip">${ic.repeat}${esc(a.schedule.replace(/ \(yours\)$/, ""))}</span>`
    : a.next ? `<span class="achip">${ic.clock}${esc(when(a.next))}</span>` : "";
  const meta = [a.group === "housekeeping" ? "Crew · " + a.what : a.what, a.often ? "" : a.schedule, a.last ? `last ${when(a.last)}` : "never ran", a.success != null ? `${a.success}% ok` : ""].filter(Boolean).join(" · ");
  // the result unless an alert needs you: a note for the health doctor ("… called 3 times") never hides it (UX review 2026-10-30)
  const iss = a.issues.find((i) => i.severity === "alert"), line = iss?.text || a.result || a.issues[0]?.text;
  const cls = iss ? "err-t" : a.result ? "" : a.issues.length ? "warn-t" : "";
  if (a.kind === "engine") return `<div class="card agcard h-${h}" data-href="${a.href}" role="link" tabindex="0"><div class="agic">${a.icon}</div><div class="agbody">
    <div class="agrow"><a class="agt" href="${a.href}">${esc(a.title)}</a><button class="btn sm ghost" data-ack="${esc(issueKeys([a]).join(" "))}" ${SEEN_TIP}>Seen</button></div>
    <div class="tiny muted agmeta">Engine · ${a.issues.length} open issue${a.issues.length > 1 ? "s" : ""}${a.run ? ` · <a href="#/live/${encodeURIComponent(a.run)}">its last run</a>` : ""}</div>
    ${a.issues.map((i) => `<div class="small agres ${i.severity === "alert" ? "err-t" : "warn-t"}">${prose(i.text)}</div>`).join("")}</div></div>`;
  return `<a class="card agcard h-${h}" href="${a.href}"><div class="agic">${a.icon}</div><div class="agbody">
    <div class="agrow"><b class="agt">${esc(a.title)}</b>${chip}</div>
    <div class="tiny muted agmeta">${esc(meta)}</div>
    ${line ? `<div class="small agres ${cls}">${prose(line)}${a.issues.length - (iss ? 1 : 0) > 0 && (iss || a.result) ? ` <span class="faint">+${a.issues.length - (iss ? 1 : 0)} note${a.issues.length - (iss ? 1 : 0) > 1 ? "s" : ""}</span>` : ""}</div>` : ""}</div></a>`;
}

// ---------- the agent page: Now · History · Memory · Payoff · Settings, the same for missions and housekeeping ----------
function vMission() { vAgent("mission", route.args[0]); }
function vCrew() { vAgent("crew", route.args[0]); }
let agentSig = "";                        // what the open page shows of the state; onState redraws it only when this changes
function agentOf(kind, id) {
  if (kind === "mission") { const m = (S.missions || []).find((x) => x.slug === id); return m ? { A: missionAgent(m), m } : null; }
  const c = (S.crew || []).find((x) => x.id === id);
  return c ? { A: crewAgent(c), c } : null;
}
function agentSigOf() {
  const o = route.name === "mission" || route.name === "crew" ? agentOf(route.name, route.args[0]) : null;
  if (!o) return "";
  const { A, m, c } = o;
  return JSON.stringify([A.live, A.queued, A.waiting, A.status, A.needs, A.issues.map((i) => i.key), A.last, A.next, A.step, m?.runs?.[0]?.id, m?.runs?.[0]?.status, c?.suggestions?.length, c?.enabled, c?.schedule,
    c?.actions && [(c.actions || []).map((s) => [s.id, s.status, s.started, s.result, s.freed]), S.phone?.connected],   // PHN-24: a tap on a cleanup step shows
    m && (S.files?.missions?.[m.slug]?.files || []).map((f) => [f.sha, f.pinned, (f.deliveries || []).length]), m?.files_asked, m?.mail?.map((x) => [x.path, x.report])]);   // MIS-23: its files
}

function vAgent(kind, id) {
  const o = agentOf(kind, id);
  if (!o) { view.innerHTML = `<a class="back" href="#/tasks">${ic.back}Tasks</a><div class="card empty">No task called ${esc(id)}.</div>`; return; }
  const { A, m, c } = o;
  const t = route.q.get("tab"), task = taskOfPage(kind, id);
  const tabs = AGENT_TABS.concat(task ? [["agents", "Agents"]] : [], kind === "crew" && swIsCrew(c.id) && (S?.swarm?.cards || []).includes(c.id) ? [["team", "Its work"]] : []);   // one page per task
  if (t) { atab = tabs.some(([k]) => k === (OLD_TAB[t] || t)) ? OLD_TAB[t] || t : "now"; route.q.delete("tab"); }
  if (!tabs.some(([k]) => k === atab)) atab = "now";
  if (kind === "mission" && route.q.get("do") === "run" && !A.live && !A.queued && !A.archived) {     // Telegram's "Run again"
    history.replaceState(history.state, "", A.href); route.q.delete("do");
    if (confirm(`Run “${m.title}” now?`)) act({ action: "run", slug: m.slug }, "Run started: follow it here; the result lands on this page");
  }
  agentSig = agentSigOf();
  const busy = A.live || A.queued;
  const acts = kind === "mission" ? `
    ${!A.archived ? `<button class="btn primary" data-a="run" ${busy ? "disabled" : ""}>${ic.play}Run now</button>` : ""}
    ${!A.archived && m.type === "task" ? `<button class="btn" data-a="deep" ${busy ? "disabled" : ""}>${ic.layers}Deep run</button>` : ""}
    <a class="btn" href="#/chat?mission=${encodeURIComponent(m.slug)}">${ic.tune}Tune in chat</a>
    ${m.wiki_pages ? `<a class="btn" href="#/wiki?root=${encodeURIComponent(m.wiki)}&back=${encodeURIComponent(`${A.href}?tab=${atab}`)}">${ic.wiki}Wiki · ${m.wiki_pages}</a>` : ""}
    ${m.status === "active" ? `<button class="btn" data-a="pause">${ic.pause}Pause</button>` : ""}
    ${m.status === "paused" || A.archived ? `<button class="btn" data-a="resume">${ic.play}Resume</button>` : ""}
    ${!A.archived ? `<button class="btn ghost danger" data-a="archive">${ic.archive}Archive</button>` : ""}
    `
    : `<button class="btn primary" data-a="crew_run" ${A.live ? "disabled" : ""}>${ic.play}Run now</button>`;
  const pill = kind === "mission" ? statusPill(m) : (([cls, l]) => `<span class="pill ${cls}">${A.live ? '<span class="dot run"></span>' : ""}${l}</span>`)(CREW_STATE[c.state] || ["archived", c.state]);
  view.innerHTML = `<a class="back" href="${kind === "crew" ? "#/tasks?v=team&p=crew" : "#/tasks"}">${ic.back}${kind === "crew" ? "Crew" : "Tasks"}</a>
  <div class="aghead h-${agentHealth(A)}"><div class="agic lg">${A.icon}</div><div class="grow" style="min-width:0">
    <h1 class="agh1">${esc(A.title)}</h1>${kind === "mission" ? fromChat("mission:" + m.slug) : ""}
    <div class="row wrap small muted" style="gap:4px 8px;margin-top:6px">${pill}${kind === "mission" && m.files_asked?.length ? ((F) => `<a class="tag ${F.done < F.total ? "warn" : ""}" href="${A.href}?tab=payoff">${ic.doc}${F.done} of ${F.total} file${F.total > 1 ? "s" : ""} ready</a>`)(filesOf(m)) : ""}<span>${A.group === "yours" ? "Your task" : "The stack's task"} · ${esc(A.what)}</span><span>${ic.clock}${esc(A.schedule || "on request")}${A.next ? ` · next ${esc(when(A.next))}` : ""}</span></div>
    <div class="small muted agwhat">${prose(kind === "mission" ? (m.goal || "").replace(/[#*_>`]/g, "").split("\n").find((l) => l.trim()) || "" : c.what)}</div>
    ${task ? `<div data-tideas="${task.id}"></div>` : ""}
    ${m?.triggers?.length ? `<div class="chips" style="margin-top:8px">${m.triggers.map((x) => `<span class="tag trig">${ic.bolt}${esc(x.text)}</span>`).join("")}</div>` : ""}
  </div></div>
  ${m?.task ? `<div class="banner info" style="margin-top:12px">${ic.target}<span class="grow">${m.type === "shopping" ? `Its checks run as <a href="#/task/${m.task}">task #${m.task}</a>: each one is a run of the task. Proposals, your approval and the purchase stay here.` : `Its runs are <a href="#/task/${m.task}">task #${m.task}</a>'s, under the Conductor. Its topic, wiki and history stay here.`}</span></div>` : ""}
  ${A.needs.map((n) => `<div class="banner info" style="margin-top:12px">${ic.alert}<span class="grow"><b>Needs you:</b> ${esc(n)}</span></div>`).join("")}
  ${(() => {                                              // alerts on top; the health doctor's notes folded into one line (UX review 2026-10-30)
    const issue = (x) => `<div class="banner ${x.severity === "alert" ? "" : "note"} agissue" style="margin-top:8px">${ic.alert}<span class="grow wrap">${esc(x.text)}${x.run ? ` · <a href="#/live/${encodeURIComponent(x.run)}">the run</a>` : ""}<span class="tiny faint"> · ${x.severity === "alert" ? "alert" : "note"}</span></span><button class="btn sm ghost" data-ack="${esc(x.key || "")}" ${SEEN_TIP}>Seen</button></div>`;
    const alerts = A.issues.filter((x) => x.severity === "alert"), notes = A.issues.filter((x) => x.severity !== "alert");
    return alerts.map(issue).join("") + (notes.length ? `<details class="agnotes" style="margin-top:8px"><summary class="small muted">${notes.length} technical note${notes.length > 1 ? "s" : ""} for the health doctor (nothing for you to do)</summary>${notes.map(issue).join("")}</details>` : "")
      + (A.issues.length > 1 ? `<div class="row" style="justify-content:flex-end;margin-top:6px"><button class="linkbtn" data-ack="${esc(issueKeys([A]).join(" "))}" ${SEEN_TIP}>mark all ${A.issues.length} seen</button></div>` : "");
  })()}
  ${kind === "crew" && (S?.swarm?.cards || []).includes(c.id) ? `<div id="agcardbox" class="section"></div>` : ""}
  <div class="actions">${acts}</div>
  <div class="seg agtabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${atab === k ? "on" : ""}">${l}</button>`).join("")}</div>
  <div id="tabbody" class="section" style="margin-top:14px"></div>`;
  $$("[data-t]").forEach((b) => (b.onclick = () => { atab = b.dataset.t; history.replaceState(history.state, "", `${A.href}?tab=${atab}`); render(true); }));
  $$("[data-ack]").forEach((b) => (b.onclick = () => ackIssues(b.dataset.ack.split(" ").filter(Boolean), b)));
  bindTasks();
  $$("[data-a]").forEach((b) => (b.onclick = async () => {
    const a = b.dataset.a;
    if (a === "archive" && !confirm(`Archive “${m.title}”? It stops; all results stay in the vault.`)) return;
    b.disabled = true;
    const req = a === "crew_run" ? { action: "crew_run", id: c.id } : a === "deep" ? { action: "run", slug: m.slug, deep: true } : { action: a, slug: m.slug };
    if (!(await act(req, { run: "Run started: follow it here; the result lands on this page", deep: "Deep research started: it takes longer; the result lands on this page",
      pause: "Paused: it does not run until you resume it", resume: "Resumed: it runs again at its next time", archive: "Archived: it runs no more; its results stay",
      crew_run: "Started: it shows as running here until it is done" }[a]))) b.disabled = false;
  }));
  if (task) fillTaskIdeas($(`[data-tideas="${task.id}"]`), task.id);
  if ($("#agcardbox")) swTeamData().then((x) => {    // the agent's card on its page, as every agent's own page has it
    const a = x.who.find((w) => w.id === c.id), box = $("#agcardbox");
    if (a && box) { box.innerHTML = `<div class="swteam one">${swTile(a, x, false)}</div>`; swBindTiles(x.who); }
  }).catch(() => {});
  ({ now: agentNow, history: agentHistory, memory: agentMemory, payoff: agentPayoff, settings: agentSettings, team: (box) => swAgentPanel(box, c.id, true, false), agents: (box) => taskAgentsInto(box, task.id),
     })[atab]($("#tabbody"), kind, A, m, c);
}

// TSK-43: who worked on a mission's or a duty's task: the task page's Agents part (task.js), from the run record
async function taskAgentsInto(box, tid) {
  box.innerHTML = `<div class="skeleton" style="height:240px"></div>`;
  const d = await api(`/api/task/${tid}`).catch((e) => ({ error: e.message }));
  if (!box.isConnected) return;
  if (d.error && !d.id) { box.innerHTML = `<div class="card pad small muted">${esc(d.error)}</div>`; return; }
  taskAgents(box, d, d.activity || { agents: [], actions: [], memory: { read: [], write: [] }, edges: [] }, (d.steps || {})[String(d.occ || 1)] || []);
}

// MIS-28: what came to this topic from the owner's e-mail, and what came of each mail
function topicMailHtml(m) {
  const of = (x) => {
    if (!x.report) return `<span class="tag warn">Waiting for the next report</span>`;
    const d = (x.report.match(/\d{4}-\d{2}-\d{2}/) || [""])[0], link = `<a href="#/read?path=${encodeURIComponent(x.report + ".md")}&m=${encodeURIComponent(m.slug)}">the report of ${d ? day(d) : "that day"}</a>`;
    return x.cited ? `<span class="tag">Cited</span> <span class="tiny">in ${link}</span>` : `<span class="tag">Not used</span> <span class="tiny">read for ${link}; it had nothing the report needed</span>`;
  };
  return `<div class="card pad-l" id="agmail" style="margin-bottom:12px"><h2>From your e-mail</h2>
    <div class="small muted" style="margin-top:4px">Newsletters that name this topic. Each goes to the next report as a source it must name, and never as instructions; through the report it reaches the wiki.</div>
    <ul class="crewf">${m.mail.map((x) => `<li><a class="wrap" href="#/read?path=${encodeURIComponent(x.path)}&m=${encodeURIComponent(m.slug)}"><b>${esc(x.subject)}</b></a>
      <div class="tiny muted wrap">${esc(x.from)}${x.at ? ` · ${dt(x.at)}` : ""}</div>${x.why ? `<div class="tiny muted wrap">${esc(x.why)}</div>` : ""}
      <div style="margin-top:4px">${of(x)}</div></li>`).join("")}</ul>${moreOf(m.mail_total, m.mail.length)}</div>`;
}

// Now: what it needs from you, then the live log (or the latest run's), then the latest result
async function agentNow(body, kind, A, m, c) {
  const needs = (m?.needs || []).map((n) => n.split(":"));
  body.innerHTML = `${needs.length ? `<div class="card pad-l" style="margin-bottom:12px"><h2>Needs access</h2><div class="small muted" style="margin-top:4px">This mission uses your apps. Its tools refuse until you grant this; revoke any time (Stack → Connections).</div>
      <div class="stack" style="margin-top:10px;gap:10px">${needs.map(([cn, sc]) => grantRow(cn, sc, `${CONN_NAME[cn] || cn}`, S.connections?.[cn]?.grants?.[sc], m.slug)).join("")}</div></div>` : ""}
    ${c?.suggestions?.length ? `<div class="card pad-l crews" style="margin-bottom:12px"><div class="row between wrap" style="gap:6px"><h2>${c.suggestions.length} memor${c.suggestions.length > 1 ? "ies" : "y"} to look at</h2><button class="btn sm ghost" data-cforgetall="1">Forget all ${c.suggestions.length}</button></div>
      <ul class="crewf">${c.suggestions.map((s) => `<li><div class="small quote">${esc(s.text)}</div><div class="row between wrap" style="gap:6px"><span class="tiny muted">${esc(s.why)}${s.note ? " · " + esc(s.note) : ""}</span><button class="btn sm ghost" data-cforget="${esc(s.id)}">Forget</button></div></li>`).join("")}</ul>
      <div class="tiny faint">Forgetting retires the fact from recall; it stays in the archive and can be restored.</div></div>` : ""}
    ${c?.keeper ? keeperHtml(c.keeper) : ""}${c?.keeper ? memAgentHtml(c) : ""}
    ${m?.type === "shopping" ? shopMissionHtml(m) : ""}
    ${c?.actions?.length ? phoneStepsHtml(c) : ""}
    ${m?.mail?.length ? topicMailHtml(m) : ""}
    ${m?.outputs?.length && !A.live ? `<div class="card pad-l" id="latest" style="margin-bottom:12px"><h2>Latest result</h2><div class="muted small" style="margin-top:10px">Loading…</div></div>` : ""}
    <div id="agrun"><div class="skeleton" style="height:220px"></div></div>
    ${m?.outputs?.length && A.live ? `<div class="card pad-l section" id="latest"><h2>Latest result</h2><div class="muted small" style="margin-top:10px">Loading…</div></div>` : ""}`;
  if (c) bindCrew();
  if (m?.outputs?.length) loadInto($("#latest"), m.outputs[0], true);
  const el = $("#agrun");
  const r = m ? (A.live ? S.running : (m.runs || []).find((x) => x.status !== "queued")) : null;
  let rid = r ? `mission-run:${r.id}` : null;
  if (c) rid = (await api(`/api/rt/runs?agent=${encodeURIComponent("crew:" + c.id)}&limit=1`).catch(() => []))?.[0]?.run || null;
  if (rid && (await mountRun(el, rid, { compact: true }))) return;
  if (r && (await oldTimeline(el, r.id))) return;
  if (!el.isConnected) return;
  const lines = c?.log || [];
  el.innerHTML = lines.length ? `<div class="card pad-l"><div class="row between"><h2>Latest run</h2><span class="tiny faint">${A.last ? when(A.last) : ""}</span></div>${logHtml(plainLog(lines, A.last), { level: "all" })}</div>`
    : `<div class="card pad-l small muted">${A.last ? "This run has no readable log (runs are recorded from 28 October on)." : "It hasn't run yet. Its log shows here from the moment it starts."}</div>`;
}

// History: the runs, each with its readable log
async function agentHistory(body, kind, A, m, c) {
  if (m) {
    const st = m.stats || {};
    setTimeout(() => swMissionDays($("#mdays", body), m.slug), 0);      // its days from the telemetry history, like an agent's page
    body.innerHTML = `<div id="mdays"></div><div class="row wrap small muted" style="gap:4px 14px;margin-bottom:10px;margin-top:12px"><span><b class="text">${st.runs || 0}</b> runs in 30 d · ${st.ok || 0} ok · ${st.failed || 0} failed</span>${st.avg_seconds ? `<span>typically ${dur(st.avg_seconds)}</span>` : ""}${st.runs ? `<span>${tok(Math.round((st.tokens || 0) / st.runs))} tokens/run</span>` : ""}</div>
      ${m.runs?.length ? `<div class="card list hruns">${m.runs.map((r) => `<div class="hrun">
        <div class="row between wrap" style="gap:6px"><div class="row wrap" style="gap:6px"><span class="pill ${r.status}">${STATUS[r.status] || r.status}</span><span class="small muted">${dt(r.started)} · ${r.event ? "⚡ " + esc(r.event.trigger || "event") : TRIG[r.trigger] || r.trigger}${r.mode === "deep" ? " · deep" : r.mode === "alert" ? " · alert" : ""}</span></div>
          ${r.status !== "queued" ? `<div class="row" style="gap:6px"><button class="btn sm" data-hlog="${r.id}">${ic.pulse}Log</button>${r.output ? `<a class="btn sm ghost" href="#/read?path=${encodeURIComponent(r.output)}&m=${encodeURIComponent(m.slug)}">${ic.doc}Result</a>` : ""}<button class="btn sm ghost" data-raw="${r.id}">Raw</button></div>` : ""}</div>
        ${r.event ? `<div class="small muted">${esc(r.event.summary)}</div>` : ""}
        <div class="small">${esc(r.summary || "")}</div>${stepsHtml(r.steps)}
        <div class="tiny faint num">${dur(r.seconds)} · ${nf(r.calls)} model calls · ${tok(r.tokens)} tokens · ${usd(r.spend)}${r.models ? " · " + esc(r.models) : ""}</div>
        <div class="log" id="log-${r.id}" hidden></div><div class="tl" id="tl-${r.id}" hidden></div></div>`).join("")}</div>` : emptyState("No runs yet: each run shows here with its log and timeline.", `<a class="btn sm primary" href="#/mission/${encodeURIComponent(m.slug)}?do=run">Run it now</a>`, "card")}
      ${m.outputs?.length ? `<details class="card pad-l section"><summary><b>All results</b> <span class="muted small">· ${m.outputs.length}</span></summary><div class="list" style="margin-top:8px">${m.outputs.map((p) => {
        const d = p.match(/(\d{4}-\d{2}-\d{2})(?:-(\d{2})(\d{2}))?/) || [], alert = p.includes("/alerts/");
        const label = d[1] ? day(d[1]) + (d[2] ? `, ${d[2]}:${d[3]}` : "") : p;
        return `<a href="#/read?path=${encodeURIComponent(p)}&m=${encodeURIComponent(m.slug)}"><div class="ic ${alert ? "warn" : ""}">${alert ? ic.bolt : ic.doc}</div><div class="grow"><div class="ttl">${alert ? "Alert · " : ""}${esc(label)}</div><div class="sub wrap">${esc(p)}</div></div></a>`;
      }).join("")}</div></details>` : ""}`;
    $$("[data-hlog]").forEach((b) => (b.onclick = async () => {
      const el = $(`#tl-${b.dataset.hlog}`);
      if (!el.hidden) { el.hidden = true; clearInterval(rtTimer); rtES?.close(); return; }
      el.hidden = false; el.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
      if (!(await mountRun(el, `mission-run:${b.dataset.hlog}`, { compact: true })) && !(await oldTimeline(el, b.dataset.hlog))) el.innerHTML = `<div class="small muted">No log recorded for this run.</div>`;
    }));
    $$("[data-raw]").forEach((b) => (b.onclick = async () => {
      const el = $(`#log-${b.dataset.raw}`);
      if (!el.hidden) { el.hidden = true; return; }
      el.textContent = (await api(`/api/runlog/${b.dataset.raw}`).catch(() => "")) || "No raw output."; el.hidden = false;
    }));
    return;
  }
  body.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
  const [H, rt] = await Promise.all([api(`/api/crew/${c.id}`).catch(() => null), api(`/api/rt/runs?agent=${encodeURIComponent("crew:" + c.id)}&limit=40`).catch(() => [])]);
  if (!body.isConnected) return;
  if (!H || H.error) { body.innerHTML = `<div class="card pad-l small muted">The history appears within 5 minutes.</div>`; return; }
  const rtOf = (r) => (rt || []).find((x) => Math.abs(x.started - r.start) < 180);
  body.innerHTML = `<div class="row wrap small muted" style="gap:4px 14px;margin-bottom:10px"><span>last ${H.runs.length} run${H.runs.length === 1 ? "" : "s"}</span><span>updated ${rel(new Date(H.updated * 1000).toISOString())}</span></div>
    <div class="card list hruns">${H.runs.map((r, i) => `<div class="hrun"><div class="row between wrap" style="gap:6px"><div class="row wrap" style="gap:6px"><span class="pill ${r.state === "failed" ? "failed" : r.state === "ok" ? "ok" : "running"}">${r.state}</span><span class="small muted">${dt(r.start)} · ${dur(r.seconds)}</span></div>
      <button class="btn sm" data-clog="${i}">${ic.pulse}Log</button></div>${r.error ? `<div class="small err-t">${esc(r.error)}</div>` : ""}<div class="tl" id="cl-${i}" hidden></div></div>`).join("") || `<div class="small muted">No runs in the last 30 days.</div>`}</div>`;
  $$("[data-clog]").forEach((b) => (b.onclick = async () => {
    const r = H.runs[+b.dataset.clog], el = $(`#cl-${b.dataset.clog}`), x = rtOf(r);
    if (!el.hidden) { el.hidden = true; return; }
    el.hidden = false;
    if (x && (await mountRun(el, x.run, { compact: true }))) return;
    el.innerHTML = r.log.length ? logHtml(plainLog(r.log, r.start), { level: "all" }) : `<div class="tiny muted">It ran without output.</div>`;
  }));
}

// Memory: the agent's journal (vault agents/<agent>/MEMORY.md, ops/journal.py); every edit is a commit
async function agentMemory(body, kind, A, m) {
  body.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
  const path = `agents/${A.key.replace(":", "-")}/MEMORY.md`;
  const J = await api(`/api/file?path=${encodeURIComponent(path)}`).then((t) => (typeof t === "string" ? parseJournal(t) : null)).catch(() => null);
  if (!body.isConnected) return;
  const li = (sec, x) => `<li class="jline" data-sec="${sec}"><span class="grow jt">${esc(x)}</span><span class="jbtn"><button class="icon-btn" data-jedit title="Edit">${ic.tune}</button><button class="icon-btn" data-jforget title="Forget">${ic.x}</button></span></li>`;
  const notes = J?.notes || [], entries = (J?.entries || []).slice().reverse();
  body.innerHTML = `<div class="card pad-l"><div class="row between wrap" style="gap:6px"><h2>Standing notes</h2><span class="tiny faint">${notes.length} · kept until changed</span></div>
      <ul class="jlist">${notes.map((x) => li("notes", x)).join("") || `<li class="small muted">None yet. The memory curator folds old entries into them, or you add one here; an agent keeps a lesson with the memory tool's note.</li>`}</ul>
      <form class="row" id="jadd" style="gap:8px;margin-top:8px"><input class="input grow" name="t" placeholder="Add a note for its next runs" maxlength="300"><button class="btn sm primary">Add</button></form></div>
    <div class="card pad-l section"><div class="row between wrap" style="gap:6px"><h2>Journal</h2><span class="tiny faint">${entries.length} entr${entries.length === 1 ? "y" : "ies"} · one per run</span></div>
      ${entries.map((e) => `<div class="jentry"><div class="tiny muted jhead">${esc(e.head)}</div><ul class="jlist">${e.lines.map((x) => li("journal", x)).join("")}</ul></div>`).join("") || `<div class="small muted" style="margin-top:6px">Empty: every run writes an entry here when it ends (what it did, results, what failed and why, open questions).</div>`}</div>
    ${m?.notes ? `<details class="card pad-l section"><summary><b>Working state</b> <span class="small muted">· in its journal, replaced by every run</span></summary><div class="md" style="margin-top:8px">${md(m.notes.replace(/^# .*\n/, ""))}</div></details>` : ""}
    <div class="tiny faint section">${ic.doc}<span class="mono">${esc(path)}</span> in the vault. Read at the start of every run: the standing notes and the last 5 entries (about 1.5k tokens), with the wiki pages that match. Every change is a commit. ${how("missions", "Agent memory")}</div>`;
  $("#jadd").onsubmit = async (e) => {
    e.preventDefault();
    const t = e.target.t.value.trim();
    if (t && (await act({ action: "journal_note", agent: A.key, text: t, by: "you" }, "Note added: the agent reads it before its next run"))) render(true);
  };
  $$("[data-jedit]").forEach((b) => (b.onclick = () => {
    const row = b.closest(".jline"), old = row.querySelector(".jt").textContent;
    row.innerHTML = `<form class="row grow" style="gap:6px"><input class="input grow" value="${esc(old)}" maxlength="400"><button class="btn sm primary">Save</button><button type="button" class="btn sm ghost" data-cancel>Cancel</button></form>`;
    const f = row.querySelector("form");
    f.querySelector("input").focus();
    f.querySelector("[data-cancel]").onclick = () => render(true);
    f.onsubmit = async (e) => {
      e.preventDefault();
      const t = f.querySelector("input").value.trim();
      if (t && t !== old && (await act({ action: "journal_edit", agent: A.key, section: row.dataset.sec, old, text: t }, "Saved: the agent reads it from its next run"))) render(true);
    };
  }));
  $$("[data-jforget]").forEach((b) => (b.onclick = async () => {
    const row = b.closest(".jline"), old = row.querySelector(".jt").textContent;
    if (!confirm(`Forget this line?\n\n${old}\n\n(The vault's history keeps it.)`)) return;
    if (await act({ action: "journal_edit", agent: A.key, section: row.dataset.sec, old, text: "" }, "Forgotten: the agent no longer reads it")) render(true);
  }));
}

function parseJournal(text) {                          // the format ops/journal.py writes (and reads)
  const J = { notes: [], entries: [] };
  let sec = null;
  for (const ln of text.split("\n")) {
    if (ln.startsWith("## ")) sec = /standing/i.test(ln) ? "notes" : /journal/i.test(ln) ? "journal" : null;
    else if (ln.startsWith("### ") && sec === "journal") J.entries.push({ head: ln.slice(4).trim(), lines: [] });
    else if (ln.startsWith("- ") && ln.slice(2).trim()) {
      if (sec === "notes") J.notes.push(ln.slice(2).trim());
      else if (sec === "journal" && J.entries.length) J.entries[J.entries.length - 1].lines.push(ln.slice(2).trim());
    }
  }
  return J;
}

// ---------- MIS-23 to MIS-26: a mission's files, the things you asked for (docs/DELIVERABLES.md) ----------
const fileHref = (slug, name, v) => `#/file?m=${encodeURIComponent(slug)}&n=${encodeURIComponent(name)}${v ? `&v=${encodeURIComponent(v)}` : ""}`;
const fileUrl = (slug, name, v, dl) => `/api/files/${encodeURIComponent(slug)}/${encodeURIComponent(name)}?${v ? `v=${encodeURIComponent(v)}&` : ""}${dl ? "download=1" : ""}`;

// what a mission was asked to make and what it saved: {asked: [{name, what, file}], extra, done, total, last (the newest run's check)}
function filesOf(m) {
  const F = S?.files?.missions?.[m.slug] || { files: [], runs: {} };
  const by = Object.fromEntries(F.files.map((f) => [f.name, f]));
  const asked = (m.files_asked || []).map((a) => ({ ...a, file: by[a.name] }));
  const ids = Object.keys(F.runs || {}).map(Number).sort((a, b) => b - a);          // run ids: the newest first
  return { asked, extra: F.files.filter((f) => !asked.some((a) => a.name === f.name)), done: asked.filter((a) => a.file).length,
    total: asked.length, last: ids.length ? { id: ids[0], ...F.runs[ids[0]] } : null };
}

function deliveredHtml(f) {
  const last = {};
  for (const d of f.deliveries || []) if (!last[d.channel]) last[d.channel] = d;     // the newest per channel
  const words = { email: "E-mailed as attachment", telegram: "Sent on Telegram" };
  const parts = Object.entries(last).map(([ch, d]) => d.ok ? `<span class="ok-t">${words[ch] || ch} ✓ ${esc(when(d.ts))}</span>`
    : `<span class="err-t" title="${esc(d.why || "")}">${words[ch] || ch}: not sent${d.why ? ` (${esc(d.why)})` : ""}</span>`);
  return `<div class="tiny fc-sent">${parts.join(" · ") || "In the app (not sent yet)"}</div>`;
}

function fileCard(slug, f, a) {
  if (!f) return `<div class="fcard missing"><div class="fc-ic">${ic.alert}</div><div class="grow fc-body">
    <div class="fc-name"><b class="wrap">${esc(a.name)}</b><span class="pill failed">Asked for, not delivered</span></div>
    ${a.what ? `<div class="small muted wrap">${esc(a.what)}</div>` : ""}
    <div class="small wrap" style="margin-top:4px">${esc(a.why || "No run has saved it yet.")}</div>
    <div class="row wrap fc-acts"><button class="btn sm primary" data-frun="${esc(slug)}">${ic.play}Run again for it</button></div></div></div>`;
  const facts = [f.words ? `${nf(f.words)} words` : "", f.checkboxes ? `${nf(f.checkboxes)} checkboxes` : "", fsize(f.size),
    `updated ${when(f.updated)}`, f.versions?.length ? `version ${f.versions.length + 1}` : ""].filter(Boolean).join(" · ");
  return `<div class="fcard"><div class="fc-ic">${ic.doc}</div><div class="grow fc-body">
    <div class="fc-name"><a class="wrap" href="${fileHref(slug, f.name)}"><b>${esc(f.name)}</b></a><span class="pill ${f.final ? "ok" : "queued"}">${f.final ? "Final" : "Draft"}</span>${f.pinned ? `<span class="tag" title="Kept by the cleanup">Pinned</span>` : ""}</div>
    ${a?.what ? `<div class="small muted wrap">${esc(a.what)}</div>` : ""}<div class="small muted">${facts}</div>${deliveredHtml(f)}
    <div class="row wrap fc-acts"><a class="btn sm" href="${fileHref(slug, f.name)}">${ic.doc}Open</a><a class="btn sm" href="${fileUrl(slug, f.name, "", true)}" download="${esc(f.name)}">Download</a>
      <button class="btn sm ghost" data-fcopy="${esc(slug)}|${esc(f.name)}">Copy</button></div></div></div>`;
}

function bindFiles(root) {
  $$("[data-fcopy]", root).forEach((b) => (b.onclick = async () => {
    const [slug, name] = b.dataset.fcopy.split("|");
    const t = await api(fileUrl(slug, name)).catch(() => null);
    if (t && (await copyText(t))) toast(`Copied ${name}`); else toast("Could not copy it", true);
  }));
  $$("[data-frun]", root).forEach((b) => (b.onclick = () => { b.disabled = true; act({ action: "run", slug: b.dataset.frun }, "Run started: the files it saves land here"); }));
}

// Results: what you asked for first, then other files it saved, drafts it left in the Ledger, then the run reports
function filesSection(m) {
  const F = filesOf(m), why = F.last ? `The last run (#${F.last.id}) ended without saving it.` : "";
  if (!F.total && !F.extra.length) return m.type === "briefing" ? "" : `<div class="card pad-l"><h2>What you asked for</h2>
    <div class="small muted" style="margin-top:6px">No files asked of this mission. Name the files it should deliver under Settings (or tell Hermes when you make a mission): they land here, as a download and as e-mail attachments.</div></div>`;
  return `<div class="card pad-l"><div class="row between wrap" style="gap:8px"><h2>What you asked for</h2>
      <span class="tiny faint">${F.total ? `${F.done} of ${F.total} ready · ` : ""}<a href="#/files">All files</a></span></div>
    <div class="fcards">${F.asked.map((a) => fileCard(m.slug, a.file, { ...a, why })).join("")}</div>
    ${F.extra.length ? `<div class="tiny faint" style="margin:12px 0 6px">${F.total ? "Also saved" : "Files it saved"}</div><div class="fcards">${F.extra.map((f) => fileCard(m.slug, f)).join("")}</div>` : ""}</div>`;
}

async function draftsInto(el, m) {
  const D = await api(`/api/mission/${encodeURIComponent(m.slug)}/drafts`).catch(() => []);
  if (!el.isConnected || !Array.isArray(D) || !D.length) return;
  el.innerHTML = `<div class="card pad-l section"><div class="row between wrap" style="gap:8px"><h2>Drafts in the Ledger</h2><span class="tiny faint">${D.length} report${D.length > 1 ? "s" : ""} its runs wrote, newest first</span></div>
    <div class="small muted" style="margin-top:4px">Long texts the agent kept in the Ledger while it worked. A file above is the delivered version.</div>
    <div class="list" style="margin-top:6px">${D.map((d) => `<a href="#/swarm/artifact/${d.id}"><div class="ic">${ic.layers}</div><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(d.title)}</div><div class="sub">#${d.id} · ${esc(when(d.ts))}</div></div>${ic.next}</a>`).join("")}</div></div>`;
}

async function vFile() {
  const slug = route.q.get("m") || "", name = route.q.get("n") || "", v = route.q.get("v") || "";
  const m = (S?.missions || []).find((x) => x.slug === slug), f = (S?.files?.missions?.[slug]?.files || []).find((x) => x.name === name);
  const back = m ? `#/mission/${encodeURIComponent(slug)}?tab=payoff` : "#/files";
  if (!f) { view.innerHTML = `<a class="back" href="${back}">${ic.back}${m ? esc(m.title) : "Files"}</a><div class="card empty">${ic.doc}<div>No file ${esc(name)} here (it may be in the trash: <a href="#/files">Files</a>).</div></div>`; return; }
  const old = v ? (f.versions || []).find((x) => x.file === v) : null;
  view.innerHTML = `<a class="back" href="${back}">${ic.back}${m ? esc(m.title) : "Files"}</a>
    <div class="row wrap between" style="gap:8px;align-items:flex-start"><div style="min-width:0"><h1 class="wrap" style="font-size:22px">${esc(name)}</h1>
      <div class="small muted" style="margin-top:4px">${old ? `Earlier version of ${esc(when(old.ts))} · ${fsize(old.size)} · <a href="${fileHref(slug, name)}">open the current one</a>` : `${f.final ? "Final" : "Draft"} · ${nf(f.words)} words${f.checkboxes ? ` · ${nf(f.checkboxes)} checkboxes` : ""} · ${fsize(f.size)} · updated ${esc(when(f.updated))}`}</div>
      ${old ? "" : deliveredHtml(f)}</div>
      <div class="row wrap" style="gap:6px"><a class="btn sm primary" href="${fileUrl(slug, name, v, true)}" download>Download</a><button class="btn sm" id="fcopy">Copy</button>
        ${old ? "" : `<button class="btn sm ghost" id="fpin">${f.pinned ? "Unpin" : "Pin"}</button><button class="btn sm ghost danger" id="fdel">${ic.trash}Delete</button>`}</div></div>
    ${!old && f.versions?.length ? `<details class="card pad section"><summary class="small"><b>Earlier versions</b> · ${f.versions.length} kept (the newest ${S.files?.policy?.keep_versions || 5})</summary>
      <div class="list" style="margin-top:6px">${f.versions.map((x) => `<a href="${fileHref(slug, name, x.file)}"><div class="grow"><div class="ttl">${esc(when(x.ts))}</div><div class="sub">${fsize(x.size)}${x.run ? ` · run #${x.run}` : ""}</div></div>${ic.next}</a>`).join("")}</div></details>` : ""}
    <article class="card pad-l md reader section" id="fdoc"><div class="skeleton"></div></article>`;
  const text = await api(fileUrl(slug, name, v)).catch(() => null);
  if (route.name !== "file") return;
  $("#fdoc").innerHTML = text == null ? "Not readable." : name.toLowerCase().endsWith(".md") ? md(text) : `<pre class="wrap">${esc(text)}</pre>`;
  $("#fcopy").onclick = async () => toast((text != null && (await copyText(text))) ? `Copied ${name}` : "Could not copy it", text == null);
  $("#fpin") && ($("#fpin").onclick = () => act({ action: "file_pin", slug, name, on: !f.pinned }, f.pinned ? "Unpinned: the cleanup may remove it later" : "Pinned: the cleanup keeps it"));
  $("#fdel") && ($("#fdel").onclick = async () => {
    if (!confirm(`Delete ${name}? It goes to the trash with its versions; you can restore it on Files for ${S.files?.policy?.trash_days || 30} days.`)) return;
    if (await act({ action: "file_delete", slug, name }, "Moved to the trash: restore it on Files")) location.hash = back;
  });
}

// the Files page: every mission's files, how much space they take, the trash, and the cleanup (MIS-26)
function vFiles() {
  const F = S?.files || { missions: {}, trash: [], usage: { used: 0, trash: 0, quota: 1, pct: 0 }, policy: {} }, u = F.usage, p = F.policy;
  const title = (slug) => (S.missions || []).find((x) => x.slug === slug)?.title || slug;
  const groups = Object.entries(F.missions).filter(([, x]) => x.files.length).sort((a, b) => (b[1].files[0]?.updated || 0) - (a[1].files[0]?.updated || 0));
  const n = groups.reduce((k, [, x]) => k + x.files.length, 0);
  view.innerHTML = `<div class="hero heading"><h1>Files</h1></div>
    <div class="card pad-l"><div class="row between wrap" style="gap:8px"><h2>Space</h2><span class="tiny faint">${nf(n)} file${n === 1 ? "" : "s"} in ${groups.length} mission${groups.length === 1 ? "" : "s"}</span></div>
      <div class="fbar" title="${u.pct} % of ${fsize(u.quota)}"><span style="width:${Math.min(100, (100 * u.used) / u.quota)}%"></span><span class="tr" style="width:${Math.min(100, (100 * u.trash) / u.quota)}%"></span></div>
      <div class="small muted">${fsize(u.used)} in files · ${fsize(u.trash)} in the trash · ${u.pct} % of ${fsize(u.quota)}${u.pct >= 80 ? ` · <b class="err-t">nearly full: clean up</b>` : ""}</div>
      <div class="small" style="margin-top:10px">Kept until you delete them. Every day the cleanup removes versions beyond the newest ${p.keep_versions}, moves the files of missions archived ${p.archived_days} days ago (unless pinned) to the trash, and empties what has been in the trash ${p.trash_days} days.${F.last_cleanup ? ` Last cleanup ${esc(when(F.last_cleanup.ts))}: ${F.last_cleanup.steps} step${F.last_cleanup.steps === 1 ? "" : "s"}, ${fsize(F.last_cleanup.freed)} freed.` : ""}</div>
      <div class="row wrap" style="gap:8px;margin-top:10px"><button class="btn sm" id="fclean">Clean up now…</button></div><div id="fplan"></div></div>
    ${groups.map(([slug, x]) => `<div class="card pad-l section"><div class="row between wrap" style="gap:8px"><h2 class="wrap"><a href="#/mission/${encodeURIComponent(slug)}?tab=payoff">${esc(title(slug))}</a></h2><span class="tiny faint">${fsize(u.by_mission?.[slug] || 0)}</span></div>
      <div class="list" style="margin-top:6px">${x.files.map((f) => `<a href="${fileHref(slug, f.name)}"><div class="ic ok">${ic.doc}</div><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(f.name)}${f.pinned ? ` <span class="tag">Pinned</span>` : ""}</div>
        <div class="sub">${fsize(f.size)} · ${nf(f.words)} words · updated ${esc(when(f.updated))}${f.versions?.length ? ` · ${f.versions.length} earlier version${f.versions.length > 1 ? "s" : ""}` : ""}</div></div>${ic.next}</a>`).join("")}</div></div>`).join("")}
    ${!groups.length ? `<div class="card pad-l section empty">${ic.doc}<div>No files yet. Ask a mission for a document (in chat: “… and send me the spec as a Markdown file”) and it lands here.</div></div>` : ""}
    <div class="card pad-l section"><div class="row between wrap" style="gap:8px"><h2>Trash</h2><span class="tiny faint">emptied after ${p.trash_days} days</span></div>
      ${F.trash.length ? `<div class="list" style="margin-top:6px">${F.trash.map((t) => `<div class="litem"><div class="ic">${ic.trash}</div><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(t.name)} <span class="faint">· ${esc(title(t.slug))}</span></div>
        <div class="sub">${fsize(t.size)} · deleted ${esc(when(t.deleted))} (${esc(t.why)}) · gone for good ${esc(dt(t.purge_at))}</div></div><button class="btn sm" data-frestore="${esc(t.id)}">Restore</button></div>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">Empty.</div>`}</div>`;
  $$("[data-frestore]").forEach((b) => (b.onclick = () => { b.disabled = true; act({ action: "file_restore", id: b.dataset.frestore }, (r) => `Restored ${r.restored}: it is back under its mission's Results`); }));
  $("#fclean").onclick = async () => {
    const r = await act({ action: "files_cleanup", dry: true }, null);
    if (!r) return;
    $("#fplan").innerHTML = r.steps.length ? `<div class="card pad section"><b class="small">The cleanup would do ${r.steps.length} thing${r.steps.length > 1 ? "s" : ""}:</b>
      <ul class="small" style="margin:6px 0 0 18px">${r.steps.map((s) => `<li>${esc(s.what)}: ${esc(title(s.slug))} · ${esc(s.name)} (${fsize(s.size)})</li>`).join("")}</ul>
      <div class="row wrap" style="gap:8px;margin-top:10px"><button class="btn sm primary" id="fcleango">Clean up</button><button class="btn sm ghost" id="fcleanno">Cancel</button></div></div>`
      : `<div class="small muted" style="margin-top:8px">Nothing to clean up: everything is within the rules above.</div>`;
    $("#fcleanno") && ($("#fcleanno").onclick = () => ($("#fplan").innerHTML = ""));
    $("#fcleango") && ($("#fcleango").onclick = () => act({ action: "files_cleanup" }, (x) => `Cleaned up: ${fsize(x.freed)} freed`));
  };
}

// Payoff: what its runs cost and what came of them
async function agentPayoff(body, kind, A, m, c) {
  const h = (S.health?.items || []).find((i) => (m ? i.kind === "mission" && i.slug === m.slug : i.kind === "crew" && i.id === c.id));
  if (m) {
    const st = m.stats, okRate = st.runs ? Math.round((st.ok / st.runs) * 100) + "%" : "–";
    const done = (m.runs || []).filter((r) => r.output && r.status === "ok").slice(0, 12);   // cap: list (the newest; History has every run)
    body.innerHTML = `${filesSection(m)}<div id="fdrafts"></div>
    <div class="card pad-l section"><div class="row between wrap" style="gap:8px"><h2>Run reports</h2><span class="tiny faint">what each run did and found · ${m.outputs?.length || 0} in the vault, newest first</span></div>
      ${done.length ? `<div class="list" style="margin-top:6px">${done.map((r) => `<a href="#/read?path=${encodeURIComponent(r.output)}"><div class="ic ok">${ic.doc}</div>
        <div class="grow" style="min-width:0"><div class="ttl">${esc(when(r.ended || r.started))}${r.trigger === "event" ? ` <span class="tag trig">${ic.bolt}event</span>` : ""}${/^Partial: /.test(r.summary || "") ? ` <span class="pill paused">Partial</span>` : ""}</div>
        <div class="sub wrap">${esc(r.summary || "Open the result")}</div></div>${ic.next}</a>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">${m.task ? `Its runs are task #${m.task}'s now: <a href="#/task/${m.task}?tab=runs">their results are on the task</a>.` : "Nothing yet: its first result lands here."}</div>`}</div>
    ${h?.payoff ? `<div class="banner info section">${ic.coin}<span class="grow">${esc(h.payoff)}</span></div>` : ""}
    <div class="section-h section"><h2>What it took</h2><span class="tiny faint">the last 30 days</span></div>
    <div class="grid g2 g3">
      <div class="card stat"><div class="l">Runs (30 d)</div><div class="v">${st.runs}</div></div>
      <div class="card stat"><div class="l">Success</div><div class="v">${okRate}</div>${h?.success_7d != null ? `<div class="tiny faint">${h.success_7d}% in 7 d</div>` : ""}</div>
      <div class="card stat"><div class="l">Typical run</div><div class="v">${dur(st.avg_seconds)}</div></div>
      <div class="card stat"><div class="l">Model calls</div><div class="v">${nf(st.calls)}</div></div>
      <div class="card stat"><div class="l">Tokens (30 d)</div><div class="v">${tok(st.tokens)}</div></div>
      <div class="card stat"><div class="l">Paid (30 d)</div><div class="v">${usd(st.spend)}</div><div class="tiny faint">subscription only</div></div>
    </div>
    <div class="card pad section"><div class="row between wrap"><h2>Tokens per run</h2><span class="tiny faint">${st.runs_all} runs · ${tok(st.tokens_all)} tokens in all · amber = event run</span></div><div style="margin-top:10px">${bars(m.runs || [])}</div></div>
    <div class="grid g2 section"><div class="card stat"><div class="l">Wiki pages</div><div class="v">${m.wiki_pages || 0}</div>${m.wiki_pages ? `<a class="tiny" href="#/wiki?root=${encodeURIComponent(m.wiki)}&back=${encodeURIComponent(`${A.href}?tab=payoff`)}">open the wiki</a>` : ""}</div></div>`;
    bindFiles(body);
    draftsInto($("#fdrafts"), m);
    return;
  }
  body.innerHTML = `<div class="grid g2 g4" id="ckpi"><div class="skeleton" style="height:80px"></div></div>`;
  const H = await api(`/api/crew/${c.id}`).catch(() => null), kpi = $("#ckpi");
  if (!kpi) return;
  if (!H || H.error) { kpi.outerHTML = `<div class="card pad-l small muted">The numbers appear within 5 minutes.</div>`; return; }
  const st = H.stats || {}, p = H.payoff || {}, openKeys = new Set((S.health?.items || []).flatMap((h) => (h.issues || []).map((i) => i.key)));
  kpi.innerHTML = `<div class="card kpi"><div class="kpi-l">Runs (30 d)</div><div class="kpi-v">${st.runs}</div><div class="kpi-s">${st.ok} ok · ${st.failed} failed</div></div>
    <div class="card kpi"><div class="kpi-l">Success (7 d)</div><div class="kpi-v">${H.health?.success_7d != null ? H.health.success_7d + "%" : "–"}</div><div class="kpi-s">${H.health?.runs_7d || 0} runs</div></div>
    <div class="card kpi"><div class="kpi-l">Duration</div><div class="kpi-v" style="font-size:20px">${st.avg_s != null ? dur(st.avg_s) : "–"}</div><div class="kpi-s">longest ${st.max_s != null ? dur(st.max_s) : "–"}</div></div>
    <div class="card kpi"><div class="kpi-l">Payoff</div><div class="kpi-v" style="font-size:20px">${p.proposals != null ? p.proposals + " proposals" : st.ok + " runs ok"}</div><div class="kpi-s">${p.proposals != null ? `${p.accepted} accepted · <a href="#/build">${p.built} built</a> · ${p.dismissed} dismissed · ${p.open} open` : esc(H.payoff_text || "")}</div></div>`;
  const isPaused = (S.swarm?.paused || []).some((x) => x === c.id || x === "*");
  if ((S.swarm?.cards || []).includes(c.id)) kpi.insertAdjacentHTML("beforebegin", `<div class="row between wrap section" style="gap:8px">${isPaused ? `<span class="pill archived">Paused by you</span>` : `<span class="tiny faint">Runs on its schedule</span>`}
    ${(S.swarm?.paused || []).includes("*") ? `<span class="tiny faint">All agents are paused (Agents → Ideas → Rules)</span>` : `<button class="btn sm ghost" data-swpause="${esc(c.id)}" data-on="${isPaused ? "0" : "1"}">${isPaused ? "Resume" : "Pause"}</button>`}</div>`);
  bindSwarmPause();
  const openProps = (S.swarm?.board?.open || []).filter((x) => x.owner === c.id).length;   // its ideas still open, not the last run's count
  const sc = (S.swarm?.scorecards || {})[c.id], pct = (v) => (v == null ? "–" : Math.round(v * 100) + "%");
  if (sc) kpi.insertAdjacentHTML("afterend", `<div class="card pad-l section"><div class="row between wrap"><h2>Scorecard</h2><span class="tiny faint">from the swarm's Ledger</span></div>
    <div class="grid g2 g4" style="margin-top:8px"><div><div class="tiny faint">Ideas</div><b>${sc.ideas}</b> <span class="tiny faint">${sc.new_30d} in 30 d</span></div>
      <div><div class="tiny faint">Accepted</div><b>${pct(sc.accepted_share)}</b> <span class="tiny faint">${sc.accepted}</span></div>
      <div><div class="tiny faint">Proven</div><b>${pct(sc.proven_share)}</b> <span class="tiny faint">${sc.proven} of ${sc.accepted}</span></div>
      <div><div class="tiny faint">Came back</div><b>${pct(sc.reopen_rate)}</b> <span class="tiny faint">${sc.reopened} reopened</span></div></div>
    <div class="tiny faint" style="margin-top:8px">${sc.refined} times it refined a known idea instead of copying it${sc.refusals_24h ? ` · ${sc.refusals_24h} refused writes today` : ""}<span id="sccost"></span></div>
    ${sc.decline_reasons?.length ? `<div class="small" style="margin-top:8px">Why you declined its ideas:<ul class="crewf">${sc.decline_reasons.map(([r, n]) => `<li>${esc(r)}${n > 1 ? ` <span class="faint">(${n}×)</span>` : ""}</li>`).join("")}</ul></div>` : ""}</div>`);
  kpi.insertAdjacentHTML("afterend", `${openProps ? `<a class="banner info section" href="#/tasks?v=ideas">${ic.next}<span class="grow">${openProps} open idea${openProps > 1 ? "s" : ""} of its own under Agents → Ideas</span></a>` : ""}
    ${c.findings?.length ? `<div class="card pad-l section"><h2>Last findings</h2><ul class="crewf">${c.findings.map((f) => `<li><span class="tag">${esc(f.kind || "")}</span> ${f.file ? `<span class="mono tiny">${esc(f.file)}${f.line ? ":" + f.line : ""}</span> ` : ""}${esc(f.issue || "")}${f.proposal ? ` <a class="tiny" href="#/tasks?v=ideas">idea: ${esc(f.proposal)}</a>` : ""}${f.acknowledge && openKeys.has(f.key) ? ` <button class="btn sm ghost" data-ack="${esc(f.key)}" ${SEEN_TIP}>Seen</button>` : ""}</li>`).join("")}</ul></div>` : ""}`);
  $$("[data-ack]").forEach((b) => (b.onclick = () => ackIssues(b.dataset.ack.split(" ").filter(Boolean), b)));   // the health doctor: expected or noise
  if (sc && $("#sccost")) api("/api/swarm/tokens").then((t) => {          // cost: its runs' tokens (subscription: the usage limit, not money)
    const n = (t || {})[c.id] || 0;
    if (n && $("#sccost")) $("#sccost").textContent = ` · ${tok(n)} tokens in 30 d` + (sc.proven ? `, ${tok(Math.round(n / sc.proven))} per proved idea` : ", none proved yet");
  }).catch(() => {});
}

// Settings: the mission's form, or the crew job's schedule
function agentSettings(body, kind, A, m, c) {
  if (m) {
    settingsForm(body, m);
    if (m.type === "shopping") body.insertAdjacentHTML("afterbegin", shopLimitsHtml());
    return;
  }
  const id = c.id;
  body.innerHTML = `<div class="card pad-l"><h2>Schedule</h2>${c.schedule === "on request" && !c.custom ? `<div class="small muted" style="margin-top:6px">Runs when the stack needs it; no schedule to set.</div>` : `
    <div class="small" style="margin-top:6px">Now: <b>${esc(c.schedule || "")}</b>${c.custom ? " (your setting)" : ""}</div>
    <label class="field"><span>Run</span><select class="input" id="cpre">${CREW_PRESETS.map(([k, v, l]) => `<option value="${k}|${v}" ${l.replace(" minutes", "min").replace(" hour", "1h") === c.schedule || l === c.schedule ? "selected" : ""}>${l}</option>`).join("")}<option value="custom">custom…</option></select></label>
    <input class="input" id="ccustom" placeholder="e.g. 2h, or Tue *-*-* 05:00" hidden>
    <div class="row wrap" style="gap:8px;margin-top:8px"><button class="btn sm primary" id="csave">Save schedule</button>${c.custom ? `<button class="btn sm ghost" id="creset">Back to the default</button>` : ""}</div>
    <label class="switch" style="margin-top:12px"><span><b>Switched on</b><div class="small muted">Off: it doesn't run on its schedule (Run now still works)</div></span><input type="checkbox" id="con" ${c.enabled === false ? "" : "checked"}></label>`}</div>`;
  const pre = $("#cpre");
  if (!pre) return;
  pre.onchange = () => ($("#ccustom").hidden = pre.value !== "custom");
  $("#csave").onclick = async () => {
    let [k, value] = pre.value.split("|");
    if (pre.value === "custom") { value = $("#ccustom").value.trim(); k = /^\d+\s*(s|min|h|d)$/.test(value) ? "every" : "calendar"; }
    await act({ action: "crew_schedule", id, kind: k, value }, (x) => (x?.schedule ? `Now ${x.schedule}: its next run follows it` : ""));
  };
  if ($("#creset")) $("#creset").onclick = async () => { await act({ action: "crew_schedule", id, kind: "reset" }, (x) => (x?.schedule ? `Back to ${x.schedule}: its next run follows it` : "")); };
  $("#con").onchange = async (e) => { const r = await act({ action: "crew_schedule", id, enabled: e.target.checked }, e.target.checked ? "On: it runs at its next time" : "Off: it does not run until you turn it on"); if (!r) e.target.checked = !e.target.checked; };
}

