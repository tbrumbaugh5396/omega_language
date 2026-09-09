"""Recorded media for Learning — quiz answers, lesson drills, class
recordings. Ported from lingua-portal's uploads service.

One table serves all three kinds, discriminated by which reference is set:
`lesson_id` (a teacher's drill attached to a lesson), `session_id` (a class
recording), neither (a student's spoken or video quiz answer, pointed at by
`quiz_responses.material_id`).

Four rules, each of which has been a real vulnerability somewhere:

1. The declared Content-Type is a claim; the **leading bytes decide** what
   a file is. A mismatch is a refusal, not a warning.
2. **The client never chooses the stored name** — a random token plus a
   derived extension, so `../../etc/passwd` and `x.php` are not
   expressible.
3. Size is capped before anything is written.
4. Files are served from their own root with a fixed content type and
   `nosniff`, never executed. The token IS the read capability: names are
   unguessable, so recordings can be streamed by plain `<video src>`
   without a header in sight (an <img>/<video> cannot send a bearer
   token — the same reason the source did it this way).

Uploads are raw bodies with a Content-Type header — no multipart anywhere,
same as the source. Files live under the tenant's own data directory
(`uploads/xx/<token>.<ext>`) so "this tenant's data" stays one folder.
"""

import os
import secrets
import time

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request

from . import tenancy

MAX_IMAGE = 8 * 1024 * 1024
MAX_MEDIA = 256 * 1024 * 1024
MAX_DOC = 32 * 1024 * 1024

# Documents a teacher hands out. Sniffed like everything else — a PDF
# starts with %PDF, the Office formats are zip containers — and the zip
# family is told apart by the name the sender declared, because from the
# bytes alone a .docx and a .pptx are the same archive. A text file has
# no signature at all, so it is the one kind admitted by NOT looking
# like anything: valid UTF-8 with no NUL in it.
_ZIP_KINDS = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".zip": "application/zip",
}

# leading-bytes signatures: (prefix, kind, mime, extension)
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image", "image/png", ".png"),
    (b"\xff\xd8\xff", "image", "image/jpeg", ".jpg"),
    (b"GIF8", "image", "image/gif", ".gif"),
    (b"OggS", "audio", "audio/ogg", ".ogg"),
    (b"fLaC", "audio", "audio/flac", ".flac"),
    (b"ID3", "audio", "audio/mpeg", ".mp3"),
    (b"\x1aE\xdf\xa3", "video", "video/webm", ".webm"),
)

TABLES = """
CREATE TABLE IF NOT EXISTS learning_materials (
  id INTEGER PRIMARY KEY,
  lesson_id INTEGER,                        -- a drill on a lesson
  session_id INTEGER,                       -- a class recording
  owner_id INTEGER,                         -- who recorded/uploaded it
  kind TEXT NOT NULL,                       -- image | audio | video
  path TEXT NOT NULL,                       -- relative to the uploads root
  original TEXT DEFAULT '',
  mime TEXT DEFAULT '',
  bytes INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS learning_materials_lesson
  ON learning_materials(lesson_id);
CREATE INDEX IF NOT EXISTS learning_materials_session
  ON learning_materials(session_id);
"""


TRAINING_TABLES = """
-- A one-time training: a film and a link. Not a course — nobody enrols,
-- there is no register, the link IS the door. For "here is the new
-- system, everybody watch this by Friday", which is a thing that
-- happens far more often than a curriculum does.
CREATE TABLE IF NOT EXISTS trainings (
  id INTEGER PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  blurb TEXT DEFAULT '',
  material_id INTEGER DEFAULT 0,
  created_by INTEGER,
  active INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS training_views (
  training_id INTEGER NOT NULL,
  who TEXT NOT NULL,                 -- user:<id> or visitor:<vid>
  name TEXT DEFAULT '',
  first_at REAL NOT NULL,
  last_at REAL NOT NULL,
  views INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (training_id, who)
);
"""


