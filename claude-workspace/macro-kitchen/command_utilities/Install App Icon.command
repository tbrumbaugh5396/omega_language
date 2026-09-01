#!/bin/bash
# Create/refresh the "MacroKitchen.app" Desktop launcher.
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3
[ -x "$PY" ] || PY=python3
"$PY" tools/make_launcher.py
read -p "  Press enter to close."
