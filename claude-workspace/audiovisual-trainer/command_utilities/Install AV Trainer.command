#!/bin/bash
# Install: check Python, build a private venv, install dependencies, create the
# database, and generate icons. Everything stays in this folder.
set -e
cd "$(dirname "$0")/.."
APP="$(pwd)"

echo "  AV Trainer — install"
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
echo "  ✓ dependencies installed (fastapi, uvicorn)"

chmod +x "$APP"/command_utilities/*.command 2>/dev/null || true
echo "  ✓ launchers are executable"

./.venv/bin/python3 scripts/make_icons.py >/dev/null
echo "  ✓ icons generated"
./.venv/bin/python3 - <<'PY'
import sys; sys.path.insert(0, "src")
from backend import db
db.init()
print("  ✓ database ready")
PY

echo
read -p "  Create a Desktop app icon too? [y/N] " yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
  ./.venv/bin/python3 tools/make_launcher.py
fi
echo
echo "  Done. Double-click 'Start AV Trainer.command' to launch."
read -p "  Press enter to close."
