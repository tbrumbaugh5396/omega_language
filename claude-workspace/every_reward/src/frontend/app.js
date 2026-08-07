/* Every Reward — vanilla JS SPA */
let TOKEN = localStorage.getItem("er_token") || "";
let ME = null;
let INFO = {};

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(path, opts = {}) {
  opts.headers = Object.assign(
    { "Content-Type": "application/json", Authorization: "Bearer " + TOKEN },
    opts.headers || {});
  if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  const r = await fetch("/api" + path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

/* ---------- auth ---------- */
async function walletLogin() {
  if (!window.ethereum) { toast("No wallet extension found — install MetaMask or use dev login"); return; }
  try {
    const [address] = await window.ethereum.request({ method: "eth_requestAccounts" });
    const { message } = await api(`/auth/nonce?address=${address}`);
    const signature = await window.ethereum.request({
      method: "personal_sign", params: [message, address] });
    const res = await api("/auth/verify", { method: "POST", body: { address, signature } });
    finishLogin(res);
  } catch (e) { toast(e.message); }
}

async function devLogin() {
  try {
    const res = await api("/auth/dev", { method: "POST",
      body: { nickname: $("#dev-nick").value, admin_key: $("#dev-key").value } });
    finishLogin(res);
  } catch (e) { toast(e.message); }
}

function finishLogin(res) {
  TOKEN = res.token;
  localStorage.setItem("er_token", TOKEN);
  ME = res.user;
  $("#login").style.display = "none";
  boot();
}

async function logout() {
  try { await api("/auth/logout", { method: "POST" }); } catch {}
  localStorage.removeItem("er_token");
  location.reload();
}

/* ---------- tabs ---------- */
document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("#tab-" + b.dataset.tab).classList.add("active");
    refresh(b.dataset.tab);
  }));

/* ---------- markets ---------- */
function mechLabel(m) {
  return { parimutuel: "pool", fixed: "fixed odds", lmsr: "market maker" }[m] || m;
}

function outcomeLine(m, o) {
  let right = "";
  if (m.mechanism === "fixed" && o.fixed_odds) right = `${o.fixed_odds}×`;
  if (m.mechanism === "parimutuel") right = o.implied_odds ? `${o.implied_odds}×` : "—";
  if (m.mechanism === "lmsr" && o.price != null) right = `${Math.round(o.price * 100)}%`;
  const winner = m.winner_outcome_id === o.id ? " winner" : "";
  const dis = m.status !== "open" ? "disabled" : "";
  return `<button class="outcome-btn${winner}" ${dis}
    onclick="betPrompt(${m.id}, ${o.id}, '${esc(o.label)}')">
    <span>${esc(o.label)}</span><span class="odds">${right}</span></button>`;
}

