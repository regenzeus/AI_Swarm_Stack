// GEN-34: the engine and its runs (docs/AI-STACK.md §5, docs/AI-STACK-PLAN.md §10): every run's blocks as a canvas,
// each with its status, what it waits for and its time, and a timeline of when each block ran. S.engine is written by
// the runner's bridge every pass (ops/engine/projector.py); a deployment on the Conductor has none.
const ENG_WORD = { pending: "not started", running: "running", waiting: "waiting", done: "done", failed: "failed", skipped: "skipped", cancelled: "stopped",
  completed: "done", terminated: "stopped", timed_out: "timed out", continued_as_new: "running" };
const ENG_DOT = { running: "run", waiting: "warn", done: "ok", completed: "ok", failed: "err", skipped: "", cancelled: "", pending: "" };
const ENG_BLOCK = { start: "Start", end: "End", notify: "Notify", agent: "Agent", command: "Command", change: "Change", gate: "Approval", wait: "Wait", tracker: "Tracker", branch: "Decision" };

function engRuns() { return S?.engine?.runs || []; }
function engMs(iso) { const d = iso ? Date.parse(iso) : NaN; return isNaN(d) ? null : d; }
function engSpan(a, b) { const x = engMs(a); if (x == null) return null; const y = engMs(b) ?? Date.now(); return Math.max(0, (y - x) / 1000); }
function engDone(r) { return (r.nodes || []).filter((n) => n.status === "done" || n.status === "skipped").length; }
function engTitle(r) { return r.graph || r.id; }

function engDays(co) {                              // §6 step 8: the Conductor goes once every kind of plan ran 14 clean days here
  const kinds = Object.entries(co?.kinds || {});
  if (!co || (!co.switched && !kinds.length)) return "";
  return `<div class="card pad small eng-days"><b>On the engine${co.switched ? ` since ${esc(clock(co.switched))}` : ""}</b> ·
    ${kinds.map(([k, v]) => `${esc(k)}: ${nf(v.days)} of ${nf(co.needed)} days${v.clean ? " ✓" : ""}`).join(" · ") || "no plan ran here yet"}
    ${explain("engine-days", `The Conductor stays as the rollback until every kind of plan has run ${co.needed} days on the engine with nothing falling back; the landing after that removes it.`)}</div>`;
}

function vEngine() {
  const e = S.engine;
  if (!e) {
    view.innerHTML = `<div class="hero"><div class="grow"><h1>Engine</h1><p>This deployment runs its plans on the Conductor. The engine takes over at the cutover.</p></div></div>`;
    return;
  }
  const id = route.args[0] || "";
  if (id) return engRunPage(e, engRuns().find((r) => r.id === id), id);
  const runs = engRuns(), w = e.engine?.workers || {};
  const workers = Object.entries(w).map(([q, x]) => `${esc(q)}: ${x.workflows ? "polling" : "<b class=\"err-t\">no worker</b>"}${x.activities ? ` · ${nf(x.activities)} step worker${x.activities > 1 ? "s" : ""}` : ""}`).join(" · ");
  view.innerHTML = `
  <div class="hero"><div class="grow"><h1>Engine</h1><p>
    ${e.engine?.up ? `<span class="dot ok"></span> running · namespace <b>${esc(e.engine.namespace)}</b> · ${nf(e.engine.running)} run${e.engine.running === 1 ? "" : "s"} now` : `<b class="err-t">not readable: ${esc(e.engine?.why || "no answer")}</b>`}
    ${workers ? ` · ${workers}` : ""} · ${explain("engine-what", "The engine (Temporal) runs every plan and template as a durable run: it survives restarts, waits for days without holding anything, and keeps each block's history. This screen shows the runs of the last " + (e.engine?.days || 7) + " days; Temporal's own view keeps all of them.")}</p></div>
    ${e.engine?.namespace ? `<a class="btn sm" href="#/runs" title="Temporal's own view of every run">${ic.doc}Runs</a>` : ""}</div>
  ${engDays(e.cutover)}
  <div class="stack eng-runs">${runs.length ? runs.map(engRunRow).join("") : `<div class="card"><p class="muted">No run in the last ${nf(e.engine?.days || 7)} days.</p></div>`}</div>`;
}

