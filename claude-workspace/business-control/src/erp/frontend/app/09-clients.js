// ---------- documents & signatures ----------
let DOCS = null;

// ---------- B2B client engagements ----------
// The studio kit run from here: one record per client, documents generated
// from the kit's own templates into the vault, signatures through the vault's
// flow, and the per-client folder generated on demand — never kept by hand.

/* A token that lists its own values — [A / B / C], [Yes / No] — is a set
   of options, not a free blank; render it as a select. Everything else is
   optional by design: blank keeps the brackets. */
function fillField(tok, suggestedVal) {
  const parts = tok.split(" / ").map((x) => x.trim());
  const isChoice = parts.length >= 2 && parts.every(
    (x) => x && x.length <= 24 && !x.includes(":"));
  const label = `<label>[${esc(tok)}]
    <span class="opt">optional</span></label>`;
  if (isChoice) {
    return `${label}<select data-fill="${esc(tok)}">
      <option value="">— leave the brackets —</option>
      ${parts.map((x) => `<option ${suggestedVal === x ? "selected" : ""}
        >${esc(x)}</option>`).join("")}</select>`;
  }
  return `${label}<input data-fill="${esc(tok)}"
    value="${esc(suggestedVal || "")}"
    placeholder="leave blank to keep the brackets">`;
}

function engDatesForm(id, dates) {
  const row = (r) => `<div class="row2" style="margin-bottom:6px">
    <input class="ed-label" placeholder="Milestone" value="${esc(r.label || "")}">
    <div style="display:flex;gap:6px">
      <input class="ed-planned" placeholder="Planned" value="${esc(r.planned || "")}">
      <input class="ed-actual" placeholder="Actual" value="${esc(r.actual || "")}">
      <input class="ed-moved" placeholder="Moved because" value="${esc(r.moved_because || "")}">
    </div></div>`;
  modal(`<h3>The dates that matter</h3>
    <p class="dim">Planned next to actual, with the honest reason when they
      differ. Shown on the client portal. Blank labels are dropped.</p>
    <div id="ed-rows">${(dates.length ? dates : [{}]).map(row).join("")}</div>
    <button class="btn alt sm" id="ed-add">+ row</button>
    <div class="modal-foot"><button class="btn" id="ed-save">Save</button></div>`);
  $("#ed-add").onclick = () => $("#ed-rows").insertAdjacentHTML("beforeend", row({}));
  $("#ed-save").onclick = async () => {
    const out = [...document.querySelectorAll("#ed-rows > div")].map((d) => ({
      label: d.querySelector(".ed-label").value.trim(),
      planned: d.querySelector(".ed-planned").value.trim(),
      actual: d.querySelector(".ed-actual").value.trim(),
      moved_because: d.querySelector(".ed-moved").value.trim(),
    })).filter((r) => r.label);
    try {
      await api(`/api/store/admin/engagements/${id}/dates`,
        { method: "PUT", body: { dates: out } });
      closeModal(); renderEngagement(id);
    } catch (err) { toast(err.message); }
  };
}

/* "3 of 15" for a page that isn't paginated: a page is one printable sheet
   at letter aspect for this content width, and the frame draws a rule at
   every boundary — so the number always names a line you can see. Fields
   growing repaginate, which is why input recounts. */
/* Which page a frame is showing, and how tall a page is on it — the same
   arithmetic wirePageCount uses, so reading and restoring agree. */
function framePageH(doc) {
  return Math.max(420, Math.round((doc.body.clientWidth || 760) * 11 / 8.5));
}
function framePage(frame) {
  try {
    const doc = frame.contentDocument, win = frame.contentWindow;
    if (!doc || !doc.body) return 1;
    return 1 + Math.floor((win.scrollY || 0) / framePageH(doc));
  } catch { return 1; }
}
function goToPage(frame, page) {
  try {
    const doc = frame.contentDocument;
    if (!doc || !doc.body || !page || page < 2) return;
    frame.contentWindow.scrollTo(0, (page - 1) * framePageH(doc));
  } catch {}
}

/* Where you were reading, in terms the other rendering also understands.
   Page number alone drifts: the editor's input boxes are taller than the
   text they replace, so the same page number lands on earlier content. And
   a whole binder section is too coarse — the same offset inside a taller
   section is the same drift again. So: which section, which block inside
   it, and how far past that block — the finest thing both renderings agree
   on. `.bd-note` is skipped because only the editor has it. */
function _anchorParts(frame) {
  const doc = frame.contentDocument, win = frame.contentWindow;
  const y = win.scrollY || 0;
  const topOf = (el) => el.getBoundingClientRect().top + y;
  const kidsOf = (el) => [...el.children].filter(
    (k) => !k.classList.contains("bd-note"));
  return { doc, win, y, topOf, kidsOf };
}

function frameAnchor(frame) {
  try {
    const { doc, y, topOf, kidsOf } = _anchorParts(frame);
    if (!doc || !doc.body) return null;
    const secs = [...doc.querySelectorAll(".binder-doc")];
    let secIdx = -1, scope = doc.body;
    secs.forEach((sec, i) => {
      if (topOf(sec) <= y + 8) { secIdx = i; scope = sec; }
    });
    let elIdx = -1, top = topOf(scope);
    kidsOf(scope).forEach((el, i) => {
      const t = topOf(el);
      if (t <= y + 8) { elIdx = i; top = t; }
    });
    return { secIdx, elIdx, delta: y - top, page: framePage(frame) };
  } catch { return null; }
}

function restoreAnchor(frame, a) {
  if (!a) return;
  try {
    const { doc, win, topOf, kidsOf } = _anchorParts(frame);
    if (!doc || !doc.body) return;
    const secs = [...doc.querySelectorAll(".binder-doc")];
    const scope = a.secIdx >= 0 ? secs[a.secIdx] : doc.body;
    if (!scope) return goToPage(frame, a.page);
    const el = a.elIdx >= 0 ? (kidsOf(scope)[a.elIdx] || scope) : scope;
    win.scrollTo(0, Math.max(0, topOf(el) + (a.delta || 0)));
  } catch {}
}

/* A one-row answer box that grows to what you type: it starts the height
   of the printed write-in line it replaces, so the editor paginates close
   to the page, and it never traps text in a scrollbar. */
function wireAutoGrow(doc) {
  const grow = (el) => {
    el.style.height = "auto";
    el.style.height = (el.scrollHeight + 2) + "px";
  };
  const all = [...doc.querySelectorAll("textarea.ph-area")];
  all.forEach(grow);
  doc.addEventListener("input", (e) => {
    if (e.target.classList && e.target.classList.contains("ph-area"))
      grow(e.target);
  });
  return () => all.forEach(grow);
}

/* Sections fold, and stay folded: a client's page is a long page, and the
   stage you are not working in is noise until you are. Kept per section
   name rather than per client, because the stage you don't care about on
   one client is usually the one you don't care about on the next. */
const FOLDED = (() => {
  try { return JSON.parse(localStorage.getItem("bc_folded") || "{}"); }
  catch { return {}; }
})();

function foldable(key, title, right, body, summary) {
  const shut = !!FOLDED[key];
  return `<div class="card foldable${shut ? " folded" : ""}"
      data-fold="${esc(key)}">
    <div class="card-head fold-head">
      <b><span class="fold-caret">\u25be</span> ${title}</b>
      <span class="fold-sum dim">${esc(summary || "")}</span>
      ${right || ""}
    </div>
    <div class="fold-body">${body}</div>
  </div>`;
}

/* Set by whatever page owns a fold-all control, so folding one section by
   hand still corrects what the control says it will do next. */
let foldAllSync = null;

function wireFolds(scope) {
  scope.querySelectorAll("[data-fold] .fold-head").forEach((h) => {
    h.onclick = (ev) => {
      if (ev.target.closest("button, a, input, select")) return;
      const card = h.closest("[data-fold]");
      const shut = card.classList.toggle("folded");
      FOLDED[card.dataset.fold] = shut;
      try { localStorage.setItem("bc_folded", JSON.stringify(FOLDED)); }
      catch {}
      if (foldAllSync) foldAllSync();
    };
  });
}

/* A title made of parts still has to be one string when it is saved, and
   each part has to be as wide as what is in it. */
function sizeTitle(el) {
  if (!el.classList || !el.classList.contains("bd-title")) return;
  el.size = Math.max((el.value || "").length + 1, el.dataset.part ? 2 : 6);
}
// the tokens that live on the client record, mirrored from the server
const GLOBAL_TOKS = new Set(["CLIENT", "CLIENT NAME", "PROJECT",
  "PROJECT NAME", "CLIENT POC", "APPROVER", "INTERNAL POC", "ORIGINATOR",
  "DATE", "BRAND", "PACKAGE", "VALUE"]);

function composeTitle(scope) {
  const part = (sel) => scope.querySelector(sel);
  const pre = part('input.bd-title[data-part="pre"]');
  const cl = part("input.bd-title-cl");
  const post = part('input.bd-title[data-part="post"]');
  if (!cl) return (pre ? pre.value : "").trim();
  return ((pre ? pre.value : "") + cl.value
          + (post ? post.value : "")).trim();
}

function wirePageCount(frame, label) {
  /* The count is also the way in: the number is a field, so a hundred-page
     binder is one keystroke from any page in it rather than a scrollbar to
     aim at. */
  let doc, win;
  try { doc = frame.contentDocument; win = frame.contentWindow; }
  catch { label.textContent = ""; return () => {}; }
  if (!doc || !doc.body) { label.textContent = ""; return () => {}; }
  label.innerHTML = `Page <input class="pg-in" type="text" inputmode="numeric"
    aria-label="page number — type one and press enter"> of
    <span class="pg-tot"></span>`;
  const box = label.querySelector(".pg-in");
  const tot = label.querySelector(".pg-tot");
  const pageH = () =>
    Math.max(420, Math.round((doc.body.clientWidth || 760) * 11 / 8.5));
  const update = () => {
    const h = pageH();
    doc.documentElement.style.setProperty("--page-h", h + "px");
    const total = Math.max(1, Math.ceil(doc.body.scrollHeight / h));
    const cur = Math.min(total, 1 + Math.floor((win.scrollY || 0) / h));
    if (doc.activeElement !== box && box !== document.activeElement)
      box.value = cur;
    tot.textContent = total;
    box.dataset.total = total;
  };
  const go = () => {
    const total = +box.dataset.total || 1;
    const want = Math.min(total, Math.max(1, parseInt(box.value, 10) || 1));
    const h = pageH();
    // A page you typed is a jump, not a glide: gliding forty pages is two
    // seconds of blur. Neighbouring pages still slide, because there the
    // movement tells you which way you went.
    const near = Math.abs(want - 1 - (win.scrollY || 0) / h) <= 3;
    win.scrollTo({ top: (want - 1) * h,
                   behavior: near ? "smooth" : "auto" });
    box.value = want;
  };
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); go(); }
  });
  box.addEventListener("blur", update);
  box.addEventListener("focus", () => box.select());
  win.addEventListener("scroll", update, { passive: true });
  win.addEventListener("resize", update);
  doc.addEventListener("input", update);
  update();
  return update;
}

async function fillInDoc(did, title, after, anchor) {
  /* The document as the form: bracket tokens, write-in answer lines,
     paragraph boxes and checkboxes, all live where they sit in the text.
     Same-name tokens type together, because the backend fills one value per
     token everywhere it appears — the editor shows that truth live. */
  try {
    const r = await fetch(`/api/store/admin/documents/${did}/editable`,
      { headers: { Authorization: "Bearer " + S.user.token } });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    const url = URL.createObjectURL(
      new Blob([await r.text()], { type: "text/html" }));
    modal(`<h3>Fill in the document — ${esc(title)}</h3>
      <p class="dim">Type straight into the highlighted fields — named
        blanks, answer lines, paragraphs and checkboxes. Amber is still
        empty; green is filled. Fields with the same name fill together.</p>
      <iframe class="doc-viewer" src="${url}" id="fid-frame"
        title="fill in the document"></iframe>
      <div class="modal-foot">
        <span class="dim" id="fid-pages"></span>
        <span class="dim" id="fid-count" style="margin-right:auto"></span>
        <button class="btn alt" id="fid-sign" title="save the fills, then
          send for signature or sign in the room">Save &amp; sign</button>
        <button class="btn" id="fid-save">Save</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`, "wide");
    const frame = $("#fid-frame");
    let initialChecks = {};
    frame.onload = () => {
      const doc = frame.contentDocument;
      const toks = [...doc.querySelectorAll("input.ph[data-tok]")];
      const areas = [...doc.querySelectorAll(
        "input.ph-line, textarea.ph-area")];
      doc.querySelectorAll("input.ph-check").forEach((c) => {
        initialChecks[c.dataset.region] = c.checked;
      });
      const paint = () => {
        toks.forEach((i) => {
          i.classList.toggle("filled", !!i.value.trim());
          i.size = Math.max((i.value || i.placeholder).length + 2, 10);
        });
        areas.forEach((i) =>
          i.classList.toggle("filled", !!i.value.trim()));
        const left = new Set(toks.filter((i) => !i.value.trim())
          .map((i) => i.dataset.tok)).size
          + areas.filter((i) => !i.value.trim()).length;
        $("#fid-count").textContent = left
          ? `${left} field${left === 1 ? "" : "s"} still empty`
          : "everything is filled in";
      };
      doc.querySelectorAll("input.bd-title").forEach((i) => sizeTitle(i));
      doc.addEventListener("input", (e) => {
        if (e.target.classList && e.target.classList.contains("bd-title"))
          sizeTitle(e.target);
      });
      toks.forEach((inp) => inp.addEventListener("input", () => {
        // a record field moves all of its twins, here as in the binder
        toks.forEach((o) => {
          const same = inp.dataset.global
            ? o.dataset.global === inp.dataset.global
            : (!o.dataset.global && o.dataset.tok === inp.dataset.tok);
          if (o !== inp && same) o.value = inp.value;
        });
        paint();
      }));
      areas.forEach((inp) => inp.addEventListener("input", paint));
      paint();
      wireAutoGrow(doc);
      const recount = wirePageCount(frame, $("#fid-pages"));
      restoreAnchor(frame, anchor);
      recount();
    };
    const saveEdits = async () => {
      const doc = frame.contentDocument;
      const tIn = doc.querySelector('input.bd-title[data-part="pre"]');
      if (tIn && tIn.value !== tIn.defaultValue)
        await api(`/api/store/admin/documents/${did}`,
          { method: "PATCH", body: { title: composeTitle(doc) } });
      const fills = {}, regions = {};
      doc.querySelectorAll("input.ph[data-tok]").forEach((i) => {
        if (i.value.trim()) fills[i.dataset.tok] = i.value.trim();
      });
      doc.querySelectorAll("input.ph-line, textarea.ph-area").forEach((i) => {
        if (i.value.trim()) regions[i.dataset.region] = i.value.trim();
      });
      doc.querySelectorAll("input.ph-check").forEach((c) => {
        // only send toggles that changed — an untouched box is not an edit
        if (c.checked !== initialChecks[c.dataset.region])
          regions[c.dataset.region] = c.checked ? "true" : "false";
      });
      return api(`/api/store/admin/documents/${did}/edit`,
        { body: { fills, regions } });
    };
    $("#fid-save").onclick = async () => {
      try {
        const out = await saveEdits();
        closeModal();
        const rec = (out.record || []).length
          ? " · client record updated everywhere" : "";
        toast((out.unfilled.length
          ? `Saved — ${out.unfilled.length} bracket${
              out.unfilled.length === 1 ? "" : "s"} left`
          : "Saved — no brackets left") + rec);
        if (after) after();
      } catch (err) { toast(err.message); }
    };
    $("#fid-sign").onclick = async () => {
      /* Fill, then sign, without leaving the flow — the edits land first,
         because a signature attests to the text as it stands. */
      try {
        const out = await saveEdits();
        closeModal();
        if (out.party) {
          engSignForm(did, out.party, after);
        } else {
          engSignForm(did, {}, after);
        }
      } catch (err) { toast(err.message); }
    };
  } catch (err) { toast(err.message); }
}

