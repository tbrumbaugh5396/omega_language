// ---------- live socket (chat + call signaling) ----------

function connectWS() {
  if (!S.user || S._ws) return;
  clearTimeout(S._wsRetry);
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${location.host}/ws?token=${encodeURIComponent(S.user.token)}`);
  S._ws = ws;
  ws.onopen = () => { S._wsWait = 0; };
  ws.onmessage = (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    if (d.type === "msg") onChatMessage(d);
    else if (d.type === "signal") onSignal(d);
  };
  /* Back off rather than retrying on a fixed timer. A socket the server
     keeps refusing — a stale token, an old tab left open overnight — used to
     mean a reconnect every three seconds forever, which is a connection
     storm nobody is watching and which multiplies by the number of open
     tabs. Doubling to a minute makes a broken tab cheap. */
  ws.onclose = () => {
    S._ws = null;
    if (!S.user) return;
    S._wsWait = Math.min((S._wsWait || 2000) * 2, 60000);
    S._wsRetry = setTimeout(connectWS, S._wsWait);
  };
}

function wsSend(obj) {
  if (S._ws && S._ws.readyState === 1) {
    S._ws.send(JSON.stringify(obj));
    return true;
  }
  return false;
}

function onChatMessage(d) {
  const m = d.message;
  if (S.tab === "chat" && S.chatConv === d.conv_id && $("#chat-msgs")) {
    if (!document.querySelector(`[data-mid="${m.id}"]`)) chatAppend(m);
    setLastRead(d.conv_id, m.id);
  } else if (m.user_id !== S.user.id) {
    toast(`${m.name}: ${m.body.slice(0, 60)}`);
  }
}

// ---------- calls (WebRTC over the socket) ----------

const CALL = { pc: null, peer: null, media: "audio", stream: null,
  pendingIce: [], state: "idle", offer: null, timer: null, started: 0 };

// Audible ring via WebAudio — no asset files needed.
const RING = { ctx: null, timer: null };
function ringStart() {
  try {
    RING.ctx = RING.ctx || new (window.AudioContext ||
      window.webkitAudioContext)();
    const beep = () => {
      const o = RING.ctx.createOscillator();
      const g = RING.ctx.createGain();
      o.frequency.value = 880;
      g.gain.setValueAtTime(0.12, RING.ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, RING.ctx.currentTime + 0.7);
      o.connect(g).connect(RING.ctx.destination);
      o.start();
      o.stop(RING.ctx.currentTime + 0.75);
    };
    beep();
    RING.timer = setInterval(beep, 1800);
  } catch {}
}
function ringStop() {
  clearInterval(RING.timer);
  RING.timer = null;
}

function signal(payload) { wsSend({ type: "signal", to: CALL.peer, payload }); }

async function startCall(peerId, media) {
  if (!peerId) return toast("nobody available to call right now");
  if (CALL.state !== "idle") return toast("already in a call");
  CALL.peer = peerId;
  CALL.media = media;
  CALL.state = "calling";
  await setupPC(true);
}

async function setupPC(isCaller, remoteOffer) {
  try {
    CALL.stream = await navigator.mediaDevices.getUserMedia(
      { audio: true, video: CALL.media === "video" });
  } catch (e) {
    toast("mic/camera unavailable: " + e.message);
    return endCall(true);
  }
  const pc = new RTCPeerConnection(
    { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
  CALL.pc = pc;
  CALL.stream.getTracks().forEach((t) => pc.addTrack(t, CALL.stream));
  pc.onicecandidate = (e) => {
    if (e.candidate) signal({ call: "ice", ice: e.candidate });
  };
  pc.ontrack = (e) => {
    const v = $("#call-remote");
    if (v && v.srcObject !== e.streams[0]) v.srcObject = e.streams[0];
  };
  pc.onconnectionstatechange = () => {
    if (["failed", "disconnected", "closed"].includes(pc.connectionState) &&
        CALL.state !== "idle") { toast("call dropped"); endCall(true); }
  };
  showCallOverlay(isCaller ? "calling…" : "connecting…");
  const lv = $("#call-local");
  if (lv) lv.srcObject = CALL.stream;
  if (isCaller) {
    await pc.setLocalDescription(await pc.createOffer());
    signal({ call: "offer", sdp: pc.localDescription, media: CALL.media });
  } else {
    await pc.setRemoteDescription(remoteOffer);
    for (const ice of CALL.pendingIce) await pc.addIceCandidate(ice).catch(() => {});
    CALL.pendingIce = [];
    await pc.setLocalDescription(await pc.createAnswer());
    signal({ call: "answer", sdp: pc.localDescription });
    CALL.state = "active";
    setCallStatus("connected");
  }
}

async function onSignal(d) {
  const p = d.payload || {};
  if (p.call === "offer") {
    if (CALL.state !== "idle") {
      wsSend({ type: "signal", to: d.from, payload: { call: "busy" } });
      return;
    }
    CALL.peer = d.from;
    CALL.media = p.media || "audio";
    CALL.state = "ringing";
    CALL.offer = p.sdp;
    showRing(d.from_name, p.media || "audio");
  } else if (p.call === "answer" && CALL.pc) {
    await CALL.pc.setRemoteDescription(p.sdp);
    for (const ice of CALL.pendingIce) await CALL.pc.addIceCandidate(ice).catch(() => {});
    CALL.pendingIce = [];
    CALL.state = "active";
    setCallStatus("connected");
  } else if (p.call === "ice") {
    if (CALL.pc && CALL.pc.remoteDescription) {
      await CALL.pc.addIceCandidate(p.ice).catch(() => {});
    } else CALL.pendingIce.push(p.ice);
  } else if (["hangup", "decline", "busy"].includes(p.call)) {
    toast(p.call === "busy" ? "they're on another call" : "call ended");
    endCall(false);
  }
}

function showCallOverlay(status) {
  let o = $("#call-overlay");
  if (!o) {
    o = document.createElement("div");
    o.id = "call-overlay";
    document.body.appendChild(o);
  }
  o.innerHTML = `
    <div class="call-box">
      <div id="call-status" class="dim">${esc(status)}</div>
      <video id="call-remote" autoplay playsinline
        ${CALL.media === "audio" ? 'style="height:60px;background:#0c1013"' : ""}></video>
      <video id="call-local" autoplay playsinline muted
        ${CALL.media === "audio" ? 'style="display:none"' : ""}></video>
      <button class="btn danger" id="call-end">Hang up</button>
    </div>`;
  $("#call-end").onclick = () => endCall(true);
}

function setCallStatus(s) {
  const el = $("#call-status");
  if (el) el.textContent = s;
  if (s === "connected" && !CALL.timer) {
    CALL.started = Date.now();
    CALL.timer = setInterval(() => {
      const sec = Math.floor((Date.now() - CALL.started) / 1000);
      const el2 = $("#call-status");
      if (el2) el2.textContent =
        `connected · ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
    }, 1000);
  }
}

