"""Part: STUDIO — the B2B paperwork. The template kit, engagements,
gates, the vault and signatures, the portal, binders, quotes and the
scope of work. A fresh database plus one founder is its whole world."""
from _harness import (ROOT, c, ok, done, mint_admin, checks,  # noqa
                      ops_app_js, ops_app_parts,  # noqa: F401
                      CFG, app)  # noqa: F401
from _harness import json, os, re, sys, tempfile, Path  # noqa: F401

admin, A = mint_admin()
from erp.backend import db as _db  # noqa: E402
from erp.backend import integrations as _ig  # noqa: E402
_ops = c.get("/ops/app.js").text

# --- the template kit names real capabilities ------------------------------
# The free consultation is where a client is told which permissions, roles and
# integrations they can have. A sales document that promises a connector the
# code does not have is worse than no document, and the drift is silent — the
# doc is prose, so nothing else would ever catch it.
_consult = Path("docs/business-control-b2b-client/templates/02-consultation/free-consultation.md").read_text()
_gov = Path("src/storefront/backend/governance.py").read_text()
_intg = Path("src/erp/backend/integrations.py").read_text()

_perms = set(re.findall(r'^    "(\w+)": "',
                        _gov.split("PERMISSIONS = {")[1].split("}")[0], re.M))
_missing = sorted(p for p in _perms if f"`{p}`" not in _consult)
ok(_perms and not _missing,
   f"the consultation offers every permission the code grants (missing: {_missing})")

_provs = set(re.findall(r'^    "([a-z_]+)": \{', _intg, re.M))
_unlisted = sorted(p for p in _provs if p not in _consult.lower())
ok(_provs and not _unlisted,
   f"and every integration that actually exists (missing: {_unlisted})")

_jobs = set(re.findall(r'"([^"]+)"',
                       ops_app_js()
                       .split("JOB_LABEL = {")[1].split("}")[0]))
_nojob = sorted(j for j in _jobs - {"general"} if j.lower() not in _consult.lower())
ok(not _nojob, f"and every staff role that has its own view (missing: {_nojob})")

# --- the kit's shape: stage folders, and the internal wall ----------------
_studio = Path("docs/business-control-b2b-client")
_stages = sorted(p.name for p in (_studio / "templates").iterdir() if p.is_dir())
ok(len(_stages) == 11 and _stages[0].startswith("01-")
   and all(re.match(r"\d\d-", s) for s in _stages),
   f"the templates are filed by numbered stage, so the order is the folder "
   f"listing rather than something to remember ({len(_stages)} stages)")

_no_readme = [s for s in _stages
              if not (_studio / "templates" / s / "README.md").exists()]
ok(not _no_readme,
   f"every stage says what it sends and what opens the next gate "
   f"(missing: {_no_readme})")

_root = (_studio / "README.md").read_text()
ok(all(f"templates/{s}/" in _root for s in _stages),
   "and the index links every one of them")

# --- aftercare covers the work that is actually continuous ----------------
# "Ongoing support" in a contract is worth what its schedule says and no more.
# Clause 15 promises security, monitoring, defect support and compliance; if
# no page defines them, the clause is a sentence the client reads their own
# hopes into.
from storefront.backend.engagements import side_of as _side_of
_after = _studio / "templates" / "11-aftercare"
_care = (_after / "care-plan-agreement.md").read_text()
_supp = (_after / "support-and-defects.md").read_text()
_mon = (_after / "monitoring-and-incidents.md").read_text()
_sec = (_after / "security-and-compliance.md").read_text()
_grow = (_after / "growth-retainer.md").read_text()

ok(all(_side_of(t) == "to_client" for t in (_care, _supp, _mon, _sec, _grow))
   and all("[SIGN HERE]" in t for t in (_supp, _mon, _sec, _grow)),
   "every ongoing-work schedule is a client document that gets signed — an "
   "unsigned promise about response times is a preference")

ok("Defect, or change?" in _supp and _supp.count("**Defect**") >= 4
   and all(f"**{p} " in _supp for p in ("P1", "P2", "P3", "P4"))
   and "First response" in _supp,
   "support defines the bug it will fix free, against the change it will "
   "bill for, with severities and a first-response time for each")

ok("[SUPPORT EMAIL / PORTAL]" in _supp and "[30] days" in _supp,
   "one route in, and the no-plan warranty window said out loud")

ok(all(w in _mon for w in ("Uptime", "Key journeys", "SSL certificate",
                           "Backups", "Malware", "Escalation"))
   and _mon.count("Every **[") >= 2,
   "monitoring names what is watched and how often, not just that it is")

ok("Alerts go to the Studio first, not to you" in _mon
   and "Primary" in _mon and "Backup" in _mon,
   "and it routes the alert to the studio, with the client contact we may "
   "ring at night written down before the night we need it")

ok("Critical" in _sec and "[24] hours" in _sec
   and "Dependency scanning" in _sec and "Restore tested" in _sec,
   "security is a cadence — patch windows by severity, weekly scanning, and "
   "a restore actually tested rather than assumed")

ok("72 hours" in _sec and "Compliance in scope" in _sec
   and all(k in _sec for k in ("WCAG", "GDPR", "PCI")),
   "and it ticks the compliance scope and states the breach clock, which is "
   "the client's to run and ours to make runnable")

ok("Who holds what" in _sec and "You own every account" in _sec,
   "credentials are inventoried and the client owns them — access to work, "
   "not leverage")

ok("SEO campaigns and advertising" in _care
   and "growth-retainer.md" in _care and "Ad spend is not the fee" in _grow
   and "You own every account" in _grow,
   "growth work is sold beside the care plan and never inside it: separate "
   "money, separate cancellation, and the ad accounts stay the client's")

for _sched in ("support-and-defects.md", "monitoring-and-incidents.md",
               "security-and-compliance.md"):
    ok(_sched in _care, f"the care plan links its {_sched} schedule")

_cc = (_studio / "templates/04-agreement/contracts/common-clauses.md").read_text()
ok(all(f"11-aftercare/{d}" in _cc for d in
       ("security-and-compliance.md", "monitoring-and-incidents.md",
        "support-and-defects.md", "growth-retainer.md")),
   "and clause 15 points at those schedules by name — the contract promises "
   "exactly what a page defines, and nothing looser")

ok((_studio / "procedures/running-a-care-plan.md").exists()
   and "Never send this to a client" in
       (_studio / "procedures/running-a-care-plan.md").read_text(),
   "and there is an internal procedure for actually running the cadence the "
   "client bought, because a plan billed monthly and touched on breakage is "
   "the one you lose at renewal")

# The wall between what a client may read and what they may not is the whole
# reason the per-client folder is shaped this way; a stage folder missing one
# side is the one that gets zipped and sent by mistake.
_ct = _studio / "clients" / "_template"
_cstages = sorted(p.name for p in _ct.iterdir() if p.is_dir())
_unwalled = [s for s in _cstages
             if not ((_ct / s / "to-client").is_dir()
                     and (_ct / s / "internal").is_dir())]
ok(_cstages and not _unwalled,
   f"every client stage separates what they receive from what they must not "
   f"(unwalled: {_unwalled})")

ok("roadmap.md" in _root and (_studio / "roadmap.md").exists(),
   "the delivery, deployment and setup roadmap is in the kit and linked from it")
_road = (_studio / "roadmap.md").read_text()
ok("../product/DEPLOY.md" in _road,
   "and it points at the technical runbook rather than duplicating it — a "
   "second copy of deployment steps is a copy that goes stale silently")

# docs/ has two halves and they must not blur: the product's own docs, and
# the client-facing kit. An index in each is what keeps a stray file from
# landing in the wrong one and being sent to the wrong audience.
# docs/ itself needs an index, or the two halves are two piles.
_docs_idx = Path("docs/README.md")
ok(_docs_idx.exists(), "docs/ has an index naming both halves")
_di = _docs_idx.read_text()
ok("product/" in _di and "business-control-b2b-client/" in _di,
   "and it points at each of them")
_docs_dirs = sorted(p.name for p in Path("docs").iterdir() if p.is_dir())
_unindexed = [d for d in _docs_dirs if d not in _di]
ok(not _unindexed,
   f"and every folder under docs/ is accounted for (missing: {_unindexed})")

# The client folder is the thing someone opens under time pressure; a stage
# that doesn't say what belongs in it gets filled by guesswork.
_ct = Path("docs/business-control-b2b-client/clients/_template")
_cst = sorted(p.name for p in _ct.iterdir() if p.is_dir())
_vague = [d for d in _cst
          if "What lands here" not in (_ct / d / "README.md").read_text()]
ok(not _vague,
   f"every client stage says what lands in it, on both sides of the wall "
   f"(vague: {_vague})")
_board = (_ct / "README.md").read_text()
ok("06 Brand" in _board and "10 Aftercare" in _board,
   "and the status board's stages match the folders beside it")
ok("project-roadmap.md" in _board,
   "and it names its client-facing twin — two status documents that disagree "
   "is worse than one, because now nobody trusts either")
ok("Gates passed" in _board and "Deposit cleared" in _board,
   "the board tracks gates as signatures, not as feelings")

_prod = Path("docs/product/README.md")
ok(_prod.exists(), "the product docs have an index of their own")
_pr_txt = _prod.read_text()
_prod_files = sorted(p.name for p in Path("docs/product").iterdir()
                     if p.name != "README.md")
_unlisted = [f for f in _prod_files if f not in _pr_txt]
ok(not _unlisted, f"and it lists every document in the folder (missing: {_unlisted})")
ok("business-control-b2b-client" in _pr_txt,
   "and points at the client-facing kit rather than absorbing it")

# A wet-ink signature table next to an electronic Signed block reads as
# broken blank space. Every template that carries the table says which is
# which — on its face, where the person filling it in is looking.
_tabled = [str(p.relative_to(_studio)) for p in
           (_studio / "templates").rglob("*.md")
           if "| Signature | | |" in p.read_text()]
_unnoted = [f for f in _tabled if "Signing electronically?"
            not in (_studio / f).read_text()]
ok(_tabled and not _unnoted,
   f"every signature table explains the electronic path beside the wet-ink "
   f"one (missing: {_unnoted})")

ok("packages-and-process.md" in _root and "free-consultation.md" in _root,
   "and both consultation documents are in the kit's index, not just on disk")

# The client gets their own roadmap — a different document from the studio's
# delivery guide, and the pair is easy to confuse precisely because both are
# called a roadmap. Each must say which one it is.
_proj = _studio / "templates" / "05-kickoff" / "project-roadmap.md"
ok(_proj.exists(), "the client gets a roadmap of their own, to track execution")
_pr = _proj.read_text()
ok("Client-facing" in _pr and "roadmap.md" in _pr,
   "and it says plainly that it is theirs, and points at the internal one it "
   "is not")
ok("internal" in _road.split("\n")[0:6].__str__().lower()
   or "Internal" in _road[:400],
   "while the delivery roadmap says plainly that it is not for sending")
ok("Last updated" in _pr and "Right now" in _pr,
   "it carries a current status, so re-sending it is the update")
ok("project-roadmap.md" in (_studio / "procedures" / "weekly-rhythm.md").read_text(),
   "and the weekly rhythm is what re-sends it — a status document nobody "
   "updates is worse than none, because it reads as current")

# The rate card must never reach a client. The index is hand-edited, so the
# guarantee is asserted on the document itself rather than on prose elsewhere.
_rate = (_studio / "templates" / "03-proposal" / "rate-card.md").read_text()
ok("Never send this to a client" in _rate,
   "the rate card says on its own face that it is internal — a price list "
   "invites line-item haggling over work priced as a whole")

# The optional brand stage, for work where the look is the point.
_brand = _studio / "templates" / "07-brand-exploration"
ok(_brand.is_dir() and (_brand / "art-direction.md").exists()
   and (_brand / "direction-review-form.md").exists()
   and (_brand / "brand-exploration-brief.md").exists(),
   "brand exploration is its own stage: a brief, directions to react to, and "
   "a signed art direction")
_bre = (_brand / "README.md").read_text()
ok("Optional" in _bre and "Week website" in _bre,
   "and it says when to skip it — a stage that always runs is not optional, "
   "it is overhead")
ok("art-direction" in (_studio / "clients" / "_template"
                       / "06-brand-exploration" / "README.md").read_text(),
   "the client folder has a home for the signed direction, which is what "
   "settles 'we never agreed to that' in month four")

# --- engagements: the kit, run from the ERP --------------------------------
# The registry is the kit folder read live, sides are derived from the
# documents' own faces, and the client bundle is drawn from the to-client
# side only — each asserted here because each is a wall someone will lean on.
_tj = c.get("/api/store/admin/engagements/templates", headers=A).json()
ok(_tj["kit_available"] and len(_tj["stages"]) == 11,
   "the template registry is the kit folder itself, all eleven stages — "
   "nothing to keep in sync")
_all_t = [t for st in _tj["stages"] for t in st["templates"]]
_by = {t["path"]: t for t in _all_t}
ok(_by["03-proposal/rate-card.md"]["side"] == "internal",
   "the rate card derives 'internal' from its own text, not from a list")
ok(_by["03-proposal/proposal-template.md"]["side"] == "to_client",
   "and the proposal goes to the client")
ok(all(t["side"] == "internal" for t in _all_t
       if "discovery-brief" in t["path"] or "exploration-brief" in t["path"]),
   "every brief that says 'never send' is born on the internal side")