async function binderEditMode(engId, e, anchor) {
  /* The whole binder, editable in place. Each section knows what it is:
     data-doc sections save through the document editor; data-tpl sections
     are blank forms — any edit generates the document for this client,
     then applies the rest. Signed pages sit read-only between them. */
  try {
    const html = await (await fetch(
      `/api/store/admin/engagements/${engId}/binder/editable`,
      { headers: { Authorization: "Bearer " + S.user.token } })).text();
    const frame = $("#bd-frame");
    frame.src = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    $("#bd-edit").hidden = true;
    $("#bd-dl").hidden = true;
    $("#bd-save").hidden = false;
    $("#bd-hint").textContent = "Type anywhere the fields glow — amber is "
      + "empty, green is filled. Signed pages are read-only. Saving writes "
      + "every touched page, and a touched blank form becomes a real "
      + "document for this client.";
    const initialChecks = new Map();
    const initialToks = new Map();
    const initialTitles = new Map();
    let signCard = null;
    frame.onload = () => {
      const doc = frame.contentDocument;
      doc.querySelectorAll("input.ph-check").forEach((c) =>
        initialChecks.set(c, c.checked));
      /* suggested values arrive pre-filled; a card only counts as touched
         by what YOU changed, or every blank form would "save" itself into
         existence on the strength of its own suggestions */
      doc.querySelectorAll("input.ph[data-tok]").forEach((i) =>
        initialToks.set(i, i.value));
      doc.querySelectorAll("input.bd-title").forEach((i) => {
        initialTitles.set(i, i.value);
        sizeTitle(i);
      });
      const paint = (scope) => {
        scope.querySelectorAll("input.ph[data-tok]").forEach((i) => {
          i.classList.toggle("filled", !!i.value.trim());
          i.size = Math.max((i.value || i.placeholder).length + 2, 10);
        });
        scope.querySelectorAll("input.ph-line, textarea.ph-area")
          .forEach((i) => i.classList.toggle("filled", !!i.value.trim()));
      };
      wireAutoGrow(doc);
      const recount = wirePageCount(frame, $("#bd-pages"));
      restoreAnchor(frame, anchor);
      recount();
      /* A record field is the same fact wherever it appears — the client
         does not change from one form to the next — so editing one moves
         every one of them, in every document in the book. A plain token
         stays local to its own page. */
      doc.addEventListener("input", (ev) => {
        const inp = ev.target;
        if (inp.classList && inp.classList.contains("bd-title"))
          sizeTitle(inp);
        if (!inp.dataset || !inp.dataset.global) return;
        doc.querySelectorAll(
          `input[data-global="${inp.dataset.global}"]`).forEach((o) => {
            if (o !== inp) { o.value = inp.value; sizeTitle(o); }
          });
        doc.querySelectorAll(".binder-doc").forEach(paint);
      });
      doc.querySelectorAll(".binder-doc[data-doc], .binder-doc[data-tpl]")
        .forEach((card) => {
          /* Signing lives on the page, not in the footer: a book has many
             signatures and they belong to different pages. Injected here
             rather than rendered server-side, so the printable binder
             stays a printable binder. */
          const sign = doc.createElement("button");
          sign.type = "button";
          sign.className = "bd-sign";
          sign.textContent = "Sign this page";
          sign.title = "saves this page, then opens the pad — or sends it";
          sign.onclick = () => signCard && signCard(card);
          card.insertBefore(sign, card.firstChild);
          card.addEventListener("input", (ev) => {
            const inp = ev.target;
            if (inp.dataset && inp.dataset.tok && !inp.dataset.global) {
              card.querySelectorAll(
                `input.ph[data-tok]`).forEach((o) => {
                  if (o !== inp && o.dataset.tok === inp.dataset.tok)
                    o.value = inp.value;
                });
            }
            paint(card);
          });
          paint(card);
        });
    };
    /* One page's worth of saving, so that Save-the-binder and Sign-this-page
       write by exactly the same rules — a signature that attested to a
       slightly different save path would be a signature to argue about.
       Returns the document id the page now has, or null if there was
       nothing to write.

       Record fields ride along in the ordinary fills — the server knows
       they belong to the client and writes them there instead of baking
       them into whichever page you happened to type on. */
    const saveCard = async (card, force) => {
      const fills = {}, regions = {};
      card.querySelectorAll("input.ph[data-tok]").forEach((i) => {
        if (i.value.trim() && i.value !== initialToks.get(i))
          fills[i.dataset.tok] = i.value.trim();
      });
      card.querySelectorAll("input.ph-line, textarea.ph-area")
        .forEach((i) => {
          if (i.value.trim()) regions[i.dataset.region] = i.value.trim();
        });
      card.querySelectorAll("input.ph-check").forEach((c) => {
        if (c.checked !== initialChecks.get(c))
          regions[c.dataset.region] = c.checked ? "true" : "false";
      });
      // the title is fields on the card: what it is called, and who
      // for — the second being the record's own client field
      const tIn = card.querySelector('input.bd-title[data-part="pre"]');
      const titleChanged = tIn && tIn.value !== initialTitles.get(tIn);
      // A record field is the client's, not this page's: changing the
      // client must not conjure twenty blank forms into existence just
      // because their copy of the client's name moved with it.
      const own = Object.keys(fills).filter((k) => !GLOBAL_TOKS.has(k));
      const touched = own.length || Object.keys(regions).length
        || titleChanged;
      if (card.dataset.doc) {
        if (!touched) return { id: +card.dataset.doc, wrote: false };
        if (titleChanged)
          await api(`/api/store/admin/documents/${card.dataset.doc}`,
            { method: "PATCH", body: { title: composeTitle(card) } });
        let record = [];
        if (Object.keys(fills).length || Object.keys(regions).length) {
          const out = await api(
            `/api/store/admin/documents/${card.dataset.doc}/edit`,
            { body: { fills, regions } });
          record = out.record || [];
        }
        return { id: +card.dataset.doc, wrote: true, record };
      }
      if (!touched && !force) return null;
      /* a blank form someone wrote on becomes a real document — the
         token fills ride along at generation; the regions land right
         after, on the same scan order. Signing one generates it too:
         you cannot sign a page that does not exist yet. */
      const out = await api(
        `/api/store/admin/engagements/${engId}/docs`,
        { body: { template_path: card.dataset.tpl, fills } });
      if (Object.keys(regions).length)
        await api(`/api/store/admin/documents/${out.doc_id}/edit`,
          { body: { fills: {}, regions } });
      card.dataset.doc = out.doc_id;
      return { id: out.doc_id, wrote: true, generated: true };
    };

    /* Sign the page you are looking at, from inside the book. The pad is
       the same one an emailed signer gets — drawn with the mouse — and the
       page is saved first, because a signature attests to the text as it
       stands. */
    signCard = async (card) => {
      try {
        const out = await saveCard(card, true);
        closeModal();
        engSignForm(out.id, { name: e.approver_name, email: e.approver_email },
          () => renderEngagement(engId));
      } catch (err) { toast(err.message); }
    };

    $("#bd-save").onclick = async () => {
      const doc = frame.contentDocument;
      const cards = [...doc.querySelectorAll(
        ".binder-doc[data-doc], .binder-doc[data-tpl]")];
      let saved = 0, generated = 0, failed = 0, recordChanged = false;
      for (const card of cards) {
        try {
          const out = await saveCard(card);
          if (!out || !out.wrote) continue;
          if (out.generated) generated += 1; else saved += 1;
          if ((out.record || []).length) recordChanged = true;
        } catch (err) { failed += 1; toast(
          `${card.dataset.name || "page"}: ${err.message}`); }
      }
      closeModal();
      toast(`Binder saved — ${saved} page${saved === 1 ? "" : "s"} updated`
        + (recordChanged ? ", client record updated everywhere" : "")
        + (generated ? `, ${generated} generated from blank forms` : "")
        + (failed ? `, ${failed} failed` : ""));
      renderEngagement(engId);
    };
  } catch (err) { toast(err.message); }
}

async function renderClients() {
  if (S.engId) return renderEngagement(S.engId);
  const data = await api("/api/store/admin/engagements"
    + (S.engArchived ? "?archived=1" : ""));
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Clients (B2B)</h2>
        <p class="dim">Studio engagements — the kit's stages, documents and
          signatures, run from one place.</p></div>
      <div class="top-actions" style="display:flex;gap:8px">
        ${data.archived_count || S.engArchived ? `<button
          class="btn alt ${S.engArchived ? "on" : ""}" id="eng-arch-toggle"
          title="clients put away — everything they have is intact"
          >Archived${data.archived_count ? ` (${data.archived_count})`
            : ""}</button>` : ""}
        <button class="btn" id="eng-new">${opsIcon("handshake","btn-ic")} New client</button>
      </div>
    </div>
    ${data.kit_available ? "" : `<div class="card alert"><b>The template kit
      isn't on this install</b><p class="dim">docs/business-control-b2b-client/
      is missing, so documents can't be generated here — records and exports
      still work.</p></div>`}
    <div id="eng-list">${data.engagements.map((e) => `
      <div class="doc-card eng-card" data-eng="${e.id}"
        style="cursor:pointer">
        <div class="eng-top">
          <span class="doc-ic">${opsIcon("handshake")}</span>
          <div class="doc-main"><b>${esc(e.name)}</b>
            <span class="dim">${esc(e.stage.replace(/^(\d\d)-/, "$1 · ").replace(/-/g, " "))} · ${
              e.package ? "package " + esc(e.package) + " · " : ""}${
              e.value_cents ? money(e.value_cents) + " · " : ""}content ${
              e.content_pct}% · ${e.docs} document${e.docs === 1 ? "" : "s"}, ${
              e.signed} signed${e.portal_seen_at
                ? " · client looked " + fmtDate(e.portal_seen_at) : ""}</span></div>
          ${e.tenant_id ? `<span class="pill ok" title="this client runs
            on the platform — their install answers at
            ${esc(e.tenant_id)}.localhost">${opsIcon("shield2","btn-ic")}
            ${esc(e.tenant_id)}</span>` : ""}
          ${(e.warnings || []).map((w) =>
            `<span class="pill warn">${esc(w)}</span>`).join("")}
          ${e.status === "closed" ? '<span class="pill">closed</span>' : ""}
          ${e.launch_target ? `<span class="dim">launch ${esc(e.launch_target)}</span>` : ""}
          <button class="btn alt sm" data-engarch="${e.id}"
            data-name="${esc(e.name)}"
            data-on="${e.status === "archived" ? 1 : 0}">${
            e.status === "archived" ? "Restore" : "Archive"}</button>
          <button class="btn alt sm" data-engdel="${e.id}"
            data-name="${esc(e.name)}" data-docs="${e.docs}"
            data-signed="${e.signed}">Delete</button>
        </div>
      </div>`).join("")
      || `<div class="card empty"><span class="e-ic">${opsIcon("handshake")}</span>
          <b>${S.engArchived ? "Nothing archived" : "No clients yet"}</b>
          <p class="dim">${S.engArchived
            ? "Archiving a client puts them away without removing anything."
            : "Create one, then generate its documents from the kit's templates."
          }</p></div>`}</div>`;
  $("#eng-new").onclick = () => engForm(null);
  const at = $("#eng-arch-toggle");
  if (at) at.onclick = () => { S.engArchived = !S.engArchived;
    renderClients(); };
  view().querySelectorAll("[data-engarch]").forEach((b) => b.onclick =
    async (ev) => {
      ev.stopPropagation();
      const on = b.dataset.on === "1";
      try {
        await api(`/api/store/admin/engagements/${b.dataset.engarch}/archive`,
          { body: { archived: !on } });
        toast(on ? `${b.dataset.name} restored`
          : `${b.dataset.name} archived — everything they have is intact`);
        renderClients();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-eng]").forEach((el) => el.onclick = (ev) => {
    // the row is a link; its own buttons are not
    if (ev.target.closest("[data-engdel], [data-engarch]")) return;
    S.engId = +el.dataset.eng; render();
  });
  view().querySelectorAll("[data-engdel]").forEach((b) => b.onclick = (ev) => {
    ev.stopPropagation();
    const n = +b.dataset.docs, sg = +b.dataset.signed;
    modal(`<h3>Delete ${esc(b.dataset.name)}?</h3>
      <p class="dim">This removes the client, their stages, dates, activity
        and exported folder${n ? `, and the ${n} document${n === 1 ? "" : "s"}
        filed under them` : ""}.</p>
      ${sg ? `<p class="dim"><b>${sg} signed document${sg === 1 ? " is" :
        "s are"} kept.</b> A signature is evidence that a named person
        agreed to a specific text on a date — deleting the client does not
        un-agree it. ${sg === 1 ? "It moves" : "They move"} to Documents →
        Archived, where deleting ${sg === 1 ? "it" : "them"} is its own
        decision.</p>` : ""}
      <p class="dim">There is no undo.</p>
      <div class="modal-foot">
        <button class="btn danger" id="ed-go">Delete the client</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#ed-go").onclick = async () => {
      try {
        const out = await api(
          `/api/store/admin/engagements/${b.dataset.engdel}`,
          { method: "DELETE" });
        closeModal();
        toast(`${out.name} deleted — ${out.removed} document${
          out.removed === 1 ? "" : "s"} removed`
          + (out.kept ? `, ${out.kept} signed kept in Documents` : ""));
        S.engId = null;
        renderClients();
      } catch (err) { toast(err.message); }
    };
  });
}

