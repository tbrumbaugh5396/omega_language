// ---------- integrations ----------
/* One screen for all of them, drawn from what the server says each provider
   needs. Seven hand-written panels would drift the moment an eighth arrived;
   this way a new integration appears here the day it's added to the
   registry, with the right form and the right explanation. */

/* A connection this business declares for itself: a name, a URL, how the
   key is carried, and which events go down it. No provider-specific
   cleverness — we have not read their documentation, and pretending
   otherwise is how an integration lies about what it sent. */
function customIntegrationForm(cur, labels, seed) {
  const on = new Set((cur && cur.events)
    || (seed && seed.events) || []);
  modal(`<h3>${cur ? "Edit " + esc(cur.label)
    : seed ? esc(seed.label) : "A connection of your own"}</h3>
    ${seed ? `<p class="dim">${esc(seed.hint)}</p>` : ""}
    <label>Name <span class="req">required</span></label>
    <input id="ic-label" value="${esc((cur && cur.label)
      || (seed && seed.label) || "")}">
    <label>What it is for</label>
    <input id="ic-blurb" value="${esc((cur && cur.blurb)
      || (seed && seed.blurb) || "")}">
    <label>URL <span class="opt">https only — a key sent over plain http is
      a key you have given away</span></label>
    <input id="ic-url" placeholder="https://…" value="${esc((cur && cur.url)
      || "")}">
    <div class="row2">
      <div><label>How the key travels</label>
        <select id="ic-auth">
          ${["bearer", "header", "query", "none"].map((k) =>
            `<option value="${k}" ${cur && cur.auth === k ? "selected" : ""}>${
              { bearer: "Authorization: Bearer …",
                header: "a header of their choosing",
                query: "a query parameter",
                none: "no key at all" }[k]}</option>`).join("")}</select></div>
      <div><label>Header or parameter name</label>
        <input id="ic-authname" placeholder="X-API-Key"></div>
    </div>
    <label>Key <span class="opt">${cur && cur.connected
      ? "stored — leave blank to keep it" : "stored, never shown again"}</span>
    </label>
    <input id="ic-secret" type="password" autocomplete="off">
    <label>Send it these</label>
    <div class="cap-grid">
      ${Object.entries(labels || {}).map(([k, label]) => `
        <label class="perm"><input type="checkbox" data-icev value="${esc(k)}"
          ${on.has(k) ? "checked" : ""}>
          <span><b>${esc(k)}</b><small>${esc(label)}</small></span></label>`)
        .join("")}
    </div>
    <div class="modal-foot">
      <button class="btn alt" data-close>Cancel</button>
      <button class="btn" id="ic-save">Save</button>
    </div>`);
  $("#ic-save").onclick = async () => {
    const body = {
      slug: cur ? cur.name.slice(7) : (seed ? seed.slug : ""),
      label: $("#ic-label").value.trim(),
      blurb: $("#ic-blurb").value.trim(),
      url: $("#ic-url").value.trim(),
      auth_kind: $("#ic-auth").value,
      auth_name: $("#ic-authname").value.trim(),
      secret: $("#ic-secret").value,
      events: [...document.querySelectorAll("[data-icev]:checked")]
        .map((b) => b.value),
    };
    if (!body.label) return toast("a connection needs a name");
    try {
      await api("/api/admin/integrations/custom", { body });
      closeModal(); renderIntegrations();
    } catch (err) { toast(err.message); }
  };
}

