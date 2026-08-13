"""WAL-safe backup: snapshot the SQLite DB (backup API, safe while the server
runs), plus config.json and the VAPID key, into data/backups/<timestamp>.tar.gz.
Keeps the newest 30 backups."""
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from erp.backend import config  # noqa: E402


def main() -> Path:
    backups = config.DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = backups / f"business-control-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "business_control.db"
        if config.DB_PATH.exists():
            src = sqlite3.connect(config.DB_PATH)
            dst = sqlite3.connect(snap)
            src.backup(dst)          # consistent even mid-write (WAL-safe)
            dst.close()
            src.close()
        with tarfile.open(out, "w:gz") as tar:
            if snap.exists():
                tar.add(snap, arcname="business_control.db")
            for name in ("config.json", "vapid_private.pem"):
                p = config.DATA_DIR / name
                if p.exists():
                    tar.add(p, arcname=name)
    old = sorted(backups.glob("business-control-*.tar.gz"))[:-30]
    for p in old:
        p.unlink()
    print(f"backup written: {out}")
    return out


if __name__ == "__main__":
    main()
