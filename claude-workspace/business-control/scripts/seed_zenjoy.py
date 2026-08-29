"""Install the Zenjoy product line over the generic food-brand demo seed.

The storefront ships with a hot-sauce demo catalog, which is fine for the
"food brand" bundle but wrong for Zenjoy — a sparkling stress-relief tea. This
replaces the catalog with the five-flavour range from the brand system
(docs/brand/zen-artwork.html), each SKU carrying its ring colour, tasting note,
nutrition panel and ingredients so the storefront can tint a whole section to
the flavour being browsed.

Safe to re-run: matches on SKU and updates in place.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# --tenant <id> aims every connect at that tenant's database;
# without it the script behaves exactly as before (legacy dir).
if "--tenant" in sys.argv:
    _ti = sys.argv.index("--tenant")
    from erp.backend import tenancy as _tenancy
    _tenancy.CURRENT.set(sys.argv[_ti + 1])
    del sys.argv[_ti:_ti + 2]

from erp.backend import db  # noqa: E402
from storefront.backend import api as store  # noqa: E402

# sku, name, note, colour, price¢, case size, case¢, caffeine, kcal, sugar g
FLAVOURS = [
    ("ZJ-YUZU", "Yuzu Calm", "bright · citrus · the first exhale",
     "#ff8c1a", 349, 12, 3588, "35mg green tea", 15, 2),
    ("ZJ-MATCHA", "Matcha Still", "green · grounding · focus without edge",
     "#00b39a", 349, 12, 3588, "45mg matcha", 20, 2),
    ("ZJ-HIBISCUS", "Hibiscus Hush", "tart · rose-red · the evening turn",
     "#e0407a", 349, 12, 3588, "caffeine-free", 15, 3),
    ("ZJ-LOTUS", "Lotus Drift", "floral · deep violet · the long unwind",
     "#6c00bf", 349, 12, 3588, "caffeine-free", 10, 2),
    ("ZJ-GINGER", "Ginger Ground", "warm · root · steady, not sleepy",
     "#c98a2e", 349, 12, 3588, "25mg green tea", 20, 3),
]

# sku, name, note, colour, price¢, case, case¢, badge, cans
PACKS = [
    ("ZJ-PACK-12", "The Full Ripple — 12 pack", "all five flavours · the whole range",
     "#6c00bf", 3599, 4, 11500, "Best value", 12),
    ("ZJ-PACK-8", "Quiet Eight — 8 pack", "your calm, eight times over",
     "#8a77e1", 2599, 6, 12500, "", 8),
]

L_THEANINE = ("Sparkling water, organic green tea, L-theanine (200mg), "
              "organic cane sugar, natural botanical flavour, citric acid, "
              "magnesium glycinate, sea salt.")


def nutrition(kcal, sugar, caffeine):
    return json.dumps({
        "Serving size": "12 fl oz (355ml)",
        "Calories": str(kcal),
        "Total sugars": f"{sugar}g",
        "L-theanine": "200mg",
        "Caffeine": caffeine,
        "Sodium": "25mg",
    })


def upsert(con, sku, name, cat, price, case_size, case_price, desc):
    row = con.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()
    if row:
        con.execute(
            "UPDATE products SET name=?, description=?, category=?,"
            " price_cents=?, case_size=?, case_price_cents=?, active=1"
            " WHERE id=?",
            (name, desc, cat, price, case_size, case_price, row["id"]))
        return row["id"]
    cur = con.execute(
        "INSERT INTO products(sku,name,description,category,price_cents,"
        " case_size,case_price_cents,image,active) VALUES(?,?,?,?,?,?,?,0,1)",
        (sku, name, desc, cat, price, case_size, case_price))
    return cur.lastrowid


def put_meta(con, pid, **kw):
    for k, v in kw.items():
        con.execute(
            "INSERT INTO store_product_meta(product_id,k,v) VALUES(?,?,?)"
            " ON CONFLICT(product_id,k) DO UPDATE SET v=excluded.v",
            (pid, k, str(v)))


def main():
    store.init_tables()
    con = db.connect()
    try:
        keep = set()
        for sku, name, note, colour, price, cs, cp, caff, kcal, sugar in FLAVOURS:
            desc = (f"Sparkling stress-relief tea. {note.split(' · ')[0].capitalize()}"
                    f" and clean, with 200mg L-theanine for calm that doesn't"
                    f" cloud. {caff}.")
            pid = upsert(con, sku, name, "sparkling tea", price, cs, cp, desc)
            keep.add(pid)
            put_meta(con, pid, flavour=sku.split("-")[1].lower(), colour=colour,
                     note=note, ingredients=L_THEANINE,
                     nutrition=nutrition(kcal, sugar, caff))
        for sku, name, note, colour, price, cs, cp, badge, cans in PACKS:
            desc = (f"{cans} cans of sparkling stress-relief tea, 200mg"
                    f" L-theanine in every can. {note.capitalize()}.")
            pid = upsert(con, sku, name, "multipacks", price, cs, cp, desc)
            keep.add(pid)
            put_meta(con, pid, flavour="pack", colour=colour, note=note,
                     badge=badge, ingredients=L_THEANINE,
                     nutrition=nutrition(15, 2, "varies by flavour"))

        # Retire the demo food-brand catalog rather than deleting it: orders
        # and analytics rows still reference those product ids.
        gone = con.execute(
            "SELECT id, name FROM products WHERE active=1 AND id NOT IN"
            f" ({','.join('?' * len(keep))})", tuple(keep)).fetchall()
        for g in gone:
            con.execute("UPDATE products SET active=0 WHERE id=?", (g["id"],))

        # Collections drive the flavour filter chips on the homepage.
        con.execute("DELETE FROM collection_products")
        con.execute("DELETE FROM collections")
        for pos, (title, cat) in enumerate(
                [("Single flavours", "sparkling tea"), ("Multipacks", "multipacks")]):
            cur = con.execute(
                "INSERT INTO collections(name,slug,position) VALUES(?,?,?)",
                (title, store.slugify(title), pos))
            cid = cur.lastrowid
            for p in con.execute(
                    "SELECT id FROM products WHERE category=? AND active=1",
                    (cat,)).fetchall():
                con.execute(
                    "INSERT INTO collection_products(collection_id,product_id)"
                    " VALUES(?,?)", (cid, p["id"]))
        con.commit()
        print(f"Zenjoy line installed: {len(FLAVOURS)} flavours,"
              f" {len(PACKS)} packs, {len(gone)} demo SKUs retired.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
