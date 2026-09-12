// ---------- policy and elections ----------
/* A business sits inside a stack of jurisdictions at once, from a treaty
   bloc down to a homeowners' association, and every one of them can
   change a rule that reaches it. This is the map of that stack and the
   register behind it: click any place and the panel beside the map is
   that place — what it is inside, what is inside it, what it has agreed
   with others, who runs it, what it is deciding, when it next votes.

   The map is Leaflet, vendored rather than fetched. Underneath it are
   OpenStreetMap tiles when the machine is online and a bundled outline of
   every country when it is not, so the page never goes grey and the top
   of the stack is clickable with no network at all. The register holds
   only the places this business is watching: the outline layer shows
   every country, and clicking one that is not yet watched offers to
   watch it, which is how the map stays a map and the register stays a
   register. */

let CIV_SEL = 0;          // the jurisdiction the panel is showing
let CIV_MAP = null;       // the Leaflet map, kept across renders
let CIV_LAYERS = {};      // what is drawn on it, so it can be redrawn
let CIV_WORLD = null;     // the bundled countries, loaded once
let CIV_ASOF = 0;         // 0 = now; otherwise the date the page is looked at as of
let CIV_TL = null;        // the timeline for the current scope

const CIV_LEVEL_ZOOM = { bloc: 2, country: 4, state: 6, county: 8,
  district: 8, city: 11, school: 10, ward: 13, hoa: 15, other: 9 };

async function civReady() {
  await loadCallScript("/vendor/leaflet/leaflet.js", () => !!window.L);
  if (!document.getElementById("civ-leaflet-css")) {
    const l = document.createElement("link");
    l.id = "civ-leaflet-css";
    l.rel = "stylesheet";
    l.href = "/vendor/leaflet/leaflet.css";
    document.head.appendChild(l);
  }
  if (!CIV_WORLD) {
    try {
      CIV_WORLD = await (await fetch("/vendor/countries-110m.geojson")).json();
    } catch (e) { CIV_WORLD = { type: "FeatureCollection", features: [] }; }
  }
}

function civCentroid(geom) {
  // The middle of the biggest ring, which is where a label goes. A true
  // centroid of France lands in the Atlantic because of Guiana.
  let best = null;
  const rings = geom.type === "Polygon" ? [geom.coordinates[0]]
    : geom.type === "MultiPolygon" ? geom.coordinates.map((p) => p[0]) : [];
  rings.forEach((ring) => {
    if (!best || ring.length > best.length) best = ring;
  });
  if (!best) return null;
  let x = 0, y = 0;
  best.forEach(([lng, lat]) => { x += lng; y += lat; });
  return { lat: y / best.length, lng: x / best.length };
}

function civDraw(d) {
  const L = window.L;
  const m = d.map;
  const host = document.getElementById("civ-leaflet");
  if (!host) return;
  if (!CIV_MAP || CIV_MAP._container !== host) {
    if (CIV_MAP) { try { CIV_MAP.remove(); } catch (e) { /* gone */ } }
    CIV_MAP = L.map(host, { worldCopyJump: true, minZoom: 1, maxZoom: 18,
      zoomControl: true, attributionControl: true });
    // Tiles when online. When the request fails the layer simply stays
    // blank, and the outline layer underneath is what the page shows.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
      crossOrigin: true }).addTo(CIV_MAP);
    CIV_MAP.on("click", () => {
      // The map itself: clear the selection. A click on a shape stops
      // propagation before it gets here.
      if (CIV_SEL) { CIV_SEL = 0; civPanel(d, null); civRestyle(d); }
    });
  }
  Object.values(CIV_LAYERS).forEach((ly) => { try { CIV_MAP.removeLayer(ly); } catch (e) { /* */ } });
  CIV_LAYERS = {};
  const watchedIso = {};
  m.jurisdictions.forEach((j) => { if (j.iso) watchedIso[j.iso.toUpperCase()] = j; });

  // Every country, from the bundled outline. Clickable whether or not it
  // is watched: an unwatched one offers to become watched.
  CIV_LAYERS.world = L.geoJSON(CIV_WORLD, {
    style: (f) => {
      const j = watchedIso[(f.properties.iso2 || "").toUpperCase()]
        || watchedIso[(f.properties.iso3 || "").toUpperCase()];
      return { className: "civ-country-outline" + (j ? " watched" : "")
        + (j && j.id === CIV_SEL ? " on" : ""), weight: 1 };
    },
    onEachFeature: (f, layer) => {
      const p = f.properties;
      layer.bindTooltip(p.name, { sticky: true });
      layer.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        const j = watchedIso[(p.iso2 || "").toUpperCase()]
          || watchedIso[(p.iso3 || "").toUpperCase()];
        if (j) { civSelect(d, j.id); return; }
        civOfferWatch(d, p, civCentroid(f.geometry));
      });
    },
  }).addTo(CIV_MAP);

  // Watched jurisdictions with their own boundary.
  m.jurisdictions.filter((j) => j.boundary).forEach((j) => {
    CIV_LAYERS["b" + j.id] = L.geoJSON(j.boundary, {
      style: { className: "civ-area" + (j.id === CIV_SEL ? " on" : ""), weight: 1.5 },
      onEachFeature: (f, layer) => {
        layer.bindTooltip(j.name, { sticky: true });
        layer.on("click", (e) => { L.DomEvent.stopPropagation(e); civSelect(d, j.id); });
      },
    }).addTo(CIV_MAP);
  });

  // Watched jurisdictions as pins, sized by level, and the business's own
  // places as squares.
  const pin = (cls, size) => L.divIcon({ className: "", iconSize: [size, size],
    html: `<div class="${cls}" style="width:${size}px;height:${size}px"></div>` });
  const sizes = { bloc: 22, country: 18, state: 15, county: 13, district: 12,
    city: 11, school: 10, ward: 9, hoa: 9, other: 9 };
  const group = L.layerGroup();
  m.jurisdictions.filter((j) => j.lat !== null && j.lng !== null && !j.iso)
    .forEach((j) => {
      const mk = L.marker([j.lat, j.lng], {
        icon: pin(`civ-pin civ-${j.level}${j.id === CIV_SEL ? " on" : ""}${j.watching ? "" : " off"}`,
                  sizes[j.level] || 10),
        title: j.name });
      mk.bindTooltip(`${j.name} · ${j.level}`);
      mk.on("click", (e) => { L.DomEvent.stopPropagation(e); civSelect(d, j.id); });
      group.addLayer(mk);
    });
  m.places.forEach((p) => {
    const mk = L.marker([p.lat, p.lng], { icon: pin("civ-place", 10), title: p.name });
    mk.bindTooltip(`${p.name}${p.city ? " · " + p.city : ""} — yours`);
    group.addLayer(mk);
  });
  CIV_LAYERS.pins = group.addTo(CIV_MAP);
  setTimeout(() => CIV_MAP.invalidateSize(), 50);
}

