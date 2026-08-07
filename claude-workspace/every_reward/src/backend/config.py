"""Configuration and paths. Everything lives inside the project folder."""
import json
import os
import secrets
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("EVERY_REWARD_DATA", APP_ROOT / "data"))
FRONTEND_DIR = APP_ROOT / "src" / "frontend"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "every_reward.db"

DEFAULTS = {
    # Chain settings. Mainnet by default per project decision; the app is
    # non-custodial: deposit_address is YOUR wallet, we only verify txs.
    "chain_id": 1,
    "chain_name": "Ethereum Mainnet",
    "rpc_urls": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"],
    "deposit_address": "",          # empty => deposits disabled until configured
    "credits_per_eth": 100000,      # 1 ETH deposited = 100,000 credits
    # ERC-20 deposits: any Transfer of these tokens to deposit_address counts.
    "tokens": {
        "USDC": {"address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                 "decimals": 6, "credits_per_token": 50},
    },
    "min_confirmations": 3,
    "oracle_max_age_sec": 21600,    # reject Chainlink rounds older than 6h
    # Monero deposits (optional). Needs a monero-wallet-rpc sidecar with your
    # VIEW-ONLY wallet; empty wallet_rpc_url keeps the whole adapter off.
    "monero": {
        "wallet_rpc_url": "",       # e.g. http://127.0.0.1:18083/json_rpc
        "rpc_login": "",            # "user:pass" if the daemon uses --rpc-login
        "address": "",              # your primary XMR address (4... / 8...)
        "credits_per_xmr": 20000,
        "min_confirmations": 10,
    },
    # Auth
    "dev_login": True,              # name-only login for local testing (no wallet)
    "admin_addresses": [],          # lowercase 0x addresses that get admin
    "admin_key": "",                # set on first run; grants admin to dev logins
    # Catalog (auto-priced store items from external feeds)
    "usd_to_credits": 50,           # $1.00 = 50 credits (matches USDC deposit rate)
    "default_markup_bps": 1500,     # 15% markup over source price
    "catalog_max_drift_bps": 2000,  # >20% price move -> suspend for admin review
    "catalog_sync_sec": 300,        # re-fetch source prices every 5 min
    "catalog_max_age_sec": 900,     # refuse redemptions on data older than 15 min
    "pokemontcg_api_key": "",       # optional; raises pokemontcg.io rate limits
    # Markets
    "default_rake_bps": 200,        # 2% house rake on parimutuel pools
    "fixed_odds_margin_bps": 700,   # 7% house edge baked into preset odds
    "default_lmsr_b": 500.0,
    # Server
    "port": 8850,
}


def load() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except Exception:
            pass
    if not cfg.get("admin_key"):
        cfg["admin_key"] = secrets.token_urlsafe(24)
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
