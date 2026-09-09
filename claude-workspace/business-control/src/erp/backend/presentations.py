"""Presentations: made here, recorded here, or brought in — and shown.

A teacher's deck, a manager's "here is the new till", a recorded
walkthrough with the presenter's voice over their screen. Three kinds,
one shelf:

  * **deck** — slides written in the app: a title, lines, an image, and
    speaker notes each. Presented from a link on any screen with the
    arrow keys or a thumb; exported as a PDF (what a phone and the class
    stage show) or a PowerPoint (what somebody's laptop expects).
  * **recording** — the screen with the presenter's voice, the camera
    with their voice, or the voice alone, captured in the browser and
    saved as a film or a sound file. No software, no upload step.
  * **file** — a .pptx, a PDF, a film or a recording made elsewhere.

Every presentation has a link that needs no sign-in; who opened it is
counted the way a training's viewers are. A presentation attached to a
class becomes one of that class's materials, so it is on the course page
and in every session's Shared tab, and the teacher can put it on the
stage of a live class.

The PowerPoint writer is the minimum Open XML package that PowerPoint,
Keynote and LibreOffice all open: one master, one layout, a theme, and
one slide per slide with a title box, a body box and the picture.
"""
import io
import json
import secrets
import time
import zipfile
from xml.sax.saxutils import escape as _x

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from . import db

TABLES = """
CREATE TABLE IF NOT EXISTS presentations (
  id INTEGER PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  blurb TEXT DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'deck',      -- deck | recording | file
  slides TEXT DEFAULT '[]',               -- JSON [{title, lines, image, notes}]
  material_id INTEGER DEFAULT 0,          -- the film / file, for recording|file
  course_id INTEGER DEFAULT 0,            -- attached to a class, if any
  owner_id INTEGER DEFAULT 0,
  published INTEGER DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS presentation_views (
  presentation_id INTEGER NOT NULL,
  who TEXT NOT NULL,                      -- user:<id> or visitor:<vid>
  name TEXT DEFAULT '',
  first_at REAL NOT NULL,
  last_at REAL NOT NULL,
  views INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (presentation_id, who)
);
"""

KINDS = ("deck", "recording", "file")
MAX_SLIDES = 200


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


# ── slides ───────────────────────────────────────────────────────────────────

def clean_slides(raw) -> list:
    """The slide list as we keep it: bounded, typed, nothing else."""
    out = []
    for s in (raw or [])[:MAX_SLIDES]:
        if not isinstance(s, dict):
            continue
        lines = s.get("lines") or []
        if isinstance(lines, str):
            lines = [ln for ln in lines.splitlines()]
        out.append({
            "title": str(s.get("title") or "")[:200],
            "lines": [str(ln)[:400] for ln in lines][:30],
            "image": str(s.get("image") or "")[:200],
            "notes": str(s.get("notes") or "")[:4000],
        })
    return out


def slides_of(row) -> list:
    try:
        return clean_slides(json.loads(row["slides"] or "[]"))
    except ValueError:
        return []


# ── the PDF ──────────────────────────────────────────────────────────────────

