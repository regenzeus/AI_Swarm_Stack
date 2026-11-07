// Mission Control guide: chapters from /api/guide (images/mission-control/guide/*.md), rendered with live blocks
// (```live <name>```: read from the running stack) and "Try it" cards (```try```: open a view, prefill a chat, open an app).
// Reading progress and tried examples are kept per device. Loaded before app.js; uses its helpers at call time.
"use strict";

let GUIDE = null, GLIVE = null, guideQuery = "";
const GPARTS = ["Get started", "Everyday use", "Knowledge", "Building", "Under the hood"];

const gp = (() => { try { return JSON.parse(localStorage.getItem("mc-guide")) || {}; } catch (_) { return {}; } })();
gp.read = gp.read || {}; gp.tried = gp.tried || {};
const gsave = () => { try { localStorage.setItem("mc-guide", JSON.stringify(gp)); } catch (_) {} };

async function loadGuide() {
  if (!GUIDE) GUIDE = await api("/api/guide?full=1").catch(() => null);
  if (!GLIVE) GLIVE = await api("/api/guide/live").catch(() => null);
  return GUIDE || [];
}
const gicon = (n) => ic[n] || ic.doc;
const chapterFor = (name) => (GUIDE || []).find((c) => (c.views || []).includes(name));
const totalTries = () => (GUIDE || []).reduce((a, c) => a + c.tries, 0);
const triedIn = (c) => Object.keys(gp.tried).filter((k) => k.startsWith(c.id + "#")).length;

// ---------- markdown with try / live blocks ----------
function parseTry(src) {
  const t = {};
  src.split("\n").forEach((ln) => { const m = ln.match(/^(\w+):\s*(.*)$/); if (m) t[m[1]] = m[2].replace(/^"(.*)"$/, "$1"); });
  return t;
}
function guideHtml(c) {
  const tries = [];
  let body = c.body.replace(/^```try\n([\s\S]*?)\n```$/gm, (_, src) => { tries.push(parseTry(src)); return `\n<div class="gtry" data-try="${tries.length - 1}"></div>\n`; })
    .replace(/^```live\n\s*([\w-]+)\s*\n```$/gm, (_, name) => `\n<div class="glive" data-live="${name}"></div>\n`);
  return { html: md(body), tries };
}
const firstMission = () => (S?.missions || []).filter((m) => m.status === "active").sort((a, b) => (a.type === "briefing" ? -1 : 1) - (b.type === "briefing" ? -1 : 1))[0];

function tryCard(c, t, i) {
  const key = `${c.id}#${i}`, done = gp.tried[key];
  let href = "#/", ext = false, kind = "Open", icon = ic.next;
  if (t.chat) { href = `#/chat?prompt=${encodeURIComponent(t.chat)}`; kind = "Try in chat"; icon = ic.chat; }
  else if (t.open) {
    const m = firstMission();
    href = t.open.includes("{mission}") ? (m ? t.open.replace("{mission}", encodeURIComponent(m.slug)) : "#/missions") : t.open;
  } else if (t.app) { href = `${HOSTURL}${t.app === "443" ? "" : ":" + t.app}/`; ext = true; kind = "Open app"; icon = ic.next; }
  return `<div class="tcard ${done ? "done" : ""}">
    <div class="tc-h"><span class="tc-badge">${done ? ic.check : ic.play}${done ? "Tried" : "Try it"}</span><b class="grow">${esc(t.label)}</b></div>
    ${t.chat ? `<div class="tc-prompt">${ic.chat}<span>${esc(t.chat)}</span></div>` : ""}
    ${t.note ? `<div class="tc-note small muted">${esc(t.note)}</div>` : ""}
    <div class="tc-foot"><a class="btn sm ${done ? "" : "primary"}" data-tried="${key}" href="${esc(href)}"${ext ? ' target="_blank" rel="noopener"' : ""}>${icon}${kind}</a>
      ${t.chat ? `<span class="tiny faint">Typed in for you, not sent: you press send.</span>` : ""}</div>
  </div>`;
}

