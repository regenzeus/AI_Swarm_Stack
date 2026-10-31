// The Agents tab's team views (#/swarm?tab=..., the row under its title is app.js's agentViews): the Chatroom (the team room:
// one timeline of what the agents do together, with filters; the owner posts), the graph of
// who works on what and who talks to whom, the agents with their scorecards, and an artifact's full timeline
// (#/swarm/artifact/<id>). Reads through /api/swarm (Mission Control's read-only door to the Swarm service); the owner's
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
function swTime(ts) { return ts ? new Date(ts * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""; }

async function vSwarm() {                            // render() calls views without arguments; view is app.js's #view
  clearInterval(swTimer);
  if (route.args[0] === "artifact") return swArtifact(view, +route.args[1]);
  swTab = route.q.get("tab") || swTab;
  if (route.q.get("ctx")) { swCtx = route.q.get("ctx"); swLastSig = ""; }      // from Needs you: open that thread
  view.innerHTML = `<div class="hero heading" style="margin-bottom:10px"><h1>Agents</h1><p>Your agents as a team. They talk and propose; only your messages decide.</p></div>
    ${agentViews(swTab)}
    <div id="swbody"><div class="skeleton" style="height:200px"></div></div>`;
  const body = $("#swbody");
  try {
    if (swTab === "graph") return await swGraph(body);
    if (swTab === "agents") return await swAgents(body);
    if (swTab === "timeline") {
      await swTimeline(body);
      swTimer = setInterval(() => (route.name === "swarm" && swTab === "timeline" ? swTimeline(body, true) : clearInterval(swTimer)), 20000);
      return;
    }
    if (swTab === "map") {
      await swMap(body);
      swTimer = setInterval(() => (route.name === "swarm" && swTab === "map" ? swMap(body, true) : clearInterval(swTimer)), 20000);
      return;
    }
    if (swTab === "tasks") return swTasks(body);
    if (swTab === "flow") return swFlow(body);
    if (swTab === "improve") {
      swIdeas(body);
      swTimer = setInterval(() => (route.name === "swarm" && swTab === "improve" ? swIdeas(body, true) : clearInterval(swTimer)), 8000);
      return;
    }
    if (swTab === "now") {
      await swNow(body);
      swTimer = setInterval(() => (route.name === "swarm" && swTab === "now" ? swNow(body) : clearInterval(swTimer)), 5000);
      return;
    }
    await swChat(body);
    swTimer = setInterval(() => route.name === "swarm" && swTab === "chat" ? swChat(body, true) : clearInterval(swTimer), 4000);
  } catch (e) {
    body.innerHTML = `<div class="card pad-l small muted">${esc(e.message)}</div>`;
  }
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
  const live = await api("/api/swarm/now").catch(() => []);
  const sig = JSON.stringify([live.map((r) => [r.run, r.tokens]), (S?.builds || []).map((b) => [b.id, b.status, b.queue_pos]), S?.swarm?.leases]);
  if (sig === body.dataset.sig) return;
  body.dataset.sig = sig;
  const queue = (S?.builds || []).filter((b) => b.queue_pos).sort((a, b) => a.queue_pos - b.queue_pos);
  const waiting = (S?.builds || []).filter((b) => ["planned", "queued", "planning"].includes(b.status));
  const leases = S?.swarm?.leases || [];
  body.innerHTML = `<div class="card pad-l"><h2>Working now <span class="hcount">${live.length}</span></h2>
    ${live.length ? `<div class="list" style="margin-top:6px">${live.map((r) => `<a href="#/live/${encodeURIComponent(r.run)}"><div class="ic run"><span class="spin" style="width:12px;height:12px"></span></div>
      <div class="grow" style="min-width:0"><div class="ttl">${esc(r.agent || "agent")}</div><div class="sub">${swRunOn(r)}</div>
      <div class="tiny faint">since ${swTime(r.started)} · ${tok(r.tokens || 0)} tokens so far · ${r.calls || 0} model calls</div></div>${ic.next}</a>`).join("")}</div>`
      : `<div class="small muted" style="margin-top:6px">No agent is running this minute.</div>`}</div>
    <div class="card pad-l section"><h2>Merge queue</h2><div class="small muted">Approved builds land one at a time, in the order you approved them; each is checked again on today's main when main moved.</div>
      ${queue.length ? `<div class="list" style="margin-top:6px">${queue.map((b) => `<a href="#/build/${b.id}"><div class="ic">${b.queue_pos}</div><div class="grow"><div class="ttl">#${b.id} ${esc(b.title)}</div>
        <div class="sub">${esc(BSTATUS[b.status] || b.status)}${b.approve_on_ci ? " · waits for CI" : ""}${b.note ? ` · ${esc(b.note)}` : ""}</div></div>${ic.next}</a>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">Empty.</div>`}</div>
    <div class="card pad-l section"><h2>Waiting to start</h2>${waiting.length ? `<div class="list" style="margin-top:6px">${waiting.map((b) => `<a href="#/build/${b.id}"><div class="grow"><div class="ttl">#${b.id} ${esc(b.title)}</div>
        <div class="sub">${esc(BSTATUS[b.status] || b.status)}${b.note ? ` · ${esc(b.note)}` : ""}</div></div>${ic.next}</a>`).join("")}</div>` : `<div class="small muted" style="margin-top:6px">Nothing waits.</div>`}</div>
    <div class="card pad-l section"><h2>Files held by builds</h2><div class="small muted">A build holds the files of its task while it works, so parallel builders never change the same file; a lease ends with its build or after 4 hours.</div>
      ${leases.length ? `<div class="list" style="margin-top:6px">${leases.map((l) => `<div style="padding:6px 2px"><div class="grow"><span class="mono small">${esc(l.path)}</span> <span class="tiny faint">${esc(l.repo)} · ${esc(l.holder)}${l.task ? ` · task #${l.task}` : ""} · until ${swTime(l.expires)}</span></div></div>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:6px">No files are held.</div>`}</div>`;
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
  body.innerHTML = `<div class="card pad-l"><h2>Flow per week</h2><div class="small muted">How ideas move from proposal to proved. Lead time is the median days from proposal to proved for the ideas proved that week; work in progress is what was approved or shipped but not yet proved at the week's end.</div>
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
      <div class="tiny faint" style="margin-top:4px">for <b>${esc(p.agent || "?")}</b> · target: ${esc(SW_METRIC[p.target?.score] || p.target?.score || "?")} · by ${esc(a.owner)}</div>
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
      <div class="small muted" style="margin-top:4px">What the agents propose to make the stack and themselves better. A problem seen again raises its rank instead of making a copy; nothing starts without your tap.</div></div>
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
    const r = await act({ action: "proposal_accept", id: +b.dataset.chgo }, "Build queued");
    if (r?.build) location.hash = `#/build/${r.build}`; else b.disabled = false;
  }));
  $$("[data-chno]").forEach((b) => (b.onclick = async () => {
    const why = prompt("Why not? (the Coach learns from your reason)");
    if (why == null) return;
    if (await act({ action: "proposal_dismiss", id: +b.dataset.chno, reason: why }, "Declined")) b.closest(".card").remove();
  }));
}

