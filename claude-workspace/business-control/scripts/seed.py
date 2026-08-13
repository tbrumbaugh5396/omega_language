"""Seed demo data: products, stores, inventory, employees, trucks, outreach,
an auto-generated experiment, and 30 days of orders + funnel events so the
analytics views have something to show. Idempotent-ish: skips if products exist."""
import random
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from erp.backend import abtest, config, db  # noqa: E402

DAY = 86400

PRODUCTS = [
    ("HS-ORIG", "Original Hot Sauce", "sauces", 799, 12, 6900),
    ("HS-VERDE", "Verde Hot Sauce", "sauces", 849, 12, 7300),
    ("HS-SMOKE", "Smoked Chipotle Sauce", "sauces", 899, 12, 7700),
    ("SN-CHIP", "Tortilla Chips", "snacks", 499, 24, 8600),
    ("SN-SALSA", "Roasted Salsa", "snacks", 649, 12, 5600),
    ("SP-RUB", "Signature Spice Rub", "spices", 999, 12, 8600),
    ("SP-TACO", "Taco Seasoning", "spices", 449, 24, 7700),
    ("DR-MICH", "Michelada Mix", "drinks", 1099, 6, 4700),
]

STORES = [
    # name, kind, region, city, lat, lng
    ("Hudson DC", "distributor_dc", "Northeast", "Newark NJ", 40.7357, -74.1724),
    ("Green Market Boston", "retail", "Northeast", "Boston MA", 42.3601, -71.0589),
    ("Corner Grocer NYC", "retail", "Northeast", "New York NY", 40.7128, -74.0060),
    ("Philly Provisions", "retail", "Northeast", "Philadelphia PA", 39.9526, -75.1652),
    ("Peach State Foods", "retail", "Southeast", "Atlanta GA", 33.7490, -84.3880),
    ("Gulf Coast Market", "retail", "Southeast", "Tampa FL", 27.9506, -82.4572),
    ("Riverside Grocery", "retail", "Southeast", "Charlotte NC", 35.2271, -80.8431),
    ("Lakeview Pantry", "retail", "Midwest", "Chicago IL", 41.8781, -87.6298),
    ("Twin Cities Co-op", "retail", "Midwest", "Minneapolis MN", 44.9778, -93.2650),
    ("Gateway Grocers", "retail", "Midwest", "St. Louis MO", 38.6270, -90.1994),
    ("Lone Star DC", "distributor_dc", "Southwest", "Dallas TX", 32.7767, -96.7970),
    ("Desert Bloom Market", "retail", "Southwest", "Phoenix AZ", 33.4484, -112.0740),
    ("Alamo Foods", "retail", "Southwest", "San Antonio TX", 29.4241, -98.4936),
    ("Golden Gate Grocery", "retail", "West", "San Francisco CA", 37.7749, -122.4194),
    ("Cascade Market", "retail", "West", "Portland OR", 45.5152, -122.6784),
    ("Sunset Provisions", "retail", "West", "Los Angeles CA", 34.0522, -118.2437),
]

EMPLOYEES = [("Maria Lopez", "1111", "Southwest"), ("Dev Patel", "2222", "Northeast"),
             ("Jo Kowalski", "3333", "Midwest"), ("Sam Reyes", "4444", "West")]

OUTREACH = [
    ("Beacon Hill Deli", "Northeast", "Boston MA", "contacted"),
    ("Bushwick Bodega Co", "Northeast", "Brooklyn NY", "lead"),
    ("Savannah Spice Shop", "Southeast", "Savannah GA", "sampled"),
    ("Nashville Hot Market", "Southeast", "Nashville TN", "lead"),
    ("Milwaukee Mercantile", "Midwest", "Milwaukee WI", "contacted"),
    ("Route 66 Trading Post", "Southwest", "Albuquerque NM", "sampled"),
    ("El Paso Pantry", "Southwest", "El Paso TX", "stocked"),
    ("Venice Beach Provisions", "West", "Los Angeles CA", "lead"),
    ("Emerald City Grocers", "West", "Seattle WA", "contacted"),
]


