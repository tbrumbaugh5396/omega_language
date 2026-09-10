"""Cameras: every property on one wall.

A business with three sites has three camera apps, three logins and no
way to see all of them at once. This is one wall: each feed a tile,
grouped by where it is, the whole estate on one screen — and a tile
opened large when something is worth a closer look.

What a browser can and cannot show, stated rather than discovered:

  **MJPEG** streams (most IP cameras' `/mjpeg` or `/video.cgi`) play in a
  plain <img>. **Snapshots** — a JPEG the camera re-serves — are shown and
  refreshed every few seconds, and work with almost anything. **HLS**
  (`.m3u8`) plays natively in Safari and needs a player elsewhere, which
  is vendored. A camera that serves its own **web page** can be framed.

  **RTSP cannot be played by any browser.** Most cameras speak it and
  nothing else, and the honest answer is a relay: `ffmpeg` on a box that
  can reach the camera turns RTSP into HLS in a folder this server
  serves. The command is on the screen. There is no way round that in a
  page, and a feature that pretended to play RTSP would be a spinner.

  **The browser fetches the feed, not this server.** A camera has to be
  reachable from wherever the wall is being looked at: on the same
  network, through a VPN, port-forwarded, or by the vendor's cloud URL.
  This install does not proxy video, on purpose — a server that fetches
  any URL a form is given is a server that can be pointed at anything
  on its own network.

  An install served over HTTPS cannot show a camera served over plain
  HTTP; browsers refuse that. The screen says which tiles that affects.

Nothing is recorded here. A recording is the camera's job, or the
relay's, and a page that appeared to keep footage while keeping none
would be worse than one that says so.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db

TABLES = """
CREATE TABLE IF NOT EXISTS cameras (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  site TEXT DEFAULT '',                    -- the property, as a label
  store_id INTEGER DEFAULT 0,              -- or one of the stores
  kind TEXT NOT NULL DEFAULT 'snapshot',   -- see KINDS
  url TEXT NOT NULL,
  refresh_sec INTEGER DEFAULT 5,           -- snapshot only
  position INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
"""

KINDS = {
    "snapshot": "A still image the camera re-serves, refreshed every few "
                "seconds. Works with almost anything.",
    "mjpeg": "A motion-JPEG stream. Most IP cameras have one.",
    "hls": "An HLS stream (.m3u8). Native in Safari; a player is loaded "
           "elsewhere.",
    "iframe": "The camera's own web page, framed.",
}

RELAY = ("ffmpeg -rtsp_transport tcp -i 'rtsp://user:pass@camera/stream' "
         "-c:v copy -an -f hls -hls_time 2 -hls_list_size 6 "
         "-hls_flags delete_segments {folder}/cam.m3u8")


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return auth.office(user, "settings")


def _may_see(user) -> bool:
    return _office(user) or user["role"] in ("employee",)


def wall(con) -> dict:
    rows = [dict(r) for r in con.execute(
        "SELECT c.*, s.name AS store_name FROM cameras c"
        " LEFT JOIN stores s ON s.id=c.store_id"
        " WHERE c.active=1 ORDER BY c.site, c.position, c.id").fetchall()]
    sites = {}
    for r in rows:
        r["where"] = r["site"] or r["store_name"] or "Unplaced"
        r["plain_http"] = r["url"].lower().startswith("http://")
        sites.setdefault(r["where"], []).append(r)
    return {"cameras": rows,
            "sites": [{"name": k, "cameras": v} for k, v in sites.items()],
            "kinds": [{"k": k, "what": v} for k, v in KINDS.items()],
            "relay": RELAY}


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/cameras")
def cameras_page(user=Depends(current_user), con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "the wall is staff's")
    d = wall(con)
    d["can_edit"] = _office(user)
    d["stores"] = [dict(r) for r in con.execute(
        "SELECT id, name, city FROM stores WHERE active=1 ORDER BY name").fetchall()]
    return d


class CameraBody(BaseModel):
    id: int = 0
    name: str
    site: str = ""
    store_id: int = 0
    kind: str = "snapshot"
    url: str
    refresh_sec: int = 5
    position: int = 0
    active: bool = True
    note: str = ""


@router.post("/api/cameras")
def camera_save(body: CameraBody, user=Depends(current_user),
                con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {sorted(KINDS)}")
    url = body.url.strip()
    low = url.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        if low.startswith("rtsp://"):
            raise HTTPException(
                400, "no browser can play RTSP. Run the relay on a machine "
                     "that can reach the camera — the command is on the "
                     "screen — and give this the .m3u8 it writes")
        raise HTTPException(400, "a feed is an http or https URL")
    if not body.name.strip():
        raise HTTPException(400, "name the camera by where it points")
    if body.refresh_sec < 1 or body.refresh_sec > 300:
        raise HTTPException(400, "refresh between 1 and 300 seconds")
    if body.store_id and con.execute("SELECT 1 FROM stores WHERE id=?",
                                     (body.store_id,)).fetchone() is None:
        raise HTTPException(404, "no such store")
    args = (body.name.strip()[:120], body.site.strip()[:120], body.store_id,
            body.kind, url[:800], body.refresh_sec, body.position,
            int(body.active), body.note.strip()[:400])
    if body.id:
        con.execute(
            "UPDATE cameras SET name=?, site=?, store_id=?, kind=?, url=?,"
            " refresh_sec=?, position=?, active=?, note=? WHERE id=?",
            args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO cameras(name,site,store_id,kind,url,refresh_sec,position,"
        " active,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        args + (db.now(),))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/cameras/{cid}")
def camera_delete(cid: int, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    con.execute("DELETE FROM cameras WHERE id=?", (cid,))
    con.commit()
    return {"ok": True}
