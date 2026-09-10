"""Intake: what arrives from outside as records rather than as events.

Three kinds of thing a small organisation collects elsewhere and then
retypes here: the answers to a form, the gifts made to it, and the test
results its learners earn on somebody else's platform. Each has one
tray on the intake screen, and each row can be turned into the thing it
was really about — a form response into an enquiry or a student, a gift
into a donor in the address book, a score into a line on the learner's
record and, when it is a pass, an achievement they can see.

How each arrives is whatever the source actually offers:

  * Google Forms has an API, so responses are pulled by form id; an Apps
    Script trigger can also push each submission as it lands (the
    snippet is on the screen). Both land in the same tray, once each.
  * Network for Good notifies by webhook through its own automations or
    Zapier, and exports a CSV. Both are taken.
  * GED Manager and NorthStar publish no API; both export a CSV of
    results. The column headings differ by export and by year, so the
    reader looks for what a column MEANS — the learner's email, the
    subject, the score, the date — rather than for a fixed name.

A row that cannot be matched to a person is kept and marked, never
guessed at: a score on the wrong student's record is worse than a score
in a tray.
"""
import json
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db
from . import integrations as IG

TABLES = """
CREATE TABLE IF NOT EXISTS form_responses (
  id INTEGER PRIMARY KEY,
  provider TEXT DEFAULT 'google_forms',
  form_id TEXT NOT NULL,
  form_title TEXT DEFAULT '',
  external_id TEXT NOT NULL,
  name TEXT DEFAULT '',
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  answers TEXT DEFAULT '{}',               -- JSON {question: answer}
  submitted_at REAL DEFAULT 0,
  handled_as TEXT DEFAULT '',              -- enquiry | student | customer
  handled_id INTEGER DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(provider, form_id, external_id)
);

CREATE TABLE IF NOT EXISTS gifts (
  id INTEGER PRIMARY KEY,
  provider TEXT DEFAULT 'network4good',
  external_id TEXT NOT NULL,
  donor TEXT DEFAULT '',
  email TEXT DEFAULT '',
  amount_cents INTEGER DEFAULT 0,
  currency TEXT DEFAULT 'USD',
  fund TEXT DEFAULT '',
  recurring INTEGER DEFAULT 0,
  note TEXT DEFAULT '',
  user_id INTEGER DEFAULT 0,               -- the donor's account here
  at REAL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(provider, external_id)
);

CREATE TABLE IF NOT EXISTS test_results (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,                  -- gedmanager | northstar
  external_id TEXT NOT NULL,
  user_id INTEGER DEFAULT 0,               -- 0 = unmatched
  taker TEXT DEFAULT '',
  email TEXT DEFAULT '',
  subject TEXT DEFAULT '',
  score REAL DEFAULT 0,
  max_score REAL DEFAULT 0,
  passed INTEGER DEFAULT 0,
  certificate TEXT DEFAULT '',
  taken_at REAL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(provider, external_id)
);
"""

GED_PASS = 145           # per subject, GED Testing Service
GED_COLLEGE_READY = 165


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    """Form responses, gifts and results all become people, so this is
    the customer-list grant."""
    return auth.office(user, "settings", "customers")

def _may_see(user) -> bool:
    return _office(user) or user["role"] in ("employee", "teacher")


# ---------- reading columns by what they mean ----------

def _col(row: dict, *wants) -> str:
    """The value of the first column whose heading contains any of the
    wanted words, case-blind. 'Learner Email', 'E-mail', 'email_address'
    all mean email."""
    low = {re.sub(r"[^a-z0-9]", "", (k or "").lower()): (v if v is not None else "")
           for k, v in row.items()}
    for w in wants:
        w = re.sub(r"[^a-z0-9]", "", w.lower())
        for k, v in low.items():
            if w in k and str(v).strip():
                return str(v).strip()
    return ""


def _when(s: str) -> float:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y",
                "%Y-%m-%d %H:%M:%S", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y %H:%M"):
        try:
            return time.mktime(time.strptime(s[:19] if "T" in s else s, fmt))
        except ValueError:
            continue
    return time.time()


def _num(s) -> float:
    m = re.search(r"-?\d+(\.\d+)?", str(s or ""))
    return float(m.group(0)) if m else 0.0


def _cents(s) -> int:
    return int(round(_num(s) * 100))


# ---------- people ----------

