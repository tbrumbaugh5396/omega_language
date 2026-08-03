"""Offline tests for ERC-20 deposit log parsing (no network needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend.chain import TRANSFER_TOPIC, token_transfer_credits  # noqa: E402

USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
DEP = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
TOKENS = {"USDC": {"address": USDC, "decimals": 6, "credits_per_token": 50}}


def pad_addr(a):
    return "0x" + "0" * 24 + a.lower().removeprefix("0x")


def transfer_log(token, to, amount):
    return {"address": token,
            "topics": [TRANSFER_TOPIC, pad_addr(OTHER), pad_addr(to)],
            "data": hex(amount)}


# 5 USDC (6 decimals) at 50 cr/token -> 250 credits
r = token_transfer_credits([transfer_log(USDC, DEP, 5_000_000)], TOKENS, DEP)
assert r == {"asset": "USDC", "amount_raw": 5_000_000, "credits": 250}, r

# two transfer logs in one tx sum together
r = token_transfer_credits(
    [transfer_log(USDC, DEP, 1_000_000), transfer_log(USDC, DEP, 2_500_000)], TOKENS, DEP)
assert r["credits"] == 175, r

# transfer to someone else does not count
assert token_transfer_credits([transfer_log(USDC, OTHER, 5_000_000)], TOKENS, DEP) is None

# transfer of an unconfigured token does not count
assert token_transfer_credits([transfer_log(OTHER, DEP, 5_000_000)], TOKENS, DEP) is None

# non-Transfer event on the right token does not count
bad = transfer_log(USDC, DEP, 5_000_000)
bad["topics"][0] = "0x" + "ab" * 32
assert token_transfer_credits([bad], TOKENS, DEP) is None

# empty / missing logs are fine
assert token_transfer_credits([], TOKENS, DEP) is None
assert token_transfer_credits(None, TOKENS, DEP) is None

# sub-cent dust rounds down to 0 credits and is treated as no deposit by caller
r = token_transfer_credits([transfer_log(USDC, DEP, 100)], TOKENS, DEP)
assert r["credits"] == 0

# ---- verify_deposit + chainlink staleness, offline via a fake rpc ----
import time  # noqa: E402

from backend import chain  # noqa: E402

SENDER = "0x3333333333333333333333333333333333333333"
TXH = "0x" + "ab" * 32
CFG = {"deposit_address": DEP, "credits_per_eth": 100000, "min_confirmations": 3,
       "tokens": TOKENS, "rpc_urls": ["fake"], "oracle_max_age_sec": 21600}


def fake_rpc(responses):
    def rpc(cfg, method, params):
        return responses[method]
    return rpc


def eth_tx(value_wei, to=DEP):
    return {
        "eth_getTransactionByHash": {"from": SENDER, "to": to, "value": hex(value_wei)},
        "eth_getTransactionReceipt": {"blockNumber": "0x64", "status": "0x1", "logs": []},
        "eth_blockNumber": "0x6e",  # 11 confirmations
    }


real_rpc = chain.rpc
try:
    # 1 ETH -> 100000 credits, sender recorded
    chain.rpc = fake_rpc(eth_tx(10 ** 18))
    r = chain.verify_deposit(CFG, TXH)
    assert (r["asset"], r["credits"], r["from"]) == ("ETH", 100000, SENDER), r

    # sender binding: claiming someone else's tx is rejected for wallet users
    try:
        chain.verify_deposit(CFG, TXH, expected_from=OTHER)
        raise AssertionError("foreign tx accepted")
    except chain.ChainError as e:
        assert "signed-in wallet" in str(e)
    # ...and accepted when the sender matches
    assert chain.verify_deposit(CFG, TXH, expected_from=SENDER.upper())["credits"] == 100000

    # ERC-20 path through verify_deposit (tx.to = token contract, value 0)
    resp = eth_tx(0, to=USDC)
    resp["eth_getTransactionReceipt"]["logs"] = [transfer_log(USDC, DEP, 5_000_000)]
    chain.rpc = fake_rpc(resp)
    r = chain.verify_deposit(CFG, TXH)
    assert (r["asset"], r["credits"]) == ("USDC", 250), r

    # too few confirmations
    resp = eth_tx(10 ** 18)
    resp["eth_blockNumber"] = "0x65"  # 2 confirmations
    chain.rpc = fake_rpc(resp)
    try:
        chain.verify_deposit(CFG, TXH)
        raise AssertionError("underconfirmed tx accepted")
    except chain.ChainError as e:
        assert "confirmations" in str(e)

    # chainlink: fresh round ok, stale round refused
    def round_data(answer, updated_at):
        words = [0, answer, 0, updated_at, 0]
        return "0x" + "".join(f"{w:064x}" for w in words)

    now = int(time.time())
    chain.rpc = fake_rpc({"eth_call": round_data(2000 * 10 ** 8, now - 60)})
    assert chain.chainlink_price(CFG, "0xfeed") == 2000.0
    chain.rpc = fake_rpc({"eth_call": round_data(2000 * 10 ** 8, now - 100000)})
    try:
        chain.chainlink_price(CFG, "0xfeed")
        raise AssertionError("stale oracle accepted")
    except chain.ChainError as e:
        assert "stale" in str(e)
finally:
    chain.rpc = real_rpc

print("test_chain: OK")
