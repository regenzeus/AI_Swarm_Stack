// The Agents tab (the row under its title is app.js's agentViews; four views since 1 Nov 2026): Overview (app.js vMissions with
// swOverview: working now, the map of who works with whom, every mission and housekeeping job), Activity (the room: what
// the agents do together, with filters, and the run timeline under them), Team (every agent, each with its own page,
// #/swarm/agent/<id> or its housekeeping page's Team tab) and Ideas (ideas, the task graph, the loop's numbers); an
// idea's full timeline is #/swarm/artifact/<id>. Reads through /api/swarm (Mission Control's read-only door to the Swarm service); the owner's
// posts go through the runner (action swarm_post), like every other action of the owner's. Requirements SWM-10, SWM-11, SWM-57, SWM-58.
// Phase 4: Now (who works on what this minute, the merge queue, the file leases: SWM-97, SWM-92, SWM-93), Tasks (the task
// graph of approved ideas: SWM-91), Flow (weekly proposed, accepted, proved, lead time, tokens per proved idea: SWM-99).
// Phase 5: Improve (agent changes with their experiments, the watch, replay sets, failure classes, requirements: SWM-18,
// SWM-20, SWM-82 to SWM-84).
let swTab = "now", swCtx = "", swTimer = null, swLastSig = "";

async function swApi(op, args = {}) {
  const r = await api("/api/swarm", { method: "POST", body: JSON.stringify({ op, args }) });
  if (!r || r.ok === false) throw new Error(r?.refused || r?.error || "the swarm is not reachable");
  return r.result;
}

const SW_ACT = { inform: "", request: "warn", propose: "run", handoff: "run", ack: "ok" };
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