function civRestyle(d) { civDraw(d); }

function civFit(d) {
  const m = d.map;
  const pts = [];
  m.jurisdictions.forEach((j) => {
    if (j.lat !== null && j.lng !== null) pts.push([j.lat, j.lng]);
  });
  m.places.forEach((p) => pts.push([p.lat, p.lng]));
  if (pts.length > 1) CIV_MAP.fitBounds(pts, { padding: [30, 30], maxZoom: 10 });
  else if (pts.length === 1) CIV_MAP.setView(pts[0], 9);
  else CIV_MAP.setView([20, 0], 2);
}

async function civSelect(d, jid) {
  CIV_SEL = jid;
  civRestyle(d);
  const j = d.map.jurisdictions.find((x) => x.id === jid);
  if (j && j.lat !== null && j.lng !== null && CIV_MAP) {
    const z = Math.max(CIV_MAP.getZoom(), CIV_LEVEL_ZOOM[j.level] || 6);
    CIV_MAP.flyTo([j.lat, j.lng], z, { duration: 0.6 });
  }
  await civPanel(d, jid);
}

function civOfferWatch(d, p, at) {
  const panel = document.getElementById("civ-panel");
  if (!panel) return;
  panel.innerHTML = `<b>${esc(p.long || p.name)}</b>
    <div class="dim">${esc(p.continent || "")}${p.region ? " · " + esc(p.region) : ""}${
      p.pop ? " · about " + Number(p.pop).toLocaleString() + " people" : ""}</div>
    <p class="dim">Not on the register yet. Watching it puts it in the
      stack, so its treaties, its measures and its elections have somewhere
      to go.</p>
    ${d.admin ? `<button class="btn sm" id="civ-watch">Watch ${esc(p.name)}</button>` : ""}`;
  if ($("#civ-watch")) $("#civ-watch").onclick = async () => {
    try {
      const r = await api("/api/civics/watch", { body: {
        iso: p.iso2 || p.iso3 || "", name: p.long || p.name,
        lat: at ? at.lat : 0, lng: at ? at.lng : 0 } });
      CIV_SEL = r.id;
      renderCivics();
    } catch (e) { toast(e.message); }
  };
}

async function civPanel(d, jid) {
  const panel = document.getElementById("civ-panel");
  if (!panel) return;
  if (!jid) {
    panel.innerHTML = `<div class="civ-hint">Click a country, a pin or a
      boundary. What opens here is that place: what it is inside, what is
      inside it, what it has agreed with others, who runs it, what it is
      deciding and when it next votes.</div>`;
    return;
  }
  let x;
  try { x = await api(`/api/civics/jurisdictions/${jid}/detail${CIV_ASOF ? "?as_of=" + CIV_ASOF : ""}`); }
  catch (e) { panel.innerHTML = `<p class="low">${esc(e.message)}</p>`; return; }
  const posPill = { support: "ok", oppose: "bad", watch: "", neutral: "" };
  const crumbs = x.ancestors.map((a) =>
    `<button data-civgo="${a.id}">${esc(a.name)}</button>`).join(" › ");
  panel.innerHTML = `
    ${crumbs ? `<div class="crumbs">${crumbs} ›</div>` : ""}
    ${x.as_of ? `<div class="pill warn">as it was on ${fmtDate(x.as_of)}</div>` : ""}
    <b>${esc(x.name)}</b> <span class="dim">${esc(x.level_label)}${
      x.population ? " · " + Number(x.population).toLocaleString() + " people" : ""}${
      x.watching ? "" : " · not watching"}</span>
    ${x.note ? `<p class="dim">${esc(x.note)}</p>` : ""}
    ${x.children.length ? `<h4>Inside it</h4><ul>${x.children.map((k) =>
      `<li><button data-civgo="${k.id}" class="btn alt sm">${esc(k.name)}</button>
        <span class="dim">${esc(k.level)}</span></li>`).join("")}</ul>` : ""}
    ${x.agreements.length ? `<h4>Agreements it is party to</h4><ul>${x.agreements.map((a) =>
      `<li><b>${esc(a.name)}</b> <span class="dim">${esc(a.kind_label)} · ${esc(a.status.replace(/_/g, " "))}</span>
        ${a.parties.length > 1 ? `<br><span class="dim">with ${a.parties.filter((q) => q.id !== x.id)
          .map((q) => esc(q.name)).join(", ")}</span>` : ""}
        ${a.why ? `<br><span class="dim">${esc(a.why)}</span>` : ""}
        <span class="pill ${posPill[a.position] || ""}">${esc(a.position)}</span></li>`).join("")}</ul>` : ""}
    ${x.officials.length ? `<h4>Who runs it</h4><ul>${x.officials.map((o) =>
      `<li><b>${esc(o.name)}</b> <span class="dim">${esc(o.office)}${o.party ? " · " + esc(o.party) : ""}</span>
        ${o.email || o.phone ? `<br><span class="dim">${esc(o.email || "")}${o.phone ? " " + esc(o.phone) : ""}</span>` : ""}
        ${o.url ? ` <a href="${esc(o.url)}" target="_blank" rel="noopener">page</a>` : ""}</li>`).join("")}</ul>` : ""}
    ${x.measures.length ? `<h4>What it is deciding</h4><ul>${x.measures.map((mm) =>
      `<li><b>${esc(mm.ref || "")}</b> ${esc(mm.title)}
        <span class="pill">${esc(mm.status.replace(/_/g, " "))}</span>
        <span class="pill ${posPill[mm.position] || ""}">${esc(mm.position)}</span>
        ${mm.why ? `<br><span class="dim">${esc(mm.why)}</span>` : ""}</li>`).join("")}</ul>` : ""}
    ${x.elections.length ? `<h4>Elections</h4><ul>${x.elections.map((e) =>
      `<li>${fmtDate(e.at)} — ${esc(e.name)} <span class="dim">${esc(e.kind)}</span></li>`).join("")}</ul>` : ""}
    ${x.given_cents ? `<h4>Given under its rules</h4><p>${money(x.given_cents)}</p>` : ""}
    ${!x.children.length && !x.agreements.length && !x.officials.length
      && !x.measures.length && !x.elections.length
      ? `<p class="dim">Nothing recorded under it yet. ${d.admin
          ? "Track a measure, add an agreement or an election, and pick this place." : ""}</p>` : ""}
    ${d.admin ? `<div class="chips" style="margin-top:10px">
      ${(x.code || "").startsWith("census:") && !x.boundary
        ? `<button class="btn alt sm" data-civoutline="${x.id}">Draw its outline</button>` : ""}
      <button class="btn alt sm" data-civaddunder="${x.id}">Add a place inside it</button>
      <button class="btn alt sm" data-civagree="${x.id}">Add an agreement</button>
    </div>` : ""}`;
  panel.querySelectorAll("[data-civgo]").forEach((b) => b.onclick = () =>
    civSelect(d, +b.dataset.civgo));
  panel.querySelectorAll("[data-civaddunder]").forEach((b) => b.onclick = () =>
    civPlaceForm(d, +b.dataset.civaddunder));
  panel.querySelectorAll("[data-civoutline]").forEach((b) => b.onclick = async () => {
    b.disabled = true; b.textContent = "Asking the Census…";
    try {
      const r = await api(`/api/civics/jurisdictions/${b.dataset.civoutline}/boundary`,
                          { method: "POST" });
      toast(`outlined, ${r.points} points`);
      renderCivics();
    } catch (e) { toast(e.message); b.disabled = false; b.textContent = "Draw its outline"; }
  });
  panel.querySelectorAll("[data-civagree]").forEach((b) => b.onclick = () =>
    civAgreementForm(d, null, +b.dataset.civagree));
}

