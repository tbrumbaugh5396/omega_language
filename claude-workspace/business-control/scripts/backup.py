"""WAL-safe backup of the WHOLE fleet, into data/backups/<stamp>.tar.gz.

Local tenants are snapshotted in place; tenants living on worker nodes are
PULLED — the provider asks each node for a backup-grade export (the node's
pack is itself a WAL-safe snapshot), so the archive covers every business
on the platform wherever its data lives, and a worker needs no cron of its
own. One node not answering skips that tenant LOUDLY (exit 1, so cron
surfaces it) while everyone else still gets backed up. Keeps the newest 30
archives, and writes data/backups/last.json so the Platform tab can say
whether the nightly promise is being kept.
"""
import json
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


def _pull_remote(tar, td, tid: str, nid: str) -> None:
    """One remote tenant into the archive, same layout as a local one, so
    restore.py never has to know where the data lived."""
    import io
    import httpx
    from erp.backend import fleet
    r = httpx.get(fleet.node_addr(nid) + f"/api/node/tenants/{tid}/export",
                  headers={"X-Fleet-Key": fleet.node_key(nid)}, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"node answered {r.status_code}")
    dest = Path(td) / f"remote_{tid}"
    dest.mkdir()
    with tarfile.open(fileobj=io.BytesIO(r.content)) as inner:
        for m in inner.getmembers():
            if m.name.startswith("/") or ".." in m.name.split("/"):
                raise RuntimeError(f"unsafe path in export: {m.name}")
        inner.extractall(dest, filter="data")
    tar.add(dest, arcname=f"tenants/{tid}")


def main() -> int:
    backups = config.DATA_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = backups / f"business-control-{stamp}.tar.gz"
    failures: dict = {}
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
            # ...and the tenants whose data lives on worker nodes. The
            # backup goes to the data, because the data no longer comes
            # to the backup.
            from erp.backend import fleet, tenancy
            for tid in tenancy.all_tenants():
                nid = tenancy.node_of(tid)
                if not fleet.node_addr(nid):
                    continue
                try:
                    _pull_remote(tar, td, tid, nid)
                    print(f"pulled {tid} from {nid}")
                except Exception as e:                  # noqa: BLE001
                    failures[tid] = f"{nid}: {str(e)[:160]}"
                    print(f"BACKUP INCOMPLETE: {tid} on {failures[tid]}")
    old = sorted(backups.glob("business-control-*.tar.gz"))[:-30]
    for p in old:
        p.unlink()
    # the record the Platform tab reads: is the nightly promise being kept?
    (backups / "last.json").write_text(json.dumps(
        {"at": time.time(), "ok": not failures, "failures": failures,
         "archive": out.name}))
    print(f"backup written: {out}"
          + (f" — {len(failures)} tenant(s) MISSING" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
