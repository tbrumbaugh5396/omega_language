// ---------- ideas: notes that link, and the graph they make ----------
/* A note is a title and some text. Write another note's title in double
   brackets and the two are linked; the graph on the left is what points
   at what. A title that is linked to but not yet written is a dotted
   node — the graph's way of saying what has not been thought through.
   The layout is a small force simulation, run here, because a graph of a
   few hundred notes does not need a library to fall into shape. */
let IDE_SEL = 0;          // the open note
let IDE_G = null;         // the graph as last fetched
let IDE_POS = {};         // node key -> {x, y}, kept across redraws
let IDE_RAF = 0;

const ideKey = (n) => n.id ? "n" + n.id : "g" + n.slug;

async function renderIdeas(q = "") {
  const d = await api(`/api/ideas${q ? "?q=" + encodeURIComponent(q) : ""}`);
  IDE_G = d;
  const hits = new Set(d.hits || []);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Ideas</h2>
        <p class="dim">Notes that point at each other. Write <code>[[a title]]</code>
          in a note and the link exists; the graph is what points at what.
          A dotted node is a title something refers to that nobody has
          written yet.</p></div>
      <div class="top-actions">
        <input id="ide-q" placeholder="find in notes" value="${esc(q)}"
          aria-label="find in notes">
        <button class="btn" id="ide-new">New note</button>
      </div>
    </div>
    <div class="ide-split">
      <div class="card ide-graph">
        <svg id="ide-svg" viewBox="0 0 800 560" preserveAspectRatio="xMidYMid meet"
          aria-label="graph of ideas"></svg>
        <div class="ide-legend dim">${d.nodes.length} note${d.nodes.length === 1 ? "" : "s"},
          ${d.links.length} link${d.links.length === 1 ? "" : "s"}${
          d.ghosts.length ? `, ${d.ghosts.length} not written yet` : ""}
          · drag to move, click to open, scroll to zoom</div>
      </div>
      <div class="card ide-side" id="ide-side">
        ${d.nodes.length ? `<ul class="ide-list">${d.nodes
          .slice().sort((a, b) => (b.pinned - a.pinned) || b.updated_at - a.updated_at)
          .map((n) => `<li data-ide="${n.id}" class="${hits.has(n.id) ? "hit" : ""}${
            q && !hits.has(n.id) ? " dim" : ""}">
            <span class="ide-dot" style="background:${esc(n.colour || "var(--accent)")}"></span>
            <b>${esc(n.title)}</b> <span class="dim">${n.degree} link${n.degree === 1 ? "" : "s"}</span>
            ${n.tags.length ? `<br><span class="dim">${n.tags.map(esc).join(" · ")}</span>` : ""}
          </li>`).join("")}</ul>`
          : `<p class="dim">Nothing yet. Start with the thing you keep meaning
             to write down, and put the next one in [[brackets]] inside it.</p>`}
      </div>
    </div>`;
  $("#ide-new").onclick = () => ideForm();
  $("#ide-q").onkeydown = (e) => { if (e.key === "Enter") renderIdeas(e.target.value.trim()); };
  view().querySelectorAll("[data-ide]").forEach((li) => li.onclick = () => ideOpen(+li.dataset.ide));
  ideGraph(d, hits);
  if (IDE_SEL && d.nodes.some((n) => n.id === IDE_SEL)) ideOpen(IDE_SEL);
}

/* A force layout: links pull, everything repels, the middle attracts
   gently so a disconnected note does not drift off the edge. Positions
   survive a redraw so the graph does not reshuffle when a note is saved. */
function ideGraph(d, hits) {
  const svg = $("#ide-svg");
  if (!svg) return;
  cancelAnimationFrame(IDE_RAF);
  const W = 800, H = 560;
  const nodes = [...d.nodes.map((n) => ({ ...n, key: ideKey(n) })),
    ...d.ghosts.map((g) => ({ ...g, key: "g" + g.slug, ghost: true, degree: 1 }))];
  const byKey = Object.fromEntries(nodes.map((n) => [n.key, n]));
  const links = d.links.map((l) => ({
    a: byKey["n" + l.from_id],
    b: byKey[l.to_id ? "n" + l.to_id : "g" + String(l.to_title).toLowerCase().split(/\s+/).join(" ").trim()],
    kind: l.kind, label: l.label,
  })).filter((l) => l.a && l.b);
  nodes.forEach((n, i) => {
    const p = IDE_POS[n.key];
    const ang = i / Math.max(nodes.length, 1) * Math.PI * 2;
    n.x = p ? p.x : W / 2 + Math.cos(ang) * 160;
    n.y = p ? p.y : H / 2 + Math.sin(ang) * 160;
    n.vx = 0; n.vy = 0;
    n.r = n.ghost ? 6 : 7 + Math.min(10, (n.degree || 0) * 1.6);
  });
  let zoom = { k: 1, x: 0, y: 0 };
  svg.innerHTML = `<g id="ide-zoom">
    <g id="ide-links">${links.map((l, i) => `<line data-l="${i}" class="ide-link ${l.kind}"></line>`).join("")}</g>
    <g id="ide-labels">${links.filter((l) => l.label).map((l) => `<text class="ide-llabel"
      data-ll="${links.indexOf(l)}">${esc(l.label)}</text>`).join("")}</g>
    <g id="ide-nodes">${nodes.map((n) => `<g class="ide-node${n.ghost ? " ghost" : ""}${
      n.id === IDE_SEL ? " sel" : ""}${hits.has(n.id) ? " hit" : ""}" data-k="${esc(n.key)}">
      <circle r="${n.r}" style="${n.colour ? "fill:" + esc(n.colour) : ""}"></circle>
      <text dy="${n.r + 12}">${esc(n.title)}</text></g>`).join("")}</g></g>`;
  const lineEls = svg.querySelectorAll("[data-l]");
  const labelEls = svg.querySelectorAll("[data-ll]");
  const nodeEls = svg.querySelectorAll("[data-k]");
  let heat = nodes.some((n) => !IDE_POS[n.key]) ? 1 : 0.15;
  let dragging = null;
  function draw() {
    lineEls.forEach((el, i) => {
      const l = links[i];
      el.setAttribute("x1", l.a.x); el.setAttribute("y1", l.a.y);
      el.setAttribute("x2", l.b.x); el.setAttribute("y2", l.b.y);
    });
    labelEls.forEach((el) => {
      const l = links[+el.dataset.ll];
      el.setAttribute("x", (l.a.x + l.b.x) / 2); el.setAttribute("y", (l.a.y + l.b.y) / 2 - 4);
    });
    nodeEls.forEach((el, i) => el.setAttribute("transform", `translate(${nodes[i].x},${nodes[i].y})`));
    $("#ide-zoom").setAttribute("transform", `translate(${zoom.x},${zoom.y}) scale(${zoom.k})`);
  }
  function step() {
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const f = 2600 / d2;
        const dist = Math.sqrt(d2);
        dx /= dist; dy /= dist;
        a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
      }
      a.vx += (W / 2 - a.x) * 0.004; a.vy += (H / 2 - a.y) * 0.004;
    }
    links.forEach((l) => {
      const dx = l.b.x - l.a.x, dy = l.b.y - l.a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (dist - 90) * 0.02;
      l.a.vx += dx / dist * f; l.a.vy += dy / dist * f;
      l.b.vx -= dx / dist * f; l.b.vy -= dy / dist * f;
    });
    nodes.forEach((n) => {
      if (n === dragging) { n.vx = n.vy = 0; return; }
      n.x += n.vx * heat; n.y += n.vy * heat;
      n.vx *= 0.6; n.vy *= 0.6;
      n.x = Math.max(20, Math.min(W - 20, n.x)); n.y = Math.max(20, Math.min(H - 30, n.y));
      IDE_POS[n.key] = { x: n.x, y: n.y };
    });
    heat *= 0.985;
    draw();
    if (heat > 0.01 || dragging) IDE_RAF = requestAnimationFrame(step);
  }
  step();
  const pt = (e) => {
    const r = svg.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width * W - zoom.x) / zoom.k,
             y: ((e.clientY - r.top) / r.height * H - zoom.y) / zoom.k };
  };
  nodeEls.forEach((el, i) => {
    const n = nodes[i];
    let moved = false;
    el.onpointerdown = (e) => {
      dragging = n; moved = false; el.setPointerCapture(e.pointerId);
      cancelAnimationFrame(IDE_RAF); heat = Math.max(heat, 0.3); step();
    };
    el.onpointermove = (e) => {
      if (dragging !== n) return;
      const p = pt(e); n.x = p.x; n.y = p.y; moved = true;
    };
    el.onpointerup = () => {
      dragging = null;
      if (!moved) {
        if (n.ghost) ideForm({ title: n.title });
        else ideOpen(n.id);
      }
    };
  });
  svg.onwheel = (e) => {
    e.preventDefault();
    const p = pt(e);
    const k = Math.max(0.4, Math.min(3, zoom.k * (e.deltaY < 0 ? 1.1 : 0.9)));
    // Keep the point under the cursor where it is: screen = z + k*p.
    zoom = { k, x: zoom.x - p.x * (k - zoom.k), y: zoom.y - p.y * (k - zoom.k) };
    draw();
  };
  let pan = null;
  svg.onpointerdown = (e) => { if (e.target === svg) pan = { x: e.clientX, y: e.clientY, zx: zoom.x, zy: zoom.y }; };
  svg.onpointermove = (e) => {
    if (!pan) return;
    const r = svg.getBoundingClientRect();
    zoom.x = pan.zx + (e.clientX - pan.x) / r.width * W;
    zoom.y = pan.zy + (e.clientY - pan.y) / r.height * H;
    draw();
  };
  svg.onpointerup = () => { pan = null; };
}

/* The note, in the side panel: its text with links live, what it points
   at, what points at it, and the explicit connections with their labels. */
async function ideOpen(id) {
  IDE_SEL = id;
  let n;
  try { n = await api(`/api/ideas/${id}`); } catch (e) { toast(e.message); return; }
  view().querySelectorAll(".ide-node").forEach((el) =>
    el.classList.toggle("sel", el.dataset.k === "n" + id));
  const body = esc(n.body).replace(/\[\[([^\[\]|]+?)(?:\|([^\[\]]*))?\]\]/g, (_, t, alias) => {
    const target = (IDE_G.nodes || []).find((x) => x.title.toLowerCase() === t.trim().toLowerCase());
    return target
      ? `<a class="ide-wl" data-open="${target.id}">${esc(alias || t)}</a>`
      : `<a class="ide-wl ghost" data-write="${esc(t.trim())}">${esc(alias || t)}</a>`;
  }).replace(/\n/g, "<br>");
  $("#ide-side").innerHTML = `
    <div class="ide-note">
      <div class="ide-notehead">
        <b>${n.pinned ? opsIcon("pin") + " " : ""}${esc(n.title)}</b>
        <span>
          <button class="btn alt sm" id="ide-edit">Edit</button>
          <button class="btn alt sm" id="ide-link">Connect</button>
          <button class="btn alt sm" id="ide-del">Remove</button>
          <button class="btn alt sm" id="ide-back">All</button>
        </span>
      </div>
      ${n.tags.length ? `<div class="dim">${n.tags.map(esc).join(" · ")}</div>` : ""}
      <div class="ide-body">${body || '<span class="dim">Nothing written yet.</span>'}</div>
      <div class="dim">changed ${fmtDate(n.updated_at)}</div>
      ${n.links_out.length ? `<h4>Points at</h4><ul class="ide-links">${n.links_out.map((l) => `<li>
        ${l.to_id ? `<a class="ide-wl" data-open="${l.to_id}">${esc(l.to_title_now || l.to_title)}</a>`
                  : `<a class="ide-wl ghost" data-write="${esc(l.to_title)}">${esc(l.to_title)}</a> <span class="dim">not written</span>`}
        ${l.kind === "explicit" ? `<span class="pill">${esc(l.label || "connected")}</span>
          <a class="dim" data-unlink="${l.id}">remove</a>` : ""}
      </li>`).join("")}</ul>` : ""}
      ${n.links_in.length ? `<h4>Pointed at by</h4><ul class="ide-links">${n.links_in.map((l) => `<li>
        <a class="ide-wl" data-open="${l.from_id}">${esc(l.from_title)}</a>
        ${l.kind === "explicit" ? `<span class="pill">${esc(l.label || "connected")}</span>` : ""}
      </li>`).join("")}</ul>` : ""}
    </div>`;
  $("#ide-edit").onclick = () => ideForm(n);
  $("#ide-link").onclick = () => ideLinkForm(n);
  $("#ide-back").onclick = () => { IDE_SEL = 0; renderIdeas(); };
  $("#ide-del").onclick = async () => {
    if (!confirm(`Remove "${n.title}"? Notes that point at it keep pointing, at a title with nothing behind it.`)) return;
    await api(`/api/ideas/${id}`, { method: "DELETE" });
    IDE_SEL = 0; renderIdeas();
  };
  $("#ide-side").querySelectorAll("[data-open]").forEach((a) => a.onclick = () => ideOpen(+a.dataset.open));
  $("#ide-side").querySelectorAll("[data-write]").forEach((a) => a.onclick = () => ideForm({ title: a.dataset.write }));
  $("#ide-side").querySelectorAll("[data-unlink]").forEach((a) => a.onclick = async () => {
    await api(`/api/ideas/links/${a.dataset.unlink}`, { method: "DELETE" });
    await renderIdeas(); ideOpen(id);
  });
}

function ideForm(n = {}) {
  modal(`<h3>${n.id ? "Edit note" : "New note"}</h3>
    <label>Title <input id="ide-f-title" value="${esc(n.title || "")}" maxlength="200"></label>
    <label>Text <textarea id="ide-f-body" rows="12" placeholder="Write [[another title]] to link to it.">${esc(n.body || "")}</textarea></label>
    <div class="row2">
      <label>Tags <input id="ide-f-tags" value="${esc((n.tags || []).join(", "))}" placeholder="comma separated"></label>
      <label>Colour <input id="ide-f-colour" type="color" value="${esc(n.colour || "#6b8afd")}"></label>
    </div>
    <label class="chk"><input type="checkbox" id="ide-f-pin" ${n.pinned ? "checked" : ""}> Pin to the top</label>
    <div class="actions"><button class="btn" id="ide-f-save">Save</button></div>`);
  $("#ide-f-save").onclick = async () => {
    try {
      const r = await api("/api/ideas", { body: {
        id: n.id || 0, title: $("#ide-f-title").value, body: $("#ide-f-body").value,
        tags: $("#ide-f-tags").value, colour: $("#ide-f-colour").value,
        pinned: $("#ide-f-pin").checked } });
      closeModal();
      if (r.claimed) toast(`${r.claimed} link${r.claimed === 1 ? "" : "s"} now point${r.claimed === 1 ? "s" : ""} here`);
      IDE_SEL = r.id;
      renderIdeas();
    } catch (e) { toast(e.message); }
  };
}

function ideLinkForm(n) {
  const others = (IDE_G.nodes || []).filter((x) => x.id !== n.id);
  modal(`<h3>Connect "${esc(n.title)}"</h3>
    <p class="dim">A link the text does not make on its own, with a word for
      what it is: depends on, contradicts, came from, replaces.</p>
    <label>To <select id="ide-l-to">
      <option value="0">a title not written yet</option>
      ${others.map((x) => `<option value="${x.id}">${esc(x.title)}</option>`).join("")}
    </select></label>
    <label>Or a title <input id="ide-l-title" placeholder="used when nothing is chosen above"></label>
    <label>As <input id="ide-l-label" placeholder="depends on" maxlength="80"></label>
    <div class="actions"><button class="btn" id="ide-l-save">Connect</button></div>`);
  $("#ide-l-save").onclick = async () => {
    try {
      await api(`/api/ideas/${n.id}/links`, { body: {
        to_id: +$("#ide-l-to").value, to_title: $("#ide-l-title").value,
        label: $("#ide-l-label").value } });
      closeModal(); await renderIdeas(); ideOpen(n.id);
    } catch (e) { toast(e.message); }
  };
}
