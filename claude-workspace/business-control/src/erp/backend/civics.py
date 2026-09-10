"""Civics and policy: the places a business sits in, and what they are doing.

A business is inside a stack of jurisdictions at once — a city, a county,
a state, a congressional district, a country — and every one of them can
change a rule that costs it money. A minimum wage ordinance, a licensing
change, a zoning decision, a ballot measure on a sales tax. The
information exists, and it exists in a dozen places none of which knows
the business is there.

So this holds four things and one map:

  * **Jurisdictions**, in a tree, each with a point on the map and
    optionally a boundary. A business's own stores are plotted beside
    them, which is the question that starts every enquiry: what are we
    inside, here?
  * **Officials**, so "who do we call about this" has an answer that is
    not a search engine.
  * **Measures** — bills, ordinances, rules, ballot questions — with the
    business's own position and how much it would matter. Tracking a
    bill without recording what you think of it is a news feed.
  * **Elections**, because a date is the thing everything else hangs off.

And, separately, a **register of political giving**. That one is written
to be a disclosure record and nothing else: who received it, under which
jurisdiction's rules, how much, when, who authorised it, and the
reference of the filing it appears in. Political contributions by a
business are regulated nearly everywhere and the rules differ by every
level of the stack above. This records what was done so it can be
reported and audited. **It gives no advice, checks no limit, and files
nothing** — a screen that implied otherwise would be worse than a
spreadsheet, because a spreadsheet does not look like it has checked.

On the map: it is drawn from what the install actually knows, projected
here, with no tiles and no outside service. That is a deliberate limit —
there is no basemap, so a jurisdiction is where somebody said it is —
and it is the reason the page works on a laptop with no internet and
sends nothing anywhere.
"""
import json
import time
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db
from . import integrations as IG

TABLES = """
CREATE TABLE IF NOT EXISTS jurisdictions (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'city',      -- see LEVELS
  parent_id INTEGER DEFAULT 0,
  code TEXT DEFAULT '',                    -- FIPS, OCD id, whatever they use
  lat REAL, lng REAL,
  boundary TEXT DEFAULT '',                -- GeoJSON geometry, when imported
  population INTEGER DEFAULT 0,
  watching INTEGER DEFAULT 1,              -- is this one of ours?
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jurisdictions_level ON jurisdictions(level);

CREATE TABLE IF NOT EXISTS officials (
  id INTEGER PRIMARY KEY,
  jurisdiction_id INTEGER DEFAULT 0,
  name TEXT NOT NULL,
  office TEXT DEFAULT '',
  party TEXT DEFAULT '',
  district TEXT DEFAULT '',
  term_start REAL DEFAULT 0,
  term_end REAL DEFAULT 0,
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  url TEXT DEFAULT '',
  incumbent INTEGER DEFAULT 1,
  external_id TEXT DEFAULT '',
  source TEXT DEFAULT 'typed',
  note TEXT DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS officials_j ON officials(jurisdiction_id);

/* A bill, an ordinance, a rule or a ballot question. `position` is the
   business's own view of it, which is what separates this from a news
   feed: tracking something without recording what you think of it means
   the next person to open the page starts from nothing. */
CREATE TABLE IF NOT EXISTS measures (
  id INTEGER PRIMARY KEY,
  jurisdiction_id INTEGER DEFAULT 0,
  ref TEXT DEFAULT '',                     -- HB 1234, Ordinance 22-15
  title TEXT NOT NULL,
  summary TEXT DEFAULT '',
  url TEXT DEFAULT '',
  kind TEXT DEFAULT 'bill',                -- bill|ordinance|rule|ballot|other
  status TEXT DEFAULT 'introduced',        -- see STATUSES
  introduced_at REAL DEFAULT 0,
  last_action_at REAL DEFAULT 0,
  last_action TEXT DEFAULT '',
  position TEXT DEFAULT 'watch',           -- support|oppose|watch|neutral
  impact TEXT DEFAULT 'medium',            -- high|medium|low
  why TEXT DEFAULT '',                     -- what it would do to US
  owner_id INTEGER DEFAULT 0,
  external_id TEXT DEFAULT '',
  source TEXT DEFAULT 'typed',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS measures_j ON measures(jurisdiction_id, status);

CREATE TABLE IF NOT EXISTS measure_events (
  id INTEGER PRIMARY KEY,
  measure_id INTEGER NOT NULL,
  at REAL NOT NULL,
  what TEXT NOT NULL,
  source TEXT DEFAULT 'typed',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS measure_events_m ON measure_events(measure_id, at);

CREATE TABLE IF NOT EXISTS elections (
  id INTEGER PRIMARY KEY,
  jurisdiction_id INTEGER DEFAULT 0,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'general',             -- general|primary|special|runoff|referendum
  at REAL NOT NULL,
  registration_deadline REAL DEFAULT 0,
  url TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS elections_at ON elections(at);

/* A disclosure record. Every field here exists because a filing asks for
   it. Nothing here checks a limit or files anything — see the module
   docstring, and mean it. */
CREATE TABLE IF NOT EXISTS contributions (
  id INTEGER PRIMARY KEY,
  jurisdiction_id INTEGER DEFAULT 0,
  election_id INTEGER DEFAULT 0,
  recipient TEXT NOT NULL,
  recipient_kind TEXT DEFAULT 'committee', -- candidate|committee|party|ballot_measure|pac
  recipient_id TEXT DEFAULT '',            -- their filer id, where there is one
  amount_cents INTEGER NOT NULL,
  at REAL NOT NULL,
  method TEXT DEFAULT '',
  authorised_by TEXT DEFAULT '',           -- the person who said yes
  disclosure_ref TEXT DEFAULT '',          -- the filing it appears in
  disclosed_at REAL DEFAULT 0,
  expense_id INTEGER DEFAULT 0,            -- the cost, once filed as one
  note TEXT DEFAULT '',
  recorded_by TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS contributions_at ON contributions(at);
"""

