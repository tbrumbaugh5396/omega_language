"""Outcome resolvers ("oracles"). Each returns the winning outcome_id or None.

resolver_config (JSON on the market row):
  chainlink_price: {"feed": "0x...", "decimals": 8, "threshold": 4000.0,
                    "above_outcome": <label or index>, "below_outcome": ...}
  http_json:       {"url": "https://...", "path": "a.b.0.c",
                    "equals": {"<value>": <label or index>, ...}}
  manual:          resolved from the admin panel only.
"""
import json
import urllib.request

from . import chain


class ResolveError(Exception):
    pass


def _pick(outcomes: list, ref) -> int:
    """Map a label or index from config to an outcome_id."""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        idx = int(ref)
        if 0 <= idx < len(outcomes):
            return outcomes[idx]["id"]
    for o in outcomes:
        if str(o["label"]).strip().lower() == str(ref).strip().lower():
            return o["id"]
    raise ResolveError(f"resolver config references unknown outcome {ref!r}")


def resolve(cfg: dict, market, outcomes: list):
    kind = market["resolver"]
    if kind == "manual":
        return None
    rc = json.loads(market["resolver_config"] or "{}")

    if kind == "chainlink_price":
        price = chain.chainlink_price(cfg, rc["feed"], int(rc.get("decimals", 8)))
        threshold = float(rc["threshold"])
        ref = rc.get("above_outcome", 0) if price >= threshold else rc.get("below_outcome", 1)
        return {"winner_outcome_id": _pick(outcomes, ref),
                "evidence": f"chainlink {rc['feed'][:10]}… = {price} vs threshold {threshold}"}

    if kind == "http_json":
        with urllib.request.urlopen(rc["url"], timeout=15) as resp:
            data = json.loads(resp.read())
        value = data
        for part in str(rc.get("path", "")).split("."):
            if part == "":
                continue
            value = value[int(part)] if isinstance(value, list) else value[part]
        mapping = rc.get("equals", {})
        for k, ref in mapping.items():
            if str(value).strip().lower() == str(k).strip().lower():
                return {"winner_outcome_id": _pick(outcomes, ref),
                        "evidence": f"{rc['url']} -> {value!r}"}
        raise ResolveError(f"value {value!r} matched no outcome mapping")

    raise ResolveError(f"unknown resolver {kind}")
