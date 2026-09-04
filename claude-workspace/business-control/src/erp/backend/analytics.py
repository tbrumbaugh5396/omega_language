"""Regional rollups, funnel with drop-off detection, engagement fall-off."""
import time

from . import config, supply

DAY = 86400.0


def regions(con, days: int = 30) -> list[dict]:
    since = time.time() - days * DAY
    rows = con.execute(
        "SELECT region,"
        " COUNT(*) orders,"
        " SUM(subtotal_cents) revenue_cents,"
        " SUM(CASE WHEN kind='distributor' THEN 1 ELSE 0 END) distributor_orders"
        " FROM orders WHERE created_at>=? AND status!='cancelled'"
        " GROUP BY region", (since,)).fetchall()
    by_region = {r["region"]: dict(r) for r in rows}
    visits = con.execute(
        "SELECT region, COUNT(DISTINCT visitor_id) visitors FROM events"
        " WHERE created_at>=? AND step='visit' GROUP BY region",
        (since,)).fetchall()
    for v in visits:
        by_region.setdefault(v["region"], {"region": v["region"], "orders": 0,
                                           "revenue_cents": 0,
                                           "distributor_orders": 0})
        by_region[v["region"]]["visitors"] = v["visitors"]
    stores = con.execute(
        "SELECT region, COUNT(*) stores FROM stores WHERE active=1"
        " GROUP BY region").fetchall()
    for s in stores:
        by_region.setdefault(s["region"], {"region": s["region"], "orders": 0,
                                           "revenue_cents": 0,
                                           "distributor_orders": 0})
        by_region[s["region"]]["stores"] = s["stores"]
    out = []
    for name, d in by_region.items():
        d.setdefault("visitors", 0)
        d.setdefault("stores", 0)
        d["revenue_cents"] = d.get("revenue_cents") or 0
        out.append(d)
    out.sort(key=lambda d: -d["revenue_cents"])
    return out


def funnel(con, days: int = 30, region: str = "") -> dict:
    """Distinct visitors per step, step-to-step drop, and the worst drop-off."""
    since = time.time() - days * DAY
    steps = []
    for step in config.FUNNEL_STEPS:
        q = ("SELECT COUNT(DISTINCT visitor_id) c FROM events"
             " WHERE step=? AND created_at>=?")
        args = [step, since]
        if region:
            q += " AND region=?"
            args.append(region)
        c = con.execute(q, args).fetchone()["c"]
        steps.append({"step": step, "visitors": c})
    worst = None
    for i in range(1, len(steps)):
        prev, cur = steps[i - 1]["visitors"], steps[i]["visitors"]
        drop = 1 - (cur / prev) if prev else 0.0
        steps[i]["drop_rate"] = round(drop, 3)
        if prev and (worst is None or drop > worst["drop_rate"]):
            worst = {"from": steps[i - 1]["step"], "to": steps[i]["step"],
                     "drop_rate": round(drop, 3)}
    return {"days": days, "region": region or "all", "steps": steps,
            "worst_dropoff": worst}


