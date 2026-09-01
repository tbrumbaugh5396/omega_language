"""The fleet's admin surface — peeled whole from engagements.py.

Nodes and the tenants living on them: the board, provisioning, the join
command, check and update, stand-up, status, moves, launches, caps and
act-as. Only the provider answers here; _provider_only (shared with the
studio routes) stays in engagements.py and is imported."""
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from erp.backend import config  # noqa: F401  (fleet_cfg and friends)

router = APIRouter()

from .api import admin_user, get_con  # noqa: E402
from .engagements import (CAP_NAMES, _cap_catalog, _core_price,  # noqa: E402
                          _eng_or_404, _provider_only, file_kit_doc, log,
                          stand_up_suggestion)


# ---------- the fleet: nodes, and the tenants living on them ----------
# Only the provider gets these. A client tenant asking about the fleet is
# asking about other people's businesses, so the gate is the first line of
# every handler rather than a rule written down somewhere.

def fleet_cfg() -> dict:
    """The provider's fleet settings — provision commands, public suffix.

    Read fresh from disk, not through the cached proxy: these are edited
    in config.json by hand, the reads are rare (stand-up, the board), and
    an operator who sets public_suffix should not need a restart for the
    next stand-up to honour it."""
    from erp.backend import config, tenancy
    prov = tenancy.provider()
    try:
        cfg = config.load(tenancy.tenant_dir(prov) / "config.json")
    except Exception:
        return {}
    return dict(cfg.get("fleet") or {})




class NodeBody(BaseModel):
    id: str = ""
    size: str = "4gb"
    region: str = ""
    provider: str = ""
    units: int = 25
    addr: str = ""       # the node process's base URL — booking becomes machine


class TenantBody(BaseModel):
    id: str = ""
    brand: str = ""
    hosts: list = []
    node: str = ""             # "" = pick · "new" = spin one up
    new_node: str = ""         # id for the node being spun up
    node_size: str = "4gb"
    node_region: str = ""
    klass: str = "growing"
    engagement_id: int = 0     # link the client record, if there is one


class StatusBody(BaseModel):
    status: str = "active"


class MoveBody(BaseModel):
    node: str = ""
    klass: str = ""


_BILLING_CACHE = {"at": 0.0, "flags": {}}


def _billing_flags(con) -> dict:
    """Which tenants' linked subscriptions Stripe would not bill today.

    Pulled when the board loads, cached ~5 minutes so opening the Platform
    tab is not a Stripe call per tenant per refresh. Card-billed rows only
    — an invoice-mode plan has no processor to disagree with. The flag is
    for the OPERATOR: suspension stays a human's click, this puts the fact
    beside the button.
    """
    from erp.backend import payments
    from erp.backend.main import CFG
    import time as _t
    if _t.time() - _BILLING_CACHE["at"] < 300:
        return _BILLING_CACHE["flags"]
    flags = {}
    if payments.enabled(CFG):
        rows = con.execute(
            "SELECT s.id, s.tenant_id, s.payment_ref, s.created_at,"
            " p.name plan FROM store_subscriptions s"
            " JOIN products p ON p.id=s.product_id"
            " WHERE s.tenant_id != '' AND s.payment_ref != ''"
            " AND s.status NOT IN ('cancelled','failed')").fetchall()
        for r in rows:
            st = payments.subscription_status(CFG, r["payment_ref"])
            if st and st not in ("active", "trialing"):
                flags[r["tenant_id"]] = {"status": st, "plan": r["plan"],
                                         "sub_id": r["id"]}
                # once per state change, on the fleet's own record
                marker = f"stripe:{st}"
                cur = con.execute(
                    "UPDATE store_subscriptions SET payment_status=?"
                    " WHERE id=? AND payment_status != ?",
                    (marker, r["id"], marker))
                if cur.rowcount:
                    con.commit()
                    fleet_mod_log(r["tenant_id"], r["plan"], st)
    _BILLING_CACHE["at"] = _t.time()
    _BILLING_CACHE["flags"] = flags
    return flags


def fleet_mod_log(tid: str, plan: str, status: str) -> None:
    from erp.backend import fleet
    fleet.log("billing warning",
              f"{tid}: {plan} is {status} at the card processor", "stripe")


