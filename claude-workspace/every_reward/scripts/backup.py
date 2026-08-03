"""Snapshot the database + config to data/backups/<timestamp>/.

Uses SQLite's online backup API rather than a file copy: in WAL mode recent
commits live in the -wal sidecar, so copying the .db file of a running server
can produce a silently inconsistent backup. Connection.backup() takes a
consistent snapshot even while the server is live.
"""
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("EVERY_REWARD_DATA", ROOT / "data"))


def main() -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = DATA / "backups" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0

    db = DATA / "every_reward.db"
    if db.exists():
        src = sqlite3.connect(db)
        dst = sqlite3.connect(dest / "every_reward.db")
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        copied += 1

    cfg = DATA / "config.json"
    if cfg.exists():
        shutil.copy2(cfg, dest / "config.json")
        copied += 1

    print(f"backed up {copied} files to {dest}")


if __name__ == "__main__":
    sys.exit(main())
