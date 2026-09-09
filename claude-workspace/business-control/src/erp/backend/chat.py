"""Chat + call signaling. Three conversation kinds:

- team: one room for every employee/admin
- support: one per customer, visible to that customer and all staff
- dm: two explicit members (staff to staff)

Real-time delivery and WebRTC call signaling ride one WebSocket per client
(/ws?token=...); REST covers history and works as a polling fallback."""
import asyncio
import json

from . import db

# user_id -> set of live WebSocket objects
HUB: dict[int, set] = {}


def is_staff(user) -> bool:
    return bool(user["is_admin"]) or user["role"] in ("employee", "owner")


def ensure_team(con) -> int:
    row = con.execute("SELECT id FROM conversations WHERE kind='team'").fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO conversations(kind,name,created_at) VALUES('team','Team',?)",
        (db.now(),))
    con.commit()
    return cur.lastrowid


def ensure_support(con, customer) -> int:
    row = con.execute(
        "SELECT id FROM conversations WHERE kind='support' AND"
        " customer_user_id=?", (customer["id"],)).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO conversations(kind,name,customer_user_id,created_at)"
        " VALUES('support',?,?,?)",
        (f"Support — {customer['name']}", customer["id"], db.now()))
    con.commit()
    return cur.lastrowid


def ensure_dm(con, a: int, b: int) -> int:
    row = con.execute(
        "SELECT c.id FROM conversations c"
        " JOIN conv_members m1 ON m1.conv_id=c.id AND m1.user_id=?"
        " JOIN conv_members m2 ON m2.conv_id=c.id AND m2.user_id=?"
        " WHERE c.kind='dm'", (a, b)).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO conversations(kind,created_at) VALUES('dm',?)", (db.now(),))
    cid = cur.lastrowid
    con.execute("INSERT INTO conv_members(conv_id,user_id) VALUES(?,?),(?,?)",
                (cid, a, cid, b))
    con.commit()
    return cid


def can_access(con, user, conv) -> bool:
    if conv["kind"] == "team":
        return is_staff(user)
    if conv["kind"] == "support":
        return is_staff(user) or conv["customer_user_id"] == user["id"]
    return con.execute("SELECT 1 FROM conv_members WHERE conv_id=? AND"
                       " user_id=?", (conv["id"], user["id"])).fetchone() \
        is not None


def audience(con, conv) -> list[int]:
    """User ids who should receive messages in this conversation."""
    if conv["kind"] == "team":
        rows = con.execute("SELECT id FROM users WHERE active=1 AND"
                           " (is_admin=1 OR role IN ('employee','owner'))")
        return [r["id"] for r in rows]
    if conv["kind"] == "support":
        rows = con.execute("SELECT id FROM users WHERE active=1 AND"
                           " (is_admin=1 OR role IN ('employee','owner'))")
        ids = [r["id"] for r in rows]
        if conv["customer_user_id"] not in ids:
            ids.append(conv["customer_user_id"])
        return ids
    rows = con.execute("SELECT user_id FROM conv_members WHERE conv_id=?",
                       (conv["id"],))
    return [r["user_id"] for r in rows]


def convs_for(con, user) -> list[dict]:
    out = []
    if is_staff(user):
        team_id = ensure_team(con)
        rows = con.execute(
            "SELECT * FROM conversations WHERE id=? OR kind='support'"
            " OR id IN (SELECT conv_id FROM conv_members WHERE user_id=?)"
            " ORDER BY kind='team' DESC, id DESC",
            (team_id, user["id"])).fetchall()
    else:
        ensure_support(con, user)
        rows = con.execute(
            "SELECT * FROM conversations WHERE"
            " (kind='support' AND customer_user_id=?)"
            " OR id IN (SELECT conv_id FROM conv_members WHERE user_id=?)"
            " ORDER BY id DESC", (user["id"], user["id"])).fetchall()
    staff_online = None
    for r in rows:
        d = dict(r)
        d["call_target"] = None
        if r["kind"] == "dm":
            other = con.execute(
                "SELECT u.id, u.name FROM conv_members m JOIN users u ON"
                " u.id=m.user_id WHERE m.conv_id=? AND m.user_id!=?",
                (r["id"], user["id"])).fetchone()
            d["name"] = other["name"] if other else "DM"
            d["call_target"] = other["id"] if other else None
        elif r["kind"] == "support":
            if is_staff(user):
                d["call_target"] = r["customer_user_id"]
            else:
                if staff_online is None:
                    ids = online_ids()
                    row2 = con.execute(
                        "SELECT id FROM users WHERE active=1 AND"
                        " (is_admin=1 OR role IN ('employee','owner'))"
                        + (" AND id IN (%s)" % ",".join(map(str, ids))
                           if ids else " AND 1=0")).fetchone()
                    staff_online = row2["id"] if row2 else 0
                d["call_target"] = staff_online or None
        last = con.execute(
            "SELECT m.id, m.user_id, m.body, m.created_at, u.name"
            " FROM messages m JOIN users u"
            " ON u.id=m.user_id WHERE conv_id=? ORDER BY m.id DESC LIMIT 1",
            (r["id"],)).fetchone()
        d["last"] = dict(last) if last else None
        out.append(d)
    return out


def add_message(con, conv_id: int, user, body: str) -> dict:
    cur = con.execute(
        "INSERT INTO messages(conv_id,user_id,body,created_at) VALUES(?,?,?,?)",
        (conv_id, user["id"], body, db.now()))
    con.commit()
    m = con.execute(
        "SELECT m.*, u.name FROM messages m JOIN users u ON u.id=m.user_id"
        " WHERE m.id=?", (cur.lastrowid,)).fetchone()
    return dict(m)


