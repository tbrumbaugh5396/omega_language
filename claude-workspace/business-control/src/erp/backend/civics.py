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

On the map: Leaflet, vendored, over OpenStreetMap tiles when the machine
is online and a bundled outline of every country when it is not. The
outline shows every country and the register holds only the watched
ones, so the map stays a map and the register stays a register. A watched
place with no boundary of its own is a pin where somebody said it is.
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

/* Something two or more jurisdictions agreed. A trade pact, a defence
   treaty, membership of a body. Not a jurisdiction: it has parties rather
   than a parent, and a country can be inside fifty of them at once. */
CREATE TABLE IF NOT EXISTS agreements (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'treaty',              -- see AGREEMENT_KINDS
  summary TEXT DEFAULT '',
  url TEXT DEFAULT '',
  signed_at REAL DEFAULT 0,
  in_force_at REAL DEFAULT 0,
  ends_at REAL DEFAULT 0,                  -- 0 = open ended
  status TEXT DEFAULT 'in_force',          -- proposed|signed|in_force|suspended|ended
  position TEXT DEFAULT 'watch',           -- what WE think of it
  impact TEXT DEFAULT 'medium',
  why TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agreement_parties (
  agreement_id INTEGER NOT NULL,
  jurisdiction_id INTEGER NOT NULL,
  role TEXT DEFAULT 'party',               -- party|member|observer|signatory
  since REAL DEFAULT 0,
  PRIMARY KEY (agreement_id, jurisdiction_id)
);
CREATE INDEX IF NOT EXISTS agreement_parties_j ON agreement_parties(jurisdiction_id);
"""

MIGRATIONS = [
    # ISO code lets a watched country be matched to the map's own outline.
    "ALTER TABLE jurisdictions ADD COLUMN iso TEXT DEFAULT ''",
    # The Census layer a row came from, by the geocoder's own name for it
    # ("119th Congressional Districts"), so the boundary is fetched from
    # the SAME vintage that placed the address rather than the newest one.
    "ALTER TABLE jurisdictions ADD COLUMN census_layer TEXT DEFAULT ''",
    # An event that changed a measure's stage records the stage it led to,
    # so "what was this bill's status on the 3rd of March" is answerable by
    # replaying its events up to that date rather than guessed from prose.
    "ALTER TABLE measure_events ADD COLUMN status_after TEXT DEFAULT ''",
]

# In order from the top of the stack to the bottom. A bloc is a treaty
# organisation or an alliance — the EU, NATO, a trade pact — which is a
# jurisdiction in the only sense that matters here: it can change a rule
# that reaches you. An HOA is the bottom of the same stack, and for a shop
# in a managed development it is the level that decides the signage.
LEVELS = {
    "bloc": "Treaty bloc or alliance",
    "country": "Country",
    "state": "State or province",
    "county": "County",
    "district": "Congressional or legislative district",
    "city": "City or municipality",
    "school": "School district",
    "ward": "Ward or precinct",
    "hoa": "Homeowners' or neighbourhood association",
    "other": "Other",
}
LEVEL_ORDER = list(LEVELS)
# Treaties and agreements are not jurisdictions; they are things
# jurisdictions have agreed with each other, and a country can be party
# to fifty of them. So they are rows of their own, linked to their parties.
AGREEMENT_KINDS = {
    "treaty": "Treaty",
    "trade": "Trade or economic agreement",
    "defense": "Defence or security agreement",
    "membership": "Membership of a body",
    "tax": "Tax or investment treaty",
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
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:                                    # noqa: BLE001
            pass
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
        " watching, iso FROM jurisdictions ORDER BY level, name").fetchall()]
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


IG.CHECKS["open_states"] = _check_open_states
IG.CHECKS["congress_gov"] = _check_congress


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
                    " status_after,created_at) VALUES(?,?,?,?,?,?)",
                    (have["id"], last_at, last[:300], source, status, db.now()))
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
            "INSERT INTO measure_events(measure_id,at,what,source,status_after,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (cur.lastrowid, last_at, last[:300], source, status, db.now()))
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


CENSUS = ("https://geocoding.geo.census.gov/geocoder/geographies/"
          "onelineaddress")


def _layer(geos: dict, *needles: str):
    """The Census names its layers by vintage — '119th Congressional
    Districts', '2024 State Legislative Districts - Upper' — so a layer is
    found by what it means, not by its exact name, and the parser survives
    the next census and the next redistricting. Returns (layer name, row):
    the name is kept, because the boundary later comes from the layer of
    the same name and vintage."""
    for key, rows in geos.items():
        k = key.lower()
        if all(n.lower() in k for n in needles) and rows:
            return key, rows[0]
    return None


def find_jurisdictions(con, address: str) -> dict:
    """The stack an address sits in, from the US Census Bureau's geocoder.

    No key, no account, nothing to connect: it is an official public
    service and it answers the question this whole screen starts with.
    It knows state, county, city, congressional district, both state
    legislative chambers and the school district, each with the FIPS code
    that every other US dataset joins on, and it gives back the point.
    What it does not know is who holds any of those offices — that is
    Open States and Congress.gov, keyed, and they start from this.

    US only, because it is the US census. An address elsewhere gets a
    plain answer rather than a guess.
    """
    address = (address or "").strip()
    if not address:
        raise HTTPException(400, "an address to look up — the business's "
                                 "own, usually")
    q = urllib.parse.urlencode({"address": address,
                                "benchmark": "Public_AR_Current",
                                "vintage": "Current_Current",
                                "layers": "all", "format": "json"})
    ok, d = IG._req(f"{CENSUS}?{q}", timeout=25)
    if not ok:
        raise HTTPException(400, f"the Census geocoder said: {d}")
    matches = ((d.get("result") or {}).get("addressMatches") or []) \
        if isinstance(d, dict) else []
    if not matches:
        raise HTTPException(
            404, "the Census geocoder could not place that address. It "
                 "covers the United States only, and wants a street, city "
                 "and state — a business name or a postcode alone is not "
                 "enough for it")
    m = matches[0]
    lat = float((m.get("coordinates") or {}).get("y") or 0)
    lng = float((m.get("coordinates") or {}).get("x") or 0)
    geos = m.get("geographies") or {}

    def put(level, hit, parent_id, name=None):
        if hit is None:
            return 0
        layer_name, row = hit
        nm = (name or row.get("NAME") or row.get("BASENAME") or "").strip()
        code = f"census:{row.get('GEOID', '')}"
        have = con.execute("SELECT id FROM jurisdictions WHERE code=?",
                           (code,)).fetchone()
        if have:
            con.execute("UPDATE jurisdictions SET watching=1, census_layer=?,"
                        " parent_id=CASE WHEN parent_id=0 THEN ? ELSE parent_id"
                        " END WHERE id=?", (layer_name, parent_id, have["id"]))
            return have["id"]
        cur = con.execute(
            "INSERT INTO jurisdictions(name,level,parent_id,code,lat,lng,"
            " watching,census_layer,created_at) VALUES(?,?,?,?,?,?,1,?,?)",
            (nm[:120], level, parent_id, code, lat, lng, layer_name, db.now()))
        return cur.lastrowid

    us = con.execute("SELECT id FROM jurisdictions WHERE level='country' AND"
                     " (iso='US' OR code='iso:US')").fetchone()
    if us:
        us_id = us["id"]
    else:
        us_id = con.execute(
            "INSERT INTO jurisdictions(name,level,code,iso,lat,lng,watching,"
            " created_at) VALUES('United States','country','iso:US','US',"
            " 39.8, -98.6, 1, ?)", (db.now(),)).lastrowid
    state = put("state", _layer(geos, "States"), us_id)
    county = put("county", _layer(geos, "Counties"), state)
    city = put("city", _layer(geos, "Incorporated Places"), county or state)
    cd = put("district", _layer(geos, "Congressional"), state)
    upper = put("district", _layer(geos, "Legislative Districts", "Upper"), state)
    lower = put("district", _layer(geos, "Legislative Districts", "Lower"), state)
    school = put("school", _layer(geos, "School Districts"), county or state)
    con.commit()
    found = [x for x in (us_id, state, county, city, cd, upper, lower, school) if x]
    IG.log(con, "census", "find_jurisdictions", True,
           f"{len(found)} for {m.get('matchedAddress', address)[:80]}")
    drawn = fill_boundaries(con, found)
    return {"ok": True, "matched": m.get("matchedAddress", ""),
            "boundaries": drawn,
            "lat": lat, "lng": lng, "jurisdictions": found,
            "state_fips": ((_layer(geos, "States") or ("", {}))[1]).get("GEOID", ""),
            "district": ((_layer(geos, "Congressional") or ("", {}))[1]).get("BASENAME", "")}


TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
# Which TIGERweb map service holds each kind of layer. The layer ID inside
# a service is NOT fixed — the same "Counties" appears once per vintage,
# and the ids shuffle when a vintage is added — so ids are resolved by
# name at call time and cached for the life of the process.
TIGER_SERVICES = ("State_County", "Legislative",
                  "Places_CouSub_ConCity_SubMCD", "School")
_TIGER_LAYERS: dict = {}
# How much a boundary may be simplified, in degrees. Two thousandths is
# about two hundred metres, which is invisible at any zoom a county or a
# district is looked at and turns a forty-thousand-point coastline into a
# few hundred.
TIGER_OFFSET = 0.002


def _tiger_layers(service: str) -> list:
    if service in _TIGER_LAYERS:
        return _TIGER_LAYERS[service]
    ok, d = IG._req(f"{TIGERWEB}/{service}/MapServer?f=json", timeout=20)
    layers = [(l.get("id"), l.get("name", "")) for l in
              (d.get("layers") or [])] if ok and isinstance(d, dict) else []
    _TIGER_LAYERS[service] = layers
    return layers


def _tiger_layer_for(census_layer: str, level: str) -> tuple:
    """(service, layer id) for a jurisdiction. The geocoder's own layer
    name is tried first, so a district placed by the 119th Congress's
    map is drawn from the 119th Congress's map, not the 120th's; then
    the newest layer whose name means the same thing."""
    wants = {"state": ("State_County", ("States",)),
             "county": ("State_County", ("Counties",)),
             "city": ("Places_CouSub_ConCity_SubMCD", ("Incorporated Places",)),
             "school": ("School", ("Unified",)),
             "district": ("Legislative", ())}
    if level not in wants:
        return "", None
    service, needles = wants[level]
    if level == "district":
        cl = census_layer.lower()
        needles = (("Congressional",) if "congress" in cl
                   else ("Legislative", "Upper") if "upper" in cl
                   else ("Legislative", "Lower") if "lower" in cl
                   else ("Congressional",))
    layers = _tiger_layers(service)
    for lid, name in layers:
        if name == census_layer:
            return service, lid
    for lid, name in layers:
        if all(n.lower() in name.lower() for n in needles):
            return service, lid
    return service, None


def fetch_boundary(con, jid: int) -> dict:
    """The outline of one jurisdiction, from the Census's own map service,
    stored on the row. Keyless, like the geocoder; the shapes are the
    TIGER/Line files, served one feature at a time so an install holds
    the counties it watches rather than all three thousand."""
    j = con.execute("SELECT * FROM jurisdictions WHERE id=?", (jid,)).fetchone()
    if j is None:
        raise HTTPException(404, "no such jurisdiction")
    if not (j["code"] or "").startswith("census:"):
        raise HTTPException(400, "only a place the Census placed has a "
                                 "Census outline — this one was typed, so "
                                 "paste a boundary on it instead")
    geoid = j["code"].split(":", 1)[1]
    service, lid = _tiger_layer_for(j["census_layer"] or "", j["level"])
    if lid is None:
        raise HTTPException(400, f"TIGERweb has no layer for a {j['level']}")
    q = urllib.parse.urlencode({
        "where": f"GEOID='{geoid}'", "outFields": "GEOID,NAME",
        "f": "geojson", "outSR": "4326",
        "maxAllowableOffset": TIGER_OFFSET, "geometryPrecision": "3"})
    ok, d = IG._req(f"{TIGERWEB}/{service}/MapServer/{lid}/query?{q}",
                    timeout=40)
    if not ok:
        raise HTTPException(400, f"TIGERweb said: {d}")
    feats = (d.get("features") or []) if isinstance(d, dict) else []
    if not feats or not feats[0].get("geometry"):
        raise HTTPException(404, f"TIGERweb has no outline for GEOID {geoid} "
                                 f"in {service}")
    geom = feats[0]["geometry"]
    con.execute("UPDATE jurisdictions SET boundary=? WHERE id=?",
                (json.dumps(geom, separators=(",", ":")), jid))
    con.commit()
    n = sum(len(r) for poly in (geom["coordinates"]
                                if geom["type"] == "MultiPolygon"
                                else [geom["coordinates"]]) for r in poly)
    return {"ok": True, "id": jid, "points": n, "type": geom["type"]}


def fill_boundaries(con, ids: list | None = None) -> dict:
    """Every Census-placed jurisdiction that has no outline yet. Each is
    its own request and its own failure: a county TIGERweb cannot find
    must not stop the state behind it."""
    rows = con.execute(
        "SELECT id FROM jurisdictions WHERE code LIKE 'census:%' AND"
        " (boundary='' OR boundary IS NULL)" +
        (" AND id IN (" + ",".join("?" * len(ids)) + ")" if ids else ""),
        tuple(ids) if ids else ()).fetchall()
    done, failed = [], []
    for r in rows:
        try:
            done.append(fetch_boundary(con, r["id"])["id"])
        except HTTPException as e:
            failed.append({"id": r["id"], "why": str(e.detail)})
        except Exception as e:                               # noqa: BLE001
            failed.append({"id": r["id"], "why": str(e)[:200]})
    if done or failed:
        IG.log(con, "census", "boundaries", not failed,
               f"{len(done)} drawn" + (f", {len(failed)} not" if failed else ""))
    return {"drawn": done, "failed": failed}


def _state_code(fips: str) -> str:
    codes = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
             "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
             "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
             "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
             "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
             "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
             "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
             "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
             "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
             "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
             "56": "WY", "72": "PR"}
    return codes.get(str(fips)[:2], "")


def _upsert_official(con, *, source, ext, jid, name, office, party="",
                     district="", email="", phone="", url="") -> bool:
    have = con.execute("SELECT id FROM officials WHERE source=? AND"
                       " external_id=?", (source, ext)).fetchone()
    args = (jid, name[:120], office[:160], (party or "")[:80],
            (district or "")[:80], (email or "")[:200], (phone or "")[:40],
            (url or "")[:400])
    if have:
        con.execute("UPDATE officials SET jurisdiction_id=?, name=?, office=?,"
                    " party=?, district=?, email=?, phone=?, url=?, incumbent=1"
                    " WHERE id=?", args + (have["id"],))
        return False
    con.execute("INSERT INTO officials(jurisdiction_id,name,office,party,"
                " district,email,phone,url,external_id,source,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)", args + (ext, source, db.now()))
    return True


def pull_state_legislators(con, lat: float, lng: float) -> dict:
    """Who sits for this point in the state legislature, from Open States.
    Needs its key; starts from the point the Census gave back."""
    c = IG.creds(con, "open_states")
    if not c:
        raise HTTPException(400, "connect Open States first")
    ok, d = IG._req(f"https://v3.openstates.org/people.geo?lat={lat}&lng={lng}",
                    headers={"X-API-Key": c.get("api_key", "")})
    if not ok:
        IG.log(con, "open_states", "pull_representatives", False, str(d)[:200])
        raise HTTPException(400, f"Open States said: {d}")
    new = 0
    for per in (d.get("results") or []) if isinstance(d, dict) else []:
        role = per.get("current_role") or {}
        jur = per.get("jurisdiction") or {}
        jid = _jurisdiction_by_name(con, jur.get("name", "") or "state", "state") \
            if jur.get("name") else 0
        chamber = {"upper": "Senate", "lower": "House"}.get(
            role.get("org_classification", ""), role.get("org_classification", ""))
        if _upsert_official(
                con, source="open_states", ext=str(per.get("id")), jid=jid,
                name=per.get("name", ""),
                office=f"State {chamber}, district {role.get('district', '')}".strip(),
                party=per.get("party", ""), district=str(role.get("district", "")),
                email=per.get("email", ""), url=per.get("openstates_url", "")):
            new += 1
    con.commit()
    IG.log(con, "open_states", "pull_representatives", True, f"{new} new")
    return {"ok": True, "new": new}


def pull_federal_members(con, state_code: str, district: str) -> dict:
    """The two senators and the representative, from Congress.gov."""
    c = IG.creds(con, "congress_gov")
    if not c:
        raise HTTPException(400, "connect Congress.gov first")
    if not state_code:
        raise HTTPException(400, "find the jurisdictions first — the state "
                                 "comes from the address")
    key = urllib.parse.quote(c.get("api_key", ""))
    ok, d = IG._req(f"https://api.congress.gov/v3/member/{state_code}"
                    f"?currentMember=true&limit=250&format=json&api_key={key}")
    if not ok:
        IG.log(con, "congress_gov", "pull_representatives", False, str(d)[:200])
        raise HTTPException(400, f"Congress.gov said: {d}")
    us = con.execute("SELECT id FROM jurisdictions WHERE level='country' AND"
                     " (iso='US' OR code='iso:US')").fetchone()
    us_id = us["id"] if us else 0
    want = str(district or "").strip().lstrip("0")
    new = 0
    for mem in (d.get("members") or []) if isinstance(d, dict) else []:
        dist = str(mem.get("district") or "").strip().lstrip("0")
        terms = ((mem.get("terms") or {}).get("item") or [])
        chamber = (terms[-1].get("chamber") if terms else "") or ""
        senator = "Senate" in chamber or not dist
        if not senator and want and dist != want:
            continue
        if _upsert_official(
                con, source="congress_gov", ext=str(mem.get("bioguideId")),
                jid=us_id, name=mem.get("name", ""),
                office=("US Senator" if senator
                        else f"US Representative, district {dist}"),
                party=mem.get("partyName", ""), district=dist,
                url=mem.get("url", "")):
            new += 1
    con.commit()
    IG.log(con, "congress_gov", "pull_representatives", True, f"{new} new")
    return {"ok": True, "new": new}


# ---------- the picture around one jurisdiction ----------

def ancestors(con, jid: int) -> list:
    out, seen = [], set()
    cur = con.execute("SELECT parent_id FROM jurisdictions WHERE id=?",
                      (jid,)).fetchone()
    pid = cur["parent_id"] if cur else 0
    while pid and pid not in seen:
        seen.add(pid)
        r = con.execute("SELECT id, name, level, parent_id FROM jurisdictions"
                        " WHERE id=?", (pid,)).fetchone()
        if r is None:
            break
        out.append({"id": r["id"], "name": r["name"], "level": r["level"]})
        pid = r["parent_id"]
    out.reverse()
    return out


def descendants(con, jid: int) -> list:
    """Every jurisdiction inside this one, however deep. A state's law
    reaches the county and the county's ordinance reaches the city, so the
    timeline of a place is the timeline of everything above it and, for
    a place looked at from above, everything within it."""
    out, frontier, seen = [], [jid], {jid}
    while frontier:
        rows = con.execute(
            "SELECT id FROM jurisdictions WHERE parent_id IN ("
            + ",".join("?" * len(frontier)) + ")", frontier).fetchall()
        frontier = [r["id"] for r in rows if r["id"] not in seen]
        seen.update(frontier)
        out.extend(frontier)
    return out


def status_as_of(con, measure, at: float | None) -> str:
    """The stage a measure was at on a date, replayed from its events.
    Without a date, the stage it is at now. With a date before it was
    introduced, nothing — it did not exist."""
    if at is None:
        return measure["status"]
    if measure["introduced_at"] and measure["introduced_at"] > at:
        return ""
    rows = con.execute(
        "SELECT status_after FROM measure_events WHERE measure_id=? AND at<=?"
        " AND status_after<>'' ORDER BY at DESC, id DESC LIMIT 1",
        (measure["id"], at)).fetchall()
    if rows:
        return rows[0]["status_after"]
    first = con.execute(
        "SELECT MIN(at) AS at FROM measure_events WHERE measure_id=?"
        " AND status_after<>''", (measure["id"],)).fetchone()
    # Nothing recorded on or before this date. With no introduced date,
    # the earliest event is the earliest the register knows it existed,
    # so before that it is not shown. A row with no history at all —
    # older than the history — is at the stage it is at now.
    return "" if first and first["at"] else measure["status"]


def timeline(con, jid: int = 0, since: float = 0, until: float = 0) -> dict:
    """Everything dated, for a place and the places that reach it.

    Scope is the whole point. With nothing selected it is the world. With
    a county selected it is the county's own events, the state's and the
    country's above it — a state law applies to the county, so it belongs
    on the county's timeline — and everything inside it, marked as
    inside. Each event says which of those it is, so a reader can tell
    "our city did this" from "this reached us from above".
    """
    own = {jid} if jid else set()
    above = {a["id"] for a in ancestors(con, jid)} if jid else set()
    below = set(descendants(con, jid)) if jid else set()
    scope_of = (lambda j: "own" if j in own else "inherited" if j in above
                else "inside" if j in below else "") if jid else (lambda j: "world")
    ids = own | above | below
    where = ""
    args: list = []
    if jid:
        where = " AND j IN (" + ",".join("?" * len(ids)) + ")"
        args = list(ids)
    ev = []
    jnames = {r["id"]: (r["name"], r["level"]) for r in con.execute(
        "SELECT id, name, level FROM jurisdictions").fetchall()}

    def add(at, kind, what, j, ref_kind, ref_id, detail_="", status=""):
        if not at or (since and at < since) or (until and at > until):
            return
        sc = scope_of(j)
        if not sc:
            return
        nm, lv = jnames.get(j, ("", ""))
        ev.append({"at": at, "kind": kind, "what": what, "jurisdiction_id": j,
                   "jurisdiction": nm, "level": lv, "scope": sc,
                   "ref_kind": ref_kind, "ref_id": ref_id, "detail": detail_,
                   "status": status})

    for m in con.execute("SELECT * FROM measures").fetchall():
        evs = con.execute("SELECT * FROM measure_events WHERE measure_id=?",
                          (m["id"],)).fetchall()
        if m["introduced_at"] and not any(e["at"] == m["introduced_at"] for e in evs):
            add(m["introduced_at"], "measure", f"{m['ref']} {m['title']}".strip(),
                m["jurisdiction_id"], "measure", m["id"], "introduced", "introduced")
        for e in evs:
            add(e["at"], "measure", f"{m['ref']} {m['title']}".strip(),
                m["jurisdiction_id"], "measure", m["id"], e["what"],
                e["status_after"])
    for e in con.execute("SELECT * FROM elections").fetchall():
        add(e["at"], "election", e["name"], e["jurisdiction_id"], "election",
            e["id"], e["kind"])
    for a in con.execute("SELECT * FROM agreements").fetchall():
        parties = [r["jurisdiction_id"] for r in con.execute(
            "SELECT jurisdiction_id FROM agreement_parties WHERE agreement_id=?",
            (a["id"],)).fetchall()]
        for pj in parties:
            add(a["signed_at"], "agreement", a["name"], pj, "agreement", a["id"], "signed")
            add(a["in_force_at"], "agreement", a["name"], pj, "agreement", a["id"], "in force")
            add(a["ends_at"], "agreement", a["name"], pj, "agreement", a["id"], "ended")
    for o in con.execute("SELECT * FROM officials").fetchall():
        add(o["term_start"], "official", o["name"], o["jurisdiction_id"], "official",
            o["id"], f"took office: {o['office']}")
        add(o["term_end"], "official", o["name"], o["jurisdiction_id"], "official",
            o["id"], f"term ends: {o['office']}")
    for g in con.execute("SELECT * FROM contributions").fetchall():
        add(g["at"], "giving", g["recipient"], g["jurisdiction_id"], "contribution",
            g["id"], f"{g['amount_cents'] / 100:,.2f} given")
    ev.sort(key=lambda x: x["at"])
    # Each event is one row here but a jurisdiction can appear under
    # several agreements; that is intended — a treaty between three
    # countries is an event in each of their histories.
    span = {"min": ev[0]["at"] if ev else 0, "max": ev[-1]["at"] if ev else 0}
    return {"events": ev, "span": span, "scope": jid,
            "counts": {k: sum(1 for e in ev if e["scope"] == k)
                       for k in ("own", "inherited", "inside", "world")}}


def detail(con, jid: int, as_of: float | None = None) -> dict:
    """Everything the register knows about one place, for the panel that
    opens when it is clicked. The whole point of the map: a country is a
    door to its treaties, a city to its ordinances, an HOA to its rules.

    With `as_of`, the place as it was on that date: the officials whose
    terms covered it, the agreements in force then, each measure at the
    stage it had reached, elections still ahead of it. What the register
    cannot do is redraw the map — a county's boundary is its boundary
    now, and a jurisdiction that did not yet exist is still drawn."""
    j = con.execute("SELECT * FROM jurisdictions WHERE id=?", (jid,)).fetchone()
    if j is None:
        raise HTTPException(404, "no such jurisdiction")
    t = as_of
    kids = [dict(r) for r in con.execute(
        "SELECT id, name, level, watching FROM jurisdictions WHERE parent_id=?"
        " ORDER BY level, name", (jid,)).fetchall()]
    agreements = [dict(r) for r in con.execute(
        "SELECT a.*, p.role, p.since FROM agreements a"
        " JOIN agreement_parties p ON p.agreement_id=a.id"
        " WHERE p.jurisdiction_id=? ORDER BY a.kind, a.name", (jid,)).fetchall()]
    for a in agreements:
        a["kind_label"] = AGREEMENT_KINDS.get(a["kind"], a["kind"])
        a["parties"] = [dict(r) for r in con.execute(
            "SELECT j.id, j.name, j.level, p.role FROM agreement_parties p"
            " JOIN jurisdictions j ON j.id=p.jurisdiction_id"
            " WHERE p.agreement_id=? ORDER BY j.name", (a["id"],)).fetchall()]
    if t is not None:
        agreements = [a for a in agreements
                      if (not a["signed_at"] or a["signed_at"] <= t)
                      and (not a["ends_at"] or a["ends_at"] > t)]
        for a in agreements:
            a["status_then"] = ("in force" if a["in_force_at"] and a["in_force_at"] <= t
                                else "signed" if a["signed_at"] else a["status"])
    if t is None:
        officials = [dict(r) for r in con.execute(
            "SELECT * FROM officials WHERE jurisdiction_id=? AND incumbent=1"
            " ORDER BY office, name", (jid,)).fetchall()]
    else:
        officials = [dict(r) for r in con.execute(
            "SELECT * FROM officials WHERE jurisdiction_id=?"
            " AND (term_start=0 OR term_start<=?)"
            " AND (term_end=0 OR term_end>?)"
            " ORDER BY office, name", (jid, t, t)).fetchall()]
    measures = []
    for r in con.execute(
            "SELECT * FROM measures WHERE jurisdiction_id=?"
            " ORDER BY (status NOT IN ('enacted','failed','vetoed','withdrawn'))"
            " DESC, last_action_at DESC LIMIT 50", (jid,)).fetchall():
        st = status_as_of(con, r, t)
        if t is not None and not st:
            continue
        m = shape_measure(con, r)
        m["status"] = st
        m["closed"] = st in ("enacted", "failed", "vetoed", "withdrawn")
        measures.append(m)
    now_ = t if t is not None else time.time()
    return {
        **dict(j), "level_label": LEVELS.get(j["level"], j["level"]),
        "as_of": t,
        "ancestors": ancestors(con, jid), "children": kids,
        "agreements": agreements,
        "officials": officials,
        "measures": measures,
        "elections": [dict(r) for r in con.execute(
            "SELECT * FROM elections WHERE jurisdiction_id=? AND at>?"
            " ORDER BY at LIMIT 20", (jid, now_ - 30 * 86400)).fetchall()],
        "given_cents": con.execute(
            "SELECT COALESCE(SUM(amount_cents),0) AS c FROM contributions"
            " WHERE jurisdiction_id=?", (jid,)).fetchone()["c"],
    }


def watch_country(con, iso: str, name: str, lat: float, lng: float) -> int:
    """A country from the map's own outline layer becomes a row in the
    register. The map can show every country; the register holds only the
    ones this business is watching, or it is a gazetteer nobody reads."""
    iso = (iso or "").upper()[:3]
    have = con.execute("SELECT id FROM jurisdictions WHERE level='country' AND"
                       " (iso=? OR lower(name)=lower(?))", (iso, name)).fetchone()
    if have:
        con.execute("UPDATE jurisdictions SET watching=1, iso=CASE WHEN iso=''"
                    " THEN ? ELSE iso END WHERE id=?", (iso, have["id"]))
        con.commit()
        return have["id"]
    cur = con.execute(
        "INSERT INTO jurisdictions(name,level,code,iso,lat,lng,watching,"
        " created_at) VALUES(?,'country',?,?,?,?,1,?)",
        (name[:120], f"iso:{iso}" if iso else "", iso, lat, lng, db.now()))
    con.commit()
    return cur.lastrowid


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
        "agreements": [dict(r) for r in con.execute(
            "SELECT a.*, (SELECT COUNT(*) FROM agreement_parties p"
            " WHERE p.agreement_id=a.id) AS parties FROM agreements a"
            " ORDER BY a.kind, a.name LIMIT 200").fetchall()],
        "agreement_kinds": [{"k": k, "label": v}
                            for k, v in AGREEMENT_KINDS.items()],
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
                "INSERT INTO measure_events(measure_id,at,what,status_after,"
                " created_at) VALUES(?,?,?,?,?)",
                (body.id, now, f"{old['status']} → {body.status}, "
                 f"recorded by {user['name']}", body.status, db.now()))
        con.commit()
        return {"ok": True, "id": body.id}
    cur = con.execute(
        "INSERT INTO measures(jurisdiction_id,ref,title,summary,url,kind,"
        " status,introduced_at,position,impact,why,owner_id,updated_at,"
        " external_id,source,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'typed',?)",
        args + (f"typed:{int(now * 1000)}", db.now()))
    # The first event is the stage it was recorded at, dated when it was
    # introduced if that is known. A slider replays the past from events,
    # and a measure with no first event has no past to replay.
    con.execute(
        "INSERT INTO measure_events(measure_id,at,what,status_after,created_at)"
        " VALUES(?,?,?,?,?)",
        (cur.lastrowid, body.introduced_at or now,
         f"recorded as {body.status} by {user['name']}", body.status, db.now()))
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
    status: str = ""          # the stage this event moved it to, if any


@router.post("/api/civics/measures/{mid}/events")
def measure_event(mid: int, body: EventBody, user=Depends(current_user),
                  con=Depends(get_con)):
    _require(user)
    if not body.what.strip():
        raise HTTPException(400, "say what happened")
    at = body.at or time.time()
    if body.status and body.status not in STATUSES:
        raise HTTPException(400, f"status is one of {STATUSES}")
    con.execute(
        "INSERT INTO measure_events(measure_id,at,what,status_after,created_at)"
        " VALUES(?,?,?,?,?)",
        (mid, at, body.what.strip()[:300], body.status, db.now()))
    con.execute("UPDATE measures SET last_action=?, last_action_at=?,"
                " updated_at=? WHERE id=?",
                (body.what.strip()[:300], at, time.time(), mid))
    if body.status:
        con.execute("UPDATE measures SET status=? WHERE id=?", (body.status, mid))
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
    raise HTTPException(404, "no such source")


class FindBody(BaseModel):
    address: str


@router.post("/api/civics/find")
def civics_find(body: FindBody, user=Depends(current_user),
                con=Depends(get_con)):
    """The stack an address sits in. Keyless: the Census geocoder is an
    official public service, so there is nothing to connect first."""
    _require(user)
    return find_jurisdictions(con, body.address)


@router.post("/api/civics/boundaries")
def civics_boundaries(user=Depends(current_user), con=Depends(get_con)):
    """Draw every Census-placed jurisdiction that has no outline yet."""
    _require(user)
    return fill_boundaries(con)


@router.post("/api/civics/jurisdictions/{jid}/boundary")
def civics_boundary(jid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    return fetch_boundary(con, jid)


class RepsBody(BaseModel):
    lat: float
    lng: float
    state_fips: str = ""
    district: str = ""


@router.post("/api/civics/representatives")
def civics_representatives(body: RepsBody, user=Depends(current_user),
                           con=Depends(get_con)):
    """Who holds the offices, from whichever keyed sources are connected.
    Each is tried; each reports; neither failing stops the other."""
    _require(user)
    out = {"state": None, "federal": None}
    try:
        out["state"] = pull_state_legislators(con, body.lat, body.lng)
    except HTTPException as e:
        out["state"] = {"ok": False, "why": str(e.detail)}
    try:
        out["federal"] = pull_federal_members(
            con, _state_code(body.state_fips), body.district)
    except HTTPException as e:
        out["federal"] = {"ok": False, "why": str(e.detail)}
    return out


@router.get("/api/civics/jurisdictions/{jid}/detail")
def civics_detail(jid: int, as_of: float = 0, user=Depends(current_user),
                  con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "an office screen")
    return detail(con, jid, as_of or None)


def federal_elections(first_year: int, last_year: int) -> list:
    """US federal general elections: the Tuesday after the first Monday
    in November of every even year, by law since 1845. Computed, not
    fetched — the one part of the calendar that needs no source and never
    changes. Presidential every fourth year from 1788, midterm otherwise."""
    import calendar as _cal
    out = []
    for y in range(first_year, last_year + 1):
        if y % 2:
            continue
        first_monday = next(d for d in range(1, 8) if _cal.weekday(y, 11, d) == 0)
        day = first_monday + 1
        at = time.mktime((y, 11, day, 7, 0, 0, 0, 0, -1))
        pres = (y - 1788) % 4 == 0
        out.append({"year": y, "at": at,
                    "name": f"{y} {'presidential' if pres else 'midterm'} general election",
                    "kind": "general",
                    "note": ("President, all 435 House seats, a third of the Senate"
                             if pres else "All 435 House seats, a third of the Senate")})
    return out


class SeedBody(BaseModel):
    years_back: int = 10
    years_ahead: int = 6


@router.post("/api/civics/seed/federal-elections")
def seed_federal_elections(body: SeedBody, user=Depends(current_user),
                           con=Depends(get_con)):
    """Put the federal calendar on the United States' timeline: the past
    elections and the coming ones. Keyless. Adds only what is not there."""
    _require(user)
    us = con.execute("SELECT id FROM jurisdictions WHERE level='country'"
                     " AND (iso='US' OR name='United States')"
                     " ORDER BY (iso='US') DESC, id LIMIT 1").fetchone()
    if us is None:
        raise HTTPException(400, "watch the United States first — the "
                                 "outline on the map offers it")
    y = time.localtime().tm_year
    added = 0
    for e in federal_elections(y - max(0, min(body.years_back, 60)),
                               y + max(0, min(body.years_ahead, 20))):
        if con.execute("SELECT 1 FROM elections WHERE jurisdiction_id=? AND name=?",
                       (us["id"], e["name"])).fetchone():
            continue
        con.execute(
            "INSERT INTO elections(jurisdiction_id,name,kind,at,registration_deadline,"
            " url,note,created_at) VALUES(?,?,?,?,0,'',?,?)",
            (us["id"], e["name"], e["kind"], e["at"], e["note"], db.now()))
        added += 1
    con.commit()
    return {"ok": True, "added": added, "jurisdiction_id": us["id"]}


@router.get("/api/civics/timeline")
def civics_timeline(jurisdiction_id: int = 0, since: float = 0,
                    until: float = 0, user=Depends(current_user),
                    con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "an office screen")
    if jurisdiction_id and con.execute(
            "SELECT 1 FROM jurisdictions WHERE id=?",
            (jurisdiction_id,)).fetchone() is None:
        raise HTTPException(404, "no such jurisdiction")
    return timeline(con, jurisdiction_id, since, until)


class WatchBody(BaseModel):
    iso: str = ""
    name: str
    lat: float
    lng: float


@router.post("/api/civics/watch")
def civics_watch(body: WatchBody, user=Depends(current_user),
                 con=Depends(get_con)):
    _require(user)
    if not body.name.strip():
        raise HTTPException(400, "a country has a name")
    return {"ok": True, "id": watch_country(con, body.iso, body.name.strip(),
                                            body.lat, body.lng)}


class AgreementBody(BaseModel):
    id: int = 0
    name: str
    kind: str = "treaty"
    summary: str = ""
    url: str = ""
    signed_at: float = 0
    in_force_at: float = 0
    ends_at: float = 0
    status: str = "in_force"
    position: str = "watch"
    impact: str = "medium"
    why: str = ""
    note: str = ""
    parties: list = []          # [{jurisdiction_id, role}]


AGREEMENT_STATUSES = ("proposed", "signed", "in_force", "suspended", "ended")


@router.post("/api/civics/agreements")
def agreement_save(body: AgreementBody, user=Depends(current_user),
                   con=Depends(get_con)):
    _require(user)
    if body.kind not in AGREEMENT_KINDS:
        raise HTTPException(400, f"kind is one of {sorted(AGREEMENT_KINDS)}")
    if body.status not in AGREEMENT_STATUSES:
        raise HTTPException(400, f"status is one of {AGREEMENT_STATUSES}")
    if body.position not in POSITIONS or body.impact not in IMPACTS:
        raise HTTPException(400, "position and impact are from the lists")
    if not body.name.strip():
        raise HTTPException(400, "an agreement needs a name")
    parties = []
    for pt in body.parties or []:
        jid = int(pt.get("jurisdiction_id") or 0)
        if jid and con.execute("SELECT 1 FROM jurisdictions WHERE id=?",
                               (jid,)).fetchone():
            parties.append((jid, str(pt.get("role") or "party")[:20]))
    if len({j for j, _ in parties}) < 2 and not body.id:
        raise HTTPException(400, "an agreement is between at least two "
                                 "jurisdictions — add the parties to it")
    now = time.time()
    args = (body.name.strip()[:200], body.kind, body.summary.strip()[:4000],
            body.url.strip()[:400], body.signed_at, body.in_force_at,
            body.ends_at, body.status, body.position, body.impact,
            body.why.strip()[:2000], body.note.strip()[:2000], now)
    if body.id:
        if con.execute("SELECT 1 FROM agreements WHERE id=?",
                       (body.id,)).fetchone() is None:
            raise HTTPException(404, "no such agreement")
        con.execute(
            "UPDATE agreements SET name=?, kind=?, summary=?, url=?, signed_at=?,"
            " in_force_at=?, ends_at=?, status=?, position=?, impact=?, why=?,"
            " note=?, updated_at=? WHERE id=?", args + (body.id,))
        aid = body.id
        if parties:
            con.execute("DELETE FROM agreement_parties WHERE agreement_id=?",
                        (aid,))
    else:
        cur = con.execute(
            "INSERT INTO agreements(name,kind,summary,url,signed_at,in_force_at,"
            " ends_at,status,position,impact,why,note,updated_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", args + (db.now(),))
        aid = cur.lastrowid
    for jid, role in parties:
        con.execute("INSERT OR IGNORE INTO agreement_parties(agreement_id,"
                    " jurisdiction_id,role) VALUES(?,?,?)", (aid, jid, role))
    con.commit()
    return {"ok": True, "id": aid}


@router.get("/api/civics/agreements/{aid}")
def agreement_detail(aid: int, user=Depends(current_user), con=Depends(get_con)):
    if not _may_see(user):
        raise HTTPException(403, "an office screen")
    a = con.execute("SELECT * FROM agreements WHERE id=?", (aid,)).fetchone()
    if a is None:
        raise HTTPException(404, "no such agreement")
    return {**dict(a), "kind_label": AGREEMENT_KINDS.get(a["kind"], a["kind"]),
            "parties": [dict(r) for r in con.execute(
                "SELECT j.id, j.name, j.level, p.role, p.since"
                " FROM agreement_parties p JOIN jurisdictions j"
                " ON j.id=p.jurisdiction_id WHERE p.agreement_id=?"
                " ORDER BY j.name", (aid,)).fetchall()]}


@router.delete("/api/civics/agreements/{aid}")
def agreement_delete(aid: int, user=Depends(current_user), con=Depends(get_con)):
    _require(user)
    con.execute("DELETE FROM agreement_parties WHERE agreement_id=?", (aid,))
    con.execute("DELETE FROM agreements WHERE id=?", (aid,))
    con.commit()
    return {"ok": True}
