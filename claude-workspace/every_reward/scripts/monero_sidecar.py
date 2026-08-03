"""Run the monero-wallet-rpc sidecar and wire it into config.json.

Defaults to STAGENET (Monero's test network — coins are valueless) against a
public remote node, so nothing needs to sync locally. Creates the 'operator'
wallet on first run, opens it, and writes wallet_rpc_url + address into the
app's monero config block. Keep this running alongside the app server.

For mainnet later: --network mainnet --daemon <your-node:18081>, and load a
VIEW-ONLY wallet instead of a generated one (see README).
"""
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WALLET_DIR = DATA / "monero"
CONFIG = DATA / "config.json"

STAGENET_DAEMONS = ["node.monerodevs.org:38089", "stagenet.xmr-tw.org:38081",
                    "node2.monerodevs.org:38089"]


def find_binary() -> str:
    for cand in (str(ROOT / "tools" / "monero-cli" / "monero-wallet-rpc"),
                 "monero-wallet-rpc",
                 "/usr/local/bin/monero-wallet-rpc",
                 "/opt/homebrew/bin/monero-wallet-rpc"):
        path = shutil.which(cand) or (cand if Path(cand).exists() else None)
        if path:
            return path
    print("monero-wallet-rpc not found — install with: brew install monero")
    sys.exit(1)


def rpc(port: int, method: str, params: dict = None):
    payload = json.dumps({"jsonrpc": "2.0", "id": "0", "method": method,
                          "params": params or {}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json_rpc", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(out["error"].get("message", str(out["error"])))
    return out.get("result", {})


def wallet_password() -> str:
    pwfile = WALLET_DIR / "wallet_password.txt"
    if not pwfile.exists():
        WALLET_DIR.mkdir(parents=True, exist_ok=True)
        pwfile.write_text(secrets.token_urlsafe(24))
        pwfile.chmod(0o600)
    return pwfile.read_text().strip()


def pick_daemon(network: str, override: str) -> str:
    if override:
        return override
    if network != "stagenet":
        print("mainnet needs --daemon <host:port> (your own or a node you trust)")
        sys.exit(1)
    payload = json.dumps({"jsonrpc": "2.0", "id": "0", "method": "get_info"}).encode()
    for d in STAGENET_DAEMONS:
        try:
            req = urllib.request.Request(f"http://{d}/json_rpc", data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if json.loads(resp.read())["result"].get("stagenet"):
                    return d
        except Exception:
            continue
    print("no public stagenet node reachable — pass one with --daemon")
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", choices=["stagenet", "mainnet"], default="stagenet")
    ap.add_argument("--port", type=int, default=18083)
    ap.add_argument("--daemon", default="")
    ap.add_argument("--wallet", default="operator")
    args = ap.parse_args()

    binary = find_binary()
    daemon = pick_daemon(args.network, args.daemon)
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  network: {args.network}   daemon: {daemon}")

    cmd = [binary, "--rpc-bind-port", str(args.port), "--disable-rpc-login",
           "--wallet-dir", str(WALLET_DIR), "--daemon-address", daemon,
           "--log-file", str(WALLET_DIR / "wallet-rpc.log"), "--log-level", "0"]
    if args.network == "stagenet":
        cmd.insert(1, "--stagenet")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (WALLET_DIR / "sidecar.pid").write_text(str(proc.pid))

    # wait for the RPC to come up
    for _ in range(60):
        if proc.poll() is not None:
            print(f"wallet-rpc exited early — see {WALLET_DIR}/wallet-rpc.log")
            return 1
        try:
            rpc(args.port, "get_version")
            break
        except Exception:
            time.sleep(1)
    else:
        print("wallet-rpc did not come up in 60s")
        proc.terminate()
        return 1

    pw = wallet_password()
    keys_file = WALLET_DIR / f"{args.wallet}.keys"
    try:
        if keys_file.exists():
            rpc(args.port, "open_wallet", {"filename": args.wallet, "password": pw})
            print(f"  ✓ opened wallet {args.wallet!r}")
        else:
            rpc(args.port, "create_wallet",
                {"filename": args.wallet, "password": pw, "language": "English"})
            print(f"  ✓ created wallet {args.wallet!r} (password in "
                  f"{WALLET_DIR}/wallet_password.txt)")
        addr = rpc(args.port, "get_address")["address"]
    except Exception as e:
        print(f"wallet setup failed: {e}")
        proc.terminate()
        return 1

    # wire the app config
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    mon = cfg.setdefault("monero", {})
    mon["wallet_rpc_url"] = f"http://127.0.0.1:{args.port}/json_rpc"
    mon["address"] = addr
    mon.setdefault("credits_per_xmr", 20000)
    # stagenet blocks are ~2 min and coins are valueless: 3 confs is plenty
    mon.setdefault("min_confirmations", 10 if args.network == "mainnet" else 3)
    mon["network"] = args.network
    CONFIG.write_text(json.dumps(cfg, indent=2))
    print(f"  ✓ config.json updated (restart the app server to pick it up)")
    print(f"\n  deposit address ({args.network}):\n  {addr}\n")
    if args.network == "stagenet":
        print("  Get free stagenet coins for a SENDER wallet via "
              "scripts/monero_test_deposit.py\n")

    print(f"  sidecar running (pid {proc.pid}) — Ctrl-C or "
          "'Stop Monero Sidecar.command' to stop")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        (WALLET_DIR / "sidecar.pid").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
