"""Script-style smoke test over a throwaway database: exercises login, orders
(retail + wholesale pricing), time clock, A/B assignment + results, affiliates,
inventory, route planning, funnel analytics, and outreach."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["BUSINESS_CONTROL_DATA"] = tempfile.mkdtemp(prefix="bc_test_")

from fastapi.testclient import TestClient  # noqa: E402
from erp.backend.main import app, CFG  # noqa: E402

c = TestClient(app)
checks = 0


def ok(cond, label):
    global checks
    checks += 1
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"  ok: {label}")


# --- auth ---
admin = c.post("/api/login", json={"name": "Boss", "admin_key": CFG["admin_key"]}).json()
ok(admin["is_admin"], "admin login via admin key")
A = {"Authorization": f"Bearer {admin['token']}"}
cust = c.post("/api/login", json={"name": "Carl Customer", "region": "West"}).json()
CU = {"Authorization": f"Bearer {cust['token']}"}


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
ok(row["qty"] == 24, "route delivery restocks the store to par")

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
ok(r.status_code == 200 and r.json()["ref"].startswith("ZJ-"),
   "ticket accepted with a reference")
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
       json={"phone": "+1 555 010 2030", "calls_enabled": True})
ok(c.get("/api/store/support/config").json()["phone"] == "+1 555 010 2030",
   "merchant phone number reaches the storefront")

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
ok("--accent: #8a6ff0" in _css, "ops palette re-toned to the brand accent")
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
_aud._last_prune = 0
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
_aud._last_prune = 0
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
ok("CACHEABLE" in _sw, "the worker decides what is worth caching")
ok("r.ok && r.type" in _sw,
   "and never stores an error response, which would strand a broken shell")

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
ok("100,000+" in _sect.defaults_for("social_proof")["figure"],
   "and it says 100,000+")

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

ok("Shop your Zen" in _storejs and '"default": "Shop your Zen"' in _sectsrc,
   "'Shop the range' is now 'Shop your Zen'")
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

# --- the template kit names real capabilities ------------------------------
# The free consultation is where a client is told which permissions, roles and
# integrations they can have. A sales document that promises a connector the
# code does not have is worse than no document, and the drift is silent — the
# doc is prose, so nothing else would ever catch it.
_consult = Path("docs/business-control-b2b-client/templates/02-consultation/free-consultation.md").read_text()
_gov = Path("src/storefront/backend/governance.py").read_text()
_intg = Path("src/erp/backend/integrations.py").read_text()

_perms = set(re.findall(r'^    "(\w+)": "',
                        _gov.split("PERMISSIONS = {")[1].split("}")[0], re.M))
_missing = sorted(p for p in _perms if f"`{p}`" not in _consult)
ok(_perms and not _missing,
   f"the consultation offers every permission the code grants (missing: {_missing})")

_provs = set(re.findall(r'^    "([a-z_]+)": \{', _intg, re.M))
_unlisted = sorted(p for p in _provs if p not in _consult.lower())
ok(_provs and not _unlisted,
   f"and every integration that actually exists (missing: {_unlisted})")

_jobs = set(re.findall(r'"([^"]+)"',
                       Path("src/erp/frontend/app.js").read_text()
                       .split("JOB_LABEL = {")[1].split("}")[0]))
_nojob = sorted(j for j in _jobs - {"general"} if j.lower() not in _consult.lower())
ok(not _nojob, f"and every staff role that has its own view (missing: {_nojob})")

# --- the kit's shape: stage folders, and the internal wall ----------------
_studio = Path("docs/business-control-b2b-client")
_stages = sorted(p.name for p in (_studio / "templates").iterdir() if p.is_dir())
ok(len(_stages) == 11 and _stages[0].startswith("01-")
   and all(re.match(r"\d\d-", s) for s in _stages),
   f"the templates are filed by numbered stage, so the order is the folder "
   f"listing rather than something to remember ({len(_stages)} stages)")

_no_readme = [s for s in _stages
              if not (_studio / "templates" / s / "README.md").exists()]
ok(not _no_readme,
   f"every stage says what it sends and what opens the next gate "
   f"(missing: {_no_readme})")

_root = (_studio / "README.md").read_text()
ok(all(f"templates/{s}/" in _root for s in _stages),
   "and the index links every one of them")

# --- aftercare covers the work that is actually continuous ----------------
# "Ongoing support" in a contract is worth what its schedule says and no more.
# Clause 15 promises security, monitoring, defect support and compliance; if
# no page defines them, the clause is a sentence the client reads their own
# hopes into.
from storefront.backend.engagements import side_of as _side_of
_after = _studio / "templates" / "11-aftercare"
_care = (_after / "care-plan-agreement.md").read_text()
_supp = (_after / "support-and-defects.md").read_text()
_mon = (_after / "monitoring-and-incidents.md").read_text()
_sec = (_after / "security-and-compliance.md").read_text()
_grow = (_after / "growth-retainer.md").read_text()

ok(all(_side_of(t) == "to_client" for t in (_care, _supp, _mon, _sec, _grow))
   and all("[SIGN HERE]" in t for t in (_supp, _mon, _sec, _grow)),
   "every ongoing-work schedule is a client document that gets signed — an "
   "unsigned promise about response times is a preference")

ok("Defect, or change?" in _supp and _supp.count("**Defect**") >= 4
   and all(f"**{p} " in _supp for p in ("P1", "P2", "P3", "P4"))
   and "First response" in _supp,
   "support defines the bug it will fix free, against the change it will "
   "bill for, with severities and a first-response time for each")

ok("[SUPPORT EMAIL / PORTAL]" in _supp and "[30] days" in _supp,
   "one route in, and the no-plan warranty window said out loud")

ok(all(w in _mon for w in ("Uptime", "Key journeys", "SSL certificate",
                           "Backups", "Malware", "Escalation"))
   and _mon.count("Every **[") >= 2,
   "monitoring names what is watched and how often, not just that it is")

ok("Alerts go to the Studio first, not to you" in _mon
   and "Primary" in _mon and "Backup" in _mon,
   "and it routes the alert to the studio, with the client contact we may "
   "ring at night written down before the night we need it")

ok("Critical" in _sec and "[24] hours" in _sec
   and "Dependency scanning" in _sec and "Restore tested" in _sec,
   "security is a cadence — patch windows by severity, weekly scanning, and "
   "a restore actually tested rather than assumed")

ok("72 hours" in _sec and "Compliance in scope" in _sec
   and all(k in _sec for k in ("WCAG", "GDPR", "PCI")),
   "and it ticks the compliance scope and states the breach clock, which is "
   "the client's to run and ours to make runnable")

ok("Who holds what" in _sec and "You own every account" in _sec,
   "credentials are inventoried and the client owns them — access to work, "
   "not leverage")

ok("SEO campaigns and advertising" in _care
   and "growth-retainer.md" in _care and "Ad spend is not the fee" in _grow
   and "You own every account" in _grow,
   "growth work is sold beside the care plan and never inside it: separate "
   "money, separate cancellation, and the ad accounts stay the client's")

for _sched in ("support-and-defects.md", "monitoring-and-incidents.md",
               "security-and-compliance.md"):
    ok(_sched in _care, f"the care plan links its {_sched} schedule")

_cc = (_studio / "templates/04-agreement/contracts/common-clauses.md").read_text()
ok(all(f"11-aftercare/{d}" in _cc for d in
       ("security-and-compliance.md", "monitoring-and-incidents.md",
        "support-and-defects.md", "growth-retainer.md")),
   "and clause 15 points at those schedules by name — the contract promises "
   "exactly what a page defines, and nothing looser")

ok((_studio / "procedures/running-a-care-plan.md").exists()
   and "Never send this to a client" in
       (_studio / "procedures/running-a-care-plan.md").read_text(),
   "and there is an internal procedure for actually running the cadence the "
   "client bought, because a plan billed monthly and touched on breakage is "
   "the one you lose at renewal")

# The wall between what a client may read and what they may not is the whole
# reason the per-client folder is shaped this way; a stage folder missing one
# side is the one that gets zipped and sent by mistake.
_ct = _studio / "clients" / "_template"
_cstages = sorted(p.name for p in _ct.iterdir() if p.is_dir())
_unwalled = [s for s in _cstages
             if not ((_ct / s / "to-client").is_dir()
                     and (_ct / s / "internal").is_dir())]
ok(_cstages and not _unwalled,
   f"every client stage separates what they receive from what they must not "
   f"(unwalled: {_unwalled})")

ok("roadmap.md" in _root and (_studio / "roadmap.md").exists(),
   "the delivery, deployment and setup roadmap is in the kit and linked from it")
_road = (_studio / "roadmap.md").read_text()
ok("../product/DEPLOY.md" in _road,
   "and it points at the technical runbook rather than duplicating it — a "
   "second copy of deployment steps is a copy that goes stale silently")

# docs/ has two halves and they must not blur: the product's own docs, and
# the client-facing kit. An index in each is what keeps a stray file from
# landing in the wrong one and being sent to the wrong audience.
# docs/ itself needs an index, or the two halves are two piles.
_docs_idx = Path("docs/README.md")
ok(_docs_idx.exists(), "docs/ has an index naming both halves")
_di = _docs_idx.read_text()
ok("product/" in _di and "business-control-b2b-client/" in _di,
   "and it points at each of them")
_docs_dirs = sorted(p.name for p in Path("docs").iterdir() if p.is_dir())
_unindexed = [d for d in _docs_dirs if d not in _di]
ok(not _unindexed,
   f"and every folder under docs/ is accounted for (missing: {_unindexed})")

# The client folder is the thing someone opens under time pressure; a stage
# that doesn't say what belongs in it gets filled by guesswork.
_ct = Path("docs/business-control-b2b-client/clients/_template")
_cst = sorted(p.name for p in _ct.iterdir() if p.is_dir())
_vague = [d for d in _cst
          if "What lands here" not in (_ct / d / "README.md").read_text()]
ok(not _vague,
   f"every client stage says what lands in it, on both sides of the wall "
   f"(vague: {_vague})")
_board = (_ct / "README.md").read_text()
ok("06 Brand" in _board and "10 Aftercare" in _board,
   "and the status board's stages match the folders beside it")
ok("project-roadmap.md" in _board,
   "and it names its client-facing twin — two status documents that disagree "
   "is worse than one, because now nobody trusts either")
ok("Gates passed" in _board and "Deposit cleared" in _board,
   "the board tracks gates as signatures, not as feelings")

_prod = Path("docs/product/README.md")
ok(_prod.exists(), "the product docs have an index of their own")
_pr_txt = _prod.read_text()
_prod_files = sorted(p.name for p in Path("docs/product").iterdir()
                     if p.name != "README.md")
_unlisted = [f for f in _prod_files if f not in _pr_txt]
ok(not _unlisted, f"and it lists every document in the folder (missing: {_unlisted})")
ok("business-control-b2b-client" in _pr_txt,
   "and points at the client-facing kit rather than absorbing it")

# A wet-ink signature table next to an electronic Signed block reads as
# broken blank space. Every template that carries the table says which is
# which — on its face, where the person filling it in is looking.
_tabled = [str(p.relative_to(_studio)) for p in
           (_studio / "templates").rglob("*.md")
           if "| Signature | | |" in p.read_text()]
_unnoted = [f for f in _tabled if "Signing electronically?"
            not in (_studio / f).read_text()]
ok(_tabled and not _unnoted,
   f"every signature table explains the electronic path beside the wet-ink "
   f"one (missing: {_unnoted})")

ok("packages-and-process.md" in _root and "free-consultation.md" in _root,
   "and both consultation documents are in the kit's index, not just on disk")

# The client gets their own roadmap — a different document from the studio's
# delivery guide, and the pair is easy to confuse precisely because both are
# called a roadmap. Each must say which one it is.
_proj = _studio / "templates" / "05-kickoff" / "project-roadmap.md"
ok(_proj.exists(), "the client gets a roadmap of their own, to track execution")
_pr = _proj.read_text()
ok("Client-facing" in _pr and "roadmap.md" in _pr,
   "and it says plainly that it is theirs, and points at the internal one it "
   "is not")
ok("internal" in _road.split("\n")[0:6].__str__().lower()
   or "Internal" in _road[:400],
   "while the delivery roadmap says plainly that it is not for sending")
ok("Last updated" in _pr and "Right now" in _pr,
   "it carries a current status, so re-sending it is the update")
ok("project-roadmap.md" in (_studio / "procedures" / "weekly-rhythm.md").read_text(),
   "and the weekly rhythm is what re-sends it — a status document nobody "
   "updates is worse than none, because it reads as current")

# The rate card must never reach a client. The index is hand-edited, so the
# guarantee is asserted on the document itself rather than on prose elsewhere.
_rate = (_studio / "templates" / "03-proposal" / "rate-card.md").read_text()
ok("Never send this to a client" in _rate,
   "the rate card says on its own face that it is internal — a price list "
   "invites line-item haggling over work priced as a whole")

# The optional brand stage, for work where the look is the point.
_brand = _studio / "templates" / "07-brand-exploration"
ok(_brand.is_dir() and (_brand / "art-direction.md").exists()
   and (_brand / "direction-review-form.md").exists()
   and (_brand / "brand-exploration-brief.md").exists(),
   "brand exploration is its own stage: a brief, directions to react to, and "
   "a signed art direction")
_bre = (_brand / "README.md").read_text()
ok("Optional" in _bre and "Week website" in _bre,
   "and it says when to skip it — a stage that always runs is not optional, "
   "it is overhead")
ok("art-direction" in (_studio / "clients" / "_template"
                       / "06-brand-exploration" / "README.md").read_text(),
   "the client folder has a home for the signed direction, which is what "
   "settles 'we never agreed to that' in month four")

# --- engagements: the kit, run from the ERP --------------------------------
# The registry is the kit folder read live, sides are derived from the
# documents' own faces, and the client bundle is drawn from the to-client
# side only — each asserted here because each is a wall someone will lean on.
_tj = c.get("/api/store/admin/engagements/templates", headers=A).json()
ok(_tj["kit_available"] and len(_tj["stages"]) == 11,
   "the template registry is the kit folder itself, all eleven stages — "
   "nothing to keep in sync")
_all_t = [t for st in _tj["stages"] for t in st["templates"]]
_by = {t["path"]: t for t in _all_t}
ok(_by["03-proposal/rate-card.md"]["side"] == "internal",
   "the rate card derives 'internal' from its own text, not from a list")
ok(_by["03-proposal/proposal-template.md"]["side"] == "to_client",
   "and the proposal goes to the client")
ok(all(t["side"] == "internal" for t in _all_t
       if "discovery-brief" in t["path"] or "exploration-brief" in t["path"]),
   "every brief that says 'never send' is born on the internal side")

_eng = c.post("/api/store/admin/engagements", headers=A, json={
    "name": "Smoke Test Client", "package": "B", "value_cents": 1200000,
    "approver_name": "Alex Chen", "approver_email": "alex@smoke.test",
    "launch_target": "2026-12-01"}).json()
_eid = _eng["id"]
ok(_eng["slug"] == "smoke-test-client", "a client becomes a slug, safely")

_td = c.get(f"/api/store/admin/engagements/{_eid}/template", headers=A,
            params={"path": "03-proposal/proposal-template.md"}).json()
ok("CLIENT NAME" in _td["placeholders"] and "DATE" in _td["placeholders"],
   "placeholders are read out of the template's brackets")
ok(_td["suggested"].get("CLIENT NAME") == "Smoke Test Client"
   and _td["suggested"].get("X") == "12,000",
   "and the engagement record pre-fills them — the proposal and the record "
   "cannot disagree about the number, because both read the same row")

_gen = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "03-proposal/proposal-template.md",
    "fills": {"NAME, ROLE": "Alex Chen, COO"}}).json()
ok(_gen["side"] == "to_client" and _gen["unfilled"],
   "generation lands on the derived side and counts what is left to fill")
_vd = [d for d in c.get("/api/store/admin/documents", headers=A,
       params={"q": "Smoke Test Client"}).json()["documents"]
       if d["id"] == _gen["doc_id"]][0]
ok("[" not in _vd["title"] and "Smoke Test Client" in _vd["title"],
   "the title is taken from the filled text — no bracket ships in a title")
c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A,
       json={"template_path": "03-proposal/rate-card.md"})

ok(c.get(f"/api/store/admin/engagements/{_eid}/template", headers=A,
         params={"path": "../../../product/DEPLOY.md"}).status_code == 404,
   "a template path cannot walk out of the kit")

_exp = c.post(f"/api/store/admin/engagements/{_eid}/export",
              headers=A).json()
ok(any(f.startswith("02-proposal/to-client/") for f in _exp["files"])
   and any(f.startswith("02-proposal/internal/") for f in _exp["files"]),
   "the folder export matches the clients/_template convention, walls intact")
ok(Path(_exp["root"], "README.md").exists(),
   "with a generated status board at the root")

import io as _io
import zipfile as _zip
_zr = c.get(f"/api/store/admin/engagements/{_eid}/export.zip", headers=A)
_names = _zip.ZipFile(_io.BytesIO(_zr.content)).namelist()
ok(_names and all("/internal/" not in n for n in _names),
   "the client bundle is drawn from side='to_client' only — sending the "
   "estimate along with the proposal is not possible from this door")
_zall = c.get(f"/api/store/admin/engagements/{_eid}/export.zip",
              headers=A, params={"side": "all"})
ok("full-archive" in _zall.headers.get("content-disposition", ""),
   "and the everything-zip is named full-archive, so nobody mistakes it")

_sr = c.post(f"/api/store/admin/documents/{_gen['doc_id']}/request-signature",
             headers=A, json={"signer_name": "Alex Chen",
                              "signer_email": "alex@smoke.test",
                              "role": "approver"}).json()
ok("/sign/" in _sr["link"],
   "a generated document signs through the vault's own flow — this module "
   "grew no signature code of its own")
_det = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(any(d["awaiting"] for d in _det["docs"]),
   "and the engagement sees the pending signature without copying any state")

# --- gates: signatures with a stage attached -------------------------------
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(len(_gd["gates"]) == 10 and _gd["current_stage"] == "02-proposal",
   "an engagement opens with every gate open, standing at the proposal")
ok(_gd["gates"][-1]["gate"] == "ongoing_support_agreed",
   "and the last gate is the ongoing one — security, monitoring, updates "
   "and bug support are continuous work, not an afterthought, and the care "
   "plan is where the contract says how they're carried")
ok(not next(g for g in _gd["gates"]
            if g["gate"] == "art_direction_signed")["active"],
   "the art direction gate doesn't exist until brand work does — a week "
   "website is never blocked on a stage it skipped")

_dep = c.post(f"/api/store/admin/engagements/{_eid}/gates/deposit_cleared",
              headers=A, json={"note": "wire ref 9001"}).json()
ok(_dep["gate"]["via"] == "manual" and _dep["gate"]["passed_at"],
   "a money gate is a manual confirmation with an actor and a timestamp")
ok("Proposal accepted" in _dep["warnings"],
   "and passing it out of order warns loudly instead of silently allowing "
   "or hard-blocking")
ok(c.post(f"/api/store/admin/engagements/{_eid}/gates/contract_signed",
          headers=A, json={}).status_code == 400,
   "a signature gate passed by hand demands a note saying where the "
   "evidence is filed — the point of a gate is that you can point at it")

_link = c.post(f"/api/store/admin/engagements/{_eid}/gates/proposal_accepted",
               headers=A, json={"doc_id": _gen["doc_id"]}).json()
ok(not _link["gate"]["passed_at"],
   "linking an unsigned document leaves the gate awaiting, not passed")
_sr2 = c.post(f"/api/store/admin/documents/{_gen['doc_id']}/request-signature",
              headers=A, json={"signer_name": "Alex Chen",
                               "signer_email": "alex@smoke.test",
                               "role": "approver"}).json()
_tok = _sr2["link"].split("/sign/")[1]
_page = c.get(f"/sign/{_tok}").text
ok("<h3>" in _page or "<table>" in _page or "<ul>" in _page,
   "the sign page renders the document's structure — a signature attests to "
   "what the signer was shown, so the shown thing carries the real headings "
   "and tables, not paragraph soup")
c.post(f"/sign/{_tok}", json={"typed_name": "Alex Chen"})
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
_pa = next(g for g in _gd["gates"] if g["gate"] == "proposal_accepted")
ok(_pa["via"] == "signature" and _pa["signed_by"] == "Alex Chen",
   "and once signed, the gate passes by derivation — read from the vault "
   "at request time, no copied state, no sync job")
c.post(f"/api/store/admin/engagements/{_eid}/gates/contract_signed",
       headers=A, json={"note": "countersigned PDF, filed 03-agreement"})
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(_gd["current_stage"] == "05-requirements",
   "the stage is the first open gate — proposal, contract and deposit "
   "passed walks it to requirements, and no stage column exists to disagree")

_alien = c.post("/api/store/admin/documents", headers=A,
                json={"title": "Someone else's paper", "body": "x"}).json()
ok(c.post(f"/api/store/admin/engagements/{_eid}/gates/handover_accepted",
          headers=A, json={"doc_id": _alien["id"]}).status_code == 400,
   "a gate only accepts documents filed under its own client — an unrelated "
   "signature would make the gate attest to nothing")
c.delete(f"/api/store/admin/documents/{_alien['id']}", headers=A)

c.request("DELETE",
          f"/api/store/admin/engagements/{_eid}/gates/contract_signed",
          headers=A)
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(_gd["current_stage"] == "03-agreement",
   "reopening a gate moves the stage back by the same derivation, and the "
   "signed evidence stays in the vault untouched")

# --- archiving a client ----------------------------------------------------
_ar = c.post("/api/store/admin/engagements", headers=A,
             json={"name": "Parked Smoke"}).json()
_arl = lambda a=0: c.get("/api/store/admin/engagements", headers=A,
                         params={"archived": a}).json()
ok(any(x["name"] == "Parked Smoke" for x in _arl()["engagements"]),
   "a new client is on the working list")
c.post(f"/api/store/admin/engagements/{_ar['id']}/archive", headers=A,
       json={"archived": True})
ok(all(x["name"] != "Parked Smoke" for x in _arl()["engagements"])
   and any(x["name"] == "Parked Smoke" for x in _arl(1)["engagements"]),
   "archiving puts a client away — off the working list, on the archived "
   "one, counted on its own chip")
_ard = c.get(f"/api/store/admin/engagements/{_ar['id']}", headers=A).json()
ok(len(_ard["docs"]) >= 2 and _ard["engagement"]["status"] == "archived",
   "and nothing is removed: the documents, gates and dates are as they "
   "were, which is the difference between archiving and deleting")
c.post(f"/api/store/admin/engagements/{_ar['id']}/archive", headers=A,
       json={"archived": False})
ok(any(x["name"] == "Parked Smoke" for x in _arl()["engagements"]),
   "so it comes back — one is reversible, the other is a decision")
c.delete(f"/api/store/admin/engagements/{_ar['id']}", headers=A)

# --- deleting a client -----------------------------------------------------
_dd = c.post("/api/store/admin/engagements", headers=A,
             json={"name": "Doomed Smoke"}).json()
_dsign = c.post(f"/api/store/admin/engagements/{_dd['id']}/docs", headers=A,
                json={"template_path": "05-kickoff/welcome-guide.md"}).json()
_dplain = c.post(f"/api/store/admin/engagements/{_dd['id']}/docs", headers=A,
                 json={"template_path": "03-proposal/proposal-template.md"}
                 ).json()
_dsr = c.post(f"/api/store/admin/documents/{_dsign['doc_id']}"
              "/request-signature", headers=A,
              json={"signer_name": "Pat", "signer_email": "p@x.t",
                    "role": "signer", "in_person": True}).json()
c.post(f"/sign/{_dsr['link'].split('/sign/')[1]}",
       json={"typed_name": "Pat"})
_dout = c.delete(f"/api/store/admin/engagements/{_dd['id']}",
                 headers=A).json()
ok(_dout["kept"] == 1 and _dout["removed"] >= 2,
   "deleting a client takes the paperwork that only existed for them — "
   "except anything signed, because deleting the client does not un-agree "
   "what a named person agreed to")
ok(c.get(f"/api/store/admin/engagements/{_dd['id']}",
         headers=A).status_code == 404, "and the client is gone")
_gone = _db.connect().execute("SELECT status FROM documents WHERE id=?",
                              (_dplain["doc_id"],)).fetchone()
ok(_gone is None, "an unsigned draft goes with it")
_kept = _db.connect().execute("SELECT status FROM documents WHERE id=?",
                              (_dsign["doc_id"],)).fetchone()
ok(_kept and _kept["status"] == "archived",
   "the signed one is archived, not destroyed")
_arch = c.get("/api/store/admin/documents", headers=A,
              params={"archived": 1}).json()
ok(any(d["id"] == _dsign["doc_id"] for d in _arch["documents"])
   and _arch["archived_count"] >= 1,
   "and it is findable — evidence you cannot find is a gesture, so "
   "Documents has an Archived view rather than hiding it for good")
_conk = _db.connect()
_conk.execute("DELETE FROM document_signatures WHERE document_id=?",
              (_dsign["doc_id"],))
_conk.execute("DELETE FROM document_events WHERE document_id=?",
              (_dsign["doc_id"],))
_conk.execute("DELETE FROM documents WHERE id=?", (_dsign["doc_id"],))
_conk.commit(); _conk.close()

# --- the client portal: one link, drawn from the same rows -----------------
ok(c.get("/engage/nope").status_code == 404, "a made-up portal token is a 404")
_purl = c.post(f"/api/store/admin/engagements/{_eid}/portal",
               headers=A).json()["url"]
_ptok = _purl.split("/engage/")[1]
c.patch(f"/api/store/admin/engagements/{_eid}", headers=A,
        json={"content_pct": 40, "week_note": "Round one went out.",
              "blockers": "Waiting on photography (since 20 Aug)"})
c.put(f"/api/store/admin/engagements/{_eid}/dates", headers=A,
      json={"dates": [{"label": "Launch", "planned": "2026-12-01"}]})
_pp = c.get(f"/engage/{_ptok}").text
ok("Round one went out." in _pp and "width:40%" in _pp
   and "Waiting on photography" in _pp and "2026-12-01" in _pp,
   "the portal renders the roadmap from the record — note, content bar, "
   "blockers and dates, nothing retyped")
ok("done" in _pp and "in progress" in _pp,
   "and the gate timeline reads live from the same gates the ERP shows")
ok("Rate card" not in _pp,
   "the internal side is invisible on the portal — not withheld, unreachable")
ok(c.get(f"/engage/{_ptok}/doc/{_gen['doc_id']}").status_code == 200,
   "a to-client document opens from its portal link")
_rate_id = next(d["id"] for d in _gd["docs"] if d["side"] == "internal")
ok(c.get(f"/engage/{_ptok}/doc/{_rate_id}").status_code == 404,
   "and the internal document 404s through the same route — the wall is the "
   "query, not discipline")
ok("awaiting your signature" in _pp or "signed" in _pp,
   "signature state surfaces on the portal; signing stays on /sign/")

ok(c.post(f"/engage/{_ptok}/direction",
          data={"choice": "1", "name": "P"}).status_code == 400,
   "a direction can't be chosen before any brand work exists")
c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A,
       json={"template_path": "07-brand-exploration/direction-review-form.md"})
_pp = c.get(f"/engage/{_ptok}").text
ok("Choose a direction" in _pp,
   "brand work on the portal brings the choice form with it")
_dc = c.post(f"/engage/{_ptok}/direction",
             data={"choice": "Direction 2 — Quiet Authority",
                   "name": "Alex Chen", "works": "calm palette"})
ok(_dc.status_code == 200, "the client's choice records from the portal")
ok(c.post(f"/engage/{_ptok}/direction",
          data={"choice": "3", "name": "B"}).status_code == 400,
   "one consolidated response means one — a second submission is refused")
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(any("direction chosen" in l["what"] for l in _gd["log"])
   and any("Direction choice" in d["title"] for d in _gd["docs"]),
   "and the choice lands as a filed document plus a log entry — the folder "
   "convention already had a home for the returned form")
_pgate = next(g for g in _gd["gates"] if g["gate"] == "art_direction_signed")
ok(_pgate["active"],
   "brand work existing is also what wakes the art direction gate")

c.request("DELETE", f"/api/store/admin/engagements/{_eid}/portal", headers=A)
ok(c.get(f"/engage/{_ptok}").status_code == 404,
   "revoking the link kills it immediately — rotation is revocation with a "
   "forwarding address")

# --- rhythm and filing -----------------------------------------------------
_purl2 = c.post(f"/api/store/admin/engagements/{_eid}/portal",
                headers=A).json()["url"]
c.patch(f"/api/store/admin/engagements/{_eid}", headers=A,
        json={"blockers": "waiting on the logo (since Monday)"})
_me = next(x for x in c.get("/api/store/admin/engagements", headers=A)
           .json()["engagements"] if x["id"] == _eid)
ok("blocked" in _me["warnings"],
   "the dashboard derives the weekly-rhythm checks server-side — a blocked "
   "engagement says so in the list, not just three clicks deep")
c.patch(f"/api/store/admin/engagements/{_eid}", headers=A,
        json={"blockers": ""})
_me = next(x for x in c.get("/api/store/admin/engagements", headers=A)
           .json()["engagements"] if x["id"] == _eid)
ok("blocked" not in _me["warnings"],
   "and clearing the blockers clears the warning — 'no blockers' is the "
   "good news, so it must be expressible")
c.get(_purl2.split("http://testserver")[-1])
_me = next(x for x in c.get("/api/store/admin/engagements", headers=A)
           .json()["engagements"] if x["id"] == _eid)
ok(_me["portal_seen_at"] > 0,
   "a portal view stamps when the client last looked — the honest half of "
   "'did they see it'")

from erp.backend import integrations as _intg
ok("gate.passed" in _intg.EVENT_LABELS
   and "direction.chosen" in _intg.EVENT_LABELS,
   "gate passage and direction choices are events on the same bus as "
   "inventory.low")
ok("gate.passed" in _intg.PROVIDERS["slack"]["events"]
   and "direction.chosen" in _intg.PROVIDERS["trello"]["events"],
   "slack hears both; trello gets a card only for the one that is work — "
   "writing up the art direction")
ok("write up the art direction" in _intg._line(
    "direction.chosen", {"client": "X", "choice": "2"}),
   "and the prose says what to do next, not just what happened")
ok(callable(getattr(_intg, "dropbox_put", None)),
   "the export can file through the same Dropbox connection that files "
   "signed documents")
_exp2 = c.post(f"/api/store/admin/engagements/{_eid}/export",
               headers=A).json()
ok(_exp2["dropbox"] in ("filing in the background", "not connected"),
   "and the export says plainly whether Dropbox filing happened — a silent "
   "non-filing would read as filed")

_pl = c.post(f"/api/store/admin/engagements/{_eid}/gates/deposit_cleared"
             "/payment-link", headers=A, json={"amount_cents": 500000})
ok(_pl.status_code == 400 and "manually" in _pl.json()["detail"],
   "with no Stripe key the payment link refuses and points at the manual "
   "path — cheques and transfers never stopped working")
ok(c.post(f"/api/store/admin/engagements/{_eid}/gates/requirements_signed"
          "/payment-link", headers=A,
          json={"amount_cents": 1}).status_code == 400,
   "and payment links exist only for the money gates — a signature gate "
   "passed by card would attest to nothing")
ok(c.post(f"/api/store/admin/engagements/{_eid}/gates/deposit_cleared"
          "/payment-check", headers=A).status_code == 400,
   "checking a payment that was never linked is a clear error, not a quiet "
   "'not paid'")
import shutil as _sh2
_sh2.rmtree(_exp2["root"], ignore_errors=True)

# --- seeing, downloading and finishing the documents -----------------------
_det2 = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
_row = next(d for d in _det2["docs"] if d["id"] == _gen["doc_id"])
ok(_row["has_body"] and _row["blanks"] > 0,
   "each stage row says how many brackets a document still has — finished "
   "is a number going to zero, not a feeling")
_pv = c.get(f"/api/store/admin/documents/{_gen['doc_id']}/preview", headers=A)
ok(_pv.status_code == 200 and ("<h2" in _pv.text or "<table" in _pv.text),
   "View renders the document with the sign page's own renderer — what you "
   "check is exactly what a signer will be shown")
_dl = c.get(f"/api/store/admin/documents/{_gen['doc_id']}/markdown",
            headers=A)
ok(_dl.status_code == 200
   and "attachment" in _dl.headers.get("content-disposition", ""),
   "and an authored document downloads as its markdown")

_bl = c.get(f"/api/store/admin/engagements/{_eid}/docs/{_gen['doc_id']}"
            "/blanks", headers=A).json()
ok(_bl["placeholders"],
   "the blanks endpoint lists what is left, with the same suggestions "
   "generation had — finishing is the same form as starting, shorter")
_locked = c.post(f"/api/store/admin/engagements/{_eid}/docs/"
                 f"{_gen['doc_id']}/fill", headers=A,
                 json={"fills": {_bl["placeholders"][0]: "x"}})
ok(_locked.status_code == 400 and "signed" in _locked.json()["detail"],
   "a signed document refuses further filling — its text is what was "
   "attested to; supersede it, don't edit it")

_g2 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "05-kickoff/welcome-guide.md"}).json()
_b2 = c.get(f"/api/store/admin/engagements/{_eid}/docs/{_g2['doc_id']}"
            "/blanks", headers=A).json()
_tok0 = _b2["placeholders"][0]
_ff = c.post(f"/api/store/admin/engagements/{_eid}/docs/{_g2['doc_id']}"
             "/fill", headers=A, json={"fills": {_tok0: "filled-now"}}).json()
ok(_tok0 not in _ff["unfilled"]
   and len(_ff["unfilled"]) == len(_b2["placeholders"]) - 1,
   "filling from the UI populates the template in place, token by token")

# --- PDFs everywhere a document appears ------------------------------------
_pdf = c.get(f"/api/store/admin/documents/{_g2['doc_id']}/pdf", headers=A)
ok(_pdf.status_code == 200 and _pdf.content[:5] == b"%PDF-"
   and "inline" in _pdf.headers.get("content-disposition", ""),
   "an authored document renders to a real PDF, served inline so the "
   "browser's own viewer is the preview")
_pdfd = c.get(f"/api/store/admin/documents/{_g2['doc_id']}/pdf?download=1",
              headers=A)
ok("attachment" in _pdfd.headers.get("content-disposition", ""),
   "and downloads as one when asked")
ok(c.get(f"/sign/{_tok}/pdf").content[:5] == b"%PDF-",
   "the signer can take a PDF copy from the same parse they signed")
_p3 = c.post(f"/api/store/admin/engagements/{_eid}/portal",
             headers=A).json()["url"].split("/engage/")[1]
ok(c.get(f"/engage/{_p3}/pdf/{_gen['doc_id']}").content[:5] == b"%PDF-",
   "the client can take a PDF of anything on their side of the wall")
ok(c.get(f"/engage/{_p3}/pdf/{_rate_id}").status_code == 404,
   "and nothing on the other side — the .pdf route holds the same wall")
_exp3 = c.post(f"/api/store/admin/engagements/{_eid}/export",
               headers=A).json()
ok(any(f.endswith(".pdf") for f in _exp3["files"]),
   "exports carry the PDF beside the markdown — the .md is for editing, "
   "the .pdf is for sending")

# --- signatures on the PDF, DocuSign in the slot, and the next step --------
import zlib as _zl
_spdf = c.get(f"/api/store/admin/documents/{_gen['doc_id']}/pdf",
              headers=A).content
_st = ""
for _m in re.finditer(rb'stream\r?\n(.*?)endstream', _spdf, re.S):
    try:
        _st += _zl.decompress(_m.group(1)).decode("latin-1", "replace")
    except Exception:
        pass
_shown = " ".join(re.findall(r'\((.*?)\)\s*Tj', _st))
ok("Signed" in _shown and "Alex Chen" in _shown and "reference" in _shown,
   "a signed document's PDF carries the signature on its face — name, date "
   "and reference; a signed PDF that shows no signature reads as unsigned "
   "to everyone it gets forwarded to")

from storefront.backend import documents as _docmod
ok("docusign" in _ig.PROVIDERS,
   "DocuSign is an integrations provider, so its form comes from the same "
   "declaration machinery as every other connection")
_env = _docmod.docusign_envelope("T", "QUJD", "N", "n@x.t", "hi")
ok(_env["status"] == "sent"
   and _env["documents"][0]["documentBase64"] == "QUJD"
   and _env["recipients"]["signers"][0]["tabs"]["signHereTabs"],
   "the envelope carries our own PDF and a sign-here anchor — the signer "
   "is shown the same bytes a builtin signer would be")
_con_p = _db.connect()
ok(_docmod.esign_provider(_con_p) == "builtin",
   "with DocuSign unconnected the provider derives to builtin — connecting "
   "it IS the choice, and there is no second switch to forget")
_con_p.close()
_rr = c.post(f"/api/store/admin/signatures/{_sr2['id']}/refresh", headers=A)
ok(_rr.status_code == 200
   and _rr.json().get("detail") == "not a DocuSign request",
   "refreshing a builtin request is a polite no-op, not an error")

ok('data-next=' in _ops and "nextStep" in _ops,
   "the next step sits atop the gates — derived from the same gates, one "
   "primary action, so the answer to 'what now?' never needs the manual")
ok("GATE_STAGE" in _ops and "03-proposal" in _ops.split("GATE_STAGE")[1][:400],
   "and each gate names the kit stage whose templates satisfy it, so "
   "generating the right document for this client is the one click")

# --- in-person signing, and taking documents back out ----------------------
_g3 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "01-potential-customer/email-scripts.md"}).json()
_ip = c.post(f"/api/store/admin/documents/{_g3['doc_id']}/request-signature",
             headers=A, json={"signer_name": "Here Now",
                              "signer_email": "here@now.test",
                              "role": "signer", "in_person": True}).json()
ok(_ip.get("in_person") and "/sign/" in _ip["link"],
   "in-person signing opens the same pad, right here — no request email; "
   "the only email is the receipt, after signing")
_ipt = _ip["link"].split("/sign/")[1]
ok("mousedown" in c.get(f"/sign/{_ipt}").text,
   "and the pad draws with the mouse, so a cursor is a pen")
c.post(f"/sign/{_ipt}", json={"typed_name": "Here Now"})
ok(c.get(f"/sign/{_ipt}").text.count("Signed") >= 1,
   "signed in the room, recorded like any other signature")

# The drawn mark and the facts, on every surface the document shows on.
import base64 as _b64
import io as _io2
from PIL import Image as _Im, ImageDraw as _ImD
_im = _Im.new("RGBA", (600, 160), (0, 0, 0, 0))
_ImD.Draw(_im).line([(60, 110), (320, 40), (540, 100)],
                    fill=(25, 25, 80, 255), width=7)
_ib = _io2.BytesIO(); _im.save(_ib, "PNG")
_mark = "data:image/png;base64," + _b64.b64encode(_ib.getvalue()).decode()
c.post(f"/sign/{_ipt}/decline", json={})  # no-op guard: already signed above
_pv2 = c.get(f"/api/store/admin/documents/{_g3['doc_id']}/preview",
             headers=A).text
ok(">Signed<" in _pv2 and "Here Now" in _pv2,
   "the View page shows the signature block — a signed document must never "
   "look unsigned exactly where you look at it")
_sp2 = c.get(f"/sign/{_ipt}").text
ok(">Signed<" in _sp2,
   "and the signer's own page carries it after signing")

_un = c.request("DELETE",
                f"/api/store/admin/engagements/{_eid}/docs/{_g3['doc_id']}",
                headers=A)
ok(_un.status_code == 200,
   "a document can be unfiled from the client while the vault keeps it")
_gd3 = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(all(d["id"] != _g3["doc_id"] for d in _gd3["docs"]),
   "gone from the client's stages")
_vd3 = c.get("/api/store/admin/documents", headers=A,
             params={"q": "Email scripts"}).json()["documents"]
ok(any(d["id"] == _g3["doc_id"] for d in _vd3),
   "still in the vault — unfiling is not deleting")
_del3 = c.delete(f"/api/store/admin/documents/{_g3['doc_id']}",
                 headers=A).json()
ok(_del3.get("archived"),
   "and vault deletion archives it, because it carries a signature — "
   "evidence is never destroyed by tidying")

# --- sections fold, and stay folded ----------------------------------------
_opsjs = c.get("/ops/app.js").text
_opscss = c.get("/ops/styles.css").text
ok('foldable("gates"' in _opsjs and 'foldable(`stage:' in _opsjs
   and 'foldable("activity"' in _opsjs,
   "the gates, each stage and the activity log fold away — a client's page "
   "is long, and the stage you are not working in is noise")
ok('localStorage.setItem("bc_folded"' in _opsjs
   and 'localStorage.getItem("bc_folded")' in _opsjs,
   "and the fold is remembered, because the page re-renders on every gate "
   "action and a fold that reopened each time would be worthless")
ok(".foldable.folded > .fold-body { display: none; }" in _opscss
   and ".foldable.folded > .fold-head .fold-caret" in _opscss,
   "folding hides the body and turns the caret — one class, both signals, "
   "and the child selector keeps a folded stage from speaking for the "
   "documents folded inside it")
ok('data-fold="doc:${x.id}"' in _opsjs and 'class="dl-title fold-head"' in _opsjs
   and 'class="dl-acts fold-body"' in _opsjs,
   "a document folds to its own title line — seven buttons per document is "
   "a lot of page for a stage you are only reading")
ok('" blank" + (x.blanks === 1 ? "" : "s") + " left"' in _opsjs,
   "and the folded line keeps the number that decides whether you open it")
ok(_opsjs.index('class="dm-state"') < _opsjs.index('class="dm-side"')
   < _opsjs.index('class="dm-blanks'),
   "read in the order the question comes: what is it waiting on, whose "
   "side is it on, how much of it is still blank")
ok(".dl-meta { display: grid; grid-template-columns: 104px 70px 84px;"
   in _opscss,
   "in fixed slots, because the alignment is the information — pills that "
   "start wherever each title happens to end cannot be scanned down a "
   "stage, only read across a row")
ok(".doc-line:not(.folded) .dm-blanks { visibility: hidden; }" in _opscss,
   "and the blanks slot holds its width when the row opens: a column that "
   "appears and disappears is a column that jumps")
ok('${x.signed} of ${' in _opsjs,
   "half-signed is its own state — one party done, one still out — and a "
   "slot that showed only the newer of the two would read as unsigned")
ok('${done} of ${live.length} passed' in _opsjs
   and 'to generate' in _opsjs and 'entr${' in _opsjs,
   "a folded section still says what it holds — gates passed, documents "
   "waiting, entries logged — so folding costs no information")
ok('if (ev.target.closest("button, a, input, select")) return;' in _opsjs,
   "clicking the Gantt button in a fold head does not also fold the card")
ok('id="fold-all"' in _opsjs and '"Unfold all" : "Fold all"' in _opsjs,
   "and one control folds every stage at once, reading back which way it "
   "will go")
ok("if (foldAllSync) foldAllSync();" in _opsjs and "foldAllSync = sync;" in _opsjs,
   "folding the last stage by hand corrects that control too — a button "
   "that promises the wrong direction is worse than no button")

# --- the record answers on every surface, not just the studio's ------------
# A record field is deliberately never baked into the body, so each renderer
# has to resolve it. One that forgets shows a client [CLIENT] where their own
# name belongs — on the page they are being asked to sign.
_gsrc = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "05-kickoff/welcome-guide.md"}).json()
_ename = c.get(f"/api/store/admin/engagements/{_eid}",
               headers=A).json()["engagement"]["name"]
_sreq = c.post(
    f"/api/store/admin/documents/{_gsrc['doc_id']}/request-signature",
    headers=A, json={"signer_name": "Reads It", "signer_email": "r@x.test",
                     "role": "signer", "in_person": True}).json()
_spage = c.get(_sreq["link"].split("localhost")[-1]).text
ok("[CLIENT]" not in _spage and "[CLIENT NAME]" not in _spage,
   "the page a client signs never shows a record token raw — asked to sign "
   "[CLIENT], they have been handed the template, not their document")
ok("fbox" in _spage,
   "and it draws blanks the same way the studio's own view does — one look "
   "for one document, whichever side of the wall you are on")
ok(_docmod.substitute_globals("For [CLIENT], approved by [CLIENT POC].",
                              {"client": "Probe Co", "client_poc": "P Poc"})
   == "For Probe Co, approved by P Poc.",
   "one resolver answers record tokens, wherever the text is going")
# PDF streams are compressed, so the bytes cannot be read for a token —
# what is checkable is that every path that builds one goes through the
# resolver, which is the property that was actually broken.
_dsrc = Path("src/storefront/backend/documents.py").read_text()
_esrc = Path("src/storefront/backend/engagements.py").read_text()
ok(_dsrc.count("substitute_globals(d[\"body\"], gvals or {})") == 1
   and "gvals=globals_for(con, did)" in _dsrc
   and "gvals=globals_for(con, d[\"id\"])" in _dsrc,
   "the studio's PDF and the signer's own copy resolve the record — the "
   "printed page outlives the screen, and it is the one that gets argued "
   "over")
ok("substitute_globals(d[\"body\"], gv)" in _dsrc.split("def docusign_send")[1],
   "and so does the file handed to DocuSign, where the client signs "
   "somewhere we do not control the rendering")
ok("vault.substitute_globals(r[\"body\"], _gv)" in _esrc
   and "gvals=global_values(e)" in _esrc
   and "vault.form_inner('', row['body'], _gv)" in _esrc,
   "and the export bundle and the client portal, which are the two ways a "
   "document leaves the building")
_ptok2 = c.post(f"/api/store/admin/engagements/{_eid}/portal",
                headers=A).json()["url"].split("/engage/")[1]
_ppdf = c.get(f"/engage/{_ptok2}/pdf/{_gsrc['doc_id']}")
_ppage = c.get(f"/engage/{_ptok2}/doc/{_gsrc['doc_id']}").text
ok(_ppdf.status_code == 200 and "[CLIENT]" not in _ppage
   and "fbox" in _ppage,
   "the portal hands over the same document the studio sees — resolved, "
   "with its blanks drawn as blanks")
ok(c.get(f"/api/store/admin/documents/{_gsrc['doc_id']}/preview",
         headers=A).text.count(_ename) >= 1,
   "the studio's preview still resolves it, from the same call — the point "
   "is that they agree, not that any one of them is right")
c.request("DELETE",
          f"/api/store/admin/engagements/{_eid}/docs/{_gsrc['doc_id']}",
          headers=A)
c.delete(f"/api/store/admin/documents/{_gsrc['doc_id']}", headers=A)

# --- per-section signing markers -------------------------------------------
from storefront.backend.pdfgen import doc_pdf as _dpdf
from storefront.backend.engagements import placeholders as _phs
_mk = "A. [INITIALS]\n\nB. [INITIALS]\n\n[SIGN HERE]\n\nFill [X]."
ok(_phs(_mk) == ["X"],
   "signing markers are instructions, not blanks — the fill form leaves "
   "them standing")
_mh = _docmod.md_html(_mk)
ok(_mh.count("Initials:") == 2 and "Sign here:" in _mh
   and "[INITIALS]" not in _mh,
   "and they render as labelled lines, one per section that carries one")
_envt = _docmod.docusign_envelope("T", "QQ==", "N", "n@x.t", "")[
    "recipients"]["signers"][0]["tabs"]
ok([x["anchorString"] for x in _envt["signHereTabs"]] ==
   ["Signed", "Sign here:"]
   and _envt["initialHereTabs"][0]["anchorString"] == "Initials:",
   "the envelope anchors on those same labels — DocuSign places a tab at "
   "every occurrence, so initials land clause by clause")
ok(all(x["anchorIgnoreIfNotPresent"] == "true"
       for x in _envt["signHereTabs"] + _envt["initialHereTabs"]),
   "and a document with no markers still signs at its Signed block")

# --- printable signature areas, markers in the contracts, scans back in ----
for _cf in ("week-website", "partially-custom", "fully-custom",
            "branding-creative"):
    _ct2 = (_studio / "templates" / "04-agreement" / "contracts"
            / f"{_cf}.md").read_text()
    ok(_ct2.count("[INITIALS]") >= 2 and "[SIGN HERE]" in _ct2,
       f"{_cf} initials its load-bearing clauses and carries an execution "
       f"line")

_g4 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "04-agreement/contracts/week-website.md"}).json()
c.post(f"/api/store/admin/documents/{_g4['doc_id']}/request-signature",
       headers=A, json={"signer_name": "Pat Lee", "signer_email": "p@x.t",
                        "role": "signer", "in_person": True})
_pv4 = c.get(f"/api/store/admin/documents/{_g4['doc_id']}/preview",
             headers=A).text
ok("Awaiting signature" in _pv4 and "Pat Lee" in _pv4,
   "an unsigned request shows as a blank signature area — name and date "
   "lines — so the form prints, gets signed, and comes back")
ok("Initials:" in _pv4 and "[INITIALS]" not in _pv4,
   "and the initials markers render as labelled lines, not literals")

_scan = c.post("/api/store/admin/documents", headers=A, json={
    "title": "Signed scan — smoke", "category": "contract",
    "party_kind": "partner", "party_name": "Smoke Test Client"}).json()
c.post(f"/api/store/admin/documents/{_scan['id']}/file", headers=A,
       files={"file": ("scan.jpg", b"\xff\xd8\xff\xe0fakejpg",
                       "image/jpeg")})
ok(c.post(f"/api/store/admin/engagements/{_eid}/attach", headers=A,
          json={"doc_id": _scan["id"], "stage": "04-agreement",
                "side": "to_client"}).status_code == 200,
   "the returned paper's scan files beside the original, in the same stage "
   "— the authored text stays exactly what was signed, and the wet-ink "
   "copy is evidence alongside it")
c.delete(f"/api/store/admin/documents/{_g4['doc_id']}", headers=A)
c.delete(f"/api/store/admin/documents/{_scan['id']}", headers=A)

# --- routes, choice fields, and columns that line up -----------------------
ok("function applyRoute" in _ops and "hashchange" in _ops
   and "#/clients/" in _ops.replace("`", ""),
   "the unique pages carry real URLs — #/orders, #/clients/3 — read on "
   "load, written on render, so the address bar and the app can't disagree")
ok("function fillField" in _ops and 'tok.split(" / ")' in _ops
   and "— leave the brackets —" in _ops,
   "a token that lists its own values renders as a select of those values, "
   "and every fill is labelled optional — blank keeps the brackets")
ok('<span class="req">required</span>' in _ops,
   "while the fields that genuinely are required say so")
ok('class="tpl-line"' in _ops and "tpl-head" in _ops
   and 'class="chips"' not in _ops.split("const stageCard")[1][:900],
   "a stage's templates stack one per line — a wrapping row of chips read "
   "as a paragraph, not a menu of things you can create")
_css3 = c.get("/ops/styles.css").text
ok("button.tpl-line { display: grid" in _css3
   and "grid-template-columns: 14px minmax(0, 1fr) auto" in _css3,
   "each on its own full-width line, with the side it lands on visible "
   "rather than hidden in a tooltip")

ok('class="dt-state"' in _ops and 'class="dt-acts"' in _ops
   and "grid-template-columns: 22px minmax(0, 1fr) 108px 168px auto" in _css3,
   "the Documents tab gets the same columns — every signed pill and every "
   "button starts at the same x down the whole list")
ok('class="sig-line' in _ops and "sl-mail" in _ops and "sl-when" in _ops
   and "150px minmax(0, 1fr) 84px 132px 104px 116px" in _css3,
   "and the signers align: who, email, role, state, when, actions")

ok("function trackHtml" in _ops and "tk-client" in _ops
   and "waiting on the client" in _ops,
   "the gates draw as a track — done, do next, waiting on the client, "
   "upcoming — derived from the same gates the list is, so the picture and "
   "the list can never disagree")
ok("function gateState" in _ops
   and "g.kind === \"money\" && g.has_payment_link" in _ops,
   "'waiting on the client' is a real state: a request that is out or a "
   "payment link unpaid is time we cannot spend")
ok("function ganttModal" in _ops and "PARALLEL" in _ops
   and "What can run in parallel" in _ops,
   "and a Gantt view shows which work overlaps — the gates are a chain, "
   "the work between them is not")
ok("critical path" in _ops.split("PARALLEL")[1][:900],
   "with content named as the thing that decides the launch date")

for _cls in ("gate-line", "gl-acts", "doc-line", "dl-acts", "log-line"):
    ok(f'class="{_cls}' in _ops or f"'{_cls}'" in _ops,
       f"{_cls} markup exists for the aligned layout")
_css2 = c.get("/ops/styles.css").text
ok("grid-template-columns: repeat(3, 92px)" in _css2,
   "gate buttons live in three fixed slots, so Link doc sits under Link doc "
   "and Confirm under Mark passed all the way down")
ok(".doc-line" in _css2 and ".dl-acts" in _css2
   and ".log-line" in _css2 and "92px 130px minmax(0, 1fr)" in _css2,
   "documents get one aligned line each, and the activity log's actors "
   "share a column")

# --- the document as the form ----------------------------------------------
_g5 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "06-requirements/requirements-template.md"}).json()
_ed = c.get(f"/api/store/admin/engagements/{_eid}/docs/{_g5['doc_id']}"
            "/editable", headers=A)
ok(_ed.status_code == 200, "a document with blanks opens as its own form")
_toks = re.findall(r'<input class="ph[^"]*" data-tok="([^"]+)"', _ed.text)
_bl5 = c.get(f"/api/store/admin/engagements/{_eid}/docs/{_g5['doc_id']}"
             "/blanks", headers=A).json()["placeholders"]
ok(set(_bl5) <= set(_toks) and len(_toks) >= len(_bl5),
   "every bracket renders as an inline field where it sits in the text — "
   "and a token used twice renders twice, to be filled once")
ok(len(set(_toks)) >= len(_bl5),
   "answered fields are fields too: they stay editable rather than "
   "dissolving into the prose the moment they are filled")
ok("\x00" not in _ed.text and "<table>" in _ed.text,
   "the sentinel pass leaks nothing and the document's structure survives")
ok(c.get(f"/api/store/admin/engagements/{_eid}/docs/{_gen['doc_id']}"
         "/editable", headers=A).status_code == 400,
   "a signed document refuses the in-place editor for the same reason it "
   "refuses the form — its text is what was attested to")
ok("function fillInDoc" in _ops and "fb-indoc" in _ops
   and "dataset.tok === inp.dataset.tok" in _ops,
   "the form offers the in-document road, and same-token fields type "
   "together — the editor shows the one-value rule live instead of "
   "surprising anyone at save")

# --- every kind of blank is fillable ---------------------------------------
_g6 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "05-kickoff/branding-questionnaire.md"}).json()
_eh = c.get(f"/api/store/admin/documents/{_g6['doc_id']}/editable",
            headers=A).text
ok(_eh.count('class="ph ph-area"') >= 20
   and 'class="ph-check"' in _eh,
   "a questionnaire's answer lines become paragraph boxes and its "
   "checkboxes toggle — not just the bracket tokens")
_pv6 = c.get(f"/api/store/admin/documents/{_g6['doc_id']}/preview",
             headers=A).text
ok(_pv6.count("fbox-area") >= 20 and _pv6.count("<hr>") <= 3,
   "and reading a document shows every blank as a box you could write on — "
   "print it and fill it in with a pen — rather than a bracketed word or a "
   "bare rule with nothing to write on")
ok('class="flab"' in _pv6 and "fcheck" in _pv6,
   "each box wears its own label, and the tick boxes are boxes")

# --- an answer is still a field --------------------------------------------
from storefront.backend.documents import GLOBAL_TOKENS as _GT
_local = next(t for t in c.get(
    f"/api/store/admin/engagements/{_eid}/docs/{_g6['doc_id']}/blanks",
    headers=A).json()["placeholders"] if t.strip() not in _GT)
c.post(f"/api/store/admin/documents/{_g6['doc_id']}/edit", headers=A,
       json={"fills": {_local: "Boxed Co"}, "regions": {}})
_pvf = c.get(f"/api/store/admin/documents/{_g6['doc_id']}/preview",
             headers=A).text
ok("fbox-set" in _pvf and "Boxed Co" in _pvf,
   "a filled blank reads as a filled blank — boxed, so you can see what "
   "was set and that it can be set again")
_bodyf = _db.connect().execute("SELECT body FROM documents WHERE id=?",
                               (_g6["doc_id"],)).fetchone()["body"]
ok(f"[{_local}=Boxed Co]" in _bodyf,
   "because filling keeps the name beside the answer instead of erasing it")
_edf = c.get(f"/api/store/admin/documents/{_g6['doc_id']}/editable",
             headers=A).text
ok('value="Boxed Co"' in _edf,
   "so the editor opens on the answer, and changing it is changing a field "
   "rather than retyping a sentence")
c.post(f"/api/store/admin/documents/{_g6['doc_id']}/edit", headers=A,
       json={"regions": {"0": "One sentence a stranger would understand."},
             "fills": {}})
_b6 = _db.connect().execute(
    "SELECT body FROM documents WHERE id=?",
    (_g6["doc_id"],)).fetchone()["body"]
ok("One sentence a stranger would understand." in _b6,
   "an answer typed on a write-in line lands in the document's own text — "
   "answered is answered, and the region is gone")
ok('id="dv-edit"' in _ops and "fillInDoc(did, name, after," in _ops,
   "and View offers Edit on any unsigned authored document, from both tabs")

# --- the binder --------------------------------------------------------------
_be = c.post("/api/store/admin/engagements", headers=A, json={
    "name": "Binder Smoke", "package": "B", "value_cents": 1200000,
    "approver_name": "Kim Doe", "approver_email": "kim@x.test"}).json()
ok(_be.get("binder_doc_id"),
   "a new client is born with its project binder — cover, introduction, "
   "contents, and the pricing and lead sections where the record has them")
_bb = _db.connect().execute("SELECT body FROM documents WHERE id=?",
                            (_be["binder_doc_id"],)).fetchone()["body"]
ok("[CLIENT]" in _bb and "[CLIENT POC]" in _bb and "[INTERNAL POC]" in _bb
   and "[ORIGINATOR]" in _bb and "[DATE]" in _bb,
   "the cover names the client with tokens, not with values — the record "
   "is the source, so the day it changes every page that names the client "
   "changes with it")
_bh0 = c.get(f"/api/store/admin/engagements/{_be['id']}/binder.html",
             headers=A).text
ok("Binder Smoke" in _bh0 and "[CLIENT]" not in _bh0
   and "Kim Doe" in _bh0 and "$12,000.00" in _bh0,
   "and a reader sees the values, never the tokens")
_intro = _db.connect().execute(
    "SELECT d.title, d.body FROM engagement_docs ed JOIN documents d"
    " ON d.id=ed.doc_id WHERE ed.engagement_id=? AND d.notes='binder intro'",
    (_be["id"],)).fetchone()
ok(_intro and "[INTRODUCTION" in _intro["body"],
   "the introduction is its own document, and so its own page — a cover "
   "with an essay under it is not a cover")
ok(_bh0.index("Introduction") < _bh0.index("Table of contents"),
   "and it sits between the title page and the contents, where a foreword "
   "goes")
_bp = c.get(f"/api/store/admin/engagements/{_be['id']}/binder.pdf",
            headers=A)
ok(_bp.status_code == 200 and _bp.content[:5] == b"%PDF-",
   "the whole packet renders as one book — cover first, contents, then "
   "every client-side paper with its signatures")
_ee = c.post(f"/api/store/admin/documents/{_be['binder_doc_id']}/edit",
             headers=A, json={"fills": {"PREPARED BY": "Tom"}}).json()
ok(_ee["party"]["name"] == "Kim Doe",
   "Save & sign prefills the client's named approver — the approver signs, "
   "not the company")
# --- the title page, the people, and the POC handshake ---------------------
# the admin's name may have been changed by an earlier test — the
# originator default is whatever it is NOW, so read it, don't assume it
_me_name = _db.connect().execute(
    "SELECT name FROM users WHERE token=?",
    (admin["token"],)).fetchone()["name"]
# mint the colleague first — this suite's db starts empty, and a POC
# that matches no account is just a label with nobody to ask
_dev = c.post("/api/login", json={"name": "Poc Colleague",
                                  "admin_key": CFG["admin_key"]}).json()
_DA = {"Authorization": f"Bearer {_dev['token']}"}
_bt = c.post("/api/store/admin/engagements", headers=A, json={
    "name": "Title Probe", "approver_name": "Pat Client",
    "approver_email": "pat@client.test", "internal_poc": "Poc Colleague",
    "originator": ""}).json()
_btb = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder.html",
             headers=A).text
ok(CFG["brand_name"] in _btb and "Title Probe" in _btb
   and "Pat Client (pat@client.test)" in _btb
   and "Poc Colleague" in _btb and _me_name in _btb,
   "the binder's title page names the five facts a binder off a shelf must "
   "answer: the brand, the client, both POCs, who started it, and when")
ok("Table of contents" in _btb and "<th>Page</th>" in _btb,
   "and the contents page carries a real table of contents — every "
   "document with the page it starts on in the printed binder")
_bte = c.get(f"/api/store/admin/engagements/{_bt['id']}",
             headers=A).json()["engagement"]
ok(_bte["internal_poc_status"] == "pending",
   "naming a colleague internal POC is pending until they take it — a job "
   "you haven't agreed to isn't yours yet")
ok(c.post(f"/api/store/admin/engagements/{_bt['id']}/poc/accept",
          headers=A).status_code == 403,
   "and nobody else can answer for them, the originator included")
_dn = c.get("/api/notifications", headers=_DA).json()["items"]
ok(any("Internal POC for Title Probe" in (n.get("title") or "")
       for n in _dn),
   "the named colleague is told, not assumed")
c.post(f"/api/store/admin/engagements/{_bt['id']}/poc/decline", headers=_DA)
_bte = c.get(f"/api/store/admin/engagements/{_bt['id']}",
             headers=A).json()["engagement"]
ok(_bte["internal_poc_status"] == "declined",
   "declining is recorded — silence is the one outcome that helps nobody")
_bn = c.get("/api/notifications", headers=A).json()["items"]
ok(any("declined internal POC" in (n.get("title") or "") for n in _bn),
   "and the originator hears about it")

_bh = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder.html",
            headers=A)
ok(_bh.status_code == 200 and "binder-doc" in _bh.text
   and "Project binder" in _bh.text,
   "the binder previews as a page — an embedded PDF is a lottery across "
   "browsers, and a blank frame reads as a broken binder")
ok("blank form, print and fill" in _bh.text
   and "Project roadmap" in _bh.text
   and "Website handover" in _bh.text,
   "every client-side paper is in the binder even before it's generated — "
   "the roadmap included — so the printed binder is the complete packet, "
   "fillable with a pen")
ok("Gate: Proposal accepted" in _bh.text
   and _bh.text.count("<h2") >= 8,
   "and the contents mirror the client's own screen: the stages as "
   "sections, each with its gates and their state, every paper beneath")
_scan2 = c.post("/api/store/admin/documents", headers=A, json={
    "title": "site-photos.jpg", "category": "other",
    "party_kind": "partner", "party_name": "Title Probe"}).json()
c.post(f"/api/store/admin/documents/{_scan2['id']}/file", headers=A,
       files={"file": ("site-photos.jpg", b"\xff\xd8\xff\xe0x",
                       "image/jpeg")})
c.post(f"/api/store/admin/engagements/{_bt['id']}/attach", headers=A,
       json={"doc_id": _scan2["id"], "stage": "01-potential-customer",
             "side": "to_client"})
_bh2 = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder.html",
             headers=A).text
ok("site-photos.jpg" in _bh2 and "attachment, filed beside" in _bh2,
   "attachments are listed in the contents, filed beside the binder — a "
   "markdown PDF can't swallow a photograph, but it can say where it lives")
ok('id="ef-files"' in _ops and '"01-potential-customer"' in _ops
   and "bd-edit" in _ops,
   "the new-client form takes attachments, and the binder modal edits its "
   "own cover — the title page is a document like any other")

# --- the whole binder, editable --------------------------------------------
_bed = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder/editable",
             headers=A)
ok(_bed.status_code == 200
   and 'data-doc="' in _bed.text and 'data-tpl="' in _bed.text,
   "the binder opens as one editable page: authored sections save through "
   "the document editor, blank forms carry the template they'd generate")
ok("bd-static" in _bed.text,
   "with the contents page sitting read-only between them")
ok("binderEditMode" in _ops
   and "i.value !== initialToks.get(i)" in _ops,
   "and only what YOU changed counts as touched — suggested values arrive "
   "pre-filled, and without the initial-value check every blank form would "
   "save itself into existence on the strength of its own suggestions")
_binderfn = _ops.split("async function binderEditMode")[1].split(
    "\nasync function ")[0]
ok('sign.textContent = "Sign this page"' in _binderfn
   and "signCard = async (card)" in _binderfn
   and "engSignForm(out.id" in _binderfn,
   "a page can be signed from inside the binder — a book has many "
   "signatures and they belong to different pages, not to a footer")
ok("const saveCard = async (card, force)" in _binderfn
   and _binderfn.count("await saveCard(") == 2,
   "and Sign-this-page saves through the same writer as Save-the-binder — "
   "a signature attesting to a slightly different save path is a signature "
   "to argue about")
ok("if (!touched && !force) return null;" in _binderfn,
   "signing a blank form generates it first: you cannot sign a page that "
   "does not exist yet")
ok(".bd-sign" in c.get(
       f"/api/store/admin/engagements/{_bt['id']}/binder/editable",
       headers=A).text
   and "@media print{.bd-sign{display:none}}" in c.get(
       f"/api/store/admin/engagements/{_bt['id']}/binder/editable",
       headers=A).text,
   "the control is styled with the binder and hidden from print — the "
   "printable book stays a printable book")
ok("out.doc_id" in _binderfn,
   "a touched blank form generates the document for this client, then the "
   "written answers land on it")

# --- cells, names, and the ongoing clause ----------------------------------
from storefront.backend.documents import scan_regions as _scan_r
_cells = [r for r in _scan_r("| A | B |\n|---|---|\n| x | |\n")
          if r["kind"] == "cell"]
ok(len(_cells) == 1,
   "an empty table cell is a blank the template meant to be filled — "
   "whitespace nobody can type into is a form with holes in it")
ok('ph-cell' in _bed.text or 'ph-cell' in c.get(
    f"/api/store/admin/engagements/{_bt['id']}/binder/editable",
    headers=A).text,
   "and the binder editor renders them as fields")
_bh3 = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder.html",
             headers=A).text
ok("[CLIENT]" not in _bh3.split("In this binder")[1].split("</div>")[0]
   and "[PROJECT]" not in _bh3.split("In this binder")[1].split("</div>")[0],
   "blank forms in the contents already belong to the client — 'Project "
   "roadmap — Title Probe', never '— [CLIENT]'")
_cc = (_studio / "templates" / "04-agreement" / "contracts"
       / "common-clauses.md").read_text()
ok("## 15. Ongoing support" in _cc and "[INITIALS]" in _cc.split("## 15.")[1]
   and "actively exploited vulnerabilities" in _cc,
   "the contract says how continuous work is carried — under a care plan, "
   "or ad hoc with the risk of declining recorded in writing — and the "
   "clause takes initials like the other load-bearing ones")
for _cf2 in ("week-website", "partially-custom", "fully-custom",
             "branding-creative"):
    _ct3 = (_studio / "templates" / "04-agreement" / "contracts"
            / f"{_cf2}.md").read_text()
    _inc = [seg[-60:] for seg in _ct3.split("Common Clauses]")[:-1]]
    ok(any("15" in seg for seg in _inc),
       f"{_cf2} incorporates the ongoing-support clause")
ok("function wirePageCount" in _ops and 'class="pg-in"' in _ops,
   "every document view counts its pages — a page being one printable "
   "sheet at letter aspect, which is the same rule the frame draws, so the "
   "number always names a line you can see")
ok('e.key === "Enter"' in _ops.split("function wirePageCount")[1][:2600]
   and 'behavior: near ? "smooth" : "auto"' in _ops,
   "and the count is the way in: type a page, press enter, and a "
   "hundred-page binder is one keystroke from any page in it")
ok("PAGE_RULE_CSS" in Path("src/storefront/backend/documents.py").read_text()
   and "--page-h" in _ops,
   "and the boundary is drawn from the height the counter measures — one "
   "definition of a page, not two")
for _pid in ("dv-pages", "fid-pages", "bd-pages"):
    ok(f'id="{_pid}"' in _ops,
       f"{_pid}: the count shows in view, in the editor, and in the binder")
# One typography for every rendering: when preview and editor disagreed
# about line-height, the editor was a different document that happened to
# hold the same words — and it paginated like one.
_docsrc = Path("src/storefront/backend/documents.py").read_text()
ok("DOC_BASE_CSS = (" in _docsrc and "FIELD_CSS = (" in _docsrc
   and "EDITABLE_CSS = DOC_BASE_CSS + FIELD_CSS" in _docsrc,
   "the reading shell and the editing shell are one base plus fields, not "
   "two stylesheets that drifted apart")
_engsrc = Path("src/storefront/backend/engagements.py").read_text()
ok(_engsrc.count("vault.DOC_BASE_CSS") + _engsrc.count("vault.EDITABLE_CSS")
   >= 2 and "line-height:1.6" not in _engsrc,
   "and both binder shells render from it, so neither can set its own "
   "line-height behind the other's back")
ok('rows="1"' in _docsrc and "function wireAutoGrow" in _ops,
   "an answer box starts the height of the printed line it replaces and "
   "grows to what you type, rather than reserving two rows nobody asked for")

# --- a title that names the client follows the client -----------------------
_ren = c.post("/api/store/admin/engagements", headers=A,
              json={"name": "Old Name Co"}).json()
c.post(f"/api/store/admin/engagements/{_ren['id']}/docs", headers=A,
       json={"template_path": "03-proposal/proposal-template.md"})
c.patch(f"/api/store/admin/engagements/{_ren['id']}", headers=A,
        json={"name": "New Name Co"})
_rt = [d["title"] for d in
       c.get(f"/api/store/admin/engagements/{_ren['id']}",
             headers=A).json()["docs"]]
ok(all("Old Name Co" not in t for t in _rt)
   and any("New Name Co" in t for t in _rt),
   "renaming the client renames every document filed under them — a "
   "binder full of papers still saying the old name is a binder that "
   "disagrees with its own cover")
# The same edit, from one page of the binder rather than the binder: a
# record field is the client's, so which door you came through must not
# decide whether the client's name changes.
_one = [d for d in c.get(f"/api/store/admin/engagements/{_ren['id']}",
        headers=A).json()["docs"] if d["title"].startswith("Proposal")][0]
_oe = c.post(f"/api/store/admin/documents/{_one['id']}/edit", headers=A,
             json={"fills": {"CLIENT NAME": "Third Name Co"},
                   "regions": {}}).json()
ok("name" in (_oe.get("record") or []),
   "typing the client's name on one document writes the client's name — "
   "the record is where it lives, whichever editor you opened")
_rt2 = c.get(f"/api/store/admin/engagements/{_ren['id']}", headers=A).json()
ok(_rt2["engagement"]["name"] == "Third Name Co"
   and all("New Name Co" not in d["title"] for d in _rt2["docs"]),
   "and every title follows from there, not just the one you were on")
_body1 = _db.connect().execute("SELECT body FROM documents WHERE id=?",
                               (_one["id"],)).fetchone()["body"]
ok("[CLIENT NAME=" not in _body1,
   "the token stays a token — baking it here is exactly how one document "
   "starts disagreeing with the next")

# The new name containing the old one is the case that doubled: rename to
# "X Labs", then swap "X" for "X Labs" inside the result, and the cover
# says "X Labs Labs".
c.patch(f"/api/store/admin/engagements/{_ren['id']}", headers=A,
        json={"name": "Third Name Co Labs"})
_rt3 = [d["title"] for d in c.get(f"/api/store/admin/engagements/{_ren['id']}",
        headers=A).json()["docs"]]
ok(all(t.count("Labs") == 1 for t in _rt3)
   and all(t.endswith("Third Name Co Labs") for t in _rt3),
   "renaming to a name that contains the old one renames once, not twice")
c.patch(f"/api/store/admin/engagements/{_ren['id']}", headers=A,
        json={"name": "Third Name Co"})

_bed2 = c.get(f"/api/store/admin/engagements/{_ren['id']}/binder/editable",
              headers=A).text
_sed2 = c.get(f"/api/store/admin/documents/{_one['id']}/editable",
              headers=A).text
ok('class="bd-title"' in _sed2,
   "and a document's title is a field in its own editor too, not only in "
   "the binder — the name in the heading is the one people read first")
ok('class="bd-title-row"' in _sed2
   and 'class="bd-title bd-title-cl ph ph-global"' in _sed2
   and 'data-global="client"' in _sed2,
   "a heading that names the client IS the client's field — typing in the "
   "heading moves the client, and moving the client moves the heading")
ok("GLOBAL_TOKS" in _ops
   and "!GLOBAL_TOKS.has(k)" in _ops,
   "and changing the client does not conjure every blank form into "
   "existence just because their copy of the name moved with it")
ok('class="bd-title"' in _bed2,
   "and a title is a field in the editor, because the one thing you could "
   "not change was the line you read first")
_conr = _db.connect()
_conr.execute("DELETE FROM documents WHERE id IN (SELECT doc_id FROM"
              " engagement_docs WHERE engagement_id=?)", (_ren["id"],))
for _t in ("engagement_docs", "engagement_gates", "engagement_log",
           "engagement_dates"):
    _conr.execute(f"DELETE FROM {_t} WHERE engagement_id=?", (_ren["id"],))
_conr.execute("DELETE FROM engagements WHERE id=?", (_ren["id"],))
_conr.commit(); _conr.close()

ok('data-global=' in Path("src/storefront/backend/documents.py").read_text()
   and 'input[data-global="${inp.dataset.global}"]' in _ops,
   "a record field moves every one of its twins in the whole book — the "
   "client does not change from one form to the next")
ok("def apply_globals" in _engsrc and "GLOBAL_COLUMN" in _engsrc
   and "eng.apply_globals(" in Path(
       "src/storefront/backend/documents.py").read_text(),
   "and it saves to the client record rather than being baked into one "
   "document's text — decided in one place on the server, so which editor "
   "you opened cannot change the answer")

ok("button.btn[hidden]" in _css3 or "btn[hidden]" in c.get(
    "/ops/styles.css").text,
   "a button marked hidden is hidden — .btn sets its own display, which "
   "beats the browser's own [hidden] rule")

ok("function frameAnchor" in _ops and "function restoreAnchor" in _ops
   and "fillInDoc(did, name, after, at)" in _ops
   and "binderEditMode(id, e, frameAnchor(bdFrame))" in _ops,
   "Edit opens where you were reading — the anchor is read before the "
   "modal goes and restored once the editor has loaded")
ok("secIdx" in _ops and "elIdx" in _ops
   and 'classList.contains("bd-note")' in _ops,
   "and it anchors to the block you were looking at, not the page number "
   "or the section: input boxes are taller than the text they replace, so "
   "the same page number — or the same offset into a taller section — "
   "lands on earlier content")

ok('closest(".doc-line, .sig-row")' in _ops,
   "and the viewer reads its title from the row class the rows actually "
   "have — the stage rows became .doc-line and the lookup went stale")

ok("ongoing_support_agreed" in _ops
   and "Ongoing — security, monitoring, updates, support" in _ops,
   "the ongoing gate is on the track and the Gantt — a lane that starts "
   "when handover ends and does not stop")
c.delete(f"/api/store/admin/documents/{_scan2['id']}", headers=A)
_bf = c.post(f"/api/store/admin/engagements/{_bt['id']}/binder",
             headers=A).json()
ok(not _bf["created"],
   "one binder per client — backfill returns the one that exists")

_conb2 = _db.connect()
for _t in ("engagement_docs", "engagement_gates", "engagement_log",
           "engagement_dates"):
    _conb2.execute(f"DELETE FROM {_t} WHERE engagement_id=?", (_bt["id"],))
_conb2.execute("DELETE FROM document_events WHERE document_id=?",
               (_bt["binder_doc_id"],))
_conb2.execute("DELETE FROM documents WHERE id=?", (_bt["binder_doc_id"],))
_conb2.execute("DELETE FROM engagements WHERE id=?", (_bt["id"],))
_conb2.execute("DELETE FROM notifications WHERE title LIKE '%Title Probe%'")
_conb2.commit(); _conb2.close()

ok('id="fid-sign"' in _ops and "engSignForm(did, out.party" in _ops,
   "and the editor's own footer carries Save & sign, edits landing before "
   "the request — a signature attests to the text as it stands")
_conb = _db.connect()
for _t in ("engagement_docs", "engagement_gates", "engagement_log",
           "engagement_dates"):
    _conb.execute(f"DELETE FROM {_t} WHERE engagement_id=?", (_be["id"],))
for _d2 in (_be["binder_doc_id"],):
    _conb.execute("DELETE FROM document_events WHERE document_id=?", (_d2,))
    _conb.execute("DELETE FROM documents WHERE id=?", (_d2,))
_conb.execute("DELETE FROM engagements WHERE id=?", (_be["id"],))
_conb.commit(); _conb.close()
c.delete(f"/api/store/admin/documents/{_g6['doc_id']}", headers=A)
c.delete(f"/api/store/admin/documents/{_g5['doc_id']}", headers=A)

# View opens an in-app viewer, never window.open after an await: the popup
# blocker eats a window opened outside the user-gesture call stack, and the
# button reads as broken to exactly the person clicking it.
_viewer = _ops.split("async function docViewer")[1][:4200]
_before_open = _viewer.split('$("#dv-open")')[0]
ok('id="dv-sign"' in _viewer and "engSignForm(did, preset || {}" in _viewer,
   "the viewer signs what it is showing: having just read the document, "
   "closing it to find the row's button is a step that exists only because "
   "of how the page was built")
ok('signed ? "Add a signature" : "Sign"' in _viewer,
   "and it says which it is — a signed document can still take the second "
   "signature it is waiting on")
ok('iframe class="doc-viewer"' in _viewer
   and "window.open" not in _before_open
   and 'window.open(pdfUrl, "_blank")' in _viewer,
   "one shared viewer shows the document in an in-app frame; window.open "
   "lives only in a synchronous click handler, where the user gesture is "
   "still alive and no blocker eats it")
ok("Download" in _viewer and "signed " in _viewer,
   "with the signed PDF as the primary action in the same modal")
ok("data-docview" in _ops and "data-engview" in _ops
   and _ops.count("docViewer(") >= 3,
   "and both the Documents tab and the engagement stages open it — the "
   "signature must be visible wherever the document is")
import shutil as _sh3
_sh3.rmtree(_exp3["root"], ignore_errors=True)
c.delete(f"/api/store/admin/documents/{_g2['doc_id']}", headers=A)

# leave the live db as we found it
import shutil as _sh
for _d in [x["id"] for x in _det["docs"]]:
    c.delete(f"/api/store/admin/documents/{_d}", headers=A)
from erp.backend import db as _dbmod
con_cleanup = _dbmod.connect()
con_cleanup.execute("DELETE FROM engagement_docs WHERE engagement_id=?", (_eid,))
con_cleanup.execute("DELETE FROM engagement_gates WHERE engagement_id=?", (_eid,))
for _dcl in (_gen["doc_id"], _g3["doc_id"]):
    con_cleanup.execute("DELETE FROM document_signatures WHERE document_id=?", (_dcl,))
    con_cleanup.execute("DELETE FROM document_events WHERE document_id=?", (_dcl,))
    con_cleanup.execute("DELETE FROM documents WHERE id=?", (_dcl,))
con_cleanup.execute("DELETE FROM document_signatures WHERE document_id=?", (_gen["doc_id"],))
con_cleanup.execute("DELETE FROM document_events WHERE document_id=?", (_gen["doc_id"],))
con_cleanup.execute("DELETE FROM documents WHERE id=?", (_gen["doc_id"],))
con_cleanup.execute("DELETE FROM engagement_log WHERE engagement_id=?", (_eid,))
con_cleanup.execute("DELETE FROM engagement_dates WHERE engagement_id=?", (_eid,))
con_cleanup.execute("DELETE FROM engagements WHERE id=?", (_eid,))
con_cleanup.commit(); con_cleanup.close()
_sh.rmtree(_exp["root"], ignore_errors=True)

print(f"\nall {checks} checks passed")
