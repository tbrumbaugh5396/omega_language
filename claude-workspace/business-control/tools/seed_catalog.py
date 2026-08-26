"""Set the storefront catalog to the real Zenjoy range, with photography.

Re-runnable: matched on SKU, so running it twice updates rather than
duplicates, and re-attaches artwork only if the file on disk has changed.

Everything not in RANGE is deactivated, never deleted. Orders, invoices and
the ledger all reference products by id; removing a row would leave past
orders pointing at nothing and silently change historical revenue. `active=0`
takes an item out of the storefront, which is what "limit the collection to
these four" actually means.

    PYTHONPATH=src python3 tools/seed_catalog.py [--images-from DIR]
"""
import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from erp.backend import config, db                      # noqa: E402
from storefront.backend import api                      # noqa: E402

# The client's own artwork, kept out of the repo root where it used to sit
# loose among the code. One constant so a tidy-up is one edit, not five.
ART = pathlib.Path(__file__).resolve().parents[1] / "assets"

# (sku, name, category, price, case size, case price, description, artwork)
RANGE = [
    ("ZJ-MANGO", "Mango Black Tea", "sparkling tea", 349, 12, 3599,
     "Sun-ripe mango over black tea, with ashwagandha, L-theanine and "
     "lemon balm. Calm that doesn't cloud.",
     "Mango Black Tea 01 without Condensation without Background with "
     "Colored Lights.png"),
    ("ZJ-PASSION", "Passion Fruit Green Tea", "sparkling tea", 349, 12, 3599,
     "Bright passion fruit over green tea, with ashwagandha, L-theanine "
     "and lemon balm. Sharp, not jittery.",
     "Passion  Fruit Green Tea 01 without Condensation without Background "
     "with Colored Lights.png"),
    ("ZJ-LAVENDER", "Lavender Black Tea", "sparkling tea", 349, 12, 3599,
     "Soft lavender over black tea, with ashwagandha, L-theanine and "
     "lemon balm. The long exhale.",
     "Lavender Black Tea 01 without Condensation without Background with "
     "Colored Lights.png"),
    ("ZJ-HONEY", "Honey Green Tea", "sparkling tea", 349, 12, 3599,
     "Real honey over green tea, with ashwagandha, L-theanine and lemon "
     "balm. Gentle all the way down.",
     "Honey Green Tea 01 without Condensation without Background with "
     "Colored Lights.png"),
    ("ZJ-PACK-12", "The Calm Case — 12 pack", "multipacks", 3599, 0, 0,
     "Three of each: mango, passion fruit, lavender and honey green tea. "
     "Four flavors, one calm.",
     "All Flavors 02 without Background with Colored Lights.png"),
]


# Presentation metadata lives in store_product_meta, and it drove the card
# colours and the shelf note. Left alone it kept the old catalog's values —
# a mango card tinted lavender, and a case still advertising five flavours.
# The tool that owns the range owns these too, or they rot.
META = {
    "ZJ-MANGO": {"flavour": "mango", "colour": "#e27e34", "badge": "",
                 "note": "sun-ripe mango · black tea"},
    "ZJ-PASSION": {"flavour": "passionfruit", "colour": "#b03064",
                   "badge": "", "note": "bright passion fruit · green tea"},
    "ZJ-LAVENDER": {"flavour": "lavender", "colour": "#7466b0", "badge": "",
                    "note": "soft lavender · black tea"},
    "ZJ-HONEY": {"flavour": "honey", "colour": "#7a9e4c", "badge": "",
                 "note": "real honey · green tea"},
    "ZJ-PACK-12": {"flavour": "pack", "colour": "#6c00bf",
                   "badge": "Best value",
                   "note": "all four flavors · three of each"},
}


# The label facts, shared by every SKU. Per-can figures the client gave us;
# the multipack shows the same per-can numbers because that is what you
# drink either way.
NUTRITION = {
    "Serving size": "12 fl oz (355ml)",
    "Calories": "70",
    "Total sugars": "15g",
    "L-theanine": "200mg",
    "Ashwagandha (KSM-66)": "150mg",
    "Lemon balm": "150mg",
}