function engForm(e) {
  modal(`<h3>${e ? "Edit client" : "New client"}</h3>
    <label>Client name <span class="req">required</span></label>
    <input id="ef-name" value="${esc(e ? e.name : "")}">
    <div class="row2">
      <div><label>Package (A / B / C)</label>
        <input id="ef-pkg" value="${esc(e ? e.package : "")}"></div>
      <div><label>Value ($)</label>
        <input id="ef-val" type="number" min="0"
          value="${e && e.value_cents ? e.value_cents / 100 : ""}"></div>
    </div>
    <div class="row2">
      <div><label>Client POC name</label>
        <input id="ef-appr" value="${esc(e ? e.approver_name : "")}"></div>
      <div><label>Client POC email</label>
        <input id="ef-email" type="email" value="${esc(e ? e.approver_email : "")}"></div>
    </div>
    <div class="row2">
      <div><label>Internal POC
          <span class="opt">must accept if it isn't you</span></label>
        <input id="ef-ipoc" value="${esc(e ? e.internal_poc || ""
          : (S.user ? S.user.name : ""))}"></div>
      <div><label>Originator</label>
        <input id="ef-orig" value="${esc(e ? e.originator || ""
          : (S.user ? S.user.name : ""))}"></div>
    </div>
    <div class="row2">
      <div><label>Launch target</label>
        <input id="ef-launch" placeholder="e.g. 2026-11-06"
          value="${esc(e ? e.launch_target : "")}"></div>
      <div><label>Status</label>
        <select id="ef-status">
          <option value="active" ${!e || e.status === "active" ? "selected" : ""}>active</option>
          <option value="closed" ${e && e.status === "closed" ? "selected" : ""}>closed</option>
          <option value="archived" ${e && e.status === "archived" ? "selected" : ""}>archived</option>
        </select></div>
    </div>
    <div class="row2">
      <div><label>Staging URL</label>
        <input id="ef-stag" value="${esc(e ? e.staging_url : "")}"></div>
      <div><label>Live URL</label>
        <input id="ef-live" value="${esc(e ? e.live_url : "")}"></div>
    </div>
    <div class="row2">
      <div><label>Content received (%)</label>
        <input id="ef-pct" type="number" min="0" max="100"
          value="${e ? e.content_pct : 0}"></div>
      <div><label>This week, in one sentence (shown on the portal)</label>
        <input id="ef-week" value="${esc(e ? e.week_note : "")}"></div>
    </div>
    <label>Blockers — one per line, empty when none (shown on the portal)</label>
    <textarea id="ef-block" rows="2">${esc(e ? e.blockers : "")}</textarea>
    <label>Notes (internal)</label>
    <textarea id="ef-notes" rows="3">${esc(e ? e.notes : "")}</textarea>
    ${e ? "" : `<label>Attachments
        <span class="opt">filed with the client, listed in the binder</span>
      </label>
      <input type="file" id="ef-files" multiple
        accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.csv,.txt">`}
    <div class="modal-foot"><button class="btn" id="ef-save">Save</button></div>`);
  $("#ef-save").onclick = async () => {
    const body = {
      name: $("#ef-name").value.trim(),
      package: $("#ef-pkg").value.trim(),
      value_cents: Math.round((+$("#ef-val").value || 0) * 100),
      approver_name: $("#ef-appr").value.trim(),
      approver_email: $("#ef-email").value.trim(),
      internal_poc: $("#ef-ipoc").value.trim(),
      originator: $("#ef-orig").value.trim(),
      launch_target: $("#ef-launch").value.trim(),
      staging_url: $("#ef-stag").value.trim(),
      live_url: $("#ef-live").value.trim(),
      notes: $("#ef-notes").value.trim(),
      status: $("#ef-status").value,
      content_pct: Math.max(0, Math.min(100, +$("#ef-pct").value || 0)),
      week_note: $("#ef-week").value.trim(),
      blockers: $("#ef-block").value.trim(),
    };
    try {
      if (e) await api(`/api/store/admin/engagements/${e.id}`,
        { method: "PATCH", body });
      else {
        const out = await api("/api/store/admin/engagements",
          { method: "POST", body });
        S.engId = out.id;
        // attachments ride in with the client: each becomes its own vault
        // document, filed under the first stage, listed in the binder
        const files = [...($("#ef-files")?.files || [])];
        for (const f of files) {
          try {
            const doc = await api("/api/store/admin/documents", { body: {
              title: f.name.slice(0, 190), category: "other",
              party_kind: "partner", party_name: body.name,
            } });
            const fd = new FormData();
            fd.append("file", f);
            const up = await fetch(
              `/api/store/admin/documents/${doc.id}/file`,
              { method: "POST", body: fd,
                headers: { Authorization: "Bearer " + S.user.token } });
            if (!up.ok) throw new Error((await up.json()).detail);
            await api(`/api/store/admin/engagements/${out.id}/attach`,
              { body: { doc_id: doc.id, stage: "01-potential-customer",
                        side: "to_client" } });
          } catch (err) { toast(`${f.name}: ${err.message}`); }
        }
        if (files.length) toast(`${files.length} attachment${
          files.length === 1 ? "" : "s"} filed`);
      }
      closeModal(); render();
    } catch (err) { toast(err.message); }
  };
}

async function renderEngagement(id) {
  let d;
  try { d = await api(`/api/store/admin/engagements/${id}`); }
  catch { S.engId = null; return renderClients(); }
  const e = d.engagement;
  const byStage = {};
  d.docs.forEach((x) => (byStage[x.stage] = byStage[x.stage] || []).push(x));

  const docRowE = (x) => `
    <div class="doc-line foldable${FOLDED["doc:" + x.id] ? " folded" : ""}${
      x.signed ? " dl-signed" : x.awaiting ? " dl-awaiting" : ""}"
      data-fold="doc:${x.id}">
      <span class="dl-title fold-head"><span class="fold-caret">\u25be</span>
        <b title="${esc(x.title)}">${esc(x.title)}</b>
        <span class="dl-meta">
          <span class="dm-state">${x.awaiting && x.signed
            /* both at once is a real state — two parties, one of them
               done — and a slot that shows only the newer of the two
               would report a half-signed contract as unsigned */
            ? `<span class="pill warn">${x.signed} of ${
                x.signed + x.awaiting} signed</span>`
            : x.awaiting ? `<span class="pill warn">${x.awaiting} awaiting</span>`
            : x.signed ? `<span class="pill ok">${x.signed} signed</span>`
            : ""}</span>
          <span class="dm-side"><span class="pill ${
            x.side === "internal" ? "warn" : "ok"}">${
            x.side === "internal" ? "internal" : "to client"}</span></span>
          <span class="dm-blanks fold-sum dim">${x.blanks
            ? x.blanks + " blank" + (x.blanks === 1 ? "" : "s") + " left"
            : "no blanks left"}</span>
        </span>
      </span>
      <span class="dl-acts fold-body">
        <span class="ga-slot">${x.sow && !x.signed ? `<button
          class="btn alt sm" data-sowfresh="${x.id}" title="re-derive the
          timeline from the live schedule — Dates-table edits and passed
          gates flow in; every other edit in the paper stands"
          >Refresh timeline</button>` : ""}
        ${x.blanks ? `<button class="btn alt sm"
          data-engfill="${x.id}" title="the brackets still unfilled — same
          form as generation, shorter each time">Fill (${x.blanks})</button>`
          : ""}</span>
        <button class="btn alt sm" data-engview="${x.id}"
          data-kind="${x.has_body ? "body" : "file"}" data-ext="${x.ext || ""}"
          data-signed="${x.signed || 0}"${x.quote ? ' data-quote="1"' : ""}
          title="${x.quote
            ? "opens the quote as the bench presents it"
            : "opens the document — signatures shown on it"}">View</button>
        <button class="btn alt sm" data-engdl="${x.id}"
          data-kind="${x.has_body ? "body" : "file"}" data-ext="${x.ext || ""}"
          data-name="${esc(x.filename || x.title)}">PDF</button>
        <button class="btn alt sm" data-engsign="${x.id}">Sign</button>
        <button class="btn alt sm" data-engopen="${esc(x.title)}">Open</button>
        <button class="btn alt sm" data-engscan="${x.id}"
          data-stage="${x.stage}" data-side="${x.side}"
          data-title="${esc(x.title)}" title="file the signed paper's scan
          or photo beside this document">Scan</button>
        <button class="btn alt sm" data-engrm="${x.id}"
          data-title="${esc(x.title)}">Remove</button>
      </span>
    </div>`;

  // Two kit stages can share one client folder (the enquiry scripts file
  // under consultation); merge them so the page shows the client's stages,
  // exactly like the exported folder does.
  const merged = [];
  d.stages.forEach((st) => {
    const prev = merged.find((m) => m.client_stage === st.client_stage);
    if (prev) { prev.templates = prev.templates.concat(st.templates);
      prev.kit = prev.kit.concat([st.stage]); }
    else merged.push({ ...st, kit: [st.stage] });
  });

  const stageName = (st) => st.replace(/^(\d\d)-/, "$1 · ").replace(/-/g, " ");

  /* The one thing to do next, derived from the same gates the stage is.
     Each gate names the kit stage whose templates satisfy it, so "generate
     the right document for THIS client" is one click, prefilled from the
     record. */
  const GATE_STAGE = {
    proposal_accepted: "03-proposal", contract_signed: "04-agreement",
    requirements_signed: "06-requirements",
    art_direction_signed: "07-brand-exploration",
    round1_signed_off: "08-build", round2_signed_off: "08-build",
    handover_accepted: "10-handover",
    ongoing_support_agreed: "11-aftercare",
  };

  /* The gates as a track: done · now · waiting on them · waiting on us ·
     upcoming. "Waiting on the client" is a real state, not a mood — a
     signature request that is out, or a payment link that is unpaid, is
     time we cannot spend. Everything derives from the same gates the stage
     does, so the picture and the list can never disagree. */
  function gateState(g, isNext) {
    if (g.passed_at) return "done";
    const doc = d.docs.find((x) => x.id === g.doc_id);
    if (doc && doc.awaiting) return "client";
    if (g.kind === "money" && g.has_payment_link) return "client";
    return isNext ? "now" : "later";
  }
  const STATE_LABEL = { done: "done", now: "do this next",
    client: "waiting on the client", later: "upcoming" };

  function trackHtml() {
    const live = d.gates.filter((g) => g.active);
    const firstOpen = live.find((g) => !g.passed_at);
    return `<div class="track">
      ${live.map((g) => {
        const st = gateState(g, g === firstOpen);
        return `<div class="tk-node tk-${st}"
          title="${esc(g.label)} — ${STATE_LABEL[st]}">
          <span class="tk-dot"></span>
          <span class="tk-label">${esc(g.label)}</span>
        </div>`;
      }).join("")}
    </div>
    <div class="tk-key">
      <span class="tk-k tk-done">done</span>
      <span class="tk-k tk-now">do next</span>
      <span class="tk-k tk-client">waiting on the client</span>
      <span class="tk-k tk-later">upcoming</span>
    </div>`;
  }

  /* What can run alongside what. The gates are a chain — each waits on the
     one before — but the WORK inside a stage mostly isn't: content
     gathering, brand exploration and build overlap in every real project,
     which is exactly what a client asks when they ask "can we start X
     while Y finishes?" */
  function ganttModal() {
    /* The tracks and the schedule come from the server — the same facts
       the Scope of Work prints, so the chart and the paper cannot
       disagree. A gate with no written date gets an estimated one from
       default durations, and the estimate SAYS it is one everywhere. */
    const live = d.gates.filter((g) => g.active);
    const sched = {};
    (d.schedule || []).forEach((s) => (sched[s.gate] = s));
    const idx = {};
    live.forEach((g, i) => (idx[g.gate] = i));
    const n = live.length || 1;
    const pct = (i) => (i / n) * 100;
    const short = (iso) => {
      const [, m, day] = (iso || "").split("-");
      return m ? `${+m}/${+day}` : "";
    };
    const bars = (d.tracks || []).filter((b) => idx[b.from] !== undefined
      && idx[b.to] !== undefined).map((b) => {
      const a = idx[b.from], z = idx[b.to];
      const doneTo = live.filter((g) => g.passed_at).length;
      const state = z < doneTo ? "done" : a <= doneTo ? "now" : "later";
      const dur = b.days < 10 ? `${b.days}d` : `~${Math.round(b.days / 7)}wk`;
      return `<div class="gt-row">
        <span class="gt-name">${esc(b.name)}${b.optional
          ? ' <span class="opt">optional</span>' : ""}</span>
        <span class="gt-track">
          <span class="gt-bar gt-${state}"
            style="left:${pct(a)}%;width:${Math.max(pct(z - a), 6)}%"
            title="${esc([b.note || "", `${b.start} → ${b.end}`
              + (b.estimated ? " (estimated)" : "")]
              .filter(Boolean).join(" · "))}"><span class="gt-dur">${dur}${
            b.estimated ? " est." : ""}</span></span>
        </span>
      </div>`;
    }).join("");
    const anyEst = (d.tracks || []).some((b) => b.estimated
      && idx[b.from] !== undefined && idx[b.to] !== undefined);
    modal(`<h3>What can run in parallel</h3>
      <p class="dim">The stages are a chain — each waits on the one before.
        The work between them is not: bars on different rows that overlap
        horizontally can be in flight at the same time.</p>
      <div class="gt">
        <div class="gt-row gt-head"><span class="gt-name"></span>
          <span class="gt-track">${live.map((g, i) => {
            const s = sched[g.gate] || {};
            return `<span class="gt-tick" style="left:${pct(i)}%"
               title="${esc(g.label)}${s.date ? " · " + s.date
                 + (s.source === "estimate" ? " (est.)" : "") : ""}">${
              g.passed_at ? "•" : "○"}<i class="gt-date">${short(s.date)}${
              s.source === "estimate" ? "?" : ""}</i></span>`;
          }).join("")}</span></div>
        ${bars}
      </div>
      <p class="dim" style="margin-top:14px">Content is the one that decides
        the launch date — it starts at kickoff and runs the whole way, so a
        week lost there is a week lost at the end.${anyEst
        ? " Dates with a ? and bars marked est. are default durations, not"
          + " commitments — write real dates in the Dates table and they"
          + " take over." : ""}</p>
      <div class="modal-foot"><button class="btn" data-close>Close</button></div>`,
      "wide");
  }

  function nextStep() {
    const g = d.gates.find((x) => x.active && !x.passed_at);
    if (!g) return { text: "Every stage has closed — aftercare from here.",
                     actions: [] };
    const actions = [];
    if (g.kind === "money") {
      actions.push({ label: g.has_payment_link ? "Check payment"
        : "Payment link", act: g.has_payment_link ? "paycheck" : "paylink",
        gate: g.gate });
      actions.push({ label: "Confirm by hand", act: "pass", gate: g.gate });
      return { text: `${g.label} is the open stage. Send the link with the `
        + "invoice, or confirm when the money arrives.", actions };
    }
    if (g.doc_id) {
      const doc = d.docs.find((x) => x.id === g.doc_id) || {};
      if (doc.awaiting)
        return { text: `${g.label}: "${doc.title}" is out for signature — `
          + "chase warmly, or reopen and relink if it went to the wrong "
          + "person.", actions: [] };
      if (doc.blanks)
        return { text: `${g.label}: "${doc.title}" still has `
          + `${doc.blanks} blank${doc.blanks === 1 ? "" : "s"} — finish it, `
          + "then send it for signature.",
          actions: [{ label: `Fill blanks (${doc.blanks})`, act: "fill",
                      doc: doc.id }] };
      return { text: `${g.label}: "${doc.title}" is ready — send it for `
        + "signature.",
        actions: [{ label: "Send for signature", act: "sign", doc: g.doc_id }] };
    }
    const stage = GATE_STAGE[g.gate];
    const st = merged.find((m) => m.kit.includes(stage))
      || d.stages.find((x) => x.stage === stage);
    const stageDocs = (byStage[stage] || []);
    if (stageDocs.length)
      return { text: `${g.label}: a document is filed under this stage — `
        + "link the one whose signature closes the stage.",
        actions: [{ label: "Link doc", act: "link", gate: g.gate }] };
    const tpls = (st && st.templates) || [];
    return { text: `${g.label} is the open stage, and nothing is drafted `
      + `yet — `
      + `generate it for ${esc(e.name)}.`,
      actions: tpls.slice(0, 4).map((t) => (
        { label: `Generate: ${t.name}`, act: "gen", path: t.path })) };
  }

  const gateRow = (g) => {
    if (!g.active) return "";
    /* The pill says where the gate stands, in one word that is the same
       width on every row; who and when belong with the evidence, because
       that is the sentence they finish — "signed, by Tom, on the 26th, on
       this document" reads as one fact, not four columns. */
    const state = g.passed_at
      ? `<span class="pill ok">${g.via === "signature"
          ? "signed" : "confirmed"}</span>`
      : g.doc_id
        ? '<span class="pill warn">awaiting</span>'
        : '<span class="pill">open</span>';
    const by = [g.signed_by || g.actor || "",
      g.passed_at ? fmtDate(g.passed_at) : ""].filter(Boolean).join(", ");
    const docBit = [g.doc_title ? esc(g.doc_title)
      : g.note && !g.doc_id ? esc(g.note) : "",
      g.passed_at ? esc(by) : ""].filter(Boolean).join(" · ");
    /* Three fixed slots, right to left: [payment] [link] [pass]. A row that
       lacks a button keeps its empty slot, so Link doc sits under Link doc
       and Confirm under Mark closed all the way down. */
    const slot = (h) => `<span class="ga-slot">${h || ""}</span>`;
    const pay = g.kind === "money" && !g.passed_at
      ? (g.has_payment_link
          ? `<button class="btn alt sm" data-gate-paycheck="${g.gate}"
               title="ask Stripe whether the link was paid">Check pay</button>`
          : `<button class="btn alt sm" data-gate-paylink="${g.gate}"
               title="a Stripe checkout link to send with the invoice">Pay
               link</button>`)
      : "";
    const acts = g.passed_at || g.doc_id
      ? slot("") + slot("") + slot(`<button class="btn alt sm"
          data-gate-reopen="${g.gate}">Reopen</button>`)
      : slot(pay)
        + slot(`<button class="btn alt sm" data-gate-link="${g.gate}">Link
            doc</button>`)
        + slot(`<button class="btn alt sm" data-gate-pass="${g.gate}"
            data-kind="${g.kind}">${g.kind === "money"
              ? "Confirm" : "Mark closed"}</button>`);
    /* The schedule, on the gate it schedules. Planned comes from the
       Dates table (matched server-side); overdue = planned in the past on
       a gate still open. When the gate closed, the actual date (stamped
       at close, or written by hand) outranks the plan. */
    const today = new Date().toISOString().slice(0, 10);
    const dateBit = g.passed_at
      ? (g.actual_date ? `<span class="pill ok">done ${esc(g.actual_date)}
          </span>` : "")
      : g.planned
        ? `<span class="pill ${g.planned < today ? "bad" : ""}"
             title="from the Dates table">${g.planned < today ? "overdue · "
             : "planned "}${esc(g.planned)}</span>`
        : "";
    return `<div class="gate-line">
      <b title="${esc(g.label)}">${esc(g.label)}</b>
      <span class="gl-state">${state}</span>
      <span class="gl-doc dim" title="${docBit}">${docBit}</span>
      <span class="gl-date">${dateBit}</span>
      <span class="gl-closes dim">stage ${esc(stageName(g.stage))}</span>
      <span class="gl-acts">${acts}</span>
    </div>`;
  };

  const stageCard = (st) => {
    const docs = st.kit.flatMap((k) => byStage[k] || []);
    if (!docs.length && !st.templates.length) return "";
    const label = "Stage " + esc(st.client_stage
      .replace(/^\d\d-/, (m) => m.slice(0, 2) + " · ").replace(/-/g, " "));
    const sum = [docs.length ? `${docs.length} document${
        docs.length === 1 ? "" : "s"}` : "",
      st.templates.length ? `${st.templates.length} to generate` : ""]
      .filter(Boolean).join(" · ");
    const report = docs.find((x) => x.title.startsWith("Progress update"));
    return foldable(`stage:${st.client_stage}`, label,
      `<button class="btn alt sm" data-report="${esc(st.client_stage)}"
        title="write this stage up for the client — where it stands, what
        they have, what is waiting on them">${report
          ? "Refresh update" : "Progress update"}</button>`
      + (report ? `<button class="btn alt sm" data-send="${report.id}"
          title="email it to the client as a link to their own portal — the
          live document, not a PDF that stops being true">Send</button>` : ""),
      `${docs.length ? `<div class="sig-rows">${docs.map(docRowE).join("")}</div>` : ""}
      ${st.templates.length ? `<div class="tpl-list">
        <span class="tpl-head">Generate for ${esc(e.name)}</span>
        ${st.templates.map((t) => `<button class="tpl-line"
          data-gen="${esc(t.path)}">
          <span class="tpl-plus">+</span>
          <span class="tpl-name">${esc(t.name)}</span>
          <span class="pill ${t.side === "internal" ? "warn" : "ok"}">${
            t.side === "internal" ? "internal" : "to client"}</span>
        </button>`).join("")}</div>` : ""}`,
      sum);
  };

  view().innerHTML = `
    <div class="page-head">
      <div>
        <button class="btn alt sm" id="eng-back">← All clients</button>
        <h2 style="display:inline;margin-left:8px">${esc(e.name)}</h2>
        <p class="dim"><span class="pill ok">stage: ${esc(stageName(d.current_stage))}</span>
          ${e.package ? " package " + esc(e.package) + " · " : ""}${
          e.value_cents ? money(e.value_cents) + " · " : ""}${
          e.approver_name ? "client POC " + esc(e.approver_name) + " · " : ""}${
          e.internal_poc ? "internal POC " + esc(e.internal_poc)
            + (e.internal_poc_status === "pending"
                ? ' <span class="pill warn">unconfirmed</span>'
                : e.internal_poc_status === "declined"
                  ? ' <span class="pill bad">declined</span>' : "")
            + " · " : ""}${
          e.launch_target ? "launch " + esc(e.launch_target) : ""}</p>
      </div>
      <div class="top-actions eng-actions">
        <button class="btn alt sm" id="eng-edit">Edit</button>
        <button class="btn alt sm" id="eng-dates">Dates</button>
        ${e.portal_url
          ? `<button class="btn alt sm" id="eng-portal-copy"
               title="the client's live roadmap — everything on it is the
               to-client side only">Portal link</button>
             <button class="btn alt sm" id="eng-portal-rotate"
               title="the old link dies the moment a new one exists">Rotate</button>
             <button class="btn alt sm" id="eng-portal-revoke">Revoke</button>`
          : `<button class="btn alt sm" id="eng-portal-make">Create
               portal</button>`}
        <button class="btn alt sm" id="eng-export" title="write the folder
          tree under data/exports/clients/">Export</button>
        <button class="btn alt sm" id="eng-binder" title="the whole packet
          as one PDF — cover, contents, then every client-side paper with
          its signatures">Binder PDF</button>
        <button class="btn sm" id="eng-bundle" title="zip of the to-client
          side only — the internal wall holds">Client bundle</button>
        <button class="btn alt sm" id="eng-bundle-send" title="email the
          client a link to their roadmap, where the same bundle downloads
          fresh">Send bundle</button>
        <button class="btn alt sm" id="eng-quote" title="price this client on
          the bench, then file the quote as a paper — it opens where the last
          quote left off">Quote</button>
        ${S.meta && S.meta.is_provider
          ? (e.tenant_id
            ? `<button class="btn alt sm" id="eng-caps" title="what
                 they're entitled to — grant new capabilities and their
                 site grows the pieces that sell them">Capabilities
               </button>
               <button class="btn alt sm" id="eng-launch" title="put their
                 install on its real address, with the capabilities the
                 quote sold">${e.live_url ? "Relaunch" : "Launch site"}
               </button>`
            : `<button class="btn alt sm" id="eng-standup" title="a tenant
                 of their own — sized and shaped from the quote, on a node
                 with room">Stand up</button>`)
          : ""}
      </div>
    </div>
    ${e.internal_poc_status === "pending" && S.user
        && e.internal_poc_user_id === S.user.id ? `
    <div class="card" style="border-left:3px solid var(--warn)">
      <b>You've been named internal POC for ${esc(e.name)}</b>
      <p class="dim">${esc(e.originator || "Someone")} put your name on this
        client. It's a job, not a label — take it or hand it back, and
        declining tells them so nobody assumes it's covered.</p>
      <div class="chips">
        <button class="btn sm" id="poc-accept">I'm the internal POC</button>
        <button class="btn alt sm" id="poc-decline">Decline</button>
      </div>
    </div>` : ""}
    ${(() => { const n = nextStep(); return `
    <div class="card" style="border-left:3px solid var(--accent, #7b5cff)">
      <b>Next step</b>
      <p class="dim">${n.text}</p>
      ${n.actions.length ? `<div class="chips">${n.actions.map((a, i) =>
        `<button class="btn ${i ? "alt " : ""}sm" data-next="${i}">${a.label}</button>`)
        .join("")}</div>` : ""}
    </div>`; })()}
    ${foldable("gates", "Stages",
      `<button class="btn alt sm" id="eng-sow">Draft SOW</button>
       <button class="btn alt sm" id="eng-gantt">Gantt chart</button>`,
      `<p class="dim">Where the project is, is the first stage that hasn't
         closed — a stage that closes on a signature reads its state from
         the linked document, live.</p>
       ${trackHtml()}
       <div class="sig-rows">${d.gates.map(gateRow).join("")}</div>`,
      (() => { const live = d.gates.filter((g) => g.active);
        const done = live.filter((g) => g.passed_at).length;
        return `${done} of ${live.length} closed`; })())}
    ${merged.some((st) => st.kit.some((k) => byStage[k]) || st.templates.length)
      ? `<div class="fold-all"><span class="dim">Stages</span>
          <button class="btn alt sm" id="fold-all">Fold all</button></div>` : ""}
    ${merged.map(stageCard).join("")}
    ${d.log.length ? foldable("activity", "Activity", "",
      `<div class="log-lines">${d.log.map((l) => `
        <div class="log-line"><span class="dim">${fmtDate(l.at)}</span>
          <b title="${esc(l.actor)}">${esc(l.actor)}</b>
          <span class="dim">${esc(l.what)}</span></div>`).join("")}</div>`,
      `${d.log.length} entr${d.log.length === 1 ? "y" : "ies"}`) : ""}`;

  const nActs = nextStep().actions;
  view().querySelectorAll("[data-next]").forEach((b) => b.onclick = () => {
    const a = nActs[+b.dataset.next];
    if (!a) return;
    if (a.act === "gen") return engGenerate(id, a.path);
    if (a.act === "sign") return engSignForm(a.doc,
      { name: e.approver_name, email: e.approver_email },
      () => renderEngagement(id));
    if (a.act === "fill")
      return view().querySelector(`[data-engfill="${a.doc}"]`)?.click();
    if (a.act === "link")
      return view().querySelector(`[data-gate-link="${a.gate}"]`)?.click();
    if (a.act === "pass")
      return view().querySelector(`[data-gate-pass="${a.gate}"]`)?.click();
    if (a.act === "paylink")
      return view().querySelector(`[data-gate-paylink="${a.gate}"]`)?.click();
    if (a.act === "paycheck")
      return view().querySelector(`[data-gate-paycheck="${a.gate}"]`)?.click();
  });

  foldAllSync = null;
  wireFolds(view());
  const foldAll = $("#fold-all");
  if (foldAll) {
    const stages = () => [...view().querySelectorAll('[data-fold^="stage:"]')];
    const sync = () => { foldAll.textContent =
      stages().every((c) => c.classList.contains("folded"))
        ? "Unfold all" : "Fold all"; };
    foldAllSync = sync;
    sync();
    foldAll.onclick = () => {
      const shut = foldAll.textContent === "Fold all";
      stages().forEach((c) => {
        c.classList.toggle("folded", shut);
        FOLDED[c.dataset.fold] = shut;
      });
      try { localStorage.setItem("bc_folded", JSON.stringify(FOLDED)); } catch {}
      sync();
    };
  }
  $("#eng-back").onclick = () => { S.engId = null; render(); };
  $("#eng-edit").onclick = () => engForm(e);
  $("#eng-dates").onclick = () => engDatesForm(id, d.dates || []);
  $("#eng-gantt").onclick = ganttModal;
  $("#eng-sow").onclick = () => {
    /* Generated, not blank: deliverables from the quote, fees from the
       price book, the timeline from the gantt's own schedule. Once a SOW
       is SIGNED, the offer changes shape — scope moves by change order,
       never by editing signed text. */
    const signedSows = d.docs.filter((x) => x.sow && x.signed);
    modal(`<h3>Draft a Scope of Work</h3>
      <p class="dim">Deliverables come from the ${
        d.docs.some((x) => x.quote) ? "filed quote" : "quote (none filed "
        + "yet — the section will be left as a blank to write)"},
        fees from the published price book, and the timeline from this
        engagement's schedule — estimates marked as estimates. It stays
        editable until it goes out for signature.</p>
      ${signedSows.length ? `<label>What to draft</label>
        <select id="sw-kind">
          <option value="0">A fresh Scope of Work</option>
          ${signedSows.map((s) => `<option value="${s.id}">Change order —
            amending “${esc(s.title)}”</option>`).join("")}
        </select>
        <p class="dim">A signed SOW never re-opens; a change order says
          what changes and is signed the same way.</p>` : ""}
      <div class="modal-foot">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="sw-go">Draft it</button>
      </div>`);
    $("#sw-go").onclick = async () => {
      try {
        const out = await api(`/api/store/admin/engagements/${id}/sow`,
          { body: { change_order_for:
              +(document.getElementById("sw-kind")?.value || 0) } });
        toast(`“${out.title}” drafted — finish the blanks, then send it`);
        closeModal();
        renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
  };
  const lb = $("#eng-launch");
  if (lb) lb.onclick = () =>
    launchSite(id, e.name, e.live_url, () => renderEngagement(id));
  const capsBtn = $("#eng-caps");
  if (capsBtn) capsBtn.onclick = () =>
    capsEditor(e.tenant_id, { after: () => renderEngagement(id) });
  const su2 = $("#eng-standup");
  if (su2) su2.onclick = () =>
    standUpClient(e.slug, id, e.name,
      { after: () => renderEngagement(id) });
  $("#eng-binder").onclick = async () => {
    // The first open lays the whole book out to number its contents; say so
    // rather than leaving a dead button under the cursor.
    toast("Building the binder — numbering the contents…");
    /* The preview frame shows the HTML rendering — an embedded PDF is a
       lottery across browsers, and a blank frame reads as a broken binder.
       The download is the real PDF, from the same section gatherer. */
    try {
      const hasBinder = d.docs.some((x) =>
        x.title.startsWith("Project binder"));
      if (!hasBinder) {
        const made = await api(
          `/api/store/admin/engagements/${id}/binder`, { method: "POST" });
        if (made.created) { toast("Binder created — cover page filed under "
          + "consultation"); return renderEngagement(id); }
      }
      const html = await (await authBlob(
        `/api/store/admin/engagements/${id}/binder.html`)).text();
      const url = URL.createObjectURL(
        new Blob([html], { type: "text/html" }));
      modal(`<h3>${esc(e.name)} — the binder</h3>
        <p class="dim" id="bd-hint">Cover, contents mirroring the stages and
          their stages, every generated paper, and a blank form for
          everything not yet generated — printable and fillable with a
          pen.</p>
        <iframe class="doc-viewer" src="${url}" id="bd-frame"
          title="binder" onload="void 0"></iframe>
        <div class="modal-foot dv-foot">
          <span class="dim" id="bd-pages" style="margin-right:auto"></span>
          <button class="btn alt" id="bd-edit"
            title="every unsigned page becomes editable in place — typing
            into a blank form generates it for this client">Edit the
            binder</button>
          <button class="btn" id="bd-save" hidden>Save the binder</button>
          <button class="btn" id="bd-dl">Download binder PDF</button>
          <button class="btn alt" data-close>Close</button>
        </div>`, "wide");
      const bdFrame = $("#bd-frame");
      bdFrame.onload = () => wirePageCount(bdFrame, $("#bd-pages"));
      if (bdFrame.contentDocument
          && bdFrame.contentDocument.readyState === "complete")
        wirePageCount(bdFrame, $("#bd-pages"));
      $("#bd-edit").onclick = () =>
        binderEditMode(id, e, frameAnchor(bdFrame));
      $("#bd-dl").onclick = async () => {
        try {
          const pdf = new Blob([await authBlob(
            `/api/store/admin/engagements/${id}/binder.pdf`)],
            { type: "application/pdf" });
          const a = document.createElement("a");
          a.href = URL.createObjectURL(pdf);
          a.download = `${e.slug}-binder.pdf`;
          document.body.appendChild(a); a.click(); a.remove();
          URL.revokeObjectURL(a.href);
        } catch (err) { toast(err.message); }
      };
    } catch (err) { toast(err.message); }
  };
  const pocAcc = $("#poc-accept");
  if (pocAcc) pocAcc.onclick = async () => {
    try { await api(`/api/store/admin/engagements/${id}/poc/accept`,
      { method: "POST" }); toast("Yours now"); renderEngagement(id); }
    catch (err) { toast(err.message); }
  };
  const pocDec = $("#poc-decline");
  if (pocDec) pocDec.onclick = async () => {
    try { await api(`/api/store/admin/engagements/${id}/poc/decline`,
      { method: "POST" });
      toast("Declined — the originator has been told");
      renderEngagement(id); }
    catch (err) { toast(err.message); }
  };
  const makePortal = async () => {
    try {
      const out = await api(`/api/store/admin/engagements/${id}/portal`,
        { method: "POST" });
      try { await navigator.clipboard.writeText(out.url); } catch {}
      toast("Portal link copied — the old one, if any, is dead");
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  };
  const pMake = $("#eng-portal-make");
  if (pMake) pMake.onclick = makePortal;
  const pRot = $("#eng-portal-rotate");
  if (pRot) pRot.onclick = () => {
    if (confirm("Rotate the portal link? The current link stops working " +
                "immediately.")) makePortal();
  };
  const pCopy = $("#eng-portal-copy");
  if (pCopy) pCopy.onclick = async () => {
    try { await navigator.clipboard.writeText(location.origin + e.portal_url);
      toast("Portal link copied"); } catch { toast(e.portal_url); }
  };
  const pRev = $("#eng-portal-revoke");
  if (pRev) pRev.onclick = async () => {
    if (!confirm("Revoke the portal link? The client loses access until a " +
                 "new one is made.")) return;
    try {
      await api(`/api/store/admin/engagements/${id}/portal`,
        { method: "DELETE" });
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  };
  $("#eng-export").onclick = async () => {
    try {
      const out = await api(`/api/store/admin/engagements/${id}/export`,
        { method: "POST" });
      toast(`${out.files.length} files → ${out.root}`);
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  };
  $("#eng-bundle").onclick = async () => {
    try {
      const r = await fetch(`/api/store/admin/engagements/${id}/export.zip`,
        { headers: { Authorization: "Bearer " + S.user.token } });
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${e.slug}-client-bundle.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) { toast(err.message); }
  };
  /* The quote bench, embedded. The bench owns the arithmetic — bands,
     dependencies, discounts, care plans — and this page owns the filing:
     it seeds the bench with the client and the last quote's saved state,
     and files what comes back as a to-client paper under the proposal
     stage, where it previews, prints, signs and sends like the rest. */
  /* The bench, in a frame. One opener, two doors: the Quote button opens
     the studio view on the latest state to work a price; a quote row's
     View opens the client view on THAT paper's state, because the quote's
     own presentation — the tape, the parts, the running total — is the
     thing worth showing, and the flat paper is one click away inside.
     The frame is a same-origin blob, so the wiring is two function calls,
     not a broadcast: bcInit seeds it, bcFile is how it answers. No window
     listener — this app has a rule about those, and it has teeth. */
  const openBench = async (opts) => {
    try {
      const saved = await api(`/api/store/admin/engagements/${id}/quote`
        + (opts.doc ? `?did=${opts.doc}` : ""));
      const html = await (await fetch("/api/store/admin/quote-bench",
        { headers: { Authorization: "Bearer " + S.user.token } })).text();
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      modal(`<h3>Quote — ${esc(e.name)}${saved.signed
          ? ' <span class="pill ok">signed</span>'
          : saved.doc_id
            ? ' <span class="pill ok">continuing the filed quote</span>'
            : ""}</h3>
        <iframe class="doc-viewer qb-tall" src="${url}" id="qb-frame"
          title="quote bench"></iframe>
        <div class="modal-foot">
          <span class="dim" style="margin-right:auto">${opts.doc
            ? "The bench's own presentation of the filed quote — edits here "
              + "refile it when you File to client."
            : "File to client, up in the bench's own toolbar, saves it as "
              + "a paper on this client."}</span>
          ${opts.doc ? `<button class="btn alt" id="qb-paper" title="the
            printable, signable paper this quote filed as">The
            paper</button>` : ""}
          <button class="btn alt" data-close>Close</button>
        </div>`, "wide");
      const frame = $("#qb-frame");
      frame.onload = () => {
        const w = frame.contentWindow;
        w.bcFile = async (d) => {
          try {
            const out = await api(`/api/store/admin/engagements/${id}/quote`,
              { body: { title: d.title, markdown: d.markdown,
                        state: d.state } });
            closeModal();
            toast(out.refreshed
              ? "Quote refreshed — same paper, new numbers"
              : "Quote filed under the proposal stage");
            renderEngagement(id);
          } catch (err) { toast(err.message); }
        };
        /* Re-prove the person before the studio face shows costs and
           margins — the bench asks, this answers. The token proves the
           session; the password proves the one holding the screen is
           still ours, which matters exactly when a client is watching. */
        w.bcVerify = (pw) =>
          api("/api/store/admin/verify", { body: { password: pw } })
            .then(() => true).catch(() => false);
        if (w.bcInit) w.bcInit({ client: e.name, state: saved.state || "",
                                 view: opts.view });
      };
      const paper = $("#qb-paper");
      if (paper) paper.onclick = () => {
        closeModal();
        docViewer(opts.doc, "body", "", opts.name || `Quote — ${e.name}`,
          saved.signed, () => renderEngagement(id),
          { name: e.approver_name, email: e.approver_email });
      };
    } catch (err) { toast(err.message); }
  };
  /* Client view on both doors: a quote is as likely to be opened with
     the client in the room as not, and the safe face is the one that
     shows first. The studio face is a toggle away, behind a password. */
  $("#eng-quote").onclick = () => openBench({ view: "client" });
  view().querySelectorAll("[data-gen]").forEach((b) => b.onclick = () =>
    engGenerate(id, b.dataset.gen));
  /* The stage, written up for the client. Composed on the server from the
     same rows the board reads, filed as a to-client document, and opened
     the way any other document opens — the point is that it is a paper in
     the vault, not a screen you can only look at here. */
  /* Sending is outward-facing and cannot be taken back, so the recipient is
     on screen before the click that sends, not in a toast afterwards. One
     modal for everything that goes to a client: what is being sent changes,
     the care taken over sending it does not. */
  const sendToClient = (path, hint) => {
    modal(`<h3>Send to the client</h3>
      <p class="dim">${hint}</p>
      <label>To <span class="req">required</span></label>
      <input id="sd-to" type="email" value="${esc(e.approver_email || "")}">
      <label>A line with it <span class="opt">optional</span></label>
      <textarea id="sd-msg" rows="2"></textarea>
      <div class="modal-foot">
        <button class="btn" id="sd-go">Send</button>
        <button class="btn alt" data-close>Cancel</button>
      </div>`);
    $("#sd-go").onclick = async () => {
      try {
        const out = await api(path,
          { body: { to: $("#sd-to").value.trim(),
                    message: $("#sd-msg").value.trim() } });
        closeModal();
        /* "dry" is the honest word for a pipeline that ran with no SMTP
           configured. Reporting it as sent is the one outcome that would
           cost someone a client. */
        if (out.status === "sent") toast(`Sent to ${out.to}`);
        else if (out.status === "dry") {
          try { await navigator.clipboard.writeText(out.link); } catch {}
          toast("No mail is configured, so nothing was sent — the link is "
            + "copied, send it yourself");
        } else toast(`Not sent — ${out.status}`);
        renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
  };
  view().querySelectorAll("[data-send]").forEach((b) => b.onclick = () =>
    sendToClient(
      `/api/store/admin/engagements/${id}/docs/${b.dataset.send}/send`,
      `They get a link to their own portal copy — the live document, which
       still says the truth next week. The page they land on offers the
       PDF.`));
  $("#eng-bundle-send").onclick = () =>
    sendToClient(`/api/store/admin/engagements/${id}/bundle/send`,
      `They get a link to their roadmap, where everything on their side of
       the wall downloads as one zip — built when they click it, so it is
       never the version that was true the day you sent it.`);
  view().querySelectorAll("[data-report]").forEach((b) => b.onclick = async () => {
    try {
      const out = await api(
        `/api/store/admin/engagements/${id}/stages/${b.dataset.report}/report`,
        { method: "POST" });
      toast(out.refreshed
        ? "Progress update refreshed — same document, current facts"
        : "Progress update written — filed on the client's side");
      await renderEngagement(id);
      view().querySelector(`[data-engview="${out.doc_id}"]`)?.click();
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-engsign]").forEach((b) => b.onclick = () =>
    engSignForm(+b.dataset.engsign,
      { name: e.approver_name, email: e.approver_email },
      () => renderEngagement(id)));
  // "Open" lands on the Documents tab, searched to this title, where the
  // vault's own editor finishes what the fill form started.
  view().querySelectorAll("[data-engopen]").forEach((b) => b.onclick = () => {
    S.docQ = b.dataset.engopen; S.tab = "docs"; render();
  });
  const authBlob = async (path) => {
    const r = await fetch(path,
      { headers: { Authorization: "Bearer " + S.user.token } });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    return r.blob();
  };
  view().querySelectorAll("[data-engview]").forEach((b) => b.onclick = () => {
    /* One shared viewer with the Documents tab — in-app, never a popup:
       a window opened by script after an awaited fetch has left the
       user-gesture call stack and blockers silently eat it. */
    const name = (b.closest(".doc-line, .sig-row")?.querySelector("b")
      ?.textContent || "document").trim();
    if (b.dataset.quote)
      return openBench({ view: "client", doc: +b.dataset.engview, name });
    docViewer(+b.dataset.engview, b.dataset.kind, b.dataset.ext, name,
              b.dataset.signed, () => renderEngagement(id),
              { name: e.approver_name, email: e.approver_email });
  });
  view().querySelectorAll("[data-engdl]").forEach((b) => b.onclick = async () => {
    const did = b.dataset.engdl;
    const isPdfable = b.dataset.kind === "body" || b.dataset.ext === "pdf";
    const path = isPdfable
      ? `/api/store/admin/documents/${did}/pdf?download=1`
      : `/api/store/admin/documents/${did}/file`;
    try {
      const blob = await authBlob(path);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = b.dataset.name
        + (b.dataset.kind === "body" ? ".pdf" : "");
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-engscan]").forEach((b) => b.onclick = () => {
    /* The paper came back — a photo or a scanned PDF. It becomes its own
       vault document filed beside the original in the same stage, so the
       original's authored text stays exactly what was (or will be) signed
       electronically, and the wet-ink copy is evidence alongside it. */
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = ".pdf,.png,.jpg,.jpeg";
    inp.onchange = async () => {
      const f = inp.files[0];
      if (!f) return;
      try {
        const doc = await api("/api/store/admin/documents", { body: {
          title: `Signed scan — ${b.dataset.title}`.slice(0, 190),
          category: "contract", party_kind: "partner",
          party_name: e.name,
          notes: `wet-ink scan of document #${b.dataset.engscan}`,
        } });
        const fd = new FormData();
        fd.append("file", f);
        const up = await fetch(
          `/api/store/admin/documents/${doc.id}/file`,
          { method: "POST", body: fd,
            headers: { Authorization: "Bearer " + S.user.token } });
        if (!up.ok) throw new Error((await up.json()).detail || up.status);
        await api(`/api/store/admin/engagements/${id}/attach`, { body: {
          doc_id: doc.id, stage: b.dataset.stage,
          side: b.dataset.side } });
        toast("Scan filed beside the document");
        renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
    inp.click();
  });
  view().querySelectorAll("[data-engrm]").forEach((b) => b.onclick = () => {
    modal(`<h3>Remove — ${esc(b.dataset.title)}</h3>
      <p class="dim">Unfiling takes it out of this client's folder but keeps
        it in the Documents vault. Deleting removes it from the vault too —
        signed documents are archived there, never destroyed.</p>
      <div class="modal-foot">
        <button class="btn alt" id="rm-unfile">Unfile from this client</button>
        <button class="btn alt" id="rm-del">Delete from the vault</button>
        <button class="btn" data-close>Cancel</button>
      </div>`);
    $("#rm-unfile").onclick = async () => {
      try {
        await api(`/api/store/admin/engagements/${id}/docs/${b.dataset.engrm}`,
          { method: "DELETE" });
        closeModal(); renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
    $("#rm-del").onclick = async () => {
      try {
        const out = await api(`/api/store/admin/documents/${b.dataset.engrm}`,
          { method: "DELETE" });
        closeModal();
        toast(out.archived
          ? "Archived — it carries signatures, so it stays as evidence"
          : "Deleted");
        renderEngagement(id);
      } catch (err) { toast(err.message); }
    };
  });
  view().querySelectorAll("[data-sowfresh]").forEach((b) => b.onclick =
    async () => {
      try {
        await api(`/api/store/admin/engagements/${id}/sow/`
          + `${b.dataset.sowfresh}/refresh-timeline`,
          { method: "POST", body: {} });
        toast("timeline re-derived from the schedule — the rest of the "
          + "paper stands");
        renderEngagement(id);
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-engfill]").forEach((b) => b.onclick = async () => {
    const did = +b.dataset.engfill;
    try {
      const t = await api(`/api/store/admin/engagements/${id}/docs/${did}/blanks`);
      const field = (tok) => fillField(tok, t.suggested[tok]);
      modal(`<h3>Fill blanks — ${esc(t.title)}</h3>
        <p class="dim">Each value fills its token everywhere it appears.
          The document goes active on its own when the last bracket is
          gone.</p>
        ${t.placeholders.map(field).join("")}
        <div class="modal-foot">
          <button class="btn alt" id="fb-indoc" style="margin-right:auto"
            title="type into the fields where they sit in the text">Fill in
            the document instead</button>
          <button class="btn" id="fb-go">Fill</button>
        </div>`);
      $("#fb-indoc").onclick = () => { closeModal();
        fillInDoc(did, t.title, () => renderEngagement(id)); };
      $("#fb-go").onclick = async () => {
        const fills = {};
        document.querySelectorAll("[data-fill]").forEach((i) => {
          if (i.value.trim()) fills[i.dataset.fill] = i.value.trim();
        });
        try {
          const out = await api(
            `/api/store/admin/engagements/${id}/docs/${did}/fill`,
            { body: { fills } });
          closeModal();
          toast(out.unfilled.length
            ? `${out.unfilled.length} blank${out.unfilled.length === 1
                ? "" : "s"} left`
            : "Complete — no brackets left");
          renderEngagement(id);
        } catch (err) { toast(err.message); }
      };
    } catch (err) { toast(err.message); }
  });

  const gateDone = (out) => {
    if (out.warnings && out.warnings.length)
      toast("Out of order — still open: " + out.warnings.join(", "));
    if (out.date_stamped)
      toast(`Dates table: '${out.date_stamped}' marked done today`);
    if (out.launch) {
      modal(`<h3>Ready to launch</h3>
        <p class="dim">${esc(out.launch.name)} runs on the platform but has
          no public address yet. Launch them now — the URL, and the
          capabilities the quote sold, in one act?</p>
        <div class="modal-foot">
          <button class="btn" id="gl-launch">Launch…</button>
          <button class="btn alt" data-close>Later — the button stays on
            their page</button>
        </div>`);
      $("#gl-launch").onclick = () => {
        closeModal();
        launchSite(id, e.name, e.live_url, () => renderEngagement(id));
      };
      return;
    }
    if (out.stand_up) {
      // The contract just closed and no install exists: the next thing an
      // operator was going to do anyway is offered, sized from the quote.
      const su = out.stand_up;
      modal(`<h3>The contract is signed</h3>
        <p class="dim">${esc(su.name)} has no install yet. Stand them up on
          the platform now? ${su.suggestion
            ? `The quote sizes them: <b>${esc(su.suggestion.reason)}</b>.`
            : "No quote is filed, so the size will be a choice, not a "
              + "derivation."}</p>
        <div class="modal-foot">
          <button class="btn" id="su-go">Stand them up</button>
          <button class="btn alt" data-close>Later — it stays on the
            Platform tab</button>
        </div>`);
      $("#su-go").onclick = () => {
        closeModal();
        standUpClient(su.slug, id, su.name,
          { suggestion: su.suggestion,
            after: () => renderEngagement(id) });
      };
      return;
    }
    renderEngagement(id);
  };
  view().querySelectorAll("[data-gate-pass]").forEach((b) => b.onclick = async () => {
    const money = b.dataset.kind === "money";
    const note = prompt(money
      ? "Confirm — note (e.g. the wire reference), optional:"
      : "Passing without a linked document — where is the evidence filed?");
    if (note === null) return;
    if (!money && !note.trim()) { toast("a signature stage needs the note"); return; }
    try { gateDone(await api(
      `/api/store/admin/engagements/${id}/gates/${b.dataset.gatePass}`,
      { body: { note: note.trim() } })); }
    catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-gate-link]").forEach((b) => b.onclick = () => {
    if (!d.docs.length) { toast("no documents filed yet — generate one first"); return; }
    modal(`<h3>Link a document</h3>
      <p class="dim">The stage closes when this document is signed — read
        from the vault, never copied.</p>
      <label>Document</label>
      <select id="gl-doc">${d.docs.map((x) =>
        `<option value="${x.id}">${esc(x.title)}${x.signed ? " (signed)" : ""}</option>`).join("")}</select>
      <div class="modal-foot"><button class="btn" id="gl-go">Link</button></div>`);
    $("#gl-go").onclick = async () => {
      try {
        const out = await api(
          `/api/store/admin/engagements/${id}/gates/${b.dataset.gateLink}`,
          { body: { doc_id: +$("#gl-doc").value } });
        closeModal(); gateDone(out);
      } catch (err) { toast(err.message); }
    };
  });
  view().querySelectorAll("[data-gate-paylink]").forEach((b) => b.onclick = async () => {
    const suggested = b.dataset.gatePaylink === "deposit_cleared" && e.value_cents
      ? e.value_cents / 200 : "";
    const amt = prompt("Amount ($):", suggested);
    if (amt === null) return;
    try {
      const out = await api(`/api/store/admin/engagements/${id}/gates/${
        b.dataset.gatePaylink}/payment-link`,
        { body: { amount_cents: Math.round((+amt || 0) * 100) } });
      try { await navigator.clipboard.writeText(out.url); } catch {}
      toast(`Payment link for ${money(out.amount_cents)} copied — send it ` +
            "with the invoice");
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-gate-paycheck]").forEach((b) => b.onclick = async () => {
    try {
      const out = await api(`/api/store/admin/engagements/${id}/gates/${
        b.dataset.gatePaycheck}/payment-check`, { method: "POST" });
      toast(out.paid ? "Paid — stage closed, verified by Stripe"
                     : out.detail);
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-gate-reopen]").forEach((b) => b.onclick = async () => {
    if (!confirm("Reopen this stage? The signed document, if any, stays in the vault.")) return;
    try {
      await api(`/api/store/admin/engagements/${id}/gates/${b.dataset.gateReopen}`,
        { method: "DELETE" });
      renderEngagement(id);
    } catch (err) { toast(err.message); }
  });
}

