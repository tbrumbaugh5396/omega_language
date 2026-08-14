#!/bin/bash
# Start with TLS (self-signed) — lets you install the PWA from your phone on
# the same network. Expect a one-time browser warning about the certificate.
#
# Worth doing for this app specifically: the drills sound different on phone
# speakers, and checking a mix there is the point.
cd "$(dirname "$0")/.."
PORT=$(python3 -c 'import json,sys; print(json.load(open("data/config.json")).get("port",8910))' 2>/dev/null || echo 8910)
( sleep 2; open "https://127.0.0.1:$PORT" ) &
exec python3 scripts/launch.py --port "$PORT" --host 0.0.0.0 --https
