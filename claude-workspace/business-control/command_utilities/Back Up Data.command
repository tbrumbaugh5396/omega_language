#!/bin/bash
# Snapshot the database + config into data/backups/ (safe while running).
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3
[ -x "$PY" ] || PY=python3
"$PY" scripts/backup.py
read -p "  Press enter to close."
