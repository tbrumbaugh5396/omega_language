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
           cta2_text="See the work", cta2_link="/#impact",
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
    """Replace the tenant's home page with the shape's layout. Returns the
    shape name. Only ever called at stand-up, against a page nobody has
    touched — an operator's later edits are theirs."""
    import json
    shape, secs = home_sections(caps, brand)
    con.execute("DELETE FROM page_sections WHERE page_slug='home'")
    for i, (stype, settings) in enumerate(secs):
        con.execute(
            "INSERT INTO page_sections(page_slug,type,settings,position,"
            " enabled) VALUES('home',?,?,?,1)",
            (stype, json.dumps(settings), i))
    # The nav's first word should match the shape: "Shop" over a list of
    # courses reads as a mistake. Same link — the grid is still there.
    label = {"commerce": "Shop", "courses": "Courses",
             "nonprofit": "Ways to give", "services": "What we do"}[shape]
    con.execute("UPDATE store_menus SET label=? WHERE url='/#shop'",
                (label,))
    # This layout is deliberate — mark the back-fill applied so a restart
    # doesn't put the drinks showcase on top of it.
    con.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                " VALUES('home_backfill',?)",
                (json.dumps(["showcase", "social_proof"]),))
    con.commit()
    return shape
