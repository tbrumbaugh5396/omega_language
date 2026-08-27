/* Run the two service workers against a stubbed browser, because the
   behaviour that matters only shows up in states a page cannot easily be
   put into: the server unreachable, the cache holding a copy stored under
   a different ?v=, and nothing cached at all.

   Prints one line per case: "PASS <name>" or "FAIL <name>: <detail>". */
import { readFileSync } from "node:fs";

/* The ops worker's path is a parameter, so the harness can be pointed at
   an older copy to confirm it still catches what it was written for. */
const OPS_SW = process.argv[2] || "src/erp/frontend/sw.js";

class FakeCache {
  constructor(net) { this.map = new Map(); this.net = net; }
  key(r) { return typeof r === "string" ? new URL(r, "http://x").href : r.url; }
  async put(r, res) { this.map.set(this.key(r), res); }
  /* Atomic, like the real one: every response first, and only then the
     puts. That is exactly why a single 404 in the shell list leaves
     nothing cached at all. */
  async addAll(us) {
    const rs = await Promise.all(us.map(async (u) => {
      const res = await this.net(new FakeRequest(u));
      if (!res.ok) throw new Error("404 " + u);
      return [u, res];
    }));
    for (const [u, res] of rs) await this.put(u, res);
  }
  async add(u) {
    const res = await this.net(new FakeRequest(u));
    if (!res.ok) throw new Error("404 " + u);
    return this.put(u, res);
  }
  async match(r, opts) {
    const want = this.key(r);
    if (this.map.has(want)) return this.map.get(want);
    if (opts && opts.ignoreSearch) {
      const bare = want.split("?")[0];
      for (const [k, v] of this.map) if (k.split("?")[0] === bare) return v;
    }
    return undefined;
  }
  async keys() { return [...this.map.keys()].map((u) => new Request(u)); }
}

class FakeCacheStorage {
  constructor(net) { this.caches = new Map(); this.net = net; }
  async open(n) {
    if (!this.caches.has(n)) this.caches.set(n, new FakeCache(this.net));
    return this.caches.get(n);
  }
  async keys() { return [...this.caches.keys()]; }
  async delete(n) { return this.caches.delete(n); }
  async match(r, opts) {
    for (const c of this.caches.values()) {
      const hit = await c.match(r, opts);
      if (hit) return hit;
    }
    return undefined;
  }
}

class FakeResponse {
  constructor(body, init = {}) {
    this.body = body;
    this.status = init.status ?? 200;
    this.ok = this.status >= 200 && this.status < 300;
    this.type = init.type ?? "basic";
    this.tag = init.tag ?? body;
  }
  clone() { return new FakeResponse(this.body, { status: this.status, type: this.type, tag: this.tag }); }
}

class FakeRequest {
  constructor(url, init = {}) {
    this.url = new URL(url, "http://host").href;
    this.method = init.method || "GET";
    this.mode = init.mode || "no-cors";
  }
}

function loadWorker(path, { online, files }) {
  const listeners = {};
  const self_ = {
    addEventListener: (t, fn) => { (listeners[t] ||= []).push(fn); },
    skipWaiting: () => {},
    clients: { claim: () => {}, matchAll: async () => [] },
    location: { origin: "http://host" },
    registration: { showNotification: () => {} },
  };
  const state = { online, files, fetches: 0 };
  const net = async (req) => {
    state.fetches += 1;
    if (!state.online) throw new TypeError("Failed to fetch");
    const p = new URL(typeof req === "string" ? req : req.url, "http://host").pathname;
    if (!(p in state.files)) return new FakeResponse("404", { status: 404 });
    return new FakeResponse(state.files[p], { tag: state.files[p] });
  };
  const cacheStorage = new FakeCacheStorage(net);
  const sandbox = {
    self: self_, caches: cacheStorage, clients: self_.clients,
    Request: FakeRequest, Response: FakeResponse, URL, console,
    fetch: net,
  };
  const src = readFileSync(path, "utf8");
  const fn = new Function(...Object.keys(sandbox), src);
  fn(...Object.values(sandbox));
  return { listeners, cacheStorage, state, self_ };
}

async function run(worker, url, mode = "no-cors") {
  const req = new FakeRequest(url, { mode });
  let answered;
  const ev = { request: req, respondWith: (p) => { answered = p; }, waitUntil: (p) => p };
  for (const fn of worker.listeners.fetch || []) fn(ev);
  if (answered === undefined) return "PASSED THROUGH";
  const out = await answered;
  // the worker stores its copy without awaiting; let that settle before
  // the next case reads the cache
  await new Promise((r) => setImmediate(r));
  return out;
}

