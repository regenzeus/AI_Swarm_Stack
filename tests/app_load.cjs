// PLT-25 (tests/test_app_routes.py): runs the app's scripts' top-level code in one shared context, in the given order, against permissive stubs for the
// browser; prints each ReferenceError (a name not defined yet when that code runs). Usage: node loadcheck.js dir f1 f2 ...
const vm = require("vm"), fs = require("fs"), path = require("path");
const P = new Proxy(function () {}, {
  get: (t, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : k === Symbol.iterator ? function* () {} : P),
  apply: () => P, construct: () => P, set: () => true, has: () => true,
});
const g = { console: { log() {}, warn() {}, error() {} }, setInterval: () => 0, setTimeout: () => 0, clearTimeout() {}, clearInterval() {},
  requestAnimationFrame: () => 0, Math, JSON, Date, Intl, URL, URLSearchParams, Promise, Map, Set, WeakMap, Array, Object, String, Number,
  Boolean, RegExp, Error, Symbol, encodeURIComponent, decodeURIComponent, parseInt, parseFloat, isNaN, isFinite, AbortController,
  TextEncoder, TextDecoder, structuredClone, queueMicrotask, Reflect, Proxy, BigInt };
for (const k of ["window", "document", "location", "navigator", "localStorage", "sessionStorage", "history", "fetch", "d3", "marked",
  "DOMPurify", "matchMedia", "addEventListener", "screen", "performance", "EventSource", "WebSocket", "Notification", "caches",
  "crypto", "getComputedStyle", "Image", "Audio", "MutationObserver", "ResizeObserver", "IntersectionObserver", "CSS", "Blob", "FormData",
  "Headers", "Request", "Response", "HTMLElement", "Element", "Node", "Event", "CustomEvent", "alert", "confirm", "prompt", "open",
  "scrollTo", "innerWidth", "innerHeight", "devicePixelRatio", "visualViewport", "speechSynthesis", "SpeechSynthesisUtterance", "DEPLOY"])
  g[k] = P;
g.self = g; g.globalThis = g;
const ctx = vm.createContext(g);
const [dir, ...files] = process.argv.slice(2);
for (const f of files) {
  const code = fs.readFileSync(path.join(dir, f), "utf8");
  try { vm.runInContext(code, ctx, { filename: f }); console.log(`${f}: ran`); }
  catch (e) { console.log(`${f}: ${e.name}: ${e.message}`); }
}
