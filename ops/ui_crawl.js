// The app's click-through (APP-24, UX review 2026-10-30): every screen reachable from Home, every button, chip and switch on
// each kind of screen, at phone width, with forms filled in, and every request RECORDED, NOT SENT, so nothing is created,
// approved or deleted. Run it in the app's page (a browser on the dev proxy, or the tab's console); read window.__rec.
//   const s = document.createElement("script"); s.src = "..."; or paste this file, then: await __crawl(); __rec
// What it reports: rec.errors (exceptions, unhandled rejections, failed GETs), rec.toasts (error messages the owner saw),
// rec.posts (the requests a tap would have sent), rec.routes (each screen, how many taps, which taps threw).
(() => {
  const rec = (window.__rec = { errors: [], posts: [], toasts: [], routes: [], clicks: 0, done: false });
  const fr = document.createElement("iframe");
  fr.style.display = "none";
  document.body.appendChild(fr);
  const real = (url, o) => fr.contentWindow.fetch(new URL(url, location.origin).href, o);   // an untouched fetch
  window.addEventListener("error", (e) => rec.errors.push({ route: location.hash, msg: e.message, where: (e.filename || "").split("/").pop() + ":" + e.lineno }), true);
  window.addEventListener("unhandledrejection", (e) => rec.errors.push({ route: location.hash, msg: String(e.reason?.message || e.reason), where: String(e.reason?.stack || "").split("\n")[1] || "" }));
  window.fetch = (url, o = {}) => {
    const m = (o.method || "GET").toUpperCase(), u = String(url);
    if (m !== "GET" && !(u === "/api/swarm" && m === "POST")) {          // /api/swarm takes read operations only (server SWARM_READ)
      rec.posts.push({ route: location.hash, url: u, body: String(o.body || "").slice(0, 160) + (String(o.body || "").length > 160 ? " …" : "") });   // cap: preview
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json" } }));
    }
    return real(u, o).then((r) => { if (!r.ok && r.status !== 404) rec.errors.push({ route: location.hash, msg: `HTTP ${r.status} ${u}`, where: "fetch" }); return r; });
  };
  navigator.sendBeacon = () => true;                                     // the crawl's own errors are not reported as the owner's
  window.confirm = () => true; window.prompt = () => "test"; window.open = () => null; window.alert = () => {};
  window.toast = (m, bad) => { if (bad) rec.toasts.push({ route: location.hash, msg: String(m) }); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const kind = (h) => h.replace(/\?.*$/, (q) => "?" + [...new URLSearchParams(q.slice(1)).keys()].sort().join("&"))
    .replace(/^(#\/(?:mission|crew|repo|live|swarm\/artifact|build))\/[^?]+/, "$1/:id");
  const shown = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden"; };
  const sig = (el) => el.tagName + "|" + (el.textContent || "").trim().slice(0, 40) + "|" + [...el.attributes].filter((a) => a.name.startsWith("data-") || a.name === "id").map((a) => `${a.name}=${a.value}`).join(",");   // cap: id
  const go = async (h) => { if (location.hash !== h) location.hash = h; await sleep(1800); };
  const fill = () => document.querySelectorAll("#view input, #view textarea").forEach((i) => {
    if (["checkbox", "radio", "file", "hidden", "submit", "button", "range", "color"].includes(i.type) || i.value) return;
    i.value = { number: "5", email: "test@example.org", url: "https://example.org", time: "06:30", date: "2026-11-01" }[i.type] || "Test value 123";
    i.dispatchEvent(new Event("input", { bubbles: true }));
  });
  window.__crawl = async (max = 140, taps = 30) => {
    const seen = new Set(), per = {}, queue = ["#/"];
    while (queue.length && rec.routes.length < max) {
      const h = queue.shift();
      if (seen.has(h)) continue;
      seen.add(h);
      const k = kind(h);
      if ((per[k] = (per[k] || 0) + 1) > 2) continue;
      const e0 = rec.errors.length;
      await go(h);
      document.querySelectorAll('a[href^="#/"]').forEach((a) => { const x = a.getAttribute("href"); if (!seen.has(x)) queue.push(x); });
      const info = { route: h, kind: k, loadErrors: rec.errors.length - e0, clicked: 0, clickErrors: [] };
      rec.routes.push(info);
      if (per[k] > 1) continue;                                          // the taps: once per kind of screen
      const done = new Set();
      for (let n = 0; n < taps; n++) {
        if (location.hash !== h) await go(h);
        fill();
        const el = [...document.querySelectorAll('#view button, #view [role="button"], #view summary, #view label.switch input')].filter(shown).find((x) => !done.has(sig(x)));
        if (!el) break;
        done.add(sig(el));
        const before = rec.errors.length;
        try { el.click(); } catch (err) { rec.errors.push({ route: h, msg: "click threw: " + err.message, where: sig(el) }); }
        rec.clicks++; info.clicked++;
        await sleep(el.type === "submit" ? 1100 : 500);
        if (rec.errors.length > before) info.clickErrors.push({ el: sig(el), errors: rec.errors.slice(before).map((x) => x.msg) });
      }
    }
    rec.done = true;
    return { routes: rec.routes.length, clicks: rec.clicks, errors: rec.errors.length, toasts: rec.toasts.length };
  };
})();
