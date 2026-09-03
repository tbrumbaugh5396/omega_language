"""Business Control's own storefront — the studio tenant's shop.

The split gave ZenJoy the shop and the studio the pipeline, which left the
studio's storefront showing the section engine's factory defaults: a drinks
hero, a can, and somebody else's flavours. This builds the studio a
storefront of its own — theme, plans, capability menu, pages and nav.

Everything with a price in it is read from docs/product/price-book.md
through storefront.backend.pricebook. Nothing here retypes a number. Change
the book, re-run this, and the shop agrees with the quote bench, the deck
and the client menu because all four are reading one table.

Usage: python scripts/seed_studio.py [--tenant studio] [--force]

--force replaces the home page's sections and re-prices the plans. Without
it, the script refuses once the shop has products, so it cannot quietly
overwrite copy an operator has since edited by hand.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from erp.backend import tenancy  # noqa: E402
from storefront.backend import pricebook as pb  # noqa: E402

# --- the brand ------------------------------------------------------------
# Neither ZenJoy's palette nor the neutral default: a studio that sells an
# operations platform should not look like it sells a soft drink.
THEME = {
    "brand": "business control", "dot": ".",
    "title": "Business Control — one install, the whole business",
    "description": "Storefront, operations and admin in one system, priced "
                   "from a published book. Built for businesses that have "
                   "outgrown five subscriptions that do not talk to each "
                   "other.",
    "purple": "#4634d9", "lavender": "#8b7cf0", "orange": "#ff6a3d",
    "ink": "#15131c", "bg": "#f7f6f3",
    # The ops app's wordmark is a plain bold sans; the storefront should
    # not introduce a second, rounder version of the same name.
    "font": "Inter", "display_font": "Fraunces", "wordmark_font": "Inter",
    "announce": ["One install — storefront, operations and admin",
                 "Every price on this site is in the published price book"],
    "footer": "© 2026 Business Control · this site runs on the product",
    "art": "card",
}

# Colour says what a thing IS, not which rung it sits on. Tinting the
# three plans apart from each other made Pro green and Care green — two
# different answers in the same colour — so the kind's colour is the only
# one now, and the price tells the rungs apart.


def esc(v) -> str:
    import html
    return html.escape(str(v or ""))


# --- the capability menu, drawn from the book ------------------------------

def menu_html() -> str:
    """The 28 capabilities, grouped, banded and priced. This is the piece
    of the site that does the selling: a buyer who can see the whole menu
    and add it up is a buyer who does not need to ask for a call first."""
    bands = pb.bands()
    rows = []
    for g in pb.groups():
        rows.append(
            f'<tr class="grp"><th colspan="3">{esc(g["name"])}'
            f'<span>{esc(g["note"])}</span></th></tr>')
        for c in g["items"]:
            rows.append(
                f'<tr><td>{esc(c["name"])}</td>'
                f'<td class="band band-{c["band"]}">{esc(c["band"])}</td>'
                f'<td class="p">${c["price"]}</td></tr>')
    band_line = " · ".join(f"{k.title()} ${v}" for k, v in bands.items())
    return f"""
<div class="capmenu">
  <p class="capnote">Pick what the business actually does. Everything rests
    on <b>Platform Core, ${pb.core_price()}</b>, and a capability selects
    what it depends on. Three bands, not twenty-seven guesses:
    {esc(band_line)} a month.</p>
  <table class="captable">{"".join(rows)}</table>
  <p class="capnote">Volume discount applies from four capabilities. Worked
    examples, seat and location limits, metered add-ons and the nonprofit
    rate are all in the price book — ask and we will send it.</p>
</div>"""


def bundle_html() -> str:
    """Worked examples. A price nobody can reproduce is a price nobody
    trusts, so show the arithmetic rather than a 'from'."""
    rows = "".join(
        f'<tr><td>{esc(b["name"])}</td><td>{b["count"]}</td>'
        f'<td>${b["sum"]}</td><td>{esc(b["volume"])}</td>'
        f'<td>{esc(b["other"])}</td>'
        f'<td class="p">${b["monthly"]:.2f}</td></tr>'
        for b in pb.bundles())
    return f"""