LEVELS = {
    "country": "Country",
    "state": "State or province",
    "county": "County",
    "district": "Congressional or legislative district",
    "city": "City or municipality",
    "ward": "Ward or precinct",
    "other": "Other",
}
# Roughly the order a thing travels in. Kept loose on purpose: a hundred
# legislatures have a hundred sets of stages, and a status list that
# claimed to model all of them would be wrong everywhere.
STATUSES = ("introduced", "in_committee", "passed_one", "passed_both",
            "signed", "enacted", "failed", "vetoed", "withdrawn")
POSITIONS = ("support", "oppose", "watch", "neutral")
IMPACTS = ("high", "medium", "low")
MEASURE_KINDS = ("bill", "ordinance", "rule", "ballot", "other")
ELECTION_KINDS = ("general", "primary", "special", "runoff", "referendum")
RECIPIENT_KINDS = ("candidate", "committee", "party", "ballot_measure", "pac")
SOON_DAYS = 90


def init_tables(con):
    con.executescript(TABLES)
    con.commit()


def _office(user) -> bool:
    return auth.office(user, "settings", "documents")


def _may_see(user) -> bool:
    return _office(user) or user["role"] in ("employee", "director", "board")


def _require(user) -> None:
    if not _office(user):
        raise HTTPException(403, "the policy register is the office's")


# ---------- the map ----------

def map_data(con) -> dict:
    """Everything with a position on it: the jurisdictions being watched,
    and the business's own places, which is what makes the map answer
    'what are we inside, here?' rather than merely draw a country."""
    js = [dict(r) for r in con.execute(
        "SELECT id, name, level, parent_id, lat, lng, boundary, population,"
        " watching FROM jurisdictions ORDER BY level, name").fetchall()]
    for j in js:
        if j["boundary"]:
            try:
                j["boundary"] = json.loads(j["boundary"])
            except ValueError:
                j["boundary"] = None
        else:
            j["boundary"] = None
    places = []
    try:
        places = [dict(r) for r in con.execute(
            "SELECT id, name, city, region, lat, lng FROM stores"
            " WHERE active=1 AND lat IS NOT NULL AND lng IS NOT NULL"
            ).fetchall()]
    except Exception:                                        # noqa: BLE001
        places = []
    pts = [(j["lat"], j["lng"]) for j in js
           if j["lat"] is not None and j["lng"] is not None]
    pts += [(p["lat"], p["lng"]) for p in places]
    bounds = None
    if pts:
        lats = [p[0] for p in pts]
        lngs = [p[1] for p in pts]
        bounds = {"min_lat": min(lats), "max_lat": max(lats),
                  "min_lng": min(lngs), "max_lng": max(lngs)}
    return {"jurisdictions": js, "places": places, "bounds": bounds}


