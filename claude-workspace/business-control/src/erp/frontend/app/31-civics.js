// ---------- policy and elections ----------
/* A business sits inside a stack of jurisdictions at once, and every one
   of them can change a rule that costs it money. This holds what those
   are, who runs them, what they are currently doing about it, and when
   the next election is — with a register of political giving kept apart,
   because that one is a disclosure record and nothing else.

   The map is drawn here, from what the install knows: no tiles, no
   outside service, nothing sent anywhere. That is a real limit — there
   is no basemap, so a jurisdiction is where somebody said it is — and it
   is why the page works on a laptop with no internet. */

let CIV_SEL = 0;      // the jurisdiction filtering everything below
let CIV_VIEW = null;  // {x, y, w, h} of the map's viewBox, for pan and zoom

const civProject = (lat, lng) => ({
  // Equirectangular, with latitude stretched by the cosine of the middle
  // of the data. A plain lat/lng plot squashes anything far from the
  // equator sideways, and a map of one county is entirely "far from the
  // equator".
  x: lng * 100,
  y: -lat * 100,
});

function civBounds(m) {
  const pts = [];
  m.jurisdictions.forEach((j) => {
    if (j.lat !== null && j.lng !== null) pts.push(civProject(j.lat, j.lng));
    if (j.boundary) civRings(j.boundary).forEach((ring) =>
      ring.forEach(([lng, lat]) => pts.push(civProject(lat, lng))));
  });
  m.places.forEach((p) => pts.push(civProject(p.lat, p.lng)));
  if (!pts.length) return { x: -18000, y: -5000, w: 36000, h: 18000 };
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const pad = Math.max(120, (Math.max(...xs) - Math.min(...xs)) * 0.15,
                       (Math.max(...ys) - Math.min(...ys)) * 0.15);
  return { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad,
           w: (Math.max(...xs) - Math.min(...xs)) + pad * 2,
           h: (Math.max(...ys) - Math.min(...ys)) + pad * 2 };
}

function civRings(geom) {
  if (!geom || !geom.coordinates) return [];
  if (geom.type === "Polygon") return geom.coordinates;
  if (geom.type === "MultiPolygon") return geom.coordinates.flat();
  return [];
}

