// ---------- presentations ----------
/* Made here, recorded here, or brought in — and shown. A deck is slides
   written in the app; a recording is the screen with the presenter's
   voice, the camera, or the voice alone, captured in this browser; a file
   is a .pptx, a PDF or a film from elsewhere. Every one has a link that
   needs no sign-in, and any of them can be attached to a class so it is
   there to put on the stage of a live class. */
let PR_REC = null;

async function renderPresentations() {
  const d = await api("/api/presentations");
  const kindPill = (k) => `<span class="pill${k === "recording" ? " ok" : ""}">${esc(k)}</span>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Presentations</h2>
        <p class="dim">Slides written here, a screen recorded with your voice, or a
          deck brought in. Each has a link anyone can open; attach one to a class
          and it is on the course page and the stage.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="pr-upload">Upload a file</button>
        <button class="btn alt" id="pr-record">Record</button>
        <button class="btn" id="pr-new">${opsIcon("pen", "btn-ic")} New deck</button>
      </div>
    </div>
    ${d.presentations.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>title</th><th>kind</th><th>class</th><th>seen</th><th>link</th><th></th></tr></thead>
      <tbody>${d.presentations.map((p) => `<tr class="${p.published ? "" : "dim"}">
        <td><b>${esc(p.title)}</b>${p.blurb ? `<div class="dim">${esc(p.blurb).slice(0, 90)}</div>` : ""}
          <div class="dim">${p.kind === "deck" ? `${p.slides.length} slide${p.slides.length === 1 ? "" : "s"}`
            : p.material ? esc(p.material.original || p.material.kind) : "nothing uploaded yet"}</div></td>
        <td>${kindPill(p.kind)}${p.published ? "" : ' <span class="pill warn">hidden</span>'}</td>
        <td class="dim">${esc(p.course || "—")}</td>
        <td><b>${p.viewers}</b> <span class="dim">· ${p.views} views</span></td>
        <td><code class="cl-link">${esc(p.url)}</code>
          <button class="btn alt sm" data-prcopy="${esc(p.url)}">Copy</button></td>
        <td class="row-acts">
          <a class="btn alt sm" href="${esc(p.url)}${p.kind === "deck" ? "?notes=1" : ""}" target="_blank" rel="noopener">Present</a>
          ${p.kind === "deck" ? `<button class="btn alt sm" data-predit="${p.id}">Edit</button>
            <a class="btn alt sm" href="/api/presentations/${p.id}/export.pdf?notes=1" download title="slides, then the speaker notes">PDF</a>
            <a class="btn alt sm" href="/api/presentations/${p.id}/export.pptx" download>PowerPoint</a>` : ""}
          ${p.kind !== "deck" ? `<label class="btn alt sm">Replace file<input type="file" hidden data-prfile="${p.id}"></label>` : ""}
          <button class="btn alt sm" data-prattach="${p.id}" title="on the course page, in every session's Shared tab, on the stage">Attach to class</button>
          <button class="btn alt sm" data-prdel="${p.id}">Delete</button></td>
      </tr>`).join("")}</tbody></table></div></div>`
      : `<div class="card empty"><b>Nothing yet</b><span class="dim">Write a deck, record your screen
        with your voice, or upload a PowerPoint, a PDF or a film.</span></div>`}`;
  $("#pr-new").onclick = async () => {
    const title = prompt("A title for the deck");
    if (!title) return;
    try { const p = await api("/api/presentations", { body: { title, kind: "deck" } }); deckEditor(p.id); }
    catch (err) { toast(err.message); }
  };
  $("#pr-record").onclick = () => recordPresentation(renderPresentations);
  $("#pr-upload").onclick = () => uploadPresentation(renderPresentations);
  view().querySelectorAll("[data-prcopy]").forEach((b) => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.prcopy); toast("link copied"); } catch (e) { toast(b.dataset.prcopy); }
  });
  view().querySelectorAll("[data-predit]").forEach((b) => b.onclick = () => deckEditor(+b.dataset.predit));
  view().querySelectorAll("[data-prdel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Delete this presentation? Its link stops working.")) return;
    try { await api(`/api/presentations/${b.dataset.prdel}`, { method: "DELETE" }); renderPresentations(); }
    catch (err) { toast(err.message); }
  });
  view().querySelectorAll("[data-prattach]").forEach((b) => b.onclick = () => {
    const p = d.presentations.find((x) => String(x.id) === b.dataset.prattach);
    modal(`<h3>Attach to a class</h3>
      <p class="dim">A deck goes as its PDF; a recording or a file goes as itself. It appears on
        the course page, in every session's Shared tab, and can be put on the stage.</p>
      <label>Class</label>
      <select id="pra-course">${d.courses.map((c) => `<option value="${c.id}"${p.course_id === c.id ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
      <div class="modal-foot"><button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="pra-go">Attach</button></div>`);
    $("#pra-go").onclick = async () => {
      try { await api(`/api/presentations/${p.id}/attach`, { body: { course_id: +$("#pra-course").value } });
        closeModal(); toast("attached — it is on the course page now"); renderPresentations(); }
      catch (err) { toast(err.message); }
    };
  });
  view().querySelectorAll("[data-prfile]").forEach((inp) => inp.onchange = () =>
    uploadBytes(`/api/presentations/${inp.dataset.prfile}/file`, inp.files[0], renderPresentations));
}

