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
import io
import json
import shlex
import subprocess
import tarfile
import time
from pathlib import Path

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
                       "caps": len(t.get("caps") or []) or None,
                       "cap_ids": t.get("caps") or [],
                       "status": t.get("status") or "active",
                       "hosts": t.get("hosts") or [],
                       "provider": tid == prov,
                       "created": t.get("created") or 0})
        used = sum(t["units"] for t in on)
        cap = int(n.get("units") or DEFAULT_UNITS)
        n = {k: v for k, v in n.items() if k != "key"}   # never ship keys to UIs
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


def node_addr(node_id: str) -> str:
    """Where a node's process listens, or "" for bookkeeping-only nodes.
    An addr is what turns a booking into a machine: with one, tenants are
    actually SHIPPED there and served from it."""
    n = nodes().get(node_id) or {}
    return (n.get("addr") or "").rstrip("/")


def node_key(node_id: str) -> str:
    n = nodes().get(node_id) or {}
    return n.get("key") or ""


def _node_call(node_id: str, method: str, path: str, content=None,
               timeout: float = 120.0):
    """One authenticated call to a worker node's process. Raises with the
    node's own words on failure — a shipment that half-happened must say
    so loudly."""
    import httpx
    addr = node_addr(node_id)
    if not addr:
        raise RuntimeError(f"node '{node_id}' has no address — it is a "
                           f"booking, not a machine")
    r = httpx.request(method, addr + path,
                      headers={"X-Fleet-Key": node_key(node_id)},
                      content=content, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"node '{node_id}' refused {path}: "
                           f"{r.text[:200]}")
    return r


# ---------- the app as cargo: bundles, versions, updates ----------
# A worker runs the same code as the provider, and this is how it gets it:
# the provider zips its own working tree (src, scripts, docs, requirements)
# stamped with a VERSION derived from the content, a fresh node fetches the
# bundle at install, and an update ships the same bundle to a running node
# — which applies it and exits, letting systemd bring it back on the new
# code. One artifact for both roads, so "what the installer got" and "what
# the update pushed" can never be different things.

BUNDLE_DIRS = ("src", "scripts", "docs")
BUNDLE_FILES = ("requirements.txt",)
_BUNDLE_SKIP = ("__pycache__", ".DS_Store")
# The kit's clients/ folder is per-client WORKING PAPERS — an operator's
# drafts and records, not app code — and it never leaves the provider.
_BUNDLE_SKIP_PREFIXES = ("docs/business-control-b2b-client/clients/",)


def _app_root():
    from . import config
    return config.APP_ROOT


def app_version() -> str:
    """What this process is running. A bundle carries a VERSION file; a
    working tree does not, and says so."""
    try:
        return (_app_root() / "VERSION").read_text().strip() or "dev"
    except OSError:
        return "dev"


def build_bundle() -> tuple[bytes, str]:
    """The app as one zip, and its version — a short hash of the content,
    so two builds of the same tree agree and any edit changes the name."""
    import hashlib
    import io
    import zipfile
    root = _app_root()
    members = []
    for d in BUNDLE_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_dir():
                continue
            rel = str(p.relative_to(root))
            if (rel.endswith(".pyc")
                    or any(s in rel.split("/") for s in _BUNDLE_SKIP)
                    or rel.startswith(_BUNDLE_SKIP_PREFIXES)):
                continue
            members.append((rel, p.read_bytes()))
    for f in BUNDLE_FILES:
        p = root / f
        if p.is_file():
            members.append((f, p.read_bytes()))
    h = hashlib.sha256()
    for rel, data in members:
        h.update(rel.encode())
        h.update(data)
    version = h.hexdigest()[:12]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, data in members:
            z.writestr(rel, data)
        z.writestr("VERSION", version)
    return buf.getvalue(), version


def apply_bundle(blob: bytes, target) -> str:
    """Unpack a bundle over the app directory. Every member must resolve
    INSIDE the target — a zip that names '..' or an absolute path is an
    attack, not an update. Data is untouched: bundles never carry it."""
    import io
    import zipfile
    from pathlib import Path as _P
    target = _P(target).resolve()
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise ValueError("that is not a bundle")
    names = z.namelist()
    if "VERSION" not in names:
        raise ValueError("bundle carries no VERSION — refused")
    for name in names:
        dest = (target / name).resolve()
        if not str(dest).startswith(str(target) + "/"):
            raise ValueError(f"bundle names a path outside the app: {name}")
        if name.split("/", 1)[0] == "data":
            raise ValueError("a bundle must never carry data/")
    for name in names:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(z.read(name))
    return z.read("VERSION").decode().strip()


