#!/bin/bash
# Stop the monero-wallet-rpc sidecar.
cd "$(dirname "$0")/.."
PIDFILE="data/monero/sidecar.pid"
if [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "  ✓ stopped monero sidecar (pid $(cat "$PIDFILE"))"
  rm -f "$PIDFILE"
elif pkill -f monero-wallet-rpc 2>/dev/null; then
  echo "  ✓ stopped monero sidecar"
else
  echo "  sidecar is not running."
fi
read -p "  Press enter to close."