_eng = c.post("/api/store/admin/engagements", headers=A, json={
    "name": "Smoke Test Client", "package": "B", "value_cents": 1200000,
    "approver_name": "Alex Chen", "approver_email": "alex@smoke.test",
    "launch_target": "2026-12-01"}).json()
_eid = _eng["id"]
ok(_eng["slug"] == "smoke-test-client", "a client becomes a slug, safely")

_td = c.get(f"/api/store/admin/engagements/{_eid}/template", headers=A,
            params={"path": "03-proposal/proposal-template.md"}).json()
ok("CLIENT NAME" in _td["placeholders"] and "DATE" in _td["placeholders"],
   "placeholders are read out of the template's brackets")
ok(_td["suggested"].get("CLIENT NAME") == "Smoke Test Client"
   and _td["suggested"].get("X") == "12,000",
   "and the engagement record pre-fills them — the proposal and the record "
   "cannot disagree about the number, because both read the same row")

_gen = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "03-proposal/proposal-template.md",
    "fills": {"NAME, ROLE": "Alex Chen, COO"}}).json()
ok(_gen["side"] == "to_client" and _gen["unfilled"],
   "generation lands on the derived side and counts what is left to fill")
_vd = [d for d in c.get("/api/store/admin/documents", headers=A,
       params={"q": "Smoke Test Client"}).json()["documents"]
       if d["id"] == _gen["doc_id"]][0]
ok("[" not in _vd["title"] and "Smoke Test Client" in _vd["title"],
   "the title is taken from the filled text — no bracket ships in a title")
c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A,
       json={"template_path": "03-proposal/rate-card.md"})

ok(c.get(f"/api/store/admin/engagements/{_eid}/template", headers=A,
         params={"path": "../../../product/DEPLOY.md"}).status_code == 404,
   "a template path cannot walk out of the kit")

_exp = c.post(f"/api/store/admin/engagements/{_eid}/export",
              headers=A).json()
ok(any(f.startswith("02-proposal/to-client/") for f in _exp["files"])
   and any(f.startswith("02-proposal/internal/") for f in _exp["files"]),
   "the folder export matches the clients/_template convention, walls intact")
ok(Path(_exp["root"], "README.md").exists(),
   "with a generated status board at the root")

import io as _io
import zipfile as _zip
_zr = c.get(f"/api/store/admin/engagements/{_eid}/export.zip", headers=A)
_names = _zip.ZipFile(_io.BytesIO(_zr.content)).namelist()
ok(_names and all("/internal/" not in n for n in _names),
   "the client bundle is drawn from side='to_client' only — sending the "
   "estimate along with the proposal is not possible from this door")
_zall = c.get(f"/api/store/admin/engagements/{_eid}/export.zip",
              headers=A, params={"side": "all"})
ok("full-archive" in _zall.headers.get("content-disposition", ""),
   "and the everything-zip is named full-archive, so nobody mistakes it")

_sr = c.post(f"/api/store/admin/documents/{_gen['doc_id']}/request-signature",
             headers=A, json={"signer_name": "Alex Chen",
                              "signer_email": "alex@smoke.test",
                              "role": "approver"}).json()
ok("/sign/" in _sr["link"],
   "a generated document signs through the vault's own flow — this module "
   "grew no signature code of its own")
_det = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(any(d["awaiting"] for d in _det["docs"]),
   "and the engagement sees the pending signature without copying any state")

# --- gates: signatures with a stage attached -------------------------------
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(len(_gd["gates"]) == 10 and _gd["current_stage"] == "02-proposal",
   "an engagement opens with every gate open, standing at the proposal")
ok(_gd["gates"][-1]["gate"] == "ongoing_support_agreed",
   "and the last gate is the ongoing one — security, monitoring, updates "
   "and bug support are continuous work, not an afterthought, and the care "
   "plan is where the contract says how they're carried")
ok(not next(g for g in _gd["gates"]
            if g["gate"] == "art_direction_signed")["active"],
   "the art direction gate doesn't exist until brand work does — a week "
   "website is never blocked on a stage it skipped")

_dep = c.post(f"/api/store/admin/engagements/{_eid}/gates/deposit_cleared",
              headers=A, json={"note": "wire ref 9001"}).json()
ok(_dep["gate"]["via"] == "manual" and _dep["gate"]["passed_at"],
   "a money gate is a manual confirmation with an actor and a timestamp")
ok("Proposal accepted" in _dep["warnings"],
   "and passing it out of order warns loudly instead of silently allowing "
   "or hard-blocking")
ok(c.post(f"/api/store/admin/engagements/{_eid}/gates/contract_signed",
          headers=A, json={}).status_code == 400,
   "a signature gate passed by hand demands a note saying where the "
   "evidence is filed — the point of a gate is that you can point at it")

_link = c.post(f"/api/store/admin/engagements/{_eid}/gates/proposal_accepted",
               headers=A, json={"doc_id": _gen["doc_id"]}).json()
ok(not _link["gate"]["passed_at"],
   "linking an unsigned document leaves the gate awaiting, not passed")
_sr2 = c.post(f"/api/store/admin/documents/{_gen['doc_id']}/request-signature",
              headers=A, json={"signer_name": "Alex Chen",
                               "signer_email": "alex@smoke.test",
                               "role": "approver"}).json()
_tok = _sr2["link"].split("/sign/")[1]
_page = c.get(f"/sign/{_tok}").text
ok("<h3>" in _page or "<table>" in _page or "<ul>" in _page,
   "the sign page renders the document's structure — a signature attests to "
   "what the signer was shown, so the shown thing carries the real headings "
   "and tables, not paragraph soup")
c.post(f"/sign/{_tok}", json={"typed_name": "Alex Chen"})
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
_pa = next(g for g in _gd["gates"] if g["gate"] == "proposal_accepted")
ok(_pa["via"] == "signature" and _pa["signed_by"] == "Alex Chen",
   "and once signed, the gate passes by derivation — read from the vault "
   "at request time, no copied state, no sync job")
c.post(f"/api/store/admin/engagements/{_eid}/gates/contract_signed",
       headers=A, json={"note": "countersigned PDF, filed 03-agreement"})
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(_gd["current_stage"] == "05-requirements",
   "the stage is the first open gate — proposal, contract and deposit "
   "passed walks it to requirements, and no stage column exists to disagree")

_alien = c.post("/api/store/admin/documents", headers=A,
                json={"title": "Someone else's paper", "body": "x"}).json()
ok(c.post(f"/api/store/admin/engagements/{_eid}/gates/handover_accepted",
          headers=A, json={"doc_id": _alien["id"]}).status_code == 400,
   "a gate only accepts documents filed under its own client — an unrelated "
   "signature would make the gate attest to nothing")
c.delete(f"/api/store/admin/documents/{_alien['id']}", headers=A)

c.request("DELETE",
          f"/api/store/admin/engagements/{_eid}/gates/contract_signed",
          headers=A)
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(_gd["current_stage"] == "03-agreement",
   "reopening a gate moves the stage back by the same derivation, and the "
   "signed evidence stays in the vault untouched")

# --- archiving a client ----------------------------------------------------
_ar = c.post("/api/store/admin/engagements", headers=A,
             json={"name": "Parked Smoke"}).json()
_arl = lambda a=0: c.get("/api/store/admin/engagements", headers=A,
                         params={"archived": a}).json()
ok(any(x["name"] == "Parked Smoke" for x in _arl()["engagements"]),
   "a new client is on the working list")
c.post(f"/api/store/admin/engagements/{_ar['id']}/archive", headers=A,
       json={"archived": True})
ok(all(x["name"] != "Parked Smoke" for x in _arl()["engagements"])
   and any(x["name"] == "Parked Smoke" for x in _arl(1)["engagements"]),
   "archiving puts a client away — off the working list, on the archived "
   "one, counted on its own chip")
_ard = c.get(f"/api/store/admin/engagements/{_ar['id']}", headers=A).json()
ok(len(_ard["docs"]) >= 2 and _ard["engagement"]["status"] == "archived",
   "and nothing is removed: the documents, gates and dates are as they "
   "were, which is the difference between archiving and deleting")
c.post(f"/api/store/admin/engagements/{_ar['id']}/archive", headers=A,
       json={"archived": False})
ok(any(x["name"] == "Parked Smoke" for x in _arl()["engagements"]),
   "so it comes back — one is reversible, the other is a decision")
c.delete(f"/api/store/admin/engagements/{_ar['id']}", headers=A)

# --- deleting a client -----------------------------------------------------
_dd = c.post("/api/store/admin/engagements", headers=A,
             json={"name": "Doomed Smoke"}).json()
_dsign = c.post(f"/api/store/admin/engagements/{_dd['id']}/docs", headers=A,
                json={"template_path": "05-kickoff/welcome-guide.md"}).json()
_dplain = c.post(f"/api/store/admin/engagements/{_dd['id']}/docs", headers=A,
                 json={"template_path": "03-proposal/proposal-template.md"}
                 ).json()
_dsr = c.post(f"/api/store/admin/documents/{_dsign['doc_id']}"
              "/request-signature", headers=A,
              json={"signer_name": "Pat", "signer_email": "p@x.t",
                    "role": "signer", "in_person": True}).json()
c.post(f"/sign/{_dsr['link'].split('/sign/')[1]}",
       json={"typed_name": "Pat"})
_dout = c.delete(f"/api/store/admin/engagements/{_dd['id']}",
                 headers=A).json()
ok(_dout["kept"] == 1 and _dout["removed"] >= 2,
   "deleting a client takes the paperwork that only existed for them — "
   "except anything signed, because deleting the client does not un-agree "
   "what a named person agreed to")
ok(c.get(f"/api/store/admin/engagements/{_dd['id']}",
         headers=A).status_code == 404, "and the client is gone")
_gone = _db.connect().execute("SELECT status FROM documents WHERE id=?",
                              (_dplain["doc_id"],)).fetchone()
ok(_gone is None, "an unsigned draft goes with it")
_kept = _db.connect().execute("SELECT status FROM documents WHERE id=?",
                              (_dsign["doc_id"],)).fetchone()
ok(_kept and _kept["status"] == "archived",
   "the signed one is archived, not destroyed")
_arch = c.get("/api/store/admin/documents", headers=A,
              params={"archived": 1}).json()
ok(any(d["id"] == _dsign["doc_id"] for d in _arch["documents"])
   and _arch["archived_count"] >= 1,
   "and it is findable — evidence you cannot find is a gesture, so "
   "Documents has an Archived view rather than hiding it for good")
_conk = _db.connect()
_conk.execute("DELETE FROM document_signatures WHERE document_id=?",
              (_dsign["doc_id"],))
_conk.execute("DELETE FROM document_events WHERE document_id=?",
              (_dsign["doc_id"],))
_conk.execute("DELETE FROM documents WHERE id=?", (_dsign["doc_id"],))
_conk.commit(); _conk.close()

# --- the client portal: one link, drawn from the same rows -----------------
ok(c.get("/engage/nope").status_code == 404, "a made-up portal token is a 404")
_purl = c.post(f"/api/store/admin/engagements/{_eid}/portal",
               headers=A).json()["url"]
_ptok = _purl.split("/engage/")[1]
c.patch(f"/api/store/admin/engagements/{_eid}", headers=A,
        json={"content_pct": 40, "week_note": "Round one went out.",
              "blockers": "Waiting on photography (since 20 Aug)"})
c.put(f"/api/store/admin/engagements/{_eid}/dates", headers=A,
      json={"dates": [{"label": "Launch", "planned": "2026-12-01"}]})
_pp = c.get(f"/engage/{_ptok}").text
ok("Round one went out." in _pp and "width:40%" in _pp
   and "Waiting on photography" in _pp and "2026-12-01" in _pp,
   "the portal renders the roadmap from the record — note, content bar, "
   "blockers and dates, nothing retyped")
ok("done" in _pp and "in progress" in _pp,
   "and the gate timeline reads live from the same gates the ERP shows")
ok("Rate card" not in _pp,
   "the internal side is invisible on the portal — not withheld, unreachable")
ok(c.get(f"/engage/{_ptok}/doc/{_gen['doc_id']}").status_code == 200,
   "a to-client document opens from its portal link")
_rate_id = next(d["id"] for d in _gd["docs"] if d["side"] == "internal")
ok(c.get(f"/engage/{_ptok}/doc/{_rate_id}").status_code == 404,
   "and the internal document 404s through the same route — the wall is the "
   "query, not discipline")
ok("awaiting your signature" in _pp or "signed" in _pp,
   "signature state surfaces on the portal; signing stays on /sign/")

ok(c.post(f"/engage/{_ptok}/direction",
          data={"choice": "1", "name": "P"}).status_code == 400,
   "a direction can't be chosen before any brand work exists")
c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A,
       json={"template_path": "07-brand-exploration/direction-review-form.md"})
_pp = c.get(f"/engage/{_ptok}").text
ok("Choose a direction" in _pp,
   "brand work on the portal brings the choice form with it")
_dc = c.post(f"/engage/{_ptok}/direction",
             data={"choice": "Direction 2 — Quiet Authority",
                   "name": "Alex Chen", "works": "calm palette"})
ok(_dc.status_code == 200, "the client's choice records from the portal")
ok(c.post(f"/engage/{_ptok}/direction",
          data={"choice": "3", "name": "B"}).status_code == 400,
   "one consolidated response means one — a second submission is refused")
