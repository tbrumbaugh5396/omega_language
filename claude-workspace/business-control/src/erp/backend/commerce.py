"""What a basket is worth, and whether anybody comes back.

Acquisition was already measured here in five ways. What happened after
somebody bought was measured in none — and for a business that sells
anything twice, the second purchase is where the money is. Three
questions, kept apart because they answer different arguments:

    how big is a basket      average order value, and the median beside it
    does anybody return      repeat rate, and how long the gap is
    are they staying         a cohort triangle, month by month

The median sits next to every average on purpose. One $18,000 build in a
month of $40 tea orders moves the mean past every real basket in the
list, and a shop that reprices itself off that number reprices itself off
one customer.
"""
import statistics
import time

DAY = 86400


def _month(ts: float) -> str:
    return time.strftime("%Y-%m", time.localtime(ts))


def _months_between(a: str, b: str) -> int:
    ay, am = (int(x) for x in a.split("-"))
    by, bm = (int(x) for x in b.split("-"))
    return (by - ay) * 12 + (bm - am)


def _orders(con, since: float = 0, kind: str = ""):
    q = ("SELECT o.id, o.user_id, o.created_at, o.kind,"
         " COALESCE(o.subtotal_cents,0) AS cents,"
         " (SELECT COALESCE(SUM(qty),0) FROM order_items oi"
         "   WHERE oi.order_id=o.id) AS units"
         " FROM orders o WHERE o.status!='cancelled'")
    args = []
    if since:
        q += " AND o.created_at>=?"
        args.append(since)
    if kind:
        q += " AND o.kind=?"
        args.append(kind)
    return [dict(r) for r in con.execute(q + " ORDER BY o.created_at", args)]


def basket(con, days: int = 90, kind: str = "", when: float = 0) -> dict:
    """What an order is worth, with the median beside the mean.

    Reported per kind as well as in total: a case of stock going to a
    distributor and a tin going to somebody's kitchen are not the same
    transaction, and one average over both describes neither.
    """
    when = when or time.time()
    rows = _orders(con, when - days * DAY, kind)
    if not rows:
        return {"orders": 0, "days": days}
    cents = [r["cents"] for r in rows]
    units = [r["units"] for r in rows if r["units"]]
    by_kind = {}
    for r in rows:
        k = by_kind.setdefault(r["kind"] or "retail", [])
        k.append(r["cents"])
    return {
        "days": days, "orders": len(rows), "revenue_cents": sum(cents),
        "aov_cents": int(statistics.mean(cents)),
        "median_cents": int(statistics.median(cents)),
        "units_per_order": round(statistics.mean(units), 2) if units else None,
        "by_kind": [{"kind": k, "orders": len(v),
                     "aov_cents": int(statistics.mean(v)),
                     "median_cents": int(statistics.median(v))}
                    for k, v in sorted(by_kind.items())],
        "spread": {"p25": int(statistics.quantiles(cents, n=4)[0]),
                   "p75": int(statistics.quantiles(cents, n=4)[2])}
        if len(cents) >= 4 else None,
    }


