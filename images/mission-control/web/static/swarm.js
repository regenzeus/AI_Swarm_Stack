// The agents' views, drawn inside the six places (APP-67): Activity on Home (the room: what the agents do together, with
// filters, and the run timeline under them; "working now" above it), the agents on Agents (each with its own page,
// #/swarm/agent/<id> or its scheduled job's page), the map inside Agents → Who works with whom, and the proposals on
// Improve (ideas, the graph of approved ideas, the loop's numbers); an idea's full timeline is #/swarm/artifact/<id>.
// #/swarm?tab=<view> is an old address: it goes to that view's place (through #/tasks, app-base.js MOVED). Reads through /api/swarm (Mission
// Control's read-only door to the Swarm service); the owner's posts go through the runner (action swarm_post), like every
// other action of the owner's. Requirements SWM-10, SWM-11, SWM-57, SWM-58.
// Phase 4: Now (who works on what this minute, the merge queue, the file leases: SWM-97, SWM-92, SWM-93), Tasks (the task
// graph of approved ideas: SWM-91), Flow (weekly proposed, accepted, proved, lead time, tokens per proved idea: SWM-99).
// Phase 5: Improve (agent changes with their experiments, the watch, replay sets, failure classes, requirements: SWM-18,
// SWM-20, SWM-82 to SWM-84).
let swTab = "now", swCtx = "", swTimer = null, swLastSig = "";

async function swApi(op, args = {}) {
  const r = await api("/api/swarm", { method: "POST", body: JSON.stringify({ op, args }) });
  if (!r || r.ok === false) throw new Error(r?.refused || r?.error || "the agents' Ledger is not reachable");
  return r.result;
}

function swWho(x) { return x === "owner" || String(x).startsWith("owner") ? "you" : x; }
function swCtxName(c) {
  if (!c) return "";
  if (c.startsWith("room:")) return "#" + c.slice(5);
  if (c.startsWith("artifact:")) return "idea #" + c.slice(9);
  if (c.startsWith("dm:")) return c.slice(3).split("+").map(swWho).join(" ↔ ");
  if (c.startsWith("calls:")) return c.slice(6).split("+").map((x) => (typeof swName === "function" ? swName(x) : x)).join(" ↔ ") + " (tool calls)";
  return c.replace(/^group:/, "").split("+").map(swWho).join(", ");
}
function swTime(ts) { return ts ? dt(ts) : ""; }

const SW_ALIAS = { chat: "activity", timeline: "activity", tasks: "improve", flow: "improve", graph: "map" };   // links from before the four views
// an old #/swarm?tab= address -> its view on the Tasks tab (the room's filters come along)
const SW_VIEW = { activity: "activity", agents: "team", map: "network", improve: "ideas", now: "activity", list: "tasks" };
function vSwarm() {                                  // render() calls views without arguments; view is app.js's #view
  clearInterval(swTimer);
  if (route.args[0] === "artifact") return swArtifact(view, +route.args[1]);
  if (route.args[0] === "agent") return location.replace(`#/agent/${encodeURIComponent(decodeURIComponent(route.args[1] || ""))}`);   // an old address: its page (APP-76)
  const asked = route.q.get("tab") || "activity", q = new URLSearchParams(route.q);
  q.delete("tab");
  q.set("v", SW_VIEW[SW_ALIAS[asked] || asked] || "activity");
  if (SW_VIEW[SW_ALIAS[asked] || asked] === "network") q.set("m", "team");
  if (["tasks", "flow"].includes(asked)) q.set("at", asked);
  location.replace("#/tasks?" + q.toString().replace(/%2C/g, ","));
}
// is its place still showing this view of the agents? (a view's timer stops when you leave it)
const SW_PLACE = { activity: "home", ideas: "ideas", network: "agents", team: "agents", agents: "agents" };
const swOn = (v) => route.name === SW_PLACE[v] && tasksView === v && (v !== "activity" || homeTab === "activity");
async function swRender(body, tab, asked = "") {     // the agents' views, drawn into a box of their place
  clearInterval(swTimer);
  swTab = tab;
  if (tab === "activity") swActivityFromUrl();
  try {
    if (tab === "agents") return await swAgents(body);
    if (tab === "map") {                               // APP-47: its own view: above the missions it pushed them 1,300 pixels down
      body.innerHTML = `<div id="ovmap"><div class="card pad-l"><div class="skeleton" style="height:320px"></div></div></div>`;
      swMapMount(true);
      swTimer = setInterval(() => (swOn("network") && netMode === "team" ? swMapMount() : clearInterval(swTimer)), 30000);
      return;
    }
    if (tab === "improve") {
      body.innerHTML = `<div id="swideas"></div><div class="section-h section" id="swtasksh"><h2>Being built</h2><span class="tiny faint">approved ideas split into parts</span></div><div id="swtasks"></div>
        <details class="card pad-l section" id="swflowd"${asked === "flow" ? " open" : ""}><summary><b>The improvement loop in numbers</b> <span class="small muted">ideas per week, replay sets, failures, requirements</span></summary><div id="swflow" style="margin-top:8px"></div></details>`;
      swIdeas($("#swideas"));
      swTasks($("#swtasks"));
      swFlow($("#swflow"));
      if (asked === "tasks" || asked === "flow") setTimeout(() => $(asked === "tasks" ? "#swtasksh" : "#swflowd")?.scrollIntoView({ block: "start" }), 60);
      swTimer = setInterval(() => (swOn("ideas") ? swIdeas($("#swideas"), true) : clearInterval(swTimer)), 8000);
      return;
    }
    await swActivity(body);
    swTimer = setInterval(() => (swOn("activity") ? swActivity(body, true) : clearInterval(swTimer)), 4000);
  } catch (e) {
    body.innerHTML = `<div class="card pad-l small muted">${esc(e.message)}</div>`;
  }
}
// Activity's filters come from the address (a tapped dot or line, Needs you, a reload) and go back into it; a filter set
// once no longer sticks to later visits (the owner's review of 1 Nov 2026: the Chatroom stayed empty until a reload)
function swActivityFromUrl() {
  const q = route.q;
  swCtx = q.get("ctx") || "";
  if (swCtx.startsWith("calls:")) { swRoomF.agents = new Set(swCtx.slice(6).split(/[+ ]/).filter(Boolean)); swCtx = ""; }   // the old map's rows ("+" reads as a space)
  else swRoomF.agents = new Set((q.get("agents") || "").split(",").filter(Boolean));
  swRoomF.types = new Set();                             // none picked: all of it (routine status only when about someone)
  swRoomF.tests = q.get("tests") === "1";
  const h = +q.get("h");
  swRoomF.hours = [6, 24, 72, 168].includes(h) ? h : swRoomF.agents.size ? 168 : 24;
  swRoomShow = 120;
  swLastSig = "";
}
function swSyncUrl() {
  const p = new URLSearchParams({ tab: "activity" });
  if (swRoomF.agents.size) p.set("agents", [...swRoomF.agents].join(","));
  if (swRoomF.hours !== 24) p.set("h", swRoomF.hours);
  if (swRoomF.tests) p.set("tests", "1");
  if (swCtx) p.set("ctx", swCtx);
  route.q = p;
  history.replaceState(history.state, "", "#/home?" + p.toString().replace(/%2C/g, ","));
}
let swTlBox = null;                                  // the run timeline sits under the filters, which it shares with the room
async function swActivity(body, poll = false) {
  if (!swTlBox) { swTlBox = document.createElement("div"); swTlBox.id = "swacttl"; swTlBox.className = "section"; }
  await swChat(body, poll);
  if (!poll || Date.now() - (swActivity.t || 0) > 20000) { swActivity.t = Date.now(); await swTimeline(swTlBox, poll); }
}
function swOverview() {                              // Activity's live part (app.js vTasks): who works now, above the room
  const nb = $("#ovnow");
  if (nb) swNow(nb);
}

// ---------- who is working right now (SWM-97), the merge queue (SWM-93) and the file leases (SWM-92) ----------
function swRunOn(r) {                                // what a live run works on, from its run id and the builds
  const m = /^build:(\d+)/.exec(r.run || r.ref || "");
  if (m) {
    const b = (S?.builds || []).find((x) => x.id === +m[1]);
    return b ? `<a href="#/build/${b.id}">build #${b.id} ${esc(b.title)}</a>${b.task ? ` · part <a href="#/swarm/artifact/${b.task}">#${b.task}</a>` : ""}${b.idea ? ` of idea <a href="#/swarm/artifact/${b.idea}">#${b.idea}</a>` : ""}${b.slot ? ` · slot ${b.slot}` : ""}` : `build #${m[1]}`;
  }
  return esc(r.title || r.name || "");
}
async function swNow(body) {
  if (swNow.html && !body.dataset.sig) body.innerHTML = swNow.html;     // the last view at once: a live redraw does not blink
  const live = await api("/api/swarm/now").catch(() => []);
  const sig = JSON.stringify([live.map((r) => [r.run, r.tokens]), (S?.builds || []).map((b) => [b.id, b.status, b.queue_pos]), S?.swarm?.leases, swNow.open]);
  if (sig === body.dataset.sig) return;
  body.dataset.sig = sig;
  const queue = (S?.builds || []).filter((b) => b.queue_pos).sort((a, b) => a.queue_pos - b.queue_pos);
  const waiting = (S?.builds || []).filter((b) => ["planned", "queued", "planning"].includes(b.status));
  const leases = S?.swarm?.leases || [];
  body.innerHTML = swNow.html = `<div class="card pad-l section"><h2>Working now <span class="hcount">${live.length}</span></h2>
    ${live.length ? `<div class="list" style="margin-top:6px">${live.map((r) => `<a href="#/live/${encodeURIComponent(r.run)}"><div class="ic run"><span class="spin" style="width:12px;height:12px"></span></div>
      <div class="grow" style="min-width:0"><div class="ttl">${esc(r.agent || "agent")}</div><div class="sub">${swRunOn(r)}</div>
      <div class="tiny faint">since ${swTime(r.started)} · ${tok(r.tokens || 0)} tokens so far · ${r.calls || 0} model calls</div></div>${ic.next}</a>`).join("")}</div>`
      : `<div class="small muted" style="margin-top:6px">No agent is running this minute.</div>`}
    <details class="swbuilds" style="margin-top:8px"${swNow.open ? " open" : ""}><summary class="small"><b>Builds</b> <span class="muted">${queue.length} in the merge queue · ${waiting.length} waiting · ${leases.length} file${leases.length === 1 ? "" : "s"} held</span></summary>
      <div class="small" style="margin-top:8px"><b>Merge queue</b> <span class="muted">Approved builds land one at a time, in the order you approved them; each is checked again on today's main when main moved.</span></div>
      ${queue.length ? `<div class="list" style="margin-top:4px">${queue.map((b) => `<a href="#/build/${b.id}"><div class="ic">${b.queue_pos}</div><div class="grow"><div class="ttl">#${b.id} ${esc(b.title)}</div>
        <div class="sub">${esc(BSTATUS[b.status] || b.status)}${b.approve_on_ci ? " · waits for CI" : ""}${b.note ? ` · ${esc(b.note)}` : ""}</div></div>${ic.next}</a>`).join("")}</div>` : `<div class="small muted">Empty.</div>`}
      <div class="small" style="margin-top:10px"><b>Waiting to start</b></div>${waiting.length ? `<div class="list" style="margin-top:4px">${waiting.map((b) => `<a href="#/build/${b.id}"><div class="grow"><div class="ttl">#${b.id} ${esc(b.title)}</div>
        <div class="sub">${esc(BSTATUS[b.status] || b.status)}${b.note ? ` · ${esc(b.note)}` : ""}</div></div>${ic.next}</a>`).join("")}</div>` : `<div class="small muted">Nothing waits.</div>`}
      <div class="small" style="margin-top:10px"><b>Files held by builds</b> <span class="muted">A build holds the files of its part while it works, so parallel builders never change the same file; a lease ends with its build or after 4 hours.</span></div>
      ${leases.length ? `<div class="list" style="margin-top:4px">${leases.map((l) => `<div style="padding:6px 2px"><div class="grow"><span class="mono small">${esc(l.path)}</span> <span class="tiny faint">${esc(l.repo)} · ${esc(l.holder)}${l.task ? ` · part #${l.task}` : ""} · until ${swTime(l.expires)}</span></div></div>`).join("")}</div>` : `<div class="small muted">No files are held.</div>`}
    </details></div>`;
  const d = $("details.swbuilds", body);
  if (d) d.ontoggle = () => { swNow.open = d.open; };
}

// ---------- the task graph of approved ideas (SWM-91) ----------
const SW_COL = [["open", "Waits for others"], ["ready", "Ready"], ["active", "Being built"], ["done", "Merged"]];
function swTasks(body) {
  const tasks = S?.swarm?.tasks || [], by = {};
  for (const t of tasks) (by[t.idea] = by[t.idea] || []).push(t);
  const ideas = Object.keys(by).sort((a, b) => b - a);
  body.innerHTML = ideas.length ? ideas.map((i) => {
    const ts = by[i], name = (id) => `#${id}`;
    return `<div class="card pad-l section"><div class="row between wrap"><h2><a href="#/swarm/artifact/${i}">Idea #${i}</a></h2><span class="tiny faint">${ts.length} task${ts.length > 1 ? "s" : ""} · ${ts.filter((t) => t.state === "done").length} merged</span></div>
      <div class="swcols">${SW_COL.map(([st, label]) => `<div class="swcol"><div class="tiny faint" style="margin-bottom:4px">${label}</div>${ts.filter((t) => t.state === st || (st === "open" && ["blocked", "draft"].includes(t.state))).map((t) => `<a class="swtask" href="#/swarm/artifact/${t.id}">
        <div class="small"><b>#${t.id}</b> ${esc(t.title)}</div><div class="tiny faint wrap">${t.files.map(esc).join(", ") || "no files named"}</div>
        ${t.depends_on.length ? `<div class="tiny">after ${t.depends_on.map(name).join(", ")}</div>` : ""}${t.builds.length ? `<div class="tiny">build ${t.builds.map((b) => "#" + b).join(", ")}</div>` : ""}</a>`).join("") || `<div class="tiny faint">–</div>`}</div>`).join("")}</div></div>`;
  }).join("") : `<div class="card pad-l small muted">Nothing split yet: when you tap Build it on an idea whose files span more than one area, it is split into parts here, and builders take the ready ones at the same time.</div>`;
}

