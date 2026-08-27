"""B2B client engagements: the studio kit, run from the ERP.

The paper process lives in docs/business-control-b2b-client/ — eleven
numbered stages of markdown templates with [BRACKET] placeholders, each
belonging on one side of a wall: sent to the client, or never sent. This
module makes that kit executable without duplicating it:

  The kit on disk IS the template registry. Stages and templates are read at
  request time; adding a template to the folder adds it here, and there is
  no second list to forget to update.

  A generated document is a row in the documents vault (documents.py), body
  bound to the client, so signatures, the audit trail, expiry and the
  /sign/{token} flow all come along for free. This module never grows its
  own signature code.

  The per-client folder convention (clients/_template: stage folders, each
  split to-client/ vs internal/) becomes the EXPORT format. The folder is
  generated from the vault, never maintained beside it — and the zip a
  client receives is drawn from side='to_client' only, so the classic
  mistake (zipping the whole folder, estimate and gut-calls included) is
  not possible from that door.
"""
import io
import json
import re
import shutil
import time
import zipfile
from pathlib import Path

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from erp.backend import config
from . import sections as sect
from .api import admin_user, get_con, rate_limit

router = APIRouter()

# The kit ships with the working tree. A deployed install without docs/ gets
# an empty registry and a clear message rather than an error.
KIT = Path(__file__).resolve().parents[3] \
    / "docs" / "business-control-b2b-client" / "templates"

EXPORT_ROOT = config.DATA_DIR / "exports" / "clients"

TABLES = """
CREATE TABLE IF NOT EXISTS engagements (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  package TEXT DEFAULT '',                 -- A / B / C, or free text
  value_cents INTEGER DEFAULT 0,
  approver_name TEXT DEFAULT '',
  approver_email TEXT DEFAULT '',
  launch_target TEXT DEFAULT '',
  staging_url TEXT DEFAULT '',
  live_url TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  status TEXT DEFAULT 'active',            -- active|closed
  originator TEXT DEFAULT '',              -- who brought the client in
  internal_poc TEXT DEFAULT '',            -- who runs it day to day
  internal_poc_user_id INTEGER DEFAULT 0,
  internal_poc_status TEXT DEFAULT 'accepted',  -- accepted|pending|declined
  portal_token TEXT DEFAULT '',            -- the client's login-free link
  content_pct INTEGER DEFAULT 0,           -- the number that predicts lateness
  week_note TEXT DEFAULT '',               -- one sentence: what changed this week
  week_note_at REAL DEFAULT 0,             -- when it last changed — staleness is a fact, not a feeling
  portal_seen_at REAL DEFAULT 0,           -- when the client last looked
  blockers TEXT DEFAULT '',                -- honest, current, empty when none
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS engagement_docs (
  id INTEGER PRIMARY KEY,
  engagement_id INTEGER NOT NULL,
  doc_id INTEGER UNIQUE NOT NULL,          -- a vault document belongs to one client
  stage TEXT NOT NULL,                     -- kit stage dir, e.g. 03-proposal
  side TEXT NOT NULL DEFAULT 'to_client',  -- to_client | internal
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS engagement_docs_eng ON engagement_docs(engagement_id);
CREATE TABLE IF NOT EXISTS engagement_dates (
  id INTEGER PRIMARY KEY,
  engagement_id INTEGER NOT NULL,
  label TEXT NOT NULL,
  planned TEXT DEFAULT '',
  actual TEXT DEFAULT '',
  moved_because TEXT DEFAULT '',
  ord INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS engagement_gates (
  id INTEGER PRIMARY KEY,
  engagement_id INTEGER NOT NULL,
  gate TEXT NOT NULL,
  doc_id INTEGER DEFAULT 0,       -- the vault document whose signature passes it
  passed_at REAL DEFAULT 0,       -- manual confirmations only; signatures derive
  actor TEXT DEFAULT '',
  note TEXT DEFAULT '',           -- for a manual pass: where the evidence is filed
  stripe_session TEXT DEFAULT '', -- money gates: the checkout session to verify
  UNIQUE(engagement_id, gate)
);
CREATE TABLE IF NOT EXISTS engagement_log (
  id INTEGER PRIMARY KEY,
  engagement_id INTEGER NOT NULL,
  at REAL NOT NULL,
  actor TEXT DEFAULT '',
  what TEXT NOT NULL
);
"""


MIGRATIONS = (
    "ALTER TABLE engagements ADD COLUMN portal_token TEXT DEFAULT ''",
    "ALTER TABLE engagements ADD COLUMN content_pct INTEGER DEFAULT 0",
    "ALTER TABLE engagements ADD COLUMN week_note TEXT DEFAULT ''",
    "ALTER TABLE engagements ADD COLUMN blockers TEXT DEFAULT ''",
    "ALTER TABLE engagements ADD COLUMN week_note_at REAL DEFAULT 0",
    "ALTER TABLE engagements ADD COLUMN portal_seen_at REAL DEFAULT 0",
    "ALTER TABLE engagement_gates ADD COLUMN stripe_session TEXT DEFAULT ''",
    "ALTER TABLE engagements ADD COLUMN originator TEXT DEFAULT ''",
    "ALTER TABLE engagements ADD COLUMN internal_poc TEXT DEFAULT ''",
    "ALTER TABLE engagements ADD COLUMN internal_poc_user_id INTEGER DEFAULT 0",
    "ALTER TABLE engagements ADD COLUMN internal_poc_status TEXT"
    " DEFAULT 'accepted'",
)


def init_tables(con):
    con.executescript(TABLES)
    for m in MIGRATIONS:
        try:
            con.execute(m)
        except Exception:
            pass          # already applied


def log(con, eid: int, actor: str, what: str) -> None:
    con.execute("INSERT INTO engagement_log(engagement_id,at,actor,what)"
                " VALUES(?,?,?,?)", (eid, time.time(), actor, what[:300]))


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "client"


# The kit's stage numbering includes 01-potential-customer; the per-client
# folder convention starts at consultation. One mapping, derived nowhere else,
# so the export matches clients/_template exactly.
KIT_TO_CLIENT_STAGE = {
    "01-potential-customer": "01-consultation",
    "02-consultation": "01-consultation",
    "03-proposal": "02-proposal",
    "04-agreement": "03-agreement",
    "05-kickoff": "04-kickoff",
    "06-requirements": "05-requirements",
    "07-brand-exploration": "06-brand-exploration",
    "08-build": "07-build",
    "09-launch": "08-launch",
    "10-handover": "09-handover",
    "11-aftercare": "10-aftercare",
}


# ---------- gates: signatures with a stage attached ----------
# The kit's rule, made executable: "each one is a signature, not a feeling —
# a gate you can't point at is a gate that didn't happen." A signature gate
# is a LINK to a vault document; whether it has passed is read from that
# document's signatures at request time, never copied, so there is no state
# to fall out of sync. The two money gates aren't signatures — those are
# manual confirmations with an actor and a timestamp.
#
# The stage of an engagement is not a column anywhere. It is the stage of
# the first gate that hasn't passed — a checkbox that could disagree with
# the signed paper beside it is the status-board bug in software form.

GATES = [
    # (key, label, kind, the client stage this gate closes)
    ("proposal_accepted",   "Proposal accepted",    "signature", "02-proposal"),
    ("contract_signed",     "Contract signed",      "signature", "03-agreement"),
    ("deposit_cleared",     "Deposit cleared",      "money",     "03-agreement"),
    ("requirements_signed", "Requirements signed",  "signature", "05-requirements"),
    ("art_direction_signed", "Art direction signed", "signature",
     "06-brand-exploration"),
    ("round1_signed_off",   "Round 1 signed off",   "signature", "07-build"),
    ("round2_signed_off",   "Round 2 signed off",   "signature", "07-build"),
    ("final_invoice_paid",  "Final invoice paid",   "money",     "08-launch"),
    ("handover_accepted",   "Handover accepted",    "signature", "09-handover"),
]
GATE_KEYS = {g[0] for g in GATES}


def resolve_gates(con, eid: int) -> list:
    rows = {r["gate"]: r for r in con.execute(
        "SELECT * FROM engagement_gates WHERE engagement_id=?", (eid,))}
    # The brand stage is optional; its gate exists once the engagement
    # actually has brand work — filed documents or an explicit link — and
    # not before, so a week website is never blocked on a stage it skipped.
    has_brand = con.execute(
        "SELECT 1 FROM engagement_docs WHERE engagement_id=?"
        " AND stage='07-brand-exploration' LIMIT 1", (eid,)).fetchone()
    out = []
    for key, label, kind, stage in GATES:
        r = rows.get(key)
        active = key != "art_direction_signed" or bool(has_brand) or bool(r)
        passed_at, via, doc_title, signed_by = 0, "", "", ""
        if r and r["doc_id"]:
            d = con.execute(
                "SELECT d.title, s.signed_at, s.signer_name"
                " FROM documents d LEFT JOIN document_signatures s"
                "   ON s.document_id=d.id AND s.status='signed'"
                " WHERE d.id=? ORDER BY s.signed_at DESC LIMIT 1",
                (r["doc_id"],)).fetchone()
            if d:
                doc_title = d["title"]
                if d["signed_at"]:
                    passed_at, via = d["signed_at"], "signature"
                    signed_by = d["signer_name"] or ""
        if not passed_at and r and r["passed_at"]:
            passed_at, via = r["passed_at"], "manual"
        out.append({"gate": key, "label": label, "kind": kind,
                    "stage": stage, "active": active,
                    "passed_at": passed_at, "via": via,
                    "signed_by": signed_by,
                    "actor": r["actor"] if r else "",
                    "note": r["note"] if r else "",
                    "doc_id": r["doc_id"] if r else 0,
                    "has_payment_link": bool(r["stripe_session"]) if r else False,
                    "doc_title": doc_title})
    return out