def _backup_health() -> dict:
    """Is the nightly promise being kept? Read from what the backup script
    itself wrote — the board reports the record, it does not guess. Stale
    means older than 26 hours: one missed night, with an hour of slack for
    the cron's own clock."""
    from erp.backend import config
    p = config.DATA_DIR / "backups" / "last.json"
    if not p.exists():
        return {"never": True, "stale": True}
    try:
        d = json.loads(p.read_text())
    except ValueError:
        return {"never": True, "stale": True}
    d["stale"] = (time.time() - (d.get("at") or 0)) > 26 * 3600
    return d



@router.get("/api/store/admin/fleet")
def fleet_board(u=Depends(admin_user), con=Depends(get_con)):
    """The whole board: nodes, capacity, who lives where, recent history."""
    _provider_only()
    from erp.backend import fleet
    clients = {}
    for r in con.execute(
            "SELECT id, name, slug, tenant_id, status FROM engagements"):
        key = r["tenant_id"] or r["slug"]
        clients[key] = {"engagement_id": r["id"], "name": r["name"],
                        "status": r["status"]}
    board = fleet.fleet()
    billing = _billing_flags(con)
    for n in board:
        for t in n["tenants"]:
            t["client"] = clients.get(t["id"])
            t["billing"] = billing.get(t["id"])
    from erp.backend import services as _svc
    return {"nodes": board, "classes": fleet.CLASSES,
            # this machine's own shared daemons — worker nodes report
            # theirs through Check, which asks them live
            "services": _svc.summary(),
            "backup": _backup_health(),
            "cap_catalog": _cap_catalog(),
            "core_price": _core_price(),
            "public_suffix": (fleet_cfg() or {}).get("public_suffix", ""),
            "events": fleet.events(20),
            "unplaced": [dict(v, slug=k) for k, v in clients.items()
                         if not any(t["id"] == k for n in board
                                    for t in n["tenants"])
                         and v["status"] != "archived"]}


@router.post("/api/store/admin/fleet/nodes")
def fleet_node_add(body: NodeBody, u=Depends(admin_user),
                   con=Depends(get_con)):
    _provider_only()
    from erp.backend import fleet
    try:
        n = fleet.provision(body.id, size=body.size, region=body.region,
                            provider=body.provider,
                            units=body.units or fleet.DEFAULT_UNITS,
                            actor=u["name"],
                        addr=body.addr)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "node": {**n, "id": body.id}}


@router.delete("/api/store/admin/fleet/nodes/{node_id}")
def fleet_node_destroy(node_id: str, u=Depends(admin_user),
                       con=Depends(get_con)):
    _provider_only()
    from erp.backend import fleet
    try:
        fleet.destroy(node_id, actor=u["name"])
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.get("/api/store/admin/fleet/nodes/{node_id}/join")
def fleet_node_join(node_id: str, request: Request, u=Depends(admin_user),
                    con=Depends(get_con)):
    """The one command that turns the booked machine into a worker: run it
    on the fresh box and it fetches the bundle, stands up systemd with the
    node's identity, and proves it answers. The key travels only in this
    command — copied by the operator, never in the script itself."""
    _provider_only()
    from erp.backend import fleet
    from erp.backend.main import CFG
    key = fleet.node_key(node_id)
    if node_id not in fleet.nodes():
        raise HTTPException(404, "no such node")
    if not key:
        raise HTTPException(409, "this node has no key — give it an "
                                 "address first (a key is minted with it)")
    base = (CFG.get("public_base_url") or "").rstrip("/") \
        or str(request.base_url).rstrip("/")
    return {"command":
            f"curl -fsSL {base}/fleet/install.sh -o /tmp/bc-install.sh"
            f" && sudo bash /tmp/bc-install.sh --node {node_id}"
            f" --key {key} --provider {base}",
            "note": "run on the fresh machine as root; then Check the "
                    "node here"}


@router.get("/api/store/admin/fleet/nodes/{node_id}/check")
def fleet_node_check(node_id: str, u=Depends(admin_user),
                     con=Depends(get_con)):
    _provider_only()
    from erp.backend import fleet
    try:
        out = fleet.check_node(node_id)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(502, str(e))
    return {**out, "current": fleet.build_bundle()[1]}


@router.post("/api/store/admin/fleet/nodes/{node_id}/update")
def fleet_node_update(node_id: str, u=Depends(admin_user),
                      con=Depends(get_con)):
    """Push this box's code to the worker and wait until the worker's
    ping answers with the pushed version — success observed, not
    assumed."""
    _provider_only()
    from erp.backend import fleet
    try:
        return fleet.update_node(node_id, actor=u["name"])
    except (ValueError, RuntimeError) as e:
        raise HTTPException(502, str(e))


