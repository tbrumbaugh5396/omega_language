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
import os
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

# Which fleet node this PROCESS is. "local" is the provider's own box —
# the default, and what every single-machine install is. A worker node's
# process is started with BUSINESS_CONTROL_NODE=<node id> and serves only
# the tenants placed on that node; everything else in the codebase keys
# off this one name.
NODE_ID = os.environ.get("BUSINESS_CONTROL_NODE", "local")

# The key a WORKER process requires on inbound /api/node/* calls. Set by
# the same environment that names the node; the provider holds each
# node's key in its registry and sends it with every shipment.
NODE_KEY = os.environ.get("BUSINESS_CONTROL_NODE_KEY", "")

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


def bust_cache() -> None:
    """Force the next registry() to re-read. Writers call this because a
    same-second write can land inside one mtime tick."""
    with _reg_lock:
        _reg_cache["mtime"] = None


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


class Suspended(Exception):
    """The hostname is claimed, but the tenant is shut down. A different
    answer from UnknownHost on purpose: their data is still here, and
    saying "no such site" to a paused customer is a lie."""


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

    def _live(tid):
        if (reg["tenants"][tid].get("status") or "active") == "suspended":
            raise Suspended(tid)
        return tid

    for tid, t in reg.get("tenants", {}).items():
        if name in [h.lower() for h in t.get("hosts", [])]:
            return _live(tid)
    for suffix in (".localhost", ".local"):
        if name.endswith(suffix):
            tid = name[: -len(suffix)]
            if tid in reg.get("tenants", {}):
                return _live(tid)
            raise UnknownHost(name)
    default = reg.get("default")
    if default in reg.get("tenants", {}):
        # Bare IPs, localhost, LAN names, TestClient's "testserver" — the
        # machine's own address is the default tenant's front door.
        if (name in ("localhost", "testserver", "") or
                name.replace(".", "").isdigit()):
            return _live(default)
    raise UnknownHost(name)


def node_of(tid) -> str:
    """Which node a tenant is placed on ("local" when unplaced)."""
    reg = registry()
    if not reg or not tid:
        return "local"
    return (reg.get("tenants", {}).get(tid, {}).get("node")
            or "local")


def merge_tenants(entries: dict) -> None:
    """A worker node learning about its tenants from the provider.

    The provider's registry is the source of truth; a worker holds only
    the slice that concerns it — the tenants shipped to it, with their
    hosts, status and caps — and never a "provider" key, so the fleet's
    own routes stay 404 on every worker. Entries replace whole: the
    provider said so, and the worker has no competing opinion to merge.
    """
    reg = registry() or {"tenants": {}}
    reg.setdefault("tenants", {})
    for tid, entry in entries.items():
        if not str(tid).replace("-", "").replace("_", "").isalnum():
            continue
        reg["tenants"][tid] = entry
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    bust_cache()


def drop_tenant_entry(tid: str) -> None:
    """A worker forgetting a tenant that was recalled or destroyed."""
    reg = registry() or {}
    (reg.get("tenants") or {}).pop(tid, None)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    bust_cache()


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


def caps_of(tid) -> list | None:
    """What the provider granted this tenant — the capability ids from the
    quote it was stood up on. None = everything (legacy installs, the
    provider itself, tenants stood up before entitlements existed): the
    absence of a grant must never take features away from anyone who
    already had them all."""
    reg = registry()
    if not reg or not tid:
        return None
    caps = reg.get("tenants", {}).get(tid, {}).get("caps")
    return list(caps) if caps else None


# What a tenant is entitled to, of the things that are counted. Absent
# means the class's own allowance, and a class nobody recognises means
# the smallest — never "unlimited", because a missing number that reads
# as infinity is how a client ends up with eleven tills on a one-till
# plan and an invoice nobody can explain.
LIMIT_KEYS = ("locations", "seats", "registers", "kiosks")

# How far a client may raise their own limits without asking. Small
# increments are a decision they are entitled to make about their own
# business at a published price; a jump to fifty tills is a conversation,
# because it is either a new shop or a mistake and both deserve a person.
SELF_SERVE_CEILING = {"locations": 5, "seats": 25, "registers": 6,
                      "kiosks": 6}


def ceiling_of(tid) -> dict:
    """The most this tenant may grant themselves, per kind."""
    reg = registry()
    row = (reg or {}).get("tenants", {}).get(tid or "", {})
    out = dict(SELF_SERVE_CEILING)
    for k, v in (row.get("self_serve_max") or {}).items():
        if k in LIMIT_KEYS and str(v).strip() != "":
            out[k] = max(0, int(v))
    return out


def set_ceiling(tid: str, caps: dict) -> dict:
    reg = registry() or {"tenants": {}}
    row = reg.setdefault("tenants", {}).setdefault(tid, {})
    keep = {k: max(0, int(v)) for k, v in caps.items()
            if k in LIMIT_KEYS and str(v).strip() != ""}
    if keep:
        row["self_serve_max"] = keep
    else:
        row.pop("self_serve_max", None)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    bust_cache()
    return keep


def limits_of(tid) -> dict:
    """The counts this tenant may use. The provider's own install has
    none — it is not a customer of itself."""
    reg = registry()
    if not reg or not tid:
        return {}
    row = reg.get("tenants", {}).get(tid, {})
    if row.get("provider"):
        return {}
    out = dict(row.get("limits") or {})
    return {k: int(v) for k, v in out.items()
            if k in LIMIT_KEYS and str(v).strip() != ""}