def _find_person(con, email: str, name: str) -> int:
    """By email first, then by exact name — and only among customers,
    because a teacher sharing a name with a learner is not that learner."""
    email = (email or "").strip().lower()
    if email:
        r = con.execute("SELECT id FROM users WHERE lower(email)=? AND active=1",
                        (email,)).fetchone()
        if r:
            return r["id"]
    name = " ".join((name or "").split())
    if name:
        rows = con.execute("SELECT id FROM users WHERE lower(name)=lower(?)"
                           " AND role='customer' AND active=1", (name,)).fetchall()
        if len(rows) == 1:
            return rows[0]["id"]
    return 0


def _make_person(con, name: str, email: str, role: str = "customer") -> int:
    have = _find_person(con, email, name)
    if have:
        return have
    name = " ".join((name or "").split())[:120] or (email.split("@")[0] if email else "")
    if not name:
        raise HTTPException(400, "a person needs a name or an email")
    cur = con.execute(
        "INSERT INTO users(name,email,role,token,created_at) VALUES(?,?,?,?,?)",
        (name, (email or "").strip().lower()[:200], role, secrets.token_urlsafe(24),
         db.now()))
    con.commit()
    return cur.lastrowid


# ---------- forms ----------

def _pick(answers: dict, *wants) -> str:
    return _col(answers, *wants)


def add_response(con, form_id: str, ext: str, answers: dict, *, form_title: str = "",
                 submitted_at: float = 0, provider: str = "google_forms") -> int:
    have = con.execute("SELECT id FROM form_responses WHERE provider=? AND form_id=?"
                       " AND external_id=?", (provider, form_id, ext)).fetchone()
    if have:
        return have["id"]
    answers = {str(k)[:200]: (", ".join(map(str, v)) if isinstance(v, list) else str(v))[:2000]
               for k, v in (answers or {}).items()}
    name = _pick(answers, "full name", "your name", "name")
    if not name:
        first, last = _pick(answers, "first"), _pick(answers, "last", "surname")
        name = f"{first} {last}".strip()
    cur = con.execute(
        "INSERT INTO form_responses(provider,form_id,form_title,external_id,name,"
        " email,phone,answers,submitted_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (provider, form_id, form_title[:200], ext, name[:120],
         _pick(answers, "email", "e-mail")[:200].lower(),
         _pick(answers, "phone", "mobile", "cell")[:40], json.dumps(answers),
         submitted_at or time.time(), time.time()))
    con.commit()
    return cur.lastrowid


def pull_forms(con) -> dict:
    from .main import CFG
    c = IG.creds(con, "google_forms")
    if not c:
        raise HTTPException(400, "connect Google Forms first")
    ids = [x.strip() for x in IG.settings(con, "google_forms").get("form_ids", "").split(",")
           if x.strip()]
    if not ids:
        raise HTTPException(400, "list at least one form id in the connection's settings")
    tok = IG.access_token(con, "google_forms", CFG)
    h = {"Authorization": f"Bearer {tok}"}
    new = 0
    for fid in ids:
        ok, form = IG._req(f"https://forms.googleapis.com/v1/forms/{fid}", headers=h)
        if not ok:
            IG.log(con, "google_forms", "pull_forms", False, f"{fid}: {form}"[:200])
            raise HTTPException(400, f"Google said: {form}")
        titles = {}
        for it in (form.get("items") or []) if isinstance(form, dict) else []:
            q = ((it.get("questionItem") or {}).get("question") or {})
            if q.get("questionId"):
                titles[q["questionId"]] = it.get("title") or q["questionId"]
        title = ((form.get("info") or {}).get("title") if isinstance(form, dict) else "") or fid
        ok2, resp = IG._req(f"https://forms.googleapis.com/v1/forms/{fid}/responses",
                            headers=h)
        if not ok2:
            raise HTTPException(400, f"Google said: {resp}")
        for r in (resp.get("responses") or []) if isinstance(resp, dict) else []:
            answers = {}
            for qid, a in (r.get("answers") or {}).items():
                vals = [x.get("value", "") for x in
                        ((a.get("textAnswers") or {}).get("answers") or [])]
                if not vals and a.get("fileUploadAnswers"):
                    vals = [x.get("fileName", "") for x in
                            a["fileUploadAnswers"].get("answers") or []]
                answers[titles.get(qid, qid)] = vals
            before = con.execute("SELECT 1 FROM form_responses WHERE form_id=?"
                                 " AND external_id=?", (fid, r.get("responseId"))).fetchone()
            add_response(con, fid, str(r.get("responseId")), answers, form_title=title,
                         submitted_at=_when((r.get("createTime") or "")[:19]))
            if before is None:
                new += 1
    IG.log(con, "google_forms", "pull_forms", True, f"{new} new")
    return {"ok": True, "new": new, "forms": len(ids)}


