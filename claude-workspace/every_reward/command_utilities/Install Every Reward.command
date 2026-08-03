#!/bin/bash
# Install: check Python, build a private venv, install dependencies, create the
# database, seed demo data, and generate icons. Everything stays in this folder.
set -e
cd "$(dirname "$0")/.."
APP="$(pwd)"

echo "  Every Reward — install"
echo "  location: $APP"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "  ✗ python3 was not found."
  echo "    Install it from https://www.python.org/downloads/ and run this again."
  read -p "  Press enter to close."; exit 1
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PYOK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3,10) else 0)')
if [ "$PYOK" != "1" ]; then
  echo "  ✗ Python $PYV found, but 3.10 or newer is needed."
  read -p "  Press enter to close."; exit 1
fi
echo "  ✓ Python $PYV"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt
echo "  ✓ dependencies installed (fastapi, uvicorn, eth-account)"

chmod +x "$APP"/command_utilities/*.command 2>/dev/null || true
echo "  ✓ launchers are executable"

./.venv/bin/python3 scripts/make_icons.py >/dev/null
./.venv/bin/python3 - <<'PY'
import sys; sys.path.insert(0, "src")
from backend import db, config
db.init(); cfg = config.load()
print(f"  ✓ database ready — admin key: {cfg['admin_key']}")
print("    (use it on the login screen's 'admin key' field, or add your wallet")
print("     address to admin_addresses in data/config.json)")
PY
./.venv/bin/python3 scripts/seed.py | sed 's/^/  ✓ /'

echo
echo "  IMPORTANT — crypto deposits are OFF until you edit data/config.json and"
echo "  set deposit_address to a wallet YOU control. The app is non-custodial:"
echo "  it never holds keys and never sends transactions. Running a real-money"
echo "  prediction market publicly may be regulated activity in your country."
echo
read -p "  Create a Desktop app icon too? [y/N] " yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
  ./.venv/bin/python3 tools/make_launcher.py
fi
echo
echo "  Done. Double-click 'Start Every Reward.command' to launch."
read -p "  Press enter to close."
