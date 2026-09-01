#!/usr/bin/env bash
# Business Control — the SFU node service (MediaMTX).
#
# Stands up a WHIP/WHEP media server shared by every tenant on this
# machine: big classes publish once and subscribe many instead of meshing,
# and the server records what it forwards. The platform composes
# tenant-prefixed paths (bc-<tenant>-<room>-<peer>) so tenants can never
# collide on the shared daemon, and collects finished recordings into
# each tenant's own media store when the class closes.
#
#   sudo bash install_sfu.sh --host <this machine's reachable IP or name>
#        [--port 8889] [--data /opt/business-control/data]
#        [--dir /opt/mediamtx] [--version v1.9.3]
#
# --host is what BROWSERS dial (and what ICE advertises); the health
# probe stays on localhost. Media runs over UDP — open 8889/tcp and
# 8189/udp to the people who take classes. Idempotent.
set -euo pipefail

PORT=8889 DATA=/opt/business-control/data DIR=/opt/mediamtx
HOST="" VERSION=v1.9.3
while [ $# -gt 0 ]; do
  case "$1" in
    --host)    HOST="$2";    shift 2 ;;
    --port)    PORT="$2";    shift 2 ;;
    --data)    DATA="$2";    shift 2 ;;
    --dir)     DIR="$2";     shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
if [ -z "$HOST" ]; then
  echo "usage: install_sfu.sh --host <reachable IP or hostname>" >&2
  exit 1
fi

ARCH=$(uname -m)
case "$ARCH" in
  x86_64)          MTX_ARCH=amd64 ;;
  aarch64|arm64)   MTX_ARCH=arm64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

echo "== MediaMTX $VERSION into $DIR"
mkdir -p "$DIR" "$DIR/recordings"
cd "$DIR"
TARBALL="mediamtx_${VERSION}_linux_${MTX_ARCH}.tar.gz"
curl -fsSL -o "/tmp/$TARBALL" \
  "https://github.com/bluenviron/mediamtx/releases/download/$VERSION/$TARBALL"
tar -xzf "/tmp/$TARBALL" -C "$DIR" mediamtx
rm -f "/tmp/$TARBALL"

echo "== configuration"
cat > "$DIR/mediamtx.yml" <<CONF
# Written by install_sfu.sh — WHIP/WHEP only, everything else off.
rtsp: no
rtmp: no
hls: no
srt: no
api: no
metrics: no
playback: no

webrtc: yes
webrtcAddress: :$PORT
webrtcLocalUDPAddress: :8189
webrtcAdditionalHosts: [$HOST]

pathDefaults:
  record: yes
  recordPath: $DIR/recordings/%path/%Y-%m-%d_%H-%M-%S-%f
  recordFormat: fmp4
  recordSegmentDuration: 1h
  recordDeleteAfter: 168h
CONF

echo "== systemd service"
cat > /etc/systemd/system/mediamtx.service <<UNIT
[Unit]
Description=MediaMTX (Business Control node service: sfu)
After=network.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/mediamtx $DIR/mediamtx.yml
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now mediamtx
systemctl restart mediamtx

echo "== declaring the service in $DATA/node_services.json"
mkdir -p "$DATA"
python3 - "$DATA/node_services.json" "$PORT" "$HOST" "$DIR" <<'PY'
import json, sys
path, port, host, mdir = sys.argv[1:]
try:
    m = json.load(open(path))
    if not isinstance(m, dict):
        m = {}
except Exception:
    m = {}
m["sfu"] = {"url": f"http://127.0.0.1:{port}",
            "public_url": f"http://{host}:{port}",
            "record_dir": f"{mdir}/recordings", "key": ""}
json.dump(m, open(path, "w"), indent=1)
print("   declared sfu ->", m["sfu"]["public_url"])
PY

echo "== waiting for the server"
for i in $(seq 1 20); do
  if curl -so /dev/null "http://127.0.0.1:$PORT/"; then
    echo "== sfu is up: browsers dial http://$HOST:$PORT, recordings land"
    echo "   in $DIR/recordings and are collected into each tenant's own"
    echo "   media store when its class closes (kept here 7 days as the"
    echo "   safety copy, then rotated)."
    echo "   Firewall: open $PORT/tcp and 8189/udp to class participants."
    echo "   For TLS, put Caddy in front of $PORT and set public_url to"
    echo "   the https name in $DATA/node_services.json."
    exit 0
  fi
  sleep 2
done
echo "mediamtx started but never answered — read:" >&2
echo "  journalctl -u mediamtx -n 50" >&2
exit 1
