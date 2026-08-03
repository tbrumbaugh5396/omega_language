"""End-to-end stagenet deposit test helper.

The claim flow needs the SENDER's txid + tx_key, so this manages a second
('sender') wallet inside the running sidecar:

  step 1:  python3 scripts/monero_test_deposit.py          -> prints sender
           address; fund it at a stagenet faucet, wait ~3 blocks (~6 min)
  step 2:  python3 scripts/monero_test_deposit.py send 0.5 -> sends to the
           operator address and prints the txid + tx_key to paste in the app

Stagenet coins are valueless test tokens. Leaves the operator wallet open.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WALLET_DIR = ROOT / "data" / "monero"
CONFIG = ROOT / "data" / "config.json"

sys.path.insert(0, str(ROOT / "scripts"))
from monero_sidecar import rpc, wallet_password  # noqa: E402

ATOMIC = 10 ** 12
FAUCETS = ["https://stagenet-faucet.xmr-tw.org/",
           "https://community.rino.io/faucet/stagenet/"]


def open_wallet(port, name, pw):
    if (WALLET_DIR / f"{name}.keys").exists():
        rpc(port, "open_wallet", {"filename": name, "password": pw})
    else:
        rpc(port, "create_wallet", {"filename": name, "password": pw,
                                    "language": "English"})


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    mon = cfg.get("monero", {})
    if not mon.get("wallet_rpc_url"):
        print("run the sidecar first: 'Start Monero Sidecar (stagenet).command'")
        return 1
    if mon.get("network") == "mainnet":
        print("this test helper is for stagenet only")
        return 1
    port = int(mon["wallet_rpc_url"].split(":")[2].split("/")[0])
    operator_addr = mon["address"]
    pw = wallet_password()

    open_wallet(port, "sender", pw)
    rpc(port, "refresh")
    addr = rpc(port, "get_address")["address"]
    bal = rpc(port, "get_balance")
    balance, unlocked = bal["balance"], bal["unlocked_balance"]
    print(f"  sender address: {addr}")
    print(f"  balance: {balance / ATOMIC} XMR ({unlocked / ATOMIC} spendable)")

    if len(sys.argv) > 1 and sys.argv[1] == "send":
        amount = float(sys.argv[2]) if len(sys.argv) > 2 else 0.1
        atomic = int(amount * ATOMIC)
        if unlocked < atomic:
            print(f"\n  not enough spendable balance for {amount} XMR."
                  "\n  faucet-funded coins unlock ~10 blocks (~20 min) after arrival.")
            return 1
        r = rpc(port, "transfer", {
            "destinations": [{"amount": atomic, "address": operator_addr}],
            "get_tx_key": True, "priority": 1})
        print(f"\n  sent {amount} XMR -> operator")
        print(f"  txid:   {r['tx_hash']}")
        print(f"  tx_key: {r['tx_key']}")
        print(f"\n  After {mon.get('min_confirmations', 3)} confirmations "
              "(~2 min/block), paste BOTH into the app's Wallet tab XMR claim.")
    else:
        print("\n  To fund it, paste the sender address into a stagenet faucet:")
        for f in FAUCETS:
            print(f"    {f}")
        print("\n  Then: python3 scripts/monero_test_deposit.py send 0.1")

    # leave the operator wallet open for the app's verifications
    rpc(port, "open_wallet", {"filename": "operator", "password": pw})
    return 0


if __name__ == "__main__":
    sys.exit(main())