async function install(worker) {
  const done = [];
  const ev = { waitUntil: (p) => done.push(p) };
  for (const fn of worker.listeners.install || []) fn(ev);
  // A rejected waitUntil is a failed install, which is a real outcome (the
  // browser keeps the old worker and the cache stays as it was) — not a
  // reason for the harness itself to fall over.
  await Promise.allSettled(done);
}

const results = [];
const ok = (name, cond, detail) =>
  results.push((cond ? "PASS " : "FAIL ") + name + (cond ? "" : ": " + detail));

const OPS_FILES = {
  "/ops/": "shell-v1", "/ops/styles.css": "css-v1", "/ops/app.js": "js-v1",
  "/ops/manifest.webmanifest": "mf", "/ops/icons/icon-192.png": "i192",
  "/ops/icons/icon-512.png": "i512",
};

// 1. A restart changes every ?v=, and the shell has to survive it.
{
  const w = loadWorker(OPS_SW, { online: true, files: OPS_FILES });
  await install(w);
  await run(w, "/ops/styles.css?v=111");            // cached under this version
  w.state.online = false;                            // server goes away
  const r = await run(w, "/ops/styles.css?v=222");   // new version after restart
  ok("ops: a restart's new ?v= still finds the cached asset",
     r && r.body === "css-v1", "got " + JSON.stringify(r && r.body));
}

// 2. Nothing cached and nothing reachable: never resolve with undefined.
{
  const w = loadWorker(OPS_SW, { online: false, files: OPS_FILES });
  let threw = null, r;
  try { r = await run(w, "/ops/never-seen.css?v=9"); } catch (e) { threw = e; }
  ok("ops: an uncacheable miss fails as a real fetch, not as undefined",
     threw !== null || (r !== undefined && r !== "PASSED THROUGH"),
     "resolved to undefined — respondWith(undefined) is itself a network error");
}

// 3. A navigation with nothing cached for it falls back to the shell.
{
  const w = loadWorker(OPS_SW, { online: true, files: OPS_FILES });
  await install(w);
  w.state.online = false;
  const r = await run(w, "/ops/?deep=1", "navigate");
  ok("ops: a navigation offline lands on the cached shell",
     r && r.body === "shell-v1", "got " + JSON.stringify(r && r.body));
}

// 4. One copy per file, not one per restart.
{
  const w = loadWorker(OPS_SW, { online: true, files: OPS_FILES });
  await install(w);
  for (const v of [1, 2, 3, 4]) await run(w, "/ops/app.js?v=" + v);
  const c = await w.cacheStorage.open([...(await w.cacheStorage.keys())][0]);
  const appCopies = [...c.map.keys()].filter((k) => k.includes("/ops/app.js"));
  ok("ops: four restarts leave one copy of app.js, not four",
     appCopies.length === 1, "kept " + JSON.stringify(appCopies));
}

// 5. A missing icon costs the icon, not the whole shell.
{
  const partial = { ...OPS_FILES };
  delete partial["/ops/icons/icon-512.png"];
  const w = loadWorker(OPS_SW, { online: true, files: partial });
  await install(w);
  const c = await w.cacheStorage.open([...(await w.cacheStorage.keys())][0]);
  w.state.online = false;
  const r = await run(w, "/ops/?x=1", "navigate");
  ok("ops: one 404 in the shell list does not empty the cache",
     r && r.body === "shell-v1", "shell missing; cached " + JSON.stringify([...c.map.keys()]));
}

// The storefront worker answers to the same two rules.
const SF_FILES = { "/": "sf-shell", "/store.css": "sf-css", "/store.js": "sf-js",
                   "/store.webmanifest": "sf-mf" };
{
  const w = loadWorker("src/storefront/frontend/sf-sw.js", { online: true, files: SF_FILES });
  await install(w);
  await run(w, "/store.css?v=111");
  w.state.online = false;
  const r = await run(w, "/store.css?v=222");
  ok("storefront: a deploy's new ?v= still finds the cached asset",
     r && r.body === "sf-css", "got " + JSON.stringify(r && r.body));
  const nav = await run(w, "/?ref=x", "navigate");
  ok("storefront: a navigation offline lands on the cached shell",
     nav && nav.body === "sf-shell", "got " + JSON.stringify(nav && nav.body));
}

console.log(results.join("\n"));
process.exit(results.some((r) => r.startsWith("FAIL")) ? 1 : 0);
