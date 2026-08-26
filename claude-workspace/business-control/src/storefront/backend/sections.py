"""Section engine — the shared substrate for the theme editor and the visual
page builder.

A page (the storefront home, or any custom page) is an ordered list of
sections. Each section has a `type` from SECTION_TYPES, whose `fields` drive
both the admin settings form and the server-side renderer. Adding a section
type means adding one entry here: the editor UI needs no changes.
"""
import html as _html
import json
import re


def esc(v) -> str:
    return _html.escape(str(v or ""))


# t: text | textarea | richtext | select | number | checkbox | media | color | list
SECTION_TYPES = {
    "hero": {
        "label": "Hero banner", "icon": "wave",
        "help": "Opener with headline, one button and the product beside it.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "Some days come\nat you in waves."},
            {"k": "sub", "t": "textarea", "label": "Sub-heading",
             "default": "Sparkling tea with 200mg L-theanine — calm that "
                        "doesn't cloud. And then it doesn't."},
            {"k": "cta_text", "t": "text", "label": "Primary button",
             "default": "Shop your Zen"},
            {"k": "cta_link", "t": "text", "label": "Primary link",
             "default": "/#shop"},
            {"k": "cta2_text", "t": "text", "label": "Secondary button",
             "default": ""},
            {"k": "cta2_link", "t": "text", "label": "Secondary link",
             "default": "/#rewards"},
            {"k": "layout", "t": "select", "label": "Layout",
             "options": ["split", "centred"], "default": "split"},
            {"k": "show_product", "t": "checkbox",
             "label": "Show product beside the copy", "default": True},
            {"k": "stat1", "t": "text", "label": "Stat 1",
             "default": "200mg|L-theanine per can"},
            {"k": "stat2", "t": "text", "label": "Stat 2",
             "default": "15|calories"},
            {"k": "stat3", "t": "text", "label": "Stat 3",
             "default": "4|flavors to find yours"},
            {"k": "bg", "t": "select", "label": "Background",
             "options": ["shader", "gradient", "image"], "default": "gradient"},
            {"k": "media_id", "t": "media", "label": "Background image"},
        ]},
    "showcase": {
        "label": "Showcase carousel", "icon": "play",
        "help": "The film, then one slide per product. Arrows, dots, "
                "keyboard and swipe all move it.",
        "fields": [
            {"k": "video_src", "t": "text", "label": "Video file",
             "default": "/hero/zenjoy-hero.mp4"},
            {"k": "video_poster", "t": "text", "label": "Video poster",
             "default": "/hero/zenjoy-hero.jpg"},
            {"k": "video_caption", "t": "text", "label": "Video caption",
             "default": "4 flavors, 1 calm"},
            {"k": "cta_text", "t": "text", "label": "Button under the caption",
             "default": "Find your zen"},
            {"k": "cta_link", "t": "text", "label": "Button link",
             "default": "/#shop"},
            {"k": "collection_id", "t": "text", "label": "Collection id",
             "default": ""},
            {"k": "autoplay", "t": "checkbox",
             "label": "Play the film automatically (muted)", "default": True},
        ]},
    "social_proof": {
        "label": "Customer count", "icon": "heart",
        "help": "One line of proof, directly under the opener.",
        "fields": [
            {"k": "figure", "t": "text", "label": "Figure",
             "default": "100,000+"},
            {"k": "label", "t": "text", "label": "Label",
             "default": "Zen customers"},
            {"k": "sub", "t": "text", "label": "Sub-line",
             "default": "and counting, one calm can at a time"},
        ]},
    "benefits": {
        "label": "Benefit strip", "icon": "check",
        "help": "The nutrition and claims row — the numbers that sell a "
                "functional drink. Keep to four or five.",
        "fields": [
            {"k": "items", "t": "repeat", "label": "Benefits",
             "item": [{"k": "icon", "t": "text", "label": "Icon name"},
                      {"k": "value", "t": "text", "label": "Value"},
                      {"k": "label", "t": "text", "label": "Label"}],
             "default": [
                 {"icon": "leaf", "value": "200mg", "label": "L-theanine"},
                 {"icon": "sparkle", "value": "150mg", "label": "ashwagandha"},
                 {"icon": "drop", "value": "150mg", "label": "lemon balm"},
                 {"icon": "shield", "value": "70", "label": "calories"},
                 {"icon": "truck", "value": "Free", "label": "shipping over $40"},
             ]},
        ]},
    "product_grid": {
        "label": "Product grid", "icon": "bag",
        "help": "The shoppable collection, with search and collection tabs.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "The collection"},
            {"k": "collection_id", "t": "collection", "label": "Collection",
             "default": ""},
            {"k": "limit", "t": "number", "label": "Max products (0 = all)",
             "default": 0},
            {"k": "show_search", "t": "checkbox", "label": "Show search box",
             "default": True},
            {"k": "show_tabs", "t": "checkbox", "label": "Show collection tabs",
             "default": True},
        ]},
    "rich_text": {
        "label": "Text block", "icon": "text",
        "help": "Headline plus paragraph. Simple formatting allowed.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "Our story"},
            {"k": "body", "t": "richtext", "label": "Body",
             "default": "Small batches. Clean ingredients. Big joy."},
            {"k": "align", "t": "select", "label": "Alignment",
             "options": ["left", "center"], "default": "left"},
        ]},
    "feature_columns": {
        "label": "Feature columns", "icon": "columns",
        "help": "Three (or more) icon + text cards.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "What's inside?"},
            {"k": "items", "t": "list", "label": "Columns",
             "item_fields": [
                 {"k": "icon", "t": "text", "label": "Icon name",
                  "default": "leaf"},
                 {"k": "title", "t": "text", "label": "Title",
                  "default": "Clean ingredients"},
                 {"k": "text", "t": "textarea", "label": "Text",
                  "default": "Nothing artificial. Everything pronounceable."}],
             "default": [
                 {"icon": "leaf", "title": "Clean ingredients",
                  "text": "Nothing artificial. Everything pronounceable."},
                 {"icon": "drop", "title": "Calm, not sleepy",
                  "text": "L-theanine takes the edge off without taking you "
                          "out. No crash, because there's nothing to crash "
                          "from."},
                 {"icon": "truck", "title": "Fresh to your door",
                  "text": "Small batches, shipped fast, tracked all the way."}]},
        ]},
    "image_banner": {
        "label": "Image banner", "icon": "image",
        "help": "Large image with optional overlay text.",
        "fields": [
            {"k": "media_id", "t": "media", "label": "Image"},
            {"k": "heading", "t": "text", "label": "Heading", "default": ""},
            {"k": "text", "t": "textarea", "label": "Text", "default": ""},
            {"k": "link", "t": "text", "label": "Link", "default": ""},
            {"k": "height", "t": "select", "label": "Height",
             "options": ["short", "medium", "tall"], "default": "medium"},
        ]},
    "video": {
        "label": "Video", "icon": "video",
        "help": "Embedded or uploaded video.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading", "default": ""},
            {"k": "video_url", "t": "text", "label": "Embed URL",
             "default": ""},
            {"k": "media_id", "t": "media", "label": "…or uploaded video"},
        ]},
    "reviews": {
        "label": "Reviews wall", "icon": "star",
        "help": "Approved customer reviews.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "Loved out loud"},
            {"k": "limit", "t": "number", "label": "How many", "default": 6},
        ]},
    "faq": {
        "label": "FAQ", "icon": "question",
        "help": "Expandable question list.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "Frequently asked questions"},
            {"k": "items", "t": "list", "label": "Questions",
             "item_fields": [
                 {"k": "q", "t": "text", "label": "Question", "default": ""},
                 {"k": "a", "t": "textarea", "label": "Answer", "default": ""}],
             "default": [
                 {"q": "How fast is shipping?",
                  "a": "Orders ship within 2 business days; free over $40."},
                 {"q": "Can I use a discount code?",
                  "a": "Yes — add it in the cart."},
                 {"q": "What if I don't love it?",
                  "a": "Tell support — we make it right, every time."}]},
        ]},
    "newsletter": {
        "label": "Email signup", "icon": "mail",
        "help": "Rewards / newsletter capture.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "Join the club"},
            {"k": "body", "t": "textarea", "label": "Body",
             "default": "10% off your first order, early access to drops, "
                        "and rewards on every sip."},
            {"k": "cta_text", "t": "text", "label": "Button",
             "default": "Become a member"},
        ]},
    "social": {
        "label": "Social row", "icon": "camera",
        "help": "Links to your social profiles.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "In the wild"},
            {"k": "items", "t": "list", "label": "Profiles",
             "item_fields": [
                 {"k": "icon", "t": "text", "label": "Icon name",
                  "default": "instagram"},
                 {"k": "handle", "t": "text", "label": "Handle",
                  "default": "@zenjoy"},
                 {"k": "network", "t": "text", "label": "Network",
                  "default": "Instagram"},
                 {"k": "link", "t": "text", "label": "Link", "default": "#"}],
             "default": [
                 {"icon": "instagram", "handle": "@zenjoy",
                  "network": "Instagram", "link": "#"},
                 {"icon": "music", "handle": "@zenjoy", "network": "TikTok",
                  "link": "#"},
                 {"icon": "play", "handle": "Zenjoy", "network": "YouTube",
                  "link": "#"}]},
        ]},
    "latest_posts": {
        "label": "Latest journal posts", "icon": "news",
        "help": "Newest blog posts — the organic-traffic engine.",
        "fields": [
            {"k": "heading", "t": "text", "label": "Heading",
             "default": "From the journal"},
            {"k": "limit", "t": "number", "label": "How many", "default": 3},
        ]},
    "custom_html": {
        "label": "Custom code", "icon": "code",
        "help": "Raw HTML/CSS/JS and Liquid — the escape hatch.",
        "fields": [
            {"k": "html", "t": "textarea", "label": "HTML", "default": ""},
            {"k": "css", "t": "textarea", "label": "CSS", "default": ""},
            {"k": "js", "t": "textarea", "label": "JavaScript", "default": ""},
            {"k": "liquid", "t": "textarea", "label": "Liquid", "default": ""},
        ]},
    "spacer": {
        "label": "Spacer", "icon": "␣", "help": "Vertical breathing room.",
        "fields": [
            {"k": "height", "t": "number", "label": "Height (px)",
             "default": 40},
        ]},
}


