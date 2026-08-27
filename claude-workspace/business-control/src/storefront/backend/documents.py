"""Document vault and electronic signature.

Every business accumulates paper that matters: customer contracts, vendor
agreements, insurance certificates, employee handbooks, NDAs. It usually
lives in somebody's inbox until the day it's needed.

This gives it one home, keyed to whoever it concerns — customer, vendor,
partner or employee — with the two things that make a vault more than a
folder:

  Expiry tracking. An insurance certificate that lapsed four months ago is
  worse than no certificate, because you believed you had one. Documents can
  carry an expiry and surface before it hits.

  Signature requests. A counterparty gets a link, reads the document, signs,
  and both sides get a copy plus an audit trail.

## What the signature is, honestly

This implements a **simple electronic signature**: the signer's typed or
drawn mark, captured with their name, email, timestamp, IP, user agent, and a
SHA-256 of the exact bytes they were shown. That hash is what makes it
tamper-evident — change the file afterwards and it no longer matches the
certificate.

Under ESIGN (US) and eIDAS (EU/UK) that is a valid electronic signature and
is enforceable for ordinary commercial agreements. It is **not** an advanced
or qualified signature: there is no identity verification beyond control of
an email address, and no certificate authority.

For anything where the counterparty's identity must be proven — property,
regulated finance, some employment instruments in some jurisdictions — use a
provider that does verified identity. The `esign` provider slot below exists
for exactly that: point it at DocuSign or Dropbox Sign and requests route
there instead, with the vault still holding the record.
"""
import hashlib
import json
import re
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from erp.backend import auth, config, mailer
from . import sections as sect
from .api import admin_user, get_con, rate_limit

router = APIRouter()

DOC_DIR = config.DATA_DIR / "uploads" / "documents"

TABLES = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT DEFAULT 'contract',        -- see CATEGORIES
  party_kind TEXT DEFAULT 'internal',      -- customer|vendor|partner|employee|internal
  party_name TEXT DEFAULT '',
  party_email TEXT DEFAULT '',
  party_user_id INTEGER DEFAULT 0,         -- linked account, when there is one
  filename TEXT DEFAULT '',
  ext TEXT DEFAULT '',
  bytes INTEGER DEFAULT 0,
  sha256 TEXT DEFAULT '',                  -- of the stored file
  body TEXT DEFAULT '',                    -- for documents authored here
  notes TEXT DEFAULT '',
  effective REAL DEFAULT 0,
  expires REAL DEFAULT 0,                  -- 0 = never
  status TEXT DEFAULT 'active',            -- draft|active|expired|superseded|archived
  supersedes INTEGER DEFAULT 0,
  confidential INTEGER DEFAULT 1,
  uploaded_by INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS documents_party ON documents(party_kind, party_name);
CREATE INDEX IF NOT EXISTS documents_expiry ON documents(expires);

