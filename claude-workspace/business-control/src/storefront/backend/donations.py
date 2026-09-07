"""Donations, which are not a sale.

The obvious way to take a donation in a shop is a £5 product called
"Donation", and it is wrong in a way that does not show up for months. It
lands in cost of goods with no cost basis, in stock as a thing that never
arrives, in taxable revenue, in average order value, in repeat rate, in
every cohort — and by the time an accountant asks why turnover is up and
margin is down, a year of numbers has been quietly wrong.

So a donation is its own column on the order, in the total because it is
charged, and out of revenue everywhere revenue is claimed.

The second thing that is not obvious: whose money it is. Two shops take
donations at checkout and they are keeping different books.

  ours       a charity taking its own donations. This is income. The
             donor may want a receipt with the charity's number on it.

  collected  a shop raising money for somebody else. This is NOT income
             and never was. It is money held on trust, a liability from
             the moment it is taken until it is sent on, and somebody
             has to be able to say what was collected and what went.

That is why a fund has a kind, and why collected funds carry a
remittance ledger. "We raised £4,000 for the hospice" is a sentence a
shop should be able to prove, and "£3,200 sent, £800 still with us" is
the sentence that keeps it true.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .api import admin_user, get_con

router = APIRouter()

KINDS = ("ours", "collected")

TABLES = """
CREATE TABLE IF NOT EXISTS donation_funds (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'collected'   -- ours | collected
    CHECK (kind IN ('ours','collected')),
  blurb TEXT DEFAULT '',                   -- what the shopper is told
  payee TEXT DEFAULT '',                   -- who it goes to, for collected
  reference TEXT DEFAULT '',               -- charity number, if there is one
  target_cents INTEGER DEFAULT 0,          -- 0 = no thermometer
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);

/* Money held on trust leaving again. Only meaningful for a collected
   fund: money that was ours all along is not remitted anywhere. */