// ---------- live blocks ----------
const svcState = (name) => {
  const s = (S?.system?.services || []).find((x) => x.name === name || x.name.endsWith("-" + name) || x.name.replace(/-\d+$/, "").endsWith(name));
  return !s ? "" : s.state !== "running" ? "err" : /unhealthy/.test(s.status) ? "warn" : "ok";
};
// the live map: every part of the stack; tapping one opens its details right under its row (archInfoHtml)
// [name, short, service (or "@runner" / null), chapter, section, longer explanation, app port or in-app route]
const ARCH = [
  ["You", [
    ["Phone & PC", "Mission Control app, push", null, "first-ten-minutes", "5. Put it on your phone", "This app, installed on your phone and PC. Everything here is reachable only from your own devices over Tailscale."],
    ["Telegram", "chat, briefings, digest", null, "delivery", "Telegram", "Hermes on Telegram: chat with it there, get briefings with buttons into this app, and the morning digest."]]],
  ["Front doors", [
    ["Mission Control", "this app + its tools", "mission-control", "welcome", "The app at a glance", "This app and its API, plus the tools Hermes uses to manage missions, builds and repositories. It never runs jobs itself: the runner does.", "#/"],
    ["Open WebUI", "classic chat", "openwebui", "technology", "Tools you can open", "A classic chat interface to Hermes. You are signed in through your Tailscale login.", "443"],
    ["Hermes admin", "skills, sessions, logs", "hermes-dashboard", "technology", "Tools you can open", "Hermes' own dashboard: its skills, sessions, logs and settings. No password: your Tailscale login lets you in.", "8448"],
    ["OpenCode", "code editor", "opencode", "code", "The other code tools", "A coding app in the browser for hands-on changes to your repositories.", "8445"],
    ["Sign-in gate", "your Tailscale login, no passwords", "gate-hermes-dashboard", "safety", "Private by default", "Single sign-in: a small gate in front of the apps that have their own login (Hermes admin, the code map). It lets in only requests carrying your Tailscale login, so there are no passwords or tokens to remember."]]],
  ["Agents", [
    ["Hermes", "main · scout · curator · mission", "hermes", "chat", "What Hermes can do here", "Your assistant, in four roles: main (chat, Telegram), scout (the only one on the web), curator (tidies the knowledge weekly) and mission (works on long-term tasks).", "#/chat"],
    ["Runner", "schedules, triggers, builds", "@runner", "missions", "Two kinds of missions", "The one place that runs jobs: mission schedules and triggers, deep research, builds and deploys, the weekly self-review and resource monitoring.", "#/missions"],
    ["Topic Desk", "writes briefings", null, "missions", "Two kinds of missions", "Writes the daily briefings: reads news, filings and prices for a topic and files a report. Runs on demand, so it has no status dot."],
    ["Builder", "codes in a sandbox", "builder", "builder", "The flow", "The coding agent (ChatGPT via Hermes, or Claude Code) in a sandbox: no secrets, no deploy rights. You review and tap to deploy.", "#/build"]]],
  ["Gateway", [
    ["LiteLLM", "every model call, keys, tools", "litellm", "technology", "The layers", "Every model call of every agent goes through here: per-agent keys and limits, tool access, cost tracking. Subscription models only."],
    ["Phoenix", "traces", "phoenix", "technology", "Tools you can open", "A trace of every model call: what was asked, which tools ran, how long it took.", "8443"]]],
  ["Knowledge & tools", [
    ["Vault search", "qmd", "qmd", "knowledge", "The vault", "Searches your vault, reports, wikis and code summaries by keywords and by meaning. Hermes uses it before answering.", "#/wiki"],
    ["Memory", "Hindsight", "hindsight", "knowledge", "Long-term memory", "Remembers lasting facts about you from conversations, with your approval for the important ones. Runs local models."],
    ["Research", "scout + page reader", "fetch", "deep-research", "Who reads the web", "Web research: a privacy check, then the scout searches, then an isolated reader opens pages and PDFs. Results are marked as untrusted."],
    ["Code graph", "Graphify", "graphify", "code", "A repository's page", "Graphs of your repositories' code (what calls and contains what), kept current within a minute of each commit.", "#/build"]]],
  ["Outside the PC", [
    ["ChatGPT", "subscription, $0", null, "safety", "$0, guaranteed", "The models behind Hermes and the default builder, on your ChatGPT subscription. Usage limits make jobs wait, never cost money."],
    ["NAS", "git, CI, backups", null, "stack-page", "Scheduled jobs", "Your Synology: Forgejo (git and CI) and the nightly encrypted backups."],
    ["Tailscale", "private network", null, "safety", "Private by default", "The private network between your devices and the PC. Your Tailscale login is the only sign-in."]]],
];
const ARCH_FLAT = ARCH.flatMap(([, nodes]) => nodes);
let archOpen = null;                                  // the box whose details are open (they open right under its row)
function archHtml() {
  let i = 0;
  return `<div class="arch">${ARCH.map(([layer, nodes], li) => {
    const first = i;
    const row = `
    <div class="arch-l" style="--i:${li}"><div class="arch-n">${esc(layer)}</div><div class="arch-row">${nodes.map(([n, d, svc]) => {
      const st = svc === "@runner" ? (S ? "ok" : "") : svc ? svcState(svc) : "";
      const k = i++;
      return `<button type="button" class="arch-node ${k === archOpen ? "on" : ""}" data-arch="${k}" aria-expanded="${k === archOpen}">${st ? `<span class="dot ${st}"></span>` : `<span class="dot ext"></span>`}<span class="grow"><b>${esc(n)}</b><span class="tiny muted">${esc(d)}</span></span></button>`;
    }).join("")}</div></div>`;
    return row + (archOpen !== null && archOpen >= first && archOpen < i ? archInfoHtml(archOpen) : "");
  }).join("")}
    <div class="arch-key tiny faint"><span><span class="dot ok"></span>running</span><span><span class="dot warn"></span>unhealthy</span><span><span class="dot err"></span>stopped</span><span><span class="dot ext"></span>outside / on demand</span><span class="grow"></span><span>Tap a box for details</span></div></div>`;
}
function archInfoHtml(i) {
  const [name, short, svc, ch, sec, about, app] = ARCH_FLAT[i];
  const s = svc && svc !== "@runner" ? (S?.system?.services || []).find((x) => x.name === svc || x.name.replace(/-\d+$/, "").endsWith(svc)) : null;
  const res = svc ? (S?.resources?.services || []).find((x) => x.name === svc) : null;
  const status = svc === "@runner" ? (S ? "running · state updated just now" : "not reporting") : s ? s.status : svc ? "not found" : "outside the PC, or started on demand";
  const dot = svc ? (svc === "@runner" ? (S ? "ok" : "err") : s ? (s.state === "running" ? (/unhealthy/.test(s.status) ? "warn" : "ok") : "err") : "") : "";
  const href = app ? (app.startsWith("#") ? app : `${HOSTURL}${app === "443" ? "" : ":" + app}/`) : "";
  return `<div class="archinfo" role="region" aria-label="${esc(name)}">
    <div class="row between" style="gap:10px;align-items:flex-start"><div><b style="font-size:16px">${esc(name)}</b> <span class="small muted">${esc(short)}</span></div>
      <button class="icon-btn" data-archclose title="Close">${ic.x}</button></div>
    <div class="small" style="margin-top:6px">${esc(about)}</div>
    <div class="row wrap tiny muted" style="gap:10px;margin-top:8px"><span>${dot ? `<span class="dot ${dot}" style="display:inline-block;margin-right:5px"></span>` : ""}${esc(status)}</span>
      ${res ? `<span>${nf(res.mem_mb)} / ${nf(res.limit_mb)} MB memory · ${nf(res.cpu, 1)} % CPU</span>` : ""}</div>
    <div class="row wrap" style="gap:8px;margin-top:10px">${href ? `<a class="btn sm primary" href="${href}"${app.startsWith("#") ? "" : ' target="_blank" rel="noopener"'}>${ic.next}Open</a>` : ""}
      <a class="btn sm" href="#/guide/${ch}?s=${encodeURIComponent(slugH(sec))}">${ic.doc}How it works</a></div></div>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-arch]"), x = e.target.closest("[data-archclose]");
  if (!b && !x) return;
  archOpen = x ? null : +b.dataset.arch === archOpen ? null : +b.dataset.arch;        // tap again to close
  fillLive();
});
const loading = `<div class="skeleton" style="height:56px"></div>`;
// plain-language descriptions of Hermes' Mission Control tools (a new tool shows its own first sentence until added here)
const TOOL_HELP = {
  house_status: "Lists the lights, plugs, switches and shutters Home Assistant knows, by room, and your Echos.",
  house_switch: "Switches one light, plug or shutter (protected ones like the fridge plug never).",
  house_alexa: "Tells Alexa a command as if you said it: for the lights that live in the Alexa app.",
  house_say: "Speaks a short message on one Echo, or on all of them.",
  windows_status: "Says how your Windows PC is: memory, disks, the folders Claude may read there, and whether Claude is signed in.",
  windows_ask: "Asks Claude Code on your Windows PC about your files there: it can only read, only in the folders you allow.",
  windows_result: "Fetches the answer from your Windows PC (and waits a little while Claude is still reading).",
  claude_task: "Hands a code question, a review or a long document to Claude Code (read-only, on your Claude plan).",
  claude_task_result: "Fetches Claude Code's answer to a task (and waits a little while it is still working).",
  health_issues: "Lists the open health issues of every agent (alerts and notes) with the run that shows each one.",
  agent_note: "Lets an agent keep a standing note in its own memory (Agents → the agent → Memory), read by all its future runs.",
  missions_overview: "Lists all your missions with status, schedule, triggers, next run and costs.",
  mission_details: "Reads one mission in full: goal, brief, notes, recent runs and where its files are.",
  mission_create: "Starts a new briefing or task, including one-off and deep research jobs, with the files it must deliver.",
  file_save: "A mission saves a file it was asked to deliver (Markdown, CSV, JSON, text): on its Results, attached to its e-mail.",
  mission_control: "Runs, pauses, resumes or archives a mission.",
  mission_update: "Changes a mission: goal, questions, sources, schedule, delivery or depth.",
  mission_set_triggers: "Sets the events a mission reacts to: SEC filings, price moves, news.",
  send_email: "E-mails you a designed report (only ever to your own address).",
  vault_add: "Saves a note or a web page into your vault, where search finds it.",
  change_request: "Starts a change request: the swarm specifies, tests, implements and checks it, and comes back with one branch for your review.",
  task_start: "Start a task for a job of several steps: it is planned, done and followed on its page",
  build_assign: "Gives the builder a coding assignment on one of your repositories.",
  builds_overview: "Lists the builder's assignments and what's waiting for your review, with the AI review's verdict.",
  build_details: "Reads one build in full: assignment, summary, files, checks, CI, every AI-review finding, and the diff if you ask.",
  build_request_changes: "Sends a build back to the builder with your changes, like the Request changes button (never approves).",
  build_switch_engine: "Moves a build to the other engine (ChatGPT or Claude Code), e.g. when one hit its usage limit.",
  build_recheck: "Re-runs a build's checks and AI review on today's code.",
  improvement_proposals: "Shows the improvements the stack proposes from its weekly self-review, and can start one now.",
  understand_repo: "Analyses a code repository and builds its code graph and code map.",
  repos_overview: "Lists your repositories: which ones the builder may change, their graphs and code maps.",
  repo_create: "Creates a new private repository on your Forgejo, ready for the builder.",
  repo_make_buildable: "Moves a studied GitHub repository to your Forgejo so the builder can change it.",
};
const LIVEB = {
  architecture: archHtml,
  services: () => !S ? loading : `<div class="gl-grid">${(S.system?.services || []).map((s) => `<div class="gl-svc"><span class="dot ${s.state === "running" ? (/unhealthy/.test(s.status) ? "warn" : "ok") : "err"}"></span><span class="wrap">${esc(s.name)}</span></div>`).join("")}</div>`,
  resources: () => !S ? loading : resourcesHtml(S.resources),
  missions: () => {
    if (!S) return loading;
    const ms = S.missions.filter((m) => m.status === "active");
    return ms.length ? `<div class="gl-list">${ms.map((m) => `<a href="#/mission/${encodeURIComponent(m.slug)}"><span class="type-ic sm">${typeIcon(m.type)}</span><span class="grow"><b>${esc(m.title)}</b><span class="tiny muted">${typeName(m.type)} · ${esc(m.schedule_text)}${m.triggers?.length ? ` · ${m.triggers.length} trigger${m.triggers.length > 1 ? "s" : ""}` : ""}</span></span><span class="tiny faint">${m.stats.runs} runs</span></a>`).join("")}</div>`
      : `<div class="small muted">No active missions yet. The examples below create your first one.</div>`;
  },
  repos: () => !S ? loading : `<div class="gl-list">${(S.code?.repos || []).map((r) => `<a href="#/repo/${encodeURIComponent(r.name)}"><span class="type-ic sm">${ic.code}</span><span class="grow"><b>${esc(r.name)}</b><span class="tiny muted">${r.buildable ? "builder can change it" : "studied"} · ${r.graph ? `graph ${nf(r.graph.nodes)} nodes` : "no graph yet"}${r.codemap ? " · code map" : ""}</span></span></a>`).join("") || `<span class="small muted">No repositories yet.</span>`}</div>`,
  skills: () => !S ? loading : `<div class="chips">${(S.system?.skills || []).map((k) => `<span class="tag">${esc(k)}</span>`).join("") || `<span class="small muted">No skills yet</span>`}</div><div class="tiny faint" style="margin-top:8px">${(S.system?.skills || []).length} skills right now</div>`,
  ci: () => !S ? loading : `<div class="gl-grid">${(S.system?.ci || []).map((c) => `<div class="gl-svc"><span class="dot ${c.status === "success" ? "ok" : c.status === "failure" ? "err" : ""}"></span><span class="grow">${esc(c.repo)}</span><span class="tiny faint">${esc(c.status)} ${esc(c.sha)}</span></div>`).join("")}</div>`,
  models: () => `<div class="gl-list">${(GLIVE?.models || []).map((m) => `<div><span class="type-ic sm">${ic.bolt}</span><span class="grow"><b>${esc(m.name)}</b><span class="tiny muted">${esc(m.note)}</span></span><code class="tiny">${esc(m.id)}</code></div>`).join("")}</div>
    <div class="tiny faint" style="margin-top:8px">Effort levels: ${(GLIVE?.efforts || []).map(esc).join(" · ")}</div>`,
  tools: () => `<div class="gl-tools">${(GLIVE?.tools || []).map((t) => `<div><code>${esc(t.name)}</code><span class="small muted">${esc(TOOL_HELP[t.name] || t.about)}</span></div>`).join("")}</div>`,
  versions: () => !S ? loading : `<div class="gl-grid">${(S.system?.versions || []).map((v) => `<div class="gl-svc"><span class="grow">${esc(v.name)}</span><code class="tiny">${esc(v.version)}</code></div>`).join("")}</div>`,
  changes: () => !S ? loading : `<div class="gl-changes">${(S.system?.changes || []).map((c) => `<div><span class="tiny faint num">${esc(c.sha)}</span><span class="grow">${esc(c.subject)}</span><span class="tiny faint" style="white-space:nowrap">${rel(c.ts)}</span></div>`).join("") || `<div class="small muted">No history available</div>`}</div>`,
  apps: () => { if (!TOOLS) { toolsLoad().then(() => fillLive()); return loading; }        // the Stack tab's tools list (APP-30)
    return `<div class="grid g2">${TOOLS.tools.map((t) => `<div class="card pad tool"><b>${esc(t.name)}</b><div class="small muted">${esc(t.what)}</div><div class="chips" style="margin-top:6px">${toolLinks(t)}</div></div>`).join("")}</div>`; },
  costs: () => { const sy = S?.system || {}; return !S ? loading : `<div class="grid g2"><div class="card kpi"><div class="kpi-l">Paid, all time</div><div class="kpi-v">${usd(sy.spend_total)}</div><div class="kpi-s">30 days: ${usd(sy.spend_30d)}</div></div><div class="card kpi"><div class="kpi-l">Calls today</div><div class="kpi-v">${nf(sy.calls_today)}</div><div class="kpi-s">all on the ChatGPT subscription</div></div></div>`; },
};
function fillLive(root = document) {
  $$(".glive", root).forEach((el) => {
    const f = LIVEB[el.dataset.live];
    const html = f ? `<div class="gl-tag tiny">${ic.pulse}Live</div>${f()}` : "";
    if (el.innerHTML !== html) el.innerHTML = html;
    requestAnimationFrame(() => el.classList.add("settled"));        // entrance animation only the first time
  });
}
function guideOnState() { if (route.name === "guide" || route.name === "system") fillLive(); }

// ---------- the guide inside the Stack page ----------
let scrollToLearn = false;
const how = (id) => `<a class="howto" href="#/guide/${id}" title="How this works">${ic.doc}<span>How it works</span></a>`;
// APP-31: an explanation is there for who needs it and folded for who knows: one small line opens it, and it stays open
// through every live redraw (the page's and a card's own) until closed
const EXPLAIN_OPEN = new Set();
const explain = (key, html, label = "About this") => `<details class="explain" data-x="${key}"${EXPLAIN_OPEN.has(key) ? " open" : ""}><summary aria-label="${label}" title="${label}"><span class="xi">i</span></summary><div class="small muted">${html}</div></details>`;
document.addEventListener("toggle", (e) => { const k = e.target?.dataset?.x; if (k) e.target.open ? EXPLAIN_OPEN.add(k) : EXPLAIN_OPEN.delete(k); }, true);

async function vGuide() {
  if (!route.args[0]) { scrollToLearn = true; location.replace("#/system"); return; }   // the guide's home is the Stack page
  if (!GUIDE) view.innerHTML = `<div class="stack"><div class="skeleton"></div><div class="skeleton"></div></div>`;
  await loadGuide();
  if (route.name !== "guide") return;
  if (!GUIDE?.length) { view.innerHTML = `<div class="card empty">${ic.doc}<div>The guide could not be loaded.</div></div>`; return; }
  return vGuideChapter(route.args[0]);
}

function progressRing(frac, size = 34) {
  const r = (size - 5) / 2, C = 2 * Math.PI * r;
  return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="var(--surface-3)" stroke-width="3" fill="none"/>
    ${frac > 0 ? `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="url(#rg)" stroke-width="3" fill="none" stroke-linecap="round" stroke-dasharray="${(C * frac).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>` : ""}
    <defs><linearGradient id="rg"><stop offset="0" stop-color="var(--accent)"/><stop offset="1" stop-color="var(--accent-2)"/></linearGradient></defs></svg>`;
}
const chapterFrac = (c) => { const tr = triedIn(c), read = gp.read[c.id]; return c.tries ? (tr / c.tries) * 0.7 + (read ? 0.3 : 0) : read ? 1 : 0; };

function chapterRow(c) {
  const f = chapterFrac(c), done = f >= 0.999;
  return `<a class="gidx" href="#/guide/${c.id}"><span class="gc-ic">${gicon(c.icon)}</span>
    <span class="grow"><b>${esc(c.title)}</b><span class="tiny muted">${c.minutes} min${c.tries ? ` · ${c.tries} example${c.tries > 1 ? "s" : ""} to try` : ""}</span></span>
    <span class="gc-ring">${progressRing(f, 28)}${done ? `<span>${ic.check}</span>` : ""}</span></a>`;
}

const plain = (s) => s.replace(/```[\s\S]*?```/g, " ").replace(/[#*`>|_\[\]]/g, " ").replace(/\s+/g, " ");
function searchHtml(q) {
  const ql = q.toLowerCase(), hits = [];
  GUIDE.forEach((c) => {
    const text = plain(c.body), i = text.toLowerCase().indexOf(ql), inTitle = (c.title + " " + c.summary).toLowerCase().includes(ql);
    if (i < 0 && !inTitle) return;
    const snip = i < 0 ? c.summary : (i > 60 ? "…" : "") + text.slice(Math.max(0, i - 60), i + 140) + "…";   // cap: preview: a search hit opens its chapter
    const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    hits.push(`<a href="#/guide/${c.id}"><div class="ic">${gicon(c.icon)}</div><div class="grow"><div class="ttl">${esc(c.title)}</div><div class="sub">${esc(snip).replace(re, (m) => `<mark>${m}</mark>`)}</div></div></a>`);
  });
  return hits.length ? `<div class="card list">${hits.join("")}</div>` : `<div class="card empty small">Nothing in the guide mentions “${esc(q)}”. Ask Hermes in Chat instead.</div>`;
}