async function renderIntegrations() {
  const d = await api("/api/admin/integrations");
  const keys = await api("/api/admin/api-keys").catch(() => null);

  const card = (p) => {
    const status = p.connected
      ? `<span class="pill ok">connected${p.account
          ? " · " + esc(p.account) : ""}</span>`
      : p.auth === "inbound"
        ? (p.inbound_ready
            ? `<span class="pill ok">ready · ${p.received} received</span>`
            : '<span class="pill">not set up</span>')
        : '<span class="pill">not connected</span>';
    return `<div class="card intg" data-p="${p.name}">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(p.label)}</b>
          <span class="dim">${esc(p.blurb)}</span></div>
        ${status}
        ${p.connected && p.syncs ? `
          <span class="pill ${p.live ? "ok" : ""}">${p.live
            ? "live" : "on demand"}</span>
          <button class="btn alt sm" data-iglive="${p.name}">${p.live
            ? "Stop live updates" : "Go live"}</button>
          <button class="btn alt sm" data-igsync="${p.name}"
            >Sync now</button>` : ""}
        ${p.connected ? `<button class="btn alt sm" data-igtest="${p.name}"
          >Test</button>` : ""}
        ${p.connected || p.inbound_ready
          ? `<button class="btn alt sm" data-igoff="${p.name}">${
              p.auth === "inbound" ? "New key" : "Disconnect"}</button>` : ""}
      </div>
      <p class="dim intg-does">${esc(p.does)}</p>
      ${p.events.length ? `<p class="dim intg-when">Fires when
        ${p.events.map(esc).join(", ")}.</p>` : ""}
      ${p.connected ? "" : `<div class="intg-form" id="f-${p.name}"></div>`}
      ${p.name === "slack" && p.connected
        ? '<div class="intg-chat" id="slack-chat"></div>' : ""}
      ${p.name === "canva" && p.connected
        ? `<button class="btn alt sm" id="canva-list">List my designs</button>
           <div id="canva-out"></div>` : ""}
      ${p.name === "laceup"
        ? `<div class="intg-form" id="f-laceup-extra"></div>` : ""}
    </div>`;
  };

  view().innerHTML = `
    <div class="page-head">
      <div><h2>Integrations</h2>
        <p class="dim">Each of these is connected once and then works on its
          own. Credentials are stored and never shown again — the screen can
          tell you what a connection reached, but not what it is.</p></div>
    </div>
    ${keys ? `<div class="page-head" style="margin-top:4px">
      <h3>API keys</h3>
      <button class="btn sm" id="ak-new">Mint a key</button>
    </div>
    <div class="card">
      <p class="dim">The machine door: a key acts AS the account it is
        bound to, through every permission the app already enforces. The
        secret shows ONCE at minting; a read key is refused mutations at
        the front door; revocation is immediate. The interactive API
        reference lives at <a href="/docs" target="_blank">/docs</a>.</p>
      ${keys.length ? `<div class="tablewrap"><table>
        <thead><tr><th>name</th><th>key</th><th>scope</th><th>acts as</th>
          <th>last used</th><th></th></tr></thead>
        <tbody>${keys.map((k) => `<tr class="${k.revoked_at ? "dim" : ""}">
          <td>${esc(k.name)}</td>
          <td class="dim">${esc(k.prefix)}…</td>
          <td>${esc(k.scope)}</td>
          <td>${esc(k.acts_as)}</td>
          <td class="dim">${k.revoked_at ? "revoked"
            : k.last_used_at ? fmtDate(k.last_used_at) : "never"}</td>
          <td>${k.revoked_at ? "" : `<button class="btn alt sm"
            data-akrev="${k.id}">Revoke</button>`}</td>
        </tr>`).join("")}</tbody></table></div>`
      : '<p class="dim">No keys yet — mint one and hand your scripts a door of their own.</p>'}
    </div>` : ""}
    ${d.providers.map(card).join("")}

    <div class="page-head" style="margin-top:18px">
      <div><h3>Your own connections</h3>
        <p class="dim">Eight services are here because somebody read eight
          sets of documentation. A business runs on more than eight — a
          broker's portal, a trends service, somebody's internal tool — and
          they all have a URL and a key. Declare one and it joins the same
          event list and the same log.</p></div>
      <button class="btn sm" id="ig-custom-new">Add a connection</button>
    </div>
    ${(d.suggestions || []).length ? `<div class="card">
      <b>Ready to fill in</b>
      <p class="dim">We have not read their documentation, so these are
        the ordinary connection with the name and the events already
        chosen — paste the URL from your own account.</p>
      <div class="chips">${d.suggestions.map((sg) =>
        `<button class="btn alt sm" data-igsuggest="${esc(sg.slug)}">${
          esc(sg.label)}</button>`).join("")}</div>
    </div>` : ""}
    ${(d.custom || []).map((p) => `<div class="card intg">
      <div class="doc-top">
        <div class="doc-main"><b>${esc(p.label)}</b>
          <span class="dim">${esc(p.blurb)}</span></div>
        <span class="pill ${p.connected ? "ok" : ""}">${p.connected
          ? "connected" : "no key"}</span>
        <button class="btn alt sm" data-igctest="${esc(p.name.slice(7))}"
          >Send a test</button>
        <button class="btn alt sm" data-igcedit="${esc(p.name.slice(7))}"
          >Edit</button>
        <button class="btn alt sm" data-igcdel="${esc(p.name.slice(7))}"
          >Remove</button>
      </div>
      <p class="dim intg-does">${esc(p.url || "no URL yet")}</p>
      ${p.events.length ? `<p class="dim intg-when">Fires when
        ${p.events.map(esc).join(", ")}.</p>` : ""}
    </div>`).join("")}
    ${d.log.length ? `<h3>Recent activity</h3>
      <div class="card"><div class="tablewrap"><table>
        <thead><tr><th>when</th><th>which</th><th>event</th><th>result</th>
          </tr></thead>
        <tbody>${d.log.map((l) => `<tr>
          <td class="dim">${fmtDate(l.created_at)}</td>
          <td>${esc(l.provider)}</td><td class="dim">${esc(l.event)}</td>
          <td>${l.ok ? '<span class="pill ok">ok</span>'
            : `<span class="pill bad">failed</span>
               <span class="dim">${esc(l.detail)}</span>`}</td>
        </tr>`).join("")}</tbody></table></div></div>` : ""}`;

  d.providers.forEach((p) => drawForm(p, () => renderIntegrations()));
  if ($("#slack-chat")) drawSlackChat();

  if ($("#ak-new")) $("#ak-new").onclick = async () => {
    const users = await api("/api/admin/users").catch(() => []);
    modal(`<h3>Mint an API key</h3>
      <label>Name <span class="dim">(what will use it)</span></label>
      <input id="ak-name" placeholder="warehouse sync">
      <div class="row2">
        <div><label>Scope</label><select id="ak-scope">
          <option value="read">read — GETs only, mutations refused</option>
          <option value="write">write — everything its account may do</option>
        </select></div>
        <div><label>Acts as</label><select id="ak-user">
          ${users.filter((u) => u.active).map((u) =>
            `<option value="${u.id}" ${u.id === S.user.id ? "selected" : ""}>
              ${esc(u.name)} (${esc(u.role)}${u.is_admin ? " · admin" : ""})
            </option>`).join("")}</select></div>
      </div>
      <p class="dim">Bind narrow: a key that acts as a plain account can
        only ever do what that account could.</p>
      <p><button class="btn sm" id="ak-go">Mint</button></p>
      <p id="ak-out"></p>`);
    $("#ak-go").onclick = async () => {
      try {
        const out = await api("/api/admin/api-keys", { body: {
          name: $("#ak-name").value.trim(), scope: $("#ak-scope").value,
          user_id: +$("#ak-user").value } });
        document.getElementById("ak-out").innerHTML =
          `<input id="ak-secret" value="${esc(out.secret)}" readonly
             style="width:100%;font-family:monospace">
           <span class="dim">This is the ONLY time the secret shows —
             copy it now. Use it as
             <code>Authorization: Bearer ${esc(out.prefix)}…</code></span>`;
        const box = document.getElementById("ak-secret");
        box.onfocus = () => box.select();
        box.focus();
      } catch (err) { toast(err.message); }
    };
  };
  view().querySelectorAll("[data-akrev]").forEach((b) => b.onclick =
    async () => {
      await api(`/api/admin/api-keys/${b.dataset.akrev}/revoke`,
                { method: "POST", body: {} });
      toast("revoked — it stopped working the moment you clicked");
      renderIntegrations();
    });

  view().querySelectorAll("[data-iglive]").forEach((b) => b.onclick = async () => {
    const name = b.dataset.iglive;
    const on = d.providers.find((x) => x.name === name).live;
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      if (on) {
        await api(`/api/admin/integrations/${name}/webhook`,
                  { method: "DELETE" });
        toast("Live updates off — sync by hand from here");
      } else {
        await api(`/api/admin/integrations/${name}/webhook`,
                  { method: "POST" });
        toast("Live — changes over there now arrive as they happen");
      }
      renderIntegrations();
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  });
  view().querySelectorAll("[data-igsync]").forEach((b) => b.onclick = async () => {
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      const r = await api(`/api/admin/integrations/${b.dataset.igsync}/sync`,
                          { method: "POST" });
      toast(r.changed.length
        ? `${r.changed.length} of ${r.checked} moved on over there — `
          + r.changed.map((x) => `${x.kind} #${x.id} ${x.applied}`).join(", ")
        : `${r.checked} checked, nothing has changed`);
      renderIntegrations();
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  });
  if ($("#ig-custom-new"))
    $("#ig-custom-new").onclick = () =>
      customIntegrationForm(null, d.event_labels, null);
  view().querySelectorAll("[data-igsuggest]").forEach((b) => b.onclick = () =>
    customIntegrationForm(null, d.event_labels,
      (d.suggestions || []).find((x) => x.slug === b.dataset.igsuggest)));
  view().querySelectorAll("[data-igcedit]").forEach((b) => b.onclick = () =>
    customIntegrationForm(
      (d.custom || []).find((x) => x.name === "custom:" + b.dataset.igcedit),
      d.event_labels, null));
  view().querySelectorAll("[data-igctest]").forEach((b) => b.onclick =
    async () => {
      try {
        await api(`/api/admin/integrations/custom/${b.dataset.igctest}/test`,
                  { body: {} });
        toast("it took the test event");
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-igcdel]").forEach((b) => b.onclick =
    async () => {
      if (!confirm("Remove this connection?\n\nIts key goes with it; the "
        + "log of what it carried stays.")) return;
      try {
        await api(`/api/admin/integrations/custom/${b.dataset.igcdel}`,
                  { method: "DELETE" });
        renderIntegrations();
      } catch (err) { toast(err.message); }
    });
  view().querySelectorAll("[data-igtest]").forEach((b) => b.onclick = async () => {
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      const r = await api(`/api/admin/integrations/${b.dataset.igtest}/test`,
                          { method: "POST" });
      toast(`Still working — ${r.detail}`);
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  });
  view().querySelectorAll("[data-igoff]").forEach((b) => b.onclick = async () => {
    const name = b.dataset.igoff;
    const p = d.providers.find((x) => x.name === name);
    if (p.auth === "inbound") {
      if (!confirm("Issue a new key? Whatever is using the old one stops "
        + "working until it's updated.")) return;
      const r = await api(
        `/api/admin/integrations/${name}/inbound-key?rotate=1`,
        { method: "POST" });
      toast("New key issued");
      renderIntegrations();
      return;
    }
    if (!confirm(`Disconnect ${p.label}?`)) return;
    await api(`/api/admin/integrations/${name}`, { method: "DELETE" });
    renderIntegrations();
  });

  if ($("#canva-list")) $("#canva-list").onclick = async () => {
    try {
      const r = await api("/api/admin/integrations/canva/designs");
      const items = r.items || r.designs || [];
      $("#canva-out").innerHTML = items.length
        ? `<table style="margin-top:8px">${items.slice(0, 20).map((x) =>
            `<tr><td>${esc(x.title || x.id)}</td>
             <td class="dim">${esc(x.id || "")}</td></tr>`).join("")}</table>`
        : '<p class="dim">No designs came back.</p>';
    } catch (e) { toast(e.message); }
  };
}

/* Slack its own screen, beside Discord, because that is where you look for
   a conversation — not inside a settings page. The integrations screen still
   holds the connection; this holds the talking. */
async function renderSlack() {
  const st = await api("/api/admin/integrations");
  const p = st.providers.find((x) => x.name === "slack");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Slack</h2>
        <p class="dim">${p.connected
          ? "Alerts go out on their own. Read the channels and answer here."
          : "Not connected yet."}</p></div>
      <button class="btn alt" id="sl-setup">${p.connected
        ? "Connection settings" : "Connect Slack"}</button>
    </div>
    ${p.connected ? '<div id="slack-chat"></div>' : `
      <div class="card empty"><span class="e-ic">${opsIcon("megaphone")}</span>
        <b>Slack isn't connected</b>
        <p class="dim">Add an incoming webhook and the business starts
          posting to your channel. Add a bot token as well and you can read
          the channels and reply from here.</p>
        <button class="btn" id="sl-go">Set it up</button></div>`}`;
  const toSettings = () => { S.tab = "integrations"; render(); };
  $("#sl-setup").onclick = toSettings;
  if ($("#sl-go")) $("#sl-go").onclick = toSettings;
  if (p.connected) {
    drawSlackChat();
    // Without a bot token the reader explains itself; say it here too, so
    // the empty panel isn't a mystery.
    setTimeout(() => {
      const box = $("#slack-chat");
      if (box && !box.innerHTML.trim()) {
        box.innerHTML = '<p class="dim">Add a bot token under Integrations '
          + "to read and reply here.</p>";
      }
    }, 1200);
  }
}

/* Reading and answering Slack from here. Same shape as the Discord reader,
   deliberately: two chat surfaces that behave differently are two things to
   learn for no reason. */
async function drawSlackChat() {
  const box = $("#slack-chat");
  if (!box) return;
  let list;
  try {
    list = await api("/api/admin/integrations/slack/channels");
  } catch (e) {
    box.innerHTML = `<p class="dim">${esc(e.message)}</p>`;
    return;
  }
  if (list.error) {
    box.innerHTML = `<p class="dim">${esc(list.error)}</p>`;
    return;
  }
  if (!list.channels.length) {
    box.innerHTML = '<p class="dim">No channels came back — check the '
      + "app has channels:read.</p>";
    return;
  }
  const readable = list.channels.filter((c) => c.member);
  if (!S.slackChan || !list.channels.some((c) => c.id === S.slackChan)) {
    S.slackChan = (readable[0] || list.channels[0]).id;
  }
  box.innerHTML = `
    <div class="dc-wrap">
      <div class="dc-list">${list.channels.map((c) => `
        <button class="dc-c ${c.id === S.slackChan ? "on" : ""}"
          data-slc="${c.id}"><b>#${esc(c.name)}</b>
          ${c.member ? (c.topic ? `<span class="dim">${esc(c.topic)}</span>`
            : "") : '<span class="dim">not joined</span>'}</button>`).join("")}
      </div>
      <div class="dc-room">
        <div class="dc-msgs" id="slack-msgs"><p class="dim">Loading…</p></div>
        <form class="dc-say" id="slack-say">
          <input id="slack-text" autocomplete="off"
            placeholder="Message #${esc((list.channels.find(
              (c) => c.id === S.slackChan) || {}).name || "")}">
          <button class="btn">Send</button>
        </form>
      </div>
    </div>`;
  box.querySelectorAll("[data-slc]").forEach((b) => b.onclick = () => {
    S.slackChan = b.dataset.slc; drawSlackChat();
  });
  $("#slack-say").onsubmit = async (e) => {
    e.preventDefault();
    const input = $("#slack-text");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    try {
      await api(`/api/admin/integrations/slack/${S.slackChan}/messages`,
                { body: { text } });
      loadSlackMsgs();
    } catch (err) { toast(err.message); input.value = text; }
  };
  loadSlackMsgs();
  clearInterval(S._slackTimer);
  S._slackTimer = setInterval(() => {
    if ((S.tab === "slack" || S.tab === "integrations") && $("#slack-msgs")) {
      loadSlackMsgs();
    }
    else clearInterval(S._slackTimer);
  }, 20000);
}

async function loadSlackMsgs() {
  const el = $("#slack-msgs");
  if (!el) return;
  try {
    const d = await api(
      `/api/admin/integrations/slack/${S.slackChan}/messages`);
    if (d.error) {
      el.innerHTML = `<p class="dim">${esc(d.error)}</p>`;
      return;
    }
    // Only redraw on change, so a poll doesn't yank the scroll position out
    // from under someone reading.
    const sig = d.messages.map((m) => m.id).join(",");
    if (sig === el.dataset.sig) return;
    el.dataset.sig = sig;
    el.innerHTML = d.messages.map((m) => `
      <div class="dc-m${m.bot ? " bot" : ""}">
        <div class="dc-who">${esc(m.author)}${m.bot
          ? '<span class="pill">bot</span>' : ""}
          <span class="dim">${fmtDate(m.at)}</span></div>
        <div class="dc-body">${esc(m.content) || '<i class="dim">—</i>'}</div>
      </div>`).join("") || '<p class="dim">Nothing here yet.</p>';
    el.scrollTop = el.scrollHeight;
  } catch (e) {
    el.innerHTML = `<p class="dim">${esc(e.message)}</p>`;
  }
}

/* The connect form for one provider, from its declared fields. */
function drawForm(p, refresh) {
  const box = $(`#f-${p.name}`);

  if (p.name === "laceup") {
    const extra = $("#f-laceup-extra");
    if (extra) {
      extra.innerHTML = `
        <p class="dim">LaceUp publishes no API to call, so this goes the
          other way: it posts orders to an address of ours, or you drop in a
          file. Lines are matched to products by SKU — the code printed on
          the case, not our internal ids.</p>
        <button class="btn alt sm" id="lu-key">${p.inbound_ready
          ? "Show the endpoint" : "Set up the endpoint"}</button>
        <label class="f" style="margin-top:10px">Or import an order CSV
          <span class="dim">columns: reference, customer, email, city, sku,
            qty — one row per line</span>
          <input type="file" id="lu-csv" accept=".csv"></label>
        <div id="lu-out"></div>`;
      $("#lu-key").onclick = async () => {
        const r = await api(`/api/admin/integrations/laceup/inbound-key`,
                            { method: "POST" });
        $("#lu-out").innerHTML = `<div class="card" style="margin-top:10px">
          <label>POST orders to</label>
          <input value="${esc(r.url)}" readonly>
          <label>With header <code>X-API-Key</code></label>
          <input value="${esc(r.key)}" readonly>
          <p class="dim">This key is the whole of the security on that
            address, so treat it like a password. Issue a new one and the old
            stops working immediately.</p></div>`;
      };
      $("#lu-csv").onchange = async (e) => {
        const f = e.target.files[0];
        if (!f) return;
        const fd = new FormData();
        fd.append("file", f);
        try {
          const r = await fetch("/api/admin/integrations/laceup/import", {
            method: "POST", headers: { Authorization: "Bearer " + S.user.token },
            body: fd });
          const out = await r.json();
          if (!r.ok) throw new Error(out.detail || "import failed");
          $("#lu-out").innerHTML = `<p class="dim">Placed
            ${out.placed.length} order(s).${out.skipped.length
              ? ` Skipped ${out.skipped.length}: ` + out.skipped.map((s) =>
                  esc(`${s.row} — ${s.why}`)).join("; ") : ""}</p>`;
        } catch (err) { toast(err.message); }
      };
    }
    return;
  }

  if (!box) return;

  if (p.auth === "oauth2") {
    box.innerHTML = `
      <p class="dim">${p.app_ready
        ? "App registered. Connecting opens " + esc(p.label)
          + " so you can approve access."
        : "First register an app with " + esc(p.label) + " and paste its "
          + "client id and secret. They belong to your company, not to this "
          + "software, which is why they aren't shipped with it."}</p>
      ${p.app_ready ? "" : `
        <label class="f">Client ID<input id="app-id-${p.name}"></label>
        <label class="f">Client secret
          <input id="app-secret-${p.name}" type="password"></label>
        <button class="btn alt sm" data-appsave="${p.name}">Save app</button>`}
      ${p.app_ready ? `<button class="btn" data-auth="${p.name}"
        >Connect ${esc(p.label)}</button>` : ""}
      <p class="dim" id="app-msg-${p.name}"></p>`;

    const save = box.querySelector("[data-appsave]");
    if (save) save.onclick = async () => {
      try {
        const r = await api(`/api/admin/integrations/${p.name}/app`, {
          body: { client_id: $(`#app-id-${p.name}`).value,
                  client_secret: $(`#app-secret-${p.name}`).value } });
        toast(`Saved. Add ${r.redirect_uri} as the redirect URI.`);
        refresh();
      } catch (e) { toast(e.message); }
    };
    const go = box.querySelector("[data-auth]");
    if (go) go.onclick = async () => {
      try {
        const r = await api(`/api/admin/integrations/${p.name}/authorize`);
        location.href = r.url;
      } catch (e) {
        $(`#app-msg-${p.name}`).innerHTML =
          `<span class="low">${esc(e.message)}</span>`;
      }
    };
    return;
  }

  box.innerHTML = `
    ${p.fields.map((f) => `<label class="f">${esc(f.label)}
      ${f.hint ? `<span class="dim">${esc(f.hint)}</span>` : ""}
      <input id="fld-${p.name}-${f.k}" ${f.secret ? 'type="password"' : ""}
        autocomplete="off"></label>`).join("")}
    <button class="btn" data-conn="${p.name}">Connect</button>
    <p class="dim" id="msg-${p.name}"></p>`;
  box.querySelector("[data-conn]").onclick = async () => {
    const b = box.querySelector("[data-conn]");
    const msg = $(`#msg-${p.name}`);
    const fields = {};
    p.fields.forEach((f) => {
      fields[f.k] = $(`#fld-${p.name}-${f.k}`).value;
    });
    b.disabled = true; b.setAttribute("aria-busy", "true");
    msg.textContent = `checking with ${p.label}…`;
    try {
      const r = await api(`/api/admin/integrations/${p.name}/connect`,
                          { body: { fields } });
      toast(`${p.label} connected${r.account ? " — " + r.account : ""}`);
      refresh();
    } catch (e) {
      msg.innerHTML = `<span class="low">${esc(e.message)}</span>`;
    } finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  };
}