CREATE TABLE IF NOT EXISTS document_signatures (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL,
  token TEXT UNIQUE NOT NULL,              -- the signing link
  signer_name TEXT NOT NULL,               -- who we asked
  signer_email TEXT NOT NULL,
  role TEXT DEFAULT 'signer',              -- signer|approver|witness
  status TEXT DEFAULT 'sent',              -- sent|viewed|signed|declined|void
  provider TEXT DEFAULT 'builtin',         -- builtin|docusign|...
  provider_ref TEXT DEFAULT '',
  -- what we captured at the moment of signing
  typed_name TEXT DEFAULT '',
  signature_data TEXT DEFAULT '',          -- data: URL of the drawn mark
  doc_sha256 TEXT DEFAULT '',              -- hash of what they were shown
  ip TEXT DEFAULT '',
  user_agent TEXT DEFAULT '',
  sent_at REAL NOT NULL,
  viewed_at REAL DEFAULT 0,
  signed_at REAL DEFAULT 0,
  decline_reason TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS document_signatures_doc
  ON document_signatures(document_id);

-- Every read and write, because a vault whose access isn't logged is just a
-- folder with extra steps.
CREATE TABLE IF NOT EXISTS document_events (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL,
  actor TEXT DEFAULT '',
  action TEXT NOT NULL,
  detail TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS document_events_doc ON document_events(document_id);
"""

CATEGORIES = {
    "contract": "Contract or agreement",
    "proposal": "Proposal or quote",
    "nda": "NDA / confidentiality",
    "policy": "Policy or handbook",
    "insurance": "Insurance certificate",
    "licence": "Licence or permit",
    "compliance": "Compliance or audit",
    "invoice": "Invoice or statement",
    "hr": "HR / employment record",
    "identity": "Identity or right-to-work",
    "other": "Other",
}

PARTY_KINDS = {
    "customer": "Customer",
    "vendor": "Vendor or supplier",
    "partner": "Partner or distributor",
    "employee": "Employee or contractor",
    "internal": "Internal — no counterparty",
}

# Categories that normally carry an expiry. Used to nudge, not to enforce.
EXPIRY_EXPECTED = ("insurance", "licence", "compliance", "identity", "contract")

ALLOWED_EXT = {
    "pdf": "application/pdf",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain", "csv": "text/csv", "md": "text/markdown",
}
MAX_BYTES = 25 * 1024 * 1024


# ---------- the fillable parts of a document ----------
# Three kinds of blank, all of them the kit's own affordances:
#   [TOKENS]        one value per name, filled everywhere it appears
#   ______ runs     write-in lines — a sentence, a paragraph, a number
#   - [ ] and ☐     checkboxes, toggled
# One scanner feeds the editor, the renderer and the save, so a document
# can never be scanned two ways.

# A blank, filled or not: [CLIENT NAME] before, [CLIENT NAME=Acme] after.
# Filling used to erase the name along with the blank, which left a filled
# value indistinguishable from the document's own prose — you could not see
# that it was a field, and you could not change it again. Keeping the name
# costs one "=" and buys both.
PLACEHOLDER = re.compile(
    r"\[([^\[\]\n(){}`=]{1,60})(?:=([^\[\]\n]{0,200}))?\]")


def token_value(m):
    """(name, value or None) for a placeholder match."""
    return m.group(1), m.group(2)

# Signing markers are instructions to the renderer and to DocuSign, not
# blanks for anyone to fill — the fill machinery must leave them standing.
RESERVED_MARKERS = {"SIGN HERE", "INITIALS", "PAGE BREAK"}

# Facts that belong to the client, not to a document. A binder full of
# forms all naming the same company should name it once: these tokens read
# from the engagement record wherever they appear, so the client cannot say
# one thing on the cover and another three forms later.
GLOBAL_TOKENS = {
    "CLIENT": "client", "CLIENT NAME": "client",
    "PROJECT": "client", "PROJECT NAME": "client",
    "CLIENT POC": "client_poc", "APPROVER": "client_poc",
    "INTERNAL POC": "internal_poc",
    "ORIGINATOR": "originator",
    "DATE": "date",
    "BRAND": "brand", "PACKAGE": "package", "VALUE": "value",
}


def substitute_globals(text: str, values: dict) -> str:
    """Render-time only: the token stays in the source, so the day the
    record changes every document changes with it."""
    if not values:
        return text
    out, last = [], 0
    for m in PLACEHOLDER.finditer(text):
        key = GLOBAL_TOKENS.get(m.group(1).strip())
        val = (values or {}).get(key or "", "")
        if key and str(val).strip():
            out.append(text[last:m.start()])
            out.append(str(val).strip())
            last = m.end()
    out.append(text[last:])
    return "".join(out)


def _matches(text: str):
    for m in PLACEHOLDER.finditer(text):
        if text[m.end():m.end() + 1] == "(":     # [label](link) — not a blank
            continue
        if m.group(1).strip() in ("", "x", "✓"):  # checkbox, not a blank
            continue
        if m.group(1).strip() in RESERVED_MARKERS:
            continue
        yield m


def placeholders(text: str) -> list:
    """The blanks still to fill — a blank that has an answer is not one."""
    seen, out = set(), []
    for m in _matches(text):
        tok, val = token_value(m)
        if val is None and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def clean_value(v) -> str:
    return str(v).strip().replace("[", "(").replace("]", ")").replace(
        "\n", " ")[:200]


def fill(text: str, fills: dict) -> str:
    """Answer each named blank everywhere it appears, keeping the name
    beside the answer so it stays a field: visible as one when reading, and
    changeable again later."""
    out, last = [], 0
    for m in _matches(text):
        tok, _ = token_value(m)
        val = clean_value((fills or {}).get(tok, ""))
        if val:
            out.append(text[last:m.start()])
            out.append(f"[{tok}={val}]")
            last = m.end()
    out.append(text[last:])
    return "".join(out)


_UNDERS = re.compile(r"_{3,}")
_CHECKBOX = re.compile(r"(?<=[-*] )\[( |x)\]")
_BOXCHAR = re.compile(r"[☐☑]")
_TABLE_LINE = re.compile(r"^\|.*\|[ \t]*$", re.M)
_TABLE_SEP = re.compile(r"\|(?:\s*:?-{2,}:?\s*\|)+\s*")


def scan_regions(text: str) -> list:
    """The write-in lines and checkboxes, in source order. Deterministic on
    the source text: the editor numbers them, the save endpoint re-scans and
    applies by number, and both see the same regions or neither does."""
    out = []
    for m in _UNDERS.finditer(text):
        ls = text.rfind("\n", 0, m.start()) + 1
        le = text.find("\n", m.end())
        le = len(text) if le == -1 else le
        out.append({"kind": "area" if text[ls:le].strip() == m.group(0)
                    else "line",
                    "start": m.start(), "end": m.end(),
                    "money": text[:m.start()].rstrip()[-1:] == "$"})
    for m in _CHECKBOX.finditer(text):
        out.append({"kind": "check", "start": m.start(), "end": m.end(),
                    "checked": m.group(1) == "x", "box": False})
    for m in _BOXCHAR.finditer(text):
        out.append({"kind": "check", "start": m.start(), "end": m.end(),
                    "checked": text[m.start()] == "☑", "box": True})
    # An empty table cell is a blank the template meant to be filled — the
    # audit grids, the roles table, the wet-ink signature rows. Whitespace
    # nobody can type into is a form with holes in it.
    for lm in _TABLE_LINE.finditer(text):
        line = lm.group(0)
        if _TABLE_SEP.fullmatch(line.strip()):
            continue
        # a header row's empty cells are layout, not blanks — the kit's
        # key-facts tables open with "| | |" on purpose
        nxt_start = lm.end() + 1
        nxt_end = text.find("\n", nxt_start)
        nxt = text[nxt_start:nxt_end if nxt_end != -1 else len(text)]
        if _TABLE_SEP.fullmatch(nxt.strip()):
            continue
        base = lm.start()
        pipes = [i for i, ch in enumerate(line) if ch == "|"]
        for a, b in zip(pipes, pipes[1:]):
            if b - a > 1 and line[a + 1:b].strip() == "":
                out.append({"kind": "cell", "start": base + a + 1,
                            "end": base + b})
    out.sort(key=lambda r: r["start"])
    return out


def apply_regions(text: str, edits: dict) -> str:
    """Apply {index: value} to the scanned regions, from the end backwards
    so earlier offsets stay true. A filled write-in line replaces its
    underscores and stops being a region — answered is answered."""
    regions = scan_regions(text)
    for i in sorted((int(k) for k in (edits or {})), reverse=True):
        if not 0 <= i < len(regions):
            continue
        r = regions[i]
        v = str(edits[str(i)] if str(i) in edits else edits[i])
        if r["kind"] in ("line", "area"):
            v = v.strip()
            if not v:
                continue
            text = text[:r["start"]] + v + text[r["end"]:]
        elif r["kind"] == "cell":
            v = v.strip().replace("|", "/").replace("\n", " ")
            if not v:
                continue
            text = text[:r["start"]] + f" {v} " + text[r["end"]:]
        else:
            on = v in ("true", "1", "on", "x")
            rep = ("☑" if on else "☐") if r["box"] else \
                ("[x]" if on else "[ ]")
            text = text[:r["start"]] + rep + text[r["end"]:]
    return text


# ---------- markdown, just enough ----------
# Documents generated from the studio kit are markdown: headings, tables,
# lists, bold. Rendering them as flat paragraphs turned a contract's terms
# table into soup — and a signature attests to what the signer was SHOWN, so
# the shown thing has to carry the document's actual structure. A subset is
# deliberate: escape first, then recognise only what the kit uses.

_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|/[^)\s]*)\)")


# Per-section signing markers. Written in a template as [SIGN HERE] or
# [INITIALS], they render as labelled lines — and because DocuSign anchors
# on the PDF's text, every occurrence of the label becomes a tab: initials
# on clause 7, a signature on the last page, however many the document
# carries. The fill machinery skips them; they are not blanks.
SIGN_MARKERS = {
    "[SIGN HERE]": ("Sign here:", "sign"),
    "[INITIALS]": ("Initials:", "initial"),
}


_FILLED = re.compile(r"\[([^\[\]\n=]{1,60})=([^\[\]\n]{0,200})\]")


def _mark_inline_html(t: str) -> str:
    t = _FILLED.sub(lambda m: m.group(2), t)
    for raw, (label, _kind) in SIGN_MARKERS.items():
        t = t.replace(sect.esc(raw),
                      f'<span style="white-space:nowrap"><b>{label}</b> '
                      f'<span style="display:inline-block;min-width:150px;'
                      f'border-bottom:1px solid #8b8496">&nbsp;</span></span>')
    return t


def _md_inline(text: str) -> str:
    t = sect.esc(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", t)
    t = _MD_LINK.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    # A relative link points at a kit file that isn't shipped with the
    # document — render the words, drop the dead target.
    t = re.sub(r"\[([^\]]+)\]\([#\w./-]+\)", r"\1", t)
    return _mark_inline_html(t)


def _md_row(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def md_blocks(text: str) -> list:
    """Parse the subset into blocks — one parser feeding both renderers, so
    the HTML a signer is shown and the PDF a client files can never carry
    different readings of the same document.

    Blocks: ("h", depth, text) · ("hr",) · ("table", head, rows) ·
    ("list", ordered, items) · ("quote", text) · ("p", text)
    """
    out, para, lines = [], [], text.splitlines()

    def flush():
        if para:
            out.append(("p", " ".join(para)))
            para.clear()

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            flush(); i += 1; continue
        if re.match(r"^#{1,4} ", stripped):
            flush()
            depth = len(stripped) - len(stripped.lstrip("#"))
            out.append(("h", depth, stripped.lstrip("#").strip()))
            i += 1; continue
        if re.fullmatch(r"_{3,}", stripped):
            # a run of underscores on its own line is the kit's write-in
            # answer line — rendering it as a separator was why the
            # questionnaires looked like they had nowhere to answer
            flush(); out.append(("aline",)); i += 1; continue
        if stripped == "[PAGE BREAK]":
            flush(); out.append(("pagebreak",)); i += 1; continue
        if re.fullmatch(r"[-*]{3,}", stripped):
            flush(); out.append(("hr",)); i += 1; continue
        if (stripped.startswith("|") and i + 1 < len(lines)
                and re.fullmatch(r"\|[\s:|-]+\|?",
                                 lines[i + 1].strip())):
            flush()
            head = _md_row(stripped)
            rows, i = [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_md_row(lines[i])); i += 1
            out.append(("table", head, rows))
            continue
        if stripped.startswith(("- ", "* ")) or re.match(r"^\d+\. ", stripped):
            flush()
            ordered = bool(re.match(r"^\d+\. ", stripped))
            items = []
            while i < len(lines):
                st = lines[i].strip()
                if st.startswith(("- ", "* ")):
                    items.append(st[2:])
                elif re.match(r"^\d+\. ", st):
                    items.append(re.sub(r"^\d+\. ", "", st))
                elif st and not st.startswith(("#", "|", ">")):
                    # a wrapped continuation line belongs to the last item
                    items[-1] += " " + st
                else:
                    break
                i += 1
            out.append(("list", ordered, items))
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip()); i += 1
            out.append(("quote", " ".join(quote)))
            continue
        para.append(stripped); i += 1
    flush()
    return out


def md_html(text: str) -> str:
    out = []
    for b in md_blocks(text):
        kind = b[0]
        if kind == "h":
            # the page already has an h1 (the document title), so shift down
            lvl = min(b[1] + 1, 5)
            out.append(f"<h{lvl}>{_md_inline(b[2])}</h{lvl}>")
        elif kind == "hr":
            out.append("<hr>")
        elif kind == "pagebreak":
            out.append('<div class="pgbreak"></div>')
        elif kind == "aline":
            out.append('<div style="border-bottom:1px solid #8b8496;'
                       'height:26px;margin:10px 0 14px"></div>')
        elif kind == "table":
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{_md_inline(h)}</th>" for h in b[1])
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(
                           f"<td>{_md_inline(c)}</td>" for c in r) + "</tr>"
                           for r in b[2])
                       + "</tbody></table>")
        elif kind == "list":
            tag = "ol" if b[1] else "ul"
            out.append(f"<{tag}>" + "".join(
                f"<li>{_md_inline(x)}</li>" for x in b[2]) + f"</{tag}>")
        elif kind == "quote":
            out.append(f"<blockquote>{_md_inline(b[1])}</blockquote>")
        else:
            out.append(f"<p>{_md_inline(b[1])}</p>")
    return "".join(out)


def init_tables(con):
    con.executescript(TABLES)
    DOC_DIR.mkdir(parents=True, exist_ok=True)


def log(con, doc_id: int, actor: str, action: str, detail: str = "") -> None:
    con.execute(
        "INSERT INTO document_events(document_id,actor,action,detail,"
        " created_at) VALUES(?,?,?,?,?)",
        (doc_id, actor[:80], action[:60], detail[:300], time.time()))


def doc_path(d) -> Path:
    return DOC_DIR / f"{d['id']}.{d['ext']}"


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_json(con, d, with_sigs=True) -> dict:
    out = dict(d)
    out["category_label"] = CATEGORIES.get(d["category"], d["category"])
    out["party_label"] = PARTY_KINDS.get(d["party_kind"], d["party_kind"])
    now = time.time()
    out["expired"] = bool(d["expires"] and d["expires"] < now)
    out["expiring_soon"] = bool(
        d["expires"] and now < d["expires"] < now + 45 * 86400)
    out["has_file"] = bool(d["ext"])
    if with_sigs:
        sigs = con.execute(
            "SELECT id, signer_name, signer_email, role, status, sent_at,"
            " viewed_at, signed_at, provider FROM document_signatures"
            " WHERE document_id=? ORDER BY id", (d["id"],)).fetchall()
        out["signatures"] = [dict(s) for s in sigs]
        out["fully_signed"] = bool(sigs) and all(
            s["status"] == "signed" for s in sigs)
        out["awaiting"] = sum(1 for s in sigs if s["status"] in ("sent", "viewed"))
    return out


# ---------- admin: the vault ----------

@router.get("/api/store/admin/documents")
def list_documents(party_kind: str = "", category: str = "", q: str = "",
                   u=Depends(admin_user), con=Depends(get_con)):
    sql = "SELECT * FROM documents WHERE status != 'archived'"
    args: list = []
    if party_kind in PARTY_KINDS:
        sql += " AND party_kind=?"
        args.append(party_kind)
    if category in CATEGORIES:
        sql += " AND category=?"
        args.append(category)
    if q.strip():
        sql += " AND (title LIKE ? OR party_name LIKE ? OR notes LIKE ?)"
        like = f"%{q.strip()}%"
        args += [like, like, like]
    sql += " ORDER BY created_at DESC LIMIT 300"
    rows = con.execute(sql, tuple(args)).fetchall()
    now = time.time()
    expiring = con.execute(
        "SELECT * FROM documents WHERE expires > 0 AND expires < ?"
        " AND status='active' ORDER BY expires", (now + 45 * 86400,)).fetchall()
    return {
        "documents": [doc_json(con, r) for r in rows],
        "expiring": [doc_json(con, r, with_sigs=False) for r in expiring],
        "categories": CATEGORIES, "party_kinds": PARTY_KINDS,
        "expiry_expected": list(EXPIRY_EXPECTED),
    }


class DocBody(BaseModel):
    title: str
    category: str = "contract"
    party_kind: str = "internal"
    party_name: str = ""
    party_email: str = ""
    body: str = ""
    notes: str = ""
    effective: float = 0
    expires: float = 0
    confidential: bool = True


@router.post("/api/store/admin/documents")
def add_document(body: DocBody, u=Depends(admin_user), con=Depends(get_con)):
    if not body.title.strip():
        raise HTTPException(400, "a document needs a title")
    if body.category not in CATEGORIES:
        raise HTTPException(400, "unknown category")
    if body.party_kind not in PARTY_KINDS:
        raise HTTPException(400, "unknown party kind")
    email = body.party_email.strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "that email doesn't look right")
    # Link to an existing account where the email matches, so a document filed
    # against a customer shows up beside their orders.
    linked = 0
    if email:
        row = con.execute("SELECT id FROM users WHERE email=? LIMIT 1",
                          (email,)).fetchone()
        linked = row["id"] if row else 0
    cur = con.execute(
        "INSERT INTO documents(title,category,party_kind,party_name,"
        " party_email,party_user_id,body,notes,effective,expires,"
        " confidential,uploaded_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.title.strip()[:200], body.category, body.party_kind,
         body.party_name.strip()[:120], email, linked, body.body,
         body.notes.strip()[:1000], body.effective, body.expires,
         1 if body.confidential else 0, u["id"], time.time()))
    log(con, cur.lastrowid, u["name"], "created", body.title.strip()[:120])
    con.commit()
    return {"id": cur.lastrowid}


@router.post("/api/store/admin/documents/{did}/file")
async def upload_file(did: int, file: UploadFile, u=Depends(admin_user),
                      con=Depends(get_con)):
    d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such document")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            400, f"file type not allowed — accepted: {', '.join(ALLOWED_EXT)}")
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(400, f"file is over {MAX_BYTES // 1024 // 1024}MB")
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOC_DIR / f"{did}.{ext}"
    dest.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    con.execute(
        "UPDATE documents SET filename=?, ext=?, bytes=?, sha256=? WHERE id=?",
        ((file.filename or "")[:200], ext, len(raw), digest, did))
    log(con, did, u["name"], "uploaded",
        f"{file.filename} ({len(raw)} bytes) sha256={digest[:16]}…")
    con.commit()
    return {"ok": True, "sha256": digest, "bytes": len(raw)}


@router.get("/api/store/admin/documents/{did}/file")
def download_file(did: int, u=Depends(admin_user), con=Depends(get_con)):
    d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if d is None or not d["ext"]:
        raise HTTPException(404, "no file on that document")
    p = doc_path(d)
    if not p.exists():
        raise HTTPException(404, "file missing from storage")
    log(con, did, u["name"], "downloaded")
    con.commit()
    return FileResponse(p, media_type=ALLOWED_EXT.get(d["ext"],
                        "application/octet-stream"),
                        filename=d["filename"] or f"document-{did}.{d['ext']}")


@router.get("/api/store/admin/documents/{did}/preview")
def preview_document(did: int, u=Depends(admin_user), con=Depends(get_con)):
    """The document as a reader sees it — the sign page's own renderer, so
    what you check here is exactly what a signer will be shown. Print this
    page to get a PDF; the browser's print dialog is the converter every
    machine already has."""
    d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such document")
    if not (d["body"] or "").strip():
        raise HTTPException(400, "this document is a file — download it "
                                 "instead")
    gv = {}
    row = con.execute("SELECT engagement_id FROM engagement_docs"
                      " WHERE doc_id=?", (did,)).fetchone()
    if row:
        from . import engagements as eng
        e = con.execute("SELECT * FROM engagements WHERE id=?",
                        (row["engagement_id"],)).fetchone()
        if e:
            gv = eng.global_values(e)
    from .api import FONT_LINK
    return HTMLResponse(
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,"
        f" initial-scale=1\"><title>{sect.esc(d['title'])}</title>"
        f"{FONT_LINK}<style>{DOC_BASE_CSS}"
        f"@media print{{body{{padding:0}}}}"
        f"html{{background:#fff}}{PAGE_RULE_CSS}"
        f"</style></head><body>"
        f"{form_inner(d['title'], d['body'], gv)}"
        f"{signatures_html(signed_rows(con, did))}"
        f"{pending_html(pending_rows(con, did))}</body></html>")


def signed_rows(con, doc_id: int) -> list:
    """The completed signatures, shaped for the PDF's signature block."""
    return [dict(r) for r in con.execute(
        "SELECT signer_name, signer_email, role, status, signed_at,"
        " typed_name, signature_data, token, doc_sha256, provider"
        " FROM document_signatures WHERE document_id=? AND status='signed'"
        " ORDER BY signed_at", (doc_id,)).fetchall()]


def signatures_html(sigs: list) -> str:
    """The signature block, for every HTML surface a document renders on —
    the preview, the portal, the signed page. The same facts the PDF prints,
    so no surface shows a signed document looking unsigned."""
    if not sigs:
        return ""
    rows = []
    for s in sigs:
        drawn = (s.get("signature_data") or "")
        mark = (f'<img src="{drawn}" alt="signature" style="max-width:220px;'
                f'display:block">' if drawn.startswith("data:image/png;base64,")
                else f'<div style="font-style:italic;font-size:22px">'
                     f'{sect.esc(s.get("typed_name") or s.get("signer_name"))}'
                     f'</div>')
        when = s.get("signed_at") or 0
        line = f'{sect.esc(s.get("signer_email", ""))} · '                f'{sect.esc(s.get("role", "signer"))}'
        if when:
            line += " · signed " + time.strftime(
                "%d %b %Y %H:%M UTC", time.gmtime(when))
        if s.get("provider") and s.get("provider") != "builtin":
            line += f' · via {sect.esc(s["provider"])}'
        ref = sect.esc((s.get("token") or "")[:12])
        sha = sect.esc((s.get("doc_sha256") or "")[:16])
        rows.append(
            f'<div style="margin:14px 0">{mark}'
            f'<b>{sect.esc(s.get("signer_name", ""))}</b><br>'
            f'<span style="color:#5d5768;font-size:13px">{line}</span>'
            + (f'<br><span style="color:#8b8496;font-size:12px">reference '
               f'{ref}' + (f' · document sha256 {sha}…' if sha else "")
               + "</span>" if ref or sha else "") + "</div>")
    return ('<hr style="margin:28px 0;border:0;border-top:1px solid #e9e4dc">'
            '<h3 style="font-family:\'Fraunces\',Georgia,serif">Signed</h3>'
            + "".join(rows))


def pending_rows(con, doc_id: int) -> list:
    """Requests still out — the blank lines on a printed copy."""
    return [dict(r) for r in con.execute(
        "SELECT signer_name, signer_email, role FROM document_signatures"
        " WHERE document_id=? AND status IN ('sent','viewed')"
        " ORDER BY sent_at", (doc_id,)).fetchall()]


def pending_html(pending: list) -> str:
    """The same blank areas, on every HTML surface — so a preview prints as
    the form the PDF is."""
    if not pending:
        return ""
    rows = "".join(
        f'<div style="margin:26px 0 10px;display:flex;gap:26px">'
        f'<div style="flex:1"><div style="border-bottom:1px solid #1b181f;'
        f'height:34px"></div><b style="font-size:13px">'
        f'{sect.esc(p.get("signer_name") or "Signature")}</b><br>'
        f'<span style="color:#5d5768;font-size:12px">'
        f'{sect.esc(p.get("signer_email", ""))} · '
        f'{sect.esc(p.get("role", "signer"))}</span></div>'
        f'<div style="width:160px"><div style="border-bottom:1px solid '
        f'#1b181f;height:34px"></div><b style="font-size:13px">Date</b>'
        f'</div></div>'
        for p in pending)
    return ('<hr style="margin:28px 0;border:0;border-top:1px solid #e9e4dc">'
            '<h3 style="font-family:\'Fraunces\',Georgia,serif">Signatures'
            '</h3><p style="color:#5d5768;font-size:13px">Awaiting signature '
            '— sign electronically from the emailed link, or print this, '
            'sign, and return a scan.</p>' + rows)


def _pdf_response(d, inline: bool = True, sigs: list | None = None,
                  pending: list | None = None):
    """A PDF for any document that can produce one: authored bodies are
    rendered — completed signatures printed on them — and an uploaded PDF
    is itself. Inline by default so the browser's own viewer is the
    preview."""
    from . import pdfgen
    stem = re.sub(r"[^\w.-]+", "-", d["title"]).strip("-")[:80] or "document"
    if (d["body"] or "").strip():
        blob = pdfgen.doc_pdf(d["title"], d["body"], signatures=sigs,
                              pending=pending)
    elif d["ext"] == "pdf":
        p = doc_path(d)
        if not p.exists():
            raise HTTPException(404, "file missing from storage")
        blob = p.read_bytes()
    else:
        raise HTTPException(400, f"this document is a .{d['ext'] or '?'} "
                                 "file — download it as itself")
    disp = "inline" if inline else "attachment"
    return Response(blob, media_type="application/pdf", headers={
        "Content-Disposition": f'{disp}; filename="{stem}.pdf"'})


@router.get("/api/store/admin/documents/{did}/pdf")
def document_pdf(did: int, download: int = 0, u=Depends(admin_user),
                 con=Depends(get_con)):
    d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such document")
    if download:
        log(con, did, u["name"], "downloaded")
        con.commit()
    return _pdf_response(d, inline=not download,
                         sigs=signed_rows(con, did),
                         pending=pending_rows(con, did))


@router.get("/sign/{token}/pdf")
def signing_pdf(token: str, con=Depends(get_con), _rl=Depends(rate_limit)):
    """The signer's own copy — the same parse as the page they signed."""
    s2 = _sig_or_404(con, token)
    d = con.execute("SELECT * FROM documents WHERE id=?",
                    (s2["document_id"],)).fetchone()
    if d is None:
        raise HTTPException(404, "document not found")
    return _pdf_response(d, inline=False,
                         sigs=signed_rows(con, d["id"]),
                         pending=pending_rows(con, d["id"]))


@router.get("/api/store/admin/documents/{did}/markdown")
def download_markdown(did: int, u=Depends(admin_user), con=Depends(get_con)):
    d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if d is None or not (d["body"] or "").strip():
        raise HTTPException(404, "no authored body on that document")
    log(con, did, u["name"], "downloaded")
    con.commit()
    stem = re.sub(r"[^\w.-]+", "-", d["title"]).strip("-")[:80] or "document"
    return Response(d["body"], media_type="text/markdown", headers={
        "Content-Disposition": f'attachment; filename="{stem}.md"'})


def marked_inner(title: str, body: str, field) -> str:
    """The heading and the body with every blank marked — `field` decides
    what a blank becomes. One walk over the document serves both the editor
    (inputs you type into) and the printable view (boxes you write on), so
    a blank can never appear in one and be missing from the other.

    `field(kind, index, meta)` returns the HTML: kind is "token" or a
    region kind; meta is the token name or the region dict."""
    toks, regions = [], scan_regions(body)
    marks = []
    for m in _matches(body):
        marks.append(("T", len(toks), m.start(), m.end()))
        toks.append(token_value(m))
    for i, r in enumerate(regions):
        marks.append(("R", i, r["start"], r["end"]))
    for kind, i, a, z in sorted(marks, key=lambda x: -x[2]):
        body = body[:a] + f"\x00{kind}{i}\x01" + body[z:]

    html = md_html(body)
    for i, tv in enumerate(toks):
        html = html.replace(f"\x00T{i}\x01", field("token", i, tv))
    for i, r in enumerate(regions):
        html = html.replace(f"\x00R{i}\x01", field(r["kind"], i, r))
    head = f"<h1>{sect.esc(title)}</h1>" if title else ""
    return f"{head}{html}"


def editable_inner(title: str, body: str, suggestions: dict) -> str:
    """Every blank as something you type into."""
    def field(kind, i, meta):
        if kind == "token":
            tok, have = meta
            # what the document already says wins over what we'd suggest
            val = sect.esc(str(have if have is not None
                               else suggestions.get(tok, "")))
            key = GLOBAL_TOKENS.get(tok.strip())
            # A record field, not a blank: the same everywhere it appears,
            # so it is marked and the editor keeps them all in step.
            g = f' data-global="{key}"' if key else ""
            return (f'<input class="ph{" filled" if val else ""}'
                    f'{" ph-global" if key else ""}"'
                    f' data-tok="{sect.esc(tok)}"{g} value="{val}"'
                    f' placeholder="{sect.esc(tok)}"'
                    f' size="{max(len(tok) + 2, 10)}">')
        if kind == "area":
            return ('<textarea class="ph ph-area" data-region="%d" rows="1"'
                    ' placeholder="Type your answer — a sentence or a'
                    ' paragraph"></textarea>' % i)
        if kind == "line":
            return (f'<input class="ph ph-line" data-region="{i}"'
                    f'{" inputmode=\"decimal\"" if meta["money"] else ""}'
                    f' placeholder="write in" size="14">')
        if kind == "cell":
            return (f'<input class="ph ph-line ph-cell" data-region="{i}"'
                    f' placeholder="…" size="8">')
        return (f'<input type="checkbox" class="ph-check" data-region="{i}"'
                f'{" checked" if meta["checked"] else ""}>')
    return marked_inner(title, body, field)


def form_inner(title: str, body: str, gvals: dict | None = None) -> str:
    """Every blank as a box you write on. Reading a document should show
    where the answers go — print it and fill it in with a pen — instead of
    hiding them as bracketed words or a bare rule. A field the record
    answers reads as answered, and still reads as a field: that is how you
    can tell the client's name from the sentence around it."""
    def field(kind, i, meta):
        if kind == "token":
            tok, have = meta
            if have is None:
                key = GLOBAL_TOKENS.get(tok.strip())
                gv = str((gvals or {}).get(key or "", "")).strip()
                if gv:
                    have = gv
            if have is not None:
                # An answer is still a field: shown as one, so you can see
                # what was set and that it can be set again.
                return (f'<span class="fbox fbox-set" title="{sect.esc(tok)}">'
                        f'{sect.esc(have)}</span>')
            w = max(len(tok) + 2, 9)
            return (f'<span class="fbox" style="min-width:{w}ch">'
                    f'<span class="flab">{sect.esc(tok)}</span></span>')
        if kind == "area":
            return ('<span class="fbox fbox-area">'
                    '<span class="flab">write your answer here</span></span>')
        if kind == "line":
            return ('<span class="fbox" style="min-width:12ch">'
                    '<span class="flab">write in</span></span>')
        if kind == "cell":
            return '<span class="fbox fbox-cell"></span>'
        return ('<span class="fcheck%s"></span>'
                % (" on" if meta["checked"] else ""))
    return marked_inner(title, body, field)


# One printable sheet at letter aspect is a page, and the rule that draws
# the boundary is the same rule the counter counts — so "3 of 15" always
# names a line you can see. --page-h is set by whoever mounts the frame.
PAGE_RULE_CSS = (
    "html{--page-h:1000px}"
    "body{background-image:repeating-linear-gradient(to bottom,"
    "rgba(0,0,0,0) 0,rgba(0,0,0,0) calc(var(--page-h) - 1px),"
    "rgba(139,132,150,.30) calc(var(--page-h) - 1px),"
    "rgba(139,132,150,.30) var(--page-h))}"
)


# One typography for every rendering of a document — preview, editor,
# binder page. When these drifted (line-height 1.7 here, 1.6 there) the
# editor was a different document that happened to hold the same words,
# and it paginated like one.
DOC_BASE_CSS = (
    "body{font-family:'Inter',system-ui,sans-serif;color:#1b181f;"
    "line-height:1.6;max-width:760px;margin:0 auto;padding:32px 24px}"
    "h1,h2,h3,h4{font-family:'Fraunces',Georgia,serif}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{border-top:1px solid #e9e4dc;padding:6px 10px 6px 0;"
    "text-align:left}"
    "blockquote{border-left:3px solid #e9e4dc;padding-left:14px;"
    "color:#5d5768;margin:10px 0}"
    "img{max-width:100%}"
    ".pgbreak{break-before:page;page-break-before:always;height:0;"
    "margin:34px 0;border-top:1px dashed #cfc8bd}"
    # a blank you can see and write on, on screen and on paper
    ".fbox{display:inline-block;border:1px solid #b9b2a6;border-radius:5px;"
    "background:#fcfaf6;padding:1px 6px;margin:0 1px;min-height:1.35em;"
    "vertical-align:baseline;line-height:1.35}"
    ".flab{font-size:.72em;letter-spacing:.02em;color:#a9a294;"
    "text-transform:none;white-space:nowrap}"
    ".fbox-area{display:block;width:100%;min-height:3.1em;margin:6px 0 10px;"
    "padding:5px 8px}"
    ".fbox-cell{display:inline-block;min-width:6ch;min-height:1.3em}"
    ".fcheck{display:inline-block;width:12px;height:12px;border:1px solid "
    "#8b8496;border-radius:3px;vertical-align:-1px}"
    ".fcheck.on{background:#3fbd82;border-color:#3fbd82}"
    ".fbox-set{border-color:#8fcfae;background:#f1faf5;color:#1b181f;"
    "min-width:0}"
)

# A field should cost the line it sits on as little as possible: hundreds
# of them across a binder, and every pixel of vertical padding is a pixel
# the editor drifts away from the printed page.
FIELD_CSS = (
    "input.ph,textarea.ph{font:inherit;font-size:.92em;"
    "padding:0 6px;margin:0 1px;border:1px dashed #d08a00;"
    "border-radius:7px;background:#fff8ec;color:#1b181f;min-width:44px;"
    "line-height:1.3;vertical-align:baseline}"
    "textarea.ph-area{display:block;width:100%;margin:4px 0 8px;"
    "padding:4px 8px;resize:vertical;line-height:1.45;"
    "overflow:hidden;box-sizing:border-box}"
    "input.ph-cell{padding:0 4px}"
    "input.ph-global{border-style:solid;border-color:#8a6ff0;"
    "background:#f4f0ff}"
    "input.bd-title{display:block;width:100%;font-family:'Fraunces',"
    "Georgia,serif;font-size:1.7em;font-weight:600;color:#1b181f;"
    "border:1px dashed transparent;border-radius:8px;padding:2px 6px;"
    "margin:0 0 6px -6px;background:transparent}"
    "input.bd-title:hover{border-color:#d5cec2}"
    "input.bd-title:focus{outline:2px solid #8a6ff0;border-color:#8a6ff0;"
    "background:#fff}"
    "input.ph:focus,textarea.ph:focus{outline:2px solid #8a6ff0;"
    "border-style:solid}"
    "input.ph.filled,textarea.ph.filled{border:1px solid #3fbd82;"
    "background:#effaf4}"
    "input.ph-check{width:15px;height:15px;accent-color:#3fbd82;"
    "vertical-align:-2px}"
)

EDITABLE_CSS = DOC_BASE_CSS + FIELD_CSS


def render_editable(d, suggestions: dict) -> str:
    """The document as its own form: every blank rendered as a live field
    where it sits in the text. Tokens become inputs that fill by name;
    write-in lines become text boxes — a whole line gets a paragraph box, an
    inline run gets a small one, a run after a $ takes numbers; checkboxes
    toggle. Everything rides through the markdown renderer as
    control-character sentinels, which html.escape ignores and no human can
    type."""
    from .api import FONT_LINK
    return (
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,"
        f" initial-scale=1\"><title>{sect.esc(d['title'])}</title>"
        f"{FONT_LINK}<style>{EDITABLE_CSS}html{{background:#fff}}"
        f"{PAGE_RULE_CSS}</style></head><body>"
        f"{editable_inner(d['title'], d['body'], suggestions)}"
        f"</body></html>")


def _editable_doc_or_refuse(con, did: int):
    d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if d is None or not (d["body"] or "").strip():
        raise HTTPException(404, "no authored document there")
    signed = con.execute(
        "SELECT COUNT(*) n FROM document_signatures WHERE document_id=?"
        " AND status='signed'", (did,)).fetchone()["n"]
    if signed:
        raise HTTPException(400, "this document has been signed — its text "
                                 "is what was attested to. Supersede it "
                                 "rather than editing it")
    return d


@router.get("/api/store/admin/documents/{did}/editable")
def vault_editable(did: int, u=Depends(admin_user), con=Depends(get_con)):
    d = _editable_doc_or_refuse(con, did)
    # a document filed under a client borrows that client's suggestions
    sug = {}
    row = con.execute("SELECT engagement_id FROM engagement_docs"
                      " WHERE doc_id=?", (did,)).fetchone()
    if row:
        from . import engagements as eng
        e = con.execute("SELECT * FROM engagements WHERE id=?",
                        (row["engagement_id"],)).fetchone()
        if e:
            sug = eng.suggested_fills(e)
    return HTMLResponse(render_editable(d, sug))


class EditBody(BaseModel):
    fills: dict = {}
    regions: dict = {}


@router.post("/api/store/admin/documents/{did}/edit")
def vault_edit(did: int, body: EditBody, u=Depends(admin_user),
               con=Depends(get_con)):
    """One save for every kind of blank: regions first (by position, from
    the end backwards), then token fills by name — the same functions the
    scanner and the renderer use."""
    d = _editable_doc_or_refuse(con, did)

    # A record field is the client's, not this document's. Whichever editor
    # you came through — the binder or one page of it — typing the client's
    # name writes the client's name, once, where every document reads it.
    fills, gvals = {}, {}
    for tok, val in (body.fills or {}).items():
        key = GLOBAL_TOKENS.get(tok.strip())
        if key:
            gvals[key] = val
        else:
            fills[tok] = val
    changed = []
    row = con.execute("SELECT engagement_id FROM engagement_docs"
                      " WHERE doc_id=?", (did,)).fetchone()
    if gvals and row:
        from . import engagements as eng
        changed = eng.apply_globals(con, row["engagement_id"], gvals,
                                    u["name"])
    elif gvals:
        fills.update({t: v for t, v in (body.fills or {}).items()
                      if GLOBAL_TOKENS.get(t.strip())})   # no record to hold it

    text = apply_regions(d["body"], body.regions or {})
    text = fill(text, fills)
    remaining = placeholders(text)
    con.execute("UPDATE documents SET body=?, status=? WHERE id=?",
                (text, "draft" if remaining else "active", did))
    n_edits = len([v for v in (body.regions or {}).values()
                   if str(v).strip()]) \
        + len([v for v in (body.fills or {}).values() if str(v).strip()])
    log(con, did, u["name"], "edited in place",
        f"{n_edits} field(s)"
        + (f", {len(remaining)} bracket(s) left" if remaining else ""))
    con.commit()
    # The party rides back so "Save & sign" can prefill the signer without
    # a second request — and a document filed under a client prefers that
    # client's named approver, because the approver signs, not the company.
    party = {"name": d["party_name"], "email": d["party_email"]}
    row = con.execute(
        "SELECT e.approver_name, e.approver_email FROM engagement_docs ed"
        " JOIN engagements e ON e.id=ed.engagement_id WHERE ed.doc_id=?",
        (did,)).fetchone()
    if row and (row["approver_name"] or row["approver_email"]):
        party = {"name": row["approver_name"] or party["name"],
                 "email": row["approver_email"] or party["email"]}
    return {"unfilled": remaining, "party": party, "record": changed}


@router.patch("/api/store/admin/documents/{did}")
def edit_document(did: int, body: DocBody, u=Depends(admin_user),
                  con=Depends(get_con)):
    if body.category not in CATEGORIES or body.party_kind not in PARTY_KINDS:
        raise HTTPException(400, "unknown category or party kind")
    con.execute(
        "UPDATE documents SET title=?,category=?,party_kind=?,party_name=?,"
        " party_email=?,notes=?,effective=?,expires=?,confidential=?"
        " WHERE id=?",
        (body.title.strip()[:200], body.category, body.party_kind,
         body.party_name.strip()[:120], body.party_email.strip(),
         body.notes.strip()[:1000], body.effective, body.expires,
         1 if body.confidential else 0, did))
    log(con, did, u["name"], "edited")
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/documents/{did}")
def delete_document(did: int, u=Depends(admin_user), con=Depends(get_con)):
    """Signed documents are archived, not deleted.

    A signature is evidence that a named person agreed to a specific text on
    a specific date, and the fingerprint in the trail is what ties the two
    together. Deleting the document leaves the signature attesting to
    nothing, which is worse than useless — it looks like a record.
    Unsigned drafts are just drafts, and those go properly.
    """
    d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such document")
    signed = con.execute(
        "SELECT COUNT(*) n FROM document_signatures WHERE document_id=?"
        " AND status='signed'",
        (did,)).fetchone()["n"]
    if signed:
        con.execute("UPDATE documents SET status='archived' WHERE id=?",
                    (did,))
        log(con, did, u["name"], "archived",
            f"{signed} signature(s) — kept as evidence")
        con.commit()
        return {"ok": True, "archived": True, "signatures": signed}
    try:
        f = doc_path(d)
        if f.exists():
            f.unlink()
    except Exception:
        pass                # a missing file must not block the delete
    con.execute("DELETE FROM document_signatures WHERE document_id=?", (did,))
    con.execute("DELETE FROM document_events WHERE document_id=?", (did,))
    # An engagement link left behind would point at nothing and count wrong,
    # and a gate resting on the deleted doc would silently reopen anyway —
    # unlink it so the reopening is visible in the gate row, not a mystery.
    con.execute("DELETE FROM engagement_docs WHERE doc_id=?", (did,))
    con.execute("UPDATE engagement_gates SET doc_id=0 WHERE doc_id=?", (did,))
    con.execute("DELETE FROM documents WHERE id=?", (did,))
    con.commit()
    return {"ok": True, "archived": False}


@router.post("/api/store/admin/documents/{did}/status")
def set_status(did: int, body: dict, u=Depends(admin_user),
               con=Depends(get_con)):
    status = body.get("status", "")
    if status not in ("draft", "active", "expired", "superseded", "archived"):
        raise HTTPException(400, "unknown status")
    con.execute("UPDATE documents SET status=? WHERE id=?", (status, did))
    log(con, did, u["name"], "status", status)
    con.commit()
    return {"ok": True}


@router.get("/api/store/admin/documents/{did}/trail")
def read_trail(did: int, u=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM document_events WHERE document_id=? ORDER BY id",
        (did,)).fetchall()
    return [dict(r) for r in rows]


# ---------- signature requests ----------

class SignRequestBody(BaseModel):
    signer_name: str
    signer_email: str
    role: str = "signer"
    message: str = ""
    in_person: bool = False        # sign here and now; the email is a receipt


@router.post("/api/store/admin/documents/{did}/request-signature")
def request_signature(did: int, body: SignRequestBody, request: Request,
                      u=Depends(admin_user), con=Depends(get_con)):
    d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such document")
    if not d["ext"] and not (d["body"] or "").strip():
        raise HTTPException(
            400, "attach a file or write the document body before sending it "
                 "for signature — there has to be something to sign")
    email = body.signer_email.strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "a valid signer email is required")
    if body.role not in ("signer", "approver", "witness"):
        raise HTTPException(400, "unknown role")

    provider = esign_provider(con)
    if body.in_person:
        # The signer is in the room: the pad opens right here, drawn with a
        # mouse or a finger, and no request email goes out — the only email
        # they get is the receipt with the certificate, after signing.
        provider = "builtin"
    token = secrets.token_urlsafe(32)
    envelope = ""
    if provider == "docusign":
        ok2, envelope = docusign_send(con, d, body.signer_name.strip(),
                                      email, body.message.strip())
        if not ok2:
            # Fall back rather than fail: the client is waiting either way,
            # and the audit trail records which road the request took.
            provider = "builtin"
            log(con, did, u["name"], "docusign failed",
                str(envelope)[:180])
            envelope = ""
    cur = con.execute(
        "INSERT INTO document_signatures(document_id,token,signer_name,"
        " signer_email,role,provider,provider_ref,sent_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (did, token, body.signer_name.strip()[:120], email, body.role,
         provider, envelope, time.time()))
    log(con, did, u["name"], "signature requested",
        f"{body.signer_name} <{email}>"
        + (f" via DocuSign {envelope}" if envelope else ""))
    con.commit()

    if provider == "docusign":
        # DocuSign sends its own email and hosts its own page; there is no
        # link of ours to hand out.
        return {"ok": True, "link": "", "id": cur.lastrowid,
                "provider": "docusign", "envelope": envelope}

    base = str(request.base_url).rstrip("/")
    link = f"{base}/sign/{token}"
    if body.in_person:
        log(con, did, u["name"], "in-person signing opened",
            f"{body.signer_name} <{email}>")
        con.commit()
        return {"ok": True, "link": link, "id": cur.lastrowid,
                "provider": "builtin", "in_person": True}
    try:
        from erp.backend.main import CFG
        mailer.send(
            CFG, email, f"Please sign: {d['title']}",
            f"Hi {body.signer_name},\n\n"
            f"{body.message.strip() or 'Please review and sign the document below.'}\n\n"
            f"{link}\n\n"
            f"This link is unique to you — please don't forward it.\n\n"
            f"— {u['name']}")
    except Exception:
        pass          # a mail outage must not lose the request
    return {"ok": True, "link": link, "id": cur.lastrowid,
            "provider": provider}


