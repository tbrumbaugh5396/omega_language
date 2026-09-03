"""Recurring revenue: what it is, and how it moved.

A subscription table can answer "what do we bill this month". It cannot
answer "did we grow", because growth is a difference between two months
and the table only ever holds today. So the answer is recorded: one row
per paying account per month, written as the month is lived and frozen
once it is over.

Everything else falls out of comparing consecutive months, account by
account:

    in this month, not the last     new (or reactivated, if we knew them)
    in both, paying more            expansion
    in both, paying less            contraction
    in the last, not this           churned

Those four add up to the change in MRR exactly, which is the point — a
growth number nobody can decompose is a number nobody acts on. Net
revenue retention is the same arithmetic restricted to accounts that were
already here: expansion minus contraction minus churn, over what they
were paying. Above 100% means the business grows without a single new
customer, and it is the one number that says whether what you sell keeps
being worth its price.

Two sources of recurring money, deduplicated by tenant:

  * store_subscriptions — sold through the shop, billed by the processor,
    carrying the price THAT subscriber agreed to rather than today's list
    price, because the price book grandfathers existing clients.
  * engagements.monthly_cents — clients invoiced directly, never through
    a checkout. Real money, and invisible to anything reading only the
    subscriptions table.
"""
import time

DAY = 86400

TABLES = """
CREATE TABLE IF NOT EXISTS mrr_month (
  month TEXT NOT NULL,                     -- YYYY-MM
  account TEXT NOT NULL,                   -- u<user_id> | e<engagement_id>
  cents INTEGER NOT NULL DEFAULT 0,
  label TEXT DEFAULT '',
  origin TEXT DEFAULT 'live',              -- live | backfill
  taken_at REAL NOT NULL,
  PRIMARY KEY (month, account)
);
CREATE INDEX IF NOT EXISTS mrr_month_m ON mrr_month(month);
"""


def init_tables(con):
    con.executescript(TABLES)
    # Installs that recorded a month before the column existed: the rows
    # are live ones, which is the default, so nothing needs restating.
    cols = {r["name"] for r in con.execute("PRAGMA table_info(mrr_month)")}
    if "origin" not in cols:
        con.execute("ALTER TABLE mrr_month ADD COLUMN origin TEXT"
                    " DEFAULT 'live'")
        con.commit()


def month_of(ts: float) -> str:
    return time.strftime("%Y-%m", time.localtime(ts))