def current_stage(gates: list) -> str:
    for g in gates:
        if g["active"] and not g["passed_at"]:
            return g["stage"]
    return "10-aftercare"


def earlier_open(gates: list, key: str) -> list:
    """The gates that should have passed before this one — the loud warning
    the plan asks for, not a hard block: real projects do occasionally take a
    deposit on a handshake, and the tool's job is to make that visible, not
    to forbid it."""
    out = []
    for g in gates:
        if g["gate"] == key:
            break
        if g["active"] and not g["passed_at"]:
            out.append(g["label"])
    return out


# ---------- the template registry: the kit folder, read live ----------

def side_of(text: str) -> str:
    """A template that says so is internal; the rest go to the client.

    The kit's internal documents carry it on their face ("Internal. Never
    send this to a client.") — deriving from that beats a hand-kept list that
    would drift the day a template is added.
    """
    return "internal" if "never send" in text[:500].lower() else "to_client"


def category_of(rel: str) -> str:
    n = rel.lower()
    if "contract" in n or "agreement" in n:
        return "contract"
    if "proposal" in n:
        return "proposal"
    return "other"


def template_title(text: str, rel: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return Path(rel).stem.replace("-", " ")


def scan_templates():
    if not KIT.is_dir():
        return []
    out = []
    for stage_dir in sorted(p for p in KIT.iterdir()
                            if p.is_dir() and re.match(r"\d\d-", p.name)):
        templates = []
        for f in sorted(stage_dir.rglob("*.md")):
            if f.name == "README.md":
                continue
            text = f.read_text()
            rel = str(f.relative_to(stage_dir))
            templates.append({
                "path": f"{stage_dir.name}/{rel}",
                "name": template_title(text, rel),
                "side": side_of(text),
                "category": category_of(rel),
            })
        out.append({"stage": stage_dir.name,
                    "client_stage": KIT_TO_CLIENT_STAGE.get(stage_dir.name,
                                                            stage_dir.name),
                    "templates": templates})
    return out


def template_path(rel: str) -> Path:
    """Resolve a template path and refuse anything outside the kit."""
    p = (KIT / rel).resolve()
    if not (p.is_file() and p.suffix == ".md"
            and str(p).startswith(str(KIT.resolve()) + "/")):
        raise HTTPException(404, "no such template")
    return p


# ---------- placeholders ----------

# The placeholder machinery lives with the vault (documents.py), because
# the vault renders and edits documents on every surface; this module reads
# the same functions so the two can never scan a document differently.
from .documents import (PLACEHOLDER, RESERVED_MARKERS,  # noqa: F401
                        _matches, fill, placeholders)


def suggested_fills(e) -> dict:
    """What the engagement record already knows. One source: the proposal and
    the status board cannot disagree about the number, because both read it
    from here."""
    today = time.strftime("%B %d, %Y").replace(" 0", " ")
    s = {"CLIENT": e["name"], "CLIENT NAME": e["name"], "DATE": today}
    if e["package"]:
        s["A / B / C"] = e["package"]
    if e["value_cents"]:
        s["X"] = f"{e['value_cents'] / 100:,.0f}"
    if e["approver_name"]:
        s["NAME"] = e["approver_name"]
        s["APPROVER"] = e["approver_name"]
        s["NAME, EMAIL"] = f"{e['approver_name']}, {e['approver_email']}"
    if e["launch_target"]:
        s["LAUNCH DATE"] = e["launch_target"]
        s["LAUNCH TARGET"] = e["launch_target"]
    return s


# ---------- engagements ----------

def binder_body(name: str, package: str, value_cents: int,
                client_poc_name: str, client_poc_email: str,
                internal_poc: str, originator: str,
                launch_target: str) -> str:
    """The binder's opening document. The title page names the five facts a
    binder pulled off a shelf must answer at a glance: whose it is, who to
    call on each side, who started it, and when. Pricing and lead sections
    appear only where the record has them."""
    from erp.backend.main import CFG
    brand = CFG.get("brand_name", "Business Control")
    today = time.strftime("%B %d, %Y").replace(" 0", " ")
    nl = "\n"
    dash = "—"
    poc = client_poc_name or dash
    if client_poc_email:
        poc += f" ({client_poc_email})"
    parts = [
        f"# {brand}",
        "",
        f"## Project binder — {name}",
        "",
        "| | |",
        "|---|---|",
        f"| Client | {name} |",
        f"| Client POC | {poc} |",
        f"| Internal POC | {internal_poc or dash} |",
        f"| Originator | {originator or dash} |",
        f"| Date | {today} |",
        "",
        "*Everything this project produces, in one place. This binder opens "
        "with who and what; every agreement, questionnaire and sign-off "
        "that follows is filed behind it, and the whole packet exports "
        "together — printed or as one PDF.*",
        "",
        "---",
        "",
        "## Introduction",
        "",
        "[INTRODUCTION — who they are, what we build, what done means]",
        "",
        "## What this binder holds",
        "",
        "| Stage | Papers |",
        "|---|---|",
        "| Consultation | How this works, and the written map of the stack |",
        "| Proposal | The proposal, and the option chosen in writing |",
        "| Agreement | The signed contract and the deposit record |",
        "| Kickoff | The questionnaires, checklists and project roadmap |",
        "| Requirements | The signed requirements |",
        "| Brand | Directions and the signed art direction *(when bought)* |",
        "| Build | Feedback rounds and change orders |",
        "| Launch & handover | The launch summary and the handover pack |",
    ]
    if package or value_cents:
        parts += ["", "## Pricing", "", "| | |", "|---|---|"]
        if package:
            parts.append(f"| Package | {package} |")
        if value_cents:
            parts.append(f"| Value | ${value_cents / 100:,.2f} |")
        parts.append("| Payment | Per the schedule in the agreement |")
    if client_poc_name or client_poc_email or launch_target:
        parts += ["", "## Lead information", "", "| | |", "|---|---|"]
        if client_poc_name or client_poc_email:
            parts.append(f"| Client POC | {poc} |")
        if launch_target:
            parts.append(f"| Launch target | {launch_target} |")
        parts.append("| One consolidated response per round | "
                     "Named in the agreement |")
    return nl.join(parts) + nl


def _create_binder(con, eid: int, e: dict, u) -> int:
    """One binder per client, shared by birth and backfill."""
    cur = con.execute(
        "INSERT INTO documents(title,category,party_kind,party_name,"
        " party_email,body,notes,status,confidential,uploaded_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (f"Project binder — {e['name']}"[:200], "other", "partner",
         e["name"][:120], e["approver_email"],
         binder_body(e["name"], e["package"], e["value_cents"],
                     e["approver_name"], e["approver_email"],
                     e["internal_poc"], e["originator"],
                     e["launch_target"]),
         "binder cover", "draft", 1, u["id"], time.time()))
    con.execute(
        "INSERT INTO engagement_docs(engagement_id,doc_id,stage,side,"
        " created_at) VALUES(?,?,?,?,?)",
        (eid, cur.lastrowid, "01-potential-customer", "to_client",
         time.time()))
    log(con, eid, u["name"], "project binder created")
    return cur.lastrowid


class EngBody(BaseModel):
    name: str = ""
    package: str = ""
    value_cents: int = 0
    approver_name: str = ""
    approver_email: str = ""
    launch_target: str = ""
    staging_url: str = ""
    live_url: str = ""
    notes: str = ""
    status: str = ""
    originator: str = ""
    internal_poc: str = ""
    content_pct: int = -1          # -1 = not sent; 0 is a real value
    week_note: str = "\x00"       # sentinel: absent, not cleared
    blockers: str = "\x00"


@router.get("/api/store/admin/engagements")
def list_engagements(u=Depends(admin_user), con=Depends(get_con)):
    rows = con.execute(
        "SELECT e.*,"
        " (SELECT COUNT(*) FROM engagement_docs d WHERE d.engagement_id=e.id)"
        "   AS docs,"
        " (SELECT COUNT(*) FROM engagement_docs d"
        "   JOIN document_signatures s ON s.document_id=d.doc_id"
        "   WHERE d.engagement_id=e.id AND s.status='signed') AS signed,"
        " (SELECT COUNT(*) FROM engagement_docs d"
        "   JOIN document_signatures s ON s.document_id=d.doc_id"
        "   WHERE d.engagement_id=e.id AND s.status IN ('sent','viewed'))"
        "   AS awaiting"
        " FROM engagements e ORDER BY e.status='active' DESC, e.updated_at DESC"
    ).fetchall()
    now = time.time()
    week = 7 * 86400
    out = []
    for r in rows:
        e = dict(r)
        e["stage"] = current_stage(resolve_gates(con, e["id"]))
        has_portal = bool(e["portal_token"])
        e["portal_url"] = (f"/engage/{e['portal_token']}"
                           if e["portal_token"] else "")
        e.pop("portal_token", None)
        # The weekly-rhythm checklist as columns. Derived here, once, so the
        # dashboard and anything else reading the API agree about what
        # "stale" means.
        warn = []
        if e["status"] == "active":
            if has_portal and now - (e["week_note_at"] or 0) > week:
                warn.append("roadmap stale — a quiet week still gets a note")
            if has_portal and e["portal_seen_at"] and \
                    now - e["portal_seen_at"] > 2 * week:
                warn.append("client hasn't looked in a fortnight")
            if e["awaiting"]:
                warn.append(f"{e['awaiting']} awaiting signature")
            if (e["blockers"] or "").strip():
                warn.append("blocked")
        e["warnings"] = warn
        out.append(e)
    return {"engagements": out, "kit_available": KIT.is_dir()}