async function engGenerate(id, path) {
  const t = await api(`/api/store/admin/engagements/${id}/template?path=`
    + encodeURIComponent(path));
  const field = (tok) => fillField(tok, t.suggested[tok]);
  modal(`<h3>Generate: ${esc(t.name)}</h3>
    <p class="dim">Each value fills its token everywhere it appears. Blanks
      stay bracketed — finish them in the document editor.</p>
    <label>Title</label><input id="gen-title" value="">
    <label>Side</label>
    <select id="gen-side">
      <option value="to_client" ${t.side === "to_client" ? "selected" : ""}>to client</option>
      <option value="internal" ${t.side === "internal" ? "selected" : ""}>internal — never sent</option>
    </select>
    ${t.placeholders.map(field).join("")}
    <div class="modal-foot"><button class="btn" id="gen-go">Generate</button></div>`);
  $("#gen-go").onclick = async () => {
    const fills = {};
    document.querySelectorAll("[data-fill]").forEach((i) => {
      if (i.value.trim()) fills[i.dataset.fill] = i.value.trim();
    });
    try {
      const out = await api(`/api/store/admin/engagements/${id}/docs`, {
        body: { template_path: path, fills,
          title: $("#gen-title").value.trim(),
          side: $("#gen-side").value },
      });
      closeModal();
      toast(out.unfilled.length
        ? `Created — ${out.unfilled.length} blank${out.unfilled.length === 1
            ? "" : "s"} left to finish in the editor`
        : "Created, fully filled");
      await renderEngagement(id);
      /* Then open it. Generating a document is asking for the document,
         and the next thing anyone does is look at what came out. Clicking
         its own View button rather than calling the viewer directly keeps
         one path: whatever the row knows about the document — its name,
         whether it is a body or a file, what it is signed with — the
         viewer is told by the row, and cannot be told something else. */
      view().querySelector(`[data-engview="${out.doc_id}"]`)?.click();
    } catch (err) { toast(err.message); }
  };
}