// the numbers behind the improvement loop, under Flow: replay sets and failure classes (SWM-82, SWM-84), requirements in
// the Ledger (SWM-20)
function swLoopNumbers() {
  const sc = S?.swarm?.scorecards || {}, req = S?.swarm?.requirements || {};
  const agents = Object.entries(sc).filter(([, s]) => s?.replays || s?.failures);
  const pct = (n, of) => (of ? Math.round((100 * n) / of) + "%" : "–");
  return `<div class="card pad-l section"><h2>Replay sets and failures</h2><div class="small muted">Every run is kept with what it read and what came of it (proven, declined, duplicate, failed): that is what experiments replay. Failed, declined and duplicate runs are sorted into the MAST failure classes.</div>
      ${agents.length ? `<div style="overflow-x:auto;margin-top:8px"><table class="swflow"><thead><tr><th>Agent</th><th>Runs</th><th>Proven</th><th>Declined</th><th>Duplicate</th><th>Failed</th><th>Specification</th><th>Between agents</th><th>Verification</th><th>Top failure</th></tr></thead>
      <tbody>${agents.map(([id, s]) => { const r = s.replays || { labels: {} }, f = s.failures || {}, n = r.examples || 0, l = r.labels || {};
        return `<tr><td>${esc(id)}</td><td>${n}${r.history ? ` <span class="tiny faint">(${r.history} from history)</span>` : ""}</td><td>${pct(l.proven || 0, n)}</td><td>${pct(l.declined || 0, n)}</td><td>${pct(l.duplicate || 0, n)}</td><td>${pct(l.failed || 0, n)}</td>
          <td>${f.FC1 || 0}</td><td>${f.FC2 || 0}</td><td>${f.FC3 || 0}</td><td class="tiny">${esc((f.modes || [])[0]?.[0] || "–")}</td></tr>`; }).join("")}</tbody></table></div>`
        : `<div class="small muted" style="margin-top:6px">No runs recorded yet.</div>`}</div>
    <div class="card pad-l section"><h2>Requirements in the Ledger</h2><div class="small muted">requirements/*.yaml is mirrored into the Ledger, so agents can find and work on a requirement: open means partial or violated (an open finding); an agent's idea names the requirements it serves.</div>
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
const swDur = (s) => (s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);
const SW_STATE = { done: ["var(--ok)", "done"], running: ["var(--accent)", "running"], failed: ["var(--err)", "failed"], stalled: ["var(--err)", "stuck"],
  limit: ["var(--warn)", "waited for a usage limit"], stopped: ["var(--faint)", "stopped"] };
const swHoursChips = (cur, key) => `<div class="chips" style="margin:4px 0 8px">${[[6, "6 h"], [24, "24 h"], [72, "3 days"], [168, "7 days"]]
  .map(([h, l]) => `<button type="button" class="tag ${cur === h ? "on" : ""}" data-${key}="${h}">${l}</button>`).join("")}</div>`;

// ---------- the timeline: one row per agent, one bar per run (SWM-103) ----------
let swTlHours = 24, swTlSel = null, swTlData = null;
async function swTimeline(body, poll = false) {
  await swWhoCards();
  const t = await api(`/api/swarm/timeline?hours=${swTlHours}`);
  const sig = JSON.stringify(t.runs.map((r) => [r.run, r.state, r.ended]));
  if (poll && sig === body.dataset.sig) return;
  body.dataset.sig = sig;
  swTlData = t;
  const order = Object.fromEntries(SW_GROUP.map(([k], i) => [k, i]));
  const count = {};
  for (const r of t.runs) count[r.lane] = (count[r.lane] || 0) + 1;
  const lanes = Object.keys(count).sort((a, b) => (order[swGroupOf(a)] - order[swGroupOf(b)]) || count[b] - count[a]);
  const live = t.runs.filter((r) => r.state === "running").length;
  body.innerHTML = `<div class="card pad-l"><h2>When each agent ran <span class="hcount">${t.runs.length}</span></h2>
    <div class="small muted">One row per agent, one bar per run, coloured by how it ended. A run another agent started (a mission's web searches by the scout) sits in its own row; tap a bar to see what started it and what it started. ${live ? `${live} running now.` : ""}</div>
    ${swHoursChips(swTlHours, "tlh")}<div class="swtl"></div>
    <div class="row wrap tiny faint" style="gap:12px;margin-top:6px">${Object.entries(SW_STATE).map(([, [c, l]]) => `<span class="row" style="gap:5px"><span style="width:12px;height:8px;border-radius:2px;background:${c}"></span>${l}</span>`).join("")}</div></div>
    <div id="swtldet"></div>`;
  const sc = $(".swtl"), box = sc.clientWidth || 320, span = t.now - t.since;
  const W = swTlHours > 24 ? Math.round(Math.max(box, (swTlHours / 24) * box * 0.9)) : box;    // a long window scrolls inside its card
  const X = (ts) => Math.max(0, Math.min(W, ((ts - t.since) / span) * W));
  const step = swTlHours <= 6 ? 3600 : swTlHours <= 24 ? 3 * 3600 : swTlHours <= 72 ? 12 * 3600 : 86400;
  const ticks = [];
  for (let s = Math.ceil(t.since / step) * step; s < t.now; s += step) if (X(s) < W - 44) ticks.push(s);
  const fmt = (s) => new Date(s * 1000).toLocaleString("en-GB", step >= 86400 ? { weekday: "short", day: "numeric" } : { hour: "2-digit", minute: "2-digit" });
  const grid = ticks.map((s) => `<line x1="${X(s)}" x2="${X(s)}" y1="0" y2="16" stroke="var(--border)"/>`).join("") + `<line x1="${W - 1}" x2="${W - 1}" y1="0" y2="16" stroke="var(--accent)" stroke-width="2"/>`;
  sc.innerHTML = `<div style="width:${W}px">
    <svg width="${W}" height="20" style="display:block">${ticks.map((s) => `<text x="${X(s) + 2}" y="13" font-size="10.5" fill="var(--muted)">${fmt(s)}</text>`).join("")}<text x="${W - 3}" y="13" font-size="10.5" text-anchor="end" fill="var(--accent)">now</text></svg>
    ${lanes.map((l, i) => `<div class="swlane" style="${i % 2 ? "" : "background:var(--surface-2)"}"><div class="swlname"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${SW_GCOL[swGroupOf(l)]};margin-right:5px"></span>${esc(swName(l))} · ${count[l]}</div>
      <svg width="${W}" height="16" style="display:block">${grid}${t.runs.filter((r) => r.lane === l).map((r) => {
        const x = X(r.started), w = Math.max(3, X(r.ended || t.now) - x), [col] = SW_STATE[r.state] || SW_STATE.done;
        return `<rect class="swbar ${r.state === "running" ? "live" : ""}" data-run="${esc(r.run)}" x="${x.toFixed(1)}" y="2" width="${w.toFixed(1)}" height="12" rx="3" fill="${col}"><title>${esc(r.name)}</title></rect>`;
      }).join("")}</svg></div>`).join("")}</div>`;
  const showRun = (id) => {
    swTlSel = id;
    const r = t.runs.find((x) => x.run === id);
    if (!r) return;
    const kids = t.runs.filter((x) => x.parent === id), par = t.runs.find((x) => x.run === r.parent);
    $$(".swbar").forEach((b) => b.classList.toggle("sel", b.dataset.run === id));
    $$(".swbar").forEach((b) => b.classList.toggle("rel", [r.parent, ...kids.map((k) => k.run)].includes(b.dataset.run)));
    const [col, label] = SW_STATE[r.state] || SW_STATE.done;
    const pairCtx = r.by && r.by !== "you" && r.by !== r.lane ? `calls:${[r.by, r.lane].sort().join("+")}` : "";
    $("#swtldet").innerHTML = `<div class="card pad-l section"><div class="row between wrap" style="gap:6px"><h2 class="wrap">${esc(r.name)}</h2><span class="pill" style="background:${col};color:var(--bg)">${esc(label)}</span></div>
      <div class="small" style="margin-top:4px"><b>${esc(swName(r.lane))}</b>${r.agent !== r.lane ? ` <span class="tiny faint">(${esc(r.agent)})</span>` : ""} · ${swTime(r.started)}${r.ended ? ` to ${swTime(r.ended)}` : ", still running"} · ${swDur((r.ended || t.now) - r.started)}</div>
      <div class="small muted">${r.calls} model call${r.calls === 1 ? "" : "s"}${r.tokens ? ` · ${tok(r.tokens)} tokens` : ""}${r.by ? ` · started by ${r.by === "you" ? "you (a chat)" : par ? `<a href="#" data-tlrun="${esc(par.run)}">${esc(swName(r.by))}</a>` : esc(swName(r.by))}` : ""}</div>
      ${kids.length ? `<div class="small" style="margin-top:6px">It started ${kids.length} run${kids.length > 1 ? "s" : ""} (outlined on the timeline):</div>
        <div class="list" style="margin-top:4px">${kids.map((k) => `<a href="#" data-tlrun="${esc(k.run)}"><div class="grow"><div class="sub wrap">${esc(k.name)}</div><div class="tiny faint">${esc(swName(k.lane))} · ${swTime(k.started)} · ${esc((SW_STATE[k.state] || SW_STATE.done)[1])}</div></div></a>`).join("")}</div>` : ""}
      <div class="row wrap" style="gap:8px;margin-top:8px"><a class="btn sm" href="#/live/${encodeURIComponent(r.run)}">Open its log</a>${pairCtx ? `<a class="btn sm ghost" href="#/swarm?tab=chat&ctx=${encodeURIComponent(pairCtx)}">What they said</a>` : ""}</div></div>`;
    $$("[data-tlrun]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); showRun(a.dataset.tlrun); }));
  };
  $$(".swbar").forEach((b) => (b.onclick = () => showRun(b.dataset.run)));
  $$("[data-tlh]").forEach((b) => (b.onclick = () => { swTlHours = +b.dataset.tlh; body.dataset.sig = ""; swTimeline(body); }));
  if (swTlSel && t.runs.some((r) => r.run === swTlSel)) showRun(swTlSel);
  sc.scrollLeft = sc.scrollWidth;                        // a long window opens at now; the names stay pinned on the left
}

// ---------- the interaction map: who works with whom (SWM-104) ----------
// One row per connection, in words: who did what to whom, how often, when last. (A force-directed bubble graph came
// first; on a phone its unlabelled bubbles and line styles said nothing, the owner's review of 2026-10-30.)
let swMapHours = 168;
const SW_ROLE = { you: "you, in chat and in the app", claude: "Claude Code, a read-only analysis in the sandbox", evals: "replays of agents' past runs (agent-change tests)",
  reviewers: "reviews of a build by the other engine", gmail: "your Gmail, through its connector", phone: "the AI phone",
  hermes: "Hermes, your assistant or a mission's agent" };
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
async function swMap(body, poll = false) {
  await swWhoCards();
  const [it, g] = await Promise.all([api(`/api/swarm/interactions?hours=${swMapHours}`), swApi("graph", { days: Math.max(1, Math.round(swMapHours / 24)) }).catch(() => ({ talk: [] }))]);
  const talk = (g.talk || []).map((x) => ({ from: swWho(x.a) === "you" ? "you" : x.a, to: swWho(x.b) === "you" ? "you" : x.b, kind: "messages", n: x.n, live: 0 }));
  const edges = [...it.edges, ...talk.filter((x) => x.from !== x.to)];
  const sig = JSON.stringify([edges, it.nodes.map((n) => [n.id, n.runs, n.live])]);
  if (poll && sig === body.dataset.sig) return;
  body.dataset.sig = sig;
  const info = Object.fromEntries(it.nodes.map((n) => [n.id, n]));
  const ids = new Set(edges.flatMap((e) => [e.from, e.to]));
  const quiet = it.nodes.filter((n) => !ids.has(n.id));
  const who = (id) => { const n = info[id]; return `<div class="swwho"><div class="row" style="gap:6px"><span class="swdot" style="background:${SW_GCOL[swGroupOf(id)]}"></span><b class="wrap">${esc(swName(id))}</b>
      ${n?.runs ? `<span class="tiny faint">${n.runs} run${n.runs === 1 ? "" : "s"}${n.failed ? ` · <span class="err-t">${n.failed} failed</span>` : ""}</span>` : ""}</div>
      ${swRole(id) ? `<div class="tiny muted wrap">${esc(swRole(id))}</div>` : ""}</div>`; };
  const row = (e) => {
    const [verb, arrow] = swVerb(e);
    const ctx = e.kind === "starts" && e.from !== "you" ? `calls:${[e.from, e.to].sort().join("+")}` : "";
    const inner = `${who(e.from)}<div class="swverb"><span class="swarrow">${arrow}</span><span class="wrap"><b>${esc(verb)}</b> · ${e.n} time${e.n === 1 ? "" : "s"}${e.last ? ` · last ${swAgo(e.last)}` : ""}${e.live ? ` · <b class="ok-t">${e.live} now</b>` : ""}</span></div>${who(e.to)}`;
    return ctx ? `<a class="swconn" href="#/swarm?tab=chat&ctx=${encodeURIComponent(ctx)}" title="What they said">${inner}</a>` : `<div class="swconn">${inner}</div>`;
  };
  body.innerHTML = `<div class="card pad-l"><h2>Who works with whom <span class="hcount">${edges.length}</span></h2>
    <div class="small muted">Each row is one connection: who did what to whom, how often, and when last. "Asked to research" means one agent's run started another's through a tool; "wrote on the Board" is a message between them. Tap a row to read what they said.</div>
    ${swHoursChips(swMapHours, "mh")}
    ${edges.length ? `<div class="swconns">${edges.map(row).join("")}</div>` : `<div class="small muted" style="margin-top:8px">No agent started or wrote to another in this window.</div>`}</div>
    ${quiet.length ? `<div class="card pad-l section"><h2>Worked alone <span class="hcount">${quiet.length}</span></h2>
      <div class="small muted">Ran in this window without starting or messaging another agent.</div>
      <div class="swalone">${quiet.map((n) => who(n.id)).join("")}</div></div>` : ""}`;
  $$("[data-mh]").forEach((b) => (b.onclick = () => { swMapHours = +b.dataset.mh; body.dataset.sig = ""; swMap(body); }));
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
  return `${esc(s.slice(0, n))}<span hidden>${esc(s.slice(n))}</span> <button type="button" class="tag swmore">Show all (${(s.length - n).toLocaleString("en-GB")} more characters)</button>`;   // cap: preview: one tap shows the rest
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
      ${swRoomF.agents.size > 1 ? `<div class="tiny faint" style="margin-top:4px">Only what passes between ${[...swRoomF.agents].map((a) => esc(swName(a))).join(" and ")}.</div>` : ""}
      <div class="chips scroll-x" style="margin-top:8px"><button type="button" class="tag ${swRoomF.topic ? "" : "on"}" data-rtop="">All topics</button>${SW_GROUP.filter(([k]) => topics[k]).map(([k, l]) => `<button type="button" class="tag ${swRoomF.topic === k ? "on" : ""}" data-rtop="${k}">${esc(l)} <span class="faint">${topics[k]}</span></button>`).join("")}</div>
      <div class="row wrap" style="gap:8px;margin-top:10px"><div class="chips">${[[24, "24 h"], [72, "3 days"], [168, "7 days"]].map(([h, l]) => `<button type="button" class="tag ${swRoomF.hours === h ? "on" : ""}" data-rh="${h}">${l}</button>`).join("")}</div>
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
    <div class="card pad-l section rroom">${rows || `<div class="small muted">Nothing in this window with these filters.</div>`}
      ${shown.length > page.length ? `<button type="button" class="btn sm ghost" id="rmore" style="margin-top:10px">Show earlier (${shown.length - page.length} more)</button>` : ""}
      ${!helps && swRoomF.types.has("help") ? `<div class="tiny faint" style="margin-top:10px">No agent stepped into another's lane in this window. That is by design: an agent works on another's artifact only with something new.</div>` : ""}</div>`;
  const redraw = () => { swLastSig = ""; swChat(body, true); };
  $$("[data-rt]", body).forEach((b) => (b.onclick = () => { const k = b.dataset.rt; swRoomF.types.has(k) ? swRoomF.types.delete(k) : swRoomF.types.add(k); redraw(); }));
  $$("[data-ra]", body).forEach((b) => (b.onclick = () => { const a = b.dataset.ra; if (!a) swRoomF.agents.clear(); else swRoomF.agents.has(a) ? swRoomF.agents.delete(a) : swRoomF.agents.add(a); redraw(); }));
  $$("[data-rtop]", body).forEach((b) => (b.onclick = () => { swRoomF.topic = b.dataset.rtop; redraw(); }));
  $$("[data-rh]", body).forEach((b) => (b.onclick = () => { swRoomF.hours = +b.dataset.rh; swRoomShow = 120; swLastSig = ""; swChat(body); }));
  $$("[data-rctx]", body).forEach((a) => (a.onclick = (e) => { e.preventDefault(); swCtx = a.dataset.rctx; redraw(); }));
  $$(".swmore", body).forEach((b) => (b.onclick = () => { b.previousElementSibling.hidden = false; b.remove(); }));
  $$("[data-hv]", body).forEach((b) => (b.onclick = async () => {        // the owner's verdict on a help counts over the agent's
    const useful = b.dataset.useful === "1", reason = useful ? "" : prompt("What made it not useful? (optional: the agent's scorecard keeps it)", "");
    if (reason === null) return;
    b.disabled = true;
    if (await act({ action: "swarm_help_verdict", seq: +b.dataset.hv, useful, reason }, useful ? "Marked useful" : "Marked not useful")) { swLastSig = ""; swChat(body); }
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
    const r = await act({ action: "swarm_post", to: [f.to.value], text, request: f.request.checked });
    if (r) { f.text.value = ""; swLastSig = ""; swChat(body); }
  };
}

// ---------- who works on what, who talks to whom ----------
// Every dot is named: an agent by its name, an idea by its number and first words (its whole title one tap away). Moving
// and zooming as in every chart (app.js chartZoom, placeLabels).
const swIdeaLabel = (x) => { const w = String(x.title || "").split(/\s+/).filter(Boolean); return `#${x.id} ${w.slice(0, 4).join(" ")}${w.length > 4 ? " …" : ""}`; };   // cap: preview: the dot's name; its card and the list name it whole
let swGraphClosed = false;                             // closed ideas (declined, merged, gone) are hidden until asked for
async function swGraph(body) {
  const g = await swApi("graph", { days: 30 });
  const closedState = (s) => ["declined", "merged", "gone"].includes(s);
  const nClosed = (g.artifacts || []).filter((x) => closedState(x.state)).length;
  const shared = Object.entries(g.shared || {});
  body.innerHTML = `<div class="card pad-l"><div class="small muted">The last 30 days. A line joins an agent and an idea it wrote to; a dashed line joins two
      agents that messaged each other. Agents are the big dots, ideas the small ones (#number and their first words).</div>
    <div id="swsvg" style="height:460px;margin-top:8px"></div><div class="tiny faint" style="margin-top:4px">${CHART_HINT} for what it is</div>
    ${nClosed ? `<div class="chips" style="margin-top:6px"><button type="button" class="tag ${swGraphClosed ? "on" : ""}" id="swgclosed">Closed ideas · ${nClosed}</button></div>` : ""}
    <div id="swginfo" class="small" style="margin-top:6px"></div><div id="swlegend" class="row wrap tiny faint" style="gap:12px;margin-top:6px"></div></div>
    <div class="card pad-l section"><h2>Ideas two or more work on</h2>${shared.length ? `<div class="list">${shared.map(([aid, who]) => {
      const a = (g.artifacts || []).find((x) => String(x.id) === aid) || {};
      return `<a href="#/swarm/artifact/${aid}"><div class="grow"><div class="ttl">#${aid} ${esc(a.title || "")}</div><div class="sub">${who.map(esc).join(", ")} · ${esc(a.state || "")}</div></div>${ic.next}</a>`;
    }).join("")}</div>` : `<div class="small muted" style="margin-top:6px">None yet: so far each idea has one worker.</div>`}</div>`;
  const el = $("#swsvg"), W = el.clientWidth || 360, H = Math.max(320, Math.min(460, Math.round(window.innerHeight * 0.6)));
  el.style.height = H + "px";
  const kindOf = (a) => (a === "owner" ? "owner" : a === "checker" ? "checker" : "agent");
  const deg = {};
  for (const t of g.touches || []) { deg["a:" + t.agent] = (deg["a:" + t.agent] || 0) + 1; deg["x:" + t.artifact] = (deg["x:" + t.artifact] || 0) + 1; }
  const nodes = [...g.agents.map((a) => ({ id: "a:" + a, label: a === "owner" ? "you" : a, kind: kindOf(a) })),
    ...(g.artifacts || []).filter((x) => swGraphClosed || !closedState(x.state)).map((x) => ({ id: "x:" + x.id, label: swIdeaLabel(x), title: x.title, aid: x.id, kind: "idea", state: x.state }))];
  const ids = new Set(nodes.map((n) => n.id));
  const links = [...(g.touches || []).map((t) => ({ source: "a:" + t.agent, target: "x:" + t.artifact, n: t.n, kind: "touch" })),
    ...(g.talk || []).map((t) => ({ source: "a:" + swWho(t.a), target: "a:" + swWho(t.b), n: t.n, kind: "talk" }))].filter((l) => ids.has(l.source) && ids.has(l.target) && l.source !== l.target);
  const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance((l) => (l.kind === "talk" ? 140 : 70)).strength(0.5))
    .force("charge", d3.forceManyBody().strength((d) => (d.kind === "idea" ? -160 : -600))).force("x", d3.forceX(0).strength(0.05)).force("y", d3.forceY(0).strength(0.07))
    .force("collide", d3.forceCollide((d) => (d.kind === "idea" ? 26 : 40))).stop();                // room for the names
  for (let i = 0; i < 400; i++) sim.tick();                       // lay it out once: nothing drifts under a finger
  const svg = d3.select(el).append("svg").attr("width", W).attr("height", H);
  const root = svg.append("g");
  root.append("g").selectAll("line").data(links).join("line").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y)
    .attr("vector-effect", "non-scaling-stroke").attr("stroke", (l) => (l.kind === "talk" ? "var(--accent-2)" : "var(--border-2)")).attr("stroke-dasharray", (l) => (l.kind === "talk" ? "5 4" : null))
    .attr("stroke-width", (l) => Math.min(4, 1 + Math.log2(l.n || 1)) * (l.kind === "talk" ? 1.2 : 0.8));
  const fill = (d) => (d.kind === "owner" ? "var(--ok)" : d.kind === "checker" ? "var(--accent-2)" : d.kind === "agent" ? "var(--accent)"
    : d.state === "done" ? "var(--ok)" : ["declined", "merged", "gone"].includes(d.state) ? "var(--faint)" : "var(--warn)");
  const rs = (d) => (d.kind === "idea" ? 6 : 12);                   // dots keep their size on screen at any zoom, like pins on a map
  const node = root.append("g").selectAll("g").data(nodes).join("g").attr("transform", (d) => `translate(${d.x},${d.y})`).style("cursor", "pointer");
  const dot = node.append("circle").attr("fill", fill).attr("stroke", "var(--surface)").attr("vector-effect", "non-scaling-stroke").attr("stroke-width", 1.5);
  const text = root.append("g").selectAll("text").data(nodes).join("text").attr("transform", (d) => `translate(${d.x},${d.y})`)   // names above every dot
    .text((d) => d.label).attr("class", (d) => "swlbl" + (d.kind === "idea" ? " idea" : ""));
  const items = nodes.map((d, i) => ({ x: d.x, y: d.y, rs: rs(d), text: d.label, el: text.nodes()[i], prio: (d.kind === "idea" ? 0 : 1000) + (deg[d.id] || 0) }));
  const info = $("#swginfo");
  node.on("click", (_, d) => {
    const who = links.filter((l) => l.source.id === d.id || l.target.id === d.id).map((l) => (l.source.id === d.id ? l.target : l.source));
    info.innerHTML = d.kind === "idea"
      ? `<div class="wmapcard"><div class="row between wrap" style="gap:8px"><b class="wrap">#${d.aid} ${esc(d.title || "")}</b><a class="btn sm" href="#/swarm/artifact/${d.aid}">Open</a></div>
          <div class="tiny faint" style="margin-top:2px">${esc(d.state || "")} · worked on by ${who.map((n) => esc(n.label)).join(", ") || "nobody in this window"}</div></div>`
      : `<div class="wmapcard"><b>${esc(swName(d.label === "you" ? "you" : d.label))}</b>${swRole(d.label === "you" ? "you" : d.label) ? ` <span class="tiny muted">${esc(swRole(d.label === "you" ? "you" : d.label))}</span>` : ""}
          <div class="tiny faint" style="margin-top:2px">${who.filter((n) => n.kind === "idea").length} idea${who.filter((n) => n.kind === "idea").length === 1 ? "" : "s"} in this window${who.some((n) => n.kind !== "idea") ? ` · messaged ${who.filter((n) => n.kind !== "idea").map((n) => esc(n.label)).join(", ")}` : ""}</div></div>`;
  });
  const fit = (animate) => (animate ? svg.transition().duration(250) : svg).call(zoom.transform, chartFit(nodes, W, H, 30, 1.6, 60, 0.6));
  const zoom = chartZoom(el, svg, root, { onZoom: (t) => { dot.attr("r", (d) => rs(d) / t.k); placeLabels(items, t.k); }, fit });
  fit(false);
  info.innerHTML = `<span class="muted">${nodes.filter((n) => n.kind === "idea").length} ideas and ${nodes.filter((n) => n.kind !== "idea").length} agents. Tap a dot.</span>`;
  const cl = $("#swgclosed");
  if (cl) cl.onclick = () => { swGraphClosed = !swGraphClosed; swGraph(body); };
  $("#swlegend").innerHTML = [["var(--accent)", "agent"], ["var(--accent-2)", "the Checker"], ["var(--ok)", "you · proved idea"], ["var(--warn)", "open idea"], ["var(--faint)", "closed"]]
    .map(([c, l]) => `<span class="row" style="gap:5px"><span style="width:9px;height:9px;border-radius:50%;background:${c}"></span>${l}</span>`).join("");
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
async function swAgents(body) {
  const who = await swWhoCards(), paused = S?.swarm?.paused || [];
  const [tokens, it] = await Promise.all([api("/api/swarm/tokens").catch(() => ({})), api("/api/swarm/interactions?hours=168").catch(() => ({ nodes: [], edges: [] }))]);
  const act = Object.fromEntries((it.nodes || []).map((n) => [n.id, n]));
  const sc = Object.fromEntries(Object.entries(S?.swarm?.scorecards || {}).map(([k, v]) => [k, { ...v, tokens_30d: tokens[k] || 0 }]));
  const pct = (v) => (v == null ? "–" : Math.round(v * 100) + "%");
  const tile = (a) => {
    const s = sc[a.id], n = act[a.id], isP = paused.includes(a.id) || paused.includes("*"), tools = a.tools || [];
    const has = (xs) => tools.some((t) => xs.includes(t));
    const three = [has(SW_PRIVATE) && "reads your private data", has(SW_UNTRUSTED) && "takes in outside content", has(SW_OUT) && "can send data out"].filter(Boolean);
    const starts = (it.edges || []).filter((e) => e.from === a.id), startedBy = (it.edges || []).filter((e) => e.to === a.id);
    return `<div class="swtile" style="border-top:3px solid ${SW_GCOL[swGroupOf(a.id)]}">
      <div class="row between wrap" style="gap:6px"><b>${esc(a.id)}</b><span>${isP ? `<span class="pill archived" style="padding:0 6px">paused</span> ` : ""}${n?.live ? `<span class="pill running" style="padding:0 6px">running</span>` : ""}</span></div>
      <div class="small" style="margin-top:4px">${esc(a.purpose || "")}</div>
      <div class="tiny faint" style="margin-top:4px">${esc(swHarness(a))} · ${esc(a.model)} · ${esc(a.schedule || "")} · ${esc(SW_WAKE[a.wake] || a.wake || "")}</div>
      <div class="tiny" style="margin-top:6px">${tools.length ? `Can reach: ${tools.map((t) => `<span class="tag" style="padding:1px 7px">${esc(SW_REACH[t] || t)}</span>`).join(" ")}` : "No tools of its own."}</div>
      ${three.length ? `<div class="tiny" style="margin-top:4px;color:${three.length === 3 ? "var(--warn)" : "var(--muted)"}">${three.map(esc).join(" · ")}${three.length === 3 ? " (all three together: what leaves through the AI phone waits for your tap)" : ""}</div>` : ""}
      <div class="tiny" style="margin-top:6px">${n ? `Last 7 days: ${n.runs} run${n.runs === 1 ? "" : "s"}${n.failed ? `, <span style="color:var(--err)">${n.failed} failed</span>` : ""}, last ${swAgo(n.last)}` : "No runs in the last 7 days."}
        ${starts.length ? ` · starts ${starts.map((e) => `${esc(swName(e.to))} ${e.n}×`).join(", ")}` : ""}${startedBy.length ? ` · started by ${startedBy.map((e) => `${esc(swName(e.from))} ${e.n}×`).join(", ")}` : ""}</div>
      ${s?.ideas ? `<div class="tiny" style="margin-top:4px">${s.ideas} ideas · accepted ${pct(s.accepted_share)} · proved ${pct(s.proven_share)} · came back ${pct(s.reopen_rate)}${s.tokens_30d ? ` · ${tok(s.tokens_30d)} tokens in 30 d` : ""}</div>` : ""}
      ${s?.requests ? `<div class="tiny">${s.requests.received} request${s.requests.received === 1 ? "" : "s"} in 30 d: ${s.requests.answered} answered, ${s.requests.declined} declined, ${s.requests.expired} expired</div>` : ""}
      ${s?.failures ? `<div class="tiny">failures (MAST): ${s.failures.FC1} specification, ${s.failures.FC2} between agents, ${s.failures.FC3} verification</div>` : ""}
      <div class="row wrap" style="gap:8px;margin-top:8px"><a class="btn sm ghost" href="#/swarm?tab=timeline">Timeline</a>
        <button class="btn sm ghost" data-swpause="${esc(a.id)}" data-on="${isP ? "0" : "1"}">${isP ? "Resume" : "Pause"}</button></div>
      <details class="tiny" style="margin-top:6px" data-a2a="${esc(a.id)}"><summary>A2A agent card (SWM-27)</summary><pre class="log" style="max-height:240px">loading…</pre></details></div>`;
  };
  const groups = SW_GROUP.map(([k, l]) => [k, l, who.filter((a) => swGroupOf(a.id) === k)]).filter(([, , xs]) => xs.length);
  body.innerHTML = `<div class="card pad-l"><h2>The team <span class="hcount">${who.length}</span></h2><div class="small muted">Every agent by its job: what it is for, how it runs, what it can reach, and how its last week went. Three things together make an agent risky: your private data, outside content and a way to send data out.</div></div>
    ${groups.map(([k, l, xs]) => `<div class="section"><div class="section-h"><h2><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${SW_GCOL[k]};margin-right:6px"></span>${esc(l)} <span class="hcount">${xs.length}</span></h2></div>
      <div class="swteam">${xs.map(tile).join("")}</div></div>`).join("")}`;
  bindSwarmPause();
  $$("[data-a2a]").forEach((d) => (d.ontoggle = async () => {           // the card other agents would read, on the Docker network only
    if (!d.open || d.dataset.loaded) return;
    d.dataset.loaded = 1;
    d.querySelector("pre").textContent = JSON.stringify(await swApi("agent_card", { agent: d.dataset.a2a }).catch((e) => ({ error: e.message })), null, 1);
  }));
}

// ---------- an artifact's timeline ----------
async function swArtifact(view, id) {
  view.innerHTML = `<div class="skeleton" style="height:200px"></div>`;
  let h;
  try { h = await swApi("history", { id }); } catch (e) { view.innerHTML = `<div class="card pad-l small muted">${esc(e.message)}</div>`; return; }
  const a = h.artifact, prog = (S?.swarm?.checks || {})[String(id)];
  const items = [...h.events.filter((e) => e.kind !== "message").map((e) => ({ ts: e.ts, who: e.actor, what: e.kind, text: e.reason || "", p: JSON.parse(e.payload || "{}") })),
    ...h.thread.map((m) => ({ ts: m.ts, who: m.sender, what: m.act, text: m.text, msg: true }))].sort((x, y) => x.ts - y.ts);
  view.innerHTML = `<a class="back" href="#/swarm?tab=graph">${ic.back || "‹"} Swarm</a>
    <div class="page-h"><h1>#${a.id} ${esc(a.title)}</h1><div class="small muted">${esc(a.kind)} · ${esc(a.state)} · owner ${esc(a.owner)} · priority ${(+a.priority).toFixed(2)}${a.recurrence ? ` · came back ${a.recurrence}×` : ""}</div></div>
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
    if (t && (await act({ action: "swarm_post", to: [`artifact:${id}`], text: t, artifact_id: id }, "Sent"))) swArtifact(view, id);
  };
}
