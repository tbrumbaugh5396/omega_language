"""Web Push: real phone/desktop notifications even with the app closed.

VAPID keys are generated once into data/vapid_private.pem. Browsers subscribe
through their platform push service (FCM / Mozilla / Apple); we post encrypted
payloads to those endpoints via pywebpush. Sending happens on a daemon thread
so requests never block on push-service round-trips."""
import base64
import json
import threading

from . import config, db

def VAPID_PEM():
    # Per tenant: browsers bind a subscription to the server key, so
    # two businesses sharing one key would be one business to the
    # push service.
    from . import tenancy
    return tenancy.data_dir() / "vapid_private.pem"


def public_key() -> str:
    """Create-if-missing and return the applicationServerKey (urlsafe b64)."""
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
    from . import tenancy
    tenancy.data_dir().mkdir(parents=True, exist_ok=True)
    if not VAPID_PEM().exists():
        v = Vapid()
        v.generate_keys()
        v.save_key(str(VAPID_PEM()))
    v = Vapid.from_file(str(VAPID_PEM()))
    raw = v.public_key.public_bytes(serialization.Encoding.X962,
                                    serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def save_subscription(con, user_id: int, sub: dict) -> None:
    con.execute(
        "INSERT OR REPLACE INTO push_subscriptions(endpoint,user_id,sub,"
        " created_at) VALUES(?,?,?,?)",
        (sub["endpoint"], user_id, json.dumps(sub), db.now()))
    con.commit()


def drop_subscription(con, endpoint: str) -> None:
    con.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
    con.commit()


def send(cfg: dict, title: str, body: str = "",
         user_ids: list[int] | None = None, admins: bool = False) -> None:
    """Queue a push to specific users and/or every admin. Fire-and-forget."""
    con = db.connect()
    try:
        subs = []
        if user_ids:
            marks = ",".join("?" * len(user_ids))
            subs += con.execute(
                f"SELECT sub FROM push_subscriptions WHERE user_id IN ({marks})",
                user_ids).fetchall()
        if admins:
            subs += con.execute(
                "SELECT ps.sub FROM push_subscriptions ps JOIN users u"
                " ON u.id=ps.user_id WHERE u.is_admin=1").fetchall()
    finally:
        con.close()
    payloads = list({s["sub"] for s in subs})   # dedup a user in both groups
    if not payloads or not VAPID_PEM().exists():
        return
    from . import tenancy
    threading.Thread(
        target=tenancy.with_tenant(tenancy.CURRENT.get(), _deliver),
        daemon=True,
                     args=(cfg, payloads, title, body)).start()


def _deliver(cfg, payloads, title, body):
    from pywebpush import webpush, WebPushException
    gone = []
    data = json.dumps({"title": title, "body": body})
    for raw in payloads:
        sub = json.loads(raw)
        try:
            webpush(sub, data, vapid_private_key=str(VAPID_PEM()),
                    vapid_claims={"sub": cfg.get("vapid_subject",
                                                 "mailto:owner@localhost")},
                    timeout=8)
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", 0)
            if code in (404, 410):
                gone.append(sub["endpoint"])
        except Exception:
            pass
    if gone:
        con = db.connect()
        try:
            for ep in gone:
                con.execute("DELETE FROM push_subscriptions WHERE endpoint=?",
                            (ep,))
            con.commit()
        finally:
            con.close()
