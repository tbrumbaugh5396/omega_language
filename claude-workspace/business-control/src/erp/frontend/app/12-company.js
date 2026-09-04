// ---------- profile ----------
async function renderProfile() {
  /* Your own record is the one screen that has to work for everyone signed
     in. Achievements and company level are the business's scoreboard, and
     both endpoints are owner-only — awaiting them alongside /api/me meant a
     customer or an employee opening their own profile got nothing at all,
     because one rejected promise fails the whole batch. They're optional
     now, and the sections they feed simply aren't drawn without them. */
  const [me, ach, game] = await Promise.all([
    api("/api/me"),
    api("/api/achievements").catch(() => []),
    api("/api/game").catch(() => null)]);
  const earned = ach.filter((a) => a.unlocked_at);
  const locked = ach.filter((a) => !a.unlocked_at);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>${esc(me.name)}</h2>
        <p class="dim">${esc(me.role)}${me.is_admin ? " · owner" : ""}
          ${me.job && me.job !== "general" ? " · " + esc(JOB_LABEL[me.job] || me.job) : ""}
          ${me.region ? " · " + esc(me.region) : ""}</p></div>
      <button class="btn" id="pf-edit">Edit profile</button>
    </div>

    <div class="stats">
      ${ach.length ? `<div class="stat"><div class="n">${earned.length}</div>
        <div class="l">achievements</div>
        <div class="d dim">of ${ach.length}</div></div>` : ""}
      ${game ? `<div class="stat"><div class="n">${esc(game.company.level)}</div>
        <div class="l">company level</div></div>` : ""}
      <div class="stat"><div class="n">${me.has_pin ? "set" : "—"}</div>
        <div class="l">time-clock PIN</div>
        <div class="d dim">${me.has_pin ? "ready to clock in" : "not set"}</div></div>
      <div class="stat"><div class="n">${me.member_since
        ? fmtDate(me.member_since) : "—"}</div>
        <div class="l">member since</div></div>
    </div>

    <div class="row">
      <div class="card" style="flex:2;min-width:300px">
        <h3 style="margin-top:0">Sign in on your phone</h3>
        <p class="dim">Scan this and your phone lands signed in as you. Single
          use, expires in a few minutes — quicker than typing a password on a
          handset in a cold warehouse.</p>
        <div id="pf-qr" style="text-align:center;padding:10px"></div>
        <button class="btn alt" id="pf-qr-go">Generate a sign-in QR</button>
      </div>
      <div class="card" style="flex:1;min-width:240px">
        <h3 style="margin-top:0">Your time-clock badge</h3>
        <p class="dim">Hold this up to the clock tablet to punch in or out.
          It identifies you, but it isn't a sign-in — someone who copies it
          can only clock you in, not open your account. Print it, or keep it
          on your phone.</p>
        <div id="pf-badge" style="text-align:center;padding:10px"></div>
        <button class="btn alt" id="pf-badge-go">Show my badge</button>
        <button class="btn alt" id="pf-badge-reset">Issue a new one</button>
      </div>
      <div class="card" style="flex:1;min-width:220px">
        <h3 style="margin-top:0">Account</h3>
        <table>
          <tr><td class="dim">Email</td><td>${esc(me.email || "—")}</td></tr>
          <tr><td class="dim">Region</td><td>${esc(me.region || "—")}</td></tr>
          <tr><td class="dim">Employment</td><td>${esc(me.employment || "—")}</td></tr>
        </table>
      </div>
    </div>

    ${ach.length ? `<h3>Achievements</h3>
    <div class="ach-grid">
      ${earned.map((a) => `<div class="ach-card on">
        <span class="ach-ic">${opsIcon(a.icon || "shield2")}</span>
        <b>${esc(a.name)}</b><span class="dim">${esc(a.desc || "")}</span>
        <span class="ach-when">${fmtDate(a.unlocked_at)}</span></div>`).join("")}
      ${locked.map((a) => `<div class="ach-card">
        <span class="ach-ic">${opsIcon(a.icon || "shield2")}</span>
        <b>${esc(a.name)}</b><span class="dim">${esc(a.desc || "")}</span>
        <span class="ach-when">${esc(a.progress || "locked")}</span></div>`)
        .join("")}
    </div>` : ""}`;

  const showBadge = async (reset) => {
    if (reset && !confirm("Issue a new badge? The old one stops working, so "
      + "anything printed with it needs replacing.")) return;
    const { token } = await api(
      `/api/me/badge${reset ? "?reset=1" : ""}`, { method: "POST" });
    $("#pf-badge").innerHTML = qrImg(token, 150);
  };
  $("#pf-badge-go").onclick = () => showBadge(false);
  $("#pf-badge-reset").onclick = () => showBadge(true);

  $("#pf-edit").onclick = () => {
    modal(`<h3>Edit profile</h3>
      <label>Name</label><input id="me-name" value="${esc(me.name)}">
      <label>Email</label><input id="me-email" type="email" value="${esc(me.email || "")}">
      <div class="row2">
        <div><label>Region</label><select id="me-region">
          <option value="">—</option>
          ${S.meta.regions.map((r) => `<option ${r === me.region ? "selected" : ""}>${r}</option>`).join("")}
        </select></div>
        <div><label>Time-clock PIN</label>
          <input id="me-pin" inputmode="numeric" placeholder="${me.has_pin ? "leave blank to keep" : "4–8 digits"}"></div>
      </div>
      <p class="dim" style="font-size:12px;margin-top:10px">Role and
        permissions aren't editable here — those are granted by an owner, not
        chosen.</p>
      <div class="modal-acts">
        <button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="me-save">Save</button>
      </div>`);
    $("#me-save").onclick = async () => {
      const payload = { name: $("#me-name").value, email: $("#me-email").value,
        region: $("#me-region").value };
      if ($("#me-pin").value.trim()) payload.pin = $("#me-pin").value.trim();
      try {
        await api("/api/me", { body: payload });
        closeModal();
        if (S.user) { S.user.name = payload.name;
          localStorage.setItem("bc_user", JSON.stringify(S.user)); }
        toast("Profile saved"); renderProfile(); renderChrome();
      } catch (e) { toast(e.message); }
    };
  };
  $("#pf-qr-go").onclick = async () => {
    const out = await api("/api/me/qr", { method: "POST" });
    $("#pf-qr").innerHTML = `${qrImg(out.url, 190)}
      <div class="dim" style="font-size:12px;margin-top:6px">
        expires in ${Math.round(out.expires_sec / 60)} minutes · single use</div>`;
  };
}

// ---------- stores ----------
async function renderStores() {
  const stores = S._stores = await api("/api/stores");
  const inv = await api("/api/inventory").catch(() => []);
  const lowBy = {};
  inv.forEach((i) => { if (i.low) lowBy[i.store_id] = (lowBy[i.store_id] || 0) + 1; });
  const q = (S.storeQ || "").toLowerCase();
  const shown = stores.filter((s) =>
    !q || (s.name + " " + s.city + " " + s.region).toLowerCase().includes(q));
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Stores</h2>
        <p class="dim">Every account, where it is, and what's low. Retail
          shops and distribution centres.</p></div>
      ${S.user && S.user.is_admin
        ? `<button class="btn" id="st-new">${opsIcon("store","btn-ic")} Add store</button>` : ""}
    </div>
    <div class="stats">
      <div class="stat"><div class="n">${stores.length}</div><div class="l">accounts</div></div>
      <div class="stat"><div class="n">${stores.filter((s) => s.kind === "distributor_dc").length}</div>
        <div class="l">distribution centres</div></div>
      <div class="stat"><div class="n">${Object.keys(lowBy).length}</div>
        <div class="l">stores with low stock</div></div>
    </div>
    ${panZoomMap({ id: "stores-map", pins: stores.map((s) => ({
      lat: s.lat, lng: s.lng, color: REGION_COLORS[s.region] || "#8b98a5",
      size: s.kind === "distributor_dc" ? 10 : 6,
      label: s.name, sub: s.city })) })}
    <div class="filters">
      <input id="st-q" placeholder="Filter stores" value="${esc(S.storeQ || "")}">
    </div>
    <div class="card"><table>
      <thead><tr><th>store</th><th>city</th><th>region</th><th>kind</th>
        <th class="num">low items</th><th>contact</th><th></th></tr></thead>
      <tbody>${shown.map((s) => `<tr>
        <td><b>${esc(s.name)}</b></td><td>${esc(s.city || "—")}</td>
        <td>${esc(s.region)}</td>
        <td>${s.kind === "distributor_dc" ? "DC" : "retail"}</td>
        <td class="num ${lowBy[s.id] ? "low" : ""}">${lowBy[s.id] || 0}</td>
        <td class="dim">${esc(s.contact || "—")}</td>
        <td>${rowActions("store", s)}</td></tr>`).join("")}
      </tbody></table></div>`;
  wireRows({ store: stores }, renderStores);
  let t;
  $("#st-q").oninput = (e) => { clearTimeout(t);
    t = setTimeout(() => { S.storeQ = e.target.value; renderStores(); }, 200); };
  if ($("#st-new")) $("#st-new").onclick = () => {
    modal(`<h3>Add store</h3>
      <label>Name</label><input id="ns-name">
      <div class="row2">
        <div><label>City</label><input id="ns-city"></div>
        <div><label>Region</label><select id="ns-region">
          ${S.meta.regions.map((r) => `<option>${r}</option>`).join("")}</select></div>
      </div>
      <div class="row2">
        <div><label>Latitude</label><input id="ns-lat" type="number" step="0.0001"></div>
        <div><label>Longitude</label><input id="ns-lng" type="number" step="0.0001"></div>
      </div>
      <label>Kind</label><select id="ns-kind">
        <option value="retail">Retail</option>
        <option value="distributor_dc">Distribution centre</option></select>
      <label>Contact</label><input id="ns-contact">
      <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="nls-save">Add</button></div>`);
    $("#nls-save").onclick = async () => {
      if (!$("#ns-name").value.trim()) return toast("a store needs a name");
      try {
        await api("/api/admin/stores", { body: {
          name: $("#ns-name").value.trim(), city: $("#ns-city").value.trim(),
          region: $("#ns-region").value, kind: $("#ns-kind").value,
          contact: $("#ns-contact").value.trim(),
          lat: +$("#ns-lat").value || null, lng: +$("#ns-lng").value || null } });
        closeModal(); S._stores = null; renderStores();
      } catch (e) { toast(e.message); }
    };
  };
}

