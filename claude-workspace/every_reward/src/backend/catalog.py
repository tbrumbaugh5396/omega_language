"""Catalog source adapters: auto-priced store items from external feeds.

Each source returns the same shape from fetch():
    {"name", "description", "emoji", "price_cents", "in_stock"}
and pricing is a formula over the fetched price:
    credits = ceil(price_cents/100 * usd_to_credits * (1 + markup_bps/10000))

Sources ship here: 'manual' (plain admin-entered items, never synced) and
'mock' (a local JSON feed at data/mock_catalog.json — edit it to simulate
price moves and stock-outs). Real adapters (Walmart affiliate API, gift-card
APIs like Tango/Tremendous) drop in as new fetch_* functions with API keys in
config; scraping retail pages is deliberately not supported (ToS, brittleness).

Sync rules, mirroring the oracle staleness guard:
  - fetch failure / out of stock  -> auto-suspend, auto-resume when it clears
  - price drift > catalog_max_drift_bps -> suspend for ADMIN review (a huge
    move is suspicious data, not something to silently reprice)
  - redemptions of catalog items with stale price data are refused in main.py
"""
import json
import math

from . import config
from .db import now


class CatalogError(Exception):
    pass


DEFAULT_MOCK_FEED = {
    "WM-AF101": {"name": "Air Fryer 5.8QT", "price_usd": 79.99, "emoji": "🍟",
                 "description": "Mock feed item — pretend it ships from walmart.com",
                 "in_stock": True},
    "GC-25":    {"name": "$25 Gift Card", "price_usd": 25.00, "emoji": "💳",
                 "description": "Mock feed item — cash-like, price should be firm",
                 "in_stock": True},
    "LEGO-501": {"name": "Space Shuttle Kit", "price_usd": 49.99, "emoji": "🧱",
                 "description": "Mock feed item", "in_stock": True},
    "PS5-D":    {"name": "Game Console (Disc)", "price_usd": 499.99, "emoji": "🎮",
                 "description": "Mock feed item — seeded out of stock",
                 "in_stock": False},
}


def mock_feed_path():
    return config.DATA_DIR / "mock_catalog.json"


def _mock_fetch(source_id: str) -> dict:
    path = mock_feed_path()
    if not path.exists():  # self-seed so the mock source works out of the box
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_MOCK_FEED, indent=2))
    feed = json.loads(path.read_text())
    if source_id not in feed:
        raise CatalogError(f"{source_id!r} is not in the mock feed "
                           f"(known: {', '.join(sorted(feed))})")
    it = feed[source_id]
    return {"name": it["name"], "description": it.get("description", ""),
            "emoji": it.get("emoji", "🛒"),
            "price_cents": int(round(float(it["price_usd"]) * 100)),
            "in_stock": bool(it.get("in_stock", True))}


def fetch(cfg: dict, source: str, source_id: str) -> dict:
    if source == "mock":
        return _mock_fetch(source_id)
    raise CatalogError(f"unknown catalog source {source!r}")


def price_credits(cfg: dict, price_cents: int, markup_bps: int) -> int:
    usd_rate = int(cfg.get("usd_to_credits", 50))
    return math.ceil(price_cents * usd_rate * (10000 + markup_bps) / (100 * 10000))


def _suspend(con, item, reason: str):
    con.execute(
        "UPDATE store_items SET active=0, suspend_reason=?, last_synced=? WHERE id=?",
        (reason, now(), item["id"]))


def sync_item(con, cfg: dict, item) -> str:
    """Refresh one catalog-sourced item. Returns what happened."""
    if item["suspend_reason"] and item["suspend_reason"].startswith("review:"):
        return "awaiting-review"  # only an admin reactivate clears these
    try:
        info = fetch(cfg, item["source"], item["source_id"])
    except CatalogError as e:
        _suspend(con, item, f"unavailable: {e}")
        return "suspended"
    if not info["in_stock"]:
        _suspend(con, item, "out of stock at source")
        return "suspended"

    old = item["base_price_cents"]
    drift_limit = int(cfg.get("catalog_max_drift_bps", 2000))
    if old and abs(info["price_cents"] - old) * 10000 > old * drift_limit:
        pct = round(abs(info["price_cents"] - old) / old * 100)
        _suspend(con, item,
                 f"review: price moved {pct}% (${old / 100:.2f} -> "
                 f"${info['price_cents'] / 100:.2f})")
        return "suspended"

    credits = price_credits(cfg, info["price_cents"], item["markup_bps"] or 0)
    con.execute(
        "UPDATE store_items SET name=?, description=?, emoji=?, price=?, "
        "base_price_cents=?, last_synced=?, active=1, suspend_reason=NULL WHERE id=?",
        (info["name"], info["description"], info["emoji"], credits,
         info["price_cents"], now(), item["id"]))
    return "resumed" if item["suspend_reason"] else "synced"


def sync_due(con, cfg: dict) -> list:
    """Sync every catalog item whose data is older than catalog_sync_sec."""
    cutoff = now() - int(cfg.get("catalog_sync_sec", 300))
    due = con.execute(
        "SELECT * FROM store_items WHERE source!='manual' AND "
        "(last_synced IS NULL OR last_synced<?)", (cutoff,)).fetchall()
    return [{"id": it["id"], "action": sync_item(con, cfg, it)} for it in due]