def _counts(con) -> dict:
    now = time.time()
    soon = now + SOON_DAYS * 86400
    return {
        "watching": con.execute(
            "SELECT COUNT(*) AS n FROM jurisdictions WHERE watching=1"
            ).fetchone()["n"],
        "live_measures": con.execute(
            "SELECT COUNT(*) AS n FROM measures WHERE status NOT IN"
            " ('enacted','failed','vetoed','withdrawn')").fetchone()["n"],
        "high_impact": con.execute(
            "SELECT COUNT(*) AS n FROM measures WHERE impact='high' AND"
            " status NOT IN ('enacted','failed','vetoed','withdrawn')"
            ).fetchone()["n"],
        "elections_soon": con.execute(
            "SELECT COUNT(*) AS n FROM elections WHERE at BETWEEN ? AND ?",
            (now, soon)).fetchone()["n"],
    }


def shape_measure(con, r) -> dict:
    d = dict(r)
    j = con.execute("SELECT name, level FROM jurisdictions WHERE id=?",
                    (d["jurisdiction_id"],)).fetchone() \
        if d["jurisdiction_id"] else None
    d["jurisdiction"] = j["name"] if j else ""
    d["jurisdiction_level"] = j["level"] if j else ""
    d["closed"] = d["status"] in ("enacted", "failed", "vetoed", "withdrawn")
    return d


# ---------- outside sources ----------
# Each needs a key the business gets for itself. None of them covers
# everything: Open States is US state legislatures, Congress.gov is the
# US federal one, and Google Civic answers "who represents this address".
# Below the state level, most of the country publishes nothing an API can
# read, which is why typing a measure in by hand is a first-class path
# here rather than a fallback.

def _check_open_states(c: dict) -> tuple:
    ok, d = IG._req("https://v3.openstates.org/jurisdictions?per_page=1",
                    headers={"X-API-Key": c.get("api_key", "")})
    return (True, "Open States") if ok else (False, str(d))


def _check_congress(c: dict) -> tuple:
    ok, d = IG._req("https://api.congress.gov/v3/bill?limit=1&format=json"
                    f"&api_key={urllib.parse.quote(c.get('api_key', ''))}")
    return (True, "Congress.gov") if ok else (False, str(d))


def _check_google_civic(c: dict) -> tuple:
    q = urllib.parse.urlencode({"key": c.get("api_key", ""),
                                "address": c.get("address", "")})
    ok, d = IG._req(
        "https://www.googleapis.com/civicinfo/v2/representatives?" + q)
    if not ok:
        return False, str(d)
    who = (d.get("normalizedInput") or {}) if isinstance(d, dict) else {}
    return True, ", ".join(x for x in (who.get("city"), who.get("state"))
                           if x) or "Google Civic"


IG.CHECKS["open_states"] = _check_open_states
IG.CHECKS["congress_gov"] = _check_congress
IG.CHECKS["google_civic"] = _check_google_civic


def _jurisdiction_by_name(con, name: str, level: str = "state") -> int:
    r = con.execute("SELECT id FROM jurisdictions WHERE lower(name)=lower(?)",
                    (name,)).fetchone()
    if r:
        return r["id"]
    cur = con.execute(
        "INSERT INTO jurisdictions(name,level,watching,created_at)"
        " VALUES(?,?,0,?)", (name[:120], level, db.now()))
    con.commit()
    return cur.lastrowid


def _upsert_measure(con, *, source: str, ext: str, jid: int, ref: str,
                    title: str, summary: str, url: str, status: str,
                    introduced: float, last_at: float, last: str) -> bool:
    """True when it is new. An update never touches position, impact or
    why: those are the business's own view and a refresh from the source
    must not overwrite what somebody here decided."""
    have = con.execute("SELECT id FROM measures WHERE source=? AND"
                       " external_id=?", (source, ext)).fetchone()
    now = time.time()
    if have:
        con.execute(
            "UPDATE measures SET title=?, summary=?, url=?, status=?,"
            " last_action_at=?, last_action=?, updated_at=? WHERE id=?",
            (title[:300], summary[:4000], url[:400], status, last_at,
             last[:300], now, have["id"]))
        if last:
            seen = con.execute(
                "SELECT 1 FROM measure_events WHERE measure_id=? AND at=?"
                " AND what=?", (have["id"], last_at, last[:300])).fetchone()
            if not seen:
                con.execute(
                    "INSERT INTO measure_events(measure_id,at,what,source,"
                    " created_at) VALUES(?,?,?,?,?)",
                    (have["id"], last_at, last[:300], source, db.now()))
        con.commit()
        return False
    cur = con.execute(
        "INSERT INTO measures(jurisdiction_id,ref,title,summary,url,status,"
        " introduced_at,last_action_at,last_action,external_id,source,"
        " created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (jid, ref[:60], title[:300], summary[:4000], url[:400], status,
         introduced, last_at, last[:300], ext, source, db.now(), now))
    if last:
        con.execute(
            "INSERT INTO measure_events(measure_id,at,what,source,created_at)"
            " VALUES(?,?,?,?,?)",
            (cur.lastrowid, last_at, last[:300], source, db.now()))
    con.commit()
    return True


