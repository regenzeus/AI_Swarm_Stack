// Mission Control front end: one small vanilla-JS app. State comes live from /api/stream (the runner's state.json);
// actions go to /api/request, which the host runner validates and executes. Chats and wikis come from their own APIs.
"use strict";

// This deployment's addresses: the server puts them into the page (deployments/<name>/deployment.env, index.html)
const DEPLOY = window.DEPLOY || {};

// a script error on a phone is invisible from the PC: report it to the server log (docker logs mission-control)
let errSent = 0;
// a cut that shows itself, like textcap.cut (AGENTS.md, truncation): how many characters follow
// a list that shows part of itself says how many more there are (AGENTS.md, truncation)
// MEM-21: what the Memory Keeper changed (each with its Undo), whether its trial lets it, and the wikis' disputes
const KEEPER_CLASS = { duplicate: "duplicate retired", test_noise: "test noise retired", agent_run: "an agent's run retired", not_english: "put into English", passing_state: "dated as passed",
  superseded: "dated: a newer fact of yours says otherwise", moved_to_wiki: "not about you: moved to the wikis",
  merged: "now holds the details of a newer copy" };
// MEM-42, MEM-43: what else the memory agent did: the nightly trials, the facts it moved, the week's skill, every write with its Undo
function memAgentHtml(c) {
  const ws = c.writes || [], t = c.trials || {}, mv = c.moved || {}, sk = (c.distiller || {}).skill;
  const row = (w) => `<li><div class="small quote">${esc(w.candidate?.text || w.where || "")}</div><div class="row between wrap" style="gap:6px"><span class="tiny muted">${esc(OUTCOME_WORD[w.outcome] || w.outcome)}${w.where ? ` → ${esc(w.where)}` : ""}${w.why ? ` · ${esc(w.why)}` : ""} · ${rel(Date.parse(w.at) / 1000)}</span>${w.undone ? `<span class="tiny muted">undone</span>` : w.undo && ["lesson", "file", "line"].includes(w.undo.kind) ? `<button class="btn sm ghost" data-wundo="${esc(w.id)}">Undo</button>` : ""}</div></li>`;
  const trialWord = (k) => (t[k] === true ? "passed" : t[k] === false ? "failed" : t[k] === null ? "could not run" : null);
  return `<div class="card pad-l crews" style="margin-bottom:12px"><h2>What entered memory, and the memory agent's other work</h2>
    <div class="tiny muted" style="margin-top:4px">${["coverage", "continuity", "recall"].filter((k) => trialWord(k)).map((k) => `${k} trial ${trialWord(k)}`).join(" · ") || "The trials run with its next night."}${mv.moved ? ` · ${nf(mv.moved)} facts moved out of long-term memory` : mv.waits ? ` · moves wait: ${esc(mv.waits)}` : ""}${sk ? ` · this week's skill: ${esc(sk.decision || sk.why || sk.error || "")}` : ""}</div>
    ${ws.length ? `<ul class="crewf">${ws.map(row).join("")}</ul>${moreOf(c.writes_total, ws.length)}` : `<div class="tiny muted" style="margin-top:6px">Nothing has entered memory through a note or a result yet.</div>`}</div>`;
}
function keeperHtml(k) {
  const ch = k.changes || [], d = k.disputes || {};
  const row = (e) => `<li><div class="small quote">${esc(e.fact || "")}</div><div class="row between wrap" style="gap:6px"><span class="tiny muted">${esc(KEEPER_CLASS[e.class] || e.class)}${e.after?.text ? ` → “${esc(e.after.text)}”` : ""}${e.after?.occurred_end ? ` (held until ${esc(e.after.occurred_end)})` : ""} · ${esc(e.why || "")} · ${rel(Date.parse(e.at) / 1000)}</span>${e.undone ? `<span class="tiny muted">undone</span>` : `<button class="btn sm ghost" data-kundo="${esc(e.id)}">Undo</button>`}</div></li>`;
  return `<div class="card pad-l crews" style="margin-bottom:12px"><h2>What the Memory Keeper changed</h2>
    <div class="tiny ${k.gate?.open ? "muted" : "warn-t"}" style="margin-top:4px">${k.gate?.open ? "It fixes duplicates, test noise, agents' runs, other languages, passed states and your facts that a newer one overrides itself: " : "It only suggests, it changes nothing itself: "}${esc(k.gate?.why || "")}</div>
    ${d.open !== undefined ? `<div class="tiny muted">Wiki disputes: ${nf(d.open)} open · ${nf((d.tasks || []).length)} being researched${d.settled ? ` · ${nf(d.settled)} settled` : ""}${d.asked ? ` · ${nf(d.asked)} its research could not settle, left marked on both pages` : ""}</div>` : ""}
    ${ch.length ? `<ul class="crewf">${ch.map(row).join("")}</ul>${moreOf(k.changes_total, ch.length)}` : `<div class="tiny muted" style="margin-top:6px">No change yet.</div>`}
    <div class="tiny faint">Nothing is deleted: a retired fact stays in the archive, a rewritten one keeps its old text here.</div></div>`;
}
// APP-57: a name, whole: the first sentence of its first line (every page's scripts load this file)
const firstSentence = (s) => { const t = String(s || "").trim().split("\n").find((x) => x.trim()) || ""; const m = /^(.+?[.!?])(\s|$)/.exec(t.trim()); return (m ? m[1] : t).trim(); };
// APP-61: the app's name, the deployment's
const APPNAME = () => (typeof DEPLOY === "object" && DEPLOY.APP_NAME) || "AI Stack";
function moreOf(total, shown) { return total > shown ? `<div class="tiny muted">… and ${nf(total - shown)} more</div>` : ""; }
function clipped(s, n) { s = String(s ?? ""); return s.length <= n ? s : `${s.slice(0, n)} [… ${nf(s.length - n)} more characters cut]`; }   /* cap: preview: the helper */
function reportError(msg, where) {
  if (errSent++ > 5) return;
  try { navigator.sendBeacon("/api/clienterror", JSON.stringify({ msg: clipped(String(msg), 500) /* cap: untrusted */, where: clipped(String(where || ""), 300) /* cap: untrusted */, url: location.hash, ua: navigator.userAgent })); } catch (_) {}
}
// An error is reported to the server and told to the owner too: a broken "Start mission" once only showed its spinner (FND-52)
const toldError = (msg) => { try { toast(`Something went wrong in the app: ${msg}. It is reported; reload the page and try again.`, true); } catch (_) {} };
window.addEventListener("error", (e) => { reportError(e.message, `${e.filename}:${e.lineno}:${e.colno}`); toldError(e.message); });
window.addEventListener("unhandledrejection", (e) => { reportError(e.reason?.message || e.reason, e.reason?.stack?.split("\n")[1]); toldError(e.reason?.message || e.reason); });

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// A link built from data (a shop page, a feed item, a source an agent read) opens only as a web page: a javascript: or
// data: link would run in this app with the owner's rights (review APP-R3). esc() still goes around it.
const safeUrl = (u) => (/^https?:\/\//i.test(String(u ?? "").trim()) ? String(u).trim() : "#");
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
  tasks: I('<path d="M4 6.5l2 2 3.5-4"/><path d="M13 7h7"/><path d="M4 16.5l2 2 3.5-4"/><path d="M13 17h7"/>'),
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
  flow: I('<circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M7 6h10M6 8l5 8m13-8-5 8"/>'),
  radar: I('<circle cx="12" cy="12" r="9"/><path d="M12 12 18 6"/><circle cx="12" cy="12" r="4"/>'),
  search: I('<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>'),
  list: I('<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>'),
  history: I('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>'),
  code: I('<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16"/>'),
  tune: I('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
  menu: I('<path d="M4 7h16M4 12h10M4 17h16"/>'),
  more: I('<circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/>'),
  copy: I('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4V6a2 2 0 0 1 2-2h9v1"/>'),
  edit: I('<path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19Z"/>'),
  image: I('<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M21 16l-5-5L6 20"/>'),
  camera: I('<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z"/><circle cx="12" cy="13.5" r="3.5"/>'),
  paste: I('<rect x="6" y="5" width="12" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/>'),
  up: I('<path d="M12 19V6M6 12l6-6 6 6"/>'),
  down: I('<path d="M12 5v13M6 12l6 6 6-6"/>'),
  stop: I('<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/>'),
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
// an agent's own sentence (an idea's signal, a crew finding): escaped, a timestamp in it shown the app's way, a passage it quotes
// marked as a quote (overnight journeys, 8 Nov 2026: "2026-11-02T15:19" and a quoted "undefined" read as the app's own words)
const ISO_IN_TEXT = /\b(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?/g;
const prose = (text) => esc(String(text ?? "")).replace(ISO_IN_TEXT, (m, d, t, z) => dt(z ? m : `${d}T${t}`)).replace(/“([^”]{1,400})”/g, '<q class="quote">$1</q>');
const fmtMs = (ms) => (ms == null ? "" : ms >= 60000 ? `${Math.floor(ms / 60000)}m${String(Math.round((ms % 60000) / 1000)).padStart(2, "0")}s` : ms >= 1000 ? `${nf(ms / 1000, 1)} s` : `${ms} ms`);
const fsize = (n) => (n >= 1e9 ? `${nf(n / 1e9, n % 1e9 ? 1 : 0)} GB` : n >= 1e6 ? `${nf(n / 1e6, 1)} MB` : n >= 1e3 ? `${nf(n / 1e3)} KB` : `${nf(n)} B`);   // a file's size (MIS-23)
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
    throw e.name === "AbortError" ? new Error(`${APPNAME()} did not answer within ${Math.round(timeout / 1000)} s`) : e;
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
    catch (e) { if (++misses >= 10) { toast(`Lost contact with ${APPNAME()}: ${e.message}. The request may still finish; check again in a minute.`, true); return null; } }
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
  const rs = runs.slice(0, 20).reverse();   /* cap: list: the 20 newest runs as bars; the run list has every one */
  if (!rs.length) return `<div class="small muted">No runs yet: each one shows here as a bar.</div>`;
  const W = 600, H = 120, max = Math.max(...rs.map((r) => r.tokens || 0)) || 1, bw = W / rs.length;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${rs.map((r, i) => {
    const bh = Math.max(3, ((r.tokens || 0) / max) * (H - 8));
    const col = r.status === "failed" ? "var(--err)" : r.event ? "var(--warn)" : r.status === "ok" ? "url(#bg)" : "var(--faint)";
    return `<rect x="${i * bw + bw * 0.18}" y="${H - bh}" width="${bw * 0.64}" height="${bh}" rx="3" fill="${col}"><title>${esc(dt(r.started))}: ${tok(r.tokens)} tokens, ${r.calls || 0} calls</title></rect>`;
  }).join("")}<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)"/><stop offset="1" stop-color="var(--accent-2)"/></linearGradient></defs></svg>`;
}