async function uploadBytes(path, f, after) {
  if (!f) return;
  toast(`uploading ${f.name}…`);
  try {
    const r = await fetch(path, { method: "POST",
      headers: { "Content-Type": f.type || "application/octet-stream", "X-Filename": f.name,
                 Authorization: "Bearer " + S.user.token }, body: f });
    if (!r.ok) throw new Error((await r.json()).detail || "upload failed");
    toast("saved");
    if (after) after();
  } catch (err) { toast(err.message); }
}

/* A .pptx, a PDF, a film, a sound file: one presentation each. */
function uploadPresentation(after) {
  modal(`<h3>Upload a presentation</h3>
    <label>Title</label><input id="pu-title" placeholder="what it is called">
    <label>File <span class="opt">.pptx, .pdf, a film, a sound file, a picture</span></label>
    <input id="pu-file" type="file" accept=".pptx,.pdf,.txt,.md,video/*,audio/*,image/*">
    <div class="modal-foot"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="pu-go">Upload</button></div>`);
  $("#pu-go").onclick = async () => {
    const f = $("#pu-file").files[0];
    const title = $("#pu-title").value.trim() || (f && f.name.replace(/\.[^.]+$/, ""));
    if (!f || !title) return toast("a title and a file");
    try {
      const p = await api("/api/presentations", { body: { title, kind: "file" } });
      closeModal();
      await uploadBytes(`/api/presentations/${p.id}/file`, f, after);
    } catch (err) { toast(err.message); }
  };
}

/* The screen with your voice, the camera with your voice, or the voice
   alone — captured here, saved as a presentation. The screen's own sound
   (a video playing in it) is mixed in when the browser offers it. */