function civPlaceForm(d, parentId) {
  const parent = d.jurisdictions.find((j) => j.id === parentId);
  modal(`<h3>Add a place${parent ? " inside " + esc(parent.name) : ""}</h3>
    <p class="dim">A bloc, a country, a state, a county, a district, a city,
      a school district, a ward or a homeowners' association. The point
      puts it on the map; a boundary is optional and is a GeoJSON geometry.</p>
    <div class="row2">
      <div><label>Name</label><input id="civ-name"></div>
      <div><label>Level</label><select id="civ-level">${d.levels.map((l) =>
        `<option value="${l.k}" ${!parent && l.k === "city" ? "selected" : ""}>${esc(l.label)}</option>`).join("")}</select></div>
    </div>
    <div class="row2">
      <div><label>Latitude</label><input id="civ-lat" type="number" step="any"
        value="${parent && parent.lat !== null ? parent.lat : ""}"></div>
      <div><label>Longitude</label><input id="civ-lng" type="number" step="any"
        value="${parent && parent.lng !== null ? parent.lng : ""}"></div>
    </div>
    <div class="row2">
      <div><label>Inside</label><select id="civ-parent"><option value="0">—</option>
        ${d.jurisdictions.map((j) => `<option value="${j.id}" ${j.id === parentId ? "selected" : ""}>${esc(j.name)}</option>`).join("")}</select></div>
      <div><label>Population</label><input id="civ-pop" type="number" min="0"></div>
    </div>
    <label>Boundary <span class="dim">(GeoJSON geometry, optional)</span></label>
    <textarea id="civ-geo" rows="3"></textarea>
    <label>Note</label><input id="civ-jnote" placeholder="what this one decides for us">
    <p><button class="btn" id="civ-psave">Add</button></p>`, "wide");
  $("#civ-psave").onclick = async () => {
    let boundary = null;
    const raw = $("#civ-geo").value.trim();
    if (raw) {
      try { boundary = JSON.parse(raw); } catch (err) { toast("that boundary is not JSON"); return; }
    }
    try {
      const r = await api("/api/civics/jurisdictions", { body: {
        name: $("#civ-name").value, level: $("#civ-level").value,
        parent_id: +$("#civ-parent").value,
        lat: $("#civ-lat").value === "" ? null : +$("#civ-lat").value,
        lng: $("#civ-lng").value === "" ? null : +$("#civ-lng").value,
        population: +$("#civ-pop").value || 0, note: $("#civ-jnote").value, boundary } });
      closeModal(); CIV_SEL = r.id; renderCivics();
    } catch (e) { toast(e.message); }
  };
}

