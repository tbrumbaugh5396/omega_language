/* Popup wrapper: embeds the Every Reward frontend, with an offline fallback. */
const DEFAULT_BASE = "http://127.0.0.1:8850";
const storage = globalThis.chrome?.storage?.sync;

function getBase() {
  return new Promise((resolve) => {
    if (!storage) return resolve(DEFAULT_BASE);
    storage.get({ base: DEFAULT_BASE }, (v) => resolve(v.base || DEFAULT_BASE));
  });
}

function setBase(base) {
  return new Promise((resolve) => {
    if (!storage) return resolve();
    storage.set({ base }, resolve);
  });
}

async function boot() {
  const base = await getBase();
  document.getElementById("base").value = base;
  let ok = false;
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch(base + "/api/info", { signal: ctrl.signal });
    ok = r.ok;
  } catch {
    ok = false;
  }
  const iframe = document.getElementById("app");
  const offline = document.getElementById("offline");
  if (ok) {
    iframe.src = base;
    iframe.style.display = "block";
    offline.style.display = "none";
  } else {
    iframe.style.display = "none";
    offline.style.display = "flex";
  }
}

document.getElementById("open-tab").addEventListener("click", async () => {
  const base = await getBase();
  if (globalThis.chrome?.tabs) chrome.tabs.create({ url: base });
  else window.open(base, "_blank");
});

document.getElementById("save").addEventListener("click", async () => {
  const base = document.getElementById("base").value.trim().replace(/\/$/, "")
    || DEFAULT_BASE;
  await setBase(base);
  boot();
});

boot();
