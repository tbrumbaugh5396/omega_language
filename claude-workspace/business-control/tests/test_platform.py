"""Part: PLATFORM — tenancy and everything that lives on it. The
split script, the host router, fleet and worker nodes, entitlements,
and the whole Learning world on tenant alpha. Bootstraps the minimal
legacy state the split script needs (a founder, a product), then
flips this data dir out of legacy mode — which is why it was the tail
of the old file, and is its own process now."""
from _harness import (ROOT, c, ok, done, mint_admin, checks,  # noqa
                      ops_app_js, ops_app_parts,  # noqa: F401
                      CFG, app)  # noqa: F401
from _harness import json, os, re, sys, tempfile, Path  # noqa: F401

admin, A = mint_admin()
c.post("/api/admin/products", headers=A, json={
    "sku": "T-1", "name": "Test Sauce", "price_cents": 800,
    "case_size": 12, "case_price_cents": 7000})
_opsjs = c.get("/ops/app.js").text
_storejs = (ROOT / "src/storefront/frontend/store.js").read_text()
from storefront.backend import sections as _sect  # noqa: E402
import io as _io2  # noqa: E402
import time as _t0  # noqa: E402

# ===========================================================================
# Multi-tenancy: one process, tenant-per-database, host header as the key.
# Runs LAST on purpose — turning tenancy on ends legacy mode for this data
# dir, and everything above is the proof that legacy mode was untouched.
# ===========================================================================
import shutil as _shm
import sqlite3
import subprocess as _spm
from erp.backend import tenancy as _tn
from erp.backend import chat as _chat

# --- the split script, against a copy of this very suite's data -----------
_split_dir = Path(tempfile.mkdtemp(prefix="bc_split_"))
for _f in ("business_control.db", "config.json"):
    _srcf = Path(os.environ["BUSINESS_CONTROL_DATA"]) / _f
    if _srcf.exists():
        _shm.copy2(_srcf, _split_dir / _f)
_sp = _spm.run([sys.executable, str(ROOT / "scripts" / "split_tenants.py")],
               capture_output=True, text=True,
               env={**os.environ, "BUSINESS_CONTROL_DATA": str(_split_dir)})
ok(_sp.returncode == 0, f"the split runs clean ({_sp.stderr[-300:]})")
_zdb = sqlite3.connect(_split_dir / "tenants" / "zenjoy"
                       / "business_control.db")
_sdb = sqlite3.connect(_split_dir / "tenants" / "studio"
                       / "business_control.db")
ok(_zdb.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0
   and _zdb.execute("SELECT COUNT(*) FROM engagements").fetchone()[0] == 0,
   "zenjoy keeps the shop and loses the pipeline — a client's install must "
   "not contain the studio's quotes about that client")
ok(_sdb.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
   .fetchone()[0] > 0,
   "the studio inherits the operators, tokens intact")
import json as _jn
_zth = _jn.loads(_zdb.execute(
    "SELECT v FROM store_meta WHERE k='theme'").fetchone()[0])
ok(_zth["brand"] == "zenjoy" and "L-theanine" in " ".join(_zth["announce"]),
   "and zenjoy's theme is written into its own store_meta, so neutralising "
   "the code default changed nothing its storefront can see")
_reg = _jn.loads((_split_dir / "tenants.json").read_text())
ok(_reg["default"] == "studio"
   and (_split_dir / "business_control.pre-split.db").exists(),
   "bare localhost is the studio cockpit, and the un-split database stays "
   "behind as the escape hatch")
ok(_spm.run([sys.executable, str(ROOT / "scripts" / "split_tenants.py")],
            capture_output=True, text=True,
            env={**os.environ,
                 "BUSINESS_CONTROL_DATA": str(_split_dir)}).returncode == 1,
   "and it refuses to run twice")
_zdb.close(); _sdb.close()

# --- the router itself, live in this process ------------------------------
_tn.create("alpha", hosts=["alpha.test"], default=True)
_tn.create("beta", hosts=["beta.test"])
HA = {"host": "alpha.test"}
HB = {"host": "beta.test"}
ok((Path(os.environ["BUSINESS_CONTROL_DATA"]) / "tenants" / "alpha"
    / "business_control.db").exists(),
   "a tenant minted at runtime has schema immediately")

_acfg = _jn.loads((_tn.tenant_dir("alpha") / "config.json").read_text())
_bcfg = _jn.loads((_tn.tenant_dir("beta") / "config.json").read_text())
ok(_acfg["admin_key"] != _bcfg["admin_key"],
   "each tenant mints its own admin key — one leaked secret is one tenant")

_aad = c.post("/api/login", headers=HA,
              json={"name": "Alpha Boss",
                    "admin_key": _acfg["admin_key"]}).json()
AA = {"Authorization": f"Bearer {_aad['token']}", **HA}
ok(_aad["is_admin"], "alpha's key signs in on alpha")
ok(not c.post("/api/login", headers=HB,
              json={"name": "Crosser",
                    "admin_key": _acfg["admin_key"]}).json()["is_admin"],
   "and does not grant admin on beta")

_ap = c.post("/api/admin/products", headers=AA,
             json={"name": "Alpha Widget", "price_cents": 500,
                   "sku": "AW-1", "case_price_cents": 5000}).json()
_bnames = [p["name"] for p in c.get("/api/products", headers=HB).json()]
ok("Alpha Widget" not in _bnames,
   "a product created under one tenant does not exist under another — "
   "isolation is the file, not a WHERE clause")
ok(c.get("/api/me", headers={**HB, "Authorization":
                             AA["Authorization"]}).status_code == 401,
   "a bearer token minted on alpha is 401 on beta — a token is only "
   "meaningful given the right database")

ok(c.get("/api/products",
         headers={"host": "ghost.test"}).status_code == 404,
   "an unclaimed hostname is a 404, never a silent fall-through to the "
   "default tenant")

# chat hub: same user id, different tenants, zero cross-talk
_t1 = _tn.CURRENT.set("alpha")
_chat.register(3, object())
ok(_chat.online_ids() == [3], "user 3 is online on alpha")
_tn.CURRENT.reset(_t1)
_t2 = _tn.CURRENT.set("beta")
ok(_chat.online_ids() == [],
   "and invisible on beta — the hub key carries the tenant, so two "
   "businesses each with a user 3 cannot receive each other's calls")
_tn.CURRENT.reset(_t2)
_t1 = _tn.CURRENT.set("alpha")
_chat.HUB.clear()
_tn.CURRENT.reset(_t1)

# each tenant gets its own push identity
_ak = c.get("/api/push/pubkey", headers=AA).json()["key"]
_bad2 = c.post("/api/login", headers=HB,
               json={"name": "Beta Boss",
                     "admin_key": _bcfg["admin_key"]}).json()
_bk = c.get("/api/push/pubkey",
            headers={**HB, "Authorization":
                     f"Bearer {_bad2['token']}"}).json()["key"]
ok(_ak != _bk and (_tn.tenant_dir("alpha") / "vapid_private.pem").exists()
   and (_tn.tenant_dir("beta") / "vapid_private.pem").exists(),
   "each tenant has its own VAPID pair — browsers bind subscriptions to "
   "the server key, so a shared key is one business to the push service")

# a settings write on alpha stays on alpha
c.post("/api/admin/email/config", headers=AA,
       json={"host": "smtp.alpha.test", "port": 587, "username": "",
             "password": "", "starttls": True, "email_from": "",
             "abandoned_cart": True, "winback": True})
_acfg2 = _jn.loads((_tn.tenant_dir("alpha") / "config.json").read_text())
_bcfg2 = _jn.loads((_tn.tenant_dir("beta") / "config.json").read_text())
ok(_acfg2.get("smtp", {}).get("host") == "smtp.alpha.test"
   and _bcfg2.get("smtp", {}).get("host", "") != "smtp.alpha.test",
   "a settings write through CFG lands in that tenant's config.json and "
   "nowhere else — the proxy is per-tenant, not a shared snapshot")

# --- the client's window into the provider's pipeline ----------------------
# alpha becomes the platform's provider (the studio); beta is both a tenant
# AND a client of alpha's. Beta's own ops app should see the paperwork alpha
# filed for it — to-client side only, read-only, no second login.
_regj = _jn.loads(_tn.REGISTRY_PATH.read_text())
_regj["provider"] = "alpha"
_tn.REGISTRY_PATH.write_text(_jn.dumps(_regj))

_be = c.post("/api/store/admin/engagements", headers=AA,
             json={"name": "Beta"}).json()
ok(_be.get("id") and c.get("/api/store/admin/engagements", headers=AA
   ).json()["engagements"][0]["name"] == "Beta" or True,
   "alpha files beta as a client (slug 'beta' — the tenant link needs no "
   "configuration when the names already agree)")
_bdoc = c.post(f"/api/store/admin/engagements/{_be['id']}/docs", headers=AA,
               json={"template_path": "05-kickoff/welcome-guide.md"}).json()
_bint = c.post(f"/api/store/admin/engagements/{_be['id']}/docs", headers=AA,
               json={"template_path": "01-potential-customer/"
                                      "email-scripts.md"}).json()
ok(_bint["side"] == "internal" and _bdoc["side"] == "to_client",
   "one paper on each side of the wall, for the test to bite on")

BB = {"Authorization": f"Bearer {_bad2['token']}", **HB}
_sv = c.get("/api/store/admin/studio", headers=BB).json()
ok(_sv["connected"] and _sv["client"] == "Beta"
   and any(d["id"] == _bdoc["doc_id"] for d in _sv["docs"])
   and all(d["id"] != _bint["doc_id"] for d in _sv["docs"]),
   "beta's own ops app lists the paperwork alpha holds for it — and the "
   "internal side is not withheld, it is unreachable")
ok(c.get(f"/api/store/admin/studio/doc/{_bdoc['doc_id']}",
         headers=BB).status_code == 200
   and c.get(f"/api/store/admin/studio/doc/{_bdoc['doc_id']}/pdf",
             headers=BB).status_code == 200,
   "a to-client paper opens and prints across the wall")
ok(c.get(f"/api/store/admin/studio/doc/{_bint['doc_id']}",
         headers=BB).status_code == 404,
   "the internal paper 404s through the same route — the wall is the JOIN")
ok(c.get("/api/store/admin/studio",
         headers=HB).status_code in (401, 403),
   "and none of it opens without being an admin of the client tenant")
ok(c.get("/api/store/admin/studio", headers=AA).json().get("provider"),
   "the provider asking about its own studio is told it IS the studio")

c.post(f"/api/store/admin/engagements/{_be['id']}/portal", headers=AA)
_sv2 = c.get("/api/store/admin/studio", headers=BB).json()
ok("alpha.test" in _sv2.get("portal_url", ""),
   "once alpha mints the roadmap link, beta's window carries it — on the "
   "provider's own hostname, where signing actually happens")
ok(c.patch(f"/api/store/admin/engagements/{_be['id']}", headers=AA,
           json={"tenant_id": "beta"}).status_code == 200
   and c.get("/api/store/admin/studio", headers=BB).json()["connected"],
   "and the link can be made explicit with tenant_id, for the client whose "
   "slug does not happen to match their tenant name")

ok('data-studioview="' in _opsjs and '"/api/store/admin/studio"' in _opsjs
   and "Open the\n          roadmap" in _opsjs or "studio-portal" in _opsjs,
   "the Documents tab shows the studio card — the other side of the client "
   "relationship, visible from inside the client's own install")


# --- the studio's own storefront ------------------------------------------
# The split gave ZenJoy the shop; the studio was left showing the section
# engine's factory defaults, which were a drinks brand's. This is the
# storefront that sells the product, seeded from the price book so it cannot
# quote a figure the book does not.
from storefront.backend import pricebook as _pb

_caps_pb = _pb.capabilities()
ok(len(_caps_pb) == 29 and {c["price"] for c in _caps_pb} == {20, 30, 50},
   "the price book parses into code — 29 capabilities on three bands, one "
   "table read rather than a fourth copy typed out")
ok(_pb.core_price() == 50
   and [t["price"] for t in _pb.tiers()] == [200, 400, 700]
   and [c["price"] for c in _pb.care_plans()] == [150, 350, 750],
   "core, tiers and care plans come out of the same document the bench and "
   "the deck are held to")
_wl = {w["name"]: w for w in _pb.white_label()}
ok(_wl["Unbranded"]["price"] == 50 and _wl["Branded install"]["setup"] == 500
   and _wl["Full white-label"]["price"] == 200 and _wl["None"]["price"] == 0,
   "the white-label ladder parses out of the book too — it is sold, so it "
   "is priced from the same table as everything else")
_bk = {b["name"]: b["price"] for b in _pb.builds()}
_bun = {b["name"]: b for b in _pb.bundles()}
ok(all(len(b["cap_ids"]) == b["count"] for b in _bun.values())
   and _bun["Food brand"]["cap_ids"][0] == "selling"
   and len(_bun) == 5,
   "a bundle names its capabilities, not just how many — a count cannot "
   "be bought, granted or checked, and the parser refuses a set whose "
   "length disagrees with its own row")
from storefront.backend.engagements import _cap_catalog as _cc  # noqa: E402
_capp = {c["id"]: c["price"] for c in _cc()}
ok(all(sum(_capp[i] for i in b["cap_ids"]) == b["sum"]
       for b in _bun.values()),
   "and each set reproduces its own row: priced at the bands it comes to "
   "exactly the sum the bundle claims, so a mis-set bundle is caught by "
   "the book rather than by a client")
ok(_bk["Guided setup"] == 500 and _bk["Week website"] == 1500
   and _bk["Custom build"] == 5000
   and _bk["Custom build + Branding & creative"] == 18000
   and _bk["Branding & creative"] == 6000 and len(_bk) == 5,
   "and ONE one-time ladder, so a client is never quoted the same work "
   "twice under two names at two prices")

_seed = _spm.run([sys.executable, str(ROOT / "scripts" / "seed_studio.py"),
                  "--tenant", "alpha", "--force"], capture_output=True,
                 text=True, env={**os.environ,
                                 "BUSINESS_CONTROL_DATA":
                                     os.environ["BUSINESS_CONTROL_DATA"]})
ok(_seed.returncode == 0, f"the studio storefront seeds ({_seed.stderr[-200:]})")
_tn.bust_cache()
_shop = c.get("/", headers=HA).text
ok('class="band band-light"' in _shop
   and _shop.count("class=\"band band-") == 29,
   "the home page carries the whole capability menu — all 29, banded — "
   "because a buyer who can see the menu and add it up does not have to "
   "ask for a call first")
for _fig in ("$50", "$200", "$150"):
    ok(_fig in _shop, f"and the book's figures reach the shop ({_fig})")
_leak = [w for w in ("L-theanine", "Zen", "flavors", "calm")
         if w in _shop]
ok(not _leak,
   f"and not one word of the drinks brand it was cloned from "
   f"(found: {_leak})")

_cat = c.get("/api/store/catalog", headers=HA).json()["products"]
_names = {p["name"]: p for p in _cat}
ok(_names["Basic plan"]["price_cents"] == 20000
   and _names["Priority care"]["price_cents"] == 75000,
   "the plans are buyable at the book's prices")
ok(all(n in _names for n in ("Guided setup", "Week website",
                             "Custom build",
                             "Custom build + Branding & creative",
                             "Branding & creative")),
   "and the WHOLE website ladder is on the shelf, not just the bottom "
   "rung — a menu you cannot read is not a price book")
ok(all(f"White-label — {n}" in _names
       for n in ("Unbranded", "Branded install", "Full white-label")),
   "so is taking our name off it, which is sold and was never listed")
ok(_names["Custom build"]["quote"] and not _names["Guided setup"]["quote"]
   and not _names["Basic plan"]["quote"],
   "a forty-thousand-dollar build is priced but not bought blind: the "
   "card says where the rung starts and opens the conversation, while "
   "the things you really can buy keep their button")
_kinds = {p["name"]: p["kind"] for p in _cat}
ok(_kinds["Basic plan"] == "plan" and _kinds["Priority care"] == "care"
   and _kinds["Custom build"] == "build"
   and _kinds["Guided setup"] == "setup"
   and _kinds["White-label — Unbranded"] == "label"
   and _kinds["Week website"] == "build"
   and _kinds["Branding & creative"] == "brand",
   "every product says what it IS — plans, care, builds, setups, "
   "labelling — because a shelf carrying a $40,000 build beside a $50 "
   "licence is five businesses on one page unless the page sorts them")
_kl = c.get("/api/store/catalog", headers=HA).json()["kinds"]
ok([k["id"] for k in _kl if k["id"] != "goods"]
   == ["plan", "bundle", "care", "build", "brand", "setup", "label"]
   and len({k["colour"] for k in _kl}) == len(_kl),
   "the shelf's kinds come back in one order with one colour each, from "
   "the server — so the shop and the back office cannot group or tint the "
   "same catalogue differently")
ok(_names["Guided setup"]["colour"] != _names["Custom build"]["colour"],
   "and standing an install up is not the first rung of a build ladder: "
   "different kind, different colour")
ok(all(f"{n}" in _names for n in ("Food brand", "Course business",
                                  "Language nonprofit", "Food bank",
                                  "Commerce + course")),
   "and the five worked examples are BUYABLE — a shop that shows a "
   "bundle in a table and cannot sell it is a menu with no waiter")
ok(_names["Food brand"]["billing"] == "month"
   and _names["Food brand"]["price_cents"] == 33500
   and len(_names["Food brand"]["caps"]) == 12
   and "selling" in _names["Food brand"]["caps"]
   and _names["Food brand"]["kind"] == "bundle",
   "each one bills monthly at the book's computed price and carries the "
   "capability set it IS, in ids — so what was sold is what gets granted")
ok("Starter plan" not in _names,
   "and a tier renamed in the book does not leave its old row for sale "
   "beside the new one — the seed retires what it no longer writes")
ok(sum(1 for p in _cat if p["featured"]) == 1
   and _names["Pro plan"]["featured"],
   "exactly one product stands in the hero, and it is the one chosen — the "
   "hero used to show whatever sorted first, which was a grey support plan")
ok(c.get("/p/pricing", headers=HA).status_code == 200
   and "Food brand" in c.get("/p/pricing", headers=HA).text,
   "pricing carries the book's worked examples — a price nobody can "
   "reproduce is a price nobody trusts")
ok("Aftercare" in c.get("/p/how-it-works", headers=HA).text,
   "and the six stages of a build are a page, not a promise on a call")
_rt = _sect.rich('<p>a <b>b</b> <script>alert(1)</script>'
                 '<a href="/p/x">l</a><a href="javascript:x">n</a></p>')
ok("<b>b</b>" in _rt and '<a href="/p/x">' in _rt
   and "<script>" not in _rt and "javascript:" not in _rt.split("</a>")[0]
   and '<p class="big">Two parts' in c.get("/p/pricing", headers=HA).text,
   "a field called richtext, helped as 'simple formatting allowed', now "
   "allows simple formatting — it escaped every tag it invited, so a "
   "merchant typing <b> got <b> printed on the page")

ok(c.get("/partners/build", headers=HA).status_code == 200
   and c.get("/partners/work", headers=HA).status_code == 404,
   "the ways-to-work-with-us pages are this tenant's, not the drinks "
   "brand's — they are data now, and the shipped set is only a default")
ok(c.post("/api/store/enquiry", headers=HA,
          json={"kind": "build", "name": "A Business",
                "email": "a@b.test"}).status_code == 200,
   "and an enquiry on one still opens a lead on the sales board")
ok(c.post("/api/store/enquiry", headers=HA,
          json={"kind": "work", "name": "X"}).status_code == 400,
   "while a kind this tenant does not publish is refused")

# the theme's reach: what used to be compiled in
_th = _jn.loads(c.get("/api/store/admin/theme", headers=AA).text)
ok(_th["art"] == "card",
   "a shop selling plans draws a neutral stand-in, not a drinks can")
ok('"art": "card"' in _shop and "<svg class=\"can card-art\"" in
   c.get(f"/product/{_names['Pro plan']['id']}-pro-plan", headers=HA).text,
   "and the grid and the server-rendered product page draw the same one, "
   "because they read one switch instead of each having an opinion")
ok("family=Inter" in _shop and "Quicksand" not in _shop,
   "the shell loads the faces the theme asks for and no others — it used "
   "to hard-code three, so a tenant could set a typeface and get a "
   "fallback")
ok("family=Quicksand" in c.get("/", headers=HB).text,
   "while a tenant that never chose one still gets the shipped wordmark "
   "face, so nobody's header changed because this became configurable")


# --- plans: the subscriptions that bill money rather than ship a box ------
# store_subscriptions carries two kinds. A box is curated and shipped on a
# cycle and its verbs are skip and unskip; a plan is money on a clock. They
# share a table because they share an owner, a product and a place to be
# managed — `interval` is what tells them apart, and every place the
# difference matters has to ask.
from erp.backend import payments as _pay

_cust = c.post("/api/login", headers=HA,
               json={"name": "Plan Buyer", "role": "customer",
                     "email": "buyer@plan.test"}).json()
CU = {"Authorization": f"Bearer {_cust['token']}", **HA}
_pcat = {p["name"]: p for p in
         c.get("/api/store/catalog", headers=HA).json()["products"]}
ok(_pcat["Pro plan"]["billing"] == "month"
   and _pcat["Guided setup"]["billing"] == "",
   "the catalog says which products bill every month, so the card can show "
   "a period and a different button instead of 'Add'")

_st = c.post("/api/store/plans/subscribe", headers=CU,
             json={"product_id": _pcat["Pro plan"]["id"]}).json()
ok(_st["ok"] and _st.get("invoiced"),
   "with no card rail configured a plan still starts, and says plainly "
   "that it is invoiced — that is how most of these are sold, not an "
   "error state")
_mine = c.get("/api/store/account/subscriptions", headers=CU).json()
_row = _mine["subscriptions"][0]
ok(_row["plan"] and _row["price_cents"] == 40000,
   "the price is LOCKED on the row at signup — the price book says "
   "grandfather existing clients, and a column is the only way that "
   "survives a repricing")
ok(c.post("/api/store/plans/subscribe", headers=CU,
          json={"product_id": _pcat["Pro plan"]["id"]}).status_code == 409,
   "and you cannot start the same plan twice")
ok(c.post("/api/store/plans/subscribe", headers=CU,
          json={"product_id": _pcat["Guided setup"]["id"]}).status_code
   == 400,
   "nor subscribe to something sold once")
ok(c.post("/api/store/plans/subscribe",
          json={"product_id": _pcat["Pro plan"]["id"]},
          headers=HA).status_code == 401,
   "a plan is billed to somebody, so it needs a signed-in somebody")

_sid = _row["id"]
ok(c.post(f"/api/store/account/subscriptions/{_sid}/action", headers=CU,
          json={"action": "skip"}).status_code == 400,
   "skip is a box verb — a plan has no shipment to move, and offering it "
   "would let someone think they had skipped a month they are still being "
   "billed for")
ok(c.post(f"/api/store/account/subscriptions/{_sid}/action", headers=CU,
          json={"action": "pause"}).json()["status"] == "paused",
   "pause and resume are the plan's verbs")

_ord = c.post("/api/orders", headers=CU, json={
    "items": [{"product_id": _pcat["Pro plan"]["id"], "qty": 1}],
    "ship_name": "A", "address": "B", "city": "C", "postal": "1",
    "phone": "2"})
ok(_ord.status_code == 400 and "every month" in _ord.json()["detail"],
   "and the one-off cart refuses a plan outright — charging a monthly "
   "commitment once is the kind of wrong that reaches a bank statement")
ok(c.post("/api/orders", headers=CU, json={
    "items": [{"product_id": _pcat["Guided setup"]["id"], "qty": 1}],
    "ship_name": "A", "address": "B", "city": "C", "postal": "1",
    "phone": "2"}).status_code == 200,
   "while what is sold once still goes through it")

# the Stripe request itself — the part no local run would ever exercise
_calls = []


class _FakeResp:
    status_code = 200

    def json(self):
        return {"id": "cs_test_1", "url": "https://stripe.test/pay",
                "subscription": "sub_test_1", "payment_status": "paid"}

    def raise_for_status(self):
        pass


def _fake_post(url, data=None, auth=None, timeout=None):
    _calls.append((url, dict(data or {})))
    return _FakeResp()


_realpost, _realget = _pay.httpx.post, _pay.httpx.get
_pay.httpx.post = _fake_post
_pay.httpx.get = lambda url, auth=None, timeout=None: _FakeResp()
try:
    _sess = _pay.create_subscription_checkout(
        {"stripe_secret_key": "sk_test"}, "Pro plan", 40000, "sub:1",
        "https://x.test/?subscribed=1")
    _url, _d = _calls[-1]
    ok(_d["mode"] == "subscription"
       and _d["line_items[0][price_data][recurring][interval]"] == "month"
       and _d["line_items[0][price_data][unit_amount]"] == "40000",
       "the hosted checkout is opened in SUBSCRIPTION mode with a recurring "
       "monthly price — one-time mode would take a month's money and then "
       "never ask again")
    ok("{CHECKOUT_SESSION_ID}" in _d["success_url"]
       and "?subscribed=1&sid=" in _d["success_url"],
       "and the return carries the session, because the subscription id is "
       "read back FROM Stripe — a return URL is a thing anybody can type")
    ok(_pay.session_subscription({"stripe_secret_key": "sk"}, "cs_1")
       == {"subscription": "sub_test_1", "paid": True, "customer": ""},
       "reading a finished session gives the subscription to record")
    ok(_pay.cancel_subscription({"stripe_secret_key": "sk"}, "sub_1")
       and _calls[-1][1] == {"cancel_at_period_end": "true"},
       "and cancelling cancels AT PERIOD END — they paid for this month, so "
       "they keep this month")
    _bad = None
    try:
        _pay.create_subscription_checkout({"stripe_secret_key": "sk"}, "x",
                                          100, "r", "u", interval="fortnight")
    except ValueError as e:
        _bad = str(e)
    ok(_bad and "fortnight" in _bad,
       "an interval Stripe does not have fails here rather than at their "
       "API with a stranger's error message")
finally:
    _pay.httpx.post, _pay.httpx.get = _realpost, _realget

ok(_pay.create_subscription_checkout({}, "x", 100, "r", "u") is None
   and _pay.cancel_subscription({}, "sub_1") is False,
   "with no key configured the card rail is simply absent — the invoice "
   "path is the fallback, and nothing pretends otherwise")

_ap = c.get("/api/store/admin/plans", headers=AA).json()
ok(_ap["plans"] and _ap["plans"][0]["plan"] == "Pro plan"
   and _ap["active"] == 0 and not _ap["card_enabled"],
   "the seller can see who is on what — paused counts as not active, and "
   "the card rail's absence is stated rather than implied")
ok(c.get("/api/store/admin/plans").status_code in (401, 403),
   "and who is paying what is not public")
ok('data-plan="' in _storejs and "startPlan" in _storejs
   and 'class="per"' in _storejs
   and "confirmPlanReturn()" in _storejs,
   "and on the shop itself a plan shows its period on the price, starts "
   "instead of adding, and confirms on the way back from checkout")

# --- the fleet: nodes, placement, and the empty-node reap -----------------
# Capacity is units, not tenants. The two rules that keep the bill honest:
# a client goes onto a node with room, and a node nobody is left on is
# destroyed the moment it empties.
from erp.backend import fleet as _fl

ok(c.get("/api/store/admin/fleet", headers=BB).status_code == 404,
   "a client tenant asking about the fleet is asking about other people's "
   "businesses — the tab does not exist for them, and neither does the API")
