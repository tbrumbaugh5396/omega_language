"""Joining and leaving: the first fortnight and the last day.

Hiring already wrote a six-line list when it opened an account, which was
right and was not enough. The same six lines went to a delivery driver
and a teacher; nothing had a date, so nothing could be late; and the only
way to see how a new starter was getting on was to open their record and
count ticks.

So the list becomes a template, and there can be more than one:

  * A **template** per role, with steps that each carry a day. "Contract
    signed" is day one; "end of first week check-in" is day seven. A step
    with a day can be overdue, and a list where nothing can be overdue is
    a list that quietly never finishes.

  * A step may **need a document**, which is the difference between "we
    asked for their right-to-work" and "we have it". The vault already
    holds documents; this records which step is waiting on one.

  * A **journey** is one person walking one template, with a start date
    that is their start date rather than the day somebody got round to
    setting it up.

Hiring keeps calling this: a hire whose role matches a template gets that
template, and anything else gets the built-in list, so an install that
never opens this screen behaves exactly as it did before.

**Leaving is the same machinery pointed the other way, and one thing
more.** A template has a kind, so a business can write the list for a
last day as it writes the list for a first one — hand back the keys,
final expenses in, handover written. What a checklist cannot be trusted
with is access, because the whole risk of somebody leaving badly is the
gap between the decision and the account still working. So closing
access is an ACTION here rather than a line to tick: it deactivates the
account, forgets the PIN and the clock badge, revokes every API key
bound to them, and takes them off the shifts nobody has worked yet. One
button, done in one transaction, and recorded.

Two deliberate limits. Nothing is deleted: the person, their hours, what
they were paid and what they did stay exactly where they are, because a
business that erases a leaver cannot answer a question about last year
and in most places may not. And the reason for leaving is recorded
plainly, including dismissal, without the software offering an opinion
about it.
"""
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS onboarding_templates (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'joining',             -- joining|leaving
  role TEXT DEFAULT '',                    -- '' = anybody
  active INTEGER DEFAULT 1,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS onboarding_steps (
  id INTEGER PRIMARY KEY,
  template_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  tab TEXT DEFAULT '',                     -- the screen it is done on
  days_after INTEGER DEFAULT 0,            -- from their start date
  needs_document INTEGER DEFAULT 0,
  position INTEGER DEFAULT 0,
  note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS onboarding_steps_t ON onboarding_steps(template_id);

CREATE TABLE IF NOT EXISTS onboarding_journeys (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  template_id INTEGER DEFAULT 0,
  starts REAL NOT NULL,
  completed_at REAL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS onboarding_journeys_u ON onboarding_journeys(user_id);

/* Somebody leaving. One row per departure, kept forever: a business that
   erases a leaver cannot answer a question about last year, and in most
   places may not. */
CREATE TABLE IF NOT EXISTS departures (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  name TEXT DEFAULT '',                    -- as it was on the day
  role TEXT DEFAULT '',
  reason TEXT NOT NULL,                    -- see REASONS
  last_day REAL NOT NULL,
  notice_given REAL DEFAULT 0,
  rehire TEXT DEFAULT 'unknown',           -- yes|no|unknown
  note TEXT DEFAULT '',
  journey_id INTEGER DEFAULT 0,            -- their leaving list
  access_closed_at REAL DEFAULT 0,
  access_closed_by TEXT DEFAULT '',
  access_detail TEXT DEFAULT '',           -- what closing it actually did
  final_pay_run_id INTEGER DEFAULT 0,
  recorded_by TEXT DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE(user_id, last_day)
);
"""

# onboarding_tasks belongs to hiring and predates this; these are the
# columns a dated, document-aware list needs. CREATE TABLE IF NOT EXISTS
# leaves an existing table alone, so they are added explicitly.
MIGRATIONS = [
    "ALTER TABLE onboarding_templates ADD COLUMN kind TEXT DEFAULT 'joining'",
    "ALTER TABLE onboarding_journeys ADD COLUMN kind TEXT DEFAULT 'joining'",
    "ALTER TABLE onboarding_tasks ADD COLUMN journey_id INTEGER DEFAULT 0",
    "ALTER TABLE onboarding_tasks ADD COLUMN due REAL DEFAULT 0",
    "ALTER TABLE onboarding_tasks ADD COLUMN needs_document INTEGER DEFAULT 0",
    "ALTER TABLE onboarding_tasks ADD COLUMN document_id INTEGER DEFAULT 0",
]


def init_tables(con):
    con.executescript(TABLES)
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:                                    # noqa: BLE001
            pass
    # The built-in list, as an editable template. Seeded so the screen has
    # something on it the first time it is opened: an empty template
    # editor teaches nobody what a template is for.
    if not con.execute("SELECT 1 FROM onboarding_templates").fetchone():
        from .hiring import ONBOARDING
        cur = con.execute(
            "INSERT INTO onboarding_templates(name,role,note,created_at)"
            " VALUES('New starter','',?,?)",
            ("The list every hire got before templates existed. Edit it, or "
             "add one per role.", db.now()))
        tid = cur.lastrowid
        for i, (title, tab) in enumerate(ONBOARDING):
            con.execute(
                "INSERT INTO onboarding_steps(template_id,title,tab,"
                " days_after,position) VALUES(?,?,?,?,?)",
                (tid, title, tab, [0, 1, 1, 2, 3, 7][i] if i < 6 else i, i))
    if not con.execute("SELECT 1 FROM onboarding_templates WHERE kind='leaving'"
                       ).fetchone():
        cur = con.execute(
            "INSERT INTO onboarding_templates(name,kind,role,note,created_at)"
            " VALUES('Last day','leaving','',?,?)",
            ("What a last day needs whatever the reason for it. Closing "
             "access is a button on the departure, not a tick here.",
             db.now()))
        lid = cur.lastrowid
        for i, (title, tab, days) in enumerate(LEAVING):
            con.execute(
                "INSERT INTO onboarding_steps(template_id,title,tab,"
                " days_after,position) VALUES(?,?,?,?,?)",
                (lid, title, tab, days, i))
    con.commit()


def _office(user) -> bool:
    return auth.office(user, "settings", "workforce")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "onboarding is the office's")


REASONS = {
    "resigned": "Resigned",
    "dismissed": "Dismissed",
    "redundancy": "Redundancy",
    "end_of_contract": "End of contract",
    "retired": "Retired",
    "died": "Died",
    "other": "Other",
}
KINDS = ("joining", "leaving")
# The list every business needs on a last day, whatever else it adds.
LEAVING = [
    ("Handover written and handed over", "board", 0),
    ("Keys, badge and equipment back", "staff", 0),
    ("Final expenses and hours in", "expenses", 0),
    ("Access closed", "staff", 0),
    ("Final pay run", "payroll", 7),
]


def template_for(con, role: str, kind: str = "joining"):
    """The template for a role, then the one for anybody, then nothing."""
    return con.execute(
        "SELECT * FROM onboarding_templates WHERE active=1 AND role=?"
        " AND kind=? ORDER BY id LIMIT 1", (role or "", kind)).fetchone() \
        or con.execute(
        "SELECT * FROM onboarding_templates WHERE active=1 AND role=''"
        " AND kind=? ORDER BY id LIMIT 1", (kind,)).fetchone()


def start(con, uid: int, template_id: int = 0, starts: float = 0,
          kind: str = "joining") -> dict:
    """Put somebody on a list. Idempotent per template: starting the same
    one twice would leave two of every step and no way to tell which tick
    counted."""
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if u is None:
        raise HTTPException(404, "no such person")
    t = con.execute("SELECT * FROM onboarding_templates WHERE id=?",
                    (template_id,)).fetchone() if template_id \
        else template_for(con, u["role"], kind)
    if t is None:
        raise HTTPException(400, "no template to start them on")
    have = con.execute(
        "SELECT id FROM onboarding_journeys WHERE user_id=? AND template_id=?"
        " AND completed_at=0", (uid, t["id"])).fetchone()
    if have:
        return {"ok": True, "journey_id": have["id"], "already": True}
    at = starts or time.time()
    cur = con.execute(
        "INSERT INTO onboarding_journeys(user_id,template_id,starts,kind,"
        " created_at) VALUES(?,?,?,?,?)",
        (uid, t["id"], at, t["kind"] or kind, db.now()))
    jid = cur.lastrowid
    steps = con.execute(
        "SELECT * FROM onboarding_steps WHERE template_id=?"
        " ORDER BY position, id", (t["id"],)).fetchall()
    for s in steps:
        con.execute(
            "INSERT INTO onboarding_tasks(user_id,title,tab,position,"
            " created_at,journey_id,due,needs_document) VALUES(?,?,?,?,?,?,?,?)",
            (uid, s["title"], s["tab"], s["position"], db.now(), jid,
             at + int(s["days_after"] or 0) * 86400,
             int(s["needs_document"] or 0)))
    con.commit()
    return {"ok": True, "journey_id": jid, "steps": len(steps)}


def _journey_row(con, j) -> dict:
    tasks = [dict(r) for r in con.execute(
        "SELECT * FROM onboarding_tasks WHERE journey_id=? ORDER BY position,"
        " id", (j["id"],)).fetchall()]
    now = time.time()
    done = sum(1 for t in tasks if t["done_at"])
    overdue = [t for t in tasks
               if not t["done_at"] and t["due"] and t["due"] < now]
    waiting = [t for t in tasks
               if not t["done_at"] and t["needs_document"] and not t["document_id"]]
    return {**dict(j), "tasks": tasks, "total": len(tasks), "done": done,
            "overdue": len(overdue), "waiting_on_documents": len(waiting),
            "next": next((t["title"] for t in tasks if not t["done_at"]), ""),
            "complete": bool(tasks) and done == len(tasks)}


def board(con) -> list:
    rows = []
    for j in con.execute(
            "SELECT j.*, u.name, u.role FROM onboarding_journeys j"
            " JOIN users u ON u.id=j.user_id"
            " ORDER BY j.completed_at, j.starts DESC LIMIT 100").fetchall():
        rows.append(_journey_row(con, j))
    return rows


def tick(con, tid: int, by: str, document_id: int = 0) -> dict:
    t = con.execute("SELECT * FROM onboarding_tasks WHERE id=?",
                    (tid,)).fetchone()
    if t is None:
        raise HTTPException(404, "no such step")
    if t["needs_document"] and not (document_id or t["document_id"]) \
            and not t["done_at"]:
        raise HTTPException(
            400, "that step is waiting on a document — attach one, or take "
                 "the requirement off the template. 'We asked for it' and "
                 "'we have it' are different states and this is the one "
                 "that records which")
    if t["done_at"]:
        con.execute("UPDATE onboarding_tasks SET done_at=0, done_by=''"
                    " WHERE id=?", (tid,))
    else:
        con.execute(
            "UPDATE onboarding_tasks SET done_at=?, done_by=?, document_id=?"
            " WHERE id=?",
            (time.time(), by[:120], document_id or t["document_id"], tid))
    con.commit()
    if t["journey_id"]:
        left = con.execute(
            "SELECT COUNT(*) AS n FROM onboarding_tasks WHERE journey_id=?"
            " AND done_at=0", (t["journey_id"],)).fetchone()["n"]
        con.execute("UPDATE onboarding_journeys SET completed_at=? WHERE id=?",
                    (0 if left else time.time(), t["journey_id"]))
        con.commit()
    return {"ok": True, "done": not t["done_at"]}


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/onboarding")
def onboarding_page(user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    from .main import JOBS, ROLES_ALLOWED
    temps = []
    for t in con.execute("SELECT * FROM onboarding_templates ORDER BY name"
                         ).fetchall():
        temps.append({**dict(t), "steps": [dict(r) for r in con.execute(
            "SELECT * FROM onboarding_steps WHERE template_id=?"
            " ORDER BY position, id", (t["id"],)).fetchall()]})
    rows = board(con)
    return {"templates": temps, "journeys": rows,
            "departures": departures(con),
            "reasons": [{"k": k, "label": v} for k, v in REASONS.items()],
            "template_kinds": list(KINDS),
            "roles": [r for r in ROLES_ALLOWED if r not in ("customer", "donor")],
            "jobs": list(JOBS),
            "counts": {
                "in_progress": sum(1 for r in rows if not r["complete"]),
                "overdue": sum(r["overdue"] for r in rows),
                "waiting": sum(r["waiting_on_documents"] for r in rows),
            },
            "staff": [dict(r) for r in con.execute(
                "SELECT id, name, role FROM users WHERE active=1 AND"
                " role NOT IN ('customer','donor') ORDER BY name").fetchall()]}


class TemplateBody(BaseModel):
    id: int = 0
    name: str
    kind: str = "joining"
    role: str = ""
    active: bool = True
    note: str = ""


@router.post("/api/onboarding/templates")
def template_save(body: TemplateBody, user=Depends(current_user),
                  con=Depends(get_con)):
    _require(user)
    if not body.name.strip():
        raise HTTPException(400, "name the template")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {KINDS}")
    args = (body.name.strip()[:80], body.kind, body.role.strip()[:40],
            int(body.active), body.note.strip()[:400])
    if body.id:
        con.execute("UPDATE onboarding_templates SET name=?, kind=?, role=?,"
                    " active=?, note=? WHERE id=?", args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO onboarding_templates(name,kind,role,active,note,"
        " created_at) VALUES(?,?,?,?,?,?)", args + (db.now(),))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


class StepBody(BaseModel):
    id: int = 0
    title: str
    tab: str = ""
    days_after: int = 0
    needs_document: bool = False
    position: int = 0
    note: str = ""


@router.post("/api/onboarding/templates/{tid}/steps")
def step_save(tid: int, body: StepBody, user=Depends(current_user),
              con=Depends(get_con)):
    _require(user)
    if con.execute("SELECT 1 FROM onboarding_templates WHERE id=?",
                   (tid,)).fetchone() is None:
        raise HTTPException(404, "no such template")
    if not body.title.strip():
        raise HTTPException(400, "say what the step is")
    if body.days_after < 0 or body.days_after > 365:
        raise HTTPException(400, "a step falls due between the start day and "
                                 "a year in")
    args = (body.title.strip()[:200], body.tab.strip()[:40], body.days_after,
            int(body.needs_document), body.position, body.note.strip()[:400])
    if body.id:
        con.execute("UPDATE onboarding_steps SET title=?, tab=?, days_after=?,"
                    " needs_document=?, position=?, note=? WHERE id=?",
                    args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO onboarding_steps(template_id,title,tab,days_after,"
        " needs_document,position,note) VALUES(?,?,?,?,?,?,?)", (tid,) + args)
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/onboarding/steps/{sid}")
def step_delete(sid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    con.execute("DELETE FROM onboarding_steps WHERE id=?", (sid,))
    con.commit()
    return {"ok": True}


class StartBody(BaseModel):
    user_id: int
    template_id: int = 0
    starts: float = 0
    kind: str = "joining"


@router.post("/api/onboarding/start")
def onboarding_start(body: StartBody, user=Depends(current_user),
                     con=Depends(get_con)):
    _require(user)
    return start(con, body.user_id, body.template_id, body.starts,
                 body.kind if body.kind in KINDS else "joining")


class TickBody(BaseModel):
    document_id: int = 0


@router.post("/api/onboarding/tasks/{tid}/done")
def task_done(tid: int, body: TickBody, user=Depends(current_user),
              con=Depends(get_con)):
    _require(user)
    return tick(con, tid, user["name"], body.document_id)


@router.get("/api/onboarding/mine")
def my_onboarding(user=Depends(current_user), con=Depends(get_con)):
    """My own list. A new starter should be able to see what is expected
    of them without asking the person who set it up."""
    js = con.execute("SELECT * FROM onboarding_journeys WHERE user_id=?"
                     " ORDER BY starts DESC", (user["id"],)).fetchall()
    return {"journeys": [_journey_row(con, j) for j in js]}


# ---------- leaving ----------

def close_access(con, uid: int, by: str) -> dict:
    """Shut every door at once.

    A checklist cannot be trusted with this. The whole risk of somebody
    leaving badly is the gap between the decision and the account still
    working, and a line somebody means to tick tomorrow is exactly that
    gap. So it is one action, in one transaction, and it says what it
    did — a security step whose result nobody can read is a security
    step nobody can rely on.

    Nothing is deleted. The account is deactivated, not removed: their
    hours, their pay and what they did stay where they are.
    """
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if u is None:
        raise HTTPException(404, "no such person")
    did = []
    if u["active"]:
        con.execute("UPDATE users SET active=0 WHERE id=?", (uid,))
        did.append("account deactivated")
    if (u["pin_hash"] or "") or (u["pin"] or ""):
        con.execute("UPDATE users SET pin_hash='', pin='' WHERE id=?", (uid,))
        did.append("time-clock PIN forgotten")
    if u["clock_token"] or "":
        con.execute("UPDATE users SET clock_token='' WHERE id=?", (uid,))
        did.append("clock badge void")
    # A token is a live session. Rotating it signs them out everywhere,
    # which a deactivated flag alone does not do until they next load a
    # page that checks.
    con.execute("UPDATE users SET token=? WHERE id=?",
                (secrets.token_urlsafe(24), uid))
    did.append("signed out everywhere")
    try:
        n = con.execute(
            "UPDATE api_keys SET revoked_at=? WHERE user_id=? AND"
            " revoked_at IS NULL", (time.time(), uid)).rowcount
        if n:
            did.append(f"{n} API key{'s' if n != 1 else ''} revoked")
    except Exception:                                        # noqa: BLE001
        pass
    try:
        n = con.execute(
            "DELETE FROM scheduled_shifts WHERE user_id=? AND starts>?",
            (uid, time.time())).rowcount
        if n:
            did.append(f"{n} future shift{'s' if n != 1 else ''} removed")
    except Exception:                                        # noqa: BLE001
        pass
    con.commit()
    return {"ok": True, "did": did}


def record_departure(con, *, uid: int, reason: str, last_day: float,
                     notice_given: float, rehire: str, note: str,
                     by: str, start_list: bool = True) -> dict:
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if u is None:
        raise HTTPException(404, "no such person")
    if reason not in REASONS:
        raise HTTPException(400, f"reason is one of {sorted(REASONS)}")
    if rehire not in ("yes", "no", "unknown"):
        raise HTTPException(400, "rehire is yes, no or unknown")
    have = con.execute("SELECT id FROM departures WHERE user_id=? AND"
                       " access_closed_at=0", (uid,)).fetchone()
    if have:
        raise HTTPException(400, "a departure for them is already open")
    jid = 0
    if start_list:
        try:
            jid = start(con, uid, 0, last_day, "leaving").get("journey_id", 0)
        except HTTPException:
            jid = 0          # no leaving template; the record still stands
    cur = con.execute(
        "INSERT INTO departures(user_id,name,role,reason,last_day,"
        " notice_given,rehire,note,journey_id,recorded_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (uid, u["name"], u["role"], reason, last_day, notice_given, rehire,
         note[:2000], jid, by[:120], db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid, "journey_id": jid}


def departures(con) -> list:
    rows = []
    for r in con.execute(
            "SELECT d.*, u.active FROM departures d"
            " LEFT JOIN users u ON u.id=d.user_id"
            " ORDER BY d.last_day DESC LIMIT 200").fetchall():
        d = dict(r)
        d["reason_label"] = REASONS.get(d["reason"], d["reason"])
        d["access_open"] = not d["access_closed_at"]
        if d["journey_id"]:
            j = con.execute("SELECT * FROM onboarding_journeys WHERE id=?",
                            (d["journey_id"],)).fetchone()
            if j is not None:
                jr = _journey_row(con, j)
                d["done"] = jr["done"]
                d["total"] = jr["total"]
                d["overdue"] = jr["overdue"]
        rows.append(d)
    return rows


class DepartureBody(BaseModel):
    user_id: int
    reason: str
    last_day: float
    notice_given: float = 0
    rehire: str = "unknown"
    note: str = ""
    close_now: bool = False


@router.post("/api/onboarding/departures")
def departure_add(body: DepartureBody, user=Depends(current_user),
                  con=Depends(get_con)):
    """Record that somebody is leaving, and open their last-day list.

    Closing access is a separate act on purpose. Somebody resigning with
    a month's notice keeps working that month; somebody dismissed on the
    spot does not, and the person recording it should say which rather
    than have the software decide from the reason.
    """
    _require(user)
    if body.user_id == user["id"]:
        raise HTTPException(400, "somebody else records your leaving — "
                                 "closing your own access mid-form is how "
                                 "a half-finished departure gets stranded")
    out = record_departure(
        con, uid=body.user_id, reason=body.reason, last_day=body.last_day,
        notice_given=body.notice_given, rehire=body.rehire, note=body.note,
        by=user["name"])
    if body.close_now:
        shut = close_access(con, body.user_id, user["name"])
        con.execute(
            "UPDATE departures SET access_closed_at=?, access_closed_by=?,"
            " access_detail=? WHERE id=?",
            (time.time(), user["name"], ", ".join(shut["did"]), out["id"]))
        con.commit()
        out["access"] = shut["did"]
    return out


@router.post("/api/onboarding/departures/{did}/close-access")
def departure_close(did: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    d = con.execute("SELECT * FROM departures WHERE id=?", (did,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such departure")
    if d["access_closed_at"]:
        raise HTTPException(400, "already closed — "
                                 + (d["access_detail"] or "nothing to do"))
    shut = close_access(con, d["user_id"], user["name"])
    con.execute(
        "UPDATE departures SET access_closed_at=?, access_closed_by=?,"
        " access_detail=? WHERE id=?",
        (time.time(), user["name"], ", ".join(shut["did"]), did))
    con.commit()
    return {"ok": True, "did": shut["did"]}


class RehireBody(BaseModel):
    rehire: str = "unknown"
    note: str = ""


@router.patch("/api/onboarding/departures/{did}")
def departure_edit(did: int, body: RehireBody, user=Depends(current_user),
                   con=Depends(get_con)):
    """The note and whether they would be taken back. The reason and the
    date are not editable: they are what was decided on the day."""
    _require(user)
    if body.rehire not in ("yes", "no", "unknown"):
        raise HTTPException(400, "rehire is yes, no or unknown")
    con.execute("UPDATE departures SET rehire=?, note=? WHERE id=?",
                (body.rehire, body.note[:2000], did))
    con.commit()
    return {"ok": True}
