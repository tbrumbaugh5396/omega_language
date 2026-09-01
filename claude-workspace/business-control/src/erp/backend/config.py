"""Configuration and paths. Everything lives inside the project folder."""
import json
import os
import secrets
import threading
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("BUSINESS_CONTROL_DATA", APP_ROOT / "data"))
FRONTEND_DIR = APP_ROOT / "src" / "erp" / "frontend"
STOREFRONT_DIR = APP_ROOT / "src" / "storefront" / "frontend"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "business_control.db"

FUNNEL_STEPS = ["visit", "view_product", "add_to_cart", "checkout", "purchase"]

DEFAULTS = {
    "brand_name": "Business Control",
    "brand_tagline": "",              # small line under the brand name
    "brand_accent": "",               # hex color; empty = default green
    "port": 8860,
    # Auth
    "admin_key": "",                 # set on first run; grants admin on login
    "pin_pepper": "",                # set on first run; hashes time-clock PINs
    # Affiliates
    "default_commission_bps": 1000,  # 10% of order subtotal
    # A/B testing
    "ab_min_exposures": 30,          # per variant before a winner can be called
    "ab_significance_z": 1.96,       # ~95% confidence
    # Engagement fall-off: alert when last 7 days < ratio * prior 7 days
    "falloff_ratio": 0.75,
    # QR sign-in links expire after this many seconds (single use)
    "qr_login_ttl_sec": 600,
    # Third-party analytics pixels. Empty id = that pixel never loads.
    # meta_pixel_id covers Facebook AND Instagram (one Meta pixel for both).
    "tracking": {
        "ga_measurement_id": "",   # Google Analytics 4, e.g. G-XXXXXXXXXX
        "meta_pixel_id": "",       # Meta pixel (Facebook + Instagram)
        "tiktok_pixel_id": "",
    },
    # Regions used for analytics groupings and outreach
    "regions": ["Northeast", "Southeast", "Midwest", "Southwest", "West"],
    # Order totals
    "tax_bps": 800,                     # 8% sales tax on customer orders
    "shipping_flat_cents": 599,
    "free_shipping_over_cents": 4000,   # matches the "over $40" storefront copy
    # Stripe Checkout (optional). Empty key = card payments off; customer
    # orders fall back to pay-on-delivery, distributor orders to on-terms.
    "stripe_secret_key": "",
    # Going public: set to e.g. "https://shop.yourbrand.com" once deployed —
    # QR codes, sign-in links, and emails then use it instead of the LAN IP.
    "public_base_url": "",
    # Passwords on accounts. True/False is an explicit answer either way;
    # None means "decide by exposure" — required the moment
    # public_base_url is set, optional on a trusted LAN. Going public
    # flips the default, and nobody has to remember the checklist row.
    "require_passwords": None,
    # A bearer token unused this many days expires (sliding window,
    # refreshed by use). 0 disables — sessions then live until rotated.
    "session_days": 30,
    # Route time model: highway-ish average speed + per-stop service time
    "route_avg_kmh": 55,
    "stop_service_min": 20,
    # Regenerate the region's coverage route whenever a store is added
    "auto_routes_on_store_add": True,
    # P&L assumptions (edit to your real numbers)
    "cogs_bps": 4500,             # cost of goods = 45% of revenue
    "hourly_wage_cents": 1800,    # $18/h average loaded labor cost
    "cost_per_km_cents": 85,      # trucking cost per km (fuel+maintenance)
    # Independent contractor drivers: paid per completed route + per stop
    "contractor_per_route_cents": 9000,
    "contractor_per_stop_cents": 800,
    # Private Shopify subscription app. Empty shop_domain = mock mode (a fake
    # contract book so the bill-run pipeline is testable without a store).
    "shopify": {"shop_domain": "",          # e.g. my-brand-dev.myshopify.com
                "admin_token": "",          # custom-app Admin API token (server-side only)
                "api_version": "2026-07",
                "webhook_secret": ""},
    # Box-cycle calendar template (day-of-month for each cutoff)
    "box_cycle": {"bill_day": 1, "dunning_days": 5, "curation_day": 8,
                  "ship_day": 15},
    # Web push (phone notifications). VAPID keys are generated automatically
    # into data/vapid_private.pem; subject is a contact for push services.
    "vapid_subject": "mailto:owner@localhost",
    # Email (SMTP). Empty host = emails are logged as 'dry' but never sent.
    "smtp": {"host": "", "port": 587, "username": "", "password": "",
             "starttls": True},
    "email_from": "Business Control <no-reply@localhost>",
    # Automated marketing playbooks (run on the notification sweep)
    "email_playbooks": {
        "abandoned_cart": True,   # added to cart 1-48h ago, never purchased
        "winback": True,          # no order in 30+ days
    },
}


def _config_path() -> Path:
    """The current tenant's config file — the bare data dir until tenancy
    is switched on."""
    from . import tenancy
    return tenancy.data_dir() / "config.json"


def load(path: Path | None = None) -> dict:
    path = path or _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text()))
        except Exception:
            pass
    if not cfg.get("admin_key"):
        cfg["admin_key"] = secrets.token_urlsafe(24)
        _write(path, cfg)
    # The pepper for time-clock PINs. It lives here rather than in the
    # database on purpose: that separation is the whole point — a stolen
    # copy of the database has to be useless on its own.
    if not cfg.get("pin_pepper"):
        cfg["pin_pepper"] = secrets.token_urlsafe(32)
        _write(path, cfg)
    return cfg


class TenantConfig:
    """CFG, made tenant-aware without touching its fifty call sites.

    The app treats CFG as a dict: reads it, mutates it from settings
    handlers, hands it to the mailer and Stripe helpers. All of that keeps
    working — this object just answers every operation against the dict
    belonging to whichever tenant the current request resolved to, loaded
    on first touch and cached per tenant. Legacy mode is the tenant None,
    which is the bare data dir, which is exactly what CFG always was.
    """

    def __init__(self):
        self._cache: dict = {}
        self._lock = threading.Lock()

    def _data(self) -> dict:
        from . import tenancy
        tid = tenancy.CURRENT.get()
        with self._lock:
            if tid not in self._cache:
                self._cache[tid] = load(
                    tenancy.tenant_dir(tid) / "config.json")
            return self._cache[tid]

    def invalidate(self, tid=None) -> None:
        with self._lock:
            self._cache.pop(tid, None)

    def __getitem__(self, k): return self._data()[k]
    def __setitem__(self, k, v): self._data()[k] = v
    def __delitem__(self, k): del self._data()[k]
    def __contains__(self, k): return k in self._data()
    def __iter__(self): return iter(self._data())
    def __len__(self): return len(self._data())
    def get(self, k, default=None): return self._data().get(k, default)
    def update(self, *a, **kw): self._data().update(*a, **kw)
    def keys(self): return self._data().keys()
    def items(self): return self._data().items()
    def values(self): return self._data().values()


_PROXY = None


def proxy() -> TenantConfig:
    global _PROXY
    if _PROXY is None:
        _PROXY = TenantConfig()
    return _PROXY


def _write(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2))


def save(cfg) -> None:
    """Write the current tenant's config. Accepts the proxy (the normal
    case — handlers mutate CFG then save it) or a plain dict (scripts)."""
    data = cfg._data() if isinstance(cfg, TenantConfig) else cfg
    _write(_config_path(), data)
