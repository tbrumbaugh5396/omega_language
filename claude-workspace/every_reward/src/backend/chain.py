"""Read-only Ethereum JSON-RPC client (stdlib urllib).

Non-custodial by design: this module only READS the chain — it verifies
deposit transactions sent to the operator's own wallet and reads Chainlink
price feeds. No keys, no signing, no outbound transactions, ever.
"""
import json
import time
import urllib.request


class ChainError(Exception):
    pass


def rpc(cfg: dict, method: str, params: list):
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    last_err = None
    for url in cfg["rpc_urls"]:
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json",
                         "User-Agent": "every-reward/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                out = json.loads(resp.read())
            if "error" in out:
                raise ChainError(str(out["error"]))
            return out["result"]
        except ChainError:
            raise
        except Exception as e:  # network trouble: try next RPC endpoint
            last_err = e
    raise ChainError(f"all RPC endpoints failed: {last_err}")


# keccak("Transfer(address,address,uint256)") — the ERC-20 transfer event topic
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def token_transfer_credits(logs: list, tokens: dict, deposit_addr: str):
    """Scan receipt logs for configured-token transfers to the deposit wallet.

    tokens: {"USDC": {"address": "0x..", "decimals": 6, "credits_per_token": N}}
    Returns {"asset", "amount_raw", "credits"} for the first token with a
    positive total, or None. Pure function so it is unit-testable offline.
    """
    dep_word = deposit_addr.lower().removeprefix("0x")
    for sym, t in tokens.items():
        taddr = t["address"].lower()
        total = 0
        for log in logs or []:
            topics = log.get("topics") or []
            if ((log.get("address") or "").lower() == taddr
                    and len(topics) >= 3
                    and topics[0].lower() == TRANSFER_TOPIC
                    and topics[2].lower().endswith(dep_word)):
                total += int(log.get("data", "0x0"), 16)
        if total > 0:
            credits = total * int(t["credits_per_token"]) // 10 ** int(t["decimals"])
            return {"asset": sym, "amount_raw": total, "credits": credits}
    return None


def verify_deposit(cfg: dict, tx_hash: str, expected_from: str = None) -> dict:
    """Verify a deposit tx to the configured deposit address.

    Accepts native ETH transfers and ERC-20 transfers of configured tokens
    (detected from the receipt's Transfer logs). When expected_from is given
    (wallet-authenticated users), the tx sender must match it — otherwise any
    user could claim a stranger's deposit. Returns
    {"asset", "amount_raw", "credits", "from"} or raises ChainError.
    """
    dep = (cfg.get("deposit_address") or "").lower()
    if not dep:
        raise ChainError("deposits are not configured (no deposit_address set)")
    tx_hash = tx_hash.strip().lower()
    if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
        raise ChainError("that does not look like a transaction hash")

    tx = rpc(cfg, "eth_getTransactionByHash", [tx_hash])
    if tx is None:
        raise ChainError("transaction not found on chain")

    receipt = rpc(cfg, "eth_getTransactionReceipt", [tx_hash])
    if receipt is None or receipt.get("blockNumber") is None:
        raise ChainError("transaction is not yet mined — try again shortly")
    if int(receipt.get("status", "0x0"), 16) != 1:
        raise ChainError("transaction failed on chain")

    head = int(rpc(cfg, "eth_blockNumber", []), 16)
    confirmations = head - int(receipt["blockNumber"], 16) + 1
    need = int(cfg.get("min_confirmations", 3))
    if confirmations < need:
        raise ChainError(f"only {confirmations}/{need} confirmations — try again shortly")

    sender = (tx.get("from") or "").lower()
    if expected_from and sender != expected_from.lower():
        raise ChainError(
            "that transaction was not sent from your signed-in wallet address")
    value = int(tx.get("value", "0x0"), 16)
    if (tx.get("to") or "").lower() == dep and value > 0:
        credits = value * int(cfg["credits_per_eth"]) // 10 ** 18
        return {"asset": "ETH", "amount_raw": value, "credits": credits, "from": sender}

    found = token_transfer_credits(receipt.get("logs"), cfg.get("tokens", {}), dep)
    if found:
        found["from"] = sender
        return found
    raise ChainError(
        "transaction sends neither ETH nor a supported token to the deposit wallet")


# ---- Chainlink price feeds (read-only eth_call) ----
# latestRoundData() selector = keccak("latestRoundData()")[:4] = 0xfeaf968c
_LATEST_ROUND_DATA = "0xfeaf968c"


def decode_latest_round(result: str) -> tuple:
    """Decode latestRoundData() return -> (answer: int, updated_at: int)."""
    raw = result[2:] if result.startswith("0x") else result
    if len(raw) < 64 * 5:
        raise ChainError("unexpected feed response")
    # (roundId, answer, startedAt, updatedAt, answeredInRound); answer is int256
    answer = int(raw[64:128], 16)
    if answer >= 2 ** 255:
        answer -= 2 ** 256
    updated_at = int(raw[192:256], 16)
    return answer, updated_at


def chainlink_price(cfg: dict, feed_address: str, decimals: int = 8) -> float:
    """Read the latest answer from a Chainlink aggregator feed.

    Rejects stale rounds: a paused or broken feed must not resolve markets on
    an old price. Max age comes from cfg oracle_max_age_sec.
    """
    result = rpc(
        cfg, "eth_call", [{"to": feed_address, "data": _LATEST_ROUND_DATA}, "latest"]
    )
    answer, updated_at = decode_latest_round(result)
    max_age = int(cfg.get("oracle_max_age_sec", 21600))
    age = int(time.time()) - updated_at
    if age > max_age:
        raise ChainError(
            f"oracle data is stale ({age}s old, limit {max_age}s) — refusing to resolve")
    return answer / (10 ** decimals)
