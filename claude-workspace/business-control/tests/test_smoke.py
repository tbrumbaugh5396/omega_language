"""Script-style smoke test over a throwaway database: exercises login, orders
(retail + wholesale pricing), time clock, A/B assignment + results, affiliates,
inventory, route planning, funnel analytics, and outreach."""
import json
import os
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

print(f"\nall {checks} checks passed")