// "Start here" until the first chapter is read or an example tried
function startHereHtml() {
  if (Object.keys(gp.read).length || Object.keys(gp.tried).length) return "";
  return `<a class="card gstart fadein section" href="#/guide/first-ten-minutes"><div class="gs-ic">${ic.play}</div><div class="grow"><div class="tiny gc-k">New here? Start here</div><h3>Your first ten minutes</h3><div class="small muted">Five quick things to try that show you most of the stack. Nothing to clean up afterwards.</div></div>${ic.next}</a>`;
}

// The chapter index at the bottom of the Stack page: every chapter by part, with progress
function learnHtml() {
  if (!GUIDE?.length) return `<div class="section-h"><h2>Learn your stack</h2></div><div class="skeleton" style="height:120px"></div>`;
  const read = GUIDE.filter((c) => gp.read[c.id]).length, tried = Object.keys(gp.tried).length, T = totalTries();
  const changes = (S?.system?.changes || []).slice(0, 3);
  return `<div class="card glearn">
    <div class="gl-head"><div class="grow"><div class="gh-k">${ic.doc}Guide</div><h3>Learn your stack</h3>
      <div class="small muted">${GUIDE.length} chapters with ${T} examples you can try right away. Live parts update themselves from the running system.</div></div>
      <div class="gl-prog small"><span>${read}/${GUIDE.length} read · ${tried}/${T} tried</span><div class="meter"><i style="width:${(((read / GUIDE.length) * 0.4 + (T ? tried / T : 0) * 0.6) * 100).toFixed(1)}%"></i></div></div></div>
    <div class="gl-parts">${GPARTS.map((p) => { const cs = GUIDE.filter((c) => c.part === p); return cs.length ? `<div><div class="gl-part">${esc(p)}</div>${cs.map(chapterRow).join("")}</div>` : ""; }).join("")}</div>
    ${changes.length ? `<div class="gl-new"><div class="gl-part">Recently changed in the stack <a class="tiny muted" href="#/guide/whats-new">all changes</a></div>${changes.map((c) => `<div class="small"><span class="tiny faint num">${esc(c.sha)}</span> ${esc(c.subject)} <span class="tiny faint">· ${rel(c.ts)}</span></div>`).join("")}</div>` : ""}
    <div class="tiny faint" style="margin-top:12px">The stack's automatic checks fail if a feature is added without a chapter, so this guide can't fall behind. Progress is saved on this device.${read || tried ? ` <button class="btn sm ghost" id="greset">Reset progress</button>` : ""}</div>
  </div>`;
}

