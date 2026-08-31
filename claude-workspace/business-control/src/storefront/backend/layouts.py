"""Starter layouts — the home page a business shape deserves on day one.

A freshly stood-up tenant used to open on HOME_DEFAULT: a commerce page,
because the section engine grew up under a drinks brand. A course business
got a product wall; a food bank got a cart. The quote already says what the
business IS — its capability set — so the stand-up can seed a home page
shaped like the business instead of shaped like the codebase's history.

Two-layer composition, so it stays derivation rather than nineteen
hand-kept pages:

  * the SHAPE picks the skeleton — what the page is fundamentally for.
    Learning beats fundraising beats selling, because a nonprofit that
    teaches leads with its courses and asks for support beside them, not
    the other way round.
  * ADD-ONS contribute sections for capabilities that deserve a spot
    regardless of shape — fundraising adds the support banner to anyone
    who has it, subscriptions add the how-it-works explainer.

Every section is built on defaults_for(), overriding only what the shape
needs — a renamed section field breaks one place, not every pack. Copy is
scaffolding in the section engine's own voice: it says what to write, and
never invents a fact (no customer counts, no fake reviews).
"""
from . import sections as sect

SHAPES = {
    "commerce":  "a shop — products first, reasons to trust, one ask",
    "courses":   "a school — the promise, the curriculum, the enrol",
    "nonprofit": "a cause — the mission, the impact, the ways to help",
    "services":  "a practice — what you do, how it goes, the conversation",
}


def shape_of(caps) -> str:
    """Which skeleton this capability set implies. Priority is deliberate:
    what a business MAKES beats how it takes money."""
    caps = set(caps or [])
    if "learning" in caps:
        return "courses"
    if "fundraising" in caps:
        return "nonprofit"
    if caps & {"selling", "subs"}:
        return "commerce"
    return "services"


def _s(stype: str, **over) -> tuple:
    """A section on the schema's own defaults, overriding only what this
    layout needs."""
    return (stype, {**sect.defaults_for(stype), **over})


# ---------------------------------------------------------------- shapes --

def _commerce(brand: str) -> list:
    return [
        _s("hero",
           heading="What you sell,\nin one line.",
           sub="One sentence under it: who it is for, and why they should "
               "care. Replace this.",
           cta_text="Shop now", cta_link="/#shop"),
        _s("benefits"),
        _s("product_grid", heading="The collection"),
        _s("feature_columns", heading="Why buy from us"),
        _s("reviews", heading="What customers say"),
        _s("faq"),
        _s("newsletter"),
    ]


def _courses(brand: str) -> list:
    return [
        _s("hero",
           heading="What they'll be able to do\nwhen they finish.",
           sub="Lead with the outcome, not the syllabus — nobody buys a "
               "course, they buy the person they become. Replace this.",
           cta_text="See the courses", cta_link="/#shop",
           show_product=False,
           stat1="|courses", stat2="|hours of material", stat3="|students"),
        _s("feature_columns",
           heading="How the teaching works",
           items=[
               {"icon": "check", "title": "The method",
                "text": "What makes your teaching different. One concrete "
                        "claim beats three vague ones."},
               {"icon": "sparkle", "title": "The pace",
                "text": "Self-paced, cohort, live — say which, and what a "
                        "week actually looks like."},
               {"icon": "shield", "title": "The support",
                "text": "What happens when a student is stuck. This is the "
                        "question every buyer has and few pages answer."}]),
        _s("product_grid", heading="Courses", show_search=False),
        _s("rich_text",
           heading="Who teaches this",
           body="The instructor's story, told for the student: not a CV, "
                "but why this person can get them to the outcome the hero "
                "promised.\n\nReplace this."),
        _s("reviews", heading="From students"),
        _s("faq", items=[
            {"q": "How long do I have access?", "a": ""},
            {"q": "What if it isn't for me?", "a": ""},
            {"q": "Do I get a certificate?", "a": ""}]),
        _s("newsletter",
           heading="Not ready to enrol?",
           body="A free lesson, a syllabus, a sample — give something real "
                "for the address, or cut this section.",
           cta_text="Send it to me"),
    ]


