// The app, part of index.html's scripts (PLT-25): n8n inside the app (WFL-11, WFL-14). The app serves n8n's editor under
// /n8n/, behind its own gate (server.n8n.py), so it shows inside the app's pages:
// - #/workflows: on the desk n8n's own editor in a frame beside the app's menu (?open=<workflow id> opens one workflow,
//   ?open=executions every run); on a phone the workflows as a plain list from the runner's view: whether n8n runs
//   each, its schedule, its last run with its steps.
// - a task's or crew job's "Where it runs" (wfWhereInto): its workflow, the run, its state and the step it is on; on the
//   desk the run's canvas in a frame, on a phone its steps as a list.
// - an agent's "In workflows" (wfInInto): every workflow it appears in.
// The view is the runner's public/workflows-runs.json (ops/flows_view.py) through GET /api/workflows.
let WFV = null, wfvAt = 0;
const wfDesk = () => matchMedia("(min-width: 960px)").matches;            // the desk has the side menu and room for n8n's canvas
if (typeof matchMedia === "function") matchMedia("(min-width: 960px)").addEventListener("change", () => {   // a window made wider or narrower: the frame or the list
  if (route.name === "workflows") vWorkflows(); else if ($(".wf-where")) render(true);
});
const n8nPath = (id, ex) => (id === "executions" ? "/n8n/home/executions" : id ? `/n8n/workflow/${encodeURIComponent(id)}${ex ? `/executions/${encodeURIComponent(ex)}` : ""}` : "/n8n/home/workflows");
const WF_STATE = { running: ["running", "running"], waiting: ["paused", "waits for you"], done: ["ok", "done"], failed: ["failed", "failed"],
  refused: ["failed", "refused"], cancelled: ["archived", "cancelled"] };
const wfStatePill = (s) => (([c, l]) => `<span class="pill ${c}">${s === "running" ? '<span class="dot run"></span>' : ""}${esc(l)}</span>`)(WF_STATE[s] || ["", s]);
const wfOnPill = (w) => (!w ? "" : w.active ? `<span class="pill ok">on n8n</span>` : w.for ? `<span class="pill paused">its old schedule runs it</span>` : `<span class="pill archived">off</span>`);
async function wfView(fresh = false) {                 // the runner rewrites it every few seconds; one fetch serves a page's parts
  if (!fresh && WFV && Date.now() - wfvAt < 15000) return WFV;
  WFV = await api("/api/workflows").catch(() => WFV || { workflows: [] });
  wfvAt = Date.now();
  return WFV;
}
const wfOf = (v, id) => (v?.workflows || []).find((w) => w.id === id);
function wfPageOf(w) {                                 // the app's own page of what the workflow runs
  const [k, key] = String(w.for || "").split(":");
  return k === "crew" ? [`#/crew/${encodeURIComponent(key)}`, "Its crew job"] : k === "task" ? [`#/task/${encodeURIComponent(key)}`, `Task #${key}`] : null;
}
function wfWho(s) {                                    // who does a step, linked to their page in the app
  if (s.kind === "crew" && s.job) return `<a href="#/crew/${encodeURIComponent(s.job)}">${esc((S?.crew || []).find((c) => c.id === s.job)?.name || s.job)}</a>`;
  if (s.kind === "task" && s.task) return `<a href="#/task/${encodeURIComponent(s.task)}">task #${esc(s.task)}</a>`;
  if (s.kind === "agent" && s.agent) { const h = typeof swAgentHref === "function" ? swAgentHref(s.agent) : ""; return h ? `<a href="${h}">${esc(s.agent)}</a>` : esc(s.agent); }
  return { ask: "a question for you", notify: "a message to you" }[s.kind] || esc(s.kind || "");
}
function wfStepsHtml(w, r) {                           // the workflow's AI Stack steps in order, each with its state in this run
  const got = new Map((r?.steps || []).map((s) => [s.title, s]));
  const rows = (w?.steps || []).map((s) => ({ ...s, run: got.get(s.title) }));
  for (const s of r?.steps || []) if (!rows.some((x) => x.title === s.title)) rows.push({ ...s, run: s });   // a step renamed since
  if (!rows.length) return `<div class="small muted">It has no AI Stack step: n8n's own nodes do its work.</div>`;
  const open = r && ["running", "waiting"].includes(r.state);
  return `<ol class="wf-steps">${rows.map((s) => { const x = s.run;
    return `<li class="${x ? `st-${esc(x.state)}` : ""}"><div class="row between wrap" style="gap:4px 8px"><b class="wrap">${esc(s.title)}</b>${x ? wfStatePill(x.state) : `<span class="tiny faint">${open ? "not yet" : r ? "not run" : ""}</span>`}</div>
      <div class="tiny muted wrap">${wfWho(s)}${x?.started ? ` · ${clock(x.started)}${x.ended ? `–${clock(x.ended)}` : ""}` : ""}</div></li>`; }).join("")}</ol>`;
}
function wfRunLine(r) {
  return `${wfStatePill(r.state)} <span>run ${esc(r.execution)} · started ${esc(dt(r.started))}${r.ended ? ` · ended ${esc(clock(r.ended))}` : ` · at “${esc(r.on)}”`}</span>`;
}

