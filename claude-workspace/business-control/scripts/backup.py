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


def _snap_dir(tar, td, src_dir: Path, prefix: str) -> None:
    """One data directory into the archive: WAL-safe DB snapshot, config,
    VAPID key, and the uploads that ARE the business records (product
    photos, signed scans, media). Backups that skip uploads restore a shop
    with no photographs and a vault with no evidence."""
    db_file = src_dir / "business_control.db"
    if db_file.exists():
        snap = Path(td) / f"{prefix.replace('/', '_') or 'root'}.db"
        src = sqlite3.connect(db_file)
        dst = sqlite3.connect(snap)
        src.backup(dst)              # consistent even mid-write (WAL-safe)
        dst.close()
        src.close()
        tar.add(snap, arcname=f"{prefix}business_control.db")
    for name in ("config.json", "vapid_private.pem"):
        p = src_dir / name
        if p.exists():
            tar.add(p, arcname=f"{prefix}{name}")
    up = src_dir / "uploads"
    if up.is_dir():
        tar.add(up, arcname=f"{prefix}uploads")


def main() -> Path:
    backups = config.DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = backups / f"business-control-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(out, "w:gz") as tar:
            _snap_dir(tar, td, config.DATA_DIR, "")
            tenants = config.DATA_DIR / "tenants"
            if tenants.is_dir():
                # One archive covers the fleet: every tenant's dir, plus
                # the registry that says who answers to which hostname.
                reg = config.DATA_DIR / "tenants.json"
                if reg.exists():
                    tar.add(reg, arcname="tenants.json")
                for tdir in sorted(p for p in tenants.iterdir()
                                   if p.is_dir()):
                    _snap_dir(tar, td, tdir, f"tenants/{tdir.name}/")
    old = sorted(backups.glob("business-control-*.tar.gz"))[:-30]
    for p in old:
        p.unlink()
    print(f"backup written: {out}")
    return out


if __name__ == "__main__":
    main()