function engRunRow(r) {
  const total = (r.nodes || []).length, done = engDone(r), t = engSpan(r.started, r.ended);
  const now = (r.nodes || []).filter((n) => n.status === "running" || n.status === "waiting").map((n) => n.title).join(", ");
  return `<a class="card eng-row" href="#/engine/${encodeURIComponent(r.id)}">
    <div class="row"><span class="dot ${ENG_DOT[r.status] || ""}"></span><b class="grow wrap">${esc(engTitle(r))}</b><span class="pill">${esc(ENG_WORD[r.status] || r.status)}</span></div>
    <div class="sub wrap">${total ? `${nf(done)} of ${nf(total)} blocks done` : "starting"} · started ${r.started ? rel(r.started) : "–"} · ${dur(t)}${now ? ` · now: ${esc(now)}` : ""}${r.why ? ` · ${esc(r.why)}` : ""}</div>
    <div class="eng-mini">${(r.nodes || []).map((n) => `<i class="st-${esc(n.status)}" title="${esc(n.title)}: ${esc(ENG_WORD[n.status] || n.status)}"></i>`).join("")}</div></a>`;
}

function engRunPage(e, r, id) {
  if (!r) {
    view.innerHTML = `<a class="back" href="#/engine">${ic.back || "←"} Engine</a><div class="card"><p>The run ${esc(id)} is not shown yet. A run that just started appears here within a few seconds; one older than ${nf(e.engine?.days || 7)} days is in Temporal's own view.</p></div>`;
    return;
  }
  const t = engSpan(r.started, r.ended);
  const line = `<span class="dot ${ENG_DOT[r.status] || ""}"></span> ${esc(ENG_WORD[r.status] || r.status)} · ${nf(engDone(r))} of ${nf((r.nodes || []).length)} blocks done · started ${r.started ? `${clock(r.started)} (${rel(r.started)})` : "–"} · ${dur(t)}${r.why ? ` · ${esc(r.why)}` : ""}`;
  const sig = `${r.status}|${(r.nodes || []).map((n) => `${n.id}:${n.status}:${n.round}:${n.items_done}`).join("|")}`;
  const box = $("#engcanvas");
  if (box && box.dataset.run === r.id && box.dataset.sig === sig) {   // the same blocks in the same states: only the times move, the buttons stay put
    for (const n of r.nodes || []) {
      const el = box.querySelector(`[data-node="${CSS.escape(n.id)}"] .eng-clock`);
      if (el) el.innerHTML = `<span class="dot ${ENG_DOT[n.status] || ""}"></span> ${engNodeTime(n)}`;
    }
    $("#enghead").innerHTML = line;
    engShow(r, false);
    $("#engtl").innerHTML = engTimeline(r);
    engWires(box, r);                               // a block's text may change its size: the wires follow
    return;
  }
  const kept = box && box.dataset.run === r.id ? [box.scrollLeft, box.scrollTop] : null;   // the same run: where you were looking stays
  view.innerHTML = `
  <a class="back" href="#/engine">${ic.back || "←"} Engine</a>
  <div class="hero"><div class="grow"><h1 class="wrap">${esc(engTitle(r))}</h1><p id="enghead">${line}</p></div>
    ${e.engine?.namespace ? `<a class="btn sm" href="#/runs/${encodeURIComponent(r.id)}" title="This run's whole history in Temporal's own view">${ic.doc}History</a>` : ""}</div>
  <div class="section-h"><h2>Blocks</h2>${explain("engine-blocks", "Each box is one block of the run. The colour says its state; under it, when it started, how long it ran, and what it waits for. Arrows show which block waits for which.")}</div>
  <div class="card eng-canvas" id="engcanvas" data-run="${esc(r.id)}" data-sig="${esc(sig)}">${engCanvas(r)}</div>
  <div id="engdetail">${engDetail(r)}</div>
  <div class="section-h section"><h2>Timing</h2>${explain("engine-timing", "When each block ran, on one time axis from the run's start: a striped bar is a block that waits (for a person, a reply or work elsewhere).")}</div>
  <div class="card" id="engtl">${engTimeline(r)}</div>`;
  engShow(r, false);
  requestAnimationFrame(() => {
    const b = $("#engcanvas");
    engWires(b, r);
    if (!b) return;
    if (kept) [b.scrollLeft, b.scrollTop] = kept;
    else {                                          // first look at a run: the block that works or waits now is in view
      const now = b.querySelector(".eng-node.st-running, .eng-node.st-waiting");
      if (now) { const a = engAt(now, b); b.scrollLeft = Math.max(0, a.l - 60); b.scrollTop = Math.max(0, a.t - 40); }
    }
  });
  window.onresize = () => engWires($("#engcanvas"), r);
  view.querySelectorAll("[data-open]").forEach((el) => {
    const open = (e) => { if (e.target.closest("button")) return; engSel = engSel === el.dataset.open ? "" : el.dataset.open; engShow(r); };
    el.onclick = open;
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(e); } };
  });
  view.querySelectorAll("[data-decide]").forEach((b) => b.onclick = () =>
    act({ action: "engine_decide", run: r.id, node: b.dataset.node, answer: b.dataset.decide, role: (r.nodes || []).find((x) => x.id === b.dataset.node)?.role || "" }, b.dataset.decide === "yes" ? "Approved: the run goes on" : "Refused: the run stops"));
}