// ---------- email campaigns ----------
async function renderEmail() {
  const d = await api("/api/store/admin/email/campaigns");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Email campaigns</h2>
        <p class="dim">Write once, send to an audience that stays accurate on
          its own. Orders are counted from the ledger via the campaign's
          discount code, not from an open-tracking pixel.</p></div>
      <button class="btn" id="em-new">${opsIcon("megaphone","btn-ic")} New campaign</button>
    </div>
    <div class="stats">
      ${Object.entries(d.audiences).map(([k, label]) => `
        <div class="stat"><div class="n">${d.sizes[k] ?? 0}</div>
          <div class="l">${esc(label)}</div></div>`).join("")}
      <div class="stat"><div class="n">${d.unsubscribed}</div>
        <div class="l">unsubscribed</div></div>
    </div>
    ${d.campaigns.map((c) => {
      const last = c.sends[0];
      return `<div class="card">
        <div class="doc-top">
          <div class="doc-main"><b>${esc(c.name)}</b>
            <span class="dim">${esc(c.subject)} · ${esc(c.audience_label)}${
              c.discount_code ? " · " + esc(c.discount_code) : ""}</span></div>
          <span class="pill ${c.status === "sent" ? "ok" : ""}">${c.status}</span>
          <button class="btn alt sm" data-emedit="${c.id}">Edit</button>
          <button class="btn alt sm" data-emsend="${c.id}">Send…</button>
        </div>
        ${c.sends.length ? `<div class="cp-stats" style="margin-top:10px">
          <span><b>${last.recipients}</b> recipients</span>
          <span><b>${last.delivered}</b> delivered</span>
          ${last.failed ? `<span class="low"><b>${last.failed}</b> failed</span>` : ""}
          <span><b>${c.orders}</b> orders</span>
          <span><b>${money(c.revenue_cents)}</b> revenue</span>
          <span class="dim">last sent ${fmtDate(last.started_at)}</span>
        </div>` : '<p class="dim" style="margin-top:8px">Never sent.</p>'}
      </div>`;
    }).join("") || `<div class="card empty"><span class="e-ic">${
      opsIcon("megaphone")}</span><b>No campaigns yet</b>
      <p class="dim">Write one, preview it, send a test to yourself, then
        send it for real.</p></div>`}`;
  $("#em-new").onclick = () => emailForm(null, d);
  view().querySelectorAll("[data-emedit]").forEach((b) => b.onclick = () =>
    emailForm(d.campaigns.find((c) => c.id === +b.dataset.emedit), d));
  view().querySelectorAll("[data-emsend]").forEach((b) => b.onclick = () =>
    emailSend(d.campaigns.find((c) => c.id === +b.dataset.emsend), d));
}

function emailForm(c, d) {
  modal(`<h3>${c ? "Edit campaign" : "New campaign"}</h3>
    <label>Name <span class="dim">(internal)</span></label>
    <input id="ec-name" value="${esc((c && c.name) || "")}">
    <div class="row2">
      <div><label>Audience</label><select id="ec-aud">
        ${Object.entries(d.audiences).map(([k, label]) =>
          `<option value="${k}" ${c && c.audience === k ? "selected" : ""}>
            ${esc(label)} (${d.sizes[k] ?? 0})</option>`).join("")}
      </select></div>
      <div><label>Discount code</label>
        <input id="ec-code" value="${esc((c && c.discount_code) || "")}"
          placeholder="optional"></div>
    </div>
    <label>Subject</label><input id="ec-subj" value="${esc((c && c.subject) || "")}">
    <label>Body</label>
    <textarea id="ec-body" rows="8">${esc((c && c.body) || "")}</textarea>
    <p class="dim" style="font-size:12px;margin-top:8px">Placeholders:
      <code>{name}</code> <code>{email}</code> <code>{code}</code>.
      An unsubscribe link is appended to every send automatically.</p>
    <div class="modal-acts">
      ${c ? '<button class="btn alt" id="ec-del" style="margin-right:auto">Delete</button>' : ""}
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="ec-save">Save</button>
    </div>`);
  $("#ec-save").onclick = async () => {
    const payload = { name: $("#ec-name").value, subject: $("#ec-subj").value,
      body: $("#ec-body").value, audience: $("#ec-aud").value,
      discount_code: $("#ec-code").value };
    try {
      if (c) await api(`/api/store/admin/email/campaigns/${c.id}`,
        { method: "PATCH", body: payload });
      else await api("/api/store/admin/email/campaigns", { body: payload });
      closeModal(); renderEmail();
    } catch (e) { toast(e.message); }
  };
  if (c && $("#ec-del")) $("#ec-del").onclick = async () => {
    if (!confirm(`Delete "${c.name}"?`)) return;
    await api(`/api/store/admin/email/campaigns/${c.id}`, { method: "DELETE" });
    closeModal(); renderEmail();
  };
}

async function emailSend(c) {
  const p = await api(`/api/store/admin/email/campaigns/${c.id}/preview`);
  modal(`<h3>Send "${esc(c.name)}"</h3>
    <p class="dim">Going to <b>${p.recipients}</b> people
      (${esc(c.audience_label)}). Unsubscribes are removed at send time.</p>
    <div class="card" style="background:var(--bg)">
      <div class="dim" style="font-size:11px">SUBJECT</div>
      <b>${esc(p.subject)}</b>
      <div class="dim" style="font-size:11px;margin-top:10px">BODY</div>
      <div style="white-space:pre-wrap;font-size:13px">${esc(p.body)}</div>
    </div>
    <label>Send a test first</label>
    <div class="row2">
      <input id="es-test" type="email" placeholder="you@example.com">
      <button class="btn alt" id="es-testgo">Send test</button>
    </div>
    <div class="modal-acts">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="esm-go">Send to ${p.recipients} people</button>
    </div>
    <p class="msg" id="esm-msg"></p>`);
  $("#es-testgo").onclick = async () => {
    try {
      await api(`/api/store/admin/email/campaigns/${c.id}/send`,
        { body: { test_to: $("#es-test").value.trim() } });
      $("#esm-msg").textContent = "Test sent.";
    } catch (e) { $("#esm-msg").textContent = e.message; }
  };
  $("#esm-go").onclick = async () => {
    if (!confirm(`Send to ${p.recipients} people? This can't be undone.`)) return;
    try {
      const out = await api(`/api/store/admin/email/campaigns/${c.id}/send`,
        { body: {} });
      closeModal();
      toast(`Sending to ${out.recipients} people…`);
      setTimeout(renderEmail, 2500);
    } catch (e) { $("#esm-msg").textContent = e.message; }
  };
}