def set_limits(tid: str, limits: dict) -> dict:
    """Record what was sold. A value of 0 means none allowed; removing the
    key means fall back to whatever the plan includes."""
    reg = registry() or {"tenants": {}}
    row = reg.setdefault("tenants", {}).setdefault(tid, {})
    keep = {}
    for k in LIMIT_KEYS:
        if k in limits and str(limits[k]).strip() != "":
            keep[k] = max(0, int(limits[k]))
    if keep:
        row["limits"] = keep
    else:
        row.pop("limits", None)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    bust_cache()
    return keep


def create(tid: str, hosts: list | None = None, default: bool = False,
           node: str = "", klass: str = "growing", brand: str = "",
           caps: list | None = None):
    """Mint a tenant: directory, config with its own secrets, registry row,
    a node to live on, schema. Idempotent on the directory."""
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
    reg["tenants"][tid].setdefault("status", "active")
    reg["tenants"][tid]["class"] = klass
    if node:
        reg["tenants"][tid]["node"] = node
    if caps:
        # the entitlement: what the quote sold, recorded where the provider
        # keeps its bookkeeping. Never written empty — see caps_of().
        reg["tenants"][tid]["caps"] = sorted(set(caps))
    d = tenant_dir(tid)
    d.mkdir(parents=True, exist_ok=True)
    cfg_path = d / "config.json"
    if not cfg_path.exists():
        cfg_path.write_text(json.dumps(
            {"admin_key": secrets.token_urlsafe(24),
             "pin_pepper": secrets.token_urlsafe(32),
             "brand_name": brand or tid.title()}, indent=2))
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    bust_cache()
    if INIT:
        INIT(tid)
        _name_the_shop(tid, brand or tid.title())
    return d


def _name_the_shop(tid: str, brand: str) -> None:
    """Put the business's name on its storefront, not just its ops app.

    Standing a client up used to brand the back office and leave the shop
    saying "your brand" — the first thing their own customers would see,
    and the first thing the client would ask about. Only the name is set;
    colours, typefaces and copy stay the neutral default, because those are
    a decision and this is a fact.
    """
    from . import db
    tok = CURRENT.set(tid)
    try:
        con = db.connect()
        try:
            row = con.execute("SELECT v FROM store_meta WHERE k='theme'"
                              ).fetchone()
            theme = json.loads(row["v"]) if row else {}
            if theme.get("brand"):
                return                       # already named; leave it alone
            low = brand.lower()
            theme.update({
                "brand": low,
                "title": f"{brand} — online store",
                "footer": f"© {brand} · powered by business-control"})
            con.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                        " VALUES('theme',?)", (json.dumps(theme),))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass          # a shop with a default name is not worth a failed
                      # stand-up; the operator can set it in the editor
    finally:
        CURRENT.reset(tok)


def add_hosts(tid: str, hosts: list) -> list:
    """Give a tenant more names to answer to. Returns the full host list.
    Merging, never replacing — launching on a real domain must not take
    the .localhost door away."""
    reg = registry() or {}
    t = (reg.get("tenants") or {}).get(tid)
    if t is None:
        raise ValueError(f"no tenant '{tid}'")
    have = set(t.get("hosts", []))
    t["hosts"] = sorted(have | {h.strip().lower() for h in hosts
                                if h.strip()})
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    bust_cache()
    return t["hosts"]


def set_caps(tid: str, caps: list) -> None:
    """Replace a tenant's capability grant. Only ever called with a real
    list from a quote — an empty grant is never written, because missing
    caps means everything on and that meaning must stay unambiguous."""
    if not caps:
        return
    reg = registry() or {}
    t = (reg.get("tenants") or {}).get(tid)
    if t is None:
        raise ValueError(f"no tenant '{tid}'")
    t["caps"] = sorted(set(caps))
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    bust_cache()


def set_status(tid: str, status: str) -> None:
    """Shut a tenant down, or wake it up. Suspended keeps every byte and
    stops answering — the reversible half of 'remove this client'."""
    if status not in ("active", "suspended"):
        raise ValueError("status is active or suspended")
    reg = registry() or {}
    t = (reg.get("tenants") or {}).get(tid)
    if t is None:
        raise ValueError(f"no tenant '{tid}'")
    t["status"] = status
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    bust_cache()


def destroy(tid: str, keep_data: bool = True, actor: str = ""):
    """Remove a tenant from the fleet.

    keep_data moves the directory to data/retired/<tid>-<stamp> rather than
    deleting it: a business that leaves still owns its records, and the
    week after a cancellation is exactly when someone asks for an export.
    """
    reg = registry() or {}
    if tid not in (reg.get("tenants") or {}):
        raise ValueError(f"no tenant '{tid}'")
    if tid == reg.get("provider"):
        raise ValueError("the provider runs the platform — it cannot be "
                         "removed from inside itself")
    from . import fleet
    nid = node_of(tid)
    if fleet.node_addr(nid):
        # the data lives on a worker: recall it for retirement, or tell
        # the node to purge — either way the machine stops holding a
        # business that left
        if keep_data:
            fleet.recall_tenant(tid, nid, actor)
        else:
            fleet._node_call(nid, "DELETE", f"/api/node/tenants/{tid}")
    d = tenant_dir(tid)
    kept = ""
    if d.exists():
        if keep_data:
            import shutil
            dest = (config.DATA_DIR / "retired"
                    / f"{tid}-{time.strftime('%Y%m%d-%H%M%S')}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(dest))
            kept = str(dest)
        else:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
    from . import fleet
    reaped = fleet.release(tid, actor)
    return {"kept": kept, "nodes_destroyed": reaped}