def _nonprofit(brand: str) -> list:
    return [
        _s("hero",
           heading="The change you exist\nto make.",
           sub="The mission in one breath — who is helped, and what "
               "changes for them. Replace this.",
           cta_text="Donate", cta_link="/#shop",
           cta2_text="See the work", cta2_link="/p/impact",
           show_product=False,
           stat1="|people helped", stat2="|of every dollar to the work",
           stat3="|years doing it"),
        _s("rich_text",
           heading="The work",
           body="What the organisation actually does, concretely — a day, "
                "a delivery, a class. Donors give to work they can "
                "picture.\n\nReplace this.", align="left"),
        _s("product_grid", heading="Ways to give",
           show_search=False, show_tabs=False),
        _s("feature_columns",
           heading="Where the money goes",
           items=[
               {"icon": "check", "title": "The programme",
                "text": "The share that reaches the work, stated plainly."},
               {"icon": "shield", "title": "The accounting",
                "text": "Who audits you, and where the report lives."},
               {"icon": "truck", "title": "The rest",
                "text": "What overhead buys. Saying it beats hiding it."}]),
        _s("faq", items=[
            {"q": "Is my donation tax-deductible?", "a": ""},
            {"q": "Can I give monthly?", "a": ""},
            {"q": "Can I volunteer instead?", "a": ""}]),
        _s("newsletter",
           heading="Follow the work",
           body="One honest update a month — what happened, what it cost, "
                "what is next.",
           cta_text="Keep me posted"),
    ]


def _services(brand: str) -> list:
    return [
        _s("hero",
           heading="The problem you solve,\nstated as the client feels it.",
           sub="Then one line on how engagements start. Replace this.",
           cta_text="Start a conversation", cta_link="/partners/build",
           cta2_text="", show_product=False,
           stat1="|", stat2="|", stat3="|"),
        _s("feature_columns", heading="What we do"),
        _s("rich_text",
           heading="How an engagement runs",
           body="The stages, in the client's language — what they get at "
                "each, and when they can stop. A process page is what "
                "separates a practice from a freelancer with a phone."
                "\n\nReplace this.", align="left"),
        _s("product_grid", heading="Ways to work with us",
           show_search=False, show_tabs=False),
        _s("reviews", heading="What clients say"),
        _s("faq", items=[
            {"q": "How do engagements start?", "a": ""},
            {"q": "What does it cost?", "a": ""},
            {"q": "How long does it take?", "a": ""}]),
        _s("newsletter"),
    ]


_SHAPE_SECTIONS = {"commerce": _commerce, "courses": _courses,
                   "nonprofit": _nonprofit, "services": _services}


# --------------------------------------------------------------- add-ons --

def _addons(shape: str, caps) -> list:
    """Sections a capability earns on ANY shape that doesn't already lead
    with it. Each returns (position_hint, section): 'after_hero' or 'end'."""
    caps = set(caps or [])
    out = []
    if "fundraising" in caps and shape != "nonprofit":
        out.append(("end", _s(
            "image_banner",
            heading="Support the work",
            text="The cause this business carries, and the ask — one "
                 "banner, one link. Replace this.",
            link="/#shop", height="medium")))
    if "subs" in caps and shape != "commerce":
        out.append(("after_hero", _s(
            "rich_text",
            heading="There's a subscription",
            body="What arrives, how often, and how to pause it. A "
                 "subscription pitched clearly outsells one hidden on a "
                 "product page.\n\nReplace this.")))
    if "events" in caps:
        out.append(("end", _s(
            "rich_text",
            heading="Come find us",
            body="Where you'll be this month — the events page has the "
                 "map and the dates.\n\nReplace this, and keep the link: "
                 "<a href=\"/events\">events</a>.")))
    return out


# ------------------------------------------------------- secondary pages --
# The pages a business shape needs BESIDE its home — where "tell them more"
# actually lives. Same scaffolding contract as the home sections: the copy
# says what to write, and never invents a fact. An image banner left empty
# renders as a labeled placeholder, which in the live editor is a
# click-to-upload target — the page tells the merchant where its photo
# goes.

def _about_page(heading: str, body: str, cols_heading: str,
                cols: list) -> list:
    return [
        _s("rich_text", heading=heading, body=body, align="left"),
        _s("image_banner", heading="", text="", link="", height="medium"),
        _s("feature_columns", heading=cols_heading, items=cols),
    ]


def _pages_commerce(brand: str) -> list:
    return [
        ("our-story", "Our story", _about_page(
            "Our story",
            "Where this started, and why. A founding story is not a "
            "timeline — it is the one problem you refused to live with, "
            "told so a stranger nods.\n\nReplace this.",
            "What we stand for",
            [{"icon": "check", "title": "The first thing",
              "text": "A value is only real if it costs you something — "
                      "name what this one costs."},
             {"icon": "shield", "title": "The second",
              "text": "Different from the first."},
             {"icon": "sparkle", "title": "The third",
              "text": "Then stop."}])),
        ("delivery-and-returns", "Delivery & returns", [
            _s("rich_text", heading="Delivery & returns",
               body="The policy, in the customer's language: when it "
                    "ships, what it costs, and what happens when "
                    "something is wrong. Write the real numbers — an "
                    "invented policy is worse than a blank.\n\n"
                    "Replace this.", align="left"),
            _s("faq", heading="The details", items=[
                {"q": "When will my order ship?", "a": ""},
                {"q": "What does delivery cost?", "a": ""},
                {"q": "How do returns work?", "a": ""},
                {"q": "My order arrived damaged — now what?", "a": ""}]),
        ]),
    ]


