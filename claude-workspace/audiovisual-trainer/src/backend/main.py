"""AV Trainer — FastAPI backend. Multi-user, JSON API + static PWA.

A training environment for the audiovisual crafts, built to the specification
in Part 9 of the roadmap: practice-loop manager, discrimination trainer,
effects lab, reference analyzer, vocabulary builder, generator+filter sandbox,
and unlearning exercises.

The backend is deliberately thin. Everything perceptual — audio synthesis,
image processing, FFT, saliency, the labs — runs in the browser, because the
feedback has to be immediate and the stimuli have to be generated fresh every
trial. The server's job is the curriculum, the schedule, and the record.

Every content route is scoped to the signed-in user, resolved from a bearer
token (see current_user).
"""
import json
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (ai, auth, briefs, config, course, curriculum as cur, db,
               library, seeder, studio)

app = FastAPI(title="AV Trainer")
db.init()

KV_KEYS = ("profile", "prefs")
TRACK_IDS = {t["id"] for t in cur.TRACKS}
PIECE_STATUS = ("briefed", "making", "shipped", "abandoned")
ARTICULATION_IDS = {a["id"] for a in cur.ARTICULATION}

# Tables carried in a backup, parents before children.
#
# studio_projects travels; `assets` does not. Asset rows are pointers to files
# on disk, and a backup that restores the pointers without the bytes is worse
# than one that admits the gap — canvas documents keep their pixels inline and
# survive, music and video projects come back missing their imported media.
BACKUP_TABLES = ["progress", "notes", "pieces", "drill_attempts", "vocab_srs",
                 "practice_log", "selections", "analyses", "articulation",
                 "lab_saves", "studio_projects"]
BACKUP_FORMAT = "av-trainer-backup/1"


# ------------------------------------------------------------ auth core

