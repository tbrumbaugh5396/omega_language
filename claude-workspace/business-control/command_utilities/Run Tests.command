#!/bin/bash
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3
[ -x "$PY" ] || PY=python3
"$PY" tests/test_smoke.py
read -p "  Press enter to close."