def _pages_courses(brand: str) -> list:
    return [
        ("our-story", "Who teaches this", _about_page(
            "Who teaches this",
            "The instructor's story, told for the student: not a CV, but "
            "the road that qualifies this person to get them to the "
            "outcome the home page promised.\n\nReplace this.",
            "Why students trust it",
            [{"icon": "check", "title": "The experience",
              "text": "Years, students, results — only what you can "
                      "stand behind."},
             {"icon": "shield", "title": "The method's origin",
              "text": "Where this way of teaching came from."},
             {"icon": "sparkle", "title": "The proof",
              "text": "One student outcome, concrete and true."}])),
        ("curriculum", "The curriculum", [
            _s("rich_text", heading="The curriculum",
               body="Module by module, in outcome language: after each, "
                    "what can the student now do? A syllabus of topics "
                    "sells to nobody; a ladder of abilities sells "
                    "itself.\n\nReplace this.", align="left"),
            _s("faq", heading="How the course runs", items=[
                {"q": "How much time does it take each week?", "a": ""},
                {"q": "Is it live, or at my own pace?", "a": ""},
                {"q": "What do I need before starting?", "a": ""},
                {"q": "What happens when I'm stuck?", "a": ""}]),
        ]),
    ]


def _pages_nonprofit(brand: str) -> list:
    return [
        ("our-story", "The mission", _about_page(
            "The mission",
            "Why this organisation exists — the gap it stepped into, who "
            "fell through it, and what changes when the work succeeds."
            "\n\nReplace this.",
            "How we work",
            [{"icon": "check", "title": "On the ground",
              "text": "What a week of the work actually looks like."},
             {"icon": "shield", "title": "With partners",
              "text": "Who you work alongside, and why."},
             {"icon": "truck", "title": "At what scale",
              "text": "Honest about size — small and real beats big and "
                      "vague."}])),
        ("impact", "The work", [
            _s("rich_text", heading="The work, this year",
               body="What happened, what it cost, what changed — numbers "
                    "you can stand behind, sourced from your own records. "
                    "Donors forgive small numbers; they do not forgive "
                    "invented ones.\n\nReplace this.", align="left"),
            _s("image_banner", heading="", text="", link="",
               height="medium"),
            _s("rich_text", heading="Who checks the numbers",
               body="The audit, the filing, the register entry — where a "
                    "sceptical donor can verify every claim above without "
                    "asking permission.\n\nReplace this.", align="left"),
        ]),
    ]


def _pages_services(brand: str) -> list:
    return [
        ("our-story", "Who we are", _about_page(
            "Who we are",
            "The people behind the practice, and the work that shaped "
            "them. Clients hire the people, not the brand — show the "
            "people.\n\nReplace this.",
            "How we think",
            [{"icon": "check", "title": "A conviction",
              "text": "Something you believe about this work that not "
                      "everyone does."},
             {"icon": "shield", "title": "A boundary",
              "text": "Work you turn down, and why — it is the fastest "
                      "way to be believed."},
             {"icon": "sparkle", "title": "A habit",
              "text": "The thing you always do that clients mention."}])),
        ("how-we-work", "How an engagement runs", [
            _s("rich_text", heading="How an engagement runs",
               body="Stage by stage, in the client's language: what they "
                    "get at each, what it costs, and where they can stop. "
                    "A written process is what separates a practice from "
                    "a freelancer with a phone.\n\nReplace this.",
               align="left"),
            _s("faq", heading="What clients ask first", items=[
                {"q": "How does it start?", "a": ""},
                {"q": "How do you charge?", "a": ""},
                {"q": "Who will we actually work with?", "a": ""},
                {"q": "What if we want to stop halfway?", "a": ""}]),
        ]),
    ]


SHAPE_PAGES = {"commerce": _pages_commerce, "courses": _pages_courses,
               "nonprofit": _pages_nonprofit, "services": _pages_services}


def secondary_pages(shape: str, brand: str = "") -> list:
    """[(slug, title, [(type, settings), ...]), ...] for this shape."""
    return SHAPE_PAGES[shape](brand)