const SW_ALIAS = { chat: "activity", timeline: "activity", tasks: "improve", flow: "improve" };   // links from before the four views
async function vSwarm() {                            // render() calls views without arguments; view is app.js's #view
  clearInterval(swTimer);
  if (route.args[0] === "artifact") return swArtifact(view, +route.args[1]);
  if (route.args[0] === "agent") return swAgentPage(view, decodeURIComponent(route.args[1] || ""));
  const asked = route.q.get("tab") || swTab;
  if (["map", "graph", "now", "list"].includes(asked)) { location.replace("#/missions"); return; }   // on the Overview now
  swTab = SW_ALIAS[asked] || asked;
  if (!["activity", "agents", "improve"].includes(swTab)) swTab = "activity";
  if (swTab === "activity") swActivityFromUrl();
  view.innerHTML = `<div class="hero heading" style="margin-bottom:10px"><h1>Agents</h1><p>Your agents as a team. They talk and propose; only your messages decide.</p></div>
    ${agentViews(swTab)}
    <div id="swbody"><div class="skeleton" style="height:200px"></div></div>`;
  const body = $("#swbody");
  try {
    if (swTab === "agents") return await swAgents(body);
    if (swTab === "improve") {
      body.innerHTML = `<div id="swideas"></div><div class="section-h section" id="swtasksh"><h2>Being built</h2><span class="tiny faint">approved ideas split into tasks</span></div><div id="swtasks"></div>
        <details class="card pad-l section" id="swflowd"${asked === "flow" ? " open" : ""}><summary><b>The improvement loop in numbers</b> <span class="small muted">ideas per week, replay sets, failures, requirements</span></summary><div id="swflow" style="margin-top:8px"></div></details>`;
      swIdeas($("#swideas"));
      swTasks($("#swtasks"));
      swFlow($("#swflow"));
      if (asked === "tasks" || asked === "flow") setTimeout(() => $(asked === "tasks" ? "#swtasksh" : "#swflowd")?.scrollIntoView({ block: "start" }), 60);
      swTimer = setInterval(() => (route.name === "swarm" && swTab === "improve" ? swIdeas($("#swideas"), true) : clearInterval(swTimer)), 8000);
      return;
    }
    await swActivity(body);
    swTimer = setInterval(() => (route.name === "swarm" && swTab === "activity" ? swActivity(body, true) : clearInterval(swTimer)), 4000);
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
  swRoomF.types = new Set(swRoomF.agents.size || swCtx ? SW_ROOM_TYPES.map(([k]) => k) : ["ask", "help", "talk", "work", "you"]);   // about someone: all of it
  const h = +q.get("h");
  swRoomF.hours = [6, 24, 72, 168].includes(h) ? h : swRoomF.agents.size ? 168 : 24;
  swRoomShow = 120;
  swLastSig = "";
}
function swSyncUrl() {
  const p = new URLSearchParams({ tab: "activity" });
  if (swRoomF.agents.size) p.set("agents", [...swRoomF.agents].join(","));
  if (swRoomF.hours !== 24) p.set("h", swRoomF.hours);
  if (swCtx) p.set("ctx", swCtx);
  route.q = p;
  history.replaceState(history.state, "", "#/swarm?" + p.toString().replace(/%2C/g, ","));
}
let swTlBox = null;                                  // the run timeline sits under the filters, which it shares with the room
async function swActivity(body, poll = false) {
  if (!swTlBox) { swTlBox = document.createElement("div"); swTlBox.id = "swacttl"; swTlBox.className = "section"; }
  await swChat(body, poll);
  if (!poll || Date.now() - (swActivity.t || 0) > 20000) { swActivity.t = Date.now(); await swTimeline(swTlBox, poll); }
}
function swOverview() {                              // the Overview's live parts (app.js vMissions): working now, the map
  const nb = $("#ovnow");
  if (nb) swNow(nb);
  swMapMount();
}

// ---------- who is working right now (SWM-97), the merge queue (SWM-93) and the file leases (SWM-92) ----------
function swRunOn(r) {                                // what a live run works on, from its run id and the builds
  const m = /^build:(\d+)/.exec(r.run || r.ref || "");
  if (m) {
    const b = (S?.builds || []).find((x) => x.id === +m[1]);
    return b ? `<a href="#/build/${b.id}">build #${b.id} ${esc(b.title)}</a>${b.task ? ` · task <a href="#/swarm/artifact/${b.task}">#${b.task}</a>` : ""}${b.idea ? ` of idea <a href="#/swarm/artifact/${b.idea}">#${b.idea}</a>` : ""}${b.slot ? ` · slot ${b.slot}` : ""}` : `build #${m[1]}`;
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
      <div class="small" style="margin-top:10px"><b>Files held by builds</b> <span class="muted">A build holds the files of its task while it works, so parallel builders never change the same file; a lease ends with its build or after 4 hours.</span></div>
      ${leases.length ? `<div class="list" style="margin-top:4px">${leases.map((l) => `<div style="padding:6px 2px"><div class="grow"><span class="mono small">${esc(l.path)}</span> <span class="tiny faint">${esc(l.repo)} · ${esc(l.holder)}${l.task ? ` · task #${l.task}` : ""} · until ${swTime(l.expires)}</span></div></div>`).join("")}</div>` : `<div class="small muted">No files are held.</div>`}
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
  }).join("") : `<div class="card pad-l small muted">No task graph yet: when you tap Build it on an idea whose files span more than one area, the planner splits it into tasks here, and builders take the ready ones at the same time.</div>`;
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
const SW_FC = { FC1: "specification", FC2: "between agents", FC3: "verification" };
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
  if (!b) { body.innerHTML = `<div class="card pad-l small muted">The swarm's Ledger is not reachable right now; the ideas come back when it is.</div>`; return; }
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
    <div class="tiny faint" style="margin-top:6px">Stack ideas: the crew and the weekly self-review (last ${imp.last ? rel(imp.last) : "not yet"}). Agent changes: the Coach, monthly, tested on past runs first.</div>
    <div class="chips" style="margin-top:10px">${[["all", "All"], ["stack", "The stack"], ["agent", "The agents"]].map(([k, l]) => `<button type="button" class="tag ${swIdeaKind === k ? "on" : ""}" data-ik="${k}">${l} <span class="faint">${count(k)}</span></button>`).join("")}</div></div>
    ${shown.map(([, h]) => h).join("") || `<div class="card pad-l section small muted">No open ideas${swIdeaKind === "all" ? "" : " of this kind"}.</div>`}
    ${decided.length ? `<details class="card pad-l section" ${(b.recent || []).some((p) => p.state === "checking") ? "open" : ""}><summary><b>Decided lately</b> <span class="small muted">${decided.length}</span></summary><div class="list" style="margin-top:6px">${decided.join("")}</div></details>` : ""}
    ${ideaRulesHtml()}`;
  $$("[data-ik]", body).forEach((x) => (x.onclick = () => { swIdeaKind = x.dataset.ik; swIdeas(body); }));
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
const SW_GROUP = [["owner", "You"], ["assistant", "Your assistant"], ["research", "Research"], ["missions", "Missions and briefings"],
  ["knowledge", "Knowledge and memory"], ["code", "Code"], ["reviewers", "Reviews and improvement"], ["health", "Health"], ["phone", "AI phone"],
  ["mail", "Mail"], ["other", "Other"]];
const SW_GCOL = { owner: "var(--ok)", assistant: "#60a5fa", research: "#2dd4bf", missions: "#fbbf24", knowledge: "#a78bfa", code: "#f472b6",
  reviewers: "#fb923c", health: "#a3e635", phone: "#94a3b8", mail: "#f87171", other: "var(--faint)" };
const SW_ROLEG = { assistant: "assistant", research: "research", missions: "missions", briefings: "missions", knowledge: "knowledge", memory: "knowledge",
  code: "code", tests: "code", reviewers: "reviewers", health: "health", phone: "phone", mail: "mail" };
const SW_LANE = { you: ["you", "owner"], claude: ["Claude tasks", "code"], evals: ["experiments", "reviewers"], reviewers: ["build reviewers", "reviewers"],
  gmail: ["Gmail", "mail"], phone: ["AI phone", "phone"], hermes: ["Hermes (your assistant or a mission)", "assistant"] };
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
const swName = (id) => (SW_LANE[id] ? SW_LANE[id][0] : id === "main" ? "main (your assistant)" : id);
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
  const t = await api(`/api/swarm/timeline?hours=${hours}`);
  const runs = pick.size ? t.runs.filter((r) => pick.has(r.lane) || pick.has(r.agent) || pick.has(r.by)) : t.runs;
  const sig = JSON.stringify([hours, [...pick], runs.map((r) => [r.run, r.state, r.ended])]);
  if (poll && sig === body.dataset.sig) return;
  body.dataset.sig = sig;
  swTlData = t;
  const order = Object.fromEntries(SW_GROUP.map(([k], i) => [k, i]));
  const count = {};
  for (const r of runs) count[r.lane] = (count[r.lane] || 0) + 1;
  const lanes = Object.keys(count).sort((a, b) => (order[swGroupOf(a)] - order[swGroupOf(b)]) || count[b] - count[a]);
  const live = runs.filter((r) => r.state === "running").length;
  if (!runs.length) { body.innerHTML = `<div class="card pad-l small muted">No runs in this window${pick.size ? " for " + [...pick].map(swName).join(" and ") : ""}.</div>`; return; }
  body.innerHTML = `<details class="card pad-l" id="swtlcard"${swTimeline.closed ? "" : " open"}><summary><b>When each ran</b> <span class="hcount">${runs.length}</span> <span class="small muted">${live ? `${live} running now` : "one bar per run"}</span></summary>
    ${explain("one-row-per-agent-one-ba", `One row per agent, one bar per run, coloured by how it ended. A run another agent started (a mission's web searches by the scout) sits in its own row; tap a bar to see what started it and what it started.`, "How to read this")}
    <div class="swtl" style="margin-top:8px"></div>
    <div class="row wrap tiny faint" style="gap:12px;margin-top:6px">${Object.entries(SW_STATE).map(([, [c, l, hollow]]) => `<span class="row" style="gap:5px"><span style="width:12px;height:8px;border-radius:2px;${hollow ? `box-shadow:inset 0 0 0 1.5px ${c}` : `background:${c}`}"></span>${l}</span>`).join("")}<span class="row" style="gap:5px"><span style="width:0;height:10px;border-left:1.5px dashed var(--muted)"></span>now</span></div>
    <div class="tiny faint" style="margin-top:2px">Failed: the run ended with an error. Stuck: it went silent for 20 minutes and was closed.</div>
    <div id="swtldet"></div></details>`;
  $("#swtlcard", body).ontoggle = (e) => { swTimeline.closed = !e.target.open; };
  const sc = $(".swtl"), box = sc.clientWidth || 320, span = t.now - t.since;
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
        const x = X(r.started), w = Math.max(3, X(r.ended || t.now) - x), [col, , hollow] = SW_STATE[r.state] || SW_STATE.done;
        return `<rect class="swbar ${r.state === "running" ? "live" : ""}" data-run="${esc(r.run)}" x="${x.toFixed(1)}" y="${hollow ? 2.75 : 2}" width="${(hollow ? Math.max(1.5, w - 1.5) : w).toFixed(1)}" height="${hollow ? 10.5 : 12}" rx="3" ${hollow ? `fill="transparent" stroke="${col}" stroke-width="1.5"` : `fill="${col}"`}><title>${esc(r.name)}</title></rect>`;
      }).join("")}</svg></div>`).join("")}</div>`;
  const showRun = (id) => {
    swTlSel = id;
    const r = t.runs.find((x) => x.run === id);
    if (!r) return;
    const kids = t.runs.filter((x) => x.parent === id), par = t.runs.find((x) => x.run === r.parent);
    $$(".swbar").forEach((b) => b.classList.toggle("sel", b.dataset.run === id));
    $$(".swbar").forEach((b) => b.classList.toggle("rel", [r.parent, ...kids.map((k) => k.run)].includes(b.dataset.run)));
    const pair = r.by && r.by !== "you" && r.by !== r.lane ? swActHref([r.by, r.lane], hours) : "";
    $("#swtldet").innerHTML = `<div class="card pad-l section"><div class="row between wrap" style="gap:6px"><h2 class="wrap">${esc(r.name)}</h2>${swPill(r.state)}</div>
      <div class="small" style="margin-top:4px"><b>${esc(swName(r.lane))}</b>${r.agent !== r.lane ? ` <span class="tiny faint">(${esc(r.agent)})</span>` : ""} · ${swTime(r.started)}${r.ended ? ` to ${swTime(r.ended)}` : ", still running"} · ${swDur((r.ended || t.now) - r.started)}</div>
      <div class="small muted">${r.calls} model call${r.calls === 1 ? "" : "s"}${r.tokens ? ` · ${tok(r.tokens)} tokens` : ""}${r.by ? ` · started by ${r.by === "you" ? "you (a chat)" : par ? `<a href="#" data-tlrun="${esc(par.run)}">${esc(swName(r.by))}</a>` : esc(swName(r.by))}` : ""}</div>
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
let swMapHours = 168, swMapIdeas = false, swOv = { el: null, t: 0, sig: "" };
const SW_ROLE = { you: "you, in chat and in the app", claude: "Claude Code, a read-only analysis in the sandbox", evals: "replays of agents' past runs (agent-change tests)",
  reviewers: "reviews of a build by the other engine", gmail: "your Gmail, through its connector", phone: "the AI phone",
  hermes: "Hermes, your assistant or a mission's agent", conductor: "the Conductor, which runs a task's plan step by step" };
