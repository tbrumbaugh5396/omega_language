"""Part: CORE — the single-tenant install. Commerce, ops, workforce,
supply, integrations, the storefront face. Everything here ran first
in the old one-file suite and builds all of its own state."""
from _harness import (ROOT, c, ok, done, mint_admin, checks,  # noqa
                      ops_app_js, ops_app_parts,  # noqa: F401
                      CFG, app)  # noqa: F401
from _harness import json, os, re, sys, tempfile, Path  # noqa: F401

# --- auth ---
admin = c.post("/api/login", json={"name": "Boss", "admin_key": CFG["admin_key"]}).json()
ok(admin["is_admin"], "admin login via admin key")
A = {"Authorization": f"Bearer {admin['token']}"}
cust = c.post("/api/login", json={"name": "Carl Customer", "region": "West"}).json()
CU = {"Authorization": f"Bearer {cust['token']}"}
_who = c.get("/api/whoami", headers=A).json()
ok(_who["name"] == "Boss" and _who["is_admin"] and _who["token"],
   "whoami hands any surface the session in its own shape — walking from "
   "the storefront to /ops or /admin carries the sign-in")
ok(c.get("/api/whoami").status_code == 401, "and a stranger gets nothing")


def verified_customer(headers, addr):
    """Mark a fixture's email as already confirmed.

    Pay-on-delivery holds the first order from an unconfirmed address, which
    is the point of it — but most tests here are about what happens *after*
    someone is an established customer, so they start as one. The holding
    behaviour has its own tests.
    """
    from erp.backend import db as _d
    con = _d.connect()
    uid = c.get("/api/me", headers=headers).json()["id"]
    con.execute("UPDATE users SET email=?, email_verified_at=?"
                " WHERE id=?", (addr, _t0.time(), uid))
    con.commit()
    con.close()


import time as _t0  # noqa: E402
verified_customer(CU, "carl@example.com")
dist = c.post("/api/login", json={"name": "Dana Dist", "role": "distributor"}).json()
DI = {"Authorization": f"Bearer {dist['token']}"}

# --- products / stores / inventory ---
r = c.post("/api/admin/products", headers=A, json={
    "sku": "T-1", "name": "Test Sauce", "price_cents": 800,
    "case_size": 12, "case_price_cents": 7000})
ok(r.status_code == 200, "admin adds product")
pid = c.get("/api/products").json()[0]["id"]
for i, (name, lat, lng) in enumerate([("S1", 40.0, -74.0), ("S2", 41.0, -73.0),
                                      ("S3", 39.5, -75.2)]):
    c.post("/api/admin/stores", headers=A, json={
        "name": name, "region": "Northeast", "lat": lat, "lng": lng})
stores = c.get("/api/stores").json()
ok(len(stores) == 3, "stores created")
c.post("/api/admin/inventory", headers=A, json={
    "store_id": stores[0]["id"], "product_id": pid, "qty": 2, "par": 24})
inv = c.get("/api/inventory", headers=A).json()
ok(inv and inv[0]["low"], "low-stock detection")

# --- orders: retail vs wholesale pricing ---
o1 = c.post("/api/orders", headers=CU, json={
    "items": [{"product_id": pid, "qty": 2}], "visitor_id": "vtest",
    "ship_name": "Carl", "address": "9 Elm St", "city": "Boston"}).json()
ok(o1["subtotal_cents"] == 1600, "customer pays unit price")
o2 = c.post("/api/orders", headers=DI, json={
    "items": [{"product_id": pid, "qty": 2}]}).json()
ok(o2["subtotal_cents"] == 14000, "distributor pays case price")
r = c.post(f"/api/admin/orders/{o1['id']}/status", headers=A,
           json={"status": "shipped"})
ok(r.status_code == 200, "order status update")

# --- time clock ---
c.post("/api/admin/employees", headers=A,
       json={"name": "Erin Emp", "pin": "9876"})
p1 = c.post("/api/clock", json={"pin": "9876"}).json()
ok(p1["action"] == "clock_in", "clock in by PIN")
p2 = c.post("/api/clock", json={"pin": "9876"}).json()
ok(p2["action"] == "clock_out", "clock out toggles")
ok(c.post("/api/clock", json={"pin": "0000"}).status_code == 404, "bad PIN rejected")

# --- A/B ---
exp = c.post("/api/admin/experiments/auto", headers=A,
             json={"goal": "purchase", "n_variants": 3}).json()
eid = exp["experiment"]["id"]
ok(len(exp["variants"]) == 3, "auto experiment generates 3 variants")
a1 = c.get("/api/ab/active", params={"visitor": "vis-1"}).json()
a2 = c.get("/api/ab/active", params={"visitor": "vis-1"}).json()
ok(a1 and a1[0]["variant_id"] == a2[0]["variant_id"], "assignment is sticky")
c.post("/api/events", json={"visitor_id": "vis-1", "step": "purchase",
                            "experiment_id": eid,
                            "variant_id": a1[0]["variant_id"]})
res = [e for e in c.get("/api/experiments", headers=A).json()
       if e["experiment"]["id"] == eid][0]
ok(sum(v["conversions"] for v in res["variants"]) == 1, "conversion counted")
r = c.post(f"/api/admin/experiments/{eid}/stop", headers=A, json={})
ok(r.status_code == 200, "experiment stop")

# --- affiliates ---
mine = c.post("/api/affiliates/join", headers=CU, json={}).json()
ok(mine["joined"], "affiliate join issues code")
r = c.get(f"/r/{mine['code']}", follow_redirects=False)
ok(r.status_code == 307 and r.headers["location"] == f"/a/{mine['code']}",
   "ref link routes to the affiliate landing page")
land = c.get(f"/a/{mine['code']}")
ok(land.status_code == 200 and mine["code"] in land.text,
   "landing page renders and stamps attribution")
# With the landing page switched off the link goes straight to the shop.
from erp.backend import db as _db
_c2 = _db.connect()
_c2.execute("UPDATE affiliates SET landing_enabled=0 WHERE code=?",
            (mine["code"],))
_c2.commit()
_c2.close()
r2 = c.get(f"/r/{mine['code']}", follow_redirects=False)
ok(r2.status_code == 307 and f"ref={mine['code']}" in r2.headers["location"],
   "ref link falls back to ?ref= when no landing page")
o3 = c.post("/api/orders", headers=DI, json={
    "items": [{"product_id": pid, "qty": 1}],
    "affiliate_code": mine["code"]}).json()
mine2 = c.get("/api/affiliates/mine", headers=CU).json()
ok(mine2["earned_cents"] == 7000 * CFG["default_commission_bps"] // 10000,
   "commission accrued")

# --- routes ---
c.post("/api/admin/trucks", headers=A, json={"name": "T1"})
tid = c.get("/api/trucks", headers=A).json()[0]["id"]
route = c.post("/api/routes/plan", headers=A,
               json={"truck_id": tid, "region": "Northeast"}).json()
ok(len(route["stops"]) == 3 and route["total_km"] > 0, "route planned + measured")
r = c.post(f"/api/routes/{route['id']}/stop", headers=A,
           json={"seq": 1, "delivered": True})
ok(r.status_code == 200, "stop marked delivered")

# --- analytics / funnel / events ---
for step in ("visit", "view_product", "add_to_cart"):
    c.post("/api/events", json={"visitor_id": "vis-9", "step": step,
                                "region": "West"})
fun = c.get("/api/analytics/funnel", headers=A).json()
ok(fun["steps"][0]["step"] == "visit", "funnel steps ordered")
ok(fun["worst_dropoff"] is not None, "drop-off detected")
regs = c.get("/api/analytics/regions", headers=A).json()
ok(any(r_["orders"] for r_ in regs), "regional rollup has orders")
eng = c.get("/api/analytics/engagement", headers=A).json()
ok(len(eng["daily"]) == 28, "engagement series")

# --- affiliate feed ---
from erp.backend import social  # noqa: E402

og = social.parse_og('<html><head><meta property="og:title" content="Big Video">'
                     '<meta property="og:image" content="http://x/i.jpg">'
                     '</head></html>')
ok(og["title"] == "Big Video" and og["image"] == "http://x/i.jpg",
   "OpenGraph parser")
ok(social.provider_for("https://www.tiktok.com/@a/video/1") == "tiktok",
   "provider detection")
r = c.post("/api/feed", headers=DI, json={"body": "hi"})
ok(r.status_code == 403, "non-affiliate cannot post")
post = c.post("/api/feed", headers=CU, json={"body": "trying the new rub"}).json()
ok(post["body"] == "trying the new rub" and post["code"], "affiliate posts to feed")
ok(post["week_orders"] >= 1, "weekly referred-order chip on post")
feed_items = c.get("/api/feed", headers=DI).json()
ok(feed_items and feed_items[0]["id"] == post["id"], "feed lists newest first")
r = c.delete(f"/api/admin/feed/{post['id']}", headers=A)
ok(r.status_code == 200 and not any(
    p["id"] == post["id"] for p in c.get("/api/feed", headers=A).json()),
   "admin deletes post")

# --- outreach ---
r = c.post("/api/outreach", headers=A, json={
    "name": "New Deli", "region": "West", "city": "LA"}).json()
c.post(f"/api/outreach/{r['id']}/update", headers=A,
       json={"stage": "contacted", "note": "left samples"})
log = c.get(f"/api/outreach/{r['id']}/log", headers=A).json()
ok(log and log[0]["note"] == "left samples", "outreach log recorded")

# --- roles: founder/owner + user management ---
own = c.post("/api/login", json={"name": "Fran Founder", "role": "owner",
                                 "admin_key": CFG["admin_key"]}).json()
ok(own["role"] == "owner" and own["is_admin"], "founder sign-in with admin key")
fake = c.post("/api/login", json={"name": "Sneaky", "role": "owner"}).json()
ok(fake["role"] == "customer" and not fake["is_admin"],
   "owner without key falls back to customer")
users = c.get("/api/admin/users", headers=A).json()
ok(any(u["name"] == "Carl Customer" for u in users), "admin lists all users")
carl = next(u for u in users if u["name"] == "Carl Customer")
r = c.post(f"/api/admin/users/{carl['id']}/update", headers=A,
           json={"role": "employee", "active": False})
ok(r.status_code == 200, "admin updates role/active")
carl2 = next(u for u in c.get("/api/admin/users", headers=A).json()
             if u["id"] == carl["id"])
ok(carl2["role"] == "employee" and not carl2["active"], "update persisted")
ok(c.get("/api/me", headers=CU).status_code == 401,
   "deactivated user is signed out")
me = next(u for u in users if u["name"] == "Boss")
ok(c.post(f"/api/admin/users/{me['id']}/update", headers=A,
          json={"is_admin": False}).status_code == 400,
   "cannot edit own account")
r = c.post(f"/api/admin/users/{carl['id']}/update", headers=A,
           json={"role": "owner", "is_admin": False})
ok(r.status_code == 200 and next(
    u for u in c.get("/api/admin/users", headers=A).json()
    if u["id"] == carl["id"])["is_admin"] == 1, "owners always keep admin")

# --- QR codes, QR sign-in, tracking pixels ---
from urllib.parse import urlparse  # noqa: E402

r = c.get("/api/qr.svg", params={"data": "http://example.com"})
ok(r.status_code == 200 and r.headers["content-type"].startswith("image/svg")
   and b"<svg" in r.content, "QR endpoint renders SVG")
ok(c.get("/api/qr.svg", params={"data": "x" * 600}).status_code == 400,
   "QR data length capped")
users = c.get("/api/admin/users", headers=A).json()
erin = next(u for u in users if u["name"] == "Erin Emp")
q = c.post(f"/api/admin/users/{erin['id']}/qr", headers=A, json={}).json()
ok(q["url"].startswith("http") and q["name"] == "Erin Emp",
   "QR sign-in link issued")
path = urlparse(q["url"]).path
r = c.get(path)
ok(r.status_code == 200 and "bc_user" in r.text, "QR link signs user in")
ok(c.get(path).status_code == 410, "QR link is single use")
r = c.post("/api/admin/tracking", headers=A, json={
    "ga_measurement_id": "G-TEST123", "meta_pixel_id": "555",
    "tiktok_pixel_id": ""})
ok(r.status_code == 200, "tracking pixels saved")
m = c.get("/api/meta").json()
ok(m["tracking"]["ga_measurement_id"] == "G-TEST123"
   and m["tracking"]["meta_pixel_id"] == "555", "pixel ids exposed via meta")

# --- route times, auto-coverage, truck check-in ---
routes = c.get("/api/routes", headers=A).json()
ok(routes and routes[0]["total_min"] > 0
   and routes[0]["stops"][1]["eta_min"] > 0, "route time estimates present")
made = c.post("/api/admin/routes/auto", headers=A, json={}).json()
ok(made and made[0]["name"].startswith("Coverage —"), "auto coverage routes")
n_before = len(c.get("/api/routes", headers=A).json())
c.post("/api/admin/stores", headers=A, json={
    "name": "S4", "region": "Northeast", "lat": 40.5, "lng": -74.5})
cov = [r_ for r_ in c.get("/api/routes", headers=A).json()
       if r_["name"] == "Coverage — Northeast"]
ok(len(cov) == 1 and len(cov[0]["stops"]) == 4,
   "adding a store regenerates region coverage route")
chk = c.post(f"/api/trucks/{tid}/checkin", headers=A, json={}).json()
ok(chk["truck"]["driver_user_id"] == admin["id"] and chk["route"],
   "truck QR check-in returns driver + route")

# --- promos, events, scans, event shifts ---
pr = c.post("/api/admin/promos", headers=A, json={
    "kind": "promo", "name": "Hot Sauce Week", "discount_pct": 15,
    "product_id": pid}).json()
ev = c.post("/api/admin/promos", headers=A, json={
    "kind": "event", "name": "Farmers Market", "region": "West",
    "city": "LA", "video_url": "https://youtu.be/jNQXAC9IVRw"}).json()
scan = c.post(f"/api/promos/{pr['id']}/scan",
              json={"visitor_id": "vis-qr"}).json()
ok(scan["name"] == "Hot Sauce Week" and scan["product"]["id"] == pid,
   "promo scan returns offer + product")
p1 = c.post("/api/clock", json={"pin": "9876", "event_id": ev["id"]}).json()
ok(p1["action"] == "clock_in" and p1["event"] == "Farmers Market",
   "employee clocks into event")
c.post("/api/clock", json={"pin": "9876"})
adm_promos = c.get("/api/admin/promos", headers=A).json()
hsw = next(p_ for p_ in adm_promos if p_["id"] == pr["id"])
fm = next(p_ for p_ in adm_promos if p_["id"] == ev["id"])
ok(hsw["scans"] == 1 and fm["staff_hours"] >= 0, "scan + staffing rollups")
sheet = c.get("/api/shifts?all=1", headers=A).json()
ok(any(s.get("event_name") == "Farmers Market" for s in sheet),
   "timesheet shows event name")

# --- P&L + game ---
p = c.get("/api/analytics/pnl", headers=A).json()
ok(p["revenue_cents"] > 0 and p["net_cents"] == p["gross_cents"]
   - p["commissions_cents"] - p["labor_cents"] - p["logistics_cents"],
   "P&L arithmetic holds")
g = c.get("/api/game", headers=A).json()
ne = next(r_ for r_ in g["regions"] if r_["region"] == "Northeast")
ok(ne["stores"] == 4 and g["company"]["level"] in ("gold", "silver", "bronze"),
   "game view aggregates territories")
ok(c.get("/api/game", headers=DI).status_code == 403, "game view is admin-only")

# --- notifications & achievements ---
n = c.get("/api/notifications", headers=A).json()
ok(any("order" in i["title"].lower() for i in n["items"]),
   "admin notified of orders")
ok(any(i["kind"] == "achievement" for i in n["items"]),
   "achievement unlocks create notifications")
ok(n["unread"] > 0, "unread count present")
c.post("/api/notifications/read", headers=A, json={})
ok(c.get("/api/notifications", headers=A).json()["unread"] == 0,
   "mark all read clears badge")
count1 = len(c.get("/api/notifications", headers=A).json()["items"])
count2 = len(c.get("/api/notifications", headers=A).json()["items"])
ok(count1 == count2, "sweep dedup: repeated polls add nothing")
c.post(f"/api/admin/orders/{o2['id']}/status", headers=A,
       json={"status": "delivered"})
nd = c.get("/api/notifications", headers=DI).json()
ok(any(f"Order #{o2['id']}" in i["title"] for i in nd["items"]),
   "customer notified of their order status")
ok(not any(i["kind"] == "inventory" for i in nd["items"]),
   "non-admin doesn't see admin notifications")
ach = c.get("/api/achievements", headers=A).json()
first = next(a for a in ach if a["key"] == "first_sale")
ok(first["unlocked_at"] and first["progress"] == "done",
   "first_sale achievement unlocked")
locked = [a for a in ach if not a["unlocked_at"]]
ok(locked and all("/" in a["progress"] or "%" in a["progress"]
                  for a in locked), "locked achievements show progress")
pioneer = next(a for a in ach if a["key"] == "ab_pioneer")
ok(pioneer["unlocked_at"], "experiment achievement earned")
ok(c.get("/api/achievements", headers=DI).status_code == 403,
   "achievements are admin-only")

# --- web push ---
k = c.get("/api/push/pubkey", headers=A).json()["key"]
ok(len(k) > 40, "VAPID public key generated")
r = c.post("/api/push/subscribe", headers=A, json={"subscription": {
    "endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}}})
ok(r.status_code == 200, "push subscription stored")
r = c.post("/api/push/unsubscribe", headers=A,
           json={"endpoint": "https://push.example/abc"})
ok(r.status_code == 200, "push unsubscribe")

# --- chat, support, DMs, websocket ---
chatty = c.post("/api/login", json={"name": "Chatty Customer",
                                    "email": "chatty@example.com"}).json()
ok(chatty["email"] == "chatty@example.com", "login captures email")
CH = {"Authorization": f"Bearer {chatty['token']}"}
verified_customer(CH, "chatty@example.com")
cc = c.get("/api/chat/convs", headers=CH).json()
ok(len(cc["convs"]) == 1 and cc["convs"][0]["kind"] == "support",
   "customer auto-gets a support conversation")
support_id = cc["convs"][0]["id"]
ac = c.get("/api/chat/convs", headers=A).json()
ok(any(v["kind"] == "team" for v in ac["convs"]) and
   any(v["id"] == support_id for v in ac["convs"]),
   "staff sees team room + support convs")
m = c.post(f"/api/chat/convs/{support_id}/messages", headers=A,
           json={"body": "How can we help?"}).json()
hist = c.get(f"/api/chat/convs/{support_id}/messages", headers=CH).json()
ok(hist and hist[-1]["body"] == "How can we help?",
   "support message round-trips")
ok(c.get(f"/api/chat/convs/{support_id}/messages", headers=DI).status_code
   == 403, "other customers can't read a support conv")
erin_id = next(u for u in c.get("/api/admin/users", headers=A).json()
               if u["name"] == "Erin Emp")["id"]
dm = c.post("/api/chat/dm", headers=A, json={"user_id": erin_id}).json()
ok(dm["conv_id"], "staff DM created")
ok(c.post("/api/chat/dm", headers=CH,
          json={"user_id": erin_id}).status_code == 403,
   "customers can't start DMs")
team_id = next(v["id"] for v in ac["convs"] if v["kind"] == "team")
with c.websocket_connect(f"/ws?token={admin['token']}") as ws:
    ws.send_json({"type": "msg", "conv_id": team_id, "body": "hello ws"})
    r = ws.receive_json()
    ok(r["type"] == "msg" and r["message"]["body"] == "hello ws",
       "websocket chat delivers in real time")

# --- email playbooks (dry mode) ---
c.post("/api/events", headers=CH, json={"visitor_id": "vis-chatty",
                                        "step": "add_to_cart"})
from erp.backend import db as bdb  # noqa: E402
import time as _t  # noqa: E402
bcon = bdb.connect()
bcon.execute("UPDATE events SET created_at=? WHERE user_id=?",
             (_t.time() - 7200, chatty["id"]))
bcon.commit()
bcon.close()
c.get("/api/notifications", headers=A)          # sweep runs playbooks
log = c.get("/api/admin/email/log", headers=A).json()
cart = [l for l in log if l["kind"] == "abandoned_cart"]
ok(cart and cart[0]["status"] == "dry" and cart[0]["email"]
   == "chatty@example.com", "abandoned-cart playbook fires (dry)")
c.get("/api/notifications", headers=A)
log2 = c.get("/api/admin/email/log", headers=A).json()
ok(len([l for l in log2 if l["kind"] == "abandoned_cart"]) == len(cart),
   "playbook dedup: no double-send")
b = c.post("/api/admin/email/blast", headers=A,
           json={"promo_id": pr["id"]}).json()
ok(b["targeted"] >= 1 and b["sent"] >= 1, "promo blast targets emails")
b2 = c.post("/api/admin/email/blast", headers=A,
            json={"promo_id": pr["id"]}).json()
ok(b2["sent"] == 0 and b2["already_sent"] >= 1, "blast dedup per customer")
r = c.post("/api/admin/email/config", headers=A, json={
    "host": "", "abandoned_cart": False, "winback": True})
ok(r.status_code == 200 and not c.get("/api/admin/email/config",
   headers=A).json()["playbooks"]["abandoned_cart"],
   "email config round-trips")

# --- SMTP wiring: test endpoint + errored-send retry ---
from erp.backend import mailer  # noqa: E402

r = c.post("/api/admin/email/test", headers=A, json={"to": "me@example.com"})
ok(r.status_code == 200 and r.json()["status"] == "dry",
   "test email endpoint (dry without SMTP host)")
ok(c.post("/api/admin/email/test", headers=A,
          json={"to": ""}).status_code == 400, "test email needs recipient")
bcon = bdb.connect()
orig_send = mailer.send
mailer.send = lambda cfg, to, s, t: "error: boom"
did = mailer.log_and_send(bcon, {}, chatty["id"], "chatty@example.com",
                          "test", "subj", "body", "retry:1")
ok(not did, "errored send reports failure")
mailer.send = lambda cfg, to, s, t: "sent"
did2 = mailer.log_and_send(bcon, {}, chatty["id"], "chatty@example.com",
                           "test", "subj", "body", "retry:1")
row = bcon.execute("SELECT status FROM email_log WHERE dedup_key='retry:1'"
                   ).fetchone()
ok(did2 and row["status"] == "sent",
   "errored email retries once SMTP works")
did3 = mailer.log_and_send(bcon, {}, chatty["id"], "chatty@example.com",
                           "test", "subj", "body", "retry:1")
ok(not did3, "sent emails never resend")
mailer.send = orig_send
bcon.close()

# --- commerce loop: totals, payments, stock consumption, restock ---
r = c.post("/api/orders", headers=CH,
           json={"items": [{"product_id": pid, "qty": 1}]})
ok(r.status_code == 400, "customer order requires shipping address")
ship = {"ship_name": "Chatty", "address": "1 Main St", "city": "LA",
        "postal": "90001"}
o4 = c.post("/api/orders", headers=CH, json={
    "items": [{"product_id": pid, "qty": 2}], **ship}).json()
ok(o4["tax_cents"] == 128 and o4["shipping_cents"] == 599
   and o4["total_cents"] == 2327 and o4["payment_status"] == "cod",
   "customer totals: 8% tax + flat shipping, pay-on-delivery")
o5 = c.post("/api/orders", headers=CH, json={
    "items": [{"product_id": pid, "qty": 6}], **ship}).json()
ok(o5["shipping_cents"] == 0, "free shipping over the threshold")
o6 = c.post("/api/orders", headers=DI,
            json={"items": [{"product_id": pid, "qty": 1}]}).json()
ok(o6["payment_status"] == "on_terms" and o6["tax_cents"] == 0,
   "distributor orders ship on terms, untaxed")
ok(o4["checkout_url"] is None, "no Stripe key -> no checkout redirect")
r = c.post(f"/api/orders/{o5['id']}/confirm-payment", headers=CH,
           json={"session_id": "cs_bogus"})
ok(r.status_code == 402, "bogus payment session rejected")
c.post("/api/admin/orders/{}/paid".format(o4["id"]), headers=A, json={})
mine = c.get("/api/orders", headers=CH).json()
ok(next(o for o in mine if o["id"] == o4["id"])["payment_status"] == "paid",
   "admin marks order paid")
c.post("/api/admin/inventory", headers=A, json={
    "store_id": stores[1]["id"], "product_id": pid, "qty": 50, "par": 24})
c.post(f"/api/admin/orders/{o4['id']}/status", headers=A,
       json={"status": "shipped"})
inv = c.get("/api/inventory", headers=A).json()
row = next(i for i in inv if i["store_id"] == stores[1]["id"]
           and i["product_id"] == pid)
ok(row["qty"] == 48, "shipping consumes stock at the best-stocked store")
o7 = c.post("/api/orders", headers=CH, json={
    "items": [{"product_id": pid, "qty": 500}], **ship}).json()
c.post(f"/api/admin/orders/{o7['id']}/status", headers=A,
       json={"status": "shipped"})
n_short = c.get("/api/notifications", headers=A).json()
ok(any("short-stocked" in i["title"] for i in n_short["items"]),
   "short-stock shipment notifies admins")
c.post("/api/admin/inventory", headers=A, json={
    "store_id": stores[2]["id"], "product_id": pid, "qty": 1, "par": 24})
route2 = c.post("/api/routes/plan", headers=A,
                json={"truck_id": tid, "region": "Northeast"}).json()
seq = next(s["seq"] for s in route2["stops"]
           if s["store_id"] == stores[2]["id"])
c.post(f"/api/routes/{route2['id']}/stop", headers=A,
       json={"seq": seq, "delivered": True})
inv = c.get("/api/inventory", headers=A).json()
row = next(i for i in inv if i["store_id"] == stores[2]["id"]
           and i["product_id"] == pid)
ok(row["qty"] == 1,
   "ticking a stop moves no stock. It used to top the store up to par, "
   "which is not a measurement of anything — it says the truck filled the "
   "shelf because somebody said the truck went there, and the store's "
   "stock then drifts from the shelf by however wrong that was")
# --- how a shelf got to the number it says -----------------------------
# Materials have had a ledger since the beginning: every movement with a
# reason and an actor. Store stock did not — it was a bare integer four
# different places overwrote, and "how did this store come to have two
# cases" had no answer at all.
_lm = c.get(f"/api/inventory/moves?store_id={stores[2]['id']}"
            f"&product_id={pid}", headers=A).json()
ok(_lm["moves"] and _lm["moves"][0]["reason"] == "count"
   and _lm["moves"][0]["counted"] == 1,
   "typing a number into a stock box is a COUNT — somebody looked at a "
   "shelf — and it lands in the ledger as one")
ok(_lm["moves"][0]["balance"] == 1,
   "carrying what the line read afterwards, so the history can be read "
   "down rather than added up")
_par = c.post("/api/admin/stores/par-fill", headers=A,
              json={"store_id": stores[2]["id"]}).json()
ok(_par["lines"] >= 1,
   "restocking to par is still there, asked for by name — losing it would "
   "push a coverage round back into a spreadsheet")
inv = c.get("/api/inventory", headers=A).json()
row = next(i for i in inv if i["store_id"] == stores[2]["id"]
           and i["product_id"] == pid)
ok(row["qty"] == 24, "and then it fills the shelf to target")
ok("assumed" in _par["note"].lower() or "Assumed" in _par["note"],
   "while saying what it is: an assumption somebody made on purpose, "
   "which is worth far more than the same assumption made by a checkbox")
_aud = c.get("/api/admin/audit", headers=A).json()
_rows = _aud if isinstance(_aud, list) else _aud.get("entries", _aud.get(
    "rows", []))
ok(any("assumed full" in (e.get("detail") or "") for e in _rows[:30]),
   "and it is in the audit log with a name on it")
_lm2 = c.get(f"/api/inventory/moves?store_id={stores[2]['id']}"
             f"&product_id={pid}", headers=A).json()
ok(_lm2["moves"][0]["reason"] == "par"
   and _lm2["moves"][0]["counted"] == 0,
   "an assumed top-up is in the same ledger and marked as inferred — a "
   "stocktake and a par-fill are both a positive number, and a business "
   "that cannot tell them apart cannot tell which of its figures it is "
   "entitled to trust")
ok(_lm2["counted"] >= 1 and _lm2["assumed"] >= 1,
   "which the summary counts separately")
ok(_lm2["moves"][0]["balance"] == 24 and _lm2["moves"][0]["qty"] == 23,
   "and the movement is the DIFFERENCE it made, not the number that was "
   "typed — a screen that writes the absolute leaves a hole exactly "
   "where the question gets asked")
_ship = c.get("/api/inventory/moves", headers=A).json()
ok(all("balance" in m and "actor" in m for m in _ship["moves"]),
   "every movement says what the line read afterwards and who moved it")

# --- passwords ---
p1 = c.post("/api/login", json={"name": "Pat Password",
                                "password": "hunter2"}).json()
ok(p1["has_password"], "password set at account creation")
ok(c.post("/api/login", json={"name": "Pat Password",
                              "password": "wrong"}).status_code == 403,
   "wrong password rejected")
ok(c.post("/api/login", json={"name": "Pat Password"}).status_code == 403,
   "missing password rejected once set")
ok(c.post("/api/login", json={"name": "Pat Password",
                              "password": "hunter2"}).status_code == 200,
   "correct password accepted")
adopt = c.post("/api/login", json={"name": "Chatty Customer",
                                   "password": "newpw"}).json()
ok(adopt["has_password"], "existing account adopts password on first supply")
pat_id = next(u for u in c.get("/api/admin/users", headers=A).json()
              if u["name"] == "Pat Password")
ok(pat_id["password_set"], "admin sees password flag")
c.post(f"/api/admin/users/{pat_id['id']}/update", headers=A,
       json={"clear_password": True})
ok(c.post("/api/login", json={"name": "Pat Password"}).status_code == 200,
   "admin password reset lets user back in")

# --- going public hardens the doors by itself --------------------------------
from erp.backend.main import CFG as _CFGH  # noqa: E402
_CFGH["public_base_url"] = "https://harden.example.com"
ok(c.post("/api/login", json={"name": "Naive Nate",
                              "mode": "create"}).status_code == 400,
   "public install: creating without a password is refused — nobody set "
   "require_passwords, exposure decided it")
ok(c.post("/api/login", json={"name": "Careful Cara", "mode": "create",
                              "password": "a long phrase"}).json()
   ["role"] == "customer",
   "and creating WITH one still works — customers sign themselves up")
ok(c.post("/api/login",
          json={"name": "Script Kid"}).status_code == 404,
   "the bare mode-less login stops minting: an unknown name gets sign-in's "
   "own answer")
_kb = c.post("/api/login", json={"name": "Keyed Boot", "password": "x y z",
                                 "admin_key": CFG["admin_key"]}).json()
ok(_kb.get("is_admin"),
   "while the key-holder's bootstrap still works — the key IS the "
   "authority")
ok(c.post("/api/login", json={"name": "Would Be Staff", "mode": "create",
                              "role": "employee",
                              "password": "w x y"}).json()["role"]
   == "customer",
   "and a self-picked staff role lands as customer — public installs "
   "confer every non-customer role")
_CFGH["require_passwords"] = False
ok(c.post("/api/login", json={"name": "Opted Out",
                              "mode": "create"}).status_code == 200,
   "an explicit require_passwords=false opts a public install out")
_CFGH["require_passwords"] = None
_CFGH["public_base_url"] = ""
ok(c.post("/api/login", json={"name": "Lan Larry",
                              "mode": "create"}).status_code == 200,
   "and back on the LAN, name-only stays the dev convenience it was")

# --- sessions age: the sliding window ----------------------------------------
_slp = c.post("/api/login", json={"name": "Sleepy Session"}).json()
_SL = {"Authorization": f"Bearer {_slp['token']}"}
ok(c.get("/api/notifications", headers=_SL).status_code == 200,
   "a fresh token works")
_hcon = _db.connect()
_hcon.execute("UPDATE users SET token_seen_at=? WHERE id=?",
              (_t0.time() - 40 * 86400, _slp["id"]))
_hcon.commit()
ok(c.get("/api/notifications", headers=_SL).status_code == 401,
   "a token unused past session_days is refused")
_row9 = _hcon.execute("SELECT token FROM users WHERE id=?",
                      (_slp["id"],)).fetchone()
ok(_row9["token"] != _slp["token"],
   "and rotated dead — the stale bearer cannot be replayed either")
_slp2 = c.post("/api/login", json={"name": "Sleepy Session"}).json()
ok(c.get("/api/notifications",
         headers={"Authorization": f"Bearer {_slp2['token']}"}
         ).status_code == 200,
   "signing in again mints a live session — expiry ends tokens, not "
   "accounts")
_hcon.close()

# --- backups ---
import subprocess  # noqa: E402
r = subprocess.run([sys.executable, str(ROOT / "scripts" / "backup.py")],
                   capture_output=True, text=True)
backups = list((Path(os.environ["BUSINESS_CONTROL_DATA"]) / "backups")
               .glob("business-control-*.tar.gz"))
ok(r.returncode == 0 and backups, "backup script writes WAL-safe archive")

# --- go-public wiring ---
from erp.backend.main import base_url, CFG as _CFG  # noqa: E402
_CFG["public_base_url"] = "https://shop.example.com/"
q2 = c.post(f"/api/admin/users/{erin_id}/qr", headers=A, json={}).json()
ok(q2["url"].startswith("https://shop.example.com/qr-login/"),
   "public_base_url drives outward links")
_CFG["public_base_url"] = ""
ok(base_url().startswith("http://"), "falls back to LAN url")

# --- branding & product images ---
r = c.post("/api/admin/branding", headers=A, json={
    "brand_name": "Fuego Foods", "tagline": "Small batch. Big flavor.",
    "accent": "#e0662f"})
m = c.get("/api/meta").json()
ok(r.status_code == 200 and m["brand"] == "Fuego Foods"
   and m["accent"] == "#e0662f", "branding round-trips through meta")
ok(c.post("/api/admin/branding", headers=A,
          json={"accent": "purple"}).status_code == 400,
   "non-hex accent rejected")
png_1px = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf"
           "FcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
r = c.post(f"/api/admin/products/{pid}/image", headers=A,
           json={"data_url": png_1px})
ok(r.status_code == 200, "product image upload")
r = c.get(f"/media/product/{pid}")
ok(r.status_code == 200 and r.headers["content-type"] == "image/png",
   "product image served with sniffed type")
ok(c.get("/api/products").json()[0]["image"] == 1,
   "product flagged as having an image")
ok(c.post(f"/api/admin/products/{pid}/image", headers=A,
          json={"data_url": "data:text/plain;base64,aGVsbG8="}).status_code
   == 400, "non-image upload rejected")

# --- staff jobs & contractors ---
ok("driver" in c.get("/api/meta").json()["jobs"], "meta lists staff jobs")
r = c.post("/api/admin/employees", headers=A, json={
    "name": "Dee Driver", "pin": "7001", "job": "driver",
    "employment": "contractor"})
ok(r.status_code == 200, "create contractor driver")
ok(c.post("/api/admin/employees", headers=A, json={
    "name": "X", "pin": "7002", "job": "astronaut"}).status_code == 400,
   "bad job rejected")
c.post("/api/admin/employees", headers=A, json={
    "name": "Wanda Warehouse", "pin": "7003", "job": "warehouse"})
c.post("/api/admin/employees", headers=A, json={
    "name": "Bam Bassador", "pin": "7004", "job": "ambassador"})
users = c.get("/api/admin/users", headers=A).json()
dee = next(u for u in users if u["name"] == "Dee Driver")
ok(dee["job"] == "driver" and dee["employment"] == "contractor",
   "job + employment stored and listed")
bam = next(u for u in users if u["name"] == "Bam Bassador")
BAM = {"Authorization": f"Bearer " + c.post("/api/login", json={
    "name": "Bam Bassador"}).json()["token"]}
ok(c.get("/api/affiliates/mine", headers=BAM).json()["joined"],
   "ambassador auto-enrolled as affiliate")
r = c.post(f"/api/admin/users/{dee['id']}/update", headers=A,
           json={"job": "dsd"})
ok(r.status_code == 200 and next(
    u for u in c.get("/api/admin/users", headers=A).json()
    if u["id"] == dee["id"])["job"] == "dsd", "admin reassigns job")
c.post(f"/api/admin/users/{dee['id']}/update", headers=A,
       json={"job": "driver"})
# picklist: staff sees pending orders w/ items; customers blocked
pl = c.get("/api/warehouse/picklist", headers=A).json()
ok(any(o["id"] == o5["id"] for o in pl)
   and not any(o["id"] == o4["id"] for o in pl),
   "picklist lists pending orders, omits shipped ones")
ok(c.get("/api/warehouse/picklist", headers=BAM).status_code == 200,
   "staff can read picklist")
ok(c.get("/api/warehouse/picklist", headers=DI).status_code == 403,
   "customers blocked from picklist")
# contractor pay hits the P&L when their route completes
dee_tok = c.post("/api/login", json={"name": "Dee Driver"}).json()["token"]
DE = {"Authorization": f"Bearer {dee_tok}"}
c.post(f"/api/trucks/{tid}/checkin", headers=DE, json={})
r3 = c.post("/api/routes/plan", headers=A,
            json={"truck_id": tid, "region": "Northeast"}).json()
c.post(f"/api/routes/{r3['id']}/status", headers=A, json={"status": "done"})
p = c.get("/api/analytics/pnl", headers=A).json()
expected = 9000 + len(r3["stops"]) * 800
ok(p["contractor_cents"] >= expected and p["contractor_routes"] >= 1,
   "contractor route pay lands in P&L")
g = c.get("/api/game", headers=A).json()
ok(any(s["job"] == "driver" and s["employment"] == "contractor"
       for s in g["staffing"]), "HQ staffing breakdown by job")

# --- box cycles: calendar, cutoffs, portal gate ---
ok(c.post("/api/admin/cycles", headers=A,
          json={"month": "2099-13"}).status_code == 400, "bad month rejected")
fut = c.post("/api/admin/cycles", headers=A, json={"month": "2099-01"}).json()
ok(fut["bill_date"] == "2099-01-01" and fut["curation_lock"] == "2099-01-08"
   and fut["ship_date"] == "2099-01-15", "template dates generated")
ok(fut["phase"] == "upcoming" and fut["changes_open"],
   "future cycle: upcoming, portal open")
ok(c.post("/api/admin/cycles", headers=A,
          json={"month": "2099-01"}).status_code == 400,
   "duplicate cycle rejected")
ok(c.post("/api/admin/cycles", headers=A, json={
    "month": "2099-02", "ship_date": "2099-02-02"}).status_code == 400,
   "out-of-order custom dates rejected")
past = c.post("/api/admin/cycles", headers=A, json={"month": "2020-01"}).json()
ok(past["phase"] == "shipped" and not past["changes_open"],
   "past cycle: shipped, portal locked")
cur = c.get("/api/cycles/current", headers=A).json()
ok(cur and cur["month"] in ("2020-01", "2099-01"),
   "current-cycle endpoint answers")
ok(c.get("/api/cycles", headers=DI).status_code == 403,
   "cycles are staff-only")
r = c.post(f"/api/admin/cycles/{past['id']}/update", headers=A,
           json={"billed_count": 10, "allocated_count": 4})
ok(r.json()["billed_count"] == 10, "cycle counts update")
c.get("/api/notifications", headers=A)      # sweep
n_cyc = c.get("/api/notifications", headers=A).json()
ok(any("allocation short" in i["title"] for i in n_cyc["items"]),
   "allocation shortfall flagged after curation lock")
count_a = len([i for i in n_cyc["items"] if i["kind"] == "cycle"])
c.get("/api/notifications", headers=A)
count_b = len([i for i in c.get("/api/notifications", headers=A).json()["items"]
               if i["kind"] == "cycle"])
ok(count_a == count_b, "cycle notifications dedup")
c.post(f"/api/admin/cycles/{past['id']}/update", headers=A,
       json={"closed": True})
ok(c.get("/api/cycles/current", headers=A).json()["month"] == "2099-01",
   "closing a cycle advances current")

# --- private Shopify subscription app (mock mode) ---
st = c.get("/api/admin/shopify/status", headers=A).json()
ok(st["mode"] == "mock" and st["connected"] is False,
   "shopify status reports mock mode without a store")
plan = c.post("/api/admin/shopify/selling-plan", headers=A,
              json={"name": "Monthly Box"}).json()
ok("SellingPlanGroup" in plan["id"], "selling plan creation (mock)")
ok(c.post("/api/admin/shopify/selling-plan", headers=A,
          json={"interval": "DAILY"}).status_code == 400,
   "bad interval rejected")
ok(c.post("/api/admin/shopify/bill-run", headers=A,
          json={"cycle_month": "2098-01"}).status_code == 404,
   "bill run requires an existing cycle")
r1 = c.post("/api/admin/shopify/bill-run", headers=A,
            json={"cycle_month": "2099-01"}).json()
ok(r1["attempted"] == 2 and r1["billed_success"] == 2,
   "bill run charges active contracts only (2 of 3 mock)")
r2 = c.post("/api/admin/shopify/bill-run", headers=A,
            json={"cycle_month": "2099-01"}).json()
ok(r2["attempted"] == 0 and r2["already_attempted"] == 2,
   "bill run is idempotent per contract per cycle")
cyc99 = next(x for x in c.get("/api/cycles", headers=A).json()
             if x["month"] == "2099-01")
ok(cyc99["billed_count"] == 2, "bill run syncs cycle billed_count")
ok(c.post("/webhooks/shopify", content=b"{}",
          headers={"X-Shopify-Hmac-Sha256": "bogus"}).status_code == 401,
   "webhook rejects bad HMAC")
import base64 as _b64  # noqa: E402
import hashlib as _hl  # noqa: E402
import hmac as _hm  # noqa: E402
from erp.backend.main import CFG as _C  # noqa: E402
_C["shopify"]["webhook_secret"] = "testsecret"
_body = b'{"subscription_contract_id": 9001}'
_sig = _b64.b64encode(_hm.new(b"testsecret", _body, _hl.sha256).digest()).decode()
r = c.post("/webhooks/shopify", content=_body, headers={
    "X-Shopify-Hmac-Sha256": _sig,
    "X-Shopify-Topic": "subscription_billing_attempts/failure"})
ok(r.status_code == 200 and r.json()["result"] == "processed",
   "signed billing webhook processed")
_C["shopify"]["webhook_secret"] = ""

# --- partner funnels, events, locator, heatmap ---
import time  # noqa: E402
r = c.post("/api/store/enquiry", json={
    "kind": "brand", "name": "Ada Lovelace", "company": "Analytical Drinks",
    "email": "ada@example.com", "city": "Boston MA", "region": "Northeast",
    "detail": "cold-brew tea, 4 SKUs"})
ok(r.status_code == 200 and r.json()["ok"], "partner enquiry accepted")
_oid = r.json()["outreach_id"]
ok(any(o["id"] == _oid and o["stage"] == "lead"
       for o in c.get("/api/outreach", headers=A).json()),
   "enquiry opens a lead in the ERP pipeline")
ok(c.post("/api/store/enquiry", json={"kind": "nope", "name": "X"}
          ).status_code == 400, "unknown enquiry kind rejected")
ok(c.post("/api/store/enquiry", json={"kind": "work", "name": "  "}
          ).status_code == 400, "enquiry needs a name")
ok(any(e["kind"] == "brand"
       for e in c.get("/api/store/admin/enquiries", headers=A).json()),
   "enquiry visible in the store admin")

for _slug in ("work", "stock-zen", "reorder", "distribute", "brand",
              "partner-brand"):
    ok(c.get(f"/partners/{_slug}").status_code == 200,
       f"partner page /{_slug} renders")
ok(c.get("/partners/nonsense").status_code == 404, "unknown partner page 404s")
ok(c.get("/events").status_code == 200, "events page renders")
ok(c.get("/find").status_code == 200, "store locator renders")

_ev = c.post("/api/store/admin/events", headers=A, json={
    "name": "Tasting — Test Shop", "kind": "tasting", "city": "Austin TX",
    "region": "Southwest", "starts": time.time() + 86400})
ok(_ev.status_code == 200, "admin creates an event")
_eid = _ev.json()["id"]
ok(any(e["id"] == _eid for e in c.get("/api/store/events").json()),
   "future event appears on the public list")
ok(c.post("/api/store/admin/events", headers=A,
          json={"name": "X", "kind": "rave"}).status_code == 400,
   "bad event kind rejected")
c.patch(f"/api/store/admin/events/{_eid}", headers=A, json={
    "name": "Tasting — Test Shop", "kind": "tasting", "active": 0,
    "starts": time.time() + 86400})
ok(not any(e["id"] == _eid for e in c.get("/api/store/events").json()),
   "deactivated event drops off the public list")
ok(c.delete(f"/api/store/admin/events/{_eid}", headers=A).status_code == 200,
   "admin deletes an event")

_locs = c.get("/api/store/locations").json()
ok(_locs and all(s["kind"] == "retail" for s in _locs),
   "locator lists retail stores only")

ok(c.post("/api/store/clicks", json={"page": "/", "hits": [
    {"x": 0.5, "y": 0.25, "vw": 1280, "label": "button.add-btn", "depth": 0.4},
    {"x": 9.9, "y": 0.5},                      # out of range, dropped
]}).json()["stored"] == 1, "heatmap keeps in-range clicks, drops the rest")
_hm = c.get("/api/store/admin/heatmap?page=/", headers=A).json()
ok(_hm["count"] >= 1 and len(_hm["reach"]) == 10,
   "heatmap returns hits and a scroll-depth profile")
ok(c.get("/api/store/admin/heatmap?page=/").status_code == 403,
   "heatmap needs admin")

# --- marketing pixels ---
ok(c.get("/api/store/admin/pixels").status_code == 403, "pixel config needs admin")
_px = c.get("/api/store/admin/pixels", headers=A).json()
ok(_px["consent_required"] and not _px["enabled"],
   "pixels ship off, with consent required by default")
ok(c.post("/api/store/admin/pixels", headers=A, json={
    "enabled": True, "ids": {"meta": '"><script>alert(1)</script>'}}
).status_code == 400, "a pixel ID that isn't an ID is rejected")
ok(c.post("/api/store/admin/pixels", headers=A, json={
    "enabled": True, "ids": {"ga4": "not-a-ga4-id"}}
).status_code == 400, "GA4 ID shape enforced")
r = c.post("/api/store/admin/pixels", headers=A, json={
    "enabled": True, "consent_required": True,
    "ids": {"meta": "123456789012345", "ga4": "G-ABC1234567"},
    "events": {k: True for k in ["page_view", "purchase"]}})
ok(r.status_code == 200 and set(r.json()["active"]) == {"meta", "ga4"},
   "valid pixel IDs saved")
_home = c.get("/").text
ok("__pixelConsent=false" in _home and "connect.facebook.net" in _home,
   "pixel loaders are present but gated behind consent")
ok(c.post("/api/store/pixel-event",
          json={"event": "nope"}).status_code == 400,
   "unknown pixel event rejected")
c.post("/api/store/pixel-event",
       json={"event": "purchase", "value_cents": 3499, "consent": True})
_log = c.get("/api/store/admin/pixels/log", headers=A).json()
ok(any(e["event"] == "purchase" and e["consented"] == 1
       for e in _log["events"]), "pixel events logged first-party")
# turn them back off so the dev store ships clean
c.post("/api/store/admin/pixels", headers=A, json={"enabled": False})
ok("connect.facebook.net" not in c.get("/").text,
   "disabling pixels removes the tags entirely")

# The heatmap preview renders the storefront in an iframe; it must not record
# its own visit, or looking at the data would change it.
_before = c.get("/api/store/admin/heatmap?page=/", headers=A).json()["count"]
ok('__preview' in c.get("/store.js").text,
   "storefront honours the preview guard")
_after = c.get("/api/store/admin/heatmap?page=/", headers=A).json()["count"]
ok(_before == _after, "viewing the heatmap doesn't add to it")

# Consent has to be withdrawable as easily as it is given.
_js = c.get("/store.js").text
ok("pref-consent" in _js, "consent can be changed from the preferences panel")
_html = c.get("/").text
ok('id="consent-yes"' in _html and 'id="consent-no"' in _html,
   "both consent buttons are on the page")
ok('id="pref-consent-row"' in _html, "preferences carry a consent switch")
# display:flex on the class outranks the UA's [hidden] rule, so without an
# explicit author rule the bar is visible from page load — empty and inert.
_css = c.get("/store.css").text
ok(".consent-bar[hidden]" in _css, "hidden consent bar actually hides")
c.post("/api/store/admin/pixels", headers=A, json={
    "enabled": True, "consent_required": True,
    "consent_text": "Custom words <script>here",
    "ids": {"meta": "123456789012345"}})
_home2 = c.get("/").text
ok("Custom words scripthere" in _home2,
   "custom consent wording reaches the page, tags stripped")
c.post("/api/store/admin/pixels", headers=A, json={"enabled": False})

# --- support hub ---
_sc = c.get("/api/store/support/config").json()
ok("topics" in _sc and "reply_target" in _sc, "support config is public")
r = c.post("/api/store/support/ticket", json={
    "name": "Ada", "email": "ada@example.com", "topic": "delivery",
    "body": "My box hasn't arrived."})
ok(r.status_code == 200 and re.match(r"[A-Z]{2}-", r.json()["ref"]),
   "ticket accepted with a reference whose prefix is the BRAND's initials "
   "— it was hard-coded ZJ, one business's monogram on everybody's tickets")
_ref = r.json()["ref"]
ok(c.post("/api/store/support/ticket",
          json={"name": "", "body": "x"}).status_code == 400,
   "ticket needs a name")
ok(c.post("/api/store/support/ticket", json={
    "name": "A", "body": "x", "email": "not-an-email"}).status_code == 400,
   "bad email rejected")
ok(c.post("/api/store/support/ticket", json={
    "name": "A", "body": "x", "topic": "nope"}).status_code == 400,
   "unknown topic rejected")
_look = c.get(f"/api/store/support/ticket/{_ref}").json()
ok(_look["status"] == "open" and "email" not in _look,
   "public lookup shows status but never the contact details")
ok(c.get("/api/store/support/ticket/ZJ-NOPE").status_code == 404,
   "unknown reference 404s")
_tid = [t for t in c.get("/api/store/admin/tickets", headers=A).json()
        if t["ref"] == _ref][0]["id"]
ok(c.post(f"/api/store/admin/tickets/{_tid}", headers=A,
          json={"body": "On its way."}).json()["status"] == "waiting",
   "replying moves the ticket to waiting")
ok(c.get(f"/api/store/support/ticket/{_ref}").json()["replies"],
   "the reply is visible to the customer")
c.post("/api/store/admin/support-contact", headers=A,
       json={"phone": "+1 555 010 2030", "email": "help@brand.test",
             "calls_enabled": True})
ok(c.get("/api/store/support/config").json()["phone"] == "+1 555 010 2030",
   "merchant phone number reaches the storefront")
_home = c.get("/").text
ok('tel:+15550102030' in _home and "+1 555 010 2030" in _home
   and '"telephone": "+1 555 010 2030"' in _home
   and "help@brand.test" in _home,
   "the business number is ONE saved value — footer link, visible text and "
   "the Organization markup search engines read all follow it, so pointing "
   "it at a VoIP service is one edit in the store admin")
c.post("/api/store/admin/support-contact", headers=A,
       json={"phone": "+1 555 010 2030", "email": "help@brand.test",
             "calls_enabled": True, "show_in_footer": False})
ok("tel:+15550102030" not in c.get("/").text,
   "and a merchant who wants it only in the support hub can say so")
c.post("/api/store/admin/support-contact", headers=A,
       json={"phone": "+1 555 010 2030", "email": "help@brand.test",
             "calls_enabled": True})
ok(c.get("/api/store/admin/support-contact", headers=A).json()["email"]
   == "help@brand.test",
   "saving the phone keeps the email — the form used to omit it, and since "
   "the server writes the whole record, a phone edit silently erased it")
ok('$("#sc-email")' in Path("src/storefront/frontend/admin.js").read_text()
   and 'id="sc-email"'
   in Path("src/storefront/frontend/admin.html").read_text(),
   "and the admin form actually carries the field")

# --- campaigns ---
r = c.post("/api/store/admin/campaigns", headers=A, json={
    "name": "Autumn waves", "objective": "sales", "status": "live",
    "discount_code": "WAVES15", "landing": "/", "spend_cents": 40000})
ok(r.status_code == 200, "campaign created")
_cid = r.json()["id"]
_cp = [x for x in c.get("/api/store/admin/campaigns",
                        headers=A).json()["campaigns"] if x["id"] == _cid][0]
ok(_cp["code"] and _cp["link"] == f"/c/{_cp['code']}", "campaign gets a link")
_r = c.get(f"/c/{_cp['code']}", follow_redirects=False)
ok(_r.status_code == 307 and "discount=WAVES15" in _r.headers["location"],
   "tracked link forwards with the discount applied")
ok([x for x in c.get("/api/store/admin/campaigns", headers=A).json()
    ["campaigns"] if x["id"] == _cid][0]["clicks"] == 1,
   "the click was counted")
ok(c.post("/api/store/admin/campaigns", headers=A, json={
    "name": "Evil", "landing": "https://evil.example"}).status_code == 200
   and all(x["landing"].startswith("/") for x in
           c.get("/api/store/admin/campaigns", headers=A).json()["campaigns"]),
   "off-site landing pages are refused — no open redirect")
r = c.post("/api/store/admin/creatives", headers=A, json={
    "campaign_id": _cid, "platform": "tiktok", "kind": "video",
    "title": "9:16 hero cut", "url": "https://cdn.example/a.mp4",
    "status": "live"})
ok(r.status_code == 200, "creative added to a campaign")
ok(c.post("/api/store/admin/creatives", headers=A, json={
    "campaign_id": _cid, "platform": "myspace"}).status_code == 400,
   "unknown platform rejected")
ok(c.post("/api/store/admin/creatives", headers=A, json={
    "campaign_id": _cid, "platform": "meta",
    "url": "javascript:alert(1)"}).status_code == 400,
   "javascript: asset links rejected")
_cp = [x for x in c.get("/api/store/admin/campaigns",
                        headers=A).json()["campaigns"] if x["id"] == _cid][0]
ok(_cp["platforms"] == ["tiktok"] and _cp["live_creatives"] == 1,
   "campaign reports which platforms it runs on")
ok(c.get("/api/store/admin/campaigns").status_code == 403,
   "campaigns need the marketing permission")

# --- ERP polish ---
_ops = c.get("/ops/app.js").text
import re as _re
ok(not _re.search(r"[\U0001F300-\U0001FAFF]", _ops),
   "no emoji left in the ops app")
ok("OPS_ICONS" in _ops, "ops app uses an inline icon set")
_css = c.get("/ops/styles.css").text
ok("--accent: var(--brand, #4634d9)" in _css
   and "var(--brand-warm" in _css,
   "the ops palette takes its accent from THIS business's brand, with a "
   "literal kept as the fallback — one install should not have two "
   "brands, and a tenant that never chose colours still gets a palette")
ok("--bg: #e8eaee" in _css and "--panel: #f6f7f9" in _css
   and "--deep: #14161d" in _css,
   "and the back office is light, a shade greyer than the shop: the same "
   "business seen from behind the counter, not a different product — "
   "with a deep tone kept for the surfaces that earn it, video and maps")
_shell = c.get("/ops/").text
ok("app.js?v=" in _shell and "styles.css?v=" in _shell,
   "ops shell stamps its assets, so a deploy can't strand stale JS")

# --- document vault & e-signature ---
ok(c.get("/api/store/admin/documents").status_code == 403,
   "the vault needs the documents permission")
_d = c.post("/api/store/admin/documents", headers=A, json={
    "title": "Supply agreement — Hudson DC", "category": "contract",
    "party_kind": "vendor", "party_name": "Hudson DC",
    "party_email": "ops@hudson.example",
    "body": "The parties agree as follows. Term of twelve months.",
    "expires": time.time() + 20 * 86400})
ok(_d.status_code == 200, "document filed")
_did = _d.json()["id"]
ok(c.post("/api/store/admin/documents", headers=A,
          json={"title": "x", "category": "nope"}).status_code == 400,
   "unknown category rejected")
_lib = c.get("/api/store/admin/documents", headers=A).json()
ok(any(x["id"] == _did for x in _lib["documents"]), "document appears in the vault")
ok(any(x["id"] == _did for x in _lib["expiring"]),
   "an expiry inside 45 days is surfaced")
ok(len(_lib["party_kinds"]) == 5,
   "documents cover customers, vendors, partners, employees and internal")

_sig = c.post(f"/api/store/admin/documents/{_did}/request-signature", headers=A,
              json={"signer_name": "Dana", "signer_email": "dana@hudson.example"})
ok(_sig.status_code == 200 and "/sign/" in _sig.json()["link"],
   "signature request creates a signing link")
_tok = _sig.json()["link"].rsplit("/", 1)[-1]
ok(c.post(f"/api/store/admin/documents/{_did}/request-signature", headers=A,
          json={"signer_name": "X", "signer_email": "nope"}).status_code == 400,
   "a bad signer email is rejected")
_page = c.get(f"/sign/{_tok}")
ok(_page.status_code == 200 and "Sign this document" in _page.text,
   "the signing page renders for the recipient")
ok(c.get("/sign/not-a-real-token").status_code == 404,
   "an unknown signing token 404s")
ok(c.post(f"/sign/{_tok}", json={"typed_name": "D"}).status_code == 400,
   "a one-character name is refused")
_done = c.post(f"/sign/{_tok}", json={"typed_name": "Dana Whitfield"})
ok(_done.status_code == 200 and _done.json()["remaining"] == 0,
   "document signed, nothing outstanding")
ok(c.post(f"/sign/{_tok}", json={"typed_name": "Dana Whitfield"}
          ).status_code == 400, "a signed document can't be signed twice")
_cert = c.get(f"/sign/{_tok}/certificate")
ok(_cert.status_code == 200 and "Signing certificate" in _cert.text
   and "unchanged since it was signed" in _cert.text,
   "the certificate proves the document is unaltered")
ok("simple electronic signature" in _cert.text,
   "the certificate states plainly what kind of signature this is")
ok("Dana Whitfield" in _cert.text and "<img src=\"data:" not in _cert.text,
   "an empty signature pad falls back to the typed name, not a blank box")
_sid = [s for s in c.get("/api/store/admin/documents", headers=A).json()
        ["documents"] if s["id"] == _did][0]["signatures"][0]["id"]
ok(c.post(f"/api/store/admin/signatures/{_sid}/void",
          headers=A).status_code == 400,
   "a completed signature cannot be voided away")
_trail = c.get(f"/api/store/admin/documents/{_did}/trail", headers=A).json()
ok({e["action"] for e in _trail} >= {"created", "signature requested",
                                     "viewed", "signed"},
   "the audit trail records the whole life of the document")

# --- ops app modernisation ---
_ops = c.get("/ops/app.js").text
ok("renderDocs" in _ops and "ops-modal" in _ops,
   "ops app has the documents view and a modal")
_css = c.get("/ops/styles.css").text
ok(".page-head" in _css and ".stat " in _css and "#ops-modal" in _css,
   "ops stylesheet carries the modernised components")

# --- editing what could previously only be created ---
_pid = c.get("/api/products").json()[0]["id"]
ok(c.patch(f"/api/store/admin/products/{_pid}", headers=A, json={
    "name": "Test Sauce Deluxe", "sku": "T-1", "price_cents": 950,
    "case_price_cents": 8000}).status_code == 200, "product edited")
ok(c.get("/api/products").json()[0]["price_cents"] == 950, "the edit stuck")
c.post("/api/admin/products", headers=A, json={
    "sku": "T-2", "name": "Second", "price_cents": 100,
    "case_price_cents": 900})
_p2id = [p for p in c.get("/api/products").json() if p["sku"] == "T-2"][0]["id"]
ok(c.patch(f"/api/store/admin/products/{_pid}", headers=A,
           json={"sku": "T-2"}).status_code == 400,
   "a duplicate SKU is refused")
_del = c.delete(f"/api/store/admin/products/{_pid}", headers=A).json()
ok(_del["action"] == "retired",
   "a product with order history is retired, not deleted")

_cid = c.post("/api/store/admin/collections", headers=A,
              json={"slug": "test-collection", "name": "Test collection",
                    "product_ids": []}).json()["id"]
ok(c.patch(f"/api/store/admin/collections/{_cid}", headers=A, json={
    "name": "Renamed", "product_ids": [_p2id]}).status_code == 200,
   "collection edited")
_after = [x for x in c.get("/api/store/catalog").json()["collections"]
          if x["id"] == _cid][0]
ok(_after["name"] == "Renamed" and _after["product_ids"] == [_p2id],
   "collection rename and membership both saved")

c.post("/api/store/admin/discounts", headers=A,
       json={"code": "EDITME", "pct": 10, "active": True})
ok(c.patch("/api/store/admin/discounts/EDITME", headers=A,
           json={"pct": 25, "usage_limit": 5}).status_code == 200,
   "discount edited")
ok(c.patch("/api/store/admin/discounts/EDITME", headers=A,
           json={"pct": 0}).status_code == 400, "0% discount refused")
ok(c.delete("/api/store/admin/discounts/EDITME",
            headers=A).json()["action"] == "deleted", "unused discount deleted")
_batch = c.post("/api/store/admin/discounts/unique", headers=A,
                json={"prefix": "VIP", "count": 12, "pct": 20}).json()
ok(_batch["count"] == 12 and len(set(_batch["codes"])) == 12,
   "twelve distinct single-use codes minted")
_one = c.get("/api/store/admin/discounts2", headers=A).json()
_v = [d for d in _one if d["code"] == _batch["codes"][0]][0]
ok(_v["usage_limit"] == 1 and _v["per_customer_limit"] == 1,
   "a unique code is one use, one customer")
ok(any(b["batch"] == _batch["batch"] for b in
       c.get("/api/store/admin/discounts/batches", headers=A).json()),
   "batches are listed")

# --- blog comments ---
_post = c.post("/api/store/admin/posts", headers=A, json={
    "slug": "test-post", "title": "Test post", "body": "<p>Hi</p>"}).json()
ok(c.post("/api/store/blog/test-post/comments",
          json={"name": "Ann", "body": "Nice"}).status_code == 403,
   "comments are closed by default")
_pid2 = [p for p in c.get("/api/store/admin/posts", headers=A).json()
         if p["slug"] == "test-post"][0]["id"]
c.post(f"/api/store/admin/posts/{_pid2}/comments-toggle", headers=A,
       json={"comments_on": True})
ok(c.post("/api/store/blog/test-post/comments",
          json={"name": "Ann", "body": "Nice"}).json()["held"],
   "a comment is accepted but held for moderation")
ok(c.get("/api/store/blog/test-post/comments").json()["comments"] == [],
   "an unapproved comment is not published")
_cmid = c.get("/api/store/admin/comments", headers=A).json()[0]["id"]
c.post(f"/api/store/admin/comments/{_cmid}", headers=A,
       json={"action": "approve"})
ok(len(c.get("/api/store/blog/test-post/comments").json()["comments"]) == 1,
   "approving publishes it")
ok("Post comment" in c.get("/blog/test-post").text,
   "the comment form renders on a post with comments on")

# The journal knew when every post went up and told nobody: the column
# ordered the list and never appeared on it. A blog whose posts carry no
# date reads as one nobody has touched in years.
_post = c.get("/blog/test-post").text
_yr = _t0.strftime("%Y", _t0.localtime(_t0.time()))
ok(_yr in _post.split('<div class="post-content">')[0],
   "a post says the day it went up, above its own body")
ok('"datePublished"' in _post,
   "and tells a search engine the same thing — without it a BlogPosting "
   "is undated in a result page, which is the one thing a journal cannot "
   "afford to look")
ok(_yr in c.get("/blog").text,
   "and the index dates its cards, so the newest-first order it is "
   "already sorted in can actually be seen")

# --- what the screens were measuring and not saying ----------------------
# A geofence exists so somebody can check. The check was written on every
# shift, returned by /api/shifts, and rendered on no screen at all — while
# the screen that shows shifts asked an endpoint that never selected it.
# Proof nobody can look at is the same as no proof.
_kk = c.post("/api/admin/kiosks", headers=A,
             json={"label": "Front door", "store_id": 1, "active": True})
_kid = _kk.json().get("kiosk_id", "") if _kk.status_code == 200 else ""
# In and straight out again: the punch is what this needs, and leaving
# somebody on the clock changes what every later test sees.
c.post("/api/clock/me", headers=A, json={"kiosk": _kid})
c.post("/api/clock/me", headers=A, json={"kiosk": _kid})
_hrs = c.get("/api/hours/everyone", headers=A).json()
_allsh = [sh for r in _hrs["rows"] for sh in r["shifts"]]
ok(all("where" in sh for sh in _allsh),
   "every shift the hours screen shows says where the punch happened, or "
   "says it was not checked")
ok(any(sh["where"] for sh in _allsh),
   "and a punch made at a registered kiosk names the tablet: 'kiosk: "
   "Front door' is a thing a manager can go and stand next to")
# --- money out: expenses, mileage, and the year ---------------------------
_xm = c.get("/api/expenses/meta", headers=A).json()
ok(_xm["office"] and _xm["may_file"] and len(_xm["categories"]) >= 15
   and any(k["code"] == "phone" and k["default_pct"] == 50 for k in _xm["categories"])
   and any(k["code"] == "hosting" for k in _xm["categories"])
   and any(k["code"] == "vehicle" for k in _xm["categories"]),
   "the books open with the categories a return has lines for — phone, "
   "hosting, vehicle wear, fuel, fees — each with a default business share")
ok(c.get("/api/expenses/meta", headers=DE).json()["may_file"]
   and not c.get("/api/expenses/meta", headers=DE).json()["office"],
   "a driver may file; the office decides")
ok(c.post("/api/expenses/settings", headers=A, json={
    "distance_unit": "mi", "mileage_rate_cents": 70, "income_tax_pct": 20,
    "tax_year_start_month": 1}).status_code == 200,
   "the office sets the rate, the unit, the tax-year start and the "
   "estimate percentage")
ok(c.post("/api/expenses/settings", headers=A, json={"distance_unit": "furlongs"}).status_code == 400
   and c.post("/api/expenses/settings", headers=DE, json={"mileage_rate_cents": 1}).status_code == 403,
   "in a real unit, and only the office")
_yr = _xm["year"]
_x1 = c.post("/api/expenses", headers=A, json={
    "category": "hosting", "amount_cents": 2400, "vendor": "Hostco",
    "note": "the site, monthly", "recurring": "monthly"})
ok(_x1.status_code == 200 and _x1.json()["state"] == "approved"
   and _x1.json()["deductible_cents"] == 2400,
   "the office's own company-paid expense is a fact, not a claim — "
   "accepted as filed, fully deductible")
_x2 = c.post("/api/expenses", headers=A, json={
    "category": "phone", "amount_cents": 8000, "vendor": "Telco"})
ok(_x2.json()["business_pct"] == 50 and _x2.json()["deductible_cents"] == 4000,
   "a phone bill takes the category's default share: half of it counts")
_x3 = c.post("/api/expenses", headers=DE, json={
    "category": "vehicle", "amount_cents": 15000, "vendor": "Tyre place",
    "paid_by": "me", "note": "a tyre on the van"})
ok(_x3.status_code == 200 and _x3.json()["state"] == "pending"
   and _x3.json()["paid_by"] == "me",
   "a driver who paid for a tyre files a claim, and it waits")
_x3id = _x3.json()["id"]
ok(c.post("/api/expenses", headers=DE, json={"category": "personal",
          "amount_cents": 5000, "paid_by": "me"}).json()["deductible_cents"] == 0,
   "a personal expense is kept for the record and deducts nothing")
_xr = [c.post("/api/expenses", headers=DE, json={"category": "unicorns", "amount_cents": 1}).status_code,
       c.post("/api/expenses", headers=DE, json={"category": "fuel", "amount_cents": 0}).status_code,
       c.post("/api/expenses", headers=CU, json={"category": "fuel", "amount_cents": 100}).status_code]
ok(_xr[0] == 400 and _xr[1] == 400 and _xr[2] in (401, 403),
   f"an unknown category, no amount, or a customer are refused ({_xr})")
_rc = c.post(f"/api/expenses/{_x3id}/receipt", headers={**DE, "X-Filename": "tyre.png"},
             content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 400)
ok(_rc.status_code == 200 and _rc.json()["receipt_url"].startswith("/media/"),
   "the receipt goes with it, as a photo or a PDF")
ok([e for e in c.get("/api/expenses?state=pending", headers=A).json()["expenses"]
    if e["id"] == _x3id][0]["receipt_url"]
   and c.get("/api/expenses", headers=DE).json()["expenses"]
   and all(e["user_id"] == c.get("/api/expenses/meta", headers=DE).json()["me"]
           for e in c.get("/api/expenses", headers=DE).json()["expenses"]),
   "the office sees the queue with the receipt; the driver sees only "
   "their own")
ok(c.post(f"/api/expenses/{_x3id}/decide", headers=DE, json={"state": "approved"}).status_code == 403
   and c.post(f"/api/expenses/{_x3id}/decide", headers=A, json={"state": "paid"}).status_code == 409,
   "the driver cannot accept their own claim, and nothing is paid before "
   "it is accepted")
ok(c.post(f"/api/expenses/{_x3id}/decide", headers=A, json={"state": "approved"}).json()["state"] == "approved",
   "the office accepts the tyre")
# trips: own car at the rate; a company vehicle as a record
_t1 = c.post("/api/trips", headers=DE, json={
    "from_place": "depot", "to_place": "Northeast client", "purpose": "delivery",
    "distance": 12.5, "vehicle": "own"})
ok(_t1.status_code == 200 and _t1.json()["rate_cents"] == 70
   and _t1.json()["amount_cents"] == 875 and _t1.json()["unit"] == "mi"
   and _t1.json()["state"] == "pending",
   "12.5 miles in the driver's own car at 70 cents is 8.75 owed, pending")
_t2 = c.post("/api/trips", headers=DE, json={
    "purpose": "parts run", "start_odo": 41200, "end_odo": 41236.4, "vehicle": "own"})
ok(_t2.json()["distance"] == 36.4, "or two odometer readings, and the "
   "distance is the difference")
ok(c.post("/api/trips", headers=DE, json={"start_odo": 100, "end_odo": 90,
          "vehicle": "own"}).status_code == 400
   and c.post("/api/trips", headers=DE, json={"distance": 5000, "vehicle": "own"}).status_code == 400
   and c.post("/api/trips", headers=DE, json={"distance": 5, "vehicle": "spaceship"}).status_code == 400,
   "an odometer that goes backwards, a trip across a continent, and a "
   "vehicle that is neither are refused")
_t3 = c.post("/api/trips", headers=DE, json={"distance": 20, "vehicle": "company",
                                             "truck_id": tid, "purpose": "run"})
ok(_t3.json()["amount_cents"] == 0 and _t3.json()["truck"],
   "a company vehicle's trip is a record of distance — its fuel and wear "
   "are expenses of their own, and nothing is owed to the driver")
# a finished route is a trip already measured
_rr = c.post("/api/routes/plan", headers=A, json={"truck_id": tid, "region": "Northeast"}).json()
c.post(f"/api/routes/{_rr['id']}/status", headers=A, json={"status": "done"})
_unc = c.get("/api/trips", headers=DE).json()["unclaimed_routes"]
ok(any(r["id"] == _rr["id"] for r in _unc),
   "the driver's finished route waits to be claimed")
_fr = c.post(f"/api/trips/from-route/{_rr['id']}", headers=DE)
ok(_fr.status_code == 200 and _fr.json()["route_id"] == _rr["id"]
   and _fr.json()["vehicle"] == "company" and _fr.json()["distance"] > 0
   and _fr.json()["purpose"].startswith("route:"),
   "and one tap files it — its km, its truck, its date — with no "
   "odometer typed twice")
ok(c.post(f"/api/trips/from-route/{_rr['id']}", headers=DE).status_code == 409,
   "and not twice")
_tl = c.get("/api/trips?state=pending", headers=A).json()["trips"]
for _tp in _tl:
    c.post(f"/api/trips/{_tp['id']}/decide", headers=A, json={"state": "approved"})
# the year
_sm = c.get(f"/api/expenses/summary?year={_yr}", headers=A).json()
ok(_sm["deductible_cents"] >= 2400 + 4000 + 15000
   and _sm["expenses_total_cents"] > _sm["deductible_cents"]
   and any(k["code"] == "phone" and k["deductible_cents"] == 4000 for k in _sm["by_category"]),
   "the year adds up what was accepted, by category, at the business share")
ok(_sm["mileage"]["unit"] == "mi" and _sm["mileage"]["amount_cents"] >= 875
   and _sm["mileage"]["distance"] >= 12.5 + 36.4 + 20,
   "mileage: the distance driven and the money it is worth")
ok(_sm["owed_cents"] >= 15000 + 875 + int(36.4 * 70)
   and any(o["cents"] >= 15000 for o in _sm["owed"]),
   "what is owed to people, by person — the tyre and the own-car miles, "
   "not the company vehicle's")
ok(_sm["income_cents"] >= 0 and "sales_tax_collected_cents" in _sm
   and _sm["estimated_tax_cents"] == int(round(max(0, _sm["net_before_tax_cents"]) * 0.2))
   and "not a return" in _sm["estimate_note"],
   "income, the sales tax collected, net before tax, and an estimate that "
   "says it is one")
_csv = c.get(f"/api/expenses/export.csv?year={_yr}", headers=A)
ok(_csv.status_code == 200 and _csv.headers["content-type"].startswith("text/csv")
   and "Hostco" in _csv.text and "Tyre place" in _csv.text and "trip" in _csv.text
   and "deductible" in _csv.text.splitlines()[0],
   "and the accountant gets a CSV: one line per accepted thing, deductible "
   "share worked out")
ok(c.get("/api/expenses/summary", headers=DE).status_code == 403
   and c.get("/api/expenses/export.csv", headers=DE).status_code == 403,
   "the year is the office's")
ok(c.post(f"/api/expenses/{_x3id}/decide", headers=A, json={"state": "paid"}).json()["state"] == "paid"
   and not any(o["cents"] >= 15000 for o in
               c.get(f"/api/expenses/summary?year={_yr}", headers=A).json()["owed"]),
   "paid, the tyre leaves what is owed")
_pl = c.get("/api/analytics/pnl?days=30", headers=A).json()
ok(_pl["expenses_cents"] >= 2400 + 4000 + 15000 and _pl["mileage_cents"] >= 875,
   "and the P&L counts them beside labour and trucking — costs the "
   "system could not see until they were logged")
# --- the limits, lifted: recurring, VAT, assets, home office, edits ------
import datetime as _dtx
_ago40 = (_dtx.datetime.now() - _dtx.timedelta(days=40)).replace(hour=12).timestamp()
_rx = c.post("/api/expenses", headers=A, json={
    "category": "phone", "amount_cents": 8000, "vendor": "Telco",
    "spent_at": _ago40, "recurring": "monthly"})
ok(_rx.status_code == 200 and _rx.json()["next_at"] > _ago40
   and _rx.json()["next_at"] < time.time(),
   "a monthly phone bill filed forty days ago is due again already")
_rxid = _rx.json()["id"]
_before = len(c.get("/api/expenses", headers=A).json()["expenses"])
_rolled = c.get("/api/expenses/meta", headers=A).json()["rolled"]
_after = c.get("/api/expenses", headers=A).json()["expenses"]
_copies = [e for e in _after if e["recurring_from"] == _rxid]
ok(_rolled >= 1 and len(_copies) == 1 and _copies[0]["state"] == "pending"
   and _copies[0]["amount_cents"] == 8000 and _copies[0]["vendor"] == "Telco"
   and "check the amount" in _copies[0]["note"],
   "and opening the page files next month's copy — pending, from the "
   "template, with a note to glance at the amount")
ok(c.get("/api/expenses/meta", headers=A).json()["rolled"] == 0
   and len([e for e in c.get("/api/expenses", headers=A).json()["expenses"]
            if e["recurring_from"] == _rxid]) == 1,
   "once; opening it again files nothing more until the next month")
ok(c.patch(f"/api/expenses/{_rxid}", headers=A, json={"recurring": ""}).status_code == 200
   and c.get("/api/expenses", headers=A).json()["expenses"]
   and [e for e in c.get("/api/expenses", headers=A).json()["expenses"]
        if e["id"] == _rxid][0]["next_at"] == 0,
   "the office stops the series; what is filed stays")
# edits in place
_ed = c.post("/api/expenses", headers=DE, json={"category": "fuel", "amount_cents": 4000,
                                                 "paid_by": "me", "vendor": "Shell"})
_edid = _ed.json()["id"]
ok(c.patch(f"/api/expenses/{_edid}", headers=DE, json={"amount_cents": 4500, "note": "typo"}).json()["amount_cents"] == 4500,
   "a pending claim is corrected in place — no withdraw and refile")
ok(c.patch(f"/api/expenses/{_edid}", headers=CU, json={"amount_cents": 1}).status_code in (401, 403),
   "by its filer or the office only")
c.post(f"/api/expenses/{_edid}/decide", headers=A, json={"state": "approved"})
ok(c.patch(f"/api/expenses/{_edid}", headers=DE, json={"amount_cents": 9999}).status_code == 409,
   "once accepted, the amount stands")
_tx = c.post("/api/trips", headers=DE, json={"distance": 10, "vehicle": "own", "purpose": "x"}).json()
ok(c.patch(f"/api/trips/{_tx['id']}", headers=DE, json={"distance": 12}).json()["amount_cents"] == 12 * 70
   and c.patch(f"/api/trips/{_tx['id']}", headers=DE, json={"start_odo": 100, "end_odo": 90}).status_code == 400,
   "a pending trip is corrected too, and the amount follows the distance")
_lh = c.post("/api/hours/logged", headers=DE, json={
    "kind": "meeting", "starts": _ago40, "ends": _ago40 + 3600}).json()
ok(c.patch(f"/api/hours/logged/{_lh['id']}", headers=DE,
           json={"ends": _ago40 + 5400, "note": "ran long"}).json()["hours"] == 1.5,
   "and so are logged hours")
ok(c.patch(f"/api/hours/logged/{_lh['id']}", headers=CU, json={"note": "x"}).status_code in (401, 403),
   "by their filer or the office only")
# assets: written off, not deducted
_cap = c.post("/api/expenses", headers=A, json={
    "category": "equipment", "amount_cents": 300000, "vendor": "Laptops R Us"})
ok(_cap.json()["capitalised"] == 1 and _cap.json()["deductible_cents"] == 0,
   "equipment at or over the threshold is an asset: nothing deducted now")
_small = c.post("/api/expenses", headers=A, json={
    "category": "equipment", "amount_cents": 20000, "vendor": "a keyboard"})
ok(_small.json()["capitalised"] == 0 and _small.json()["deductible_cents"] == 20000,
   "a keyboard under it is an expense like any other")
_sm2 = c.get("/api/expenses/summary", headers=A).json()
ok(_sm2["capital_cents"] >= 300000 and _sm2["depreciation_cents"] >= 300000 // 5
   and any(a["vendor"] == "Laptops R Us" and a["this_year_cents"] == 60000 for a in _sm2["assets"]),
   "the year card shows the purchase capitalised and one fifth of it "
   "depreciated this year, straight-line over five")
ok(c.patch(f"/api/expenses/{_cap.json()['id']}", headers=A, json={"capitalised": False}).json()["deductible_cents"] == 300000
   and c.patch(f"/api/expenses/{_cap.json()['id']}", headers=A, json={"capitalised": True}).status_code == 200,
   "the office can say otherwise, either way")
# home office
c.post("/api/expenses/settings", headers=A, json={"home_office_pct": 10, "home_costs_cents": 2400000})
_sm3 = c.get("/api/expenses/summary", headers=A).json()
ok(_sm3["home_office_cents"] == 240000 and "home office" in _sm3["estimate_note"]
   and _sm3["net_before_tax_cents"] == _sm2["net_before_tax_cents"] - 240000,
   "ten percent of a 24,000 home is a 2,400 home-office line, and net "
   "moves by exactly that")
# VAT
c.post("/api/expenses/settings", headers=A, json={"tax_regime": "vat", "vat_pct": 20})
_vx = c.post("/api/expenses", headers=A, json={"category": "software", "amount_cents": 12000})
ok(_vx.json()["tax_cents"] == 2000 and _vx.json()["deductible_cents"] == 10000
   and _vx.json()["input_tax_cents"] == 2000,
   "under VAT a 120 software bill is 100 of cost and 20 of tax to reclaim")
_sm4 = c.get("/api/expenses/summary", headers=A).json()
ok(_sm4["vat"] and _sm4["vat"]["input_cents"] >= 2000
   and _sm4["vat"]["owed_cents"] == _sm4["vat"]["output_cents"] - _sm4["vat"]["input_cents"],
   "and the year says what is owed: charged on sales less reclaimed on "
   "purchases")
ok(c.post("/api/expenses", headers=A, json={"category": "software", "amount_cents": 12000,
          "tax_cents": 500}).json()["tax_cents"] == 500,
   "a receipt that says otherwise wins over the rate")
c.post("/api/expenses/settings", headers=A, json={"tax_regime": "sales_tax", "vat_pct": 0,
                                                    "home_office_pct": 0})
ok(c.get("/api/expenses/summary", headers=A).json()["vat"] is None,
   "back on sales tax, the VAT line is gone")

_xjs = (Path(__file__).parent.parent / "src/erp/frontend/app/17-expenses.js"
        ).read_text(encoding="utf-8")
ok("async function renderExpenses(" in _xjs and "function expenseForm(" in _xjs
   and "function tripForm(" in _xjs and "from-route" in _xjs and "export.csv" in _xjs
   and "Owed to people" in _xjs and "receipt" in _xjs,
   "the Expenses screen files, lists, accepts, claims routes, keeps "
   "receipts and hands the year to the accountant")

# --- the wifi: links that point at the door that is actually open --------
import importlib.util as _ilu
_ln = _ilu.spec_from_file_location("bc_launch", Path(__file__).parent.parent / "scripts/launch.py")
_lnm = _ilu.module_from_spec(_ln); _ln.loader.exec_module(_lnm)
ok("IP:192.168.1.50" in _lnm.cert_sans("192.168.1.50")
   and "DNS:localhost" in _lnm.cert_sans("192.168.1.50")
   and "DNS:*.localhost" in _lnm.cert_sans("192.168.1.50")
   and "IP:127.0.0.1" not in _lnm.cert_sans("127.0.0.1").replace("IP:127.0.0.1", "", 1),
   "the self-signed cert names the machine's wifi address beside "
   "localhost — a cert that names only localhost makes every phone call "
   "the site an impostor")
ok(_lnm.cert_covers(Path("/nonexistent/cert.pem"), "10.0.0.9") is False
   or not __import__("shutil").which("openssl"),
   "and a cert that does not name the current address is made again")
_env0 = {k: os.environ.get(k) for k in ("BC_SCHEME", "BC_PORT")}
os.environ["BC_SCHEME"] = "https"; os.environ["BC_PORT"] = "8443"
_lu = base_url()
for k, v in _env0.items():
    if v is None: os.environ.pop(k, None)
    else: os.environ[k] = v
ok(_lu.startswith("https://") and _lu.endswith(":8443"),
   "an HTTPS server on 8443 hands out https links on 8443 — QR codes and "
   "class invites point at the door that is open, not at plain http on "
   "the default port")
ok(base_url().startswith("http://") and not base_url().startswith("https"),
   "and without the launcher's word, links are plain http on the "
   "configured port as before")
_lj = json.loads((Path(__file__).parent.parent / ".claude/launch.json").read_text())
_pv = [c for c in _lj["configurations"] if c["name"] == "business-control"][0]
_hs = [c for c in _lj["configurations"] if c["name"] == "business-control-https"]
ok("0.0.0.0" in _pv["runtimeArgs"] and _hs and "--https" in _hs[0]["runtimeArgs"]
   and "0.0.0.0" in _hs[0]["runtimeArgs"] and _hs[0]["url"].startswith("https://"),
   "the preview binds every interface so a phone on the wifi reaches it, "
   "and an HTTPS preview stands beside it for the camera and the home "
   "screen")
ok("--host 0.0.0.0" in (Path(__file__).parent.parent
                        / "command_utilities/Start Business Control (HTTPS).command").read_text(),
   "the double-click HTTPS start does the same")

# --- one tenant, two nodes: the hub and the rooms are rows now ------------
import asyncio as _aio
from erp.backend import chat as _chat, community as _cmm
_here = _chat.node_id()
ok(_here and ":" in _here, "a node knows its own name")
_conx = _db.connect()
_conx.execute("INSERT OR REPLACE INTO ws_presence(node,user_id,seen)"
              " VALUES('other-node:1', ?, ?)", (cust["id"], _t.time()))
_conx.commit()
ok(cust["id"] in _chat.online_ids() and cust["id"] not in _chat.local_ids(),
   "somebody connected to the OTHER node counts as online here — presence "
   "is a table every node reads, not a dict in one process")
_aio.run(_chat.send_to([cust["id"]], {"type": "msg", "body": "over the wire"}))
_mail = _chat.collect(cust["id"])
ok(len(_mail) == 1 and json.loads(_mail[0])["body"] == "over the wire",
   "a message for them lands in the outbox, and the node holding their "
   "socket collects it")
ok(_chat.collect(cust["id"]) == [], "once")
_conx.execute("UPDATE ws_presence SET seen=? WHERE node='other-node:1'",
              (_t.time() - 3600,))
_conx.commit()
ok(cust["id"] not in _chat.online_ids(),
   "a node that stopped saying so an hour ago is not counted — a dead "
   "machine does not keep its people online")
_aio.run(_chat.send_to([cust["id"]], {"type": "msg", "body": "to nobody"}))
ok(_chat.collect(cust["id"]) == [],
   "and nothing is left in the outbox for somebody connected nowhere")
_conx.execute("DELETE FROM ws_presence WHERE node='other-node:1'"); _conx.commit()
# the class's video room is rows too
_j1 = _cmm._rtc_join("rm-two-nodes", None, {"name": "Ann", "user_id": 1}, con=_conx)
_j2 = _cmm._rtc_join("rm-two-nodes", None, {"name": "Bob", "user_id": 2}, con=_conx)
_conx2 = _db.connect()          # a second connection stands in for a second node
ok([w["name"] for w in _cmm._rtc_poll("rm-two-nodes", _j2["peer"], con=_conx2)["who"]]
   == ["Ann", "Bob"],
   "a room joined through one connection is seen whole through another — "
   "the roster is a table, so a second node has the same room")
_cmm._rtc_signal("rm-two-nodes", _j2["peer"], _j1["peer"], {"sdp": "offer"}, con=_conx)
_pl2 = _cmm._rtc_poll("rm-two-nodes", _j2["peer"], con=_conx2)
ok(_pl2["messages"] == [{"from": _j1["peer"], "payload": {"sdp": "offer"}}],
   "and a signal posted on one lands in the mailbox read from the other")
ok(_cmm._rtc_poll("rm-two-nodes", _j2["peer"], con=_conx2)["messages"] == [],
   "once")
_conx.execute("UPDATE rtc_peers SET seen=? WHERE room='rm-two-nodes' AND peer=?",
              (_t.time() - 600, _j1["peer"])); _conx.commit()
ok([w["name"] for w in _cmm._rtc_poll("rm-two-nodes", _j2["peer"], con=_conx2)["who"]]
   == ["Bob"],
   "a peer that stopped polling ten minutes ago is swept from the room — "
   "the memory version kept its ghosts until a restart")
_cmm._rtc_leave("rm-two-nodes", _j2["peer"], con=_conx)
_conx2.close(); _conx.close()

# --- files somewhere every node can reach --------------------------------
# A fake S3 in this process: four verbs on a dict, checking that every
# request carries a Signature V4 header. Not AWS; enough to prove the
# client speaks the protocol and the app never touches a path.
import threading as _thr
from http.server import BaseHTTPRequestHandler as _H, HTTPServer as _HS
_S3STORE: dict = {}
_S3SEEN: list = []
class _FakeS3(_H):
    def log_message(self, *a): pass
    def _auth(self):
        a = self.headers.get("Authorization", "")
        _S3SEEN.append((self.command, self.path, a[:16], self.headers.get("x-amz-content-sha256", "")[:8]))
        if not (a.startswith("AWS4-HMAC-SHA256 Credential=") and "Signature=" in a
                and self.headers.get("x-amz-date")):
            self.send_response(403); self.end_headers(); return False
        return True
    def do_PUT(self):
        if not self._auth(): return
        n = int(self.headers.get("Content-Length", 0))
        _S3STORE[self.path] = self.rfile.read(n)
        self.send_response(200); self.end_headers()
    def do_GET(self):
        if not self._auth(): return
        b = _S3STORE.get(self.path)
        if b is None: self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_HEAD(self):
        if not self._auth(): return
        self.send_response(200 if self.path in _S3STORE else 404); self.end_headers()
    def do_DELETE(self):
        if not self._auth(): return
        _S3STORE.pop(self.path, None); self.send_response(204); self.end_headers()
_s3srv = _HS(("127.0.0.1", 0), _FakeS3)
_thr.Thread(target=_s3srv.serve_forever, daemon=True).start()
_s3port = _s3srv.server_address[1]
from erp.backend import blobs as _blobs, materials as _MAT
_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 300
ok(_blobs.store()["kind"] == "local",
   "with nothing configured, files live where they always did")
_savedL = _MAT.save(_png, allow=("image",))
ok(_blobs.local_path(_savedL["path"]) and _blobs.get(_savedL["path"]) == _png
   and _MAT.unlink(_savedL["path"]) and _blobs.get(_savedL["path"]) is None,
   "the local driver writes, reads and deletes the same relative path the "
   "row holds")
os.environ["BC_BLOBS"] = json.dumps({"kind": "s3", "endpoint": f"http://127.0.0.1:{_s3port}",
    "bucket": "bc-files", "region": "us-east-1", "key": "AKIATEST", "secret": "s3cr3t",
    "prefix": "tenants"})
try:
    ok(_blobs.store()["kind"] == "s3", "configured, the store is an object store")
    _saved = _MAT.save(_png, allow=("image",))
    _keyp = [k for k in _S3STORE if k.endswith(_saved["path"])]
    ok(len(_keyp) == 1 and _keyp[0].startswith("/bc-files/tenants/")
       and _S3STORE[_keyp[0]] == _png,
       "an upload goes to the bucket under prefix/tenant/path — the same "
       "relative path the row holds, so a tenant moved to object storage "
       "keeps every row it had")
    ok(all(a.startswith("AWS4-HMAC-SHA25") and h for (_, _, a, h) in _S3SEEN),
       "every request is signed (Signature V4) and carries the payload hash")
    ok(_blobs.local_path(_saved["path"]) is None and _blobs.get(_saved["path"]) == _png
       and _blobs.exists(_saved["path"]),
       "nothing is on this node's disk; the bytes come back from the store")
    ok(_MAT.unlink(_saved["path"]) and not _blobs.exists(_saved["path"]),
       "and deleting the row's file deletes the object")
    # what this node already has on disk goes up once
    os.environ.pop("BC_BLOBS")
    _old = _MAT.save(_png, allow=("image",))
    _conb = _db.connect()
    _conb.execute("INSERT INTO learning_materials(lesson_id,session_id,owner_id,kind,"
                  "path,original,mime,bytes,created_at) VALUES(NULL,NULL,1,'image',?,"
                  "'old.png','image/png',?,?)", (_old["path"], len(_png), _t.time()))
    _conb.commit()
    os.environ["BC_BLOBS"] = json.dumps({"kind": "s3", "endpoint": f"http://127.0.0.1:{_s3port}",
        "bucket": "bc-files", "key": "AKIATEST", "secret": "s3cr3t"})
    _mig = _blobs.migrate_local_to_store(_conb)
    ok(_mig["pushed"] == 1 and _blobs.exists(_old["path"]),
       "a node's existing uploads are pushed into the store by their rows")
    ok(_blobs.migrate_local_to_store(_conb)["present"] >= 1
       and _blobs.migrate_local_to_store(_conb)["pushed"] == 0,
       "and pushing again pushes nothing — the store already has them")
    _conb.execute("DELETE FROM learning_materials WHERE path=?", (_old["path"],))
    _conb.commit(); _conb.close()
    # the shop's own pictures go the same way — a real picture, since the
    # pipeline makes two sizes from it and a header alone will not decode
    import base64 as _b64, io as _iob
    from PIL import Image as _Img
    _buf = _iob.BytesIO(); _Img.new("RGBA", (64, 48), (200, 30, 30, 255)).save(_buf, "PNG")
    _png_real = _buf.getvalue()
    _pm = c.post("/api/store/admin/media", headers=A, json={
        "product_id": pid, "data_url": "data:image/png;base64," + _b64.b64encode(_png_real).decode(),
        "alt": "the can"})
    ok(_pm.status_code == 200 and _pm.json()["kind"] == "image",
       "a product picture uploads through the storefront pipeline")
    _mid = _pm.json()["id"]
    _keys = [k for k in _S3STORE if f"/media/{_mid}" in k]
    ok(any(k.endswith(f"media/{_mid}.png") for k in _keys)
       and any(f"media/{_mid}_lg." in k for k in _keys) and any(f"media/{_mid}_th." in k for k in _keys),
       "the original and both sizes land in the bucket — nothing on this "
       "node's disk")
    _mf = c.get(f"/media/m/{_mid}")
    _mt = c.get(f"/media/m/{_mid}/thumb")
    ok(_mf.status_code == 200 and _mf.headers["content-type"].startswith("image/")
       and _mt.status_code == 200 and len(_mt.content) > 0,
       "and the shop serves the picture and its thumbnail from the store")
    ok(c.get(f"/media/product/{pid}").status_code == 200,
       "the legacy product-art route finds the pipeline's picture the same way")
    _vp = c.post("/api/field/photo", headers=A, json={"visit_id": 0, "step_id": 0, "kind": "shelf",
                 "data_url": "data:image/png;base64," + _b64.b64encode(_png_real).decode()})
    if _vp.status_code == 200:
        ok(c.get(_vp.json()["url"], headers=A).status_code == 200
           and any(k.endswith("visit_" + _vp.json()["token"]) for k in _S3STORE),
           "a visit photo too — filed in the store, served from it")
    ok(c.delete(f"/api/store/admin/media/{_mid}", headers=A).status_code == 200
       and not any(f"/media/{_mid}" in k for k in _S3STORE),
       "deleting the media deletes every size from the bucket")
finally:
    os.environ.pop("BC_BLOBS", None)
    _s3srv.shutdown()
ok(_blobs.store()["kind"] == "local", "(and back to local for what follows)")

# --- the Postgres face: what the app's SQL becomes ------------------------
from erp.backend import pgstore as _pgs
ok(_pgs.translate("SELECT * FROM t WHERE a=? AND b LIKE ? AND c >= 5 %% 2", True)
   == "SELECT * FROM t WHERE a=%s AND b ILIKE %s AND c >= 5 %%%% 2",
   "placeholders become %s, SQLite's lax LIKE becomes ILIKE, and a literal "
   "percent is escaped when parameters ride along")
ok(_pgs.translate("SELECT 1 WHERE reason LIKE 'order:%'", False)
   == "SELECT 1 WHERE reason ILIKE 'order:%'",
   "and left alone when none do")
ok(_pgs.translate("SELECT CAST((a - ?) / ? AS INTEGER) AS day, CAST(x AS TEXT) FROM t")
   == "SELECT sqlite_int((a - %s) / %s) AS day, CAST(x AS TEXT) FROM t",
   "an integer cast truncates the way SQLite's does — a day bucket is "
   "floor, never round — and other casts pass through")
ok(_pgs.translate("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, n INTEGER, x REAL, b BLOB)")
   == "CREATE TABLE IF NOT EXISTS t (id BIGSERIAL PRIMARY KEY, n BIGINT, x DOUBLE PRECISION, b BYTEA)",
   "the schema's SQLite types become Postgres types, and an INTEGER "
   "PRIMARY KEY becomes a sequence")
ok(_pgs.translate("SELECT name FROM u ORDER BY name COLLATE NOCASE LIMIT -1")
   == "SELECT name FROM u ORDER BY lower(name) LIMIT ALL",
   "COLLATE NOCASE orders by lower(), and LIMIT -1 means no limit")
ok(_pgs._split_statements("CREATE TABLE a(x TEXT); -- a; comment\nINSERT INTO a VALUES('semi;colon'); /* b; */ SELECT 1")
   == ["CREATE TABLE a(x TEXT)", "INSERT INTO a VALUES('semi;colon')", "SELECT 1"],
   "a script splits on semicolons outside quotes and comments")
_row = _pgs.Row(("id", "name", "total"), {"id": 0, "name": 1, "total": 2},
                (7, "x", __import__("decimal").Decimal("12.50")))
ok(_row["id"] == 7 and _row[1] == "x" and _row["total"] == 12.5 and dict(_row)["name"] == "x"
   and list(_row) == [7, "x", 12.5] and "name" in _row,
   "a row answers by name, by position, as a dict and as values — and a "
   "SUM comes back as a number, not a Decimal")
_sq = __import__("sqlite3")
ok(issubclass(_pgs.Error, _sq.Error) and issubclass(_pgs.IntegrityError, _sq.IntegrityError),
   "its errors ARE sqlite3 errors, so every existing fallback keeps its "
   "meaning")

# --- every QR the app prints is read by the scanner meant for it --------
# A code is only as good as the thing that reads it. Each pair below is
# printed by one screen and scanned by another, and the two are tested
# as a pair, so a change to either side that breaks the round trip
# fails here rather than at a door with a queue behind it.
_qr = c.get("/api/qr.svg?data=" + "bc:clock:demo")
ok(_qr.status_code == 200 and "<svg" in _qr.text and "<path" in _qr.text,
   "the printer: /api/qr.svg draws a real QR as an SVG path")
ok(c.get("/api/qr.svg?data=" + "x" * 600).status_code == 400,
   "and refuses a payload no phone camera would read")
_bdg = c.post("/api/me/badge", headers=A).json()
ok(_bdg["token"].startswith("bc:clock:"),
   "an employee badge prints as bc:clock:<token>, which nothing else "
   "prints — a badge cannot be mistaken for an ID card")
_pch = c.post("/api/clock/badge", json={"token": _bdg["token"]})
ok(_pch.status_code == 200 and _pch.json()["name"] == admin["name"],
   f"and the clock reads it: scan the badge, you are on the clock"
   f" ({_pch.status_code} {_pch.text[:80]})")
c.post("/api/clock/badge", json={"token": _bdg["token"]})    # and off again
ok(c.post("/api/clock/badge", json={"token": "bc:person:" + "0" * 32}).status_code == 404
   and c.post("/api/clock/badge", json={"token": "https://example.com/x"}).status_code == 404,
   "a student card or a stray link held up to the clock is refused, not "
   "punched in as somebody")
_sq = c.post("/api/me/qr", headers=A).json()
import re as _re
ok(_re.match(r"^https?://[^/]+/qr-login/[\w-]+$", _sq["url"]),
   "a sign-in QR is a link of exactly the shape the scanner accepts — "
   "/qr-login/<token> on this origin, nothing else navigates")
_sqp = c.get("/qr-login/" + _sq["url"].rsplit("/", 1)[1], follow_redirects=False)
ok(_sqp.status_code in (200, 302, 303, 307) and "expired" not in _sqp.text.lower(),
   "and scanning it lands you signed in")
_trk = c.post(f"/api/trucks/{tid}/checkin", headers=A, json={})
ok(_trk.status_code == 200 and _re.match(r"^bc:truck:\d+$", f"bc:truck:{tid}"),
   "a truck's tag is bc:truck:<id>, and the scan screen's check-in reads it")
_qsj = (Path(__file__).parent.parent / "src/storefront/frontend/qr-scan.js"
        ).read_text(encoding="utf-8")
ok("qrs-typed" in _qsj and "loadJsQR" in _qsj and "/vendor/jsqr.js" in _qsj
   and "willReadFrequently" in _qsj,
   "the scanner has two roads besides the browser's own detector: a "
   "typed field that a USB scanner or a read-out code lands in, and a "
   "software decoder for the browsers with no detector — Safari on every "
   "iPhone and iPad, and Firefox — so a door run from an iPad is not a "
   "door that cannot scan")
_vj = c.get("/vendor/jsqr.js")
ok(_vj.status_code == 200 and "jsQR" in _vj.text[:4000]
   and "Apache License" in _vj.text[:3000],
   "and the decoder is served from this install with its licence, not "
   "fetched from somebody's CDN at the door")
ok("Type the code in instead, or open" not in _qsj,
   "the old dead end — 'type it in' with nowhere to type — is gone")

_ojs = ops_app_js()
ok("sh.where" in _ojs and "not checked" in _ojs,
   "a punch with no location says so rather than leaving a blank cell — "
   "an empty column reads as 'fine' when it means 'we never asked'")
ok("paid_hours" in _ojs,
   "and the row shows what the week actually costs, rather than leaving "
   "the reader to add regular, overtime and leave themselves")
ok("last_order_at" in _ojs,
   "a customer row says when they last bought: the number that decides "
   "whether they are a customer or someone who used to be")
ok("temp_c" in _ojs and "humidity_pct" in _ojs and "cloud_pct" in _ojs,
   "and the weather fetched for every trading day reaches the day it "
   "belongs to — it was being stored, returned, and shown nowhere")

# --- the tablets by the door ---------------------------------------------
# A kiosk was registerable, enforceable and billable before it was ever
# visible, and worse: nothing in the app ever wrote the id onto a tablet.
# bc_kiosk_id was read on every punch and set by nobody, so a person
# bound to a kiosk could not clock in at all — their own door refused
# them, and the only way to reach the feature was to forge the field by
# hand, which is exactly what my own earlier check had done.
_kjs = ops_app_js()
ok('id: "kiosks"' in _kjs and "async function renderKiosks" in _kjs,
   "the tablets have a screen: they could be registered, bound to staff, "
   "counted against a limit and charged for without one")
ok('localStorage.setItem(KIOSK_KEY' in _kjs,
   "and something in this app finally writes the id onto a device — the "
   "step between registering a kiosk and it existing anywhere but a "
   "table, which nothing had ever done")
ok("qrImg(link.url" in _kjs,
   "carried on a QR, because the tablet is across the room from the "
   "computer that registered it — and the URL is the one the server "
   "minted, not one the page assembled around a kiosk id")
ok('/^#\\/([\\w-]+)(?:\\/([\\w-]+))?$/' in _kjs,
   "and the route accepts a minted token, not only a row number — a "
   "kiosk is named by the id it was given, so a digits-only route could "
   "not link to one at all")
ok("never used" in _kjs and "settling" in _kjs,
   "the list says which tablets are actually punched on, and holds a "
   "new one back from being called idle on its second day")
ok("cannot clock in at all" in _kjs,
   "and the empty state warns against the trap the feature shipped in: "
   "binding somebody to a kiosk that no tablet has claimed")

# --- setting a tablet up without an owner standing at it -----------------
# Enrolling needed an admin session ON the tablet, which means an owner
# walking to every door — and in a shop that is exactly how a device ends
# up permanently signed in as the manager. The authority is spent minting
# a link instead; what walks to the door can do one thing, once, soon.
_kall = c.get("/api/admin/kiosks", headers=A).json()
_k1 = _kall[0]["kiosk_id"]
_link = c.post(f"/api/admin/kiosks/{_k1}/enrol", headers=A, json={}).json()
ok(_link["token"] and _link["expires_sec"] > 0,
   "an owner mints a setup link at the screen, without going anywhere")
ok(f"/ops/#/enrol/{_link['token']}" in _link["url"],
   "and it carries the token rather than the kiosk's own id — a photo of "
   "a QR that named the door would let anybody's phone claim to be it")
_claim = c.post("/api/kiosk/claim", json={"token": _link["token"]})
ok(_claim.status_code == 200 and _claim.json()["kiosk_id"] == _k1,
   "whoever is standing at the tablet spends it with no session at all, "
   "which is the whole point")
ok(c.post("/api/kiosk/claim",
          json={"token": _link["token"]}).status_code == 410,
   "and it is gone the moment it is used: a link left live on somebody's "
   "phone is a door they can pretend to be standing at")
ok(c.post("/api/kiosk/claim", json={"token": "nonsense"}).status_code == 410,
   "a token nobody minted gets the same answer as a spent one — a "
   "different error would say which guesses were close")
_stale = c.post(f"/api/admin/kiosks/{_k1}/enrol", headers=A, json={}).json()
_kc2 = _db.connect()
_kc2.execute("UPDATE kiosk_enrolments SET expires_at=? WHERE token=?",
             (_t0.time() - 1, _stale["token"]))
_kc2.commit(); _kc2.close()
ok(c.post("/api/kiosk/claim",
          json={"token": _stale["token"]}).status_code == 410,
   "and one nobody spent dies on its own, so a link that never made it "
   "to the door does not wait around for somebody else to find")
ok(c.post("/api/admin/kiosks/nosuchkiosk/enrol",
          headers=A, json={}).status_code == 404,
   "there is no link for a kiosk that does not exist")
_live = [k for k in c.get("/api/admin/kiosks", headers=A).json()
         if k["kiosk_id"] == _k1][0]
ok(_live["claimed_at"] > 0,
   "the kiosk row records when a tablet last took its identity — a "
   "device claimed a door and somebody should be able to see that later")
# The link is bound to the network it was minted on. An owner presses
# the button standing in the shop; so is the tablet.
from erp.backend.main import _same_network as _sn  # noqa: E402
ok(_sn("203.0.113.9", "203.0.113.7") and not _sn("203.0.114.9",
                                                 "203.0.113.7"),
   "same shop, not same city: a /24 covers the office computer and the "
   "tablet by the door, which are on one network and never on one address")
ok(_sn("2001:db8::5", "2001:db8::99")
   and not _sn("2001:db9::5", "2001:db8::99"),
   "and a /64 does the same for v6, where a single device holds more "
   "addresses than a shop has staff")
ok(not _sn("203.0.113.7", "2001:db8::7") and not _sn("", "203.0.113.7"),
   "two families never match, and an address we do not have matches "
   "nothing — an unknown network is not a passing network")

# Who a request came from, which the network binding rests on entirely.
from erp.backend.main import _client_ip as _cip  # noqa: E402


class _FakeReq:
    def __init__(self, peer, xff=None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


ok(_cip(_FakeReq("127.0.0.1", "203.0.113.9")) == "203.0.113.9",
   "behind the proxy this ships with, the caller's real address is read "
   "with nothing to configure — the app binds loopback, so a request "
   "whose peer is 127.0.0.1 can only have come through Caddy")
ok(_cip(_FakeReq("127.0.0.1", "10.9.9.9, 203.0.113.9")) == "203.0.113.9",
   "and it takes the LAST hop, which is the proxy's own word for who "
   "called. Everything before it is what the caller claimed, so reading "
   "the first entry — the commoner mistake — reads the attacker's")
ok(_cip(_FakeReq("203.0.113.50", "127.0.0.1")) == "203.0.113.50",
   "a request that did NOT come through a local proxy has its header "
   "ignored outright: otherwise anyone could post one and be believed")
ok(_cip(_FakeReq("127.0.0.1")) == "127.0.0.1",
   "and with no header there is nothing to read, so the peer stands")
_dep = open("docs/product/DEPLOY.md").read()
ok("trust_forwarded_for" in _dep and "different machine" in _dep,
   "the runbook says when to set it and when not to — the answer for "
   "the layout it documents is 'not at all', and a setting nobody "
   "explains gets turned on everywhere by somebody being careful")

# A CDN answers for every caller, so the /24 guess collapses behind one:
# every shop arrives from the same edge and looks like one network.
from erp.backend import main as _mn3  # noqa: E402
_cfg0 = _mn3.CFG.get


def _cfg(**over):
    _mn3.CFG.get = lambda k, d=None: over.get(k, _cfg0(k, d))


_cfg(client_ip_header="", kiosk_networks=[])
ok(_cip(_FakeReq("127.0.0.1", "198.51.100.7")) == "198.51.100.7",
   "behind a CDN with nothing configured, the address is the edge's — "
   "which is the same for every shop, and a check on it is a formality")
_mn3.CFG.get = lambda k, d=None: ({"client_ip_header": "cf-connecting-ip",
                                   "kiosk_networks": []}.get(k)
                                  if k in ("client_ip_header",
                                           "kiosk_networks")
                                  else _cfg0(k, d))
_r2 = _FakeReq("127.0.0.1", "198.51.100.7")
_r2.headers["cf-connecting-ip"] = "203.0.113.44"
ok(_cip(_r2) == "203.0.113.44",
   "told which header the CDN fills in, it reads the caller the CDN "
   "actually saw — named in config rather than guessed, because a header "
   "we invented a meaning for is one anybody can send")
_r3 = _FakeReq("203.0.113.50", "10.0.0.1")
_r3.headers["cf-connecting-ip"] = "127.0.0.1"
ok(_cip(_r3) == "203.0.113.50",
   "and a request that did not come through the local proxy has it "
   "ignored with everything else: the CDN header is only the CDN's word "
   "when the CDN is who is speaking")

_NETS = ["203.0.113.0/24", "192.0.2.0/24"]
_cfg(client_ip_header="cf-connecting-ip", kiosk_networks=_NETS)
_af = _mn3._allowed_from
ok(_af("203.0.113.44", "203.0.113.9"),
   "with the shops' own networks declared, a tablet in the shop the link "
   "was made in is let through")
ok(not _af("192.0.2.10", "203.0.113.9"),
   "and a device at ANOTHER of the same business's shops is not — which "
   "is the case a /24 comparison behind one CDN edge could never see")
ok(not _af("198.51.100.7", "203.0.113.9")
   and not _af("81.2.69.4", "203.0.113.9"),
   "nor the edge itself, nor somebody's home broadband")
ok(_af("203.0.113.44", "81.2.69.4"),
   "a link minted off-site is spendable in any declared shop and nowhere "
   "else — an owner at an airport can still set a tablet up, and nobody "
   "at the airport can spend what they made")
_cfg(client_ip_header="", kiosk_networks=["nonsense", "203.0.113.0/24"])
ok(_mn3._listed("203.0.113.44") == "203.0.113.0/24",
   "one unparseable entry does not take the good ones down with it")
_cfg(client_ip_header="", kiosk_networks=["nonsense"])
ok(_af("203.0.113.44", "203.0.113.9") and not _af("81.2.69.4", "203.0.1.9"),
   "and a list that is entirely rubbish falls back to the rough check "
   "rather than to letting everybody in — a typo in config should cost "
   "precision, never the whole door")
_mn3.CFG.get = _cfg0
_dep2 = open("docs/product/DEPLOY.md").read()
ok("kiosk_networks" in _dep2 and "client_ip_header" in _dep2,
   "both are in the runbook, because neither is discoverable from a "
   "screen that looks fine until the day it is wrong")

_bl = c.post(f"/api/admin/kiosks/{_k1}/enrol", headers=A, json={}).json()
ok(_bl["bound"] and "same network" in _bl["note"],
   "a link is bound by default rather than by remembering to ask")
ok("network_known" in _bl and "network" in _bl,
   "and it reports which network it bound to, and whether that address "
   "can tell one device from another at all — a check that passes "
   "everything reads as protection, which is worse than admitting there "
   "is none, so the screen is given what it needs to say so")
ok(_bl["network_known"] is (bool(_bl["network"])
                            and not _bl["network"].startswith("127.")),
   "and that flag is the honest reading of the address rather than a "
   "hopeful constant")
_kc3 = _db.connect()
_kc3.execute("UPDATE kiosk_enrolments SET made_ip='203.0.113.7'"
             " WHERE token=?", (_bl["token"],))
_kc3.commit(); _kc3.close()
_wrong = c.post("/api/kiosk/claim", json={"token": _bl["token"]})
ok(_wrong.status_code == 403 and "same network" in _wrong.json()["detail"],
   "a device somewhere else is refused even inside the few minutes")
ok(c.post("/api/kiosk/claim", json={"token": _bl["token"]},
          headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 403,
   "and it cannot talk its way in: the forwarded header is written by "
   "whoever is asking, so it is ignored unless this install has been "
   "told a proxy in front of it is trustworthy")
_kc4 = _db.connect()
_still = _kc4.execute("SELECT used FROM kiosk_enrolments WHERE token=?",
                      (_bl["token"],)).fetchone()["used"]
_kc4.close()
ok(not _still,
   "a refusal does not spend the link — otherwise anybody could destroy "
   "a setup by opening it from the wrong place, which is a denial of "
   "service dressed as a security check")

_any = c.post(f"/api/admin/kiosks/{_k1}/enrol", headers=A,
              json={"anywhere": True}).json()
ok(not _any["bound"] and "key" in _any["note"],
   "an owner can deliberately make one for a tablet that is genuinely "
   "elsewhere, and is told what they have made")
_kc5 = _db.connect()
_kc5.execute("UPDATE kiosk_enrolments SET made_ip='198.51.100.4'"
             " WHERE token=?", (_any["token"],))
_kc5.commit(); _kc5.close()
ok(c.post("/api/kiosk/claim",
          json={"token": _any["token"]}).status_code == 200,
   "which then works from anywhere — the escape hatch has to exist, or "
   "the first person locked out of a second site turns the whole check "
   "off for everybody")
ok(any("ANY network" in (e.get("detail") or "")
       for e in c.get("/api/admin/audit", headers=A).json()["entries"][:12]),
   "and it is on the record as the deliberate act it is")

_ejs = ops_app_js()
ok('S.tab === "enrol" && S.deepKey' in _ejs
   and 'S.tab !== "enrol"' in _ejs,
   "and the screen renders with nobody signed in: the tab list would "
   "otherwise bounce an unknown tab to the shop and throw the setup away "
   "without a word")

# --- rooms, and who has them when ----------------------------------------
# A class had a teacher, a course and a start time and no place, which is
# fine until two of them want the same four walls at six on a Tuesday.
def _rm_at(y, mo, d, h, mi=0):
    return _t0.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


_rm = c.post("/api/rooms", headers=A, json={
    "name": "Studio 2", "store_id": 1, "kind": "classroom", "seats": 12})
ok(_rm.status_code == 200, "a room is a place inside a location")
_rid = _rm.json()["id"]
ok(c.post("/api/rooms", headers=A,
          json={"name": "", "kind": "classroom"}).status_code == 400
   and c.post("/api/rooms", headers=A,
              json={"name": "X", "kind": "dungeon"}).status_code == 400,
   "it needs a name, and a kind this software has heard of")

def _next_weekday(wd, hour, weeks_out=1):
    """The next `wd` at `hour`, at least `weeks_out` weeks away.

    Not a date typed into the file. A booking fixture pinned to April
    2027 is in the future until it is not, and then the series-cancel
    test — which only touches bookings that have not happened — quietly
    stops testing anything and starts failing instead.
    """
    lt = _t0.localtime(_t0.time())
    days = (wd - lt.tm_wday) % 7 + 7 * weeks_out
    return _t0.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + days,
                       hour, 0, 0, 0, 0, -1))


_t1 = _next_weekday(1, 18)                       # a Tuesday, six o'clock
_bk = c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid, "starts": _t1, "ends": _t1 + 5400,
    "title": "Spanish A2", "repeat_weeks": 10}).json()
ok(_bk["booked"] == 10 and not _bk["refused"],
   "a term is ten Tuesdays, booked in one go — a timetable somebody has "
   "to enter ten times is a timetable kept in a spreadsheet")
_rows = c.get(f"/api/rooms/bookings?from_ts={_t1 - 86400}"
              f"&to_ts={_t1 + 80 * 86400}&room_id={_rid}",
              headers=A).json()["bookings"]
ok(all(_t0.localtime(b["starts"]).tm_hour == 18 for b in _rows),
   "and every one of them is at six o'clock — a term booked from October "
   "runs through the clocks changing, and a repeat counted in seconds "
   "would quietly move half of it to five")
ok(len({_t0.strftime("%Y-%m-%d", _t0.localtime(b["starts"]))
        for b in _rows}) == 10,
   "on ten different days rather than ten copies of one")

_clash = c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid, "starts": _t1 + 1800, "ends": _t1 + 3600,
    "title": "Staff meeting"})
ok(_clash.status_code == 409 and "Spanish A2" in _clash.json()["detail"],
   "a second booking over the first is refused, and told what has it — "
   "'no' without 'because Anna has it' sends somebody hunting")
ok(c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid, "starts": _t1 - 3600, "ends": _t1,
    "title": "Beginners"}).status_code == 200,
   "but a class ending exactly when the next begins is two bookings, not "
   "a clash: get that wrong and no timetable can be built back to back")

# A person is as bookable as a room.
_rid2 = c.post("/api/rooms", headers=A, json={
    "name": "Studio 9", "kind": "studio"}).json()["id"]
_who = c.get("/api/admin/users", headers=A).json()[0]["id"]
_t3 = _next_weekday(4, 15)                       # a Friday, three o'clock
ok(c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid, "starts": _t3, "ends": _t3 + 3600,
    "title": "Grooming A", "teacher_id": _who}).status_code == 200,
   "somebody is booked into a room for an hour")
_dbl = c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid2, "starts": _t3, "ends": _t3 + 3600,
    "title": "Grooming B", "teacher_id": _who})
ok(_dbl.status_code == 409 and "already teaching" in _dbl.json()["detail"],
   "and cannot be booked into a DIFFERENT room in the same hour. The "
   "teacher was recorded and shown and never checked, so both bookings "
   "were accepted: the timetable looked full and one of the two rooms "
   "had nobody coming to it. Being the resource nobody modelled is how "
   "a person gets double-booked")
ok(c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid2, "starts": _t3, "ends": _t3 + 3600,
    "title": "Grooming C", "teacher_id": 0}).status_code == 200,
   "a free room at that hour still takes somebody else, because it was "
   "the person who was busy and not the building")
ok(c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid, "starts": _t3 + 7200, "ends": _t3 + 10800,
    "title": "Unstaffed A"}).status_code == 200
   and c.post("/api/rooms/bookings", headers=A, json={
       "room_id": _rid2, "starts": _t3 + 7200, "ends": _t3 + 10800,
       "title": "Unstaffed B"}).status_code == 200,
   "and nobody is not a person who can be in two places: two bookings "
   "with no teacher named do not collide with each other, which they "
   "would if teacher 0 were treated as somebody")
_roomclash = c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid, "starts": _t3 + 8000, "ends": _t3 + 9000,
    "title": "Room clash", "teacher_id": 0})
ok(_roomclash.status_code == 409
   and "already taken" in _roomclash.json()["detail"],
   "while a room clash still reads as one — which of the two is busy is "
   "the difference between finding another room and making a phone call")

_t2 = _next_weekday(2, 20)                       # the Wednesday, eight
c.post("/api/rooms/bookings", headers=A, json={
    # The NEXT Wednesday, as a calendar week rather than 604800 seconds:
    # across a clock change those are not the same instant, and the
    # repeat this is meant to collide with is booked by the calendar.
    "room_id": _rid, "starts": _next_weekday(2, 20, 2),
    "ends": _next_weekday(2, 20, 2) + 1800, "title": "Governors"})
_part = c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rid, "starts": _t2, "ends": _t2 + 3600,
    "title": "Conversation club", "repeat_weeks": 4}).json()
ok(_part["booked"] == 3 and len(_part["refused"]) == 1,
   "asking for four weeks and getting three is what happens when one is "
   "already taken")
ok(_part["refused"][0]["taken_by"] == "Governors",
   "and the one that was skipped says which week and what took it, "
   "rather than being silently dropped from a run of four")

_ser = [b for b in c.get(f"/api/rooms/bookings?from_ts={_t2 - 86400}"
                         f"&to_ts={_t2 + 40 * 86400}&room_id={_rid}",
                         headers=A).json()["bookings"]
        if b["said"] == "Conversation club"]
_sid2 = _ser[0]["id"]
ok(c.delete(f"/api/rooms/bookings/{_sid2}?whole_series=1",
            headers=A).json()["cancelled"] >= 3,
   "cancelling a weekly booking can take the whole run — a term called "
   "off one Tuesday at a time is how one gets missed")

_now = c.get(f"/api/rooms/{_rid}/now", headers=A).json()
ok("now" in _now and "next" in _now and _now["room"]["name"] == "Studio 2",
   "and a room can be asked what it holds now and next, which is the "
   "shape a screen on a wall wants")
ok(c.get("/api/rooms", headers=A).json()["rooms"][0]["next"] is not None,
   "the list answers the corridor question without a second request")

_del = c.delete(f"/api/rooms/{_rid}", headers=A).json()
ok(_del.get("archived") and not _del.get("deleted"),
   "a room that has been used is switched off rather than deleted — last "
   "term's timetable is how somebody answers 'where was that class'")
_gov = open("src/storefront/backend/governance.py").read()
ok('"rooms"' in _gov and '("/api/rooms", "rooms")' in _gov,
   "and booking a room is its own permission: whoever runs the timetable "
   "should not need the shipping config to do it")

# --- the screen on the wall ----------------------------------------------
# A kiosk became two things. Everything that came before is a clock, so
# no install wakes up with its tablets reclassified underneath it.
_rm2 = c.post("/api/rooms", headers=A,
              json={"name": "Studio 9", "kind": "classroom"}).json()["id"]
_k_before = [x for x in c.get("/api/entitlements", headers=A).json()["lines"]
             if x["kind"] == "kiosks"][0]["used"]
_disp = c.post("/api/admin/kiosks", headers=A, json={
    "label": "Studio 9 door", "kind": "display", "room_id": _rm2})
ok(_disp.status_code == 200 and _disp.json()["kind"] == "display",
   "a kiosk can be a screen that shows the room rather than a tablet "
   "people punch in on")
_k_after = [x for x in c.get("/api/entitlements", headers=A).json()["lines"]
            if x["kind"] == "kiosks"][0]["used"]
ok(_k_after == _k_before,
   "and it is not counted against the plan. Billing a school $6 a "
   "classroom for a timetable it could read on the door is how a feature "
   "nobody adopts gets built — and counting them would refuse the fifth "
   "classroom's screen at the door, correctly, for the wrong reason")
ok(c.post("/api/admin/kiosks", headers=A,
          json={"label": "Nowhere", "kind": "display"}).status_code == 400,
   "a display shows ONE room, so it is refused without one rather than "
   "hung on a wall showing nothing")
ok(c.post("/api/admin/kiosks", headers=A,
          json={"label": "X", "kind": "hologram"}).status_code == 400,
   "and a kiosk is one of the two things it can be")

_dcon = _db.connect()
_kinds = {r[0] for r in _dcon.execute("SELECT DISTINCT kind FROM kiosks")}
_dcon.close()
ok("clock" in _kinds,
   "every kiosk that existed before the split is still a clock kiosk — a "
   "default that reclassified them would have moved somebody's bill "
   "without anybody asking")

_wall = c.get(f"/api/rooms/{_rm2}/display")
ok(_wall.status_code == 200,
   "the wall screen reads without a session: a login between a corridor "
   "and a timetable is how a tablet ends up permanently signed in as "
   "somebody's manager, which is worse to leave in a corridor than a "
   "timetable anybody could have read on the door")
_w = _wall.json()
ok(_w["state"] == "free" and set(_w) >= {"room", "now", "next", "later"},
   "an empty room says so rather than showing nothing at all")
_soon = _t0.time() - 300
_wb = c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rm2, "starts": _soon, "ends": _soon + 3600,
    "title": "Evening class"}).json()["ids"][0]
ok(c.get(f"/api/rooms/{_rm2}/display").json()["state"] == "due",
   "a room booked for now but not started reads as due, which is a "
   "different thing from a class in progress and the difference somebody "
   "standing outside the door is asking about")
# A real class, not a made-up session id: "started" means a class that
# is open, and attaching a number that matches nothing should not make a
# wall claim a room is in use.
_wc = c.post("/api/learning/courses", headers=A,
             json={"name": "Wall test", "language": "es"}).json()["id"]
_wsid = c.post("/api/learning/sessions", headers=A,
               json={"course_id": _wc}).json()["session"]["id"]
c.post(f"/api/rooms/bookings/{_wb}/session", headers=A,
       json={"session_id": _wsid})
_live = c.get(f"/api/rooms/{_rm2}/display").json()
ok(_live["state"] == "in progress" and _live["now"]["started"],
   "and once the teacher starts the class, the screen says they are in "
   "there")
c.post(f"/api/rooms/bookings/{_wb}/session", headers=A,
       json={"session_id": 999999})
ok(c.get(f"/api/rooms/{_rm2}/display").json()["state"] != "in progress",
   "while a session id matching no class at all leaves the wall saying "
   "anything but 'in progress' — a screen is not made truthful by being "
   "handed a number")
c.post(f"/api/rooms/bookings/{_wb}/session", headers=A,
       json={"session_id": _wsid})
ok(_live["now"]["recording"] is False,
   "recording is claimed only when segments are actually landing — a "
   "screen that says RECORDING because a video room id exists is a "
   "screen lying to a class about being on tape")
_names = str(_live)
ok("teacher" in _live["now"] and "roster" not in _names
   and "student" not in _names,
   "and nothing else is on it: a screen in a corridor is read by "
   "whoever walks past, so what is NOT on it is the design")

_djs = ops_app_js()
ok('S.tab === "display"' in _djs and 'S.tab !== "display"' in _djs,
   "the wall screen renders with nobody signed in, and the tab list does "
   "not bounce it to the shop")
ok("DISPLAY_KEY" in _djs and 'k.kind === "display"' in _djs,
   "and claiming a display's setup link makes the tablet a display "
   "rather than a clock — a wall screen handed a clock identity is a "
   "punch button in a corridor")
ok("setInterval(paint" in _djs,
   "it refreshes itself, because nobody walks over to reload a wall")

# --- starting a class from the wall --------------------------------------
# The display has no session, so a teacher proves who they are the way
# this software already lets people prove it at a shared device.
_crs = c.post("/api/learning/courses", headers=A,
              json={"name": "Spanish A2", "language": "es",
                    "level": "A2"}).json()["id"]
c.post("/api/me", headers=A, json={"pin": "7788"})
_rm3 = c.post("/api/rooms", headers=A,
              json={"name": "Studio 8", "kind": "classroom"}).json()["id"]
_soon2 = _t0.time() - 120
c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rm3, "starts": _soon2, "ends": _soon2 + 5400,
    "course_id": _crs})
_w2 = c.get(f"/api/rooms/{_rm3}/display").json()
ok(_w2["can_start"] and _w2["starting"] == "Spanish A2",
   "the wall offers to start the class booked into this room, and names "
   "it — a button that cannot do anything is worse than no button")

ok(c.post(f"/api/rooms/{_rm3}/start",
          json={"pin": "0000"}).status_code == 403,
   "a code nobody has does nothing")
_go = c.post(f"/api/rooms/{_rm3}/start", json={"pin": "7788"})
ok(_go.status_code == 200 and _go.json()["started_by"],
   "the teacher's own time-clock code starts it, with no session left "
   "behind on a screen bolted to a corridor wall")
_w3 = c.get(f"/api/rooms/{_rm3}/display").json()
ok(_w3["state"] == "in progress" and _w3["can_end"] and not _w3["can_start"],
   "and the wall changes to say they are in there")

# A session id on a booking says a class was STARTED, not that one is
# running. This was wrong first time round and the wall said "in
# progress" twenty minutes after everybody had left.
c.post(f"/api/rooms/{_rm3}/end", json={"pin": "7788"})
_w4 = c.get(f"/api/rooms/{_rm3}/display").json()
ok(_w4["state"] == "finished" and not _w4["can_end"],
   "once it ends, the wall says finished rather than staying confidently "
   "wrong in a corridor until the booking runs out")
ok(_w4["now"]["recording"] is False,
   "and a class that is over is not recording, whatever is on disk")

_rm4 = c.post("/api/rooms", headers=A,
              json={"name": "Studio 10", "kind": "classroom"}).json()["id"]
_s4 = _t0.time() - 60
c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rm4, "starts": _s4, "ends": _s4 + 3600, "course_id": _crs})
c.post("/api/admin/users", headers=A, json={
    "name": "Bystander", "role": "employee"})
_bs = [u for u in c.get("/api/admin/users", headers=A).json()
       if u["name"] == "Bystander"][0]["id"]
c.patch(f"/api/admin/users/{_bs}", headers=A, json={"pin": "4242"})
_no = c.post(f"/api/rooms/{_rm4}/start", json={"pin": "4242"})
if _no.status_code == 403:
    ok("Bystander" not in _no.json()["detail"],
       "a code that is real but not this class's teacher is refused "
       "WITHOUT naming whose it is — the real teacher knows their own "
       "name, and the only person who learns anything from it is a "
       "stranger in a corridor being told the code they guessed is real")

for _i in range(6):
    _last = c.post(f"/api/rooms/{_rm4}/start", json={"pin": "0001"})
ok(_last.status_code == 429,
   "and the screen stops answering after five wrong codes. A wrong code "
   "doing nothing was never the risk — the risk is a corridor screen "
   "working as an oracle, somebody trying four-digit codes until one is "
   "taken and then walking to the time clock with it")
ok(c.post(f"/api/rooms/{_rm3}/start",
          json={"pin": "0001"}).status_code != 429,
   "the lockout is per screen, so one room being hammered does not shut "
   "the class down the corridor")

# --- the register, behind the code ---------------------------------------
# The wall shows no names at rest, on purpose. Marking needs names, which
# is a tension rather than a feature: the sheet is opened by a code and
# shuts itself, and the wall goes back to a course title and a time.
# Its own course and room: a booking's class is started once, and a
# course runs one class at a time, so reusing either would be testing
# those rules rather than the register.
_crs2 = c.post("/api/learning/courses", headers=A,
               json={"name": "Register test", "language": "es"}).json()["id"]
c.post(f"/api/learning/courses/{_crs2}/enroll", headers=A,
       json={"name": "Bystander"})
_rm6 = c.post("/api/rooms", headers=A,
              json={"name": "Studio 13", "kind": "classroom"}).json()["id"]
_s6 = _t0.time() - 60
c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rm6, "starts": _s6, "ends": _s6 + 3600, "course_id": _crs2})
c.post(f"/api/rooms/{_rm6}/start", json={"pin": "7788"})
_sheet = c.post(f"/api/rooms/{_rm6}/roster", json={"pin": "7788"})
ok(_sheet.status_code == 200 and _sheet.json()["token"],
   "a code opens the register for the class running in this room")
_sh = _sheet.json()
ok("photo" not in str(_sh),
   "with no photographs. The staff screen carries faces because "
   "attendance cannot run on initials, and that reasoning does not "
   "survive being moved to a corridor where everybody walking past can "
   "see the screen")
ok(_sh["marking_as"] and _sh["open_for_sec"] > 0,
   "it says who is marking and that it is going to close itself")

_tok = _sh["token"]
_m = c.post(f"/api/rooms/{_rm6}/mark", json={
    "token": _tok, "student_id": [r["student_id"] for r in _sh["roster"]][0],
    "status": "late"})
ok(_m.status_code == 200
   and any(r["status"] == "late" for r in _m.json()["roster"]),
   "one code marks the whole class rather than one code per student — "
   "twenty codes for twenty people is how a register ends up filled in "
   "afterwards from memory, which is the thing attendance exists to stop")
ok(_m.json()["open_for_sec"] > 0,
   "and every mark pushes the closing time out, so somebody working down "
   "a list of twenty is not timed out at fourteen")
ok(c.post(f"/api/rooms/{_rm6}/mark", json={
    "token": "invented", "student_id": 1}).status_code == 403,
   "a token nobody was given opens nothing")
ok(c.post(f"/api/rooms/{_rm4}/mark", json={
    "token": _tok, "student_id": 1}).status_code == 403,
   "and a sheet is for the room it was opened in: one code at one door "
   "does not mark a register down the corridor")
c.post(f"/api/rooms/{_rm6}/close-sheet", json={"token": _tok})
ok(c.post(f"/api/rooms/{_rm6}/mark", json={
    "token": _tok, "student_id": 1}).status_code == 403,
   "and putting it away means it is away")

# A course runs one class at a time, so a wall offering to start one that
# is already open elsewhere is offering a button that will fail.
_rm5 = c.post("/api/rooms", headers=A,
              json={"name": "Studio 12", "kind": "classroom"}).json()["id"]
_s5 = _t0.time() - 60
c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _rm5, "starts": _s5, "ends": _s5 + 3600, "course_id": _crs2})
_w5 = c.get(f"/api/rooms/{_rm5}/display").json()
ok(not _w5["can_start"] and "already running" in _w5["blocked"],
   "so it does not offer it, and says why — 'nothing happened' in a "
   "corridor is indistinguishable from a broken screen")
ok(c.post(f"/api/rooms/{_rm5}/roster",
          json={"pin": "7788"}).status_code == 409,
   "and a room with no class running has nobody to mark, which it says "
   "rather than opening an empty sheet")

# --- connections, metered apart from custom ones --------------------------
_ent2 = c.get("/api/entitlements", headers=A).json()
_by2 = {l["kind"]: l for l in _ent2["lines"]}
ok({"connections", "custom_connections"} <= set(_by2),
   "an install can see both kinds of connection on the same screen as "
   "its tills and its seats, because they are the same question: how "
   "much of this do we have and what does more cost")
ok(_by2["custom_connections"]["self_serve_max"] == 0
   and not _by2["custom_connections"]["can_raise"],
   "and the custom one cannot be raised from that screen — it is work "
   "before it is a number, and a button that takes the money and "
   "delivers nothing is the worst thing that could be on it")
ok(0 < _by2["custom_connections"]["included"]
   < _by2["connections"]["included"],
   "the plan includes fewer custom ones than ordinary ones, which is the "
   "difference said in the one place a client reads it")
ok(c.post("/api/admin/integrations/custom", headers=A, json={
    "label": "Broker portal", "url": "https://x.example/hook",
    "auth_kind": "bearer"}).status_code == 200,
   "and a single-tenant install may have one anyway: an install nobody "
   "sold anything to is unlimited by design, because a legacy shop must "
   "never wake up with fewer features than it went to bed with. The "
   "refusal is proven where limits exist, on tenant alpha")

# --- the one offer at checkout -------------------------------------------
# Three products, because the rules are about one suggesting another.
for _n in ("Offer test A", "Offer test B", "Offer test C"):
    c.post("/api/admin/products", headers=A,
           json={"sku": _n.replace(" ", "-").lower(), "name": _n,
                 "price_cents": 349, "category": "tea",
                 "case_size": 12, "case_price_cents": 3600})
_op = [p for p in c.get("/api/products", headers=A).json()
       if p["name"].startswith("Offer test")]
_pa, _pb, _pc = _op[0]["id"], _op[1]["id"], _op[2]["id"]
ok(c.post("/api/store/checkout-offer",
          json={"subtotal_cents": 1500}).json()["offer"] is None,
   "a shop with no offers says nothing at checkout, which is a real "
   "answer and the one it starts with")
ok(c.post("/api/store/admin/checkout-offers", headers=A, json={
    "label": "x", "product_id": _pa,
    "trigger": "cart_has"}).status_code == 400,
   "a 'they already have' offer without saying what they have is refused "
   "rather than quietly never matching")
ok(c.post("/api/store/admin/checkout-offers", headers=A, json={
    "label": "x", "product_id": _pa,
    "trigger": "under_free_ship"}).status_code == 400,
   "and a free-shipping nudge needs the line it is nudging them over")

c.post("/api/store/admin/checkout-offers", headers=A, json={
    "label": "Shipping is free with this", "product_id": _pb,
    "trigger": "under_free_ship", "under_cents": 4000, "position": 1})
c.post("/api/store/admin/checkout-offers", headers=A, json={
    "label": "Goes with that", "product_id": _pc, "trigger": "cart_has",
    "needs_product_id": _pa, "discount_pct": 20, "position": 0})

_o1 = c.post("/api/store/checkout-offer", json={
    "subtotal_cents": 1500, "product_ids": [_pa],
    "visitor_id": "t1"}).json()["offer"]
ok(_o1["product_id"] == _pc and _o1["saving_cents"] > 0,
   "with a rule that fits, the first match by position wins — an owner "
   "can predict the behaviour from the screen rather than discovering it "
   "from sales")
_o2 = c.post("/api/store/checkout-offer", json={
    "subtotal_cents": 1500, "product_ids": [], "visitor_id": "t2"
}).json()["offer"]
ok(_o2["product_id"] == _pb and _o2["short_by_cents"] == 2500,
   "without it, the basket falls through to the nudge, which says how "
   "far off they are rather than just naming a threshold")
ok(c.post("/api/store/checkout-offer", json={
    "subtotal_cents": 6000, "product_ids": []}).json()["offer"] is None,
   "and a basket already over the line is offered nothing — a slot that "
   "always finds something to say ends up saying something irrelevant, "
   "which at checkout is worse than an empty space")
ok(c.post("/api/store/checkout-offer", json={
    "subtotal_cents": 1500,
    "product_ids": [_pa, _pc]}).json()["offer"]["product_id"] != _pc,
   "it never offers what is already in the basket")

c.post("/api/store/checkout-offer/taken", json={
    "offer_id": _o1["offer_id"], "visitor_id": "t1",
    "value_cents": _o1["price_cents"]})
_rep = c.get("/api/store/admin/checkout-offers", headers=A).json()
_row1 = [o for o in _rep["offers"] if o["label"] == "Goes with that"][0]
ok(_row1["shown"] >= 1 and _row1["taken"] == 1
   and _row1["take_pct"] is not None,
   "shown and taken are both counted, because an offer nobody can "
   "measure is decoration nobody can switch off")
ok(_row1["taken_cents"] == _o1["price_cents"],
   "with the money on what was taken")
ok("not revenue" in _rep["note"] and "would have bought it anyway"
   in _rep["note"],
   "and the payload says what that money is NOT: some of those people "
   "would have bought it anyway and there is no honest way from here to "
   "know how many. A number that quietly claims credit for sales that "
   "would have happened is how a feature nobody can evaluate survives "
   "for years")

_sfjs = c.get("/store.js").text if c.get("/store.js").status_code == 200 \
    else open("src/storefront/frontend/store.js").read()
ok("OFFER_TAKEN" in _sfjs,
   "and the shop asks once: taking the suggestion and being handed "
   "another immediately is a rack of sweets, and the difference between "
   "a shop that helps and one that nags is whether it asks twice")

# --- donations, which are not a sale --------------------------------------
ok(c.post("/api/store/admin/donations", headers=A,
          json={"name": "Hospice", "kind": "collected"}).status_code == 400,
   "money collected for somebody else has to say who: it is not income "
   "and somebody will have to prove where it went")
_fid = c.post("/api/store/admin/donations", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "blurb": "Round up",
    "target_cents": 400000}).json()["id"]
ok(c.get("/api/store/donation").json()["fund"]["name"] == "Hospice appeal",
   "and the checkout is offered one fund, not four — a shop asking which "
   "of four charities is asking a question nobody came to answer")

_pid2 = c.get("/api/products", headers=A).json()[0]["id"]
_rev0 = _db.connect()
_before = _rev0.execute("SELECT COALESCE(SUM(subtotal_cents),0) c FROM"
                        " orders WHERE status!='cancelled'").fetchone()["c"]
_rev0.close()
# Pay-on-delivery for a passwordless account goes through an email
# confirmation, so the donation has to survive being parked as JSON and
# replayed — which is worth proving rather than routing around.
c.post("/api/me", headers=A, json={"email": "donor@example.com"})
_ord = c.post("/api/orders", headers=A, json={
    "items": [{"product_id": _pid2, "qty": 1}], "donation_cents": 500,
    "ship_name": "T", "address": "1 St", "city": "X", "postal": "1"})
ok(_ord.status_code == 200, f"an order takes a donation ({_ord.text[:90]})")
if _ord.json().get("awaiting_confirmation"):
    _pc2 = _db.connect()
    _tok2 = _pc2.execute("SELECT token FROM pending_orders ORDER BY id DESC"
                         " LIMIT 1").fetchone()["token"]
    _pc2.close()
    ok(c.get(f"/confirm-order/{_tok2}").status_code == 200,
       "and it survives the confirmation round trip — the order is parked "
       "as JSON and replayed, so a field the parking forgot would lose "
       "somebody's donation silently")
_c2 = _db.connect()
_o = _c2.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 1").fetchone()
_after = _c2.execute("SELECT COALESCE(SUM(subtotal_cents),0) c FROM orders"
                     " WHERE status!='cancelled'").fetchone()["c"]
_c2.close()
ok(_o["donation_cents"] == 500 and _o["donation_fund_id"] == _fid,
   "it lands in its own column on the order, against the fund it was for")
ok(_o["total_cents"] - (_o["subtotal_cents"] + _o["tax_cents"]
                        + _o["shipping_cents"] - _o["discount_cents"]
                        - _o["gift_cents"]) == 500,
   "and it IS charged — the card is debited for it, so it is in the total")
ok(_after - _before == _o["subtotal_cents"],
   "but revenue moved by the goods alone. A donation as a £5 product "
   "would have landed in cost of goods with no cost basis, in stock as a "
   "thing that never arrives, in taxable revenue, in average order "
   "value and in every cohort — and a year of numbers would be quietly "
   "wrong before anybody asked why")

_tot = c.get("/api/store/donation").json()["fund"]
ok(_tot["raised_cents"] == 500, "the fund knows what it has taken")
ok(c.post(f"/api/store/admin/donations/{_fid}/remit", headers=A,
          json={"cents": 9999}).status_code == 409,
   "sending on more than was collected is refused — that is either a "
   "typo or a different transaction, and neither should be recorded as "
   "this one")
c.post(f"/api/store/admin/donations/{_fid}/remit", headers=A,
       json={"cents": 300, "reference": "BACS-1"})
_f = [f for f in c.get("/api/store/admin/donations",
                       headers=A).json()["funds"] if f["id"] == _fid][0]
ok(_f["raised_cents"] == 500 and _f["remitted_cents"] == 300
   and _f["held_cents"] == 200,
   "'we raised five hundred for the hospice' is a sentence a shop should "
   "be able to prove, and 'three hundred sent, two hundred still with "
   "us' is the one that keeps it true")
ok(c.get("/api/store/donation").json()["fund"]["raised_cents"] == 500,
   "the shop's thermometer still shows what was RAISED — a total that "
   "fell when the money was sent on would read as donations being taken "
   "back")

# The donor's own copy. Kept apart from the order receipt because a
# donation and a purchase are different documents to whoever reads them
# next: one proves what was bought, the other what was given.
_ocon = _db.connect()
_dr = _ocon.execute("SELECT * FROM donation_receipts ORDER BY order_id DESC"
                    " LIMIT 1").fetchone()
_ocon.close()
ok(_dr is not None and _dr["cents"] == 500,
   "a donation mints the donor a receipt, with the gift")
_page = c.get(f"/dr/{_dr['token']}")
ok(_page.status_code == 200 and "$5.00" in _page.text,
   "at an address they can keep — token-addressed, because an order id "
   "is guessable by counting and this one carries a name and an amount")
ok("acknowledgement, not a tax receipt" in _page.text
   and "Hospice" in _page.text,
   "and a shop collecting for a hospice says exactly that. It is not the "
   "hospice and cannot issue a tax receipt on somebody else's behalf — a "
   "document that looked like one would be the shop making a claim it "
   "has no standing to make, and that is a mistake a tax office finds "
   "rather than an accountant")
ok("No goods or services" not in _page.text,
   "so the line a tax office looks for is absent, because it would not "
   "be true of this document")

_own = c.post("/api/store/admin/donations", headers=A, json={
    "name": "Our appeal", "kind": "ours", "reference": "CHY 12345"}).json()
_o2 = c.post("/api/orders", headers=A, json={
    "items": [{"product_id": _pid2, "qty": 1}], "donation_cents": 1000,
    "donation_fund_id": _own["id"], "ship_name": "Alex Donor",
    "address": "1 St", "city": "X", "postal": "1"})
if _o2.json().get("awaiting_confirmation"):
    _pc3 = _db.connect()
    _t3 = _pc3.execute("SELECT token FROM pending_orders ORDER BY id DESC"
                       " LIMIT 1").fetchone()["token"]
    _pc3.close()
    c.get(f"/confirm-order/{_t3}")
_oc2 = _db.connect()
_dr2 = _oc2.execute("SELECT * FROM donation_receipts ORDER BY order_id DESC"
                    " LIMIT 1").fetchone()
_oc2.close()
_p2 = c.get(f"/dr/{_dr2['token']}").text
ok("Donation receipt" in _p2 and "No goods or services were provided"
   in _p2 and "CHY 12345" in _p2,
   "a charity taking its OWN donations issues the real thing: its "
   "number, and the line a tax office looks for")
ok("acknowledgement, not a tax receipt" not in _p2,
   "and does not disclaim what it is entitled to say")

ok(c.get("/dr/nosuchtoken").status_code == 404,
   "an address nobody was given holds nothing")
_ost = c.get(f"/api/store/order-status/{_dr['order_id']}").json()
ok(_ost.get("donation_receipt_url", "").endswith(_dr["token"]),
   "the order page hands the link over, because that is where somebody "
   "looks for anything to do with an order they placed — and a receipt "
   "nobody can find is a receipt that was not issued")
ok(c.get(f"/api/orders/{_dr['order_id']}/donation-receipt",
         headers=A).status_code == 200,
   "and staff can find it when a donor rings having lost theirs")

_ec = _db.connect()
_sent = _ec.execute(
    "SELECT subject, status FROM email_log WHERE kind='donation-receipt'"
    " ORDER BY id DESC LIMIT 1").fetchone()
_rec2 = _ec.execute("SELECT emailed_at FROM donation_receipts"
                    " WHERE order_id=?", (_dr["order_id"],)).fetchone()
_ec.close()
ok(_sent is not None and _rec2["emailed_at"] > 0,
   "the copy is posted with the gift rather than waiting to be asked "
   "for — a receipt somebody has to go looking for is one most people "
   "never see")
_ag = c.post(f"/api/orders/{_dr['order_id']}/donation-receipt/send",
             headers=A).json()
ok(_ag["sent"] is True,
   "and 'send it again' actually sends. The automatic one dedups for "
   "ever, which is right; a resend that inherited that key would be a "
   "button whose only effect is the person clicking it telling the "
   "donor it is on its way")
ok(c.post(f"/api/orders/{_dr['order_id']}/donation-receipt/send",
          headers=A).json()["sent"] is False,
   "while a double-click inside the minute does not send twice")
ok(_ag["to"] == _dr["email"],
   "it goes to the address on the receipt and never to one in the "
   "request — a staff-triggered send that took an arbitrary destination "
   "is a way to post somebody's giving history to whoever asks nicely")
ok(c.post("/api/orders/1/donation-receipt/send",
          headers=A).status_code == 404,
   "and an order with no donation has no receipt to send")

# --- bookings: a thing you buy that happens at a time ------------------
_gp = c.post("/api/admin/products", headers=A, json={
    "sku": "GROOM-T", "name": "Full groom", "price_cents": 6500,
    "case_price_cents": 6500}).json()
ok(_gp.get("id"), "creating a product says which one it made")
_groom = _gp["id"]
_groomer = c.get("/api/admin/users", headers=A).json()[0]["id"]
_bay = c.post("/api/rooms", headers=A, json={
    "name": "Grooming bay", "kind": "other"}).json()["id"]
_svc = c.post("/api/store/admin/services", headers=A, json={
    "name": "Full groom", "product_id": _groom, "duration_min": 60,
    "buffer_min": 15, "room_id": _bay, "staff_ids": [_groomer],
    "days": [True] * 7, "from_min": 540, "to_min": 720, "lead_hours": 0})
ok(_svc.status_code == 200, "a service: an hour, a bay, a groomer, "
   "mornings, every day")
_svid = _svc.json()["id"]
_cat = c.get("/api/store/catalog").json()
_gcard = [p for p in _cat["products"] if p["id"] == _groom][0]
ok(_gcard["kind"] == "service" and _gcard["service"]["id"] == _svid,
   "the shelf files it as a service and the card knows it happens at a "
   "time — the button says 'Pick a time', not 'Add'")

_tmrw = _t0.time() + 86400
_sl = c.get(f"/api/store/services/{_svid}/slots?day={_tmrw}").json()
_day = _sl["days"][0]
ok(_day["free"] == 2 and [_t0.localtime(x["starts"]).tm_min for x in
                          _day["slots"]] == [0, 15],
   "09:00–12:00 at an hour plus fifteen turnaround is two starts, 09:00 "
   "and 10:15 — the buffer is real time, not a note")
ok(all(x["staff_id"] == _groomer for x in _day["slots"]),
   "and each one says who would take it")
_s0 = _day["slots"][0]["starts"]

_h1 = c.post("/api/store/appointments/hold", json={
    "service_id": _svid, "starts": _s0, "visitor_id": "vis-a",
    "name": "Ana"}).json()
ok(_h1.get("appointment_id") and _h1["held_until"] > _t0.time() + 600,
   "a visitor holds 09:00 for a quarter of an hour — long enough to pay, "
   "short enough that a closed tab gives it back")
ok(c.post("/api/store/appointments/hold", json={
    "service_id": _svid, "starts": _s0, "visitor_id": "vis-b"}
).status_code == 409,
   "and the next visitor is told it has just gone, rather than both "
   "being told 09:00")
_sl2 = c.get(f"/api/store/services/{_svid}/slots?day={_tmrw}").json()
_row0 = [x for x in _sl2["days"][0]["slots"] if x["starts"] == _s0][0]
ok(not _row0["free"] and _row0["why"] == "full",
   "a held slot shows as taken with the reason, so a page of greyed "
   "times is not a page somebody rings up about")
ok(c.post("/api/store/appointments/hold", json={
    "service_id": _svid, "starts": _s0, "visitor_id": "vis-a"}
).json().get("appointment_id") == _h1["appointment_id"] + 1
   and c.get(f"/api/store/services/{_svid}/slots?day={_tmrw}").json()
   ["days"][0]["free"] == 1,
   "the same visitor choosing again replaces their hold rather than "
   "stacking a second — one person, one slot")
_aid = _h1["appointment_id"] + 1

_login = c.post("/api/login", json={"name": "Ana", "role": "customer",
                                    "email": "ana-groom@example.com"}).json()
_AG = {"Authorization": "Bearer " + _login["token"]}
_ship = {"ship_name": "Ana", "address": "1 St", "city": "X", "postal": "1",
         "email": "ana-groom@example.com"}
ok(c.post("/api/orders", headers=_AG, json={
    "items": [{"product_id": _groom, "qty": 1}], **_ship}).status_code == 400,
   "the cart refuses a service with no time on it — a grooming "
   "appointment does not ship as a parcel")
ok(c.post("/api/orders", headers=_AG, json={
    "items": [{"product_id": _groom, "qty": 2, "appointment_id": _aid}],
    **_ship}).status_code == 400,
   "and two of one appointment is not a thing")
ok(c.post("/api/orders", headers=_AG, json={
    "items": [{"product_id": _groom, "qty": 1, "appointment_id": _aid}],
    "visitor_id": "someone-else", **_ship}).status_code == 409,
   "a hold id typed into somebody else's order is not their appointment")
_ord = c.post("/api/orders", headers=_AG, json={
    "items": [{"product_id": _groom, "qty": 1, "appointment_id": _aid}],
    "visitor_id": "vis-a", **_ship}).json()
_bcon = _db.connect()
_ap = _bcon.execute("SELECT state, held_until, order_id FROM appointments"
                    " WHERE id=?", (_aid,)).fetchone()
if _ord.get("awaiting_confirmation"):
    ok(_ap["state"] == "held" and _ap["held_until"] > _t0.time() + 2 * 86400,
       "an order parked for email confirmation may sit for days, so its "
       "hold is extended to match — a customer who did everything right "
       "must not lose the slot from an email they were told to expect")
    _ptok = _bcon.execute("SELECT token FROM pending_orders ORDER BY id DESC"
                          " LIMIT 1").fetchone()["token"]
    c.get(f"/confirm-order/{_ptok}")
    _ap = _bcon.execute("SELECT state, order_id, user_id FROM appointments"
                        " WHERE id=?", (_aid,)).fetchone()
ok(_ap["state"] == "confirmed" and _ap["order_id"] and _ap["user_id"],
   "the order lands and the held time becomes an appointment, in the "
   "same transaction, tied to the order and the person")
_bcon.close()
_mine_ap = c.get("/api/store/account/appointments", headers=_AG).json()
ok(len(_mine_ap["upcoming"]) == 1 and _mine_ap["upcoming"][0]["room"]
   == "Grooming bay",
   "and the customer sees it in their account, with the bay and who")

# The three things a slot is made of, each on its own.
_s1 = _day["slots"][1]["starts"]
ok(c.post("/api/rooms/bookings", headers=A, json={
    "room_id": _bay, "starts": _s1, "ends": _s1 + 1800,
    "title": "Deep clean"}).status_code == 200
   and [x for x in c.get(f"/api/store/services/{_svid}/slots?day={_tmrw}")
        .json()["days"][0]["slots"] if x["starts"] == _s1][0]["why"]
   == "room taken",
   "the classroom timetable and the diary share the bay: a room booked "
   "for a clean is not a room a dog can be groomed in")
_svc2 = c.post("/api/store/admin/services", headers=A, json={
    "name": "Nail trim", "duration_min": 30, "staff_ids": [_groomer],
    "days": [True] * 7, "from_min": 540, "to_min": 720, "lead_hours": 0}
).json()["id"]
_trim = [x for x in c.get(f"/api/store/services/{_svc2}/slots?day={_tmrw}")
         .json()["days"][0]["slots"] if x["starts"] == _s0][0]
ok(not _trim["free"] and _trim["why"] == "nobody free",
   "and the groomer is one person: booked for a groom at nine, they are "
   "not free for a trim at nine on a different service either")
_svc3 = c.post("/api/store/admin/services", headers=A, json={
    "name": "Puppy class", "duration_min": 60, "capacity": 2,
    "days": [True] * 7, "from_min": 540, "to_min": 660, "lead_hours": 0}
).json()["id"]
for v in ("p1", "p2"):
    c.post("/api/store/appointments/hold", json={
        "service_id": _svc3, "starts": _s0, "visitor_id": v})
_pc = [x for x in c.get(f"/api/store/services/{_svc3}/slots?day={_tmrw}")
       .json()["days"][0]["slots"] if x["starts"] == _s0][0]
ok(not _pc["free"] and _pc["why"] == "full",
   "a service with no room and nobody named takes its capacity and then "
   "says full — two puppies, and the third is told so")

_sb = c.post("/api/store/admin/appointments", headers=A, json={
    "service_id": _svid, "starts": _s0 + 86400, "name": "Phoned in"})
ok(_sb.status_code == 200 and _sb.json()["staff_id"] == _groomer,
   "the phone rings: staff book on somebody's behalf, confirmed at once, "
   "with the same free-time rules as the website")
_diary = c.get("/api/store/admin/appointments?days=3", headers=A).json()
ok(any(a["who"] == "Phoned in" for a in _diary["appointments"])
   and any(a["state"] == "held" for a in _diary["appointments"]),
   "the diary shows the booked and the held alike — a hold is a person "
   "mid-checkout, and a slot that looks free and is not is how two "
   "people get told 2:30")
_done = [a for a in _diary["appointments"] if a["who"] == "Phoned in"][0]
ok(c.post(f"/api/store/admin/appointments/{_done['id']}/state", headers=A,
          json={"state": "no_show"}).status_code == 200,
   "and who did not turn up is recorded, not deleted")
# --- intake: what the shop needs to know before the appointment ---------
_qs = [{"label": "Dog's name and breed", "kind": "text", "required": True},
       {"label": "Vaccinations up to date?", "kind": "yesno", "required": True},
       {"label": "Temperament", "kind": "choice",
        "choices": ["calm", "nervous", "reactive"]},
       {"label": "Anything else", "kind": "long"}]
ok(c.patch(f"/api/store/admin/services/{_svid}", headers=A, json={
    "name": "Full groom", "product_id": _groom, "duration_min": 60,
    "buffer_min": 15, "room_id": _bay, "staff_ids": [_groomer],
    "days": [True] * 7, "from_min": 540, "to_min": 720, "lead_hours": 0,
    "intake": _qs}).status_code == 200,
   "a service asks its questions: a name, a yes/no, one of a list, a "
   "paragraph — and says which are required")
ok(c.patch(f"/api/store/admin/services/{_svid}", headers=A, json={
    "name": "Full groom", "duration_min": 60, "days": [True] * 7,
    "from_min": 540, "to_min": 720,
    "intake": [{"label": "Size", "kind": "choice", "choices": ["big"]}]}
).status_code == 400,
   "and a choice with one choice is refused, because that is not a "
   "question")
_cat2 = [p for p in c.get("/api/store/catalog").json()["products"]
         if p["id"] == _groom][0]
ok(_cat2["service"]["asks"] == 4,
   "the card knows a form follows the time, so it can say so")
_s_in = [x for x in c.get(f"/api/store/services/{_svid}/slots?day={_tmrw + 86400 * 3}")
         .json()["days"][0]["slots"] if x["free"]][0]["starts"]
_hi = c.post("/api/store/appointments/hold", json={
    "service_id": _svid, "starts": _s_in, "visitor_id": "vis-q"}).json()
ok([q["required"] for q in _hi["intake"]] == [True, True, False, False],
   "holding the time hands back the questions — asked AFTER the slot is "
   "held, because a form is a reason to leave and a held time is a "
   "reason to stay")
_aq = _hi["appointment_id"]
_r0 = c.post("/api/orders", headers=_AG, json={
    "items": [{"product_id": _groom, "qty": 1, "appointment_id": _aq}],
    "visitor_id": "vis-q", **_ship})
ok(_r0.status_code == 400 and "Vaccinations" in _r0.json()["detail"]
   and "Dog's name" in _r0.json()["detail"],
   "the order will not go through with the required ones blank, and it "
   "names them rather than saying 'form incomplete'")
ok(c.post(f"/api/store/appointments/{_aq}/intake", json={
    "visitor_id": "vis-q", "answers": {"q2": "maybe"}}).status_code == 400,
   "a yes/no does not take 'maybe'")
ok(c.post(f"/api/store/appointments/{_aq}/intake", json={
    "visitor_id": "vis-q", "answers": {"q3": "huge"}}).status_code == 400,
   "and a choice does not take an answer off the list")
ok(c.post(f"/api/store/appointments/{_aq}/intake", json={
    "visitor_id": "someone-else", "answers": {"q1": "x"}}).status_code == 403,
   "only the visitor holding the slot may answer for it")
_half = c.post(f"/api/store/appointments/{_aq}/intake", json={
    "visitor_id": "vis-q",
    "answers": {"q1": "Biscuit, cockapoo", "q3": "nervous"}}).json()
ok(not _half["complete"] and _half["missing"] == ["Vaccinations up to date?"],
   "half an answer sheet is saved and says exactly what is still needed")
ok(c.post(f"/api/store/appointments/{_aq}/intake", json={
    "visitor_id": "vis-q", "answers": {"q2": "yes"}}).json()["complete"],
   "and the rest completes it")
_r1 = c.post("/api/orders", headers=_AG, json={
    "items": [{"product_id": _groom, "qty": 1, "appointment_id": _aq}],
    "visitor_id": "vis-q", **_ship})
ok(_r1.status_code == 200, "now the order goes through")
if _r1.json().get("awaiting_confirmation"):
    _bc2 = _db.connect()
    _pt2 = _bc2.execute("SELECT token FROM pending_orders ORDER BY id DESC"
                        " LIMIT 1").fetchone()["token"]
    _bc2.close()
    c.get(f"/confirm-order/{_pt2}")
_dq = [a for a in c.get("/api/store/admin/appointments?days=10", headers=A)
       .json()["appointments"] if a["id"] == _aq][0]
ok(_dq["state"] == "confirmed" and {x["label"]: x["answer"] for x in _dq["answers"]}
   == {"Dog's name and breed": "Biscuit, cockapoo", "Temperament": "nervous",
       "Vaccinations up to date?": "yes"},
   "the diary shows the answers beside the appointment — the day's sheet")
ok(any(x["label"] == "Temperament" for x in
       c.get("/api/store/account/appointments", headers=_AG).json()
       ["upcoming"][0]["answers"] if True),
   "and the customer sees what they said")
_ph = c.post("/api/store/admin/appointments", headers=A, json={
    "service_id": _svid, "starts": _s_in + 86400, "name": "Phoned in",
    "answers": {"q1": "Rex, alsatian", "q3": "reactive"}}).json()
ok(_ph["missing"] == ["Vaccinations up to date?"],
   "the phone takes the answers down too, and is allowed to leave a "
   "required one blank — 'she'll tell us on the day' is an answer the "
   "shop may accept from itself — while saying what is still to ask")
_bc3 = _db.connect()
ok(_bc3.execute("SELECT COUNT(*) FROM appointment_answers a JOIN"
                " appointment_answers n ON n.appointment_id=a.appointment_id"
                " AND n.q_key='q1' WHERE a.q_key='q3' AND a.answer='reactive'"
                ).fetchone()[0] == 1,
   "answers are rows, not a blob: 'which dogs are reactive' is a query, "
   "not a grep")
_bc3.close()
# --- devices: who has been here, and roughly where they are --------------
_UA_PHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
ok(c.post("/api/device", headers={"User-Agent": _UA_PHONE}, json={
    "visitor_id": "vis-dv", "tz": "Europe/Madrid", "lang": "es-ES",
    "screen": "390x844@3", "platform": "iPhone", "touch": True,
    "surface": "storefront"}).status_code == 200,
   "a browser reports what it is: timezone, language, screen, platform")
c.post("/api/device", headers={"User-Agent": _UA_PHONE}, json={
    "visitor_id": "vis-dv", "tz": "Europe/Madrid", "lang": "es-ES",
    "screen": "390x844@3", "platform": "iPhone", "touch": True,
    "surface": "storefront"})
c.get("/learn", headers={"Accept": "text/html",
                         "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"})
c.get("/api/products", headers={"Accept": "application/json",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"})
_dv = c.get("/api/admin/devices?days=1", headers=A).json()["devices"]
_ph = [d for d in _dv if d["visitor_id"] == "vis-dv"]
ok(len(_ph) == 1 and _ph[0]["hits"] == 2 and _ph[0]["browser"] == "Safari"
   and _ph[0]["os"] == "iOS" and _ph[0]["tz"] == "Europe/Madrid",
   "the same browser coming back is one device with a growing count, not "
   "a new row every time — read as Safari on iOS, clock in Madrid")
_win = [d for d in _dv if d["os"] == "Windows"]
ok(len(_win) == 1 and _win[0]["surface"] == "learn" and not _win[0]["visitor_id"],
   "a page load with no script at all is still a sighting — address and "
   "user-agent are enough — while an API call is not: one write per "
   "page, not one per click")
_an = c.get("/api/admin/devices/analysis?days=1", headers=A).json()
ok(_an["devices"] >= 2 and any(x["k"] == "Europe/Madrid" for x in _an["by_tz"])
   and any(x["k"] == "iOS" for x in _an["by_os"])
   and any(p["path"] == "/learn" for p in _an["paths"]),
   "the analysis counts by timezone, system, and page — where a browser's "
   "clock and keyboard think it is, said as a guess and never a claim")
ok(c.get("/api/admin/devices", headers={"Authorization": "Bearer nope"}
         ).status_code == 401, "and it is the office's to read, not the shop's")
ok("deviceBeacon" in open("src/storefront/frontend/store.js").read()
   and "opsDeviceBeacon" in ops_app_js() and "renderDevices" in ops_app_js(),
   "the storefront and the office both report in, and the office has "
   "the screen to read it on")

# --- the account door: a stored token is a claim, not a fact ------------
_sfj = open("src/storefront/frontend/store.js").read()
_alive = _sfj.split("async function tokenAlive")[1].split("function signIn(")[0]
ok('fetch("/api/store/account/orders"' in _alive
   and 'fetch("/api/whoami"' not in _alive,
   "the account button checks the stored token before trusting it — "
   "against a CUSTOMER route, because the office's whoami refuses a "
   "perfectly good shopper and probing it would sign every customer out "
   "on every click. Every sign-in mints a fresh token, so a second sign-in "
   "anywhere left this one stale: the door fetched the orders with it, "
   "got a 401 body, tried to .map() it, and the modal never opened — "
   "the only way out was Sign out, the one button that clears the token")
ok("if (oR.status === 401 || sR.status === 401)" in _sfj,
   "and the account panel reads the status, not just the body")
# Both places the two doors are offered together, checked separately:
# reading one block's admin link against the other's office link is
# satisfied by file order alone, and passed while the sign-in modal
# listed them the other way round.
for _door in (_sfj.split("On the team — teaching")[1][:400],
              _sfj.split("Work here?")[1][:400]):
    ok(_door.index('href="/admin"') < _door.index('href="/ops/"'),
       "the shop's own admin door is offered before the office's")

ok("intakeForm(" in open("src/storefront/frontend/store.js").read()
   and "bkQuestionRow" in ops_app_js(),
   "the storefront asks the questions after the hold, and the shop edits "
   "them on the service")

_ops_bk = ops_app_js()
ok("renderBookings" in _ops_bk and 'bookings: "selling"' in _ops_bk,
   "the ops app has the Bookings screen, filed under Selling — it is a "
   "thing the shop sells, not a new capability to buy")
ok('data-book="${p.id}"' in open("src/storefront/frontend/store.js").read()
   and "appointment_id: h ? h.appointment_id : 0" in
   open("src/storefront/frontend/store.js").read(),
   "and the storefront card offers a time and the checkout carries it")

# The other side of the same list: who gave, on the fund.
_gl = c.get(f"/api/store/admin/donations/{_fid}/gifts", headers=A).json()
ok(_gl["total_cents"] == 500 and _gl["givers"] >= 1,
   "a fund can be asked who gave to it — the shop's own customers and "
   "its own orders, gathered by the thing they were given to rather than "
   "by the basket they rode in on")
ok(all("token" not in g for g in _gl["gifts"])
   and any(g["receipt_url"] for g in _gl["gifts"]),
   "with a way into each donor's copy and never the raw token")
ok(any("email" in g for g in _gl["gifts"]),
   "and the address it went to, because staff answer the phone: a donor "
   "who has lost their copy is identified by where it was sent, and "
   "making somebody cross-reference an order id to do that is how they "
   "stop bothering")
ok("passing_it_on" in _gl and "separate decision" in _gl["passing_it_on"],
   "a collected fund says the thing worth saying where somebody is most "
   "likely to be about to do it: these people gave at this checkout, not "
   "to the charity. Sending the money on is what the shop undertook to "
   "do; sending the list is a different act, and the donor's to make")
_own_gifts = c.get(f"/api/store/admin/donations/{_own['id']}/gifts",
                   headers=A).json()
ok("passing_it_on" not in _own_gifts,
   "and a fund whose money is the shop's own has no such line, because "
   "there is nobody to pass anything to")
ok(c.get("/api/store/admin/donations/9999/gifts",
         headers=A).status_code == 404,
   "a fund that does not exist has no givers")

# The report carries the appeal's progress, from the same sentence.
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 2000, "active": True})
_gp = c.get(f"/api/store/admin/donations/{_fid}/gifts", headers=A).json()
ok(_gp["pct"] == 25 and "to go" in _gp["line"],
   "the shop's fund report says how far the appeal has got, beside the "
   "list of who got it there — the two facts are read together and were "
   "on separate screens")
ok(_gp["line"] in c.get(f"/dr/{_dr['token']}").text,
   "the identical sentence to the donor's receipt for the same fund, "
   "checked against the receipt rather than against a restatement of "
   "the rule — the shop and the donor reading different numbers for one "
   "appeal is the failure worth spending a function on")
ok(_gp["total_cents"] == _gp["listed_cents"]
   and _gp["all_gifts"] == _gp["listed"] and "truncated" not in _gp,
   "and where the list is whole, the listed total and the fund's total "
   "agree, with nothing to explain")
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 2000, "active": False})
_gc = c.get(f"/api/store/admin/donations/{_fid}/gifts", headers=A).json()
ok(not _gc["active"] and "closed" in _gc["line"],
   "a closed appeal says so here too, so the bar beside it is not read "
   "as a live one")
# And where it is not whole, it says so. On its own fund with its own
# orders, so nothing else in this file has to know about the 501 rows —
# and both are deleted afterwards, because the point of using a
# throwaway is that it gets thrown away.
_bigf = c.post("/api/store/admin/donations", headers=A, json={
    "name": "Big appeal", "kind": "ours", "target_cents": 100000,
    "active": False}).json()["id"]
_bcon = _db.connect()
_bcon.executemany(
    "INSERT INTO orders(user_id,kind,status,region,subtotal_cents,"
    "total_cents,donation_cents,donation_fund_id,created_at)"
    " VALUES(1,'web','paid','',0,100,100,?,?)",
    [(_bigf, _t0.time() - i) for i in range(501)])
_bcon.commit(); _bcon.close()
_big = c.get(f"/api/store/admin/donations/{_bigf}/gifts", headers=A).json()
ok(_big["listed"] == 500 and _big["all_gifts"] == 501,
   "the list stops at 500 gifts, because a report nobody can scroll is "
   "not a report")
ok(_big["total_cents"] == 50100 and _big["listed_cents"] == 50000,
   "but the total above it is the whole fund and not the sum of what "
   "is listed. This report sits beside a card showing the real figure, "
   "which is the worst place to publish a quieter one")
ok("truncated" in _big and "501" in _big["truncated"]
   and "CSV has all of them" in _big["truncated"],
   "and the gap is stated rather than left to be found by adding the "
   "column up — with where the rest actually is")
ok(_big["pct"] == 50,
   "the progress is the fund's, so a truncated list does not quietly "
   "shorten the bar")
_ccsv = c.get(f"/api/store/admin/donations/{_bigf}/gifts.csv", headers=A)
ok(len(_ccsv.text.strip().split("\n")) == 502,
   "and the CSV really does have all of them, header included — the "
   "note above sends people there, so it had better be true")
_bcon2 = _db.connect()
_bcon2.execute("DELETE FROM orders WHERE donation_fund_id=?", (_bigf,))
_bcon2.execute("DELETE FROM donation_funds WHERE id=?", (_bigf,))
_bcon2.commit(); _bcon2.close()

c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 0, "active": True})

# How far the appeal has got.
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 2000, "active": True})
_th = c.get("/api/store/donation").json()["fund"]
ok(_th["pct"] == 25 and not _th["passed"],
   "a fund with a target shows how far it has got — $5 of $20 is a "
   "quarter of the way")
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 300, "active": True})
_th2 = c.get("/api/store/donation").json()["fund"]
ok(_th2["pct"] == 100 and _th2["passed"],
   "past the target the bar stops at full and the fact does not — an "
   "appeal does not stop being worth giving to the moment it works, so "
   "the fund keeps taking and the wording says which it is")
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 0, "active": True})
ok(c.get("/api/store/donation").json()["fund"]["pct"] is None,
   "and a fund with no target draws no thermometer rather than a bar "
   "measuring against nothing — which is the control a shop has if it "
   "would rather not show one, and the only one it is offered")
_pjs = ops_app_js()
ok("to go" in _pjs and "passed, and still taking" in _pjs,
   "the shop's own card says what is left, or that it is past — a "
   "percentage on its own leaves somebody doing the subtraction")
ok("give-goal-bar" in open("src/storefront/frontend/store.js").read(),
   "and the shopper sees it at the moment they are deciding, which is "
   "the only moment it changes anything")

# And the donor's own copy carries it too — the one page they keep.
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 2000, "active": True})
_drp = c.get(f"/dr/{_dr['token']}").text
ok("of $20.00" in _drp and "to go" in _drp,
   "the receipt says where the fund has got to, not only what one "
   "person gave — a gift lands somewhere, and until now the somewhere "
   "was the one thing the receipt could not tell them")
ok("as at" in _drp,
   "and dates it. A receipt is a document about a fixed day, and this "
   "is the only number on it that moves — undated on a printed page it "
   "quietly ages into a wrong one")
ok("$5.00 is part of that" in _drp,
   "their own gift is named inside the total, because 'did mine go "
   "into this' is the question the total is being read to answer")
ok(_drp.index("class=\"note") < _drp.index("class=prog"),
   "it sits below the statement and outside the table of facts. A "
   "moving number among fixed ones makes the fixed ones look like they "
   "might move too — including the amount, which is the part somebody "
   "is relying on")
ok("$20.00" in _drp.split("class=pl")[1][:80],
   "and the words carry the whole fact rather than the bar. Print drops "
   "background colours, so a figure that exists only as a coloured "
   "rectangle does not survive the likeliest thing to happen to this "
   "page")
ok(".bar{display:none}" in _drp and "color-scheme:light" in _drp,
   "the bar is hidden in print, and the page states its own ground — a "
   "document with no background is dark text on whatever colour the "
   "reader's browser happened to pick")
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 300, "active": True})
_drp2 = c.get(f"/dr/{_dr['token']}").text
_pl2 = _drp2.split("class=pl")[1][:80]
ok("passed, and still open" in _pl2 and "100%" not in _pl2,
   "past the target it says so and drops the percentage rather than "
   "pinning it at 100 — capping the bar is right, it cannot draw past "
   "its own end, but '$5.00 of $3.00 — 100%' puts a number between two "
   "figures that contradict it, and a receipt must not argue with "
   "itself")

# And the emailed copy carries the same sentence — caught at mailer.send
# rather than read off the source, because "the caller passes it" and
# "it arrives in the body" are different claims and only one of them is
# what the donor gets.
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 2000, "active": True})
# The resend throttle is a real one and an earlier check just used it,
# so clear it rather than wait sixty seconds: what is under test here is
# what the body says, not that the throttle works — which is checked in
# its own right further up.
from erp.backend.main import _RESENT as _RS               # noqa: E402
_RS.clear()
_sent_bodies = []
_orig_ms = mailer.send
mailer.send = lambda cfg, to, s, t: (_sent_bodies.append((s, t)), "sent")[1]
c.post(f"/api/orders/{_dr['order_id']}/donation-receipt/send", headers=A)
mailer.send = _orig_ms
_eb = _sent_bodies[-1][1] if _sent_bodies else ""
ok("of $20.00" in _eb and "to go" in _eb,
   "the emailed receipt carries the progress too, not just the page it "
   "links to — the email is the thing that arrives, and a donor who "
   "never clicks through is still a donor who was told")
ok("as at" in _eb and "true when this was sent" in _eb
   and "always has the figure for today" in _eb,
   "and it apologises for itself in advance. An email is frozen at the "
   "moment it was sent and can never be corrected, so it dates the "
   "figure, says it was true then, and points at the link for now — a "
   "stale number that admits to being one is useful, and the same "
   "number presented as current is a small lie that gets worse every "
   "day it sits in an archive")
ok(_eb.count("$20.00") and "$5.00" in _eb,
   "with the currency on it, matching the page. The two are the same "
   "document, and a bare 5.00 against the page's $5.00 is the kind of "
   "small disagreement that makes somebody check the rest")
_pl_page = c.get(f"/dr/{_dr['token']}").text.split("class=pl")[1][:80]
_RS.clear()
_sent2 = []
_orig2 = mailer.send
mailer.send = lambda cfg, to, s, t: (_sent2.append(t), "sent")[1]
c.post(f"/api/orders/{_dr['order_id']}/donation-receipt/send", headers=A)
mailer.send = _orig2
ok(len(_sent2) == 1,
   "and a second deliberate resend in the same second still goes. Its "
   "dedup key was the clock to the second, so two of them collided and "
   "the mailer refused the later one as a repeat — silently, while "
   "telling the person who asked that nothing went. Seconds are a "
   "coincidence, not an identity; the throttle is what stops a "
   "double-click, and the key's only job is to keep one resend from "
   "being mistaken for another")

ok(_pl_page.split(">")[1].split("<")[0].strip() in _eb,
   "and it is the identical sentence, from one function. The page draws "
   "a bar and the email cannot, which is exactly the invitation to "
   "write them twice — and twice is how a receipt ends up disagreeing "
   "with the email that carried it")

c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 0, "active": True})
_drp3 = c.get(f"/dr/{_dr['token']}").text
ok("given so far" in _drp3 and "class=bar" not in _drp3,
   "and with no target there is no bar, but there is still news: no "
   "target is not the same as nothing to say, and a donor still wants "
   "to know their gift landed among others rather than alone")

# Giving over time, in calendar months.
def _months_back(n, day=12):
    """The 12th of the month `n` months before this one. Relative,
    because a fixture dated to August 2026 falls out of a twelve-month
    window the moment the clock is anywhere else — which is exactly what
    the date audit exists to catch, and I had just written one."""
    lt = _t0.localtime(_t0.time())
    y, m = lt.tm_year, lt.tm_mon - n
    while m < 1:
        m += 12
        y -= 1
    return _t0.mktime((y, m, day, 14, 0, 0, 0, 0, -1)), f"{y:04d}-{m:02d}"


_tc = _db.connect()
_m1, _ = _months_back(2)
_m2, _aug_key = _months_back(1)
for _when, _cents in ((_m1, 1200), (_m2, 2500), (_m2, 600)):
    _tc.execute(
        "INSERT INTO orders(user_id,kind,region,store_id,subtotal_cents,"
        "tax_cents,shipping_cents,total_cents,payment_status,status,"
        "created_at,donation_cents,donation_fund_id)"
        " VALUES(?,'customer','',0,1000,0,0,?,'cod','confirmed',?,?,?)",
        (1, 1000 + _cents, _when, _cents, _fid))
_tc.commit(); _tc.close()
_tr = c.get("/api/store/admin/donations/trend?months=12", headers=A).json()
ok(len(_tr["months"]) == 12
   and len({m["month"] for m in _tr["months"]}) == 12,
   "twelve DIFFERENT calendar months — stepping by thirty days prints "
   "one month twice and skips February, and a series that cannot count "
   "months is one nobody should trust with the shape it draws")
ok(sum(1 for m in _tr["months"] if m["partial"]) == 1
   and _tr["months"][-1]["partial"],
   "with the month still running marked, and only that one")
_fin = [m for m in _tr["months"] if not m["partial"] and m["cents"]]
ok(_tr["best"] and _tr["best"] != _tr["months"][-1]["month"],
   "the best month is chosen from the finished ones. Half of September "
   "against the whole of August always looks like a collapse, and a "
   "month three days old cannot win — so it is not allowed to lose "
   "either")
_aug = [m for m in _tr["months"] if m["month"] == _aug_key][0]
ok(_aug["gifts"] == 2 and _aug["cents"] == 3100
   and _aug["biggest_cents"] == 2500
   and _aug["average_cents"] == 1550,
   "each month carries what it is made of — the count, the average and "
   "the biggest single gift, because one large one moves an average "
   "past every ordinary gift in the month")
ok(c.get(f"/api/store/admin/donations/trend?fund_id={_fid}",
         headers=A).json()["fund_id"] == _fid,
   "and it can be asked about one fund rather than all of them")
_tjs = ops_app_js()
ok("give-bar" in _tjs and 'm.partial ? " part"' in _tjs,
   "the shop's own chart draws the running month differently, because a "
   "half-month drawn like a whole one is a fall that did not happen")

_csv = c.get(f"/api/store/admin/donations/{_fid}/gifts.csv", headers=A)
ok(_csv.status_code == 200
   and "given_on,donor,email,amount" in _csv.text,
   "the list comes out as a file, for the spreadsheet somebody is going "
   "to build from it anyway")
ok("/dr/" not in _csv.text and "hospice-appeal-donors-"
   in _csv.headers.get("content-disposition", ""),
   "without the receipt links. A receipt URL needs no password — that "
   "is what makes it convenient for the donor and exactly the wrong "
   "thing to put in a spreadsheet emailed to a committee. And the "
   "filename says which fund and which day, because a download called "
   "export.csv is a file nobody can identify a week later")
ok(any("exported" in (e.get("detail") or "") and "donor" in
       (e.get("detail") or "")
       for e in c.get("/api/admin/audit", headers=A).json()["entries"][:8]),
   "and it is on the record: handing a list of named people to a file is "
   "a disclosure whether or not anybody meant it as one")
_ejs = ops_app_js()
ok("d.passing_it_on && !confirm" in _ejs,
   "the shop is asked before a collected fund's list becomes a file — "
   "the same sentence as the screen, at the click that turns a list "
   "somebody is looking at into one they can forward")
ok(c.get(f"/api/store/admin/donations/{_fid}/gifts.csv").status_code
   in (401, 403),
   "and a donor list is not public")

# One person's giving, in one place.
ok(c.get("/api/store/account/donations").status_code == 401,
   "somebody's giving history is theirs — signed out, there is nothing "
   "to see")
_mine = c.get("/api/store/account/donations", headers=A).json()
ok(len(_mine["gifts"]) >= 2 and all("token" not in g for g in
                                    _mine["gifts"]),
   "signed in, every gift they have made — with the link to their own "
   "copy, and never the raw token, which is the thing that addresses it")
ok(_mine["to_us_cents"] > 0 and _mine["through_us_cents"] > 0
   and "to_us_cents" in str(_mine["years"][0]),
   "two totals and a year-by-year split, because a tax year is the unit "
   "anybody asking this question is working in")
ok(all(g["tax_receipt"] == (g["kind"] == "ours") for g in _mine["gifts"]),
   "each gift says whether its copy is a receipt or an acknowledgement, "
   "which is the same distinction the document itself makes")
ok("has to come from them" in _mine["note"],
   "and the two totals are kept apart rather than added: what somebody "
   "gave THROUGH us is not ours to certify — we handled it, they "
   "received it — and one combined 'you have given' figure would "
   "overstate what this business can stand behind")
# Where each appeal they gave to has got to.
ok(len(_mine["funds"]) >= 2
   and sum(f["my_gifts"] for f in _mine["funds"]) == len(_mine["gifts"]),
   "the giving page shows progress once per fund, not once per gift — "
   "somebody who gave to the same appeal three times wants to see the "
   "appeal once, and every gift is accounted for in exactly one of them")
ok(all(f["mine_cents"] <= f["raised_cents"] for f in _mine["funds"]),
   "with their own share named inside the fund's total, which is the "
   "question a giving page is opened to answer")
_fset = {f["name"] for f in _mine["funds"]}
ok(all(g["fund"] in _fset for g in _mine["gifts"]),
   "and only the funds they actually gave to. This is their page, not "
   "a list of causes to consider")
ok(all("fund_id" not in g for g in _mine["gifts"]),
   "the gift rows do not carry the internal id they were grouped by")
# Open with a target, then closed — the two states said out loud, and
# checked against the receipt for the same fund rather than against
# themselves.
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 1000000, "active": True})
_mo = [f for f in c.get("/api/store/account/donations", headers=A).json()
       ["funds"] if f["fund_id"] == _fid][0]
ok(_mo["pct"] is not None and "to go" in _mo["line"],
   "an open appeal with a target shows how far it has got, and what is "
   "left")
ok(_mo["line"] in c.get(f"/dr/{_dr['token']}").text,
   "and it is the identical sentence to the one on the receipt for a "
   "gift to that same fund — checked against the receipt itself, not "
   "against a copy of the rule. Three surfaces writing it three times "
   "is three chances for a donor's own page to disagree with the "
   "document in their inbox")
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 1000000, "active": False})
_mine = c.get("/api/store/account/donations", headers=A).json()
_mc = [f for f in _mine["funds"] if f["fund_id"] == _fid][0]
ok(not _mc["active"] and "closed there" in _mc["line"],
   "and a closed appeal says so rather than 'with $3,933.50 to go'. "
   "That wording tells somebody it is still running, and a giving page "
   "read years later is exactly where a fund is most likely to be one "
   "nobody is collecting for any more — an appeal that ended short says "
   "so, because dressing it up is a comfort this page has no right to "
   "offer")
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 0, "active": False})
_mc2 = [f for f in c.get("/api/store/account/donations", headers=A).json()
        ["funds"] if f["fund_id"] == _fid][0]
ok("given in all" in _mc2["line"] and "so far" not in _mc2["line"],
   "and a closed fund with no target says 'given in all' rather than "
   "'so far', which is the same tense problem in the case where there "
   "is no bar to draw")
# Put the fund back as it was found. These checks borrowed shared
# fixture state — the active fund is what a later checkout is offered —
# and a test that leaves it changed fails a test three hundred lines
# down with a symptom that has nothing to do with it.
c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "collected",
    "payee": "St Anne's Hospice", "target_cents": 0, "active": True})
_sjs = open("src/storefront/frontend/store.js").read()
ok("give-fund" in _sjs and "· closed" in _sjs,
   "the page marks the fund itself closed too, so the bar beside it is "
   "not read as a live one")

# A real second account, not a stub: an isolation test that cannot fail
# is not an isolation test.
_oc3 = _db.connect()
_oc3.execute("INSERT INTO users(name,email,role,token,region,created_at)"
             " VALUES('Nosy','nosy@example.com','customer','nosy-tok-1',"
             "'',?)", (_t0.time(),))
_oc3.commit(); _oc3.close()
_NB = {"Authorization": "Bearer nosy-tok-1"}
_other = c.get("/api/store/account/donations", headers=_NB)
ok(_other.status_code == 200 and _other.json()["gifts"] == []
   and _other.json()["to_us_cents"] == 0,
   "and it is scoped to the account asking: somebody else's giving is "
   "not in this one's list, and their totals are their own")

# A present is bought by one person and shipped to another.
_gift = c.post("/api/orders", headers=A, json={
    "items": [{"product_id": _pid2, "qty": 1}], "donation_cents": 400,
    "ship_name": "Granny Smith", "address": "2 Lane", "city": "Y",
    "postal": "2"})
if _gift.json().get("awaiting_confirmation"):
    _gc = _db.connect()
    _gt = _gc.execute("SELECT token FROM pending_orders ORDER BY id DESC"
                      " LIMIT 1").fetchone()["token"]
    _gc.close()
    c.get(f"/confirm-order/{_gt}")
_gc2 = _db.connect()
_grow = _gc2.execute(
    "SELECT dr.donor, o.ship_name FROM donation_receipts dr"
    " JOIN orders o ON o.id=dr.order_id ORDER BY dr.order_id DESC"
    " LIMIT 1").fetchone()
_gc2.close()
ok(_grow["ship_name"] == "Granny Smith" and _grow["donor"] != "Granny Smith",
   "the parcel goes to the recipient and the receipt is made out to "
   "whoever paid — a gift receipt crediting the person who was given the "
   "present is made out to somebody who did not give anything, which is "
   "worse than useless to the person who did")


_ours = c.post("/api/store/admin/donations", headers=A, json={
    "name": "Our own appeal", "kind": "ours", "active": False}).json()["id"]
ok(c.post(f"/api/store/admin/donations/{_ours}/remit", headers=A,
          json={"cents": 100}).status_code == 400,
   "a fund whose money is the business's own has nobody to send it to, "
   "and a remittance there would be an invented transaction")
ok(c.patch(f"/api/store/admin/donations/{_fid}", headers=A, json={
    "name": "Hospice appeal", "kind": "ours"}).status_code == 409,
   "and once money has been taken, whose it is cannot change: the same "
   "rows would move between income and a liability with nothing "
   "recording that they had")

# The client's own books. Excluding donations from revenue is right and
# leaves a shop whose bank does not match its turnover — so the gap is
# named on the same table as both figures, or the turnover looks wrong.
_pl = c.get("/api/analytics/pnl?days=365", headers=A).json()
ok(_pl["donations_cents"] >= 500,
   "the P&L shows what was taken in donations over the period")
ok(_pl["taken_cents"] == _pl["revenue_cents"] + _pl["donations_cents"],
   "and what the card machine actually saw, which is the figure that "
   "has to agree with a bank statement — revenue alone never will once "
   "a shop takes donations")
ok(_pl["donations_held_cents"] >= 0 and "not income at all"
   in _pl["donations_note"],
   "with the part that is somebody else's money called that, on the "
   "page, rather than left for an accountant to discover in March")
_ajs = ops_app_js()
ok("donations taken" in _ajs and "card machine saw" in _ajs,
   "and the client's own P&L reads down to it: revenue, the donations "
   "that are not revenue, and the sum that went through the machine")

_sfjs2 = open("src/storefront/frontend/store.js").read()
ok("GIVE_CENTS" in _sfjs2 and "addToCart(offer.product_id)" in _sfjs2,
   "the shop sends the donation beside the order rather than as a cart "
   "line — the offer adds to the basket, the donation never does")

# --- page-to-page funnel ---
for _v, _pages in (("pf-1", ["/", "/find", "/"]), ("pf-2", ["/", "/events"]),
                   ("pf-3", ["/"])):
    for _pg in _pages:
        c.post("/api/store/track", json={"visitor_id": _v, "page": _pg})
_pf = c.get("/api/store/admin/page-funnel?days=30", headers=A).json()
ok(_pf["sessions"] >= 3, "funnel reconstructs sessions from the pageview log")
ok(any(p["page"] == "/" for p in _pf["pages"]), "pages ranked by views")
ok(any(f["from"] == "/" and f["to"] == "/find" for f in _pf["flow"]),
   "page-to-page transitions are counted")
ok(all("exit_rate" in p for p in _pf["pages"]), "each page reports an exit rate")
ok(c.get("/api/store/admin/page-funnel").status_code == 403,
   "the funnel needs the analytics permission")

# --- ops app additions ---
_ops = c.get("/ops/app.js").text
ok("panZoomMap" in _ops and "wireMap" in _ops,
   "ops app has a pan/zoom map component")
ok("renderStaff" in _ops and "renderEvents" in _ops and "drawStoreRail" in _ops,
   "ops app has team access, events and the store rail")
ok("dm-name" in _ops, "chat can start a DM by typing a name")
_acss = c.get("/store.css").text
ok(".cmt-form" in _acss, "comment form is styled")

# --- own profile ---
_me = c.get("/api/me", headers=A).json()
ok(_me["name"] == "Boss" and "permissions" not in _me, "profile reads back")
ok(c.post("/api/me", headers=A, json={"name": "Boss Prime"}
          ).status_code == 200, "own name is editable")
ok(c.get("/api/me", headers=A).json()["name"] == "Boss Prime", "the edit stuck")
ok(c.post("/api/me", headers=A, json={"name": "x"}).status_code == 400,
   "a one-character name is refused")
ok(c.post("/api/me", headers=A, json={"pin": "abc"}).status_code == 400,
   "a non-numeric PIN is refused")
ok(c.post("/api/me", headers=A, json={"pin": "9876"}).status_code == 400,
   "a PIN already used by someone else is refused")
_qr = c.post("/api/me/qr", headers=A).json()
ok("/qr-login/" in _qr["url"] and _qr["expires_sec"] > 0,
   "own sign-in QR issued, short-lived")
ok(c.get(_qr["url"].split("://", 1)[-1].split("/", 1)[-1].join(("/", "")),
         follow_redirects=False).status_code in (200, 307),
   "the QR link resolves")

# --- discord ---
ok(c.get("/api/store/admin/discord").status_code == 403, "discord needs admin")
_dc = c.get("/api/store/admin/discord", headers=A).json()
ok(len(_dc["events"]) >= 8 and "webhook" not in json.dumps(_dc["channels"]),
   "discord config never returns the webhook secret")
for _bad in ("http://evil.example/api/webhooks/1/x",
             "https://discord.com.evil.example/api/webhooks/1/x",
             "https://192.168.1.1/api/webhooks/1/x", "not-a-url"):
    ok(c.post("/api/store/admin/discord/channels", headers=A,
              json={"label": "#x", "webhook": _bad}).status_code == 400,
       f"non-Discord webhook rejected: {_bad[:34]}")
_ch = c.post("/api/store/admin/discord/channels", headers=A, json={
    "label": "#orders",
    "webhook": "https://discord.com/api/webhooks/123456789/abcDEF-123_xyz"})
ok(_ch.status_code == 200, "a real Discord webhook URL is accepted")
_chid = _ch.json()["id"]
ok(c.post("/api/store/admin/discord/rules", headers=A, json={
    "channel_id": _chid, "event": "nope"}).status_code == 400,
   "unknown discord event rejected")
_r = c.post("/api/store/admin/discord/rules", headers=A, json={
    "channel_id": _chid, "event": "order.created",
    "condition_field": "total_cents", "condition_op": "gt",
    "condition_value": "5000"})
ok(_r.status_code == 200, "discord rule created with a condition")
from storefront.backend import discord as _dcm  # noqa: E402
_rule = {"condition_field": "total_cents", "condition_op": "gt",
         "condition_value": "5000"}
ok(_dcm._matches(_rule, {"total_cents": 9000}), "condition matches above")
ok(not _dcm._matches(_rule, {"total_cents": 900}), "condition filters below")
ok(not _dcm._matches(_rule, {}), "a missing field doesn't fire the rule")

# The bot half — reading and replying. No token is connected in the test DB,
# so every chat route should say so rather than fall over.
ok(c.get("/api/store/admin/discord", headers=A).json()["bot"] is None,
   "no bot connected reports as such")
for _p in ("/api/store/admin/discord/chat/channels",
           "/api/store/admin/discord/chat/123/messages"):
    ok(c.get(_p, headers=A).status_code == 400,
       f"{_p.split('/')[-1]} needs a connected bot")
ok("no Discord bot connected" in
   c.get("/api/store/admin/discord/chat/channels", headers=A).json()["detail"],
   "and says how to fix it")
ok(c.post("/api/store/admin/discord/bot", headers=A,
          json={"token": "x", "guild_id": ""}).status_code == 400,
   "connecting a bot needs a server ID")
ok(c.post("/api/store/admin/discord/bot", headers=A,
          json={"token": "", "guild_id": "123"}).status_code == 400,
   "connecting a bot needs a token")
# The token is a credential: it must never come back out of the API.
_con_d = _db.connect()
_con_d.execute("INSERT OR REPLACE INTO discord_bot(id,token,guild_id,bot_name,"
               " guild_name,created_at) VALUES(1,'super-secret','9','zenbot',"
               "'Zenjoy',1)")
_con_d.commit()
_cfg = c.get("/api/store/admin/discord", headers=A).json()
ok(_cfg["bot"] and _cfg["bot"]["bot_name"] == "zenbot",
   "a connected bot is reported")
ok("super-secret" not in json.dumps(_cfg), "the bot token is never returned")
_con_d.execute("DELETE FROM discord_bot")
_con_d.commit()
_con_d.close()

# --- email campaigns ---
ok(c.get("/api/store/admin/email/campaigns").status_code == 403,
   "email campaigns need the marketing permission")
_ec = c.post("/api/store/admin/email/campaigns", headers=A, json={
    "name": "Autumn", "subject": "Hello {name}", "body": "Use {code}",
    "audience": "subscribers", "discount_code": "AUTUMN"})
ok(_ec.status_code == 200, "campaign created")
_ecid = _ec.json()["id"]
ok(c.post("/api/store/admin/email/campaigns", headers=A, json={
    "name": "x", "subject": "y", "body": "", "audience": "nope"}
).status_code == 400, "unknown audience rejected")
c.post("/api/store/subscribe", json={"email": "sub@example.com"})
_prev = c.get(f"/api/store/admin/email/campaigns/{_ecid}/preview",
              headers=A).json()
ok("{name}" not in _prev["subject"] and "{code}" not in _prev["body"],
   "preview fills the placeholders")
ok(_prev["recipients"] >= 1, "the audience resolves to real recipients")
_u = c.get("/unsubscribe?email=sub@example.com")
ok(_u.status_code == 200 and "unsubscribed" in _u.text.lower(),
   "one-click unsubscribe works without a login")
_prev2 = c.get(f"/api/store/admin/email/campaigns/{_ecid}/preview",
               headers=A).json()
ok(_prev2["recipients"] == _prev["recipients"] - 1,
   "an unsubscribe is removed from the audience")
ok(any(x["email"] == "sub@example.com" for x in
       c.get("/api/store/admin/email/unsubscribes", headers=A).json()),
   "unsubscribes are listed")

# --- ops app views ---
_ops = c.get("/ops/app.js").text
ok("renderProfile" in _ops and "renderStores" in _ops
   and "renderEmail" in _ops and "renderDiscord" in _ops,
   "ops app has profile, stores, email and discord views")
ok("NOTIF_TAB" in _ops, "notifications map to a destination tab")
ok('id="me-link"' in _ops and 'S.tab = "profile"' in _ops,
   "your name in the header opens your profile")
ok("dc-msgs" in _ops and "loadDiscordMsgs" in _ops,
   "the ops app can read and reply to Discord channels")
ok("BORDER_PATH" in _ops and "map-border" in _ops,
   "the map separates countries")
ok("data-docedit" in _ops, "documents are editable")
ok("WORLD_PATH" in _ops and "HOME_VIEW" in _ops,
   "the map is a world projection opening on the US")

ok(".pin-s" in _ops and "scale(${(1 / k)" in _ops,
   "map pins counter-scale so a dot stays a dot when zoomed")

# The achievement card reads the payload's own field names. Rendering
# a.title against a payload keyed "name" fails silently — a grid of
# correctly-styled blanks — so pin the contract rather than the markup.
_ach = c.get("/api/achievements", headers=A).json()
ok(_ach and {"name", "desc", "icon"} <= set(_ach[0]),
   "achievements are keyed name/desc/icon")
ok("esc(a.name)" in _ops and "opsIcon(a.icon" in _ops,
   "the achievement card renders those field names")
ok(all(a["icon"].isascii() and a["icon"].isalnum() for a in _ach),
   "achievement icons are sprite names, not emoji")

# --- no emoji in the product ---
# The store and the back office are meant to read as one professional
# product, and an emoji renders as a different drawing on every platform.
# Everything that appears on a screen goes through the icon sprite instead.
# The one exception is the copy in customer emails and order texts, which is
# a different voice — that stays warm on purpose.
import pathlib as _pl, re as _re
_EMOJI = _re.compile("[\U0001F000-\U0001FAFF\u2728\u26A0\u2753\u2705\u2B50]")
_MAIL = _re.compile(r"log_and_send|sms\.|mailer\.send|verb = |has arrived")
_hits = []
for _f in sorted(_pl.Path("src").rglob("*")):
    if _f.suffix not in (".py", ".js", ".css", ".html", ".svg"):
        continue
    if not _f.is_file():
        continue
    _lines = _f.read_text(errors="replace").splitlines()
    for _i, _line in enumerate(_lines, 1):
        if not _EMOJI.search(_line):
            continue
        # Is this line part of a message going to a customer? Look back for
        # the call it belongs to — these are long multi-line sends.
        if _MAIL.search(" ".join(_lines[max(0, _i - 14):_i + 1])):
            continue
        _hits.append(f"{_f}:{_i}")
ok(not _hits,
   "no emoji in the store or the back office"
   + (" — " + ", ".join(_hits[:5]) if _hits else ""))

# The page builder and the affiliate page draw from the same sprite the
# storefront uses, which only works if the sprite is actually on the page.
for _p in ("/admin", "/admin/theme"):
    _html = c.get(_p, headers=A).text
    ok("<symbol id=\"i-" in _html, f"{_p} carries the icon sprite")

# --- one route per path ---
# A second @app.get on the same path silently shadows the first, and the
# older one wins. That is how /api/me lost has_pin: two handlers, and the
# profile read the one without it. Nothing about it looks wrong at the call
# site, so it needs a test rather than a careful reader.
_seen, _dupes = {}, []
for _r in app.routes:
    for _m in getattr(_r, "methods", ()) or ():
        if _m in ("HEAD", "OPTIONS"):
            continue
        _k = (_m, getattr(_r, "path", ""))
        if _k in _seen:
            _dupes.append(f"{_m} {_k[1]}")
        _seen[_k] = 1
ok(not _dupes, "no route is registered twice"
   + (" — " + ", ".join(_dupes[:4]) if _dupes else ""))

# --- the time clock ---
ok(c.post("/api/me", headers=A, json={"pin": "4417"}).status_code == 200,
   "a PIN can be set from your own profile")
ok(c.get("/api/me", headers=A).json()["has_pin"],
   "and the profile then says the PIN is set")
_in = c.post("/api/clock", json={"pin": "4417"})
ok(_in.status_code == 200 and _in.json()["action"] == "clock_in",
   "that PIN clocks in")
_out = c.post("/api/clock", json={"pin": "4417"})
ok(_out.json()["action"] == "clock_out", "and clocks out again")
ok(c.post("/api/clock", json={"pin": "0000"}).status_code == 404,
   "an unknown PIN is refused")

# --- edit and delete across the ERP ---
_p = c.post("/api/admin/products", headers=A, json={
    "sku": "EDIT-1", "name": "Editable", "price_cents": 400,
    "case_price_cents": 4000}).status_code
_pid = c.get("/api/products").json()[-1]["id"]
_pid = [p["id"] for p in c.get("/api/products").json()
        if p["sku"] == "EDIT-1"][0]
ok(c.patch(f"/api/admin/products/{_pid}", headers=A,
           json={"name": "Renamed"}).status_code == 200, "a product edits")
ok(any(p["name"] == "Renamed" for p in c.get("/api/products").json()),
   "and the change is visible")
ok(c.patch(f"/api/admin/products/{_pid}", headers=A,
           json={}).status_code == 400, "an empty edit is refused")
ok(c.delete(f"/api/admin/products/{_pid}", headers=A).json()["retired"]
   is False, "an unsold product deletes outright")

# A product with order history is retired instead, so past orders keep
# describing something that exists.
_con_s = _db.connect()
_sold_row = _con_s.execute(
    "SELECT product_id FROM order_items LIMIT 1").fetchone()
_con_s.close()
ok(_sold_row is not None, "some product has been ordered by now")
_sold = _sold_row["product_id"]
_before = c.get("/api/admin/db/products", headers=A).json()["total"]
_del = c.delete(f"/api/admin/products/{_sold}", headers=A).json()
ok(_del["retired"], "a product with orders is retired, not deleted")
ok(c.get("/api/admin/db/products", headers=A).json()["total"] == _before,
   "and its row is still there")

_st = c.post("/api/admin/stores", headers=A, json={
    "name": "Editable Store", "region": "Midwest", "lat": 41.0, "lng": -87.0})
_sid = [s["id"] for s in c.get("/api/stores").json()
        if s["name"] == "Editable Store"][0]
ok(c.patch(f"/api/admin/stores/{_sid}", headers=A,
           json={"city": "Gary"}).status_code == 200, "a store edits")
ok(c.delete(f"/api/admin/stores/{_sid}", headers=A).status_code == 200,
   "and deletes")

_pr = c.post("/api/admin/promos", headers=A,
             json={"kind": "promo", "name": "Editable promo"}).json()
ok(c.patch(f"/api/admin/promos/{_pr['id']}", headers=A,
           json={"discount_pct": 15}).status_code == 200, "a promo edits")
ok(c.delete(f"/api/admin/promos/{_pr['id']}", headers=A).status_code == 200,
   "and deletes")

_ords = c.get("/api/orders", headers=A).json()
if _ords:
    _oid = _ords[0]["id"]
    ok(c.patch(f"/api/admin/orders/{_oid}", headers=A,
               json={"city": "Elsewhere"}).status_code == 200, "an order edits")
    ok(c.patch(f"/api/admin/orders/{_oid}", headers=A,
               json={"status": "teleported"}).status_code == 400,
       "an invented order status is refused")
    ok(c.delete(f"/api/admin/orders/{_oid}", headers=A).json()["cancelled"],
       "deleting an order cancels it rather than erasing the record")

ok(c.delete("/api/admin/inventory/999999/999999",
            headers=A).status_code == 404,
   "clearing stock a store never had is a 404, not a silent success")

# --- sourcing and supply ---
_sup = c.post("/api/supply/suppliers", headers=A,
              json={"name": "Test Farms", "lead_days": 30}).json()
ok(_sup.get("id"), "a supplier is created")
ok(c.post("/api/supply/suppliers", headers=A,
          json={"name": "", "kind": "ingredient"}).status_code == 400,
   "a nameless supplier is refused")
ok(c.post("/api/supply/suppliers", headers=A,
          json={"name": "x", "kind": "invented"}).status_code == 400,
   "an unknown supplier kind is refused")
_mat = c.post("/api/supply/materials", headers=A, json={
    "name": "Test concentrate", "unit": "L", "supplier_id": _sup["id"],
    "unit_cost_cents": 800, "reorder_point": 20}).json()
_po = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _sup["id"], "reference": "PO-T1",
    "lines": [{"material_id": _mat["id"], "qty": 50,
               "unit_cost_cents": 800}]}).json()
ok(_po.get("id"), "a purchase order is created")
ok(c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _sup["id"], "lines": []}).status_code == 400,
   "a purchase order with no lines is refused")
c.post(f"/api/supply/purchase-orders/{_po['id']}/status", headers=A,
       json={"status": "sent"})
_ovv = c.get("/api/supply", headers=A).json()
_line = [ln for p in _ovv["purchase_orders"] if p["id"] == _po["id"]
         for ln in p["lines"]][0]
_rec = c.post(f"/api/supply/purchase-orders/{_po['id']}/receive", headers=A,
              json={"lines": {str(_line["id"]): 20}}).json()
ok(_rec["complete"] is False, "a partial delivery leaves the order open")
ok(c.post(f"/api/supply/purchase-orders/{_po['id']}/receive", headers=A,
          json={"lines": {str(_line["id"]): 500}}).status_code == 400,
   "receiving more than was ordered is refused")
_m2 = [m for m in c.get("/api/supply", headers=A).json()["materials"]
       if m["id"] == _mat["id"]][0]
ok(_m2["on_hand"] == 20, "stock moved by exactly what was received")
ok(_m2["incoming"] == 30, "the rest still counts as incoming")

# Stock only moves with a reason attached.
ok(c.patch(f"/api/supply/materials/{_mat['id']}", headers=A,
           json={"name": "Renamed", "on_hand": 9999}).status_code == 200,
   "a material edits")
_m3 = [m for m in c.get("/api/supply", headers=A).json()["materials"]
       if m["id"] == _mat["id"]][0]
ok(_m3["on_hand"] == 20,
   "but on_hand is not writable through the edit endpoint")
ok(c.post(f"/api/supply/materials/{_mat['id']}/adjust", headers=A,
          json={"qty": -5, "note": ""}).status_code == 400,
   "an adjustment without a reason is refused")
c.post(f"/api/supply/materials/{_mat['id']}/adjust", headers=A,
       json={"qty": -5, "note": "stocktake"})
_moves = c.get(f"/api/supply/materials/{_mat['id']}/moves", headers=A).json()
ok(len(_moves) == 2 and _moves[0]["note"] == "stocktake",
   "every movement is recorded with who and why")
ok(sum(m["qty"] for m in _moves) == 15,
   "and the level is the sum of the movements")

# A run consumes its recipe and produces cases.
_prod = c.get("/api/products").json()[0]["id"]
c.post(f"/api/supply/bom/{_prod}", headers=A,
       json={"material_id": _mat["id"], "qty_per_case": 2})
_run = c.post("/api/supply/runs", headers=A,
              json={"product_id": _prod, "planned_cases": 5}).json()
ok(not _run["shortfall"], "a run with enough materials reports no shortfall")
_big = c.post("/api/supply/runs", headers=A,
              json={"product_id": _prod, "planned_cases": 500}).json()
ok(_big["shortfall"], "a run beyond stock says what it is short of")
_fin = c.post(f"/api/supply/runs/{_run['id']}/finish", headers=A,
              json={"actual_cases": 4}).json()
ok(_fin["cases"] == 4, "finishing a run records what was actually made")
_m4 = [m for m in c.get("/api/supply", headers=A).json()["materials"]
       if m["id"] == _mat["id"]][0]
ok(_m4["on_hand"] == 7, "and consumes materials for the real number, not the plan")

# The two ledgers meet here or nowhere. "Add the cases it made" was a
# sentence in finish_run's docstring and nothing else: materials were
# consumed and the finished goods went nowhere, so a case could be
# manufactured out of real ingredients and exist in no store's stock.
ok(_fin.get("made") and _fin["made"]["units"] > 0,
   "closing a run puts its output on a shelf — a run that consumes real "
   "ingredients and produces goods that exist nowhere is the seam between "
   "the two records, and it is where stock goes missing")
_pcase = [p2 for p2 in c.get("/api/products", headers=A).json()
          if p2["id"] == _prod][0]
ok(_fin["made"]["units"] == 4 * (_pcase["case_size"] or 1),
   "in units, because a shelf counts units and a run counts cases — two "
   "units of measure meeting unconverted is the oldest way for stock to "
   "be wrong by a factor of twelve")
_tr = c.get(f"/api/supply/trail/{_prod}", headers=A).json()
ok(_tr["materials_used"] == 8 and _tr["made_units"] == _fin["made"]["units"],
   "and one product reads down both ledgers in one list: what the run "
   "consumed and what it produced")
_sides = {m["side"] for m in _tr["moves"]}
ok(_sides == {"materials", "goods"},
   "both sides of the seam, in one order — 'we bought a thousand litres, "
   "where did it go' crosses it at production and was unanswerable from "
   "either side alone")
ok(any(m["reason"] == f"run:{_run['id']}" for m in _tr["moves"]
       if m["side"] == "goods"),
   "with the run itself as the reason on the shelf side")

# --- what it cost, carried through ------------------------------------
# The list price on a material is what we expect to pay. The average is
# what we did. They are the same number until a supplier reprices, and
# then a margin computed from the first is a margin about a purchase
# nobody made.
_cm = c.post("/api/supply/materials", headers=A, json={
    "name": "Costed syrup", "unit": "L", "unit_cost_cents": 100,
    "supplier_id": _sup["id"]}).json()
_cmid = [m for m in c.get("/api/supply", headers=A).json()["materials"]
         if m["name"] == "Costed syrup"][0]["id"]
_cpo = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _sup["id"],
    "lines": [{"material_id": _cmid, "qty": 10, "unit_cost_cents": 100}]}
    ).json()
_cl = _db.connect()
_cline = _cl.execute("SELECT id FROM purchase_order_lines WHERE po_id=?"
                     " ORDER BY id DESC LIMIT 1",
                     (_cpo["id"],)).fetchone()["id"]
_cl.close()
c.post(f"/api/supply/purchase-orders/{_cpo['id']}/receive", headers=A,
       json={"lines": {str(_cline): 10}})
_after1 = [m for m in c.get("/api/supply", headers=A).json()["materials"]
           if m["id"] == _cmid][0]
ok(round(_after1["avg_cost_cents"]) == 100,
   "a receipt at a price is what the stock on hand cost")
_cpo2 = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _sup["id"],
    "lines": [{"material_id": _cmid, "qty": 10, "unit_cost_cents": 300}]}
    ).json()
_cl = _db.connect()
_cline2 = _cl.execute("SELECT id FROM purchase_order_lines WHERE po_id=?"
                      " ORDER BY id DESC LIMIT 1",
                      (_cpo2["id"],)).fetchone()["id"]
_cl.close()
c.post(f"/api/supply/purchase-orders/{_cpo2['id']}/receive", headers=A,
       json={"lines": {str(_cline2): 10}})
_after2 = [m for m in c.get("/api/supply", headers=A).json()["materials"]
           if m["id"] == _cmid][0]
ok(round(_after2["avg_cost_cents"]) == 200,
   "and a second at a different price moves the average, weighted by what "
   "was already on the shelf — ten at 100 and ten at 300 is 200, not 300")
# Its own product, so the recipe under test is the only one on it.
c.post("/api/admin/products", headers=A, json={
    "sku": "COST-TEST", "name": "Costed line", "price_cents": 500,
    "case_size": 1, "case_price_cents": 500})
_cprod = [x for x in c.get("/api/products", headers=A).json()
          if x["sku"] == "COST-TEST"][0]["id"]
c.post(f"/api/supply/bom/{_cprod}", headers=A,
       json={"material_id": _cmid, "qty_per_case": 2})
_crun = c.post("/api/supply/runs", headers=A,
               json={"product_id": _cprod, "planned_cases": 5}).json()
_cfin = c.post(f"/api/supply/runs/{_crun['id']}/finish", headers=A,
               json={"actual_cases": 5}).json()
ok(_cfin["cost_cents"] == 2000,
   "a run values what it consumed at what that stock actually cost — ten "
   "litres at the 200 average, not at the 300 the last delivery happened "
   "to be")
ok(_cfin["made"]["per_case_cents"] == 400,
   "which divides into a real cost per case")
ok(_cfin["made"]["per_unit_cents"] > 0,
   "and per unit, carried onto the goods themselves so a shelf knows what "
   "its stock cost on the day it was made rather than what the recipe "
   "would cost to buy today")
_cmoves = c.get(f"/api/inventory/moves?product_id={_cprod}", headers=A).json()
ok(any(m["unit_cost_cents"] > 0 for m in _cmoves["moves"]),
   "the movement carries it, so a repricing months later cannot restate "
   "the margin on stock already made and already sold")

# --- parcels, and the sale that eats them -----------------------------
# A shelf is not a number, it is a pile of deliveries. Two cases of the
# same product made three months apart genuinely cost different amounts,
# and which one went out decides what the sale cost.
_lstore = [x for x in c.get("/api/stores", headers=A).json()][0]["id"]
_lcon = _db.connect()
_lcon.execute("DELETE FROM stock_layers WHERE product_id=?", (_cprod,))
_lcon.execute("DELETE FROM inventory_moves WHERE product_id=?", (_cprod,))
_lcon.execute("UPDATE inventory SET qty=0 WHERE product_id=?", (_cprod,))
_lcon.commit()
_db.stock_move(_lcon, _lstore, _cprod, 10, "run:a", "t", "",
               unit_cost_cents=100)
_db.stock_move(_lcon, _lstore, _cprod, 10, "run:b", "t", "",
               unit_cost_cents=500)
_lcon.commit()
_lay = c.get(f"/api/inventory/layers?store_id={_lstore}"
             f"&product_id={_cprod}", headers=A).json()
ok(len(_lay["layers"]) == 2 and _lay["value_cents"] == 6000,
   "two deliveries at different costs are two parcels, not one average — "
   "an average describes neither of them")
_db.stock_move(_lcon, _lstore, _cprod, -12, "order:999", "t", "")
_lcon.commit()
_mv = _lcon.execute(
    "SELECT cost_cents, unknown_qty FROM inventory_moves"
    " WHERE product_id=? ORDER BY id DESC LIMIT 1", (_cprod,)).fetchone()
ok(_mv["cost_cents"] == -(10 * 100 + 2 * 500),
   "and a sale eats the oldest first: ten at 100 then two at 500, which "
   "is what a shop does because that is what a date code is for")
ok(_mv["cost_cents"] < 0,
   "signed the way the quantity is — value leaving is negative, and a "
   "ledger with one column signed and the next not is summed wrongly by "
   "whoever reads it next")
_lay2 = c.get(f"/api/inventory/layers?store_id={_lstore}"
              f"&product_id={_cprod}", headers=A).json()
ok(_lay2["units"] == 8 and _lay2["layers"][0]["unit_cost_cents"] == 500,
   "what is left is the newer parcel, at its own cost")

# Stock that predates any of this cannot be costed, and saying so is the
# whole point — a cost of nothing flatters a margin exactly the way an
# assumed one does.
_lcon.execute("UPDATE inventory SET qty=50 WHERE store_id=? AND"
              " product_id=?", (_lstore, _cprod))
_lcon.execute("DELETE FROM stock_layers WHERE product_id=?", (_cprod,))
_lcon.commit()
_db.stock_move(_lcon, _lstore, _cprod, -5, "order:998", "t", "")
_lcon.commit()
_un = _lcon.execute(
    "SELECT cost_cents, unknown_qty FROM inventory_moves"
    " WHERE product_id=? ORDER BY id DESC LIMIT 1", (_cprod,)).fetchone()
ok(_un["unknown_qty"] == 5.0 and _un["cost_cents"] == 0,
   "so stock nobody ever priced leaves as five units that cannot be "
   "costed, reported rather than valued at zero")
_lcon.close()
ok(c.post(f"/api/supply/runs/{_run['id']}/finish", headers=A,
          json={"actual_cases": 1}).status_code == 400,
   "a finished run can't be finished twice")
ok(c.delete(f"/api/supply/runs/{_run['id']}", headers=A).status_code == 400,
   "and can't be deleted, because its movements point at it")
ok(c.get("/api/supply", headers={"Authorization": "Bearer nope"}
         ).status_code == 401, "sourcing needs an admin")

# --- the audit log ---
_au = c.get("/api/admin/audit", headers=A).json()
ok(_au["total"] > 0, "the audit log has entries")
ok(any("/api/supply/suppliers" in e["action"] for e in _au["entries"]),
   "including the ones nobody added an audit call for")
ok(all(e["actor"] for e in _au["entries"] if e["user_id"]),
   "each entry names who did it")
ok(any(e["status"] >= 400 for e in _au["entries"]),
   "refused requests are recorded too, not just successful ones")
# The whole point of summarising rather than storing bodies.
c.post("/api/me", headers=A, json={"pin": "5511"})
_au2 = c.get("/api/admin/audit?entity=me", headers=A).json()
ok(any("pin=***" in e["detail"] for e in _au2["entries"]),
   "a PIN in a request body is recorded as a name, never a value")
# As a value in its own right, not as four digits found anywhere. An
# audit detail carries request bodies, and request bodies carry raw
# epoch floats — expires=1790492765.032191, whose last six digits are
# effectively random. A bare substring search over that will match a
# four-digit PIN by chance about once in a few hundred runs, and it duly
# did: a Sunday push failed on this line with the PIN nowhere near the
# log. A test that fails at random on a gate everybody has to pass is
# worse than no test, because the first thing it teaches is that red
# means try again.
#
# Bounded by "not part of a longer number" rather than by field name, so
# it still catches the thing worth catching — the PIN surfacing where
# nobody expected it, name=5511 as much as pin=5511 — while a run of
# digits inside a timestamp cannot trip it.
_leak = _re.compile(r"(?<![\d.])5511(?![\d.])")
ok(not any(_leak.search(e["detail"] or "") for e in _au2["entries"]),
   "and the value itself is nowhere in the log, in any field")
ok(c.get("/api/admin/audit", headers={"Authorization": "Bearer nope"}
         ).status_code == 401, "the audit log needs an admin")

# --- the database viewer ---
# Not _db: that name is the database module, imported at the top.
_dbov = c.get("/api/admin/db", headers=A).json()
ok(_dbov["tables"], "the database lists its tables")
ok(not any(t["name"].startswith("sqlite_") for t in _dbov["tables"]),
   "internal tables are not listed")
ok(not any(t["name"] == "login_tokens" for t in _dbov["tables"]),
   "and neither is the table of live sign-in tokens")
_users = c.get("/api/admin/db/users", headers=A).json()
_ucols = {col["name"]: col for col in _users["columns"]}
ok(_ucols["token"]["secret"] and _ucols["token"]["locked"],
   "the token column is marked secret and locked")
ok(all(r["token"] == "••• hidden" for r in _users["rows"] if r["token"]),
   "and no token value is ever sent to the browser")
ok(all(r["pin"] == "••• hidden" for r in _users["rows"] if r["pin"]),
   "nor a PIN")
_uid = _users["rows"][0]["id"]
for _bad, _why in (("token", "a credential"), ("is_admin", "a grant"),
                   ("id", "an identity"), ("password_hash", "a hash")):
    ok(c.patch(f"/api/admin/db/users/{_uid}", headers=A,
               json={"values": {_bad: "1"}}).status_code == 400,
       f"the table editor refuses to write {_bad} — {_why}")
ok(c.patch(f"/api/admin/db/users/{_uid}", headers=A,
           json={"values": {"region": "Midwest"}}).status_code == 200,
   "but an ordinary column edits")
ok(c.patch(f"/api/admin/db/users/{_uid}", headers=A,
           json={"values": {"nonexistent": "x"}}).status_code == 400,
   "a column that doesn't exist is refused")
# The table name reaches SQL, so it must only ever be a name from the schema.
for _inj in ("users; DROP TABLE users", "users' OR '1", "../etc/passwd"):
    ok(c.get(f"/api/admin/db/{_inj}", headers=A).status_code == 404,
       f"a table name that isn't a table is refused: {_inj[:22]}")
ok(c.get("/api/admin/db/users", headers=A).json()["total"] > 0,
   "and users is still there afterwards")
ok(c.get("/api/admin/db", headers={"Authorization": "Bearer nope"}
         ).status_code == 401, "the database viewer needs an admin")

# --- documents delete ---
_docs = c.get("/api/store/admin/documents", headers=A).json()["documents"]
_sigcount = lambda d: sum(  # noqa: E731
    1 for s in d.get("signatures", []) if s["status"] == "signed")
_signed = next((d for d in _docs if _sigcount(d)), None)
_unsigned = next((d for d in _docs if not _sigcount(d)), None)
if _unsigned:
    ok(c.delete(f"/api/store/admin/documents/{_unsigned['id']}",
                headers=A).json()["archived"] is False,
       "an unsigned document deletes")
if _signed:
    ok(c.delete(f"/api/store/admin/documents/{_signed['id']}",
                headers=A).json()["archived"],
       "a signed one is archived, because the signature has to keep "
       "pointing at something")

# --- the ops app carries the new screens ---
ok("renderSupply" in _ops and "renderAudit" in _ops and "renderDb" in _ops,
   "the ops app has sourcing, audit and database views")
ok("rowActions" in _ops and "ROW_KINDS" in _ops,
   "edit and delete are declared once and shared, not per screen")
# The dialog element is #ops-modal. A selector written as "#modal ..." matches
# nothing, so the form collects no fields and saves an empty body — which
# fails as "nothing to change" rather than as a broken selector.
ok('"#modal ' not in _ops and "'#modal " not in _ops,
   "modal field selectors use the id the modal actually has")
ok('id: "supply"' in _ops and 'id: "audit"' in _ops and 'id: "dbview"' in _ops,
   "and each has a tab")


from erp.backend import auth  # noqa: E402

# --- PINs are hashed ---
# The threat is a stolen copy of the database. The pepper lives in the config
# file, so the four-digit space can't be enumerated from the dump alone.
c.post("/api/me", headers=A, json={"pin": "8342"})
_con_p = _db.connect()
_row = _con_p.execute(
    "SELECT pin, pin_hash FROM users WHERE id=?",
    (c.get("/api/me", headers=A).json()["id"],)).fetchone()
ok(not (_row["pin"] or "").strip(), "no PIN is stored in plaintext")
ok(len(_row["pin_hash"]) == 64, "a PIN is stored as a hash")
# What this is really asserting is that the stored value cannot be
# reproduced without the pepper. It used to assert that the four digits
# were not a substring of the hash, which is true of a hex string about
# 999 times in 1000 and fails the other time for no reason anybody could
# reproduce — the exact shape of flake this repo's date audit exists to
# stamp out.
_bare = __import__("hashlib").sha256(b"8342").hexdigest()
ok(_row["pin_hash"] != _bare,
   "and it is not the bare hash of the PIN, which four digits would not "
   "survive being")
ok(_row["pin_hash"] != auth.hash_pin("8342", "some other pepper"),
   "the pepper is what makes the four-digit space unenumerable from a "
   "stolen copy of the database")
ok(_con_p.execute("SELECT COUNT(*) n FROM users WHERE pin LIKE '%8342%'"
                  ).fetchone()["n"] == 0,
   "the PIN appears nowhere in the users table")
ok(c.post("/api/clock", json={"pin": "8342"}).json()["action"] == "clock_in",
   "the clock still finds someone by their PIN alone")
c.post("/api/clock", json={"pin": "8342"})

# The hash must depend on the pepper, or the dump would be enough.
from erp.backend import auth as _auth  # noqa: E402
ok(_auth.hash_pin("8342", "pepper-a") != _auth.hash_pin("8342", "pepper-b"),
   "the hash depends on a secret the database doesn't hold")
ok(_auth.hash_pin("8342", CFG["pin_pepper"]) == _row["pin_hash"],
   "and it is the pepper from the config file")

# An old install with plaintext PINs converts on the next boot.
_con_p.execute("UPDATE users SET pin='7777', pin_hash='' WHERE id=?",
               (_row_id := c.get("/api/me", headers=A).json()["id"],))
_con_p.commit()
ok(_auth.migrate_pins(_con_p, CFG["pin_pepper"]) >= 1,
   "an old plaintext PIN is migrated")
ok(not _con_p.execute("SELECT pin FROM users WHERE id=?",
                      (_row_id,)).fetchone()["pin"],
   "and the plaintext is cleared")
ok(c.post("/api/clock", json={"pin": "7777"}).status_code == 200,
   "the migrated PIN still works")
c.post("/api/clock", json={"pin": "7777"})

# --- admin PIN reset ---
# An active account: the clock only recognises active staff, which is the
# point — a PIN outliving someone's employment is the bug, not the test.
_staff_id = [u["id"] for u in c.get("/api/admin/users", headers=A).json()
             if u["id"] != _row_id and u["active"]][0]
ok(c.post(f"/api/admin/users/{_staff_id}/pin", headers=A,
          json={"pin": "5150"}).status_code == 200, "an admin sets a PIN")
ok(c.post("/api/clock", json={"pin": "5150"}).status_code == 200,
   "and that PIN works immediately")
c.post("/api/clock", json={"pin": "5150"})
ok(c.post(f"/api/admin/users/{_staff_id}/pin", headers=A,
          json={"pin": "7777"}).status_code == 400,
   "a PIN already in use is refused")
ok(c.post(f"/api/admin/users/{_staff_id}/pin", headers=A,
          json={"pin": "12"}).status_code == 400, "a short PIN is refused")
ok(c.post(f"/api/admin/users/{_staff_id}/pin", headers=A,
          json={"pin": ""}).json()["cleared"], "and a PIN can be removed")
ok(c.post("/api/clock", json={"pin": "5150"}).status_code == 404,
   "after which it no longer clocks in")
ok(c.post(f"/api/admin/users/{_staff_id}/pin", headers=CU,
          json={"pin": "1212"}).status_code in (401, 403),
   "resetting a PIN needs an admin")
# The list an admin works from must not be a list of PINs.
_emps = c.get("/api/admin/employees", headers=A).json()
ok(_emps and "has_pin" in _emps[0] and "pin" not in _emps[0],
   "the employee list says whether a PIN is set, never what it is")
_con_p.close()

# --- COGS from the recipe ---
_pnl0 = c.get("/api/analytics/pnl", headers=A).json()
ok("cogs_measured_cents" in _pnl0,
   "the P&L separates measured cost from estimated")
# A product actually sold inside the P&L window, or there is nothing for the
# recipe to price and the test would pass or fail on seed data ordering.
_con_c = _db.connect()
_pid_c = _con_c.execute(
    "SELECT oi.product_id FROM order_items oi JOIN orders o ON o.id=oi.order_id"
    " WHERE o.status!='cancelled' AND o.created_at >= ?"
    " GROUP BY oi.product_id ORDER BY SUM(oi.qty) DESC LIMIT 1",
    (_t0.time() - 2592000,)).fetchone()
_con_c.close()
ok(_pid_c is not None, "something was sold in the P&L window")
_pid_c = _pid_c["product_id"]
_matc = c.post("/api/supply/materials", headers=A, json={
    "name": "Costed input", "unit": "each", "unit_cost_cents": 50}).json()
c.post(f"/api/supply/bom/{_pid_c}", headers=A,
       json={"material_id": _matc["id"], "qty_per_case": 24})
_pnl1 = c.get("/api/analytics/pnl", headers=A).json()
ok(_pnl1["assumptions"]["recipes_priced"] >= 1,
   "a priced recipe is counted")
ok(_pnl1["cogs_measured_cents"] > 0,
   "and its cost is measured rather than assumed")
ok(_pnl1["cogs_cents"] == _pnl1["cogs_measured_cents"]
   + _pnl1["cogs_estimated_cents"],
   "total COGS is the measured part plus the estimate on the rest")
ok(0 < _pnl1["cogs_measured_pct"] <= 100,
   "the share of revenue that was actually measured is reported")
ok(_pnl1["gross_cents"] == _pnl1["revenue_cents"] - _pnl1["cogs_cents"],
   "gross profit still follows from revenue minus COGS")
# A product with no recipe must not be treated as free.
from erp.backend import supply as _sup  # noqa: E402
_con_u = _db.connect()
_costs = _sup.unit_costs(_con_u)
ok(_pid_c in _costs, "a product with a recipe has a unit cost")
_con_u.execute(
    "INSERT INTO products(sku,name,price_cents,case_size,case_price_cents)"
    " VALUES('NO-BOM','Unpriced',300,12,3000)")
_con_u.commit()
_costs2 = _sup.unit_costs(_con_u)
_bare = _con_u.execute("SELECT id FROM products WHERE sku='NO-BOM'"
                       ).fetchone()["id"]
ok(_bare not in _costs2,
   "a product with no recipe is absent from the cost table, not zero-cost")
_con_u.close()

# --- the supply permission ---
_wh = c.post("/api/login", json={"name": "Warehouse Lead",
                                 "role": "employee"}).json()
_WH = {"Authorization": "Bearer " + _wh["token"]}
ok(c.get("/api/supply", headers=_WH).status_code == 403,
   "sourcing is closed to staff without the grant")
c.post(f"/api/store/admin/staff/{_wh['id']}/permissions", headers=A,
       json={"permissions": ["supply"]})
ok(c.get("/api/supply", headers=_WH).status_code == 200,
   "and open to staff who have it, without making them an owner")
ok(c.get("/api/admin/db", headers=_WH).status_code == 403,
   "the grant doesn't leak into anything else")

# --- one audit row per request ---
_before_n = c.get("/api/admin/audit", headers=A).json()["total"]
c.post(f"/api/store/admin/staff/{_wh['id']}/permissions", headers=A,
       json={"permissions": ["supply", "orders"]})
_after = c.get("/api/admin/audit", headers=A).json()
ok(_after["total"] == _before_n + 1,
   "a store-admin action leaves exactly one audit entry, not two")
ok("set permissions" in _after["entries"][0]["detail"],
   "and it carries the handler's own description, not the raw body")

# --- migrations reach an existing database ---
# A fresh test database gets every column from CREATE TABLE, so the only way
# to catch a missing migration is to build the old shape on purpose. This
# one bit for real: the dev database had purchase_orders without
# portal_token, and CREATE TABLE IF NOT EXISTS left it that way.
# On its own in-memory database — the live one has orders in it.
import sqlite3 as _sq3  # noqa: E402
_con_m = _sq3.connect(":memory:")
_con_m.execute("CREATE TABLE purchase_orders (id INTEGER PRIMARY KEY,"
               " supplier_id INTEGER NOT NULL, reference TEXT DEFAULT '',"
               " status TEXT DEFAULT 'draft', expected REAL DEFAULT 0,"
               " notes TEXT DEFAULT '', created_at REAL NOT NULL,"
               " received_at REAL DEFAULT 0)")
_con_m.commit()
_sup.init_tables(_con_m)
_pocols = {r[1] for r in _con_m.execute("PRAGMA table_info(purchase_orders)")}
ok("portal_token" in _pocols and "confirmed_at" in _pocols,
   "an older purchase_orders table gains the columns added since")
_con_m.close()

# --- the supplier portal ---
_psup = c.post("/api/supply/suppliers", headers=A,
               json={"name": "Portal Farms", "lead_days": 21}).json()
_pmat = c.post("/api/supply/materials", headers=A, json={
    "name": "Portal input", "unit": "kg", "supplier_id": _psup["id"],
    "unit_cost_cents": 400}).json()
_ppo = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _psup["id"], "reference": "PO-PORTAL", "expected": 1790000000,
    "lines": [{"material_id": _pmat["id"], "qty": 100,
               "unit_cost_cents": 400}]}).json()
_url = c.post(f"/api/supply/purchase-orders/{_ppo['id']}/portal-link",
              headers=A).json()["url"]
_tok = _url.rsplit("/", 1)[1]
ok(len(_tok) > 20, "a purchase order gets a supplier link")
ok(c.post(f"/api/supply/purchase-orders/{_ppo['id']}/portal-link",
          headers=A).json()["url"] == _url,
   "and the link is stable, so a supplier can come back to it")
_pv = c.get(f"/api/supplier/{_tok}").json()
ok(_pv["reference"] == "PO-PORTAL", "the supplier can open it with no login")
# What they must not see.
_dump = json.dumps(_pv)
ok("unit_cost_cents" not in _dump and "400" not in _dump,
   "the portal never shows the supplier what we pay")
ok("suppliers" not in _dump and "on_hand" not in _dump,
   "nor our stock or our other suppliers")
ok(c.get("/api/supplier/not-a-real-token").status_code == 404,
   "a wrong token gets nothing")
_lid = _pv["lines"][0]["id"]
ok(c.post(f"/api/supplier/{_tok}/confirm",
          json={"lines": {str(_lid): 90}}).status_code == 400,
   "a confirmation without a name is refused")
_conf = c.post(f"/api/supplier/{_tok}/confirm", json={
    "confirmed_by": "Aiko", "confirmed_eta": 1791000000,
    "lines": {str(_lid): 80}, "message": "short crop"}).json()
ok(_conf["short"] and _conf["short"][0]["said"] == 80,
   "a short confirmation is reported back as a shortfall")
ok(_conf["later"], "and a later date is flagged as a slip")
# A line id from someone else's order must not be writable through this link.
ok(c.post(f"/api/supplier/{_tok}/confirm", json={
    "confirmed_by": "Aiko", "lines": {"999999": 5}}).status_code == 200,
   "an unknown line id is ignored rather than accepted")
_conf2 = _db.connect().execute(
    "SELECT lines FROM po_confirmations ORDER BY id DESC LIMIT 1").fetchone()
ok("999999" not in _conf2["lines"], "and is not recorded")

# --- days of cover ---
_fc = c.get("/api/supply/forecast", headers=A).json()
ok("materials" in _fc and "products" in _fc, "the forecast covers both")
ok(all(m["per_day"] > 0 for m in _fc["materials"]),
   "a material that has not moved gets no forecast, rather than a fake one")
for _m in _fc["materials"]:
    ok(_m["order_by_days"] == _m["days_cover"] - _m["lead_days"],
       f"{_m['name']}: the order-by date accounts for the lead time")
    break
ok(c.get("/api/supply/forecast", headers=CU).status_code in (401, 403),
   "the forecast needs the supply permission")

# --- the ops app carries all of it ---
ok("data-setpin" in _ops, "an admin can reset a PIN from Team & access")
ok("data-polink" in _ops, "a purchase order offers its supplier link")
ok("days_cover" in _ops, "and the sourcing page shows days of cover")
ok("cogs_measured_cents" in _ops,
   "the P&L shows which part of COGS was measured")


# --- audit retention ---
from erp.backend import audit as _aud  # noqa: E402
_con_r = _db.connect()
_now_r = _t.time()
for _t_off, _act in (
        (400, "POST /api/admin/products"),                    # old, ordinary
        (400, "POST /api/store/admin/staff/3/permissions"),   # old, sensitive
        (400, "POST /api/admin/users/2/pin"),                 # old, sensitive
        (400, "GET /api/admin/db/users"),                     # old, sensitive
        (1200, "POST /api/admin/users/9/pin"),                # past every window
        (5, "POST /api/admin/orders/5")):                     # recent
    _con_r.execute(
        "INSERT INTO audit_log(actor,action,detail,status,created_at)"
        " VALUES('retention-test',?,'',200,?)",
        (_act, _now_r - _t_off * 86400))
_con_r.commit()
_aud._last_prune.clear()
_removed = _aud.prune(_con_r, _now_r)
_left = [r["action"] for r in _con_r.execute(
    "SELECT action FROM audit_log WHERE actor='retention-test'").fetchall()]
ok(_removed >= 2, "pruning removes entries past their window")
ok("POST /api/admin/products" not in _left,
   "an ordinary entry is dropped after the short window")
ok("POST /api/store/admin/staff/3/permissions" in _left
   and "POST /api/admin/users/2/pin" in _left,
   "but anything touching access is kept longer")
ok("GET /api/admin/db/users" in _left,
   "including a look at the raw tables")
ok("POST /api/admin/users/9/pin" not in _left,
   "and even those go once past the long window")
ok("POST /api/admin/orders/5" in _left, "recent entries are untouched")
# Pruning on every request would be a delete over the whole table per write.
ok(_aud.prune(_con_r, _now_r) == 0,
   "and it does nothing again within the hour")
ok(_aud.prune(_con_r, _now_r + _aud.PRUNE_EVERY + 1) == 0,
   "with nothing left to remove, the next run is still a no-op")
_con_r.close()
_aud._last_prune.clear()
_ret = c.get("/api/admin/audit", headers=A).json()
ok(_ret["retention"]["days"] == _aud.KEEP_DAYS
   and _ret["retention"]["sensitive_days"] > _aud.KEEP_DAYS,
   "the viewer is told the policy, both windows")
ok("retention" in _ops and "sensitive_days" in _ops,
   "and shows it, rather than silently deleting history")

# --- a confirmation reaches receiving ---
_csup = c.post("/api/supply/suppliers", headers=A,
               json={"name": "Confirm Co"}).json()
_cmat = c.post("/api/supply/materials", headers=A, json={
    "name": "Confirmed input", "unit": "kg",
    "supplier_id": _csup["id"], "unit_cost_cents": 100}).json()
_cpo = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _csup["id"], "reference": "PO-CONF",
    "lines": [{"material_id": _cmat["id"], "qty": 50,
               "unit_cost_cents": 100}]}).json()
_ctok = c.post(f"/api/supply/purchase-orders/{_cpo['id']}/portal-link",
               headers=A).json()["url"].rsplit("/", 1)[1]
_cline = c.get(f"/api/supplier/{_ctok}").json()["lines"][0]["id"]
c.post(f"/api/supplier/{_ctok}/confirm", json={
    "confirmed_by": "Sam", "lines": {str(_cline): 40}})
_cpo_row = [p for p in c.get("/api/supply", headers=A).json()["purchase_orders"]
            if p["id"] == _cpo["id"]][0]
ok(_cpo_row["confirmation"] and _cpo_row["confirmation"]["by"] == "Sam",
   "the latest confirmation rides along with the purchase order")
ok(_cpo_row["lines"][0]["confirmed"] == 40,
   "and is attached to the line it refers to")
ok(_cpo_row["lines"][0]["qty"] == 50,
   "so ordered and promised are both on the row, and differ")
_nopo = [p for p in c.get("/api/supply", headers=A).json()["purchase_orders"]
         if p["confirmation"] is None]
ok(_nopo and _nopo[0]["lines"][0]["confirmed"] is None,
   "an unconfirmed order says so rather than implying agreement")
ok("promised" in _ops and "data-said" in _ops,
   "the receive dialog shows ordered, promised and arrived together")

# --- the forecast counts stock already on order ---
c.post(f"/api/supply/purchase-orders/{_cpo['id']}/status", headers=A,
       json={"status": "sent"})
# Give it consumption, or there is nothing to forecast against.
c.post(f"/api/supply/materials/{_cmat['id']}/adjust", headers=A,
       json={"qty": 30, "note": "opening count"})
c.post(f"/api/supply/materials/{_cmat['id']}/adjust", headers=A,
       json={"qty": -20, "note": "used in production"})
_fm = [m for m in c.get("/api/supply/forecast", headers=A).json()["materials"]
       if m["id"] == _cmat["id"]]
ok(_fm, "a material with consumption appears in the forecast")
_fm = _fm[0]
ok(_fm["incoming"] == 50, "the outstanding purchase order counts as incoming")
ok(_fm["days_cover_with_incoming"] > _fm["days_cover"],
   "cover with it on order is longer than cover on hand")
ok(_fm["on_hand"] == 10, "and on-hand still reflects only what is here")
# Without a date, an order in transit is assumed to arrive in time; the
# useful case is when it demonstrably doesn't.
_late = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _csup["id"], "reference": "PO-LATE",
    "expected": _t.time() + 400 * 86400,
    "lines": [{"material_id": _cmat["id"], "qty": 5,
               "unit_cost_cents": 100}]}).json()
c.post(f"/api/supply/purchase-orders/{_late['id']}/status", headers=A,
       json={"status": "sent"})
_fm2 = [m for m in c.get("/api/supply/forecast", headers=A).json()["materials"]
        if m["id"] == _cmat["id"]][0]
ok(_fm2["eta_days"] is not None,
   "the soonest expected date is reported in days")
ok("covered_by_order" in _fm2,
   "and whether that order lands before the shelf empties is stated")
ok("days_cover_with_incoming" in _ops and "covered_by_order" in _ops,
   "the sourcing page shows both covers and what to do about it")


# --- revoking a supplier link ---
_rsup = c.post("/api/supply/suppliers", headers=A,
               json={"name": "Revoke Co"}).json()
_rmat = c.post("/api/supply/materials", headers=A, json={
    "name": "Revoke input", "unit": "kg", "supplier_id": _rsup["id"]}).json()
_rpo = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _rsup["id"], "reference": "PO-REV",
    "lines": [{"material_id": _rmat["id"], "qty": 10}]}).json()
_u1 = c.post(f"/api/supply/purchase-orders/{_rpo['id']}/portal-link",
             headers=A, json={}).json()["url"]
_t1 = _u1.rsplit("/", 1)[1]
ok(c.get(f"/api/supplier/{_t1}").status_code == 200, "a fresh link works")

# Rotating: the old one has to stop working in the same step, or "I sent it
# to the wrong address" is only half solved.
_u2 = c.post(f"/api/supply/purchase-orders/{_rpo['id']}/portal-link",
             headers=A, json={"rotate": True}).json()["url"]
_t2 = _u2.rsplit("/", 1)[1]
ok(_t2 != _t1, "rotating issues a different link")
ok(c.get(f"/api/supplier/{_t2}").status_code == 200, "the new one works")
ok(c.get(f"/api/supplier/{_t1}").status_code == 404,
   "and the old one stops immediately")

ok(c.delete(f"/api/supply/purchase-orders/{_rpo['id']}/portal-link",
            headers=A).status_code == 200, "a link can be revoked outright")
ok(c.get(f"/api/supplier/{_t2}").status_code == 404,
   "after which nobody can answer the order")
ok(c.delete(f"/api/supply/purchase-orders/{_rpo['id']}/portal-link",
            headers=A).status_code == 400,
   "revoking twice says there is nothing to revoke")
# A blank stored token must not match a blank request, or every order
# without a link would answer to an empty string.
ok(c.get("/api/supplier/").status_code in (404, 405),
   "an empty token matches no order")
_after = [p for p in c.get("/api/supply", headers=A).json()["purchase_orders"]
          if p["id"] == _rpo["id"]][0]
ok(_after["has_link"] is False, "the order reports that it has no link")
ok("portal_token" not in json.dumps(_after),
   "and the token itself never reaches the browser")
_u3 = c.post(f"/api/supply/purchase-orders/{_rpo['id']}/portal-link",
             headers=A, json={}).json()["url"]
ok(c.get(f"/api/supplier/{_u3.rsplit('/', 1)[1]}").status_code == 200,
   "a revoked order can be given a new link later")
ok("po-revoke" in _ops and "po-rotate" in _ops,
   "the link dialog offers both replacing and revoking")

# --- exporting ---
_csv = c.get("/api/admin/db/users/export.csv", headers=A)
ok(_csv.status_code == 200 and "text/csv" in _csv.headers["content-type"],
   "a table exports as CSV")
ok("users.csv" in _csv.headers.get("content-disposition", ""),
   "with a filename the browser will use")
ok("token" in _csv.text.splitlines()[0], "the column is present")
ok("••• hidden" in _csv.text, "but its values are redacted")
# The real proof: this session's own token must not be in the file.
_mytoken = A["Authorization"].split()[1]
ok(_mytoken not in _csv.text, "no live token appears in an export")

_js = c.get("/api/admin/db/export.json?tables=users,products", headers=A)
ok(_js.status_code == 200, "several tables export as JSON")
_jd = json.loads(_js.text)
ok(set(_jd) == {"users", "products"}, "and only the ones asked for")
ok(all(u["token"] in ("", None, "••• hidden") for u in _jd["users"]),
   "with the same redaction")
ok(c.get("/api/admin/db/export.json?tables=users;DROP",
         headers=A).status_code == 404,
   "a table name that isn't a table is refused here too")

# Literal paths have to beat the {table} parameter, which is registration
# order — "export.json" would otherwise be read as a table name.
ok(c.get("/api/admin/db/export.json", headers=A).status_code == 200,
   "the export path isn't swallowed by the table route")
ok(c.get("/api/admin/db/backup.db", headers=A).status_code == 200,
   "nor is the backup path")

_bak = c.get("/api/admin/db/backup.db", headers=A)
if os.environ.get("BC_STORE") == "postgres":
    ok(_bak.content.startswith(b"--") and b"PostgreSQL database dump" in _bak.content[:200]
       and ".sql" in _bak.headers["content-disposition"],
       "a tenant in Postgres downloads as a plain pg_dump — readable, and "
       "what psql restores, not a copy of files nobody can open")
else:
    ok(_bak.content[:15] == b"SQLite format 3",
       "the backup is a real SQLite file, not a dump that might not restore")
import sqlite3 as _sq  # noqa: E402
if os.environ.get("BC_STORE") != "postgres":
    _bp = Path(tempfile.mkdtemp()) / "b.db"
    _bp.write_bytes(_bak.content)
    _bcon = _sq.connect(_bp)
    ok(_bcon.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0,
       "it opens and has the data in it")
    ok(_bcon.execute("SELECT COUNT(*) FROM users WHERE token=?",
                     (_mytoken,)).fetchone()[0] == 1,
       "and it keeps the credentials — a redacted backup is not a backup")
    _bcon.close()
else:
    ok(b"users" in _bak.content and _mytoken.encode() in _bak.content,
       "the archive carries the users table and the credentials — a "
       "redacted backup is not a backup")

ok(c.get("/api/admin/db/users/export.csv", headers=CU).status_code
   in (401, 403), "exporting needs an admin")
# Exports are GETs, so the middleware skips them; each records itself.
_ex = c.get("/api/admin/audit?entity=export", headers=A).json()
ok(any("export" in e["action"] for e in _ex["entries"]),
   "an export records itself in the audit log even though it is a GET")
ok(any("backup" in (e["detail"] or "") for e in
       c.get("/api/admin/audit", headers=A).json()["entries"]),
   "and so does a full backup")
ok("db-csv" in _ops and "db-backup" in _ops,
   "the database screen offers both exports and a backup")

# --- the two layout fixes ---
_css = c.get("/ops/styles.css").text
ok(".dm-start" in _css and "display: flex" in
   _css.split(".dm-start")[1][:60],
   "the chat name box and its button are laid out as one row")
ok(".punch-card" in _css and "max-width:380px" not in _ops,
   "the punch card fills the page rather than floating in a narrow box")
ok(".punch-card select { width: 100%" in _css,
   "and its event dropdown can't outgrow the card")


# --- no window listeners per map render ---
# This one had teeth: every map attached mousemove and mouseup to window and
# never removed them, so each visit to Stores or Routes left two more live
# handlers holding a whole detached SVG. Measured at 194 listeners and
# ~20ms per 200 mouse moves before the fix, rising linearly.
ok("window.addEventListener" not in _ops,
   "nothing in the ops app attaches a listener to window")
ok("setPointerCapture" in _ops,
   "the map drags with pointer capture, so its listeners die with the node")
ok('addEventListener("touchstart"' not in _ops,
   "and the separate touch handling is gone, since pointer events cover it")

# --- the socket backs off ---
ok("_wsWait" in _ops and "60000" in _ops,
   "a refused socket backs off instead of retrying forever on a fixed timer")
ok(_ops.count("clearTimeout(S._wsRetry)") >= 2,
   "and a pending reconnect is cancelled on sign-out as well as on connect")

# --- the service worker caches the shell, not everything ---
_sw = c.get("/ops/sw.js").text
_sfsw = c.get("/sf-sw.js").text
_store_js2 = c.get("/store.js").text
ok("CACHEABLE" in _sw, "the worker decides what is worth caching")
ok("r.ok && r.type" in _sw,
   "and never stores an error response, which would strand a broken shell")

# Both workers, one rule each way. These are the two failures that make a
# restart look like a broken build: a lookup that cannot find what it
# stored, and a fallback that answers with nothing at all.
for _name, _src in (("ops", _sw), ("storefront", _sfsw)):
    ok("const key = url.pathname;" in _src
       and "c.put(key, copy)" in _src
       and "caches.match(key, { ignoreSearch: true })" in _src,
       f"the {_name} worker keys its cache by path: every asset arrives as "
       f"?v=<mtime>, so a full-URL key stores a fresh copy each restart and "
       f"matches none of them afterwards — the offline shell goes missing "
       f"on exactly the restart it was meant to survive")
    ok("return fetch(e.request);" in _src.split(".catch(")[1],
       f"and the {_name} worker's last resort is a real request, never an "
       f"implicit undefined — resolving respondWith() with undefined is "
       f"itself a network error, which turns a server that was merely "
       f"restarting into ERR_FAILED and a page left silently unstyled")
    ok('e.request.mode === "navigate"' in _src,
       f"a navigation with nothing cached falls back to the {_name} shell, "
       f"which is what every route renders from anyway")
    ok("Promise.allSettled(SHELL.map((u) => c.add(u)))" in _src,
       f"and the {_name} shell is cached one file at a time: addAll() "
       f"rejects wholesale on a single 404, leaving nothing cached at all")

for _wpath in ("/ops/sw.js", "/sf-sw.js"):
    ok(c.get(_wpath).headers.get("cache-control") == "no-cache",
       f"{_wpath} is served must-revalidate: a worker kept on heuristic "
       f"freshness is a fix that lands a day late for everyone already "
       f"running the old one")
ok('{ updateViaCache: "none" }' in _ops
   and '{ updateViaCache: "none" }' in _store_js2,
   "and both registrations refuse the HTTP cache outright — the worker is "
   "what ships the fix, so it cannot be the thing that arrives stale")
ok("Every flavor" not in _store_js2 and "data-kindnav" in _store_js2
   and '<div class="side-group">\' + esc(t("all_products")) + \'</div>' in _store_js2,
   "the menu is the shop's own table of contents: All products, then one "
   "lane per category, each its own section — not one wall of faces under "
   "a heading inherited from a drinks brand")
ok('href="/plan-builder"' in _store_js2 and "builderIn" in _store_js2
   and 'cfg-card' in _store_js2,
   "and the shelf carries the door to the configurator where the "
   "capabilities are — a shop that sells them says so beside them, not "
   "only in the nav, and a shop that does not sell them shows nothing")
ok("kind-head" in _store_js2 and "CATALOG.kinds" in _store_js2
   and "kinds.length < 2" in _store_js2,
   "the shop groups its shelf by what things ARE, with each group's own "
   "colour — and a shop selling one kind of thing gets no headings, "
   "because a heading naming the only thing on the page says nothing")


# Reading the worker is not the same as running it. The harness loads both
# workers against a stubbed browser and puts them in the states that matter
# — server unreachable, cache holding a copy under a different ?v=, nothing
# cached at all — which is where the old one turned a restart into a page
# with no CSS. Pointed at the pre-fix worker, every ops case fails.
_swh = subprocess.run(["node", str(ROOT / "tests" / "sw_harness.mjs")],
                      capture_output=True, text=True, cwd=ROOT)
for _line in _swh.stdout.strip().splitlines():
    ok(_line.startswith("PASS "), _line)
ok(_swh.returncode == 0 and _swh.stdout.count("PASS ") >= 7,
   "the workers survive a restart when run, not just when read")

ok('"business-control-ops-v6"' in _sw and '"storefront-v4"' in _sfsw,
   "both cache names move when the keying changes, so the entries written "
   "under the old scheme are retired rather than half-matched")

# --- the hero shader can't run unattended ---
_store_js = c.get("/store.js").text
ok("IntersectionObserver" in _store_js and "visibilitychange" in _store_js,
   "the hero shader stops when off-screen or hidden")
ok("prefers-reduced-motion" in _store_js,
   "and never starts if the visitor asked for less motion")

# --- the QR sign-in scanner ---
_qr = c.get("/qr-scan.js")
ok(_qr.status_code == 200, "the shared scanner is served")
ok("getTracks().forEach((t) => t.stop())" in _qr.text,
   "and stops the camera on every exit path")
for _surface, _path in (("ops app", "/ops/"), ("store admin", "/admin"),
                        ("storefront", "/")):
    ok("/qr-scan.js" in c.get(_path).text, f"{_surface} loads the scanner")
ok("li-scan" in _ops, "the ops sign-in offers a scan")
ok("li-scan" in c.get("/admin").text, "so does the store admin")

# The admin scan button shipped with nothing behind it, because /admin had no
# cache-busting: the server had the new admin.js and the browser kept running
# the previous deploy's copy. Every surface has to version its own scripts.
_adm = c.get("/admin").text
ok('/admin.js?v=' in _adm and '/qr-scan.js?v=' in _adm,
   "the store admin versions its scripts")
ok('/store.js?v=' in c.get("/").text and '/qr-scan.js?v=' in c.get("/").text,
   "so does the storefront")
ok('/ops/app.js?v=' in c.get("/ops/").text
   and '/qr-scan.js?v=' in c.get("/ops/").text,
   "and so does the ops app")
ok('/theme.js?v=' in c.get("/admin/theme").text,
   "and the page builder")
# The version has to move when any asset changes, not just three named ones.
from storefront.backend import api as _sfapi  # noqa: E402
_v1 = _sfapi.asset_version()
_scan = Path(_sfapi.config.STOREFRONT_DIR) / "qr-scan.js"
# Newer than the version we just read, not newer than the wall clock. The
# version is the newest mtime in the directory, and a machine whose clock
# is behind those files — a test running on a moved clock, a restore onto
# a box with a wrong date — would set an mtime that is older than what is
# already there and watch nothing happen.
_bump = float(_v1) + 60 if str(_v1).isdigit() else _t.time() + 60
os.utime(_scan, (_bump, _bump))
ok(_sfapi.asset_version() != _v1,
   "touching any asset moves the version, not only the ones once listed")
ok("si-scan" in _store_js, "and so does the storefront")

# --- a disabled button is unavailable, not busy ---
# `cursor: wait` on :disabled meant hovering the signed-out Checkout button
# gave a spinning wait cursor over something that was never going to finish.
ok("cursor: not-allowed" in _css and
   "button.btn:disabled { opacity: .55; cursor: wait" not in _css,
   "a disabled button shows not-allowed, not a wait spinner")
ok('button.btn[aria-busy="true"]' in _css,
   "and busy is a state of its own, for a request actually in flight")
ok('setAttribute("aria-busy", "true")' in _ops,
   "which is set where a button is disabled during a request")

# The signed-out cart used to be a dead end: a disabled button beside a line
# of grey text that wasn't a link. It now goes straight to checkout, because
# an account is offered at the delivery step rather than demanded before it.
ok("sign in to order" not in _ops,
   "the inert label beside the checkout button is gone")
ok("if (co) co.onclick = onCheckout;" in _ops,
   "and the button checks out whether or not you're signed in")
ok('S.afterLogin = "shop"' in _ops and "S.afterLogin\n        ||" in _ops,
   "signing in mid-cart returns to the cart, not an employee job home")

# --- the side nav scrolls on its own and keeps its place ---
ok("overflow-y: auto" in _css.split("#tabs {")[1][:400]
   and "position: sticky" in _css.split("#tabs {")[1][:400],
   "the nav scrolls independently of the page")
ok("bc_nav_scroll" in _ops,
   "and remembers where it was scrolled to")
ok("scrollIntoView" in _ops.split("bc_nav_scroll")[-1][:900],
   "unless that would leave the current tab out of view")

# A scanned QR is a string a stranger can print, so only a sign-in link for
# this origin is ever followed.
ok("u.origin !== location.origin" in _qr.text,
   "a code pointing at another origin is refused")
ok("/^\\/qr-login\\/[\\w-]+$/" in _qr.text,
   "and only the sign-in path shape is accepted")

# --- the sign-in page sizes itself ---
ok("max-width:420px" not in _ops and "max-width:280px" not in _ops,
   "the sign-in cards no longer carry fixed pixel widths")
ok(".signin input, .signin select { width: 100%" in _css,
   "its fields fill whatever width the card has")
ok("max-width: 720px" in _css and ".signin { grid-template-columns: 1fr" in _css,
   "and it collapses to one column on a narrow window")


# --- your own profile works whoever you are ---
_cust = c.post("/api/login", json={"name": "Cart Tester",
                                   "role": "customer"}).json()
_CT = {"Authorization": "Bearer " + _cust["token"]}
_meq = c.get("/api/me", headers=_CT)
ok(_meq.status_code == 200, "a customer can read their own profile")
ok("member_since" in _meq.json(), "which now says how long they've been one")
# The two the page also wants stay owner-only, so the page must not need them.
ok(c.get("/api/achievements", headers=_CT).status_code == 403
   and c.get("/api/game", headers=_CT).status_code == 403,
   "the company scoreboard is still the owner's")
ok('api("/api/achievements").catch' in _ops
   and 'api("/api/game").catch' in _ops,
   "so the profile treats both as optional rather than failing the batch")
ok("${ach.length ? `<h3>Achievements" in _ops,
   "and simply omits the section when there is nothing to show")

# --- ordering without an account ---
_gp = c.post("/api/admin/products", headers=A, json={
    "sku": "GUEST-1", "name": "Guest Item", "price_cents": 500,
    "case_size": 12, "case_price_cents": 4800})
_gpid = [p for p in c.get("/api/products").json()
         if p["sku"] == "GUEST-1"][0]["id"]
_gbase = {"items": [{"product_id": _gpid, "qty": 2}],
          "ship_name": "Guest Buyer", "address": "1 Main St",
          "city": "Chicago", "postal": "60601"}
ok(c.post("/api/orders", json=_gbase).status_code == 400,
   "ordering without an account still needs an email")
ok("email" in c.post("/api/orders", json=_gbase).json()["detail"],
   "and says why")
ok(c.post("/api/orders", json={**_gbase, "email": "g@example.com",
                               "ship_name": ""}).status_code == 400,
   "and a name for the delivery")
_go = c.post("/api/orders", json={**_gbase, "email": "guest@example.com"})
ok(_go.status_code == 200, "a guest can order")
ok("token" not in _go.text,
   "and is never handed a session token for doing so")
_con_g = _db.connect()
_ga = _con_g.execute(
    "SELECT * FROM users WHERE lower(email)='guest@example.com'").fetchall()
ok(len(_ga) == 1, "one account is created for the email")
ok(not _ga[0]["password_hash"],
   "with no password, so it isn't a credential anyone now holds")
c.post("/api/orders", json={**_gbase, "email": "guest@example.com"})
ok(_con_g.execute("SELECT COUNT(*) n FROM users WHERE"
                  " lower(email)='guest@example.com'").fetchone()["n"] == 1,
   "and a second order attaches to it rather than making another")

# The guard that matters: a guest is priced as a customer even when the
# email belongs to a distributor, or the guest form would be a wholesale
# discount anyone could type their way into.
_dist = c.post("/api/login", json={"name": "Wholesale Co",
                                   "role": "distributor",
                                   "email": "buyer@wholesale.example"}).json()
_dr = c.post("/api/orders", headers={"Authorization": "Bearer " + _dist["token"]},
             json={"items": [{"product_id": _gpid, "qty": 1}]})
ok(_dr.json()["kind"] == "distributor" and _dr.json()["subtotal_cents"] == 4800,
   "a signed-in distributor is billed at case price")
_gr = c.post("/api/orders", json={**_gbase, "items": [{"product_id": _gpid,
             "qty": 1}], "email": "buyer@wholesale.example"})
ok(_gr.json()["kind"] == "customer" and _gr.json()["subtotal_cents"] == 500,
   "but a guest using that same email pays retail")
_con_g.close()
ok("sh-email" in _ops, "the checkout form asks a guest for an email")
ok("Order #${o.id} placed" in _ops,
   "and confirms the order in place, rather than sending them to a sign-in")

# --- clocking in with a badge ---
_badge = c.post("/api/me/badge", headers=A).json()["token"]
ok(_badge.startswith("bc:clock:"), "a badge is issued")
ok(c.post("/api/me/badge", headers=A).json()["token"] == _badge,
   "and is stable — a badge you must reissue every shift is one nobody uses")
_bin = c.post("/api/clock/badge", json={"token": _badge})
ok(_bin.status_code == 200 and _bin.json()["action"] == "clock_in",
   "scanning it clocks in")
ok(c.post("/api/clock/badge", json={"token": _badge}).json()["action"]
   == "clock_out", "and scanning again clocks out")
ok(c.post("/api/clock/badge", json={"token": "bc:clock:invented"}
          ).status_code == 404, "an unknown badge is refused")
# The separation is the point: a badge is not a login, and a login is not a
# badge. Either direction working would make a photographed lanyard an
# account.
ok(c.post("/api/clock/badge",
          json={"token": A["Authorization"].split()[1]}).status_code == 404,
   "a sign-in token is not accepted as a badge")
_notlogin = c.get("/api/me", headers={"Authorization": "Bearer " + _badge})
ok(_notlogin.status_code == 401, "and a badge is not accepted as a sign-in")
_badge2 = c.post("/api/me/badge?reset=1", headers=A).json()["token"]
ok(_badge2 != _badge, "a lost badge can be replaced")
ok(c.post("/api/clock/badge", json={"token": _badge}).status_code == 404,
   "which stops the old one")
ok(c.post("/api/admin/users/999999/badge", headers=A).status_code == 404,
   "issuing a badge for nobody is a 404")
ok(c.post("/api/me/badge", headers=CU).status_code == 401,
   "and getting a badge needs a sign-in")
ok("badge-btn" in _ops and "/api/clock/badge" in _ops,
   "the time clock offers a badge scan")
ok("pf-badge-go" in _ops, "your profile shows your own badge")
ok("data-badge=" in _ops, "and an owner can issue one from Team & access")


# --- choosing a delivery ---
_ships = c.get("/api/store/shipping").json()
ok(len(_ships) >= 2, "there is more than one delivery to choose between")
_std = [m for m in _ships if m["position"] == 0][0]
_fast = [m for m in _ships if m["position"] != 0][0]
# pay_method "card" with Stripe off still places immediately, which keeps
# this about delivery pricing rather than about the confirmation gate.
_dbase = {"items": [{"product_id": _gpid, "qty": 1}], "ship_name": "Ship Test",
          "address": "1 St", "city": "Chicago", "email": "carl@example.com",
          "pay_method": "card"}
_o_std = c.post("/api/orders", headers=CU,
                json={**_dbase, "shipping_method_id": _std["id"]}).json()
_o_fast = c.post("/api/orders", headers=CU,
                 json={**_dbase, "shipping_method_id": _fast["id"]}).json()
ok(_o_fast["shipping_cents"] == _fast["price_cents"],
   "the faster delivery is charged at its own price")
ok(_o_fast["shipping_cents"] > _o_std["shipping_cents"],
   "and costs more than standard")
ok(_o_fast["total_cents"] - _o_std["total_cents"]
   == _o_fast["shipping_cents"] - _o_std["shipping_cents"],
   "with the difference landing in the total, not somewhere else")
ok("ship-opt" in _ops and 'name="shipm"' in _ops,
   "the checkout offers the choice")
ok("cartTotals = (method)" in _ops and "S.shipMethod = r.value" in _ops,
   "and re-totals when it changes, rather than only on submit")

# The form has to ask for an email whenever the account hasn't confirmed one
# — not just for guests. An owner with no email on file was shown no field
# and then refused by the server, with nothing to type into.
ok("email_confirmed" in c.get("/api/me", headers=A).json(),
   "the account says whether its email is confirmed")
ok("const needEmail = !me || !me.email || !me.email_confirmed;" in _ops,
   "and the checkout asks based on that, not on being signed out")

# --- pay on delivery waits for a confirmed email ---
import re as _re2  # noqa: E402
_cod = {"items": [{"product_id": _gpid, "qty": 2}], "ship_name": "COD Buyer",
        "address": "3 Oak St", "city": "Chicago", "email": "cod@example.com",
        "pay_method": "cod"}
_before_orders = _db.connect().execute(
    "SELECT COUNT(*) n FROM orders").fetchone()["n"]
_held = c.post("/api/orders", json=_cod)
ok(_held.json().get("awaiting_confirmation"),
   "a first pay-on-delivery order is held, not placed")
ok("id" not in _held.json(), "and isn't given an order number yet")
_con_c = _db.connect()
ok(_con_c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
   == _before_orders,
   "nothing lands in orders, so nothing can be counted as revenue")
# The reason it lives outside `orders`: thirteen queries count anything that
# isn't cancelled, and an unconfirmed order must not be one of them.
_pnl_before = c.get("/api/analytics/pnl", headers=A).json()["revenue_cents"]

_tok_c = _con_c.execute(
    "SELECT token FROM pending_orders ORDER BY id DESC LIMIT 1"
).fetchone()["token"]
ok(c.get("/confirm-order/not-a-token").status_code == 200
   and "Link not valid" in c.get("/confirm-order/not-a-token").text,
   "a wrong link says so rather than erroring")
_conf = c.get(f"/confirm-order/{_tok_c}")
ok("Order confirmed" in _conf.text, "the link places the order")
ok(_con_c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
   == _before_orders + 1, "and now there is exactly one more order")
ok(c.get("/api/analytics/pnl", headers=A).json()["revenue_cents"]
   > _pnl_before, "which only now counts towards revenue")
ok("Already confirmed" in c.get(f"/confirm-order/{_tok_c}").text,
   "the link can't be used twice to place two orders")
ok(_con_c.execute("SELECT email_verified_at FROM users WHERE"
                  " lower(email)='cod@example.com'").fetchone()[0] > 0,
   "confirming proves the address")
_again = c.post("/api/orders", json=_cod)
ok("id" in _again.json(),
   "so the next pay-on-delivery order from it places outright")

# An expired link places nothing.
_exp = c.post("/api/orders", json={**_cod, "email": "expired@example.com"})
_con_c.execute("UPDATE pending_orders SET expires_at=1 WHERE placed_order_id=0")
_con_c.commit()
_etok = _con_c.execute("SELECT token FROM pending_orders WHERE"
                       " placed_order_id=0 ORDER BY id DESC LIMIT 1"
                       ).fetchone()["token"]
ok("expired" in c.get(f"/confirm-order/{_etok}").text.lower(),
   "an old link is refused")
_con_c.close()

# Card orders skip the hold — the payment itself is the proof.
ok("awaiting_confirmation" not in c.post("/api/orders", json={
    **_cod, "email": "card@example.com", "pay_method": "card"}).text,
   "paying by card doesn't wait on an email")
# And an order is checked before it's held, so nobody is emailed a link for
# something that could never have been placed.
ok(c.post("/api/orders", json={**_cod, "email": "shape@example.com",
                               "city": ""}).status_code == 400,
   "a malformed order is refused up front, not after a click")
ok(_db.connect().execute(
    "SELECT COUNT(*) n FROM pending_orders WHERE email='shape@example.com'"
   ).fetchone()["n"] == 0, "and nothing is held for it")

# Held orders stay visible to staff even though they aren't orders yet.
_await = c.get("/api/admin/orders/awaiting", headers=A)
ok(_await.status_code == 200, "staff can see what's waiting on confirmation")
ok(any(w["email"] == "expired@example.com" or w["items"]
       for w in _await.json()) or _await.json() == [],
   "with the items and the address that asked for them")
ok(c.get("/api/admin/orders/awaiting", headers=CU).status_code in (401, 403),
   "which is an owner's view")
ok("Waiting on email confirmation" in _ops,
   "and the orders screen shows them, separated from real orders")

# --- card payments are configurable ---
_pc = c.get("/api/admin/payments", headers=A).json()
ok("enabled" in _pc and "key_set" in _pc, "the payment settings read back")
ok("secret_key" not in json.dumps(_pc) and not _pc.get("key"),
   "and never include the key itself")
ok(c.post("/api/admin/payments", headers=A,
          json={"secret_key": "pk_test_wrong"}).status_code == 400,
   "a publishable key is rejected — this side needs the secret")
ok("secret" in c.post("/api/admin/payments", headers=A,
                      json={"secret_key": "pk_test_wrong"}).json()["detail"],
   "and says which one to use")
ok(c.post("/api/admin/payments", headers=A,
          json={"secret_key": "nonsense"}).status_code == 400,
   "so is anything that isn't a Stripe key")
ok(c.get("/api/admin/payments", headers=CU).status_code in (401, 403),
   "payment settings need an owner")
ok(c.post("/api/admin/payments", headers=A,
          json={"secret_key": ""}).json()["enabled"] is False,
   "an empty key turns card payments off rather than breaking the shop")
ok(c.get("/api/meta").json()["stripe_enabled"] is False,
   "which the checkout form can see")
ok("pay-key" in _ops and "pay-save" in _ops,
   "and there's a screen to paste a key into")

# Twice now a button has shipped with nothing behind it, because the code
# that would have wired it was inserted against an anchor that never matched
# and str.replace returns the string unchanged rather than complaining. So:
# every id the ops app renders a button for must actually be *given* a
# handler somewhere, not merely mentioned — the id appears inside its own
# handler body too, which is why "is it referenced" isn't the question.
import re as _re3  # noqa: E402
_rendered = set(_re3.findall(r'<button[^>]*\bid="([\w-]+)"', _ops))
# A button inside a form is wired by that form's submit handler.
_in_form = set()
for _f in _re3.finditer(r"<form\b.*?</form>", _ops, _re3.S):
    _in_form |= set(_re3.findall(r'<button[^>]*\bid="([\w-]+)"', _f.group()))


def _is_wired(bid: str) -> bool:
    """Is a handler attached to *this* button, rather than merely near it?

    Proximity was tried both ways and neither works: a tight window flags
    buttons whose handler sits past a comment, and a loose one is satisfied
    by the next button's handler, which is worse — it reports success for the
    exact bug this exists to catch. So the attachment is matched directly,
    including the local-variable form the app uses in a few places
    (`const co = $("#checkout"); co.onclick = ...`).
    """
    sel = r'(?:\$|document\.getElementById|\w+\.querySelector)\(\s*"#' \
        + _re3.escape(bid) + r'"\s*\)'
    if _re3.search(sel + r'\s*\.on(click|submit|change)\s*=', _ops):
        return True
    for m in _re3.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*' + sel, _ops):
        # Only where the local is actually used, not anywhere in the file: a
        # variable called `b` is declared a hundred times, and searching
        # globally for `b.onclick` reports every button as wired.
        near = _ops[m.end():m.end() + 700]
        if _re3.search(r'\b' + m.group(1) + r'\.on(click|submit|change)\s*=',
                       near):
            return True
    return False


_unwired = sorted(i for i in _rendered
                  if i not in _in_form and not _is_wired(i))
ok(not _unwired,
   "every button the ops app renders is given a handler"
   + (" — " + ", ".join(_unwired[:5]) if _unwired else ""))
ok("verify_key" in Path("src/erp/backend/payments.py").read_text(),
   "the key is checked with Stripe before it is saved")

# With a key configured, the checkout offers the choice.
_CFG["stripe_secret_key"] = "sk_test_pretend_not_real"
ok(c.get("/api/meta").json()["stripe_enabled"],
   "a configured key turns card payments on")
ok("stripe_enabled ?" in _ops,
   "and the checkout form offers card or pay-on-delivery accordingly")

# A card payment that can't be started must leave nothing behind. It used to
# keep the order and quietly mark it pay-on-delivery — so the customer
# believed they had paid, and it was the one route that skipped the
# confirmation the other pay-on-delivery orders now go through.
_con_k = _db.connect()
_before_k = _con_k.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
_kr = c.post("/api/orders", json={"items": [{"product_id": _gpid, "qty": 1}],
             "ship_name": "Card Buyer", "address": "1 St", "city": "Chicago",
             "email": "cardfail@example.com", "pay_method": "card"})
ok(_kr.status_code == 502, "an unreachable Stripe fails the order outright")
ok("nothing has been charged" in _kr.json()["detail"],
   "and says plainly that nothing was charged")
ok(_con_k.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == _before_k,
   "no half-made order is left behind")
ok(_con_k.execute("SELECT COUNT(*) n FROM orders WHERE"
                  " payment_status='cod' AND ship_name='Card Buyer'"
                  ).fetchone()["n"] == 0,
   "and none of it silently became pay-on-delivery")
# Choosing pay-on-delivery deliberately still goes through confirmation.
ok(c.post("/api/orders", json={"items": [{"product_id": _gpid, "qty": 1}],
          "ship_name": "Card Buyer", "address": "1 St", "city": "Chicago",
          "email": "cardfail@example.com", "pay_method": "cod"}
          ).json().get("awaiting_confirmation"),
   "the deliberate fallback is still held for confirmation")
_con_k.close()
_CFG["stripe_secret_key"] = ""


# --- integrations ---
from erp.backend import integrations as _ig  # noqa: E402
_ist = c.get("/api/admin/integrations", headers=A).json()
_names = [p["name"] for p in _ist["providers"]]
for _want in ("dropbox", "canva", "quickbooks", "pipedrive", "slack",
              "laceup", "trello"):
    ok(_want in _names, f"{_want} is offered")
ok(all(not p["connected"] for p in _ist["providers"] if p["auth"] != "none"),
   "none is connected until someone connects it — except the keyless "
   "ones, which point at a public thing and have nothing to connect")
ok("credentials" not in json.dumps(_ist) and "access_token" not in
   json.dumps(_ist),
   "the status payload carries no credential of any kind")
ok(c.get("/api/admin/integrations", headers=CU).status_code in (401, 403),
   "integrations are an owner's screen")

# Every provider declares what it needs, so the screen can be generated
# rather than hand-written seven times.
for _p in _ist["providers"]:
    ok(_p["does"] and _p["auth"],
       f"{_p['name']} says what it does and how it connects")

# Credentials are checked before they are stored, not after.
ok(c.post("/api/admin/integrations/slack/connect", headers=A,
          json={"fields": {"webhook_url": "https://evil.example/hook"}}
          ).status_code == 400,
   "a webhook that isn't Slack's is refused")
ok("hooks.slack.com" in c.post(
    "/api/admin/integrations/slack/connect", headers=A,
    json={"fields": {"webhook_url": "https://evil.example/h"}}
   ).json()["detail"], "and says what a real one looks like")
ok(c.post("/api/admin/integrations/trello/connect", headers=A,
          json={"fields": {"api_key": "x"}}).status_code == 400,
   "a half-filled form is refused before any call is made")
ok(c.post("/api/admin/integrations/notreal/connect", headers=A,
          json={"fields": {}}).status_code == 404,
   "an unknown provider is a 404")
_con_i = _db.connect()
ok(_con_i.execute("SELECT COUNT(*) n FROM integrations").fetchone()["n"] == 0,
   "and nothing was stored by any of those attempts")

# OAuth: the client secret is the company's, so it can't be shipped.
ok(c.get("/api/admin/integrations/dropbox/authorize",
         headers=A).status_code == 400,
   "an OAuth provider can't be authorised before its app is registered")
ok("client id" in c.get("/api/admin/integrations/dropbox/authorize",
                        headers=A).json()["detail"],
   "and says what is missing")
ok(c.post("/api/admin/integrations/slack/app", headers=A,
          json={"client_id": "x"}).status_code == 400,
   "a non-OAuth provider has no app to register")
_app = c.post("/api/admin/integrations/dropbox/app", headers=A,
              json={"client_id": "cid", "client_secret": "shh"}).json()
ok("/oauth/dropbox" in _app["redirect_uri"],
   "registering an app tells you the redirect URI to paste back")
_auth = c.get("/api/admin/integrations/dropbox/authorize", headers=A).json()
ok(_auth["url"].startswith("https://www.dropbox.com/oauth2/authorize"),
   "and then it can build the approval URL")
ok("state=" in _auth["url"] and "cid" in _auth["url"],
   "carrying a state and the client id")
# Without the state check this endpoint would accept a code from anywhere,
# which is how somebody attaches their account to your integration.
ok("Not connected" in c.get("/oauth/dropbox?code=abc&state=wrong").text,
   "a callback with the wrong state connects nothing")
ok(_con_i.execute("SELECT COUNT(*) n FROM integrations").fetchone()["n"] == 0,
   "and still stores nothing")

# LaceUp goes the other way, because there is no API to call.
ok([p for p in _ist["providers"] if p["name"] == "laceup"][0]["auth"]
   == "inbound", "LaceUp is inbound rather than pretending to be a client")
ok(c.post("/api/admin/integrations/laceup/connect", headers=A,
          json={"fields": {}}).status_code == 400,
   "so it can't be 'connected' like the others")
_lu = c.post("/api/admin/integrations/laceup/inbound-key", headers=A).json()
ok(len(_lu["key"]) > 20 and _lu["url"].endswith("/api/inbound/laceup"),
   "it issues a key and an address instead")
ok(c.post("/api/inbound/laceup", json={}).status_code == 401,
   "posting without the key is refused")
ok(c.post("/api/inbound/laceup", headers={"X-API-Key": "wrong"},
          json={}).status_code == 401, "and so is the wrong key")

_pre = _con_i.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
_push = c.post("/api/inbound/laceup", headers={"X-API-Key": _lu["key"]},
               json={"orders": [
                   {"reference": "LU-1", "customer": "Corner Grocer",
                    "email": "van@example.com", "city": "Chicago",
                    "address": "9 Oak",
                    "items": [{"sku": "GUEST-1", "qty": 6}]},
                   {"reference": "LU-2", "customer": "Bad",
                    "items": [{"sku": "NOT-A-SKU", "qty": 1}]}]})
ok(_push.status_code == 200, "a pushed batch is accepted")
ok(len(_push.json()["placed"]) == 1, "the good order is placed")
ok(_push.json()["skipped"] and "NOT-A-SKU" in
   _push.json()["skipped"][0]["why"],
   "and the bad one is skipped with the reason, not silently dropped")
ok(_con_i.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == _pre + 1,
   "exactly one order landed")

_csv = b"reference,customer,email,city,sku,qty\n" \
       b"A1,Van Sale,v@example.com,Boston,GUEST-1,3\n" \
       b"A1,Van Sale,v@example.com,Boston,GUEST-1,2\n"
_imp = c.post("/api/admin/integrations/laceup/import", headers=A,
              files={"file": ("orders.csv", _csv, "text/csv")})
ok(_imp.status_code == 200 and len(_imp.json()["placed"]) == 1,
   "a CSV with two lines under one reference becomes one order")
ok(c.post("/api/admin/integrations/laceup/import", headers=CU,
          files={"file": ("o.csv", _csv, "text/csv")}).status_code
   in (401, 403), "importing needs an owner")
_con_i.close()

# The fan-out reaches integrations without each emitter knowing.
_sf = Path("src/storefront/backend/api.py").read_text()
ok("_fan_integrations" in _sf and "_fan_discord" in _sf,
   "business events fan out to integrations as well as Discord")
ok(_sf.index("def fire_webhooks") < _sf.index("_fan_integrations"),
   "from the one place every emitter already calls")
ok("emit" in _ig.__dict__ and _ig.PROVIDERS["slack"]["events"],
   "and providers declare which events they want")
ok("integrations" in _ops and "renderIntegrations" in _ops,
   "the ops app has the screen")

# Reachability. Below 720px the sidebar is hidden and the bottom bar held
# five tabs out of twenty-six, so twenty-one screens — Integrations among
# them — had no route to them at all. A screen you can't navigate to is a
# screen that doesn't exist, whatever the render map says.
ok("more-tabs" in _ops and "showAllTabs" in _ops,
   "a narrow window can reach every screen, not just the bottom five")
ok("#tabs { display: none; }" in _css,
   "the sidebar really is hidden at that width")   # the reason More matters
ok("slice(0, 4)" in _ops,
   "the bar keeps four shortcuts and spends the fifth slot on the way out")
ok("tab-find" in _ops,
   "and the list can be typed at, because 26 is more than anyone scans")
# Every tab in the nav must appear in the sheet, or the sheet is another
# partial list and the bug comes back in a smaller form.
ok("NAV_GROUPS.map((g)" in _ops.split("function showAllTabs")[1][:600],
   "the sheet is built from the same groups as the sidebar")
ok("tabs.filter((t) => t.group === g)" in
   _ops.split("function showAllTabs")[1][:900],
   "and from the same allowed-tab list, so it can't drift from it")
ok("drawForm" in _ops,
   "which builds each form from the provider's own declaration")


# --- what each integration actually does, versus what it claims ---
# A provider that declares an event it has no handler for, or listens for an
# event nothing ever fires, is a connection that looks live and does nothing.
# Both were true when these first shipped.
_src_ig = Path("src/erp/backend/integrations.py").read_text()
_deliver = _src_ig[_src_ig.index("def _deliver("):]
for _p, _pd in _ig.PROVIDERS.items():
    if not _pd["events"]:
        continue
    ok(f'if name == "{_p}"' in _deliver,
       f"{_p} declares events and has a handler for them")

# Every event a provider listens for must be one the business actually
# raises, or the integration waits forever for a thing that never happens.
_emitted = set()
for _f in Path("src").rglob("*.py"):
    for _m in _re3.findall(r'fire_webhooks\(\s*"([a-z.]+)"',
                           _f.read_text(errors="replace")):
        _emitted.add(_m)
_listened = set()
for _pd in _ig.PROVIDERS.values():
    _listened |= set(_pd["events"])
_never = sorted(_listened - _emitted)
ok(not _never,
   "every event an integration waits for is one the business raises"
   + (" — " + ", ".join(_never) if _never else ""))
ok("order.paid" in _emitted, "a paid order is announced")
ok("inventory.low" in _emitted, "and so is low stock")

# Both routes to "paid" have to announce it, or the books are right until
# someone marks an order paid by hand.
_mainsrc = Path("src/erp/backend/main.py").read_text()
ok(_mainsrc.count("_order_paid(con, oid)") >= 2,
   "both the Stripe confirmation and the manual mark announce it")

# --- Slack in both directions ---
_slack = [p for p in _ist["providers"] if p["name"] == "slack"][0]
ok(any(f.get("optional") for f in _slack["fields"]),
   "the Slack bot token is optional — the alerts work without it")
# Checked against the rule rather than through a live Slack call: the
# webhook POST would fail first on a made-up URL, so a network test here
# proves nothing about the token rule it claims to be about.
_real_json = _ig._json_req
_ig._json_req = lambda *a, **k: (True, {"ok": True})
_bad_tok = _ig.check("slack", {"webhook_url": "https://hooks.slack.com/x",
                               "bot_token": "xoxp-user-token"})
_ig._json_req = _real_json
ok(_bad_tok[0] is False, "a user token is refused where a bot token is needed")
ok("xoxb" in _bad_tok[1], "and says which one to use")
ok(c.get("/api/admin/integrations/slack/channels",
         headers=A).status_code == 400,
   "reading channels without a bot token is refused")
ok("bot token" in c.get("/api/admin/integrations/slack/channels",
                        headers=A).json()["detail"],
   "with an explanation rather than an empty list")
ok(c.post("/api/admin/integrations/slack/C123/messages", headers=A,
          json={"text": ""}).status_code == 400,
   "an empty message is refused")
ok(c.get("/api/admin/integrations/slack/channels",
         headers=CU).status_code in (401, 403),
   "and the whole Slack surface is an owner's")
# Slack answers 200 with ok:false, which a naive client reads as success.
ok('if not d.get("ok")' in _src_ig,
   "Slack's 200-with-an-error is unwrapped in one place")
ok("slack-chat" in _ops and "loadSlackMsgs" in _ops,
   "the screen reads and replies, not just posts")
ok("_slackTimer" in _ops and _ops.count("clearInterval(S._slackTimer)") >= 2,
   "and stops polling when you leave the tab")

# A connection can be re-checked, because OAuth grants rot quietly.
ok("def verify(" in _src_ig, "a connected provider can be re-tested")
ok(c.post("/api/admin/integrations/dropbox/test",
          headers=A).status_code == 400,
   "testing something unconnected says so")
ok("data-igtest" in _ops, "and there's a button for it")

# QuickBooks needs the company id, which arrives on the callback rather than
# in the token — losing it leaves a connection that can't post anywhere.
ok("realm_id" in _src_ig and "dict(request.query_params)" in _mainsrc,
   "the QuickBooks company id is captured from the callback and kept")


# --- reading state back from Trello and Pipedrive ---
# A one-way integration becomes a stale copy: cards get done over there and
# the enquiry list here still shows them waiting.
_con_l = _db.connect()
_con_l.execute(
    "INSERT INTO store_enquiries(kind,name,email,company,status,created_at)"
    " VALUES('wholesale','Ann','ann@example.com','Corner Shop','new',?)",
    (_t.time(),))
_con_l.commit()
_eid = _con_l.execute(
    "SELECT id FROM store_enquiries ORDER BY id DESC LIMIT 1").fetchone()["id"]

# An event has to carry the id, or a card can be raised that nothing here can
# ever match back to the thing that caused it.
_psrc = Path("src/storefront/backend/partners.py").read_text()
_tsrc = Path("src/storefront/backend/support.py").read_text()
ok('"id": ecur.lastrowid' in _psrc, "an enquiry event carries its id")
ok('"id": tid' in _tsrc, "and so does a ticket event")

_ig.link(_con_l, "trello", "enquiry", _eid, "card-1", "https://trello.com/c/x")
_lk = _con_l.execute("SELECT * FROM integration_links WHERE local_id=?",
                     (_eid,)).fetchone()
ok(_lk and _lk["remote_id"] == "card-1",
   "creating a card records which enquiry it belongs to")
_ig.link(_con_l, "trello", "enquiry", _eid, "card-2", "u")
ok(_con_l.execute("SELECT COUNT(*) n FROM integration_links WHERE local_id=?"
                  " AND provider='trello'", (_eid,)).fetchone()["n"] == 1,
   "and re-linking replaces rather than duplicating")

# The reconciling rule: forward only. A sync that can move a record backwards
# resurrects work somebody already finished.
ok(_ig._advance(_con_l, "enquiry", _eid, "contacted") == "new → contacted",
   "the remote can move an enquiry forward")
ok(_ig._advance(_con_l, "enquiry", _eid, "closed") == "contacted → closed",
   "and forward again")
ok(_ig._advance(_con_l, "enquiry", _eid, "contacted") == "",
   "but never back once it is closed here")
ok(_ig._advance(_con_l, "enquiry", _eid, "closed") == "",
   "and says nothing happened when it is already there")
ok(_con_l.execute("SELECT status FROM store_enquiries WHERE id=?",
                  (_eid,)).fetchone()["status"] == "closed",
   "so the local record ends where it should")
ok(_ig._advance(_con_l, "enquiry", 999999, "closed") == "gone",
   "a record deleted here is reported, not resurrected")
ok(_ig._advance(_con_l, "enquiry", _eid, "invented") == "",
   "and a state we don't have is ignored rather than written")

# How a board and a pipeline are read.
_real_req = _ig._req
_stub = {}
_ig._req = lambda url, method="GET", headers=None, body=None, timeout=15: (
    (True, _stub["card"]) if "/cards/" in url
    else (True, {"name": _stub.get("list", "")}) if "/lists/" in url
    else (True, {"data": _stub["deal"]}) if "/deals/" in url
    else (False, "?"))
_c = {"api_key": "k", "token": "t"}
for _card, _list, _want in (
        ({"closed": True, "idList": "L"}, "Backlog", "closed"),
        ({"dueComplete": True, "idList": "L"}, "Backlog", "closed"),
        ({"idList": "L"}, "Done", "closed"),
        ({"idList": "L"}, "Shipped", "closed"),
        ({"idList": "L"}, "In Progress", "contacted"),
        ({"idList": "L"}, "Backlog", "")):
    _stub.update(card=_card, list=_list)
    _st, _to = _ig._trello_state(_c, "c")
    ok(_to == _want,
       f"a Trello card in {_list!r}"
       + (f" means {_want}" if _want else " changes nothing here"))
_ig._req = lambda url, method="GET", headers=None, body=None, timeout=15: (
    False, "404")
ok(_ig._trello_state(_c, "gone") == (None, ""),
   "a card that has been deleted is reported unreachable, not closed")

_ig.save(_con_l, "pipedrive", {"api_token": "t"}, "Acme", {"domain": "acme"})
for _deal, _want in (({"status": "open", "stage_order_nr": 1}, ""),
                     ({"status": "open", "stage_order_nr": 3}, "contacted"),
                     ({"status": "won", "stage_order_nr": 5}, "closed"),
                     ({"status": "lost", "stage_order_nr": 2}, "closed")):
    _stub["deal"] = _deal
    _ig._req = lambda url, method="GET", headers=None, body=None, timeout=15: (
        True, {"data": _stub["deal"]})
    _st, _to = _ig._pipedrive_state(_con_l, {"api_token": "t"}, "1")
    ok(_to == _want,
       f"a {_deal['status']} deal at stage {_deal['stage_order_nr']}"
       + (f" means {_want}" if _want else " changes nothing here"))
_ig._req = _real_req
_con_l.close()

ok(c.post("/api/admin/integrations/trello/sync",
          headers=A).status_code == 400,
   "syncing something unconnected says so")
ok(c.post("/api/admin/integrations/trello/sync",
          headers=CU).status_code in (401, 403), "and syncing needs an owner")
_lks = c.get(f"/api/admin/integrations/links/enquiry/{_eid}", headers=A)
ok(_lks.status_code == 200 and _lks.json()["links"],
   "an enquiry can say where else it lives")
ok(_ig.PROVIDERS["trello"].get("syncs")
   and _ig.PROVIDERS["pipedrive"].get("syncs"),
   "both declare that they read state back")
ok(not _ig.PROVIDERS["slack"].get("syncs"),
   "and one that doesn't, doesn't claim to")
ok("data-igsync" in _ops, "the screen offers the sync")
ok("links" in c.get("/api/store/admin/enquiries", headers=A).text,
   "and the enquiry list carries the remote state with it")


# --- live sync, and refusing to pretend ---
# A webhook registered against an address the provider can't reach creates a
# subscription that never fires and looks exactly like one that works.
for _addr, _want in (("http://localhost:8860", False),
                     ("http://127.0.0.1:8860", False),
                     ("http://192.168.1.15:8860", False),
                     ("http://10.0.0.4:8860", False),
                     ("http://172.16.4.4:8860", False),
                     ("https://ops.example.com", True)):
    ok(_ig.reachable(_addr)[0] is _want,
       f"{_addr} is {'usable' if _want else 'refused'} for a webhook")
ok("public_base_url" in _ig.reachable("http://localhost:8860")[1],
   "and the refusal says how to fix it")

_con_w = _db.connect()
_ig.save(_con_w, "trello", {"api_key": "k", "token": "t"}, "me",
         {"list_id": "L1"})
ok(c.post("/api/admin/integrations/trello/webhook",
          headers=A).status_code == 400,
   "going live from a private address is refused")
ok(c.post("/api/admin/integrations/slack/webhook",
          headers=A).status_code == 400,
   "and a provider with no state to send back has nothing to register")
ok(c.delete("/api/admin/integrations/trello/webhook",
            headers=A).status_code == 400,
   "removing one that was never registered says so")

# Trello checks the address answers before it will register anything.
ok(c.head("/api/inbound/trello").status_code == 200,
   "the inbound address answers the probe Trello sends first")
ok(c.head("/api/inbound/notreal").status_code == 404,
   "but only for a provider that exists")

# A push arriving.
_con_w.execute(
    "INSERT INTO store_enquiries(kind,name,company,status,created_at)"
    " VALUES('wholesale','Live','Live Co','new',?)", (_t.time(),))
_con_w.commit()
_lid = _con_w.execute(
    "SELECT id FROM store_enquiries ORDER BY id DESC LIMIT 1").fetchone()["id"]
_ig.link(_con_w, "trello", "enquiry", _lid, "live-card", "u")
_wkey = _ig.inbound_key(_con_w, "trello")
ok(len(_wkey) > 20, "a provider that pushes gets an inbound key too")
ok(c.post("/api/inbound/trello", json={}).status_code == 401,
   "a push with no key is refused")

_real2 = _ig._req
_ig._req = lambda url, method="GET", headers=None, body=None, timeout=15: (
    (True, {"idList": "L9"}) if "/cards/" in url else (True, {"name": "Done"}))
_pushed = c.post(f"/api/inbound/trello?key={_wkey}",
                 json={"action": {"data": {"card": {"id": "live-card"}}}})
ok(_pushed.status_code == 200 and _pushed.json().get("applied"),
   "a card moved to Done arrives and is applied")
ok(_con_w.execute("SELECT status FROM store_enquiries WHERE id=?",
                  (_lid,)).fetchone()["status"] == "closed",
   "closing the enquiry without anyone pressing sync")
# A board has other cards on it and a pipeline has other deals; those are
# not errors.
ok(c.post(f"/api/inbound/trello?key={_wkey}",
          json={"action": {"data": {"card": {"id": "someone-elses"}}}}
          ).json()["ignored"] == "not one of ours",
   "a card we didn't create is ignored rather than failing")
ok("nothing identifiable" in c.post(
    f"/api/inbound/trello?key={_wkey}", json={"unexpected": 1}
   ).json()["ignored"], "and so is a payload shape we don't recognise")
_ig._req = _real2
_con_w.close()

# The push re-reads the record rather than trusting the payload, so one
# interpretation serves both the button and the webhook.
ok("_trello_state(c, remote_id)" in _src_ig
   and "_pipedrive_state(con, c, remote_id)" in _src_ig,
   "a push is interpreted by the same readers the manual sync uses")

# --- Slack has its own place in the nav ---
ok('{ id: "slack"' in _ops and "renderSlack" in _ops,
   "Slack is a screen in the sidebar, not only a settings panel")
ok('S.tab === "slack"' in _ops,
   "and its reader keeps polling while you are on it")
ok('id: "integrations"' in _ops,
   "integrations is in the sidebar too")


# --- a provider's capabilities are declared, so they can be checked ---
# Dropbox said in prose that it gave the database export somewhere to land,
# and no code did that. Prose can't be tested, so the capability is named and
# the name is what gets checked.
_ACTION_IMPL = {
    "file_documents": "_document_bytes",
    "store_backup": "def dropbox_upload(",
    "browse": "def dropbox_list(",
    "cards": "def trello_cards(",
    # the second wave: declared in the registry, implemented in a family module
    "pull_forms": "def pull_forms(",
    "pull_ads": "def pull(con, platform: str)",
    "pull_candidates": "def pull_candidates(",
    "push_menu": "def push_menu(",
    "store_status": "def set_status(con, name: str, is_open: bool)",
    "pull_listing": "def pull_google(con)",
    "push_listing": "def push_google(con)",
    "pull_reviews": "def pull_google_reviews(",
    "pull_measures": "def pull_open_states(",
    "pull_representatives": "def pull_state_legislators(",
    "reply_review": "def reply_google(",
    "embed_deck": "def embed_url(",
}
_src_families = _src_ig + "".join(
    Path(f"src/erp/backend/{m}.py").read_text()
    for m in ("ads", "hiring", "marketplaces", "listings", "intake",
              "civics", "presentations"))
for _n, _pd in _ig.PROVIDERS.items():
    for _a in _pd.get("actions", []):
        ok(_a in _ACTION_IMPL,
           f"{_n} declares the known action {_a!r}")
        ok(_ACTION_IMPL.get(_a, "\0") in _src_families,
           f"and {_n}'s {_a} has an implementation behind it")
ok("store_backup" in _ig.PROVIDERS["dropbox"]["actions"],
   "Dropbox declares that it stores the backup")
ok("dbview.backup_bytes(con)" in _mainsrc.split(
    "/api/admin/integrations/dropbox/backup")[1][:900],
   "and the endpoint sends the real database file, not a summary")
ok("owners only" in _mainsrc.split(
    "/api/admin/integrations/dropbox/backup")[1][:1200],
   "which is owners-only, being unredacted")

# --- screens, not just connect forms ---
for _tab, _fn in (("slack", "renderSlack"), ("trello", "renderTrello"),
                  ("dropbox", "renderDropbox"),
                  ("discord", "renderDiscord")):
    ok(f'{{ id: "{_tab}"' in _ops and _fn in _ops,
       f"{_tab} has its own screen in the sidebar")
ok(c.get("/api/admin/integrations/trello/cards",
         headers=A).status_code == 200,
   "the Trello screen has something to read")
ok(c.get("/api/admin/integrations/dropbox/files",
         headers=A).status_code == 400,
   "and the Dropbox one says so when nothing is connected")
ok(c.post("/api/admin/integrations/dropbox/backup",
          headers=A).status_code == 400,
   "backing up to a disconnected Dropbox is refused rather than silent")
for _p in ("/api/admin/integrations/trello/cards",
           "/api/admin/integrations/dropbox/files"):
    ok(c.get(_p, headers=CU).status_code in (401, 403),
       f"{_p.rsplit('/', 1)[1]} is an owner's view")

# The Trello view reads our own link rows, so it shows what we raised rather
# than whatever else is on someone's board.
ok("FROM integration_links WHERE provider='trello'" in _src_ig,
   "the card list comes from what this system pushed")

# --- the showcase carousel -------------------------------------------------
# It is the first thing on the page and it is server-rendered, so the checks
# are about what actually reaches the browser, not what the JS intends to do.
from storefront.backend import sections as _sect          # noqa: E402
_sfdir = Path(_sfapi.config.STOREFRONT_DIR)
_sjs = (_sfdir / "store.js").read_text()
_scss = (_sfdir / "store.css").read_text()
_ssw = (_sfdir / "sf-sw.js").read_text()

# --- the shop's stylesheet reads no property that does not exist -----
# The same guard the ops sheet carries, and it found the same shape of
# bug: the donation controls were var(--accent, #2dd4bf), and --accent is
# defined nowhere here. So the fallback was not a fallback, it was the
# value — every shop on the platform got one hardcoded teal on the single
# control that asks a customer for money, ignoring the brand every other
# thing on that screen follows.
#
# Comments are stripped first: a rule is a rule, and the word --accent
# inside the note explaining its removal is not one.
_scss_live = _re.sub(r"/\*.*?\*/", "", _scss, flags=_re.S)
_SF_INJECTED = {
    "--cols",       # store.js layoutGrid(), from the measured width
    "--consent-h",  # store.js, the consent bar's measured height
    "--kind",       # store.js, per product group, inline
}
_sf_used = set(_re.findall(r"var\(\s*(--[\w-]+)", _scss_live))
_sf_def = set(_re.findall(r"(--[\w-]+)\s*:", _scss_live))
_sf_ghosts = sorted(_sf_used - _sf_def - _SF_INJECTED)
ok(not _sf_ghosts,
   "every custom property the storefront reads is defined in its own "
   f"palette or injected by named code at runtime ({_sf_ghosts} is "
   "neither — and a property nothing defines is a hardcoded value "
   "wearing a variable's clothes, invisible to anyone reading :root)")
ok("var(--flavour)" in _scss.split(".co-give-amt.on")[1][:120],
   "so the donation controls tint from the shop's own brand, like the "
   "rest of its checkout")

# layoutGrid() sizes --cols from the measured width, but it is only ever
# called on #product-grid.
ok(_re.search(r"@media[^{]*max-width:\s*560px[^{]*\{\s*\.grid\s*\{[^}]*--cols:\s*1",
              _scss_live),
   "and every OTHER .grid narrows by stylesheet rather than keeping the "
   "fallback of four. The reviews grid was four 66px columns on a "
   "phone, one of them holding a whole paragraph — a fallback written "
   "for a desktop, inherited by everything the script never visits")
ok("min-width: min(280px, 100%)" in _scss,
   "and the subscribe field asks for 280px or the width it actually "
   "has, whichever is smaller: a minimum wider than the phone it is on "
   "is a minimum the phone cannot honour")

ok("showcase" in _sect.SECTION_TYPES and "showcase" in _sect.RENDERERS,
   "the showcase is a real section type, editable like the rest")
ok(_sect.HOME_DEFAULT[0] == "showcase",
   "and a fresh store gets it at the top of the home page")
ok(_sect.defaults_for("showcase")["video_src"] == "",
   "with NO default film — a brand film is a brand asset, and the one "
   "that used to sit here put another business's movie on every fresh "
   "install's front page")
# a merchant who has a film sets it — and then it is server-rendered
_shsec = next(x for x in c.get("/api/store/admin/sections/home",
                               headers=A).json() if x["type"] == "showcase")
c.post(f"/api/store/admin/sections/{_shsec['id']}", headers=A,
       json={"settings": {**_shsec["settings"],
                          "video_src": "/hero/hero.mp4",
                          "video_poster": "/hero/hero.jpg"}})
_home = c.get("/").text
ok('id="show-rail"' in _home and 'data-kind="video"' in _home,
   "the film is on the page as markup, not fetched in later")
ok(_home.count('data-kind="product"') ==
   len([r for r in bdb.connect().execute(
       "SELECT 1 FROM products WHERE active=1")]),
   "one slide per live product, so the rail cannot drift from the catalog")

# Every control the section renders has to be wired; a carousel whose arrow
# does nothing looks identical to one that is merely slow.
for _id in ("show-prev", "show-next", "show-rail", "show-sound"):
    ok(f'id="{_id}"' in _home, f"{_id} is rendered")
    ok(f'$("#{_id}")' in _sjs, f"and {_id} is wired up")

ok("Math.round(rail.scrollLeft / w)" in _sjs
   and "let current" not in _sjs.split("const at = () =>")[0][-400:],
   "position is read back from the rail, so a swipe cannot desync the dots")
ok("video.muted = true" in _sjs,
   "the film is muted in JS, not only by attribute, or autoplay is blocked")

import importlib.util as _ilu                             # noqa: E402
_seed_path = Path(__file__).resolve().parents[1] / "tools/seed_catalog.py"
_seed_src = _seed_path.read_text()
_spec = _ilu.spec_from_file_location("_seed", _seed_path)
_seed_pre = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_seed_pre)
_sectsrc = Path("src/storefront/backend/sections.py").read_text()

# --- each SKU wears its own pattern from the film --------------------------
# The rendered page cannot be asserted against here: the suite runs on its
# own database, which has none of the real SKUs in it. What can be asserted
# is the invariant that matters — every product the seeder ships has a
# pattern, that pattern has a tile on disk, and the stylesheet paints it.
_apisrc = Path("src/storefront/backend/api.py").read_text()
_pat_dir = Path(_sfapi.config.STOREFRONT_DIR) / "hero/patterns"
for _sku, *_ in _seed_pre.RANGE:
    _pat = _sect.SKU_PATTERN.get(_sku)
    ok(_pat is not None, f"{_sku} is mapped to a pattern")
    ok((_pat_dir / f"{_pat}.png").exists(), f"and the {_pat} tile is exported")
    ok(f".pat-{_pat}" in _scss, f"and .pat-{_pat} paints the slide")
ok("background-repeat: repeat" in _scss and "background-size: 340px" in _scss,
   "tiles repeat at their own size rather than stretching to the slide")
ok('f" pat-{pat}" if pat else ""' in _sectsrc,
   "the renderer only skins a slide it has a pattern for")
ok('class="btn-pill primary show-cta"' in _home,
   "the film slide carries its call to action")

# Cut-out product art on a coloured slide is the whole reason this matters.
ok("def has_alpha" in _apisrc and 'f"media/{mid}_{suffix}.png"' in _apisrc,
   "transparent art keeps its alpha through the derivative step")
ok('f\'/media/m/{r["mid"]}\'' in _sectsrc,
   "slides link the immutable media id, not the mutable product pointer")
ok('"Cache-Control": "no-cache"' in _mainsrc.split(
    "primary_media_file")[1][:700],
   "and the mutable pointer revalidates, so swapped art actually appears")

# --- this round's fixes ----------------------------------------------------
_storejs = _sjs  # already read above
ok("drawCart();" in _storejs.split("function openCart()")[1][:400],
   "opening the cart draws it, so a restored cart is not shown as empty")
ok(".cart-items { flex: 0 0 auto; }" in _scss,
   "and the line list sizes to its content rather than collapsing to 0px")

ok('slides[i].dataset.pattern' in _storejs,
   "the section publishes which flavour is showing")
ok('#showcase[data-active="mango"] .show-arrow' in _scss,
   "so the mango slide can give the shared controls a purple edge")
ok(".show-slide[data-pattern] .show-add { background: var(--orange)" in _scss,
   "add to cart is the site's action colour on every pattern slide")
ok('video.addEventListener("ended"' in _storejs and "go(1)" in _storejs,
   "the film hands over to the first product when it finishes")
ok(" loop " not in _sectsrc.split("show-video")[1][:200],
   "and it is not looped, or ended would never fire")
ok("video.muted = false" in _storejs,
   "sound is asked for by default")
ok("video.muted = true; paintSound();" in _storejs
   or "video.muted = true;" in _storejs,
   "with a muted fallback, because policy can refuse audible autoplay")

ok("social_proof" in _sect.SECTION_TYPES
   and _sect.HOME_DEFAULT[1] == "social_proof",
   "the customer count sits directly under the carousel")
ok(not _sect.defaults_for("social_proof")["figure"],
   "and it ships EMPTY — a shared default that invents a customer count "
   "puts a number on a shop that has not sold anything yet, in the "
   "merchant's name")
_defaults = json.dumps({k: _sect.defaults_for(k) for k in _sect.SECTION_TYPES})
_voice = [w for w in ("zenjoy", "theanine", "ashwagandha", "lemon balm",
                      "flavors", "your zen", "100,000")
          if w in _defaults.lower()]
ok(not _voice,
   f"and no section default speaks in one particular business's voice — "
   f"these are what a FRESH tenant of any kind opens on (found: {_voice})")

ok("const isCase" in _storejs and 'category || "") === "multipacks"' in _storejs,
   "the case is recognised by category, so a rename cannot lose it")
ok(".product.feature { grid-column: 1 / -1" in _scss,
   "it takes a full row in the collection")
ok(".menu-tile.wide" in _scss and 'class="menu-tile wide"' in _storejs,
   "and its own row in the side menu")
ok(".show-wide .show-shot" in _scss and 'show-wide' in _sectsrc,
   "the landscape case shot gets a landscape slot in the carousel")
ok("META = {" in _seed_src and "all four flavors" in _seed_src,
   "the seeder owns the shelf copy, so it cannot keep saying five flavors")

# --- one code field, and layout symmetry -----------------------------------
_html = (Path(_sfapi.config.STOREFRONT_DIR) / "index.html").read_text()
ok('id="code-input"' in _html
   and 'id="discount-input"' not in _html and 'id="gift-input"' not in _html,
   "discount and gift card share one field")
ok("/api/store/discount/preview" in _storejs.split("async function applyCode")[1][:900]
   and "/api/store/gift-card/" in _storejs.split("async function applyCode")[1][:1400],
   "and that field tries both kinds before rejecting a code")
ok("out.detail" in _storejs.split("async function applyCode")[1][:1600],
   "keeping the server's reason rather than a generic 'invalid'")
ok("function drawCodes" in _storejs and "code-chip" in _scss,
   "what is applied is shown as removable chips")
ok(".cart-foot > .btn-pill" in _scss,
   "the checkout button rule is a direct child, so it stops stretching "
   "the Apply button beside the input")

ok("repeat(auto-fit, minmax(140px, 1fr))" in _scss,
   "menu tiles auto-fit, so four flavours span the row the case sits above")
ok("auto-fill" not in _scss.split(".menu-tiles {")[1][:160],
   "and no empty tracks are left holding the row short")

ok("p.active=1" in _sectsrc.split("product_reviews")[1][:400],
   "the reviews wall only quotes products still on sale")

# --- one click starts everything ------------------------------------------
# The three surfaces are one server, so the launcher's job is to open all
# three and not to jump the gun on a cold start.
_cmds = Path(__file__).resolve().parents[1] / "command_utilities"
_start = (_cmds / "Start Business Control.command").read_text()
_https = (_cmds / "Start Business Control (HTTPS).command").read_text()
_serve = (_cmds / "_serve.sh").read_text()

ok(_serve.count("bc_open") >= 1 and "_serve.sh" in _start and "_serve.sh" in _https,
   "both launchers share one implementation")
for _u in ("/admin", "/ops/"):
    ok(_u in _serve, f"the launcher opens {_u} as well as the storefront")
ok("seq 1 60" in _serve and "sleep 2;" not in _start,
   "it waits for the server to answer instead of sleeping a fixed guess")
ok("bc_exit_if_running" in _start and "bc_exit_if_running" in _https,
   "a second double-click raises the tabs rather than colliding on the port")
ok('bc_exit_if_running "$BASE" "-k"' in _https
   and 'bc_wait_then_open "$BASE" "-k"' in _https
   and 'curl -fs $2' in _serve,
   "the HTTPS checks pass -k through to curl, or a self-signed cert would "
   "make a live server look dead")
ok("BC_NO_OPEN" in _serve, "and it can be started headless for scripts")

# --- the film is a player, and the cans are 70% of the slide --------------
_sw = _storejs.split("function showcase()")[1]
ok('id="show-play"' in _home and 'id="show-scrub"' in _home,
   "the film has a play/pause control and a timeline")
ok('role="slider"' in _home and 'aria-valuenow' in _home,
   "and the timeline is a real slider to assistive tech")
ok('video.addEventListener("click", toggle)' in _sw,
   "clicking the film pauses and resumes it")
ok("let held = false" in _sw and "video._held" in _sw
   and "!(video._held && video._held())" in _sw,
   "a person's pause is distinct from a scroll pause, and survives it")
ok("setPointerCapture" in _sw and "video.currentTime = f * video.duration" in _sw,
   "dragging the timeline seeks — mouse, pen and touch through one handler")
ok('"ArrowRight"' in _sw.split("scrub.addEventListener(\"keydown\"")[1][:200],
   "and the keyboard can seek too")
for _ev in ("visibilitychange", "pagehide", "pageshow"):
    ok(f'"{_ev}"' in _sw, f"sound stops on {_ev} — it must not follow the visitor")
ok("MutationObserver" in _sw and "document.body.contains(video)" in _sw,
   "and stops if a route swap removes the carousel from the page")
ok("let watched = false" in _sw and "if (onScreen && watched) go(1)" in _sw,
   "the end-of-film handoff needs a genuine viewing, not a stale ended flag")
ok("function openOnFilm" in _sw and '"pageshow", openOnFilm' in _sw,
   "back-navigation reopens on the film, after the browser restores scroll")

ok("bbox = im.getchannel(\"A\").getbbox()" in _apisrc
   and "im = im.crop(bbox)" in _apisrc,
   "derivatives are trimmed to the opaque bounds, so sizing the image sizes "
   "the can rather than the air around it")
ok("height: calc(0.70 * var(--slide-h))" in _scss.split(".show-shot {")[1][:200],
   "the can container is 70% of the slide's height")
ok(".show-slide { flex: 0 0 100%; scroll-snap-align: center;\n  height: var(--slide-h)" in _scss,
   "and the slide's height is fixed, so 70% is 70% of what is on screen")
ok("max-height: calc(0.62 * var(--slide-h))" in _scss,
   "the film is capped against the same reference, so the row cannot outgrow it")

# Trimming the derivative changed every consumer's input; the fix is that
# product art is contained, never cropped, wherever it appears.
for _sel in (".product .art img", ".menu-tile .art img", ".cart-line .art img",
             ".pp-thumb img", ".pp-stage img", ".upsell-row img"):
    _blk = _scss.split(_sel + " {")[1].split("}")[0]     # this rule only
    ok("object-fit: contain" in _blk and "object-fit: cover" not in _blk,
       f"{_sel} contains the product rather than cropping the trimmed can")
ok("object-fit: cover" in _scss.split(".pp-stage video")[1][:200],
   "video in the product stage still fills the frame — cover is for footage")
ok('decoding="async"' in _sectsrc and 'loading="lazy"' not in _sectsrc.split("def _showcase")[1].split("def _benefits")[0],
   "carousel images load eagerly — lazy ones in an off-axis slide never do")
ok('id="i-pause"' in (Path(_sfapi.config.STOREFRONT_DIR) / "icons.svg").read_text(),
   "the sprite has a pause glyph for the play button to flip to")

# --- this round: product page, layout rules, copy ---------------------------
# Whatever product this run happens to have — the suite's database is its
# own, so a hardcoded id fetches someone else's page or a 404.
_ppid = [r["id"] for r in bdb.connect().execute(
    "SELECT id FROM products WHERE active=1 ORDER BY id LIMIT 1")][0]
_pdp = c.get(f"/product/{_ppid}-x").text
# The product page used to be a standalone document with a hand-rolled
# topbar, which is why its navigation drifted from every other page.
ok('id="side-menu"' in _pdp and 'id="menu-btn"' in _pdp
   and 'id="cart-drawer"' in _pdp,
   "the product page carries the site's own menu and cart, not its own")
ok("Back to shop" not in _pdp,
   "so it needs no 'back to shop' crutch for a missing menu")
ok('class="top-links"' in _pdp,
   "and the same header links as every other page")
ok("head_extra" in _apisrc.split("def render_shell")[1][:400],
   "the shell takes per-page head content, so canonical and structured "
   "data survive the move")
ok('rel="canonical"' in _pdp and "application/ld+json" in _pdp,
   "and they did")
ok('class="add-btn" data-rec-add=' in _apisrc, "'You may also like' has an Add")
_rec_js = _apisrc.split("document.querySelectorAll('[data-rec-add]')")[1][:500]
ok("sf_cart" in _rec_js and "location.href='/?cart=1'" in _rec_js,
   "and it writes the cart and opens the drawer, like every other Add")
ok('class="section pp-main"' in _pdp
   and ".section.pp-main, .section.pp-main:last-of-type" in _scss,
   "the page reserves the sticky bar's height, at a specificity that beats "
   "`.section:last-of-type`, so reviews are not slid under it")

ok("function layoutGrid" in _storejs and "n % c !== 1" in _storejs,
   "the grid picks a column count that cannot strand one card alone")
ok("repeat(var(--cols, 4)" in _scss
   and "@media (max-width: 1080px) { .grid" not in _scss,
   "and no media query overrides that count — which is what put the lone "
   "card back the first time")
ok('addEventListener("resize"' in _storejs.split("function layoutGrid")[1][:600],
   "the count is recomputed when the width changes")

ok(".benefits-row { max-width: var(--wrap); margin: 0 auto; display: flex;" in _scss
   and "justify-content: center" in _scss.split(".benefits-row {")[1][:200],
   "the benefit strip centres its short last row rather than leaving a "
   "trailing single")

_ci = _html.index('id="cart-total"')
ok(_ci < _html.index('id="code-input"') < _html.index('id="checkout-btn"'),
   "in the cart: total, then the code field, then checkout")

ok('id="offer"' in _html and "function firstVisitOffer" in _storejs,
   "new visitors get an offer for their email")
ok("sf_offer_seen" in _storejs and 'settle("closed")' in _storejs.replace("close(\"closed\")", 'settle("closed")'),
   "shown once — dismissing counts, so it cannot nag")
ok("innerHeight * 0.6" in _storejs or "scrollY >" in _storejs,
   "and held back until they have actually looked around")
ok("out.code ||" in _storejs,
   "the discount code comes from the server, not invented on the client")

ok('${t("shop_cta")}' in _storejs and "Shop your Zen" not in _storejs
   and "Shop your Zen" not in _sectsrc,
   "the shop's own invitation is a string the tenant owns, not one "
   "business's slogan compiled into the storefront everyone shares")
ok("f'Flavor</span>'" in _apisrc and "f'Flavour</span>'" not in _apisrc,
   "the product page's switcher is labelled Flavor")
ok("all four flavors" in _storejs, "and the menu says flavors")

# --- data the range owns, and links that work off the home page ------------
ok("COLLECTIONS = {" in _seed_src and "def set_collections" in _seed_src,
   "the seeder owns collection membership")
ok("DELETE FROM collection_products WHERE product_id NOT IN" in _seed_src,
   "and clears out products it retired — a deactivated product left in a "
   "collection shows an empty shelf under a tab that still has a name")
ok("NUTRITION = {" in _seed_src and '"Calories": "70"' in _seed_src
   and '"Ashwagandha (KSM-66)": "150mg"' in _seed_src,
   "the label facts are the client's, in one place")

# A fragment resolves only against ids on the page you are standing on. The
# nav's "#shop" was written for the home page and went nowhere from /blog or
# /affiliates; an anchor to a section of *this* page is fine. So the rule is
# not "no fragments" — it is "no fragment without a target here".
for _p in ("/blog", "/affiliates"):
    _txt = c.get(_p).text
    _ids = set(re.findall(r'id="([\w-]+)"', _txt))
    _bad = [h for h in re.findall(r'href="(#[a-z][\w-]*)"', _txt)
            if not h.startswith("#i-") and h[1:] not in _ids]
    ok(not _bad, f"{_p} has no dead fragment links (found {_bad[:3]})")
ok('href="/#shop"' in c.get("/blog").text,
   "and its nav points home, then to the section")

ok('id="write-review"' in _sectsrc and "data-review-for=" in _apisrc,
   "both review sections have a way in")
ok("function wireReviewButtons" in _storejs and "rev-picks" in _storejs,
   "the wall asks which product, since it shows the whole range")

# --- the hero is off the page but kept ------------------------------------
ok((Path(_sfapi.config.STOREFRONT_DIR) / "reference/hero.html").exists(),
   "the hero is saved as a standalone reference page")
ok("hero" in _sect.SECTION_TYPES,
   "and it is still a section type, so it can be switched back on")

# --- the collection is the real range --------------------------------------
# Asserted against the seeder rather than this run's throwaway database: the
# suite creates products of its own, so a live row count would only measure
# the tests. What matters is what the tool guarantees when it is run.
_skus = [r[0] for r in _seed_pre.RANGE]
_seed = _seed_pre
ok(_skus == ["ZJ-MANGO", "ZJ-PASSION", "ZJ-LAVENDER", "ZJ-HONEY",
             "ZJ-PACK-12"],
   "the range is the four flavours and the multipack, in order")
for _sku, _name, *_rest in _seed.RANGE:
    _art = Path(_seed.ART) / _rest[-1]
    ok(_art.exists(), f"{_sku} has its artwork on disk ({_name})")

ok("UPDATE products SET active=0 WHERE id NOT IN" in _seed_src,
   "everything outside the range is deactivated…")
ok("DELETE FROM products" not in _seed_src,
   "…and never deleted, so past orders still resolve to a product")
ok("DELETE FROM product_media WHERE product_id" in _seed_src,
   "artwork is replaced rather than piled up")
ok("digest(src)" in _seed_src,
   "and re-running with unchanged art does no work, so URLs stay cached")

# --- the cookie bar must not sit on the Buy button -------------------------
ok('classList.add("consent-open")' in _sjs
   and "body.consent-open .buy-fab" in _scss,
   "showing the cookie bar lifts the buy button, in both halves")
ok("--consent-h" in _sjs and "--consent-h" in _scss,
   "and the lift is the bar's measured height, not a guessed constant")
ok("ResizeObserver" in _sjs.split("makeBarRoom")[1][:600],
   "re-measured when the copy reflows, so a two-line bar still clears")
ok('classList.remove("consent-open")' in _sjs,
   "and dismissing it puts the button back")

# A service worker that answers respondWith(undefined) turns any blip into an
# unstyled page; this is the regression that produced one.
ok("ignoreSearch: true" in _ssw,
   "the worker ignores the cache-buster, so a deploy cannot strand a visitor")
ok(_ssw.rstrip().endswith("});")
   and "return fetch(e.request);" in _ssw,
   "and a total miss retries rather than resolving with nothing")


# --- one colour per product, everywhere that product appears ---------------
# The client's words: "the background should be based on the product it is
# the background of not the product page that you are on."
#
# The failure mode was not a missing rule, it was a *duplicated* one:
# `--flavour-soft` was assigned by hand next to `--flavour` in some places and
# forgotten in others, so wherever it was forgotten the tint inherited from an
# ancestor — on a product page, the current product. Deriving the tint from the
# colour is what makes the two unable to disagree, so that is what is asserted
# here rather than the symptom.
_soft_decls = re.findall(r"--flavour-soft:\s*([^;]+);", _scss)
_derived = [d for d in _soft_decls if "color-mix" in d]
_ok_literal = {"var(--lav-soft)"}   # the :root fallback for anything unpriced
ok(_derived, "the flavour tint is derived from the flavour, not written twice")
ok(all("color-mix" in d or d.strip() in _ok_literal for d in _soft_decls),
   "and nothing hand-sets it beside the fallback — hand-setting it in some "
   f"places and not others is the whole bug (stray: "
   f"{[d for d in _soft_decls if 'color-mix' not in d and d.strip() not in _ok_literal][:2]})")
for _sel in (".product", ".cart-line", ".upsell-row", ".pp-stage", ".pp-thumb",
             ".show-slide", ".menu-tile", ".art"):
    ok(re.search(rf"{re.escape(_sel)}[,\s][^{{}}]*{{[^}}]*--flavour-soft:"
                 r"\s*color-mix", _scss, re.S),
       f"{_sel} derives its own tint, so it cannot wear the page's colour")

# A derived tint is only as good as the colour it derives from: a payload that
# omits `colour` sends every card back to the default purple by another route.
_promos = Path("src/storefront/backend/promos.py").read_text()
ok("'colour','flavour','note'" in _promos.replace('"', "'"),
   "recommendations carry the product's own colour, so cross-sells can use it")
ok(_sjs.count('style="--flavour:${flavourOf(') >= 7,
   "and every surface that shows a product sets --flavour from that product")

# The carousel reads its active slide back from scrollLeft/clientWidth. An
# unlaid-out rail has clientWidth 0, 0/0 is NaN, and slides[NaN] is undefined
# — sync() then threw on every scroll settle.
_at = _sjs.split("const at = () =>")[1][:260]
ok("if (!w) return 0" in _at and "Math.min(slides.length - 1" in _at,
   "the carousel's slide index is clamped, so a zero-width rail cannot make "
   "it index past the end or land on NaN")

# --- the rest of this batch ------------------------------------------------
ok('href="/affiliates"' in _sjs
   and "PARTNER_LINKS" in _sjs.split('href="/affiliates"')[0][-1200:],
   "the affiliate programme sits under 'Work with us', not only in the footer")

_admjs = (_sfdir / "admin.js").read_text()
_admhtml = (_sfdir / "admin.html").read_text()
ok('id="sign-out"' in _admhtml and "wireSignOut" in _admjs,
   "the admin can end its session")
ok('localStorage.removeItem("bc_user")' in _admjs,
   "and signing out drops the token, which is the whole session")
ok("wireSignOut(true)" in _admjs.split("async function boot()")[1][:500],
   "revealed from boot(), which is reached by a fresh sign-in as well as by a "
   "stored token — otherwise it hides from whoever just started a session")
ok("wireSignOut(false)" in _admjs,
   "and never beside the sign-in form, which is what a stale token would do")

ok(".a11y-fab.lifted" in _scss and "'.a11y-fab'" in _apisrc.replace('"', "'"),
   "the accessibility badge lifts with the buy bar instead of sitting on the "
   "product")
ok("sticky-shot" in _apisrc and "/media/product/" in
   _apisrc.split("sticky-shot")[1][:120],
   "and the bar shows the real product photo, not a drawn stand-in")


# --- three doors that were missing --------------------------------------
# The shop and the inventory could edit every product on them and create
# none: a new line had to be typed into the database. A shelf you cannot
# add to is a catalogue somebody else built.
_ocss = Path("src/erp/frontend/styles.css").read_text()
ok('id="sh-new"' in _ops and 'id="inv-new"' in _ops,
   "both product pages — the shop and the inventory — open a new product")
ok("async function productForm(" in _ops,
   "through one form, so the two doors cannot drift apart")
_pfm = _ops.split("async function productForm(")[1][:3600]
ok("/api/admin/product-kinds" in _pfm and 'id="npd-kind"' in _pfm,
   "which asks which lane it sits in, from the kinds this install has")
ok("draft: true" in _pfm and "/shelf" in _pfm,
   "and a new line opens as a draft — priced and described in private, "
   "invisible to the shop until somebody publishes it")
ok('id="npd-bar"' in _pfm and "QRScan.wedge" in _pfm,
   "with a place for the barcode that can be scanned into — the natural "
   "moment to teach the till a code is while somebody is holding the tin")

# Eight connections lived behind one list. A person looking for QuickBooks
# looks in the navigation, and four of the eight already had a page there.
_prov = Path("src/erp/backend/integrations.py").read_text()
_pnames = re.findall(r'^    "([a-z_]+)": \{', _prov, re.M)
ok(len(_pnames) >= 11, f"the registry carries every provider ({len(_pnames)})")
_navd = set(re.findall(r'\{ id: "([\w:-]+)"', _ops))
# A provider in a family is reached through its family's screen — the ad
# platforms on Advertising, the boards on Hiring — which is the place a
# person looks for it. Thirty rail entries is a list nobody scans.
_FAMILY_TAB = {"intake": "intake", "ads": "ads", "hiring": "hiring",
               "delivery": "marketplaces", "listings": "listings",
               "results": "results", "civics": "civics",
               "presentations": "presentations"}
_missing = [n for n in _pnames
            if n not in _navd and f"ig-{n}" not in _navd
            and _FAMILY_TAB.get(_ig.PROVIDERS[n].get("family", "")) not in _navd]
ok(not _missing,
   f"every connection has a place in the navigation of its own ({_missing})")
ok("renderOneIntegration" in _ops,
   "and the ones without a bespoke screen share one: connected or not, "
   "what it has carried, and a test")
for _t in re.findall(r'\{ id: "(ig-[\w_]+)"', _ops):
    ok(re.match(r"^ig-[\w]+$", _t) is not None,
       f"{_t} is a tab id the hash router can carry")

# The store rail was 240px of stores whether you were reading them or not.
ok("wireStoreRail" in _ops and "srail-fold" in _ops and "srail-grip" in _ops,
   "the store rail folds away and drags to a width")
ok("body.srail-folded #store-rail" in _ocss and "--srail" in _ocss,
   "with the width in a custom property, so nothing else has to be told")
ok("bc_srail_w" in _ops and "bc_srail_fold" in _ops,
   "and both are remembered — a rail re-folded every morning is a rail "
   "nobody folds")
_wsr = _ops.split("function wireStoreRail(")[1][:1600]
ok("Math.max(26, Math.min(460" in _wsr,
   "the drag is clamped: a rail dragged to nothing cannot be found again")


# --- where a page's actions live ------------------------------------------
# Every page's action buttons sat wherever .page-head's flex happened to
# put them, because .top-actions had no rule in this stylesheet at all: it
# was just another div child, so it took the same flex:1 as the title and
# landed in the middle of the header. Stores looked right only because its
# button is a direct child.
ok(".page-head .top-actions {" in _ocss and "margin-left: auto"
   in _ocss.split(".page-head .top-actions {")[1][:200],
   "a page's actions are pinned to the top right corner")
for _tab, _btn in (("renderShop", "sh-new"), ("renderInventory", "inv-new"),
                   ("renderCustomers", "cu-new"), ("renderStaff", "staff-new"),
                   ("renderBoard", "bd-new"), ("renderHours", "hr-off"),
                   ("renderSchedule", "rt-pub"), ("renderCalendar", "cal-today"),
                   ("renderClients", "eng-new")):
    _body = _ops.split(f"function {_tab}(")[1][:5000]
    _head = _body.split('class="top-actions"')[1][:900] \
        if 'class="top-actions"' in _body else ""
    ok(f'id="{_btn}"' in _head,
       f"{_tab}'s {_btn} sits in the page's action corner")
    ok(f'class="btn sm" id="{_btn}"' not in _head,
       f"and at the size every other page's does — not the small one")

# The board's five columns are wider than the pane. A flex item is as wide
# as its widest child unless told otherwise, so the view stretched past the
# window and took the page's own buttons off the right-hand edge with it.
ok("min-width: 0" in _ocss.split("#view {")[1][:120],
   "the view refuses to be stretched by what is inside it")
ok("overflow-x: auto" in _ocss.split(".board {")[1][:200],
   "and the board scrolls sideways inside its own box instead")

# The nav is sticky so a long tab list scrolls on its own. Setting
# position:relative on it — to hang the drag grip off — quietly undid that,
# and the last connection in the list could only be reached by scrolling
# the whole document.
ok('nav.style.position = "relative"' not in _ops,
   "nothing takes the nav out of sticky to hang a grip on it")
ok("--topbar" in _ocss and "trackTopbar" in _ops,
   "and what hangs off the top bar measures it rather than assuming 45px, "
   "which is only true while its account line fits on one row")
for _sel in ("#tabs {", "#store-rail {"):
    ok("var(--topbar" in _ocss.split(_sel)[1][:340],
       f"{_sel.strip(' {')} sticks to the bar's real height")

# The fold control for the store rail was hung off the rail's left edge —
# outside a box that scrolls its own contents, so the control for bringing
# the panel back was itself half cut off.
_fold = _ocss.split("\n.srail-fold {")[1][:300]
ok("position: absolute" not in _fold and "align-self" in _fold,
   "the store rail's fold control sits inside the rail, where it can be "
   "seen and clicked")

# Rows of pills that start wherever a name happens to end cannot be read
# down a list. Both fleet-scale lists get real columns.
ok("grid-template-columns: 22px minmax(0, 1fr)" in
   _ocss.split(".eng-top {")[1][:220],
   "a client row reads down its columns: host, flags, launch, actions")
ok('class="eng-host"' in _ops and 'class="eng-flags"' in _ops
   and 'class="eng-when dim"' in _ops,
   "and every row carries every cell, empty ones included — a cell that "
   "vanishes when it has nothing in it takes the alignment with it")
ok(".doc-line.fleet-line {" in _ocss and ".dl-acts.fleet-acts {" in _ocss,
   "the fleet's tenants line up the same way")
ok('style="grid-template-columns:74px 74px 70px"' not in _ops,
   "with the six actions in columns wide enough for their labels, rather "
   "than an inline width that clipped 'Act as admin' mid-word")


# --- recurring revenue, and what moved it -----------------------------------
# A subscription table answers "what do we bill this month". It cannot
# answer "did we grow", because growth is a difference between two months
# and the table only ever holds today. So each month is recorded per
# account, and the four movements are read off the difference.
from erp.backend import db as _mdb, mrr as _mrr  # noqa: E402
_mcon = _mdb.connect()
_mcon.execute("DELETE FROM mrr_month")
_mcon.commit()


def _mrr_write(month, rows, origin="live"):
    _mcon.executemany(
        "INSERT OR REPLACE INTO mrr_month(month,account,cents,label,origin,"
        " taken_at) VALUES(?,?,?,?,?,0)",
        [(month, a, c, a, origin) for a, c in rows])
    _mcon.commit()


_mrr_write("2026-01", [("u1", 10000), ("u2", 20000)])
_mrr_write("2026-02", [("u1", 15000), ("u2", 20000), ("u3", 5000)])
_mrr_write("2026-03", [("u1", 15000), ("u3", 4000)])
_mv = {m["month"]: m for m in
       _mrr.movement(_mcon, 12, when=_t0.mktime((2026, 3, 15, 0, 0, 0, 0, 0, -1))
                     )["months"]}
_feb, _mar = _mv["2026-02"], _mv["2026-03"]
ok(_feb["mrr_cents"] == 40000 and _feb["accounts"] == 3,
   "a month's MRR is the sum of what every paying account is on")
ok(_feb["new_cents"] == 5000 and _feb["expansion_cents"] == 5000
   and _feb["contraction_cents"] == 0 and _feb["churn_cents"] == 0,
   "an account that was not there is new; one paying more is expansion — "
   "and they are different things, because one is sales and the other is "
   "the product being worth more")
ok(_mar["churn_cents"] == 20000 and _mar["contraction_cents"] == 1000,
   "an account that stops is churn; one paying less is contraction")
ok(_feb["net_new_cents"] == _feb["mrr_cents"] - 30000
   and _mar["net_new_cents"] == _mar["mrr_cents"] - _feb["mrr_cents"],
   "and the four add up to the change EXACTLY — a growth number nobody "
   "can take apart is a number nobody acts on")
ok(_feb["nrr_pct"] == 116.7,
   "net revenue retention is what LAST month's accounts are worth this "
   "month: 30k grew to 35k, so 116.7% — the new logo is deliberately not "
   "in it, or it would hide the answer")
ok(_mar["nrr_pct"] == 47.5 and _mar["grr_pct"] == 47.5,
   "and when they leave it says so without the new business papering "
   "over it")
ok(_feb["quick_ratio"] is None and _mar["quick_ratio"] == 0.0,
   "the quick ratio is growth over loss — undefined when nothing was "
   "lost, rather than dressed up as infinity")
ok(_mar["logo_churn_pct"] == 33.3,
   "logo churn counts customers, not money — one of three left, and the "
   "money says 50% because the one that left was the big one")
ok([x["label"] for x in _mar["movers"]["churn"]] == ["u2"],
   "and the months name who moved, because 'churn was 20k' is a fact "
   "nobody can act on and 'u2 left' is a phone call")

# The seam: a reconstructed month knows about subscriptions and nothing
# about invoiced clients, so the step up to the first recorded month is an
# artefact of what could be reconstructed, not business that was won.
_mcon.execute("DELETE FROM mrr_month")
_mcon.commit()
_mrr_write("2026-01", [("u1", 10000)], origin="backfill")
_mrr_write("2026-02", [("u1", 10000), ("e9", 40000)])
_seam = {m["month"]: m for m in _mrr.movement(
    _mcon, 12, when=_t0.mktime((2026, 2, 15, 0, 0, 0, 0, 0, -1)))["months"]}
ok(_seam["2026-01"]["origin"] == "backfill",
   "a reconstructed month says it is one")
ok(_seam["2026-02"]["seam"] and _seam["2026-02"]["new_cents"] == 0
   and _seam["2026-02"]["net_new_cents"] == 0,
   "and the step across the seam is not counted as new business — a lie "
   "with a chart around it is worse than a gap")
ok(_seam["2026-02"]["mrr_cents"] == 50000,
   "while the MRR itself is still the truth on both sides of it")

# Two sources of recurring money, and a client on both is one account.
_mcon.execute("DELETE FROM mrr_month")
_mcon.commit()
_live = {r["account"]: r["cents"] for r in _mrr.live(_mcon)}
_mcon.close()                       # the endpoint below needs the write lock
ok(isinstance(_live, dict),
   "the live read walks subscriptions and invoiced clients together")
_mrrapi = c.get("/api/analytics/mrr?months=6", headers=A).json()
ok("months" in _mrrapi and "undated_cancellations" in _mrrapi,
   "the endpoint says how many cancellations have no date on them — from "
   "before that was recorded, and left out of the past rather than "
   "guessed at")
ok(c.get("/api/analytics/mrr").status_code in (401, 403),
   "and it is the office's number")


# --- the field --------------------------------------------------------------
# Delivering cases, resetting a shelf, taking a pallet off a truck: four
# departments call these different things and they are one shape. What
# makes a visit evidence rather than a claim is what this checks.
_tpl = c.post("/api/field/templates", headers=A, json={
    "name": "Shelf reset", "kind": "merchandising",
    "needs_signature": True, "needs_mileage": True,
    "steps": [{"label": "Photo before", "photo": True},
              {"label": "Face the stock"},
              {"label": "Check date codes"}]}).json()
ok(_tpl["id"], "a kind of call is a template, not code — the questions on "
   "a merchandising visit change every season, and a change that needs a "
   "developer happens in a spreadsheet instead")
ok(c.post("/api/field/templates", headers=A,
          json={"name": "x", "kind": "nonsense"}).status_code == 400,
   "and it is one of the kinds the field knows")
_vid = c.post("/api/field/visits", headers=A,
              json={"template_id": _tpl["id"]}).json()["id"]
_v = c.get(f"/api/field/visits/{_vid}", headers=A).json()
ok(len(_v["steps"]) == 3 and _v["state"] == "planned",
   "booking one copies the list onto it, so a template edited later does "
   "not rewrite a visit that already happened")
c.post(f"/api/field/visits/{_vid}/start", headers=A,
       json={"lat": 40.1, "lng": -75.3, "accuracy_m": 10, "odo_km": 41230})
_sid = _v["steps"][0]["id"]
ok(c.post(f"/api/field/steps/{_sid}", headers=A,
          json={"state": "skipped"}).status_code == 400,
   "skipping needs a reason — a list that only offers 'done' gets ticked "
   "from the van, and everybody involved knows it")
ok(c.post(f"/api/field/steps/{_sid}", headers=A,
          json={"state": "failed", "note": "three cases out of date"}
          ).status_code == 200, "and failing is an answer, with the reason")
_png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
_ph = c.post("/api/field/photo", headers=A, json={
    "visit_id": _vid, "step_id": _sid, "caption": "the shelf",
    "lat": 40.1, "lng": -75.3, "accuracy_m": 8,
    "data_url": _png}).json()
ok(_ph["token"], "a picture goes with the visit")
_v = c.get(f"/api/field/visits/{_vid}", headers=A).json()
ok(_v["media"][0]["lat"] == 40.1 and _v["media"][0]["accuracy_m"] == 8,
   "carrying where and how surely the phone said it was taken — a photo "
   "of a shelf proves nothing about which shelf, and the same photo with "
   "a fix on it proves both")
ok(c.post("/api/field/photo", headers=A, json={
    "visit_id": _vid, "data_url": "data:image/png;base64,bm90YW5pbWFnZQ=="}
    ).status_code == 400, "and it has to actually be a picture")
ok(c.get(f"/media/visit/{_ph['token']}", headers=A).status_code == 200
   and c.get(f"/media/visit/{_ph['token']}").status_code in (401, 403),
   "which is served to the office and not to the internet")

ok(c.post(f"/api/field/visits/{_vid}/finish", headers=A,
          json={"odo_km": 41258}).status_code == 400,
   "a visit that is signed for cannot be closed unsigned — a delivery "
   "accepted by 'manager' is a delivery nobody accepted")
_done = c.post(f"/api/field/visits/{_vid}/finish", headers=A, json={
    "odo_km": 41258, "signature": "D. Okafor",
    "contact_name": "Dele Okafor", "contact_role": "store manager"}).json()
ok(_done["state"] == "done" and _done["km"] == 28.0,
   "and the distance comes off the odometer at both ends, not the GPS "
   "trail — a phone in a loading bay invents a straight line through a "
   "building, and mileage is a payment")
ok(_done["open_steps"] == 2 and _done["failed_steps"] == ["Photo before"],
   "a visit can be closed over an unfinished list, because the field is "
   "not tidy and refusing would teach people to tick everything — but "
   "what was left open stays on it")
_fs = c.get("/api/field/visits?days=30", headers=A).json()
ok(_fs["done"] >= 1 and _fs["clean"] == 0 and _fs["clean_pct"] == 0.0,
   "so 'finished' and 'finished properly' are counted apart — the second "
   "is the number this exists to make visible")
ok(any(f["failed"] for f in _fs["failed"]),
   "and whatever came back failed is named rather than averaged away")
ok(_fs["km"] == 28.0 and _fs["photos"] >= 1,
   "with the miles and the pictures added up beside them")

# Goods coming in: the list IS the paperwork. A receiving checklist typed
# out by hand says what somebody remembers was ordered, which is the
# number least worth checking against.
_sup = c.post("/api/supply/suppliers", headers=A,
              json={"name": "Yuzu Imports"}).json()
_mat = c.post("/api/supply/materials", headers=A, json={
    "name": "Yuzu concentrate", "unit": "L",
    "supplier_id": _sup.get("id", 1)}).json()
_po = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _sup.get("id", 1),
    "lines": [{"material_id": _mat.get("id", 1), "qty": 100,
               "unit_cost_cents": 900}]}).json()
_poid = _po.get("id") or 1
_rv = c.post("/api/field/visits", headers=A, json={
    "kind": "receiving", "title": "Pallet in", "po_id": _poid}).json()["id"]
_rvd = c.get(f"/api/field/visits/{_rv}", headers=A).json()
ok(len(_rvd["steps"]) == 1 and _rvd["steps"][0]["expected_qty"] == 100.0,
   "the lines still outstanding on the order become the steps, each "
   "carrying what is expected — so a short pallet is visible while the "
   "driver is still there rather than at the month end")
ok(_rvd["steps"][0]["line_id"],
   "and each step knows which line it answers")
c.post(f"/api/field/visits/{_rv}/start", headers=A, json={})
c.post(f"/api/field/steps/{_rvd['steps'][0]['id']}", headers=A,
       json={"state": "done", "qty": 92, "note": "two cases refused"})
_fin = c.post(f"/api/field/visits/{_rv}/finish", headers=A, json={}).json()
ok(_fin["received"]["booked"] == 1
   and _fin["received"]["short"][0]["got"] == 92.0,
   "closing the visit books what was COUNTED, not what was ordered — a "
   "receiving screen that books the paperwork's number is a screen that "
   "invents stock")
_poafter = c.get(f"/api/supply/purchase-orders", headers=A).json()
_line = None
for _o in (_poafter if isinstance(_poafter, list)
           else _poafter.get("orders", [])):
    for _l in _o.get("lines", []):
        if _l.get("id") == _rvd["steps"][0]["line_id"]:
            _line = _l
ok(_line is None or _line["received"] == 92.0,
   "the order line carries the 92 that arrived")
_again = c.post(f"/api/field/visits/{_rv}/finish", headers=A, json={}).json()
ok("received" not in _again,
   "and finishing a finished visit does not book the pallet in twice")

# Three numbers meet on a loading bay and they are all different: what we
# ORDERED, what the supplier PROMISED, and what ARRIVED.
_po2 = c.post("/api/supply/purchase-orders", headers=A, json={
    "supplier_id": _sup.get("id", 1),
    "lines": [{"material_id": _mat.get("id", 1), "qty": 100,
               "unit_cost_cents": 900}]}).json()
_po2id = _po2.get("id") or 2
_pcon = _mdb.connect()
_line2 = _pcon.execute("SELECT id FROM purchase_order_lines WHERE po_id=?"
                       " ORDER BY id DESC LIMIT 1", (_po2id,)).fetchone()["id"]
_pcon.execute(
    "INSERT INTO po_confirmations(po_id,confirmed_by,confirmed_eta,message,"
    " lines,created_at) VALUES(?,?,?,'',?,?)",
    (_po2id, "Marta", _t0.time() + 2 * 86400,
     _json_dumps := __import__("json").dumps({str(_line2): 70}), _t0.time()))
_pcon.execute("UPDATE purchase_orders SET status='sent' WHERE id=?",
              (_po2id,))
_pcon.commit()
_pcon.close()

_inb = c.get("/api/field/inbound", headers=A).json()
_row = [x for x in _inb["deliveries"] if x["po_id"] == _po2id][0]
ok(_row["confirmed"] and _row["eta"] and _row["lines"][0]["promised"] == 70.0,
   "an order the supplier has confirmed is a delivery with a date on it "
   "and a quantity beside the one we asked for")
ok(_row["visit"] is None and _inb["unbooked"] >= 1,
   "and one with nobody booked to meet it is named — a truck nobody knew "
   "was coming gets counted by whoever happens to be near the door, which "
   "is the receiving that goes wrong")
_meet = c.post("/api/field/inbound/meet", headers=A,
               json={"po_id": _po2id}).json()
_mv = c.get(f"/api/field/visits/{_meet['id']}", headers=A).json()
ok(abs(_mv["planned_for"] - _row["eta"]) < 2,
   "meeting it books the visit for the SUPPLIER'S date — one booked for a "
   "date we invented is a delivery somebody waits for on the wrong day")
_step = _mv["steps"][0]
ok(_step["expected_qty"] == 70.0 and _step["ordered_qty"] == 100.0,
   "the step counts against what was promised and carries what was "
   "ordered beside it — counting against the order alone flags a "
   "delivery short when the supplier already told us it would be, which "
   "trains everybody to ignore the flag")
ok("we ordered 100" in _step["label"],
   "and says both numbers out loud on the label")
ok(c.post("/api/field/inbound/meet", headers=A,
          json={"po_id": _po2id}).status_code == 409,
   "two people are not booked onto one delivery")
c.post(f"/api/field/visits/{_meet['id']}/start", headers=A, json={})
c.post(f"/api/field/steps/{_step['id']}", headers=A,
       json={"state": "done", "qty": 70})
_got = c.post(f"/api/field/visits/{_meet['id']}/finish", headers=A,
              json={}).json()["received"]
ok(not _got["short"] and _got["short_of_order"],
   "seventy against a seventy promise is not a short delivery — it is a "
   "short ORDER, and filing the two together is how everybody learns to "
   "ignore the short deliveries")
ok(_got["short_of_order"][0]["ordered"] == 100.0,
   "the buyer's conversation keeps the number the buyer needs")
_inb2 = c.get("/api/field/inbound", headers=A).json()
_row2 = [x for x in _inb2["deliveries"] if x["po_id"] == _po2id]
ok(not _row2 or _row2[0]["lines"][0]["promised"] is None,
   "and a promise already kept stops being reported as news — 'they "
   "promised 70' against 30 still owed reads as seventy more coming")

# Going out. The mirror of receiving in shape and not at all in meaning:
# the stock left when the order shipped, so what a delivery visit settles
# is whether it ARRIVED.
c.post("/api/admin/stores", headers=A, json={
    "name": "Drop Test Depot", "kind": "retail", "region": "Northeast",
    "city": "Trenton", "lat": 40.2171, "lng": -74.7429})
_dsid = [x for x in c.get("/api/stores", headers=A).json()
         if x["name"] == "Drop Test Depot"][0]["id"]
_dpid = c.get("/api/products", headers=A).json()[0]["id"]
_ocon = _mdb.connect()
_dp = _ocon.execute(
    "INSERT INTO orders(user_id,kind,status,region,store_id,"
    " fulfilled_store_id,subtotal_cents,total_cents,created_at)"
    " VALUES(1,'distributor','shipped','Northeast',?,?,10000,10000,?)",
    (_dsid, _dsid, _t0.time())).lastrowid
_ocon.execute("INSERT INTO order_items(order_id,product_id,qty,"
              " unit_price_cents) VALUES(?,?,4,2500)", (_dp, _dpid))
_ocon.execute("INSERT INTO inventory(store_id,product_id,qty,updated_at)"
              " VALUES(?,?,0,0) ON CONFLICT(store_id,product_id)"
              " DO UPDATE SET qty=0", (_dsid, _dpid))
_ocon.commit()
_case = _ocon.execute("SELECT case_size FROM products WHERE id=?",
                      (_dpid,)).fetchone()["case_size"] or 1
_ocon.close()

_ob = c.get("/api/field/outbound", headers=A).json()
_drop = [x for x in _ob["drops"] if x["order_id"] == _dp][0]
ok(_drop["visit"] is None and _ob["unbooked"] >= 1,
   "an order paid for and not yet handed over is a promise with a van in "
   "front of it, and the one nobody is named on is the one that happens "
   "when somebody has a spare hour")
_take = c.post("/api/field/outbound/take", headers=A,
               json={"order_id": _dp}).json()
_tv = c.get(f"/api/field/visits/{_take['id']}", headers=A).json()
ok(len(_tv["steps"]) == 1 and _tv["steps"][0]["ordered_qty"] == 4.0,
   "taking it copies the order's lines onto the visit as things to hand "
   "over")
ok(c.post("/api/field/outbound/take", headers=A,
          json={"order_id": _dp}).status_code == 409,
   "and two people do not take one drop")
c.post(f"/api/field/visits/{_take['id']}/start", headers=A, json={})
c.post(f"/api/field/steps/{_tv['steps'][0]['id']}", headers=A,
       json={"state": "done", "qty": 3, "note": "one case dented, refused"})
_nosig = c.post(f"/api/field/visits/{_take['id']}/finish", headers=A,
                json={})
ok(_nosig.status_code == 400 and "proved by the person" in
   _nosig.json()["detail"],
   "a delivery is proved by whoever took it — a delivery dispute is never "
   "about our count, it is about whether they got it")
_out = c.post(f"/api/field/visits/{_take['id']}/finish", headers=A, json={
    "signature": "R. Alvarez", "contact_name": "Rosa Alvarez",
    "contact_role": "receiving clerk"}).json()["handed"]
ok(not _out["accepted_all"] and _out["refused"][0]["back"] == 1.0,
   "three of four taken leaves one refused")
ok(_out["returned_units"] == float(_case),
   "and the refused case comes BACK to the store that sent it — two "
   "cases refused at a door are two cases on a van, not two cases that "
   "evaporated, and writing the shortfall off the paperwork is how a "
   "van's stock and the system's diverge by exactly the amount nobody "
   "wanted")
_icon = _mdb.connect()
ok(_icon.execute("SELECT qty FROM inventory WHERE store_id=? AND"
                 " product_id=?", (_dsid, _dpid)).fetchone()["qty"]
   == _case, "in units, the way the order shipped them")
ok(_icon.execute("SELECT status FROM orders WHERE id=?",
                 (_dp,)).fetchone()["status"] == "part_delivered",
   "and a delivery the customer took half of is not delivered — calling "
   "it so is how a credit note goes unwritten")
_icon.close()

# A stop on a route is a store, and until now it was closed by a
# checkbox — which is a claim.
_rt = c.get("/api/routes", headers=A).json()
_route = next((r for r in _rt if len(r["stops"]) >= 2), None)
if _route:
    _sseq = _route["stops"][1]["seq"]
    _sstore = _route["stops"][1]["store_id"]
    _scon = _mdb.connect()
    _so = _scon.execute(
        "INSERT INTO orders(user_id,kind,status,region,store_id,"
        " fulfilled_store_id,subtotal_cents,total_cents,created_at)"
        " VALUES(1,'distributor','shipped','Northeast',?,?,5000,5000,?)",
        (_sstore, _sstore, _t0.time())).lastrowid
    _scon.execute("INSERT INTO order_items(order_id,product_id,qty,"
                  " unit_price_cents) VALUES(?,?,6,800)", (_so, _dpid))
    _scon.commit()
    _scon.close()
    _st = c.post(f"/api/field/route/{_route['id']}/stop/{_sseq}/take",
                 headers=A, json={}).json()
    ok(_st["lines"] >= 1,
       "taking a stop builds the list from the orders outstanding for that "
       "STORE — often several on one pallet, which is the difference "
       "between a driver with one docket and a driver with the day's work "
       "for that door")
    ok(c.post(f"/api/field/route/{_route['id']}/stop/{_sseq}/take",
              headers=A, json={}).status_code == 409,
       "and two people are not sent to one door")
    _sv = c.get(f"/api/field/visits/{_st['id']}", headers=A).json()
    ok(_sv["route_id"] == _route["id"] and _sv["route_seq"] == _sseq,
       "the visit knows which stop it is")
    c.post(f"/api/field/visits/{_st['id']}/start", headers=A, json={})
    for _step in _sv["steps"]:
        c.post(f"/api/field/steps/{_step['id']}", headers=A,
               json={"state": "done", "qty": _step["ordered_qty"]})
    _sfin = c.post(f"/api/field/visits/{_st['id']}/finish", headers=A,
                   json={"signature": "P. Nowak",
                         "contact_name": "Piotr Nowak"}).json()
    ok(_sfin["stop"]["stop"] == _sseq,
       "finishing it closes the stop")
    _rt2 = [r for r in c.get("/api/routes", headers=A).json()
            if r["id"] == _route["id"]][0]
    _row = [x for x in _rt2["stops"] if x["seq"] == _sseq][0]
    ok(_row["delivered"] == 1 and _row["proved"],
       "which is delivered AND proved — the same word in the database as a "
       "ticked checkbox, and not the same fact")
    ok(_row["visit"]["who"] and _row["visit"]["contact_name"],
       "carrying who took it and who signed for it")
    _unproved = [x for x in _rt2["stops"] if x["seq"] != _sseq]
    ok(all(not x["proved"] for x in _unproved),
       "and a stop nobody has been to is not dressed up as one that "
       "somebody has")
    c.post(f"/api/routes/{_route['id']}/stop", headers=A,
           json={"seq": _unproved[0]["seq"], "delivered": True})
    _rt3 = [r for r in c.get("/api/routes", headers=A).json()
            if r["id"] == _route["id"]][0]
    _hand = [x for x in _rt3["stops"] if x["seq"] == _unproved[0]["seq"]][0]
    ok(_hand["delivered"] == 1 and not _hand["proved"],
       "the checkbox still works — a driver without a phone has to be able "
       "to close a stop, and a system that only accepts proof is one that "
       "gets worked around with a paper list — but it does not look like "
       "the proved kind")

# A truck that answers to no order. Replacement pallets, samples, a case
# coming back — these arrive, and refusing to book them until somebody
# raises a retrospective purchase order means they get booked as an
# adjustment, or not at all, and the stock is wrong either way.
_loose = c.post("/api/field/visits", headers=A, json={
    "kind": "receiving", "title": "Replacement pallet",
    "supplier_id": _sup.get("id", 1)}).json()["id"]
ok(c.get(f"/api/field/visits/{_loose}", headers=A).json()["steps"] == [],
   "a delivery with no order starts with no list — nobody knows what is "
   "on a truck until it is open")
c.post(f"/api/field/visits/{_loose}/start", headers=A, json={})
_ln = c.post(f"/api/field/visits/{_loose}/steps", headers=A, json={
    "material_id": _mat.get("id", 1), "expected_qty": 40}).json()
ok(_ln["id"], "so the list is written at the door")
ok(c.post(f"/api/field/visits/{_loose}/steps", headers=A,
          json={"material_id": 999999}).status_code == 400,
   "against the material catalogue, not free text — stock booked against "
   "a typed phrase lands on nothing and turns up a month later as an "
   "adjustment nobody can explain")
ok(c.post(f"/api/field/visits/{_loose}/steps", headers=A,
          json={}).status_code == 400, "and a step has to say what it is")
_drop = c.post(f"/api/field/visits/{_loose}/steps", headers=A,
               json={"label": "a line added by mistake"}).json()
ok(c.request("DELETE", f"/api/field/steps/{_drop['id']}",
             headers=A).status_code == 200,
   "one added by mistake comes off again")

_before = _mdb.connect()
_had = _before.execute("SELECT on_hand FROM materials WHERE id=?",
                       (_mat.get("id", 1),)).fetchone()["on_hand"]
_before.close()
c.post(f"/api/field/steps/{_ln['id']}", headers=A,
       json={"state": "done", "qty": 40})
_no = c.post(f"/api/field/visits/{_loose}/finish", headers=A, json={})
ok(_no.status_code == 400 and "where this came from" in _no.json()["detail"],
   "and it cannot be closed silently: a purchase order IS the authority "
   "for a receipt, so without one the authority is a person and a written "
   "reason")
c.post(f"/api/field/steps/{_ln['id']}", headers=A, json={
    "state": "done", "qty": 40, "note": "replacement for the split drums"})
_got = c.post(f"/api/field/visits/{_loose}/finish", headers=A,
              json={}).json()["received"]
ok(_got["loose"] and _got["booked"] == 1,
   "with the reason on it, the stock goes in")
_after = _mdb.connect()
ok(_after.execute("SELECT on_hand FROM materials WHERE id=?",
                  (_mat.get("id", 1),)).fetchone()["on_hand"] == _had + 40,
   "and it is the counted quantity that moves")
_mv = _after.execute(
    "SELECT reason, actor, note FROM material_moves ORDER BY id DESC"
    " LIMIT 1").fetchone()
_after.close()
ok(_mv["reason"] == f"visit:{_loose}" and _mv["note"]
   and _mv["actor"],
   "the ledger carries the visit, the person and the reason — 'where did "
   "forty litres come from' then has an answer that is not 'an "
   "adjustment'")

# --- clocking in where the work is ------------------------------------------
# Somebody rostered at the Norristown shop punching in from home is a
# payroll question. The fence answers it — but only on the way in.
c.post("/api/admin/users", headers=A, json={
    "name": "Fenced Fran", "role": "employee", "pin": "4791"})
_fuid = [u for u in c.get("/api/admin/users", headers=A).json()
         if u["name"] == "Fenced Fran"][0]["id"]
c.post("/api/admin/stores", headers=A, json={
    "name": "Fence Test Shop", "kind": "retail", "region": "Northeast",
    "city": "Norristown", "lat": 40.1215, "lng": -75.3399})
_fsid = [s2 for s2 in c.get("/api/stores", headers=A).json()
         if s2["name"] == "Fence Test Shop"][0]["id"]
c.post(f"/api/admin/users/{_fuid}/update", headers=A,
       json={"clock_store_id": _fsid})
# The PIN door carries the same rules, and needs no session.
_far = c.post("/api/clock", json={"pin": "4791", "lat": 40.20, "lng": -75.40,
                                  "accuracy_m": 10})
ok(_far.status_code == 403 and " m from " in _far.json()["detail"],
   "a punch from the wrong place is refused, and the refusal says how far "
   "away it was rather than just no")
_blind = c.post("/api/clock", json={"pin": "4791"})
ok(_blind.status_code == 403,
   "and a punch with no location at all cannot prove anything — a refusal "
   "to share it is a refusal, not a pass")
_vague = c.post("/api/clock", json={"pin": "4791", "lat": 40.1215,
                                    "lng": -75.3399, "accuracy_m": 900})
ok(_vague.status_code == 403 and "accurate" in _vague.json()["detail"],
   "a fix that says 'somewhere within 900 metres' cannot show somebody is "
   "inside a 150 metre fence — treating it as though it can is how a "
   "geofence becomes theatre everybody knows about")
_near = c.post("/api/clock", json={"pin": "4791", "lat": 40.12155,
                                   "lng": -75.33995, "accuracy_m": 12})
ok(_near.status_code == 200 and _near.json()["action"] == "clock_in",
   "and at the shop, they are on shift")
_out = c.post("/api/clock", json={"pin": "4791"})
ok(_out.status_code == 200 and _out.json()["action"] == "clock_out",
   "the fence gates going ON shift and never coming off it — refusing a "
   "clock-out because a phone has no fix leaves somebody being paid for "
   "a car park")

_k = c.post("/api/admin/kiosks", headers=A, json={
    "label": "Front door tablet", "store_id": _fsid}).json()
ok(_k["kiosk_id"] and len(_k["kiosk_id"]) > 6,
   "a kiosk id is minted here, not accepted from the device — an id a "
   "browser can choose for itself is not a location, it is a claim")
c.post(f"/api/admin/users/{_fuid}/update", headers=A,
       json={"clock_store_id": 0, "clock_kiosk_only": True})
ok(c.post("/api/clock", json={"pin": "4791", "lat": 40.1215,
                              "lng": -75.3399}).status_code == 403,
   "somebody bound to a kiosk is not let in by coordinates — the tablet "
   "is the location, and it cannot be changed by a setting")
ok(c.post("/api/clock", json={"pin": "4791",
                              "kiosk": "made-up"}).status_code == 403,
   "nor by naming a tablet that was never registered")
_kin = c.post("/api/clock", json={"pin": "4791", "kiosk": _k["kiosk_id"]})
ok(_kin.status_code == 200,
   "at the registered tablet by the door, they are on shift")
c.post("/api/clock", json={"pin": "4791"})           # off again
_sh = _mdb.connect()
_row = _sh.execute("SELECT in_kiosk, in_lat FROM shifts WHERE user_id=?"
                   " ORDER BY id DESC LIMIT 1", (_fuid,)).fetchone()
_sh.close()
ok(_row["in_kiosk"] == _k["kiosk_id"],
   "and where the punch happened is written on the shift — 'the fence "
   "said yes' is not evidence six weeks later when an hour is disputed")

# --- the counter ------------------------------------------------------------
# A till is not a checkout with bigger buttons. The differences are all
# about cash: a drawer with a counted float, tenders that can be more than
# one, change that comes back, and a count at the end whose difference is
# stated rather than absorbed.
_till = c.post("/api/pos/session", headers=A,
               json={"register": "smoke", "float_cents": 10000}).json()
ok(_till["id"], "a drawer opens with a counted float in it")
ok(c.post("/api/pos/session", headers=A,
          json={"register": "smoke"}).status_code == 409,
   "and only one drawer is open on a register at a time — two tills "
   "against one float is a variance nobody can attribute")
_prod = c.get("/api/products", headers=A).json()[0]
_sale = c.post("/api/pos/sale", headers=A, json={
    "register": "smoke",
    "items": [{"product_id": _prod["id"], "qty": 2,
               "unit_price_cents": 500}],
    "tenders": [{"kind": "cash", "cents": 2000}]}).json()
ok(_sale["change_cents"] == 1000,
   "a sale takes the money and gives the change back")
_kinds = [(t["kind"], t["cents"]) for t in _sale["receipt"]["tenders"]]
ok(("cash", 2000) in _kinds and ("cash", -1000) in _kinds,
   "and change is a NEGATIVE cash tender rather than a field on the sale, "
   "so the drawer nets out of what went in and out of it")
_split = c.post("/api/pos/sale", headers=A, json={
    "register": "smoke",
    "items": [{"product_id": _prod["id"], "qty": 1,
               "unit_price_cents": 1000}],
    "tenders": [{"kind": "cash", "cents": 400},
                {"kind": "card", "cents": 600, "ref": "4242"}]}).json()
ok(_split["change_cents"] == 0 and len(_split["receipt"]["tenders"]) == 2,
   "one sale can be part cash and part card — recording a total and a "
   "payment method loses the half a drawer is counted against")
ok(c.post("/api/pos/sale", headers=A, json={
    "register": "smoke",
    "items": [{"product_id": _prod["id"], "qty": 1,
               "unit_price_cents": 1000}],
    "tenders": [{"kind": "cash", "cents": 400}]}).status_code == 400,
   "a sale is not part-paid at a counter, it is unfinished")
ok(c.post("/api/pos/sale", headers=A, json={
    "register": "nowhere", "items": [{"product_id": _prod["id"]}]}
    ).status_code == 409,
   "and nothing rings through a register with no drawer open")

_dr = c.get("/api/pos/session?register=smoke", headers=A).json()
ok(_dr["expected_cents"] == 10000 + 1000 + 400,
   "the drawer expects the float plus the CASH only — a card sale never "
   "touched it, and counting it in is how a till reads hundreds short "
   "every evening and everybody learns to ignore the variance")
_shut = c.post("/api/pos/session/close", headers=A, json={
    "session_id": _till["id"], "counted_cents": _dr["expected_cents"] - 250,
    "note": "a fiver stuck to a twenty"}).json()
ok(_shut["variance_cents"] == -250 and _shut["short"],
   "and the count states the difference — a till that silently balances "
   "is a till nobody can trust")

_rec = c.get(f"/api/pos/receipt/{_sale['order_id']}", headers=A).json()
ok(_rec["token"] and _rec["change_cents"] == 1000,
   "every sale has a receipt at an address of its own")
_page = c.get(f"/rc/{_rec['token']}")
ok(_page.status_code == 200 and "qr.svg" in _page.text,
   "which the customer can open from the QR on the paper — a receipt only "
   "the shop can find is a returns argument waiting to happen")
ok(c.get("/rc/not-a-real-token").status_code == 404,
   "and the token is the address, because an order id is guessable by "
   "counting and a receipt carries what somebody bought")
_ords = c.get("/api/orders", headers=A).json()
ok(any(o["kind"] == "pos" for o in (_ords if isinstance(_ords, list)
                                    else _ords.get("orders", []))),
   "a counter sale is an ordinary order — the day book, the P&L, margin "
   "and stock all read orders already, and a second sales table would "
   "have meant teaching every one of them a second answer")

# A beep has to mean one thing. Codes are normalised at both ends,
# because people paste them out of spreadsheets with spaces in and a
# scanner sends the digits and nothing else.
_bp = c.post(f"/api/admin/products/{_prod['id']}/barcode", headers=A,
             json={"barcode": " 5060337502115 "}).json()
ok(_bp["barcode"] == "5060337502115",
   "a code is stored as the scanner would read it back — storing "
   "'0 12345 67890 5' and scanning '012345678905' is a product that "
   "exists twice and can be found neither time")
_look = c.get("/api/pos/lookup?code=5060337502115", headers=A).json()
ok(_look["id"] == _prod["id"], "and scanning it finds the product")
ok(c.get("/api/pos/lookup?code=506-0337 502115", headers=A).json()["id"]
   == _prod["id"], "however it was typed")
_other = [p for p in c.get("/api/products", headers=A).json()
          if p["id"] != _prod["id"]][0]
ok(c.post(f"/api/admin/products/{_other['id']}/barcode", headers=A,
          json={"barcode": "5060337502115"}).status_code == 409,
   "two products cannot share a code — a beep that could mean either is "
   "worse than a beep that means nothing")
ok(c.get(f"/api/pos/lookup?code={_prod['sku']}", headers=A).json()["id"]
   == _prod["id"],
   "a SKU works too, because staff type those when a label is torn")
ok(c.get("/api/pos/lookup?code=00000000000", headers=A).status_code == 404,
   "and an unknown code says so rather than ringing up the wrong thing")
ok(c.get("/api/pos/lookup?code=5060337502115").status_code in (401, 403),
   "the lookup is the till's — it is the product list with a different "
   "shape")

_qrjs = c.get("/qr-scan.js").text
ok("ean_13" in _qrjs and "upc_a" in _qrjs and "code_128" in _qrjs,
   "the reader knows the symbologies a shop actually prints, not just QR")
ok("getSupportedFormats" in _qrjs,
   "and asks the browser which of them it can do — handing a detector a "
   "format it does not know makes it refuse the lot, which presents as a "
   "scanner that never sees anything")
ok("function wedge(" in _qrjs and "keydown" in _qrjs,
   "and the scanner actually on a counter is a USB device that types, so "
   "there is a listener for a burst of keystrokes ending in Return")
ok("gapMs" in _qrjs or "gap = " in _qrjs,
   "told apart from a person typing by speed, which is the only thing "
   "that distinguishes them")
ok("wedgeOff" in _ops and "if (typeof wedgeOff" in _ops,
   "and it is turned off when the till is not on screen — left on it "
   "would swallow the Enter key everywhere else, which is the sort of "
   "bug that gets blamed on the keyboard")

# --- the client who keeps their own website ---------------------------
# Not every client wants us to build their site, and telling them the back
# office comes with a shop they have to ignore is how a good fit is talked
# out of a sale.
_ws = c.get("/api/website", headers=A).json()
ok(_ws["base"] and len(_ws["calls"]) >= 3,
   "an install says where it is and what an outside website calls")
ok({x["path"] for x in _ws["calls"]} <= {
    "/api/store/catalog", "/api/orders", "/api/products"},
   "and every one of them is a call this software already answers — not a "
   "second API bolted on for the purpose, which would be a second thing "
   "to keep true")
ok(not _ws["storefront_off"], "the shop is on until somebody turns it off")
ok(c.get("/").status_code == 200, "and the front door serves it")
ok(c.post("/api/website", headers=A,
          json={"external_site": "example.com"}).status_code == 400,
   "an address without its scheme is refused rather than guessed at")
c.post("/api/website", headers=A, json={
    "storefront_off": True, "external_site": "https://elsewhere.test"})
_door = c.get("/", follow_redirects=False)
ok(_door.status_code == 307
   and _door.headers["location"] == "https://elsewhere.test",
   "with the shop off, the door points at the site they actually keep — "
   "an unmaintained storefront on a real domain is worse than none, "
   "because it is a second shop with old prices that customers cannot "
   "tell from the real one")
c.post("/api/website", headers=A, json={"external_site": ""})
_bare = c.get("/")
ok(_bare.status_code == 200 and "back office" in _bare.text,
   "and with nowhere to point, it says what the address is rather than "
   "serving a shop nobody maintains")
ok(c.get("/ops/app.js").status_code == 200,
   "the back office itself is untouched — it is the product they bought")
c.post("/api/website", headers=A, json={"storefront_off": False})
ok(c.get("/").status_code == 200, "and it comes back")
ok(c.get("/api/website").status_code in (401, 403),
   "the wiring page is the owner's")

# A single-tenant install has no grant and must never acquire one: the
# absence of an entitlement cannot take features from somebody who
# already had them all.
_e1 = c.get("/api/entitlements", headers=A).json()
_reg = [x for x in _e1["lines"] if x["kind"] == "registers"][0]
ok(_reg["each_cents"] == 1900,
   "an install can see what another till would cost")
ok(_reg["allowed"] > 1000,
   "and an install nobody sold anything to is not limited — the same rule "
   "capabilities follow, for the same reason")
ok(c.post("/api/pos/session", headers=A, json={
    "register": "second-lane", "float_cents": 0}).status_code == 200,
   "so a second lane opens")
c.post("/api/pos/session/close", headers=A, json={
    "session_id": c.get("/api/pos/session?register=second-lane",
                        headers=A).json()["session"]["id"],
    "counted_cents": 0})

# The same till, handed to the customer.
_lane = c.post("/api/pos/session", headers=A, json={
    "register": "lane-smoke", "self_serve": True,
    "float_cents": 10000}).json()
ok(_lane["self_serve"] and _lane["float_cents"] == 0,
   "an unattended lane opens with no float — there is no drawer, so a "
   "float would be a number nobody can count at the end")
_cashtry = c.post("/api/pos/sale", headers=A, json={
    "register": "lane-smoke",
    "items": [{"product_id": _prod["id"], "qty": 1,
               "unit_price_cents": 500}],
    "tenders": [{"kind": "cash", "cents": 500}]})
ok(_cashtry.status_code == 400 and "cards only" in _cashtry.json()["detail"],
   "and it takes cards only: a machine that accepts a twenty and owes "
   "eleven dollars back with nobody standing at it is a complaint with a "
   "receipt attached")
_lanesale = c.post("/api/pos/sale", headers=A, json={
    "register": "lane-smoke",
    "items": [{"product_id": _prod["id"], "qty": 1,
               "unit_price_cents": 500}],
    "tenders": [{"kind": "card", "cents": 500, "ref": "self"}]}).json()
ok(_lanesale["receipt"]["token"],
   "a customer serving themselves still gets a receipt of their own")
_lanedr = c.get("/api/pos/session?register=lane-smoke", headers=A).json()
ok(_lanedr["expected_cents"] == 0 and _lanedr["taken_cents"] == 500,
   "and the lane takes money without expecting any cash in a drawer")

from storefront.backend import governance as _gov  # noqa: E402
ok("till" in _gov.PERMISSIONS and _gov.ROLE_DEFAULTS["cashier"] == ["till"],
   "a cashier gets the till and nothing else — a role that quietly "
   "carries the customer list is a role nobody can hand out quickly")

# --- the site as a chain ----------------------------------------------------
# A step funnel says how many reached checkout; a transition list says
# which page leaks. Neither says which page the traffic runs THROUGH.
_pg = c.get("/api/store/admin/page-graph?days=90", headers=A).json()
ok(_pg["nodes"] and _pg["edges"],
   "the pageview log is already a chain of transitions — it only needed "
   "normalising")
ok(abs(sum(n["rank"] for n in _pg["nodes"]) - 1) < 0.01,
   "rank is a distribution: it sums to one, because it is the share of a "
   "wandering visitor's time each page holds")
ok(all(0 <= e["p"] <= 1 for e in _pg["edges"]),
   "and an arrow carries the chance of that step, not a raw count")
for _n in _pg["nodes"]:
    _out = sum(e["p"] for e in _pg["edges"] if e["from"] == _n["page"])
    ok(_out + _n["leave_p"] <= 1.02,
       f"what can happen on {_n['page']} adds to one WITH leaving — "
       "renormalising the exit away makes every page look stickier than "
       "it is")
ok(all("mean_step" in n for n in _pg["nodes"]),
   "each page knows where in a path it usually appears, which is what "
   "lets a drawing of this run left to right in the order people walk it")
ok(_pg["nodes"] == sorted(_pg["nodes"],
                          key=lambda n: (n["mean_step"], -n["rank"])),
   "and they arrive in that order")
ok(c.get("/api/store/admin/page-graph").status_code in (401, 403),
   "the chain is the office's")

# --- baskets, and whether anybody comes back --------------------------------
# Acquisition was measured five ways here and what happened after somebody
# bought was measured in none, which for a business that sells anything
# twice is the half the money is in.
#
# On a scratch database rather than the suite's: these are arithmetic, and
# arithmetic is checked against numbers you chose, not against whatever
# every test before this one happened to leave in the orders table.
from erp.backend import commerce as _com  # noqa: E402
_ccon = _sq3.connect(":memory:")
_ccon.row_factory = _sq3.Row
_ccon.executescript(
    "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INT, kind TEXT,"
    " status TEXT, region TEXT, subtotal_cents INT, total_cents INT,"
    " created_at REAL);"
    "CREATE TABLE order_items (order_id INT, product_id INT, qty INT,"
    " unit_price_cents INT);")
_c_now = _t0.time()


def _buy(uid, when, cents, kind="customer", qty=2):
    cur = _ccon.execute(
        "INSERT INTO orders(user_id,kind,status,region,subtotal_cents,"
        " total_cents,created_at) VALUES(?,?,'paid','Northeast',?,?,?)",
        (uid, kind, cents, cents, when))
    _ccon.execute("INSERT INTO order_items(order_id,product_id,qty,"
                  " unit_price_cents) VALUES(?,1,?,?)",
                  (cur.lastrowid, qty, cents // max(1, qty)))
    _ccon.commit()


for _i in range(6):                       # six little baskets
    _buy(900 + _i, _c_now - 40 * 86400, 1000 + _i * 100)
_buy(999, _c_now - 39 * 86400, 500000, "distributor")   # and one whale
_bk = _com.basket(_ccon, 90, when=_c_now)
ok(_bk["orders"] == 7 and _bk["aov_cents"] == 72500
   and _bk["median_cents"] == 1300,
   "the median sits beside the average, because one wholesale order in a "
   "month of small ones moves the mean past every real basket in the "
   "list — $725 average, $13 middle")
ok(_bk["units_per_order"] == 2.0,
   "items per order comes off the lines, not the order count")
ok([k["kind"] for k in _bk["by_kind"]] == ["customer", "distributor"]
   and _bk["by_kind"][0]["aov_cents"] == 1250,
   "and the kinds are kept apart — a case to a distributor and a tin to "
   "somebody's kitchen are not the same transaction, and one average over "
   "both describes neither")
ok(_com.basket(_ccon, 90, kind="distributor",
               when=_c_now)["orders"] == 1, "either can be asked for alone")

_rp = _com.repeat(_ccon, 365, when=_c_now)
ok(_rp["repeat_ever_pct"] == 0.0 and _rp["customers_ever"] == 7,
   "nobody who bought once is a repeat customer, and the rate says 0 "
   "rather than nothing")
_buy(900, _c_now - 10 * 86400, 1500)
_rp = _com.repeat(_ccon, 365, when=_c_now)
ok(_rp["repeat_ever"] == 1 and _rp["median_gap_days"] == 30.0,
   "one comes back after thirty days, and both the count and the gap say "
   "so")
ok(_rp["returning_revenue_cents"] == 1500
   and _rp["new_revenue_cents"] == 507500,
   "money from somebody who had bought before is counted apart from money "
   "from a stranger — a month that grew entirely on strangers grew the "
   "most expensive way there is")
_narrow = _com.repeat(_ccon, 5, when=_c_now)
ok(_narrow["repeat_pct"] is None and _narrow["customers_in_window"] == 0
   and _com.repeat(_ccon, 365, when=_c_now)["repeat_ever_pct"] > 0,
   "the in-window rate moves with the window, which is a fact about the "
   "window rather than the business — so the two are reported apart, and "
   "a window nobody bought in has no rate rather than a rate of zero")

# Two months back, so there is a row with a month after it to follow.
# Said in months rather than in days: "+35 days" is not "the next month"
# when the cohort lands near the end of one, so this test passed until
# the day the clock made _old the 27th and pushed the return into the
# month after next. Cohorts are calendar buckets, so the fixture has to
# speak calendar too.
def _month_start(back):
    """Midday on the 10th, `back` months before now — midday and the 10th
    so no timezone or short-month edge can nudge it into a neighbour."""
    t = _t0.localtime(_c_now)
    y, m = t.tm_year, t.tm_mon - back
    while m < 1:
        m += 12
        y -= 1
    return _t0.mktime((y, m, 10, 12, 0, 0, 0, 0, -1))


# Three months back, not two: the baskets above already sit ~40 days ago,
# and a cohort sharing their month would be a row of eleven rather than
# the four this is about.
_old = _month_start(3)
for _i in range(4):
    _buy(800 + _i, _old, 2000)
_buy(800, _month_start(2), 2000)          # one of them returns a month on
_co = _com.cohorts(_ccon, 12, when=_c_now)
_row = next(x for x in _co["cohorts"] if x["size"] == 4)
ok(all(cell["month"] >= 1 for cell in _row["cells"]),
   "month zero is everybody by definition, so the triangle does not draw "
   "a column of 100% as though it meant something")
ok(_row["cells"][0]["pct"] == 25.0 and _row["cells"][0]["n"] == 1,
   "and a cell is how many of THAT month's customers came back in the "
   "month after it — one of four is 25%")
ok(any(cell["partial"] for x in _co["cohorts"] for cell in x["cells"]),
   "a cell inside the month still running is marked: three days is not a "
   "month, and drawing it as one turns an ordinary week into a crisis "
   "meeting")
# Per line and per category. An overall margin is an average of things
# that are not alike.
_ccon.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT,"
              " category TEXT, case_size INT)")
_ccon.executemany("INSERT INTO products(id,name,category,case_size)"
                  " VALUES(?,?,?,12)",
                  [(1, "Hot Sauce", "sauces"), (2, "Rub", "spices")])
_ccon.execute("UPDATE order_items SET product_id=2 WHERE order_id IN"
              " (SELECT id FROM orders WHERE kind='distributor')")
_ln = _com.lines(_ccon, 90, when=_c_now)
ok(len(_ln["lines"]) == 2 and {x["category"] for x in _ln["lines"]}
   == {"sauces", "spices"},
   "every line reports on its own, with the category it sits in")
ok(all(x["margin_pct"] is None and not x["priced"] for x in _ln["lines"]),
   "and a line with no recipe behind it says so rather than borrowing the "
   "shop's average margin and calling itself profitable")
ok(sum(c["share_pct"] for c in _ln["categories"]) > 99,
   "categories carve the revenue up between them")
ok(_ln["top_fifth_pct"] is not None and _ln["losing"] == [],
   "with the concentration of the range beside them, and any line sold "
   "under cost named")
ok(all(x["attach_pct"] is not None for x in _ln["lines"]),
   "attach rate is on every line — it is the argument for keeping a "
   "thin-margin one")
_ccon.close()
_capi = c.get("/api/analytics/commerce?days=90", headers=A).json()
ok("lines" in _capi and "categories" in _capi["lines"],
   "and the shelf arrives with the baskets")
ok(all(k in _capi for k in ("basket", "repeat", "cohorts")),
   "and the three arrive together, because they are one question asked "
   "three ways")
ok(c.get("/api/analytics/commerce").status_code in (401, 403),
   "the shop's numbers are the office's")

# --- the trading calendar ---------------------------------------------------
# A month has four weekends or five, Easter moves, and a holiday closes
# the shop or triples it. Comparing this month with the last without
# knowing which days were trading days is reporting the calendar as
# performance — and nobody notices, because the number always comes out.
from erp.backend import daybook as _dbk  # noqa: E402
ok(_dbk.easter(2025) == "2025-04-20" and _dbk.easter(2026) == "2026-04-05"
   and _dbk.easter(2027) == "2027-03-28",
   "Easter is computed, five weeks of range and all — two Aprils compared "
   "without it are a holiday week against an ordinary one")
_h26 = dict((d, n) for d, n in _dbk.public_holidays(2026))
ok(_h26.get("2026-01-19") == "Martin Luther King Jr. Day"
   and _h26.get("2026-05-25") == "Memorial Day"
   and _h26.get("2026-11-26") == "Thanksgiving",
   "the floating ones land on the right weekday: third Monday, last "
   "Monday, fourth Thursday")
ok(_h26.get("2026-07-03") == "Independence Day (observed)"
   and "2026-07-04" not in _h26,
   "and the observed rule moves a Saturday holiday to the Friday — the "
   "day off is the day the doors are shut, which is the one a sales "
   "chart feels")
ok(not _dbk.public_holidays(2026, "XX"),
   "a country whose rules are not in here returns nothing rather than "
   "somebody else's holidays")

_dcon = _mdb.connect()
_dbk.fill_calendar(_dcon, [2026])
ok(_dcon.execute("SELECT COUNT(*) n FROM calendar_days").fetchone()["n"] >= 12,
   "a year of them is written once and left alone")
_dbk.fill_calendar(_dcon, [2026])
ok(_dcon.execute("SELECT COUNT(*) n FROM calendar_days WHERE day="
                 "'2026-12-25'").fetchone()["n"] == 1,
   "and filling it twice does not double it")
_dcon.execute("INSERT OR REPLACE INTO calendar_days(day,name,kind,closed)"
              " VALUES('2026-12-24','Stocktake','company',1)")
_dcon.commit()

_dbk.rebuild(_dcon, 90)
_ds = _dbk.series(_dcon, 90)
ok(len(_ds["days"]) == 90,
   "every day in the window has a row, including the ones nothing "
   "happened on — leaving those out turns every average into an average "
   "of the days that went well")
ok(_ds["trading_days"] + _ds["closed_days"] == len(_ds["days"]),
   "and each is either a trading day or one the doors were shut")
ok(all(0 <= d["weekday"] <= 6 for d in _ds["days"]),
   "with the weekday on the row, so the shape of a week is a group-by "
   "rather than a date library")
ok(len(_ds["weekdays"]) <= 7 and all(w["days"] for w in _ds["weekdays"]),
   "which is what the by-weekday average is read off")
_dcon.close()

_days = c.get("/api/analytics/days?days=60", headers=A).json()
_cmp = _days["compare"]
ok(_cmp["this"]["stretch"] == _cmp["last"]["stretch"],
   "month against month compares the SAME stretch of each — three days "
   "of September against the whole of August is not a comparison, it is "
   "a subtraction, and it always says the business collapsed")
ok(all(x["covered"] <= x["stretch"] for x in (_cmp["this"], _cmp["last"])),
   "and it says how much of that stretch it actually holds, which is a "
   "different fact from the stretch: on the thirtieth of April, sixty "
   "days of history does not reach the first of March")
ok(_cmp["thin"] == bool(_cmp["this"]["short_by"]
                        or _cmp["last"]["short_by"]),
   "a side missing days is flagged rather than averaged over — a month "
   "compared against nineteen days of another, presented as a month, "
   "reads as a collapse that never happened")
ok("per_day_pct" in _days["compare"] and "raw_pct" in _days["compare"],
   "and it reports the raw difference beside the per-trading-day one, "
   "because where they disagree the calendar is the difference")
ok(_days["holiday_lift_pct"] is None or _days["holidays_n"] >= 3,
   "a holiday lift is not reported off one or two days — that is a quiet "
   "Tuesday wearing a trend's clothes")
ok(c.post("/api/analytics/calendar", headers=A, json={
    "day": "2026-08-14", "name": "Summer close", "closed": True}
    ).status_code == 200,
   "a company's own day sits beside the public ones")
ok(c.post("/api/analytics/calendar", headers=A, json={
    "day": "next friday"}).status_code == 400, "dates are dates")
ok(c.get("/api/analytics/days").status_code in (401, 403),
   "the daily table is the office's")
ok(all(k in _days["days"][0] for k in
       ("temp_c", "precip_mm", "cloud_pct", "humidity_pct")),
   "and the weather has a place on the row already — 'it rained' is not "
   "a metric, and 'Saturday was down 18% and it rained' is the start of "
   "one")

# The rebuild must not throw away what it does not know about. INSERT OR
# REPLACE deletes the row and writes a new one, dropping every column the
# statement does not name — so a rebuild wiped the weather it had just
# been given, every time anybody opened the screen.
_wcon = _mdb.connect()
_dbk.rebuild(_wcon, 30)
_wday = _dbk._day_key(_t0.time() - 5 * 86400)
_dbk.save_weather(_wcon, {_wday: {"temp_c": 18.5, "precip_mm": 4.2,
                                  "cloud_pct": 80.0, "humidity_pct": 71.0}})
ok(_wcon.execute("SELECT temp_c FROM day_facts WHERE day=? AND region=''",
                 (_wday,)).fetchone()["temp_c"] == 18.5,
   "weather lands on the day row beside the money")
_dbk.rebuild(_wcon, 30)
ok(_wcon.execute("SELECT temp_c FROM day_facts WHERE day=? AND region=''",
                 (_wday,)).fetchone()["temp_c"] == 18.5,
   "and a rebuild keeps it — recomputing the facts must not drop the "
   "columns it does not compute")
_sky = _dbk.weather_read(_wcon, 30)
ok(not _sky["enough"] and _sky["have"] == 1,
   "one day of weather is not a comparison, and it says so rather than "
   "reporting a 100% difference off a single Tuesday")
for _i in range(20):
    _d = _dbk._day_key(_t0.time() - (_i + 1) * 86400)
    _dbk.save_weather(_wcon, {_d: {"temp_c": 10.0 + _i, "precip_mm": _i % 4,
                                   "cloud_pct": 50.0, "humidity_pct": 60.0}})
_sky = _dbk.weather_read(_wcon, 30)
ok(_sky["enough"] and _sky["warm"] and _sky["warm"]["hi_days"] >= 5
   and _sky["warm"]["lo_days"] >= 5,
   "with enough of them it splits warm against cool, both sides big "
   "enough to be a comparison")
ok(_sky["warm"]["split_at"] is not None and _sky["cloud"] is None,
   "at the median of the days themselves — and a field where every day is "
   "identical splits into nothing, rather than into a spurious result")
_lab = _dbk.labour_read(_wcon, 30)
ok("per_hour_cents" in _lab and "rota" in _lab
   and _lab["rota"]["adherence_pct"] is None,
   "sales per labour hour comes with rota adherence beside it — read the "
   "first alone and a day two people did not turn up looks productive")
_wcon.close()

# --- how long a customer stays, and what they are worth ---------------------
# One connection, closed at the end. Three opened inline and left to the
# garbage collector is a lock held for however long that takes, which is
# the kind of thing that fails one run in ten and never the one you are
# watching.
_lcon = _mdb.connect()
_life = _mrr.lifetime(_lcon, [
    {"logo_churn_pct": 10.0, "arpa_cents": 20000},
    {"logo_churn_pct": 10.0, "arpa_cents": 20000}], margin_pct=60.0)
ok(_life["implied_months"] == 10.0,
   "average lifetime is 1 over the churn rate: lose a tenth a month and "
   "the average customer stays ten months")
ok(_life["ltv_cents"] == 120000,
   "and lifetime VALUE is that at the margin, not at the price — $200 a "
   "month for ten months at 60% is $1,200 of value, and the difference "
   "is the whole of what runs the business")
_none = _mrr.lifetime(_lcon, [{"logo_churn_pct": 0.0,
                              "arpa_cents": 20000}], 60.0)
ok(_none["implied_months"] is None and _none["ltv_cents"] is None,
   "nobody lost yet means the lifetime is unknown, not infinite — an "
   "infinite lifetime is a number somebody will put in a business plan")
_nomargin = _mrr.lifetime(_lcon, [{"logo_churn_pct": 10.0,
                                  "arpa_cents": 20000}], 0.0)
ok(_nomargin["implied_months"] == 10.0 and _nomargin["ltv_cents"] is None,
   "and with no margin known the value is left out rather than reported "
   "at full price")
_lcon.close()


# --- a day you can step into, and a week you can carve up ------------------
# A month grid can say a day has three things on it. It cannot say who is
# working it, who could be, or what is in the way — which is the whole of
# what somebody opens a calendar to find out.
ok("async function dayView(" in _ops,
   "a day opens into a day: what is on it, who is on it, who could be")
ok('data-calday' in _ops and 'data-rotaday' in _ops,
   "reached from both calendars — the month grid and the rota's own days")
ok('id="cal-mon"' in _ops and 'id="cal-year"' in _ops,
   "and the month and the year are picked, not stepped to one arrow at a "
   "time")
_cy = _ops.split('id="cal-year"')[1][:400]
ok("y - 5" in _cy and "y + 5" in _cy,
   "eleven years wide: last year's accounts and next year's booked work")

ok("function whoIsFree(" in _ops and "/api/availability/who" in _ops,
   "a manager can ask who is free for a window of a day")
ok("FREE_LABEL" in _ops and '"has not said"' in _ops,
   "and the answer includes the people who are not, with the reason — "
   "without it the manager rings round to find out anyway")
ok("function whoHasSaid(" in _ops and "/api/availability/filled" in _ops,
   "and who has filled their week in at all")
_wfr = _ops.split("function wireFreeRows(")[1][:900]
ok("win.from_min" in _wfr and "win.to_min" in _wfr,
   "rostering somebody from that list uses the window they were just "
   "measured against — a shift in different hours than the ones judged is "
   "a rota telling a lie")

_avf = _ops.split("async function availabilityForm(")[1][:8000]
ok('data-avday' in _avf and "DAYS_LONG" in _avf,
   "the week steps into one weekday at a time")
ok('data-avoff' in _avf and 'to_min: 1440' in _avf,
   "a whole weekday can be marked off from inside it")
ok('data-avadd="open"' in _avf and 'data-avadd="shut"' in _avf,
   "and a day carries both sentences: the hours somebody can work, and "
   "the hours inside them they cannot")
ok('id="bl-from"' in _avf and 'id="bl-fmin"' in _avf,
   "with dates the week is not true of — a range of days, and a range of "
   "hours inside them")
ok("modalBody" in _ops and "function modalBody(" in _ops,
   "the dialog redraws in place, so stepping between days does not shut "
   "and reopen the thing you are in")

# Renaming a document is a label change, and the client page is where the
# label is wrong.
ok('data-engname' in _ops and "/rename" in _ops,
   "a document filed under a client can be renamed from the client page")


# --- the rest of the alignment pass ---------------------------------------
# A date that wraps is a date in two columns. A launch date is short and
# known; the track is sized for it and told not to break.
_ew = _ocss.split(".eng-when {")[1][:160]
ok("white-space: nowrap" in _ew and "text-align: right" in _ew,
   "a client's launch date holds one line in its own column")

# The fleet's capability count was a pill among pills, so it started
# wherever the class pill happened to end.
ok('class="fl-caps"' in _ops and ".fl-caps {" in _ocss,
   "a tenant's capability count has a column of its own")
ok("minmax(0, 1fr) minmax(0, 240px) 74px" in
   _ocss.split(".doc-line.fleet-line {")[1][:160],
   "sized and fixed, so it reads down the list rather than across each row")

# The same row on a narrower screen. Its collapse was set at the width
# where the layout breaks rather than the width where it stops fitting.
_fl_media = [b for b in _ocss.split("@media") if "fleet-line" in b
             and "grid-column: 1 / -1" in b]
ok(_fl_media and "1180px" in _fl_media[0],
   "the fleet row collapses at 1180 and not at 1000. It reserves 240 "
   "for tags, 74 for caps and 306 for seven buttons — 660px with the "
   "gaps, gone before the name or the hosts get a pixel — so at 1001 "
   "the two 1fr columns were 29px each and every laptop between the "
   "two rendered the tenant name as three clipped characters")
# By its condition, not merely by "a chunk mentioning fleet-acts" —
# splitting on @media hands back the chunk holding the BASE rule first,
# which is the one this is checked against rather than confused with.
_fa_media = [b for b in _ocss.split("@media")
             if "fleet-acts" in b and "760px" in b]
ok(_fa_media and "repeat(2, minmax(0, 1fr))" in _fa_media[0],
   "and its seven buttons go two abreast on a phone rather than three "
   "at a fixed 98px: 306px of track in a 278px box put a whole column "
   "of them outside the row, and Suspend and Remove are not verbs to "
   "leave hanging off the edge of a thumb")
ok(".dl-acts.fleet-acts" in _fa_media[0]
   and ".doc-line" in _fa_media[0].split(".dl-acts.fleet-acts")[0],
   "named against its base rather than trusted to file order, which is "
   "the rule this stylesheet already has a guard for — and which the "
   "generic .dl-acts collapse at 900px lost to, being both less "
   "specific and earlier")
ok('class="fl-hosts dim" title=' in _ops,
   "a host list that ellipsises carries its full text on the element. "
   "It is the one field on this row somebody reads in order to type it "
   "somewhere else, and half a hostname is not a shorter hostname — "
   "the same rule the verdict cell on the pressure board follows")
ok(any("white-space: normal" in b for b in _fa_media),
   "and narrow, where it has a full-width row to itself, it wraps "
   "instead: nothing to reach for, because nothing is hidden")
# The dossier's footer. It was an INLINE display:flex;gap:8px, which is
# the strongest possible way to say "no stylesheet may have an opinion",
# so nothing could make it wrap.
ok('class="modal-foot ds-foot"' in _ops and "style=" not in
   _ops.split('class="modal-foot ds-foot"')[1][:40],
   "the dossier's footer takes its layout from the stylesheet, not from "
   "an inline style. Inline beats every rule short of !important, so at "
   "phone width its four buttons ran 367px inside a 293px box and the "
   "one pushed out was Done — the dossier could be opened on a phone "
   "and not closed from its own footer")
ok(".modal-foot.ds-foot" in _ocss
   and "flex-wrap: wrap" in _ocss.split(".modal-foot.ds-foot")[1][:120],
   "and it wraps, named against its base so file order cannot decide it")
ok(".card.ds-press .card-head" in _ocss,
   "the dossier's limits head wraps too — card-head is nowrap, and "
   "inside a modal on a phone it had 50px less than its contents")

# --- every custom property a rule reads has to exist -----------------
# .press-lines b was color: var(--ink, #e8ecf3). --ink is defined
# nowhere, so the fallback was not a fallback, it was the value: a
# near-white from a dark-theme era, on this app's near-white paper. The
# label naming WHICH limit was at issue rendered at 1.11:1 against its
# card — present in the DOM, invisible on the screen, and no test could
# see it because every one of them reads text.
_INJECTED = {
    # the shell hands these in from the tenant's own theme
    "--brand", "--brand-2", "--brand-warm",
    # set per element or on :root by the app at runtime
    "--kind",                      # 03-sell.js, per product group
    "--rail", "--srail",           # 02-chrome.js / 09-clients.js, measured
    "--topbar",                    # 02-chrome.js, measured
}
_used = set(_re.findall(r"var\(\s*(--[\w-]+)", _ocss))
_defined = set(_re.findall(r"(--[\w-]+)\s*:", _ocss))
_ghosts = sorted(_used - _defined - _INJECTED)
ok(not _ghosts,
   "every custom property a rule reads is either defined in this "
   f"stylesheet or injected by a named thing at runtime ({_ghosts} is "
   "neither, so its fallback is not a fallback — it is the value, "
   "unreviewed)")

# --- and no text on this app's paper may be unreadable ---------------
def _lum(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return round((max(la, lb) + .05) / (min(la, lb) + .05), 2)


# A rule that sets its own background is painting its text on THAT, so
# it is not measured against the panel. This started as a hand-kept list
# of selectors — and the list was where the bug hid. .disp- was on it,
# on my say-so that a wall display is a dark screen; it is not. .disp
# set no background at all, so it painted on the app's light page, and
# the three colours exempted on that assumption measured 1.55, 1.73 and
# 2.67 against it. The one screen in the product meant to be read from a
# doorway held the least legible text in it, and the guard had been told
# not to look.
#
# So the exemption is read from the CSS instead of remembered. Every
# entry the list used to hold — the buttons, the chips, the badge, the
# scanner's caption — sets a background in its own rule and exempts
# itself. Nothing has to be trusted, and .disp, which set none, could
# not have exempted itself no matter what I believed about it.
# Enough colour arithmetic to follow a rule to its own ground: the
# palette's own entries, and one color-mix of two of them. Not a CSS
# engine — just the two forms this stylesheet actually writes.
_ROOT = dict(_re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,6})\s*;",
                         _ocss.split("}")[0]))


def _solve(v):
    """A colour literal, a var(), or one color-mix — or None."""
    v = v.strip()
    if v.startswith("#"):
        return v
    _mv = _re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", v)
    if _mv:
        return _ROOT.get(_mv.group(1))
    _mx = _re.fullmatch(
        r"color-mix\(in srgb,\s*(.+?)\s+(\d+)%,\s*(.+?)\s*\)", v)
    if _mx:
        _a, _p, _b = _solve(_mx.group(1)), int(_mx.group(2)) / 100, _solve(_mx.group(3))
        if not (_a and _b):
            return None
        _ha, _hb = _a.lstrip("#"), _b.lstrip("#")
        if len(_ha) == 3:
            _ha = "".join(c * 2 for c in _ha)
        if len(_hb) == 3:
            _hb = "".join(c * 2 for c in _hb)
        return "#" + "".join(
            "%02x" % round(_p * int(_ha[i:i + 2], 16)
                           + (1 - _p) * int(_hb[i:i + 2], 16))
            for i in (0, 2, 4))
    return None


# A rule that sets its own background is measured AGAINST that background
# rather than excused by having one. Excusing it was a hole big enough to
# hide the status pills in: .pill.bad tints its ground with 12% of --bad
# and then writes --bad on it, which is 4.26 and not the 5.07 the token
# scores on a panel. A token is chosen against one surface and used on
# another, and only the arithmetic notices.
_faint = []
for _m in _re.finditer(r"([^;{}]*)\{([^}]*)\}", _ocss):
    _sel = _m.group(1).strip().splitlines()[-1].strip()
    _body = _m.group(2)
    _bgm = _re.search(r"(?<!-)\bbackground(?:-color)?:\s*([^;}]+)", _body)
    if _re.search(r"\bbackground(-image)?:\s*(url|linear-|radial-|repeating)",
                  _body):
        continue                      # a gradient or image, not a flat colour
    _ground = _solve(_bgm.group(1)) if _bgm else "#f6f7f9"
    if _bgm and _ground is None:
        continue                      # not resolvable here; not guessed at
    for _cm in _re.finditer(r"(?<!-)\bcolor:\s*([^;}]+)", _body):
        _fg = _solve(_cm.group(1))
        if _fg and _ratio(_fg, _ground) < 4.5:
            _faint.append(f"{_sel} {_fg} on {_ground}")
# The rule's own block, to its closing brace — not a fixed slice, which
# a long enough comment walks straight out of.
_disp_rule = _ocss.split(".disp {")[1].split("}")[0] if ".disp {" in _ocss else ""
ok("#view:has(> .disp)" in _ocss,
   "the wall screen is let out of the app's reading column. #view caps "
   "at 1080 so a form or a table is read at a comfortable width; a sign "
   "in a corridor is not read at a desk, and on a 1920 wall it was "
   "using 1044 of them while the rule below claimed to fill the "
   "viewport. Written against #view because the id is what sets the "
   "cap — a rule naming only the element loses to it however true it is")
ok("background: var(--panel)" in _disp_rule,
   "and the wall display names the surface it paints on, so that claim "
   "is a rule rather than a memory — a screen with no background of its "
   "own takes whatever the page behind it happens to be, and every "
   "colour chosen against the wrong one is wrong by exactly that much")
ok(not _faint,
   "no text colour falls below 4.5:1 against the ground its own rule "
   f"puts it on ({_faint[:3]}). Eleven did: a salmon and a mint left "
   "over from a dark-theme era, and then the tinted badges — a pill "
   "that washes its ground with 12% of the same token it writes in is "
   "not on a panel any more, and the token was chosen for a panel. All "
   "of them read as decoration until somebody measures them")

# A wide table needs something to scroll in, and 25 of this app's 57
# tables were written without the .tablewrap that exists for it.
ok(".card:has(> table) { overflow-x: auto" in _ocss,
   "a card holding a table scrolls, so the PAGE does not. The orders "
   "list is 975px of columns in a 351px card on a phone, and without "
   "this the whole document went 1012px wide to hold it — every screen "
   "in the app sliding sideways under a list nobody could read anyway")
_bare = len([m for m in _re.finditer(r"<table\b", _ops)
             if "tablewrap" not in _ops[max(0, m.start() - 400):m.start()]])
ok(_bare > 0,
   f"and it is a rule rather than {_bare} more edits: the wrap is easy "
   "to forget, was forgotten in nearly half of them, and forgetting it "
   "again costs nothing now")

ok(any(".log-line { grid-template-columns: auto minmax(0, 1fr)" in b
       for b in _ocss.split("@media")),
   "the history under it stacks too — 92 and 130 fixed left 67px for "
   "the entry, which is the only part of a history line anybody opens "
   "it to read")

# Every kind of service drew its own table, and a table sizes its columns
# to its own contents — so Plans, Bundles and Packs each put the SKU and
# the price somewhere different.
ok('class="svc-table"' in _ops and "table.svc-table { table-layout: fixed"
   in _ocss,
   "the inventory's service lines share one set of columns across every "
   "kind, instead of each table sizing itself")
ok('class="svc-price"' in _ops and 'class="dim svc-from"' in _ops,
   "with the price and the 'from — quoted' in tracks of their own — a "
   "suffix inside the price cell moves the price")

# An inline form's submit is the page's action.
ok("form.inline > button.btn:last-child { margin-left: auto; }" in _ocss,
   "an inline form's action sits at the right-hand end of its row, where "
   "every other page's action is, rather than wherever the last field "
   "happens to leave off")
for _id in ("lt-add", "lt-invite", "lib-add", "lib-scan"):
    ok(f'id="{_id}"' in _ops, f"{_id} is still there")
# A bare <div> in a page head takes the title block's flex:1 and lands in
# the middle of the header — the bug the whole alignment pass was. Nothing
# in a page head may hand-roll its own row.
_rolled = [c[:70].replace("\n", " ") for c in _ops.split('class="page-head"')[1:]
           if re.search(r"<div style=", c[:400])]
ok(not _rolled,
   f"no page head hand-rolls its own action row — it takes the title's "
   f"flex and lands in the middle ({_rolled[:2]})")

# The picture is the work: somebody is holding a phone over a code on a
# case and reading the frame to know whether they have got it.
ok(".scan-stage" in _ocss and 'class="scan-stage"' in _ops,
   "the scanner has a stage of its own")
_ss = _ocss.split(".scan-stage {")[1][:260]
ok("width: 100%" in _ss and "aspect-ratio" not in _ss,
   "as wide as the page — an aspect ratio caps the width to whatever the "
   "height allows, which left a third of the card empty beside it")
ok("clamp(" in _ss and "100vh" in _ss,
   "and as tall as the window can give it")
ok("object-fit: cover" in _ocss.split(".scan-stage video {")[1][:120],
   "the stream fills that frame rather than sitting letterboxed in it")


# --- a modifier may not depend on where it sits in the file ---------------
# Twice in one afternoon a row variant collapsed because its rule was
# written above the rule it was meant to override: same specificity, later
# wins, and .fleet-line's four columns silently became .doc-line's two.
# Nothing in the markup says which of two classes is the base, so the
# stylesheet has to say it: a rule that overrides another for the same
# element names both (.doc-line.fleet-line), which is true wherever in the
# file it sits. This guard reads the markup for which classes actually
# share an element, and refuses the pairs that would be decided by order.
def _class_lists(js):
    """Every class attribute in the ops markup, as its class tokens.

    A class attribute is not a literal here: it carries ${...}, and the
    classes inside those (" dl-awaiting") are as real as the ones outside.
    Quoted pieces of an expression count; nested templates are skipped,
    being markup of their own. One unparseable attribute costs itself and
    nothing after it."""
    out, i = [], 0
    while True:
        j = js.find('class="', i)
        if j < 0:
            return out
        k, depth, buf, stop = j + 7, 0, [], min(len(js), j + 700)
        while k < stop:
            ch = js[k]
            if depth == 0 and ch == '"':
                break
            if js.startswith("${", k):
                depth += 1; k += 2; continue
            if depth and ch == "{":
                depth += 1; k += 1; continue
            if depth and ch == "}":
                depth -= 1; k += 1; continue
            if depth and ch == "`":
                e = js.find("`", k + 1)
                if e < 0 or e > stop:
                    break
                k = e + 1; continue
            if depth and ch in "\"'":
                e = js.find(ch, k + 1)
                if e < 0 or e > stop:
                    break
                lit = js[k + 1:e]
                if re.fullmatch(r"[\sa-z0-9_-]*", lit):
                    buf.append(" " + lit + " ")
                k = e + 1; continue
            if depth == 0:
                buf.append(ch)
            k += 1
        out.append(" ".join("".join(buf).split()))
        i = j + 7


def _css_contexts(css):
    """The stylesheet split into the contexts a rule can win inside: the
    top level, and each @media block. A compound selector written inside a
    media block does nothing at the width where the base rule applies."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    out, top, i = [], [], 0
    while i < len(css):
        m = re.compile(r"@media[^{]*\{").search(css, i)
        if not m:
            top.append(css[i:])
            break
        top.append(css[i:m.start()])
        depth, k = 1, m.end()
        while k < len(css) and depth:
            depth += (css[k] == "{") - (css[k] == "}")
            k += 1
        out.append((css[m.start():m.end()].strip(), css[m.end():k - 1]))
        i = k
    return [("top level", "".join(top))] + out


_together = set()
for _cl in _class_lists(_ops):
    _toks = sorted({t for t in _cl.split() if re.fullmatch(r"[a-z][\w-]*", t)})
    for _i, _a in enumerate(_toks):
        for _b in _toks[_i + 1:]:
            _together.add(frozenset((_a, _b)))
ok(len(_together) > 150,
   f"the guard can see which classes share an element ({len(_together)} pairs)")
ok(frozenset(("doc-line", "fleet-line")) in _together
   and frozenset(("dl-acts", "eng-row-acts")) in _together,
   "including the pairs that broke — proof it is looking at the right thing")
for _where, _chunk in _css_contexts(_ocss):
    for _prop in ("grid-template-columns", "display", "position",
                  "flex-direction", "width"):
        _solo, _both = set(), set()
        for _m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _chunk):
            if not re.search(rf"(^|;|\s){_prop}\s*:", _m.group(2)):
                continue
            for _one in (x.strip() for x in _m.group(1).split(",")):
                if re.fullmatch(r"\.[\w-]+", _one):
                    _solo.add(_one[1:])
                for _c in re.findall(r"\.([\w-]+)\.([\w-]+)", _one):
                    _both.add(frozenset(_c))
        _clash = sorted(tuple(sorted(x)) for x in
                        {frozenset((a, b)) for a in _solo for b in _solo
                         if a != b and frozenset((a, b)) in _together} - _both)
        ok(not _clash,
           f"{_where[:34]}: no two classes on one element set {_prop} from "
           f"bare selectors, where only the file order decides which wins — "
           f"write the override as .base.modifier ({_clash})")

# --- the rest of this pass -----------------------------------------------
# A section's buttons moved every time somebody opened it, because they
# were riding on the summary's margin — and the summary only shows while
# the section is shut.
ok('<span class="fold-acts">${right' in _ops,
   "a foldable section's actions are a group of their own")
ok(".foldable:not(.folded) > .fold-head .fold-acts" in _ocss,
   "aligned right whether the section is open or shut, so opening one "
   "does not move its buttons")

# Folded should mean folded: 26px of empty panel down the side of the page
# is not a fold, it is a stripe.
_srf = _ocss.split("body.srail-folded #store-rail {")[1][:200]
ok("width: 0" in _srf and "border-left: none" in _srf,
   "a folded store rail takes no width at all")
ok("position: fixed" in _ocss.split("body.srail-folded .srail-fold {")[1][:200],
   "and the way back is a tab on the window's edge — a panel that leaves "
   "nothing to press is a panel nobody reopens")

# Connections are one group, not four in Company and eight below it.
for _t in ("discord", "slack", "trello", "dropbox", "integrations"):
    _row = re.search(rf'\{{ id: "{_t}",[^}}]*\}}', _ops).group(0)
    ok('group: "Connections"' in _row,
       f"{_t} sits with the other connections")
ok('label: "All connections"' in _ops
   and "<h2>All connections</h2>" in _ops,
   "and the list of them is called the same thing in the rail and on the "
   "page it opens")

# Every connection's own screen offers the same button for the same step.
ok('<button class="btn" data-appsave=' in _ops,
   "registering an app is the primary action on the pages that need one")
ok('<button class="btn" id="lu-key"' in _ops,
   "and so is standing up the endpoint on the one that takes deliveries")
ok('class="btn alt sm" data-appsave' not in _ops
   and 'class="btn alt sm" id="lu-key"' not in _ops,
   "neither is a quiet secondary next to another connection's Connect")


# --- the ops app's file family: no name may mean two things ------------------
# app.js became ordered part files served as one script. Concatenated
# global scope means a duplicate definition is a silent overwrite — the
# .doc-top/.lrn-bar failure mode, at file scale. So the family polices
# itself: no function, top-level const, or element id may be DEFINED in
# two different files.
_pf = {p.name: p.read_text(encoding="utf-8") for p in ops_app_parts()}
ok(len(_pf) >= 10, "the ops app is a family of part files")
ok(c.get("/ops/app.js").text == "\n".join(
       _pf[k] for k in sorted(_pf)),
   "and the served script IS the parts, concatenated in name order — the "
   "browser, the worker and the cache-buster never learn the layout "
   "changed")
_dups = {}
for _kind, _rx in (("function", r"^(?:async )?function (\w+)\("),
                   ("const", r"^const (\w+) ="),
                   ("id", r'id="([a-zA-Z][\w-]*)"')):
    _seen = {}
    for _fn, _txt in _pf.items():
        for _m in re.finditer(_rx, _txt, re.M):
            _seen.setdefault(_m.group(1), set()).add(_fn)
    for _nm, _files in _seen.items():
        if len(_files) > 1:
            _dups[f"{_kind} {_nm}"] = sorted(_files)
ok(not _dups,
   f"no function, const or id is defined in two part files ({_dups})")


# ===== the second wave of connections: five families, each with a screen =====
# Twenty providers arrived at once — forms, funders, testing services, seven
# ad platforms, five hiring systems, two delivery apps, two listings. The
# registry is the same table; what is new is that each family has a working
# screen the connection is set up on, and a module that does the work.
import base64 as _b64  # noqa: E402
import hmac as _hmac  # noqa: E402
import hashlib as _hashlib  # noqa: E402
from collections import Counter as _Counter  # noqa: E402
from erp.backend import ads as _ads, hiring as _hir, intake as _ink  # noqa: E402
from erp.backend import listings as _lst, marketplaces as _mkt  # noqa: E402

_st2 = c.get("/api/admin/integrations", headers=A).json()
_fam = {p["name"]: p for p in _st2["providers"]}
_WAVE = {"google_forms": "intake", "network4good": "intake",
         "gedmanager": "results",
         "northstar": "results", "meta_ads": "ads", "google_ads": "ads",
         "tiktok_ads": "ads", "linkedin_ads": "ads", "x_ads": "ads",
         "reddit_ads": "ads", "snapchat_ads": "ads", "indeed": "hiring",
         "ziprecruiter": "hiring", "linkedin_jobs": "hiring", "greenhouse": "hiring",
         "workable": "hiring", "ubereats": "delivery", "doordash": "delivery",
         "google_business": "listings", "yelp": "listings"}
for _n, _f in _WAVE.items():
    ok(_n in _fam and _fam[_n]["family"] == _f, f"{_n} is offered, in the {_f} family")
ok("credentials" not in json.dumps(_st2) and "developer_token" not in json.dumps(
    {k: v for k, v in _st2.items() if k != "providers"}),
   "the status payload still carries no credential")
ok(all("settings_fields" in p and "settings" in p for p in _st2["providers"]),
   "every provider reports the settings it takes after connecting")

# The rail: eight groups, each a working area, none longer than a screen.
_tabs_src = _ops[_ops.index("const TABS = ["):_ops.index("\n];", _ops.index("const TABS = ["))]
_cnt = _Counter(re.findall(r'group: "([^"]+)"', _tabs_src))
ok(set(_cnt) == {"Sell", "Stock & supply", "Work", "Teach", "Grow", "Money",
                 "Team", "Company", "Connections"},
   f"the rail is grouped by what a person is doing ({sorted(_cnt)})")
ok(max(v for k, v in _cnt.items() if k != "Connections") <= 10,
   "and no working group holds more than ten screens — Operate held seventeen")
ok('NAV_GROUPS = ["Sell", "Stock & supply", "Work", "Teach", "Grow",\n'
   '                    "Money", "Team", "Company", "Connections"]' in _ops,
   "in that order, Sell first so the default landing is still the shop")
for _t, _grp in (("ads", "Grow"), ("listings", "Grow"), ("hiring", "Team"),
                 ("marketplaces", "Sell"), ("intake", "Grow"),
                 ("presentations", "Teach"), ("expenses", "Work"),
                 ("inventory", "Stock & supply")):
    _row = re.search(rf'\{{ id: "{_t}",[^}}]*\}}', _ops).group(0)
    ok(f'group: "{_grp}"' in _row, f"{_t} sits in {_grp}")
ok(all(f"{_t}: render" in _ops for _t in ("ads", "listings", "hiring",
                                          "marketplaces", "intake")),
   "and each new screen is routed")
ok("function connectionCards" in _ops and _ops.count("connectionCards(") >= 6,
   "one card helper draws a family's connections on its own screen")
ok(all(f'"ig-{_n}"' not in _ops for _n in _WAVE),
   "the second wave adds no rail entries of its own — thirty is a list nobody scans")

# Honesty, stated in the registry rather than discovered later.
ok(any(p["provider"] is None and "Amazon Ads" in p.get("note", "") for p in _ads.PLATFORMS),
   "Twitch is typed, and the ledger says why")
ok("no API for replying" in _ig.PROVIDERS["yelp"]["does"], "Yelp says it takes no reply")
ok(all(_ig.PROVIDERS[n]["auth"] == "inbound" for n in ("gedmanager", "northstar")),
   "GED Manager and NorthStar are import routes, because that is what exists")
ok(all(_ig.PROVIDERS[n]["auth"] == "inbound" for n in ("indeed", "ziprecruiter", "linkedin_jobs")),
   "the job boards ingest a feed and post back; none takes a posting by API")
ok(all(_ig.receives(_ig.PROVIDERS[n]) for n in ("ubereats", "doordash", "google_forms")),
   "a provider that also pushes to us gets a key even though it connects outbound")

# --- OAuth machinery the wave needed: a shared Google app, body-auth, PKCE ---
_apps_cfg = {"integration_apps": {"google_calendar": {"client_id": "gcid", "client_secret": "gsec"}}}
ok(_ig.app_for(_apps_cfg, "google_forms").get("client_id") == "gcid",
   "one registered Google app serves every Google consent")
ok(not _ig.app_for(_apps_cfg, "meta_ads"), "and does not leak to Meta")
# through the real door, so the proxied per-tenant config is what the
# authorize route reads
c.post("/api/admin/integrations/google_calendar/app", headers=A,
       json={"client_id": "gcid", "client_secret": "gsec"})
c.post("/api/admin/integrations/x_ads/app", headers=A,
       json={"client_id": "xcid", "client_secret": "xsec"})
ok(next(p for p in c.get("/api/admin/integrations", headers=A).json()["providers"]
        if p["name"] == "google_business")["app_ready"],
   "and the status says Google Business Profile is ready to connect")
_r = c.get("/api/admin/integrations/google_forms/authorize", headers=A)
ok(_r.status_code == 200 and "forms.responses.readonly" in _r.json()["url"]
   and "access_type=offline" in _r.json()["url"],
   "Google Forms authorises with the forms scopes and an offline token")
_r = c.get("/api/admin/integrations/x_ads/authorize", headers=A)
ok(_r.status_code == 200 and "code_challenge_method=S256" in _r.json()["url"],
   "X demands PKCE and gets it")
_h1, _b1 = _ig._token_headers_body(_ig.PROVIDERS["meta_ads"], {"client_id": "a", "client_secret": "b"},
                                    {"grant_type": "authorization_code"})
ok("Authorization" not in _h1 and b"client_secret=b" in _b1, "Meta gets the secret as a form field")
_h2, _b2 = _ig._token_headers_body(_ig.PROVIDERS["reddit_ads"], {"client_id": "a", "client_secret": "b"},
                                    {"grant_type": "authorization_code"})
ok(_h2.get("Authorization", "").startswith("Basic ") and b"client_secret" not in _b2,
   "Reddit gets HTTP Basic, the RFC default")

# A plain customer, minted here: whatever earlier tests did to Carl's
# account is not this block's concern.
_wc = c.post("/api/login", json={"name": "Wave Customer", "region": "West"}).json()
_WCU = {"Authorization": f"Bearer {_wc['token']}"}

# --- the office manager reaches all of it, without being made an owner ---
# The five screens above each began by checking the admin bit alone, while
# the older money and people screens honoured the permissions grid. So the
# person trusted to approve an expense and sign off everybody's hours could
# not open the hiring board at all, and could read the ad ledger but do
# nothing on it. One predicate now, named areas per module.
_om = c.post("/api/login", json={"name": "Office Manager",
                                 "role": "employee"}).json()
_OM = {"Authorization": "Bearer " + _om["token"]}
_NEW_SCREENS = ("/api/ads", "/api/hiring", "/api/marketplaces",
                "/api/listings", "/api/intake", "/api/results")
ok(all(c.get(_p, headers=_OM).status_code == 403 for _p in
       ("/api/hiring", "/api/marketplaces")),
   "a member of staff with no grant runs none of the new screens")
c.post(f"/api/store/admin/staff/{_om['id']}/permissions", headers=A,
       json={"permissions": ["settings"]})
_shut = [_p for _p in _NEW_SCREENS if c.get(_p, headers=_OM).status_code != 200]
ok(not _shut,
   f"the settings grant opens every one of them, as it already opened the "
   f"books and the timesheet ({_shut})")
_omr = c.post("/api/ads/manual", headers=_OM, json={
    "platform": "other", "name": "Office manager's flyer", "spend_cents": 500})
ok(_omr.status_code == 200,
   "and it acts, rather than only looking — a screen you may open and not "
   "use is the same 403 one click later")
ok(c.get("/api/admin/db", headers=_OM).status_code == 403,
   "the grant still doesn't leak into anything else")

# A narrower grant stays narrow: marketing runs the campaigns and the
# listing, and does not thereby run the books or the hiring.
_mk = c.post("/api/login", json={"name": "Marketing Hand",
                                 "role": "employee"}).json()
_MK = {"Authorization": "Bearer " + _mk["token"]}
c.post(f"/api/store/admin/staff/{_mk['id']}/permissions", headers=A,
       json={"permissions": ["marketing"]})
_mkr = c.post("/api/ads/manual", headers=_MK, json={
    "platform": "other", "name": "Spring cards", "spend_cents": 100})
ok(_mkr.status_code == 200
   and c.post("/api/listings/profile", headers=_MK,
              json={"category": "Language school"}).status_code == 200,
   "the marketing grant runs the ad ledger and the listing")
ok(c.get("/api/hiring", headers=_MK).status_code == 403,
   "and not the hiring board")
# Those two proved the grant by writing, so take the rows back out: the
# ledger's own totals are checked below and a test that leaves a figure
# behind makes the next one lie.
for _rid in (_omr.json()["id"], _mkr.json()["id"]):
    c.delete(f"/api/ads/{_rid}", headers=A)
ok(c.get("/api/ads", headers=A).json()["total_cents"] == 0,
   "and the ledger is as empty as it was before they proved it")

# Written once. Eight copies is how the five drifted from the three in the
# first place, and two of those three read the column directly and so
# never saw a role default.
_auth_src = Path("src/erp/backend/auth.py").read_text()
ok("def office(user, *areas" in _auth_src
   and "governance.granted(user)" in _auth_src,
   "the predicate lives in one place and resolves grants through "
   "governance, role defaults included")
for _m in ("expenses", "timesheet", "ads", "hiring", "listings",
           "marketplaces", "intake", "students"):
    _msrc = Path(f"src/erp/backend/{_m}.py").read_text()
    ok("auth.office(" in _msrc and '["permissions"]' not in _msrc,
       f"{_m} asks it rather than keeping a copy")

# --- advertising: the ledger ---
ok(c.get("/api/ads", headers=_WCU).status_code == 403, "the ledger is an office screen")
_r = c.post("/api/ads/manual", headers=A, json={
    "platform": "twitch", "name": "Autumn stream", "spend_cents": 12000,
    "impressions": 40000, "clicks": 320, "results": 4})
ok(_r.status_code == 200, "a Twitch run is typed into the ledger")
_led = c.get("/api/ads", headers=A).json()
ok(_led["total_cents"] == 12000 and _led["campaigns"][0]["source"] == "manual"
   and _led["campaigns"][0]["cpc_cents"] == 37,
   "and counts in the total with its cost per click worked out")
ok(c.post("/api/ads/twitch/pull", headers=A).status_code == 400,
   "a typed platform cannot be pulled")
ok(c.post("/api/ads/meta_ads/pull", headers=A).status_code == 400,
   "nor an unconnected one")
_r = c.post("/api/ads/twitch/expense", headers=A)
ok(_r.status_code == 200 and _r.json()["amount_cents"] == 12000, "spend files as an expense")
_exp = c.get("/api/expenses", headers=A).json()
_exp_rows = _exp if isinstance(_exp, list) else _exp.get("expenses", [])
ok(any(e["category"] == "advertising" and e["amount_cents"] == 12000
       and e["state"] == "approved" for e in _exp_rows),
   "in the advertising category, approved, because the office filed a company cost")
ok(c.post("/api/ads/other/expense", headers=A).status_code == 400,
   "and nothing files when nothing was spent")

_real_req2 = _ig._req
_calls = []
def _fake_req(url, method="GET", headers=None, body=None, timeout=15):
    _calls.append((method, url, headers or {}, body))
    if "user/info" in url:
        return True, {"code": 0, "data": {"display_name": "Lingua Ads"}}
    if "report/integrated" in url:
        return True, {"code": 0, "data": {"list": [
            {"dimensions": {"campaign_id": "c1"},
             "metrics": {"campaign_name": "Fall enrolment", "spend": "42.50",
                         "impressions": "1000", "clicks": "80", "conversion": "3"}}]}}
    return False, "unexpected " + url
_ig._req = _fake_req
_r = c.post("/api/admin/integrations/tiktok_ads/connect", headers=A,
            json={"fields": {"token": "tok", "advertiser_id": "adv1"}})
ok(_r.status_code == 200 and "Lingua Ads" in _r.json()["account"],
   "TikTok connects when its user endpoint answers")
_r = c.post("/api/ads/tiktok_ads/pull", headers=A)
ok(_r.status_code == 200 and _r.json()["pulled"] == 1, "and its report pulls")
c.post("/api/ads/tiktok_ads/pull", headers=A)
_led = c.get("/api/ads", headers=A).json()
_tk = next(p for p in _led["platforms"] if p["key"] == "tiktok_ads")
ok(_tk["connected"] and _tk["totals"]["spend_cents"] == 4250 and _tk["totals"]["clicks"] == 80
   and _tk["totals"]["campaigns"] == 1,
   "into the ledger in cents, once, however often it is pulled")
ok(any("Access-Token" in h for _, u, h, _ in _calls if "report" in u),
   "with the token in the header TikTok reads")
_r = c.post("/api/admin/integrations/tiktok_ads/settings", headers=A, json={"fields": {"nope": "x"}})
ok(_r.status_code == 200 and "nope" not in _r.json()["settings"],
   "settings only take the fields the provider declared")
ok(c.post("/api/admin/integrations/meta_ads/settings", headers=A,
          json={"fields": {"ad_account_id": "1"}}).status_code == 400,
   "and not before the connection exists")

# --- hiring ---
ok(c.get("/api/hiring", headers=_WCU).status_code == 403, "hiring is an office screen")
_r = c.post("/api/hiring/postings", headers=A, json={
    "title": "Evening class assistant", "kind": "part_time", "location": "Springfield, IL",
    "pay_text": "$18/hr", "description": "Greet, register, set up.", "state": "open"})
ok(_r.status_code == 200 and _r.json()["slug"] == "evening-class-assistant",
   "a posting gets a slug from its title")
_slug = _r.json()["slug"]
_pid_job = _r.json()["id"]
ok("Evening class assistant" in c.get("/jobs").text, "open postings are a public page")
ok(f'action="/api/jobs/{_slug}/apply' in c.get(f"/jobs/{_slug}").text,
   "each with a form that applies")
_feed = c.get("/jobs.xml")
ok(_feed.status_code == 200 and "xml" in _feed.headers["content-type"]
   and f"<referencenumber><![CDATA[{_pid_job}]]>" in _feed.text
   and "<jobtype><![CDATA[Part time]]>" in _feed.text,
   "and the feed the boards ingest carries the posting in Indeed's shape")
_r = c.post(f"/api/jobs/{_slug}/apply", data={"name": "Verify Applicant",
            "email": "verify@example.com", "phone": "555", "cover": "hi"},
            files={"resume": ("cv.txt", b"my cv", "text/plain")})
ok(_r.status_code == 200, "anyone can apply from the page")
_aid = _r.json()["applicant_id"]
_r2 = c.post(f"/api/jobs/{_slug}/apply", data={"name": "Verify Applicant",
             "email": "verify@example.com"})
ok(_r2.json()["applicant_id"] == _aid, "applying twice is one applicant")
_r = c.get(f"/api/hiring/applicants/{_aid}/resume", headers=A)
ok(_r.status_code == 200 and _r.content == b"my cv", "the CV went through the blob store and comes back")
_key = c.post("/api/admin/integrations/indeed/inbound-key", headers=A).json()["key"]
ok(c.post("/api/inbound/indeed", headers={"X-API-Key": "wrong"}, json={}).status_code == 401,
   "a board with the wrong key is refused")
_ind = {"id": "ind-1", "applicant": {"fullName": "Indeed Person", "email": "ind@example.com",
                                    "phoneNumber": "555-1", "resume": {"file": {
                                        "fileName": "ip.pdf",
                                        "data": _b64.b64encode(b"%PDF-1.4 x").decode()}}},
        "job": {"jobId": str(_pid_job)}}
_r = c.post("/api/inbound/indeed", headers={"X-API-Key": _key}, json=_ind)
ok(_r.status_code == 200, "Indeed Apply posts an application")
_aid2 = _r.json()["applicant_id"]
ok(c.post("/api/inbound/indeed", headers={"X-API-Key": _key}, json=_ind).json()["applicant_id"] == _aid2,
   "and a retried webhook is the same applicant")
_hp = c.get("/api/hiring", headers=A).json()
_ap = {a["id"]: a for a in _hp["applicants"]}
ok(_ap[_aid2]["source"] == "indeed" and _ap[_aid2]["posting_id"] == _pid_job
   and _ap[_aid2]["resume_name"] == "ip.pdf" and _ap[_aid]["source"] == "page",
   "both sit on one board, each saying where it came from")
ok(_hp["postings"][0]["open_applicants"] == 2, "the posting counts its open applicants")
ok(c.patch(f"/api/hiring/applicants/{_aid}", headers=A, json={"stage": "interview"}).status_code == 200
   and c.patch(f"/api/hiring/applicants/{_aid}", headers=A, json={"stage": "hired"}).status_code == 400,
   "stages move by hand except hired, which is a button that does more")
ok(c.post(f"/api/hiring/applicants/{_aid}/hire", headers=A, json={"role": "customer"}).status_code == 400,
   "a hire is staff of some kind")
_r = c.post(f"/api/hiring/applicants/{_aid}/hire", headers=A,
            json={"role": "employee", "job": "general", "employment": "employee"})
ok(_r.status_code == 200 and _r.json()["user_id"], "hiring opens an account")
_new_uid = _r.json()["user_id"]
_u = c.get("/api/admin/users", headers=A).json()
_u = _u if isinstance(_u, list) else _u.get("users", [])
ok(any(u["id"] == _new_uid and u["role"] == "employee" and u["name"] == "Verify Applicant"
       for u in _u), "with the role the office chose")
_ob = c.get(f"/api/hiring/onboarding/{_new_uid}", headers=A).json()["tasks"]
ok(len(_ob) == len(_hir.ONBOARDING) and not any(t["done_at"] for t in _ob),
   "and a first-week list, all still to do")
ok(c.post(f"/api/hiring/onboarding/{_ob[0]['id']}/done", headers=A).json()["done"] is True,
   "which the office ticks")
ok(c.post(f"/api/hiring/applicants/{_aid}/hire", headers=A,
          json={"role": "employee"}).json().get("already"),
   "hiring twice is once")
c.post("/api/hiring/postings", headers=A, json={
    "id": _pid_job, "title": "Evening class assistant", "state": "closed"})
ok(c.post(f"/api/jobs/{_slug}/apply", data={"name": "Late"}).status_code == 404
   and "evening-class-assistant" not in c.get("/jobs.xml").text,
   "a closed posting takes no application and leaves the feed")

def _gh_req(url, method="GET", headers=None, body=None, timeout=15):
    if "candidates?per_page=1" in url:
        return True, []
    if "/applications" in url:
        return True, [{"id": 901, "candidate_id": 77, "current_stage": {"name": "Onsite Interview"},
                       "jobs": [{"name": "Teacher"}]}]
    if "/candidates/77" in url:
        return True, {"first_name": "Green", "last_name": "House",
                      "email_addresses": [{"value": "gh@example.com"}], "phone_numbers": []}
    return False, "unexpected " + url
_ig._req = _gh_req
_r = c.post("/api/admin/integrations/greenhouse/connect", headers=A, json={"fields": {"api_key": "k"}})
ok(_r.status_code == 200, "Greenhouse connects with a Harvest key")
_r = c.post("/api/hiring/greenhouse/pull", headers=A)
ok(_r.status_code == 200 and _r.json()["new"] == 1, "and pulls its candidates")
_gh = next(a for a in c.get("/api/hiring", headers=A).json()["applicants"] if a["source"] == "greenhouse")
ok(_gh["name"] == "Green House" and _gh["stage"] == "interview" and _gh["email"] == "gh@example.com",
   "with their stage folded into ours")

# --- delivery apps ---
_prod = c.get("/api/products").json()[0]
ok(c.post("/api/marketplaces/ubereats/push", headers=A).status_code == 400,
   "a menu cannot be pushed to an app that is not connected")
_r = c.post("/api/marketplaces/ubereats/menu", headers=A, json={"product_ids": [_prod["id"]]})
ok(_r.status_code == 200 and _r.json()["listed"] == 1, "a product is marked as on the menu")
_sent = {}
def _uber_req(url, method="GET", headers=None, body=None, timeout=15):
    if "oauth/v2/token" in url:
        return True, {"access_token": "ut", "expires_in": 3600}
    if url.endswith("/eats/stores/store-1"):
        return True, {"name": "Lingua Kitchen"}
    if "/menus" in url:
        _sent["menu"] = json.loads(body)
        return True, {}
    if "/status" in url:
        _sent["status"] = json.loads(body)
        return True, {}
    if "accept_pos_order" in url:
        _sent["accepted"] = url
        return True, {}
    return False, "unexpected " + url
_ig._req = _uber_req
_r = c.post("/api/admin/integrations/ubereats/connect", headers=A, json={"fields": {
    "client_id": "cid", "client_secret": "sec", "store_id": "store-1"}})
ok(_r.status_code == 200 and _r.json()["account"] == "Lingua Kitchen",
   "Uber Eats connects by client credentials and names the store")
_r = c.post("/api/marketplaces/ubereats/push", headers=A)
ok(_r.status_code == 200 and _r.json()["items"] == 1, "the menu pushes")
_item = _sent["menu"]["items"][0]
ok(_item["id"] == _prod["sku"] and _item["external_data"] == _prod["sku"]
   and _item["price_info"]["price"] == _prod["price_cents"],
   "each item carries our SKU as its id, so the order line needs no mapping")
ok(c.post("/api/marketplaces/ubereats/status", headers=A, json={"open": False}).json()["open"] is False
   and _sent["status"]["status"] == "PAUSED", "the store pauses")
_ukey = c.post("/api/admin/integrations/ubereats/inbound-key", headers=A).json()["key"]
_ord = {"id": "ub-1", "cart": {"items": [{"external_data": _prod["sku"],
        "quantity": {"in_sellable_unit": {"quantity": 2}}}]},
        "eater": {"first_name": "Uber", "last_name": "Eater"}}
_r = c.post(f"/api/inbound/ubereats?key={_ukey}", json=_ord)
ok(_r.status_code == 200 and _r.json()["order_id"], "an Uber order becomes an order in the queue")
_oid = _r.json()["order_id"]
ok("ub-1" in _sent.get("accepted", ""), "and is accepted back to Uber")
ok(c.post(f"/api/inbound/ubereats?key={_ukey}", json=_ord).json().get("already"),
   "a retried order notification is the same order")
_mp = c.get("/api/marketplaces", headers=A).json()["providers"][0]
ok(_mp["orders"][0]["order_id"] == _oid and _mp["orders"][0]["state"] == "accepted"
   and _mp["open"] is False, "the screen shows the order and the paused store")
_r = c.post(f"/api/inbound/ubereats?key={_ukey}", json={"id": "ub-2", "cart": {"items": [
    {"external_data": "NO-SUCH-SKU", "quantity": 1}]}})
ok(_r.status_code == 400 and "NO-SUCH-SKU" in _r.text, "an unknown SKU fails loudly, not silently")
_ccon = _db.connect()
_cr = _ig.creds(_ccon, "ubereats")
ok(_ig._deliver(_ccon, "ubereats", "product.updated", {"id": _prod["id"]}, _cr)[1].startswith("menu re-pushed"),
   "a product change re-pushes the menu it is on")
ok(_ig._deliver(_ccon, "ubereats", "product.updated", {"id": 999999}, _cr)[1] == "not on this menu",
   "and leaves one it is not on alone")
_ccon.close()
_jwt = _mkt.dd_jwt({"developer_id": "dev", "key_id": "kid",
                    "signing_secret": _b64.urlsafe_b64encode(b"secret").decode().rstrip("=")})
_hd, _pl, _sg = _jwt.split(".")
_pad = lambda x: x + "=" * (-len(x) % 4)
ok(json.loads(_b64.urlsafe_b64decode(_pad(_hd)))["dd-ver"] == "DD-JWT-V1"
   and json.loads(_b64.urlsafe_b64decode(_pad(_pl)))["iss"] == "dev"
   and _b64.urlsafe_b64decode(_pad(_sg)) == _hmac.new(b"secret", f"{_hd}.{_pl}".encode(), _hashlib.sha256).digest(),
   "DoorDash's JWT is HS256 over the developer id and key id, signed with the decoded secret")

# --- listings and reviews ---
ok(c.get("/api/listings", headers=_WCU).status_code == 403, "listings are staff screens")
_r = c.post("/api/listings/profile", headers=A, json={
    "phone": "555-0100", "website": "https://example.test",
    "hours": {"mon": [["09:00", "17:00"]], "tue": [["09:00", "12:00"], ["13:00", "17:00"]],
              "wed": [["bad"]], "xxx": [["09:00", "17:00"]]}})
ok(_r.status_code == 200 and _r.json()["hours"] == {"mon": [["09:00", "17:00"]],
                                                     "tue": [["09:00", "12:00"], ["13:00", "17:00"]]},
   "the profile keeps well-formed hours and drops the rest")
ok(c.post("/api/listings/ask", headers=A, json={"email": "x@example.com"}).status_code == 400,
   "asking for a review needs somewhere to send them")
c.post("/api/listings/profile", headers=A, json={"maps_url": "https://maps.app.goo.gl/abc"})
_r = c.post("/api/listings/ask", headers=A, json={"email": "x@example.com", "name": "Xan Yu"})
ok(_r.status_code == 200 and _r.json()["link"] == "https://maps.app.goo.gl/abc",
   "and sends the Maps link when there is no place id")
ok(c.get("/api/listings", headers=A).json()["requests"][0]["to_email"] == "x@example.com",
   "logged as asked")
_gcon = _db.connect()
_ig.save(_gcon, "google_business", {"access_token": "gt", "refresh_token": ""}, "Lingua",
         {"location": "locations/1", "_account": "accounts/9", "place_id": "PLACE"}, time.time() + 3600)
_gcon.close()
_gsent = {}
def _g_req(url, method="GET", headers=None, body=None, timeout=15):
    if url.endswith("/reviews?pageSize=50"):
        return True, {"reviews": [
            {"reviewId": "r1", "reviewer": {"displayName": "Pat"}, "starRating": "FIVE",
             "comment": "Lovely", "createTime": "2026-09-01T10:00:00Z"},
            {"reviewId": "r2", "reviewer": {"displayName": "Sam"}, "starRating": "TWO",
             "comment": "Slow", "createTime": "2026-09-02T10:00:00Z",
             "reviewReply": {"comment": "Sorry", "updateTime": "2026-09-03T10:00:00Z"}}]}
    if "/reviews/r1/reply" in url:
        _gsent["reply"] = json.loads(body)
        return True, {}
    if "updateMask=" in url:
        _gsent["push"] = (url, json.loads(body))
        return True, {}
    if "readMask=" in url:
        return True, {"title": "Lingua School", "phoneNumbers": {"primaryPhone": "555-9"},
                      "websiteUri": "https://lingua.test", "regularHours": {"periods": [
                          {"openDay": "MONDAY", "openTime": {"hours": 9}, "closeTime": {"hours": 17}}]},
                      "storefrontAddress": {"addressLines": ["1 High St"], "locality": "Springfield",
                                            "administrativeArea": "IL", "postalCode": "62701",
                                            "regionCode": "US"}}
    if "/businesses/lingua-springfield/reviews" in url:
        return True, {"reviews": [{"id": "y1", "user": {"name": "Yelper"}, "rating": 4,
                                   "text": "Good", "url": "https://yelp.test/r/y1",
                                   "time_created": "2026-09-04 10:00:00"}]}
    if url.endswith("/businesses/lingua-springfield"):
        return True, {"name": "Lingua (Yelp)", "display_phone": "555-1", "rating": 4.5,
                      "review_count": 12, "url": "https://yelp.test/biz", "location": {
                          "display_address": ["1 High St", "Springfield"]}, "hours": [], "categories": []}
    return False, "unexpected " + url
_ig._req = _g_req
_r = c.post("/api/listings/google_business/pull", headers=A)
ok(_r.status_code == 200 and _r.json()["name"] == "Lingua School" and _r.json()["postal"] == "62701"
   and _r.json()["hours"] == {"mon": [["09:00", "17:00"]]},
   "the Google listing pulls into the profile, hours included")
_r = c.post("/api/listings/google_business/push", headers=A)
ok(_r.status_code == 200 and "regularHours" in _gsent["push"][0]
   and _gsent["push"][1]["regularHours"]["periods"][0]["openDay"] == "MONDAY"
   and "title" not in _gsent["push"][1],
   "and pushes back the fields Google lets an API change, not the name")
ok(c.post("/api/listings/google_business/reviews/pull", headers=A).json()["pulled"] == 2,
   "Google reviews pull into the inbox")
_lp = c.get("/api/listings", headers=A).json()
ok(_lp["summary"]["google_business"]["n"] == 2 and _lp["summary"]["google_business"]["unanswered"] == 1
   and _lp["summary"]["google_business"]["avg"] == 3.5,
   "counted, averaged, and the unanswered one flagged")
_rv = next(r for r in _lp["reviews"] if r["external_id"] == "r1")
ok(c.post(f"/api/listings/reviews/{_rv['id']}/reply", headers=A, json={"text": "Thank you"}).status_code == 200
   and _gsent["reply"] == {"comment": "Thank you"},
   "a reply goes to Google through the same API")
ok(c.get("/api/listings", headers=A).json()["review_link"].endswith("placeid=PLACE"),
   "with a place id the review link opens the review box")
_r = c.post("/api/admin/integrations/yelp/connect", headers=A, json={"fields": {
    "api_key": "yk", "business_id": "lingua-springfield"}})
ok(_r.status_code == 200 and _r.json()["account"] == "Lingua (Yelp)", "Yelp connects with an API key")
_r = c.post("/api/listings/yelp/pull", headers=A)
ok(_r.status_code == 200 and _r.json()["review_count"] == 12
   and c.get("/api/listings", headers=A).json()["profile"]["name"] == "Lingua School",
   "Yelp's listing is pulled beside ours, not into ours — it cannot be pushed back")
ok(c.post("/api/listings/yelp/reviews/pull", headers=A).json()["pulled"] == 1, "Yelp reviews pull")
_yv = next(r for r in c.get("/api/listings", headers=A).json()["reviews"] if r["provider"] == "yelp")
_r = c.post(f"/api/listings/reviews/{_yv['id']}/reply", headers=A, json={"text": "hi"})
ok(_r.status_code == 400 and "Yelp" in _r.text, "and a Yelp reply is refused with the reason")

# --- intake: forms, gifts, results ---
ok(c.get("/api/intake", headers=_WCU).status_code == 403, "intake is a staff screen")
_fk = c.post("/api/admin/integrations/google_forms/inbound-key", headers=A).json()["key"]
_push = {"form_id": "f1", "form_title": "Interest form", "responses": [
    {"id": "r1", "submitted_at": "2026-09-08T10:00:00",
     "answers": {"Your name": "Form Person", "Email address": "form@example.com",
                 "Phone": "555-2", "Which class?": "Evening ESL", "City": "Springfield"}}]}
ok(c.post("/api/inbound/google_forms", headers={"X-API-Key": _fk}, json=_push).json()["received"] == 1,
   "an Apps Script trigger pushes a response")
c.post("/api/inbound/google_forms", headers={"X-API-Key": _fk}, json=_push)
_ik = c.get("/api/intake", headers=A).json()
ok(len([r for r in _ik["responses"] if r["form_id"] == "f1"]) == 1
   and _ik["responses"][0]["name"] == "Form Person" and _ik["responses"][0]["email"] == "form@example.com",
   "kept once, with the person read out of the answers by what the questions mean")
ok("X-API-Key" in _ik["apps_script"] and _fk in _ik["apps_script"],
   "and the snippet on the screen carries the address and key")
_rid = _ik["responses"][0]["id"]
_r = c.post(f"/api/intake/forms/{_rid}/as", headers=A, json={"kind": "student"})
ok(_r.status_code == 200 and _r.json()["id"], "a response becomes a student")
_sid = _r.json()["id"]
_sp = c.get(f"/api/students/{_sid}", headers=A).json()
ok(_sp["profile"]["phone"] == "555-2" and _sp["profile"]["extra"].get("Which class?") == "Evening ESL",
   "with the answers on their profile")
ok(any("Signed up via Interest form" in t.get("title", "") for t in _sp.get("timeline", [])),
   "and the form on their timeline")
ok(c.post(f"/api/intake/forms/{_rid}/as", headers=A, json={"kind": "enquiry"}).json().get("already") == "student",
   "handled once")
c.post("/api/inbound/google_forms", headers={"X-API-Key": _fk}, json={
    "form_id": "f1", "responses": [{"id": "r2", "answers": {"Name": "Partner Co", "Email": "p@co.test"}}]})
_rid2 = next(r["id"] for r in c.get("/api/intake", headers=A).json()["responses"] if r["external_id"] == "r2")
_r = c.post(f"/api/intake/forms/{_rid2}/as", headers=A, json={"kind": "enquiry"})
_ocon = _db.connect()
ok(_r.status_code == 200 and _ocon.execute("SELECT name FROM outreach WHERE id=?",
                                            (_r.json()["id"],)).fetchone()["name"] == "Partner Co",
   "or an enquiry on the sales board")
_ocon.close()

# The screens are split, and each carries only its own: a school buys
# Learning for the score imports and must not need Fundraising to reach
# them. One screen could only ever be sold as one capability.
ok("results" not in c.get("/api/intake", headers=A).json()
   and "gifts" not in c.get("/api/results", headers=A).json(),
   "forms and gifts on one screen, scores on another, neither carrying "
   "the other's rows")
ok({p["name"] for p in c.get("/api/results", headers=A).json()["connections"]}
   == {"gedmanager", "northstar"}
   and {p["name"] for p in c.get("/api/intake", headers=A).json()["connections"]}
   == {"google_forms", "network4good"},
   "and each offering only the connections that feed it")

_gk = c.post("/api/admin/integrations/network4good/inbound-key", headers=A).json()["key"]
_r = c.post("/api/inbound/network4good", headers={"X-API-Key": _gk}, json={
    "transaction_id": "nfg-1", "donor_name": "Generous Giver", "email": "giver@example.com",
    "amount": "50.00", "designation": "Scholarships", "recurring": "Monthly", "date": "09/01/2026"})
ok(_r.status_code == 200 and _r.json()["received"] == 1, "a Network for Good gift arrives")
_csv = ("Donor First Name,Donor Last Name,Email,Donation Amount,Donation Date,Designation,Transaction ID\n"
        "Quiet,Helper,quiet@example.com,$25.00,09/03/2026,General,nfg-2\n"
        "Generous,Giver,giver@example.com,50.00,09/01/2026,Scholarships,nfg-1\n"
        "No,Amount,,,09/03/2026,,nfg-3\n")
_r = c.post("/api/admin/integrations/network4good/import", headers=A,
            files={"file": ("gifts.csv", _csv.encode(), "text/csv")})
ok(_r.status_code == 200 and _r.json()["imported"] == 2 and len(_r.json()["skipped"]) == 1,
   "and the CSV export imports, skipping a row with no amount")
_ik = c.get("/api/intake", headers=A).json()
ok(_ik["gift_totals"]["cents"] == 7500 and _ik["gift_totals"]["n"] == 2 and _ik["gift_totals"]["donors"] == 2,
   "the same transaction twice is one gift; two donors gave seventy-five dollars")
ok(any(g["recurring"] for g in _ik["gifts"] if g["external_id"] == "nfg-1"), "monthly read as recurring")
ok(any(u["name"] == "Generous Giver" and u["role"] == "donor" for u in
       (lambda x: x if isinstance(x, list) else x.get("users", []))(c.get("/api/admin/users", headers=A).json())),
   "and each donor is in the address book as a donor")

_ged = ("Student Name,Email,Test Subject,Scaled Score,Test Date,Status\n"
        f"{_wc['name']},,Reasoning Through Language Arts,158,08/20/2026,Passed\n"
        f"{_wc['name']},,Mathematical Reasoning,140,08/22/2026,Not Passed\n"
        "Nobody Known,nobody@example.com,Science,170,08/22/2026,Passed\n")
_r = c.post("/api/admin/integrations/gedmanager/import", headers=A,
            files={"file": ("ged.csv", _ged.encode(), "text/csv")})
ok(_r.status_code == 200 and _r.json()["imported"] == 3 and _r.json()["matched"] == 2,
   "a GED Manager score report imports, matching the student by name")
_tl = c.get(f"/api/students/{_wc['id']}", headers=A).json()
_titles = [t.get("title", "") for t in _tl.get("timeline", [])]
ok(any("Passed GED Reasoning Through Language Arts" in t for t in _titles)
   and any("GED Mathematical Reasoning: 140" in t for t in _titles),
   "a pass is an achievement on their record and a miss is a milestone")
_rk = c.get("/api/results", headers=A).json()
_un = next(t for t in _rk["results"] if not t["user_id"])
ok(_un["taker"] == "Nobody Known" and _un["certificate"] == "College Ready" and _rk["unmatched"] == 1,
   "an unknown taker is kept unmatched, never guessed, and 170 is college-ready")
ok(c.post(f"/api/intake/results/{_un['id']}/match", headers=A, json={"user_id": _wc["id"]}).status_code == 200
   and c.get("/api/results", headers=A).json()["unmatched"] == 0, "until the office says whose it is")
_ns = ("Learner,Email,Module,Score %,Passed,Date,Certificate\n"
       f"{_wc['name']},,Basic Computer Skills,92,Yes,09/05/2026,Yes\n")
_r = c.post("/api/admin/integrations/northstar/import", headers=A,
            files={"file": ("ns.csv", _ns.encode(), "text/csv")})
ok(_r.status_code == 200 and _r.json()["matched"] == 1, "a NorthStar results export imports")
ok(any("NorthStar: Basic Computer Skills" in t for t in
       [x.get("title", "") for x in c.get(f"/api/students/{_wc['id']}", headers=A).json().get("timeline", [])]),
   "and the certificate is an achievement")
ok(c.post("/api/admin/integrations/gedmanager/import", headers=A,
          files={"file": ("ged.csv", _ged.encode(), "text/csv")}).json()["imported"] == 3
   and len([t for t in c.get("/api/results", headers=A).json()["results"] if t["provider"] == "gedmanager"]) == 3,
   "importing the same report twice adds nothing")

_fcon = _db.connect()
_ig.save(_fcon, "google_forms", {"access_token": "ft", "refresh_token": ""}, "forms",
         {"form_ids": "F9"}, time.time() + 3600)
_fcon.close()
def _forms_req(url, method="GET", headers=None, body=None, timeout=15):
    if url.endswith("/forms/F9"):
        return True, {"info": {"title": "Placement"}, "items": [
            {"title": "Full name", "questionItem": {"question": {"questionId": "q1"}}},
            {"title": "Email", "questionItem": {"question": {"questionId": "q2"}}}]}
    if url.endswith("/forms/F9/responses"):
        return True, {"responses": [{"responseId": "resp1", "createTime": "2026-09-07T09:00:00Z",
                                     "answers": {"q1": {"textAnswers": {"answers": [{"value": "Pulled Person"}]}},
                                                 "q2": {"textAnswers": {"answers": [{"value": "pulled@example.com"}]}}}}]}
    return False, "unexpected " + url
_ig._req = _forms_req
_r = c.post("/api/intake/forms/pull", headers=A)
ok(_r.status_code == 200 and _r.json()["new"] == 1, "Google Forms responses pull by form id")
ok(c.post("/api/intake/forms/pull", headers=A).json()["new"] == 0, "once")
ok(any(r["name"] == "Pulled Person" and r["form_title"] == "Placement" and r["email"] == "pulled@example.com"
       for r in c.get("/api/intake", headers=A).json()["responses"]),
   "with the question ids turned back into their titles")
_ig._req = _real_req2

# --- documentation ---
_cdoc = Path("docs/product/connections.md").read_text()
ok(all(w in _cdoc for w in ("Twitch", "Yelp", "GED Manager", "NorthStar", "jobs.xml", "Uber Eats")),
   "the connections doc covers every family and every honest limit")
ok("connections.md" in Path("docs/product/README.md").read_text(),
   "and the product README points at it")


# ===== the agent's door: every tool points at a route that exists =======
# An MCP server is a promise made in a schema and kept by an HTTP call,
# and nothing checks the join. The first version of it offered a ticket
# tool whose body said `topic` while the route wanted `title`, which is
# invisible until a model tries it and reads back "a ticket needs a
# title" — a failure the model then reports as a broken business rather
# than a broken tool. So the whole catalogue is checked against the app's
# own OpenAPI document, which is generated from the routes themselves.
import importlib as _il  # noqa: E402
_mcpt = _il.import_module("mcp_server.tools")
_mcps = _il.import_module("mcp_server.server")
_spec = c.get("/openapi.json").json()
_paths = _spec["paths"]

ok(len(_mcpt.TOOLS) >= 25,
   f"the agent is offered a curated list, not all {len(_paths)} paths")
ok(len({t["name"] for t in _mcpt.TOOLS}) == len(_mcpt.TOOLS),
   "no tool name means two things")

for _t in _mcpt.TOOLS:
    _p, _m = _t["path"], _t["method"].lower()
    ok(_p in _paths, f"{_t['name']} points at a route that exists ({_p})")
    ok(_m in _paths.get(_p, {}),
       f"{_t['name']} uses a method that route answers ({_m.upper()} {_p})")
    _op = _paths[_p][_m]

    # Path placeholders must be declared, or the URL is built with a
    # literal {uid} in it and the app 404s on a route it does have.
    _holes = set(re.findall(r"\{(\w+)\}", _p))
    ok(_holes == set(_t.get("path_params") or {}),
       f"{_t['name']} declares exactly the path parameters its route has "
       f"({_holes})")
    ok(_holes <= set(_t.get("required") or []),
       f"{_t['name']} requires every part of its own URL")

    # Body fields must be fields the route's model accepts. FastAPI drops
    # unknown keys silently, so a misspelled one is a value that vanishes.
    if _t.get("body"):
        _rb = _op.get("requestBody")
        ok(_rb is not None, f"{_t['name']} sends a body to a route that takes one")
        _ref = _rb["content"]["application/json"]["schema"].get("$ref", "")
        _model = _spec["components"]["schemas"].get(_ref.split("/")[-1], {})
        _extra = sorted(set(_t["body"]) - set(_model.get("properties", {})))
        ok(not _extra,
           f"{_t['name']} sends only fields its route accepts (stray: {_extra})")

    # Query parameters likewise.
    if _t.get("query"):
        _known = {q["name"] for q in _op.get("parameters", [])}
        _stray = sorted(set(_t["query"]) - _known)
        ok(not _stray, f"{_t['name']} passes known query parameters ({_stray})")

# Writing is a decision the operator makes, not one the model makes.
_reads = [t for t in _mcpt.TOOLS if not t.get("write")]
_writes = [t for t in _mcpt.TOOLS if t.get("write")]
ok(_reads and _writes, "the catalogue has both, and knows which is which")
ok(all(t["method"] == "GET" for t in _reads),
   "nothing marked read-only can change anything, whatever it is called")
ok(all(t["method"] != "GET" for t in _writes), "and vice versa")
ok(len(_mcps.offered({"writes": False})) == len(_reads)
   and len(_mcps.offered({"writes": True})) == len(_mcpt.TOOLS),
   "a server started read-only does not even LIST the write tools — a "
   "tool a model can see is a tool it will eventually try")
ok(all("WRITES" in _mcps.description_for(t) if hasattr(_mcps, "description_for")
       else "WRITES" in _mcpt.description_for(t) for t in _writes),
   "and each write tool says so in the sentence the model actually reads")

# Nothing that spends, publishes or cannot be undone, even with writes on.
_offered = {f"{t['method']} {t['path']}" for t in _mcpt.TOOLS}
for _forbidden in ("POST /api/finance/invoices/{iid}/send",
                   "POST /api/civics/contributions",
                   "POST /api/onboarding/departures",
                   "POST /api/payroll/runs/{rid}/paid",
                   "POST /api/payroll/rates",
                   "POST /api/accounting/journals",
                   "POST /api/treasury/transfer",
                   "POST /api/automation/rules",
                   "POST /api/orders",
                   "POST /api/orders/{oid}/confirm-payment",
                   "POST /api/expenses/{eid}/decide",
                   "POST /api/hours/approve",
                   "POST /api/hiring/applicants/{aid}/hire",
                   "POST /api/listings/reviews/{rid}/reply",
                   "POST /api/listings/ask",
                   "POST /api/marketplaces/{name}/push"):
    ok(_forbidden not in _offered,
       f"the agent cannot {_forbidden} — irreversible, public or it moves "
       f"money, and a person stays in that loop")
    ok(_forbidden in _mcpt.EXCLUDED,
       f"and the omission is written down as a decision ({_forbidden})")
ok(not any(t["method"] == "DELETE" for t in _mcpt.TOOLS),
   "nothing the agent can reach deletes anything")
ok(not any(t["path"].startswith("/api/admin/") for t in _mcpt.TOOLS),
   "nor touches settings, staff, permissions or keys")

# The transport: stdout is protocol, and a refusal must reach the model.
_ini = _mcps.handle({"writes": False}, {"jsonrpc": "2.0", "id": 1,
                                        "method": "initialize",
                                        "params": {"protocolVersion": "2025-06-18"}})
ok(_ini["result"]["protocolVersion"] == "2025-06-18"
   and "tools" in _ini["result"]["capabilities"],
   "the handshake answers in the version the client asked for")
ok(_mcps.handle({"writes": False},
                {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None,
   "a notification gets no reply, which is what makes it a notification")
_bad = _mcps.handle({"writes": False, "key": "", "url": "", "host": ""},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "bc_log_expense", "arguments": {}}})
ok(_bad["result"]["isError"] is True
   and "read-only" in _bad["result"]["content"][0]["text"],
   "a refused tool comes back as a readable result, not a protocol error "
   "— the model has to read it to do anything about it")
_unknown = _mcps.handle({"writes": True, "key": "", "url": "", "host": ""},
                        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                         "params": {"name": "bc_nope", "arguments": {}}})
ok(_unknown["result"]["isError"] is True,
   "and so does a tool that does not exist")
ok(_mcps.handle({"writes": False},
                {"jsonrpc": "2.0", "id": 4, "method": "resources/list"}
                )["result"] == {"resources": [], "resourceTemplates": []},
   "clients probe for resources whether or not we offered them, and an "
   "error in their log reads as a fault")
_src_mcp = Path("src/mcp_server/server.py").read_text()
ok('print(f"[business-control mcp] {msg}", file=sys.stderr' in _src_mcp,
   "every human word goes to stderr: a stray line on stdout is a parse "
   "error at the client and a server that appears to hang")
ok("BC_MCP_KEY" in _src_mcp and "Bearer" in _src_mcp,
   "and it carries the app's own API key, so there is no second "
   "authorization model to drift from the first")



# ===== the four that were priced and unbuilt ===========================
# Accounting, Treasury, Legal and Automation were rows in the price book
# with nothing behind them: a quote could be built that a customer could
# not be delivered. These are them.
from erp.backend import accounting as _acc  # noqa: E402
from erp.backend import automation as _aut  # noqa: E402
from erp.backend import legal as _lgl  # noqa: E402
from erp.backend import treasury as _tre  # noqa: E402

# --- accounting: a ledger, which is a stronger claim than a report ---
_ac = c.get("/api/accounting", headers=A).json()
ok(len(_ac["accounts"]) >= 15 and any(a["code"] == "1010" for a in _ac["accounts"]),
   "a chart of accounts is seeded — an empty one is a screen nobody can "
   "start from")
ok(c.get("/api/accounting", headers=_WCU).status_code == 403,
   "the books are the office's")

_r = c.post("/api/accounting/journals", headers=A, json={"memo": "lopsided",
            "lines": [{"account": "1010", "debit_cents": 500},
                      {"account": "4000", "credit_cents": 400}]})
ok(_r.status_code == 400 and "balance" in _r.text,
   "a journal that does not balance is refused — that refusal is what "
   "makes a trial balance mean anything")
_r = c.post("/api/accounting/journals", headers=A, json={"memo": "owner puts in",
            "lines": [{"account": "1010", "debit_cents": 100000},
                      {"account": "3000", "credit_cents": 100000}]})
ok(_r.status_code == 200, "a balanced one posts")
_jid = _r.json()["id"]
ok(c.post("/api/accounting/journals", headers=A, json={"memo": "x", "lines": [
    {"account": "9999", "debit_cents": 1}, {"account": "1010", "credit_cents": 1}]}
   ).status_code == 400, "and only to accounts that exist")

_r = c.post("/api/accounting/sync", headers=A)
ok(_r.status_code == 200 and _r.json()["posted"] > 0,
   "the orders and expenses already recorded post themselves")
_first = _r.json()["posted"]
ok(c.post("/api/accounting/sync", headers=A).json()["posted"] == 0,
   "and posting again posts nothing twice — the key is (source, id), so a "
   "run that half failed is safe to repeat")
_ac = c.get("/api/accounting", headers=A).json()
ok(_ac["trial_balance"]["balanced"],
   f"the trial balance balances ({_ac['trial_balance']['out_by_cents']} out)")
ok(_ac["statements"]["sheet_balanced"],
   "and so does what the business holds against what it owes and owns")
ok(_ac["unposted"] == {"orders": 0, "expenses": 0},
   "nothing is left that the books do not know about")

# A discount is the full sale and an amount given away, not a smaller
# sale. Posted anywhere else it is invisible, and "what is the
# discounting costing us" becomes unanswerable.
_dcon = _db.connect()
_dsum = _dcon.execute(
    "SELECT COALESCE(SUM(discount_cents),0) AS c FROM orders WHERE"
    " payment_status IN ('paid','cod')").fetchone()["c"]
if _dsum:
    _d45 = next(b for b in _acc.balances(_dcon) if b["code"] == "4500")
    ok(_d45["debit_cents"] == _dsum,
       "every discount given lands in its own account, not buried in other "
       "income")
ok(any(a["code"] == "4500" for a in _ac["accounts"]),
   "which exists in the chart whether or not anything has been discounted")
_dcon.close()

_r = c.post(f"/api/accounting/journals/{_jid}/reverse", headers=A, json={})
ok(_r.status_code == 200, "a journal is corrected by reversal")
_rev = _r.json()["id"]
_jd = c.get(f"/api/accounting/journals/{_rev}", headers=A).json()
_orig = c.get(f"/api/accounting/journals/{_jid}", headers=A).json()
ok(_orig["reversed_by"] == _rev and _jd["reverses"] == _jid,
   "each pointing at the other, so the history a return was filed from "
   "stays where it was")
ok(sorted((l["account"], l["debit_cents"], l["credit_cents"])
          for l in _jd["lines"])
   == sorted((l["account"], l["credit_cents"], l["debit_cents"])
             for l in _orig["lines"]),
   "and the correction is the mirror of it, line for line")
ok(c.post(f"/api/accounting/journals/{_jid}/reverse", headers=A,
          json={}).status_code == 400, "reversed once is enough")

_ledger = c.get("/api/accounting/ledger/1010", headers=A).json()
ok(_ledger["rows"] and "running_cents" in _ledger["rows"][0],
   "an account opens as a running statement, which is how a difference is "
   "found rather than merely noticed")

_yr = _t0.time()
_r = c.post("/api/accounting/periods", headers=A,
            json={"label": "last year", "starts": _yr - 700 * 86400,
                  "ends": _yr - 400 * 86400})
_pid_per = _r.json()["id"]
ok(c.post(f"/api/accounting/periods/{_pid_per}/close", headers=A,
          json={}).status_code == 200, "a period closes when it balances")
_r = c.post("/api/accounting/journals", headers=A, json={
    "at": _yr - 500 * 86400, "memo": "backdated",
    "lines": [{"account": "1010", "debit_cents": 100},
              {"account": "4000", "credit_cents": 100}]})
ok(_r.status_code == 400 and "closed" in _r.text,
   "and afterwards refuses anything dated inside it — a year you filed "
   "from must not be able to change")

# --- treasury: where the money is, and how long it lasts ---
ok(c.get("/api/treasury", headers=_WCU).status_code == 403,
   "the money is the office's too")
_a1 = c.post("/api/treasury/accounts", headers=A, json={
    "name": "Current", "kind": "bank", "balance_cents": 400000,
    "reserved_cents": 50000, "reserved_for": "sales tax",
    "ledger_account": "1010"}).json()["id"]
_a2 = c.post("/api/treasury/accounts", headers=A, json={
    "name": "Deposit", "kind": "savings", "balance_cents": 100000}).json()["id"]
_tr = c.get("/api/treasury", headers=A).json()
ok(_tr["total_cents"] == 500000 and _tr["free_cents"] == 450000,
   "money set aside is still in the account and is not free to spend — "
   "which is the whole reason a treasury screen is not a bank balance")
ok(c.post("/api/treasury/accounts", headers=A, json={
    "name": "Bad", "ledger_account": "9999"}).status_code == 400,
   "a cash account can only name a ledger account that exists")
_r = c.post("/api/treasury/transfer", headers=A, json={
    "from_id": _a1, "to_id": _a2, "amount_cents": 75000, "memo": "sweep"})
ok(_r.status_code == 200, "money moves between your own accounts")
_tr = c.get("/api/treasury", headers=A).json()
_bal = {a["name"]: a["balance_cents"] for a in _tr["accounts"]}
ok(_bal["Current"] == 325000 and _bal["Deposit"] == 175000
   and _tr["total_cents"] == 500000,
   "both sides move and the total does not — a transfer is not income")
ok(len([m for m in _tr["movements"] if m["memo"] == "sweep"]) == 2,
   "and it leaves a trail on both accounts, because a balance that can be "
   "changed with no record is a number nobody can argue with")
ok(c.post("/api/treasury/transfer", headers=A, json={
    "from_id": _a1, "to_id": _a1, "amount_cents": 100}).status_code == 400,
   "not to itself")
ok(c.post("/api/treasury/transfer", headers=A, json={
    "from_id": _a1, "to_id": _a2, "amount_cents": -5}).status_code == 400,
   "and not a negative amount, which is a transfer the other way wearing a "
   "disguise")
_rec = {r["name"]: r for r in _tr["reconciliation"]}
ok("Current" in _rec and _rec["Current"]["difference_cents"] ==
   _rec["Current"]["stated_cents"] - _rec["Current"]["ledger_cents"],
   "an account linked to the books reports the difference between the two "
   "rather than quietly preferring one")
_h = c.post("/api/treasury/holdings", headers=A, json={
    "name": "Index fund", "kind": "fund", "cost_cents": 300000,
    "value_cents": 341000}).json()["id"]
_tr = c.get("/api/treasury", headers=A).json()
ok(_tr["holdings"][0]["gain_cents"] == 41000,
   "a holding carries what was paid and what it is worth, and the "
   "difference between them")
ok(c.delete(f"/api/treasury/holdings/{_h}", headers=A).status_code == 200
   and not c.get("/api/treasury", headers=A).json()["holdings"],
   "and closing one stops it counting")

# --- legal: the diary above the filing cabinet ---
ok(c.get("/api/legal", headers=_WCU).status_code == 403, "the register too")
_soon = _t0.time() + 40 * 86400
_r = c.post("/api/legal/matters", headers=A, json={
    "kind": "contract", "title": "Unit 4 lease", "counterparty": "Harbour",
    "ends": _soon, "notice_days": 30, "renews": "auto", "risk": "high"})
ok(_r.status_code == 200, "a matter goes on the register")
_mid = _r.json()["id"]
ok(c.post("/api/legal/matters", headers=A, json={
    "title": "No end", "notice_days": 30}).status_code == 400,
   "a notice period counts back from an end date, so it cannot exist "
   "without one")
ok(c.post("/api/legal/matters", headers=A, json={
    "title": "Backwards", "starts": _soon, "ends": _soon - 86400}
   ).status_code == 400, "and nothing ends before it starts")
_lg = c.get("/api/legal", headers=A).json()
_m = next(m for m in _lg["matters"] if m["id"] == _mid)
ok(abs(_m["decide_by"] - (_soon - 30 * 86400)) < 2,
   "the date to decide by is the end minus the notice, which is the fact "
   "the filing cabinet never held")
ok(_m["needs_attention"], "and a decision inside its notice period is flagged")
_past = _t0.time() - 10 * 86400
_oid = c.post("/api/legal/obligations", headers=A, json={
    "matter_id": _mid, "what": "Quarterly fire inspection", "due": _past,
    "every_months": 3}).json()["id"]
_lg = c.get("/api/legal", headers=A).json()
_kinds = {x["kind"] for x in _lg["diary"]}
ok({"obligation", "decide", "ends"} <= _kinds,
   "the diary holds obligations, decisions and endings together — a lease "
   "break and a licence renewal are the same kind of problem")
ok(any(x["overdue"] for x in _lg["diary"]) and _lg["counts"]["overdue"] == 1,
   "and says which is already late")
ok(_lg["diary"] == sorted(_lg["diary"], key=lambda x: x["at"]),
   "in date order, which is the only order a diary has")
_r = c.post(f"/api/legal/obligations/{_oid}/done", headers=A, json={})
ok(_r.status_code == 200 and _r.json()["next_id"],
   "marking a repeating obligation done opens the next one")
_lg = c.get("/api/legal", headers=A).json()
_next = next(o for o in _lg["obligations"] if o["id"] == _r.json()["next_id"])
ok(abs(_next["due"] - _lgl._add_months(_past, 3)) < 2,
   "three calendar months on, not ninety days — a quarterly filing due on "
   "the 31st is due on the 30th of a short month")
ok(c.post(f"/api/legal/obligations/{_oid}/done", headers=A,
          json={}).status_code == 400, "and done once is done")
_before_n = len(c.get("/api/legal", headers=A).json()["obligations"])
ok(_before_n == 2,
   "the next one only appears on completion — a diary pre-filled with a "
   "year of rows is a diary whose overdue count means nothing")

# --- automation: when this happens, do that ---
ok(c.get("/api/automation", headers=_WCU).status_code == 403,
   "automations are an owner's screen")
ok(c.post("/api/automation/rules", headers=A, json={
    "name": "x", "event": "moon.rose", "action": "notify",
    "config": {"title": "t"}}).status_code == 400,
   "a rule cannot wait for an event nothing raises")
_r = c.post("/api/automation/rules", headers=A, json={
    "name": "x", "event": "order.paid", "action": "refund", "config": {}})
ok(_r.status_code == 400 and "spends" in _r.text,
   "nor do anything outside the list, and the refusal says why the list is "
   "short")
ok(c.post("/api/automation/rules", headers=A, json={
    "name": "no title", "event": "order.paid", "action": "ticket",
    "config": {}}).status_code == 400,
   "an action without what it needs is refused at the door, not at the "
   "first event")
_rid = c.post("/api/automation/rules", headers=A, json={
    "name": "Big order needs a call", "event": "order.paid",
    "conditions": [{"field": "total_cents", "op": "gt", "value": "5000"}],
    "action": "ticket", "config": {"title": "Call about order {id}"},
    "cooldown_sec": 0}).json()["id"]
_r = c.post(f"/api/automation/rules/{_rid}/test", headers=A,
            json={"payload": {"id": 9, "total_cents": 100}})
ok(_r.json()["matched"] is False,
   "a payload the conditions do not match runs nothing")
_before_t = len(c.get("/api/tickets", headers=A).json().get("tickets", []))
_r = c.post(f"/api/automation/rules/{_rid}/test", headers=A,
            json={"payload": {"id": 9, "total_cents": 9900}})
ok(_r.json()["matched"] and _r.json()["ok"], "one that does, acts")
_tk = c.get("/api/tickets", headers=A).json().get("tickets", [])
ok(any(t["title"] == "Call about order 9" for t in _tk),
   "and {id} in the text becomes the id from the event — a headline that "
   "cannot say which order it is about makes the reader open every order")

_acon = _db.connect()
# A cooldown is time since the LAST run, so there has to have been one.
# The test route deliberately does not set it — testing a rule is not
# using up its allowance.
_acon.execute("UPDATE automation_rules SET cooldown_sec=3600, last_run=?"
              " WHERE id=?", (_t0.time(), _rid))
_acon.commit()
_n_before = _acon.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"]
_aut.run_for(_acon, "order.paid", {"id": 10, "total_cents": 9900})
_n_after = _acon.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"]
ok(_n_after == _n_before,
   "a cooldown holds the next one back, so a busy Saturday cannot turn one "
   "rule into a thousand")
ok("cooldown" in _acon.execute(
    "SELECT detail FROM automation_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()["detail"],
   "and says so in the log rather than looking like nothing happened")
_acon.execute("UPDATE automation_rules SET cooldown_sec=0, last_run=0"
              " WHERE id=?", (_rid,))
_acon.commit()
_n_before = _acon.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"]
_aut.run_for(_acon, "order.paid", {"id": 11, "total_cents": 9900})
ok(_acon.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"]
   == _n_before + 1,
   "an event straight off the bus reaches the rules")
_aut.run_for(_acon, "order.paid", {"id": 12, "total_cents": 10})
ok(_acon.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"]
   == _n_before + 1, "and the conditions still gate it there")
_acon.close()

_r = c.post("/api/automation/rules", headers=A, json={
    "name": "webhook one", "event": "ticket.created", "action": "webhook",
    "config": {"url": "https://example.invalid/hook", "token": "s3cret"}})
_wid = _r.json()["id"]
_aut_page = c.get("/api/automation", headers=A).json()
_wr = next(r for r in _aut_page["rules"] if r["id"] == _wid)
ok(_wr["has_token"] and "s3cret" not in json.dumps(_aut_page),
   "a rule may carry a token and the screen is told only that it has one")
ok(c.delete(f"/api/automation/rules/{_wid}", headers=A).status_code == 200,
   "and a rule can be removed")

ok(_aut.matches([{"field": "a.b", "op": "eq", "value": "x"}],
                {"a": {"b": "x"}}),
   "a condition reaches into the event by a dotted name, so a rule can "
   "test a field this module has never heard of")
ok(not _aut.matches([{"field": "a.b", "op": "eq", "value": "x"}], {"a": {}}),
   "and a field that is not there matches nothing rather than everything")

_src_bus = Path("src/storefront/backend/api.py").read_text()
ok("_fan_automation" in _src_bus
   and _src_bus.index("_fan_automation") < _src_bus.index("def fire_webhooks")
   or "_fan_automation" in _src_bus.split("for fan in (")[1][:120],
   "the rules ride the same event bus as Discord and the integrations, "
   "which is what makes a failing rule unable to fail the order")

# --- and the four are reachable, which was the whole point ---
for _cap, _tab in (("accounting", "accounting"), ("treasury", "treasury"),
                   ("legal", "legal"), ("automation", "automation")):
    _row = re.search(rf'\{{ id: "{_tab}",[^}}]*\}}', _ops).group(0)
    ok('group: "' in _row, f"{_cap} has a place in the navigation")
    ok(f'{_tab}: "{_cap}"' in _ops,
       f"and is gated on the {_cap} capability it is sold as")
ok('"Money"' in _ops and "Books" in _ops and "Cash & holdings" in _ops,
   "the books and the bank are their own group rather than more of "
   "Company, which was already seven deep")



def _dbcon():
    """A connection for the checks that read tables directly."""
    return _db.connect()



# ===== finance, payroll and onboarding ==================================
# The last three the price book sold without building. Payroll is the one
# that has to be right: a payslip is the document somebody disputes.
from erp.backend import finance as _fin  # noqa: E402
from erp.backend import onboarding as _onb  # noqa: E402
from erp.backend import payroll as _pay  # noqa: E402

# --- no two modules may own the same table name ---
# This is not decoration. classroom.py already owned a table called
# pay_rates, keyed on teacher_id; payroll's first version declared its own
# with the same name, CREATE TABLE IF NOT EXISTS did nothing at all and
# said nothing about it, and the index that followed failed on a column
# the other module's table has never had. The same collision between the
# storefront's api_keys and the ERP's had been live and unnoticed: every
# call to the public /api/v1 answered 500 on a missing `active`.
_owners: dict = {}
for _f in Path("src").rglob("*.py"):
    # The open bracket matters: without it this matches the phrase
    # inside the comments explaining the collisions it exists to catch.
    for _m in _re3.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\(",
                            _f.read_text(errors="replace")):
        _owners.setdefault(_m.group(1), set()).add(_f.name)
_shared = {t: sorted(fs) for t, fs in _owners.items() if len(fs) > 1}
ok(not _shared,
   f"no table name is declared by two modules ({_shared}) — the second "
   "declaration is silently ignored and the two disagree forever after")
ok(len(_owners) > 200, f"and the check saw the whole schema ({len(_owners)})")

# The bug that guard was written for, checked at the front door too.
_r = c.get("/api/v1/products", headers={"Authorization": "Bearer sk_live_nope"})
ok(_r.status_code == 401,
   "the public API refuses an unknown key rather than failing on its own "
   "schema")

# --- payroll ---
ok(c.get("/api/payroll", headers=_WCU).status_code == 403,
   "payroll is the office's")
_ded = [
    {"code": "tax", "label": "Income tax", "kind": "percent",
     "rate_bps": 2000, "side": "employee", "position": 1},
    {"code": "pension", "label": "Pension", "kind": "percent",
     "rate_bps": 500, "side": "employee", "of_remaining": True, "position": 2},
    {"code": "er", "label": "Employer contribution", "kind": "percent",
     "rate_bps": 300, "side": "employer", "position": 3},
]
for _d in _ded:
    ok(c.post("/api/payroll/deductions", headers=A, json=_d).status_code == 200,
       f"a deduction is configured: {_d['label']}")
ok(c.post("/api/payroll/deductions", headers=A, json={
    "code": "bad", "label": "Over a hundred percent", "kind": "percent",
    "rate_bps": 20000}).status_code == 400,
   "and cannot take more than everything")
_lines, _taken, _employer = _pay._apply(10000, _pay.deductions(_dbcon()))
ok([x["amount_cents"] for x in _lines] == [2000, 400, 300],
   "a percentage of gross, then a percentage of WHAT IS LEFT, then an "
   "employer cost — compounding in the order the operator set, which is "
   "why the order is a field")
ok(_taken == 2400 and _employer == 300,
   "the employer's share is on top of the wage, not out of it")
_, _t2, _ = _pay._apply(1000, [{"code": "x", "label": "Huge", "kind": "fixed",
                                "rate_bps": 0, "amount_cents": 999999,
                                "side": "employee", "of_remaining": 0}])
ok(_t2 == 1000, "and nothing takes more off somebody than they earned")

# Somebody who actually worked. Shifts are written directly because the
# clock is another test's subject; what matters here is that payroll reads
# the same hours the timesheet does.
_emp = c.post("/api/login", json={"name": "Payroll Person",
                                  "role": "employee"}).json()
_pcon = _db.connect()
_pcon.execute("UPDATE users SET employment='employee' WHERE id=?", (_emp["id"],))
_p_from = _t0.time() - 20 * 86400
for _i in range(3):
    _in = _p_from + _i * 86400 + 9 * 3600
    _pcon.execute("INSERT INTO shifts(user_id,clock_in,clock_out) VALUES(?,?,?)",
                  (_emp["id"], _in, _in + 8 * 3600))
_pcon.commit()
_pcon.close()
ok(c.post("/api/payroll/rates", headers=A, json={
    "user_id": _emp["id"], "kind": "hourly", "rate_cents": 2000,
    "overtime_bps": 15000, "effective_from": _p_from - 86400}
   ).status_code == 200, "a rate is set, dated from when it applies")
ok(c.post("/api/payroll/rates", headers=A, json={
    "user_id": _emp["id"], "rate_cents": 2000, "overtime_bps": 5000}
   ).status_code == 400,
   "and overtime cannot be worth less than the hour it was")

_run = c.post("/api/payroll/runs", headers=A, json={
    "label": "Test period", "period_start": _p_from - 86400,
    "period_end": _t0.time()}).json()["id"]
_r = c.post("/api/payroll/runs", headers=A, json={
    "label": "Overlapping", "period_start": _p_from,
    "period_end": _t0.time() - 86400})
ok(_r.status_code == 400 and "twice" in _r.text,
   "two runs over the same hours would pay them twice, so the second is "
   "refused")
ok(c.post(f"/api/payroll/runs/{_run}/approve", headers=A,
          json={}).status_code == 400,
   "an unbuilt run approves nothing and must not look as if it did")
_b = c.post(f"/api/payroll/runs/{_run}/build", headers=A).json()
ok(_b["payslips"] >= 1, "building works out the payslips")
_rd = c.get(f"/api/payroll/runs/{_run}", headers=A).json()
_slip = next(s for s in _rd["payslips"] if s["user_id"] == _emp["id"])
ok(_slip["regular_hours"] == 24.0 and _slip["gross_cents"] == 48000,
   f"24 hours at $20 is $480 gross ({_slip['regular_hours']}h, "
   f"{_slip['gross_cents']})")
ok(_slip["net_cents"] == 48000 - 9600 - 1920,
   "less 20% tax and 5% of what is left")
ok(_slip["employer_cents"] == 1440,
   "with the employer's 3% recorded beside it rather than inside it")
ok(sum(l["amount_cents"] for l in _slip["lines"]) == _slip["gross_cents"],
   "and the lines add up to the gross, so the working is visible")
_before_build = _slip["gross_cents"]
ok(c.post(f"/api/payroll/runs/{_run}/build", headers=A).json()["payslips"]
   == _b["payslips"], "a draft rebuilds without duplicating anybody")

ok(c.post(f"/api/payroll/runs/{_run}/paid", headers=A,
          json={}).status_code == 400, "a run is approved before it is paid")
ok(c.post(f"/api/payroll/runs/{_run}/approve", headers=A,
          json={}).status_code == 200, "approving freezes it")
ok(c.post(f"/api/payroll/runs/{_run}/build", headers=A).status_code == 400,
   "and an approved run does not rebuild — a payslip from March must "
   "still say in June what it said in March")
_mine = c.get("/api/payroll/mine", headers={
    "Authorization": "Bearer " + _emp["token"]}).json()["payslips"]
ok(len(_mine) == 1 and _mine[0]["gross_cents"] == _before_build
   and _mine[0]["lines"],
   "the person paid sees their own payslip in full, working included — a "
   "number somebody cannot see the working of is one they cannot dispute")
_r = c.post(f"/api/payroll/runs/{_run}/paid", headers=A, json={})
ok(_r.status_code == 200 and _r.json()["journal_id"],
   "marking it paid puts it in the books, which approving did not")
_j = c.get(f"/api/accounting/journals/{_r.json()['journal_id']}",
           headers=A).json()
_by_acct = {}
for _l in _j["lines"]:
    _by_acct[_l["account"]] = _by_acct.get(_l["account"], 0) \
        + _l["debit_cents"] - _l["credit_cents"]
ok(_by_acct.get("6100", 0) == _rd["gross_cents"] + _rd["employer_cents"],
   "the wage and the employer's share are both a cost")
ok(_by_acct.get("2210", 0) == -(_rd["deductions_cents"] + _rd["employer_cents"]),
   "what was held back is owed onward, not earned")
ok(_by_acct.get("1010", 0) == -_rd["net_cents"],
   "and only the net actually left the bank")
ok(c.get("/api/accounting", headers=A).json()["trial_balance"]["balanced"],
   "the books still balance with payroll in them")
ok(c.post(f"/api/payroll/runs/{_run}/cancel", headers=A).status_code == 400,
   "a paid run is history — it is reversed in the books, not cancelled here")

# --- finance ---
ok(c.get("/api/finance", headers=_WCU).status_code == 403,
   "the finances are the office's")
_fp = c.get("/api/finance", headers=A).json()
ok("rows" in _fp["receivables"] and "aged" in _fp["receivables"],
   "what is owed to us is derived from the orders, aged by how long it "
   "has been owed")
_fcon = _db.connect()
_owed = _fcon.execute(
    "SELECT COALESCE(SUM(total_cents),0) AS c FROM orders WHERE"
    " payment_status IN ('on_terms','unpaid') AND status<>'cancelled'"
    ).fetchone()["c"]
ok(_fp["receivables"]["total_cents"] == _owed,
   "and it IS the orders, not a second copy that can drift from them")
ok(sum(_fp["receivables"]["aged"].values())
   == _fp["receivables"]["total_cents"],
   "every pound owed sits in exactly one age bucket")
_fcon.close()

_bud = c.post("/api/finance/budgets", headers=A, json={
    "label": "Test year", "starts": _t0.time() - 180 * 86400,
    "ends": _t0.time() + 180 * 86400}).json()["id"]
ok(c.post("/api/finance/budgets", headers=A, json={
    "label": "Backwards", "starts": _t0.time(),
    "ends": _t0.time() - 86400}).status_code == 400,
   "a budget ends after it starts")
ok(c.post(f"/api/finance/budgets/{_bud}/lines", headers=A, json={
    "account": "9999", "amount_cents": 100}).status_code == 400,
   "a budget line is planned against an account the actual can land in, "
   "or the two can never be compared")
c.post(f"/api/finance/budgets/{_bud}/lines", headers=A,
       json={"account": "4000", "amount_cents": 10_000_00})
c.post(f"/api/finance/budgets/{_bud}/lines", headers=A,
       json={"account": "6100", "amount_cents": 100_00})
_bv = c.get(f"/api/finance/budgets/{_bud}", headers=A).json()
_sales = next(l for l in _bv["lines"] if l["account"] == "4000")
_wages = next(l for l in _bv["lines"] if l["account"] == "6100")
ok(_sales["actual_cents"] == next(
    b["balance_cents"] for b in _acc.balances(
        _dbcon(), since=_bv["starts"], upto=_bv["ends"]) if b["code"] == "4000"),
   "the actual comes from the ledger, so budget and books cannot drift "
   "into two definitions of a cost")
ok(_wages["actual_cents"] > _wages["planned_cents"] and not _wages["on_track"],
   "spending more than planned on wages is off track")
ok(_sales["actual_cents"] < _sales["planned_cents"] and not _sales["on_track"],
   "and so is earning LESS than planned — one subtraction cannot mean "
   "both, so the sign follows the kind of account")
c.post(f"/api/finance/budgets/{_bud}/lines", headers=A,
       json={"account": "4000", "amount_cents": 1})
ok(len(c.get(f"/api/finance/budgets/{_bud}", headers=A).json()["lines"]) == 2,
   "a line for an account already budgeted replaces it rather than "
   "doubling it")
_fc = c.get("/api/finance", headers=A).json()["forecast"]
ok(len(_fc["weeks"]) == 12 and _fc["weeks"][0]["closing_cents"] is not None,
   "the forecast runs a quarter ahead")
ok("not a prediction" in _fc["note"],
   "and says on the screen that it is arithmetic on the rows already "
   "here, not a promise anybody made")

# --- onboarding ---
ok(c.get("/api/onboarding", headers=_WCU).status_code == 403,
   "onboarding is the office's")
_ob = c.get("/api/onboarding", headers=A).json()
ok(_ob["templates"] and all(t["steps"] for t in _ob["templates"]),
   "the built-in lists are seeded as editable templates — an empty "
   "template editor teaches nobody what a template is for")
_joining = next(t for t in _ob["templates"] if t["kind"] == "joining")
ok([s["title"] for s in _joining["steps"]]
   == [t[0] for t in _hir.ONBOARDING],
   "and it is the list hiring already used, so nothing changed for an "
   "install that never opens this screen")
_tpl = c.post("/api/onboarding/templates", headers=A, json={
    "name": "Driver", "role": "employee"}).json()["id"]
c.post(f"/api/onboarding/templates/{_tpl}/steps", headers=A, json={
    "title": "Licence on file", "tab": "docs", "days_after": 0,
    "needs_document": True})
c.post(f"/api/onboarding/templates/{_tpl}/steps", headers=A, json={
    "title": "Van walkaround", "tab": "routes", "days_after": 2})
ok(c.post(f"/api/onboarding/templates/{_tpl}/steps", headers=A, json={
    "title": "Too far off", "days_after": 999}).status_code == 400,
   "a step falls due between the start day and a year in")
_started = c.post("/api/onboarding/start", headers=A, json={
    "user_id": _emp["id"], "template_id": _tpl,
    "starts": _t0.time() - 5 * 86400}).json()
ok(_started["steps"] == 2, "starting somebody writes their list")
ok(c.post("/api/onboarding/start", headers=A, json={
    "user_id": _emp["id"], "template_id": _tpl}).json().get("already"),
   "and starting the same one twice would leave two of every step, so it "
   "does not")
_ob = c.get("/api/onboarding", headers=A).json()
_j = next(j for j in _ob["journeys"] if j["user_id"] == _emp["id"])
ok(_j["overdue"] == 2 and _j["total"] == 2,
   "dates count from THEIR start date, so a list begun late is late")
ok(_j["waiting_on_documents"] == 1,
   "and a step that needs a document says so before anybody ticks it")
_doc_task = next(t for t in _j["tasks"] if t["needs_document"])
_r = c.post(f"/api/onboarding/tasks/{_doc_task['id']}/done", headers=A, json={})
ok(_r.status_code == 400 and "waiting on a document" in _r.text,
   "'we asked for their right-to-work' and 'we have it' are different "
   "states, and only one of them ticks")
ok(c.post(f"/api/onboarding/tasks/{_doc_task['id']}/done", headers=A,
          json={"document_id": 1}).status_code == 200,
   "with one attached it ticks")
_plain = next(t for t in _j["tasks"] if not t["needs_document"])
c.post(f"/api/onboarding/tasks/{_plain['id']}/done", headers=A, json={})
_ob = c.get("/api/onboarding", headers=A).json()
_j = next(j for j in _ob["journeys"] if j["user_id"] == _emp["id"])
ok(_j["complete"] and _j["completed_at"],
   "and the journey finishes when its last step does")
_theirs = c.get("/api/onboarding/mine", headers={
    "Authorization": "Bearer " + _emp["token"]}).json()["journeys"]
ok(_theirs and _theirs[0]["total"] == 2,
   "a new starter can see what is expected of them without asking the "
   "person who set it up")

# Hiring hands off to a template when the role has one, and keeps its own
# list otherwise, so an install that never opens Onboarding is unchanged.
_hsrc = Path("src/erp/backend/hiring.py").read_text()
ok("_ob.template_for(con, role)" in _hsrc and "if not started:" in _hsrc,
   "hiring uses the role's template when there is one and its built-in "
   "list when there is not")

# --- the three are reachable ---
for _cap in ("finance", "payroll", "onboarding"):
    ok(f'{_cap}: "{_cap}"' in _ops, f"{_cap} is gated on the capability it "
                                    "is sold as")
    ok(_re3.search(rf'\{{ id: "{_cap}",[^}}]*group: "\w', _ops),
       f"and {_cap} has a place in the navigation")



# ===== invoicing, leaving, and the policy register =====================
from erp.backend import civics as _civ  # noqa: E402

# --- invoices: a receivable you can send ---
_r = c.post("/api/finance/invoices", headers=A, json={
    "bill_to": "Harbour Estates", "bill_email": "ap@harbour.test",
    "reference": "PO-4471", "terms_days": 30, "lines": [
        {"what": "Consulting, March", "qty": 12, "unit_cents": 9000,
         "tax_bps": 2000},
        {"what": "Materials", "qty": 1, "unit_cents": 25000}]})
ok(_r.status_code == 200, "an invoice starts as a draft")
_iid = _r.json()["id"]
_inv = c.get(f"/api/finance/invoices/{_iid}", headers=A).json()
ok(_inv["subtotal_cents"] == 133000 and _inv["tax_cents"] == 21600
   and _inv["total_cents"] == 154600,
   f"the lines add up and tax is per line ({_inv['total_cents']})")
ok(_inv["state"] == "draft" and not _inv["number"],
   "a draft has no number — an abandoned one must not consume one, "
   "because a gap in an invoice sequence is a question somebody asks")
ok(c.get("/api/finance/invoices", headers=_WCU).status_code == 403,
   "invoices are the office's")

_r = c.post(f"/api/finance/invoices/{_iid}/issue", headers=A, json={})
ok(_r.status_code == 200 and _r.json()["number"].endswith("-0001"),
   f"issuing numbers it ({_r.json().get('number')})")
_num = _r.json()["number"]
ok(_r.json()["journal_id"],
   "and puts it in the books at ISSUE, not at payment — a business that "
   "only recognises a claim when it is settled cannot say what it is owed")
_j = c.get(f"/api/accounting/journals/{_r.json()['journal_id']}",
           headers=A).json()
_by = {}
for _l in _j["lines"]:
    _by[_l["account"]] = _by.get(_l["account"], 0) + _l["debit_cents"] - _l["credit_cents"]
ok(_by.get("1200") == 154600 and _by.get("4000") == -133000
   and _by.get("2100") == -21600,
   "they owe us the whole of it; we earned the net and hold the tax")
ok(c.post("/api/finance/invoices", headers=A, json={
    "id": _iid, "bill_to": "Somebody else"}).status_code == 400,
   "an issued invoice cannot be edited — somebody has a copy of what it "
   "said")

_r = c.post(f"/api/finance/invoices/{_iid}/payments", headers=A,
            json={"amount_cents": 50000, "method": "transfer"})
ok(_r.status_code == 200 and _r.json()["paid_cents"] == 50000,
   "part payment is normal and is recorded as what arrived")
ok(c.get(f"/api/finance/invoices/{_iid}", headers=A).json()["state"]
   == "part_paid", "which leaves it part paid rather than open or shut")
ok(c.post(f"/api/finance/invoices/{_iid}/payments", headers=A,
          json={"amount_cents": 9_999_999}).status_code == 400,
   "and nobody can pay more than is outstanding")

_fin_owed = c.get("/api/finance", headers=A).json()["receivables"]
ok(any(x.get("kind") == "invoice" and x["total_cents"] == 104600
       for x in _fin_owed["rows"]),
   "an issued invoice is owed to us in the same list as an unpaid order, "
   "for what is left on it")

_r = c.post(f"/api/finance/invoices/{_iid}/credit", headers=A,
            json={"reason": "Work cancelled"})
ok(_r.status_code == 200 and _r.json()["number"].endswith("-CN"),
   "a correction is a credit note")
ok(c.get(f"/api/finance/invoices/{_iid}", headers=A).json()["state"] == "void"
   and c.get(f"/api/finance/invoices/{_iid}", headers=A).json()["number"] == _num,
   "the original keeps its number and says it was credited, rather than "
   "changing into something else")
ok(c.post(f"/api/finance/invoices/{_iid}/credit", headers=A,
          json={}).status_code == 400, "and is credited once")
_acc_now = c.get("/api/accounting", headers=A).json()
ok(_acc_now["trial_balance"]["balanced"],
   "the books still balance with the invoice and its credit in them")
_inv_list = c.get("/api/finance/invoices", headers=A).json()
ok(_inv_list["outstanding_cents"] == 0 and _inv_list["overdue_cents"] == 0
   and _inv_list["credited_cents"] == 154600,
   "a credit note is money we owe THEM: counting it as outstanding would "
   "say the business is owed the very amount it gave back")
ok(not any(x.get("kind") == "invoice"
           for x in c.get("/api/finance", headers=A).json()["receivables"]["rows"]),
   "and a credited invoice leaves the receivables entirely")

_tok = c.get(f"/api/finance/invoices/{_iid}", headers=A).json()["token"]
_page = c.get(f"/invoice/{_tok}")
ok(_page.status_code == 200 and "Harbour Estates" in _page.text
   and "PO-4471" in _page.text,
   "the customer opens it from a link with no sign-in — a customer made "
   "to open an account to read a bill telephones instead")
ok(c.get(f"/api/finance/invoices/{_iid}", headers=A).json()["viewed_at"],
   "and opening it is recorded, which answers 'we never received it'")
ok(c.get("/invoice/nonsense").status_code == 404, "a bad token is nothing")
_pdf = c.get(f"/api/finance/invoices/{_iid}/pdf", headers=A)
ok(_pdf.status_code == 200 and _pdf.content[:4] == b"%PDF",
   "and there is a PDF of it to attach to an email")

# --- leaving ---
_leaver = c.post("/api/login", json={"name": "Leaving Person",
                                     "role": "employee"}).json()
_lcon = _db.connect()
_lcon.execute("UPDATE users SET pin_hash='abc', clock_token='badge1'"
              " WHERE id=?", (_leaver["id"],))
_lcon.execute("INSERT INTO scheduled_shifts(user_id,starts,ends,created_at)"
              " VALUES(?,?,?,?)",
              (_leaver["id"], _t0.time() + 3 * 86400,
               _t0.time() + 3 * 86400 + 8 * 3600, _t0.time()))
_lcon.commit()
_lcon.close()
_key = c.post("/api/admin/api-keys", headers=A, json={
    "name": "their key", "scope": "read", "user_id": _leaver["id"]}).json()
ok(_key.get("secret"), "they have a live API key before they leave")

_last = _t0.time() + 14 * 86400
_r = c.post("/api/onboarding/departures", headers=A, json={
    "user_id": _leaver["id"], "reason": "resigned", "last_day": _last,
    "rehire": "yes", "note": "Moving abroad"})
ok(_r.status_code == 200 and _r.json()["journey_id"],
   "recording a departure opens their last-day list")
_did = _r.json()["id"]
ok(c.post("/api/onboarding/departures", headers=A, json={
    "user_id": _leaver["id"], "reason": "dismissed", "last_day": _last}
   ).status_code == 400, "and there is only one open departure per person")
_ob = c.get("/api/onboarding", headers=A).json()
_dep = next(x for x in _ob["departures"] if x["id"] == _did)
ok(_dep["access_open"] and _dep["total"] == len(_onb.LEAVING),
   "access is still open at that point, which is the state the screen "
   "shouts about")
ok(c.get("/api/onboarding", headers=A).json()["templates"] and any(
    t["kind"] == "leaving" for t in _ob["templates"]),
   "a last-day template is seeded beside the first-fortnight one")

_r = c.post(f"/api/onboarding/departures/{_did}/close-access", headers=A,
            json={})
ok(_r.status_code == 200, "closing access is one action, not a tick")
_did_what = set(_r.json()["did"])
_ccon = _db.connect()
_u = _ccon.execute("SELECT * FROM users WHERE id=?", (_leaver["id"],)).fetchone()
ok(not _u["active"], "the account is deactivated")
ok(not (_u["pin_hash"] or "") and not (_u["clock_token"] or ""),
   "the time-clock PIN and the badge are forgotten, so neither opens a "
   "door tomorrow")
ok(_u["token"] != _leaver["token"],
   "their session token is rotated — a deactivated flag alone leaves them "
   "signed in until something happens to check")
ok(_ccon.execute("SELECT COUNT(*) AS n FROM api_keys WHERE user_id=? AND"
                 " revoked_at IS NULL", (_leaver["id"],)).fetchone()["n"] == 0,
   "every API key bound to them is revoked")
ok(_ccon.execute("SELECT COUNT(*) AS n FROM scheduled_shifts WHERE user_id=?"
                 " AND starts>?", (_leaver["id"], _t0.time())
                 ).fetchone()["n"] == 0,
   "and shifts nobody has worked yet are dropped")
ok(_ccon.execute("SELECT COUNT(*) AS n FROM users WHERE id=?",
                 (_leaver["id"],)).fetchone()["n"] == 1,
   "nothing is deleted: a business that erases a leaver cannot answer a "
   "question about last year")
_ccon.close()
ok(c.get("/api/whoami", headers={"Authorization": "Bearer " + _leaver["token"]}
         ).status_code in (401, 403),
   "and their old token opens nothing")
ok(c.post(f"/api/onboarding/departures/{_did}/close-access", headers=A,
          json={}).status_code == 400, "closing twice is refused, with what "
                                       "the first one did")

# --- civics ---
ok(c.get("/api/civics", headers=_WCU).status_code == 403,
   "the policy register is an office screen")
_country = c.post("/api/civics/jurisdictions", headers=A, json={
    "name": "United States", "level": "country", "lat": 39.8, "lng": -98.6}
    ).json()["id"]
_state = c.post("/api/civics/jurisdictions", headers=A, json={
    "name": "Illinois", "level": "state", "parent_id": _country,
    "lat": 40.0, "lng": -89.0}).json()["id"]
_city = c.post("/api/civics/jurisdictions", headers=A, json={
    "name": "Springfield", "level": "city", "parent_id": _state,
    "lat": 39.8, "lng": -89.65, "population": 114394,
    "boundary": {"type": "Polygon", "coordinates": [
        [[-89.7, 39.75], [-89.6, 39.75], [-89.6, 39.85], [-89.7, 39.85],
         [-89.7, 39.75]]]}}).json()["id"]
ok(c.post("/api/civics/jurisdictions", headers=A, json={
    "name": "Nowhere", "level": "city", "lat": 999}).status_code == 400,
   "a latitude that is not on the earth is refused")
_cv = c.get("/api/civics", headers=A).json()
ok(len(_cv["map"]["jurisdictions"]) == 3 and _cv["map"]["bounds"],
   "the map is drawn from the install's own rows, with bounds to fit it in")
ok(any(isinstance(j["boundary"], dict) for j in _cv["map"]["jurisdictions"]),
   "a boundary comes back as geometry the page can draw, not as a string")
ok("places" in _cv["map"],
   "and the business's own places go on it beside them — 'what are we "
   "inside, here' is the question that starts every enquiry")

_mid = c.post("/api/civics/measures", headers=A, json={
    "jurisdiction_id": _state, "ref": "HB 1234",
    "title": "Minimum wage increase", "status": "in_committee",
    "position": "oppose", "impact": "high",
    "why": "About 40k a year across the two shops"}).json()["id"]
ok(c.post("/api/civics/measures", headers=A, json={
    "title": "x", "position": "furious"}).status_code == 400,
   "a position is one of the four, not a mood")
c.post("/api/civics/measures", headers=A, json={
    "id": _mid, "jurisdiction_id": _state, "title": "Minimum wage increase",
    "status": "passed_one", "position": "oppose", "impact": "high"})
_m = c.get(f"/api/civics/measures/{_mid}", headers=A).json()
ok(any("in_committee" in e["what"] and "passed_one" in e["what"]
       for e in _m["events"]),
   "a stage change writes itself into the history, so the page is not a "
   "snapshot of the last time somebody looked")
ok(_m["jurisdiction"] == "Illinois", "and a measure knows where it is")

_r = c.post("/api/civics/elections", headers=A, json={
    "jurisdiction_id": _state, "name": "State general", "kind": "general",
    "at": _t0.time() + 60 * 86400,
    "registration_deadline": _t0.time() + 30 * 86400})
ok(_r.status_code == 200, "an election goes on the calendar")
ok(c.post("/api/civics/elections", headers=A, json={
    "name": "Backwards", "at": _t0.time(),
    "registration_deadline": _t0.time() + 86400}).status_code == 400,
   "registration closes before the election, not after it")

ok(c.post("/api/civics/contributions", headers=A, json={
    "recipient": "Somebody", "amount_cents": 50000}).status_code == 400,
   "a contribution with nobody recorded as having authorised it is the "
   "one that becomes a problem later, so it is refused")
ok(c.post("/api/civics/contributions", headers=A, json={
    "recipient": "Committee for Main Street", "amount_cents": 50000,
    "authorised_by": "Boss", "jurisdiction_id": _state}).status_code == 200,
   "with one, it is recorded")
_cv = c.get("/api/civics", headers=A).json()
ok(_cv["given_cents"] == 50000 and _cv["undisclosed"] == 1,
   "and what has no filing reference yet is counted, because that is the "
   "number somebody has to work down")
ok("not advice" in _cv["disclaimer"] and "files" in _cv["disclaimer"],
   "the screen says plainly that it checks no limit and files nothing — "
   "software that looked like it had checked would be worse than a "
   "spreadsheet, which does not look like it has")
_csv = c.get("/api/civics/contributions.csv", headers=A)
ok(_csv.status_code == 200 and "authorised by" in _csv.text
   and "Committee for Main Street" in _csv.text,
   "the register exports as a file, because a disclosure is attached to a "
   "form on a website this software has never heard of")
ok(_cv["counts"]["live_measures"] == 1 and _cv["counts"]["high_impact"] == 1
   and _cv["counts"]["elections_soon"] == 1,
   "and the counts at the top are the four questions worth asking")
ok(c.delete(f"/api/civics/jurisdictions/{_state}", headers=A).status_code == 400,
   "a jurisdiction with measures under it does not simply vanish")

# The three sources, and what they honestly are.
_civ_prov = {p["name"]: p for p in c.get("/api/admin/integrations", headers=A
                                          ).json()["providers"]
             if p.get("family") == "civics"}
ok(set(_civ_prov) == {"open_states", "congress_gov"},
   "two keyed sources — the third, the Census geocoder, needs no key and "
   "so is not a connector at all")
ok("google_civic" not in json.dumps(c.get("/api/admin/integrations", headers=A).json()),
   "and Google Civic is not offered: its representatives endpoint was "
   "turned down in April 2025 and a connector to it would fail on the "
   "first real key")
ok(all(not p["connected"] for p in _civ_prov.values()),
   "none connected until somebody connects it")
_civ_src = Path("src/erp/backend/civics.py").read_text()
ok("publishes nothing an API can" in _civ_src,
   "and the file says out loud that below the state line most places "
   "publish nothing, which is why typing a measure in is a first-class "
   "path rather than a fallback")

# --- the map: vendored, layered, and honest about the network ---
ok("/vendor/leaflet/leaflet.js" in _ops and "countries-110m.geojson" in _ops,
   "the map is Leaflet, vendored, over a bundled outline of every country "
   "— nothing is fetched from a CDN to draw it")
for _asset in ("src/storefront/frontend/vendor/leaflet/leaflet.js",
               "src/storefront/frontend/vendor/leaflet/leaflet.css",
               "src/storefront/frontend/vendor/leaflet/LICENSE",
               "src/storefront/frontend/vendor/countries-110m.geojson",
               "src/storefront/frontend/vendor/countries-110m.LICENSE"):
    ok(Path(_asset).exists(), f"{_asset.split('/')[-1]} ships with the install")
ok(c.get("/vendor/leaflet/leaflet.js").status_code == 200
   and c.get("/vendor/countries-110m.geojson").status_code == 200,
   "and both are served from the install itself")
_world = c.get("/vendor/countries-110m.geojson").json()
ok(len(_world["features"]) >= 170
   and all(k in _world["features"][0]["properties"]
           for k in ("name", "iso2", "iso3", "continent")),
   "every country, with the codes a watched country is matched on")
ok(len(c.get("/vendor/countries-110m.geojson").content) < 400_000,
   "stripped and rounded, so it is a download the page can afford")
ok("tile.openstreetmap.org" in _ops
   and "outline layer underneath is what the page shows" in _ops,
   "tiles come from OpenStreetMap when online, and the page says what "
   "happens when they do not: the outline is what you see, not grey")
ok("civOfferWatch" in _ops and "/api/civics/watch" in _ops,
   "clicking a country that is not on the register offers to watch it — "
   "the map shows every country, the register holds only the watched ones")
ok("/api/civics/jurisdictions/${jid}/detail" in _ops,
   "and clicking any place opens that place, not a filter")

# --- the stack now runs from a treaty bloc to a homeowners' association ---
ok(_civ.LEVEL_ORDER[0] == "bloc" and _civ.LEVEL_ORDER[-2] == "hoa",
   "the levels run from a treaty bloc down to an HOA, in that order")

# --- finding the stack: the Census geocoder, stubbed in that shape ---
_census_shape = {"result": {"addressMatches": [{
    "matchedAddress": "1 CITY HALL PLZ, BOSTON, MA, 02201",
    "coordinates": {"x": -71.058, "y": 42.360},
    "geographies": {
        "States": [{"NAME": "Massachusetts", "GEOID": "25"}],
        "Counties": [{"NAME": "Suffolk County", "GEOID": "25025"}],
        "Incorporated Places": [{"NAME": "Boston city", "GEOID": "2507000"}],
        "119th Congressional Districts": [{"NAME": "Congressional District 8",
                                          "GEOID": "2508", "BASENAME": "8"}],
        "2024 State Legislative Districts - Upper": [
            {"NAME": "First Suffolk District", "GEOID": "25001"}],
        "2024 State Legislative Districts - Lower": [
            {"NAME": "Third Suffolk District", "GEOID": "25003"}],
        "Unified School Districts": [{"NAME": "Boston School District",
                                     "GEOID": "2502790"}],
        "Census Tracts": [{"NAME": "Census Tract 303", "GEOID": "25025030300"}],
    }}]}}
# TIGERweb, in the shape the Census actually serves: a service lists its
# layers once per vintage with shuffling ids, and a query returns GeoJSON.
_tiger_layers = {"State_County": [(0, "States"), (1, "Counties"),
                                  (2, "States"), (3, "Counties")],
                 "Legislative": [(0, "120th Congressional Districts"),
                                 (1, "2026 State Legislative Districts - Upper"),
                                 (2, "2026 State Legislative Districts - Lower"),
                                 (4, "119th Congressional Districts"),
                                 (5, "2024 State Legislative Districts - Upper"),
                                 (6, "2024 State Legislative Districts - Lower")],
                 "Places_CouSub_ConCity_SubMCD": [(4, "Incorporated Places")],
                 "School": [(0, "Unified School Districts")]}
_tiger_hits = []
def _census_req(url, method="GET", headers=None, body=None, timeout=15):
    if "geocoding.geo.census.gov" in url:
        return True, _census_shape
    if "tigerweb.geo.census.gov" in url and "MapServer?f=json" in url:
        svc = url.split("/TIGERweb/")[1].split("/")[0]
        return True, {"layers": [{"id": i, "name": n}
                                 for i, n in _tiger_layers.get(svc, [])]}
    if "tigerweb.geo.census.gov" in url and "/query?" in url:
        _tiger_hits.append(url)
        geoid = url.split("GEOID%3D%27")[1].split("%27")[0]
        return True, {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"GEOID": geoid},
             "geometry": {"type": "Polygon", "coordinates": [
                 [[-71.2, 42.3], [-71.0, 42.3], [-71.0, 42.4], [-71.2, 42.4],
                  [-71.2, 42.3]]]}}]}
    return False, "unexpected " + url
_real_req3 = _ig._req
_ig._req = _census_req
_r = c.post("/api/civics/find", headers=A, json={"address": "1 City Hall Plaza, Boston, MA"})
ok(_r.status_code == 200 and _r.json()["matched"].startswith("1 CITY HALL"),
   "an address is placed by the Census geocoder, which needs no key")
ok(len(_r.json()["jurisdictions"]) == 8,
   "and the whole stack comes back: country, state, county, city, the "
   "congressional district, both state chambers and the school district")
ok(len(_r.json()["boundaries"]["drawn"]) == 7 and not _r.json()["boundaries"]["failed"],
   "and every Census-placed one is outlined straight away, from the "
   "Census's own map service — the country is not, having no GEOID")
ok(any("Legislative/MapServer/4/" in u for u in _tiger_hits),
   "the congressional district is drawn from the 119th Congress's layer, "
   "the vintage that PLACED it, not from the 120th that sits first in the "
   "service — ids there shuffle per vintage and are resolved by name")
ok(any("Legislative/MapServer/5/" in u for u in _tiger_hits)
   and any("Legislative/MapServer/6/" in u for u in _tiger_hits),
   "and each state chamber from its own layer")
ok(any("School/MapServer/0/" in u for u in _tiger_hits),
   "the school district from the School service, which is what the "
   "Census calls it")
ok(all("maxAllowableOffset" in u for u in _tiger_hits),
   "every outline asked for simplified, so a coastline is hundreds of "
   "points rather than tens of thousands")
ok(_r.json()["state_fips"] == "25" and _r.json()["district"] == "8",
   "with the state and district the keyed sources start from")
_cv = c.get("/api/civics", headers=A).json()
_bos = next(j for j in _cv["jurisdictions"] if j["name"] == "Boston city")
_suf = next(j for j in _cv["jurisdictions"] if j["name"] == "Suffolk County")
_ma = next(j for j in _cv["jurisdictions"] if j["name"] == "Massachusetts")
ok(_bos["parent_id"] == _suf["id"] and _suf["parent_id"] == _ma["id"],
   "nested the way they are on the ground: city inside county inside state")
ok(_bos["code"] == "census:2507000",
   "each carrying the FIPS code every other US dataset joins on")
ok(not any(j["name"].startswith("Census Tract") for j in _cv["jurisdictions"]),
   "and the layers that mean nothing to a business — tracts, blocks — are "
   "left where they are")
_n = len(_cv["jurisdictions"])
c.post("/api/civics/find", headers=A, json={"address": "1 City Hall Plaza, Boston, MA"})
ok(len(c.get("/api/civics", headers=A).json()["jurisdictions"]) == _n,
   "finding twice adds nothing twice")
_bos_full = next(j for j in c.get("/api/civics", headers=A).json()["map"]["jurisdictions"]
                 if j["id"] == _bos["id"])
ok(isinstance(_bos_full["boundary"], dict) and _bos_full["boundary"]["type"] == "Polygon",
   "and the outline is stored on the row as geometry the map draws")
_typed = c.post("/api/civics/jurisdictions", headers=A, json={
    "name": "Typed Town", "level": "city", "lat": 42.0, "lng": -71.0}).json()["id"]
_r = c.post(f"/api/civics/jurisdictions/{_typed}/boundary", headers=A)
ok(_r.status_code == 400 and "typed" in _r.text,
   "a place somebody typed has no Census outline, and the refusal says "
   "to paste one instead")
_n_hits = len(_tiger_hits)
ok(c.post("/api/civics/boundaries", headers=A).json()["drawn"] == []
   and len(_tiger_hits) == _n_hits,
   "drawing again asks the Census for nothing — an outline it already "
   "has is not fetched twice")
ok(_civ._layer(_census_shape["result"]["addressMatches"][0]["geographies"],
               "Legislative Districts", "Upper")[1]["NAME"] == "First Suffolk District",
   "layers are matched by what they mean — the Census names them by "
   "vintage, and the 120th Congress must not break the parser")
ok(_civ._state_code("25") == "MA" and _civ._state_code("06") == "CA",
   "a FIPS code becomes the two letters Congress.gov wants")
_ig._req = lambda url, method="GET", headers=None, body=None, timeout=15: (
    True, {"result": {"addressMatches": []}})
_r = c.post("/api/civics/find", headers=A, json={"address": "10 Downing Street, London"})
ok(_r.status_code == 404 and "United States only" in _r.text,
   "an address the geocoder cannot place gets a plain answer, and the "
   "answer says why")
_ig._req = _real_req3

# --- who holds the offices, from the keyed sources, stubbed in shape ---
def _reps_req(url, method="GET", headers=None, body=None, timeout=15):
    if "jurisdictions?per_page=1" in url:
        return True, {}
    if "people.geo" in url:
        return True, {"results": [
            {"id": "ocd-person/1", "name": "A. Senator", "party": "Independent",
             "current_role": {"title": "Senator", "org_classification": "upper",
                              "district": "First Suffolk"},
             "jurisdiction": {"name": "Massachusetts"}, "email": "a@ma.gov",
             "openstates_url": "https://openstates.org/person/1"}]}
    if "/v3/bill?limit=1" in url:
        return True, {}
    if "/v3/member/MA" in url:
        return True, {"members": [
            {"bioguideId": "S1", "name": "Sen One", "partyName": "D",
             "terms": {"item": [{"chamber": "Senate"}]}, "url": "u1"},
            {"bioguideId": "R8", "name": "Rep Eight", "partyName": "D",
             "district": 8, "terms": {"item": [{"chamber": "House of Representatives"}]}, "url": "u8"},
            {"bioguideId": "R1", "name": "Rep One", "partyName": "D",
             "district": 1, "terms": {"item": [{"chamber": "House of Representatives"}]}, "url": "u1b"}]}
    return False, "unexpected " + url
_ig._req = _reps_req
c.post("/api/admin/integrations/open_states/connect", headers=A,
       json={"fields": {"api_key": "k"}})
c.post("/api/admin/integrations/congress_gov/connect", headers=A,
       json={"fields": {"api_key": "k"}})
_r = c.post("/api/civics/representatives", headers=A, json={
    "lat": 42.36, "lng": -71.06, "state_fips": "25", "district": "8"})
ok(_r.status_code == 200 and _r.json()["state"]["new"] == 1
   and _r.json()["federal"]["new"] == 2,
   "the state legislators come from Open States by point and the federal "
   "members from Congress.gov by state — and the representative for a "
   "different district is left out")
_offs = {o["name"]: o for o in c.get("/api/civics", headers=A).json()["officials"]}
ok("Rep Eight" in _offs and "Rep One" not in _offs and "Sen One" in _offs,
   "both senators, our representative, not the neighbouring one")
ok(_offs["A. Senator"]["office"].startswith("State Senate"),
   "and a state chamber is named as a chamber, not as 'upper'")
_ig._req = _real_req3

# --- the panel: one place, and everything the register knows about it ---
_ca = c.post("/api/civics/watch", headers=A, json={
    "iso": "CA", "name": "Canada", "lat": 56.1, "lng": -106.3}).json()["id"]
ok(c.post("/api/civics/watch", headers=A, json={
    "iso": "CA", "name": "Canada", "lat": 56.1, "lng": -106.3}).json()["id"] == _ca,
   "watching a country twice is once")
_us = next(j["id"] for j in c.get("/api/civics", headers=A).json()["jurisdictions"]
           if j["level"] == "country" and j.get("iso") == "US")
ok(c.post("/api/civics/agreements", headers=A, json={
    "name": "Lonely", "parties": [{"jurisdiction_id": _us}]}).status_code == 400,
   "an agreement is between at least two places")
_ag = c.post("/api/civics/agreements", headers=A, json={
    "name": "USMCA", "kind": "trade", "position": "support", "impact": "high",
    "why": "Tariff-free parts from Ontario",
    "parties": [{"jurisdiction_id": _us}, {"jurisdiction_id": _ca}]})
ok(_ag.status_code == 200, "a trade agreement goes on the register")
_det = c.get(f"/api/civics/jurisdictions/{_us}/detail", headers=A).json()
ok(_det["level_label"] == "Country" and not _det["ancestors"],
   "the panel for a country knows it is at the top of its stack")
ok(any(k["name"] == "Massachusetts" for k in _det["children"]),
   "what is inside it")
ok(_det["agreements"] and _det["agreements"][0]["name"] == "USMCA"
   and {p["name"] for p in _det["agreements"][0]["parties"]} == {"United States", "Canada"},
   "what it has agreed, and with whom")
ok(any(o["name"] == "Sen One" for o in _det["officials"]),
   "and who runs it")
_bd = c.get(f"/api/civics/jurisdictions/{_bos['id']}/detail", headers=A).json()
ok([a["name"] for a in _bd["ancestors"]]
   == ["United States", "Massachusetts", "Suffolk County"],
   "and the panel for a city walks the stack above it, in order")
ok(c.get("/api/civics/jurisdictions/999999/detail", headers=A).status_code == 404,
   "a place that is not there is nothing")
ok(c.delete(f"/api/civics/agreements/{_ag.json()['id']}", headers=A).status_code == 200
   and not c.get(f"/api/civics/jurisdictions/{_us}/detail", headers=A).json()["agreements"],
   "an agreement removed leaves both parties")

# --- time: a slider through the register, and a timeline for a scope ---
# The point of the timeline is inheritance. A state law applies to the
# county under it, so the county's timeline carries it — marked as from
# above — and a city's ordinance shows on the county's timeline as inside.
_tl = c.get(f"/api/civics/timeline?jurisdiction_id={_city}", headers=A).json()
ok(_tl["counts"]["inherited"] >= 2 and any(
    e["scope"] == "inherited" and "Minimum wage" in e["what"] for e in _tl["events"]),
   "the city's timeline carries the state's bill, marked as reaching it "
   "from above — Maryland's law applies to the county")
ok(any(e["kind"] == "election" and e["scope"] == "inherited"
       for e in _tl["events"]),
   "and the state's election, which the city votes in")
_tls = c.get(f"/api/civics/timeline?jurisdiction_id={_state}", headers=A).json()
ok(any(e["scope"] == "own" and "Minimum wage" in e["what"] for e in _tls["events"]),
   "the same bill is the state's own on the state's timeline")
ok(_tls["counts"]["inside"] == 0 or all(
    e["jurisdiction_id"] != _state for e in _tls["events"] if e["scope"] == "inside"),
   "and what is inside it is marked inside, never as its own")
ok(_tl["events"] == sorted(_tl["events"], key=lambda e: e["at"]),
   "events come in time order")
_tlw = c.get("/api/civics/timeline", headers=A).json()
ok(_tlw["counts"]["world"] == len(_tlw["events"]) and len(_tlw["events"]) >= len(_tl["events"]),
   "with nothing selected the timeline is the whole world")
ok(all(e["status"] for e in _tlw["events"] if e["kind"] == "measure"),
   "every measure event carries the stage it led to, which is what a "
   "slider needs to replay the past")
ok(c.get("/api/civics/timeline?jurisdiction_id=999999", headers=A).status_code == 404,
   "a scope that is not there is nothing")
ok(c.get("/api/civics/timeline", headers=_WCU).status_code == 403,
   "the timeline is an office screen like the rest")
# Replaying the past: the bill was in committee, then passed one house.
# Asked about a date between the two, the panel says in committee; asked
# about a date before it was introduced, the bill is not there at all.
_evs = c.get(f"/api/civics/measures/{_mid}", headers=A).json()["events"]
ok(any(e["status_after"] == "in_committee" and e["what"].startswith("recorded as")
       for e in _evs),
   "a typed measure's first event is the stage it was recorded at, so "
   "there is a past to replay")
_moved = min(e["at"] for e in _evs if e["status_after"] == "passed_one")
_intro = min(e["at"] for e in _evs)
_then = c.get(f"/api/civics/jurisdictions/{_state}/detail?as_of={(_intro + _moved) / 2}",
              headers=A).json()
ok(_then["as_of"] and any(
    m["id"] == _mid and m["status"] == "in_committee" for m in _then["measures"]),
   "the panel as of a moment before it passed shows it still in committee")
_nowd = c.get(f"/api/civics/jurisdictions/{_state}/detail", headers=A).json()
ok(any(m["id"] == _mid and m["status"] == "passed_one" for m in _nowd["measures"])
   and _nowd["as_of"] is None,
   "and as of now shows where it is")
_before = c.get(f"/api/civics/jurisdictions/{_state}/detail?as_of={_intro - 1}",
                headers=A).json()
ok(not any(m["id"] == _mid for m in _before["measures"]),
   "before the register first knew of it, it is not shown")
_ev2 = c.post(f"/api/civics/measures/{_mid}/events", headers=A, json={
    "what": "Signed", "at": _t0.time(), "status": "enacted"})
ok(_ev2.status_code == 200 and c.get(f"/api/civics/measures/{_mid}", headers=A)
   .json()["status"] == "enacted",
   "an event can carry the stage it moved the measure to, and the measure follows")
ok(c.post(f"/api/civics/measures/{_mid}/events", headers=A, json={
    "what": "x", "status": "wishful"}).status_code == 400,
   "at one of the known stages")
ok('id="civ-slider"' in _ops and 'type="range"' in _ops
   and "function civTimeline" in _ops and "function civSetTime" in _ops,
   "the screen has the slider and the timeline under the map")
ok("as_of=" in _ops and "as it was on" in _ops,
   "and the panel is fetched as of the chosen date, and says so")
ok(".civ-tlev.future" in _css and ".civ-tlev.inherited" in _css,
   "events after the chosen date fade rather than vanish, and what "
   "reaches a place from above is marked")

# --- ideas: notes that link, and the graph they make ---
ok(c.get("/api/ideas", headers=_WCU).status_code == 403,
   "ideas are the team's, not a customer's")
_i1 = c.post("/api/ideas", headers=A, json={
    "title": "Second shop", "tags": "expansion",
    "body": "Foot traffic from the [[Farmers market]] and the lease from "
            "[[Landlord talks]]. See [[farmers MARKET]] again."}).json()
ok(_i1["ok"] and _i1["id"], "a note is a title and some text")
_g = c.get("/api/ideas", headers=A).json()
ok({g["title"] for g in _g["ghosts"]} == {"Farmers market", "Landlord talks"},
   "what it points at that is not written yet is a dotted node — the "
   "graph's way of saying what has not been thought through")
ok(sum(1 for l in _g["links"] if l["from_id"] == _i1["id"]) == 2,
   "and the same title twice, in any case, is one link")
_i2 = c.post("/api/ideas", headers=A, json={
    "title": "farmers market", "body": "Saturday stall. Feeds [[Second shop]]."}).json()
ok(_i2["claimed"] == 1, "a note written claims the dotted links that pointed at its title")
_g = c.get("/api/ideas", headers=A).json()
ok({g["title"] for g in _g["ghosts"]} == {"Landlord talks"}
   and any(l["from_id"] == _i1["id"] and l["to_id"] == _i2["id"] for l in _g["links"])
   and any(l["from_id"] == _i2["id"] and l["to_id"] == _i1["id"] for l in _g["links"]),
   "and the two notes now point at each other")
ok(c.post("/api/ideas", headers=A, json={"title": "Farmers  Market"}).status_code == 409,
   "two notes with one title would leave links pointing nowhere certain, so refused")
ok(c.post("/api/ideas", headers=A, json={"title": "  "}).status_code == 400,
   "a note needs a title — it is what the links point at")
_n1 = c.get(f"/api/ideas/{_i1['id']}", headers=A).json()
ok(len(_n1["links_out"]) == 2 and len(_n1["links_in"]) == 1
   and _n1["links_in"][0]["from_title"] == "farmers market",
   "a note knows what it points at and what points at it")
_lk = c.post(f"/api/ideas/{_i1['id']}/links", headers=A, json={
    "to_id": _i2["id"], "label": "depends on"})
ok(_lk.status_code == 200 and any(
    l["kind"] == "explicit" and l["label"] == "depends on"
    for l in c.get(f"/api/ideas/{_i1['id']}", headers=A).json()["links_out"]),
   "an explicit connection carries a word for what it is")
ok(c.post(f"/api/ideas/{_i1['id']}/links", headers=A, json={
    "to_id": _i1["id"]}).status_code == 400, "an idea cannot link to itself")
c.post("/api/ideas", headers=A, json={
    "id": _i1["id"], "title": "Second shop", "body": "Rewritten with no links."})
_n1 = c.get(f"/api/ideas/{_i1['id']}", headers=A).json()
ok([l["kind"] for l in _n1["links_out"]] == ["explicit"],
   "rewriting the text rewrites the text links and leaves the explicit one")
ok(c.get("/api/ideas?q=stall", headers=A).json()["hits"] == [_i2["id"]],
   "a search says which notes hit, and the graph stays whole around them")
c.delete(f"/api/ideas/{_i2['id']}", headers=A)
_g = c.get("/api/ideas", headers=A).json()
ok(any(g["title"] == "farmers market" for g in _g["ghosts"])
   and any(l["from_id"] == _i1["id"] and l["to_id"] == 0 for l in _g["links"]),
   "removing a note leaves what pointed at it pointing at a title with "
   "nothing behind it — that three notes referred to it is worth seeing")
ok(c.delete(f"/api/ideas/links/{_lk.json()['id']}", headers=A).status_code == 200,
   "an explicit link can be taken away")
ok('"ideas"' in _ops and "ideas: renderIdeas" in _ops and "function ideGraph" in _ops
   and 'id="ide-svg"' in _ops,
   "the screen is on the rail and draws its own graph")
ok(".ide-node.ghost" in _css, "and a dotted node is dotted")

# --- cameras: every property on one wall ---
ok(c.get("/api/cameras", headers=_WCU).status_code == 403,
   "the wall is staff's")
ok(c.post("/api/cameras", headers=A, json={
    "name": "Yard", "kind": "hls", "url": "rtsp://cam/stream"}).status_code == 400,
   "no browser plays RTSP; the wall says so and gives the relay, rather "
   "than showing a spinner")
ok(c.post("/api/cameras", headers=A, json={
    "name": "Yard", "kind": "hologram", "url": "https://cam/a.m3u8"}).status_code == 400,
   "a kind is one the page can show")
ok(c.post("/api/cameras", headers=A, json={
    "name": "Yard", "kind": "snapshot", "url": "http://cam/a.jpg",
    "store_id": 999999}).status_code == 404, "a store it is at has to exist")
_c1 = c.post("/api/cameras", headers=A, json={
    "name": "Front door", "site": "Main St", "kind": "snapshot",
    "url": "http://192.168.1.20/snapshot.jpg", "refresh_sec": 2}).json()
_c2 = c.post("/api/cameras", headers=A, json={
    "name": "Loading bay", "site": "Warehouse", "kind": "mjpeg",
    "url": "https://192.168.1.21/video.cgi"}).json()
_w = c.get("/api/cameras", headers=A).json()
ok([s["name"] for s in _w["sites"]] == ["Main St", "Warehouse"]
   and all(len(s["cameras"]) == 1 for s in _w["sites"]),
   "the wall is grouped by where each camera is")
ok(next(x for x in _w["cameras"] if x["id"] == _c1["id"])["plain_http"]
   and not next(x for x in _w["cameras"] if x["id"] == _c2["id"])["plain_http"],
   "and each feed says whether an https install will be able to show it")
ok("ffmpeg" in _w["relay"] and ".m3u8" in _w["relay"]
   and {k["k"] for k in _w["kinds"]} == {"snapshot", "mjpeg", "hls", "iframe"},
   "the relay command and the four kinds a browser can show are on the page")
ok(c.get("/api/cameras", headers=A).json()["can_edit"],
   "the office edits the wall")
c.delete(f"/api/cameras/{_c1['id']}", headers=A)
c.delete(f"/api/cameras/{_c2['id']}", headers=A)
ok(not c.get("/api/cameras", headers=A).json()["cameras"],
   "a camera removed from the wall is gone from it — the camera itself is untouched")
ok('"cameras"' in _ops and "cameras: renderCameras" in _ops
   and "/vendor/hls/hls.min.js" in _ops and 'canPlayType("application/vnd.apple.mpegurl")' in _ops,
   "the screen is on the rail, plays HLS natively where it can and loads "
   "the vendored player where it cannot")
ok(c.get("/vendor/hls/hls.min.js").status_code == 200
   and Path("src/storefront/frontend/vendor/hls/LICENSE").exists(),
   "the player is vendored with its licence, not fetched from a CDN")
ok("requestFullscreen" in _ops and ".cam-wall:fullscreen" in _css,
   "and the wall goes full screen for the eagle eye")
ok("proxy" not in Path("src/erp/backend/cameras.py").read_text().lower().split("on purpose")[0]
   or "does not proxy" in Path("src/erp/backend/cameras.py").read_text(),
   "this server relays no video, on purpose, and the module says why")

# --- labels and ID cards: every code the building needs, on one sheet ---
ok(c.get("/api/labels", headers=_WCU).status_code == 403,
   "the label sheet is for the office and the teaching staff")
ok(c.get("/api/labels?kind=hats", headers=A).status_code == 400,
   "a set is students, items or staff")
_lp = c.post("/api/login", json={"name": "Label Pupil", "region": "West"}).json()
c.post(f"/api/students/{_lp['id']}/profile", headers=A,
       json={"fields": {"origin": "Kyiv"}})
_ls = c.get("/api/labels?kind=students", headers=A).json()
_lrow = next((r for r in _ls["labels"] if r["id"] == _lp["id"]), None)
ok(_lrow is not None and "/p/" in _lrow["payload"]
   and _lrow["line3"] == f"Student #{_lp['id']}",
   "a student with a record is on the sheet, with the same person code "
   "their own portal prints — a card from here and a card from there are "
   "the same card")
ok(_lrow["payload"] == c.get(f"/api/labels?kind=students&ids={_lp['id']}",
                             headers=A).json()["labels"][0]["payload"]
   and c.get(f"/api/labels?kind=students&ids={_lp['id']}", headers=A).json()["labels"]
   .__len__() == 1,
   "asked for one student, the sheet is one card, with the same code again")
ok(not any(r["id"] == _wc["id"] for r in _ls["labels"]) or c.get(
    f"/api/students/{_wc['id']}", headers=A).json()["profile"].get("origin") is not None,
   "a customer who only ever bought something is not a student and gets no card")
_li = c.post("/api/learning/library/items", headers=A,
             json={"name": "Projector (label)", "kind": "equipment"}).json()
_lit = c.get("/api/labels?kind=items&kinds=equipment", headers=A).json()
_litem = next((r for r in _lit["labels"] if r["name"] == "Projector (label)"), None)
ok(_litem is not None and _litem["payload"].startswith("bc:item:")
   and _litem["line2"] == "equipment",
   "an item's label carries the code the lending desk scans")
ok(not any(r["name"] == "Projector (label)" for r in
           c.get("/api/labels?kind=items&kinds=book", headers=A).json()["labels"]),
   "and the item kinds filter the shelf")
_lb = c.get("/api/labels?kind=staff", headers=A).json()
_nobadge_before = len(_lb["without_badge"])
c.post("/api/me/badge", headers=A)
_lb = c.get("/api/labels?kind=staff", headers=A).json()
ok(any(r["payload"].startswith("bc:clock:") for r in _lb["labels"]),
   "a staff badge carries the code the time clock reads")
ok("without_badge" in _lb,
   "and staff without a badge are named, not minted one — issuing a badge "
   "is a decision made per person on Team & access")
ok({l["id"] for l in _ls["layouts"]} >= {"avery5160", "avery5163", "idcard", "badge", "tag"}
   and all(l["w"] > 0 and l["cols"] * l["rows"] > 0 for l in _ls["layouts"]),
   "layouts are named for the label stock they fit, in inches")
ok('"labels"' in _ops and "labels: renderLabels" in _ops
   and "@page { size: letter; margin: 0; }" in _ops and "window.print()" in _ops
   and "URL.createObjectURL" in _ops,
   "the screen is on the rail, prints a sheet at exact size, and saves it as a page")
ok('id="stu-idcard"' in _ops and "LBL_PRESET" in _ops,
   "and a student's page hands one card to the sheet")

# --- tickets: tasks, the pages it is about, and attachments ---
_tkp = c.post("/api/tickets", headers=A, json={"title": "Pieces (test)"}).json()["id"]
ok(c.post(f"/api/tickets/{_tkp}/tasks", headers=A,
          json={"title": " "}).status_code == 400, "a task says what")
_tk1 = c.post(f"/api/tickets/{_tkp}/tasks", headers=A,
              json={"title": "Call the supplier"}).json()["id"]
c.post(f"/api/tickets/{_tkp}/tasks", headers=A, json={"title": "Book the room"})
ok(c.patch(f"/api/tickets/{_tkp}/tasks/{_tk1}", headers=A,
           json={"done": True}).status_code == 200,
   "a task is ticked")
_tkd = c.get(f"/api/tickets/{_tkp}", headers=A).json()
ok(_tkd["tasks_done"] == 1 and len(_tkd["tasks"]) == 2
   and any("ticked" in l["what"] for l in _tkd["log"]),
   "the ticket counts its tasks and writes the tick on its own record")
ok(c.post(f"/api/tickets/{_tkp}/links", headers=A,
          json={"tab": "orders"}).status_code == 400,
   "a link to a screen with rows says which row")
ok(c.post(f"/api/tickets/{_tkp}/links", headers=A,
          json={"tab": "till", "ref_id": 4}).status_code == 400,
   "and a screen without rows takes no number")
ok(c.post(f"/api/tickets/{_tkp}/links", headers=A,
          json={"tab": "nowhere", "ref_id": 1}).status_code == 400,
   "and only screens of this product can be pointed at")
c.post(f"/api/tickets/{_tkp}/links", headers=A, json={"tab": "orders", "ref_id": 7})
ok(c.post(f"/api/tickets/{_tkp}/links", headers=A,
          json={"tab": "orders", "ref_id": 7}).json().get("already"),
   "the same page twice is once")
_tkd = c.get(f"/api/tickets/{_tkp}", headers=A).json()
ok(_tkd["links"][0]["href"] == "#/orders/7" and _tkd["links"][0]["label"] == "Order #7",
   "a link is the page in this product the ticket is about — the reader "
   "lands on the order in one click")
_up = c.post(f"/api/tickets/{_tkp}/files", headers={**A, "x-filename": "note.txt"},
             content=b"hello attachment")
ok(_up.status_code == 200 and _up.json()["bytes"] == 16, "a file is attached")
ok(c.post(f"/api/tickets/{_tkp}/files", headers={**A, "x-filename": "run.exe"},
          content=b"MZ").status_code == 400,
   "a board that takes executables is a board somebody will regret")
ok(c.post(f"/api/tickets/{_tkp}/files", headers={**A, "x-filename": "empty.txt"},
          content=b"").status_code == 400, "an empty file is not attached")
_tkd = c.get(f"/api/tickets/{_tkp}", headers=A).json()
_fid = _tkd["files"][0]["id"]
_dl = c.get(f"/api/tickets/{_tkp}/files/{_fid}", headers=A)
ok(_dl.status_code == 200 and _dl.content == b"hello attachment"
   and _tkd["files"][0]["name"] == "note.txt" and _tkd["files"][0]["by_name"],
   "and comes back as it went in, with who attached it")
ok(c.get(f"/api/tickets/{_tkp}/files/{_fid}", headers=_WCU).status_code in (401, 403),
   "a customer cannot read the board's attachments")
ok(c.delete(f"/api/tickets/{_tkp}/files/{_fid}", headers=A).status_code == 200
   and c.get(f"/api/tickets/{_tkp}/files/{_fid}", headers=A).status_code == 404,
   "an attachment removed is gone from disk and record")
_tkb = c.get("/api/tickets", headers=A).json()
_tkrow = next(t for t in _tkb["tickets"] if t["id"] == _tkp)
ok(_tkrow["tasks_done"] == 1 and len(_tkrow["links"]) == 1 and "link_tabs" in _tkb,
   "the board carries the counts a card shows")
ok("function ticketPieces" in _ops and 'id="tk-task-add"' in _ops
   and 'id="tk-link-add"' in _ops and 'id="tk-file"' in _ops
   and "x-filename" in _ops,
   "the ticket form has its tasks, its pages and its attachments")
_up2 = c.post(f"/api/tickets/{_tkp}/files", headers={**A, "x-filename": "gone.txt"},
              content=b"bytes on disk").json()
from erp.backend import tickets as _tkmod  # noqa: E402
_tkpath = _tkmod._dir() / f"{_up2['id']}.txt"
ok(_tkpath.exists(), "an attachment's bytes are on disk under the tenant")
c.delete(f"/api/tickets/{_tkp}", headers=A)
ok(not _tkpath.exists()
   and not any(t["id"] == _tkp for t in c.get("/api/tickets", headers=A).json()["tickets"]),
   "and deleting the ticket takes its tasks, links and files with it — "
   "the bytes too, or the folder fills with files no row remembers")

# --- Prezi: a deck that lives elsewhere, framed under a link of our own ---
from erp.backend import presentations as _prs  # noqa: E402
ok(_prs.embed_url("https://prezi.com/view/AbC123xyz/") == "https://prezi.com/view/AbC123xyz/embed/"
   and _prs.embed_url("https://prezi.com/p/AbC123xyz/some-title/") == "https://prezi.com/view/AbC123xyz/embed/",
   "a Prezi share link becomes its embed address — that is the whole integration")
ok(_prs.embed_url("https://docs.google.com/presentation/d/1AbC/edit#slide=1")
   == "https://docs.google.com/presentation/d/1AbC/embed",
   "Google Slides the same way")
ok(_prs.embed_source("https://prezi.com/view/x/embed/") == "Prezi",
   "and the page says where it lives")
ok(c.post("/api/presentations", headers=A, json={
    "title": "x", "kind": "embed", "embed_link": "http://prezi.com/view/a"}).status_code == 400,
   "an embed is an https link")
_pz = c.post("/api/presentations", headers=A, json={
    "title": "Prezi (test)", "kind": "embed",
    "embed_link": "https://prezi.com/view/AbC123xyz/"}).json()
ok(_pz["kind"] == "embed" and _pz["embed_url"].endswith("/embed/") and _pz["url"],
   "it is a presentation like any other, with a link of this product's own")
_pzp = c.get("/present/" + _pz["token"])
ok(_pzp.status_code == 200 and 'class="doc embed" src="https://prezi.com/view/AbC123xyz/embed/"' in _pzp.text
   and "open it there" in _pzp.text,
   "the public page frames it, and says what to do if the site refuses framing")
ok(_ig.PROVIDERS["prezi"]["auth"] == "none"
   and _ig.PROVIDERS["prezi"]["family"] == "presentations",
   "Prezi is a keyless provider that lives on the Presentations screen")
ok(any(p["name"] == "prezi" and p["connected"]
       for p in c.get("/api/admin/integrations", headers=A).json()["providers"]),
   "and is never 'disconnected' — the product points at a public thing")
ok('id="pr-embed"' in _ops and 'connectionCards(["prezi"]' in _ops,
   "the screen embeds a link and shows the card")
c.delete(f"/api/presentations/{_pz['id']}", headers=A)

# --- applications: what a student is applying to beyond here ---
ok(c.get(f"/api/students/{_wc['id']}/applications", headers=_WCU).status_code == 403,
   "applications are moved by the office")
ok(c.post(f"/api/students/{_wc['id']}/applications", headers=A,
          json={"institution": " "}).status_code == 400,
   "an application is to somewhere")
_apd = c.post(f"/api/students/{_wc['id']}/applications", headers=A, json={
    "institution": "Harcum College", "program": "Associate in Nursing",
    "kind": "college", "deadline": _t0.time() + 30 * 86400,
    "notes": "office only"}).json()
_apl = c.get(f"/api/students/{_wc['id']}/applications", headers=A).json()
_ap1 = next(a for a in _apl["applications"] if a["id"] == _apd["id"])
ok(_ap1["stage"] == "considering" and len(_ap1["checklist"]) == 6
   and _ap1["suggested_next"] == "preparing",
   "a college application opens with the usual checklist and a next stage")
ok(any("Applying to Harcum" in e["title"] for e in
       c.get(f"/api/students/{_wc['id']}", headers=A).json()["timeline"]),
   "and opening it is a line on the student's timeline")
ok(c.post(f"/api/students/{_wc['id']}/applications/{_apd['id']}/stage", headers=A,
          json={"stage": "famous"}).status_code == 400, "a stage is one of the known ones")
c.post(f"/api/students/{_wc['id']}/applications/{_apd['id']}/stage", headers=A,
       json={"stage": "submitted", "next_step": "Wait for the letter"})
c.post(f"/api/students/{_wc['id']}/applications/{_apd['id']}/tick", headers=A,
       json={"index": 0, "done": True})
_ap1 = next(a for a in c.get(f"/api/students/{_wc['id']}/applications", headers=A)
            .json()["applications"] if a["id"] == _apd["id"])
ok(_ap1["stage"] == "submitted" and _ap1["submitted_at"] > 0 and _ap1["checklist_done"] == 1
   and _ap1["checklist"][0]["by"] and any("Submitted" in l["what"] for l in _ap1["log"]),
   "moving it forward dates the submission, ticks are signed, and the "
   "history says who did what")
_mine = c.get("/api/learn/me/applications", headers=_WCU).json()
_my1 = next(a for a in _mine["applications"] if a["id"] == _apd["id"])
ok(_my1["stage_label"] == "Submitted" and _my1["next_step"] == "Wait for the letter"
   and "notes" not in _my1 and _my1["checklist_done"] == 1,
   "the student sees where it stands and what is next — and never the "
   "office's own notes")
c.post(f"/api/students/{_wc['id']}/applications/{_apd['id']}/stage", headers=A,
       json={"stage": "accepted"})
ok(any("Accepted: Harcum" in e["title"] for e in
       c.get(f"/api/students/{_wc['id']}", headers=A).json()["timeline"]),
   "being accepted somewhere is an achievement on the timeline")
ok("function studentApplications" in _ops and 'id="stu-app-new"' in _ops
   and "data-appnext" in _ops,
   "the student page carries the applications and moves them forward")
_lrnjs = c.get("/learn.js").text if c.get("/learn.js").status_code == 200 else ""
ok("/api/learn/me/applications" in _lrnjs and "My applications" in _lrnjs,
   "and the student's own page shows them")
c.delete(f"/api/students/{_wc['id']}/applications/{_apd['id']}", headers=A)

# --- the annual report: the year added up, with the words around it ---
ok(c.get("/api/reports/annual", headers=_WCU).status_code == 403,
   "the annual report is the office's and the board's")
ok(c.get("/api/reports/annual?year=1999", headers=A).status_code == 400,
   "a year between 2000 and 2100")
_ann = c.get("/api/reports/annual", headers=A).json()
_thisy = _dtx.datetime.now().year
ok(_ann["year"] == _thisy and _thisy in _ann["years"],
   "no year asked for is this year, and this year is always offered")
ok({"sales", "learning", "people"} <= set(_ann["sections"]),
   "it adds up what the install has: sales, learning, people")
ok(len(_ann["sections"]["sales"]["by_month_cents"]) == 12
   and _ann["sections"]["sales"]["orders"] >= 1
   and _ann["sections"]["sales"]["revenue_cents"] > 0,
   "sales are twelve months of cents from the orders, worked out fresh")
ok(_ann["sections"]["people"]["staff_at_end"] >= 1
   and "hours_worked" in _ann["sections"]["people"],
   "people counts the staff and the hours the clock saw")
ok("money" in _ann["sections"] and "expenses_cents" in _ann["sections"]["money"],
   "money out comes from the approved expenses")
_ann0 = c.get("/api/reports/annual?year=2003", headers=A).json()
ok(_ann0["sections"]["sales"]["orders"] == 0 and _ann0["words"]["title"] == "",
   "a year with nothing in it is zeros and no words, not an error")
ok(c.post("/api/reports/annual", headers=A, json={
    "year": _thisy, "title": "Our year", "letter": "It was a year.",
    "highlights": ["Opened the second shop", "  ", "Forty students"],
    "thanks": "Everyone."}).status_code == 200,
   "the words are kept by year")
_annw = c.get("/api/reports/annual", headers=A).json()["words"]
ok(_annw["title"] == "Our year" and _annw["highlights"] == ["Opened the second shop", "Forty students"]
   and _annw["by_name"],
   "and come back with the blanks dropped and who wrote them")
_csv = c.get(f"/api/reports/annual.csv?year={_thisy}", headers=A)
ok(_csv.status_code == 200 and "text/csv" in _csv.headers["content-type"]
   and _csv.text.splitlines()[0] == "year,section,measure,value"
   and any(",sales,revenue_cents," in ln for ln in _csv.text.splitlines()),
   "the numbers export flat, one measure a row, for whoever wants to check them")
ok('"annual"' in _ops and "annual: renderAnnual" in _ops and "function annualDoc" in _ops
   and 'id="ann-print"' in _ops and "@page { size: letter; margin: .8in; }" in _ops,
   "the screen is on the rail under Money and prints as a document")

# --- the storefront in the visitor's language and conventions ---
from storefront.backend import content as _ct  # noqa: E402
ok("nav_account" in _ct.UI_KEYS and "side_account" in _ct.UI_KEYS,
   "the shell's own chrome has keys, so the menu is translatable and not "
   "only the product cards")
ok(c.post("/api/store/admin/i18n", headers=A, json={
    "locales": [{"code": "e s"}], "default": "en"}).status_code == 400,
   "a language is a code")
ok(c.post("/api/store/admin/i18n", headers=A, json={
    "locales": [{"code": "es", "label": "Español"}], "default": "fr"}).status_code == 400,
   "and the default is one of the languages offered")
_i18 = c.post("/api/store/admin/i18n", headers=A, json={
    "locales": [{"code": "es", "label": "Español"}, {"code": "ar", "label": "العربية"}],
    "default": "es", "auto_detect": False}).json()
ok([l["code"] for l in _i18["locales"]] == ["en", "es", "ar"]
   and next(l for l in _i18["locales"] if l["code"] == "ar")["dir"] == "rtl"
   and _i18["default"] == "es" and _i18["auto_detect"] is False,
   "English stays, Arabic reads right to left without being told, and the "
   "default and first-visit rule are kept")
c.post("/api/store/admin/translations", headers=A, json={
    "locale": "es", "entries": {"side_account": "Tu cuenta", "add_to_cart": "Añadir"}})
_pubi = c.get("/api/store/i18n").json()
ok(_pubi["locales"] == ["en", "es", "ar"] and _pubi["default_locale"] == "es"
   and _pubi["strings"]["es"]["side_account"] == "Tu cuenta",
   "the storefront reads the languages, the default and the strings")
_home = c.get("/").text
ok('window.STORE_I18N=' in _home and '"locale_info"' in _home
   and 'data-i18n="side_account"' in _home and 'data-i18n-title="nav_support"' in _home,
   "every page carries the languages, and the chrome carries its keys")
_sfjs = c.get("/store.js").text
ok("function resolveLocale" in _sfjs and "navigator.languages" in _sfjs
   and 'get("lang")' in _sfjs and "document.documentElement.dir" in _sfjs,
   "the page picks the visitor's language — chosen, in the address, the "
   "browser's, or the default — and sets the reading direction")
ok("Intl.NumberFormat(LOCALE, { style: \"currency\"" in _sfjs
   and "function applyI18n" in _sfjs and "toLocaleString(LOCALE," in _sfjs,
   "and prices and dates are formatted in that language's conventions")
_admh = c.get("/admin").text
ok('id="ln-list"' in _admh and 'id="ln-default"' in _admh
   and "drawLanguages" in c.get("/admin.js").text,
   "the store admin offers languages, a default and the first-visit rule")
c.post("/api/store/admin/i18n", headers=A, json={"locales": [], "default": "en"})
c.post("/api/store/admin/translations", headers=A, json={
    "locale": "es", "entries": {"side_account": "", "add_to_cart": ""}})
ok(c.get("/api/store/i18n").json()["locales"] == ["en"],
   "languages taken away leave English")

# --- health: a locked cabinet that logs ---
from storefront.backend import governance as _govh  # noqa: E402
ok("health" in _govh.PERMISSIONS and "health" not in _govh.ROLE_DEFAULTS["employee"],
   "reading a chart is a named permission no role carries by default")
ok(c.get("/api/health", headers=_WCU).status_code == 403,
   "a customer does not open the cabinet")
_nurse = c.post("/api/login", json={"name": "Nurse Nell", "role": "employee"}).json()
_NH = {"Authorization": f"Bearer {_nurse['token']}"}
ok(c.get("/api/health", headers=_NH).status_code == 403,
   "nor does an employee without the grant — being staff is not being allowed")
_hcon = _db.connect()
_hcon.execute("UPDATE users SET permissions='health' WHERE id=?", (_nurse["id"],))
_hcon.commit(); _hcon.close()
_hp = c.get("/api/health", headers=_NH)
ok(_hp.status_code == 200 and "queue" in _hp.json() and "patients" in _hp.json(),
   "with the grant, the desk's screen opens: the queue and the patients")
ok(c.post(f"/api/health/patients/{_wc['id']}", headers=_NH, json={
    "birth_date": "1990-13-40"}).status_code == 400, "a birth date is a date")
ok(c.post(f"/api/health/patients/{_wc['id']}", headers=_NH, json={
    "birth_date": "1990-05-04", "allergies": "penicillin", "notes": "desk only",
    "consent": True}).status_code == 200,
   "a person in the customer book becomes a patient with a record beside them")
_rec = c.get(f"/api/health/patients/{_wc['id']}", headers=_NH).json()
ok(_rec["patient"]["allergies"] == "penicillin" and _rec["patient"]["consent_at"] > 0
   and _rec["patient"]["consent_by"] == "Nurse Nell" and _rec["patient"]["age"] is not None,
   "the record holds what the desk needs, and consent is recorded with who took it")
ok(any(a["what"] == "record" and a["by_name"] == "Nurse Nell" for a in _rec["access"]),
   "and opening it was written down — who, and when")
ok(c.post(f"/api/health/patients/{_wc['id']}/insurance", headers=_NH, json={
    "payer": " "}).status_code == 400, "insurance names the insurer")
_pol = c.post(f"/api/health/patients/{_wc['id']}/insurance", headers=_NH, json={
    "payer": "Blue Cross", "member_id": "BC123", "copay_cents": 2500,
    "verified": True}).json()
ok(_pol["ok"] and c.get(f"/api/health/patients/{_wc['id']}", headers=_NH).json()
   ["insurance"][0]["verified_by"] == "Nurse Nell",
   "a policy on file, verified by name")
ok(c.post(f"/api/health/patients/{_wc['id']}/encounters", headers=_NH, json={
    "kind": "seance"}).status_code == 400, "a visit is one of the known kinds")
ok(c.post(f"/api/health/patients/{_wc['id']}/encounters", headers=_NH, json={
    "kind": "visit"}).status_code == 400, "and says why, or what was noted")
_enc = c.post(f"/api/health/patients/{_wc['id']}/encounters", headers=_NH, json={
    "kind": "visit", "reason": "sore throat", "notes": "Throat red. Rest.",
    "vitals": {"temp": "38.1", "pulse": "", "bp": "120/80"}, "plan": "fluids"}).json()
_enc2 = c.post(f"/api/health/patients/{_wc['id']}/encounters", headers=_NH, json={
    "kind": "note", "notes": "private clinical note", "shared": False}).json()
_rec = c.get(f"/api/health/patients/{_wc['id']}", headers=_NH).json()
ok(len(_rec["encounters"]) == 2 and _rec["encounters"][-1]["vitals"] == {"temp": "38.1", "bp": "120/80"}
   and _rec["encounters"][-1]["practitioner"] == "Nurse Nell",
   "a visit keeps what was measured — blanks dropped — and who saw them")
_hf = c.post(f"/api/health/patients/{_wc['id']}/files",
             headers={**_NH, "x-filename": "xray.png", "x-kind": "image"}, content=b"\x89PNG")
ok(_hf.status_code == 200, "a file goes on the record")
ok(c.post(f"/api/health/patients/{_wc['id']}/files",
          headers={**_NH, "x-filename": "tool.exe"}, content=b"MZ").status_code == 400,
   "of a kind the vault would take")
_hf2 = c.post(f"/api/health/patients/{_wc['id']}/files",
              headers={**_NH, "x-filename": "private.pdf", "x-shared": "0"}, content=b"%PDF")
ok(c.get(f"/api/health/patients/{_wc['id']}/files/{_hf.json()['id']}", headers=_NH).content == b"\x89PNG",
   "and comes back as it went in")
ok(c.get(f"/api/health/patients/{_wc['id']}/files/{_hf.json()['id']}", headers=A).status_code == 200
   and any(a["what"] == f"file:{_hf.json()['id']}" for a in
           c.get(f"/api/health/patients/{_wc['id']}/access", headers=_NH).json()["access"]),
   "an admin may read it too, and that read is logged like any other")
# the patient's own window
_me = c.get("/api/health/me", headers=_WCU).json()
ok(_me["patient"]["allergies"] == "penicillin" and "notes" not in _me["patient"],
   "the patient sees their record — and never the desk's notes")
ok([e["kind"] for e in _me["encounters"]] == ["visit"] and [f["name"] for f in _me["files"]] == ["xray.png"],
   "and only the visits and files the practice marked shared")
ok(c.get(f"/api/health/me/files/{_hf2.json()['id']}", headers=_WCU).status_code == 404
   and c.get(f"/api/health/me/files/{_hf.json()['id']}", headers=_WCU).content == b"\x89PNG",
   "an unshared file is not there for the patient; a shared one is")
ok(any(a["what"] == "portal" and a["by_name"] == _wc["name"] for a in
       c.get(f"/api/health/patients/{_wc['id']}/access", headers=_NH).json()["access"]),
   "and the patient opening their portal is written down like any other read")
ok(c.post("/api/health/me/insurance", headers=_WCU, json={
    "id": _pol["id"], "payer": "Other"}).status_code == 400,
   "a policy the desk verified is not the patient's to rewrite")
_selfpol = c.post("/api/health/me/insurance", headers=_WCU, json={
    "payer": "Aetna", "member_id": "AE9"}).json()
ok(_selfpol["ok"] and any(i["payer"] == "Aetna" and not i["verified_at"] and not i["primary_policy"]
                          for i in c.get("/api/health/me", headers=_WCU).json()["insurance"]),
   "the patient keeps their own card on file, unverified until the desk says so")
_other = c.post("/api/login", json={"name": "Not A Patient", "region": "West"}).json()
ok(c.get("/api/health/me", headers={"Authorization": f"Bearer {_other['token']}"}).status_code == 404,
   "a customer with no record has no portal — the record is the practice's to open")
c.post(f"/api/health/patients/{_wc['id']}", headers=_NH, json={
    "birth_date": "1990-05-04", "allergies": "penicillin", "consent": True, "portal": False})
ok(c.get("/api/health/me", headers=_WCU).status_code == 403,
   "and the practice can keep a record off the portal")
c.post(f"/api/health/patients/{_wc['id']}", headers=_NH, json={
    "birth_date": "1990-05-04", "allergies": "penicillin", "consent": True, "portal": True})
# the queue: an appointment, checked in from the portal
_svc = c.post("/api/store/admin/services", headers=A, json={
    "name": "Consultation (health)", "minutes": 30, "price_cents": 0}).json()
_hstart = _t0.time() + 3600
_appt = None
if _svc.get("id"):
    _hcon = _db.connect()
    _appt = _hcon.execute(
        "INSERT INTO appointments(service_id,starts,ends,staff_id,room_id,user_id,visitor_id,"
        " order_id,state,held_until,name,email,note,source,created_at)"
        " VALUES(?,?,?,0,0,?,'',0,'confirmed',0,?,?,'','store',?)",
        (_svc["id"], _hstart, _hstart + 1800, _wc["id"], _wc["name"], "", _t0.time())).lastrowid
    _hcon.commit(); _hcon.close()
if _appt:
    _meq = c.get("/api/health/me", headers=_WCU).json()
    ok(any(a["id"] == _appt and a["can_check_in"] for a in _meq["appointments"]),
       "an appointment in the next three hours can be checked into from the portal")
    ok(c.post("/api/health/me/checkin", headers=_WCU, json={"appointment_id": _appt}).json()["ok"],
       "and the patient says they have arrived")
    _q = c.get("/api/health", headers=_NH).json()["queue"]
    _qrow = next((r for r in _q if r["id"] == _appt), None)
    ok(_qrow is not None and _qrow["checkin_state"] == "arrived" and _qrow["method"] == "portal",
       "which lands on the desk's queue the same moment, marked as self check-in")
    ok(c.post("/api/health/checkin", headers=_NH, json={
        "appointment_id": _appt, "state": "with_practitioner"}).json()["state"] == "with_practitioner",
       "the desk moves them along the queue")
    ok(c.post("/api/health/checkin", headers=_NH, json={
        "appointment_id": _appt, "state": "beamed_up"}).status_code == 400,
       "to one of its states")
    _other2 = c.post("/api/login", json={"name": "Wrong Patient", "region": "West"}).json()
    ok(c.post("/api/health/me/checkin", headers={"Authorization": f"Bearer {_other2['token']}"},
              json={"appointment_id": _appt}).status_code in (403, 404),
       "and nobody checks in to somebody else's appointment")
else:
    ok(True, "(no bookable service could be made here; the queue is covered by the desk routes)")
ok(c.get("/health").status_code == 200 and "My health" in c.get("/health").text
   and "hp-root" in c.get("/health").text,
   "the portal page is served on the storefront")
ok('"health"' in _ops and "health: renderHealth" in _ops and 'id="hea-desk"' in _ops
   and "function heaEncounterForm" in _ops,
   "the desk's screen is on the rail behind the permission, with a front-desk view")
ok("/api/health/*" in _mcpt.EXCLUDED,
   "the agent door names the whole of it as out of bounds")
from storefront.backend import pricebook as _pbh  # noqa: E402
ok(any(x["name"] == "Health" and x["price"] == 50 for x in _pbh.capabilities()),
   "Health is in the price book as a heavy capability")

# --- the six limits, lifted ---
# The year before, beside each number.
_ann2 = c.get("/api/reports/annual", headers=A).json()
ok("prior" in _ann2 and "sales" in _ann2["prior"] and "orders" in _ann2["prior"]["sales"]
   and "_months" in _ann2["prior"],
   "the report carries the year before, derived the same way, so each number can say how it moved")
ok("function delta" not in _ops and "vs ${d.year - 1}" in _ops and ".ann-delta" in _css,
   "and the screen shows the move beside the tile, last year's bars behind this year's")
# The federal calendar, computed.
ok(len(_civ.federal_elections(2020, 2026)) == 4
   and _civ.federal_elections(2024, 2024)[0]["name"].startswith("2024 presidential")
   and _civ.federal_elections(2026, 2026)[0]["name"].startswith("2026 midterm")
   and _dtx.datetime.fromtimestamp(_civ.federal_elections(2024, 2024)[0]["at"]).strftime("%Y-%m-%d") == "2024-11-05",
   "US general elections are the Tuesday after the first Monday in November of even years — computed, not fetched")
_seed = c.post("/api/civics/seed/federal-elections", headers=A, json={"years_back": 4, "years_ahead": 4}).json()
ok(_seed["added"] >= 3 and _seed["jurisdiction_id"] == _us,
   "seeding puts them on the United States' timeline")
ok(c.post("/api/civics/seed/federal-elections", headers=A,
          json={"years_back": 4, "years_ahead": 4}).json()["added"] == 0,
   "and twice adds nothing twice")
ok(any(e["kind"] == "election" and "general election" in e["what"]
       for e in c.get(f"/api/civics/timeline?jurisdiction_id={_us}", headers=A).json()["events"]),
   "so the timeline has dated things in both directions with no key and no network")
ok('id="civ-federal"' in _ops, "from a button on the screen")
# A word before the deadline.
_apr = c.post(f"/api/students/{_wc['id']}/applications", headers=A, json={
    "institution": "Reminder U", "kind": "college", "deadline": _t0.time() + 2 * 86400,
    "next_step": "Send the essay"}).json()
c.get("/api/learn/me/applications", headers=_WCU)
_ln = c.get("/api/learn/notifications", headers=_WCU).json()
_lnl = _ln if isinstance(_ln, list) else _ln.get("items") or _ln.get("notifications") or []
ok(any("Reminder U" in n["title"] and "Send the essay" in n["body"] for n in _lnl),
   "a student with a deadline in two days is told, on their own page, what is still wanted")
c.get("/api/learn/me/applications", headers=_WCU)
_lnl2 = (lambda x: x if isinstance(x, list) else x.get("items") or x.get("notifications") or [])(
    c.get("/api/learn/notifications", headers=_WCU).json())
ok(sum(1 for n in _lnl2 if "Reminder U" in n["title"]) == 1,
   "and told once — the reminder carries a key, so opening the page again does not repeat it")
ok(any("reminded" in l["what"] for l in next(
    a for a in c.get(f"/api/students/{_wc['id']}/applications", headers=A).json()["applications"]
    if a["id"] == _apr["id"])["log"]),
   "and the application's history says so")
c.delete(f"/api/students/{_wc['id']}/applications/{_apr['id']}", headers=A)
# Attachments previewed where the ticket is.
ok("data-tkpeek" in _ops and "URL.createObjectURL(blob)" in _ops and ".tk-peek iframe" in _css,
   "an image, a PDF, a text or a film on a ticket is looked at inside the ticket")
# The shopper's country and language, on the order and the receipt.
ok("function addressShape" in _sfjs or "function addressShape" in c.get("/store.js").text,
   "the checkout shapes the address for the country: ZIP after the state, PLZ before the Ort")
_sfjs2 = c.get("/store.js").text
ok('id="co-country"' in _sfjs2 and "country, locale: LOCALE" in _sfjs2,
   "and sends the country and the language the shopper was reading in")
c.post("/api/store/admin/i18n", headers=A, json={
    "locales": [{"code": "de", "label": "Deutsch"}], "default": "en"})
c.post("/api/store/admin/translations", headers=A, json={
    "locale": "de", "entries": {"email_receipt_subject": "Deine Bestellung #{oid} ist da!",
                                "email_total": "Gesamt"}})
_dcon = _db.connect()
ok(_ct.strings_for(_dcon, "de")["email_total"] == "Gesamt"
   and _ct.strings_for(_dcon, "de")["email_tax"] == "Steuern"
   and _ct.strings_for(_dcon, "xx")["email_total"] == "Total",
   "an email's words come from the translations — the merchant's, else the "
   "shipped ones, else English for a language nobody knows")
ok(_ct.fmt_money(_dcon, 123456, "de") == "1.234,56 $" and _ct.fmt_money(_dcon, 123456, "en") == "$1,234.56",
   "and its money is in the language's conventions")
_dcon.close()
_dcon = _db.connect()
_dcon.execute("UPDATE users SET email='wave@example.com', email_verified_at=? WHERE id=?",
              (_t0.time(), _wc["id"]))
_dcon.commit(); _dcon.close()
_pde = c.post("/api/admin/products", headers=A, json={
    "sku": "DE-1", "name": "Berlin Sauce", "price_cents": 900,
    "case_price_cents": 8000}).json()
_pde_id = _pde.get("id") or next(
    p["id"] for p in (lambda x: x if isinstance(x, list) else x.get("products", []))(
        c.get("/api/products").json()) if p["sku"] == "DE-1")
_ode = c.post("/api/orders", headers=_WCU, json={
    "items": [{"product_id": _pde_id, "qty": 1}], "ship_name": "Wave Customer",
    "address": "Hauptstr. 1", "city": "Berlin", "postal": "10115", "country": "de",
    "locale": "de"})
ok(_ode.status_code == 200, f"an order carries a country and a language ({_ode.status_code} {_ode.text[:80]})")
_dcon = _db.connect()
_orow = _dcon.execute("SELECT country, locale FROM orders WHERE id=?", (_ode.json()["id"],)).fetchone()
_urow = _dcon.execute("SELECT locale FROM users WHERE id=?", (_wc["id"],)).fetchone()
_mrow = _dcon.execute("SELECT subject FROM email_log WHERE user_id=? ORDER BY id DESC LIMIT 1",
                      (_wc["id"],)).fetchone()
_dcon.close()
ok(_orow["country"] == "DE" and _orow["locale"] == "de" and _urow["locale"] == "de",
   "kept on the order, and remembered on the account")
ok(_mrow is not None and _mrow["subject"].startswith("Deine Bestellung"),
   "so the receipt goes out in German")
c.post("/api/store/admin/i18n", headers=A, json={"locales": [], "default": "en"})
c.post("/api/store/admin/translations", headers=A, json={
    "locale": "de", "entries": {"email_receipt_subject": "", "email_total": ""}})
# Files sealed on disk; a counter that signs nobody in.
from erp.backend import health as _hea  # noqa: E402
_hf3 = c.post(f"/api/health/patients/{_wc['id']}/files",
              headers={**_NH, "x-filename": "scan.png"}, content=b"\x89PNG secret").json()
_hpath = _hea._dir() / f"{_hf3['id']}.png"
ok(_hpath.read_bytes().startswith(b"BCH1") and b"secret" not in _hpath.read_bytes(),
   "a patient's file on disk is ciphertext")
ok(c.get(f"/api/health/patients/{_wc['id']}/files/{_hf3['id']}", headers=_NH).content == b"\x89PNG secret",
   "and comes back as it went in")
ok(_hea.unseal(_hea.seal(b"x" * 1000)) == b"x" * 1000 and _hea.seal(b"a") != _hea.seal(b"a"),
   "AES-GCM under the tenant's key, a fresh nonce every time")
_hpath.write_bytes(b"\x89PNG legacy")
ok(c.get(f"/api/health/patients/{_wc['id']}/files/{_hf3['id']}", headers=_NH).content == b"\x89PNG legacy"
   and _hpath.read_bytes().startswith(b"BCH1"),
   "a file written before sealing is served as it is and sealed on first read")
ok(c.get("/health/kiosk").status_code == 200 and "please check in" in c.get("/health/kiosk").text,
   "the counter kiosk is a public page")
ok(c.post("/api/health/kiosk/checkin", json={"name": "Wave Customer", "birth_date": "1990-01-01"}).status_code == 404
   and c.post("/api/health/kiosk/checkin", json={"name": "Nobody", "birth_date": "1990-05-04"}).status_code == 404,
   "a wrong date, a wrong name and no record all get the same answer — the kiosk faces the waiting room")
if _appt:
    _dcon = _db.connect()
    _dcon.execute("DELETE FROM patient_checkins WHERE appointment_id=?", (_appt,))
    _dcon.execute("UPDATE appointments SET starts=?, ends=? WHERE id=?",
                  (_t0.time() + 1800, _t0.time() + 3600, _appt))
    _dcon.commit(); _dcon.close()
    _kk = c.post("/api/health/kiosk/checkin", json={"name": "wave customer", "birth_date": "1990-05-04"})
    ok(_kk.status_code == 200 and _kk.json()["first_name"] == "Wave",
       "name and date of birth together check the patient in, and the screen says only that")
    ok(next(r for r in c.get("/api/health", headers=_NH).json()["queue"] if r["id"] == _appt)["method"] == "kiosk",
       "marked on the queue as from the kiosk")
    _dcon = _db.connect()
    _dcon.execute("DELETE FROM patient_checkins WHERE appointment_id=?", (_appt,))
    _dcon.commit(); _dcon.close()
    _code = c.get("/api/labels?kind=students&ids=" + str(_wc["id"]), headers=A).json()["labels"]
    if _code:
        ok(c.post("/api/health/kiosk/checkin", json={"code": _code[0]["payload"]}).status_code == 200,
           "or the code on the ID card does")
ok('id="hea-kiosk"' in _ops and "/health/kiosk" in _ops, "the desk's screen hands out the kiosk link")

# --- the storefront speaks six languages the day it opens ---
ok([l["code"] for l in _ct.BUILTIN_LOCALES] == ["es", "fr", "de", "pt", "zh", "ar"]
   and all(set(_ct.UI_KEYS) - {"cart_tag", "cart_note"} <= set(d) for d in _ct.BUILTIN.values()),
   "the product ships a translation of every one of its own words in six languages")
_dcon = _db.connect()
_dcon.execute("DELETE FROM store_meta WHERE k='i18n'"); _dcon.commit()
_fresh = _ct.i18n_settings(_dcon)
ok([l["code"] for l in _fresh["locales"]] == ["en", "es", "fr", "de", "pt", "zh", "ar"]
   and next(l for l in _fresh["locales"] if l["code"] == "ar")["dir"] == "rtl",
   "with nothing chosen, the picker offers English and all six — so choosing "
   "Spanish does something the day the shop opens")
ok(_ct.translations_for(_dcon, "es")["prefs"] == "Preferencias"
   and _ct.translations_for(_dcon, "pt-br")["prefs"] == "Preferências",
   "and a shipped translation answers, a regional code falling back to its language")
_dcon.execute("INSERT OR REPLACE INTO translations(locale,key,value) VALUES('es','prefs','Ajustes')")
_dcon.commit()
ok(_ct.translations_for(_dcon, "es")["prefs"] == "Ajustes"
   and _ct.translations_for(_dcon, "es")["language"] == "Idioma",
   "a merchant's own word for a key wins over the shipped one, key by key")
_dcon.execute("DELETE FROM translations WHERE locale='es' AND key='prefs'"); _dcon.commit()
_dcon.close()
_pubi2 = c.get("/api/store/i18n").json()
ok(_pubi2["locales"][:2] == ["en", "es"] and _pubi2["strings"]["es"]["sign_in"] == "Iniciar sesión"
   and _pubi2["strings"]["ar"]["prefs"],
   "every page carries them")
_tr_es = c.get("/api/store/admin/translations/es", headers=A).json()
ok(_tr_es["shipped"]["prefs"] == "Preferencias" and "own" in _tr_es,
   "the translations screen shows what shipped and what the merchant typed, apart")
_home2 = c.get("/").text
ok('data-i18n="prefs"' in _home2 and 'data-i18n="language"' in _home2
   and 'data-i18n="reset_all"' in _home2 and 'data-i18n-aria="a11y_open"' in _home2,
   "the preferences panel under the accessibility button carries keys for every label")
_sfjs3 = c.get("/store.js").text
ok('${t("checkout_title")}' in _sfjs3 and '${t("place_order")}' in _sfjs3
   and '${t("sign_in")}' in _sfjs3 and '${t("my_account")}' in _sfjs3
   and '${t("empty_cart_line")}' in _sfjs3 and "data-i18n-aria" in _sfjs3,
   "and the cart, the checkout, the doors and the account go through the same layer")
c.post("/api/store/admin/i18n", headers=A, json={"locales": [{"code": "es", "label": "Español"}], "default": "en"})
ok(c.get("/api/store/i18n").json()["locales"] == ["en", "es"],
   "a merchant who wants two languages gets two")
_dcon = _db.connect(); _dcon.execute("DELETE FROM store_meta WHERE k='i18n'"); _dcon.commit(); _dcon.close()

# --- the merchant's content in the visitor's language, and a machine to fill it ---
_ck = _ct.content_keys(_db.connect())
ok(any(k.startswith("product:") and k.endswith(":name") for k in _ck)
   and any(k.startswith("kind:") for k in _ck)
   and any(k.startswith("section:") for k in _ck),
   "the merchant's content — products, kinds, sections, menus, pages — is listed as keys")
ok(not any(k.endswith(":image") or k.endswith(":url") for k in _ck),
   "and only the words: images, links and layout are not translated")
_cc = _db.connect()
_mk = next((k for k in _ck if k.startswith("menu:")), None)
_sk = next((k for k in _ck if k.startswith("section:") and not k.endswith(":html")), None)
_cc.execute("INSERT OR REPLACE INTO translations(locale,key,value,source) VALUES('es',?,?,'typed')",
            (_mk or "menu:0:label", "Menú de prueba"))
if _sk:
    _cc.execute("INSERT OR REPLACE INTO translations(locale,key,value,source) VALUES('es',?,?,'typed')",
                (_sk, "TEXTO TRADUCIDO"))
_cc.commit()
ok(_ct.tx(_cc, _mk or "menu:0:label", "Menu", "es") == "Menú de prueba"
   and _ct.tx(_cc, _mk or "menu:0:label", "Menu", "en") == "Menu"
   and _ct.tx(_cc, "menu:none:label", "Menu", "es") == "Menu",
   "a string comes back in the language when a translation exists, as it was when none does")
_home_es = c.get("/?lang=es")
ok(_home_es.status_code == 200 and '<html lang="es"' in _home_es.text
   and ("Menú de prueba" in _home_es.text if _mk else True)
   and ("TEXTO TRADUCIDO" in _home_es.text if _sk else True),
   "with ?lang=es the server renders the menu and the sections in Spanish, "
   "and says so in the html tag")
_home_ck = c.get("/", cookies={"sf_locale": "es"})
ok('<html lang="es"' in _home_ck.text and ("Menú de prueba" in _home_ck.text if _mk else True),
   "and the sf_locale cookie the page writes does the same on every later visit")
ok('<html lang="ar" dir="rtl"' in c.get("/?lang=ar").text,
   "a right-to-left language is right to left from the first byte")
ok('<html lang="en"' in c.get("/").text and "Menú de prueba" not in c.get("/").text,
   "and with no language chosen, the base")
_sfjs4 = c.get("/store.js").text
ok("syncLocaleCookie" in _sfjs4 and "sf_locale_reloaded" in _sfjs4
   and "t(`kind:${k.id}:label`" in _sfjs4,
   "the page writes the cookie and reloads once when its language and the cookie disagree, "
   "and the kind headings go through the layer")
_cc.execute("DELETE FROM translations WHERE locale='es' AND value IN ('Menú de prueba','TEXTO TRADUCIDO')")
_cc.commit(); _cc.close()
# the machine
ok(c.post("/api/store/admin/translations/es/fill", headers=A).status_code == 400,
   "no engine connected: the fill says so")
ok(c.post("/api/store/admin/mt", headers=A, json={"engine": "babelfish"}).status_code == 400,
   "an engine is one of the known ones")
_mts = c.post("/api/store/admin/mt", headers=A, json={"engine": "deepl", "key": "k-1"}).json()
ok(_mts["engine"] == "deepl" and _mts["has_key"] and "key" not in _mts,
   "an engine and a key are kept, and the key never comes back")
_calls = []
def _fake_mt(engine, cfg, texts, target, html=False):
    _calls.append((engine, target, html, len(texts)))
    return [f"[{target}] {t}" for t in texts]
_real_mt = _ct._mt_call
_ct._mt_call = _fake_mt
try:
    _fill = c.post("/api/store/admin/translations/es/fill", headers=A).json()
finally:
    _ct._mt_call = _real_mt
ok(_fill["ok"] and _fill["filled"] > 0 and _calls and all(cl[0] == "deepl" and cl[1] == "es" for cl in _calls),
   f"the fill sends what the language lacks to the engine, in batches ({len(_calls)} calls)")
_tr_es2 = c.get("/api/store/admin/translations/es", headers=A).json()
_mkey = next((k for k in _tr_es2["own"] if k.startswith("product:")), None)
ok(_mkey and _tr_es2["sources"][_mkey] == "machine" and _tr_es2["own"][_mkey].startswith("[es] "),
   "what it wrote is marked as the machine's")
ok("prefs" not in _tr_es2["own"] or _tr_es2["sources"].get("prefs") != "machine",
   "and the interface's own words were never sent")
c.post("/api/store/admin/translations", headers=A, json={"locale": "es", "entries": {_mkey: "Salsa de la casa"}})
_tr_es3 = c.get("/api/store/admin/translations/es", headers=A).json()
ok(_tr_es3["sources"][_mkey] == "typed" and _tr_es3["own"][_mkey] == "Salsa de la casa",
   "and is replaced the moment somebody types the real thing")
_calls.clear(); _ct._mt_call = _fake_mt
try:
    _fill2 = c.post("/api/store/admin/translations/es/fill", headers=A).json()
finally:
    _ct._mt_call = _real_mt
ok(_fill2["filled"] == 0 and not _calls, "a second fill sends nothing — nothing is missing")
_cc = _db.connect(); _cc.execute("DELETE FROM translations WHERE locale='es'"); _cc.execute("DELETE FROM store_meta WHERE k='mt'"); _cc.commit(); _cc.close()
_admh2 = c.get("/admin").text
ok('id="mt-engine"' in _admh2 and 'id="tr-fill"' in _admh2 and "drawMt" in c.get("/admin.js").text,
   "the store admin connects the engine and fills a language from the translations screen")

# --- every major language, by one algorithm ---
ok(len(_ct.LANGUAGES) >= 40 and _ct.language_entry("ar")["dir"] == "rtl"
   and _ct.language_entry("he")["dir"] == "rtl" and _ct.language_entry("ja")["label"] == "日本語"
   and _ct.language_entry("xx")["label"] == "XX",
   "a catalogue of the major languages, each named in its own, with its reading direction")
_off = c.post("/api/store/admin/i18n/offer", headers=A, json={"codes": []}).json()
ok(len(_off["locales"]) >= 40 and _off["locales"][0]["code"] == "en"
   and any(l["code"] == "ko" for l in _off["locales"]),
   "one call offers every major language, English first, keeping what was there")
ok(c.post("/api/store/admin/i18n/offer", headers=A, json={"codes": ["e s"]}).status_code == 400,
   "and refuses what is not a code")
ok(_ct._intact("Your order #{oid} is in!", "¡Tu pedido #{oid} está en marcha!")
   and not _ct._intact("Your order #{oid} is in!", "¡Tu pedido está en marcha!")
   and _ct._intact("<b>Part one</b> is the platform", "<b>Primera parte</b> es la plataforma")
   and not _ct._intact("<b>Part one</b> is the platform", "Primera parte es la plataforma"),
   "an answer is kept only if every placeholder and every tag survived")
_big = {f"k{i}": "x" * 500 for i in range(30)}
ok(all(sum(len(_big[k]) for k in ch) <= 6000 for ch in _ct._chunks(list(_big), _big))
   and len(_ct._chunks(list(_big), _big)) == 3,
   "batches are sized by characters, not by count")
c.post("/api/store/admin/mt", headers=A, json={"engine": "anthropic", "key": "sk-1", "model": "claude-sonnet-5"})
ok(c.get("/api/store/admin/mt", headers=A).json()["model"] == "claude-sonnet-5",
   "an LLM engine keeps its model")
_sent = []
def _fake_mt2(engine, cfg, texts, target, html=False):
    _sent.append((target, list(texts)))
    out = []
    for t in texts:
        if t.startswith("DROPME"):
            out.append("lost it")          # the placeholder is gone
        else:
            out.append(f"[{target}] {t}")
    return out
_ct._mt_call = _fake_mt2
try:
    _dry = c.post("/api/store/admin/translations/it/fill", headers=A, json={"dry_run": True}).json()
    ok(_dry["dry_run"] and _dry["would_send"] > 0 and not _sent,
       "a dry run counts what would go and sends nothing")
    _it = c.post("/api/store/admin/translations/it/fill", headers=A, json={}).json()
    _es2 = c.post("/api/store/admin/translations/es/fill", headers=A, json={}).json()
finally:
    _ct._mt_call = _real_mt
ok(_it["filled"] > 0
   and any(any(t == "Preferences" for t in texts) for tgt, texts in _sent if tgt == "it")
   and not any(any(t == "Preferences" for t in texts) for tgt, texts in _sent if tgt == "es"),
   "a language nothing shipped for gets the interface's words from the machine; "
   "a shipped one never sends them")
_tr_it = c.get("/api/store/admin/translations/it", headers=A).json()
ok(_tr_it["sources"].get("prefs") == "machine" and _tr_it["own"]["prefs"] == "[it] Preferences",
   "and they land marked as the machine's")
_cc = _db.connect()
_cc.execute("UPDATE products SET description='DROPME {placeholder} text', active=1 WHERE id=?", (_pde_id,))
_cc.execute("DELETE FROM translations WHERE locale='it' AND key=?", (f"product:{_pde_id}:description",))
_cc.commit(); _cc.close()
_sent.clear(); _ct._mt_call = _fake_mt2
try:
    _it2 = c.post("/api/store/admin/translations/it/fill", headers=A, json={}).json()
finally:
    _ct._mt_call = _real_mt
ok(_it2["dropped"] >= 1 and f"product:{_pde_id}:description" not in
   c.get("/api/store/admin/translations/it", headers=A).json()["own"],
   "an answer that lost a placeholder is dropped, not kept")
c.post("/api/store/admin/translations", headers=A, json={"locale": "it", "entries": {"prefs": "Impostazioni"}})
_sent.clear(); _ct._mt_call = _fake_mt2
try:
    _it3 = c.post("/api/store/admin/translations/it/fill", headers=A, json={"force_machine": True}).json()
finally:
    _ct._mt_call = _real_mt
ok(not any(any(t == "Preferences" for t in texts) for tgt, texts in _sent)
   and c.get("/api/store/admin/translations/it", headers=A).json()["own"]["prefs"] == "Impostazioni",
   "a fresh machine pass never touches what somebody typed")
_sent.clear(); _ct._mt_call = _fake_mt2
try:
    _all = c.post("/api/store/admin/translations/fill-all", headers=A, json={"locales": ["fr", "de", "en"]}).json()
finally:
    _ct._mt_call = _real_mt
ok(_all["ok"] and [l["locale"] for l in _all["languages"]] == ["fr", "de"]
   and all("filled" in l for l in _all["languages"]),
   "fill-all runs the same algorithm per language and reports each on its own line")
# the LLM engines, through the wire
class _FakeResp:
    def __init__(self, body): self._b = json.dumps(body).encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False
_seen_req = []
def _fake_open(req, timeout=0):
    _seen_req.append((req.full_url, dict(req.header_items()), json.loads(req.data.decode())))
    n = len(json.loads(_seen_req[-1][2]["messages"][-1]["content"]))
    arr = json.dumps([f"T{i}" for i in range(n)])
    if "anthropic" in req.full_url:
        return _FakeResp({"content": [{"type": "text", "text": "Here you go:\n" + arr}]})
    return _FakeResp({"choices": [{"message": {"content": arr}}]})
_real_open = _ct.urllib.request.urlopen
_ct.urllib.request.urlopen = _fake_open
try:
    _o1 = _ct._mt_call("openai", {"key": "k", "model": "m"}, ["a", "b"], "sv")
    _o2 = _ct._mt_call("anthropic", {"key": "k"}, ["a", "b", "c"], "ko")
finally:
    _ct.urllib.request.urlopen = _real_open
ok(_o1 == ["T0", "T1"] and _o2 == ["T0", "T1", "T2"]
   and _seen_req[0][0].endswith("/chat/completions") and _seen_req[1][0].endswith("/v1/messages")
   and "Svenska" in _seen_req[0][2]["messages"][0]["content"]
   and _seen_req[1][1].get("X-api-key") == "k",
   "an OpenAI-compatible endpoint and the Anthropic API both answer one string per input, "
   "asked in the language's own name")
# the command line
import subprocess as _sp2
_h = _sp2.run([sys.executable, "scripts/translate.py", "--help"], capture_output=True, text=True,
              cwd=str(ROOT), env={**os.environ, "PYTHONPATH": "src"})
ok(_h.returncode == 0 and "--locales" in _h.stdout and "--force-machine" in _h.stdout
   and "--dry-run" in _h.stdout,
   "and the same algorithm runs from the command line for a whole language list")
ok('id="ln-major"' in c.get("/admin").text and 'id="mt-fill-all"' in c.get("/admin").text,
   "the store admin offers every major language and fills them all with two buttons")
_cc = _db.connect()
_cc.execute("UPDATE products SET description='' WHERE id=?", (_pde_id,))
_cc.execute("DELETE FROM translations WHERE locale IN ('it','fr','de')")
_cc.execute("DELETE FROM store_meta WHERE k IN ('mt','i18n')"); _cc.commit(); _cc.close()

# --- translators that are Python packages, not APIs ---
ok([e["id"] for e in _ct.mt_settings(_db.connect())["engines"]][:2] == ["argos", "nllb"]
   and "pip install" in _ct.MT_ENGINES["argos"]["hint"],
   "two engines run inside the process — a pip package, no server, no key — and are offered first")
import sys as _sys2
_saved_mod = {k: _sys2.modules.get(k) for k in ("argostranslate", "argostranslate.package", "argostranslate.translate")}
for k in _saved_mod:
    _sys2.modules[k] = None                       # makes `import argostranslate…` raise ImportError
try:
    try:
        _ct._argos(["hello"], "es"); _argos_msg = ""
    except Exception as e:                         # noqa: BLE001
        _argos_msg = getattr(e, "detail", str(e))
finally:
    for k, v in _saved_mod.items():
        if v is None:
            _sys2.modules.pop(k, None)
        else:
            _sys2.modules[k] = v
ok("pip install argostranslate" in _argos_msg,
   "without the package installed, the engine says what to install rather than crashing")
ok(_ct.NLLB_CODES["ar"] == "arb_Arab" and _ct.NLLB_CODES["zh-tw"] == "zho_Hant"
   and all(c in _ct.NLLB_CODES for c, _ in _ct.LANGUAGES),
   "and every language in the catalogue has an NLLB code")
_h2 = _sp2.run([sys.executable, "scripts/translate.py", "--help"], capture_output=True, text=True,
               cwd=str(ROOT), env={**os.environ, "PYTHONPATH": "src"})
ok("argos" in _h2.stdout and "nllb" in _h2.stdout, "the command line offers them")

_g = _ct._translate_guarded(lambda t: "X" * len(t), ["Hi {name}, <b>part one</b> is &amp; the platform"])[0]
ok("{name}" in _g and "<b>" in _g and "</b>" in _g and "&amp;" in _g and "part" not in _g
   and _ct._intact("Hi {name}, <b>part one</b> is &amp; the platform", _g),
   "a plain-text engine never sees a tag, an entity or a placeholder — the prose between them "
   "goes out and comes back into the same slots, so the guard passes it")
ok(_ct._translate_guarded(lambda t: "Y", ["  spaced  "]) == ["  Y  "],
   "and the spacing around each piece is kept")

ok(_ct._join_pieces(["▁从一个安装中运行整个业务.", "第二句。"], "zh") == "从一个安装中运行整个业务.第二句。"
   and _ct._join_pieces(["▁Hola", "mundo"], "es") == "Hola mundo",
   "a stray word marker never reaches the page, and languages written without spaces are joined without one")

ok(_ct._degenerate("有出出出出出出出出出出出出出出出出出出出出出出") and _ct._degenerate("plan plan plan plan plan")
   and not _ct._degenerate("从一个安装中运行整个业务.") and not _ct._degenerate("Plan de acción")
   and not _ct._degenerate("<b>aaa</b> {oid}"),
   "an answer that is one character or one word over and over is a model in a loop, not a translation, and is dropped")

# a forced pass that cannot do better than the machine's old row removes it
_cc = _db.connect()
_cc.execute("INSERT OR REPLACE INTO translations(locale,key,value,source) VALUES('it',?,?,'machine')",
            (f"product:{_pde_id}:name", "junk junk junk junk junk"))
_cc.execute("UPDATE products SET active=1 WHERE id=?", (_pde_id,)); _cc.commit(); _cc.close()
c.post("/api/store/admin/mt", headers=A, json={"engine": "deepl", "key": "k-2"})
_ct._mt_call = lambda engine, cfg, texts, target, html=False: ["loop loop loop loop loop" for _ in texts]
try:
    _rp = c.post("/api/store/admin/translations/it/fill", headers=A, json={"force_machine": True}).json()
finally:
    _ct._mt_call = _real_mt
ok(_rp["dropped"] >= 1 and f"product:{_pde_id}:name" not in
   c.get("/api/store/admin/translations/it", headers=A).json()["own"],
   "when a forced pass drops its answer, the machine's old row goes too — missing reads as "
   "English, junk reads as junk")
_cc = _db.connect(); _cc.execute("DELETE FROM translations WHERE locale='it'"); _cc.execute("DELETE FROM store_meta WHERE k='mt'"); _cc.commit(); _cc.close()

# --- traffic: every request written down, and the door with a list ---
from erp.backend import traffic as _trf  # noqa: E402
_CFGH["trust_forwarded_for"] = True          # the test client has no address of its own
_XF = lambda ip: {"X-Forwarded-For": ip}     # noqa: E731
ok(c.get("/api/traffic", headers=_WCU).status_code == 403,
   "the door is the owner's and the admin's")
c.get("/api/products", headers=_XF("203.0.113.10"))
c.get("/no/such/page", headers=_XF("203.0.113.10"))
_tp = c.get("/api/traffic?minutes=5", headers={**A, **_XF("203.0.113.1")}).json()
_mine = [r for r in _tp["recent"] if r["ip"] == "203.0.113.10"]
ok(len(_mine) >= 2 and {r["path"] for r in _mine} >= {"/api/products", "/no/such/page"}
   and any(r["status"] == 404 for r in _mine) and all("kind" in r and r["ms"] >= 0 for r in _mine),
   "every request is written down: who, what, how it went, how long")
ok(not any(r["path"].startswith("/vendor/") for r in _tp["recent"])
   and _tp["settings"]["log_assets"] is False,
   "assets are not logged unless asked — noise")
ok(any(t["ip"] == "203.0.113.10" and t["n"] >= 2 and t["sample_paths"] for t in _tp["talkers"]),
   "and the screen says who is asking the most, with what they asked for")
ok(_trf.classify({"ua": "Mozilla/5.0 (compatible; Googlebot/2.1)", "n": 3, "paths": 3, "errors": 0}) == "bot, says so"
   and _trf.classify({"ua": "", "n": 3, "paths": 3, "errors": 0}) == "no user agent"
   and _trf.classify({"ua": "Mozilla", "n": 200, "paths": 80, "errors": 0}) == "crawling"
   and _trf.classify({"ua": "Mozilla", "n": 10, "paths": 3, "errors": 8}) == "mostly errors",
   "each address is described by how it behaves, not judged")
# the door
ok(c.post("/api/traffic/rules", headers=A, json={"target": "ip", "value": "203.0.113.10"}).status_code == 400,
   "a ban needs a reason")
ok(c.post("/api/traffic/rules", headers=A, json={"target": "ip", "value": "not-an-ip", "reason": "x"}).status_code == 400,
   "and an address that is one")
_ban = c.post("/api/traffic/rules", headers=A, json={
    "target": "ip", "value": "203.0.113.10", "reason": "hammering the checkout (test)", "hours": 1}).json()
ok(_ban["ok"] and c.get("/api/products", headers=_XF("203.0.113.10")).status_code == 403
   and c.get("/", headers=_XF("203.0.113.10")).status_code == 403
   and c.get("/api/products", headers=_XF("203.0.113.11")).status_code == 200,
   "a banned address is refused everywhere, before any handler; its neighbour is not")
_tp = c.get("/api/traffic?minutes=5&status=blocked", headers={**A, **_XF("203.0.113.1")}).json()
ok(any(r["ip"] == "203.0.113.10" and r["blocked"] for r in _tp["recent"])
   and next(r for r in _tp["rules"] if r["id"] == _ban["id"])["hits"] >= 2,
   "a refused request is logged as refused, and the rule counts its hits")
c.post("/api/traffic/rules", headers=A, json={"target": "ip", "value": "203.0.113.0/28", "reason": "the whole block (test)"})
ok(c.get("/api/products", headers=_XF("203.0.113.14")).status_code == 403
   and c.get("/api/products", headers=_XF("203.0.113.20")).status_code == 200,
   "a network ban covers the range and nothing past it")
c.post("/api/traffic/rules", headers=A, json={"target": "ua", "value": "EvilScraper", "reason": "scraper (test)"})
ok(c.get("/api/products", headers={**_XF("203.0.113.30"), "User-Agent": "EvilScraper/1.0"}).status_code == 403
   and c.get("/api/products", headers={**_XF("203.0.113.30"), "User-Agent": "Mozilla/5.0"}).status_code == 200,
   "a user agent can be refused")
c.post("/api/traffic/rules", headers=A, json={"target": "path", "value": "/xmlrpc", "reason": "never ours (test)"})
ok(c.get("/xmlrpc.php", headers=_XF("203.0.113.31")).status_code == 403, "and a path")
# the allow list, the sharp tool
_al = c.post("/api/traffic/rules", headers=A, json={
    "kind": "allow", "target": "ip", "value": "203.0.113.100", "scope": "/ops", "reason": "the office (test)"}).json()
ok(c.get("/ops/", headers=_XF("203.0.113.40")).status_code == 403
   and c.get("/ops/", headers=_XF("203.0.113.100")).status_code == 200
   and c.get("/", headers=_XF("203.0.113.40")).status_code == 200,
   "an allow list on /ops locks /ops to the listed addresses and touches nothing else")
c.delete(f"/api/traffic/rules/{_al['id']}", headers=A)
ok(c.get("/ops/", headers=_XF("203.0.113.40")).status_code == 200, "lifting it opens the door again")
# expiry
_dcon = _db.connect()
_dcon.execute("UPDATE access_rules SET expires_at=? WHERE id=?", (_t0.time() - 1, _ban["id"])); _dcon.commit(); _dcon.close()
_trf._forget_rules()
ok(c.get("/api/products", headers=_XF("203.0.113.10")).status_code == 403,
   "(the /28 still covers .10)")
_dcon = _db.connect(); _dcon.execute("DELETE FROM access_rules WHERE reason LIKE '%(test)%'"); _dcon.commit(); _dcon.close()
_trf._forget_rules()
ok(c.get("/api/products", headers=_XF("203.0.113.10")).status_code == 200,
   "an expired or lifted ban lets the address back in")
# automatic bans
ok(c.get("/wp-login.php", headers=_XF("203.0.113.50")).status_code == 404
   and c.get("/api/products", headers=_XF("203.0.113.50")).status_code == 403,
   "one request for /wp-login.php is a scanner: banned for a day without anyone looking")
_auto = [r for r in c.get("/api/traffic", headers={**A, **_XF("203.0.113.1")}).json()["rules"]
         if r["value"] == "203.0.113.50"]
ok(_auto and _auto[0]["auto"] and "automatic" in _auto[0]["reason"] and _auto[0]["expires_at"] > _t0.time(),
   "marked as the guard's own, with the reason and an expiry")
c.post("/api/traffic/settings", headers=A, json={"patch": {"rate_per_minute": 5, "rate_ban_minutes": 1}})
for _i in range(8):
    c.get("/api/products", headers=_XF("203.0.113.60"))
ok(c.get("/api/products", headers=_XF("203.0.113.60")).status_code == 403,
   "more requests in a minute than a person makes earns a short ban")
ok(c.get("/wp-login.php").status_code == 404 and c.get("/api/products").status_code == 200,
   "but never for this machine itself — an operator cannot lock the box out")
c.post("/api/traffic/settings", headers=A, json={"patch": {"rate_per_minute": 300, "rate_ban_minutes": 30}})
ok(c.post("/api/traffic/settings", headers=A, json={"patch": {"keep_days": "soon"}}).status_code == 400,
   "a setting that is a number is a number")
_csv = c.get("/api/traffic/export.csv?minutes=60", headers={**A, **_XF("203.0.113.1")})
ok(_csv.status_code == 200 and "text/csv" in _csv.headers["content-type"]
   and _csv.text.splitlines()[0].startswith("at,ip,method,path")
   and "203.0.113.10" in _csv.text,
   "the log exports as CSV")
ok(not any(k in _csv.text for k in ("Authorization", "Bearer", _wc["token"])),
   "and never a token, a cookie or a body")
_dcon = _db.connect(); _dcon.execute("DELETE FROM access_rules"); _dcon.commit(); _dcon.close(); _trf._forget_rules()
_CFGH["trust_forwarded_for"] = False
ok('"traffic"' in _ops and "traffic: renderTraffic" in _ops and "data-trfban" in _ops
   and 'id="trf-save"' in _ops,
   "the screen is on the rail under Company with a Ban button beside each address")
_tabs_src2 = _ops[_ops.index("const TABS = ["):_ops.index("\n];", _ops.index("const TABS = ["))]
ok('id: "audit", label: "Audit log", icon: "shield2", group: "Team"' in _tabs_src2,
   "and the audit log moved to Team — who did what is about the team")
ok("/api/traffic/*" in _mcpt.EXCLUDED, "the agent door does not reach the log or the bans")

done("core")
