"""Monero deposit adapter. Optional: off unless monero.wallet_rpc_url is set.

Monero's chain is private (RingCT, stealth addresses), so deposits cannot be
verified from public chain data like the EVM path. Instead this talks to a
monero-wallet-rpc daemon loaded with the operator's VIEW-ONLY wallet: it can
see incoming funds but cannot spend — the spend key never touches this machine.

Claim flow: the sender pastes their txid plus the per-transaction secret key
(tx_key — shown by their own wallet, e.g. `get_tx_key` in monero-wallet-cli or
the GUI's tx details). `check_tx_key` then proves that tx paid our address.
Only the sender's wallet knows the tx_key, so possession of it IS proof of
being the sender — no further sender binding is possible or needed.

Run the sidecar like:
  monero-wallet-rpc --rpc-bind-port 18083 --wallet-file view_only.keys \
      --daemon-address <node>:18081 --disable-rpc-login
"""
import json
import urllib.request

ATOMIC = 10 ** 12  # piconero per XMR

_HEX = set("0123456789abcdef")


class MoneroError(Exception):
    pass


def enabled(cfg: dict) -> bool:
    m = cfg.get("monero", {})
    return bool(m.get("wallet_rpc_url") and m.get("address"))


def wallet_rpc(mcfg: dict, method: str, params: dict):
    url = mcfg["wallet_rpc_url"]
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": "0", "method": method, "params": params}
    ).encode()
    handlers = []
    login = mcfg.get("rpc_login")  # "user:pass" if the daemon uses --rpc-login
    if login:
        user, _, pwd = login.partition(":")
        mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        mgr.add_password(None, url, user, pwd)
        handlers.append(urllib.request.HTTPDigestAuthHandler(mgr))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=20) as resp:
            out = json.loads(resp.read())
    except Exception as e:
        raise MoneroError(f"monero wallet-rpc unreachable: {e}")
    if "error" in out:
        err = out["error"]
        raise MoneroError(str(err.get("message", err) if isinstance(err, dict) else err))
    return out.get("result", {})


def verify_deposit(cfg: dict, txid: str, tx_key: str) -> dict:
    """Verify an XMR payment to the operator address via check_tx_key.

    Returns {"asset", "amount_raw", "credits", "from"} (from is always None —
    Monero senders are anonymous by design) or raises MoneroError.
    """
    if not enabled(cfg):
        raise MoneroError("Monero deposits are not configured")
    m = cfg["monero"]
    txid = txid.strip().lower()
    tx_key = tx_key.strip().lower()
    if len(txid) != 64 or not set(txid) <= _HEX:
        raise MoneroError("that does not look like a Monero transaction id")
    if len(tx_key) != 64 or not set(tx_key) <= _HEX:
        raise MoneroError("that does not look like a tx secret key (64 hex chars, "
                          "from your wallet's transaction details)")

    r = wallet_rpc(m, "check_tx_key",
                   {"txid": txid, "tx_key": tx_key, "address": m["address"]})
    received = int(r.get("received", 0))
    if received <= 0:
        raise MoneroError("that transaction does not pay the deposit address")
    if r.get("in_pool"):
        raise MoneroError("transaction is still in the mempool — try again shortly")
    confirmations = int(r.get("confirmations", 0))
    need = int(m.get("min_confirmations", 10))
    if confirmations < need:
        raise MoneroError(
            f"only {confirmations}/{need} confirmations — try again shortly")

    credits = received * int(m["credits_per_xmr"]) // ATOMIC
    return {"asset": "XMR", "amount_raw": received, "credits": credits, "from": None}