function engSignForm(docId, preset, after) {
  preset = preset || {};
  after = after || (() => renderEngagement(S.engId));
  modal(`<h3>Request a signature</h3>
    <div class="row2">
      <div><label>Signer name <span class="req">required</span></label>
        <input id="es-name" value="${esc(preset.name || "")}"></div>
      <div><label>Signer email <span class="req">required</span></label>
        <input id="es-email" type="email" value="${esc(preset.email || "")}"></div>
    </div>
    <label>Message <span class="opt">optional</span></label>
    <textarea id="es-msg" rows="2"></textarea>
    <div class="modal-foot">
      <button class="btn alt" id="es-here" title="the pad opens right here —
        drawn with the mouse; the only email is the receipt, after
        signing">Sign now — in person</button>
      <button class="btn" id="es-go">Send request</button>
    </div>`);
  const sendIt = async (inPerson) => {
      const out = await api(`/api/store/admin/documents/${docId}/request-signature`, {
        body: { signer_name: $("#es-name").value.trim(),
          signer_email: $("#es-email").value.trim(),
          role: "approver", message: $("#es-msg").value.trim(),
          in_person: !!inPerson },
      });
      closeModal();
      return out;
  };
  $("#es-here").onclick = async () => {
    try {
      const out = await sendIt(true);
      // The signing page, in the viewer modal — the same page an emailed
      // signer would see, pad and all; closing it refreshes the gate state.
      modal(`<h3>Sign here</h3>
        <iframe class="doc-viewer" src="${out.link}" title="sign"></iframe>
        <div class="modal-foot" style="margin-top:10px">
          <button class="btn" id="sh-done">Done</button>
        </div>`, "wide");
      $("#sh-done").onclick = () => { closeModal(); after(); };
    } catch (err) { toast(err.message); }
  };
  $("#es-go").onclick = async () => {
    try {
      const out = await sendIt(false);
      if (out.provider === "docusign") {
        toast("Sent via DocuSign — they'll get DocuSign's own email; " +
              "check the request to pull the status back");
      } else {
        try { await navigator.clipboard.writeText(out.link); } catch {}
        toast("Signature link created and copied — emailed too, if mail is set up");
      }
      after();
    } catch (err) { toast(err.message); }
  };
}