function showRing(name, media) {
  ringStart();
  let o = $("#call-overlay");
  if (!o) {
    o = document.createElement("div");
    o.id = "call-overlay";
    document.body.appendChild(o);
  }
  o.innerHTML = `
    <div class="call-box">
      <div style="font-size:17px">${opsIcon(media === "video" ? "video" : "phone","call-ic")}
        <b>${esc(name)}</b> is calling…</div>
      <div style="margin-top:12px">
        <button class="btn" id="call-accept">Accept</button>
        <button class="btn danger" id="call-decline">Decline</button>
      </div>
    </div>`;
  $("#call-accept").onclick = () => { ringStop(); setupPC(false, CALL.offer); };
  $("#call-decline").onclick = () => {
    ringStop();
    signal({ call: "decline" });
    endCall(false);
  };
}

function endCall(sendHangup) {
  ringStop();
  clearInterval(CALL.timer);
  if (sendHangup && CALL.peer && CALL.state !== "idle") {
    signal({ call: "hangup" });
  }
  if (CALL.pc) CALL.pc.close();
  if (CALL.stream) CALL.stream.getTracks().forEach((t) => t.stop());
  Object.assign(CALL, { pc: null, peer: null, stream: null, pendingIce: [],
    state: "idle", offer: null, timer: null });
  const o = $("#call-overlay");
  if (o) o.remove();
}

