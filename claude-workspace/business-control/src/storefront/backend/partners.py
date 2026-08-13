"""Partner funnels, events and the store locator.

Six audiences arrive at a beverage brand's site who are not shoppers, and
each one is worth more than a single order:

  work          — an office wants Zenjoy in the kitchen
  stock-zen     — a shop wants to carry Zenjoy
  reorder       — a shop that already carries it wants more
  distribute    — someone wants to distribute Zenjoy
  brand         — a brand wants Zenjoy's distribution arm to carry them
  partner-brand — a shop wants a Zenjoy-distributed brand on its shelf

They share one shape: a page that explains the path and a short form. So
there's one renderer driven by PATHS rather than six hand-built pages.

Enquiries land in `store_enquiries` and also open an `outreach` row, which is
the ERP's existing B2B pipeline — the sales rep's board picks them up without
anyone re-keying anything. That link is the whole point of the storefront and
the ERP being one system.
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from erp.backend import db
from . import sections as sect
from .api import (admin_user, get_con, rate_limit, render_shell, slugify)

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS store_enquiries (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                      -- PATHS key
  name TEXT NOT NULL,
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  company TEXT DEFAULT '',                 -- office / shop / brand name
  city TEXT DEFAULT '',
  region TEXT DEFAULT '',
  detail TEXT DEFAULT '',                  -- headcount, shelf space, volumes
  message TEXT DEFAULT '',
  status TEXT DEFAULT 'new',               -- new|contacted|closed
  outreach_id INTEGER DEFAULT 0,           -- the ERP pipeline row we opened
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS store_enquiries_time
  ON store_enquiries(created_at DESC);

CREATE TABLE IF NOT EXISTS store_events (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'tasting',             -- tasting|popup|market|class
  venue TEXT DEFAULT '',
  city TEXT DEFAULT '',
  region TEXT DEFAULT '',
  starts REAL NOT NULL,
  ends REAL DEFAULT 0,
  url TEXT DEFAULT '',
  body TEXT DEFAULT '',
  active INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS store_events_when ON store_events(starts);
"""