async function renderDocs() {
  const q = S.docQ || "";
  const kind = S.docKind || "";
  DOCS = await api("/api/store/admin/documents?party_kind="
    + encodeURIComponent(kind) + "&q=" + encodeURIComponent(q)
    + (S.docArchived ? "&archived=1" : ""));
  /* The paperwork our studio holds for US — the other side of the client
     relationship. A business that runs on this platform is usually also a
     client of the studio that built it; its contracts, quotes and progress
     updates live in the studio's pipeline, and this reads them across the
     wall (to-client side only, read-only, no second login). */
  if (S.studioDocs === undefined) {
    try { S.studioDocs = await api("/api/store/admin/studio"); }
    catch { S.studioDocs = { connected: false }; }
  }

  const expiring = DOCS.expiring.filter((d) => !d.expired);
  const expired = DOCS.expiring.filter((d) => d.expired);
  const alert = (expired.length || expiring.length) ? `
    <div class="card alert">
      <b>${expired.length ? opsIcon("shield2", "inline-ic") + " " +
        expired.length + " expired" : ""}${
        expired.length && expiring.length ? " · " : ""}${
        expiring.length ? expiring.length + " expiring within 45 days" : ""}</b>
      <div class="doc-alerts">${DOCS.expiring.map((d) => `
        <span class="pill ${d.expired ? "bad" : "warn"}">${esc(d.title)} —
          ${d.expired ? "expired" : "expires"} ${fmtDate(d.expires)}</span>`).join("")}
      </div>
    </div>` : "";

  const kinds = Object.entries(DOCS.party_kinds).map(([k, v]) =>
    `<button class="chip ${kind === k ? "on" : ""}" data-kind="${k}">${v}</button>`).join("");

  view().innerHTML = `
    <div class="page-head">
      <div><h2>Documents</h2>
        <p class="dim">Contracts, policies and certificates for customers,
          vendors, partners and staff — with signatures and an audit trail.</p></div>
      <button class="btn" id="doc-new">${opsIcon("file","btn-ic")} New document</button>
    </div>
    ${alert}
    ${S.studioDocs && S.studioDocs.connected ? `
    <div class="card studio-docs">
      <div class="card-head"><b>From ${esc(S.studioDocs.studio)}</b>
        <span class="dim">stage ${esc(S.studioDocs.stage || "")} ·
          ${S.studioDocs.gates_closed} of ${S.studioDocs.gates_total}
          stages closed</span>
        ${S.studioDocs.portal_url ? `<button class="btn alt sm"
          id="studio-portal" data-url="${esc(S.studioDocs.portal_url)}"
          title="the live roadmap the studio keeps for you">Open the
          roadmap</button>` : ""}</div>
      <p class="dim">Your paperwork with the studio that runs this
        platform — read straight from their pipeline, so it is always
        current. Signing and questions happen on the roadmap.</p>
      <div class="sig-rows">${S.studioDocs.docs.map((d) => `
        <div class="doc-line">
          <span class="dl-title"><b title="${esc(d.title)}">${esc(d.title)}</b>
            ${d.signed ? `<span class="pill ok">${d.signed} signed</span>` : ""}
            ${d.awaiting ? `<span class="pill warn">${d.awaiting} awaiting
              your signature</span>` : ""}</span>
          <span class="dl-acts" style="grid-template-columns: 56px 50px">
            <button class="btn alt sm" data-studioview="${d.id}"
              data-title="${esc(d.title)}"
              data-ext="${d.ext || ""}">View</button>
            ${d.ext ? "" : `<button class="btn alt sm"
              data-studiopdf="${d.id}"
              data-title="${esc(d.title)}">PDF</button>`}
          </span>
        </div>`).join("")}
      </div>
    </div>` : ""}
    <div class="filters">
      <input id="doc-q" placeholder="Search titles, parties, notes" value="${esc(q)}">
      <div class="chips"><button class="chip ${kind ? "" : "on"}" data-kind="">All</button>${kinds}
        ${DOCS.archived_count || S.docArchived ? `<button class="chip ${
          S.docArchived ? "on" : ""}" id="doc-arch" title="kept as evidence —
          signed papers whose client was deleted, and superseded versions"
          >Archived${DOCS.archived_count ? ` (${DOCS.archived_count})`
            : ""}</button>` : ""}</div>
    </div>
    <div id="doc-list">${DOCS.documents.map(docRow).join("")
      || '<div class="card empty"><span class="e-ic">' + opsIcon("file")
       + '</span><b>Nothing filed yet</b><p class="dim">Upload a contract or write one here, then send it for signature.</p></div>'}</div>`;

  $("#doc-new").onclick = () => docForm(null);
  let t;
  $("#doc-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.docQ = e.target.value; renderDocs(); }, 250); };
  view().querySelectorAll("[data-kind]").forEach((b) => b.onclick = () => {
    S.docKind = b.dataset.kind; renderDocs(); });
  const arch = $("#doc-arch");
  if (arch) arch.onclick = () => { S.docArchived = !S.docArchived;
    renderDocs(); };
  wireDocRows();
}