// ---------- navigation ----------
// one navigation on every screen (no top bar): the agents' views live under Tasks (DEC-46), the live state is a dot on Stack
// the Memory tab's parts (APP-50); the wikis keep their route
const MEM_ROUTES = ["memory", "howto", "longterm", "codemem", "skills", "journals", "memsearch", "sources"];
const NAV = [["home", "#/", "Home", ic.home], ["tasks", "#/tasks", "Tasks", ic.tasks], ["wiki", "#/memory", "Memory", ic.wiki], ["build", "#/build", "Code", ic.code],
  ["chat", "#/chat", "Chat", ic.chat], ["workflows", "#/workflows", "Workflows", ic.flow], ["system", "#/system", "Stack", ic.layers]];
function navHtml(bottom) {
  const pend = S?.system?.pending_memory?.length || 0;
  return NAV.map(([k, href, label, icon]) => {
    if (k === "workflows" && bottom) return "";       // WFL-11: n8n inside the app is the desk's; a phone reaches the list from Tasks and the pages
    const on = route.name === k || (k === "home" && route.name === "decide")
      || (k === "tasks" && ["task", "taskmap", "mission", "crew", "new", "swarm", "missions", "telemetry", "trials"].includes(route.name)) || (k === "system" && ["mail", "guide"].includes(route.name)) || (k === "wiki" && MEM_ROUTES.includes(route.name)) || (k === "build" && route.name === "repo");
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
  if (cd && chip) { cd.className = chip.className + " chatchip"; cd.innerHTML = chip.innerHTML; cd.title = chip.title; cd.onclick = chip.onclick; cd.hidden = !updateReady && liveState() !== "off"; }   // APP-45: said only while something is off; the Stack tab's dot has the rest
}
// ok (Ready), run (an agent works), off (connecting, offline, no link): the dot on Stack and the sidebar's foot
const liveState = () => (!S || !S.generated || Date.now() - lastState > 60000 ? "off" : S.running ? "run" : "ok");   // the app answers, but no runner ever wrote: not connected
const notConnected = () => liveState() === "off";           // then "all quiet" and "nothing needs you" would be guesses
function footState() {                                       // the rail's foot: the one place that always says how the stack is
  const st = liveState(), word = st === "off" ? (S || noLink() ? "Not connected" : "Connecting…") : S.running ? "Running" : "Ready";
  const f = $("#side-foot");
  if (f) f.innerHTML = `<span class="dot ${st === "off" ? "err" : st}"></span><b>${word}</b><span class="when">${S?.generated ? `updated ${clock(S.generated, true)}` : "no data yet"}</span>`;
}
function liveChip(chip) {
  footState();
  const bar = $("#livebar");                                // shown only when something is off: an update, no link, offline
  if (bar) bar.hidden = !updateReady && liveState() !== "off";
  chip.onclick = updateReady ? () => location.reload() : null;
  if (updateReady) { chip.className = "chip live upd"; chip.innerHTML = `${ic.repeat}Update ready · tap`; return; }
  if (!S) { chip.innerHTML = noLink() ? `<span class="dot err"></span>No connection` : `<span class="dot"></span>Connecting…`; chip.className = "chip"; return; }
  if (!S.generated) { chip.className = "chip"; chip.innerHTML = `<span class="dot err"></span>Not connected · the runner has written nothing here`; return; }
  if (Date.now() - lastState > 60000) { chip.className = "chip"; chip.innerHTML = `<span class="dot err"></span>Not connected${S.generated ? ` · last update ${clock(S.generated)}` : " · no data yet"}`; return; }
  if (S.running) { chip.className = "chip live"; chip.title = S.running.title; chip.innerHTML = `<span class="dot run"></span>Running`; }   // a title does not fit the header: Home's Now has it whole
  else { chip.className = "chip"; chip.title = ""; chip.innerHTML = `<span class="dot ok"></span>Ready`; }
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
  const prev = route.name + route.args[0]; parseRoute(); if (route.name + route.args[0] !== prev) { tab = "overview"; atab = "now"; } if (route.name !== "wiki") wikiBack = "";
  if (route.name + route.args[0] !== prev || !repoTabSwitch()) render(true);   // a tab of the same repo page redraws nothing
  countView();
});
// PLT-26: which screens are opened, counted per day for the monthly unused report: the route's name and tab only (no
// address, no ids). The automated browser (the nightly route check opens every screen) is not counted.
function countView() {
  if (navigator.webdriver) return;
  try { navigator.sendBeacon("/api/view", JSON.stringify({ name: route.name, tab: route.q.get("tab") || "" })); } catch (_) {}
}

// views that re-render on every state update (forms, chat and wiki do not, so nothing is lost while you work)
const LIVE = new Set(["home", "decide", "engine"]);
const typing = () => document.activeElement && ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
function render(force = false) {
  chrome();
  if (!force && route.name === "live") return;
  if (!force && route.name === "repo") return repoLive();
  if (!force && !(LIVE.has(route.name) || (route.name === "files" && !$("#fplan")?.innerHTML && !typing()) || ((route.name === "mission" || route.name === "crew") && agentSigOf() !== agentSig && !typing() && !$(".tl:not([hidden])") && !$("#tabbody details[open]")) || (route.name === "build" && !typing() && !$("#chbox:not([hidden])") && !$("#view details[open]") && !$("#blogbox:not([hidden])") && !$("#nb:not([hidden])") && !$("#addrepo:not([hidden])")))) return;
  // views that load their own data draw at once; the others wait for the first state (they are drawn when it comes)
  if (!S && !["missions", "new", "mail", "chat", "wiki", "read", "guide", "phone", "share", "live", "swarm", "skills", "memory", "howto", "longterm", "codemem", "journals", "memsearch", "sources", "taskmap", "telemetry", "task", "trials", "workflows"].includes(route.name)) { view.innerHTML = noLink() ? offlineHtml() : `<div class="stack"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>`; return; }
  const y = window.scrollY;
  if (force) { document.body.classList.add("anim"); clearTimeout(render.anim); render.anim = setTimeout(() => document.body.classList.remove("anim"), 600); }
  const open = force ? [] : [...view.querySelectorAll("details[open][id], details[open][data-keep]")].map((d) => d.id || d.dataset.keep);
  document.body.dataset.page = route.name;          // APP-56: the stylesheet lays each page out for the width it has
  const fn = { mail: vMail, decide: vDecide, tasks: vTasks, task: vTask, trials: vTrials, home: vHome, missions: vMissionsGo, mission: vMission, new: vNewGo, chat: vChat, system: vSystem, read: vRead, file: vFile, files: vFiles, wiki: vWiki, build: vBuild, repo: vRepo, guide: vGuide, share: vShare, phone: vPhone, house: vHouse, crew: vCrew, live: vLive, swarm: vSwarm, skills: vSkills, memory: vMemory, howto: vHowto, longterm: vLongTerm, codemem: vCodeMem, journals: vJournals, memsearch: vMemSearch, sources: vSources, taskmap: vTaskMap, telemetry: vTelemetry, engine: vEngine, templates: vTemplates, packs: vPacks, trackers: vTrackers, runs: vRuns, workflows: vWorkflows }[route.name] || vHome;
  if (force) {                                      // a page that loads for a moment: not the page you left under the new tab's name
    const was = view.firstChild, n = (render.nav = (render.nav || 0) + 1);
    setTimeout(() => { if (render.nav === n && view.firstChild === was) view.innerHTML = `<div class="stack"><div class="skeleton" style="height:96px"></div><div class="skeleton" style="height:280px"></div></div>`; }, 180);
  }
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

// ---------- home ----------
function workBuildRow(b) {
  const cls = bcls(b.status), review = b.ai_review;
  const verdict = !review ? "Not done" : review.pending ? "Reviewing" : review.error ? "Unavailable" : VERDICT[review.verdict]?.[1] || "Not done";
  return `<a href="#/build/${b.id}"><div class="ic ${cls === "running" ? "run" : ""}">${b.status === "review" ? ic.search : ic.rocket}</div>
    <div class="grow small"><span class="ttl">#${b.id} ${esc(b.title)}</span> · <span class="pill ${cls}" style="padding:1px 7px">${BSTATUS[b.status] || b.status}</span>${b.status === "review" ? ` · Checks: ${b.checks ? (b.checks_ok ? "Passed" : "Failed") : "Not run yet"} · CI: ${esc(b.ci || "Not pushed yet")} · AI review: ${esc(verdict)}` : ""}</div></a>`;
}

// ---------- your mail: the copy on the NAS and the sender report, from headers only (CNX-07, CNX-08) ----------
let mailData = null, mailFilter = "all", mailShown = 100, mailFind = "";
const MAIL_FILTERS = [["all", "All senders"], ["bulk", "Mailing lists you never answer"], ["people", "People you write to"], ["big", "Biggest"], ["protected", "Banks and security"]];
function mailRows() {
  let rows = mailData?.census?.senders || [];
  const q = mailFind.trim().toLowerCase();
  if (q) rows = rows.filter((r) => `${r.name} ${r.addr}`.toLowerCase().includes(q));
  if (mailFilter === "bulk") rows = rows.filter((r) => r.list > 0 && !r.wrote_to && !r.protected && !r.starred);
  if (mailFilter === "people") rows = rows.filter((r) => r.wrote_to > 0);
  if (mailFilter === "protected") rows = rows.filter((r) => r.protected);
  if (mailFilter === "big") rows = [...rows].sort((a, b) => b.bytes - a.bytes);
  return rows;
}
const mailMb = (n) => gb(n || 0);
function mailCopyHtml(st) {
  if (!st) return `<div class="small muted">The copy on the NAS has not reported yet.</div>`;
  if (st.state === "waiting") return `<div class="small">It waits for its app password: <code>make mailvault-password</code> on the PC.</div>`;
  const left = Math.max(0, (st.total_bytes || 0) - (st.copied_bytes || 0)), days = Math.ceil(left / (st.daily_bytes || 2e9));
  const pct = st.total ? Math.floor((100 * st.copied) / st.total) : 0;
  return `<div class="kpi-v" style="font-size:20px">${pct} %</div><div class="small muted wrap">${nf(st.copied)} of ${nf(st.total)} mails, ${mailMb(st.copied_bytes)} of ${mailMb(st.total_bytes)}${left ? ` · about ${days} day${days === 1 ? "" : "s"} to go` : ""} · ${rel(new Date(st.at * 1000).toISOString())}</div>
    ${st.state === "failed" ? `<div class="small err-t wrap" style="margin-top:6px">${esc(st.why || "It stopped.")}</div>` : ""}${st.gone ? `<div class="tiny muted" style="margin-top:6px">${nf(st.gone)} have left Gmail and stay here.</div>` : ""}`;
}
function mailListHtml() {
  const rows = mailRows(), shown = rows.slice(0, mailShown);  /* cap: list */
  const total = rows.reduce((a, r) => a + r.n, 0);
  return `<div class="tiny muted" style="margin-bottom:8px">${nf(rows.length)} sender${rows.length === 1 ? "" : "s"} · ${nf(total)} mails</div>
    <div class="card list">${shown.map((r) => `<div class="mailrow"><div class="grow wrap"><b>${esc(r.name || r.addr)}</b><div class="tiny muted wrap">${esc(r.addr)}</div>
      <div class="tiny faint wrap">${nf(r.unread)} unread · ${mailMb(r.bytes)} · last ${r.last ? rel(new Date(r.last * 1000).toISOString()) : "unknown"}${r.list ? " · mailing list" : ""}${r.wrote_to ? ` · you wrote ${nf(r.wrote_to)}` : ""}${r.protected ? " · protected" : ""}</div></div><div class="kpi-v" style="font-size:18px">${nf(r.n)}</div></div>`).join("") || `<div class="muted small">No sender here.</div>`}</div>
    ${rows.length > shown.length ? `<button class="btn" id="mailmore" style="margin-top:10px">Show ${nf(Math.min(100, rows.length - shown.length))} more of ${nf(rows.length - shown.length)}</button>` : ""}`;
}
function bindMail() {
  $$("[data-mf]").forEach((b) => (b.onclick = () => { mailFilter = b.dataset.mf; mailShown = 100; $$("[data-mf]").forEach((x) => x.classList.toggle("on", x === b)); $("#maillist").innerHTML = mailListHtml(); bindMailMore(); }));
  const f = $("#mailfind");
  if (f) f.oninput = () => { mailFind = f.value; mailShown = 100; $("#maillist").innerHTML = mailListHtml(); bindMailMore(); };
  bindMailMore();
}
function bindMailMore() {
  const m = $("#mailmore");
  if (m) m.onclick = () => { mailShown += 100; $("#maillist").innerHTML = mailListHtml(); bindMailMore(); };
}
async function vMail() {
  view.innerHTML = `<a class="back" href="#/system?conn=1">${ic.back}Connections</a><h1 style="font-size:26px">Your mail</h1><div class="skeleton" style="height:200px;margin-top:14px"></div>`;
  let got, why = "";
  try { got = await api("/api/mail"); } catch (e) { why = e.message; }
  if (route.name !== "mail") return;                          // FND-95: you moved on while it loaded
  if (!got) { view.innerHTML = `<a class="back" href="#/system?conn=1">${ic.back}Connections</a><div class="card empty">${esc(why)}</div>`; return; }
  mailData = got;
  const p = mailData.postmaster || {}, c = mailData.census;
  view.innerHTML = `<a class="back" href="#/system?conn=1">${ic.back}Connections</a><div class="row between"><h1 style="font-size:26px">Your mail</h1>${explain("this-page-is-made-from", "This page is made from the headers of your mail: who wrote, how much, whether you read it, whether you answer. No message text is read, and nothing here changes Gmail. The copy on the NAS only reads Gmail and keeps a mail even after it leaves Gmail.", "About this")}</div>
    <div class="grid g2 section"><div class="card kpi"><div class="kpi-l">Copy on the NAS</div>${mailCopyHtml(mailData.status)}</div>
      <div class="card kpi"><div class="kpi-l">AI Stack label</div><div class="kpi-v" style="font-size:20px">${nf(p.total_filed || 0)}</div><div class="kpi-s wrap">${esc(p.result || "The Postmaster has not run yet.")}</div></div></div>
    <div class="section"><div class="section-h"><h2>Who writes to you</h2></div>${c ? `
      <input id="mailfind" class="input" placeholder="Find a sender" value="${esc(mailFind)}" style="width:100%;margin-bottom:10px">
      <div class="row wrap" style="gap:6px;margin-bottom:10px">${MAIL_FILTERS.map(([k, t]) => `<button class="chip ${mailFilter === k ? "on" : ""}" data-mf="${k}">${t}</button>`).join("")}</div>
      <div id="maillist">${mailListHtml()}</div>` : `<div class="card empty small">The report appears when the copy has read the headers.</div>`}</div>`;
  bindMail();
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
    <div class="small muted" style="margin-top:8px">Most from: ${(p.top_senders || []).slice(0, 5).map(([f, n]) => `${esc(f)} (${n})`).join(", ")}${(p.top_senders || []).length > 5 ? `, and ${nf(p.top_senders.length - 5)} more senders` : ""}</div>
    <ul class="small" style="margin:6px 0 0 16px">${(p.sample || []).slice(0, 10).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>${moreOf((p.sample || []).length, 10)}
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
      ${c.id === "gmail" ? `<a class="btn sm" href="#/mail" style="margin-top:10px">${ic.wiki}Your mail</a>` : ""}
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

// the way to the AI phone's page, on Agents and Stack too (PHN-27)
const phoneBanner = () => (S.phone ? `<a class="banner info" href="#/phone" style="margin-bottom:14px">${ic.bolt}<span class="grow"><b>AI phone</b> · ${S.phone.stopped ? "stopped" : S.phone.connected ? "connected" : "not connected"}${S.phone.pending ? ` · ${S.phone.pending} waiting for your OK` : ""}</span>${ic.next}</a>` : "");
// ---------- your devices on Home: the AI phone's state and its allowance in one tap ----------
function devicesHtml() {
  const p = S.phone;
  if (!p) return '<div id="homedev" hidden></div>';
  const now = Date.now() / 1000, trust = p.trust_until > now, forever = p.trust_until > now + 365 * 86400;
  const state = p.stopped ? ["failed", "Stopped"] : p.connected ? ["ok", "Connected"] : ["paused", "Not connected"];
  return `<div id="homedev" class="card pad-l devcard" data-href="#/phone" style="margin-bottom:14px">
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
  toast(r.error || (body.do === "stop" ? "AI phone stopped" : body.minutes === 0 ? "It asks you once for each job again" : body.minutes < 0 ? "Works without asking until you stop it" : `Works without asking for ${body.minutes} minutes`), !!r.error);
});

// ---------- Tasks (TSK-01 to TSK-04): give a task in a sentence, or with its details set; every task on one board ----------
const TSTATUS = { intake: "being planned", planning: "being planned", planned: "starting", needs_answer: "has a question", waiting_approval: "waits for your OK",
  waiting_owner: "waits for your review", running: "running", after: "waits for another task", scheduled: "scheduled", done: "done", failed: "failed", cancelled: "cancelled" };
const TKINDS = { change: "Change request", coding: "Coding", code_question: "Question about code", research: "Research", analysis: "Analysis", watching: "Watching", briefing: "Briefing", shopping: "Shopping", errand: "Errand", cleanup: "Cleanup" };
const TDOOR = { mission: (r) => [`#/mission/${encodeURIComponent(r)}`, "Open the mission"], build: (r) => [`#/build/${r}`, `Open build #${r}`],
  claude: (r) => [`#/live/claude-task:${r}`, `Open Claude task #${r}`], chat: (r) => [`#/chat?c=${r}`, "Open the chat"] };
const rhythmText = (r, after) => r?.type === "schedule" ? r.schedule + (r.triggers?.length ? ` · ${rhythmText({ type: "event", triggers: r.triggers })}` : "") : r?.type === "event" ? `on ${(r.triggers || []).map((x) => x.type === "news" ? `news on “${x.query}”` : x.type === "price_move" ? `a ${x.pct} % move of ${x.symbol}` : `SEC filings of ${(x.tickers || []).join(", ")}`).join(", ")}`
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
// a step's state in words (the task page's plan and steps)
const SSTATE = { pending: "waits", running: "running", waiting: "waits for its agent", done: "done", failed: "failed", cancelled: "cancelled", skipped: "dropped by the Orchestrator" };
// TSK-22: each run of a recurring task with how it started, its own verdict against the definition of done and its answer
const VWORD = { met: ["met", ""], partly: ["partly met", "warn-t"], "not met": ["not met", "err-t"], failed: ["failed", "err-t"], quiet: ["nothing new", "faint"], "not judged": ["not judged", "faint"] };
const HOW = { start: "at once", schedule: "on its schedule", owner: "you ran it" };
// ---------- TSK-24: the swarm map of a task's run ----------
// Flow: what was read (sources, by site), who worked (each step and its agent), what they found, what came out; a tap
// shows where a part came from and what it fed. Sources read but never cited are dashed. Timeline: one lane per agent
// run, dots for what it read, squares for what it made. Drawn from public/maps/<task>.<occ>.json (ops/provenance.py),
// redrawn every 5 s while the run goes on. On a phone the map pans sideways instead of shrinking.
let tmapMode = "flow", tmapTimer = null, tmapPick = null;
const TM_KIND = { page: "Page", item: "News item", job: "Job ad", note: "Vault note", memory: "Memory", search: "Search", finding: "Finding",
  report: "Report", result: "The answer", delivery: "Delivery", wiki: "Wiki page", file: "File" };
const TM_OUT = new Set(["report", "result", "delivery", "wiki"]);
// A name in an SVG wraps onto as many lines as it needs: nothing of it is cut. fits(line) says whether a line fits (its
// width measured in the label's own font); a word wider than a line breaks with a hyphen and goes on.
function wrapWords(text, fits) {
  const out = [];
  let cur = "";
  for (let w of String(text || "").split(/\s+/).filter(Boolean)) {
    while (!fits(w) && w.length > 2) {
      if (cur) { out.push(cur); cur = ""; }
      let k = w.length - 1;
      while (k > 1 && !fits(`${w.slice(0, k)}-`)) k--;
      out.push(`${w.slice(0, k)}-`); w = w.slice(k);
    }
    if (!cur) cur = w; else if (fits(`${cur} ${w}`)) cur += ` ${w}`; else { out.push(cur); cur = w; }
  }
  if (cur) out.push(cur);
  return out.length ? out : [""];
}
const SVG_FONT = {};
function svgTextWidth(text, cls, host) {                // the width of a label of that class, in the font the page gives it
  if (!SVG_FONT[cls]) {
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg"), t = document.createElementNS(ns, "text");
    svg.setAttribute("class", "netsvg tmapsvg"); t.setAttribute("class", cls); svg.append(t); (host || document.body).append(svg);
    const cs = getComputedStyle(t);
    SVG_FONT[cls] = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    svg.remove();
  }
  const c = (svgTextWidth.ctx ||= document.createElement("canvas").getContext("2d"));
  c.font = SVG_FONT[cls];
  return c.measureText(text).width;
}
// AI Change Requests, step 1: where each idea came from (its first run, agent and task), read at most once a minute
let ideaOrig = { t: 0, d: null, p: null };
function ideaOrigins() {
  if (ideaOrig.d && Date.now() - ideaOrig.t < 60000) return Promise.resolve(ideaOrig.d);
  ideaOrig.p ||= api("/api/ideas/origins").catch(() => ({ ideas: [] })).then((r) => {
    ideaOrig = { t: Date.now(), d: new Map((r.ideas || []).map((x) => [x.id, x])), p: null, ed: r.editor || null };
    return ideaOrig.d;
  });
  return ideaOrig.p;
}
const ideasOfTask = (m, tid) => [...(m?.values() || [])].filter((x) => x.task === tid);
const ideaTaskName = (o) => (S?.tasks || []).find((t) => t.id === o.task)?.title || `task #${o.task}`;
const ED_WORD = { in: "into a change request", held: "held", covered: "covered", dropped: "dropped" };
function editorHtml(v) {                                 // ACR-02: the Editor's verdict on an idea, its reason one tap away
  if (!v) return "";
  return `<span class="tag ed-${v.verdict}" title="${esc(v.reason)}">Editor: ${esc(ED_WORD[v.verdict] || v.verdict)}${v.verdict === "in" ? ` · ${esc(v.request)}` : v.covered_by ? ` by ${esc(v.covered_by)}` : ""}</span>`;
}
function ideaFromHtml(o) {                               // one line: which task's run saw it first, and how often since
  if (!o?.first_run) return o?.task ? `from <a href="#/task/${o.task}">${esc(ideaTaskName(o))}</a> · its writer's duty; no run recorded` : "";
  return `${o.task ? `from <a href="#/task/${o.task}">${esc(ideaTaskName(o))}</a>` : "from a run on no task"} · first seen ${esc(when(new Date(o.first_at * 1000).toISOString()))}${o.first_actor ? ` by ${esc(agentName(o.first_actor))}` : ""}${o.runs > 1 ? ` · seen in ${nf(o.runs)} runs` : ""}`;
}
async function fillIdeaFrom(box) {                       // every [data-iorig] in box gets its line; a task filter hides the others
  const els = $$("[data-iorig]", box);
  if (!els.length) return;
  const m = await ideaOrigins(), only = +(route.q.get("task") || 0);
  els.forEach((el) => {
    const o = m.get(+el.dataset.iorig);
    el.innerHTML = [ideaFromHtml(o), editorHtml(o?.editor)].filter(Boolean).join(" ");
    if (only) el.closest(".prop")?.toggleAttribute("hidden", o?.task !== only);
  });
  const ed = $("#ieditor", box), E = ideaOrig.ed;      // ACR-02: the Editor's sorting at a glance; nothing changes until step 3
  if (ed && E?.at && !only) {
    const vs = [...m.values()].map((x) => x.editor).filter(Boolean), n = (k) => vs.filter((v) => v.verdict === k).length;
    ed.innerHTML = `<details class="card pad-l section"><summary><b>The Editor's sorting</b> <span class="small muted">${esc(when(new Date(E.at * 1000).toISOString()))} · ${nf(E.requests.length)} would-be request${E.requests.length === 1 ? "" : "s"} · ${nf(n("held"))} held · ${nf(n("covered"))} covered · ${nf(n("dropped"))} dropped</span></summary>
      <div class="small muted" style="margin-top:6px">What the Editor would make of the open ideas. It changes nothing yet: you still decide each idea below.</div>
      ${E.requests.map((r) => `<div style="margin-top:8px"><b class="small">${esc(r.title)}</b> <span class="tiny faint">${nf(r.ideas.length)} idea${r.ideas.length === 1 ? "" : "s"}: ${r.ideas.map((i) => `<a href="#/swarm/artifact/${i}">#${i}</a>`).join(" ")}</span>${r.why ? `<div class="tiny muted">${esc(r.why)}</div>` : ""}</div>`).join("")}
      ${E.missing.length ? `<div class="tiny warn-t" style="margin-top:8px">Not sorted: ${E.missing.map((i) => `#${i}`).join(" ")}</div>` : ""}</details>`;
  }
  const hd = $("#ionly", box);
  if (hd && only) hd.innerHTML = `<div class="banner info" style="margin-top:10px">${ic.target}<span class="grow">Ideas from <a href="#/task/${only}">${esc(ideaTaskName({ task: only }))}</a> · ${nf(ideasOfTask(m, only).filter((x) => ["open", "ready"].includes(x.state)).length)} open</span><a class="small" href="#/tasks?v=ideas">All ideas</a></div>`;
}
async function fillTaskIdeas(el, tid) {                  // a task's page: one quiet line to the ideas its runs had
  if (!el || !tid) return;
  const xs = ideasOfTask(await ideaOrigins(), tid);
  if (el.isConnected && xs.length) el.innerHTML = `<a class="tiny faint" href="#/tasks?v=ideas&task=${tid}"><span class="idot"></span>${nf(xs.length)} idea${xs.length === 1 ? "" : "s"} from its runs${xs.some((x) => ["open", "ready"].includes(x.state)) ? ` · ${nf(xs.filter((x) => ["open", "ready"].includes(x.state)).length)} open` : ""} ›</a>`;
}
const svgTspans = (ls, x, y, lh) => ls.map((l, k) => `<tspan x="${x}" ${k ? `dy="${lh}"` : `y="${y}"`}>${esc(l)}</tspan>`).join("");   // wrapped lines in one <text>
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

const TM_LINES = 3;                                     // a box's lines: a name is whole; a long step instruction shows its start, the panel the rest
function tmapFlow(box, d, g) {
  const COLS = ["What was read", "Who worked", "What they found", "What came out"], CW = 176, GAP = 46, NH = 34, VG = 8, TOP = 26;
  const cols = [0, 1, 2, 3].map((k) => g.nodes.filter((n) => n.col === k));
  cols[0].sort((a, b) => (b.cited - a.cited) || ((b.members?.length || 1) - (a.members?.length || 1)));
  cols[1].sort((a, b) => a.step.idx - b.step.idx);
  const shown = [0, 1, 2, 3].filter((k) => cols[k].length);   // an empty column takes no room (a run that read nothing)
  for (const n of g.nodes) {                            // a box as tall as its whole name: nothing is cut
    n.tl = wrapWords(n.label, (s) => svgTextWidth(s, "tml", box) <= CW - 16);
    if (n.tl.length > TM_LINES) n.tl = [...n.tl.slice(0, TM_LINES - 1), "… tap for all"];   /* cap: preview: a step's whole instruction; tapping the box shows it in the panel */
    n.sl = n.sub ? wrapWords(n.sub, (s) => svgTextWidth(s, "tms", box) <= CW - 16) : [];
    n.h = Math.max(NH, 10 + n.tl.length * 13 + n.sl.length * 12);
  }
  const H = TOP + Math.max(...cols.map((c) => c.reduce((s, n) => s + n.h + VG, 0)), NH + VG) + 10, W = shown.length * CW + (shown.length - 1) * GAP + 34;
  shown.forEach((k, j) => { let y = TOP; cols[k].forEach((n) => { n.x = 2 + j * (CW + GAP); n.y = y; y += n.h + VG; }); });
  const at = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  const stroke = (n) => n.kind === "step" ? (n.step.status === "failed" ? "var(--err)" : n.step.status === "running" ? "var(--warn)" : "var(--accent)")
    : n.col === 0 ? (n.cited ? "var(--accent)" : "var(--border-2)") : TM_OUT.has(n.kind) ? "var(--accent-2)" : "var(--border-2)";
  box.innerHTML = `<div class="tmap-wrap"><svg class="tmapsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="The swarm of this run">
    ${shown.map((k, j) => `<text x="${2 + j * (CW + GAP)}" y="14" class="tmcol">${COLS[k]}</text>`).join("")}
    ${g.edges.map((e) => { const a = at[e.a], b = at[e.b]; if (!a || !b) return ""; const y1 = a.y + a.h / 2, y2 = b.y + b.h / 2;
      const p = e.kind === "chain" ? (() => { const x = a.x + CW, bend = x + 14 + Math.min(16, Math.abs(y2 - y1) / 6); return `M${x},${y1} C${bend},${y1} ${bend},${y2} ${x},${y2}`; })()   // step to step, beside the column
        : (() => { const x1 = a.x + CW, x2 = b.x, m = (x1 + x2) / 2; return `M${x1},${y1} C${m},${y1} ${m},${y2} ${x2},${y2}`; })();
      return `<path d="${p}" class="tmedge ${e.kind}${a.col === 0 && !a.cited ? " uncited" : ""}" data-e="${esc(e.a)}|${esc(e.b)}"${e.kind === "chain" ? ' marker-end="url(#tmarrow)"' : ""}/>`; }).join("")}
    <defs><marker id="tmarrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="var(--accent-2)"/></marker></defs>
    ${g.nodes.map((n) => `<g class="tmnode" data-n="${esc(n.id)}" tabindex="0" role="button" transform="translate(${n.x},${n.y})"><title>${esc(n.label)}</title>
      <rect width="${CW}" height="${n.h}" rx="8" fill="var(--surface-2)" stroke="${stroke(n)}" stroke-width="${n.cited || n.kind === "step" ? 2 : 1.2}" ${n.col === 0 && n.read && !n.cited ? 'stroke-dasharray="4 3" opacity="0.7"' : ""}/>
      <text class="tml">${svgTspans(n.tl, 9, 15, 13)}</text>${n.sl.length ? `<text class="tms">${svgTspans(n.sl, 9, 15 + n.tl.length * 13, 12)}</text>` : ""}</g>`).join("")}
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
  const name = (id) => { const x = g.nodes.find((y) => y.id === id); return x ? `<button class="linkbtn" data-tm="${esc(id)}">${esc(x.label)}</button>` : ""; };
  const from = g.edges.filter((e) => e.b === n.id).map((e) => name(e.a)), fed = g.edges.filter((e) => e.a === n.id).map((e) => name(e.b));
  const s = n.step, run = s ? `task:${d.task}${d.occ > 1 ? "." + d.occ : ""}:step:${s.idx}` : "";
  const members = (n.members || []).map((i) => g.A[i]).map((a) => `<li class="${g.cited.has(a.id) ? "" : "faint"}">${g.cited.has(a.id) ? "cited · " : "read, not cited · "}<a href="${esc(safeUrl(a.uri))}" target="_blank" rel="noopener noreferrer">${esc(a.title || a.uri)}</a></li>`).join("");
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
  const LW = 118, W = Math.max((box.clientWidth || 340) - 20, 300), LH = 26;
  const LL = lanes.map((l) => wrapWords(`${l.own ? `${l.step}. ` : "↳ "}${l.agent}`, (s) => svgTextWidth(s, l.own ? "tml" : "tms", box) <= LW - (l.own ? 0 : 12) - 6));
  const RH = LL.map((ls) => Math.max(LH, ls.length * 13 + 6)), RT = RH.reduce((o, h, i) => (o.push(i ? o[i - 1] + RH[i - 1] : 20), o), []), H = 22 + RH.reduce((s, h) => s + h, 0);
  const x = (s) => LW + (s - t0) / (t1 - t0) * (W - LW - 10);
  const A = Object.fromEntries(d.artifacts.map((a) => [a.id, a]));
  const marks = d.links.filter((l) => (l.rel === "used" || l.rel === "generated") && A[l.artifact]);
  const fmt = (s) => s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;
  box.innerHTML = `<div class="tmap-wrap"><svg class="tmapsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="When each agent worked">
    <text x="${LW}" y="12" class="tmcol">0</text><text x="${W - 10}" y="12" class="tmcol" text-anchor="end">${fmt(t1 - t0)}</text>
    ${lanes.map((l, i) => { const y = RT[i] + (RH[i] - LH) / 2, end = l.ended || nowS, mine = marks.filter((m) => m.run === l.run || (l.own && m.step === l.step && !m.at));
      return `<g><title>${esc(`${l.agent} · step ${l.step} · ${fmt(end - l.started)}${l.tokens ? ` · ${tok(l.tokens)} tokens${l.cost != null ? `, ${ifPaid(l.cost)}` : ""}${l.models?.length ? ` (${l.models.join(", ")})` : ""}` : ""}`)}</title><text class="${l.own ? "tml" : "tms"}">${svgTspans(LL[i], l.own ? 0 : 12, y + 15 - (LL[i].length - 1) * 6.5, 13)}</text>
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
  <div class="hero heading"><div class="row between" style="gap:10px"><h1>Telemetry</h1><a class="btn sm" href="#/trials">${ic.target}Trials</a></div>${explain("telemetry-numbers", `Runs, how many ended well, the judge's verdicts, tokens, time, and what the tokens would cost at list price (the subscriptions cost $0 a call).${telData.prices?.date ? ` Prices of ${esc(telData.prices.date)}, from the gateway's table.` : ""}`, "What these numbers are")}</div>
  ${telData.error ? `<div class="card pad small muted">${esc(telData.error)}</div>` : ""}
  <div class="row wrap telf"><div class="seg">${[7, 30, 90, 365].map((d) => `<button data-td="${d}" class="${telF.days === d ? "on" : ""}">${d === 365 ? "Year" : d + " days"}</button>`).join("")}</div>${sel("agent", "Agent")}${sel("model", "Model")}${sel("kind", "Kind")}</div>
  <div class="tmnums" style="margin-top:12px">${[[nf(s.runs), "runs", ""], [pct(s.ok, s.runs), `ended well (${nf(s.failed)} failed)`, ""], [judged ? pct(s.met + 0.5 * s.partly, judged) : "–", `of ${nf(judged)} judged tasks met`, ""],
    [tok(s.tin + s.tout), "tokens", ""], [ifPaid(s.cost) || "–", "at list price", ""], [s.runs ? dur(s.p50) : "–", `median run · p95 ${s.runs ? dur(s.p95) : "–"}`, ""]]
    .map(([v, l]) => `<div class="card pad tmnum"><b>${esc(v)}</b><span class="tiny faint">${esc(l)}</span></div>`).join("")}</div>
  <div class="stack section">${telBars(rows, (r) => r.runs, "Runs", nf)}${telBars(rows, (r) => (r.tin || 0) + (r.tout || 0), "Tokens", tok)}</div>
  <div class="section-h section"><h2>Agents · ${agents.length}</h2></div>
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

