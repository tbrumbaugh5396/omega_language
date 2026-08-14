"""Configuration and paths. Everything lives inside the project folder."""
import json
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("AV_TRAINER_DATA", APP_ROOT / "data"))
FRONTEND_DIR = APP_ROOT / "src" / "frontend"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "avtrainer.db"

DEFAULTS = {
    "port": 8910,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