# kind -> page copy + which optional fields the form asks for.
PATHS = {
    "work": {
        "nav": "Zen at work",
        "title": "Zen at work",
        "kicker": "For workplaces",
        "lede": "The 3pm slump is a workplace design problem. Stock the "
                "kitchen with something that takes the edge off without "
                "taking the afternoon with it.",
        "points": [
            ("leaf", "200mg L-theanine, no crash",
             "Calm that doesn't cloud — people stay sharp through the "
             "afternoon instead of riding a caffeine spike into a trough."),
            ("truck", "Delivered on a schedule you set",
             "Weekly, fortnightly or monthly pallets and cases, billed to "
             "the company. Skip a week when the office is empty."),
            ("shield", "Nothing to administer",
             "One invoice, one contact, one delivery window. No per-person "
             "accounts and no app for your staff to install."),
        ],
        "detail_label": "How many people are in the office?",
        "detail_ph": "e.g. 40 across two floors",
        "company_label": "Company",
        "cta": "Ask about workplace supply",
    },
    "stock-zen": {
        "nav": "Stock Zenjoy",
        "title": "Get Zenjoy into your store",
        "kicker": "For retailers",
        "lede": "Cases of the five-flavour range, wholesale pricing, and a "
                "rep who actually answers. We start most shops on a mixed "
                "case so the shelf tells you what sells.",
        "points": [
            ("box", "Start with one mixed case",
             "Twelve cans across all five flavours. Low commitment, and the "
             "sell-through tells you which flavours your customers want."),
            ("truck", "Direct-store delivery in our regions",
             "Our own routes in covered regions, freight everywhere else. "
             "You get a delivery window, not a tracking number."),
            ("sparkle", "Merchandising that isn't cardboard junk",
             "Shelf strips and cooler clings in the flavour colours, free "
             "with your first three cases."),
        ],
        "detail_label": "What kind of store?",
        "detail_ph": "e.g. independent grocer, 2 locations",
        "company_label": "Store name",
        "cta": "Request wholesale pricing",
    },
    "reorder": {
        "nav": "Reorder for my store",
        "title": "Reorder for your store",
        "kicker": "For existing stockists",
        "lede": "Already carrying Zenjoy? Tell us what you're low on and "
                "we'll put it on the next run. If you have an account with "
                "us, sign in and your last order is one click away.",
        "points": [
            ("repeat", "Repeat your last order",
             "Sign in and reorder the same case mix, or adjust the flavour "
             "split before it ships."),
            ("clock", "Cut-off is Thursday 5pm",
             "Anything in by Thursday goes out on the following week's "
             "route for your region."),
            ("chat", "Or just tell your rep",
             "If you'd rather not use a form, message your rep in the chat "
             "and it lands in the same queue."),
        ],
        "detail_label": "What do you need?",
        "detail_ph": "e.g. 4 cases mixed, heavy on Yuzu",
        "company_label": "Store name",
        "cta": "Send reorder request",
    },
    "distribute": {
        "nav": "Distribute Zenjoy",
        "title": "Distribute Zenjoy",
        "kicker": "For distributors",
        "lede": "We're adding distribution partners region by region. If you "
                "run routes and know the accounts in your patch, there's "
                "margin here and we're not precious about territory.",
        "points": [
            ("truck", "Territory that's actually yours",
             "Defined regions with agreed accounts, not a free-for-all "
             "where we undercut you into your own shops."),
            ("box", "Pallet pricing, real margin",
             "Distributor pricing by volume band, with the band published "
             "up front rather than negotiated every quarter."),
            ("shield", "We carry the brand spend",
             "Sampling, events and merchandising in your territory are on "
             "us — you carry the trucks and the relationships."),
        ],
        "detail_label": "What do you currently distribute, and where?",
        "detail_ph": "e.g. 60 accounts across the Southeast, mostly grocery",
        "company_label": "Company",
        "cta": "Talk about distribution",
    },
    "brand": {
        "nav": "We'll distribute your brand",
        "title": "Have us distribute your brand",
        "kicker": "For brands",
        "lede": "Our routes have room. If you make something good and can't "
                "get it onto shelves, we'll carry it the way we carry our "
                "own — same trucks, same reps, same shelf conversations.",
        "points": [
            ("truck", "Onto our existing routes",
             "You get the accounts we already service, without building a "
             "field team or buying a van."),
            ("sparkle", "We only take what we'd drink",
             "A short list, carried properly, beats a catalogue nobody can "
             "sell. Expect us to actually taste it."),
            ("shield", "Your brand stays yours",
             "Distribution, not acquisition. No exclusivity on your DTC and "
             "no claim on your recipe."),
        ],
        "detail_label": "Tell us about the product",
        "detail_ph": "e.g. cold-brew tea, 4 SKUs, currently DTC only",
        "company_label": "Brand name",
        "cta": "Pitch us your brand",
    },
    "partner-brand": {
        "nav": "Stock a partner brand",
        "title": "Stock a brand we distribute",
        "kicker": "For retailers",
        "lede": "Zenjoy isn't the only thing on our trucks. If you already "
                "take a delivery from us — or want to — you can add any of "
                "the brands we carry to the same order and the same invoice.",
        "points": [
            ("box", "One delivery, one invoice",
             "Add partner brands to your existing Zenjoy order rather than "
             "opening another account with another distributor."),
            ("search", "Tell us the gap on your shelf",
             "Say what's missing and we'll tell you honestly whether "
             "anything we carry fills it."),
            ("truck", "Same route, same cut-off",
             "Partner brands ship on the run you're already on — no second "
             "delivery window to staff."),
        ],
        "detail_label": "Which brand, or what are you looking for?",
        "detail_ph": "e.g. a non-alc aperitif for the chiller",
        "company_label": "Store name",
        "cta": "Ask about partner brands",
    },
}


