"""Hiring: a posting, the people who answered it, and the first week.

The job boards do not take postings by API. Indeed, ZipRecruiter and
LinkedIn each read an XML feed you publish and each posts applications
back to an address you give them — which is a better shape for a small
business than nine "post to Indeed" buttons would have been, because one
feed reaches all of them and one address hears from all of them. So:

  /jobs         the open postings, as a page anyone can read and apply on
  /jobs.xml     the same postings in the feed format the boards ingest
  /api/inbound/<board>   where a board posts an application

An application from any of those, from the page, or typed in by whoever
took the phone call, is one row on one board with stages — new, screen,
interview, offer, hired, declined — because a candidate's state is a fact
about the candidate, not about which site they came through.

Hiring somebody does the paperwork a first morning otherwise forgets: it
opens their account with the right role and job, and writes them an
onboarding list — contract, paperwork, PIN and badge, rota, tools, a
check-in — that the office ticks off. Greenhouse and Workable, which are
applicant-tracking systems with real APIs, pull candidates into the same
board so a person hired there is a person here.
"""
import base64
import html
import json
import secrets
import time
import urllib.parse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from . import blobs, db
from . import integrations as IG

TABLES = """
CREATE TABLE IF NOT EXISTS job_postings (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  department TEXT DEFAULT '',
  location TEXT DEFAULT '',
  remote INTEGER DEFAULT 0,
  kind TEXT DEFAULT 'full_time',           -- full_time|part_time|contract|volunteer|internship
  pay_text TEXT DEFAULT '',
  description TEXT DEFAULT '',
  requirements TEXT DEFAULT '',
  role TEXT DEFAULT 'employee',            -- what a hire becomes
  job TEXT DEFAULT 'general',
  state TEXT DEFAULT 'draft',              -- draft|open|closed
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  closed_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS applicants (
  id INTEGER PRIMARY KEY,
  posting_id INTEGER DEFAULT 0,
  name TEXT NOT NULL,
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  cover TEXT DEFAULT '',
  resume_key TEXT DEFAULT '',              -- blob key
  resume_name TEXT DEFAULT '',
  source TEXT DEFAULT 'page',              -- page|indeed|ziprecruiter|linkedin_jobs|greenhouse|workable|typed
  external_id TEXT DEFAULT '',
  stage TEXT DEFAULT 'new',                -- STAGES
  notes TEXT DEFAULT '',
  user_id INTEGER DEFAULT 0,               -- once hired
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS applicants_stage ON applicants(stage);

CREATE TABLE IF NOT EXISTS onboarding_tasks (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  tab TEXT DEFAULT '',                     -- where in the app it is done
  position INTEGER DEFAULT 0,
  done_at REAL DEFAULT 0,
  done_by TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS onboarding_user ON onboarding_tasks(user_id);
"""

STAGES = ("new", "screen", "interview", "offer", "hired", "declined")
KINDS = ("full_time", "part_time", "contract", "volunteer", "internship")
KIND_LABEL = {"full_time": "Full time", "part_time": "Part time",
              "contract": "Contract", "volunteer": "Volunteer",
              "internship": "Internship"}
# The first week, as a list somebody ticks. Each line names the screen
# it is done on, so the list is a set of doors rather than a poster.
ONBOARDING = [
    ("Contract signed", "docs"),
    ("Right-to-work and tax paperwork on file", "docs"),
    ("Time-clock PIN set and badge printed", "staff"),
    ("On the rota for the first week", "rota"),
    ("Shown the Board, Chat and Scan", "board"),
    ("End of first week check-in", "calendar"),
]
BOARDS = ("indeed", "ziprecruiter", "linkedin_jobs")


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return bool(user["is_admin"] or user["role"] in ("admin", "owner"))