// ---------- Trello ----------
/* What we sent to the board and what became of it. Read from our own
   records rather than from the board, because the question is "what did we
   raise and did anyone deal with it" — a board has plenty on it this system
   never put there. */
async function renderTrello() {
  const st = await api("/api/admin/integrations");
  const p = st.providers.find((x) => x.name === "trello");
  if (!p.connected) {
    view().innerHTML = `
      <h2>Trello</h2>
      <div class="card empty"><span class="e-ic">${opsIcon("list")}</span>
        <b>Trello isn't connected</b>
        <p class="dim">Connect it and every enquiry, support ticket and
          low-stock warning becomes a card on the list you choose.</p>
        <button class="btn" id="tr-go">Set it up</button></div>`;
    $("#tr-go").onclick = () => { S.tab = "integrations"; render(); };
    return;
  }
  const { cards } = await api("/api/admin/integrations/trello/cards");
  const open = cards.filter((c) => c.local_state !== "closed");
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Trello</h2>
        <p class="dim">${esc(p.account)} · ${p.live
          ? "changes on the board arrive here as they happen"
          : "press sync to read the board — or go live under Integrations"}
        </p></div>
      <span class="head-acts">
        <button class="btn alt" id="tr-sync">Sync now</button>
      </span>
    </div>
    <div class="stats">
      <div class="stat"><div class="n">${cards.length}</div>
        <div class="l">cards raised</div></div>
      <div class="stat"><div class="n ${open.length ? "" : ""}">${open.length}</div>
        <div class="l">still open here</div></div>
      <div class="stat"><div class="n">${p.live ? "live" : "manual"}</div>
        <div class="l">updates</div></div>
    </div>
    ${cards.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>what</th><th>raised for</th><th>on the board</th>
        <th>here</th><th>last read</th><th></th></tr></thead>
      <tbody>${cards.map((c) => `<tr>
        <td>${esc(c.kind)} #${c.local_id}</td>
        <td>${esc(c.label || "—")}</td>
        <td>${c.remote_state
          ? `<span class="pill">${esc(c.remote_state)}</span>`
          : '<span class="dim">not read yet</span>'}</td>
        <td><span class="pill ${c.local_state === "closed" ? "ok" : ""}"
          >${esc(c.local_state || "—")}</span></td>
        <td class="dim">${c.synced_at ? timeAgo(c.synced_at) : "never"}</td>
        <td>${c.url ? `<a class="btn alt sm" href="${esc(c.url)}"
          target="_blank" rel="noopener">Open</a>` : ""}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : `<div class="card empty"><span class="e-ic">${opsIcon("list")}</span>
         <b>No cards raised yet</b>
         <p class="dim">The next enquiry, ticket or low-stock warning will
           make one.</p></div>`}`;
  $("#tr-sync").onclick = async () => {
    const b = $("#tr-sync");
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      const r = await api("/api/admin/integrations/trello/sync",
                          { method: "POST" });
      toast(r.changed.length
        ? `${r.changed.length} of ${r.checked} moved on`
        : `${r.checked} checked, nothing has changed`);
      renderTrello();
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  };
}

// ---------- Dropbox ----------
/* The folder, not a promise about it. An integration that files things
   somewhere you can't see is one you take on faith, and the first time
   anybody checks is the day they need the file. */
async function renderDropbox() {
  const st = await api("/api/admin/integrations");
  const p = st.providers.find((x) => x.name === "dropbox");
  if (!p.connected) {
    view().innerHTML = `
      <h2>Dropbox</h2>
      <div class="card empty"><span class="e-ic">${opsIcon("file")}</span>
        <b>Dropbox isn't connected</b>
        <p class="dim">Connect it and signed documents are filed
          automatically, and the database backup has somewhere to live that
          isn't this machine.</p>
        <button class="btn" id="db-go">Set it up</button></div>`;
    $("#db-go").onclick = () => { S.tab = "integrations"; render(); };
    return;
  }
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Dropbox</h2>
        <p class="dim">${esc(p.account)} · signed documents are filed here as
          they're signed.</p></div>
      <span class="head-acts">
        <button class="btn" id="dbx-backup">Back up the database</button>
        <button class="btn alt" id="dbx-refresh">Refresh</button>
      </span>
    </div>
    <p class="dim" style="max-width:640px">A backup goes up whole and
      unredacted — credentials included — because one with the secrets
      stripped out only looks like a backup until you need it. Treat the
      folder the way you'd treat the database.</p>
    <div id="dbx-files"><div class="skel"></div></div>`;
  const draw = async () => {
    try {
      const d = await api("/api/admin/integrations/dropbox/files");
      $("#dbx-files").innerHTML = d.files.length
        ? `<div class="card"><div class="tablewrap"><table>
            <thead><tr><th>file</th><th>where</th><th class="num">size</th>
              <th>filed</th></tr></thead>
            <tbody>${d.files.map((f) => `<tr>
              <td>${esc(f.name)}</td>
              <td class="dim">${esc(f.path.replace("/" + f.name, "") || "/")}</td>
              <td class="num">${(f.size / 1024).toFixed(0)} KB</td>
              <td class="dim">${esc((f.modified || "").replace("T", " ")
                .replace("Z", ""))}</td>
            </tr>`).join("")}</tbody></table></div></div>`
        : `<div class="card empty"><span class="e-ic">${opsIcon("file")}</span>
           <b>Nothing filed yet</b><p class="dim">${esc(d.note
             || "Sign a document, or back the database up, and it appears here.")}
           </p></div>`;
    } catch (e) {
      $("#dbx-files").innerHTML = `<div class="card dim">${esc(e.message)}</div>`;
    }
  };
  $("#dbx-refresh").onclick = draw;
  $("#dbx-backup").onclick = async () => {
    const b = $("#dbx-backup");
    if (!confirm("Send a full backup to Dropbox?\n\nIt contains everything, "
      + "credentials included.")) return;
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try {
      const r = await api("/api/admin/integrations/dropbox/backup",
                          { method: "POST" });
      toast(`Backed up — ${(r.bytes / 1024).toFixed(0)} KB`);
      draw();
    } catch (e) { toast(e.message); }
    finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  };
  draw();
}

// ---------- confetti (achievement unlocks) ----------

function confetti() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const cv = document.createElement("canvas");
  cv.id = "confetti";
  cv.width = innerWidth;
  cv.height = innerHeight;
  document.body.appendChild(cv);
  const ctx = cv.getContext("2d");
  const colors = ["#35b26b", "#4a9eda", "#d4a017", "#d0564f", "#a06ad4"];
  const parts = Array.from({ length: 90 }, () => ({
    x: cv.width / 2 + (Math.random() - 0.5) * 220,
    y: cv.height * 0.28,
    vx: (Math.random() - 0.5) * 9,
    vy: -Math.random() * 9 - 3,
    s: Math.random() * 6 + 3,
    c: colors[Math.floor(Math.random() * colors.length)],
    r: Math.random() * Math.PI,
  }));
  const t0 = performance.now();
  (function step(t) {
    ctx.clearRect(0, 0, cv.width, cv.height);
    for (const p of parts) {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.28;
      p.r += 0.1;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.r);
      ctx.fillStyle = p.c;
      ctx.fillRect(-p.s / 2, -p.s / 2, p.s, p.s * 0.6);
      ctx.restore();
    }
    if (t - t0 < 1700) requestAnimationFrame(step);
    else cv.remove();
  })(t0);
}


/* ---------- one connection, on its own page ----------
   Four connections earned bespoke screens because they do more than
   connect — Slack reads channels, Trello syncs cards. The rest have one
   story each: is it connected, what has it carried, and does it still
   work. That is a screen, and it belongs where somebody looks for it
   rather than three clicks inside a list. */
async function renderOneIntegration(name, label) {
  const d = await api("/api/admin/integrations");
  const p = (d.providers || []).find((x) => x.name === name);
  if (!p) {
    view().innerHTML = `<h2>${esc(label)}</h2>
      ${emptyState("link", "Not a connection this install knows",
        "It may have been taken out of the registry.")}`;
    return;
  }
  const log = (d.log || []).filter((l) => l.provider === name).slice(0, 25);
  const bespoke = { slack: "slack", trello: "trello", dropbox: "dropbox" };
  view().innerHTML = `
    <div class="page-head">
      <div><h2>${esc(p.label)}</h2>
        <p class="dim">${esc(p.blurb)}</p></div>
      <div class="top-actions">
        ${bespoke[name] ? `<button class="btn alt" data-onefull
          >Open ${esc(p.label)}</button>` : ""}
        ${p.connected ? `<button class="btn alt" data-oneoff
          >Disconnect</button>
          <button class="btn alt" data-onetest>Send a test</button>` : ""}
        <button class="btn alt" data-oneall>${opsIcon("link", "btn-ic")}
          All connections</button>
      </div>
    </div>
    <div class="card intg">
      <div class="doc-top">
        <div class="doc-main"><b>${p.connected ? "Connected"
          : p.inbound_ready ? "Listening" : "Not connected yet"}</b>
          <span class="dim">${esc(p.does)}</span></div>
        <span class="pill ${p.connected || p.inbound_ready ? "ok" : ""}">${
          p.connected ? esc(p.account || "connected")
            : p.inbound_ready ? "has a key" : "off"}</span>
      </div>
      ${p.events.length ? `<p class="dim intg-when">Fires when
        ${p.events.map(esc).join(", ")}.</p>` : ""}
      ${p.connected ? "" : `<div class="intg-form" id="f-${name}"></div>`}
      ${name === "laceup"
        ? `<div class="intg-form" id="f-${name}-extra"></div>` : ""}
    </div>
    <h3>What it has carried</h3>
    ${log.length ? `<div class="card"><div class="tablewrap"><table>
      <thead><tr><th>when</th><th>event</th><th>result</th></tr></thead>
      <tbody>${log.map((l) => `<tr>
        <td class="dim">${fmtDate(l.created_at)}</td>
        <td>${esc(l.event)}</td>
        <td>${l.ok ? '<span class="pill ok">ok</span>'
          : `<span class="pill bad">failed</span>
             <span class="dim">${esc(l.detail)}</span>`}</td>
      </tr>`).join("")}</tbody></table></div></div>`
      : emptyState("link", "Nothing yet", "A connection that has never "
        + "carried anything is a guess. Send it a test.")}`;
  drawForm(p, () => renderOneIntegration(name, label));
  if ($("[data-oneall]")) $("[data-oneall]").onclick = () => {
    S.tab = "integrations"; render();
  };
  if ($("[data-onefull]")) $("[data-onefull]").onclick = () => {
    S.tab = bespoke[name]; render();
  };
  if ($("[data-onetest]")) $("[data-onetest]").onclick = async () => {
    try {
      const r = await api(`/api/admin/integrations/${name}/test`,
                          { method: "POST" });
      toast(r.detail || "it answered");
    } catch (err) { toast(err.message); }
    renderOneIntegration(name, label);
  };
  if ($("[data-oneoff]")) $("[data-oneoff]").onclick = async () => {
    if (!confirm(`Disconnect ${label}?\n\nThe credential is forgotten. `
      + "The record of what it carried stays.")) return;
    try {
      await api(`/api/admin/integrations/${name}`, { method: "DELETE" });
    } catch (err) { toast(err.message); }
    renderOneIntegration(name, label);
  };
}
