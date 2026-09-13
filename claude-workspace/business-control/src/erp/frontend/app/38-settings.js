// ---------- settings: how this app reads to you ----------
/* Accessibility and the few preferences that belong to the person, not
   the business: text size, contrast, motion, underlined links, and how
   the rail starts. Saved on this device, applied to <html> before the
   first paint on every visit, the same four switches the storefront
   offers its shoppers — so a member of staff who needs larger text gets
   it on every surface they use. */
const OPS_A11Y_KEY = "bc_a11y";
let OPS_A11Y = { text: "", contrast: false, motion: false, links: false };
try { OPS_A11Y = { ...OPS_A11Y, ...JSON.parse(localStorage.getItem(OPS_A11Y_KEY) || "{}") }; } catch (e) { /* fresh */ }

function applyOpsA11y() {
  const r = document.documentElement;
  r.classList.remove("a11y-text-lg", "a11y-text-xl");
  if (OPS_A11Y.text) r.classList.add("a11y-text-" + OPS_A11Y.text);
  r.classList.toggle("a11y-contrast", !!OPS_A11Y.contrast);
  r.classList.toggle("a11y-motion", !!OPS_A11Y.motion);
  r.classList.toggle("a11y-links", !!OPS_A11Y.links);
  try { localStorage.setItem(OPS_A11Y_KEY, JSON.stringify(OPS_A11Y)); } catch (e) { /* private mode */ }
}
applyOpsA11y();

async function renderSettings() {
  const folded = localStorage.getItem("bc_rail_folded") === "1";
  const seg = (v, label) => `<button class="btn alt sm${OPS_A11Y.text === v ? " on" : ""}" data-a11ytext="${v}">${label}</button>`;
  const sw = (id, key, label, sub) => `<label class="set-row">
    <span><b>${label}</b>${sub ? `<br><span class="dim">${sub}</span>` : ""}</span>
    <input type="checkbox" id="${id}" ${OPS_A11Y[key] ? "checked" : ""}></label>`;
  view().innerHTML = `
    <div class="page-head">
      <div><h2>Settings</h2>
        <p class="dim">How this app reads to you. Saved on this device, applied before
          the first paint, and the same switches the storefront offers its shoppers.
          The business's own settings live on ${S.user && S.user.is_admin ? '<a id="set-admin">Admin</a> and ' : ""}
          <a id="set-profile">your profile</a>.</p></div>
      <div class="top-actions"><button class="btn alt" id="set-reset">Reset all</button></div>
    </div>
    <div class="card set-card">
      <h3>Accessibility</h3>
      <div class="set-row"><span><b>Text size</b><br><span class="dim">everything scales with it</span></span>
        <span class="set-seg">${seg("", "A")}${seg("lg", "A+")}${seg("xl", "A++")}</span></div>
      ${sw("set-contrast", "contrast", "High contrast", "darker text, stronger lines")}
      ${sw("set-motion", "motion", "Reduce motion", "no animations or transitions")}
      ${sw("set-links", "links", "Underline links", "so a link is a link without colour")}
    </div>
    <div class="card set-card">
      <h3>The rail</h3>
      <label class="set-row"><span><b>Start folded</b><br><span class="dim">icons only until you widen it; the width you drag to is remembered</span></span>
        <input type="checkbox" id="set-folded" ${folded ? "checked" : ""}></label>
    </div>
    <div class="card set-card">
      <h3>This device</h3>
      <p class="dim">Signed in as <b>${esc(S.user ? S.user.name : "nobody")}</b>. Preferences here follow the
        device, not the account: another person on this screen gets their own, and you get yours on
        another screen once you set them there.</p>
      <p class="dim">Language and currency for shoppers are set on the storefront's own preferences panel
        and, for the business, on Store admin → Currency &amp; language.</p>
    </div>`;
  view().querySelectorAll("[data-a11ytext]").forEach((b) => b.onclick = () => { OPS_A11Y.text = b.dataset.a11ytext; applyOpsA11y(); renderSettings(); });
  $("#set-contrast").onchange = (e) => { OPS_A11Y.contrast = e.target.checked; applyOpsA11y(); };
  $("#set-motion").onchange = (e) => { OPS_A11Y.motion = e.target.checked; applyOpsA11y(); };
  $("#set-links").onchange = (e) => { OPS_A11Y.links = e.target.checked; applyOpsA11y(); };
  $("#set-folded").onchange = (e) => { localStorage.setItem("bc_rail_folded", e.target.checked ? "1" : ""); toast("applies on the next load"); };
  $("#set-reset").onclick = () => { OPS_A11Y = { text: "", contrast: false, motion: false, links: false }; applyOpsA11y(); localStorage.removeItem("bc_rail_folded"); localStorage.removeItem("bc_rail_w"); renderSettings(); };
  if ($("#set-admin")) $("#set-admin").onclick = () => { S.tab = "admin"; render(); };
  $("#set-profile").onclick = () => { S.tab = "profile"; render(); };
}
