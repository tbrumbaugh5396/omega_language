"""Health: patients, their insurance, their records, and the day's queue.

A clinic, a therapist's practice, a school nurse, a dentist, a
counselling service — they have a front desk, a diary and a filing
cabinet, and the cabinet is the part that must not leak. This capability
is that cabinet with a lock that logs: a patient is a person in the
customer book with a health record beside it; the record holds what a
front desk and a practitioner need — insurance on file, allergies and
medications, the visits and what was noted at each, the files attached
— and every time somebody reads it the reading is written down, with
who and when, because a record whose readers are unknown is a record
that has already leaked.

What this is not, said plainly so nobody builds on the wrong idea:

  **Not a certified electronic health record.** Nothing here has been
  certified against any standard, and no claim of HIPAA, GDPR or any
  other regime's compliance is made by the software. Compliance is a
  property of the practice — its agreements, its training, its hosting
  — and this only makes the technical part possible: access is
  restricted to a named permission, every read is logged, the patient
  sees their own record and nobody else's, and nothing here is emailed.

  **Not a billing system.** Insurance is kept so the desk can see who
  the payer is and what the copay is; claims are filed elsewhere, and a
  screen that looked like it filed them would be worse than none.

  **Not a diagnostic tool.** A visit note is what the practitioner
  typed. Nothing here suggests, checks or infers anything clinical.

Appointments are the bookings capability's: a patient books a service
like anyone else, and the queue here is those appointments for today,
with a check-in state on each so the desk can see who has arrived, who
is waiting and who has been seen. The patient can check themselves in
from their portal within the window before their time, which is the
tablet on the counter without the tablet.
"""
import json
import pathlib
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS patients (
  user_id INTEGER PRIMARY KEY,             -- a person in the customer book
  mrn TEXT DEFAULT '',                     -- the practice's own number, if it has one
  birth_date TEXT DEFAULT '',              -- YYYY-MM-DD
  sex TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  address TEXT DEFAULT '',
  emergency_contact TEXT DEFAULT '',
  primary_practitioner_id INTEGER DEFAULT 0,
  allergies TEXT DEFAULT '',
  medications TEXT DEFAULT '',
  conditions TEXT DEFAULT '',
  notes TEXT DEFAULT '',                   -- the desk's, not shown to the patient
  consent_at REAL DEFAULT 0,               -- consent to keep a record, recorded
  consent_by TEXT DEFAULT '',
  portal INTEGER DEFAULT 1,                -- may the patient see their record
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS insurance_policies (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  payer TEXT NOT NULL,                     -- the insurer
  plan TEXT DEFAULT '',
  member_id TEXT DEFAULT '',
  group_no TEXT DEFAULT '',
  subscriber TEXT DEFAULT '',              -- whose policy, if not the patient's
  relationship TEXT DEFAULT 'self',        -- self|spouse|child|other
  effective TEXT DEFAULT '',               -- YYYY-MM-DD
  expires TEXT DEFAULT '',
  copay_cents INTEGER DEFAULT 0,
  payer_phone TEXT DEFAULT '',
  primary_policy INTEGER DEFAULT 1,
  verified_at REAL DEFAULT 0,
  verified_by TEXT DEFAULT '',
  note TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS insurance_who ON insurance_policies(user_id);

CREATE TABLE IF NOT EXISTS encounters (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  at REAL NOT NULL,
  kind TEXT DEFAULT 'visit',               -- visit|call|telehealth|note|result
  practitioner_id INTEGER DEFAULT 0,
  practitioner TEXT DEFAULT '',
  reason TEXT DEFAULT '',
  notes TEXT DEFAULT '',                   -- what the practitioner typed
  vitals TEXT DEFAULT '{}',                -- JSON: whatever was measured
  plan TEXT DEFAULT '',
  followup_at REAL DEFAULT 0,
  shared INTEGER DEFAULT 1,                -- visible on the patient's portal
  appointment_id INTEGER DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS encounters_who ON encounters(user_id, at);

CREATE TABLE IF NOT EXISTS health_files (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  encounter_id INTEGER DEFAULT 0,
  name TEXT NOT NULL,
  ext TEXT NOT NULL,
  mime TEXT DEFAULT '',
  bytes INTEGER DEFAULT 0,
  sha256 TEXT DEFAULT '',
  kind TEXT DEFAULT 'document',            -- document|result|image|referral|consent
  shared INTEGER DEFAULT 1,
  by_name TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS health_files_who ON health_files(user_id);

/* The day's queue: an appointment's check-in state. The appointment
   itself is the bookings capability's row. */
CREATE TABLE IF NOT EXISTS patient_checkins (
  id INTEGER PRIMARY KEY,
  appointment_id INTEGER NOT NULL UNIQUE,
  user_id INTEGER NOT NULL,
  arrived_at REAL DEFAULT 0,
  method TEXT DEFAULT 'desk',              -- desk|portal|kiosk
  state TEXT DEFAULT 'arrived',            -- arrived|waiting|with_practitioner|done|left
  note TEXT DEFAULT '',
  updated_at REAL NOT NULL
);

/* Every read of a record, by whom. Not the audit log: that records what
   changed; this records who looked, which is the question a patient asks. */
CREATE TABLE IF NOT EXISTS health_access (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,                -- the patient
  by_id INTEGER DEFAULT 0,
  by_name TEXT DEFAULT '',
  what TEXT NOT NULL,                      -- record|file:<id>|portal|insurance
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS health_access_who ON health_access(user_id, at);
"""

ENCOUNTER_KINDS = ("visit", "call", "telehealth", "note", "result")
CHECKIN_STATES = ("arrived", "waiting", "with_practitioner", "done", "left")
FILE_KINDS = ("document", "result", "image", "referral", "consent")
RELATIONSHIPS = ("self", "spouse", "child", "other")
FILE_EXT = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg",
    "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "txt": "text/plain", "csv": "text/csv",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
    "dcm": "application/dicom",
}
MAX_FILE = 25 * 1024 * 1024
CHECKIN_WINDOW = 3 * 3600          # a patient may check in this long before their time


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    """Who opens a record: the named permission, or an admin. Being
    staff is not enough — a cashier does not read charts."""
    return auth.office(user, "health")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "health records need the health permission")


def _dir():
    from . import tenancy
    d = tenancy.data_dir() / "uploads" / "health"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- the bytes on disk ----------
# A patient's file is encrypted before it touches the disk and decrypted
# on the way out: AES-256-GCM, a fresh nonce per file, the tenant's key.
# The key lives in a file of its own, mode 0600, under the tenant's data
# — or wherever BC_HEALTH_KEY_DIR points, which is how an operator keeps
# the key on a different disk from the data it unlocks. Lose the key and
# every file is noise; that is the point, and the docs say so. The
# database rows (names, notes, vitals) are NOT encrypted by this: that is
# the host's disk encryption, and a claim otherwise would be a lie.

def _key() -> bytes:
    import os
    import secrets
    from . import tenancy
    root = os.environ.get("BC_HEALTH_KEY_DIR")
    d = (pathlib.Path(root) / tenancy.CURRENT.get()) if root else (tenancy.data_dir() / "keys")
    d.mkdir(parents=True, exist_ok=True)
    kf = d / "health.key"
    if not kf.exists():
        kf.write_bytes(secrets.token_bytes(32))
        os.chmod(kf, 0o600)
    return kf.read_bytes()


def seal(data: bytes) -> bytes:
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return b"BCH1" + nonce + AESGCM(_key()).encrypt(nonce, data, b"health-file")


def unseal(blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(b"BCH1"):
        # A file written before encryption existed: served as it is, and
        # re-sealed the first time it is read.
        return blob
    nonce, body = blob[4:16], blob[16:]
    return AESGCM(_key()).decrypt(nonce, body, b"health-file")


def log_access(con, patient_id: int, user, what: str) -> None:
    con.execute("INSERT INTO health_access(user_id,by_id,by_name,what,at)"
                " VALUES(?,?,?,?,?)",
                (patient_id, user["id"], user["name"], what[:80], time.time()))


def _person(con, uid: int):
    u = con.execute("SELECT id, name, email, photo FROM users WHERE id=?"
                    " AND erased_at IS NULL", (uid,)).fetchone()
    if u is None:
        raise HTTPException(404, "no such person")
    return u


def ensure_patient(con, uid: int) -> None:
    if con.execute("SELECT 1 FROM patients WHERE user_id=?", (uid,)).fetchone() is None:
        now = time.time()
        con.execute("INSERT INTO patients(user_id,created_at,updated_at) VALUES(?,?,?)",
                    (uid, now, now))


def _age(birth: str) -> int | None:
    """None unless the string is a real calendar date."""
    import datetime
    try:
        y, m, d = (int(x) for x in birth.split("-"))
        datetime.date(y, m, d)
    except (ValueError, AttributeError):
        return None
    t = time.localtime()
    return t.tm_year - y - ((t.tm_mon, t.tm_mday) < (m, d))


def record(con, uid: int, *, for_patient: bool = False) -> dict:
    u = _person(con, uid)
    ensure_patient(con, uid)
    p = dict(con.execute("SELECT * FROM patients WHERE user_id=?", (uid,)).fetchone())
    p["age"] = _age(p["birth_date"])
    if for_patient:
        p.pop("notes", None)
    pr = con.execute("SELECT name FROM users WHERE id=?",
                     (p["primary_practitioner_id"],)).fetchone() if p["primary_practitioner_id"] else None
    p["primary_practitioner"] = pr["name"] if pr else ""
    shared = " AND shared=1" if for_patient else ""
    encounters = []
    for r in con.execute("SELECT * FROM encounters WHERE user_id=?" + shared
                         + " ORDER BY at DESC LIMIT 200", (uid,)).fetchall():
        e = dict(r)
        try:
            e["vitals"] = json.loads(r["vitals"] or "{}")
        except ValueError:
            e["vitals"] = {}
        encounters.append(e)
    files = [dict(r) for r in con.execute(
        "SELECT id, encounter_id, name, ext, mime, bytes, kind, shared, by_name,"
        " created_at FROM health_files WHERE user_id=?" + shared
        + " ORDER BY created_at DESC", (uid,)).fetchall()]
    policies = [dict(r) for r in con.execute(
        "SELECT * FROM insurance_policies WHERE user_id=? AND active=1"
        " ORDER BY primary_policy DESC, id", (uid,)).fetchall()]
    upcoming = []
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='appointments'").fetchone():
        upcoming = [dict(r) for r in con.execute(
            "SELECT a.id, a.starts, a.ends, a.state, s.name AS service, a.staff_id,"
            " c.state AS checkin_state, c.arrived_at"
            " FROM appointments a LEFT JOIN bookable_services s ON s.id=a.service_id"
            " LEFT JOIN patient_checkins c ON c.appointment_id=a.id"
            " WHERE a.user_id=? AND a.state IN ('held','confirmed') AND a.ends>?"
            " ORDER BY a.starts LIMIT 20", (uid, time.time() - 3600)).fetchall()]
        for a in upcoming:
            a["can_check_in"] = (not a["checkin_state"]
                                 and a["starts"] - CHECKIN_WINDOW <= time.time() <= a["ends"])
    out = {"person": {"id": u["id"], "name": u["name"], "email": u["email"] or "",
                      "photo": u["photo"] or ""},
           "patient": p, "insurance": policies, "encounters": encounters,
           "files": files, "appointments": upcoming}
    if not for_patient:
        out["access"] = [dict(r) for r in con.execute(
            "SELECT by_name, what, at FROM health_access WHERE user_id=?"
            " ORDER BY id DESC LIMIT 30", (uid,)).fetchall()]
    return out


def today_queue(con) -> list:
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='appointments'").fetchone() is None:
        return []
    # From the start of today to the end of it — or as far ahead as a
    # patient may check in, whichever is later, so the late-evening
    # arrival for a just-after-midnight slot is on the desk's screen.
    t = time.localtime()
    a = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    b = max(a + 86400, time.time() + CHECKIN_WINDOW)
    rows = [dict(r) for r in con.execute(
        "SELECT a.id, a.starts, a.ends, a.state, a.user_id, a.name AS booked_name,"
        " u.name AS person, s.name AS service, st.name AS practitioner,"
        " c.state AS checkin_state, c.arrived_at, c.method, c.note AS checkin_note"
        " FROM appointments a LEFT JOIN users u ON u.id=a.user_id"
        " LEFT JOIN bookable_services s ON s.id=a.service_id"
        " LEFT JOIN users st ON st.id=a.staff_id"
        " LEFT JOIN patient_checkins c ON c.appointment_id=a.id"
        " WHERE a.starts>=? AND a.starts<? AND a.state IN ('held','confirmed')"
        " ORDER BY a.starts", (a, b)).fetchall()]
    for r in rows:
        r["name"] = r["person"] or r["booked_name"] or "walk-in"
        r["waited_min"] = (int((time.time() - r["arrived_at"]) / 60)
                           if r["arrived_at"] and r["checkin_state"] in ("arrived", "waiting")
                           else 0)
    return rows


def check_in(con, appointment_id: int, *, method: str, by_user=None,
             patient_id: int = 0) -> dict:
    a = con.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "no such appointment")
    if patient_id and a["user_id"] != patient_id:
        raise HTTPException(403, "not your appointment")
    if a["state"] not in ("held", "confirmed"):
        raise HTTPException(400, f"that appointment is {a['state']}")
    now = time.time()
    if method == "portal" and not (a["starts"] - CHECKIN_WINDOW <= now <= a["ends"]):
        raise HTTPException(400, "check in from three hours before your time "
                                 "until it ends")
    if con.execute("SELECT 1 FROM patient_checkins WHERE appointment_id=?",
                   (appointment_id,)).fetchone():
        return {"ok": True, "already": True}
    if a["user_id"]:
        ensure_patient(con, a["user_id"])
    con.execute(
        "INSERT INTO patient_checkins(appointment_id,user_id,arrived_at,method,state,"
        " updated_at) VALUES(?,?,?,?,'arrived',?)",
        (appointment_id, a["user_id"] or 0, now, method, now))
    con.commit()
    return {"ok": True, "arrived_at": now}


def kiosk_check_in(con, *, name: str = "", birth_date: str = "", code: str = "") -> dict:
    """Arrival from the screen on the counter. Nobody is signed in on
    it, so the patient proves who they are with what a stranger would
    not know together — their name and date of birth — or by showing
    the person code on their ID card. It says only that they are
    checked in, never anything from the record, because a kiosk faces
    the waiting room."""
    from . import identity
    uid = 0
    if code.strip():
        parsed = identity.parse_payload(code)
        r = con.execute("SELECT id FROM users WHERE uid=? AND erased_at IS NULL",
                        (parsed,)).fetchone() if parsed else None
        uid = r["id"] if r else 0
    elif name.strip() and birth_date.strip():
        rows = con.execute(
            "SELECT u.id FROM users u JOIN patients p ON p.user_id=u.id"
            " WHERE lower(u.name)=lower(?) AND p.birth_date=? AND u.erased_at IS NULL",
            (" ".join(name.split()), birth_date.strip())).fetchall()
        uid = rows[0]["id"] if len(rows) == 1 else 0
    if not uid:
        # One answer whether the name is wrong, the date is wrong, or
        # there is no record: a kiosk that said which would be telling
        # the waiting room who is a patient here.
        raise HTTPException(404, "we could not match that — please see the desk")
    now = time.time()
    a = con.execute(
        "SELECT * FROM appointments WHERE user_id=? AND state IN ('held','confirmed')"
        " AND starts-?<=? AND ends>? ORDER BY starts LIMIT 1",
        (uid, CHECKIN_WINDOW, now, now)).fetchone()
    if a is None:
        raise HTTPException(404, "no appointment in the next three hours — please see the desk")
    out = check_in(con, a["id"], method="kiosk", patient_id=uid)
    out["first_name"] = con.execute("SELECT name FROM users WHERE id=?",
                                    (uid,)).fetchone()["name"].split()[0]
    out["at"] = a["starts"]
    return out


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/health")
def health_page(q: str = "", user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    needle = f"%{q.strip().lower()}%" if q.strip() else ""
    patients = [dict(r) for r in con.execute(
        "SELECT u.id, u.name, u.email, p.mrn, p.birth_date, p.updated_at,"
        " (SELECT MAX(at) FROM encounters e WHERE e.user_id=u.id) AS last_seen,"
        " (SELECT COUNT(*) FROM insurance_policies i WHERE i.user_id=u.id AND i.active=1) AS policies"
        " FROM patients p JOIN users u ON u.id=p.user_id WHERE u.erased_at IS NULL"
        + (" AND (lower(u.name) LIKE ? OR lower(u.email) LIKE ? OR p.mrn LIKE ?)" if needle else "")
        + " ORDER BY u.name COLLATE NOCASE LIMIT 300",
        (needle, needle, needle) if needle else ()).fetchall()]
    return {"patients": patients, "queue": today_queue(con),
            "checkin_states": list(CHECKIN_STATES),
            "encounter_kinds": list(ENCOUNTER_KINDS),
            "file_kinds": list(FILE_KINDS), "relationships": list(RELATIONSHIPS),
            "practitioners": [dict(r) for r in con.execute(
                "SELECT id, name FROM users WHERE active=1 AND (is_admin=1 OR role IN"
                " ('employee','owner','director')) ORDER BY name")],
            "counts": {"patients": _n(con, "SELECT COUNT(*) FROM patients"),
                       "seen_30d": _n(con, "SELECT COUNT(DISTINCT user_id) FROM encounters"
                                      " WHERE at>?", (time.time() - 30 * 86400,)),
                       "waiting": sum(1 for r in today_queue(con)
                                      if r["checkin_state"] in ("arrived", "waiting"))}}


def _n(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return int(r[0] or 0) if r else 0


@router.get("/api/health/people")
def health_people(q: str = "", user=Depends(current_user), con=Depends(get_con)):
    """Who could become a patient: anyone in the customer book."""
    _require(user)
    needle = f"%{q.strip().lower()}%"
    return {"people": [dict(r) for r in con.execute(
        "SELECT id, name, email FROM users WHERE erased_at IS NULL AND active=1"
        " AND role='customer' AND (lower(name) LIKE ? OR lower(email) LIKE ?)"
        " ORDER BY name LIMIT 30", (needle, needle)).fetchall()]}


@router.get("/api/health/patients/{uid}")
def patient_record(uid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    # Logged before it is read, so the log the reader sees includes them.
    log_access(con, uid, user, "record")
    con.commit()
    return record(con, uid)


class PatientBody(BaseModel):
    mrn: str = ""
    birth_date: str = ""
    sex: str = ""
    phone: str = ""
    address: str = ""
    emergency_contact: str = ""
    primary_practitioner_id: int = 0
    allergies: str = ""
    medications: str = ""
    conditions: str = ""
    notes: str = ""
    consent: bool | None = None
    portal: bool = True


@router.post("/api/health/patients/{uid}")
def patient_save(uid: int, body: PatientBody, user=Depends(current_user),
                 con=Depends(get_con)):
    _require(user)
    _person(con, uid)
    ensure_patient(con, uid)
    if body.birth_date and _age(body.birth_date) is None:
        raise HTTPException(400, "birth date as YYYY-MM-DD")
    cur = con.execute("SELECT consent_at FROM patients WHERE user_id=?", (uid,)).fetchone()
    consent_at = cur["consent_at"]
    consent_by = None
    if body.consent is True and not consent_at:
        consent_at, consent_by = time.time(), user["name"]
    elif body.consent is False:
        consent_at, consent_by = 0, ""
    con.execute(
        "UPDATE patients SET mrn=?, birth_date=?, sex=?, phone=?, address=?,"
        " emergency_contact=?, primary_practitioner_id=?, allergies=?, medications=?,"
        " conditions=?, notes=?, consent_at=?, consent_by=COALESCE(?, consent_by),"
        " portal=?, updated_at=? WHERE user_id=?",
        (body.mrn.strip()[:40], body.birth_date.strip()[:10], body.sex.strip()[:20],
         body.phone.strip()[:40], body.address.strip()[:400],
         body.emergency_contact.strip()[:200], body.primary_practitioner_id,
         body.allergies.strip()[:2000], body.medications.strip()[:2000],
         body.conditions.strip()[:2000], body.notes.strip()[:4000], consent_at,
         consent_by, int(body.portal), time.time(), uid))
    log_access(con, uid, user, "edit")
    con.commit()
    return {"ok": True}


class PolicyBody(BaseModel):
    id: int = 0
    payer: str
    plan: str = ""
    member_id: str = ""
    group_no: str = ""
    subscriber: str = ""
    relationship: str = "self"
    effective: str = ""
    expires: str = ""
    copay_cents: int = 0
    payer_phone: str = ""
    primary_policy: bool = True
    verified: bool | None = None
    note: str = ""


@router.post("/api/health/patients/{uid}/insurance")
def policy_save(uid: int, body: PolicyBody, user=Depends(current_user),
                con=Depends(get_con)):
    _require(user)
    _person(con, uid)
    ensure_patient(con, uid)
    if not body.payer.strip():
        raise HTTPException(400, "who is the insurer?")
    if body.relationship not in RELATIONSHIPS:
        raise HTTPException(400, f"relationship is one of {RELATIONSHIPS}")
    if body.copay_cents < 0:
        raise HTTPException(400, "a copay is not negative")
    if body.primary_policy:
        con.execute("UPDATE insurance_policies SET primary_policy=0 WHERE user_id=?", (uid,))
    args = (body.payer.strip()[:120], body.plan.strip()[:120], body.member_id.strip()[:60],
            body.group_no.strip()[:60], body.subscriber.strip()[:120], body.relationship,
            body.effective.strip()[:10], body.expires.strip()[:10], body.copay_cents,
            body.payer_phone.strip()[:40], int(body.primary_policy), body.note.strip()[:400])
    if body.id:
        r = con.execute("SELECT * FROM insurance_policies WHERE id=? AND user_id=?",
                        (body.id, uid)).fetchone()
        if r is None:
            raise HTTPException(404, "no such policy")
        con.execute(
            "UPDATE insurance_policies SET payer=?, plan=?, member_id=?, group_no=?,"
            " subscriber=?, relationship=?, effective=?, expires=?, copay_cents=?,"
            " payer_phone=?, primary_policy=?, note=? WHERE id=?", args + (body.id,))
        pid = body.id
    else:
        pid = con.execute(
            "INSERT INTO insurance_policies(user_id,payer,plan,member_id,group_no,"
            " subscriber,relationship,effective,expires,copay_cents,payer_phone,"
            " primary_policy,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid,) + args + (db.now(),)).lastrowid
    if body.verified is True:
        con.execute("UPDATE insurance_policies SET verified_at=?, verified_by=? WHERE id=?",
                    (time.time(), user["name"], pid))
    elif body.verified is False:
        con.execute("UPDATE insurance_policies SET verified_at=0, verified_by='' WHERE id=?",
                    (pid,))
    log_access(con, uid, user, "insurance")
    con.commit()
    return {"ok": True, "id": pid}


@router.delete("/api/health/patients/{uid}/insurance/{pid}")
def policy_drop(uid: int, pid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    con.execute("UPDATE insurance_policies SET active=0 WHERE id=? AND user_id=?", (pid, uid))
    con.commit()
    return {"ok": True}


class EncounterBody(BaseModel):
    id: int = 0
    at: float = 0
    kind: str = "visit"
    practitioner_id: int = 0
    reason: str = ""
    notes: str = ""
    vitals: dict = {}
    plan: str = ""
    followup_at: float = 0
    shared: bool = True
    appointment_id: int = 0


@router.post("/api/health/patients/{uid}/encounters")
def encounter_save(uid: int, body: EncounterBody, user=Depends(current_user),
                   con=Depends(get_con)):
    """A visit, a call, a note, a result: what the practitioner typed,
    dated, with whatever was measured."""
    _require(user)
    _person(con, uid)
    ensure_patient(con, uid)
    if body.kind not in ENCOUNTER_KINDS:
        raise HTTPException(400, f"kind is one of {ENCOUNTER_KINDS}")
    if not (body.reason.strip() or body.notes.strip()):
        raise HTTPException(400, "say why, or what was noted")
    vitals = {str(k)[:30]: str(v)[:40] for k, v in (body.vitals or {}).items()
              if str(v).strip()}
    who = con.execute("SELECT name FROM users WHERE id=?",
                      (body.practitioner_id or user["id"],)).fetchone()
    now = time.time()
    args = (body.at or now, body.kind, body.practitioner_id or user["id"],
            who["name"] if who else user["name"], body.reason.strip()[:300],
            body.notes.strip()[:20000], json.dumps(vitals), body.plan.strip()[:4000],
            body.followup_at, int(body.shared), body.appointment_id, now)
    if body.id:
        if con.execute("SELECT 1 FROM encounters WHERE id=? AND user_id=?",
                       (body.id, uid)).fetchone() is None:
            raise HTTPException(404, "no such encounter")
        con.execute(
            "UPDATE encounters SET at=?, kind=?, practitioner_id=?, practitioner=?,"
            " reason=?, notes=?, vitals=?, plan=?, followup_at=?, shared=?,"
            " appointment_id=?, updated_at=? WHERE id=?", args + (body.id,))
        eid = body.id
    else:
        eid = con.execute(
            "INSERT INTO encounters(user_id,at,kind,practitioner_id,practitioner,reason,"
            " notes,vitals,plan,followup_at,shared,appointment_id,updated_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (uid,) + args + (now,)).lastrowid
        if body.appointment_id:
            con.execute("UPDATE patient_checkins SET state='done', updated_at=?"
                        " WHERE appointment_id=? AND state<>'left'", (now, body.appointment_id))
    log_access(con, uid, user, "encounter")
    con.commit()
    return {"ok": True, "id": eid}


@router.post("/api/health/patients/{uid}/files")
async def file_add(uid: int, request: Request, user=Depends(current_user),
                   con=Depends(get_con)):
    _require(user)
    _person(con, uid)
    ensure_patient(con, uid)
    name = (request.headers.get("x-filename") or "file").strip()[:200]
    kind = (request.headers.get("x-kind") or "document").strip()
    encounter_id = int(request.headers.get("x-encounter") or 0)
    shared = (request.headers.get("x-shared") or "1") != "0"
    if kind not in FILE_KINDS:
        raise HTTPException(400, f"kind is one of {FILE_KINDS}")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in FILE_EXT:
        raise HTTPException(400, f"attach one of: {', '.join(sorted(FILE_EXT))}")
    data = await request.body()
    if not data:
        raise HTTPException(400, "the file is empty")
    if len(data) > MAX_FILE:
        raise HTTPException(413, "25 MB is the most one file may be")
    import hashlib
    fid = con.execute(
        "INSERT INTO health_files(user_id,encounter_id,name,ext,mime,bytes,sha256,kind,"
        " shared,by_name,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (uid, encounter_id, name, ext, FILE_EXT[ext], len(data),
         hashlib.sha256(data).hexdigest(), kind, int(shared), user["name"],
         db.now())).lastrowid
    (_dir() / f"{fid}.{ext}").write_bytes(seal(data))
    log_access(con, uid, user, f"file:{fid}:add")
    con.commit()
    return {"ok": True, "id": fid, "bytes": len(data)}


def _serve_file(con, uid: int, fid: int, *, for_patient: bool):
    f = con.execute("SELECT * FROM health_files WHERE id=? AND user_id=?",
                    (fid, uid)).fetchone()
    if f is None or (for_patient and not f["shared"]):
        raise HTTPException(404, "no such file")
    path = _dir() / f"{fid}.{f['ext']}"
    if not path.exists():
        raise HTTPException(410, "the file is no longer on disk")
    raw = path.read_bytes()
    data = unseal(raw)
    if not raw.startswith(b"BCH1"):
        path.write_bytes(seal(data))          # sealed from now on
    from fastapi.responses import Response
    return Response(data, media_type=f["mime"] or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{f["name"]}"',
                             "Cache-Control": "no-store"})


@router.get("/api/health/patients/{uid}/files/{fid}")
def file_get(uid: int, fid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    log_access(con, uid, user, f"file:{fid}")
    con.commit()
    return _serve_file(con, uid, fid, for_patient=False)


@router.delete("/api/health/patients/{uid}/files/{fid}")
def file_drop(uid: int, fid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    f = con.execute("SELECT * FROM health_files WHERE id=? AND user_id=?",
                    (fid, uid)).fetchone()
    if f is None:
        raise HTTPException(404, "no such file")
    con.execute("DELETE FROM health_files WHERE id=?", (fid,))
    try:
        (_dir() / f"{fid}.{f['ext']}").unlink()
    except FileNotFoundError:
        pass
    log_access(con, uid, user, f"file:{fid}:removed")
    con.commit()
    return {"ok": True}


class CheckinBody(BaseModel):
    appointment_id: int
    state: str = "arrived"
    note: str = ""


@router.post("/api/health/checkin")
def desk_checkin(body: CheckinBody, user=Depends(current_user), con=Depends(get_con)):
    """The desk marks an arrival, or moves somebody along the queue."""
    _require(user)
    if body.state not in CHECKIN_STATES:
        raise HTTPException(400, f"state is one of {CHECKIN_STATES}")
    existing = con.execute("SELECT * FROM patient_checkins WHERE appointment_id=?",
                           (body.appointment_id,)).fetchone()
    if existing is None:
        check_in(con, body.appointment_id, method="desk")
    if body.state != "arrived" or body.note.strip():
        con.execute("UPDATE patient_checkins SET state=?, note=?, updated_at=?"
                    " WHERE appointment_id=?",
                    (body.state, body.note.strip()[:200], time.time(), body.appointment_id))
    con.commit()
    return {"ok": True, "state": body.state}


@router.get("/api/health/patients/{uid}/access")
def access_log(uid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    return {"access": [dict(r) for r in con.execute(
        "SELECT by_name, what, at FROM health_access WHERE user_id=?"
        " ORDER BY id DESC LIMIT 200", (uid,)).fetchall()]}
