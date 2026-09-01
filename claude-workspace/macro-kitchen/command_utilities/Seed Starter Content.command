#!/bin/bash
# Fill a fresh account with example content (a pantry of common ingredients,
# meal-prep recipes, and a few planned days). Does nothing if you already
# have data, so it's safe to run once after installing.
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3
[ -x "$PY" ] || PY=python3
"$PY" scripts/seed.py "$@"
read -p "  Press enter to close."
