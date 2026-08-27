/* Storefront service worker — cache-first shell, network-first API.
   Distinct file + cache name so it never collides with /ops/sw.js. */
const CACHE = "storefront-v4";
const SHELL = ["/", "/store.css", "/store.js", "/store.webmanifest"];

self.addEventListener("install", (e) => {
  /* One at a time: addAll() rejects wholesale if any single URL 404s, and
     the shell then goes entirely uncached — the one state this exists to
     prevent. */
  e.waitUntil(caches.open(CACHE).then((c) =>
    Promise.allSettled(SHELL.map((u) => c.add(u)))));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k.startsWith("storefront-") && k !== CACHE)
      .map((k) => caches.delete(k)))));
  self.clients.claim();
});

/* Network-first, and only for things worth having offline. Caching every
   GET meant uploaded media and one-off downloads piled up with no ceiling,
   and storing an error response is how a deploy strands someone on a broken
   page. */
const CACHEABLE = /\.(css|js|png|jpg|jpeg|svg|webp|woff2?|webmanifest)$|^\/$/;

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api") ||
      url.pathname.startsWith("/ops")) return;
  if (!CACHEABLE.test(url.pathname)) return;
  /* Keyed by path: the ?v=<mtime> cache-buster means a full-URL key would
     store one copy per deploy and match none of them next time. */
  const key = url.pathname;
  e.respondWith(
    fetch(e.request).then((r) => {
      if (r.ok && r.type === "basic") {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(key, copy));
      }
      return r;
    }).catch(async () => {
      /* ignoreSearch matters more than it looks. Assets are requested with
         a ?v=<mtime> cache-buster, so after any deploy the cached
         "/store.css" no longer matches "/store.css?v=NEW" and every lookup
         misses — the offline shell becomes unreachable on exactly the
         deploy it was meant to survive. The cached copy is still the right
         answer here; the query string only ever addressed the HTTP cache. */
      const hit = await caches.match(key, { ignoreSearch: true });
      if (hit) return hit;
      if (e.request.mode === "navigate") {
        const shell = await caches.match("/", { ignoreSearch: true });
        if (shell) return shell;
      }
      /* Nothing cached either. Retrying lets the real failure propagate:
         resolving respondWith() with undefined turns any transient blip
         into an opaque ERR_FAILED and leaves the page silently unstyled,
         which is what a restart mid-request used to do. */
      return fetch(e.request);
    }));
});
