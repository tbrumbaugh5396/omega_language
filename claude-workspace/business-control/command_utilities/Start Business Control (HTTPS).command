#!/bin/bash
# HTTPS variant — needed to install the PWA from phones/other devices.
# Expect a browser warning for the self-signed cert.
cd "$(dirname "$0")/.."
PORT=$(python3 -c 'import json,sys; print(json.load(open("data/config.json")).get("port",8860))' 2>/dev/null || echo 8860)
( sleep 2; open "https://127.0.0.1:$PORT" ) &
exec python3 scripts/launch.py --port "$PORT" --https