function docRow(d) {
  const sigs = d.signatures || [];
  const state = d.fully_signed ? '<span class="pill ok">signed</span>'
    : d.awaiting ? `<span class="pill warn">${d.awaiting} awaiting</span>`
    : "";
  const exp = d.expired ? '<span class="pill bad">expired</span>'
    : d.expiring_soon ? `<span class="pill warn">expires ${fmtDate(d.expires)}</span>`
    : d.expires ? `<span class="dim">expires ${fmtDate(d.expires)}</span>` : "";
  /* Same column discipline as a client's stages: title block, then a fixed
     state column so every "signed" pill starts at the same x down the whole
     list, then the actions in fixed slots. */
  return `<div class="doc-card${d.fully_signed ? " dl-signed"
      : d.awaiting ? " dl-awaiting" : ""}" data-doc="${d.id}">
    <div class="doc-top">
      <span class="doc-ic">${opsIcon("file")}</span>
      <div class="doc-main">
        <b title="${esc(d.title)}">${esc(d.title)}</b>
        <span class="dim">${esc(d.category_label)}${
          d.party_name ? " · " + esc(d.party_name) : ""} ·
          <span class="tag">${esc(d.party_label)}</span></span>
      </div>
      <span class="dt-state">${state}</span>
      <span class="dt-exp">${exp}</span>
      <span class="dt-acts">
        <button class="btn alt sm" data-docview="${d.id}"
          data-kind="${(d.body || "").trim() ? "body" : d.has_file ? "file" : "body"}"
          data-ext="${d.ext || ""}" data-signed="${(d.signatures || [])
            .filter((x) => x.status === "signed").length}"
          data-name="${esc(d.title)}">View</button>
        <button class="btn alt sm" data-docedit="${d.id}">Edit</button>
        <button class="btn alt sm" data-sign="${d.id}">Sign</button>
        <button class="btn alt sm" data-rowdel="doc:${d.id}">Delete</button>
      </span>
    </div>
    ${sigs.length ? `<div class="sig-rows">${sigs.map((s) => `
      <div class="sig-line sig-${s.status}">
        <b title="${esc(s.signer_name)}">${esc(s.signer_name)}</b>
        <span class="sl-mail dim">${esc(s.signer_email)}</span>
        <span class="sl-role dim">${esc(s.role)}</span>
        <span class="sl-state"><span class="pill ${s.status === "signed" ? "ok"
          : s.status === "declined" ? "bad" : "warn"}">${s.status}</span>${
          s.provider === "docusign"
            ? ' <span class="tag">DocuSign</span>' : ""}</span>
        <span class="sl-when dim">${s.status === "signed"
          ? fmtDate(s.signed_at) : ""}</span>
        <span class="sl-acts">${s.status === "signed" ? ""
          : `${s.provider === "docusign"
              ? `<button class="btn alt sm" data-sigcheck="${s.id}">check</button>`
              : ""}<button class="btn alt sm" data-void="${s.id}">void</button>`}
        </span>
      </div>`).join("")}</div>` : ""}
  </div>`;
}

