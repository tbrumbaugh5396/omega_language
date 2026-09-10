"""Ideas: notes that link to each other, and the graph they make.

A business accumulates thinking that has no table to live in — why the
second shop is where it is, what was learned from the campaign that
flopped, the three suppliers somebody keeps meaning to compare. It ends
up in a document nobody reopens. This is the other shape for it: short
notes, each of which can point at others by writing the other's title in
double brackets, and a graph of what points at what, because the useful
question about a note is rarely "what does it say" and usually "what
does it touch".

Two rules, both borrowed from the tools that do this well:

  **A link is text.** Write `[[Second shop]]` inside a note and the link
  exists. Rename nothing, register nothing. A note that is linked to but
  does not yet exist is a dotted node in the graph, which is how the
  graph tells you what you have not written down yet.

  **Nothing is deleted from the graph by accident.** Removing a note
  removes it; the links that pointed at it become dotted again rather
  than vanishing, because the fact that three notes referred to it is
  itself worth seeing.

Explicit links — "this depends on that", "this contradicts that" — sit
beside the text ones with a label, for the connection the prose does not
make on its own.
"""
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,               -- lower-cased title, for [[matching]]
  body TEXT DEFAULT '',
  tags TEXT DEFAULT '',                    -- comma separated
  colour TEXT DEFAULT '',
  pinned INTEGER DEFAULT 0,
  by_id INTEGER DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

/* Links, of two kinds in one table: those written as [[text]] in a body
   (kind 'wiki', rewritten on every save) and those declared with a label
   (kind 'explicit', kept until removed). A target that does not exist as
   a note yet is kept by title, so it can be drawn as a dotted node. */
