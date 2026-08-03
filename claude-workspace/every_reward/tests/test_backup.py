"""Backup must capture WAL-resident commits that a raw file copy would miss."""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="er_test_")
os.environ["EVERY_REWARD_DATA"] = tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend import db, ledger  # noqa: E402

db.init()
con = db.connect()
with con:
    ledger.post(con, [("house", -777), ("user:1", 777)], kind="grant")
# keep the connection OPEN so the commit stays in the -wal sidecar,
# exactly the state where a plain file copy loses data
assert (Path(tmp) / "every_reward.db-wal").exists(), "test premise: WAL file present"

r = subprocess.run(
    [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "backup.py")],
    capture_output=True, text=True, env=dict(os.environ))
assert r.returncode == 0, r.stderr

backups = sorted((Path(tmp) / "backups").iterdir())
assert backups, "backup.py produced nothing"
check = sqlite3.connect(backups[-1] / "every_reward.db")
total = check.execute(
    "SELECT COALESCE(SUM(delta),0) FROM ledger WHERE account='user:1'").fetchone()[0]
assert total == 777, f"snapshot missing WAL-resident commit: {total}"

print("test_backup: OK")
