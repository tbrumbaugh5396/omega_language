"""Seed demo data: a few markets and store items. Idempotent."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backend import db  # noqa: E402


def main() -> None:
    db.init()
    con = db.connect()
    if con.execute("SELECT COUNT(*) c FROM markets").fetchone()["c"] > 0:
        print("already seeded")
        return
    now = int(time.time())
    week = 7 * 24 * 3600
    demo_markets = [
        dict(title="Will ETH be above $4,000 one week from now?",
             description="Resolves automatically from the Chainlink ETH/USD feed.",
             mechanism="lmsr", close_at=now + week, resolver="chainlink_price",
             resolver_config=json.dumps({
                 "feed": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
                 "decimals": 8, "threshold": 4000.0,
                 "above_outcome": "Yes", "below_outcome": "No"}),
             outcomes=[("Yes", None), ("No", None)]),
        dict(title="Coin flip Friday: heads or tails?",
             description="A simple parimutuel pool — winners split the pot.",
             mechanism="parimutuel", close_at=now + week, resolver="manual",
             resolver_config="{}", outcomes=[("Heads", None), ("Tails", None)]),
        dict(title="Will it rain in Austin this weekend?",
             description="Fixed odds set by the house.",
             mechanism="fixed", close_at=now + week, resolver="manual",
             resolver_config="{}", outcomes=[("Rain", 2.4), ("Dry", 1.5)]),
    ]
    with con:
        for m in demo_markets:
            cur = con.execute(
                "INSERT INTO markets(title,description,mechanism,close_at,resolver,"
                "resolver_config,rake_bps,lmsr_b,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (m["title"], m["description"], m["mechanism"], m["close_at"],
                 m["resolver"], m["resolver_config"], 200, 500.0, now))
            for label, odds in m["outcomes"]:
                con.execute(
                    "INSERT INTO outcomes(market_id,label,fixed_odds) VALUES(?,?,?)",
                    (cur.lastrowid, label, odds))
        for name, desc, price, stock, emoji in [
            ("Coffee on the house", "One fancy coffee, fulfilled by the operator", 500, -1, "☕"),
            ("Movie night pick", "You choose the next movie", 1200, -1, "🎬"),
            ("$25 gift card", "Digital gift card of your choice", 25000, 10, "💳"),
            ("Mystery box", "Could be anything. Probably great.", 5000, 5, "📦"),
        ]:
            con.execute(
                "INSERT INTO store_items(name,description,price,stock,emoji) "
                "VALUES(?,?,?,?,?)", (name, desc, price, stock, emoji))
    print("seeded demo markets and store items")


if __name__ == "__main__":
    main()
