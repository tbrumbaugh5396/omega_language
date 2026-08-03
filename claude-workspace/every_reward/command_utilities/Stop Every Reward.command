#!/bin/bash
# Stop the server using the pidfile written at launch.
cd "$(dirname "$0")/.."
PIDFILE="data/server.pid"
if [ -f "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if kill "$PID" 2>/dev/null; then
    echo "  ✓ stopped Every Reward (pid $PID)"
  else
    echo "  server was not running (stale pidfile removed)"
  fi
  rm -f "$PIDFILE"
else
  # fall back to matching the launch command
  if pkill -f "backend.main:app" 2>/dev/null; then
    echo "  ✓ stopped Every Reward"
  else
    echo "  Every Reward is not running."
  fi
fi
read -p "  Press enter to close."
