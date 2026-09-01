"""People, managed: role requests, invitations, the customer book,
and the teaching team.

Extracted whole from main.py — the routes that decide WHO somebody is on
this install. The rules stay in roles.py (pure, enumerable); these routes
only apply them. Approval IS the promotion — same rights, same audit —
so no queue here can become the way around the permission model.
"""
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db, notify

router = APIRouter()

from .main import CFG, admin_user, current_user, get_con  # noqa: E402


# ── role requests: what somebody asked to be, and who decides it ─────────────
# The rules live in roles.py (pure, enumerable); these routes only apply
# them. Approval IS the promotion — same rights, same audit — so the queue
# can never become the way around the permission model.

@router.get("/api/roles")
def role_catalog():
    """The sign-up dropdown's source of truth: every role, its label, and
    what it is for. Public — it is shown to people who have no account."""
    from . import roles as R
    return [{"value": r, "label": R.LABELS[r], "what": R.DESCRIPTIONS[r]}
            for r in R.ROLES]


def _reviewer(user=Depends(current_user)):
    from . import roles as R
    if not R.is_reviewer(user["role"], is_admin=bool(user["is_admin"])):
        raise HTTPException(403, "only the office reviews role requests")
    return user


@router.get("/api/roles/requests")
def role_requests(user=Depends(_reviewer), con=Depends(get_con)):
    """People waiting to be told what they are — only the requests this
    reviewer could actually grant. Showing an office administrator a
    director request they cannot act on is an invitation to try."""
    from . import roles as R
    grantable = R.grantable_by(user["role"],
                               is_admin=bool(user["is_admin"]))
    rows = con.execute(
        "SELECT id,name,email,role,requested_role,created_at FROM users"
        " WHERE requested_role!='' AND active=1 AND erased_at IS NULL"
        " ORDER BY created_at").fetchall()
    return [{**dict(r),
             "requested_label": R.LABELS.get(r["requested_role"],
                                             r["requested_role"])}
            for r in rows if r["requested_role"] in grantable]


class RoleDecideBody(BaseModel):
    approve: bool
    note: str = ""


@router.post("/api/roles/requests/{uid}/decide")
def role_decide(uid: int, body: RoleDecideBody, user=Depends(_reviewer),
                con=Depends(get_con)):
    from . import roles as R
    target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if target is None or not target["requested_role"]:
        raise HTTPException(404, "no request standing for this person")
    if uid == user["id"]:
        raise HTTPException(400, "someone else decides what you are")
    wanted = target["requested_role"]
    if not R.can_grant(user, wanted):
        raise HTTPException(403, "that request is for the owner to decide")
    label = R.LABELS.get(wanted, wanted)
    if body.approve:
        # The promotion, and cleanly: a role change alters what every
        # existing session may do, so the sessions end — the person signs
        # in again and gets the new capabilities whole, not half-changed.
        con.execute(
            "UPDATE users SET role=?, is_admin=?, requested_role='',"
            " token=? WHERE id=?",
            (wanted, 1 if (R.carries_admin(wanted) or target["is_admin"])
             else 0, secrets.token_urlsafe(24), uid))
        con.execute("DELETE FROM login_tokens WHERE user_id=?", (uid,))
        notify.push(con, f"You are confirmed as {label}",
                    (body.note or "Sign in again to pick up what that"
                                  " opens."), kind="role", user_id=uid)
    else:
        con.execute("UPDATE users SET requested_role='' WHERE id=?", (uid,))
        notify.push(con, f"Your {label} request was declined",
                    body.note or "Talk to the office if this is a surprise.",
                    kind="role", user_id=uid)
    con.commit()
    return {"id": uid, "requested": wanted, "approved": body.approve,
            "role": wanted if body.approve else target["role"]}


# ── invites: authority in link form ──────────────────────────────────────────
# The third way in, beside the storefront's claim and the key-holder's
# direct create: the office mints a link that carries a role, sends it to
# the person, and their sign-up lands straight in that role — or wires up
# an account made for them in advance. Minting takes the same right as
# granting, so a link can never outrank its author.

