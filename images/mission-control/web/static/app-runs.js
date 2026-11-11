// The app, part of app-base.js, app-tasks.js, app-runs.js, app-devices.js, app-wiki-code.js, app-memory.js, app-workflows.js, app.js (PLT-25): the run log and run view, schedule controls and the chat. Loaded in that order; one global scope.
// ---------- run telemetry (ops/telemetry.py): every model call, tool call, result and thought of a run ----------
const TL_LEVEL = { summary: "Summary", steps: "Steps", all: "Everything" };
let tlLevel = "";
// ---------- the readable agent log: one list for every agent, live and afterwards ----------
// Every source (the runtime record, the old timelines, builder steps, Claude task steps, chat tools, crew logs) is drawn
// by logHtml. logKind is the ONE place where event kinds and tool names become these kinds; a source may also name the
// kind itself (e.kind "wait", data.kind "WRITE"). A call and its result are one line; the model calls before a step
// lend it their tokens. Details unfold on tap: arguments, result preview, the diff of a write.
const LOG_KINDS = ["START", "READ", "WRITE", "TOOL", "WEB", "MAIL", "PHONE", "THINK", "SAYS", "WAIT", "PROPOSE", "ERROR", "END"];
const LK_SERVER = { qmd: "READ", graphify: "READ", research: "WEB", fetch: "WEB", webfetch: "WEB", browser: "WEB", mail: "MAIL", phone: "PHONE" };
const LK_TOOL = [
  [/^(read|read_file|wiki_search|search_files|grep|glob|ls|list_dir|find_symbol|get_symbols_overview|find_referencing_symbols|find_declaration|find_implementations|search_for_pattern|notebookread|skill_view|skills_list|session_search|memory_search|codemap|mission_details|missions_overview|builds_overview|build_details|repos_overview|improvement_proposals|journal_read)$/, "READ"],
  [/^(write|write_file|patch|edit|multiedit|notebookedit|replace_symbol_body|insert_after_symbol|insert_before_symbol|rename_symbol|replace_content|replace_in_files|safe_delete_symbol|vault_add|agent_note|journal_write|memory)$/, "WRITE"],
  [/^(web_search|web_extract|websearch|webfetch|fetch|browse.*|research)$/, "WEB"],
  [/^(send_email|mail_.*|gmail_.*)$/, "MAIL"],
  [/^(phone_.*)$/, "PHONE"],
  [/(propose|proposal|build_assign|mission_create|shop_offer)/, "PROPOSE"],
  [/^(todo_list|todowrite|think|plan)$/, "THINK"],
  [/^(wait|sleep|clarify)$/, "WAIT"],
];
const LK_LABEL = { todo_list: "plan", todowrite: "plan", research: "research", claude_task: "ask Claude", claude_task_result: "Claude's answer", agent_note: "standing note" };
function toolName(name) {                // mcp__vault__research_research → {srv: "research", tool: "research"}; Read → {tool: "read"}
  const own = String(name || "").split("__").pop().toLowerCase();
  const srv = Object.keys(LK_SERVER).concat(["claude", "missions"]).find((s) => own.startsWith(s + "_"));
  return { srv: srv || "", tool: srv ? own.slice(srv.length + 1) : own };
}
function logKind(e) {
  const k = String(e.data?.kind || e.kind || "").toUpperCase();
  if (LOG_KINDS.includes(k)) return k;
  const status = String(e.status || "").toLowerCase();
  switch (e.kind) {
    case "run": return "START";
    case "end": return "END";
    case "say": case "text": case "finding": case "log": return "SAYS";
    case "think": case "llm": return "THINK";
    case "error": return "ERROR";
    case "stage": return status === "failed" || status === "failure" ? "ERROR" : /wait|requested|queued/i.test(e.title || "") || status === "waiting" ? "WAIT" : "TOOL";
    case "conn": return /mail/i.test(e.title || "") ? "MAIL" : /phone/i.test(e.title || "") ? "PHONE" : "TOOL";
  }
  const { srv, tool } = toolName(e.title || e.tool);
  if (srv === "missions" && /build_assign|mission_create/.test(tool)) return "PROPOSE";
  for (const [re, kind] of LK_TOOL) if (re.test(tool)) return kind;
  return LK_SERVER[srv] || "TOOL";
}
function argsOf(d) {
  if (d && typeof d === "object") return d;
  try { const a = JSON.parse(d || "{}"); return a && typeof a === "object" && !Array.isArray(a) ? a : {}; } catch (_) { return {}; }
}
function whatOf(tool, a, raw) {                     // what was done with what: the path, URL, command or question
  if (/^todo/.test(tool) && Array.isArray(a.todos)) {
    const t = a.todos, cur = t.find((x) => x.status === "in_progress");
    return `${t.filter((x) => x.status === "completed").length} of ${t.length} done${cur ? " · now: " + cur.content : ""}`;
  }
  const v = a.command ?? a.cmd ?? a.file_path ?? a.path ?? a.relative_path ?? a.notebook_path ?? a.url ?? a.question ?? a.query ?? a.q ?? a.pattern ?? a.subject ?? a.title ?? a.name_path ?? a.text ?? a.id;
  if (v != null && typeof v !== "object") return String(v);
  if (raw && !/^\s*[{[]/.test(raw)) return raw;
  const keys = Object.keys(a);
  return keys.length ? keys.slice(0, 3).map((k) => `${k}: ${typeof a[k] === "object" ? "…" : String(a[k]).length > 40 ? String(a[k]).slice(0, 40) + "…" : String(a[k]) /* cap: preview: the row opens to all arguments */}`).join(", ") : "";
}
const MONO_ARG = /^(read|read_file|write|write_file|edit|multiedit|patch|bash|terminal|grep|glob|ls|list_dir|fetch|browse_open|search_files)$/;
function resultOf(r) {                                 // a result's one-line outcome: its error, or its size
  if (!r) return "";
  const t = String(r.detail || r.text || "");
  const err = t.match(/"error":\s*"((?:[^"\\]|\\.)+)/);
  if (err || r.kind === "error" || /^(error|failure|failed)$/i.test(r.status || "")) return (err ? err[1] : t.replace(/^\{"(output|content|result)":\s*"/, "")) || "failed";
  const n = r.data?.chars || t.length;
  return n ? `→ ${kn(n)} chars` : "";
}
function resultText(d) {                               // {"result": "..."} → its text; other JSON pretty; text as it is
  const a = argsOf(d), inner = a.result ?? a.output ?? a.content;
  if (typeof inner === "string") return inner;
  return Object.keys(a).length ? JSON.stringify(a, null, 1) : String(d || "");
}
function diffOf(tool, a) {                             // the change a write makes: patch text, old → new, or the new content
  const L = (s, sign) => String(s || "").split("\n").map((x) => `<div class="dl ${sign === "+" ? "add" : sign === "-" ? "del" : ""}">${esc(sign + x)}</div>`).join("");
  if (a.patch) return String(a.patch).split("\n").map((x) => `<div class="dl ${/^\+(?!\+\+)/.test(x) ? "add" : /^-(?!--)/.test(x) ? "del" : /^(@@|\*\*\*)/.test(x) ? "hunk" : ""}">${esc(x)}</div>`).join("");
  if (a.old_string != null || a.new_string != null) return L(a.old_string, "-") + L(a.new_string, "+");
  if (Array.isArray(a.edits)) return a.edits.map((x) => L(x.old_string, "-") + L(x.new_string, "+")).join(`<div class="dl hunk">…</div>`);
  if (a.content != null) return L(a.content, "+");
  return "";
}
const lineCount = (a) => (a.content != null ? `+${String(a.content).split("\n").length} lines` : a.new_string != null ? `${String(a.old_string || "").split("\n").length} → ${String(a.new_string).split("\n").length} lines` : a.patch ? `+${(a.patch.match(/^\+(?!\+\+)/gm) || []).length} −${(a.patch.match(/^-(?!--)/gm) || []).length}` : "");
const tokLine = (t) => (t && t.in ? `${tok(t.in)} in · ${tok(t.out || 0)} out${t.in && t.cached ? ` · ${Math.round((100 * t.cached) / t.in)}% cached` : ""}${t.reasoning ? ` · ${tok(t.reasoning)} thinking` : ""}` : "");

function logLines(events) {                            // events (any source) → readable lines
  const ev = (events || []).map((e) => ({ ...e, title: e.title ?? e.tool ?? "", detail: e.detail ?? e.text ?? "" }));
  const out = [], open = {}, byName = {};
  let pend = null;                                     // tokens of the model calls since the last step
  const addTok = (t) => { if (!t) return; pend = pend || { in: 0, out: 0, cached: 0, reasoning: 0, calls: 0, ms: 0 }; for (const k of ["in", "out", "cached", "reasoning"]) pend[k] += t[k] || 0; pend.calls++; };
  for (const e of ev) {
    if (e.kind === "result" || (e.kind === "error" && (e.data?.call_id || byName[e.title]?.length))) {
      const id = e.data?.call_id, line = (id && open[id]) || (byName[e.title] || []).shift();
      if (line) {
        if (id) delete open[id];
        line.res = e;
        if (e.ms != null) line.ms = e.ms;
        if (e.kind === "error" || /^(error|failure|failed)$/i.test(e.status || "") || /"error":\s*"/.test(String(e.detail).slice(0, 200)) && !/"error":\s*(null|"")/.test(String(e.detail).slice(0, 200))) { line.kind = "ERROR"; line.failed = true; }   // cap: parse: where an error shows
        if (e.ts && line.ts) line.ms = line.ms ?? Math.round((e.ts - line.ts) * 1000);
        continue;
      }
      if (e.kind === "result") continue;               // a result without its call: nothing to say on its own
    }
    if (e.kind === "llm") {
      addTok(e.tokens);
      if (pend) pend.ms += e.ms || 0;
      out.push({ ...e, lk: "THINK", model: true, text: `model call · ${e.title || "model"}${e.data?.finish ? " · " + e.data.finish : ""}`, meta: [fmtMs(e.ms), tokLine(e.tokens), e.status && e.status !== "success" ? e.status : ""] });
      continue;
    }
    if (e.kind === "mcp") { out.push({ ...e, lk: "TOOL", gateway: true, text: `gateway · ${e.title}`, meta: [fmtMs(e.ms), e.status && e.status !== "success" ? e.status : ""] }); continue; }
    const lk = logKind(e), line = { ...e, lk, tok: null };
    if (e.kind === "call" || e.kind === "error" || e.kind === "conn" || (lk !== "START" && lk !== "END" && lk !== "SAYS" && lk !== "THINK" && e.kind !== "stage" && e.kind !== "wait")) {
      const { srv, tool } = toolName(e.title), a = argsOf(e.detail);
      Object.assign(line, { srv, tool, args: a, what: whatOf(tool, a, typeof e.detail === "string" ? e.detail : ""), label: LK_LABEL[tool] || tool.replace(/_/g, " ") });
      if (e.kind === "error") line.failed = true;
      if (e.kind === "call") { if (e.data?.call_id) open[e.data.call_id] = line; else (byName[e.title] = byName[e.title] || []).push(line); }
    } else {
      line.what = e.kind === "run" ? e.title === "started" ? "started" : e.title : e.kind === "end" ? `${e.title || e.status || "ended"}${e.detail ? " · " + e.detail : ""}` : e.title && e.detail && e.kind !== "say" ? (String(e.detail).length <= 140 ? `${e.title} · ${e.detail}` : e.title) : e.detail || e.title;   // a long detail (a prompt) unfolds
      line.label = "";
    }
    if (pend && (lk !== "START" && lk !== "END")) { line.tok = pend; pend = null; }
    out.push(line);
  }
  return out;
}
const phoenixHref = (l) => `/api/phoenix?ts=${encodeURIComponent(l.ts)}&ms=${encodeURIComponent(l.ms || 0)}&model=${encodeURIComponent(l.title || "")}`;
function logShown(l, level) {
  if (level === "all") return true;
  if (l.model || l.gateway) return false;
  if (level === "summary") return ["START", "SAYS", "WRITE", "PROPOSE", "ERROR", "WAIT", "END"].includes(l.lk) || (l.lk === "THINK" && l.kind === "think");
  return true;
}
function logLine(l, i, t0) {
  const tm = l.ts ? clock(l.ts, true) : l.t != null ? "+" + (l.t >= 60 ? Math.floor(l.t / 60) + "m" + String(Math.round(l.t % 60)).padStart(2, "0") : Math.round(l.t) + "s") : "";
  const meta = (l.meta || [fmtMs(l.ms), l.lk === "WRITE" && l.args ? lineCount(l.args) : "", tokLine(l.tok), l.res || l.failed ? resultOf(l.res || l) : ""]).filter(Boolean);
  const mono = l.tool && MONO_ARG.test(l.tool);
  const what = l.label ? `<b>${esc(l.label)}</b>${l.what ? ` <span class="${mono ? "mono" : ""}">${esc(mono || l.lk === "READ" || l.lk === "WRITE" ? l.what : `“${l.what}”`)}</span>` : ""}` : `<span>${esc(l.what || "")}</span>`;
  const build = l.tool === "build_assign" && String(l.res?.detail || "").match(/#(\d+)|"id":\s*(\d+)/);
  const diff = l.lk === "WRITE" && l.args ? diffOf(l.tool, l.args) : "";
  const argsTxt = l.args && Object.keys(l.args).length ? JSON.stringify(l.args, null, 1) : "";
  const full = String(l.detail || "");
  const body = [
    l.agent && l.agent !== l.rootAgent ? `<div class="tiny muted">by ${esc(agentName(l.agent))}</div>` : "",
    l.kind === "say" || l.kind === "think" || (l.lk === "SAYS" && full.length > 160) ? `<div class="md small lgmd">${md(full)}</div>` : "",
    diff ? `<div class="lgsec">Change</div><div class="diffv">${diff}</div>` : "",
    argsTxt && !diff ? `<div class="lgsec">Arguments</div><pre class="lgpre">${esc(argsTxt)}</pre>` : "",
    l.res ? `<div class="lgsec">Result${l.res.data?.chars ? ` · ${nf(l.res.data.chars)} chars` : ""}</div><pre class="lgpre">${esc(resultText(l.res.detail || l.res.text))}</pre>` : "",
    build ? `<a class="btn sm" href="#/build/${build[1] || build[2]}">${ic.code}Open build #${build[1] || build[2]}</a>` : "",
    !l.res && !argsTxt && l.kind !== "say" && l.kind !== "think" && full.length > 160 ? `<pre class="lgpre">${esc(full)}</pre>` : "",
    l.tok ? `<div class="tiny faint">model before this step: ${l.tok.calls} call${l.tok.calls > 1 ? "s" : ""}${l.tok.ms ? " · " + fmtMs(l.tok.ms) : ""} · ${esc(tokLine(l.tok))}</div>` : "",
    l.model && l.data?.finish ? `<div class="tiny faint">finish: ${esc(l.data.finish)}</div>` : "",
    l.model && l.ts ? `<a class="btn sm" href="${phoenixHref(l)}">${ic.search}Open in Phoenix · the full prompt and answer</a>` : "",
  ].filter(Boolean).join("");
  const nested = l.agent && l.rootAgent && l.agent !== l.rootAgent;
  const cls = `lg lk-${l.lk.toLowerCase()}${nested ? " nested" : ""}${l.failed ? " fail" : ""}${l.model || l.gateway ? " minor" : ""}${tm ? "" : " notime"}`;
  const sum = `<span class="lgt num">${tm}</span><span class="lgk">${l.lk}</span><span class="lgx">${what}</span>${meta.length ? `<span class="lgm">${esc(meta.join(" · "))}</span>` : ""}`;
  return body ? `<details class="${cls}" data-lid="${esc(l.id ?? i)}"><summary>${sum}</summary><div class="lgd">${body}</div></details>` : `<div class="${cls}">${sum}</div>`;
}
let logFilter = "";
function logHtml(events, opts = {}) {
  const level = opts.level || tlLevel || "steps", lines = logLines(events);
  const root = lines.find((l) => l.lk === "START")?.agent || lines[0]?.agent;
  lines.forEach((l) => (l.rootAgent = root));
  const shown = lines.filter((l) => logShown(l, level) && (!logFilter || l.lk === logFilter));
  const counts = {};
  lines.filter((l) => !l.model && !l.gateway).forEach((l) => (counts[l.lk] = (counts[l.lk] || 0) + 1));
  const chips = opts.bare ? "" : `<div class="lgchips">${LOG_KINDS.filter((k) => counts[k] && !["START", "END"].includes(k)).map((k) => `<button type="button" class="lgchip lk-${k.toLowerCase()} ${logFilter === k ? "on" : ""}" data-lk="${k}">${k} ${counts[k]}</button>`).join("")}</div>`;
  return `${chips}<div class="lgbox ${opts.cls || ""}">${shown.map((l, i) => logLine(l, i)).join("") || `<div class="small muted" style="padding:8px">${logFilter ? `No ${logFilter} lines.` : "Nothing at this level yet."}</div>`}</div>`;
}
function bindLog(el, redraw) {                         // the kind chips filter the log; a second tap shows all again
  $$("[data-lk]", el).forEach((b) => (b.onclick = () => { logFilter = logFilter === b.dataset.lk ? "" : b.dataset.lk; redraw(); }));
  $$("[data-tll]", el).forEach((b) => (b.onclick = () => { tlLevel = b.dataset.tll; setPref("mc-tl", tlLevel); redraw(); }));
}
const levelSeg = () => `<div class="seg sm lglevel">${Object.entries(TL_LEVEL).map(([k2, l]) => `<button type="button" data-tll="${k2}" class="${tlLevel === k2 ? "on" : ""}">${l}</button>`).join("")}</div>`;
function plainLog(lines, start) {                      // a job's plain log lines (systemd) as log events
  return (lines || []).map((x, i) => ({ id: "p" + i, kind: /error|fail|traceback|denied|refused/i.test(x) ? "error" : "log", title: "", detail: x, t: null, ts: null }));
}
async function oldTimeline(el, rid) {                  // runs before the runtime record: their timeline, drawn as the same log
  const T = await api(`/api/run/${rid}/timeline`).catch(() => null);
  if (!T || T.error || !el.isConnected) return false;
  const draw = () => {
    el.innerHTML = `<div class="card pad-l"><div class="row between wrap" style="gap:6px"><b class="small">Run ${esc(rid)} · ${dur(T.stats.seconds)} · ${T.stats.llm_calls} model calls · ${T.stats.tool_calls} tool calls</b>${levelSeg()}</div>
      ${T.problems?.length ? problemsHtml(T.problems) : ""}${logHtml(T.events)}<details class="obsb"><summary class="small"><b>What it touched</b></summary>${touchesHtml(T.data, T.files)}</details></div>`;
    bindLog(el, draw);
  };
  draw();
  return true;
}
// ---------- observability blocks (ops/observe.py): files read vs modified, statistics ----------
function filesHtml(files) {
  if (!files?.length) return `<div class="small muted">No files read or changed.</div>`;
  const mod = files.filter((f) => f.modified).length, row = (f) => `<div class="frow"><span class="mono small wrap grow" title="${esc(f.path)}">${esc(f.path)}</span>
    ${f.modified ? `<span class="tag fmod">changed${f.modified > 1 ? " ×" + f.modified : ""}</span>` : ""}${f.read ? `<span class="tag">read${f.read > 1 ? " ×" + f.read : ""}</span>` : ""}<span class="tiny faint">${esc(f.tools.join(", "))}</span></div>`;
  return `<div class="tiny muted" style="margin-bottom:6px">${files.length} files · ${mod} changed · ${files.length - mod} only read</div>
    <div class="flist">${files.slice(0, 20).map(row).join("") /* cap: list: the rest folds below */}</div>
    ${files.length > 20 ? `<details><summary class="tiny muted">${files.length - 20} more</summary><div class="flist">${files.slice(20).map(row).join("")}</div></details>` : ""}`;
}
function statsHtml(d) {
  if (!d) return "";
  const m = d.model || {}, t = d.time || {};
  return `<div class="row wrap small" style="gap:14px">${m.calls ? `<span><b>${m.calls}</b> model calls · ${tok(m.tokens_per_call)} tokens/call · <b>${m.cache_pct}%</b> cached${m.p50_ms ? ` · ${fmtMs(m.p50_ms)} typical, ${fmtMs(m.p95_ms)} slowest 5 %` : ""}</span>` : ""}
      ${t.total_s ? `<span>time: ${dur(t.total_s)}${t.model_s ? ` · model ${dur(t.model_s)}` : ""}${t.tools_s ? ` · tools ${dur(t.tools_s)}` : ""}</span>` : ""}</div>
    ${d.tools?.length ? `<table class="stab"><tr><th>Tool</th><th>calls</th><th>errors</th><th>avg</th><th>max</th></tr>${d.tools.slice(0, 15).map((x) => `<tr><td class="mono">${esc(x.tool)}</td><td>${x.calls}</td><td class="${x.errors ? "err-t" : ""}">${x.errors || ""}</td><td>${x.avg_s != null ? x.avg_s + " s" : ""}</td><td>${x.max_s != null ? x.max_s + " s" : ""}</td></tr>`).join("")}</table>${moreOf(d.tools.length, 15)}` : ""}`;
}
const PROB_LABEL = { "unknown-tool": "Unknown tool names", "empty-args": "Calls without arguments", "bad-args": "Arguments not JSON",
  repeat: "Same call again and again", "tool-error": "Tool errors", limit: "Usage limit", "partial-read": "Answer after cut-off results", "no-end": "No clean end" };
function problemsHtml(ps) {
  const groups = {};
  ps.forEach((p) => (groups[p.kind] = groups[p.kind] || []).push(p));
  return `<div class="obsprob"><b class="small">Problems · ${ps.length}</b>${Object.entries(groups).map(([k, xs]) => `<details><summary class="small err-t">${esc(PROB_LABEL[k] || k)} ×${xs.length}</summary>
    ${xs.map((p) => `<div class="tiny">+${Math.round(p.t || 0)}s · ${esc(p.text)}</div>`).join("")}</details>`).join("")}</div>`;   /* cap: list */
}
function touchesHtml(d, files) {
  if (!d) return `<div class="small muted">Recorded for runs from 28 October on.</div>`;
  files = files || d.files || [];
  const changed = files.filter((f) => f.modified), read = files.filter((f) => !f.modified);
  const sec = (title, n, body, cls = "") => `<details class="obsb" ${n && cls ? "open" : ""}><summary class="small"><b class="${cls}">${title}</b> <span class="muted">· ${n}</span></summary>${body}</details>`;
  const lines = (xs, mono) => xs.map((x) => `<div class="${mono ? "mono " : ""}tiny ellipsis" title="${esc(x)}">${esc(x)}</div>`).join("") || `<div class="tiny muted">none</div>`;
  return `<div class="tiny muted">${d.used_tools.length} tools used${d.allowed_tools.length ? ` of ${d.allowed_tools.length} allowed` : ""}${d.grants?.length ? ` · grants: ${d.grants.map(esc).join(", ")}` : ""}${d.mails_read ? ` · ${d.mails_read} mails read` : ""}${d.phone_screens ? ` · ${d.phone_screens} phone screens` : ""}</div>
    ${sec("Changed", changed.length, filesHtml(changed), changed.length ? "warn-t" : "")}
    ${sec("Read", read.length + (d.urls_total ?? d.urls.length) + (d.searches_total ?? d.searches.length), `${read.length ? filesHtml(read) : ""}${d.urls.length ? `<div style="margin-top:6px"><b class="tiny">Pages</b>${lines(d.urls, true)}${moreOf(d.urls_total, d.urls.length)}</div>` : ""}${d.searches.length ? `<div style="margin-top:6px"><b class="tiny">Searches</b>${lines(d.searches)}${moreOf(d.searches_total, d.searches.length)}</div>` : ""}`)}
    ${sec("Refused", d.refused_total ?? (d.refused?.length || 0), (d.refused || []).map((r) => `<div class="tiny">+${Math.round(r.t || 0)}s <b>${esc(r.tool)}</b>: ${esc(r.why)}</div>`).join("") || `<div class="tiny muted">none</div>`, d.refused?.length ? "err-t" : "")}
    ${sec("Cut off", d.partial.length, d.partial.map((p) => `<div class="tiny">+${Math.round(p.t || 0)}s <b>${esc(p.tool)}</b>: ${esc(p.why)}</div>`).join("") || `<div class="tiny muted">none</div>`, d.partial.length ? "err-t" : "")}`;
}
function obsBlocks(files, detail) {
  return `<details class="obsb"><summary class="small"><b>Files</b> <span class="muted">· ${files?.length || 0} · ${(files || []).filter((f) => f.modified).length} changed</span></summary>${filesHtml(files)}</details>
    <details class="obsb"><summary class="small"><b>Statistics</b></summary>${statsHtml(detail)}</details>`;
}

// ---------- the run view (runrecord.py): what an agent does and what it touches, live over SSE or replayed ----------
// The one view for every run kind (Hermes chats, missions, builds, Claude tasks, AI phone, Gmail, Crew): #/live/<run>
// full page, and mountRun() inside an agent page's Now and History. The log is logHtml; the old per-run Timeline remains
// for runs recorded before the runtime record existed.
const RT_STATE = { done: ["ok", "Done"], failed: ["failed", "Failed"], stopped: ["paused", "Stopped"], stalled: ["failed", "Stalled"], limit: ["paused", "Usage limit"] };
let rtES = null, rtTimer = null;

// TAX-12: an agent card's own readable name (config/agents.yaml name: "Tax reader"), from the agents the board offers
const cardName = (a) => ((S?.task_agents || []).find((x) => x.id === a) || {}).name || "";
function agentName(a) {
  return ({ main: "Hermes (chat)", mission: "Hermes (workflow steps)", scout: "Scout", curator: "Curator", builder: "Builder (ChatGPT)", "claude-builder": "Builder (Claude Code)",
            "claude-task": "Claude question", "claude-review": "Claude review", "claude-maintainability": "Claude review (scheduled)", "ai-phone": "AI phone", mail: "Gmail", runner: "Runner" })[a]
    || (String(a || "").startsWith("mission:") ? (S?.missions || []).find((m) => "mission:" + m.slug === a)?.title || "Briefing " + a.slice(8)
    : String(a || "").startsWith("crew:") ? (S?.crew || []).find((c) => "crew:" + c.id === a)?.name || "Scheduled: " + a.slice(5)
    : { claude: "Claude Code", phone: "AI phone", gmail: "Gmail", house: "House", "self-review": "Self-review", "phone-check": "Phone check", "phone-cleanup": "Phone cleanup" }[a]
    || cardName(a) || String(a || "").replace(/^\w/, (x) => x.toUpperCase()));
}
// a link to a thing's newest run (build:7, claude-task:3, mission-run:15, phone, mail): opens the run view
function liveLink(id, label = "Run view") { return `<a class="btn sm" href="#/live/${encodeURIComponent(id)}">${ic.pulse}${label}</a>`; }

async function mountRun(el, id, opts = {}) {           // → false when the runtime has no record of this run
  clearInterval(rtTimer); rtES?.close();
  tlLevel = tlLevel || pref("mc-tl", "steps");
  let V = await api(`/api/rt/run/${encodeURIComponent(id)}`).catch(() => null);
  if (!V || V.error || !el.isConnected) return false;
  const draw = () => {
    if (!el.isConnected) return;
    const open = new Set($$("details[open]", el).map((d) => d.dataset.lid || d.className));   // keep open what you are reading
    const list = $(".lgbox", el), atEnd = !list || list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    el.innerHTML = liveHtml(V, opts);
    $$("details", el).forEach((d) => { if (open.has(d.dataset.lid || d.className)) d.open = true; });
    const nl = $(".lgbox", el);
    if (nl && V.live && atEnd) nl.scrollTop = nl.scrollHeight;
    bindLog(el, draw);
  };
  draw();
  if (!V.live) return true;
  const after = V.events.length ? V.events[V.events.length - 1].id : 0;
  rtES = new EventSource(`/api/rt/run/${encodeURIComponent(V.run)}/stream?after=${after}`);
  rtES.onmessage = (m) => {                    // new steps show at once; touches and totals follow with the next refresh
    for (const e of JSON.parse(m.data)) { e.t = Math.round((e.ts - V.started) * 10) / 10; V.events.push(e); }
    draw();
  };
  rtES.addEventListener("end", () => { rtES.close(); refresh(); });
  async function refresh() {                   // touches, problems and totals are worked out on the server
    if (!el.isConnected) { clearInterval(rtTimer); rtES?.close(); return; }
    const n = await api(`/api/rt/run/${encodeURIComponent(V.run)}`).catch(() => null);
    if (n && !n.error) { V = n; draw(); }
    if (!V.live) { clearInterval(rtTimer); rtES?.close(); }
  }
  rtTimer = setInterval(refresh, 8000);
  return true;
}

async function vLive() {
  const id = decodeURIComponent(route.args[0] || "");
  view.innerHTML = `<a class="back" href="javascript:history.back()">${ic.back}Back</a><div id="lv"><div class="skeleton" style="height:240px"></div></div>`;
  // a bare #/live names no run: nothing to fetch, the empty state at once
  if (!(id && await mountRun($("#lv"), id)) && $("#lv")) $("#lv").innerHTML = emptyState("No run record for this yet. Runs show here from the moment they start (recorded from 28 October on).",
    `<a class="btn sm" href="#/home?tab=activity">${ic.history}Every run on the timeline</a>`, "card pad-l");
}

// MEM-46: what memory a run was given (by collection), which items it used, what it yielded; a chat turn's long-term memory
const OUTCOME_WORD = { add: "kept", confirm: "confirmed", skip: "already held", reject: "not kept", queue: "queued", retire: "retired", split: "split", archive: "archived", error: "could not be written" };
function memRunHtml(r, chat) {
  const given = r?.given || [], used = r?.used, ys = r?.yielded || [];
  const usedRef = new Set((used?.items || []).filter((x) => x.used).map((x) => x.ref));
  const op = given.map((g) => `<div style="margin-top:6px"><b class="small">${esc(KIND_WORD[g.kind] || g.kind)} memory: ${nf(g.chars)} of ${nf(g.budget)} characters</b>
      ${(g.items || []).map((x) => `<div class="tiny wrap">${usedRef.has(x.ref) ? ic.check : "·"} <span class="mono">${esc(x.coll)}</span> ${esc(x.title)} · ${nf(x.chars)}${x.cut ? " (cut to fit)" : ""}</div>`).join("")}
      ${(g.pointers || []).length ? `<div class="tiny faint">${nf(g.pointers.length)} more listed for it to open, not given</div>` : ""}
      ${(g.missing || []).map((m) => `<div class="tiny warn-t wrap">${ic.alert} could not be read: ${esc(m)}</div>`).join("")}</div>`).join("");
  const u = used ? `<div class="tiny" style="margin-top:6px">${used.measurable_chars ? `Used ${Math.round((100 * used.used_chars) / used.measurable_chars)} % of what could be measured (${nf(used.used_chars)} of ${nf(used.measurable_chars)} characters); a ✓ marks what it used.` : "What it used could not be measured: the items name no file or page."}</div>` : given.length ? `<div class="tiny faint" style="margin-top:6px">Used: measured when the run ends.</div>` : "";
  const y = ys.length ? `<div style="margin-top:8px"><b class="small">Yielded</b>${ys.map((w) => `<div class="tiny wrap">${esc(OUTCOME_WORD[w.outcome] || w.outcome)}: ${esc(w.candidate?.text || "")}${w.where ? ` → ${esc(w.where)}` : ""}${w.why ? ` <span class="faint">(${esc(w.why)})</span>` : ""}${w.undo && !w.undone && ["lesson", "file", "line"].includes(w.undo.kind) ? ` <button type="button" class="linkbtn tiny" data-memundo="${esc(w.id)}">Undo</button>` : ""}</div>`).join("")}</div>` : "";
  const c = chat?.rows?.length ? `<div style="margin-top:8px"><b class="small">Long-term memory in this turn</b>${chat.rows.map((x) => `<div class="tiny wrap">${esc(x.action === "recall" ? "recalled" : "kept")} at ${clock(x.at)}: <span class="faint">${esc(x.action === "recall" ? x.response : x.request)}</span></div>`).join("")}</div>` : chat?.error ? `<div class="tiny warn-t">${esc(chat.error)}</div>` : "";
  return (op + u + y + c) || "No memory was given to this run, and it yielded none.";
}
document.addEventListener("toggle", async (e) => {
  const d = e.target;
  if (!(d instanceof HTMLDetailsElement) || !d.open || !d.dataset.memrun || d.dataset.loaded) return;
  d.dataset.loaded = "1";
  const box = $(".memrun", d);
  const r = await api(`/api/memory/run?run=${encodeURIComponent(d.dataset.memrun)}`).catch(() => null);
  const from = Number(d.dataset.memfrom) || Date.parse(d.dataset.memfrom) / 1000, to = Number(d.dataset.memto) || Date.parse(d.dataset.memto) / 1000 || Date.now() / 1000;
  const chat = d.dataset.memagent === "main" && from ? await act({ action: "mem_chat", start: from, end: to + 60 }, null) : null;
  box.innerHTML = memRunHtml(r, chat);
  $$("[data-memundo]", box).forEach((b) => (b.onclick = async () => { b.disabled = true; if (await act({ action: "mem_undo", id: b.dataset.memundo }, "Undone: the entry is back as it was")) b.replaceWith(document.createTextNode(" undone")); else b.disabled = false; }));
}, true);

function liveHtml(V, opts = {}) {
  const st = V.live ? ["running", "Live"] : RT_STATE[V.end_state] || ["archived", V.end_state || "Ended"];
  const k = V.stats.model, T = V.touches, m = V.manifest || {};
  const llm = V.events.filter((e) => e.kind === "llm"), sum = (f) => llm.reduce((n, e) => n + ((e.tokens || {})[f] || 0), 0);
  const title = V.name || V.title || agentName(V.agent) || V.run;
  const parent = V.ref && /^(mission-run|build|claude-task|crew):/.test(V.ref) ? `<a class="tiny" href="#/live/${encodeURIComponent(V.ref)}">part of ${esc(V.ref)}</a>` : "";
  const priced = llm.filter((e) => costOf(e.title, e.tokens) != null), paid = priced.reduce((n, e) => n + costOf(e.title, e.tokens), 0);
  const nums = `<span>${dur(V.seconds)}</span><span>${k.calls} model calls · ${tok(sum("in"))} in${k.cache_pct ? ` · ${k.cache_pct}% cached` : ""}${priced.length ? ` · ${ifPaid(paid)}` : ""}${sum("reasoning") ? ` · ${tok(sum("reasoning"))} thinking` : ""}</span><span>${V.stats.tools.reduce((n, t) => n + t.calls, 0)} tool calls</span>${llm.length ? `<a href="#/traces" title="Every model call with its full prompt and answer (a model call in the log opens its own trace)">Traces</a>` : ""}`;
  const head = opts.compact
    ? `<div class="row between wrap" style="gap:6px;align-items:center"><div class="row wrap" style="gap:6px;align-items:center"><span class="pill ${st[0]}">${V.live ? `<span class="dot run"></span>` : ""}${st[1]}</span><b class="small">${V.live ? "Now" : "Latest run"} · ${dt(V.started)}</b></div><a class="tiny" href="#/live/${encodeURIComponent(V.run)}">full view →</a></div>
       <div class="row wrap tiny muted" style="gap:2px 10px;margin-top:4px">${nums}</div>`
    : `<div class="row wrap" style="gap:8px;align-items:center"><span class="pill ${st[0]}">${V.live ? `<span class="dot run"></span>` : ""}${st[1]}</span><h1 class="grow lvh1" title="${esc(title)}">${esc(title)}</h1></div>
       ${V.title && V.name && !V.name.includes(V.title) && !/^##\s*Your memory/.test(V.title) ? `<div class="small muted wrap" style="margin-top:4px" title="${esc(V.title)}">${esc(V.title)}</div>` : ""}
       <div class="row wrap small muted" style="gap:4px 12px;margin-top:6px"><span>${esc(agentName(V.agent))}</span>${nums}${parent}</div>${/^claude-task:\d+$/.test(V.run) ? fromChat("claude:" + V.run.slice(12)) : ""}`;
  return `<div class="card pad-l lvcard">${head}
      ${V.children.length ? `<div class="row wrap" style="gap:6px;margin-top:8px">${V.children.map((c) => `<a class="tag" href="#/live/${encodeURIComponent(c.run)}" title="${esc(c.title || "")}">${esc(agentName(c.agent))}${c.end_state ? " · " + esc(c.end_state) : " · live"}</a>`).join("")}</div>` : ""}
      ${(V.drift || []).length ? `<div class="tiny muted" style="margin-top:6px">${ic.tune}Changed since its last run: ${V.drift.map(esc).join("; ")}</div>` : ""}
      ${V.problems.length ? problemsHtml(V.problems) : ""}
      <div class="row between wrap" style="gap:6px;margin-top:10px"><b class="small">Log</b>${levelSeg()}</div>
      ${V.events_total > V.events.length ? `<div class="small muted">${nf(V.events_total - V.events.length)} earlier events are not shown here; the run record keeps every one.</div>` : ""}
      ${logHtml(V.events, { cls: V.live ? "live" : "" })}
      <details class="obsb" ${opts.compact ? "" : "open"}><summary class="small"><b>What it touched</b> <span class="muted">· ${T.files.length} files · ${T.urls.length} pages${T.connections.length ? ` · ${T.connections.length} connections` : ""}</span></summary>
        ${V.box ? `<div class="lvbox"><b class="small">${ic.lock || ""}The box it works in</b><div class="tiny muted">${esc(V.box.where || "")}${V.box.can ? ` · may: ${esc(V.box.can)}` : ""}${V.box.network ? ` · network: ${esc(V.box.network)}` : ""}${V.box.never ? ` · never: ${esc(V.box.never)}` : ""}</div></div>` : ""}
        ${touchesHtml(T)}
        <details class="obsb" ${T.connections.length ? "open" : ""}><summary class="small"><b>Connections used</b> <span class="muted">· ${T.connections.length}</span></summary>${T.connections.map((c) => `<div class="tiny"><span class="mono">${esc(c.tool)}</span> ×${c.calls}</div>`).join("") || `<div class="tiny muted">none</div>`}</details></details>
      <details class="obsb" data-memrun="${esc(V.run)}" data-memagent="${esc(V.agent || "")}" data-memfrom="${esc(V.started || "")}" data-memto="${esc(V.ended || "")}"><summary class="small"><b>Memory</b> <span class="muted">· given, used, yielded</span></summary><div class="memrun tiny muted">Opening it reads the record…</div></details>
      <details class="obsb"><summary class="small"><b>Statistics</b></summary>${statsHtml(V.stats)}</details>
      ${m.agent ? `<details class="obsb"><summary class="small"><b>Manifest</b> <span class="muted">· what it started with${V.drift?.length ? " · drift" : ""}</span></summary><div class="tiny mono" style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(Object.entries(m).map(([a, b]) => `${a} ${typeof b === "object" ? JSON.stringify(b) : b}`).join("\n"))}</div></details>` : ""}
    </div>`;
}

const openResults = new Set();                          // results you opened stay open while the page redraws
async function loadInto(el, path, preview) {
  try {
    const t = await api(`/api/file?path=${encodeURIComponent(path)}`);
    const open = !preview || !openResults.has(`closed:${path}`);           // the whole result from the start (the owner, 9 Nov 2026)
    el.innerHTML = `<div class="row between"><h2>Latest result</h2><a class="tiny muted" href="#/read?path=${encodeURIComponent(path)}&m=${encodeURIComponent(route.args[0] || "")}">${ic.doc}Full page</a></div>
      <div class="md result ${open ? "" : "clamped"}" style="margin-top:8px">${md(t)}</div>
      ${preview ? `<button class="btn sm ghost rmore" type="button">${open ? "Show less" : "Show all"}</button>` : ""}`;   /* cap: preview: one long result, whole from the start; its reader may fold it */
    if (!preview) return;
    const body = el.querySelector(".result"), more = el.querySelector(".rmore");
    if (body.scrollHeight <= body.clientHeight + 4 && !open) { body.classList.remove("clamped"); more.remove(); return; }   // short: nothing to open
    const toggle = () => {
      const now = body.classList.toggle("clamped");
      now ? openResults.add(`closed:${path}`) : openResults.delete(`closed:${path}`);
      more.textContent = now ? "Show all" : "Show less";   /* cap: preview: one long result, whole from the start; its reader may fold it */
      if (now) el.scrollIntoView({ block: "nearest" });
    };
    more.onclick = toggle;
    body.onclick = (e) => { if (body.classList.contains("clamped") && !e.target.closest("a")) toggle(); };   // tap the text to open it
  } catch (e) { el.innerHTML = `<h2>Latest result</h2><div class="muted small">Not readable.</div>`; }
}

function vRead() {
  const p = route.q.get("path"), m = route.q.get("m");
  view.innerHTML = `<a class="back" href="${m ? `#/mission/${encodeURIComponent(m)}` : "javascript:history.back()"}">${ic.back}Back</a>
    <article class="card pad-l md reader" id="doc"><div class="skeleton"></div></article>`;
  api(`/api/file?path=${encodeURIComponent(p)}`).then((t) => { const d = $("#doc"); if (d) d.innerHTML = md(t); })   // you may have left the page meanwhile
    .catch(() => { const d = $("#doc"); if (d) d.textContent = "Not readable."; });
}

// ---------- schedule + triggers controls (shared by new + settings) ----------
const DAYS = [["mon", "Mo"], ["tue", "Tu"], ["wed", "We"], ["thu", "Th"], ["fri", "Fr"], ["sat", "Sa"], ["sun", "Su"]];
function parseSched(s) {
  let m;
  if (!s || s === "manual") return { mode: "manual", time: "06:30", days: ["mon"], hours: 6 };
  if ((m = s.match(/^(daily|weekdays) (\d\d:\d\d)$/))) return { mode: m[1], time: m[2], days: ["mon"], hours: 6 };
  if ((m = s.match(/^weekly (\S+) (\d\d:\d\d)$/))) return { mode: "weekly", time: m[2], days: m[1].split(","), hours: 6 };
  if ((m = s.match(/^every (\d+)h$/))) return { mode: "every", time: "06:30", days: ["mon"], hours: +m[1] };
  return { mode: "daily", time: "06:30", days: ["mon"], hours: 6 };
}
function schedHtml(s) {
  const p = parseSched(s);
  return `<label class="field"><span>Schedule</span><select class="input" name="smode">
      ${[["daily", "Daily"], ["weekdays", "Weekdays (Mon–Fri)"], ["weekly", "On chosen days"], ["every", "Every few hours"], ["manual", "No schedule (on demand / events only)"]].map(([k, l]) => `<option value="${k}" ${p.mode === k ? "selected" : ""}>${l}</option>`).join("")}
    </select></label>
    <div class="field" data-show="weekly"><span>Days</span><div class="days">${DAYS.map(([k, l]) => `<label><input type="checkbox" name="sday" value="${k}" ${p.days.includes(k) ? "checked" : ""}><span>${l}</span></label>`).join("")}</div></div>
    <label class="field" data-show="daily weekdays weekly"><span>Time</span><input class="input" type="time" name="stime" value="${p.time}" style="max-width:160px"></label>
    <label class="field" data-show="every"><span>Interval</span><select class="input" name="shours" style="max-width:200px">${[1, 2, 3, 4, 6, 8, 12, 24].map((h) => `<option value="${h}" ${p.hours === h ? "selected" : ""}>every ${h} h</option>`).join("")}</select></label>`;
}
function bindSched(form) {
  const sync = () => { const v = form.smode.value; $$("[data-show]", form).forEach((el) => (el.hidden = !el.dataset.show.split(" ").includes(v))); };
  form.smode.onchange = sync; sync();
}
function readSched(form) {
  const v = form.smode.value, t = form.stime?.value || "06:30";
  if (v === "manual") return "manual";
  if (v === "every") return `every ${form.shours.value}h`;
  if (v === "weekly") { const d = $$("[name=sday]:checked", form).map((x) => x.value); return d.length ? `weekly ${d.join(",")} ${t}` : null; }
  return `${v} ${t}`;
}
const lines = (s) => String(s || "").split("\n").map((x) => x.trim()).filter(Boolean);

function trigRow(t = { type: "sec_filing" }) {
  const v = (k, d = "") => esc(t[k] ?? d);
  return `<div class="trow card">
    <select class="input" data-k="type">${[["sec_filing", "New SEC filing"], ["price_move", "Big price move"], ["news", "News on a topic"]].map(([k, l]) => `<option value="${k}" ${t.type === k ? "selected" : ""}>${l}</option>`).join("")}</select>
    <input class="input" data-k="tickers" data-for="sec_filing" placeholder="US tickers, e.g. ASPI, LEU" value="${esc((t.tickers || []).join(", "))}">
    <div class="row" data-for="price_move"><input class="input" data-k="symbol" placeholder="Symbol, e.g. ACME" value="${v("symbol")}"><input class="input" data-k="pct" type="number" min="1" max="50" step="0.5" value="${v("pct", 5)}" style="max-width:90px"><span class="small muted">%</span></div>
    <input class="input" data-k="query" data-for="news" placeholder="Search, e.g. Beta Materials contract" value="${v("query")}">
    <button type="button" class="icon-btn" data-del title="Remove">${ic.trash}</button>
  </div>`;
}
function trigEditor(list) {
  return `<div class="field"><span>Event triggers <small style="display:inline">· checked every 10 minutes; each new event starts a run</small></span>
    <div id="trigs">${(list || []).map(trigRow).join("")}</div>
    <button type="button" class="btn sm" id="addtrig" style="margin-top:8px">${ic.plus}Add trigger</button></div>`;
}
function bindTrig(form) {
  const sync = (row) => { const t = $("[data-k=type]", row).value; $$("[data-for]", row).forEach((el) => (el.hidden = el.dataset.for !== t)); };
  const bindRow = (row) => { $("[data-k=type]", row).onchange = () => sync(row); $("[data-del]", row).onclick = () => row.remove(); sync(row); };
  $$(".trow", form).forEach(bindRow);
  $("#addtrig", form).onclick = () => { $("#trigs", form).insertAdjacentHTML("beforeend", trigRow()); bindRow($("#trigs", form).lastElementChild); };
}
function readTrig(form) {
  return $$(".trow", form).map((row) => {
    const g = (k) => $(`[data-k=${k}]`, row).value.trim(), type = g("type");
    if (type === "sec_filing") return { type, tickers: g("tickers").split(/[,\s]+/).filter(Boolean) };
    if (type === "price_move") return { type, symbol: g("symbol"), pct: +g("pct") };
    return { type, query: g("query") };
  }).filter((t) => (t.tickers && t.tickers.length) || t.symbol || t.query);
}

function deliverHtml(d = ["telegram", "app"]) {
  const mail = S?.system?.email_ready;
  return `<div class="card pad" style="margin-top:16px;padding-top:4px;padding-bottom:4px">
    <label class="switch"><span><b>Telegram</b><div class="small muted">Short version with buttons into the app</div></span><input type="checkbox" name="d_telegram" ${d.includes("telegram") ? "checked" : ""}></label>
    <label class="switch"><span><b>App notification</b><div class="small muted">Push to your phone when a run finishes</div></span><input type="checkbox" name="d_app" ${d.includes("app") ? "checked" : ""}></label>
    <label class="switch"><span><b>E-mail</b><div class="small muted">${mail ? "Designed e-mail with the full report" : "Not set up yet: run <code>make email-setup</code> on the PC once"}</div></span><input type="checkbox" name="d_email" ${d.includes("email") ? "checked" : ""}></label>
  </div>`;
}
const readDeliver = (f) => [f.d_telegram.checked && "telegram", f.d_app.checked && "app", f.d_email.checked && "email"].filter(Boolean);

function settingsForm(body, m) {
  const b = m.brief || {};
  body.innerHTML = `<form class="card pad-l" id="sf" autocomplete="off">
    <label class="field" style="margin-top:0"><span>Title</span><input class="input" name="title" value="${esc(m.title)}" maxlength="80"></label>
    ${m.workflow ? `<div class="field"><span>Schedule</span>${wfScheduleHtml(m.schedule_text, m.status === "active" ? m.next_run : null, m.workflow)}</div>` : schedHtml(m.schedule)}
    ${trigEditor(m.triggers)}
    ${m.type === "task" ? `<div class="card pad" style="margin-top:16px;padding-top:4px;padding-bottom:4px"><label class="switch"><span><b>Deep research</b><div class="small muted">Every run sets out 3–5 research steps, works through them, then combines the findings</div></span><input type="checkbox" name="deep" ${m.depth === "deep" ? "checked" : ""}></label></div>` : ""}
    <div class="field"><span>Cost</span><small style="font-size:13.5px">Runs only on your ChatGPT subscription: $0. If ChatGPT pauses the stack, runs wait and retry every 30 minutes.</small></div>
    ${deliverHtml(m.deliver || [])}
    ${m.type === "task" ? `<label class="field"><span>Goal</span><textarea class="input" name="goal" rows="7">${esc(m.goal)}</textarea></label>
      <label class="field"><span>Files it must deliver</span><textarea class="input" name="files" rows="3" placeholder="spec.md: the checkbox spec">${esc((m.files_asked || []).map((a) => a.name + (a.what ? ": " + a.what : "")).join("\n"))}</textarea>
        <small>One per line, “name.md: what it is”. Markdown, CSV, JSON or text. They show under Results and are attached to its e-mail; a run that does not save one is marked partial.</small></label>` : `
      <label class="field"><span>Key questions</span><textarea class="input" name="kq" rows="6">${esc((b.key_questions || []).join("\n"))}</textarea><small>One per line. The report follows this order.</small></label>
      <label class="field"><span>Google News searches</span><textarea class="input" name="search" rows="5">${esc((b.search || []).join("\n"))}</textarea><small>One search per line.</small></label>
      <label class="field"><span>Watchlist</span><textarea class="input" name="watch" rows="5">${esc((b.watchlist || []).map((w) => w.name + (w.symbol ? " | " + w.symbol : "")).join("\n"))}</textarea><small>“Name | ticker” (Yahoo), ticker optional.</small></label>
      <label class="field"><span>RSS feeds</span><textarea class="input" name="feeds" rows="3">${esc((b.feeds || []).join("\n"))}</textarea></label>
      <label class="field"><span>SEC filings in the daily report (US tickers)</span><input class="input" name="filings" value="${esc((b.filings || []).join(", "))}"></label>
      <label class="field"><span>Notes for the desk</span><textarea class="input" name="notes" rows="4">${esc(b.notes || "")}</textarea><small>Style and focus instructions, e.g. “explain jargon”, “skip penny stocks”.</small></label>`}
    <div class="form-foot"><button class="btn primary" type="submit">${ic.check}Save</button><a class="btn" href="#/chat?mission=${encodeURIComponent(m.slug)}">${ic.tune}Tune in chat instead</a></div>
  </form>`;
  const f = $("#sf");
  if (f.smode) bindSched(f);
  bindTrig(f);
  f.onsubmit = async (e) => {
    e.preventDefault();
    const sched = m.workflow ? null : readSched(f);                       // a workflow holds its schedule: the form leaves it
    if (!m.workflow && !sched) return toast("Choose at least one day", true);
    const fields = { title: f.title.value.trim(), ...(sched ? { schedule: sched } : {}), deliver: readDeliver(f), triggers: readTrig(f) };
    if (m.type === "task") { fields.goal = f.goal.value; fields.depth = f.deep.checked ? "deep" : "standard"; }
    else {
      fields.key_questions = lines(f.kq.value); fields.search = lines(f.search.value); fields.feeds = lines(f.feeds.value); fields.notes = f.notes.value;
      fields.filings = f.filings.value.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
      const old = Object.fromEntries((b.watchlist || []).map((w) => [w.name, w]));
      fields.watchlist = lines(f.watch.value).map((l) => { const [n, s] = l.split("|").map((x) => x.trim()); return { ...(old[n] || {}), name: n, symbol: s || undefined }; });
    }
    const btn = $("button[type=submit]", f); btn.disabled = true;
    const files = m.type === "task" && f.files ? lines(f.files.value).map((l) => { const i = l.indexOf(":"); return i > 0 ? { name: l.slice(0, i).trim(), what: l.slice(i + 1).trim() } : { name: l.trim() }; }) : null;
    if (files && JSON.stringify(files) !== JSON.stringify((m.files_asked || []).map((a) => (a.what ? { name: a.name, what: a.what } : { name: a.name })))
        && !(await act({ action: "files_asked", slug: m.slug, files }, null))) { btn.disabled = false; return; }   // a format it cannot make is refused, with why
    await act({ action: "update", slug: m.slug, fields }, (x) => `Saved ${(x.changed || []).concat(files && files.length !== (m.files_asked || []).length ? ["files"] : []).join(", ") || "it"}: the next run uses it`);
    btn.disabled = false;
  };
}

// ---------- chat: Hermes, with history on the server (Claude-style) ----------
let chats = [], cur = null, streaming = false, follower = null, pending = [], editing = null, chatQuery = "";
const LAST_CHAT = "mc-last-chat", chatScroll = {};       // APP-42: the chat you left, and where you were in each
const draftKey = () => `mc-draft-${cur?.id || route.q.get("mission") || "new"}`;
function saveDraft() {                                    // what you typed and attached waits for you, per chat, on this device
  if (editing !== null) return;
  const text = $("#cf")?.q.value || "";
  try { if (text || pending.length) localStorage.setItem(draftKey(), JSON.stringify({ text, pending })); else localStorage.removeItem(draftKey()); } catch (_) {}
}
function readDraft() { try { return JSON.parse(localStorage.getItem(draftKey())) || {}; } catch (_) { return {}; } }
let MODELS = null;
const pref = (k, d) => { try { return localStorage.getItem(k) || d; } catch (_) { return d; } };
const setPref = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
const EFFORT_LABEL = { low: "Low", medium: "Medium", high: "High", xhigh: "Extra high" };

async function loadChats() { try { chats = await api(`/api/chats${chatQuery ? "?q=" + encodeURIComponent(chatQuery) : ""}`); } catch (_) { chats = []; } }

function chatGroup(c, now = new Date()) {                 // the list's headings, by the day you last used a chat on this device's clock
  if (c.pinned) return "Pinned";
  const at = new Date(c.updated * 1000), start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime(), d = 86400000;
  return at.getTime() >= start ? "Today" : at.getTime() >= start - d ? "Yesterday" : at.getTime() >= start - 6 * d ? "Last 7 days" : "Earlier";
}
function chatListHtml() {
  const groups = { Pinned: [], Today: [], Yesterday: [], "Last 7 days": [], Earlier: [] }, auto = chats.filter((c) => c.origin && c.origin !== "owner");
  chats.filter((c) => !auto.includes(c)).forEach((c) => groups[chatGroup(c)].push(c));
  const when = (c) => (chatGroup({ updated: c.updated }) === "Today" ? clock(c.updated) : day(c.updated));
  const item = (c) => `<div class="citem ${cur?.id === c.id ? "on" : ""}">
    <a class="cmain" href="#/chat?c=${c.id}"><span class="cname">${c.pending ? '<span class="dot run"></span>' : ""}${c.mission ? `<span class="mtag">${ic.tune}</span>` : ""}<span class="cttl">${esc(c.title || "New chat")}</span></span>
      <span class="cmeta"><span class="clast"><span class="cwhen">${esc(when(c))}</span>${c.last ? ` · ${esc(c.last)}` : ""}</span>${madeIcons(c.made)}</span></a>
    <button type="button" class="cmore" data-cmore aria-label="More for this chat">${ic.more}</button>
    <div class="cacts" hidden><button type="button" data-pinchat="${c.id}" data-p="${c.pinned ? 1 : 0}">${c.pinned ? "Unpin" : "Pin"}</button><button type="button" class="err-t" data-delchat="${c.id}">Delete</button></div></div>`;
  const mine = Object.entries(groups).filter(([, l]) => l.length).map(([g, l]) => `<div class="cgroup">${g}</div>${l.map(item).join("")}`).join("");
  const tests = auto.length ? `<details class="cauto" data-keep="cauto"><summary class="cgroup">From tests and agents · ${auto.length}</summary><div class="tiny faint" style="padding:0 10px 6px">Sent by the stack's own checks and helper agents, not from your devices.</div>${auto.map(item).join("")}</details>` : "";
  return (mine || (!auto.length ? `<div class="small muted" style="padding:10px">${chatQuery ? "Nothing found." : "No chats yet."}</div>` : "")) + tests;
}

function askTwice(b) {                                    // asks for 4 seconds, then a tap is a first tap again
  const label = b.lastChild, was = label.textContent;
  b.dataset.sure = "1"; label.textContent = "Tap again to delete";
  setTimeout(() => { delete b.dataset.sure; label.textContent = was; }, 4000);
}
async function chatDelete(id) {
  await api(`/api/chats/${id}`, { method: "DELETE" });
  if (pref(LAST_CHAT, "") === id) setPref(LAST_CHAT, "");
  if (cur?.id === id) location.replace("#/chat?new=1"); else { await loadChats(); refreshList(); }
}
function chatDrawer(on) {
  const l = $("#clist");
  if (!l) return;
  l.classList.toggle("open", on); $("#cscrim").hidden = !on; document.body.classList.toggle("cdrawer", on);
}
const closeChatDrawer = () => (history.state?.drawer ? history.back() : chatDrawer(false));
const openChatDrawer = () => { chatDrawer(true); history.pushState({ ...(history.state || {}), drawer: 1 }, ""); };
// what a finished swipe means: right opens the list, left closes it; a mostly vertical move is a scroll, a short one nothing
function chatSwipe(dx, dy, open, width) {
  if (Math.abs(dy) > Math.abs(dx) || Math.abs(dx) < Math.min(70, width * 0.25)) return null;
  return !open && dx > 0 ? "open" : open && dx < 0 ? "close" : null;
}
function bindChatSwipe(wrap, list, scrim) {               // the drawer follows the finger, anywhere on the chat; code blocks and the box keep their own swipes
  let t = null;
  const end = () => { list.classList.remove("dragging"); list.style.transform = ""; scrim.style.opacity = ""; scrim.hidden = !list.classList.contains("open"); };
  wrap.addEventListener("touchstart", (e) => {
    t = e.touches.length !== 1 || String(getSelection()) || e.target.closest("pre, table, .cquick, textarea, input, select, .chatmenu, .madesheet") ? null
      : { x: e.touches[0].clientX, y: e.touches[0].clientY, open: list.classList.contains("open"), on: false };
  }, { passive: true });
  wrap.addEventListener("touchmove", (e) => {
    if (!t) return;
    const dx = e.touches[0].clientX - t.x, dy = e.touches[0].clientY - t.y, w = list.offsetWidth;
    if (!t.on) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      if (Math.abs(dy) > Math.abs(dx) || (dx > 0) === t.open) { t = null; return; }
      t.on = true; list.classList.add("dragging"); scrim.hidden = false;
    }
    const at = t.open ? Math.min(0, dx) : Math.max(-w, Math.min(0, dx - w));
    list.style.transform = `translateX(${at}px)`; scrim.style.opacity = String(1 + at / w);
    t.dx = dx; t.dy = dy;
  }, { passive: true });
  wrap.addEventListener("touchend", () => {
    if (!t?.on) { t = null; return; }
    const what = chatSwipe(t.dx || 0, t.dy || 0, t.open, list.offsetWidth);
    t = null; end();
    if (what === "open") openChatDrawer(); else if (what === "close") closeChatDrawer();
  });
  wrap.addEventListener("touchcancel", () => { if (t?.on) end(); t = null; });
}
window.addEventListener("popstate", () => { if (!history.state?.drawer) chatDrawer(false); });   // the phone's Back closes the drawer first

function refreshList() { if ($("#citems")) { $("#citems").innerHTML = chatListHtml(); bindChatList(); } }

function bindChatList() {
  $$("[data-cmore]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); const a = b.nextElementSibling; a.hidden = !a.hidden; }));
  $$("[data-delchat]").forEach((b) => (b.onclick = async (e) => {
    e.preventDefault(); e.stopPropagation();
    if (!b.dataset.sure) { askTwice(b); return; }        // two taps, in place: no system dialog over the chat
    await chatDelete(b.dataset.delchat);
  }));
  $$("[data-pinchat]").forEach((b) => (b.onclick = async (e) => {
    e.preventDefault(); e.stopPropagation();
    await api(`/api/chats/${b.dataset.pinchat}`, { method: "PATCH", body: JSON.stringify({ pinned: b.dataset.p !== "1" }) });
    if (cur?.id === b.dataset.pinchat) cur.pinned = b.dataset.p !== "1";
    await loadChats(); refreshList();
  }));
  $$(".citem .cmain, .chatlist [data-newchat]").forEach((a) => (a.onclick = (e) => {   // from the drawer: the drawer's step in the history makes way, so Back returns to the chat you came from
    if (!history.state?.drawer) return;
    e.preventDefault();
    const to = a.getAttribute("href");
    if (to === location.hash) history.back(); else location.replace(to);
  }));
}

function selectHtml() {
  const model = pref("mc-model", "gpt-sub"), effort = pref("mc-effort", "medium");
  return `<select class="pick" id="pmodel" title="Model">${(MODELS?.models || []).map((m) => `<option value="${m.id}" ${m.id === model ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select>
    <select class="pick" id="peffort" title="Reasoning effort">${(MODELS?.efforts || []).map((e) => `<option value="${e}" ${e === effort ? "selected" : ""}>${EFFORT_LABEL[e] || e}</option>`).join("")}</select>`;
}

function toolsHtml(tools, live) {
  if (!tools?.length) return "";
  const ev = tools.map((t, i) => ({ id: "c" + i, kind: t.status === "error" ? "error" : "call", title: t.name, detail: t.detail || "", status: t.status }));   // the agent log, without times
  return `<details class="tools" ${live ? "open" : ""}><summary>${live ? '<span class="spin" style="width:12px;height:12px;vertical-align:-1px"></span> ' : ""}${live ? "Working" : "Worked"} through ${tools.length} step${tools.length > 1 ? "s" : ""}</summary>${logHtml(ev, { bare: true, level: "all", cls: "chatlog" })}</details>`;
}
function reasoningHtml(r, live) {
  return r ? `<details class="tools"${live ? " open" : ""}><summary>Thinking</summary><div class="small muted" style="white-space:pre-wrap;margin-top:6px">${esc(r)}</div></details>` : "";
}
function attsHtml(atts) {
  if (!atts?.length) return "";
  return `<div class="atts">${atts.map((a) => a.kind === "image"
    ? `<a href="/api/chat/files/${a.id}" target="_blank"><img src="/api/chat/files/${a.id}" alt="${esc(a.name)}"></a>`
    : `<a class="attdoc" href="/api/chat/files/${a.id}" target="_blank">${ic.doc}<span class="wrap">${esc(a.name)}</span></a>`).join("")}</div>`;
}
const modelName = (id) => (MODELS?.models || []).find((m) => m.id === id)?.name || id;

// ---------- APP-39: what a chat made (docs/CHAT-MADE.md): a card under the message that made it, the Made here sheet, the way back ----------
const MADE_IC = { mission: "rocket", build: "code", claude: "brain", repo: "layers", note: "doc", email: "send" };
const MADE_KIND = { mission: "Workflow", build: "Build", claude: "Claude question", repo: "Repository", note: "Note in the vault", email: "E-mail" };
const MADE_STATE = { creating: ["queued", "Being created"], queued: ["queued", "Queued"], running: ["running", "Running"], done: ["ok", "Done"],
  waits: ["paused", "Waits for you"], failed: ["failed", "Failed"], paused: ["paused", "Paused"], sent: ["ok", "Sent"], made: ["ok", "Made"],
  gone: ["archived", "No longer there"] };
const MADE_OPEN = ["creating", "queued", "running"];
const madeIc = (k) => ic[MADE_IC[k]] || ic.doc;
const madeCount = (made) => (made || []).filter((x) => x.verb !== "changed" && x.verb !== "failed").length;

function madeCard(x) {
  if (x.verb === "changed") return `<div class="madeline tiny muted">${madeIc(x.kind)}<span>${x.href ? `<a href="${x.href}">${esc(x.name || x.id)}</a>` : esc(x.name || x.id || "")}: ${esc(x.what || "changed")}</span></div>`;
  const [cls, label] = MADE_STATE[x.state] || ["archived", x.state || ""];
  const inner = `<span class="mc-ic">${madeIc(x.kind)}</span><span class="grow mc-body"><span class="tiny faint">${esc(MADE_KIND[x.kind] || x.kind)}${x.verb === "exists" ? " · already existed" : ""}</span>
    <b class="wrap mc-name">${esc(x.name || x.id || "…")}</b>${x.line ? `<span class="small muted mc-line" title="${esc(x.line)}">${esc(x.line)}</span>` : ""}</span>
    ${label ? `<span class="pill ${cls}">${x.state === "running" ? '<span class="dot run"></span>' : ""}${label}</span>` : ""}${x.href ? ic.next : ""}`;
  const files = (x.files || []).length || (x.files_missing || []).length    // MIS-23: the files it made, each one tap away
    ? `<div class="mc-files">${(x.files || []).map((f) => `<a class="tag" href="${f.href}">${ic.doc}${esc(f.name)}</a>`).join("")}${(x.files_missing || []).map((n) => `<span class="tag warn" title="Asked for, not delivered yet">${esc(n)}</span>`).join("")}</div>` : "";
  return x.href ? `<div class="madewrap"><a class="madecard" data-mk="${x.key}" href="${x.href}">${inner}</a>${files}</div>` : `<div class="madecard" data-mk="${x.key}">${inner}</div>`;
}

// each item under the answer of the turn that made it; one whose turn was edited away is only in the Made here sheet
function madeByMsg(msgs, made) {
  const out = {};
  for (const x of made || []) {
    const j = msgs.findIndex((m) => m.role === "assistant" && !m.note && (m.ts || 0) >= x.ts);
    if (j < 0) continue;
    let u = j - 1;
    while (u >= 0 && msgs[u].role !== "user") u--;
    if (u >= 0 && (msgs[u].ts || 0) > x.ts) continue;
    (out[j] = out[j] || []).push(x);
  }
  return out;
}

function drawMade() {
  if (!cur) return;
  const by = madeByMsg(cur.messages || [], cur.made);
  $$("[data-mi]").forEach((el) => (el.innerHTML = (by[+el.dataset.mi] || []).map(madeCard).join("")));
  const chip = $("#madechip"), n = madeCount(cur.made);
  if (!chip) return;
  chip.hidden = !n;
  chip.innerHTML = `${ic.layers}<span class="ml">Made here · </span>${n}`;
  const items = [...(cur.made || [])].reverse();
  $("#madesheet").innerHTML = `<div class="row between" style="align-items:center"><b>Made in this chat</b><span class="tiny faint">newest first</span></div>
    ${items.filter((x) => x.verb !== "changed").map(madeCard).join("")}
    ${items.some((x) => x.verb === "changed") ? `<div class="tiny faint" style="margin-top:4px">Changed here</div>${items.filter((x) => x.verb === "changed").map(madeCard).join("")}` : ""}`;
}

// while something it made is still on its way, the chat looks again every 15 s: states, and the line when it ends
let madeTimer = null;
function watchMade() {
  clearInterval(madeTimer);
  madeTimer = setInterval(async () => {
    if (route.name !== "chat" || !cur?.id) return clearInterval(madeTimer);
    if (streaming || document.hidden || !(cur.made || []).some((x) => MADE_OPEN.includes(x.state) || (x.kind === "build" && x.state === "waits"))) return;
    const id = cur.id, full = await api(`/api/chats/${id}`).catch(() => null);
    if (!full?.messages || cur?.id !== id || streaming) return;
    const more = full.messages.length !== (cur.messages || []).length;
    cur = full;
    if (more) { const b = $("#msgs"); b.innerHTML = ""; full.messages.forEach((x, i) => b.insertAdjacentHTML("beforeend", bubble(x, i))); codeCopy(b); bindMsgActions(); scrollChat(); }
    drawMade();
  }, 15000);
}

// on the page of something a chat made: the way back to the turn that made it
function fromChat(key) {
  const f = S?.from_chat?.[key];
  return f ? `<a class="fromchat small" href="#/chat?c=${encodeURIComponent(f.chat)}&made=${f.key}">${ic.chat}<span class="wrap">From a chat: <b>${esc(f.title)}</b></span></a>` : "";
}

function madeIcons(made) {
  const e = Object.entries(made || {});
  return e.length ? `<span class="cmade">${e.map(([k, n]) => `<span title="${n} × ${esc(MADE_KIND[k] || k)} made here">${madeIc(k)}${n > 1 ? n : ""}</span>`).join("")}</span>` : "";
}

function bubble(x, i) {
  if (x.note) return `<div class="mrow note" data-i="${i}"><div class="msgnote">${ic.bell}<div class="md grow">${md(x.content)}</div></div></div>`;
  if (x.role === "user") {
    return `<div class="mrow user" data-i="${i}"><div class="msg user">${attsHtml(x.attachments)}${x.content && x.content !== "(see attachment)" ? `<div class="utext">${esc(x.content)}</div>` : ""}</div>
      <div class="macts"><button data-copy="${i}" title="Copy" aria-label="Copy">${ic.copy}</button><button data-edit="${i}" title="Edit and resend" aria-label="Edit and resend">${ic.edit}</button></div></div>`;
  }
  return `<div class="mrow assistant" data-i="${i}"><div class="msg assistant">${toolsHtml(x.tools)}${reasoningHtml(x.reasoning)}<div class="md">${md(x.content)}</div>${x.limit ? limitHtml(x) : ""}<div class="madecards" data-mi="${i}"></div></div>
    <div class="macts"><button data-copy="${i}" title="Copy" aria-label="Copy">${ic.copy}</button><button data-regen="${i}" title="Regenerate" aria-label="Regenerate">${ic.repeat}</button>${x.model ? `<span class="tiny faint">${esc(modelName(x.model))}${x.effort ? " · " + esc(x.effort) : ""}</span>` : ""}</div></div>`;
}

// AST-12: a message that waits for the subscription's usage limit says when it is tried again, in this device's time
function limitHtml(x) {
  const at = new Date(x.limit.retry_at * 1000), other = at.toDateString() !== new Date().toDateString();
  return `<div class="limitnote tiny"><span>${x.limit.reset_known ? "The limit resets" : "Next try"} at <b>${clock(at)}</b>${other ? " on " + esc(day(at, true)) : ""}</span>
    <button class="btn sm ghost" data-retrynow>${ic.repeat}Try now</button></div>${x.detail ? `<details class="limitdetail tiny faint"><summary>What the subscription answered</summary><pre>${esc(x.detail)}</pre></details>` : ""}`;
}

function codeCopy(root) {
  $$(".md pre", root).forEach((pre) => {
    if (pre.querySelector(".ccopy")) return;
    const b = document.createElement("button");
    b.className = "ccopy"; b.textContent = "Copy";
    b.onclick = async () => { if (await copyText(pre.querySelector("code")?.innerText || pre.innerText)) { b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1500); } };
    pre.appendChild(b);
  });
}

async function vChat() {
  let cid = route.q.get("c");
  const mslug = route.q.get("mission");
  if (!cid && !mslug && !route.q.get("new") && !route.q.get("prompt") && !route.q.get("share") && (cid = pref(LAST_CHAT, ""))) {   // APP-42: the Chat tab opens the chat you left
    history.replaceState(history.state, "", `#/chat?c=${cid}`); route.q = new URLSearchParams(`c=${cid}`);
  }
  if (!MODELS) MODELS = await api("/api/models").catch(() => ({ models: [{ id: "gpt-sub", name: "GPT-6.1 Sol" }], efforts: ["medium"] }));
  await loadChats();
  cur = cid ? await api(`/api/chats/${cid}`).catch(() => null) : null;
  if (route.name !== "chat") return;
  if (cur?.error) {                                      // deleted elsewhere: not an error to show, a new chat instead (a lost connection keeps it for next time)
    if (pref(LAST_CHAT, "") === cid) setPref(LAST_CHAT, "");
    cur = null; history.replaceState(history.state, "", "#/chat?new=1"); route.q = new URLSearchParams("new=1");
  }
  if (cur?.id) setPref(LAST_CHAT, cur.id);
  editing = null;
  const draft = readDraft();
  pending = draft.pending || [];
  const mis = mslug || cur?.mission;
  const m = mis && S ? S.missions.find((x) => x.slug === mis) : null;
  const sugg = m ? [`What does this workflow track right now?`, `Make it focus more on `, `Add a key question about `, `Alert me when ${m.brief?.filings?.[0] || "the company"} files with the SEC`]
    : ["What are my agents doing?", "What changed in my repositories this week?", "Research a company and e-mail me an analysis", "Watch a share and tell me if it moves 8 % in a day"];
  view.innerHTML = `<div class="chatwrap">
    <div class="cscrim" id="cscrim" hidden></div>
    <aside class="chatlist" id="clist" aria-label="Your chats">
      <div class="clhead"><b>Chats</b><button type="button" class="icon-btn clclose" id="clclose" aria-label="Close">${ic.x}</button></div>
      <a class="btn primary cnew" href="#/chat?new=1" data-newchat>${ic.compose}New chat</a>
      <div class="wsearch clsearch">${ic.search}<input class="input" id="cq" placeholder="Search chats" value="${esc(chatQuery)}"></div>
      <div id="citems" class="citems">${chatListHtml()}</div>
    </aside>
    <div class="chatpane">
      <div class="chathead">
        <button class="icon-btn hist" id="histbtn" title="Chats" aria-label="Your chats">${ic.menu}</button>
        <div class="chatti">
          <h1 class="grow wrap" id="ctitle">${m ? "Tune: " + esc(m.title) : cur ? esc(cur.title) : "New chat"}</h1>
          <div class="chatstat">
            <button type="button" id="madechip" class="chip madechip" title="What this chat made: missions, builds, Claude tasks, notes" hidden></button>
            <span id="chatchip" class="chip chatchip" hidden></span>
          </div>
        </div>
        ${cur ? `<button type="button" class="icon-btn cmenu" id="cmenubtn" aria-label="More for this chat" aria-expanded="false">${ic.more}</button>` : ""}
      </div>
      ${cur ? `<div class="chatmenu card" id="chatmenu" hidden>
        <button type="button" data-cm="rename">${ic.edit}Rename</button>
        <button type="button" data-cm="pin">${ic.target}${cur.pinned ? "Unpin" : "Pin"}</button>
        <a href="#/live/${encodeURIComponent("chat:" + cur.id)}">${ic.pulse}What Hermes did</a>
        <button type="button" class="err-t" data-cm="delete">${ic.trash}Delete</button>
      </div>` : ""}
      <div class="madesheet card" id="madesheet" hidden></div>
      ${m ? `<div class="banner info" style="margin:0 0 10px">${ic.tune}<span class="grow small">Focus chat for <b>${esc(m.title)}</b>: say what to track more or less; it changes the workflow.</span></div>` : ""}
      <div class="msgs" id="msgs">${(cur?.messages || []).length ? "" : `<div class="empty-chat"><h2 class="chello">What can I do for you?</h2><div class="suggest">${sugg.map((x) => `<button type="button">${esc(x)}</button>`).join("")}</div></div>`}</div>
      <div class="tobwrap"><button type="button" class="tobottom" id="tobottom" aria-label="Go to the newest message" hidden>${ic.down}</button></div>
      <div class="cquick" id="cquick">
        <label class="qchip">${ic.image}Screenshot or photo<input type="file" id="cphoto" accept="image/*" multiple hidden></label>
        <label class="qchip">${ic.camera}Camera<input type="file" id="ccam" accept="image/*" capture="environment" hidden></label>
        ${navigator.clipboard?.read ? `<button type="button" class="qchip" id="cpaste">${ic.paste}Paste</button>` : ""}
      </div>
      <form class="composer2" id="cf">
        <div class="pend" id="pend"></div>
        <div class="editing" id="editbar" hidden>Editing a message <button type="button" class="btn sm ghost" id="canceledit">Cancel</button></div>
        <textarea class="input" name="q" rows="1" placeholder="Message Hermes…" enterkeyhint="send"></textarea>
        <div class="crow">
          <label class="icon-btn" title="Attach pictures or documents" aria-label="Attach pictures or documents">${ic.clip}<input type="file" id="cfile" multiple hidden accept="image/*,.pdf,.docx,.xlsx,.csv,.txt,.md,.json,.html,.py,.js,.ts,.yaml,.yml,.log"></label>
          ${selectHtml()}
          <span class="grow"></span>
          <button class="btn primary sendbtn" type="submit" id="sendbtn" aria-label="Send">${ic.up}</button>
        </div>
      </form>
    </div>
  </div>`;
  mirrorChip();
  const box = $("#msgs");
  (cur?.messages || []).forEach((x, i) => box.insertAdjacentHTML("beforeend", bubble(x, i)));
  codeCopy(box);
  bindMsgActions();
  drawMade(); watchMade();
  $("#madechip").onclick = (e) => {                      // the sheet opens under the header, however many lines its title takes
    e.stopPropagation();
    const sh = $("#madesheet"), head = $(".chathead");
    sh.style.top = head.offsetTop + head.offsetHeight + 4 + "px"; sh.hidden = !sh.hidden;
  };
  view.onclick = (e) => {
    const sh = $("#madesheet"), cm = $("#chatmenu");
    if (sh && !sh.hidden && !sh.contains(e.target)) sh.hidden = true;
    if (cm && !cm.hidden && !cm.contains(e.target)) cm.hidden = true;
  };
  const f = $("#cf"), ta = f.q, cpane = $(".chatpane");
  const canSend = () => $("#sendbtn").classList.toggle("idle", !streaming && !ta.value.trim() && !pending.length);
  ta.oninput = () => { ta.style.height = "auto"; ta.style.height = Math.min(180, ta.scrollHeight) + "px"; saveDraft(); canSend(); };
  const pane = $("#msgs");                               // APP-40: the keyboard opens or closes: the newest message stays in sight
  const scrollKey = cur?.id || "";
  let atEnd = true;
  pane.addEventListener("scroll", () => {
    atEnd = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 60;
    $("#tobottom").hidden = atEnd;
    if (atEnd) delete chatScroll[scrollKey]; else chatScroll[scrollKey] = pane.scrollTop;
  }, { passive: true });
  $("#tobottom").onclick = () => pane.scrollTo({ top: pane.scrollHeight, behavior: "smooth" });
  pane.onclick = (e) => {                                // APP-45: a message's actions, on a tap: they do not sit under every message
    if (e.target.closest("a, button, summary, pre, img") || String(getSelection())) return;
    const row = e.target.closest(".mrow");
    if (!row) return;
    const was = row.classList.contains("show");
    $$(".mrow.show", pane).forEach((r) => r.classList.remove("show"));
    row.classList.toggle("show", !was);
  };
  new ResizeObserver(() => { if (atEnd) pane.scrollTop = pane.scrollHeight; }).observe(pane);
  ta.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer:coarse)").matches) { e.preventDefault(); f.requestSubmit(); } };
  $$(".suggest button").forEach((b) => (b.onclick = () => { ta.value = b.textContent; ta.focus(); if (!b.textContent.endsWith(" ")) f.requestSubmit(); }));
  $("#histbtn").onclick = openChatDrawer;
  if (matchMedia("(max-width: 959px)").matches) bindChatSwipe($(".chatwrap"), $("#clist"), $("#cscrim"));
  if (history.state?.drawer) history.replaceState({ ...history.state, drawer: 0 }, "");   // a page drawn afresh has its drawer closed
  $("#cscrim").onclick = closeChatDrawer;
  $("#clclose").onclick = closeChatDrawer;
  const menu = $("#chatmenu"), menuBtn = $("#cmenubtn");
  const showMenu = (on) => { if (menu) { menu.hidden = !on; menuBtn.setAttribute("aria-expanded", on); } };
  if (menu) {
    menuBtn.onclick = (e) => { e.stopPropagation(); showMenu(menu.hidden); };
    $("#ctitle").onclick = (e) => { e.stopPropagation(); showMenu(menu.hidden); };   // the title is the chat's menu, as in other chat apps
    menu.onclick = async (e) => {
      const b = e.target.closest("[data-cm]");
      if (!b) return;
      e.stopPropagation();
      if (b.dataset.cm === "rename") { showMenu(false); renameChat(); }
      if (b.dataset.cm === "pin") {
        await api(`/api/chats/${cur.id}`, { method: "PATCH", body: JSON.stringify({ pinned: !cur.pinned }) });
        cur.pinned = !cur.pinned; showMenu(false); render(true);
      }
      if (b.dataset.cm === "delete") {
        if (!b.dataset.sure) { askTwice(b); return; }
        await chatDelete(cur.id);
      }
    };
  }
  const renameChat = () => {                             // in place, no system dialog
    const h = $("#ctitle"), was = cur.title || "";
    h.innerHTML = `<input class="input ctitlein" maxlength="120" aria-label="Chat title" value="${esc(was)}">`;
    const inp = h.firstChild;
    h.onclick = (e) => e.stopPropagation();
    inp.focus(); inp.select();
    let done = false;
    const end = async (save) => {
      if (done) return;
      done = true;
      const t = inp.value.trim();
      h.textContent = save && t ? t : was;
      h.onclick = (e) => { e.stopPropagation(); showMenu(menu.hidden); };
      if (save && t && t !== was) { await api(`/api/chats/${cur.id}`, { method: "PATCH", body: JSON.stringify({ title: t }) }); cur.title = t; await loadChats(); refreshList(); }
    };
    inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); end(true); } if (e.key === "Escape") end(false); };
    inp.onblur = () => end(true);
  };
  $("#pmodel").onchange = (e) => setPref("mc-model", e.target.value);
  $("#peffort").onchange = (e) => setPref("mc-effort", e.target.value);
  $("#cq").oninput = async (e) => { chatQuery = e.target.value.trim(); await loadChats(); refreshList(); };
  const pendChip = (r, chip = document.createElement("span")) => {
    chip.className = "pchip";
    chip.innerHTML = `${r.kind === "image" ? `<img src="/api/chat/files/${r.id}" alt="">` : ic.doc} <span class="wrap">${esc(r.name)}</span><button type="button" title="Remove" aria-label="Remove ${esc(r.name)}">${ic.x}</button>`;
    chip.querySelector("button").onclick = () => { pending = pending.filter((p) => p.id !== r.id); chip.remove(); saveDraft(); canSend(); };
    return chip;
  };
  const uploadFiles = async (files) => {                 // the clip, the row above the keyboard, a paste and a drop all come here
    for (const file of files) {
      const chip = document.createElement("span"); chip.className = "pchip"; chip.innerHTML = `<span class="spin" style="width:12px;height:12px"></span> ${esc(file.name)}`;
      $("#pend").appendChild(chip);
      try {
        const r = await fetch("/api/chat/upload", { method: "POST", body: file, headers: { "X-Filename": file.name } }).then((x) => x.json());
        if (r.error) throw new Error(r.error);
        pending.push(r);
        pendChip(r, chip);
        saveDraft(); canSend();
      } catch (err) { chip.remove(); toast(`${file.name}: ${err.message}`, true); }
    }
  };
  for (const a of pending) $("#pend").appendChild(pendChip(a));
  if (draft.text && !route.q.get("prompt")) { ta.value = draft.text; ta.oninput(); }
  canSend();
  ["cfile", "cphoto", "ccam"].forEach((id) => ($("#" + id).onchange = async (e) => { await uploadFiles([...e.target.files]); e.target.value = ""; }));
  // APP-44: a web page cannot look through your photos unasked, so the way to them sits above the keyboard, one tap away
  cpane.classList.toggle("cempty", !(cur?.messages || []).length);
  ta.onfocus = () => cpane.classList.add("cfocus");
  ta.onblur = () => setTimeout(() => { if (document.activeElement !== ta) cpane.classList.remove("cfocus"); }, 150);
  $("#cquick").onpointerdown = (e) => e.preventDefault();   // a tap on the row keeps the keyboard up
  const named = (blob, i = 0) => new File([blob], blob.name || `screenshot${i ? "-" + (i + 1) : ""}.${(blob.type.split("/")[1] || "png").split("+")[0]}`, { type: blob.type });
  if ($("#cpaste")) $("#cpaste").onclick = async () => {
    try {
      const shots = [];
      for (const it of await navigator.clipboard.read()) {
        const t = it.types.find((x) => x.startsWith("image/"));
        if (t) shots.push(named(await it.getType(t), shots.length));
      }
      if (shots.length) await uploadFiles(shots); else toast("No picture on the clipboard: copy a screenshot first, or use Screenshot or photo", true);
    } catch (err) { toast("The browser did not allow reading the clipboard: use Screenshot or photo", true); }
  };
  ta.onpaste = (e) => {                                  // a keyboard's clipboard and Ctrl+V: a picture is attached, text is pasted as usual
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); uploadFiles(files.map(named)); }
  };
  cpane.ondragover = (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); cpane.classList.add("cdrop"); } };
  cpane.ondragleave = (e) => { if (!cpane.contains(e.relatedTarget)) cpane.classList.remove("cdrop"); };
  cpane.ondrop = (e) => { e.preventDefault(); cpane.classList.remove("cdrop"); uploadFiles([...(e.dataTransfer?.files || [])]); };
  $("#canceledit").onclick = () => { editing = null; $("#editbar").hidden = true; ta.value = readDraft().text || ""; ta.oninput(); };
  bindChatList();
  f.onsubmit = (e) => {
    e.preventDefault();
    if (streaming) return stopChat();
    const q = ta.value.trim();
    if (!q && !pending.length) return;
    const trunc = editing;
    try { localStorage.removeItem(draftKey()); } catch (_) {}
    ta.value = ""; ta.style.height = ""; editing = null; $("#editbar").hidden = true;
    send(q, mis, trunc);
  };
  if (cur?.pending) follow(cur.id);
  const pre = route.q.get("prompt");                     // from a guide example or a share: typed in, not sent
  const shared = route.q.get("share") ? await api(`/api/share/${route.q.get("share")}`).catch(() => null) : null;
  for (const a of shared?.files || []) {                  // what the phone shared comes along as attachments
    pending.push(a);
    $("#pend").appendChild(pendChip(a));
  }
  canSend();
  if ((pre || shared) && !cur) { ta.value = pre || ""; ta.oninput(); ta.focus(); history.replaceState(history.state, "", mslug ? `#/chat?mission=${encodeURIComponent(mslug)}` : "#/chat?new=1"); route.q = new URLSearchParams(mslug ? `mission=${encodeURIComponent(mslug)}` : "new=1"); saveDraft(); canSend(); }
  if (route.q.get("send") && (pre || pending.length) && !cur) f.requestSubmit();
  const back = route.q.get("made") && $(`.madecards [data-mk="${CSS.escape(route.q.get("made"))}"]`);   // "From a chat": the turn that made it
  if (back) { back.scrollIntoView({ block: "center" }); back.classList.add("flash"); }
  else if (chatScroll[scrollKey] && !cur?.pending) pane.scrollTop = chatScroll[scrollKey];   // APP-42: where you were; the newest message when you were at the end
  else scrollChat(true);
}