// ---------- flow metrics (SWM-99) ----------
function swFlow(body) {
  const w = S?.swarm?.flow || [];
  if (!w.length) { body.innerHTML = `<div class="card pad-l small muted">No flow numbers yet.</div>${swLoopNumbers()}`; return; }
  const max = Math.max(1, ...w.map((x) => Math.max(x.proposed, x.accepted, x.proved)));
  const bar = (v, c) => `<span style="display:inline-block;height:8px;width:${Math.round((60 * v) / max)}px;background:${c};border-radius:4px;vertical-align:middle"></span> ${v}`;
  body.innerHTML = `<div class="card pad-l"><h2>Flow per week</h2>${explain("how-ideas-move-from-prop", `How ideas move from proposal to proved. Lead time is the median days from proposal to proved for the ideas proved that week; work in progress is what was approved or shipped but not yet proved at the week's end.`, "How it is counted")}
    <div style="overflow-x:auto;margin-top:8px"><table class="swflow"><thead><tr><th>Week</th><th>Proposed</th><th>Accepted</th><th>Proved</th><th>Came back</th><th>Lead time</th><th>In progress</th><th>Tokens per proved</th></tr></thead>
    <tbody>${w.slice().reverse().map((x) => `<tr><td class="mono">${esc(x.week)}</td><td>${bar(x.proposed, "var(--warn)")}</td><td>${bar(x.accepted, "var(--accent)")}</td><td>${bar(x.proved, "var(--ok)")}</td>
      <td>${x.reopened}</td><td>${x.median_days == null ? "–" : x.median_days + " d"}</td><td>${x.wip}</td><td>${x.tokens_per_proved == null ? "–" : tok(x.tokens_per_proved)}</td></tr>`).join("")}</tbody></table></div></div>${swLoopNumbers()}`;
}

// ---------- the improvement loop (phase 5): agent changes and their experiments (SWM-18, SWM-83), replay sets (SWM-82),
// failure classes (SWM-84), requirements in the Ledger (SWM-20) ----------
const SW_METRIC = { valid: "valid answers", keeps_proven: "keeps what you accepted", avoids_declined: "avoids what you declined",
  avoids_duplicates: "avoids duplicates", no_noise: "quiet when nothing is worth it" };
function swExperiment(ex) {
  if (!ex) return `<div class="tiny faint">No experiment yet: it runs on the agent's past runs as soon as the change is ready.</div>`;
  const rows = Object.keys(SW_METRIC).filter((m) => ex.baseline[m] != null || ex.candidate[m] != null).map((m) => {
    const b = ex.baseline[m], c = ex.candidate[m], d = b == null || c == null ? "" : c > b ? "ok" : c < b ? "err" : "";
    return `<tr><td>${esc(SW_METRIC[m])}${m === ex.target ? " <b>(target)</b>" : ""}</td><td>${b == null ? "–" : Math.round(b * 100) + "%"}</td>
      <td style="${d === "ok" ? "color:var(--ok);font-weight:600" : d === "err" ? "color:var(--err);font-weight:600" : ""}">${c == null ? "–" : Math.round(c * 100) + "%"}</td></tr>`;
  }).join("");
  return `<div class="row wrap" style="gap:8px;align-items:center;margin-top:6px"><span class="pill ${ex.passed ? "ok" : "failed"}">${ex.passed ? "passed" : "not passed"}</span>
    <span class="small">${esc(ex.why)}</span></div><div class="tiny faint">experiment ${ex.id} · ${ex.examples} replayed run${ex.examples === 1 ? "" : "s"} · ${swTime(ex.ts)}${ex.phoenix?.dataset ? " · in Phoenix as the dataset replay-" + esc(ex.agent) : ""}</div>
    ${rows ? `<table class="swflow swscore" style="margin-top:6px"><thead><tr><th>Score</th><th>Now</th><th>With it</th></tr></thead><tbody>${rows}</tbody></table>` : ""}`;
}
// the one Ideas list (Agents → Ideas): the stack's own fixes and the Coach's agent changes, ranked together. First what
// waits for your tap with a measured gain (agent changes that passed their experiment), then the stack's ideas by
// priority, then agent changes still being tested. Decided ideas of both kinds, then the rules (autonomy, pause).
let swIdeaKind = "all", swIdeaSig = "";
const SW_CHANGE_DONE = ["checking", "done", "declined", "gone"];
function swIdeas(body, quiet) {
  const b = S?.swarm?.board, ch = S?.swarm?.changes || [], imp = S?.improve || {};
  const sig = JSON.stringify([(b?.open || []).map((p) => [p.id, p.state, p.evidence]), (b?.recent || []).map((p) => [p.id, p.state]), ch.map((a) => [a.id, a.state, a.version]), S?.swarm?.autonomy, S?.swarm?.paused, imp]);
  if (quiet && sig === swIdeaSig) return;
  swIdeaSig = sig;
  if (!b) { body.innerHTML = `<div class="card pad-l small muted">The agents' Ledger is not reachable right now; the ideas come back when it is.</div>`; return; }
  const st = { draft: "draft", open: "back to the Coach", ready: "ready", active: "being built", checking: "shipped, watched", done: "held", declined: "declined", gone: "withdrawn" };
  const change = (a) => {
    const p = a.plan || {}, ex = a.experiment, build = (a.builds || []).slice(-1)[0];
    const add = p.change?.instructions?.add || (Array.isArray(p.change?.instructions) ? p.change.instructions : []);
    return `<div class="card pad-l section prop" data-kind="agent"><div class="row wrap" style="gap:6px;margin-bottom:4px"><span class="tag kind">Agent: ${esc(p.agent || "?")}</span></div><div class="row between wrap" style="gap:6px"><h2><a href="#/swarm/artifact/${a.id}">#${a.id}</a> ${esc(a.title)}</h2><span class="pill ${a.state === "done" ? "ok" : ["declined", "gone"].includes(a.state) ? "archived" : "running"}">${esc(st[a.state] || a.state)}</span></div>
      <div class="small" style="margin-top:4px">${esc(p.target?.why ? p.target.why[0].toUpperCase() + p.target.why.slice(1) + "." : a.body || "")}</div>
      <div class="tiny faint" style="margin-top:4px">for <b>${esc(p.agent || "?")}</b> · target: ${esc(p.target && p.target.score == null ? "nothing may get worse (your change)" : SW_METRIC[p.target?.score] || p.target?.score || "?")} · by ${esc(a.owner)}</div>
      ${p.security?.adds?.length ? `<div class="tiny warn-t" style="margin-top:4px">${ic.alert} Security change: ${esc(p.agent)}'s key gets ${esc(p.security.adds.join(", "))} (granted by you)</div>` : ""}
      ${add.length ? `<ul class="small" style="margin:6px 0 0 18px">${add.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      ${["model", "tools", "harness"].filter((k) => p.change?.[k]).map((k) => `<div class="tiny">${k}: ${esc(JSON.stringify(p.change[k]))}</div>`).join("")}
      ${swExperiment(ex)}
      ${a.state === "checking" ? `<div class="small" style="margin-top:6px">Watched on its real runs: ${a.watch_left_days} days left. It reopens by itself if its target falls.${build ? ` <a href="#/build/${build}">Build #${build}</a> has the one-tap Revert.` : ""}</div>` : ""}
      ${a.state === "ready" && ex?.passed && ex.version === a.version ? `<div class="row wrap" style="gap:8px;margin-top:8px"><button class="btn sm primary" data-chgo="${a.id}">Build it</button><button class="btn sm ghost" data-chno="${a.id}">Decline</button></div>`
        : ["open", "ready"].includes(a.state) ? `<div class="row wrap" style="gap:8px;margin-top:8px"><button class="btn sm ghost" data-chno="${a.id}">Decline</button></div>` : ""}</div>`;
  };
  const passed = (a) => a.state === "ready" && a.experiment?.passed && a.experiment.version === a.version;
  const changesOpen = ch.filter((a) => !SW_CHANGE_DONE.includes(a.state) && a.state !== "active");
  const items = [...changesOpen.filter(passed).map((a) => ["agent", change(a)]), ...(b.open || []).map((p, n) => ["stack", stackIdeaCard(p, n)]),
    ...changesOpen.filter((a) => !passed(a)).map((a) => ["agent", change(a)])];
  const shown = items.filter(([k]) => swIdeaKind === "all" || k === swIdeaKind);
  const count = (k) => items.filter(([x]) => k === "all" || x === k).length;
  const decided = [...(b.recent || []).map((p) => stackDecidedRow(p)),
    ...ch.filter((a) => SW_CHANGE_DONE.includes(a.state) || a.state === "active").map((a) => `<div style="padding:7px 2px;flex-wrap:wrap"><span class="pill ${a.state === "done" ? "ok" : ["declined", "gone"].includes(a.state) ? "archived" : "running"}" style="padding:1px 7px">${esc(st[a.state] || a.state)}</span>
      <div class="grow small"><a href="#/swarm/artifact/${a.id}">${esc(a.title)}</a> <span class="faint">· agent ${esc(a.plan?.agent || "?")}${a.state === "checking" ? ` · watched, ${a.watch_left_days} days left` : ""}</span></div></div>`)];
  const scanning = imp.requested && imp.requested > (imp.last || "");
  body.innerHTML = `<div class="card pad-l"><div class="row between wrap" style="gap:10px"><div class="grow" style="min-width:200px"><h2>Ideas</h2>
      ${explain("what-the-agents-propose-", `What the agents propose to make the stack and themselves better. A problem seen again raises its rank instead of making a copy; nothing starts without your tap.`, "About this")}</div>
      <button class="btn sm" id="iscan" ${scanning ? "disabled" : ""}>${scanning ? '<span class="spin" style="width:13px;height:13px"></span>Reviewing…' : `${ic.search}Look for improvements`}</button></div>
    <div class="tiny faint" style="margin-top:6px">Stack ideas: the scheduled jobs and the weekly self-review (last ${imp.last ? rel(imp.last) : "not yet"}). Agent changes: the Coach, monthly, tested on past runs first.</div>
    <div class="chips" style="margin-top:10px">${[["all", "All"], ["stack", "The stack"], ["agent", "The agents"]].map(([k, l]) => `<button type="button" class="tag ${swIdeaKind === k ? "on" : ""}" data-ik="${k}">${l} <span class="faint">${count(k)}</span></button>`).join("")}</div></div>
    <div id="ionly"></div><div id="ieditor"></div>
    ${shown.map(([, h]) => h).join("") || `<div class="card pad-l section small muted">No open ideas${swIdeaKind === "all" ? "" : " of this kind"}.</div>`}
    ${decided.length ? `<details class="card pad-l section" ${(b.recent || []).some((p) => p.state === "checking") ? "open" : ""}><summary><b>Decided lately</b> <span class="small muted">${decided.length}</span></summary><div class="list" style="margin-top:6px">${decided.join("")}</div></details>` : ""}
    ${ideaRulesHtml()}`;
  $$("[data-ik]", body).forEach((x) => (x.onclick = () => { swIdeaKind = x.dataset.ik; swIdeas(body); }));
  fillIdeaFrom(body);                                       // each stack idea's task and runs; ?task= shows one task's
  bindProposals();
  $$("[data-chgo]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Build it: the builder edits the agent's card exactly as the change says; you approve the build before it deploys.")) return;
    b.disabled = true;
    const r = await act({ action: "proposal_accept", id: +b.dataset.chgo }, (x) => (x?.build ? `Build #${x.build} queued: follow it on its page` : ""));
    if (r?.build) location.hash = `#/build/${r.build}`; else b.disabled = false;
  }));
  $$("[data-chno]").forEach((b) => (b.onclick = async () => {
    const why = prompt("Why not? (the Coach learns from your reason)");
    if (why == null) return;
    if (await act({ action: "proposal_dismiss", id: +b.dataset.chno, reason: why }, "Declined: the Coach learns from your reason")) b.closest(".card").remove();
  }));
}