@router.post("/api/store/admin/signatures/{sid}/void")
def void_signature(sid: int, u=Depends(admin_user), con=Depends(get_con)):
    s = con.execute("SELECT * FROM document_signatures WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "no such request")
    if s["status"] == "signed":
        raise HTTPException(
            400, "a completed signature can't be voided — supersede the "
                 "document instead, which keeps the record intact")
    con.execute("UPDATE document_signatures SET status='void' WHERE id=?",
                (sid,))
    log(con, s["document_id"], u["name"], "signature voided", s["signer_email"])
    con.commit()
    return {"ok": True}


def esign_provider(con) -> str:
    """Which signature provider is configured.

    Follows the same slot pattern as the rest of the platform: `builtin` uses
    the flow in this module; anything else is expected to be a third-party
    service reached over its own API. Nothing here calls a vendor directly.
    """
    # Derived, not configured twice: connecting DocuSign in integrations IS
    # the choice. The store_meta key still wins if someone set it by hand.
    row = con.execute(
        "SELECT v FROM store_meta WHERE k='esign_provider'").fetchone()
    if row and row["v"]:
        return row["v"]
    return "docusign" if docusign_creds(con) else "builtin"


# ---------- public: the signing page ----------

def _sig_or_404(con, token: str):
    s = con.execute("SELECT * FROM document_signatures WHERE token=?",
                    (token,)).fetchone()
    if s is None or s["status"] in ("void",):
        raise HTTPException(404, "this signing link is no longer valid")
    return s


@router.get("/sign/{token}")
def signing_page(token: str, request: Request, con=Depends(get_con),
                 _rl=Depends(rate_limit)):
    s = _sig_or_404(con, token)
    d = con.execute("SELECT * FROM documents WHERE id=?",
                    (s["document_id"],)).fetchone()
    if d is None:
        raise HTTPException(404, "document not found")
    if s["status"] == "sent":
        con.execute(
            "UPDATE document_signatures SET status='viewed', viewed_at=?"
            " WHERE id=?", (time.time(), s["id"]))
        log(con, d["id"], s["signer_email"], "viewed")
        con.commit()

    from .api import icon_sprite, FONT_LINK
    done = s["status"] == "signed"
    declined = s["status"] == "declined"
    body_html = ""
    if (d["body"] or "").strip():
        body_html = (f'<div class="doc-body">{md_html(d["body"])}'
                     f'{signatures_html(signed_rows(con, d["id"]))}</div>')
    elif d["ext"] == "pdf":
        body_html = (f'<iframe class="doc-frame" src="/sign/{token}/file"'
                     f' title="{sect.esc(d["title"])}"></iframe>')
    elif d["ext"] in ("png", "jpg", "jpeg"):
        body_html = (f'<img class="doc-img" src="/sign/{token}/file"'
                     f' alt="{sect.esc(d["title"])}">')
    else:
        body_html = (f'<p class="doc-dl">This document is a '
                     f'<b>.{d["ext"]}</b> file. '
                     f'<a href="/sign/{token}/file">Download it</a> to read '
                     f'before signing.</p>')

    if done:
        panel = f"""
        <div class="sign-done">
          <h2>Signed</h2>
          <p>You signed this on {time.strftime('%d %B %Y at %H:%M UTC',
             time.gmtime(s['signed_at']))}.</p>
          <p class="fine">A copy has been emailed to {sect.esc(s['signer_email'])}.
             Reference <code>{s['token'][:12]}</code>.</p>
          <p><a class="btn" href="/sign/{token}/certificate">View the
             signing certificate</a>
             <a class="btn" href="/sign/{token}/pdf">Download the PDF</a></p>
        </div>"""
    elif declined:
        panel = """<div class="sign-done"><h2>Declined</h2>
          <p>You declined to sign this document. Nothing further is needed.</p>
          </div>"""
    else:
        panel = f"""
        <form class="sign-form" id="sign-form">
          <h2>Sign this document</h2>
          <p class="fine">By signing you agree to use an electronic signature,
            and that it has the same effect as a handwritten one.</p>

          <label>Your full legal name</label>
          <input id="sg-name" required autocomplete="name"
            value="{sect.esc(s['signer_name'])}">

          <label>Draw your signature <span class="fine">(or leave blank to use
            your typed name)</span></label>
          <div class="pad-wrap">
            <canvas id="sg-pad" width="600" height="160"></canvas>
            <button type="button" class="btn ghost sm" id="sg-clear">Clear</button>
          </div>

          <label class="agree">
            <input type="checkbox" id="sg-agree" required>
            I have read this document and agree to be bound by it.
          </label>

          <div class="acts">
            <button type="button" class="btn ghost" id="sg-decline">Decline</button>
            <button type="submit" class="btn">Sign document</button>
          </div>
          <p class="msg" id="sg-msg"></p>
        </form>"""

    page = f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign — {sect.esc(d['title'])}</title>
{FONT_LINK}
<style>
:root {{ --ink:#1b181f; --ink2:#5d5768; --ink3:#8b8496; --bg:#fbf9f6;
  --paper:#fff; --line:#e8e3ee; --accent:#6c00bf; --ok:#00714f; }}
*{{box-sizing:border-box;margin:0}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);
  color:var(--ink);line-height:1.55;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:820px;margin:0 auto;padding:28px 22px 70px}}
header{{display:flex;align-items:center;gap:12px;padding:16px 22px;
  border-bottom:1px solid var(--line);background:var(--paper)}}
h1{{font-family:'Fraunces',Georgia,serif;font-size:26px;font-weight:600;
  letter-spacing:-.02em}}
h2{{font-family:'Fraunces',Georgia,serif;font-size:21px;font-weight:600;
  margin-bottom:8px}}
.meta{{color:var(--ink2);font-size:13.5px;margin-top:6px}}
.card{{background:var(--paper);border:1px solid var(--line);
  border-radius:16px;padding:26px;margin-top:18px}}
.doc-body p{{margin-bottom:12px}}
.doc-frame{{width:100%;height:70vh;border:1px solid var(--line);
  border-radius:10px}}
.doc-img{{width:100%;border-radius:10px}}
.doc-dl{{padding:26px;text-align:center;color:var(--ink2)}}
label{{display:block;font-size:11.5px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink3);margin:18px 0 6px}}
input[type=text],input:not([type]){{width:100%;border:1px solid var(--line);
  border-radius:10px;padding:11px 13px;font-family:inherit;font-size:15px;
  background:var(--bg)}}
