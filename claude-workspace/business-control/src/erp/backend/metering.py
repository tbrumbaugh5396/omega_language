"""What the metered units actually cost the business that hit them.

Three numbers decide whether somebody should buy another till, and until
now this software knew none of them.

The first is the refusal. A limit is enforced at the door, which is the
right place — but a 409 that is raised and forgotten is a person standing
at a counter with a queue in front of them, and by the time anyone talks
about the plan, nobody remembers it happened. Every refusal is now
written down, with what they were allowed and what was already running,
because a business arguing about whether it needs a fourth lane should be
arguing over a number rather than a feeling.

The second is the peak. Registers are metered on tills open AT ONCE, so
counting them at the moment somebody happens to look answers a question
nobody asked. Saturday at noon is the number that matters, and it is
recoverable exactly: every session already records when it opened and
when it closed, and the busiest moment of a day is a sweep over those two
columns. Nothing new has to be stored to know it.

The third is whether the refusal was ever answered. A refusal followed by
a raise is a sale; a refusal followed by silence is a customer who walked
out of a queue, and the two look identical in a count. So a raise stamps
the refusals it answers, and the gap between them is the honest measure
of how much the limit is costing.
"""
import time

# The table lives in db.REFUSAL_TABLE, with every other schema, so an
# install that upgrades into this version has it before its first refusal
# rather than after it.

DAY = 86400.0


def record(con, user, kind: str, cap: int, in_use: int) -> None:
    """Write down a refusal. Never raises.

    This runs inside the exception path of a request that is about to
    fail anyway, and a bookkeeping error that turns "you have reached
    your limit" into "internal server error" would be a strictly worse
    day for the person at the counter.
    """
    uid, who = 0, ""
    try:
        # A user here is a sqlite3.Row as often as a dict, and a Row has
        # no .get() — which would throw, be swallowed below, and lose the
        # refusal to save a name. Whose refusal it was is worth having;
        # it is not worth the refusal itself.
        uid, who = int(user["id"]), str(user["name"])[:60]
    except Exception:                                        # noqa: BLE001
        pass
    try:
        con.execute(
            "INSERT INTO limit_refusals(at,kind,cap,in_use,user_id,who)"
            " VALUES(?,?,?,?,?,?)",
            (time.time(), kind, int(cap), int(in_use), uid, who))
        con.commit()
    except Exception:                                        # noqa: BLE001
        pass


def answer(con, kind: str) -> int:
    """A raise answers every refusal of that kind still waiting.

    Not only the most recent one: three people refused the same fourth
    till on the same afternoon were all asking for the same thing, and
    counting that as one answered ask understates what the limit cost.
    """
    try:
        cur = con.execute(
            "UPDATE limit_refusals SET answered_at=? WHERE kind=?"
            " AND answered_at=0", (time.time(), kind))
        con.commit()
        return cur.rowcount or 0
    except Exception:                                        # noqa: BLE001
        return 0


def refusals(con, kind: str, days: int = 30) -> dict:
    """How often this limit turned somebody away, and whether we fixed it."""
    since = time.time() - days * DAY
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT at, cap, in_use, who, answered_at FROM limit_refusals"
            " WHERE kind=? AND at>? ORDER BY at DESC", (kind, since))]
    except Exception:                                        # noqa: BLE001
        return {"count": 0, "days": days, "answered": 0, "unanswered": 0,
                "last": 0, "on_days": 0, "recent": [], "known": False}
    by_day: dict[str, int] = {}
    for r in rows:
        by_day[_daystamp(r["at"])] = by_day.get(_daystamp(r["at"]), 0) + 1
    answered = sum(1 for r in rows if r["answered_at"])
    return {"count": len(rows), "days": days, "answered": answered,
            "unanswered": len(rows) - answered,
            "last": rows[0]["at"] if rows else 0,
            "on_days": len(by_day), "by_day": by_day,
            "recent": rows[:8], "known": True}