def _resolve_poc(con, name: str, u) -> tuple:
    """(name, user_id, status). Naming yourself is accepted on the spot;
    naming a colleague makes it PENDING and tells them — being someone's
    internal POC is a job, and a job you haven't agreed to isn't yours yet.
    A name that matches no account is recorded as-is with nobody to ask."""
    name = (name or "").strip()[:120] or u["name"]
    row = con.execute("SELECT id FROM users WHERE lower(name)=lower(?)"
                      " AND active=1", (name,)).fetchone()
    if row is None:
        return name, 0, "accepted"
    if row["id"] == u["id"]:
        return name, row["id"], "accepted"
    return name, row["id"], "pending"


@router.post("/api/store/admin/engagements")
def create_engagement(body: EngBody, u=Depends(admin_user),
                      con=Depends(get_con)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "a client needs a name")
    slug = slugify(name)
    if con.execute("SELECT 1 FROM engagements WHERE slug=?",
                   (slug,)).fetchone():
        raise HTTPException(400, f"'{slug}' already exists")
    now = time.time()
    originator = (body.originator or "").strip()[:120] or u["name"]
    poc_name, poc_uid, poc_status = _resolve_poc(con, body.internal_poc, u)
    cur = con.execute(
        "INSERT INTO engagements(name,slug,package,value_cents,approver_name,"
        " approver_email,launch_target,staging_url,live_url,notes,status,"
        " originator,internal_poc,internal_poc_user_id,internal_poc_status,"
        " created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name[:120], slug, body.package.strip()[:40], body.value_cents,
         body.approver_name.strip()[:120], body.approver_email.strip()[:200],
         body.launch_target.strip()[:40], body.staging_url.strip()[:300],
         body.live_url.strip()[:300], body.notes.strip()[:2000],
         "active", originator, poc_name, poc_uid, poc_status, now, now))
    eid = cur.lastrowid
    log(con, eid, u["name"], f"engagement created: {name}")
    e = con.execute("SELECT * FROM engagements WHERE id=?", (eid,)).fetchone()
    binder_id = _create_binder(con, eid, e, u)
    con.commit()
    if poc_status == "pending":
        from erp.backend import notify
        notify.push(con, f"Internal POC for {name} — yours?",
                    f"{u['name']} named you internal POC. Open the client "
                    f"to accept or decline.", kind="engagement",
                    user_id=poc_uid)
    return {"id": eid, "slug": slug, "binder_doc_id": binder_id}


def _eng_or_404(con, eid: int):
    e = con.execute("SELECT * FROM engagements WHERE id=?", (eid,)).fetchone()
    if e is None:
        raise HTTPException(404, "no such engagement")
    return e


@router.patch("/api/store/admin/engagements/{eid}")
def edit_engagement(eid: int, body: EngBody, u=Depends(admin_user),
                    con=Depends(get_con)):
    e = _eng_or_404(con, eid)
    fields = {}
    for k in ("name", "package", "approver_name", "approver_email",
              "launch_target", "staging_url", "live_url", "notes", "status"):
        v = getattr(body, k).strip()
        if v and v != e[k]:
            fields[k] = v
    # Blockers and the week note must be CLEARABLE — "no blockers" is the
    # good news, and a sentinel keeps an absent field from wiping anything.
    if body.originator.strip() and body.originator.strip() != e["originator"]:
        fields["originator"] = body.originator.strip()[:120]
    poc_in = body.internal_poc.strip()
    if poc_in and poc_in.lower() != (e["internal_poc"] or "").lower():
        poc_name, poc_uid, poc_status = _resolve_poc(con, poc_in, u)
        fields["internal_poc"] = poc_name
        fields["internal_poc_user_id"] = poc_uid
        fields["internal_poc_status"] = poc_status
        if poc_status == "pending":
            from erp.backend import notify
            notify.push(con, f"Internal POC for {e['name']} — yours?",
                        f"{u['name']} named you internal POC. Open the "
                        f"client to accept or decline.", kind="engagement",
                        user_id=poc_uid)
    for k in ("week_note", "blockers"):
        v = getattr(body, k)
        if v != "\x00" and v.strip() != e[k]:
            fields[k] = v.strip()[:2000]
            if k == "week_note":
                fields["week_note_at"] = time.time()
    if body.value_cents and body.value_cents != e["value_cents"]:
        fields["value_cents"] = body.value_cents
    if body.content_pct >= 0 and body.content_pct != e["content_pct"]:
        fields["content_pct"] = max(0, min(100, body.content_pct))
    if fields.get("status") not in (None, "active", "closed"):
        raise HTTPException(400, "status is active or closed")
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE engagements SET {sets}, updated_at=? WHERE id=?",
                    (*fields.values(), time.time(), eid))
        log(con, eid, u["name"], "updated: " + ", ".join(fields))
        con.commit()
    return {"ok": True}


@router.get("/api/store/admin/engagements/templates")
def list_templates(u=Depends(admin_user)):
    return {"stages": scan_templates(), "kit_available": KIT.is_dir()}


@router.get("/api/store/admin/engagements/{eid}")
def engagement_detail(eid: int, u=Depends(admin_user), con=Depends(get_con)):
    e = _eng_or_404(con, eid)
    docs = []
    for r in con.execute(
            "SELECT ed.stage, ed.side, d.id, d.title, d.category, d.status,"
            " d.ext, d.filename, d.body,"
            " (SELECT COUNT(*) FROM document_signatures s"
            "   WHERE s.document_id=d.id AND s.status='signed') AS signed,"
            " (SELECT COUNT(*) FROM document_signatures s"
            "   WHERE s.document_id=d.id AND s.status IN ('sent','viewed'))"
            "   AS awaiting"
            " FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
            " WHERE ed.engagement_id=? ORDER BY ed.stage, d.created_at",
            (eid,)).fetchall():
        d = dict(r)
        body = d.pop("body") or ""
        d["has_body"] = bool(body.strip())
        # How much of the template is still a bracket. Shown on the row, so
        # "finished" is a number going to zero, not a feeling.
        d["blanks"] = len(placeholders(body)) if d["has_body"] else 0
        docs.append(d)
    events = con.execute(
        "SELECT at, actor, what FROM engagement_log WHERE engagement_id=?"
        " ORDER BY at DESC LIMIT 40", (eid,)).fetchall()
    gates = resolve_gates(con, eid)
    ej = dict(e)
    ej["portal_url"] = (f"/engage/{e['portal_token']}"
                        if e["portal_token"] else "")
    ej.pop("portal_token", None)
    dates = con.execute(
        "SELECT label, planned, actual, moved_because FROM engagement_dates"
        " WHERE engagement_id=? ORDER BY ord", (eid,)).fetchall()
    return {"engagement": ej,
            "dates": [dict(r) for r in dates],
            "docs": docs,
            "gates": gates,
            "current_stage": current_stage(gates),
            "stages": scan_templates(),
            "log": [dict(r) for r in events]}


@router.get("/api/store/admin/engagements/{eid}/template")
def template_detail(eid: int, path: str, u=Depends(admin_user),
                    con=Depends(get_con)):
    e = _eng_or_404(con, eid)
    text = template_path(path).read_text()
    toks = placeholders(text)
    sug = suggested_fills(e)
    return {"path": path, "name": template_title(text, path),
            "side": side_of(text), "category": category_of(path),
            "placeholders": toks,
            "suggested": {t: sug[t] for t in toks if t in sug}}


class GenerateBody(BaseModel):
    template_path: str
    fills: dict = {}
    title: str = ""
    side: str = ""


@router.post("/api/store/admin/engagements/{eid}/docs")
def generate_doc(eid: int, body: GenerateBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    e = _eng_or_404(con, eid)
    p = template_path(body.template_path)
    text = p.read_text()
    stage = body.template_path.split("/", 1)[0]
    if stage not in KIT_TO_CLIENT_STAGE:
        raise HTTPException(400, "template is not in a stage folder")
    side = body.side or side_of(text)
    if side not in ("to_client", "internal"):
        raise HTTPException(400, "side is to_client or internal")

    filled = fill(text, {**suggested_fills(e), **(body.fills or {})})
    remaining = placeholders(filled)
    title = body.title.strip()
    if not title:
        # From the FILLED text, so "Proposal — [CLIENT NAME]" becomes
        # "Proposal — Acme"; any bracket that survived is stripped rather
        # than shipped in a title, and the client name is appended only when
        # the fill didn't already put it there.
        t = re.sub(r"\s*[—–-]?\s*\[[^\]]*\]", "",
                   template_title(filled, body.template_path)).strip(" —–-")
        title = t if e["name"].lower() in t.lower() else f"{t} — {e['name']}"

    cur = con.execute(
        "INSERT INTO documents(title,category,party_kind,party_name,"
        " party_email,body,notes,status,confidential,uploaded_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (title[:200], category_of(body.template_path), "partner",
         e["name"][:120], e["approver_email"], filled,
         f"Generated from the kit: {body.template_path}",
         "draft" if remaining else "active", 1, u["id"], time.time()))
    doc_id = cur.lastrowid
    con.execute(
        "INSERT INTO engagement_docs(engagement_id,doc_id,stage,side,"
        " created_at) VALUES(?,?,?,?,?)",
        (eid, doc_id, stage, side, time.time()))
    log(con, eid, u["name"],
        f"generated '{title}' from {body.template_path}"
        + (f" ({len(remaining)} blanks left)" if remaining else ""))
    con.commit()
    return {"doc_id": doc_id, "unfilled": remaining, "side": side}