class InviteBody(BaseModel):
    role: str
    name: str = ""
    email: str = ""
    person_id: int | None = None


@router.post("/api/roles/invites")
def invite_create(body: InviteBody, user=Depends(_reviewer),
                  con=Depends(get_con)):
    from . import roles as R
    role = R.normalise(body.role)
    if not R.can_grant(user, role):
        raise HTTPException(403, "you cannot invite a role you could not "
                                 "grant")
    if body.person_id is not None:
        if con.execute("SELECT 1 FROM users WHERE id=?",
                       (body.person_id,)).fetchone() is None:
            raise HTTPException(404, "no such person to bind the invite to")
    token = secrets.token_urlsafe(18)
    con.execute(
        "INSERT INTO invites(token,role,name,email,person_id,created_by,"
        " created_at) VALUES(?,?,?,?,?,?,?)",
        (token, role, body.name.strip()[:200], body.email.strip()[:200],
         body.person_id, user["id"], db.now()))
    con.commit()
    return {"token": token, "path": f"/join/{token}", "role": role,
            "role_label": R.LABELS.get(role, role)}


def _invite(con, token: str):
    inv = con.execute("SELECT * FROM invites WHERE token=?",
                      (token,)).fetchone()
    if inv is None:
        raise HTTPException(404, "that invitation does not exist")
    if inv["used_at"]:
        raise HTTPException(410, "that invitation was already used")
    return inv


@router.get("/api/join/{token}")
def invite_peek(token: str, con=Depends(get_con)):
    """What the link-holder sees before committing: which role, and
    whether a name is already waiting for them."""
    from . import roles as R
    inv = _invite(con, token)
    name = inv["name"]
    if inv["person_id"]:
        p = con.execute("SELECT name FROM users WHERE id=?",
                        (inv["person_id"],)).fetchone()
        name = p["name"] if p else name
    return {"role": inv["role"],
            "role_label": R.LABELS.get(inv["role"], inv["role"]),
            "name": name, "locked": inv["person_id"] is not None,
            "brand": CFG["brand_name"]}


class JoinBody(BaseModel):
    name: str = ""
    password: str = ""


@router.post("/api/join/{token}")
def invite_join(token: str, body: JoinBody, con=Depends(get_con)):
    from . import roles as R
    inv = _invite(con, token)
    if CFG.get("require_passwords") and not body.password:
        raise HTTPException(400, "a password is required here")
    flag = 1 if R.carries_admin(inv["role"]) else 0
    if inv["person_id"]:
        # The premade account: the invite IS its activation. The name was
        # chosen when the account was made; sign-up supplies the secret.
        u = con.execute("SELECT * FROM users WHERE id=?",
                        (inv["person_id"],)).fetchone()
        if u is None:
            raise HTTPException(410, "the account this invite pointed at "
                                     "is gone")
        con.execute(
            "UPDATE users SET role=?, is_admin=?, active=1,"
            " requested_role='', password_hash=?, token=? WHERE id=?",
            (inv["role"], flag or u["is_admin"],
             auth.hash_password(body.password) if body.password
             else u["password_hash"],
             secrets.token_urlsafe(24), u["id"]))
        uid = u["id"]
    else:
        name = (body.name or inv["name"]).strip()
        if not name:
            raise HTTPException(400, "tell us your name")
        if con.execute("SELECT 1 FROM users WHERE lower(name)=lower(?)",
                       (name,)).fetchone():
            raise HTTPException(409, "that name already has an account — "
                                     "ask the office to bind the invite "
                                     "to it")
        cur = con.execute(
            "INSERT INTO users(name,role,token,region,is_admin,email,"
            " password_hash,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (name[:200], inv["role"], secrets.token_urlsafe(24), "", flag,
             inv["email"], auth.hash_password(body.password)
             if body.password else "", db.now()))
        uid = cur.lastrowid
    con.execute("UPDATE invites SET used_at=? WHERE id=?",
                (db.now(), inv["id"]))
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    con.commit()
    notify.push(con, f"{u['name']} accepted their"
                     f" {R.LABELS.get(inv['role'], inv['role'])} invitation",
                "The account is live.", kind="role")
    return auth.user_json(u)