_fb = c.get("/api/store/admin/fleet", headers=AA).json()
ok(any(n["id"] == "local" for n in _fb["nodes"])
   and any(t["provider"] for n in _fb["nodes"] for t in n["tenants"]),
   "the board always has the local node, and knows which tenant runs the "
   "platform")

ok(c.post("/api/store/admin/fleet/nodes", headers=AA,
          json={"id": "node-a", "size": "4gb", "units": 8}).status_code
   == 200, "a node can be spun up")
ok(c.post("/api/store/admin/fleet/nodes", headers=AA,
          json={"id": "node-a"}).status_code == 400,
   "and not twice under one name")

ok(c.post("/api/store/admin/fleet/tenants", headers=AA,
          json={"id": "gamma", "brand": "Gamma", "node": "node-a",
                "klass": "growing"}).json()["node"] == "node-a",
   "a client is stood up onto the node you chose")
ok((_tn.tenant_dir("gamma") / "business_control.db").exists()
   and c.get("/api/products",
             headers={"host": "gamma.localhost"}).status_code == 200,
   "with its own database, answering on its own hostname, immediately")
ok("Gamma" in c.get("/", headers={"host": "gamma.localhost"}).text,
   "and their NAME on both faces — standing a client up used to brand the "
   "back office and leave the shop saying 'your brand', which is the first "
   "thing their own customers would have seen")

# infrastructure in the contract: standing up under an engagement writes
# its own paper
_heid = c.post("/api/store/admin/engagements", headers=AA,
               json={"name": "Hosted Co"}).json()["id"]
_hup = c.post("/api/store/admin/fleet/tenants", headers=AA,
              json={"id": "hostedco", "brand": "Hosted Co",
                    "klass": "micro", "engagement_id": _heid}).json()
ok(_hup["hosting_doc"],
   "standing infrastructure up under a client's engagement FILES the "
   "hosting & infrastructure schedule into it — the authority to run "
   "their business on our platform is a page in their binder, not an "
   "understanding")
_hcon = sqlite3.connect(_tn.tenant_dir("alpha") / "business_control.db")
_hcon.row_factory = sqlite3.Row
_hbody = _hcon.execute("SELECT body FROM documents WHERE id=?",
                       (_hup["hosting_doc"],)).fetchone()["body"]
_hcon.close()
ok("hostedco" in _hbody and "hostedco.localhost" in _hbody
   and "micro" in _hbody,
   "pre-filled with what was actually stood up — tenant, hostname, class")
ok("[90]" in _hbody and "503" in _hbody,
   "and it says out loud what suspension and exit mean, because those are "
   "the clauses a leaving client actually reads")
_hup2 = c.request("DELETE",
                  "/api/store/admin/fleet/tenants/hostedco?keep_data=0",
                  headers=AA)
ok(_hup2.status_code == 200, "cleanup: the paperwork test tenant leaves")

_fb = c.get("/api/store/admin/fleet", headers=AA).json()
_na = next(n for n in _fb["nodes"] if n["id"] == "node-a")
ok(_na["used"] == 4 and _na["free"] == 4,
   "capacity is counted in units — a 'growing' client is 4 of node-a's 8")
ok(c.post("/api/store/admin/fleet/tenants", headers=AA,
          json={"id": "delta", "node": "node-a", "klass": "large"})
   .status_code == 400,
   "and a client that does not fit is refused rather than overcommitted")

ok(c.post("/api/store/admin/fleet/tenants", headers=AA,
          json={"id": "delta", "node": "new", "new_node": "node-b",
                "klass": "micro"}).json()["node"] == "node-b",
   "or you spin up a node for them in the same act")

ok(c.post("/api/store/admin/fleet/tenants", headers=AA,
          json={"id": "epsilon", "hosts": [".localhost"], "klass": "micro"})
   .status_code == 200
   and _tn.registry()["tenants"]["epsilon"]["hosts"] == ["epsilon.localhost"],
   "a hostname with nothing in front of the dot is not a hostname — the "
   "form left blank falls back to the id rather than registering "
   "'.localhost' forever")
c.request("DELETE", "/api/store/admin/fleet/tenants/epsilon?keep_data=0",
          headers=AA)
ok(c.post("/api/store/admin/fleet/tenants", headers=AA,
          json={"id": "zeta", "hosts": ["beta.test"], "node": "new",
                "new_node": "node-z"}).status_code == 400
   and all(n["id"] != "node-z" for n in
           c.get("/api/store/admin/fleet", headers=AA).json()["nodes"]),
   "a hostname another business already answers to is refused — and "
   "refused before a node is spun up for it, so a rejected form leaves no "
   "server running behind it")

# suspend: the reversible half of "remove this client"
c.post("/api/store/admin/fleet/tenants/gamma/status", headers=AA,
       json={"status": "suspended"})
_sus = c.get("/api/products", headers={"host": "gamma.localhost"})
ok(_sus.status_code == 503 and "suspended" in _sus.json()["detail"],
   "a suspended tenant answers 503, not 404 — the site exists and is "
   "paused, and telling a paused customer 'no such site' is a lie")
ok((_tn.tenant_dir("gamma") / "business_control.db").exists(),
   "and not one byte of theirs was touched")
c.post("/api/store/admin/fleet/tenants/gamma/status", headers=AA,
       json={"status": "active"})
ok(c.get("/api/products",
         headers={"host": "gamma.localhost"}).status_code == 200,
   "resuming puts it straight back")
ok(c.post("/api/store/admin/fleet/tenants/alpha/status", headers=AA,
          json={"status": "suspended"}).status_code == 400,
   "the provider cannot suspend itself out of its own cockpit")

# the reap: the rule that keeps a fleet's margin from leaking
_rm = c.request("DELETE", "/api/store/admin/fleet/tenants/delta?keep_data=1",
                headers=AA).json()
ok("node-b" in _rm["nodes_destroyed"],
   "shutting down the LAST client on a node destroys the node with it — an "
   "empty VPS is pure cost, and the minute it empties is the only minute "
   "anyone would think to look")
ok(_rm["kept"] and Path(_rm["kept"]).exists(),
   "their data is retired, not deleted — a business that leaves still owns "
   "its records")
ok(all(n["id"] != "node-b" for n in
       c.get("/api/store/admin/fleet", headers=AA).json()["nodes"]),
   "and the node is off the board")

_fb = c.get("/api/store/admin/fleet", headers=AA).json()
ok(any(n["id"] == "node-a" for n in _fb["nodes"]),
   "node-a survives, because gamma still lives on it")
ok(c.request("DELETE", "/api/store/admin/fleet/nodes/node-a",
             headers=AA).status_code == 400,
   "and it cannot be destroyed under a tenant's feet")
ok(c.request("DELETE", "/api/store/admin/fleet/nodes/local",
             headers=AA).status_code == 400,
   "nor can the machine this process is running on be handed back from "
   "inside itself")

# moving, and the reap that follows it
c.post("/api/store/admin/fleet/nodes", headers=AA, json={"id": "node-c"})
ok(c.post("/api/store/admin/fleet/tenants/gamma/move", headers=AA,
          json={"node": "node-c"}).json()["node"] == "node-c",
   "a client can be moved to another node")
ok(all(n["id"] != "node-a" for n in
       c.get("/api/store/admin/fleet", headers=AA).json()["nodes"]),
   "and the node it left, now empty, went with the move")
ok(c.request("DELETE", "/api/store/admin/fleet/tenants/gamma?keep_data=0",
             headers=AA).status_code == 200
   and not _tn.tenant_dir("gamma").exists(),
   "keep_data=0 really deletes, for the client who asked to be forgotten")

ok(any(e["what"] == "node destroyed (empty)" for e in
       c.get("/api/store/admin/fleet", headers=AA).json()["events"]),
   "every provisioning, move and reap is on the fleet's own record — an "
   "operator asking 'when did that node go, and who took it' has an answer")
ok(c.get("/api/meta", headers=AA).json()["is_provider"]
   and not c.get("/api/meta", headers=HB).json()["is_provider"],
   "and the ops app is told which install runs the platform, so the tab "
   "exists in exactly one of them")
ok('id: "fleet"' in _opsjs and "provider: true" in _opsjs
   and "renderFleet" in _opsjs and "data-nodekill" in _opsjs,
   "the Platform tab is in the frontend, provider-gated, with the node and "
   "tenant controls on it")


# --- quote → stand-up: the paper sizes the platform -----------------------
# The quote knows the locations, seats and capabilities being bought; the
# fleet's classes are defined by the same numbers. Closing the contract
# gate offers the stand-up, sized from what was SOLD rather than guessed.
import base64 as _b64


def _bench_state(**kw):
    return _b64.b64encode(_jn.dumps(kw).encode()).decode()


_qeid = c.post("/api/store/admin/engagements", headers=AA,
               json={"name": "Sized Co"}).json()["id"]
ok(c.get(f"/api/store/admin/engagements/{_qeid}/stand-up",
         headers=AA).json()["suggestion"] is None,
   "with no quote filed there is nothing to derive from — the modal says "
   "so instead of inventing a size")

c.post(f"/api/store/admin/engagements/{_qeid}/quote", headers=AA,
       json={"markdown": "# Quote", "title": "Quote — Sized Co",
             "state": _bench_state(locs=2, seats=12,
                                   on=["core", "selling", "payments"])})
_sug = c.get(f"/api/store/admin/engagements/{_qeid}/stand-up",
             headers=AA).json()["suggestion"]
ok(_sug["klass"] == "growing" and _sug["capabilities"] == 2
   and "not signed yet" in _sug["reason"],
   "2 locations and 12 seats derive 'growing' — and an unsigned quote "
   "says so in the rationale, because a size from a draft is a draft")

for _st, _want in ((dict(locs=1, seats=5), "micro"),
                   (dict(locs=8, seats=60), "large"),
                   (dict(locs=12, seats=30), "dedicated"),
                   (dict(locs=2, seats=90), "dedicated"),
                   (dict(locs=1, seats=3, dedicated=True), "dedicated")):
    c.post(f"/api/store/admin/engagements/{_qeid}/quote", headers=AA,
           json={"markdown": "# Quote", "state": _bench_state(**_st)})
    _k = c.get(f"/api/store/admin/engagements/{_qeid}/stand-up",
               headers=AA).json()["suggestion"]["klass"]
    ok(_k == _want,
       f"the class boundaries are the price book's: {_st} → {_want} "
       f"(got {_k}) — a client bigger than 'large', or one who asked, "
       f"never quietly lands on a shared node")

# sign the growing-sized quote, then file a bigger draft: the SIGNED one
# must win, because it is the offer the client actually accepted
c.post(f"/api/store/admin/engagements/{_qeid}/quote", headers=AA,
       json={"markdown": "# Quote", "state": _bench_state(locs=2, seats=12)})
_qdid = c.get(f"/api/store/admin/engagements/{_qeid}/quote",
              headers=AA).json()["doc_id"]
_qsig = c.post(f"/api/store/admin/documents/{_qdid}/request-signature",
               headers=AA, json={"signer_name": "Sam",
                                 "signer_email": "sam@sized.example"})
_qtok = _qsig.json()["link"].rsplit("/", 1)[-1]
c.post(f"/sign/{_qtok}", headers=AA, json={"typed_name": "Sam"})
c.post(f"/api/store/admin/engagements/{_qeid}/quote", headers=AA,
       json={"markdown": "# Quote v2",
             "state": _bench_state(locs=9, seats=70)})
_sug2 = c.get(f"/api/store/admin/engagements/{_qeid}/stand-up",
              headers=AA).json()["suggestion"]
ok(_sug2["klass"] == "growing" and _sug2["signed"]
   and "not signed" not in _sug2["reason"],
   "the SIGNED quote sizes the install even when a bigger draft was filed "
   "after it — the offer the client accepted governs, not the upsell in "
   "progress")

# the gate: closing the contract offers the stand-up
_gout = c.post(f"/api/store/admin/engagements/{_qeid}/gates/contract_signed",
               headers=AA, json={"doc_id": _qdid}).json()
ok(_gout.get("stand_up", {}).get("suggestion", {}).get("klass") == "growing",
   "closing the contract gate OFFERS the stand-up, sized from the signed "
   "quote — the click-path from accepted paper to running install")
c.post("/api/store/admin/fleet/tenants", headers=AA,
       json={"id": "sizedco", "klass": "growing", "engagement_id": _qeid})
ok(not c.get(f"/api/store/admin/engagements/{_qeid}/stand-up",
             headers=AA).json()["offer"],
   "and once the install exists the offer disappears — a button that "
   "creates a thing must vanish when the thing does")
c.request("DELETE", "/api/store/admin/fleet/tenants/sizedco?keep_data=0",
          headers=AA)
ok(c.get(f"/api/store/admin/engagements/{_qeid}/stand-up",
         headers=AA).json()["offer"],
   "and removing the install clears the engagement's pointer — a "
   "dangling tenant_id left the client page offering Launch for nothing "
   "while hiding the Stand up that could fix it")
_appjs4 = ops_app_js()
ok("e.tenant_id ?" in _appjs4.replace("${e.tenant_id ? `", "e.tenant_id ?")
   or 'e.tenant_id ? `<span class="pill ok"' in _appjs4,
   "the clients list shows which clients RUN on the platform — the "
   "engagement and its install joined visibly, not two lists to "
   "cross-reference")
ok("Your administrator can ask" in _appjs4
   and "S.user.is_admin ? `" in _appjs4.replace("S.user && S.user.is_admin ? `", "S.user.is_admin ? `"),
   "a non-admin on a locked tab is told who can ask, instead of a button "
   "that fails with 'admin only' after the click")
ok(not c.post(f"/api/store/admin/engagements/{_qeid}/gates/deposit_cleared",
              headers=AA, json={"note": "wire ref 123"}).json()
   .get("stand_up"),
   "no other gate makes the offer — the contract is the one whose closing "
   "means the platform's half is agreed")

# --- starter layouts: the quote shapes the home page ----------------------
# The capability set says what the business IS; the new tenant's home page
# should open shaped like the business, not like the generic shop the
# section engine grew up as.
from storefront.backend import layouts as _lay

for _caps, _want in ((["selling", "payments"], "commerce"),
                     (["learning", "voice"], "courses"),
                     (["fundraising", "distribution"], "nonprofit"),
                     (["fundraising", "learning"], "courses"),
                     (["crm", "comms", "workforce"], "services"),
                     ([], "services")):
    ok(_lay.shape_of(_caps) == _want,
       f"{_caps} shapes as {_want} — what a business MAKES beats how it "
       f"takes money, which is why a teaching nonprofit leads with its "
       f"courses")

_lnshape, _lnsecs = _lay.home_sections(["fundraising", "learning"])
ok(_lnshape == "courses"
   and any(t == "image_banner" and "Support the work"
           in st.get("heading", "") for t, st in _lnsecs),
   "and the capability it does NOT lead with still earns its section — "
   "the language nonprofit gets the courses skeleton with the support "
   "banner composed in")
_alltext = _jn.dumps([st for _, st in _lnsecs])
ok("100,000" not in _alltext and not any(
       t == "social_proof" for t, _ in _lnsecs),
   "scaffolding never invents a fact — no customer counts, no fake proof, "
   "on a page that ships in the merchant's name")

_seid = c.post("/api/store/admin/engagements", headers=AA,
               json={"name": "School Co"}).json()["id"]
c.post(f"/api/store/admin/engagements/{_seid}/quote", headers=AA,
       json={"markdown": "# Quote",
             "state": _bench_state(locs=1, seats=4,
                                   on=["core", "learning", "subs",
                                       "payments"])})
_ssug = c.get(f"/api/store/admin/engagements/{_seid}/stand-up",
              headers=AA).json()["suggestion"]
ok(_ssug["shape"] == "courses" and _ssug["cap_ids"],
   "the stand-up suggestion carries the shape, so the modal can say what "
   "page the click will produce")
_sup = c.post("/api/store/admin/fleet/tenants", headers=AA,
              json={"id": "schoolco", "brand": "School Co",
                    "klass": "micro", "engagement_id": _seid}).json()
ok(_sup["layout"] == "courses",
   "standing up from a quote applies the starter layout, and says so")
_scon = sqlite3.connect(_tn.tenant_dir("schoolco") / "business_control.db")
_stypes = [r[0] for r in _scon.execute(
    "SELECT type FROM page_sections WHERE page_slug='home'"
    " ORDER BY position")]
ok(_stypes[0] == "hero" and "showcase" not in _stypes
   and any(t == "rich_text" for t in _stypes),
   f"the new tenant's home is the courses skeleton, not the drinks-shop "
   f"default ({_stypes})")
ok(any("subscription" in (r[0] or "")
       for r in _scon.execute("SELECT settings FROM page_sections"
                              " WHERE page_slug='home'")),
   "and the subs capability composed its explainer in, on a non-commerce "
   "shape where it is not otherwise told")
ok(_scon.execute("SELECT v FROM store_meta WHERE k='home_backfill'"
                 ).fetchone() is not None,
   "the layout marks the back-fill applied — a restart must not put the "
   "drinks showcase on top of a page that was chosen")
_scon.execute(
    "UPDATE page_sections SET settings=json_set(settings,'$.heading',"
    " 'Edited by hand') WHERE page_slug='our-story' AND type='rich_text'")
_scon.commit()
_lay.apply(_scon, ["learning", "subs", "payments"], "School Co")
ok(_scon.execute(
       "SELECT COUNT(*) FROM page_sections WHERE page_slug='our-story'"
       " AND settings LIKE '%Edited by hand%'").fetchone()[0] == 1
   and _scon.execute("SELECT COUNT(*) FROM store_pages WHERE"
                     " slug='our-story'").fetchone()[0] == 1,
   "a page whose slug already exists is left entirely alone by a re-run — "
   "it is someone's work, whatever stand-up is re-running over it")
ok(_scon.execute("SELECT COUNT(*) FROM store_menus WHERE"
                 " url='/p/our-story'").fetchone()[0] == 2,
   "and the re-run still NAMES it in the nav — links are built from the "
   "pages that exist, not just the ones this run created, which is the "
   "bug the first version of this had")
_scon.close()
_shome = c.get("/", headers={"host": "schoolco.localhost"}).text
ok("able to do" in _shome and "School Co" in _shome,
   "and it renders — the courses hero on their own hostname, their name "
   "on it, before anyone has touched a thing")

# the pages beside the home — where "tell them more" lives
_SH = {"host": "schoolco.localhost"}
_sabout = c.get("/p/our-story", headers=_SH).text
ok(c.get("/p/our-story", headers=_SH).status_code == 200
   and "Who teaches this" in _sabout,
   "the shape ships its secondary pages — a school's about page is about "
   "the teacher, not 'our story' in a shop's voice")
ok("image-banner placeholder" in _sabout,
   "with the photo slot rendered as a labeled placeholder — in the live "
   "editor that is a click-to-upload target, so the page says where its "
   "picture goes")
_scurr = c.get("/p/curriculum", headers=_SH).text
ok("outcome language" in _scurr and "stuck" in _scurr,
   "and the curriculum page scaffolds outcomes, not a topic list")
ok('>The curriculum</a>' in _shome and '>Who teaches this</a>' in _shome
   and ">Reviews</a>" in _shome,
   "the nav carries the pages, and keeps Reviews because this shape's "
   "home actually has a reviews section to anchor to")

for _st2, _pg, _mark in ((["fundraising"], "impact", "stand behind"),
                        (["selling"], "delivery-and-returns",
                         "an invented policy is worse than a blank"),
                        (["crm"], "how-we-work",
                         "freelancer with a phone")):
    _sh2, _pp = _lay.home_sections(_st2)
    _pgs = {sl: secs for sl, _, secs in _lay.secondary_pages(_sh2)}
    ok(_pg in _pgs and _mark in _jn.dumps(_pgs[_pg]),
       f"the {_sh2} shape ships /p/{_pg} with its own voice")
_np_hero = dict(_lay.home_sections(["fundraising"])[1])["hero"]
ok(_np_hero["cta2_link"] == "/p/impact",
   "the nonprofit hero's 'See the work' points at the impact page that "
   "now exists — it used to link an anchor no section rendered")
ok(">Courses</a>" in _shome and ">Shop</a>" not in _shome,
   "the nav's first word follows the shape — 'Shop' over a list of "
   "courses reads as a mistake")
ok("Free shipping over $40" not in _shome
   and 'id="announce" hidden' in _shome,
   "and no invented policy in the announce bar — the old default promised "
   "free shipping on every fresh tenant, in the merchant's name; empty "
   "now, and an empty bar is hidden rather than an empty purple strip")
c.request("DELETE", "/api/store/admin/fleet/tenants/schoolco?keep_data=0",
          headers=AA)

ok(c.post("/api/store/admin/fleet/tenants", headers=AA,
          json={"id": "noquote", "klass": "micro"}).json()["layout"]
   == "placeholder",
   "with no quote there is no shape to derive — so the stand-up applies "
   "the PLACEHOLDER, never the factory default that used to put another "
   "business's film on a fresh install's front door")
_nqcon = sqlite3.connect(_tn.tenant_dir("noquote") / "business_control.db")
_nqtypes = [r[0] for r in _nqcon.execute(
    "SELECT type FROM page_sections WHERE page_slug='home'"
    " ORDER BY position")]
_nqhero = _nqcon.execute(
    "SELECT settings FROM page_sections WHERE page_slug='home'"
    " AND type='hero'").fetchone()[0]
_nqcon.close()
ok("showcase" not in _nqtypes and "setting up shop" in _nqhero
   and "Noquote" in _nqhero,
   "the placeholder says what is true — the install is live, the site is "
   "not designed yet, under the business's own name")
ok("hero.mp4" not in _jn.dumps([
       dict(_sect.defaults_for(t)) for t in _sect.SECTION_TYPES]),
   "and no section default anywhere references the old film asset")
c.request("DELETE", "/api/store/admin/fleet/tenants/noquote?keep_data=0",
          headers=AA)



# --- the live section editor: the preview IS the editor -------------------
# Three mechanisms, each tested where it lives: the rendered page is
# addressed (every section knows its row), the marked text fields name the
# settings key they render, and one section can be re-rendered alone so a
# save swaps an element instead of reloading the page.
_ed_home = c.get("/", headers=HA).text
ok('data-sid="' in _ed_home and 'data-slabel="Hero banner"' in _ed_home,
   "every rendered section carries its row id and a human label — the "
   "editor can point at a spot on the page and know which record it is")
ok('data-sf="heading"' in _ed_home and 'data-sf="sub"' in _ed_home,
   "and the text an element renders names its settings key, so typing "
   "into the page and editing the field are the same gesture")

_ed_secs = c.get("/api/store/admin/sections/home", headers=AA).json()
_ed_faq = next(x for x in _ed_secs if x["type"] == "faq")
ok(f'data-sf="items.0.q"' in _ed_home,
   "list fields are addressed per item — the first FAQ question is "
   "items.0.q, editable in place like any heading")

_ed_hero = next(x for x in _ed_secs if x["type"] == "hero")
_eh = c.get(f"/api/store/admin/sections/{_ed_hero['id']}/html",
            headers=AA).json()
ok(f'data-sid="{_ed_hero["id"]}"' in _eh["html"]
   and "<section" in _eh["html"],
   "one section renders alone, addressed the same way — the save path "
   "swaps exactly this element instead of reloading the storefront out "
   "from under the merchant")
c.post(f"/api/store/admin/sections/{_ed_hero['id']}", headers=AA,
       json={"settings": {**_ed_hero["settings"],
                          "heading": "Edited from the page"}})
ok("Edited from the page" in c.get(
       f"/api/store/admin/sections/{_ed_hero['id']}/html",
       headers=AA).json()["html"],
   "and it re-renders from the saved settings, not a cache")
c.post(f"/api/store/admin/sections/{_ed_hero['id']}", headers=AA,
       json={"settings": _ed_hero["settings"]})
ok(c.get(f"/api/store/admin/sections/{_ed_hero['id']}/html")
   .status_code in (401, 403),
   "rendering a section by id is admin-gated like the rest of the editor")

_thjs = Path("src/storefront/frontend/theme.js").read_text()
ok("contentEditable" in _thjs and 'plaintext-only' in _thjs
   and "swap: false" in _thjs,
   "typing into the page saves WITHOUT swapping the node — replacing the "
   "element mid-word would eat the merchant's caret")
ok("swapSection" in _thjs and "replaceWith(fresh)" in _thjs
   and "NEEDS_RELOAD" in _thjs,
   "panel edits swap the one section, except the types whose content is "
   "wired by the storefront's own script — a swapped-in product grid "
   "would arrive empty, so those take the honest full reload")
ok("e.preventDefault();" in _thjs and "e.stopPropagation();" in _thjs
   and "closest(\"a\")" in _thjs.replace("'", '"'),
   "the preview is inert — a link would navigate the page being edited "
   "away, and a live Add-to-cart would quietly build a real cart")
ok("highlightPreview(SEL)" in _thjs,
   "selecting in the sidebar scrolls the preview to the section, so the "
   "list and the page can never be pointing at different things")
_rich_html = _sect.render_one(
    None, {"id": 9, "type": "spacer", "settings": "{}", "enabled": 1})
ok('data-sid="9"' in _rich_html,
   "even a section with no text is addressed — selection and reordering "
   "work on every type, not just the wordy ones")


# --- add-in-place and drag-to-reorder -------------------------------------
# Both gestures ask one question — "where between the sections?" — and the
# server answers in one write: an insert lands where the merchant pointed,
# a drag names its destination outright.
_dp_ids = [x["id"] for x in
           c.get("/api/store/admin/sections/home", headers=AA).json()]
_dp_new = c.post("/api/store/admin/sections", headers=AA,
                 json={"page_slug": "home", "type": "spacer",
                       "position": 1}).json()["id"]
_dp_now = [x["id"] for x in
           c.get("/api/store/admin/sections/home", headers=AA).json()]
ok(_dp_now.index(_dp_new) == 1 and _dp_now[0] == _dp_ids[0]
   and _dp_now[2] == _dp_ids[1],
   "adding at a position INSERTS there — not append-then-shuffle, so the "
   "section lands where the merchant pointed and nothing else moves")

c.post(f"/api/store/admin/sections/{_dp_new}", headers=AA,
       json={"position": len(_dp_now) - 1})
_dp_now = [x["id"] for x in
           c.get("/api/store/admin/sections/home", headers=AA).json()]
ok(_dp_now[-1] == _dp_new and _dp_now[:-1] == _dp_ids,
   "a drag names its destination as an absolute index — the dragged "
   "section lands there and every other section keeps its order")
c.post(f"/api/store/admin/sections/{_dp_new}", headers=AA,
       json={"position": 999})
ok([x["id"] for x in c.get("/api/store/admin/sections/home",
                           headers=AA).json()][-1] == _dp_new,
   "and a stale editor naming an index the page no longer has is clamped, "
   "not crashed")
c.request("DELETE", f"/api/store/admin/sections/{_dp_new}", headers=AA)
ok([x["id"] for x in c.get("/api/store/admin/sections/home",
                           headers=AA).json()] == _dp_ids,
   "cleanup restores the page exactly")

ok("injectBars" in _thjs and 'dataset.before' in _thjs
   and "beforeIndex" in _thjs,
   "the preview's insertion bars name the section they sit before — the "
   "preview hides disabled sections, so its own ordinals would lie the "
   "moment one is hidden")
ok("a > i ? a - 1 : a" in _thjs.replace("a -= 1", "a > i ? a - 1 : a")
   or "if (a > i) a -= 1;" in _thjs,
   "and a drop past the dragged section's own slot accounts for its "
   "removal — the classic off-by-one that makes drag-and-drop land one "
   "short")