.pad-wrap{{position:relative}}
#sg-pad{{width:100%;height:160px;border:1px dashed var(--line);
  border-radius:10px;background:var(--paper);touch-action:none;display:block}}
#sg-clear{{position:absolute;right:10px;top:10px}}
.agree{{display:flex;gap:10px;align-items:flex-start;text-transform:none;
  letter-spacing:0;font-size:14.5px;font-weight:400;color:var(--ink);
  margin-top:20px}}
.agree input{{width:auto;margin-top:3px}}
.acts{{display:flex;gap:10px;justify-content:flex-end;margin-top:22px}}
.btn{{background:var(--accent);color:#fff;border:none;border-radius:999px;
  padding:12px 24px;font-family:inherit;font-weight:600;font-size:15px;
  cursor:pointer;text-decoration:none;display:inline-block}}
.btn.ghost{{background:none;color:var(--ink);border:1px solid var(--line)}}
.btn.sm{{padding:6px 14px;font-size:13px}}
.fine{{font-size:12.5px;color:var(--ink3);text-transform:none;
  letter-spacing:0;font-weight:400}}
.msg{{margin-top:12px;font-size:14px}}
.msg.bad{{color:#c01060}} .msg.ok{{color:var(--ok)}}
.sign-done h2{{color:var(--ok)}}
</style></head><body>
{icon_sprite()}
<header><b>{sect.esc(d['party_name'] or 'Document')}</b>
  <span class="fine" style="margin-left:auto">Secure signing</span></header>
<div class="wrap">
  <h1>{sect.esc(d['title'])}</h1>
  <p class="meta">{CATEGORIES.get(d['category'], d['category'])}
    {f" · effective {time.strftime('%d %B %Y', time.gmtime(d['effective']))}"
      if d['effective'] else ""}
    {f" · expires {time.strftime('%d %B %Y', time.gmtime(d['expires']))}"
      if d['expires'] else ""}</p>
  <div class="card">{body_html}</div>
  <div class="card">{panel}</div>
  <p class="fine" style="margin-top:16px">Signing records your name, the time,
    your IP address and a fingerprint of this exact document, so it can be
    shown later that this is what you signed.</p>
</div>
<script>
(function(){{
  var pad=document.getElementById('sg-pad');
  if(!pad) return;
  var ctx=pad.getContext('2d'), drawing=false, drew=false;
  function resize(){{
    var r=pad.getBoundingClientRect(), s=window.devicePixelRatio||1;
    pad.width=r.width*s; pad.height=160*s; ctx.scale(s,s);
    ctx.lineWidth=2.2; ctx.lineCap='round'; ctx.strokeStyle='#1b181f';
  }}
  resize();
  function pos(e){{
    var r=pad.getBoundingClientRect();
    var t=e.touches?e.touches[0]:e;
    return [t.clientX-r.left, t.clientY-r.top];
  }}
  function start(e){{ drawing=true; drew=true; var p=pos(e);
    ctx.beginPath(); ctx.moveTo(p[0],p[1]); e.preventDefault(); }}
  function move(e){{ if(!drawing) return; var p=pos(e);
    ctx.lineTo(p[0],p[1]); ctx.stroke(); e.preventDefault(); }}
  function end(){{ drawing=false; }}
  pad.addEventListener('mousedown',start); pad.addEventListener('mousemove',move);
  window.addEventListener('mouseup',end);
  pad.addEventListener('touchstart',start,{{passive:false}});
  pad.addEventListener('touchmove',move,{{passive:false}});
  pad.addEventListener('touchend',end);
  document.getElementById('sg-clear').onclick=function(){{
    ctx.clearRect(0,0,pad.width,pad.height); drew=false; }};

  var msg=document.getElementById('sg-msg');
  document.getElementById('sign-form').onsubmit=async function(e){{
    e.preventDefault();
    var name=document.getElementById('sg-name').value.trim();
    if(!name){{ msg.className='msg bad'; msg.textContent='Please type your name.'; return; }}
    if(!document.getElementById('sg-agree').checked){{
      msg.className='msg bad'; msg.textContent='Please tick the box to agree.'; return; }}
    var btn=e.target.querySelector('button[type=submit]'); btn.disabled=true;
    try{{
      var r=await fetch(location.pathname,{{method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{typed_name:name,
          signature_data: drew ? pad.toDataURL('image/png') : ''}})}});
      var out=await r.json();
      if(!r.ok) throw new Error(out.detail||'could not sign');
      location.reload();
    }}catch(err){{
      msg.className='msg bad'; msg.textContent=String(err.message||err);
      btn.disabled=false;
    }}
  }};
  document.getElementById('sg-decline').onclick=async function(){{
    var why=prompt('Optional — why are you declining?');
    if(why===null) return;
    await fetch(location.pathname+'/decline',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{reason:why||''}})}});
    location.reload();
  }};
}})();
</script></body></html>"""
    return HTMLResponse(page)


@router.get("/sign/{token}/file")
def signing_file(token: str, con=Depends(get_con), _rl=Depends(rate_limit)):
    s = _sig_or_404(con, token)
    d = con.execute("SELECT * FROM documents WHERE id=?",
                    (s["document_id"],)).fetchone()
    if d is None or not d["ext"]:
        raise HTTPException(404, "no file")
    p = doc_path(d)
    if not p.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(p, media_type=ALLOWED_EXT.get(d["ext"],
                        "application/octet-stream"))


class SignBody(BaseModel):
    typed_name: str
    signature_data: str = ""


@router.post("/sign/{token}")
def do_sign(token: str, body: SignBody, request: Request,
            con=Depends(get_con), _rl=Depends(rate_limit)):
    s = _sig_or_404(con, token)
    if s["status"] == "signed":
        raise HTTPException(400, "this document has already been signed")
    if s["status"] == "declined":
        raise HTTPException(400, "this request was declined")
    name = body.typed_name.strip()
    if len(name) < 2:
        raise HTTPException(400, "please type your full name")
    d = con.execute("SELECT * FROM documents WHERE id=?",
                    (s["document_id"],)).fetchone()

    # The fingerprint of exactly what they were shown. If the file is later
    # replaced, this no longer matches and the certificate says so.
    if d["ext"]:
        p = doc_path(d)
        digest = file_sha256(p) if p.exists() else ""
    else:
        digest = hashlib.sha256((d["body"] or "").encode()).hexdigest()

    sig = (body.signature_data or "")[:200000]
    if sig and not sig.startswith("data:image/png;base64,"):
        sig = ""          # only accept what our own pad produces
    # An untouched 600×160 canvas encodes to a couple of hundred bytes. Storing
    # that would print an empty box on the certificate where a signature should
    # be — worse than no image, because it looks like something failed. Below
    # this threshold, fall back to rendering the typed name.
    if len(sig) < 1500:
        sig = ""
    now = time.time()
    con.execute(
        "UPDATE document_signatures SET status='signed', typed_name=?,"
        " signature_data=?, doc_sha256=?, ip=?, user_agent=?, signed_at=?"
        " WHERE id=?",
        (name[:120], sig, digest,
         (request.client.host if request.client else "")[:60],
         request.headers.get("user-agent", "")[:300], now, s["id"]))
    log(con, d["id"], s["signer_email"], "signed",
        f"as '{name}' sha256={digest[:16]}…")

    remaining = con.execute(
        "SELECT COUNT(*) n FROM document_signatures WHERE document_id=?"
        " AND status NOT IN ('signed','void')", (d["id"],)).fetchone()["n"]
    if remaining == 0:
        con.execute("UPDATE documents SET status='active' WHERE id=?", (d["id"],))
        log(con, d["id"], "system", "fully executed")
    con.commit()

    try:
        from erp.backend.main import CFG
        mailer.send(
            CFG, s["signer_email"], f"Signed: {d['title']}",
            f"Thank you — you signed '{d['title']}' on "
            f"{time.strftime('%d %B %Y at %H:%M UTC', time.gmtime(now))}.\n\n"
            f"Your signing certificate: "
            f"{str(request.base_url).rstrip('/')}/sign/{token}/certificate\n\n"
            f"Document fingerprint (SHA-256): {digest}")
    except Exception:
        pass
    from .api import fire_webhooks
    fire_webhooks("document.signed",
                  {"document_id": d["id"], "title": d["title"],
                   "signer": s["signer_email"]})
    return {"ok": True, "remaining": remaining}


@router.post("/sign/{token}/decline")
def do_decline(token: str, body: dict, con=Depends(get_con),
               _rl=Depends(rate_limit)):
    s = _sig_or_404(con, token)
    if s["status"] == "signed":
        raise HTTPException(400, "already signed")
    con.execute(
        "UPDATE document_signatures SET status='declined', decline_reason=?"
        " WHERE id=?", (str(body.get("reason", ""))[:400], s["id"]))
    log(con, s["document_id"], s["signer_email"], "declined",
        str(body.get("reason", ""))[:200])
    con.commit()
    return {"ok": True}


@router.get("/sign/{token}/certificate")
def certificate(token: str, con=Depends(get_con), _rl=Depends(rate_limit)):
    """The audit record. This is what makes the signature defensible: who
    signed, when, from where, and the fingerprint of exactly what they saw."""
    s = _sig_or_404(con, token)
    if s["status"] != "signed":
        raise HTTPException(404, "not signed yet")
    d = con.execute("SELECT * FROM documents WHERE id=?",
                    (s["document_id"],)).fetchone()
    events = con.execute(
        "SELECT * FROM document_events WHERE document_id=? ORDER BY id",
        (d["id"],)).fetchall()
    current = ""
    if d["ext"]:
        p = doc_path(d)
        current = file_sha256(p) if p.exists() else ""
    else:
        current = hashlib.sha256((d["body"] or "").encode()).hexdigest()
    intact = (current == s["doc_sha256"])

    fmt = lambda t: (time.strftime("%d %b %Y %H:%M:%S UTC", time.gmtime(t))
                     if t else "—")
    rows = "".join(
        f"<tr><td>{fmt(e['created_at'])}</td><td>{sect.esc(e['actor'])}</td>"
        f"<td>{sect.esc(e['action'])}</td><td>{sect.esc(e['detail'])}</td></tr>"
        for e in events)
    sig_img = (f'<img src="{s["signature_data"]}" alt="signature" '
               f'style="max-width:320px;border-bottom:1px solid #999">'
               if s["signature_data"] else
               f'<span style="font-family:Fraunces,Georgia,serif;font-size:26px;'
               f'border-bottom:1px solid #999;padding:0 12px">'
               f'{sect.esc(s["typed_name"])}</span>')

    page = f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>Signing certificate — {sect.esc(d['title'])}</title>
<style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;max-width:760px;
  margin:40px auto;padding:0 20px;color:#1b181f;line-height:1.6}}
h1{{font-size:22px}} h2{{font-size:15px;margin-top:28px;
  text-transform:uppercase;letter-spacing:.1em;color:#8b8496}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}}
td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid #eee;
  vertical-align:top}}
code{{font-size:12px;word-break:break-all;background:#f4f2f7;padding:2px 5px;
  border-radius:4px}}
.seal{{border:1px solid #e8e3ee;border-radius:12px;padding:20px;margin:20px 0}}
.ok{{color:#00714f;font-weight:600}} .bad{{color:#c01060;font-weight:600}}
@media print{{ body{{margin:0}} }}
</style></head><body>
<h1>Signing certificate</h1>
<p><b>{sect.esc(d['title'])}</b><br>
{CATEGORIES.get(d['category'], d['category'])}
{f" · {sect.esc(d['party_name'])}" if d['party_name'] else ""}</p>

<div class="seal">
  <h2 style="margin-top:0">Signature</h2>
  <p>{sig_img}</p>
  <table>
    <tr><td>Signed by</td><td><b>{sect.esc(s['typed_name'])}</b></td></tr>
    <tr><td>Email</td><td>{sect.esc(s['signer_email'])}</td></tr>
    <tr><td>Role</td><td>{sect.esc(s['role'])}</td></tr>
    <tr><td>Requested</td><td>{fmt(s['sent_at'])}</td></tr>
    <tr><td>First viewed</td><td>{fmt(s['viewed_at'])}</td></tr>
    <tr><td>Signed</td><td><b>{fmt(s['signed_at'])}</b></td></tr>
    <tr><td>IP address</td><td>{sect.esc(s['ip'])}</td></tr>
    <tr><td>Device</td><td style="font-size:11px">{sect.esc(s['user_agent'])}</td></tr>
    <tr><td>Reference</td><td><code>{s['token'][:24]}</code></td></tr>
  </table>
</div>

<h2>Document fingerprint</h2>
<p>SHA-256 of the document as presented at signing:</p>
<p><code>{s['doc_sha256'] or '—'}</code></p>
<p>Current fingerprint: <code>{current or '—'}</code></p>
<p>{'<span class="ok">The document is unchanged since it was signed.</span>'
   if intact else
   '<span class="bad">WARNING: the stored document no longer matches what '
   'was signed.</span>'}</p>

<h2>Audit trail</h2>
<table><tr><th>When</th><th>Who</th><th>What</th><th>Detail</th></tr>
{rows}</table>

<h2>About this signature</h2>
<p style="font-size:13px;color:#5d5768">This is a simple electronic signature
under ESIGN (US) and eIDAS (EU/UK): the signer's mark captured with their
name, email, time, network address and a cryptographic fingerprint of the
document. It is not an advanced or qualified electronic signature — the
signer's identity was not independently verified beyond control of the email
address the request was sent to.</p>
</body></html>"""
    return HTMLResponse(page)


