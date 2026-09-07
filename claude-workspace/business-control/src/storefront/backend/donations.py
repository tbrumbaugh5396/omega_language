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
from .api import current_customer as _customer

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


def receipt_email(fund, cents: int, donor: str, shop: str,
                  url: str) -> tuple:
    """Subject and body for the donor's copy.

    Says the same thing the page says, because a receipt that disagrees
    with its own email is worse than one that was never sent. The
    collected case still refuses to be a tax receipt — the wording is not
    softer in an email because nobody is reading it over somebody's
    shoulder.
    """
    amount = f"{cents / 100:.2f}"
    if fund["kind"] == "ours":
        return (f"Your donation receipt — {shop}",
                f"Hi {donor or 'there'},\n\n"
                f"Thank you for giving {amount} to {fund['name']}.\n\n"
                f"Your receipt: {url}\n\n"
                "No goods or services were provided in return for this "
                "donation"
                + (f", and our registered number is {fund['reference']}"
                   if fund["reference"] else "")
                + ".\n\nKeep the link — it is your copy, and it will "
                  "still be there when you need it.")
    payee = fund["payee"] or "the cause"
    return (f"Thank you for giving to {payee}",
            f"Hi {donor or 'there'},\n\n"
            f"Thank you for the {amount} you gave through {shop} for "
            f"{payee}.\n\n"
            f"Your acknowledgement: {url}\n\n"
            f"This is not a tax receipt. {shop} collected this on behalf "
            f"of {payee} and is not the charity, so anything you need for "
            f"tax has to come from them directly.\n\nKeep the link — it "
            "is your copy.")


def mark_emailed(con, token: str) -> None:
    try:
        con.execute("UPDATE donation_receipts SET emailed_at=?"
                    " WHERE token=?", (time.time(), token))
        con.commit()
    except Exception:                                        # noqa: BLE001
        pass


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


@router.get("/api/store/account/donations")
def my_donations(con=Depends(get_con), user=Depends(_customer)):
    """Everything one person has given here, and their own copies.

    Two totals, not one, and they are kept apart for the same reason the
    receipts are. What somebody gave to this business, if it is a charity
    taking its own donations, is a figure a tax office will accept from
    us. What they gave THROUGH us for a hospice is not ours to certify —
    we handled it, we did not receive it, and adding the two into a
    single "you have given" number would be quietly overstating what we
    are able to stand behind.

    So: given to us, given through us, and a year-by-year split, because
    a tax year is the unit anybody asking this question is working in.
    """
    rows = [dict(r) for r in con.execute(
        "SELECT o.id AS order_id, o.donation_cents AS cents,"
        " o.created_at, f.name AS fund, f.kind, f.payee, f.reference,"
        " COALESCE(dr.token,'') AS token"
        " FROM orders o JOIN donation_funds f ON f.id=o.donation_fund_id"
        " LEFT JOIN donation_receipts dr ON dr.order_id=o.id"
        " WHERE o.user_id=? AND o.donation_cents>0"
        " AND o.status!='cancelled' ORDER BY o.created_at DESC",
        (user["id"],))]
    to_us = sum(r["cents"] for r in rows if r["kind"] == "ours")
    through = sum(r["cents"] for r in rows if r["kind"] != "ours")
    years: dict = {}
    for r in rows:
        y = time.strftime("%Y", time.localtime(r["created_at"]))
        b = years.setdefault(y, {"year": y, "to_us_cents": 0,
                                 "through_us_cents": 0, "gifts": 0})
        b["gifts"] += 1
        b["to_us_cents" if r["kind"] == "ours"
          else "through_us_cents"] += r["cents"]
        r["receipt_url"] = f"/dr/{r['token']}" if r["token"] else ""
        r["tax_receipt"] = r["kind"] == "ours"
        r.pop("token", None)
    return {
        "gifts": rows, "to_us_cents": to_us, "through_us_cents": through,
        "years": sorted(years.values(), key=lambda x: x["year"],
                        reverse=True),
        "note": ("What you gave to us and what you gave through us are "
                 "listed apart. Money we collected for somebody else was "
                 "handled by us and received by them, so a receipt for "
                 "it has to come from them — ours is an acknowledgement "
                 "and says so."),
    }


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


@router.get("/api/store/admin/donations/trend")
def trend(months: int = 12, fund_id: int = 0, user=Depends(admin_user),
          con=Depends(get_con)):
    """Giving month by month.

    Calendar months, not thirty-day blocks. Stepping by thirty days
    prints one month twice and skips February, and a series that cannot
    count months is one nobody should trust with the shape it draws.

    The month in progress is marked as such. Half of September against
    the whole of August always looks like a collapse, and a shop that
    reads one of those on the seventh will conclude that giving has
    stopped rather than that the month has.
    """
    months = max(1, min(36, months))
    now = time.time()
    lt = time.localtime(now)
    buckets, keys = [], []
    y, m = lt.tm_year, lt.tm_mon
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    where = " AND o.donation_fund_id=?" if fund_id else ""
    args = [keys[0] + "-01"] + ([fund_id] if fund_id else [])
    rows = con.execute(
        "SELECT strftime('%Y-%m', o.created_at, 'unixepoch', 'localtime')"
        " AS mon, COUNT(*) AS gifts,"
        " COALESCE(SUM(o.donation_cents),0) AS cents,"
        " COALESCE(MAX(o.donation_cents),0) AS biggest,"
        " COUNT(DISTINCT o.user_id) AS givers"
        " FROM orders o WHERE o.donation_cents>0"
        " AND o.status!='cancelled'"
        " AND date(o.created_at,'unixepoch','localtime')>=date(?)"
        + where + " GROUP BY mon", args).fetchall()
    got = {r["mon"]: dict(r) for r in rows}
    this_month = f"{lt.tm_year:04d}-{lt.tm_mon:02d}"
    for k in keys:
        b = got.get(k) or {"gifts": 0, "cents": 0, "biggest": 0,
                           "givers": 0}
        buckets.append({
            "month": k, "gifts": b["gifts"], "cents": b["cents"],
            "givers": b["givers"], "biggest_cents": b["biggest"],
            "average_cents": round(b["cents"] / b["gifts"]) if b["gifts"]
            else 0,
            "partial": k == this_month,
        })
    done = [b for b in buckets if not b["partial"] and b["gifts"]]
    return {
        "months": buckets, "fund_id": fund_id,
        "total_cents": sum(b["cents"] for b in buckets),
        # Best month excludes the one still running, for the same reason
        # it is marked: a month three days old cannot win and should not
        # be allowed to lose either.
        "best": max(done, key=lambda b: b["cents"])["month"] if done else "",
        "note": "Calendar months, and the one still running is marked. "
                "Half of a month against the whole of the last always "
                "looks like a collapse, and it is the calendar rather "
                "than the giving.",
    }