function renderMarket(m) {
  return `
    <div class="card">
      <div class="market-title">${esc(m.title)}</div>
      <div class="market-meta">
        <span class="pill ${m.status}">${m.status}</span>
        <span class="pill">${mechLabel(m.mechanism)}</span>
        <span class="pill">${m.total_staked} cr staked</span>
        ${m.opening_id ? `<span class="pill">📦 opening #${m.opening_id}</span>` : ""}
        ${m.close_at ? `<span class="pill">closes ${new Date(m.close_at * 1000).toLocaleString()}</span>` : ""}
        ${m.resolver !== "manual" ? `<span class="pill">oracle: ${esc(m.resolver)}</span>` : ""}
      </div>
      ${m.description ? `<div class="fine" style="margin-bottom:8px">${esc(m.description)}</div>` : ""}
      ${m.outcomes.map((o) => outcomeLine(m, o)).join("")}
      ${ME && ME.is_admin && m.status !== "resolved" && m.status !== "void" ? `
        <div class="row" style="margin-top:8px">
          <button class="ghost" onclick="adminResolve(${m.id}, ${JSON.stringify(m.outcomes.map(o => ({ id: o.id, label: o.label }))).replace(/"/g, "&quot;")}, '${esc(m.resolver)}')">Resolve</button>
          <button class="danger" onclick="adminVoid(${m.id})">Void</button>
        </div>` : ""}
    </div>`;
}

async function loadMarkets() {
  const { markets } = await api("/markets");
  $("#markets-list").innerHTML =
    markets.map(renderMarket).join("") || "<p>No markets yet.</p>";
}

async function betPrompt(marketId, outcomeId, label) {
  if (!ME) return;
  const stake = parseInt(prompt(`Stake on "${label}" (credits):`), 10);
  if (!stake || stake <= 0) return;
  try {
    const q = await api(`/markets/${marketId}/quote?outcome_id=${outcomeId}&stake=${stake}`);
    const win = q.payout_if_win ?? q.payout_if_win_now;
    if (!confirm(`Stake ${stake} cr on "${label}"?\nEstimated payout if it wins: ~${win} cr`)) return;
    const r = await api(`/markets/${marketId}/bet`, { method: "POST",
      body: { outcome_id: outcomeId, stake } });
    toast(`Bet placed. Balance: ${r.balance} cr`);
    loadMarkets(); loadMe();
  } catch (e) { toast(e.message); }
}

async function adminResolve(marketId, outcomes, resolver) {
  let winner = null;
  if (resolver === "manual") {
    const pick = prompt("Winner?\n" + outcomes.map((o, i) => `${i}: ${o.label}`).join("\n"));
    if (pick === null) return;
    const o = outcomes[parseInt(pick, 10)];
    if (!o) { toast("bad choice"); return; }
    winner = o.id;
  } else if (!confirm("Ask the oracle to resolve this market now?")) return;
  try {
    const r = await api(`/markets/${marketId}/resolve`, { method: "POST",
      body: { winner_outcome_id: winner } });
    toast(`Resolved: paid ${r.total_paid} cr across ${r.bets_settled} bets. ${r.evidence || ""}`);
    loadMarkets(); loadMe();
  } catch (e) { toast(e.message); }
}

async function adminVoid(marketId) {
  if (!confirm("Void this market and refund all stakes?")) return;
  try {
    const r = await api(`/markets/${marketId}/void`, { method: "POST" });
    toast(`Voided — refunded ${r.refunded_bets} bets`);
    loadMarkets();
  } catch (e) { toast(e.message); }
}

function addOutcomeRow() {
  const div = document.createElement("div");
  div.className = "row outcome-row";
  div.innerHTML = `<input class="o-label" placeholder="Outcome label">
    <input class="o-odds" placeholder="odds (fixed only)" type="number" step="0.01">`;
  $("#nm-outcomes").appendChild(div);
}

let PRESETS = [];

async function loadPresets() {
  const r = await api("/presets");
  PRESETS = r.presets;
  $("#nm-preset").innerHTML =
    '<option value="">pull-rate preset… (fills fixed odds from known rates)</option>' +
    PRESETS.map((p) => `<option value="${esc(p.key)}">${esc(p.label)}</option>`).join("");
}

function applyPreset() {
  const p = PRESETS.find((x) => x.key === $("#nm-preset").value);
  if (!p) { $("#preset-note").textContent = ""; return; }
  $("#nm-mech").value = "fixed";
  const box = $("#nm-outcomes");
  box.innerHTML = "";
  for (const o of p.outcomes) {
    const div = document.createElement("div");
    div.className = "row outcome-row";
    div.innerHTML = `<input class="o-label"><input class="o-odds" type="number" step="0.01">`;
    div.querySelector(".o-label").value = o.label;
    div.querySelector(".o-odds").value = o.odds;
    box.appendChild(div);
  }
  if (!$("#nm-title").value) $("#nm-title").value = p.label;
  $("#preset-note").textContent = "Approximate rates: " +
    p.outcomes.map((o) => `${o.label} ${Math.round(o.probability * 1000) / 10}%`).join(" · ") +
    " — odds include the house margin; edit freely, real rates vary by set.";
}

async function loadLeaders() {
  const { leaders } = await api("/leaderboard");
  const medal = (i) => ["🥇", "🥈", "🥉"][i] || `${i + 1}.`;
  $("#leaders-table").innerHTML = leaders.length ? `
    <table><tr><th></th><th>who</th><th>bets</th><th>wins</th><th>staked</th><th>net</th></tr>` +
    leaders.map((l, i) => `<tr>
      <td>${medal(i)}</td><td>${esc(l.nickname)}</td>
      <td>${l.bets}</td><td>${l.wins}/${l.settled}</td><td>${l.staked} cr</td>
      <td class="${l.net >= 0 ? "plus" : "minus"}">${l.net >= 0 ? "+" : ""}${l.net} cr</td>
    </tr>`).join("") + "</table>"
    : "<p class='fine'>No settled bets yet — the podium is wide open.</p>";
}

async function loadOpeningOptions() {
  const { openings } = await api("/openings");
  $("#nm-opening").innerHTML = '<option value="">no opening</option>' +
    openings.filter((o) => o.status === "open")
      .map((o) => `<option value="${o.id}">📦 #${o.id} ${esc(o.title)}</option>`).join("");
}

