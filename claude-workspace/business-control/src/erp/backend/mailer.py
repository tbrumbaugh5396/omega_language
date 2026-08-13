"""SMTP email + marketing playbooks.

With no SMTP host configured every send is recorded in email_log with status
'dry' — the full pipeline (targeting, dedup, content) runs and is inspectable,
nothing leaves the machine. Configure data/config.json smtp (or the Admin tab)
to go live. Playbooks run on the notification sweep and dedup weekly/monthly
so a customer is never nagged twice for the same thing."""
import smtplib
import time
from email.message import EmailMessage

from . import db

DAY = 86400


def send(cfg: dict, to: str, subject: str, text: str) -> str:
    s = cfg.get("smtp", {})
    if not s.get("host"):
        return "dry"
    try:
        msg = EmailMessage()
        msg["From"] = cfg.get("email_from", "no-reply@localhost")
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        with smtplib.SMTP(s["host"], int(s.get("port", 587)),
                          timeout=15) as srv:
            if s.get("starttls", True):
                srv.starttls()
            if s.get("username"):
                srv.login(s["username"], s.get("password", ""))
            srv.send_message(msg)
        return "sent"
    except Exception as e:
        return f"error: {e}"[:200]


def log_and_send(con, cfg, user_id: int, email: str, kind: str,
                 subject: str, text: str, dedup: str) -> bool:
    """Send at most once per dedup key; previously *errored* (or crashed
    mid-send) attempts are retried on later sweeps, so a half-configured SMTP
    never permanently burns an email. 'dry' and 'sent' are terminal.
    Returns True when this call performed a successful (sent/dry) send."""
    cur = con.execute(
        "INSERT OR IGNORE INTO email_log(user_id,kind,dedup_key,subject,"
        " status,created_at) VALUES(?,?,?,?,?,?)",
        (user_id, kind, dedup, subject, "pending", db.now()))
    con.commit()
    if not cur.rowcount:
        row = con.execute("SELECT status FROM email_log WHERE dedup_key=?",
                          (dedup,)).fetchone()
        if row is None or not str(row["status"]).startswith(
                ("error", "pending")):
            return False
    status = send(cfg, email, subject, text)
    con.execute("UPDATE email_log SET status=? WHERE dedup_key=?",
                (status, dedup))
    con.commit()
    return status in ("sent", "dry")


def run_playbooks(con, cfg) -> None:
    books = cfg.get("email_playbooks", {})
    now = time.time()
    week = int(now // (7 * DAY))
    month = int(now // (30 * DAY))
    brand = cfg.get("brand_name", "Business Control")

    if books.get("abandoned_cart", True):
        rows = con.execute(
            "SELECT u.id, u.name, u.email, MAX(e.created_at) t FROM events e"
            " JOIN users u ON u.id=e.user_id"
            " WHERE e.step='add_to_cart' AND u.email!='' AND u.active=1"
            " GROUP BY u.id").fetchall()
        for r in rows:
            if not (now - 48 * 3600 <= r["t"] <= now - 3600):
                continue
            ordered = con.execute(
                "SELECT 1 FROM orders WHERE user_id=? AND created_at>=?",
                (r["id"], r["t"])).fetchone()
            if ordered:
                continue
            log_and_send(
                con, cfg, r["id"], r["email"], "abandoned_cart",
                f"You left something tasty behind at {brand}",
                f"Hi {r['name'].split()[0]},\n\nYour cart is still waiting — "
                "come back and finish checking out before it sells out.\n\n"
                f"— {brand}", f"cart:{r['id']}:{week}")

    if books.get("winback", True):
        rows = con.execute(
            "SELECT u.id, u.name, u.email, MAX(o.created_at) t FROM orders o"
            " JOIN users u ON u.id=o.user_id"
            " WHERE u.email!='' AND u.active=1 AND o.status!='cancelled'"
            " GROUP BY u.id").fetchall()
        for r in rows:
            if now - r["t"] < 30 * DAY:
                continue
            log_and_send(
                con, cfg, r["id"], r["email"], "winback",
                f"We miss you at {brand}",
                f"Hi {r['name'].split()[0]},\n\nIt's been a while — your "
                "favorites are stocked and there's new stuff to try.\n\n"
                f"— {brand}", f"winback:{r['id']}:{month}")


def blast(con, cfg, promo, url: str) -> dict:
    """Manual playbook: email an active promo to every customer with an email."""
    rows = con.execute(
        "SELECT id, name, email FROM users WHERE email!='' AND active=1"
        " AND role IN ('customer','distributor','influencer')").fetchall()
    sent = skipped = 0
    brand = cfg.get("brand_name", "Business Control")
    for r in rows:
        did = log_and_send(
            con, cfg, r["id"], r["email"], "blast",
            f"{promo['name']} — {brand}",
            f"Hi {r['name'].split()[0]},\n\n{promo['body'] or promo['name']}"
            + (f"\n{promo['discount_pct']}% off." if promo["discount_pct"]
               else "") + f"\n\n{url}\n\n— {brand}",
            f"blast:{promo['id']}:{r['id']}")
        sent += did
        skipped += not did
    return {"targeted": len(rows), "sent": sent, "already_sent": skipped}
