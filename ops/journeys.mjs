// The journey checks' browser half (TSK-32), run by ops/journeys.py in the scout's browser image (headless Chromium, the
// Playwright that @playwright/mcp brings): every route of the app at 375 px on the live data, then again on an emptied
// state, and the e-mail at phone width. Nothing is changed: a write is answered here and never reaches the stack, and
// nothing outside the app is reached. One JSON report on stdout.
//   node journeys.mjs /j/config.json        config: { base, web, routes, email, wide }   (web: the checkout's front end)
import { createRequire } from "module";
import { readFileSync, existsSync } from "fs";
import { extname, join, normalize } from "path";

const require = createRequire("/usr/local/lib/node_modules/@playwright/mcp/package.json");
const { chromium } = require("playwright");
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const base = new URL(cfg.base);
const TYPES = { ".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json", ".webmanifest": "application/manifest+json" };
const PHONE = { viewport: { width: 375, height: 812 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// what the page shows, measured where the owner sees it
function measure(W) {                                     // W: the phone's width (a phone browser zooms out a wider page)
  const out = { overflow: 0, wide: [], main: "", skeleton: false, cards: [], empties: [], formats: [] };
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

async function sweep(browser, emptied) {
  const ctx = await browser.newContext({ ...PHONE, extraHTTPHeaders: { "Tailscale-User-Login": "journeys@stack.local", "Tailscale-User-Name": "Journey check" } });
  const writes = [], errs = [];
  await ctx.route("**/*", async (route) => {
    const req = route.request(), u = new URL(req.url());
    if (u.host !== base.host) return route.abort();                                    // nothing outside the app
    if (req.method() !== "GET" && !(u.pathname === "/api/swarm" && req.method() === "POST")) {   // /api/swarm reads only
      if (u.pathname === "/api/clienterror") errs.push({ route: "", msg: "the app reported: " + (req.postData() || "").slice(0, 300) });   // cap: preview
      else writes.push(`${req.method()} ${u.pathname}`);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, pending: false, result: {} }) });
    }
    if (cfg.web && (u.pathname === "/" || u.pathname.startsWith("/static/") || u.pathname === "/sw.js" || u.pathname.endsWith(".webmanifest"))) {
      const f = normalize(join(cfg.web, u.pathname === "/" ? "index.html" : u.pathname));
      if (f.startsWith(cfg.web) && existsSync(f)) return route.fulfill({ status: 200, contentType: TYPES[extname(f)] || "application/octet-stream", body: readFileSync(f) });
    }
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
  const seen = new Set(), per = {}, queue = [...cfg.routes], results = [];
  while (queue.length && results.length < (cfg.max || 90)) {
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
    const m = await page.evaluate(measure, PHONE.viewport.width);
    if (!emptied) for (const x of await page.$$eval('#view a[href^="#/"]', (as) => as.map((a) => a.getAttribute("href")))) if (!seen.has(x)) queue.push(x);
    results.push({ route: h, kind: k, ...m, errors: errs.slice(e0).map((e) => e.msg) });
  }
  await ctx.close();
  return { results, writes, errors: errs };
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
  if (cfg.routes?.length) {
    report.live = await sweep(browser, false);
    report.empty = await sweep(browser, true);
  }
  if (cfg.email) report.email = await email(browser);
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(report));
