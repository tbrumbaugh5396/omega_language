"""The Scope of Work — peeled whole from engagements.py.

Generated, never blank: deliverables from the quote, fees from the price
book, the timeline from the same schedule the gantt draws — composed here,
filed and signed through the vault like everything else. Change orders
amend a SIGNED SOW; an open draft just gets edited. The shared facts
(gates, tracks, the kit's filing helpers) stay in engagements.py and are
imported — one source, two files."""
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter()

from .api import admin_user, get_con  # noqa: E402
from .engagements import (QUOTE_NOTE, SOW_NOTE, _cap_catalog,  # noqa: E402
                          _core_price, _eng_or_404, _gates_with_dates,
                          log, placeholders, tracks_of)


# ---------- the scope of work ----------
#
# A SOW here is GENERATED, not authored blank: deliverables come from the
# quote, fees from the price book, the timeline from the same schedule the
# gantt draws — so the paper cannot disagree with the record it rides on.
# It stays editable in the vault until the signature request goes out, and
# freezes there like every signed document. Scope changes afterwards are a
# CHANGE ORDER referencing the signed SOW, never an edit of it.

def _quote_facts(con, eid: int) -> dict | None:
    """What the client is buying, from the quote — the signed one if there
    is one, else the latest, saying which."""
    rows = con.execute(
        "SELECT d.id, d.title, d.notes,"
        "  (SELECT COUNT(*) FROM document_signatures s"
        "    WHERE s.document_id=d.id AND s.status='signed') AS signed"
        " FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND d.notes LIKE ?"
        "   AND d.status!='archived' ORDER BY d.created_at DESC",
        (eid, QUOTE_NOTE + "%")).fetchall()
    row = next((r for r in rows if r["signed"]), rows[0] if rows else None)
    if row is None:
        return _facts_from_record(con, eid)
    import base64
    try:
        state = json.loads(base64.b64decode(
            row["notes"][len(QUOTE_NOTE):]).decode("utf-8"))
    except Exception:
        return None
    return {"cap_ids": [c for c in (state.get("on") or []) if c != "core"],
            "locs": int(state.get("locs") or 1),
            "seats": int(state.get("seats") or 5),
            "dedicated": bool(state.get("dedicated")),
            "doc_id": row["id"], "doc_title": row["title"],
            "signed": bool(row["signed"])}


def _facts_from_record(con, eid: int) -> dict | None:
    """No quote on file, but the client card says what they are buying.

    The bench is one way to decide a line-up and the client form is the
    other; a Scope of Work composed only from the first would go out
    empty for every client sold across a table. So the record answers
    when no quote does, in the same shape.
    """
    e = con.execute("SELECT * FROM engagements WHERE id=?", (eid,)).fetchone()
    if e is None:
        return None
    caps = [c for c in (e["caps"] or "").split(",") if c]
    if not (caps or e["package"]):
        return None
    if not caps and e["package"]:
        # a packaged tier covers its own set; the book says which
        from .pricebook import tiers as _tiers
        try:
            t = next(t for t in _tiers() if t["name"] == e["package"])
        except (StopIteration, Exception):              # noqa: BLE001
            t = None
        if t:
            names = {c["name"].lower(): c["id"] for c in _cap_catalog()}
            caps = [names[n.strip().lower()] for n
                    in t["capabilities"].split(",")
                    if n.strip().lower() in names]
    return {"cap_ids": caps, "locs": 1, "seats": 5, "dedicated": False,
            "doc_id": 0, "doc_title": "the client record", "signed": False,
            "from_record": True}