CREATE TABLE IF NOT EXISTS donation_remittances (
  id INTEGER PRIMARY KEY,
  fund_id INTEGER NOT NULL,
  cents INTEGER NOT NULL,
  sent_at REAL NOT NULL,
  reference TEXT DEFAULT '',               -- their receipt, our payment ref
  note TEXT DEFAULT '',
  by_user INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS dr_fund ON donation_remittances(fund_id, sent_at);

/* The donor's own copy, at an address they can keep. Token-addressed
   because an order id is guessable by counting, and this one carries a
   name and an amount. */
CREATE TABLE IF NOT EXISTS donation_receipts (
  order_id INTEGER PRIMARY KEY,
  token TEXT UNIQUE NOT NULL,
  fund_id INTEGER NOT NULL,
  cents INTEGER NOT NULL,
  donor TEXT DEFAULT '',
  email TEXT DEFAULT '',
  issued_at REAL NOT NULL,
  emailed_at REAL DEFAULT 0
);
"""


def init_tables(con) -> None:
    con.executescript(TABLES)


def active_fund(con):
    """The fund a checkout should offer, or None.

    One at a time. A checkout asking which of four charities is a
    checkout asking a question nobody came to answer.
    """
    return con.execute(
        "SELECT * FROM donation_funds WHERE active=1 ORDER BY id"
    ).fetchone()


def totals(con, fund_id: int) -> dict:
    """Taken, sent on, and still here."""
    got = con.execute(
        "SELECT COALESCE(SUM(donation_cents),0) AS c, COUNT(*) AS n"
        " FROM orders WHERE donation_fund_id=? AND status!='cancelled'",
        (fund_id,)).fetchone()
    sent = con.execute(
        "SELECT COALESCE(SUM(cents),0) AS c FROM donation_remittances"
        " WHERE fund_id=?", (fund_id,)).fetchone()
    return {"raised_cents": got["c"], "gifts": got["n"],
            "remitted_cents": sent["c"],
            "held_cents": max(0, got["c"] - sent["c"])}


def issue_receipt(con, order_id: int, fund_id: int, cents: int,
                  donor: str = "", email: str = "") -> str:
    """Mint the donor's copy. Returns the token, or '' if it could not.

    Never fatal: a gift that was taken and a receipt that failed to
    generate is a bookkeeping problem, and losing the gift to fix it
    would be a worse one.
    """
    if not (order_id and fund_id and cents > 0):
        return ""
    try:
        import secrets
        row = con.execute("SELECT token FROM donation_receipts"
                          " WHERE order_id=?", (order_id,)).fetchone()
        if row:
            return row["token"]
        tok = secrets.token_urlsafe(18)
        con.execute(
            "INSERT INTO donation_receipts(order_id,token,fund_id,cents,"
            "donor,email,issued_at) VALUES(?,?,?,?,?,?,?)",
            (order_id, tok, fund_id, cents, (donor or "")[:80],
             (email or "")[:120], time.time()))
        con.commit()
        return tok
    except Exception:                                        # noqa: BLE001
        return ""


def receipt_lines(fund, cents: int, donor: str, when: float,
                  shop: str) -> dict:
    """What a donation receipt may honestly say.

    This is the whole of the thinking. A charity taking its own donations
    issues a tax receipt: its name, its number, and the line a tax office
    looks for — that nothing was received in return.

    A shop collecting for a hospice is not the hospice. It cannot issue a
    tax receipt on somebody else's behalf, and a document that looked
    like one would be the shop making a claim it has no standing to
    make — the kind of mistake that is discovered by a tax office rather
    than by an accountant. So what it issues is an acknowledgement: you
    gave this much, through us, and it is going there. Anybody who needs
    a tax receipt has to get it from the charity, and the paper says so
    rather than leaving them to find out.
    """
    ours = fund["kind"] == "ours"
    return {
        "title": "Donation receipt" if ours else "Thank you for giving",
        "issuer": shop,
        "for": fund["name"],
        "payee": "" if ours else (fund["payee"] or ""),
        "reference": fund["reference"] or "",
        "cents": cents, "donor": donor, "at": when,
        "tax_receipt": bool(ours),
        "statement": (
            "No goods or services were provided in return for this "
            "donation." if ours else
            f"This is an acknowledgement, not a tax receipt. "
            f"{shop} collected this on behalf of "
            f"{fund['payee'] or 'the named cause'} and is not the "
            f"charity — anything you need for tax has to come from "
            f"them."),
    }


# ---------- what the shop asks ----------

@router.get("/api/store/donation")
def offer(con=Depends(get_con)):
    """What the checkout should say, if anything."""
    f = active_fund(con)
    if f is None:
        return {"fund": None}
    t = totals(con, f["id"])
    return {"fund": {
        "id": f["id"], "name": f["name"], "blurb": f["blurb"],
        "payee": f["payee"], "kind": f["kind"],
        "target_cents": f["target_cents"],
        # The thermometer is what was RAISED, not what is still held —
        # a total that fell when the money was sent on would read as
        # donations being taken back.
        "raised_cents": t["raised_cents"],
        "note": ("Collected for " + f["payee"] if f["kind"] == "collected"
                 and f["payee"] else ""),
    }}


# ---------- what the shop's owner runs ----------

class FundBody(BaseModel):
    name: str = ""
    kind: str = "collected"
    blurb: str = ""
    payee: str = ""
    reference: str = ""
    target_cents: int = 0
    active: bool = True


@router.get("/api/store/admin/donations")
def list_funds(user=Depends(admin_user), con=Depends(get_con)):
    rows = []
    for f in con.execute("SELECT * FROM donation_funds ORDER BY id"):
        d = dict(f)
        d.update(totals(con, f["id"]))
        d["remittances"] = [dict(r) for r in con.execute(
            "SELECT * FROM donation_remittances WHERE fund_id=?"
            " ORDER BY sent_at DESC LIMIT 12", (f["id"],))]
        rows.append(d)
    return {
        "funds": rows, "kinds": list(KINDS),
        "note": "Donations are never revenue. Money collected for "
                "somebody else is not income at all — it is held on "
                "trust from the moment it is taken until it is sent on, "
                "which is why those funds carry a remittance ledger and "
                "a figure for what is still here.",
    }


@router.post("/api/store/admin/donations")
def add_fund(body: FundBody, user=Depends(admin_user), con=Depends(get_con)):
    if not body.name.strip():
        raise HTTPException(400, "a fund needs a name")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {KINDS}")
    if body.kind == "collected" and not body.payee.strip():
        raise HTTPException(
            400, "money collected for somebody else has to say who. It is "
                 "not income and somebody will have to prove where it "
                 "went.")
    if body.active:
        con.execute("UPDATE donation_funds SET active=0")
    cur = con.execute(
        "INSERT INTO donation_funds(name,kind,blurb,payee,reference,"
        "target_cents,active,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (body.name.strip()[:80], body.kind, body.blurb.strip()[:300],
         body.payee.strip()[:120], body.reference.strip()[:80],
         max(0, body.target_cents), 1 if body.active else 0, time.time()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.patch("/api/store/admin/donations/{fid}")
def edit_fund(fid: int, body: FundBody, user=Depends(admin_user),
              con=Depends(get_con)):
    f = con.execute("SELECT * FROM donation_funds WHERE id=?",
                    (fid,)).fetchone()
    if f is None:
        raise HTTPException(404, "no such fund")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {KINDS}")
    if f["kind"] != body.kind and totals(con, fid)["raised_cents"]:
        # Changing whose money it is, after some has been taken, would
        # rewrite history: the same rows would move between income and a
        # liability with nothing recording that they had.
        raise HTTPException(
            409, "money has already been taken for this fund, so whose it "
                 "is cannot change now. Close it and open another.")
    if body.active:
        con.execute("UPDATE donation_funds SET active=0 WHERE id!=?", (fid,))
    con.execute(
        "UPDATE donation_funds SET name=?, kind=?, blurb=?, payee=?,"
        " reference=?, target_cents=?, active=? WHERE id=?",
        (body.name.strip()[:80] or f["name"], body.kind,
         body.blurb.strip()[:300], body.payee.strip()[:120],
         body.reference.strip()[:80], max(0, body.target_cents),
         1 if body.active else 0, fid))
    con.commit()
    return {"ok": True}


class RemitBody(BaseModel):
    cents: int = 0
    reference: str = ""
    note: str = ""


@router.post("/api/store/admin/donations/{fid}/remit")
def remit(fid: int, body: RemitBody, user=Depends(admin_user),
          con=Depends(get_con)):
    """Record money sent on to whoever it was collected for."""
    f = con.execute("SELECT * FROM donation_funds WHERE id=?",
                    (fid,)).fetchone()
    if f is None:
        raise HTTPException(404, "no such fund")
    if f["kind"] != "collected":
        raise HTTPException(
            400, "this fund's money is the business's own, so there is "
                 "nobody to send it to. A remittance here would be an "
                 "invented transaction.")
    if body.cents <= 0:
        raise HTTPException(400, "an amount, please")
    held = totals(con, fid)["held_cents"]
    if body.cents > held:
        raise HTTPException(
            409, f"that is more than is being held. {held / 100:.2f} came "
                 f"in and has not gone out — sending more than was "
                 f"collected is either a typo or a different transaction.")
    con.execute(
        "INSERT INTO donation_remittances(fund_id,cents,sent_at,reference,"
        "note,by_user) VALUES(?,?,?,?,?,?)",
        (fid, body.cents, time.time(), body.reference.strip()[:80],
         body.note.strip()[:300], user["id"]))
    con.commit()
    return {"ok": True, **totals(con, fid)}
