"""A window onto the database, for the times the UI doesn't have a screen.

Every business system eventually needs someone to look at a row directly —
a bad import, a stuck status, a column the forms don't expose. Doing that
over SSH with the sqlite3 CLI is how databases get wrecked at 11pm, so this
puts it behind the same login, the same permission check and the same audit
log as everything else.

Three deliberate limits, because a database editor is the most dangerous
screen in any admin tool:

  Secrets are never shown. Tokens, password and PIN hashes, webhook URLs and
  API keys are replaced with a marker on the way out and rejected on the way
  in. A viewer that can display a credential is a viewer that leaks it to
  whoever is standing behind you; one that can *write* a password hash is an
  account-takeover tool.

  Identity columns are read-only. You cannot edit a primary key, and you
  cannot grant yourself `is_admin` here — that check lives in the staff
  screen where it can be reasoned about, and routing around it through the
  table editor would make it decorative.

  Writes go one row at a time, by primary key, with the table and column
  names checked against the real schema rather than interpolated from user
  input. There is no free-text SQL box: the value of one is a query tool,
  and the cost is a DROP TABLE one paste away.
"""
import csv
import io
import json
import pathlib
import re
import sqlite3
import tempfile

from fastapi import HTTPException

from . import db

# Column names whose values never leave the server. Matched on the name
# rather than a fixed list so a new table with a `token` column is covered
# the day it's added, not the day someone remembers to update this.
SECRET_COL = re.compile(
    r"^(.*_)?(token|password|passwd|pw|pin|secret|webhook|api_key|apikey|"
    r"key|hash|signature|private)(_.*)?$", re.I)

# Never editable, whatever table they appear in.
LOCKED_COL = re.compile(r"^(id|created_at|is_admin|permissions)$", re.I)

# Tables that hold nothing but credentials or machine state; listing their
# contents has no legitimate use from this screen.
HIDDEN_TABLE = re.compile(
    r"^(sqlite_.*|.*_fts(_\w+)?|login_tokens|push_subscriptions)$", re.I)

REDACTED = "••• hidden"


def _tables(con) -> list:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows if not HIDDEN_TABLE.match(r["name"])]


def _check_table(con, table: str) -> str:
    """Resolve a table name against the real schema.

    The name is used in SQL that can't be parameterised, so it never reaches
    a query as anything other than one of these known-good strings.
    """
    for name in _tables(con):
        if name == table:
            return name
    raise HTTPException(404, f"no table called {table!r}")


def _columns(con, table: str) -> list:
    return [{"name": r["name"], "type": r["type"],
             "pk": bool(r["pk"]), "notnull": bool(r["notnull"]),
             "secret": bool(SECRET_COL.match(r["name"])),
             "locked": bool(LOCKED_COL.match(r["name"])
                            or SECRET_COL.match(r["name"]) or r["pk"])}
            for r in con.execute(f"PRAGMA table_info({table})").fetchall()]


def _pk(cols: list) -> str:
    for c in cols:
        if c["pk"]:
            return c["name"]
    raise HTTPException(
        400, "that table has no primary key, so a row can't be addressed "
             "safely — edit it through its own screen instead")


def overview(con) -> dict:
    out = []
    for t in _tables(con):
        try:
            n = con.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
        except Exception:
            n = 0
        out.append({"name": t, "rows": n})
    out.sort(key=lambda t: -t["rows"])
    return {"tables": out}


def rows(con, table: str, q: str = "", limit: int = 50,
         offset: int = 0) -> dict:
    table = _check_table(con, table)
    cols = _columns(con, table)
    names = [c["name"] for c in cols]

    where, args = "", []
    if q.strip():
        # Search every column as text. Column names come from the schema, so
        # only the search term is user input and it is bound, not spliced.
        clauses = " OR ".join(f"CAST({n} AS TEXT) LIKE ?" for n in names)
        where = f" WHERE {clauses}"
        args = [f"%{q.strip()}%"] * len(names)

    total = con.execute(f"SELECT COUNT(*) n FROM {table}{where}",
                        tuple(args)).fetchone()["n"]
    order = _pk(cols) if any(c["pk"] for c in cols) else names[0]
    limit = min(max(limit, 1), 200)
    data = con.execute(
        f"SELECT * FROM {table}{where} ORDER BY {order} DESC LIMIT ? OFFSET ?",
        tuple(args) + (limit, max(offset, 0))).fetchall()

    secret = {c["name"] for c in cols if c["secret"]}
    out = []
    for r in data:
        row = {}
        for k in r.keys():
            v = r[k]
            if k in secret and v not in (None, ""):
                row[k] = REDACTED
            elif isinstance(v, (bytes, bytearray)):
                row[k] = f"<{len(v)} bytes>"
            elif isinstance(v, str) and len(v) > 300:
                row[k] = v[:300] + "…"
            else:
                row[k] = v
        out.append(row)
    return {"table": table, "columns": cols, "rows": out, "total": total,
            "limit": limit, "offset": max(offset, 0)}