_gd = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(any("direction chosen" in l["what"] for l in _gd["log"])
   and any("Direction choice" in d["title"] for d in _gd["docs"]),
   "and the choice lands as a filed document plus a log entry — the folder "
   "convention already had a home for the returned form")
_pgate = next(g for g in _gd["gates"] if g["gate"] == "art_direction_signed")
ok(_pgate["active"],
   "brand work existing is also what wakes the art direction gate")

c.request("DELETE", f"/api/store/admin/engagements/{_eid}/portal", headers=A)
ok(c.get(f"/engage/{_ptok}").status_code == 404,
   "revoking the link kills it immediately — rotation is revocation with a "
   "forwarding address")

# --- rhythm and filing -----------------------------------------------------
_purl2 = c.post(f"/api/store/admin/engagements/{_eid}/portal",
                headers=A).json()["url"]
c.patch(f"/api/store/admin/engagements/{_eid}", headers=A,
        json={"blockers": "waiting on the logo (since Monday)"})
_me = next(x for x in c.get("/api/store/admin/engagements", headers=A)
           .json()["engagements"] if x["id"] == _eid)
ok("blocked" in _me["warnings"],
   "the dashboard derives the weekly-rhythm checks server-side — a blocked "
   "engagement says so in the list, not just three clicks deep")
c.patch(f"/api/store/admin/engagements/{_eid}", headers=A,
        json={"blockers": ""})
_me = next(x for x in c.get("/api/store/admin/engagements", headers=A)
           .json()["engagements"] if x["id"] == _eid)
ok("blocked" not in _me["warnings"],
   "and clearing the blockers clears the warning — 'no blockers' is the "
   "good news, so it must be expressible")
c.get(_purl2.split("http://testserver")[-1])
_me = next(x for x in c.get("/api/store/admin/engagements", headers=A)
           .json()["engagements"] if x["id"] == _eid)
ok(_me["portal_seen_at"] > 0,
   "a portal view stamps when the client last looked — the honest half of "
   "'did they see it'")

from erp.backend import integrations as _intg
ok("gate.passed" in _intg.EVENT_LABELS
   and "direction.chosen" in _intg.EVENT_LABELS,
   "gate passage and direction choices are events on the same bus as "
   "inventory.low")
ok("gate.passed" in _intg.PROVIDERS["slack"]["events"]
   and "direction.chosen" in _intg.PROVIDERS["trello"]["events"],
   "slack hears both; trello gets a card only for the one that is work — "
   "writing up the art direction")
ok("write up the art direction" in _intg._line(
    "direction.chosen", {"client": "X", "choice": "2"}),
   "and the prose says what to do next, not just what happened")
ok(callable(getattr(_intg, "dropbox_put", None)),
   "the export can file through the same Dropbox connection that files "
   "signed documents")
_exp2 = c.post(f"/api/store/admin/engagements/{_eid}/export",
               headers=A).json()
ok(_exp2["dropbox"] in ("filing in the background", "not connected"),
   "and the export says plainly whether Dropbox filing happened — a silent "
   "non-filing would read as filed")

_pl = c.post(f"/api/store/admin/engagements/{_eid}/gates/deposit_cleared"
             "/payment-link", headers=A, json={"amount_cents": 500000})
ok(_pl.status_code == 400 and "manually" in _pl.json()["detail"],
   "with no Stripe key the payment link refuses and points at the manual "
   "path — cheques and transfers never stopped working")
ok(c.post(f"/api/store/admin/engagements/{_eid}/gates/requirements_signed"
          "/payment-link", headers=A,
          json={"amount_cents": 1}).status_code == 400,
   "and payment links exist only for the money gates — a signature gate "
   "passed by card would attest to nothing")
ok(c.post(f"/api/store/admin/engagements/{_eid}/gates/deposit_cleared"
          "/payment-check", headers=A).status_code == 400,
   "checking a payment that was never linked is a clear error, not a quiet "
   "'not paid'")
import shutil as _sh2
_sh2.rmtree(_exp2["root"], ignore_errors=True)

# --- seeing, downloading and finishing the documents -----------------------
_det2 = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
_row = next(d for d in _det2["docs"] if d["id"] == _gen["doc_id"])
ok(_row["has_body"] and _row["blanks"] > 0,
   "each stage row says how many brackets a document still has — finished "
   "is a number going to zero, not a feeling")
_pv = c.get(f"/api/store/admin/documents/{_gen['doc_id']}/preview", headers=A)
ok(_pv.status_code == 200 and ("<h2" in _pv.text or "<table" in _pv.text),
   "View renders the document with the sign page's own renderer — what you "
   "check is exactly what a signer will be shown")
_dl = c.get(f"/api/store/admin/documents/{_gen['doc_id']}/markdown",
            headers=A)
ok(_dl.status_code == 200
   and "attachment" in _dl.headers.get("content-disposition", ""),
   "and an authored document downloads as its markdown")

_bl = c.get(f"/api/store/admin/engagements/{_eid}/docs/{_gen['doc_id']}"
            "/blanks", headers=A).json()
ok(_bl["placeholders"],
   "the blanks endpoint lists what is left, with the same suggestions "
   "generation had — finishing is the same form as starting, shorter")
_locked = c.post(f"/api/store/admin/engagements/{_eid}/docs/"
                 f"{_gen['doc_id']}/fill", headers=A,
                 json={"fills": {_bl["placeholders"][0]: "x"}})
ok(_locked.status_code == 400 and "signed" in _locked.json()["detail"],
   "a signed document refuses further filling — its text is what was "
   "attested to; supersede it, don't edit it")

_g2 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "05-kickoff/welcome-guide.md"}).json()
_b2 = c.get(f"/api/store/admin/engagements/{_eid}/docs/{_g2['doc_id']}"
            "/blanks", headers=A).json()
_tok0 = _b2["placeholders"][0]
_ff = c.post(f"/api/store/admin/engagements/{_eid}/docs/{_g2['doc_id']}"
             "/fill", headers=A, json={"fills": {_tok0: "filled-now"}}).json()
ok(_tok0 not in _ff["unfilled"]
   and len(_ff["unfilled"]) == len(_b2["placeholders"]) - 1,
   "filling from the UI populates the template in place, token by token")

# --- PDFs everywhere a document appears ------------------------------------
_pdf = c.get(f"/api/store/admin/documents/{_g2['doc_id']}/pdf", headers=A)
ok(_pdf.status_code == 200 and _pdf.content[:5] == b"%PDF-"
   and "inline" in _pdf.headers.get("content-disposition", ""),
   "an authored document renders to a real PDF, served inline so the "
   "browser's own viewer is the preview")
_pdfd = c.get(f"/api/store/admin/documents/{_g2['doc_id']}/pdf?download=1",
              headers=A)
ok("attachment" in _pdfd.headers.get("content-disposition", ""),
   "and downloads as one when asked")
ok(c.get(f"/sign/{_tok}/pdf").content[:5] == b"%PDF-",
   "the signer can take a PDF copy from the same parse they signed")
_p3 = c.post(f"/api/store/admin/engagements/{_eid}/portal",
             headers=A).json()["url"].split("/engage/")[1]
ok(c.get(f"/engage/{_p3}/pdf/{_gen['doc_id']}").content[:5] == b"%PDF-",
   "the client can take a PDF of anything on their side of the wall")
ok(c.get(f"/engage/{_p3}/pdf/{_rate_id}").status_code == 404,
   "and nothing on the other side — the .pdf route holds the same wall")
_exp3 = c.post(f"/api/store/admin/engagements/{_eid}/export",
               headers=A).json()
ok(any(f.endswith(".pdf") for f in _exp3["files"]),
   "exports carry the PDF beside the markdown — the .md is for editing, "
   "the .pdf is for sending")

# --- signatures on the PDF, DocuSign in the slot, and the next step --------
import zlib as _zl
_spdf = c.get(f"/api/store/admin/documents/{_gen['doc_id']}/pdf",
              headers=A).content
_st = ""
for _m in re.finditer(rb'stream\r?\n(.*?)endstream', _spdf, re.S):
    try:
        _st += _zl.decompress(_m.group(1)).decode("latin-1", "replace")
    except Exception:
        pass
_shown = " ".join(re.findall(r'\((.*?)\)\s*Tj', _st))
ok("Signed" in _shown and "Alex Chen" in _shown and "reference" in _shown,
   "a signed document's PDF carries the signature on its face — name, date "
   "and reference; a signed PDF that shows no signature reads as unsigned "
   "to everyone it gets forwarded to")

from storefront.backend import documents as _docmod
ok("docusign" in _ig.PROVIDERS,
   "DocuSign is an integrations provider, so its form comes from the same "
   "declaration machinery as every other connection")
_env = _docmod.docusign_envelope("T", "QUJD", "N", "n@x.t", "hi")
ok(_env["status"] == "sent"
   and _env["documents"][0]["documentBase64"] == "QUJD"
   and _env["recipients"]["signers"][0]["tabs"]["signHereTabs"],
   "the envelope carries our own PDF and a sign-here anchor — the signer "
   "is shown the same bytes a builtin signer would be")
_con_p = _db.connect()
ok(_docmod.esign_provider(_con_p) == "builtin",
   "with DocuSign unconnected the provider derives to builtin — connecting "
   "it IS the choice, and there is no second switch to forget")
_con_p.close()
_rr = c.post(f"/api/store/admin/signatures/{_sr2['id']}/refresh", headers=A)
ok(_rr.status_code == 200
   and _rr.json().get("detail") == "not a DocuSign request",
   "refreshing a builtin request is a polite no-op, not an error")

ok('data-next=' in _ops and "nextStep" in _ops,
   "the next step sits atop the gates — derived from the same gates, one "
   "primary action, so the answer to 'what now?' never needs the manual")
ok("GATE_STAGE" in _ops and "03-proposal" in _ops.split("GATE_STAGE")[1][:400],
   "and each gate names the kit stage whose templates satisfy it, so "
   "generating the right document for this client is the one click")

# --- in-person signing, and taking documents back out ----------------------
_g3 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "01-potential-customer/email-scripts.md"}).json()
_ip = c.post(f"/api/store/admin/documents/{_g3['doc_id']}/request-signature",
             headers=A, json={"signer_name": "Here Now",
                              "signer_email": "here@now.test",
                              "role": "signer", "in_person": True}).json()
ok(_ip.get("in_person") and "/sign/" in _ip["link"],
   "in-person signing opens the same pad, right here — no request email; "
   "the only email is the receipt, after signing")
_ipt = _ip["link"].split("/sign/")[1]
ok("mousedown" in c.get(f"/sign/{_ipt}").text,
   "and the pad draws with the mouse, so a cursor is a pen")
c.post(f"/sign/{_ipt}", json={"typed_name": "Here Now"})
ok(c.get(f"/sign/{_ipt}").text.count("Signed") >= 1,
   "signed in the room, recorded like any other signature")

# The drawn mark and the facts, on every surface the document shows on.
import base64 as _b64
import io as _io2
from PIL import Image as _Im, ImageDraw as _ImD
_im = _Im.new("RGBA", (600, 160), (0, 0, 0, 0))
_ImD.Draw(_im).line([(60, 110), (320, 40), (540, 100)],
                    fill=(25, 25, 80, 255), width=7)
_ib = _io2.BytesIO(); _im.save(_ib, "PNG")
_mark = "data:image/png;base64," + _b64.b64encode(_ib.getvalue()).decode()
c.post(f"/sign/{_ipt}/decline", json={})  # no-op guard: already signed above
_pv2 = c.get(f"/api/store/admin/documents/{_g3['doc_id']}/preview",
             headers=A).text
ok(">Signed<" in _pv2 and "Here Now" in _pv2,
   "the View page shows the signature block — a signed document must never "
   "look unsigned exactly where you look at it")
_sp2 = c.get(f"/sign/{_ipt}").text
ok(">Signed<" in _sp2,
   "and the signer's own page carries it after signing")

_un = c.request("DELETE",
                f"/api/store/admin/engagements/{_eid}/docs/{_g3['doc_id']}",
                headers=A)
ok(_un.status_code == 200,
   "a document can be unfiled from the client while the vault keeps it")
_gd3 = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(all(d["id"] != _g3["doc_id"] for d in _gd3["docs"]),
   "gone from the client's stages")
_vd3 = c.get("/api/store/admin/documents", headers=A,
             params={"q": "Email scripts"}).json()["documents"]
ok(any(d["id"] == _g3["doc_id"] for d in _vd3),
   "still in the vault — unfiling is not deleting")
_del3 = c.delete(f"/api/store/admin/documents/{_g3['doc_id']}",
                 headers=A).json()
ok(_del3.get("archived"),
   "and vault deletion archives it, because it carries a signature — "
   "evidence is never destroyed by tidying")

# --- sections fold, and stay folded ----------------------------------------
_opsjs = c.get("/ops/app.js").text
_opscss = c.get("/ops/styles.css").text
ok('foldable("gates"' in _opsjs and 'foldable(`stage:' in _opsjs
   and 'foldable("activity"' in _opsjs,
   "the gates, each stage and the activity log fold away — a client's page "
   "is long, and the stage you are not working in is noise")
ok('localStorage.setItem("bc_folded"' in _opsjs
   and 'localStorage.getItem("bc_folded")' in _opsjs,
   "and the fold is remembered, because the page re-renders on every gate "
   "action and a fold that reopened each time would be worthless")