def repeat(con, days: int = 365, kind: str = "", when: float = 0) -> dict:
    """Does anybody come back, and how long do they take about it.

    Two rates, because the obvious one is ambiguous and people argue past
    each other with it:

      * **in the window** — of the customers who bought in this window,
        how many bought more than once IN it. Moves with the window: a
        30-day window on a business people buy from quarterly reads
        almost zero, and that is a fact about the window.
      * **ever** — of everybody who has ever bought, how many have bought
        more than once. Slow, unambiguous, and the one to watch.
    """
    when = when or time.time()
    win = _orders(con, when - days * DAY, kind)
    allo = _orders(con, 0, kind)
    by_cust_win, by_cust_all = {}, {}
    for r in win:
        by_cust_win.setdefault(r["user_id"], []).append(r)
    for r in allo:
        by_cust_all.setdefault(r["user_id"], []).append(r)
    gaps = []
    for rows in by_cust_all.values():
        if len(rows) >= 2:
            gaps.append((rows[1]["created_at"] - rows[0]["created_at"]) / DAY)
    rep_win = sum(1 for v in by_cust_win.values() if len(v) >= 2)
    rep_all = sum(1 for v in by_cust_all.values() if len(v) >= 2)
    # Money from people who had bought before, against money from people
    # who had not. The split matters more than either half: a month that
    # grew entirely on strangers grew on the most expensive kind.
    first_of = {u: rows[0]["id"] for u, rows in by_cust_all.items()}
    new_cents = sum(r["cents"] for r in win if first_of.get(r["user_id"])
                    == r["id"])
    ret_cents = sum(r["cents"] for r in win) - new_cents
    return {
        "days": days,
        "customers_in_window": len(by_cust_win),
        "repeat_in_window": rep_win,
        "repeat_pct": round(rep_win / len(by_cust_win) * 100, 1)
        if by_cust_win else None,
        "customers_ever": len(by_cust_all),
        "repeat_ever": rep_all,
        "repeat_ever_pct": round(rep_all / len(by_cust_all) * 100, 1)
        if by_cust_all else None,
        "orders_per_customer": round(len(allo) / len(by_cust_all), 2)
        if by_cust_all else None,
        "median_gap_days": round(statistics.median(gaps), 1) if gaps else None,
        "new_revenue_cents": new_cents,
        "returning_revenue_cents": ret_cents,
        "returning_pct": round(ret_cents / (new_cents + ret_cents) * 100, 1)
        if (new_cents + ret_cents) else None,
    }


def cohorts(con, months: int = 12, kind: str = "", when: float = 0) -> dict:
    """Customers grouped by the month they first bought, then followed.

    Month 0 is everybody by definition, so it is not reported as a
    retention figure — a triangle whose first column is always 100% is a
    triangle with a column of decoration in it. What is reported is how
    many of that month's customers came back in each month after, and a
    cohort still inside its own month is marked rather than shown as a
    collapse: three days is not a month, and drawing it as one is how a
    perfectly ordinary week becomes a crisis meeting.
    """
    when = when or time.time()
    rows = _orders(con, 0, kind)
    if not rows:
        return {"cohorts": [], "months": months}
    first, active = {}, {}
    for r in rows:
        m = _month(r["created_at"])
        first.setdefault(r["user_id"], m)
        active.setdefault(r["user_id"], set()).add(m)
    this_month = _month(when)
    all_months = sorted({m for m in first.values()})[-months:]
    out = []
    for cm in all_months:
        who = [u for u, m in first.items() if m == cm]
        if not who:
            continue
        span = _months_between(cm, this_month)
        cells = []
        for n in range(1, min(span, months) + 1):
            y, mo = (int(x) for x in cm.split("-"))
            mo += n
            y, mo = y + (mo - 1) // 12, (mo - 1) % 12 + 1
            tag = f"{y:04d}-{mo:02d}"
            back = sum(1 for u in who if tag in active[u])
            cells.append({"month": n, "tag": tag, "n": back,
                          "pct": round(back / len(who) * 100, 1),
                          "partial": tag == this_month})
        out.append({"cohort": cm, "size": len(who), "cells": cells,
                    "partial": cm == this_month})
    return {
        "cohorts": out, "months": months,
        "note": "Each row is the customers who first bought in that month, "
                "and each cell is how many of them bought again in the "
                "month after it. Month 0 is everybody by definition, so it "
                "is not drawn. The current month is marked: it is not over, "
                "and reading a part-month as a full one turns an ordinary "
                "week into a crisis meeting.",
    }


# ---------- the shelf, line by line ----------

