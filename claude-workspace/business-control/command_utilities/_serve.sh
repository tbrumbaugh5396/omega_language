#!/bin/bash
# Shared launch behaviour for the Start commands. Sourced, not double-clicked
# (no .command extension, so Finder leaves it alone).
#
# Business Control is one server: the storefront at /, the ERP/CRM at /ops/
# and the store admin at /admin all come from the same process on the same
# port. "Start everything" is therefore one command, and the only thing worth
# getting right is not opening the browser before the server can answer.
#
# BC_NO_OPEN=1 starts the server without opening any tabs.

bc_port() {
  python3 -c 'import json; print(json.load(open("data/config.json")).get("port",8860))' \
    2>/dev/null || echo 8860
}

# $1 base url, $2 extra curl flags (-k for the self-signed HTTPS cert)
bc_alive() {
  curl -fs $2 -o /dev/null --max-time 1 "$1/" 2>/dev/null
}

bc_urls() {
  echo "    Storefront   $1/"
  echo "    ERP / CRM    $1/ops/"
  echo "    Store admin  $1/admin"
}

bc_open() {
  [ -n "$BC_NO_OPEN" ] && return
  # Storefront last so it lands on top — it is the one you look at most.
  open "$1/admin"; sleep 0.4
  open "$1/ops/";  sleep 0.4
  open "$1/"
}

# Poll rather than sleep a fixed two seconds: a cold start runs migrations
# first, and opening the browser before that finishes greets you with a
# connection error on a server that was seconds away from being fine.
bc_wait_then_open() {
  local base="$1" flags="$2"
  for _ in $(seq 1 60); do
    if bc_alive "$base" "$flags"; then
      echo ""
      echo "  Business Control is up:"
      bc_urls "$base"
      echo ""
      bc_open "$base"
      return 0
    fi
    sleep 0.5
  done
  echo "  ! server did not answer on $base after 30s — see the log above."
  return 1
}

# Double-clicking a second time should raise the windows, not fight for the
# port and die with an unhelpful "address already in use".
bc_exit_if_running() {
  local base="$1" flags="$2" port="$3"
  if bc_alive "$base" "$flags"; then
    echo "  Business Control is already running on port $port."
    bc_urls "$base"
    bc_open "$base"
    echo ""
    read -p "  Press enter to close (the server keeps running)."
    exit 0
  fi
}