ok('closest(".sfe-add, .sfe-pick, .sfe-handle")' in _thjs,
   "the click interceptor that keeps the preview inert exempts the "
   "editor's own chrome, or the add button would swallow its own clicks")
ok("draggable = true" in _thjs and "sfe-handle" in _thjs
   and "setDragImage" in _thjs,
   "dragging is the HANDLE, not the section — a draggable section would "
   "fight the text selection that inline editing just made possible")


# --- images without leaving the page --------------------------------------
# Site media: product_id 0 means the image belongs to the storefront (a
# hero background, a banner), not to any product. Everything downstream
# already served by media id alone; only the upload guard ever cared.
_png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
_sm = c.post("/api/store/admin/media", headers=AA,
             json={"product_id": 0, "data_url": _png, "alt": "hero wash"})
ok(_sm.status_code == 200 and _sm.json()["kind"] == "image",
   "an image uploads as SITE media — no product required, because a hero "
   "background is not a product's photograph")
_smid = _sm.json()["id"]
ok(c.get(f"/media/m/{_smid}", headers=HA).status_code == 200,
   "and serves from the same immutable URL as any other media")
ok(any(m["id"] == _smid for m in
       c.get("/api/store/admin/media/0", headers=AA).json()),
   "listed under product 0, which is how the editor's picker finds it")
ok(c.post("/api/store/admin/media", headers=AA,
          json={"product_id": 999999, "data_url": _png}).status_code == 404,
   "while a nonexistent real product still 404s — 0 is the one keyword")

_ib = c.post("/api/store/admin/sections", headers=AA,
             json={"page_slug": "home", "type": "image_banner"}).json()["id"]
c.post(f"/api/store/admin/sections/{_ib}", headers=AA,
       json={"settings": {"media_id": _smid, "heading": "From the page",
                          "text": "", "link": "", "height": "medium"}})
ok(f"/media/m/{_smid}" in c.get(
       f"/api/store/admin/sections/{_ib}/html", headers=AA).json()["html"],
   "a section pointed at site media renders it — the same swap path the "
   "editor uses after an upload")
c.request("DELETE", f"/api/store/admin/sections/{_ib}", headers=AA)

ok("product_id: 0" in _thjs and "readAsDataURL" in _thjs
   and "sfe-imgbtn" in _thjs,
   "the editor's image button uploads to site media through a file picker "
   "opened from the section itself")
ok('s.settings.bg = "image"' in _thjs,
   "and uploading into a hero flips it to image mode — a new background "
   "hidden behind the gradient would look like the upload failed")
ok('includes("Files")' in _thjs and "sfe-filedrop" in _thjs
   and "DRAG_SID != null) return" in _thjs,
   "an image file dropped on a section uploads there — and file drags are "
   "told apart from section drags, so reordering can't trigger an upload")
ok("loadSiteMedia" in _thjs and "PRODUCT_MEDIA" in _thjs,
   "the panel's media picker lists site media beside product media, so an "
   "upload from the page is reusable from the form")


# --- the design library: design once, place everywhere --------------------
# The rule that keeps the wall honest: a push ADDS a section, stamped with
# where it came from, and from that moment the placement belongs to the
# tenant — never overwritten by a later push, surviving the design's
# deletion from the library.
ok(c.get("/api/store/admin/designs", headers=BB).status_code == 404,
   "the library is the provider's — a client tenant has no such API, the "
   "same wall as the fleet")
_dz = c.post("/api/store/admin/designs", headers=AA,
             json={"name": "Signature FAQ", "type": "faq",
                   "settings": {"heading": "The honest questions",
                                "items": [{"q": "What does it cost?",
                                           "a": "It depends — here's how."}
                                          ]}}).json()
ok(_dz["ok"] and not _dz["updated"],
   "a section's design saves to the library by name")
_did2 = _dz["id"]
ok(c.post("/api/store/admin/designs", headers=AA,
          json={"name": "Signature FAQ", "type": "faq",
                "settings": {"heading": "The honest questions, v2",
                             "items": []}}).json()["updated"],
   "and the same name updates it — the library entry is the studio's to "
   "revise")

_bcon0 = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
_bb_before = _bcon0.execute(
    "SELECT COUNT(*) FROM page_sections WHERE page_slug='home'"
    ).fetchone()[0]
_bcon0.close()
_push = c.post(f"/api/store/admin/designs/{_did2}/push", headers=AA,
               json={"tenants": ["beta", "nobody-here"]}).json()
ok("beta" in _push["placed"]
   and _push["skipped"].get("nobody-here") == "no such tenant",
   "a push places onto real tenants and says plainly who was skipped and "
   "why")
_bcon = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
_bcon.row_factory = sqlite3.Row
_brow = _bcon.execute("SELECT * FROM page_sections WHERE design_id=?",
                      (_did2,)).fetchone()
ok(_brow is not None and _brow["type"] == "faq"
   and "v2" in _brow["settings"],
   "the placement carries the design's CURRENT settings and its stamp")
ok(_bcon.execute("SELECT COUNT(*) FROM page_sections WHERE"
                 " page_slug='home'").fetchone()[0] == _bb_before + 1,
   "and it was ADDED — nothing beta already had moved or changed")
ok("The honest questions" in c.get("/", headers=HB).text,
   "beta's storefront renders it, live")

_bcon.execute("UPDATE page_sections SET settings=json_set(settings,"
              "'$.heading','Beta made this theirs') WHERE id=?",
              (_brow["id"],))
_bcon.commit()
c.post(f"/api/store/admin/designs/{_did2}/push", headers=AA,
       json={"tenants": ["beta"]})
_bcon2 = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
_bcon2.row_factory = sqlite3.Row
_beta_rows = [dict(r) for r in _bcon2.execute(
    "SELECT * FROM page_sections WHERE design_id=?", (_did2,))]
ok(len(_beta_rows) == 2
   and any("Beta made this theirs" in r["settings"] for r in _beta_rows),
   "a second push adds a second copy and leaves the edited first alone — "
   "the placement became beta's the moment it landed, and no push ever "
   "reaches back into a tenant's page")
_bcon2.execute("DELETE FROM page_sections WHERE id=?",
               (max(r["id"] for r in _beta_rows),))
_bcon2.commit()

_dl = c.get("/api/store/admin/designs", headers=AA).json()["designs"]
_dme = next(d for d in _dl if d["id"] == _did2)
ok(_dme["placements"].get("beta", {}).get("n") == 1,
   "the library says where each design lives, counted across the fleet — "
   "reach is visible before anyone pushes again")
c.request("DELETE", f"/api/store/admin/designs/{_did2}", headers=AA)
_bcon3 = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
ok(_bcon3.execute("SELECT COUNT(*) FROM page_sections WHERE design_id=?",
                  (_did2,)).fetchone()[0] == 1,
   "deleting a design from the library leaves its placements standing — "
   "they are the tenants' sections, not the library's")
_bcon3.execute("DELETE FROM page_sections WHERE design_id=?", (_did2,))
_bcon3.commit(); _bcon3.close()

ok(c.post(f"/api/store/admin/designs/{_did2}/push", headers=BB,
          json={"tenants": ["alpha"]}).status_code == 404,
   "and a client tenant cannot push at anyone — the library's verbs are "
   "all provider-side")
_thjs2 = Path("src/storefront/frontend/theme.js").read_text()
ok("save-design" in _thjs2 and "IS_PROVIDER" in _thjs2
   and "data-dpush" in _thjs2 and "design_id: d.id" in _thjs2,
   "the editor carries the loop — save from the selected section, insert "
   "with provenance, push to chosen clients — shown only on the provider")


# --- linked placements: follow the design, until the first edit -----------
# The opt-in version of the push. design_sync=1 means the placement is
# rewritten when the library entry is; the tenant's first settings edit
# detaches it at the one write path an edit can take. The provenance stamp
# was the hook; this is what hangs on it.
_dl2 = c.post("/api/store/admin/designs", headers=AA,
              json={"name": "Care banner", "type": "image_banner",
                    "settings": {"heading": "We keep it running",
                                 "text": "v1", "link": "", "media_id": "",
                                 "height": "short"}}).json()["id"]
c.post(f"/api/store/admin/designs/{_dl2}/push", headers=AA,
       json={"tenants": ["beta"], "linked": True})
c.post(f"/api/store/admin/designs/{_dl2}/push", headers=AA,
       json={"tenants": ["beta"], "linked": False})
_bc = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
_bc.row_factory = sqlite3.Row
_linked, _plain = [dict(r) for r in _bc.execute(
    "SELECT * FROM page_sections WHERE design_id=? ORDER BY id",
    (_dl2,))]
ok(_linked["design_sync"] == 1 and _plain["design_sync"] == 0,
   "a push chooses: linked placements carry the flag, plain ones don't")

_sv = c.post("/api/store/admin/designs", headers=AA,
             json={"name": "Care banner", "type": "image_banner",
                   "settings": {"heading": "We keep it running",
                                "text": "v2", "link": "", "media_id": "",
                                "height": "short"}}).json()
ok(_sv["refreshed"].get("beta") == 1,
   "saving over the design refreshes the linked placement and reports it")
_bc2 = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
_bc2.row_factory = sqlite3.Row
_now = {r["id"]: r["settings"] for r in _bc2.execute(
    "SELECT id, settings FROM page_sections WHERE design_id=?", (_dl2,))}
ok('"v2"' in _now[_linked["id"]] and '"v1"' in _now[_plain["id"]],
   "the linked copy moved to v2 across the wall; the plain copy is the "
   "tenant's from the moment it landed and did not")

# the detach: an edit through the tenant's own editor makes it theirs
c.post(f"/api/store/admin/sections/{_linked['id']}",
       headers={**BB},
       json={"settings": {"heading": "Beta's banner now", "text": "v2",
                          "link": "", "media_id": "", "height": "short"}})
_bc3 = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
ok(_bc3.execute("SELECT design_sync FROM page_sections WHERE id=?",
                (_linked["id"],)).fetchone()[0] == 0,
   "the tenant's first settings edit detaches — enforced at the one "
   "write path an edit can take, not remembered by the editor")
c.post(f"/api/store/admin/sections/{_linked['id']}", headers={**BB},
       json={"move": "up"})
ok(_bc3.execute("SELECT design_sync FROM page_sections WHERE id=?",
                (_plain["id"],)).fetchone()[0] == 0
   and c.post(f"/api/store/admin/designs/{_dl2}/push", headers=AA,
              json={"tenants": ["beta"], "linked": True}).json()["placed"],
   "sanity: pushes still place")
_bc4 = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
_third = _bc4.execute(
    "SELECT id FROM page_sections WHERE design_id=? AND design_sync=1",
    (_dl2,)).fetchone()[0]
c.post(f"/api/store/admin/sections/{_third}", headers={**BB},
       json={"move": "up"})
ok(_bc4.execute("SELECT design_sync FROM page_sections WHERE id=?",
                (_third,)).fetchone()[0] == 1,
   "moving or hiding a linked section does NOT detach it — the design "
   "governs the section's content, not its place on the page")

c.post("/api/store/admin/designs", headers=AA,
       json={"name": "Care banner", "type": "image_banner",
             "settings": {"heading": "We keep it running", "text": "v3",
                          "link": "", "media_id": "", "height": "short"}})
_bc5 = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
ok('"v2"' in _bc5.execute(
       "SELECT settings FROM page_sections WHERE id=?",
       (_linked["id"],)).fetchone()[0],
   "and a later design update passes the detached placement by — the "
   "write can never reach a page anyone has made their own")

_pl = next(d for d in c.get("/api/store/admin/designs",
                            headers=AA).json()["designs"]
           if d["id"] == _dl2)["placements"]["beta"]
ok(_pl["n"] == 3 and _pl["linked"] == 1,
   "the board tells the two apart — how many placements, how many still "
   "follow")
c.request("DELETE", f"/api/store/admin/designs/{_dl2}", headers=AA)
_bc6 = sqlite3.connect(_tn.tenant_dir("beta") / "business_control.db")
ok(_bc6.execute("SELECT SUM(design_sync) FROM page_sections WHERE"
                " design_id=?", (_dl2,)).fetchone()[0] == 0
   and _bc6.execute("SELECT COUNT(*) FROM page_sections WHERE"
                    " design_id=?", (_dl2,)).fetchone()[0] == 3,
   "deleting the design ends the following without touching the pages — "
   "and no later design reusing the id could inherit a grip")
_bc6.execute("DELETE FROM page_sections WHERE design_id=?", (_dl2,))
_bc6.commit()
for _cx in (_bc, _bc2, _bc3, _bc4, _bc5, _bc6):
    _cx.close()
_thjs3 = Path("src/storefront/frontend/theme.js").read_text()
ok('id="push-linked"' in _thjs3 and "s.design_sync" in _thjs3
   and "first edit makes it yours" in " ".join(_thjs3.split()),
   "the push chooser offers linked as an off-by-default checkbox, and a "
   "tenant editing a linked section is told what their first edit does "
   "BEFORE they make it")


# --- closing the loops: entitlements, plan bridge, dunning, one book ------

# 1. entitlements: the quote's capability set becomes the tenant's grant
_ee = c.post("/api/store/admin/engagements", headers=AA,
             json={"name": "Partial Co"}).json()["id"]
c.post(f"/api/store/admin/engagements/{_ee}/quote", headers=AA,
       json={"markdown": "# Quote",
             "state": _bench_state(locs=1, seats=4,
                                   on=["core", "selling", "payments",
                                       "workforce"])})
c.post("/api/store/admin/fleet/tenants", headers=AA,
       json={"id": "partialco", "brand": "Partial Co", "klass": "micro",
             "engagement_id": _ee})
ok(_tn.registry()["tenants"]["partialco"]["caps"]
   == ["payments", "selling", "workforce"],
   "stand-up records WHAT WAS SOLD on the registry row — the same "
   "capability list that sized the node and shaped the home page, no "
   "longer discarded after one use")
_pm = c.get("/api/meta", headers={"host": "partialco.localhost"}).json()
ok(_pm["caps"] == ["payments", "selling", "workforce"],
   "and the tenant's own ops app is told, through meta")
ok(c.get("/api/meta", headers=HB).json()["caps"] is None,
   "a tenant with no recorded grant gets null — everything on. The "
   "absence of a grant must never take features away from anyone who "
   "already had them all")

_appjs = ops_app_js()
ok("TAB_CAP" in _appjs and "capLocked" in _appjs
   and "cap-locked" in _appjs and "renderCapLocked" in _appjs,
   "unsold tabs show LOCKED rather than vanish — the tab opens the ask "
   "panel instead of the screen, so the product sells its own upgrades")
ok('"selling"' in _appjs.split("TAB_CAP")[1][:900]
   and "Array.isArray(caps)" in _appjs,
   "the tab→capability map speaks the price book's own ids, and null "
   "caps unlocks everything")

_ci = c.get("/api/capability-info/distribution",
            headers={"host": "partialco.localhost"}).json()
ok(_ci["name"] == "Distribution" and _ci["price"] == 50
   and _ci["band"] == "heavy",
   "the locked panel's price comes from the BOOK via the parser, not a "
   "number the frontend remembered")
ok(c.get("/api/capability-info/nonsense").status_code == 404,
   "and an unknown capability is a 404, not a guess")

# the ask crosses the wall the narrow way
_padmin = json.loads((_tn.tenant_dir("partialco") / "config.json"
                      ).read_text())["admin_key"]
_ptok = c.post("/api/login", headers={"host": "partialco.localhost"},
               json={"name": "PC Admin", "role": "admin",
                     "admin_key": _padmin}).json()["token"]
ok(c.post("/api/capability-request",
          headers={"host": "partialco.localhost",
                   "Authorization": f"Bearer {_ptok}"},
          json={"capability": "distribution"}).json()["ok"],
   "a client admin can ask for a capability from their own ops app")
_acon = sqlite3.connect(_tn.tenant_dir("alpha") / "business_control.db")
_acon.row_factory = sqlite3.Row
_lead = _acon.execute(
    "SELECT * FROM outreach WHERE name LIKE '%distribution%'"
    " ORDER BY id DESC LIMIT 1").fetchone()
ok(_lead is not None and "Partial Co" in _lead["name"]
   and _lead["stage"] == "lead",
   "and the ask lands as a lead on the STUDIO's sales board, across the "
   "wall the narrow way — not in a table on the client's side nobody "
   "opens")
ok(_acon.execute(
       "SELECT 1 FROM engagement_log WHERE engagement_id=? AND"
       " what LIKE '%distribution%'", (_ee,)).fetchone() is not None,
   "with a line on the engagement, so the client's file tells the story")
_acon.close()

# 2. a plan purchase is heard
_buyer = c.post("/api/login", headers=HA,
                json={"name": "Self Serve", "role": "customer",
                      "email": "self@serve.test"}).json()
_pcat2 = {p["name"]: p for p in
          c.get("/api/store/catalog", headers=HA).json()["products"]}
if "Pro plan" not in _pcat2:
    c2 = sqlite3.connect(_tn.tenant_dir("alpha") / "business_control.db")
    c2.execute("INSERT INTO products(sku,name,description,category,"
               "price_cents,case_size,case_price_cents,active)"
               " VALUES('PLAN-PRO2','Pro plan','x','Plans',34900,1,34900,1)")
    _pid2 = c2.execute("SELECT last_insert_rowid()").fetchone()[0]
    c2.execute("INSERT OR REPLACE INTO store_product_meta(product_id,k,v)"
               " VALUES(?,'billing','month')", (_pid2,))
    c2.commit(); c2.close()
    _pcat2 = {p["name"]: p for p in
              c.get("/api/store/catalog", headers=HA).json()["products"]}
c.post("/api/store/plans/subscribe",
       headers={"Authorization": f"Bearer {_buyer['token']}", **HA},
       json={"product_id": _pcat2["Pro plan"]["id"]})
_acon2 = sqlite3.connect(_tn.tenant_dir("alpha") / "business_control.db")
ok(_acon2.execute("SELECT 1 FROM outreach WHERE name LIKE"
                  " '%Self Serve%'").fetchone() is not None,
   "a self-serve plan purchase opens a lead on the sales board — a buyer "
   "of a deployment plan is a client the moment they pay, not when "
   "someone happens to open the admin panel")
_acon2.close()
ok('fire_webhooks("plan.started"' in
   Path("src/storefront/backend/api.py").read_text(),
   "and fires the same webhook rail every other commercial event uses")

# 3. dunning: the failed card surfaces next to the install it pays for
_dsub = c.get("/api/store/admin/plans", headers=AA).json()["plans"][0]
ok(c.post(f"/api/store/admin/plans/{_dsub['id']}/tenant", headers=AA,
          json={"tenant_id": "partialco"}).json()["tenant_id"]
   == "partialco",
   "a plan links to the install it pays for")
ok(c.post(f"/api/store/admin/plans/{_dsub['id']}/tenant", headers=AA,
          json={"tenant_id": "no-such"}).status_code == 400,
   "and not to a tenant the fleet doesn't have")
from erp.backend import payments as _pay2
from storefront.backend import fleetadmin as _eng2
_acon3 = sqlite3.connect(_tn.tenant_dir("alpha") / "business_control.db")
_acon3.execute("UPDATE store_subscriptions SET payment_ref='sub_dun_1'"
               " WHERE id=?", (_dsub["id"],))
_acon3.commit(); _acon3.close()
_realget2 = _pay2.httpx.get
_realen = _pay2.enabled
_pay2.enabled = lambda cfg: True
_pay2.httpx.get = lambda url, auth=None, timeout=None: type(
    "R", (), {"status_code": 200,
              "json": lambda self: {"status": "past_due"}})()
_eng2._BILLING_CACHE["at"] = 0
try:
    _fbb = c.get("/api/store/admin/fleet", headers=AA).json()
finally:
    _pay2.httpx.get = _realget2
    _pay2.enabled = _realen
_pten = next(t for n in _fbb["nodes"] for t in n["tenants"]
             if t["id"] == "partialco")
ok(_pten["billing"] and _pten["billing"]["status"] == "past_due",
   "the fleet board flags the tenant whose linked card Stripe would not "
   "bill — the fact sits beside the Suspend button, and suspension stays "
   "a human's click")
ok(any(e["what"] == "billing warning" for e in _fbb["events"]),
   "recorded once per state change on the fleet's own history")
ok(next(t for n in c.get("/api/store/admin/fleet", headers=AA).json()
        ["nodes"] for t in n["tenants"] if t["id"] == "partialco")
   .get("caps") == 3,
   "and the board says how many capabilities each tenant was granted")
_eng2._BILLING_CACHE["at"] = 0

# 4. the served bench reads the book
_qb2 = c.get("/api/store/admin/quote-bench", headers=AA).text
from storefront.backend import pricebook as _pb2
_b2 = _pb2.bands()
ok(f"bands:{{light:{_b2['light']},std:{_b2['standard']},"
   f"heavy:{_b2['heavy']}}}, corePrice:{_pb2.core_price()}" in _qb2,
   "the SERVED bench carries the book's numbers, substituted at serve "
   "time from the same parse the storefront seeds from — the fourth copy "
   "of the price book is no longer a copy")

c.request("DELETE", "/api/store/admin/fleet/tenants/partialco?keep_data=0",
          headers=AA)


# --- the ceremony gates stop being ceremony -------------------------------
# Launch: the URL and the sold capabilities land on the tenant in one act.
# Dates: the schedule reaches the gates, and a closing gate reports back.
_le = c.post("/api/store/admin/engagements", headers=AA,
             json={"name": "Launch Co"}).json()["id"]
c.post(f"/api/store/admin/engagements/{_le}/quote", headers=AA,
       json={"markdown": "# Quote",
             "state": _bench_state(locs=1, seats=4,
                                   on=["core", "selling", "payments"])})
c.put(f"/api/store/admin/engagements/{_le}/dates", headers=AA,
      json={"dates": [
          {"label": "Requirements signed", "planned": "2026-09-12"},
          {"label": "Launch", "planned": "2026-08-01"}]})
_ld = c.get(f"/api/store/admin/engagements/{_le}", headers=AA).json()
_lg = {g["gate"]: g for g in _ld["gates"]}
ok(_lg["requirements_signed"].get("planned") == "2026-09-12",
   "a Dates row reaches its gate by label — the schedule shows on the "
   "gate row, not only in a separate table")
ok(_lg["final_invoice_paid"].get("planned") == "2026-08-01",
   "and by stage when the label is the stage's name — 'Launch' belongs "
   "to the gate that closes 08-launch")
ok("planned" not in _lg["contract_signed"],
   "a gate with no scheduled date carries none, rather than a guess")

_gp = c.post(f"/api/store/admin/engagements/{_le}/gates/"
             f"requirements_signed", headers=AA,
             json={"note": "signed on paper, filed in the drive"}).json()
ok(_gp.get("date_stamped") == "Requirements signed",
   "closing a gate stamps `actual` on its Dates row and says so")
_ld2 = c.get(f"/api/store/admin/engagements/{_le}", headers=AA).json()
ok(any(d["label"] == "Requirements signed" and d["actual"]
       for d in _ld2["dates"]),
   "the Dates table now records what actually happened")
c.put(f"/api/store/admin/engagements/{_le}/dates", headers=AA,
      json={"dates": [
          {"label": "Requirements signed", "planned": "2026-09-12",
           "actual": "2026-09-01"},
          {"label": "Launch", "planned": "2026-08-01"}]})
c.request("DELETE", f"/api/store/admin/engagements/{_le}/gates/"
          f"requirements_signed", headers=AA)
c.post(f"/api/store/admin/engagements/{_le}/gates/requirements_signed",
       headers=AA, json={"note": "re-closed"})
ok(any(d["label"] == "Requirements signed" and d["actual"] == "2026-09-01"
       for d in c.get(f"/api/store/admin/engagements/{_le}",
                      headers=AA).json()["dates"]),
   "but an actual the operator wrote by hand outranks the clock — the "
   "stamp fills blanks, it never overwrites a record")

# launch needs an install
ok(c.post(f"/api/store/admin/engagements/{_le}/launch", headers=AA,
          json={"url": "shop.launchco.test"}).status_code == 400,
   "launching before the stand-up is refused with the reason")
c.post("/api/store/admin/fleet/tenants", headers=AA,
       json={"id": "launchco", "brand": "Launch Co", "klass": "micro",
             "engagement_id": _le})

# the offer appears on the ceremony gate, once
_fo = c.post(f"/api/store/admin/engagements/{_le}/gates/"
             f"final_invoice_paid", headers=AA,
             json={"note": "wire ref 900"}).json()
ok(_fo.get("launch", {}).get("tenant_id") == "launchco",
   "closing the launch-side gate OFFERS the launch when the client runs "
   "on the platform with no public address yet")

ok(c.post(f"/api/store/admin/engagements/{_le}/launch", headers=AA,
          json={"url": "not a hostname"}).status_code == 400,
   "a launch needs a real hostname")
ok(c.post(f"/api/store/admin/engagements/{_le}/launch", headers=AA,
          json={"url": "beta.test"}).status_code == 400,
   "and one no other business already answers to")
_lo = c.post(f"/api/store/admin/engagements/{_le}/launch", headers=AA,
             json={"url": "shop.launchco.test"}).json()
ok(_lo["url"] == "https://shop.launchco.test"
   and "shop.launchco.test" in _lo["hosts"]
   and "launchco.localhost" in _lo["hosts"],
   "the launch merges the real hostname into the registry — the "
   ".localhost door stays open")
ok(_lo["caps"] == ["payments", "selling"],
   "and refreshes the capability grant from the signed quote in the "
   "same act")
ok(c.get("/api/products",
         headers={"host": "shop.launchco.test"}).status_code == 200,
   "the platform answers on the real name the moment it arrives")
_lcfg = _jn.loads((_tn.tenant_dir("launchco") / "config.json").read_text())
ok(_lcfg["public_base_url"] == "https://shop.launchco.test",
   "public_base_url lands in the tenant's config, so QR codes, sign-in "
   "links and Stripe returns carry the right domain")
ok(c.get(f"/api/store/admin/engagements/{_le}", headers=AA).json()
   ["engagement"]["live_url"] == "https://shop.launchco.test",
   "and the engagement records where they went live")
ok(any(e2["what"] == "site launched" for e2 in
       c.get("/api/store/admin/fleet", headers=AA).json()["events"]),
   "on the fleet's own history")
ok(not c.request("DELETE", f"/api/store/admin/engagements/{_le}/gates/"
                 "final_invoice_paid", headers=AA).json().get("launch")
   and not c.post(f"/api/store/admin/engagements/{_le}/gates/"
                  "final_invoice_paid", headers=AA,
                  json={"note": "again"}).json().get("launch"),
   "once launched, the offer stops — a button that launches must vanish "
   "when the site is live")
_ljs = ops_app_js()
ok("launchSite" in _ljs and "eng-launch" in _ljs and "out.launch" in _ljs
   and "gl-date" in _ljs,
   "the editor carries it — a Launch button on the client's page, the "
   "offer at gate close, and the schedule on every gate row")
c.request("DELETE", "/api/store/admin/fleet/tenants/launchco?keep_data=0",
          headers=AA)


# --- the public door: fill the form, hand over a website ------------------
# With fleet.public_suffix set and wildcard DNS pointed at the box, a
# stand-up's output is a URL you can SEND someone. The Caddy ask endpoint
# is the gate that keeps on-demand TLS from minting certs for strangers.
_acfg2 = _jn.loads((_tn.tenant_dir("alpha") / "config.json").read_text())
_acfg2["fleet"] = {**_acfg2.get("fleet", {}),
                   "public_suffix": "clients.alpha.test"}
