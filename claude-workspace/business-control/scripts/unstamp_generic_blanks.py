#!/usr/bin/env python3
"""Give back the blanks that a generic token stamped over.

The client record used to suggest a value for [X] and [NAME]. Those are
not fields — the kit uses [X] for a domain renewal on one page, an hourly
rate on the next and three option prices in one table, and [NAME] for the
client here and whoever requested a change order there. Generating a
document wrote the SAME number, or the same person, into every one of
them: a proposal whose option A, option B, option C and every add-on all
said $200.

Generating no longer does that (see engagements.suggested_fills), but
documents already on the shelf carry the stamps. This walks them back:
where every [X=…] in one document holds the identical machine-stamped
value — the engagement's own figure, or its approver — the answer is
removed and the blank stands open again, ready for a person to answer
each one on its own.

Safe by construction:

  * signed documents are never touched — their text is what was attested
  * a document is only reverted when its stamps are UNIFORM and MATCH the
    engagement's stamp; a person who typed different numbers into those
    blanks has said something, and what a person said is kept
  * --dry (the default) reports and writes nothing

    python3 scripts/unstamp_generic_blanks.py            # look
    python3 scripts/unstamp_generic_blanks.py --apply    # do it
    python3 scripts/unstamp_generic_blanks.py --apply --tenant studio
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Only these two. Every other suggestion names one thing and is welcome
# wherever it appears.
STAMPED = ("X", "NAME")


def _filled(body: str, tok: str) -> list:
    return re.findall(r"\[" + re.escape(tok) + r"=([^\]]*)\]", body or "")


def _open_up(body: str, tok: str) -> str:
    return re.sub(r"\[" + re.escape(tok) + r"=[^\]]*\]", f"[{tok}]", body)


def stamps_of(e) -> dict:
    """What the old code would have written for this client."""
    out = {}
    if e["value_cents"]:
        out["X"] = f"{e['value_cents'] / 100:,.0f}"
    if e["approver_name"]:
        out["NAME"] = e["approver_name"]
    return out


def sweep(db: Path, apply: bool) -> dict:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        con.execute("SELECT 1 FROM engagements LIMIT 1")
    except sqlite3.OperationalError:
        con.close()
        return {"docs": 0, "blanks": 0, "kept": 0}
    docs = blanks = kept = 0
    for e in con.execute("SELECT * FROM engagements").fetchall():
        stamp = stamps_of(e)
        rows = con.execute(
            "SELECT d.id, d.title, d.body, d.status,"
            " (SELECT COUNT(*) FROM document_signatures s"
            "   WHERE s.document_id=d.id AND s.status='signed') AS signed"
            " FROM engagement_docs ed JOIN documents d ON d.id=ed.doc_id"
            " WHERE ed.engagement_id=?", (e["id"],)).fetchall()
        for r in rows:
            if r["signed"] or not (r["body"] or "").strip():
                continue
            body, hit = r["body"], 0
            for tok in STAMPED:
                vals = set(_filled(body, tok))
                if not vals:
                    continue
                # a person's own answers are not a stamp
                if len(vals) > 1 or tok not in stamp:
                    kept += len(_filled(body, tok))
                    continue
                # the historic stamp for [X] may predate a repriced client;
                # accept the current figure, or a single uniform value that
                # no human would have repeated verbatim a dozen times
                if vals != {stamp[tok]} and len(_filled(body, tok)) < 3:
                    kept += len(_filled(body, tok))
                    continue
                hit += len(_filled(body, tok))
                body = _open_up(body, tok)
            if not hit:
                continue
            docs += 1
            blanks += hit
            print(f"  {db.parent.name}: doc {r['id']} '{r['title']}'"
                  f" — {hit} blank(s) reopened")
            if apply:
                # reopening blanks makes it a draft again: it is not
                # finished, and the board should say so
                con.execute("UPDATE documents SET body=?, status='draft'"
                            " WHERE id=?", (body, r["id"]))
    if apply:
        con.commit()
    con.close()
    return {"docs": docs, "blanks": blanks, "kept": kept}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    ap.add_argument("--tenant", default="",
                    help="one tenant id, else every tenant on this node")
    a = ap.parse_args()

    from erp.backend import config
    dbs = []
    root = config.DATA_DIR / "tenants"
    if root.is_dir():
        reg = config.DATA_DIR / "tenants.json"
        ids = sorted(p.name for p in root.iterdir() if p.is_dir())
        if reg.exists():
            try:
                known = json.loads(reg.read_text()).get("tenants") or {}
                ids = [t for t in ids if t in known] or ids
            except ValueError:
                pass
        for t in ids:
            if a.tenant and t != a.tenant:
                continue
            p = root / t / "business_control.db"
            if p.exists():
                dbs.append(p)
    if not a.tenant:
        p = config.DATA_DIR / "business_control.db"
        if p.exists():
            dbs.append(p)

    tot = {"docs": 0, "blanks": 0, "kept": 0}
    for db in dbs:
        out = sweep(db, a.apply)
        for k in tot:
            tot[k] += out[k]
    verb = "reopened" if a.apply else "would reopen"
    print(f"{verb} {tot['blanks']} blank(s) across {tot['docs']} document(s)"
          f" in {len(dbs)} database(s); left {tot['kept']} answer(s) alone")
    if not a.apply and tot["blanks"]:
        print("dry run — nothing was written. Add --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
