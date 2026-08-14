#!/bin/bash
# Fill a fresh account with example content: three pieces at different stages
# with real postmortems, a week of practice, and the theory items those breaks
# pulled in. Does nothing if you already have content, so it is safe to run.
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3
[ -x "$PY" ] || PY=python3
"$PY" scripts/seed.py "$@"
read -p "  Press enter to close."
