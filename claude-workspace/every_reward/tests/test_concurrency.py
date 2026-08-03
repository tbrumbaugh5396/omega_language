"""Write-lock races: concurrent posts must never overdraw an account, and
concurrent last-unit redeem-style decrements must not go negative."""
import os
import sys
import tempfile
import threading
from pathlib import Path

os.environ["EVERY_REWARD_DATA"] = tempfile.mkdtemp(prefix="er_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend import db, ledger  # noqa: E402

db.init()
setup = db.connect()
with setup:
    ledger.post(setup, [("house", -1000), ("user:1", 1000)], kind="grant")
setup.close()

# --- two threads, separate connections, both try to spend 800 of the 1000.
# Without BEGIN IMMEDIATE both balance checks pass and the user ends at -600.
barrier = threading.Barrier(2)
results = []


def spend():
    con = db.connect()
    barrier.wait()  # maximize overlap
    try:
        with con:
            ledger.post(con, [("user:1", -800), ("house", 800)], kind="bet")
        results.append("ok")
    except ledger.LedgerError:
        results.append("insufficient")
    except Exception as e:  # e.g. database locked — also acceptable, not a double spend
        results.append(f"error:{e}")
    finally:
        con.close()


threads = [threading.Thread(target=spend) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()

con = db.connect()
bal = ledger.balance(con, "user:1")
assert results.count("ok") == 1, f"exactly one spend should win: {results}"
assert bal == 200, f"balance must be 200, got {bal} ({results})"
assert bal >= 0, "overdraft happened"

# --- guarded stock decrement: 10 threads race for 3 units
with con:
    con.execute("INSERT INTO store_items(id,name,price,stock) VALUES(9,'x',1,3)")
con.close()
wins = []


def grab():
    c = db.connect()
    try:
        with c:
            cur = c.execute(
                "UPDATE store_items SET stock=stock-1 WHERE id=9 AND stock>0")
            if cur.rowcount:
                wins.append(1)
    finally:
        c.close()


threads = [threading.Thread(target=grab) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()

con = db.connect()
stock = con.execute("SELECT stock FROM store_items WHERE id=9").fetchone()["stock"]
assert len(wins) == 3, f"exactly 3 grabs should win, got {len(wins)}"
assert stock == 0, f"stock must end at 0, got {stock}"

print("test_concurrency: OK")