<div class="capmenu">
  <table class="captable bundles">
   <tr><th>Business</th><th>Capabilities</th><th>Sum</th><th>Volume</th>
       <th>Other</th><th>Monthly</th></tr>{rows}</table>
  <p class="capnote">Platform only. Support and maintenance is the second
    half of the bill and is quoted separately — one number for two different
    businesses is how a support plan quietly becomes free.</p>
</div>"""


def care_html() -> str:
    cols = pb.care_plans()
    head = "".join(f"<th>{esc(c['name'])}<span>${c['price']}/mo</span></th>"
                   for c in cols)
    def row(label, key):
        return (f"<tr><td>{esc(label)}</td>"
                + "".join(f"<td>{esc(c[key] or '—')}</td>" for c in cols)
                + "</tr>")
    return f"""
<div class="capmenu">
  <table class="captable care"><tr><th>Support &amp; maintenance</th>{head}</tr>
   {row("First response", "response")}
   {row("Defect targets", "defects")}
   {row("Updates applied", "updates")}
   {row("Key journeys watched", "monitoring")}
   {row("Content changes included", "included")}
  </table>
  <p class="capnote">Every plan includes managed hosting, nightly off-site
    backups, a restore tested and dated, and critical security patches
    within 24 hours any day of the week. Three schedules travel with the
    agreement and say exactly what each line means.</p>
</div>"""


def build_html() -> str:
    rows = "".join(
        f'<tr><td>{esc(b["name"])}</td><td class="p">${b["price"]:,}</td></tr>'
        for b in pb.builds())
    return f"""
<div class="capmenu">
  <table class="captable builds"><tr><th>Getting started</th><th>One-time</th>
   </tr>{rows}</table>
  <p class="capnote">Optionally split by surface — storefront, admin, ops,
    migration — which is how the work divides and how scope arguments are
    avoided. Guided setup is buyable above; the rest start with a
    conversation and a written quote.</p>
</div>"""


CAP_CSS = """
.capmenu{max-width:900px;margin:0 auto}
.captable{width:100%;border-collapse:collapse;font-size:15px;margin:18px 0}
.captable td,.captable th{padding:9px 12px;text-align:left;
  border-bottom:1px solid rgba(27,24,31,.10)}
.captable tr.grp th{padding-top:22px;font-family:var(--display),serif;
  font-size:19px;border-bottom:2px solid var(--ink)}
.captable tr.grp th span{display:block;font-family:var(--ui);font-size:13px;
  font-weight:400;opacity:.62;margin-top:2px}
.captable td.p{text-align:right;font-variant-numeric:tabular-nums;
  font-weight:600;white-space:nowrap}
.captable .band{font-size:12px;text-transform:uppercase;letter-spacing:.06em;
  opacity:.72}
.captable .band-heavy{color:var(--orange);opacity:1}
.captable th span{display:block;font-weight:400;font-size:13px;opacity:.7}
.captable.care td:not(:first-child),.captable.bundles td:not(:first-child){
  text-align:center}
.captable.bundles td.p,.captable.builds td.p{text-align:right}
.capnote{font-size:14px;opacity:.75;line-height:1.6;max-width:70ch}
@media(max-width:640px){.captable{font-size:13.5px}
  .captable td,.captable th{padding:7px 6px}}