// ---------- a tool's page: its own UI in a frame on the app's address, beside the app's menu (server.frames.py) ----------
// One component for every tool inside the app: the title row (its name, its views as one segmented control, what it is
// behind the (i), "On its own"), then the frame filling the rest of the window. A tool keeps its own state: the page is
// never redrawn under you while the same view is open.
function toolPage(title, src, segs, about) {
  if (view.querySelector("iframe.tool-frame")?.dataset.src === src) return;
  view.innerHTML = `<div class="tool-head"><h1>${esc(title)}</h1>
    ${segs.length ? `<div class="seg sm">${segs.map(([href, label, on]) => `<a href="${href}" class="${on ? "on" : ""}">${esc(label)}</a>`).join("")}</div>` : ""}
    ${about}<a class="btn sm ghost" href="${esc(src)}" target="_blank" rel="noopener">${ic.next}On its own</a></div>
  <iframe class="tool-frame" data-src="${esc(src)}" src="${esc(src)}" title="${esc(title)}"></iframe>`;
}

// ---------- the Workflows page ----------
function vWorkflows() {
  const open = route.q.get("open") || "";
  if (!wfDesk()) return wfList(open);
  toolPage("Workflows", n8nPath(open), [["#/workflows", "Workflows", open !== "executions"], ["#/workflows?open=executions", "Runs", open === "executions"]],
    explain("wf-what", `n8n decides when each piece of work starts and in what order; the stack's agents do the work. This is n8n's own editor, inside the app: sign in to it once with its own account. Its AI Stack steps hand work to the stack and wait for the answer. ${how("workflows")}`, "About n8n"));
}

// ---------- the Traces page (APP-66): Phoenix inside the app, every model call with its prompt and answer ----------
// #/traces?open=<a Phoenix path> opens that view (a step log's "Open in Phoenix" goes through /api/phoenix, which finds
// the call's trace). On a phone too: Phoenix's lists work at 375 px, its trace view scrolls inside the frame.
function vTraces() {
  const open = route.q.get("open") || "";
  const path = /^\/[\w\-/.=?&%]*$/.test(open) ? open : "/projects";          // only a path inside Phoenix
  toolPage("Traces", `/phoenix${path}`, [],
    explain("traces-what", `Phoenix keeps every model call the stack made through its gateway: the whole prompt, the answer, the tokens and the time, grouped into traces (a task's run is one trace). Open in Phoenix on a step's log jumps to that call. ${how("telemetry")}`, "About traces"));
}