def home_sections(caps, brand: str = "") -> tuple:
    """(shape, [(type, settings), ...]) for this capability set."""
    shape = shape_of(caps)
    secs = _SHAPE_SECTIONS[shape](brand)
    for where, sec in _addons(shape, caps):
        if where == "after_hero":
            secs.insert(1, sec)
        else:
            secs.append(sec)
    return shape, secs


def apply(con, caps, brand: str = "") -> str:
    """Seed the tenant's home page, secondary pages and nav from the
    shape. Returns the shape name. Only ever called at stand-up, against
    pages nobody has touched — an operator's later edits are theirs, and
    a page whose slug already exists is left entirely alone."""
    import json
    import time
    shape, secs = home_sections(caps, brand)
    con.execute("DELETE FROM page_sections WHERE page_slug='home'")
    for i, (stype, settings) in enumerate(secs):
        con.execute(
            "INSERT INTO page_sections(page_slug,type,settings,position,"
            " enabled) VALUES('home',?,?,?,1)",
            (stype, json.dumps(settings), i))

    # The pages beside the home — where "tell them more" lives. Created
    # only where the slug is free: a page that already exists is someone's
    # work, whatever stand-up is re-running over it.
    for slug, title, psecs in secondary_pages(shape, brand):
        cur = con.execute(
            "INSERT OR IGNORE INTO store_pages(slug,title,published,"
            " created_at) VALUES(?,?,1,?)", (slug, title, time.time()))
        if not cur.rowcount:
            continue
        for i, (stype, settings) in enumerate(psecs):
            con.execute(
                "INSERT INTO page_sections(page_slug,type,settings,"
                " position,enabled) VALUES(?,?,?,?,1)",
                (slug, stype, json.dumps(settings), i))
    # The nav names the shape's pages that EXIST — not only the ones this
    # run created, or a re-run would silently drop the links to pages it
    # left alone — under their stored titles, because a renamed page is
    # the operator's rename.
    made = []
    for slug, _, _ in secondary_pages(shape, brand):
        row = con.execute("SELECT title FROM store_pages WHERE slug=?"
                          " AND published=1", (slug,)).fetchone()
        if row:
            made.append((slug, row[0]))

    # The nav, rebuilt to carry the shape: its word for the grid, the new
    # pages, then the anchors the home page actually has. A "Reviews" link
    # on a shape with no reviews section is a link to nothing.
    label = {"commerce": "Shop", "courses": "Courses",
             "nonprofit": "Ways to give", "services": "What we do"}[shape]
    header = [(label, "/#shop")] + [(t, f"/p/{sl}") for sl, t in made]
    if any(t == "reviews" for t, _ in secs):
        header.append(("Reviews", "/#reviews"))
    header += [("FAQ", "/#faq"), ("Blog", "/blog")]
    footer = ([(label, "/#shop")] + [(t, f"/p/{sl}") for sl, t in made]
              + [("Blog", "/blog")])
    con.execute("DELETE FROM store_menus")
    for loc, links in (("header", header), ("footer", footer)):
        for pos, (lbl, url) in enumerate(links):
            con.execute("INSERT INTO store_menus(location,label,url,"
                        " position) VALUES(?,?,?,?)", (loc, lbl, url, pos))
    # This layout is deliberate — mark the back-fill applied so a restart
    # doesn't put the drinks showcase on top of it.
    con.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                " VALUES('home_backfill',?)",
                (json.dumps(["showcase", "social_proof"]),))
    con.commit()
    return shape


# ------------------------------------------------------ the placeholder --
# What a tenant stood up WITHOUT a quote opens on. No shape can be derived
# from nothing, and the old answer — the section engine's factory default,
# drinks film and all — put another business's brand on the new one's
# front page. The placeholder says exactly what is true: the install is
# live, the site is not designed yet, and here is where designing happens.

def placeholder_home(brand: str = "") -> list:
    b = brand or "This business"
    return [
        _s("hero",
           heading=f"{b}\nis setting up shop.",
           sub="The install is live — the storefront just hasn't been "
               "designed yet. Everything on this page is a placeholder "
               "waiting for the real thing.",
           cta_text="", cta_link="", cta2_text="",
           show_product=False, bg="gradient",
           stat1="|", stat2="|", stat3="|"),
        _s("rich_text",
           heading="What happens next",
           body="The design happens in the theme editor — click any "
                "section on the page and type over it, drop images "
                "straight onto it, add and reorder sections in place. Or "
                "file a quote for this client and re-run the stand-up: "
                "the capabilities they buy will shape this page "
                "automatically.\n\nReplace this page; it knows it is "
                "temporary.", align="center"),
        _s("newsletter",
           heading="Opening soon",
           body="Leave an address and hear about it first.",
           cta_text="Keep me posted"),
    ]