def inbound_form(con, body: dict) -> dict:
    """An Apps Script trigger: {form_id, form_title, responses:[{id,
    submitted_at, answers:{question: answer}}]} — or one response flat."""
    if not isinstance(body, dict):
        raise HTTPException(400, "expected a JSON object")
    fid = str(body.get("form_id") or body.get("formId") or "script")
    rows = body.get("responses")
    if rows is None:
        rows = [body]
    n = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        ext = str(r.get("id") or r.get("response_id") or r.get("timestamp")
                  or secrets.token_hex(6))
        add_response(con, fid, ext, r.get("answers") or {},
                     form_title=str(body.get("form_title") or ""),
                     submitted_at=_when(str(r.get("submitted_at") or r.get("timestamp") or "")))
        n += 1
    IG.log(con, "google_forms", "inbound", True, f"{n} response(s)")
    return {"ok": True, "received": n}


IG.INBOUND["google_forms"] = inbound_form


def handle_response(con, rid: int, kind: str, user) -> dict:
    r = con.execute("SELECT * FROM form_responses WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such response")
    if r["handled_as"]:
        return {"ok": True, "already": r["handled_as"], "id": r["handled_id"]}
    answers = json.loads(r["answers"] or "{}")
    lines = "\n".join(f"{k}: {v}" for k, v in answers.items() if v)
    if kind == "enquiry":
        cur = con.execute(
            "INSERT INTO outreach(name,region,city,stage,next_action,next_action_date,"
            " updated_at) VALUES(?,?,?,'lead',?,?,?)",
            ((r["name"] or r["email"] or "Form response")[:80],
             _pick(answers, "region", "state", "province")[:80],
             _pick(answers, "city", "town")[:80],
             f"Follow up: {r['form_title'] or 'form response'}",
             time.time() + 86400, time.time()))
        hid = cur.lastrowid
        try:
            con.execute("INSERT INTO outreach_log(outreach_id,user_id,note,created_at)"
                        " VALUES(?,?,?,?)", (hid, user["id"], lines[:4000], time.time()))
        except Exception:                                    # noqa: BLE001
            pass
    elif kind in ("student", "customer"):
        hid = _make_person(con, r["name"], r["email"])
        if kind == "student":
            from . import students as ST
            prof = ST.profile_of(con, hid)
            extra = dict(prof.get("extra") or {})
            for k, v in answers.items():
                if v and k not in extra:
                    extra[k[:60]] = v[:400]
            ST.save_profile(con, hid, {"phone": r["phone"]} if r["phone"] else {},
                            extra, user["name"])
            con.execute(
                "INSERT INTO student_log(user_id,kind,title,body,at,by_id,by_name,"
                " created_at) VALUES(?,?,?,?,?,?,?,?)",
                (hid, "note", f"Signed up via {r['form_title'] or 'a form'}",
                 lines[:2000], r["submitted_at"] or time.time(), user["id"],
                 user["name"], db.now()))
    else:
        raise HTTPException(400, "enquiry, student or customer")
    con.execute("UPDATE form_responses SET handled_as=?, handled_id=? WHERE id=?",
                (kind, hid, rid))
    con.commit()
    return {"ok": True, "id": hid}


# ---------- gifts ----------

def add_gift(con, *, ext: str, donor: str, email: str, amount_cents: int,
             currency: str = "USD", fund: str = "", recurring: bool = False,
             note: str = "", at: float = 0, provider: str = "network4good") -> int:
    if amount_cents <= 0:
        raise HTTPException(400, "a gift has an amount")
    have = con.execute("SELECT id FROM gifts WHERE provider=? AND external_id=?",
                       (provider, ext)).fetchone()
    if have:
        return have["id"]
    uid = 0
    try:
        uid = _make_person(con, donor, email, role="donor") if (donor or email) else 0
    except HTTPException:
        uid = 0
    cur = con.execute(
        "INSERT INTO gifts(provider,external_id,donor,email,amount_cents,currency,fund,"
        " recurring,note,user_id,at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (provider, ext, (donor or "")[:120], (email or "").lower()[:200], amount_cents,
         (currency or "USD")[:3].upper(), (fund or "")[:120], int(bool(recurring)),
         (note or "")[:400], uid, at or time.time(), time.time()))
    con.commit()
    return cur.lastrowid


