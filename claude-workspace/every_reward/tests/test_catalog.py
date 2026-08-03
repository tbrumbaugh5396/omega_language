"""Catalog adapter: formula pricing, sync, drift/stock suspend + resume."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["EVERY_REWARD_DATA"] = tempfile.mkdtemp(prefix="er_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend import catalog, db  # noqa: E402

CFG = {"usd_to_credits": 50, "default_markup_bps": 1500,
       "catalog_max_drift_bps": 2000, "catalog_sync_sec": 300}

db.init()
con = db.connect()


def feed():
    return json.loads(catalog.mock_feed_path().read_text())


def set_feed(d):
    catalog.mock_feed_path().write_text(json.dumps(d))


def item(iid):
    return con.execute("SELECT * FROM store_items WHERE id=?", (iid,)).fetchone()


# pricing formula: $79.99 * 50 cr/$ * 1.15 = 4599.4 -> ceil 4600
assert catalog.price_credits(CFG, 7999, 1500) == 4600
assert catalog.price_credits(CFG, 2500, 0) == 1250
# ceil always rounds in the house's favor
assert catalog.price_credits(CFG, 1, 0) == 1

# mock feed self-seeds and fetches
info = catalog.fetch(CFG, "mock", "WM-AF101")
assert info["price_cents"] == 7999 and info["in_stock"]
try:
    catalog.fetch(CFG, "mock", "NOPE")
    raise AssertionError("unknown sku accepted")
except catalog.CatalogError as e:
    assert "not in the mock feed" in str(e)
try:
    catalog.fetch(CFG, "walmart", "X")
    raise AssertionError("unknown source accepted")
except catalog.CatalogError as e:
    assert "unknown catalog source" in str(e)

# add an item the way the endpoint does, then sync it through its life
with con:
    cur = con.execute(
        "INSERT INTO store_items(name,description,price,stock,emoji,active,"
        "source,source_id,base_price_cents,markup_bps,last_synced) "
        "VALUES('Air Fryer','',4600,-1,'🍟',1,'mock','WM-AF101',7999,1500,0)")
    iid = cur.lastrowid

# small price move (+10% < 20% limit): reprices in place, stays active
f = feed()
f["WM-AF101"]["price_usd"] = 87.99
set_feed(f)
with con:
    assert catalog.sync_item(con, CFG, item(iid)) == "synced"
it = item(iid)
assert it["base_price_cents"] == 8799 and it["active"] == 1
assert it["price"] == catalog.price_credits(CFG, 8799, 1500)

# big move (+50% > 20% limit): suspended for admin review, price NOT honored
f["WM-AF101"]["price_usd"] = 131.99
set_feed(f)
with con:
    assert catalog.sync_item(con, CFG, item(iid)) == "suspended"
it = item(iid)
assert it["active"] == 0 and it["suspend_reason"].startswith("review:")
assert it["base_price_cents"] == 8799, "suspended item must keep the old baseline"

# review-suspends do NOT auto-resume even if the price returns to normal
f["WM-AF101"]["price_usd"] = 87.99
set_feed(f)
with con:
    assert catalog.sync_item(con, CFG, item(iid)) == "awaiting-review"
assert item(iid)["active"] == 0

# admin reactivate: clear reason + baseline, re-sync accepts current price
with con:
    con.execute("UPDATE store_items SET suspend_reason=NULL, base_price_cents=NULL "
                "WHERE id=?", (iid,))
    assert catalog.sync_item(con, CFG, item(iid)) == "synced"
assert item(iid)["active"] == 1

# out-of-stock suspends, restock auto-resumes
f["WM-AF101"]["in_stock"] = False
set_feed(f)
with con:
    assert catalog.sync_item(con, CFG, item(iid)) == "suspended"
assert item(iid)["suspend_reason"] == "out of stock at source"
f["WM-AF101"]["in_stock"] = True
set_feed(f)
with con:
    assert catalog.sync_item(con, CFG, item(iid)) == "resumed"
assert item(iid)["active"] == 1

# vanishing from the feed suspends too
f2 = dict(f)
del f2["WM-AF101"]
set_feed(f2)
with con:
    assert catalog.sync_item(con, CFG, item(iid)) == "suspended"
assert "unavailable" in item(iid)["suspend_reason"]

# ---- card sources, offline via a faked HTTP seam ----
real_http = catalog._http_json

POKE_RESP = {"data": {
    "name": "Charizard", "number": "4", "rarity": "Rare Holo",
    "set": {"name": "Base"},
    "images": {"small": "https://img.example/base1-4.png"},
    "tcgplayer": {"prices": {
        "normal": {"market": 100.0},
        "holofoil": {"market": 420.69},
    }}}}
YGO_RESP = {"data": [{
    "name": "Dark Magician", "type": "Normal Monster",
    "card_prices": [{"tcgplayer_price": "12.34"}],
    "card_images": [{"image_url_small": "https://img.example/dm.jpg"}]}]}

try:
    catalog._http_json = lambda url, headers=None: POKE_RESP
    info = catalog.fetch(CFG, "pokemontcg", "base1-4")
    # holofoil market wins over normal (chase value is the holo printing)
    assert info["price_cents"] == 42069, info
    assert info["image_url"] == "https://img.example/base1-4.png"
    assert "Charizard" in info["name"] and "Base" in info["name"]

    catalog._http_json = lambda url, headers=None: YGO_RESP
    info = catalog.fetch(CFG, "ygoprodeck", "46986414")
    assert info["price_cents"] == 1234 and info["emoji"] == "🃏", info

    # no price listed -> clean error, never a 0-credit listing
    catalog._http_json = lambda url, headers=None: {"data": {"name": "X", "set": {}}}
    try:
        catalog.fetch(CFG, "pokemontcg", "base1-4")
        raise AssertionError("priceless card accepted")
    except catalog.CatalogError as e:
        assert "no market price" in str(e)

    catalog._http_json = lambda url, headers=None: {"data": []}
    try:
        catalog.fetch(CFG, "ygoprodeck", "0")
        raise AssertionError("missing card accepted")
    except catalog.CatalogError as e:
        assert "not found" in str(e)
finally:
    catalog._http_json = real_http

# sync_due only touches catalog items with data older than catalog_sync_sec
set_feed(f)
with con:
    con.execute("UPDATE store_items SET last_synced=? WHERE id=?", (db.now(), iid))
    assert catalog.sync_due(con, CFG) == []
    con.execute("UPDATE store_items SET last_synced=0 WHERE id=?", (iid,))
    assert [r["id"] for r in catalog.sync_due(con, CFG)] == [iid]

print("test_catalog: OK")