ok(".foldable.folded > .fold-body { display: none; }" in _opscss
   and ".foldable.folded > .fold-head .fold-caret" in _opscss,
   "folding hides the body and turns the caret — one class, both signals, "
   "and the child selector keeps a folded stage from speaking for the "
   "documents folded inside it")
ok('data-fold="doc:${x.id}"' in _opsjs and 'class="dl-title fold-head"' in _opsjs
   and 'class="dl-acts fold-body"' in _opsjs,
   "a document folds to its own title line — seven buttons per document is "
   "a lot of page for a stage you are only reading")
ok('" blank" + (x.blanks === 1 ? "" : "s") + " left"' in _opsjs,
   "and the folded line keeps the number that decides whether you open it")
ok(_opsjs.index('class="dm-state"') < _opsjs.index('class="dm-side"')
   < _opsjs.index('class="dm-blanks'),
   "read in the order the question comes: what is it waiting on, whose "
   "side is it on, how much of it is still blank")
ok(".dl-meta { display: grid; grid-template-columns: 104px 70px 84px;"
   in _opscss,
   "in fixed slots, because the alignment is the information — pills that "
   "start wherever each title happens to end cannot be scanned down a "
   "stage, only read across a row")
ok(".doc-line:not(.folded) .dm-blanks { visibility: hidden; }" in _opscss
   and ".doc-line:not(.folded) .dl-meta { grid-template-columns: 104px 70px; }"
   in _opscss,
   "the blanks slot holds its width when a row opens — a column that "
   "appears and disappears is a column that jumps — and gives the track "
   "back below the width where the title starts losing letters to it")
ok('${x.signed} of ${' in _opsjs,
   "half-signed is its own state — one party done, one still out — and a "
   "slot that showed only the newer of the two would read as unsigned")
ok("grid-template-columns: minmax(0, 1.35fr) 92px minmax(0, 1fr) 128px 122px"
   in _opscss and ".gate-line > b { overflow: hidden;" in _opscss,
   "the gates line up the same way — one line per gate, one width per "
   "column (six now, the schedule earned one), so ten gates read as a "
   "list rather than ten sentences")
ok('? "signed" : "confirmed"}</span>' in " ".join(_opsjs.split())
   and 'awaiting</span>' in _opsjs,
   "the state is one word wide on every row")
ok('g.passed_at ? esc(by) : ""' in _opsjs,
   "and who signed it and when travel with the document they attest to, "
   "which is the sentence they finish")

# --- one vocabulary: everything the client and the studio read is a stage --
ok('foldable("gates", "Stages"' in _opsjs
   and '"Stage " + esc(st.client_stage' in _opsjs,
   "the board says stage for both lists — the ten that close and the "
   "eleven they close — because two words for one shape is a thing to "
   "learn before you can read the page")
# Only what a person reads: comments and data-gate-* attributes keep the
# mechanical name, where it is precise and nobody has to meet it.
_visible = re.findall(r">([^<>{}`]{4,120})<", _opsjs)
_leftover = sorted({t.strip() for t in _visible if "gate" in t.lower()})
ok(not _leftover, f"and nothing a person reads still says gate: {_leftover}")
ok("Mark closed" in _opsjs and "Mark passed" not in _opsjs
   and "Reopen this stage?" in _opsjs,
   "the buttons and the confirmations moved with it — a stage closes, and "
   "reopening reopens a stage")
ok(">The stages<" in c.get("/engage/" + c.post(
       f"/api/store/admin/engagements/{_eid}/portal",
       headers=A).json()["url"].split("/engage/")[1]).text,
   "and the client's own page says stages too — they were never going to "
   "learn our word for it")

# --- the stage, written up for the client ---------------------------------
# A status report composed by hand is a status report that disagrees with
# the system it describes — usually in the studio's favour, usually on the
# week that matters. This one is composed from the same rows the board
# reads, and filed as a paper rather than rendered as a screen.
_rep = c.post(f"/api/store/admin/engagements/{_eid}/stages/03-agreement/report",
              headers=A).json()
ok(_rep.get("doc_id") and _rep.get("refreshed") is False,
   "a stage writes itself up for the client on request")
_rmd = c.get(f"/api/store/admin/documents/{_rep['doc_id']}/markdown",
             headers=A).text
ok("Stage 03 · agreement" in _rmd and not _rmd.startswith("#"),
   "it reports on a named stage, and does not repeat its own title — every "
   "renderer already draws that above the body")
ok(any(d["id"] == _rep["doc_id"] and d["title"].startswith("Progress update")
       for d in c.get("/api/store/admin/documents", headers=A,
                      params={"q": "Progress update"}).json()["documents"]),
   "titled as what it is")
for _head in ("Where the project stands", "What closes this stage",
              "What you have from us", "What we need from you",
              "What happens next"):
    ok(f"## {_head}" in _rmd, f"and it answers '{_head.lower()}'")
ok(_rmd.count("| Stage ") >= 1 and "in progress" in _rmd,
   "with the whole run in one table, so the client can see where this "
   "stage sits rather than being told")
_ratecard = next((d for d in c.get(
    f"/api/store/admin/engagements/{_eid}", headers=A).json()["docs"]
    if d["side"] == "internal"), None)
ok(_ratecard and _ratecard["title"] not in _rmd,
   "the internal wall holds inside the report too — side='to_client' is a "
   "clause in its query, not a rule someone has to remember while writing")
ok("Progress update" not in _rmd.split("## What you have from us")[1]
   .split("##")[0],
   "and it does not list itself among the papers — it is the covering "
   "note, not one of the things it covers")
# --- and sent, as a link to the live document ------------------------------
_send = c.post(
    f"/api/store/admin/engagements/{_eid}/docs/{_rep['doc_id']}/send",
    headers=A, json={"to": "poc@client.test", "message": "Week 3, as promised."})
ok(_send.status_code == 200 and _send.json()["status"] == "dry",
   "with no SMTP configured the whole pipeline runs and reports 'dry' — "
   "nothing left the machine, and it says so rather than claiming a send")
_sj = _send.json()
ok("/engage/" in _sj["link"] and f"/doc/{_rep['doc_id']}" in _sj["link"],
   "what goes out is a link to their own portal copy, not an attachment: "
   "the document they open next week is next week's truth")
ok(c.get(_sj["link"].split("8000")[-1].split("testserver")[-1]).status_code
   == 200, "and the link opens without a login, which is the point of it")
_llog = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()["log"]
ok(any("sent" in l["what"] and "poc@client.test" in l["what"]
       and "nothing left the machine" in l["what"] for l in _llog),
   "the log records the send and, when nothing was sent, says so in the "
   "same line — a send recorded as done when it wasn't is the one outcome "
   "worth being loud about")
_intdoc = next(d for d in c.get(f"/api/store/admin/engagements/{_eid}",
                                headers=A).json()["docs"]
               if d["side"] == "internal")
ok(c.post(f"/api/store/admin/engagements/{_eid}/docs/{_intdoc['id']}/send",
          headers=A, json={"to": "poc@client.test"}).status_code == 404,
   "an internal paper cannot be sent from here at all — not 'should not', "
   "cannot: the wall is the query")
ok(c.post(f"/api/store/admin/engagements/{_eid}/docs/{_rep['doc_id']}/send",
          headers=A, json={"to": "not-an-email"}).status_code == 400,
   "and a malformed address is refused rather than swallowed")
# --- and the whole bundle, the same way ------------------------------------
_bsend = c.post(f"/api/store/admin/engagements/{_eid}/bundle/send",
                headers=A, json={"to": "poc@client.test"}).json()
ok(_bsend["status"] == "dry" and _bsend["files"] >= 2
   and _bsend["link"].endswith(_bsend["link"].split("/engage/")[1]),
   "the bundle sends as a link to the roadmap, and says how many files are "
   "behind it")
_btok = _bsend["link"].split("/engage/")[1]
_bz = c.get(f"/engage/{_btok}/bundle.zip")
ok(_bz.status_code == 200 and _bz.content[:2] == b"PK",
   "which the client can download without a login — built when they click "
   "it, so the link in an email never goes stale")
import zipfile as _zf, io as _io3
_names = _zf.ZipFile(_io3.BytesIO(_bz.content)).namelist()
ok(_names and all("/internal/" not in n for n in _names)
   and any("/to-client/" in n for n in _names),
   "and it is the client's side only — the same query with the same clause "
   "the studio's own bundle uses, so there is no second idea of what they "
   "are allowed to have")
ok(">Download everything<" in c.get(f"/engage/{_btok}").text,
   "the roadmap page offers it, so the link they were sent lands somewhere "
   "that explains itself")
# Every outbound mail lands in one panel, whichever screen sent it: an
# operator asking "did that go?" should not have to know which part of the
# app wrote it.
_elog = c.get("/api/admin/email/log", headers=A).json()
_mine = [l for l in _elog if l["email"] == "poc@client.test"]
ok(len(_mine) >= 2 and {l["kind"] for l in _mine} == {"client"}
   and all(l["status"] == "dry" for l in _mine),
   "the document send and the bundle send both show in the ERP's email log, "
   "against the address they went to — a client POC is not a user of this "
   "system, so the recorded address wins over any join")
ok(any(l["kind"] == "signature" for l in _elog),
   "and so do signature requests, which were sending without ever "
   "appearing there")
ok("Email — SMTP, and everything sent" in _opsjs
   and "app password" in _opsjs and "smtp.gmail.com" in _opsjs,
   "the settings panel says what those credentials actually carry, and how "
   "to get one for Gmail without handing over a real password")

ok(any("client bundle" in l["what"] and "poc@client.test" in l["what"]
       for l in c.get(f"/api/store/admin/engagements/{_eid}",
                      headers=A).json()["log"]),
   "and the send is on the record like any other")
ok('id="eng-bundle-send"' in _opsjs
   and "const sendToClient = (path, hint)" in _opsjs
   and _opsjs.count("sendToClient(") == 2,
   "one send modal serves both — what is being sent changes, the care "
   "taken over sending it does not")

ok('data-send="' in _opsjs and 'id="sd-to"' in _opsjs
   and 'out.status === "dry"' in _opsjs,
   "the button asks who it is going to before it goes, and reads back what "
   "actually happened — an outward-facing act is not a fire-and-forget one")
ok('"Refresh update" : "Progress update"' in _opsjs,
   "and the same button says which it will do, because a stage that already "
   "has an update is the common case after the first week")

_again = c.post(f"/api/store/admin/engagements/{_eid}/stages/03-agreement/report",
                headers=A).json()
ok(_again["doc_id"] == _rep["doc_id"] and _again["refreshed"],
   "asking again refreshes the same paper rather than breeding copies")
_rdocs = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()["docs"]
_filed = next(d for d in _rdocs if d["id"] == _rep["doc_id"])
ok(_filed["side"] == "to_client" and _filed["stage"] == "04-agreement",
   "filed on the client's side, under the stage it reports on — so it "
   "travels in the binder, the export and the portal with everything else")
ok(c.get(f"/api/store/admin/documents/{_rep['doc_id']}/pdf",
         headers=A).status_code == 200,
   "and prints like any other paper")
_ptok3 = c.post(f"/api/store/admin/engagements/{_eid}/portal",
                headers=A).json()["url"].split("/engage/")[1]
ok(c.get(f"/engage/{_ptok3}/doc/{_rep['doc_id']}").status_code == 200,
   "the client can open it from their own link, which is the point of "
   "writing it")
ok('data-report="' in _opsjs and "/stages/${b.dataset.report}/report" in _opsjs,
   "every stage on the board offers it")
c.request("DELETE",
          f"/api/store/admin/engagements/{_eid}/docs/{_rep['doc_id']}",
          headers=A)
c.delete(f"/api/store/admin/documents/{_rep['doc_id']}", headers=A)

# --- the quote bench, wired into the client's paperwork --------------------
# The bench owns the arithmetic; the server files what it produced. A quote
# that lives outside the filing system is a quote nobody can find in six
# months — filed, it previews, prints, signs, sends and travels in the
# binder through machinery that already exists.
ok(c.get("/api/store/admin/quote-bench").status_code in (401, 403),
   "the bench embeds our costs and margins, so it is never served without "
   "the admin wall")
_qb = c.get("/api/store/admin/quote-bench", headers=A)
ok(_qb.status_code == 200 and "const CAPS=" in _qb.text
   and "quoteMarkdown" in _qb.text and "window.bcInit" in _qb.text,
   "behind it, the whole bench — capabilities, bands, and the embedded-mode "
   "seams the ERP drives")

ok(c.get(f"/api/store/admin/engagements/{_eid}/quote", headers=A).json()
   == {"doc_id": 0, "state": "", "signed": 0},
   "a client with no quote says so, rather than erroring")

import base64 as _b64q
_qstate = _b64q.b64encode(b'{"on":["core","selling"],"locs":1}').decode()
_qmd = ("**An estimate, not an invoice.**\n\n## Part 1 — your platform\n\n"
        "| | Monthly |\n|---|---|\n| Selling | $50.00 |\n"
        "| **Part 1 — platform** | **$100.00** |\n\n"
        "Accepted for Probe: [SIGN HERE]\n")
_qr = c.post(f"/api/store/admin/engagements/{_eid}/quote", headers=A,
             json={"title": "Quote — Probe", "markdown": _qmd,
                   "state": _qstate}).json()
ok(_qr["doc_id"] and _qr["refreshed"] is False,
   "filing a quote creates a paper on the client")