def defaults_for(stype: str) -> dict:
    spec = SECTION_TYPES.get(stype)
    if not spec:
        return {}
    return {f["k"]: f.get("default", "") for f in spec["fields"]}


def schema_json() -> dict:
    """What the editor needs to build forms for every section type."""
    return {k: {"label": v["label"], "icon": v["icon"],
                "help": v.get("help", ""), "fields": v["fields"]}
            for k, v in SECTION_TYPES.items()}


def _settings(row) -> dict:
    try:
        s = json.loads(row["settings"] or "{}")
    except (ValueError, TypeError):
        s = {}
    return {**defaults_for(row["type"]), **s}


# ---------- renderers ----------

def _media_url(con, mid, thumb=False) -> str:
    if not mid:
        return ""
    row = con.execute("SELECT id FROM product_media WHERE id=?",
                      (mid,)).fetchone()
    if row is None:
        return ""
    return f"/media/m/{mid}{'/thumb' if thumb else ''}"


def icon(name: str, cls: str = "ico") -> str:
    """Reference the sprite in index.html. Falls back to nothing rather than
    rendering a broken glyph if an old emoji value is still stored."""
    name = re.sub(r"[^a-z0-9-]", "", str(name or "").lower())
    if not name:
        return ""
    return f'<svg class="{cls}" aria-hidden="true"><use href="#i-{name}"/></svg>'