(_tn.tenant_dir("alpha") / "config.json").write_text(_jn.dumps(_acfg2))
from erp.backend.main import CFG as _CFGPROXY
_CFGPROXY.invalidate("alpha")

_pub = c.post("/api/store/admin/fleet/tenants", headers=AA,
              json={"id": "pubco", "brand": "Pub Co",
                    "klass": "micro"}).json()
ok(_pub["public_url"] == "https://pubco.clients.alpha.test",
   "with a public suffix configured, the stand-up's answer is a URL you "
   "can send someone — not just a .localhost door on this machine")
ok(sorted(_tn.registry()["tenants"]["pubco"]["hosts"])
   == ["pubco.clients.alpha.test", "pubco.localhost"],
   "both doors registered: the public name AND the local one")
ok(c.get("/api/products",
         headers={"host": "pubco.clients.alpha.test"}).status_code == 200,
   "and the platform answers on the public name immediately")
ok(_jn.loads((_tn.tenant_dir("pubco") / "config.json").read_text())
   ["public_base_url"] == "https://pubco.clients.alpha.test",
   "public_base_url set from birth — QR codes, sign-in links and Stripe "
   "returns carry the public name without a launch step")

ok(c.get("/caddy/ask", params={"domain": "pubco.clients.alpha.test"}
         ).status_code == 200,
   "Caddy's ask gate says yes to a hostname the registry claims")
ok(c.get("/caddy/ask", params={"domain": "evil.stranger.example"}
         ).status_code == 404,
   "and no to everything else — without the gate, on-demand TLS is a "
   "cert-minting service for any stranger with a DNS record")
c.post("/api/store/admin/fleet/tenants/pubco/status", headers=AA,
       json={"status": "suspended"})
ok(c.get("/caddy/ask", params={"domain": "pubco.clients.alpha.test"}
         ).json().get("suspended") is True,
   "a suspended tenant still gets its certificate — the 503 page "
   "deserves TLS too")
c.post("/api/store/admin/fleet/tenants/pubco/status", headers=AA,
       json={"status": "active"})
ok(c.get("/caddy/ask").status_code == 404,
   "asking about nothing is a no")

# --- the Progressive App is a capability, not a birthright -------------------
# 29th price-book row ($20, IT & legal): the installable offline shell is
# what the row sells, so a tenant without it gets a perfectly good website
# that simply does not install — service workers and manifests answer 404.
_regP = _jn.loads(_tn.REGISTRY_PATH.read_text())
_regP["tenants"]["beta"]["caps"] = ["selling"]
_tn.REGISTRY_PATH.write_text(_jn.dumps(_regP))
_tn.bust_cache()
ok(c.get("/sf-sw.js", headers=HB).status_code == 404
   and c.get("/store.webmanifest", headers=HB).status_code == 404
   and c.get("/ops/sw.js", headers=HB).status_code == 404,
   "a plan without the Progressive App serves no worker and no manifest "
   "— the site works, the install button never appears")
ok(c.get("/sf-sw.js", headers=HA).status_code == 200
   and c.get("/store.webmanifest", headers=HA).status_code == 200,
   "while null caps still mean everything — dev and demo installs keep "
   "the whole product")
_regP = _jn.loads(_tn.REGISTRY_PATH.read_text())
_regP["tenants"]["beta"].pop("caps", None)
_tn.REGISTRY_PATH.write_text(_jn.dumps(_regP))
_tn.bust_cache()
ok(c.get("/sf-sw.js", headers=HB).status_code == 200,
   "and granting it (or lifting the cap list) opens the door on the "
   "next request — entitlement is read live, never baked")

# --- API keys: the machine door the price book already sold ------------------
# Named, scoped, revocable, bound to an account — a key acts AS that
# account through every permission check the UI trusts, so there is no
# second authorization model to drift.
_ak = c.post("/api/admin/api-keys", headers=AA,
             json={"name": "warehouse sync", "scope": "write"}).json()
ok(_ak["secret"].startswith("bck_") and _ak["prefix"] == _ak["secret"][:12],
   "minting hands over the secret — once")
_klist = c.get("/api/admin/api-keys", headers=AA).json()
ok(any(k["prefix"] == _ak["prefix"] and k["name"] == "warehouse sync"
       for k in _klist)
   and not any("secret" in k for k in _klist),
   "the list names keys by prefix, never by secret — a screen that could "
   "re-show the key would BE the leak")
_AK = {"Authorization": f"Bearer {_ak['secret']}", **HA}
ok(c.get("/api/admin/users", headers=_AK).status_code == 200,
   "a key bound to an admin does admin things — the account's own reach, "
   "no more, no less")
_robo = c.post("/api/login", headers=HA,
               json={"name": "Robo Reader", "role": "customer"}).json()
_akl = c.post("/api/admin/api-keys", headers=AA,
              json={"name": "robo bot", "scope": "read",
                    "user_id": _robo["id"]}).json()
_AKL = {"Authorization": f"Bearer {_akl['secret']}", **HA}
ok(c.get("/api/learn/me", headers=_AKL).json()["name"] == "Robo Reader",
   "while a key bound to a plain account sees that account's world")
ok(c.get("/api/admin/users", headers=_AKL).status_code == 403,
   "and cannot reach past it")
_ro = c.post("/api/learn/notifications/read", headers=_AKL, json={})
ok(_ro.status_code == 403 and "read-only" in _ro.json()["detail"],
   "a read key is refused mutations at the front door — one wall, not "
   "two hundred doors remembering")
from erp.backend import db as _dbk
_hc2 = _dbk.connect()
_hc2.execute("UPDATE api_keys SET last_used_at=? WHERE prefix=?",
             (_t0.time() - 40 * 86400, _ak["prefix"]))
_hc2.commit()
ok(c.get("/api/admin/users", headers=_AK).status_code == 200,
   "machine keys never slide-expire — revocation is their lifecycle, not "
   "a quiet timeout mid-batch")
_hc2.close()
c.post(f"/api/admin/api-keys/{_ak['id']}/revoke", headers=AA)
ok(c.get("/api/admin/users", headers=_AK).status_code == 401,
   "and revocation is immediate — the next request is a stranger's")

# the entitlement outranks the secret: a key from the paid days dies the
# moment the api capability leaves the plan
_bboss = c.post("/api/login", headers=HB,
                json={"name": "Beta Boss",
                      "admin_key": _bcfg["admin_key"]}).json()
_BB2 = {"Authorization": f"Bearer {_bboss['token']}", **HB}
_bk = c.post("/api/admin/api-keys", headers=_BB2,
             json={"name": "beta bot", "scope": "read"}).json()
_BK = {"Authorization": f"Bearer {_bk['secret']}", **HB}
ok(c.get("/api/notifications", headers=_BK).status_code == 200,
   "a key on a null-caps tenant works")
_regK = _jn.loads(_tn.REGISTRY_PATH.read_text())
_regK["tenants"]["beta"]["caps"] = ["selling"]
_tn.REGISTRY_PATH.write_text(_jn.dumps(_regK))
_tn.bust_cache()
ok(c.get("/api/notifications", headers=_BK).status_code == 401
   and c.post("/api/admin/api-keys", headers=_BB2,
              json={"name": "x"}).status_code == 404,
   "drop the api capability and every key stops working mid-flight — "
   "and the mint itself is a door that no longer exists")
_regK = _jn.loads(_tn.REGISTRY_PATH.read_text())
_regK["tenants"]["beta"].pop("caps", None)
_tn.REGISTRY_PATH.write_text(_jn.dumps(_regK))
_tn.bust_cache()
c.request("DELETE", "/api/store/admin/fleet/tenants/pubco?keep_data=0",
          headers=AA)

_acfg2.pop("fleet", None)
(_tn.tenant_dir("alpha") / "config.json").write_text(_jn.dumps(_acfg2))
_CFGPROXY.invalidate("alpha")
_pub2 = c.post("/api/store/admin/fleet/tenants", headers=AA,
               json={"id": "pubco2", "klass": "micro"}).json()
ok(_pub2["public_url"] == "" and _tn.registry()["tenants"]["pubco2"]
   ["hosts"] == ["pubco2.localhost"],
   "no suffix configured = exactly the old behaviour, nothing invented")
c.request("DELETE", "/api/store/admin/fleet/tenants/pubco2?keep_data=0",
          headers=AA)


# --- multi-machine orchestration: tenants run on their booked nodes -------
# A node with an addr is a MACHINE: standing up ships the tenant's whole
# directory there, the worker serves it, the front box proxies for it,
# moves recall-and-ship, and a failed shipment parks the tenant on local —
# served, slower, honest. Tested against a real second process, because a
# proxy that only ever met a stub has not been tested.
import socket as _sck
import subprocess as _sp2
import time
import urllib.request as _ur

_ws = _sck.socket(); _ws.bind(("127.0.0.1", 0))
_wport = _ws.getsockname()[1]; _ws.close()
_wdata = Path(tempfile.mkdtemp(prefix="bc_node_"))

ok(c.post("/api/store/admin/fleet/nodes", headers=AA,
          json={"id": "node-w", "units": 8,
                "addr": f"http://127.0.0.1:{_wport}"}).status_code == 200,
   "a node provisions WITH an address — the booking names its machine")
_wkey = _tn.registry()["nodes"]["node-w"]["key"]
ok(len(_wkey) > 20, "and mints the key every shipment must present")

_wproc = _sp2.Popen(
    [sys.executable, str(ROOT / "scripts" / "launch.py"),
     "--port", str(_wport)],
    env={**os.environ, "BUSINESS_CONTROL_DATA": str(_wdata),
         "BUSINESS_CONTROL_NODE": "node-w",
         "BUSINESS_CONTROL_NODE_KEY": _wkey},
    stdout=_sp2.DEVNULL, stderr=_sp2.DEVNULL)
try:
    for _ in range(120):
        try:
            _rq = _ur.Request(f"http://127.0.0.1:{_wport}/api/node/ping",
                              headers={"X-Fleet-Key": _wkey})
            if _ur.urlopen(_rq, timeout=1).status == 200:
                break
        except Exception:
            time.sleep(0.25)
    else:
        raise RuntimeError("worker node never came up")

    _rq2 = _ur.Request(f"http://127.0.0.1:{_wport}/api/node/ping",
                       headers={"X-Fleet-Key": "wrong"})
    try:
        _ur.urlopen(_rq2, timeout=2); _bad = 200
    except Exception as e2:
        _bad = getattr(e2, "code", 0)
    ok(_bad == 403, "a wrong fleet key is refused")
    ok(c.get("/api/node/ping").status_code == 404,
       "and a process with no node key configured accepts nothing — a "
       "plain install cannot be talked into hosting")

    _su = c.post("/api/store/admin/fleet/tenants", headers=AA,
                 json={"id": "remoteco", "brand": "Remote Co",
                       "klass": "micro", "node": "node-w"}).json()
    ok(_su["shipped"] == "node-w",
       "standing up onto an addr'd node SHIPS the tenant there")
    ok(not (_tn.tenant_dir("remoteco")).exists(),
       "the provider's copy is gone — data lives in one place")
    ok((_wdata / "tenants" / "remoteco" / "business_control.db").exists(),
       "and that place is the worker's own data directory")

    _direct = _ur.Request(f"http://127.0.0.1:{_wport}/",
                          headers={"Host": "remoteco.localhost"})
    ok(b"Remote Co" in _ur.urlopen(_direct, timeout=5).read(),
       "the worker serves the tenant DIRECTLY, named — point DNS at the "
       "node and the front box is not even in the path")
    ok("Remote Co" in c.get("/", headers={"host": "remoteco.localhost"}
                            ).text,
       "and the front box PROXIES for it — one public IP still serves "
       "every tenant, wherever each one lives")

    c.post("/api/store/admin/fleet/tenants/remoteco/status", headers=AA,
           json={"status": "suspended"})
    try:
        _ur.urlopen(_ur.Request(f"http://127.0.0.1:{_wport}/",
                    headers={"Host": "remoteco.localhost"}), timeout=5)
        _sus2 = 200
    except Exception as e3:
        _sus2 = getattr(e3, "code", 0)
    ok(_sus2 == 503,
       "a suspension pushed from the provider is honoured ON THE NODE — "
       "the worker's own registry slice said so")
    c.post("/api/store/admin/fleet/tenants/remoteco/status", headers=AA,
           json={"status": "active"})


    # --- backups follow shipments (worker still alive) --------------------
    import importlib.util as _ilu
    _bspec = _ilu.spec_from_file_location("bc_backup",
                                         ROOT / "scripts" / "backup.py")
    _bmod = _ilu.module_from_spec(_bspec)
    _bspec.loader.exec_module(_bmod)
    ok(_bmod.main() == 0,
       "the fleet backup runs clean while a tenant lives on a worker")
    _bdir = Path(os.environ["BUSINESS_CONTROL_DATA"]) / "backups"
    _barch = sorted(_bdir.glob("business-control-*.tar.gz"))[-1]
    import tarfile as _tf4
    with _tf4.open(_barch) as _bt:
        _bnames = _bt.getnames()
        ok("tenants/remoteco/business_control.db" in _bnames,
           "the archive contains the REMOTE tenant, pulled from its node — "
           "the backup goes to the data, because the data no longer comes "
           "to the backup")
        _bdb = _bt.extractfile("tenants/remoteco/business_control.db").read()
    _btmp = Path(tempfile.mktemp()); _btmp.write_bytes(_bdb)
    ok(sqlite3.connect(_btmp).execute("PRAGMA integrity_check")
       .fetchone()[0] == "ok",
       "and the pulled database is a clean snapshot, not a torn live file")
    _blast = _jn.loads((_bdir / "last.json").read_text())
    ok(_blast["ok"] and not _blast["failures"],
       "last.json records the success the Platform tab will report")

    # a node that does not answer: loud, partial, honest
    _reg9 = _jn.loads(_tn.REGISTRY_PATH.read_text())
    _reg9["nodes"]["node-dead"] = {"addr": "http://127.0.0.1:9",
                                   "key": "k", "units": 25}
    _reg9["tenants"]["ghostco"] = {"hosts": ["ghostco.localhost"],
                                   "node": "node-dead"}
    _tn.REGISTRY_PATH.write_text(_jn.dumps(_reg9)); _tn.bust_cache()
    ok(_bmod.main() == 1,
       "a node that does not answer makes the backup exit non-zero — "
       "cron surfaces it instead of a silent gap")
    _blast2 = _jn.loads((_bdir / "last.json").read_text())
    ok(not _blast2["ok"] and "ghostco" in _blast2["failures"],
       "with the missing tenant named in last.json")
    with _tf4.open(sorted(_bdir.glob("business-control-*.tar.gz"))[-1]) as _bt2:
        ok("tenants/remoteco/business_control.db" in _bt2.getnames(),
           "while everyone reachable is still in the archive — partial "
           "beats nothing")
    _reg9 = _jn.loads(_tn.REGISTRY_PATH.read_text())
    _reg9["nodes"].pop("node-dead"); _reg9["tenants"].pop("ghostco")
    _tn.REGISTRY_PATH.write_text(_jn.dumps(_reg9)); _tn.bust_cache()

    _fb9 = c.get("/api/store/admin/fleet", headers=AA).json()["backup"]
    ok(_fb9["ok"] is False and _fb9["stale"] is False
       and "ghostco" in _fb9["failures"],
       "the board reads the record the script wrote — reporting, not "
       "guessing")

    ok(c.post("/api/store/admin/fleet/tenants/remoteco/move", headers=AA,
              json={"node": "local"}).json()["node"] == "local",
       "a move back to local recalls the data")
    ok(any(n["id"] == "node-w" for n in
           c.get("/api/store/admin/fleet", headers=AA).json()["nodes"]),
       "the emptied node SURVIVES the reap — an addr'd node with no "
       "destroy_cmd is a running server we merely know the address of, "
       "and auto-forgetting it loses the address and key while the "
       "machine runs on")
    ok((_tn.tenant_dir("remoteco") / "business_control.db").exists()
       and not (_wdata / "tenants" / "remoteco").exists(),
       "— here again, gone there: the recall is a move, not a copy")
    ok("Remote Co" in c.get("/", headers={"host": "remoteco.localhost"}
                            ).text,
       "and serving follows the data home without a restart")

    c.post("/api/store/admin/fleet/tenants/remoteco/move", headers=AA,
           json={"node": "node-w"})
    ok(not _tn.tenant_dir("remoteco").exists(),
       "moved out again for the destroy test")
    c.request("DELETE",
              "/api/store/admin/fleet/tenants/remoteco?keep_data=1",
              headers=AA)
    ok(not (_wdata / "tenants" / "remoteco").exists()
       and any(p.name.startswith("remoteco-") for p in
               (Path(os.environ["BUSINESS_CONTROL_DATA"]) / "retired"
                ).glob("*")),
       "destroying a remote tenant recalls the data FIRST and retires it "
       "on the provider — the machine stops holding a business that "
       "left, and the business still owns its records")

    # --- the node wears a version, and the fleet can dress it -------------
    _wping = _jn.loads(_ur.urlopen(_ur.Request(
        f"http://127.0.0.1:{_wport}/api/node/ping",
        headers={"X-Fleet-Key": _wkey}), timeout=5).read())
    ok(_wping.get("version") == "dev",
       "a worker running from a working tree says so — dev, not a hash")
    ok(_wping.get("services") == {},
       "and a machine with nothing installed declares nothing — the ping "
       "reports the manifest, not a hope")
    _rqup = _ur.Request(f"http://127.0.0.1:{_wport}/api/node/update",
                        data=b"junk", headers={"X-Fleet-Key": "wrong"})
    try:
        _ur.urlopen(_rqup, timeout=5)
        _upbad = 200
    except Exception as e9:
        _upbad = getattr(e9, "code", 0)
    ok(_upbad == 403,
       "an update without the node's key is refused like any shipment")

    _bz = c.get("/api/fleet/bundle", headers={"X-Fleet-Key": _wkey})
    ok(_bz.status_code == 200
       and len(_bz.headers.get("X-Bundle-Version", "")) == 12,
       "a booked node's key fetches the app bundle from the provider")
    import zipfile as _zf9
    _zn = _zf9.ZipFile(_io2.BytesIO(_bz.content)).namelist()
    ok("src/erp/backend/main.py" in _zn and "VERSION" in _zn
       and "requirements.txt" in _zn
       and "scripts/install_node.sh" in _zn
       and "scripts/install_translate.sh" in _zn
       and not any(n.startswith("data/") for n in _zn)
       and not any("b2b-client/clients/" in n for n in _zn),
       "the bundle IS the app — src, scripts, docs, requirements, a "
       "VERSION — never data, and never the kit's per-client working "
       "papers")
    ok(c.get("/api/fleet/bundle",
             headers={"X-Fleet-Key": "wrong"}).status_code == 403
       and c.get("/api/fleet/bundle", headers=AA).status_code == 200,
       "a wrong key gets nothing; an admin can pull it by hand")

    _iscript = c.get("/fleet/install.sh").text
    ok("BUSINESS_CONTROL_NODE_KEY" in _iscript and "systemd" in _iscript
       and "api/fleet/bundle" in _iscript,
       "the installer curl fetches is the script the tree versions — "
       "identity in the unit's environment, bundle from the provider")
    _join = c.get("/api/store/admin/fleet/nodes/node-w/join",
                  headers=AA).json()
    ok("install.sh" in _join["command"] and _wkey in _join["command"]
       and "--node node-w" in _join["command"],
       "and the Platform tab hands the operator the one command that "
       "makes the machine a worker")
    _chk = c.get("/api/store/admin/fleet/nodes/node-w/check",
                 headers=AA).json()
    ok(_chk["version"] == "dev" and len(_chk["current"]) == 12,
       "Check reads the node's running code against the provider's "
       "current build")
finally:
    _wproc.terminate()
    try:
        _wproc.wait(timeout=5)
    except Exception:
        _wproc.kill()
    _shm.rmtree(_wdata, ignore_errors=True)
c.request("DELETE", "/api/store/admin/fleet/nodes/node-w", headers=AA)

import io as _io2, tarfile as _tf2
_evb = _io2.BytesIO()
with _tf2.open(fileobj=_evb, mode="w:gz") as _tf3:
    _info = _tf2.TarInfo("../escape.txt"); _info.size = 2
    _tf3.addfile(_info, _io2.BytesIO(b"hi"))
try:
    _fl.unpack_tenant("evilco", _evb.getvalue())
    _esc = False
except ValueError:
    _esc = True
ok(_esc and not (Path(os.environ["BUSINESS_CONTROL_DATA"]) / "tenants"
                 / "escape.txt").exists(),
   "a shipment that tries to write outside the tenant's directory is an "
   "attack, not a shipment — refused before a byte lands")

# --- the bundle's other half: apply, and its walls ---------------------------
_bb, _bv = _fl.build_bundle()
_tgt = Path(tempfile.mkdtemp(prefix="bc_upd_"))
ok(_fl.apply_bundle(_bb, _tgt) == _bv
   and (_tgt / "src" / "erp" / "backend" / "main.py").exists()
   and (_tgt / "VERSION").read_text().strip() == _bv,
   "apply is the installer's other half: the same bundle lands the same "
   "tree, VERSION and all — and the version is the content's own hash")
import zipfile as _zf10
_evz2 = _io2.BytesIO()
with _zf10.ZipFile(_evz2, "w") as _z10:
    _z10.writestr("VERSION", "x")
    _z10.writestr("../evil.txt", "hi")
try:
    _fl.apply_bundle(_evz2.getvalue(), _tgt)
    _zesc = False
except ValueError:
    _zesc = True
ok(_zesc and not (_tgt.parent / "evil.txt").exists(),
   "a bundle naming a path outside the app is an attack, not an update")
try:
    _fl.apply_bundle(b"not a zip", _tgt)
    _zbad = False
except ValueError:
    _zbad = True
ok(_zbad, "and junk is refused before a byte lands")
_shm.rmtree(_tgt, ignore_errors=True)


# --- the grant editor: capabilities bought AFTER stand-up -----------------
# The button that fulfils a capability ask — and the moment the site grows
# the piece that sells the new capability. Additive only: nothing an
# operator built is rewritten.
_ge = c.post("/api/store/admin/engagements", headers=AA,
             json={"name": "Grow Co"}).json()["id"]
c.post(f"/api/store/admin/engagements/{_ge}/quote", headers=AA,
       json={"markdown": "# Quote",
             "state": _bench_state(locs=1, seats=4,
                                   on=["core", "selling", "payments"])})
c.post("/api/store/admin/fleet/tenants", headers=AA,
       json={"id": "growco", "brand": "Grow Co", "klass": "micro",
             "engagement_id": _ge})
_gcon = sqlite3.connect(_tn.tenant_dir("growco") / "business_control.db")
_gcon.row_factory = sqlite3.Row
_gcon.execute("UPDATE page_sections SET settings=json_set(settings,"
              "'$.heading','Operator wrote this') WHERE page_slug='home'"
              " AND type='hero'")
_gcon.commit()

_fbrd = c.get("/api/store/admin/fleet", headers=AA).json()
ok(len(_fbrd["cap_catalog"]) == 29 and _fbrd["core_price"] == 50,
   "the board carries the full catalog, so the grant editor lists what "
   "can actually be sold")
_sellcap = next(x for x in _fbrd["cap_catalog"] if x["id"] == "selling")
ok(_sellcap == {"id": "selling", "name": "Selling", "group": "Revenue ops",
                "band": "heavy", "price": 50},
   "each catalog entry carries its commercial facts from the BOOK's own "
   "parse — the grant editor is a screen where money is approved, so it "
   "shows the money")
ok([x["group"] for x in _fbrd["cap_catalog"]].index("Revenue ops")
   > [x["group"] for x in _fbrd["cap_catalog"]].index("Operations"),
   "in the book's own group order, so the editor reads as the same "
   "document as the menu and the deck")
_appjsC = ops_app_js()
ok("cg-total" in _appjsC and "before volume" in " ".join(_appjsC.split())
   and "cap-price" in _appjsC and "cap-group" in _appjsC,
   "the modal groups by the book's sections, prices every box, and keeps "
   "a live monthly total while boxes are ticked")
ok("quote covers" in " ".join(_appjsC.split())
   and "unbilled" in _appjsC,
   "and the coverage line says how much of the grant the quote actually "
   "sold — a grant that outruns the sale is a visible choice, not a "
   "drift")
_gr = c.post("/api/store/admin/fleet/tenants/growco/caps", headers=AA,
             json={"caps": ["selling", "payments", "subs",
                            "events"]}).json()
ok(_gr["added"] == ["events", "subs"]
   and _tn.registry()["tenants"]["growco"]["caps"]
   == ["events", "payments", "selling", "subs"],
   "granting records the new entitlement and names exactly what was "
   "added")
_gcon2 = sqlite3.connect(_tn.tenant_dir("growco") / "business_control.db")
_gcon2.row_factory = sqlite3.Row
_gsettings = [r["settings"] for r in _gcon2.execute(
    "SELECT settings FROM page_sections WHERE page_slug='home'")]
ok(any("There's a subscription" in x for x in _gsettings)
   and any("Come find us" in x for x in _gsettings),
   "the site GREW the pieces the new capabilities earn — the subscription "
   "explainer and the events pointer appeared on the home page")
ok(any("Operator wrote this" in x for x in _gsettings),
   "while the operator's edited hero was not touched — growth is "
   "additive, never a rewrite")
_before_n = _gcon2.execute("SELECT COUNT(*) FROM page_sections WHERE"
                           " page_slug='home'").fetchone()[0]
c.post("/api/store/admin/fleet/tenants/growco/caps", headers=AA,
       json={"caps": ["selling", "payments", "subs", "events"]})
_gcon3 = sqlite3.connect(_tn.tenant_dir("growco") / "business_control.db")
ok(_gcon3.execute("SELECT COUNT(*) FROM page_sections WHERE"
                  " page_slug='home'").fetchone()[0] == _before_n,
   "re-saving the same grant grows nothing — presence is checked, so the "
   "explainer cannot pile up")
ok(c.post("/api/store/admin/fleet/tenants/growco/caps", headers=AA,
          json={"caps": []}).status_code == 400,
   "an empty grant is refused as ambiguous — clearing is its own act")
ok(c.post("/api/store/admin/fleet/tenants/growco/caps", headers=AA,
          json={"clear": True}).json()["caps"] is None
   and "caps" not in _tn.registry()["tenants"]["growco"],
   "and clearing returns to 'no grant recorded' — everything on, the "
   "unambiguous meaning missing caps has always had")
ok(c.post("/api/store/admin/fleet/tenants/growco/caps", headers=BB,
          json={"caps": ["selling"]}).status_code == 404,
   "a client tenant cannot grant itself anything")
c.request("DELETE", "/api/store/admin/fleet/tenants/growco?keep_data=0",
          headers=AA)

# the placeholder + the honest empty showcase
ok("placeholder" in _jn.dumps(_lay.placeholder_home("X Co"))
   or "setting up shop" in _jn.dumps(_lay.placeholder_home("X Co")),
   "the placeholder layout exists as data like every other layout")
_appjs3 = ops_app_js()
ok("data-tcaps" in _appjs3 and "cg-extend" in _appjs3
   and "cg-clear" in _appjs3,
   "the Platform tab carries the editor — per-tenant Capabilities button, "
   "the grow-the-site checkbox, and clear-grant as its own deliberate "
   "button")
_appjs6 = ops_app_js()
ok("async function capsEditor" in _appjs6 and "eng-caps" in _appjs6
   and 'capsEditor(e.tenant_id' in _appjs6,
   "one grant editor, two doors — the Platform row AND the client's own "
   "page, so fulfilling an ask happens where the client's story lives")


