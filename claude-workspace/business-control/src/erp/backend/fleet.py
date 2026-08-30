"""Nodes, and which tenant lives on which one.

A node is a machine that runs this codebase. A tenant is a business whose
data lives on exactly one node. The deck's cluster model is the arithmetic
here, made executable: capacity is measured in UNITS, not tenants — a
corner shop and a fifty-location distributor are not the same load — and a
4 GB node carries 25 units.

Placement rules, in the order they bite:

  * a tenant is created ONTO a node: an existing one with room, or a new
    one spun up for it. The choice is the operator's, and the default is
    the fullest node that still fits (bin-packing beats round-robin when
    you pay per node).
  * a node with no tenants left is destroyed. Paying for an empty VPS is
    the single most common way a fleet's margin leaks, and the moment it
    empties is the only moment anyone would notice.
  * the node the provider itself lives on is never auto-destroyed, and
    neither is the local one — the machine you are standing on cannot be
    handed back to a cloud API.

Provisioning is a driver. `local` is this machine and does nothing. Any
other node runs the commands in config `fleet.provision_cmd` /
`fleet.destroy_cmd` with {node}/{size}/{region} substituted — point them at
`hcloud server create …` and the button really makes a server. Unset, a
node is a booking in the registry: honest, and still the right bookkeeping
for a fleet you provision by hand.
"""
import json
import shlex
import subprocess
import time

from . import tenancy

# The deck's weights. A tenant's class says what it costs to carry, and
# capacity is the sum — 25 units to a 4 GB node.
CLASSES = {
    "micro":     {"units": 1,  "note": "1 location · ≤5 seats"},
    "growing":   {"units": 4,  "note": "≤3 locations · ≤20 seats"},
    "large":     {"units": 16, "note": "≤10 locations · ≤75 seats"},
    "dedicated": {"units": 0,  "note": "a node to itself"},
}
DEFAULT_CLASS = "growing"
DEFAULT_UNITS = 25          # a 4 GB node
LOCAL = "local"             # the machine this process is running on


def _reg():
    return tenancy.registry() or {}


def _save(reg) -> None:
    tenancy.REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
    tenancy.bust_cache()


def units_of(t: dict) -> int:
    if t.get("class") == "dedicated":
        return DEFAULT_UNITS
    return CLASSES.get(t.get("class") or DEFAULT_CLASS, {}).get("units", 1)


def nodes() -> dict:
    """Every node, with the local one always present — it is where the
    install runs, whether or not anybody wrote it down."""
    reg = _reg()
    out = dict(reg.get("nodes") or {})
    out.setdefault(LOCAL, {"provider": "local", "size": "this machine",
                           "region": "", "units": DEFAULT_UNITS,
                           "created": 0})
    return out


def fleet() -> list:
    """Nodes with their tenants and capacity — the whole board, in the
    shape the UI draws."""
    reg = _reg()
    tenants = reg.get("tenants") or {}
    prov = reg.get("provider")
    out = []
    for nid, n in nodes().items():
        on = []
        for tid, t in tenants.items():
            if (t.get("node") or LOCAL) != nid:
                continue
            on.append({"id": tid, "class": t.get("class") or DEFAULT_CLASS,
                       "units": units_of(t),
                       "status": t.get("status") or "active",
                       "hosts": t.get("hosts") or [],
                       "provider": tid == prov,
                       "created": t.get("created") or 0})
        used = sum(t["units"] for t in on)
        cap = int(n.get("units") or DEFAULT_UNITS)
        out.append({**n, "id": nid, "tenants": sorted(
            on, key=lambda t: (not t["provider"], t["id"])),
            "used": used, "capacity": cap, "free": max(0, cap - used),
            "carries_provider": any(t["provider"] for t in on),
            "destroyable": nid != LOCAL and not on})
    return sorted(out, key=lambda n: (n["id"] != LOCAL, n["id"]))


def _run(cmd_tmpl: str, **kw) -> str:
    """A provisioning hook. Fails loudly: a node the operator believes was
    created, that wasn't, is worse than an error at the button."""
    if not cmd_tmpl:
        return ""
    cmd = cmd_tmpl.format(**{k: shlex.quote(str(v)) for k, v in kw.items()})
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "command failed")[:400])
    return (r.stdout or "").strip()[:400]


def _cfg():
    from .main import CFG
    with tenancy.run_as(tenancy.provider()):
        return dict(CFG.get("fleet") or {})


def log(what: str, detail: str = "", actor: str = "system") -> None:
    """Fleet history, in the provider's own database — the one place an
    operator can ask 'when did that node go, and who took it?'"""
    prov = tenancy.provider()
    if not prov:
        return
    from . import db
    with tenancy.run_as(prov):
        con = db.connect()
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS fleet_events ("
                " id INTEGER PRIMARY KEY, at REAL NOT NULL,"
                " actor TEXT DEFAULT '', what TEXT NOT NULL,"
                " detail TEXT DEFAULT '')")
            con.execute("INSERT INTO fleet_events(at,actor,what,detail)"
                        " VALUES(?,?,?,?)",
                        (time.time(), actor[:80], what[:120], detail[:400]))
            con.commit()
        finally:
            con.close()


