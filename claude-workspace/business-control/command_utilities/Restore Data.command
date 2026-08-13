#!/bin/bash
# Restore the newest backup from data/backups/ (stop the server first).
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3
[ -x "$PY" ] || PY=python3
"$PY" scripts/restore.py
read -p "  Press enter to close."