def _prev(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def live(con) -> list:
    """Every account paying us something every month, right now.

    Subscriptions first; then engagements whose monthly money is not
    already counted through a subscription of theirs. A client with both
    is one account, not two — double counting is the failure mode that
    makes an MRR chart worse than no chart.
    """
    out = {}
    for r in con.execute(
            "SELECT s.user_id, s.qty, s.price_cents, s.tenant_id,"
            " COALESCE(u.name,'') AS name"
            " FROM store_subscriptions s LEFT JOIN users u ON u.id=s.user_id"
            " WHERE s.status='active' AND s.interval='month'"):
        key = f"u{r['user_id']}"
        got = out.setdefault(key, {"cents": 0, "label": r["name"],
                                   "tenants": set()})
        got["cents"] += (r["price_cents"] or 0) * max(1, r["qty"] or 1)
        if r["tenant_id"]:
            got["tenants"].add(r["tenant_id"])
    billed = {t for v in out.values() for t in v["tenants"]}
    try:
        rows = con.execute(
            "SELECT id, name, monthly_cents, tenant_id FROM engagements"
            " WHERE COALESCE(monthly_cents,0) > 0"
            "  AND COALESCE(status,'') NOT IN ('archived','closed','lost')")
    except Exception:                                        # noqa: BLE001
        rows = []
    for r in rows:
        if r["tenant_id"] and r["tenant_id"] in billed:
            continue                       # already counted at the checkout
        out[f"e{r['id']}"] = {"cents": r["monthly_cents"], "label": r["name"],
                              "tenants": set()}
    return [{"account": k, "cents": int(v["cents"]), "label": v["label"]}
            for k, v in out.items() if v["cents"] > 0]


def snapshot(con, when: float = 0) -> str:
    """Write this month's row for every paying account.

    Idempotent, and only ever writes the CURRENT month: a past month is
    what it was, and a snapshot that rewrites history on every page load
    is not a record of anything. Called on read rather than by a cron so
    that a month is never missed by an install nobody has scheduled.
    """
    when = when or time.time()
    m = month_of(when)
    rows = live(con)
    con.execute("DELETE FROM mrr_month WHERE month=?", (m,))
    con.executemany(
        "INSERT INTO mrr_month(month,account,cents,label,origin,taken_at)"
        " VALUES(?,?,?,?,'live',?)",
        [(m, r["account"], r["cents"], r["label"][:80], when) for r in rows])
    con.commit()
    return m


def backfill(con, months: int = 12, when: float = 0) -> int:
    """Reconstruct the months before anybody was recording.

    Only from what is actually knowable: a subscription's start, and its
    cancellation IF the date was kept. Rows cancelled before that column
    existed have no date, so they are left out of the past entirely
    rather than guessed at — an invented churn month is worse than a gap,
    because a gap is visible. Never overwrites a month already recorded.
    """
    when = when or time.time()
    have = {r["month"] for r in con.execute(
        "SELECT DISTINCT month FROM mrr_month")}
    lt = time.localtime(when)
    y, mo = lt.tm_year, lt.tm_mon
    written = 0
    for _ in range(max(1, months)):
        mo -= 1
        if mo < 1:
            mo, y = 12, y - 1
        m = f"{y:04d}-{mo:02d}"
        if m in have:
            continue
        # the last moment of that month, which is when its MRR is read
        nxt = time.mktime((y + (mo == 12), (mo % 12) + 1, 1,
                           0, 0, 0, 0, 0, -1))
        rows = []
        for r in con.execute(
                "SELECT s.user_id, s.qty, s.price_cents, s.created_at,"
                " COALESCE(s.cancelled_at,0) AS cancelled_at,"
                " COALESCE(u.name,'') AS name"
                " FROM store_subscriptions s"
                " LEFT JOIN users u ON u.id=s.user_id"
                " WHERE s.interval='month' AND s.created_at < ?", (nxt,)):
            if r["cancelled_at"] and r["cancelled_at"] < nxt:
                continue
            rows.append((r["user_id"], (r["price_cents"] or 0)
                         * max(1, r["qty"] or 1), r["name"]))
        by = {}
        for uid, cents, name in rows:
            got = by.setdefault(f"u{uid}", [0, name])
            got[0] += cents
        if not by:
            continue
        con.executemany(
            "INSERT OR IGNORE INTO mrr_month(month,account,cents,label,"
            " origin,taken_at) VALUES(?,?,?,?,'backfill',?)",
            [(m, k, v[0], v[1][:80], nxt) for k, v in by.items() if v[0] > 0])
        written += 1
    con.commit()
    return written


def lifetime(con, months: list, margin_pct: float = 0.0) -> dict:
    """How long a customer stays, and what they are worth while they do.

    Two answers, because they are found two different ways and a business
    should see both:

      * **implied** — 1 / the monthly churn rate. Fast, forward-looking,
        and wrong in a specific way: it assumes today's churn is
        everybody's future, so one bad month makes every customer look
        doomed. On thin history it is arithmetic, not evidence.
      * **observed** — the actual length of the subscriptions that have
        actually ended. Slow to become meaningful and biased short (the
        long-lived ones have not ended yet, so they are not in it), but
        it is a measurement rather than a projection.

    Value is ARPA times months times gross margin. Revenue is not value:
    a customer paying $200 a month against 45% cost of sales is worth
    $90 a month, and the difference is the whole of what is left to run
    the business on. Where the margin is not known the value is left out
    rather than reported at full price.
    """
    rated = [m for m in months if m["logo_churn_pct"] is not None]
    recent = rated[-3:]
    churn = (sum(m["logo_churn_pct"] for m in recent) / len(recent) / 100
             if recent else None)
    implied = (1 / churn) if churn else None
    ended = con.execute(
        "SELECT created_at, cancelled_at FROM store_subscriptions"
        " WHERE COALESCE(cancelled_at,0) > 0 AND created_at > 0").fetchall()
    spans = [(r["cancelled_at"] - r["created_at"]) / (30.44 * DAY)
             for r in ended if r["cancelled_at"] > r["created_at"]]
    observed = (sum(spans) / len(spans)) if spans else None
    arpa = months[-1]["arpa_cents"] if months else 0
    def _value(m):
        if not m or not margin_pct:
            return None
        return int(arpa * m * margin_pct / 100)
    return {
        "implied_months": round(implied, 1) if implied else None,
        "observed_months": round(observed, 1) if observed else None,
        "observed_n": len(spans),
        "churn_pct": round(churn * 100, 1) if churn is not None else None,
        "months_of_churn": len(recent),
        "arpa_cents": arpa,
        "margin_pct": margin_pct or None,
        "ltv_cents": _value(implied),
        "ltv_observed_cents": _value(observed),
        "note": "Implied lifetime is 1 divided by the churn rate, which "
                "assumes this month repeats forever. Observed is the real "
                "length of the plans that have ended — biased short, "
                "because the ones that have lasted are not in it yet.",
    }


def movement(con, months: int = 12, when: float = 0,
             margin_pct: float = 0.0) -> dict:
    """The series, and what moved between each pair of months.

    A pure read: taking this month's snapshot is the caller's business,
    so that asking what happened cannot itself change the answer.
    """
    when = when or time.time()
    rows = con.execute(
        "SELECT month, account, cents, label,"
        " COALESCE(origin,'live') AS origin FROM mrr_month"
        " ORDER BY month").fetchall()
    by_month, origin = {}, {}
    for r in rows:
        by_month.setdefault(r["month"], {})[r["account"]] = {
            "cents": r["cents"], "label": r["label"]}
        origin[r["month"]] = r["origin"]
    order = sorted(by_month)[-max(2, months):]
    out = []
    for i, m in enumerate(order):
        cur = by_month[m]
        # Movement is only read between two months recorded the same way.
        # A reconstructed month knows about subscriptions and nothing
        # about invoiced clients, so the step up to the first live month
        # is an artefact of what could be reconstructed — reporting it as
        # £600 of new business would be a lie with a chart around it.
        same = i and origin.get(order[i - 1]) == origin.get(m)
        prev = by_month[order[i - 1]] if same else {}
        new = exp = con_ = churn = 0
        movers = {"new": [], "expansion": [], "contraction": [], "churn": []}
        for acc, v in cur.items():
            was = prev.get(acc)
            if was is None:
                new += v["cents"]
                movers["new"].append({"account": acc, "label": v["label"],
                                      "cents": v["cents"]})
            elif v["cents"] > was["cents"]:
                exp += v["cents"] - was["cents"]
                movers["expansion"].append({
                    "account": acc, "label": v["label"],
                    "cents": v["cents"] - was["cents"]})
            elif v["cents"] < was["cents"]:
                con_ += was["cents"] - v["cents"]
                movers["contraction"].append({
                    "account": acc, "label": v["label"],
                    "cents": was["cents"] - v["cents"]})
        for acc, was in prev.items():
            if acc not in cur:
                churn += was["cents"]
                movers["churn"].append({"account": acc, "label": was["label"],
                                        "cents": was["cents"]})
        total = sum(v["cents"] for v in cur.values())
        base = sum(v["cents"] for v in prev.values())
        joined = bool(i) and not same
        # Net revenue retention asks one question: of the money that was
        # already here, how much is still here a month later. New logos
        # are deliberately not in it — they would hide the answer, which
        # is whether what you sell keeps being worth its price.
        nrr = ((base + exp - con_ - churn) / base * 100) if base else None
        grr = ((base - con_ - churn) / base * 100) if base else None
        out.append({
            "month": m, "mrr_cents": total, "accounts": len(cur),
            "origin": origin.get(m, "live"),
            # said out loud rather than shown as growth
            "seam": joined,
            "new_cents": 0 if joined else new,
            "expansion_cents": exp,
            "contraction_cents": con_, "churn_cents": churn,
            "net_new_cents": 0 if joined else new + exp - con_ - churn,
            "arr_cents": total * 12,
            "arpa_cents": int(total / len(cur)) if cur else 0,
            "nrr_pct": round(nrr, 1) if nrr is not None else None,
            "grr_pct": round(grr, 1) if grr is not None else None,
            "new_logos": len(movers["new"]),
            "lost_logos": len(movers["churn"]),
            # The two rates people actually ask for, both measured against
            # the month you started with rather than the one you ended
            # with — a percentage of a number that already includes the
            # arrivals cannot be compared to the one that lost them.
            "logo_churn_pct": round(
                len(movers["churn"]) / len(prev) * 100, 1) if prev else None,
            "logo_new_pct": round(
                len(movers["new"]) / len(prev) * 100, 1) if prev else None,
            "quick_ratio": round((new + exp) / (con_ + churn), 2)
            if (con_ + churn) else None,
            "movers": movers,
        })
    life = lifetime(con, out, margin_pct)
    first = con.execute("SELECT MIN(month) AS m FROM mrr_month").fetchone()
    unknown = con.execute(
        "SELECT COUNT(*) AS n FROM store_subscriptions"
        " WHERE status='cancelled' AND COALESCE(cancelled_at,0)=0"
    ).fetchone()["n"]
    return {"months": out, "lifetime": life,
            "from": first["m"] if first else "",
            "recorded_months": len(by_month),
            "undated_cancellations": unknown,
            "note": "One row per paying account per month, so growth can be "
                    "taken apart: new, expansion, contraction and churn add "
                    "up to the change exactly. NRR is what last month's "
                    "accounts are worth this month — above 100% is growth "
                    "without a single new customer."}
