#!/bin/bash
# Restore the newest backup (stop the server first). To pick a specific one,
# run: python3 scripts/restore.py list   then   python3 scripts/restore.py <stamp>
cd "$(dirname "$0")/.."
PY=./.venv/bin/python3; [ -x "$PY" ] || PY=python3
echo "  Available backups:"
"$PY" scripts/restore.py list | sed 's/^/  /'
echo
read -p "  Restore the NEWEST backup over current data? [y/N] " yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
  "$PY" scripts/restore.py latest
else
  echo "  cancelled"
fi
read -p "  Press enter to close."