def inbound_gift(con, body: dict) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(400, "expected a JSON object")
    rows = body.get("donations") or body.get("gifts") or [body]
    n = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        donor = (_col(r, "donor name", "donor", "name") or
                 f"{_col(r, 'first')} {_col(r, 'last')}".strip())
        amt = _col(r, "amount_cents")
        cents = int(_num(amt)) if amt else _cents(_col(r, "amount", "total"))
        add_gift(con, ext=_col(r, "transaction", "id", "reference") or secrets.token_hex(6),
                 donor=donor, email=_col(r, "email"), amount_cents=cents,
                 currency=_col(r, "currency") or "USD",
                 fund=_col(r, "designation", "fund", "campaign"),
                 recurring=_col(r, "recurring", "frequency").lower() not in ("", "no", "false", "0", "one-time", "onetime"),
                 note=_col(r, "note", "comment", "message"), at=_when(_col(r, "date", "time")))
        n += 1
    IG.log(con, "network4good", "inbound", True, f"{n} gift(s)")
    return {"ok": True, "received": n}


IG.INBOUND["network4good"] = inbound_gift


def import_gifts(con, rows: list, filename: str) -> dict:
    n, skipped = 0, []
    for i, r in enumerate(rows, 2):
        donor = (_col(r, "donor name", "donor", "name") or
                 f"{_col(r, 'first')} {_col(r, 'last')}".strip())
        cents = _cents(_col(r, "amount", "total"))
        if cents <= 0:
            skipped.append({"row": i, "why": "no amount"})
            continue
        add_gift(con, ext=_col(r, "transaction", "id", "reference") or f"{filename}:{i}",
                 donor=donor, email=_col(r, "email"), amount_cents=cents,
                 currency=_col(r, "currency") or "USD",
                 fund=_col(r, "designation", "fund", "campaign"),
                 recurring=_col(r, "recurring", "frequency").lower() not in ("", "no", "false", "0", "one-time", "onetime"),
                 note=_col(r, "note", "comment"), at=_when(_col(r, "date")))
        n += 1
    IG.log(con, "network4good", "import", True, f"{n} gift(s) from {filename}")
    return {"imported": n, "skipped": skipped}


IG.IMPORTS["network4good"] = import_gifts


# ---------- test results ----------

def _record_result(con, provider: str, ext: str, *, taker: str, email: str,
                   subject: str, score: float, max_score: float, passed: bool,
                   certificate: str, taken_at: float) -> tuple:
    """One result on one learner. Returns (result id, matched user id)."""
    have = con.execute("SELECT id, user_id FROM test_results WHERE provider=? AND"
                       " external_id=?", (provider, ext)).fetchone()
    if have:
        return have["id"], have["user_id"]
    uid = _find_person(con, email, taker)
    cur = con.execute(
        "INSERT INTO test_results(provider,external_id,user_id,taker,email,subject,"
        " score,max_score,passed,certificate,taken_at,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (provider, ext, uid, taker[:120], (email or "").lower()[:200], subject[:120],
         score, max_score, int(passed), certificate[:200], taken_at, time.time()))
    if uid:
        label = IG.PROVIDERS[provider]["label"].split(" ")[0]
        if passed:
            title = (f"{label}: {subject} — {certificate}" if certificate
                     else f"Passed {label} {subject}")
            body = f"score {score:g}" + (f" of {max_score:g}" if max_score else "")
            kind = "achievement"
        else:
            title = f"{label} {subject}: {score:g}"
            body = "not yet a pass" if score else ""
            kind = "milestone"
        con.execute(
            "INSERT INTO student_log(user_id,kind,title,body,at,by_id,by_name,"
            " created_at) VALUES(?,?,?,?,?,?,?,?)",
            (uid, kind, title[:200], body[:2000], taken_at, None, label, db.now()))
    con.commit()
    return cur.lastrowid, uid