# ---------- DocuSign, through the esign provider slot ----------
# The slot existed from day one ("point it at DocuSign and requests route
# there instead"); this is the pointing. Which provider is in use is DERIVED
# from whether DocuSign is connected in integrations — connecting it is the
# choice, and there is no second switch to forget.

def docusign_creds(con) -> dict | None:
    from erp.backend import integrations
    c = integrations.creds(con, "docusign")
    if c and c.get("token") and c.get("account_id") \
            and c.get("base_uri"):
        return c
    return None


def docusign_envelope(title: str, pdf_b64: str, signer_name: str,
                      signer_email: str, message: str) -> dict:
    """The envelope payload, as a pure function so a test can hold its
    shape without an account."""
    return {
        "emailSubject": f"Please sign: {title}"[:100],
        "emailBlurb": (message or "Please review and sign.")[:1000],
        "documents": [{"documentBase64": pdf_b64, "name": f"{title}.pdf",
                       "fileExtension": "pdf", "documentId": "1"}],
        "recipients": {"signers": [{
            "email": signer_email, "name": signer_name,
            "recipientId": "1", "routingOrder": "1",
            # DocuSign places a tab at EVERY occurrence of an anchor string,
            # so "Sign here:" three times in a contract is three signature
            # tabs, and "Initials:" on each clause is initials on each
            # clause. All ignore-if-absent: a document with no markers still
            # signs at its Signed block.
            "tabs": {
                "signHereTabs": [
                    {"anchorString": "Signed", "anchorUnits": "pixels",
                     "anchorXOffset": "0", "anchorYOffset": "20",
                     "anchorIgnoreIfNotPresent": "true"},
                    {"anchorString": "Sign here:", "anchorUnits": "pixels",
                     "anchorXOffset": "60", "anchorYOffset": "-6",
                     "anchorIgnoreIfNotPresent": "true"},
                ],
                "initialHereTabs": [
                    {"anchorString": "Initials:", "anchorUnits": "pixels",
                     "anchorXOffset": "50", "anchorYOffset": "-6",
                     "anchorIgnoreIfNotPresent": "true"},
                ],
            },
        }]},
        "status": "sent",
    }