async function docViewer(did, kind, ext, name, signedN, after, preset) {
  /* One viewer for both tabs: the rendered document with its signature
     block, and the signed PDF as the primary download. */
  const auth = async (path) => {
    const r = await fetch(path,
      { headers: { Authorization: "Bearer " + S.user.token } });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    return r.blob();
  };
  const isPdfable = kind === "body" || ext === "pdf";
  try {
    let frameUrl;
    if (kind === "body") {
      const html = await (await auth(
        `/api/store/admin/documents/${did}/preview`)).text();
      frameUrl = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    } else {
      frameUrl = URL.createObjectURL(
        await auth(`/api/store/admin/documents/${did}/file`));
    }
    const pdfUrl = isPdfable ? URL.createObjectURL(new Blob(
      [await auth(`/api/store/admin/documents/${did}/pdf`)],
      { type: "application/pdf" })) : frameUrl;
    const signed = +signedN > 0;
    modal(`<h3>${esc(name)}${signed
        ? ' <span class="pill ok">signed</span>' : ""}</h3>
      ${signed ? `<p class="dim">The signature block is at the end of the
        document — scroll down, and it's on the last page of the PDF.</p>` : ""}
      <iframe class="doc-viewer" src="${frameUrl}" title="${esc(name)}"></iframe>
      <div class="modal-foot dv-foot">
        <span class="dim" id="dv-pages" style="margin-right:auto"></span>
        ${kind === "body" && !signed ? `<button class="btn alt" id="dv-edit"
          title="type into the blanks where they sit in the text"
          >Edit</button>` : ""}
        <button class="btn alt" id="dv-sign" title="send it for signature, or
          open the pad here and sign with the mouse">${
          signed ? "Add a signature" : "Sign"}</button>
        <button class="btn" id="dv-dl">${opsIcon("file", "btn-ic")}
          Download ${signed ? "signed " : ""}${isPdfable ? "PDF" : "file"}</button>
        <button class="btn alt" id="dv-open">Open ${isPdfable ? "PDF" : ""}
          in tab</button>
        <button class="btn alt" data-close>Close</button>
      </div>`, "wide");
    const dvFrame = document.querySelector("#ops-modal iframe.doc-viewer");
    if (dvFrame) dvFrame.onload = () => wirePageCount(dvFrame, $("#dv-pages"));
    /* Signing belongs where you are reading: having just read the thing,
       closing the viewer to find the row's button is a step that exists
       only because of how the page was built. */
    $("#dv-sign").onclick = () => {
      closeModal();
      engSignForm(did, preset || {}, after || (() => render()));
    };
    const dvEdit = $("#dv-edit");
    if (dvEdit) dvEdit.onclick = () => {
      const at = frameAnchor(dvFrame);     // read it before the modal goes
      closeModal();
      fillInDoc(did, name, after, at);
    };
    /* Buttons, not anchors: .btn styling is scoped to button.btn, and a
       synchronous handler keeps the user gesture, so the new tab is never
       popup-blocked and the download never depends on anchor semantics. */
    $("#dv-dl").onclick = () => {
      const a = document.createElement("a");
      a.href = pdfUrl;
      a.download = name + (isPdfable ? ".pdf" : "");
      document.body.appendChild(a); a.click(); a.remove();
      toast("Downloading — the PDF carries the document and every "
        + "signature on it");
    };
    $("#dv-open").onclick = () => {
      const w = window.open(pdfUrl, "_blank");
      if (!w) { $("#dv-dl").click(); }   // a blocker still gets the file
    };
  } catch (err) { toast(err.message); }
}

function wireDocRows() {
  wireRows({}, renderDocs);
  const sp = $("#studio-portal");
  if (sp) sp.onclick = () => window.open(sp.dataset.url, "_blank");
  view().querySelectorAll("[data-studioview]").forEach((b) => b.onclick =
    async () => {
      try {
        const r = await fetch(`/api/store/admin/studio/doc/${b.dataset.studioview}`,
          { headers: { Authorization: "Bearer " + S.user.token } });
        if (!r.ok) throw new Error((await r.json()).detail || r.status);
        const url = URL.createObjectURL(await r.blob());
        modal(`<h3>${esc(b.dataset.title)} <span class="pill ok">from the
            studio</span></h3>
          <iframe class="doc-viewer" src="${url}"
            title="${esc(b.dataset.title)}"></iframe>
          <div class="modal-foot">
            <span class="dim" style="margin-right:auto">Read-only — this is
              the studio's copy. Signing happens on your roadmap.</span>
            <button class="btn alt" data-close>Close</button>
          </div>`, "wide");
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-studiopdf]").forEach((b) => b.onclick =
    async () => {
      try {
        const r = await fetch(
          `/api/store/admin/studio/doc/${b.dataset.studiopdf}/pdf`,
          { headers: { Authorization: "Bearer " + S.user.token } });
        if (!r.ok) throw new Error((await r.json()).detail || r.status);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(await r.blob());
        a.download = b.dataset.title + ".pdf";
        document.body.appendChild(a); a.click(); a.remove();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-docview]").forEach((b) => b.onclick = () =>
    docViewer(+b.dataset.docview, b.dataset.kind, b.dataset.ext,
              b.dataset.name, b.dataset.signed, renderDocs));
  view().querySelectorAll("[data-docedit]").forEach((b) => b.onclick = () =>
    docForm(DOCS.documents.find((x) => x.id === +b.dataset.docedit)));
  view().querySelectorAll("[data-sign]").forEach((b) => b.onclick = () =>
    signForm(+b.dataset.sign));
  view().querySelectorAll("[data-sigcheck]").forEach((b) => b.onclick = async () => {
    try {
      const out = await api(`/api/store/admin/signatures/${b.dataset.sigcheck}/refresh`,
        { method: "POST" });
      toast(out.status === "signed" ? "Signed — pulled back from DocuSign"
        : out.detail || `status: ${out.status}`);
      renderDocs();
    } catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-void]").forEach((b) => b.onclick = async () => {
    if (!confirm("Void this signature request?")) return;
    try { await api(`/api/store/admin/signatures/${b.dataset.void}/void`,
      { method: "POST" }); renderDocs(); }
    catch (e) { toast(e.message); }
  });
}

function docForm(d) {
  const cats = Object.entries(DOCS.categories).map(([k, v]) =>
    `<option value="${k}" ${d && d.category === k ? "selected" : ""}>${v}</option>`).join("");
  const kinds = Object.entries(DOCS.party_kinds).map(([k, v]) =>
    `<option value="${k}" ${d && d.party_kind === k ? "selected" : ""}>${v}</option>`).join("");
  const day = (t) => t ? new Date(t * 1000).toISOString().slice(0, 10) : "";
  modal(`<h3>${d ? "Edit document" : "New document"}</h3>
    <label>Title</label>
    <input id="nd-title" value="${esc((d && d.title) || "")}"
      placeholder="Supply agreement — Hudson DC">
    <div class="row2">
      <div><label>Category</label><select id="nd-cat">${cats}</select></div>
      <div><label>Concerns</label><select id="nd-kind">${kinds}</select></div>
    </div>
    <div class="row2">
      <div><label>Party name</label>
        <input id="nd-party" value="${esc((d && d.party_name) || "")}"></div>
      <div><label>Party email</label>
        <input id="nd-email" type="email" value="${esc((d && d.party_email) || "")}"></div>
    </div>
    <div class="row2">
      <div><label>Effective</label>
        <input id="nd-eff" type="date" value="${day(d && d.effective)}"></div>
      <div><label>Expires <span class="dim">(optional)</span></label>
        <input id="nd-exp" type="date" value="${day(d && d.expires)}"></div>
    </div>
    <label>File ${d && d.has_file
      ? `<span class="dim">— currently ${esc(d.filename || "attached")};
         uploading replaces it</span>` : '<span class="dim">(PDF, image or Office)</span>'}</label>
    <input id="nd-file" type="file">
    <label>${d && d.has_file ? "Notes for the reader" : "Or write the document"}</label>
    <textarea id="nd-body" rows="5"
      placeholder="Paste or write the agreement text. This is what a signer sees."
      >${esc((d && d.body) || "")}</textarea>
    <label>Internal notes</label>
    <input id="nd-notes" value="${esc((d && d.notes) || "")}">
    ${d ? `<label>Status</label><select id="nd-status">
      ${["draft", "active", "superseded", "archived"].map((st) =>
        `<option ${d.status === st ? "selected" : ""}>${st}</option>`).join("")}
      </select>` : ""}
    ${d && d.signatures && d.signatures.some((s) => s.status === "signed")
      ? `<p class="dim" style="font-size:12px;margin-top:10px">This document
         has been signed. Editing the text or replacing the file will make the
         signing certificate report a fingerprint mismatch — which is the
         point, but supersede it with a new document instead if you want a
         clean record.</p>` : ""}
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="nd-save">Save</button>
    </div>`);
  $("#nd-save").onclick = async () => {
    const title = $("#nd-title").value.trim();
    if (!title) return toast("a document needs a title");
    const dt = (v) => v ? new Date(v + "T12:00").getTime() / 1000 : 0;
    const payload = { title, category: $("#nd-cat").value,
      party_kind: $("#nd-kind").value,
      party_name: $("#nd-party").value.trim(),
      party_email: $("#nd-email").value.trim(),
      body: $("#nd-body").value, notes: $("#nd-notes").value.trim(),
      effective: dt($("#nd-eff").value), expires: dt($("#nd-exp").value) };
    try {
      let id = d && d.id;
      if (d) await api(`/api/store/admin/documents/${d.id}`,
        { method: "PATCH", body: payload });
      else id = (await api("/api/store/admin/documents", { body: payload })).id;
      if (d && $("#nd-status")) await api(
        `/api/store/admin/documents/${d.id}/status`,
        { body: { status: $("#nd-status").value } });
      const f = $("#nd-file").files[0];
      if (f) {
        const fd = new FormData(); fd.append("file", f);
        const r = await fetch(`/api/store/admin/documents/${id}/file`, {
          method: "POST", headers: { Authorization: "Bearer " + S.user.token },
          body: fd });
        if (!r.ok) toast("saved, but the file upload failed: "
          + ((await r.json()).detail || r.status));
      }
      closeModal(); renderDocs();
    } catch (e) { toast(e.message); }
  };
}

function signForm(did) {
  const d = DOCS.documents.find((x) => x.id === did);
  modal(`<h3>Request a signature</h3>
    <p class="dim">${esc(d.title)}</p>
    <div class="row2">
      <div><label>Signer name</label>
        <input id="sr-name" value="${esc(d.party_name || "")}"></div>
      <div><label>Signer email</label>
        <input id="sr-email" type="email" value="${esc(d.party_email || "")}"></div>
    </div>
    <label>Role</label>
    <select id="sr-role"><option value="signer">Signer</option>
      <option value="approver">Approver</option>
      <option value="witness">Witness</option></select>
    <label>Message <span class="dim">(optional)</span></label>
    <textarea id="sr-msg" rows="2"></textarea>
    <p class="dim" style="font-size:12px;margin-top:10px">They'll get a unique
      link. Signing records their name, time, IP and a fingerprint of the
      document — a simple electronic signature valid under ESIGN and eIDAS.</p>
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="sr-send">Send request</button>
    </div>`);
  $("#sr-send").onclick = async () => {
    try {
      const out = await api(`/api/store/admin/documents/${did}/request-signature`,
        { body: { signer_name: $("#sr-name").value.trim(),
          signer_email: $("#sr-email").value.trim(),
          role: $("#sr-role").value, message: $("#sr-msg").value } });
      closeModal();
      toast("Signing link sent");
      prompt("Signing link (also emailed):", out.link);
      renderDocs();
    } catch (e) { toast(e.message); }
  };
}

// ---------- stores rail ----------
/* A persistent list of accounts beside the work. Field staff spend the day
   asking "which stores are in this region and what's low" — making them
   change tab to find out was the wrong default. */
async function drawStoreRail() {
  const rail = $("#store-rail");
  if (!rail || !S.user) return;
  if (!["shop", "inventory", "routes", "outreach", "orders", "hq"]
      .includes(S.tab)) { rail.innerHTML = ""; rail.hidden = true; return; }
  rail.hidden = false;
  let stores = S._stores;
  if (!stores) { stores = S._stores = await api("/api/stores"); }
  const q = (S.railQ || "").toLowerCase();
  const shown = stores.filter((st) =>
    !q || (st.name + " " + st.city + " " + st.region).toLowerCase().includes(q));
  const byRegion = {};
  shown.forEach((st) => (byRegion[st.region] = byRegion[st.region] || []).push(st));
  rail.innerHTML = `
    <div class="rail-head">
      <b>Stores</b><span class="dim">${shown.length}</span>
    </div>
    <input id="rail-q" placeholder="Filter" value="${esc(S.railQ || "")}">
    <div class="rail-list">
      ${Object.entries(byRegion).map(([region, list]) => `
        <div class="rail-group">
          <span class="rail-region"><i style="background:${
            REGION_COLORS[region] || "#8b98a5"}"></i>${esc(region)}</span>
          ${list.map((st) => `
            <button class="rail-item ${S.railPick === st.id ? "on" : ""}"
              data-rail="${st.id}">
              <b>${esc(st.name)}</b>
              <span class="dim">${esc(st.city)}${
                st.kind === "distributor_dc" ? " · DC" : ""}</span>
            </button>`).join("")}
        </div>`).join("") || '<p class="dim" style="padding:8px">No matches.</p>'}
    </div>`;
  let t;
  $("#rail-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.railQ = e.target.value; drawStoreRail(); }, 200); };
  rail.querySelectorAll("[data-rail]").forEach((b) => b.onclick = async () => {
    S.railPick = +b.dataset.rail;
    const st = stores.find((x) => x.id === S.railPick);
    const inv = await api("/api/inventory").catch(() => []);
    const mine = inv.filter((i) => i.store_id === st.id);
    modal(`<h3>${esc(st.name)}</h3>
      <p class="dim">${esc(st.city)} · ${esc(st.region)}${
        st.kind === "distributor_dc" ? " · distribution centre" : ""}${
        st.contact ? " · " + esc(st.contact) : ""}</p>
      ${mine.length ? `<table><thead><tr><th>product</th><th class="num">on hand</th>
        <th class="num">par</th></tr></thead><tbody>
        ${mine.map((i) => `<tr class="${i.low ? "low" : ""}">
          <td>${esc(i.product_name || i.product_id)}</td>
          <td class="num">${i.qty}</td><td class="num">${i.par}</td></tr>`).join("")}
        </tbody></table>` : '<p class="dim">No inventory recorded here yet.</p>'}
      <div class="modal-acts"><button class="btn alt" data-close>Close</button></div>`);
    drawStoreRail();
  });
}