def import_ged(con, rows: list, filename: str) -> dict:
    n, matched, skipped = 0, 0, []
    for i, r in enumerate(rows, 2):
        subject = _col(r, "subject", "test name", "test", "module")
        score_s = _col(r, "scaled score", "score")
        if not subject or not score_s:
            skipped.append({"row": i, "why": "no subject or score"})
            continue
        score = _num(score_s)
        status = _col(r, "status", "result", "outcome").lower()
        passed = ("pass" in status and "not" not in status) if status else score >= GED_PASS
        taker = (_col(r, "student name", "test taker", "candidate", "name") or
                 f"{_col(r, 'first')} {_col(r, 'last')}".strip())
        email = _col(r, "email")
        ext = _col(r, "result id", "appointment", "registration") or \
            f"{email or taker}:{subject}:{_col(r, 'date')}".lower()
        cert = "College Ready" if score >= GED_COLLEGE_READY else ""
        _, uid = _record_result(con, "gedmanager", ext, taker=taker, email=email,
                                subject=subject, score=score, max_score=200,
                                passed=passed, certificate=cert,
                                taken_at=_when(_col(r, "test date", "date")))
        n += 1
        matched += 1 if uid else 0
    IG.log(con, "gedmanager", "import", True, f"{n} result(s), {matched} matched")
    return {"imported": n, "matched": matched, "skipped": skipped}


def import_northstar(con, rows: list, filename: str) -> dict:
    n, matched, skipped = 0, 0, []
    for i, r in enumerate(rows, 2):
        subject = _col(r, "module", "assessment", "standard", "test")
        score_s = _col(r, "percent", "score", "%")
        if not subject or not score_s:
            skipped.append({"row": i, "why": "no module or score"})
            continue
        score = _num(score_s)
        status = _col(r, "passed", "pass", "result", "status").lower()
        passed = (status in ("yes", "y", "true", "1", "pass", "passed")
                  if status else score >= 85)
        cert = _col(r, "certificate", "badge")
        if cert.lower() in ("yes", "y", "true", "1"):
            cert = "certificate"
        taker = (_col(r, "learner", "student", "name") or
                 f"{_col(r, 'first')} {_col(r, 'last')}".strip())
        email = _col(r, "email")
        ext = _col(r, "result id", "assessment id", "id") or \
            f"{email or taker}:{subject}:{_col(r, 'date')}".lower()
        _, uid = _record_result(con, "northstar", ext, taker=taker, email=email,
                                subject=subject, score=score, max_score=100,
                                passed=passed, certificate=cert,
                                taken_at=_when(_col(r, "date", "completed")))
        n += 1
        matched += 1 if uid else 0
    IG.log(con, "northstar", "import", True, f"{n} result(s), {matched} matched")
    return {"imported": n, "matched": matched, "skipped": skipped}


IG.IMPORTS["gedmanager"] = import_ged
IG.IMPORTS["northstar"] = import_northstar


def match_result(con, rid: int, uid: int) -> dict:
    """The office says who an unmatched result belongs to."""
    r = con.execute("SELECT * FROM test_results WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such result")
    if r["user_id"]:
        return {"ok": True, "already": r["user_id"]}
    u = con.execute("SELECT id FROM users WHERE id=? AND active=1", (uid,)).fetchone()
    if u is None:
        raise HTTPException(404, "no such person")
    con.execute("UPDATE test_results SET user_id=? WHERE id=?", (uid, rid))
    label = IG.PROVIDERS[r["provider"]]["label"].split(" ")[0]
    if r["passed"]:
        title = (f"{label}: {r['subject']} — {r['certificate']}" if r["certificate"]
                 else f"Passed {label} {r['subject']}")
        kind, body = "achievement", f"score {r['score']:g}"
    else:
        title, kind, body = f"{label} {r['subject']}: {r['score']:g}", "milestone", ""
    con.execute(
        "INSERT INTO student_log(user_id,kind,title,body,at,by_id,by_name,created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (uid, kind, title[:200], body, r["taken_at"], None, label, db.now()))
    con.commit()
    return {"ok": True}


def results_of(con, uid: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT provider, subject, score, max_score, passed, certificate, taken_at"
        " FROM test_results WHERE user_id=? ORDER BY taken_at", (uid,)).fetchall()]


APPS_SCRIPT = """function onFormSubmit(e) {
  // Google Forms → Extensions → Apps Script. Paste, set URL, add an
  // "On form submit" trigger. Sends each submission as it lands.
  var URL = "%s";
  var answers = {};
  e.response.getItemResponses().forEach(function (ir) {
    answers[ir.getItem().getTitle()] = ir.getResponse();
  });
  UrlFetchApp.fetch(URL, {
    method: "post", contentType: "application/json",
    headers: { "X-API-Key": "%s" },
    payload: JSON.stringify({
      form_id: e.source.getId(), form_title: e.source.getTitle(),
      responses: [{ id: e.response.getId(),
                    submitted_at: e.response.getTimestamp().toISOString(),
                    answers: answers }] })
  });
}"""