@router.get("/api/store/admin/engagements/{eid}/docs/{did}/blanks")
def doc_blanks(eid: int, did: int, u=Depends(admin_user),
               con=Depends(get_con)):
    """The brackets still unfilled on a generated document, with the same
    suggestions generation had — so finishing a document is the same form
    as starting one, just shorter each time."""
    e = _eng_or_404(con, eid)
    r = con.execute(
        "SELECT d.body, d.title FROM engagement_docs ed"
        " JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND ed.doc_id=?", (eid, did)).fetchone()
    if r is None or not (r["body"] or "").strip():
        raise HTTPException(404, "no authored document there")
    toks = placeholders(r["body"])
    sug = suggested_fills(e)
    return {"title": r["title"], "placeholders": toks,
            "suggested": {t: sug[t] for t in toks if t in sug}}


@router.get("/api/store/admin/engagements/{eid}/docs/{did}/editable")
def doc_editable(eid: int, did: int, u=Depends(admin_user),
                 con=Depends(get_con)):
    """The document as its own form, scoped to this client — the rendering
    and the rules live with the vault, so this route only adds the wall
    (the document must be filed here) and the client's suggestions."""
    e = _eng_or_404(con, eid)
    if not con.execute("SELECT 1 FROM engagement_docs WHERE engagement_id=?"
                       " AND doc_id=?", (eid, did)).fetchone():
        raise HTTPException(404, "not filed under this client")
    from . import documents as vault
    d = vault._editable_doc_or_refuse(con, did)
    from fastapi.responses import HTMLResponse as _HR
    return _HR(vault.render_editable(d, suggested_fills(e)))


class FillBody(BaseModel):
    fills: dict = {}


@router.post("/api/store/admin/engagements/{eid}/docs/{did}/fill")
def doc_fill(eid: int, did: int, body: FillBody, u=Depends(admin_user),
             con=Depends(get_con)):
    _eng_or_404(con, eid)
    r = con.execute(
        "SELECT d.body, d.title FROM engagement_docs ed"
        " JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND ed.doc_id=?", (eid, did)).fetchone()
    if r is None or not (r["body"] or "").strip():
        raise HTTPException(404, "no authored document there")
    signed = con.execute(
        "SELECT COUNT(*) n FROM document_signatures WHERE document_id=?"
        " AND status='signed'", (did,)).fetchone()["n"]
    if signed:
        raise HTTPException(400, "this document has been signed — its text "
                                 "is what was attested to. Supersede it "
                                 "rather than editing it")
    filled = fill(r["body"], body.fills or {})
    remaining = placeholders(filled)
    con.execute("UPDATE documents SET body=?, status=? WHERE id=?",
                (filled, "draft" if remaining else "active", did))
    log(con, eid, u["name"],
        f"filled blanks on '{r['title']}'"
        + (f" ({len(remaining)} left)" if remaining else " — complete"))
    con.commit()
    return {"unfilled": remaining}


class AttachBody(BaseModel):
    doc_id: int
    stage: str
    side: str = "to_client"