async function createMarket() {
  const outcomes = [...document.querySelectorAll(".outcome-row")].map((r) => ({
    label: r.querySelector(".o-label").value.trim(),
    fixed_odds: parseFloat(r.querySelector(".o-odds").value) || null,
  })).filter((o) => o.label);
  let rconfig = {};
  try { rconfig = JSON.parse($("#nm-rconfig").value || "{}"); }
  catch { toast("resolver config is not valid JSON"); return; }
  const closeRaw = $("#nm-close").value;
  try {
    await api("/markets", { method: "POST", body: {
      title: $("#nm-title").value, description: $("#nm-desc").value,
      mechanism: $("#nm-mech").value, outcomes,
      close_at: closeRaw ? Math.floor(new Date(closeRaw).getTime() / 1000) : null,
      resolver: $("#nm-resolver").value, resolver_config: rconfig,
      opening_id: $("#nm-opening").value ? parseInt($("#nm-opening").value, 10) : null,
    }});
    toast("Market created");
    $("#nm-title").value = ""; $("#nm-desc").value = "";
    loadMarkets();
  } catch (e) { toast(e.message); }
}

/* ---------- pack openings ---------- */
async function apiUpload(path, formData) {
  const r = await fetch("/api" + path, {
    method: "POST", headers: { Authorization: "Bearer " + TOKEN }, body: formData });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

const GAME_ICONS = { pokemon: "⚡", yugioh: "🃏", baseball: "⚾", other: "📦" };
let REC = null; // { openingId, stream, mr, chunks }

function openingControls(o) {
  if (!ME || !ME.is_admin) return "";
  if (o.status === "open") {
    return `<button class="danger" onclick="sealOpening(${o.id})">🔒 Seal betting</button>
      <p class="fine">Sealing closes all linked markets and unlocks the video slot.</p>`;
  }
  if (o.status === "sealed") {
    return `
      <div class="row">
        <button onclick="startRec(${o.id})" id="rec-btn-${o.id}">⏺ Record reveal</button>
        <button class="ghost" onclick="stopRec()" id="stop-btn-${o.id}" disabled>⏹ Stop &amp; upload</button>
      </div>
      <video id="rec-preview-${o.id}" muted playsinline style="display:none"></video>
      <div class="row">
        <input type="file" id="vid-file-${o.id}" accept="video/*">
        <button class="ghost" onclick="uploadVideoFile(${o.id})" style="flex:0 0 auto">Upload file</button>
      </div>`;
  }
  return "";
}

function renderOpening(o) {
  return `
    <div class="card">
      <div class="market-title">${GAME_ICONS[o.game] || "📦"} ${esc(o.title)}</div>
      <div class="market-meta">
        <span class="pill ${o.status === "open" ? "open" : o.status === "revealed" ? "resolved" : "closed"}">${esc(o.status)}</span>
        <span class="pill">${esc(o.game)}</span>
        <span class="pill">${o.markets.length} market${o.markets.length === 1 ? "" : "s"}</span>
      </div>
      ${o.description ? `<div class="fine" style="margin-bottom:8px">${esc(o.description)}</div>` : ""}
      ${o.has_video ? `<video controls preload="metadata" src="/api/openings/${o.id}/video"></video>` : ""}
      ${o.status === "sealed" && !o.has_video ? `<p class="fine">🔒 Betting sealed — reveal video coming.</p>` : ""}
      ${openingControls(o)}
      ${o.markets.map(renderMarket).join("")}
    </div>`;
}

async function loadOpenings() {
  $("#new-opening-card").hidden = !(ME && ME.is_admin);
  const { openings } = await api("/openings");
  $("#openings-list").innerHTML =
    openings.map(renderOpening).join("") || "<p>No pack openings yet.</p>";
}

async function createOpening() {
  try {
    await api("/openings", { method: "POST", body: {
      title: $("#no-title").value, description: $("#no-desc").value,
      game: $("#no-game").value } });
    toast("Opening created — now add markets to it in the Admin tab");
    $("#no-title").value = ""; $("#no-desc").value = "";
    loadOpenings();
  } catch (e) { toast(e.message); }
}

async function sealOpening(id) {
  if (!confirm("Seal betting? All linked markets close and the video slot unlocks.")) return;
  try {
    await api(`/openings/${id}/seal`, { method: "POST" });
    toast("Sealed — record or upload the reveal");
    loadOpenings();
  } catch (e) { toast(e.message); }
}

async function startRec(openingId) {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    const preview = $(`#rec-preview-${openingId}`);
    preview.style.display = "block";
    preview.srcObject = stream;
    preview.play();
    const mr = new MediaRecorder(stream, { mimeType: "video/webm" });
    REC = { openingId, stream, mr, chunks: [] };
    mr.ondataavailable = (e) => e.data.size && REC.chunks.push(e.data);
    mr.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      preview.style.display = "none";
      const blob = new Blob(REC.chunks, { type: "video/webm" });
      await uploadVideoBlob(openingId, blob);
      REC = null;
    };
    mr.start();
    $(`#rec-btn-${openingId}`).disabled = true;
    $(`#stop-btn-${openingId}`).disabled = false;
    toast("Recording… open those packs 🎬");
  } catch (e) { toast("camera unavailable: " + e.message); }
}

