// APP-82 (tests/test_app_pages.py): every page of the app drawn while it has no state yet ("Connecting…"): the scripts
// run in one context against permissive stand-ins for the browser (app_load.cjs's), S stays null, and each route's view
// is called; a TypeError of its own (reading a property of null) is printed as "route: error". The stand-in browser
// answers every call with itself, so what fails is the page's own code. Usage: node app_pages.cjs dir route1 ... -- f1 f2 ...
const vm = require("vm"), fs = require("fs"), path = require("path");
const P = new Proxy(function () {}, {
  get: (t, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : k === Symbol.iterator ? function* () {} : k === "length" ? 0 : P),
  apply: () => P, construct: () => P, set: () => true, has: () => true,
});
const g = { console: { log() {}, warn() {}, error() {} }, setInterval: () => 0, setTimeout: () => 0, clearTimeout() {}, clearInterval() {},
  requestAnimationFrame: () => 0, Math, JSON, Date, Intl, URL, URLSearchParams, Promise, Map, Set, WeakMap, Array, Object, String, Number,
  Boolean, RegExp, Error, TypeError, Symbol, encodeURIComponent, decodeURIComponent, parseInt, parseFloat, isNaN, isFinite, AbortController,
  TextEncoder, TextDecoder, structuredClone, queueMicrotask, Reflect, Proxy, BigInt };
for (const k of ["window", "document", "location", "navigator", "localStorage", "sessionStorage", "history", "d3", "marked",
  "DOMPurify", "matchMedia", "addEventListener", "screen", "performance", "EventSource", "WebSocket", "Notification", "caches",
  "crypto", "getComputedStyle", "Image", "Audio", "MutationObserver", "ResizeObserver", "IntersectionObserver", "CSS", "Blob", "FormData",
  "Headers", "Request", "Response", "HTMLElement", "Element", "Node", "Event", "CustomEvent", "alert", "confirm", "prompt", "open",
  "scrollTo", "innerWidth", "innerHeight", "devicePixelRatio", "visualViewport", "speechSynthesis", "SpeechSynthesisUtterance", "DEPLOY", "getSelection"])
  g[k] = P;
g.location = { hash: "#/home", replace() {}, reload() {}, hostname: "pc.example.ts.net", protocol: "https:", host: "pc.example.ts.net", origin: "https://pc.example.ts.net", href: "https://pc.example.ts.net/" };
g.fetch = () => Promise.reject(new Error("no answer yet"));          // nothing answers: the app is connecting
g.self = g; g.globalThis = g;
const ctx = vm.createContext(g);
const args = process.argv.slice(2), cut = args.indexOf("--");
const [dir, ...routes] = args.slice(0, cut), files = args.slice(cut + 1);
for (const f of files) vm.runInContext(fs.readFileSync(path.join(dir, f), "utf8"), ctx, { filename: f });
const bad = (r, e) => /Cannot read properties of null|of undefined \(reading|is not iterable|null/.test(String(e?.message || e)) && console.log(`${r}: error: ${e.message}`);
(async () => {
  for (const r of routes) {
    const [name, ...rest] = r.split("?")[0].split("/");
    vm.runInContext(`S = null; route = { name: ${JSON.stringify(name)}, args: ${JSON.stringify(rest)}, q: new URLSearchParams(${JSON.stringify(r.split("?")[1] || "")}) };`, ctx);
    try { await vm.runInContext("render(true)", ctx); await new Promise((res) => setImmediate(res)); console.log(`${r}: drawn`); }
    catch (e) { bad(r, e) || console.log(`${r}: drawn (stand-in: ${e.message})`); }
  }
})();
process.on("unhandledRejection", (e) => bad("async", e));
