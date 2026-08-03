#!/bin/bash
# Run the script-style tests.
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3; [ -x "$PY" ] || PY=python3
FAIL=0
for t in tests/test_*.py; do
  echo "== $t"
  "$PY" "$t" || FAIL=1
done
[ "$FAIL" = "0" ] && echo "ALL TESTS PASSED" || echo "SOME TESTS FAILED"
read -p "  Press enter to close."
