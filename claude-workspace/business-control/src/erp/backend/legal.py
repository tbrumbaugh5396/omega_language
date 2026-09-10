"""Legal: what this business is committed to, and what falls due when.

The document vault already holds contracts, policies and signatures, and
holds them well. What it does not hold is the *obligation* — the fact
that a lease has a ninety-day break clause, that the insurance renews in
March whether or not anyone opens the folder, that the licence has to be
displayed, that the policy was due for review a year ago. A filing
cabinet is not a diary, and every business that has been stung by a
notice period was one that had the contract filed correctly.

So this is the register above the cabinet:

  * A **matter** — a contract, a policy, a licence, a filing, a dispute —
    with the counterparty, the dates that matter, and a link to the
    document if one has been filed.
  * The **obligations** under it, each with a date and, where it repeats,
    how often. Renewals generate the next one when you mark the last done.
  * A **diary** of everything falling due, which is the screen this
    exists for.

Two deliberate limits, stated rather than discovered.

**Notice periods are counted backwards from the end date, and that is
the whole of the cleverness.** A contract that renews unless cancelled
ninety days out produces a "decide by" date ninety days before it ends.
It does not read the contract to find that number; somebody types it.

**Nothing here is advice.** It records what somebody decided the business
must do. It does not know your jurisdiction, and a register that seemed
to imply otherwise would be worse than no register.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS legal_matters (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'contract',   -- see KINDS
  title TEXT NOT NULL,
  counterparty TEXT DEFAULT '',
  reference TEXT DEFAULT '',               -- their number for it
  jurisdiction TEXT DEFAULT '',
  document_id INTEGER DEFAULT 0,           -- the vault, where it is filed
  owner_id INTEGER DEFAULT 0,              -- who answers for it here
  starts REAL DEFAULT 0,
  ends REAL DEFAULT 0,                     -- 0 = open ended
  notice_days INTEGER DEFAULT 0,           -- warn this far before it ends
  renews TEXT DEFAULT 'none',              -- none|auto|manual
  value_cents INTEGER DEFAULT 0,           -- what it is worth or costs
  value_period TEXT DEFAULT '',            -- once|monthly|yearly
  status TEXT DEFAULT 'active',            -- draft|active|expired|ended|disputed
  risk TEXT DEFAULT 'normal',              -- low|normal|high
  note TEXT DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS legal_matters_ends ON legal_matters(ends);

CREATE TABLE IF NOT EXISTS legal_obligations (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER DEFAULT 0,             -- 0 = a standing duty of its own
  what TEXT NOT NULL,
  detail TEXT DEFAULT '',
  due REAL NOT NULL,
  every_months INTEGER DEFAULT 0,          -- 0 = once
  owner_id INTEGER DEFAULT 0,
  done_at REAL DEFAULT 0,
  done_by TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS legal_obligations_due ON legal_obligations(due);
"""

KINDS = {
    "contract": "Contract or agreement",
    "policy": "Policy we publish or follow",
    "licence": "Licence, permit or registration",
    "filing": "Something we must file",
    "insurance": "Insurance",
    "ip": "Trade mark, domain or other IP",
    "dispute": "Dispute or claim",
    "other": "Other",
}
STATUSES = ("draft", "active", "expired", "ended", "disputed")
RISKS = ("low", "normal", "high")
RENEWS = ("none", "auto", "manual")
SOON_DAYS = 60


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    """The register is the office's, and `documents` is the grant that
    already means 'may see the contracts'."""
    return auth.office(user, "settings", "documents")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "the register is the office's")


def _add_months(ts: float, months: int) -> float:
    """Calendar months, not thirty-day blocks. A quarterly filing due on
    the 31st is due on the 30th of a short month, not two days into the
    next one."""
    t = time.localtime(ts)
    y, m = t.tm_year, t.tm_mon + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    day = t.tm_mday
    while day > 28:
        try:
            return time.mktime((y, m, day, t.tm_hour, t.tm_min, 0, 0, 0, -1))
        except (ValueError, OverflowError):
            day -= 1
    return time.mktime((y, m, day, t.tm_hour, t.tm_min, 0, 0, 0, -1))


def decide_by(m) -> float:
    """When a decision has to be made about a matter that ends. Zero when
    there is nothing to decide."""
    if not m["ends"] or not m["notice_days"]:
        return 0.0
    return m["ends"] - m["notice_days"] * 86400


