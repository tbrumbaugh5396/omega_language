#!/bin/bash
# Run the monero-wallet-rpc sidecar on STAGENET (test coins, no real value).
# Creates the operator wallet on first run and wires data/config.json.
cd "$(dirname "$0")/.."
exec python3 scripts/monero_sidecar.py --network stagenet