function stopRec() {
  if (REC) REC.mr.stop();
}

async function uploadVideoBlob(openingId, blob) {
  const fd = new FormData();
  fd.append("file", blob, "reveal.webm");
  try {
    const r = await apiUpload(`/openings/${openingId}/video`, fd);
    toast(`Reveal uploaded (${(r.bytes / 1e6).toFixed(1)} MB) — resolve the markets!`);
    loadOpenings();
  } catch (e) { toast(e.message); }
}

async function uploadVideoFile(openingId) {
  const input = $(`#vid-file-${openingId}`);
  if (!input.files.length) { toast("choose a video file first"); return; }
  await uploadVideoBlob(openingId, input.files[0]);
}

/* ---------- store ---------- */
async function loadStore() {
  const { items } = await api("/store");
  $("#store-list").innerHTML = items.map((i) => `
    <div class="card store-item">
      ${i.image_url ? `<img class="item-img" src="${esc(i.image_url)}" alt="">`
        : `<div class="emoji">${esc(i.emoji)}</div>`}
      <div class="market-title">${esc(i.name)}</div>
      <div class="fine">${esc(i.description)}</div>
      ${i.source && i.source !== "manual" ? `<span class="pill">via ${esc(i.source)}
        · $${(i.base_price_cents / 100).toFixed(2)} + markup</span>` : ""}
      <div class="price">${i.price} cr</div>
      <div class="stock">${i.stock < 0 ? "unlimited" : i.stock + " left"}</div>
      <button style="margin-top:8px" onclick="redeem(${i.id}, '${esc(i.name)}', ${i.price})">Redeem</button>
    </div>`).join("") || "<p>The store is empty.</p>";
  const { redemptions } = await api("/redemptions");
  $("#redemptions-list").innerHTML = redemptions.map((r) => `
    <div class="line-item"><span>${esc(r.emoji)} ${esc(r.name)}</span>
      <span>${r.price_paid} cr · ${esc(r.status)}</span></div>`).join("")
    || "<p class='fine'>Nothing redeemed yet.</p>";
}