def current_user(authorization: str = Header(None)) -> int:
    """Resolve the signed-in user id from an 'Authorization: Bearer <token>'."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(401, "not signed in")
    with db.connect() as con:
        row = con.execute(
            "SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "session expired")
    return row["user_id"]


def _user_public(con, uid: int) -> dict:
    r = con.execute(
        "SELECT id, username, display_name, created FROM users WHERE id=?",
        (uid,)).fetchone()
    return dict(r) if r else {}


class SignupIn(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/signup")
def signup(body: SignupIn):
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(400, "username must be at least 3 characters")
    if len(body.password) < 6:
        raise HTTPException(400, "password must be at least 6 characters")
    salt, pw = auth.hash_password(body.password)
    display = body.display_name.strip() or username
    with db.connect() as con:
        if con.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE",
                       (username,)).fetchone():
            raise HTTPException(409, "that username is taken")
        cur_ = con.execute(
            "INSERT INTO users(username,display_name,salt,pw_hash,created) "
            "VALUES(?,?,?,?,?)", (username, display, salt, pw, db.now()))
        uid = cur_.lastrowid
        token = auth.new_token()
        con.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)",
                    (token, uid, db.now()))
        return {"token": token, "user": _user_public(con, uid)}


@app.post("/api/auth/login")
def login(body: LoginIn):
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (body.username.strip(),)).fetchone()
        if not row or not auth.verify_password(body.password, row["salt"],
                                               row["pw_hash"]):
            raise HTTPException(401, "wrong username or password")
        token = auth.new_token()
        con.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)",
                    (token, row["id"], db.now()))
        return {"token": token, "user": _user_public(con, row["id"])}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(None)):
    token = authorization[7:] if authorization and authorization.lower(
    ).startswith("bearer ") else ""
    with db.connect() as con:
        con.execute("DELETE FROM sessions WHERE token=?", (token,))
    return {"ok": True}


@app.get("/api/auth/me")
def me(uid: int = Depends(current_user)):
    with db.connect() as con:
        return {"user": _user_public(con, uid)}


class ProfileIn(BaseModel):
    display_name: str | None = None
    password: str | None = None
    current_password: str | None = None


@app.patch("/api/auth/profile")
def update_profile(body: ProfileIn, uid: int = Depends(current_user)):
    with db.connect() as con:
        row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if body.display_name is not None:
            con.execute("UPDATE users SET display_name=? WHERE id=?",
                        (body.display_name.strip() or row["username"], uid))
        if body.password:
            if not body.current_password or not auth.verify_password(
                    body.current_password, row["salt"], row["pw_hash"]):
                raise HTTPException(403, "current password is wrong")
            if len(body.password) < 6:
                raise HTTPException(400, "password must be at least 6 characters")
            salt, pw = auth.hash_password(body.password)
            con.execute("UPDATE users SET salt=?, pw_hash=? WHERE id=?",
                        (salt, pw, uid))
        return {"user": _user_public(con, uid)}


# ------------------------------------------------------------ content

@app.get("/api/curriculum")
def get_curriculum():
    """Static: the tracks, theory map, drill and lab registries, protocols."""
    return {
        "tracks": cur.TRACKS,
        "modules": cur.MODULES,
        "drills": cur.DRILLS,
        "dimensions": cur.DIMENSIONS,
        "labs": cur.LABS,
        "articulation": cur.ARTICULATION,
        "unlearning": cur.UNLEARNING,
        "constraints": cur.BRIEF_CONSTRAINTS,
        "bundles": cur.BRIEF_BUNDLES,
    }


@app.get("/api/library")
def get_library():
    """Static: Parts 8 and 10-12 — the reference layer."""
    return {
        "catalog": library.CATALOG,
        "genres": library.GENRES,
        "systems": library.SYSTEMS,
        "reading": [{"section": s["section"],
                     "items": [{"author": a, "work": w, "note": n}
                               for a, w, n in s["items"]]}
                    for s in library.READING],
        "tools": library.TOOLS,
        "glossary": [{"term": t, "definition": d} for t, d in library.GLOSSARY],
        "terms": [{"term": t, "domain": dm, "definition": d}
                  for t, dm, d in library.TERMS],
    }


# ------------------------------------------------------------ progress / notes

class ProgressIn(BaseModel):
    slug: str
    status: str | None = None
    confidence: int | None = None
    add_minutes: int = 0
    pulled_by: str | None = None


@app.get("/api/progress")
def list_progress(uid: int = Depends(current_user)):
    with db.connect() as con:
        return {"progress": db.rows(
            con, "SELECT * FROM progress WHERE user_id=? ORDER BY updated DESC",
            (uid,))}


@app.post("/api/progress")
def set_progress(body: ProgressIn, uid: int = Depends(current_user)):
    if body.slug not in cur.LESSONS:
        raise HTTPException(404, "unknown lesson")
    now = db.now()
    with db.connect() as con:
        row = con.execute("SELECT * FROM progress WHERE user_id=? AND slug=?",
                          (uid, body.slug)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO progress(user_id,slug,status,confidence,minutes,"
                "pulled_by,started,updated) VALUES(?,?,?,?,?,?,?,?)",
                (uid, body.slug, body.status or "reading", body.confidence or 0,
                 max(0, body.add_minutes), body.pulled_by or "", now, now))
        else:
            con.execute(
                "UPDATE progress SET status=?, confidence=?, minutes=minutes+?, "
                "pulled_by=?, updated=? WHERE user_id=? AND slug=?",
                (body.status or row["status"],
                 row["confidence"] if body.confidence is None else body.confidence,
                 max(0, body.add_minutes),
                 row["pulled_by"] if body.pulled_by is None else body.pulled_by,
                 now, uid, body.slug))
        r = con.execute("SELECT * FROM progress WHERE user_id=? AND slug=?",
                        (uid, body.slug)).fetchone()
        return {"progress": dict(r)}


class NoteIn(BaseModel):
    slug: str
    body: str = ""


@app.get("/api/notes")
def list_notes(uid: int = Depends(current_user)):
    with db.connect() as con:
        return {"notes": db.rows(
            con, "SELECT * FROM notes WHERE user_id=? ORDER BY updated DESC",
            (uid,))}


@app.put("/api/notes")
def put_note(body: NoteIn, uid: int = Depends(current_user)):
    with db.connect() as con:
        con.execute(
            "INSERT INTO notes(user_id,slug,body,updated) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,slug) DO UPDATE SET body=excluded.body, "
            "updated=excluded.updated",
            (uid, body.slug, body.body, db.now()))
    return {"ok": True}


# ------------------------------------------------------------ MAKE track

def _shipped_count(con, uid: int) -> int:
    r = con.execute("SELECT COUNT(*) c FROM pieces WHERE user_id=? AND "
                    "status='shipped'", (uid,)).fetchone()
    return r["c"] if r else 0


@app.get("/api/brief")
def get_brief(seed: int = 0, craft: str = "any", uid: int = Depends(current_user)):
    """Generate a brief. seed=0 gives the stable brief for this ISO week."""
    with db.connect() as con:
        shipped = _shipped_count(con, uid)
        recent = [r["medium"] for r in con.execute(
            "SELECT medium FROM pieces WHERE user_id=? ORDER BY created DESC "
            "LIMIT 2", (uid,))]
    if not seed:
        # Stable per user per week, so refreshing the page doesn't reroll it.
        seed = abs(hash((uid, briefs.week_id()))) % (2 ** 31)
    level = min(4, shipped // 4)
    return {"brief": briefs.generate(seed, level, craft, avoid=recent),
             "shipped": shipped}


class PieceIn(BaseModel):
    title: str = ""
    week: str = ""
    brief: dict | None = None
    medium: str = ""
    constraint_note: str = ""
    rubric: str = ""
    status: str = "briefed"
    deadline: str = ""
    shipped: str = ""
    link: str = ""
    pm_reads: str = ""
    pm_why: str = ""
    pm_study: str = ""
    pm_slug: str = ""


@app.get("/api/pieces")
def list_pieces(uid: int = Depends(current_user)):
    with db.connect() as con:
        out = db.rows(con, "SELECT * FROM pieces WHERE user_id=? "
                           "ORDER BY created DESC", (uid,))
    for p in out:
        try:
            p["brief"] = json.loads(p["brief"] or "{}")
        except json.JSONDecodeError:
            p["brief"] = {}
    return {"pieces": out}


@app.post("/api/pieces")
def create_piece(body: PieceIn, uid: int = Depends(current_user)):
    if body.status not in PIECE_STATUS:
        raise HTTPException(400, "unknown status")
    now = db.now()
    with db.connect() as con:
        c = con.execute(
            "INSERT INTO pieces(user_id,title,week,brief,medium,constraint_note,"
            "rubric,status,deadline,shipped,link,pm_reads,pm_why,pm_study,"
            "pm_slug,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, body.title, body.week or briefs.week_id(),
             json.dumps(body.brief or {}), body.medium, body.constraint_note,
             body.rubric, body.status, body.deadline or briefs.week_end(),
             body.shipped, body.link, body.pm_reads, body.pm_why, body.pm_study,
             body.pm_slug, now, now))
        return {"id": c.lastrowid}


@app.patch("/api/pieces/{pid}")
def update_piece(pid: int, body: PieceIn, uid: int = Depends(current_user)):
    if body.status not in PIECE_STATUS:
        raise HTTPException(400, "unknown status")
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM pieces WHERE id=? AND user_id=?",
                           (pid, uid)).fetchone():
            raise HTTPException(404, "no such piece")
        con.execute(
            "UPDATE pieces SET title=?,week=?,brief=?,medium=?,constraint_note=?,"
            "rubric=?,status=?,deadline=?,shipped=?,link=?,pm_reads=?,pm_why=?,"
            "pm_study=?,pm_slug=?,updated=? WHERE id=? AND user_id=?",
            (body.title, body.week, json.dumps(body.brief or {}), body.medium,
             body.constraint_note, body.rubric, body.status, body.deadline,
             body.shipped, body.link, body.pm_reads, body.pm_why, body.pm_study,
             body.pm_slug, db.now(), pid, uid))
    return {"ok": True}


@app.delete("/api/pieces/{pid}")
def delete_piece(pid: int, uid: int = Depends(current_user)):
    with db.connect() as con:
        con.execute("DELETE FROM pieces WHERE id=? AND user_id=?", (pid, uid))
    return {"ok": True}


# ------------------------------------------------------------ drills

class AttemptIn(BaseModel):
    drill: str
    level: int = 1
    correct: int = 0
    total: int = 0
    ms: int = 0
    detail: list | dict | None = None


@app.post("/api/drills/attempt")
def record_attempt(body: AttemptIn, uid: int = Depends(current_user)):
    if body.drill not in cur.DRILL_IDS:
        raise HTTPException(404, "unknown drill")
    if body.total < 0 or body.correct < 0 or body.correct > body.total:
        raise HTTPException(400, "impossible score")
    with db.connect() as con:
        con.execute(
            "INSERT INTO drill_attempts(user_id,drill,level,correct,total,ms,"
            "detail,created) VALUES(?,?,?,?,?,?,?,?)",
            (uid, body.drill, body.level, body.correct, body.total, body.ms,
             json.dumps(body.detail or []), db.now()))
    return {"ok": True}


@app.get("/api/drills/stats")
def drill_stats(uid: int = Depends(current_user)):
    """Per-drill accuracy plus a coarse trend: recent vs everything before.

    Perceptual learning shows up as a slow accuracy climb at a *rising* level,
    so the level is reported alongside — accuracy alone would look flat.
    """
    with db.connect() as con:
        per = db.rows(con,
                      "SELECT drill, COUNT(*) rounds, SUM(correct) correct, "
                      "SUM(total) total, MAX(level) level, MAX(created) last "
                      "FROM drill_attempts WHERE user_id=? GROUP BY drill", (uid,))
        recent = db.rows(con,
                         "SELECT drill, SUM(correct) c, SUM(total) t FROM "
                         "(SELECT * FROM drill_attempts WHERE user_id=? "
                         " ORDER BY created DESC LIMIT 40) GROUP BY drill", (uid,))
        series = db.rows(con,
                         "SELECT drill, level, correct, total, created FROM "
                         "drill_attempts WHERE user_id=? ORDER BY created ASC "
                         "LIMIT 2000", (uid,))
    rmap = {r["drill"]: r for r in recent}
    for p in per:
        r = rmap.get(p["drill"])
        p["recent_pct"] = round(100 * r["c"] / r["t"]) if r and r["t"] else None
        p["pct"] = round(100 * p["correct"] / p["total"]) if p["total"] else 0
    return {"per_drill": per, "series": series}


# ------------------------------------------------------------ vocabulary SRS

class ReviewIn(BaseModel):
    term: str
    grade: int          # 0 again, 1 hard, 2 good, 3 easy


DAY = 86400


@app.get("/api/vocab/due")
def vocab_due(limit: int = 20, uid: int = Depends(current_user)):
    """Cards due now, then unseen ones, so a new deck starts immediately."""
    now = db.now()
    with db.connect() as con:
        seen = {r["term"]: dict(r) for r in con.execute(
            "SELECT * FROM vocab_srs WHERE user_id=?", (uid,))}
    known = [t for t in seen.values() if t["due"] <= now
             and t["term"] in library.TERM_INDEX]
    known.sort(key=lambda r: r["due"])
    fresh = [t for t, _, _ in library.TERMS if t not in seen]
    cards = [{**library.TERM_INDEX[r["term"]], "srs": r} for r in known]
    cards += [{**library.TERM_INDEX[t], "srs": None} for t in fresh]
    return {"cards": cards[:limit], "due": len(known), "new": len(fresh),
            "total": len(library.TERMS)}


@app.post("/api/vocab/review")
def vocab_review(body: ReviewIn, uid: int = Depends(current_user)):
    """SM-2 lite. Grade 0 resets the interval and costs ease; 3 accelerates."""
    if body.term not in library.TERM_INDEX:
        raise HTTPException(404, "unknown term")
    g = max(0, min(3, body.grade))
    now = db.now()
    with db.connect() as con:
        row = con.execute("SELECT * FROM vocab_srs WHERE user_id=? AND term=?",
                          (uid, body.term)).fetchone()
        ease = row["ease"] if row else 2.5
        interval = row["interval_days"] if row else 0.0
        reps = row["reps"] if row else 0
        lapses = row["lapses"] if row else 0

        if g == 0:
            ease, interval, lapses, reps = max(1.3, ease - 0.2), 0.0, lapses + 1, 0
        else:
            ease = min(3.0, max(1.3, ease + (-0.15, 0.0, 0.15)[g - 1]))
            if reps == 0:
                interval = 1.0
            elif reps == 1:
                interval = 3.0
            else:
                interval = interval * ease * (0.8 if g == 1 else 1.0)
            reps += 1
        due = now + int(max(0.02, interval) * DAY)  # 0 → ~30 min, same session
        con.execute(
            "INSERT INTO vocab_srs(user_id,term,ease,interval_days,due,reps,"
            "lapses,updated) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id,term) DO UPDATE SET ease=excluded.ease, "
            "interval_days=excluded.interval_days, due=excluded.due, "
            "reps=excluded.reps, lapses=excluded.lapses, updated=excluded.updated",
            (uid, body.term, ease, interval, due, reps, lapses, now))
    return {"ok": True, "interval_days": round(interval, 2)}


@app.get("/api/vocab/stats")
def vocab_stats(uid: int = Depends(current_user)):
    now = db.now()
    with db.connect() as con:
        rows = db.rows(con, "SELECT * FROM vocab_srs WHERE user_id=?", (uid,))
    learning = [r for r in rows if r["interval_days"] < 7]
    mature = [r for r in rows if r["interval_days"] >= 21]
    return {"seen": len(rows), "total": len(library.TERMS),
            "due": sum(1 for r in rows if r["due"] <= now),
            "learning": len(learning), "mature": len(mature)}


# ------------------------------------------------------------ practice log

class PracticeIn(BaseModel):
    day: str
    track: str = "tools"
    tool: str = ""
    slug: str = ""
    focus: str = ""
    minutes: int = 0
    rating: int = 0
    notes: str = ""


@app.get("/api/practice")
def list_practice(limit: int = 200, uid: int = Depends(current_user)):
    with db.connect() as con:
        return {"practice": db.rows(
            con, "SELECT * FROM practice_log WHERE user_id=? ORDER BY day DESC, "
                 "created DESC LIMIT ?", (uid, limit))}


@app.post("/api/practice")
def add_practice(body: PracticeIn, uid: int = Depends(current_user)):
    if body.track not in TRACK_IDS:
        raise HTTPException(400, "unknown track")
    with db.connect() as con:
        c = con.execute(
            "INSERT INTO practice_log(user_id,day,track,tool,slug,focus,minutes,"
            "rating,notes,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (uid, body.day, body.track, body.tool, body.slug, body.focus,
             max(0, body.minutes), body.rating, body.notes, db.now()))
        return {"id": c.lastrowid}


@app.delete("/api/practice/{pid}")
def delete_practice(pid: int, uid: int = Depends(current_user)):
    with db.connect() as con:
        con.execute("DELETE FROM practice_log WHERE id=? AND user_id=?",
                    (pid, uid))
    return {"ok": True}


# ------------------------------------------------------------ taste selections

class SelectionIn(BaseModel):
    sandbox: str
    chosen: dict
    candidates: list = []
    rationale: str = ""


@app.get("/api/selections")
def list_selections(limit: int = 100, uid: int = Depends(current_user)):
    with db.connect() as con:
        out = db.rows(con, "SELECT * FROM selections WHERE user_id=? "
                           "ORDER BY created DESC LIMIT ?", (uid, limit))
    for s in out:
        for k in ("chosen", "candidates"):
            try:
                s[k] = json.loads(s[k])
            except json.JSONDecodeError:
                s[k] = {} if k == "chosen" else []
    return {"selections": out}


@app.post("/api/selections")
def add_selection(body: SelectionIn, uid: int = Depends(current_user)):
    with db.connect() as con:
        c = con.execute(
            "INSERT INTO selections(user_id,sandbox,chosen,candidates,rationale,"
            "created) VALUES(?,?,?,?,?,?)",
            (uid, body.sandbox, json.dumps(body.chosen),
             json.dumps(body.candidates), body.rationale, db.now()))
        return {"id": c.lastrowid}


# ------------------------------------------------------------ reference analyses

class AnalysisIn(BaseModel):
    kind: str = "image"
    name: str = ""
    features: dict = {}
    notes: str = ""


@app.get("/api/analyses")
def list_analyses(uid: int = Depends(current_user)):
    with db.connect() as con:
        out = db.rows(con, "SELECT * FROM analyses WHERE user_id=? "
                           "ORDER BY created DESC", (uid,))
    for a in out:
        try:
            a["features"] = json.loads(a["features"])
        except json.JSONDecodeError:
            a["features"] = {}
    return {"analyses": out}


@app.post("/api/analyses")
def add_analysis(body: AnalysisIn, uid: int = Depends(current_user)):
    if body.kind not in ("image", "audio"):
        raise HTTPException(400, "kind must be image or audio")
    with db.connect() as con:
        c = con.execute(
            "INSERT INTO analyses(user_id,kind,name,features,notes,created) "
            "VALUES(?,?,?,?,?,?)",
            (uid, body.kind, body.name, json.dumps(body.features), body.notes,
             db.now()))
        return {"id": c.lastrowid}


@app.patch("/api/analyses/{aid}")
def update_analysis(aid: int, body: AnalysisIn, uid: int = Depends(current_user)):
    with db.connect() as con:
        con.execute("UPDATE analyses SET notes=?, name=? WHERE id=? AND user_id=?",
                    (body.notes, body.name, aid, uid))
    return {"ok": True}


@app.delete("/api/analyses/{aid}")
def delete_analysis(aid: int, uid: int = Depends(current_user)):
    with db.connect() as con:
        con.execute("DELETE FROM analyses WHERE id=? AND user_id=?", (aid, uid))
    return {"ok": True}


# ------------------------------------------------------------ articulation

class ArticulationIn(BaseModel):
    kind: str = "teachback"
    slug: str = ""
    prompt: str = ""
    body: str = ""
    predicted: str = ""
    actual: str = ""
    score: int = 0


@app.get("/api/articulation")
def list_articulation(uid: int = Depends(current_user)):
    with db.connect() as con:
        return {"reps": db.rows(
            con, "SELECT * FROM articulation WHERE user_id=? ORDER BY created "
                 "DESC", (uid,))}


@app.post("/api/articulation")
def add_articulation(body: ArticulationIn, uid: int = Depends(current_user)):
    if body.kind not in ARTICULATION_IDS:
        raise HTTPException(404, "unknown protocol")
    with db.connect() as con:
        c = con.execute(
            "INSERT INTO articulation(user_id,kind,slug,prompt,body,predicted,"
            "actual,score,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (uid, body.kind, body.slug, body.prompt, body.body, body.predicted,
             body.actual, max(0, min(100, body.score)), db.now()))
        return {"id": c.lastrowid}


@app.patch("/api/articulation/{rid}")
def update_articulation(rid: int, body: ArticulationIn,
                        uid: int = Depends(current_user)):
    with db.connect() as con:
        con.execute("UPDATE articulation SET body=?, actual=?, score=? "
                    "WHERE id=? AND user_id=?",
                    (body.body, body.actual, max(0, min(100, body.score)),
                     rid, uid))
    return {"ok": True}


@app.delete("/api/articulation/{rid}")
def delete_articulation(rid: int, uid: int = Depends(current_user)):
    with db.connect() as con:
        con.execute("DELETE FROM articulation WHERE id=? AND user_id=?",
                    (rid, uid))
    return {"ok": True}


# ------------------------------------------------------------ lab saves

class LabSaveIn(BaseModel):
    lab: str
    name: str = ""
    params: dict = {}
    source: str = ""
    note: str = ""


@app.get("/api/labs/saves")
def list_lab_saves(uid: int = Depends(current_user)):
    with db.connect() as con:
        out = db.rows(con, "SELECT * FROM lab_saves WHERE user_id=? "
                           "ORDER BY created DESC", (uid,))
    for s in out:
        try:
            s["params"] = json.loads(s["params"])
        except json.JSONDecodeError:
            s["params"] = {}
    return {"saves": out}


@app.post("/api/labs/saves")
def add_lab_save(body: LabSaveIn, uid: int = Depends(current_user)):
    if body.lab not in cur.LAB_IDS:
        raise HTTPException(404, "unknown lab")
    with db.connect() as con:
        c = con.execute(
            "INSERT INTO lab_saves(user_id,lab,name,params,source,note,created) "
            "VALUES(?,?,?,?,?,?,?)",
            (uid, body.lab, body.name or "untitled", json.dumps(body.params),
             body.source, body.note, db.now()))
        return {"id": c.lastrowid}


@app.delete("/api/labs/saves/{sid}")
def delete_lab_save(sid: int, uid: int = Depends(current_user)):
    with db.connect() as con:
        con.execute("DELETE FROM lab_saves WHERE id=? AND user_id=?", (sid, uid))
    return {"ok": True}


# ------------------------------------------------------------ dashboard

@app.get("/api/today")
def today(uid: int = Depends(current_user)):
    """Everything the Today view needs, in one round trip.

    The dashboard's job is to make the week's obligation unavoidable and to
    put the next drill one click away. Everything else is secondary.
    """
    now = db.now()
    week = briefs.week_id()
    with db.connect() as con:
        piece = con.execute(
            "SELECT * FROM pieces WHERE user_id=? AND week=? "
            "ORDER BY created DESC LIMIT 1", (uid, week)).fetchone()
        shipped = _shipped_count(con, uid)
        drill_rows = db.rows(con,
                             "SELECT drill, MAX(created) last, SUM(correct) c, "
                             "SUM(total) t FROM drill_attempts WHERE user_id=? "
                             "GROUP BY drill", (uid,))
        streak_days = [r["day"] for r in con.execute(
            "SELECT DISTINCT day FROM practice_log WHERE user_id=? "
            "ORDER BY day DESC LIMIT 60", (uid,))]
        minutes_week = con.execute(
            "SELECT COALESCE(SUM(minutes),0) m FROM practice_log WHERE user_id=? "
            "AND created>=?", (uid, now - 7 * DAY)).fetchone()["m"]
        vocab = con.execute(
            "SELECT COUNT(*) c FROM vocab_srs WHERE user_id=? AND due<=?",
            (uid, now)).fetchone()["c"]
        seen_terms = con.execute(
            "SELECT COUNT(*) c FROM vocab_srs WHERE user_id=?", (uid,)
        ).fetchone()["c"]
        pieces_recent = db.rows(con,
                                "SELECT id,title,week,status,medium,pm_reads "
                                "FROM pieces WHERE user_id=? ORDER BY created "
                                "DESC LIMIT 5", (uid,))

    # Coldest drills first: never-attempted, then longest since last touched.
    touched = {r["drill"]: r for r in drill_rows}
    cold = []
    for d in cur.DRILLS:
        r = touched.get(d["id"])
        cold.append({
            "id": d["id"], "title": d["title"], "craft": d["craft"],
            "dim": d["dim"],
            "last": r["last"] if r else 0,
            "pct": round(100 * r["c"] / r["t"]) if r and r["t"] else None,
        })
    cold.sort(key=lambda x: x["last"])
    # Interleave ear and eye. Sorting alone hands back five ear drills on a
    # fresh account, which reads as an app that only does audio.
    ear = [d for d in cold if d["craft"] == "audio"]
    eye = [d for d in cold if d["craft"] == "visual"]
    cold = [d for pair in zip(ear, eye) for d in pair]
    cold += ear[len(eye):] + eye[len(ear):]

    out = {
        "week": week,
        "deadline": briefs.week_end(),
        "piece": dict(piece) if piece else None,
        "shipped": shipped,
        "level": min(4, shipped // 4),
        "cold_drills": cold[:5],
        "vocab_due": vocab,
        "vocab_seen": seen_terms,
        "vocab_total": len(library.TERMS),
        "minutes_week": minutes_week,
        "practice_days": streak_days,
        "recent_pieces": pieces_recent,
    }
    if out["piece"]:
        try:
            out["piece"]["brief"] = json.loads(out["piece"]["brief"] or "{}")
        except json.JSONDecodeError:
            out["piece"]["brief"] = {}
    return out


# ------------------------------------------------------------ kv / prefs

@app.get("/api/kv/{key}")
def kv_get(key: str, uid: int = Depends(current_user)):
    if key not in KV_KEYS:
        raise HTTPException(404, "unknown key")
    with db.connect() as con:
        r = con.execute("SELECT value FROM kv WHERE user_id=? AND key=?",
                        (uid, key)).fetchone()
    try:
        return {"value": json.loads(r["value"]) if r else {}}
    except json.JSONDecodeError:
        return {"value": {}}


@app.put("/api/kv/{key}")
def kv_put(key: str, value: dict, uid: int = Depends(current_user)):
    if key not in KV_KEYS:
        raise HTTPException(404, "unknown key")
    with db.connect() as con:
        con.execute(
            "INSERT INTO kv(user_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
            (uid, key, json.dumps(value)))
    return {"ok": True}


# ------------------------------------------------------------ seed / backup

@app.post("/api/seed")
def seed(uid: int = Depends(current_user)):
    with db.connect() as con:
        added = seeder.seed_user(con, uid)
    return {"ok": True, **added}


@app.get("/api/backup")
def backup(uid: int = Depends(current_user)):
    with db.connect() as con:
        data = {t: db.rows(con, f"SELECT * FROM {t} WHERE user_id=?", (uid,))
                for t in BACKUP_TABLES}
        data["kv"] = db.rows(con, "SELECT key,value FROM kv WHERE user_id=?",
                             (uid,))
    for table in data.values():
        for row in table:
            row.pop("user_id", None)
            row.pop("id", None)
    return JSONResponse(
        {"format": BACKUP_FORMAT, "exported": db.now(), "data": data},
        headers={"Content-Disposition":
                 f'attachment; filename="av-trainer-{time.strftime("%Y%m%d")}.json"'})


@app.post("/api/restore")
def restore(payload: dict, uid: int = Depends(current_user)):
    if payload.get("format") != BACKUP_FORMAT:
        raise HTTPException(400, "not an AV Trainer backup file")
    data = payload.get("data") or {}
    counts = {}
    with db.connect() as con:
        for table in BACKUP_TABLES:
            rows = data.get(table) or []
            if not rows:
                continue
            con.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({table})")
                    if c[1] not in ("id",)]
            for row in rows:
                vals = [uid if c == "user_id" else row.get(c, "") for c in cols]
                con.execute(
                    f"INSERT INTO {table}({','.join(cols)}) "
                    f"VALUES({','.join('?' * len(cols))})", vals)
            counts[table] = len(rows)
        for row in data.get("kv") or []:
            con.execute(
                "INSERT INTO kv(user_id,key,value) VALUES(?,?,?) "
                "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                (uid, row.get("key", ""), row.get("value", "")))
    return {"ok": True, "restored": counts}


# ------------------------------------------------------------ static PWA

@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


@app.get("/sw.js")
def service_worker():
    return FileResponse(config.FRONTEND_DIR / "sw.js",
                        media_type="application/javascript")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(config.FRONTEND_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


# The studio and AI routers take current_user as an argument rather than
# importing it, so those modules never have to import main back.
studio.register(app, current_user)
ai.register(app, current_user)
course.register(app, current_user)


class RevalidatingStatics(StaticFiles):
    """Serve the frontend with 'no-cache'.

    Not 'no-store' — the etag still does its job, so a repeat load is a cheap
    304. But without this there is no Cache-Control at all, browsers fall back
    to heuristic freshness, and an updated app keeps serving yesterday's
    JavaScript out of the HTTP cache. The service worker is what handles
    offline; the network copy should always be the current one.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        response_headers.setdefault("cache-control", "no-cache")
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("cache-control", "no-cache")
        return response


app.mount("/static", RevalidatingStatics(directory=config.FRONTEND_DIR),
          name="static")
