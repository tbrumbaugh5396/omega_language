/* Service worker: cache the app shell (network-first for /api), and surface
   Web Push notifications. */
const CACHE = "business-control-ops-v4";

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch {}
  e.waitUntil(self.registration.showNotification(
    d.title || "Business Control",
    { body: d.body || "", icon: "/ops/icons/icon-192.png",
      badge: "/ops/icons/icon-192.png" }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: "window" }).then((cs) =>
    cs.length ? cs[0].focus() : clients.openWindow("/ops/")));
});
const SHELL = ["/ops/", "/ops/styles.css", "/ops/app.js", "/ops/manifest.webmanifest",
  "/ops/icons/icon-192.png", "/ops/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  // Only retire *our* old caches — the storefront PWA shares this origin
  // and owns the "storefront-*" ones.
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k.startsWith("business-control-ops-") && k !== CACHE)
      .map((k) => caches.delete(k)))));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api") || e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
