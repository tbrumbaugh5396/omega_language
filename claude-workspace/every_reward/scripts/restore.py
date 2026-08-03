"""Restore the database + config from a backup made by backup.py."""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("EVERY_REWARD_DATA", ROOT / "data"))
BACKUPS = DATA / "backups"


def main() -> int:
    stamps = sorted([d for d in BACKUPS.iterdir() if d.is_dir()]) if BACKUPS.exists() else []
    if not stamps:
        print("no backups found — run 'Back Up Data.command' first")
        return 1
    choice = sys.argv[1] if len(sys.argv) > 1 else "latest"
    if choice == "list":
        for d in stamps:
            print(" ", d.name)
        return 0
    if (DATA / "server.pid").exists():
        print("the server appears to be running — stop it first "
              "(Stop Every Reward.command), then restore")
        return 1
    src = stamps[-1] if choice == "latest" else BACKUPS / choice
    if not src.is_dir():
        print(f"no backup named {choice!r}; try: restore.py list")
        return 1

    # WAL sidecar files from the old database would corrupt the restored one
    for leftover in ("every_reward.db-wal", "every_reward.db-shm"):
        (DATA / leftover).unlink(missing_ok=True)
    restored = 0
    for name in ("every_reward.db", "config.json"):
        if (src / name).exists():
            shutil.copy2(src / name, DATA / name)
            restored += 1
    print(f"restored {restored} files from {src.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