def _when(s) -> float:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(str(s)[:19], fmt))
        except (ValueError, TypeError):
            continue
    return 0.0


def _fold_status(text: str) -> str:
    t = (text or "").lower()
    for needle, status in (("enact", "enacted"), ("became law", "enacted"),
                           ("signed", "signed"), ("veto", "vetoed"),
                           ("withdraw", "withdrawn"), ("fail", "failed"),
                           ("died", "failed"), ("passed both", "passed_both"),
                           ("committee", "in_committee")):
        if needle in t:
            return status
    return "introduced"


def pull_open_states(con, query: str) -> dict:
    """Bills for a US state legislature, by search term."""
    c = IG.creds(con, "open_states")
    if not c:
        raise HTTPException(400, "connect Open States first")
    s = IG.settings(con, "open_states")
    juris = (s.get("jurisdiction") or "").strip()
    if not juris:
        raise HTTPException(400, "set which jurisdiction to search — a state "
                                 "name, or an OCD id")
    q = urllib.parse.urlencode({"jurisdiction": juris, "q": query or "",
                                "per_page": 20, "sort": "updated_desc"})
    ok, d = IG._req(f"https://v3.openstates.org/bills?{q}",
                    headers={"X-API-Key": c.get("api_key", "")})
    if not ok:
        IG.log(con, "open_states", "pull_measures", False, str(d)[:200])
        raise HTTPException(400, f"Open States said: {d}")
    jid = _jurisdiction_by_name(con, juris, "state")
    new = 0
    for b in (d.get("results") or []) if isinstance(d, dict) else []:
        acts = b.get("latest_action_description") or ""
        if _upsert_measure(
                con, source="open_states", ext=str(b.get("id")), jid=jid,
                ref=b.get("identifier", ""), title=b.get("title", ""),
                summary=(b.get("abstracts") or [{}])[0].get("abstract", "")
                if b.get("abstracts") else "",
                url=b.get("openstates_url", ""),
                status=_fold_status(acts),
                introduced=_when(b.get("first_action_date")),
                last_at=_when(b.get("latest_action_date")), last=acts):
            new += 1
    IG.log(con, "open_states", "pull_measures", True, f"{new} new")
    return {"ok": True, "new": new, "seen": len(d.get("results") or [])}


def pull_congress(con, query: str) -> dict:
    """Federal bills. Congress.gov's search is by congress and type, so
    this takes the most recently updated and filters on the term."""
    c = IG.creds(con, "congress_gov")
    if not c:
        raise HTTPException(400, "connect Congress.gov first")
    key = urllib.parse.quote(c.get("api_key", ""))
    ok, d = IG._req(f"https://api.congress.gov/v3/bill?limit=50&format=json"
                    f"&sort=updateDate+desc&api_key={key}")
    if not ok:
        IG.log(con, "congress_gov", "pull_measures", False, str(d)[:200])
        raise HTTPException(400, f"Congress.gov said: {d}")
    jid = _jurisdiction_by_name(con, "United States", "country")
    term = (query or "").lower()
    new, seen = 0, 0
    for b in (d.get("bills") or []) if isinstance(d, dict) else []:
        title = b.get("title", "")
        if term and term not in title.lower():
            continue
        seen += 1
        acts = (b.get("latestAction") or {})
        ext = f"{b.get('congress')}-{b.get('type')}-{b.get('number')}"
        if _upsert_measure(
                con, source="congress_gov", ext=ext, jid=jid,
                ref=f"{b.get('type', '')}{b.get('number', '')}", title=title,
                summary="", url=b.get("url", ""),
                status=_fold_status(acts.get("text", "")),
                introduced=_when(b.get("introducedDate")),
                last_at=_when(acts.get("actionDate")),
                last=acts.get("text", "")):
            new += 1
    IG.log(con, "congress_gov", "pull_measures", True, f"{new} new")
    return {"ok": True, "new": new, "seen": seen}