def pnl(con, cfg: dict, days: int = 30) -> dict:
    """Profit & loss for the period from what the system actually recorded:
    orders (revenue), referrals (commissions), shifts (labor), routes
    (logistics). COGS/wage/km-cost assumptions come from config."""
    now = time.time()
    since = now - days * DAY
    revenue = con.execute(
        "SELECT COALESCE(SUM(subtotal_cents),0) c FROM orders"
        " WHERE created_at>=? AND status!='cancelled'", (since,)).fetchone()["c"]
    commissions = con.execute(
        "SELECT COALESCE(SUM(commission_cents),0) c FROM referrals"
        " WHERE created_at>=?", (since,)).fetchone()["c"]
    hours = con.execute(
        "SELECT COALESCE(SUM(COALESCE(s.clock_out,?) - s.clock_in),0)/3600.0 h"
        " FROM shifts s JOIN users u ON u.id=s.user_id"
        " WHERE s.clock_in>=? AND u.employment='employee'",
        (now, since)).fetchone()["h"]
    crows = con.execute(
        "SELECT r.id, COUNT(rs.seq) stops FROM routes r"
        " JOIN trucks t ON t.id=r.truck_id"
        " JOIN users u ON u.id=t.driver_user_id"
        " LEFT JOIN route_stops rs ON rs.route_id=r.id"
        " WHERE r.created_at>=? AND r.status='done'"
        " AND u.employment='contractor' GROUP BY r.id",
        (since,)).fetchall()
    contractor = sum(cfg.get("contractor_per_route_cents", 0)
                     + c["stops"] * cfg.get("contractor_per_stop_cents", 0)
                     for c in crows)
    km = con.execute(
        "SELECT COALESCE(SUM(total_km),0) k FROM routes WHERE created_at>=?"
        " AND status!='planned'", (since,)).fetchone()["k"]
    # Cost of goods, measured where the recipe says what a unit costs and
    # estimated where it doesn't. Reporting the split rather than one number
    # matters: a flat percentage of revenue is an assumption wearing a
    # result's clothes, and it can't tell you a product is sold at a loss.
    # What the stock that actually left cost. Not the recipe priced
    # today, and not an average over everything the product has ever
    # cost — the parcels that shipped, at what those parcels cost. Where
    # the ledger has it, it is the real number rather than the best
    # available guess, and the two are told apart below.
    shipped = con.execute(
        "SELECT COALESCE(SUM(-m.cost_cents),0) AS cents,"
        " COALESCE(SUM(m.unknown_qty),0) AS unknown"
        " FROM inventory_moves m WHERE m.created_at>=? AND m.qty<0"
        "  AND m.reason LIKE 'order:%'", (since,)).fetchone()
    ledger_cogs = int(shipped["cents"] or 0)
    ledger_unknown = float(shipped["unknown"] or 0)

    measured_cogs, measured_rev = 0, 0
    costs = supply.unit_costs(con)
    if costs:
        rows = con.execute(
            "SELECT oi.product_id, SUM(oi.qty) qty,"
            " SUM(oi.qty * oi.unit_price_cents) rev FROM order_items oi"
            " JOIN orders o ON o.id=oi.order_id"
            " WHERE o.created_at>=? AND o.status!='cancelled'"
            " GROUP BY oi.product_id", (since,)).fetchall()
        for r in rows:
            c = costs.get(r["product_id"])
            if not c:
                continue
            measured_cogs += int(r["qty"] * c["per_unit_cents"])
            measured_rev += r["rev"]
    est_rev = max(0, revenue - measured_rev)
    cogs = measured_cogs + est_rev * cfg.get("cogs_bps", 4500) // 10000
    # The ledger wins where it has an answer. It is the only one of the
    # three that describes a thing that happened rather than a rule about
    # what things usually cost.
    if ledger_cogs > 0:
        cogs = ledger_cogs + (est_rev * cfg.get("cogs_bps", 4500) // 10000
                              if ledger_unknown else 0)
    labor = int(hours * cfg.get("hourly_wage_cents", 1800))
    logistics_cost = int(km * cfg.get("cost_per_km_cents", 85))
    gross = revenue - cogs
    net = gross - commissions - labor - logistics_cost - contractor
    by_region = con.execute(
        "SELECT region, COALESCE(SUM(subtotal_cents),0) revenue_cents"
        " FROM orders WHERE created_at>=? AND status!='cancelled'"
        " GROUP BY region ORDER BY revenue_cents DESC", (since,)).fetchall()
    return {"days": days, "revenue_cents": revenue, "cogs_cents": cogs,
            "cogs_shipped_cents": ledger_cogs,
            "cogs_unknown_units": round(ledger_unknown, 2),
            "cogs_basis": ("shipped" if ledger_cogs > 0
                           else "recipe" if measured_cogs else "assumed"),
            "cogs_measured_cents": measured_cogs,
            "cogs_estimated_cents": cogs - measured_cogs,
            "cogs_measured_pct": round(measured_rev / revenue * 100)
            if revenue else 0,
            "gross_cents": gross, "commissions_cents": commissions,
            "labor_hours": round(hours, 1), "labor_cents": labor,
            "contractor_routes": len(crows), "contractor_cents": contractor,
            "logistics_km": round(km, 1), "logistics_cents": logistics_cost,
            "net_cents": net,
            "margin_pct": round(net / revenue * 100, 1) if revenue else 0.0,
            "by_region": [dict(r) for r in by_region],
            "assumptions": {"cogs_bps": cfg.get("cogs_bps"),
                            "recipes_priced": len(costs),
                            "hourly_wage_cents": cfg.get("hourly_wage_cents"),
                            "cost_per_km_cents": cfg.get("cost_per_km_cents")}}


LEVELS = ((0.75, "gold"), (0.40, "silver"), (0.0, "bronze"))


