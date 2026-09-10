"""Automation: when this happens, do that.

The install already announces everything that matters — an order paid, a
ticket opened, stock below par, a document signed — and already has
places to send those announcements. What it has never had is a way for
the business to say what should *happen* as a result, without somebody
writing code. That gap is why every small business ends up with a person
whose job is to notice things.

A rule is four parts: the event it listens for, the conditions that
narrow it, the action, and whether it is on. Rules run off the event bus,
in the same fan-out as Discord and the integrations, which means they
inherit its one hard promise: **a listener must never break the thing it
heard**. An automation that throws does not fail the order.

The action list is short and stays short, for the same reason the agent's
tool list is short. An engine that can do anything is a way to arrange,
by accident and at three in the morning, an outcome nobody would have
approved on purpose. So automations may raise attention, open work, and
tell an outside system. They may not spend money, publish anything, mail
a customer, or change a record's state. If a rule looks like it wants to,
what it actually wants is to open a ticket for a person.

Two things that stop a rule becoming a problem:

  **A cooldown.** A rule that fires on every order fires a lot. Each rule
  carries a minimum gap between runs, defaulting to a minute, so a busy
  Saturday cannot turn one misconfigured webhook into a thousand.

  **A log.** Every run is recorded with what it decided and what came
  back, because an automation you cannot see is indistinguishable from a
  bug in the thing it acted on.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS automation_rules (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  event TEXT NOT NULL,
  conditions TEXT DEFAULT '[]',            -- JSON [{field, op, value}]
  action TEXT NOT NULL,                    -- see ACTIONS
  config TEXT DEFAULT '{}',                -- JSON, per action
  active INTEGER DEFAULT 1,
  cooldown_sec INTEGER DEFAULT 60,
  runs INTEGER DEFAULT 0,
  last_run REAL DEFAULT 0,
  last_ok INTEGER DEFAULT 1,
  created_by TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS automation_rules_event ON automation_rules(event);

CREATE TABLE IF NOT EXISTS automation_runs (
  id INTEGER PRIMARY KEY,
  rule_id INTEGER NOT NULL,
  event TEXT DEFAULT '',
  matched INTEGER DEFAULT 0,
  ok INTEGER DEFAULT 0,
  detail TEXT DEFAULT '',
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS automation_runs_rule ON automation_runs(rule_id, at);
"""

# What a rule may listen for. The same list the integrations use, because
# they are the same events; a rule that waited for something nothing
# raises would sit there looking configured.
EVENTS = {
    "order.created": "an order is placed",
    "order.paid": "an order is paid",
    "order.updated": "an order changes",
    "customer.created": "somebody opens an account",
    "subscriber.created": "somebody subscribes",
    "enquiry.created": "a partner enquiry arrives",
    "ticket.created": "a support ticket opens",
    "inventory.low": "stock drops below par",
    "review.created": "a review is left",
    "document.signed": "a document is signed",
    "product.created": "a product is added",
    "product.updated": "a product changes",
    "gate.passed": "a client project passes a gate",
    "plan.started": "a plan starts",
    "direction.chosen": "a client chooses a brand direction",
}

# Raise attention, open work, tell an outside system. Nothing that
# spends, publishes, mails a customer or changes a record.
ACTIONS = {
    "notify": {
        "label": "Tell the team",
        "what": "Raises a notification in the app. The cheapest possible "
                "action and usually the right one.",
        "fields": [("title", "Headline", True),
                   ("body", "Detail", False)],
    },
    "ticket": {
        "label": "Open a ticket",
        "what": "Puts a real item on the support board, so the thing that "
                "happened becomes somebody's work rather than somebody's "
                "memory.",
        "fields": [("title", "Ticket title", True),
                   ("body", "Detail", False),
                   ("priority", "Priority", False)],
    },
    "email_office": {
        "label": "Email the office",
        "what": "Sends to an address you type here. Deliberately not the "
                "customer's: an automation that mails customers is a "
                "campaign, and campaigns are written by people.",
        "fields": [("to", "Address here at the business", True),
                   ("subject", "Subject", True),
                   ("body", "Body", False)],
    },
    "webhook": {
        "label": "Send it somewhere",
        "what": "POSTs the event as JSON to a URL you control, with an "
                "optional bearer token. For the system this one does not "
                "know about.",
        "fields": [("url", "URL to POST to", True),
                   ("token", "Bearer token, if it needs one", False)],
    },
}