def sow_body(con, e) -> str:
    """The Scope of Work, composed from what the record already knows.
    Identity facts stay as [TOKENS] — they read from the client record
    until the signature freezes the text. The derived tables are baked at
    drafting, which is the point: the draft is the record's view TODAY,
    and signing is what turns that view into a commitment."""
    q = _quote_facts(con, e["id"])
    caps = {c["id"]: c for c in _cap_catalog()}
    core = _core_price()
    today = time.strftime("%B %d, %Y").replace(" 0", " ")
    L = [
        "# [BRAND]",
        "",
        "## Scope of Work — [CLIENT]",
        "",
        "| | |",
        "|---|---|",
        "| Client | [CLIENT] |",
        "| Client approver | [CLIENT POC] |",
        "| Our lead | [INTERNAL POC] |",
        f"| Issued | {today} |",
        "",
        "### 1. Background & purpose",
        "",
        "[PURPOSE — one short paragraph: what the client is trying to "
        "achieve, in their words]",
        "",
        "### 2. Deliverables",
        "",
    ]
    if q:
        L += [f"The platform, stood up and configured for [CLIENT] — "
              f"{q['locs']} location{'s' if q['locs'] != 1 else ''}, "
              f"{q['seats']} seat{'s' if q['seats'] != 1 else ''}"
              + (", on dedicated infrastructure" if q["dedicated"] else "")
              + " — carrying the capabilities below.", "",
              "| Capability | Group | Monthly |", "|---|---|---|",
              f"| Platform Core | — | ${core} |"]
        for cid in q["cap_ids"]:
            c = caps.get(cid)
            if c:
                L.append(f"| {c['name']} | {c['group'] or '—'} |"
                         f" ${c['price']} |")
        total = core + sum(caps[c]["price"] for c in q["cap_ids"]
                           if c in caps)
        L += [f"| **Software subtotal** | | **${total}/mo** |", "",
              f"Per the {'signed ' if q['signed'] else ''}quote "
              f"“{q['doc_title']}”, which governs pricing. "
              "Metered lines move with real usage; pass-throughs on the "
              "client's own vendor accounts are billed by those vendors "
              "directly.", ""]
    else:
        L += ["[DELIVERABLES — no quote is filed on this engagement yet; "
              "file one on the bench and regenerate, or write the "
              "deliverables here]", ""]
    L += timeline_md(con, e)
    L += [
        "### 4. Fees & payment",
        "",
        ("Monthly software fees as itemised in §2, from the published "
         "price book. " if q else "[FEES — from the quote] ")
        + "Build and one-time fees per the quote; deposit due at contract "
          "signing, final invoice before launch, as the payment gates on "
          "this engagement schedule them.",
        "",
        "### 5. Change control",
        "",
        "Work not described in §2 is out of scope. Changes are agreed in a "
        "written **change order** referencing this Scope of Work — stating "
        "what changes, the fee adjustment, and any effect on §3 — and "
        "signed the way this document is signed. No changed work begins "
        "before its change order is.",
        "",
        "### 6. Suspension & exit",
        "",
        "As the signed agreement provides: either party may end the "
        "engagement per its notice terms; suspension for non-payment and "
        "the return of client materials follow the agreement's clauses, "
        "which this SOW does not amend.",
        "",
        "### 7. Acceptance",
        "",
        "Signed for the client by **[APPROVER]**, and for [BRAND] by "
        "**[INTERNAL POC]**. Signature attests to this text as it stands.",
    ]
    return "\n".join(L)


def timeline_md(con, e) -> list:
    """Section 3, composed from the live schedule — one builder, used by
    the first draft AND by refresh-timeline, so the two can never render
    the table differently."""
    L = ["### 3. Timeline", ""]
    gates, _dates = _gates_with_dates(con, e["id"])
    tracks = tracks_of(gates)
    est_any = any(t["estimated"] for t in tracks)
    if tracks:
        L += ["| Phase | Begins | Ends | Duration |", "|---|---|---|---|"]
        for t in tracks:
            mark = " *(est.)*" if t["estimated"] else ""
            wk = (f"{t['days']} days" if t["days"] < 10
                  else f"~{round(t['days'] / 7)} weeks")
            L.append(f"| {t['name']}"
                     + (" *(optional)*" if t.get("optional") else "")
                     + f" | {t['start']}{mark} | {t['end']}{mark}"
                     + f" | {wk}{mark} |")
        if est_any:
            L += ["", "Dates marked *(est.)* are planning durations, not "
                  "commitments — the engagement's Dates table is the "
                  "governing schedule, and written dates replace these "
                  "estimates wherever they appear."]
        L.append("")
    return L