def game(con, cfg: dict) -> dict:
    """The owners' map view: per-region penetration, level, momentum, and a
    playbook of actions the app can actually execute."""
    now = time.time()
    since = now - 30 * DAY
    out = []
    for region in cfg["regions"]:
        stores = con.execute(
            "SELECT COUNT(*) c FROM stores WHERE active=1 AND region=?",
            (region,)).fetchone()["c"]
        prospects = con.execute(
            "SELECT COUNT(*) c FROM outreach WHERE region=? AND stage IN"
            " ('lead','contacted','sampled')", (region,)).fetchone()["c"]
        stocked = con.execute(
            "SELECT COUNT(*) c FROM outreach WHERE region=? AND stage='stocked'",
            (region,)).fetchone()["c"]
        revenue = con.execute(
            "SELECT COALESCE(SUM(subtotal_cents),0) c FROM orders"
            " WHERE region=? AND created_at>=? AND status!='cancelled'",
            (region, since)).fetchone()["c"]
        prev_revenue = con.execute(
            "SELECT COALESCE(SUM(subtotal_cents),0) c FROM orders"
            " WHERE region=? AND created_at>=? AND created_at<?"
            " AND status!='cancelled'",
            (region, since - 30 * DAY, since)).fetchone()["c"]
        reach = stores + stocked
        penetration = reach / (reach + prospects) if (reach + prospects) else 0.0
        level = next(name for cut, name in LEVELS if penetration >= cut)
        has_route = con.execute(
            "SELECT COUNT(*) c FROM routes r JOIN route_stops rs ON"
            " rs.route_id=r.id JOIN stores s ON s.id=rs.store_id"
            " WHERE s.region=? AND r.status='planned'", (region,)).fetchone()["c"]
        playbook = []
        if prospects:
            playbook.append({"action": "outreach",
                             "label": f"Work {prospects} open prospect(s)"})
        if stores >= 2 and not has_route:
            playbook.append({"action": "auto_route",
                             "label": "Plan a coverage route"})
        if prev_revenue and revenue < 0.9 * prev_revenue:
            playbook.append({"action": "experiment",
                             "label": "Revenue slipping — launch an A/B test"})
        out.append({"region": region, "stores": stores, "stocked": stocked,
                    "prospects": prospects,
                    "penetration": round(penetration, 2), "level": level,
                    "revenue_30d_cents": revenue,
                    "revenue_prev_30d_cents": prev_revenue,
                    "playbook": playbook})
    p = pnl(con, cfg)
    running_exp = con.execute(
        "SELECT COUNT(*) c FROM experiments WHERE status='running'"
    ).fetchone()["c"]
    staffing = [dict(r) for r in con.execute(
        "SELECT job, employment, COUNT(*) n FROM users WHERE active=1 AND"
        " role='employee' GROUP BY job, employment ORDER BY n DESC")]
    company_pen = (sum(r["penetration"] for r in out) / len(out)) if out else 0
    return {"regions": out, "pnl": p, "staffing": staffing,
            "company": {
                "level": next(n for c, n in LEVELS if company_pen >= c),
                "penetration": round(company_pen, 2),
                "net_30d_cents": p["net_cents"],
                "running_experiments": running_exp}}


def engagement(con, cfg: dict, days: int = 28) -> dict:
    """Daily event counts plus a fall-off alert comparing the last 7 days
    against the prior 7, overall and per funnel step."""
    now = time.time()
    since = now - days * DAY
    rows = con.execute(
        "SELECT CAST((created_at - ?) / ? AS INTEGER) day, step, COUNT(*) c"
        " FROM events WHERE created_at>=? GROUP BY day, step",
        (since, DAY, since)).fetchall()
    daily = [{"day": i, "total": 0} for i in range(days)]
    per_step = {s: [0] * days for s in config.FUNNEL_STEPS}
    for r in rows:
        d = min(max(r["day"], 0), days - 1)
        daily[d]["total"] += r["c"]
        if r["step"] in per_step:
            per_step[r["step"]][d] += r["c"]

    ratio = cfg.get("falloff_ratio", 0.75)

    def weeks(series):
        last = sum(series[-7:])
        prior = sum(series[-14:-7])
        falling = bool(prior >= 20 and last < ratio * prior)
        return {"last_7": last, "prior_7": prior, "falling_off": falling}

    totals = [d["total"] for d in daily]
    alerts = []
    overall = weeks(totals)
    if overall["falling_off"]:
        alerts.append({"scope": "overall", **overall})
    step_summary = {}
    for step, series in per_step.items():
        w = weeks(series)
        step_summary[step] = w
        if w["falling_off"]:
            alerts.append({"scope": step, **w})
    return {"days": days, "daily": daily, "overall": overall,
            "per_step": step_summary, "alerts": alerts}
