"""In-app notifications. Rows are created two ways: pushed directly from
endpoints when something happens (orders, check-ins, stage changes), and by
sweep(), which turns data conditions (low stock, engagement fall-off, an
experiment ready to call) into notifications with dedup keys so they fire once
per condition (weekly for recurring ones)."""
import time

from . import analytics, config, db
from . import push as webpush

WEEK = 7 * 86400
_CFG = config.load()


def push(con, title: str, body: str = "", kind: str = "info",
         user_id: int | None = None, dedup: str | None = None) -> None:
    cur = con.execute(
        "INSERT OR IGNORE INTO notifications(user_id,kind,dedup_key,title,"
        " body,created_at) VALUES(?,?,?,?,?,?)",
        (user_id, kind, dedup, title, body, db.now()))
    con.commit()
    if cur.rowcount:                       # only web-push genuinely new rows
        webpush.send(_CFG, title, body,
                     user_ids=[user_id] if user_id else None,
                     admins=user_id is None)


def for_user(con, user) -> tuple[list[dict], int]:
    rows = con.execute(
        "SELECT n.*, (r.user_id IS NOT NULL) is_read FROM notifications n"
        " LEFT JOIN notification_reads r ON r.notification_id=n.id"
        "  AND r.user_id=?"
        " WHERE n.user_id=? OR (n.user_id IS NULL AND ?)"
        " ORDER BY n.id DESC LIMIT 60",
        (user["id"], user["id"], 1 if user["is_admin"] else 0)).fetchall()
    items = [dict(r) for r in rows]
    unread = sum(1 for i in items if not i["is_read"])
    return items, unread


def mark_all_read(con, user) -> None:
    con.execute(
        "INSERT OR IGNORE INTO notification_reads(notification_id, user_id)"
        " SELECT id, ? FROM notifications"
        " WHERE user_id=? OR (user_id IS NULL AND ?)",
        (user["id"], user["id"], 1 if user["is_admin"] else 0))
    con.commit()


def sweep(con, cfg) -> None:
    """Data-driven notifications for admins. Cheap; runs on notification poll."""
    from . import achieve                     # deferred: achieve imports notify
    week = int(time.time() // WEEK)

    lows = con.execute(
        "SELECT i.store_id, i.product_id, i.qty, s.name store, p.name product"
        " FROM inventory i JOIN stores s ON s.id=i.store_id"
        " JOIN products p ON p.id=i.product_id"
        " WHERE i.qty < MAX(1, i.par / 4)").fetchall()
    for r in lows:
        push(con, f"Low stock: {r['product']} at {r['store']} ({r['qty']} left)",
             kind="inventory",
             dedup=f"low:{r['store_id']}:{r['product_id']}:{week}")
        # Also a business event, so Slack and Trello hear about it. It was
        # only ever a bell inside the app before, which meant the providers
        # that declared an interest in low stock never actually got any.
        try:
            from storefront.backend.api import fire_webhooks
            fire_webhooks("inventory.low", {
                "product": r["product"], "store": r["store"],
                "qty": r["qty"], "store_id": r["store_id"],
                "product_id": r["product_id"]})
        except Exception:
            pass

    eng = analytics.engagement(con, cfg)
    for a in eng["alerts"]:
        push(con, f"Engagement falling off: {a['scope']}",
             f"{a['last_7']} events this week vs {a['prior_7']} last week",
             kind="analytics", dedup=f"falloff:{a['scope']}:{week}")

    for e in con.execute(
            "SELECT * FROM experiments WHERE status='running'").fetchall():
        from . import abtest
        r = abtest.results(con, e, cfg)
        if r["ready"] and r["winner"] and r["winner"]["significant"]:
            push(con, f"Experiment ready to call: {e['name']}",
                 f"{r['winner']['name']} leads at "
                 f"{round(r['winner']['rate'] * 100, 1)}% — stop it to lock in"
                 " the winner", kind="experiment", dedup=f"expready:{e['id']}")

    achieve.check(con, cfg)

    from . import cycles, mailer
    cycles.sweep(con, cfg)
    mailer.run_playbooks(con, cfg)