function swRole(id) {
  if (SW_ROLE[id]) return SW_ROLE[id];
  const c = (swCards || []).find((x) => x.id === id);
  return c?.purpose || "";
}
function swVerb(e) {                                     // what the connection was, in words
  if (e.kind === "messages") return ["wrote on the Board with", "↔"];
  if (e.from === "you") return [e.to === "main" ? "chatted with" : "started", "→"];
  return [{ scout: "asked to research", claude: "asked Claude Code for an analysis", phone: "used", gmail: "read mail through", evals: "replayed through" }[e.to] || "started a run of", "→"];
}
const swShort = (id) => ({ hermes: "Hermes", claude: "Claude tasks", evals: "experiments", gmail: "Gmail", phone: "AI phone", reviewers: "reviewers" }[id] || id);   // a dot's name
const swIdeaLabel = (x) => { const w = String(x.title || "").split(/\s+/).filter(Boolean); return `#${x.id} ${w.slice(0, 4).join(" ")}${w.length > 4 ? " …" : ""}`; };   // cap: preview: the dot's name; its card and the list name it whole
async function swMapData() {
  await swWhoCards();
  const [it, g] = await Promise.all([api(`/api/swarm/interactions?hours=${swMapHours}`),
    swApi("graph", { days: swMapIdeas ? 30 : Math.max(1, Math.round(swMapHours / 24)) }).catch(() => ({ talk: [], agents: [], artifacts: [], touches: [] }))]);
  const me = (x) => (swWho(x) === "you" ? "you" : x);
  const talk = (g.talk || []).map((x) => ({ from: me(x.a), to: me(x.b), kind: "messages", n: x.n, live: 0 })).filter((x) => x.from !== x.to);
  return { it, g, edges: [...it.edges, ...talk] };
}
function swMapMount(force) {                            // Overview's map survives the page's live redraws (state updates)
  const ph = $("#ovmap");
  if (!ph) return;
  if (swOv.el && swOv.el !== ph && !force) ph.replaceWith(swOv.el);
  if (force || !swOv.el || Date.now() - swOv.t > 60000) {
    swOv.t = Date.now();
    swMapData().then((d) => {
      const sig = JSON.stringify([swMapHours, swMapIdeas, d.edges, d.it.nodes.map((n) => [n.id, n.runs, n.failed, n.live]), swMapIdeas ? d.g.touches : 0]);
      const cur = $("#ovmap");
      if (!cur || (!force && sig === swOv.sig && swOv.el)) return;
      swOv.sig = sig;
      swOv.el = swMapCard(cur, d);
    }).catch((e) => { const cur = $("#ovmap"); if (cur && !swOv.el) cur.innerHTML = `<div class="card pad-l small muted">The map could not load: ${esc(e.message)}</div>`; });
  }
}
function swMapCard(ph, { it, g, edges }) {
  const card = document.createElement("div");
  card.id = "ovmap";
  card.className = "card pad-l section";
  const info = Object.fromEntries(it.nodes.map((n) => [n.id, n]));
  const pairs = {};
  for (const e of edges) {
    const [a, b] = [e.from, e.to].sort(), k = a + "+" + b, p = (pairs[k] = pairs[k] || { a, b, n: 0, dirs: new Set(), kinds: new Set(), live: 0, last: 0 });
    p.n += e.n; p.kinds.add(e.kind); p.live += e.live || 0; p.last = Math.max(p.last, e.last || 0);
    if (e.kind !== "messages") p.dirs.add(e.from + ">" + e.to);
  }
  const used = new Set(edges.flatMap((e) => [e.from, e.to]));
  const agentIds = [...new Set([...it.nodes.filter((n) => n.runs || used.has(n.id)).map((n) => n.id), ...used])];
  const closed = (s) => ["declined", "merged", "gone"].includes(s);
  const ideas = swMapIdeas ? (g.artifacts || []).filter((x) => !closed(x.state)) : [];
  const touches = swMapIdeas ? (g.touches || []).map((t) => ({ agent: swWho(t.agent) === "you" ? "you" : t.agent, artifact: t.artifact, n: t.n })) : [];
  const groups = [...new Set(agentIds.map(swGroupOf))];
  const conn = Object.values(pairs).sort((x, y) => y.n - x.n);
  const who = (id) => { const n = info[id]; return `<div class="swwho"><div class="row" style="gap:6px"><span class="swdot" style="background:${SW_GCOL[swGroupOf(id)]}"></span><b class="wrap">${esc(swName(id))}</b>
      ${n?.runs ? `<span class="tiny faint">${n.runs} run${n.runs === 1 ? "" : "s"}${n.failed ? ` · <span class="err-t">${n.failed} failed</span>` : ""}</span>` : ""}</div>
      ${swRole(id) ? `<div class="tiny muted wrap">${esc(swRole(id))}</div>` : ""}</div>`; };
  const row = (e) => { const [verb, arrow] = swVerb(e);
    return `<a class="swconn" href="${swActHref([e.from, e.to], swMapHours)}">${who(e.from)}<div class="swverb"><span class="swarrow">${arrow}</span><span class="wrap"><b>${esc(verb)}</b> · ${e.n} time${e.n === 1 ? "" : "s"}${e.last ? ` · last ${swAgo(e.last)}` : ""}${e.live ? ` · <b class="ok-t">${e.live} now</b>` : ""}</span></div>${who(e.to)}</a>`; };
  const alone = agentIds.filter((id) => !used.has(id));
  const shared = Object.entries(g.shared || {});
  card.innerHTML = `<div class="row between wrap" style="gap:8px"><h2>Who works with whom</h2><div class="chips">${[[24, "24 h"], [72, "3 days"], [168, "7 days"]].map(([h, l]) => `<button type="button" class="tag ${swMapHours === h ? "on" : ""}" data-mh="${h}">${l}</button>`).join("")}</div></div>
    ${explain("each-dot-is-an-agent-the", `Each dot is an agent: the bigger, the more it ran; a red ring means some runs failed. A line joins two agents that worked together: the arrow points from the one who asked, the number says how often, dashed means they only wrote to each other. <b>Tap a dot or a line</b> for what they said and did.`, "How to read this")}
    <div class="chips" style="margin-top:8px"><button type="button" class="tag ${swMapIdeas ? "on" : ""}" data-mideas>Ideas too</button></div>
    <div class="swmapsvg" style="margin-top:6px"></div><div class="tiny faint" style="margin-top:4px">${CHART_HINT} or a line</div>
    <div class="row wrap tiny faint" style="gap:12px;margin-top:6px">${groups.map((k) => `<span class="row" style="gap:5px"><span class="swdot" style="background:${SW_GCOL[k]}"></span>${esc((SW_GROUP.find(([x]) => x === k) || [, k])[1])}</span>`).join("")}${swMapIdeas ? `<span class="row" style="gap:5px"><span class="swdot" style="background:var(--warn);width:7px;height:7px"></span>an open idea</span>` : ""}</div>
    <details class="swmapwords" style="margin-top:10px"><summary class="small"><b>Every connection in words</b> <span class="muted">${conn.length}${alone.length ? ` · ${alone.length} worked alone` : ""}</span></summary>
      ${edges.length ? `<div class="swconns" style="margin-top:6px">${edges.sort((x, y) => y.n - x.n).map(row).join("")}</div>` : `<div class="small muted" style="margin-top:6px">No agent started or wrote to another in this window.</div>`}
      ${alone.length ? `<div class="small" style="margin-top:10px"><b>Worked alone</b> <span class="muted">ran without starting or messaging another agent</span></div><div class="swalone">${alone.map(who).join("")}</div>` : ""}
      ${swMapIdeas ? `<div class="small" style="margin-top:10px"><b>Ideas two or more work on</b></div>${shared.length ? `<div class="list">${shared.map(([aid, ws]) => { const a = (g.artifacts || []).find((x) => String(x.id) === aid) || {};
        return `<a href="#/swarm/artifact/${aid}"><div class="grow"><div class="ttl">#${aid} ${esc(a.title || "")}</div><div class="sub">${ws.map(esc).join(", ")} · ${esc(a.state || "")}</div></div>${ic.next}</a>`; }).join("")}</div>` : `<div class="small muted">None yet: so far each idea has one worker.</div>`}` : ""}
    </details>`;
  ph.replaceWith(card);
  $$("[data-mh]", card).forEach((b) => (b.onclick = () => { swOv.pos = swOv.zoom = null; swMapHours = +b.dataset.mh; swMapMount(true); }));
  $("[data-mideas]", card).onclick = () => { swOv.pos = swOv.zoom = null; swMapIdeas = !swMapIdeas; swMapMount(true); };
  const el = $(".swmapsvg", card);
  if (!agentIds.length) { el.innerHTML = emptyState("No agent ran in this window.", `<button type="button" class="btn sm" data-mh2="168">Show 7 days</button>`); $("[data-mh2]", el).onclick = () => { swMapHours = 168; swMapMount(true); }; return card; }
  const W = el.clientWidth || 340, H = Math.max(340, Math.min(540, Math.round(window.innerHeight * 0.68)));
  el.style.height = H + "px";
  const nodes = [...agentIds.map((id) => ({ id, kind: "agent", label: swShort(id), runs: info[id]?.runs || 0, failed: info[id]?.failed || 0, live: info[id]?.live || 0 })),
    ...ideas.map((x) => ({ id: "x:" + x.id, kind: "idea", label: swIdeaLabel(x), aid: x.id, state: x.state }))];
  const ids = new Set(nodes.map((n) => n.id));
  const links = [...conn.map((p) => ({ source: p.a, target: p.b, p, kind: "pair" })),
    ...touches.map((t) => ({ source: t.agent, target: "x:" + t.artifact, n: t.n, kind: "idea" }))].filter((l) => ids.has(l.source) && ids.has(l.target));
  const rs = (d) => (d.kind === "idea" ? 4 : Math.min(14, 5 + 1.8 * Math.log2(1 + d.runs)));          // screen px at any zoom
  // laid out at screen size inside the box (the dots keep their size at any zoom, so a zoomed-out fit piled them up):
  // the whole team shows at once, each name readable; zoom in for a crowded corner
  const padX = 48, padY = 20, was = swOv.pos || {};
  for (const n of nodes) if (was[n.id]) Object.assign(n, was[n.id], { fx: was[n.id].x, fy: was[n.id].y });   // a redraw keeps every dot where it was; a new one settles around them
  const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance((l) => (l.kind === "idea" ? 34 : 70)).strength(0.35))
    .force("charge", d3.forceManyBody().strength((d) => (d.kind === "idea" ? -40 : -170))).force("x", d3.forceX(W / 2).strength(0.05)).force("y", d3.forceY(H / 2).strength(0.07))
    .force("collide", d3.forceCollide((d) => (d.kind === "idea" ? rs(d) + 6 : rs(d) + 20))).stop();      // room for the name under each dot
  const settled = nodes.every((n) => was[n.id]);
  for (let i = 0; i < (settled ? 0 : nodes.some((n) => was[n.id]) ? 120 : 500); i++) {   // laid out once: nothing drifts under a finger
    sim.tick();
    for (const n of nodes) { n.x = Math.max(padX, Math.min(W - padX, n.x)); n.y = Math.max(n.x > W - 96 ? 132 : padY, Math.min(H - padY - 14, n.y)); }   // the zoom buttons keep their corner
  }
  const svg = d3.select(el).append("svg").attr("width", W).attr("height", H);
  const root = svg.append("g");
  const pl = links.filter((l) => l.kind === "pair"), il = links.filter((l) => l.kind === "idea");
  root.append("g").selectAll("line").data(il).join("line").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y)
    .attr("vector-effect", "non-scaling-stroke").attr("stroke", "var(--border)").attr("stroke-width", 1);
  root.append("g").selectAll("line").data(pl).join("line").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y)
    .attr("vector-effect", "non-scaling-stroke").attr("stroke", (d) => (d.p.live ? "var(--accent)" : "var(--border-2)")).attr("stroke-linecap", "round")
    .attr("stroke-dasharray", (d) => (d.p.dirs.size ? null : "6 5")).attr("stroke-width", (d) => Math.min(7, 1.5 + Math.log2(d.p.n)));
  const go = (h) => { location.hash = h; };
  root.append("g").selectAll("line").data(pl).join("line").attr("class", "swhit").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y)
    .attr("vector-effect", "non-scaling-stroke").attr("stroke", "transparent").attr("stroke-width", 22).style("cursor", "pointer")
    .on("click", (_, d) => go(swActHref([d.p.a, d.p.b], swMapHours))).append("title").text((d) => `${swName(d.p.a)} and ${swName(d.p.b)}: ${d.p.n} times`);
  const arrows = [];                                       // one small arrow per direction, kept at screen size like the dots
  for (const l of pl) for (const dir of l.p.dirs) {
    const [f, t] = dir.split(">"), s = f === l.source.id ? l.source : l.target, e = f === l.source.id ? l.target : l.source;
    arrows.push({ x: s.x + (e.x - s.x) * 0.6, y: s.y + (e.y - s.y) * 0.6, a: (Math.atan2(e.y - s.y, e.x - s.x) * 180) / Math.PI, t });
  }
  const arr = root.append("g").selectAll("path").data(arrows).join("path").attr("d", "M-5,-4 L4,0 L-5,4 Z").attr("fill", "var(--muted)").style("pointer-events", "none");
  const nums = root.append("g").selectAll("text").data(pl).join("text").attr("class", "swnum").text((d) => d.p.n).style("pointer-events", "none");
  const mid = (d) => [(d.source.x + d.target.x) / 2, (d.source.y + d.target.y) / 2];
  const node = root.append("g").selectAll("g").data(nodes).join("g").attr("transform", (d) => `translate(${d.x},${d.y})`).style("cursor", "pointer")
    .on("click", (_, d) => go(d.kind === "idea" ? `#/swarm/artifact/${d.aid}` : swActHref([d.id], swMapHours)));
  node.append("title").text((d) => (d.kind === "idea" ? d.label : `${swName(d.id)}: ${d.runs} run${d.runs === 1 ? "" : "s"}${d.failed ? `, ${d.failed} failed` : ""}`));
  const ring = node.filter((d) => d.kind === "agent" && (d.failed || d.live)).append("circle").attr("fill", "none").attr("vector-effect", "non-scaling-stroke")
    .attr("stroke", (d) => (d.failed ? "var(--err)" : "var(--accent)")).attr("stroke-width", 2.5).attr("class", (d) => (d.live ? "swlive" : ""));
  const dot = node.append("circle").attr("fill", (d) => (d.kind === "idea" ? (d.state === "done" ? "var(--ok)" : "var(--warn)") : SW_GCOL[swGroupOf(d.id)] || "var(--faint)"))
    .attr("stroke", "var(--surface)").attr("vector-effect", "non-scaling-stroke").attr("stroke-width", 1.5);
  const agentsN = nodes.filter((d) => d.kind === "agent"), ideasN = nodes.filter((d) => d.kind === "idea");
  const name = root.append("g").selectAll("text").data(agentsN).join("text").text((d) => d.label).attr("class", "swlbl swag").attr("y", (d) => rs(d) + 13)
    .style("pointer-events", "none");                       // an agent's name always shows, centred under its dot
  const text = root.append("g").selectAll("text").data(ideasN).join("text").attr("transform", (d) => `translate(${d.x},${d.y})`)
    .text((d) => d.label).attr("class", "swlbl idea").style("pointer-events", "none");
  const items = ideasN.map((d, i) => ({ x: d.x, y: d.y, rs: rs(d), text: d.label, el: text.nodes()[i], prio: 0 }));
  const onZoom = (t) => {
    dot.attr("r", (d) => rs(d) / t.k);
    ring.attr("r", (d) => (rs(d) + 3.5) / t.k);
    arr.attr("transform", (d) => `translate(${d.x},${d.y}) rotate(${d.a}) scale(${1 / t.k})`);
    nums.attr("transform", (d) => { const [x, y] = mid(d); return `translate(${x},${y}) scale(${1 / t.k})`; });
    name.attr("transform", (d) => `translate(${d.x},${d.y}) scale(${1 / t.k})`);
    placeLabels(items, t.k);
  };
  swOv.pos = Object.fromEntries(nodes.map((n) => [n.id, { x: n.x, y: n.y }]));
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
const SW_ENGINE = { main: "Hermes (chat)", mission: "Hermes (missions)", scout: "Research (scout)", curator: "Wiki curator", builder: "Builder" };   // ops/crew.py ENGINES
function swAgentHref(id) {
  if (swIsCrew(id)) return `#/crew/${encodeURIComponent(id)}?tab=team`;
  if ((S?.swarm?.cards || []).includes(id) || (swCards || []).some((c) => c.id === id)) return `#/swarm/agent/${encodeURIComponent(id)}`;
  return "";
}
const swActHref = (ids, hours) => `#/swarm?tab=activity&agents=${ids.map(encodeURIComponent).join(",")}${hours ? `&h=${hours}` : ""}`;
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
  const first = all.reduce((m, r) => (r.day < m ? r.day : m), "9999"), young = first > dayKey(Date.now() - 30 * 86400e3);   // a history younger than 30 days says so
  return `<div class="card pad-l section"><h2>${young ? `Since ${day(first)}` : "Last 30 days"} <span class="hcount">${dayRows.reduce((s, [, d]) => s + d.runs, 0)} runs</span></h2>
    ${dayRows.length ? `<div style="overflow-x:auto;margin-top:6px"><table class="swflow"><thead><tr><th>Day</th><th>Runs</th><th>Failed</th><th>Judged met</th><th>Tokens</th><th>Typical time</th><th>If paid</th></tr></thead><tbody>
      ${dayRows.map(([dd, d]) => `<tr><td>${day(dd)}</td><td>${d.runs}</td><td class="${d.failed ? "err-t" : ""}">${d.failed}</td><td>${d.met + d.partly + d.not_met ? `${d.met} of ${d.met + d.partly + d.not_met}` : "–"}</td><td>${tok(d.tokens)}</td><td>${d.p50.length ? dur(d.p50.sort((p, q) => p - q)[Math.floor(d.p50.length / 2)]) : "–"}</td><td>${d.cost ? ifPaid(d.cost) : "–"}</td></tr>`).join("")}</tbody></table></div>
      <div class="tiny faint" style="margin-top:4px">From the telemetry history (<a href="#/telemetry">Stack → Telemetry</a>), one row a day${young ? `; it began on ${day(first)}, so earlier runs are not in it` : ""}.</div>`
      : `<div class="small muted" style="margin-top:6px">No runs in the telemetry history yet: it adds a row for each day this runs.</div>`}</div>`;
}
async function swTelemetry() { return (typeof telData !== "undefined" && telData) || (telData = await api("/api/telemetry").catch(() => ({ rows: [] }))); }
async function swMissionDays(el, slug) {              // a mission's History tab: its days, like an agent's page
  if (!el) return;
  const tel = await swTelemetry();
  if (el.isConnected) el.outerHTML = swDaysHtml((tel.rows || []).filter((r) => r.agent === "mission:" + slug), tel.rows || []);
}
async function swAgentPage(view, id) {
  view.innerHTML = `<a class="back" href="#/swarm?tab=agents">${ic.back}Team</a><div class="page-h"><h1>${esc(swName(id))}</h1></div><div id="swagent"></div>`;
  await swAgentPanel($("#swagent"), id);
}
// what a team agent is (its card), how its last 30 days went (telemetry), with whom it works, its runs, what it said and
// did, and the ideas it worked on; the same panel on its own page and on a housekeeping agent's page (Team tab)
async function swAgentPanel(box, id, crew = false) {    // crew: on its housekeeping page, which shows its issues and memory
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
    : id === "mission" ? `<div class="small muted" style="margin-top:6px">It keeps a journal per mission, read at the start of that mission's runs:</div><div class="list" style="margin-top:4px">${(S?.missions || []).filter((m) => !m.archived && m.status !== "archived").map((m) => `<a href="#/mission/${encodeURIComponent(m.slug)}?tab=memory"><div class="grow"><div class="ttl wrap">${esc(m.title)}</div><div class="sub">its standing notes and journal</div></div>${ic.next}</a>`).join("") || `<div class="small muted">No mission yet.</div>`}</div>`
    : id === "main" ? `<div class="small muted" style="margin-top:6px">Its memory is Hermes' own: its notes about you and the long-term memory of your conversations. Search or forget it on the <a href="#/system">Stack page</a>; a fact it wants to keep waits there for your OK when it is sensitive.</div>`
    : `${explain("it-keeps-no-journal-of-i", `It keeps no journal of its own: each run starts from its card, its standing instructions and the Board. Missions and housekeeping jobs keep journals.`, "About this")}`;
  const edges = (x.it.edges || []).filter((e) => e.from === id || e.to === id);
  const runs = (tl.runs || []).filter((r) => r.lane === id || r.agent === id).sort((p, q) => q.started - p.started);
  const lines = (room.lines || []).filter((l) => swInvolved(l).includes(id)).reverse();
  const ideaIds = [...new Set((g.touches || []).filter((t) => t.agent === id).map((t) => String(t.artifact)))];
  const ideas = ideaIds.map((i) => (g.artifacts || []).find((y) => String(y.id) === i) || { id: i, title: "", state: "" });
  const runRow = (r) => { 
    return `<a href="#/live/${encodeURIComponent(r.run)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(r.name)}</div>
      <div class="sub">${swTime(r.started)} · ${swDur((r.ended || tl.now) - r.started)}${r.by ? ` · started by ${esc(swName(r.by))}` : ""}${r.tokens ? ` · ${tok(r.tokens)} tokens` : ""}</div></div>${swPill(r.state)}</a>`; };
  box.innerHTML = `${a ? `<div class="swteam one">${swTile(a, x, false)}</div>` : `<div class="card pad-l small muted">${esc(swName(id))} has no card in the team (config/agents.yaml): it is a tool or a service the agents use.</div>`}
    ${crew ? "" : `<div class="card pad-l section"><h2>Health <span class="hcount">${issues.length}</span></h2>
      ${issues.length ? issues.map((x) => `<div class="banner ${x.severity === "alert" ? "" : "note"} agissue" style="margin-top:8px">${ic.alert}<span class="grow wrap">${esc(x.text)}${x.run ? ` · <a href="#/live/${encodeURIComponent(x.run)}">the run</a>` : ""}<span class="tiny faint"> · ${x.severity === "alert" ? "alert" : "note"}</span></span>${x.key ? `<button class="btn sm ghost" data-ack="${esc(x.key)}">Acknowledge</button>` : ""}</div>`).join("")
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
    <div class="card pad-l section"><h2>Tasks it did steps for <span class="hcount">${tasks.length}</span></h2>
      ${tasks.length ? `<div class="list" style="margin-top:6px">${tasks.map(({ t, steps }) => `<a href="#/task/${t.id}"><div class="grow" style="min-width:0"><div class="ttl wrap">#${t.id} ${esc(t.title)}</div>
        <div class="sub wrap">${steps.map((s) => `step ${s.idx}${s.occ > 1 ? ` (run ${s.occ})` : ""}: ${esc(s.title)} · ${esc(s.status)}`).join("; ")}</div></div><span class="pill ${t.status === "done" ? "ok" : t.status === "failed" ? "failed" : "running"}">${esc(t.status)}</span></a>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">No task on the board (open or of the last 7 days) gave it a step.</div>`}</div>
    ${crew ? "" : `<div class="card pad-l section"><h2>Memory</h2>${journalHtml}</div>`}
    <div class="card pad-l section"><h2>Ideas it worked on <span class="hcount">${ideas.length}</span></h2>
      ${ideas.length ? `<div class="list" style="margin-top:6px">${ideas.map((i) => `<a href="#/swarm/artifact/${i.id}"><div class="grow"><div class="ttl">#${i.id} ${esc(i.title)}</div><div class="sub">${esc(i.state)}</div></div>${ic.next}</a>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">None in the last 30 days.</div>`}</div>`;
  swBindTiles(x.who);
  $$("[data-ack]", box).forEach((b) => (b.onclick = () => ackIssues(b.dataset.ack.split(" ").filter(Boolean), b)));
}

// ---------- the Chatroom: the team room (SWM-107) ----------
// One timeline of what the agents do together, newest first, drawn from what they do (no agent is asked to post):
// Asks (tool calls between agents, with the answer), Helps (an agent works on another agent's artifact: a step into
// another's lane), Talk (the Board), Work (the shared artifacts), You (your decisions and messages) and Status (runs no one
// asked for, the stack's bookkeeping; off at first). Filters: type, agent (two picked: only what passes between them),
// topic, time and text. A link from Needs you (ctx=) opens on that conversation.
function swFold(text, n = 1200) {                     // a long text folds behind a visible "Show all" (AGENTS.md, Truncation)
  const s = String(text || "");
  if (s.length <= n + 600) return esc(s);                // folding away a few lines is not worth a tap
  return `${esc(s.slice(0, n))}<span hidden>${esc(s.slice(n))}</span> <button type="button" class="tag swmore">Show all (${nf(s.length - n)} more characters)</button>`;   // cap: preview: one tap shows the rest
}
const SW_ROOM_TYPES = [["ask", "Asks"], ["help", "Helps"], ["talk", "Talk"], ["work", "Work"], ["you", "You"], ["status", "Status"]];
const swRoomF = { types: new Set(["ask", "help", "talk", "work", "you"]), agents: new Set(), topic: "", hours: 24, q: "" };
let swRoom = { t: 0, h: 0, d: null }, swRoomShow = 120;
async function swRoomLoad(force) {
  if (force || !swRoom.d || swRoom.h !== swRoomF.hours || Date.now() - swRoom.t > 15000)
    swRoom = { t: Date.now(), h: swRoomF.hours, d: await api(`/api/swarm/room?hours=${swRoomF.hours}`).catch(() => swRoom.d || { lines: [], error: "Mission Control did not answer" }) };
  return swRoom.d;
}
const swInvolved = (l) => [l.actor, ...String(l.target || "").split(", ")].filter((x) => x && !x.startsWith("#"));
const swTopicOf = (l) => swGroupOf(l.type === "help" || l.type === "ask" ? l.target : l.actor === "you" || l.actor === "stack" || l.actor === "checker" ? (l.target || l.actor) : l.actor);
function swRoomMatch(l, skip) {
  const f = swRoomF, inv = swInvolved(l);
  if (skip !== "type" && !f.types.has(l.type)) return false;
  if (swCtx && !(l.ref?.context === swCtx || (swCtx.startsWith("artifact:") && String(l.ref?.artifact) === swCtx.slice(9)))) return false;
  if (skip !== "agent" && f.agents.size === 1 && !inv.some((a) => f.agents.has(a))) return false;
  if (skip !== "agent" && f.agents.size > 1 && inv.filter((a) => f.agents.has(a)).length < 2) return false;   // between the ones picked
  if (skip !== "topic" && f.topic && swTopicOf(l) !== f.topic) return false;
  if (f.q) { const q = f.q.toLowerCase(); if (![l.actor, l.target, l.verb, l.title, l.text, l.detail].join(" ").toLowerCase().includes(q)) return false; }
  return true;
}
let swJudged = {};                                     // help seq -> the latest verdict line on it (SWM-109)
function swRoomLine(l) {
  const g = swGroupOf(l.actor === "you" ? "you" : l.actor), col = SW_GCOL[g] || "var(--faint)", name = l.actor === "you" ? "You" : swName(l.actor);
  const [scol, slabel] = l.state ? SW_STATE[l.state] || [null, l.state] : [null, ""];
  const art = l.ref?.artifact, links = [art ? `<a href="#/swarm/artifact/${art}">#${art}'s timeline</a>` : "", l.ref?.run ? `<a href="#/live/${encodeURIComponent(l.ref.run)}">its log</a>` : "",
    l.ref?.context && !swCtx ? `<a href="#" data-rctx="${esc(l.ref.context)}">this conversation</a>` : ""].filter(Boolean);
  return `<div class="rline t-${l.type}"><span class="rav" style="background:${col}" aria-hidden="true">${esc(name.slice(0, 1).toUpperCase())}</span>
    <div class="grow" style="min-width:0">
      <div class="rhead"><span class="wrap"><b>${esc(name)}</b> ${esc(l.verb)}${l.target ? ` <b>${esc(l.target.split(", ").map((x) => (x.startsWith("#") ? x : swName(x))).join(", "))}</b>` : ""}</span><span class="tiny faint rtime">${clockOf(new Date(l.ts * 1000).toISOString())}</span></div>
      ${l.title ? `<div class="small rtitle wrap">${art ? `<a href="#/swarm/artifact/${art}">${esc(l.title)}</a>` : esc(l.title)}</div>` : ""}
      ${l.text ? `<div class="small rtext">${swFold(l.text, 600)}</div>` : ""}
      ${l.detail ? `<details class="rdet"><summary class="tiny muted">${l.type === "ask" ? `${esc(swName(l.target))}'s answer` : "More"}</summary><div class="small rtext">${swFold(l.detail)}</div></details>` : ""}
      ${l.ref?.help ? (swJudged[l.ref.help] ? `<div class="tiny rjudged">${esc(swJudged[l.ref.help].actor === "you" ? "You" : swName(swJudged[l.ref.help].actor))} ${esc(swJudged[l.ref.help].verb.replace(/^judged /, "judged this "))}</div>`
        : `<div class="row wrap" style="gap:6px;margin-top:6px"><span class="tiny faint">Was it useful to ${esc(swName(l.target))}?</span><button type="button" class="btn sm" data-hv="${l.ref.help}" data-useful="1">Useful</button><button type="button" class="btn sm ghost" data-hv="${l.ref.help}" data-useful="0">Not useful</button></div>`) : ""}
      <div class="tiny faint rmeta">${l.type === "help" ? `<span class="rhelp">helps ${esc(swName(l.target))}</span>` : `<span>${esc(SW_ROOM_TYPES.find(([k]) => k === l.type)?.[1].replace(/s$/, "") || l.type)}</span>`}${slabel ? ` · <span style="color:${scol || "inherit"}">${esc(slabel)}</span>` : ""}${links.length ? " · " + links.join(" · ") : ""}</div>
    </div></div>`;
}
async function swChat(body, poll = false) {
  await swWhoCards();
  const d = await swRoomLoad(!poll), all = d.lines || [];
  const sig = JSON.stringify([all.length, all.at(-1)?.ts, [...swRoomF.types], [...swRoomF.agents], swRoomF.topic, swRoomF.hours, swRoomF.q, swCtx, swRoomShow]);
  if (poll && sig === swLastSig) return;                       // nothing new: keep what the owner is typing
  swLastSig = sig;
  const typed = $("#swtext")?.value || "", qFocus = document.activeElement?.id === "rq";
  swJudged = {};
  for (const l of all) if (l.ref?.judges) swJudged[l.ref.judges] = l;
  const shown = all.filter((l) => swRoomMatch(l)).reverse(), page = shown.slice(0, swRoomShow);   // cap: list: "Show earlier" shows the rest
  const count = (pred) => all.filter(pred).length;
  const agents = {};
  for (const l of all.filter((l) => swRoomMatch(l, "agent"))) for (const a of swInvolved(l)) if (a !== "you") agents[a] = (agents[a] || 0) + 1;
  for (const a of swRoomF.agents) agents[a] = agents[a] || 0;            // a picked agent keeps its chip, also with nothing to show
  const topics = {};
  for (const l of all.filter((l) => swRoomMatch(l, "topic"))) { const t = swTopicOf(l); topics[t] = (topics[t] || 0) + 1; }
  let day = "";
  const groups = [];                                            // a burst of asks between the same two agents: one line that opens
  for (const l of page) {
    const g = groups.at(-1), same = g && l.type === "ask" && g[0].type === "ask" && g[0].actor === l.actor && g[0].target === l.target
      && g.at(-1).ts - l.ts < 900 && dayOf(new Date(l.ts * 1000).toISOString()) === dayOf(new Date(g[0].ts * 1000).toISOString());
    same ? g.push(l) : groups.push([l]);
  }
  const rows = groups.map((g) => {
    const l = g[0], dd = dayOf(new Date(l.ts * 1000).toISOString()), head = dd !== day ? `<div class="fday">${esc((day = dd))}</div>` : "";
    if (g.length < 3) return head + g.map(swRoomLine).join("");
    const col = SW_GCOL[swGroupOf(l.actor)] || "var(--faint)", span = clockOf(new Date(g.at(-1).ts * 1000).toISOString()) + "–" + clockOf(new Date(l.ts * 1000).toISOString());
    return `${head}<details class="rburst"><summary class="rline t-ask"><span class="rav" style="background:${col}" aria-hidden="true">${esc(swName(l.actor).slice(0, 1).toUpperCase())}</span>
      <div class="grow" style="min-width:0"><div class="rhead"><span class="wrap"><b>${esc(swName(l.actor))}</b> asked <b>${esc(swName(l.target))}</b> ${g.length} times</span><span class="tiny faint rtime">${span}</span></div>
      <div class="small rtext">${esc(String(l.text).split("\n")[0])}${g.length > 1 ? " …" : ""}</div><div class="tiny faint rmeta">Asks · tap for each question and its answer</div></div></summary>
      <div class="rburstin">${g.map(swRoomLine).join("")}</div></details>`;
  }).join("");
  const cards = S?.swarm?.cards || [], rooms = ["all", "health", "code", "research", "house", "shopping", "ops"];
  const helps = count((l) => l.type === "help" && swRoomMatch(l, "type"));
  body.innerHTML = `<div class="card pad-l rfilters">
      <div class="tiny muted">What the agents do together, drawn from their work: nobody has to post here. <b>Helps</b> are the rare steps into another agent's lane.</div>
      <div class="chips" style="margin-top:8px">${SW_ROOM_TYPES.map(([k, l]) => `<button type="button" class="tag ${swRoomF.types.has(k) ? "on" : ""}" data-rt="${k}">${l} <span class="faint">${count((x) => x.type === k && swRoomMatch(x, "type"))}</span></button>`).join("")}</div>
      <div class="chips scroll-x" style="margin-top:8px"><button type="button" class="tag ${swRoomF.agents.size ? "" : "on"}" data-ra="">Everyone</button>${Object.entries(agents).sort((a, b) => b[1] - a[1]).map(([a, n]) => `<button type="button" class="tag ${swRoomF.agents.has(a) ? "on" : ""}" data-ra="${esc(a)}"><span class="fdot" style="background:${SW_GCOL[swGroupOf(a)] || "var(--faint)"}"></span>${esc(swName(a))} <span class="faint">${n}</span></button>`).join("")}</div>
      ${swRoomF.agents.size ? `<div class="tiny faint" style="margin-top:4px">${swRoomF.agents.size > 1 ? "Only what passes between" : "Only what involves"} ${[...swRoomF.agents].map((a) => esc(swName(a))).join(" and ")}${[...swRoomF.agents].some(swAgentHref) ? ` · ${[...swRoomF.agents].filter(swAgentHref).map((a) => `<a href="${swAgentHref(a)}">${esc(swName(a))}'s page</a>`).join(" · ")}` : ""}</div>` : ""}
      <div class="chips scroll-x" style="margin-top:8px"><button type="button" class="tag ${swRoomF.topic ? "" : "on"}" data-rtop="">All topics</button>${SW_GROUP.filter(([k]) => topics[k]).map(([k, l]) => `<button type="button" class="tag ${swRoomF.topic === k ? "on" : ""}" data-rtop="${k}">${esc(l)} <span class="faint">${topics[k]}</span></button>`).join("")}</div>
      <div class="row wrap" style="gap:8px;margin-top:10px"><div class="chips">${[[6, "6 h"], [24, "24 h"], [72, "3 days"], [168, "7 days"]].map(([h, l]) => `<button type="button" class="tag ${swRoomF.hours === h ? "on" : ""}" data-rh="${h}">${l}</button>`).join("")}</div>
        <input class="input grow" id="rq" type="search" placeholder="Search what they said" value="${esc(swRoomF.q)}" style="min-width:150px"></div>
      ${swCtx ? `<div class="chips" style="margin-top:8px"><button type="button" class="tag on" data-rctx="">${esc(swCtxName(swCtx))} ×</button></div>` : ""}
    </div>
    ${d.error ? `<div class="banner section">${ic.alert}<span class="small">${esc(d.error)}</span></div>` : ""}
    <details class="card pad-l section" id="rpost" ${swCtx || typed ? "open" : ""}><summary><b>Write to the agents</b> <span class="small muted">they read it at the start of their next run</span></summary>
      <form id="swpost" class="swpost" style="margin-top:8px">
        <select name="to" class="input">${(swCtx.startsWith("room:") || swCtx.startsWith("artifact:") || swCtx.startsWith("dm:") ? [swCtx.startsWith("dm:") ? "agent:" + swCtx.slice(3).split("+").find((x) => !x.startsWith("owner")) : swCtx] : []).concat(rooms.map((r) => "room:" + r), cards.map((c) => "agent:" + c))
          .filter((v, i, a) => a.indexOf(v) === i).map((v) => `<option value="${esc(v)}">${esc(v.startsWith("agent:") ? "to " + v.slice(6) : swCtxName(v))}</option>`).join("")}</select>
        <textarea id="swtext" name="text" class="input" rows="2" placeholder="Write to an agent or a room">${esc(typed)}</textarea>
        <div class="row between wrap" style="gap:8px"><label class="tiny"><input type="checkbox" name="request"> as a request (tracked until answered)</label><button class="btn sm primary">Send</button></div>
      </form></details>
    <div class="card pad-l section rroom">${rows || emptyState("Nothing in this window with these filters.", [swRoomF.hours < 168 ? `<button type="button" class="btn sm" data-rwide="h">Show 7 days</button>` : "",
        swRoomF.types.size < SW_ROOM_TYPES.length ? `<button type="button" class="btn sm ghost" data-rwide="t">Every kind, status too</button>` : "", swRoomF.agents.size || swCtx ? `<button type="button" class="btn sm ghost" data-rwide="a">Everyone</button>` : ""].join(""))}
      ${shown.length > page.length ? `<button type="button" class="btn sm ghost" id="rmore" style="margin-top:10px">Show earlier (${shown.length - page.length} more)</button>` : ""}
      ${!helps && swRoomF.types.has("help") ? `${explain("no-agent-stepped-into-an", `No agent stepped into another's lane in this window. That is by design: an agent works on another's artifact only with something new.`, "About this")}` : ""}</div>`;
  if (swTlBox) $(".rfilters", body)?.after(swTlBox);
  const redraw = () => { swLastSig = ""; swSyncUrl(); swChat(body, true); if (swTlBox) swTimeline(swTlBox); };
  $$("[data-rwide]", body).forEach((b) => (b.onclick = () => { const k = b.dataset.rwide;
    if (k === "h") swRoomF.hours = 168; else if (k === "t") swRoomF.types = new Set(SW_ROOM_TYPES.map(([x]) => x)); else { swRoomF.agents.clear(); swCtx = ""; }
    redraw(); }));
  $$("[data-rt]", body).forEach((b) => (b.onclick = () => { const k = b.dataset.rt; swRoomF.types.has(k) ? swRoomF.types.delete(k) : swRoomF.types.add(k); redraw(); }));
  $$("[data-ra]", body).forEach((b) => (b.onclick = () => { const a = b.dataset.ra; if (!a) swRoomF.agents.clear(); else swRoomF.agents.has(a) ? swRoomF.agents.delete(a) : swRoomF.agents.add(a); redraw(); }));
  $$("[data-rtop]", body).forEach((b) => (b.onclick = () => { swRoomF.topic = b.dataset.rtop; redraw(); }));
  $$("[data-rh]", body).forEach((b) => (b.onclick = () => { swRoomF.hours = +b.dataset.rh; swRoomShow = 120; redraw(); }));
  $$("[data-rctx]", body).forEach((a) => (a.onclick = (e) => { e.preventDefault(); swCtx = a.dataset.rctx; redraw(); }));
  $$(".swmore", body).forEach((b) => (b.onclick = () => { b.previousElementSibling.hidden = false; b.remove(); }));
  $$("[data-hv]", body).forEach((b) => (b.onclick = async () => {        // the owner's verdict on a help counts over the agent's
    const useful = b.dataset.useful === "1", reason = useful ? "" : prompt("What made it not useful? (optional: the agent's scorecard keeps it)", "");
    if (reason === null) return;
    b.disabled = true;
    if (await act({ action: "swarm_help_verdict", seq: +b.dataset.hv, useful, reason }, useful ? "Marked useful: the swarm records it for this agent" : "Marked not useful: the swarm records it for this agent")) { swLastSig = ""; swChat(body); }
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
  house: "your house (Home Assistant)", qmd: "your vault (notes and wiki)", missions: "your missions", claude: "Claude Code tasks", graphify: "the code map",
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
    <div class="row between wrap" style="gap:6px"><b>${href ? `<a href="${href}">${esc(a.id)}</a>` : esc(a.id)}</b><span>${isP ? `<span class="pill archived" style="padding:0 6px">paused</span> ` : ""}${n?.live ? `<span class="pill running" style="padding:0 6px">running</span>` : ""}${href ? `<span class="tiny faint">${ic.next}</span>` : ""}</span></div>
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
    location.hash = "#/swarm?tab=improve";
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
  view.innerHTML = `<a class="back" href="#/swarm?tab=improve">${ic.back || "‹"} Ideas</a>
    <div class="page-h"><h1>#${a.id} ${esc(a.title)}</h1><div class="small muted">${esc(a.kind)} · ${esc(a.state)} · owner ${esc(a.owner)} · priority ${nf(+a.priority, 2)}${a.recurrence ? ` · came back ${a.recurrence}×` : ""}</div></div>
    ${a.check ? `<div class="card pad-l section small">Success check: <b>${esc(swCheck(a.check))}</b>${prog ? `<div class="tiny faint">Checker: ${esc(prog)}</div>` : ""}</div>` : ""}
    <div class="card pad-l section"><h2>Timeline</h2><div class="swtimeline">${items.map((x) => `<div class="swev ${x.msg ? "msg" : ""}"><span class="tiny faint">${swTime(x.ts)}</span>
      <b class="small">${esc(swWho(x.who))}</b> <span class="tag">${esc(x.what === "transition" ? "→ " + (x.p.to || "") : x.what)}</span>
      <div class="small" style="white-space:pre-wrap">${esc(x.what === "evidence" ? x.p.text || "" : x.text)}</div></div>`).join("")}</div></div>
    <div class="card pad-l section"><h2>Evidence</h2><div class="list">${(a.evidence || []).map((e) => `<div style="padding:6px 2px"><div class="grow small">${esc(e.text)}<div class="tiny faint">${esc(e.actor || "")} · ${esc(e.ref || "")} · ${swTime(e.ts)}</div></div></div>`).join("") || `<div class="small muted">none</div>`}</div></div>
    <div class="card pad-l section"><h2>Write about it</h2><form id="swapost"><textarea name="text" class="input" rows="2" placeholder="To everyone working on this idea"></textarea>
      <div class="row" style="justify-content:flex-end;margin-top:6px"><button class="btn sm primary">Send</button></div></form></div>`;
  $("#swapost").onsubmit = async (e) => {
    e.preventDefault();
    const t = e.target.text.value.trim();
    if (t && (await act({ action: "swarm_post", to: [`artifact:${id}`], text: t, artifact_id: id }, "Sent: it shows under this artifact"))) swArtifact(view, id);
  };
}