def _stat(raw: str) -> str:
    """"200mg|L-theanine per can" -> big number over small label."""
    if not raw:
        return ""
    value, _, label = str(raw).partition("|")
    return f"<div><b>{esc(value)}</b>{esc(label)}</div>"


def _hero(con, s) -> str:
    head = "<br>".join(esc(l) for l in str(s["heading"]).split("\n"))
    bg = s.get("bg", "gradient")
    centred = s.get("layout") == "centred"
    img = _media_url(con, s.get("media_id"))
    style = ""
    canvas = ""
    if bg == "image" and img:
        style = (f' style="background-image:linear-gradient('
                 f'rgba(27,24,31,.42),rgba(27,24,31,.42)),url({img});'
                 f'background-size:cover;background-position:center"')
    elif bg == "gradient":
        # Soft wash rather than a saturated flood — the copy has to sit on it.
        style = (' style="background:radial-gradient(120% 100% at 78% 30%,'
                 'var(--lav-soft) 0%, #f6f1fb 42%, var(--bg) 100%)"')
    else:
        canvas = '<canvas id="shader-bg"></canvas>'
    btns = ""
    if s.get("cta_text"):
        btns += (f'<a class="btn-pill primary" href="{esc(s["cta_link"])}">'
                 f'{esc(s["cta_text"])}'
                 f'{icon("arrow", "ico ico-sm")}</a>')
    if s.get("cta2_text"):
        btns += (f'<a class="btn-pill ghost" href="{esc(s["cta2_link"])}">'
                 f'{esc(s["cta2_text"])}</a>')
    stats = "".join(_stat(s.get(k, "")) for k in ("stat1", "stat2", "stat3"))
    stats = f'<div class="hero-note">{stats}</div>' if stats else ""
    # The stage is filled client-side with the first product's can (or its
    # photo once real imagery exists) — see hydrateHero() in store.js.
    stage = ('<div class="hero-stage" id="hero-stage"></div>'
             if s.get("show_product", True) and not centred else "")
    cls = "hero centred" if centred else "hero"
    return (f'<section class="{cls}"{style}>{canvas}'
            f'<div class="hero-grid"><div class="hero-inner">'
            f'<h1>{head}</h1><p>{esc(s["sub"])}</p>'
            f'<div class="hero-cta">{btns}</div>{stats}</div>'
            f'{stage}</div></section>')