async function redeem(id, name, price) {
  if (!confirm(`Redeem "${name}" for ${price} cr?`)) return;
  try {
    const r = await api(`/store/${id}/redeem`, { method: "POST" });
    toast(`Redeemed! Balance: ${r.balance} cr`);
    loadStore(); loadMe();
  } catch (e) { toast(e.message); }
}

async function createItem() {
  try {
    await api("/admin/items", { method: "POST", body: {
      name: $("#ni-name").value, description: $("#ni-desc").value,
      price: parseInt($("#ni-price").value, 10) || 0,
      stock: parseInt($("#ni-stock").value, 10) ?? -1,
      emoji: $("#ni-emoji").value || "🎁",
    }});
    toast("Item added"); loadStore();
  } catch (e) { toast(e.message); }
}

/* ---------- wallet ---------- */
async function loadWallet() {
  const w = await api("/wallet");
  $("#balance").textContent = w.balance;
  const box = $("#deposit-box");
  let boxHtml = "";
  if (INFO.deposits_enabled) {
    const rates = [`1 ETH = ${INFO.credits_per_eth} cr`].concat(
      Object.entries(INFO.tokens || {}).map(
        ([sym, t]) => `1 ${sym} = ${t.credits_per_token} cr`));
    const assets = ["ETH"].concat(Object.keys(INFO.tokens || {})).join(" or ");
    boxHtml += `
      <p class="fine">Buy credits: send ${esc(assets)} on ${esc(INFO.chain_name)} to the deposit
      address below <b>from your own wallet</b>, then paste the transaction hash.
      Rates: ${esc(rates.join(" · "))}. ${INFO.min_confirmations} confirmations required.</p>
      <div class="addr">${esc(INFO.deposit_address)}</div>
      ${window.ethereum ? `<button class="ghost" style="margin-top:8px"
        onclick="sendDeposit()">🦊 Send ETH deposit with wallet…</button>` : ""}
      <div class="row" style="margin-top:8px">
        <input id="dep-tx" placeholder="0x… transaction hash">
        <button onclick="claimDeposit()" style="flex:0 0 auto">Claim credits</button>
      </div>`;
  }
  if (INFO.monero && INFO.monero.enabled) {
    boxHtml += `
      <p class="fine" style="margin-top:${INFO.deposits_enabled ? 14 : 0}px">
      Or send XMR to the Monero address below, then paste the transaction id
      <b>and its tx secret key</b> (your wallet shows it in the transaction
      details — monero-wallet-cli: <code>get_tx_key</code>). The key proves the
      payment without revealing anything else.
      Rate: 1 XMR = ${INFO.monero.credits_per_xmr} cr.
      ${INFO.monero.min_confirmations} confirmations required.</p>
      <div class="addr">${esc(INFO.monero.address)}</div>
      <div class="row" style="margin-top:8px">
        <input id="xmr-txid" placeholder="transaction id (64 hex)">
        <input id="xmr-key" placeholder="tx secret key (64 hex)">
        <button onclick="claimMoneroDeposit()" style="flex:0 0 auto">Claim</button>
      </div>`;
  }
  box.innerHTML = boxHtml || `<p class="fine">On-chain deposits are not configured yet
      (set <code>deposit_address</code> or <code>monero</code> in data/config.json).
      An admin can grant credits meanwhile.</p>`;
  const { bets } = await api("/bets");
  $("#bets-list").innerHTML = bets.map((b) => {
    const won = b.settled && b.payout > 0;
    const res = b.settled ? (won ? `won ${b.payout} cr` : "lost") : "open";
    return `<div class="line-item"><span>${esc(b.title)} — ${esc(b.outcome_label)}</span>
      <span class="${won ? "plus" : b.settled ? "minus" : ""}">${b.stake} cr · ${res}</span></div>`;
  }).join("") || "<p class='fine'>No bets yet.</p>";
  $("#ledger-list").innerHTML = w.history.map((h) => `
    <div class="line-item">
      <span>${esc(h.kind)}${h.memo ? " · " + esc(h.memo) : ""}</span>
      <span class="${h.delta > 0 ? "plus" : "minus"}">${h.delta > 0 ? "+" : ""}${h.delta} cr</span>
    </div>`).join("") || "<p class='fine'>No activity yet.</p>";
}

