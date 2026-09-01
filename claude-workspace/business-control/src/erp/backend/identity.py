"""QR identity — per-person unguessable cards, ported from lingua-portal.

**`uid` is separate from `id` on purpose.** The primary key is an internal
row number: it leaks how many people the tenant has, and it is trivially
guessable (id 5 exists if id 6 does). `uid` is a UUID4 — unguessable,
meaningless outside this database, and what goes on a printed card, in a
QR, and into any future integration. It is minted lazily on first card
render and can be reissued, which is how a lost card stops working.

The payload is either `bc:person:<uuid>` or a URL `{base}/p/<uuid>`. The
URL form exists specifically so an iPhone can be a scanner: Safari has no
BarcodeDetector, so the in-app scanner cannot run there — but the Camera
app recognises a URL and offers to open it, landing the scanner in the
portal already holding the code.

Two scan flows, and one rule shared by both:

- **Scan-to-check-in** (a teacher at the door): the QR decides *who*,
  never *whether* — it routes through the ordinary check-in rules, so
  enrolment, session-open and the late window all still apply, and the
  row records the teacher as the marker. A student scanning their own
  card cannot mark themselves present.
- **Scan-as-contact-handshake**: the code shows the FULL name whatever
  the person's privacy level — a uid is only obtainable from the card or
  screen its owner presented, so scanning one is the physical handshake
  the privacy settings exist to require. Blocks and ghosts still answer
  "no such person", indistinguishable from a code that never existed.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

PREFIX = "bc:person:"


def ensure_uid(con, user_id: int) -> str:
    r = con.execute("SELECT uid FROM users WHERE id=?",
                    (int(user_id),)).fetchone()
    if r is None:
        raise HTTPException(404, "no such person")
    if r["uid"]:
        return r["uid"]
    uid = str(uuid.uuid4())
    con.execute("UPDATE users SET uid=? WHERE id=?", (uid, int(user_id)))
    return uid


def reissue(con, user_id: int) -> str:
    """A new code; the old card stops working the same moment."""
    uid = str(uuid.uuid4())
    cur = con.execute("UPDATE users SET uid=? WHERE id=?",
                      (uid, int(user_id)))
    if cur.rowcount == 0:
        raise HTTPException(404, "no such person")
    return uid


def payload_for(uid: str, *, base: str = "") -> str:
    if base:
        return base.rstrip("/") + "/p/" + uid
    return PREFIX + uid


def parse_payload(scanned: str) -> str:
    """Permissive about the wrapper, strict about the UUID. Accepts the
    scheme form, a full URL, or a bare UUID (USB scanners strip schemes)."""
    s = str(scanned or "").strip()
    if s.lower().startswith(PREFIX):
        s = s[len(PREFIX):]
    elif "://" in s or s.startswith("/"):
        s = s.split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1]
    s = s.strip().strip("/")
    try:
        return str(uuid.UUID(s))     # validates shape AND normalises casing
    except (ValueError, AttributeError):
        raise HTTPException(400, "that is not one of our ID codes")


def by_uid(con, uid: str):
    r = con.execute("SELECT * FROM users WHERE uid=? AND active=1",
                    (uid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such person")
    return dict(r)


def scan_check_in(con, actor, *, session_id: int, scanned: str) -> dict:
    """Teacher scans a card at the door. Routes through the ordinary
    check-in rules — the QR only answers WHO."""
    from . import classroom
    uid = parse_payload(scanned)
    person = by_uid(con, uid)
    c, fresh = classroom.do_check_in(
        con, session_id=session_id, student_id=person["id"],
        method="teacher", marked_by=actor["id"], note="scanned in")
    return {"student": {"id": person["id"], "name": person["name"]},
            "status": c.status, "at": c.at, "new_achievements": fresh}


def resolve_handshake(con, actor, scanned: str) -> dict:
    """A member scans another member's card: full name plus the contact
    state, so the UI can offer Connect / Accept / Message. Every refusal —
    unknown code, blocked, ghosted, outside the community — is the same
    answer."""
    from . import community as CM
    uid = parse_payload(scanned)
    row = con.execute("SELECT id, name FROM users WHERE uid=? AND active=1",
                      (uid,)).fetchone()
    if row is None or not CM.in_community(con, row["id"]):
        raise HTTPException(404, "no such person")
    if row["id"] == actor["id"]:
        return {"id": row["id"], "name": row["name"], "contact": "self"}
    p = CM.prefs_of(con, row["id"])
    if p["invisible"] or CM._blocked_between(con, actor["id"], row["id"]) \
            or CM._ghosts(con, row["id"], actor["id"]):
        raise HTTPException(404, "no such person")
    return CM._decorate_contact(con, actor, {"id": row["id"],
                                             "name": row["name"]})


# ── ops routes ───────────────────────────────────────────────────────────────

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)
from .learning import may_edit  # noqa: E402


class ScanBody(BaseModel):
    code: str = ""


@router.post("/api/learning/sessions/{sid}/scan")
def ops_scan_checkin(sid: int, body: ScanBody, user=Depends(current_user),
                     con=Depends(get_con)):
    s = con.execute("SELECT course_id FROM class_sessions WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "session not found")
    if not may_edit(con, user, s["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    out = scan_check_in(con, user, session_id=sid, scanned=body.code)
    con.commit()
    return out