function civAgreementForm(d, a, partyId) {
  const chosen = new Set(a ? [] : partyId ? [partyId] : []);
  modal(`<h3>${a ? "Edit" : "Add"} an agreement</h3>
    <p class="dim">A treaty, a trade pact, a defence alliance, membership
      of a body. Not a place — something two or more places agreed, so it
      has parties rather than a parent.</p>
    <div class="row2">
      <div><label>Name</label><input id="civ-aname" value="${esc(a ? a.name : "")}"
        placeholder="USMCA"></div>
      <div><label>Kind</label><select id="civ-akind">${d.agreement_kinds.map((k) =>
        `<option value="${k.k}" ${a && a.kind === k.k ? "selected" : ""}>${esc(k.label)}</option>`).join("")}</select></div>
    </div>
    <div class="row2">
      <div><label>Status</label><select id="civ-astatus">${["proposed", "signed", "in_force", "suspended", "ended"].map((k) =>
        `<option value="${k}" ${(a ? a.status : "in_force") === k ? "selected" : ""}>${k.replace(/_/g, " ")}</option>`).join("")}</select></div>
      <div><label>In force from</label><input id="civ-aforce" type="date"
        value="${a && a.in_force_at ? new Date(a.in_force_at * 1000).toISOString().slice(0, 10) : ""}"></div>
    </div>
    <label>Parties <span class="dim">(at least two)</span></label>
    <div class="perm-grid">${d.jurisdictions.filter((j) => ["bloc", "country", "state"].includes(j.level) || chosen.has(j.id)).map((j) =>
      `<label class="perm"><input type="checkbox" data-civparty="${j.id}" ${chosen.has(j.id) ? "checked" : ""}>
        <span><b>${esc(j.name)}</b><small>${esc(j.level)}</small></span></label>`).join("")
      || '<span class="dim">Watch some countries first — an agreement is between places.</span>'}</div>
    <div class="row2">
      <div><label>We are</label><select id="civ-apos">${d.positions.map((k) =>
        `<option value="${k}" ${a && a.position === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
      <div><label>Impact on us</label><select id="civ-aimpact">${d.impacts.map((k) =>
        `<option value="${k}" ${a && a.impact === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
    </div>
    <label>What it does to us</label><textarea id="civ-awhy" rows="2">${esc(a ? a.why : "")}</textarea>
    <label>Summary</label><textarea id="civ-asum" rows="2">${esc(a ? a.summary : "")}</textarea>
    <label>Link</label><input id="civ-aurl" value="${esc(a ? a.url : "")}">
    <p><button class="btn" id="civ-asave">Save</button></p>`, "wide");
  $("#civ-asave").onclick = async () => {
    const parties = [...modalBody().querySelectorAll("[data-civparty]:checked")]
      .map((c) => ({ jurisdiction_id: +c.dataset.civparty, role: "party" }));
    try {
      await api("/api/civics/agreements", { body: {
        id: a ? a.id : 0, name: $("#civ-aname").value, kind: $("#civ-akind").value,
        status: $("#civ-astatus").value,
        in_force_at: $("#civ-aforce").value ? new Date($("#civ-aforce").value).getTime() / 1000 : 0,
        position: $("#civ-apos").value, impact: $("#civ-aimpact").value,
        why: $("#civ-awhy").value, summary: $("#civ-asum").value,
        url: $("#civ-aurl").value, parties } });
      closeModal(); renderCivics();
    } catch (e) { toast(e.message); }
  };
}

async function renderCivics() {
  const d = await api("/api/civics");
  d.admin = S.user.is_admin || S.user.role === "admin" || S.user.role === "owner";
  const sel = d.jurisdictions.find((j) => j.id === CIV_SEL);
  const inScope = (x) => !CIV_SEL || x.jurisdiction_id === CIV_SEL;
  const measures = d.measures.filter(inScope);
  const elections = d.elections.filter(inScope);
  const giving = d.contributions.filter(inScope);
  const posPill = { support: "ok", oppose: "bad", watch: "", neutral: "" };
  const hasAny = d.map.jurisdictions.length || d.map.places.length;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Policy & elections</h2>
        <p class="dim">The places this business sits inside, from a treaty
          bloc down to the association that decides the signage, and what
          each is doing. ${esc(d.disclaimer)}</p></div>
      <div class="top-actions">
        ${d.admin ? `<button class="btn alt" id="civ-find">Find my jurisdictions</button>
        <button class="btn alt" id="civ-draw">Draw the boundaries</button>
        <button class="btn alt" id="civ-place">Add a place</button>
        <button class="btn" id="civ-measure">Track something</button>` : ""}
      </div>
    </div>
    <div class="tiles">
      <div class="card tile"><span class="dim">Watching</span>
        <b>${d.counts.watching}</b><span class="dim">jurisdictions</span></div>
      <div class="card tile"><span class="dim">Live measures</span>
        <b>${d.counts.live_measures}</b>
        <span class="dim">${d.counts.high_impact} would matter a lot</span></div>
      <div class="card tile"><span class="dim">Elections in 90 days</span>
        <b>${d.counts.elections_soon}</b></div>
      <div class="card tile"><span class="dim">Given</span>
        <b>${money(d.given_cents)}</b>
        <span class="dim">${d.undisclosed ? d.undisclosed + " without a filing reference" : "all referenced"}</span></div>
    </div>
    <div class="card civ-wrap">
      <div class="civ-split">
        <div id="civ-leaflet" class="civ-map"></div>
        <div id="civ-panel" class="civ-panel"></div>
      </div>
      <div class="civ-legend">
        <span class="dim">${hasAny ? "Click a place to open it. Scroll to zoom, drag to move."
          : "Every country is clickable. Find my jurisdictions puts your own stack on it."}</span>
        ${d.levels.map((l) => `<span class="civ-key"><i class="civ-${l.k}"></i>${esc(l.label)}</span>`).join("")}
        <span class="civ-key"><i class="civ-place"></i>your places</span>
        ${CIV_SEL ? '<button class="btn alt sm" id="civ-all">Show everything</button>' : ""}
        ${hasAny ? '<button class="btn alt sm" id="civ-fit">Fit</button>' : ""}
      </div>
    </div>
    <div class="card civ-time">
      <div class="civ-timehead">
        <b id="civ-tlhead">${CIV_ASOF ? "As of " + fmtDate(CIV_ASOF) : "Now"}</b>
        <span class="dim" id="civ-tlscope"></span>
        <button class="btn alt sm" id="civ-now" ${CIV_ASOF ? "" : "hidden"}>Back to now</button>
        <button class="btn alt sm" id="civ-federal" title="past and coming US general elections, computed — no key, no network">Add the federal election calendar</button>
      </div>
      <input type="range" id="civ-slider" min="0" max="1000" value="1000"
        aria-label="Move backwards and forwards in time">
      <div class="civ-timeaxis"><span id="civ-tlmin" class="dim"></span>
        <span id="civ-tlmax" class="dim"></span></div>
      <div id="civ-tl"></div>
    </div>
    <h3>What is moving${sel ? " in " + esc(sel.name) : ""}</h3>
    ${measures.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>measure</th><th>where</th><th>stage</th><th>we say</th>
        <th>last action</th><th></th></tr></thead>
      <tbody>${measures.map((m) => `<tr class="${m.closed ? "dim" : ""}">
        <td><b>${esc(m.ref || "—")}</b> ${esc(m.title)}
          ${m.why ? `<br><span class="dim">${esc(m.why)}</span>` : ""}</td>
        <td class="dim">${esc(m.jurisdiction || "")}</td>
        <td><span class="pill">${esc(m.status.replace(/_/g, " "))}</span></td>
        <td><span class="pill ${posPill[m.position] || ""}">${esc(m.position)}</span>
          ${m.impact === "high" ? '<span class="pill warn">high impact</span>' : ""}</td>
        <td class="dim">${m.last_action_at ? fmtDate(m.last_action_at) : ""}
          ${m.last_action ? `<br>${esc(m.last_action.slice(0, 70))}` : ""}</td>
        <td class="chips"><button class="btn alt sm" data-civm="${m.id}">Open</button>
          ${d.admin ? `<button class="btn alt sm" data-civmedit="${m.id}">Edit</button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("pin", "Nothing tracked here yet",
          "Add a bill, an ordinance or a ballot question, and say what it "
          + "would do to you — tracking one without that is a news feed.")}
    <h3>Agreements${sel ? " involving " + esc(sel.name) : ""}</h3>
    ${(sel ? d.agreements.filter((a) => true) : d.agreements).length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>agreement</th><th>kind</th><th>parties</th><th>status</th><th>we say</th><th></th></tr></thead>
      <tbody>${d.agreements.map((a) => `<tr>
        <td><b>${esc(a.name)}</b>${a.why ? `<br><span class="dim">${esc(a.why)}</span>` : ""}</td>
        <td class="dim">${esc((d.agreement_kinds.find((k) => k.k === a.kind) || {}).label || a.kind)}</td>
        <td>${a.parties}</td>
        <td><span class="pill">${esc(a.status.replace(/_/g, " "))}</span></td>
        <td><span class="pill ${posPill[a.position] || ""}">${esc(a.position)}</span></td>
        <td class="chips">${d.admin ? `<button class="btn alt sm" data-civaedit="${a.id}">Edit</button>
          <button class="btn alt sm" data-civadel="${a.id}">Remove</button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : `<div class="card"><p class="dim">No agreements recorded. A treaty, a
        trade pact or an alliance goes here, between the places it binds.</p>
        ${d.admin ? '<button class="btn alt sm" id="civ-agree">Add an agreement</button>' : ""}</div>`}
    <h3>Elections</h3>
    ${elections.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>when</th><th>what</th><th>where</th><th>registration closes</th></tr></thead>
      <tbody>${elections.map((e) => `<tr>
        <td>${fmtDate(e.at)}</td>
        <td>${esc(e.name)} <span class="dim">${esc(e.kind)}</span></td>
        <td class="dim">${esc(e.jurisdiction || "")}</td>
        <td class="dim">${e.registration_deadline ? fmtDate(e.registration_deadline) : "—"}</td>
      </tr>`).join("")}</tbody></table></div>
      ${d.admin ? `<div class="chips" style="margin-top:8px">
        <button class="btn alt sm" id="civ-election">Add an election</button></div>` : ""}</div>`
      : `<div class="card"><p class="dim">No elections on the calendar.</p>
        ${d.admin ? '<button class="btn alt sm" id="civ-election">Add one</button>' : ""}</div>`}
    <h3>Political giving</h3>
    <div class="card">
      <p class="dim">A disclosure record. Nothing here checks a
        contribution limit, reads a statute or files anything — the rules
        differ at every level above, and software that looked like it had
        checked would be worse than a spreadsheet.</p>
      ${giving.length ? `<div class="tablewrap"><table>
        <thead><tr><th>when</th><th>to</th><th>amount</th><th>where</th>
          <th>authorised by</th><th>filing</th></tr></thead>
        <tbody>${giving.map((x) => `<tr>
          <td class="dim">${fmtDate(x.at)}</td>
          <td>${esc(x.recipient)} <span class="dim">${esc(x.recipient_kind)}</span></td>
          <td>${money(x.amount_cents)}</td>
          <td class="dim">${esc(x.jurisdiction || "")}</td>
          <td class="dim">${esc(x.authorised_by)}</td>
          <td>${x.disclosure_ref ? esc(x.disclosure_ref)
            : '<span class="pill warn">not referenced</span>'}</td>
        </tr>`).join("")}</tbody></table></div>` : '<p class="dim">Nothing recorded.</p>'}
      ${d.admin ? `<div class="chips" style="margin-top:10px">
        <button class="btn alt sm" id="civ-give">Record giving</button>
        <a class="btn alt sm" href="/api/civics/contributions.csv?token=${
          encodeURIComponent(S.user.token)}">Export for a filing</a>
      </div>` : ""}
    </div>
    ${d.admin ? `<h3>Where the information comes from</h3>
    <p class="dim">The stack itself comes from the US Census Bureau's
      geocoder, which needs no key: Find my jurisdictions asks it. Who holds
      each office comes from the two below, each needing a key of its own.
      Neither covers everything, and below the state line most places
      publish nothing an API can read — typing a measure in by hand is a
      first-class path here rather than a fallback.</p>
    <div id="civ-cxn"></div>` : ""}`;

  try { await civReady(); civDraw(d); } catch (e) {
    $("#civ-leaflet").innerHTML = `<div class="civ-blank"><div><b>The map
      could not load.</b><span class="dim">${esc(e.message)}</span></div></div>`;
  }
  if (CIV_MAP) {
    if (CIV_SEL) civSelect(d, CIV_SEL); else { civFit(d); civPanel(d, null); }
  }
  civTimeline(d);
  if ($("#civ-all")) $("#civ-all").onclick = () => { CIV_SEL = 0; renderCivics(); };
  $("#civ-now").onclick = () => civSetTime(d, 0);
  $("#civ-federal").onclick = async () => {
    try {
      const r = await api("/api/civics/seed/federal-elections", { body: { years_back: 10, years_ahead: 6 } });
      toast(r.added ? `${r.added} election${r.added === 1 ? "" : "s"} added to the United States` : "already on the calendar");
      if (r.added) { CIV_SEL = CIV_SEL || r.jurisdiction_id; renderCivics(); }
    } catch (e) { toast(e.message); }
  };
  if ($("#civ-fit")) $("#civ-fit").onclick = () => civFit(d);
  if ($("#civ-place")) $("#civ-place").onclick = () => civPlaceForm(d, 0);
  if ($("#civ-agree")) $("#civ-agree").onclick = () => civAgreementForm(d, null, 0);
  view().querySelectorAll("[data-civaedit]").forEach((b) => b.onclick = async () =>
    civAgreementForm(d, await api(`/api/civics/agreements/${b.dataset.civaedit}`), 0));
  view().querySelectorAll("[data-civadel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Remove this agreement from the register?")) return;
    await api(`/api/civics/agreements/${b.dataset.civadel}`, { method: "DELETE" });
    renderCivics();
  });

  if ($("#civ-draw")) $("#civ-draw").onclick = async () => {
    const b = $("#civ-draw"); b.disabled = true; b.textContent = "Asking the Census…";
    try {
      const r = await api("/api/civics/boundaries", { method: "POST" });
      toast(r.drawn.length ? `${r.drawn.length} outline(s) drawn`
        : r.failed.length ? `none drawn — ${r.failed[0].why}`
        : "every Census-placed jurisdiction already has its outline");
      renderCivics();
    } catch (e) { toast(e.message); b.disabled = false; b.textContent = "Draw the boundaries"; }
  };
  if ($("#civ-find")) $("#civ-find").onclick = () => {
    modal(`<h3>Find my jurisdictions</h3>
      <p class="dim">The US Census Bureau's geocoder places an address and
        says what it is inside: state, county, city, congressional district,
        both state chambers, the school district. No key, no account. US
        addresses only, and it wants a street, a city and a state.</p>
      <label>Address</label><input id="civ-addr" placeholder="12 Main St, Springfield, IL 62701">
      <p><button class="btn" id="civ-findgo">Find</button></p>
      <p id="civ-findout" class="dim"></p>`);
    $("#civ-findgo").onclick = async () => {
      const b = $("#civ-findgo"); b.disabled = true;
      $("#civ-findout").textContent = "asking the Census Bureau…";
      try {
        const r = await api("/api/civics/find", { body: { address: $("#civ-addr").value } });
        let reps = "";
        try {
          const rr = await api("/api/civics/representatives", { body: {
            lat: r.lat, lng: r.lng, state_fips: r.state_fips, district: r.district } });
          reps = ["state", "federal"].map((k) => {
            const v = rr[k];
            if (!v) return "";
            return `${k}: ${v.ok === false ? esc(v.why) : (v.new || 0) + " new"}`;
          }).filter(Boolean).join(" · ");
        } catch (e) { reps = e.message; }
        const drawn = r.boundaries ? r.boundaries.drawn.length : 0;
        $("#civ-findout").innerHTML = `<b>${esc(r.matched)}</b> — ${r.jurisdictions.length}
          jurisdictions on the register${drawn ? `, ${drawn} outlined` : ""}.${
          reps ? "<br>Officials — " + reps : ""}`;
        setTimeout(() => { closeModal(); CIV_SEL = r.jurisdictions[r.jurisdictions.length - 1] || 0; renderCivics(); }, 1800);
      } catch (e) { $("#civ-findout").innerHTML = `<span class="low">${esc(e.message)}</span>`; b.disabled = false; }
    };
  };

  const measureForm = (m) => {
    modal(`<h3>${m ? "Edit" : "Track"} a measure</h3>
      <label>Title</label><input id="civ-mtitle" value="${esc(m ? m.title : "")}"
        placeholder="Minimum wage increase">
      <div class="row2">
        <div><label>Reference</label><input id="civ-mref" value="${esc(m ? m.ref : "")}"
          placeholder="HB 1234"></div>
        <div><label>Where</label><select id="civ-mjur"><option value="0">—</option>
          ${d.jurisdictions.map((j) => `<option value="${j.id}" ${
            (m ? m.jurisdiction_id : CIV_SEL) === j.id ? "selected" : ""}>${esc(j.name)}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Kind</label><select id="civ-mkind">${d.measure_kinds.map((k) =>
          `<option value="${k}" ${m && m.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
        <div><label>Stage</label><select id="civ-mstatus">${d.statuses.map((k) =>
          `<option value="${k}" ${m && m.status === k ? "selected" : ""}>${k.replace(/_/g, " ")}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>We are</label><select id="civ-mpos">${d.positions.map((k) =>
          `<option value="${k}" ${m && m.position === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
        <div><label>Impact on us</label><select id="civ-mimpact">${d.impacts.map((k) =>
          `<option value="${k}" ${m && m.impact === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
      </div>
      <label>What it would do to us</label>
      <textarea id="civ-mwhy" rows="2">${esc(m ? m.why : "")}</textarea>
      <label>Summary</label><textarea id="civ-msum" rows="3">${esc(m ? m.summary : "")}</textarea>
      <label>Link</label><input id="civ-murl" value="${esc(m ? m.url : "")}">
      <p><button class="btn" id="civ-msave">Save</button></p>`, "wide");
    $("#civ-msave").onclick = async () => {
      try {
        await api("/api/civics/measures", { body: {
          id: m ? m.id : 0, title: $("#civ-mtitle").value,
          ref: $("#civ-mref").value, jurisdiction_id: +$("#civ-mjur").value,
          kind: $("#civ-mkind").value, status: $("#civ-mstatus").value,
          position: $("#civ-mpos").value, impact: $("#civ-mimpact").value,
          why: $("#civ-mwhy").value, summary: $("#civ-msum").value,
          url: $("#civ-murl").value } });
        closeModal(); renderCivics();
      } catch (e) { toast(e.message); }
    };
  };
  if ($("#civ-measure")) $("#civ-measure").onclick = () => measureForm(null);
  view().querySelectorAll("[data-civmedit]").forEach((b) => b.onclick = () =>
    measureForm(d.measures.find((m) => m.id === +b.dataset.civmedit)));
  view().querySelectorAll("[data-civm]").forEach((b) => b.onclick = async () => {
    const m = await api(`/api/civics/measures/${b.dataset.civm}`);
    modal(`<h3>${esc(m.ref || "")} ${esc(m.title)}</h3>
      <p class="dim">${esc(m.jurisdiction || "")} · ${esc(m.status.replace(/_/g, " "))}
        · we ${esc(m.position)} · ${esc(m.impact)} impact</p>
      ${m.why ? `<div class="card"><b>What it would do to us</b><p>${esc(m.why)}</p></div>` : ""}
      ${m.summary ? `<p>${esc(m.summary)}</p>` : ""}
      ${m.url ? `<p><a href="${esc(m.url)}" target="_blank" rel="noopener">The text of it</a></p>` : ""}
      <h3 style="font-size:15px">What has happened</h3>
      ${m.events.length ? `<div class="tablewrap"><table><tbody>${m.events.map((e) =>
        `<tr><td class="dim">${fmtDate(e.at)}</td><td>${esc(e.what)}</td></tr>`).join("")}
        </tbody></table></div>` : '<p class="dim">Nothing recorded yet.</p>'}
      <label>Add what just happened</label><input id="civ-mev">
      <p><button class="btn sm" id="civ-mevsave">Record it</button></p>`, "wide");
    $("#civ-mevsave").onclick = async () => {
      try {
        await api(`/api/civics/measures/${m.id}/events`, { body: { what: $("#civ-mev").value } });
        closeModal(); renderCivics();
      } catch (e) { toast(e.message); }
    };
  });
  if ($("#civ-election")) $("#civ-election").onclick = () => {
    modal(`<h3>Add an election</h3>
      <label>What</label><input id="civ-ename" placeholder="State general, or the HOA annual meeting">
      <div class="row2">
        <div><label>Kind</label><select id="civ-ekind">${d.election_kinds.map((k) =>
          `<option value="${k}">${k}</option>`).join("")}</select></div>
        <div><label>Where</label><select id="civ-ejur"><option value="0">—</option>
          ${d.jurisdictions.map((j) => `<option value="${j.id}" ${CIV_SEL === j.id ? "selected" : ""}>${esc(j.name)}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Date</label><input id="civ-edate" type="date"></div>
        <div><label>Registration closes</label><input id="civ-ereg" type="date"></div>
      </div>
      <p><button class="btn" id="civ-esave">Add</button></p>`);
    $("#civ-esave").onclick = async () => {
      const ts = (id) => $(id).value ? new Date($(id).value).getTime() / 1000 : 0;
      try {
        await api("/api/civics/elections", { body: {
          name: $("#civ-ename").value, kind: $("#civ-ekind").value,
          jurisdiction_id: +$("#civ-ejur").value, at: ts("#civ-edate"),
          registration_deadline: ts("#civ-ereg") } });
        closeModal(); renderCivics();
      } catch (e) { toast(e.message); }
    };
  };
  if ($("#civ-give")) $("#civ-give").onclick = () => {
    modal(`<h3>Record political giving</h3>
      <p class="dim">For disclosure. Every field here is one a filing asks
        for; nothing here checks a limit or files anything.</p>
      <div class="row2">
        <div><label>To</label><input id="civ-grecip"></div>
        <div><label>What they are</label><select id="civ-gkind">${d.recipient_kinds.map((k) =>
          `<option value="${k}">${k.replace(/_/g, " ")}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Amount ($)</label><input id="civ-gamt" type="number" step="0.01"></div>
        <div><label>When</label><input id="civ-gdate" type="date"></div>
      </div>
      <div class="row2">
        <div><label>Under which jurisdiction's rules</label>
          <select id="civ-gjur"><option value="0">—</option>
          ${d.jurisdictions.map((j) => `<option value="${j.id}">${esc(j.name)}</option>`).join("")}</select></div>
        <div><label>How</label><input id="civ-gmethod" placeholder="transfer"></div>
      </div>
      <div class="row2">
        <div><label>Authorised by</label><input id="civ-gauth" placeholder="who said yes"></div>
        <div><label>Their filer id</label><input id="civ-grid"></div>
      </div>
      <label>Filing reference <span class="dim">(where it appears; add it later if you must)</span></label>
      <input id="civ-gref">
      <label>Note</label><input id="civ-gnote">
      <p><button class="btn" id="civ-gsave">Record</button></p>`, "wide");
    $("#civ-gsave").onclick = async () => {
      try {
        await api("/api/civics/contributions", { body: {
          recipient: $("#civ-grecip").value, recipient_kind: $("#civ-gkind").value,
          recipient_id: $("#civ-grid").value,
          amount_cents: Math.round(parseFloat($("#civ-gamt").value || 0) * 100),
          at: $("#civ-gdate").value ? new Date($("#civ-gdate").value).getTime() / 1000 : 0,
          jurisdiction_id: +$("#civ-gjur").value, method: $("#civ-gmethod").value,
          authorised_by: $("#civ-gauth").value, disclosure_ref: $("#civ-gref").value,
          note: $("#civ-gnote").value } });
        closeModal(); renderCivics();
      } catch (e) { toast(e.message); }
    };
  };
  if ($("#civ-cxn")) {
    connectionCards(["open_states", "congress_gov"], renderCivics, $("#civ-cxn"))
      .then(() => {
        d.connections.filter((c) => c.connected).forEach((c) => {
          const card = view().querySelector(`[data-cxn="${c.name}"] .doc-top`);
          if (!card) return;
          const b = document.createElement("button");
          b.className = "btn alt sm";
          b.textContent = "Search bills";
          b.onclick = async () => {
            const q = prompt("What to search for — a narrow term works better "
              + "than a broad one.", "minimum wage");
            if (q === null) return;
            try {
              const r = await api(`/api/civics/pull/${c.name}`, { body: { query: q } });
              toast(`${r.new} new`); renderCivics();
            } catch (e) { toast(e.message); }
          };
          card.appendChild(b);
        });
      });
  }
}


/* The timeline for whatever the map has selected, and a slider through it.
   Scope is the point: with a county selected it shows the county's own
   events, the state's and the country's above it — a state law applies
   to the county, so it belongs here — and everything inside it, marked.
   The slider sets the date the whole page is looked at as of: the panel
   shows a place as it was, and events after the date fade. The map does
   not redraw for the date; a county's outline is its outline now, and
   the screen says so rather than pretending otherwise. */
async function civTimeline(d) {
  const host = $("#civ-tl");
  const slider = $("#civ-slider");
  if (!host || !slider) return;
  let tl;
  try {
    tl = await api(`/api/civics/timeline${CIV_SEL ? "?jurisdiction_id=" + CIV_SEL : ""}`);
  } catch (e) { host.innerHTML = `<p class="low">${esc(e.message)}</p>`; return; }
  CIV_TL = tl;
  const sel = d.jurisdictions.find((j) => j.id === CIV_SEL);
  const c = tl.counts;
  $("#civ-tlscope").textContent = sel
    ? `${esc(sel.name)}: ${c.own} of its own, ${c.inherited} from above, ${c.inside} inside it`
    : `the whole world: ${tl.events.length} dated things`;
  const now = Date.now() / 1000;
  // The axis runs from the earliest thing known to a little past now, so
  // the right-hand end is always "now" and the future stays reachable.
  const lo = tl.span.min ? Math.min(tl.span.min, now - 365 * 86400) : now - 365 * 86400;
  const hi = Math.max(tl.span.max || 0, now) + 30 * 86400;
  $("#civ-tlmin").textContent = fmtDate(lo);
  $("#civ-tlmax").textContent = fmtDate(hi);
  const toT = (v) => lo + (hi - lo) * (v / 1000);
  const toV = (t) => Math.round((t - lo) / (hi - lo) * 1000);
  slider.value = CIV_ASOF ? toV(CIV_ASOF) : toV(now);
  let pending = null;
  slider.oninput = () => {
    const t = toT(+slider.value);
    const atNow = Math.abs(t - now) < 3 * 86400;
    $("#civ-tlhead").textContent = atNow ? "Now" : "As of " + fmtDate(t);
    $("#civ-now").hidden = atNow;
    civDrawTimeline(tl, t, d);
    clearTimeout(pending);
    pending = setTimeout(() => civSetTime(d, atNow ? 0 : t, true), 350);
  };
  slider._toV = toV;
  civDrawTimeline(tl, CIV_ASOF || now, d);
}

/* The date the page is looked at as of. Only the panel is refetched —
   the map stays where it is, because redrawing it for a date it cannot
   honour would be motion without meaning. */
function civSetTime(d, t, fromSlider = false) {
  CIV_ASOF = t;
  const slider = $("#civ-slider");
  if (slider && !fromSlider && slider._toV) {
    slider.value = slider._toV(t || Date.now() / 1000);
    $("#civ-tlhead").textContent = t ? "As of " + fmtDate(t) : "Now";
    $("#civ-now").hidden = !t;
    if (CIV_TL) civDrawTimeline(CIV_TL, t || Date.now() / 1000, d);
  }
  if (CIV_SEL) civPanel(d, CIV_SEL);
}

function civDrawTimeline(tl, asOf, d) {
  const host = $("#civ-tl");
  if (!host) return;
  if (!tl.events.length) {
    host.innerHTML = `<p class="dim">Nothing dated yet${CIV_SEL ? " for this place or the places around it" : ""}.
      Measures, elections, agreements, officials' terms and giving all land here as they are recorded.</p>`;
    return;
  }
  const scopeLabel = { own: "here", inherited: "applies from above", inside: "inside", world: "" };
  const kindIcon = { measure: "pen", election: "calendar", agreement: "handshake",
    official: "user", giving: "card" };
  let lastDay = "";
  host.innerHTML = `<ul class="civ-tllist">${tl.events.map((e) => {
    const day = fmtDate(e.at);
    const head = day !== lastDay ? `<li class="civ-tlday">${esc(day)}</li>` : "";
    lastDay = day;
    return head + `<li class="civ-tlev ${e.scope}${e.at > asOf ? " future" : ""}"
        data-civtl="${e.jurisdiction_id}">
      <span class="ic">${opsIcon(kindIcon[e.kind] || "pin")}</span>
      <span><b>${esc(e.what)}</b>${e.detail ? ` <span class="dim">— ${esc(e.detail)}</span>` : ""}
        <br><span class="dim">${esc(e.jurisdiction)}${e.level ? " · " + esc(e.level) : ""}${
          scopeLabel[e.scope] ? " · " + scopeLabel[e.scope] : ""}</span></span>
    </li>`;
  }).join("")}</ul>`;
  host.querySelectorAll("[data-civtl]").forEach((li) => li.onclick = () => {
    const id = +li.dataset.civtl;
    if (id && id !== CIV_SEL) civSelect(d, id);
  });
  // Keep the "now" line in view when the slider has moved a long way.
  const first = host.querySelector(".civ-tlev.future");
  if (first && Math.abs(asOf - Date.now() / 1000) > 3 * 86400)
    first.scrollIntoView({ block: "center" });
}