async function sendDeposit() {
  // Prefill a transaction for the USER to review and approve in their own
  // wallet. The app never holds keys; MetaMask does the signing and sending.
  const amount = parseFloat(prompt("Amount of ETH to deposit:"));
  if (!amount || amount <= 0) return;
  if (!confirm(`This opens your wallet to send ${amount} ETH to\n` +
    `${INFO.deposit_address}\nYou approve or reject it there.`)) return;
  try {
    const [from] = await window.ethereum.request({ method: "eth_requestAccounts" });
    // integer µETH * 1e12 keeps the wei math exact in BigInt
    const wei = BigInt(Math.round(amount * 1e6)) * 1000000000000n;
    const hash = await window.ethereum.request({
      method: "eth_sendTransaction",
      params: [{ from, to: INFO.deposit_address, value: "0x" + wei.toString(16) }],
    });
    $("#dep-tx").value = hash;
    toast(`Sent. Once it has ${INFO.min_confirmations} confirmations, hit Claim credits.`);
  } catch (e) { toast(e.message); }
}

async function claimMoneroDeposit() {
  try {
    const r = await api("/deposit", { method: "POST",
      body: { tx_hash: $("#xmr-txid").value, tx_key: $("#xmr-key").value } });
    toast(`Verified via wallet-rpc: +${r.credits} cr`);
    $("#xmr-txid").value = ""; $("#xmr-key").value = "";
    loadWallet(); loadMe();
  } catch (e) { toast(e.message); }
}

async function claimDeposit() {
  try {
    const r = await api("/deposit", { method: "POST", body: { tx_hash: $("#dep-tx").value } });
    toast(`Verified on-chain: +${r.credits} cr`);
    $("#dep-tx").value = "";
    loadWallet(); loadMe();
  } catch (e) { toast(e.message); }
}

/* ---------- catalog admin ---------- */
function catBody() {
  return { source: $("#cat-source").value, source_id: $("#cat-sku").value.trim(),
    markup_bps: $("#cat-markup").value ? parseInt($("#cat-markup").value, 10) : null };
}

async function catalogPreview() {
  try {
    const p = await api("/admin/catalog/preview", { method: "POST", body: catBody() });
    $("#cat-preview").innerHTML = `${esc(p.emoji)} <b>${esc(p.name)}</b> —
      $${(p.price_cents / 100).toFixed(2)} + ${p.markup_bps} bps →
      <b>${p.credits} cr</b> ${p.in_stock ? "" : "· ⚠️ out of stock at source"}`;
  } catch (e) { toast(e.message); }
}

async function catalogAdd() {
  try {
    const r = await api("/admin/catalog/add", { method: "POST", body: catBody() });
    toast(`Added "${r.name}" at ${r.credits} cr`);
    $("#cat-sku").value = ""; $("#cat-preview").innerHTML = "";
    loadAdmin(); loadStore();
  } catch (e) { toast(e.message); }
}

async function catalogSyncNow() {
  try {
    const r = await api("/admin/catalog/sync", { method: "POST" });
    toast("Synced: " + (r.synced.map((s) => `#${s.id} ${s.action}`).join(", ") || "no catalog items"));
    loadAdmin(); loadStore();
  } catch (e) { toast(e.message); }
}