let engSel = "";                                    // the block whose details are open on a run's page

function engDetail(r) {                             // what goes on inside the selected block
  const n = (r.nodes || []).find((x) => x.id === engSel);
  if (!n) return "";
  const ns = S.engine?.engine?.namespace;
  const ans = n.answer && Object.keys(n.answer).length ? n.answer : null;
  const step = /^step:(\d+)$/.exec(ans?.ref || "");
  const task = /^task:(\d+):/.exec(r.id);
  const rows = [["Kind", ENG_BLOCK[n.block] || n.block], ["Agent", n.agent], ["Who decides", n.role], ["State", ENG_WORD[n.status] || n.status],
    ["Started", n.started ? `${clock(n.started, true)} (${rel(n.started)})` : ""], ["Ended", n.ended ? clock(n.ended, true) : ""],
    ["Took", n.started ? dur(engSpan(n.started, n.ended)) : ""], ["Waits for", n.waiting_for], ["Round", n.round ? `${nf(n.round + 1)}` : ""],
    ["Who may decide", n.people?.length ? `${n.role ? `${n.role}: ` : ""}${n.people.join(", ")}` : ""],
    ["Refused answers", (n.refused || []).map((x) => `${x.who} (${x.answer}, ${clock(x.at)}): not one of the role's people`).join("; ")],
    ["Reminders sent", n.reminded ? nf(n.reminded) : ""], ["Items", n.items ? `${nf(n.items_done)} of ${nf(n.items)} done` : ""],
    ["Goes back to", n.loop_to ? `${(r.nodes.find((x) => x.id === n.loop_to) || {}).title || n.loop_to}, while problems remain` : ""],
    ["Comes after", (n.after || []).map((a) => (r.nodes.find((x) => x.id === a) || {}).title || a).join(", ")]].filter(([, v]) => v);
  return `<div class="card eng-detail"><div class="row"><b class="grow wrap">${esc(n.title || n.id)}</b><button class="btn sm" id="engclose">Close</button></div>
    <dl class="eng-dl">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd class="wrap">${esc(v)}</dd>`).join("")}</dl>
    ${n.error ? `<p class="err-t wrap">${esc(n.error)}</p>` : ""}
    ${ans ? `<div class="tiny faint">Its answer (references only; the content stays in its step and its files)</div><pre class="wrap small">${esc(JSON.stringify(ans, null, 1))}</pre>` : ""}
    <div class="row eng-links">${step && task ? `<a class="btn sm" href="#/task/${task[1]}">Open the step in its task</a>` : ""}${ns ? `<a class="btn sm" href="#/runs/${encodeURIComponent(r.id)}">Its history in Temporal</a>` : ""}</div></div>`;
}

function engShow(r, scroll = true) {                // the selected block's details and its highlight, in place (no redraw of the page)
  const box = $("#engdetail");
  if (!box) return;
  box.innerHTML = engDetail(r);
  view.querySelectorAll("[data-open]").forEach((el) => el.classList.toggle("sel", el.dataset.open === engSel));
  const cl = $("#engclose");
  if (cl) cl.onclick = () => { engSel = ""; engShow(r); };
  if (scroll && engSel) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function engLayers(nodes) {
  const by = Object.fromEntries(nodes.map((n) => [n.id, n])), depth = {};
  const d = (id, seen = new Set()) => {
    if (depth[id] != null) return depth[id];
    if (seen.has(id)) return 0;
    seen.add(id);
    const n = by[id];
    return (depth[id] = n && n.after?.length ? 1 + Math.max(...n.after.filter((a) => by[a]).map((a) => d(a, seen)), -1) : 0);
  };
  nodes.forEach((n) => d(n.id));
  const layers = [];
  nodes.forEach((n) => (layers[depth[n.id]] = layers[depth[n.id]] || []).push(n));
  return layers.filter(Boolean);
}

function engNodeTime(n) {
  if (n.status === "waiting") return `waits${n.waiting_for ? `: ${esc(n.waiting_for)}` : ""} · for ${dur(engSpan(n.started, ""))}`;
  if (n.status === "running") return `running · ${dur(engSpan(n.started, ""))}`;
  if (n.started && n.ended) return `${clock(n.started)} · ${dur(engSpan(n.started, n.ended))}`;
  return ENG_WORD[n.status] || n.status;
}

function engCanvas(r) {
  const nodes = r.nodes || [];
  if (!nodes.length) return `<p class="muted">The run's blocks are not known yet.</p>`;
  return `<svg class="eng-wires" aria-hidden="true"></svg>${engLayers(nodes).map((layer) => `<div class="eng-layer">${layer.map((n) => `
    <div class="eng-node st-${esc(n.status)}${n.id === engSel ? " sel" : ""}" data-node="${esc(n.id)}" data-open="${esc(n.id)}" role="button" tabindex="0" aria-label="${esc(n.title || n.id)}: open its details">
      <div class="eng-kind">${esc(ENG_BLOCK[n.block] || n.block)}${n.agent ? ` · ${esc(n.agent)}` : ""}${n.round ? ` · round ${nf(n.round + 1)}` : ""}</div>
      <div class="eng-title">${esc(n.title || n.id)}</div>
      ${Object.entries(n.when || {}).map(([a, w]) => `<div class="eng-time faint">${w === "failed" ? `if “${esc((nodes.find((x) => x.id === a) || {}).title || a)}” fails` : `on the branch “${esc(w)}”`}</div>`).join("")}
      ${n.block === "end" && n.answer?.outcome === "stopped" ? `<div class="eng-time">counts as stopped</div>` : ""}
      ${n.block === "branch" && n.answer?.branch ? `<div class="eng-time">went “${esc(n.answer.branch)}”</div>` : ""}
      <div class="eng-time eng-clock"><span class="dot ${ENG_DOT[n.status] || ""}"></span> ${engNodeTime(n)}</div>
      ${n.items ? `<div class="eng-items" title="${nf(n.items_done)} of ${nf(n.items)} items done">${Array.from({ length: n.items }, (_, k) => `<i class="${k < n.items_done ? "st-done" : n.status === "running" ? "st-running" : ""}"></i>`).join("")}<span class="tiny">${nf(n.items_done)}/${nf(n.items)}</span></div>` : ""}
      ${n.loop_to ? `<div class="eng-time faint">back to “${esc((nodes.find((x) => x.id === n.loop_to) || {}).title || n.loop_to)}” while problems remain</div>` : ""}
      ${n.error ? `<div class="eng-time err-t">${esc(n.error)}</div>` : ""}
      ${(n.block === "gate" || (n.block === "wait" && (n.waiting_for || "").includes("did not answer"))) && n.status === "waiting" ? `<div class="row eng-act"><button class="btn sm primary" data-decide="yes" data-node="${esc(n.id)}">Approve</button><button class="btn sm" data-decide="no" data-node="${esc(n.id)}">Refuse</button></div>` : ""}
    </div>`).join("")}</div>`).join("")}`;
}