def check_node(node_id: str) -> dict:
    """One live look at a worker: is it up, what code, what services, how
    many tenants."""
    p = _node_call(node_id, "GET", "/api/node/ping", timeout=6).json()
    return {"ok": True, "node": p.get("node"),
            "version": p.get("version", "unknown"),
            "services": p.get("services") or {},
            "tenants": len(p.get("tenants") or {})}


def update_node(node_id: str, actor: str = "") -> dict:
    """Ship this box's code to a worker and wait for it to come back
    wearing it. The worker applies the bundle, answers, and exits —
    systemd restarts it on the new code — so success is observed, not
    assumed: we poll until the ping reports the pushed version."""
    blob, version = build_bundle()
    before = check_node(node_id)
    if before["version"] == version:
        return {**before, "updated": False,
            "note": "already on this version"}
    _node_call(node_id, "POST", "/api/node/update", content=blob,
               timeout=300)
    for _ in range(30):
        time.sleep(2)
        try:
            now = check_node(node_id)
            if now["version"] == version:
                log("node updated",
                    f"{node_id} · {before['version']} -> {version}",
                    actor or "operator")
                return {**now, "updated": True, "from": before["version"]}
        except Exception:
            continue                       # mid-restart: keep waiting
    raise RuntimeError(
        f"node '{node_id}' took the bundle but never reported version "
        f"{version} — check its service logs before pushing again")


def install_script() -> str:
    """The node installer, from disk — it ships in the repo (and in every
    bundle), so the script a fresh machine curls is the script the tree
    versions."""
    p = _app_root() / "scripts" / "install_node.sh"
    return p.read_text(encoding="utf-8")


def pack_tenant(tid: str) -> bytes:
    """A tenant's whole directory as one tar.gz — database, config,
    uploads, push keys. The unit of shipment, and of backup.

    The database goes in as a WAL-safe SNAPSHOT (sqlite's backup API),
    not the live file: taring a database mid-write ships torn pages, and
    a shipment is exactly when the tenant may still be serving. The
    snapshot is self-contained, so the -wal/-shm siblings stay out."""
    import sqlite3
    import tempfile
    from . import tenancy
    d = tenancy.tenant_dir(tid)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        with tempfile.TemporaryDirectory() as td:
            for p in sorted(d.rglob("*")):
                rel = p.relative_to(d)
                name = str(rel)
                if p.is_dir():
                    tf.add(p, arcname=f"./{name}", recursive=False)
                    continue
                if not p.is_file():
                    continue
                if p.suffix == ".db":
                    snap = Path(td) / name.replace("/", "_")
                    src = sqlite3.connect(p)
                    dst = sqlite3.connect(snap)
                    src.backup(dst)
                    dst.close()
                    src.close()
                    tf.add(snap, arcname=f"./{name}")
                elif p.name.endswith((".db-wal", ".db-shm")):
                    continue          # folded into the snapshot above
                else:
                    tf.add(p, arcname=f"./{name}")
    return buf.getvalue()


def unpack_tenant(tid: str, blob: bytes) -> None:
    """The receiving side. Members are screened — a tar that tries to
    write outside the tenant's own directory is an attack, not a
    shipment."""
    from . import tenancy
    d = tenancy.tenant_dir(tid)
    d.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            name = m.name.lstrip("./")
            if m.name.startswith("/") or ".." in m.name.split("/"):
                raise ValueError(f"unsafe path in shipment: {m.name}")
            if not (m.isfile() or m.isdir()):
                continue
        tf.extractall(d, filter="data")


def _tenant_entry(tid: str) -> dict:
    from . import tenancy
    return (tenancy.registry() or {}).get("tenants", {}).get(tid, {})


def ship_tenant(tid: str, node_id: str, actor: str = "") -> None:
    """Move a tenant's data TO its booked node and hand serving over.

    Order is the whole safety story: the data lands and is acknowledged,
    the node learns the tenant (registry slice), and only THEN does the
    local copy go — a failure anywhere earlier leaves the tenant served
    from here exactly as before, and says so.
    """
    import shutil
    from . import tenancy
    _node_call(node_id, "POST", f"/api/node/tenants/{tid}/import",
               content=pack_tenant(tid))
    _node_call(node_id, "POST", "/api/node/registry", content=json.dumps(
        {"tenants": {tid: {**_tenant_entry(tid), "node": node_id}}}))
    shutil.rmtree(tenancy.tenant_dir(tid), ignore_errors=True)
    log("tenant shipped", f"{tid} → {node_id}", actor or "operator")