def init_tables(con):
    con.executescript(TABLES)
    con.executescript(TRAINING_TABLES)
    try:
        # A film or a deck for the whole class, not one lesson of it.
        con.execute("ALTER TABLE learning_materials ADD COLUMN course_id INTEGER")
    except Exception:                                        # noqa: BLE001
        pass
    con.commit()


def of_course(con, course_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT id, kind, path, original, mime, bytes, created_at"
        " FROM learning_materials WHERE course_id=? ORDER BY id DESC",
        (int(course_id),)).fetchall()]


# ── the store ────────────────────────────────────────────────────────────────

def uploads_root() -> str:
    return str(tenancy.data_dir() / "uploads")


def sniff(data: bytes, filename: str = ""):
    """(kind, mime, ext) from the leading bytes, or None. RIFF and ftyp
    containers are refined by the tag deeper in; zip containers by the
    declared name; text by being nothing else."""
    for prefix, kind, mime, ext in _SIGNATURES:
        if data.startswith(prefix):
            return kind, mime, ext
    if data.startswith(b"%PDF"):
        return "document", "application/pdf", ".pdf"
    if data.startswith(b"PK\x03\x04"):
        ext = os.path.splitext(str(filename or "").lower())[1]
        if ext not in _ZIP_KINDS:
            ext = ".zip"
        return "document", _ZIP_KINDS[ext], ext
    if data and b"\x00" not in data[:65536]:
        try:
            data[:65536].decode("utf-8")
            if str(filename or "").lower().endswith((".txt", ".md", ".csv")):
                ext = os.path.splitext(filename.lower())[1]
                return "document", {".txt": "text/plain", ".md": "text/markdown",
                                    ".csv": "text/csv"}[ext], ext
        except UnicodeDecodeError:
            pass
    if data[:4] == b"RIFF" and len(data) >= 12:
        tag = data[8:12]
        if tag == b"WEBP":
            return "image", "image/webp", ".webp"
        if tag == b"WAVE":
            return "audio", "audio/wav", ".wav"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        tag = data[8:12]
        if tag in (b"M4A ", b"M4B "):
            return "audio", "audio/mp4", ".m4a"
        return "video", "video/mp4", ".mp4"
    return None


def save(data: bytes, *, allow=("image", "audio", "video"),
         filename: str = "") -> dict:
    if not data:
        raise HTTPException(400, "the upload arrived empty")
    found = sniff(data, filename)
    if found is None:
        raise HTTPException(400, "that file type is not accepted here")
    kind, mime, ext = found
    if kind not in allow:
        raise HTTPException(400, f"a {kind} is not accepted here")
    cap = (MAX_IMAGE if kind == "image" else
           MAX_DOC if kind == "document" else MAX_MEDIA)
    if len(data) > cap:
        raise HTTPException(400,
                            f"too large — the cap is {cap // (1024*1024)} MB")
    token = secrets.token_hex(16)
    rel = f"{token[:2]}/{token}{ext}"
    from . import blobs
    blobs.put(rel, data, mime)
    return {"path": rel, "mime": mime, "kind": kind, "bytes": len(data)}


def record(con, *, saved: dict, owner_id: int, lesson_id=None,
           session_id=None, original: str = "", course_id=None) -> int:
    cur = con.execute(
        "INSERT INTO learning_materials(lesson_id,session_id,owner_id,kind,"
        " path,original,mime,bytes,created_at,course_id)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (lesson_id, session_id, owner_id, saved["kind"], saved["path"],
         str(original or "")[:200], saved["mime"], saved["bytes"],
         time.time(), course_id))
    return cur.lastrowid


def unlink(rel_path: str) -> bool:
    """Delete a stored file — wherever the store keeps it."""
    from . import blobs
    if not rel_path:
        return False
    return blobs.delete(str(rel_path))