# Which of the film's tessellations belongs behind which SKU. Keyed on sku
# rather than derived from the name so a rename cannot silently drop a
# pattern; anything unlisted falls back to the plain slide, which still reads.
SKU_PATTERN = {
    "ZJ-MANGO": "mango", "ZJ-PASSION": "passionfruit",
    "ZJ-LAVENDER": "lavender", "ZJ-HONEY": "honey", "ZJ-PACK-12": "all",
}


def _showcase(con, s) -> str:
    """The film and the range in one swipeable rail.

    Slides are rendered server-side rather than fetched: this is the first
    thing on the page, and a carousel that arrives empty and pops in a
    moment later is worse than no carousel. Only the wiring is JavaScript,
    so with none the rail is still a readable, scrollable row of products.
    """
    # The primary media id comes along so slides can link the immutable
    # /media/m/<mid> URL. /media/product/<id> means "whatever art this
    # product has now" — a mutable pointer that browsers happily cache,
    # so swapping a photo leaves everyone who saw the old one looking at it.
    q = ("SELECT p.id, p.sku, p.name, p.description, p.price_cents, p.image,"
         " p.category,"
         " (SELECT m.id FROM product_media m WHERE m.product_id=p.id"
         "  AND m.kind='image' ORDER BY m.position, m.id LIMIT 1) mid"
         " FROM products p WHERE p.active=1")
    args = []
    if s.get("collection_id"):
        q += (" AND p.id IN (SELECT product_id FROM collection_products"
              " WHERE collection_id=?)")
        args.append(s["collection_id"])
    rows = con.execute(q + " ORDER BY p.category DESC, p.id", args).fetchall()

    slides = []
    if s.get("video_src"):
        auto = " autoplay" if s.get("autoplay", True) else ""
        cta = ""
        if s.get("cta_text"):
            cta = (f'<a class="btn-pill primary show-cta"'
                   f' href="{esc(s.get("cta_link") or "#shop")}">'
                   f'{esc(s["cta_text"])}{icon("arrow", "ico ico-sm")}</a>')
        slides.append(
            f'<li class="show-slide show-video" data-kind="video">'
            f'<video id="show-video" playsinline preload="metadata"'
            f' poster="{esc(s["video_poster"])}"{auto}>'
            f'<source src="{esc(s["video_src"])}" type="video/mp4"></video>'
            # A play/pause glyph over the film, a scrubber under it. Both are
            # real controls with names — the film is content, not decor.
            f'<button class="show-play" id="show-play" type="button"'
            f' aria-label="Pause film" aria-pressed="false">'
            f'<svg class="ico" aria-hidden="true"><use href="#i-play"/></svg>'
            f'</button>'
            f'<div class="show-scrub" id="show-scrub" role="slider"'
            f' tabindex="0" aria-label="Film position" aria-valuemin="0"'
            f' aria-valuemax="100" aria-valuenow="0">'
            f'<div class="show-scrub-buf" id="show-scrub-buf"></div>'
            f'<div class="show-scrub-fill" id="show-scrub-fill"></div>'
            f'<div class="show-scrub-knob" id="show-scrub-knob"></div></div>'
            f'<button class="show-sound" id="show-sound" type="button"'
            f' aria-pressed="false" aria-label="Turn sound on">'
            f'{icon("music", "ico ico-sm")}<span>Sound on</span></button>'
            f'<div class="show-cap"><b>{esc(s["video_caption"])}</b>{cta}</div>'
            f'</li>')

    for r in rows:
        src = (f'/media/m/{r["mid"]}' if r["mid"]
               else f'/media/product/{r["id"]}')
        # Eager, deliberately. These sit inside a horizontal scroll-snap
        # rail; a lazy image in an off-axis slide is not "near the viewport"
        # by the browser's reckoning until it is scrolled to, and with the
        # image sized by its own aspect the box is 0px until it loads — so
        # nothing ever brings it in. Five product renders is a fine cost for
        # a carousel that is the first thing on the page.
        img = (f'<img src="{src}" alt="{esc(r["name"])}"'
               f' decoding="async">' if r["image"] else "")
        pat = SKU_PATTERN.get(r["sku"] or "")
        # The case is photographed wide; in a single-can slot it comes out
        # small enough that you cannot tell there are four in it.
        wide = " show-wide" if (r["category"] or "") == "multipacks" else ""
        slides.append(
            f'<li class="show-slide{f" pat-{pat}" if pat else ""}{wide}"'
            f' data-kind="product" data-id="{r["id"]}"'
            f'{f" data-pattern={pat}" if pat else ""}>'
            f'<div class="show-shot">{img}</div>'
            f'<div class="show-copy"><b>{esc(r["name"])}</b>'
            f'<p>{esc((r["description"] or "")[:120])}</p>'
            f'<span class="show-price">${r["price_cents"] / 100:.2f}</span>'
            f'<button class="btn-pill primary sm show-add"'
            f' data-add="{r["id"]}">Add to cart</button></div></li>')

    dots = "".join(
        f'<button class="show-dot" data-go="{i}" type="button"'
        f' aria-label="Slide {i + 1} of {len(slides)}"></button>'
        for i in range(len(slides)))
    return (
        f'<section class="showcase" id="showcase" aria-roledescription="carousel"'
        f' aria-label="Zenjoy film and products">'
        f'<ul class="show-rail" id="show-rail">{"".join(slides)}</ul>'
        f'<button class="show-arrow prev" id="show-prev" type="button"'
        f' aria-label="Previous slide">{icon("arrow")}</button>'
        f'<button class="show-arrow next" id="show-next" type="button"'
        f' aria-label="Next slide">{icon("arrow")}</button>'
        f'<div class="show-dots" id="show-dots">{dots}</div></section>')