def _slug(title: str, con) -> str:
    base = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    base = "-".join(x for x in base.split("-") if x)[:60] or "job"
    slug, n = base, 2
    while con.execute("SELECT 1 FROM job_postings WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _posting(r) -> dict:
    d = dict(r)
    d["kind_label"] = KIND_LABEL.get(d["kind"], d["kind"])
    return d


def open_postings(con) -> list:
    return [_posting(r) for r in con.execute(
        "SELECT * FROM job_postings WHERE state='open' ORDER BY created_at DESC"
        ).fetchall()]


# ---------- an application, from anywhere ----------

def add_applicant(con, *, name: str, email: str = "", phone: str = "",
                  cover: str = "", posting_id: int = 0, source: str = "page",
                  external_id: str = "", resume: tuple | None = None) -> int:
    """One person answering one posting. Idempotent on (source,
    external_id) because a board retries a webhook it did not hear an
    answer to, and a queue of near-identical rows loses the applicant."""
    name = (name or "").strip()[:120]
    if not name:
        raise HTTPException(400, "an application needs a name")
    email = (email or "").strip()[:200].lower()
    if external_id:
        have = con.execute("SELECT id FROM applicants WHERE source=? AND external_id=?",
                           (source, external_id)).fetchone()
        if have:
            return have["id"]
    elif email:
        # The same person applying twice to the same posting is one
        # applicant with a newer note, not two.
        have = con.execute(
            "SELECT id FROM applicants WHERE email=? AND posting_id=?"
            " AND stage NOT IN ('hired','declined')", (email, posting_id)).fetchone()
        if have:
            con.execute("UPDATE applicants SET updated_at=? WHERE id=?",
                        (time.time(), have["id"]))
            con.commit()
            return have["id"]
    key, fname = "", ""
    if resume and resume[1]:
        fname = (resume[0] or "resume")[:120]
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "bin"
        if ext not in ("pdf", "doc", "docx", "txt", "rtf", "odt"):
            ext = "bin"
        key = f"hiring/{secrets.token_urlsafe(12)}.{ext}"
        blobs.put(key, resume[1])
    now = time.time()
    cur = con.execute(
        "INSERT INTO applicants(posting_id,name,email,phone,cover,resume_key,"
        " resume_name,source,external_id,stage,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,'new',?,?)",
        (int(posting_id or 0), name, email, (phone or "").strip()[:40],
         (cover or "").strip()[:4000], key, fname, source, external_id, now, now))
    con.commit()
    try:
        from . import notify
        notify.push(con, f"New applicant: {name}",
                    f"via {source}" + (f" for posting #{posting_id}" if posting_id else ""),
                    kind="hiring")
    except Exception:                                        # noqa: BLE001
        pass
    return cur.lastrowid


def _walk(d, *paths):
    """The first value found at any of several dotted paths — because
    three boards spell 'the applicant's name' three ways."""
    for path in paths:
        cur = d
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return ""


def _posting_for(con, ref) -> int:
    """The posting a board's reference points at: our slug, our id, or
    the referencenumber from the feed (which is the id)."""
    ref = str(ref or "").strip()
    if not ref:
        return 0
    if ref.isdigit():
        r = con.execute("SELECT id FROM job_postings WHERE id=?", (int(ref),)).fetchone()
        if r:
            return r["id"]
    r = con.execute("SELECT id FROM job_postings WHERE slug=?", (ref,)).fetchone()
    return r["id"] if r else 0


def inbound_application(con, board: str, body: dict) -> dict:
    """What a board POSTs. Indeed Apply sends {applicant:{fullName,email,
    phoneNumber,resume:{file:{fileName,data}}}, job:{jobId}}; ZipRecruiter
    and LinkedIn are flatter. Read all three shapes; store one row."""
    if not isinstance(body, dict):
        raise HTTPException(400, "expected a JSON object")
    name = _walk(body, "applicant.fullName", "applicant.name", "name",
                 "candidate.name", "full_name")
    if not name:
        first = _walk(body, "applicant.firstName", "first_name", "candidate.first_name")
        last = _walk(body, "applicant.lastName", "last_name", "candidate.last_name")
        name = f"{first} {last}".strip()
    email = _walk(body, "applicant.email", "email", "candidate.email")
    phone = _walk(body, "applicant.phoneNumber", "applicant.phone", "phone",
                  "candidate.phone")
    cover = _walk(body, "applicant.coverLetter", "cover_letter", "cover",
                  "questions", "answers")
    if not isinstance(cover, str):
        cover = json.dumps(cover)[:4000]
    ref = _walk(body, "job.jobId", "job.jobKey", "job.referencenumber",
                "job_id", "referencenumber", "posting", "job.id")
    ext = str(_walk(body, "id", "applicant.id", "application_id",
                    "candidate.id") or "")
    resume = None
    data = _walk(body, "applicant.resume.file.data", "resume.data", "resume_base64")
    fname = _walk(body, "applicant.resume.file.fileName", "resume.name",
                  "resume_name") or "resume.pdf"
    if data:
        try:
            resume = (str(fname), base64.b64decode(str(data)))
        except Exception:                                    # noqa: BLE001
            resume = None
    aid = add_applicant(con, name=str(name), email=str(email), phone=str(phone),
                        cover=str(cover), posting_id=_posting_for(con, ref),
                        source=board, external_id=ext, resume=resume)
    IG.log(con, board, "application", True, f"{name} → #{aid}")
    return {"ok": True, "applicant_id": aid}


for _b in BOARDS:
    IG.INBOUND[_b] = (lambda b: lambda con, body: inbound_application(con, b, body))(_b)


# ---------- the ATSs, which do have APIs ----------

def _check_greenhouse(c: dict) -> tuple:
    basic = base64.b64encode(f"{c.get('api_key','')}:".encode()).decode()
    ok, d = IG._req("https://harvest.greenhouse.io/v1/candidates?per_page=1",
                    headers={"Authorization": f"Basic {basic}"})
    return (True, "Harvest API readable") if ok else (False, str(d))


def _check_workable(c: dict) -> tuple:
    sub = c.get("subdomain", "").replace(".workable.com", "").strip("/")
    ok, d = IG._req(f"https://{sub}.workable.com/spi/v3/jobs?limit=1",
                    headers={"Authorization": f"Bearer {c.get('token','')}"})
    return (True, f"{sub}.workable.com") if ok else (False, str(d))


IG.CHECKS["greenhouse"] = _check_greenhouse
IG.CHECKS["workable"] = _check_workable

# Their stage names, folded into ours. Anything unrecognised is a screen.
_STAGE_FOLD = {"application review": "screen", "sourced": "new", "applied": "new",
               "phone screen": "screen", "phone interview": "screen",
               "assessment": "screen", "interview": "interview",
               "onsite": "interview", "offer": "offer", "hired": "hired",
               "rejected": "declined", "disqualified": "declined"}


def _fold(stage: str) -> str:
    s = (stage or "").lower()
    for k, v in _STAGE_FOLD.items():
        if k in s:
            return v
    return "screen" if s else "new"


def pull_candidates(con, name: str) -> dict:
    c = IG.creds(con, name)
    if not c:
        raise HTTPException(400, f"connect {IG.PROVIDERS[name]['label']} first")
    s = IG.settings(con, name)
    rows = []
    if name == "greenhouse":
        basic = base64.b64encode(f"{c.get('api_key','')}:".encode()).decode()
        ok, d = IG._req("https://harvest.greenhouse.io/v1/applications?per_page=100",
                        headers={"Authorization": f"Basic {basic}"})
        if not ok:
            raise HTTPException(400, f"Greenhouse said: {d}")
        for a in d if isinstance(d, list) else []:
            cand = a.get("candidate") or {}
            cid = str(a.get("candidate_id") or cand.get("id") or "")
            ok2, cd = IG._req(f"https://harvest.greenhouse.io/v1/candidates/{cid}",
                              headers={"Authorization": f"Basic {basic}"}) \
                if cid and not cand.get("first_name") else (True, cand)
            cd = cd if ok2 and isinstance(cd, dict) else {}
            rows.append({
                "name": f"{cd.get('first_name','')} {cd.get('last_name','')}".strip()
                        or f"Greenhouse candidate {cid}",
                "email": ((cd.get("email_addresses") or [{}])[0]).get("value", ""),
                "phone": ((cd.get("phone_numbers") or [{}])[0]).get("value", ""),
                "external_id": str(a.get("id") or cid),
                "stage": _fold(((a.get("current_stage") or {}).get("name")
                                or a.get("status") or "")),
                "job": ((a.get("jobs") or [{}])[0]).get("name", "")})
    elif name == "workable":
        sub = s.get("subdomain", "").replace(".workable.com", "").strip("/")
        h = {"Authorization": f"Bearer {c.get('token','')}"}
        ok, d = IG._req(f"https://{sub}.workable.com/spi/v3/candidates?limit=100",
                        headers=h)
        if not ok:
            raise HTTPException(400, f"Workable said: {d}")
        for a in (d.get("candidates") or []) if isinstance(d, dict) else []:
            rows.append({"name": a.get("name", ""), "email": a.get("email", ""),
                         "phone": a.get("phone", ""), "external_id": str(a.get("id")),
                         "stage": _fold(a.get("stage", "")),
                         "job": (a.get("job") or {}).get("title", "")})
    else:
        raise HTTPException(400, "that provider doesn't pull candidates")
    made, moved = 0, 0
    for r in rows:
        before = con.execute("SELECT id, stage FROM applicants WHERE source=?"
                             " AND external_id=?", (name, r["external_id"])).fetchone()
        aid = add_applicant(con, name=r["name"], email=r["email"], phone=r["phone"],
                            cover=f"{IG.PROVIDERS[name]['label']}: {r['job']}",
                            source=name, external_id=r["external_id"])
        if before is None:
            made += 1
        if r["stage"] and (before is None or before["stage"] != r["stage"]) \
                and not (before and before["stage"] in ("hired",)):
            con.execute("UPDATE applicants SET stage=?, updated_at=? WHERE id=?",
                        (r["stage"], time.time(), aid))
            moved += 1
        # a pull is the ATS's word; a name it has changed is changed here
        con.execute("UPDATE applicants SET name=?, email=?, phone=? WHERE id=?",
                    (r["name"][:120], r["email"][:200].lower(), r["phone"][:40], aid))
    con.commit()
    IG.log(con, name, "pull_candidates", True, f"{len(rows)} seen, {made} new")
    return {"ok": True, "seen": len(rows), "new": made, "moved": moved}


# ---------- hiring somebody ----------

def hire(con, cfg, applicant_id: int, by, *, role: str, job: str,
         employment: str, email: str = "") -> dict:
    """An account, and the first week's list. The applicant row is kept
    and linked, so the board shows who was hired rather than losing them
    the moment they were."""
    from .main import JOBS, ROLES_ALLOWED
    a = con.execute("SELECT * FROM applicants WHERE id=?", (applicant_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "no such applicant")
    if a["user_id"]:
        return {"ok": True, "user_id": a["user_id"], "already": True}
    if role not in ROLES_ALLOWED or role in ("customer", "donor"):
        raise HTTPException(400, "a hire is staff of some kind")
    if job and job not in JOBS:
        raise HTTPException(400, "bad job")
    if employment not in ("employee", "contractor"):
        raise HTTPException(400, "employee or contractor")
    email = (email or a["email"] or "").strip()[:200]
    name = a["name"]
    if con.execute("SELECT 1 FROM users WHERE lower(name)=lower(?)", (name,)).fetchone():
        raise HTTPException(409, f"'{name}' already has an account here — "
                                 "link them from Team & access instead")
    cur = con.execute(
        "INSERT INTO users(name,email,role,job,employment,is_admin,active,token,"
        " created_at) VALUES(?,?,?,?,?,0,1,?,?)",
        (name, email, role, job or "general", employment,
         secrets.token_urlsafe(24), db.now()))
    uid = cur.lastrowid
    now = time.time()
    for i, (title, tab) in enumerate(ONBOARDING):
        con.execute("INSERT INTO onboarding_tasks(user_id,title,tab,position,"
                    " created_at) VALUES(?,?,?,?,?)", (uid, title, tab, i, now))
    con.execute("UPDATE applicants SET stage='hired', user_id=?, updated_at=?"
                " WHERE id=?", (uid, now, applicant_id))
    con.commit()
    try:
        from . import notify
        notify.push(con, f"{name} joins as {role}",
                    f"Onboarding list opened — {len(ONBOARDING)} things to do",
                    kind="hiring")
    except Exception:                                        # noqa: BLE001
        pass
    return {"ok": True, "user_id": uid}


def onboarding_of(con, uid: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT * FROM onboarding_tasks WHERE user_id=? ORDER BY position",
        (uid,)).fetchall()]


# ---------- the feed the boards read ----------

def feed_xml(con, base: str, company: str) -> str:
    """The shape Indeed defined and every other board adopted."""
    now = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
    items = []
    for p in open_postings(con):
        when = time.strftime("%a, %d %b %Y %H:%M:%S GMT",
                             time.gmtime(p["created_at"]))
        city, _, region = (p["location"] or "").partition(",")
        items.append(f"""  <job>
    <title><![CDATA[{p['title']}]]></title>
    <date><![CDATA[{when}]]></date>
    <referencenumber><![CDATA[{p['id']}]]></referencenumber>
    <url><![CDATA[{base}/jobs/{p['slug']}]]></url>
    <company><![CDATA[{company}]]></company>
    <city><![CDATA[{city.strip()}]]></city>
    <state><![CDATA[{region.strip()}]]></state>
    <country><![CDATA[]]></country>
    <description><![CDATA[{p['description']}{(chr(10) + chr(10) + 'Requirements: ' + p['requirements']) if p['requirements'] else ''}]]></description>
    <salary><![CDATA[{p['pay_text']}]]></salary>
    <jobtype><![CDATA[{KIND_LABEL.get(p['kind'], p['kind'])}]]></jobtype>
    <category><![CDATA[{p['department']}]]></category>
    <remotetype><![CDATA[{'Fully remote' if p['remote'] else ''}]]></remotetype>
  </job>""")
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<source>\n'
            f"  <publisher><![CDATA[{company}]]></publisher>\n"
            f"  <publisherurl><![CDATA[{base}]]></publisherurl>\n"
            f"  <lastBuildDate><![CDATA[{now}]]></lastBuildDate>\n"
            + "\n".join(items) + "\n</source>\n")