OPS = {
    "eq": "is", "ne": "is not", "gt": "is more than", "lt": "is less than",
    "contains": "contains", "present": "is set at all",
}
MAX_RUNS_LOGGED = 200


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return auth.office(user, "settings")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "automations are an owner's screen")


# ---------- deciding ----------

def _value(payload: dict, field: str):
    """Dotted lookup, so a rule can reach `customer.email` without this
    module knowing the shape of every event."""
    cur = payload
    for part in str(field).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def matches(conditions, payload: dict) -> bool:
    """All conditions must hold. A rule with none matches every instance
    of its event, which is the common case and should not need a
    condition that says so."""
    for c in conditions or []:
        got = _value(payload, c.get("field", ""))
        op = c.get("op", "eq")
        want = c.get("value", "")
        if op == "present":
            if got in (None, "", [], {}):
                return False
            continue
        if got is None:
            return False
        if op in ("gt", "lt"):
            a, b = _num(got), _num(want)
            if a is None or b is None:
                return False
            if op == "gt" and not a > b:
                return False
            if op == "lt" and not a < b:
                return False
            continue
        a, b = str(got).strip().lower(), str(want).strip().lower()
        if op == "eq" and a != b:
            return False
        if op == "ne" and a == b:
            return False
        if op == "contains" and b not in a:
            return False
    return True


def _fill(text: str, event: str, payload: dict) -> str:
    """`{field}` in a rule's text becomes the value from the event. A
    headline that cannot say which order it is about makes the reader
    open every order."""
    out = str(text or "")
    for key in set(__import__("re").findall(r"\{([\w.]+)\}", out)):
        val = _value(payload, key)
        out = out.replace("{" + key + "}",
                          "" if val is None else str(val)[:200])
    return out.replace("{event}", event)


# ---------- doing ----------