def _daystamp(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _midnight(ts: float) -> float:
    """The start of the local day `ts` falls in. The shop's day, not the
    server's: a Saturday peak reported on Friday is a peak nobody can go
    and look at a rota to check."""
    t = time.localtime(ts)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def peak_registers(con, days: int = 30, cap: int = 0) -> dict:
    """The most tills open at the same moment, per day and overall.

    A sweep, not a sample: every open is +1 and every close is -1, sorted
    by time, and the running total's high-water mark is the answer. A
    session still open counts to now — it is open, and a shop that has had
    four lanes running since this morning has four lanes running.

    Ties in timestamp are ordered closes-before-opens, so a lane handed
    from one cashier to the next at exactly the same second is one lane
    rather than briefly two. Getting that backwards invents a peak nobody
    ever ran, and invented peaks sell tills people do not need.
    """
    now = time.time()
    since = now - days * DAY
    try:
        rows = con.execute(
            "SELECT opened_at, closed_at FROM register_sessions"
            " WHERE opened_at>? OR closed_at=0 OR closed_at>?",
            (since, since)).fetchall()
    except Exception:                                        # noqa: BLE001
        return {"known": False, "peak": 0, "days": days, "by_day": {},
                "at_cap_days": 0, "peak_at": 0}
    events = []
    for r in rows:
        events.append((float(r["opened_at"]), 1))
        events.append((float(r["closed_at"]) or now, -1))
    # A day with no opening and no closing in it is not a quiet day if a
    # lane was already running through it. Somebody who leaves a
    # self-serve lane up over a weekend was using it all weekend, and a
    # sweep that only looks where the events are reports Sunday as zero.
    # So each midnight is its own event, carrying whatever is still open.
    # Local midnights, recomputed each step rather than added to: the
    # clocks change twice a year and a day that is 23 hours long would
    # otherwise walk every later marker into the wrong day.
    edge = _midnight(since)
    while edge <= now:
        events.append((edge, 0))
        edge = _midnight(edge + 36 * 3600)
    events.sort(key=lambda e: (e[0], e[1]))          # closes first on a tie
    live, peak, peak_at = 0, 0, 0.0
    by_day: dict[str, int] = {}
    for when, delta in events:
        live += delta
        if when >= since:
            d = _daystamp(when)
            if live > by_day.get(d, 0):
                by_day[d] = live
            if live > peak:
                peak, peak_at = live, when
    at_cap = sum(1 for v in by_day.values() if cap and v >= cap)
    return {"known": True, "peak": peak, "peak_at": peak_at, "days": days,
            "by_day": by_day, "at_cap_days": at_cap,
            "busiest_day": max(by_day, key=lambda k: by_day[k])
                           if by_day else ""}


def by_store(con, days: int = 30) -> list:
    """The peak, per location.

    The limit is counted across the business, but the queue is at one
    shop. "You peaked at four tills" is true and useless to a manager
    deciding whether to open a fifth lane in Camden; four at once across
    three shops is a different business from four at once in one.

    Staffed and self-serve are counted apart because they are bought for
    different reasons — one is a wage and one is a machine — and a lane
    of each costs the same $19 while meaning opposite things.
    """
    now = time.time()
    since = now - days * DAY
    try:
        rows = con.execute(
            "SELECT r.store_id, r.opened_at, r.closed_at, r.self_serve,"
            " COALESCE(s.name,'') AS store FROM register_sessions r"
            " LEFT JOIN stores s ON s.id=r.store_id"
            " WHERE r.opened_at>? OR r.closed_at=0 OR r.closed_at>?",
            (since, since)).fetchall()
    except Exception:                                        # noqa: BLE001
        return []
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["store_id"] or 0, r["store"] or ""), []).append(r)
    out = []
    for (sid, name), rs in groups.items():
        events, staffed, selfserve, open_now = [], 0, 0, 0
        for r in rs:
            events.append((float(r["opened_at"]), 1))
            events.append((float(r["closed_at"]) or now, -1))
            if not r["closed_at"]:
                open_now += 1
            if float(r["opened_at"]) >= since:
                if r["self_serve"]:
                    selfserve += 1
                else:
                    staffed += 1
        events.sort(key=lambda e: (e[0], e[1]))
        live, peak = 0, 0
        for when, delta in events:
            live += delta
            if when >= since and live > peak:
                peak = live
        out.append({"store_id": sid, "store": name or (
            "not tied to a location" if not sid else f"store {sid}"),
            "peak": peak, "open_now": open_now, "sessions": staffed + selfserve,
            "staffed": staffed, "self_serve": selfserve})
    out.sort(key=lambda x: (-x["peak"], -x["sessions"]))
    return out


# A tablet registered this week and not yet used is being set up, not
# wasted. Calling it waste on day two is how a report teaches people to
# ignore it.
SETTLING_DAYS = 7