def _social_proof(con, s) -> str:
    sub = (f'<p class="proof-sub">{esc(s["sub"])}</p>' if s.get("sub") else "")
    return (f'<section class="proof"><p class="proof-line">'
            f'<b>{esc(s["figure"])}</b> {esc(s["label"])}</p>{sub}</section>')


def _benefits(con, s) -> str:
    cells = "".join(
        f'<div class="benefit">{icon(i.get("icon"))}'
        f'<b>{esc(i.get("value"))}</b><span>{esc(i.get("label"))}</span></div>'
        for i in (s.get("items") or []))
    return (f'<section class="benefits"><div class="benefits-row">{cells}'
            f'</div></section>')


def _product_grid(con, s) -> str:
    search = (f'<span class="search-wrap">{icon("search")}'
              f'<input id="search-input" type="search" placeholder="Search"'
              f' aria-label="Search products"></span>'
              if s.get("show_search") else "")
    tabs = ('<div class="collection-tabs" id="collection-tabs"'
            ' role="group" aria-label="Filter products"></div>'
            if s.get("show_tabs") else "")
    return (f'<section class="section" id="shop">'
            f'<div class="shop-head"><h2>{esc(s["heading"])}</h2>{search}</div>'
            f'{tabs}<div class="grid" id="product-grid"'
            f' data-collection="{esc(s.get("collection_id") or "")}"'
            f' data-limit="{int(s.get("limit") or 0)}"></div></section>')


def _rich_text(con, s) -> str:
    align = "center" if s.get("align") == "center" else "left"
    body = esc(s["body"]).replace("\n\n", "</p><p>").replace("\n", "<br>")
    return (f'<section class="section" style="text-align:{align}">'
            f'<h2>{esc(s["heading"])}</h2><p class="big">{body}</p></section>')


