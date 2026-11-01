// Mission Control front end: one small vanilla-JS app. State comes live from /api/stream (the runner's state.json);
// actions go to /api/request, which the host runner validates and executes. Chats and wikis come from their own APIs.
"use strict";

// a script error on a phone is invisible from the PC: report it to the server log (docker logs mission-control)
let errSent = 0;
function reportError(msg, where) {
  if (errSent++ > 5) return;
  try { navigator.sendBeacon("/api/clienterror", JSON.stringify({ msg: String(msg).slice(0, 500) /* cap: untrusted */, where: String(where || "").slice(0, 300) /* cap: untrusted */, url: location.hash, ua: navigator.userAgent })); } catch (_) {}
}
// An error is reported to the server and told to the owner too: a broken "Start mission" once only showed its spinner (FND-52)
const toldError = (msg) => { try { toast(`Something went wrong in the app: ${msg}. It is reported; reload the page and try again.`, true); } catch (_) {} };
window.addEventListener("error", (e) => { reportError(e.message, `${e.filename}:${e.lineno}:${e.colno}`); toldError(e.message); });
window.addEventListener("unhandledrejection", (e) => { reportError(e.reason?.message || e.reason, e.reason?.stack?.split("\n")[1]); toldError(e.reason?.message || e.reason); });

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = $("#view");
let S = null;                    // latest state
let route = { name: "home", args: [], q: new URLSearchParams() };
let tab = "overview";            // mission detail tab
let missionFilter = "active";

// ---------- icons (inline, stroke) ----------
const I = (d) => `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;   // .ico: one line of text high unless its place sizes it
const ic = {
  home: I('<rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2"/>'),
  house: I('<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10h13V10"/><path d="M10 20v-5.5h4V20"/>'),
  target: I('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>'),
  chat: I('<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4A8 8 0 1 1 20 12Z"/>'),
  pulse: I('<path d="M3 12h4l2.5-6 5 12 2.5-6H21"/>'),
  wiki: I('<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8.3 7.1 15.6 7M7.4 8.2l3.5 7.6M16.9 9.2l-3.6 6.7"/>'),
  news: I('<path d="M5 4h11a2 2 0 0 1 2 2v13a1 1 0 0 0 2 0V8"/><path d="M5 4a1 1 0 0 0-1 1v13a2 2 0 0 0 2 2h14"/><path d="M8 8h6M8 12h6M8 16h4"/>'),
  rocket: I('<path d="M12 15l-3-3a13 13 0 0 1 9-8.5 13 13 0 0 1-6 11.5Z"/><path d="M9 12H5l2-4h4M12 15v4l4-2v-4"/><path d="M6.5 17.5c-1 1-1.5 3-1.5 3s2-.5 3-1.5"/>'),
  play: I('<path d="M7 5v14l11-7Z"/>'),
  pause: I('<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>'),
  archive: I('<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8M10 12h4"/>'),
  back: I('<path d="M15 6l-6 6 6 6"/>'),
  next: I('<path d="M9 6l6 6-6 6"/>'),
  plus: I('<path d="M12 5v14M5 12h14"/>'),
  compose: I('<path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6"/><path d="M17.5 3.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4Z"/>'),
  clip: I('<path d="m20.5 11.5-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l7.9-7.9"/>'),
  clock: I('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  coin: I('<circle cx="12" cy="12" r="9"/><path d="M14.5 9.5c-.5-1-1.5-1.5-2.5-1.5-1.7 0-2.5 1-2.5 2 0 2.5 5 1.5 5 4 0 1-1 2-2.5 2-1 0-2-.5-2.5-1.5M12 6.5v1.5M12 16v1.5"/>'),
  bolt: I('<path d="M13 3 5 14h6l-1 7 8-11h-6Z"/>'),
  check: I('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
  x: I('<path d="M6 6l12 12M18 6 6 18"/>'),
  send: I('<path d="M5 12h13M13 6l6 6-6 6"/>'),
  bell: I('<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15Z"/><path d="M10 20a2 2 0 0 0 4 0"/>'),
  alert: I('<path d="M12 3 2 20h20Z"/><path d="M12 10v4M12 17h.01"/>'),
  doc: I('<path d="M7 3h7l5 5v13H7Z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>'),
  brain: I('<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3V4Z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3V4Z"/>'),
  repeat: I('<path d="M17 2l3 3-3 3"/><path d="M4 11V9a4 4 0 0 1 4-4h12M7 22l-3-3 3-3"/><path d="M20 13v2a4 4 0 0 1-4 4H4"/>'),
  trash: I('<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>'),
  layers: I('<path d="M12 3 2 8l10 5 10-5Z"/><path d="M2 13l10 5 10-5"/>'),
  radar: I('<circle cx="12" cy="12" r="9"/><path d="M12 12 18 6"/><circle cx="12" cy="12" r="4"/>'),
  search: I('<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>'),
  list: I('<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>'),
  history: I('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>'),
  code: I('<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16"/>'),
  tune: I('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
};

// ---------- formatting (TSK-31): the only place the app turns a date, a time or a number into text, in English ----------
// "Sat 31 Oct, 18:40" (rel within a day: "in 3 h", "12 min ago"), "Sat 31 Oct", "18:40"; "1,234", "4.2k", "$0.42", "€12.34".
// tests/test_ux_standards.py fails on a toLocale…, Intl or a sliced ISO time anywhere else; "fmt-ok" marks a key or a geometry.
const toDate = (x) => (x == null || x === "" ? null : x instanceof Date ? x : new Date(typeof x === "number" ? (x < 1e12 ? x * 1000 : x) : x));
const nf = (n, d = 0) => Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const usd = (n) => (n > 0 && n < 0.01 ? "$" + Number(n).toFixed(4) : "$" + Number(n || 0).toFixed(2));
const eur = (v) => (v == null ? "?" : "€" + nf(+v, 2));
const kn = (n) => (n >= 1e6 ? nf(n / 1e6, 1) + "M" : n >= 1e4 ? nf(n / 1e3, 0) + "k" : n >= 1e3 ? nf(n / 1e3, 1) + "k" : nf(n));
const tok = kn;
const gb = (n) => (n >= 1e8 ? `${nf(n / 1e9, 1)} GB` : `${nf((n || 0) / 1e6)} MB`);
const clock = (x, sec = false) => { const d = toDate(x); return d && !isNaN(d) ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", ...(sec ? { second: "2-digit" } : {}) }) : "–"; };
const day = (x, long = false) => { const d = toDate(x); if (!d || isNaN(d)) return "–";
  return d.toLocaleDateString("en-GB", { weekday: long ? "long" : "short", day: "numeric", month: long ? "long" : "short", ...(d.getFullYear() !== new Date().getFullYear() ? { year: "numeric" } : {}) }); };
const dayKey = (x) => toDate(x).toISOString().slice(0, 10);       // a day as a key ("2026-11-01"), never shown
// TSK-27: what tokens would cost at the provider's list price (config/prices.json, from the gateway's own price table);
// the subscriptions cost $0 a call, so this is for comparing and spotting waste, never a bill
const ifPaid = (x) => x == null ? "" : x < 0.01 ? "<$0.01 if paid" : `$${x < 100 ? x.toFixed(2) : nf(x, 0)} if paid`;
const costOf = (model, t, P = S?.prices || {}) => { const p = P[model]; if (!p || !t) return null; const cached = t.cached || 0;
  return ((t.in || 0) - cached) * p.in + cached * (p.cached ?? p.in) + (t.out || 0) * p.out; };
const dur = (s) => (!s ? "–" : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${nf(s / 3600, 1)} h`);
function rel(iso) {
  if (!iso) return "–";
  const d = (toDate(iso) - Date.now()) / 1000, a = Math.abs(d);
  if (a < 60) return "just now";
  const t = a < 3600 ? `${Math.round(a / 60)} min` : a < 86400 * 1.5 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} days`;
  return d > 0 ? `in ${t}` : `${t} ago`;
}
const dt = (x) => { const d = toDate(x); return d && !isNaN(d) ? `${day(d)}, ${clock(d)}` : "–"; };
const when = (x) => { const d = toDate(x); return !d || isNaN(d) ? "–" : Math.abs(d - Date.now()) < 86400e3 ? rel(d) : dt(d); };
const fmtMs = (ms) => (ms == null ? "" : ms >= 60000 ? `${Math.floor(ms / 60000)}m${String(Math.round((ms % 60000) / 1000)).padStart(2, "0")}s` : ms >= 1000 ? `${nf(ms / 1000, 1)} s` : `${ms} ms`);
// ---------- end of formatting ----------
const greet = () => { const h = new Date().getHours(); return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };
const STATUS = { active: "Active", paused: "Paused", archived: "Archived", ok: "Done", failed: "Failed", running: "Running", queued: "Queued", skipped: "Skipped", waiting: "Waiting for ChatGPT" };
const typeIcon = (t) => (t === "briefing" ? ic.news : t === "shopping" ? ic.coin : t === "cleanup" ? ic.trash : ic.rocket);
const typeName = (t) => (t === "briefing" ? "Briefing" : t === "shopping" ? "Shopping" : t === "cleanup" ? "Cleanup analysis" : "Long-term task");
const TRIG = { schedule: "scheduled", manual: "on demand", event: "event", restart: "restarted after a deploy" };

function md(text, wl) {
  let body = String(text || "").replace(/^---\n[\s\S]*?\n---\n?/, "");
  body = body.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (_, target, alias) => {
    const label = esc(alias || target.split("/").pop().replace(/-/g, " "));
    const r = wl && wl.links ? wl.links[target] : null;
    if (r && r.kind === "page") return `<a class="wl" href="#/wiki?root=${encodeURIComponent(wl.root)}&page=${encodeURIComponent(r.ref)}">${label}</a>`;
    if (r && r.kind === "file") return `<a class="wl" href="#/read?path=${encodeURIComponent(r.ref)}">${label}</a>`;
    if (!wl && /^(topics|missions|wiki)\//.test(target)) return `<a class="wl" href="#/read?path=${encodeURIComponent(target + ".md")}">${label}</a>`;
    return `<span class="wl dead" title="no page yet">${label}</span>`;
  });
  const html = DOMPurify.sanitize(marked.parse(body, { gfm: true, breaks: false }));
  return html.replace(/<a href="(https?:)/g, '<a target="_blank" rel="noopener" href="$1');
}

// an empty state says what fills it and offers that action (TSK-31): text and action are HTML
function emptyState(text, action, cls = "") {
  return `<div class="empty${cls ? " " + cls : ""}"><div>${text}</div><div class="empty-a">${action}</div></div>`;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast on" + (err ? " err" : "");
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.className = "toast"), 3400);
}

// Every call has a time limit (APP-23): a request that stalls on the way (the phone's network, the app restarting during
// a deploy) once left a "Drafting the brief…" button spinning for good.
async function api(path, opts = {}) {
  const { timeout = 45000, ...rest } = opts;
  const ctl = typeof AbortController === "function" ? new AbortController() : null, t = ctl && setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(path, { headers: { "Content-Type": "application/json" }, cache: "no-cache", ...(ctl ? { signal: ctl.signal } : {}), ...rest });   // never a stale answer
    if (!r.ok && r.status !== 404) throw new Error(`HTTP ${r.status}`);
    return await (r.headers.get("content-type")?.includes("json") ? r.json() : r.text());
  } catch (e) {
    throw e.name === "AbortError" ? new Error(`Mission Control did not answer within ${Math.round(timeout / 1000)} s`) : e;
  } finally { clearTimeout(t); }
}

// every action says what happens next (TSK-31): okMsg is that sentence, or made from the answer ((r) => …); null for a read
async function act(req, okMsg) {
  let r;
  try {
    r = await api("/api/request", { method: "POST", body: JSON.stringify(req), timeout: 30000 });
  } catch (e) {                                          // it may or may not have arrived: say so, and how to check
    toast(`${e.message}. ${req.action === "create" ? "Look under Missions before trying again (a repeat with the same title is refused)." : "Please try again."}`, true);
    return null;
  }
  for (let i = 0, misses = 0; r.pending && i < 150; i++) {   // slow requests (a new briefing): keep asking, up to 5 minutes
    await new Promise((res) => setTimeout(res, 2000));
    try { const x = await api(`/api/result/${r.id}`, { timeout: 15000 }); if (!x.pending) r = x; misses = 0; }
    catch (e) { if (++misses >= 10) { toast(`Lost contact with Mission Control: ${e.message}. The request may still finish; check again in a minute.`, true); return null; } }
  }
  if (r.pending) { toast("Still working on it: it shows up when it is done (you get a message).", true); return null; }
  if (r.ok === false) { toast(r.error || "Error", true); return null; }
  const said = typeof okMsg === "function" ? okMsg(r) : okMsg;
  if (said) toast(said);
  return r;
}

// ---------- charts ----------
function spark(vals, w = 84, h = 28) {
  vals = vals.filter((v) => v != null);
  if (vals.length < 2) return "";
  const max = Math.max(...vals) || 1, step = w / (vals.length - 1);
  const pts = vals.map((v, i) => `${(i * step).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><defs><linearGradient id="sg" x1="0" x2="1"><stop offset="0" stop-color="var(--accent)"/><stop offset="1" stop-color="var(--accent-2)"/></linearGradient></defs><polyline points="${pts}" fill="none" stroke="url(#sg)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
function bars(runs) {
  const rs = runs.slice(0, 20).reverse();
  if (!rs.length) return `<div class="small muted">No runs yet: each one shows here as a bar.</div>`;
  const W = 600, H = 120, max = Math.max(...rs.map((r) => r.tokens || 0)) || 1, bw = W / rs.length;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${rs.map((r, i) => {
    const bh = Math.max(3, ((r.tokens || 0) / max) * (H - 8));
    const col = r.status === "failed" ? "var(--err)" : r.event ? "var(--warn)" : r.status === "ok" ? "url(#bg)" : "var(--faint)";
    return `<rect x="${i * bw + bw * 0.18}" y="${H - bh}" width="${bw * 0.64}" height="${bh}" rx="3" fill="${col}"><title>${esc(dt(r.started))}: ${tok(r.tokens)} tokens, ${r.calls || 0} calls</title></rect>`;
  }).join("")}<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)"/><stop offset="1" stop-color="var(--accent-2)"/></linearGradient></defs></svg>`;
}

// ---------- navigation ----------
// one navigation on every screen (no top bar): the swarm's views live under Agents, the live state is a dot on Stack
const NAV = [["home", "#/", "Home", ic.home], ["missions", "#/missions", "Agents", ic.target], ["wiki", "#/wiki", "Wiki", ic.wiki], ["build", "#/build", "Code", ic.code],
  ["chat", "#/chat", "Chat", ic.chat], ["system", "#/system", "Stack", ic.layers]];
function navHtml(bottom) {
  const pend = S?.system?.pending_memory?.length || 0;
  return NAV.map(([k, href, label, icon]) => {
    const on = route.name === k || (k === "missions" && ["mission", "crew", "new", "swarm", "tasks", "task", "taskmap"].includes(route.name)) || (k === "system" && ["guide", "telemetry", "trials"].includes(route.name)) || (k === "build" && route.name === "repo");
    const toReview = (S?.builds || []).filter((b) => b.status === "review").length;        // the badge = what waits for you
    const n = k === "system" && pend ? `<span class="tab-n">${pend}</span>` : k === "build" && toReview ? `<span class="tab-n">${toReview}</span>`
      : k === "system" ? `<span class="tab-dot ${liveState()}" title="${liveState() === "run" ? "An agent is running" : liveState() === "ok" ? "Ready" : "Not connected"}"></span>` : "";
    return `<a href="${href}" class="${on ? "on" : ""}">${icon}<span>${label}</span>${n}</a>`;
  }).join("");
}
function chrome() {
  $("#nav-side").innerHTML = navHtml();
  $("#nav-bottom").innerHTML = navHtml(true);
  const help = $("#pagehelp");                            // the page's own help, at its end (no header button)
  if (help) { help.querySelector("a").href = helpHref(); help.classList.toggle("off", route.name === "guide"); }
  const chip = $("#live-chip");
  liveChip(chip);
  mirrorChip();
}
function mirrorChip() {                                   // on a phone the chat's bar is the only top bar: it shows the same state
  const chip = $("#live-chip"), cd = $("#chatchip");
  if (cd && chip) { cd.className = chip.className + " chatchip"; cd.innerHTML = chip.innerHTML; cd.title = chip.title; cd.onclick = chip.onclick; }
}
// ok (Ready), run (an agent works), off (connecting, offline, no link): the dot on Stack and the sidebar's foot
const liveState = () => (!S || Date.now() - lastState > 60000 ? "off" : S.running ? "run" : "ok");
function liveChip(chip) {
  const bar = $("#livebar");                                // shown only when something is off: an update, no link, offline
  if (bar) bar.hidden = !updateReady && liveState() !== "off";
  chip.onclick = updateReady ? () => location.reload() : null;
  if (updateReady) { chip.className = "chip live upd"; chip.innerHTML = `${ic.repeat}Update ready · tap`; return; }
  if (!S) { chip.innerHTML = noLink() ? `<span class="dot err"></span>No connection` : `<span class="dot"></span>Connecting…`; chip.className = "chip"; return; }
  if (Date.now() - lastState > 60000) { chip.className = "chip"; chip.innerHTML = `<span class="dot err"></span>Offline · ${clock(S.generated)}`; return; }
  if (S.running) { chip.className = "chip live"; chip.title = S.running.title; chip.innerHTML = `<span class="dot run"></span>Running`; }   // a title does not fit the header: Home's Now has it whole
  else { chip.className = "chip"; chip.title = ""; chip.innerHTML = `<span class="dot ok"></span>Ready`; }
  $("#side-foot").innerHTML = `<span class="dot ${S.running ? "run" : "ok"}"></span> ${S.running ? "Running" : "Ready"} · updated ${clock(S.generated, true)}`;
}

function parseRoute() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, q] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  route = { name: parts[0] || "home", args: parts.slice(1).map(decodeURIComponent), q: new URLSearchParams(q || "") };
}
let prevHash = "#/";
window.addEventListener("hashchange", (e) => { prevHash = new URL(e.oldURL).hash || "#/"; });
// APP-33: Back and Forward return to where you were on a page; a new page starts at its top. Each history entry gets an
// index (history.state.i): a step without one is a new page, one with an index is a step through the history.
const scrollAt = {};
let navIdx = history.state?.i ?? 0, navMax = navIdx, restoreTo = null;
if (history.state?.i === undefined) history.replaceState({ ...(history.state || {}), i: 0 }, "");   // the first page counts too
window.addEventListener("scroll", () => { scrollAt[location.hash || "#/"] = window.scrollY; }, { passive: true });
function navStep() {
  const i = history.state?.i;
  if (i === undefined) { navIdx = navMax = navMax + 1; history.replaceState({ ...(history.state || {}), i: navIdx }, ""); return "new"; }
  navIdx = i;
  return "history";
}
function restoreScroll(y) {                  // the page's slower parts (the map, the lists) come in after it is drawn
  let tries = 0, last = -1;
  const go = () => {
    if (last >= 0 && Math.abs(window.scrollY - last) > 2) return;          // you scrolled meanwhile: leave it
    window.scrollTo(0, y);
    last = window.scrollY;
    if (Math.abs(last - y) > 2 && ++tries < 8) setTimeout(go, 250);
  };
  go();
}
window.addEventListener("hashchange", () => {
  if (updateReady) return location.reload();
  const saved = scrollAt[location.hash || "#/"];
  restoreTo = navStep() === "history" && saved ? saved : null;
  const prev = route.name + route.args[0]; parseRoute(); if (route.name + route.args[0] !== prev) { tab = "overview"; atab = "now"; } if (route.name !== "wiki") wikiBack = ""; render(true);
});

// views that re-render on every state update (forms, chat and wiki do not, so nothing is lost while you work)
const LIVE = new Set(["home", "missions"]);
const typing = () => document.activeElement && ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
function render(force = false) {
  chrome();
  if (!force && route.name === "missions" && $("#view details[open]")) return;
  if (!force && route.name === "missions" && missionsSig() === missionsSig.last) return swOverview();   // APP-32: nothing on the list changed:
                                                                 // only its live parts update in place, the page never moves
  if (!force && route.name === "live") return;
  if (!force && !(LIVE.has(route.name) || ((route.name === "mission" || route.name === "crew") && agentSigOf() !== agentSig && !typing() && !$(".tl:not([hidden])") && !$("#tabbody details[open]")) || (route.name === "build" && !typing() && !$("#chbox:not([hidden])") && !$("#view details[open]") && !$("#blogbox:not([hidden])") && !($("#ar-url")?.value || $("#ar-name")?.value)))) return;
  // views that load their own data draw at once; the others wait for the first state (they are drawn when it comes)
  if (!S && !["chat", "wiki", "read", "guide", "phone", "share", "live", "swarm", "taskmap", "telemetry", "task", "trials"].includes(route.name)) { view.innerHTML = noLink() ? offlineHtml() : `<div class="stack"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>`; return; }
  const y = window.scrollY;
  if (force) { document.body.classList.add("anim"); clearTimeout(render.anim); render.anim = setTimeout(() => document.body.classList.remove("anim"), 600); }
  const open = force ? [] : [...view.querySelectorAll("details[open][id], details[open][data-keep]")].map((d) => d.id || d.dataset.keep);
  const fn = { tasks: vTasks, task: vTask, trials: vTrials, home: vHome, missions: vMissions, mission: vMission, new: vNew, chat: vChat, system: vSystem, read: vRead, wiki: vWiki, build: vBuild, repo: vRepo, guide: vGuide, share: vShare, phone: vPhone, house: vHouse, crew: vCrew, live: vLive, swarm: vSwarm, taskmap: vTaskMap, telemetry: vTelemetry }[route.name] || vHome;
  fn();
  for (const k of open) {                          // a live redraw keeps what you opened open
    const d = view.querySelector(`details#${CSS.escape(k)}`) || view.querySelector(`details[data-keep="${CSS.escape(k)}"]`);
    if (d) d.open = true;
  }
  if (route.name === "system") { clearInterval(connTimer); drawConnections(); connTimer = setInterval(drawConnections, 5000); }   // Stack → Connections
  document.body.classList.toggle("chatmode", route.name === "chat");
  if (!force) window.scrollTo(0, y);
  else if (restoreTo) { restoreScroll(restoreTo); restoreTo = null; }
  else if (route.name !== "chat") window.scrollTo(0, 0);
}

// ---------- shared pieces ----------
function statusPill(m) {
  const running = S.running?.slug === m.slug, queued = (S.queue || []).some((q) => q.slug === m.slug);
  if (running) return `<span class="pill running"><span class="dot run"></span>Running</span>`;
  const q = (S.queue || []).find((x) => x.slug === m.slug);
  if (q?.status === "parked") return `<span class="pill paused">Waiting · ${esc(q.waiting_for || "a slow step")}</span>`;
  if (q?.status === "waiting") return `<span class="pill paused">Waiting for ChatGPT · ${q.retry_at ? clock(q.retry_at) : "soon"}</span>`;
  if (queued) return `<span class="pill queued">Queued</span>`;
  return `<span class="pill ${m.status}">${STATUS[m.status] || m.status}</span>`;
}

function missionCard(m) {
  const last = m.runs?.[0];
  const running = S.running?.slug === m.slug;
  const sp = spark((m.runs || []).slice(0, 12).reverse().map((r) => r.tokens || 0));
  return `<a class="card mcard fadein ${running ? "is-running" : ""}" href="#/mission/${encodeURIComponent(m.slug)}">
    ${sp}
    <div class="row"><div class="type-ic">${typeIcon(m.type)}</div><div class="grow" style="padding-right:90px">
      <div class="t wrap">${esc(m.title)}</div>
      <div class="row small muted" style="gap:8px;margin-top:2px">${statusPill(m)}<span>${typeName(m.type)}${m.depth === "deep" ? " · deep" : ""}</span></div>
    </div></div>
    <div class="meta">
      <span>${ic.clock}${esc(m.schedule_text)}${m.next_run ? ` · ${rel(m.next_run)}` : ""}</span>
      ${m.triggers?.length ? `<span>${ic.radar}${m.triggers.length} trigger${m.triggers.length > 1 ? "s" : ""}</span>` : ""}
      <span>${ic.repeat}${m.stats.runs} runs</span>
      <span>${ic.bolt}${tok(m.stats.tokens)} tokens</span>
      <span>${ic.coin}${usd(m.stats.spend)}</span>
      ${m.wiki_pages ? `<span>${ic.wiki}${m.wiki_pages} pages</span>` : ""}
    </div>
    ${last ? `<div class="last">${last.status === "failed" ? "⚠ " : last.event ? "⚡ " : ""}${esc(last.summary || STATUS[last.status])}</div>` : `<div class="last">No run yet.</div>`}
  </a>`;
}

// a deep run's steps; each finding is the agent's markdown, folded so the card stays short (the newest one open)
function stepsHtml(steps) {
  if (!steps?.length) return "";
  const last = steps.map((s) => !!s.finding).lastIndexOf(true);
  return `<ol class="steps">${steps.map((s, i) => `<li class="${s.status}"><span class="sdot">${s.status === "done" ? ic.check : s.status === "failed" ? ic.x : ""}</span><div class="sbody"><b>${esc(s.title)}</b><div class="small muted">${esc(s.question)}</div>${s.finding ? `<details class="sfind"${i === last ? " open" : ""}><summary class="tiny">What it found</summary><div class="md small">${md(s.finding)}</div></details>` : ""}</div></li>`).join("")}</ol>`;
}

function runningCard() {
  const r = S.running;
  if (!r) return "";
  const href = r.slug ? `#/mission/${encodeURIComponent(r.slug)}` : "";
  return `<div class="card runcard fadein"${href ? ` data-href="${href}"` : ""}>
    <div class="row between"><a class="row grow" href="${href || "#/"}"><span class="dot run"></span><b class="wrap">${esc(r.title)}</b>${href ? `<span class="tiny faint">${ic.next}</span>` : ""}</a><span class="small muted num" data-since="${esc(r.started)}"></span></div>
    <div class="small muted" style="margin-top:4px">${r.event ? "⚡ " + esc(r.event.trigger || "Event") : TRIG[r.trigger] === "scheduled" ? "Scheduled run" : "Started on demand"}${r.mode === "deep" ? " · deep research" : r.mode === "alert" ? " · alert" : ""}</div>
    ${r.event ? `<div class="small" style="margin-top:6px">${esc(r.event.summary)}</div>` : ""}
    ${stepsHtml(r.steps)}
    <div class="log" id="livelog">${esc((r.tail || []).join("\n")) || "Starting…"}</div>
  </div>`;
}

function activityList(n = 12) {
  const ev = (S.activity || []).slice(0, n);
  if (!ev.length) return `<div class="card empty small">No activity yet</div>`;
  const kind = { run_done: ["ok", ic.check], run_failed: ["err", ic.x], run_started: ["run", ic.play], created: ["ok", ic.plus], error: ["err", ic.alert],
    budget: ["warn", ic.coin], pause: ["warn", ic.pause], resume: ["ok", ic.play], archive: ["", ic.archive], queued: ["run", ic.clock],
    updated: ["", ic.tune], memory: ["", ic.brain], triggered: ["warn", ic.bolt], waiting: ["warn", ic.clock], swarm: ["", ic.radar], deploy: ["ok", ic.rocket] };
  return `<div class="card list">${ev.map((e) => {
    const [cls, icon] = kind[e.kind] || ["", ic.pulse];
    // build events open their build; the stack's ideas and the swarm's changes open the Code list
    const bn = e.kind === "build" && !e.slug && /^Build #(\d+)/.exec(e.text || "");
    const href = e.slug ? `#/mission/${encodeURIComponent(e.slug)}` : bn ? `#/build/${bn[1]}` : (e.kind === "build" && /^The stack proposes/.test(e.text || "")) || e.kind === "swarm" ? "#/swarm?tab=improve" : "#/system";
    return `<a href="${href}"><div class="ic ${cls}">${icon}</div><div class="grow"><div class="ttl wrap">${esc(e.title || "System")}</div><div class="sub">${esc(e.text)}</div></div><div class="tiny faint" style="white-space:nowrap">${rel(e.ts)}</div></a>`;
  }).join("")}</div>`;
}

function callsList(n = 10) {
  const c = (S.calls || []).slice(0, n);
  if (!c.length) return `<div class="card empty small">No model calls</div>`;
  return `<div class="card list">${c.map((x) => `<div><span class="agent ${esc(x.agent)}">${esc(x.agent)}</span><div class="grow small"><span class="num">${tok(x.tokens)}</span> <span class="muted">tokens · ${esc(x.model)}</span></div><div class="tiny faint">${rel(x.ts)}</div></div>`).join("")}</div>`;
}

// ---------- home ----------
function workBuildRow(b) {
  const cls = bcls(b.status), review = b.ai_review;
  const verdict = !review ? "Not done" : review.pending ? "Reviewing" : review.error ? "Unavailable" : VERDICT[review.verdict]?.[1] || "Not done";
  return `<a href="#/build/${b.id}"><div class="ic ${cls === "running" ? "run" : ""}">${b.status === "review" ? ic.search : ic.rocket}</div>
    <div class="grow small"><span class="ttl">#${b.id} ${esc(b.title)}</span> · <span class="pill ${cls}" style="padding:1px 7px">${BSTATUS[b.status] || b.status}</span>${b.status === "review" ? ` · Checks: ${b.checks ? (b.checks_ok ? "Passed" : "Failed") : "Not run yet"} · CI: ${esc(b.ci || "Not pushed yet")} · AI review: ${esc(verdict)}` : ""}</div></a>`;
}

// ---------- app connections (Gmail first): time-limited grants, first-Trash approvals, log ----------
const CONN_NAME = { gmail: "Gmail" };
const GRANT_FOR = [[60, "1 hour"], [480, "8 hours"], [-1, "Until I revoke"]];
function untilText(t) {
  return t > Date.now() / 1000 + 365 * 86400 ? "until you revoke it" : "until " + dt(t);
}
function grantRow(conn, scope, what, until, mission) {
  return `<div class="row between wrap cgrant" style="gap:8px;align-items:center"><div><b>${esc(scope)}</b> <span class="small muted">${esc(what)}</span>
      <div class="tiny ${until ? "" : "faint"}">${until ? `<span class="pill ok" style="padding:1px 7px">granted</span> ${untilText(until)}` : "not granted"}</div></div>
    <div class="row wrap" style="gap:6px">${until ? `<button class="btn sm ghost danger" data-cgrant="${conn}:${scope}:0">Revoke</button>`
      : GRANT_FOR.map(([m, l]) => `<button class="btn sm" data-cgrant="${conn}:${scope}:${m}${mission ? ":" + esc(mission) : ""}">${l}</button>`).join("")}</div></div>`;
}
function connPendingHtml(list) {
  return list.map((p) => `<div class="card pad-l phreq" style="margin-top:10px"><div class="tag">Waiting for your OK · ${esc(CONN_NAME[p.conn] || p.conn)}${p.mission ? " · " + esc(p.mission) : ""}</div>
    <h2 style="margin:8px 0 4px">Move ${p.count} mails to Trash?</h2><div class="small">${esc(p.reason || "")}</div>
    <div class="small muted" style="margin-top:8px">Most from: ${(p.top_senders || []).slice(0, 5).map(([f, n]) => `${esc(f)} (${n})`).join(", ")}</div>
    <ul class="small" style="margin:6px 0 0 16px">${(p.sample || []).slice(0, 10).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <div class="tiny faint" style="margin-top:6px">Trash only: Gmail empties it after 30 days, and the batch can be undone. Bank and security mails are never included. This OK covers this grant's later batches too.</div>
    <div class="row wrap" style="gap:8px;margin-top:12px"><button class="btn primary" data-cdec="${p.id}:1">${ic.check}Move to Trash</button><button class="btn ghost" data-cdec="${p.id}:0">${ic.x}Don't</button></div></div>`).join("");
}
let connTimer = null;
async function drawConnections() {
  if (!$("#conncard")) return clearInterval(connTimer);
  const C = await api("/api/connections").catch(() => null);
  const el = $("#conncard");                                  // look it up after the wait: the page may have been redrawn
  if (!C || !el || el.querySelector("details[open]")) return;
  el.innerHTML = C.connections.map((c) => {
    const st = c.status || {};
    return `<div class="card pad-l"><div class="row between wrap" style="gap:8px;align-items:center"><div><b>${esc(CONN_NAME[c.id] || c.id)}</b> <span class="small muted">${esc(st.account || "")}</span>
        <div class="tiny muted">${st.ok ? `connected · ${nf(st.inbox_unread || 0)} unread in the inbox · ${nf(st.spam || 0)} in spam` : st.configured === false ? "not set up (make email-setup)" : esc(st.error || "checking…")}</div></div></div>
      <div class="stack" style="margin-top:10px;gap:10px">${Object.entries(c.scopes).map(([s, what]) => grantRow(c.id, s, what, c.grants[s]?.until)).join("")}</div>
      ${connPendingHtml(C.pending.filter((p) => p.conn === c.id))}
      <details style="margin-top:10px"><summary class="small muted">What it did · ${C.log.filter((e) => e.conn === c.id).length}</summary><ul class="phlog">${C.log.filter((e) => e.conn === c.id).map((e) => `<li><span class="tiny faint">${dt(e.at)}</span> <b>${esc(e.action)}</b> ${esc(e.scope || e.query || e.reason || "")}${e.count != null ? ` · ${e.count}` : ""}${e.found != null ? ` · ${e.found} found` : ""}${e.batch ? ` · batch ${esc(e.batch)}` : ""}${e.mission ? ` · ${esc(e.mission)}` : ""}</li>`).join("")}</ul></details></div>`;
  }).join("");
}
document.addEventListener("click", async (e) => {                     // grant buttons live in redrawn cards: delegate
  const g = e.target.closest("[data-cgrant]"), d = e.target.closest("[data-cdec]");
  if (g) {
    const [conn, scope, minutes, mission] = g.dataset.cgrant.split(":");
    const r = await api("/api/connections/grant", { method: "POST", body: JSON.stringify({ conn, scope, minutes: +minutes, mission }) }).catch((err) => ({ error: err.message }));
    toast(r.error || (+minutes === 0 ? `${CONN_NAME[conn]} ${scope}: revoked` : `${CONN_NAME[conn]} ${scope}: granted`), !!r.error);
    drawConnections(); if (route.name === "mission") setTimeout(() => render(true), 2500);
  } else if (d) {
    const [id, allow] = d.dataset.cdec.split(":");
    const r = await api("/api/connections/decide", { method: "POST", body: JSON.stringify({ id, allow: allow === "1" }) }).catch((err) => ({ error: err.message }));
    toast(r.error || (allow === "1" ? "OK: moving to Trash" : "Declined: nothing moved"), !!r.error);
    drawConnections();
  }
});

// ---------- your devices on Home: the AI phone's state and its allowance in one tap ----------
function devicesHtml() {
  const p = S.phone;
  if (!p) return '<div id="homedev" hidden></div>';
  const now = Date.now() / 1000, trust = p.trust_until > now, forever = p.trust_until > now + 365 * 86400;
  const state = p.stopped ? ["failed", "Stopped"] : p.connected ? ["ok", "Connected"] : ["paused", "Not connected"];
  return `<div id="homedev" class="card pad-l devcard" style="margin-bottom:14px">
    <div class="row between wrap" style="gap:8px;align-items:center">
      <a class="row" style="gap:10px;align-items:center" href="#/phone"><div class="repo-ic">${ic.bolt}</div><div><b>AI phone</b> <span class="small muted">${esc(p.model || "")}</span>
        <div class="row wrap small muted" style="gap:6px;align-items:center"><span class="pill ${state[0]}" style="padding:1px 7px">${state[1]}</span>${p.connected ? esc(p.foreground || "home screen") : ""}${p.pending ? ` · <b class="err-t">${p.pending} waiting for your OK</b>` : ""}</div></div></a>
      <a class="btn sm ghost" href="#/phone">Open ${ic.next}</a></div>
    ${p.connected && !p.stopped ? `<div class="row wrap" style="gap:6px;margin-top:10px;align-items:center">
      ${trust ? `<span class="small"><b>Works without asking ${forever ? "until you stop it" : "until " + clock(p.trust_until)}</b></span><button class="btn sm ghost" data-devtrust="0">Ask me again</button>`
        : `<span class="small muted">Let it work without asking:</span>${[[10, "10 min"], [60, "1 hour"], [-1, "Until I stop it"]].map(([m, l]) => `<button class="btn sm" data-devtrust="${m}">${l}</button>`).join("")}`}
      <button class="btn sm ghost danger" data-devstop="1">${ic.pause}Stop</button></div>
      <div class="tiny faint" style="margin-top:6px">Then just tell Hermes in Chat what to do on the AI phone. Spending money always asks you.</div>` : ""}
  </div>`;
}
// a card that stands for a page opens it on a tap anywhere, except on its own links, buttons, folds and selected text
document.addEventListener("click", (e) => {
  const card = e.target.closest("[data-href]");
  if (!card || e.target.closest("a,button,summary,details,input,select,textarea,label,form") || String(getSelection() || "")) return;
  location.hash = card.dataset.href;
});
document.addEventListener("click", async (e) => {                     // the devices card is redrawn live: delegate
  const t = e.target.closest("[data-devtrust],[data-devstop]");
  if (!t) return;
  const body = t.dataset.devstop ? { do: "stop" } : { do: "trust", minutes: +t.dataset.devtrust };
  const r = await api("/api/phone/control", { method: "POST", body: JSON.stringify(body) }).catch((err) => ({ error: err.message }));
  toast(r.error || (body.do === "stop" ? "AI phone stopped" : body.minutes === 0 ? "It asks again for every action" : body.minutes < 0 ? "Works without asking until you stop it" : `Works without asking for ${body.minutes} minutes`), !!r.error);
});

// ---------- Tasks (TSK-01 to TSK-04): give a task in a sentence, or with its details set; every task on one board ----------
const TGROUPS = [["Waiting on you", ["needs_answer", "waiting_approval", "waiting_owner"]], ["Running", ["intake", "planning", "planned", "running", "after"]],
  ["Scheduled", ["scheduled"]], ["Done", ["done", "failed", "cancelled"]]];
const TSTATUS = { intake: "being planned", planning: "being planned", planned: "starting", needs_answer: "has a question", waiting_approval: "waits for your OK",
  waiting_owner: "waits for your review", running: "running", after: "waits for another task", scheduled: "scheduled", done: "done", failed: "failed", cancelled: "cancelled" };
const TKINDS = { coding: "Coding", code_question: "Question about code", research: "Research", analysis: "Analysis", watching: "Watching", briefing: "Briefing", shopping: "Shopping", errand: "Errand" };
const TDOOR = { mission: (r) => [`#/mission/${encodeURIComponent(r)}`, "Open the mission"], build: (r) => [`#/build/${r}`, `Open build #${r}`],
  claude: (r) => [`#/live/claude-task:${r}`, `Open Claude task #${r}`], chat: (r) => [`#/chat?c=${r}`, "Open the chat"] };
const openTasks = () => (S?.tasks || []).filter((t) => !["done", "failed", "cancelled"].includes(t.status)).length;
const rhythmText = (r, after) => r?.type === "schedule" ? r.schedule : r?.type === "event" ? `on ${(r.triggers || []).map((x) => x.type === "news" ? `news on “${x.query}”` : x.type === "price_move" ? `a ${x.pct} % move of ${x.symbol}` : `SEC filings of ${(x.tickers || []).join(", ")}`).join(", ")}`
  : r?.type === "after" || after ? `after task #${r?.task || after}` : "once";
let taskOpen = null;
// FND-77: a scheduled task says what its last run did and when the next one comes, so "scheduled" never reads as "waiting";
// the date in English like the rest of the app (DEC-02), in the browser's time zone
const nextText = dt;
const ranText = (t) => t.last_run ? (t.last_run.ended ? `ran ${rel(t.last_run.ended)}` : "running now") : "";
// TSK-21: a task on an event says it waits for its trigger, not "scheduled"
const tstat = (t) => t.door === "plan" && t.rhythm?.type === "event" && ["scheduled", "running"].includes(t.status)
  ? [ranText(t), t.status === "scheduled" ? "waits for its trigger" : ""].filter(Boolean).join(" · ")
  : !["mission", "plan"].includes(t.door) || !["scheduled", "running"].includes(t.status) || (t.door === "plan" && !t.next_run) ? TSTATUS[t.status] || t.status
  : [ranText(t) || "first run starting", t.next_run ? `next ${nextText(t.next_run)}` : ""].filter(Boolean).join(" · ");
function lastRunHtml(t) {
  const r = t.last_run;
  if (!r) return "";
  return `<div class="tlabel">${r.ended ? "Last run" : "Running now"}</div><p class="${r.status === "ok" || !r.ended ? "" : "err-t"}">${esc(r.summary || (r.ended ? r.status : "started " + rel(r.started)))}</p>
    <div class="row" style="gap:8px">${r.output ? `<a class="btn sm primary" href="#/read?path=${encodeURIComponent(r.output)}${t.door === "mission" ? `&m=${encodeURIComponent(t.ref)}` : ""}">${ic.doc}Read it</a>` : ""}<a class="btn sm ghost" href="#/live/${encodeURIComponent(r.live || `mission-run:${r.id}`)}">${ic.pulse}How it ran</a>${t.door === "plan" && ["scheduled", "done", "failed"].includes(t.status) ? `<button class="btn sm ghost" data-trun="${t.id}">${ic.play}Run again now</button>` : ""}</div>
    ${t.door === "mission" && ["briefing", "shopping"].includes(t.kind) && t.status === "scheduled" ? `${explain("it-still-runs-as-its-own", `It still runs as its own mission. Under the Conductor each run is planned steps (${t.kind === "briefing" ? "collect, a scout per key question, write, deliver" : "its shopping agent's check"}), judged on its own and shown here.`, "About this")}
      <button class="btn sm" data-tconduct="${t.id}" style="margin-top:6px">${ic.layers}Run it under the Conductor</button>` : ""}`;
}

// TSK-22: each run of a recurring task with how it started, its own verdict against the definition of done and its answer
const VWORD = { met: ["met", ""], partly: ["partly met", "warn-t"], "not met": ["not met", "err-t"], failed: ["failed", "err-t"], quiet: ["nothing new", "faint"], "not judged": ["not judged", "faint"] };
const HOW = { start: "at once", schedule: "on its schedule", owner: "you ran it" };
function runsHtml(t) {
  const rs = t.runs || [];
  if (!rs.length || (rs.length < 2 && !["schedule", "event"].includes(t.rhythm?.type))) return "";   // a one-off: the last run says it
  return `<div class="tlabel">Runs</div><ol class="truns">${rs.map((r) => {
    const [word, cls] = r.status === "running" ? ["running now", "warn-t"] : r.status === "cancelled" ? ["cancelled", "faint"]
      : VWORD[r.verdict] || (r.status === "failed" ? VWORD.failed : ["not judged yet", "faint"]);
    const pts = r.judgement?.points || [];
    return `<li><a href="#/live/${encodeURIComponent(r.live)}">Run ${r.occ}</a> · ${esc(r.trigger === "event" ? r.event?.trigger || "an event" : HOW[r.trigger] || r.trigger)} · ${esc(nextText(r.started))}
      · <span class="${cls}">${esc(word)}</span>${pts.length ? ` <span class="faint">(${pts.filter((p) => p.met).length} of ${pts.length} points)</span>` : ""}${r.tokens ? ` · ${tok(r.tokens)} tokens${r.cost != null ? `, ${ifPaid(r.cost)}` : ""}` : ""}${(r.result || "").startsWith("tasks/") ? ` · <a href="#/read?path=${encodeURIComponent(r.result)}">read it</a>` : ""} · <a href="#/taskmap?t=${t.id}&o=${r.occ}">map</a>
      ${r.event?.summary ? `<div class="faint">${esc(r.event.summary)}</div>` : ""}</li>`; }).join("")}</ol>`;
}

// ---------- TSK-24: the swarm map of a task's run ----------
// Flow: what was read (sources, by site), who worked (each step and its agent), what they found, what came out; a tap
// shows where a part came from and what it fed. Sources read but never cited are dashed. Timeline: one lane per agent
// run, dots for what it read, squares for what it made. Drawn from public/maps/<task>.<occ>.json (ops/provenance.py),
// redrawn every 5 s while the run goes on. On a phone the map pans sideways instead of shrinking.
let tmapMode = "flow", tmapTimer = null, tmapPick = null;
const TM_KIND = { page: "Page", item: "News item", job: "Job ad", note: "Vault note", memory: "Memory", search: "Search", finding: "Finding",
  report: "Report", result: "The answer", delivery: "Delivery", wiki: "Wiki page", file: "File" };
const TM_OUT = new Set(["report", "result", "delivery", "wiki"]);
const tmShort = (s, n = 26) => (s = String(s || ""), s.length > n ? s.slice(0, n - 1) + "…" : s);   // cap: preview: a box's label; the panel names it whole
const tmOpen = (a) => !a ? "" : a.uri.startsWith("http") ? `<a class="btn sm" href="${esc(a.uri)}" target="_blank" rel="noopener noreferrer">${ic.next}Open the page</a>`
  : a.uri.startsWith("vault:") ? `<a class="btn sm" href="#/read?path=${encodeURIComponent(a.uri.slice(6))}">${ic.doc}Read it</a>` : "";

function tmapGraph(d) {
  const A = Object.fromEntries(d.artifacts.map((a) => [a.id, a]));
  const cited = new Set(d.links.filter((l) => l.rel === "cited").map((l) => l.artifact));
  const nodes = new Map(), edges = new Map();
  const add = (n) => (nodes.has(n.id) ? nodes.get(n.id) : (nodes.set(n.id, n), n));
  const edge = (a, b, kind) => a && b && a !== b && edges.set(`${a}>${b}`, { a, b, kind });
  for (const s of d.steps) add({ id: `step:${s.idx}`, col: 1, label: s.item || s.title, sub: s.agent, step: s, kind: "step" });
  const used = d.links.filter((l) => l.rel === "used" && A[l.artifact]);
  const bySite = {};
  for (const l of used) (bySite[A[l.artifact].kind === "search" ? `search:${l.artifact}` : A[l.artifact].site || A[l.artifact].kind] ??= new Set()).add(l.artifact);
  const srcNode = {};
  for (const [key, ids] of Object.entries(bySite)) {
    const list = [...ids];
    if (list.length > 3) {                                     // a site with many pages is one box with a count
      const n = add({ id: `site:${key}`, col: 0, label: `${key} · ${list.length}`, sub: `${list.filter((i) => cited.has(i)).length} cited`, members: list, kind: "site",
        cited: list.some((i) => cited.has(i)), read: true });
      list.forEach((i) => (srcNode[i] = n.id));
    } else list.forEach((i) => { const a = A[i]; add({ id: i, col: 0, label: a.title || a.uri, sub: TM_KIND[a.kind] || a.kind, art: a, kind: a.kind, cited: cited.has(i), read: a.kind !== "search" }); srcNode[i] = i; });
  }
  for (const l of used) edge(srcNode[l.artifact], `step:${l.step}`, "used");
  const madeBy = {};
  for (const l of d.links.filter((x) => x.rel === "generated" && A[x.artifact])) {
    const a = A[l.artifact];
    add({ id: a.id, col: TM_OUT.has(a.kind) ? 3 : 2, label: a.title || a.uri, sub: TM_KIND[a.kind] || a.kind, art: a, kind: a.kind });
    madeBy[a.id] = l.step ? `step:${l.step}` : null;
    if (l.step) edge(`step:${l.step}`, a.id, "generated");
  }
  for (const l of d.links.filter((x) => x.rel === "derived" && nodes.has(x.artifact) && nodes.has(x.src))) {
    const into = nodes.get(l.artifact), from = nodes.get(l.src);
    if (from.col < 2) continue;
    if (into.col === 3 || !madeBy[l.artifact]) edge(l.src, l.artifact, "derived");          // a finding goes into the output
    else if (madeBy[l.src]) edge(madeBy[l.src], madeBy[l.artifact], "chain");             // a step's finding feeds the next step
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()], A, cited };
}

function tmapFlow(box, d, g) {
  const COLS = ["What was read", "Who worked", "What they found", "What came out"], CW = 176, GAP = 46, NH = 34, VG = 8, TOP = 26;
  const cols = [0, 1, 2, 3].map((k) => g.nodes.filter((n) => n.col === k));
  cols[0].sort((a, b) => (b.cited - a.cited) || ((b.members?.length || 1) - (a.members?.length || 1)));
  cols[1].sort((a, b) => a.step.idx - b.step.idx);
  const shown = [0, 1, 2, 3].filter((k) => cols[k].length);   // an empty column takes no room (a run that read nothing)
  const H = TOP + Math.max(...cols.map((c) => c.length), 1) * (NH + VG) + 10, W = shown.length * CW + (shown.length - 1) * GAP + 34;
  shown.forEach((k, j) => cols[k].forEach((n, i) => { n.x = 2 + j * (CW + GAP); n.y = TOP + i * (NH + VG); }));
  const at = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  const stroke = (n) => n.kind === "step" ? (n.step.status === "failed" ? "var(--err)" : n.step.status === "running" ? "var(--warn)" : "var(--accent)")
    : n.col === 0 ? (n.cited ? "var(--accent)" : "var(--border-2)") : TM_OUT.has(n.kind) ? "var(--accent-2)" : "var(--border-2)";
  box.innerHTML = `<div class="tmap-wrap"><svg class="tmapsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="The swarm of this run">
    ${shown.map((k, j) => `<text x="${2 + j * (CW + GAP)}" y="14" class="tmcol">${COLS[k]}</text>`).join("")}
    ${g.edges.map((e) => { const a = at[e.a], b = at[e.b]; if (!a || !b) return ""; const y1 = a.y + NH / 2, y2 = b.y + NH / 2;
      const p = e.kind === "chain" ? (() => { const x = a.x + CW, bend = x + 14 + Math.min(16, Math.abs(y2 - y1) / 6); return `M${x},${y1} C${bend},${y1} ${bend},${y2} ${x},${y2}`; })()   // step to step, beside the column
        : (() => { const x1 = a.x + CW, x2 = b.x, m = (x1 + x2) / 2; return `M${x1},${y1} C${m},${y1} ${m},${y2} ${x2},${y2}`; })();
      return `<path d="${p}" class="tmedge ${e.kind}${a.col === 0 && !a.cited ? " uncited" : ""}" data-e="${esc(e.a)}|${esc(e.b)}"${e.kind === "chain" ? ' marker-end="url(#tmarrow)"' : ""}/>`; }).join("")}
    <defs><marker id="tmarrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="var(--accent-2)"/></marker></defs>
    ${g.nodes.map((n) => `<g class="tmnode" data-n="${esc(n.id)}" tabindex="0" role="button" transform="translate(${n.x},${n.y})"><title>${esc(n.label)}</title>
      <rect width="${CW}" height="${NH}" rx="8" fill="var(--surface-2)" stroke="${stroke(n)}" stroke-width="${n.cited || n.kind === "step" ? 2 : 1.2}" ${n.col === 0 && n.read && !n.cited ? 'stroke-dasharray="4 3" opacity="0.7"' : ""}/>
      <text x="9" y="14" class="tml">${esc(tmShort(n.label))}</text><text x="9" y="27" class="tms">${esc(tmShort(n.sub || "", 30))}</text></g>`).join("")}
  </svg></div>`;
  if (!g.nodes.length) box.innerHTML = `<div class="card pad small muted">Nothing is recorded for this run yet.</div>`;
  $$(".tmnode", box).forEach((el) => (el.onclick = el.onkeydown = (e) => { if (e.type === "keydown" && e.key !== "Enter") return; tmapPick = el.dataset.n; tmapInfo(d, g); }));
  if (tmapPick && at[tmapPick]) tmapInfo(d, g);
}

function tmapInfo(d, g) {
  const n = g.nodes.find((x) => x.id === tmapPick), el = $("#tminfo");
  if (!n || !el) return;
  $$(".tmnode").forEach((x) => x.classList.toggle("on", x.dataset.n === n.id));
  $$(".tmedge").forEach((x) => x.classList.toggle("on", x.dataset.e.split("|").includes(n.id)));
  const name = (id) => { const x = g.nodes.find((y) => y.id === id); return x ? `<button class="linkbtn" data-tm="${esc(id)}">${esc(tmShort(x.label, 60))}</button>` : ""; };
  const from = g.edges.filter((e) => e.b === n.id).map((e) => name(e.a)), fed = g.edges.filter((e) => e.a === n.id).map((e) => name(e.b));
  const s = n.step, run = s ? `task:${d.task}${d.occ > 1 ? "." + d.occ : ""}:step:${s.idx}` : "";
  const members = (n.members || []).map((i) => g.A[i]).map((a) => `<li class="${g.cited.has(a.id) ? "" : "faint"}">${g.cited.has(a.id) ? "cited · " : "read, not cited · "}<a href="${esc(a.uri)}" target="_blank" rel="noopener noreferrer">${esc(a.title || a.uri)}</a></li>`).join("");
  el.innerHTML = `<div class="card pad tminfo"><div class="tiny faint">${esc(s ? `Step ${s.idx} · ${s.agent} · ${s.harness} · ${s.status}` : n.kind === "site" ? "A site" : TM_KIND[n.kind] || n.kind)}${n.col === 0 && n.read ? (n.cited ? " · cited in the answer" : " · read, not cited") : ""}</div>
    <div class="ttl wrap" style="margin-top:4px">${esc(s ? s.title : n.label)}</div>
    ${n.art && n.art.uri !== n.label ? `<div class="tiny faint wrap">${esc(n.art.uri)}</div>` : ""}
    ${members ? `<ul class="tmlist">${members}</ul>` : ""}
    ${from.length ? `<div class="small" style="margin-top:8px">Came from: ${from.join(", ")}</div>` : ""}
    ${fed.length ? `<div class="small" style="margin-top:4px">Fed: ${fed.join(", ")}</div>` : ""}
    <div class="row wrap" style="gap:8px;margin-top:10px">${tmOpen(n.art)}${s ? `<a class="btn sm" href="#/live/${encodeURIComponent(run)}">${ic.pulse}How it ran</a>` : ""}</div></div>`;
  $$("[data-tm]", el).forEach((b) => (b.onclick = () => { tmapPick = b.dataset.tm; tmapInfo(d, g); }));
}

function tmapTimeline(box, d) {
  const lanes = (d.lanes.length ? d.lanes : d.steps.filter((s) => s.started).map((s) => ({ run: `step:${s.idx}`, agent: s.agent, step: s.idx, own: true,
    started: Date.parse(s.started) / 1000, ended: s.ended ? Date.parse(s.ended) / 1000 : null, state: s.status })))
    .slice().sort((a, b) => a.step - b.step || !b.own - !a.own || a.started - b.started);
  if (!lanes.length) { box.innerHTML = `<div class="card pad small muted">No step has started yet.</div>`; return; }
  const nowS = Date.now() / 1000, t0 = Math.min(...lanes.map((l) => l.started)), t1 = Math.max(...lanes.map((l) => l.ended || nowS), t0 + 1);
  const LW = 118, W = Math.max((box.clientWidth || 340) - 20, 300), LH = 26, H = 22 + lanes.length * LH;
  const x = (s) => LW + (s - t0) / (t1 - t0) * (W - LW - 10);
  const A = Object.fromEntries(d.artifacts.map((a) => [a.id, a]));
  const marks = d.links.filter((l) => (l.rel === "used" || l.rel === "generated") && A[l.artifact]);
  const fmt = (s) => s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;
  box.innerHTML = `<div class="tmap-wrap"><svg class="tmapsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="When each agent worked">
    <text x="${LW}" y="12" class="tmcol">0</text><text x="${W - 10}" y="12" class="tmcol" text-anchor="end">${fmt(t1 - t0)}</text>
    ${lanes.map((l, i) => { const y = 20 + i * LH, end = l.ended || nowS, mine = marks.filter((m) => m.run === l.run || (l.own && m.step === l.step && !m.at));
      return `<g><title>${esc(`${l.agent} · step ${l.step} · ${fmt(end - l.started)}${l.tokens ? ` · ${tok(l.tokens)} tokens${l.cost != null ? `, ${ifPaid(l.cost)}` : ""}${l.models?.length ? ` (${l.models.join(", ")})` : ""}` : ""}`)}</title><text x="${l.own ? 0 : 12}" y="${y + 15}" class="${l.own ? "tml" : "tms"}">${esc(tmShort(`${l.own ? `${l.step}. ` : "↳ "}${l.agent}`, 22))}</text>
        <rect x="${x(l.started)}" y="${y + 4}" width="${Math.max(3, x(end) - x(l.started))}" height="${LH - 10}" rx="4" class="tmbar ${l.state === "failed" ? "bad" : l.ended ? "" : "live"}"/>
        ${mine.map((m) => m.rel === "used" ? `<circle cx="${x(m.at || l.started)}" cy="${y + LH / 2}" r="3" class="tmdot"><title>${esc(A[m.artifact].title || A[m.artifact].uri)}</title></circle>`
          : `<rect x="${x(end) - 4}" y="${y + LH / 2 - 4}" width="8" height="8" class="tmsq"><title>${esc(A[m.artifact].title || A[m.artifact].uri)}</title></rect>`).join("")}</g>`; }).join("")}
  </svg></div><div class="tiny faint" style="margin-top:6px">A bar is an agent at work; ● what it read, ■ what it made. Indented: an agent another one called in.</div>`;
}

async function vTaskMap() {
  clearTimeout(tmapTimer);
  const t = +route.q.get("t"), o = route.q.get("o");
  if (!view.querySelector("#tmap")) view.innerHTML = `<a class="back" href="#/task/${t}">${ic.back}Task #${t}</a><div id="tmap"><div class="skeleton" style="height:320px"></div></div>`;
  const d = await api(`/api/task/map?t=${t}${o ? `&o=${encodeURIComponent(o)}` : ""}`).catch((e) => ({ error: e.message }));
  if (route.name !== "taskmap" || +route.q.get("t") !== t) return;
  const box = $("#tmap");
  if (!box) return;
  if (d.error) { box.innerHTML = `<div class="card empty">${esc(d.error)}</div>`; return; }
  const task = (S?.tasks || []).find((x) => x.id === t), n = d.numbers, r = d.run || {};
  const g = tmapGraph(d);
  box.innerHTML = `<div class="hero heading" style="margin-bottom:10px"><h1 class="wh1">${esc(d.title)}</h1>
      <p>${esc([`Run ${d.occ}`, r.trigger === "event" ? "started by an event" : HOW[r.trigger] || r.trigger, r.status === "running" ? "running now" : r.status, r.verdict && (VWORD[r.verdict] || [r.verdict])[0]].filter(Boolean).join(" · "))}</p></div>
    ${(task?.runs || []).length > 1 ? `<div class="chips" style="margin-bottom:10px">${task.runs.map((x) => `<a class="tag${x.occ === d.occ ? " on" : ""}" href="#/taskmap?t=${t}&o=${x.occ}">Run ${x.occ}</a>`).join("")}</div>` : ""}
    <div class="tmnums">${[[`${n.read} → ${n.cited}`, "sources read → cited"], [`${n.agents}`, `agents, ${n.parallel} at once at most`], [n.wall_s != null ? (n.wall_s < 90 ? `${n.wall_s} s` : `${Math.round(n.wall_s / 60)} min`) : "–", "from start to end"], [n.tokens != null ? tok(n.tokens) : "–", n.cost != null ? `tokens · ${ifPaid(n.cost)}` : "tokens"]]
      .map(([v, l]) => `<div class="card pad tmnum"><b>${esc(v)}</b><span class="tiny faint">${esc(l)}</span></div>`).join("")}</div>
    <div class="seg" style="margin:12px 0">${[["flow", "Flow"], ["time", "Timeline"]].map(([k, l]) => `<button data-tmm="${k}" class="${tmapMode === k ? "on" : ""}">${l}</button>`).join("")}</div>
    <div id="tmbody"></div><div id="tminfo" style="margin-top:10px"></div>
    ${explain("tmapmode-flow-tap-a-box-", `${tmapMode === "flow" ? "Tap a box: where it came from and what it fed. A dashed source was read but not cited; a site with many pages is one box with its count." : ""}`, "How to read this")}`;
  $$("[data-tmm]").forEach((b) => (b.onclick = () => { tmapMode = b.dataset.tmm; vTaskMap(); }));
  if (tmapMode === "flow") tmapFlow($("#tmbody"), d, g); else tmapTimeline($("#tmbody"), d);
  if (r.status === "running") tmapTimer = setTimeout(() => route.name === "taskmap" && vTaskMap(), 5000);   // live while it runs
}

// ---------- TSK-19: outside agents over A2A: off until you switch it on; each with its own token; their tasks wait for you ----------
function a2aCardHtml() {
  const a = S?.a2a || { enabled: false, agents: [] };
  return `<div class="card pad" id="a2acard" style="margin-bottom:14px"><div class="row between wrap" style="gap:8px"><b>Outside agents (A2A)</b>
      <label class="tag"><input type="checkbox" data-a2aon${a.enabled ? " checked" : ""}> ${a.enabled ? "on" : "off"}</label></div>
    ${explain("agents-on-your-tailnet-c", `Agents on your tailnet can give the stack a task over A2A, each with its own token; every task from outside waits for your OK on Tasks. Nothing outside the tailnet reaches it.`, "About this")}
    ${a.agents.length ? `<div class="list" style="margin-top:8px">${a.agents.map((x) => `<div><b class="grow">${esc(x.name)}</b><span class="tiny faint">added ${rel(x.created)}</span><button class="btn sm ghost danger" data-a2arevoke="${esc(x.name)}">Revoke</button></div>`).join("")}</div>` : ""}
    <form class="row wrap" id="a2aform" style="gap:6px;margin-top:8px"><input class="input grow" name="name" placeholder="Name of an outside agent, e.g. laptop-claude" pattern="[a-z0-9][a-z0-9-]{1,30}" style="min-width:180px"><button class="btn sm">Add</button></form>
    <div id="a2atok"></div></div>`;
}
function bindA2a() {
  const on = $("[data-a2aon]");
  if (on) on.onchange = () => act({ action: "a2a_settings", on: on.checked }, on.checked ? "A2A is on: agents you add can send tasks, each waits for your OK" : "A2A is off: outside agents cannot reach the stack");
  $$("[data-a2arevoke]").forEach((b) => (b.onclick = () => confirm(`Revoke ${b.dataset.a2arevoke}? Its token stops working at once.`) && act({ action: "a2a_revoke", name: b.dataset.a2arevoke }, "Revoked: its token stops working now")));
  const f = $("#a2aform");
  if (f) f.onsubmit = async (e) => {
    e.preventDefault();
    const r = await api("/api/a2a/token", { method: "POST", body: JSON.stringify({ name: f.name.value.trim().toLowerCase() }) }).catch((x) => ({ error: x.message }));
    if (!r?.ok) return toast(r?.error || "Not added", true);
    f.reset();
    $("#a2atok").innerHTML = `<div class="banner info" style="margin-top:8px;display:block"><b>${esc(r.name)}</b>: its token, shown only now. Give it to that agent with the card's address.
      <pre class="log" style="white-space:pre-wrap;overflow-wrap:anywhere">Authorization: Bearer ${esc(r.token)}\n${esc(r.card)}</pre><button class="btn sm" data-a2acopy>${ic.doc}Copy</button></div>`;
    $("[data-a2acopy]").onclick = () => navigator.clipboard?.writeText(`Authorization: Bearer ${r.token}\n${r.card}`).then(() => toast("Copied"));
  };
}

// ---------- TSK-25: telemetry, one row a day per agent, model, harness and kind (ops/history.py) ----------
// Stat tiles on top, runs and tokens per day (one series each, so no legend: the title names it; hover any bar), and
// the agents' table (the table view of it all). Every number opens its runs. Filters in one row above.
let telData = null, telF = { days: 30, agent: "", model: "", kind: "" }, telOpen = null;
const pct = (a, b) => (b ? Math.round((100 * a) / b) + " %" : "–");
function telRows() {
  const since = dayKey(Date.now() - telF.days * 86400e3);
  return (telData?.rows || []).filter((r) => r.day >= since && (!telF.agent || r.agent === telF.agent) && (!telF.model || r.model === telF.model) && (!telF.kind || r.kind === telF.kind));
}
function telSum(rows) {
  const s = { runs: 0, ok: 0, failed: 0, met: 0, partly: 0, not_met: 0, tin: 0, tout: 0, cost: 0, p95: 0, p50: [] };
  for (const r of rows) { for (const k of ["runs", "ok", "failed", "met", "partly", "not_met", "tin", "tout", "cost"]) s[k] += r[k] || 0; s.p95 = Math.max(s.p95, r.p95_s || 0); s.p50.push(r.p50_s || 0); }
  s.p50 = s.p50.length ? s.p50.sort((a, b) => a - b)[Math.floor(s.p50.length / 2)] : 0;
  return s;
}
function telBars(rows, value, label, fmt) {
  const days = [], since = Date.now() - telF.days * 86400e3;
  for (let t = since; t <= Date.now(); t += 86400e3) days.push(dayKey(t));
  const v = days.map((d) => ({ d, x: rows.filter((r) => r.day === d).reduce((n, r) => n + value(r), 0) }));
  const max = Math.max(...v.map((x) => x.x), 1), W = 600, H = 120, bw = W / v.length;
  return `<div class="card pad"><div class="small"><b>${label}</b> <span class="tiny faint">per day, the last ${telF.days} days · most ${esc(fmt(max))}</span></div>
    <svg class="telbars" viewBox="0 0 ${W} ${H + 16}" preserveAspectRatio="none" role="img" aria-label="${esc(label)} per day">
      <line x1="0" x2="${W}" y1="${H}" y2="${H}" class="telaxis"/>
      ${v.map((x, i) => `<g><title>${esc(`${x.d}: ${fmt(x.x)}`)}</title><rect x="${i * bw}" y="0" width="${bw}" height="${H}" fill="transparent"/>
        ${x.x ? `<rect x="${i * bw + Math.min(2, bw * 0.15)}" y="${H - (x.x / max) * H}" width="${Math.max(1, bw - 2 * Math.min(2, bw * 0.15))}" height="${(x.x / max) * H}" rx="${Math.min(4, bw / 3)}" class="telbar"/>` : ""}</g>`).join("")}
      <text x="0" y="${H + 13}" class="tms">${v[0].d.slice(5)}</text><text x="${W}" y="${H + 13}" class="tms" text-anchor="end">today</text>
    </svg></div>`;
}
async function vTelemetry() {
  if (!telData || route.q.get("reload")) telData = await api("/api/telemetry").catch((e) => ({ rows: [], error: e.message }));
  if (route.name !== "telemetry") return;
  const all = telData.rows || [], rows = telRows(), s = telSum(rows);
  const opts = (k) => [...new Set(all.map((r) => r[k]).filter(Boolean))].sort();
  const sel = (k, l) => `<label class="tiny faint">${l}<select class="input" data-tf="${k}"><option value="">All</option>${opts(k).map((v) => `<option${telF[k] === v ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`;
  const byAgent = {};
  for (const r of rows) (byAgent[r.agent] ??= []).push(r);
  const agents = Object.entries(byAgent).map(([a, rs]) => [a, telSum(rs), rs]).sort((x, y) => y[1].runs - x[1].runs);
  const judged = s.met + s.partly + s.not_met;
  view.innerHTML = `<a class="back" href="#/system">${ic.back}Stack</a>
  <div class="hero heading"><div class="row between" style="gap:10px"><h1>Telemetry</h1><a class="btn sm" href="#/trials">${ic.target}Trials</a></div><p>How each agent did, day by day: runs, how many ended well, the judge's verdicts on their tasks, tokens, time, and what the tokens would cost at list price (the subscriptions cost $0 a call).${telData.prices?.date ? ` Prices of ${esc(telData.prices.date)}, from the gateway's table.` : ""}</p></div>
  ${telData.error ? `<div class="card pad small muted">${esc(telData.error)}</div>` : ""}
  <div class="row wrap telf"><div class="seg">${[7, 30, 90, 365].map((d) => `<button data-td="${d}" class="${telF.days === d ? "on" : ""}">${d === 365 ? "Year" : d + " days"}</button>`).join("")}</div>${sel("agent", "Agent")}${sel("model", "Model")}${sel("kind", "Kind")}</div>
  <div class="tmnums" style="margin-top:12px">${[[nf(s.runs), "runs", ""], [pct(s.ok, s.runs), `ended well (${nf(s.failed)} failed)`, ""], [judged ? pct(s.met + 0.5 * s.partly, judged) : "–", `of ${nf(judged)} judged tasks met`, ""],
    [tok(s.tin + s.tout), "tokens", ""], [ifPaid(s.cost) || "–", "at list price", ""], [s.runs ? dur(s.p50) : "–", `median run · p95 ${s.runs ? dur(s.p95) : "–"}`, ""]]
    .map(([v, l]) => `<div class="card pad tmnum"><b>${esc(v)}</b><span class="tiny faint">${esc(l)}</span></div>`).join("")}</div>
  <div class="stack section">${telBars(rows, (r) => r.runs, "Runs", nf)}${telBars(rows, (r) => (r.tin || 0) + (r.tout || 0), "Tokens", tok)}</div>
  <div class="section-h section"><h2>Agents · ${agents.length}</h2><span class="tiny faint">busiest first; tap one for its days and runs</span></div>
  <div class="card list telag">${agents.map(([a, x, rs]) => `<details data-ta="${esc(a)}"${telOpen === a ? " open" : ""}><summary><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(agentName(a) || a)}${x.runs >= 3 && x.ok / x.runs < 0.7 ? ` <span class="pill failed" style="padding:1px 7px">fails often</span>` : ""}</div>
      <div class="sub wrap">${nf(x.runs)} runs · ${pct(x.ok, x.runs)} well${x.met + x.partly + x.not_met ? ` · judged ${x.met} met, ${x.partly} partly, ${x.not_met} not` : ""} · ${tok(x.tin + x.tout)} tokens${x.cost ? ` · ${ifPaid(x.cost)}` : ""} · median ${dur(x.p50)}, p95 ${dur(x.p95)}</div></div></summary>
      <div class="telruns" data-truns="${esc(a)}"><div class="tiny faint">${[...new Set(rs.map((r) => `${r.model || "no model"} · ${r.harness} · ${r.kind}`))].map(esc).join(" · ")}</div><div class="skeleton" style="height:60px;margin-top:8px"></div></div></details>`).join("")
    || `<div class="pad small muted">No runs in these days${telF.agent || telF.model || telF.kind ? " with these filters" : ""}.</div>`}</div>
  <div class="tiny faint section">A row is one day of one agent on one model, harness and kind of work (ops/history.py), kept for a year; a verdict counts on the day its task was judged. ${how("telemetry")}</div>`;
  $$("[data-td]").forEach((b) => (b.onclick = () => { telF.days = +b.dataset.td; vTelemetry(); }));
  $$("[data-tf]").forEach((x) => (x.onchange = () => { telF[x.dataset.tf] = x.value; vTelemetry(); }));
  $$("[data-ta]").forEach((d) => (d.ontoggle = async () => {
    if (!d.open) { if (telOpen === d.dataset.ta) telOpen = null; return; }
    telOpen = d.dataset.ta;
    const box = $("[data-truns]", d), since = Date.now() / 1000 - telF.days * 86400;
    const list = await api(`/api/rt/runs?agent=${encodeURIComponent(d.dataset.ta)}&since=${since}&limit=200`).catch(() => []);
    box.lastElementChild.outerHTML = `<div class="stack" style="margin-top:8px">${(list.length ? list : []).map((r) => `<a class="witem" href="#/live/${encodeURIComponent(r.run)}">${esc(r.name || r.title || r.run)} <span class="tiny faint">· ${esc(r.end_state || "live")} · ${r.ended ? rel(new Date(r.ended * 1000).toISOString()) : "now"}</span></a>`).join("")
      || `<div class="small muted">Its runs of these days are no longer in the run record (it keeps them 90 days).</div>`}${list.length === 200 ? `<div class="tiny faint">the newest 200</div>` : ""}</div>`;
  }));
  if (telOpen) $(`[data-ta="${CSS.escape(telOpen)}"]`)?.dispatchEvent(new Event("toggle"));
}

// TSK-30: the agents the owner may pick for a task: those that can do a step (their harness has an adapter)
const tAgents = () => S?.task_agents || [];

// TSK-05 to TSK-08: a Conductor task's steps, each with its agent, harness, state and what it waits for
const SSTATE = { pending: "waits", running: "running", waiting: "waits for its agent", done: "done", failed: "failed", cancelled: "cancelled", skipped: "dropped by the Orchestrator" };
function taskStepsHtml(t) {
  return `<div class="tlabel">Steps</div><ol class="tplan">${t.steps.map((s) => `<li><b>${esc(s.title)}</b> <span class="agent">${esc(s.agent)}</span>${(s.why || "").includes("(your choice") ? ` <span class="pill ok" style="padding:0 6px">your choice</span>` : ""} <span class="tiny faint">${esc(s.harness)}</span>
    <div class="sub ${s.status === "failed" ? "err-t" : s.status === "done" ? "" : "warn-t"}">${esc(SSTATE[s.status] || s.status)}${s.after?.length ? ` · after step ${s.after.join(", ")}` : ""}${s.waiting_for ? ` · ${esc(s.waiting_for)}` : ""}${s.attempts > 1 ? ` · attempt ${s.attempts}` : ""}</div>
    ${s.error && s.status !== "done" ? `<div class="faint">${esc(s.error)}</div>` : ""}${s.output ? `<details class="tiny"><summary>Its result</summary><div class="md">${md(s.output)}</div></details>` : ""}</li>`).join("")}</ol>`;
}

function taskCard(t) {
  const [href, label] = t.door && t.ref && TDOOR[t.door] ? TDOOR[t.door](t.ref) : [null, ""];
  const bad = ["failed", "cancelled"].includes(t.status), wait = ["needs_answer", "waiting_approval", "waiting_owner"].includes(t.status);
  return `<details class="card tcard" id="task-${t.id}" data-keep="task-${t.id}"${taskOpen === t.id || t.status === "needs_answer" ? " open" : ""}>
    <summary><div class="row" style="gap:10px;align-items:flex-start"><div class="ic ${bad ? "err" : wait ? "warn" : t.status === "done" ? "ok" : ""}">${ic.target}</div>
      <div class="grow" style="min-width:0"><div class="ttl">${esc(t.title)}</div><div class="sub">#${t.id} · ${esc(tstat(t))}${t.kind ? ` · ${esc(TKINDS[t.kind] || t.kind)}` : ""} · ${esc(rhythmText(t.rhythm, t.after))} · ${rel(t.created)}</div></div></div></summary>
    <div class="tbody small">
      ${t.goal && t.goal !== t.title ? `<p>${esc(t.goal)}</p>` : ""}
      ${t.text !== t.goal ? `<p class="faint">You wrote: “${esc(t.text)}”</p>` : ""}
      ${t.error ? `<div class="banner" style="padding:8px 12px">${ic.alert}<span>${esc(t.error)}</span></div>` : ""}
      ${lastRunHtml(t)}
      ${t.judgement?.points?.length ? `<div class="tlabel">Done when · ${t.judgement.run && (t.runs || []).length > 1 ? `run ${t.judgement.run} ` : ""}judged: ${esc(t.verdict)}</div><ul class="tjudge">${t.judgement.points.map((p) => `<li class="${p.met ? "" : "err-t"}">${p.met ? "✓" : "✗"} ${esc(p.point)}<div class="faint">${esc(p.why)}</div></li>`).join("")}</ul>`
        : t.done?.length ? `<div class="tlabel">Done when${t.verdict ? ` · ${esc(t.verdict)}` : ""}</div><ul>${t.done.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : ""}
      ${t.tokens ? `<div class="tiny faint">${t.judgement?.run && (t.runs || []).length > 1 ? `run ${t.judgement.run} ` : ""}used ${tok(t.tokens)} of the subscriptions${t.cost != null ? ` (${ifPaid(t.cost)})` : ""}</div>` : ""}
      ${runsHtml(t)}
      ${t.steps?.length ? taskStepsHtml(t) : t.plan?.length ? `<div class="tlabel">Plan</div><ol class="tplan">${t.plan.map((p) => `<li><b>${esc(p.step)}</b> <span class="agent">${esc(p.agent)}</span><div class="faint">${esc(p.why)}</div></li>`).join("")}</ol>` : ""}
      ${t.result ? `<a class="btn sm primary" href="#/read?path=${encodeURIComponent(t.result)}">${ic.doc}Read the answer</a>` : ""}
      ${t.status === "needs_answer" ? `<form class="tans" data-tans="${t.id}">${t.questions.map((q, i) => `<label><span>${esc(q)}</span><input class="input" name="a${i}" required></label>`).join("")}<div class="row" style="justify-content:flex-end"><button class="btn sm primary">${ic.check}Answer</button></div></form>` : ""}
      <div class="row tacts">${t.door === "plan" && (t.runs || []).length ? `<a class="btn sm" href="#/taskmap?t=${t.id}">${ic.wiki}Swarm map</a>` : ""}${t.door === "plan" ? `<a class="btn sm ghost" href="#/live/${encodeURIComponent(`task:${t.id}`)}">${ic.pulse}Live trace</a>` : ""}${href ? `<a class="btn sm ghost" href="${href}">${ic.next}${esc(label)}</a>` : ""}${t.shop ? `<a class="btn sm ghost" href="#/mission/${encodeURIComponent(t.shop)}">${ic.next}Its shopping agent</a>` : ""}${t.door !== "chat" && t.source !== "door" ? `<a class="btn sm ghost" href="#/live/${encodeURIComponent(`task-intake:${t.id}-${(t.answers || []).length}`)}">${ic.pulse}How it was planned</a>` : ""}
        ${t.status === "waiting_approval" ? `<button class="btn sm primary" data-tok="${t.id}">${ic.check}Start it</button>` : ""}
        ${t.status === "failed" && !t.ref ? `<button class="btn sm ghost" data-tretry="${t.id}">${ic.repeat}Plan it again</button>` : ""}
        ${!["done", "failed", "cancelled"].includes(t.status) && !t.ref ? `<button class="btn sm ghost danger" data-tcancel="${t.id}">${ic.x}Cancel</button>` : ""}</div>
    </div></details>`;
}

function taskBoardHtml() {
  const ts = S.tasks || [];
  return TGROUPS.map(([name, sts]) => { const g = ts.filter((t) => sts.includes(t.status)); return name === "Done"
    ? `<details class="section" data-keep="tdone"><summary class="section-h"><h2>Done · ${g.length}</h2></summary><div class="stack">${g.map(taskCard).join("") || `<div class="muted small">Nothing in the last 7 days</div>`}</div></details>`
    : `<div class="section"><div class="section-h"><h2>${name} · ${g.length}</h2></div><div class="stack">${g.map(taskCard).join("") || `<div class="muted small">${name === "Waiting on you" ? "Nothing waits for you" : "None"}</div>`}</div></div>`; }).join("");
}

function vTasks() {
  if (+route.q.get("t")) return location.replace(`#/task/${+route.q.get("t")}`);   // APP-35: a task has its own page
  taskOpen = null;
  const details = route.q.get("new") === "1";
  view.innerHTML = `<div class="hero"><div><h1>Tasks</h1><p>Say what the stack should do. It writes what done means, plans it, picks the agents and starts it; you see the plan here and answer only real questions.</p></div></div>
  <form class="card pad tform" id="taskform"><textarea class="input" name="text" rows="2" placeholder="What should the stack do? One sentence is enough." required></textarea>
    <details id="tdet"${details ? " open" : ""}><summary class="small">Details: leave any as it is, and the stack decides it</summary><div class="tgrid">
      <label>Kind<select class="input" name="kind"><option value="">The stack decides</option>${Object.entries(TKINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
      <label>When<select class="input" name="rtype"><option value="">The stack decides</option><option value="once">Once, now</option><option value="schedule">On a schedule</option><option value="after">After another task</option></select></label>
      <label>Schedule<input class="input" name="schedule" placeholder="daily 07:00 · weekly mon 08:00 · every 6h"></label>
      <label>After task #<input class="input" name="after" type="number" min="1"></label>
      <label>Deadline<input class="input" name="deadline" type="date"></label>
      <label>Effort<select class="input" name="effort"><option value="">The stack decides</option><option value="light">Light: a quick look</option><option value="standard">Standard</option><option value="deep">Deep: thorough</option></select></label>
      <label>Before it starts<select class="input" name="autonomy"><option value="auto">Start right away</option><option value="ask">Show me the plan first</option></select></label>
      <label>Model for one-call steps<select class="input" name="model"><option value="">The stack decides</option>${Object.entries(S?.prices || {}).map(([k, p]) => `<option value="${esc(k)}">${esc(k)} (${esc(p.model)})</option>`).join("")}</select></label>
      <div class="wide"><div class="small">Agents <span class="tiny faint">none ticked: the stack picks them; ticked: only these do the steps</span></div>
        <div class="chips tagents">${tAgents().map((a) => `<label class="tag" title="${esc(a.purpose || "")}"><input type="checkbox" name="agents" value="${esc(a.id)}"> ${esc(a.id)}</label>`).join("")}</div></div>
      <label class="wide">Done when (one point per line; empty: the stack writes it)<textarea class="input" name="done" rows="2"></textarea></label></div></details>
    <div class="row" style="justify-content:flex-end;margin-top:10px"><button class="btn primary">${ic.rocket}Do it</button></div></form>
  <div id="taskboard">${taskBoardHtml()}</div>
  <div class="section-h section" id="triggers"><h2>Triggers</h2><span class="tiny faint">events that start tasks by themselves</span></div>
  <div id="trigboard">${trigBoardHtml()}</div>
  ${ruleFormHtml()}
  <div class="section-h section"><h2>Agents, measured</h2><span class="tiny faint">how each agent did, per kind of task, last 30 days</span></div>
  <div id="staffboard">${staffHtml()}</div>`;
  bindTasks();
  bindTriggers();
  if (taskOpen) setTimeout(() => $(`#task-${taskOpen}`)?.scrollIntoView({ block: "center" }), 30);
}

function bindTasks() {
  const f = $("#taskform");
  if (f && !f.dataset.bound) {
    f.dataset.bound = 1;
    f.onsubmit = async (e) => {
      e.preventDefault();
      const d = $("#tdet").open, req = { action: "task_create", text: f.text.value.trim(), autonomy: f.autonomy.value };
      if (d) {                                            // deliberate mode: only what the owner set is decided already
        if (f.kind.value) req.kind = f.kind.value;
        if (f.effort.value) req.effort = f.effort.value;
        if (f.deadline.value) req.deadline = f.deadline.value;
        if (f.rtype.value === "schedule") req.rhythm = { type: "schedule", schedule: f.schedule.value.trim() };
        else if (f.rtype.value === "after") req.rhythm = { type: "after", task: f.after.value };
        else if (f.rtype.value === "once") req.rhythm = { type: "once" };
        req.done = f.done.value.split("\n").map((x) => x.trim()).filter(Boolean);
        const picked = [...f.querySelectorAll("[name=agents]:checked")].map((x) => x.value);   // TSK-30
        if (picked.length) req.agents = picked;
        if (f.model.value) req.model = f.model.value;
      }
      const r = await act(req, "The stack is planning it");
      if (r?.task) { f.reset(); location.hash = `#/task/${r.task}`; }
    };
  }
  $$("[data-tans]").forEach((fm) => (fm.onsubmit = async (e) => { e.preventDefault(); await act({ action: "task_answer", id: +fm.dataset.tans, answers: [...fm.querySelectorAll("input")].map((x) => x.value) }, "Answered: it plans again"); }));
  $$("[data-tok]").forEach((b) => (b.onclick = () => act({ action: "task_approve", id: +b.dataset.tok }, "Started: its steps show here as they run")));
  $$("[data-tretry]").forEach((b) => (b.onclick = () => act({ action: "task_retry", id: +b.dataset.tretry }, "Planning it again: the new plan shows here")));
  $$("[data-trun]").forEach((b) => (b.onclick = () => act({ action: "task_run", id: +b.dataset.trun }, "Running it again now: its steps show here as they go")));
  $$("[data-tconduct]").forEach((b) => (b.onclick = () => confirm("Run it under the Conductor from now on? Its mission keeps its topic, wiki and history, and the next run comes on the same schedule.")
    && act({ action: "task_conduct", id: +b.dataset.tconduct }, "It runs under the Conductor now: its next run shows here")));
  $$("[data-tcancel]").forEach((b) => (b.onclick = () => act({ action: "task_cancel", id: +b.dataset.tcancel }, "Cancelled: nothing more of it runs")));
}

// ---------- Triggers (TSK-10 to TSK-12): the event bus's sources, the owner's rules, breaking stories ----------
const PARAM = { news: ["Search for", "uranium supply"], breaking: ["Subject to watch", "Cameco"], feed: ["Feed address", "https://example.com/feed.xml"],
  github: ["Repository (owner/name)", "regenzeus/AI_Swarm_Stack"], price: ["Symbol:percent", "CCJ:8"], filing: ["US ticker", "CCJ"],
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
    <details class="card pad small" data-keep="tevents" style="margin-top:10px"><summary>Newest events · ${b.events.length}</summary><div class="list">${b.events.map((e) => `<div><span class="agent">${esc(e.source)}</span><div class="grow"><div class="ttl">${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a>` : esc(e.title)}</div></div><div class="tiny faint" style="white-space:nowrap">${rel(e.ts)}</div></div>`).join("") || `<div class="muted small">Nothing yet</div>`}</div></details>`;
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
    <label>Name<input class="input" name="name" placeholder="Cameco breaking news" required></label>
    <label>When<select class="input" name="source">${src.map(([k, s]) => `<option value="${k}">${esc(s.what)}</option>`).join("")}</select></label>
    <label id="rparam"><span>${PARAM[src[0]?.[0]]?.[0] || "Parameter"}</span><input class="input" name="param" placeholder="${esc(PARAM[src[0]?.[0]]?.[1] || "")}"></label>
    <label>Only with these words (optional)<input class="input" name="words" placeholder="contract, uranium"></label>
    <label class="wide">Then the stack should<input class="input" name="task" placeholder="Read {title} and tell me in three lines what it means for my uranium positions" required></label>
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

// a live update of the board that keeps what you opened and never replaces a field you are typing in
let taskSig = "";
function tasksUpdate() {
  const b = $("#taskboard");
  if (!b || (typing() && b.contains(document.activeElement))) return;
  const sig = JSON.stringify([S.tasks || [], S.bus || {}, S.staffing || {}]);
  if (sig === taskSig) return;
  taskSig = sig;
  const open = [...view.querySelectorAll("details[open][data-keep]")].map((d) => d.dataset.keep);
  b.innerHTML = taskBoardHtml();
  const tb = $("#trigboard");
  if (tb) tb.innerHTML = trigBoardHtml();
  const sb = $("#staffboard");
  if (sb) sb.innerHTML = staffHtml();
  for (const k of open) { const d = view.querySelector(`details[data-keep="${CSS.escape(k)}"]`); if (d) d.open = true; }
  bindTasks();
  bindTriggers();
}

// ---------- Home (redesigned 28 Oct 2026) ----------
// Three questions, in this order: does anything need me (decisions only, each one tap away), what is happening right now,
// and what did my agents produce (a live feed of results, newest first). Live updates replace only the parts that changed
// (homeUpdate), so nothing twitches. Starting things is the ask bar at the top: Hermes can start agents itself.
let homeFilter = "mine", homeShow = 12;                 // the feed opens on 12 (U2: 40 made Home 13 phone screens); "Show older" adds 40
// a long text's first line, marked when more follows (the rest is on its page)
const firstLine = (s) => { const l = String(s || "").split("\n"); return l[0] + (l.slice(1).join("").trim() ? " …" : ""); };
// who asked Claude: a crew agent's task is named after it (its question is a long standing prompt, shown when opened)
const ctAsker = (t) => { const c = /^crew:(.+)/.exec(t.source || ""); return c ? (S?.crew || []).find((x) => x.id === c[1])?.name || c[1] : t.source === "chat" ? "your chat" : "Hermes"; };
const ctTitle = (t) => /^crew:/.test(t.source || "") ? `Asked by the ${ctAsker(t)}` : firstLine(t.question);
const homeEx = new Map();                                // result file -> its first lines (fetched once per file)
const homeLast = {};
const toIso = (x) => (x == null ? "" : typeof x === "number" ? new Date(x > 1e12 ? x : x * 1000).toISOString() : String(x));
const gbOf = gb;

function needsItems() {
  const out = [], c = S.connections, sy = S.system || {};
  for (const b of (S.builds || []).filter((x) => x.status === "review")) out.push({ build: b });
  for (const p of (typeof shopProposals === "function" ? shopProposals() : []).filter((p) => ["proposed", "needs_owner"].includes(p.status)))
    out.push({ href: `#/mission/${encodeURIComponent(p.slug)}?shop=${p.id}`, icon: ic.coin, title: p.status === "proposed" ? "A purchase to approve" : "A purchase needs you", sub: `${p.item} · ${eur(p.total_eur)}` });
  const steps = ((S.crew || []).find((x) => x.id === "phone-cleanup")?.actions || []).filter((x) => x.status === "open");
  if (steps.length) out.push({ href: "#/crew/phone-cleanup", icon: ic.trash, title: `${steps.length} AI phone cleanup step${steps.length > 1 ? "s" : ""} to approve`, sub: `${gbOf(steps.reduce((a, x) => a + (x.size || 0), 0))} in all · one Approve each` });
  if (S.phone?.pending) out.push({ href: "#/phone", icon: ic.alert, cls: "err", title: `The AI phone asks for ${S.phone.pending} approval${S.phone.pending > 1 ? "s" : ""}`, sub: "it waits for your tap" });
  if (c?.pending) out.push({ href: "#/system?conn=1", icon: ic.alert, title: "Gmail: a Trash batch waits for your OK", sub: "nothing is moved without it" });
  for (const m of (S.missions || []).filter((m) => m.status === "active" && (m.needs || []).some((n) => { const [cn, sc] = n.split(":"); return !c?.[cn]?.grants?.[sc]; })))
    out.push({ href: `#/mission/${encodeURIComponent(m.slug)}`, icon: ic.lock || ic.alert, title: `${m.title} needs access`, sub: `grant ${m.needs.join(", ")} on its page` });
  const pend = sy.pending_memory?.length || 0;
  if (pend) out.push({ href: "#/system", icon: ic.brain, title: `${pend} memor${pend > 1 ? "ies wait" : "y waits"} for your OK`, sub: "Hermes wants to remember it" });
  const hs = S.house?.reachable ? houseSteps(S.house).find((x) => !x.done && !x.optional) : null;
  if (hs) out.push({ href: "#/house", icon: ic.house, title: "Finish setting up the House", sub: `next: ${hs.title.toLowerCase()}` });
  for (const t of (S.tasks || []).filter((x) => ["needs_answer", "waiting_approval"].includes(x.status)))   // TSK-04
    out.push({ href: `#/task/${t.id}`, icon: ic.target, title: t.status === "needs_answer" ? `Task #${t.id} asks you` : `Task #${t.id} waits for your OK`, sub: t.title });
  for (const m of S.swarm?.owner_requests || [])        // SWM-98: what an agent asks of you waits here until you answer
    out.push({ href: `#/swarm?tab=chat&ctx=${encodeURIComponent(m.context || "")}`, icon: ic.chat || ic.alert, title: `${m.sender} asks you`, sub: m.text });
  return out;
}

function needsHtml() {
  const it = needsItems();
  if (!it.length) return `<div id="homeneeds" class="needs-calm">${ic.check}<span>Nothing needs you right now.</span></div>`;
  return `<div id="homeneeds"><div class="section-h"><h2>Needs you <span class="hcount">${it.length}</span></h2></div>
    <div class="card list hneeds">${it.map((x) => x.build ? workBuildRow(x.build) : `<a href="${x.href}"><div class="ic ${x.cls || "warn"}">${x.icon}</div><div class="grow" style="min-width:0"><div class="ttl">${esc(x.title)}</div><div class="sub wrap">${esc(x.sub || "")}</div></div>${ic.next}</a>`).join("")}</div></div>`;
}

// the stack's own upkeep (health alerts the doctor looks at, its improvement ideas): visible, but not "Needs you"
function upkeepHtml() {
  const props = ideasWaiting(), alerts = S.health?.alerts || 0;
  if (!props && !alerts) return "";
  const failed = (S.crew || []).filter((x) => x.state === "failed").map((x) => x.name);
  return `<div class="hsub">Stack upkeep</div><div class="card list">
    ${alerts ? `<a href="#/missions"><div class="ic">${ic.pulse}</div><div class="grow" style="min-width:0"><div class="ttl">${alerts} health alert${alerts > 1 ? "s" : ""}</div><div class="sub wrap">${esc(failed.join(", ") || "the Health doctor looks at them")}</div></div>${ic.next}</a>` : ""}
    ${props ? `<a href="#/swarm?tab=improve"><div class="ic">${ic.rocket}</div><div class="grow" style="min-width:0"><div class="ttl">${props} improvement idea${props > 1 ? "s" : ""}</div><div class="sub wrap">the stack's own fixes and changes to its agents, in Agents → Ideas</div></div>${ic.next}</a>` : ""}</div>`;
}

function nowHtml() {
  const builds = (S.builds || []).filter((b) => ["working", "queued", "checking", "deploying", "approved", "recheck"].includes(b.status));
  const queued = (S.queue || []).filter((q) => q.status === "queued").map((q) => (S.missions || []).find((m) => m.slug === q.slug)).filter(Boolean);
  const tasks = (S.claude_tasks || []).filter((t) => ["running", "queued"].includes(t.status));
  const next = (S.missions || []).filter((m) => m.status === "active" && m.next_run).sort((a, b) => a.next_run.localeCompare(b.next_run)).slice(0, 3);
  const busy = S.running || builds.length || tasks.length;
  const rows = [...builds.map(workBuildRow),
    ...queued.map((m) => `<a href="#/mission/${encodeURIComponent(m.slug)}"><div class="ic">${typeIcon(m.type)}</div><div class="grow"><div class="ttl wrap">${esc(m.title)}</div><div class="sub">waits for the run slot</div></div><span class="pill queued">Queued</span></a>`),
    ...tasks.map((t) => `<a href="#/build"><div class="ic ${t.status === "running" ? "run" : ""}">${ic.code}</div><div class="grow"><div class="ttl wrap">Claude task #${t.id}</div><div class="sub wrap">${esc(ctTitle(t))}</div></div><span class="pill ${t.status === "running" ? "running" : "queued"}">${t.status === "running" ? "Running" : "Queued"}</span></a>`)];
  return `<div id="homenow"><div class="section-h"><h2>Now</h2>${busy ? `<span class="pill running"><span class="dot run"></span>working</span>` : `<span class="tiny faint">all quiet</span>`}</div>
    ${S.running ? runningCard() : ""}
    ${rows.length ? `<div class="card list" ${S.running ? 'style="margin-top:10px"' : ""}>${rows.join("")}</div>` : S.running ? "" : `<div class="card pad small muted">No agent is working right now.</div>`}
    ${upkeepHtml()}
    ${next.length ? `<div class="hsub">Up next</div><div class="card list">${next.map((m) => `<a href="#/mission/${encodeURIComponent(m.slug)}"><div class="ic">${typeIcon(m.type)}</div><div class="grow"><div class="ttl wrap">${esc(m.title)}</div><div class="sub">${dt(m.next_run)}</div></div><div class="tiny faint">${rel(m.next_run)}</div></a>`).join("")}</div>` : ""}</div>`;
}

// every result, decision and finished job of the agents, newest first
function feedItems() {
  const out = [];
  for (const m of S.missions || []) for (const r of m.runs || []) {
    const ts = r.ended || r.started;
    if (r.status === "ok" && r.summary) out.push({ ts, cat: m.type === "shopping" ? "shopping" : "results", agent: m.title, icon: typeIcon(m.type), head: r.summary, path: r.output, big: true,
      href: r.output ? `#/read?path=${encodeURIComponent(r.output)}&m=${encodeURIComponent(m.slug)}` : `#/mission/${encodeURIComponent(m.slug)}`,
      meta: [r.trigger === "event" ? "after an event" : r.trigger === "schedule" ? "scheduled" : "on request", dur(r.seconds), r.calls ? `${r.calls} model calls` : ""] });
    else if (r.status === "failed") out.push({ ts, cat: m.type === "shopping" ? "shopping" : "results", agent: m.title, icon: ic.x, tone: "err", head: `Run failed${r.summary ? `: ${r.summary}` : ""}`, href: `#/mission/${encodeURIComponent(m.slug)}?tab=history` });
  }
  for (const p of typeof shopProposals === "function" ? shopProposals() : [])
    if (["proposed", "needs_owner", "approved", "buying", "bought", "shipped", "delivered", "failed"].includes(p.status))
      out.push({ ts: p.updated || p.created, cat: "shopping", agent: p.mission || "Shopping", icon: ic.coin, tone: p.status === "failed" ? "err" : "",
        head: `${p.item}: ${eur(p.total_eur)} · ${(SHOP_STATE[p.status] || [, p.status])[1]}`, href: `#/mission/${encodeURIComponent(p.slug)}?shop=${p.id}` });
  for (const c of S.crew || []) {
    if (!c.last || !c.result) continue;
    if (/^every \d+\s*(min|h)/.test(c.schedule || "") && c.state !== "failed") continue;    // every few minutes: not news
    out.push({ ts: toIso(c.last), cat: "housekeeping", agent: c.name, icon: ic[CREW_IC[c.area]] || ic.layers, tone: c.state === "failed" ? "err" : "",
      head: String(c.result).replace(/^failed: (\w+Error: )?/, c.state === "failed" ? "Failed: " : ""), href: `#/crew/${encodeURIComponent(c.id)}` });
  }
  for (const b of S.builds || []) {
    const done = ["deployed", "merged"].includes(b.status), bad = ["failed", "rolled_back", "stopped"].includes(b.status);
    if (done || bad || b.status === "review")
      out.push({ ts: toIso(b.updated), cat: "code", agent: `Build #${b.id}`, icon: ic.rocket, tone: bad ? "err" : "",
        head: `${done ? "Deployed" : bad ? (b.status === "rolled_back" ? "Rolled back" : "Failed") : "Ready for your review"}: ${b.title}`, href: `#/build/${b.id}` });
  }
  for (const t of S.claude_tasks || [])
    if (t.status === "done" && !/^You are the Health doctor/.test(t.question || ""))
      out.push({ ts: toIso(t.ended || t.updated || t.created), cat: "code", agent: `Claude task #${t.id}`, icon: ic.code, head: `Answered: ${firstLine(t.question)}`, href: "#/build" });
  const KEEP = { triggered: ic.bolt, email: ic.mail || ic.doc, created: ic.plus, system: ic.pulse, wiki: ic.wiki, understand: ic.code, archive: ic.archive,
    swarm: ic.radar, deploy: ic.rocket };                             // swarm: the Ledger's changes; deploy: a session's deploy
  for (const e of S.activity || [])
    if (KEEP[e.kind] || (e.kind === "health" && e.push))
      out.push({ ts: e.ts, cat: ["understand", "system", "deploy"].includes(e.kind) ? "code" : e.kind === "swarm" ? "housekeeping" : e.kind === "health" ? "housekeeping" : "results", agent: e.title || "System",
        icon: KEEP[e.kind] || ic.alert, tone: e.kind === "health" || /^DEPLOY FAILED/.test(e.text || "") ? "err" : "", head: e.text,
        href: e.slug ? `#/mission/${encodeURIComponent(e.slug)}` : e.kind === "health" ? "#/missions" : e.kind === "swarm" ? "#/swarm?tab=improve" : "#/system" });
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
  // "For you": your results and shopping, and whatever failed; the stack's deploys and bookkeeping only under their own chips
  // (UX review 2026-10-30: a day of deploys filled the feed)
  const forYou = (x) => ["results", "shopping"].includes(x.cat) || x.tone === "err";
  const cats = [["mine", "For you"], ["results", "Results"], ["shopping", "Shopping"], ["housekeeping", "Housekeeping"], ["code", "Code"], ["all", "Everything"]]
    .filter(([k]) => k === "all" || k === "mine" || all.some((x) => x.cat === k));
  if (!cats.some(([k]) => k === homeFilter)) homeFilter = "mine";
  const mine = all.filter((x) => homeFilter === "all" || (homeFilter === "mine" ? forYou(x) : x.cat === homeFilter)), items = mine.slice(0, homeShow);   /* cap: list: "Show older" shows the rest */
  let day = "";
  const rows = items.map((x) => {
    const d = dayOf(toIso(x.ts)), head = d !== day ? `<div class="fday">${esc((day = d))}</div>` : "";
    const ex = x.path ? homeEx.get(x.path) : "";
    return `${head}<a class="fitem ${x.big ? "big" : ""} ${x.tone || ""}" href="${x.href}"><div class="fi-ic">${x.icon}</div>
      <div class="grow" style="min-width:0"><div class="fi-top"><b class="wrap">${esc(x.agent)}</b><span class="tiny faint">${clockOf(toIso(x.ts))}</span></div>
        <div class="fi-h">${esc(x.head)}</div>${x.path ? `<div class="fi-x small muted" data-ex="${esc(x.path)}">${ex ? esc(ex) : ""}</div>` : ""}
        ${(x.meta || []).filter((v) => v && v !== "–").length ? `<div class="tiny faint" style="margin-top:4px">${x.meta.filter((v) => v && v !== "–").map(esc).join(" · ")}</div>` : ""}</div></a>`;
  }).join("");
  return `<div id="homefeed"><div class="section-h"><h2>Latest from your agents</h2><span class="tiny faint"><span class="dot ok" style="display:inline-block;margin-right:5px"></span>live</span></div>
    <div class="chips scroll-x" style="margin-bottom:6px">${cats.map(([k, l]) => `<button type="button" class="tag hf ${homeFilter === k ? "on" : ""}" data-hf="${k}">${l}</button>`).join("")}</div>
    ${rows || `<div class="card empty small">Nothing here yet. A result shows up the moment an agent finishes.</div>`}
    ${mine.length > items.length ? `<button type="button" class="btn sm ghost" id="hfmore" style="margin-top:8px">Show older (${mine.length - items.length} more)</button>` : ""}</div>`;
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
  const n = needsItems().length, next = (S.missions || []).filter((m) => m.status === "active" && m.next_run).sort((a, b) => a.next_run.localeCompare(b.next_run))[0];
  const busy = (S.running ? 1 : 0) + (S.builds || []).filter((b) => ["working", "checking", "deploying"].includes(b.status)).length + (S.claude_tasks || []).filter((t) => t.status === "running").length;
  return `<p id="homehead">${day(new Date(), true)} · ${n ? `<b class="warn-t">${n} thing${n > 1 ? "s need" : " needs"} you</b>` : "nothing needs you"} · ${busy ? `${busy} working now` : "all quiet"}${next ? ` · next: ${esc(next.title)} ${rel(next.next_run)}` : ""}</p>`;
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

function vHome() {
  view.innerHTML = `<div class="home">
  <div class="home-head">
    <div class="hero" style="margin-bottom:6px"><div><h1>${greet()}${S.viewer_name ? ", " + esc(String(S.viewer_name).split(" ")[0]) : ""}</h1>${homeHeadHtml()}</div></div>
    ${!Object.keys(gp.read).length && !Object.keys(gp.tried).length && !gp.hideTour ? `<div class="banner info tour" style="margin-bottom:10px">${ic.doc}<a class="grow" href="#/guide/first-ten-minutes"><b>New here?</b> Take the ten-minute tour of everything your stack can do.</a><button class="icon-btn" id="hidetour" title="Hide">${ic.x}</button></div>` : ""}
    <form class="askbar" id="askbar"><input class="input" name="q" autocomplete="off" placeholder="Ask or give a task"><button class="btn ask" type="submit" data-to="chat" title="Ask Hermes in a chat">${ic.chat}<span>Ask</span></button><button class="btn primary" type="submit" data-to="task" title="The stack plans it and does it">${ic.rocket}<span>Do it</span></button></form>
    <div class="chips hquick"><a class="tag" href="#/tasks">${ic.target}Tasks${openTasks() ? ` · ${openTasks()}` : ""}</a><a class="tag" href="#/tasks?new=1">${ic.tune}Task with details</a><a class="tag" href="#/new">${ic.plus}New mission</a><a class="tag" href="#/wiki?new=1">${ic.wiki}New wiki</a><a class="tag" href="#/chat">${ic.chat}Chats</a><a class="tag" href="#/missions">${ic.target}All agents</a></div>
  </div>
  <div class="home-side">
    ${needsHtml()}
    ${nowHtml()}
    ${devicesHtml()}
    ${homeStatsHtml()}
  </div>
  <div class="home-feed">${feedHtml()}</div>
  </div>`;
  for (const id of ["homehead", "homeneeds", "homenow", "homedev", "homestats", "homefeed"]) homeLast[id] = document.getElementById(id)?.outerHTML;
  bindHome();
}

function bindHome() {
  const ht = $("#hidetour"); if (ht) ht.onclick = () => { gp.hideTour = 1; gsave(); ht.closest(".banner").remove(); };
  const f = $("#askbar");
  if (f) f.onsubmit = async (e) => {                      // TSK-02: Ask goes to a chat, Do it makes a task the stack plans and does
    e.preventDefault();
    const v = f.q.value.trim();
    if (!v) return;
    if (e.submitter?.dataset.to !== "task") { location.hash = `#/chat?prompt=${encodeURIComponent(v)}&send=1`; return; }
    const r = await act({ action: "task_create", text: v }, "The stack is planning it");
    if (r?.task) { f.q.value = ""; location.hash = `#/task/${r.task}`; }
  };
  $$("[data-hf]").forEach((b) => (b.onclick = () => { homeFilter = b.dataset.hf; homeShow = 12; const el = $("#homefeed"); el.outerHTML = feedHtml(); homeLast.homefeed = $("#homefeed").outerHTML; bindHome(); }));
  if ($("#hfmore")) $("#hfmore").onclick = () => { homeShow += 40; const el = $("#homefeed"); el.outerHTML = feedHtml(); homeLast.homefeed = $("#homefeed").outerHTML; bindHome(); };
  loadExcerpts();
}

// a live update on Home: only the parts whose content changed are replaced (no full redraw, no twitch)
function homeUpdate() {
  const parts = [["homehead", homeHeadHtml], ["homeneeds", needsHtml], ["homenow", nowHtml], ["homedev", devicesHtml], ["homestats", homeStatsHtml], ["homefeed", feedHtml]];
  for (const [id, fn] of parts) {
    const el = document.getElementById(id), html = fn();
    if (!el || homeLast[id] === html) continue;
    el.outerHTML = html;
    homeLast[id] = html;
  }
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
  const fresh = open.filter((s) => s.status === "open"), freshSize = fresh.reduce((a, s) => a + (s.size || 0), 0);
  const row = (s) => `<li><div class="row between wrap" style="gap:8px;align-items:flex-start"><div style="flex:1 1 240px;min-width:0"><div class="small"><b>${esc(s.title)}</b> · ${gbs(s.size)}</div>
      <div class="tiny muted">${esc(s.why || "")}</div>${s.result ? `<div class="tiny ${s.status === "failed" ? "bad" : "muted"}">${esc(s.result)}</div>` : ""}</div>
      ${s.status === "approved" ? `<span class="pill running"><span class="dot run"></span>On the AI phone…</span>` : s.status === "done" ? `<span class="pill ok">${ic.check}${gbs(s.freed || 0)} freed</span>`
        : `<div class="row" style="gap:6px"><button class="btn sm primary" data-pdo="${esc(s.id)}">${ic.check}${s.status === "failed" ? "Try again" : "Approve"}</button><button class="btn sm ghost" data-pdis="${esc(s.id)}">Dismiss</button></div>`}</div></li>`;
  return `<div class="card pad-l crews" style="margin-bottom:12px"><div class="row between wrap" style="gap:6px"><h2>${open.length ? `${open.length} cleanup step${open.length > 1 ? "s" : ""} for the AI phone` : "Cleanup steps"}</h2>
      ${c.free ? `<span class="tiny muted">${gbs(c.free)} free of ${gbs(c.total)}${c.freed_total ? ` · ${gbs(c.freed_total)} freed so far` : ""}</span>` : ""}</div>
    ${fresh.length > 1 ? `<div class="row wrap" style="gap:8px;margin-top:10px;align-items:center"><button class="btn primary" data-pdoall="${esc(fresh.map((s) => s.id).join(","))}" data-n="${fresh.length}" data-size="${esc(gbs(freshSize))}">${ic.check}Approve all ${fresh.length} · ${gbs(freshSize)}</button><span class="tiny faint">The AI phone does them one after another.</span></div>` : ""}
    ${open.length ? `<ul class="crewf">${open.map(row).join("")}</ul>` : `<div class="small muted" style="margin-top:6px">Nothing waiting. The next weekly run looks again.</div>`}
    ${done.length ? `<details class="obsb"><summary class="small"><b>Done</b> <span class="muted">· ${done.length}</span></summary><ul class="crewf">${done.slice(-10).reverse().map(row).join("")}</ul></details>` : ""}
    ${explain("each-approve-runs-exactl", `Each Approve runs exactly that step once on the AI phone (within 30 minutes), with its block list and path checks. Nothing is deleted without it; you can't approve from the AI phone itself.`, "About this")}</div>`;
}
function bindCrew() {
  $$("[data-pdo]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (!(await act({ action: "phone_cleanup_do", id: b.dataset.pdo }, "Approved: the AI phone does it now"))) b.disabled = false; }));
  $$("[data-pdis]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (!(await act({ action: "phone_cleanup_dismiss", id: b.dataset.pdis }, "Dismissed: the phone keeps it as it is"))) b.disabled = false; }));
  $$("[data-pdoall]").forEach((b) => (b.onclick = async () => {        // it deletes a lot at once: a second tap confirms, in place
    if (!b.dataset.armed) {
      b.dataset.armed = "1"; b.innerHTML = `${ic.check}Tap again: delete and uninstall all ${b.dataset.n} (${b.dataset.size})`;
      setTimeout(() => { if (b.isConnected && !b.disabled) { delete b.dataset.armed; b.innerHTML = `${ic.check}Approve all ${b.dataset.n} · ${b.dataset.size}`; } }, 6000);
      return;
    }
    b.disabled = true;
    if (!(await act({ action: "phone_cleanup_do_all", ids: b.dataset.pdoall.split(",") }, "Approved: the AI phone works through them one after another"))) b.disabled = false;
  }));
  $$("[data-crun]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (!(await act({ action: "crew_run", id: b.dataset.crun }, "Started: it shows as running here until it is done"))) b.disabled = false; }));
  const forget = async (ids, btn) => { btn.disabled = true; const r = await act({ action: "crew_memory_forget", ids }, (x) => (x?.forgotten !== undefined ? `${x.forgotten} forgotten (reversible): no agent recalls them now` : "")); if (r?.forgotten === undefined) btn.disabled = false; };
  $$("[data-cforget]").forEach((b) => (b.onclick = () => forget([b.dataset.cforget], b)));
  $$("[data-cforgetall]").forEach((b) => (b.onclick = () => forget((S.crew.find((a) => a.id === "memory")?.suggestions || []).map((s) => s.id), b)));
}

const CREW_PRESETS = [["every", "5min", "every 5 minutes"], ["every", "10min", "every 10 minutes"], ["every", "1h", "every hour"],
  ["calendar", "*-*-* 03:30", "daily 03:30"], ["calendar", "*-*-* 07:30", "daily 07:30"], ["calendar", "Mon *-*-* 04:30", "Mondays 04:30"],
  ["calendar", "Sun *-*-* 04:00", "Sundays 04:00"], ["calendar", "*-*-01 09:00", "monthly, the 1st, 09:00"]];

// ---------- Agents (design "Agents in Mission Control", 28 Oct 2026): one list, one page for every agent ----------
// An agent is anything that works by itself on a schedule, an event or your request: a mission you gave the stack
// ("Yours") or a crew job that keeps it in shape ("Housekeeping"). "Mission" stays the word for the job; health is a
// colour on the card, not a second list. #/mission/<slug> and #/crew/<id> both open the same agent page.
let agentFilter = "all", atab = "now", showArchived = false;
const AGENT_FILTERS = [["all", "All"], ["yours", "Yours"], ["housekeeping", "Housekeeping"], ["live", "Live"]];
const AGENT_TABS = [["now", "Now"], ["history", "History"], ["tasks", "Tasks"], ["memory", "Memory"], ["payoff", "Results"], ["settings", "Settings"]];
const OLD_TAB = { overview: "now", outputs: "history", runs: "history" };            // links from before the agent page
const CREW_IC = { memory: "brain", skills: "tune", code: "code", ops: "pulse" };
const IN_FILTER = { all: () => true, yours: (a) => a.group === "yours", housekeeping: (a) => a.group === "housekeeping", live: (a) => a.live || a.queued };

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
    what: (CREW_AREAS.find(([k]) => k === a.area) || [0, "Housekeeping"])[1], live: a.state === "running", queued: false,
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
function engineAgent(h) {                             // an engine with open issues (its sessions roll up into it)
  return { key: `engine:${h.id}`, kind: "engine", id: h.id, href: h.run ? `#/live/${encodeURIComponent(h.run)}` : "#/missions", group: "housekeeping", title: h.name,
    icon: ic.layers, what: "Engine", live: false, queued: false, waiting: null, off: false, archived: false, status: "issues", schedule: "", next: null, last: null,
    lastOk: null, step: "", result: "", issues: h.issues || [], success: null, needs: [] };
}
function allAgents() {
  return [...(S.missions || []).map(missionAgent), ...(S.crew || []).map(crewAgent),
    ...(S.health?.items || []).filter((h) => h.kind === "engine" && h.issues?.length).map(engineAgent)];
}
const issueKeys = (as) => as.flatMap((a) => a.issues.map((i) => i.key)).filter(Boolean);
async function ackIssues(keys, btn) {
  if (!keys.length) return;
  if (btn) btn.disabled = true;
  const r = await act({ action: "health_ack", keys }, (x) => `${x.acknowledged} acknowledged: hidden until it happens again`);
  if (r) render(true); else if (btn) btn.disabled = false;
}

// the Agents tab's views in one row under its title: the list (#/missions) and the swarm's (swarm.js, #/swarm?tab=)
const AGENT_VIEWS = [["list", "Overview"], ["activity", "Activity"], ["agents", "Team"], ["improve", "Ideas"]];   // ten views became four (1 Nov 2026)
function agentViews(cur) {
  setTimeout(() => {                    // the row scrolls sideways on a phone: show the chosen one. Only the row moves: centring the tab
    const a = $(".agviews a.on"), row = a?.parentElement;   // into view also scrolled the page up to the row on every live redraw (FND-96)
    if (row) row.scrollLeft = a.offsetLeft - (row.clientWidth - a.offsetWidth) / 2;
  }, 0);
  return `<nav class="seg agviews">${AGENT_VIEWS.map(([k, l]) => `<a class="${cur === k ? "on" : ""}" href="${k === "list" ? "#/missions" : `#/swarm?tab=${k}`}">${l}</a>`).join("")}</nav>`;
}
// what the Agents overview shows of the state: a live update redraws the page only when this changes (a redraw every few
// seconds threw a phone's scroll back to the top, 1 Nov)
const missionsSig = () => JSON.stringify([agentFilter, showArchived, route.q.get("f"), allAgents()]);
function vMissions() {                     // the Agents tab (the route keeps its name: notifications and the guide link here)
  missionsSig.last = missionsSig();
  const all = allAgents(), cur = all.filter((a) => !a.archived), arch = all.filter((a) => a.archived);
  const f = route.q.get("f") || agentFilter;
  agentFilter = IN_FILTER[f] ? f : "all";
  const list = cur.filter(IN_FILTER[agentFilter]).sort(byUrgency);
  const need = cur.filter((a) => a.needs.length).length, live = cur.filter((a) => a.live).length, bad = cur.filter((a) => agentHealth(a) === "bad").length;
  const keys = issueKeys(cur);
  view.innerHTML = `<div class="hero"><div><h1>Agents</h1>
      <p class="agtop">${need ? `<b class="warn-t">${need} need${need > 1 ? "" : "s"} you</b>` : "Nothing needs you"}${live ? ` · <span class="run-t">${live} live</span>` : ""}${bad ? ` · <span class="err-t">${bad} with problems</span>` : ""} · ${cur.length} agents${keys.length ? ` · <button class="linkbtn" id="ackall">acknowledge all ${keys.length}</button>` : ""}</p></div></div>
    ${agentViews("list")}
    <div id="ovnow"></div>
    <div id="ovmap"><div class="card pad-l section"><div class="skeleton" style="height:320px"></div></div></div>
    <div class="section-h section wrap"><h2>Missions and housekeeping</h2><a class="btn sm" href="#/new">${ic.plus}New mission</a></div>
    <div class="agf">${AGENT_FILTERS.map(([k, l]) => `<button class="fchip ${agentFilter === k ? "on" : ""}" data-af="${k}">${l}<span>${cur.filter(IN_FILTER[k]).length}</span></button>`).join("")}</div>
    <div class="aglist">${list.map(agentCard).join("") || emptyState(`${ic.target}<div>${agentFilter === "live" ? "Nothing is running right now: an agent shows here while it works." : "No agents here."}</div>`, `<a class="btn sm" href="#/missions?f=all">All agents</a><a class="btn sm ghost" href="#/new">${ic.plus}New mission</a>`, "card")}</div>
    ${arch.length && agentFilter !== "housekeeping" && agentFilter !== "live" ? `<details class="agarch" ${showArchived ? "open" : ""}><summary class="small muted">Archived missions · ${arch.length}</summary><div class="aglist">${arch.map(agentCard).join("")}</div></details>` : ""}
    <div class="section">${explain("missions-list", `Yours: the missions you gave the stack. Housekeeping: the crew that keeps it in shape; it proposes, nothing changes without your tap. <a href="#/swarm?tab=agents">The team behind them</a> · ${how("missions")}`)}</div>`;
  $$("[data-af]").forEach((b) => (b.onclick = () => { agentFilter = b.dataset.af; route.q.set("f", agentFilter); history.replaceState(history.state, "", `#/missions?f=${agentFilter}`); render(true); }));
  const ad = $(".agarch");
  if (ad) ad.ontoggle = () => (showArchived = ad.open);
  if ($("#ackall")) $("#ackall").onclick = (e) => confirm(`Acknowledge all ${keys.length} open issues? Each comes back if it happens again.`) && ackIssues(keys, e.target);
  $$("[data-ack]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); ackIssues(b.dataset.ack.split(" "), b); }));
  swOverview();
}

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
  const meta = [a.group === "housekeeping" ? "Housekeeping · " + a.what : a.what, a.often ? "" : a.schedule, a.last ? `last ${when(a.last)}` : "never ran", a.success != null ? `${a.success}% ok` : ""].filter(Boolean).join(" · ");
  // the result unless an alert needs you: a note for the health doctor ("… called 3 times") never hides it (UX review 2026-10-30)
  const iss = a.issues.find((i) => i.severity === "alert"), line = iss?.text || a.result || a.issues[0]?.text;
  const cls = iss ? "err-t" : a.result ? "" : a.issues.length ? "warn-t" : "";
  if (a.kind === "engine") return `<div class="card agcard h-${h}"><div class="agic">${a.icon}</div><div class="agbody">
    <div class="agrow"><a class="agt" href="${a.href}">${esc(a.title)}</a><button class="btn sm ghost" data-ack="${esc(issueKeys([a]).join(" "))}">Acknowledge</button></div>
    <div class="tiny muted agmeta">Engine · ${a.issues.length} open issue${a.issues.length > 1 ? "s" : ""} · tap the name for the run</div>
    ${a.issues.map((i) => `<div class="small agres ${i.severity === "alert" ? "err-t" : "warn-t"}">${esc(i.text)}</div>`).join("")}</div></div>`;
  return `<a class="card agcard h-${h}" href="${a.href}"><div class="agic">${a.icon}</div><div class="agbody">
    <div class="agrow"><b class="agt">${esc(a.title)}</b>${chip}</div>
    <div class="tiny muted agmeta">${esc(meta)}</div>
    ${line ? `<div class="small agres ${cls}">${esc(line)}${a.issues.length - (iss ? 1 : 0) > 0 && (iss || a.result) ? ` <span class="faint">+${a.issues.length - (iss ? 1 : 0)} note${a.issues.length - (iss ? 1 : 0) > 1 ? "s" : ""}</span>` : ""}</div>` : ""}</div></a>`;
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
  return JSON.stringify([A.live, A.queued, A.waiting, A.status, A.needs, A.issues.map((i) => i.key), A.last, A.next, A.step, m?.runs?.[0]?.id, m?.runs?.[0]?.status, c?.suggestions?.length, c?.enabled, c?.schedule]);
}

function vAgent(kind, id) {
  const o = agentOf(kind, id);
  if (!o) { view.innerHTML = `<a class="back" href="#/missions">${ic.back}Agents</a><div class="card empty">No agent called ${esc(id)}.</div>`; return; }
  const { A, m, c } = o;
  const t = route.q.get("tab");
  const tabs = AGENT_TABS.concat(kind === "crew" && swIsCrew(c.id) && (S?.swarm?.cards || []).includes(c.id) ? [["team", "Team"]] : []);   // one page per agent
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
    ${!A.archived ? `<button class="btn ghost danger" data-a="archive">${ic.archive}Archive</button>` : ""}`
    : `<button class="btn primary" data-a="crew_run" ${A.live ? "disabled" : ""}>${ic.play}Run now</button>`;
  const pill = kind === "mission" ? statusPill(m) : (([cls, l]) => `<span class="pill ${cls}">${A.live ? '<span class="dot run"></span>' : ""}${l}</span>`)(CREW_STATE[c.state] || ["archived", c.state]);
  view.innerHTML = `<a class="back" href="#/missions">${ic.back}Agents</a>
  <div class="aghead h-${agentHealth(A)}"><div class="agic lg">${A.icon}</div><div class="grow" style="min-width:0">
    <h1 class="agh1">${esc(A.title)}</h1>
    <div class="row wrap small muted" style="gap:4px 8px;margin-top:6px">${pill}<span>${A.group === "yours" ? "Yours" : "Housekeeping"} · ${esc(A.what)}</span><span>${ic.clock}${esc(A.schedule || "on request")}${A.next ? ` · next ${esc(when(A.next))}` : ""}</span></div>
    <div class="small muted agwhat">${esc(kind === "mission" ? (m.goal || "").replace(/[#*_>`]/g, "").split("\n").find((l) => l.trim()) || "" : c.what)}</div>
    ${m?.triggers?.length ? `<div class="chips" style="margin-top:8px">${m.triggers.map((x) => `<span class="tag trig">${ic.bolt}${esc(x.text)}</span>`).join("")}</div>` : ""}
  </div></div>
  ${m?.task ? `<div class="banner info" style="margin-top:12px">${ic.target}<span class="grow">${m.type === "shopping" ? `Its checks run as <a href="#/task/${m.task}">task #${m.task}</a>: each one is a run of the task. Proposals, your approval and the purchase stay here.` : `Its runs are <a href="#/task/${m.task}">task #${m.task}</a>'s, under the Conductor. Its topic, wiki and history stay here.`}</span></div>` : ""}
  ${A.needs.map((n) => `<div class="banner info" style="margin-top:12px">${ic.alert}<span class="grow"><b>Needs you:</b> ${esc(n)}</span></div>`).join("")}
  ${(() => {                                              // alerts on top; the health doctor's notes folded into one line (UX review 2026-10-30)
    const issue = (x) => `<div class="banner ${x.severity === "alert" ? "" : "note"} agissue" style="margin-top:8px">${ic.alert}<span class="grow wrap">${esc(x.text)}${x.run ? ` · <a href="#/live/${encodeURIComponent(x.run)}">the run</a>` : ""}<span class="tiny faint"> · ${x.severity === "alert" ? "alert" : "note"}</span></span><button class="btn sm ghost" data-ack="${esc(x.key || "")}">Acknowledge</button></div>`;
    const alerts = A.issues.filter((x) => x.severity === "alert"), notes = A.issues.filter((x) => x.severity !== "alert");
    return alerts.map(issue).join("") + (notes.length ? `<details class="agnotes" style="margin-top:8px"><summary class="small muted">${notes.length} technical note${notes.length > 1 ? "s" : ""} for the health doctor (nothing for you to do)</summary>${notes.map(issue).join("")}</details>` : "")
      + (A.issues.length > 1 ? `<div class="row" style="justify-content:flex-end;margin-top:6px"><button class="linkbtn" data-ack="${esc(issueKeys([A]).join(" "))}">acknowledge all ${A.issues.length}</button></div>` : "");
  })()}
  <div class="actions">${acts}</div>
  <div class="seg agtabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${atab === k ? "on" : ""}">${l}</button>`).join("")}</div>
  <div id="tabbody" class="section" style="margin-top:14px"></div>`;
  $$("[data-t]").forEach((b) => (b.onclick = () => { atab = b.dataset.t; history.replaceState(history.state, "", `${A.href}?tab=${atab}`); render(true); }));
  $$("[data-ack]").forEach((b) => (b.onclick = () => ackIssues(b.dataset.ack.split(" ").filter(Boolean), b)));
  $$("[data-a]").forEach((b) => (b.onclick = async () => {
    const a = b.dataset.a;
    if (a === "archive" && !confirm(`Archive “${m.title}”? It stops; all results stay in the vault.`)) return;
    b.disabled = true;
    const req = a === "crew_run" ? { action: "crew_run", id: c.id } : a === "deep" ? { action: "run", slug: m.slug, deep: true } : { action: a, slug: m.slug };
    if (!(await act(req, { run: "Run started: follow it here; the result lands on this page", deep: "Deep research started: it takes longer; the result lands on this page",
      pause: "Paused: it does not run until you resume it", resume: "Resumed: it runs again at its next time", archive: "Archived: it runs no more; its results stay",
      crew_run: "Started: it shows as running here until it is done" }[a]))) b.disabled = false;
  }));
  ({ now: agentNow, history: agentHistory, memory: agentMemory, payoff: agentPayoff, settings: agentSettings, team: (box) => swAgentPanel(box, c.id, true),
     tasks: (box) => agentTasksInto(box, kind === "mission" ? `mission:${m.slug}` : c.id) })[atab]($("#tabbody"), kind, A, m, c);
}

// Now: what it needs from you, then the live log (or the latest run's), then the latest result
async function agentNow(body, kind, A, m, c) {
  const needs = (m?.needs || []).map((n) => n.split(":"));
  body.innerHTML = `${needs.length ? `<div class="card pad-l" style="margin-bottom:12px"><h2>Needs access</h2><div class="small muted" style="margin-top:4px">This mission uses your apps. Its tools refuse until you grant this; revoke any time (Stack → Connections).</div>
      <div class="stack" style="margin-top:10px;gap:10px">${needs.map(([cn, sc]) => grantRow(cn, sc, `${CONN_NAME[cn] || cn}`, S.connections?.[cn]?.grants?.[sc], m.slug)).join("")}</div></div>` : ""}
    ${c?.suggestions?.length ? `<div class="card pad-l crews" style="margin-bottom:12px"><div class="row between wrap" style="gap:6px"><h2>${c.suggestions.length} memor${c.suggestions.length > 1 ? "ies" : "y"} to look at</h2><button class="btn sm ghost" data-cforgetall="1">Forget all ${c.suggestions.length}</button></div>
      <ul class="crewf">${c.suggestions.map((s) => `<li><div class="small quote">${esc(s.text)}</div><div class="row between wrap" style="gap:6px"><span class="tiny muted">${esc(s.why)}${s.note ? " · " + esc(s.note) : ""}</span><button class="btn sm ghost" data-cforget="${esc(s.id)}">Forget</button></div></li>`).join("")}</ul>
      <div class="tiny faint">Forgetting retires the fact from recall; it stays in the archive and can be restored.</div></div>` : ""}
    ${m?.type === "shopping" ? shopMissionHtml(m) : ""}
    ${c?.actions?.length ? phoneStepsHtml(c) : ""}
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
      <ul class="jlist">${notes.map((x) => li("notes", x)).join("") || `<li class="small muted">None yet. The agent adds one with agent_note, the memory curator folds old entries into them, or you add one here.</li>`}</ul>
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

// Payoff: what its runs cost and what came of them
async function agentPayoff(body, kind, A, m, c) {
  const h = (S.health?.items || []).find((i) => (m ? i.kind === "mission" && i.slug === m.slug : i.kind === "crew" && i.id === c.id));
  if (m) {
    const st = m.stats, okRate = st.runs ? Math.round((st.ok / st.runs) * 100) + "%" : "–";
    const done = (m.runs || []).filter((r) => r.output && r.status === "ok").slice(0, 12);   // cap: list (the newest; History has every run)
    body.innerHTML = `<div class="card pad-l"><div class="row between wrap" style="gap:8px"><h2>What it delivered</h2><span class="tiny faint">${m.outputs?.length || 0} results in the vault, newest first</span></div>
      ${done.length ? `<div class="list" style="margin-top:6px">${done.map((r) => `<a href="#/read?path=${encodeURIComponent(r.output)}"><div class="ic ok">${ic.doc}</div>
        <div class="grow" style="min-width:0"><div class="ttl">${esc(when(r.ended || r.started))}${r.trigger === "event" ? ` <span class="tag trig">${ic.bolt}event</span>` : ""}</div>
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
  kpi.insertAdjacentHTML("afterend", `${openProps ? `<a class="banner info section" href="#/swarm?tab=improve">${ic.next}<span class="grow">${openProps} open idea${openProps > 1 ? "s" : ""} of its own under Agents → Ideas</span></a>` : ""}
    ${c.findings?.length ? `<div class="card pad-l section"><h2>Last findings</h2><ul class="crewf">${c.findings.map((f) => `<li><span class="tag">${esc(f.kind || "")}</span> ${f.file ? `<span class="mono tiny">${esc(f.file)}${f.line ? ":" + f.line : ""}</span> ` : ""}${esc(f.issue || "")}${f.proposal ? ` <a class="tiny" href="#/swarm?tab=improve">idea: ${esc(f.proposal)}</a>` : ""}${f.acknowledge && openKeys.has(f.key) ? ` <button class="btn sm ghost" data-ack="${esc(f.key)}">Acknowledge</button>` : ""}</li>`).join("")}</ul></div>` : ""}`);
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
    l.model && l.ts ? `<a class="btn sm" target="_blank" rel="noopener" href="${phoenixHref(l)}">${ic.search}Open in Phoenix · the full prompt and response</a>` : "",
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
    <div class="flist">${files.slice(0, 20).map(row).join("")}</div>
    ${files.length > 20 ? `<details><summary class="tiny muted">${files.length - 20} more</summary><div class="flist">${files.slice(20).map(row).join("")}</div></details>` : ""}`;
}
function statsHtml(d) {
  if (!d) return "";
  const m = d.model || {}, t = d.time || {};
  return `<div class="row wrap small" style="gap:14px">${m.calls ? `<span><b>${m.calls}</b> model calls · ${tok(m.tokens_per_call)} tokens/call · <b>${m.cache_pct}%</b> cached${m.p50_ms ? ` · ${fmtMs(m.p50_ms)} typical, ${fmtMs(m.p95_ms)} slowest 5 %` : ""}</span>` : ""}
      ${t.total_s ? `<span>time: ${dur(t.total_s)}${t.model_s ? ` · model ${dur(t.model_s)}` : ""}${t.tools_s ? ` · tools ${dur(t.tools_s)}` : ""}</span>` : ""}</div>
    ${d.tools?.length ? `<table class="stab"><tr><th>Tool</th><th>calls</th><th>errors</th><th>avg</th><th>max</th></tr>${d.tools.slice(0, 15).map((x) => `<tr><td class="mono">${esc(x.tool)}</td><td>${x.calls}</td><td class="${x.errors ? "err-t" : ""}">${x.errors || ""}</td><td>${x.avg_s != null ? x.avg_s + " s" : ""}</td><td>${x.max_s != null ? x.max_s + " s" : ""}</td></tr>`).join("")}</table>` : ""}`;
}
const PROB_LABEL = { "unknown-tool": "Unknown tool names", "empty-args": "Calls without arguments", "bad-args": "Arguments not JSON",
  repeat: "Same call again and again", "tool-error": "Tool errors", limit: "Usage limit", "partial-read": "Answer after cut-off results", "no-end": "No clean end" };
function problemsHtml(ps) {
  const groups = {};
  ps.forEach((p) => (groups[p.kind] = groups[p.kind] || []).push(p));
  return `<div class="obsprob"><b class="small">Problems · ${ps.length}</b>${Object.entries(groups).map(([k, xs]) => `<details><summary class="small err-t">${esc(PROB_LABEL[k] || k)} ×${xs.length}</summary>
    ${xs.slice(0, 30).map((p) => `<div class="tiny">+${Math.round(p.t || 0)}s · ${esc(p.text)}</div>`).join("")}</details>`).join("")}</div>`;
}
function touchesHtml(d, files) {
  if (!d) return `<div class="small muted">Recorded for runs from 28 October on.</div>`;
  files = files || d.files || [];
  const changed = files.filter((f) => f.modified), read = files.filter((f) => !f.modified);
  const sec = (title, n, body, cls = "") => `<details class="obsb" ${n && cls ? "open" : ""}><summary class="small"><b class="${cls}">${title}</b> <span class="muted">· ${n}</span></summary>${body}</details>`;
  const lines = (xs, mono) => xs.map((x) => `<div class="${mono ? "mono " : ""}tiny ellipsis" title="${esc(x)}">${esc(x)}</div>`).join("") || `<div class="tiny muted">none</div>`;
  return `<div class="tiny muted">${d.used_tools.length} tools used${d.allowed_tools.length ? ` of ${d.allowed_tools.length} allowed` : ""}${d.grants?.length ? ` · grants: ${d.grants.map(esc).join(", ")}` : ""}${d.mails_read ? ` · ${d.mails_read} mails read` : ""}${d.phone_screens ? ` · ${d.phone_screens} phone screens` : ""}</div>
    ${sec("Changed", changed.length, filesHtml(changed), changed.length ? "warn-t" : "")}
    ${sec("Read", read.length + d.urls.length + d.searches.length, `${read.length ? filesHtml(read) : ""}${d.urls.length ? `<div style="margin-top:6px"><b class="tiny">Pages</b>${lines(d.urls, true)}</div>` : ""}${d.searches.length ? `<div style="margin-top:6px"><b class="tiny">Searches</b>${lines(d.searches)}</div>` : ""}`)}
    ${sec("Refused", d.refused?.length || 0, (d.refused || []).map((r) => `<div class="tiny">+${Math.round(r.t || 0)}s <b>${esc(r.tool)}</b>: ${esc(r.why)}</div>`).join("") || `<div class="tiny muted">none</div>`, d.refused?.length ? "err-t" : "")}
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

function agentName(a) {
  return ({ main: "Hermes (chat)", mission: "Hermes (mission)", scout: "Scout", curator: "Curator", builder: "Builder (ChatGPT)", "claude-builder": "Builder (Claude Code)",
            "claude-task": "Claude task", "claude-review": "Claude review", "claude-maintainability": "Claude review (Crew)", "ai-phone": "AI phone", mail: "Gmail", runner: "Runner" })[a]
    || (String(a || "").startsWith("mission:") ? (S?.missions || []).find((m) => "mission:" + m.slug === a)?.title || "Mission " + a.slice(8)
    : String(a || "").startsWith("crew:") ? (S?.crew || []).find((c) => "crew:" + c.id === a)?.name || "Crew: " + a.slice(5) : String(a || ""));
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
  if (!(await mountRun($("#lv"), id)) && $("#lv")) $("#lv").innerHTML = emptyState("No run record for this yet. Runs show here from the moment they start (recorded from 28 October on).",
    `<a class="btn sm" href="#/swarm?tab=timeline">${ic.history}Every run on the timeline</a>`, "card pad-l");
}

function liveHtml(V, opts = {}) {
  const st = V.live ? ["running", "Live"] : RT_STATE[V.end_state] || ["archived", V.end_state || "Ended"];
  const k = V.stats.model, T = V.touches, m = V.manifest || {};
  const llm = V.events.filter((e) => e.kind === "llm"), sum = (f) => llm.reduce((n, e) => n + ((e.tokens || {})[f] || 0), 0);
  const title = V.name || V.title || agentName(V.agent) || V.run;
  const parent = V.ref && /^(mission-run|build|claude-task|crew):/.test(V.ref) ? `<a class="tiny" href="#/live/${encodeURIComponent(V.ref)}">part of ${esc(V.ref)}</a>` : "";
  const priced = llm.filter((e) => costOf(e.title, e.tokens) != null), paid = priced.reduce((n, e) => n + costOf(e.title, e.tokens), 0);
  const nums = `<span>${dur(V.seconds)}</span><span>${k.calls} model calls · ${tok(sum("in"))} in${k.cache_pct ? ` · ${k.cache_pct}% cached` : ""}${priced.length ? ` · ${ifPaid(paid)}` : ""}${sum("reasoning") ? ` · ${tok(sum("reasoning"))} thinking` : ""}</span><span>${V.stats.tools.reduce((n, t) => n + t.calls, 0)} tool calls</span>${llm.length ? `<a target="_blank" rel="noopener" href="/api/phoenix" title="Every model call with its full prompt and response (open a model call in the log for its own trace)">traces in Phoenix ↗</a>` : ""}`;
  const head = opts.compact
    ? `<div class="row between wrap" style="gap:6px;align-items:center"><div class="row wrap" style="gap:6px;align-items:center"><span class="pill ${st[0]}">${V.live ? `<span class="dot run"></span>` : ""}${st[1]}</span><b class="small">${V.live ? "Now" : "Latest run"} · ${dt(V.started)}</b></div><a class="tiny" href="#/live/${encodeURIComponent(V.run)}">full view →</a></div>
       <div class="row wrap tiny muted" style="gap:2px 10px;margin-top:4px">${nums}</div>`
    : `<div class="row wrap" style="gap:8px;align-items:center"><span class="pill ${st[0]}">${V.live ? `<span class="dot run"></span>` : ""}${st[1]}</span><h1 class="grow lvh1" title="${esc(title)}">${esc(title)}</h1></div>
       ${V.title && V.name && !V.name.includes(V.title) && !/^##\s*Your memory/.test(V.title) ? `<div class="small muted wrap" style="margin-top:4px" title="${esc(V.title)}">${esc(V.title)}</div>` : ""}
       <div class="row wrap small muted" style="gap:4px 12px;margin-top:6px"><span>${esc(agentName(V.agent))}</span>${nums}${parent}</div>`;
  return `<div class="card pad-l lvcard">${head}
      ${V.children.length ? `<div class="row wrap" style="gap:6px;margin-top:8px">${V.children.map((c) => `<a class="tag" href="#/live/${encodeURIComponent(c.run)}" title="${esc(c.title || "")}">${esc(agentName(c.agent))}${c.end_state ? " · " + esc(c.end_state) : " · live"}</a>`).join("")}</div>` : ""}
      ${(V.drift || []).length ? `<div class="tiny muted" style="margin-top:6px">${ic.tune}Changed since its last run: ${V.drift.map(esc).join("; ")}</div>` : ""}
      ${V.problems.length ? problemsHtml(V.problems) : ""}
      <div class="row between wrap" style="gap:6px;margin-top:10px"><b class="small">Log</b>${levelSeg()}</div>
      ${logHtml(V.events, { cls: V.live ? "live" : "" })}
      <details class="obsb" ${opts.compact ? "" : "open"}><summary class="small"><b>What it touched</b> <span class="muted">· ${T.files.length} files · ${T.urls.length} pages${T.connections.length ? ` · ${T.connections.length} connections` : ""}</span></summary>
        ${V.box ? `<div class="lvbox"><b class="small">${ic.lock || ""}The box it works in</b><div class="tiny muted">${esc(V.box.where || "")}${V.box.can ? ` · may: ${esc(V.box.can)}` : ""}${V.box.network ? ` · network: ${esc(V.box.network)}` : ""}${V.box.never ? ` · never: ${esc(V.box.never)}` : ""}</div></div>` : ""}
        ${touchesHtml(T)}
        <details class="obsb" ${T.connections.length ? "open" : ""}><summary class="small"><b>Connections used</b> <span class="muted">· ${T.connections.length}</span></summary>${T.connections.map((c) => `<div class="tiny"><span class="mono">${esc(c.tool)}</span> ×${c.calls}</div>`).join("") || `<div class="tiny muted">none</div>`}</details></details>
      <details class="obsb"><summary class="small"><b>Statistics</b></summary>${statsHtml(V.stats)}</details>
      ${m.agent ? `<details class="obsb"><summary class="small"><b>Manifest</b> <span class="muted">· what it started with${V.drift?.length ? " · drift" : ""}</span></summary><div class="tiny mono" style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(Object.entries(m).map(([a, b]) => `${a} ${typeof b === "object" ? JSON.stringify(b) : b}`).join("\n"))}</div></details>` : ""}
    </div>`;
}

const openResults = new Set();                          // results you opened stay open while the page redraws
async function loadInto(el, path, preview) {
  try {
    const t = await api(`/api/file?path=${encodeURIComponent(path)}`);
    const open = !preview || openResults.has(path);
    el.innerHTML = `<div class="row between"><h2>Latest result</h2><a class="tiny muted" href="#/read?path=${encodeURIComponent(path)}&m=${encodeURIComponent(route.args[0] || "")}">${ic.doc}Full page</a></div>
      <div class="md result ${open ? "" : "clamped"}" style="margin-top:8px">${md(t)}</div>
      ${preview ? `<button class="btn sm ghost rmore" type="button">${open ? "Show less" : "Show all"}</button>` : ""}`;
    if (!preview) return;
    const body = el.querySelector(".result"), more = el.querySelector(".rmore");
    if (body.scrollHeight <= body.clientHeight + 4 && !open) { body.classList.remove("clamped"); more.remove(); return; }   // short: nothing to open
    const toggle = () => {
      const now = body.classList.toggle("clamped");
      now ? openResults.delete(path) : openResults.add(path);
      more.textContent = now ? "Show all" : "Show less";
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
  api(`/api/file?path=${encodeURIComponent(p)}`).then((t) => ($("#doc").innerHTML = md(t))).catch(() => ($("#doc").textContent = "Not readable."));
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
    <div class="row" data-for="price_move"><input class="input" data-k="symbol" placeholder="Symbol, e.g. CCJ" value="${v("symbol")}"><input class="input" data-k="pct" type="number" min="1" max="50" step="0.5" value="${v("pct", 5)}" style="max-width:90px"><span class="small muted">%</span></div>
    <input class="input" data-k="query" data-for="news" placeholder="Search, e.g. ASP Isotopes contract" value="${v("query")}">
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
    ${schedHtml(m.schedule)}
    ${trigEditor(m.triggers)}
    ${m.type === "task" ? `<div class="card pad" style="margin-top:16px;padding-top:4px;padding-bottom:4px"><label class="switch"><span><b>Deep research</b><div class="small muted">Every run plans 3–5 research steps, works through them, then combines the findings</div></span><input type="checkbox" name="deep" ${m.depth === "deep" ? "checked" : ""}></label></div>` : ""}
    <div class="field"><span>Cost</span><small style="font-size:13.5px">Runs only on your ChatGPT subscription: $0. If ChatGPT pauses the stack, runs wait and retry every 30 minutes.</small></div>
    ${deliverHtml(m.deliver || [])}
    ${m.type === "task" ? `<label class="field"><span>Goal</span><textarea class="input" name="goal" rows="7">${esc(m.goal)}</textarea></label>` : `
      <label class="field"><span>Key questions</span><textarea class="input" name="kq" rows="6">${esc((b.key_questions || []).join("\n"))}</textarea><small>One per line. The report follows this order.</small></label>
      <label class="field"><span>Google News searches</span><textarea class="input" name="search" rows="5">${esc((b.search || []).join("\n"))}</textarea><small>One search per line.</small></label>
      <label class="field"><span>Watchlist</span><textarea class="input" name="watch" rows="5">${esc((b.watchlist || []).map((w) => w.name + (w.symbol ? " | " + w.symbol : "")).join("\n"))}</textarea><small>“Name | ticker” (Yahoo), ticker optional.</small></label>
      <label class="field"><span>RSS feeds</span><textarea class="input" name="feeds" rows="3">${esc((b.feeds || []).join("\n"))}</textarea></label>
      <label class="field"><span>SEC filings in the daily report (US tickers)</span><input class="input" name="filings" value="${esc((b.filings || []).join(", "))}"></label>
      <label class="field"><span>Notes for the desk</span><textarea class="input" name="notes" rows="4">${esc(b.notes || "")}</textarea><small>Style and focus instructions, e.g. “explain jargon”, “skip penny stocks”.</small></label>`}
    <div class="form-foot"><button class="btn primary" type="submit">${ic.check}Save</button><a class="btn" href="#/chat?mission=${encodeURIComponent(m.slug)}">${ic.tune}Tune in chat instead</a></div>
  </form>`;
  const f = $("#sf");
  bindSched(f); bindTrig(f);
  f.onsubmit = async (e) => {
    e.preventDefault();
    const sched = readSched(f);
    if (!sched) return toast("Choose at least one day", true);
    const fields = { title: f.title.value.trim(), schedule: sched, deliver: readDeliver(f), triggers: readTrig(f) };
    if (m.type === "task") { fields.goal = f.goal.value; fields.depth = f.deep.checked ? "deep" : "standard"; }
    else {
      fields.key_questions = lines(f.kq.value); fields.search = lines(f.search.value); fields.feeds = lines(f.feeds.value); fields.notes = f.notes.value;
      fields.filings = f.filings.value.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
      const old = Object.fromEntries((b.watchlist || []).map((w) => [w.name, w]));
      fields.watchlist = lines(f.watch.value).map((l) => { const [n, s] = l.split("|").map((x) => x.trim()); return { ...(old[n] || {}), name: n, symbol: s || undefined }; });
    }
    const btn = $("button[type=submit]", f); btn.disabled = true;
    await act({ action: "update", slug: m.slug, fields }, (x) => `Saved ${(x.changed || []).join(", ") || "it"}: the next run uses it`);
    btn.disabled = false;
  };
}

function vNew() {
  const kind = route.q.get("type") || "briefing";
  view.innerHTML = `<a class="back" href="#/missions">${ic.back}Agents</a>
  <div class="hero"><div><h1>New mission</h1><p>Describe what should get done. The agents set up the rest.</p></div></div>
  <form class="card pad-l" id="nf" autocomplete="off">
    <div class="choice">
      <label><input type="radio" name="type" value="briefing" ${kind === "briefing" ? "checked" : ""}><div class="type-ic">${ic.news}</div><div><b>Daily briefing</b><small>Researches the news on a topic and writes a report with sources. Builds a topic wiki over time.</small></div></label>
      <label><input type="radio" name="type" value="task" ${kind === "task" ? "checked" : ""}><div class="type-ic">${ic.rocket}</div><div><b>Long-term task</b><small>An agent works toward a goal over many runs and keeps notes.</small></div></label>
      <label><input type="radio" name="type" value="cleanup" ${kind === "cleanup" ? "checked" : ""}><div class="type-ic">${ic.trash}</div><div><b>Cleanup analysis</b><small>Where the space goes on the AI phone or the PC, and what could go (safe / caution / never). Never deletes.</small></div></label>
      <label><input type="radio" name="type" value="shopping" ${kind === "shopping" ? "checked" : ""}><div class="type-ic">${ic.coin}</div><div><b>Shopping</b><small>Works out what fits (from your PC's own facts), compares offers in several shops, ranks them. Never buys.</small></div></label>
    </div>
    <label class="field"><span>Title</span><input class="input" name="title" required minlength="3" maxlength="80" placeholder="e.g. Lithium market"></label>
    <label class="field"><span>What should it do?</span><textarea class="input" name="desc" rows="5" placeholder="e.g. Follow lithium producers, prices and new projects in Europe and Australia, especially Albemarle, SQM and Pilbara.">${esc(route.q.get("desc") || "")}</textarea></label>
    <div id="sched"></div>
    ${trigEditor([])}
    <div class="card pad" id="watchbox" style="margin-top:16px;padding-top:4px;padding-bottom:4px"><label class="switch"><span><b>Watch the price</b><div class="small muted">Checks daily; tells you only when the best price drops 5 % or more</div></span><input type="checkbox" name="watch"></label></div>
    <div class="card pad" id="deepbox" style="margin-top:16px;padding-top:4px;padding-bottom:4px"><label class="switch"><span><b>Deep research</b><div class="small muted">Each run: plan, 3–5 research steps, synthesis</div></span><input type="checkbox" name="deep"></label></div>
    <div class="field"><span>Cost</span><small style="font-size:13.5px">Runs only on your ChatGPT subscription: $0.</small></div>
    ${deliverHtml(["telegram", "app"])}
    <div class="card pad" style="margin-top:12px;padding-top:4px;padding-bottom:4px"><label class="switch"><span><b>Run once right away</b></span><input type="checkbox" name="now" checked></label></div>
    <div class="form-foot"><button class="btn primary" type="submit" style="flex:1">${ic.rocket}Start mission</button></div>
  </form>`;
  const f = $("#nf");
  const setType = () => { $("#sched").innerHTML = schedHtml(f.type.value === "briefing" ? "daily 06:30" : "manual"); bindSched(f); $("#deepbox").hidden = f.type.value !== "task"; $("#watchbox").hidden = f.type.value !== "shopping"; };
  $$("[name=type]", f).forEach((r) => (r.onchange = setType)); setType(); bindTrig(f);
  f.onsubmit = async (e) => {
    e.preventDefault();
    let sched = readSched(f);
    if (!sched) return toast("Choose at least one day", true);
    const watch = f.type.value === "shopping" && f.watch.checked;      // a price watch checks daily
    if (watch && sched === "manual") sched = "daily 08:00";
    const btn = $("button[type=submit]", f); btn.disabled = true;
    btn.innerHTML = `<span class="spin"></span>${f.type.value === "briefing" ? "Drafting the brief, checking sources…" : "Creating…"}`;
    const r = await act({ action: "create", type: f.type.value, title: f.title.value.trim(), description: f.desc.value.trim(), schedule: sched,
      triggers: readTrig(f), depth: f.deep.checked ? "deep" : null, deliver: readDeliver(f), run_now: f.now.checked, watch_pct: watch ? 5 : 0 },
      (x) => (x?.slug ? (x.duplicate ? "It already exists: here it is" : "Mission created" + (f.now.checked ? ": its first run is starting" : ": it runs on its schedule")) : ""));
    if (r?.slug) { location.hash = `#/mission/${encodeURIComponent(r.slug)}`; }
    else { btn.disabled = false; btn.innerHTML = `${ic.rocket}Start mission`; }
  };
}

// ---------- chat: Hermes, with history on the server (Claude-style) ----------
let chats = [], cur = null, streaming = false, follower = null, pending = [], editing = null, chatQuery = "";
let MODELS = null;
const pref = (k, d) => { try { return localStorage.getItem(k) || d; } catch (_) { return d; } };
const setPref = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
const EFFORT_LABEL = { low: "Low", medium: "Medium", high: "High", xhigh: "Extra high" };

async function loadChats() { try { chats = await api(`/api/chats${chatQuery ? "?q=" + encodeURIComponent(chatQuery) : ""}`); } catch (_) { chats = []; } }

function chatListHtml() {
  const today = new Date().toDateString();
  const groups = { Pinned: [], Today: [], Earlier: [] }, auto = chats.filter((c) => c.origin && c.origin !== "owner");
  chats.filter((c) => !auto.includes(c)).forEach((c) => groups[c.pinned ? "Pinned" : new Date(c.updated * 1000).toDateString() === today ? "Today" : "Earlier"].push(c));
  const item = (c) => `<a class="citem ${cur?.id === c.id ? "on" : ""}" href="#/chat?c=${c.id}">
    <span class="grow wrap">${c.pending ? '<span class="dot run" style="display:inline-block;margin-right:6px"></span>' : ""}${c.mission ? `<span class="mtag">${ic.tune}</span>` : ""}${esc(c.title || "New chat")}</span>
    <button class="del" data-pinchat="${c.id}" data-p="${c.pinned ? 1 : 0}" title="${c.pinned ? "Unpin" : "Pin"}">${c.pinned ? ic.x : ic.target}</button>
    <button class="del" data-delchat="${c.id}" title="Delete">${ic.trash}</button></a>`;
  const mine = Object.entries(groups).filter(([, l]) => l.length).map(([g, l]) => `<div class="cgroup">${g}</div>${l.map(item).join("")}`).join("");
  const tests = auto.length ? `<details class="cauto" data-keep="cauto"><summary class="cgroup">From tests and agents · ${auto.length}</summary><div class="tiny faint" style="padding:0 10px 6px">Sent by the stack's own checks and helper agents, not from your devices.</div>${auto.map(item).join("")}</details>` : "";
  return (mine || (!auto.length ? `<div class="small muted" style="padding:10px">${chatQuery ? "Nothing found." : "No chats yet."}</div>` : "")) + tests;
}

function refreshList() { if ($("#citems")) { $("#citems").innerHTML = chatListHtml(); bindChatList(); } }

function bindChatList() {
  $$("[data-delchat]").forEach((b) => (b.onclick = async (e) => {
    e.preventDefault(); e.stopPropagation();
    if (!confirm("Delete this chat?")) return;
    await api(`/api/chats/${b.dataset.delchat}`, { method: "DELETE" });
    if (cur?.id === b.dataset.delchat) location.hash = "#/chat"; else { await loadChats(); refreshList(); }
  }));
  $$("[data-pinchat]").forEach((b) => (b.onclick = async (e) => {
    e.preventDefault(); e.stopPropagation();
    await api(`/api/chats/${b.dataset.pinchat}`, { method: "PATCH", body: JSON.stringify({ pinned: b.dataset.p !== "1" }) });
    await loadChats(); refreshList();
  }));
}

function selectHtml() {
  const model = pref("mc-model", "gpt-sub"), effort = pref("mc-effort", "medium");
  return `<select class="pick" id="pmodel" title="Model">${(MODELS?.models || []).map((m) => `<option value="${m.id}" ${m.id === model ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select>
    <select class="pick" id="peffort" title="Reasoning effort">${(MODELS?.efforts || []).map((e) => `<option value="${e}" ${e === effort ? "selected" : ""}>${EFFORT_LABEL[e] || e} effort</option>`).join("")}</select>`;
}

function toolsHtml(tools, live) {
  if (!tools?.length) return "";
  const ev = tools.map((t, i) => ({ id: "c" + i, kind: t.status === "error" ? "error" : "call", title: t.name, detail: t.detail || "", status: t.status }));   // the agent log, without times
  return `<details class="tools" ${live ? "open" : ""}><summary>${live ? '<span class="spin" style="width:12px;height:12px;vertical-align:-1px"></span> ' : ""}${tools.length} step${tools.length > 1 ? "s" : ""}: ${esc([...new Set(tools.map((t) => t.name))].slice(0, 4).join(", "))}</summary>${logHtml(ev, { bare: true, level: "all", cls: "chatlog" })}</details>`;
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

function bubble(x, i) {
  if (x.role === "user") {
    return `<div class="mrow user" data-i="${i}"><div class="msg user">${attsHtml(x.attachments)}${x.content && x.content !== "(see attachment)" ? `<div class="utext">${esc(x.content)}</div>` : ""}</div>
      <div class="macts"><button data-copy="${i}" title="Copy">${ic.doc}</button><button data-edit="${i}" title="Edit and resend">${ic.tune}</button></div></div>`;
  }
  return `<div class="mrow assistant" data-i="${i}"><div class="msg assistant">${toolsHtml(x.tools)}${reasoningHtml(x.reasoning)}<div class="md">${md(x.content)}</div>${x.limit ? limitHtml(x) : ""}</div>
    <div class="macts"><button data-copy="${i}" title="Copy">${ic.doc}</button><button data-regen="${i}" title="Regenerate">${ic.repeat}</button>${x.model ? `<span class="tiny faint">${esc(modelName(x.model))}${x.effort ? " · " + esc(x.effort) : ""}</span>` : ""}</div></div>`;
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
  const cid = route.q.get("c"), mslug = route.q.get("mission");
  if (!MODELS) MODELS = await api("/api/models").catch(() => ({ models: [{ id: "gpt-sub", name: "GPT-6.1 Sol" }], efforts: ["medium"] }));
  await loadChats();
  cur = cid ? await api(`/api/chats/${cid}`).catch(() => null) : null;
  if (route.name !== "chat") return;
  if (cur?.error) cur = null;
  pending = []; editing = null;
  const mis = mslug || cur?.mission;
  const m = mis && S ? S.missions.find((x) => x.slug === mis) : null;
  const sugg = m ? [`What does this mission track right now?`, `Make it focus more on `, `Add a key question about `, `Alert me when ${m.brief?.filings?.[0] || "the company"} files with the SEC`]
    : ["What are my missions doing?", "What's new on uranium today?", "Research Boss Energy and e-mail me an analysis", "Watch ASPI and tell me if it moves 8 % in a day"];
  view.innerHTML = `<div class="chatwrap">
    <aside class="chatlist card" id="clist">
      <div class="row between" style="padding:8px 8px 4px"><b>Chats</b><a class="btn sm" href="#/chat" data-newchat>${ic.compose}New chat</a></div>
      <div class="wsearch" style="padding:2px 6px 6px">${ic.search}<input class="input" id="cq" placeholder="Search chats" value="${esc(chatQuery)}"></div>
      <div id="citems">${chatListHtml()}</div>
    </aside>
    <div class="chatpane">
      <div class="chathead">
        <button class="icon-btn hist" id="histbtn" title="Chats">${ic.history}</button>
        <h1 class="grow wrap" id="ctitle" title="Tap to rename">${m ? "Tune: " + esc(m.title) : cur ? esc(cur.title) : "New chat"}</h1>
        <span id="chatchip" class="chip chatchip"></span>
        ${cur ? `<a class="icon-btn" href="#/live/${encodeURIComponent("chat:" + cur.id)}" title="What Hermes did in its last answer">${ic.pulse}</a>` : ""}
        <a class="icon-btn" href="#/chat" title="New chat" aria-label="New chat" data-newchat>${ic.compose}</a>
      </div>
      ${m ? `<div class="banner info" style="margin:0 0 10px">${ic.tune}<span class="grow small">Focus chat for <b>${esc(m.title)}</b>: say what to track more or less; it changes the mission.</span></div>` : ""}
      <div class="msgs" id="msgs">${(cur?.messages || []).length ? "" : `<div class="empty-chat"><div class="muted">This is Hermes, your assistant. It knows your notes, reports, wikis and missions; it researches the web, starts missions and e-mails you. Attach pictures or documents with the clip.</div><div class="suggest">${sugg.map((x) => `<button type="button">${esc(x)}</button>`).join("")}</div></div>`}</div>
      <form class="composer2" id="cf">
        <div class="pend" id="pend"></div>
        <div class="editing" id="editbar" hidden>Editing a message <button type="button" class="btn sm ghost" id="canceledit">Cancel</button></div>
        <textarea class="input" name="q" rows="1" placeholder="Message Hermes…" enterkeyhint="send"></textarea>
        <div class="crow">
          <label class="icon-btn" title="Attach pictures or documents" aria-label="Attach pictures or documents">${ic.clip}<input type="file" id="cfile" multiple hidden accept="image/*,.pdf,.docx,.xlsx,.csv,.txt,.md,.json,.html,.py,.js,.ts,.yaml,.yml,.log"></label>
          ${selectHtml()}
          <span class="grow"></span>
          <button class="btn primary sendbtn" type="submit" id="sendbtn" aria-label="Send">${ic.send}</button>
        </div>
      </form>
    </div>
  </div>`;
  mirrorChip();
  const box = $("#msgs");
  (cur?.messages || []).forEach((x, i) => box.insertAdjacentHTML("beforeend", bubble(x, i)));
  codeCopy(box);
  bindMsgActions();
  const f = $("#cf"), ta = f.q;
  ta.oninput = () => { ta.style.height = "auto"; ta.style.height = Math.min(180, ta.scrollHeight) + "px"; };
  ta.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer:coarse)").matches) { e.preventDefault(); f.requestSubmit(); } };
  $$(".suggest button").forEach((b) => (b.onclick = () => { ta.value = b.textContent; ta.focus(); if (!b.textContent.endsWith(" ")) f.requestSubmit(); }));
  $("#histbtn").onclick = () => $("#clist").classList.toggle("open");
  $("#pmodel").onchange = (e) => setPref("mc-model", e.target.value);
  $("#peffort").onchange = (e) => setPref("mc-effort", e.target.value);
  $("#cq").oninput = async (e) => { chatQuery = e.target.value.trim(); await loadChats(); refreshList(); };
  $("#ctitle").onclick = async () => {
    if (!cur?.id) return;
    const t = prompt("Rename chat", cur.title || "");
    if (t && t.trim()) { await api(`/api/chats/${cur.id}`, { method: "PATCH", body: JSON.stringify({ title: t.trim() }) }); cur.title = t.trim(); $("#ctitle").textContent = t.trim(); await loadChats(); refreshList(); }
  };
  $("#cfile").onchange = async (e) => {
    for (const file of e.target.files) {
      const chip = document.createElement("span"); chip.className = "pchip"; chip.innerHTML = `<span class="spin" style="width:12px;height:12px"></span> ${esc(file.name)}`;
      $("#pend").appendChild(chip);
      try {
        const r = await fetch("/api/chat/upload", { method: "POST", body: file, headers: { "X-Filename": file.name } }).then((x) => x.json());
        if (r.error) throw new Error(r.error);
        pending.push(r);
        chip.innerHTML = `${r.kind === "image" ? `<img src="/api/chat/files/${r.id}">` : ic.doc} <span class="wrap">${esc(r.name)}</span><button type="button" title="Remove">${ic.x}</button>`;
        chip.querySelector("button").onclick = () => { pending = pending.filter((p) => p.id !== r.id); chip.remove(); };
      } catch (err) { chip.remove(); toast(`${file.name}: ${err.message}`, true); }
    }
    e.target.value = "";
  };
  $("#canceledit").onclick = () => { editing = null; $("#editbar").hidden = true; ta.value = ""; };
  $$("[data-newchat]").forEach((a) => (a.onclick = (e) => {           // on #/chat already the link changes nothing: start afresh here
    if (location.hash !== "#/chat") return;
    e.preventDefault(); $("#clist").classList.remove("open"); render(true);
  }));
  bindChatList();
  f.onsubmit = (e) => {
    e.preventDefault();
    if (streaming) return stopChat();
    const q = ta.value.trim();
    if (!q && !pending.length) return;
    const trunc = editing;
    ta.value = ""; ta.style.height = ""; editing = null; $("#editbar").hidden = true;
    send(q, mis, trunc);
  };
  if (cur?.pending) follow(cur.id);
  const pre = route.q.get("prompt");                     // from a guide example or a share: typed in, not sent
  const shared = route.q.get("share") ? await api(`/api/share/${route.q.get("share")}`).catch(() => null) : null;
  for (const a of shared?.files || []) {                  // what the phone shared comes along as attachments
    pending.push(a);
    $("#pend").insertAdjacentHTML("beforeend", `<span class="pchip">${a.kind === "image" ? `<img src="/api/chat/files/${a.id}">` : ic.doc} <span class="wrap">${esc(a.name)}</span></span>`);
  }
  if ((pre || shared) && !cur) { ta.value = pre || ""; ta.oninput(); ta.focus(); history.replaceState(history.state, "", "#/chat" + (mslug ? `?mission=${encodeURIComponent(mslug)}` : "")); }
  if (route.q.get("send") && (pre || pending.length) && !cur) f.requestSubmit();
  scrollChat(true);
}

// ---------- the AI phone (images/phone): approvals, Stop, pairing, log ----------
let phoneTimer = null;
const PHONE_NOT_TAKEN = "The AI phone did not pick this up (its service may be restarting). It asks again if still needed.";
async function vPhone() {
  clearInterval(phoneTimer);
  const pre = route.q.get("do"), pid = route.q.get("id");             // a button in the Telegram message
  if (pre && pid) {
    history.replaceState(history.state, "", "#/phone");
    const r = await api("/api/phone/decide", { method: "POST", body: JSON.stringify({ id: pid, allow: pre !== "deny", minutes: pre === "allow5" ? 5 : 0 }) })
      .catch((e) => ({ error: e.message }));
    toast(r.error ? `Too late: ${r.error}` : !r.taken ? PHONE_NOT_TAKEN : pre === "deny" ? "Declined" : pre === "allow5" ? "Allowed, and for the next 5 minutes" : "Allowed: the AI phone is doing it", !!r.error || !r.taken);
    if (route.name !== "phone") return;
  }
  view.innerHTML = `<div class="hero"><div class="grow"><h1>AI phone</h1><p>Hermes' hands on your old phone. Every action waits for your OK here.</p></div>${liveLink("phone", "What it did")}</div><div id="ph"></div>`;
  let last = "";
  const draw = async () => {
    if (route.name !== "phone") return clearInterval(phoneTimer);
    const P = await api("/api/phone").catch(() => null);
    if (route.name !== "phone") return clearInterval(phoneTimer);
    const sig = JSON.stringify([P?.state?.connected, P?.state?.foreground, P?.state?.error, P?.stopped, P?.pending?.map((p) => p.id), P?.log?.[0]?.ts, P?.state?.trust_until > Date.now() / 1000, P?.state?.screen_held, Math.round((P?.state?.screen_until || 0) / 30), P?.state?.task?.until, P?.state?.task?.actions]);
    if (sig === last || typing()) return;
    last = sig;
    $("#ph").innerHTML = phoneHtml(P);
    bindPhone(P);
  };
  await draw();
  phoneTimer = setInterval(draw, 2000);
  document.onvisibilitychange = () => { if (!document.hidden && route.name === "phone") draw(); };   // a background tab is paused
}

function phoneHtml(P) {
  if (!P?.installed) return `<div class="card pad-l empty">The AI phone service is not running.</div>`;
  const st = P.state, trust = st.trust_until > Date.now() / 1000, forever = st.trust_until > Date.now() / 1000 + 365 * 86400;
  const status = P.stopped ? `<span class="pill failed">Stopped</span>` : st.connected ? `<span class="pill ok">Connected</span>` : `<span class="pill paused">Not connected</span>`;
  return `<div class="stack">
    ${!P.push_devices ? `<a class="banner" href="#/system">${ic.bell}<span class="grow">No device gets notifications, so approval requests only reach you on Telegram. Switch notifications on under <b>This device</b>.</span>${ic.next}</a>` : ""}
    <div class="card pad-l"><div class="row between wrap" style="gap:10px;align-items:center">
      <div><div class="row" style="gap:8px;align-items:center">${status}<b>${esc(st.model || "Phone")}</b>${st.android ? `<span class="small muted">Android ${esc(st.android)}</span>` : ""}</div>
        <div class="small muted" style="margin-top:4px">${st.connected ? `In front: <span class="mono">${esc(st.foreground || "home screen")}</span>` : esc(st.error || "")}${forever ? " · <b>actions allowed until you stop it</b>" : trust ? ` · <b>actions allowed until ${dt(st.trust_until)}</b>` : ""}</div></div>
      ${P.stopped ? `<button class="btn primary" id="phresume">${ic.play}Switch on</button>` : `<button class="btn danger" id="phstop">${ic.pause}Stop</button>`}
    </div>${st.connected && !P.stopped ? phoneScreenHtml(st) : ""}${trust ? `<button class="btn sm ghost" id="phuntrust" style="margin-top:10px">Ask me again for every action</button>`
      : st.connected && !P.stopped ? `<div class="row wrap" style="gap:8px;margin-top:10px;align-items:center"><span class="small"><b>Let it use the phone freely:</b></span>
        ${[[10, "10 min"], [60, "1 hour"], [480, "8 hours"], [-1, "Until I stop it"]].map(([m, l]) => `<button class="btn sm" data-trust="${m}">${l}</button>`).join("")}
        <input class="input" id="phmin" inputmode="numeric" placeholder="min" style="width:70px;padding:6px 8px"><button class="btn sm ghost" id="phcustom">Set</button></div>
        ${explain("freely-taps-swipes-openi", `Freely: taps, swipes, opening apps and typing run without asking. Still asking: spending money, and typing or a web address that holds an e-mail address, phone number, IBAN or key. Passwords are never typed, blocked apps stay blocked, Stop ends it.`, "What still asks")}` : ""}</div>
    ${phoneTaskHtml(st)}
    ${P.pending.map((p) => `<div class="card pad-l phreq${p.money ? " money" : ""}">
      <div class="tag">Waiting for your OK · ${esc(p.app || "")}</div><h2 style="margin:8px 0 4px">${esc(p.text)}</h2><div class="small">${esc(p.why || "")}</div>
      <div class="row wrap" style="gap:8px;margin-top:14px"><button class="btn primary" data-allow="${p.id}">${ic.check}Allow</button>${p.money ? "" : `<button class="btn" data-allow5="${p.id}">Allow 5 min</button>`}<button class="btn ghost" data-deny="${p.id}">${ic.x}Decline</button></div>
      ${p.shot ? `<img class="phshot" src="/api/phone/shot/${p.shot}" alt="The phone's screen now; a red circle marks a planned tap">` : ""}
    </div>`).join("")}
    ${!st.connected && !P.stopped ? `<div class="card pad-l"><h2>${st.paired ? "Reconnect" : "Pair the phone"}</h2>
      ${st.paired ? `<div class="small muted" style="margin-top:6px">Paired before. Make sure Wireless debugging is on, then:</div><button class="btn primary" id="phconnect" style="margin-top:10px">Connect</button>` : ""}
      <ol class="small" style="margin:10px 0 0 18px;line-height:1.6"><li>On the old phone: Settings → Developer options → <b>Wireless debugging</b> → <b>Pair device with pairing code</b>.</li>
        <li>Enter the 6-digit code and the port (the digits after the colon in “IP address &amp; Port” of that dialog).</li></ol>
      <form id="phpair" class="row wrap" style="gap:8px;margin-top:10px"><input class="input" name="code" inputmode="numeric" maxlength="6" placeholder="Code (6 digits)" style="width:150px"><input class="input" name="port" inputmode="numeric" maxlength="5" placeholder="Port" style="width:110px"><button class="btn primary">Pair</button></form></div>` : ""}
    ${st.connected && st.boot ? `<div class="card pad-l"><div class="row between wrap" style="gap:8px;align-items:center"><h2>Starts in AI mode after a restart</h2>
      ${Object.values(st.boot).every(Boolean) ? `<span class="pill ok">Ready</span>` : `<button class="btn sm primary" id="phboot">Set it up</button>`}</div>
      <ul class="phlog" style="margin-top:8px">${[["keepadb_allowed", "Wireless debugging switches itself on (KeepADB)"], ["tailscale_always_on", "Tailscale connects by itself (always-on VPN)"],
        ["no_battery_limit", "Android never stops Tailscale or KeepADB (no battery limit)"]].map(([k, l]) => `<li>${st.boot[k] ? "✓" : "○"} ${esc(l)}</li>`).join("")}</ul>
      ${Object.values(st.boot).every(Boolean) ? "" : `<div class="tiny muted" style="margin-top:6px">Each change asks for your Allow (here and on Telegram) before it runs.</div>`}</div>` : ""}
    <div class="card pad-l"><h2>What it did</h2>${P.log.length ? `<ul class="phlog">${P.log.map((e) => `<li><span class="tiny faint">${e.ts ? clock(e.ts) : ""}</span> <b>${esc(e.tool)}</b> ${esc(e.decision || e.result || "")}${e.why ? `<div class="tiny muted">${esc(e.why)}</div>` : ""}</li>`).join("")}</ul>` : `<div class="small muted" style="margin-top:6px">Nothing yet. Ask Hermes in chat, e.g. “On the AI phone, open Chrome and look up the weather”.</div>`}</div>
    <details class="card pad-l"><summary><b>Never touched</b> <span class="small muted">· ${P.blocklist.length} apps and words</span></summary><div class="small muted" style="margin-top:8px">Banking, investment, payment, password and settings apps: the AI phone never reads or touches them; if one comes up it goes to the home screen. Edit <span class="mono">/srv/ai/phone/blocklist.txt</span>.</div><div class="row wrap" style="gap:6px;margin-top:8px">${P.blocklist.map((b) => `<span class="tag">${esc(b)}</span>`).join("")}</div></details>
  </div>`;
}

// PHN-18: a task the owner allowed once: its apps, the texts it may type, until when, how many actions so far
function phoneTaskHtml(st) {
  const t = st.task;
  if (!t || t.until < Date.now() / 1000) return "";
  return `<div class="card pad-l"><div class="row between wrap" style="gap:4px 8px;align-items:center"><h2>Task allowed once</h2><button class="btn sm ghost" id="phendtask">End task</button></div>
    <div class="small" style="margin-top:6px"><b>${esc(t.task)}</b></div>
    <div class="small muted" style="margin-top:4px">In ${esc((t.apps || []).join(", "))} · types ${t.texts?.length ? esc(t.texts.join("; ")) : "nothing"} · until ${clock(t.until)} · ${nf(t.actions || 0)} action${t.actions === 1 ? "" : "s"} so far without asking</div></div>`;
}

// PHN-17: the screen is on while the agents work (and while an action waits for you), off when idle; watch on demand
function phoneScreenHtml(st) {
  const on = st.screen_held && st.screen_until > Date.now() / 1000;
  return `<div class="row wrap" style="gap:8px;margin-top:10px;align-items:center"><span class="small"><b>Screen:</b> ${on ? `on until ${clock(st.screen_until)} · ${esc(st.screen_why || "")}` : "off when idle (saves the battery)"}</span>
    <button class="btn sm" data-phscreen="10">${on ? "Keep on 10 min" : "Watch 10 min"}</button>${on ? `<button class="btn sm ghost" data-phscreen="0">Turn off now</button>` : ""}</div>`;
}

function bindPhone(P) {
  const ctl = async (body) => { const r = await api("/api/phone/control", { method: "POST", body: JSON.stringify(body) }).catch((e) => ({ error: e.message })); if (r.error) toast(r.error, true); return r; };
  // the tap shows at once on the card; it stays as "doing it" until the phone is done and the card goes away
  const decide = async (id, allow, minutes, btn) => {
    const row = btn.parentElement;
    row.innerHTML = `<span class="small"><span class="spin" style="width:12px;height:12px;vertical-align:-1px"></span> ${allow ? "Allowed. The AI phone is doing it…" : "Declining…"}</span>`;
    const r = await api("/api/phone/decide", { method: "POST", body: JSON.stringify({ id, allow, minutes }) }).catch((e) => ({ error: e.message }));
    if (r.error || !r.taken) row.innerHTML = `<span class="small err-t">${esc(r.error || PHONE_NOT_TAKEN)}</span>`;
    toast(r.error || (!r.taken ? PHONE_NOT_TAKEN : allow ? "Allowed: the AI phone is doing it" : "Declined"), !!r.error || !r.taken);
  };
  $("#phstop") && ($("#phstop").onclick = () => ctl({ do: "stop" }).then(() => toast("AI phone stopped")));
  $("#phresume") && ($("#phresume").onclick = () => ctl({ do: "resume" }).then(() => ctl({ do: "connect" })));
  $("#phconnect") && ($("#phconnect").onclick = (e) => { e.target.disabled = true; ctl({ do: "connect" }).then(() => toast("Connecting…")); });
  $("#phboot") && ($("#phboot").onclick = (e) => { e.target.disabled = true; ctl({ do: "boot_setup" }).then((r) => r.ok && toast("Asking for your OK on each setting…")); });
  $("#phuntrust") && ($("#phuntrust").onclick = () => ctl({ do: "trust", minutes: 0 }));
  $("#phendtask") && ($("#phendtask").onclick = () => ctl({ do: "end_task" }).then((r) => r.ok && toast("Task ended: every action asks again")));
  $$("[data-phscreen]").forEach((b) => (b.onclick = () => ctl({ do: "screen", minutes: +b.dataset.phscreen }).then((r) => r.ok && toast(+b.dataset.phscreen ? "The screen stays on for 10 minutes" : "The screen turns off"))));
  const trustFor = (m) => ctl({ do: "trust", minutes: m }).then((r) => r.ok && toast(m < 0 ? "Allowed until you stop it" : `Allowed for ${m} minutes`));
  $$("[data-trust]").forEach((b) => (b.onclick = () => trustFor(+b.dataset.trust)));
  $("#phcustom") && ($("#phcustom").onclick = () => { const m = parseInt($("#phmin").value, 10); if (m > 0) trustFor(m); else toast("Minutes, e.g. 30", true); });
  $$("[data-allow]").forEach((b) => (b.onclick = () => decide(b.dataset.allow, true, 0, b)));
  $$("[data-allow5]").forEach((b) => (b.onclick = () => decide(b.dataset.allow5, true, 5, b)));
  $$("[data-deny]").forEach((b) => (b.onclick = () => decide(b.dataset.deny, false, 0, b)));
  const f = $("#phpair");
  if (f) f.onsubmit = async (e) => { e.preventDefault(); const r = await ctl({ do: "pair", code: f.code.value.trim(), port: f.port.value.trim() }); if (r.ok) { toast("Pairing… this takes a few seconds"); f.code.value = ""; f.port.value = ""; } };
}

// ---------- House: Home Assistant on the NAS (ops/house.py): setup, rooms, Echos, the voice bridge ----------
function houseSteps(h) {
  const has = (d) => (h.integrations || []).some((x) => x.domain === d);
  const ha = h.url || "http://192.168.1.80:8123";
  return [
    { done: h.reachable, title: "Home Assistant runs on the NAS", sub: h.reachable ? ha : "not reachable from the PC: is the NAS on?" },
    { done: h.onboarded, title: "Create your Home Assistant account", sub: "once, on your home Wi-Fi: name, user, password, your location",
      btn: !h.onboarded && h.reachable ? `<a class="btn sm primary" href="${esc(ha)}" target="_blank" rel="noopener">Open Home Assistant</a>` : "" },
    { done: h.connected, title: "Connect it to the AI stack", sub: h.connected ? "the stack holds its own token (encrypted)" : "sign in to Home Assistant once more; it sends you back here",
      btn: h.onboarded && !h.connected ? `<a class="btn sm primary" href="/api/house/connect">Connect</a>` : "" },
    { done: has("alexa_devices"), title: "Sign in to Amazon (Alexa)", sub: has("alexa_devices") ? `${(h.echos || []).length} Echo${(h.echos || []).length === 1 ? "" : "s"} found` : "Amazon e-mail, password and the code from your authenticator app",
      btn: h.connected && !has("alexa_devices") ? `<a class="btn sm primary" href="${esc(ha)}/config/integrations/dashboard/add?domain=alexa_devices" target="_blank" rel="noopener">Add Alexa</a>` : "" },
    { done: has("tplink"), optional: true, title: "Tapo plugs (optional)", sub: has("tplink") ? "connected" : "Home Assistant usually finds them by itself; then sign in with your TP-Link account",
      btn: h.connected && !has("tplink") ? `<a class="btn sm" href="${esc(ha)}/config/integrations/dashboard/add?domain=tplink" target="_blank" rel="noopener">Add Tapo</a>` : "" },
  ];
}

// VOI-08: Hermes on the AI phone, as steps that tick themselves where the stack can see them (in Home Assistant)
const PLAY_HA = "https://play.google.com/store/apps/details?id=io.homeassistant.companion.android";
function phoneVoiceSteps(h, ha) {
  const link = (name, label) => { const m = ha?.menus.find((x) => x.name === name); return m ? `<a class="btn sm primary" href="${esc(toolUrl(ha, m))}" target="_blank" rel="noopener">${label}</a>` : ""; };
  const person = (h.people || []).find((n) => /ai.?phone/i.test(n)), app = (h.integrations || []).filter((x) => x.domain === "mobile_app");
  return [
    { done: (h.pipelines || []).includes("Hermes"), title: "Hermes' voice in Home Assistant", sub: "speech to text, Hermes and an English voice, set up by the stack" },
    { done: !!person, title: "Add a person “AI phone” in Home Assistant", sub: person ? `“${person}” can log in` : "Add person → name “AI phone” → switch on “Allow login” → a username and a password you choose → leave “Administrator” off → Create",
      btn: person ? "" : link("People", "Open People") },
    { done: app.length > 0, title: "Install the Home Assistant app on the AI phone", sub: app.length ? `signed in: ${app.map((x) => x.title).join(", ")}` : "On the S22: Install, open it, it finds Home Assistant on your Wi-Fi, sign in as “AI phone”",
      btn: app.length ? "" : `<a class="btn sm primary" href="${PLAY_HA}" target="_blank" rel="noopener">Open in Play Store</a>` },
    { done: !!(S.phone?.voice?.assistant && S.phone?.voice?.mic && S.phone?.voice?.awake), title: "Make it the phone's voice assistant",
      sub: S.phone?.voice?.assistant && S.phone?.voice?.mic && S.phone?.voice?.awake ? "the default assistant, with the microphone, listening also when locked"
        : "the stack sets it after your one Allow: the default assistant instead of Google's, the microphone, and no battery limit so it hears you when locked",
      btn: S.phone?.voice?.assistant && S.phone?.voice?.mic && S.phone?.voice?.awake ? "" : `<button class="btn sm primary" data-phvoice>Set it up</button>` },
    { manual: true, title: "Wake word on in the app", sub: "Hermes switches it on in Home Assistant's Assist settings (“Okay Nabu”)" },
    { manual: true, title: "Say “Okay Nabu”, then ask Hermes anything", sub: "the answer comes from the phone in English; the conversation is the Voice chat",
      btn: `<a class="btn sm" href="#/chat?c=voicechat">Open the Voice chat</a>` },
  ];
}

function phoneVoiceHtml(h, ha) {
  const steps = phoneVoiceSteps(h, ha), left = steps.filter((s) => !s.done && !s.manual).length;
  return `<div class="card pad-l"><div class="row between wrap" style="gap:4px 8px;align-items:center"><h2>Talk to Hermes on the AI phone</h2><span class="tiny faint">${left ? `${left} step${left > 1 ? "s" : ""} for you` : "ready to try"}</span></div>
    <ol class="hsteps">${steps.map((s) => `<li class="${s.done ? "done" : ""}"><span class="hs-ic">${s.done ? ic.check : s.manual ? "·" : ""}</span><div class="grow"><div class="ttl">${esc(s.title)}</div><div class="sub">${esc(s.sub)}</div></div>${s.btn || ""}</li>`).join("")}</ol>
    ${explain("you-type-the-password-yo", `You type the password yourself; the agents never open the Home Assistant app on the AI phone (its login reaches the house, the FRITZ!Box and the NAS).`, "About this")}</div>`;
}

function houseThingHtml(t) {
  const on = t.state === "on" || t.state === "open";
  const ctl = t.domain === "cover"
    ? `<button class="btn sm" data-hs="${esc(t.entity_id)}" data-op="open">Up</button><button class="btn sm" data-hs="${esc(t.entity_id)}" data-op="stop">Stop</button><button class="btn sm" data-hs="${esc(t.entity_id)}" data-op="close">Down</button>`
    : `<button class="btn sm ${on ? "primary" : ""}" data-hs="${esc(t.entity_id)}" data-op="${on ? "off" : "on"}"${t.state === "unavailable" ? " disabled" : ""}>${on ? "On" : "Off"}</button>`;
  const extra = [t.brightness != null && on ? `${t.brightness} %` : "", t.position != null ? `position ${t.position}` : "", t.power_w != null ? `${t.power_w} W` : "",
    t.state === "unavailable" ? "unavailable" : "", t.protected ? "protected: agents never switch it" : ""].filter(Boolean).join(" · ");
  return `<div class="hrow"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(t.name)}</div><div class="sub wrap">${esc(extra || t.domain)}</div></div><div class="row" style="gap:6px">${ctl}</div></div>`;
}

function houseHtml(h) {
  if (!h) return `<div class="card pad-l empty">The runner has not reported the House yet.</div>`;
  const steps = houseSteps(h), open = steps.filter((s) => !s.done && !s.optional);
  const rooms = {};
  for (const t of h.things || []) (rooms[t.area || "No room yet"] ||= []).push(t);
  const echos = h.echos || [], ha = toolOf("homeassistant");
  return `<div class="stack">
    ${h.error ? `<div class="banner warn">${ic.alert}<span class="small">${esc(h.error)}</span></div>` : ""}
    ${ha && h.reachable ? `<div class="card pad-l"><div class="row between wrap" style="gap:4px 8px;align-items:baseline"><h2>Home Assistant</h2><span class="tiny faint">home Wi-Fi · opens in a new tab</span></div>
      <div class="chips" style="margin-top:8px">${toolLinks(ha)}</div></div>` : ""}
    ${h.connected ? phoneVoiceHtml(h, ha) : ""}
    <div class="card pad-l"><div class="row between" style="align-items:center"><h2>${open.length ? "Set up" : "Set up · done"}</h2>${open.length ? `<span class="tiny faint">${steps.filter((s) => s.done).length} of ${steps.length}</span>` : ""}</div>
      <ol class="hsteps">${steps.map((s) => `<li class="${s.done ? "done" : ""}"><span class="hs-ic">${s.done ? ic.check : ""}</span><div class="grow"><div class="ttl">${esc(s.title)}</div><div class="sub">${esc(s.sub)}</div></div>${s.btn || ""}</li>`).join("")}</ol>
      ${!h.onboarded || !h.connected ? `<div class="tiny muted" style="margin-top:8px">Home Assistant is reached on your home Wi-Fi only (nothing is open to the internet). You type every password into Home Assistant yourself; the stack never sees one.</div>` : ""}</div>
    ${h.connected ? `<div class="card pad-l"><h2>Tell Alexa</h2><div class="small muted" style="margin-top:4px">For the lights and devices that live in the Alexa app: the command runs as if you said it to an Echo.</div>
      <form id="halexa" class="row wrap" style="gap:8px;margin-top:10px"><input class="input grow" name="cmd" placeholder="e.g. schalte das Licht im Wohnzimmer aus" style="min-width:200px">
        ${echos.length > 1 ? `<select class="input" name="echo" style="width:auto">${echos.map((e) => `<option value="${esc(e.id)}">${esc(e.name)}</option>`).join("")}</select>` : ""}
        <button class="btn primary"${echos.length ? "" : " disabled"}>${ic.send}Send</button></form>
      <div class="suggest" style="margin-top:10px">${["Alle Lichter aus", "Licht im Wohnzimmer an", "Gute Nacht"].map((x) => `<button class="btn sm" data-hcmd="${esc(x)}"${echos.length ? "" : " disabled"}>${esc(x)}</button>`).join("")}</div></div>` : ""}
    ${Object.keys(rooms).length ? Object.entries(rooms).map(([room, ts]) => `<div class="card pad-l"><h2>${esc(room)}</h2><div class="hlist">${ts.map(houseThingHtml).join("")}</div></div>`).join("")
      : h.connected ? `<div class="card pad-l small muted">No lights, plugs or shutters in Home Assistant yet. The ones in the Alexa app work through <b>Tell Alexa</b>; Tapo plugs show up here once they are added.</div>` : ""}
    ${h.connected ? `<div class="card pad-l"><div class="row between wrap" style="gap:8px;align-items:center"><h2>Talk to Hermes through an Echo</h2>
        <label class="row" style="gap:6px;align-items:center"><input type="checkbox" id="hvoice"${h.voice ? " checked" : ""}><span class="small">${h.voice ? "On" : "Off"}</span></label></div>
      <div class="small" style="margin-top:6px">Say <b>“Alexa, Hermes, …”</b> or <b>“Alexa, frag Hermes …”</b>. Alexa may first say it can't help (it doesn't know Hermes); then the same Echo speaks Hermes' answer, usually within 5-20 seconds. Only requests that start with “Hermes” are passed on; nothing else you say to Alexa is kept.</div>
      ${echos.length ? `<div class="hlist" style="margin-top:10px">${echos.map((e) => `<div class="hrow"><div class="grow"><div class="ttl">${esc(e.name)}</div><div class="sub">${esc([e.area, e.model].filter(Boolean).join(" · ") || "Echo")}</div></div><button class="btn sm" data-hsay="${esc(e.id)}">Test voice</button></div>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:8px">No Echo yet: sign in to Amazon (step 4).</div>`}</div>` : ""}
    <div class="card pad-l"><div class="row between" style="align-items:center"><h2>What happened</h2>${liveLink("house", "Run view")}</div>${(h.log || []).length ? `<ul class="phlog">${h.log.map((e) => `<li class="${e.ok ? "" : "err"}"><span class="tiny faint">${dt(e.ts)}</span> <b>${esc(e.what)}</b> ${esc(e.text)} <span class="tiny muted">· ${esc(e.by)}</span></li>`).join("")}</ul>`
      : `<div class="small muted" style="margin-top:6px">Nothing yet. Ask Hermes in chat, e.g. “Turn off all the lights” or “Say on the Echo that dinner is ready”.</div>`}</div>
  </div>`;
}

let houseSig = "";
function vHouse() {
  const err = route.q.get("err"), ok = route.q.get("connected");
  if (err || ok) { history.replaceState(history.state, "", "#/house"); toast(err || "Home Assistant is connected. The stack restarts briefly to load it.", !!err); }
  view.innerHTML = `<div class="hero"><div class="grow"><h1>House</h1><p>Your flat through Home Assistant on the NAS: lights, plugs, Echos. Hermes can switch them too; protected plugs only you.</p></div></div><div id="housebody"></div>`;
  houseSig = "";
  houseUpdate();
  if (!TOOLS) toolsLoad().then(() => { houseSig = ""; houseUpdate(); });   // Home Assistant's menus come from the tools list
}

function houseUpdate() {
  const box = $("#housebody");
  if (!box || typing()) return;
  const h = S?.house, sig = JSON.stringify([h || null, S?.phone?.voice]);     // the phone's voice step ticks from the phone
  if (sig === houseSig) return;
  houseSig = sig;
  box.innerHTML = houseHtml(h);
  bindHouse();
}

function bindHouse() {
  const pv = $("[data-phvoice]");
  if (pv) pv.onclick = async () => {
    pv.disabled = true;
    const r = await api("/api/phone/control", { method: "POST", body: JSON.stringify({ do: "voice_setup" }) }).catch((e) => ({ error: e.message }));
    toast(r.error || "One Allow: the card is on the AI phone page (and on Telegram)", !!r.error);
  };
  const call = async (body, okMsg) => {
    const r = await api("/api/house", { method: "POST", body: JSON.stringify(body) }).catch((e) => ({ ok: false, error: e.message }));
    if (r.ok === false) toast(r.error || "Error", true); else if (r.pending) toast("Sent; Home Assistant is slow to answer"); else toast(okMsg || r.done || "Done");
    return r;
  };
  $$("[data-hs]").forEach((b) => (b.onclick = () => { b.disabled = true; call({ do: "switch", entity: b.dataset.hs, op: b.dataset.op }); }));
  const f = $("#halexa");
  const send = (cmd) => cmd && call({ do: "alexa", command: cmd, echo: f?.echo?.value || "" });
  if (f) f.onsubmit = (e) => { e.preventDefault(); send(f.cmd.value.trim()); f.cmd.value = ""; };
  $$("[data-hcmd]").forEach((b) => (b.onclick = () => send(b.dataset.hcmd)));
  $$("[data-hsay]").forEach((b) => (b.onclick = () => call({ do: "say", echo: b.dataset.hsay, message: "Hello, this is Hermes. I can speak on this Echo." }, "Speaking…")));
  const v = $("#hvoice");
  if (v) v.onchange = () => call({ do: "settings", voice: v.checked }, v.checked ? "Echo bridge on" : "Echo bridge off");
}

// ---------- share: what the phone's Share menu sent (server.py share) ----------
async function vShare() {
  const s = await api(`/api/share/${route.args[0]}`).catch(() => null);
  if (route.name !== "share") return;
  if (!s || s.error) { view.innerHTML = emptyState("This shared item is gone (they are kept two weeks).", `<a class="btn sm" href="#/">${ic.home || ""}Go to Home</a>`, "card pad-l"); return; }
  const about = [s.title, s.url, s.text && s.text !== s.url ? s.text : ""].filter(Boolean).join("\n").slice(0, 4000);   // cap: prompt: what a new mission or chat starts from
  const ctx = about ? `\n\n${about}` : "";
  const ask = (q, send) => `#/chat?share=${s.id}&prompt=${encodeURIComponent(q + ctx)}${send ? "&send=1" : ""}`;
  const quick = [["Summarise this", "Summarise this for me: the key points and why it matters."],
    ["What should I do?", "What should I do with this? Suggest next steps, and say if a mission or a reminder would help."],
    ["Explain it simply", "Explain this simply, as to a smart friend outside the field."]];
  view.innerHTML = `<div class="stack">
    <div class="card pad-l">
      <div class="row wrap" style="gap:8px;align-items:center"><span class="tag">Shared ${rel(s.at)}</span><h1 class="grow wrap" style="margin:0">${esc(s.title || (s.url ? new URL(s.url).hostname : s.files[0]?.name || "Shared text"))}</h1></div>
      ${s.url ? `<a class="small mono wrap" style="display:block;margin-top:8px" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>` : ""}
      ${s.text && s.text !== s.url ? `<div class="small" style="margin-top:8px;white-space:pre-wrap;max-height:220px;overflow:auto">${esc(s.text)}</div>` : ""}
      ${s.files.length ? `<div class="pend" style="margin-top:10px">${s.files.map((a) => `<span class="pchip">${a.kind === "image" ? `<img src="/api/chat/files/${a.id}">` : ic.doc} <span class="wrap">${esc(a.name)}</span></span>`).join("")}</div>` : ""}
      ${s.errors.length ? `<div class="banner warn" style="margin-top:10px">${ic.alert}<span class="small">${s.errors.map(esc).join("<br>")}</span></div>` : ""}
    </div>
    <div class="card pad-l"><h2>One tap</h2><div class="suggest" style="margin-top:10px">${quick.map(([l, q]) => `<a class="btn" href="${ask(q, true)}">${esc(l)}</a>`).join("")}</div></div>
    <div class="card pad-l"><h2>Or</h2><div class="stack" style="margin-top:10px;gap:8px">
      <a class="btn" href="${ask("", false)}">${ic.chat}Ask Hermes about it…</a>
      <button class="btn" id="shsave">${ic.wiki}Save to my knowledge</button>
      <a class="btn" href="#/new?type=task&desc=${encodeURIComponent(about.slice(0, 1500) /* cap: api: a link carries at most this much */)}">${ic.rocket}Make it a mission</a>
    </div></div>
  </div>`;
  $("#shsave").onclick = async (e) => {
    e.target.disabled = true;
    const r = await api(`/api/share/${s.id}/save`, { method: "POST" }).catch((err) => ({ errors: [err.message] }));
    if (r.saved) toast(`Saved to your knowledge${r.of > 1 ? ` (${r.saved} of ${r.of})` : ""}; it is filed in a minute`);
    else { toast(r.errors?.[0] || "Nothing to save", true); e.target.disabled = false; }
  };
}

// Copy to the clipboard; true when it worked, otherwise it says why (a copy button never claims "Copied" for nothing)
async function copyText(text) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("this browser gives no clipboard access here");
    await navigator.clipboard.writeText(String(text ?? ""));
    return true;
  } catch (e) { toast("Could not copy: " + e.message, true); return false; }
}

function scrollChat(force) {
  const box = $("#msgs");
  if (box && (force || box.scrollHeight - box.scrollTop - box.clientHeight < 260)) box.scrollTop = box.scrollHeight;
}

function bindMsgActions() {
  $$("[data-copy]").forEach((b) => (b.onclick = async () => {
    const x = cur?.messages?.[+b.dataset.copy];
    if (x && (await copyText(x.content))) toast("Copied");
  }));
  $$("[data-edit]").forEach((b) => (b.onclick = () => {
    if (streaming) return;
    const i = +b.dataset.edit, x = cur?.messages?.[i];
    if (!x) return;
    editing = i; $("#editbar").hidden = false;
    const ta = $("#cf").q; ta.value = x.content === "(see attachment)" ? "" : x.content; ta.focus(); ta.oninput();
  }));
  $$("[data-retrynow]").forEach((b) => (b.onclick = async () => {   // AST-12: try the waiting message now
    b.disabled = true;
    const id = cur?.id, r = await api(`/api/chats/${id}/retry`, { method: "POST" }).catch((e) => ({ ok: false, error: e.message }));
    toast(r.ok ? "Trying now: the answer appears here within half a minute" : r.error, !r.ok);
    if (r.ok) setTimeout(() => { if (cur?.id === id && route.name === "chat") vChat(); }, 25000);
  }));
  $$("[data-regen]").forEach((b) => (b.onclick = () => {
    if (streaming) return;
    const i = +b.dataset.regen;
    let u = i - 1;
    while (u >= 0 && cur.messages[u].role !== "user") u--;
    if (u < 0) return;
    const x = cur.messages[u];
    pending = (x.attachments || []).map((a) => ({ ...a }));
    send(x.content === "(see attachment)" ? "" : x.content, cur.mission, u);
  }));
}

function setSending(on) {
  streaming = on;
  const b = $("#sendbtn");
  if (b) { b.innerHTML = on ? ic.pause : ic.send; b.classList.toggle("stopping", on); b.title = on ? "Stop" : "Send"; }
}

async function stopChat() {
  if (!cur?.id) return;
  await api(`/api/chats/${cur.id}/stop`, { method: "POST" }).catch(() => {});
  toast("Stopping…");
}

async function send(q, mis, truncate) {
  const box = $("#msgs");
  $(".empty-chat")?.remove();
  const atts = pending; pending = []; if ($("#pend")) $("#pend").innerHTML = "";
  if (typeof truncate === "number" && cur?.messages) {
    cur.messages = cur.messages.slice(0, truncate);
    box.innerHTML = ""; cur.messages.forEach((x, i) => box.insertAdjacentHTML("beforeend", bubble(x, i)));
  }
  const userMsg = { role: "user", content: q || "(see attachment)", attachments: atts };
  box.insertAdjacentHTML("beforeend", bubble(userMsg, (cur?.messages || []).length));
  scrollChat(true);
  setSending(true);
  try {
    const r = await api("/api/chat", { method: "POST", body: JSON.stringify({ chat: cur?.id, mission: mis, message: q, truncate,
      model: $("#pmodel")?.value, effort: $("#peffort")?.value, attachments: atts.map((a) => ({ id: a.id })) }) });
    if (r.error) throw new Error(r.error);
    if (!cur?.id) { cur = { id: r.chat, title: r.title, messages: [] }; history.replaceState(history.state, "", `#/chat?c=${r.chat}`); route.q = new URLSearchParams(`c=${r.chat}`); $("#ctitle").textContent = r.title; }
    cur.messages = [...(cur.messages || []), userMsg];
    follow(r.chat);
    loadChats().then(refreshList);
  } catch (e) {
    box.insertAdjacentHTML("beforeend", `<div class="mrow assistant"><div class="msg assistant"><div class="md">⚠ Could not send (${esc(e.message)}). Try again.</div></div></div>`);
    setSending(false);
  }
}

function follow(cid) {
  follower?.close();
  const box = $("#msgs");
  if (!box) return;
  $("#curmsg")?.remove();
  box.insertAdjacentHTML("beforeend", `<div class="mrow assistant" id="curmsg"><div class="msg assistant"><div class="typing"><span></span><span></span><span></span></div><div class="tiny faint" style="margin-top:6px">Working on it. You can close the app; the answer is saved here.</div></div></div>`);
  scrollChat(true);
  setSending(true);
  const es = (follower = new EventSource(`/api/chats/${cid}/stream`));
  es.onmessage = (e) => {
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    const c = $("#curmsg .msg");
    if (c && (d.text || d.tools?.length || d.reasoning)) c.innerHTML = `${toolsHtml(d.tools, !d.done)}${reasoningHtml(d.reasoning, !d.done && !d.text)}<div class="md">${d.text ? md(d.text) : '<div class="typing"><span></span><span></span><span></span></div>'}</div>`;
    scrollChat();
    if (d.done) {
      es.close(); follower = null; setSending(false);
      api(`/api/chats/${cid}`).then((full) => {
        if (full?.messages && $("#msgs")) {
          cur = full; const b = $("#msgs"); b.innerHTML = "";
          full.messages.forEach((x, i) => b.insertAdjacentHTML("beforeend", bubble(x, i)));
          codeCopy(b); bindMsgActions(); scrollChat(true);
        }
      }).catch(() => {});
      loadChats().then(refreshList);
    }
  };
}

// ---------- wiki (Obsidian-style: pages, links, backlinks, graph) ----------
const FOLDER_COLORS = { entities: "#2dd4bf", concepts: "#a78bfa", projects: "#fbbf24", events: "#f472b6", sources: "#94a3b8", answers: "#60a5fa", howto: "#a3e635", comparisons: "#fb923c" };
const fcolor = (f) => FOLDER_COLORS[f] || "#8e97ab";
let wikiRoots = [], wikiMode = "pages", wikiLast = "";       // wikiMode: the open wiki's tab (Pages, Graph, About)

// the New wiki form (bindWikiAdmin): a topic and what it should cover
const wikiNewForm = () => `<form class="card pad-l wnew" id="wnew" hidden><h2>New wiki</h2>
    ${explain("a-research-agent-studies", `A research agent studies the topic in depth (several research steps, with sources) and builds a linked wiki from what it finds. You can chat with Hermes about it afterwards, and run the agent again to deepen it.`, "About this")}
    <input class="input" name="topic" maxlength="70" required placeholder="Topic, e.g. Home battery storage" style="margin-top:10px">
    <textarea class="input" name="cover" rows="3" maxlength="1500" placeholder="What should it cover? (optional) e.g. technologies, prices in Germany, best brands, pitfalls" style="margin-top:8px"></textarea>
    <div class="row wrap" style="gap:8px;margin-top:10px"><button class="btn primary" type="submit">${ic.search}Research and build the wiki</button><button class="btn ghost" type="button" id="wnewx">Cancel</button></div></form>`;

// the Wiki tab: every wiki (the vault's and each agent's), each opening as pages and a graph
function wikiIndex() {
  const live = wikiRoots.filter((r) => !r.archived), old = wikiRoots.filter((r) => r.archived);
  const pages = live.reduce((n, r) => n + (r.pages || 0), 0);
  const row = (r) => `<a href="#/wiki?root=${encodeURIComponent(r.root)}"><div class="ic">${r.mission ? ic.target : ic.brain}</div><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(r.title)}</div>
    <div class="sub wrap">${r.pages} pages · ${r.links} links${r.mission ? "" : " · your vault"}${r.archived ? " · its mission is archived" : ""}</div><div class="sub wrap wuse" data-wuse="${esc(r.root)}"></div></div>${ic.next}</a>`;
  view.innerHTML = `<div class="hero heading" style="margin-bottom:12px"><div class="row between" style="gap:10px"><h1>Wiki</h1>
    <button class="btn sm" id="wnewb">${ic.plus}New wiki</button></div><p>${live.length} wikis · ${pages} pages: what your agents learned, each as linked pages and a graph.</p></div>
  ${wikiNewForm()}
  <div class="card pad-l wmap"><div class="section-h" style="margin:0"><h2>How they connect</h2><span class="tiny faint">bubble = a wiki, tap to open · line = subjects both have</span></div>
    <div id="wmapsvg" class="wmapsvg"><div class="skeleton" style="height:260px"></div></div><div id="wmapinfo" class="small"></div></div>
  <div class="card list wikis section">${live.map(row).join("") || `<div class="pad small muted">No wiki yet. New wiki starts one; every agent's results build its own.</div>`}</div>
  ${old.length ? `<details class="section"><summary class="small muted">${old.length} wiki${old.length > 1 ? "s" : ""} of archived missions (kept, not on the map)</summary><div class="card list wikis" style="margin-top:8px">${old.map(row).join("")}</div></details>` : ""}`;
  bindWikiAdmin("", {});
  wikiMap();
}

// MEM-09, MEM-10: the top layer of the wikis (bubbles sized by pages, lines for shared subjects) and who reads and
// writes each (the run record, 7 days); tap a bubble or a line for the whole story
const wikiAgentName = (a) => (a.startsWith("mission:") ? (S?.missions || []).find((m) => m.slug === a.slice(8))?.title || a.slice(8) : swName(a));
const wikiShort = (t) => String(t).split(/:| \(/)[0].trim();   // cap: preview: the bubble's label; its card and the list name it whole
// Where each bubble's name goes (FND-61): below it, else above, right or left, whichever covers no other name or bubble
// and stays in the box; the biggest wiki chooses first. Returns {x, y, anchor} relative to the bubble's centre.
function wikiMapLabels(nodes, rad, W, H, label, cw = 6.4) {
  const placed = [], out = new Map();
  const hit = (a, b) => a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];
  const over = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  for (const n of [...nodes].sort((a, b) => (b.pages || 0) - (a.pages || 0))) {
    const r = rad(n), w = label(n).length * cw;
    const spots = [{ x: 0, y: r + 13, anchor: "middle" }, { x: 0, y: -r - 5, anchor: "middle" }, { x: r + 4, y: 4, anchor: "start" }, { x: -r - 4, y: 4, anchor: "end" }]
      .map((s) => { const x0 = n.x + s.x - (s.anchor === "middle" ? w / 2 : s.anchor === "end" ? w : 0); return { ...s, box: [x0, n.y + s.y - 11, x0 + w, n.y + s.y + 3] }; });
    const bubbles = nodes.filter((o) => o !== n).map((o) => [o.x - rad(o), o.y - rad(o), o.x + rad(o), o.y + rad(o)]);
    const cost = (s) => (s.box[0] < 0 || s.box[2] > W || s.box[1] < 0 || s.box[3] > H ? 1e6 : 0)
      + [...placed, ...bubbles].reduce((c, b) => c + over(s.box, b), 0);
    const best = spots.find((s) => cost(s) === 0) || spots.reduce((a, b) => (cost(b) < cost(a) ? b : a));
    placed.push(best.box);
    out.set(n, { x: best.x, y: best.y, anchor: best.anchor });
    if (cost(best)) out.clashes = (out.clashes || 0) + 1;
  }
  return out;
}
async function wikiMap() {
  const [map, acc] = await Promise.all([api("/api/wiki/map").catch(() => null), api("/api/wiki/access?hours=168").catch(() => [])]);
  const box = $("#wmapsvg");
  if (!box || !map) { if (box) box.innerHTML = `<div class="small muted">The map is not available right now.</div>`; return; }
  const byRoot = {};
  for (const x of acc || []) (byRoot[x.root] ??= []).push(x);
  for (const n of map.nodes) {
    const el = $(`[data-wuse="${CSS.escape(n.root)}"]`), use = byRoot[n.root] || [];
    const readers = use.filter((x) => x.reads).map((x) => `${n.mission && x.agent === "mission:" + n.mission ? "its agent" : wikiAgentName(x.agent)} (${x.reads})`);
    if (el) el.textContent = `${readers.length ? `read in the last 7 days by ${readers.join(", ")}` : "not read by an agent in the last 7 days"} · written by ${n.mission ? "its agent" : "the curator"}${n.changed_7d ? `, ${n.changed_7d} page${n.changed_7d > 1 ? "s" : ""} changed this week` : ""}`;
  }
  const W = box.clientWidth || 340;
  let H = Math.max(260, Math.min(380, W * 0.8));
  const col = (n) => (n.root === "wiki" ? "#a78bfa" : n.root.startsWith("topics/") ? "#2dd4bf" : "#fbbf24");
  const rad = (n) => 12 + 4 * Math.sqrt(n.pages || 0);
  const nodes = map.nodes.map((n) => ({ ...n, id: n.root })), links = map.edges.map((e) => ({ source: e.a, target: e.b, subjects: e.subjects }));
  let at;
  for (;;) {                                                   // taller, 60 px at a time, until every name has a free place
    const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance(110).strength(0.25))
      .force("charge", d3.forceManyBody().strength(-260)).force("x", d3.forceX(W / 2).strength(0.07)).force("y", d3.forceY(H / 2).strength(0.1))
      .force("collide", d3.forceCollide((d) => Math.max(rad(d) + 34, wikiShort(d.title).length * 3.2 + 8))).stop();
    for (let i = 0; i < 300; i++) sim.tick();
    for (const n of nodes) {                                   // inside the box with its whole label
      const half = Math.max(rad(n), wikiShort(n.title).length * 3.2) + 4;
      n.x = Math.max(half, Math.min(W - half, n.x)); n.y = Math.max(rad(n) + 4, Math.min(H - rad(n) - 18, n.y));
    }
    at = wikiMapLabels(nodes, rad, W, H, (d) => wikiShort(d.title));
    if (!at.clashes || H >= 520) break;                         // at most 520 px tall: still one screen on a phone
    H += 60;
  }
  const top = Math.min(...nodes.map((n) => n.y + Math.min(-rad(n), at.get(n).y - 12))) - 6;     // no empty band above or below
  H = Math.max(...nodes.map((n) => n.y + Math.max(rad(n), at.get(n).y + 4))) + 6 - top;
  for (const n of nodes) n.y -= top;
  box.innerHTML = "";
  const svg = d3.select(box).append("svg").attr("viewBox", [0, 0, W, H]).attr("class", "graph");
  svg.append("g").selectAll("line").data(links).join("line").attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y)
    .attr("stroke", "var(--border-2)").attr("stroke-width", (d) => 1.5 + Math.min(6, d.subjects.length)).style("cursor", "pointer")
    .on("click", (_, d) => info(`<b>${esc(d.source.title)}</b> and <b>${esc(d.target.title)}</b> share ${d.subjects.length} subject${d.subjects.length > 1 ? "s" : ""}: ${d.subjects.map(esc).join(", ")}`));
  const g = svg.append("g").selectAll("g").data(nodes).join("g").attr("transform", (d) => `translate(${d.x},${d.y})`).style("cursor", "pointer")
    .on("click", (_, d) => (location.hash = `#/wiki?root=${encodeURIComponent(d.root)}`));      // a bubble is the wiki: tap and you are in
  g.append("title").text((d) => `${d.title}: ${d.pages} pages`);
  g.append("circle").attr("r", rad).attr("fill", (d) => col(d)).attr("fill-opacity", 0.25).attr("stroke", (d) => col(d)).attr("stroke-width", 2);
  g.append("text").attr("text-anchor", "middle").attr("dy", "0.35em").attr("class", "wmapn").text((d) => d.pages);
  g.append("text").attr("text-anchor", (d) => at.get(d).anchor).attr("x", (d) => at.get(d).x).attr("y", (d) => at.get(d).y).attr("class", "wmapl").text((d) => wikiShort(d.title));
  const info = (h) => ($("#wmapinfo").innerHTML = `<div class="wmapcard">${h}</div>`);
  info(`<span class="muted">${map.shared.length ? `${map.shared.length} subject${map.shared.length > 1 ? "s are" : " is"} in two or more wikis. Tap a bubble to open its wiki, a line for the subjects both have.` : "No subject is in two wikis yet. Tap a bubble to open its wiki."}</span>`);
}
// a summary's first sentence, marked when more follows (the whole summary heads the wiki's page)  cap: preview
const firstSentence = (s) => { const m = /^(.+?[.!?])(\s|$)/s.exec(String(s || "").trim()); return m && m[1].length < String(s).trim().length ? m[1] + " …" : String(s || "").trim(); };

let wikiBack = "";                                       // where the wiki was opened from (an agent page and its tab)
async function vWiki() {
  const bk = route.q.get("back");
  if (bk && /^#\/[\w\/%?=&.:-]*$/.test(bk)) wikiBack = bk;
  if (!wikiRoots.length) wikiRoots = await api("/api/wiki/roots").catch(() => []);
  if (route.name !== "wiki") return;                                            // FND-95: you left while it loaded
  if (!route.q.get("root")) return wikiIndex();                     // the tab opens on every wiki, not on one picked for you
  const root = route.q.get("root"), pageId = route.q.get("page");
  if (root !== wikiLast) { wikiMode = "pages"; wikiLast = root; }    // another wiki opens on its pages
  const info = wikiRoots.find((r) => r.root === root) || { title: root };
  const graph = await api(`/api/wiki/graph?root=${encodeURIComponent(root)}`).catch(() => ({ nodes: [], links: [] }));
  if (route.name !== "wiki" || route.q.get("root") !== root) return;
  const home = `#/wiki?root=${encodeURIComponent(root)}`;
  if (pageId) {                                                      // a page gets the whole screen, one step back to its wiki
    view.innerHTML = `<a class="back" href="${home}">${ic.back}${esc(info.title)}</a><div id="wbody"></div>`;
    return wikiPage($("#wbody"), root, pageId, graph);
  }
  // a wiki: its name, search, then its pages to tap (Graph and About one tap away)
  const byFolder = {};
  graph.nodes.forEach((n) => (byFolder[n.folder || "pages"] ??= []).push(n));
  Object.values(byFolder).forEach((l) => l.sort((a, b) => a.title.localeCompare(b.title)));
  const mode = ["pages", "graph", "about"].includes(wikiMode) ? wikiMode : "pages";
  const back = wikiBack ? (S?.missions || []).find((x) => wikiBack.startsWith(`#/mission/${encodeURIComponent(x.slug)}`))?.title || "Back" : "";
  const owner = info.mission ? `#/mission/${encodeURIComponent(info.mission)}` : "";
  view.innerHTML = `<a class="back" href="${back ? esc(wikiBack) : "#/wiki"}">${ic.back}${back ? esc(back) : "All wikis"}</a>
  <div class="hero heading" style="margin-bottom:14px"><h1 class="wh1">${esc(info.title)}</h1>
    <p>${graph.nodes.length} pages · ${graph.links.length} links${owner ? ` · <a class="wl" href="${owner}">its agent</a>` : info.task ? ` · <a class="wl" href="#/task/${info.task}">its task</a>` : " · your vault"}</p></div>
  <div class="row wrap wacts"><button class="btn sm primary" id="wrefb">${ic.tune}Improve this wiki</button>${owner ? `<a class="btn sm" href="${owner}">${ic.target}Its agent</a>` : ""}${info.mission ? `<button class="btn sm ghost danger" id="wdel">${ic.trash}Delete wiki</button>` : ""}</div>
  ${refineForm("wiki")}
  <div class="wsearch card">${ic.search}<input class="input" id="wq" type="search" placeholder="Search this wiki"></div>
  <div class="seg wseg">${[["pages", "Pages"], ["graph", "Graph"], ["about", "About"]].map(([k, l]) => `<button data-wm="${k}" class="${mode === k ? "on" : ""}">${l}</button>`).join("")}</div>
  <div id="wbody"></div>`;
  const body = $("#wbody"), link = (id) => `${home}&page=${encodeURIComponent(id)}`;
  const row = (n, sub) => `<a href="${link(n.id)}"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(n.title)}</div>${sub ? `<div class="sub wrap">${sub}</div>` : ""}</div>${ic.next}</a>`;
  const pages = () => Object.entries(byFolder).map(([f, l]) => `<div class="wfold"><span class="fdot" style="background:${fcolor(f)}"></span>${esc(f)} <span class="faint">${l.length}</span></div>
    <div class="card list">${l.map((n) => row(n, n.summary ? esc(firstSentence(n.summary)) : "")).join("")}</div>`).join("")
    || `<div class="card pad small muted">This wiki is empty. It fills up with every result of its agent.</div>`;
  const about = () => `<div class="card pad-l"><h2>About this wiki</h2>
    <p class="small" style="margin:8px 0 0">${info.summary ? esc(info.summary) : `<span class="muted">No summary yet: it is written within half an hour.</span>`}</p>
    <div class="tiny faint" style="margin-top:10px">${owner ? "Its agent adds to it with every result; Improve this wiki asks for a correction or more research now. Delete wiki removes its pages (the vault's history keeps them) and its agent stops writing one."
      : "Built from the notes and clippings in your vault by the curator, so it can't be deleted here: change or delete the notes instead. Improve this wiki still corrects or extends its pages."}</div></div>`;
  const show = () => {
    if (mode === "graph") drawGraph(body, graph, root, null);
    else body.innerHTML = mode === "about" ? about() : pages();
    bindWikiAdmin(root, info);
  };
  $$("[data-wm]").forEach((b) => (b.onclick = () => { wikiMode = b.dataset.wm; render(true); }));
  bindRefine(root, "");
  show();
  const q = $("#wq");
  q.oninput = async () => {
    const v = q.value.trim();
    if (v.length < 2) return show();
    const hits = await api(`/api/wiki/search?root=${encodeURIComponent(root)}&q=${encodeURIComponent(v)}`).catch(() => []);
    if (q.value.trim() !== v) return;                                // a newer search is on its way
    body.innerHTML = `<div class="wfold">${hits.length} found</div><div class="card list">${hits.map((h) => row(h, `…${esc(h.snippet)}…`)).join("") || `<div class="pad small muted">Nothing found.</div>`}</div>`;
  };
}

// TSK-34: improve a wiki or one page: what is wrong or what to find out becomes a task; research agents look into it,
// then the wiki's writer corrects and extends the pages (an old fact stays, marked superseded)
const REFINE = { wiki: ["Check its facts and fix the mistakes", "Research what is missing", "Bring it up to date"],
  page: ["Check its facts and fix the mistakes", "Research more about this", "Bring it up to date"] };
const refineForm = (scope) => `<form class="card pad-l wref" id="wref" hidden><h2>${scope === "page" ? "Correct or research this page" : "Improve this wiki"}</h2>
    ${explain("say-what-is-wrong-or-wha", `Say what is wrong or what to find out. It becomes a task: research agents look into it with sources, then the wiki's writer corrects ${scope === "page" ? "this page" : "the pages"} (an old fact stays, marked superseded) and adds what is new. You follow it on Tasks.`, "About this")}
    <div class="chips" style="margin-top:10px">${REFINE[scope].map((x) => `<button type="button" class="tag" data-rq="${esc(x)}">${esc(x)}</button>`).join("")}</div>
    <textarea class="input" name="text" rows="3" maxlength="3000" required placeholder="${scope === "page" ? "e.g. The capacity figure is wrong: check the newest quarterly report" : "e.g. Add the Kazakh producers and check every price"}" style="margin-top:8px"></textarea>
    <div class="row wrap" style="gap:8px;margin-top:10px"><button class="btn primary" type="submit">${ic.rocket}Do it</button><button class="btn ghost" type="button" data-rx>Cancel</button></div></form>`;
function bindRefine(root, page) {
  const f = $("#wref"), b = $("#wrefb");
  if (!f || !b) return;
  b.onclick = () => { f.hidden = !f.hidden; if (!f.hidden) { f.scrollIntoView({ block: "nearest", behavior: "smooth" }); f.text.focus({ preventScroll: true }); } };
  $("[data-rx]", f).onclick = () => (f.hidden = true);
  $$("[data-rq]", f).forEach((x) => (x.onclick = () => { f.text.value = x.dataset.rq + (f.text.value.trim() ? ". " + f.text.value.trim() : ""); f.text.focus(); }));
  f.onsubmit = async (e) => {
    e.preventDefault();
    const sub = $("[type=submit]", f);
    sub.disabled = true;
    const r = await act({ action: "task_create", text: f.text.value.trim(), kind: "research", wiki: { root, page } }, (x) => `Task #${x.task} is being planned: its steps show on Tasks`);
    sub.disabled = false;
    if (!r) return;
    location.hash = `#/task/${r.task}`;
  };
}

// New wiki = a deep research task whose results compile into its wiki; delete = two taps (the vault keeps the history)
function bindWikiAdmin(root, info) {
  const f = $("#wnew");
  if (f) bindWikiNew(f);
  const d = $("#wdel");
  if (!d) return;
  d.onclick = async () => {
    if (!d.dataset.armed) {
      d.dataset.armed = "1"; d.innerHTML = `${ic.trash}Tap again to delete ${info.pages || 0} pages`;
      setTimeout(() => { if (d.isConnected) { delete d.dataset.armed; d.innerHTML = `${ic.trash}Delete wiki`; } }, 5000);
      return;
    }
    d.disabled = true;
    const r = await act({ action: "wiki_delete", root }, (x) => x.detail);
    if (!r) { d.disabled = false; return; }
    wikiRoots = [];
    location.hash = "#/wiki";
  };
}

function bindWikiNew(f) {
  $("#wnewb").onclick = () => { f.hidden = !f.hidden; if (!f.hidden) f.topic.focus(); };
  $("#wnewx").onclick = () => (f.hidden = true);
  if (route.q.get("new") && f.hidden) { f.hidden = false; f.topic.focus(); }
  f.onsubmit = async (e) => {
    e.preventDefault();
    const topic = f.topic.value.trim(), cover = f.cover.value.trim();
    if (topic.length < 3) return toast("Name the topic (3 characters or more)", true);
    f.querySelector("[type=submit]").disabled = true;
    const r = await act({ action: "create", type: "task", title: `Wiki: ${topic}`.slice(0, 80) /* cap: id: the topic is in its description */, depth: "deep", deliver: ["app"], schedule: "manual",
      description: `Research "${topic}" in depth and build a knowledge wiki about it: the key entities, concepts, projects and events, with dated facts and sources.${cover ? ` Cover: ${cover}` : ""} Write a clear report of the findings; the wiki is compiled from it.` },
      (x) => (x.duplicate ? x.detail : "Research started: the wiki appears with its first result"));
    f.querySelector("[type=submit]").disabled = false;
    if (!r) return;
    wikiRoots = [];
    location.hash = `#/mission/${encodeURIComponent(r.slug)}`;
  };
}

async function wikiPage(el, root, id, graph) {
  el.innerHTML = `<div class="skeleton"></div>`;
  const p = await api(`/api/wiki/page?root=${encodeURIComponent(root)}&id=${encodeURIComponent(id)}`);
  if (p.error) { el.innerHTML = `<div class="card empty">${esc(p.error)}</div>`; return; }
  const meta = p.meta || {};
  const local = { nodes: graph.nodes.filter((n) => n.id === id || graph.links.some((l) => (l.source === id && l.target === n.id) || (l.target === id && l.source === n.id))), links: graph.links.filter((l) => l.source === id || l.target === id) };
  el.innerHTML = `${refineForm("page")}<div class="wpage">
    <article class="card pad-l md reader">
      <div class="chips" style="margin-bottom:10px">${p.type ? `<span class="tag"><span class="fdot" style="background:${fcolor(id.split("/")[0])}"></span>${esc(p.type)}</span>` : ""}${meta.last_validated ? `<span class="tag">updated ${esc(meta.last_validated)}</span>` : ""}${meta.trust ? `<span class="tag">${esc(meta.trust)}</span>` : ""}${(meta.sources || []).length ? `<span class="tag">${meta.sources.length} source${meta.sources.length > 1 ? "s" : ""}</span>` : ""}</div>
      <div class="row wrap wtitle"><h1>${esc(p.title)}</h1><button type="button" class="btn sm primary" id="wrefb">${ic.tune}Correct or research</button><button type="button" class="btn sm" data-copy-markdown>${ic.doc}Copy markdown</button></div>
      ${md(p.body.replace(/^#\s+.*\n/, ""), { root, links: p.links })}
      ${(meta.sources || []).length ? `<h2>Sources</h2><ul>${meta.sources.slice(-12).reverse().map((s) => `<li><a class="wl" href="#/read?path=${encodeURIComponent(String(s).endsWith(".md") ? s : s + ".md")}">${esc(s)}</a></li>`).join("")}</ul>` : ""}
    </article>
    <aside class="stack">
      <div class="card pad"><h2>Linked mentions · ${p.backlinks.length}</h2><div class="stack" style="margin-top:10px">${p.backlinks.map((b) => `<a class="witem" href="#/wiki?root=${encodeURIComponent(root)}&page=${encodeURIComponent(b.id)}">${esc(b.title)}</a>`).join("") || `<div class="small muted">No page links here yet.</div>`}</div></div>
      <div class="card pad"><h2>Local graph</h2><div id="lgraph" class="lgraph"></div></div>
    </aside></div>`;
  const copy = $("[data-copy-markdown]", el);
  copy.onclick = async () => {
    copy.disabled = true;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(p.markdown);
      toast("Copied");
    } catch (e) { toast("Could not copy: " + e.message, true); }
    finally { copy.disabled = false; }
  };
  bindRefine(root, id);
  drawGraph($("#lgraph"), local, root, id, true);
}

// ---------- charts: one way to move, zoom and name the dots (every zoomable chart; the owner's review of 2026-10-30) ----------
// One finger or the mouse moves the view, two fingers (or ctrl + wheel, a trackpad pinch) zoom, the + − and fit buttons
// do both; a plain wheel scrolls the page. Every dot has a name: a name that would cover another gives way to the busier
// dot's and comes back as you zoom in, like the names on a map. (Before, one chart moved with one finger, another only
// with two, and dots carried no name until zoomed.)
const CHART_HINT = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches ? "Two fingers to move or zoom · tap a dot" : "Drag to move · Ctrl + wheel or + − to zoom · tap a dot";
function chartZoom(host, svg, root, { min = 0.2, max = 8, onZoom, fit } = {}) {
  svg.style("touch-action", "pan-y").style("cursor", "grab");          // one finger scrolls the page, as on any phone map
  const zoom = d3.zoom().scaleExtent([min, max])
    .filter((e) => (e.type === "wheel" ? e.ctrlKey || e.metaKey : e.type.startsWith("touch") ? e.touches.length > 1 : !e.button))
    .on("zoom", (e) => { root.attr("transform", e.transform); onZoom?.(e.transform); });
  svg.call(zoom).on("dblclick.zoom", null);
  if (getComputedStyle(host).position === "static") host.style.position = "relative";
  host.insertAdjacentHTML("beforeend", `<div class="chartbtns"><button type="button" data-z="in" aria-label="Zoom in">+</button><button type="button" data-z="out" aria-label="Zoom out">−</button><button type="button" data-z="fit" aria-label="Fit everything in">⤢</button></div>`);
  host.lastElementChild.onclick = (e) => {
    const z = e.target.closest("[data-z]")?.dataset.z;
    if (z === "fit") (fit ? fit(true) : svg.transition().duration(250).call(zoom.transform, d3.zoomIdentity));
    else if (z) svg.transition().duration(200).call(zoom.scaleBy, z === "in" ? 1.6 : 1 / 1.6);
  };
  return zoom;
}
// The transform that fits every point into a w x h box (at most `most` times bigger), `right` screen pixels kept free
// on the right for the names of the dots there
// `least`: never start smaller than this (a dense chart then opens at a readable size around its middle; drag for the rest)
function chartFit(pts, w, h, pad = 30, most = 1.5, right = 60, least = 0) {
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  const k = Math.max(least, Math.min((w - right) / (x1 - x0), h / (y1 - y0), most));
  return d3.zoomIdentity.translate((w - right) / 2 - k * (x0 + x1) / 2, h / 2 - k * (y0 + y1) / 2).scale(k);
}
// Show the names that fit at zoom k, busiest first; items: {x, y, r (data units) or rs (screen px), text, prio, el}.
// A name never covers another name, nor a dot that ranks as high as its own (an agent's name may cover a small idea's dot).
function placeLabels(items, k, px = 11) {
  const dots = items.map((it) => { const r = it.rs ? it.rs / k : it.r; return [it.x - r, it.y - r, it.x + r, it.y + r, it.prio, it]; });
  const names = [], h = (px + 3) / k, cw = (px * 0.58) / k;
  const hit = (b, x0, y0, x1, y1) => x0 < b[2] && x1 > b[0] && y0 < b[3] && y1 > b[1];
  for (const it of [...items].sort((a, b) => b.prio - a.prio)) {
    const r = it.rs ? it.rs / k : it.r, x0 = it.x + r + 3 / k, y0 = it.y - h / 2, x1 = x0 + it.text.length * cw, y1 = y0 + h;
    const free = !names.some((b) => hit(b, x0, y0, x1, y1)) && !dots.some((b) => b[5] !== it && b[4] >= it.prio && hit(b, x0, y0, x1, y1));
    if (free) names.push([x0, y0, x1, y1]);
    Object.assign(it.el.style, { display: free ? "" : "none", fontSize: `${px / k}px`, strokeWidth: `${3 / k}px` });
    it.el.setAttribute("x", r + 3 / k);
    it.el.setAttribute("y", (px * 0.36) / k);
  }
}

function drawGraph(el, g, root, focus, small = false, opts = {}) {
  if (!window.d3) { el.innerHTML = `<div class="card empty">Graph library not loaded.</div>`; return; }
  if (!g.nodes.length) { el.innerHTML = `<div class="card empty">${ic.wiki}<div>No pages yet.</div></div>`; return; }
  const W = el.clientWidth || 600, H = small ? 240 : Math.max(420, Math.min(window.innerHeight - 260, 720));
  el.innerHTML = small ? "" : `<div class="card graphcard"></div>`;
  const host = small ? el : $(".graphcard", el);
  const nodes = g.nodes.map((n) => ({ ...n })), links = g.links.map((l) => ({ ...l }));
  const svg = d3.select(host).append("svg").attr("viewBox", [0, 0, W, H]).attr("class", "graph");
  const zoomG = svg.append("g");
  const link = zoomG.append("g").attr("class", "glinks").selectAll("line").data(links).join("line");
  const node = zoomG.append("g").selectAll("g").data(nodes).join("g").attr("class", (d) => "gnode" + (d.id === focus ? " focus" : ""))
    .style("cursor", "pointer").on("click", (_, d) => { if (opts.click) return opts.click(d); location.hash = `#/wiki?root=${encodeURIComponent(root)}&page=${encodeURIComponent(d.id)}`; });
  const r = (d) => 4 + Math.min(Math.sqrt(d.degree || 0) * 2.6, opts.still ? 12 : 99) + (d.id === focus ? 3 : 0);
  node.append("circle").attr("r", r).attr("fill", (d) => (opts.color ? opts.color(d) : fcolor(d.folder)));
  node.append("title").text((d) => `${d.title}${d.summary ? "\n" + d.summary : ""}`);
  const lbl = zoomG.append("g").attr("class", "glabels").selectAll("g").data(nodes).join("g");      // names above every dot
  const text = lbl.append("text").text((d) => d.title).attr("class", "lbl");
  const items = nodes.map((d, i) => ({ get x() { return d.x; }, get y() { return d.y; }, r: r(d), text: String(d.title || ""), el: text.nodes()[i],
    prio: (d.id === focus ? 1e6 : 0) + (d.degree || 0) }));
  let k = 1;
  const place = () => placeLabels(items, k);
  const adj = new Set(links.map((l) => `${l.source}|${l.target}`));
  node.on("mouseenter", (_, d) => {
    node.classed("dim", (o) => o.id !== d.id && !adj.has(`${d.id}|${o.id}`) && !adj.has(`${o.id}|${d.id}`));
    link.classed("hot", (l) => l.source.id === d.id || l.target.id === d.id);
  }).on("mouseleave", () => { node.classed("dim", false); link.classed("hot", false); });
  const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance(small ? 50 : 70))
    .force("charge", d3.forceManyBody().strength(small ? -160 : -220)).force("center", d3.forceCenter(W / 2, H / 2))
    .force("collide", d3.forceCollide().radius((d) => r(d) + 6)).force("x", d3.forceX(W / 2).strength(0.04)).force("y", d3.forceY(H / 2).strength(0.06))
    .on("tick", () => {
      link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
      lbl.attr("transform", (d) => `translate(${d.x},${d.y})`);
    }).on("end", place);
  sim.stop(); for (let i = 0; i < 260; i++) sim.tick(); sim.on("tick")();     // lay out once, draw once: nothing drifts under a finger
  const fit = (animate) => { const t = chartFit(nodes, W, H, 30, small ? 1.2 : 1.5, small ? 30 : 60, small ? 0 : 0.55); (animate ? svg.transition().duration(250) : svg).call(zoom.transform, t); };
  const zoom = chartZoom(host, svg, zoomG, { onZoom: (t) => { k = t.k; place(); }, fit });
  fit(false);
  const legend = opts.legend || [...new Set(nodes.map((n) => n.folder || "pages"))].map((f) => [f, fcolor(f)]);
  if (!small) host.insertAdjacentHTML("beforeend", `<div class="legend">${legend.map(([f, col]) => `<span><span class="fdot" style="background:${col}"></span>${esc(f)}</span>`).join("")}<span class="faint">${CHART_HINT} ${opts.click ? "for its details" : "to open it"}</span></div>`);
}

// ---------- build: assignments for the sandboxed builder, review, tap-to-deploy ----------
const BSTEPS = [["queued", "Queued"], ["working", "Building"], ["review", "Review"], ["deploying", "Deploying"], ["deployed", "Live"]];
const BSTATUS = { waiting: "Waiting for ChatGPT", queued: "Queued", working: "Building", review: "Ready for review", approved: "Approved", deploying: "Deploying",
  deployed: "Deployed", merged: "Merged", rolled_back: "Rolled back", failed: "Failed", rejected: "Rejected", recheck: "Checks queued", checking: "Checking",
  planning: "Being planned", planned: "Waits for its dependencies", cancelled: "Cancelled", reverting: "Being reverted", reverted: "Reverted" };
const bcls = (s) => ({ deployed: "ok", merged: "ok", review: "running", working: "running", deploying: "running", approved: "running",
  queued: "queued", waiting: "paused", failed: "failed", rolled_back: "failed", rejected: "archived", planning: "running", planned: "queued", cancelled: "archived",
  reverting: "running", reverted: "archived" }[s] || "queued");

function stepper(st) {
  const idx = { queued: 0, waiting: 1, working: 1, review: 2, approved: 3, deploying: 3, deployed: 4, merged: 4 }[st] ?? -1;
  const bad = ["failed", "rolled_back", "rejected"].includes(st);
  return `<div class="stepper">${BSTEPS.map(([k, l], i) => `<div class="st ${i < idx || (i === idx && ["deployed", "merged"].includes(st)) ? "done" : i === idx ? (bad ? "bad" : "cur") : ""}"><span></span>${l}</div>`).join("")}</div>`;
}

// The stack's own improvement ideas: the swarm's Ledger (ops/swarm_client.publish -> S.swarm.board). Agents propose by
// identity key and refine instead of copying; open ideas are ranked by impact, confidence, recurrence and effort.
// the owner taps "Build it" (the idea becomes a builder assignment, review and tap-to-deploy still follow) or "Dismiss".
const IDEA_STATE = { active: ["run", "building"], checking: ["ok", "shipped, being checked"], done: ["ok", "proved"], declined: ["archived", "dismissed"],
  merged: ["archived", "merged"], gone: ["archived", "gone"], blocked: ["warn", "blocked"], snoozed: ["archived", "snoozed"] };
// ---------- ideas (the Ledger): the stack's own fixes (crew, self-review, doctor) in one list with the Coach's agent
// changes, under Agents → Ideas (swarm.js swIdeas). These are its parts. ----------
function stackIdeaCard(p, n) {
  return `<div class="prop card pad-l section" data-kind="stack">
        <div class="row" style="gap:8px;flex-wrap:wrap"><span class="tag">#${n + 1}</span><span class="tag kind">The stack</span><span class="tag">${esc(p.owner || "")}</span><span class="tag">${esc(p.effort || "small")}</span>${p.state === "ready" ? `<span class="tag">ready</span>` : ""}<span class="tiny faint">${p.created ? rel(new Date(p.created * 1000).toISOString()) : ""}</span><span class="tiny mono faint" title="priority: impact × confidence × recurrence ÷ effort" style="margin-left:auto">${nf(+p.priority, 2)}</span></div>
        <b class="ptitle">${esc(p.title)}</b>
        <div class="tiny faint psig">${ic.radar}${esc(p.signal || "")}${p.evidence > 1 ? ` · ${p.evidence} sightings` : ""}${p.merged_from ? ` · ${p.merged_from} duplicate${p.merged_from > 1 ? "s" : ""} merged in` : ""}${p.recurrence ? ` · came back ${p.recurrence}×` : ""}</div>
        <details class="pdesc"><summary class="small muted">What the builder will do</summary><div class="small" style="white-space:pre-wrap;margin-top:6px">${esc(p.body || "")}</div></details>
        <div class="row" style="justify-content:flex-end;gap:8px"><button class="btn sm ghost" data-pdismiss="${p.id}">${ic.x}Dismiss</button>${S.engines?.claude ? `<button class="btn sm" data-paccept="${p.id}" data-engine="claude" title="Build it with Claude Code">Claude</button>` : ""}<button class="btn sm primary" data-paccept="${p.id}">${ic.rocket}Build it</button></div>
      </div>`;
}
function stackDecidedRow(p) {
      const [cls, label] = IDEA_STATE[p.state] || ["archived", p.state], build = (p.refs || []).find((r) => r.system === "build");
      const prog = p.state === "checking" ? (S.swarm?.checks || {})[String(p.id)] : "";
      return `<div style="padding:7px 2px;flex-wrap:wrap"><span class="pill ${cls}" style="padding:1px 7px">${esc(label)}</span><div class="grow small">${esc(p.title)}${p.decision?.reason ? ` <span class="faint">· ${esc(p.decision.reason)}</span>` : ""}${prog ? `<div class="tiny faint">Checker: ${esc(prog)}</div>` : ""}</div>${build ? `<a class="tiny" href="#/build/${esc(build.ref)}">#${esc(build.ref)}</a>` : ""}
        ${p.state === "checking" ? `<div class="row" style="gap:6px;width:100%;justify-content:flex-end">${p.check?.type === "owner_confirms" ? `<button class="btn sm" data-sconfirm="${p.id}">It works</button>` : ""}<button class="btn sm ghost" data-sreopen="${p.id}">Still broken</button></div>` : ""}</div>`;
    }
function ideaRulesHtml() {
  const paused = S.swarm?.paused || [];
  return `<div class="card pad-l section"><h2>Rules</h2>
    ${(S.swarm?.autonomy || []).length ? `<div class="hsub" style="margin-top:8px">Autonomy</div>${explain("a-rule-lets-an-agent-sta", `A rule lets an agent start building an idea without your tap. The deploy always waits for your tap; you can stop any build. Off unless you switch it on.`, "About this")}
      <div class="list" style="margin-top:6px">${S.swarm.autonomy.map((r) => `<div style="padding:7px 2px"><div class="grow small">${esc(r.title)}</div><button class="btn sm ${r.on ? "" : "ghost"}" data-sauto="${esc(r.id)}" data-on="${r.on ? "0" : "1"}">${r.on ? "On · switch off" : "Off · switch on"}</button></div>`).join("")}</div>` : ""}
    <div class="row between wrap" style="margin-top:12px;gap:8px"><span class="tiny faint">${paused.length ? `Paused: ${paused.map((x) => (x === "*" ? "all agents" : esc(x))).join(", ")}` : "No agent is paused"}</span>
      <button class="btn sm ghost" data-swpause="*" data-on="${paused.includes("*") ? "0" : "1"}">${paused.includes("*") ? "Resume all agents" : "Pause all agents"}</button></div></div>`;
}
// what waits for a tap: the stack's open ideas and the agent changes that passed their experiment
const ideasWaiting = () => (S?.swarm?.board?.open || []).length
  + (S?.swarm?.changes || []).filter((a) => a.state === "ready" && a.experiment?.passed && a.experiment.version === a.version).length;

function bindSwarmIdeas() {
  $$("[data-sconfirm]").forEach((b) => (b.onclick = async () => { b.disabled = true; if (await act({ action: "swarm_confirm", id: +b.dataset.sconfirm }, "Thanks: the Checker marks it proved")) chrome(); }));
  $$("[data-sreopen]").forEach((b) => (b.onclick = async () => {
    const reason = prompt("What is still broken?", "");
    if (reason === null) return;
    b.disabled = true;
    if (await act({ action: "swarm_reopen", id: +b.dataset.sreopen, reason }, "Back on the list")) chrome();
  }));
  $$("[data-sauto]").forEach((b) => (b.onclick = async () => {
    const on = b.dataset.on === "1";
    if (on && !confirm("Switch this rule on? The agent may start such builds by itself; every deploy still waits for your tap.")) return;
    b.disabled = true;
    if (await act({ action: "swarm_autonomy", template: b.dataset.sauto, on }, on ? "Rule on: ideas it allows start by themselves" : "Rule off: its unfinished builds wait for you")) chrome();
  }));
}

function bindSwarmPause() {
  $$("[data-swpause]").forEach((b) => (b.onclick = async () => {
    const on = b.dataset.on === "1", who = b.dataset.swpause;
    if (on && !confirm(who === "*" ? "Pause every agent? None runs or writes until you resume." : `Pause ${who}? It does not run or write until you resume it.`)) return;
    b.disabled = true;
    if (await act({ action: "swarm_pause", agent: who, on }, on ? "Paused: it starts no new runs until you resume it" : "Resumed: it runs at its next time")) chrome(); else b.disabled = false;
  }));
}

function bindProposals() {
  bindSwarmPause();
  bindSwarmIdeas();
  const sc = $("#iscan");
  if (sc) sc.onclick = async () => { sc.disabled = true; if (await act({ action: "improve_scan" }, "Self-review started: proposals arrive in a minute or two")) chrome(); };
  $$("[data-paccept]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    const r = await act({ action: "proposal_accept", id: +b.dataset.paccept, engine: b.dataset.engine || "hermes" }, (x) => (x?.build ? `Build #${x.build} queued: follow it on its page` : ""));
    if (r?.build) { location.hash = `#/build/${r.build}`; } else b.disabled = false;
  }));
  $$("[data-pdismiss]").forEach((b) => (b.onclick = async () => {
    const reason = prompt("Why not? (optional: the agent that proposed it learns from your reason)", "");
    if (reason === null) return;
    b.disabled = true;
    await act({ action: "proposal_dismiss", id: +b.dataset.pdismiss, reason }, "Dismissed: the agent that proposed it learns from your reason");
  }));
}

// ---------- code tab: repositories (study, code graph, code map), the stack's proposals, builds ----------
const repoOf = (name) => (S.code?.repos || []).find((r) => r.name === name);

function repoActivity(name) {
  const bs = (S.builds || []).filter((b) => b.repo === name);
  return { review: bs.filter((b) => b.status === "review").length, busy: bs.filter((b) => ["queued", "working", "checking", "waiting", "deploying"].includes(b.status)).length };
}

function repoCard(r) {
  const g = r.graph, a = repoActivity(r.name);
  return `<a class="card repo fadein ${a.review ? "has-review" : ""}" href="#/repo/${encodeURIComponent(r.name)}">
    <div class="row between" style="align-items:flex-start;gap:10px"><div class="repo-ic">${ic.code}</div>
      <div class="row wrap" style="gap:6px;justify-content:flex-end">${a.review ? `<span class="pill failed" style="padding:2px 8px">${a.review} to review</span>` : ""}${a.busy ? `<span class="pill running" style="padding:2px 8px">${a.busy} building</span>` : ""}
      <span class="pill ${r.buildable ? "ok" : "archived"}" style="padding:2px 8px">${r.buildable ? "builder can change it" : "studied"}</span></div></div>
    <b class="repo-n">${esc(r.name)}</b>
    <div class="tiny muted wrap">${r.last ? `${esc(r.last.subject)} · ${rel(r.last.ts)}` : esc(r.source || "")}</div>
    <div class="repo-m tiny faint">
      <span>${ic.wiki}${g ? `${nf(g.nodes)} nodes` : "no graph yet"}</span>
      <span>${ic.layers}${r.codemap ? "code map" : "no code map"}</span>
      ${r.files ? `<span>${ic.doc}${nf(r.files)} files</span>` : ""}
    </div></a>`;
}

function forgejoCard() {
  if (S.code?.forgejo_token) return "";
  return `<details class="card pad-l fjcard" ${route.q.get("forgejo") ? "open" : ""}><summary><b>Connect Forgejo once</b> <span class="small muted">· 2 minutes · lets the stack create repositories, let the builder change studied ones, and open pull requests</span></summary>
    <ol class="small" style="margin:10px 0 0;padding-left:20px;line-height:1.75">
      <li>At home (Forgejo is on your NAS), open <a href="http://192.168.1.80:3000/user/settings/applications" target="_blank" rel="noopener"><b>Forgejo → Settings → Applications</b></a> and sign in if asked.</li>
      <li>Under <b>Generate new token</b>: name <code>mission-control</code>; permissions <b>repository: Read and write</b>, <b>user: Read</b>. Tap <b>Generate token</b> and copy the long code it shows (only shown once).
        <div class="tiny faint">Your existing token <i>ai-stack-status</i> can only read, and Forgejo can't add rights to a token later. This one replaces it for everything; you can delete the old one afterwards.</div></li>
      <li>Paste it here: <div class="row wrap" style="gap:8px;margin-top:6px"><input class="input" id="fjtok" type="password" autocomplete="off" spellcheck="false" placeholder="paste the token" style="flex:1;min-width:200px"><button class="btn primary" id="fjgo">${ic.check}Connect</button></div>
        <div class="tiny faint" style="margin-top:4px">The runner checks it with Forgejo, stores it encrypted with your other secrets and restarts itself. It never goes to Hermes or any AI.</div></li>
    </ol></details>`;
}

function claudeCard() {
  if (S.engines?.claude) return "";
  return `<details class="card pad-l fjcard"><summary><b>Connect Claude Code once</b> <span class="small muted">a second builder engine, on your Claude subscription</span></summary>
    <ol class="small" style="margin:10px 0 0;padding-left:20px;line-height:1.7">
      <li>In Windows PowerShell: <code>wsl -d Ubuntu-24.04 -u owner --cd /home/owner/ai-stack make claude-connect</code></li>
      <li>Open the link it shows, sign in to Claude, paste the code back.</li>
      <li>Paste the token it then prints (starts with <code>sk-ant-oat</code>) when it asks. It stays hidden and is saved encrypted.</li>
      <li>That's it: this card disappears, and <b>Claude Code</b> becomes an engine choice for builds.</li>
    </ol>
    ${explain("claude-builds-run-in-the", `Claude builds run in the same sandbox, with the same checks, review and tap-to-deploy. That repository's code is sent to Anthropic for those builds; usage counts against your Claude plan.`, "About this")}</details>`;
}

function vBuild() {
  const id = route.args[0];
  if (id) return vBuildOne(+id);
  const bs = S.builds || [], repos = S.code?.repos || [], buildable = repos.filter((r) => r.buildable).map((r) => r.name);
  const pre = route.q.get("repo") || "ai-stack";
  const review = bs.filter((b) => b.status === "review");
  const busy = bs.filter((b) => ["queued", "working", "checking", "waiting", "deploying", "failed"].includes(b.status));
  const done = bs.filter((b) => !review.includes(b) && !busy.includes(b));
  const props = (S.swarm?.board?.open || []).length;
  view.innerHTML = `
  <div class="hero"><div class="grow"><h1>Code</h1><p>Your repositories and the builder that changes them. Nothing reaches production without your tap.</p></div></div>
  <div class="row wrap" style="gap:8px;margin-bottom:14px"><button class="btn" id="addbtn">${ic.plus}Add repository</button><button class="btn primary" id="newbtn">${ic.rocket}New build</button></div>
  <div class="card repo addrepo" id="addrepo" ${route.q.get("add") ? "" : "hidden"} style="margin-bottom:14px">
      <div class="row between"><b class="repo-n" style="margin:0">Add a repository</b><button class="icon-btn" id="addclose" title="Close">${ic.x}</button></div>
      <div class="seg sm" style="margin-top:8px"><button type="button" data-ar="study" class="on">Study GitHub repo</button><button type="button" data-ar="new">New repo</button></div>
      <div id="ar-study"><input class="input" id="ar-url" placeholder="https://github.com/owner/name" style="margin-top:8px"><button class="btn sm primary" id="ar-go" style="margin-top:8px">${ic.search}Study it</button>
        <div class="tiny faint" style="margin-top:6px">Clones it, builds its code graph and code map (minutes). The code is never run.</div></div>
      <div id="ar-new" hidden><input class="input" id="ar-name" placeholder="name (lowercase)" style="margin-top:8px"><input class="input" id="ar-desc" placeholder="What is it for? (optional)" style="margin-top:6px">
        <button class="btn sm primary" id="ar-create" style="margin-top:8px" ${S.code?.forgejo_token ? "" : "disabled"}>${ic.plus}Create on Forgejo</button>
        ${S.code?.forgejo_token ? "" : `<div class="tiny faint" style="margin-top:6px">Needs the Forgejo connection (below, one time).</div>`}</div>
      <div class="tiny faint" style="margin-top:8px">Or in Chat: "study github.com/owner/repo", "create a repo called …"</div>
  </div>
  ${review.length ? `<div class="section-h"><h2>Waiting for you · ${review.length}</h2>${readyAll(review) ? `<button class="btn sm primary" id="appall">${ic.check}Approve all ready (${readyAll(review)})</button>` : ""}</div>
    <div class="tiny faint" style="margin:-4px 0 8px">Tap one to see the change. <i>Approve all</i> deploys every build whose checks and CI passed, one after another; a conflict goes back to you.</div>
    <div class="card list waiting">${review.map(buildRow).join("")}</div>` : `<div class="card pad small muted">Nothing waits for your review.</div>`}
  ${busy.length ? `<div class="section-h section"><h2>Being built · ${busy.length}</h2>${how("builder")}</div><div class="card list">${busy.map(buildRow).join("")}</div>` : ""}
  ${(S.claude_tasks || []).length ? `<div class="section-h section"><h2>Claude tasks</h2><span class="tiny faint" style="text-align:right">what your agents asked Claude Code (read-only)</span></div>
    <div class="card list">${S.claude_tasks.map(ctRow).join("")}</div>` : ""}
  <div class="section-h section"><h2>Repositories</h2>${how("code")}</div>
  <div class="repos">${repos.map(repoCard).join("")}</div>
  ${forgejoCard()}${claudeCard()}
  <details class="card pad-l newbuild section" id="nb" ${route.q.get("new") ? "open" : ""}><summary><b>${ic.rocket} New build</b> <span class="small muted">give the builder an assignment</span></summary>
  <form id="bf" autocomplete="off" style="margin-top:12px">
    <div class="row wrap" style="gap:10px">
      <label class="field" style="margin:0;flex:1;min-width:140px"><span>Repository</span><select class="input" name="repo">${(buildable.length ? buildable : ["ai-stack"]).map((r) => `<option ${r === pre ? "selected" : ""}>${esc(r)}</option>`).join("")}</select></label>
      <label class="field" style="margin:0;flex:3;min-width:200px"><span>Title</span><input class="input" name="title" maxlength="100" placeholder="e.g. Show the next run time in the mission cards"></label>
      <label class="field" style="margin:0;flex:1;min-width:150px"><span>Engine</span><select class="input" name="engine"><option value="claude" ${S.engines?.claude ? "selected" : "disabled"}>Claude Code${S.engines?.claude ? "" : " (connect first)"}</option><option value="hermes" ${S.engines?.claude ? "" : "selected"}>ChatGPT · Hermes</option></select></label>
    </div>
    <label class="field"><span>What should it do?</span><textarea class="input" name="desc" rows="4" placeholder="Describe the change and how you'll know it works."></textarea></label>
    <button class="btn primary" type="submit">${ic.rocket}Assign to the builder</button>
  </form></details>
  <a class="banner info section" href="#/swarm?tab=improve">${ic.radar}<span class="grow">${ideasWaiting() ? `<b>${ideasWaiting()} idea${ideasWaiting() > 1 ? "s" : ""} wait for your tap</b>: the stack's own fixes and changes to its agents` : "No open ideas: the stack's own fixes and changes to its agents"}, in Agents → Ideas</span>${ic.next}</a>
  ${done.length ? `<details class="section"><summary class="section-h"><h2>Earlier builds · ${done.length}</h2></summary><div class="card list">${done.map(buildRow).join("")}</div></details>` : ""}`;
  bindAddRepo();
  if ($("#appall")) $("#appall").onclick = async (e) => {
    e.target.disabled = true;
    const r = await act({ action: "build_approve_all" }, (x) => (x?.approved ? `${x.approved.length} approved: deploying one after another` : ""));
    if (!r?.approved) e.target.disabled = false;
  };
  $("#addbtn").onclick = () => { $("#addrepo").hidden = !$("#addrepo").hidden; if (!$("#addrepo").hidden) $("#ar-url").focus(); };
  $("#addclose").onclick = () => ($("#addrepo").hidden = true);
  $("#newbtn").onclick = () => { $("#nb").open = true; $("#nb").scrollIntoView({ behavior: "smooth", block: "start" }); $("#bf").title.focus(); };
  if ($("#fjgo")) $("#fjgo").onclick = async () => {
    const t = $("#fjtok").value.trim();
    if (!t) return toast("Paste the token first", true);
    $("#fjgo").disabled = true;
    const r = await api("/api/forgejo/connect", { method: "POST", body: JSON.stringify({ token: t }) }).catch((e) => ({ ok: false, error: e.message }));
    $("#fjtok").value = ""; $("#fjgo").disabled = false;
    if (r.ok) toast(`Forgejo connected as ${r.user}. The card disappears in a minute.`); else toast(r.error || "Could not connect", true);
  };
  const f = $("#bf");
  f.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("button[type=submit]", f); btn.disabled = true;
    const r = await act({ action: "build_assign", repo: f.repo.value, title: f.title.value.trim(), description: f.desc.value.trim(), engine: f.engine.value }, (x) => (x?.id ? `Build #${x.id} queued: follow it on its page` : ""));
    btn.disabled = false;
    if (r?.id) { location.hash = `#/build/${r.id}`; }
  };
}

// ---------- Claude tasks (ops/claude_tasks.py): Hermes' questions to Claude Code, with Claude's steps and thinking ----------
const CT_STATUS = { queued: ["queued", "Queued"], running: ["running", "Working"], done: ["ok", "Answered"], failed: ["failed", "Failed"], waiting: ["paused", "Waits for Claude's limit"] };
function ctRow(t) {
  const [cls, label] = CT_STATUS[t.status] || ["queued", t.status];
  return `<details class="ctask" data-ct="${t.id}" style="display:block;padding:10px 12px"><summary style="list-style:none;cursor:pointer">
    <div class="row between" style="gap:8px"><b class="small wrap">#${t.id} ${esc(ctTitle(t))}</b><span class="tiny faint" style="white-space:nowrap">${rel(t.ended || t.started || t.created)}</span></div>
    <div class="row wrap tiny muted" style="gap:6px;margin-top:3px"><span class="pill ${cls}" style="padding:1px 7px">${label}</span>${esc(t.mode)}${t.repo ? " · " + esc(t.repo) : ""}${t.turns ? ` · ${t.turns} steps` : ""}${t.tokens ? ` · ${tok(t.tokens)} tokens${t.cached ? ` (${Math.round(100 * t.cached / t.tokens)} % cached)` : ""}` : ""}</div></summary>
    ${ctTitle(t) !== t.question ? `<details style="margin-top:10px"><summary class="small muted">The whole question${/^crew:/.test(t.source || "") ? ` the ${esc(ctAsker(t))} asked` : ""}</summary><div class="small wrap" style="white-space:pre-wrap;margin-top:6px">${esc(t.question)}</div></details>` : ""}
    <div class="ctbody" id="ct-${t.id}" style="margin-top:10px"><div class="skeleton" style="height:40px"></div></div></details>`;
}
// an answer in JSON (the Health doctor's diagnoses) is shown as findings, any other as Markdown; nothing is left out
function ctAnswer(a) {
  let j;
  try { j = JSON.parse(a.trim().replace(/^```(?:json)?\s*|\s*```$/g, "")); } catch { return `<div class="md small">${md(a)}</div>`; }
  const { diagnoses, ...rest } = j && typeof j === "object" ? j : { diagnoses: null };
  const more = Object.keys(rest).length ? `<pre class="small" style="white-space:pre-wrap;margin-top:8px">${esc(JSON.stringify(rest, null, 2))}</pre>` : "";
  if (!Array.isArray(diagnoses)) return `<pre class="small" style="white-space:pre-wrap">${esc(JSON.stringify(j, null, 2))}</pre>`;
  return diagnoses.map((x) => {
    const { issue, class: kind, cause, fix, evidence, confidence, ...other } = x || {};
    return `<div class="card pad ctdiag"><div class="row wrap" style="gap:6px"><b class="small">Issue ${esc(issue ?? "")}</b>${kind ? `<span class="tag">${esc(kind)}</span>` : ""}${confidence ? `<span class="tag">${esc(confidence)} confidence</span>` : ""}</div>
      ${cause ? `<p class="small wrap" style="margin:6px 0 0">${esc(cause)}</p>` : ""}${fix ? `<p class="small wrap" style="margin:6px 0 0"><b>Fix:</b> ${esc(fix)}</p>` : ""}
      ${(evidence || []).length ? `<details style="margin-top:6px"><summary class="tiny muted">Evidence · ${evidence.length}</summary><ul class="small" style="margin:6px 0 0;padding-left:18px">${evidence.map((e) => `<li class="wrap">${esc(e)}</li>`).join("")}</ul></details>` : ""}
      ${Object.keys(other).length ? `<pre class="tiny" style="white-space:pre-wrap;margin-top:6px">${esc(JSON.stringify(other, null, 2))}</pre>` : ""}</div>`;
  }).join("") + more;
}
document.addEventListener("toggle", async (e) => {                   // load a task when it is opened (toggle doesn't bubble)
  const d = e.target;
  if (!d.matches?.("details.ctask") || !d.open) return;
  const T = await api(`/api/claude/${d.dataset.ct}`).catch(() => null), el = $(`#ct-${d.dataset.ct}`);
  if (!el) return;
  if (!T || T.error) { el.innerHTML = `<div class="small muted">Not available.</div>`; return; }
  tlLevel = tlLevel || pref("mc-tl", "steps");
  el.innerHTML = `<div class="row" style="margin-bottom:8px">${liveLink("claude-task:" + d.dataset.ct)}</div>${T.answer ? ctAnswer(T.answer) : T.error ? `<div class="banner" style="padding:8px 12px">${ic.alert}<span class="small">${esc(T.error)}</span></div>` : ""}
    ${obsBlocks(T.files, T.detail)}
    <details style="margin-top:10px"><summary class="small muted">What Claude did · ${T.steps.length} steps${T.steps.some((s) => s.kind === "think") ? " · with its thinking" : ""}</summary>
      <div style="margin-top:6px">${T.steps.length ? logHtml(T.steps, { level: "all" }) : `<div class="small muted">No steps yet.</div>`}</div></details>`;
}, true);

function readyAll(list) {
  return list.filter((b) => b.checks_ok && (!["ai-stack", "TestRepo"].includes(b.repo) || b.ci === "success") && b.ai_review?.verdict !== "block").length;
}

function buildRow(b) {
  const cls = bcls(b.status);
  return `<a href="#/build/${b.id}"><div class="ic ${cls === "ok" ? "ok" : cls === "failed" ? "err" : cls === "running" ? "run" : ""}">${b.status === "review" ? ic.search : ["deployed", "merged"].includes(b.status) ? ic.check : ["failed", "rolled_back"].includes(b.status) ? ic.alert : ic.rocket}</div>
    <div class="grow"><div class="ttl wrap">#${b.id} ${esc(b.title)}</div><div class="sub">${esc(b.repo)}${b.engine === "claude" ? " · Claude Code" : ""} · <span class="pill ${cls}" style="padding:1px 7px">${BSTATUS[b.status] || b.status}</span>${b.ci && b.status === "review" ? ` · CI ${esc(b.ci)}` : ""}${b.status === "review" && b.ai_review?.verdict ? ` · ${VERDICT[b.ai_review.verdict]?.[1] || ""}` : ""}${b.tokens ? ` · ${tok(b.tokens)} tokens` : ""}</div></div>
    <div class="tiny faint">${rel(b.updated)}</div></a>`;
}

function bindAddRepo() {
  $$("[data-ar]").forEach((b) => (b.onclick = () => {
    $$("[data-ar]").forEach((x) => x.classList.toggle("on", x === b));
    $("#ar-study").hidden = b.dataset.ar !== "study"; $("#ar-new").hidden = b.dataset.ar !== "new";
  }));
  $("#ar-go").onclick = async () => {
    const v = $("#ar-url").value.trim();
    if (v && (await act({ action: "understand", repo: v }, "Studying it: graph and code map arrive in a few minutes"))) $("#ar-url").value = "";
  };
  $("#ar-create").onclick = async () => {
    const name = $("#ar-name").value.trim().toLowerCase();
    if (!name) return toast("Give it a name", true);
    $("#ar-create").disabled = true;
    const r = await act({ action: "repo_create", name, description: $("#ar-desc").value.trim() }, `Created ${name}: it shows in your repositories`);
    $("#ar-create").disabled = false;
    if (r?.repo) location.hash = `#/repo/${encodeURIComponent(r.repo)}`;
  };
}

let cmSwitching = "";                                          // the repo the code map viewer is switching to (one switch at a time)
async function vRepo() {
  const name = route.args[0], r = repoOf(name);
  if (!name) { location.hash = "#/build"; return; }          // no repository named: the list of them (U4)
  if (!r) { view.innerHTML = `<a class="back" href="#/build">${ic.back}Code</a><div class="card empty">${ic.code}<div>No repository called ${esc(name)}. <a href="#/build">All repositories</a></div></div>`; return; }
  const bs = (S.builds || []).filter((b) => b.repo === name);
  const g = r.graph;
  view.innerHTML = `
  <a class="back" href="#/build">${ic.back}Code</a>
  <div class="row wrap between" style="gap:12px;align-items:flex-end">
    <div><h1 style="font-size:26px">${esc(name)}</h1>
      <div class="row wrap small muted" style="gap:8px;margin-top:6px"><span class="pill ${r.buildable ? "ok" : "archived"}">${r.buildable ? "builder can change it" : "studied only"}</span>
        ${r.source ? `<span class="wrap" style="max-width:340px">${esc(r.source)}</span>` : ""}${r.last ? `<span>· last commit ${rel(r.last.ts)}</span>` : ""}</div></div>
    <div class="row wrap" style="gap:8px">
      ${r.codemap ? `<button class="btn primary" id="rmap">${ic.layers}Interactive code map</button>` : ""}
      <a class="btn" href="#/chat?prompt=${encodeURIComponent(`In the repository ${name}: `)}">${ic.chat}Ask about it</a>
      ${r.buildable ? `<a class="btn" href="#/build?repo=${encodeURIComponent(name)}&new=1">${ic.rocket}New build</a>` : ""}
      <button class="btn ghost" id="rstudy" title="Refresh the code map (the graph updates by itself)">${ic.repeat}${r.codemap ? "Re-analyse" : "Build code map"}</button>
      ${!r.buildable && name !== "ai-stack" ? `<button class="btn ghost" id="rbuildable" ${S.code?.forgejo_token ? "" : "disabled title='Needs the Forgejo connection (Code tab)'"}>${ic.rocket}Let the builder change it</button>` : ""}
    </div>
  </div>
  ${bs.some((b) => b.status === "review") ? `<div class="section"><div class="section-h"><h2>Waiting for you</h2></div><div class="card list waiting">${bs.filter((b) => b.status === "review").map(buildRow).join("")}</div></div>` : ""}
  <div class="grid g2 g4 section">
    <div class="card kpi"><div class="kpi-l">Code graph</div><div class="kpi-v">${g ? nf(g.nodes) : "–"}</div><div class="kpi-s">${g ? `${nf(g.links)} links · ${g.communities} groups` : "builds by itself within a minute"}</div></div>
    <div class="card kpi"><div class="kpi-l">Code map</div><div class="kpi-v" style="font-size:20px">${r.codemap ? "ready" : "–"}</div><div class="kpi-s">${!r.codemap ? "tap Build code map" : r.explained?.files ? `${r.explained.status === "running" ? "explaining… " : ""}${nf(r.explained.explained || 0)} of ${nf(r.explained.files)} files explained${r.explained.status === "limit" ? " · resumes later" : ""}` : "explained below"}</div></div>
    <div class="card kpi"><div class="kpi-l">Files</div><div class="kpi-v">${r.files ? nf(r.files) : "–"}</div><div class="kpi-s">${r.last ? esc(r.last.sha) : ""}</div></div>
    <div class="card kpi"><div class="kpi-l">Builds</div><div class="kpi-v">${bs.length}</div><div class="kpi-s">${bs.filter((b) => b.status === "deployed" || b.status === "merged").length} merged</div></div>
  </div>
  ${r.codemap ? `<div class="section" id="rframesec"><div class="section-h"><h2>Interactive code map</h2><a class="tiny" href="${HOSTURL}:8446/" target="_blank" rel="noopener" id="rframefull" ${S.code?.codemap === name ? "" : "hidden"}>Full screen</a></div>
    <div class="card cmframe" id="rframe">${S.code?.codemap === name ? `<iframe src="${HOSTURL}:8446/" title="Code map of ${esc(name)}" loading="lazy"></iframe>`
      : `<div class="pad-l" id="rframewait"><div class="small muted">Opening the code map of ${esc(name)}… The viewer shows one repository at a time and switches to this one now (a few seconds).</div></div>`}</div></div>`
    : `<div class="card pad-l section cmnone"><h2>No code map yet</h2>${explain("the-code-map-explains-in", `The code map explains ${esc(name)} in plain language: what it does, its layers, a guided tour, every file and function, and an interactive, clickable map. Understand Anything writes it from the code (about 10 to 40 minutes, on your ChatGPT subscription; the code is never run).`, "About this")}
      <button class="btn primary" id="rstudy2" style="margin-top:10px">${ic.layers}Build the code map</button></div>`}
  <div id="rcodemap"></div>
  <div class="section"><div class="section-h"><h2>Code graph</h2><span class="tiny faint" id="rgnote">${g ? "tap a node: what it is, its code, what it calls" : ""}</span></div>
    <div class="rgwrap"><div id="rgraph">${g ? `<div class="skeleton" style="height:420px"></div>` : `<div class="card empty small">No graph yet. It is built by itself within a minute of a repository arriving.</div>`}</div>
      <aside class="card pad-l rnode" id="rnode" ${g ? "" : "hidden"}>${explain("tap-a-node-in-the-graph-", `Tap a node in the graph to see what it is, its source code, what it calls and what calls it${r.codemap ? ", and what the code map says about it" : ""}.`, "How to read this")}</aside></div></div>
  <div class="split section">
    <div class="card pad-l"><div class="row between"><h2>What it is</h2><span class="tiny faint" id="rsrc"></span></div><div class="md" id="rover" style="margin-top:8px"><div class="skeleton" style="height:120px"></div></div></div>
    <div><div class="section-h"><h2>Builds</h2></div><div class="card list">${bs.map(buildRow).join("") || `<div class="muted small">${r.buildable ? "No builds yet." : "The builder can only change repositories on your Forgejo."}</div>`}</div>
      ${name !== "ai-stack" ? `<details class="card pad-l danger-zone" style="margin-top:14px"><summary class="small"><b>Remove from the stack</b></summary>
        <div class="small muted" style="margin-top:8px">Deletes the stack's copy of ${esc(name)}: its clone, code graph, code map and the builder's working copy. ${r.buildable ? "<b>It stays on your Forgejo</b>: delete it there if you want it gone." : "You can study it again any time."}</div>
        <button class="btn sm ghost danger" id="rremove" style="margin-top:10px">${ic.trash}Remove ${esc(name)}</button></details>` : ""}</div>
  </div>`;
  api(`/api/repo/${encodeURIComponent(name)}/overview`).then((o) => {
    $("#rover").innerHTML = o.markdown ? md(o.markdown) : `<div class="small muted">No README and no code map yet.</div>`;
    $("#rsrc").textContent = o.source || "";
  }).catch(() => {});
  if (r.codemap) api(`/api/repo/${encodeURIComponent(name)}/map`).then((m) => { const el = $("#rcodemap"); if (el && !m.error) { el.innerHTML = codeMapHtml(m); bindCodeMap(el, m); } }).catch(() => {});
  if (g) api(`/api/repo/${encodeURIComponent(name)}/graph`).then((d) => {
    $("#rgnote").textContent = `${d.shown < d.total ? `${d.shown} best-connected of ${d.total} nodes` : `${d.total} nodes`} · tap a node: what it is, its code, what it calls`;
    const colors = {}; (d.communities || []).forEach(([c], i) => (colors[c] = d3.schemeTableau10[i % 10]));
    const groupName = (c) => {                       // a group by its best-connected member, not its number
      const top = d.nodes.filter((n) => n.folder === c).sort((x, y) => (y.degree || 0) - (x.degree || 0))[0];
      return top ? `around ${top.title}` : "other";
    };
    drawGraph($("#rgraph"), d, "", null, false, {
      color: (n) => colors[n.folder] || "#8e97ab", click: (n) => showNode(name, n.id),
      legend: (d.communities || []).map(([c, k]) => [groupName(c), colors[c], k]), still: true, labels: 25,
    });
  }).catch(() => ($("#rgraph").innerHTML = `<div class="card empty small">Graph not available.</div>`));
  // the viewer shows one repo at a time: switch it to this one, then show it inside the page
  const showMap = async (btn, quiet) => {
    if (!quiet) $("#rframesec")?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (S.code?.codemap !== name) {
      if (cmSwitching === name) return;
      if (btn) btn.disabled = true;
      cmSwitching = name;
      const ok = await act({ action: "codemap", repo: name }, null);   // the viewer opens in place
      cmSwitching = "";
      if (btn) btn.disabled = false;
      if (!ok) {
        const w = $("#rframewait");
        if (w) w.innerHTML = `<div class="small err-t">The code map viewer did not start. <button class="btn sm" id="rframeb">${ic.refresh || ""}Try again</button></div>`;
        const again = $("#rframeb");
        if (again) again.onclick = () => showMap(again);
        return;
      }
      if (S.code) S.code.codemap = name;
      await new Promise((res) => setTimeout(res, 2500));          // the viewer restarts on the new repo
    }
    const f = $("#rframe");
    if (f && !f.querySelector("iframe")) f.innerHTML = `<iframe src="${HOSTURL}:8446/" title="Code map of ${esc(name)}"></iframe>`;
    const full = $("#rframefull"); if (full) full.hidden = false;
  };
  const rm = $("#rmap");
  if (rm) rm.onclick = () => showMap(rm);
  if (r.codemap && S.code?.codemap !== name) showMap(null, true);   // every repo with a code map shows it, not only the last one opened
  const study = async (b) => { b.disabled = true; if (await act({ action: "understand", repo: name }, "Analysing: you get a message when the code map is ready")) b.textContent = "Analysing… (you get a message)"; else b.disabled = false; };
  $("#rstudy").onclick = () => study($("#rstudy"));
  const rs2 = $("#rstudy2");
  if (rs2) rs2.onclick = () => study(rs2);
  const rb = $("#rbuildable");
  if (rb) rb.onclick = async () => { if (!confirm(`Copy ${name} to your Forgejo so the builder can change it? The original stays as "upstream".`)) return; rb.disabled = true; await act({ action: "repo_buildable", repo: name }, `${name} is on Forgejo now`); };
  const rr = $("#rremove");
  if (rr) rr.onclick = async () => {
    if (prompt(`Type ${name} to remove it from the stack:`) !== name) return toast("Not removed", true);
    rr.disabled = true;
    const res = await act({ action: "repo_remove", repo: name }, (x) => (x?.removed ? `${name} removed from the stack${x.still_on_forgejo ? "; it stays on Forgejo" : ""}` : ""));
    if (res?.removed) { location.hash = "#/build"; } else rr.disabled = false;
  };
}

// one code graph node: what it is, its source, what it calls / what calls it, and what the code map says
async function showNode(repo, id) {
  const el = $("#rnode");
  if (!el) return;
  el.hidden = false;
  el.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
  const n = await api(`/api/repo/${encodeURIComponent(repo)}/node?id=${encodeURIComponent(id)}`).catch(() => null);
  if (!n || n.error) { el.innerHTML = `<div class="small muted">Nothing more known about this node.</div>`; return; }
  const peers = (list, dir) => {
    const groups = {};
    list.forEach((p) => (groups[p.relation || "linked"] = groups[p.relation || "linked"] || []).push(p));
    return Object.entries(groups).map(([rel, ps]) => `<div class="tiny faint" style="margin-top:8px">${esc(dir === "out" ? relOut[rel] || rel : relIn[rel] || rel)} · ${ps.length}</div>
      <div class="chips" style="margin-top:4px">${ps.slice(0, 14).map((p) => `<button class="tag peer" data-node="${esc(p.id)}" title="${esc(p.file)}${p.inferred ? " (inferred)" : ""}">${esc(p.label)}</button>`).join("")}${ps.length > 14 ? `<span class="tiny faint">+${ps.length - 14}</span>` : ""}</div>`).join("");
  };
  const ua = n.about || n.about_file;
  el.innerHTML = `
    <div class="row between" style="gap:8px;align-items:flex-start"><div style="min-width:0"><b class="rn-t">${esc(n.label)}</b>
      <div class="row wrap tiny muted" style="gap:6px;margin-top:4px"><span class="tag">${esc(n.kind)}</span>${n.group ? `<span class="tag">${esc(n.group)}</span>` : ""}${n.external ? `<span class="tag">outside this repo</span>` : ""}</div></div>
      <a class="btn sm ghost" href="#/chat?prompt=${encodeURIComponent(`In the repository ${repo}, explain ${n.label}${n.file ? ` (${n.file}${n.line ? `:${n.line}` : ""})` : ""}: what it does, who uses it, and what to watch out for when changing it.`)}" title="Ask Hermes about it">${ic.chat}Ask</a></div>
    ${n.file ? `<div class="small mono" style="margin-top:8px">${esc(n.file)}${n.line ? `:${n.line}` : ""}</div>` : ""}
    ${n.about ? `<div class="rn-ua"><div class="tiny faint">Code map</div><div class="small">${esc(n.about.summary || "")}</div>${n.about.tags?.length ? `<div class="chips" style="margin-top:4px">${n.about.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}${n.about.complexity ? `<span class="tag">${esc(n.about.complexity)}</span>` : ""}</div>` : ""}</div>` : ""}
    ${n.about_file ? `<div class="rn-ua"><div class="tiny faint">Its file, in the code map</div><div class="small">${esc(n.about_file.summary || "")}</div></div>` : ""}
    ${!ua && !S.code?.repos?.find((x) => x.name === repo)?.codemap ? `<div class="tiny faint" style="margin-top:8px">Build the code map for plain-language explanations of each file and function.</div>` : ""}
    ${peers(n.outgoing, "out")}${peers(n.incoming, "in")}
    ${n.code ? `<details class="rn-code" open><summary class="tiny faint">Source · from line ${n.code.start}</summary><pre class="code">${esc(n.code.text)}</pre></details>` : ""}`;
  $$(".peer", el).forEach((b) => (b.onclick = () => showNode(repo, b.dataset.node)));
  if (matchMedia("(max-width: 959px)").matches) el.scrollIntoView({ behavior: "smooth", block: "start" });
}
const relOut = { calls: "Calls", contains: "Contains", imports: "Imports", imports_from: "Imports from", references: "References", inherits: "Inherits from", defines: "Defines", method: "Methods", indirect_call: "Calls indirectly", rationale_for: "Explains" };
const relIn = { calls: "Called by", contains: "Part of", imports: "Imported by", imports_from: "Imported by", references: "Referenced by", inherits: "Inherited by", defines: "Defined by", method: "Method of", indirect_call: "Called indirectly by", rationale_for: "Explained by" };

// the code map (Understand Anything) in the app: project, guided tour, layers, every file and function
function codeMapHtml(m) {
  const p = m.project || {}, nodes = m.nodes || [], byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const item = (id) => { const n = byId[id]; return n ? `<li><b>${esc(n.name || n.filePath)}</b>${n.filePath && n.name !== n.filePath ? ` <span class="tiny faint mono">${esc(n.filePath)}</span>` : ""}<div class="small muted">${esc(n.summary || "")}</div></li>` : ""; };
  return `<div class="section"><div class="section-h"><h2>Code map</h2><span class="tiny faint">Understand Anything${p.analyzedAt ? ` · analysed ${rel(p.analyzedAt)}` : ""}</span></div>
  <div class="card pad-l cmap">
    ${p.description ? `<div class="cm-desc">${esc(p.description)}</div>` : ""}
    <div class="chips" style="margin-top:8px">${(p.languages || []).map((l) => `<span class="tag">${esc(l)}</span>`).join("")}${(p.frameworks || []).map((l) => `<span class="tag">${esc(l)}</span>`).join("")}</div>
    <div class="seg sm" style="margin-top:14px"><button type="button" data-cm="tour" class="on">Guided tour · ${(m.tour || []).length}</button><button type="button" data-cm="layers">Layers · ${(m.layers || []).length}</button><button type="button" data-cm="files">Files & symbols · ${nodes.length}</button></div>
    <div data-cmp="tour"><ol class="cm-tour">${(m.tour || []).sort((a, b) => a.order - b.order).map((t) => `<li><b>${esc(t.title)}</b><div class="small">${esc(t.description)}</div><ul class="cm-list">${(t.nodeIds || []).map(item).join("")}</ul></li>`).join("")}</ol></div>
    <div data-cmp="layers" hidden>${(m.layers || []).map((l) => `<div class="cm-layer"><b>${esc(l.name)}</b><div class="small muted">${esc(l.description || "")}</div><ul class="cm-list">${(l.nodeIds || []).map(item).join("")}</ul></div>`).join("")}</div>
    <div data-cmp="files" hidden><div class="wsearch" style="margin-top:10px">${ic.search}<input class="input" id="cmq" placeholder="Filter files and symbols"></div>
      <div class="cm-files">${nodes.map((n) => `<div class="cm-file" data-q="${esc(`${n.name} ${n.filePath} ${n.summary} ${(n.tags || []).join(" ")}`.toLowerCase())}"><div class="row wrap" style="gap:6px"><span class="tag">${esc(n.type)}</span><b>${esc(n.name || n.filePath)}</b>${n.complexity ? `<span class="tiny faint">${esc(n.complexity)}</span>` : ""}</div>
        ${n.filePath && n.name !== n.filePath ? `<div class="tiny faint mono">${esc(n.filePath)}${n.lineRange ? `:${n.lineRange[0]}-${n.lineRange[1]}` : ""}</div>` : ""}<div class="small muted">${esc(n.summary || "")}</div></div>`).join("")}</div></div>
  </div></div>`;
}
function bindCodeMap(el) {
  $$("[data-cm]", el).forEach((b) => (b.onclick = () => {
    $$("[data-cm]", el).forEach((x) => x.classList.toggle("on", x === b));
    $$("[data-cmp]", el).forEach((p) => (p.hidden = p.dataset.cmp !== b.dataset.cm));
  }));
  const q = $("#cmq", el);
  if (q) q.oninput = () => { const v = q.value.trim().toLowerCase(); $$(".cm-file", el).forEach((f) => (f.hidden = v && !f.dataset.q.includes(v))); };
}

// the second pair of eyes (ops/builds.py ai_review): the other engine's verdict on the diff
const VERDICT = { approve: ["ok", "Fine to deploy"], changes: ["paused", "Improve first"], block: ["failed", "Do not deploy"] };
const LENS = { requirements: "Requirements and correctness", security: "Security and data flow", agents: "Agents rule (no agent rewrites itself)" };
function findingsHtml(fs) {
  return fs?.length ? `<ul class="findings">${fs.map((f) => `<li class="${f.severity}"><div class="row wrap" style="gap:6px"><span class="tag sev">${esc(f.severity)}</span>${f.file ? `<span class="mono tiny">${esc(f.file)}${f.line ? `:${f.line}` : ""}</span>` : ""}</div>
      <div class="small" style="margin-top:4px">${esc(f.issue)}</div>${f.fix ? `<div class="tiny muted" style="margin-top:2px">Fix: ${esc(f.fix)}</div>` : ""}</li>`).join("")}</ul>` : `<div class="small muted" style="margin-top:6px">No problems found.</div>`;
}
function aiReviewHtml(b) {
  const r = b.ai_review;
  if (!r) return "";
  const who = (e) => (e === "claude" ? "Claude Code" : e === "rule" ? "a rule, no model" : "ChatGPT");
  if (r.pending) return `<div class="card pad-l"><h2>AI review</h2><div class="small muted" style="margin-top:8px"><span class="spin" style="width:12px;height:12px;vertical-align:-1px"></span> ${who(r.engine)} reviews the change${r.lenses ? ` with ${r.lenses.length} lenses (${r.lenses.map((l) => LENS[l] || l).join(", ")})` : ""}…</div></div>`;
  if (r.error && !r.verdict) return `<div class="card pad-l"><h2>AI review</h2><div class="small muted" style="margin-top:8px">${esc(r.error)} (${who(r.engine)}). Re-run checks to try again.</div></div>`;
  const [cls, label] = VERDICT[r.verdict] || VERDICT.changes;
  const lenses = r.reviews || [];                        // SWM-95: one reviewer per lens, each with its own verdict
  return `<div class="card pad-l aireview"><div class="row between wrap" style="gap:8px"><h2>AI review</h2><span class="tiny faint">${lenses.length ? `${lenses.length} reviewers` : `by ${who(r.engine)}`} · ${rel(r.at)}</span></div>
    <div class="row wrap" style="gap:8px;margin-top:8px;align-items:center"><span class="pill ${cls}">${label}</span>${lenses.length ? `<span class="small muted">the strictest verdict counts${b.override ? `; you overrode the block: “${esc(b.override.reason)}”` : ""}</span>` : `<span class="small">${esc(r.summary)}</span>`}</div>
    ${r.note ? `<div class="tiny muted" style="margin-top:6px">${esc(r.note)}${r.same_engine ? " Same engine as the builder, so less independent." : ""}</div>` : ""}
    ${lenses.length ? lenses.map((x) => { const [c2, l2] = VERDICT[x.verdict] || ["queued", "not done"]; return `<div class="lens" style="margin-top:12px;border-top:1px solid var(--border);padding-top:10px">
      <div class="row between wrap" style="gap:6px"><b class="small">${esc(LENS[x.lens] || x.lens)}</b><span class="tiny faint">${who(x.engine)}${x.same_engine ? " (same engine as the builder)" : ""}</span></div>
      <div class="row wrap" style="gap:8px;margin-top:6px;align-items:center"><span class="pill ${c2}">${l2}</span><span class="small">${esc(x.summary || x.error || "")}</span></div>${x.verdict ? findingsHtml(x.findings) : ""}</div>`; }).join("")
    : findingsHtml(r.findings)}
  </div>`;
}

// the plan behind a build (SWM-91, SWM-92, SWM-94, SWM-96): its task and idea, its files and lease, the merge queue,
// the requirements it names and their proof, and the code graph's blast radius
function planHtml(b) {
  const lease = (S.swarm?.leases || []).filter((l) => l.holder === `build:${b.id}`);
  const board = [...(S.swarm?.board?.open || []), ...(S.swarm?.board?.recent || [])];   // builds from before phase 4: the Ledger's ref
  const idea = b.idea || board.find((x) => (x.refs || []).some((r) => r.system === "build" && r.ref === String(b.id)))?.id;
  return `<div class="card pad-l" id="bplan"><h2>Plan, files and blast radius</h2>
    <div class="small" style="margin-top:8px">${b.task ? `Task <a href="#/swarm/artifact/${b.task}">#${b.task}</a> of idea <a href="#/swarm/artifact/${idea}">#${idea}</a>` : idea ? `For idea <a href="#/swarm/artifact/${idea}">#${idea}</a>` : "A direct assignment (no idea behind it)"}${b.note ? ` · ${esc(b.note)}` : ""}${b.slot ? ` · slot ${b.slot}` : ""}${b.queue_pos ? ` · <b>merge queue: ${b.queue_pos === 1 ? "next" : "#" + b.queue_pos}</b>` : ""}</div>
    ${b.files_plan?.length ? `<div class="tiny faint" style="margin-top:6px">Its files: ${b.files_plan.map((f) => `<span class="mono">${esc(f)}</span>`).join(", ")}${lease.length ? " · held for this build" : ""}</div>` : ""}
    ${b.proof ? `<details class="tools" style="margin-top:8px" ${/NOT PROVEN/.test(b.proof) ? "open" : ""}><summary>Requirements it names: ${b.requirements?.length ? b.requirements.map(esc).join(", ") : "none"} · ${/REQUIREMENTS PROVEN/.test(b.proof) ? "proven" : "not proven"}</summary><div class="log">${esc(b.proof)}</div></details>` : ""}
    <div id="bblast" style="margin-top:10px"><div class="small muted">Loading the blast radius…</div></div></div>`;
}
function blastHtml(ctx) {
  const p = ctx?.changed?.files && Object.keys(ctx.changed.files).length ? ctx.changed : ctx?.planned;
  if (!p?.files || !Object.keys(p.files).length) return `<div class="small muted">No blast radius yet (it is drawn from the files a build names or changes).</div>`;
  return `<div class="tiny faint">${p === ctx.changed ? "Of the files it changed" : "Of the files it plans to change"}, from the code graph of main:</div><div class="list" style="margin-top:4px">${Object.entries(p.files).map(([f, d]) => `<div style="padding:6px 2px;display:block">
    <div class="mono small">${esc(f)}</div><div class="tiny faint">${d.callers.length ? `used by ${d.callers.map(esc).join(", ")}${d.more_callers ? ` +${d.more_callers}` : ""}` : "no callers in the graph"}${d.callees.length ? ` · uses ${d.callees.map(esc).join(", ")}` : ""}</div>
    <div class="tiny">tests: ${d.tests.length ? d.tests.map(esc).join(", ") : "<b>none found</b>"}${d.requirements.length ? ` · requirements: ${d.requirements.map(esc).join(", ")}` : ""}</div></div>`).join("")}</div>`;
}

function stepText(x) {                                  // a tool result: its error message if it failed, else its first words
  if (x.kind !== "error" && x.kind !== "result") return x.text;
  const m = x.text.match(/"error":\s*"([^"]*)/);
  return m ? m[1] : x.text.replace(/^\{"(output|content)":\s*"/, "");
}

function stepsList(steps) {                             // the builder's steps, drawn as the agent log
  if (!steps.length) return `<div class="small muted">No steps yet.</div>`;
  return (steps.length > 400 ? `<div class="small muted">${steps.length - 400} earlier steps are in the Full log below.</div>` : "") + logHtml(steps.slice(-400) /* cap: list */, { level: "all" });
}

function diffHtml(text) {
  if (!text) return `<div class="small muted">No diff.</div>`;
  const files = text.split(/^diff --git /m).filter(Boolean);
  return files.map((f) => {
    const name = (f.match(/ b\/(.+)\n/) || [])[1] || "file";
    const lines = f.split("\n").slice(1);
    const adds = lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length, dels = lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length;
    const body = lines.filter((l) => !/^(index |--- |\+\+\+ |new file|deleted file|similarity|rename )/.test(l))
      .map((l) => `<div class="dl ${l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : ""}">${esc(l) || " "}</div>`).join("");
    return `<details class="dfile" ${files.length <= 8 ? "open" : ""}><summary><span class="wrap">${esc(name)}</span><span class="tiny"><b style="color:var(--ok)">+${adds}</b> <b style="color:var(--err)">−${dels}</b></span></summary><div class="dcode">${body}</div></details>`;
  }).join("");
}

function vBuildOne(id) {
  const b = (S.builds || []).find((x) => x.id === id);
  if (!b) { view.innerHTML = `<a class="back" href="#/build">${ic.back}Code</a><div class="card empty">Build not found.</div>`; return; }
  const review = b.status === "review";
  const other = b.engine === "claude" ? "hermes" : "claude", otherName = other === "claude" ? "Claude Code" : "ChatGPT";
  const canSwitch = ["queued", "waiting", "review", "failed"].includes(b.status) && (other !== "claude" || S.engines?.claude);
  const ciNeeded = ["ai-stack", "TestRepo"].includes(b.repo), ciOk = !ciNeeded || b.ci === "success";
  const canApprove = review && b.checks_ok && b.ci !== "failure" && !b.approve_on_ci;   // CI running: approve now, deploys when it passes
  view.innerHTML = `
  <a class="back" href="#/build">${ic.back}Code</a>
  <h1 style="font-size:23px">#${b.id} ${esc(b.title)}</h1>
  <div class="row wrap small muted" style="gap:8px;margin-top:6px"><span class="pill ${bcls(b.status)}">${BSTATUS[b.status] || b.status}</span><span>${esc(b.repo)}</span><span>· ${b.engine === "claude" ? "Claude Code" : "ChatGPT · Hermes"}</span><span>· ${esc(b.branch || "")}</span>${b.tokens ? `<span>· ${tok(b.tokens)} tokens${b.cached ? ` (${Math.round(100 * b.cached / b.tokens)} % cached)` : ""}, $0</span>` : ""}</div>
  <div class="row wrap" style="gap:6px;margin-top:10px">${liveLink("build:" + b.id)}</div>
  ${stepper(b.status)}
  ${b.error ? `<div class="banner" style="margin-top:12px;background:var(--err-bg);color:var(--err)">${ic.alert}<span class="grow">${esc(b.error)}</span></div>` : ""}
  ${b.status === "waiting" ? `<div class="banner" style="margin-top:12px">${ic.clock}<span class="grow">Waiting for the usage limit to reset${b.retry_at ? ` (${clock(b.retry_at)})` : ""}${canSwitch ? `, or switch to ${otherName}` : ""}.</span></div>` : ""}
  ${canSwitch ? `<div class="row wrap" style="margin-top:12px"><button class="btn sm ghost" id="bswitch" title="Run this build with the other engine, continuing from its branch">${ic.repeat}Switch to ${otherName}</button></div>` : ""}
  ${review ? `<div class="card pad" style="margin-top:14px">
      <div class="row wrap" style="gap:8px">
        <button class="btn primary" id="bapprove" ${canApprove ? "" : "disabled"}>${ic.check}${b.approve_on_ci ? "Approved · deploys when CI passes" : ciOk ? "Approve & deploy" : "Approve · deploy when CI passes"}</button>
        <button class="btn" id="bchanges">${ic.tune}Request changes</button>
        <button class="btn ghost" id="brecheck" title="Run the checks again on today's main, without the builder">${ic.repeat}Re-run checks</button>
        <button class="btn ghost danger" id="breject">${ic.x}Reject</button>
      </div>
      <div class="small muted" style="margin-top:8px">${b.approve_on_ci ? `Approved. CI on Forgejo is ${esc(b.ci || "pending")}; it merges and deploys by itself the moment CI passes (and stays here if CI fails).` : !b.checks_ok ? "Checks failed: request changes." : b.ci === "failure" ? "CI failed: request changes." : ciOk ? "Approving merges into the main branch and deploys; if the smoke test fails it rolls back by itself." : `CI on Forgejo is ${esc(b.ci || "pending")} (usually 1–3 minutes). You can approve now: it deploys by itself when CI passes.`}</div>
      ${b.sensitive?.length ? `<div class="banner" style="margin-top:10px">${ic.alert}<span class="grow">Touches sensitive files: ${b.sensitive.map(esc).join(", ")}. Read the diff carefully.</span></div>` : ""}
      <div id="chbox" hidden style="margin-top:10px"><textarea class="input" id="chtext" rows="3" placeholder="What should the builder change?"></textarea><button class="btn sm primary" id="chsend" style="margin-top:8px">Send to the builder</button></div>
    </div>` : ""}
  <div class="card pad-l section"><div class="row between wrap" style="gap:8px"><h2>The change · ${b.files?.length || 0} file${b.files?.length === 1 ? "" : "s"}</h2><span class="tiny faint mono">git diff main…${esc(b.branch || "")}</span></div>
    ${b.files?.length ? `<div id="diff" style="margin-top:10px"><div class="skeleton" style="height:60px"></div></div>` : `<div class="small muted" style="margin-top:8px">${["review", "merged", "rolled_back"].includes(b.status) ? "This build changed no files." : "No change yet: the builder is still working."}</div>`}</div>
  <div class="split section">
    <div class="stack">
      <div class="card pad-l" id="bfiles"><h2>Files the builder read and changed</h2><div class="small muted" style="margin-top:6px">Loading…</div></div>
      <div class="card pad-l"><h2>Assignment</h2><div class="md small" style="margin-top:8px">${md(b.description)}</div>${b.feedback ? `<h2 style="margin-top:14px">Changes requested</h2><div class="small" style="margin-top:6px">${esc(b.feedback)}</div>` : ""}</div>
      ${aiReviewHtml(b)}
      ${planHtml(b)}
      ${b.summary ? `<div class="card pad-l"><h2>Builder's summary</h2><div class="md" style="margin-top:8px">${md(b.summary)}</div></div>` : ""}
    </div>
    <div class="stack">
      <div class="card pad"><h2>Checks</h2><div class="row" style="margin-top:8px"><span class="dot ${b.checks ? (b.checks_ok ? "ok" : "err") : ""}"></span><span class="small">${b.checks ? (b.checks_ok ? "Passed in the sandbox" : "Failed") : "Not run yet"}</span></div>${b.checks ? `<details class="tools" style="margin-top:8px"><summary>Output</summary><div class="log">${esc(b.checks)}</div></details>` : ""}
        <h2 style="margin-top:14px">CI (Forgejo)</h2><div class="row" style="margin-top:8px"><span class="dot ${b.ci === "success" ? "ok" : b.ci === "failure" ? "err" : b.ci ? "run" : ""}"></span><span class="small">${esc(b.ci || "not pushed yet")}</span></div>
        ${b.pr ? `<a class="btn sm" style="margin-top:12px" href="${esc(b.pr)}" target="_blank" rel="noopener">${ic.next}Pull request on Forgejo</a>` : ""}</div>
      ${b.status === "deployed" && b.repo === "ai-stack" && b.merged ? `<div class="card pad"><h2>Undo</h2><div class="small muted" style="margin-top:6px">One tap reverts this change on main and deploys the revert, next in the merge queue.${b.idea ? ` Its ${esc((S.swarm?.changes || []).some((x) => x.id === b.idea) ? "agent change" : "idea")} <a href="#/swarm/artifact/${b.idea}">#${b.idea}</a> opens again.` : ""}</div>
        <button class="btn sm" id="brevert" style="margin-top:8px">Revert</button></div>` : ""}
      ${b.deploy ? `<div class="card pad"><h2>Deploy</h2><div class="log" style="margin-top:8px;max-height:320px">${esc(b.deploy)}</div></div>` : ""}
      <div class="card pad"><div class="row between"><h2>What the builder did</h2><span class="tiny faint">${["working", "checking"].includes(b.status) ? "live" : ""}</span></div><div id="bsteps" class="bsteps" style="margin-top:8px"><div class="small muted">Loading…</div></div>
        <button class="btn sm ghost" id="blog" style="margin-top:8px">Full log</button><div class="log" id="blogbox" hidden style="max-height:400px"></div></div>
    </div>
  </div>`;
  api(`/api/build/${b.id}/files`).then((t) => { const el = $("#bfiles"); if (el) { const F = typeof t === "string" ? JSON.parse(t || "{}") : t; el.innerHTML = `<h2>Files the builder read and changed</h2><div style="margin-top:8px">${filesHtml(F.files)}</div><details class="obsb"><summary class="small"><b>Statistics</b></summary>${statsHtml(F.stats)}</details>`; } })
    .catch(() => { const el = $("#bfiles"); if (el) el.innerHTML = `<h2>Files</h2><div class="small muted" style="margin-top:6px">Recorded for builds from 28 October on.</div>`; });
  api(`/api/build/${b.id}/steps`).then((t) => { const el = $("#bsteps"); if (el) el.innerHTML = stepsList(JSON.parse(t || "[]")); }).catch(() => { const el = $("#bsteps"); if (el) el.innerHTML = `<div class="small muted">No steps recorded for this build yet (they appear while the builder works).</div>`; });
  if (b.files?.length) api(`/api/build/${b.id}/diff`).then((t) => ($("#diff").innerHTML = diffHtml(t))).catch(() => ($("#diff").textContent = "Diff not available."));
  api(`/api/build/${b.id}/context`).then((t) => { const el = $("#bblast"); if (el) el.innerHTML = blastHtml(typeof t === "string" ? JSON.parse(t || "{}") : t); })
    .catch(() => { const el = $("#bblast"); if (el) el.innerHTML = blastHtml(null); });
  if ($("#brevert")) $("#brevert").onclick = async () => {            // SWM-18: the one-step revert
    if (!confirm(`Revert build #${b.id} "${b.title}"? A revert commit lands on main and is deployed.`)) return;
    $("#brevert").disabled = true;
    if (!(await act({ action: "build_revert", id: b.id }, `#${b.id}: the revert is next in the merge queue`))) $("#brevert").disabled = false;
  };
  $("#blog").onclick = async () => { const box = $("#blogbox"); box.hidden = !box.hidden; if (!box.hidden) { box.textContent = (await api(`/api/build/${b.id}/log`).catch(() => "")) || "No log yet."; box.scrollTop = box.scrollHeight; } };
  if (canSwitch) $("#bswitch").onclick = async () => {
    if (review && !confirm(`Switch build #${b.id} to ${otherName}? It goes back to the builder for a second attempt from the current branch.`)) return;
    $("#bswitch").disabled = true;
    if (!(await act({ action: "build_switch_engine", id: b.id, engine: other }, `#${b.id} switched to ${otherName}`))) $("#bswitch").disabled = false;
  };
  if (review) {
    $("#bapprove").onclick = async () => {               // one tap; a reviewer's block needs your reason to override (SWM-95)
      let override;
      if (b.ai_review?.verdict === "block") {
        override = prompt(`A reviewer says build #${b.id} must NOT be deployed. To deploy it anyway, write why the block is wrong:`);
        if (!override || override.trim().length < 10) return;
      }
      $("#bapprove").disabled = true;
      if (await act({ action: "build_approve", id: b.id, ...(override ? { override } : {}) }, `#${b.id} approved: in the merge queue`)) location.hash = prevHash.startsWith("#/build/") ? "#/build" : prevHash;
    };
    $("#breject").onclick = async () => { if (confirm(`Reject build #${b.id}? Its branch is deleted.`)) await act({ action: "build_reject", id: b.id }, "Rejected: its branch is deleted"); };
    $("#bchanges").onclick = () => { $("#chbox").hidden = false; $("#chtext").focus(); };
    $("#brecheck").onclick = async () => { $("#brecheck").disabled = true; await act({ action: "build_recheck", id: b.id }, "Checks re-run on today's main"); };
    $("#chsend").onclick = async () => { const t = $("#chtext").value.trim(); if (t && (await act({ action: "build_revise", id: b.id, feedback: t }, "Sent: the builder continues"))) $("#chbox").hidden = true; };
  }
}

// ---------- stack (system) ----------
// ---------- tools: every tool the stack runs on, its menus one tap away (APP-30; web/static/tools.json is the one list) ----------
let TOOLS = null, toolQuery = "";
const toolsLoad = () => (TOOLS ? Promise.resolve(TOOLS) : fetch("/static/tools.json").then((r) => r.json()).then((j) => (TOOLS = j)).catch(() => ({ tools: [], pages: [] })));
const toolBase = (t) => (t.host.startsWith("tailnet") ? HOSTURL + t.host.slice(7) : t.host);
const toolUrl = (t, m) => toolBase(t) + m.path;
const toolAtHome = (t) => !t.host.startsWith("tailnet") && !t.host.includes("tailscale.com");   // the home network only
const toolOf = (id) => (TOOLS?.tools || []).find((t) => t.id === id);
function toolState(t) {
  if (t.status === "house" && S.house) return S.house.reachable ? ["ok", "up"] : ["err", "not reachable"];
  return null;
}
const toolLinks = (t) => t.menus.map((m) => `<a class="tag" href="${esc(toolUrl(t, m))}" target="_blank" rel="noopener">${esc(m.name)}</a>`).join("");

function stackToolsHtml() {
  if (!TOOLS) return `<div class="skeleton" style="height:120px"></div>`;
  return `<div class="wsearch gsearch">${ic.search}<input class="input" id="toolq" placeholder="Go to… people, wifi, tokens, voice, logs" value="${esc(toolQuery)}" autocomplete="off"></div>
    <div id="toolres"></div>
    <div class="grid g2 tools">${TOOLS.tools.map((t) => { const st = toolState(t);
      return `<div class="card pad tool"><div class="row between wrap" style="gap:4px 8px;align-items:baseline"><b>${esc(t.name)}</b><span class="tiny faint">${st ? `<span class="dot ${st[0]}" style="display:inline-block;margin-right:5px"></span>${esc(st[1])} · ` : ""}${toolAtHome(t) ? "home Wi-Fi" : "anywhere"}</span></div>
        <div class="small muted">${esc(t.what)}</div><div class="chips" style="margin-top:8px">${toolLinks(t)}</div></div>`; }).join("")}</div>
    ${explain("anywhere-opens-with-your", `${ic.check} “Anywhere” opens with your Tailscale login, no password. “Home Wi-Fi” tools (the NAS, the FRITZ!Box, Home Assistant) open at home and keep their own logins.`, "Where they open")}`;
}

function toolHits(q) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length || !TOOLS) return [];
  const hit = (s) => words.every((w) => s.toLowerCase().includes(w));
  const pages = TOOLS.pages.filter(([n, , w]) => hit(`${n} ${w}`)).map(([n, href]) => ({ name: `Mission Control → ${n}`, href, ext: false }));
  const menus = TOOLS.tools.flatMap((t) => t.menus.filter((m) => hit(`${t.name} ${m.name} ${m.words || ""} ${t.what}`)).map((m) => ({ name: `${t.name} → ${m.name}`, href: toolUrl(t, m), ext: true })));
  return [...pages, ...menus];
}

function bindStackTools() {
  const q = $("#toolq"), out = $("#toolres");
  if (!q) return;
  const draw = () => {
    toolQuery = q.value;
    const hits = toolHits(q.value);
    out.innerHTML = !q.value.trim() ? "" : hits.length
      ? `<div class="card list" style="margin-bottom:10px">${hits.map((h) => `<a href="${esc(h.href)}"${h.ext ? ' target="_blank" rel="noopener"' : ""}><div class="grow"><div class="ttl">${esc(h.name)}</div></div>${ic.next}</a>`).join("")}</div>`
      : `<div class="small muted" style="margin-bottom:10px">Nothing matches “${esc(q.value)}”: try a tool's name, or words like people, wifi, logs.</div>`;
  };
  q.oninput = draw;
  q.onkeydown = (e) => {                              // Enter opens the first match
    const h = e.key === "Enter" && toolHits(q.value)[0];
    if (h) h.ext ? window.open(h.href, "_blank", "noopener") : (location.hash = h.href);
  };
  draw();
}
const HOSTURL = location.hostname.endsWith(".ts.net") ? `https://${location.hostname}` : "https://pc.example.ts.net";

function stackTop(sy) {
  const ci = sy.ci || [], repos = sy.repos || [], skills = sy.skills || [];
  const ciCls = (s) => (s === "success" ? "ok" : s === "failure" ? "err" : s === "running" || s === "waiting" ? "run" : "");
  return `

  <div class="section-h section"><h2>Resources</h2>${how("stack-page")}</div>
  <div id="rescard">${resourcesHtml(S.resources)}</div>

  <div class="split section">
    <div class="stack">
      <div class="card pad-l" id="addk">
        <div class="row between"><h2>Add knowledge to the vault</h2>${how("knowledge")}</div>
        <div class="small muted" style="margin-top:4px">The curator turns it into linked wiki pages within minutes.</div>
        <div class="seg" style="margin-top:12px">${[["text", "Note"], ["url", "Web page"], ["file", "File"]].map(([k, l], i) => `<button type="button" data-k="${k}" class="${i ? "" : "on"}">${l}</button>`).join("")}</div>
        <input class="input" id="k_title" placeholder="Title (optional)" style="margin-top:10px">
        <textarea class="input" id="k_text" rows="4" placeholder="Paste or write a note…" style="margin-top:8px"></textarea>
        <input class="input" id="k_url" placeholder="https://…" style="margin-top:8px" hidden>
        <input class="input" id="k_file" type="file" accept=".pdf,.docx,.md,.txt,.html,.pptx,.xlsx,.csv" style="margin-top:8px" hidden>
        <button class="btn primary" id="k_go" style="margin-top:10px">${ic.plus}Add to vault</button>
      </div>
      <div class="card pad-l">
        <div class="row between"><h2>Long-term memory</h2>${how("knowledge")}</div>
        <div class="small muted" style="margin-top:4px">${nf(sy.memory?.facts)} facts, ${nf(sy.memory?.observations)} observations from your conversations.</div>
        <div class="row" style="margin-top:10px"><input class="input" id="m_q" placeholder="Search what it remembers…"><button class="btn" id="m_go">${ic.search}</button></div>
        <div id="m_res" class="stack" style="margin-top:10px"></div>
      </div>
    </div>
    <div class="stack">
      <div class="card pad-l">
        <div class="row between"><h2>Code</h2>${how("code")}</div>
        <div class="list" style="margin-top:6px">${repos.map((r) => `<div style="padding:8px 2px"><div class="grow"><b>${esc(r.name)}</b></div>${r.map ? `<a class="tag" href="${HOSTURL}:8446/" target="_blank" rel="noopener">code map</a>` : `<span class="tag faint">no map</span>`}</div>`).join("")}</div>
        <div class="row" style="margin-top:10px"><input class="input" id="u_repo" placeholder="https://github.com/owner/repo"><button class="btn" id="u_go">Analyse</button></div>
      </div>
      <div class="card pad-l"><div class="row between"><h2>Checks (CI)</h2>${how("stack-page")}</div><div class="list" style="margin-top:6px">${ci.map((c) => `<div style="padding:8px 2px"><span class="dot ${ciCls(c.status)}"></span><div class="grow">${esc(c.repo)}</div><span class="tiny faint">${esc(c.status)} ${esc(c.sha)}</span></div>`).join("")}</div></div>
      <div class="card pad-l"><div class="row between"><h2>Skills · ${skills.length}</h2>${how("stack-page")}</div><div class="small muted" style="margin-top:4px">What Hermes has learned; saved in Forgejo (hermes-skills).</div><div class="chips" style="margin-top:10px">${skills.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</div></div>
    </div>
  </div>`;
}

function bar(used, total, warnAt = 0.8) {
  const r = total ? Math.min(1, used / total) : 0;
  return `<div class="meter" style="margin-top:6px"><i style="width:${(r * 100).toFixed(1)}%;${r >= warnAt ? "background:var(--warn)" : ""}${r >= 0.93 ? ";background:var(--err)" : ""}"></i></div>`;
}
function resourcesHtml(R) {
  if (!R || !R.wsl) return `<div class="card empty small">Measuring…</div>`;
  const h = R.host, w = R.wsl;
  const tiles = [];
  if (h) tiles.push(`<div class="card kpi"><div class="kpi-l">Windows RAM</div><div class="kpi-v" style="font-size:22px">${nf(h.ram_total_gb - h.ram_free_gb, 1)} <span class="muted" style="font-size:14px">/ ${nf(h.ram_total_gb, 0)} GB</span></div><div class="kpi-s">${nf(h.ram_free_gb, 1)} GB free · AI stack VM ${nf(h.wsl_vm_gb, 1)} GB</div>${bar(h.ram_total_gb - h.ram_free_gb, h.ram_total_gb)}</div>`);
  tiles.push(`<div class="card kpi"><div class="kpi-l">AI stack RAM (WSL)</div><div class="kpi-v" style="font-size:22px">${nf(w.mem_used_gb, 1)} <span class="muted" style="font-size:14px">/ ${nf(w.mem_total_gb, 1)} GB</span></div><div class="kpi-s">limit set in .wslconfig</div>${bar(w.mem_used_gb, w.mem_total_gb)}</div>`);
  tiles.push(`<div class="card kpi"><div class="kpi-l">CPU</div><div class="kpi-v" style="font-size:22px">${w.cpu_pct} %</div><div class="kpi-s">AI stack · ${w.cores} threads${h ? ` · Windows total ${h.cpu_pct} %` : ""}</div>${bar(w.cpu_pct, 100)}</div>`);
  tiles.push(`<div class="card kpi"><div class="kpi-l">Disk</div><div class="kpi-v" style="font-size:22px">${h ? nf(h.disk_c_free_gb, 0) : nf(w.disk_free_gb, 0)} GB <span class="muted" style="font-size:14px">free</span></div><div class="kpi-s">${h ? `C: ${nf(h.disk_c_total_gb, 0)} GB · ` : ""}WSL ${nf(w.disk_free_gb, 0)} of ${nf(w.disk_total_gb, 0)} GB free</div>${h ? bar(h.disk_c_total_gb - h.disk_c_free_gb, h.disk_c_total_gb, 0.85) : ""}</div>`);
  const svc = (R.services || []).map((x) => `<div class="svcrow"><span class="n">${esc(x.name)}</span><span class="tiny faint num">${nf(x.cpu, 1)} %</span><div class="grow">${bar(x.mem_mb, x.limit_mb)}</div><span class="tiny num" style="min-width:96px;text-align:right">${nf(x.mem_mb)} / ${nf(x.limit_mb)} MB</span></div>`).join("");
  return `<div class="grid g2 g4">${tiles.join("")}</div><div class="card pad" style="margin-top:12px"><div class="tiny faint" style="margin-bottom:6px">Per service: CPU · RAM against its limit</div>${svc}</div>`;
}

function bindStack() {
  let kind = "text";
  $$("#addk [data-k]").forEach((b) => (b.onclick = () => {
    kind = b.dataset.k; $$("#addk [data-k]").forEach((x) => x.classList.toggle("on", x === b));
    $("#k_text").hidden = kind !== "text"; $("#k_url").hidden = kind !== "url"; $("#k_file").hidden = kind !== "file";
  }));
  $("#k_go").onclick = async () => {
    const btn = $("#k_go"), title = $("#k_title").value.trim();
    btn.disabled = true;
    try {
      if (kind === "file") {
        const f = $("#k_file").files[0];
        if (!f) return toast("Choose a file", true);
        const r = await fetch("/api/upload", { method: "POST", body: f, headers: { "X-Filename": f.name, "X-Title": title } }).then((x) => x.json());
        r.ok === false ? toast(r.error || "Upload failed", true) : toast("Added to the vault inbox");
      } else {
        const r = await act({ action: "vault_add", title, text: kind === "text" ? $("#k_text").value : "", url: kind === "url" ? $("#k_url").value.trim() : "" }, (x) => `Added as ${x.path || "a note"}: search and chat find it from now on`);
        if (r) { $("#k_text").value = ""; $("#k_url").value = ""; $("#k_title").value = ""; }
      }
    } finally { btn.disabled = false; }
  };
  const msearch = async () => {
    const q = $("#m_q").value.trim();
    if (q.length < 2) return;
    $("#m_res").innerHTML = `<div class="skeleton" style="height:40px"></div>`;
    const r = await act({ action: "memory_search", q }, null);   // a search: its answer shows below
    const facts = r?.facts || [];
    $("#m_res").innerHTML = (facts.map((f) => `<div class="small"><span class="tag">${esc(f.type)}</span> <span class="faint">${esc(f.date)}</span><div>${esc(f.text)}</div></div>`).join("") || `<div class="small muted">Nothing found.</div>`)
      + (facts.length ? `<button class="btn sm ghost danger" id="m_forget">${ic.trash}Forget conversations containing “${esc(q)}”</button>` : "");
    const fb = $("#m_forget");
    if (fb) fb.onclick = async () => { if (confirm(`Forget every stored conversation containing “${q}”?`)) { await act({ action: "forget", text: q }, "Forgotten: those conversations are gone from long-term memory"); msearch(); } };
  };
  $("#m_go").onclick = msearch;
  $("#m_q").onkeydown = (e) => { if (e.key === "Enter") msearch(); };
  $("#u_go").onclick = async () => { const v = $("#u_repo").value.trim(); if (v && (await act({ action: "understand", repo: v }, "Analysis started; you get a message when it's ready"))) $("#u_repo").value = ""; };
}

// The Stack tab is one page: how the stack works (live map, guide chapters, search) and how it is doing (status),
// each status section linked to the chapter that explains it. Chapters open as #/guide/<id> (guide.js).
// MEM-01, MEM-07: every memory the stack keeps (ops/memory.py, refreshed hourly): kind, size, growth, limit, who tidies it, problems
const MEM_KIND = { episodic: "what happened", semantic: "what is true", procedural: "how to act", shared: "shared work", index: "search" };
const fmtBytes = (b) => (b >= 1e9 ? `${nf(b / 1e9, 1)} GB` : b >= 1e6 ? `${nf(b / 1e6, 1)} MB` : `${nf(Math.round((b || 0) / 1e3))} KB`);
function memUse(m) {                                          // how full it is against its limit: [value, limit, label]
  const [n, unit] = m.limit || [];
  const v = unit === "MB" ? m.bytes / 1e6 : unit === "orphaned share" ? m.orphaned_share || 0 : /per wiki|per journal|lines each/.test(unit || "") ? m.largest || 0 : m.count;
  return n ? [v, n, unit === "orphaned share" ? `${Math.round(100 * v)} % orphaned of ${Math.round(100 * n)} %` : `${nf(Math.round(v))} of ${nf(n)} ${unit}`] : null;
}
function memoryHtml() {
  const mem = S.memory, st = mem?.stores || [];
  if (!st.length) return `<div class="section-h section"><h2>Memory</h2>${how("knowledge")}</div><div class="card pad small muted">The memory inventory comes within the hour.</div>`;
  const row = (m) => {
    const u = m.error ? null : memUse(m), g = m.growth_7d, pct = u ? Math.min(100, (100 * u[0]) / u[1]) : 0;
    return `<div class="memrow"><div class="row between wrap" style="gap:6px"><b>${esc(m.name)}</b><span class="tag">${esc(MEM_KIND[m.kind] || m.kind)}</span></div>
      <div class="tiny muted wrap">${esc(m.holds)}</div>
      ${m.error ? "" : `<div class="small" style="margin-top:4px">${nf(m.count)} ${esc(m.count_label ? `${m.unit} in ${m.count_label}` : m.unit)} · ${fmtBytes(m.bytes)}${g ? ` · <span class="${g.count > 0 ? "warn-t" : "muted"}">${g.count >= 0 ? "+" : ""}${nf(g.count)} since ${esc(g.since)}</span>` : ""}</div>`}
      ${u ? `<div class="meter" title="${esc(u[2])}"><i style="width:${pct}%;${pct > 90 ? "background:var(--err)" : pct > 70 ? "background:var(--warn)" : ""}"></i></div><div class="tiny faint">${esc(u[2])}</div>` : ""}
      <div class="tiny faint wrap" style="margin-top:4px">Writes: ${esc(m.writes)} · Reads: ${esc(m.reads)}</div>
      <div class="tiny wrap ${m.curator || m.tidy ? "faint" : "warn-t"}">${m.tidy && !m.curator ? esc(m.tidy[0].toUpperCase() + m.tidy.slice(1)) : m.curator ? `Tidied by the ${esc(({ memory: "Librarian", checker: "Checker", curator: "skill curator", "wiki-curator": "wiki curator" })[m.curator] || m.curator)}${m.curated ? `, last ${rel(new Date((m.curated > 1e12 ? m.curated : m.curated * 1000)).toISOString())}` : ", not yet"}` : "Nobody tidies it yet"}</div>
      ${m.over_since ? `<div class="tiny warn-t wrap">Over its limit since ${day(m.over_since)}; after 8 days its curator gets an alert</div>` : ""}
      ${(m.problems || []).map((p) => `<div class="tiny err-t wrap">${ic.alert} ${esc(p)}</div>`).join("")}</div>`;
  };
  const bad = st.reduce((n, m) => n + (m.problems || []).length, 0);
  return `<div class="section-h section"><h2>Memory</h2>${how("knowledge")}</div>
    ${explain("every-memory-the-stack-k", `Every memory the stack keeps: what it is for, who writes and reads it, how big it is and who keeps it tidy · ${st.length} stores${bad ? ` · <span class="err-t">${bad} problem${bad > 1 ? "s" : ""}</span>` : ""} · as of ${rel(new Date(mem.at * 1000).toISOString())} (hourly)`, "About this")}
    <div class="card memlist">${st.map(row).join("")}</div>
    ${librarianHtml(mem.librarian)}`;
}

// MEM-08: the Librarian's last pass over the wikis and the search index (public/librarian.json, via memory.json)
const LIB_KIND = { "broken-link": ["broken link", "broken links"], orphan: ["page no other page links to", "pages no other page links to"], duplicate: ["possible duplicate", "possible duplicates"],
  contradiction: ["page with a marked contradiction", "pages with a marked contradiction"], stale: ["page not confirmed for 90 days", "pages not confirmed for 90 days"], "over-limit": ["over the page limit", "over the page limit"] };
function librarianHtml(lib) {
  if (!lib) return `<div class="card pad small muted" style="margin-top:10px"><b>The Librarian</b> tidies every wiki and the search index once a week (Wednesdays). Its first pass has not run yet.</div>`;
  const ws = lib.wikis || [], ix = lib.index || {}, h = lib.hubs || {};
  const n = (k) => ws.reduce((a, w) => a + (w[k] || []).length, 0);
  const wrow = (w) => {
    const kinds = {};
    (w.issues || []).forEach((i) => (kinds[i.kind] = (kinds[i.kind] || 0) + 1));
    const did = [["merged", "merged"], ["contradictions", "contradictions marked"], ["stale", "marked stale"]].filter(([k]) => (w[k] || []).length).map(([k, t]) => `${w[k].length} ${t}`);
    return `<div class="memrow"><div class="row between wrap" style="gap:6px"><b>${esc(w.title)}</b><span class="tiny faint">${nf(w.pages || 0)} pages</span></div>
      ${did.length ? `<div class="small">${esc(did.join(" · "))}</div>` : ""}
      <div class="tiny faint wrap">${Object.keys(kinds).length ? Object.entries(kinds).map(([k, c]) => `${c} ${esc((LIB_KIND[k] || [k, k])[c === 1 ? 0 : 1])}`).join(" · ") : "nothing to report"}${w.waits ? ` · ${nf(w.waits)} wait for the next pass` : ""}</div>
      ${(w.merged || []).map((x) => `<div class="tiny wrap">${ic.check} ${esc(x.drop)} merged into ${esc(x.keep)}: ${esc(x.why)}</div>`).join("")}
      ${(w.refused || []).map((x) => `<div class="tiny warn-t wrap">Kept apart ${esc(x.drop)} and ${esc(x.keep)}: ${esc(x.why)}</div>`).join("")}
      ${w.error || w.not_judged ? `<div class="tiny err-t wrap">${ic.alert} ${esc(w.error || `not judged: ${w.not_judged}`)}</div>` : ""}</div>`;
  };
  return `<div class="section-h section"><h2>The Librarian</h2><span class="tiny faint">last pass ${rel(new Date(lib.at * 1000).toISOString())} · ${nf(lib.seconds || 0)} s${lib.commit ? ` · vault commit ${esc(lib.commit)}` : " · nothing changed"}</span></div>
    ${explain("weekly-merges-duplicate-", `Weekly: merges duplicate pages, marks contradictions and stale pages, writes the hub pages that join the wikis, cleans the search index. It adds no facts, and everything it changes can be restored from the vault's history.
      ${n("merged")} merged · ${n("contradictions")} contradictions marked · ${n("stale")} marked stale · ${nf(h.hubs || 0)} hub pages${ix.before ? ` · search index: ${nf(ix.before.orphaned)} → ${nf(ix.after.orphaned)} orphaned chunks` : ix.error ? ` · <span class="err-t">search index cleanup failed: ${esc(ix.error)}</span>` : ""}`, "About this")}
    <div class="card memlist">${ws.map(wrow).join("")}</div>`;
}

// OBS-16: the one notification path: what goes where, quiet hours, and what it did lately (Stack → Notifications)
const NDOT = { sent: "ok", held: "warn", failed: "err" };
function notifyHtml(sy) {
  const n = S.notify || { prefs: { telegram: {}, push: {}, quiet: null }, categories: {}, recent: [] }, q = n.prefs.quiet;
  const box = (ch, c) => `<input type="checkbox" data-np="${ch}" data-cat="${esc(c)}" aria-label="${esc(ch)}: ${esc(c)}"${n.prefs[ch]?.[c] !== false ? " checked" : ""}${c === "approval" ? ` disabled title="Approvals always go out: they expire when nobody sees them"` : ""}>`;
  const name = (r) => r.title || (n.categories[r.category] || r.category).split(":")[0];
  return `<div class="card pad small">
    <div class="row"><span class="dot ok"></span>Telegram with buttons, and push to this app</div>
    <div class="row" style="margin-top:8px"><span class="dot ${sy.email_ready ? "ok" : "warn"}"></span>${sy.email_ready ? "E-mail ready" : "E-mail not set up: on the PC, run <code>make email-setup</code> once"}</div>
    <table class="ntable"><thead><tr><th>What</th><th>Telegram</th><th>Push</th></tr></thead><tbody>
      ${Object.entries(n.categories).map(([c, d]) => { const [what, ...more] = d.split(": "); return `<tr><td><b>${esc(what)}</b>${more.length ? `<div class="tiny faint">${esc(more.join(": "))}</div>` : ""}</td><td>${box("telegram", c)}</td><td>${box("push", c)}</td></tr>`; }).join("")}</tbody></table>
    <div class="nquiet"><label><input type="checkbox" id="nquiet"${q ? " checked" : ""}> Quiet hours from</label>
      <input class="input" type="time" id="nfrom" value="${esc(q?.from || "22:00")}"> <span>to</span> <input class="input" type="time" id="nto" value="${esc(q?.to || "07:00")}"></div>
    <div class="tiny faint" style="margin-top:6px">In quiet hours only approvals reach you; the Telegram messages wait and come as one message when they end.${n.quiet_now ? ` <b>Quiet hours now${n.held ? `: ${n.held} waiting` : ""}.</b>` : ""}</div>
    <div class="row" style="justify-content:flex-end;margin-top:10px"><button class="btn sm primary" id="nsave">${ic.check}Save</button></div>
  </div>
  <details class="card pad small nrecent" data-keep="nrecent" style="margin-top:10px"><summary>What the stack sent lately · ${n.recent.length}</summary>
    <div class="list">${n.recent.map((r) => `<div><span class="dot ${NDOT[r.decision] || ""}"></span><div class="grow"><div class="ttl">${esc(name(r))}</div><div class="sub">${esc(r.text || "")}</div></div>
      <div class="tiny faint" style="white-space:nowrap;text-align:right">${esc(r.channel)} · ${esc(r.decision)}<br>${rel(new Date(r.ts * 1000).toISOString())}</div></div>`).join("") || `<div class="muted small">Nothing sent yet</div>`}</div></details>`;
}

function bindNotify() {
  const save = $("#nsave");
  if (!save) return;
  save.onclick = async () => {
    const prefs = { telegram: {}, push: {}, quiet: $("#nquiet").checked ? { from: $("#nfrom").value, to: $("#nto").value } : null };
    $$("[data-np]").forEach((b) => (prefs[b.dataset.np][b.dataset.cat] = b.checked));
    save.disabled = true;
    await act({ action: "notify_prefs", prefs }, "Notification settings saved");
    save.disabled = false;
  };
}

// U1 (review 2026-10-30): the Stack page has 17 sections; one row of chips jumps to each
function fillJump() {
  const nav = $("#stackjump");
  if (!nav) return;
  const hs = [...view.querySelectorAll(".section-h h2")];
  nav.innerHTML = hs.map((h, i) => `<button type="button" class="chip" data-jump="${i}">${esc(h.textContent.replace(/\s*·\s*\d+$/, "").trim())}</button>`).join("");
  $$("[data-jump]", nav).forEach((b) => (b.onclick = () => hs[+b.dataset.jump].scrollIntoView({ behavior: "smooth", block: "start" })));
}

// the subscriptions' load: tokens in the last 5 hours (ChatGPT's usage window) and 24 hours, and whether one is at its
// limit now (a build or mission waiting on it, as the runner sees it) and until when
const SUB_WAIT = { ChatGPT: "ChatGPT", Claude: "Claude" };
function subLimit(eng) {
  const until = [...(S?.builds || []).filter((b) => b.status === "waiting" && (b.error || "").includes(SUB_WAIT[eng]) && b.retry_at).map((b) => b.retry_at),
    ...(eng === "ChatGPT" ? (S?.queue || []).filter((q) => q.status === "waiting").map((q) => q.retry_at || "") : [])].filter((x) => x === "" || Date.parse(x) > Date.now());
  return until.length ? until.sort().at(-1) || "soon" : null;
}
async function subsInto(box) {
  const u = await api("/api/usage").catch(() => null);
  if (!box.isConnected || !u) return;
  const rows = ["ChatGPT", "Claude"].map((eng) => ({ engine: eng, tokens_5h: 0, calls_5h: 0, tokens_24h: 0, calls_24h: 0, top: [], ...(u.find((x) => x.engine === eng) || {}) }));
  box.innerHTML = `<div class="card pad"><div class="row between wrap" style="gap:8px"><h2>Subscriptions</h2><span class="tiny faint">what they carried · ChatGPT counts its limit in 5-hour windows</span></div>
    <div class="list" style="margin-top:6px">${rows.map((r) => { const lim = subLimit(r.engine);
      return `<div><div class="ic ${lim ? "warn" : "ok"}">${lim ? ic.clock : ic.check}</div><div class="grow" style="min-width:0"><div class="ttl">${r.engine} <span class="pill ${lim ? "paused" : "ok"}" style="padding:1px 8px">${lim ? `at its limit${lim === "soon" ? "" : ` until ${clock(lim)}`}` : "available"}</span></div>
        <div class="sub wrap">${tok(r.tokens_5h)} tokens in the last 5 h (${nf(r.calls_5h)} calls) · ${tok(r.tokens_24h)} in 24 h${r.top.length ? ` · most: ${r.top.map(([a, n]) => `${esc(a === "claude" ? "Claude Code" : agentName(a) || a)} ${tok(n)}`).join(", ")}` : ""}</div></div></div>`; }).join("")}</div></div>`;
}

function vSystem() {
  const sy = S.system || {};
  const svc = sy.services || [];
  const down = svc.filter((s) => s.state !== "running");
  view.innerHTML = `
  <div class="hero stackhero"><div class="grow"><h1>Stack</h1><p>How your AI stack works, and how it is doing right now ·
    ${down.length ? `<b class="err-t">${down.length} service${down.length > 1 ? "s" : ""} not running</b>` : "all services running"} · ${sy.failed?.length ? `<b class="err-t">failed: ${sy.failed.map((u) => {                // which one, one tap to it (UX review 2026-10-30)
      const c = (S.crew || []).find((x) => `${x.unit}.service` === u);
      return c ? `<a class="err-t" href="#/crew/${encodeURIComponent(c.id)}">${esc(c.name)}</a>` : esc(u.replace(/\.service$/, ""));
    }).join(", ")}</b>` : "no errors"}</p></div></div>
  <nav class="jump" id="stackjump" aria-label="Sections of this page"></nav>
  <div class="section-h"><h2>Tools</h2><span class="tiny faint">every menu one tap away</span></div>
  <div id="toolsbox" style="margin-bottom:14px">${stackToolsHtml()}</div>
  ${S.phone ? `<a class="banner info" href="#/phone" style="margin-bottom:14px">${ic.bolt}<span class="grow"><b>AI phone</b> · ${S.phone.stopped ? "stopped" : S.phone.connected ? "connected" : "not connected"}${S.phone.pending ? ` · ${S.phone.pending} waiting for your OK` : ""}</span>${ic.next}</a>` : ""}
  ${S.house ? `<a class="banner info" href="#/house" style="margin-bottom:14px">${ic.house}<span class="grow"><b>House</b> · ${S.house.connected ? `${(S.house.things || []).length} things, ${(S.house.echos || []).length} Echos` : S.house.reachable ? "setup not finished" : "Home Assistant not reachable"}</span>${ic.next}</a>` : ""}
  ${a2aCardHtml()}
  <div id="subs" style="margin-bottom:14px"></div>
  <a class="banner info" href="#/telemetry" style="margin-bottom:14px">${ic.pulse}<span class="grow"><b>Telemetry</b> · how each agent did, day by day: runs, verdicts, tokens, time, cost if paid</span>${ic.next}</a>
  <div class="section-h"><h2>Connections</h2><span class="tiny faint">apps the agents may use, only while you allow it</span></div>
  <div id="conncard" class="stack" style="margin-bottom:14px"><div class="skeleton" style="height:90px"></div></div>
  <div class="wsearch gsearch">${ic.search}<input class="input" id="gq" placeholder="How do I…? Search the guide: triggers, memory, deploy…" value="${esc(guideQuery)}"></div>
  <div id="gresults"></div>
  ${(sy.pending_memory || []).length ? `<div class="section-h section"><h2>Waiting for you</h2>${how("knowledge")}</div>
    <div class="card list">${sy.pending_memory.map((p) => `<div style="flex-direction:column;gap:8px"><div class="row"><div class="ic warn">${ic.brain}</div><div class="grow small">${esc(p.text)}</div></div>
      <div class="row" style="justify-content:flex-end"><button class="btn sm ghost danger" data-mem="reject" data-id="${esc(p.id)}">${ic.x}Discard</button><button class="btn sm primary" data-mem="approve" data-id="${esc(p.id)}">${ic.check}Remember</button></div></div>`).join("")}</div>` : ""}
  ${startHereHtml()}
  <div class="section"><div class="section-h"><h2>How it fits together</h2><span class="tiny faint">live · tap a box to learn about it</span></div>
    <div class="card pad-l"><div class="glive" data-live="architecture"></div></div></div>
  <div class="section" id="learn">${learnHtml()}</div>
  ${stackTop(sy)}
  <div class="section-h section"><h2>Health and costs</h2>${how("safety")}</div>
  <div class="grid g2 g4">
    <div class="card kpi"><div class="kpi-l">Paid today</div><div class="kpi-v">${usd(sy.spend_today)}</div><div class="kpi-s">30 days: ${usd(sy.spend_30d)}</div></div>
    <div class="card kpi"><div class="kpi-l">Credit used</div><div class="kpi-v">${usd(sy.spend_total)}</div><div class="kpi-s">of $${nf(sy.budget_total || 10)}</div><div class="meter"><i style="width:${Math.min(100, ((sy.spend_total || 0) / (sy.budget_total || 10)) * 100).toFixed(1)}%"></i></div></div>
    <div class="card kpi"><div class="kpi-l">Long-term memory</div><div class="kpi-v">${nf(sy.memory?.facts)}</div><div class="kpi-s">facts · ${nf(sy.memory?.observations)} observations</div></div>
    <div class="card kpi"><div class="kpi-l">Last backup</div><div class="kpi-v" style="font-size:20px">${sy.backup ? rel(new Date(sy.backup.ts * 1000).toISOString()) : "–"}</div><div class="kpi-s">${sy.drill ? "restore test: " + esc(sy.drill.result) : ""}</div></div>
  </div>
  ${memoryHtml()}
  <div class="split section">
    <div>
      <div class="section-h"><h2>Agents today</h2>${how("technology")}</div>
      <div class="card list">${(sy.agents_today || []).map((a) => { const max = Math.max(...sy.agents_today.map((x) => x.tokens)) || 1; return `<div style="align-items:center"><span class="agent ${esc(a.agent)}">${esc(a.agent)}</span><div class="grow"><div class="meter" style="margin:0"><i style="width:${((a.tokens / max) * 100).toFixed(1)}%"></i></div></div><div class="small num" style="min-width:110px;text-align:right">${nf(a.calls)} · ${tok(a.tokens)}</div></div>`; }).join("") || `<div class="muted small">No calls today</div>`}</div>
      <div class="section-h section"><h2>Services</h2>${how("stack-page")}</div>
      <div class="card grid g2" style="gap:0">${svc.map((s) => `<div class="svc"><span class="dot ${s.state === "running" ? (/unhealthy/.test(s.status) ? "warn" : "ok") : "err"}"></span><span class="n">${esc(s.name)}</span><span class="tiny faint">${esc(s.status.replace(/^Up /, "").replace(/ \(healthy\)/, ""))}</span></div>`).join("")}</div>
    </div>
    <div>
      <div class="section-h"><h2>Scheduled jobs</h2>${how("stack-page")}</div>
      <div class="card list">${(sy.timers || []).map((t) => { const failed = (sy.failed || []).some((f) => f.startsWith(t.unit + ".")); return `<div><div class="ic ${failed ? "err" : ""}">${failed ? ic.alert : ic.clock}</div><div class="grow"><div class="ttl">${esc((S.crew || []).find((c) => c.unit === t.unit)?.name || t.unit)}</div><div class="sub">last ${t.last ? rel(new Date(t.last / 1000).toISOString()) : "–"}</div></div><div class="tiny faint" style="white-space:nowrap">${t.next ? rel(new Date(t.next / 1000).toISOString()) : "–"}</div></div>`; }).join("")}</div>
      <div class="section-h section"><h2>Notifications</h2>${how("delivery")}</div>
      ${notifyHtml(sy)}
      <div class="section-h section"><h2>This device</h2>${how("first-ten-minutes")}</div>
      <div class="card pad" id="device"></div>
    </div>
  </div>`;
  subsInto($("#subs"));
  fillJump();
  bindA2a();                                            // TSK-19: outside agents
  bindStackTools();
  if (!TOOLS) toolsLoad().then(() => { const b = $("#toolsbox"); if (b) { b.innerHTML = stackToolsHtml(); bindStackTools(); } });
  bindStack();
  bindLearn();
  fillLive();
  $$("[data-mem]").forEach((b) => (b.onclick = async () => { b.disabled = true; await act({ action: "memory", id: b.dataset.id, decision: b.dataset.mem }, b.dataset.mem === "approve" ? "Remembered: Hermes knows it from the next chat" : "Discarded: it is not remembered"); }));
  deviceCard();
  bindNotify();
  if (scrollToLearn) { scrollToLearn = false; setTimeout(() => $("#learn")?.scrollIntoView({ block: "start" }), 30); }
}

async function deviceCard() {
  const el = $("#device");
  if (!el) return;
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const ios = /iphone|ipad/i.test(navigator.userAgent);
  let sub = null;
  const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.ready.catch(() => null) : null;
  if (reg && "pushManager" in reg) sub = await reg.pushManager.getSubscription().catch(() => null);
  const canPush = reg && "PushManager" in window && (!ios || standalone);
  el.innerHTML = `
    ${standalone ? `<div class="row small"><span class="dot ok"></span>Installed as an app</div>` : `<div class="small muted">${ios ? "Install: Share → “Add to Home Screen”." : "Install: browser menu → “Install app” / “Add to Home screen”."}</div>`}
    <label class="switch" style="margin-top:6px"><span><b>Push notifications</b><div class="small muted">${canPush ? "Finished runs, events, errors, new missions" : ios ? "On iPhone only after installing the app" : "Not supported by this browser"}</div></span><input type="checkbox" id="pushsw" ${sub ? "checked" : ""} ${canPush ? "" : "disabled"}></label>
    ${sub ? `<button class="btn sm" id="pushtest" style="margin-top:4px">${ic.bell}Send a test</button>` : ""}`;
  const sw = $("#pushsw");
  if (sw) sw.onchange = async () => {
    try {
      if (sw.checked) {
        if ((await Notification.requestPermission()) !== "granted") { sw.checked = false; return toast("Notifications not allowed", true); }
        const { key } = await api("/api/push/key");
        const pad = "=".repeat((4 - (key.length % 4)) % 4), raw = atob((key + pad).replace(/-/g, "+").replace(/_/g, "/"));
        const s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: Uint8Array.from(raw, (c) => c.charCodeAt(0)) });
        await api("/api/push/subscribe", { method: "POST", body: JSON.stringify(s.toJSON()) });
        toast("Push on");
      } else {
        const s = await reg.pushManager.getSubscription();
        if (s) { await api("/api/push/unsubscribe", { method: "POST", body: JSON.stringify(s.toJSON()) }); await s.unsubscribe(); }
        toast("Push off");
      }
    } catch (e) { sw.checked = !sw.checked; toast("Push: " + e.message, true); }
    deviceCard();
  };
  const t = $("#pushtest");
  if (t) t.onclick = async () => { await api("/api/push/test", { method: "POST" }); toast("Test sent"); };
}

// ---------- live data ----------
function onState(s) {
  const wasRunning = S?.running?.id, first = !S;
  S = s;
  lastState = Date.now();
  if (first && ["mission", "chat", "wiki", "new", "system", "build", "repo", "guide", "crew", "house", "tasks"].includes(route.name)) return render(true);
  if (route.name === "tasks" && !first) { tasksUpdate(); chrome(); return; }
  if (first && route.name === "swarm" && ["improve", "agents"].includes(swTab)) return render(true);   // FND-36: they read S
  if (route.name === "house" && !first) { houseUpdate(); chrome(); return; }
  if (route.name === "guide") { guideOnState(); chrome(); return; }
  if (route.name === "home" && !first && $("#homefeed")) { homeUpdate(); chrome(); return; }
  if (route.name === "system" && $("#rescard") && !first) { $("#rescard").innerHTML = resourcesHtml(S.resources); guideOnState(); chrome(); return; }
  if (wasRunning && S.running?.id === wasRunning && $("#livelog") && (route.name === "home" || (route.name === "mission" && tab === "overview"))) {
    $("#livelog").textContent = (S.running.tail || []).join("\n") || "Starting…";        // update in place, no flicker
    const st = $(".runcard .steps"); if (st && S.running.steps) st.outerHTML = stepsHtml(S.running.steps);
    chrome(); return;
  }
  render();
}
// ---------- no connection: say why instead of loading forever (the shell itself comes from the phone's cache) ----------
const bootAt = Date.now();
let lastState = 0;
const noLink = () => !S && Date.now() - bootAt > 8000;
function offlineHtml() {
  return `<div class="card pad-l" id="offline"><h2>Can't reach your AI stack</h2>
    <div class="small" style="margin-top:8px;line-height:1.6">This device gets no answer from the PC. Usually <b>Tailscale is off on this device</b>: open the Tailscale app and switch it on. Otherwise the PC is asleep or off.</div>
    <div class="small muted" style="margin-top:8px">This page connects by itself as soon as it can.</div></div>`;
}
setInterval(() => { if (noLink() && !$("#offline") && $("#view .skeleton")) render(true); chrome(); }, 4000);

function connect() {
  let es;
  try { es = new EventSource("/api/stream"); } catch (_) { return poll(); }
  es.onmessage = (e) => { try { onState(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => { es.close(); setTimeout(connect, 4000); poll(true); };
}
async function poll(once) {
  try { onState(await api("/api/state")); } catch (_) {}
  if (!once) setTimeout(poll, 5000);
}
setInterval(() => $$("[data-since]").forEach((el) => {
  const s = Math.max(0, (Date.now() - new Date(el.dataset.since)) / 1000);
  el.textContent = `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}), 1000);

// ---------- updates: an open app (an installed one stays open for days) notices a new version and reloads itself ----------
let bootVersion = null, updateReady = false;
async function checkVersion() {
  try {
    const { version } = await api("/api/version");
    if (!bootVersion) bootVersion = version;
    else if (version !== bootVersion && !updateReady) {
      updateReady = true;                                 // the next screen change loads the new version
      navigator.serviceWorker?.getRegistration().then((r) => r?.update()).catch(() => {});
      if (document.hidden || (!typing() && !streaming && route.name !== "new")) return location.reload();
      chrome();
    }
  } catch (_) {}
}
setInterval(checkVersion, 60000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) checkVersion(); });
checkVersion();

parseRoute();
render(true);
connect();
loadGuide().then(() => { chrome(); const l = $("#learn"); if (l) { l.innerHTML = learnHtml(); bindLearn(); } });   // chapters: each page's "How this page works", Stack page
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