def kiosks_idle(con, days: int = 30) -> dict:
    """Tablets that are active, billed, and have not been touched.

    `last_seen` was declared when kiosks were and never written to, so
    until now every kiosk looked equally unused. It is stamped on each
    punch that names one. That means this report is only as old as the
    stamping: a kiosk in daily use since long before still reads as never
    seen until somebody clocks in on it, so a fleet with no history says
    "not known yet" rather than accusing every tablet of being idle.
    """
    now = time.time()
    cut = now - days * DAY
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT k.kiosk_id, k.label, k.created_at, k.last_seen,"
            " COALESCE(s.name,'') AS store FROM kiosks k"
            " LEFT JOIN stores s ON s.id=k.store_id"
            " WHERE k.active=1 ORDER BY k.last_seen")]
    except Exception:                                        # noqa: BLE001
        return {"known": False, "idle": [], "live": 0, "settling": 0}
    idle, live, settling = [], 0, 0
    for r in rows:
        seen = float(r["last_seen"] or 0)
        if seen >= cut:
            live += 1
            continue
        if (now - float(r["created_at"] or 0)) < SETTLING_DAYS * DAY:
            settling += 1
            continue
        r["never"] = not seen
        r["days_idle"] = 0 if not seen else int((now - seen) / DAY)
        idle.append(r)
    return {"known": True, "idle": idle, "live": live, "settling": settling,
            "total": len(rows), "days": days,
            "ever_seen": any(float(r["last_seen"] or 0) for r in rows)}


def pressure(con, kind: str, cap: int, used: int, days: int = 30) -> dict:
    """One reading per metered unit: how tight is this, really.

    `peak` is only honest for registers, where history exists. Locations,
    seats and kiosks are counts of things that exist rather than things
    running at once, so their peak is their present, and this says so
    rather than dressing a current count up as a measurement.
    """
    ref = refusals(con, kind, days)
    if kind == "registers":
        pk = peak_registers(con, days, cap)
    else:
        pk = {"known": False, "peak": used, "days": days, "by_day": {},
              "at_cap_days": 0, "peak_at": 0,
              "why": "counted as it stands: this is a thing that exists, "
                     "not a thing that runs at once, so there is no busier "
                     "moment to find"}
    head = max(0, cap - pk["peak"])
    where = by_store(con, days) if kind == "registers" else []
    tablets = kiosks_idle(con, days) if kind == "kiosks" else {}
    return {
        "by_store": where, "kiosks": tablets,
        "kind": kind, "cap": cap, "used": used,
        "peak": pk["peak"], "peak_known": pk["known"],
        "peak_at": pk.get("peak_at", 0),
        "busiest_day": pk.get("busiest_day", ""),
        "at_cap_days": pk.get("at_cap_days", 0),
        "by_day": pk.get("by_day", {}),
        "refused": ref["count"], "refused_on_days": ref["on_days"],
        "refused_last": ref["last"], "unanswered": ref["unanswered"],
        "recent": ref["recent"], "why_no_peak": pk.get("why", ""),
        "headroom": head,
        "verdict": _verdict(kind, cap, used, ref, pk, head, tablets),
        "idle_count": len(tablets.get("idle", [])),
    }


def _verdict(kind: str, cap: int, used: int, ref: dict, pk: dict,
             head: int, tablets: dict | None = None) -> str:
    """Say the thing the numbers mean, in the words somebody would use.

    A dashboard that shows a client six figures and leaves them to infer
    the sentence has moved the work rather than done it.

    The idle-tablet clause is appended to whatever else is true rather
    than competing with it. Somebody asking for a fourth tablet while two
    of the three they have sit untouched is the single most useful
    sentence this can produce, and letting a refusal outrank it would
    suppress it exactly when it matters most.
    """
    idle = (tablets or {}).get("idle", [])
    note = ""
    if idle:
        never = sum(1 for k in idle if k["never"])
        note = (f"{len(idle)} of {tablets['total']} tablets not used in "
                f"{tablets['days']} days"
                + (f", {never} never at all" if never else ""))
    tail = f" \u00b7 {note}" if note else ""

    if used > cap:
        return (f"{used} in use against {cap} covered — over by "
                f"{used - cap}, which is a bill rather than a refusal: "
                f"these were already here when the limit was set" + tail)
    if note and not ref["count"]:
        return note + " — paid for and switched on, standing there"
    if ref["count"] and ref["unanswered"]:
        return (f"turned away {ref['count']} time"
                f"{'' if ref['count'] == 1 else 's'} in {ref['days']} days"
                f" — {ref['unanswered']} of those still unanswered" + tail)
    if ref["count"]:
        return (f"turned away {ref['count']} time"
                f"{'' if ref['count'] == 1 else 's'}, since resolved" + tail)
    if pk["known"] and pk.get("at_cap_days"):
        return (f"at the limit on {pk['at_cap_days']} day"
                f"{'' if pk['at_cap_days'] == 1 else 's'} without being "
                f"refused — the next busy one will be refused" + tail)
    if pk["known"] and cap and pk["peak"] and head >= max(2, cap // 2):
        return (f"busiest moment used {pk['peak']} of {cap} — there is "
                f"room here that is being paid for" + tail)
    if not head and cap:
        return "full: the next one asked for will be refused" + tail
    return ("comfortable" + tail) if tail else "comfortable"
