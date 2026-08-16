/* Service worker: cache the app shell (network-first for /api), and surface
   Web Push notifications. */
const CACHE = "business-control-ops-v5";

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

/* Only the shell is worth keeping offline. Caching every GET meant uploaded
   media and one-off downloads accumulated on disk with no ceiling and no
   reason — the point of this cache is that the app still opens in a
   warehouse with no signal, not that it hoards every file it has ever
   seen. */
const CACHEABLE = /^\/ops\/(?!.*\bexport\b)|^\/manifest|\.(css|js|png|svg|webmanifest)$/;

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api") || e.request.method !== "GET") return;
  if (!CACHEABLE.test(url.pathname)) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        // Opaque and error responses are not worth storing, and storing a
        // 404 is how a deploy leaves someone stuck on a broken shell.
        if (r.ok && r.type === "basic") {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
