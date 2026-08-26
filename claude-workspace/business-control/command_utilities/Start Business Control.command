#!/bin/bash
# Double-click to run Business Control — storefront, ERP/CRM and store admin.
# They are one server on one port, so this is the only thing you need to start.
cd "$(dirname "$0")/.."
source "command_utilities/_serve.sh"

PORT=$(bc_port)
BASE="http://127.0.0.1:$PORT"

bc_exit_if_running "$BASE" "" "$PORT"
bc_wait_then_open "$BASE" "" &
exec python3 scripts/launch.py --port "$PORT"