def pdf_bytes(title: str, slides: list, *, notes: bool = False,
              image_bytes=None) -> bytes:
    """Landscape pages, one per slide, in the proportions of a screen.
    `image_bytes(path)` hands back a slide picture's bytes from wherever
    files live. With `notes`, the speaker's notes follow as pages of
    their own — a printout for the lectern."""
    from fpdf import FPDF
    pdf = FPDF(orientation="L", unit="mm", format=(160, 90))
    pdf.set_auto_page_break(False)
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_xy(10, 30)
    pdf.multi_cell(140, 12, _latin(title or "Presentation"), align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(10, 70)
    pdf.cell(140, 8, _latin(f"{len(slides)} slide{'s' if len(slides) != 1 else ''}"), align="C")
    for i, s in enumerate(slides, 1):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_xy(10, 8)
        pdf.multi_cell(140, 9, _latin(s["title"] or f"Slide {i}"))
        y = pdf.get_y() + 3
        img = None
        if s.get("image") and image_bytes:
            try:
                img = image_bytes(s["image"])
            except Exception:                                # noqa: BLE001
                img = None
        text_w = 140 if not img else 78
        pdf.set_font("Helvetica", "", 12)
        pdf.set_xy(10, y)
        for ln in s["lines"]:
            if pdf.get_y() > 78:
                break
            pdf.set_x(10)
            pdf.multi_cell(text_w, 6.5, _latin("- " + ln if ln.strip() else ""))
        if img:
            try:
                pdf.image(io.BytesIO(img), x=92, y=y, w=58)
            except Exception:                                # noqa: BLE001
                pass
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(10, 82)
        pdf.cell(140, 5, f"{i} / {len(slides)}", align="R")
    if notes and any(s.get("notes") for s in slides):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(10, 10)
        pdf.cell(140, 8, "Speaker notes")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_xy(10, 22)
        for i, s in enumerate(slides, 1):
            if not s.get("notes"):
                continue
            if pdf.get_y() > 75:
                pdf.add_page()
                pdf.set_xy(10, 10)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_x(10)
            pdf.multi_cell(140, 5, _latin(f"{i}. {s['title'] or ''}"))
            pdf.set_font("Helvetica", "", 10)
            pdf.set_x(10)
            pdf.multi_cell(140, 5, _latin(s["notes"]))
            pdf.ln(2)
    return bytes(pdf.output())


def _latin(s: str) -> str:
    """The core fonts know Latin-1; anything else becomes a close cousin
    or a question mark rather than a crash."""
    return (s or "").encode("latin-1", "replace").decode("latin-1")


# ── the PowerPoint ───────────────────────────────────────────────────────────

_CT = ("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Default Extension="gif" ContentType="image/gif"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
{slides}</Types>""")

_RELS_ROOT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')

_THEME = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Plain">
<a:themeElements>
<a:clrScheme name="Plain"><a:dk1><a:srgbClr val="16202B"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
<a:dk2><a:srgbClr val="1F2937"/></a:dk2><a:lt2><a:srgbClr val="F3F4F6"/></a:lt2>
<a:accent1><a:srgbClr val="4634D9"/></a:accent1><a:accent2><a:srgbClr val="0D8F7A"/></a:accent2>
<a:accent3><a:srgbClr val="F59E0B"/></a:accent3><a:accent4><a:srgbClr val="EF4444"/></a:accent4>
<a:accent5><a:srgbClr val="3B82F6"/></a:accent5><a:accent6><a:srgbClr val="8B5CF6"/></a:accent6>
<a:hlink><a:srgbClr val="4634D9"/></a:hlink><a:folHlink><a:srgbClr val="6B7280"/></a:folHlink></a:clrScheme>
<a:fontScheme name="Plain"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>
<a:fmtScheme name="Plain">
<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>
<a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="25400"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="38100"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>
<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>
</a:fmtScheme></a:themeElements></a:theme>"""

_MASTER = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster {_NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>
<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="3600"/></a:lvl1pPr></p:titleStyle>
<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2000"/></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles>
</p:sldMaster>"""

_MASTER_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

_LAYOUT = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout {_NS} type="blank" preserve="1"><p:cSld name="Blank">
<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"""

_LAYOUT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

# 16:9, in EMU
_W, _H = 12192000, 6858000


def _textbox(sid: int, name: str, x, y, w, h, paras: list, *, size: int,
             bold: bool = False) -> str:
    body = ""
    for text in paras:
        rpr = f'<a:rPr lang="en-US" sz="{size}"{" b=\"1\"" if bold else ""}/>'
        body += (f"<a:p><a:r>{rpr}<a:t>{_x(text)}</a:t></a:r></a:p>"
                 if text.strip() else "<a:p><a:endParaRPr lang=\"en-US\"/></a:p>")
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_x(name)}"/><p:cNvSpPr txBox="1"/>'
            f'<p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/>'
            f'<a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square" rtlCol="0">'
            f'<a:normAutofit/></a:bodyPr><a:lstStyle/>{body}</p:txBody></p:sp>')


def _picture(sid: int, rid: str, x, y, w, h) -> str:
    return (f'<p:pic><p:nvPicPr><p:cNvPr id="{sid}" name="Picture {sid}"/><p:cNvPicPr>'
            f'<a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
            f'</p:blipFill><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/>'
            f'</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')


def pptx_bytes(title: str, slides: list, *, image_bytes=None) -> bytes:
    """A .pptx: a title slide, then one slide per slide. Pictures ride
    along as media parts; the notes go in as the slide's notes would in
    spirit — a final 'Speaker notes' slide, since a notes part is the
    one piece of the package not worth its weight here."""
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    n = len(slides) + 1
    overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>\n'
        for i in range(1, n + 1))
    z.writestr("[Content_Types].xml", _CT.format(slides=overrides))
    z.writestr("_rels/.rels", _RELS_ROOT)
    sld_ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n + 1))
    z.writestr("ppt/presentation.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation {_NS} saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
<p:sldIdLst>{sld_ids}</p:sldIdLst><p:sldSz cx="{_W}" cy="{_H}"/><p:notesSz cx="6858000" cy="9144000"/>
<p:defaultTextStyle><a:defPPr><a:defRPr lang="en-US"/></a:defPPr></p:defaultTextStyle></p:presentation>""")
    pres_rels = ('<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
                 + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>' for i in range(1, n + 1))
                 + f'<Relationship Id="rId{n + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>')
    z.writestr("ppt/_rels/presentation.xml.rels",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + pres_rels + "</Relationships>")
    z.writestr("ppt/slideMasters/slideMaster1.xml", _MASTER)
    z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _MASTER_RELS)
    z.writestr("ppt/slideLayouts/slideLayout1.xml", _LAYOUT)
    z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _LAYOUT_RELS)
    z.writestr("ppt/theme/theme1.xml", _THEME)

    def slide_xml(shapes: str) -> str:
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sld {_NS}><p:cSld><p:spTree>'
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                f'{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')

    layout_rel = '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
    # the title slide
    shapes = _textbox(2, "Title", 914400, 2286000, _W - 1828800, 1600000,
                      [title or "Presentation"], size=4000, bold=True)
    shapes += _textbox(3, "Subtitle", 914400, 4000000, _W - 1828800, 700000,
                       [f"{len(slides)} slide{'s' if len(slides) != 1 else ''}"], size=1800)
    z.writestr("ppt/slides/slide1.xml", slide_xml(shapes))
    z.writestr("ppt/slides/_rels/slide1.xml.rels",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + layout_rel + "</Relationships>")
    media_n = 0
    for i, s in enumerate(slides, 2):
        rels = layout_rel
        shapes = _textbox(2, "Title", 685800, 457200, _W - 1371600, 1000000,
                          [s["title"] or f"Slide {i - 1}"], size=3200, bold=True)
        img = None
        if s.get("image") and image_bytes:
            try:
                img = image_bytes(s["image"])
            except Exception:                                # noqa: BLE001
                img = None
        body_w = (_W - 1371600) if not img else 6400000
        shapes += _textbox(3, "Body", 685800, 1600000, body_w, _H - 2200000,
                           [("• " + ln) if ln.strip() else "" for ln in s["lines"]], size=2000)
        if img:
            media_n += 1
            ext = ".png" if img[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg" if img[:3] == b"\xff\xd8\xff" else ".gif"
            z.writestr(f"ppt/media/image{media_n}{ext}", img)
            rels += (f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                     f'Target="../media/image{media_n}{ext}"/>')
            shapes += _picture(4, "rId2", 7400000, 1600000, 4300000, 3200000)
        z.writestr(f"ppt/slides/slide{i}.xml", slide_xml(shapes))
        z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + rels + "</Relationships>")
    z.close()
    return buf.getvalue()


# ── routes ───────────────────────────────────────────────────────────────────

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


def _staff(con, user) -> bool:
    from . import community as CM
    return bool(user["is_admin"] or CM.is_staff(con, user)
                or user["role"] in ("employee", "teacher", "director", "owner"))


def _require_staff(con, user) -> None:
    if not _staff(con, user):
        raise HTTPException(403, "staff make presentations")


def _get(con, pid: int):
    r = con.execute("SELECT * FROM presentations WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such presentation")
    return r


def _image_reader():
    from . import blobs
    return lambda rel: blobs.get(rel)


def shape(con, r) -> dict:
    from .main import base_url
    d = dict(r)
    d["slides"] = slides_of(r)
    d["url"] = f"{base_url()}/present/{r['token']}"
    d["viewers"] = con.execute(
        "SELECT COUNT(*) FROM presentation_views WHERE presentation_id=?",
        (r["id"],)).fetchone()[0]
    d["views"] = con.execute(
        "SELECT COALESCE(SUM(views),0) FROM presentation_views WHERE"
        " presentation_id=?", (r["id"],)).fetchone()[0]
    m = con.execute("SELECT id, kind, path, original, mime, bytes FROM"
                    " learning_materials WHERE id=?",
                    (r["material_id"],)).fetchone() if r["material_id"] else None
    d["material"] = dict(m) if m else None
    if m:
        d["material"]["url"] = f"/media/{m['path']}"
    c = con.execute("SELECT name FROM courses WHERE id=?",
                    (r["course_id"],)).fetchone() if r["course_id"] else None
    d["course"] = c["name"] if c else ""
    # the lessons it is on: a deck's PDF or a recording, as lesson material
    d["lessons"] = [dict(x) for x in con.execute(
        "SELECT l.id, l.title FROM learning_materials m JOIN lessons l"
        " ON l.id=m.lesson_id WHERE m.presentation_id=? ORDER BY l.position",
        (r["id"],))]
    return d


@router.get("/api/presentations")
def list_presentations(course_id: int = 0, user=Depends(current_user),
                       con=Depends(get_con)):
    _require_staff(con, user)
    rows = con.execute(
        "SELECT * FROM presentations" + (" WHERE course_id=?" if course_id else "")
        + " ORDER BY updated_at DESC", (course_id,) if course_id else ()).fetchall()
    courses = [dict(r) for r in con.execute(
        "SELECT id, name FROM courses WHERE active=1 ORDER BY name")]
    return {"presentations": [shape(con, r) for r in rows], "courses": courses,
            "kinds": list(KINDS)}


@router.get("/api/presentations/{pid}")
def get_presentation(pid: int, user=Depends(current_user), con=Depends(get_con)):
    _require_staff(con, user)
    return shape(con, _get(con, pid))


class PresentationBody(BaseModel):
    title: str = ""
    blurb: str = ""
    kind: str = "deck"
    slides: list | None = None
    course_id: int | None = None
    published: bool | None = None


@router.post("/api/presentations")
def create_presentation(body: PresentationBody, user=Depends(current_user),
                        con=Depends(get_con)):
    _require_staff(con, user)
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind is one of {KINDS}")
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "a presentation needs a title")
    now = time.time()
    cur = con.execute(
        "INSERT INTO presentations(token,title,blurb,kind,slides,material_id,"
        " course_id,owner_id,published,created_at,updated_at)"
        " VALUES(?,?,?,?,?,0,?,?,?,?,?)",
        (secrets.token_urlsafe(12), title[:200], body.blurb.strip()[:2000],
         body.kind, json.dumps(clean_slides(body.slides or [])),
         body.course_id or 0, user["id"],
         1 if body.published is None or body.published else 0, now, now))
    con.commit()
    return {"ok": True, **shape(con, _get(con, cur.lastrowid))}


@router.post("/api/presentations/{pid}")
def update_presentation(pid: int, body: PresentationBody,
                        user=Depends(current_user), con=Depends(get_con)):
    _require_staff(con, user)
    r = _get(con, pid)
    con.execute(
        "UPDATE presentations SET title=?, blurb=?, slides=?, course_id=?,"
        " published=?, updated_at=? WHERE id=?",
        (body.title.strip()[:200] or r["title"],
         r["blurb"] if body.blurb is None else body.blurb.strip()[:2000],
         json.dumps(clean_slides(body.slides)) if body.slides is not None else r["slides"],
         r["course_id"] if body.course_id is None else (body.course_id or 0),
         r["published"] if body.published is None else (1 if body.published else 0),
         time.time(), pid))
    con.commit()
    return {"ok": True, **shape(con, _get(con, pid))}


@router.delete("/api/presentations/{pid}")
def delete_presentation(pid: int, user=Depends(current_user),
                        con=Depends(get_con)):
    _require_staff(con, user)
    r = _get(con, pid)
    if r["owner_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "its maker or an admin removes it")
    from . import materials as MAT
    if r["material_id"]:
        try:
            MAT.delete_material(con, r["material_id"])
        except Exception:                                    # noqa: BLE001
            pass
    for s in slides_of(r):
        if s.get("image"):
            MAT.unlink(s["image"])
    con.execute("DELETE FROM presentations WHERE id=?", (pid,))
    con.execute("DELETE FROM presentation_views WHERE presentation_id=?", (pid,))
    con.commit()
    return {"ok": True}


@router.post("/api/presentations/{pid}/file")
async def upload_file(pid: int, request: Request, user=Depends(current_user),
                      con=Depends(get_con)):
    """The film, the sound, the deck, the PDF: raw bytes, one per
    presentation, replacing what was there. A recording made in the
    browser arrives the same way."""
    _require_staff(con, user)
    r = _get(con, pid)
    from . import materials as MAT
    data = await MAT.read_upload(request)
    name = request.headers.get("x-filename", "")
    saved = MAT.save(data, allow=("video", "audio", "document", "image"),
                     filename=name)
    mid = MAT.record(con, saved=saved, owner_id=user["id"], original=name,
                     course_id=r["course_id"] or None)
    if r["material_id"]:
        try:
            MAT.delete_material(con, r["material_id"])
        except Exception:                                    # noqa: BLE001
            pass
    kind = r["kind"] if r["kind"] != "deck" else "file"
    con.execute("UPDATE presentations SET material_id=?, kind=?, updated_at=?"
                " WHERE id=?", (mid, kind, time.time(), pid))
    con.commit()
    return {"ok": True, "material_id": mid, **saved}


@router.post("/api/presentations/{pid}/slides/{n}/image")
async def slide_image(pid: int, n: int, request: Request,
                      user=Depends(current_user), con=Depends(get_con)):
    _require_staff(con, user)
    r = _get(con, pid)
    slides = slides_of(r)
    if not 0 <= n < len(slides):
        raise HTTPException(404, "no such slide")
    from . import materials as MAT
    data = await MAT.read_upload(request)
    saved = MAT.save(data, allow=("image",))
    if slides[n].get("image"):
        MAT.unlink(slides[n]["image"])
    slides[n]["image"] = saved["path"]
    con.execute("UPDATE presentations SET slides=?, updated_at=? WHERE id=?",
                (json.dumps(slides), time.time(), pid))
    con.commit()
    return {"ok": True, "image": saved["path"], "url": f"/media/{saved['path']}"}


@router.get("/api/presentations/{pid}/export.pdf")
def export_pdf(pid: int, notes: int = 0, user=Depends(current_user),
               con=Depends(get_con)):
    _require_staff(con, user)
    r = _get(con, pid)
    blob = pdf_bytes(r["title"], slides_of(r), notes=bool(notes),
                     image_bytes=_image_reader())
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in r["title"])[:60]
    return Response(blob, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'})


@router.get("/api/presentations/{pid}/export.pptx")
def export_pptx(pid: int, user=Depends(current_user), con=Depends(get_con)):
    _require_staff(con, user)
    r = _get(con, pid)
    blob = pptx_bytes(r["title"], slides_of(r), image_bytes=_image_reader())
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in r["title"])[:60]
    return Response(
        blob, media_type="application/vnd.openxmlformats-officedocument"
                         ".presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pptx"'})


class AttachBody(BaseModel):
    course_id: int = 0
    lesson_id: int = 0


@router.post("/api/presentations/{pid}/attach")
def attach(pid: int, body: AttachBody, user=Depends(current_user),
           con=Depends(get_con)):
    """Make it part of a class's information: as a course material — on
    the course page, in every session's Shared tab, on the stage — or
    as material on one lesson, where it sits with that lesson's drills.
    A deck goes as its PDF (made now, so the lesson keeps what was
    presented); a recording or a file goes as itself. Attaching again
    moves it rather than doubling it."""
    _require_staff(con, user)
    r = _get(con, pid)
    course_id, lesson_id = body.course_id or 0, body.lesson_id or 0
    if lesson_id:
        les = con.execute("SELECT course_id FROM lessons WHERE id=?",
                          (lesson_id,)).fetchone()
        if les is None:
            raise HTTPException(404, "no such lesson")
        course_id = les["course_id"]
    if not course_id or not con.execute("SELECT 1 FROM courses WHERE id=?",
                                        (course_id,)).fetchone():
        raise HTTPException(404, "no such course")
    from . import materials as MAT
    # one place at a time: an earlier attachment of this deck's PDF goes
    old_pdf = [x["id"] for x in con.execute(
        "SELECT id FROM learning_materials WHERE presentation_id=?", (pid,))]
    if r["kind"] == "deck":
        blob = pdf_bytes(r["title"], slides_of(r), image_bytes=_image_reader())
        saved = MAT.save(blob, allow=("document",), filename=f"{r['title']}.pdf")
        mid = MAT.record(con, saved=saved, owner_id=user["id"],
                         original=f"{r['title']}.pdf",
                         course_id=None if lesson_id else course_id,
                         lesson_id=lesson_id or None)
        for oid in old_pdf:
            MAT.delete_material(con, oid)
    elif r["material_id"]:
        con.execute("UPDATE learning_materials SET course_id=?, lesson_id=?"
                    " WHERE id=?",
                    (None if lesson_id else course_id, lesson_id or None,
                     r["material_id"]))
        mid = r["material_id"]
    else:
        raise HTTPException(409, "nothing to attach yet — upload or record first")
    con.execute("UPDATE learning_materials SET presentation_id=? WHERE id=?",
                (pid, mid))
    con.execute("UPDATE presentations SET course_id=?, updated_at=? WHERE id=?",
                (course_id, time.time(), pid))
    con.commit()
    return {"ok": True, "material_id": mid, "course_id": course_id,
            "lesson_id": lesson_id}


@router.post("/api/presentations/{pid}/detach")
def detach(pid: int, user=Depends(current_user), con=Depends(get_con)):
    """Off the class and its lessons; the presentation and its link stay."""
    _require_staff(con, user)
    r = _get(con, pid)
    from . import materials as MAT
    for x in con.execute("SELECT id, kind FROM learning_materials WHERE"
                         " presentation_id=?", (pid,)).fetchall():
        if r["kind"] == "deck":
            MAT.delete_material(con, x["id"])          # the PDF was made for it
        else:
            con.execute("UPDATE learning_materials SET course_id=NULL,"
                        " lesson_id=NULL WHERE id=?", (x["id"],))
    con.execute("UPDATE presentations SET course_id=0, updated_at=? WHERE id=?",
                (time.time(), pid))
    con.commit()
    return {"ok": True}


# ── the player's door: seen ──────────────────────────────────────────────────

def mark_seen(con, token: str, who: str, name: str) -> dict:
    p = con.execute("SELECT id FROM presentations WHERE token=? AND published=1",
                    (token,)).fetchone()
    if p is None:
        raise HTTPException(404, "no such presentation")
    now = time.time()
    con.execute(
        "INSERT INTO presentation_views(presentation_id,who,name,first_at,last_at,"
        " views) VALUES(?,?,?,?,?,1) ON CONFLICT(presentation_id, who) DO UPDATE SET"
        " last_at=excluded.last_at, views=presentation_views.views+1,"
        " name=excluded.name", (p["id"], who, name, now, now))
    con.commit()
    return {"ok": True, "as": name or "a visitor"}