function engAt(el, box) {                         // an element's box inside the canvas, in the canvas's own pixels (zoom-proof)
  let x = 0, y = 0, e = el;
  while (e && e !== box) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent; }
  return { l: x, t: y, r: x + el.offsetWidth, b: y + el.offsetHeight, cx: x + el.offsetWidth / 2, cy: y + el.offsetHeight / 2 };
}

function engWires(box, r) {
  if (!box) return;
  const svg = box.querySelector(".eng-wires");
  if (!svg) return;
  const lr = getComputedStyle(box).flexDirection === "row";       // wide: left to right; narrow: top to bottom
  svg.setAttribute("width", box.scrollWidth); svg.setAttribute("height", box.scrollHeight);
  const at = (id) => { const el = box.querySelector(`[data-node="${CSS.escape(id)}"]`); return el ? engAt(el, box) : null; };
  const by = Object.fromEntries((r.nodes || []).map((n) => [n.id, n]));
  let paths = "";
  for (const n of r.nodes || []) {
    const q = at(n.id);
    for (const a of n.after || []) {
      const p = at(a);
      if (!p || !q) continue;
      const on = ["done", "skipped"].includes(by[a]?.status) ? "on" : "";
      if (lr) { const mx = (p.r + q.l) / 2; paths += `<path class="${on}" d="M${p.r},${p.cy} C${mx},${p.cy} ${mx},${q.cy} ${q.l - 4},${q.cy}"/>`; }
      else { const my = (p.b + q.t) / 2; paths += `<path class="${on}" d="M${p.cx},${p.b} C${p.cx},${my} ${q.cx},${my} ${q.cx},${q.t - 4}"/>`; }
    }
    const back = n.loop_to && at(n.loop_to);
    if (back && q) {                              // a loop: the check sends work back, drawn as a dashed return arrow
      const label = `up to ${nf(Math.max(1, (n.loop_max || 0)))} more round${(n.loop_max || 0) === 1 ? "" : "s"}`;
      if (lr) { const top = Math.min(back.t, q.t) - 26; paths += `<path class="loop" d="M${q.cx},${q.t} C${q.cx},${top} ${back.cx},${top} ${back.cx},${back.t - 4}"/><text x="${(q.cx + back.cx) / 2}" y="${top + 4}" text-anchor="middle">${label}</text>`; }
      else { const side = Math.max(back.r, q.r) + 34; paths += `<path class="loop" d="M${q.r},${q.cy} C${side},${q.cy} ${side},${back.cy} ${back.r + 4},${back.cy}"/><text x="${side + 4}" y="${(q.cy + back.cy) / 2}">${label}</text>`; }
    }
  }
  svg.innerHTML = `<defs><marker id="engarrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="9" markerHeight="9" orient="auto"><path d="M0,0 L8,4 L0,8 z"/></marker></defs>${paths}`;
}