_qd = next(d for d in c.get(f"/api/store/admin/engagements/{_eid}",
                            headers=A).json()["docs"]
           if d["id"] == _qr["doc_id"])
ok(_qd["side"] == "to_client" and _qd["stage"] == "03-proposal",
   "filed on the client's side under the proposal stage — it travels in "
   "the binder, the bundle and the portal with everything else")
ok(_qd["quote"] is True and all(
       d["quote"] is False for d in c.get(
           f"/api/store/admin/engagements/{_eid}", headers=A).json()["docs"]
       if d["id"] != _qr["doc_id"]),
   "the row knows it is a quote, so the UI can open the bench's own view "
   "of it rather than the plain paper")
_qs = c.get(f"/api/store/admin/engagements/{_eid}/quote", headers=A).json()
ok(_qs["doc_id"] == _qr["doc_id"] and _qs["state"] == _qstate,
   "and the bench state rides in the paper, so the next Quote click opens "
   "where the conversation left off — the document is the storage")
ok(c.get(f"/api/store/admin/documents/{_qr['doc_id']}/pdf",
         headers=A).status_code == 200
   and "Sign here:" in c.get(
       f"/api/store/admin/documents/{_qr['doc_id']}/preview", headers=A).text,
   "the filed quote prints, and carries a signature line — accepting a "
   "quote is the signature that passes the proposal gate")

_qr2 = c.post(f"/api/store/admin/engagements/{_eid}/quote", headers=A,
              json={"title": "Quote — Probe v2", "markdown": _qmd,
                    "state": _qstate}).json()
ok(_qr2["doc_id"] == _qr["doc_id"] and _qr2["refreshed"],
   "re-filing replaces the unsigned quote rather than breeding copies")

_qsig = c.post(f"/api/store/admin/documents/{_qr['doc_id']}/request-signature",
               headers=A, json={"signer_name": "Quote Signer",
                                "signer_email": "q@s.test",
                                "role": "signer", "in_person": True}).json()
c.post("/sign/" + _qsig["link"].split("/sign/")[1],
       json={"typed_name": "Quote Signer"})
_qstate2 = _b64q.b64encode(b'{"on":["core","selling","inventory"]}').decode()
_qr3 = c.post(f"/api/store/admin/engagements/{_eid}/quote", headers=A,
              json={"title": "Quote — Probe v3", "markdown": _qmd,
                    "state": _qstate2}).json()
ok(_qr3["doc_id"] != _qr["doc_id"],
   "but a signed quote is the offer the client accepted — it is left alone "
   "and the new quote is filed beside it")
ok(c.get(f"/api/store/admin/engagements/{_eid}/quote", headers=A)
   .json()["state"] == _qstate2
   and c.get(f"/api/store/admin/engagements/{_eid}/quote",
             headers=A, params={"did": _qr["doc_id"]}).json()["state"]
   == _qstate,
   "each paper keeps its own bench state — viewing the signed old quote "
   "must not show the new quote's numbers")
ok(c.post(f"/api/store/admin/engagements/{_eid}/quote", headers=A,
          json={"title": "x", "markdown": "  ", "state": ""}).status_code
   == 400, "an empty quote is refused")

# --- the schedule speaks even when nobody wrote dates ------------------------
_det0 = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
ok(_det0["schedule"] and all(
       s["source"] in ("actual", "planned", "estimate")
       for s in _det0["schedule"])
   and _det0["tracks"]
   and all({"start", "end", "days", "estimated"} <= set(t)
           for t in _det0["tracks"]),
   "every gate carries a date, and every date says whether it is fact, "
   "plan or estimate — a blank schedule is not an option")
c.put(f"/api/store/admin/engagements/{_eid}/dates", headers=A, json={
    "dates": [{"label": "Requirements signed", "planned": "2027-03-01"}]})
_det1 = c.get(f"/api/store/admin/engagements/{_eid}", headers=A).json()
_reqs = [s for s in _det1["schedule"] if s["gate"] == "requirements_signed"]
ok(_reqs and _reqs[0]["source"] == "planned"
   and _reqs[0]["date"] == "2027-03-01",
   "a written date replaces the estimate the moment it exists")
ok(any(s["source"] == "estimate" for s in _det1["schedule"]),
   "while the gates nobody dated still say something — a default "
   "duration, marked as a guess")

# --- the scope of work: generated, never blank -------------------------------
_sw = c.post(f"/api/store/admin/engagements/{_eid}/sow", headers=A,
             json={}).json()
_swrow = next(d for d in c.get(f"/api/store/admin/engagements/{_eid}",
                               headers=A).json()["docs"]
              if d["id"] == _sw["doc_id"])
ok(_swrow["sow"] is True and _swrow["stage"] == "04-agreement"
   and _swrow["category"] == "contracts",
   "the SOW files under the agreement stage, and the row knows what it "
   "is — a change order can find it later")
_swtxt = c.get(f"/api/store/admin/documents/{_sw['doc_id']}/preview",
               headers=A).text
ok("Scope of Work" in _swtxt and "Selling" in _swtxt
   and "Platform Core" in _swtxt,
   "deliverables and fees come from the SIGNED quote and the price book "
   "— the paper cannot disagree with the record it rides on")
ok("(est.)" in _swtxt and "2027-03-01" in _swtxt,
   "the timeline is the gantt's own schedule: the written date verbatim, "
   "the guessed ones marked as guesses")
ok("change order" in _swtxt and "out of scope" in _swtxt,
   "and change control is a clause, not a hope")

ok(c.post(f"/api/store/admin/engagements/{_eid}/sow", headers=A,
          json={"change_order_for": _sw["doc_id"]}).status_code == 409,
   "a change order amends a SIGNED scope of work — an open draft just "
   "gets edited")
ok(c.post(f"/api/store/admin/engagements/{_eid}/sow", headers=A,
          json={"change_order_for": _qr["doc_id"]}).status_code == 404,
   "and it refuses to amend a paper that is not a SOW at all")
_swsig = c.post(f"/api/store/admin/documents/{_sw['doc_id']}"
                "/request-signature", headers=A,
                json={"signer_name": "Scope Signer",
                      "signer_email": "s@s.test",
                      "role": "signer", "in_person": True}).json()
c.post("/sign/" + _swsig["link"].split("/sign/")[1],
       json={"typed_name": "Scope Signer"})
_co = c.post(f"/api/store/admin/engagements/{_eid}/sow", headers=A,
             json={"change_order_for": _sw["doc_id"]}).json()
_cotxt = c.get(f"/api/store/admin/documents/{_co['doc_id']}/preview",
               headers=A).text
ok("Change order" in _co["title"]
   and "Amends the signed Scope of Work" in _cotxt
   and _sw["title"] in _cotxt.replace("&#x27;", "'"),
   "once signed, scope moves by change order — a paper that names the "
   "SOW it amends and never re-opens its text")

ok('id="eng-quote"' in _opsjs and "w.bcFile = async (d)" in _opsjs
   and "bc-init" not in _opsjs,
   "the client page opens the bench in a frame and hands it a function to "
   "answer with — two direct calls on a same-origin frame, no window "
   "listener, which this app forbids for cause")
ok('data-quote="1"' in _opsjs
   and 'openBench({ view: "client", doc:' in _opsjs
   and 'id="qb-paper"' in _opsjs,
   "a quote's View opens the bench's client view on that paper's state — "
   "the tape, the parts, the running total — with the flat printable paper "
   "one click away inside, not instead")
ok("if(d.view==='client') S.client=true;" in _qb.text,
   "and the bench lets the embedder choose which face opens")
ok('$("#eng-quote").onclick = () => openBench({ view: "client" });' in _opsjs,
   "both doors open on the client face — a quote is as likely to be opened "
   "with the client in the room as not, and the safe face shows first")

# --- the studio face is behind a second proof of identity ------------------
# The bearer token proves the session; this proves the person still holding
# the screen — which matters exactly when that screen is turned toward a
# client and one click would show costs and margins.
ok(c.post(f"/api/store/admin/verify",
          json={"password": "x"}).status_code in (401, 403),
   "no token, no verify")
ok(c.post("/api/store/admin/verify", headers=A,
          json={"password": "not-the-key"}).status_code == 403,
   "a wrong answer is a 403, not a shrug")
ok(c.post("/api/store/admin/verify", headers=A,
          json={"password": CFG["admin_key"]}).json()["ok"],
   "an account with no password answers with the admin key — the thing "
   "that signed it in as admin in the first place")
from erp.backend import auth as _auth
_vcon = _db.connect()
_vuid = c.get("/api/me", headers=A).json()["id"]
_vcon.execute("UPDATE users SET password_hash=? WHERE id=?",
              (_auth.hash_password("open-sesame"), _vuid))
_vcon.commit()
ok(c.post("/api/store/admin/verify", headers=A,
          json={"password": "open-sesame"}).json()["ok"]
   and c.post("/api/store/admin/verify", headers=A,
              json={"password": CFG["admin_key"]}).status_code == 403,
   "once the account has a password, only the password answers — the "
   "admin key stops being a skeleton key the moment a real one exists")
_vcon.execute("UPDATE users SET password_hash='' WHERE id=?", (_vuid,))
_vcon.commit(); _vcon.close()
ok("w.bcVerify = (pw) =>" in _opsjs
   and "gateStudio" in _qb.text and "studioUnlocked" in _qb.text
   and "if(S.client) gateStudio(flipView);" in _qb.text,
   "and the bench's client→studio flip asks for that proof — going to the "
   "client view stays free, because hiding things needs no permission")
_qbjs = _qb.text
ok("quoteMarkdown" in _qbjs and "Part 2 — support" in _qbjs
   and "[SIGN HERE]" in _qbjs,
   "the bench renders the client-view tape as markdown — parts, totals, "
   "acceptance line — and the cost, margin and infra lines never leave it")

# --- the bench, the menu and the price book say the same numbers -----------
# price-book.md v2 is the source; the bench and the client-facing menu carry
# copies. This parses the book's own capability table and holds the other
# two to it, so a price changed in one place fails here instead of drifting.
_book = Path("docs/product/price-book.md").read_text()
_menu = Path("docs/business-control-b2b-client/templates/02-consultation/"
             "capability-menu.md").read_text()
_caps = re.findall(r"^\| ([A-Z][^|*]+?)(?: \*)? \| (?:Light|Standard|Heavy)"
                   r" \| \*\*\$(\d+)\*\* \|", _book, re.M)
ok(len(_caps) == 29,
   f"the book's capability table parses whole ({len(_caps)} of 29)")
_off = [f"{n} ${p}" for n, p in _caps
        if not re.search(r"\*\*" + re.escape(n) + r"\*\*[^|]*\| [^|]*\|"
                         r" \$" + p + r" \|", _menu)]
ok(not _off,
   f"every capability carries the book's band price in the client menu "
   f"(off: {_off})")
for _fig in ("$335.00", "$288.00", "$183.75", "$192.50"):
    ok(_fig in _book and _fig in _menu,
       f"the {_fig} bundle figure agrees between book and menu")
ok("$[X]" not in _menu,
   "nothing in the menu is left unpriced — the bands priced the nine that "
   "v1 could not sell")
for _pair in ("**$199**", "**$349**", "**$699**", "**$150**", "**$350**",
              "**$750**"):
    ok(_pair in _book and _pair in _menu,
       f"tier and care figures agree between book and menu ({_pair})")
ok("bands:{light:20,std:30,heavy:50}, corePrice:50" in _qb.text
   and "tierPrice:{starter:199,pro:349,scale:699}" in _qb.text
   and "{n:'Essential — $150',p:150" in _qb.text,
   "and the bench runs on the same numbers — bands, core, tiers, care")

# The deck too: its three data models each carried their own copies of the
# prices, which is how the drift happened the first time. Held to the same
# parsed book table via a name→id map (structure, not prices).
_deck = Path("docs/product/ecommerce-stack-deck.html").read_text()
_D_ID = {"Sourcing": "src", "Inventory": "inv", "Production": "prd",
         "Warehouse": "wh", "Distribution": "log", "Learning": "lrn",
         "Voice & translation": "lng", "Nutrition": "ntr",
         "Selling": "sell",
         "Subscriptions & boxes": "box", "Fundraising": "fund",
         "Marketing": "mkt", "CRM & Support": "crm", "Events": "evt",
         "Affiliates": "aff", "Payments": "pay", "Accounting": "acc",
         "Finance": "fin", "Treasury & investments": "tre",
         "Workforce": "work", "Onboarding": "onb", "Payroll": "pyr",
         "Intelligence": "intel", "Automation": "auto", "Comms": "com",
         "InfoSec": "sec", "API & data platform": "api",
         "Progressive App": "pwa", "Legal": "leg"}
_doff = [f"{n} ${p}" for n, p in _caps
         if not re.search(r'id:"' + _D_ID[n] + r'",\s*nm:"[^"]*",price:'
                          + p + ",", _deck)]
ok(not _doff,
   f"every capability carries the book's band price in the deck's price "
   f"book too (off: {_doff})")
ok('nm:"Platform Core",price:50,' in _deck
   and _deck.count("price:199,") >= 1 and "price:349," in _deck
   and "price:699," in _deck and "mrr:199" in _deck and "mrr:349" in _deck
   and "mrr:699" in _deck
   and '"starter","Starter",199,' in _deck
   and '"pro","Pro",349,' in _deck and '"scale","Scale",699,' in _deck,
   "core and the tier prices agree across all three of the deck's models — "
   "quote builder, cluster planner and tier cards")