function recordPresentation(after) {
  if (PR_REC) return toast("a recording is already running");
  modal(`<h3>Record a presentation</h3>
    <div class="row2">
      <div><label>What to record</label>
        <select id="pr-mode">
          <option value="screen">My screen, with my voice</option>
          <option value="camera">My camera, with my voice</option>
          <option value="voice">My voice only</option></select></div>
      <div><label>Title</label><input id="pr-title" placeholder="what this is"></div>
    </div>
    <p class="dim">Pick the window or screen when the browser asks. Talk as you go; the
      recording ends when you press Stop or close the share. Up to two hours.</p>
    <div class="pr-stage"><video id="pr-preview" autoplay muted playsinline hidden></video>
      <div class="pr-meter" id="pr-state">Not recording</div></div>
    <div class="modal-foot">
      <button class="btn alt" data-close id="pr-cancel">Cancel</button>
      <button class="btn" id="pr-start">Start</button>
      <button class="btn" id="pr-stop" hidden>Stop and save</button></div>`, "wide");
  const state = (m) => { const el = $("#pr-state"); if (el) el.textContent = m; };
  let ctx = null, tracksToStop = [];
  const teardown = () => {
    for (const t of tracksToStop) { try { t.stop(); } catch (e) {} }
    tracksToStop = [];
    if (ctx) { try { ctx.close(); } catch (e) {} ctx = null; }
    PR_REC = null;
  };
  $("#pr-cancel").onclick = () => { if (PR_REC) PR_REC.discard(); teardown(); closeModal(); };
  $("#pr-start").onclick = async () => {
    try { await loadCallScript("/rtc-compose.js", () => window.LinguaCompose); }
    catch (e) { return toast(e.message); }
    const mode = $("#pr-mode").value;
    let stream;
    try {
      if (mode === "voice") {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } else if (mode === "camera") {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: { width: 1280, height: 720 } });
      } else {
        if (!navigator.mediaDevices.getDisplayMedia) return toast("this browser cannot record a screen");
        const screen = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
        let mic = null;
        try { mic = await navigator.mediaDevices.getUserMedia({ audio: true }); }
        catch (e) { toast("no microphone — recording the screen without a voice"); }
        // one audio track from two sources: the screen's own sound and the voice
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        const dest = ctx.createMediaStreamDestination();
        if (screen.getAudioTracks().length) ctx.createMediaStreamSource(new MediaStream(screen.getAudioTracks())).connect(dest);
        if (mic) ctx.createMediaStreamSource(mic).connect(dest);
        stream = new MediaStream([...screen.getVideoTracks(), ...dest.stream.getAudioTracks()]);
        tracksToStop.push(...screen.getTracks(), ...(mic ? mic.getTracks() : []));
        screen.getVideoTracks()[0].onended = () => { if (PR_REC) $("#pr-stop").click(); };
      }
    } catch (err) { return toast(err.message || "could not start"); }
    tracksToStop.push(...stream.getTracks());
    const pv = $("#pr-preview");
    if (mode !== "voice") { pv.hidden = false; pv.srcObject = stream; }
    PR_REC = window.LinguaCompose.createRecorder({
      kind: mode === "voice" ? "audio" : "video", source: stream, maxSeconds: 2 * 3600,
      onTick: (s) => state("Recording " + window.LinguaCompose.fmtSecs(s)),
      onError: (m) => toast(m) });
    try { await PR_REC.start(); } catch (err) { teardown(); return toast(err.message); }
    $("#pr-start").hidden = true; $("#pr-stop").hidden = false; $("#pr-mode").disabled = true;
  };
  $("#pr-stop").onclick = async () => {
    if (!PR_REC) return;
    const rec = PR_REC;
    const blob = await rec.stop();
    const mode = $("#pr-mode").value;
    const title = $("#pr-title").value.trim() || `Recording ${new Date().toLocaleString()}`;
    teardown();
    if (!blob || !blob.size) { rec.discard(); return toast("nothing was recorded"); }
    state("Saving…");
    try {
      const p = await api("/api/presentations", { body: { title, kind: "recording" } });
      const r = await fetch(`/api/presentations/${p.id}/file`, { method: "POST",
        headers: { "Content-Type": blob.type || (mode === "voice" ? "audio/webm" : "video/webm"),
                   "X-Filename": rec.filename(mode === "voice" ? "voice" : "screen"),
                   Authorization: "Bearer " + S.user.token }, body: blob });
      if (!r.ok) throw new Error((await r.json()).detail || "upload failed");
      rec.discard();
      closeModal();
      toast("saved — the link is on the list");
      if (after) after();
    } catch (err) { state(err.message); toast(err.message); }
  };
}

/* Slides: a title, lines, a picture, and notes for the speaker. Saved as
   they are; exported as a PDF or a PowerPoint when somebody wants one. */