def docusign_send(con, d, signer_name: str, signer_email: str,
                  message: str) -> tuple:
    """(ok, envelope_id_or_error). The document travels as our own PDF —
    the same bytes a builtin signer would have been shown."""
    import base64
    c = docusign_creds(con)
    if not c:
        return False, "not connected"
    from erp.backend.integrations import _json_req
    from . import pdfgen
    if (d["body"] or "").strip():
        blob = pdfgen.doc_pdf(d["title"], d["body"])
    elif d["ext"] == "pdf":
        p = doc_path(d)
        if not p.exists():
            return False, "file missing from storage"
        blob = p.read_bytes()
    else:
        return False, f"a .{d['ext']} file can't go to DocuSign — PDF only"
    base = c["base_uri"].rstrip("/")
    ok, out = _json_req(
        f"{base}/restapi/v2.1/accounts/{c['account_id']}/envelopes", "POST",
        {"Authorization": f"Bearer {c['token']}"},
        docusign_envelope(d["title"], base64.b64encode(blob).decode(),
                          signer_name, signer_email, message))
    if ok and isinstance(out, dict) and out.get("envelopeId"):
        return True, out["envelopeId"]
    return False, str(out)[:200]


@router.post("/api/store/admin/signatures/{sid}/refresh")
def refresh_signature(sid: int, u=Depends(admin_user), con=Depends(get_con)):
    """Pull a DocuSign envelope's status back into the vault. Polling by
    button rather than webhook: it needs no public URL, and the person who
    cares is the one looking at the row anyway."""
    s = con.execute("SELECT * FROM document_signatures WHERE id=?",
                    (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "no such signature request")
    if s["provider"] != "docusign" or not s["provider_ref"]:
        return {"status": s["status"], "detail": "not a DocuSign request"}
    if s["status"] in ("signed", "declined", "void"):
        return {"status": s["status"]}
    c = docusign_creds(con)
    if not c:
        raise HTTPException(400, "DocuSign is no longer connected")
    from erp.backend.integrations import _req
    base = c["base_uri"].rstrip("/")
    ok, out = _req(
        f"{base}/restapi/v2.1/accounts/{c['account_id']}/envelopes/"
        f"{s['provider_ref']}", "GET",
        {"Authorization": f"Bearer {c['token']}"})
    if not ok or not isinstance(out, dict):
        raise HTTPException(502, f"DocuSign didn't answer: {str(out)[:120]}")
    status = out.get("status", "")
    if status == "completed":
        d = con.execute("SELECT * FROM documents WHERE id=?",
                        (s["document_id"],)).fetchone()
        digest = (file_sha256(doc_path(d)) if d["ext"] and doc_path(d).exists()
                  else hashlib.sha256((d["body"] or "").encode()).hexdigest())
        con.execute(
            "UPDATE document_signatures SET status='signed', signed_at=?,"
            " typed_name=?, doc_sha256=? WHERE id=?",
            (time.time(), s["signer_name"], digest, sid))
        log(con, s["document_id"], "DocuSign",
            "signed", f"envelope {s['provider_ref']}")
        con.commit()
        from .api import fire_webhooks
        fire_webhooks("document.signed", {
            "id": s["document_id"], "title": d["title"],
            "signer": s["signer_name"]})
        return {"status": "signed"}
    if status in ("declined", "voided"):
        new = "declined" if status == "declined" else "void"
        con.execute("UPDATE document_signatures SET status=? WHERE id=?",
                    (new, sid))
        log(con, s["document_id"], "DocuSign", new,
            f"envelope {s['provider_ref']}")
        con.commit()
        return {"status": new}
    return {"status": s["status"],
            "detail": f"DocuSign says: {status or 'no status'}"}