ok("price:49," not in _deck and "price:149," not in _deck
   and "price:399," not in _deck and "npPrice(49)" not in _deck,
   "no v1 tier price survives anywhere in the deck")
_dbundles = _deck.split("const BUNDLES=")[1][:600]
ok('"lngB"' not in _dbundles,
   "the graph bundles match the book's §13 derivation — course and lingua "
   "carry no Voice & translation, which the priced side never had")
ok("the platform — $50/mo" in _menu,
   "the menu's platform line is the book's $50 Core")

# tidy: unfile and remove the quote papers
for _qid in {_qr["doc_id"], _qr3["doc_id"]}:
    c.request("DELETE",
              f"/api/store/admin/engagements/{_eid}/docs/{_qid}", headers=A)
    c.delete(f"/api/store/admin/documents/{_qid}", headers=A)

# --- a document you just asked for opens ----------------------------------
ok('view().querySelector(`[data-engview="${out.doc_id}"]`)?.click()'
   in _opsjs,
   "generating a document opens it: asking for a document is asking to see "
   "it, and clicking its own row's View button means the viewer is told "
   "what the row knows rather than a second guess at the same facts")
ok('${done} of ${live.length} closed' in _opsjs
   and 'to generate' in _opsjs and 'entr${' in _opsjs,
   "a folded section still says what it holds — stages closed, documents "
   "waiting, entries logged — so folding costs no information")
ok('if (ev.target.closest("button, a, input, select")) return;' in _opsjs,
   "clicking the Gantt button in a fold head does not also fold the card")
ok('id="fold-all"' in _opsjs and '"Unfold all" : "Fold all"' in _opsjs,
   "and one control folds every stage at once, reading back which way it "
   "will go")
ok("if (foldAllSync) foldAllSync();" in _opsjs and "foldAllSync = sync;" in _opsjs,
   "folding the last stage by hand corrects that control too — a button "
   "that promises the wrong direction is worse than no button")

# --- the record answers on every surface, not just the studio's ------------
# A record field is deliberately never baked into the body, so each renderer
# has to resolve it. One that forgets shows a client [CLIENT] where their own
# name belongs — on the page they are being asked to sign.
_gsrc = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "05-kickoff/welcome-guide.md"}).json()
_ename = c.get(f"/api/store/admin/engagements/{_eid}",
               headers=A).json()["engagement"]["name"]
_sreq = c.post(
    f"/api/store/admin/documents/{_gsrc['doc_id']}/request-signature",
    headers=A, json={"signer_name": "Reads It", "signer_email": "r@x.test",
                     "role": "signer", "in_person": True}).json()
_spage = c.get(_sreq["link"].split("localhost")[-1]).text
ok("[CLIENT]" not in _spage and "[CLIENT NAME]" not in _spage,
   "the page a client signs never shows a record token raw — asked to sign "
   "[CLIENT], they have been handed the template, not their document")
ok("fbox" in _spage,
   "and it draws blanks the same way the studio's own view does — one look "
   "for one document, whichever side of the wall you are on")
ok(_docmod.substitute_globals("For [CLIENT], approved by [CLIENT POC].",
                              {"client": "Probe Co", "client_poc": "P Poc"})
   == "For Probe Co, approved by P Poc.",
   "one resolver answers record tokens, wherever the text is going")
# PDF streams are compressed, so the bytes cannot be read for a token —
# what is checkable is that every path that builds one goes through the
# resolver, which is the property that was actually broken.
_dsrc = Path("src/storefront/backend/documents.py").read_text()
_esrc = Path("src/storefront/backend/engagements.py").read_text()
ok(_dsrc.count("substitute_globals(d[\"body\"], gvals or {})") == 1
   and "gvals=globals_for(con, did)" in _dsrc
   and "gvals=globals_for(con, d[\"id\"])" in _dsrc,
   "the studio's PDF and the signer's own copy resolve the record — the "
   "printed page outlives the screen, and it is the one that gets argued "
   "over")
ok("substitute_globals(d[\"body\"], gv)" in _dsrc.split("def docusign_send")[1],
   "and so does the file handed to DocuSign, where the client signs "
   "somewhere we do not control the rendering")
ok("vault.substitute_globals(r[\"body\"], _gv)" in _esrc
   and "gvals=global_values(e)" in _esrc
   and "vault.form_inner('', row['body'], _gv)" in _esrc,
   "and the export bundle and the client portal, which are the two ways a "
   "document leaves the building")
_ptok2 = c.post(f"/api/store/admin/engagements/{_eid}/portal",
                headers=A).json()["url"].split("/engage/")[1]
_ppdf = c.get(f"/engage/{_ptok2}/pdf/{_gsrc['doc_id']}")
_ppage = c.get(f"/engage/{_ptok2}/doc/{_gsrc['doc_id']}").text
ok(_ppdf.status_code == 200 and "[CLIENT]" not in _ppage
   and "fbox" in _ppage,
   "the portal hands over the same document the studio sees — resolved, "
   "with its blanks drawn as blanks")
ok(c.get(f"/api/store/admin/documents/{_gsrc['doc_id']}/preview",
         headers=A).text.count(_ename) >= 1,
   "the studio's preview still resolves it, from the same call — the point "
   "is that they agree, not that any one of them is right")
c.request("DELETE",
          f"/api/store/admin/engagements/{_eid}/docs/{_gsrc['doc_id']}",
          headers=A)
c.delete(f"/api/store/admin/documents/{_gsrc['doc_id']}", headers=A)

# --- per-section signing markers -------------------------------------------
from storefront.backend.pdfgen import doc_pdf as _dpdf
from storefront.backend.engagements import placeholders as _phs
_mk = "A. [INITIALS]\n\nB. [INITIALS]\n\n[SIGN HERE]\n\nFill [X]."
ok(_phs(_mk) == ["X"],
   "signing markers are instructions, not blanks — the fill form leaves "
   "them standing")
_mh = _docmod.md_html(_mk)
ok(_mh.count("Initials:") == 2 and "Sign here:" in _mh
   and "[INITIALS]" not in _mh,
   "and they render as labelled lines, one per section that carries one")
_envt = _docmod.docusign_envelope("T", "QQ==", "N", "n@x.t", "")[
    "recipients"]["signers"][0]["tabs"]
ok([x["anchorString"] for x in _envt["signHereTabs"]] ==
   ["Signed", "Sign here:"]
   and _envt["initialHereTabs"][0]["anchorString"] == "Initials:",
   "the envelope anchors on those same labels — DocuSign places a tab at "
   "every occurrence, so initials land clause by clause")
ok(all(x["anchorIgnoreIfNotPresent"] == "true"
       for x in _envt["signHereTabs"] + _envt["initialHereTabs"]),
   "and a document with no markers still signs at its Signed block")

# --- printable signature areas, markers in the contracts, scans back in ----
for _cf in ("week-website", "partially-custom", "fully-custom",
            "branding-creative"):
    _ct2 = (_studio / "templates" / "04-agreement" / "contracts"
            / f"{_cf}.md").read_text()
    ok(_ct2.count("[INITIALS]") >= 2 and "[SIGN HERE]" in _ct2,
       f"{_cf} initials its load-bearing clauses and carries an execution "
       f"line")

_g4 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "04-agreement/contracts/week-website.md"}).json()
c.post(f"/api/store/admin/documents/{_g4['doc_id']}/request-signature",
       headers=A, json={"signer_name": "Pat Lee", "signer_email": "p@x.t",
                        "role": "signer", "in_person": True})
_pv4 = c.get(f"/api/store/admin/documents/{_g4['doc_id']}/preview",
             headers=A).text
ok("Awaiting signature" in _pv4 and "Pat Lee" in _pv4,
   "an unsigned request shows as a blank signature area — name and date "
   "lines — so the form prints, gets signed, and comes back")
ok("Initials:" in _pv4 and "[INITIALS]" not in _pv4,
   "and the initials markers render as labelled lines, not literals")

_scan = c.post("/api/store/admin/documents", headers=A, json={
    "title": "Signed scan — smoke", "category": "contract",
    "party_kind": "partner", "party_name": "Smoke Test Client"}).json()
c.post(f"/api/store/admin/documents/{_scan['id']}/file", headers=A,
       files={"file": ("scan.jpg", b"\xff\xd8\xff\xe0fakejpg",
                       "image/jpeg")})
ok(c.post(f"/api/store/admin/engagements/{_eid}/attach", headers=A,
          json={"doc_id": _scan["id"], "stage": "04-agreement",
                "side": "to_client"}).status_code == 200,
   "the returned paper's scan files beside the original, in the same stage "
   "— the authored text stays exactly what was signed, and the wet-ink "
   "copy is evidence alongside it")
c.delete(f"/api/store/admin/documents/{_g4['doc_id']}", headers=A)
c.delete(f"/api/store/admin/documents/{_scan['id']}", headers=A)

# --- routes, choice fields, and columns that line up -----------------------
ok("function applyRoute" in _ops and "hashchange" in _ops
   and "#/clients/" in _ops.replace("`", ""),
   "the unique pages carry real URLs — #/orders, #/clients/3 — read on "
   "load, written on render, so the address bar and the app can't disagree")
ok("function fillField" in _ops and 'tok.split(" / ")' in _ops
   and "— leave the brackets —" in _ops,
   "a token that lists its own values renders as a select of those values, "
   "and every fill is labelled optional — blank keeps the brackets")
ok('<span class="req">required</span>' in _ops,
   "while the fields that genuinely are required say so")
ok('class="tpl-line"' in _ops and "tpl-head" in _ops
   and 'class="chips"' not in _ops.split("const stageCard")[1][:900],
   "a stage's templates stack one per line — a wrapping row of chips read "
   "as a paragraph, not a menu of things you can create")
_css3 = c.get("/ops/styles.css").text
ok("button.tpl-line { display: grid" in _css3
   and "grid-template-columns: 14px minmax(0, 1fr) auto" in _css3,
   "each on its own full-width line, with the side it lands on visible "
   "rather than hidden in a tooltip")

ok('class="dt-state"' in _ops and 'class="dt-acts"' in _ops
   and "grid-template-columns: 22px minmax(0, 1fr) 108px 168px auto" in _css3,
   "the Documents tab gets the same columns — every signed pill and every "
   "button starts at the same x down the whole list")
ok('class="sig-line' in _ops and "sl-mail" in _ops and "sl-when" in _ops
   and "150px minmax(0, 1fr) 84px 132px 104px 116px" in _css3,
   "and the signers align: who, email, role, state, when, actions")

ok("function trackHtml" in _ops and "tk-client" in _ops
   and "waiting on the client" in _ops,
   "the gates draw as a track — done, do next, waiting on the client, "
   "upcoming — derived from the same gates the list is, so the picture and "
   "the list can never disagree")
ok("function gateState" in _ops
   and "g.kind === \"money\" && g.has_payment_link" in _ops,
   "'waiting on the client' is a real state: a request that is out or a "
   "payment link unpaid is time we cannot spend")
ok("function ganttModal" in _ops and "d.tracks" in _ops
   and "What can run in parallel" in _ops,
   "and a Gantt view shows which work overlaps — the gates are a chain, "
   "the work between them is not")
ok("critical path" in (Path(__file__).parent.parent
                       / "src/storefront/backend/engagements.py"
                       ).read_text(encoding="utf-8"),
   "with content named as the thing that decides the launch date — on the "
   "server's TRACKS, where the SOW reads it too")

for _cls in ("gate-line", "gl-acts", "doc-line", "dl-acts", "log-line"):
    ok(f'class="{_cls}' in _ops or f"'{_cls}'" in _ops,
       f"{_cls} markup exists for the aligned layout")
_css2 = c.get("/ops/styles.css").text
ok("grid-template-columns: repeat(3, 92px)" in _css2,
   "gate buttons live in three fixed slots, so Link doc sits under Link doc "
   "and Confirm under Mark passed all the way down")
ok(".doc-line" in _css2 and ".dl-acts" in _css2
   and ".log-line" in _css2 and "92px 130px minmax(0, 1fr)" in _css2,
   "documents get one aligned line each, and the activity log's actors "
   "share a column")

# --- the document as the form ----------------------------------------------
_g5 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "06-requirements/requirements-template.md"}).json()
_ed = c.get(f"/api/store/admin/engagements/{_eid}/docs/{_g5['doc_id']}"
            "/editable", headers=A)
ok(_ed.status_code == 200, "a document with blanks opens as its own form")
_toks = re.findall(r'<input class="ph[^"]*" data-tok="([^"]+)"', _ed.text)
_bl5 = c.get(f"/api/store/admin/engagements/{_eid}/docs/{_g5['doc_id']}"
             "/blanks", headers=A).json()["placeholders"]
ok(set(_bl5) <= set(_toks) and len(_toks) >= len(_bl5),
   "every bracket renders as an inline field where it sits in the text — "
   "and a token used twice renders twice, to be filled once")
ok(len(set(_toks)) >= len(_bl5),
   "answered fields are fields too: they stay editable rather than "
   "dissolving into the prose the moment they are filled")
ok("\x00" not in _ed.text and "<table>" in _ed.text,
   "the sentinel pass leaks nothing and the document's structure survives")
ok(c.get(f"/api/store/admin/engagements/{_eid}/docs/{_gen['doc_id']}"
         "/editable", headers=A).status_code == 400,
   "a signed document refuses the in-place editor for the same reason it "
   "refuses the form — its text is what was attested to")
