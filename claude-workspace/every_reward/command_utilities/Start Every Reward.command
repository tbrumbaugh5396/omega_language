#!/bin/bash
# Double-click to run Every Reward. Opens your browser when the server is up.
cd "$(dirname "$0")/.."
PORT=$(python3 -c 'import json,sys; print(json.load(open("data/config.json")).get("port",8850))' 2>/dev/null || echo 8850)
( sleep 2; open "http://127.0.0.1:$PORT" ) &
exec python3 scripts/launch.py --port "$PORT"
