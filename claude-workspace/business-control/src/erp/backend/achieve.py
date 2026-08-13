"""Achievements: company milestones computed from real operating data.
Once earned they persist in the achievements table (and fire a notification),
even if the underlying numbers later dip."""
from . import db, notify


def _n(con, sql, *args) -> int:
    return con.execute(sql, args).fetchone()[0] or 0


def _prog(n, target, label):
    return n >= target, f"{min(n, target)}/{target} {label}"


def _golden(con, cfg):
    best = 0.0
    for region in cfg["regions"]:
        reach = (_n(con, "SELECT COUNT(*) FROM stores WHERE active=1 AND"
                        " region=?", region) +
                 _n(con, "SELECT COUNT(*) FROM outreach WHERE region=? AND"
                         " stage='stocked'", region))
        prospects = _n(con, "SELECT COUNT(*) FROM outreach WHERE region=? AND"
                            " stage IN ('lead','contacted','sampled')", region)
        if reach + prospects:
            best = max(best, reach / (reach + prospects))
    return best >= 0.75, f"best region {int(best * 100)}%/75% penetration"


DEFS = [
    ("first_sale", "First Sale", "Take your first order", "🧾",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM orders WHERE"
                             " status!='cancelled'"), 1, "orders")),
    ("century_club", "Century Club", "100 orders on the books", "💯",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM orders WHERE"
                             " status!='cancelled'"), 100, "orders")),
    ("grand", "First Grand", "$1,000 in lifetime revenue", "💵",
     lambda c, f: _prog(_n(c, "SELECT COALESCE(SUM(subtotal_cents),0) FROM"
                             " orders WHERE status!='cancelled'") // 100,
                        1000, "dollars")),
    ("big_time", "Big Time", "$10,000 in lifetime revenue", "🏦",
     lambda c, f: _prog(_n(c, "SELECT COALESCE(SUM(subtotal_cents),0) FROM"
                             " orders WHERE status!='cancelled'") // 100,
                        10000, "dollars")),
    ("ab_pioneer", "Lab Coat", "Launch your first A/B experiment", "🧪",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM experiments"), 1,
                        "experiments")),
    ("proven_winner", "Proven Winner", "Finish an experiment with a winner",
     "🏁",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM experiments WHERE"
                             " status='done' AND winner_variant_id IS NOT"
                             " NULL"), 1, "winners")),
    ("influencer_army", "Influencer Army", "3 affiliates spreading the word",
     "📣",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM affiliates"), 3,
                        "affiliates")),
    ("word_of_mouth", "Word of Mouth", "First affiliate-referred order", "🗣️",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM referrals"), 1,
                        "referred orders")),
    ("road_warrior", "Road Warrior", "Complete your first route", "🚚",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM routes WHERE"
                             " status='done'"), 1, "routes")),
    ("long_haul", "Long Haul", "1,000 km of completed routes", "🛣️",
     lambda c, f: _prog(int(_n(c, "SELECT COALESCE(SUM(total_km),0) FROM"
                                  " routes WHERE status='done'")), 1000, "km")),
    ("shelf_space", "Shelf Space", "15 stores carrying the brand", "🏪",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM stores WHERE active=1"),
                        15, "stores")),
    ("full_crew", "Full Crew", "3 employees on the time clock", "👥",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM users WHERE"
                             " role='employee' AND active=1"), 3, "employees")),
    ("event_horizon", "Event Horizon", "Staff your first in-person event",
     "🎪",
     lambda c, f: _prog(_n(c, "SELECT COUNT(*) FROM shifts WHERE event_id"
                             " IS NOT NULL"), 1, "event shifts")),
    ("promo_hit", "Promo Hit", "One promo QR scanned 25 times", "🔥",
     lambda c, f: _prog(_n(c, "SELECT COALESCE(MAX(n),0) FROM (SELECT"
                             " COUNT(*) n FROM promo_scans GROUP BY"
                             " promo_id)"), 25, "scans")),
    ("golden_region", "Golden Territory",
     "Push any region to 75% market penetration", "🥇", _golden),
]


def check(con, cfg) -> list[dict]:
    """Evaluate every definition, unlock (and notify) new ones, return all."""
    unlocked = {r["key"]: r["unlocked_at"] for r in
                con.execute("SELECT * FROM achievements").fetchall()}
    out = []
    for key, name, desc, icon, fn in DEFS:
        earned, progress = fn(con, cfg)
        at = unlocked.get(key)
        if earned and at is None:
            at = db.now()
            con.execute("INSERT OR IGNORE INTO achievements(key, unlocked_at)"
                        " VALUES(?,?)", (key, at))
            con.commit()
            notify.push(con, f"🏆 Achievement unlocked: {name}", desc,
                        kind="achievement", dedup=f"ach:{key}")
        out.append({"key": key, "name": name, "desc": desc, "icon": icon,
                    "progress": "done" if at else progress,
                    "unlocked_at": at})
    out.sort(key=lambda a: (a["unlocked_at"] is None,
                            -(a["unlocked_at"] or 0)))
    return out
