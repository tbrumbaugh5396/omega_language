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
r = c.post(f"/api/admin/feed/{post['id']}/delete", headers=A, json={})
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

# --- no emoji in the back office ---
# The ERP is meant to read as a tool, not a toy, and an emoji renders as a
# different drawing on every platform. This covers the back-office chrome and
# anything that lands in the notification bell. Customer-facing email and SMS
# copy is a different voice and keeps its warmth; typographic marks (arrows,
# ticks) are deliberate and stay.
import pathlib as _pl, re as _re
# The pictographic planes, plus the handful of legacy pictographs that read
# as emoji. Ticks, crosses, arrows and stars are typography, not emoji.
_EMOJI = _re.compile("[\U0001F000-\U0001FAFF\u2728\u26A0\u2753\u2705\u2B50]")
_hits = []
for _f in sorted(_pl.Path("src/erp").rglob("*")):
    if not _f.is_file():
        continue
    _front = _f.suffix in (".js", ".css", ".html")
    if not _front and _f.suffix != ".py":
        continue
    _lines = _f.read_text(errors="replace").splitlines()
    for _i, _line in enumerate(_lines, 1):
        if not _EMOJI.search(_line):
            continue
        # In backend Python only the notification titles are in scope — find
        # the call this line belongs to by looking back a few lines.
        if not _front:
            _ctx = " ".join(_lines[max(0, _i - 4):_i])
            if "notify.push(" not in _ctx and "push.send(" not in _ctx:
                continue
        _hits.append(f"{_f}:{_i}")
ok(not _hits,
   "no emoji in the back office chrome or notifications"
   + (" — " + ", ".join(_hits[:4]) if _hits else ""))
print(f"\nall {checks} checks passed")
