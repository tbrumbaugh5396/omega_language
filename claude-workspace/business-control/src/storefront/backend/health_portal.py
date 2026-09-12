"""The patient's own window on their record.

What a patient wants from a portal is short: when am I next in, can I
say I have arrived, what is on file about me, and what have they got of
mine. This page answers those and nothing else. It shows the record as
the practice shares it — a visit marked not-shared stays with the
practice, and the desk's own notes never appear — and every opening of
it is written in the same access log the practice sees, because a
record whose readers are unknown is a record that has already leaked.

Checking in from here is the tablet on the counter without the tablet:
allowed from three hours before the appointment until it ends, and it
lands on the desk's queue the same moment.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from erp.backend import health as H

from .api import current_customer, get_con, render_shell
from .partners import _require_cap, brand_name

router = APIRouter()


def _patient(con, user) -> None:
    """A customer with no record has no portal — the page says so
    rather than making an empty one, because the record is the
    practice's to open."""
    row = con.execute("SELECT portal FROM patients WHERE user_id=?",
                      (user["id"],)).fetchone()
    if row is None:
        raise HTTPException(404, "no record here yet — the practice opens one")
    if not row["portal"]:
        raise HTTPException(403, "your record is not shown online; ask the practice")


@router.get("/api/health/me")
def my_record(user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("health")
    _patient(con, user)
    H.log_access(con, user["id"], user, "portal")
    con.commit()
    return H.record(con, user["id"], for_patient=True)


class SelfCheckin(BaseModel):
    appointment_id: int


@router.post("/api/health/me/checkin")
def my_checkin(body: SelfCheckin, user=Depends(current_customer),
               con=Depends(get_con)):
    _require_cap("health")
    _patient(con, user)
    return H.check_in(con, body.appointment_id, method="portal",
                      patient_id=user["id"])


@router.get("/api/health/me/files/{fid}")
def my_file(fid: int, user=Depends(current_customer), con=Depends(get_con)):
    _require_cap("health")
    _patient(con, user)
    H.log_access(con, user["id"], user, f"portal:file:{fid}")
    con.commit()
    return H._serve_file(con, user["id"], fid, for_patient=True)


class SelfPolicy(BaseModel):
    id: int = 0
    payer: str
    plan: str = ""
    member_id: str = ""
    group_no: str = ""
    subscriber: str = ""
    relationship: str = "self"
    payer_phone: str = ""


@router.post("/api/health/me/insurance")
def my_insurance(body: SelfPolicy, user=Depends(current_customer),
                 con=Depends(get_con)):
    """The patient keeps their own card on file. Anything they type is
    unverified until the desk marks it, and a policy the desk verified
    is not theirs to rewrite here."""
    _require_cap("health")
    _patient(con, user)
    if not body.payer.strip():
        raise HTTPException(400, "who is the insurer?")
    if body.relationship not in H.RELATIONSHIPS:
        raise HTTPException(400, f"relationship is one of {H.RELATIONSHIPS}")
    args = (body.payer.strip()[:120], body.plan.strip()[:120],
            body.member_id.strip()[:60], body.group_no.strip()[:60],
            body.subscriber.strip()[:120], body.relationship,
            body.payer_phone.strip()[:40])
    if body.id:
        r = con.execute("SELECT * FROM insurance_policies WHERE id=? AND user_id=?"
                        " AND active=1", (body.id, user["id"])).fetchone()
        if r is None:
            raise HTTPException(404, "no such policy")
        if r["verified_at"]:
            raise HTTPException(400, "the practice has verified this one; ask "
                                     "them to change it")
        con.execute("UPDATE insurance_policies SET payer=?, plan=?, member_id=?,"
                    " group_no=?, subscriber=?, relationship=?, payer_phone=?"
                    " WHERE id=?", args + (body.id,))
        pid = body.id
    else:
        has = con.execute("SELECT COUNT(*) FROM insurance_policies WHERE user_id=?"
                          " AND active=1", (user["id"],)).fetchone()[0]
        pid = con.execute(
            "INSERT INTO insurance_policies(user_id,payer,plan,member_id,group_no,"
            " subscriber,relationship,payer_phone,primary_policy,note,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (user["id"],) + args + (0 if has else 1, "entered by the patient",
                                    time.time())).lastrowid
    H.log_access(con, user["id"], user, "portal:insurance")
    con.commit()
    return {"ok": True, "id": pid}


@router.get("/health", response_class=HTMLResponse)
def health_page(con=Depends(get_con)):
    _require_cap("health")
    from .api import asset_version
    brand = brand_name(con)
    v = asset_version()
    body = f"""
<section class="section partner-head">
 <span class="eyebrow">Your record</span>
 <h1>My health</h1>
 <p class="lede">Your next appointment, a way to say you have arrived, what
  is on file about you, and the documents the practice has shared. Only
  you can see this page, and every time it is opened is written down.</p>
</section>
<section class="section" id="hp-root"><p class="lrn-meta">Loading…</p></section>
<style>
 .hp-card{{border:1px solid rgba(127,127,127,.35);border-radius:12px;padding:14px 16px;margin:10px 0}}
 .hp-row{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
 .hp-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin:8px 0}}
 .hp-grid span{{display:block;font-size:.8em;opacity:.7;text-transform:uppercase;letter-spacing:.04em}}
 .hp-enc{{padding:8px 0;border-top:1px solid rgba(127,127,127,.2)}}
 .hp-notes{{white-space:pre-wrap;margin:4px 0}}
 .hp-pill{{font-size:.8em;padding:2px 8px;border-radius:999px;border:1px solid currentColor}}
 .hp-form{{display:grid;gap:8px;max-width:420px}}
 .hp-form input,.hp-form select{{padding:8px;border-radius:8px;border:1px solid rgba(127,127,127,.4);background:none;color:inherit}}
 .lrn-btn{{padding:8px 16px;border-radius:8px;border:1px solid currentColor;background:none;color:inherit;cursor:pointer}}
 .lrn-btn.sm{{padding:4px 10px;font-size:.85em}}
 .lrn-meta{{opacity:.7;font-size:.9em}}
</style>
<script src="/health.js?v={v}"></script>"""
    return HTMLResponse(render_shell(
        con, body, title=f"My health — {brand}",
        description=f"{brand}: your appointments, record and documents."))