ok("function fillInDoc" in _ops and "fb-indoc" in _ops
   and "dataset.tok === inp.dataset.tok" in _ops,
   "the form offers the in-document road, and same-token fields type "
   "together — the editor shows the one-value rule live instead of "
   "surprising anyone at save")

# --- every kind of blank is fillable ---------------------------------------
_g6 = c.post(f"/api/store/admin/engagements/{_eid}/docs", headers=A, json={
    "template_path": "05-kickoff/branding-questionnaire.md"}).json()
_eh = c.get(f"/api/store/admin/documents/{_g6['doc_id']}/editable",
            headers=A).text
ok(_eh.count('class="ph ph-area"') >= 20
   and 'class="ph-check"' in _eh,
   "a questionnaire's answer lines become paragraph boxes and its "
   "checkboxes toggle — not just the bracket tokens")
_pv6 = c.get(f"/api/store/admin/documents/{_g6['doc_id']}/preview",
             headers=A).text
ok(_pv6.count("fbox-area") >= 20 and _pv6.count("<hr>") <= 3,
   "and reading a document shows every blank as a box you could write on — "
   "print it and fill it in with a pen — rather than a bracketed word or a "
   "bare rule with nothing to write on")
ok('class="flab"' in _pv6 and "fcheck" in _pv6,
   "each box wears its own label, and the tick boxes are boxes")

# --- an answer is still a field --------------------------------------------
from storefront.backend.documents import GLOBAL_TOKENS as _GT
_local = next(t for t in c.get(
    f"/api/store/admin/engagements/{_eid}/docs/{_g6['doc_id']}/blanks",
    headers=A).json()["placeholders"] if t.strip() not in _GT)
c.post(f"/api/store/admin/documents/{_g6['doc_id']}/edit", headers=A,
       json={"fills": {_local: "Boxed Co"}, "regions": {}})
_pvf = c.get(f"/api/store/admin/documents/{_g6['doc_id']}/preview",
             headers=A).text
ok("fbox-set" in _pvf and "Boxed Co" in _pvf,
   "a filled blank reads as a filled blank — boxed, so you can see what "
   "was set and that it can be set again")
_bodyf = _db.connect().execute("SELECT body FROM documents WHERE id=?",
                               (_g6["doc_id"],)).fetchone()["body"]
ok(f"[{_local}=Boxed Co]" in _bodyf,
   "because filling keeps the name beside the answer instead of erasing it")
_edf = c.get(f"/api/store/admin/documents/{_g6['doc_id']}/editable",
             headers=A).text
ok('value="Boxed Co"' in _edf,
   "so the editor opens on the answer, and changing it is changing a field "
   "rather than retyping a sentence")
c.post(f"/api/store/admin/documents/{_g6['doc_id']}/edit", headers=A,
       json={"regions": {"0": "One sentence a stranger would understand."},
             "fills": {}})
_b6 = _db.connect().execute(
    "SELECT body FROM documents WHERE id=?",
    (_g6["doc_id"],)).fetchone()["body"]
ok("One sentence a stranger would understand." in _b6,
   "an answer typed on a write-in line lands in the document's own text — "
   "answered is answered, and the region is gone")
ok('id="dv-edit"' in _ops and "fillInDoc(did, name, after," in _ops,
   "and View offers Edit on any unsigned authored document, from both tabs")

# --- the binder --------------------------------------------------------------
_be = c.post("/api/store/admin/engagements", headers=A, json={
    "name": "Binder Smoke", "package": "B", "value_cents": 1200000,
    "approver_name": "Kim Doe", "approver_email": "kim@x.test"}).json()
ok(_be.get("binder_doc_id"),
   "a new client is born with its project binder — cover, introduction, "
   "contents, and the pricing and lead sections where the record has them")
_bb = _db.connect().execute("SELECT body FROM documents WHERE id=?",
                            (_be["binder_doc_id"],)).fetchone()["body"]
ok("[CLIENT]" in _bb and "[CLIENT POC]" in _bb and "[INTERNAL POC]" in _bb
   and "[ORIGINATOR]" in _bb and "[DATE]" in _bb,
   "the cover names the client with tokens, not with values — the record "
   "is the source, so the day it changes every page that names the client "
   "changes with it")
_bh0 = c.get(f"/api/store/admin/engagements/{_be['id']}/binder.html",
             headers=A).text
ok("Binder Smoke" in _bh0 and "[CLIENT]" not in _bh0
   and "Kim Doe" in _bh0 and "$12,000.00" in _bh0,
   "and a reader sees the values, never the tokens")
_intro = _db.connect().execute(
    "SELECT d.title, d.body FROM engagement_docs ed JOIN documents d"
    " ON d.id=ed.doc_id WHERE ed.engagement_id=? AND d.notes='binder intro'",
    (_be["id"],)).fetchone()
ok(_intro and "[INTRODUCTION" in _intro["body"],
   "the introduction is its own document, and so its own page — a cover "
   "with an essay under it is not a cover")
ok(_bh0.index("Introduction") < _bh0.index("Table of contents"),
   "and it sits between the title page and the contents, where a foreword "
   "goes")
_bp = c.get(f"/api/store/admin/engagements/{_be['id']}/binder.pdf",
            headers=A)
ok(_bp.status_code == 200 and _bp.content[:5] == b"%PDF-",
   "the whole packet renders as one book — cover first, contents, then "
   "every client-side paper with its signatures")
_ee = c.post(f"/api/store/admin/documents/{_be['binder_doc_id']}/edit",
             headers=A, json={"fills": {"PREPARED BY": "Tom"}}).json()
ok(_ee["party"]["name"] == "Kim Doe",
   "Save & sign prefills the client's named approver — the approver signs, "
   "not the company")
# --- the title page, the people, and the POC handshake ---------------------
# the admin's name may have been changed by an earlier test — the
# originator default is whatever it is NOW, so read it, don't assume it
_me_name = _db.connect().execute(
    "SELECT name FROM users WHERE token=?",
    (admin["token"],)).fetchone()["name"]
# mint the colleague first — this suite's db starts empty, and a POC
# that matches no account is just a label with nobody to ask
_dev = c.post("/api/login", json={"name": "Poc Colleague",
                                  "admin_key": CFG["admin_key"]}).json()
_DA = {"Authorization": f"Bearer {_dev['token']}"}
_bt = c.post("/api/store/admin/engagements", headers=A, json={
    "name": "Title Probe", "approver_name": "Pat Client",
    "approver_email": "pat@client.test", "internal_poc": "Poc Colleague",
    "originator": ""}).json()
_btb = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder.html",
             headers=A).text
ok(CFG["brand_name"] in _btb and "Title Probe" in _btb
   and "Pat Client (pat@client.test)" in _btb
   and "Poc Colleague" in _btb and _me_name in _btb,
   "the binder's title page names the five facts a binder off a shelf must "
   "answer: the brand, the client, both POCs, who started it, and when")
ok("Table of contents" in _btb and "<th>Page</th>" in _btb,
   "and the contents page carries a real table of contents — every "
   "document with the page it starts on in the printed binder")
_bte = c.get(f"/api/store/admin/engagements/{_bt['id']}",
             headers=A).json()["engagement"]
ok(_bte["internal_poc_status"] == "pending",
   "naming a colleague internal POC is pending until they take it — a job "
   "you haven't agreed to isn't yours yet")
ok(c.post(f"/api/store/admin/engagements/{_bt['id']}/poc/accept",
          headers=A).status_code == 403,
   "and nobody else can answer for them, the originator included")
_dn = c.get("/api/notifications", headers=_DA).json()["items"]
ok(any("Internal POC for Title Probe" in (n.get("title") or "")
       for n in _dn),
   "the named colleague is told, not assumed")
c.post(f"/api/store/admin/engagements/{_bt['id']}/poc/decline", headers=_DA)
_bte = c.get(f"/api/store/admin/engagements/{_bt['id']}",
             headers=A).json()["engagement"]
ok(_bte["internal_poc_status"] == "declined",
   "declining is recorded — silence is the one outcome that helps nobody")
_bn = c.get("/api/notifications", headers=A).json()["items"]
ok(any("declined internal POC" in (n.get("title") or "") for n in _bn),
   "and the originator hears about it")

_bh = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder.html",
            headers=A)
ok(_bh.status_code == 200 and "binder-doc" in _bh.text
   and "Project binder" in _bh.text,
   "the binder previews as a page — an embedded PDF is a lottery across "
   "browsers, and a blank frame reads as a broken binder")
ok("blank form, print and fill" in _bh.text
   and "Project roadmap" in _bh.text
   and "Website handover" in _bh.text,
   "every client-side paper is in the binder even before it's generated — "
   "the roadmap included — so the printed binder is the complete packet, "
   "fillable with a pen")
ok("Stage: Proposal accepted" in _bh.text
   and _bh.text.count("<h2") >= 8,
   "and the contents mirror the client's own screen: the stages as "
   "sections, each with what closes it and where that stands, every "
   "paper beneath")
_scan2 = c.post("/api/store/admin/documents", headers=A, json={
    "title": "site-photos.jpg", "category": "other",
    "party_kind": "partner", "party_name": "Title Probe"}).json()
c.post(f"/api/store/admin/documents/{_scan2['id']}/file", headers=A,
       files={"file": ("site-photos.jpg", b"\xff\xd8\xff\xe0x",
                       "image/jpeg")})
c.post(f"/api/store/admin/engagements/{_bt['id']}/attach", headers=A,
       json={"doc_id": _scan2["id"], "stage": "01-potential-customer",
             "side": "to_client"})
_bh2 = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder.html",
             headers=A).text
ok("site-photos.jpg" in _bh2 and "attachment, filed beside" in _bh2,
   "attachments are listed in the contents, filed beside the binder — a "
   "markdown PDF can't swallow a photograph, but it can say where it lives")
ok('id="ef-files"' in _ops and '"01-potential-customer"' in _ops
   and "bd-edit" in _ops,
   "the new-client form takes attachments, and the binder modal edits its "
   "own cover — the title page is a document like any other")

# --- the whole binder, editable --------------------------------------------
_bed = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder/editable",
             headers=A)
ok(_bed.status_code == 200
   and 'data-doc="' in _bed.text and 'data-tpl="' in _bed.text,
   "the binder opens as one editable page: authored sections save through "
   "the document editor, blank forms carry the template they'd generate")
ok("bd-static" in _bed.text,
   "with the contents page sitting read-only between them")
ok("binderEditMode" in _ops
   and "i.value !== initialToks.get(i)" in _ops,
   "and only what YOU changed counts as touched — suggested values arrive "
   "pre-filled, and without the initial-value check every blank form would "
   "save itself into existence on the strength of its own suggestions")
_binderfn = _ops.split("async function binderEditMode")[1].split(
    "\nasync function ")[0]
ok('sign.textContent = "Sign this page"' in _binderfn
   and "signCard = async (card)" in _binderfn
   and "engSignForm(out.id" in _binderfn,
   "a page can be signed from inside the binder — a book has many "
   "signatures and they belong to different pages, not to a footer")
ok("const saveCard = async (card, force)" in _binderfn
   and _binderfn.count("await saveCard(") == 2,
   "and Sign-this-page saves through the same writer as Save-the-binder — "
   "a signature attesting to a slightly different save path is a signature "
   "to argue about")
ok("if (!touched && !force) return null;" in _binderfn,
   "signing a blank form generates it first: you cannot sign a page that "
   "does not exist yet")
ok(".bd-sign" in c.get(
       f"/api/store/admin/engagements/{_bt['id']}/binder/editable",
       headers=A).text
   and "@media print{.bd-sign{display:none}}" in c.get(
       f"/api/store/admin/engagements/{_bt['id']}/binder/editable",
       headers=A).text,
   "the control is styled with the binder and hidden from print — the "
   "printable book stays a printable book")
ok("out.doc_id" in _binderfn,
   "a touched blank form generates the document for this client, then the "
   "written answers land on it")

# --- cells, names, and the ongoing clause ----------------------------------
from storefront.backend.documents import scan_regions as _scan_r
_cells = [r for r in _scan_r("| A | B |\n|---|---|\n| x | |\n")
          if r["kind"] == "cell"]
ok(len(_cells) == 1,
   "an empty table cell is a blank the template meant to be filled — "
   "whitespace nobody can type into is a form with holes in it")
ok('ph-cell' in _bed.text or 'ph-cell' in c.get(
    f"/api/store/admin/engagements/{_bt['id']}/binder/editable",
    headers=A).text,
   "and the binder editor renders them as fields")
_bh3 = c.get(f"/api/store/admin/engagements/{_bt['id']}/binder.html",
             headers=A).text
ok("[CLIENT]" not in _bh3.split("In this binder")[1].split("</div>")[0]
   and "[PROJECT]" not in _bh3.split("In this binder")[1].split("</div>")[0],
   "blank forms in the contents already belong to the client — 'Project "
   "roadmap — Title Probe', never '— [CLIENT]'")
_cc = (_studio / "templates" / "04-agreement" / "contracts"
       / "common-clauses.md").read_text()
ok("## 15. Ongoing support" in _cc and "[INITIALS]" in _cc.split("## 15.")[1]
   and "actively exploited vulnerabilities" in _cc,
   "the contract says how continuous work is carried — under a care plan, "
   "or ad hoc with the risk of declining recorded in writing — and the "
   "clause takes initials like the other load-bearing ones")