def recall_tenant(tid: str, node_id: str, actor: str = "") -> None:
    """Bring a tenant's data BACK from its node — the reverse shipment,
    with the same order of operations: fetched, unpacked, verified here,
    and only then removed there."""
    r = _node_call(node_id, "GET", f"/api/node/tenants/{tid}/export",
                   timeout=300.0)
    unpack_tenant(tid, r.content)
    from . import tenancy
    if not (tenancy.tenant_dir(tid) / "business_control.db").exists():
        raise RuntimeError(f"recall of '{tid}' unpacked no database — "
                           f"the node's copy is untouched")
    _node_call(node_id, "DELETE", f"/api/node/tenants/{tid}")
    log("tenant recalled", f"{tid} ← {node_id}", actor or "operator")


def set_status_pushed(tid: str) -> None:
    """After a suspend/resume: the tenant's own node must honour it."""
    push_entry(tid)


def push_entry(tid: str) -> None:
    """Keep a remote tenant's node current on status/caps/hosts — called
    after any registry change that a worker must honour (suspension, a
    launch's new hostname, a refreshed grant)."""
    from . import tenancy
    nid = tenancy.node_of(tid)
    if node_addr(nid):
        try:
            _node_call(nid, "POST", "/api/node/registry", content=json.dumps(
                {"tenants": {tid: {**_tenant_entry(tid), "node": nid}}}))
        except Exception as e:
            log("registry push failed",
                f"{tid} → {nid}: {e}"[:380], "system")


def provision(node_id: str, size: str = "4gb", region: str = "",
              provider: str = "", units: int = DEFAULT_UNITS,
              actor: str = "", addr: str = "") -> dict:
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
    import secrets as _secrets
    reg.setdefault("nodes", {})[node_id] = {
        "provider": provider or _cfg().get("provider", "manual"),
        "size": size, "region": region, "units": int(units),
        "created": time.time(),
        # an addr turns the booking into a machine; the key is what the
        # provider presents on every shipment to it
        "addr": (addr or "").rstrip("/"),
        "key": _secrets.token_urlsafe(24) if addr else ""}
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
    """Destroy every empty node the reap can actually TEAR DOWN. Called
    after a tenant leaves — an empty node is pure cost, and the minute it
    empties is the only minute anyone would think to look.

    The refinement a live machine forced: an addr'd node with no
    destroy_cmd is a running server we merely know the address of.
    Auto-destroying its record doesn't stop the bill — it loses the
    address and the key while the machine runs on. Those stay on the
    board, flagged empty, until an operator destroys them deliberately
    (or a destroy_cmd exists to really tear them down)."""
    teardown = bool(_cfg().get("destroy_cmd"))
    gone = []
    for n in fleet():
        if n["destroyable"] and (teardown or not n.get("addr")):
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


def park_local(tid: str) -> None:
    """Point a tenant's booking back at local WITHOUT moving any data —
    for the failure paths where the data never left."""
    reg = _reg()
    t = (reg.get("tenants") or {}).get(tid)
    if t is not None:
        t["node"] = LOCAL
        _save(reg)


def place(tid: str, node: str, klass: str = DEFAULT_CLASS,
          actor: str = "") -> None:
    """Move a tenant between nodes — the DATA moves with the booking.

    A move off an addr'd node recalls the directory here first; a move
    onto one ships it after. Failure order is the design: a recall that
    fails leaves everything where it was; a ship that fails after a
    successful recall parks the tenant on local and says so — served,
    slower, honest — rather than a registry pointing at a machine that
    does not have the data.
    """
    reg = _reg()
    t = (reg.get("tenants") or {}).get(tid)
    if t is None:
        raise ValueError(f"no tenant '{tid}'")
    was = t.get("node") or LOCAL
    if was != node:
        if node_addr(was):
            recall_tenant(tid, was, actor)
        if node_addr(node):
            try:
                # the slice shipped with the data must already say the
                # destination, so update the booking first
                t["node"] = node
                t["class"] = klass
                _save(reg)
                ship_tenant(tid, node, actor)
            except Exception as e:
                t["node"] = LOCAL
                _save(reg)
                log("move failed — parked on local",
                    f"{tid}: {e}"[:300], actor or "operator")
                raise RuntimeError(
                    f"could not ship '{tid}' to {node} — parked on local, "
                    f"still served: {e}")
    t = (_reg().get("tenants") or {}).get(tid)
    reg = _reg()
    reg["tenants"][tid]["node"] = node
    reg["tenants"][tid]["class"] = klass
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