function engTimeline(r) {
  const nodes = (r.nodes || []).filter((n) => n.started);
  if (!nodes.length) return `<p class="muted">No block has started yet.</p>`;
  const t0 = Math.min(...nodes.map((n) => engMs(n.started))), t1 = Math.max(Date.now() * (r.ended ? 0 : 1), ...nodes.map((n) => engMs(n.ended) || engMs(n.started)), engMs(r.ended) || 0);
  const span = Math.max(1, t1 - t0);
  return `<div class="eng-tl">${nodes.map((n) => {
    const a = engMs(n.started), b = engMs(n.ended) ?? Date.now();
    return `<div class="eng-tl-row"><div class="eng-tl-name wrap">${esc(n.title || n.id)}</div><div class="eng-tl-track"><i class="st-${esc(n.status)}" style="left:${((a - t0) / span * 100).toFixed(2)}%;width:${Math.max(0.6, (b - a) / span * 100).toFixed(2)}%" title="${esc(n.title)}: ${esc(engNodeTime(n).replace(/<[^>]+>/g, ""))}"></i></div><div class="eng-tl-d tiny">${dur(engSpan(n.started, n.ended))}</div></div>`;
  }).join("")}<div class="eng-tl-axis tiny faint"><span>${clock(new Date(t0).toISOString())}</span><span>${dur(span / 1000)}</span><span>${r.ended ? clock(r.ended) : "now"}</span></div></div>`;
}

function engineBanner() {                            // on Stack: one tap to the engine, with what it does now
  const e = S?.engine;
  if (!e) return "";
  return `<a class="banner info" href="#/engine" style="margin-bottom:14px"><span class="dot ${e.engine?.up ? "ok" : "err"}"></span><span class="grow"><b>Engine</b> · ${e.engine?.up ? `${nf(e.engine.running)} run${e.engine.running === 1 ? "" : "s"} now, ${nf((e.runs || []).length)} in the last ${nf(e.engine.days || 7)} days` : "not readable"}</span>${ic.next}</a>`;
}

// §10 "Runs": Temporal's own web UI inside the app, behind its gate, its payloads decrypted by the app's codec endpoint:
// every run, its history, its timers and its signals. route.args[0] opens one run.
function vRuns() {
  const ns = S?.engine?.engine?.namespace || "home", wid = route.args[0];
  const src = `/runs/namespaces/${encodeURIComponent(ns)}/workflows${wid ? `/${encodeURIComponent(wid)}` : ""}`;
  if (view.querySelector("iframe.runs-frame")?.dataset.src === src) return;     // the UI keeps its own state: never redrawn under you
  view.innerHTML = `<a class="back" href="#/engine">${ic.back} Engine</a>
  <div class="hero"><div class="grow"><h1>Runs</h1><p>${esc(ns)} · ${explain("runs-what", "Temporal's own view of every run: its whole history, its timers, its signals and its activities, with the payloads decrypted by the app. The Engine screen draws the same runs as blocks.")}</p></div>
    <a class="btn" href="${esc(src)}" target="_blank" rel="noopener">${ic.doc}Open on its own</a></div>
  <iframe class="runs-frame" data-src="${esc(src)}" src="${esc(src)}" title="Temporal's view of the runs"></iframe>`;
}
