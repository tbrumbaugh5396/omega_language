"""Ledger invariants: zero-sum, no overdrafts, balances add up."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EVERY_REWARD_DATA"] = tempfile.mkdtemp(prefix="er_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend import db, ledger  # noqa: E402

db.init()
con = db.connect()

# grant from house, then spend
with con:
    ledger.post(con, [("house", -1000), ("user:1", 1000)], kind="grant")
assert ledger.balance(con, "user:1") == 1000
assert ledger.balance(con, "house") == -1000

# non-zero-sum rejected
try:
    with con:
        ledger.post(con, [("user:1", -5)], kind="bet")
    raise AssertionError("non-zero-sum accepted")
except ledger.LedgerError:
    pass

# overdraft rejected for users
try:
    with con:
        ledger.post(con, [("user:1", -2000), ("house", 2000)], kind="bet")
    raise AssertionError("overdraft accepted")
except ledger.LedgerError:
    pass
assert ledger.balance(con, "user:1") == 1000, "failed txn must not change balance"

# whole ledger sums to zero
total = con.execute("SELECT COALESCE(SUM(delta),0) t FROM ledger").fetchone()["t"]
assert total == 0

print("test_ledger: OK")
