// Network-first everywhere (this is a local server, so the network is the
// source of truth); the cache is only an offline fallback.
const CACHE = "av-trainer-v1";
const SHELL = ["/", "/static/styles.css", "/static/app.js", "/static/ui.js",
               "/static/engine-audio.js", "/static/engine-image.js",
               "/static/drills-audio.js", "/static/drills-visual.js",
               "/static/train.js", "/static/labs.js", "/static/labs-content.js",
               "/static/make.js", "/static/analyze.js", "/static/sandbox.js",
               "/static/library.js", "/static/progress.js",
               "/static/icons/icon-192.png", "/static/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(
    fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return res;
    }).catch(() => caches.match(e.request)));
});
