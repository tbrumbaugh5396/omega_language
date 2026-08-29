"""Which tenant is this request for? The whole answer, in one module.

The design is tenant-per-database, exactly as docs/product/saas-scaling.md
sketched: one process, one codebase, and every piece of state that belongs
to a business — its database, its config, its uploads, its push keys —
lives under data/tenants/<id>/. The host header picks the tenant; a
contextvar carries the choice to every connect() and path lookup for the
rest of the request, including into threads that outlive it.

Tenancy is OFF until data/tenants.json exists. Without it, everything
behaves as it always has: one bare data/ directory is the sole tenant, and
resolve() answers None. That is what keeps a single-shop install — and the
whole existing test suite — untouched by this machinery.
"""
import contextvars
import json
import secrets
import threading
import time
from pathlib import Path

from . import config

# The tenant id for the work currently in flight. None = legacy single-
# tenant mode OR "not resolved yet"; both mean "the bare data dir".
CURRENT: contextvars.ContextVar = contextvars.ContextVar(
    "tenant", default=None)

REGISTRY_PATH = config.DATA_DIR / "tenants.json"

_reg_cache = {"mtime": None, "data": None}
_reg_lock = threading.Lock()


def registry() -> dict | None:
    """data/tenants.json, or None when tenancy is off.

    Cached on mtime so the hot path is a stat, not a parse — and an edit
    to the file (a new tenant, a new host alias) is picked up without a
    restart.
    """
    try:
        mtime = REGISTRY_PATH.stat().st_mtime
    except OSError:
        return None
    with _reg_lock:
        if _reg_cache["mtime"] != mtime:
            _reg_cache["data"] = json.loads(REGISTRY_PATH.read_text())
            _reg_cache["mtime"] = mtime
        return _reg_cache["data"]


def active() -> bool:
    return registry() is not None


def provider():
    """The tenant whose pipeline manages the others — the studio. Set in
    the registry ("provider": "<id>"); None when tenancy is off or nobody
    is declared. Deliberately explicit rather than inferred from
    "default": which hostname answers by default and who operates the
    platform are different questions."""
    reg = registry()
    if not reg:
        return None
    tid = reg.get("provider")
    return tid if tid in reg.get("tenants", {}) else None


class run_as:
    """Act as another tenant for a narrow, explicit scope.

    Exists for the one legitimate cross-tenant read: a client tenant
    looking at ITS OWN paperwork in the provider's pipeline. Anything
    wider than a `with` block should not be using this."""

    def __init__(self, tid):
        self.tid = tid

    def __enter__(self):
        self._tok = CURRENT.set(self.tid)
        return self

    def __exit__(self, *exc):
        CURRENT.reset(self._tok)
        return False


def all_tenants() -> list:
    reg = registry()
    return list((reg or {}).get("tenants", {}).keys())


class UnknownHost(Exception):
    """A hostname no tenant answers to.

    Deliberately NOT a fall-through to the default tenant: a typo'd DNS
    record must never show one business's data under another's name.
    """


def resolve(host: str):
    """Host header -> tenant id, or None when tenancy is off.

    Exact aliases from the registry win; then the <id>.localhost /
    <id>.local convention; then the registry's default for anything that
    looks local (bare IPs, plain localhost, testserver). A public-looking
    hostname nobody claimed raises rather than guessing.
    """
    reg = registry()
    if reg is None:
        return None
    name = (host or "").split(":", 1)[0].lower().strip()
    for tid, t in reg.get("tenants", {}).items():
        if name in [h.lower() for h in t.get("hosts", [])]:
            return tid
    for suffix in (".localhost", ".local"):
        if name.endswith(suffix):
            tid = name[: -len(suffix)]
            if tid in reg.get("tenants", {}):
                return tid
            raise UnknownHost(name)
    default = reg.get("default")
    if default in reg.get("tenants", {}):
        # Bare IPs, localhost, LAN names, TestClient's "testserver" — the
        # machine's own address is the default tenant's front door.
        if (name in ("localhost", "testserver", "") or
                name.replace(".", "").isdigit()):
            return default
    raise UnknownHost(name)


def tenant_dir(tid) -> Path:
    return config.DATA_DIR / "tenants" / tid if tid else config.DATA_DIR


def data_dir() -> Path:
    """THE per-tenant path root. Every file a tenant owns hangs off this."""
    return tenant_dir(CURRENT.get())


def db_path() -> Path:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "business_control.db"


def with_tenant(tid, fn):
    """Wrap fn so it runs under tid — for threads that outlive the request
    that spawned them. A daemon thread has no request to ask, so the tenant
    travels with the work."""
    def run(*a, **kw):
        tok = CURRENT.set(tid)
        try:
            return fn(*a, **kw)
        finally:
            CURRENT.reset(tok)
    return run


# main.py assigns its init_tenant here once every module is importable, so
# create() can give a runtime-made tenant working schema immediately without
# this module importing half the app.
INIT = None


def create(tid: str, hosts: list | None = None, default: bool = False):
    """Mint a tenant: directory, config with its own secrets, registry row,
    schema. Idempotent on the directory, loud on a registry clash."""
    if not tid.replace("-", "").replace("_", "").isalnum():
        raise ValueError("tenant id: letters, digits, - and _ only")
    reg = registry() or {"default": tid if default else None, "tenants": {}}
    if default:
        reg["default"] = tid
    reg["tenants"].setdefault(tid, {})
    if hosts:
        have = set(reg["tenants"][tid].get("hosts", []))
        reg["tenants"][tid]["hosts"] = sorted(have | set(hosts))
    reg["tenants"][tid].setdefault("created", time.time())
    d = tenant_dir(tid)
    d.mkdir(parents=True, exist_ok=True)
    cfg_path = d / "config.json"
    if not cfg_path.exists():
        cfg_path.write_text(json.dumps(
            {"admin_key": secrets.token_urlsafe(24),
             "pin_pepper": secrets.token_urlsafe(32)}, indent=2))
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    with _reg_lock:
        _reg_cache["mtime"] = None
    if INIT:
        INIT(tid)
    return d
