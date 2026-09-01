#!/usr/bin/env bash
# Business Control — the forge node service (Forgejo). The pilot for the
# tooling family.
#
# Stands a git forge up on this machine: one binary, SQLite storage, a
# systemd unit, an admin account, and a line in node_services.json so the
# Platform tab wears the pill. Today the platform only KNOWS the forge is
# here — repos, CI and releases as a sellable capability are a price-book
# decision this pilot exists to inform.
#
#   sudo bash install_forge.sh --host <reachable name or IP> \
#        --admin-pass <password> [--port 3000] [--dir /opt/forgejo]
#        [--data /opt/business-control/data] [--version 9.0.3]
set -euo pipefail

PORT=3000 DIR=/opt/forgejo DATA=/opt/business-control/data
HOST="" ADMIN_PASS="" VERSION=9.0.3
while [ $# -gt 0 ]; do
  case "$1" in
    --host)       HOST="$2";       shift 2 ;;
    --admin-pass) ADMIN_PASS="$2"; shift 2 ;;
    --port)       PORT="$2";       shift 2 ;;
    --dir)        DIR="$2";        shift 2 ;;
    --data)       DATA="$2";       shift 2 ;;
    --version)    VERSION="$2";    shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
if [ -z "$HOST" ] || [ -z "$ADMIN_PASS" ]; then
  echo "usage: install_forge.sh --host NAME --admin-pass PASS" >&2
  exit 1
fi

ARCH=$(uname -m)
case "$ARCH" in
  x86_64)        FJ_ARCH=amd64 ;;
  aarch64|arm64) FJ_ARCH=arm64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

echo "== prerequisites"
if command -v apt-get >/dev/null; then
  apt-get update -y -qq && apt-get install -y -qq git curl
fi
id -u forgejo >/dev/null 2>&1 || useradd -r -m -d "$DIR" forgejo

echo "== Forgejo $VERSION into $DIR"
mkdir -p "$DIR" "$DIR/data" "$DIR/custom/conf"
curl -fsSL -o "$DIR/forgejo" \
  "https://codeberg.org/forgejo/forgejo/releases/download/v$VERSION/forgejo-$VERSION-linux-$FJ_ARCH"
chmod +x "$DIR/forgejo"

cat > "$DIR/custom/conf/app.ini" <<CONF
; Written by install_forge.sh — SQLite, registration closed, localhost
; bind with the public name in ROOT_URL (front with Caddy for TLS).
[server]
HTTP_ADDR = 0.0.0.0
HTTP_PORT = $PORT
ROOT_URL = http://$HOST:$PORT/
DOMAIN = $HOST

[database]
DB_TYPE = sqlite3
PATH = $DIR/data/forgejo.db

[repository]
ROOT = $DIR/data/repos

[service]
DISABLE_REGISTRATION = true

[security]
INSTALL_LOCK = true
CONF
chown -R forgejo:forgejo "$DIR"

echo "== systemd service"
cat > /etc/systemd/system/forgejo.service <<UNIT
[Unit]
Description=Forgejo (Business Control node service: forge)
After=network.target

[Service]
User=forgejo
WorkingDirectory=$DIR
Environment=FORGEJO_WORK_DIR=$DIR/data
ExecStart=$DIR/forgejo web --config $DIR/custom/conf/app.ini
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now forgejo
systemctl restart forgejo

echo "== waiting for the forge"
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/api/v1/version" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "== admin account"
sudo -u forgejo "$DIR/forgejo" --config "$DIR/custom/conf/app.ini" \
  admin user create --admin --username forge-admin \
  --password "$ADMIN_PASS" --email "forge-admin@$HOST" 2>/dev/null \
  || echo "   (admin exists — kept)"

echo "== declaring the service in $DATA/node_services.json"
mkdir -p "$DATA"
python3 - "$DATA/node_services.json" "$PORT" "$HOST" <<'PY'
import json, sys
path, port, host = sys.argv[1:]
try:
    m = json.load(open(path))
    if not isinstance(m, dict):
        m = {}
except Exception:
    m = {}
m["forge"] = {"url": f"http://127.0.0.1:{port}",
              "public_url": f"http://{host}:{port}", "key": ""}
json.dump(m, open(path, "w"), indent=1)
print("   declared forge ->", m["forge"]["public_url"])
PY

if curl -fsS "http://127.0.0.1:$PORT/api/v1/version" >/dev/null 2>&1; then
  echo "== forge is up: http://$HOST:$PORT (sign in as forge-admin;"
  echo "   registration is closed — the forge's accounts are the"
  echo "   operator's to mint until the capability that sells seats"
  echo "   exists). Front with Caddy for TLS and update public_url."
  exit 0
fi
echo "forgejo started but never answered — read:" >&2
echo "  journalctl -u forgejo -n 50" >&2
exit 1