# ── customers: the consumer half of the CRM ──────────────────────────────────
# Clients (B2B) had a tab from the start; the people who simply buy things
# never did — the ERP could take their orders but not show them to anyone.

@router.get("/api/customers")
def customers_list(q: str = "", user=Depends(current_user),
                   con=Depends(get_con)):
    if not (user["is_admin"] or user["role"] == "employee"):
        raise HTTPException(403, "the customer book is office-side")
    like = f"%{q.strip()}%"
    rows = con.execute(
        "SELECT u.id, u.name, u.email, u.region, u.active, u.created_at,"
        " u.requested_role,"
        " COUNT(o.id) AS orders,"
        " COALESCE(SUM(CASE WHEN o.status!='cancelled'"
        "   THEN o.total_cents END),0) AS spent_cents,"
        " MAX(o.created_at) AS last_order_at"
        " FROM users u LEFT JOIN orders o ON o.user_id=u.id"
        " WHERE u.role='customer' AND u.erased_at IS NULL"
        "  AND (? = '%%' OR u.name LIKE ? OR u.email LIKE ?)"
        " GROUP BY u.id"
        " ORDER BY last_order_at IS NULL, last_order_at DESC, u.name"
        " LIMIT 500", (like, like, like)).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/customers/{uid}")
def customer_detail(uid: int, user=Depends(current_user),
                    con=Depends(get_con)):
    if not (user["is_admin"] or user["role"] == "employee"):
        raise HTTPException(403, "the customer book is office-side")
    u = con.execute(
        "SELECT id,name,email,region,active,created_at,requested_role"
        " FROM users WHERE id=? AND role='customer' AND erased_at IS NULL",
        (uid,)).fetchone()
    if u is None:
        raise HTTPException(404, "no such customer")
    orders = con.execute(
        "SELECT id,status,total_cents,created_at FROM orders WHERE user_id=?"
        " ORDER BY created_at DESC LIMIT 50", (uid,)).fetchall()
    courses = con.execute(
        "SELECT c.name FROM enrollments e JOIN courses c ON c.id=e.course_id"
        " WHERE e.user_id=? AND e.until IS NULL", (uid,)).fetchall()
    return {**dict(u), "orders": [dict(o) for o in orders],
            "courses": [c["name"] for c in courses]}


# ── the teaching team: who runs the school day to day ────────────────────────

@router.get("/api/learning/team")
def team_list(user=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT u.id, u.name, u.email, u.role, u.active, u.is_admin,"
        " (SELECT COUNT(*) FROM courses c WHERE c.teacher_id=u.id"
        "   AND c.active=1) AS teaches,"
        " (SELECT 1 FROM pay_rates p WHERE p.teacher_id=u.id) AS has_rate"
        " FROM users u"
        " WHERE u.erased_at IS NULL AND (u.role IN"
        "  ('teacher','employee','volunteer','director') OR u.is_admin=1)"
        " ORDER BY u.active DESC, u.role, u.name").fetchall()
    return [dict(r) for r in rows]


class TeamBody(BaseModel):
    name: str
    role: str = "teacher"
    email: str = ""


@router.post("/api/learning/team")
def team_add(body: TeamBody, user=Depends(admin_user), con=Depends(get_con)):
    """The premade account: made by the office, before its person arrives.
    Pair it with an invite bound to it and their sign-up wires straight
    in. Direct creation is an admin act — everyone else's road here runs
    through claims or invitations."""
    from . import roles as R
    role = R.normalise(body.role, default="")
    if role not in R.ROLES or role == R.STUDENT:
        raise HTTPException(400, "pick one of the team roles")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "a person needs a name")
    if con.execute("SELECT 1 FROM users WHERE lower(name)=lower(?)",
                   (name,)).fetchone():
        raise HTTPException(409, "that name already has an account")
    cur = con.execute(
        "INSERT INTO users(name,role,token,region,is_admin,email,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (name[:200], role, secrets.token_urlsafe(24), "",
         1 if R.carries_admin(role) else 0, body.email.strip()[:200],
         db.now()))
    con.commit()
    return {"id": cur.lastrowid}