// ---------- chat ----------

function chatAppend(m) {
  const box = $("#chat-msgs");
  if (!box) return;
  const mine = m.user_id === S.user.id;
  const el = document.createElement("div");
  el.className = "msg" + (mine ? " mine" : "");
  el.dataset.mid = m.id;
  el.innerHTML = `${mine ? "" : `<span class="dim" style="font-size:11px">
    ${esc(m.name)}</span><br>`}${esc(m.body)}
    <span class="dim" style="font-size:10px"> ${timeAgo(m.created_at)}</span>`;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

const lastRead = () => JSON.parse(localStorage.getItem("bc_lastread") || "{}");
const setLastRead = (cid, mid) => {
  const lr = lastRead();
  lr[cid] = Math.max(lr[cid] || 0, mid || 0);
  localStorage.setItem("bc_lastread", JSON.stringify(lr));
};

async function renderChat() {
  if (!S.user) { S.tab = "login"; return renderLogin(); }
  connectWS();
  const data = await api("/api/chat/convs");
  const lr = lastRead();
  const isStaff = S.user.is_admin ||
    ["employee", "owner"].includes(S.user.role);
  if (!data.convs.find((c) => c.id === S.chatConv)) {
    S.chatConv = data.convs.length ? data.convs[0].id : null;
  }
  const conv = data.convs.find((c) => c.id === S.chatConv);
  const staff = isStaff ? await api("/api/chat/staff") : null;
  view().innerHTML = `
    <h2>Chat</h2>
    <div class="chat-wrap">
      <div class="chat-side">
        ${isStaff && staff && staff.staff.length ? `
          <div class="dm-start">
            <input id="dm-name" list="dm-names" placeholder="Message someone by name…"
              autocomplete="off">
            <datalist id="dm-names">${staff.staff.map((u) =>
              `<option value="${esc(u.name)}">${
                staff.online.includes(u.id) ? "online" : ""}</option>`).join("")}</datalist>
            <button class="btn sm" id="dm-go">Start</button>
          </div>` : ""}
        ${data.convs.map((c) => {
          const unread = c.last && c.last.user_id !== data.me &&
            c.last.id > (lr[c.id] || 0);
          return `
          <div class="conv ${c.id === S.chatConv ? "on" : ""}" data-conv="${c.id}">
            ${unread ? '<span class="unread-dot"></span>' : ""}
            <b>${esc(c.name || c.kind)}</b>
            ${c.call_target && data.online.includes(c.call_target)
              ? '<span class="dot-online" title="online"></span>' : ""}
            ${c.last ? `<div class="dim" style="font-size:11px">
              ${esc(c.last.name)}: ${esc(c.last.body.slice(0, 26))}</div>` : ""}
          </div>`;
        }).join("")}
      </div>
      <div class="chat-main">
        ${conv ? `
          <div class="chat-head">
            <b>${esc(conv.name || conv.kind)}</b>
            ${conv.call_target ? `
              <span style="float:right">
                <button class="btn alt" id="call-audio" title="voice call">${opsIcon("phone","btn-ic")}</button>
                <button class="btn alt" id="call-video" title="video call">${opsIcon("video","btn-ic")}</button>
              </span>` : ""}
          </div>
          <div id="chat-msgs"></div>
          <form id="chat-form" class="inline" style="margin-top:8px">
            <input id="chat-input" style="flex:1" autocomplete="off"
              placeholder="message…">
            <button class="btn">Send</button>
          </form>`
        : '<div class="dim">no conversations yet</div>'}
      </div>
    </div>`;
  document.querySelectorAll("[data-conv]").forEach((el) => {
    el.onclick = () => { S.chatConv = +el.dataset.conv; render(); };
  });
  if ($("#dm-go")) {
    const startDm = async () => {
      const typed = $("#dm-name").value.trim().toLowerCase();
      if (!typed) return;
      // Exact name first, then a unique partial — so "dev" finds Dev Patel
      // but an ambiguous fragment asks rather than guessing.
      const all = (staff && staff.staff) || [];
      let hit = all.find((u) => u.name.toLowerCase() === typed);
      if (!hit) {
        const near = all.filter((u) => u.name.toLowerCase().includes(typed));
        if (near.length === 1) hit = near[0];
        else if (near.length > 1) {
          return toast(`${near.length} people match "${typed}" — be more specific`);
        }
      }
      if (!hit) return toast(`nobody on the team matches "${typed}"`);
      const r = await api("/api/chat/dm", { body: { user_id: hit.id } });
      S.chatConv = r.conv_id;
      $("#dm-name").value = "";
      render();
    };
    $("#dm-go").onclick = startDm;
    $("#dm-name").onkeydown = (e) => { if (e.key === "Enter") startDm(); };
  }
  if (!conv) return;
  const history = await api(`/api/chat/convs/${conv.id}/messages`);
  history.forEach(chatAppend);
  if (history.length) setLastRead(conv.id, history[history.length - 1].id);
  $("#chat-form").onsubmit = async (e) => {
    e.preventDefault();
    const text = $("#chat-input").value.trim();
    if (!text) return;
    $("#chat-input").value = "";
    if (!wsSend({ type: "msg", conv_id: conv.id, body: text })) {
      const m = await api(`/api/chat/convs/${conv.id}/messages`,
        { body: { body: text } });
      chatAppend(m);
    }
  };
  if ($("#call-audio")) $("#call-audio").onclick = () =>
    startCall(conv.call_target, "audio");
  if ($("#call-video")) $("#call-video").onclick = () =>
    startCall(conv.call_target, "video");
}

// ---------- notifications ----------
/* Where each kind of alert should take you. A notification is a prompt to do
   something; landing on the screen where you do it is the whole point. */
const NOTIF_TAB = {
  order: "orders", inventory: "inventory", logistics: "routes",
  affiliate: "affiliates", analytics: "analytics",
  experiment: "experiments", achievement: "profile",
  document: "docs", ticket: "chat", enquiry: "outreach",
  engagement: "clients",
  // a capability ask is fulfilled on the Platform tab — the notification
  // lands you where the grant button is, not on a board to hunt through
  lead: "fleet",
  learning: "learning",
};
const NOTIF_LABEL = {
  order: "open orders", inventory: "open inventory", logistics: "open routes",
  affiliate: "open affiliates", analytics: "open analytics",
  experiment: "open experiments", achievement: "see your profile",
  document: "open documents", ticket: "open chat", enquiry: "open outreach",
  lead: "open the Platform tab",
};

async function fetchNotifs() {
  if (!S.user) return;
  try {
    const d = await api("/api/notifications");
    const prevTop = S.notifs && S.notifs.items[0] ? S.notifs.items[0].id : 0;
    S.notifs = d;
    const fresh = d.items.filter((i) => i.id > prevTop && !i.is_read);
    if (prevTop && fresh.length) {
      toast(fresh[0].title);
      if (fresh.some((i) => i.kind === "achievement")) confetti();
      if ("Notification" in window && Notification.permission === "granted") {
        fresh.slice(0, 3).forEach((i) =>
          new Notification(S.meta.brand || "Business Control",
            { body: i.title }));
      }
    }
    const bell = $("#bell");
    if (bell) bell.innerHTML = opsIcon("bell","bell-ic") + (d.unread
      ? `<span class="bell-n">${d.unread}</span>` : "");
  } catch {}
}

function b64ToU8(s) {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

async function enablePush() {
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      return toast("push unsupported here — on iPhone, install the app to"
        + " your Home Screen first");
    }
    if ((await Notification.requestPermission()) !== "granted") {
      return toast("notifications not allowed");
    }
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/pubkey");
    const sub = await reg.pushManager.subscribe(
      { userVisibleOnly: true, applicationServerKey: b64ToU8(key) });
    await api("/api/push/subscribe", { body: { subscription: sub.toJSON() } });
    toast("push enabled on this device");
  } catch (e) { toast("push failed: " + e.message); }
}