function bindLearn() {
  const q = $("#gq");
  if (q) {
    const doSearch = () => { guideQuery = q.value.trim(); $("#gresults").innerHTML = guideQuery.length > 1 && GUIDE ? `<div class="section-h section"><h2>From the guide</h2></div>${searchHtml(guideQuery)}` : ""; };
    q.oninput = doSearch; if (guideQuery) doSearch();
  }
  const rs = $("#greset");
  if (rs) rs.onclick = () => { if (confirm("Reset your guide progress on this device?")) { gp.read = {}; gp.tried = {}; gsave(); render(true); } };
}

function vGuideChapter(id) {
  const i = GUIDE.findIndex((c) => c.id === id), c = GUIDE[i];
  if (!c) { location.replace("#/system"); return; }
  const { html, tries } = guideHtml(c), prev = GUIDE[i - 1], next = GUIDE[i + 1];
  const VNAMES = { home: "Home", missions: "Missions", mission: "Mission", new: "New mission", read: "Reports", wiki: "Wiki", build: "Build", chat: "Chat", system: "Stack" };
  const views = [...new Set((c.views || []).map((v) => VNAMES[v]).filter(Boolean))];
  view.innerHTML = `
  <div class="gbar"><i id="gbar"></i></div>

  <div class="gchap">
    <article class="gart fadein">
      <a class="small muted gback" href="#/system">${ic.back}Stack</a>
      <header class="ghead">
        <div class="gh-ic">${gicon(c.icon)}</div>
        <div class="tiny gc-k">${esc(c.part)} · ${esc(c.kicker)}</div>
        <h1>${esc(c.title)}</h1>
        <p class="muted">${esc(c.summary)}</p>
        <div class="gc-m tiny faint"><span>${ic.clock}${c.minutes} min read</span>${c.tries ? `<span>${ic.play}${c.tries} example${c.tries > 1 ? "s" : ""} to try</span>` : ""}${views.length ? `<span>${ic.layers}Explains: ${views.join(", ")}</span>` : ""}</div>
      </header>
      <div class="md gbody">${html}</div>
      <footer class="gfoot" id="gfoot">
        <div class="gdone small">${gp.read[c.id] ? `${ic.check}You've read this chapter` : `Reach the end to mark it read`}</div>
        <div class="gnav">${prev ? `<a class="card pad" href="#/guide/${prev.id}"><span class="tiny faint">${ic.back}Previous</span><b>${esc(prev.title)}</b></a>` : "<span></span>"}
          ${next ? `<a class="card pad nx" href="#/guide/${next.id}"><span class="tiny faint">Next${ic.next}</span><b>${esc(next.title)}</b></a>` : `<a class="card pad nx" href="#/system"><span class="tiny faint">Done${ic.next}</span><b>Back to Stack</b></a>`}</div>
      </footer>
    </article>
    <aside class="gtoc">
      <div class="tiny faint" style="margin-bottom:8px">On this page</div>
      ${c.sections.map((s) => `<a href="#" data-sec="${esc(slugH(s))}">${esc(s)}</a>`).join("")}
      ${c.tries ? `<div class="gtoc-p small"><span>${triedIn(c)} of ${c.tries} tried</span><div class="meter"><i style="width:${((triedIn(c) / c.tries) * 100).toFixed(0)}%"></i></div></div>` : ""}
    </aside>
  </div>`;
  const body = $(".gbody");
  $$("h2", body).forEach((h) => (h.id = slugH(h.textContent)));
  $$("blockquote", body).forEach((b) => {
    const p = b.querySelector("p"), m = p && p.innerHTML.match(/^\[!(tip|note|warning)\]\s*/i);
    if (m) { b.classList.add("callout", m[1].toLowerCase()); p.innerHTML = `<span class="co-l">${{ tip: "Tip", note: "Good to know", warning: "Careful" }[m[1].toLowerCase()]}</span>` + p.innerHTML.slice(m[0].length); }
  });
  $$(".gtry", body).forEach((el) => (el.outerHTML = tryCard(c, tries[+el.dataset.try], +el.dataset.try)));
  fillLive(body);
  $$("[data-tried]").forEach((a) => a.addEventListener("click", () => { gp.tried[a.dataset.tried] = 1; gsave(); }));
  $$(".gtoc [data-sec]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); document.getElementById(a.dataset.sec)?.scrollIntoView({ behavior: "smooth", block: "start" }); }));
  const sec = route.q.get("s");
  if (sec) setTimeout(() => document.getElementById(sec)?.scrollIntoView({ block: "start" }), 30);
  const bar = $("#gbar"), art = $(".gart");
  const onScroll = () => {
    if (!bar.isConnected) return window.removeEventListener("scroll", onScroll);
    const r = art.getBoundingClientRect(), f = Math.min(1, Math.max(0, -r.top / Math.max(1, r.height - innerHeight)));
    bar.style.width = (f * 100).toFixed(1) + "%";
    let on = null; $$("h2[id]", body).forEach((h) => { if (h.getBoundingClientRect().top < 140) on = h.id; });
    $$(".gtoc [data-sec]").forEach((a) => a.classList.toggle("on", a.dataset.sec === on));
  };
  window.addEventListener("scroll", onScroll, { passive: true }); onScroll();
  if (!gp.read[c.id] && "IntersectionObserver" in window) {
    const ob = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { gp.read[c.id] = 1; gsave(); ob.disconnect(); const d = $(".gdone"); if (d) d.innerHTML = `${ic.check}Marked as read`; } });
    ob.observe($("#gfoot"));
  }
}
const slugH = (s) => "s-" + String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// contextual help: the chapter about the current screen
function helpHref() {
  const c = chapterFor(route.name);
  return c ? `#/guide/${c.id}` : "#/guide";                 // no chapter: the guide's contents, not the Stack page
}