def lines(con, days: int = 90, when: float = 0, group: str = "product") -> dict:
    """Revenue, units and margin per product — or per category.

    An overall margin is an average of things that are not alike. It can
    be healthy while a third of the range is sold at a loss, and the only
    way to find that out is to ask each line separately. Where a recipe
    prices a product the margin is measured; where it does not, the line
    says so rather than borrowing the shop's average and calling itself
    profitable.

    Attach rate is here because it is the number that argues for keeping a
    thin-margin line: a product that is mostly bought alone earns its
    shelf on its own margin, and one that is almost always in a basket
    with something else earns it on the basket's.
    """
    when = when or time.time()
    since = when - days * DAY
    costs = supply_costs(con)
    rows = con.execute(
        "SELECT oi.product_id, p.name, COALESCE(p.category,'') AS category,"
        " SUM(oi.qty) AS units,"
        " SUM(oi.qty * oi.unit_price_cents) AS cents,"
        " COUNT(DISTINCT oi.order_id) AS orders,"
        " COUNT(DISTINCT o.user_id) AS buyers"
        " FROM order_items oi JOIN orders o ON o.id=oi.order_id"
        " LEFT JOIN products p ON p.id=oi.product_id"
        " WHERE o.status!='cancelled' AND o.created_at>=?"
        " GROUP BY oi.product_id", (since,)).fetchall()
    if not rows:
        return {"days": days, "lines": [], "group": group}
    # How often a line is the whole order, which is what attach rate is
    # really asking: alone on the receipt, or in company.
    sizes = {r["order_id"]: r["n"] for r in con.execute(
        "SELECT order_id, COUNT(*) AS n FROM order_items GROUP BY order_id")}
    alone = {}
    for r in con.execute(
            "SELECT oi.product_id, oi.order_id FROM order_items oi"
            " JOIN orders o ON o.id=oi.order_id"
            " WHERE o.status!='cancelled' AND o.created_at>=?", (since,)):
        if sizes.get(r["order_id"], 1) == 1:
            alone[r["product_id"]] = alone.get(r["product_id"], 0) + 1
    out = []
    for r in rows:
        c = costs.get(r["product_id"])
        cogs = int(c["per_unit_cents"] * r["units"]) if c else None
        out.append({
            "product_id": r["product_id"],
            "name": r["name"] or f"product {r['product_id']}",
            "category": r["category"] or "uncategorised",
            "units": r["units"], "orders": r["orders"], "buyers": r["buyers"],
            "revenue_cents": r["cents"],
            "avg_price_cents": int(r["cents"] / r["units"]) if r["units"]
            else 0,
            "cogs_cents": cogs,
            "margin_cents": (r["cents"] - cogs) if cogs is not None else None,
            "margin_pct": round((r["cents"] - cogs) / r["cents"] * 100, 1)
            if cogs is not None and r["cents"] else None,
            "priced": c is not None,
            "attach_pct": round(
                (1 - alone.get(r["product_id"], 0) / r["orders"]) * 100, 1)
            if r["orders"] else None,
        })
    out.sort(key=lambda x: -x["revenue_cents"])
    rev = sum(x["revenue_cents"] for x in out)
    # The share of revenue the top fifth of the range carries. Not a law of
    # nature, but a shelf where it is 95% is a shelf with a long tail
    # nobody is paying for.
    cut = max(1, len(out) // 5)
    cats = {}
    for x in out:
        k = cats.setdefault(x["category"], {
            "category": x["category"], "lines": 0, "units": 0,
            "revenue_cents": 0, "margin_cents": 0, "priced_revenue": 0})
        k["lines"] += 1
        k["units"] += x["units"]
        k["revenue_cents"] += x["revenue_cents"]
        if x["margin_cents"] is not None:
            k["margin_cents"] += x["margin_cents"]
            k["priced_revenue"] += x["revenue_cents"]
    cat_rows = sorted(cats.values(), key=lambda k: -k["revenue_cents"])
    for k in cat_rows:
        k["margin_pct"] = (round(k["margin_cents"] / k["priced_revenue"] * 100,
                                 1) if k["priced_revenue"] else None)
        k["share_pct"] = round(k["revenue_cents"] / rev * 100, 1) if rev else 0
    return {
        "days": days, "group": group, "lines": out, "categories": cat_rows,
        "revenue_cents": rev,
        "priced_pct": round(sum(x["revenue_cents"] for x in out if x["priced"])
                            / rev * 100) if rev else 0,
        "top_fifth_pct": round(sum(x["revenue_cents"] for x in out[:cut])
                               / rev * 100, 1) if rev else None,
        "losing": [x for x in out
                   if x["margin_pct"] is not None and x["margin_pct"] < 0],
        "note": "Margin is measured where a recipe prices the product and "
                "left blank where it does not — an overall margin is an "
                "average of things that are not alike, and it can look "
                "healthy while a third of the range is sold at a loss.",
    }


def supply_costs(con) -> dict:
    from . import supply
    try:
        return supply.unit_costs(con)
    except Exception:                                        # noqa: BLE001
        return {}
