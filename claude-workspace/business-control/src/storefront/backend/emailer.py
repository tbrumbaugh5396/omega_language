"""Email campaigns: an audience, a message, and a record of what was sent.

The ERP could already blast a promo to every customer and log the result.
That's a broadcast, not a campaign — it has no audience choice, no reusable
message, and no way to see how one send compared to another.

This adds the three parts that make it a campaign:

  Audiences, defined as a query rather than a list, so "customers who ordered
  in the last 90 days" stays accurate without anyone maintaining a
  spreadsheet.

  Campaigns — a saved subject and body with placeholders, sendable more than
  once, holding its own send history.

  Sends — who it went to, how many delivered, and the orders that followed,
  read from the ledger rather than an open-tracking pixel.

Sending is throttled and off-thread. Every recipient is checked against the
unsubscribe list at send time, not at audience-build time, because the gap
between the two is exactly where an unsubscribe gets ignored.
"""
import json
import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from erp.backend import mailer
from .api import admin_user, get_con

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS email_campaigns (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  audience TEXT DEFAULT 'subscribers',
  discount_code TEXT DEFAULT '',           -- how replies get attributed
  status TEXT DEFAULT 'draft',             -- draft|sent
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS email_sends (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL,
  audience TEXT DEFAULT '',
  recipients INTEGER DEFAULT 0,
  delivered INTEGER DEFAULT 0,
  failed INTEGER DEFAULT 0,
  started_at REAL NOT NULL,
  finished_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS email_unsubscribes (
  email TEXT PRIMARY KEY,
  created_at REAL NOT NULL
);
"""

# name -> (label, SQL returning email + name)
AUDIENCES = {
    "subscribers": (
        "Newsletter subscribers",
        "SELECT email, '' name FROM store_subscribers WHERE email != ''"),
    "customers": (
        "Everyone who has ordered",
        "SELECT DISTINCT u.email, u.name FROM users u"
        " JOIN orders o ON o.user_id=u.id WHERE u.email != ''"),
    "recent_customers": (
        "Ordered in the last 90 days",
        "SELECT DISTINCT u.email, u.name FROM users u"
        " JOIN orders o ON o.user_id=u.id"
        " WHERE u.email != '' AND o.created_at > (strftime('%s','now') - 7776000)"),
    "lapsed": (
        "Ordered once, not in 90 days",
        "SELECT u.email, u.name FROM users u JOIN orders o ON o.user_id=u.id"
        " WHERE u.email != '' GROUP BY u.id"
        " HAVING MAX(o.created_at) < (strftime('%s','now') - 7776000)"),
    "distributors": (
        "Distributors and wholesale",
        "SELECT email, name FROM users WHERE email != ''"
        " AND role='distributor' AND active=1"),
    "affiliates": (
        "Affiliates",
        "SELECT u.email, u.name FROM users u"
        " JOIN affiliates a ON a.user_id=u.id WHERE u.email != ''"),
    "staff": (
        "Staff and owners",
        "SELECT email, name FROM users WHERE email != '' AND active=1"
        " AND (is_admin=1 OR role IN ('employee','owner'))"),
}


def init_tables(con):
    con.executescript(TABLES)


def resolve(con, audience: str) -> list:
    spec = AUDIENCES.get(audience)
    if spec is None:
        raise HTTPException(400, "unknown audience")
    rows = con.execute(spec[1]).fetchall()
    unsub = {r["email"].lower() for r in
             con.execute("SELECT email FROM email_unsubscribes").fetchall()}
    seen, out = set(), []
    for r in rows:
        e = (r["email"] or "").strip().lower()
        if not e or e in seen or e in unsub:
            continue
        seen.add(e)
        out.append({"email": r["email"].strip(), "name": r["name"] or ""})
    return out


def render(text: str, person: dict, extra: dict) -> str:
    out = text
    for k, v in {**extra, "name": person.get("name") or "there",
                 "email": person.get("email", "")}.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# ---------- admin ----------

@router.get("/api/store/admin/email/campaigns")
def list_campaigns(u=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM email_campaigns ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        sends = con.execute(
            "SELECT * FROM email_sends WHERE campaign_id=?"
            " ORDER BY started_at DESC", (r["id"],)).fetchall()
        d["sends"] = [dict(s) for s in sends]
        d["audience_label"] = AUDIENCES.get(r["audience"], ("?",))[0]
        # Orders carrying this campaign's code, from the ledger.
        if r["discount_code"]:
            first = sends[-1]["started_at"] if sends else 0
            row = con.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(total_cents),0) v FROM orders"
                " WHERE UPPER(COALESCE(discount_code,''))=? AND created_at>=?",
                (r["discount_code"].upper(), first)).fetchone()
            d["orders"] = row["n"]
            d["revenue_cents"] = row["v"]
        else:
            d["orders"] = 0
            d["revenue_cents"] = 0
        out.append(d)
    sizes = {}
    for key in AUDIENCES:
        try:
            sizes[key] = len(resolve(con, key))
        except Exception:
            sizes[key] = 0
    return {"campaigns": out,
            "audiences": {k: v[0] for k, v in AUDIENCES.items()},
            "sizes": sizes,
            "unsubscribed": con.execute(
                "SELECT COUNT(*) n FROM email_unsubscribes").fetchone()["n"]}


class CampaignBody(BaseModel):
    name: str
    subject: str
    body: str
    audience: str = "subscribers"
    discount_code: str = ""


@router.post("/api/store/admin/email/campaigns")
def add_campaign(body: CampaignBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    if not body.name.strip() or not body.subject.strip():
        raise HTTPException(400, "a campaign needs a name and a subject")
    if body.audience not in AUDIENCES:
        raise HTTPException(400, "unknown audience")
    cur = con.execute(
        "INSERT INTO email_campaigns(name,subject,body,audience,"
        " discount_code,created_at) VALUES(?,?,?,?,?,?)",
        (body.name.strip()[:120], body.subject.strip()[:160], body.body,
         body.audience,
         re.sub(r"[^A-Za-z0-9_-]", "", body.discount_code)[:40].upper(),
         time.time()))
    con.commit()
    return {"id": cur.lastrowid}


@router.patch("/api/store/admin/email/campaigns/{cid}")
def edit_campaign(cid: int, body: CampaignBody, u=Depends(admin_user),
                  con=Depends(get_con)):
    if body.audience not in AUDIENCES:
        raise HTTPException(400, "unknown audience")
    con.execute(
        "UPDATE email_campaigns SET name=?,subject=?,body=?,audience=?,"
        " discount_code=? WHERE id=?",
        (body.name.strip()[:120], body.subject.strip()[:160], body.body,
         body.audience,
         re.sub(r"[^A-Za-z0-9_-]", "", body.discount_code)[:40].upper(), cid))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/email/campaigns/{cid}")
def del_campaign(cid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM email_campaigns WHERE id=?", (cid,))
    con.commit()
    return {"ok": True}


@router.get("/api/store/admin/email/campaigns/{cid}/preview")
def preview(cid: int, u=Depends(admin_user), con=Depends(get_con)):
    c = con.execute("SELECT * FROM email_campaigns WHERE id=?",
                    (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "no such campaign")
    people = resolve(con, c["audience"])
    sample = people[0] if people else {"name": "Sam", "email": "sam@example.com"}
    extra = {"code": c["discount_code"], "shop": "/"}
    return {"to": sample["email"], "recipients": len(people),
            "subject": render(c["subject"], sample, extra),
            "body": render(c["body"], sample, extra)}


class SendBody(BaseModel):
    test_to: str = ""


@router.post("/api/store/admin/email/campaigns/{cid}/send")
def send_campaign(cid: int, body: SendBody, u=Depends(admin_user),
                  con=Depends(get_con)):
    from erp.backend.main import CFG
    c = con.execute("SELECT * FROM email_campaigns WHERE id=?",
                    (cid,)).fetchone()
    if c is None:
        raise HTTPException(404, "no such campaign")
    extra = {"code": c["discount_code"], "shop": "/"}

    # A test send goes to one address and is not recorded as a send, so a
    # proofread doesn't show up in the campaign's numbers.
    if body.test_to.strip():
        to = body.test_to.strip()
        person = {"name": u["name"], "email": to}
        try:
            mailer.send(CFG, to, "[TEST] " + render(c["subject"], person, extra),
                        render(c["body"], person, extra))
        except Exception as e:                  # noqa: BLE001
            raise HTTPException(400, f"send failed: {e}")
        return {"ok": True, "test": True, "to": to}

    people = resolve(con, c["audience"])
    if not people:
        raise HTTPException(400, "that audience is empty right now")
    cur = con.execute(
        "INSERT INTO email_sends(campaign_id,audience,recipients,started_at)"
        " VALUES(?,?,?,?)", (cid, c["audience"], len(people), time.time()))
    send_id = cur.lastrowid
    con.execute("UPDATE email_campaigns SET status='sent' WHERE id=?", (cid,))
    con.commit()

    subject, tmpl, code = c["subject"], c["body"], c["discount_code"]

    def run():
        from erp.backend import db
        c2 = db.connect()
        ok = bad = 0
        try:
            for person in people:
                try:
                    mailer.send(CFG, person["email"],
                                render(subject, person, {"code": code, "shop": "/"}),
                                render(tmpl, person, {"code": code, "shop": "/"}))
                    ok += 1
                except Exception:
                    bad += 1
                # Gentle pacing. Most SMTP providers rate-limit, and a burst
                # that trips the limit costs more than the seconds saved.
                time.sleep(0.12)
            c2.execute(
                "UPDATE email_sends SET delivered=?, failed=?, finished_at=?"
                " WHERE id=?", (ok, bad, time.time(), send_id))
            c2.commit()
        finally:
            c2.close()
    from erp.backend import tenancy
    threading.Thread(target=tenancy.with_tenant(
        tenancy.CURRENT.get(), run), daemon=True).start()
    return {"ok": True, "send_id": send_id, "recipients": len(people)}


@router.get("/api/store/admin/email/unsubscribes")
def list_unsubs(u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT * FROM email_unsubscribes ORDER BY created_at DESC LIMIT 500")]


# ---------- public ----------

@router.get("/unsubscribe")
def unsubscribe(email: str, con=Depends(get_con)):
    """One click, no login, no confirmation step.

    Every marketing email must carry this link. Making someone sign in to
    stop hearing from you is how a sender ends up in spam folders — and in
    several jurisdictions it isn't optional.
    """
    e = (email or "").strip().lower()
    if e and "@" in e:
        con.execute(
            "INSERT OR IGNORE INTO email_unsubscribes(email,created_at)"
            " VALUES(?,?)", (e, time.time()))
        # The unsubscribe list is the single source of truth — resolve()
        # filters against it, so there's no second flag to keep in sync.
        con.execute("DELETE FROM store_subscribers WHERE lower(email)=?", (e,))
        con.commit()
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<style>body{font-family:system-ui;max-width:520px;margin:80px auto;"
        "padding:0 20px;line-height:1.6;color:#1b181f}</style>"
        "<h1>You're unsubscribed</h1>"
        "<p>We won't email you again about offers. You'll still get order "
        "confirmations and delivery updates, because those are about "
        "something you asked us for.</p>"
        "<p><a href='/'>Back to the shop</a></p>")
