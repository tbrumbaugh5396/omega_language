"""End-to-end mechanism tests: parimutuel, fixed odds, LMSR settle correctly."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["EVERY_REWARD_DATA"] = tempfile.mkdtemp(prefix="er_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend import db, engines, ledger  # noqa: E402

db.init()
con = db.connect()


def new_user(name, credits=10000):
    with con:
        cur = con.execute(
            "INSERT INTO users(nickname,created_at) VALUES(?,?)", (name, db.now()))
        uid = cur.lastrowid
        ledger.post(con, [("house", -credits), (f"user:{uid}", credits)], kind="grant")
    return uid


def new_market(mechanism, outcomes, rake_bps=0, lmsr_b=100.0):
    with con:
        cur = con.execute(
            "INSERT INTO markets(title,mechanism,resolver,resolver_config,rake_bps,"
            "lmsr_b,created_at) VALUES(?,?,?,?,?,?,?)",
            (f"test {mechanism}", mechanism, "manual", "{}", rake_bps, lmsr_b, db.now()))
        mid = cur.lastrowid
        for label, odds in outcomes:
            con.execute("INSERT INTO outcomes(market_id,label,fixed_odds) VALUES(?,?,?)",
                        (mid, label, odds))
    m = con.execute("SELECT * FROM markets WHERE id=?", (mid,)).fetchone()
    outs = con.execute("SELECT * FROM outcomes WHERE market_id=? ORDER BY id", (mid,)).fetchall()
    return m, outs


def outs(mid):
    return con.execute("SELECT * FROM outcomes WHERE market_id=? ORDER BY id", (mid,)).fetchall()


alice, bob = new_user("alice"), new_user("bob")

# --- parimutuel: alice 300 on A, bob 100 on B; A wins; 10% rake ---
m, o = new_market("parimutuel", [("A", None), ("B", None)], rake_bps=1000)
engines.place_bet(con, m, outs(m["id"]), alice, o[0]["id"], 300)
engines.place_bet(con, m, outs(m["id"]), bob, o[1]["id"], 100)
r = engines.settle(con, m, o[0]["id"])
# pot 400, rake 40, alice gets all 360
assert r["total_paid"] == 360, r
assert ledger.balance(con, f"user:{alice}") == 10000 - 300 + 360
assert ledger.balance(con, f"user:{bob}") == 10000 - 100
assert ledger.balance(con, ledger.market_account(m["id"])) == 0

# --- parimutuel nobody-picked-winner: full refund ---
m2, o2 = new_market("parimutuel", [("A", None), ("B", None)], rake_bps=1000)
engines.place_bet(con, m2, outs(m2["id"]), alice, o2[0]["id"], 200)
r2 = engines.settle(con, m2, o2[1]["id"])
assert r2["total_paid"] == 200, "stake must be refunded when winner pool is empty"

# --- fixed odds: 2.5x, house covers the shortfall ---
house_before = ledger.balance(con, "house")
m3, o3 = new_market("fixed", [("win", 2.5), ("lose", 1.5)])
engines.place_bet(con, m3, outs(m3["id"]), bob, o3[0]["id"], 100)
r3 = engines.settle(con, m3, o3[0]["id"])
assert r3["total_paid"] == 250
assert ledger.balance(con, "house") == house_before + 100 - 250

# --- lmsr: shares priced by closed form; winning shares pay 1 cr each ---
m4, o4 = new_market("lmsr", [("yes", None), ("no", None)], lmsr_b=100.0)
q = engines.quote(m4, outs(m4["id"]), o4[0]["id"], 500)
assert 0.49 < q["price"] < 0.51, "fresh binary market should price near 50%"
b1 = engines.place_bet(con, m4, outs(m4["id"]), alice, o4[0]["id"], 500)
assert abs(b1["shares"] - q["shares"]) < 1e-3  # quote rounds to 4 decimals
# price of yes must rise after the buy
q2 = engines.quote(m4, outs(m4["id"]), o4[0]["id"], 1)
assert q2["price"] > q["price"]
r4 = engines.settle(con, m4, o4[0]["id"])
assert r4["total_paid"] == int(b1["shares"])
assert int(b1["shares"]) > 500, "winning shares should beat the stake"

# --- void refunds ---
m5, o5 = new_market("parimutuel", [("A", None), ("B", None)])
bal = ledger.balance(con, f"user:{alice}")
engines.place_bet(con, m5, outs(m5["id"]), alice, o5[0]["id"], 50)
engines.void(con, m5)
assert ledger.balance(con, f"user:{alice}") == bal

# whole ledger still zero-sum
total = con.execute("SELECT COALESCE(SUM(delta),0) t FROM ledger").fetchone()["t"]
assert total == 0

print("test_markets: OK")