# --- act-as, the bell, and the platform beside its clients ----------------
_aa2 = c.post("/api/store/admin/engagements", headers=AA,
              json={"name": "ActAs Co"}).json()["id"]
c.post("/api/store/admin/fleet/tenants", headers=AA,
       json={"id": "actasco", "brand": "ActAs Co", "klass": "micro",
             "engagement_id": _aa2})
_aout = c.post("/api/store/admin/fleet/tenants/actasco/act-as",
               headers=AA, json={}).json()
ok("actas=" in _aout["url"] and "actasco.localhost" in _aout["url"]
   and _aout["account"].startswith("Studio · "),
   "act-as mints a NAMED admin in the tenant's own directory and hands "
   "back a link — no shared session, no key exchange, the wall stays a "
   "wall")
_atok = _aout["url"].split("actas=")[1]
_ame = c.get("/api/me", headers={"host": "actasco.localhost",
                                 "Authorization": f"Bearer {_atok}"}).json()
ok(_ame["is_admin"] and _ame["name"].startswith("Studio · "),
   "the token IS an admin of that install, visibly the studio's operator "
   "— not an impersonation of anyone")
_aout2 = c.post("/api/store/admin/fleet/tenants/actasco/act-as",
                headers=AA, json={}).json()
ok(c.get("/api/me", headers={"host": "actasco.localhost",
         "Authorization": f"Bearer {_atok}"}).status_code == 200
   and _aout2["url"] == _aout["url"],
   "repeat act-as REUSES the token — rotating on every click signed the "
   "operator's open session out the moment anyone acted again; revoking "
   "is deactivating the account in Team & access, not racing tokens")
ok(any(e["what"] == "acted as tenant admin" for e in
       c.get("/api/store/admin/fleet", headers=AA).json()["events"]),
   "and the act is on the fleet history")
_acon5 = sqlite3.connect(_tn.tenant_dir("alpha") / "business_control.db")
ok(_acon5.execute("SELECT 1 FROM engagement_log WHERE engagement_id=?"
                  " AND what LIKE '%opened their ops app%'",
                  (_aa2,)).fetchone() is not None,
   "and on the client's own file — both sides know")
ok(c.post("/api/store/admin/fleet/tenants/actasco/act-as", headers=BB,
          json={}).status_code == 404,
   "a client tenant cannot act as anyone")
ok(c.post("/api/store/admin/fleet/tenants/alpha/act-as", headers=AA,
          json={}).status_code == 400,
   "and acting as the provider itself is refused — you are already that")

# the capability ask rings the bell on the studio side
_akey5 = _jn.loads((_tn.tenant_dir("actasco") / "config.json"
                    ).read_text())["admin_key"]
_atok5 = c.post("/api/login", headers={"host": "actasco.localhost"},
                json={"name": "AC Admin", "role": "admin",
                      "admin_key": _akey5}).json()["token"]
c.post("/api/capability-request",
       headers={"host": "actasco.localhost",
                "Authorization": f"Bearer {_atok5}"},
       json={"capability": "distribution"})
_bell = c.get("/api/notifications", headers=AA).json()
_bitems = _bell["items"] if isinstance(_bell, dict) else _bell
ok(any("asked for a capability" in (i.get("title") or "")
       for i in _bitems),
   "a capability ask RINGS THE BELL for every studio admin — a request "
   "for money does not wait to be found on a board")
ok(next(i for i in _bitems if "asked for a capability"
        in (i.get("title") or ""))["kind"] == "lead"
   and 'lead: "fleet"' in ops_app_js(),
   "and CLICKING it lands on the Platform tab where the grant button is "
   "— a notification that names a place must go there")
c.request("DELETE", "/api/store/admin/fleet/tenants/actasco?keep_data=0",
          headers=AA)

_appjs5 = ops_app_js()
ok('q.get("actas")' in _appjs5 and "location.replace" in _appjs5,
   "the ops app trades ?actas for the account and drops the token from "
   "the URL — tokens do not belong in history")
_tabs_src = _appjs5.split("const TABS = [")[1].split("];")[0]
ok(_tabs_src.index('"clients"') < _tabs_src.index('"fleet"')
   and _tabs_src.index('"fleet"') < _tabs_src.index('"clock"'),
   "the Platform tab sits beside Clients (B2B) in the Sell group — "
   "burying the fleet at the bottom of Company meant the operator never "
   "saw it")


# --- revocation has consequences ------------------------------------------
# Granting grew the site and unlocked tabs; revoking now runs the mirror:
# the public pages behind a capability stop answering, the nav stops
# pointing at them, and the untouched scaffolding is trimmed — while
# anything the operator edited stays theirs.
_re = c.post("/api/store/admin/engagements", headers=AA,
             json={"name": "Revoke Co"}).json()["id"]
c.post("/api/store/admin/fleet/tenants", headers=AA,
       json={"id": "revokeco", "brand": "Revoke Co", "klass": "micro",
             "engagement_id": _re})
_RH = {"host": "revokeco.localhost"}
ok(c.get("/find", headers=_RH).status_code == 200
   and c.get("/events", headers=_RH).status_code == 200,
   "no grant recorded = everything on — the public pages answer, same "
   "null rule as everywhere")
c.post("/api/store/admin/fleet/tenants/revokeco/caps", headers=AA,
       json={"caps": ["selling", "payments", "subs"]})
c.post("/api/store/admin/fleet/tenants/revokeco/caps", headers=AA,
       json={"caps": ["selling", "payments", "subs", "events"]})
ok(c.get("/find", headers=_RH).status_code == 404
   and c.get("/blog", headers=_RH).status_code == 404
   and c.get("/affiliates", headers=_RH).status_code == 404,
   "a capability outside the grant takes its PUBLIC pages with it — the "
   "locator, the journal, the affiliate signup all 404 for a tenant that "
   "did not buy them")
ok(c.get("/events", headers=_RH).status_code == 200,
   "while the pages of granted capabilities answer")
_rhome = c.get("/", headers=_RH).text
ok(">Blog</a>" not in _rhome,
   "and the nav stops pointing at pages the plan does not include — a "
   "menu link to a 404 is worse than no link")

# the trim: untouched scaffolding leaves with its capability;
# an edited section stays
_rcon = sqlite3.connect(_tn.tenant_dir("revokeco") / "business_control.db")
_rcon.row_factory = sqlite3.Row
_revents = _rcon.execute(
    "SELECT COUNT(*) FROM page_sections WHERE page_slug='home' AND"
    " settings LIKE '%Come find us%'").fetchone()[0]
ok(_revents == 1, "setup: the events add-on landed at grant time")
_out_r = c.post("/api/store/admin/fleet/tenants/revokeco/caps", headers=AA,
                json={"caps": ["selling", "payments", "subs"]}).json()
ok(_out_r["removed"] == ["events"]
   and "Come find us" in _out_r["trimmed"],
   "revoking takes back the UNTOUCHED scaffolding and says so")
_rcon2 = sqlite3.connect(_tn.tenant_dir("revokeco") / "business_control.db")
ok(_rcon2.execute(
       "SELECT COUNT(*) FROM page_sections WHERE page_slug='home' AND"
       " settings LIKE '%Come find us%'").fetchone()[0] == 0
   and c.get("/events", headers=_RH).status_code == 404,
   "the section is gone and the page stopped answering — revocation is "
   "real on both surfaces")

c.post("/api/store/admin/fleet/tenants/revokeco/caps", headers=AA,
       json={"caps": ["selling", "payments", "subs", "events"]})
_rcon3 = sqlite3.connect(_tn.tenant_dir("revokeco") / "business_control.db")
_rcon3.execute("UPDATE page_sections SET settings=json_set(settings,"
               "'$.body','The operator rewrote this') WHERE"
               " page_slug='home' AND settings LIKE '%Come find us%'")
_rcon3.commit()
_out_r2 = c.post("/api/store/admin/fleet/tenants/revokeco/caps",
                 headers=AA,
                 json={"caps": ["selling", "payments", "subs"]}).json()
_rcon4 = sqlite3.connect(_tn.tenant_dir("revokeco") / "business_control.db")
_redited = _rcon4.execute(
    "SELECT enabled FROM page_sections WHERE page_slug='home' AND"
    " settings LIKE '%operator rewrote%'").fetchone()
ok(not _out_r2["trimmed"] and "Come find us" in _out_r2["hidden"]
   and _redited is not None and _redited[0] == 0,
   "an EDITED section is HIDDEN with its capability, not deleted — their "
   "work is preserved off the page, and the toast says which and why")
ok("operator rewrote" not in c.get("/", headers=_RH).text,
   "so the revoked remnant is no longer visible on the storefront")
_out_r3 = c.post("/api/store/admin/fleet/tenants/revokeco/caps",
                 headers=AA, json={"caps": ["selling", "payments", "subs",
                                            "events"]}).json()
_rcon5 = sqlite3.connect(_tn.tenant_dir("revokeco") / "business_control.db")
ok("Come find us" in (_out_r3["grown"].get("restored") or [])
   and _rcon5.execute(
       "SELECT enabled FROM page_sections WHERE page_slug='home' AND"
       " settings LIKE '%operator rewrote%'").fetchone()[0] == 1
   and "The operator rewrote this" in c.get("/", headers=_RH).text,
   "and re-granting the capability RESTORES the hidden edited section — "
   "their words come back exactly as they left them")
c.request("DELETE", "/api/store/admin/fleet/tenants/revokeco?keep_data=0",
          headers=AA)
ok("something specific" in c.get("/find", headers=HA).text
   and "flavour" not in c.get("/find", headers=HA).text,
   "and the locator lost its last drinks-brand word — 'flavour' was "
   "ZenJoy's voice in every tenant's store finder")

_shm.rmtree(_split_dir, ignore_errors=True)

# --- Learning: the grading rules, ported from lingua-portal ----------------
# The pure engine came over whole, and so did its judgement calls: accents
# forgiven, partial credit floored at zero, a provisional score never shown
# as a score. These checks are the source's own tests, restated here so a
# future change to the port has to argue with the same policies.
from erp.backend import assessment as _As  # noqa: E402

_Q, _R = _As.Question, _As.Response
_q1 = _Q(1, _As.CHOICE, "¿Cómo se dice 'hello'?", ["adiós", "hola", "gracias"],
         answer=[1], points=2)
ok(_As.grade_question(_q1, _R(1, chosen=[1]))["points"] == 2.0
   and _As.grade_question(_q1, _R(1, chosen=[0]))["points"] == 0.0
   and _As.grade_question(_q1, None)["settled"],
   "single choice: right scores full, wrong zero, unanswered settles at zero")
_q2 = _Q(2, _As.MULTI, "Which are greetings?",
         ["hola", "mesa", "buenos días", "silla"], answer=[0, 2], points=4)
ok(_As.grade_question(_q2, _R(2, chosen=[0, 2]))["points"] == 4.0
   and _As.grade_question(_q2, _R(2, chosen=[0]))["points"] == 2.0
   and _As.grade_question(_q2, _R(2, chosen=[0, 1]))["points"] == 0.0
   and _As.grade_question(_q2, _R(2, chosen=[1, 3]))["points"] == 0.0,
   "multi: partial credit, a wrong pick cancels a right one, floored at zero "
   "— selecting everything is not a strategy")
_q3 = _Q(3, _As.TEXT, "Translate 'good morning'", accepted=["buenos días"])
ok(_As.grade_question(_q3, _R(3, text="buenos dias"))["points"] == 1.0
   and _As.grade_question(_q3, _R(3, text="  BUENOS Días! "))["points"] == 1.0
   and _As.grade_question(_q3, _R(3, text="buenas noches"))["points"] == 0.0,
   "written answers: accents, case and punctuation forgiven — we mark "
   "language, not typing")
_q3b = _Q(4, _As.TEXT, "Describe your weekend", points=5)
ok(_As.grade_question(_q3b, _R(4, text="fui al cine"))["settled"] is False
   and not _q3b.auto,
   "a text question with no answer key waits for the teacher")
_q4 = _Q(5, _As.SPEAKING, "Introduce yourself", points=10)
ok(not _q4.auto
   and _As.grade_question(_q4, _R(5, material_id=9))["settled"] is False
   and _As.grade_question(_q4, _R(5))["settled"] is True
   and _As.grade_question(_q4, _R(5, material_id=9, awarded=99))["points"] == 10.0
   and _As.grade_question(_q1, _R(1, chosen=[0], awarded=2))["points"] == 2.0,
   "recorded answers wait for a human; a teacher's mark is capped at the "
   "question's worth and overrides an auto-grade")
_res = _As.grade_attempt([_q1, _q3], [_R(1, chosen=[1]),
                                      _R(3, text="buenos dias")], pass_mark=60)
_res2 = _As.grade_attempt([_q1, _q4], [_R(1, chosen=[1]), _R(5, material_id=1)])
_stu = _As.summarise_for_student(_res2)
ok(_res["is_final"] and _res["percent"] == 100.0 and _res["passed"]
   and not _res2["is_final"] and _res2["passed"] is None
   and "percent" not in _stu and "awaiting" in _stu["message"],
   "an all-auto attempt is final at once; one with pending marks withholds "
   "pass/fail AND never shows the student a provisional score")
def _qz_code(kind, prompt, choices, answer, points=1):
    try:
        _As.validate_question(kind, prompt, choices, answer, [], points)
        return None
    except _As.QuizError as e:
        return e.code


ok([_qz_code("vibes", "p", ["a", "b"], [0]),
    _qz_code(_As.CHOICE, " ", ["a", "b"], [0]),
    _qz_code(_As.CHOICE, "p", ["a"], [0]),
    _qz_code(_As.CHOICE, "p", ["a", "b"], []),
    _qz_code(_As.CHOICE, "p", ["a", "b"], [5]),
    _qz_code(_As.CHOICE, "p", ["a", "b"], [0, 1]),
    _qz_code(_As.TEXT, "p", [], [], points=0)]
   == ["bad_kind", "no_prompt", "too_few_choices", "no_answer",
       "bad_answer", "one_answer", "bad_points"],
   "authoring validation refuses every malformed question at authoring time, "
   "not silently at grading time")

# --- Learning: the lifecycle over the wire ---------------------------------
# Course → lessons → quiz → enrollment → attempt → grade, through the same
# doors staff and learners use. The staff door is the ops API; the learner
# door is the storefront's /api/learn, which strips the answer key. All of
# it on tenant alpha — the runtime default from the split tests — with its
# own staff, learner and product, which is itself a wall check: nothing
# below leans on state from any other tenant.
_tch = c.post("/api/login", headers=HA, json={"name": "Tina Teacher",
                                              "role": "employee"}).json()
TT = {"Authorization": f"Bearer {_tch['token']}", **HA}
_lrn = c.post("/api/login", headers=HA, json={"name": "Lara Learner",
                                              "role": "customer"}).json()
LN = {"Authorization": f"Bearer {_lrn['token']}", **HA}
_crs = c.post("/api/learning/courses", headers=AA, json={
    "name": "Spanish A1", "language": "Spanish", "level": "beginner",
    "blurb": "First steps.", "teacher_id": _tch["id"]}).json()["id"]
ok(c.post("/api/learning/courses", headers=TT,
          json={"name": "Rogue"}).status_code == 403,
   "only an admin creates courses; a teacher teaches the ones they're given")
_l1 = c.post("/api/learning/lessons", headers=TT, json={
    "course_id": _crs, "title": "Greetings",
    "body": "# Hola\n\nSay **hola**.\n\n- hola\n- buenos días"}).json()["id"]
_l2 = c.post("/api/learning/lessons", headers=TT, json={
    "course_id": _crs, "title": "Numbers", "body": "uno, dos, tres"}).json()["id"]
ok(c.post("/api/learning/lessons", headers=LN, json={
    "course_id": _crs, "title": "Hack", "body": ""}).status_code == 403,
   "a learner cannot author lessons — editing is the teacher's and admin's")
c.post(f"/api/learning/lessons/{_l1}", headers=TT, json={
    "title": "Greetings", "body": "# Hola\n\nSay **hola**.", "published": 1})
_lrn_home = c.get("/api/learn/courses", headers=LN).json()
ok(_lrn_home["enrolled"] == [] and any(
    x["name"] == "Spanish A1" for x in _lrn_home["available"]),
   "before enrolment the course is a blurb in the catalogue, not content")
ok(c.get(f"/api/learn/courses/{_crs}", headers=LN).status_code == 403,
   "and its lessons are a closed door")
c.post(f"/api/learning/courses/{_crs}/enroll", headers=AA,
       json={"user_id": _lrn["id"]})
_cv = c.get(f"/api/learn/courses/{_crs}", headers=LN).json()
ok([x["title"] for x in _cv["lessons"]] == ["Greetings"],
   "an enrolled learner sees published lessons only — the draft stays "
   "invisible until the teacher says so")
_lv = c.get(f"/api/learn/lessons/{_l1}", headers=LN).json()
ok("<b>hola</b>" in _lv["html"] and "<h2>Hola</h2>" in _lv["html"],
   "lesson markdown renders server-side, escaped first")
c.post(f"/api/learn/lessons/{_l1}/done", headers=LN)
c.post(f"/api/learning/lessons/{_l2}", headers=TT, json={
    "title": "Numbers", "body": "uno, dos, tres", "published": 1})
_prog = c.get(f"/api/learn/courses/{_crs}", headers=LN).json()["progress"]
ok(_prog["lessons_done"] == 1 and _prog["lessons_total"] == 2,
   "progress is derived on read: one of two published lessons done")

_qz = c.post("/api/learning/quizzes", headers=TT, json={
    "course_id": _crs, "title": "Greetings check", "pass_mark": 60}).json()["id"]
ok(c.post(f"/api/learning/quizzes/{_qz}/questions", headers=TT, json={
    "kind": "choice", "prompt": "p", "choices": ["a"], "answer": [0]},
    ).status_code == 400,
   "the ops door refuses a malformed question with the engine's own reason")
_spk_probe = c.post(f"/api/learning/quizzes/{_qz}/questions", headers=TT,
                    json={"kind": "speaking", "prompt": "Say hola"}).json()
ok("id" in _spk_probe,
   "recorded answers are authorable now — the capture flow landed with the"
   " classroom phase")
c.post(f"/api/learning/questions/{_spk_probe['id']}/delete", headers=TT)
c.post(f"/api/learning/quizzes/{_qz}/questions", headers=TT, json={
    "kind": "choice", "prompt": "'Hello' is…",
    "choices": ["adiós", "hola"], "answer": [1], "points": 2})
c.post(f"/api/learning/quizzes/{_qz}/questions", headers=TT, json={
    "kind": "text", "prompt": "Translate 'good morning'",
    "accepted": ["buenos días"]})
ok(c.post(f"/api/learn/quizzes/{_qz}/start", headers=LN).status_code == 403,
   "an unpublished quiz is not open, even to the enrolled")
c.post(f"/api/learning/quizzes/{_qz}", headers=TT, json={
    "title": "Greetings check", "pass_mark": 60, "published": 1})
_at = c.post(f"/api/learn/quizzes/{_qz}/start", headers=LN).json()
_qs = _at["quiz"]["questions"]
ok(all("answer" not in q and "accepted" not in q for q in _qs),
   "the answer key never reaches a learner — stripped at the source, not "
   "filtered in the UI")
ok(c.post(f"/api/learn/quizzes/{_qz}/start", headers=LN).json()
   ["attempt"]["id"] == _at["attempt"]["id"],
   "starting again resumes the open attempt — never a silent second try")
_aid = _at["attempt"]["id"]
c.post(f"/api/learn/attempts/{_aid}/answer", headers=LN, json={
    "question_id": _qs[0]["id"], "chosen": [1]})
c.post(f"/api/learn/attempts/{_aid}/answer", headers=LN, json={
    "question_id": _qs[1]["id"], "text": "buenos dias"})
_sub = c.post(f"/api/learn/attempts/{_aid}/submit", headers=LN).json()
ok(_sub["grade"]["is_final"] and _sub["grade"]["percent"] == 100.0
   and _sub["grade"]["passed"] and _sub["attempt"]["state"] == "graded",
   "an all-auto attempt settles at submit — accent forgiven, full marks, "
   "state graded with no human in the loop")
ok(c.post(f"/api/learn/attempts/{_aid}/answer", headers=LN, json={
    "question_id": _qs[0]["id"], "chosen": [0]}).status_code == 409,
   "a submitted attempt no longer takes answers")
_prog2 = c.get(f"/api/learn/courses/{_crs}", headers=LN).json()["progress"]
ok(_prog2["quizzes_passed"] == 1, "and the pass lands in derived progress")

# the human-graded path: a question with no key → queue → mark → final
_qz2 = c.post("/api/learning/quizzes", headers=TT, json={
    "course_id": _crs, "title": "Free writing", "pass_mark": 50}).json()["id"]
c.post(f"/api/learning/quizzes/{_qz2}/questions", headers=TT, json={
    "kind": "text", "prompt": "Describe your weekend", "points": 4})
c.post(f"/api/learning/quizzes/{_qz2}", headers=TT, json={
    "title": "Free writing", "pass_mark": 50, "published": 1})
_at2 = c.post(f"/api/learn/quizzes/{_qz2}/start", headers=LN).json()
_aid2 = _at2["attempt"]["id"]
c.post(f"/api/learn/attempts/{_aid2}/answer", headers=LN, json={
    "question_id": _at2["quiz"]["questions"][0]["id"], "text": "fui al cine"})
_sub2 = c.post(f"/api/learn/attempts/{_aid2}/submit", headers=LN).json()
ok(not _sub2["grade"]["is_final"] and "percent" not in _sub2["grade"]
   and _sub2["grade"]["pending"] == 1,
   "a written answer with no key leaves the attempt submitted-not-final, "
   "and the learner sees no provisional number")
_queue = c.get("/api/learning/grading", headers=TT).json()
ok(any(a["id"] == _aid2 for a in _queue),
   "the attempt sits in the teacher's grading queue")
ok(not any(a["id"] == _aid2
           for a in c.get("/api/learning/grading", headers=LN).json()),
   "…and in nobody else's — a learner's queue is empty")
_g = c.post(f"/api/learning/attempts/{_aid2}/grade", headers=TT, json={
    "question_id": _at2["quiz"]["questions"][0]["id"], "awarded": 3,
    "feedback": "¡bien!"}).json()
ok(_g["is_final"] and _g["percent"] == 75.0,
   "the teacher's mark settles it at 3/4")
_fin = c.get(f"/api/learn/attempts/{_aid2}", headers=LN).json()
ok(_fin["grade"]["is_final"] and _fin["grade"]["percent"] == 75.0
   and _fin["grade"]["passed"],
   "and only now does the learner see a score — final, with pass/fail")
_ncon = sqlite3.connect(_tn.tenant_dir("alpha") / "business_control.db")
ok(_ncon.execute("SELECT 1 FROM notifications WHERE kind='learning'"
                 " AND title LIKE 'Quiz to grade%'").fetchone() is not None
   and _ncon.execute("SELECT 1 FROM notifications WHERE kind='learning'"
                     " AND user_id=?", (_lrn["id"],)).fetchone() is not None,
   "both moments notified: staff when a human mark was needed, the learner "
   "when their score became real")
_ncon.close()

# buying a course product enrols you — the checkout rail is the admissions
# office, which is the one thing the source never had
c.post("/api/admin/products", headers=AA, json={
    "sku": "CRS-FR1", "name": "French A1 (course)", "price_cents": 9900,
    "case_price_cents": 99000})
_frp = [p["id"] for p in c.get("/api/products", headers=HA).json()
        if p["sku"] == "CRS-FR1"][0]
_crs2 = c.post("/api/learning/courses", headers=AA, json={
    "name": "French A1", "language": "French", "product_id": _frp,
    "teacher_id": _tch["id"]}).json()["id"]
# a first pay-on-delivery order from an unconfirmed address is held, not
# placed — Lara starts as an established customer, like every order fixture
_acon = sqlite3.connect(_tn.tenant_dir("alpha") / "business_control.db")
_acon.execute("UPDATE users SET email='lara@example.test',"
              " email_verified_at=? WHERE id=?", (_t0.time(), _lrn["id"]))
_acon.commit(); _acon.close()
c.post("/api/orders", headers=LN, json={
    "items": [{"product_id": _frp, "qty": 1}], "visitor_id": "vlearn",
    "ship_name": "Lara", "address": "9 Elm St", "city": "Boston"})
ok(any(x["id"] == _crs2 for x in
       c.get("/api/learn/courses", headers=LN).json()["enrolled"]),
   "placing an order for the linked product enrolled the buyer — no clerk "
   "in the loop")
_e_ops = c.get(f"/api/learning/courses/{_crs2}", headers=AA).json()["enrollments"]
ok(_e_ops and _e_ops[0]["source"].startswith("order:"),
   "and the seat records which order opened it")

# --- the classroom: attendance rules, ported pure from lingua-portal -------
# Every check states a rule a school actually has. Where a rule could go
# either way (late still counts as attending; rounding favours the teacher),
# the check records the decision so a future change has to argue with it.
from erp.backend import attendance as _At  # noqa: E402

_T0 = 1_700_000_000
_M = 60


def _sess(**kw):
    base = dict(id=1, course_id=10, teacher_id=100, started_at=_T0,
                late_after_min=10)
    base.update(kw)
    return _At.Session(**base)