function startNotifPoll() {
  clearInterval(S._notifTimer);
  fetchNotifs();
  S._notifTimer = setInterval(fetchNotifs, 45000);
}

async function toggleNotifPanel() {
  const old = $("#notif-panel");
  if (old) { old.remove(); return; }
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
  const panel = document.createElement("div");
  panel.id = "notif-panel";
  const items = (S.notifs && S.notifs.items) || [];
  panel.innerHTML = `<h3 style="margin:4px 0 8px">Notifications
      <button class="btn alt" id="push-btn" style="float:right;padding:3px 9px"
        title="get these on this device even with the app closed">
        Enable push</button></h3>` +
    (items.length ? items.map((i) => `
      <div class="notif ${i.is_read ? "" : "unread"} ${
        NOTIF_TAB[i.kind] ? "clickable" : ""}"
        ${NOTIF_TAB[i.kind] ? `data-ngo="${i.kind}"` : ""}>
        <div>${esc(i.title)}</div>
        ${i.body ? `<div class="dim" style="font-size:12px">${esc(i.body)}</div>` : ""}
        <div class="dim" style="font-size:11px">${timeAgo(i.created_at)}${
          NOTIF_TAB[i.kind] ? " · " + NOTIF_LABEL[i.kind] : ""}</div>
      </div>`).join("")
    : '<div class="dim">nothing yet</div>');
  document.body.appendChild(panel);
  $("#push-btn").onclick = enablePush;
  // A notification that tells you something happened but not where to deal
  // with it makes you hunt for the tab. Each kind knows its own destination.
  panel.querySelectorAll("[data-ngo]").forEach((el) => el.onclick = () => {
    const tab = NOTIF_TAB[el.dataset.ngo];
    panel.remove();
    if (tab && tab !== S.tab) { S.tab = tab; render(); }
    else if (tab) render();
  });
  if (S.notifs && S.notifs.unread) {
    await api("/api/notifications/read", { body: {} }).catch(() => {});
    S.notifs.items.forEach((i) => { i.is_read = 1; });
    S.notifs.unread = 0;
    const bell = $("#bell");
    if (bell) bell.innerHTML = opsIcon("bell","bell-ic");
  }
}