def main() -> None:
    db.init()
    cfg = config.load()
    con = db.connect()
    rng = random.Random(7)
    now = time.time()

    if con.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]:
        print("seed skipped (products already exist)")
        return

    for sku, name, cat, price, case, casep in PRODUCTS:
        con.execute(
            "INSERT INTO products(sku,name,category,price_cents,case_size,"
            " case_price_cents) VALUES(?,?,?,?,?,?)",
            (sku, name, cat, price, case, casep))
    for name, kind, region, city, lat, lng in STORES:
        con.execute("INSERT INTO stores(name,kind,region,city,lat,lng)"
                    " VALUES(?,?,?,?,?,?)", (name, kind, region, city, lat, lng))
    pids = [r["id"] for r in con.execute("SELECT id FROM products")]
    sids = [r["id"] for r in con.execute("SELECT id FROM stores")]
    for sid in sids:
        for pid in pids:
            con.execute(
                "INSERT INTO inventory(store_id,product_id,qty,par,updated_at)"
                " VALUES(?,?,?,?,?)", (sid, pid, rng.randint(0, 60), 24, now))
    for name, pin, region in EMPLOYEES:
        con.execute(
            "INSERT INTO users(name,role,token,pin,region,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (name, "employee", secrets.token_urlsafe(24), pin, region, now))
        # A few past shifts each
        uid = con.execute("SELECT id FROM users WHERE pin=?", (pin,)).fetchone()["id"]
        for d in range(1, 6):
            start = now - d * DAY - 8 * 3600
            con.execute("INSERT INTO shifts(user_id,clock_in,clock_out)"
                        " VALUES(?,?,?)",
                        (uid, start, start + rng.uniform(6.5, 9) * 3600))
    con.execute("INSERT INTO trucks(name,capacity_cases,home_region)"
                " VALUES('Truck 1 — East', 400, 'Northeast'),"
                " ('Truck 2 — Southwest', 500, 'Southwest'),"
                " ('Truck 3 — West', 400, 'West')")
    for name, region, city, stage in OUTREACH:
        con.execute(
            "INSERT INTO outreach(name,region,city,stage,updated_at)"
            " VALUES(?,?,?,?,?)", (name, region, city, stage,
                                   now - rng.uniform(0, 10) * DAY))

    # Demo customers/distributors + an influencer with an affiliate code.
    regions = cfg["regions"]
    people = []
    for i in range(28):
        role = "distributor" if i % 7 == 0 else "customer"
        con.execute(
            "INSERT INTO users(name,role,token,region,created_at)"
            " VALUES(?,?,?,?,?)",
            (f"Demo {role.title()} {i}", role, secrets.token_urlsafe(24),
             rng.choice(regions), now - 40 * DAY))
        people.append((con.execute("SELECT last_insert_rowid() id").fetchone()["id"],
                       role))
    con.execute(
        "INSERT INTO users(name,role,token,region,created_at)"
        " VALUES('Ava Influencer','influencer',?, 'West', ?)",
        (secrets.token_urlsafe(24), now - 30 * DAY))
    inf_id = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.execute(
        "INSERT INTO affiliates(user_id,code,rate_bps,clicks,created_at)"
        " VALUES(?,?,?,?,?)",
        (inf_id, "ava01", cfg["default_commission_bps"], 214, now - 30 * DAY))
    aff = con.execute("SELECT * FROM affiliates WHERE code='ava01'").fetchone()

    # A few feed posts from the demo influencer (preview fields preset so
    # seeding never needs the network).
    for days_ago, body, url, provider, title in [
        (9, "Made the whole taco spread with the Verde — recipe video is up!",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube",
         "Verde Hot Sauce Taco Night"),
        (4, "Pantry restock haul, featuring the Original. Code ava01 in bio.",
         "https://www.tiktok.com/@ava/video/1234567890", "tiktok",
         "pantry restock ft. the good stuff"),
        (1, "Michelada Sunday. That mix + lime + a cold one. Unreal.", "", "", ""),
    ]:
        con.execute(
            "INSERT INTO posts(user_id,body,url,provider,title,image,"
            " description,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (inf_id, body, url, provider, title, "",
             "by Ava" if url else "", now - days_ago * DAY))

    # Running auto-experiment on the flagship product.
    variants = abtest.generate_variants("purchase", "Original Hot Sauce", 3)
    con.execute(
        "INSERT INTO experiments(name,goal,status,auto_generated,created_at)"
        " VALUES('Original Hot Sauce — purchase','purchase','running',1,?)",
        (now - 21 * DAY,))
    eid = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    for v in variants:
        con.execute("INSERT INTO variants(experiment_id,name,headline,cta,theme)"
                    " VALUES(?,?,?,?,?)",
                    (eid, v["name"], v["headline"], v["cta"], v["theme"]))
    vids = [r["id"] for r in con.execute(
        "SELECT id FROM variants WHERE experiment_id=?", (eid,))]
    # Give variants different true conversion rates so results are interesting.
    conv_rate = {vids[0]: 0.10, vids[1]: 0.16, vids[2]: 0.07}

    # 30 days of funnel traffic + orders. Recent week is quieter in the
    # Southeast so the fall-off detector has something to flag.
    prods = con.execute("SELECT * FROM products").fetchall()
    for day in range(30, 0, -1):
        t0 = now - day * DAY
        n_visitors = rng.randint(28, 42)
        for _ in range(n_visitors):
            vis = f"seed-{rng.randrange(10 ** 9)}"
            region = rng.choice(regions)
            if region == "Southeast" and day <= 7 and rng.random() < 0.6:
                continue  # engineered engagement fall-off
            t = t0 + rng.uniform(0, DAY * 0.8)
            vid = vids[rng.randrange(len(vids))]
            con.execute(
                "INSERT INTO assignments(experiment_id,visitor_id,variant_id,"
                " assigned_at) VALUES(?,?,?,?)", (eid, vis, vid, t))

            def ev(step, value=0, pid=None):
                con.execute(
                    "INSERT INTO events(visitor_id,step,region,product_id,"
                    " experiment_id,variant_id,value_cents,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (vis, step, region, pid, eid, vid, value, t))

            ev("visit")
            if rng.random() < 0.75:
                p = rng.choice(prods)
                ev("view_product", pid=p["id"])
                if rng.random() < 0.55:
                    ev("add_to_cart", pid=p["id"])
                    if rng.random() < 0.6:
                        ev("checkout")
                        if rng.random() < conv_rate[vid] / (0.75 * 0.55 * 0.6):
                            uid, role = rng.choice(people)
                            kind = ("distributor" if role == "distributor"
                                    else "customer")
                            qty = rng.randint(2, 6) if kind == "distributor" \
                                else rng.randint(1, 3)
                            unit = (p["case_price_cents"] if kind == "distributor"
                                    else p["price_cents"])
                            sub = unit * qty
                            code = "ava01" if rng.random() < 0.2 else ""
                            con.execute(
                                "INSERT INTO orders(user_id,kind,status,region,"
                                " subtotal_cents,affiliate_code,visitor_id,"
                                " created_at) VALUES(?,?,?,?,?,?,?,?)",
                                (uid, kind, rng.choice(
                                    ["delivered", "delivered", "shipped",
                                     "confirmed"]), region, sub, code, vis, t))
                            oid = con.execute(
                                "SELECT last_insert_rowid() id").fetchone()["id"]
                            con.execute(
                                "INSERT INTO order_items(order_id,product_id,"
                                " qty,unit_price_cents) VALUES(?,?,?,?)",
                                (oid, p["id"], qty, unit))
                            if code:
                                con.execute(
                                    "INSERT INTO referrals(affiliate_id,order_id,"
                                    " commission_cents,created_at)"
                                    " VALUES(?,?,?,?)",
                                    (aff["id"], oid,
                                     sub * aff["rate_bps"] // 10000, t))
                            ev("purchase", value=sub, pid=p["id"])
    con.commit()
    n_orders = con.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
    n_events = con.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    print(f"seeded {len(PRODUCTS)} products, {len(STORES)} stores, "
          f"{len(EMPLOYEES)} employees, {n_orders} orders, {n_events} events")
    print("employee PINs: " + ", ".join(f"{n} → {p}" for n, p, _ in EMPLOYEES))
    print("affiliate demo link: /r/ava01")


if __name__ == "__main__":
    main()