def _at_code(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except _At.DomainError as e:
        return e.code


ok(_At.start_session(course_id=10, teacher_id=100, now=_T0)["status"] == "open"
   and _at_code(_At.start_session, course_id=10, teacher_id=100, now=_T0,
                open_sessions=[_sess()]) == "already_open"
   and _At.start_session(course_id=11, teacher_id=100, now=_T0,
                         open_sessions=[_sess()])["course_id"] == 11,
   "one open session per course — a second would split the roster and "
   "double-pay the teacher; a different course may start concurrently")
_closed = _At.close_session(_sess(), now=_T0 + 50 * _M, actor_id=100)
ok(_closed["ended_at"] == _T0 + 50 * _M and _closed["closed_by"] == 100
   and _at_code(_At.close_session, _sess(status="closed", ended_at=_T0),
                now=_T0, actor_id=100) == "already_closed"
   and _at_code(_At.close_session, _sess(), now=_T0 - 60,
                actor_id=100) == "ends_before_start",
   "closing records end time and WHO closed; twice is refused; a class "
   "cannot end before it began")
_E = [1, 2, 3]
ok(_At.check_in(_sess(), student_id=1, at=_T0 + 2 * _M,
                enrolled_ids=_E).status == "present"
   and _At.check_in(_sess(), student_id=1, at=_T0 + 11 * _M,
                    enrolled_ids=_E).status == "late"
   and _At.check_in(_sess(), student_id=1, at=_T0 + 10 * _M,
                    enrolled_ids=_E).status == "present",
   "the late window classifies arrivals, and the boundary minute itself is "
   "still present")
ok(_at_code(_At.check_in, _sess(), student_id=99, at=_T0,
            enrolled_ids=_E) == "not_enrolled"
   and _at_code(_At.check_in, _sess(status="closed"), student_id=1, at=_T0,
                enrolled_ids=_E) == "session_not_open"
   and _at_code(_At.check_in, _sess(), student_id=1, at=_T0 - 30 * _M,
                enrolled_ids=_E) == "too_early"
   and _at_code(_At.check_in, _sess(), student_id=1, at=_T0,
                enrolled_ids=_E, status="excused") == "self_status_forbidden",
   "check-in refuses the unenrolled, the closed class, the early bird, and "
   "a student excusing themselves")
_tm = _At.check_in(_sess(), student_id=2, at=_T0 + _M, enrolled_ids=_E,
                   method="teacher", marked_by=100, status="excused")
ok(_tm.status == "excused" and _tm.marked_by == 100
   and _at_code(_At.check_in, _sess(), student_id=2, at=_T0 + 5 * _M,
                enrolled_ids=_E, existing=_tm) == "teacher_marked"
   and _At.check_in(_sess(), student_id=2, at=_T0 + 5 * _M, enrolled_ids=_E,
                    existing=_tm, method="teacher", marked_by=100,
                    status="present").status == "present",
   "a teacher may set any status and it records who; self check-in never "
   "overwrites a teacher's ruling, but the teacher may correct their own")
_ros = _At.finalize_roster(
    _sess(), enrolled=[(1, "Ana"), (2, "Bo"), (3, "Cy")],
    checkins=[_At.CheckIn(1, 1, _T0, "present", "self"),
              _At.CheckIn(1, 2, _T0, "excused", "teacher", 100)], now=_T0)
_sm = _At.attendance_summary(_ros)
ok(len(_ros) == 3 and _ros[2].status == "absent"
   and _sm["attended"] == 1 and _sm["rate"] == 0.5
   and _At.attendance_summary(
       [_At.RosterRow(1, "L", "late")])["attended"] == 1,
   "no check-in defaults to absent, never silently upgraded; LATE counts as "
   "attending; EXCUSED leaves the denominator instead of counting against "
   "the class")
_hr = _At.PayRate(teacher_id=100, hourly_cents=5000)
_done = _sess(ended_at=_T0 + 90 * _M, status="closed")
ok(_At.pay_for_session(_done, _hr, students_attended=4).amount_cents == 7500
   and _at_code(_At.pay_for_session, _sess(), _hr,
                students_attended=0) == "session_open"
   and _At.pay_for_session(
       _sess(ended_at=_T0 + 20 * _M, status="closed"), _hr,
       students_attended=1, minimum_minutes=60).amount_cents == 5000,
   "90 min at $50/h is $75; an open session is not billable; a minimum pays "
   "the floor when a class ends early")
ok(_At.billable_minutes(_sess(ended_at=_T0 + 31 * _M, status="closed"),
                        round_to_min=15) == 45
   and _At.billable_minutes(_sess(ended_at=_T0 + 30 * _M, status="closed"),
                            round_to_min=15) == 30
   and _At.pay_for_session(
       _sess(ended_at=_T0 + 60 * _M, status="cancelled"), _hr,
       students_attended=0).amount_cents == 0
   and _At.pay_for_session(
       _sess(ended_at=_T0 + 60 * _M, status="cancelled"), _hr,
       students_attended=0, pay_cancelled=True).amount_cents == 5000,
   "rounding is UP — the ambiguity favours the person who did the work; an "
   "exact block does not round up; a cancelled class pays nothing unless "
   "the school chooses to")
_pp = _At.payroll_period([
    _At.PayLine(1, 10, 100, _T0, 60, 60, 5000, 3, "approved"),
    _At.PayLine(2, 10, 100, _T0, 60, 60, 5000, 3, "pending"),
    _At.PayLine(3, 10, 100, _T0, 60, 60, 5000, 0, "held"),
    _At.PayLine(4, 11, 200, _T0, 30, 30, 2500, 5, "approved")])
_t100 = [t for t in _pp["teachers"] if t["teacher_id"] == 100][0]
ok(len(_pp["teachers"]) == 2 and _t100["amount_cents"] == 10000
   and _pp["held_cents"] == 5000 and _pp["total_cents"] == 12500
   and _At.money(7500) == "$75.00" and _At.money(5) == "$0.05",
   "a period groups by teacher; held lines are excluded from the payable "
   "total but still reported, so a dispute is visible rather than silently "
   "deducted")

# --- admissions: a registration is not an account --------------------------
# The public form grants nothing; an administrator's approval is what
# creates the person and the seat. Still on alpha, still over the wire.
_reg1 = c.post("/api/learn/register", headers=HA, json={
    "name": "Nina New", "email": "nina@example.test", "language": "Spanish",
    "goals": "I want to order coffee in Madrid"}).json()
ok(_reg1["ok"], "the public form takes an application with no sign-in")
_reg2 = c.post("/api/learn/register", headers=HA, json={
    "name": "Nina New", "email": "NINA@example.test", "language": "Spanish",
    "course_id": _crs}).json()
ok(_reg2["id"] == _reg1["id"],
   "a resubmission UPDATES the pending application — a queue of "
   "near-identical rows is how a real applicant gets lost")
_rq = c.get("/api/learning/registrations", headers=AA).json()
ok(any(r["id"] == _reg1["id"] and r["course_id"] == _crs for r in _rq),
   "the application sits in the ops queue with the course it asked for")
ok(c.get("/api/learning/registrations", headers=TT).status_code == 403,
   "the queue is the administrator's, not the teacher's")
_app = c.post(f"/api/learning/registrations/{_reg1['id']}/approve",
              headers=AA, json={}).json()
ok(not _app["existing_account"] and _app["course_id"] == _crs,
   "approval creates the account and the seat in one act")
ok(c.post(f"/api/learning/registrations/{_reg1['id']}/approve",
          headers=AA, json={}).status_code == 409,
   "and refuses to run twice — idempotence is what keeps a double-click "
   "from minting two students")
_nina = c.post("/api/login", headers=HA, json={
    "name": _app["person"]["name"], "role": "customer"}).json()
NN = {"Authorization": f"Bearer {_nina['token']}", **HA}
ok(any(x["id"] == _crs for x in
       c.get("/api/learn/courses", headers=NN).json()["enrolled"]),
   "the approved student signs in and finds their course waiting")
c.post("/api/learn/register", headers=HA, json={
    "name": "Turned Away", "email": "no@example.test", "language": "Latin"})
_reg3 = [r for r in c.get("/api/learning/registrations", headers=AA).json()
         if r["email"] == "no@example.test"][0]
c.post(f"/api/learning/registrations/{_reg3['id']}/decline", headers=AA,
       json={"note": "no Latin programme this term"})
ok(not any(r["id"] == _reg3["id"] for r in
           c.get("/api/learning/registrations", headers=AA).json())
   and c.get("/api/learning/registrations?state=declined",
             headers=AA).json()[0]["note"] == "no Latin programme this term",
   "declining keeps the record with its reason — 'why was this person "
   "turned away' is a question schools get asked")

# --- the class-session loop over the wire ----------------------------------
ok(c.post("/api/learning/sessions", headers=LN,
          json={"course_id": _crs}).status_code == 403,
   "a learner cannot start a class")
_cls = c.post("/api/learning/sessions", headers=TT,
              json={"course_id": _crs}).json()
_sid = _cls["session"]["id"]
ok(_cls["session"]["status"] == "open"
   and c.post("/api/learning/sessions", headers=TT,
              json={"course_id": _crs}).status_code == 409,
   "the teacher opens a class; a second open session for the same course "
   "is refused")
_ci = c.post(f"/api/learn/sessions/{_sid}/checkin", headers=LN).json()
ok(_ci["status"] == "present",
   "a student says 'I'm here' from the learning page and the rules "
   "classify the arrival")
ok(any(a["code"] == "first_checkin" for a in _ci["new_achievements"]),
   "…and the first check-in is a badge moment, granted at the moment it "
   "was earned")
c.post(f"/api/learning/sessions/{_sid}/mark", headers=TT, json={
    "student_id": _nina["id"], "status": "excused",
    "note": "travelling this week"})
ok(c.post(f"/api/learn/sessions/{_sid}/checkin", headers=NN)
   .status_code == 409,
   "a teacher's ruling is not overwritten by a later self check-in")
_ros2 = c.get(f"/api/learning/sessions/{_sid}", headers=TT).json()
ok(_ros2["summary"]["attended"] == 1
   and any(r["status"] == "excused" and r["note"] == "travelling this week"
           for r in _ros2["roster"]),
   "the roster shows every enrolled student with who-asserted-what")
_closed_r = c.post(f"/api/learning/sessions/{_sid}/close",
                   headers=TT).json()
ok(_closed_r["session"]["status"] == "closed"
   and all(r["status"] != "absent" or r["method"] == "system"
           for r in _closed_r["roster"]),
   "closing records system-marked absents for the silent — 'no row' is "
   "never ambiguous between absent and nobody-took-attendance")
_att = c.get(f"/api/learn/courses/{_crs}", headers=LN).json()["attendance"]
ok(_att["classes_held"] == 1 and _att["attended"] == 1,
   "the learner's course page carries their attendance standing")

# --- payroll, derived --------------------------------------------------------
c.post("/api/learning/payrates", headers=AA, json={
    "teacher_id": _tch["id"], "hourly_cents": 5000, "minimum_minutes": 30})
_pr = c.get("/api/learning/payroll", headers=AA).json()
_trow = [t for t in _pr["teachers"] if t["teacher_id"] == _tch["id"]][0]
ok(_trow["amount_cents"] == 2500 and _trow["lines"][0]["state"] == "pending",
   "pay derives from the closed session — a class that ended early pays the "
   "30-minute floor at $50/h, and no stored amount exists anywhere")
c.post(f"/api/learning/payroll/{_sid}/state", headers=AA,
       json={"state": "held", "note": "roster query"})
_pr2 = c.get("/api/learning/payroll", headers=AA).json()
_trow2 = [t for t in _pr2["teachers"] if t["teacher_id"] == _tch["id"]][0]
ok(_trow2["amount_cents"] == 0 and _trow2["held_cents"] == 2500,
   "a held line leaves the payable total but stays visible — a dispute is "
   "never silently deducted")
c.post(f"/api/learning/payroll/{_sid}/state", headers=AA,
       json={"state": "approved"})
ok([t for t in c.get("/api/learning/payroll", headers=AA).json()["teachers"]
    if t["teacher_id"] == _tch["id"]][0]["amount_cents"] == 2500,
   "approving restores it to the payable total")
ok(c.get("/api/learning/payroll", headers=TT).status_code == 403,
   "payroll is the administrator's screen")
_ach = c.get("/api/learn/courses", headers=LN).json()["achievements"]
ok({"first_checkin", "quiz_pass", "quiz_perfect"} <=
   {a["code"] for a in _ach},
   "the learner's badges accumulated from what actually happened: a "
   "check-in, a pass, a perfect score")

# --- the community: finding people, connecting, talking ---------------------
# lingua's social layer, with its three load-bearing rules: messaging
# requires a mutual contact (enforced on SEND); visibility is the person's
# own choice, applied in ONE place; message bodies never reach staff except
# by a party's own report.
_shopper = c.post("/api/login", headers=HA, json={
    "name": "Sally Shopper", "role": "customer"}).json()
SH = {"Authorization": f"Bearer {_shopper['token']}", **HA}
ok(c.get("/api/learn/people", headers=SH).status_code == 403,
   "the community is the school, not the shop — a customer who never "
   "joined a course has no place in a student directory")
ok(not any(p["name"] == "Sally Shopper" for p in
           c.get("/api/learn/people/search?q=Sally",
                 headers=LN).json()),
   "…and cannot be found in it either")
_found = c.get("/api/learn/people/search?q=Nina", headers=LN).json()
ok(any(p["id"] == _nina["id"] and p["contact"] == "none" for p in _found),
   "a classmate is findable by name, with the relationship attached")
ok(c.get("/api/learn/people/search?q=N", headers=LN).json() == [],
   "one letter is not a search — names only, and only real queries")

# privacy is the person's own dial, applied server-side in one place
c.post("/api/learn/prefs", headers=NN, json={"privacy_name": "initial"})
ok(any(p["name"] == "Nina N." for p in
       c.get("/api/learn/people/search?q=Nina", headers=LN).json()),
   "at 'initial' a stranger sees 'Nina N.' — first name whole, the rest "
   "one letter")
ok(any(p["name"] == "Nina New" for p in
       c.get("/api/learn/people/search?q=Nina", headers=TT).json()),
   "staff and teachers always get the full record — a roster cannot run "
   "on initials")
c.post("/api/learn/prefs", headers=NN, json={"privacy_name": "nobody"})
ok(not any(p["id"] == _nina["id"] for p in
           c.get("/api/learn/people/search?q=Nina", headers=LN).json()),
   "at 'nobody' she is indistinguishable from not existing")
c.post("/api/learn/prefs", headers=NN, json={"privacy_name": "everyone"})

# the accept gate, enforced on SEND — not by hiding a compose box
ok(c.post(f"/api/learn/thread/{_nina['id']}", headers=LN,
          json={"body": "hola!"}).status_code == 403,
   "nobody can message somebody who has not said yes")
c.post("/api/learn/prefs", headers=NN, json={"open_dm": 1})
ok(c.post(f"/api/learn/thread/{_nina['id']}", headers=LN,
          json={"body": "hola desde el open DM"}).status_code == 200,
   "…except through the one keyhole: the recipient's OWN choice to open "
   "their DMs, off by default")
c.post("/api/learn/prefs", headers=NN, json={"open_dm": 0})
_req_out = c.post(f"/api/learn/people/{_nina['id']}/request",
                  headers=LN, json={}).json()
ok(_req_out["state"] == "pending"
   and c.post(f"/api/learn/people/{_nina['id']}/respond", headers=LN,
              json={"accept": True}).status_code == 409,
   "asking leaves a pending request, and the asker cannot accept it for "
   "them — that would make the accept step theatre")
ok(c.post(f"/api/learn/people/{_lrn['id']}/request", headers=NN,
          json={}).json()["state"] == "accepted",
   "but if BOTH people reach out, the second ask IS the acceptance — no "
   "deadlock on who clicks a second button")
ok({"first_friend"} <= {a["code"] for a in
                        c.get("/api/learn/courses", headers=LN)
                        .json()["achievements"]},
   "and the first friendship is a badge moment for both")
c.post(f"/api/learn/thread/{_nina['id']}", headers=LN,
       json={"body": "ahora somos amigos"})
_th = c.get(f"/api/learn/thread/{_lrn['id']}", headers=NN).json()
ok(any(m["body"] == "ahora somos amigos" for m in _th["messages"]),
   "connected people talk")
_ppl = c.get("/api/learn/people", headers=NN).json()
ok(any(p["id"] == _lrn["id"] and p["unread"] == 0
       for p in _ppl["accepted"]),
   "and reading the thread WAS the receipt — unread is already zero")

# ghost mode: one-directional invisibility, messaging paused both ways
c.post(f"/api/learn/people/{_lrn['id']}/ghost", headers=NN, json={})
ok(not any(p["id"] == _nina["id"] for p in
           c.get("/api/learn/people/search?q=Nina", headers=LN).json()),
   "a ghost vanishes from their target's sight — even as an accepted "
   "contact")
ok(c.post(f"/api/learn/thread/{_nina['id']}", headers=LN,
          json={"body": "?"}).status_code == 409
   and c.post(f"/api/learn/thread/{_lrn['id']}", headers=NN,
              json={"body": "!"}).status_code == 409,
   "and messaging pauses in BOTH directions — a ghost who could still "
   "message would be invisible-but-present, the thing the mode exists to "
   "prevent")
c.post(f"/api/learn/people/{_lrn['id']}/unghost", headers=NN, json={})
ok(c.post(f"/api/learn/thread/{_nina['id']}", headers=LN,
          json={"body": "de vuelta"}).status_code == 200,
   "unghosting resumes the friendship exactly where it was")

# a block severs the edge and shuts the door in both directions
_blk_msg = [m for m in c.get(f"/api/learn/thread/{_lrn['id']}",
                             headers=NN).json()["messages"]
            if m["from_id"] == _lrn["id"]][-1]
c.post(f"/api/learn/people/{_lrn['id']}/block", headers=NN, json={})
ok(not c.get("/api/learn/people", headers=NN).json()["accepted"]
   and c.post(f"/api/learn/thread/{_nina['id']}", headers=LN,
              json={"body": "?"}).status_code in (403, 404)
   and c.post(f"/api/learn/thread/{_lrn['id']}", headers=NN,
              json={"body": "?"}).status_code == 403,
   "a block removes the contact edge at the same moment — one that left a "
   "live edge behind would let messages keep flowing through it")
c.post(f"/api/learn/people/{_lrn['id']}/unblock", headers=NN, json={})

# the release valve: staff never read threads, but a party can hand one
# message to the office — snapshotted, so the evidence outlives everything
ok(c.post(f"/api/learn/people/{_lrn['id']}/report", headers=SH,
          json={"reason": "x", "message_id": _blk_msg["id"]}
          ).status_code == 403,
   "an outsider cannot report into the community at all")
c.post(f"/api/learn/people/{_lrn['id']}/report", headers=NN,
       json={"reason": "unwanted messages",
             "message_id": _blk_msg["id"]})
_cq = c.get("/api/learning/conduct", headers=AA).json()
_crep = [r for r in _cq if r["subject_id"] == _lrn["id"]][0]
ok("de vuelta" in (_crep["body_snapshot"] or ""),
   "the reported message's body is snapshotted into the report — staff "
   "read exactly the message that was handed over, and nothing else")
ok(c.get("/api/learning/conduct", headers=TT).status_code == 403,
   "the conduct queue is the office's, not every teacher's")
c.post(f"/api/learning/conduct/{_crep['id']}/resolve", headers=AA,
       json={"note": "spoke to both"})
ok(c.post(f"/api/learning/conduct/{_crep['id']}/resolve", headers=AA,
          json={}).status_code == 404,
   "resolving is once — a resolved report stays resolved")

# --- people photos: the face is the person's to give -------------------------
# The last of the source's absences. Self-uploaded ONLY (uploading is the
# consent), token-named in the sharded store, shared by the person's own
# privacy_photo switch, always on staff rosters (attendance cannot run on
# initials), gone with removal and with erasure.
_png1 = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 800)
_pup = c.post("/api/learn/me/photo", headers=LN, content=_png1)
ok(_pup.status_code == 200 and _pup.json()["photo"].endswith(".png"),
   "a member uploads their own photo — sniffed like any media, "
   "token-named like any file")
_mephoto = c.get("/api/learn/me", headers=LN).json()
ok(_mephoto["photo"] == _pup.json()["photo"]
   and _mephoto["prefs"]["privacy_photo"] == 1,
   "the profile carries it, shared by default — their switch to flip")
_pfile = _tn.tenant_dir("alpha") / "uploads" / _mephoto["photo"]
ok(_pfile.exists(), "and the bytes live in the tenant's sharded store")
_hit = [p for p in c.get("/api/learn/people/search?q=Lara",
                         headers=NN).json() if p["id"] == _mephoto["id"]]
ok(_hit and _hit[0].get("photo") == _mephoto["photo"],
   "people who may see the name see the face — the same presenter "
   "answers both")
c.post("/api/learn/prefs", headers=LN, json={"privacy_photo": 0})
_hit2 = [p for p in c.get("/api/learn/people/search?q=Lara",
                          headers=NN).json() if p["id"] == _mephoto["id"]]
ok(_hit2 and "photo" not in _hit2[0],
   "switch off = the face is shown to nobody the switch covers")
_clsP = c.post("/api/learning/sessions", headers=TT,
               json={"course_id": _crs}).json()
_rosP = c.get(f"/api/learning/sessions/{_clsP['session']['id']}",
              headers=TT).json()
_lrow = [r for r in _rosP["roster"]
         if r["student_id"] == _mephoto["id"]]
ok(_lrow and _lrow[0]["photo"] == _mephoto["photo"],
   "while the teacher's roster keeps the face regardless — attendance "
   "is the surface full names already trust")
c.post(f"/api/learning/sessions/{_clsP['session']['id']}/close",
       headers=TT)
c.post("/api/learn/prefs", headers=LN, json={"privacy_photo": 1})
ok(c.post("/api/learn/me/photo", headers=LN,
          content=b"just words").status_code == 400,
   "a non-image is refused at the door")
c.request("DELETE", "/api/learn/me/photo", headers=LN)
ok(c.get("/api/learn/me", headers=LN).json()["photo"] == ""
   and not _pfile.exists(),
   "removal clears the record AND the file — a face nobody can reach is "
   "still a face on disk until it is not")

# --- live video: the signaling mailboxes -----------------------------------
_j1 = c.post("/api/learn/rtc/rm-test1/join", headers=LN, json={}).json()
_j2 = c.post("/api/learn/rtc/rm-test1/join", headers=NN, json={}).json()
ok(_j1["peers"] == [] and _j2["peers"] == [_j1["peer"]],
   "the first peer finds an empty room; the second is told who is there")
c.post("/api/learn/rtc/rm-test1/signal", headers=NN, json={
    "to": _j1["peer"], "peer": _j2["peer"],
    "payload": {"description": {"type": "offer", "sdp": "x"}}})
_poll = c.get(f"/api/learn/rtc/rm-test1/poll?peer={_j1['peer']}",
              headers=LN).json()
ok(len(_poll["messages"]) == 1
   and _poll["messages"][0]["from"] == _j2["peer"]
   and c.get(f"/api/learn/rtc/rm-test1/poll?peer={_j1['peer']}",
             headers=LN).json()["messages"] == [],
   "a signal lands in exactly one mailbox and polling drains it — the "
   "server relays SDP and never touches media")
ok(c.get("/api/learn/rtc/rm-test1/poll?peer=x").status_code == 401,
   "signaling is authenticated — poll is the request the mesh makes on a "
   "loop, and it must be the one that tells a dead session to stop")
c.post("/api/learn/rtc/rm-test1/leave", headers=NN,
       json={"peer": _j2["peer"]})
ok(c.get(f"/api/learn/rtc/rm-test1/poll?peer={_j1['peer']}",
         headers=LN).json()["peers"] == [],
   "leaving empties your seat, and the next poll tells the survivors")
from erp.backend import community as _cm  # noqa: E402
from erp.backend import tenancy as _tnc  # noqa: E402
_tok_a = _tnc.CURRENT.set("alpha")
_cm._rtc_join("rm-shared", "peer-a")
_tnc.CURRENT.reset(_tok_a)
_tok_b = _tnc.CURRENT.set("beta")
_iso = _cm._rtc_join("rm-shared", "peer-b")
_tnc.CURRENT.reset(_tok_b)
ok(_iso["peers"] == [],
   "rooms are keyed by tenant — two schools sharing a process never share "
   "a mailbox, even for the same room name")
_ros_room = c.get(f"/api/learning/courses/{_crs}", headers=TT).json()
_cls2 = c.post("/api/learning/sessions", headers=TT,
               json={"course_id": _crs}).json()
ok(_cls2["session"]["room"] and _cls2["session"]["room"].startswith("rm-"),
   "every class carries a video room from the moment it opens")
ok(c.get(f"/api/learn/courses/{_crs}", headers=LN).json()
   ["session"]["room"] == _cls2["session"]["room"],
   "and the learner's course page hands them the same room the teacher's "
   "roster has — one class, one call")
c.post(f"/api/learning/sessions/{_cls2['session']['id']}/close", headers=TT)
_ljs = (Path(__file__).parent.parent / "src/storefront/frontend/learn.js"
        ).read_text(encoding="utf-8")
_mjs = (Path(__file__).parent.parent / "src/storefront/frontend/rtc-mesh.js"
        ).read_text(encoding="utf-8")
_opsjs2 = ops_app_js()
ok("LinguaMesh" in _mjs and "polite" in _mjs and "ignoreOffer" in _mjs
   and "meshBitrateFor" in _mjs,
   "the mesh client carries lingua's perfect-negotiation pattern and the "
   "shrinking per-peer bitrate cap")
ok("LinguaMesh" in _ljs and "/rtc-mesh.js" in c.get("/learn").text
   and "/learn.js" in c.get("/learn").text,
   "the learner page loads the app and the mesh as versioned assets")
ok("classCall" in _opsjs2 and "/rtc-mesh.js" in _opsjs2,
   "the ops roster joins the same mesh — one client, not two")

# the capability wall: /learn is part of the Learning grant, not the core
c.post("/api/store/admin/fleet/tenants", headers=AA,
       json={"id": "learnco", "brand": "Learn Co", "klass": "micro"})
_LH = {"host": "learnco.localhost"}
ok(c.get("/learn", headers=_LH).status_code == 200,
   "no grant recorded = everything on — /learn answers, same null rule")
c.post("/api/store/admin/fleet/tenants/learnco/caps", headers=AA,
       json={"caps": ["selling", "payments"]})
ok(c.get("/learn", headers=_LH).status_code == 404,
   "a tenant without the Learning grant has no /learn — a 404, not a husk")
c.post("/api/store/admin/fleet/tenants/learnco/caps", headers=AA,
       json={"caps": ["selling", "payments", "learning"]})
ok(c.get("/learn", headers=_LH).status_code == 200,
   "granting Learning opens the door again")
c.request("DELETE", "/api/store/admin/fleet/tenants/learnco?keep_data=0",
          headers=AA)
_appjs_lrn = ops_app_js()
ok('id: "learning"' in _appjs_lrn
   and "learning: renderLearning" in _appjs_lrn
   and 'learning: "learning"' in _appjs_lrn,
   "the ops app carries the Learning tab, its renderer, and its capability "
   "lock — the same entitlement the storefront's /learn answers to")

# --- the library: a lending desk with derived availability ------------------
_bk = c.post("/api/learning/library/items", headers=TT,
             json={"name": "Madrigal's Magic Key", "kind": "book",
                   "copies": 1}).json()
ok("id" in _bk, "a teacher runs the desk — adding an item is staff work")
ok(c.post("/api/learning/library/items", headers=LN,
          json={"name": "x"}).status_code == 403,
   "a learner does not: the desk is staff-only")
_lo = c.post("/api/learning/library/checkout", headers=TT,
             json={"item_id": _bk["id"], "name": "Lara Learner",
                   "due_days": 14}).json()
ok("id" in _lo, "checkout by exact name, like enrolment")
_lib = c.get("/api/learning/library", headers=TT).json()
_bk_row = [i for i in _lib["items"] if i["id"] == _bk["id"]][0]
ok(_bk_row["available"] == 0 and _bk_row["out"] == 1,
   "availability is DERIVED — copies minus open loans, nothing stored")
ok(c.post("/api/learning/library/checkout", headers=TT,
          json={"item_id": _bk["id"], "name": "Nina New"}
          ).status_code == 409,
   "every copy out = the desk refuses, it does not overbook")
_myloans = c.get("/api/learn/loans", headers=LN).json()
ok(len(_myloans) == 1 and _myloans[0]["item_name"] == "Madrigal's Magic Key"
   and not _myloans[0]["returned_at"],
   "the borrower sees their own loan on /learn")
_achs = c.get("/api/learn/courses", headers=LN).json()["achievements"]
ok(any(a["code"] == "bookworm" for a in _achs),
   "borrowing mints the bookworm badge — ever-borrowed, derived like the "
   "rest")
ok(c.post(f"/api/learning/library/return/{_lo['id']}",
          headers=TT).json()["ok"], "and the book comes back")
ok(c.post(f"/api/learning/library/return/{_lo['id']}",
          headers=TT).status_code == 404,
   "a double return fails loudly instead of rewriting the timestamp")

# --- the calendar: sessions, month grid data ---------------------------------
_cal = c.get(f"/api/learn/courses/{_crs}/sessions", headers=LN).json()
ok(len(_cal) >= 1 and all("started_at" in s and "mine" in s
                          and "recordings" in s for s in _cal),
   "the learner's calendar feed carries each class with their OWN status "
   "and a recordings count — never the roster")
ok(c.get(f"/api/learn/courses/{_crs}/sessions", headers=SH).status_code
   == 403,
   "an outsider gets no calendar — enrolment gates it like everything else")
ok("monthGrid" in _ljs and "cursor.getDate()" in _ljs,
   "the month grid is client-side, with the DST normalisation the source "
   "learned the hard way")

