"""Labels and ID cards: every QR the building needs, on one sheet.

The product already gives each student a card, each library item a
label and each member of staff a badge — one at a time, from three
different screens, each printed with the browser's print button. A term
starts with forty students and a shelf of new equipment, and somebody
opens forty pages. This is the sheet instead: pick a set, pick a layout
that matches the stock in the printer, and print, or save it as a page
to print later.

The codes are the ones the scanners already know. A student's card
carries their person code (the same one their own portal prints), an
item's label the code the lending desk scans, a badge the code the time
clock reads. Nothing is minted differently for the sheet, so a card from
the sheet and a card from the portal are the same card.

Layouts are named for the label stock they fit, in inches, because that
is how the box is labelled. The page is drawn at exact size and printed
with no margin; a printer that adds its own scaling is a printer setting,
and the screen says so.

Badges are printed only for staff who already have one. Issuing a badge
is a decision about who may clock in, made per person on Team & access;
a sheet that minted forty badges because forty names were ticked would
be making that decision by accident.
"""
from fastapi import APIRouter, Depends, HTTPException

from . import auth, identity

LAYOUTS = {
    "avery5160": {
        "label": "Address labels, 30 a sheet (Avery 5160)",
        "w": 2.625, "h": 1.0, "cols": 3, "rows": 10,
        "top": 0.5, "left": 0.1875, "gap_x": 0.125, "gap_y": 0.0,
        "qr": 0.85, "font": 9,
    },
    "avery5163": {
        "label": "Shipping labels, 10 a sheet (Avery 5163)",
        "w": 4.0, "h": 2.0, "cols": 2, "rows": 5,
        "top": 0.5, "left": 0.1875, "gap_x": 0.125, "gap_y": 0.0,
        "qr": 1.6, "font": 12,
    },
    "tag": {
        "label": "Equipment tags, 20 a sheet (2 x 1.25 in)",
        "w": 2.0, "h": 1.25, "cols": 4, "rows": 8,
        "top": 0.5, "left": 0.25, "gap_x": 0.0, "gap_y": 0.0,
        "qr": 1.0, "font": 9,
    },
    "idcard": {
        "label": "ID cards, 8 a sheet (CR80, 3.375 x 2.125 in)",
        "w": 3.375, "h": 2.125, "cols": 2, "rows": 4,
        "top": 0.5, "left": 0.625, "gap_x": 0.25, "gap_y": 0.25,
        "qr": 1.5, "font": 12, "card": True,
    },
    "badge": {
        "label": "Badges, 6 a sheet (4 x 3 in)",
        "w": 4.0, "h": 3.0, "cols": 2, "rows": 3,
        "top": 0.5, "left": 0.25, "gap_x": 0.0, "gap_y": 0.0,
        "qr": 2.0, "font": 14, "card": True,
    },
}

SETS = ("students", "items", "staff")


def _may(user) -> bool:
    return (auth.office(user, "customers", "settings", "content")
            or user["role"] in ("employee", "teacher", "director"))


def students(con, course_id: int = 0, ids: list | None = None) -> list:
    """Everyone with a student record or a seat in a course. A customer
    who only ever bought something is not a student and gets no card."""
    from .main import base_url
    where = ("SELECT DISTINCT u.id, u.name, u.email, u.photo FROM users u"
             " LEFT JOIN student_profiles sp ON sp.user_id=u.id"
             " LEFT JOIN enrollments e ON e.user_id=u.id AND e.until IS NULL"
             " WHERE u.active=1 AND u.erased_at IS NULL"
             " AND (sp.user_id IS NOT NULL OR e.id IS NOT NULL)")
    args: list = []
    if course_id:
        where += " AND e.course_id=?"
        args.append(course_id)
    if ids:
        where += " AND u.id IN (" + ",".join("?" * len(ids)) + ")"
        args.extend(ids)
    out = []
    base = base_url()
    for r in con.execute(where + " ORDER BY u.name COLLATE NOCASE", args).fetchall():
        uid = identity.ensure_uid(con, r["id"])
        courses = [c["name"] for c in con.execute(
            "SELECT c.name FROM enrollments e JOIN courses c ON c.id=e.course_id"
            " WHERE e.user_id=? AND e.until IS NULL ORDER BY c.name", (r["id"],))]
        out.append({"id": r["id"], "name": r["name"],
                    "line2": ", ".join(courses[:2]) + (" …" if len(courses) > 2 else ""),
                    "line3": f"Student #{r['id']}",
                    "photo": r["photo"] or "",
                    "payload": identity.payload_for(uid, base=base)})
    con.commit()
    return out


def items(con, kinds: list | None = None, ids: list | None = None) -> list:
    from . import library
    q = "SELECT * FROM library_items WHERE retired_at IS NULL"
    args: list = []
    if kinds:
        q += " AND kind IN (" + ",".join("?" * len(kinds)) + ")"
        args.extend(kinds)
    if ids:
        q += " AND id IN (" + ",".join("?" * len(ids)) + ")"
        args.extend(ids)
    out = []
    for r in con.execute(q + " ORDER BY kind, name COLLATE NOCASE", args).fetchall():
        uid = library.ensure_uid(con, r["id"])
        out.append({"id": r["id"], "name": r["name"], "line2": r["kind"],
                    "line3": f"Item #{r['id']}" + (
                        f" · {r['copies']} copies" if r["copies"] > 1 else ""),
                    "photo": "", "payload": library.ITEM_PREFIX + uid})
    con.commit()
    return out


def staff(con, ids: list | None = None) -> dict:
    q = ("SELECT id, name, job, clock_token, photo FROM users WHERE active=1"
         " AND erased_at IS NULL AND (is_admin=1 OR role IN"
         " ('employee','owner','teacher','volunteer','director','cashier'))")
    args: list = []
    if ids:
        q += " AND id IN (" + ",".join("?" * len(ids)) + ")"
        args.extend(ids)
    rows = con.execute(q + " ORDER BY name COLLATE NOCASE", args).fetchall()
    out, without = [], []
    for r in rows:
        if not r["clock_token"]:
            without.append(r["name"])
            continue
        out.append({"id": r["id"], "name": r["name"],
                    "line2": (r["job"] or "").replace("_", " "),
                    "line3": f"Staff #{r['id']}", "photo": r["photo"] or "",
                    "payload": "bc:clock:" + r["clock_token"]})
    return {"labels": out, "without_badge": without}


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


def _ints(s: str) -> list:
    return [int(x) for x in s.split(",") if x.strip().isdigit()]


@router.get("/api/labels")
def labels_page(kind: str = "students", course_id: int = 0, kinds: str = "",
                ids: str = "", user=Depends(current_user), con=Depends(get_con)):
    if not _may(user):
        raise HTTPException(403, "the label sheet is for the office and the "
                                 "teaching staff")
    if kind not in SETS:
        raise HTTPException(400, f"kind is one of {SETS}")
    from .main import CFG
    out = {"kind": kind, "brand": CFG.get("brand_name") or "",
           "layouts": [{"id": k, **v} for k, v in LAYOUTS.items()],
           "courses": [dict(r) for r in con.execute(
               "SELECT id, name FROM courses WHERE active=1 ORDER BY name")],
           "item_kinds": ["book", "material", "equipment"],
           "without_badge": []}
    wanted = _ints(ids)
    if kind == "students":
        out["labels"] = students(con, course_id, wanted)
    elif kind == "items":
        out["labels"] = items(con, [k for k in kinds.split(",") if k], wanted)
    else:
        s = staff(con, wanted)
        out["labels"] = s["labels"]
        out["without_badge"] = s["without_badge"]
    return out
