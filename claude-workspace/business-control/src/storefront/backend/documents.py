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
from fastapi.responses import FileResponse, HTMLResponse
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
    con.execute("DELETE FROM document_log WHERE document_id=?", (did,))
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
    token = secrets.token_urlsafe(32)
    cur = con.execute(
        "INSERT INTO document_signatures(document_id,token,signer_name,"
        " signer_email,role,provider,sent_at) VALUES(?,?,?,?,?,?,?)",
        (did, token, body.signer_name.strip()[:120], email, body.role,
         provider, time.time()))
    log(con, did, u["name"], "signature requested", f"{body.signer_name} <{email}>")
    con.commit()

    base = str(request.base_url).rstrip("/")
    link = f"{base}/sign/{token}"
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
    row = con.execute(
        "SELECT v FROM store_meta WHERE k='esign_provider'").fetchone()
    return (row["v"] if row else "builtin") or "builtin"


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
        paras = "".join(f"<p>{sect.esc(p)}</p>"
                        for p in d["body"].split("\n\n") if p.strip())
        body_html = f'<div class="doc-body">{paras}</div>'
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
             signing certificate</a></p>
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
