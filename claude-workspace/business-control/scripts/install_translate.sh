#!/usr/bin/env bash
# Business Control — the translate node service (LibreTranslate).
#
# Installs LibreTranslate as a machine-level daemon shared by every tenant
# on this node: its own venv under /opt/libretranslate, a systemd unit
# bound to localhost, and a line in the app's node_services.json so the
# platform finds it. Fully offline once the language models download —
# students' words never leave the machine.
#
#   sudo bash install_translate.sh [--port 5000] [--langs en,es]
#        [--data /opt/business-control/data] [--dir /opt/libretranslate]
#
# The resolution rule the app applies: a tenant's own translate_url wins,
# this shared daemon is the floor, and neither installed leaves the
# offline glossary exactly as it was. Idempotent — run again to update.
set -euo pipefail

PORT=5000 LANGS="en,es" DATA=/opt/business-control/data DIR=/opt/libretranslate
while [ $# -gt 0 ]; do
  case "$1" in
    --port)  PORT="$2";  shift 2 ;;
    --langs) LANGS="$2"; shift 2 ;;
    --data)  DATA="$2";  shift 2 ;;
    --dir)   DIR="$2";   shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

echo "== installing prerequisites"
if command -v apt-get >/dev/null; then
  apt-get update -y -qq
  apt-get install -y -qq python3 python3-venv
fi

echo "== LibreTranslate into $DIR"
mkdir -p "$DIR"
cd "$DIR"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q --upgrade libretranslate

echo "== systemd service"
cat > /etc/systemd/system/libretranslate.service <<UNIT
[Unit]
Description=LibreTranslate (Business Control node service)
After=network.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/libretranslate --host 127.0.0.1 --port $PORT \\
  --load-only $LANGS --update-models
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now libretranslate
systemctl restart libretranslate

echo "== declaring the service in $DATA/node_services.json"
mkdir -p "$DATA"
python3 - "$DATA/node_services.json" "http://127.0.0.1:$PORT" <<'PY'
import json, sys
path, url = sys.argv[1], sys.argv[2]
try:
    m = json.load(open(path))
    if not isinstance(m, dict):
        m = {}
except Exception:
    m = {}
m["translate"] = {"url": url, "key": ""}
json.dump(m, open(path, "w"), indent=1)
print("   declared translate ->", url)
PY

echo "== waiting for the service (first run downloads language models —"
echo "   this can take a few minutes)"
for i in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:$PORT/languages" >/dev/null 2>&1; then
    echo "== translate is up on 127.0.0.1:$PORT ($LANGS)"
    echo "   Every tenant on this machine without its own translate_url"
    echo "   now translates here — offline, and visible as a service pill"
    echo "   on the Platform tab."
    exit 0
  fi
  sleep 5
done
echo "the service started but never answered /languages — read:" >&2
echo "  journalctl -u libretranslate -n 50" >&2
exit 1