"""


# --- sections -------------------------------------------------------------

def home_sections() -> list:
    tiers = pb.tiers()
    caps = pb.capabilities()
    return [
        ("hero", {
            "heading": "Run the whole business\nfrom one install.",
            "sub": "Your storefront, your operations and your admin on one "
                   "database — so an order, the stock behind it and the "
                   "person who packs it are the same fact, not three "
                   "systems agreeing on a good day.",
            "cta_text": "See what it costs", "cta_link": "/#shop",
            "cta2_text": "Talk to us", "cta2_link": "/partners/build",
            "layout": "split", "show_product": True,
            "stat1": f"{len(caps)}|capabilities, priced individually",
            "stat2": "3|surfaces, one login",
            "stat3": f"${tiers[0]['price']}|a month to start",
            "bg": "gradient", "media_id": "",
        }),
        ("benefits", {"items": [
            {"icon": "shield", "value": "24h",
             "label": "critical patches, any day"},
            {"icon": "check", "value": "Nightly",
             "label": "off-site backups, restore tested"},
            {"icon": "truck", "value": "One", "label": "bill, two halves"},
            {"icon": "sparkle", "value": "Yours",
             "label": "data, exportable, always"},
        ]}),
        ("feature_columns", {
            "heading": "Why one system rather than five",
            "items": [
                {"icon": "check", "title": "The join is free",
                 "text": "Stock, orders, staff hours and the customer record "
                         "sit in one database. Nobody reconciles anything at "
                         "the end of the month, because there is nothing to "
                         "reconcile."},
                {"icon": "columns", "title": "You buy what you do",
                 "text": "Capabilities are priced one at a time and depend on "
                         "each other honestly. A shop that does not ship "
                         "pallets does not pay for distribution."},
                {"icon": "shield", "title": "The price is written down",
                 "text": "Every figure on this site comes out of a published "
                         "price book. Ask for it and you get the same "
                         "document we quote from, including what is still "
                         "unresolved in it."},
            ]}),
        ("product_grid", {
            "heading": "Plans", "collection_id": "", "limit": 0,
            "show_search": False, "show_tabs": True}),
        ("rich_text", {
            "heading": "What the monthly bill is made of",
            # Paragraphs are blank lines; the renderer wraps them. Tags
            # are for emphasis inside one, not for structure.
            "body": "Two parts, and they are two different businesses. "
                    "<b>Part one is the platform</b> — the capabilities you "
                    "picked, plus Platform Core, less the volume discount. "
                    "<b>Part two is support and maintenance</b> — the care "
                    "plan, which is people rather than software and takes "
                    "no discounts.\n\n"
                    "A packaged plan is part one bought as one number. It "
                    "is priced <i>above</i> the equivalent menu at a single "
                    "location: it buys headroom, not a discount. We quote "
                    "both and quote the cheaper one.",
            "align": "left"}),
        ("custom_html", {"html": menu_html(), "css": CAP_CSS, "js": "",
                         "liquid": ""}),
        ("custom_html", {"html": care_html(), "css": "", "js": "",
                         "liquid": ""}),
        ("faq", {
            "heading": "The questions everybody asks",
            "items": [
                {"q": "Can we start small and add later?",
                 "a": "Yes — that is what the menu is for. Capabilities are "
                      "added and removed monthly; the volume discount "
                      "recalculates on its own."},
                {"q": "Who owns the data?",
                 "a": "You do. Your install has its own database, its own "
                      "uploads and its own keys — nothing is shared with "
                      "another business. Export it whenever you want, and if "
                      "you leave we retire your data rather than deleting "
                      "it, because the week after a cancellation is exactly "
                      "when someone asks for a copy."},
                {"q": "Do you host it, or do we?",
                 "a": "We host it by default, on a node we manage, with SSL "
                      "issued and renewed automatically. Self-hosting is "
                      "possible and changes the care plan, not the "
                      "platform."},
                {"q": "What happens when something breaks?",
                 "a": "One tracked route with a reference number, defect "
                      "targets in writing, and monitoring that calls us "
                      "before it calls you. The response times differ by "
                      "care plan and are in the table above."},
                {"q": "Can you build the rest of it?",
                 "a": "Yes. Builds run as a documented engagement — "
                      "discovery, quote, design, build, launch, aftercare — "
                      "with a gate at each stage and paperwork you sign "
                      "rather than a status meeting."},
            ]}),
        ("newsletter", {
            "heading": "Want the price book?",
            "body": "The whole thing — bands, capabilities, discounts, cost "
                    "to serve and the list of what is still contradictory in "
                    "it. Leave an address and we will send it.",
            "cta_text": "Send it over"}),
    ]


def pricing_sections() -> list:
    return [
        ("rich_text", {
            "heading": "Pricing, in full",
            "body": "Two parts to the monthly bill, one one-time build, "
                    "and no figure on this page that is not in the price "
                    "book. Where the book still disagrees with itself, it "
                    "says so — and so do we.",
            "align": "left"}),
        ("custom_html", {"html": menu_html(), "css": CAP_CSS, "js": "",
                         "liquid": ""}),
        ("rich_text", {
            "heading": "Worked examples",
            "body": "Real selections, added up. If one of these looks "
                    "wrong, the band assignment is wrong — not the "
                    "arithmetic.", "align": "left"}),
        ("custom_html", {"html": bundle_html(), "css": "", "js": "",
                         "liquid": ""}),
        ("custom_html", {"html": care_html(), "css": "", "js": "",
                         "liquid": ""}),
        ("custom_html", {"html": build_html(), "css": "", "js": "",
                         "liquid": ""}),
    ]


def process_sections() -> list:
    stages = [
        ("Discovery", "We learn the business before pricing it — what is "
                      "sold, who does what, and which of the five systems "
                      "you are on is actually load-bearing."),
        ("Quote", "A written quote off the price book, capability by "
                  "capability, with the packaged plan priced beside it so "
                  "you can see which is cheaper."),
        ("Design", "The surfaces you will actually use, agreed before "
                   "anybody writes code: storefront, admin, ops."),
        ("Build", "In stages, each with a gate. Nothing moves on until the "
                  "paperwork for the last stage is signed."),
        ("Launch", "Migration, a rehearsal, then the switch — with the old "
                   "system still standing until you say otherwise."),
        ("Aftercare", "The care plan starts. Monitoring, patches, backups, "
                      "defects to target, and a monthly report you did not "
                      "have to ask for."),
    ]
    items = "".join(
        f'<li><b>{esc(n)}</b><span>{esc(d)}</span></li>' for n, d in stages)
    return [
        ("rich_text", {
            "heading": "How a build runs",
            "body": "Six stages, each with a gate and a document. The "
                    "point of the gates is that neither side can be "
                    "surprised later: everything agreed is written down, "
                    "signed, and filed where you can see it.",
            "align": "left"}),
        ("custom_html", {
            "html": f'<ol class="stagelist">{items}</ol>',
            "css": """
