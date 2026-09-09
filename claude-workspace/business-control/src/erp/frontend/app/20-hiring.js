// ---------- hiring ----------
/* A posting, the people who answered it, and the first week. The boards
   read one feed and post back to one address; the page anyone can apply
   on is ours. Hiring somebody opens their account and their list. */
async function renderHiring() {
  const d = await api("/api/hiring");
  const byStage = {};
  d.applicants.forEach((a) => (byStage[a.stage] = byStage[a.stage] || []).push(a));
  const stageLabel = { new: "New", screen: "Screening", interview: "Interview",
    offer: "Offer", hired: "Hired", declined: "Declined" };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Hiring</h2>
        <p class="dim">Open postings are on <a href="${esc(d.page_url)}" target="_blank" rel="noopener">${esc(d.page_url)}</a>
          and in the feed the job boards read. Every application, from any
          board or the page or the phone, lands on one board below.</p></div>
      <div class="top-actions">
        <button class="btn alt" id="hir-add">Add an applicant</button>
        <button class="btn" id="hir-new">New posting</button>
      </div>
    </div>
    <h3>Postings</h3>
    ${d.postings.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>title</th><th>kind</th><th>where</th><th>state</th><th>open applicants</th><th></th></tr></thead>
      <tbody>${d.postings.map((p) => `<tr>
        <td><b>${esc(p.title)}</b>${p.department ? `<br><span class="dim">${esc(p.department)}</span>` : ""}</td>
        <td class="dim">${esc(p.kind_label)}</td>
        <td class="dim">${esc(p.location || "")}${p.remote ? " · remote" : ""}</td>
        <td><span class="pill ${p.state === "open" ? "ok" : ""}">${esc(p.state)}</span></td>
        <td>${p.open_applicants}</td>
        <td class="chips"><button class="btn alt sm" data-hiredit="${p.id}">Edit</button>
          ${p.state === "open" ? `<a class="btn alt sm" href="/jobs/${esc(p.slug)}" target="_blank" rel="noopener">View</a>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("users", "No postings yet", "Write one and open it; the page and the feed fill themselves.")}
    <h3>Applicants</h3>
    <div class="tiles">${d.stages.map((s) => `<div class="card tile"><span class="dim">${stageLabel[s]}</span>
      <b>${(byStage[s] || []).length}</b></div>`).join("")}</div>
    ${d.applicants.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>who</th><th>for</th><th>from</th><th>stage</th><th>when</th><th></th></tr></thead>
      <tbody>${d.applicants.map((a) => `<tr class="${a.stage === "declined" ? "dim" : ""}">
        <td><b>${esc(a.name)}</b><br><span class="dim">${esc(a.email || "")}${a.phone ? " · " + esc(a.phone) : ""}</span></td>
        <td class="dim">${esc(a.posting_title || "—")}</td>
        <td class="dim">${esc(a.source)}</td>
        <td>${a.stage === "hired" ? '<span class="pill ok">hired</span>'
          : `<select data-hirstage="${a.id}">${d.stages.filter((s) => s !== "hired").map((s) =>
              `<option value="${s}" ${s === a.stage ? "selected" : ""}>${stageLabel[s]}</option>`).join("")}</select>`}</td>
        <td class="dim">${fmtAgo(a.updated_at)}</td>
        <td class="chips"><button class="btn alt sm" data-hirview="${a.id}">Open</button>
          ${a.stage !== "hired" && a.stage !== "declined" ? `<button class="btn sm" data-hirhire="${a.id}">Hire</button>` : ""}
          ${a.user_id ? `<button class="btn alt sm" data-hirlist="${a.user_id}">Onboarding</button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("users", "Nobody has applied yet", "Open a posting, or add the person who phoned.")}
    ${d.onboarding.length ? `<h3>Onboarding</h3><div class="card"><div class="tablewrap"><table>
      <thead><tr><th>who</th><th>done</th><th></th></tr></thead>
      <tbody>${d.onboarding.map((o) => `<tr><td><b>${esc(o.name)}</b></td>
        <td>${o.done} of ${o.total}${o.done === o.total ? ' <span class="pill ok">complete</span>' : ""}</td>
        <td><button class="btn alt sm" data-hirlist="${o.user_id}">Open the list</button></td></tr>`).join("")}</tbody>
      </table></div></div>` : ""}
    <h3>Job boards and applicant systems</h3>
    <div class="card">
      <p class="dim">The boards take postings by feed, not by API. Give each
        of them this feed address, and give their apply-webhook the inbound
        address from its card below.</p>
      <label>Feed</label><input value="${esc(d.feed_url)}" readonly>
    </div>
    <div id="hir-cxn"></div>`;

  const postingForm = (p) => {
    modal(`<h3>${p ? "Edit" : "New"} posting</h3>
      <label>Title</label><input id="hir-title" value="${esc(p ? p.title : "")}" placeholder="Evening class assistant">
      <div class="row2">
        <div><label>Kind</label><select id="hir-kind">${d.kinds.map((k) =>
          `<option value="${k.k}" ${p && p.kind === k.k ? "selected" : ""}>${esc(k.label)}</option>`).join("")}</select></div>
        <div><label>Department</label><input id="hir-dept" value="${esc(p ? p.department : "")}"></div>
      </div>
      <div class="row2">
        <div><label>Location <span class="dim">(City, Region)</span></label><input id="hir-loc" value="${esc(p ? p.location : "")}"></div>
        <div><label>Pay</label><input id="hir-pay" value="${esc(p ? p.pay_text : "")}" placeholder="$18/hr"></div>
      </div>
      <label class="perm"><input type="checkbox" id="hir-remote" ${p && p.remote ? "checked" : ""}><span>Remote</span></label>
      <label>Description</label><textarea id="hir-desc" rows="5">${esc(p ? p.description : "")}</textarea>
      <label>Requirements</label><textarea id="hir-req" rows="3">${esc(p ? p.requirements : "")}</textarea>
      <div class="row2">
        <div><label>A hire becomes</label><select id="hir-role">${["employee", "teacher", "volunteer", "cashier", "distributor"].map((r) =>
          `<option value="${r}" ${p && p.role === r ? "selected" : ""}>${r}</option>`).join("")}</select></div>
        <div><label>State</label><select id="hir-state">${["draft", "open", "closed"].map((s) =>
          `<option value="${s}" ${p && p.state === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>
      </div>
      <p><button class="btn" id="hir-save">Save</button></p>`, "wide");
    $("#hir-save").onclick = async () => {
      try {
        await api("/api/hiring/postings", { body: {
          id: p ? p.id : 0, title: $("#hir-title").value, kind: $("#hir-kind").value,
          department: $("#hir-dept").value, location: $("#hir-loc").value,
          pay_text: $("#hir-pay").value, remote: $("#hir-remote").checked,
          description: $("#hir-desc").value, requirements: $("#hir-req").value,
          role: $("#hir-role").value, state: $("#hir-state").value } });
        closeModal(); renderHiring();
      } catch (e) { toast(e.message); }
    };
  };
  $("#hir-new").onclick = () => postingForm(null);
  view().querySelectorAll("[data-hiredit]").forEach((b) => b.onclick = () =>
    postingForm(d.postings.find((p) => p.id === +b.dataset.hiredit)));
  $("#hir-add").onclick = () => {
    modal(`<h3>Add an applicant</h3>
      <div class="row2">
        <div><label>Name</label><input id="hir-aname"></div>
        <div><label>Email</label><input id="hir-amail" type="email"></div>
      </div>
      <div class="row2">
        <div><label>Phone</label><input id="hir-aphone"></div>
        <div><label>For</label><select id="hir-apost"><option value="0">—</option>${d.postings.map((p) =>
          `<option value="${p.id}">${esc(p.title)}</option>`).join("")}</select></div>
      </div>
      <label>Notes</label><textarea id="hir-acover" rows="3"></textarea>
      <p><button class="btn" id="hir-asave">Add</button></p>`);
    $("#hir-asave").onclick = async () => {
      try {
        await api("/api/hiring/applicants", { body: { name: $("#hir-aname").value,
          email: $("#hir-amail").value, phone: $("#hir-aphone").value,
          cover: $("#hir-acover").value, posting_id: +$("#hir-apost").value } });
        closeModal(); renderHiring();
      } catch (e) { toast(e.message); }
    };
  };
  view().querySelectorAll("[data-hirstage]").forEach((s) => s.onchange = async () => {
    try { await api(`/api/hiring/applicants/${s.dataset.hirstage}`, { method: "PATCH", body: { stage: s.value } }); renderHiring(); }
    catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-hirview]").forEach((b) => b.onclick = () => {
    const a = d.applicants.find((x) => x.id === +b.dataset.hirview);
    modal(`<h3>${esc(a.name)}</h3>
      <p class="dim">${esc(a.email || "")}${a.phone ? " · " + esc(a.phone) : ""} · via ${esc(a.source)} · ${fmtDate(a.created_at)}</p>
      ${a.resume_key ? `<p><a class="btn alt sm" href="/api/hiring/applicants/${a.id}/resume?token=${encodeURIComponent(S.user.token)}" target="_blank" rel="noopener">Open ${esc(a.resume_name || "the CV")}</a></p>` : ""}
      ${a.cover ? `<div class="card" style="white-space:pre-wrap">${esc(a.cover)}</div>` : ""}
      <label>Notes</label><textarea id="hir-notes" rows="4">${esc(a.notes || "")}</textarea>
      <p><button class="btn" id="hir-nsave">Save notes</button></p>`, "wide");
    $("#hir-nsave").onclick = async () => {
      try { await api(`/api/hiring/applicants/${a.id}`, { method: "PATCH", body: { notes: $("#hir-notes").value } }); closeModal(); renderHiring(); }
      catch (e) { toast(e.message); }
    };
  });
  view().querySelectorAll("[data-hirhire]").forEach((b) => b.onclick = () => {
    const a = d.applicants.find((x) => x.id === +b.dataset.hirhire);
    const post = d.postings.find((p) => p.id === a.posting_id) || {};
    modal(`<h3>Hire ${esc(a.name)}</h3>
      <p class="dim">Opens their account and their onboarding list. No password is
        set; they adopt one the first time they sign in, like everyone.</p>
      <div class="row2">
        <div><label>Role</label><select id="hir-hrole">${["employee", "teacher", "volunteer", "cashier", "distributor"].map((r) =>
          `<option value="${r}" ${(post.role || "employee") === r ? "selected" : ""}>${r}</option>`).join("")}</select></div>
        <div><label>Paid as</label><select id="hir-hemp"><option value="employee">employee (hourly)</option>
          <option value="contractor">contractor</option></select></div>
      </div>
      <label>Email</label><input id="hir-hmail" value="${esc(a.email || "")}">
      <p><button class="btn" id="hir-hgo">Hire</button></p>`);
    $("#hir-hgo").onclick = async () => {
      try {
        const r = await api(`/api/hiring/applicants/${a.id}/hire`, { body: {
          role: $("#hir-hrole").value, employment: $("#hir-hemp").value, email: $("#hir-hmail").value } });
        closeModal(); toast(`${a.name} has an account (#${r.user_id}) and a list`); renderHiring();
      } catch (e) { toast(e.message); }
    };
  });
  view().querySelectorAll("[data-hirlist]").forEach((b) => b.onclick = async () => {
    const uid = b.dataset.hirlist;
    const r = await api(`/api/hiring/onboarding/${uid}`);
    modal(`<h3>Onboarding</h3>
      <div class="perm-grid">${r.tasks.map((t) => `<label class="perm">
        <input type="checkbox" data-hirtask="${t.id}" ${t.done_at ? "checked" : ""}>
        <span><b>${esc(t.title)}</b><small>${t.done_at ? `done by ${esc(t.done_by)} ${fmtAgo(t.done_at)}` : `on the ${esc(t.tab)} screen`}</small></span>
      </label>`).join("")}</div>`);
    modalBody().querySelectorAll("[data-hirtask]").forEach((c) => c.onchange = async () => {
      try { await api(`/api/hiring/onboarding/${c.dataset.hirtask}/done`, { method: "POST" }); }
      catch (e) { toast(e.message); }
    });
  });
  connectionCards(["indeed", "ziprecruiter", "linkedin_jobs", "greenhouse", "workable"], renderHiring, $("#hir-cxn"))
    .then(() => {
      // the ATSs pull; put the button on their cards
      ["greenhouse", "workable"].forEach((n) => {
        const card = view().querySelector(`[data-cxn="${n}"] .doc-top`);
        const p = d.connections.find((c) => c.name === n);
        if (!card || !p || !p.connected) return;
        const b = document.createElement("button");
        b.className = "btn alt sm"; b.textContent = "Pull candidates";
        b.onclick = async () => {
          try { const r = await api(`/api/hiring/${n}/pull`, { method: "POST" }); toast(`${r.seen} seen, ${r.new} new`); renderHiring(); }
          catch (e) { toast(e.message); }
        };
        card.appendChild(b);
      });
    });
}