def shape(con, r) -> dict:
    d = dict(r)
    d["kind_label"] = KINDS.get(d["kind"], d["kind"])
    d["decide_by"] = decide_by(r)
    now = time.time()
    d["days_to_end"] = int((d["ends"] - now) // 86400) if d["ends"] else None
    d["days_to_decide"] = (int((d["decide_by"] - now) // 86400)
                           if d["decide_by"] else None)
    # The flag the screen sorts on: a decision inside its notice period,
    # or an end inside the next two months.
    d["needs_attention"] = bool(
        (d["decide_by"] and d["decide_by"] <= now + SOON_DAYS * 86400)
        or (d["ends"] and d["ends"] <= now + SOON_DAYS * 86400)
    ) and d["status"] in ("active", "draft")
    return d


def diary(con, days: int = 180) -> list:
    """Everything falling due, from both tables, in one list. The whole
    point of the capability: a lease break and a licence renewal are the
    same kind of problem and belong on one page."""
    now = time.time()
    horizon = now + days * 86400
    out = []
    for r in con.execute(
            "SELECT * FROM legal_obligations WHERE done_at=0 AND due<=?"
            " ORDER BY due", (horizon,)).fetchall():
        m = con.execute("SELECT title FROM legal_matters WHERE id=?",
                        (r["matter_id"],)).fetchone() if r["matter_id"] else None
        out.append({"kind": "obligation", "id": r["id"], "at": r["due"],
                    "what": r["what"], "matter_id": r["matter_id"],
                    "matter": m["title"] if m else "",
                    "overdue": r["due"] < now,
                    "every_months": r["every_months"]})
    for r in con.execute(
            "SELECT * FROM legal_matters WHERE status IN ('active','draft')"
            " AND ends>0").fetchall():
        d = decide_by(r)
        if d and d <= horizon:
            out.append({"kind": "decide", "id": r["id"], "at": d,
                        "what": f"Decide on {r['title']}"
                                + (" — it renews on its own"
                                   if r["renews"] == "auto" else ""),
                        "matter_id": r["id"], "matter": r["title"],
                        "overdue": d < now, "every_months": 0})
        if r["ends"] <= horizon:
            out.append({"kind": "ends", "id": r["id"], "at": r["ends"],
                        "what": f"{r['title']} ends",
                        "matter_id": r["id"], "matter": r["title"],
                        "overdue": r["ends"] < now, "every_months": 0})
    out.sort(key=lambda x: x["at"])
    return out


def complete(con, oid: int, by: str) -> dict:
    """Mark an obligation done, and open the next one where it repeats.
    Generating the next only on completion is deliberate: a diary that
    pre-creates a year of rows is a diary of things nobody has looked at
    yet, and the overdue count stops meaning anything."""
    r = con.execute("SELECT * FROM legal_obligations WHERE id=?",
                    (oid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such obligation")
    if r["done_at"]:
        raise HTTPException(400, "that one is already done")
    now = time.time()
    con.execute("UPDATE legal_obligations SET done_at=?, done_by=? WHERE id=?",
                (now, by[:120], oid))
    nxt = 0
    if r["every_months"]:
        nxt = con.execute(
            "INSERT INTO legal_obligations(matter_id,what,detail,due,"
            " every_months,owner_id,created_at) VALUES(?,?,?,?,?,?,?)",
            (r["matter_id"], r["what"], r["detail"],
             _add_months(r["due"], r["every_months"]), r["every_months"],
             r["owner_id"], db.now())).lastrowid
    con.commit()
    return {"ok": True, "next_id": nxt}


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/legal")
def legal_page(user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    matters = [shape(con, r) for r in con.execute(
        "SELECT * FROM legal_matters ORDER BY (status='active') DESC,"
        " ends, title").fetchall()]
    d = diary(con)
    now = time.time()
    return {
        "matters": matters, "diary": d,
        "kinds": [{"k": k, "label": v} for k, v in KINDS.items()],
        "statuses": list(STATUSES), "risks": list(RISKS),
        "renews": list(RENEWS),
        "counts": {
            "active": sum(1 for m in matters if m["status"] == "active"),
            "attention": sum(1 for m in matters if m["needs_attention"]),
            "overdue": sum(1 for x in d if x["overdue"]),
            "high_risk": sum(1 for m in matters
                             if m["risk"] == "high" and m["status"] == "active"),
        },
        "obligations": [dict(r) for r in con.execute(
            "SELECT * FROM legal_obligations ORDER BY done_at, due"
            " LIMIT 300").fetchall()],
        "now": now,
    }


class MatterBody(BaseModel):
    id: int = 0
    kind: str = "contract"
    title: str
    counterparty: str = ""
    reference: str = ""
    jurisdiction: str = ""
    document_id: int = 0
    owner_id: int = 0
    starts: float = 0
    ends: float = 0
    notice_days: int = 0
    renews: str = "none"
    value_cents: int = 0
    value_period: str = ""
    status: str = "active"
    risk: str = "normal"
    note: str = ""


@router.post("/api/legal/matters")
def matter_save(body: MatterBody, user=Depends(current_user),
                con=Depends(get_con)):
    _require(user)
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {sorted(KINDS)}")
    if body.status not in STATUSES:
        raise HTTPException(400, f"status is one of {STATUSES}")
    if body.risk not in RISKS:
        raise HTTPException(400, f"risk is one of {RISKS}")
    if body.renews not in RENEWS:
        raise HTTPException(400, f"renews is one of {RENEWS}")
    if not body.title.strip():
        raise HTTPException(400, "a matter needs a title")
    if body.ends and body.starts and body.ends < body.starts:
        raise HTTPException(400, "it cannot end before it starts")
    if body.notice_days and not body.ends:
        raise HTTPException(400, "a notice period counts back from an end "
                                 "date, so it needs one")
    if body.notice_days < 0 or body.notice_days > 3650:
        raise HTTPException(400, "that notice period is not a number of days")
    now = time.time()
    args = (body.kind, body.title.strip()[:200], body.counterparty.strip()[:160],
            body.reference.strip()[:80], body.jurisdiction.strip()[:80],
            body.document_id, body.owner_id, body.starts, body.ends,
            body.notice_days, body.renews, body.value_cents,
            body.value_period[:20], body.status, body.risk,
            body.note.strip()[:2000])
    if body.id:
        if con.execute("SELECT 1 FROM legal_matters WHERE id=?",
                       (body.id,)).fetchone() is None:
            raise HTTPException(404, "no such matter")
        con.execute(
            "UPDATE legal_matters SET kind=?, title=?, counterparty=?,"
            " reference=?, jurisdiction=?, document_id=?, owner_id=?, starts=?,"
            " ends=?, notice_days=?, renews=?, value_cents=?, value_period=?,"
            " status=?, risk=?, note=?, updated_at=? WHERE id=?",
            args + (now, body.id))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO legal_matters(kind,title,counterparty,reference,"
        " jurisdiction,document_id,owner_id,starts,ends,notice_days,renews,"
        " value_cents,value_period,status,risk,note,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", args + (db.now(), now))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


class ObligationBody(BaseModel):
    id: int = 0
    matter_id: int = 0
    what: str
    detail: str = ""
    due: float
    every_months: int = 0
    owner_id: int = 0


@router.post("/api/legal/obligations")
def obligation_save(body: ObligationBody, user=Depends(current_user),
                    con=Depends(get_con)):
    _require(user)
    if not body.what.strip():
        raise HTTPException(400, "say what has to be done")
    if not body.due:
        raise HTTPException(400, "and when")
    if body.every_months < 0 or body.every_months > 120:
        raise HTTPException(400, "repeat every 1 to 120 months, or not at all")
    if body.matter_id and con.execute(
            "SELECT 1 FROM legal_matters WHERE id=?",
            (body.matter_id,)).fetchone() is None:
        raise HTTPException(404, "no such matter")
    args = (body.matter_id, body.what.strip()[:200], body.detail.strip()[:2000],
            body.due, body.every_months, body.owner_id)
    if body.id:
        con.execute(
            "UPDATE legal_obligations SET matter_id=?, what=?, detail=?, due=?,"
            " every_months=?, owner_id=? WHERE id=?", args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO legal_obligations(matter_id,what,detail,due,every_months,"
        " owner_id,created_at) VALUES(?,?,?,?,?,?,?)", args + (db.now(),))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.post("/api/legal/obligations/{oid}/done")
def obligation_done(oid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    return complete(con, oid, user["name"])


@router.delete("/api/legal/obligations/{oid}")
def obligation_delete(oid: int, user=Depends(current_user),
                      con=Depends(get_con)):
    _require(user)
    con.execute("DELETE FROM legal_obligations WHERE id=?", (oid,))
    con.commit()
    return {"ok": True}
