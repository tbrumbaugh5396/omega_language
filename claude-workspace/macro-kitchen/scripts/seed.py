"""Seed starter content into an account from the command line.

With one account, seeds it. With several, pass --user <username>.
Refuses to touch an account that already has content."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backend import db, seeder  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=None, help="username to seed")
    args = ap.parse_args()

    db.init()
    with db.connect() as con:
        users = db.rows(con, "SELECT id, username FROM users ORDER BY id")
        if not users:
            print("No accounts yet — start the app and sign up first.")
            return 1
        if args.user:
            match = [u for u in users if u["username"].lower() == args.user.lower()]
            if not match:
                print(f"No account named {args.user!r}. "
                      f"Accounts: {', '.join(u['username'] for u in users)}")
                return 1
            target = match[0]
        elif len(users) == 1:
            target = users[0]
        else:
            print("Several accounts exist — pass --user <name>. "
                  f"Accounts: {', '.join(u['username'] for u in users)}")
            return 1

        if seeder.has_content(con, target["id"]):
            print(f"Account {target['username']!r} already has content — "
                  "seeding skipped.")
            return 1
        counts = seeder.seed_user(con, target["id"])
    print(f"Seeded {target['username']!r}: " +
          ", ".join(f"{v} {k}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