def update(con, table: str, row_id, values: dict) -> dict:
    table = _check_table(con, table)
    cols = _columns(con, table)
    pk = _pk(cols)
    by_name = {c["name"]: c for c in cols}

    sets, args = [], []
    for k, v in values.items():
        c = by_name.get(k)
        if c is None:
            raise HTTPException(400, f"{table} has no column {k!r}")
        if c["locked"]:
            raise HTTPException(
                400, f"{k} can't be edited here — identity, timestamps and "
                     "anything secret are deliberately read-only")
        if v == REDACTED:
            continue                    # unchanged redacted field; skip it
        sets.append(f"{k}=?")
        args.append(None if v == "" and not c["notnull"] else v)
    if not sets:
        raise HTTPException(400, "nothing to change")
    args.append(row_id)
    cur = con.execute(
        f"UPDATE {table} SET {', '.join(sets)} WHERE {pk}=?", tuple(args))
    con.commit()
    if not cur.rowcount:
        raise HTTPException(404, "no row with that id")
    return {"ok": True, "changed": len(sets)}


def delete(con, table: str, row_id) -> dict:
    table = _check_table(con, table)
    pk = _pk(_columns(con, table))
    cur = con.execute(f"DELETE FROM {table} WHERE {pk}=?", (row_id,))
    con.commit()
    if not cur.rowcount:
        raise HTTPException(404, "no row with that id")
    return {"ok": True}


# ---------- getting the data out ----------
#
# Every business system needs an exit. A database you can only read through
# someone else's screens is a database you don't own, and the moment that
# matters — an accountant wants the ledger, a new tool needs the customer
# list, the company is being sold — is never the moment to start writing an
# export.
#
# The same redaction applies as to the viewer. That is the point worth
# stating: an export is the easiest way to walk a table of password hashes
# out of the building, and a file is far more portable than a screen. So
# secret columns leave as the marker, not the value, and the whole-database
# dump is offered as a *backup* — restorable, but plainly labelled as
# containing everything, so nobody mails it to a contractor by accident.


def export_csv(con, table: str) -> str:
    """One table, as CSV, with secrets redacted the same way the viewer
    redacts them. Rows come out oldest-first: an export is usually read as a
    history, not as a screen."""
    table = _check_table(con, table)
    cols = _columns(con, table)
    names = [c["name"] for c in cols]
    secret = {c["name"] for c in cols if c["secret"]}

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(names)
    order = _pk(cols) if any(c["pk"] for c in cols) else names[0]
    for r in con.execute(f"SELECT * FROM {table} ORDER BY {order}"):
        row = []
        for k in names:
            v = r[k]
            if k in secret and v not in (None, ""):
                row.append(REDACTED)
            elif isinstance(v, (bytes, bytearray)):
                row.append(f"<{len(v)} bytes>")
            else:
                row.append("" if v is None else v)
        w.writerow(row)
    return out.getvalue()


def export_json(con, tables=None) -> str:
    """Several tables at once, for feeding another system. Same redaction."""
    names = list(tables) if tables else _tables(con)
    doc = {}
    for t in names:
        t = _check_table(con, t)
        cols = _columns(con, t)
        secret = {c["name"] for c in cols if c["secret"]}
        rows = []
        for r in con.execute(f"SELECT * FROM {t}"):
            row = {}
            for k in r.keys():
                v = r[k]
                if k in secret and v not in (None, ""):
                    row[k] = REDACTED
                elif isinstance(v, (bytes, bytearray)):
                    row[k] = f"<{len(v)} bytes>"
                else:
                    row[k] = v
            rows.append(row)
        doc[t] = rows
    return json.dumps(doc, indent=1, default=str)


def backup_bytes(con) -> bytes:
    """The whole database, as a file you could put back.

    Nothing is redacted here, and that is deliberate — a backup with the
    credentials stripped out is not a backup, it's a file that looks like one
    right up until you need it. It is a separate, clearly-labelled action for
    exactly that reason.

    Uses SQLite's own backup API into a real database file rather than
    copying bytes off disk: the live database runs in WAL mode, so the main
    file is only part of the story and copying it mid-write yields something
    subtly wrong. What comes back is a consistent .db anyone can open.
    """
    with tempfile.TemporaryDirectory() as tmp:
        dest = pathlib.Path(tmp) / "backup.db"
        out = sqlite3.connect(dest)
        try:
            con.backup(out)
        finally:
            out.close()
        return dest.read_bytes()