// the numbers behind the improvement loop, under Flow: replay sets and failure classes (SWM-82, SWM-84), requirements in
// the Ledger (SWM-20)
function swLoopNumbers() {
  const sc = S?.swarm?.scorecards || {}, req = S?.swarm?.requirements || {};
  const agents = Object.entries(sc).filter(([, s]) => s?.replays || s?.failures);
  const pct = (n, of) => (of ? Math.round((100 * n) / of) + "%" : "–");
  return `<div class="card pad-l section"><h2>Replay sets and failures</h2>${explain("every-run-is-kept-with-w", `Every run is kept with what it read and what came of it (proven, declined, duplicate, failed): that is what experiments replay. Failed, declined and duplicate runs are sorted into the MAST failure classes.`, "About this")}
      ${agents.length ? `<div style="overflow-x:auto;margin-top:8px"><table class="swflow"><thead><tr><th>Agent</th><th>Runs</th><th>Proven</th><th>Declined</th><th>Duplicate</th><th>Failed</th><th>Specification</th><th>Between agents</th><th>Verification</th><th>Top failure</th></tr></thead>
      <tbody>${agents.map(([id, s]) => { const r = s.replays || { labels: {} }, f = s.failures || {}, n = r.examples || 0, l = r.labels || {};
        return `<tr><td>${esc(id)}</td><td>${n}${r.history ? ` <span class="tiny faint">(${r.history} from history)</span>` : ""}</td><td>${pct(l.proven || 0, n)}</td><td>${pct(l.declined || 0, n)}</td><td>${pct(l.duplicate || 0, n)}</td><td>${pct(l.failed || 0, n)}</td>
          <td>${f.FC1 || 0}</td><td>${f.FC2 || 0}</td><td>${f.FC3 || 0}</td><td class="tiny">${esc((f.modes || [])[0]?.[0] || "–")}</td></tr>`; }).join("")}</tbody></table></div>`
        : `<div class="small muted" style="margin-top:6px">No runs recorded yet.</div>`}</div>
    <div class="card pad-l section"><h2>Requirements in the Ledger</h2>${explain("requirements-yaml-is-mir", `requirements/*.yaml is mirrored into the Ledger, so agents can find and work on a requirement: open means partial or violated (an open finding); an agent's idea names the requirements it serves.`, "About this")}
      <div class="row wrap" style="gap:14px;margin-top:8px">${[["done", "implemented"], ["open", "open (partial or violated)"], ["ready", "planned"], ["draft", "proposed"], ["gone", "deprecated"]].map(([k, l]) => `<span class="small"><b>${req[k] || 0}</b> ${l}</span>`).join("")}</div>
      ${S?.swarm?.requirements_sync?.at ? `<div class="tiny faint" style="margin-top:4px">last synced ${swTime(S?.swarm?.requirements_sync?.at)}</div>` : ""}</div>`;
}

// ---------- the team: names, groups and colours shared by the timeline, the map, the Chatroom and the agent map ----------
const SW_GROUP = [["owner", "You"], ["assistant", "Your assistant"], ["research", "Research"], ["missions", "Briefings and research"],
  ["knowledge", "Knowledge and memory"], ["code", "Code"], ["reviewers", "Reviews and improvement"], ["health", "Health"], ["phone", "AI phone"],
  ["mail", "Mail"], ["other", "Other"]];
const SW_GCOL = { owner: "var(--ok)", assistant: "#60a5fa", research: "#2dd4bf", missions: "#fbbf24", knowledge: "#a78bfa", code: "#f472b6",
  reviewers: "#fb923c", health: "#a3e635", phone: "#94a3b8", mail: "#f87171", other: "var(--faint)" };
const SW_ROLEG = { assistant: "assistant", research: "research", missions: "missions", briefings: "missions", knowledge: "knowledge", memory: "knowledge",
  code: "code", tests: "code", reviewers: "reviewers", health: "health", phone: "phone", mail: "mail" };
const SW_LANE = { you: ["you", "owner"], claude: ["Claude questions", "code"], evals: ["experiments", "reviewers"], reviewers: ["build reviewers", "reviewers"],
  gmail: ["Gmail", "mail"], phone: ["AI phone", "phone"], windows: ["Windows PC", "other"], hermes: ["Hermes (your assistant or a workflow's agent)", "assistant"] };
let swCards = null;
async function swWhoCards() {
  if (!swCards) swCards = await swApi("who").catch(() => []);
  return swCards;
}
function swGroupOf(id) {
  if (SW_LANE[id]) return SW_LANE[id][1];
  const c = (swCards || []).find((x) => x.id === id);
  return SW_ROLEG[(c?.roles || [])[0]] || "other";
}
const swName = (id) => (SW_LANE[id] ? SW_LANE[id][0] : id === "main" ? "main (your assistant)" : (typeof cardName === "function" && cardName(id)) || (S?.crew || []).find((c) => c.id === id)?.name || id);
const swAgo = (ts) => { const s = Date.now() / 1000 - ts; return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`; };
const swDur = (s) => dur(s);
const SW_STATE = { done: ["var(--ok)", "done"], running: ["var(--run)", "running"], failed: ["var(--err)", "failed"], stalled: ["var(--err)", "stuck", true],
  limit: ["var(--warn)", "waited for a usage limit"], stopped: ["var(--faint)", "stopped"] };
// failed: the run ended with an error; stuck (outlined): it went silent for 20 minutes and the watchdog closed it (runrecord STALL_S)
const swPill = (state) => { const [c, l, hollow] = SW_STATE[state] || SW_STATE.done;
  return `<span class="pill" style="${hollow ? `background:transparent;color:${c};box-shadow:inset 0 0 0 1.5px ${c}` : `background:${c};color:var(--bg)`}">${esc(l)}</span>`; };

// ---------- the timeline: one row per agent, one bar per run (SWM-103) ----------
let swTlSel = null, swTlData = null;
async function swTimeline(body, poll = false) {
  await swWhoCards();
  const hours = swRoomF.hours, pick = swRoomF.agents;
  const t = await api(`/api/swarm/timeline?hours=${hours}${swRoomF.tests ? "&tests=1" : ""}`);
  const runs = pick.size ? t.runs.filter((r) => pick.has(r.lane) || pick.has(r.agent) || pick.has(r.by)) : t.runs;
  const sig = JSON.stringify([hours, swRoomF.tests, [...pick], runs.map((r) => [r.run, r.state, r.ended])]);
  if (poll && sig === body.dataset.sig) return;
  body.dataset.sig = sig;
  swTlData = t;
  const order = Object.fromEntries(SW_GROUP.map(([k], i) => [k, i]));
  const count = {};
  for (const r of runs) count[r.lane] = (count[r.lane] || 0) + 1;
  const lanes = Object.keys(count).sort((a, b) => (order[swGroupOf(a)] - order[swGroupOf(b)]) || count[b] - count[a]);
  const live = runs.filter((r) => r.state === "running").length;
  if (!runs.length) { body.innerHTML = `<div class="card pad-l small muted">No runs in this window${pick.size ? " for " + [...pick].map(swName).join(" and ") : ""}.</div>`; return; }
  body.innerHTML = `<details class="card pad-l" id="swtlcard"${swTimeline.open ? " open" : ""}><summary><b>When each ran</b> <span class="hcount">${runs.length}</span>${live ? ` <span class="small muted">${live} running now</span>` : ""}</summary>
    ${explain("one-row-per-agent-one-ba", `One row per agent, one bar per run, coloured by how it ended. Swipe for earlier days, and tap a bar to see what started it. <span class="row wrap" style="gap:10px;margin-top:6px">${Object.entries(SW_STATE).map(([, [c, l, hollow]]) => `<span class="row" style="gap:5px"><span style="width:12px;height:8px;border-radius:2px;${hollow ? `box-shadow:inset 0 0 0 1.5px ${c}` : `background:${c}`}"></span>${l}</span>`).join("")}</span>`, "How to read this")}
    <div class="swtl" style="margin-top:8px"></div>
    <div id="swtldet"></div></details>`;
  $("#swtlcard", body).ontoggle = (e) => { swTimeline.open = e.target.open; if (e.target.open) { const x = $(".swtl", body); if (x) x.scrollLeft = x.scrollWidth; } };
  const sc = $(".swtl"), box = sc.clientWidth || (($("#swbody")?.clientWidth || 368) - 48), span = t.now - t.since;
  const W = hours > 24 ? Math.round(Math.max(box, (hours / 24) * box * 0.9)) : box;    // a long window scrolls inside its card
  const X = (ts) => Math.max(0, Math.min(W, ((ts - t.since) / span) * W));
  const step = hours <= 6 ? 3600 : hours <= 24 ? 3 * 3600 : hours <= 72 ? 12 * 3600 : 86400;
  const ticks = [];
  for (let s = Math.ceil(t.since / step) * step; s < t.now; s += step) if (X(s) < W - 62) ticks.push(s);         // a tick's label (5 characters) stays clear of "now"
  const fmt = (s) => (step >= 86400 ? day(s) : clock(s));
  const grid = ticks.map((s) => `<line x1="${X(s)}" x2="${X(s)}" y1="0" y2="16" stroke="var(--border)"/>`).join("") + `<line x1="${W - 1}" x2="${W - 1}" y1="0" y2="16" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="3 3"/>`;
  sc.innerHTML = `<div style="width:${W}px">
    <svg width="${W}" height="20" style="display:block">${ticks.map((s) => `<text x="${X(s) + 2}" y="13" font-size="10.5" fill="var(--muted)">${fmt(s)}</text>`).join("")}<text x="${W - 3}" y="13" font-size="10.5" text-anchor="end" fill="var(--muted)">now</text></svg>
    ${lanes.map((l, i) => `<div class="swlane" style="${i % 2 ? "" : "background:var(--surface-2)"}"><div class="swlname"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${SW_GCOL[swGroupOf(l)]};margin-right:5px"></span>${esc(swName(l))} · ${count[l]}</div>
      <svg width="${W}" height="16" style="display:block">${grid}${runs.filter((r) => r.lane === l).map((r) => {
        const x = X(r.started), w = Math.max(3, X(r.until || r.ended || t.now) - x), [col, , hollow] = SW_STATE[r.state] || SW_STATE.done;
        return `<rect class="swbar ${r.state === "running" ? "live" : ""}" data-run="${esc(r.run)}" x="${x.toFixed(1)}" y="${hollow ? 2.75 : 2}" width="${(hollow ? Math.max(1.5, w - 1.5) : w).toFixed(1)}" height="${hollow ? 10.5 : 12}" rx="3" ${hollow ? `fill="transparent" stroke="${col}" stroke-width="1.5"` : `fill="${col}"`}><title>${esc(r.name)}</title></rect>`;
      }).join("")}</svg></div>`).join("")}</div>`;
  const showRun = (id) => {
    swTlSel = id;
    const r = t.runs.find((x) => x.run === id);
    if (!r) return;
    const kids = t.runs.filter((x) => x.parent === id), par = t.runs.find((x) => x.run === r.parent);
    $$(".swbar").forEach((b) => b.classList.toggle("sel", b.dataset.run === id));
    $$(".swbar").forEach((b) => b.classList.toggle("rel", [r.parent, ...kids.map((k) => k.run)].includes(b.dataset.run)));
    const pair = r.by && r.by !== r.lane ? swActHref([r.by, r.lane], hours) : "";
    $("#swtldet").innerHTML = `<div class="card pad-l section"><div class="row between wrap" style="gap:6px"><h2 class="wrap">${esc(r.name)}</h2>${swPill(r.state)}</div>
      <div class="small" style="margin-top:4px"><b>${esc(swName(r.lane))}</b>${r.agent !== r.lane ? ` <span class="tiny faint">(${esc(r.agent)})</span>` : ""} · ${swTime(r.started)}${r.ended ? ` to ${swTime(r.ended)}` : ", still running"} · ${swDur((r.ended || t.now) - r.started)}</div>
      <div class="small muted">${r.calls} model call${r.calls === 1 ? "" : "s"}${r.tokens ? ` · ${tok(r.tokens)} tokens` : ""}${r.by ? ` · started by ${r.by === "you" ? "you (a chat)" : par ? `<a href="#" data-tlrun="${esc(par.run)}">${esc(swName(r.by))}</a>` : esc(swName(r.by))}` : r.cause ? ` · ${esc(swCauseWords(r.cause))}` : ""}</div>
      ${kids.length ? `<div class="small" style="margin-top:6px">It started ${kids.length} run${kids.length > 1 ? "s" : ""} (outlined on the timeline):</div>
        <div class="list" style="margin-top:4px">${kids.map((k) => `<a href="#" data-tlrun="${esc(k.run)}"><div class="grow"><div class="sub wrap">${esc(k.name)}</div><div class="tiny faint">${esc(swName(k.lane))} · ${swTime(k.started)} · ${esc((SW_STATE[k.state] || SW_STATE.done)[1])}</div></div></a>`).join("")}</div>` : ""}
      <div class="row wrap" style="gap:8px;margin-top:8px"><a class="btn sm" href="#/live/${encodeURIComponent(r.run)}">Open its log</a>${pair ? `<a class="btn sm ghost" href="${pair}">What they said</a>` : ""}</div></div>`;
    $$("[data-tlrun]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); showRun(a.dataset.tlrun); }));
  };
  $$(".swbar").forEach((b) => (b.onclick = () => showRun(b.dataset.run)));
  if (swTlSel && t.runs.some((r) => r.run === swTlSel)) showRun(swTlSel);
  sc.scrollLeft = sc.scrollWidth;                        // a long window opens at now; the names stay pinned on the left
}

// ---------- the map: agents as dots, who worked with whom as lines (Overview; SWM-104) ----------
// A dot's size says how often the agent ran, a red ring that some runs failed; a line joins two that worked together, its
// arrow who asked whom, dashed when they only wrote to each other, its number how often. Tapping a dot or a line opens
// Activity on that agent or that pair. "Ideas too" adds the ideas each agent wrote to (the former "who works on what").
// (Before: a list of rows called a map, and a second graph of ideas, the owner's review of 1 Nov 2026.)
let swMapHours = 168, swMapIdeas = false, swMapTold = false, swMapTests = false, swOv = { el: null, t: 0, sig: "" };
const swCauseWords = (c) => ({ you: "started by you", clock: "started by its timer", rule: "started by a rule", alert: "started by an alert", test: "a test",
  unrecorded: "timer, Run now or an alert: not recorded for this run", unknown: "nothing on record says what started it", agent: `started by ${swName(c.who)}` }[c.kind] || "");
const SW_ROLE = { stack: "the stack itself: its runner and its upkeep", you: "you, in chat and in the app", claude: "Claude Code, a read-only analysis in the sandbox", evals: "replays of agents' past runs (agent-change tests)",
  reviewers: "reviews of a build by the other engine", gmail: "your Gmail, through its connector", phone: "the AI phone", windows: "your Windows PC, read-only",
  hermes: "Hermes, your assistant or a workflow's agent", conductor: "the runner, which runs a request's steps one by one" };
function swRole(id) {
  if (SW_ROLE[id]) return SW_ROLE[id];
  const c = (swCards || []).find((x) => x.id === id);
  return c?.purpose || "";
}
function swVerb(e) {                                     // what the connection was, in words
  if (e.kind === "ask") return [{ scout: "asked to research", claude: "asked Claude Code for an analysis", evals: "replayed through" }[e.to] || "started a run of", "→"];
  return [{ talk: "wrote on the Board to", you: e.to === "main" ? "talked to" : "asked or decided for", tell: "told", use: "used", hand: "handed over to", help: "helped" }[e.kind] || e.kind, "→"];
}
const swShort = (id) => ({ stack: "The stack", you: "You", claude: "Claude questions", evals: "experiments", gmail: "Gmail", phone: "AI phone", windows: "Windows PC", reviewers: "reviewers" }[id] || id);   // a dot's name
// APP-57: the idea's whole title, wrapped
const swIdeaLabel = (x) => `#${x.id} ${String(x.title || "").split(/\s+/).filter(Boolean).join(" ")}`;
async function swMapData() {
  await swWhoCards();
  const [it, g] = await Promise.all([api(`/api/swarm/interactions?hours=${swMapHours}${swMapTests ? "&tests=1" : ""}`),
    swMapIdeas ? swApi("graph", { days: 30 }).catch(() => ({ agents: [], artifacts: [], touches: [] })) : { artifacts: [], touches: [] }]);
  return { it, g, edges: it.edges };
}
const swCoverage = (c) => (c && c.runs ? `Cause known for ${c.known} of ${c.runs} runs${c.unrecorded ? ` · ${c.unrecorded} from before it was recorded` : ""}${c.unknown ? ` · ${c.unknown} unknown` : ""}` : "");
function swMapMount(force) {                            // Overview's map survives the page's live redraws (state updates)
  const ph = $("#ovmap");
  if (!ph) return;
  if (swOv.el && swOv.el !== ph && !force) ph.replaceWith(swOv.el);
  if (force || !swOv.el || Date.now() - swOv.t > 60000) {
    swOv.t = Date.now();
    swMapData().then((d) => {
      const sig = JSON.stringify([swMapHours, swMapIdeas, swMapTests, d.edges, d.it.nodes.map((n) => [n.id, n.runs, n.failing, n.live]), d.it.coverage, swMapIdeas ? d.g.touches : 0]);
      const cur = $("#ovmap");
      if (!cur || (!force && sig === swOv.sig && swOv.el)) return;
      swOv.sig = sig;
      swOv.el = swMapCard(cur, d);
    }).catch((e) => { const cur = $("#ovmap"); if (cur && !swOv.el) cur.innerHTML = `<div class="card pad-l small muted">The map has no data to show${notConnected() ? ": it fills once the stack's runner has run here" : `: ${esc(e.message)}`}.</div>`; });
  }
}
// The map's rows, top to bottom: you; the reviewers only you answer; whom you ask; whom they ask; what they use; the task
// team last (chosen on a week's real lines: fewest crossings, and no line has to go through a dot). An agent's place comes
// from this list and the width alone, never from who ran in the window, so a dot is in the same place every time. An agent
// not listed here gets a place in the last row.
const SW_MAP_ROWS = [["stack", "you"], ["maintainability", "tests", "self-review", "coach"], ["intake", "main", "mission", "doctor", "checker"],
  ["conductor", "scout", "claude", "phone-check"], ["desk", "phone", "house", "builder", "phone-cleanup"], ["journeys", "gmail", "inbox", "curator", "memory"],
  ["planner", "analyst", "tester", "tracer"], ["breaker", "judge", "presenter", "evals", "reviewers"]];
function swMapRows(ids, W, label, gap) {
  const here = new Set(ids), known = new Set(SW_MAP_ROWS.flat()), slot = (id) => Math.max(label(id).length * 6.4, 28) + 10;   // a dot's name and its biggest dot fit its slot
  const lines = [];
  [...SW_MAP_ROWS, ids.filter((id) => !known.has(id)).sort()].forEach((row, i) => {
    let line = [], used = 0;
    for (const id of row) {
      if (line.length && used + slot(id) > W) { lines.push({ line, keep: i < 6 }); line = []; used = 0; }   // a narrow screen wraps a row, it never squeezes names together
      line.push(id); used += slot(id);
    }
    if (line.length) lines.push({ line, keep: i < 6 });
  });
  const at = {};
  let y = 26, last = y;
  for (const { line, keep } of lines) {
    const someone = line.some((id) => here.has(id));
    if (!someone && !keep) continue;                       // an empty row keeps its place, or everyone below would move; only the rows under the everyday map close up
    const spare = (W - line.reduce((n, id) => n + slot(id), 0)) / line.length;
    let x = 0;
    for (const id of line) { const w = slot(id) + spare; if (here.has(id)) at[id] = { x: x + w / 2, y }; x += w; }   // an absent agent keeps its place empty
    if (someone) last = y;
    y += gap;
  }
  if (at.you) at.you.x = W / 2;                            // you are always top and centre
  return { at, H: last + 46 };
}
// Each line: the smallest bend that passes no other dot and, where it can, no other name (a name's halo keeps it readable
// over a line; a line through a dot reads as a connection). `blocked`: lines that could not miss a dot. Each number: the first free spot along its line, the
// busiest first, away from other lines where it can be. `clashes`: numbers that found no free spot.
function swMapRoute({ at, H }, W, rs, label, pairs) {
  const ids = Object.keys(at), names = {}, routes = {}, curves = [];
  for (const id of ids) { const w = label(id).length * 6.4 + 2, y = at[id].y + rs(id); names[id] = [at[id].x - w / 2, y + 3, at[id].x + w / 2, y + 16]; }
  const point = (a, c, b, t) => [(1 - t) ** 2 * a.x + 2 * (1 - t) * t * c[0] + t ** 2 * b.x, (1 - t) ** 2 * a.y + 2 * (1 - t) * t * c[1] + t ** 2 * b.y];
  const inBox = ([x, y], o) => x > o[0] && x < o[2] && y > o[1] && y < o[3], meets = (b, o) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1];
  let blocked = 0, clashes = 0;
  for (const p of pairs) {
    const a = at[p.a], b = at[p.b], mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, len = Math.hypot(b.x - a.x, b.y - a.y) || 1, nx = (a.y - b.y) / len, ny = (b.x - a.x) / len;
    const outward = (mx - W / 2) * nx + (a.y === b.y ? -ny * 40 : 0) >= 0 ? 1 : -1;   // bow away from the middle, and up within a row (a name sits under each dot)
    let best = null;
    for (const off of [0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8, -8]) {
      const c = [mx + nx * off * 20 * outward, my + ny * off * 20 * outward], pts = Array.from({ length: 39 }, (_, i) => point(a, c, b, (i + 1) / 40));
      const others = ids.filter((id) => id !== p.a && id !== p.b);
      const dots = pts.filter((q) => q[0] < 4 || q[0] > W - 4 || q[1] < 4 || others.some((id) => Math.hypot(q[0] - at[id].x, q[1] - at[id].y) < rs(id) + 5)).length;
      const hits = dots * 10 + pts.filter((q) => others.some((id) => inBox(q, names[id]))).length;
      if (!best || hits < best.hits) best = { c, hits, dots, pts };
      if (!hits) break;
    }
    blocked += best.dots ? 1 : 0;
    routes[p.a + "+" + p.b] = { c: best.c };
    curves.push({ p, a, b, nx, ny, ...best });
  }
  const fixed = [[W - 122, 0, W, 46], ...Object.values(names), ...ids.map((id) => [at[id].x - rs(id) - 1, at[id].y - rs(id) - 1, at[id].x + rs(id) + 1, at[id].y + rs(id) + 1])], placed = [];
  for (const l of [...curves].sort((x, y) => y.p.n - x.p.n)) {
    const w = String(l.p.n).length * 6.2 + 5;
    let best = null;
    for (const side of [0, 11, -11]) for (const t of [0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74, 0.2, 0.8, 0.14, 0.86]) {   // on its line, or else just beside it
      const q = point(l.a, l.c, l.b, t), x = q[0] + l.nx * side, y = q[1] + l.ny * side, box = [x - w / 2, y - 7, x + w / 2, y + 7];
      if (box[0] < 0 || box[2] > W || box[1] < 0 || box[3] > H || fixed.some((o) => meets(box, o)) || placed.some((o) => meets(box, o))) continue;
      const crossed = curves.filter((o) => o !== l && o.pts.some((r) => Math.hypot(r[0] - x, r[1] - y) < 8)).length + (side ? 1 : 0);
      if (!best || crossed < best.crossed) best = { x, y, box, crossed };
      if (!crossed) break;
    }
    if (!best) { clashes++; const q = point(l.a, l.c, l.b, 0.5); best = { x: q[0], y: q[1], box: [q[0] - w / 2, q[1] - 7, q[0] + w / 2, q[1] + 7] }; }
    placed.push(best.box);
    routes[l.p.a + "+" + l.p.b].num = [best.x, best.y];
  }
  return { at, H, routes, blocked, clashes };
}
function swMapPlan(ids, W, rs, label, pairs) {
  let plan;
  for (let gap = 78; gap <= 150; gap += 12) {              // taller only when a number found no free spot
    plan = swMapRoute(swMapRows(ids, W, label, gap), W, rs, label, pairs);
    if (!plan.clashes) break;
  }
  return plan;
}
function swMapArrow(l, forward, gap) {                     // the arrow at a line's end, just off the dot it points at
  const a = l.source, b = l.target, c = l.c, len = Math.hypot(c[0] - a.x, c[1] - a.y) + Math.hypot(b.x - c[0], b.y - c[1]) || 1;
  const t = Math.max(0, Math.min(1, forward ? 1 - gap / len : gap / len)), u = 1 - t;
  const dx = u * (c[0] - a.x) + t * (b.x - c[0]), dy = u * (c[1] - a.y) + t * (b.y - c[1]);
  return { x: u * u * a.x + 2 * u * t * c[0] + t * t * b.x, y: u * u * a.y + 2 * u * t * c[1] + t * t * b.y, a: (Math.atan2(forward ? dy : -dy, forward ? dx : -dx) * 180) / Math.PI };
}
function swMapCard(ph, { it, g, edges: every }) {
  const told = every.filter((e) => e.kind === "tell"), edges = swMapTold ? every : every.filter((e) => e.kind !== "tell");   // the busiest kind of line: a chip away
  const hrefOf = (ids) => swActHref(ids, swMapHours, swMapTests);   // a test's line opens with tests on, so the tap finds what the number counts
  const card = document.createElement("div");
  card.id = "ovmap";
  card.className = "card pad-l section";
  const info = Object.fromEntries(it.nodes.map((n) => [n.id, n]));
  const pairs = {};
  for (const e of edges) {
    const [a, b] = [e.from, e.to].sort(), k = a + "+" + b, p = (pairs[k] = pairs[k] || { a, b, n: 0, dirs: new Set(), kinds: new Set(), live: 0, last: 0 });
    p.n += e.n; p.kinds.add(e.kind); p.live += e.live || 0; p.last = Math.max(p.last, e.last || 0);
    p.dirs.add(e.from + ">" + e.to);
  }
  const used = new Set(edges.flatMap((e) => [e.from, e.to]));
  const agentIds = [...new Set([...it.nodes.filter((n) => n.runs || used.has(n.id)).map((n) => n.id), ...used])];
  const closed = (s) => ["declined", "merged", "gone"].includes(s);
  const ideas = swMapIdeas ? (g.artifacts || []).filter((x) => !closed(x.state)) : [];
  const touches = swMapIdeas ? (g.touches || []).map((t) => ({ agent: swWho(t.agent) === "you" ? "you" : t.agent, artifact: t.artifact, n: t.n })) : [];
  const groups = [...new Set(agentIds.map(swGroupOf))];
  const conn = Object.values(pairs).sort((x, y) => y.n - x.n);
  const who = (id) => { const n = info[id]; return `<div class="swwho"><div class="row" style="gap:6px"><span class="swdot" style="background:${SW_GCOL[swGroupOf(id)]}"></span><b class="wrap">${esc(swName(id))}</b>
      ${n?.runs ? `<span class="tiny faint">${n.runs} run${n.runs === 1 ? "" : "s"}${n.failed ? ` · <span class="err-t">${n.failed} failed</span>` : ""}${n.causes?.clock === n.runs ? " · all on its timer" : ""}</span>` : ""}</div>
      ${swRole(id) ? `<div class="tiny muted wrap">${esc(swRole(id))}</div>` : ""}</div>`; };
  const row = (e) => { const [verb, arrow] = swVerb(e);
    return `<a class="swconn" href="${hrefOf([e.from, e.to])}">${who(e.from)}<div class="swverb"><span class="swarrow">${arrow}</span><span class="wrap"><b>${esc(verb)}</b> · ${e.n} time${e.n === 1 ? "" : "s"}${e.last ? ` · last ${swAgo(e.last)}` : ""}${e.live ? ` · <b class="ok-t">${e.live} now</b>` : ""}</span></div>${who(e.to)}</a>`; };
  const alone = agentIds.filter((id) => !used.has(id));
  const shared = Object.entries(g.shared || {});
  card.innerHTML = `<div class="row between wrap" style="gap:8px"><h2>Who works with whom</h2><div class="chips">${[[24, "24 h"], [72, "3 days"], [168, "7 days"]].map(([h, l]) => `<button type="button" class="tag ${swMapHours === h ? "on" : ""}" data-mh="${h}">${l}</button>`).join("")}</div></div>
    ${explain("each-dot-is-an-agent-the", `Each dot is an agent: the bigger, the more real work it did; a red ring means its newest run failed. An arrow says who asked or told whom and how often. A dashed line is a Board message, a dotted line is a hand-over through a file or a list of steps. <b>Tap a dot or a line</b> for exactly what the number counts. ${CHART_HINT}. <span class="row wrap" style="gap:10px;margin-top:6px">${groups.map((k) => `<span class="row" style="gap:5px"><span class="swdot" style="background:${SW_GCOL[k]}"></span>${esc((SW_GROUP.find(([x]) => x === k) || [, k])[1])}</span>`).join("")}</span>`, "How to read this")}
    <div class="chips" style="margin-top:8px"><button type="button" class="tag ${swMapIdeas ? "on" : ""}" data-mideas>Ideas too</button>${told.length ? `<button type="button" class="tag ${swMapTold ? "on" : ""}" data-mtold>Messages to you <span class="faint">${told.reduce((n, e) => n + e.n, 0)}</span></button>` : ""}${it.coverage?.tests || swMapTests ? `<button type="button" class="tag ${swMapTests ? "on" : ""}" data-mtests>Tests${it.coverage?.tests ? ` <span class="faint">${it.coverage.tests}</span>` : ""}</button>` : ""}</div>
    <div class="swmapsvg" style="margin-top:6px"></div>
    ${it.coverage?.runs ? `<div class="tiny faint" style="margin-top:6px">${esc(swCoverage(it.coverage))}</div>` : ""}
    ${Object.keys(it.sources || {}).length ? `<div class="tiny warn-t" style="margin-top:4px">No data from: ${esc(Object.keys(it.sources).join(", "))}</div>` : ""}
    <details class="swmapwords" style="margin-top:10px"><summary class="small"><b>Every connection in words</b> <span class="muted">${conn.length}${alone.length ? ` · ${alone.length} worked alone` : ""}</span></summary>
      ${edges.length ? `<div class="swconns" style="margin-top:6px">${[...edges].sort((x, y) => y.n - x.n).map(row).join("")}</div>` : `<div class="small muted" style="margin-top:6px">Nothing passed between agents in this window.</div>`}
      ${alone.length ? `<div class="small" style="margin-top:10px"><b>Worked alone</b></div><div class="swalone">${alone.map(who).join("")}</div>` : ""}
      ${swMapIdeas ? `<div class="small" style="margin-top:10px"><b>Ideas two or more work on</b></div>${shared.length ? `<div class="list">${shared.map(([aid, ws]) => { const a = (g.artifacts || []).find((x) => String(x.id) === aid) || {};
        return `<a href="#/swarm/artifact/${aid}"><div class="grow"><div class="ttl">#${aid} ${esc(a.title || "")}</div><div class="sub">${ws.map(esc).join(", ")} · ${esc(a.state || "")}</div></div>${ic.next}</a>`; }).join("")}</div>` : `<div class="small muted">None yet: so far each idea has one worker.</div>`}` : ""}
    </details>`;
  ph.replaceWith(card);
  $$("[data-mh]", card).forEach((b) => (b.onclick = () => { swOv.zoom = null; swMapHours = +b.dataset.mh; swMapMount(true); }));
  $("[data-mideas]", card).onclick = () => { swOv.zoom = null; swMapIdeas = !swMapIdeas; swMapMount(true); };
  const toldChip = $("[data-mtold]", card);
  if (toldChip) toldChip.onclick = () => { swOv.zoom = null; swMapTold = !swMapTold; swMapMount(true); };
  const testsChip = $("[data-mtests]", card);
  if (testsChip) testsChip.onclick = () => { swOv.zoom = null; swMapTests = !swMapTests; swMapMount(true); };
  const el = $(".swmapsvg", card);
  if (!agentIds.length) { el.innerHTML = emptyState("No agent ran in this window.", `<button type="button" class="btn sm" data-mh2="168">Show 7 days</button>`); $("[data-mh2]", el).onclick = () => { swMapHours = 168; swMapMount(true); }; return card; }
  const W = el.clientWidth || 340;
  const rs = (d) => (d.kind === "idea" ? 4 : d.id === "you" ? 9 : Math.min(14, 5 + 1.8 * Math.log2(1 + d.runs)));          // screen px at any zoom
  const agents = agentIds.map((id) => ({ id, kind: "agent", label: swShort(id), runs: info[id]?.runs || 0, failed: info[id]?.failed || 0, failing: info[id]?.failing, live: info[id]?.live || 0 }));
  const one = Object.fromEntries(agents.map((n) => [n.id, n]));
  const plan = swMapPlan(agentIds, W, (id) => rs(one[id]), swShort, conn);
  for (const n of agents) Object.assign(n, plan.at[n.id]);
  const cols = W >= 520 ? 2 : 1;                           // the ideas: a list under the agents
  const ideasAt = ideas.map((x, i) => ({ id: "x:" + x.id, kind: "idea", label: swIdeaLabel(x), aid: x.id, state: x.state, x: 14 + (i % cols) * (W / cols), y: plan.H + Math.floor(i / cols) * 24 }));
  const H = plan.H + Math.ceil(ideas.length / cols) * 24;
  el.style.height = H + "px";
  const nodes = [...agents, ...ideasAt], byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const pl = conn.map((p) => ({ p, source: byId[p.a], target: byId[p.b], ...plan.routes[p.a + "+" + p.b] }));
  const il = touches.map((t) => ({ source: byId[t.agent], target: byId["x:" + t.artifact], n: t.n })).filter((l) => l.source && l.target);
  const curve = (d) => `M${d.source.x},${d.source.y}Q${d.c[0]},${d.c[1]} ${d.target.x},${d.target.y}`;
  const svg = d3.select(el).append("svg").attr("width", W).attr("height", H);
  const root = svg.append("g");
  root.append("g").selectAll("line").data(il).join("line").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y)
    .attr("vector-effect", "non-scaling-stroke").attr("stroke", "var(--border)").attr("stroke-width", 1);
  root.append("g").selectAll("path").data(pl).join("path").attr("d", curve).attr("fill", "none")
    .attr("vector-effect", "non-scaling-stroke").attr("stroke", (d) => (d.p.live ? "var(--accent)" : "var(--border-2)")).attr("stroke-linecap", "round")
    .attr("stroke-dasharray", (d) => (d.p.kinds.size === 1 && d.p.kinds.has("talk") ? "6 5" : d.p.kinds.size === 1 && d.p.kinds.has("hand") ? "1 6" : null)).attr("stroke-width", (d) => Math.min(5, 1.5 + 0.6 * Math.log2(d.p.n)));
  const go = (h) => { location.hash = h; };
  root.append("g").selectAll("path").data(pl).join("path").attr("class", "swhit").attr("d", curve).attr("fill", "none")
    .attr("vector-effect", "non-scaling-stroke").attr("stroke", "transparent").attr("stroke-width", 22).style("cursor", "pointer")
    .on("click", (_, d) => go(hrefOf([d.p.a, d.p.b]))).append("title").text((d) => `${swName(d.p.a)} and ${swName(d.p.b)}: ${d.p.n} times`);
  const arrows = pl.flatMap((l) => [...l.p.dirs].map((dir) => { const t = dir.split(">")[1]; return { l, forward: t === l.target.id, to: byId[t] }; }));   // one small arrow per direction, at the dot it points to
  const arr = root.append("g").selectAll("path").data(arrows).join("path").attr("d", "M-5,-4 L4,0 L-5,4 Z").attr("fill", "var(--muted)").style("pointer-events", "none");
  const nums = root.append("g").selectAll("text").data(pl).join("text").attr("class", "swnum").text((d) => d.p.n).style("pointer-events", "none");
  const node = root.append("g").selectAll("g").data(nodes).join("g").attr("transform", (d) => `translate(${d.x},${d.y})`).style("cursor", "pointer")
    .on("click", (_, d) => go(d.kind === "idea" ? `#/swarm/artifact/${d.aid}` : hrefOf([d.id])));
  node.append("title").text((d) => (d.kind === "idea" ? d.label : `${swName(d.id)}: ${d.runs} run${d.runs === 1 ? "" : "s"}${d.failed ? `, ${d.failed} failed` : ""}`));
  const ring = node.filter((d) => d.kind === "agent" && (d.failing || d.live)).append("circle").attr("fill", "none").attr("vector-effect", "non-scaling-stroke")
    .attr("stroke", (d) => (d.failing ? "var(--err)" : "var(--accent)")).attr("stroke-width", 2.5).attr("class", (d) => (d.live ? "swlive" : ""));
  const dot = node.append("circle").attr("fill", (d) => (d.kind === "idea" ? (d.state === "done" ? "var(--ok)" : "var(--warn)") : SW_GCOL[swGroupOf(d.id)] || "var(--faint)"))
    .attr("stroke", "var(--surface)").attr("vector-effect", "non-scaling-stroke").attr("stroke-width", 1.5);
  const name = root.append("g").selectAll("text").data(agents).join("text").text((d) => d.label).attr("class", "swlbl swag").attr("y", (d) => rs(d) + 13)
    .style("pointer-events", "none");                       // an agent's name always shows, centred under its dot
  const text = root.append("g").selectAll("text").data(ideasAt).join("text").attr("transform", (d) => `translate(${d.x},${d.y})`)
    .text((d) => d.label).attr("class", "swlbl idea").style("pointer-events", "none");
  const items = ideasAt.map((d, i) => ({ x: d.x, y: d.y, rs: rs(d), text: d.label, el: text.nodes()[i], prio: 0 }));
  const onZoom = (t) => {
    dot.attr("r", (d) => rs(d) / t.k);
    ring.attr("r", (d) => (rs(d) + 3.5) / t.k);
    arr.attr("transform", (d) => { const q = swMapArrow(d.l, d.forward, (rs(d.to) + 7) / t.k); return `translate(${q.x},${q.y}) rotate(${q.a}) scale(${1 / t.k})`; });
    nums.attr("transform", (d) => `translate(${d.num[0]},${d.num[1]}) scale(${1 / t.k})`);
    name.attr("transform", (d) => `translate(${d.x},${d.y}) scale(${1 / t.k})`);
    placeLabels(items, t.k);
  };
  const fit = (animate) => (animate ? svg.transition().duration(250) : svg).call(zoom.transform, d3.zoomIdentity);   // laid out to fit already
  const zoom = chartZoom(el, svg, root, { onZoom: (tr) => { swOv.zoom = tr; onZoom(tr); }, fit });
  svg.call(zoom.transform, swOv.zoom || d3.zoomIdentity);     // and the zoom you left it at
  return card;
}

// ---------- one page per agent (#/swarm/agent/<id>, or its housekeeping page's Team tab) ----------
// a team card and a housekeeping job can share an id without being one agent: the team's curator keeps the wiki and the
// long-term memory (a Hermes profile); the job called "curator" curates the skills
const SW_OTHER_CREW = new Set(["curator"]);
const swIsCrew = (id) => !SW_OTHER_CREW.has(id) && (S?.crew || []).some((c) => c.id === id);
const SW_ENGINE = { main: "Hermes (chat)", mission: "Hermes (workflow steps)", scout: "Research (scout)", curator: "Wiki curator", builder: "Builder" };   // ops/crew.py ENGINES
function swAgentHref(id) {
  if (swIsCrew(id)) return `#/crew/${encodeURIComponent(id)}?tab=team`;
  if ((S?.swarm?.cards || []).includes(id) || (swCards || []).some((c) => c.id === id)) return `#/agent/${encodeURIComponent(id)}`;   // APP-76: its page
  return "";
}
const swActHref = (ids, hours, tests) => `#/home?tab=activity&agents=${ids.map(encodeURIComponent).join(",")}${hours ? `&h=${hours}` : ""}${tests ? "&tests=1" : ""}`;
async function swTeamData() {
  const who = await swWhoCards();
  const [tokens, it] = await Promise.all([api("/api/swarm/tokens").catch(() => ({})), api("/api/swarm/interactions?hours=168").catch(() => ({ nodes: [], edges: [] }))]);
  return { who, it, paused: S?.swarm?.paused || [], act: Object.fromEntries((it.nodes || []).map((n) => [n.id, n])),
    sc: Object.fromEntries(Object.entries(S?.swarm?.scorecards || {}).map(([k, v]) => [k, { ...v, tokens_30d: tokens[k] || 0 }])) };
}
function swDaysHtml(rows, all = rows) {             // telemetry rows (ops/history.py) -> one line a day, newest first
  const days = {};
  for (const r of rows) {
    const d = (days[r.day] = days[r.day] || { runs: 0, ok: 0, failed: 0, met: 0, partly: 0, not_met: 0, tokens: 0, cost: 0, p50: [] });
    for (const k of ["runs", "ok", "failed", "met", "partly", "not_met", "cost"]) d[k] += r[k] || 0;
    d.tokens += (r.tin || 0) + (r.tout || 0);
    if (r.p50_s != null) d.p50.push(r.p50_s);
  }
  const dayRows = Object.entries(days).sort((p, q) => (p[0] < q[0] ? 1 : -1));
  const first = all.reduce((m, r) => (r.day < m ? r.day : m), "9999"), young = first !== "9999" && first > dayKey(Date.now() - 30 * 86400e3);   // a history younger than 30 days says so; none is no date
  return `<div class="card pad-l section"><h2>${young ? `Since ${day(first)}` : "Last 30 days"} <span class="hcount">${dayRows.reduce((s, [, d]) => s + d.runs, 0)} runs</span></h2>
    ${dayRows.length ? `<div style="overflow-x:auto;margin-top:6px"><table class="swflow"><thead><tr><th>Day</th><th>Runs</th><th>Failed</th><th>Judged met</th><th>Tokens</th><th>Typical time</th><th>If paid</th></tr></thead><tbody>
      ${dayRows.map(([dd, d]) => `<tr><td>${day(dd)}</td><td>${d.runs}</td><td class="${d.failed ? "err-t" : ""}">${d.failed}</td><td>${d.met + d.partly + d.not_met ? `${d.met} of ${d.met + d.partly + d.not_met}` : "–"}</td><td>${tok(d.tokens)}</td><td>${d.p50.length ? dur(d.p50.sort((p, q) => p - q)[Math.floor(d.p50.length / 2)]) : "–"}</td><td>${d.cost ? ifPaid(d.cost) : "–"}</td></tr>`).join("")}</tbody></table></div>
      <div class="tiny faint" style="margin-top:4px">From the agents' history (<a href="#/system?tab=costs">Stack → Costs</a>), one row a day${young ? `; it began on ${day(first)}, so earlier runs are not in it` : ""}.</div>`
      : `<div class="small muted" style="margin-top:6px">No runs in the telemetry history yet: it adds a row for each day this runs.</div>`}</div>`;
}
async function swTelemetry() { return (typeof telData !== "undefined" && telData) || (telData = await api("/api/telemetry").catch(() => ({ rows: [] }))); }
async function swMissionDays(el, slug) {              // a mission's History tab: its days, like an agent's page
  if (!el) return;
  const tel = await swTelemetry();
  if (el.isConnected) el.outerHTML = swDaysHtml((tel.rows || []).filter((r) => r.agent === "mission:" + slug), tel.rows || []);
}
// what a team agent is (its card), how its last 30 days went (telemetry), with whom it works, its runs, what it said and
// did, and the ideas it worked on; the same panel on its own page and on a housekeeping agent's page (Team tab)
async function swAgentPanel(box, id, crew = false, tile = true) {    // crew: on its housekeeping page, which shows its issues, memory and (tile false) its card on top
  if (!box) return;
  box.innerHTML = `<div class="skeleton" style="height:200px"></div>`;
  const x = await swTeamData();
  const a = x.who.find((c) => c.id === id);
  const [tl, room, g, tel] = await Promise.all([api("/api/swarm/timeline?hours=168").catch(() => ({ runs: [], now: Date.now() / 1000 })),
    api("/api/swarm/room?hours=168").catch(() => ({ lines: [] })), swApi("graph", { days: 30 }).catch(() => ({})), swTelemetry()]);
  const mine = (r) => r.agent === id || (crew && r.agent === "crew:" + id) || (id === "mission" && r.agent.startsWith("mission:"));
  const journal = crew ? null : await api(`/api/file?path=${encodeURIComponent(`agents/${id}/MEMORY.md`)}`).then((t) => (typeof t === "string" ? parseJournal(t) : null)).catch(() => null);
  const health = crew ? [] : (S?.health?.items || []).filter((i) => i.kind !== "mission" && (i.id === id || i.id === SW_ENGINE[id] || i.name === SW_ENGINE[id]) && !(i.kind === "crew" && !swIsCrew(id)));
  const issues = health.flatMap((i) => i.issues || []);
  const tasks = (S?.tasks || []).map((t) => ({ t, steps: (t.steps || []).filter((s) => s.agent === id) })).filter((x) => x.steps.length);
  const journalHtml = journal ? `<div class="small" style="margin-top:6px"><b>Standing notes</b></div><ul class="jlist">${journal.notes.map((x) => `<li class="small">${esc(x)}</li>`).join("") || `<li class="small muted">none</li>`}</ul>
      <div class="small" style="margin-top:6px"><b>Last entries</b></div>${journal.entries.slice(-3).reverse().map((e) => `<div class="jentry"><div class="tiny muted jhead">${esc(e.head)}</div><ul class="jlist">${e.lines.map((x) => `<li class="small">${esc(x)}</li>`).join("")}</ul></div>`).join("") || `<div class="small muted">none yet</div>`}
      <div class="tiny faint" style="margin-top:4px"><span class="mono">agents/${esc(id)}/MEMORY.md</span> in the vault, read at the start of every run</div>`
    : id === "mission" ? `<div class="small muted" style="margin-top:6px">It keeps a journal per workflow, read at the start of that workflow's runs:</div><div class="list" style="margin-top:4px">${(S?.missions || []).filter((m) => !m.archived && m.status !== "archived").map((m) => `<a href="#/mission/${encodeURIComponent(m.slug)}?tab=memory"><div class="grow"><div class="ttl wrap">${esc(m.title)}</div><div class="sub">its standing notes and journal</div></div>${ic.next}</a>`).join("") || `<div class="small muted">No briefing or research workflow yet.</div>`}</div>`
    : id === "main" ? `<div class="small muted" style="margin-top:6px">Its memory is Hermes' own: its notes about you and the long-term memory of your conversations. Search or forget it on the <a href="#/system">Stack page</a>; a fact it wants to keep waits there for your OK when it is sensitive.</div>`
    : `${explain("it-keeps-no-journal-of-i", `It keeps no journal of its own: each run starts from its card, its standing instructions and the Board. Briefings, research and scheduled jobs keep journals.`, "About this")}`;
  const edges = (x.it.edges || []).filter((e) => e.from === id || e.to === id);
  const runs = (tl.runs || []).filter((r) => r.lane === id || r.agent === id).sort((p, q) => q.started - p.started);
  const lines = (room.lines || []).filter((l) => swInvolved(l).includes(id)).reverse();
  const ideaIds = [...new Set((g.touches || []).filter((t) => t.agent === id).map((t) => String(t.artifact)))];
  const ideas = ideaIds.map((i) => (g.artifacts || []).find((y) => String(y.id) === i) || { id: i, title: "", state: "" });
  const runRow = (r) => { 
    return `<a href="#/live/${encodeURIComponent(r.run)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(r.name)}</div>
      <div class="sub">${swTime(r.started)} · ${swDur((r.ended || tl.now) - r.started)}${r.by ? ` · started by ${esc(swName(r.by))}` : ""}${r.tokens ? ` · ${tok(r.tokens)} tokens` : ""}</div></div>${swPill(r.state)}</a>`; };
  box.innerHTML = `${!tile ? "" : a ? `<div class="swteam one">${swTile(a, x, false)}</div>` : `<div class="card pad-l small muted">${esc(swName(id))} has no card in the team (config/agents.yaml): it is a tool or a service the agents use.</div>`}
    ${crew || !tile ? "" : `<div id="swwfin" style="margin-top:12px"></div>`}
    ${crew ? "" : `<div class="card pad-l section"><h2>Health <span class="hcount">${issues.length}</span></h2>
      ${issues.length ? issues.map((x) => `<div class="banner ${x.severity === "alert" ? "" : "note"} agissue" style="margin-top:8px">${ic.alert}<span class="grow wrap">${esc(x.text)}${x.run ? ` · <a href="#/live/${encodeURIComponent(x.run)}">the run</a>` : ""}<span class="tiny faint"> · ${x.severity === "alert" ? "alert" : "note"}</span></span>${x.key ? `<button class="btn sm ghost" data-ack="${esc(x.key)}" title="Hides it here, from its count and from the Health doctor until it happens again. Nothing is fixed or deleted.">Seen</button>` : ""}</div>`).join("")
        : `<div class="small muted" style="margin-top:6px">No open issue on the health board.</div>`}</div>`}
    ${swDaysHtml((tel.rows || []).filter(mine), tel.rows || [])}
    <div class="card pad-l section"><h2>Works with <span class="hcount">${edges.length}</span></h2>
      ${edges.length ? `<div class="list" style="margin-top:6px">${edges.map((e) => { const other = e.from === id ? e.to : e.from, [verb] = swVerb(e);
        return `<a href="${swActHref([id, other], 168)}"><div class="grow"><div class="ttl">${esc(e.from === id ? `${verb} ${swName(other)}` : `${swName(other)} ${verb} it`)}</div><div class="sub">${e.n} time${e.n === 1 ? "" : "s"} in 7 days${e.last ? ` · last ${swAgo(e.last)}` : ""}</div></div>${ic.next}</a>`; }).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">It worked alone in the last 7 days.</div>`}</div>
    <div class="card pad-l section"><h2>Runs in the last 7 days <span class="hcount">${runs.length}</span></h2>
      ${runs.length ? `<div class="list" style="margin-top:6px">${runs.slice(0, 15).map(runRow).join("")}</div>${runs.length > 15 ? `<details><summary class="small muted" style="margin-top:6px">${runs.length - 15} earlier runs</summary><div class="list">${runs.slice(15).map(runRow).join("")}</div></details>` : ""}`
        : `<div class="small muted" style="margin-top:6px">No runs in the last 7 days.</div>`}</div>
    <div class="card pad-l section"><div class="row between wrap" style="gap:8px"><h2>What it said and did <span class="hcount">${lines.length}</span></h2><a class="btn sm" href="${swActHref([id], 168)}">All of it in Activity</a></div>
      ${lines.length ? `<div class="rroom" style="margin-top:6px">${lines.slice(0, 12).map(swRoomLine).join("")}</div>${lines.length > 12 ? `<a class="small" href="${swActHref([id], 168)}">${lines.length - 12} more in Activity</a>` : ""}`
        : `<div class="small muted" style="margin-top:6px">Nothing in the last 7 days.</div>`}</div>
    <div class="card pad-l section"><h2>Runs it did steps for <span class="hcount">${tasks.length}</span></h2>
      ${tasks.length ? `<div class="list" style="margin-top:6px">${tasks.map(({ t, steps }) => `<a href="#/task/${t.id}"><div class="grow" style="min-width:0"><div class="ttl wrap">#${t.id} ${esc(t.title)}</div>
        <div class="sub wrap">${steps.map((s) => `step ${s.idx}${s.occ > 1 ? ` (run ${s.occ})` : ""}: ${esc(s.title)} · ${esc(s.status)}`).join("; ")}</div></div><span class="pill ${t.status === "done" ? "ok" : t.status === "failed" ? "failed" : "running"}">${esc(t.status)}</span></a>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">No run (open or of the last 7 days) gave it a step.</div>`}</div>
    ${crew ? "" : `<div class="card pad-l section"><h2>Memory</h2>${journalHtml}</div>`}
    <div class="card pad-l section"><h2>Ideas it worked on <span class="hcount">${ideas.length}</span></h2>
      ${ideas.length ? `<div class="list" style="margin-top:6px">${ideas.map((i) => `<a href="#/swarm/artifact/${i.id}"><div class="grow"><div class="ttl">#${i.id} ${esc(i.title)}</div><div class="sub">${esc(i.state)}</div></div>${ic.next}</a>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">None in the last 30 days.</div>`}</div>`;
  swBindTiles(x.who);
  $$("[data-ack]", box).forEach((b) => (b.onclick = () => ackIssues(b.dataset.ack.split(" ").filter(Boolean), b)));
  if (!crew && tile) wfInInto($("#swwfin", box), "agent", id);   // WFL-11: every workflow the agent is a step of (its own page has Used in, APP-76)
}

// ---------- the Chatroom: the team room (SWM-107) ----------
// One timeline of what the agents do together, newest first, drawn from what they do (no agent is asked to post):
// Asks (tool calls between agents, with the answer), Helps (an agent works on another agent's artifact: a step into
// another's lane), Talk (the Board), Work (the shared artifacts), You (your decisions and messages) and Status (runs no one
// asked for, the stack's bookkeeping; off at first). Filters: type, agent (two picked: only what passes between them),
// topic, time and text. A link from Needs you (ctx=) opens on that conversation.
function swFold(text, n = 1200) {                     // cap: preview: one long text folds behind a visible "Show all" (AGENTS.md, Truncation)
  const s = String(text || "");
  if (s.length <= n + 600) return esc(s);                // folding away a few lines is not worth a tap
  return `${esc(s.slice(0, n))}<span hidden>${esc(s.slice(n))}</span> <button type="button" class="tag swmore">Show all (${nf(s.length - n)} more characters)</button>`;   // cap: preview: one tap shows the rest
}
const SW_ROOM_TYPES = [["you", "You"], ["ask", "Asks"], ["hand", "Hand-overs"], ["talk", "Board"], ["work", "Work"], ["help", "Helps"], ["status", "Status"]];
// a chip's lines: tool use counts under Asks, messages to you under You
const SW_KIND = { use: "ask", tell: "you" };
const swKind = (l) => SW_KIND[l.type] || l.type;
const SW_LINE = { ask: "Ask", use: "Uses", hand: "Hand-over", you: "You", talk: "Board", work: "Work", status: "Status" };
const swRoomF = { types: new Set(), agents: new Set(), topic: "", hours: 24, q: "", tests: false };
let swRoom = { t: 0, h: 0, d: null }, swRoomShow = 120;
async function swRoomLoad(force) {
  if (force || !swRoom.d || swRoom.h !== swRoomF.hours || swRoom.tests !== swRoomF.tests || Date.now() - swRoom.t > 15000)
    swRoom = { t: Date.now(), h: swRoomF.hours, tests: swRoomF.tests, d: await api(`/api/swarm/room?hours=${swRoomF.hours}${swRoomF.tests ? "&tests=1" : ""}`).catch(() => swRoom.d || { lines: [], error: "${APPNAME()} did not answer" }) };
  return swRoom.d;
}
const swInvolved = (l) => [l.actor, ...(l.to || [])].filter(Boolean);
// interactions.py between: what a line's number counts
const swBetween = (l, picked) => picked.has(l.actor) && (l.to || []).some((t) => picked.has(t) && t !== l.actor);
const swTopicOf = (l) => swGroupOf(l.type === "help" || l.type === "ask" ? l.target : l.actor === "you" || l.actor === "stack" || l.actor === "checker" ? (l.target || l.actor) : l.actor);
function swRoomMatch(l, skip) {
  const f = swRoomF, inv = swInvolved(l);
  if (skip !== "type" && (f.types.size ? !f.types.has(swKind(l)) : l.type === "status" && !f.agents.size)) return false;
  if (swCtx && !(l.ref?.context === swCtx || (swCtx.startsWith("artifact:") && String(l.ref?.artifact) === swCtx.slice(9)))) return false;
  if (skip !== "agent" && f.agents.size === 1 && !inv.some((a) => f.agents.has(a))) return false;
  if (skip !== "agent" && f.agents.size > 1 && !swBetween(l, f.agents)) return false;   // between the ones picked
  if (skip !== "topic" && f.topic && swTopicOf(l) !== f.topic) return false;
  if (f.q) { const q = f.q.toLowerCase(); if (![l.actor, l.target, l.verb, l.title, l.text, l.detail].join(" ").toLowerCase().includes(q)) return false; }
  return true;
}
let swJudged = {};                                     // help seq -> the latest verdict line on it (SWM-109)
// a line's time: the clock today, the day and the clock before (the lines of one task span days)
const swLineTime = (ts) => { const iso = new Date(ts * 1000).toISOString(), d = dayOf(iso); return d === "Today" ? clockOf(iso) : `${d} ${clockOf(iso)}`; };
// OBS-19: what the stack told you is the message itself, in plain words; the raw reason and the run are one tap away
function swTellLine(l, col, name) {
  const who = ["stack", "mission"].includes(l.actor) || swTaskFor({ actor: l.actor }) ? "" : name;   // its group already names a crew job
  return `<div class="rline t-tell${l.quiet ? " rquiet" : ""}"><span class="rav" style="background:${col}" aria-hidden="true">${esc(name.slice(0, 1).toUpperCase())}</span>
    <div class="grow" style="min-width:0">
      <div class="rhead"><span class="rtell">${swFold(l.text, 600)}</span><span class="tiny faint rtime">${swLineTime(l.ts)}</span></div>
      ${l.detail ? `<details class="rdet"><summary class="tiny muted">${esc(l.detail_label || "Details")}</summary><div class="small rtext">${swFold(l.detail)}</div></details>` : ""}
      ${who || l.state === "failed" ? `<div class="tiny faint rmeta">${who ? `From ${esc(who)}` : ""}${who && l.state === "failed" ? " · " : ""}${l.state === "failed" ? `<span class="err-t">not delivered</span>` : ""}</div>` : ""}
    </div></div>`;
}
function swRoomLine(l) {
  const g = swGroupOf(l.actor === "you" ? "you" : l.actor), col = SW_GCOL[g] || "var(--faint)", name = l.actor === "you" ? "You" : swName(l.actor);
  if (l.type === "tell") return swTellLine(l, col, name);
  const [scol, slabel] = l.state ? SW_STATE[l.state] || [null, l.state] : [null, ""];
  // OBS-21: one agent's request to another is one line; the request and the answer are one tap each
  const asked = l.type === "ask", request = asked && l.text && String(l.text).trim() !== l.summary;
  const art = l.ref?.artifact, links = [art ? `<a href="#/swarm/artifact/${art}">#${art}'s timeline</a>` : "", l.ref?.run ? `<a href="#/live/${encodeURIComponent(l.ref.run)}">its log</a>` : "",
    l.ref?.chat ? `<a href="#/chat?c=${encodeURIComponent(l.ref.chat)}">the chat</a>` : "", l.ref?.task ? `<a href="#/task/${l.ref.task}">the run</a>` : "", l.ref?.build ? `<a href="#/build/${l.ref.build}">the build</a>` : "",
    l.ref?.context && !swCtx ? `<a href="#" data-rctx="${esc(l.ref.context)}">this conversation</a>` : ""].filter(Boolean);
  return `<div class="rline t-${l.type}"><span class="rav" style="background:${col}" aria-hidden="true">${esc(name.slice(0, 1).toUpperCase())}</span>
    <div class="grow" style="min-width:0">
      <div class="rhead"><span class="wrap"><b>${esc(name)}</b> ${esc(l.verb)}${l.target ? ` <b>${esc(l.target.split(", ").map((x) => (x.startsWith("#") ? x : x === "you" ? "you" : swName(x))).join(", "))}</b>` : ""}${asked ? (l.summary ? `: ${esc(l.summary)}` : ` for help`) : ""}</span><span class="tiny faint rtime">${swLineTime(l.ts)}</span></div>
      ${l.title ? `<div class="small rtitle wrap">${art ? `<a href="#/swarm/artifact/${art}">${esc(l.title)}</a>` : esc(l.title)}</div>` : ""}
      ${request ? `<details class="rdet"><summary class="tiny muted">The request${l.words ? ` (${nf(l.words)} words)` : ""}</summary><div class="small rtext">${swFold(l.text)}</div></details>` : l.text && !asked ? `<div class="small rtext">${swFold(l.text, 600)}</div>` : ""}
      ${l.detail ? `<details class="rdet"><summary class="tiny muted">${asked ? `${esc(swName(l.target))}'s answer` : esc(l.detail_label || "More")}</summary><div class="small rtext">${swFold(l.detail)}</div></details>` : ""}
      ${l.ref?.help ? (swJudged[l.ref.help] ? `<div class="tiny rjudged">${esc(swJudged[l.ref.help].actor === "you" ? "You" : swName(swJudged[l.ref.help].actor))} ${esc(swJudged[l.ref.help].verb.replace(/^judged /, "judged this "))}</div>`
        : `<div class="row wrap" style="gap:6px;margin-top:6px"><span class="tiny faint">Was it useful to ${esc(swName(l.target))}?</span><button type="button" class="btn sm" data-hv="${l.ref.help}" data-useful="1">Useful</button><button type="button" class="btn sm ghost" data-hv="${l.ref.help}" data-useful="0">Not useful</button></div>`) : ""}
      <div class="tiny faint rmeta">${l.type === "help" ? `<span class="rhelp">helps ${esc(swName(l.target))}</span>` : `<span>${esc(SW_LINE[l.type] || l.type)}</span>`}${l.via ? ` · ${esc(l.via)}` : ""}${l.certainty === "matched" ? " · worked out from the timing" : ""}${l.world === "test" ? " · test" : ""}${slabel ? ` · <span style="color:${scol || "inherit"}">${esc(slabel)}</span>` : ""}${links.length ? " · " + links.join(" · ") : ""}</div>
    </div></div>`;
}
// OBS-22: the task a line belongs to: the one it names (interactions.task_of), or its agent's own duty (a crew job is a task)
function swTaskFor(l) {
  const ts = S?.tasks || [];
  return (l.task && ts.find((t) => t.id === +l.task)) || ts.find((t) => t.door === "crew" && t.ref === l.actor) || null;
}
const swAreaName = (a) => (a && typeof AREAS === "object" && AREAS[a]) || "";
function swTaskKey(l) {
  const t = swTaskFor(l);
  return t ? `task:${t.id}` : l.task ? `task:${l.task}` : l.type === "tell" && (l.area || l.title) ? `area:${l.area || l.title}` : `who:${l.actor}`;
}
function swTaskHead(l) {                               // the group's head: the task's name, a link to it, and its area as a quiet label
  const t = swTaskFor(l), id = t?.id || l.task, area = swAreaName(t?.area || l.area);
  const name = t ? t.title : id ? `Run #${id}` : l.type === "tell" && (l.area || l.title) ? area || l.title : l.actor === "you" ? "You" : swName(l.actor);
  const href = id ? `#/task/${id}` : l.actor !== "you" && l.type !== "tell" ? swAgentHref(l.actor) : "";
  return `<div class="rtask-h"><span class="wrap">${href ? `<a href="${href}">${esc(name)}</a>` : esc(name)}</span>${area && area !== name ? `<span class="tiny faint">${esc(area)}</span>` : ""}</div>`;
}
async function swChat(body, poll = false) {
  await swWhoCards();
  const d = await swRoomLoad(!poll), all = d.lines || [];
  const sig = JSON.stringify([all.length, all.at(-1)?.ts, [...swRoomF.types], [...swRoomF.agents], swRoomF.topic, swRoomF.hours, swRoomF.q, swRoomF.tests, swCtx, swRoomShow]);
  if (poll && sig === swLastSig) return;                       // nothing new: keep what the owner is typing
  swLastSig = sig;
  const typed = $("#swtext")?.value || "", qFocus = document.activeElement?.id === "rq";
  swJudged = {};
  for (const l of all) if (l.ref?.judges) swJudged[l.ref.judges] = l;
  const shown = all.filter((l) => swRoomMatch(l)).reverse(), page = shown.slice(0, swRoomShow);   // cap: list: "Show earlier" shows the rest
  const count = (pred) => all.filter(pred).length;
  const agents = {};
  for (const l of all.filter((l) => swRoomMatch(l, "agent"))) for (const a of swInvolved(l)) agents[a] = (agents[a] || 0) + 1;
  for (const a of swRoomF.agents) agents[a] = agents[a] || 0;            // a picked agent keeps its chip, also with nothing to show
  const topics = {};
  for (const l of all.filter((l) => swRoomMatch(l, "topic"))) { const t = swTopicOf(l); topics[t] = (topics[t] || 0) + 1; }
  // OBS-22: grouped by the task each line belongs to, the task with the newest line first and its lines newest first,
  // under the task's name and its area; a line of no task goes with its agent's duty, else its area or its agent
  const byTask = new Map();
  for (const l of page) { const k = swTaskKey(l); if (!byTask.has(k)) byTask.set(k, []); byTask.get(k).push(l); }
  const rows = [...byTask.values()].map((ls) => {
    const bursts = [];                                          // a burst of asks between the same two agents: one line that opens
    for (const l of ls) {
      const g = bursts.at(-1), same = g && l.type === "ask" && g[0].type === "ask" && g[0].actor === l.actor && g[0].target === l.target && g.at(-1).ts - l.ts < 900;
      same ? g.push(l) : bursts.push([l]);
    }
    return `<div class="rtask">${swTaskHead(ls[0])}${bursts.map((g) => {
      const l = g[0];
      if (g.length < 3) return g.map(swRoomLine).join("");
      const col = SW_GCOL[swGroupOf(l.actor)] || "var(--faint)", span = swLineTime(g.at(-1).ts) + "–" + clockOf(new Date(l.ts * 1000).toISOString());
      return `<details class="rburst"><summary class="rline t-ask"><span class="rav" style="background:${col}" aria-hidden="true">${esc(swName(l.actor).slice(0, 1).toUpperCase())}</span>
        <div class="grow" style="min-width:0"><div class="rhead"><span class="wrap"><b>${esc(swName(l.actor))}</b> asked <b>${esc(swName(l.target))}</b> ${g.length} times</span><span class="tiny faint rtime">${span}</span></div>
        <div class="tiny faint rmeta">Asks · tap for each request and its answer</div></div></summary>
        <div class="rburstin">${g.map(swRoomLine).join("")}</div></details>`;
    }).join("")}</div>`;
  }).join("");
  const cards = S?.swarm?.cards || [], rooms = ["all", "health", "code", "research", "house", "shopping", "ops"];
  const kinds = SW_ROOM_TYPES.map(([k, l]) => [k, l, count((x) => swKind(x) === k && swRoomMatch(x, "type"))]).filter(([k, , n]) => n || swRoomF.types.has(k));
  const people = Object.entries(agents).sort((a, b) => swRoomF.agents.has(b[0]) - swRoomF.agents.has(a[0]) || b[1] - a[1]);   // who is picked comes first, so it is always in sight
  const topicList = SW_GROUP.filter(([k]) => topics[k]);
  const cov = d.coverage || {};
  body.innerHTML = `<div class="card pad-l rfilters">
      <div class="row rfirst" style="gap:8px"><input class="input grow" id="rq" type="search" placeholder="Search" aria-label="Search what they said" value="${esc(swRoomF.q)}">
        <select class="input rsel" data-rh aria-label="Time window">${[[6, "6 h"], [24, "24 h"], [72, "3 days"], [168, "7 days"]].map(([h, l]) => `<option value="${h}"${swRoomF.hours === h ? " selected" : ""}>${l}</option>`).join("")}</select></div>
      ${explain("activity-what-passes", `Everything that passes between your agents and you, drawn from their work: nobody has to post here. It is grouped by the run each line belongs to, the newest first, with its area beside its name; a request from one agent to another and the raw reason of a failure are one tap away. Pick one name for what involves it, two for what passed between them. <b>Helps</b> are the rare steps into another agent's lane.${[...swRoomF.agents].some(swAgentHref) ? ` Open ${[...swRoomF.agents].filter(swAgentHref).map((a) => `<a href="${swAgentHref(a)}">${esc(swName(a))}'s page</a>`).join(" · ")}.` : ""}`, "About Activity")}
      <div class="chips scroll-x"><button type="button" class="tag ${swRoomF.types.size ? "" : "on"}" data-rt="">All</button>${kinds.map(([k, l, n]) => `<button type="button" class="tag ${swRoomF.types.has(k) ? "on" : ""}" data-rt="${k}">${l} <span class="faint">${n}</span></button>`).join("")}${cov.tests ? `<button type="button" class="tag ${swRoomF.tests ? "on" : ""}" data-rtests>Tests <span class="faint">${cov.tests}</span></button>` : ""}</div>
      ${people.length ? `<div class="chips scroll-x">${topicList.length > 1 || swRoomF.topic ? `<select class="input rsel rtopic" data-rtop aria-label="Topic"><option value="">All topics</option>${topicList.map(([k, l]) => `<option value="${k}"${swRoomF.topic === k ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>` : ""}${people.map(([a, n]) => `<button type="button" class="tag ${swRoomF.agents.has(a) ? "on" : ""}" data-ra="${esc(a)}"><span class="fdot" style="background:${SW_GCOL[swGroupOf(a)] || "var(--faint)"}"></span>${esc(a === "you" ? "You" : swName(a))} ${swRoomF.agents.has(a) ? "×" : `<span class="faint">${n}</span>`}</button>`).join("")}</div>` : ""}
      ${swCtx ? `<div class="chips"><button type="button" class="tag on" data-rctx="">${esc(swCtxName(swCtx))} ×</button></div>` : ""}
    </div>
    ${d.error ? `<div class="banner section">${ic.alert}<span class="small">${esc(d.error)}</span></div>` : ""}
    <div class="card pad-l section rroom">${rows || emptyState("Nothing here.", [swRoomF.hours < 168 ? `<button type="button" class="btn sm" data-rwide="h">Show 7 days</button>` : "",
        swRoomF.types.size ? `<button type="button" class="btn sm ghost" data-rwide="t">Every kind</button>` : "", swRoomF.agents.size || swCtx ? `<button type="button" class="btn sm ghost" data-rwide="a">Everyone</button>` : ""].join(""))}
      ${shown.length > page.length ? `<button type="button" class="btn sm ghost" id="rmore" style="margin-top:10px">Show earlier (${shown.length - page.length} more)</button>` : ""}
      ${cov.runs ? `<div class="tiny faint" style="margin-top:10px">${esc(swCoverage(cov))}</div>` : ""}</div>
    <details class="card pad-l section" id="rpost" ${swCtx || typed ? "open" : ""}><summary><b>Write to the agents</b></summary>
      <form id="swpost" class="swpost" style="margin-top:8px">
        <select name="to" class="input">${(swCtx.startsWith("room:") || swCtx.startsWith("artifact:") || swCtx.startsWith("dm:") ? [swCtx.startsWith("dm:") ? "agent:" + swCtx.slice(3).split("+").find((x) => !x.startsWith("owner")) : swCtx] : []).concat(rooms.map((r) => "room:" + r), cards.map((c) => "agent:" + c))
          .filter((v, i, a) => a.indexOf(v) === i).map((v) => `<option value="${esc(v)}">${esc(v.startsWith("agent:") ? "to " + v.slice(6) : swCtxName(v))}</option>`).join("")}</select>
        <textarea id="swtext" name="text" class="input" rows="2" placeholder="They read it at the start of their next run">${esc(typed)}</textarea>
        <div class="row between wrap" style="gap:8px"><label class="tiny"><input type="checkbox" name="request"> as a request (tracked until answered)</label><button class="btn sm primary">Send</button></div>
      </form></details>`;
  if (swTlBox) $(".rroom", body)?.after(swTlBox);
  const redraw = () => { swLastSig = ""; swSyncUrl(); swChat(body, true); if (swTlBox) swTimeline(swTlBox); };
  $$("[data-rwide]", body).forEach((b) => (b.onclick = () => { const k = b.dataset.rwide;
    if (k === "h") swRoomF.hours = 168; else if (k === "t") swRoomF.types.clear(); else { swRoomF.agents.clear(); swCtx = ""; }
    redraw(); }));
  $$("[data-rt]", body).forEach((b) => (b.onclick = () => { const k = b.dataset.rt; if (!k) swRoomF.types.clear(); else swRoomF.types.has(k) ? swRoomF.types.delete(k) : swRoomF.types.add(k); redraw(); }));
  $$("[data-rtests]", body).forEach((b) => (b.onclick = () => { swRoomF.tests = !swRoomF.tests; redraw(); }));
  $$("[data-ra]", body).forEach((b) => (b.onclick = () => { const a = b.dataset.ra; swRoomF.agents.has(a) ? swRoomF.agents.delete(a) : swRoomF.agents.add(a); redraw(); }));
  $$("[data-rtop]", body).forEach((b) => (b.onchange = () => { swRoomF.topic = b.value; redraw(); }));
  $$("[data-rh]", body).forEach((b) => (b.onchange = () => { swRoomF.hours = +b.value; swRoomShow = 120; redraw(); }));
  $$("[data-rctx]", body).forEach((a) => (a.onclick = (e) => { e.preventDefault(); swCtx = a.dataset.rctx; redraw(); }));
  $$(".swmore", body).forEach((b) => (b.onclick = () => { b.previousElementSibling.hidden = false; b.remove(); }));
  $$("[data-hv]", body).forEach((b) => (b.onclick = async () => {        // the owner's verdict on a help counts over the agent's
    const useful = b.dataset.useful === "1", reason = useful ? "" : prompt("What made it not useful? (optional: the agent's scorecard keeps it)", "");
    if (reason === null) return;
    b.disabled = true;
    if (await act({ action: "swarm_help_verdict", seq: +b.dataset.hv, useful, reason }, useful ? "Marked useful: recorded for this agent" : "Marked not useful: recorded for this agent")) { swLastSig = ""; swChat(body); }
    else b.disabled = false;
  }));
  if ($("#rmore")) $("#rmore").onclick = () => { swRoomShow += 120; redraw(); };
  const q = $("#rq");
  q.oninput = () => { clearTimeout(q._t); q._t = setTimeout(() => { swRoomF.q = q.value.trim(); redraw(); }, 250); };
  if (qFocus) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  $("#swpost").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target, text = f.text.value.trim();
    if (!text) return;
    const r = await act({ action: "swarm_post", to: [f.to.value], text, request: f.request.checked }, f.request.checked ? "Sent as a request: the agent answers here" : "Sent: it shows in the chatroom");
    if (r) { f.text.value = ""; swLastSig = ""; swChat(body); }
  };
}

// A success check in plain words (ops/checker.py check types)
function swCheck(c) {
  if (!c || !c.type) return "none yet";
  const d = c.days ? ` for ${c.days} days` : c.hours ? ` for ${c.hours} hours` : "";
  const keys = [...(c.keys || []), ...(c.key ? [c.key] : []), ...(c.kind ? ["any " + c.kind + " issue"] : [])];
  return { health_issue_absent: () => `the health issue ${keys.join(", ")} stays away${d}`,
    log_count: () => `“${c.pattern || ""}” shows up at most ${c.max ?? 0} times in ${String(c.container || "").startsWith("unit:") ? `the ${c.container.slice(5)} service's journal` : `the ${c.container || ""} logs`}${d}`,
    test_passes: () => `CI is green with the test ${c.nodeid || ""}`, ci_green: () => `CI is green on ${c.repo || "the repo"}`,
    smoke_ok: () => `the smoke test passes`, metric: () => `${c.name || "the metric"} ${c.op || "≤"} ${c.value ?? ""}${d}`,
    owner_confirms: () => `you confirm it works` }[c.type]?.() || c.type;
}

// ---------- the agents ----------
// ---------- the agent map: the team by job, what each one can reach, how it is doing (SWM-106) ----------
const SW_REACH = { fetch: "the web", browser: "a web browser", research: "web research (asks the scout)", mail: "your Gmail", phone: "the AI phone",
  house: "your house (Home Assistant)", qmd: "your vault (notes and wiki)", missions: "your workflows", claude: "Claude Code questions", graphify: "the code map",
  swarm: "the Board and the Ledger" };
const SW_PRIVATE = ["mail", "qmd", "house", "missions", "phone"], SW_UNTRUSTED = ["fetch", "browser", "research", "mail"], SW_OUT = ["fetch", "browser", "phone"];
const SW_WAKE = { never: "others cannot wake it", on_request: "wakes when an agent asks it", digest: "wakes for requests, at most every 6 h", always: "always on" };
function swHarness(c) {
  if (c.id === "builder") return "changes code in its sandbox; never pushes or deploys";
  return { "claude-code": "reads the code, read-only", hermes: "a Hermes profile", python: "a runner job with a model", script: "plain code, no model",
    opencode: "OpenCode" }[c.harness] || c.harness;
}
function swTile(a, x, link = true) {
  const s = x.sc[a.id], n = x.act[a.id], isP = x.paused.includes(a.id) || x.paused.includes("*"), tools = a.tools || [];
  const has = (xs) => tools.some((t) => xs.includes(t));
  const three = [has(SW_PRIVATE) && "reads your private data", has(SW_UNTRUSTED) && "takes in outside content", has(SW_OUT) && "can send data out"].filter(Boolean);
  const starts = (x.it.edges || []).filter((e) => e.from === a.id), startedBy = (x.it.edges || []).filter((e) => e.to === a.id);
  const pct = (v) => (v == null ? "–" : Math.round(v * 100) + "%"), href = link ? swAgentHref(a.id) : "";
  return `<div class="swtile"${href ? ` data-href="${href}"` : ""} style="border-top:3px solid ${SW_GCOL[swGroupOf(a.id)]}">
    <div class="row between wrap" style="gap:6px"><b>${href ? `<a href="${href}">${esc(swName(a.id))}</a>` : esc(swName(a.id))}</b><span>${isP ? `<span class="pill archived" style="padding:0 6px">paused</span> ` : ""}${n?.live ? `<span class="pill running" style="padding:0 6px">running</span>` : ""}${href ? `<span class="tiny faint">${ic.next}</span>` : ""}</span></div>
    <div class="small" style="margin-top:4px">${esc(a.purpose || "")}</div>
    <div class="tiny faint" style="margin-top:4px">${esc(swHarness(a))} · ${esc(a.model)} · ${esc(a.schedule || "")} · ${esc(SW_WAKE[a.wake] || a.wake || "")}</div>
    <div class="tiny" style="margin-top:6px">${tools.length ? `Can reach: ${tools.map((t) => `<span class="tag" style="padding:1px 7px">${esc(SW_REACH[t] || t)}</span>`).join(" ")}` : "No tools of its own."}</div>
    ${three.length ? `<div class="tiny" style="margin-top:4px;color:${three.length === 3 ? "var(--warn)" : "var(--muted)"}">${three.map(esc).join(" · ")}${three.length === 3 ? " (all three together: what leaves through the AI phone waits for your tap)" : ""}</div>` : ""}
    <div class="tiny" style="margin-top:6px">${n ? `Last 7 days: ${n.runs} run${n.runs === 1 ? "" : "s"}${n.failed ? `, <span style="color:var(--err)">${n.failed} failed</span>` : ""}, last ${swAgo(n.last)}` : "No runs in the last 7 days."}
      ${starts.length ? ` · starts ${starts.map((e) => `${esc(swName(e.to))} ${e.n}×`).join(", ")}` : ""}${startedBy.length ? ` · started by ${startedBy.map((e) => `${esc(swName(e.from))} ${e.n}×`).join(", ")}` : ""}</div>
    ${s?.ideas ? `<div class="tiny" style="margin-top:4px">${s.ideas} ideas · accepted ${pct(s.accepted_share)} · proved ${pct(s.proven_share)} · came back ${pct(s.reopen_rate)}${s.tokens_30d ? ` · ${tok(s.tokens_30d)} tokens in 30 d` : ""}</div>` : ""}
    ${s?.requests ? `<div class="tiny">${s.requests.received} request${s.requests.received === 1 ? "" : "s"} in 30 d: ${s.requests.answered} answered, ${s.requests.declined} declined, ${s.requests.expired} expired</div>` : ""}
    ${s?.failures ? `<div class="tiny">failures (MAST): ${s.failures.FC1} specification, ${s.failures.FC2} between agents, ${s.failures.FC3} verification</div>` : ""}
    <div class="row wrap" style="gap:8px;margin-top:8px"><a class="btn sm ghost" href="${swActHref([a.id], 168)}">Its activity</a>
      <button class="btn sm ghost" data-swpause="${esc(a.id)}" data-on="${isP ? "0" : "1"}">${isP ? "Resume" : "Pause"}</button>
      ${a.model && a.model !== "none" ? `<button class="btn sm" data-swset="${esc(a.id)}">${ic.tune}Settings</button>` : ""}</div>
    <div data-swsetbox="${esc(a.id)}"></div>
    <details class="tiny" style="margin-top:6px" data-a2a="${esc(a.id)}"><summary>A2A agent card (SWM-27)</summary><pre class="log" style="max-height:240px">loading…</pre></details></div>`;
}
function swBindTiles(who) {
  bindSwarmPause();
  $$("[data-swset]").forEach((b) => (b.onclick = () => swSettings(who.find((x) => x.id === b.dataset.swset), $(`[data-swsetbox="${CSS.escape(b.dataset.swset)}"]`))));
  $$("[data-a2a]").forEach((d) => (d.ontoggle = async () => {           // the card other agents would read, on the Docker network only
    if (!d.open || d.dataset.loaded) return;
    d.dataset.loaded = 1;
    d.querySelector("pre").textContent = JSON.stringify(await swApi("agent_card", { agent: d.dataset.a2a }).catch((e) => ({ error: e.message })), null, 1);
  }));
}
async function swAgents(body) {
  const x = await swTeamData();
  const groups = SW_GROUP.map(([k, l]) => [k, l, x.who.filter((a) => swGroupOf(a.id) === k)]).filter(([, , xs]) => xs.length);
  body.innerHTML = `<div class="row between wrap" style="gap:4px 12px;align-items:baseline;margin:2px 2px 4px"><span class="small muted">${x.who.length} agents, by their job</span>${explain("every-agent-by-its-job-w", `Every agent by its job: what it is for, how it runs, what it can reach, and how its last week went. Three things together make an agent risky: your private data, outside content and a way to send data out. <b>Tap an agent</b> for its page: its last 30 days, its runs, with whom it works, what it said and the ideas it worked on.`, "About this")}</div>
    ${groups.map(([k, l, xs]) => `<div class="section"><div class="section-h"><h2><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${SW_GCOL[k]};margin-right:6px"></span>${esc(l)} <span class="hcount">${xs.length}</span></h2></div>
      <div class="swteam">${xs.map((a) => swTile(a, x)).join("")}</div></div>`).join("")}`;
  swBindTiles(x.who);
}

// ---------- TSK-28, TSK-29: an agent's settings, tested before they apply ----------
// A change is not applied here: it becomes an agent change like the Coach's, replayed on the agent's past runs (no
// score may drop), then waits under Ideas for your Build it, and the build for your deploy tap; Revert undoes it.
// Adding a tool gives the agent's key access to it, so it asks for an explicit grant and is recorded as a security change.
function swSettings(a, box) {
  if (!a || !box) return;
  if (box.innerHTML) { box.innerHTML = ""; return; }
  const allTools = [...new Set((swCards || []).flatMap((c) => c.tools || []))].sort();
  const models = [...new Set([...Object.keys(S?.prices || {}), ...(swCards || []).map((c) => c.model)].filter((m) => m && m !== "none"))].sort();
  box.innerHTML = `<form class="swset card pad" style="margin-top:8px"><b class="small">Settings of ${esc(a.id)}</b>
    <div class="tiny faint" style="margin-top:2px">Saving tests the change on ${esc(a.id)}'s past runs first. It applies only if no score drops and you tap Build it under Ideas, then the deploy; Revert on the build undoes it.</div>
    <label class="field"><span>Model</span><select class="input" name="model">${models.map((m) => `<option${m === a.model ? " selected" : ""} value="${esc(m)}">${esc(m)}${S?.prices?.[m] ? ` · ${esc(S.prices[m].model)}` : ""}</option>`).join("")}</select></label>
    <label class="field"><span>Harness</span><select class="input" name="harness">${["hermes", "claude-code", "python"].map((h) => `<option${h === a.harness ? " selected" : ""}>${h}</option>`).join("")}</select></label>
    <div class="field"><span>Tools</span><div class="chips">${allTools.map((t) => `<label class="tag"><input type="checkbox" name="tools" value="${esc(t)}"${(a.tools || []).includes(t) ? " checked" : ""}> ${esc(SW_REACH[t] || t)}</label>`).join("")}</div></div>
    <label class="field"><span>Standing instructions <span class="tiny faint">one per line, at most 12</span></span><textarea class="input" name="instructions" rows="4">${esc((a.instructions || []).join("\n"))}</textarea></label>
    <label class="field"><span>Why</span><input class="input" name="why" maxlength="1000" placeholder="e.g. the cheaper model should do for its searches"></label>
    <label class="tag swgrant" hidden><input type="checkbox" name="grant"> <span></span></label>
    <div class="row wrap" style="gap:8px;margin-top:8px"><button class="btn sm primary" type="submit">${ic.check}Test this change</button><button class="btn sm ghost" type="button" data-swsetx>Cancel</button></div></form>`;
  const f = $("form", box), g = $(".swgrant", f);
  const added = () => [...f.querySelectorAll("[name=tools]:checked")].map((x) => x.value).filter((t) => !(a.tools || []).includes(t));
  const sync = () => { const ad = added(); g.hidden = !ad.length; $("span", g).textContent = `Grant it: ${a.id}'s key gets ${ad.map((t) => SW_REACH[t] || t).join(", ")} (a security change, recorded)`; };
  f.querySelectorAll("[name=tools]").forEach((x) => (x.onchange = sync));
  $("[data-swsetx]", f).onclick = () => (box.innerHTML = "");
  f.onsubmit = async (e) => {
    e.preventDefault();
    const change = { model: f.model.value, harness: f.harness.value, tools: [...f.querySelectorAll("[name=tools]:checked")].map((x) => x.value),
      instructions: f.instructions.value.split("\n").map((x) => x.trim()).filter(Boolean) };
    const sub = $("[type=submit]", f);
    sub.disabled = true;
    const r = await act({ action: "swarm_agent_change", agent: a.id, change, why: f.why.value.trim(), grant: f.grant.checked },
      (x) => `Change #${x.id}: ${x.diff.join("; ")}. Testing it on past runs; the result shows under Ideas`);
    sub.disabled = false;
    if (!r) return;
    swCards = null;
    location.hash = "#/ideas";
  };
}

// ---------- an artifact's timeline ----------
async function swArtifact(view, id) {
  view.innerHTML = `<div class="skeleton" style="height:200px"></div>`;
  let h;
  try { h = await swApi("history", { id }); } catch (e) { view.innerHTML = `<div class="card pad-l small muted">${esc(e.message)}</div>`; return; }
  const a = h.artifact, prog = (S?.swarm?.checks || {})[String(id)];
  const items = [...h.events.filter((e) => e.kind !== "message").map((e) => ({ ts: e.ts, who: e.actor, what: e.kind, text: e.reason || "", p: JSON.parse(e.payload || "{}") })),
    ...h.thread.map((m) => ({ ts: m.ts, who: m.sender, what: m.act, text: m.text, msg: true }))].sort((x, y) => x.ts - y.ts);
  view.innerHTML = `<a class="back" href="#/ideas">${ic.back || "‹"} Ideas</a>
    <div class="page-h"><h1>#${a.id} ${esc(a.title)}</h1><div class="small muted">${esc(a.kind)} · ${esc(a.state)} · owner ${esc(a.owner)} · priority ${nf(+a.priority, 2)}${a.recurrence ? ` · came back ${a.recurrence}×` : ""}</div></div>
    <div id="iorigin"></div>
    ${a.check ? `<div class="card pad-l section small">Success check: <b>${esc(swCheck(a.check))}</b>${prog ? `<div class="tiny faint">Checker: ${esc(prog)}</div>` : ""}</div>` : ""}
    <div class="card pad-l section"><h2>Timeline</h2><div class="swtimeline">${items.map((x) => `<div class="swev ${x.msg ? "msg" : ""}"><span class="tiny faint">${swTime(x.ts)}</span>
      <b class="small">${esc(swWho(x.who))}</b> <span class="tag">${esc(x.what === "transition" ? "→ " + (x.p.to || "") : x.what)}</span>
      <div class="small" style="white-space:pre-wrap">${esc(x.what === "evidence" ? x.p.text || "" : x.text)}</div></div>`).join("")}</div></div>
    <div class="card pad-l section"><h2>Evidence</h2><div class="list">${(a.evidence || []).map((e) => `<div style="padding:6px 2px"><div class="grow small">${esc(e.text)}<div class="tiny faint">${esc(e.actor || "")} · ${esc(e.ref || "")} · ${swTime(e.ts)}</div></div></div>`).join("") || `<div class="small muted">none</div>`}</div></div>
    <div class="card pad-l section"><h2>Write about it</h2><form id="swapost"><textarea name="text" class="input" rows="2" placeholder="To everyone working on this idea"></textarea>
      <div class="row" style="justify-content:flex-end;margin-top:6px"><button class="btn sm primary">Send</button></div></form></div>`;
  ideaOrigins().then((m) => {                             // how it came about: the run and task that first saw it
    const o = m.get(+a.id), el = $("#iorigin");
    if (!el || !o) return;
    if (!o.first_run) {                                     // written outside a recorded run (the weekly self-review): its writer's duty
      if (o.task) el.innerHTML = `<div class="card pad-l section"><h2>How it came about</h2><div class="small" style="margin-top:6px">Written by ${esc(agentName(o.owner))} during its scheduled job <a href="#/task/${o.task}">${esc(ideaTaskName(o))}</a>; no run of it was recorded.</div></div>`;
      return;
    }
    el.innerHTML = `<div class="card pad-l section"><h2>How it came about</h2><div class="small" style="margin-top:6px">First seen ${esc(when(new Date(o.first_at * 1000).toISOString()))}${o.first_actor ? ` by ${esc(agentName(o.first_actor))}` : ""} in <a href="#/live/${encodeURIComponent(o.first_run)}">a run</a>${o.task ? ` of <a href="#/task/${o.task}">${esc(ideaTaskName(o))}</a>` : ", outside any workflow"}.
      ${o.runs > 1 ? `Seen in ${nf(o.runs)} runs, the last ${esc(when(new Date(o.last_at * 1000).toISOString()))}.` : "Seen in that run only."} Every sighting is under Evidence.</div>
      ${o.editor ? `<div class="small" style="margin-top:8px">${editorHtml(o.editor)} <span class="muted">${esc(o.editor.reason)}</span></div>` : ""}</div>`;
  });
  $("#swapost").onsubmit = async (e) => {
    e.preventDefault();
    const t = e.target.text.value.trim();
    if (t && (await act({ action: "swarm_post", to: [`artifact:${id}`], text: t, artifact_id: id }, "Sent: it shows under this artifact"))) swArtifact(view, id);
  };
}