async function reactivateItem(id) {
  try {
    const r = await api(`/admin/items/${id}/activate`, { method: "POST" });
    toast(`Item ${id}: ${r.action}`);
    loadAdmin(); loadStore();
  } catch (e) { toast(e.message); }
}

/* ---------- admin ---------- */
async function loadAdmin() {
  const o = await api("/admin/overview");
  $("#admin-users").innerHTML = `<table><tr><th>id</th><th>who</th><th>balance</th><th></th></tr>` +
    o.users.map((u) => `<tr><td>${u.id}</td>
      <td>${esc(u.nickname)}${u.is_admin ? " ⭐" : ""}${u.address ? `<div class="addr">${esc(u.address)}</div>` : ""}</td>
      <td>${u.balance} cr</td>
      <td><button class="ghost" onclick="grantCredits(${u.id})">grant</button></td></tr>`).join("") +
    `</table><p class="fine">House balance: ${o.house_balance} cr</p>`;
  $("#catalog-table").innerHTML = (o.catalog_items.length ? `
    <table><tr><th>id</th><th>item</th><th>source</th><th>base</th><th>cr</th><th>status</th><th></th></tr>` +
    o.catalog_items.map((c) => `<tr><td>${c.id}</td>
      <td>${esc(c.emoji)} ${esc(c.name)}</td>
      <td>${esc(c.source)}:${esc(c.source_id)}</td>
      <td>$${((c.base_price_cents || 0) / 100).toFixed(2)}</td>
      <td>${c.price}</td>
      <td>${c.active ? "active" : `<span style="color:var(--bad)">${esc(c.suspend_reason || "suspended")}</span>`}</td>
      <td>${c.active ? "" : `<button class="ghost" onclick="reactivateItem(${c.id})">reactivate</button>`}</td>
    </tr>`).join("") + "</table>" : "") +
    `<button class="ghost" style="margin-top:8px" onclick="catalogSyncNow()">Sync catalog now</button>`;
  $("#admin-redemptions").innerHTML = o.pending_redemptions.map((r) => `
    <div class="line-item"><span>${esc(r.emoji)} ${esc(r.name)} → ${esc(r.nickname)}</span>
      <button class="ghost" onclick="fulfill(${r.id})">mark fulfilled</button></div>`).join("")
    || "<p class='fine'>None pending.</p>";
}

async function grantCredits(userId) {
  const amount = parseInt(prompt("Grant how many credits?"), 10);
  if (!amount) return;
  try {
    await api("/admin/grant", { method: "POST", body: { user_id: userId, amount } });
    toast("Granted"); loadAdmin();
  } catch (e) { toast(e.message); }
}

async function fulfill(rid) {
  await api(`/admin/redemptions/${rid}/fulfill`, { method: "POST" });
  loadAdmin();
}

/* ---------- boot ---------- */
function refresh(tab) {
  if (tab === "markets") loadMarkets();
  if (tab === "openings") loadOpenings();
  if (tab === "store") loadStore();
  if (tab === "leaders") loadLeaders();
  if (tab === "wallet") loadWallet();
  if (tab === "admin") { loadAdmin(); loadOpeningOptions(); loadPresets(); }
}

async function loadMe() {
  const r = await api("/me");
  ME = r.user;
  $("#who").innerHTML = `<span>${esc(ME.nickname)}</span><b>${r.balance} cr</b>
    <button class="ghost" onclick="logout()" style="padding:4px 10px">out</button>`;
  $("#admin-tab").hidden = !ME.is_admin;
}

async function boot() {
  INFO = await api("/info");
  if (!INFO.dev_login) $("#dev-login-box").style.display = "none";
  if (!TOKEN) { $("#login").style.display = "flex"; return; }
  try {
    await loadMe();
    $("#login").style.display = "none";
    loadMarkets();
  } catch {
    localStorage.removeItem("er_token"); TOKEN = "";
    $("#login").style.display = "flex";
  }
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
boot();