def delete_material(con, mid: int) -> None:
    r = con.execute("SELECT path FROM learning_materials WHERE id=?",
                    (int(mid),)).fetchone()
    if r is None:
        return
    unlink(r["path"])                       # file first: no orphaned bytes
    con.execute("DELETE FROM learning_materials WHERE id=?", (int(mid),))
    con.execute("UPDATE quiz_responses SET material_id=NULL"
                " WHERE material_id=?", (int(mid),))


def of_lesson(con, lesson_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT id, kind, path, original, mime, bytes, created_at"
        " FROM learning_materials WHERE lesson_id=? ORDER BY id",
        (int(lesson_id),)).fetchall()]


def collect_sfu_tapes(con, session, owner_id: int) -> list:
    """The class tapes come home. The machine's SFU records what it
    forwards under record_dir/bc-<tenant>-<room>-<peer>/; when the class
    ends (or an operator asks), everything recorded for this session's
    room is ingested into the sharded store as a session recording —
    sniffed like any upload, served like any tape, swept by data rights
    like everything else — and the source file is REMOVED, because data
    that lives in two places is data that disagrees eventually.

    Best-effort by design: a segment still being finalised, or a torn
    one, is skipped and waits for the next collect. Returns the material
    ids it landed."""
    import glob

    from . import services, tenancy
    s = services.service("sfu")
    rec = (s or {}).get("record_dir") or ""
    room = session["room"] if session["room"] else ""
    if not (s and rec and room):
        return []
    tid = tenancy.CURRENT.get() or "default"
    got = []
    for f in sorted(glob.glob(os.path.join(
            rec, f"bc-{tid}-{room}-*", "*"))):
        try:
            data = open(f, "rb").read()
        except OSError:
            continue
        if len(data) < 4096:
            continue                    # torn or still-open segment
        try:
            saved = save(data, allow=("video", "audio"))
        except HTTPException:
            continue                    # not a media file we recognise
        peer = os.path.basename(os.path.dirname(f))
        peer = peer[len(f"bc-{tid}-{room}-"):]
        mid = record(con, saved=saved, owner_id=owner_id,
                     session_id=session["id"],
                     original=f"class tape — {peer}")
        got.append(mid)
        try:
            os.remove(f)
        except OSError:
            pass
    if got:
        con.commit()
    return got


def of_session(con, session_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT id, kind, path, original, mime, bytes, created_at"
        " FROM learning_materials WHERE session_id=? ORDER BY id",
        (int(session_id),)).fetchall()]


async def read_upload(request: Request) -> bytes:
    data = await request.body()
    if len(data) > MAX_MEDIA:
        raise HTTPException(400, "too large")
    return data


# ── ops routes ───────────────────────────────────────────────────────────────

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)
from .learning import may_edit  # noqa: E402


