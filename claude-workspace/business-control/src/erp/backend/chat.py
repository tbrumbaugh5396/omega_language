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
                           if ids else " AND 0")).fetchone()
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

def register(user_id: int, ws) -> None:
    HUB.setdefault(user_id, set()).add(ws)


def unregister(user_id: int, ws) -> None:
    HUB.get(user_id, set()).discard(ws)
    if not HUB.get(user_id):
        HUB.pop(user_id, None)


def online_ids() -> list[int]:
    return list(HUB.keys())


async def send_to(user_ids: list[int], payload: dict) -> None:
    data = json.dumps(payload)
    dead = []
    for uid in user_ids:
        for ws in list(HUB.get(uid, ())):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append((uid, ws))
    for uid, ws in dead:
        unregister(uid, ws)