@router.post("/api/store/admin/engagements/{eid}/sow/{did}/refresh-timeline")
def refresh_timeline(eid: int, did: int, u=Depends(admin_user),
                     con=Depends(get_con)):
    """Editing the timeline, the governed way: write real dates in the
    Dates table (or pass gates), then refresh — section 3 is re-derived
    from the live schedule while every other edit in the paper stands.
    A SIGNED SOW refuses: its text is what was attested; scope moves by
    change order."""
    e = _eng_or_404(con, eid)
    d = con.execute(
        "SELECT d.*, (SELECT COUNT(*) FROM document_signatures s"
        "  WHERE s.document_id=d.id AND s.status='signed') AS signed"
        " FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
        " WHERE ed.engagement_id=? AND d.id=?", (eid, did)).fetchone()
    if d is None or not str(d["notes"] or "").startswith(SOW_NOTE):
        raise HTTPException(404, "that document is not this engagement's "
                                 "Scope of Work")
    if d["signed"]:
        raise HTTPException(409, "a signed SOW's text is what was attested "
                                 "— changes ride a change order")
    body = d["body"] or ""
    lo = body.find("### 3. Timeline")
    hi = body.find("### 4.")
    if lo == -1 or hi == -1 or hi < lo:
        raise HTTPException(409, "the timeline section was edited beyond "
                                 "recognition — update it by hand")
    new = body[:lo] + "\n".join(timeline_md(con, e)) + body[hi:]
    con.execute("UPDATE documents SET body=? WHERE id=?", (new, did))
    log(con, eid, u["name"], "SOW timeline refreshed from the schedule")
    con.commit()
    return {"ok": True}


def change_order_body(e, sow) -> str:
    when = time.strftime("%B %d, %Y").replace(" 0", " ")
    return "\n".join([
        "# [BRAND]",
        "",
        f"## Change order — [CLIENT]",
        "",
        f"Amends the signed Scope of Work “{sow['title']}” "
        f"(document #{sow['id']}). That SOW stands except as changed "
        "below; nothing here re-opens its signed text.",
        "",
        f"| | |", "|---|---|",
        "| Client | [CLIENT] |",
        f"| Issued | {when} |",
        "",
        "### What changes",
        "",
        "[CHANGES — what is added, removed or altered, precisely]",
        "",
        "### Fee adjustment",
        "",
        "[FEE ADJUSTMENT — the delta, one-time or monthly, or “none"
        "”]",
        "",
        "### Effect on the timeline",
        "",
        "[TIMELINE EFFECT — which phases move, or “none”]",
        "",
        "### Acceptance",
        "",
        "Signed for the client by **[APPROVER]**, and for [BRAND] by "
        "**[INTERNAL POC]**.",
    ])


def _file_composed(con, e, text: str, title: str, note: str,
                   actor: str) -> int:
    """A composed paper into the vault, linked to its engagement — the
    same landing file_kit_doc gives a template, minus the template."""
    remaining = placeholders(text)
    cur = con.execute(
        "INSERT INTO documents(title,category,party_kind,party_name,"
        " party_email,body,notes,status,confidential,uploaded_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (title[:200], "contracts", "partner", e["name"][:120],
         e["approver_email"], text, note,
         "draft" if remaining else "active", 1, 0, time.time()))
    doc_id = cur.lastrowid
    con.execute(
        "INSERT INTO engagement_docs(engagement_id,doc_id,stage,side,"
        " created_at) VALUES(?,?,?,?,?)",
        (e["id"], doc_id, "04-agreement", "to_client", time.time()))
    log(con, e["id"], actor,
        f"drafted '{title}'"
        + (f" ({len(remaining)} blanks left)" if remaining else ""))
    con.commit()
    return doc_id


class SowBody(BaseModel):
    change_order_for: int = 0


@router.post("/api/store/admin/engagements/{eid}/sow")
def draft_sow(eid: int, body: SowBody, u=Depends(admin_user),
              con=Depends(get_con)):
    e = _eng_or_404(con, eid)
    if body.change_order_for:
        sow = con.execute(
            "SELECT d.id, d.title, d.notes,"
            "  (SELECT COUNT(*) FROM document_signatures s"
            "    WHERE s.document_id=d.id AND s.status='signed') AS signed"
            " FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
            " WHERE ed.engagement_id=? AND d.id=?",
            (eid, body.change_order_for)).fetchone()
        if sow is None or not sow["notes"].startswith(SOW_NOTE):
            raise HTTPException(404, "that document is not this "
                                     "engagement's Scope of Work")
        if not sow["signed"]:
            raise HTTPException(409, "a change order amends a SIGNED scope "
                                     "of work — this one is still open to "
                                     "ordinary edits")
        text = change_order_body(e, dict(sow))
        title = f"Change order — {e['name']}"
        note = SOW_NOTE + f"change-order:{sow['id']}"
    else:
        text = sow_body(con, e)
        title = f"Scope of Work — {e['name']}"
        note = SOW_NOTE + "sow"
    doc_id = _file_composed(con, e, text, title, note, u["name"])
    return {"doc_id": doc_id, "title": title}


