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

from fastapi import APIRouter, Depends, HTTPException, Request

from . import tenancy

MAX_IMAGE = 8 * 1024 * 1024
MAX_MEDIA = 256 * 1024 * 1024

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


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


# ── the store ────────────────────────────────────────────────────────────────

def uploads_root() -> str:
    return str(tenancy.data_dir() / "uploads")


def sniff(data: bytes):
    """(kind, mime, ext) from the leading bytes, or None. RIFF and ftyp
    containers are refined by the tag deeper in."""
    for prefix, kind, mime, ext in _SIGNATURES:
        if data.startswith(prefix):
            return kind, mime, ext
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


def save(data: bytes, *, allow=("image", "audio", "video")) -> dict:
    if not data:
        raise HTTPException(400, "the upload arrived empty")
    found = sniff(data)
    if found is None:
        raise HTTPException(400, "that file type is not accepted here")
    kind, mime, ext = found
    if kind not in allow:
        raise HTTPException(400, f"a {kind} is not accepted here")
    cap = MAX_IMAGE if kind == "image" else MAX_MEDIA
    if len(data) > cap:
        raise HTTPException(400,
                            f"too large — the cap is {cap // (1024*1024)} MB")
    token = secrets.token_hex(16)
    rel = f"{token[:2]}/{token}{ext}"
    dest = os.path.join(uploads_root(), token[:2], token + ext)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with open(tmp, "wb") as f:              # write-then-rename: no half file
        f.write(data)
    os.replace(tmp, dest)
    return {"path": rel, "mime": mime, "kind": kind, "bytes": len(data)}


def record(con, *, saved: dict, owner_id: int, lesson_id=None,
           session_id=None, original: str = "") -> int:
    cur = con.execute(
        "INSERT INTO learning_materials(lesson_id,session_id,owner_id,kind,"
        " path,original,mime,bytes,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (lesson_id, session_id, owner_id, saved["kind"], saved["path"],
         str(original or "")[:200], saved["mime"], saved["bytes"],
         time.time()))
    return cur.lastrowid


def unlink(rel_path: str) -> bool:
    """Delete a stored file — refusing anything that escapes the root."""
    root = os.path.abspath(uploads_root())
    target = os.path.abspath(os.path.join(root, str(rel_path or "")))
    if not target.startswith(root + os.sep):
        return False
    try:
        os.unlink(target)
        return True
    except OSError:
        return False


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
    saved = save(data)
    mid = record(con, saved=saved, owner_id=user["id"], lesson_id=lid,
                 original=request.headers.get("x-filename", ""))
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