def _feature_columns(con, s) -> str:
    cards = "".join(
        f'<div class="story-card"><span class="ico-wrap">'
        f'{icon(i.get("icon"), "ico ico-lg")}</span>'
        f'<b>{esc(i.get("title"))}</b><p>{esc(i.get("text"))}</p></div>'
        for i in (s.get("items") or []))
    return (f'<section class="section story"><h2>{esc(s["heading"])}</h2>'
            f'<div class="story-grid">{cards}</div></section>')


def _image_banner(con, s) -> str:
    img = _media_url(con, s.get("media_id"))
    h = {"short": "220px", "medium": "360px", "tall": "540px"}.get(
        s.get("height", "medium"), "360px")
    inner = ""
    if s.get("heading") or s.get("text"):
        inner = (f'<div class="banner-copy"><h2>{esc(s["heading"])}</h2>'
                 f'<p>{esc(s["text"])}</p></div>')
    body = (f'<div class="image-banner" style="height:{h};'
            f'background-image:linear-gradient(rgba(40,0,70,.28),'
            f'rgba(40,0,70,.28)),url({img});">{inner}</div>'
            if img else
            f'<div class="image-banner placeholder" style="height:{h}">'
            f'{inner or "<p>Pick an image in the editor</p>"}</div>')
    if s.get("link"):
        body = f'<a href="{esc(s["link"])}">{body}</a>'
    return f'<section class="section">{body}</section>'


def _video(con, s) -> str:
    head = f'<h2>{esc(s["heading"])}</h2>' if s.get("heading") else ""
    if s.get("video_url"):
        player = (f'<iframe src="{esc(s["video_url"])}" allowfullscreen'
                  f' allow="autoplay; encrypted-media"></iframe>')
    elif s.get("media_id"):
        player = (f'<video src="{_media_url(con, s["media_id"])}" controls'
                  f' playsinline></video>')
    else:
        player = '<p class="dim">Add an embed URL or upload a video.</p>'
    return (f'<section class="section">{head}'
            f'<div class="video-wrap">{player}</div></section>')


def _reviews(con, s) -> str:
    lim = max(1, int(s.get("limit") or 6))
    rows = con.execute(
        "SELECT r.name, r.rating, r.body, r.verified, p.name pname"
        " FROM product_reviews r JOIN products p ON p.id=r.product_id"
        # Only products still on sale. A retired line keeps its reviews in
        # the table — correct for the record, wrong on the shelf, where a
        # tea brand ended up quoting praise for a discontinued hot sauce.
        " WHERE r.approved=1 AND p.active=1"
        " ORDER BY r.id DESC LIMIT ?", (lim,)).fetchall()
    verified = (f'<span class="dim">{icon("check", "ico ico-sm")}'
                f' verified buyer</span>')
    if rows:
        cards = "".join(
            f'<div class="review-card"><span class="stars">'
            f'{icon("star") * r["rating"]}</span>'
            f'{verified if r["verified"] else ""}'
            f'<p>&ldquo;{esc(r["body"])}&rdquo;</p>'
            f'<span class="who">{esc(r["name"])} · {esc(r["pname"])}</span>'
            f'</div>' for r in rows)
    else:
        cards = (f'<div class="review-card"><span class="stars">'
                 f'{icon("star") * 5}</span>'
                 f'<p>Reviews appear here as customers post them.</p>'
                 f'<span class="who">Awaiting your first review</span></div>')
    # A wall of praise with no way to add to it is a dead end. The button
    # asks which product first — this section is the whole range, so it
    # cannot know on its own.
    return (f'<section class="section" id="reviews">'
            f'<div class="pp-rev-head"><h2>{esc(s["heading"])}</h2>'
            f'<button class="btn-pill ghost sm" id="write-review">'
            f'{icon("star", "ico ico-sm")} Write a review</button></div>'
            f'<div class="grid">{cards}</div></section>')


def _faq(con, s) -> str:
    items = "".join(
        f'<details><summary>{esc(i.get("q"))}</summary>'
        f'<p>{esc(i.get("a"))}</p></details>'
        for i in (s.get("items") or []))
    return (f'<section class="section" id="faq"><h2>{esc(s["heading"])}</h2>'
            f'{items}</section>')