async function wfList(open) {
  if (!WFV) view.innerHTML = `<h1>Workflows</h1><div class="stack"><div class="skeleton" style="height:96px"></div><div class="skeleton" style="height:96px"></div></div>`;
  const v = await wfView();
  if (route.name !== "workflows" || wfDesk()) return;
  const last = (w) => w.runs?.[0]?.started || "";
  const ws = [...(v.workflows || [])].sort((a, b) => (b.active - a.active) || last(b).localeCompare(last(a)) || a.name.localeCompare(b.name));
  const on = ws.filter((w) => w.active).length;
  view.innerHTML = `<div class="hero"><div class="grow"><h1>Workflows</h1><p>${nf(on)} of ${nf(ws.length)} on n8n</p></div>${explain("wf-phone", `n8n decides when each piece of work starts; the stack's agents do it. Each workflow shows its schedule and its last runs, with the steps the stack ran. Its canvas opens on the desk. ${how("workflows")}`, "About workflows")}</div>
    ${ws.length ? `<div class="stack wf-list">${ws.map((w) => wfCard(w, w.id === open)).join("")}</div>` : emptyState("Workflows come from the repository's n8n folder: each deploy brings them in.", `<a class="btn sm" href="#/guide/workflows">${ic.doc}How workflows come in</a>`)}`;
  if (open) $(`[data-wf="${CSS.escape(open)}"]`)?.scrollIntoView({ block: "start" });
}
function wfCard(w, isOpen) {
  const r = w.runs?.[0], page = wfPageOf(w), more = (w.runs_total || 0) - (w.runs || []).length;
  return `<details class="card wf-card" data-wf="${esc(w.id)}"${isOpen ? " open" : ""}><summary>
    <div class="row between wrap" style="gap:4px 8px"><b class="wrap">${esc(w.name)}</b>${wfOnPill(w)}</div>
    <div class="small muted wrap" style="margin-top:4px">${ic.clock}${esc(w.schedule)} · ${r ? `last run ${wfStatePill(r.state)} ${esc(when(r.started))}` : "no run yet"}</div></summary>
    <div class="wf-body">${(w.runs || []).map((x, i) => `<div class="wf-run"><div class="small row wrap" style="gap:4px 8px">${wfRunLine(x)}</div>${i === 0 ? wfStepsHtml(w, x) : ""}</div>`).join("")
      || `<div class="small muted">No run has reached the stack yet. Its steps:</div>${wfStepsHtml(w, null)}`}
      ${more > 0 ? `<div class="tiny faint">${nf(more)} older run${more > 1 ? "s" : ""} in n8n's list of runs, on the desk.</div>` : ""}
      ${page ? `<a class="btn sm" href="${page[0]}" style="margin-top:8px">${ic.next}${esc(page[1])}</a>` : ""}</div></details>`;
}

// ---------- Where it runs (a task's page, a crew job's page) and In workflows (an agent's page) ----------
function wfWhereOf(t) {                                // a task the step service made names its workflow and run; a plan task moved to n8n is in the catalogue
  const m = t.door === "workflow" ? /^n8n:([^/]+)\/(.*)$/.exec(t.ref || "") : null;
  if (m) return { wid: m[1], ex: m[2] };
  const j = S?.workflows?.jobs?.[`task:${t.id}`];
  return j ? { wid: j.id, ex: "" } : null;
}
// n8n's run view keeps its own state: a redraw of the page moves the frame instead of loading it again (where the
// browser can move a frame without reloading it)
function wfKeepFrame() {
  const f = $(".wf-where iframe.tool-frame");
  if (!f || !document.body.moveBefore) return null;
  f.hidden = true;
  document.body.moveBefore(f, null);
  return f;
}
async function wfWhereInto(el, wid, ex = "", inList = null, keep = null) {
  if (!el) { keep?.remove(); return; }
  const v = await wfView();
  if (!el.isConnected) { keep?.remove(); return; }
  const w = wfOf(v, wid), r = ex ? (w?.runs || []).find((x) => x.execution === ex) : w?.runs?.[0], run = ex || r?.execution || "";
  const src = n8nPath(wid, run), list = inList || (w ? [w] : []);
  const names = list.length ? list.map((x) => `<a class="tag" href="#/workflows?open=${encodeURIComponent(x.id)}">${ic.flow}${esc(x.name)}</a>`).join("")
    : `<a class="tag" href="#/workflows?open=${encodeURIComponent(wid)}">${ic.flow}${esc(wid)}</a>`;
  el.innerHTML = `<div class="card pad wf-where"><div class="row between wrap" style="gap:6px"><h2>Where it runs</h2>${explain("wf-where", `n8n starts it and the stack does the work. ${wfDesk() ? "Below is the run on n8n's canvas: each node's state, its input and its output." : "On the desk the run opens on n8n's canvas."} ${how("workflows")}`, "About where it runs")}</div>
    <div class="chips wf-in" style="margin-top:6px">${inList ? `<span class="small muted">In workflows</span>` : ""}${names}${w && !inList ? wfOnPill(w) : ""}</div>
    <div class="small row wrap" style="gap:4px 8px;margin-top:8px">${r ? wfRunLine(r) : run ? `<span>run ${esc(run)}</span>` : `<span class="muted">No run yet${w ? ` · ${esc(w.schedule)}` : ""}</span>`}</div>
    ${wfDesk() ? `<iframe class="tool-frame run" data-src="${esc(src)}" src="${esc(src)}" loading="lazy" title="n8n: ${run ? "this run" : "its workflow"}"></iframe>` : r || w ? wfStepsHtml(w, r) : ""}</div>`;
  const slot = el.querySelector("iframe.tool-frame");
  if (keep && slot && keep.dataset.src === slot.dataset.src) { slot.parentNode.moveBefore(keep, slot); slot.remove(); keep.hidden = false; }
  else keep?.remove();
}
// WFL-09: a schedule held by a workflow, read-only in plain words (a crew job's or a mission's Settings), with the way to
// change it: the workflow inside the app (its schedule trigger, its Active switch)
function wfScheduleHtml(text, next, wid) {
  return `<div class="card pad wf-sched mt-2"><div class="row between wrap gap-2"><b class="wrap">${esc(text || "when called")}</b>
      <a class="btn sm" href="#/workflows?open=${encodeURIComponent(wid)}">${ic.flow}Its workflow</a></div>
    <div class="small muted mt-1">${next ? `next ${esc(when(next))}` : text === "switched off" ? "it does not run until it is switched on" : "no run planned on a schedule"}</div>
    ${explain("wf-sched", "Its workflow starts it: change the schedule on n8n's canvas (its schedule trigger), or switch it off there (its Active switch).", "Where to change it")}</div>`;
}
async function wfInInto(el, kind, id) {                // kind: "agent" (an agent card) or "crew" (a crew job)
  if (!el) return;
  const v = await wfView();
  if (!el.isConnected) return;
  const ws = (v.workflows || []).filter((w) => (kind === "crew" ? w.crew : w.agents)?.includes(id));
  el.innerHTML = ws.length ? `<div class="chips wf-in"><span class="small muted">In workflows</span>${ws.map((w) => `<a class="tag" href="#/workflows?open=${encodeURIComponent(w.id)}">${ic.flow}${esc(w.name)}</a>`).join("")}</div>` : "";
}
async function wfCrewInto(el, id, keep = null) {       // a crew job's page: its own workflow's last run, and every workflow it is in
  if (!el) { keep?.remove(); return; }
  const v = await wfView(), own = S?.workflows?.jobs?.[`crew:${id}`];
  const ws = (v.workflows || []).filter((w) => w.crew?.includes(id));
  if (!el.isConnected) { keep?.remove(); return; }
  if (!own && !ws.length) { el.innerHTML = ""; keep?.remove(); return; }
  return wfWhereInto(el, own?.id || ws[0].id, "", ws, keep);
}
