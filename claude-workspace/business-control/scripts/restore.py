"""Restore data/ from a backup archive. Refuses while the server is running.
Usage: restore.py [path-to-backup.tar.gz]   (default: newest backup)"""
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from erp.backend import config  # noqa: E402


def main() -> int:
    pidfile = config.DATA_DIR / "server.pid"
    if pidfile.exists():
        print("Server appears to be running — stop it first"
              " (Stop Business Control.command).")
        return 1
    if len(sys.argv) > 1:
        archive = Path(sys.argv[1])
    else:
        backups = sorted((config.DATA_DIR / "backups")
                         .glob("business-control-*.tar.gz"))
        if not backups:
            print("No backups found in data/backups/.")
            return 1
        archive = backups[-1]
    if not archive.exists():
        print(f"No such file: {archive}")
        return 1
    # Safety net: keep the current state aside before overwriting — the
    # legacy triple, plus the whole tenants tree and its registry when the
    # install is multi-tenant.
    aside = config.DATA_DIR / f"pre-restore-{time.strftime('%Y%m%d-%H%M%S')}"
    aside.mkdir(parents=True, exist_ok=True)
    for name in ("business_control.db", "config.json", "vapid_private.pem",
                 "tenants.json", "tenants"):
        p = config.DATA_DIR / name
        if p.exists():
            p.rename(aside / name)
    with tarfile.open(archive) as tar:
        tar.extractall(config.DATA_DIR, filter="data")
    # A restored remote tenant is parked on local: the archive's copy is
    # now the authoritative one, and it must not fight whatever a worker
    # node still holds. Reconciling the worker (wipe or re-ship) is the
    # operator's deliberate act, said out loud here.
    import json
    reg_p = config.DATA_DIR / "tenants.json"
    if reg_p.exists():
        reg = json.loads(reg_p.read_text())
        nodes = reg.get("nodes") or {}
        parked = []
        for tid, t in (reg.get("tenants") or {}).items():
            nid = t.get("node") or "local"
            if (nodes.get(nid) or {}).get("addr"):
                t["node"] = "local"
                parked.append(f"{tid} (was on {nid})")
        if parked:
            reg_p.write_text(json.dumps(reg, indent=2))
            print("parked on local — the restored copy is authoritative; "
                  "reconcile the worker before re-shipping:")
            for line in parked:
                print(f"  {line}")
    print(f"restored from {archive.name}")
    print(f"previous state kept in {aside}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
