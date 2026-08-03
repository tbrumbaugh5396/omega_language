#!/bin/bash
# HTTPS variant: needed to install the PWA from another device (e.g. your phone).
# Uses a self-signed certificate, so the browser will show a one-time warning.
cd "$(dirname "$0")/.."
PORT=$(python3 -c 'import json,sys; print(json.load(open("data/config.json")).get("port",8850))' 2>/dev/null || echo 8850)
( sleep 2; open "https://127.0.0.1:$PORT" ) &
exec python3 scripts/launch.py --https --host 0.0.0.0 --port "$PORT"