def _newsletter(con, s) -> str:
    return (f'<section class="section rewards" id="rewards">'
            f'<div class="rewards-card"><h2>{esc(s["heading"])}</h2>'
            f'<p>{esc(s["body"])}</p>'
            f'<form id="subscribe-form">'
            f'<input type="email" id="subscribe-email"'
            f' placeholder="you@example.com" required>'
            f'<button class="btn-pill primary" type="submit">'
            f'{esc(s["cta_text"])}</button></form>'
            f'<p class="dim" id="subscribe-msg"></p></div></section>')


def _social(con, s) -> str:
    cards = "".join(
        f'<a class="social-card" href="{esc(i.get("link") or "#")}">'
        f'{icon(i.get("icon"), "ico ico-lg")}<b>{esc(i.get("handle"))}</b>'
        f'<span>{esc(i.get("network"))}</span></a>'
        for i in (s.get("items") or []))
    return (f'<section class="section social"><h2>{esc(s["heading"])}</h2>'
            f'<div class="social-row">{cards}</div></section>')


def _custom_html(con, s, liquid_renderer=None) -> str:
    css = f'<style>{s.get("css") or ""}</style>' if s.get("css") else ""
    js = f'<script>{s.get("js") or ""}</script>' if s.get("js") else ""
    liq = ""
    if s.get("liquid") and liquid_renderer:
        liq = liquid_renderer(s["liquid"], con)
    return (f'<section class="section custom">{css}'
            f'{s.get("html") or ""}{liq}{js}</section>')


def _spacer(con, s) -> str:
    return f'<div style="height:{int(s.get("height") or 40)}px"></div>'


def _latest_posts(con, s) -> str:
    lim = max(1, int(s.get("limit") or 3))
    try:
        rows = con.execute(
            "SELECT slug, title, excerpt, media_id, author FROM blog_posts"
            " WHERE published=1 ORDER BY published_at DESC LIMIT ?",
            (lim,)).fetchall()
    except Exception:
        rows = []
    if not rows:
        return (f'<section class="section"><h2>{esc(s["heading"])}</h2>'
                f'<p class="dim">No posts yet — write one in '
                f'Store admin → Blog.</p></section>')
    cards = "".join(
        f'<a class="post-card" href="/blog/{esc(p["slug"])}">'
        + (f'<div class="post-art"><img src="/media/m/{p["media_id"]}/thumb"'
           f' alt="" loading="lazy"></div>' if p["media_id"] else "")
        + f'<div class="post-body"><b>{esc(p["title"])}</b>'
        f'<p class="dim">{esc(p["excerpt"])}</p></div></a>' for p in rows)
    return (f'<section class="section"><h2>{esc(s["heading"])}</h2>'
            f'<div class="post-grid">{cards}</div>'
            f'<p><a class="btn-pill ghost" href="/blog">Read the journal</a></p>'
            f'</section>')


RENDERERS = {
    "showcase": _showcase, "social_proof": _social_proof,
    "hero": _hero, "benefits": _benefits,
    "product_grid": _product_grid, "rich_text": _rich_text,
    "feature_columns": _feature_columns, "image_banner": _image_banner,
    "video": _video, "reviews": _reviews, "faq": _faq,
    "newsletter": _newsletter, "social": _social, "spacer": _spacer,
    "latest_posts": _latest_posts,
}


def render_page(con, rows, liquid_renderer=None) -> str:
    """Render enabled sections in order. One bad section renders an inline
    notice rather than taking down the whole page."""
    out = []
    for row in rows:
        if not row["enabled"]:
            continue
        s = _settings(row)
        try:
            if row["type"] == "custom_html":
                out.append(_custom_html(con, s, liquid_renderer))
            else:
                fn = RENDERERS.get(row["type"])
                out.append(fn(con, s) if fn else "")
        except Exception as e:
            out.append(f'<section class="section"><p class="dim">'
                       f'Section “{esc(row["type"])}” could not render: '
                       f'{esc(e)}</p></section>')
    return "\n".join(out)


# The storefront home page as shipped — seeded once so merchants start from
# the designed layout instead of a blank canvas.
# Order is a selling argument: hook, proof, product, then the softer story.
# The benefit strip sits directly under the hero because the numbers (200mg,
# 15 cal, 2g sugar) are what qualify a functional drink for the shopper.
HOME_DEFAULT = ["showcase", "social_proof", "benefits", "product_grid",
                "feature_columns",
                "reviews", "social", "newsletter", "faq"]
