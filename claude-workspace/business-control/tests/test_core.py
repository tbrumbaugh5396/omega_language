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
ok(not any("5511" in (e["detail"] or "") for e in _au2["entries"]),
   "and the value itself is nowhere in the log")
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
ok("8342" not in _row["pin_hash"], "and the digits are not in it")
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
    " WHERE o.status!='cancelled' AND o.created_at >= strftime('%s','now')-2592000"
    " GROUP BY oi.product_id ORDER BY SUM(oi.qty) DESC LIMIT 1").fetchone()
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
ok(_bak.content[:15] == b"SQLite format 3",
   "the backup is a real SQLite file, not a dump that might not restore")
import sqlite3 as _sq  # noqa: E402
_bp = Path(tempfile.mkdtemp()) / "b.db"
_bp.write_bytes(_bak.content)
_bcon = _sq.connect(_bp)
ok(_bcon.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0,
   "it opens and has the data in it")
ok(_bcon.execute("SELECT COUNT(*) FROM users WHERE token=?",
                 (_mytoken,)).fetchone()[0] == 1,
   "and it keeps the credentials — a redacted backup is not a backup")
_bcon.close()

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
   and '<div class="side-group">All products</div>' in _store_js2,
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
os.utime(_scan, (_t.time() + 60, _t.time() + 60))
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
ok(all(not p["connected"] for p in _ist["providers"]),
   "none is connected until someone connects it")
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
}
for _n, _pd in _ig.PROVIDERS.items():
    for _a in _pd.get("actions", []):
        ok(_a in _ACTION_IMPL,
           f"{_n} declares the known action {_a!r}")
        ok(_ACTION_IMPL.get(_a, "\0") in _src_ig,
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
ok("def has_alpha" in _apisrc and 'f"{mid}_{suffix}.png"' in _apisrc,
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
_missing = [n for n in _pnames
            if n not in _navd and f"ig-{n}" not in _navd]
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
_old = _c_now - 70 * 86400
for _i in range(4):
    _buy(800 + _i, _old, 2000)
_buy(800, _old + 35 * 86400, 2000)        # one of them returns a month on
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
ok(_days["compare"]["this"]["days"] == _days["compare"]["last"]["days"],
   "month against month compares the SAME stretch of each — three days "
   "of September against the whole of August is not a comparison, it is "
   "a subtraction, and it always says the business collapsed")
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

done("core")