def pull_representatives(con) -> dict:
    """Who represents an address, at every level Google knows about."""
    c = IG.creds(con, "google_civic")
    if not c:
        raise HTTPException(400, "connect Google Civic first")
    s = IG.settings(con, "google_civic")
    address = (s.get("address") or "").strip()
    if not address:
        raise HTTPException(400, "set the address to look up — the business's "
                                 "own, usually")
    q = urllib.parse.urlencode({"key": c.get("api_key", ""),
                                "address": address})
    ok, d = IG._req(
        "https://www.googleapis.com/civicinfo/v2/representatives?" + q)
    if not ok:
        IG.log(con, "google_civic", "pull_representatives", False, str(d)[:200])
        raise HTTPException(400, f"Google said: {d}")
    divisions = (d.get("divisions") or {}) if isinstance(d, dict) else {}
    offices = d.get("offices") or []
    people = d.get("officials") or []
    made = 0
    by_division = {}
    for ocd, div in divisions.items():
        level = "other"
        if "/country:" in ocd and ocd.count("/") == 1:
            level = "country"
        elif "/state:" in ocd and "cd:" not in ocd and "place:" not in ocd \
                and "county:" not in ocd:
            level = "state"
        elif "cd:" in ocd or "sldl:" in ocd or "sldu:" in ocd:
            level = "district"
        elif "county:" in ocd:
            level = "county"
        elif "place:" in ocd:
            level = "city"
        r = con.execute("SELECT id FROM jurisdictions WHERE code=?",
                        (ocd,)).fetchone()
        if r is None:
            cur = con.execute(
                "INSERT INTO jurisdictions(name,level,code,watching,"
                " created_at) VALUES(?,?,?,1,?)",
                (div.get("name", ocd)[:120], level, ocd, db.now()))
            by_division[ocd] = cur.lastrowid
        else:
            by_division[ocd] = r["id"]
    con.commit()
    for off in offices:
        jid = by_division.get(off.get("divisionId", ""), 0)
        for idx in off.get("officialIndices") or []:
            if idx >= len(people):
                continue
            per = people[idx]
            ext = f"{off.get('divisionId', '')}:{off.get('name', '')}:{per.get('name', '')}"
            have = con.execute(
                "SELECT id FROM officials WHERE source='google_civic' AND"
                " external_id=?", (ext,)).fetchone()
            args = (jid, per.get("name", "")[:120], off.get("name", "")[:160],
                    (per.get("party") or "")[:80],
                    (per.get("emails") or [""])[0][:200],
                    (per.get("phones") or [""])[0][:40],
                    (per.get("urls") or [""])[0][:400])
            if have:
                con.execute(
                    "UPDATE officials SET jurisdiction_id=?, name=?, office=?,"
                    " party=?, email=?, phone=?, url=? WHERE id=?",
                    args + (have["id"],))
            else:
                con.execute(
                    "INSERT INTO officials(jurisdiction_id,name,office,party,"
                    " email,phone,url,external_id,source,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?, 'google_civic',?)",
                    args + (ext, db.now()))
                made += 1
    con.commit()
    IG.log(con, "google_civic", "pull_representatives", True, f"{made} new")
    return {"ok": True, "new": made, "divisions": len(divisions)}


# ---------- routes ----------

router = APIRouter()

from .main import current_user, get_con  # noqa: E402  (safe: included late)


@router.get("/api/civics")
def civics_page(user=Depends(current_user), con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "the policy register is an office screen")
    now = time.time()
    measures = [shape_measure(con, r) for r in con.execute(
        "SELECT * FROM measures ORDER BY (status NOT IN"
        " ('enacted','failed','vetoed','withdrawn')) DESC,"
        " (impact='high') DESC, last_action_at DESC LIMIT 300").fetchall()]
    status = {p["name"]: p for p in IG.status(con)["providers"]
              if p.get("family") == "civics"}
    return {
        "map": map_data(con),
        "jurisdictions": [dict(r) for r in con.execute(
            "SELECT * FROM jurisdictions ORDER BY level, name").fetchall()],
        "officials": [dict(r) for r in con.execute(
            "SELECT o.*, j.name AS jurisdiction FROM officials o"
            " LEFT JOIN jurisdictions j ON j.id=o.jurisdiction_id"
            " WHERE o.incumbent=1 ORDER BY o.office, o.name LIMIT 300"
            ).fetchall()],
        "measures": measures,
        "elections": [dict(r) for r in con.execute(
            "SELECT e.*, j.name AS jurisdiction FROM elections e"
            " LEFT JOIN jurisdictions j ON j.id=e.jurisdiction_id"
            " WHERE e.at > ? ORDER BY e.at LIMIT 60", (now - 30 * 86400,)
            ).fetchall()],
        "contributions": [dict(r) for r in con.execute(
            "SELECT c.*, j.name AS jurisdiction FROM contributions c"
            " LEFT JOIN jurisdictions j ON j.id=c.jurisdiction_id"
            " ORDER BY c.at DESC LIMIT 200").fetchall()],
        "given_cents": con.execute(
            "SELECT COALESCE(SUM(amount_cents),0) AS c FROM contributions"
            ).fetchone()["c"],
        "undisclosed": con.execute(
            "SELECT COUNT(*) AS n FROM contributions WHERE disclosure_ref=''"
            ).fetchone()["n"],
        "counts": _counts(con),
        "levels": [{"k": k, "label": v} for k, v in LEVELS.items()],
        "statuses": list(STATUSES), "positions": list(POSITIONS),
        "impacts": list(IMPACTS), "measure_kinds": list(MEASURE_KINDS),
        "election_kinds": list(ELECTION_KINDS),
        "recipient_kinds": list(RECIPIENT_KINDS),
        "connections": list(status.values()),
        "disclaimer": "A register, not advice. Nothing here checks a "
                      "contribution limit, reads a statute or files "
                      "anything with anybody.",
    }


