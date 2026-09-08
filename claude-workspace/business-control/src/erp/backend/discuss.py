"""A discussion board per course.

Threads and posts, nothing cleverer. The DM system is the wrong shape
for it (two endpoints, a contact gate, no group) and product reviews
are flat and anonymous; a course needs a place where a question asked
on Tuesday is still there for the person who has it on Thursday, and
where the teacher's answer is under the question rather than in
somebody's inbox.

Who may read is who may be in the course — enrolled, or teaching it.
Who may delete is the author or the teacher, and a deleted post keeps
its row with the body gone, so a thread does not silently renumber
under the people replying to it.
"""
import time

TABLES = """
CREATE TABLE IF NOT EXISTS course_threads (
  id INTEGER PRIMARY KEY,
  course_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  body TEXT DEFAULT '',
  pinned INTEGER DEFAULT 0,
  deleted INTEGER DEFAULT 0,
  created_at REAL NOT NULL,
  last_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS course_threads_course
  ON course_threads(course_id, pinned DESC, last_at DESC);

CREATE TABLE IF NOT EXISTS course_posts (
  id INTEGER PRIMARY KEY,
  thread_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  body TEXT NOT NULL,
  deleted INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS course_posts_thread ON course_posts(thread_id, id);
"""


def init_tables(con) -> None:
    con.executescript(TABLES)
    con.commit()


def threads(con, course_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT t.id, t.title, t.pinned, t.created_at, t.last_at,"
        " t.user_id, COALESCE(u.name,'') AS author,"
        " (SELECT COUNT(*) FROM course_posts p WHERE p.thread_id=t.id"
        "  AND p.deleted=0) AS replies"
        " FROM course_threads t LEFT JOIN users u ON u.id=t.user_id"
        " WHERE t.course_id=? AND t.deleted=0"
        " ORDER BY t.pinned DESC, t.last_at DESC LIMIT 200", (course_id,))]


def start(con, course_id: int, user_id: int, title: str, body: str) -> int:
    now = time.time()
    cur = con.execute(
        "INSERT INTO course_threads(course_id,user_id,title,body,created_at,"
        "last_at) VALUES(?,?,?,?,?,?)",
        (course_id, user_id, title.strip()[:160], body.strip()[:8000],
         now, now))
    return cur.lastrowid


def thread(con, tid: int):
    t = con.execute(
        "SELECT t.*, COALESCE(u.name,'') AS author FROM course_threads t"
        " LEFT JOIN users u ON u.id=t.user_id WHERE t.id=? AND t.deleted=0",
        (tid,)).fetchone()
    if t is None:
        return None
    posts = [dict(r) for r in con.execute(
        "SELECT p.id, p.user_id, p.body, p.deleted, p.created_at,"
        " COALESCE(u.name,'') AS author FROM course_posts p"
        " LEFT JOIN users u ON u.id=p.user_id WHERE p.thread_id=?"
        " ORDER BY p.id", (tid,))]
    for x in posts:
        if x["deleted"]:
            x["body"] = ""
    return {**dict(t), "posts": posts}


def reply(con, tid: int, user_id: int, body: str) -> int:
    now = time.time()
    cur = con.execute(
        "INSERT INTO course_posts(thread_id,user_id,body,created_at)"
        " VALUES(?,?,?,?)", (tid, user_id, body.strip()[:8000], now))
    con.execute("UPDATE course_threads SET last_at=? WHERE id=?", (now, tid))
    return cur.lastrowid
