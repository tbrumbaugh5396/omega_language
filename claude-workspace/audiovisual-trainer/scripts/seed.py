"""Load starter content for an account from the command line.

Usage:  python3 scripts/seed.py [--user <username>]
With one account, --user is optional.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=None, help="username to seed")
    args = ap.parse_args()

    from backend import db, seeder
    db.init()
    with db.connect() as con:
        users = db.rows(con, "SELECT id, username FROM users ORDER BY id")
        if not users:
            print("No accounts yet — sign up in the app first.")
            return 1
        if args.user:
            match = [u for u in users if u["username"].lower() == args.user.lower()]
            if not match:
                print(f"No account called {args.user!r}. "
                      f"Have: {', '.join(u['username'] for u in users)}")
                return 1
            target = match[0]
        elif len(users) > 1:
            print("Several accounts exist — pass --user <username>. "
                  f"Have: {', '.join(u['username'] for u in users)}")
            return 1
        else:
            target = users[0]

        added = seeder.seed_user(con, target["id"])
    total = sum(added.values())
    if total:
        print(f"Seeded {target['username']}: " +
              ", ".join(f"{v} {k}" for k, v in added.items() if v))
    else:
        print(f"{target['username']} already has content — nothing added.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
