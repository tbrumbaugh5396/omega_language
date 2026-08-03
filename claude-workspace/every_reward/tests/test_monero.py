"""Monero adapter: check_tx_key verification logic, offline via fake wallet-rpc."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EVERY_REWARD_DATA"] = tempfile.mkdtemp(prefix="er_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend import monero  # noqa: E402

TXID = "ab" * 32
TXKEY = "cd" * 32
MCFG = {"wallet_rpc_url": "http://fake/json_rpc", "address": "4xxTEST",
        "credits_per_xmr": 20000, "min_confirmations": 10}
CFG = {"monero": MCFG}

# disabled when not configured
assert not monero.enabled({"monero": {"wallet_rpc_url": "", "address": ""}})
assert monero.enabled(CFG)
try:
    monero.verify_deposit({"monero": {}}, TXID, TXKEY)
    raise AssertionError("unconfigured adapter accepted a claim")
except monero.MoneroError as e:
    assert "not configured" in str(e)


def fake(result):
    def rpc(mcfg, method, params):
        assert method == "check_tx_key"
        assert params == {"txid": TXID, "tx_key": TXKEY, "address": "4xxTEST"}
        return result
    return rpc


real = monero.wallet_rpc
try:
    # happy path: 0.5 XMR = 5e11 piconero -> 10000 cr; sender stays anonymous
    monero.wallet_rpc = fake({"received": 5 * 10 ** 11, "confirmations": 12,
                              "in_pool": False})
    r = monero.verify_deposit(CFG, TXID.upper(), TXKEY)  # case-insensitive input
    assert (r["asset"], r["credits"], r["from"]) == ("XMR", 10000, None), r

    # tx that doesn't pay us
    monero.wallet_rpc = fake({"received": 0, "confirmations": 12, "in_pool": False})
    try:
        monero.verify_deposit(CFG, TXID, TXKEY)
        raise AssertionError("zero-value claim accepted")
    except monero.MoneroError as e:
        assert "does not pay" in str(e)

    # still in mempool
    monero.wallet_rpc = fake({"received": 10 ** 12, "confirmations": 0, "in_pool": True})
    try:
        monero.verify_deposit(CFG, TXID, TXKEY)
        raise AssertionError("mempool tx accepted")
    except monero.MoneroError as e:
        assert "mempool" in str(e)

    # under-confirmed
    monero.wallet_rpc = fake({"received": 10 ** 12, "confirmations": 3, "in_pool": False})
    try:
        monero.verify_deposit(CFG, TXID, TXKEY)
        raise AssertionError("under-confirmed tx accepted")
    except monero.MoneroError as e:
        assert "confirmations" in str(e)

    # malformed inputs rejected before any RPC call
    monero.wallet_rpc = fake(None)  # would blow up if reached
    for bad_txid, bad_key in ((TXID[:-2], TXKEY), ("0x" + TXID[2:], TXKEY),
                              (TXID, TXKEY + "ff"), (TXID, "zz" * 32)):
        try:
            monero.verify_deposit(CFG, bad_txid, bad_key)
            raise AssertionError(f"malformed input accepted: {bad_txid[:8]}/{bad_key[:8]}")
        except monero.MoneroError as e:
            assert "look like" in str(e)
finally:
    monero.wallet_rpc = real

print("test_monero: OK")