@router.post("/api/store/admin/fleet/tenants")
def fleet_tenant_add(body: TenantBody, request: Request,
                     u=Depends(admin_user), con=Depends(get_con)):
    """Stand a client up: a node to live on (existing or new), a tenant
    with its own database and secrets, and the hostname it answers to."""
    _provider_only()
    from erp.backend import fleet, tenancy
    tid = (body.id or "").strip().lower()
    if not tid:
        raise HTTPException(400, "a tenant id is required")
    if tid in (tenancy.registry() or {}).get("tenants", {}):
        raise HTTPException(400, f"'{tid}' already exists")
    # A hostname needs a name in front of the dot. ".localhost" is a typo:
    # dropped, not repaired — stripping the dot would hand this tenant
    # "localhost" itself, which is somebody else's front door.
    hosts = [h for h in (h.strip().lower() for h in body.hosts)
             if h and h.split(".")[0]]
    if not hosts:
        hosts = [f"{tid}.localhost"]
    # The public door, granted at birth: with fleet.public_suffix set (a
    # wildcard-DNS'd domain like clients.example.com), every stand-up also
    # answers at <tenant>.<suffix> — so the form's output is a URL you can
    # SEND someone. Appended AFTER the local fallback is settled: the
    # public name must never crowd out the .localhost door.
    suffix = (fleet_cfg() or {}).get("public_suffix", "").strip(". ").lower()
    public_host = f"{tid}.{suffix}" if suffix else ""
    if public_host and public_host not in hosts:
        hosts.append(public_host)
    taken = {h.lower(): t for t, cfg in
             (tenancy.registry() or {}).get("tenants", {}).items()
             for h in cfg.get("hosts", [])}
    for h in hosts:
        if taken.get(h, tid) != tid:
            raise HTTPException(400, f"'{h}' already answers for "
                                     f"{taken[h]} — one name, one business")
    klass = body.klass if body.klass in fleet.CLASSES else "growing"
    units = fleet.units_of({"class": klass})
    try:
        if body.node == "new":
            nid = (body.new_node or f"node-{tid}").strip()
            fleet.provision(nid, size=body.node_size,
                            region=body.node_region, actor=u["name"])
        else:
            nid = fleet.pick_node(units, prefer=body.node)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    # The quote's capability set becomes the tenant's entitlement — the
    # same list that sizes the node and shapes the home page also records
    # what was sold, so the ops app can say which tabs are theirs.
    sug0 = (stand_up_suggestion(con, body.engagement_id)
            if body.engagement_id else None)
    tenancy.create(tid, hosts=hosts, node=nid,
                   klass=klass, brand=body.brand or tid.title(),
                   caps=(sug0 or {}).get("cap_ids"))
    fleet.log("tenant created", f"{tid} on {nid} ({klass})", u["name"])
    if public_host:
        with tenancy.run_as(tid):
            from erp.backend import config as _config
            from erp.backend.main import CFG as _tcfg
            _tcfg["public_base_url"] = f"https://{public_host}"
            _config.save(_tcfg)
    hosting_doc = 0
    layout = ""
    if body.engagement_id:
        # The quote knows what the business IS — its capability set — so
        # the new tenant's home page opens shaped like the business, not
        # like the generic shop. Only at stand-up, onto a page nobody has
        # touched; and never a reason the stand-up fails.
        sug = sug0
        if sug and sug.get("cap_ids"):
            from erp.backend import db as _db
            from .layouts import apply as apply_layout
            try:
                with tenancy.run_as(tid):
                    tcon = _db.connect()
                    try:
                        layout = apply_layout(tcon, sug["cap_ids"],
                                              body.brand or tid.title())
                    finally:
                        tcon.close()
                fleet.log("starter layout", f"{tid}: {layout} "
                          f"({len(sug['cap_ids'])} capabilities)",
                          u["name"])
            except Exception:
                layout = ""
    if not layout:
        # No quote, no capabilities, no shape to derive — the honest page,
        # not the factory default that used to put another business's film
        # on a fresh install's front door.
        try:
            with tenancy.run_as(tid):
                from erp.backend import db as _db2
                from .layouts import apply_placeholder
                pcon = _db2.connect()
                try:
                    apply_placeholder(pcon, body.brand or tid.title())
                finally:
                    pcon.close()
            layout = "placeholder"
        except Exception:
            pass
    if body.engagement_id:
        con.execute("UPDATE engagements SET tenant_id=? WHERE id=?",
                    (tid, body.engagement_id))
        log(con, body.engagement_id, u["name"],
            f"stood up as tenant '{tid}' on node {nid}")
        con.commit()
        # The act writes its own paper. Standing infrastructure up under a
        # client's engagement files the hosting & infrastructure schedule
        # into it, pre-filled with what was actually stood up — so the
        # authority to run their business on our platform is a signed page
        # in their binder, not an understanding. If the schedule was
        # already filed (a re-stand-up after a move), it is not duplicated.
        e = con.execute("SELECT * FROM engagements WHERE id=?",
                        (body.engagement_id,)).fetchone()
        rel = "04-agreement/contracts/hosting-and-infrastructure.md"
        already = con.execute(
            "SELECT 1 FROM engagement_docs ed JOIN documents d"
            " ON d.id=ed.doc_id WHERE ed.engagement_id=? AND d.notes LIKE ?",
            (body.engagement_id, f"%{rel}%")).fetchone()
        if e is not None and not already:
            try:
                hosting_doc, _, _ = file_kit_doc(
                    con, e, rel,
                    fills={"TENANT ID": tid,
                           "HOSTNAMES": ", ".join(hosts
                                                  or [f"{tid}.localhost"]),
                           "NODE CLASS": klass,
                           "CLIENT LEGAL NAME": e["name"]},
                    actor=u["name"], actor_id=u["id"])
            except Exception:
                # a stand-up must not fail for want of its paperwork —
                # the operator can still generate the schedule by hand
                hosting_doc = 0
    shipped = ""
    if fleet.node_addr(nid):
        # Everything local is written — schema, layout, hosting paper —
        # so the shipment carries the finished install. A ship that fails
        # parks the tenant on local, served and honest, never a registry
        # pointing at a machine without the data.
        try:
            fleet.ship_tenant(tid, nid, u["name"])
            shipped = nid
        except Exception as e:
            fleet.park_local(tid)
            fleet.log("stand-up ship failed — parked on local",
                      f"{tid}: {e}"[:300], u["name"])
            nid = "local"
    return {"ok": True, "tenant": tid, "node": nid, "shipped": shipped,
            "hosting_doc": hosting_doc, "layout": layout,
            "public_url": f"https://{public_host}" if public_host else ""}


