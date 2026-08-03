#!/bin/bash
# Copy the database and config into data/backups/<timestamp>/.
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3; [ -x "$PY" ] || PY=python3
"$PY" scripts/backup.py
read -p "  Press enter to close."