@router.post("/api/learning/lessons/{lid}/material")
async def ops_lesson_material(lid: int, request: Request,
                              user=Depends(current_user),
                              con=Depends(get_con)):
    """A drill on a lesson: the teacher's recorded audio or video (or an
    image), raw bytes in."""
    r = con.execute("SELECT course_id FROM lessons WHERE id=?",
                    (lid,)).fetchone()
    if r is None:
        raise HTTPException(404, "lesson not found")
    if not may_edit(con, user, r["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    data = await read_upload(request)
    name = request.headers.get("x-filename", "")
    saved = save(data, allow=("image", "audio", "video", "document"),
                 filename=name)
    mid = record(con, saved=saved, owner_id=user["id"], lesson_id=lid,
                 original=name)
    con.commit()
    return {"id": mid, **saved}


@router.post("/api/learning/courses/{cid}/material")
async def ops_course_material(cid: int, request: Request,
                              user=Depends(current_user),
                              con=Depends(get_con)):
    """A deck or a film for the class as a whole — the slides you put
    on every week, the recording of the intro — rather than a drill on
    one lesson. Shows on the course page and in every session's Shared
    tab."""
    if con.execute("SELECT 1 FROM courses WHERE id=?", (cid,)).fetchone() is None:
        raise HTTPException(404, "course not found")
    if not may_edit(con, user, cid):
        raise HTTPException(403, "you do not teach this course")
    data = await read_upload(request)
    name = request.headers.get("x-filename", "")
    saved = save(data, allow=("image", "audio", "video", "document"),
                 filename=name)
    mid = record(con, saved=saved, owner_id=user["id"], course_id=cid,
                 original=name)
    con.commit()
    return {"id": mid, **saved}


# ── trainings: a film and a link ─────────────────────────────────────────────

class TrainingBody(BaseModel):
    title: str = ""
    blurb: str = ""
    active: bool = True


@router.get("/api/learning/trainings")
def ops_trainings(user=Depends(current_user), con=Depends(get_con)):
    from .main import base_url
    rows = [dict(r) for r in con.execute(
        "SELECT t.*, COALESCE(u.name,'') AS by_name, m.kind, m.path, m.original,"
        " (SELECT COUNT(*) FROM training_views v WHERE v.training_id=t.id) AS viewers,"
        " (SELECT COALESCE(SUM(views),0) FROM training_views v WHERE v.training_id=t.id) AS views"
        " FROM trainings t LEFT JOIN users u ON u.id=t.created_by"
        " LEFT JOIN learning_materials m ON m.id=t.material_id"
        " ORDER BY t.created_at DESC")]
    for r in rows:
        r["url"] = f"{base_url()}/training/{r['token']}"
        r["watched_by"] = [dict(v) for v in con.execute(
            "SELECT name, who, views, last_at FROM training_views"
            " WHERE training_id=? ORDER BY last_at DESC LIMIT 100", (r["id"],))]
    return {"trainings": rows,
            "note": "A training is a film and a link. Nobody enrols; the "
                    "link is the door. Who opened it is counted by account "
                    "when signed in and by browser when not."}


@router.post("/api/learning/trainings")
def ops_training_create(body: TrainingBody, user=Depends(current_user),
                        con=Depends(get_con)):
    from . import community as CM
    if not (user["is_admin"] or CM.is_staff(con, user)):
        raise HTTPException(403, "staff make trainings")
    if not body.title.strip():
        raise HTTPException(400, "a training needs a title")
    import secrets as _sec
    cur = con.execute(
        "INSERT INTO trainings(token,title,blurb,created_by,active,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (_sec.token_urlsafe(12), body.title.strip()[:160],
         body.blurb.strip()[:2000], user["id"], 1 if body.active else 0,
         time.time()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.post("/api/learning/trainings/{tid}/film")
async def ops_training_film(tid: int, request: Request,
                            user=Depends(current_user), con=Depends(get_con)):
    """The film itself (or a deck, or a PDF): raw bytes, one per
    training, replacing whatever was there."""
    t = con.execute("SELECT * FROM trainings WHERE id=?", (tid,)).fetchone()
    if t is None:
        raise HTTPException(404, "no such training")
    from . import community as CM
    if not (user["is_admin"] or CM.is_staff(con, user)):
        raise HTTPException(403, "staff make trainings")
    data = await read_upload(request)
    name = request.headers.get("x-filename", "")
    saved = save(data, allow=("video", "audio", "document", "image"),
                 filename=name)
    mid = record(con, saved=saved, owner_id=user["id"], original=name)
    if t["material_id"]:
        delete_material(con, t["material_id"])
    con.execute("UPDATE trainings SET material_id=? WHERE id=?", (mid, tid))
    con.commit()
    return {"ok": True, "material_id": mid, **saved}


@router.post("/api/learning/trainings/{tid}")
def ops_training_update(tid: int, body: TrainingBody,
                        user=Depends(current_user), con=Depends(get_con)):
    from . import community as CM
    if not (user["is_admin"] or CM.is_staff(con, user)):
        raise HTTPException(403, "staff make trainings")
    con.execute("UPDATE trainings SET title=?, blurb=?, active=? WHERE id=?",
                (body.title.strip()[:160] or "Training", body.blurb.strip()[:2000],
                 1 if body.active else 0, tid))
    con.commit()
    return {"ok": True}


@router.post("/api/learning/sessions/{sid}/material")
async def ops_session_material(sid: int, request: Request,
                               user=Depends(current_user),
                               con=Depends(get_con)):
    """Something put in front of THIS class — a handout, a slide deck,
    a photo of the whiteboard. The teacher's, or the door's: whoever is
    running the room may hand things out in it."""
    s = con.execute("SELECT * FROM class_sessions WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "session not found")
    from .classroom import _door
    _door(con, user, s["course_id"])
    data = await read_upload(request)
    name = request.headers.get("x-filename", "")
    saved = save(data, allow=("image", "audio", "video", "document"),
                 filename=name)
    mid = record(con, saved=saved, owner_id=user["id"], session_id=sid,
                 original=name)
    con.commit()
    return {"id": mid, **saved}


@router.post("/api/learning/materials/{mid}/delete")
def ops_material_delete(mid: int, user=Depends(current_user),
                        con=Depends(get_con)):
    r = con.execute(
        "SELECT m.*, l.course_id FROM learning_materials m"
        " LEFT JOIN lessons l ON l.id=m.lesson_id WHERE m.id=?",
        (mid,)).fetchone()
    if r is None:
        return {"ok": True}
    course_id = r["course_id"]
    if course_id is None and r["session_id"] is not None:
        s = con.execute("SELECT course_id FROM class_sessions WHERE id=?",
                        (r["session_id"],)).fetchone()
        course_id = s["course_id"] if s else None
    allowed = user["is_admin"] or r["owner_id"] == user["id"] or (
        course_id is not None and may_edit(con, user, course_id))
    if not allowed:
        raise HTTPException(403, "not yours to delete")
    delete_material(con, mid)
    con.commit()
    return {"ok": True}


@router.post("/api/learning/sessions/{sid}/recording")
async def ops_class_recording(sid: int, request: Request,
                              user=Depends(current_user),
                              con=Depends(get_con)):
    """The class recording. Ownership, not just role: a recording of a class
    is a recording of the students in it, so only ITS teacher (or an admin)
    may attach one."""
    s = con.execute("SELECT * FROM class_sessions WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "session not found")
    if not user["is_admin"] and s["teacher_id"] != user["id"]:
        raise HTTPException(403,
                            "only the teacher of this class may add its"
                            " recording")
    data = await read_upload(request)
    saved = save(data, allow=("video", "audio"))
    mid = record(con, saved=saved, owner_id=user["id"], session_id=sid,
                 original=request.headers.get("x-filename", ""))
    con.commit()
    return {"id": mid, **saved}


@router.post("/api/learning/sessions/{sid}/collect-tape")
def ops_collect_tape(sid: int, user=Depends(current_user),
                     con=Depends(get_con)):
    """Bring home whatever the machine's SFU recorded for this class —
    the manual half of the sweep that also runs when the class closes,
    for segments that finished late."""
    s = con.execute("SELECT * FROM class_sessions WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "session not found")
    if not user["is_admin"] and s["teacher_id"] != user["id"]:
        raise HTTPException(403, "only the teacher of this class collects"
                                 " its tapes")
    got = collect_sfu_tapes(con, s, owner_id=user["id"])
    return {"collected": len(got), "ids": got}


@router.get("/api/learning/sessions/{sid}/recordings")
def ops_session_recordings(sid: int, user=Depends(current_user),
                           con=Depends(get_con)):
    s = con.execute("SELECT course_id FROM class_sessions WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "session not found")
    if not may_edit(con, user, s["course_id"]):
        raise HTTPException(403, "you do not teach this course")
    return of_session(con, sid)
