// ---------- cameras: every property on one wall ----------
/* Each feed a tile, grouped by where it is; a tile opened large when
   something is worth a closer look. The browser fetches each feed itself
   — this server relays nothing — so a camera has to be reachable from
   wherever the wall is being looked at, and the screen says so instead
   of showing a spinner. Snapshots refresh on a timer; MJPEG plays in an
   <img>; HLS plays natively in Safari and through a vendored player
   elsewhere; RTSP is turned away with the relay command that fixes it. */
let CAM_TIMERS = [];
let CAM_HLS = [];
let CAM_COLS = 0;

function camStop() {
  CAM_TIMERS.forEach(clearInterval); CAM_TIMERS = [];
  CAM_HLS.forEach((h) => { try { h.destroy(); } catch (e) { /* gone */ } }); CAM_HLS = [];
}

function camTile(c) {
  const dead = c.plain_http && location.protocol === "https:";
  const inner = dead
    ? `<div class="cam-dead"><b>Cannot show a plain-http feed from an https page.</b>
       <span class="dim">The browser refuses it. Serve the camera over https, or look at the wall over http.</span></div>`
    : c.kind === "iframe" ? `<iframe src="${esc(c.url)}" title="${esc(c.name)}" loading="lazy"
        sandbox="allow-scripts allow-same-origin"></iframe>`
    : c.kind === "hls" ? `<video data-hls="${esc(c.url)}" muted autoplay playsinline></video>`
    : `<img data-cam="${c.id}" data-kind="${c.kind}" data-src="${esc(c.url)}"
        src="${esc(c.url)}" alt="${esc(c.name)}">`;
  return `<div class="cam-tile" data-camtile="${c.id}">
    ${inner}
    <div class="cam-cap"><b>${esc(c.name)}</b>
      <span class="dim">${esc(c.kind)}${c.kind === "snapshot" ? ` · every ${c.refresh_sec}s` : ""}</span>
      <span class="cam-state dim" data-camstate="${c.id}"></span></div>
  </div>`;
}

/* Start every feed on the page: snapshot timers, HLS players, and the
   "no picture" note on anything that never loads. */
async function camStart(root) {
  camStop();
  root.querySelectorAll("img[data-cam]").forEach((img) => {
    const st = root.querySelector(`[data-camstate="${img.dataset.cam}"]`);
    img.onerror = () => { st.textContent = "no picture — is it reachable from here?"; img.classList.add("dead"); };
    img.onload = () => { st.textContent = ""; img.classList.remove("dead"); };
    if (img.dataset.kind === "snapshot") {
      const c = (CAM_D.cameras || []).find((x) => x.id === +img.dataset.cam);
      const every = Math.max(1, (c && c.refresh_sec) || 5) * 1000;
      CAM_TIMERS.push(setInterval(() => {
        const u = new URL(img.dataset.src, location.href);
        u.searchParams.set("_t", Date.now());
        img.src = u.toString();
      }, every));
    }
  });
  const videos = [...root.querySelectorAll("video[data-hls]")];
  if (!videos.length) return;
  const native = document.createElement("video").canPlayType("application/vnd.apple.mpegurl");
  if (!native) {
    try { await loadCallScript("/vendor/hls/hls.min.js", () => !!window.Hls); }
    catch (e) { videos.forEach((v) => v.replaceWith(Object.assign(document.createElement("div"),
      { className: "cam-dead", textContent: "the HLS player did not load" }))); return; }
  }
  videos.forEach((v) => {
    if (native) { v.src = v.dataset.hls; return; }
    if (!window.Hls.isSupported()) return;
    const h = new window.Hls({ enableWorker: true });
    h.loadSource(v.dataset.hls); h.attachMedia(v);
    h.on(window.Hls.Events.ERROR, (_, data) => {
      if (data.fatal) v.closest(".cam-tile").querySelector(".cam-state").textContent =
        "no stream — is it reachable from here?";
    });
    CAM_HLS.push(h);
  });
}