# ---------- routes ----------

router = APIRouter()

from .main import CFG, base_url, current_user, get_con  # noqa: E402  (safe: included late)


def _page(title: str, body: str, company: str) -> HTMLResponse:
    e = html.escape
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{e(title)} — {e(company)}</title>
<style>:root{{color-scheme:light}}
body{{font:17px/1.55 system-ui,sans-serif;color:#16202b;background:#f7f6f3;margin:0}}
main{{max-width:720px;margin:0 auto;padding:1.4rem 1.2rem 3rem}}
header{{display:flex;gap:.8rem;align-items:baseline;flex-wrap:wrap;margin-bottom:1rem}}
h1{{font-size:1.5rem;margin:0}} h2{{font-size:1.15rem;margin:1.4rem 0 .4rem}}
.k{{color:#5b6b7c;font-size:.92rem}} .card{{background:#fff;border:1px solid #e3e0d9;border-radius:14px;padding:1rem 1.1rem;margin:.7rem 0}}
.card a.t{{font-weight:600;color:#16202b;text-decoration:none;font-size:1.05rem}}
label{{display:block;margin:.7rem 0 .2rem;font-weight:600;font-size:.92rem}}
input,textarea{{width:100%;box-sizing:border-box;font:inherit;padding:.55rem .7rem;border:1px solid #cbd2dc;border-radius:.5rem;background:#fff}}
textarea{{min-height:7rem}} .btn{{display:inline-block;margin-top:1rem;padding:.65rem 1.1rem;border-radius:.5rem;background:#4634d9;color:#fff;border:0;font:inherit;cursor:pointer;text-decoration:none}}
.pill{{display:inline-block;padding:.1rem .55rem;border-radius:1rem;background:#eceaf6;font-size:.82rem;margin-right:.3rem}}
.pre{{white-space:pre-wrap}}</style>
<main><header><h1>{e(title)}</h1><span class="k">{e(company)}</span></header>{body}</main>""")


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(con=Depends(get_con)):
    company = CFG.get("brand_name") or "this business"
    e = html.escape
    ps = open_postings(con)
    body = "".join(
        f'<div class="card"><a class="t" href="/jobs/{e(p["slug"])}">{e(p["title"])}</a>'
        f'<div class="k" style="margin:.3rem 0">'
        f'<span class="pill">{e(p["kind_label"])}</span>'
        + (f'<span class="pill">{e(p["location"])}</span>' if p["location"] else "")
        + ('<span class="pill">remote</span>' if p["remote"] else "")
        + (f'<span class="pill">{e(p["pay_text"])}</span>' if p["pay_text"] else "")
        + f'</div><p class="k">{e((p["description"] or "")[:220])}'
        + ("…" if len(p["description"] or "") > 220 else "") + "</p></div>"
        for p in ps) or '<p class="k">Nothing open right now. Check back soon.</p>'
    return _page("Work with us", body, company)


@router.get("/jobs.xml")
def jobs_feed(con=Depends(get_con)):
    company = CFG.get("brand_name") or "Business Control"
    return Response(feed_xml(con, base_url(), company),
                    media_type="application/xml")


@router.get("/api/jobs")
def jobs_json(con=Depends(get_con)):
    base = base_url()
    return {"jobs": [{**p, "url": f"{base}/jobs/{p['slug']}",
                      "apply": f"{base}/api/jobs/{p['slug']}/apply"}
                     for p in open_postings(con)]}


@router.get("/jobs/{slug}", response_class=HTMLResponse)
def job_page(slug: str, con=Depends(get_con)):
    company = CFG.get("brand_name") or "this business"
    e = html.escape
    r = con.execute("SELECT * FROM job_postings WHERE slug=?", (slug,)).fetchone()
    if r is None or r["state"] != "open":
        return HTMLResponse("<h3>That posting is closed.</h3>", 404)
    p = _posting(r)
    body = (f'<div class="k"><span class="pill">{e(p["kind_label"])}</span>'
            + (f'<span class="pill">{e(p["location"])}</span>' if p["location"] else "")
            + ('<span class="pill">remote</span>' if p["remote"] else "")
            + (f'<span class="pill">{e(p["pay_text"])}</span>' if p["pay_text"] else "")
            + f'</div><div class="card pre">{e(p["description"])}</div>'
            + (f'<h2>What we need</h2><div class="card pre">{e(p["requirements"])}</div>'
               if p["requirements"] else "")
            + f'''<h2>Apply</h2><form class="card" method="post" enctype="multipart/form-data"
      action="/api/jobs/{e(slug)}/apply?html=1">
    <label>Your name<input name="name" required maxlength="120"></label>
    <label>Email<input name="email" type="email" required maxlength="200"></label>
    <label>Phone<input name="phone" maxlength="40"></label>
    <label>A few lines about you<textarea name="cover" maxlength="4000"></textarea></label>
    <label>CV or résumé <span class="k">(PDF or Word, optional)</span>
      <input name="resume" type="file" accept=".pdf,.doc,.docx,.txt,.rtf,.odt"></label>
    <button class="btn" type="submit">Send application</button></form>''')
    return _page(p["title"], body, company)


@router.post("/api/jobs/{slug}/apply")
async def job_apply(slug: str, request: Request, name: str = Form(...),
                    email: str = Form(""), phone: str = Form(""),
                    cover: str = Form(""), resume: UploadFile | None = File(None),
                    con=Depends(get_con)):
    r = con.execute("SELECT * FROM job_postings WHERE slug=?", (slug,)).fetchone()
    if r is None or r["state"] != "open":
        raise HTTPException(404, "that posting is closed")
    blob = None
    if resume is not None and resume.filename:
        data = await resume.read()
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, "keep the file under 8 MB")
        blob = (resume.filename, data)
    aid = add_applicant(con, name=name, email=email, phone=phone, cover=cover,
                        posting_id=r["id"], source="page", resume=blob)
    if request.query_params.get("html"):
        company = CFG.get("brand_name") or "this business"
        return _page("Thank you", '<div class="card">Your application is in. '
                     "We read every one, and you will hear from us.</div>"
                     '<p><a class="btn" href="/jobs">Back to the openings</a></p>',
                     company)
    return {"ok": True, "applicant_id": aid}


# --- the office ---

@router.get("/api/hiring")
def hiring_page(user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "hiring is an office screen")
    posts = [_posting(r) for r in con.execute(
        "SELECT * FROM job_postings ORDER BY (state='open') DESC, created_at DESC"
        ).fetchall()]
    counts = {}
    for r in con.execute("SELECT posting_id, COUNT(*) AS n FROM applicants"
                         " WHERE stage NOT IN ('hired','declined')"
                         " GROUP BY posting_id").fetchall():
        counts[r["posting_id"]] = r["n"]
    for p in posts:
        p["open_applicants"] = counts.get(p["id"], 0)
    apps = [dict(r) for r in con.execute(
        "SELECT a.*, p.title AS posting_title FROM applicants a"
        " LEFT JOIN job_postings p ON p.id=a.posting_id"
        " ORDER BY a.updated_at DESC LIMIT 400").fetchall()]
    recent = [dict(r) for r in con.execute(
        "SELECT o.user_id, u.name, COUNT(*) AS total,"
        " SUM(CASE WHEN o.done_at>0 THEN 1 ELSE 0 END) AS done"
        " FROM onboarding_tasks o JOIN users u ON u.id=o.user_id"
        " GROUP BY o.user_id, u.name ORDER BY MAX(o.created_at) DESC LIMIT 20"
        ).fetchall()]
    status = {p["name"]: p for p in IG.status(con)["providers"]
              if p.get("family") == "hiring"}
    base = base_url()
    return {"postings": posts, "applicants": apps, "stages": list(STAGES),
            "kinds": [{"k": k, "label": KIND_LABEL[k]} for k in KINDS],
            "onboarding": recent, "connections": list(status.values()),
            "feed_url": f"{base}/jobs.xml", "page_url": f"{base}/jobs",
            "inbound_urls": {b: f"{base}/api/inbound/{b}" for b in BOARDS}}


class PostingBody(BaseModel):
    id: int = 0
    title: str
    department: str = ""
    location: str = ""
    remote: bool = False
    kind: str = "full_time"
    pay_text: str = ""
    description: str = ""
    requirements: str = ""
    role: str = "employee"
    job: str = "general"
    state: str = "draft"


@router.post("/api/hiring/postings")
def posting_save(body: PostingBody, user=Depends(current_user),
                 con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    title = body.title.strip()[:160]
    if not title:
        raise HTTPException(400, "a posting needs a title")
    if body.kind not in KINDS:
        raise HTTPException(400, "bad kind")
    if body.state not in ("draft", "open", "closed"):
        raise HTTPException(400, "draft, open or closed")
    now = time.time()
    if body.id:
        r = con.execute("SELECT * FROM job_postings WHERE id=?", (body.id,)).fetchone()
        if r is None:
            raise HTTPException(404, "no such posting")
        con.execute(
            "UPDATE job_postings SET title=?, department=?, location=?, remote=?,"
            " kind=?, pay_text=?, description=?, requirements=?, role=?, job=?,"
            " state=?, updated_at=?, closed_at=? WHERE id=?",
            (title, body.department.strip()[:80], body.location.strip()[:120],
             int(body.remote), body.kind, body.pay_text.strip()[:120],
             body.description.strip()[:8000], body.requirements.strip()[:4000],
             body.role, body.job, body.state, now,
             now if body.state == "closed" and r["state"] != "closed" else r["closed_at"],
             body.id))
        con.commit()
        return {"ok": True, "id": body.id, "slug": r["slug"]}
    slug = _slug(title, con)
    cur = con.execute(
        "INSERT INTO job_postings(slug,title,department,location,remote,kind,"
        " pay_text,description,requirements,role,job,state,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (slug, title, body.department.strip()[:80], body.location.strip()[:120],
         int(body.remote), body.kind, body.pay_text.strip()[:120],
         body.description.strip()[:8000], body.requirements.strip()[:4000],
         body.role, body.job, body.state, now, now))
    con.commit()
    return {"ok": True, "id": cur.lastrowid, "slug": slug}


class ApplicantBody(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    cover: str = ""
    posting_id: int = 0


@router.post("/api/hiring/applicants")
def applicant_add(body: ApplicantBody, user=Depends(current_user),
                  con=Depends(get_con)):
    """Typed in: the person who phoned, the CV handed over the counter."""
    if not _office(user):
        raise HTTPException(403, "office only")
    aid = add_applicant(con, name=body.name, email=body.email, phone=body.phone,
                        cover=body.cover, posting_id=body.posting_id, source="typed")
    return {"ok": True, "id": aid}


class StageBody(BaseModel):
    stage: str | None = None
    notes: str | None = None


@router.patch("/api/hiring/applicants/{aid}")
def applicant_edit(aid: int, body: StageBody, user=Depends(current_user),
                   con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    a = con.execute("SELECT * FROM applicants WHERE id=?", (aid,)).fetchone()
    if a is None:
        raise HTTPException(404, "no such applicant")
    if body.stage is not None:
        if body.stage not in STAGES:
            raise HTTPException(400, f"stage is one of {STAGES}")
        if body.stage == "hired":
            raise HTTPException(400, "hire them with the Hire button, which "
                                     "opens the account and the list")
        con.execute("UPDATE applicants SET stage=?, updated_at=? WHERE id=?",
                    (body.stage, time.time(), aid))
    if body.notes is not None:
        con.execute("UPDATE applicants SET notes=?, updated_at=? WHERE id=?",
                    (body.notes.strip()[:4000], time.time(), aid))
    con.commit()
    return {"ok": True}


@router.get("/api/hiring/applicants/{aid}/resume")
def applicant_resume(aid: int, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    a = con.execute("SELECT * FROM applicants WHERE id=?", (aid,)).fetchone()
    if a is None or not a["resume_key"]:
        raise HTTPException(404, "no file on this application")
    data = blobs.get(a["resume_key"])
    if data is None:
        raise HTTPException(404, "the file is gone")
    ext = a["resume_key"].rsplit(".", 1)[-1]
    mt = {"pdf": "application/pdf", "txt": "text/plain",
          "doc": "application/msword",
          "docx": "application/vnd.openxmlformats-officedocument."
                  "wordprocessingml.document"}.get(ext, "application/octet-stream")
    return Response(data, media_type=mt, headers={
        "Content-Disposition": f'inline; filename="{urllib.parse.quote(a["resume_name"] or "resume")}"'})


class HireBody(BaseModel):
    role: str = "employee"
    job: str = "general"
    employment: str = "employee"
    email: str = ""


@router.post("/api/hiring/applicants/{aid}/hire")
def applicant_hire(aid: int, body: HireBody, user=Depends(current_user),
                   con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    return hire(con, CFG, aid, user, role=body.role, job=body.job,
                employment=body.employment, email=body.email)


@router.get("/api/hiring/onboarding/{uid}")
def onboarding_get(uid: int, user=Depends(current_user), con=Depends(get_con)):
    if not (_office(user) or user["id"] == uid):
        raise HTTPException(403, "your own list, or the office")
    return {"tasks": onboarding_of(con, uid)}


@router.post("/api/hiring/onboarding/{tid}/done")
def onboarding_done(tid: int, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "the office ticks the list")
    t = con.execute("SELECT * FROM onboarding_tasks WHERE id=?", (tid,)).fetchone()
    if t is None:
        raise HTTPException(404, "no such task")
    if t["done_at"]:
        con.execute("UPDATE onboarding_tasks SET done_at=0, done_by='' WHERE id=?", (tid,))
    else:
        con.execute("UPDATE onboarding_tasks SET done_at=?, done_by=? WHERE id=?",
                    (time.time(), user["name"], tid))
    con.commit()
    return {"ok": True, "done": not t["done_at"]}


@router.post("/api/hiring/{name}/pull")
def hiring_pull(name: str, user=Depends(current_user), con=Depends(get_con)):
    if not _office(user):
        raise HTTPException(403, "office only")
    return pull_candidates(con, name)
