"""The studio's own numbers, read off work that was already recorded.

Nothing here is measured on purpose. Every engagement already carries a
ladder of gates with the moment each one passed — derived from the
signature on the document where there is one, and from a manual
confirmation where there is not — and a dates table holding what was
planned against what actually happened, with the reason it moved. That
is a pipeline, a conversion funnel, a cycle time and a delivery record
already; it was just never added up.

The four questions it answers:

  where is the money      value by stage, and how much of it is stuck
  what converts           how far engagements get, gate by gate
  how long it takes       days between gates, and start to signature
  do we deliver           planned against actual, and why it moved

Plus the one nobody asks until it is too late: how much of the business
is one client. A studio with 60% of its revenue in one engagement is a
studio one phone call from a bad year, and that is a number you want on
a screen long before the call.
"""
import statistics
import time

from .engagements import GATES, _parse_day, resolve_gates

DAY = 86400
# The gate that means the work was actually sold. Everything before it is
# a conversation; everything after is delivery, and mixing the two makes
# a win rate that flatters whichever end has more rows in it.
WON_GATE = "contract_signed"


def _days(a: float, b: float) -> float:
    return (b - a) / DAY


def snapshot(con, when: float = 0) -> dict:
    when = when or time.time()
    engs = [dict(r) for r in con.execute(
        "SELECT * FROM engagements ORDER BY id")]
    labels = {g[0]: g[1] for g in GATES}
    order = [g[0] for g in GATES]

    live, reached, times, cycles, deals = [], {k: 0 for k in order}, {}, [], []
    won = lost = 0
    for e in engs:
        gates = resolve_gates(con, e["id"])
        passed = {g["gate"]: g["passed_at"] for g in gates if g["passed_at"]}
        prev_key, prev_at = None, e["created_at"]
        for k in order:
            if k in passed:
                reached[k] += 1
                gap = _days(prev_at, passed[k])
                if gap >= 0:
                    times.setdefault(k, []).append(gap)
                prev_key, prev_at = k, passed[k]
        is_won = WON_GATE in passed
        if is_won:
            won += 1
            deals.append(e["value_cents"] or 0)
            if e["created_at"]:
                cycles.append(_days(e["created_at"], passed[WON_GATE]))
        if (e["status"] or "") in ("lost", "declined"):
            lost += 1
        if (e["status"] or "") not in ("archived", "closed", "lost"):
            # Where it actually is: the first gate it has not passed.
            at = next((k for k in order if k not in passed), "")
            live.append({
                "id": e["id"], "name": e["name"], "stage": at,
                "stage_label": labels.get(at, "done"),
                "value_cents": e["value_cents"] or 0,
                "monthly_cents": e["monthly_cents"] or 0,
                "age_days": round(_days(e["created_at"], when), 1)
                if e["created_at"] else 0,
                "idle_days": round(_days(max(passed.values()), when), 1)
                if passed else round(_days(e["created_at"], when), 1)
                if e["created_at"] else 0,
                "won": is_won,
            })

    by_stage = {}
    for x in live:
        s = by_stage.setdefault(x["stage"], {
            "gate": x["stage"], "label": x["stage_label"], "n": 0,
            "value_cents": 0, "monthly_cents": 0, "oldest_idle": 0})
        s["n"] += 1
        s["value_cents"] += x["value_cents"]
        s["monthly_cents"] += x["monthly_cents"]
        s["oldest_idle"] = max(s["oldest_idle"], x["idle_days"])
    stages = [by_stage[k] for k in order if k in by_stage]
    if "" in by_stage:
        stages.append(dict(by_stage[""], label="delivered"))

    total = len(engs)
    funnel = [{"gate": k, "label": labels[k], "reached": reached[k],
               "pct": round(reached[k] / total * 100, 1) if total else 0,
               "median_days": round(statistics.median(times[k]), 1)
               if times.get(k) else None}
              for k in order]
    return {
        "engagements": total, "live": len(live), "won": won, "lost": lost,
        "win_rate_pct": round(won / total * 100, 1) if total else None,
        "open_value_cents": sum(x["value_cents"] for x in live
                                if not x["won"]),
        "delivering_value_cents": sum(x["value_cents"] for x in live
                                      if x["won"]),
        "open_monthly_cents": sum(x["monthly_cents"] for x in live),
        "avg_deal_cents": int(sum(deals) / len(deals)) if deals else 0,
        "median_cycle_days": round(statistics.median(cycles), 1)
        if cycles else None,
        "stages": stages, "funnel": funnel,
        "stuck": sorted([x for x in live if not x["won"]],
                        key=lambda x: -x["idle_days"])[:5],
        "concentration": concentration(engs),
        "delivery": delivery(con, engs, when),
    }


def concentration(engs: list) -> dict:
    """How much of the business is one client.

    Reported on both books, because they fail differently: losing the
    biggest build costs a quarter you can see coming, and losing the
    biggest retainer costs every month afterwards.
    """
    def share(field):
        vals = sorted(((e["name"], e[field] or 0) for e in engs
                       if (e["status"] or "") not in ("archived", "lost")),
                      key=lambda x: -x[1])
        tot = sum(v for _, v in vals)
        if not tot:
            return None
        top = vals[0]
        return {"top_name": top[0], "top_cents": top[1],
                "total_cents": tot,
                "top_pct": round(top[1] / tot * 100, 1),
                "top3_pct": round(sum(v for _, v in vals[:3]) / tot * 100, 1)}
    return {"build": share("value_cents"), "monthly": share("monthly_cents")}


def delivery(con, engs: list, when: float) -> dict:
    """Planned against actual, and why it moved.

    A date that moved with a reason written next to it is a project being
    managed. A date that moved silently is one that will move again, so
    the two are counted apart.
    """
    slips, ontime, late, moved_why = [], 0, 0, {}
    for e in engs:
        for d in con.execute(
                "SELECT label, planned, actual, moved_because"
                " FROM engagement_dates WHERE engagement_id=?", (e["id"],)):
            p, a = _parse_day(d["planned"]), _parse_day(d["actual"])
            if d["moved_because"]:
                key = d["moved_because"].strip()[:60]
                moved_why[key] = moved_why.get(key, 0) + 1
            if not p or not a:
                continue
            days = round(_days(p, a), 1)
            slips.append(days)
            if days <= 0:
                ontime += 1
            else:
                late += 1
    launches = []
    for e in engs:
        t = _parse_day(e["launch_target"] or "")
        if not t:
            continue
        gates = {g["gate"]: g["passed_at"] for g in resolve_gates(con, e["id"])
                 if g["passed_at"]}
        got = gates.get("handover_accepted") or gates.get("final_invoice_paid")
        if got:
            launches.append({"name": e["name"], "days": round(_days(t, got), 1)})
    return {
        "dated": len(slips), "on_time": ontime, "late": late,
        "on_time_pct": round(ontime / len(slips) * 100, 1) if slips else None,
        "median_slip_days": round(statistics.median(slips), 1)
        if slips else None,
        "launches": launches,
        "launch_on_time_pct": round(
            sum(1 for x in launches if x["days"] <= 0) / len(launches) * 100, 1)
        if launches else None,
        "reasons": sorted(({"why": k, "n": v} for k, v in moved_why.items()),
                          key=lambda x: -x["n"])[:6],
    }