def apply_placeholder(con, brand: str = "") -> None:
    """Replace the factory-default home with the honest placeholder. Only
    ever called at stand-up, onto a page nobody has touched."""
    import json
    con.execute("DELETE FROM page_sections WHERE page_slug='home'")
    for i, (stype, settings) in enumerate(placeholder_home(brand)):
        con.execute(
            "INSERT INTO page_sections(page_slug,type,settings,position,"
            " enabled) VALUES('home',?,?,?,1)",
            (stype, json.dumps(settings), i))
    con.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                " VALUES('home_backfill',?)",
                (json.dumps(["showcase", "social_proof"]),))
    con.commit()


# ------------------------------------------------- the grant, growing --
# When a capability is bought AFTER stand-up, the site should grow the
# piece that sells it — additively. The operator's edits are theirs: this
# never rewrites the home page or the nav wholesale, it only ADDS what a
# newly granted capability earns and is verifiably absent.

def extend_for_caps(con, added, all_caps, brand: str = "") -> dict:
    """Additive site growth for newly granted capabilities.

    Adds: the add-on sections the new caps earn (detected absent by
    type + heading, the same pair the add-ons are defined by), the shape's
    secondary pages where the slug is free, and nav links for pages
    created HERE only — an operator's nav stays their nav. Returns what
    was done, so the caller can say it out loud."""
    import json
    shape = shape_of(all_caps)
    done = {"sections": [], "pages": [], "nav": []}

    have = {(r[0], (json.loads(r[1] or "{}")).get("heading", ""))
            for r in con.execute(
                "SELECT type, settings FROM page_sections"
                " WHERE page_slug='home'")}
    # The shape-skips in _addons are stand-up reasoning ("the commerce
    # skeleton already sells, so no subs explainer") — reasoning that does
    # not hold for a page built BEFORE the capability existed. A later
    # purchase earns its section unconditionally; "services" is the shape
    # with no skips.
    for _where, (stype, settings) in _addons("services", added):
        key = (stype, settings.get("heading", ""))
        if key in have:
            continue
        nxt = con.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM page_sections"
            " WHERE page_slug='home'").fetchone()[0]
        con.execute(
            "INSERT INTO page_sections(page_slug,type,settings,position,"
            " enabled) VALUES('home',?,?,?,1)",
            (stype, json.dumps(settings), nxt))
        done["sections"].append(settings.get("heading") or stype)

    import time
    for slug, title, psecs in secondary_pages(shape, brand):
        cur = con.execute(
            "INSERT OR IGNORE INTO store_pages(slug,title,published,"
            " created_at) VALUES(?,?,1,?)", (slug, title, time.time()))
        if not cur.rowcount:
            continue
        for i, (stype, settings) in enumerate(psecs):
            con.execute(
                "INSERT INTO page_sections(page_slug,type,settings,"
                " position,enabled) VALUES(?,?,?,?,1)",
                (slug, stype, json.dumps(settings), i))
        done["pages"].append(slug)
        if not con.execute("SELECT 1 FROM store_menus WHERE url=?",
                           (f"/p/{slug}",)).fetchone():
            for loc in ("header", "footer"):
                nxt = con.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM"
                    " store_menus WHERE location=?", (loc,)).fetchone()[0]
                con.execute(
                    "INSERT INTO store_menus(location,label,url,position)"
                    " VALUES(?,?,?,?)", (loc, title, f"/p/{slug}", nxt))
            done["nav"].append(title)
    con.commit()
    return done


def trim_for_caps(con, removed) -> list:
    """The reverse of growth, under a stricter rule: a revoked capability
    takes back its add-on sections ONLY where the section is still
    exactly the scaffolding growth placed — byte-for-byte untouched. The
    moment an operator edited one, it became their page, and revocation
    of a capability is not licence to delete their work; an edited
    remnant merely stops being reachable through the gated routes.
    Returns what was removed, so the caller can say it."""
    import json
    trimmed = []
    for _where, (stype, settings) in _addons("services", removed):
        for r in con.execute(
                "SELECT id, settings FROM page_sections WHERE"
                " page_slug='home' AND type=?", (stype,)).fetchall():
            try:
                if json.loads(r[1]) == settings:
                    con.execute("DELETE FROM page_sections WHERE id=?",
                                (r[0],))
                    trimmed.append(settings.get("heading") or stype)
                    break
            except ValueError:
                continue
    if trimmed:
        con.commit()
    return trimmed