let CAM_D = null;
async function renderCameras() {
  camStop();
  const d = await api("/api/cameras");
  CAM_D = d;
  const cols = CAM_COLS || (d.cameras.length <= 1 ? 1 : d.cameras.length <= 4 ? 2 : d.cameras.length <= 9 ? 3 : 4);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Cameras</h2>
        <p class="dim">Every property on one wall. The browser fetches each feed
          itself, so a camera has to be reachable from where you are sitting.
          Nothing is recorded here; that is the camera's job.</p></div>
      <div class="top-actions">
        <select id="cam-cols" aria-label="tiles per row">
          ${[1, 2, 3, 4, 6].map((n) => `<option value="${n}" ${n === cols ? "selected" : ""}>${n} across</option>`).join("")}
        </select>
        <button class="btn alt" id="cam-full">Full screen</button>
        ${d.can_edit ? '<button class="btn" id="cam-new">Add a camera</button>' : ""}
      </div>
    </div>
    <div id="cam-wall" class="cam-wall" style="--cam-cols:${cols}">
      ${d.sites.length ? d.sites.map((s) => `
        <h3 class="cam-site">${esc(s.name)} <span class="dim">${s.cameras.length}</span></h3>
        <div class="cam-grid">${s.cameras.map(camTile).join("")}</div>`).join("")
      : `<div class="card"><p class="dim">No cameras yet.</p>
          <p class="dim">A camera is a name, where it is, and the URL of what
          it serves — a snapshot, an MJPEG stream, an HLS playlist, or its
          own page. RTSP does not play in a browser; the relay below turns
          it into HLS.</p></div>`}
    </div>
    ${d.can_edit ? `<details class="card cam-help"><summary>What a camera can give this page</summary>
      <ul>${d.kinds.map((k) => `<li><b>${esc(k.k)}</b> — ${esc(k.what)}</li>`).join("")}</ul>
      <p><b>RTSP</b> — no browser plays it. Run this on a machine that can reach
        the camera, serve the folder, and give the wall the .m3u8:</p>
      <pre>${esc(d.relay.replace("{folder}", "/srv/cams/front"))}</pre>
      <p class="dim">An https install cannot show a plain-http feed; browsers refuse mixed content.</p>
    </details>
    ${d.cameras.length ? `<h3>Cameras</h3><div class="card"><div class="tablewrap"><table>
      <thead><tr><th>name</th><th>where</th><th>kind</th><th>url</th><th></th></tr></thead>
      <tbody>${d.cameras.map((c) => `<tr>
        <td>${esc(c.name)}</td><td>${esc(c.where)}</td><td>${esc(c.kind)}</td>
        <td class="dim">${esc(c.url.length > 60 ? c.url.slice(0, 58) + "…" : c.url)}</td>
        <td><a class="dim" data-camedit="${c.id}">edit</a> · <a class="dim" data-camdel="${c.id}">remove</a></td>
      </tr>`).join("")}</tbody></table></div></div>` : ""}` : ""}`;
  $("#cam-cols").onchange = (e) => { CAM_COLS = +e.target.value; $("#cam-wall").style.setProperty("--cam-cols", CAM_COLS); };
  $("#cam-full").onclick = () => {
    const w = $("#cam-wall");
    if (w.requestFullscreen) w.requestFullscreen(); else toast("this browser has no full screen");
  };
  if ($("#cam-new")) $("#cam-new").onclick = () => camForm(d);
  view().querySelectorAll("[data-camedit]").forEach((a) => a.onclick = () =>
    camForm(d, d.cameras.find((c) => c.id === +a.dataset.camedit)));
  view().querySelectorAll("[data-camdel]").forEach((a) => a.onclick = async () => {
    if (!confirm("Remove this camera from the wall? The camera itself is untouched.")) return;
    await api(`/api/cameras/${a.dataset.camdel}`, { method: "DELETE" }); renderCameras();
  });
  view().querySelectorAll("[data-camtile]").forEach((t) => t.ondblclick = () => t.classList.toggle("big"));
  camStart($("#cam-wall"));
}

function camForm(d, c = {}) {
  modal(`<h3>${c.id ? "Edit camera" : "Add a camera"}</h3>
    <label>Name <input id="cam-f-name" value="${esc(c.name || "")}" placeholder="Front door" maxlength="120"></label>
    <div class="row2">
      <label>Property <input id="cam-f-site" value="${esc(c.site || "")}" placeholder="Warehouse, Main St…" maxlength="120"></label>
      <label>Or a store <select id="cam-f-store">
        <option value="0">—</option>
        ${d.stores.map((s) => `<option value="${s.id}" ${s.id === c.store_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
      </select></label>
    </div>
    <label>Kind <select id="cam-f-kind">
      ${d.kinds.map((k) => `<option value="${k.k}" ${k.k === (c.kind || "snapshot") ? "selected" : ""}>${esc(k.k)} — ${esc(k.what)}</option>`).join("")}
    </select></label>
    <label>URL <input id="cam-f-url" value="${esc(c.url || "")}" placeholder="http://192.168.1.20/snapshot.jpg"></label>
    <div class="row2">
      <label>Refresh (snapshot, seconds) <input id="cam-f-refresh" type="number" min="1" max="300" value="${c.refresh_sec || 5}"></label>
      <label>Order <input id="cam-f-pos" type="number" value="${c.position || 0}"></label>
    </div>
    <label>Note <input id="cam-f-note" value="${esc(c.note || "")}" placeholder="points at the loading bay" maxlength="400"></label>
    <div class="actions"><button class="btn" id="cam-f-save">Save</button></div>`);
  $("#cam-f-save").onclick = async () => {
    try {
      await api("/api/cameras", { body: {
        id: c.id || 0, name: $("#cam-f-name").value, site: $("#cam-f-site").value,
        store_id: +$("#cam-f-store").value, kind: $("#cam-f-kind").value,
        url: $("#cam-f-url").value, refresh_sec: +$("#cam-f-refresh").value,
        position: +$("#cam-f-pos").value, active: true, note: $("#cam-f-note").value } });
      closeModal(); renderCameras();
    } catch (e) { toast(e.message); }
  };
}