@router.get("/api/store/admin/donations/{fid}/gifts")
def fund_gifts(fid: int, user=Depends(admin_user), con=Depends(get_con)):
    """Who gave to this fund, and what.

    The shop's own customers and its own orders, so nothing here is data
    it did not already hold — this is the same list, gathered by the
    thing it was given to rather than by the basket it rode in on.

    The email is included because staff answer the phone: a donor who
    has lost their copy is identified by the address it went to, and
    making somebody cross-reference an order id to do that is how they
    stop bothering.
    """
    f = con.execute("SELECT * FROM donation_funds WHERE id=?",
                    (fid,)).fetchone()
    if f is None:
        raise HTTPException(404, "no such fund")
    rows = [dict(r) for r in con.execute(
        "SELECT o.id AS order_id, o.donation_cents AS cents, o.created_at,"
        " COALESCE(dr.donor,'') AS donor, COALESCE(dr.email,'') AS email,"
        " COALESCE(dr.token,'') AS token,"
        " COALESCE(dr.emailed_at,0) AS emailed_at"
        " FROM orders o LEFT JOIN donation_receipts dr ON dr.order_id=o.id"
        " WHERE o.donation_fund_id=? AND o.donation_cents>0"
        " AND o.status!='cancelled' ORDER BY o.created_at DESC LIMIT 500",
        (fid,))]
    for r in rows:
        r["receipt_url"] = f"/dr/{r['token']}" if r["token"] else ""
        r.pop("token", None)
    givers = len({r["email"] or f"o{r['order_id']}" for r in rows})
    out = {"fund": f["name"], "kind": f["kind"], "payee": f["payee"],
           "gifts": rows, "givers": givers,
           "total_cents": sum(r["cents"] for r in rows)}
    if f["kind"] == "collected":
        # Worth saying where somebody is most likely to be about to do
        # it. The donor gave at this shop's checkout; they did not join
        # the charity's mailing list, and the two are different acts even
        # though the money went the same way.
        out["passing_it_on"] = (
            f"These people gave at your checkout, not to "
            f"{f['payee'] or 'the cause'}. Sending the money on is what "
            f"you undertook to do; sending the list is a separate "
            f"decision, and it is theirs rather than yours.")
    return out


@router.get("/api/store/admin/donations/{fid}/gifts.csv")
def fund_gifts_csv(fid: int, user=Depends(admin_user),
                   con=Depends(get_con)):
    """The same list, as a file.

    Without the receipt links. Every other column here is already in the
    orders export, but a receipt URL is the donor's private address for
    their own document — it needs no password, which is what makes it
    convenient and what makes it exactly the wrong thing to put in a
    spreadsheet that gets emailed to a committee. Staff who need one open
    it from the screen, where the reading is deliberate and one at a
    time.

    The export is recorded, because handing a list of named people to a
    file is a disclosure whether or not anybody meant it as one.
    """
    import csv
    import io

    from fastapi import Response

    from erp.backend import audit

    f = con.execute("SELECT * FROM donation_funds WHERE id=?",
                    (fid,)).fetchone()
    if f is None:
        raise HTTPException(404, "no such fund")
    rows = con.execute(
        "SELECT o.id, o.created_at, o.donation_cents,"
        " COALESCE(dr.donor,'') AS donor, COALESCE(dr.email,'') AS email,"
        " COALESCE(dr.emailed_at,0) AS emailed_at"
        " FROM orders o LEFT JOIN donation_receipts dr ON dr.order_id=o.id"
        " WHERE o.donation_fund_id=? AND o.donation_cents>0"
        " AND o.status!='cancelled' ORDER BY o.created_at",
        (fid,)).fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["given_on", "donor", "email", "amount", "order_id",
                "receipt_sent"])
    for r in rows:
        w.writerow([
            time.strftime("%Y-%m-%d", time.localtime(r["created_at"])),
            r["donor"], r["email"], f"{r['donation_cents'] / 100:.2f}",
            r["id"], "yes" if r["emailed_at"] else "no"])
    slug = "".join(ch if ch.isalnum() else "-"
                   for ch in (f["name"] or "fund").lower()).strip("-")[:40]
    day = time.strftime("%Y-%m-%d")
    audit.record(con, user, "GET",
                 f"/api/store/admin/donations/{fid}/gifts.csv",
                 f"exported {len(rows)} donor(s) for {f['name']}", 200)
    return Response(
        out.getvalue(), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="{slug}-donors-{day}.csv"'})


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