# ---------- live socket hub ----------

# ── who is on, and how a message reaches a socket on another machine ──────
# A websocket lives in one process. When a tenant is served by two nodes,
# the person you are messaging may be connected to the other one. So the
# hub is two things now: the sockets this process holds (delivered to at
# once, as before), and two tables in the tenant's database — presence
# (who is on which node, heartbeated) and an outbox (what is waiting for
# somebody not connected here). Every node's socket handler pumps the
# outbox for its own people once a second. On one node none of that is
# visible; on two, a message still lands.

WS_TABLES = """
CREATE TABLE IF NOT EXISTS ws_presence (
  node TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  seen REAL NOT NULL,
  PRIMARY KEY (node, user_id)
);
CREATE TABLE IF NOT EXISTS ws_outbox (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  payload TEXT NOT NULL,
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ws_outbox_who ON ws_outbox(user_id, id);
"""
PRESENCE_SEC = 60          # a node that has not said so in a minute is gone
OUTBOX_SEC = 60            # a message nobody collected in a minute is dropped


def node_id() -> str:
    import os
    import socket
    return os.environ.get("BC_NODE") or f"{socket.gethostname()}:{os.getpid()}"


def init_tables(con):
    con.executescript(WS_TABLES)
    con.commit()


def _key(user_id: int):
    """(tenant, user id). Bare ids collide across tenants — two businesses
    each with a user 3 must not receive each other's messages or calls."""
    from . import tenancy
    return (tenancy.CURRENT.get(), user_id)


def _own_con():
    return db.connect()


def register(user_id: int, ws) -> None:
    HUB.setdefault(_key(user_id), set()).add(ws)
    heartbeat(user_id)


def heartbeat(user_id: int) -> None:
    """Say this person is connected here, now."""
    import time
    con = _own_con()
    try:
        con.execute("INSERT OR REPLACE INTO ws_presence(node,user_id,seen)"
                    " VALUES(?,?,?)", (node_id(), user_id, time.time()))
        con.commit()
    except Exception:                                        # noqa: BLE001
        pass
    finally:
        con.close()


def unregister(user_id: int, ws) -> None:
    k = _key(user_id)
    HUB.get(k, set()).discard(ws)
    if not HUB.get(k):
        HUB.pop(k, None)
        con = _own_con()
        try:
            con.execute("DELETE FROM ws_presence WHERE node=? AND user_id=?",
                        (node_id(), user_id))
            con.commit()
        except Exception:                                    # noqa: BLE001
            pass
        finally:
            con.close()


def local_ids() -> list[int]:
    from . import tenancy
    tid = tenancy.CURRENT.get()
    return [uid for (t, uid) in HUB.keys() if t == tid]


def online_ids() -> list[int]:
    """Connected here, or connected to any node that has said so lately."""
    import time
    ids = set(local_ids())
    con = _own_con()
    try:
        for r in con.execute("SELECT DISTINCT user_id FROM ws_presence"
                             " WHERE seen>=?", (time.time() - PRESENCE_SEC,)):
            ids.add(r["user_id"])
    except Exception:                                        # noqa: BLE001
        pass
    finally:
        con.close()
    return sorted(ids)


async def send_to(user_ids: list[int], payload: dict) -> None:
    """Here at once; elsewhere through the outbox. A person with a socket
    on this node and another on a second node gets it on both, which is
    what having two tabs open means."""
    import time
    data = json.dumps(payload)
    dead = []
    remote = []
    for uid in user_ids:
        socks = list(HUB.get(_key(uid), ()))
        for ws in socks:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append((uid, ws))
        remote.append(uid)
    for uid, ws in dead:
        unregister(uid, ws)
    if remote:
        con = _own_con()
        try:
            here = node_id()
            elsewhere = {r["user_id"] for r in con.execute(
                "SELECT DISTINCT user_id FROM ws_presence WHERE node!=? AND"
                " seen>=?", (here, time.time() - PRESENCE_SEC))}
            now = time.time()
            for uid in remote:
                if uid in elsewhere:
                    con.execute("INSERT INTO ws_outbox(user_id,payload,at)"
                                " VALUES(?,?,?)", (uid, data, now))
            con.commit()
        except Exception:                                    # noqa: BLE001
            pass
        finally:
            con.close()


def collect(user_id: int) -> list[str]:
    """What other nodes left for this person; taken once, and stale mail
    swept on the way."""
    import time
    con = _own_con()
    try:
        con.execute("DELETE FROM ws_outbox WHERE at<?", (time.time() - OUTBOX_SEC,))
        rows = con.execute("SELECT id, payload FROM ws_outbox WHERE user_id=?"
                           " ORDER BY id LIMIT 100", (user_id,)).fetchall()
        if rows:
            con.execute("DELETE FROM ws_outbox WHERE user_id=? AND id<=?",
                        (user_id, rows[-1]["id"]))
        con.commit()
        return [r["payload"] for r in rows]
    except Exception:                                        # noqa: BLE001
        return []
    finally:
        con.close()


async def pump(user_id: int, ws, every: float = 1.0) -> None:
    """Runs beside a socket for its whole life: delivers what other nodes
    left, and keeps presence fresh."""
    import time
    last_beat = time.time()
    try:
        while True:
            await asyncio.sleep(every)
            for data in await asyncio.to_thread(collect, user_id):
                try:
                    await ws.send_text(data)
                except Exception:
                    return
            if time.time() - last_beat > PRESENCE_SEC / 3:
                await asyncio.to_thread(heartbeat, user_id)
                last_beat = time.time()
    except asyncio.CancelledError:
        return