.stagelist{max-width:760px;margin:0 auto;padding:0;list-style:none;
  counter-reset:s}
.stagelist li{counter-increment:s;position:relative;padding:16px 0 16px 58px;
  border-bottom:1px solid rgba(27,24,31,.10)}
.stagelist li::before{content:counter(s);position:absolute;left:0;top:16px;
  width:34px;height:34px;border-radius:50%;background:var(--purple);
  color:#fff;display:grid;place-items:center;font-weight:700;font-size:15px}
.stagelist b{display:block;font-family:var(--display),serif;font-size:20px}
.stagelist span{display:block;opacity:.75;line-height:1.6;margin-top:3px}
""", "js": "", "liquid": ""}),
    ]


# --- products -------------------------------------------------------------

def _cap_ids() -> list:
    """Capability ids with their names — the same map the ERP prices
    grants from, so a bundle names its capabilities the way every other
    surface does."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from storefront.backend.engagements import _cap_catalog
    return _cap_catalog()


def products() -> list:
    """What is buyable. The plans and the care plans, priced from the book;
    the bigger builds are quoted, because pretending a $40,000 engagement is
    an add-to-cart is the kind of lie a shop never recovers from."""
    out = []
    for t in pb.tiers():
        covers = t["capabilities"]
        lead = ("Everything in the plan below, plus " if t["adds"] else "")
        out.append({
            "sku": f"PLAN-{t['name'].upper()}", "name": f"{t['name']} plan",
            "billing": "month", "kind": "plan",
            "category": "Plans", "price_cents": t["price"] * 100,
            "description":
                f"{t['locations']} location(s), {t['seats']} staff seats, "
                f"{t['email']} emails a month. {lead}{covers}. Billed "
                f"monthly, cancel monthly. Support and maintenance is "
                f"quoted separately.",
        })
    # The worked examples, buyable. Each is a real capability set at a
    # price the book already computes — the count, the sum, the volume
    # discount and the nonprofit cut are all in §13. A shop that shows
    # them in a table and cannot sell them is a menu with no waiter.
    cap_by_id = {c["id"]: c for c in _cap_ids()}
    for b in pb.bundles():
        names = [cap_by_id[i]["name"] for i in b["cap_ids"] if i in cap_by_id]
        out.append({
            "sku": "BUNDLE-" + b["name"].upper().replace(" + ", "-")
                   .replace(" ", "-")[:16],
            "name": b["name"], "kind": "bundle", "billing": "month",
            "category": "Bundles",
            "price_cents": int(round(b["monthly"] * 100)),
            "caps": ",".join(b["cap_ids"]),
            "description":
                f"{b['count']} capabilities for a business shaped like "
                f"this one: {', '.join(names)}. "
                f"${b['sum']} at the menu, {b['volume']} for taking "
                f"{b['count']} of them"
                + (f", {b['other']}" if b["other"] not in ("—", "-", "")
                   else "")
                + f" — ${b['monthly']:,.2f} a month. Support and "
                  f"maintenance is the second half of the bill.",
        })
    # A group of the menu, taken whole. The book already groups the 29
    # into five departments; each one priced by the same rule as a bundle
    # is a real thing to sell, and the cheapest honest way to say "we do
    # your back office" without listing eight lines.
    prices = {c["id"]: c["price"] for c in cap_by_id.values()}
    for g in pb.groups():
        ids = [i["id"] for i in cap_by_id.values()
               if i["name"] in {x["name"] for x in g["items"]}]
        if not ids:
            continue
        q = pb.price_selection(ids, prices)
        out.append({
            "sku": "PACK-" + g["name"].upper().replace(" & ", "-")
                   .replace(" ", "-")[:16],
            "name": g["name"] + " pack", "kind": "pack", "billing": "month",
            "category": "Capability packs",
            "price_cents": int(round(q["monthly"] * 100)),
            "caps": ",".join(ids),
            "description":
                f"{g['note'] or g['name']} — all {q['count']} of them: "
                + ", ".join(cap_by_id[i]["name"] for i in ids)
                + f". ${q['sum']} at the menu"
                + (f", {int(q['volume_rate'] * 100)}% off for taking "
                   f"{q['count']}" if q["volume_rate"] else "")
                + f", plus Platform Core ${q['core']}. Build a different "
                  f"set at /plan-builder.",
        })
    for c in pb.care_plans():
        out.append({
            "sku": f"CARE-{c['name'].upper()}", "name": f"{c['name']} care",
            "billing": "month", "kind": "care",
            "category": "Care", "price_cents": c["price"] * 100,
            "description":
                f"First response {c['response'].lower()}, defects to "
                f"{c['defects']}, updates {c['updates'].lower()}. Managed "
                f"hosting, nightly off-site backups and critical patches "
                f"within 24 hours are in every plan. "
                + (f"Includes {c['included']} of content changes a month."
                   if c["included"] not in ("—", "") else
                   "No included content-change hours."),
        })
    # ONE one-time ladder, every rung of it. Guided setup is the way in
    # and is bought outright; the rest are banded, because the shape of
    # that work is known before the scope is — so the shop shows where a
    # rung starts and the quote lands inside the band after discovery.
    SKU = {"Guided setup": "BUILD-GUIDED", "Week website": "BUILD-WEEK",
           "Custom build": "BUILD-CUSTOM",
           "Custom build + Branding & creative": "BUILD-CUSTOMBRAND",
           "Branding & creative": "BUILD-BRANDING"}
    for b in pb.builds():
        setup = b["name"] == "Guided setup"
        brand = b["name"] == "Branding & creative"
        band = b["ceiling"] > b["price"]
        out.append({
            "sku": SKU[b["name"]], "name": b["name"],
            "kind": "setup" if setup else "brand" if brand else "build",
            "category": "Setups" if setup
                        else "Branding" if brand else "Builds",
            "price_cents": b["price"] * 100, "quote": band,
            "description":
                f"{b['what']}. {b['timeline']}"
                + (f", {b['revisions']}" if b["revisions"] != "-" else "")
                + (f". Priced ${b['price']:,}-${b['ceiling']:,} — the band "
                   f"is the honest answer before discovery; the quote "
                   f"lands inside it." if band else "."),
        })
    # Taking our name off it is a licence, not a fork, and it is sold.
    for w in pb.white_label():
        if not w["price"]:
            continue                      # 'None' is the default, not a sale
        out.append({
            "sku": f"WL-{w['name'].split()[0].upper()}",
            "name": f"White-label — {w['name']}", "billing": "month",
            "kind": "label",
            "category": "White-labelling", "price_cents": w["price"] * 100,
            "description": w["gets"].rstrip(".") + "."
            + (f" One-time setup ${w['setup']:,}." if w["setup"] else ""),
        })
    return out



# --- ways to work with us -------------------------------------------------
# The shipped partner pages are a drinks brand's. These are ours: the four
# conversations that actually start an engagement. Each one opens a lead on
# the sales board through the same enquiry rail.
PARTNER_PAGES = {
    "build": {
        "nav": "Build it with us",
        "title": "Build it with us",
        "kicker": "For a business ready to move",
        "lede": "You know what the business does. We know what it takes to "
                "run it on one system. A build starts with discovery and a "
                "written quote off the published price book — not an "
                "estimate, and not a call you have to chase.",
        "points": [
            ["check", "A quote you can check",
             "Every capability priced from the book, the packaged plan "
             "priced beside it, and the cheaper of the two is the one we "
             "put in front of you."],
            ["columns", "Stages with gates",
             "Discovery, design, build, launch, aftercare. Each stage has "
             "paperwork you sign before the next one starts, so nobody is "
             "surprised in month four."],
            ["shield", "Your data, from day one",
             "Your own database, your own keys, exports whenever you want "
             "them. If you leave, your records are retired rather than "
             "deleted."],
        ],
        "detail_label": "What are you running the business on today?",
        "detail_ph": "e.g. Shopify, a spreadsheet, and a lot of texting",
        "company_label": "Business",
        "cta": "Start a conversation",
    },
    "migrate": {
        "nav": "Move off the stack",
        "title": "Move off the stack you have",
        "kicker": "For businesses paying five subscriptions",
        "lede": "A storefront here, inventory there, staff hours in a third "
                "thing, and a spreadsheet holding it together. Migration is "
                "the work, and it is work we have done — with the old system "
                "still standing until you say otherwise.",
        "points": [
            ["truck", "Your data comes with you",
             "Products, customers, orders, stock and staff. We import what "
             "exists, show you the differences, and fix them before "
             "anything goes live."],
            ["check", "Rehearsed before it is real",
             "A full dress rehearsal on your actual data. The switch is the "
             "boring part, which is the point."],
            ["shield", "Nothing is turned off for you",
             "The old stack stays up until you decide otherwise. We have no "
             "interest in a cutover you cannot walk back."],
        ],
        "detail_label": "What are you moving off?",
        "detail_ph": "e.g. Shopify + Katana + Gusto",
        "company_label": "Business",
        "cta": "Ask about migrating",
    },
    "white-label": {
        "nav": "Resell it",
        "title": "Put your name on it",
        "kicker": "For agencies and consultants",
        "lede": "You have the clients and the relationship. We have the "
                "platform and the operations behind it. White-labelling runs "
                "at four levels, from our name in the footer to none of it "
                "anywhere.",
        "points": [
            ["columns", "Your brand, our platform",
             "Your logo, your domain, your invoices. The product behaves "
             "the same either way — the licence is what changes."],
            ["check", "Priced from the same book",
             "You buy at the platform price and price your clients "
             "yourself. Nothing about the arrangement is a negotiation "
             "each time."],
            ["shield", "We do not talk to your clients",
             "Unless you want us to. Support routes through you by default, "
             "and the escalation path is written down."],
        ],
        "detail_label": "How many clients would you bring?",
        "detail_ph": "e.g. 6 now, a dozen next year",
        "company_label": "Agency",
        "cta": "Ask about white-labelling",
    },
    "care": {
        "nav": "Take care of it",
        "title": "Take care of what we built",
        "kicker": "For a system that already exists",
        "lede": "Somebody built it and then went quiet. Monitoring, patches, "
                "backups and a route for defects with times attached — that "
                "is a care plan, and it is the half of the bill most "
                "quotes leave out.",
        "points": [
            ["shield", "Watched, not hoped for",
             "Uptime checked every minute from three locations, key "
             "journeys tested, certificates and domains watched 45 and 21 "
             "days out. Alerts reach us before they reach you."],
            ["check", "Defects have deadlines",
             "What counts as a bug and how fast it is fixed are in a "
             "schedule you sign, not in a shared understanding."],
            ["truck", "Backups you can actually restore",
             "Nightly, off-site, encrypted — and restored on a test "
             "schedule, dated and filed. An untested backup is a belief."],
        ],
        "detail_label": "What is it running on now?",
        "detail_ph": "e.g. WordPress on a VPS nobody has logged into",
        "company_label": "Business",
        "cta": "Ask about a care plan",
    },
}


MENUS = [
    ("header", "Plans", "/#shop", 0),
    ("header", "Build your own", "/plan-builder", 1),
    ("header", "Pricing", "/p/pricing", 2),
    ("header", "How a build runs", "/p/how-it-works", 3),
    ("header", "Talk to us", "/partners/build", 4),
    ("footer", "Build your own", "/plan-builder", 0),
    ("footer", "Pricing", "/p/pricing", 1),
    ("footer", "How a build runs", "/p/how-it-works", 2),
    ("footer", "Talk to us", "/partners/build", 3),
]


def seed(con, force: bool) -> dict:
    n = {"products": 0, "sections": 0, "pages": 0, "menus": 0}
    have = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if have and not force:
        raise SystemExit(f"the studio shop already has {have} products — "
                         f"--force to re-seed (this replaces the home page)")

    con.execute("INSERT OR REPLACE INTO store_meta(k,v) VALUES('theme',?)",
                (json.dumps(THEME),))
    # This home page is deliberate, carousel and customer-count included —
    # say so, or the section back-fill puts a drinks showcase back on top of
    # it the next time the process starts.
    con.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                " VALUES('home_backfill',?)",
                (json.dumps(["showcase", "social_proof"]),))
    con.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                " VALUES('partner_pages',?)", (json.dumps(PARTNER_PAGES),))

    prods = products()
    for p in prods:
        row = con.execute("SELECT id FROM products WHERE sku=?",
                          (p["sku"],)).fetchone()
        if row:
            con.execute(
                "UPDATE products SET name=?, description=?, category=?,"
                " price_cents=?, active=1 WHERE id=?",
                (p["name"], p["description"], p["category"],
                 p["price_cents"], row[0]))
            pid = row[0]
        else:
            cur = con.execute(
                "INSERT INTO products(sku,name,description,category,"
                " price_cents,case_size,case_price_cents,active)"
                " VALUES(?,?,?,?,?,1,?,1)",
                (p["sku"], p["name"], p["description"], p["category"],
                 p["price_cents"], p["price_cents"]))
            pid = cur.lastrowid
        con.execute("INSERT OR REPLACE INTO store_product_meta"
                    "(product_id,k,v) VALUES(?,'colour',?)",
                    (pid, p.get("colour", "")))
        # The hero puts one product on stage. Pro is the one most businesses
        # land on, so it is the one standing there.
        con.execute("INSERT OR REPLACE INTO store_product_meta"
                    "(product_id,k,v) VALUES(?,'featured',?)",
                    (pid, "1" if p["sku"] == "PLAN-PRO" else "0"))
        # Plans and care bill every month; guided setup is bought once.
        # The flag is what makes the card say "Start" instead of "Add",
        # keeps it out of the one-off cart, and picks the checkout mode.
        con.execute("INSERT OR REPLACE INTO store_product_meta"
                    "(product_id,k,v) VALUES(?,'billing',?)",
                    (pid, p.get("billing", "")))
        # Some work is priced but not bought blind: the card shows where
        # the rung starts and sends you to the conversation instead of a
        # cart. Listed rather than hidden — a menu you cannot read is not
        # a price book.
        con.execute("INSERT OR REPLACE INTO store_product_meta"
                    "(product_id,k,v) VALUES(?,'quote',?)",
                    (pid, "1" if p.get("quote") else ""))
        # What it is, which is how every surface groups and tints it.
        con.execute("INSERT OR REPLACE INTO store_product_meta"
                    "(product_id,k,v) VALUES(?,'kind',?)",
                    (pid, p.get("kind", "goods")))
        # A bundle IS its capability set — carried on the product so the
        # shop can say what is in it and a stand-up can grant exactly it.
        con.execute("INSERT OR REPLACE INTO store_product_meta"
                    "(product_id,k,v) VALUES(?,'caps',?)",
                    (pid, p.get("caps", "")))
        n["products"] += 1

    # A tier renamed in the book leaves its old row behind — 'Starter plan'
    # sitting in the shop beside 'Basic plan', both for sale, both real to
    # a customer. What this script owns, it owns completely: the rows it
    # would have written and no longer does are retired. Deactivated, not
    # deleted, because somebody may already have bought one.
    mine = tuple(p["sku"] for p in prods)
    stale = [r[0] for r in con.execute(
        "SELECT sku FROM products WHERE active=1 AND ("
        " sku LIKE 'PLAN-%' OR sku LIKE 'CARE-%' OR sku LIKE 'BUILD-%'"
        " OR sku LIKE 'WL-%' OR sku LIKE 'WEB-%'"
        " OR sku LIKE 'BUNDLE-%' OR sku LIKE 'PACK-%')").fetchall()
        if r[0] not in mine]
    for sku in stale:
        con.execute("UPDATE products SET active=0 WHERE sku=?", (sku,))
    n["retired"] = len(stale)

    for slug, secs in (("home", home_sections()),
                       ("pricing", pricing_sections()),
                       ("how-it-works", process_sections())):
        if slug != "home":
            con.execute(
                "INSERT OR REPLACE INTO store_pages(slug,title,content_html,"
                " content_css,content_js,liquid,published,created_at)"
                " VALUES(?,?,'','','','',1,?)",
                (slug, {"pricing": "Pricing",
                        "how-it-works": "How a build runs"}[slug],
                 time.time()))
            n["pages"] += 1
        con.execute("DELETE FROM page_sections WHERE page_slug=?", (slug,))
        for i, (stype, settings) in enumerate(secs):
            con.execute(
                "INSERT INTO page_sections(page_slug,type,settings,position,"
                " enabled) VALUES(?,?,?,?,1)",
                (slug, stype, json.dumps(settings), i))
            n["sections"] += 1

    # No seeded collections. Sorting the shelf is what a product's KIND
    # does now — plans, care, builds, setups, labelling — and two category
    # systems side by side means a chip row that says "Care" twice and a
    # "Getting started" lane that empties itself the day a product moves.
    # Collections stay a merchant's own tool for groupings the kinds do not
    # express ("Black Friday"), so the ones seeded before are cleared here.
    for slug in ("plans", "care", "getting-started"):
        row = con.execute("SELECT id FROM collections WHERE slug=?",
                          (slug,)).fetchone()
        if row:
            con.execute("DELETE FROM collection_products WHERE"
                        " collection_id=?", (row[0],))
            con.execute("DELETE FROM collections WHERE id=?", (row[0],))
            n["collections"] = n.get("collections", 0) + 1

    con.execute("DELETE FROM store_menus")
    for loc, label, url, pos in MENUS:
        con.execute("INSERT INTO store_menus(location,label,url,position)"
                    " VALUES(?,?,?,?)", (loc, label, url, pos))
        n["menus"] += 1
    con.commit()
    return n


def main() -> int:
    force = "--force" in sys.argv
    tid = "studio"
    if "--tenant" in sys.argv:
        tid = sys.argv[sys.argv.index("--tenant") + 1]
    if tenancy.registry() and tid not in tenancy.all_tenants():
        print(f"no tenant '{tid}'")
        return 1
    tok = tenancy.CURRENT.set(tid if tenancy.registry() else None)
    try:
        from erp.backend import db
        con = db.connect()
        try:
            n = seed(con, force)
        finally:
            con.close()
    finally:
        tenancy.CURRENT.reset(tok)
    print(f"seeded {tid}: {n['products']} products, {n['sections']} sections "
          f"across {n['pages'] + 1} pages, {n['menus']} menu links"
          + (f", {n['retired']} renamed row(s) retired"
             if n.get("retired") else ""))
    print("  the numbers came from docs/product/price-book.md — re-run after "
          "a price change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
