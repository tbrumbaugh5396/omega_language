#!/bin/bash
# Create a double-clickable app with a real icon on the Desktop (macOS).
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3; [ -x "$PY" ] || PY=python3
"$PY" tools/make_launcher.py "$@"
echo
read -p "  Press enter to close."