for _cf2 in ("week-website", "partially-custom", "fully-custom",
             "branding-creative"):
    _ct3 = (_studio / "templates" / "04-agreement" / "contracts"
            / f"{_cf2}.md").read_text()
    _inc = [seg[-60:] for seg in _ct3.split("Common Clauses]")[:-1]]
    ok(any("15" in seg for seg in _inc),
       f"{_cf2} incorporates the ongoing-support clause")
ok("function wirePageCount" in _ops and 'class="pg-in"' in _ops,
   "every document view counts its pages — a page being one printable "
   "sheet at letter aspect, which is the same rule the frame draws, so the "
   "number always names a line you can see")
ok('e.key === "Enter"' in _ops.split("function wirePageCount")[1][:2600]
   and 'behavior: near ? "smooth" : "auto"' in _ops,
   "and the count is the way in: type a page, press enter, and a "
   "hundred-page binder is one keystroke from any page in it")
ok("PAGE_RULE_CSS" in Path("src/storefront/backend/documents.py").read_text()
   and "--page-h" in _ops,
   "and the boundary is drawn from the height the counter measures — one "
   "definition of a page, not two")
for _pid in ("dv-pages", "fid-pages", "bd-pages"):
    ok(f'id="{_pid}"' in _ops,
       f"{_pid}: the count shows in view, in the editor, and in the binder")
# One typography for every rendering: when preview and editor disagreed
# about line-height, the editor was a different document that happened to
# hold the same words — and it paginated like one.
_docsrc = Path("src/storefront/backend/documents.py").read_text()
ok("DOC_BASE_CSS = (" in _docsrc and "FIELD_CSS = (" in _docsrc
   and "EDITABLE_CSS = DOC_BASE_CSS + FIELD_CSS" in _docsrc,
   "the reading shell and the editing shell are one base plus fields, not "
   "two stylesheets that drifted apart")
_engsrc = Path("src/storefront/backend/engagements.py").read_text()
ok(_engsrc.count("vault.DOC_BASE_CSS") + _engsrc.count("vault.EDITABLE_CSS")
   >= 2 and "line-height:1.6" not in _engsrc,
   "and both binder shells render from it, so neither can set its own "
   "line-height behind the other's back")
ok('rows="1"' in _docsrc and "function wireAutoGrow" in _ops,
   "an answer box starts the height of the printed line it replaces and "
   "grows to what you type, rather than reserving two rows nobody asked for")

# --- a title that names the client follows the client -----------------------
_ren = c.post("/api/store/admin/engagements", headers=A,
              json={"name": "Old Name Co"}).json()
c.post(f"/api/store/admin/engagements/{_ren['id']}/docs", headers=A,
       json={"template_path": "03-proposal/proposal-template.md"})
c.patch(f"/api/store/admin/engagements/{_ren['id']}", headers=A,
        json={"name": "New Name Co"})
_rt = [d["title"] for d in
       c.get(f"/api/store/admin/engagements/{_ren['id']}",
             headers=A).json()["docs"]]
ok(all("Old Name Co" not in t for t in _rt)
   and any("New Name Co" in t for t in _rt),
   "renaming the client renames every document filed under them — a "
   "binder full of papers still saying the old name is a binder that "
   "disagrees with its own cover")
# The same edit, from one page of the binder rather than the binder: a
# record field is the client's, so which door you came through must not
# decide whether the client's name changes.
_one = [d for d in c.get(f"/api/store/admin/engagements/{_ren['id']}",
        headers=A).json()["docs"] if d["title"].startswith("Proposal")][0]
_oe = c.post(f"/api/store/admin/documents/{_one['id']}/edit", headers=A,
             json={"fills": {"CLIENT NAME": "Third Name Co"},
                   "regions": {}}).json()
ok("name" in (_oe.get("record") or []),
   "typing the client's name on one document writes the client's name — "
   "the record is where it lives, whichever editor you opened")
_rt2 = c.get(f"/api/store/admin/engagements/{_ren['id']}", headers=A).json()
ok(_rt2["engagement"]["name"] == "Third Name Co"
   and all("New Name Co" not in d["title"] for d in _rt2["docs"]),
   "and every title follows from there, not just the one you were on")
_body1 = _db.connect().execute("SELECT body FROM documents WHERE id=?",
                               (_one["id"],)).fetchone()["body"]
ok("[CLIENT NAME=" not in _body1,
   "the token stays a token — baking it here is exactly how one document "
   "starts disagreeing with the next")

# The new name containing the old one is the case that doubled: rename to
# "X Labs", then swap "X" for "X Labs" inside the result, and the cover
# says "X Labs Labs".
c.patch(f"/api/store/admin/engagements/{_ren['id']}", headers=A,
        json={"name": "Third Name Co Labs"})
_rt3 = [d["title"] for d in c.get(f"/api/store/admin/engagements/{_ren['id']}",
        headers=A).json()["docs"]]
ok(all(t.count("Labs") == 1 for t in _rt3)
   and all(t.endswith("Third Name Co Labs") for t in _rt3),
   "renaming to a name that contains the old one renames once, not twice")
c.patch(f"/api/store/admin/engagements/{_ren['id']}", headers=A,
        json={"name": "Third Name Co"})

_bed2 = c.get(f"/api/store/admin/engagements/{_ren['id']}/binder/editable",
              headers=A).text
_sed2 = c.get(f"/api/store/admin/documents/{_one['id']}/editable",
              headers=A).text
ok('class="bd-title"' in _sed2,
   "and a document's title is a field in its own editor too, not only in "
   "the binder — the name in the heading is the one people read first")
ok('class="bd-title-row"' in _sed2
   and 'class="bd-title bd-title-cl ph ph-global"' in _sed2
   and 'data-global="client"' in _sed2,
   "a heading that names the client IS the client's field — typing in the "
   "heading moves the client, and moving the client moves the heading")
ok("GLOBAL_TOKS" in _ops
   and "!GLOBAL_TOKS.has(k)" in _ops,
   "and changing the client does not conjure every blank form into "
   "existence just because their copy of the name moved with it")
ok('class="bd-title"' in _bed2,
   "and a title is a field in the editor, because the one thing you could "
   "not change was the line you read first")
_conr = _db.connect()
_conr.execute("DELETE FROM documents WHERE id IN (SELECT doc_id FROM"
              " engagement_docs WHERE engagement_id=?)", (_ren["id"],))
for _t in ("engagement_docs", "engagement_gates", "engagement_log",
           "engagement_dates"):
    _conr.execute(f"DELETE FROM {_t} WHERE engagement_id=?", (_ren["id"],))
_conr.execute("DELETE FROM engagements WHERE id=?", (_ren["id"],))
_conr.commit(); _conr.close()

ok('data-global=' in Path("src/storefront/backend/documents.py").read_text()
   and 'input[data-global="${inp.dataset.global}"]' in _ops,
   "a record field moves every one of its twins in the whole book — the "
   "client does not change from one form to the next")
ok("def apply_globals" in _engsrc and "GLOBAL_COLUMN" in _engsrc
   and "eng.apply_globals(" in Path(
       "src/storefront/backend/documents.py").read_text(),
   "and it saves to the client record rather than being baked into one "
   "document's text — decided in one place on the server, so which editor "
   "you opened cannot change the answer")

ok("button.btn[hidden]" in _css3 or "btn[hidden]" in c.get(
    "/ops/styles.css").text,
   "a button marked hidden is hidden — .btn sets its own display, which "
   "beats the browser's own [hidden] rule")

ok("function frameAnchor" in _ops and "function restoreAnchor" in _ops
   and "fillInDoc(did, name, after, at)" in _ops
   and "binderEditMode(id, e, frameAnchor(bdFrame))" in _ops,
   "Edit opens where you were reading — the anchor is read before the "
   "modal goes and restored once the editor has loaded")
ok("secIdx" in _ops and "elIdx" in _ops
   and 'classList.contains("bd-note")' in _ops,
   "and it anchors to the block you were looking at, not the page number "
   "or the section: input boxes are taller than the text they replace, so "
   "the same page number — or the same offset into a taller section — "
   "lands on earlier content")

ok('closest(".doc-line, .sig-row")' in _ops,
   "and the viewer reads its title from the row class the rows actually "
   "have — the stage rows became .doc-line and the lookup went stale")

ok("ongoing_support_agreed" in _ops
   and "Ongoing — security, monitoring, updates, support" in (
       Path(__file__).parent.parent
       / "src/storefront/backend/engagements.py").read_text(
           encoding="utf-8"),
   "the ongoing gate is on the track and the Gantt — a lane that starts "
   "when handover ends and does not stop")
c.delete(f"/api/store/admin/documents/{_scan2['id']}", headers=A)
_bf = c.post(f"/api/store/admin/engagements/{_bt['id']}/binder",
             headers=A).json()
ok(not _bf["created"],
   "one binder per client — backfill returns the one that exists")

_conb2 = _db.connect()
for _t in ("engagement_docs", "engagement_gates", "engagement_log",
           "engagement_dates"):
    _conb2.execute(f"DELETE FROM {_t} WHERE engagement_id=?", (_bt["id"],))
_conb2.execute("DELETE FROM document_events WHERE document_id=?",
               (_bt["binder_doc_id"],))
_conb2.execute("DELETE FROM documents WHERE id=?", (_bt["binder_doc_id"],))
_conb2.execute("DELETE FROM engagements WHERE id=?", (_bt["id"],))
_conb2.execute("DELETE FROM notifications WHERE title LIKE '%Title Probe%'")
_conb2.commit(); _conb2.close()

ok('id="fid-sign"' in _ops and "engSignForm(did, out.party" in _ops,
   "and the editor's own footer carries Save & sign, edits landing before "
   "the request — a signature attests to the text as it stands")
_conb = _db.connect()
for _t in ("engagement_docs", "engagement_gates", "engagement_log",
           "engagement_dates"):
    _conb.execute(f"DELETE FROM {_t} WHERE engagement_id=?", (_be["id"],))
for _d2 in (_be["binder_doc_id"],):
    _conb.execute("DELETE FROM document_events WHERE document_id=?", (_d2,))
    _conb.execute("DELETE FROM documents WHERE id=?", (_d2,))
_conb.execute("DELETE FROM engagements WHERE id=?", (_be["id"],))
_conb.commit(); _conb.close()
c.delete(f"/api/store/admin/documents/{_g6['doc_id']}", headers=A)
c.delete(f"/api/store/admin/documents/{_g5['doc_id']}", headers=A)

# View opens an in-app viewer, never window.open after an await: the popup
# blocker eats a window opened outside the user-gesture call stack, and the
# button reads as broken to exactly the person clicking it.
_viewer = _ops.split("async function docViewer")[1][:4200]
_before_open = _viewer.split('$("#dv-open")')[0]
ok('id="dv-sign"' in _viewer and "engSignForm(did, preset || {}" in _viewer,
   "the viewer signs what it is showing: having just read the document, "
   "closing it to find the row's button is a step that exists only because "
   "of how the page was built")
ok('signed ? "Add a signature" : "Sign"' in _viewer,
   "and it says which it is — a signed document can still take the second "
   "signature it is waiting on")
ok('iframe class="doc-viewer"' in _viewer
   and "window.open" not in _before_open
   and 'window.open(pdfUrl, "_blank")' in _viewer,
   "one shared viewer shows the document in an in-app frame; window.open "
   "lives only in a synchronous click handler, where the user gesture is "
   "still alive and no blocker eats it")
ok("Download" in _viewer and "signed " in _viewer,
   "with the signed PDF as the primary action in the same modal")
ok("data-docview" in _ops and "data-engview" in _ops
   and _ops.count("docViewer(") >= 3,
   "and both the Documents tab and the engagement stages open it — the "
   "signature must be visible wherever the document is")
import shutil as _sh3
_sh3.rmtree(_exp3["root"], ignore_errors=True)
c.delete(f"/api/store/admin/documents/{_g2['doc_id']}", headers=A)

# leave the live db as we found it
import shutil as _sh
for _d in [x["id"] for x in _det["docs"]]:
    c.delete(f"/api/store/admin/documents/{_d}", headers=A)
from erp.backend import db as _dbmod
con_cleanup = _dbmod.connect()
con_cleanup.execute("DELETE FROM engagement_docs WHERE engagement_id=?", (_eid,))
con_cleanup.execute("DELETE FROM engagement_gates WHERE engagement_id=?", (_eid,))
for _dcl in (_gen["doc_id"], _g3["doc_id"]):
    con_cleanup.execute("DELETE FROM document_signatures WHERE document_id=?", (_dcl,))
    con_cleanup.execute("DELETE FROM document_events WHERE document_id=?", (_dcl,))
    con_cleanup.execute("DELETE FROM documents WHERE id=?", (_dcl,))
con_cleanup.execute("DELETE FROM document_signatures WHERE document_id=?", (_gen["doc_id"],))
con_cleanup.execute("DELETE FROM document_events WHERE document_id=?", (_gen["doc_id"],))
con_cleanup.execute("DELETE FROM documents WHERE id=?", (_gen["doc_id"],))
con_cleanup.execute("DELETE FROM engagement_log WHERE engagement_id=?", (_eid,))
con_cleanup.execute("DELETE FROM engagement_dates WHERE engagement_id=?", (_eid,))
con_cleanup.execute("DELETE FROM engagements WHERE id=?", (_eid,))
con_cleanup.commit(); con_cleanup.close()
_sh.rmtree(_exp["root"], ignore_errors=True)


done("studio")
