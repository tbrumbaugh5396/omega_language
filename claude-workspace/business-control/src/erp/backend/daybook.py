"""One row per day, per region: the table every other number can join to.

Almost every question a business asks is a daily series compared with
another daily series — sales against footfall, footfall against staffing,
staffing against the weather, this March against last March. Computing
each of those from the transaction tables separately is how a reporting
screen becomes six different definitions of "a day", so there is one:

    day × region → money, orders, people, hours, and what kind of day it
    was

The last part is the one that quietly corrupts everything else. A month
has four weekends or five. Easter moves. A public holiday closes a shop
or triples it, depending on the shop. Comparing "this month against last"
without knowing which days were trading days is comparing two different
questions and reporting the difference as performance — and nobody
notices, because the number always comes out.

Holidays are computed rather than fetched: the rules are stable, they are
the same every year, and an install with no outbound network still has to
know that Christmas is a Thursday. Company days — the closure, the
stocktake, the staff party — are added by hand and sit in the same table,
because a day the doors were shut is a day the doors were shut whoever
decided it.

Weather has columns here and nothing in them yet. It belongs on a day
rather than in a service of its own: "it rained" is not a metric, and
"Saturday was down 18% and it rained" is the beginning of one.
"""
import time

DAY = 86400

TABLES = """
CREATE TABLE IF NOT EXISTS day_facts (
  day TEXT NOT NULL,                       -- YYYY-MM-DD, local
  region TEXT NOT NULL DEFAULT '',         -- '' = the whole business
  weekday INTEGER NOT NULL,                -- 0 Monday .. 6 Sunday
  revenue_cents INTEGER DEFAULT 0,
  orders INTEGER DEFAULT 0,
  units INTEGER DEFAULT 0,
  visitors INTEGER DEFAULT 0,              -- distinct, from the pageview log
  new_customers INTEGER DEFAULT 0,
  labour_minutes INTEGER DEFAULT 0,
  holiday TEXT DEFAULT '',                 -- name, or '' for an ordinary day
  closed INTEGER DEFAULT 0,                -- a day the doors were shut
  temp_c REAL,                             -- weather: still to be filled
  precip_mm REAL,
  cloud_pct REAL,
  humidity_pct REAL,
  built_at REAL NOT NULL,
  PRIMARY KEY (day, region)
);
CREATE INDEX IF NOT EXISTS day_facts_day ON day_facts(day);

CREATE TABLE IF NOT EXISTS calendar_days (
  day TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'public',     -- public | company | school
  closed INTEGER DEFAULT 0,
  PRIMARY KEY (day, name)
);
"""


def init_tables(con):
    con.executescript(TABLES)