async function deckEditor(pid) {
  const p = await api(`/api/presentations/${pid}`);
  const slides = p.slides.length ? p.slides : [{ title: "", lines: [], image: "", notes: "" }];
  const draw = () => {
    view().innerHTML = `
      <div class="page-head">
        <div><h2>${esc(p.title)}</h2>
          <p class="dim">${slides.length} slide${slides.length === 1 ? "" : "s"} · arrows and space move
            through them when presented · N shows the notes</p></div>
        <div class="top-actions">
          <button class="btn alt" id="de-back">&larr; Presentations</button>
          <a class="btn alt" href="${esc(p.url)}?notes=1" target="_blank" rel="noopener">Present</a>
          <button class="btn" id="de-save">Save</button>
        </div>
      </div>
      <div class="card">
        <div class="row2">
          <div><label>Title</label><input id="de-title" value="${esc(p.title)}"></div>
          <div><label>Blurb <span class="opt">under the slides, on the link</span></label>
            <input id="de-blurb" value="${esc(p.blurb || "")}"></div>
        </div>
        <label class="dim" style="display:flex;gap:8px;align-items:center;margin-top:6px">
          <input type="checkbox" id="de-pub"${p.published ? " checked" : ""}> Published — the link opens</label>
      </div>
      ${slides.map((s, i) => `<div class="card pr-slide" data-i="${i}">
        <div class="card-head"><b>Slide ${i + 1}</b>
          <span class="chips">
            <button class="btn alt sm" data-sup="${i}" ${i === 0 ? "disabled" : ""}>&uarr;</button>
            <button class="btn alt sm" data-sdown="${i}" ${i === slides.length - 1 ? "disabled" : ""}>&darr;</button>
            <button class="btn alt sm" data-sdel="${i}">remove</button></span></div>
        <div class="row">
          <div style="flex:2;min-width:min(280px,100%)">
            <label>Heading</label><input data-st="${i}" value="${esc(s.title)}">
            <label>Lines <span class="opt">one per line — they become the bullets</span></label>
            <textarea data-sl="${i}" rows="5">${esc(s.lines.join("\n"))}</textarea>
            <label>Speaker notes <span class="opt">only you see these</span></label>
            <textarea data-sn="${i}" rows="2">${esc(s.notes)}</textarea>
          </div>
          <div style="flex:1;min-width:min(200px,100%)">
            <label>Picture</label>
            ${s.image ? `<img class="pr-thumb" src="/media/${esc(s.image)}" alt="">` : '<p class="dim">none</p>'}
            <label class="btn alt sm">${s.image ? "Replace" : "Add a picture"}<input type="file" hidden accept="image/*" data-simg="${i}"></label>
          </div>
        </div>
      </div>`).join("")}
      <button class="btn alt" id="de-add">+ Add a slide</button>`;
    const collect = () => {
      view().querySelectorAll(".pr-slide").forEach((card) => {
        const i = +card.dataset.i;
        slides[i].title = card.querySelector(`[data-st="${i}"]`).value;
        slides[i].lines = card.querySelector(`[data-sl="${i}"]`).value.split("\n");
        slides[i].notes = card.querySelector(`[data-sn="${i}"]`).value;
      });
    };
    const save = async (quiet) => {
      collect();
      try {
        const r = await api(`/api/presentations/${pid}`, { body: {
          title: $("#de-title").value.trim(), blurb: $("#de-blurb").value.trim(),
          slides, published: $("#de-pub").checked } });
        p.title = r.title; p.blurb = r.blurb; p.published = r.published;
        if (!quiet) toast("saved");
        return true;
      } catch (err) { toast(err.message); return false; }
    };
    $("#de-save").onclick = () => save(false).then((ok) => ok && draw());
    $("#de-back").onclick = () => save(true).then(renderPresentations);
    $("#de-add").onclick = () => { collect(); slides.push({ title: "", lines: [], image: "", notes: "" }); draw(); };
    view().querySelectorAll("[data-sdel]").forEach((b) => b.onclick = () => {
      collect(); slides.splice(+b.dataset.sdel, 1); if (!slides.length) slides.push({ title: "", lines: [], image: "", notes: "" }); draw(); });
    view().querySelectorAll("[data-sup]").forEach((b) => b.onclick = () => {
      collect(); const i = +b.dataset.sup; [slides[i - 1], slides[i]] = [slides[i], slides[i - 1]]; draw(); });
    view().querySelectorAll("[data-sdown]").forEach((b) => b.onclick = () => {
      collect(); const i = +b.dataset.sdown; [slides[i + 1], slides[i]] = [slides[i], slides[i + 1]]; draw(); });
    view().querySelectorAll("[data-simg]").forEach((inp) => inp.onchange = async () => {
      const f = inp.files[0]; if (!f) return;
      if (!(await save(true))) return;
      try {
        const r = await fetch(`/api/presentations/${pid}/slides/${inp.dataset.simg}/image`, { method: "POST",
          headers: { "Content-Type": f.type || "application/octet-stream", Authorization: "Bearer " + S.user.token }, body: f });
        if (!r.ok) throw new Error((await r.json()).detail || "upload failed");
        slides[+inp.dataset.simg].image = (await r.json()).image; draw();
      } catch (err) { toast(err.message); }
    });
  };
  draw();
}