@router.post("/api/store/admin/engagements/{eid}/attach")
def attach_doc(eid: int, body: AttachBody, u=Depends(admin_user),
               con=Depends(get_con)):
    """File an existing vault document — an upload, a countersigned PDF —
    under a stage of this engagement."""
    e = _eng_or_404(con, eid)
    if body.stage not in KIT_TO_CLIENT_STAGE:
        raise HTTPException(400, "unknown stage")
    if body.side not in ("to_client", "internal"):
        raise HTTPException(400, "side is to_client or internal")
    d = con.execute("SELECT title FROM documents WHERE id=?",
                    (body.doc_id,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such document")
    con.execute(
        "INSERT OR REPLACE INTO engagement_docs(engagement_id,doc_id,stage,"
        " side,created_at) VALUES(?,?,?,?,?)",
        (eid, body.doc_id, body.stage, body.side, time.time()))
    log(con, eid, u["name"], f"filed '{d['title']}' under {body.stage}")
    con.commit()
    return {"ok": True}


class GateBody(BaseModel):
    doc_id: int = 0
    note: str = ""


@router.post("/api/store/admin/engagements/{eid}/gates/{gate}")
def pass_gate(eid: int, gate: str, body: GateBody, u=Depends(admin_user),
              con=Depends(get_con)):
    """Link the document whose signature passes the gate, or — for the money
    gates, and for evidence that lives elsewhere — confirm by hand.

    A hand-passed signature gate requires a note saying where the evidence
    is filed. That is the status board's own column, enforced: the point of
    a gate is that in month four you can point at something."""
    e = _eng_or_404(con, eid)
    if gate not in GATE_KEYS:
        raise HTTPException(404, "no such gate")
    kind = next(g[2] for g in GATES if g[0] == gate)

    if body.doc_id:
        # Only this engagement's documents can carry its gates — linking an
        # unrelated signature would make the gate attest to nothing.
        if not con.execute(
                "SELECT 1 FROM engagement_docs WHERE engagement_id=?"
                " AND doc_id=?", (eid, body.doc_id)).fetchone():
            raise HTTPException(400, "that document isn't filed under this "
                                     "client — attach it first")
        con.execute(
            "INSERT INTO engagement_gates(engagement_id,gate,doc_id,actor,"
            " note) VALUES(?,?,?,?,?) ON CONFLICT(engagement_id,gate) DO"
            " UPDATE SET doc_id=excluded.doc_id, note=excluded.note",
            (eid, gate, body.doc_id, u["name"], body.note.strip()[:300]))
        what = f"gate '{gate}' linked to document #{body.doc_id}"
    else:
        if kind == "signature" and not body.note.strip():
            raise HTTPException(
                400, "a signature gate passed by hand needs a note saying "
                     "where the evidence is filed")
        con.execute(
            "INSERT INTO engagement_gates(engagement_id,gate,passed_at,"
            " actor,note) VALUES(?,?,?,?,?) ON CONFLICT(engagement_id,gate)"
            " DO UPDATE SET passed_at=excluded.passed_at,"
            " actor=excluded.actor, note=excluded.note",
            (eid, gate, time.time(), u["name"], body.note.strip()[:300]))
        what = f"gate '{gate}' confirmed by hand"

    gates = resolve_gates(con, eid)
    warnings = earlier_open(gates, gate)
    if warnings:
        what += f" — out of order, still open: {', '.join(warnings)}"
    log(con, eid, u["name"], what)
    con.commit()
    g = next(x for x in gates if x["gate"] == gate)
    if g["passed_at"]:
        # Through the one fan-out — webhooks, Discord and the integrations
        # all hear it, and none of them can fail the gate it reports.
        from .api import fire_webhooks
        fire_webhooks("gate.passed", {
            "id": eid, "client": e["name"], "gate": g["label"],
            "warnings": ", ".join(warnings)})
    return {"gate": g, "current_stage": current_stage(gates),
            "warnings": warnings}


@router.delete("/api/store/admin/engagements/{eid}/gates/{gate}")
def reopen_gate(eid: int, gate: str, u=Depends(admin_user),
                con=Depends(get_con)):
    """Undo a link or a hand-pass. The signed document, if any, stays in the
    vault untouched — reopening a gate never destroys evidence."""
    _eng_or_404(con, eid)
    if gate not in GATE_KEYS:
        raise HTTPException(404, "no such gate")
    con.execute("DELETE FROM engagement_gates WHERE engagement_id=?"
                " AND gate=?", (eid, gate))
    log(con, eid, u["name"], f"gate '{gate}' reopened")
    con.commit()
    gates = resolve_gates(con, eid)
    return {"current_stage": current_stage(gates)}


class DatesBody(BaseModel):
    dates: list = []


@router.put("/api/store/admin/engagements/{eid}/dates")
def set_dates(eid: int, body: DatesBody, u=Depends(admin_user),
              con=Depends(get_con)):
    """The dates that matter, with planned/actual/moved-because — replaced
    whole, so the table always reads top to bottom in the order given."""
    _eng_or_404(con, eid)
    rows = []
    for i, d in enumerate(body.dates[:40]):
        label = str(d.get("label", "")).strip()
        if not label:
            continue
        rows.append((eid, label[:120], str(d.get("planned", "")).strip()[:40],
                     str(d.get("actual", "")).strip()[:40],
                     str(d.get("moved_because", "")).strip()[:200], i))
    con.execute("DELETE FROM engagement_dates WHERE engagement_id=?", (eid,))
    con.executemany(
        "INSERT INTO engagement_dates(engagement_id,label,planned,actual,"
        " moved_because,ord) VALUES(?,?,?,?,?,?)", rows)
    log(con, eid, u["name"], f"dates updated ({len(rows)} rows)")
    con.commit()
    return {"ok": True, "count": len(rows)}


@router.post("/api/store/admin/engagements/{eid}/portal")
def portal_create(eid: int, request: Request, u=Depends(admin_user),
                  con=Depends(get_con)):
    """Create — or rotate, which is the same act — the client's link.

    Rotation is revocation with a forwarding address: the old link dies the
    moment a new one exists, so a link that leaked with a forwarded email
    is one click from worthless."""
    e = _eng_or_404(con, eid)
    token = secrets.token_urlsafe(24)
    con.execute("UPDATE engagements SET portal_token=?, updated_at=?"
                " WHERE id=?", (token, time.time(), eid))
    log(con, eid, u["name"],
        "portal link rotated" if e["portal_token"] else "portal link created")
    con.commit()
    base = str(request.base_url).rstrip("/")
    return {"url": f"{base}/engage/{token}"}


@router.delete("/api/store/admin/engagements/{eid}/portal")
def portal_revoke(eid: int, u=Depends(admin_user), con=Depends(get_con)):
    _eng_or_404(con, eid)
    con.execute("UPDATE engagements SET portal_token='', updated_at=?"
                " WHERE id=?", (time.time(), eid))
    log(con, eid, u["name"], "portal link revoked")
    con.commit()
    return {"ok": True}


class PayLinkBody(BaseModel):
    amount_cents: int = 0


@router.post("/api/store/admin/engagements/{eid}/gates/{gate}/payment-link")
def gate_payment_link(eid: int, gate: str, body: PayLinkBody,
                      request: Request, u=Depends(admin_user),
                      con=Depends(get_con)):
    """A Stripe checkout link for a money gate — the deposit or the final
    invoice. The link is how the money arrives; the gate still passes by
    verification, and manual confirmation stays for cheques and transfers."""
    e = _eng_or_404(con, eid)
    kind = dict((g[0], g[2]) for g in GATES).get(gate)
    if kind != "money":
        raise HTTPException(400, "payment links are for the money gates")
    from erp.backend import payments
    from erp.backend.main import CFG
    if not payments.enabled(CFG):
        raise HTTPException(400, "no Stripe key configured — confirm the "
                                 "payment manually when it arrives")
    amount = body.amount_cents or (
        e["value_cents"] // 2 if gate == "deposit_cleared" else 0)
    if amount <= 0:
        raise HTTPException(400, "an amount is required")
    label = ("Deposit" if gate == "deposit_cleared" else "Final invoice")         + f" — {e['name']}"
    base = str(request.base_url).rstrip("/")
    out = payments.create_simple_checkout(
        CFG, label, amount, f"eng-{eid}-{gate}", f"{base}/")
    con.execute(
        "INSERT INTO engagement_gates(engagement_id,gate,stripe_session,"
        " actor) VALUES(?,?,?,?) ON CONFLICT(engagement_id,gate) DO UPDATE"
        " SET stripe_session=excluded.stripe_session",
        (eid, gate, out["id"], u["name"]))
    log(con, eid, u["name"],
        f"payment link created for '{gate}' — ${amount / 100:,.2f}")
    con.commit()
    return {"url": out["url"], "amount_cents": amount}


@router.post("/api/store/admin/engagements/{eid}/gates/{gate}/payment-check")
def gate_payment_check(eid: int, gate: str, u=Depends(admin_user),
                       con=Depends(get_con)):
    """Ask Stripe whether the link's session was paid; if so, the gate
    passes with Stripe named as the actor — verified, not vouched for."""
    e = _eng_or_404(con, eid)
    r = con.execute("SELECT * FROM engagement_gates WHERE engagement_id=?"
                    " AND gate=?", (eid, gate)).fetchone()
    if r is None or not r["stripe_session"]:
        raise HTTPException(400, "no payment link exists for this gate")
    if r["passed_at"]:
        return {"paid": True, "already": True}
    from erp.backend import payments
    from erp.backend.main import CFG
    paid = payments.session_paid(CFG, r["stripe_session"])
    if paid:
        con.execute(
            "UPDATE engagement_gates SET passed_at=?, actor='Stripe',"
            " note=? WHERE id=?",
            (time.time(), f"paid via checkout {r['stripe_session'][:24]}",
             r["id"]))
        gates_now = resolve_gates(con, eid)
        log(con, eid, "Stripe", f"gate '{gate}' passed — payment verified")
        con.commit()
        from .api import fire_webhooks
        g = next(x for x in gates_now if x["gate"] == gate)
        fire_webhooks("gate.passed", {
            "id": eid, "client": e["name"], "gate": g["label"],
            "warnings": ", ".join(earlier_open(gates_now, gate))})
        return {"paid": True}
    return {"paid": False,
            "detail": "not paid yet — check again once they've clicked "
                      "through, or confirm manually if it arrived by "
                      "transfer"}


def _dropbox_connected(con) -> bool:
    from erp.backend import integrations
    return bool(integrations.creds(con, "dropbox"))


@router.delete("/api/store/admin/engagements/{eid}/docs/{did}")
def unfile_doc(eid: int, did: int, u=Depends(admin_user),
               con=Depends(get_con)):
    """Take a document out of this client's folder — the vault keeps it.
    Deleting from the vault is the other door (and archives when signed);
    unfiling is for the mis-filed and the superseded."""
    _eng_or_404(con, eid)
    r = con.execute(
        "SELECT d.title FROM engagement_docs ed JOIN documents d"
        " ON d.id=ed.doc_id WHERE ed.engagement_id=? AND ed.doc_id=?",
        (eid, did)).fetchone()
    if r is None:
        raise HTTPException(404, "not filed under this client")
    con.execute("DELETE FROM engagement_docs WHERE engagement_id=?"
                " AND doc_id=?", (eid, did))
    con.execute("UPDATE engagement_gates SET doc_id=0 WHERE engagement_id=?"
                " AND doc_id=?", (eid, did))
    log(con, eid, u["name"], f"unfiled '{r['title']}' — kept in the vault")
    con.commit()
    return {"ok": True}


# ---------- the client folder: generated, never maintained ----------

def safe_name(s: str) -> str:
    return re.sub(r"[^\w.-]+", "-", s).strip("-")[:80] or "document"


def _export_entries(con, eid: int, side: str):
    """(relative path, bytes) pairs for one engagement's folder tree."""
    q = ("SELECT ed.stage, ed.side, d.* FROM engagement_docs ed"
         " JOIN documents d ON d.id=ed.doc_id WHERE ed.engagement_id=?")
    args = [eid]
    if side != "all":
        q += " AND ed.side=?"
        args.append(side)
    from . import documents as vault
    for r in con.execute(q + " ORDER BY ed.stage", args).fetchall():
        cstage = KIT_TO_CLIENT_STAGE.get(r["stage"], r["stage"])
        folder = f"{cstage}/{'to-client' if r['side'] == 'to_client' else 'internal'}"
        stem = safe_name(r["title"])
        if r["ext"]:
            p = vault.doc_path(r)
            if p.exists():
                yield f"{folder}/{safe_name(r['filename'] or stem)}", p.read_bytes()
        if (r["body"] or "").strip():
            yield f"{folder}/{stem}.md", r["body"].encode()
            # The PDF beside it: the .md is for editing, the .pdf is for
            # sending — a bundle a client can open needs no explanation.
            from . import documents as vault
            from . import pdfgen
            try:
                yield f"{folder}/{stem}.pdf", pdfgen.doc_pdf(
                    r["title"], r["body"],
                    signatures=vault.signed_rows(con, r["id"]))
            except Exception:
                pass          # a render bug must not sink the whole export
        sigs = con.execute(
            "SELECT signer_name, signer_email, role, status, signed_at,"
            " ip, doc_sha256 FROM document_signatures WHERE document_id=?"
            " AND status IN ('signed','declined')", (r["id"],)).fetchall()
        if sigs:
            yield (f"{folder}/{stem}-signatures.json",
                   json.dumps([dict(s) for s in sigs], indent=1).encode())


def _status_readme(e, docs) -> str:
    by_stage = {}
    for d in docs:
        by_stage.setdefault(d["stage"], []).append(d)
    lines = [f"# {e['name']}", "",
             f"**Slug:** `{e['slug']}` · **Package:** {e['package'] or '—'}"
             f" · **Value:** ${e['value_cents'] / 100:,.2f}",
             f"**Approver:** {e['approver_name'] or '—'}"
             f" · **Launch target:** {e['launch_target'] or '—'}", "",
             f"Exported from Business Control on"
             f" {time.strftime('%Y-%m-%d %H:%M')}. This folder is generated"
             f" from the document vault — the vault is the record; regenerate"
             f" rather than editing here.", "",
             "| Stage | Document | Side | Signatures |", "|---|---|---|---|"]
    for stage in sorted(by_stage):
        for d in by_stage[stage]:
            state = (f"{d['signed']} signed" if d["signed"] else
                     f"{d['awaiting']} awaiting" if d["awaiting"] else "—")
            lines.append(
                f"| {KIT_TO_CLIENT_STAGE.get(stage, stage)} | {d['title']} |"
                f" {'to client' if d['side'] == 'to_client' else 'internal'} |"
                f" {state} |")
    return "\n".join(lines) + "\n"


@router.post("/api/store/admin/engagements/{eid}/export")
def export_folder(eid: int, u=Depends(admin_user), con=Depends(get_con)):
    """Write the per-client folder tree to data/exports/clients/{slug}/ —
    both sides, walls intact, regenerated from scratch each time so a stale
    file from a previous export can't linger as if current."""
    e = _eng_or_404(con, eid)
    docs = engagement_detail(eid, u, con)["docs"]
    root = EXPORT_ROOT / e["slug"]
    if root.exists():
        shutil.rmtree(root)
    files = []
    for rel, data in _export_entries(con, eid, "all"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        files.append(rel)
    readme = _status_readme(e, docs)
    (root / "README.md").write_text(readme)
    log(con, eid, u["name"], f"exported folder ({len(files)} files)")
    con.commit()

    # File the same tree to Dropbox when it's connected — the folder
    # convention becomes the filing format. Off-thread, logging its outcome
    # into the engagement's activity: a cloud outage must never fail the
    # local export, but a silent non-filing would read as filed.
    from erp.backend import db as erp_db
    from erp.backend import integrations
    entries = [(rel, (root / rel).read_bytes()) for rel in files]
    entries.append(("README.md", readme.encode()))
    slug = e["slug"]

    def file_to_dropbox():
        con2 = erp_db.connect()
        try:
            sent = 0
            detail = "not connected"
            for rel, blob in entries:
                ok2, detail = integrations.dropbox_put(
                    con2, f"/business-control/clients/{slug}/{rel}", blob)
                if not ok2:
                    break
                sent += 1
            if sent:
                log(con2, eid, "Dropbox",
                    f"filed {sent}/{len(entries)} export files"
                    + ("" if sent == len(entries) else f" — then: {detail}"))
            elif detail != "not connected":
                log(con2, eid, "Dropbox", f"filing failed: {detail}")
            con2.commit()
        except Exception:
            pass
        finally:
            con2.close()

    import threading
    threading.Thread(target=file_to_dropbox, daemon=True).start()
    return {"root": str(root), "files": sorted(files),
            "dropbox": "filing in the background"
            if _dropbox_connected(con) else "not connected"}


def _binder_sections(con, eid: int) -> tuple:
    """(sections, files): the whole binder, printable and complete.

    The cover opens it; a contents page mirrors the client's own screen —
    the stages as sections, each with its gates and their state, and every
    paper beneath. Then the documents themselves: the generated ones with
    their signatures, and for every client-side template NOT yet generated,
    the blank form — brackets, write-in lines and checkboxes intact — so a
    printed binder can be filled with a pen. One gatherer behind the PDF
    and the HTML preview, so they can never disagree."""
    from . import documents as vault
    e = con.execute("SELECT * FROM engagements WHERE id=?", (eid,)).fetchone()
    rows = con.execute(
        "SELECT ed.stage, d.* FROM engagement_docs ed"
        " JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND ed.side='to_client'"
        " ORDER BY ed.stage, d.created_at", (eid,)).fetchall()
    authored = [r for r in rows if (r["body"] or "").strip()]
    files = [r for r in rows if not (r["body"] or "").strip() and r["ext"]]
    cover = [r for r in authored if (r["notes"] or "") == "binder cover"]
    if not cover:
        return [], files
    authored = [r for r in authored if (r["notes"] or "") != "binder cover"]

    # which templates already became documents, by the path in their notes
    generated_paths = {
        (r["notes"] or "").replace("Generated from the kit: ", "").strip()
        for r in rows if (r["notes"] or "").startswith("Generated from")}
    tpl_by_stage = {}
    for st in scan_templates():
        tpl_by_stage[st["stage"]] = [
            t for t in st["templates"]
            if t["side"] == "to_client" and t["path"] not in generated_paths]

    gates = resolve_gates(con, eid)
    stage_order = list(KIT_TO_CLIENT_STAGE)
    by_stage = {}
    for r in authored:
        by_stage.setdefault(r["stage"], []).append(r)
    file_stage = {}
    for r in files:
        file_stage.setdefault(r["stage"], []).append(r)

    def gate_line(g):
        if g["passed_at"]:
            who = g["signed_by"] or g["actor"] or ""
            how = "signed" if g["via"] == "signature" else "confirmed"
            return (f"**Gate: {g['label']}** — {how}"
                    + (f" by {who}" if who else ""))
        if g["doc_id"]:
            return f"**Gate: {g['label']}** — awaiting signature"
        return f"**Gate: {g['label']}** — open"

    # the contents, and the section list, walk the stages together
    sections = [{"title": cover[0]["title"], "body": cover[0]["body"],
                 "signatures": vault.signed_rows(con, cover[0]["id"]),
                 "pending": vault.pending_rows(con, cover[0]["id"])}]
    toc = []
    ordered_docs = []
    for kit_stage in stage_order:
        cstage = KIT_TO_CLIENT_STAGE[kit_stage]
        stage_docs = by_stage.get(kit_stage, [])
        stage_tpls = tpl_by_stage.get(kit_stage, [])
        stage_files = file_stage.get(kit_stage, [])
        stage_gates = [g for g in gates
                       if g["stage"] == cstage and g["active"]]
        if not (stage_docs or stage_tpls or stage_files or stage_gates):
            continue
        label = STAGE_LABELS.get(cstage, cstage)
        toc.append("")
        toc.append(f"## {label}")
        toc.append("")
        for g in stage_gates:
            toc.append(gate_line(g))
            toc.append("")
        # consecutive numbered lines form ONE list, so the browser and the
        # PDF number them 1..k within the stage — binder numbering, not a
        # column of stray "1."s
        for r in stage_docs:
            sigs = vault.signed_rows(con, r["id"])
            state = (f"signed by {sigs[-1]['signer_name']}" if sigs
                     else "awaiting signature"
                     if vault.pending_rows(con, r["id"]) else "draft")
            toc.append(f"1. **{r['title']}** — {state}")
            ordered_docs.append({"title": r["title"], "body": r["body"],
                                 "signatures": sigs,
                                 "pending": vault.pending_rows(con, r["id"])})
        for t in stage_tpls:
            toc.append(f"1. {t['name']} — *blank form, print and fill*")
            try:
                body = template_path(t["path"]).read_text()
            except Exception:
                toc.pop()
                continue
            ordered_docs.append({"title": t["name"], "body": body})
        for r in stage_files:
            toc.append(f"1. *{r['title']}* — attachment, filed beside "
                       f"this binder")
    sections.append({"title": "In this binder",
                     "body": "\n".join(toc).strip()})
    sections.extend(ordered_docs)
    return sections, files


@router.post("/api/store/admin/engagements/{eid}/binder")
def binder_backfill(eid: int, u=Depends(admin_user), con=Depends(get_con)):
    """Create the binder for a client that predates binder-at-birth. One
    per client — asking again returns the one that exists."""
    e = _eng_or_404(con, eid)
    row = con.execute(
        "SELECT d.id FROM engagement_docs ed JOIN documents d"
        " ON d.id=ed.doc_id WHERE ed.engagement_id=?"
        " AND d.notes='binder cover'", (eid,)).fetchone()
    if row:
        return {"binder_doc_id": row["id"], "created": False}
    did = _create_binder(con, eid, e, u)
    con.commit()
    return {"binder_doc_id": did, "created": True}


@router.post("/api/store/admin/engagements/{eid}/poc/{verdict}")
def poc_verdict(eid: int, verdict: str, u=Depends(admin_user),
                con=Depends(get_con)):
    """The named internal POC accepts or declines the job. Declining tells
    the originator — silence is the one outcome that helps nobody."""
    e = _eng_or_404(con, eid)
    if verdict not in ("accept", "decline"):
        raise HTTPException(404, "accept or decline")
    if e["internal_poc_user_id"] != u["id"]:
        raise HTTPException(403, "only the named internal POC can answer")
    if e["internal_poc_status"] != "pending":
        return {"status": e["internal_poc_status"]}
    status = "accepted" if verdict == "accept" else "declined"
    con.execute("UPDATE engagements SET internal_poc_status=?, updated_at=?"
                " WHERE id=?", (status, time.time(), eid))
    log(con, eid, u["name"], f"internal POC {status}")
    con.commit()
    if status == "declined":
        from erp.backend import notify
        orig = con.execute("SELECT id FROM users WHERE lower(name)=lower(?)"
                           " AND active=1", (e["originator"],)).fetchone()
        notify.push(con, f"{u['name']} declined internal POC for {e['name']}",
                    "Pick another internal POC on the client's Edit form.",
                    kind="engagement",
                    user_id=orig["id"] if orig else None)
    return {"status": status}


@router.get("/api/store/admin/engagements/{eid}/binder.html")
def binder_html(eid: int, u=Depends(admin_user), con=Depends(get_con)):
    """The binder as a page — for the in-app preview, where an embedded PDF
    is a lottery. Same sections as the PDF, from the same gatherer."""
    e = _eng_or_404(con, eid)
    from . import documents as vault
    sections, _ = _binder_sections(con, eid)
    if not sections:
        raise HTTPException(404, "nothing to bind yet")
    inner = "".join(
        f'<div class="binder-doc">'
        f'<h1>{sect.esc(sec["title"])}</h1>'
        f'{vault.md_html(sec["body"])}'
        f'{vault.signatures_html(sec.get("signatures") or [])}'
        f'{vault.pending_html(sec.get("pending") or [])}'
        f"</div>" for sec in sections)
    from .api import FONT_LINK
    return HTMLResponse(
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,"
        f" initial-scale=1\"><title>{sect.esc(e['name'])} — binder</title>"
        f"{FONT_LINK}<style>"
        f"body{{font-family:'Inter',system-ui,sans-serif;color:#1b181f;"
        f"line-height:1.6;max-width:760px;margin:0 auto;padding:28px 24px;"
        f"background:#f2efe9}}"
        f"h1,h2,h3,h4{{font-family:'Fraunces',Georgia,serif}}"
        f"table{{border-collapse:collapse;width:100%}}"
        f"td,th{{border-top:1px solid #e9e4dc;padding:6px 10px 6px 0;"
        f"text-align:left}}"
        f"blockquote{{border-left:3px solid #e9e4dc;padding-left:14px;"
        f"color:#5d5768;margin:10px 0}}"
        f".binder-doc{{background:#fff;border-radius:12px;"
        f"padding:34px 38px;margin:0 0 22px;"
        f"box-shadow:0 2px 10px rgba(20,15,30,.07)}}"
        f"</style></head><body>{inner}</body></html>")


@router.get("/api/store/admin/engagements/{eid}/binder.pdf")
def binder_pdf_route(eid: int, u=Depends(admin_user), con=Depends(get_con)):
    """The whole packet as one book, from the same gatherer as the HTML
    preview. Uploaded files (scans) are listed in the contents but travel
    beside the binder in the export — a PDF made of markdown can't swallow
    a photograph of paper."""
    e = _eng_or_404(con, eid)
    from . import pdfgen
    sections, _ = _binder_sections(con, eid)
    if not sections:
        raise HTTPException(404, "nothing to bind yet")
    log(con, eid, u["name"], f"binder PDF ({len(sections)} sections)")
    con.commit()
    return Response(pdfgen.binder_pdf(sections),
                    media_type="application/pdf", headers={
        "Content-Disposition":
            f'inline; filename="{e["slug"]}-binder.pdf"'})


@router.get("/api/store/admin/engagements/{eid}/export.zip")
def export_zip(eid: int, side: str = "to_client", u=Depends(admin_user),
               con=Depends(get_con)):
    """The bundle. Defaults to the client's side of the wall only — sending
    everything is a decision, made by asking for 'all', never an accident."""
    e = _eng_or_404(con, eid)
    if side not in ("to_client", "all"):
        raise HTTPException(400, "side is to_client or all")
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, data in _export_entries(con, eid, side):
            z.writestr(f"{e['slug']}/{rel}", data)
            n += 1
    if not n:
        raise HTTPException(404, "nothing to bundle yet")
    kind = "client-bundle" if side == "to_client" else "full-archive"
    log(con, eid, u["name"], f"downloaded {kind} ({n} files)")
    con.commit()
    return Response(buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition":
            f'attachment; filename="{e["slug"]}-{kind}.zip"'})


# ---------- public: the client portal ----------
# One revocable link per engagement, following the supplier-portal precedent:
# the link carries its own token and needs no account. Everything on it is
# drawn from the same rows the ERP reads — gates, dates, documents — so the
# roadmap the client sees cannot drift from reality, because it IS the
# reality. And the wall holds by construction: every query on these routes
# filters side='to_client', so an internal document isn't withheld — it is
# unreachable.

def _portal_or_404(con, token: str):
    if not token or len(token) < 10:
        raise HTTPException(404, "this link is no longer valid")
    e = con.execute("SELECT * FROM engagements WHERE portal_token=?",
                    (token,)).fetchone()
    if e is None:
        raise HTTPException(404, "this link is no longer valid")
    return e


def _portal_docs(con, eid: int):
    return con.execute(
        "SELECT ed.stage, d.id, d.title, d.ext, d.notes,"
        " (SELECT COUNT(*) FROM document_signatures s"
        "   WHERE s.document_id=d.id AND s.status='signed') AS signed,"
        " (SELECT s.token FROM document_signatures s"
        "   WHERE s.document_id=d.id AND s.status IN ('sent','viewed')"
        "   ORDER BY s.sent_at DESC LIMIT 1) AS sign_token"
        " FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND ed.side='to_client'"
        " ORDER BY ed.stage, d.created_at", (eid,)).fetchall()


STAGE_LABELS = {
    "01-consultation": "Consultation", "02-proposal": "Proposal",
    "03-agreement": "Agreement", "04-kickoff": "Kickoff",
    "05-requirements": "Requirements",
    "06-brand-exploration": "Brand exploration", "07-build": "Build",
    "08-launch": "Launch", "09-handover": "Handover",
    "10-aftercare": "Aftercare",
}

DIRECTION_MARK = "portal-direction-choice"

PORTAL_CSS = """
:root{--ink:#1b181f;--ink2:#5d5768;--ink3:#8b8496;--bg:#fbf9f6;
  --card:#fff;--line:#e9e4dc;--accent:#6c00bf;--ok:#2e7d47;--warn:#a05a00}
*{box-sizing:border-box;margin:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);
  color:var(--ink);line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:780px;margin:0 auto;padding:36px 20px 80px}
h1{font-family:'Fraunces',Georgia,serif;font-size:28px;font-weight:600}
h2{font-family:'Fraunces',Georgia,serif;font-size:20px;font-weight:600;
  margin:34px 0 10px}
.meta{color:var(--ink2);font-size:14px;margin-top:4px}
.card{background:var(--card);border:1px solid var(--line);
  border-radius:14px;padding:18px 20px;margin-top:12px}
.pill{display:inline-block;font-size:12px;font-weight:600;
  padding:3px 10px;border-radius:99px;background:#f1ecf7;color:var(--accent)}
.pill.ok{background:#e8f3ec;color:var(--ok)}
.pill.warn{background:#faf0e0;color:var(--warn)}
.gate{display:flex;gap:12px;align-items:baseline;padding:9px 0;
  border-bottom:1px solid var(--line);font-size:14.5px}
.gate:last-child{border-bottom:0}
.gate .when{color:var(--ink3);font-size:13px;margin-left:auto;
  white-space:nowrap}
.gate.now b{color:var(--accent)}
.bar{height:10px;background:var(--line);border-radius:99px;overflow:hidden;
  margin-top:8px}
.bar i{display:block;height:100%;background:var(--accent);border-radius:99px}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th{text-align:left;font-size:11.5px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink3);padding:6px 10px 6px 0}
td{padding:7px 10px 7px 0;border-top:1px solid var(--line);
  vertical-align:top}
a{color:var(--accent)}
.doc{display:flex;gap:10px;align-items:baseline;padding:9px 0;
  border-bottom:1px solid var(--line);font-size:14.5px}
.doc:last-child{border-bottom:0}
.doc .st{color:var(--ink3);font-size:13px}
.btn{display:inline-block;background:var(--accent);color:#fff;border:0;
  border-radius:10px;padding:10px 18px;font-weight:600;font-size:14.5px;
  text-decoration:none;cursor:pointer;font-family:inherit}
label{display:block;font-size:11.5px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink3);margin:14px 0 5px}
input,textarea,select{width:100%;border:1px solid var(--line);
  border-radius:10px;padding:10px 12px;font-family:inherit;font-size:15px;
  background:#fff}
.fine{font-size:12.5px;color:var(--ink3)}
.doc-body{font-size:15px}
.doc-body h2,.doc-body h3,.doc-body h4{font-family:'Fraunces',Georgia,serif;
  margin:22px 0 8px}
.doc-body p,.doc-body ul,.doc-body ol,.doc-body blockquote{margin:10px 0}
.doc-body blockquote{border-left:3px solid var(--line);padding-left:14px;
  color:var(--ink2)}
.doc-body img{max-width:100%}
.brand-shot{max-width:100%;border-radius:10px;border:1px solid var(--line);
  margin-top:10px}
"""


def _portal_shell(title: str, inner: str) -> str:
    from .api import FONT_LINK
    return (f"<!doctype html><html lang=\"en\"><head>"
            f"<meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,"
            f" initial-scale=1\">"
            f"<meta name=\"robots\" content=\"noindex\">"
            f"<title>{sect.esc(title)}</title>{FONT_LINK}"
            f"<style>{PORTAL_CSS}</style></head>"
            f"<body><div class=\"wrap\">{inner}</div></body></html>")


@router.get("/engage/{token}")
def portal_page(token: str, con=Depends(get_con), _rl=Depends(rate_limit)):
    e = _portal_or_404(con, token)
    con.execute("UPDATE engagements SET portal_seen_at=? WHERE id=?",
                (time.time(), e["id"]))
    con.commit()
    gates = [g for g in resolve_gates(con, e["id"]) if g["active"]]
    stage = current_stage(gates)
    docs = _portal_docs(con, e["id"])
    dates = con.execute(
        "SELECT label, planned, actual, moved_because FROM engagement_dates"
        " WHERE engagement_id=? ORDER BY ord", (e["id"],)).fetchall()

    day = lambda t: time.strftime("%d %b %Y", time.localtime(t))
    reached_current = False
    gate_rows = []
    for g in gates:
        if g["passed_at"]:
            state = (f'<span class="pill ok">done</span>'
                     f'<span class="when">{day(g["passed_at"])}</span>')
            cls = ""
        elif not reached_current:
            state = '<span class="pill warn">in progress</span>'
            cls = " now"
            reached_current = True
        else:
            state = '<span class="pill">upcoming</span>'
            cls = ""
        gate_rows.append(f'<div class="gate{cls}"><b>{sect.esc(g["label"])}'
                         f'</b>{state}</div>')

    dates_html = ""
    if dates:
        rows = "".join(
            f"<tr><td>{sect.esc(r['label'])}</td>"
            f"<td>{sect.esc(r['planned']) or '—'}</td>"
            f"<td>{sect.esc(r['actual']) or '—'}</td>"
            f"<td>{sect.esc(r['moved_because']) or ''}</td></tr>"
            for r in dates)
        dates_html = (f"<h2>The dates that matter</h2><div class=\"card\">"
                      f"<table><tr><th>Milestone</th><th>Planned</th>"
                      f"<th>Actual</th><th>Moved because</th></tr>{rows}"
                      f"</table></div>")

    blockers_html = ""
    if (e["blockers"] or "").strip():
        items = "".join(f"<li>{sect.esc(b.strip())}</li>"
                        for b in e["blockers"].splitlines() if b.strip())
        blockers_html = (f"<h2>What's blocking</h2><div class=\"card\">"
                         f"<ul style=\"padding-left:18px\">{items}</ul>"
                         f"<p class=\"fine\" style=\"margin-top:8px\">Honest"
                         f" and current — this section is empty when nothing"
                         f" is in the way.</p></div>")

    brand_docs = [d for d in docs if d["stage"] == "07-brand-exploration"]
    other_docs = [d for d in docs if d["stage"] != "07-brand-exploration"]

    def doc_row(d):
        state = ('<span class="pill ok">signed</span>' if d["signed"]
                 else f'<a class="pill warn" href="/sign/{d["sign_token"]}">'
                      f'awaiting your signature</a>' if d["sign_token"]
                 else "")
        cstage = KIT_TO_CLIENT_STAGE.get(d["stage"], d["stage"])
        return (f'<div class="doc"><a href="/engage/{token}/doc/{d["id"]}">'
                f'{sect.esc(d["title"])}</a>'
                f'<span class="st">{STAGE_LABELS.get(cstage, cstage)}</span>'
                f'{state}</div>')

    docs_html = ""
    if other_docs:
        docs_html = ("<h2>Your documents</h2><div class=\"card\">"
                     + "".join(doc_row(d) for d in other_docs) + "</div>")

    brand_html = ""
    if brand_docs:
        chosen = next((d for d in brand_docs
                       if DIRECTION_MARK in (d["notes"] or "")), None)
        boards = "".join(
            f'<img class="brand-shot" src="/engage/{token}/doc/{d["id"]}"'
            f' alt="{sect.esc(d["title"])}">'
            if d["ext"] in ("png", "jpg", "jpeg") else doc_row(d)
            for d in brand_docs
            if DIRECTION_MARK not in (d["notes"] or ""))
        if chosen:
            form = ("<p class=\"pill ok\" style=\"margin-top:14px\">Your"
                    " direction choice is recorded — thank you.</p>")
        else:
            form = f"""
  <form method="post" action="/engage/{token}/direction"
        style="margin-top:18px">
    <b>Choose a direction</b>
    <p class="fine">One consolidated response, please — gather everyone's
      views first. Judge the direction, not the details: the words and
      photos are stand-ins. Ask "is this right for the business?", not
      "do I like it?"</p>
    <label>We're going with</label>
    <input name="choice" required maxlength="120"
      placeholder="e.g. Direction 2 — Quiet Authority">
    <label>What works</label>
    <textarea name="works" rows="3" maxlength="4000"></textarea>
    <label>Anything that would be a firm no</label>
    <textarea name="worries" rows="2" maxlength="4000"></textarea>
    <label>Your name</label>
    <input name="name" required maxlength="120">
    <p style="margin-top:14px"><button class="btn">Send the choice</button></p>
  </form>"""
        brand_html = (f"<h2>Brand work</h2><div class=\"card\">{boards}"
                      f"{form}</div>")

    cstage_label = STAGE_LABELS.get(stage, stage)
    passed = sum(1 for g in gates if g["passed_at"])
    inner = f"""
  <h1>{sect.esc(e["name"])} — project roadmap</h1>
  <p class="meta">{sect.esc(e["week_note"]) or
    "Live view — this page always shows where things stand right now."}</p>
  <div class="card">
    <span class="pill">stage: {sect.esc(cstage_label)}</span>
    {f'<span class="pill">launch target: {sect.esc(e["launch_target"])}</span>'
     if e["launch_target"] else ''}
    <p class="meta" style="margin-top:12px">Content received —
      the thing that most often moves a launch date</p>
    <div class="bar"><i style="width:{int(e["content_pct"])}%"></i></div>
    <p class="fine" style="margin-top:4px">{int(e["content_pct"])}%</p>
  </div>
  <h2>The gates</h2>
  <div class="card">
    <p class="fine">Each phase ends at a gate you approve. {passed} of
      {len(gates)} passed. This is read live from the signed documents —
      it cannot say one thing while the paperwork says another.</p>
    <div style="margin-top:8px">{"".join(gate_rows)}</div>
  </div>
  {dates_html}{blockers_html}{docs_html}{brand_html}
  <p class="fine" style="margin-top:34px">This link is yours — please don't
    forward it. Questions: reply to any email from us, or ring.</p>"""
    return HTMLResponse(_portal_shell(f"{e['name']} — project roadmap",
                                      inner))


@router.get("/engage/{token}/doc/{did}")
def portal_doc(token: str, did: int, con=Depends(get_con),
               _rl=Depends(rate_limit)):
    e = _portal_or_404(con, token)
    # The wall, enforced by the query: not this engagement's, or not on the
    # client's side — then as far as this route knows, it does not exist.
    row = con.execute(
        "SELECT d.* FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND ed.doc_id=? AND ed.side='to_client'",
        (e["id"], did)).fetchone()
    if row is None:
        raise HTTPException(404, "not found")
    from . import documents as vault
    if row["ext"]:
        p = vault.doc_path(row)
        if not p.exists():
            raise HTTPException(404, "file missing from storage")
        return FileResponse(p, media_type=vault.ALLOWED_EXT.get(
            row["ext"], "application/octet-stream"))
    sigs = vault.signed_rows(con, row["id"])
    inner = (f"<p><a href=\"/engage/{token}\">← back to the roadmap</a>"
             f"<a class=\"btn\" style=\"float:right\""
             f" href=\"/engage/{token}/pdf/{did}\">Download "
             f"{'signed ' if sigs else ''}PDF</a></p>"
             f"<h1>{sect.esc(row['title'])}</h1>"
             f"<div class=\"card doc-body\">{vault.md_html(row['body'])}"
             f"{vault.signatures_html(sigs)}"
             f"{vault.pending_html(vault.pending_rows(con, row['id']))}"
             f"</div>")
    return HTMLResponse(_portal_shell(row["title"], inner))


@router.get("/engage/{token}/pdf/{did}")
def portal_doc_pdf(token: str, did: int, con=Depends(get_con),
                   _rl=Depends(rate_limit)):
    e = _portal_or_404(con, token)
    row = con.execute(
        "SELECT d.* FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND ed.doc_id=? AND ed.side='to_client'",
        (e["id"], did)).fetchone()
    if row is None:
        raise HTTPException(404, "not found")
    from . import documents as vault
    return vault._pdf_response(row, inline=False,
                               sigs=vault.signed_rows(con, row["id"]),
                               pending=vault.pending_rows(con, row["id"]))


@router.post("/engage/{token}/direction")
async def portal_direction(token: str, request: Request,
                           con=Depends(get_con), _rl=Depends(rate_limit)):
    """The direction-review form, answered in the portal. The response is
    filed as a document under the brand stage — it is the client's returned
    choice form, and the folder convention already has a home for it."""
    e = _portal_or_404(con, token)
    form = await request.form()
    choice = str(form.get("choice", "")).strip()[:120]
    name = str(form.get("name", "")).strip()[:120]
    works = str(form.get("works", "")).strip()[:4000]
    worries = str(form.get("worries", "")).strip()[:4000]
    if not choice or not name:
        raise HTTPException(400, "the choice and your name are required")
    if not con.execute(
            "SELECT 1 FROM engagement_docs WHERE engagement_id=?"
            " AND stage='07-brand-exploration' LIMIT 1",
            (e["id"],)).fetchone():
        raise HTTPException(400, "there is no brand work to choose from")
    already = con.execute(
        "SELECT 1 FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND d.notes LIKE ? LIMIT 1",
        (e["id"], f"%{DIRECTION_MARK}%")).fetchone()
    if already:
        raise HTTPException(400, "a choice is already recorded — if it needs "
                                 "to change, tell us and we'll reopen it")
    body = (f"# Direction choice — {e['name']}\n\n"
            f"**We're going with:** {choice}\n\n"
            f"**What works:** {works or '—'}\n\n"
            f"**A firm no, whichever way we go:** {worries or '—'}\n\n"
            f"**Recorded by:** {name}, via the project portal, "
            f"{time.strftime('%d %b %Y %H:%M')}")
    cur = con.execute(
        "INSERT INTO documents(title,category,party_kind,party_name,"
        " party_email,body,notes,status,confidential,uploaded_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (f"Direction choice — {name}"[:200], "other", "partner",
         e["name"][:120], e["approver_email"], body, DIRECTION_MARK,
         "active", 1, 0, time.time()))
    con.execute(
        "INSERT INTO engagement_docs(engagement_id,doc_id,stage,side,"
        " created_at) VALUES(?,?,?,?,?)",
        (e["id"], cur.lastrowid, "07-brand-exploration", "to_client",
         time.time()))
    log(con, e["id"], name, f"direction chosen via portal: {choice}")
    con.commit()
    from .api import fire_webhooks
    fire_webhooks("direction.chosen", {
        "id": e["id"], "client": e["name"], "choice": choice})
    return HTMLResponse(_portal_shell("Choice recorded", f"""
  <h1>Thank you</h1>
  <p class="meta">Your choice — <b>{sect.esc(choice)}</b> — is recorded and
    the team has it. Next: it gets written up as the art direction, and you
    sign that. From then on it's the reference for everything built.</p>
  <p style="margin-top:18px"><a class="btn" href="/engage/{token}">Back to
    the roadmap</a></p>"""))