def init_tables(con):
    con.executescript(TABLES)
    if not con.execute("SELECT 1 FROM store_events").fetchone():
        now = time.time()
        day = 86400
        seed = [
            ("Tasting — Lakeview Pantry", "tasting", "Lakeview Pantry",
             "Chicago IL", "Midwest", now + 3 * day,
             "Try all five flavours. We'll be pouring 4–7pm, no ticket "
             "needed."),
            ("Zenjoy x Sunset Provisions pop-up", "popup",
             "Sunset Provisions", "Los Angeles CA", "West", now + 9 * day,
             "A weekend pop-up with the full range plus the Full Ripple "
             "pack at launch pricing."),
            ("Farmers market — Twin Cities", "market", "Mill City Market",
             "Minneapolis MN", "Midwest", now + 14 * day,
             "Find us near the north entrance. Cold cans, cash or card."),
            ("Afternoon reset workshop", "class", "Green Market Boston",
             "Boston MA", "Northeast", now + 21 * day,
             "Twenty minutes on why the 3pm slump happens and what actually "
             "helps. Free, and you get a can."),
        ]
        for name, kind, venue, city, region, starts, body in seed:
            con.execute(
                "INSERT INTO store_events(name,kind,venue,city,region,starts,"
                " body,active) VALUES(?,?,?,?,?,?,?,1)",
                (name, kind, venue, city, region, starts, body))


# ---------- public API ----------

class EnquiryBody(BaseModel):
    kind: str
    name: str
    email: str = ""
    phone: str = ""
    company: str = ""
    city: str = ""
    region: str = ""
    detail: str = ""
    message: str = ""


@router.post("/api/store/enquiry")
def create_enquiry(body: EnquiryBody, con=Depends(get_con),
                   _rl=Depends(rate_limit)):
    if body.kind not in PATHS:
        raise HTTPException(400, "unknown enquiry kind")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "a name is required")
    # Open a pipeline row so the enquiry appears on the sales board rather
    # than sitting in a table nobody opens. The company name is what a rep
    # recognises; fall back to the person's name for workplace enquiries.
    label = (body.company.strip() or name)[:80]
    cur = con.execute(
        "INSERT INTO outreach(name,region,city,stage,next_action,"
        " next_action_date,updated_at) VALUES(?,?,?,'lead',?,?,?)",
        (label, body.region.strip(), body.city.strip(),
         f"Follow up: {PATHS[body.kind]['nav']}",
         time.time() + 86400, time.time()))
    oid = cur.lastrowid
    con.execute(
        "INSERT INTO store_enquiries(kind,name,email,phone,company,city,"
        " region,detail,message,outreach_id,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (body.kind, name, body.email.strip(), body.phone.strip(),
         body.company.strip(), body.city.strip(), body.region.strip(),
         body.detail.strip(), body.message.strip(), oid, time.time()))
    con.commit()
    from .api import fire_webhooks
    fire_webhooks("enquiry.created", {"kind": body.kind, "company": label})
    return {"ok": True, "outreach_id": oid}