// ---------- shared helpers: time, video, route summary ----------

const fmtMin = (m) => m >= 60
  ? `${Math.floor(m / 60)}h ${Math.round(m % 60)}m` : `${Math.round(m)}m`;

function videoEmbed(url) {
  if (!url) return "";
  const yt = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{6,})/);
  if (yt) return `<iframe width="100%" height="240"
    style="border:0;border-radius:8px"
    src="https://www.youtube.com/embed/${yt[1]}" allowfullscreen
    loading="lazy"></iframe>`;
  if (/\.(mp4|webm|mov|m4v)(\?|$)/i.test(url))
    return `<video controls playsinline
      style="width:100%;border-radius:8px" src="${esc(url)}"></video>`;
  return `<a href="${esc(url)}" target="_blank" rel="noopener">▶ video feed</a>`;
}

function routeSummary(r) {
  return `${routeMap(r.stops)}
    <div class="dim" style="margin:4px 0">${r.total_km} km ·
      about ${fmtMin(r.total_min)} including stops</div>
    <table><thead><tr><th>#</th><th>store</th><th>city</th><th>leg</th>
      <th>drive</th><th>ETA</th><th>done</th></tr></thead><tbody>
    ${r.stops.map((s) => `<tr><td>${s.seq + 1}</td><td>${esc(s.name)}</td>
      <td class="dim">${esc(s.city)}</td><td>${s.leg_km} km</td>
      <td>${fmtMin(s.drive_min)}</td><td>+${fmtMin(s.eta_min)}</td>
      <td>${s.delivered ? "✓" : ""}</td></tr>`).join("")}
    </tbody></table>`;
}