@router.post("/api/store/admin/fleet/tenants/{tid}/status")
def fleet_tenant_status(tid: str, body: StatusBody, u=Depends(admin_user),
                        con=Depends(get_con)):
    """Shut a client down without losing a byte, or wake it back up."""
    _provider_only()
    from erp.backend import fleet, tenancy
    if tid == tenancy.provider():
        raise HTTPException(400, "the provider cannot suspend itself")
    try:
        tenancy.set_status(tid, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    fleet.set_status_pushed(tid)
    fleet.log(f"tenant {body.status}", tid, u["name"])
    return {"ok": True, "status": body.status}


@router.post("/api/store/admin/fleet/tenants/{tid}/move")
def fleet_tenant_move(tid: str, body: MoveBody, u=Depends(admin_user),
                      con=Depends(get_con)):
    """Move a tenant to another node — and reap whatever it left empty."""
    _provider_only()
    from erp.backend import fleet, tenancy
    reg = tenancy.registry() or {}
    t = (reg.get("tenants") or {}).get(tid)
    if t is None:
        raise HTTPException(404, "no such tenant")
    klass = body.klass or t.get("class") or "growing"
    units = fleet.units_of({"class": klass})
    try:
        nid = (fleet.pick_node(units, prefer=body.node) if body.node != "new"
               else fleet.provision(f"node-{tid}", actor=u["name"]) and
               f"node-{tid}")
        fleet.place(tid, nid, klass=klass, actor=u["name"])
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "node": nid}