function civPath(geom) {
  return civRings(geom).map((ring) => ring.map(([lng, lat], i) => {
    const p = civProject(lat, lng);
    return `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
  }).join(" ") + " Z").join(" ");
}

const CIV_R = { country: 13, state: 10, county: 8, district: 7, city: 6,
  ward: 5, other: 5 };

function civMap(m) {
  const vb = CIV_VIEW || civBounds(m);
  const marks = m.jurisdictions.filter((j) => j.lat !== null && j.lng !== null);
  return `<svg id="civ-svg" viewBox="${vb.x} ${vb.y} ${vb.w} ${vb.h}"
      preserveAspectRatio="xMidYMid meet" class="civ-map" role="img"
      aria-label="The jurisdictions this business sits in, and its own places">
    <rect x="${vb.x}" y="${vb.y}" width="${vb.w}" height="${vb.h}"
      class="civ-bg"></rect>
    ${m.jurisdictions.filter((j) => j.boundary).map((j) =>
      `<path d="${civPath(j.boundary)}" class="civ-area${
        CIV_SEL === j.id ? " on" : ""}" data-civpick="${j.id}"><title>${
        esc(j.name)}</title></path>`).join("")}
    ${m.places.map((p) => {
      const q = civProject(p.lat, p.lng);
      const r = Math.max(vb.w, vb.h) / 110;
      return `<rect x="${(q.x - r / 2).toFixed(1)}" y="${(q.y - r / 2).toFixed(1)}"
        width="${r.toFixed(1)}" height="${r.toFixed(1)}" class="civ-place"
        ><title>${esc(p.name)}${p.city ? " · " + esc(p.city) : ""}</title></rect>`;
    }).join("")}
    ${marks.map((j) => {
      const q = civProject(j.lat, j.lng);
      const r = (CIV_R[j.level] || 6) * Math.max(vb.w, vb.h) / 1600;
      return `<circle cx="${q.x.toFixed(1)}" cy="${q.y.toFixed(1)}"
        r="${Math.max(1.5, r).toFixed(1)}"
        class="civ-dot civ-${esc(j.level)}${CIV_SEL === j.id ? " on" : ""}${
          j.watching ? "" : " off"}" data-civpick="${j.id}"
        ><title>${esc(j.name)} · ${esc(j.level)}</title></circle>`;
    }).join("")}
  </svg>`;
}

function civWire(m) {
  const svg = $("#civ-svg");
  if (!svg) return;
  const box = () => CIV_VIEW || civBounds(m);
  const apply = (v) => {
    CIV_VIEW = v;
    svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  };
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const v = box();
    const k = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    const r = svg.getBoundingClientRect();
    // Zoom toward the pointer rather than the middle, so the thing you
    // are looking at stays where you are looking.
    const fx = (e.clientX - r.left) / r.width;
    const fy = (e.clientY - r.top) / r.height;
    apply({ x: v.x + v.w * fx * (1 - k), y: v.y + v.h * fy * (1 - k),
            w: v.w * k, h: v.h * k });
  }, { passive: false });
  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY, v: box(), moved: false };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const r = svg.getBoundingClientRect();
    const dx = (e.clientX - drag.x) / r.width * drag.v.w;
    const dy = (e.clientY - drag.y) / r.height * drag.v.h;
    if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
    apply({ ...drag.v, x: drag.v.x - dx, y: drag.v.y - dy });
  });
  svg.addEventListener("pointerup", (e) => {
    const wasDrag = drag && drag.moved;
    drag = null;
    // A drag that ends on a shape must not also select it, or the map
    // reselects something every time somebody moves it.
    if (wasDrag) return;
    const hit = e.target.closest("[data-civpick]");
    if (!hit) return;
    CIV_SEL = CIV_SEL === +hit.dataset.civpick ? 0 : +hit.dataset.civpick;
    renderCivics();
  });
}

async function renderCivics() {
  const d = await api("/api/civics");
  const admin = S.user.is_admin || S.user.role === "admin"
    || S.user.role === "owner";
  const sel = d.jurisdictions.find((j) => j.id === CIV_SEL);
  const inScope = (x) => !CIV_SEL || x.jurisdiction_id === CIV_SEL;
  const measures = d.measures.filter(inScope);
  const elections = d.elections.filter(inScope);
  const officials = d.officials.filter(inScope);
  const giving = d.contributions.filter(inScope);
  const levelOf = Object.fromEntries(d.levels.map((l) => [l.k, l.label]));
  const posPill = { support: "ok", oppose: "bad", watch: "", neutral: "" };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Policy & elections</h2>
        <p class="dim">The places this business sits inside and what they
          are doing about it. ${esc(d.disclaimer)}</p></div>
      <div class="top-actions">
        ${admin ? `<button class="btn alt" id="civ-place">Add a place</button>
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
      ${civMap(d.map)}
      <div class="civ-legend">
        <span class="dim">Scroll to zoom, drag to move, click to filter.</span>
        ${d.levels.map((l) => `<span class="civ-key"><i class="civ-dot civ-${l.k}"></i>${esc(l.label)}</span>`).join("")}
        <span class="civ-key"><i class="civ-place"></i>your places</span>
        ${CIV_SEL ? `<button class="btn alt sm" id="civ-all">Show everything</button>` : ""}
        <button class="btn alt sm" id="civ-fit">Fit</button>
      </div>
      ${sel ? `<p class="dim">Filtered to <b>${esc(sel.name)}</b> ·
        ${esc(levelOf[sel.level] || sel.level)}${sel.population
          ? ` · population ${sel.population.toLocaleString()}` : ""}</p>` : ""}
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
          ${admin ? `<button class="btn alt sm" data-civmedit="${m.id}">Edit</button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("pin", "Nothing tracked here yet",
          "Add a bill, an ordinance or a ballot question, and say what it "
          + "would do to you — tracking one without that is a news feed.")}
    <h3>Elections</h3>
    ${elections.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>when</th><th>what</th><th>where</th><th>registration closes</th></tr></thead>
      <tbody>${elections.map((e) => `<tr>
        <td>${fmtDate(e.at)}</td>
        <td>${esc(e.name)} <span class="dim">${esc(e.kind)}</span></td>
        <td class="dim">${esc(e.jurisdiction || "")}</td>
        <td class="dim">${e.registration_deadline ? fmtDate(e.registration_deadline) : "—"}</td>
      </tr>`).join("")}</tbody></table></div>
      ${admin ? `<div class="chips" style="margin-top:8px">
        <button class="btn alt sm" id="civ-election">Add an election</button></div>` : ""}</div>`
      : `<div class="card"><p class="dim">No elections on the calendar.</p>
        ${admin ? '<button class="btn alt sm" id="civ-election">Add one</button>' : ""}</div>`}
    ${officials.length ? `<h3>Who to call</h3>
    <div class="card"><div class="tablewrap"><table>
      <thead><tr><th>who</th><th>office</th><th>where</th><th>reach them</th></tr></thead>
      <tbody>${officials.map((o) => `<tr>
        <td><b>${esc(o.name)}</b>${o.party ? `<br><span class="dim">${esc(o.party)}</span>` : ""}</td>
        <td>${esc(o.office)}${o.district ? `<span class="dim"> ${esc(o.district)}</span>` : ""}</td>
        <td class="dim">${esc(o.jurisdiction || "")}</td>
        <td class="dim">${esc(o.email || "")}${o.phone ? "<br>" + esc(o.phone) : ""}
          ${o.url ? `<br><a href="${esc(o.url)}" target="_blank" rel="noopener">page</a>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>` : ""}
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
      ${admin ? `<div class="chips" style="margin-top:10px">
        <button class="btn alt sm" id="civ-give">Record giving</button>
        <a class="btn alt sm" href="/api/civics/contributions.csv?token=${
          encodeURIComponent(S.user.token)}">Export for a filing</a>
      </div>` : ""}
    </div>
    ${admin ? `<h3>Where the information comes from</h3>
    <p class="dim">None of these covers everything. Open States is US state
      legislatures, Congress.gov is the federal one, and Google Civic
      answers who represents an address. Below the state line most places
      publish nothing an API can read, which is why typing a measure in by
      hand is a first-class path here rather than a fallback.</p>
    <div id="civ-cxn"></div>` : ""}`;

  civWire(d.map);
  if ($("#civ-all")) $("#civ-all").onclick = () => { CIV_SEL = 0; renderCivics(); };
  $("#civ-fit").onclick = () => { CIV_VIEW = null; renderCivics(); };

  if ($("#civ-place")) $("#civ-place").onclick = () => {
    modal(`<h3>Add a place</h3>
      <p class="dim">A city, county, district, state or country this
        business is inside. The point puts it on the map; a boundary is
        optional and comes from a GeoJSON geometry if you have one.</p>
      <div class="row2">
        <div><label>Name</label><input id="civ-name"></div>
        <div><label>Level</label><select id="civ-level">${d.levels.map((l) =>
          `<option value="${l.k}">${esc(l.label)}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Latitude</label><input id="civ-lat" type="number" step="any"></div>
        <div><label>Longitude</label><input id="civ-lng" type="number" step="any"></div>
      </div>
      <div class="row2">
        <div><label>Inside</label><select id="civ-parent"><option value="0">—</option>
          ${d.jurisdictions.map((j) => `<option value="${j.id}">${esc(j.name)}</option>`).join("")}</select></div>
        <div><label>Population</label><input id="civ-pop" type="number" min="0"></div>
      </div>
      <label>Boundary <span class="dim">(a GeoJSON geometry, optional)</span></label>
      <textarea id="civ-geo" rows="3" placeholder='{"type":"Polygon","coordinates":[[[...]]]}'></textarea>
      <p><button class="btn" id="civ-psave">Add</button></p>`, "wide");
    $("#civ-psave").onclick = async () => {
      let boundary = null;
      const raw = $("#civ-geo").value.trim();
      if (raw) {
        try { boundary = JSON.parse(raw); }
        catch (err) { toast("that boundary is not JSON"); return; }
      }
      try {
        await api("/api/civics/jurisdictions", { body: {
          name: $("#civ-name").value, level: $("#civ-level").value,
          parent_id: +$("#civ-parent").value,
          lat: $("#civ-lat").value === "" ? null : +$("#civ-lat").value,
          lng: $("#civ-lng").value === "" ? null : +$("#civ-lng").value,
          population: +$("#civ-pop").value || 0, boundary } });
        closeModal(); CIV_VIEW = null; renderCivics();
      } catch (e) { toast(e.message); }
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
            m && m.jurisdiction_id === j.id ? "selected" : ""}>${esc(j.name)}</option>`).join("")}</select></div>
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
      ${m.why ? `<div class="card"><b>What it would do to us</b>
        <p>${esc(m.why)}</p></div>` : ""}
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
      <label>What</label><input id="civ-ename" placeholder="State general">
      <div class="row2">
        <div><label>Kind</label><select id="civ-ekind">${d.election_kinds.map((k) =>
          `<option value="${k}">${k}</option>`).join("")}</select></div>
        <div><label>Where</label><select id="civ-ejur"><option value="0">—</option>
          ${d.jurisdictions.map((j) => `<option value="${j.id}">${esc(j.name)}</option>`).join("")}</select></div>
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
    connectionCards(["open_states", "congress_gov", "google_civic"],
                    renderCivics, $("#civ-cxn")).then(() => {
      d.connections.filter((c) => c.connected).forEach((c) => {
        const card = view().querySelector(`[data-cxn="${c.name}"] .doc-top`);
        if (!card) return;
        const b = document.createElement("button");
        b.className = "btn alt sm";
        b.textContent = c.name === "google_civic" ? "Pull representatives"
          : "Search bills";
        b.onclick = async () => {
          const q = c.name === "google_civic" ? "" :
            prompt("What to search for — a narrow term works better than a "
              + "broad one.", "minimum wage");
          if (q === null && c.name !== "google_civic") return;
          try {
            const r = await api(`/api/civics/pull/${c.name}`, { body: { query: q || "" } });
            toast(`${r.new} new`);
            renderCivics();
          } catch (e) { toast(e.message); }
        };
        card.appendChild(b);
      });
    });
  }
}
