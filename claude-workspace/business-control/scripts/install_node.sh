#!/usr/bin/env bash
# Business Control — worker node installer.
#
# Turns a bare Ubuntu/Debian machine into a fleet worker in one run:
# fetches the app bundle from the provider (authenticated by the node key
# the provider minted at booking), stands it up under systemd with the
# node's identity in its environment, and proves it answers before
# claiming success. Idempotent — run it again to reinstall.
#
# The provider's Platform tab prints the exact command for each booked
# node; by hand it is:
#
#   sudo bash install_node.sh --node NODE_ID --key NODE_KEY \
#        --provider https://shop.yourbrand.com [--port 8860] \
#        [--dir /opt/business-control] [--host 0.0.0.0]
#
set -euo pipefail

NODE="" KEY="" PROVIDER="" PORT=8860 DIR=/opt/business-control HOST=0.0.0.0
while [ $# -gt 0 ]; do
  case "$1" in
    --node)     NODE="$2";     shift 2 ;;
    --key)      KEY="$2";      shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --port)     PORT="$2";     shift 2 ;;
    --dir)      DIR="$2";      shift 2 ;;
    --host)     HOST="$2";     shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
if [ -z "$NODE" ] || [ -z "$KEY" ] || [ -z "$PROVIDER" ]; then
  echo "usage: install_node.sh --node ID --key KEY --provider URL" >&2
  exit 1
fi
PROVIDER="${PROVIDER%/}"

echo "== installing prerequisites"
if command -v apt-get >/dev/null; then
  apt-get update -y -qq
  apt-get install -y -qq python3 python3-venv curl unzip
fi

echo "== fetching the app bundle from $PROVIDER"
mkdir -p "$DIR"
curl -fsS -H "X-Fleet-Key: $KEY" "$PROVIDER/api/fleet/bundle" \
  -o /tmp/bc-bundle.zip
unzip -oq /tmp/bc-bundle.zip -d "$DIR"
rm -f /tmp/bc-bundle.zip
echo "   version $(cat "$DIR/VERSION" 2>/dev/null || echo unknown)"

echo "== python environment"
cd "$DIR"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt

echo "== systemd service"
cat > /etc/systemd/system/business-control-node.service <<UNIT
[Unit]
Description=Business Control worker node ($NODE)
After=network.target

[Service]
WorkingDirectory=$DIR
Environment=BUSINESS_CONTROL_NODE=$NODE
Environment=BUSINESS_CONTROL_NODE_KEY=$KEY
ExecStartPre=$DIR/.venv/bin/pip install -q -r $DIR/requirements.txt
ExecStart=$DIR/.venv/bin/python scripts/launch.py --port $PORT --host $HOST
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now business-control-node
systemctl restart business-control-node

echo "== waiting for the node to answer"
for i in $(seq 1 30); do
  if curl -fsS -H "X-Fleet-Key: $KEY" \
       "http://127.0.0.1:$PORT/api/node/ping" >/dev/null 2>&1; then
    echo "== node '$NODE' is up on port $PORT and accepts the fleet key"
    echo "   Firewall reminder: only the provider (and port 22) needs to"
    echo "   reach port $PORT — 'ufw allow 22/tcp && ufw allow from"
    echo "   <provider-ip> to any port $PORT && ufw enable' is the shape."
    echo "   The provider's Platform tab can now Check and Update this"
    echo "   node, and ship tenants to it."
    exit 0
  fi
  sleep 2
done
echo "the service started but never answered a ping — read:" >&2
echo "  journalctl -u business-control-node -n 50" >&2
exit 1