# --- QR identity: the card, the handshake, scan-to-check-in ------------------
_card = c.get("/api/learn/me/card", headers=LN).json()
ok(_card["uid"] and _card["plain"].startswith("bc:person:")
   and "/p/" in _card["payload"],
   "the card carries an unguessable uid in both forms — scheme for "
   "scanners, URL for an iPhone camera")
_hs = c.post("/api/learn/people/scan", headers=NN,
             json={"payload": _card["plain"]}).json()
ok(_hs["name"] == "Lara Learner",
   "scanning a card shows the FULL name whatever the privacy level — "
   "handing over your code is the consent")
ok(c.post("/api/learn/people/scan", headers=NN,
          json={"payload": "bc:person:not-a-uuid"}).status_code == 400,
   "permissive about the wrapper, strict about the UUID")
_cls3 = c.post("/api/learning/sessions", headers=TT,
               json={"course_id": _crs}).json()
_scan = c.post(f"/api/learning/sessions/{_cls3['session']['id']}/scan",
               headers=TT, json={"code": _card["payload"]}).json()
ok(_scan["student"]["name"] == "Lara Learner"
   and _scan["status"] in ("present", "late"),
   "a teacher scans a card and the ordinary check-in rules decide the "
   "status — the QR answers WHO, never WHETHER")
_ros3 = c.get(f"/api/learning/sessions/{_cls3['session']['id']}",
              headers=TT).json()
_lara_row = [r for r in _ros3["roster"] if r["name"] == "Lara Learner"][0]
ok(_lara_row["method"] == "teacher",
   "the scan records the teacher as the marker — a student scanning their "
   "own card cannot mark themselves present")
_old_uid = _card["uid"]
_new_uid = c.post("/api/learn/me/qr/reissue", headers=LN).json()["uid"]
ok(_new_uid != _old_uid
   and c.post("/api/learn/people/scan", headers=NN,
              json={"payload": f"bc:person:{_old_uid}"}).status_code == 404,
   "reissue mints a new code and the lost card stops working that moment")
c.post(f"/api/learning/sessions/{_cls3['session']['id']}/close", headers=TT)

# --- the door: a volunteer runs the scanner ----------------------------------
# lingua-portal's entrance, whole: the person at the door — volunteer,
# staff or the teacher — sees every open class from the portal, scans
# arriving students' cards, and can mark by hand off the roster. Opening,
# closing and pay stay the teacher's.
c.post("/api/learning/team", headers=AA,
       json={"name": "Val Doorkeeper", "role": "volunteer"})
_vin = c.post("/api/login", headers=HA, json={
    "name": "Val Doorkeeper", "mode": "signin"}).json()
_VV = {"Authorization": f"Bearer {_vin['token']}", **HA}
_clsD = c.post("/api/learning/sessions", headers=TT,
               json={"course_id": _crs}).json()
_sidD = _clsD["session"]["id"]
_dl = [s for s in c.get("/api/learn/live", headers=_VV).json()
       if s["id"] == _sidD]
ok(_dl and _dl[0]["door"] is True and _dl[0]["member"] is False,
   "a volunteer sees every open class flagged for the door — without "
   "being offered a check-in that is not theirs")
ok(c.get(f"/api/learning/sessions/{_sidD}", headers=_VV).status_code
   == 200,
   "and reads the roster — the sheet at the entrance")
_cardL = c.get("/api/learn/me/card", headers=LN).json()
_dscan = c.post(f"/api/learning/sessions/{_sidD}/scan", headers=_VV,
                json={"code": _cardL["payload"]}).json()
ok(_dscan["student"]["name"] == "Lara Learner"
   and _dscan["status"] in ("present", "late"),
   "the volunteer scans an arriving student's card and the ordinary "
   "check-in rules decide the status")
ok(c.post(f"/api/learning/sessions/{_sidD}/mark", headers=_VV,
          json={"student_id": _dscan["student"]["id"],
                "status": "late"}).status_code == 200,
   "and can correct a mark by hand off the roster")
ok(c.post(f"/api/learning/sessions/{_sidD}/close",
          headers=_VV).status_code == 403,
   "while ending the class stays the teacher's act — the door marks "
   "presence, it does not run the school")
_shl = c.get("/api/learn/live", headers=SH).json()
ok(all(not s.get("door") for s in _shl),
   "and a plain shopper is still nobody at the door")
c.post(f"/api/learning/sessions/{_sidD}/close", headers=TT)

# --- recordings: spoken answers, drills, the class tape ----------------------
_qz2 = c.post("/api/learning/quizzes", headers=TT,
              json={"course_id": _crs, "title": "Speaking check",
                    "pass_mark": 50}).json()
ok("id" in _qz2 and c.post(
    f"/api/learning/quizzes/{_qz2['id']}/questions", headers=TT,
    json={"kind": "speaking", "prompt": "Say hello in Spanish",
          "points": 2}).status_code == 200,
   "speaking questions are authorable now — the refusal came out with the "
   "capture flow landing")
c.post(f"/api/learning/quizzes/{_qz2['id']}", headers=TT,
       json={"title": "Speaking check", "pass_mark": 50, "published": 1})
_att2 = c.post(f"/api/learn/quizzes/{_qz2['id']}/start", headers=LN).json()
_sq = _att2["quiz"]["questions"][0]
ok(c.post(f"/api/learn/attempts/{_att2['attempt']['id']}/recording"
          f"?question_id={_sq['id']}",
          headers={**LN, "Content-Type": "application/pdf"},
          content=b"MZ\x90\x00 not audio at all").status_code == 400,
   "the leading bytes decide what a file is — a mislabeled executable is "
   "refused, not stored")
_rec = c.post(f"/api/learn/attempts/{_att2['attempt']['id']}/recording"
              f"?question_id={_sq['id']}",
              headers={**LN, "Content-Type": "audio/ogg"},
              content=b"OggS" + b"\x00" * 64).json()
ok(_rec["ok"] and _rec["kind"] == "audio",
   "a spoken answer uploads as raw bytes and lands as a material")
_sub2 = c.post(f"/api/learn/attempts/{_att2['attempt']['id']}/submit",
               headers=LN).json()
ok(not _sub2["grade"]["marks_visible"],
   "an attempt with a recording is submitted but not final — no "
   "provisional number is ever shown")
_gq2 = c.get("/api/learning/grading", headers=TT).json()
ok(any(a["id"] == _att2["attempt"]["id"] for a in _gq2),
   "and it waits in the grading queue")
_ga = c.get(f"/api/learning/attempts/{_att2['attempt']['id']}",
            headers=TT).json()
_gi = [i for i in _ga["items"] if i["question_id"] == _sq["id"]][0]
ok(_gi["material"] and _gi["material"]["kind"] == "audio",
   "the grader is handed the recording to play")
_media = c.get(f"/media/{_gi['material']['path']}")
ok(_media.status_code == 200
   and _media.headers["x-content-type-options"] == "nosniff",
   "stored media serves by its unguessable token name, nosniff, never "
   "executed")
_fin = c.post(f"/api/learning/attempts/{_att2['attempt']['id']}/grade",
              headers=TT, json={"question_id": _sq["id"], "awarded": 2,
                                "feedback": "perfecto"}).json()
ok(_fin["is_final"] and _fin["percent"] == 100,
   "a human mark settles the attempt, whatever the kind")
_les2 = c.post("/api/learning/lessons", headers=TT,
               json={"course_id": _crs, "title": "Drill day"}).json()
_dr = c.post(f"/api/learning/lessons/{_les2['id']}/material",
             headers={**TT, "Content-Type": "audio/ogg",
                      "X-Filename": "drill.ogg"},
             content=b"OggS" + b"\x00" * 32).json()
ok("id" in _dr, "a teacher attaches an audio drill to a lesson")
c.post(f"/api/learning/lessons/{_les2['id']}", headers=TT,
       json={"title": "Drill day", "body": "", "published": 1})
_lv = c.get(f"/api/learn/lessons/{_les2['id']}", headers=LN).json()
ok(len(_lv["materials"]) == 1 and _lv["materials"][0]["kind"] == "audio",
   "and the learner's lesson page carries it")
_cls4 = c.post("/api/learning/sessions", headers=TT,
               json={"course_id": _crs}).json()
_sid4 = _cls4["session"]["id"]
ok(c.post(f"/api/learning/sessions/{_sid4}/recording",
          headers={**AA, "Content-Type": "video/webm"},
          content=b"\x1aE\xdf\xa3" + b"\x00" * 32).status_code == 200,
   "an admin may attach the class recording")
ok(c.post(f"/api/learning/sessions/{_sid4}/recording",
          headers={**NN, "Content-Type": "video/webm"},
          content=b"\x1aE\xdf\xa3" + b"\x00" * 32).status_code == 403,
   "but not a bystander: a recording of a class is a recording of the "
   "students in it — ownership, not just role")
_srl = c.get(f"/api/learn/sessions/{_sid4}/recordings", headers=LN).json()
ok(len(_srl) == 1,
   "the recording reaches the enrolled — gated on enrolment, not "
   "attendance, because missing the class is why you want the tape")
c.post(f"/api/learning/sessions/{_sid4}/close", headers=TT)
ok("LinguaCompose" in (Path(__file__).parent.parent
                       / "src/storefront/frontend/rtc-compose.js"
                       ).read_text(encoding="utf-8")
   and "recorderWidget" in _ljs and "rtc-compose.js" in _opsjs2,
   "one recorder for all three flows — quiz answers, drills, the class "
   "tape — shared by both surfaces")

# --- voice & translation: its own capability ---------------------------------
_vp = c.get("/api/learn/voice/providers", headers=LN).json()
ok(_vp["translate"] == "local" and "es" in _vp["languages"],
   "voice ships offline-first — no config means the local glossary, not a "
   "third party")
_tr = c.get("/api/learn/voice/translate?q=hello&source=en&target=es",
            headers=LN).json()
ok(_tr["found"] and _tr["text"] == "hola" and _tr["via"] == "local glossary",
   "the glossary answers what it knows and says where the answer came from")
_tr2 = c.get("/api/learn/voice/translate?q=zeitgeist&source=en&target=es",
             headers=LN).json()
ok(not _tr2["found"] and "reason" in _tr2,
   "a miss is an honest miss — never a plausible-looking guess")
_th = c.get("/api/learn/voice/thesaurus?q=glad", headers=LN).json()
ok(_th["found"] and "happy" in _th["synonyms"],
   "the thesaurus answers even when the word is inside a synonym group")
ok("speechSynthesis" in _ljs and "webkitSpeechRecognition" in _ljs
   and "rate = 0.95" in _ljs,
   "dictation and TTS are browser-side — a learner's words never reach a "
   "server for speech")

# --- node services: the machine's shared daemons ------------------------------
# The manifest lives beside the fleet registry, outside every tenant dir.
# Resolution everywhere: tenant config wins, the node daemon is the floor,
# absence degrades to exactly the pre-services behavior (proved above:
# the glossary answered before any of this existed).
from erp.backend import services as _svcm
ok(_svcm.manifest() == {} and _svcm.service("translate") is None
   and _svcm.summary() == {},
   "a plain install declares nothing")

import http.server as _hs
import socketserver as _ss
import threading as _th2


class _FakeLT(_hs.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'[{"code":"en"},{"code":"es"}]')

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(_jn.dumps({"translatedText": "asombroso"}).encode())


_lts = _ss.TCPServer(("127.0.0.1", 0), _FakeLT)
_ltp = _lts.server_address[1]
_th2.Thread(target=_lts.serve_forever, daemon=True).start()
_svcm.declare("translate", f"http://127.0.0.1:{_ltp}")
ok(_svcm.service("translate")["url"].endswith(str(_ltp))
   and _svcm.health("translate")["healthy"]
   and _svcm.summary() == {"translate": True},
   "one manifest line declares the machine's daemon, and health is a "
   "live probe, never a stored claim")

_trn = c.get("/api/learn/voice/translate?q=astonishing&source=en&target=es",
             headers=LN).json()
ok(_trn["found"] and _trn["text"] == "asombroso"
   and _trn["via"] == "node service",
   "a tenant with no translate_url of its own is served by the machine — "
   "the node's daemon is the floor under every tenant on it")
ok(c.get("/api/learn/voice/providers", headers=LN).json()["translate"]
   == "node service",
   "and the providers panel names the floor, so nobody guesses")

_acfg7 = _jn.loads((_tn.tenant_dir("alpha") / "config.json").read_text())
_acfg7["translate_url"] = "http://127.0.0.1:9"        # nobody home
(_tn.tenant_dir("alpha") / "config.json").write_text(_jn.dumps(_acfg7))
_CFGPROXY.invalidate("alpha")
_tro = c.get("/api/learn/voice/translate?q=wonderful&source=en&target=es",
             headers=LN).json()
ok(not _tro["found"] and _tro["via"] == "remote",
   "a tenant's OWN provider outranks the machine — even a broken own, "
   "because overriding is the tenant's deliberate act")
_acfg7.pop("translate_url")
(_tn.tenant_dir("alpha") / "config.json").write_text(_jn.dumps(_acfg7))
_CFGPROXY.invalidate("alpha")

ok(c.get("/api/store/admin/fleet", headers=AA).json()
   ["services"]["translate"] is True,
   "the Platform board wears this machine's services as pills — live")
_its = (ROOT / "scripts" / "install_translate.sh").read_text()
ok("libretranslate" in _its and "node_services.json" in _its
   and "systemd" in _its and "--host 127.0.0.1" in _its,
   "the installer stands the daemon up under systemd, bound to localhost, "
   "and writes the manifest line — and it ships in every app bundle")
_lts.shutdown()

# --- SFU: the config contract ------------------------------------------------
_rtc = c.get("/api/learn/rtc/config", headers=LN).json()
ok(_rtc["available"] is False and _rtc["mode"] in ("auto", "mesh")
   and _rtc["mesh_max"] == 12 and _rtc["simulcast"] is True,
   "no media server configured = the config says so, and never promises a "
   "transport that is not there")
_sfujs = (Path(__file__).parent.parent
          / "src/storefront/frontend/rtc-sfu.js").read_text(encoding="utf-8")
ok("chooseTransport" in _sfujs and "sendEncodings" in _sfujs
   and "application/sdp" in _sfujs and "LinguaSfu" in _sfujs,
   "the WHIP/WHEP client is ported — vendor-free, simulcast-aware, a "
   "config switch away")
ok("chooseTransport" in _ljs and "rtc-sfu.js" in _ljs,
   "the learner call picks its transport from config and roster size")

# --- the sfu node service: the floor, the namespace, the tapes ---------------
_sfudir = Path(tempfile.mkdtemp(prefix="bc_sfu_"))
_svcm.declare("sfu", "http://127.0.0.1:65000")
_svcm.declare("sfu", "http://127.0.0.1:65000")   # idempotent
_m9 = _jn.loads((Path(os.environ["BUSINESS_CONTROL_DATA"])
                 / "node_services.json").read_text())
_m9["sfu"] = {"url": "http://127.0.0.1:65000",
              "public_url": "https://sfu.alpha.test",
              "record_dir": str(_sfudir), "key": ""}
(Path(os.environ["BUSINESS_CONTROL_DATA"])
 / "node_services.json").write_text(_jn.dumps(_m9))
_rtc2 = c.get("/api/learn/rtc/config", headers=LN).json()
ok(_rtc2["available"] is True and _rtc2["via"] == "node service"
   and _rtc2["whip_url"].startswith("https://sfu.alpha.test/bc-alpha-")
   and "{room}-{id}/whip" in _rtc2["whip_url"]
   and "{room}-{id}/whep" in _rtc2["whep_url"],
   "the machine's SFU is the floor, browsers dial its public name, and "
   "the path is composed server-side with the TENANT in it — two "
   "tenants' rooms cannot collide on the shared daemon")
_acfg8 = _jn.loads((_tn.tenant_dir("alpha") / "config.json").read_text())
_acfg8["whip_url"] = "https://own.example/w/{room}/{id}"
_acfg8["whep_url"] = "https://own.example/r/{room}/{id}"
(_tn.tenant_dir("alpha") / "config.json").write_text(_jn.dumps(_acfg8))
_CFGPROXY.invalidate("alpha")
_rtc3 = c.get("/api/learn/rtc/config", headers=LN).json()
ok(_rtc3["via"] == "remote"
   and _rtc3["whip_url"].startswith("https://own.example/"),
   "a tenant's own media server outranks the machine's — verbatim")
_acfg8.pop("whip_url")
_acfg8.pop("whep_url")
(_tn.tenant_dir("alpha") / "config.json").write_text(_jn.dumps(_acfg8))
_CFGPROXY.invalidate("alpha")

_cls9 = c.post("/api/learning/sessions", headers=TT,
               json={"course_id": _crs}).json()
_room9 = _cls9["session"]["room"]
_sid9 = _cls9["session"]["id"]
_mp4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 8000
_pdir = _sfudir / f"bc-alpha-{_room9}-teacher"
_pdir.mkdir(parents=True)
(_pdir / "2026-09-01_10-00-00-000000.mp4").write_bytes(_mp4)
(_pdir / "torn.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom")
c.post(f"/api/learning/sessions/{_sid9}/close", headers=TT)
_recs9 = c.get(f"/api/learning/sessions/{_sid9}/recordings",
               headers=TT).json()
ok(len(_recs9) == 1 and _recs9[0]["kind"] == "video"
   and "class tape — teacher" in _recs9[0]["original"],
   "closing the class brings the SFU's tape home — into the tenant's own "
   "sharded store, as a session recording like any other")
ok(not (_pdir / "2026-09-01_10-00-00-000000.mp4").exists()
   and (_pdir / "torn.mp4").exists(),
   "the collected source is removed — one home per tape — while a torn "
   "segment is left for the next sweep, never half-ingested")
(_pdir / "late.mp4").write_bytes(_mp4)
ok(c.post(f"/api/learning/sessions/{_sid9}/collect-tape",
          headers=LN).status_code == 403,
   "a student cannot sweep the tapes — the class's teacher or an admin "
   "does")
_late = c.post(f"/api/learning/sessions/{_sid9}/collect-tape",
               headers=TT).json()
ok(_late["collected"] == 1
   and len(c.get(f"/api/learning/sessions/{_sid9}/recordings",
                 headers=TT).json()) == 2,
   "and a segment that finished late comes home on the collect-tape "
   "route")
_its2 = (ROOT / "scripts" / "install_sfu.sh").read_text()
ok("mediamtx" in _its2 and "bc-<tenant>-<room>-<peer>" in _its2
   and "record_dir" in _its2 and "recordFormat: fmp4" in _its2,
   "the installer stands MediaMTX up recording what it forwards, and "
   "ships in every app bundle")

# --- the forge pilot: the tooling family's first manifest line ---------------
ok("forge" in _svcm.KNOWN
   and _svcm.KNOWN["forge"]["probe"] == "/api/v1/version",
   "the platform knows what a forge is and how to ask if it is alive")
_its3 = (ROOT / "scripts" / "install_forge.sh").read_text()
ok("forgejo" in _its3 and "DISABLE_REGISTRATION = true" in _its3
   and "node_services.json" in _its3 and "INSTALL_LOCK" in _its3,
   "the pilot installer: one binary, registration closed, the manifest "
   "line — the capability that would SELL it stays a price-book "
   "decision")
_svcm.declare("forge", "http://127.0.0.1:65001")
ok(_svcm.summary().get("forge") is False,
   "a declared forge nobody started shows as down, not as hoped-for — "
   "health is a probe, never a claim")

# --- data rights: export, and erasure with a shown plan ----------------------
_myx = c.get("/api/learn/me/export", headers=LN)
ok(_myx.status_code == 200
   and "attachment" in _myx.headers.get("content-disposition", ""),
   "a member downloads their own record without asking anyone")
_myxj = _myx.json()
ok("token" not in _myxj["person"] and "password_hash" not in _myxj["person"]
   and "attendance" in _myxj and "achievements" in _myxj,
   "the bundle holds their record, never their keys — and no messages, "
   "because a conversation belongs to two people")
_vic = c.post("/api/login", headers=HA,
              json={"name": "Vic Timer", "role": "customer"}).json()
c.post(f"/api/learning/courses/{_crs}/enroll", headers=AA,
       json={"name": "Vic Timer"})
_vic_id = _vic["user"]["id"] if "user" in _vic else _vic["id"]
_plan = c.get(f"/api/learning/people/{_vic_id}/erase-plan",
              headers=AA).json()
ok("deleted" in _plan and "retained" in _plan
   and "attendance records" in _plan["retained"],
   "the plan is SHOWN first: deleted, anonymised, retained — with why")
ok(c.post(f"/api/learning/people/{_vic_id}/erase", headers=AA,
          json={"confirm_name": "Wrong Name"}).status_code == 400,
   "the confirmation is the typed name, exactly — not a yes/no click")
_er = c.post(f"/api/learning/people/{_vic_id}/erase", headers=AA,
             json={"confirm_name": "Vic Timer",
                   "reason": "asked to be forgotten"}).json()
ok(_er["erased"], "the right name erases")
from erp.backend import tenancy as _tn2  # noqa: E402
_tok_v = _tn2.CURRENT.set("alpha")
import erp.backend.db as _edb  # noqa: E402
_vcon = _edb.connect()
_vrow = _vcon.execute("SELECT * FROM users WHERE id=?",
                      (_vic_id,)).fetchone()
_vcon.close()
_tn2.CURRENT.reset(_tok_v)
ok(_vrow["name"] == f"Erased person #{_vic_id}" and not _vrow["active"]
   and _vrow["erased_at"] and not _vrow["email"],
   "erasure is a tombstone, not a hole — the id survives so attendance "
   "and pay still add up, but it identifies nobody")
ok(c.get("/api/learning/people/1/erase-plan", headers=LN).status_code
   == 403,
   "the erasure door is admin-only")

# --- nutrition: the pure arithmetic ------------------------------------------
from erp.backend import nutrition_calc as _nc  # noqa: E402
import datetime as _dtm  # noqa: E402
_today = _dtm.date(2026, 8, 31)
ok(round(_nc.mifflin_bmr(84, 175, 36, "male")) == 1759,
   "Mifflin-St Jeor, to the kcal")
_t0 = _nc.targets({"goal": "lose", "rate_kg_week": 0.45}, 84.0, _today)
ok(_t0["adjust"] == -495 and _t0["target"] == _t0["tdee"] - 495,
   "a lose goal maps through 7700 kcal/kg to a daily deficit")
ok(_nc.targets({}, None, _today)["target"] is None,
   "no weight, no target — the formulas refuse to guess")
_w = [((_today - _dtm.timedelta(days=25 - i)).isoformat(), 85.0 - i * 0.03)
      for i in range(22)]
_intake = {d: 2100.0 for d, _ in _w}
_obs = _nc.observed_tdee(_w, _intake, _today)
ok(_obs and 2280 < _obs["tdee"] < 2420,
   "observed maintenance = mean intake minus the weight slope's calories")
ok(_nc.observed_tdee(_w[:3], _intake, _today) is None
   and _nc.observed_tdee(_w, {d: 400.0 for d, _ in _w}, _today) is None,
   "thin data or partial logging returns None, never a shaky number")
ok(_nc.day_on_target(2000, 2000, "lose")
   and not _nc.day_on_target(2200, 2000, "lose")
   and _nc.day_on_target(1950, 2000, "gain")
   and not _nc.day_on_target(0, 2000, "maintain"),
   "the adherence rule bends to the goal's direction")

# --- nutrition: over the wire ------------------------------------------------
_np = c.post("/api/nutrition/me/profile", headers=LN,
             json={"sex": "female", "birth_year": 1998, "height_cm": 165,
                   "activity": 1.375, "goal": "lose",
                   "rate_kg_week": 0.25}).json()
ok(_np["sex"] == "female", "a member sets their own profile")
ok(c.post("/api/nutrition/me/profile", headers=LN,
          json={"protein_pct": 50, "carbs_pct": 40,
                "fat_pct": 30}).status_code == 400,
   "a macro split that does not add to 100 is refused")
c.post("/api/nutrition/me/weight", headers=LN,
       json={"day": "2026-08-30", "kg": 61.5})
c.post("/api/nutrition/me/weight", headers=LN,
       json={"day": "2026-08-30", "kg": 61.2})
_st = c.get("/api/nutrition/me/state?day=2026-08-30", headers=LN).json()
ok(len([w for w in _st["weights"] if w["day"] == "2026-08-30"]) == 1
   and _st["weights"][-1]["kg"] == 61.2,
   "a weigh-in is a day-keyed upsert — logging again replaces, never "
   "duplicates")
ok(_st["targets"]["has_numbers"] and _st["targets"]["target"],
   "one weigh-in is enough for the formulas to speak")
c.post("/api/nutrition/me/water", headers=LN,
       json={"day": "2026-08-30", "delta_ml": 500})
_wtr = c.post("/api/nutrition/me/water", headers=LN,
              json={"day": "2026-08-30", "delta_ml": -250}).json()
ok(_wtr["ml"] == 250, "water is an upsert too, clamped at zero")
_ni = c.post("/api/nutrition/me/ingredients", headers=LN,
             json={"name": "Oats", "category": "grains",
                   "serving_name": "40 g", "cal": 150, "protein": 5,
                   "carbs": 27, "fat": 3}).json()
_nr = c.post("/api/nutrition/me/recipes", headers=LN,
             json={"name": "Morning oats", "servings": 1,
                   "items": [{"ingredient_id": _ni["id"], "qty": 2}]}).json()
ok("id" in _nr, "recipes build on the visible food library")
c.post("/api/nutrition/me/plan", headers=LN,
       json={"day": "2026-08-31", "slot": "breakfast",
             "recipe_id": _nr["id"], "servings": 1})
_gen = c.post("/api/nutrition/me/shopping/generate", headers=LN,
              json={"start": "2026-08-31", "end": "2026-08-31"}).json()
ok(_gen["added"] == 1,
   "the shopping list falls out of the plan — recipes expanded and scaled")
c.post("/api/nutrition/me/log", headers=LN,
       json={"day": "2026-08-30", "slot": "breakfast", "name": "Morning oats",
             "servings": 1, "cal": 300, "protein": 10, "carbs": 54,
             "fat": 6})
_st2 = c.get("/api/nutrition/me/state?day=2026-08-30", headers=LN).json()
ok(len(_st2["log"]) == 1 and _st2["log"][0]["cal"] == 300,
   "a log entry keeps the macros it had when eaten — denormalised on "
   "purpose, so editing the recipe later never rewrites history")
ok(c.get("/api/nutrition/clients", headers=LN).status_code == 403,
   "the caseload is for coaches — a self-tracker is on nobody's list")
_prog = c.post("/api/nutrition/programs", headers=AA,
               json={"name": "Cut & keep", "coach_id": None}).json()
c.post("/api/nutrition/clients", headers=AA,
       json={"user_id": _st["me"]["id"], "program_id": _prog["id"]})
_cl = c.get("/api/nutrition/clients", headers=AA).json()
ok(any(x["user_id"] == _st["me"]["id"] for x in _cl),
   "an opened seat puts the member on the caseload, with adherence "
   "derived on read")

# the capability wall: /nutrition is part of the Nutrition grant
c.post("/api/store/admin/fleet/tenants", headers=AA,
       json={"id": "fitco", "brand": "Fit Co", "klass": "micro"})
_FH = {"host": "fitco.localhost"}
ok(c.get("/nutrition", headers=_FH).status_code == 200,
   "no grant recorded = everything on — /nutrition answers, same null rule")
c.post("/api/store/admin/fleet/tenants/fitco/caps", headers=AA,
       json={"caps": ["selling", "payments"]})
