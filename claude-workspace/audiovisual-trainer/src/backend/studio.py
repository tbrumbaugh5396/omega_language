"""Studio: project documents and the imported-media store.

The three editors (canvas, music, video) are completely different programs,
but they share a document row, an asset store, the AI panel and the link back
to a MAKE piece — so those live here once.

Media bytes go on disk under DATA_DIR/assets, not in SQLite. A video in a
database row is a mistake you only make once.

Blob reads are authorised by a per-asset capability key rather than the
session token, because <img> and <video> cannot send an Authorization header
and putting a session token in a URL is how it ends up in a log.
"""
import json
import mimetypes
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, db

router = APIRouter(prefix="/api/studio")

KINDS = ("canvas", "music", "video", "shader")
MAX_UPLOAD = 512 * 1024 * 1024        # 512 MB — a short 4K clip fits
ALLOWED_PREFIXES = ("image/", "audio/", "video/")


def assets_dir(uid: int) -> Path:
    d = config.DATA_DIR / "assets" / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _public(row: dict) -> dict:
    out = dict(row)
    out.pop("akey", None)
    return out


# ------------------------------------------------------------ projects

class ProjectIn(BaseModel):
    name: str = "untitled"
    kind: str = "canvas"
    data: dict = {}
    thumb: str = ""
    piece_id: int | None = None