# Which collection each SKU belongs in, by the category the range already
# declares. Membership rotted exactly like the presentation meta did: the
# storefront's "Single flavors" still listed five discontinued products, and
# Mango sat under Multipacks because it inherited a retired product's id.
COLLECTIONS = {"sparkling tea": "Single flavors", "multipacks": "Multipacks"}


def set_collections(con, pid, category):
    want = COLLECTIONS.get(category)
    con.execute("DELETE FROM collection_products WHERE product_id=?", (pid,))
    if not want:
        return
    row = con.execute("SELECT id FROM collections WHERE name=?", (want,)).fetchone()
    cid = row["id"] if row else con.execute(
        "INSERT INTO collections(name) VALUES(?)", (want,)).lastrowid
    con.execute("INSERT OR IGNORE INTO collection_products(collection_id,"
                " product_id) VALUES(?,?)", (cid, pid))


def set_meta(con, pid, sku):
    vals = dict(META.get(sku, {}))
    vals["nutrition"] = json.dumps(NUTRITION)
    for k, v in vals.items():
        con.execute("INSERT INTO store_product_meta(product_id,k,v)"
                    " VALUES(?,?,?) ON CONFLICT(product_id,k)"
                    " DO UPDATE SET v=excluded.v", (pid, k, v))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def attach(con, pid, src, alt, force=False):
    """Give a product its photo, replacing any earlier one.

    The stored copy is fingerprinted in `alt` so a re-run with unchanged
    artwork does no work — re-encoding derivatives every run would churn the
    upload directory and bust every cached URL for no reason.
    """
    tag = f"{alt}#{digest(src)}"
    have = con.execute(
        "SELECT id, alt FROM product_media WHERE product_id=? AND kind='image'"
        " ORDER BY position, id LIMIT 1", (pid,)).fetchone()
    if have and have["alt"] == tag and not force:
        return "kept"

    con.execute("DELETE FROM product_media WHERE product_id=?", (pid,))
    cur = con.execute(
        "INSERT INTO product_media(product_id,kind,ext,video_url,alt,"
        " position,created_at) VALUES(?,'image','png','',?,0,?)",
        (pid, tag, db.now()))
    mid = cur.lastrowid
    api.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    (api.MEDIA_DIR / f"{mid}.png").write_bytes(src.read_bytes())
    api.make_derivatives(mid, "png")
    con.execute("UPDATE products SET image=1 WHERE id=?", (pid,))
    return "attached"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-from", default=str(ART),
                    help="directory holding the product renders")
    ap.add_argument("--force", action="store_true",
                    help="re-attach artwork even if it has not changed "
                         "(use after changing how derivatives are made)")
    args = ap.parse_args()
    art = pathlib.Path(args.images_from)

    con = db.connect()
    keep = []
    for sku, name, cat, price, cs, cp, desc, img in RANGE:
        row = con.execute("SELECT id FROM products WHERE sku=?",
                          (sku,)).fetchone()
        if row:
            pid = row["id"]
            con.execute(
                "UPDATE products SET name=?, description=?, category=?,"
                " price_cents=?, case_size=?, case_price_cents=?, active=1"
                " WHERE id=?", (name, desc, cat, price, cs, cp, pid))
            what = "updated"
        else:
            pid = con.execute(
                "INSERT INTO products(sku,name,description,category,"
                " price_cents,case_size,case_price_cents,active,image)"
                " VALUES(?,?,?,?,?,?,?,1,0)",
                (sku, name, desc, cat, price, cs, cp)).lastrowid
            what = "created"
        keep.append(pid)

        set_meta(con, pid, sku)
        set_collections(con, pid, cat)
        src = art / img
        art_note = "NO ARTWORK FOUND" if not src.exists() else attach(
            con, pid, src, name, args.force)
        print(f"  {sku:<13} #{pid:<3} {what:<8} {art_note}")

    marks = ",".join("?" * len(keep))
    n = con.execute(f"UPDATE products SET active=0 WHERE id NOT IN ({marks})",
                    keep).rowcount
    # A deactivated product left in a collection makes the storefront show an
    # empty shelf under a tab that still has a name.
    gone = con.execute(
        f"DELETE FROM collection_products WHERE product_id NOT IN ({marks})",
        keep).rowcount
    con.commit()
    print(f"\n{len(keep)} products live; {n} others deactivated "
          f"(not deleted); {gone} stale collection rows removed")


if __name__ == "__main__":
    main()