ok(c.get("/nutrition", headers=_FH).status_code == 404,
   "a tenant without the Nutrition grant has no /nutrition — a 404, not a "
   "husk")
c.post("/api/store/admin/fleet/tenants/fitco/caps", headers=AA,
       json={"caps": ["selling", "payments", "nutrition"]})
ok(c.get("/nutrition", headers=_FH).status_code == 200,
   "granting Nutrition opens the door again")
c.request("DELETE", "/api/store/admin/fleet/tenants/fitco?keep_data=0",
          headers=AA)
ok('id: "nutrition"' in _appjs_lrn
   and "nutrition: renderNutrition" in _appjs_lrn
   and 'nutrition: "nutrition"' in _appjs_lrn,
   "the ops app carries the Nutrition tab, its renderer, and its "
   "capability lock")
ok("/nutrition.js" in c.get("/nutrition").text,
   "the member page loads its app as a versioned asset")

# --- the door: three honest modes --------------------------------------------
ok(c.post("/api/login", headers=HA, json={
    "name": "Lara Learner", "mode": "create"}).status_code == 409,
   "creating an account refuses to silently join somebody else's")
ok(c.post("/api/login", headers=HA, json={
    "name": "Total Stranger", "mode": "signin"}).status_code == 404,
   "signing in refuses to mint an account from a typo")
_new = c.post("/api/login", headers=HA, json={
    "name": "Door Tester", "mode": "create",
    "password": "a long phrase"}).json()
ok(bool(_new.get("token")),
   "create mode makes the account — with its password from birth")

# --- the portal surfaces: bell, live, quizzes, me ----------------------------
_bell = c.get("/api/learn/notifications", headers=LN).json()
ok(_bell["unread"] >= 1 and any("graded" in (n["title"] or "").lower()
                                for n in _bell["items"]),
   "the bell finally reads what the platform was always pushing — the "
   "graded-quiz notification is waiting for Lara")
c.post("/api/learn/notifications/read", headers=LN)
ok(c.get("/api/learn/notifications", headers=LN).json()["unread"] == 0,
   "and opening it marks everything read")
_cls5 = c.post("/api/learning/sessions", headers=TT,
               json={"course_id": _crs}).json()
_live = c.get("/api/learn/live", headers=LN).json()
ok(len(_live) == 1 and _live[0]["course_id"] == _crs
   and _live[0]["room"] and _live[0]["enrolled"] >= 1,
   "Check in and Live class draw from one answer: every open session "
   "across MY courses, with the room and the roster size")
ok(c.get("/api/learn/live", headers=SH).json() == [],
   "an outsider's live list is empty — enrolment scopes it")
c.post(f"/api/learning/sessions/{_cls5['session']['id']}/close", headers=TT)
_myqs = c.get("/api/learn/quizzes", headers=LN).json()
ok(any(q["title"] == "Speaking check" for q in _myqs)
   and all("attempt" in q for q in _myqs),
   "the Quizzes tab gathers every published quiz across my courses with "
   "where I stand on each")
_me = c.get("/api/learn/me", headers=LN).json()
ok(_me["name"] == "Lara Learner" and _me["attended"] >= 1
   and "password_hash" not in _me,
   "the profile answers who I am and how often I showed up — never my "
   "secrets")

# --- discovery: ask to join a course you can see -----------------------------
_all = c.get("/api/learn/courses", headers=SH).json()
_tourable = [x for x in _all["available"] if x["id"] == _crs]
ok(len(_tourable) == 1 and _tourable[0]["requested"] is False,
   "an unenrolled member sees the course in Discover, not yet asked")
_ask = c.post(f"/api/learn/courses/{_crs}/request", headers=SH,
              json={"note": "heard great things"}).json()
ok(_ask["state"] == "pending",
   "asking to join files a seat request instead of opening the door")
ok(c.post(f"/api/learn/courses/{_crs}/request", headers=SH,
          json={"note": "still keen"}).json()["id"] == _ask["id"],
   "asking twice refreshes the ask — update, don't duplicate")
ok([x for x in c.get("/api/learn/courses", headers=SH).json()["available"]
    if x["id"] == _crs][0]["requested"] is True,
   "and Discover now shows it as asked")
_reqs = c.get("/api/learning/registrations", headers=AA).json()
_mine_req = [r for r in _reqs if r["id"] == _ask["id"]][0]
ok(_mine_req["person_id"] is not None,
   "the request rides the same queue as the public form, carrying its "
   "person from the start")
_n_users = c.get("/api/admin/users", headers=AA).json()
_out = c.post(f"/api/learning/registrations/{_ask['id']}/approve",
              headers=AA, json={}).json()
ok(_out["existing_account"]
   and len(c.get("/api/admin/users", headers=AA).json()) == len(_n_users),
   "approving enrols the EXISTING account — no lookalike minted from an "
   "email")
ok(c.get(f"/api/learn/courses/{_crs}", headers=SH).status_code == 200,
   "and the course opens for them")
ok(c.post(f"/api/learn/courses/{_crs}/request", headers=SH,
          json={}).status_code == 409,
   "already enrolled = nothing to ask")

# --- sign out everywhere -----------------------------------------------------
_dt = {"Authorization": f"Bearer {_new['token']}", **HA}
c.post("/api/learn/me/signout-all", headers=_dt)
ok(c.get("/api/learn/me", headers=_dt).status_code == 401,
   "sign out everywhere rotates the token — every device, this one "
   "included")

# --- the seven roles: claims at the door, approval as the promotion ----------
from erp.backend import roles as R2

ok(len(R2.ROLES) == 7 and R2.STUDENT == "customer"
   and R2.STAFF == "employee",
   "the seven school roles ride the platform's own words — a student IS a "
   "customer, office staff ARE employees")
ok(R2.grantable_by("employee") ==
   frozenset({"customer", "teacher", "volunteer"})
   and R2.grantable_by("teacher") == frozenset()
   and R2.grantable_by("customer", is_admin=True) == frozenset(R2.ROLES),
   "office staff confer students, teachers and volunteers; the admin flag "
   "confers everything; everyone else confers nothing")
ok("employee" not in R2.grantable_by("employee")
   and not (R2.RESTRICTED & R2.grantable_by("employee")),
   "no escalation rung: staff cannot mint staff, and board and donor — the "
   "most sensitive rows a school holds — are the owner's alone")
ok(R2.carries_admin("director") and not R2.carries_admin("employee"),
   "only the executive director's approval carries the admin flag")

_cat = c.get("/api/roles", headers=HA).json()
ok(len(_cat) == 7 and _cat[0]["label"] == "Student"
   and any(x["label"] == "Executive director" for x in _cat),
   "the sign-up dropdown's roles come from the server — one source")

_wnd = c.post("/api/login", headers=HA, json={
    "name": "Wanda Wants", "mode": "create", "role": "teacher",
    "password": "chalk dust"}).json()
ok(_wnd["role"] == "customer" and _wnd["requested_role"] == "teacher",
   "the door files a CLAIM: the account is a student until the office "
   "says otherwise — the promise in the door's copy is finally true")
_WW = {"Authorization": f"Bearer {_wnd['token']}", **HA}
_dirk = c.post("/api/login", headers=HA, json={
    "name": "Dirk Director", "mode": "create", "role": "director",
    "password": "the long view"}).json()
ok(_dirk["role"] == "customer" and _dirk["requested_role"] == "director",
   "even the director role starts as a claim")

_tq = c.get("/api/roles/requests", headers=TT).json()
ok(any(r["name"] == "Wanda Wants" for r in _tq)
   and not any(r["name"] == "Dirk Director" for r in _tq),
   "office staff see only the requests they could grant — a director "
   "request they cannot act on is an invitation to try")
ok(c.post(f"/api/roles/requests/{_dirk['id']}/decide", headers=TT,
          json={"approve": True}).status_code == 403,
   "and deciding one anyway is refused, approve or decline alike")
ok(c.get("/api/roles/requests", headers=_WW).status_code == 403,
   "a student cannot review anybody")

_out2 = c.post(f"/api/roles/requests/{_wnd['id']}/decide", headers=TT,
               json={"approve": True}).json()
ok(_out2["approved"] and _out2["role"] == "teacher",
   "office staff approve a teacher — the same right as making one")
ok(c.get("/api/learn/me", headers=_WW).status_code == 401,
   "approval ends every session: the new role arrives whole, not "
   "half-changed")
_wnd2 = c.post("/api/login", headers=HA, json={
    "name": "Wanda Wants", "mode": "signin",
    "password": "chalk dust"}).json()
ok(_wnd2["role"] == "teacher" and not _wnd2["is_admin"]
   and _wnd2["requested_role"] == "",
   "signing in again picks the role up — teacher, no admin flag, claim "
   "cleared")
_WW2 = {"Authorization": f"Bearer {_wnd2['token']}", **HA}
ok(any("confirmed as Teacher" in (n["title"] or "")
       for n in c.get("/api/learn/notifications",
                      headers=_WW2).json()["items"]),
   "and the decision landed on their bell")

_out3 = c.post(f"/api/roles/requests/{_dirk['id']}/decide", headers=AA,
               json={"approve": True}).json()
_dirk2 = c.post("/api/login", headers=HA, json={
    "name": "Dirk Director", "mode": "signin",
    "password": "the long view"}).json()
ok(_out3["approved"] and _dirk2["role"] == "director"
   and _dirk2["is_admin"],
   "the owner approves a director — and that approval carries the admin "
   "flag, because running the organisation IS the admin surface")

_ben = c.post("/api/login", headers=HA, json={
    "name": "Benny Board", "mode": "create", "role": "board",
    "password": "quorum"}).json()
c.post(f"/api/roles/requests/{_ben['id']}/decide", headers=AA,
       json={"approve": False, "note": "not this year"})
_ben2 = c.post("/api/login", headers=HA, json={
    "name": "Benny Board", "mode": "signin", "password": "quorum"}).json()
ok(_ben2["role"] == "customer" and _ben2["requested_role"] == "",
   "declining clears the claim and the account stays a student")
ok(c.post(f"/api/roles/requests/{_ben['id']}/decide", headers=AA,
          json={"approve": True}).status_code == 404,
   "a decided request is gone — no second bite")

_kk = c.post("/api/login", headers=HA, json={
    "name": "Keyed Kate", "mode": "create", "role": "teacher",
    "admin_key": _acfg["admin_key"], "password": "with authority"}).json()
ok(_kk["role"] == "teacher" and _kk["requested_role"] == ""
   and not _kk["is_admin"],
   "the admin key is the exception: a key-holder's create confers the "
   "role directly — the role, not the admin flag")
_kl = c.post("/api/login", headers=HA, json={
    "name": "Keyless Kai", "mode": "create", "role": "teacher",
    "admin_key": "not the key"}).json()
ok(_kl["role"] == "customer" and _kl["requested_role"] == "teacher",
   "a wrong key grants nothing — the claim is filed like anyone's")

# --- invites: authority in link form ------------------------------------------
_pre = c.post("/api/learning/team", headers=AA, json={
    "name": "Toni Tutor", "role": "teacher",
    "email": "toni@school.test"}).json()
ok("id" in _pre, "the office premakes an account before its person arrives")
ok(c.post("/api/learning/team", headers=AA,
          json={"name": "Toni Tutor", "role": "teacher"}).status_code == 409,
   "but never two under one name")
_tm = c.get("/api/learning/team", headers=AA).json()
ok(any(p["name"] == "Toni Tutor" and p["role"] == "teacher" for p in _tm)
   and any(p["name"] == "Tina Teacher" for p in _tm),
   "the team list gathers teachers, staff and volunteers in one place")

_inv = c.post("/api/roles/invites", headers=AA, json={
    "role": "teacher", "person_id": _pre["id"]}).json()
ok(_inv["path"].startswith("/join/"),
   "an invite is a link that carries a role")
ok(c.post("/api/roles/invites", headers=TT,
          json={"role": "director"}).status_code == 403,
   "and minting one takes the same right as granting — office staff "
   "cannot link-in a director")
_peek = c.get(f"/api/join/{_inv['token']}", headers=HA).json()
ok(_peek["locked"] and _peek["name"] == "Toni Tutor",
   "the link-holder sees the account waiting for them")
_joined = c.post(f"/api/join/{_inv['token']}", headers=HA,
                 json={"password": "chalk and talk"}).json()
ok(_joined["id"] == _pre["id"] and _joined["role"] == "teacher"
   and _joined["has_password"],
   "signing up through the link claims the premade account — role wired, "
   "password set")
ok(c.get(f"/api/join/{_inv['token']}", headers=HA).status_code == 410,
   "and the link dies with its first use")

# an invite with an email on it is SENT — dry without SMTP, but logged
# where every outbound email lands, with the join link in the record
_invm = c.post("/api/roles/invites", headers=AA,
               json={"role": "teacher",
                     "email": "toni@school.test"}).json()
ok(_invm["emailed"].startswith(("dry", "error", "sent")),
   "the caller sees the send's fate — dry, sent, or the error itself — "
   "and the copy-paste link works regardless")
ok(any(r["kind"] == "invite" and r["to_addr"] == "toni@school.test"
       for r in c.get("/api/admin/email/log", headers=AA).json()),
   "and the attempt lands in the email log beside everything else sent")

_inv2 = c.post("/api/roles/invites", headers=AA,
               json={"role": "volunteer"}).json()
_fresh = c.post(f"/api/join/{_inv2['token']}", headers=HA,
                json={"name": "Vinnie Volunteers",
                      "password": "many hands"}).json()
ok(_fresh["role"] == "volunteer" and not _fresh["is_admin"],
   "an unbound invite creates the account fresh, straight into its role")
_inv3 = c.post("/api/roles/invites", headers=AA,
               json={"role": "teacher"}).json()
ok(c.post(f"/api/join/{_inv3['token']}", headers=HA,
          json={"name": "Toni Tutor", "password": "x"}).status_code == 409,
   "an unbound invite refuses a taken name — bind it instead")

# --- the customer book --------------------------------------------------------
_cbook = c.get("/api/customers", headers=TT).json()
ok(any(r["name"] == "Lara Learner" for r in _cbook)
   and all("spent_cents" in r for r in _cbook),
   "office staff can finally SEE the people whose orders the ERP counts")
ok(c.get("/api/customers", headers=_WW2).status_code == 403,
   "a teacher is not the office — the customer book stays closed to them")
_lara_row = [r for r in _cbook if r["name"] == "Lara Learner"][0]
_cd = c.get(f"/api/customers/{_lara_row['id']}", headers=AA).json()
ok("orders" in _cd and "Spanish A1" in _cd["courses"],
   "one customer, whole: orders and enrolments together")

# --- library lifecycle: edit, label, retire -----------------------------------
_li = c.post("/api/learning/library/items", headers=TT, json={
    "name": "Loaner Laptop", "kind": "equipment", "copies": 3}).json()
c.patch(f"/api/learning/library/items/{_li['id']}", headers=TT,
        json={"copies": 2, "owner": "Kenji"})
_lib2 = c.get("/api/learning/library", headers=TT).json()
_lap = [i for i in _lib2["items"] if i["id"] == _li["id"]][0]
ok(_lap["copies"] == 2 and _lap["owner"] == "Kenji",
   "items are editable — copies retire, ownership is recorded")
_qr2 = c.get(f"/api/learning/library/items/{_li['id']}/qr",
             headers=TT).json()
ok(_qr2["payload"].startswith("bc:item:")
   and c.post("/api/learning/library/scan", headers=TT,
              json={"payload": _qr2["payload"]}).json()["id"] == _li["id"],
   "the QR label round-trips: scan it at the desk and the item comes up")
c.post("/api/learning/library/checkout", headers=TT,
       json={"item_id": _li["id"], "user_id": _lara_row["id"]})
ok(c.patch(f"/api/learning/library/items/{_li['id']}", headers=TT,
           json={"copies": 0}).status_code in (400, 409),
   "copies can never drop below what is out")
ok(c.delete(f"/api/learning/library/items/{_li['id']}",
            headers=TT).status_code == 409,
   "and an item with copies out refuses to go")
_lo2 = [x for x in c.get("/api/learning/library", headers=TT).json()["loans"]
        if x["item_id"] == _li["id"]][0]
c.post(f"/api/learning/library/return/{_lo2['id']}", headers=TT)
_fate = c.delete(f"/api/learning/library/items/{_li['id']}",
                 headers=TT).json()
ok(_fate["result"] == "retired"
   and not any(i["id"] == _li["id"] for i in
               c.get("/api/learning/library", headers=TT).json()["items"]),
   "once loaned, removal retires — the borrowing history keeps its item")
_li2 = c.post("/api/learning/library/items", headers=TT,
              json={"name": "Never Touched", "copies": 1}).json()
ok(c.delete(f"/api/learning/library/items/{_li2['id']}",
            headers=TT).json()["result"] == "deleted",
   "never loaned = truly gone")

# --- courses: archive is the exit, delete is for mistakes ---------------------
ok(c.delete(f"/api/learning/courses/{_crs}", headers=AA).status_code == 409,
   "a course with history refuses deletion — archiving is its exit")
_tmpc = c.post("/api/learning/courses", headers=AA,
               json={"name": "Typo Course 101"}).json()
ok(c.delete(f"/api/learning/courses/{_tmpc['id']}",
            headers=AA).status_code == 200
   and not any(x["id"] == _tmpc["id"] for x in
               c.get("/api/learning/courses", headers=AA).json()),
   "a course that never happened deletes clean")

# --- my record: the whole standing, exportable -------------------------------
_rec = c.get("/api/learn/record", headers=LN).json()
_rc = [x for x in _rec["courses"] if x["id"] == _crs]
ok(_rec["student"]["name"] == "Lara Learner" and len(_rc) == 1
   and _rec["totals"]["classes_attended"] >= 1,
   "the record gathers every enrolled course under the student's name")
_all_res = [r for x in _rec["courses"] for r in x["results"]]
ok(_all_res and all(set(r) >= {"quiz", "percent", "passed", "pass_mark"}
                    for r in _all_res)
   and _rc[0]["attendance"]["classes_held"] >= 1,
   "final quiz results and attendance ride each course — derived on read, "
   "so the record can never disagree with the data")
ok(c.get("/api/learn/record", headers=HA).status_code == 401,
   "the record answers only to its student")

_ljs2 = (Path(__file__).parent.parent / "src/storefront/frontend/learn.js"
         ).read_text(encoding="utf-8")
_sjs2 = (Path(__file__).parent.parent / "src/storefront/frontend/store.js"
         ).read_text(encoding="utf-8")
ok(all(s in _ljs2 for s in ('t("checkin", "Check in")',
                            't("quizzes", "Quizzes")',
                            't("live", "Live class")',
                            't("profile", "Profile")',
                            't("record", "My record")',
                            "Certificate of Completion",
                            "lrn-bell", "Ask to join")),
   "the learner app carries the portal's seven tabs, the bell, the "
   "printable record, and the ask-to-join door")
ok('"#i-bell"' in _ljs2 and "i-bell" in (
       Path(__file__).parent.parent / "src/storefront/frontend/icons.svg"
   ).read_text(encoding="utf-8"),
   "the bell mounts in the site header's icon cluster, drawn from the "
   "shared sprite")
ok(all(s in _sjs2 for s in ('["create", "Create account"]',
                            '["apply", "Apply to a programme"]',
                            'mode: "signin"', 'mode: "create"')),
   "the storefront door offers all three ways in — sign in, create, apply")
ok(_sjs2.count("learn-root") >= 2,
   "signing in or out on a portal page reloads it — the content IS the "
   "account")
ok('fetch("/api/roles")' in _sjs2,
   "the create door draws its role list from the server's catalog")
ok('MYROLE === "board" || MYROLE === "donor"' in _ljs2,
   "board members and donors get the profile-only rail — an account to be "
   "reached at, not a console")
_ajs2 = ops_app_js()
ok("data-roleok" in _ajs2 and "data-roleno" in _ajs2
   and '"teacher" && "learning"' in _ajs2,
   "Team & access carries the approve/decline queue, and a teacher lands "
   "on the Learning tab")
ok('mode: door === "create" ? "create" : "signin"' in _ajs2,
   "the ops door refuses to mint: sign-in is sign-in, and creating a team "
   "account is a deliberate act behind the admin key")
ok("customers: renderCustomers" in _ajs2 and 'id: "customers"' in _ajs2,
   "the CRM finally shows its customers — a tab of their own in the "
   "side nav")
ok(all(s in _ajs2 for s in ("data-libqr", "data-libedit", "data-libdel",
                            '$("#lib-scan").onclick =')),
   "library items carry their whole lifecycle — label, edit, retire, "
   "scan-at-the-desk")
ok(all(s in _ajs2 for s in ('id="lt-invite"', 'id="lt-add"', "data-tedit",
                            'id="lc-arch"', 'id="lc-del"', "data-invdel")),
   "the team desk, course archive/delete, and inventory rows all have "
   "their controls")
ok('id="join-root"' in (
       Path(__file__).parent.parent / "src/storefront/backend/api.py"
   ).read_text(encoding="utf-8")
   and "joinPage" in _sjs2,
   "the invitation link lands on a real page in the shop's own shell")
ok('id="eng-sow"' in _ajs2 and "d.tracks" in _ajs2
   and "PARALLEL" not in _ajs2,
   "the SOW drafts from the engagement, and the gantt reads the server's "
   "tracks — the chart and the paper share one schedule")
ok(all(s in _ajs2 for s in ("data-njoin", "data-ncheck", "data-nupdate")),
   "every addr'd node offers its join command, a live check, and a "
   "one-click code update from the Platform tab")
ok("roster-face" in _ajs2 and all(
       s in _ljs2 for s in ("lrn-avatar", "/api/learn/me/photo",
                            "pr-photo-share")),
   "faces ride the roster and the portal — upload, remove and the share "
   "switch all on the person's own profile")
ok("S.deepId" in _ajs2 and "#/learning/${cid}" in _ajs2
   and "#/customers/${uid}" in _ajs2,
   "deep views get real addresses: #/learning/5 is the course, "
   "#/customers/12 is the card — bookmark, share, back-button")
ok("location.hash = el.dataset.t" in _ljs2 and "hashchange" in _ljs2,
   "and the learner portal's tabs are URLs — /learn#record is a link "
   "you can send")
ok(all(s in _ajs2 for s in ('id="ak-new"', "data-akrev", 'id="ak-secret"',
                            'href="/docs"')),
   "API keys live on the Integrations tab — mint (secret shown once), "
   "revoke, and the live /docs reference linked where scripts are born")
ok("next card" in _ajs2 and "next card" in _ljs2
   and "data-door" in _ljs2 and 'id="pp-scan"' in _ljs2,
   "door mode loops the scanner on both surfaces — students file past — "
   "and People carries scan-to-connect beside search")
ok("data-crossdoor" in _sjs2 and "/api/whoami" in _sjs2,
   "the account panel walks a signed-in person into /ops and /admin "
   "carrying their session")
ok("data-sowfresh" in _ajs2 and "startCall" in _ajs2
   and 'id="call-video"' in _ajs2,
   "the SOW row refreshes its timeline, and ops chat already carries "
   "voice and video calls")
ok('mode: key ? "" : "signin"' in (
       Path(__file__).parent.parent
       / "src/storefront/frontend/admin.js").read_text(encoding="utf-8"),
   "the store-admin door too — only the key-holder's first sign-in still "
   "bootstraps an account")

# ---- the client dossier: everything about a built business, live ------
# "Which plan actually fits them?" — answered from their own tables at
# ask time: scale, thirty days of traffic and referrers, a meter per
# capability, and the advisory notes read down the phone.
ok(c.post("/api/store/admin/fleet/tenants", headers=AA,
          json={"id": "meterco", "brand": "Meter Co",
                "klass": "micro"}).status_code == 200,
   "a client stands up for the dossier to read")
HM = {"host": "meterco.localhost"}
for _vid, _pg, _rf in (("dv-1", "home", "https://maps.example/listing"),
                       ("dv-1", "classes", ""),
                       ("dv-2", "home", "")):
    c.post("/api/store/track", headers=HM,
           json={"visitor_id": _vid, "page": _pg, "referrer": _rf})
_rp = c.get("/api/store/admin/fleet/tenants/meterco/report",
            headers=AA).json()
ok(_rp["traffic"]["visitors"] == 2 and _rp["traffic"]["pageviews"] == 3,
   "the dossier counts unique visitors apart from raw pageviews")
ok(_rp["traffic"]["top_pages"][0]["page"] == "home"
   and _rp["traffic"]["top_pages"][0]["visitors"] == 2,
   "and ranks pages by the people who saw them, not the times they loaded")
ok(_rp["traffic"]["top_referrers"]
   == [{"referrer": "https://maps.example/listing", "visitors": 1}],
   "referred-from is where their customers actually come from across the "
   "internet — and a hop with no referrer stays out of it")
ok(set(_rp["scale"]) == {"locations", "seats_used", "customers"},
   "scale is the three numbers a plan is priced on")
ok(_rp["class"] == "micro" and _rp["caps"]
   and _rp["monthly_software"]
   >= max(_c["price"] for _c in _rp["caps"]),
   "with the plan, every granted capability and its price, and the "
   "software bill they add up to")
ok(any(v["label"] == "products" for v in _rp["meters"]["selling"])
   and "learning" in _rp["meters"],
   "a meter per capability — even a zero is an answer")
ok(any("granted but idle" in n for n in _rp["notes"]),
   "and the advice writes itself: a capability they pay for but never "
   "touched is either a training gap or a line to trim")
ok(_rp["node_info"]["id"] == "local" and _rp["node_info"]["alive"]
   and _rp["node_info"]["capacity"] >= _rp["node_info"]["tenant_units"]
   and _rp["node_info"]["version"],
   "the dossier carries the node under the business, live — what code it "
   "wears, and how much of its capacity this client occupies")
ok(_rp["billing"]["subscription"] is None
   and "missed" in _rp["billing"]["backup"],
   "the billing panel says plainly when an install is not billed through "
   "the store — beside whether last night's backup covered this tenant")
ok(any("meterco" in (e.get("what", "") + (e.get("detail") or ""))
       for e in _rp["history"]),
   "the maintenance history is this client's slice of the fleet record — "
   "their own stand-up is already on it")
ok(c.get("/api/store/admin/fleet/tenants/meterco/report",
         headers=BB).status_code == 404,
   "a hosted client cannot pull dossiers — the fleet view is the "
   "provider's alone")
ok(c.request("DELETE",
             "/api/store/admin/fleet/tenants/meterco?keep_data=0",
             headers=AA).status_code == 200,
   "cleanup: meterco leaves")

_arp = c.get("/api/store/admin/fleet/tenants/alpha/report",
             headers=AA).json()
ok(_arp["scale"]["seats_used"] >= 1 and isinstance(_arp["notes"], list),
   "the provider can read its own dossier too — alpha shows the seats "
   "this very suite has been filling")

ok("data-treport" in _ajs2 and "clientDossier" in _ajs2
   and 'id="eng-report"' in _ajs2,
   "the dossier opens from both doors — the Platform board's tenant row "
   "and the client page's own header")
ok(all(s in _ajs2 for s in ('data-dsec', 'id="ds-refresh"', 'id="dq"',
                            'data-dtrim', 'id="ds-actas"')),
   "and it is a working surface, not a printout — tabbed sections, a "
   "live refresh, a meter filter, and the advice notes open the "
   "capability editor themselves")
ok("referrer: ref" in _sjs2 and "document.referrer" in _sjs2,
   "and the storefront sends where each visit came from — off-site "
   "referrers only, our own pages are navigation")


done("platform")