def register(app, current_user):
    """Wire the routes. current_user is injected from main to avoid a cycle."""

    @router.get("/projects")
    def list_projects(uid: int = Depends(current_user)):
        with db.connect() as con:
            rows = db.rows(
                con, "SELECT id,name,kind,thumb,piece_id,created,updated "
                     "FROM studio_projects WHERE user_id=? ORDER BY updated DESC",
                (uid,))
        return {"projects": rows}

    @router.get("/projects/{pid}")
    def get_project(pid: int, uid: int = Depends(current_user)):
        with db.connect() as con:
            r = con.execute("SELECT * FROM studio_projects WHERE id=? AND user_id=?",
                            (pid, uid)).fetchone()
            if not r:
                raise HTTPException(404, "no such project")
            out = dict(r)
            assets = db.rows(
                con, "SELECT * FROM assets WHERE user_id=? AND project_id=? "
                     "ORDER BY created", (uid, pid))
        try:
            out["data"] = json.loads(out["data"] or "{}")
        except json.JSONDecodeError:
            out["data"] = {}
        out["assets"] = [_asset_public(a) for a in assets]
        return out

    @router.post("/projects")
    def create_project(body: ProjectIn, uid: int = Depends(current_user)):
        if body.kind not in KINDS:
            raise HTTPException(400, "unknown project kind")
        now = db.now()
        with db.connect() as con:
            c = con.execute(
                "INSERT INTO studio_projects(user_id,name,kind,data,thumb,"
                "piece_id,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                (uid, body.name.strip() or "untitled", body.kind,
                 json.dumps(body.data), body.thumb, body.piece_id, now, now))
            return {"id": c.lastrowid}

    @router.put("/projects/{pid}")
    def save_project(pid: int, body: ProjectIn, uid: int = Depends(current_user)):
        with db.connect() as con:
            if not con.execute("SELECT 1 FROM studio_projects WHERE id=? AND "
                               "user_id=?", (pid, uid)).fetchone():
                raise HTTPException(404, "no such project")
            con.execute(
                "UPDATE studio_projects SET name=?, data=?, thumb=?, piece_id=?, "
                "updated=? WHERE id=? AND user_id=?",
                (body.name.strip() or "untitled", json.dumps(body.data),
                 body.thumb, body.piece_id, db.now(), pid, uid))
        return {"ok": True}

    @router.delete("/projects/{pid}")
    def delete_project(pid: int, uid: int = Depends(current_user)):
        with db.connect() as con:
            rows = db.rows(con, "SELECT path FROM assets WHERE user_id=? AND "
                                "project_id=?", (uid, pid))
            con.execute("DELETE FROM assets WHERE user_id=? AND project_id=?",
                        (uid, pid))
            con.execute("DELETE FROM studio_projects WHERE id=? AND user_id=?",
                        (pid, uid))
        for r in rows:
            _unlink(r["path"])
        return {"ok": True}

    # ------------------------------------------------------------ assets

    @router.post("/assets")
    async def upload_asset(request: Request,
                           name: str = Query("file"),
                           mime: str = Query(""),
                           project_id: int | None = Query(None),
                           meta: str = Query("{}"),
                           uid: int = Depends(current_user)):
        """Raw-body upload.

        Deliberately not multipart: that would pull in python-multipart just to
        move bytes we already have, and streaming the raw body lets a large
        video land on disk without being held in memory twice.
        """
        kind = (mime or mimetypes.guess_type(name)[0] or "").lower()
        if not kind.startswith(ALLOWED_PREFIXES):
            raise HTTPException(400, "only image, audio and video files")

        suffix = Path(name).suffix[:12] or mimetypes.guess_extension(kind) or ""
        akey = secrets.token_urlsafe(24)
        stem = f"{secrets.token_hex(8)}{suffix}"
        dest = assets_dir(uid) / stem
        written = 0
        try:
            with open(dest, "wb") as f:
                async for chunk in request.stream():
                    written += len(chunk)
                    if written > MAX_UPLOAD:
                        raise HTTPException(413, "file is too large (512 MB limit)")
                    f.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise
        if not written:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "empty upload")

        try:
            meta_obj = json.loads(meta)
        except json.JSONDecodeError:
            meta_obj = {}

        rel = str(dest.relative_to(config.DATA_DIR))
        with db.connect() as con:
            c = con.execute(
                "INSERT INTO assets(user_id,project_id,name,mime,bytes,path,"
                "akey,meta,created) VALUES(?,?,?,?,?,?,?,?,?)",
                (uid, project_id, name, kind, written, rel, akey,
                 json.dumps(meta_obj), db.now()))
            row = con.execute("SELECT * FROM assets WHERE id=?",
                              (c.lastrowid,)).fetchone()
        return _asset_public(dict(row))

    @router.get("/assets")
    def list_assets(project_id: int | None = None, uid: int = Depends(current_user)):
        with db.connect() as con:
            if project_id is None:
                rows = db.rows(con, "SELECT * FROM assets WHERE user_id=? "
                                    "ORDER BY created DESC", (uid,))
            else:
                rows = db.rows(con, "SELECT * FROM assets WHERE user_id=? AND "
                                    "project_id=? ORDER BY created", (uid, project_id))
        return {"assets": [_asset_public(r) for r in rows]}

    @router.get("/assets/{aid}/blob")
    def read_asset(aid: int, k: str = Query("")):
        """Capability-authorised: the key is unguessable and per asset, so no
        session token has to travel in a URL that ends up in <video src>."""
        with db.connect() as con:
            r = con.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
        if not r or not k or not secrets.compare_digest(k, r["akey"]):
            raise HTTPException(404, "no such asset")
        path = config.DATA_DIR / r["path"]
        if not path.exists():
            raise HTTPException(410, "the file behind this asset is gone")
        return FileResponse(path, media_type=r["mime"] or "application/octet-stream",
                            filename=r["name"])

    @router.delete("/assets/{aid}")
    def delete_asset(aid: int, uid: int = Depends(current_user)):
        with db.connect() as con:
            r = con.execute("SELECT path FROM assets WHERE id=? AND user_id=?",
                            (aid, uid)).fetchone()
            if r:
                con.execute("DELETE FROM assets WHERE id=? AND user_id=?", (aid, uid))
        if r:
            _unlink(r["path"])
        return {"ok": True}

    app.include_router(router)


def _asset_public(row: dict) -> dict:
    out = _public(row)
    try:
        out["meta"] = json.loads(row.get("meta") or "{}")
    except json.JSONDecodeError:
        out["meta"] = {}
    # The URL carries the capability, so the client never needs the raw key.
    out["url"] = f"/api/studio/assets/{row['id']}/blob?k={row['akey']}"
    return out


def _unlink(rel_path: str) -> None:
    try:
        target = (config.DATA_DIR / rel_path).resolve()
        root = (config.DATA_DIR / "assets").resolve()
        if root in target.parents:          # never delete outside the store
            target.unlink(missing_ok=True)
    except OSError:
        pass


def purge_user(uid: int) -> None:
    """Remove a user's whole asset directory. Used by restore."""
    shutil.rmtree(config.DATA_DIR / "assets" / str(uid), ignore_errors=True)
