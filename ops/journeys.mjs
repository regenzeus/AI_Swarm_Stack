// The journey checks' browser half (TSK-32), run by ops/journeys.py in the scout's browser image (headless Chromium, the
// Playwright that @playwright/mcp brings): every route of the app at 375 px on the live data, then again on an emptied
// state, and the e-mail at phone width. Nothing is changed: a write is answered here and never reaches the stack, and
// nothing outside the app is reached. The one exception is the decide journey (GEN-03), where the tap on the nightly test
// item's own answer is sent, and only that. One JSON report on stdout.
//   node journeys.mjs /j/config.json        config: { base, web, routes, email, wide, decide }   (web: the checkout's front end)
import { createRequire } from "module";
import { readFileSync, existsSync } from "fs";
import { extname, join, normalize } from "path";

const require = createRequire("/usr/local/lib/node_modules/@playwright/mcp/package.json");
const { chromium } = require("playwright");
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const base = new URL(cfg.base);
const TYPES = { ".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json", ".webmanifest": "application/manifest+json" };
const PHONE = { viewport: { width: 375, height: 812 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
// APP-60: the windows the app must look right in, any shape (the owner, 9 Nov 2026: "on Mobile and on desktop on any ratio")
const SHAPES = {
  phone: PHONE, "phone-landscape": { viewport: { width: 812, height: 375 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  tablet: { viewport: { width: 768, height: 1024 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  "tablet-landscape": { viewport: { width: 1024, height: 768 } }, laptop: { viewport: { width: 1366, height: 768 } },
  desktop: { viewport: { width: 1440, height: 900 } }, "desktop-1080p": { viewport: { width: 1920, height: 1080 } },
  ultrawide: { viewport: { width: 2560, height: 1080 } }, "portrait-monitor": { viewport: { width: 1080, height: 1920 } },
  "4k": { viewport: { width: 3840, height: 2160 } },
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// what the page shows, measured where the owner sees it
function measure(W) {                                     // W: the window's width (a phone browser zooms out a wider page)
  const out = { overflow: 0, wide: [], main: "", skeleton: false, cards: [], empties: [], formats: [], clipped: [] };
  const H = window.innerHeight;
  // APP-60: text a box cuts off (hidden overflow, no scrolling, more inside than it shows), the chat's box to write in
  // outside the window, a chat page that scrolls, and no way to the other pages
  const nm = (e) => `${e.tagName.toLowerCase()}${e.id ? "#" + e.id : ""}${e.className && typeof e.className === "string" ? "." + e.className.trim().split(/\s+/).slice(0, 2).join(".") : ""}`;
  for (const e of document.querySelectorAll("#view *, .side *")) {
    const s = getComputedStyle(e), ov = s.overflowX + " " + s.overflowY;
    if (!/hidden|clip/.test(ov) || /auto|scroll/.test(ov) || e.closest("svg, .skeleton, [hidden], details:not([open]) > :not(summary)")) continue;
    if (e.querySelector(":scope > svg, :scope > canvas")) continue;       // a chart's viewport: it pans and zooms, it does not cut
    if (e.scrollWidth <= e.clientWidth + 2 && e.scrollHeight <= e.clientHeight + 2) continue;
    if (!(e.innerText || "").trim() || e.getBoundingClientRect().width === 0) continue;
    out.clipped.push(`${nm(e)} “${(e.innerText || "").trim().replace(/\s+/g, " ").slice(0, 40)}”`);
    if (out.clipped.length >= 4) break;
  }
  const box = location.hash.startsWith("#/chat") && document.querySelector(".composer2");
  out.writebox = !box || box.getBoundingClientRect().bottom <= H + 1;
  out.pagescroll = location.hash.startsWith("#/chat") ? Math.max(0, document.documentElement.scrollHeight - H) : 0;
  out.nav = [...document.querySelectorAll(".tabbar, .side")].some((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).display !== "none"; });
  out.overflow = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - W;
  if (out.overflow > 1) {                                  // the deepest elements that stick out, to say where
    const els = [...document.querySelectorAll("#view *, body > *")].filter((e) => { const r = e.getBoundingClientRect(); return r.width && r.right > W + 1 && getComputedStyle(e).position !== "fixed"; });
    const name = (e) => `${e.tagName.toLowerCase()}${e.id ? "#" + e.id : ""}${e.className && typeof e.className === "string" ? "." + e.className.trim().split(/\s+/).slice(0, 2).join(".") : ""}`;
    const deepest = els.filter((e) => !els.some((x) => x !== e && e.contains(x)));
    out.wide = deepest.slice(0, 4).map((e) => `${name(e)} (${Math.round(e.getBoundingClientRect().right - W)} px)`);
    const chain = [];                                       // where it starts: the outermost box wider than the phone
    for (let e = deepest[0]; e && e !== document.body; e = e.parentElement) {
      const s = getComputedStyle(e);
      chain.unshift(`${name(e)}[${Math.round(e.getBoundingClientRect().width)}px ${s.display}${s.whiteSpace !== "normal" ? " " + s.whiteSpace : ""}]`);
    }
    out.chain = chain.slice(0, 12);
  }
  const view = document.querySelector("#view") || document.body;
  out.main = (view.innerText || "").trim().slice(0, 200);
  out.graphic = !!view.querySelector("svg:not(.ico), canvas, iframe, img");
  out.skeleton = !!view.querySelector(".skeleton") && !(view.innerText || "").trim();
  out.actions = view.querySelectorAll("a[href], button").length;
  // a card that stands for a page (its heading is the link, and every link but a help link goes there) opens it on a tap
  const cards = [...view.querySelectorAll(".card")].filter((c) => c.parentElement && [...c.parentElement.children].filter((x) => x.classList.contains("card")).length >= 2);
  for (const c of cards) {
    const targets = [...new Set([...c.querySelectorAll('a[href^="#/"]')].map((a) => a.getAttribute("href")).filter((h) => !h.startsWith("#/guide")))];
    const head = c.querySelector("h1, h2, h3, h4, b, strong");
    const linked = head && (head.closest('a[href^="#/"]') || head.querySelector('a[href^="#/"]'));
    if (targets.length === 1 && linked && c.tagName !== "A" && !c.closest("[data-href]") && !c.querySelector("button, input, select, textarea, form"))
      out.cards.push(`${(head.innerText || "").trim().slice(0, 60)} → ${targets[0]}`);
  }
  for (const e of view.querySelectorAll(".empty")) if (!e.querySelector("a[href], button")) out.empties.push((e.innerText || "").trim().slice(0, 80));
  const own = view.cloneNode(true);                         // the app's own words: not a report, a log, code or a quote
  own.querySelectorAll(".md, pre, code, .log, .mono, blockquote, .quote, .rtext, .phlog, iframe").forEach((e) => e.remove());
  const text = own.textContent || "";
  for (const re of [/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[^\s]*/g, /\b\d+,\d{2} ?€/g, /\bNaN\b|\bundefined\b|\[object Object\]|Invalid Date/g])
    for (const m of text.match(re) || []) out.formats.push(m);
  return out;
}

const kind = (h) => h.replace(/\?.*$/, (q) => "?" + [...new URLSearchParams(q.slice(1)).keys()].sort().join("&"))
  .replace(/^(#\/(?:mission|crew|repo|live|swarm\/artifact|build|guide))\/[^?]+/, "$1/:id")
  + (/[?&]tab=([\w-]+)/.exec(h) ? ":" + /[?&]tab=([\w-]+)/.exec(h)[1] : "");      // each tab is its own screen

// the checkout's front end, when the journey was given one
function fromWeb(route, u) {
  if (!cfg.web || !(u.pathname === "/" || u.pathname.startsWith("/static/") || u.pathname === "/sw.js" || u.pathname.endsWith(".webmanifest"))) return null;
  const f = normalize(join(cfg.web, u.pathname === "/" ? "index.html" : u.pathname));
  return f.startsWith(cfg.web) && existsSync(f) ? route.fulfill({ status: 200, contentType: TYPES[extname(f)] || "application/octet-stream", body: readFileSync(f) }) : null;
}

async function sweep(browser, emptied, shape = "phone", routes = cfg.routes, max = cfg.max || 90) {
  const SH = SHAPES[shape] || PHONE;
  const ctx = await browser.newContext({ ...SH, extraHTTPHeaders: { "Tailscale-User-Login": "journeys@stack.local", "Tailscale-User-Name": "Journey check" } });
  const writes = [], errs = [];
  await ctx.route("**/*", async (route) => {
    const req = route.request(), u = new URL(req.url());
    if (u.host !== base.host) return route.abort();                                    // nothing outside the app
    if (req.method() !== "GET" && !(u.pathname === "/api/swarm" && req.method() === "POST")) {   // /api/swarm reads only
      if (u.pathname === "/api/clienterror") errs.push({ route: "", msg: "the app reported: " + (req.postData() || "").slice(0, 300) });   // cap: preview
      else writes.push(`${req.method()} ${u.pathname}`);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, pending: false, result: {} }) });
    }
    const own = fromWeb(route, u);
    if (own) return own;
    if (emptied && u.pathname === "/api/state") {                                       // the same app with nothing in it
      const r = await route.fetch(), s = await r.json();
      for (const [k, v] of Object.entries(s)) if (Array.isArray(v)) s[k] = [];
      s.running = null;
      return route.fulfill({ response: r, body: JSON.stringify(s) });
    }
    return route.continue();
  });
  const page = await ctx.newPage();
  let at = "";
  page.on("pageerror", (e) => errs.push({ route: at, msg: e.message }));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errs.push({ route: at, msg: m.text().slice(0, 300) }); });   // cap: preview
  page.on("response", (r) => { const u = new URL(r.url()); if (u.host === base.host && r.status() >= 500) errs.push({ route: at, msg: `HTTP ${r.status()} ${u.pathname}` }); });
  await page.addInitScript(() => { window.confirm = () => false; window.prompt = () => null; window.alert = () => {}; });
  await page.goto(cfg.base + "/", { waitUntil: "domcontentloaded" });
  await sleep(2500);
  const started = await page.evaluate(() => typeof render === "function" && typeof route === "object");
  if (!started) errs.push({ route: "#/", msg: "the app's scripts did not start (a syntax error or a script that did not load)" });
  const seen = new Set(), per = {}, queue = [...routes], results = [];
  while (queue.length && results.length < max) {
    const h = queue.shift();
    if (seen.has(h)) continue;
    seen.add(h);
    const k = kind(h);
    if ((per[k] = (per[k] || 0) + 1) > 2) continue;                                     // two of each kind of screen
    at = h;
    const e0 = errs.length;
    await page.evaluate((x) => { location.hash = x; }, h);
    await sleep(1600);
    for (let i = 0; i < 6 && (await page.evaluate(() => !!document.querySelector("#view .skeleton") && !(document.querySelector("#view").innerText || "").trim())); i++) await sleep(1000);
    const m = await page.evaluate(measure, SH.viewport.width);
    if (!emptied && shape === "phone") for (const x of await page.$$eval('#view a[href^="#/"]', (as) => as.map((a) => a.getAttribute("href")))) if (!seen.has(x)) queue.push(x);
    results.push({ route: h, kind: k, shape, size: `${SH.viewport.width}×${SH.viewport.height}`, ...m, errors: errs.slice(e0).map((e) => e.msg) });
  }
  await ctx.close();
  return { results, writes, errors: errs };
}

// The decide journey (GEN-03): the test item read from the app's list, Home and #/decide, answered by a tap on its own
// button, and then gone from all three with its answer recorded. That tap is the only write this page may send.
async function decide(browser) {
  const { token, wait = 120 } = cfg.decide, id = `test:${token}`, button = `[data-dact*="${token}"]`, ms = wait * 1000;
  const out = { id, writes: [], errors: [], still_shown: [] };
  const ctx = await browser.newContext({ ...PHONE, extraHTTPHeaders: { "Tailscale-User-Login": "journeys@stack.local", "Tailscale-User-Name": "Journey check" } });
  await ctx.route("**/*", async (route) => {
    const req = route.request(), u = new URL(req.url());
    if (u.host !== base.host) return route.abort();                                    // nothing outside the app
    if (req.method() !== "GET" && !(u.pathname === "/api/swarm" && req.method() === "POST")) {   // /api/swarm reads only
      let body = {};
      try { body = JSON.parse(req.postData() || "{}"); } catch { body = {}; }
      if (u.pathname === "/api/request" && body.action === "decision_test_answer" && body.token === token) { out.tapped = true; return route.continue(); }
      if (u.pathname === "/api/clienterror") out.errors.push("the app reported: " + (req.postData() || "").slice(0, 300));   // cap: preview
      else out.writes.push(`${req.method()} ${u.pathname}`);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, pending: false, result: {} }) });
    }
    return fromWeb(route, u) || route.continue();
  });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => out.errors.push(e.message));
  page.on("response", async (r) => {
    const u = new URL(r.url()), tap = u.pathname === "/api/request" && (r.request().postData() || "").includes(token);
    if (tap || u.pathname.startsWith("/api/result/")) out.answer = await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status()} from ${u.pathname}` }));
  });
  await page.addInitScript(() => { window.confirm = () => false; window.prompt = () => null; window.alert = () => {}; });
  const until = async (fn, limit) => { const end = Date.now() + limit; for (;;) { const v = await fn(); if (v || Date.now() >= end) return v; await sleep(1000); } };
  const state = () => page.evaluate(() => fetch("/api/state").then((r) => r.json())).catch(() => ({}));
  const look = (where, count) => page.evaluate(([where, count, id]) => {
    const item = (S?.decisions || []).find((d) => d.id === id), el = document.querySelector(where);
    return { shown: !!item && !!el && (el.innerText || "").includes(item.what), count: +(document.querySelector(count)?.textContent || "").replace(/\D/g, ""), list: (S?.decisions || []).length };
  }, [where, count, id]);
  const go = (h) => page.evaluate((x) => { location.hash = x; }, h);
  try {
    await page.goto(cfg.base + "/", { waitUntil: "domcontentloaded" });
    await sleep(2500);
    out.started = await page.evaluate(() => typeof render === "function" && typeof route === "object");
    const before = await until(async () => { const s = await state(); return (s.decisions || []).some((d) => d.id === id) ? s : null; }, ms);
    if (!before) return out;                                                            // it never reached the list: the report says so
    out.listed = true;
    out.marked = !!before.decisions.find((d) => d.id === id).test;
    out.no_answer = before.decisions.filter((d) => !(d.answers || []).some((a) => a.act || a.href)).map((d) => d.id);
    await go("#/");
    out.home = await until(async () => { const v = await look("#homeneeds", "#homeneeds .hcount"); return v.shown && v.count === v.list ? v : null; }, ms) || await look("#homeneeds", "#homeneeds .hcount");
    await go("#/decide");
    out.queue = await until(async () => { const v = await look("#view", "#dcount"); return v.shown && v.count === v.list ? v : null; }, ms) || await look("#view", "#dcount");
    await page.locator(button).first().click({ timeout: 15000 }).catch((e) => out.errors.push(`no answer to tap: ${e.message.split("\n")[0]}`));
    const after = await until(async () => { const s = await state(); return !(s.decisions || []).some((d) => d.id === id) ? s : null; }, ms);
    out.still_listed = !after;
    out.record = (after || await state()).decision_test || null;
    if (after) {
      if (!await until(() => page.evaluate((b) => !document.querySelector(b), button), 30000)) out.still_shown.push("#/decide");
      await go("#/");
      if (!await until(async () => !(await look("#homeneeds", "#homeneeds .hcount")).shown && await page.evaluate((id) => !(S?.decisions || []).some((d) => d.id === id), id), 30000)) out.still_shown.push("Home");
    }
    return out;
  } finally {
    await ctx.close();
  }
}

async function email(browser) {
  const ctx = await browser.newContext(PHONE);
  await ctx.route("**/*", (r) => (r.request().url().startsWith("data:") ? r.continue() : r.abort()));   // a mail app shows no remote parts first
  const page = await ctx.newPage();
  await page.setContent(readFileSync(cfg.email, "utf8"), { waitUntil: "domcontentloaded" });
  const out = await page.evaluate(([headline, W]) => {
    const all = [...document.querySelectorAll("body *")];
    const el = all.filter((e) => (e.innerText || "").trim() === headline).pop();
    const r = el?.getBoundingClientRect();
    return { overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - W, headline: !!el,
             headline_top: r ? Math.round(r.top) : null, headline_px: el ? parseFloat(getComputedStyle(el).fontSize) : null,
             body_px: parseFloat(getComputedStyle(document.querySelector("p") || document.body).fontSize) };
  }, [cfg.headline || "", PHONE.viewport.width]);
  await ctx.close();
  return out;
}

async function wide(browser) {      // the self-test: a page with each fault the checks are for must be caught
  const ctx = await browser.newContext(PHONE);
  const page = await ctx.newPage();
  await page.setContent(`<meta name="viewport" content="width=device-width"><div id="view"><div class="card" style="width:520px">wide</div>
    <div><div class="card"><b><a href="#/mission/a">A mission</a></b> its last run</div><div class="card"><b><a href="#/mission/b">B</a></b> two</div></div>
    <div class="empty">Nothing here yet</div><p>Started 2026-11-01T08:00:00+01:00, cost 12,34 €</p></div>`);
  const m = await page.evaluate(measure, PHONE.viewport.width);
  await ctx.close();
  return m;
}

const browser = await chromium.launch({ headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-features=LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights"] });
const report = {};
try {
  if (cfg.wide) report.wide = await wide(browser);
  if (cfg.decide) report.decide = await decide(browser);
  if (cfg.routes?.length && !cfg.onlyShapes) {
    report.live = await sweep(browser, false);
    report.empty = await sweep(browser, true);
  }
  if (cfg.shapes?.length) {                                // APP-60: the main screens at every shape, every screen at a desktop
    report.shapes = { results: [], errors: [] };
    const routes = report.live ? [...new Set(report.live.results.map((r) => r.route))] : cfg.routes || [];
    for (const shape of cfg.shapes) {
      const many = shape === "desktop";
      const r = await sweep(browser, false, shape, many ? routes : cfg.shapeRoutes || routes.slice(0, 8), many ? (cfg.max || 90) : 12);
      report.shapes.results.push(...r.results);
      report.shapes.errors.push(...r.errors.filter((e) => !e.route));
    }
  }
  if (cfg.email) report.email = await email(browser);
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(report));
