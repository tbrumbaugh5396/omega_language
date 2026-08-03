"""Copy the database + config to data/backups/<timestamp>/."""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def main() -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = DATA / "backups" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in ("every_reward.db", "config.json"):
        src = DATA / name
        if src.exists():
            shutil.copy2(src, dest / name)
            copied += 1
    print(f"backed up {copied} files to {dest}")


if __name__ == "__main__":
    sys.exit(main())
