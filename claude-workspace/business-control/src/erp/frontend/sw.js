/* Service worker: cache the app shell (network-first for /api), and surface
   Web Push notifications. */
const CACHE = "business-control-ops-v6";

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
  /* One at a time, and failures allowed to be failures: cache.addAll()
     rejects wholesale if any single URL 404s, which silently leaves the
     shell entirely uncached — the one state this worker exists to prevent.
     A missing icon should cost the icon, not the app. */
  e.waitUntil(caches.open(CACHE).then((c) =>
    Promise.allSettled(SHELL.map((u) => c.add(u)))));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  // Only retire *our* old caches — the storefront PWA shares this origin
  // and owns the "storefront-*" ones.
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k.startsWith("business-control-ops-") && k !== CACHE)
      .map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

/* Only the shell is worth keeping offline. Caching every GET meant uploaded
   media and one-off downloads accumulated on disk with no ceiling and no
   reason — the point of this cache is that the app still opens in a
   warehouse with no signal, not that it hoards every file it has ever
   seen. */
const CACHEABLE = /^\/ops\/(?!.*\bexport\b)|^\/manifest|\.(css|js|png|svg|webmanifest)$/;

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api") || e.request.method !== "GET") return;
  if (!CACHEABLE.test(url.pathname)) return;
  /* Keyed by path, deliberately. Every asset is requested as
     app.js?v=<mtime>, so keying on the full URL stores a fresh copy on
     every restart and matches none of them afterwards: the offline shell
     goes missing on exactly the restart it was meant to survive. The query
     only ever addressed the HTTP cache, so it is not part of the identity
     of the file. */
  const key = url.pathname;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        // Opaque and error responses are not worth storing, and storing a
        // 404 is how a deploy leaves someone stuck on a broken shell.
        if (r.ok && r.type === "basic") {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(key, copy));
        }
        return r;
      })
      .catch(async () => {
        const hit = await caches.match(key, { ignoreSearch: true });
        if (hit) return hit;
        /* A navigation with nothing cached for it is still worth answering
           with the shell: this is a single-page app, and the shell is what
           every route renders from. */
        if (e.request.mode === "navigate") {
          const shell = await caches.match("/ops/", { ignoreSearch: true });
          if (shell) return shell;
        }
        /* Nothing cached either. Retry, and let the real failure be the
           failure: resolving respondWith() with undefined is itself a
           network error, which turns a server that was merely restarting
           into an opaque ERR_FAILED and a page left silently unstyled. */
        return fetch(e.request);
      })
  );
});
