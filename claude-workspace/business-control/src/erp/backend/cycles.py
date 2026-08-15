"""Box-cycle calendar & cutoff orchestration.

A subscription-box month is a state machine nobody else owns — the billing
provider knows charge dates, Shopify knows orders, but the cutoffs live here:

  bill -> dunning closes -> curation locks -> pack -> ship -> closed

Phases derive from dates; counts (billed/skipped/allocated) are recorded per
cycle — entered by hand today, synced from the subscription provider's
webhooks later. `changes_open` is the one flag the subscriber portal must
obey: skip/swap allowed only before curation lock."""
import calendar
import datetime as dt

from . import db

PHASES = ("upcoming", "billing", "curation", "packing", "shipped", "closed")


def _day(year: int, month: int, day: int) -> str:
    day = min(day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day).isoformat()


def make_dates(cfg: dict, month: str) -> dict:
    """month 'YYYY-MM' -> the cycle's cutoff dates from config template."""
    year, mon = int(month[:4]), int(month[5:7])
    t = cfg.get("box_cycle", {})
    return {
        "bill_date": _day(year, mon, t.get("bill_day", 1)),
        "dunning_close": _day(year, mon, t.get("bill_day", 1)
                              + t.get("dunning_days", 5)),
        "curation_lock": _day(year, mon, t.get("curation_day", 8)),
        "ship_date": _day(year, mon, t.get("ship_day", 15)),
    }


def create(con, cfg: dict, month: str, dates: dict | None = None) -> dict:
    d = dict(make_dates(cfg, month))
    if dates:
        d.update({k: v for k, v in dates.items() if v})
    if not (d["bill_date"] <= d["dunning_close"] <= d["curation_lock"]
            <= d["ship_date"]):
        raise ValueError("dates must be ordered: bill <= dunning <= "
                         "curation <= ship")
    con.execute(
        "INSERT INTO box_cycles(month,bill_date,dunning_close,curation_lock,"
        " ship_date,created_at) VALUES(?,?,?,?,?,?)",
        (month, d["bill_date"], d["dunning_close"], d["curation_lock"],
         d["ship_date"], db.now()))
    con.commit()
    return get(con, month)


def phase(c, today: str) -> str:
    if c["closed"]:
        return "closed"
    if today < c["bill_date"]:
        return "upcoming"
    if today <= c["dunning_close"]:
        return "billing"
    if today <= c["curation_lock"]:
        return "curation"
    if today < c["ship_date"]:
        return "packing"
    return "shipped"


def as_json(c, today: str | None = None) -> dict:
    today = today or dt.date.today().isoformat()
    d = dict(c)
    d["phase"] = phase(c, today)
    # The portal gate: subscriber skip/swap allowed only before curation lock.
    d["changes_open"] = (not c["closed"]) and today <= c["curation_lock"]
    d["ship_ready"] = (d["phase"] in ("packing", "shipped")
                       and c["allocated_count"] >= c["billed_count"] > 0)
    return d


def get(con, month: str):
    row = con.execute("SELECT * FROM box_cycles WHERE month=?",
                      (month,)).fetchone()
    return as_json(row) if row else None


def current(con):
    """The cycle most relevant right now: latest un-closed, else latest."""
    today = dt.date.today().isoformat()
    row = con.execute(
        "SELECT * FROM box_cycles WHERE closed=0 ORDER BY month LIMIT 1"
    ).fetchone() or con.execute(
        "SELECT * FROM box_cycles ORDER BY month DESC LIMIT 1").fetchone()
    return as_json(row, today) if row else None


def sweep(con, cfg) -> None:
    """Cutoff notifications, deduped per cycle+milestone (runs on the
    notification sweep). Warns the day before a cutoff, announces the day of."""
    from . import notify
    today = dt.date.today()
    t = today.isoformat()
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    for c in con.execute("SELECT * FROM box_cycles WHERE closed=0").fetchall():
        m = c["month"]
        checks = (
            (c["bill_date"], "bill", f"Cycle {m}: billing day — charges run"
             " today; watch dunning outcomes before allocating"),
            (c["dunning_close"], "dun", f"Cycle {m}: dunning window closes"
             " today — final billed count is now trustworthy"),
            (c["curation_lock"], "lock", f"Cycle {m}: curation LOCKS today"
             " — subscriber skip/swap closes, allocate the box"),
            (c["ship_date"], "ship", f"Cycle {m}: ship day"),
        )
        for date, key, msg in checks:
            if date == tomorrow:
                notify.push(con, msg.replace("today", "TOMORROW"),
                            kind="cycle", dedup=f"cyc:{m}:{key}:pre")
            elif date == t:
                notify.push(con, msg, kind="cycle", dedup=f"cyc:{m}:{key}")
        if (t >= c["curation_lock"] and c["billed_count"] > 0
                and c["allocated_count"] < c["billed_count"]):
            notify.push(con, f"Cycle {m}: allocation short — "
                        f"{c['allocated_count']}/{c['billed_count']} boxes"
                        " allocated after curation lock",
                        kind="cycle", dedup=f"cyc:{m}:short:{t}")