CREATE TABLE IF NOT EXISTS idea_links (
  id INTEGER PRIMARY KEY,
  from_id INTEGER NOT NULL,
  to_id INTEGER DEFAULT 0,                 -- 0 = not written yet
  to_title TEXT DEFAULT '',
  kind TEXT DEFAULT 'wiki',                -- wiki|explicit
  label TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idea_links_from ON idea_links(from_id);
CREATE INDEX IF NOT EXISTS idea_links_to ON idea_links(to_id);
"""

WIKI = re.compile(r"\[\[([^\[\]|]+?)(?:\|[^\[\]]*)?\]\]")


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _slug(title: str) -> str:
    return " ".join(title.lower().split())[:200]


def _may(user) -> bool:
    return auth.office(user) or user["role"] in (
        "employee", "teacher", "director", "board", "volunteer")


def _require(user) -> None:
    if not _may(user):
        raise HTTPException(403, "ideas are the team's")


def relink(con, idea_id: int, body: str) -> None:
    """Rewrite the [[text]] links from one note's body. Explicit links are
    somebody's decision and are left alone."""
    con.execute("DELETE FROM idea_links WHERE from_id=? AND kind='wiki'",
                (idea_id,))
    seen = set()
    for m in WIKI.finditer(body or ""):
        title = m.group(1).strip()
        key = _slug(title)
        if not key or key in seen:
            continue
        seen.add(key)
        target = con.execute("SELECT id FROM ideas WHERE slug=?", (key,)).fetchone()
        con.execute(
            "INSERT INTO idea_links(from_id,to_id,to_title,kind,created_at)"
            " VALUES(?,?,?,'wiki',?)",
            (idea_id, target["id"] if target else 0, title[:200], db.now()))
    con.commit()


def adopt(con, idea_id: int, slug: str) -> int:
    """A note just written claims every dotted link that was pointing at
    its title. Returns how many."""
    cur = con.execute("UPDATE idea_links SET to_id=? WHERE to_id=0 AND"
                      " lower(to_title)=?", (idea_id, slug))
    con.commit()
    return cur.rowcount


def graph(con) -> dict:
    nodes = [dict(r) for r in con.execute(
        "SELECT id, title, tags, colour, pinned, updated_at,"
        " length(body) AS size FROM ideas ORDER BY title").fetchall()]
    links = [dict(r) for r in con.execute(
        "SELECT from_id, to_id, to_title, kind, label FROM idea_links").fetchall()]
    # Titles that are pointed at and not yet written: dotted nodes.
    ghosts = {}
    for l in links:
        if not l["to_id"]:
            ghosts.setdefault(_slug(l["to_title"]), l["to_title"])
    deg = {}
    for l in links:
        deg[l["from_id"]] = deg.get(l["from_id"], 0) + 1
        if l["to_id"]:
            deg[l["to_id"]] = deg.get(l["to_id"], 0) + 1
    for n in nodes:
        n["degree"] = deg.get(n["id"], 0)
        n["tags"] = [t.strip() for t in (n["tags"] or "").split(",") if t.strip()]
    return {"nodes": nodes,
            "ghosts": [{"title": t, "slug": s_} for s_, t in ghosts.items()],
            "links": links}


def shape(con, r) -> dict:
    d = dict(r)
    d["tags"] = [t.strip() for t in (d["tags"] or "").split(",") if t.strip()]
    d["links_out"] = [dict(x) for x in con.execute(
        "SELECT l.*, i.title AS to_title_now FROM idea_links l"
        " LEFT JOIN ideas i ON i.id=l.to_id WHERE l.from_id=?"
        " ORDER BY l.kind, l.id", (r["id"],)).fetchall()]
    d["links_in"] = [dict(x) for x in con.execute(
        "SELECT l.id, l.kind, l.label, i.id AS from_id, i.title AS from_title"
        " FROM idea_links l JOIN ideas i ON i.id=l.from_id WHERE l.to_id=?"
        " ORDER BY i.title", (r["id"],)).fetchall()]
    return d


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/ideas")
def ideas_page(q: str = "", user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    g = graph(con)
    if q.strip():
        needle = f"%{q.strip().lower()}%"
        hits = {r["id"] for r in con.execute(
            "SELECT id FROM ideas WHERE lower(title) LIKE ? OR lower(body) LIKE ?"
            " OR lower(tags) LIKE ?", (needle, needle, needle)).fetchall()}
        g["hits"] = sorted(hits)
    return g


@router.get("/api/ideas/{iid}")
def idea_get(iid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    r = con.execute("SELECT * FROM ideas WHERE id=?", (iid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such idea")
    return shape(con, r)


class IdeaBody(BaseModel):
    id: int = 0
    title: str
    body: str = ""
    tags: str = ""
    colour: str = ""
    pinned: bool = False


@router.post("/api/ideas")
def idea_save(body: IdeaBody, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    title = " ".join(body.title.split())[:200]
    if not title:
        raise HTTPException(400, "an idea needs a title — it is what the "
                                 "links point at")
    slug = _slug(title)
    clash = con.execute("SELECT id FROM ideas WHERE slug=? AND id<>?",
                        (slug, body.id)).fetchone()
    if clash:
        raise HTTPException(409, f"there is already a note called "
                                 f"'{title}' — links are by title, so two "
                                 "of them would point nowhere certain")
    now = time.time()
    tags = ",".join(t.strip() for t in body.tags.split(",") if t.strip())[:400]
    if body.id:
        if con.execute("SELECT 1 FROM ideas WHERE id=?", (body.id,)).fetchone() is None:
            raise HTTPException(404, "no such idea")
        con.execute(
            "UPDATE ideas SET title=?, slug=?, body=?, tags=?, colour=?, pinned=?,"
            " updated_at=? WHERE id=?",
            (title, slug, body.body[:100_000], tags, body.colour[:20],
             int(body.pinned), now, body.id))
        iid = body.id
    else:
        cur = con.execute(
            "INSERT INTO ideas(title,slug,body,tags,colour,pinned,by_id,"
            " created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (title, slug, body.body[:100_000], tags, body.colour[:20],
             int(body.pinned), user["id"], db.now(), now))
        iid = cur.lastrowid
    con.commit()
    relink(con, iid, body.body)
    claimed = adopt(con, iid, slug)
    return {"ok": True, "id": iid, "claimed": claimed}


@router.delete("/api/ideas/{iid}")
def idea_delete(iid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    r = con.execute("SELECT * FROM ideas WHERE id=?", (iid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such idea")
    # What pointed here keeps pointing, at a title with no note behind
    # it. That three notes referred to this one is worth seeing.
    con.execute("UPDATE idea_links SET to_id=0, to_title=? WHERE to_id=?",
                (r["title"], iid))
    con.execute("DELETE FROM idea_links WHERE from_id=?", (iid,))
    con.execute("DELETE FROM ideas WHERE id=?", (iid,))
    con.commit()
    return {"ok": True}


class LinkBody(BaseModel):
    to_id: int = 0
    to_title: str = ""
    label: str = ""


@router.post("/api/ideas/{iid}/links")
def idea_link(iid: int, body: LinkBody, user=Depends(current_user),
              con=Depends(get_con)):
    """An explicit connection with a label: the one the prose does not
    make on its own."""
    _require(user)
    if con.execute("SELECT 1 FROM ideas WHERE id=?", (iid,)).fetchone() is None:
        raise HTTPException(404, "no such idea")
    to_id, to_title = body.to_id, body.to_title.strip()
    if to_id:
        t = con.execute("SELECT title FROM ideas WHERE id=?", (to_id,)).fetchone()
        if t is None:
            raise HTTPException(404, "no such target")
        to_title = t["title"]
    elif to_title:
        t = con.execute("SELECT id FROM ideas WHERE slug=?",
                        (_slug(to_title),)).fetchone()
        to_id = t["id"] if t else 0
    else:
        raise HTTPException(400, "link to something")
    if to_id == iid:
        raise HTTPException(400, "an idea cannot link to itself")
    cur = con.execute(
        "INSERT INTO idea_links(from_id,to_id,to_title,kind,label,created_at)"
        " VALUES(?,?,?,'explicit',?,?)",
        (iid, to_id, to_title[:200], body.label.strip()[:80], db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/ideas/links/{lid}")
def idea_unlink(lid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    con.execute("DELETE FROM idea_links WHERE id=? AND kind='explicit'", (lid,))
    con.commit()
    return {"ok": True}