// ---------- discord ----------
async function renderDiscord() {
  const d = await api("/api/store/admin/discord");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Discord</h2>
        <p class="dim">Let the business talk to the room the team already
          sits in — and answer from here. Webhooks push alerts out; connect a
          bot and you can read the channels and reply without leaving.</p></div>
      <button class="btn" id="dc-add">Add channel</button>
    </div>

    <div class="card dc-bot">
      <div class="doc-top">
        <div class="doc-main">
          <b>${d.bot ? esc(d.bot.guild_name || "Discord server") : "Read and reply"}</b>
          <span class="dim">${d.bot
            ? `connected as ${esc(d.bot.bot_name)} — channels below are live`
            : "connect a bot to read channels and reply from here"}</span>
        </div>
        <button class="btn ${d.bot ? "alt" : ""} sm" id="dc-bot">${
          d.bot ? "Disconnect" : "Connect a bot"}</button>
      </div>
    </div>
    ${d.bot ? '<div id="dc-chat"></div>' : ""}

    <h3>Alert channels</h3>
    ${d.channels.map((c) => `<div class="card">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(c.label)}</b>
          <span class="dim">webhook stored · added ${fmtDate(c.created_at)}</span></div>
        <span class="pill ${c.active ? "ok" : ""}">${c.active ? "active" : "off"}</span>
        <button class="btn alt sm" data-dctest="${c.id}">Send test</button>
        <button class="btn alt sm" data-dcdel="${c.id}">Remove</button>
      </div></div>`).join("") || `<div class="card empty"><span class="e-ic">${
        opsIcon("chat")}</span><b>No channels yet</b>
        <p class="dim">In Discord: Server settings → Integrations → Webhooks →
          New webhook, then paste the URL here.</p></div>`}

    ${d.channels.length ? `
      <div class="page-head" style="margin-top:22px">
        <div><h3 style="margin:0">Rules</h3></div>
        <button class="btn" id="dc-rule">Add rule</button>
      </div>
      ${d.rules.map((r) => `<div class="card">
        <div class="doc-top">
          <div class="doc-main">
            <b>${esc(d.events[r.event] || r.event)} → ${esc(r.channel_label)}</b>
            <span class="dim">${r.condition_field
              ? `only when ${esc(r.condition_field)} ${esc(r.condition_op)} ${esc(r.condition_value)}`
              : "every time"} · fired ${r.fired}×${
              r.last_fired ? " · last " + fmtDate(r.last_fired) : ""}</span>
          </div>
          <label class="perm" style="border:none;padding:0">
            <input type="checkbox" data-dcon="${r.id}" ${r.active ? "checked" : ""}>
            <span><b>on</b></span></label>
          <button class="btn alt sm" data-dcruledel="${r.id}">Remove</button>
        </div></div>`).join("") || '<p class="dim">No rules yet.</p>'}` : ""}

    ${d.log.length ? `<h3>Recent deliveries</h3>
      <div class="card"><table>
        <thead><tr><th>when</th><th>event</th><th>result</th></tr></thead>
        <tbody>${d.log.map((l) => `<tr>
          <td class="dim">${fmtDate(l.created_at)}</td>
          <td>${esc(l.event)}</td>
          <td>${l.ok ? '<span class="pill ok">sent</span>'
            : `<span class="pill bad">failed</span> <span class="dim">${esc(l.detail)}</span>`}</td>
        </tr>`).join("")}</tbody></table></div>` : ""}`;

  $("#dc-add").onclick = () => {
    modal(`<h3>Add a Discord channel</h3>
      <p class="dim">In Discord: <b>Server settings → Integrations → Webhooks
        → New webhook</b>. Pick the channel, copy the URL, paste it here.</p>
      <label>Label</label><input id="dc-label" placeholder="#orders">
      <label>Webhook URL</label>
      <input id="dc-url" placeholder="https://discord.com/api/webhooks/...">
      <p class="dim" style="font-size:12px;margin-top:8px">Anyone with this URL
        can post to the channel, so it's stored as a secret and never shown
        again after saving.</p>
      <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="dc-save">Add</button></div>`);
    $("#dc-save").onclick = async () => {
      try {
        await api("/api/store/admin/discord/channels", { body: {
          label: $("#dc-label").value, webhook: $("#dc-url").value } });
        closeModal(); renderDiscord();
      } catch (e) { toast(e.message); }
    };
  };
  if ($("#dc-rule")) $("#dc-rule").onclick = () => {
    modal(`<h3>Add a rule</h3>
      <div class="row2">
        <div><label>When this happens</label><select id="dr-event">
          ${Object.entries(d.events).map(([k, v]) =>
            `<option value="${k}">${esc(v)}</option>`).join("")}</select></div>
        <div><label>Post to</label><select id="dr-chan">
          ${d.channels.map((c) => `<option value="${c.id}">${esc(c.label)}</option>`).join("")}
        </select></div>
      </div>
      <label>Only when <span class="dim">(optional)</span></label>
      <div class="row2">
        <input id="dr-field" placeholder="field, e.g. total_cents">
        <select id="dr-op"><option value="">—</option>
          ${d.ops.map((o) => `<option>${o}</option>`).join("")}</select>
        <input id="dr-val" placeholder="value">
      </div>
      <label>Message <span class="dim">(blank uses the default)</span></label>
      <input id="dr-tpl" placeholder="">
      <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
        <button class="btn" id="dr-save">Add rule</button></div>`);
    $("#dr-event").onchange = () => {
      $("#dr-tpl").placeholder = d.defaults[$("#dr-event").value] || "";
    };
    $("#dr-event").onchange();
    $("#dr-save").onclick = async () => {
      try {
        await api("/api/store/admin/discord/rules", { body: {
          channel_id: +$("#dr-chan").value, event: $("#dr-event").value,
          condition_field: $("#dr-field").value,
          condition_op: $("#dr-op").value,
          condition_value: $("#dr-val").value,
          template: $("#dr-tpl").value } });
        closeModal(); renderDiscord();
      } catch (e) { toast(e.message); }
    };
  };
  view().querySelectorAll("[data-dctest]").forEach((b) => b.onclick = async () => {
    try { await api(`/api/store/admin/discord/channels/${b.dataset.dctest}/test`,
      { method: "POST" }); toast("Test posted to Discord"); renderDiscord(); }
    catch (e) { toast(e.message); }
  });
  view().querySelectorAll("[data-dcdel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Remove this channel and its rules?")) return;
    await api(`/api/store/admin/discord/channels/${b.dataset.dcdel}`,
      { method: "DELETE" }); renderDiscord();
  });
  view().querySelectorAll("[data-dcruledel]").forEach((b) => b.onclick = async () => {
    await api(`/api/store/admin/discord/rules/${b.dataset.dcruledel}`,
      { method: "DELETE" }); renderDiscord();
  });
  view().querySelectorAll("[data-dcon]").forEach((c) => c.onchange = async () => {
    await api(`/api/store/admin/discord/rules/${c.dataset.dcon}`,
      { method: "PATCH", body: { active: c.checked } }); renderDiscord();
  });

  $("#dc-bot").onclick = () => d.bot ? disconnectBot() : connectBotModal();
  if (d.bot) drawDiscordChat();
}

function connectBotModal() {
  modal(`<h3>Connect a Discord bot</h3>
    <p class="dim">A webhook can only push messages out. Reading a channel or
      replying in it needs a bot, so this step is separate — skip it and the
      alerts still work.</p>
    <ol class="dim" style="font-size:13px;padding-left:18px;line-height:1.7">
      <li>At <b>discord.com/developers/applications</b>, make an application
        and add a bot.</li>
      <li>Under <b>Bot</b>, reset and copy the token.</li>
      <li>Invite it to your server with <b>View Channels</b>,
        <b>Read Message History</b> and <b>Send Messages</b>.</li>
      <li>Right-click the server name → <b>Copy Server ID</b>.</li>
    </ol>
    <label>Bot token</label><input id="dc-token" type="password"
      placeholder="paste the token">
    <label>Server ID</label><input id="dc-guild" placeholder="e.g. 913…">
    <p class="dim" style="font-size:12px;margin-top:8px">The token can post as
      the bot anywhere it's a member, so it's stored as a secret and never
      shown again.</p>
    <div class="modal-acts"><button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="dc-bot-save">Connect</button></div>`);
  $("#dc-bot-save").onclick = async () => {
    const b = $("#dc-bot-save");
    b.disabled = true; b.setAttribute("aria-busy", "true");
    b.textContent = "checking…";
    try {
      const r = await api("/api/store/admin/discord/bot", { body: {
        token: $("#dc-token").value, guild_id: $("#dc-guild").value } });
      closeModal();
      toast(`Connected as ${r.bot_name} in ${r.guild_name}`);
      renderDiscord();
    } catch (e) {
      toast(e.message); b.disabled = false; b.textContent = "Connect";
    }
  };
}

async function disconnectBot() {
  if (!confirm("Disconnect the bot? Alert webhooks keep working.")) return;
  await api("/api/store/admin/discord/bot", { method: "DELETE" });
  renderDiscord();
}

/* The channel reader. Kept deliberately plain: this is for seeing what the
   room is saying and answering it, not for reimplementing Discord. */
async function drawDiscordChat() {
  const box = $("#dc-chat");
  if (!box) return;
  let list;
  try {
    list = await api("/api/store/admin/discord/chat/channels");
  } catch (e) {
    box.innerHTML = `<div class="card"><p class="dim">${esc(e.message)}</p></div>`;
    return;
  }
  if (!list.channels.length) {
    box.innerHTML = `<div class="card"><p class="dim">The bot can't see any
      text channels — give it <b>View Channel</b> on the ones you want
      here.</p></div>`;
    return;
  }
  if (!S.dcChan || !list.channels.some((c) => c.id === S.dcChan)) {
    S.dcChan = list.channels[0].id;
  }
  box.innerHTML = `
    <div class="dc-wrap">
      <div class="dc-list">${list.channels.map((c) => `
        <button class="dc-c ${c.id === S.dcChan ? "on" : ""}" data-dcc="${c.id}">
          <b>#${esc(c.name)}</b>${c.topic
            ? `<span class="dim">${esc(c.topic)}</span>` : ""}</button>`).join("")}
      </div>
      <div class="dc-room">
        <div class="dc-msgs" id="dc-msgs"><p class="dim">Loading…</p></div>
        <form class="dc-say" id="dc-say">
          <input id="dc-text" placeholder="Message #${esc(
            (list.channels.find((c) => c.id === S.dcChan) || {}).name || "")}"
            autocomplete="off">
          <button class="btn">Send</button>
        </form>
      </div>
    </div>`;
  box.querySelectorAll("[data-dcc]").forEach((b) => b.onclick = () => {
    S.dcChan = b.dataset.dcc; drawDiscordChat();
  });
  $("#dc-say").onsubmit = async (e) => {
    e.preventDefault();
    const input = $("#dc-text");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    try {
      await api(`/api/store/admin/discord/chat/${S.dcChan}/messages`,
                { body: { content: text } });
      loadDiscordMsgs();
    } catch (err) { toast(err.message); input.value = text; }
  };
  loadDiscordMsgs();
  // Poll while the tab is open. Cleared on any tab change by render().
  clearInterval(S._dcTimer);
  S._dcTimer = setInterval(() => {
    if (S.tab === "discord" && $("#dc-msgs")) loadDiscordMsgs();
    else clearInterval(S._dcTimer);
  }, 15000);
}

async function loadDiscordMsgs() {
  const el = $("#dc-msgs");
  if (!el) return;
  try {
    const d = await api(
      `/api/store/admin/discord/chat/${S.dcChan}/messages`);
    // Only redraw when something changed, so a poll doesn't yank the
    // scroll position out from under someone reading.
    const sig = d.messages.map((m) => m.id).join(",");
    if (sig === el.dataset.sig) return;
    el.dataset.sig = sig;
    el.innerHTML = d.messages.map((m) => `
      <div class="dc-m${m.bot ? " bot" : ""}">
        <div class="dc-who">${esc(m.author)}${m.bot
          ? '<span class="pill">bot</span>' : ""}
          <span class="dim">${fmtDate(Date.parse(m.at) / 1000)}</span></div>
        <div class="dc-body">${esc(m.content) || '<i class="dim">—</i>'}${
          m.attachments.map((a) =>
            `<span class="pill">${esc(a)}</span>`).join("")}</div>
      </div>`).join("") || '<p class="dim">Nothing here yet.</p>';
    el.scrollTop = el.scrollHeight;
  } catch (e) {
    el.innerHTML = `<p class="dim">${esc(e.message)}</p>`;
  }
}


/* ---------- what you pay for ----------
   Somebody refused a fourth till is standing at a counter with a queue in
   front of them. Making them ring their supplier to say yes to a
   published price is not caution, it is a business held up by its
   software — so within a ceiling they say yes here, and above it the ask
   goes to a person instead of being refused. */
const LIMIT_WORDS = {
  registers: ["Tills", "open at the same time"],
  kiosks: ["Clock kiosks", "tablets people punch in on"],
  locations: ["Locations", "shops, depots, kitchens"],
  seats: ["Staff seats", "people who sign in to run the business"],
};

async function renderPlan() {
  const d = await api("/api/entitlements");
  const money2 = (c) => money(c);
  view().innerHTML = `
    <div class="page-head">
      <div><h2>What you pay for</h2>
        <p class="dim">${d.tenant
          ? "What your plan covers, what you are using, and what another "
            + "one costs. Anything inside your own ceiling takes effect "
            + "the moment you set it."
          : "This install is not on a metered plan — nothing here is "
            + "counted or capped."}</p></div>
    </div>
    <div class="sig-rows">${d.lines.map((l) => {
      const w = LIMIT_WORDS[l.kind] || [l.kind, ""];
      const tight = l.room === 0;
      return `<div class="doc-line planline${
        l.over ? " dl-awaiting" : tight ? " dl-signed" : ""}">
        <span class="dl-title"><b>${w[0]}</b>
          <span class="dim">${w[1]}</span></span>
        <span class="plan-use ${tight ? "low" : ""}">
          <b>${l.used}</b> of ${l.allowed}</span>
        <span class="dim plan-each">${l.each_cents
          ? money2(l.each_cents) + " each beyond " + l.included : "included"}
        </span>
        <span class="dl-acts planline-acts">${d.tenant
          ? `<button class="btn alt sm" data-plan="${l.kind}"
               data-now="${l.allowed}" data-max="${l.self_serve_max}"
               data-each="${l.each_cents}">Change</button>` : ""}</span>
      </div>`;
    }).join("")}</div>
    ${d.overage_cents ? `<div class="card alert">
      <b>${money2(d.overage_cents)} a month over what you are covered
        for</b>
      <span class="dim">More is in use than the plan allows. Nothing has
        been switched off — raise the number and it stops being an
        overage, or stop using them and it stops being a bill.</span>
    </div>` : ""}
    <p class="dim">${esc(d.note)}</p>`;
  view().querySelectorAll("[data-plan]").forEach((b) =>
    b.onclick = () => planChange(b.dataset.plan, +b.dataset.now,
                                +b.dataset.max, +b.dataset.each));
}

function planChange(kind, now, ceiling, each) {
  const w = LIMIT_WORDS[kind] || [kind, ""];
  modal(`<h3>${w[0]}</h3>
    <p class="dim">You have ${now}. ${each
      ? `Each one beyond what the plan includes is ${money(each)} a month.`
      : ""} You can set up to ${ceiling} yourself; past that it goes to
      your account manager rather than being refused.</p>
    <label>How many</label>
    <input id="pl-n" type="number" min="0" value="${now}">
    <label>Why <span class="opt">only needed above ${ceiling}</span></label>
    <input id="pl-why" placeholder="opening a second site">
    <p class="dim" id="pl-cost"></p>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="pl-go">Set it</button></div>`);
  const cost = () => {
    const n = +$("#pl-n").value || 0;
    $("#pl-cost").textContent = n > ceiling
      ? `Above ${ceiling} — this becomes a request, not a change.`
      : n === now ? ""
        : n > now
          ? `${n - now} more · about ${money((n - now) * each)} a month more.`
          : `${now - n} fewer · about ${money((now - n) * each)} a month less.`;
  };
  $("#pl-n").oninput = cost;
  cost();
  $("#pl-go").onclick = async () => {
    try {
      const r = await api("/api/entitlements/raise", { body: {
        kind, to: +$("#pl-n").value || 0, why: $("#pl-why").value.trim() } });
      closeModal();
      toast(r.asked
        ? "Asked — your account manager has it"
        : r.to > now
          ? `Done — ${r.to} now, ${money(r.monthly_cents)} a month`
          : `Done — ${r.to} now`);
      renderPlan();
    } catch (e) { toast(e.message); }
  };
}