// ---------- camera QR scanner ----------

async function renderScan() {
  view().innerHTML = `
    <h2>Scan</h2>
    <div class="card" style="max-width:520px">
      <video id="scan-video" autoplay playsinline muted
        style="width:100%;border-radius:8px;background:#000"></video>
      <div id="scan-status" class="dim" style="margin:8px 0">starting camera…</div>
      <form class="inline" id="scan-manual">
        <input id="scan-code" style="flex:1"
          placeholder="or type a code / link (e.g. bc:truck:1)">
        <button class="btn alt">Go</button>
      </form>
      <div class="dim" style="font-size:12px;margin-top:6px">Drivers: scan the
        QR on your truck to check in and get today's route. Any app QR
        (sign-in, promo) works here too. On phones the camera needs the HTTPS
        start command.</div>
    </div>
    <div id="scan-result"></div>`;
  $("#scan-manual").onsubmit = (e) => {
    e.preventDefault();
    handleScan($("#scan-code").value.trim());
  };
  const status = $("#scan-status");
  if (!("BarcodeDetector" in window)) {
    status.textContent = "No built-in QR detector in this browser (e.g. iPhone "
      + "Safari) — use the box below, or open in Chrome.";
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia(
      { video: { facingMode: "environment" } });
    const video = $("#scan-video");
    video.srcObject = stream;
    const det = new BarcodeDetector({ formats: ["qr_code"] });
    status.textContent = "point the camera at a QR code";
    let last = "";
    const loop = async () => {
      if (S.tab !== "scan" || !video.isConnected) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      try {
        const codes = await det.detect(video);
        if (codes.length && codes[0].rawValue !== last) {
          last = codes[0].rawValue;
          status.textContent = "scanned!";
          handleScan(last);
        }
      } catch {}
      setTimeout(loop, 400);
    };
    video.onloadedmetadata = loop;
  } catch (e) {
    status.textContent = `camera unavailable (${e.message}) — manual entry `
      + "below still works.";
  }
}

async function handleScan(text) {
  if (!text) return;
  const out = $("#scan-result");
  const truck = text.match(/^bc:truck:(\d+)$/);
  if (truck) {
    if (!S.user) { out.innerHTML =
      '<div class="card">Sign in first (ask an admin for your sign-in QR), '
      + "then scan the truck again.</div>"; return; }
    try {
      const r = await api(`/api/trucks/${truck[1]}/checkin`, { body: {} });
      out.innerHTML = `<div class="card">
        <b>Checked in to ${esc(r.truck.name)}</b> — drive safe, ${esc(r.driver)}.
        ${r.route ? `<h3>Your route: ${esc(r.route.name)}</h3>${routeSummary(r.route)}`
          : '<div class="dim">No route assigned to this truck yet — ask dispatch.</div>'}
        </div>`;
    } catch (e) {
      out.innerHTML = `<div class="card">Error: ${esc(e.message)}</div>`;
    }
    return;
  }
  try {
    const url = new URL(text);
    if (url.origin === location.origin) { location.href = url.href; return; }
    out.innerHTML = `<div class="card">External link:
      <a href="${esc(url.href)}" target="_blank" rel="noopener">${esc(url.href)}</a></div>`;
  } catch {
    out.innerHTML = `<div class="card">Scanned: ${esc(text)}</div>`;
  }
}