def events(limit: int = 40) -> list:
    prov = tenancy.provider()
    if not prov:
        return []
    from . import db
    with tenancy.run_as(prov):
        con = db.connect()
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS fleet_events ("
                " id INTEGER PRIMARY KEY, at REAL NOT NULL,"
                " actor TEXT DEFAULT '', what TEXT NOT NULL,"
                " detail TEXT DEFAULT '')")
            return [dict(r) for r in con.execute(
                "SELECT at, actor, what, detail FROM fleet_events"
                " ORDER BY id DESC LIMIT ?", (limit,))]
        finally:
            con.close()


def provision(node_id: str, size: str = "4gb", region: str = "",
              provider: str = "", units: int = DEFAULT_UNITS,
              actor: str = "") -> dict:
    """Spin up a node. Runs the configured command when there is one, and
    records the booking either way."""
    node_id = (node_id or "").strip()
    if not node_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("node id: letters, digits, - and _ only")
    reg = _reg()
    if node_id in (reg.get("nodes") or {}) or node_id == LOCAL:
        raise ValueError(f"node '{node_id}' already exists")
    out = _run(_cfg().get("provision_cmd", ""), node=node_id, size=size,
               region=region)
    reg.setdefault("nodes", {})[node_id] = {
        "provider": provider or _cfg().get("provider", "manual"),
        "size": size, "region": region, "units": int(units),
        "created": time.time()}
    _save(reg)
    log("node provisioned", f"{node_id} · {size}"
        + (f" · {region}" if region else "") + (f" · {out}" if out else ""),
        actor or "operator")
    return reg["nodes"][node_id]


def destroy(node_id: str, actor: str = "", auto: bool = False) -> None:
    """Hand a node back. Refuses while anything lives on it — the check is
    here rather than in the UI, because the UI is not the only caller."""
    if node_id == LOCAL:
        raise ValueError("the local node is this machine — it cannot be "
                         "destroyed from inside itself")
    board = {n["id"]: n for n in fleet()}
    n = board.get(node_id)
    if n is None:
        raise ValueError(f"no node '{node_id}'")
    if n["tenants"]:
        raise ValueError(
            f"{len(n['tenants'])} tenant(s) still on '{node_id}' — move or "
            f"shut them down first")
    _run(_cfg().get("destroy_cmd", ""), node=node_id, size=n.get("size", ""),
         region=n.get("region", ""))
    reg = _reg()
    (reg.get("nodes") or {}).pop(node_id, None)
    _save(reg)
    log("node destroyed" + (" (empty)" if auto else ""), node_id,
        actor or ("auto" if auto else "operator"))


def reap(actor: str = "") -> list:
    """Destroy every node nothing lives on. Called after a tenant leaves —
    an empty node is pure cost, and the minute it empties is the only
    minute anyone would think to look."""
    gone = []
    for n in fleet():
        if n["destroyable"]:
            try:
                destroy(n["id"], actor=actor, auto=True)
                gone.append(n["id"])
            except Exception:
                pass          # a driver refusing must not block the rest
    return gone


def pick_node(units: int, prefer: str = "") -> str:
    """Where a new tenant goes. Named node if it fits; otherwise the
    fullest node that still has room — bin-packing, because the bill is
    per node, not per unit."""
    board = {n["id"]: n for n in fleet()}
    if prefer and prefer != "new":
        n = board.get(prefer)
        if n is None:
            raise ValueError(f"no node '{prefer}'")
        if n["free"] < units:
            raise ValueError(f"'{prefer}' has {n['free']} units free, "
                             f"this client needs {units}")
        return prefer
    fits = [n for n in board.values() if n["free"] >= units]
    if not fits:
        raise ValueError("no node has room — provision one first")
    return sorted(fits, key=lambda n: (n["free"], n["id"]))[0]["id"]


def place(tid: str, node: str, klass: str = DEFAULT_CLASS,
          actor: str = "") -> None:
    reg = _reg()
    t = (reg.get("tenants") or {}).get(tid)
    if t is None:
        raise ValueError(f"no tenant '{tid}'")
    was = t.get("node") or LOCAL
    t["node"] = node
    t["class"] = klass
    _save(reg)
    if was != node:
        log("tenant moved", f"{tid}: {was} → {node}", actor or "operator")
        reap(actor)


def release(tid: str, actor: str = "") -> list:
    """A tenant leaves the fleet. Returns the nodes that went with it."""
    reg = _reg()
    t = (reg.get("tenants") or {}).pop(tid, None)
    _save(reg)
    if t is not None:
        log("tenant removed", f"{tid} (was on {t.get('node') or LOCAL})",
            actor or "operator")
    return reap(actor)
