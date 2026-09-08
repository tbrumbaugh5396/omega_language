#!/bin/bash
# Fill an install with example content: the demo catalog, stores, staff and
# thirty days of orders so the analytics have something to draw, then a class
# that is in session right now so Learning opens on a live register rather
# than an empty one.
#
# Safe to run on an install that already has data — the catalog seed skips
# when products exist, and the class seed does nothing if one is already open.
#
# Takes an optional tenant: `Seed Starter Content.command lingua`. Without
# one it seeds whichever tenant `localhost` opens, because seeding a tenant
# you do not look at is the same as not seeding.
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3
[ -x "$PY" ] || PY=python3

echo "  Business Control — starter content"
echo

"$PY" scripts/seed.py ${1:+--tenant "$1"} 2>/dev/null | sed 's/^/  ✓ /'
"$PY" scripts/seed_live_class.py ${1:+"$1"} 2>/dev/null | sed 's/^/  /'

echo
read -p "  Press enter to close."
