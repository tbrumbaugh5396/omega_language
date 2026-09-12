// ---------- labels and ID cards: every QR the building needs, on one sheet ----------
/* Pick a set — the students of a course, the shelf of equipment, the
   staff with badges — pick the stock in the printer, and print, or save
   the sheet as a page for later. The codes are the ones the scanners
   already know; nothing is minted differently for the sheet. Drawn at
   exact size in inches and printed with no margin, so a printer that
   still shrinks it is a printer setting, and the page says so. */
let LBL_PRESET = null;     // {kind, ids, layout} handed over by another screen
let LBL = { kind: "students", layout: "idcard", course_id: 0,
            kinds: "book,material,equipment", brand: true, line2: true,
            line3: true, picked: null };

async function renderLabels() {
  if (LBL_PRESET) {
    LBL = { ...LBL, ...LBL_PRESET, picked: LBL_PRESET.ids ? new Set(LBL_PRESET.ids) : null };
    LBL_PRESET = null;
  }
  const q = new URLSearchParams({ kind: LBL.kind });
  if (LBL.kind === "students" && LBL.course_id) q.set("course_id", LBL.course_id);
  if (LBL.kind === "items") q.set("kinds", LBL.kinds);
  const d = await api("/api/labels?" + q.toString());
  const layout = d.layouts.find((l) => l.id === LBL.layout) || d.layouts[0];
  const chosen = d.labels.filter((r) => !LBL.picked || LBL.picked.has(r.id));
  const perSheet = layout.cols * layout.rows;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Labels and ID cards</h2>
        <p class="dim">Every code the building needs, on one sheet: student
          cards, item labels, staff badges. The same codes the scanners
          already read, so a card from here and a card from the student's
          own page are the same card.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="lbl-save">Save as a page</button>
        <button class="btn" id="lbl-print">Print ${chosen.length}</button>
      </div>
    </div>
    <div class="lbl-split">
      <div class="card lbl-controls">
        <label>What <select id="lbl-kind">
          <option value="students" ${LBL.kind === "students" ? "selected" : ""}>Students</option>
          <option value="items" ${LBL.kind === "items" ? "selected" : ""}>Materials and equipment</option>
          <option value="staff" ${LBL.kind === "staff" ? "selected" : ""}>Staff badges</option>
        </select></label>
        ${LBL.kind === "students" ? `<label>Course <select id="lbl-course">
          <option value="0">everyone with a student record or a seat</option>
          ${d.courses.map((c) => `<option value="${c.id}" ${c.id === LBL.course_id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}
        </select></label>` : ""}
        ${LBL.kind === "items" ? `<div class="lbl-kinds">${d.item_kinds.map((k) => `<label class="chk">
          <input type="checkbox" data-lblkind="${k}" ${LBL.kinds.split(",").includes(k) ? "checked" : ""}> ${k}</label>`).join("")}</div>` : ""}
        <label>Stock <select id="lbl-layout">
          ${d.layouts.map((l) => `<option value="${l.id}" ${l.id === layout.id ? "selected" : ""}>${esc(l.label)}</option>`).join("")}
        </select></label>
        <div class="lbl-fields">
          <label class="chk"><input type="checkbox" id="lbl-line2" ${LBL.line2 ? "checked" : ""}> second line (course, kind, job)</label>
          <label class="chk"><input type="checkbox" id="lbl-line3" ${LBL.line3 ? "checked" : ""}> number</label>
          <label class="chk"><input type="checkbox" id="lbl-brand" ${LBL.brand ? "checked" : ""}> ${esc(d.brand || "the business name")}</label>
        </div>
        <p class="dim">${chosen.length} of ${d.labels.length} chosen · ${perSheet} a sheet ·
          ${Math.ceil(chosen.length / perSheet) || 0} sheet${Math.ceil(chosen.length / perSheet) === 1 ? "" : "s"}.
          Print at 100%: if the print dialog offers "fit to page", turn it off.</p>
        ${d.without_badge.length ? `<p class="dim">No badge yet, so not on the sheet:
          ${d.without_badge.map(esc).join(", ")}. A badge is issued per person on Team &amp; access.</p>` : ""}
      </div>
      <div class="card lbl-pick">
        <div class="lbl-pickhead">
          <b>${d.labels.length} on the list</b>
          <span><button class="btn alt sm" id="lbl-all">All</button>
            <button class="btn alt sm" id="lbl-none">None</button></span>
        </div>
        ${d.labels.length ? `<ul class="lbl-list">${d.labels.map((r) => `<li>
          <label class="chk"><input type="checkbox" data-lblpick="${r.id}" ${!LBL.picked || LBL.picked.has(r.id) ? "checked" : ""}>
            <b>${esc(r.name)}</b> <span class="dim">${esc(r.line2 || "")}</span></label>
        </li>`).join("")}</ul>` : `<p class="dim">Nobody and nothing in this set yet.</p>`}
      </div>
    </div>
    <h3>Preview</h3>
    <div class="card lbl-preview">${chosen.length
      ? lblCells(chosen.slice(0, Math.min(chosen.length, 6)), layout, d.brand, true)
      : '<p class="dim">Choose something to print.</p>'}</div>`;
  const redo = () => renderLabels();
  $("#lbl-kind").onchange = (e) => { LBL.kind = e.target.value; LBL.picked = null; redo(); };
  if ($("#lbl-course")) $("#lbl-course").onchange = (e) => { LBL.course_id = +e.target.value; LBL.picked = null; redo(); };
  view().querySelectorAll("[data-lblkind]").forEach((c) => c.onchange = () => {
    LBL.kinds = [...view().querySelectorAll("[data-lblkind]")].filter((x) => x.checked).map((x) => x.dataset.lblkind).join(",");
    LBL.picked = null; redo();
  });
  $("#lbl-layout").onchange = (e) => { LBL.layout = e.target.value; redo(); };
  $("#lbl-line2").onchange = (e) => { LBL.line2 = e.target.checked; redo(); };
  $("#lbl-line3").onchange = (e) => { LBL.line3 = e.target.checked; redo(); };
  $("#lbl-brand").onchange = (e) => { LBL.brand = e.target.checked; redo(); };
  $("#lbl-all").onclick = () => { LBL.picked = null; redo(); };
  $("#lbl-none").onclick = () => { LBL.picked = new Set(); redo(); };
  view().querySelectorAll("[data-lblpick]").forEach((c) => c.onchange = () => {
    LBL.picked = new Set([...view().querySelectorAll("[data-lblpick]")].filter((x) => x.checked).map((x) => +x.dataset.lblpick));
    if (LBL.picked.size === d.labels.length) LBL.picked = null;
    redo();
  });
  $("#lbl-print").onclick = () => {
    if (!chosen.length) return toast("nothing chosen");
    const w = window.open("", "_blank");
    if (!w) return toast("the browser blocked the print window — allow pop-ups for this site");
    w.document.write(lblSheet(chosen, layout, d.brand, true));
    w.document.close();
  };
  $("#lbl-save").onclick = () => {
    if (!chosen.length) return toast("nothing chosen");
    const blob = new Blob([lblSheet(chosen, layout, d.brand, false)], { type: "text/html" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${LBL.kind}-${layout.id}-${new Date().toISOString().slice(0, 10)}.html`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast("saved — open it in a browser and print at 100%");
  };
}

/* The cells of one layout, positioned in inches. `preview` draws the
   first few in the page instead of a whole sheet. */
function lblCells(rows, L, brand, preview) {
  const qr = (r) => `<img src="${location.origin}/api/qr.svg?data=${encodeURIComponent(r.payload)}"
    width="${L.qr * 96}" height="${L.qr * 96}" style="width:${L.qr}in;height:${L.qr}in" alt="">`;
  const text = (r) => `<div class="t">
    <b style="font-size:${L.font}pt">${esc(r.name)}</b>
    ${LBL.line2 && r.line2 ? `<span style="font-size:${L.font - 2}pt">${esc(r.line2)}</span>` : ""}
    ${LBL.line3 && r.line3 ? `<span style="font-size:${L.font - 3}pt">${esc(r.line3)}</span>` : ""}
    ${LBL.brand && brand ? `<span class="brand" style="font-size:${L.font - 3}pt">${esc(brand)}</span>` : ""}
  </div>`;
  const cell = (r, i) => {
    const c = i % L.cols, rw = Math.floor(i / L.cols);
    const pos = preview ? "" : `left:${(L.left + c * (L.w + L.gap_x)).toFixed(4)}in;top:${(L.top + rw * (L.h + L.gap_y)).toFixed(4)}in;`;
    return `<div class="cell${L.card ? " card" : ""}" style="${pos}width:${L.w}in;height:${L.h}in">
      ${L.card && r.photo ? `<img class="photo" src="${esc(r.photo)}" alt="" style="height:${(L.h - 0.3).toFixed(2)}in">` : ""}
      ${qr(r)}${text(r)}</div>`;
  };
  return rows.map(cell).join("");
}

function lblSheet(rows, L, brand, autoprint) {
  const per = L.cols * L.rows;
  const pages = [];
  for (let i = 0; i < rows.length; i += per) pages.push(rows.slice(i, i + per));
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(brand || "Labels")} — ${rows.length} labels</title>
<style>
@page { size: letter; margin: 0; }
html, body { margin: 0; padding: 0; background: #fff; color: #000; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
.page { position: relative; width: 8.5in; height: 11in; overflow: hidden; page-break-after: always; break-after: page; }
.page:last-child { page-break-after: auto; break-after: auto; }
.cell { position: absolute; box-sizing: border-box; padding: .08in; display: flex; gap: .1in; align-items: center; overflow: hidden; }
.cell.card { border: 1px solid #bbb; border-radius: .12in; }
.cell img { flex: 0 0 auto; display: block; }
.cell img.photo { width: auto; border-radius: .06in; object-fit: cover; }
.cell .t { min-width: 0; line-height: 1.25; overflow: hidden; }
.cell .t b, .cell .t span { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cell .t span { color: #333; }
.cell .t .brand { color: #777; margin-top: .04in; }
.note { font: 11px system-ui; color: #333; padding: 12px 0; text-align: center; }
@media screen { body { background: #777; padding: 20px 0; } .page { margin: 0 auto 20px; box-shadow: 0 2px 10px rgba(0,0,0,.45); } }
@media print { .note { display: none; } }
</style></head><body>
<p class="note">${rows.length} labels on ${pages.length} sheet${pages.length === 1 ? "" : "s"} of ${esc(L.label)}.
  Print at 100% with no margins. ${autoprint ? "The print dialog opens when the codes have loaded." : ""}</p>
${pages.map((pg) => `<div class="page">${lblCells(pg, L, brand, false)}</div>`).join("")}
${autoprint ? `<script>
(function () {
  var imgs = Array.prototype.slice.call(document.images), left = imgs.length;
  function go() { setTimeout(function () { window.print(); }, 150); }
  if (!left) return go();
  imgs.forEach(function (im) {
    var done = function () { if (--left === 0) go(); };
    if (im.complete) done(); else { im.onload = done; im.onerror = done; }
  });
})();
</script>` : ""}
</body></html>`;
}