class JurisdictionBody(BaseModel):
    id: int = 0
    name: str
    level: str = "city"
    parent_id: int = 0
    code: str = ""
    lat: float | None = None
    lng: float | None = None
    population: int = 0
    watching: bool = True
    note: str = ""
    boundary: dict | None = None


@router.post("/api/civics/jurisdictions")
def jurisdiction_save(body: JurisdictionBody, user=Depends(current_user),
                      con=Depends(get_con)):
    _require(user)
    if body.level not in LEVELS:
        raise HTTPException(400, f"level is one of {sorted(LEVELS)}")
    if not body.name.strip():
        raise HTTPException(400, "a jurisdiction needs a name")
    if body.lat is not None and not -90 <= body.lat <= 90:
        raise HTTPException(400, "a latitude is between -90 and 90")
    if body.lng is not None and not -180 <= body.lng <= 180:
        raise HTTPException(400, "a longitude is between -180 and 180")
    if body.parent_id and body.parent_id == body.id:
        raise HTTPException(400, "a jurisdiction cannot contain itself")
    bound = json.dumps(body.boundary) if body.boundary else ""
    args = (body.name.strip()[:120], body.level, body.parent_id,
            body.code.strip()[:80], body.lat, body.lng, body.population,
            int(body.watching), body.note.strip()[:2000])
    if body.id:
        if bound:
            con.execute("UPDATE jurisdictions SET boundary=? WHERE id=?",
                        (bound, body.id))
        con.execute(
            "UPDATE jurisdictions SET name=?, level=?, parent_id=?, code=?,"
            " lat=?, lng=?, population=?, watching=?, note=? WHERE id=?",
            args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO jurisdictions(name,level,parent_id,code,lat,lng,"
        " population,watching,note,boundary,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)", args + (bound, db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/civics/jurisdictions/{jid}")
def jurisdiction_delete(jid: int, user=Depends(current_user),
                        con=Depends(get_con)):
    _require(user)
    used = con.execute("SELECT COUNT(*) AS n FROM measures WHERE"
                       " jurisdiction_id=?", (jid,)).fetchone()["n"]
    if used:
        raise HTTPException(400, f"{used} measure(s) sit under it — move or "
                                 "close those first")
    con.execute("DELETE FROM jurisdictions WHERE id=?", (jid,))
    con.commit()
    return {"ok": True}


class MeasureBody(BaseModel):
    id: int = 0
    jurisdiction_id: int = 0
    ref: str = ""
    title: str
    summary: str = ""
    url: str = ""
    kind: str = "bill"
    status: str = "introduced"
    introduced_at: float = 0
    position: str = "watch"
    impact: str = "medium"
    why: str = ""
    owner_id: int = 0


@router.post("/api/civics/measures")
def measure_save(body: MeasureBody, user=Depends(current_user),
                 con=Depends(get_con)):
    _require(user)
    for field, allowed in (("status", STATUSES), ("position", POSITIONS),
                           ("impact", IMPACTS), ("kind", MEASURE_KINDS)):
        if getattr(body, field) not in allowed:
            raise HTTPException(400, f"{field} is one of {allowed}")
    if not body.title.strip():
        raise HTTPException(400, "a measure needs a title")
    now = time.time()
    args = (body.jurisdiction_id, body.ref.strip()[:60],
            body.title.strip()[:300], body.summary.strip()[:4000],
            body.url.strip()[:400], body.kind, body.status,
            body.introduced_at, body.position, body.impact,
            body.why.strip()[:2000], body.owner_id, now)
    if body.id:
        old = con.execute("SELECT status FROM measures WHERE id=?",
                          (body.id,)).fetchone()
        if old is None:
            raise HTTPException(404, "no such measure")
        con.execute(
            "UPDATE measures SET jurisdiction_id=?, ref=?, title=?, summary=?,"
            " url=?, kind=?, status=?, introduced_at=?, position=?, impact=?,"
            " why=?, owner_id=?, updated_at=? WHERE id=?", args + (body.id,))
        if old["status"] != body.status:
            con.execute(
                "INSERT INTO measure_events(measure_id,at,what,created_at)"
                " VALUES(?,?,?,?)",
                (body.id, now, f"{old['status']} → {body.status}, "
                 f"recorded by {user['name']}", db.now()))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO measures(jurisdiction_id,ref,title,summary,url,kind,"
        " status,introduced_at,position,impact,why,owner_id,updated_at,"
        " external_id,source,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'typed',?)",
        args + (f"typed:{int(now * 1000)}", db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.get("/api/civics/measures/{mid}")
def measure_detail(mid: int, user=Depends(current_user), con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "an office screen")
    r = con.execute("SELECT * FROM measures WHERE id=?", (mid,)).fetchone()
    if r is None:
        raise HTTPException(404, "no such measure")
    return {**shape_measure(con, r), "events": [dict(x) for x in con.execute(
        "SELECT * FROM measure_events WHERE measure_id=? ORDER BY at DESC",
        (mid,)).fetchall()]}


class EventBody(BaseModel):
    what: str
    at: float = 0


@router.post("/api/civics/measures/{mid}/events")
def measure_event(mid: int, body: EventBody, user=Depends(current_user),
                  con=Depends(get_con)):
    _require(user)
    if not body.what.strip():
        raise HTTPException(400, "say what happened")
    at = body.at or time.time()
    con.execute(
        "INSERT INTO measure_events(measure_id,at,what,created_at)"
        " VALUES(?,?,?,?)", (mid, at, body.what.strip()[:300], db.now()))
    con.execute("UPDATE measures SET last_action=?, last_action_at=?,"
                " updated_at=? WHERE id=?",
                (body.what.strip()[:300], at, time.time(), mid))
    con.commit()
    return {"ok": True}


class OfficialBody(BaseModel):
    id: int = 0
    jurisdiction_id: int = 0
    name: str
    office: str = ""
    party: str = ""
    district: str = ""
    email: str = ""
    phone: str = ""
    url: str = ""
    incumbent: bool = True
    note: str = ""


@router.post("/api/civics/officials")
def official_save(body: OfficialBody, user=Depends(current_user),
                  con=Depends(get_con)):
    _require(user)
    if not body.name.strip():
        raise HTTPException(400, "a person needs a name")
    args = (body.jurisdiction_id, body.name.strip()[:120],
            body.office.strip()[:160], body.party.strip()[:80],
            body.district.strip()[:80], body.email.strip()[:200],
            body.phone.strip()[:40], body.url.strip()[:400],
            int(body.incumbent), body.note.strip()[:2000])
    if body.id:
        con.execute(
            "UPDATE officials SET jurisdiction_id=?, name=?, office=?, party=?,"
            " district=?, email=?, phone=?, url=?, incumbent=?, note=?"
            " WHERE id=?", args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO officials(jurisdiction_id,name,office,party,district,"
        " email,phone,url,incumbent,note,external_id,source,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,'typed',?)",
        args + (f"typed:{int(time.time() * 1000)}", db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


class ElectionBody(BaseModel):
    id: int = 0
    jurisdiction_id: int = 0
    name: str
    kind: str = "general"
    at: float
    registration_deadline: float = 0
    url: str = ""
    note: str = ""


@router.post("/api/civics/elections")
def election_save(body: ElectionBody, user=Depends(current_user),
                  con=Depends(get_con)):
    _require(user)
    if body.kind not in ELECTION_KINDS:
        raise HTTPException(400, f"kind is one of {ELECTION_KINDS}")
    if not body.name.strip() or not body.at:
        raise HTTPException(400, "an election has a name and a date")
    if body.registration_deadline and body.registration_deadline > body.at:
        raise HTTPException(400, "registration closes before the election, "
                                 "not after it")
    args = (body.jurisdiction_id, body.name.strip()[:160], body.kind, body.at,
            body.registration_deadline, body.url.strip()[:400],
            body.note.strip()[:2000])
    if body.id:
        con.execute(
            "UPDATE elections SET jurisdiction_id=?, name=?, kind=?, at=?,"
            " registration_deadline=?, url=?, note=? WHERE id=?",
            args + (body.id,))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO elections(jurisdiction_id,name,kind,at,"
        " registration_deadline,url,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
        args + (db.now(),))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


class ContributionBody(BaseModel):
    id: int = 0
    jurisdiction_id: int = 0
    election_id: int = 0
    recipient: str
    recipient_kind: str = "committee"
    recipient_id: str = ""
    amount_cents: int
    at: float = 0
    method: str = ""
    authorised_by: str = ""
    disclosure_ref: str = ""
    note: str = ""


@router.post("/api/civics/contributions")
def contribution_save(body: ContributionBody, user=Depends(current_user),
                      con=Depends(get_con)):
    """Record a political contribution, for disclosure.

    Deliberately demanding: a recipient, an amount, a date and the person
    who authorised it. Those are the fields a filing asks for, and a
    register missing any of them is a register that cannot answer the
    question it exists for. Nothing here checks a limit or files
    anything — see the module docstring.
    """
    _require(user)
    if body.recipient_kind not in RECIPIENT_KINDS:
        raise HTTPException(400, f"recipient is one of {RECIPIENT_KINDS}")
    if not body.recipient.strip():
        raise HTTPException(400, "who received it")
    if body.amount_cents <= 0:
        raise HTTPException(400, "an amount above zero")
    if not body.authorised_by.strip():
        raise HTTPException(
            400, "who authorised it — a contribution nobody is recorded as "
                 "having approved is the one that becomes a problem later")
    at = body.at or time.time()
    if at > time.time() + 86400:
        raise HTTPException(400, "the register records what was given, not "
                                 "what will be")
    args = (body.jurisdiction_id, body.election_id, body.recipient.strip()[:200],
            body.recipient_kind, body.recipient_id.strip()[:80],
            body.amount_cents, at, body.method.strip()[:40],
            body.authorised_by.strip()[:120],
            body.disclosure_ref.strip()[:120], body.note.strip()[:2000])
    if body.id:
        con.execute(
            "UPDATE contributions SET jurisdiction_id=?, election_id=?,"
            " recipient=?, recipient_kind=?, recipient_id=?, amount_cents=?,"
            " at=?, method=?, authorised_by=?, disclosure_ref=?, note=?"
            " WHERE id=?", args + (body.id,))
        con.execute("UPDATE contributions SET disclosed_at=? WHERE id=? AND"
                    " disclosure_ref<>'' AND disclosed_at=0",
                    (time.time(), body.id))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO contributions(jurisdiction_id,election_id,recipient,"
        " recipient_kind,recipient_id,amount_cents,at,method,authorised_by,"
        " disclosure_ref,note,recorded_by,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        args + (user["name"], db.now()))
    con.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.get("/api/civics/contributions.csv")
def contributions_csv(user=Depends(current_user), con=Depends(get_con)):
    """The register as a file, because a disclosure is something somebody
    attaches to a form on a website this software has never heard of."""
    _require(user)
    import csv
    import io
    from fastapi.responses import Response
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "recipient", "kind", "recipient id", "jurisdiction",
                "amount", "method", "authorised by", "disclosure reference",
                "note"])
    for r in con.execute(
            "SELECT c.*, j.name AS jurisdiction FROM contributions c"
            " LEFT JOIN jurisdictions j ON j.id=c.jurisdiction_id"
            " ORDER BY c.at").fetchall():
        w.writerow([time.strftime("%Y-%m-%d", time.localtime(r["at"])),
                    r["recipient"], r["recipient_kind"], r["recipient_id"],
                    r["jurisdiction"] or "", f"{r['amount_cents'] / 100:.2f}",
                    r["method"], r["authorised_by"], r["disclosure_ref"],
                    r["note"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":
                             'attachment; filename="contributions.csv"'})


class PullBody(BaseModel):
    query: str = ""


@router.post("/api/civics/pull/{name}")
def civics_pull(name: str, body: PullBody, user=Depends(current_user),
                con=Depends(get_con)):
    _require(user)
    if name == "open_states":
        return pull_open_states(con, body.query)
    if name == "congress_gov":
        return pull_congress(con, body.query)
    if name == "google_civic":
        return pull_representatives(con)
    raise HTTPException(404, "no such source")