# ---------- routes ----------

router = APIRouter()

from .main import base_url, current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/intake")
def intake_page(user=Depends(current_user), con=Depends(get_con)):
    """Forms and gifts. The score imports used to be here too, and are
    now their own screen: a school buys Learning for those and has no
    reason to buy Fundraising to reach them."""
    if not _may_see(user):
        raise HTTPException(403, "an office screen")
    status = {p["name"]: p for p in IG.status(con)["providers"]
              if p.get("family") == "intake"}
    key = con.execute("SELECT key FROM integration_inbound WHERE provider='google_forms'"
                      ).fetchone()
    gk = con.execute("SELECT key FROM integration_inbound WHERE provider='network4good'"
                     ).fetchone()
    base = base_url()
    resp = [dict(r) for r in con.execute(
        "SELECT * FROM form_responses ORDER BY submitted_at DESC LIMIT 200").fetchall()]
    for r in resp:
        r["answers"] = json.loads(r["answers"] or "{}")
    gifts = [dict(r) for r in con.execute(
        "SELECT * FROM gifts ORDER BY at DESC LIMIT 200").fetchall()]
    tot = con.execute("SELECT COALESCE(SUM(amount_cents),0) AS c, COUNT(*) AS n,"
                      " COUNT(DISTINCT COALESCE(NULLIF(email,''), donor)) AS donors"
                      " FROM gifts").fetchone()
    return {"connections": list(status.values()),
            "responses": resp, "gifts": gifts,
            "gift_totals": {"cents": tot["c"], "n": tot["n"], "donors": tot["donors"]},
            "forms_inbound_url": f"{base}/api/inbound/google_forms",
            "gifts_inbound_url": f"{base}/api/inbound/network4good",
            "apps_script": APPS_SCRIPT % (f"{base}/api/inbound/google_forms",
                                          key["key"] if key else "<key from the connection card>"),
            "gifts_key_ready": bool(gk)}


@router.get("/api/results")
def results_page(user=Depends(current_user), con=Depends(get_con)):
    """What a learner passed somewhere else. Its own screen, under
    Learning, because that is the capability a school actually buys —
    and teaching staff read it, which the gifts ledger is not for."""
    if not _may_see(user):
        raise HTTPException(403, "an office screen")
    status = {p["name"]: p for p in IG.status(con)["providers"]
              if p.get("family") == "results"}
    results = [dict(r) for r in con.execute(
        "SELECT t.*, u.name AS student FROM test_results t LEFT JOIN users u ON u.id=t.user_id"
        " ORDER BY t.taken_at DESC LIMIT 300").fetchall()]
    passed = sum(1 for r in results if r["passed"])
    return {"connections": list(status.values()), "results": results,
            "unmatched": sum(1 for r in results if not r["user_id"]),
            "passed": passed,
            "learners": len({r["user_id"] for r in results if r["user_id"]})}


@router.post("/api/intake/forms/pull")
def intake_pull(user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    return pull_forms(con)


class AsBody(BaseModel):
    kind: str


@router.post("/api/intake/forms/{rid}/as")
def intake_as(rid: int, body: AsBody, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    return handle_response(con, rid, body.kind, user)


class GiftBody(BaseModel):
    donor: str = ""
    email: str = ""
    amount_cents: int
    fund: str = ""
    recurring: bool = False
    note: str = ""
    at: float = 0


@router.post("/api/intake/gifts")
def intake_gift(body: GiftBody, user=Depends(current_user), con=Depends(get_con)):
    """Typed in: a cheque in the post, cash in a tin."""
    if not _office(user):
        raise HTTPException(403, "office only")
    gid = add_gift(con, ext=f"typed:{int(time.time() * 1000)}", donor=body.donor,
                   email=body.email, amount_cents=body.amount_cents, fund=body.fund,
                   recurring=body.recurring, note=body.note, at=body.at,
                   provider="typed")
    return {"ok": True, "id": gid}


class MatchBody(BaseModel):
    user_id: int


@router.post("/api/intake/results/{rid}/match")
def intake_match(rid: int, body: MatchBody, user=Depends(current_user),
                 con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    return match_result(con, rid, body.user_id)
