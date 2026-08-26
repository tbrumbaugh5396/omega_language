#!/bin/bash
# HTTPS variant — needed to install the PWA from phones and other devices.
# Expect a browser warning for the self-signed cert; that is the cert being
# self-signed, not something being wrong.
cd "$(dirname "$0")/.."
source "command_utilities/_serve.sh"

PORT=$(bc_port)
BASE="https://127.0.0.1:$PORT"

# -k because the cert is self-signed: without it every check fails and the
# launcher would report a healthy server as unreachable.
bc_exit_if_running "$BASE" "-k" "$PORT"
bc_wait_then_open "$BASE" "-k" &
exec python3 scripts/launch.py --port "$PORT" --https