def _do(con, rule, event: str, payload: dict) -> tuple:
    cfg = json.loads(rule["config"] or "{}")
    action = rule["action"]

    if action == "notify":
        from . import notify
        notify.push(con, _fill(cfg.get("title", ""), event, payload)[:200]
                    or f"Automation: {rule['name']}",
                    _fill(cfg.get("body", ""), event, payload)[:400],
                    kind="automation")
        return True, "told the team"

    if action == "ticket":
        from . import tickets as _tk
        _COL = _tk.COLUMNS[0] if isinstance(_tk.COLUMNS, (list, tuple)) else "backlog"
        _PRIO = "normal" if "normal" in _tk.PRIORITIES else _tk.PRIORITIES[0]
        title = _fill(cfg.get("title", ""), event, payload)[:200] \
            or f"Automation: {rule['name']}"
        cur = con.execute(
            "INSERT INTO tickets(title,body,col,priority,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (title, _fill(cfg.get("body", ""), event, payload)[:4000],
             _COL, (str(cfg.get("priority", "")).strip().lower()
                    if str(cfg.get("priority", "")).strip().lower()
                    in _tk.PRIORITIES else _PRIO),
             db.now(), db.now()))
        con.commit()
        return True, f"opened ticket #{cur.lastrowid}"

    if action == "email_office":
        from . import mailer
        from .main import CFG
        to = str(cfg.get("to", "")).strip()
        if "@" not in to:
            return False, "no address to send to"
        status = mailer.send_logged(
            con, CFG, to,
            _fill(cfg.get("subject", ""), event, payload)[:200] or rule["name"],
            _fill(cfg.get("body", ""), event, payload)[:4000]
            or json.dumps(payload, indent=1)[:2000],
            "automation")
        return True, f"emailed {to} ({status})"

    if action == "webhook":
        url = str(cfg.get("url", "")).strip()
        if not url.startswith("https://") and not url.startswith("http://"):
            return False, "that is not a URL"
        headers = {"Content-Type": "application/json"}
        if cfg.get("token"):
            headers["Authorization"] = "Bearer " + str(cfg["token"])
        body = json.dumps({"event": event, "rule": rule["name"],
                           "data": payload}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return True, f"posted, {r.status}"
        except urllib.error.HTTPError as e:
            return False, f"{e.code} from {urllib.parse.urlsplit(url).netloc}"
        except Exception as e:                               # noqa: BLE001
            return False, str(e)[:200]

    return False, f"no action called {action!r}"


def run_for(con, event: str, payload: dict) -> int:
    """Every active rule listening for this event. Returns how many acted."""
    acted = 0
    try:
        rules = con.execute(
            "SELECT * FROM automation_rules WHERE event=? AND active=1",
            (event,)).fetchall()
    except Exception:                                        # noqa: BLE001
        return 0
    now = time.time()
    for rule in rules:
        try:
            if not matches(json.loads(rule["conditions"] or "[]"), payload):
                continue
            if rule["last_run"] and now - rule["last_run"] < (
                    rule["cooldown_sec"] or 0):
                con.execute(
                    "INSERT INTO automation_runs(rule_id,event,matched,ok,"
                    " detail,at) VALUES(?,?,1,1,'skipped: inside its cooldown',?)",
                    (rule["id"], event, now))
                con.commit()
                continue
            ok, detail = _do(con, rule, event, payload)
            con.execute(
                "INSERT INTO automation_runs(rule_id,event,matched,ok,detail,at)"
                " VALUES(?,?,1,?,?,?)",
                (rule["id"], event, int(ok), str(detail)[:400], now))
            con.execute(
                "UPDATE automation_rules SET runs=runs+1, last_run=?,"
                " last_ok=? WHERE id=?", (now, int(ok), rule["id"]))
            con.commit()
            acted += 1
        except Exception as e:                               # noqa: BLE001
            try:
                con.execute(
                    "INSERT INTO automation_runs(rule_id,event,matched,ok,"
                    " detail,at) VALUES(?,?,1,0,?,?)",
                    (rule["id"], event, str(e)[:400], now))
                con.commit()
            except Exception:                                # noqa: BLE001
                pass
    return acted


def emit(event: str, payload: dict) -> None:
    """Called from the event bus. Off-thread and swallowing everything,
    because the order matters and the automation does not."""
    if event not in EVENTS:
        return

    def go():
        con = db.connect()
        try:
            run_for(con, event, payload)
        except Exception:                                    # noqa: BLE001
            pass
        finally:
            con.close()
    from . import tenancy
    threading.Thread(target=tenancy.with_tenant(tenancy.CURRENT.get(), go),
                     daemon=True).start()


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


def _shape(r) -> dict:
    d = dict(r)
    d["conditions"] = json.loads(d["conditions"] or "[]")
    # The config may hold a token. It is never returned; the screen is
    # told only that one is set.
    cfg = json.loads(d["config"] or "{}")
    d["has_token"] = bool(cfg.pop("token", ""))
    d["config"] = cfg
    d["event_label"] = EVENTS.get(d["event"], d["event"])
    d["action_label"] = ACTIONS.get(d["action"], {}).get("label", d["action"])
    return d


@router.get("/api/automation")
def automation_page(user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    return {
        "rules": [_shape(r) for r in con.execute(
            "SELECT * FROM automation_rules ORDER BY active DESC, name"
            ).fetchall()],
        "events": [{"k": k, "label": v} for k, v in EVENTS.items()],
        "actions": [{"k": k, "label": v["label"], "what": v["what"],
                     "fields": [{"k": f[0], "label": f[1], "required": f[2]}
                                for f in v["fields"]]}
                    for k, v in ACTIONS.items()],
        "ops": [{"k": k, "label": v} for k, v in OPS.items()],
        "runs": [dict(r) for r in con.execute(
            "SELECT r.*, a.name FROM automation_runs r"
            " LEFT JOIN automation_rules a ON a.id=r.rule_id"
            " ORDER BY r.id DESC LIMIT ?", (MAX_RUNS_LOGGED,)).fetchall()],
    }


class RuleBody(BaseModel):
    id: int = 0
    name: str
    event: str
    conditions: list = []
    action: str
    config: dict = {}
    active: bool = True
    cooldown_sec: int = 60


def _clean(body: RuleBody, con, existing=None) -> tuple:
    if body.event not in EVENTS:
        raise HTTPException(400, f"nothing raises {body.event!r}")
    if body.action not in ACTIONS:
        raise HTTPException(
            400, f"no action called {body.action!r}. Automations may raise "
                 "attention, open work and tell an outside system — nothing "
                 "that spends, publishes or mails a customer.")
    if not body.name.strip():
        raise HTTPException(400, "a rule needs a name you will recognise")
    if body.cooldown_sec < 0 or body.cooldown_sec > 86400:
        raise HTTPException(400, "a cooldown is 0 seconds to a day")
    conds = []
    for c in body.conditions or []:
        op = c.get("op", "eq")
        if op not in OPS:
            raise HTTPException(400, f"no condition called {op!r}")
        if not str(c.get("field", "")).strip():
            raise HTTPException(400, "a condition needs a field")
        conds.append({"field": str(c["field"])[:80], "op": op,
                      "value": str(c.get("value", ""))[:200]})
    spec = ACTIONS[body.action]
    cfg = dict(json.loads(existing["config"]) if existing else {})
    for k, label, required in spec["fields"]:
        if k in body.config and str(body.config[k]).strip():
            cfg[k] = str(body.config[k])[:2000]
        if required and not cfg.get(k):
            raise HTTPException(400, f"{label} is needed for this action")
    # An action change must not carry the previous one's settings.
    if existing and existing["action"] != body.action:
        cfg = {k: v for k, v in cfg.items()
               if k in {f[0] for f in spec["fields"]}}
    return json.dumps(conds), json.dumps(cfg)


@router.post("/api/automation/rules")
def rule_save(body: RuleBody, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    existing = None
    if body.id:
        existing = con.execute("SELECT * FROM automation_rules WHERE id=?",
                               (body.id,)).fetchone()
        if existing is None:
            raise HTTPException(404, "no such rule")
    conds, cfg = _clean(body, con, existing)
    if body.id:
        con.execute(
            "UPDATE automation_rules SET name=?, event=?, conditions=?,"
            " action=?, config=?, active=?, cooldown_sec=? WHERE id=?",
            (body.name.strip()[:120], body.event, conds, body.action, cfg,
             int(body.active), body.cooldown_sec, body.id))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO automation_rules(name,event,conditions,action,config,"
        " active,cooldown_sec,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (body.name.strip()[:120], body.event, conds, body.action, cfg,
         int(body.active), body.cooldown_sec, user["name"], db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/automation/rules/{rid}")
def rule_delete(rid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    con.execute("DELETE FROM automation_rules WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}


class TestBody(BaseModel):
    payload: dict = {}


@router.post("/api/automation/rules/{rid}/test")
def rule_test(rid: int, body: TestBody, user=Depends(current_user),
              con=Depends(get_con)):
    """Fire a rule against a payload you supply, ignoring its cooldown.

    Worth its own route: a rule nobody has ever seen work is a rule
    somebody wrote and hoped about, and the first real event is a bad
    time to discover the URL was wrong.
    """
    _require(user)
    rule = con.execute("SELECT * FROM automation_rules WHERE id=?",
                       (rid,)).fetchone()
    if rule is None:
        raise HTTPException(404, "no such rule")
    payload = body.payload or {"id": 0, "test": True}
    hit = matches(json.loads(rule["conditions"] or "[]"), payload)
    if not hit:
        return {"ok": True, "matched": False,
                "detail": "the conditions did not match that payload, so "
                          "nothing ran"}
    ok, detail = _do(con, rule, rule["event"], payload)
    con.execute(
        "INSERT INTO automation_runs(rule_id,event,matched,ok,detail,at)"
        " VALUES(?,?,1,?,?,?)",
        (rid, rule["event"], int(ok), f"test: {detail}"[:400], time.time()))
    con.commit()
    return {"ok": ok, "matched": True, "detail": detail}
