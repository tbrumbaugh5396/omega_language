/* Storefront service worker — cache-first shell, network-first API.
   Distinct file + cache name so it never collides with /ops/sw.js. */
const CACHE = "storefront-v2";
const SHELL = ["/", "/store.css", "/store.js", "/store.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
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
  e.respondWith(
    fetch(e.request).then((r) => {
      if (r.ok && r.type === "basic") {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return r;
    }).catch(() => caches.match(e.request)));
});