# ---------- what kind of day it was ----------

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> str:
    """The nth given weekday of a month — 'the third Monday in January'.
    n = -1 asks for the last one."""
    first = time.localtime(time.mktime((year, month, 1, 12, 0, 0, 0, 0, -1)))
    if n > 0:
        offset = (weekday - first.tm_wday) % 7 + (n - 1) * 7
        return time.strftime("%Y-%m-%d", time.localtime(
            time.mktime((year, month, 1 + offset, 12, 0, 0, 0, 0, -1))))
    days = [31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31,
            30, 31][month - 1]
    last = time.localtime(time.mktime((year, month, days, 12, 0, 0, 0, 0, -1)))
    return time.strftime("%Y-%m-%d", time.localtime(
        time.mktime((year, month, days - (last.tm_wday - weekday) % 7,
                     12, 0, 0, 0, 0, -1))))


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def easter(year: int) -> str:
    """Anonymous Gregorian computus. Easter is here because it MOVES —
    five weeks of range — and a like-for-like comparison of two Aprils
    that ignores it is comparing a holiday week with an ordinary one."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return f"{year:04d}-{month:02d}-{day + 1:02d}"


def _shift(day: str, days: int) -> str:
    y, m, d = (int(x) for x in day.split("-"))
    return time.strftime("%Y-%m-%d", time.localtime(
        time.mktime((y, m, d, 12, 0, 0, 0, 0, -1)) + days * DAY))


US_FIXED = ((1, 1, "New Year's Day"), (6, 19, "Juneteenth"),
            (7, 4, "Independence Day"), (11, 11, "Veterans Day"),
            (12, 25, "Christmas Day"))
US_FLOATING = ((1, 0, 3, "Martin Luther King Jr. Day"),
               (2, 0, 3, "Presidents' Day"),
               (5, 0, -1, "Memorial Day"),
               (9, 0, 1, "Labor Day"),
               (10, 0, 2, "Columbus Day"),
               (11, 3, 4, "Thanksgiving"))


def public_holidays(year: int, country: str = "US") -> list:
    """The year's public holidays, computed from the rules.

    Computed rather than fetched: the rules do not change, an install
    with no outbound network still has to know when Christmas is, and a
    reporting number that depends on somebody else's uptime is a
    reporting number that is sometimes wrong and never says so.
    """
    out = []
    if country.upper() == "US":
        for mo, d, name in US_FIXED:
            day = f"{year:04d}-{mo:02d}-{d:02d}"
            wd = time.localtime(time.mktime(
                (year, mo, d, 12, 0, 0, 0, 0, -1))).tm_wday
            # The federal observed rule: Saturday moves back to Friday,
            # Sunday forward to Monday. The day off is the day the doors
            # are shut, which is the one a sales chart feels.
            if wd == 5:
                out.append((_shift(day, -1), name + " (observed)"))
            elif wd == 6:
                out.append((_shift(day, 1), name + " (observed)"))
            else:
                out.append((day, name))
        for mo, wd, n, name in US_FLOATING:
            out.append((_nth_weekday(year, mo, wd, n), name))
        e = easter(year)
        out.append((_shift(e, -2), "Good Friday"))
        out.append((e, "Easter Sunday"))
    return sorted(out)


def fill_calendar(con, years: list, country: str = "US") -> int:
    n = 0
    for y in years:
        for day, name in public_holidays(y, country):
            cur = con.execute(
                "INSERT OR IGNORE INTO calendar_days(day,name,kind,closed)"
                " VALUES(?,?,'public',0)", (day, name))
            n += cur.rowcount
    con.commit()
    return n


# ---------- the facts ----------

def _day_key(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _midnight(ts: float) -> float:
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def rebuild(con, days: int = 120, when: float = 0) -> int:
    """Recompute the last N days from the transaction tables.

    Whole days only, and recomputed rather than accumulated: a refund, a
    late-cancelled order or a corrected shift changes a day that has
    already happened, and a counter that was incremented at the time
    cannot hear about it.
    """
    when = when or time.time()
    start = _midnight(when) - (days - 1) * DAY
    marks = {r["day"]: r for r in con.execute(
        "SELECT day, name, closed FROM calendar_days ORDER BY kind DESC")}
    rows = {}

    def slot(day, region):
        key = (day, region)
        if key not in rows:
            y, m, d = (int(x) for x in day.split("-"))
            wd = time.localtime(time.mktime(
                (y, m, d, 12, 0, 0, 0, 0, -1))).tm_wday
            mk = marks.get(day)
            rows[key] = {"weekday": wd, "revenue_cents": 0, "orders": 0,
                         "units": 0, "visitors": 0, "new_customers": 0,
                         "labour_minutes": 0,
                         "holiday": mk["name"] if mk else "",
                         "closed": (mk["closed"] if mk else 0)}
        return rows[key]

    for r in con.execute(
            "SELECT o.id, o.created_at, COALESCE(o.region,'') AS region,"
            " COALESCE(o.subtotal_cents,0) AS cents,"
            " (SELECT COALESCE(SUM(qty),0) FROM order_items oi"
            "   WHERE oi.order_id=o.id) AS units"
            " FROM orders o WHERE o.created_at>=? AND o.status!='cancelled'",
            (start,)):
        for region in ("", r["region"]):
            g = slot(_day_key(r["created_at"]), region)
            g["revenue_cents"] += r["cents"]
            g["orders"] += 1
            g["units"] += r["units"]
    # Visitors are distinct PEOPLE per day, which cannot be summed out of
    # a grouped query without counting somebody twice, so they are
    # gathered day by day.
    try:
        seen = {}
        for r in con.execute(
                "SELECT created_at, visitor FROM store_pageviews"
                " WHERE created_at>=?", (start,)):
            seen.setdefault(_day_key(r["created_at"]), set()).add(r["visitor"])
        for day, who in seen.items():
            slot(day, "")["visitors"] = len(who)
    except Exception:                                        # noqa: BLE001
        pass
    try:
        for r in con.execute(
                "SELECT created_at, COALESCE(region,'') AS region"
                " FROM users WHERE created_at>=? AND role='customer'",
                (start,)):
            for region in ("", r["region"]):
                slot(_day_key(r["created_at"]), region)["new_customers"] += 1
    except Exception:                                        # noqa: BLE001
        pass
    try:
        for r in con.execute(
                "SELECT clock_in, clock_out FROM shifts WHERE clock_in>=?",
                (start,)):
            out = r["clock_out"] or 0
            if out <= r["clock_in"]:
                continue
            slot(_day_key(r["clock_in"]), "")["labour_minutes"] += int(
                (out - r["clock_in"]) / 60)
    except Exception:                                        # noqa: BLE001
        pass

    # Days with nothing on them are days too — a closed Sunday with no
    # sales is a fact, and leaving it out of the table turns every
    # average into an average of the days that went well.
    for i in range(days):
        slot(_day_key(start + i * DAY), "")

    # Upsert the facts and ONLY the facts. INSERT OR REPLACE deletes the
    # row and writes a new one, which silently drops every column this
    # statement does not name — so a rebuild threw away the weather it had
    # just been given, every time anybody opened the screen.
    con.executemany(
        "INSERT INTO day_facts(day,region,weekday,revenue_cents,"
        " orders,units,visitors,new_customers,labour_minutes,holiday,closed,"
        " built_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(day,region) DO UPDATE SET"
        "  weekday=excluded.weekday, revenue_cents=excluded.revenue_cents,"
        "  orders=excluded.orders, units=excluded.units,"
        "  visitors=excluded.visitors,"
        "  new_customers=excluded.new_customers,"
        "  labour_minutes=excluded.labour_minutes,"
        "  holiday=excluded.holiday, closed=excluded.closed,"
        "  built_at=excluded.built_at",
        [(d, rg, v["weekday"], v["revenue_cents"], v["orders"], v["units"],
          v["visitors"], v["new_customers"], v["labour_minutes"],
          v["holiday"], v["closed"], when)
         for (d, rg), v in rows.items()])
    con.commit()
    return len(rows)


def series(con, days: int = 90, region: str = "", when: float = 0) -> dict:
    """The daily series, and what can be read off it once the calendar is
    part of the row rather than a thing somebody remembers."""
    when = when or time.time()
    start = _day_key(_midnight(when) - (days - 1) * DAY)
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM day_facts WHERE region=? AND day>=? ORDER BY day",
        (region, start))]
    trading = [r for r in rows if not r["closed"]]
    rev = sum(r["revenue_cents"] for r in rows)
    by_weekday = {}
    for r in trading:
        w = by_weekday.setdefault(r["weekday"], {"cents": 0, "days": 0})
        w["cents"] += r["revenue_cents"]
        w["days"] += 1
    weekdays = [{"weekday": k, "avg_cents": int(v["cents"] / v["days"]),
                 "days": v["days"]}
                for k, v in sorted(by_weekday.items()) if v["days"]]
    hol = [r for r in rows if r["holiday"]]
    hol_avg = (sum(r["revenue_cents"] for r in hol) / len(hol)) if hol else 0
    ord_days = [r for r in trading if not r["holiday"]]
    ord_avg = (sum(r["revenue_cents"] for r in ord_days) / len(ord_days)
               if ord_days else 0)
    return {
        "days": rows, "region": region,
        "revenue_cents": rev,
        "trading_days": len(trading),
        "closed_days": len(rows) - len(trading),
        "avg_cents": int(rev / len(trading)) if trading else 0,
        "weekdays": weekdays,
        "best_weekday": max(weekdays, key=lambda w: w["avg_cents"])["weekday"]
        if weekdays else None,
        "holidays": [{"day": r["day"], "name": r["holiday"],
                      "revenue_cents": r["revenue_cents"]} for r in hol],
        "holidays_n": len(hol),
        # Three is not a large sample, but it is the point below which a
        # "holidays are 40% down" headline is one quiet Tuesday wearing a
        # trend's clothes.
        "holiday_lift_pct": round((hol_avg - ord_avg) / ord_avg * 100, 1)
        if ord_avg and len(hol) >= 3 else None,
        "weather": any(r["temp_c"] is not None for r in rows),
    }


def compare(con, region: str = "", when: float = 0) -> dict:
    """This month against the last, aligned by trading day.

    The comparison everybody makes and nobody adjusts. February has 28
    days and March has 31; one month has five Saturdays and the next has
    four; a holiday lands in one of them. Reporting the raw difference as
    performance is reporting the calendar as performance — so both the
    raw number and the per-trading-day number are returned, and where
    they disagree, the per-day one is the business.
    """
    when = when or time.time()
    lt = time.localtime(when)
    this_m = f"{lt.tm_year:04d}-{lt.tm_mon:02d}"
    py, pm = (lt.tm_year - 1, 12) if lt.tm_mon == 1 else (lt.tm_year,
                                                          lt.tm_mon - 1)
    last_m = f"{py:04d}-{pm:02d}"

    # Month to date against the same stretch of the month before. Three
    # days of September against the whole of August is not a comparison,
    # it is a subtraction — and it always says the business collapsed.
    upto = lt.tm_mday

    def side(month):
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM day_facts WHERE region=? AND day LIKE ?",
            (region, month + "-%"))]
        rows = [r for r in rows if int(r["day"][-2:]) <= upto]
        trade = [r for r in rows if not r["closed"]]
        cents = sum(r["revenue_cents"] for r in rows)
        return {"month": month, "revenue_cents": cents, "days": len(rows),
                "trading_days": len(trade), "orders": sum(
                    r["orders"] for r in rows),
                "per_trading_day_cents": int(cents / len(trade))
                if trade else 0,
                "holidays": [r["holiday"] for r in rows if r["holiday"]]}

    a, b = side(last_m), side(this_m)

    def pct(now, was):
        return round((now - was) / was * 100, 1) if was else None
    return {
        "this": b, "last": a, "to_day": upto,
        "raw_pct": pct(b["revenue_cents"], a["revenue_cents"]),
        "per_day_pct": pct(b["per_trading_day_cents"],
                           a["per_trading_day_cents"]),
        "trading_day_gap": b["trading_days"] - a["trading_days"],
        "note": f"Both sides are the first {upto} days of the month, so a "
                f"month three days old is not compared with one that is "
                f"over. Two months are rarely the same shape even then. "
                "The per-trading-day "
                "figure is the one to read when they disagree: the raw "
                "difference includes the calendar, and the calendar is not "
                "something the business did.",
    }


# ---------- the sky ----------
#
# Weather is not a KPI. "It rained" explains nothing on its own; "Saturday
# was down 18% and it rained" is the start of an explanation, and "wet
# Saturdays run 14% under dry ones across eleven of them" is a fact you
# can staff against. So it lands on the day row beside the money rather
# than in a service of its own, and the only numbers reported off it are
# comparisons with enough days behind them to mean something.
#
# Open-Meteo, because it needs no key, serves history and forecast from
# one shape, and asks nothing about who is asking. Observed weather, not
# forecast: the retrospective question is what the weather WAS, and a
# forecast that was wrong is exactly the day you are trying to explain.

WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_weather(lat: float, lon: float, start: str, end: str,
                  timeout: float = 12.0) -> dict:
    """{day: {temp_c, precip_mm, cloud_pct, humidity_pct}} for a range.

    Raises on anything that goes wrong, so a caller can say so plainly
    rather than writing a day of zeroes and calling it a measurement.
    """
    import json
    import urllib.parse
    import urllib.request
    today = time.strftime("%Y-%m-%d")
    url = WEATHER_URL if end < today else FORECAST_URL
    q = urllib.parse.urlencode({
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start_date": start, "end_date": end,
        "daily": "temperature_2m_mean,precipitation_sum,cloud_cover_mean,"
                 "relative_humidity_2m_mean",
        "timezone": "auto"})
    with urllib.request.urlopen(f"{url}?{q}", timeout=timeout) as r:
        got = json.loads(r.read().decode("utf-8"))
    d = got.get("daily") or {}
    days = d.get("time") or []
    out = {}
    for i, day in enumerate(days):
        def at(key):
            vals = d.get(key) or []
            return vals[i] if i < len(vals) else None
        out[day] = {"temp_c": at("temperature_2m_mean"),
                    "precip_mm": at("precipitation_sum"),
                    "cloud_pct": at("cloud_cover_mean"),
                    "humidity_pct": at("relative_humidity_2m_mean")}
    return out


def save_weather(con, got: dict, region: str = "") -> int:
    n = 0
    for day, w in got.items():
        cur = con.execute(
            "UPDATE day_facts SET temp_c=?, precip_mm=?, cloud_pct=?,"
            " humidity_pct=? WHERE day=? AND region=?",
            (w["temp_c"], w["precip_mm"], w["cloud_pct"], w["humidity_pct"],
             day, region))
        n += cur.rowcount
    con.commit()
    return n


def weather_read(con, days: int = 90, region: str = "",
                 when: float = 0) -> dict:
    """What the weather did to trade, said carefully.

    Wet against dry and warm against cool, each reported only with enough
    days on both sides to be a comparison rather than an anecdote. The
    threshold is the median rather than a fixed millimetre, because "wet"
    means something different in Seattle and Phoenix and a number baked
    in here would be wrong in one of them.
    """
    when = when or time.time()
    start = _day_key(_midnight(when) - (days - 1) * DAY)
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM day_facts WHERE region=? AND day>=? AND temp_c"
        " IS NOT NULL AND closed=0 ORDER BY day", (region, start))]
    if len(rows) < 14:
        return {"have": len(rows), "enough": False,
                "why": "fewer than fourteen days of weather on trading days "
                       "— nothing here would be a comparison yet"}

    def split(field, label_hi, label_lo):
        vals = sorted(r[field] for r in rows if r[field] is not None)
        if len(vals) < 14:
            return None
        mid = vals[len(vals) // 2]
        hi = [r for r in rows if (r[field] or 0) > mid]
        lo = [r for r in rows if (r[field] or 0) <= mid]
        if len(hi) < 5 or len(lo) < 5:
            return None
        a = sum(r["revenue_cents"] for r in hi) / len(hi)
        b = sum(r["revenue_cents"] for r in lo) / len(lo)
        return {"field": field, "split_at": round(mid, 1),
                "hi_label": label_hi, "lo_label": label_lo,
                "hi_days": len(hi), "lo_days": len(lo),
                "hi_avg_cents": int(a), "lo_avg_cents": int(b),
                "diff_pct": round((a - b) / b * 100, 1) if b else None}
    return {
        "have": len(rows), "enough": True,
        "rain": split("precip_mm", "wet", "dry"),
        "warm": split("temp_c", "warmer", "cooler"),
        "cloud": split("cloud_pct", "cloudier", "clearer"),
        "note": "Each split is at the median of the days themselves, not a "
                "fixed threshold: wet means something different in Seattle "
                "and Phoenix. A difference across a few dozen days is a "
                "hint to staff against, not a law.",
    }


# ---------- what the hours bought, and whether the rota held ----------

def labour_read(con, days: int = 90, region: str = "",
                when: float = 0) -> dict:
    """Sales per labour hour, and the rota against the clock.

    Two numbers that need each other. Sales per hour says whether the
    staffing was worth it; adherence says whether the staffing that was
    planned is the staffing that happened. A business that reads the
    first without the second congratulates itself on a productive day
    that was actually a day two people did not turn up.
    """
    when = when or time.time()
    start_ts = _midnight(when) - (days - 1) * DAY
    start = _day_key(start_ts)
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM day_facts WHERE region=? AND day>=? AND closed=0",
        (region, start))]
    worked = sum(r["labour_minutes"] for r in rows) / 60
    rev = sum(r["revenue_cents"] for r in rows)
    per_day = [{"day": r["day"], "cents": int(r["revenue_cents"]
                                              / (r["labour_minutes"] / 60))}
               for r in rows if r["labour_minutes"] >= 60]

    planned = kept = missed = 0
    late = []
    try:
        for sh in con.execute(
                "SELECT s.id, s.user_id, s.starts, s.ends FROM"
                " scheduled_shifts s WHERE s.published=1 AND s.starts>=?"
                "  AND s.starts<?", (start_ts, when)):
            planned += 1
            got = con.execute(
                "SELECT clock_in FROM shifts WHERE user_id=? AND clock_in>=?"
                " AND clock_in<? ORDER BY clock_in LIMIT 1",
                (sh["user_id"], sh["starts"] - 3 * 3600,
                 sh["ends"])).fetchone()
            if got is None:
                missed += 1
                continue
            kept += 1
            # Late is measured in minutes past the start, not "was late":
            # five minutes is weather and forty is a rota nobody read.
            mins = (got["clock_in"] - sh["starts"]) / 60
            if mins > 5:
                late.append(round(mins))
    except Exception:                                        # noqa: BLE001
        planned = 0
    return {
        "hours": round(worked, 1),
        "revenue_cents": rev,
        "per_hour_cents": int(rev / worked) if worked else 0,
        "days_measured": len(per_day),
        "best_day": max(per_day, key=lambda x: x["cents"])
        if per_day else None,
        "rota": {
            "planned": planned, "kept": kept, "missed": missed,
            "adherence_pct": round(kept / planned * 100, 1)
            if planned else None,
            "late": len(late),
            "median_late_min": int(sorted(late)[len(late) // 2])
            if late else None,
        },
    }