@router.delete("/api/store/admin/fleet/tenants/{tid}")
def fleet_tenant_remove(tid: str, keep_data: int = 1,
                        u=Depends(admin_user), con=Depends(get_con)):
    """Remove a client from the fleet. Their directory is retired rather
    than deleted unless asked otherwise, and any node they were the last
    one on is destroyed with them."""
    _provider_only()
    from erp.backend import tenancy
    try:
        out = tenancy.destroy(tid, keep_data=bool(keep_data),
                              actor=u["name"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    # The engagement stops pointing at an install that no longer exists —
    # a dangling tenant_id left the client page offering Launch for
    # nothing, and hid the Stand up chip that could fix it.
    con.execute("UPDATE engagements SET tenant_id='' WHERE tenant_id=?",
                (tid,))
    con.commit()
    return {"ok": True, **out}


class LaunchBody(BaseModel):
    url: str


@router.post("/api/store/admin/engagements/{eid}/launch")
def launch_site(eid: int, body: LaunchBody, u=Depends(admin_user),
                con=Depends(get_con)):
    """Put the client's install on its real address, with the capabilities
    that were sold.

    One act, four writes, all derived from things already agreed: the
    hostname joins the tenant's registry row (merged — the .localhost door
    stays), public_base_url lands in their config so QR codes, sign-in
    links and Stripe returns carry the right domain, the capability grant
    refreshes from the signed quote, and the engagement records the URL.
    DNS and the reverse proxy stay the operator's job — this makes the
    platform answer when the name arrives, it does not buy the name.
    """
    _provider_only()
    from urllib.parse import urlparse
    from erp.backend import fleet, tenancy
    e = _eng_or_404(con, eid)
    tid = e["tenant_id"]
    if not tid or tid not in tenancy.all_tenants():
        raise HTTPException(400, "no install to launch — stand them up "
                                 "first")
    raw = (body.url or "").strip()
    if raw and "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not host or "." not in host:
        raise HTTPException(400, "a launch needs a real hostname, like "
                                 "shop.example.com")
    taken = {h.lower(): t for t, cfg in
             (tenancy.registry() or {}).get("tenants", {}).items()
             for h in cfg.get("hosts", [])}
    if taken.get(host, tid) != tid:
        raise HTTPException(400, f"'{host}' already answers for "
                                 f"{taken[host]} — one name, one business")
    url = f"{parsed.scheme}://{host}" + (f":{parsed.port}"
                                         if parsed.port else "")
    hosts = tenancy.add_hosts(tid, [host])
    with tenancy.run_as(tid):
        from erp.backend import config as _config
        from erp.backend.main import CFG as _tcfg
        _tcfg["public_base_url"] = url
        _config.save(_tcfg)
    sug = stand_up_suggestion(con, eid)
    caps = sorted(set((sug or {}).get("cap_ids") or []))
    if caps:
        tenancy.set_caps(tid, caps)
    con.execute("UPDATE engagements SET live_url=? WHERE id=?", (url, eid))
    log(con, eid, u["name"],
        f"launched at {url}" + (f" with {len(caps)} capabilities from the "
                                f"signed quote" if caps else ""))
    con.commit()
    fleet.push_entry(tid)      # the tenant's node learns the new name
    fleet.log("site launched", f"{tid} → {url}"
              + (f" · {len(caps)} caps" if caps else ""), u["name"])
    return {"ok": True, "url": url, "hosts": hosts, "caps": caps}


class GrantBody(BaseModel):
    caps: list[str] = []
    clear: bool = False              # back to "no grant recorded" = all on
    extend_site: bool = True


@router.post("/api/store/admin/fleet/tenants/{tid}/caps")
def set_tenant_caps(tid: str, body: GrantBody, u=Depends(admin_user),
                    con=Depends(get_con)):
    """Change what a tenant is entitled to — the button that FULFILS a
    capability ask, and the moment the site should grow the piece that
    sells the new capability.

    Growth is additive only: newly granted capabilities earn their add-on
    sections and the shape's missing pages, and nothing an operator built
    is rewritten. The tenant's node hears about it, and their ops app's
    locked tabs open on the next load."""
    _provider_only()
    from erp.backend import db as _db, fleet, tenancy
    if tid not in tenancy.all_tenants():
        raise HTTPException(404, f"no tenant '{tid}'")
    if body.clear:
        reg = tenancy.registry() or {}
        (reg.get("tenants") or {}).get(tid, {}).pop("caps", None)
        tenancy.REGISTRY_PATH.write_text(json.dumps(reg, indent=2))
        tenancy.bust_cache()
        fleet.push_entry(tid)
        fleet.log("grant cleared", f"{tid}: everything on", u["name"])
        return {"ok": True, "caps": None, "grown": {}}
    caps = sorted({c for c in body.caps if c in CAP_NAMES})
    if not caps:
        raise HTTPException(400, "an empty grant is ambiguous — pick "
                                 "capabilities, or clear the grant to "
                                 "mean everything")
    before = set(tenancy.caps_of(tid) or [])
    tenancy.set_caps(tid, caps)
    fleet.push_entry(tid)
    added = sorted(set(caps) - before) if before else []
    removed = sorted(before - set(caps)) if before else []
    grown, trimmed = {}, {}
    if body.extend_site and (added or removed) and not fleet.node_addr(
            tenancy.node_of(tid)):
        from .layouts import extend_for_caps, trim_for_caps
        try:
            with tenancy.run_as(tid):
                tcon = _db.connect()
                try:
                    if added:
                        grown = extend_for_caps(tcon, added, caps)
                    if removed:
                        # growth's mirror: revoked capabilities take back
                        # their scaffolding — but never an edited section
                        trimmed = trim_for_caps(tcon, removed)
                finally:
                    tcon.close()
        except Exception:
            grown, trimmed = {}, {}
    fleet.log("grant changed",
              f"{tid}: {len(caps)} capabilities"
              + (f" (+{', '.join(added)})" if added else ""), u["name"])
    e = con.execute("SELECT id FROM engagements WHERE tenant_id=? AND"
                    " status != 'archived' LIMIT 1", (tid,)).fetchone()
    if e:
        log(con, e["id"], u["name"],
            f"capability grant now: {', '.join(caps)}")
        con.commit()
    return {"ok": True, "caps": caps, "added": added, "removed": removed,
            "grown": grown, "trimmed": trimmed.get("trimmed", []),
            "hidden": trimmed.get("hidden", [])}


@router.post("/api/store/admin/fleet/tenants/{tid}/act-as")
def act_as_tenant_admin(tid: str, request: Request, u=Depends(admin_user),
                        con=Depends(get_con)):
    """One click from the Platform tab into a client tenant's ops app, as
    an admin of THAT install.

    The wall stays a wall: no shared session, no key exchange — the
    provider's operator gets a named account ("Studio · <operator>")
    minted in the TENANT'S own user directory with a fresh token, and the
    act is written down on both sides: the fleet history and, when the
    client has an engagement, their file. Repeat uses REUSE the account's
    token so the operator's open session survives another click; revoking
    access is deactivating the account in the tenant's Team & access, not
    racing tokens."""
    _provider_only()
    import secrets as _secrets
    from erp.backend import db as _db, fleet, tenancy
    if tid not in tenancy.all_tenants():
        raise HTTPException(404, f"no tenant '{tid}'")
    if tid == tenancy.provider():
        raise HTTPException(400, "you are already the provider's admin")
    if fleet.node_addr(tenancy.node_of(tid)):
        raise HTTPException(400, "this tenant lives on a worker node — "
                                 "sign in on its own host directly")
    acct = f"Studio · {u['name']}"[:60]
    with tenancy.run_as(tid):
        tcon = _db.connect()
        try:
            row = tcon.execute(
                "SELECT id, token FROM users WHERE name=?",
                (acct,)).fetchone()
            if row and row["token"]:
                # Reuse, don't rotate: rotating on every click signed the
                # operator's OPEN session out the moment anyone (including
                # a second tab) acted again. The account is the security
                # boundary — revoke it in the tenant's Team & access, not
                # by racing tokens.
                token = row["token"]
                tcon.execute("UPDATE users SET is_admin=1, active=1,"
                             " role='owner' WHERE id=?", (row["id"],))
            else:
                token = _secrets.token_urlsafe(24)
                if row:
                    tcon.execute("UPDATE users SET token=?, is_admin=1,"
                                 " active=1, role='owner' WHERE id=?",
                                 (token, row["id"]))
                else:
                    tcon.execute(
                        "INSERT INTO users(name, role, token, region,"
                        " is_admin, password_hash, created_at)"
                        " VALUES(?, 'owner', ?, '', 1, '', ?)",
                        (acct, token, time.time()))
            tcon.commit()
        finally:
            tcon.close()
    host = next((h for h in (tenancy.registry() or {}).get("tenants", {})
                 .get(tid, {}).get("hosts", []) if h.endswith(".localhost")),
                f"{tid}.localhost")
    port = f":{request.url.port}" if request.url.port else ""
    fleet.log("acted as tenant admin", f"{u['name']} → {tid}", u["name"])
    e = con.execute("SELECT id FROM engagements WHERE tenant_id=? AND"
                    " status != 'archived' LIMIT 1", (tid,)).fetchone()
    if e:
        log(con, e["id"], u["name"], f"opened their ops app as '{acct}'")
        con.commit()
    return {"ok": True,
            "url": f"http://{host}{port}/ops/?actas={token}",
            "account": acct}


