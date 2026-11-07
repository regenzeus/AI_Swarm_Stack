// Mission Control service worker: app shell offline, live data always from the network, push notifications.
const CACHE = "mc-v6";
const SHELL = ["/", "/static/app.css", "/static/app.js", "/static/shop.js", "/static/swarm.js", "/static/task.js", "/static/guide.js", "/static/guide.css", "/static/vendor/marked.min.js", "/static/vendor/purify.min.js", "/static/vendor/d3.min.js",
  "/static/vendor/inter.woff2", "/static/vendor/archivo.woff2", "/static/vendor/jetbrains-mono.woff2", "/static/icons/icon-192.png", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  // shell: network first (always the newest version), cache when offline
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("/"))));
});

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch (_) { d = { title: "Mission Control", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Mission Control", {
    body: d.body || "", icon: "/static/icons/icon-192.png", badge: "/static/icons/icon-192.png",
    data: { url: d.url || "/" }, tag: d.url || "mc",
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data && e.notification.data.url || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) { if ("focus" in c) { c.navigate(url); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