@router.get("/api/store/events")
def list_events(con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM store_events WHERE active=1 AND starts > ?"
        " ORDER BY starts LIMIT 60", (time.time() - 86400,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/store/locations")
def list_locations(con=Depends(get_con)):
    """Where to buy. Retail accounts only — a distributor DC is not somewhere
    a shopper can walk into."""
    rows = con.execute(
        "SELECT id, name, kind, region, city, lat, lng FROM stores"
        " WHERE active=1 AND kind='retail' ORDER BY region, city").fetchall()
    return [dict(r) for r in rows]


# ---------- admin ----------

@router.get("/api/store/admin/enquiries")
def admin_enquiries(limit: int = 100, u=Depends(admin_user),
                    con=Depends(get_con)):
    rows = con.execute(
        "SELECT * FROM store_enquiries ORDER BY created_at DESC LIMIT ?",
        (min(limit, 300),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["nav"] = PATHS.get(r["kind"], {}).get("nav", r["kind"])
        out.append(d)
    return out


# ---------- pages ----------

def _shell(con, body, title, desc):
    return HTMLResponse(render_shell(con, body, title=title, description=desc))


def _form(kind: str, spec: dict, regions) -> str:
    opts = "".join(f'<option value="{sect.esc(r)}">{sect.esc(r)}</option>'
                   for r in regions)
    return f"""
<form class="enq-form" id="enq-form" data-kind="{kind}">
 <div class="enq-row">
  <label>Your name<input name="name" required autocomplete="name"></label>
  <label>{sect.esc(spec['company_label'])}<input name="company"
    autocomplete="organization"></label>
 </div>
 <div class="enq-row">
  <label>Email<input name="email" type="email" autocomplete="email"></label>
  <label>Phone <span class="opt">optional</span><input name="phone"
    type="tel" autocomplete="tel"></label>
 </div>
 <div class="enq-row">
  <label>City<input name="city" autocomplete="address-level2"></label>
  <label>Region<select name="region"><option value="">Choose…</option>
    {opts}</select></label>
 </div>
 <label>{sect.esc(spec['detail_label'])}
  <input name="detail" placeholder="{sect.esc(spec['detail_ph'])}"></label>
 <label>Anything else <span class="opt">optional</span>
  <textarea name="message" rows="3"></textarea></label>
 <button class="btn-pill primary" type="submit">{sect.esc(spec['cta'])}</button>
 <p class="enq-msg" id="enq-msg" role="status"></p>
</form>"""


@router.get("/partners/{kind}")
def partner_page(kind: str, request: Request, con=Depends(get_con)):
    spec = PATHS.get(kind)
    if spec is None:
        raise HTTPException(404, "no such page")
    from erp.backend.main import CFG
    regions = CFG.get("regions") or []
    points = "".join(
        f'<div class="story-card"><span class="ico-wrap">'
        f'{sect.icon(i, "ico ico-lg")}</span><b>{sect.esc(t)}</b>'
        f'<p>{sect.esc(b)}</p></div>' for i, t, b in spec["points"])
    others = "".join(
        f'<a class="side-item" href="/partners/{k}">{sect.esc(v["nav"])}</a>'
        for k, v in PATHS.items() if k != kind)
    body = f"""
<section class="section partner-head">
 <span class="eyebrow">{sect.esc(spec['kicker'])}</span>
 <h1>{sect.esc(spec['title'])}</h1>
 <p class="lede">{sect.esc(spec['lede'])}</p>
</section>
<section class="section"><div class="story-grid">{points}</div></section>
<section class="section">
 <div class="enq-wrap">
  <div>
   <h2>Tell us a bit and we'll come back to you</h2>
   <p class="dim">A person reads these. Expect a reply within two working
    days — sooner if you're in a region we already run routes in.</p>
   {_form(kind, spec, regions)}
  </div>
 </div>
</section>
<section class="section">
 <span class="eyebrow">Other ways to work with us</span>
 <div class="menu-cols" style="margin-top:12px">{others}</div>
</section>"""
    return _shell(con, body, f"{spec['title']} — Zenjoy", spec["lede"][:155])


@router.get("/events")
def events_page(request: Request, con=Depends(get_con)):
    body = """
<section class="section partner-head">
 <span class="eyebrow">Come say hello</span>
 <h1>Events</h1>
 <p class="lede">Tastings, pop-ups and markets. Everything here is free to
  turn up to — bring someone who needs an afternoon off.</p>
</section>
<section class="section">
 <div class="collection-tabs" id="event-filters"
   role="group" aria-label="Filter events by region"></div>
 <div class="event-list" id="event-list"></div>
</section>"""
    return _shell(con, body, "Events — Zenjoy",
                  "Zenjoy tastings, pop-ups and markets near you.")


@router.get("/find")
def locator_page(request: Request, con=Depends(get_con)):
    body = """
<section class="section partner-head">
 <span class="eyebrow">Store locator</span>
 <h1>Find Zenjoy near you</h1>
 <p class="lede">Shops that carry the range. Stock varies by store — if
  you're after a specific flavour it's worth a call first.</p>
</section>
<section class="section">
 <div class="locator-bar">
  <span class="search-wrap">
   <svg class="ico" aria-hidden="true"><use href="#i-search"/></svg>
   <input id="loc-search" type="search" placeholder="City or store"
     aria-label="Search stores">
  </span>
  <button class="btn-pill ghost sm" id="loc-near">
   <svg class="ico ico-sm" aria-hidden="true"><use href="#i-pin"/></svg>
   Use my location</button>
 </div>
 <div class="collection-tabs" id="loc-filters"
   role="group" aria-label="Filter stores by region"></div>
 <div class="loc-list" id="loc-list"></div>
 <p class="dim" id="loc-empty" hidden>No stores match that yet — we're
  adding accounts every week. <a class="text-link"
  href="/partners/stock-zen">Ask your local shop to stock us.</a></p>
</section>"""
    return _shell(con, body, "Find Zenjoy near you",
                  "Store locator — shops that carry Zenjoy.")
