"""Blog, navigation menus, URL redirects, translations and currencies.

The growth surface: content that earns organic traffic, navigation the
merchant controls, redirects so migrating a store doesn't break inbound
links, and a translation/currency layer so the same storefront can serve
more than one market.
"""
import html as _html
import contextvars
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from erp.backend import db
from .api import (admin_user, get_con, get_theme, page_rows, rate_limit,
                  render_shell, slugify)
from . import sections as sect

router = APIRouter()

TABLES = """
CREATE TABLE IF NOT EXISTS blog_posts (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  excerpt TEXT DEFAULT '',
  body TEXT DEFAULT '',                    -- simple HTML
  media_id INTEGER,
  author TEXT DEFAULT '',
  tags TEXT DEFAULT '',
  published INTEGER DEFAULT 1,
  published_at REAL NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS store_menus (
  id INTEGER PRIMARY KEY,
  location TEXT NOT NULL DEFAULT 'header', -- header|footer
  label TEXT NOT NULL,
  url TEXT NOT NULL,
  position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS store_redirects (
  id INTEGER PRIMARY KEY,
  from_path TEXT UNIQUE NOT NULL,
  to_path TEXT NOT NULL,
  code INTEGER DEFAULT 301,
  hits INTEGER DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS translations (
  locale TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (locale, key)
);
"""

# UI strings the storefront can translate. Product copy uses generated keys
# ("product:12:name"), so merchants translate catalog text the same way.
UI_KEYS = {
    "shop": "Shop", "reviews": "Reviews", "faq": "FAQ",
    "cart": "Your cart", "checkout": "Checkout →", "add_to_cart": "Add to cart",
    "search": "Search…", "account": "My account", "track": "Track my order",
    "support": "Support", "empty_cart": "Your cart is empty",
    "discount_code": "Discount code", "apply": "Apply", "total": "Total",
    "free_shipping_at": "free shipping at $40", "sold_out": "Sold out",
    # The shop's own invitation. It was "Shop your Zen", in the shared
    # storefront script, on every tenant's side menu and empty cart.
    "shop_cta": "Shop the range",
    # The first-visit offer's headline. It was "Take 10% off your first
    # calm." — in the shell, for every tenant.
    "offer_title": "Take 10% off your first order.",
    # A plan's button. "Add" is wrong for something that bills every month.
    "start_plan": "Start", "plans_heading": "Your plans",
    "no_plans": "Nothing running yet.",
    # The line over the cart. It was "breathe in, check out." — one brand's
    # breathing exercise in everyone's drawer.
    "cart_tag": "",
    # Under the checkout button. Shipped with an invented shipping policy
    # and box language; a policy line belongs to the tenant that has the
    # policy.
    "cart_note": "",
}

# The shell's own chrome — header buttons, the side menu — was raw
# literals in index.html and never reached t(). These keys carry them,
# applied to data-i18n attributes at boot, so a Spanish visitor's menu is
# in Spanish and not only the product cards.
UI_KEYS.update({
    "nav_account": "My account", "nav_track": "Track my order",
    "nav_support": "Support", "nav_menu": "Menu",
    "side_learn": "Learn with us", "side_learning": "Learning",
    "side_learning_sub": "Your courses, lessons, quizzes and people",
    "side_nutrition": "Nutrition",
    "side_nutrition_sub": "Plan, prep and track — coach optional",
    "side_find": "Come find us", "side_stores": "Find a store",
    "side_stores_sub": "Shops that carry the range", "side_events": "Events",
    "side_events_sub": "Tastings, pop-ups and markets",
    "side_work": "Work with us", "side_account": "Your account",
    "side_signin": "Sign in", "side_signin_sub": "Customers and team — one door",
    "side_track": "Track an order", "side_track_sub": "Where your order is right now",
    "side_support": "Support",
    "side_support_sub": "Real humans, same system the team runs on",
    "side_a11y": "Accessibility & language",
    "side_a11y_sub": "Text size, contrast, region and currency",
    "close": "Close", "back": "Back", "continue": "Continue", "cancel": "Cancel",
    "quantity": "Quantity", "subtotal": "Subtotal", "shipping": "Shipping",
    "tax": "Tax", "order_placed": "Order placed", "sign_out": "Sign out",
})

# What the shop writes to a customer. Placeholders in braces are filled
# by the sender; a translation keeps them. The money in an email is the
# base currency, formatted for the language, because a receipt in
# Spanish with "$1,234.56" in it is half translated.
UI_KEYS.update({
    "email_receipt_subject": "Your order #{oid} is in!",
    "email_receipt_thanks": "Thanks {name}!",
    "email_discount": "Discount {code}", "email_tax": "Tax",
    "email_shipping": "Shipping", "email_total": "Total",
    "email_track": "Track any time: {url}  →  order #{oid}",
    "email_shipped_subject": "Order #{oid} is on its way",
    "email_delivered_subject": "Order #{oid} has arrived",
    "email_hi": "Hi {name},",
    "email_shipped_line": "Your order #{oid} is on its way.",
    "email_delivered_line": "Your order #{oid} has arrived.",
    "email_track_it": "Track it: {url}  →  order #{oid}",
})


# The language this request is being served in. Set by a middleware from
# the sf_locale cookie (which the page writes when it resolves a
# language) or ?lang=, so what the server renders — the menu, the
# sections, a page — is in the visitor's language and not swapped after
# the fact. Empty means the base language.
LOCALE_CTX: contextvars.ContextVar = contextvars.ContextVar("sf_locale", default="")


def current_locale() -> str:
    return LOCALE_CTX.get() or ""


def tx(con, key: str, fallback: str, locale: str | None = None) -> str:
    """One string in the current language: the merchant's translation,
    else the shipped one, else what was passed."""
    loc = (locale if locale is not None else current_locale()).lower()
    if not loc or loc == "en":
        return fallback
    v = translations_for(con, loc).get(key)
    return v if v else fallback


def translate_settings(con, prefix: str, settings: dict, locale: str | None = None) -> dict:
    """A section's settings with every string a translation exists for
    swapped, keyed `section:<id>:<field>`. Lists of dicts (columns,
    questions) are keyed by index too, so a three-column feature strip
    translates column by column."""
    loc = (locale if locale is not None else current_locale()).lower()
    if not loc or loc == "en":
        return settings
    tr = translations_for(con, loc)
    if not tr:
        return settings

    def walk(node, key):
        if isinstance(node, str):
            v = tr.get(key)
            return v if v else node
        if isinstance(node, dict):
            return {k: walk(v, f"{key}:{k}") for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, f"{key}:{i}") for i, v in enumerate(node)]
        return node
    return walk(settings, prefix)


# The merchant's content, as keys: what the translations screen lists
# beside the interface's own words and what a machine fill translates.
# Products by id, menus by id, product kinds by id, pages by slug,
# sections by id and field — every string a visitor reads that came out
# of this database rather than out of the code.
CONTENT_SKIP = {"url", "href", "image", "img", "src", "link", "video", "color",
                "colour", "icon", "anchor", "id", "slug", "align", "layout",
                "product_ids", "collection", "kind", "handle", "class", "style",
                "type", "variant", "size", "width", "height", "position",
                "css", "js", "bg", "background", "font", "theme", "mode"}


def _walk_strings(node, key, out):
    if isinstance(node, str):
        last = key.rsplit(":", 1)[-1]
        if (node.strip() and last not in CONTENT_SKIP
                and not node.startswith(("http", "/", "#", "data:")) and len(node) <= 4000):
            out[key] = node
    elif isinstance(node, dict):
        for k, v in node.items():
            _walk_strings(v, f"{key}:{k}", out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_strings(v, f"{key}:{i}", out)


def content_keys(con) -> dict:
    keys: dict = {}
    for r in con.execute("SELECT id, name, description FROM products WHERE active=1").fetchall():
        keys[f"product:{r['id']}:name"] = r["name"]
        if r["description"]:
            keys[f"product:{r['id']}:description"] = r["description"]
    try:
        for r in con.execute("SELECT id, name FROM collections").fetchall():
            if r["name"]:
                keys[f"collection:{r['id']}:name"] = r["name"]
    except Exception:                                        # noqa: BLE001
        pass
    for r in con.execute("SELECT id, label FROM store_menus ORDER BY location, position").fetchall():
        if r["label"]:
            keys[f"menu:{r['id']}:label"] = r["label"]
    try:
        from .api import PRODUCT_KINDS
        for k in PRODUCT_KINDS:
            keys[f"kind:{k['id']}:label"] = k["label"]
            if k.get("note"):
                keys[f"kind:{k['id']}:note"] = k["note"]
    except Exception:                                        # noqa: BLE001
        pass
    try:
        from .api import get_theme
        for i, a in enumerate(get_theme(con).get("announce") or []):
            if str(a).strip():
                keys[f"announce:{i}"] = str(a)
    except Exception:                                        # noqa: BLE001
        pass
    for r in con.execute("SELECT slug, title, content_html FROM store_pages"
                         " WHERE published=1").fetchall():
        if r["title"]:
            keys[f"page:{r['slug']}:title"] = r["title"]
        if r["content_html"] and len(r["content_html"]) <= 20000:
            keys[f"page:{r['slug']}:html"] = r["content_html"]
    for r in con.execute("SELECT id, settings FROM page_sections WHERE enabled=1").fetchall():
        try:
            st = json.loads(r["settings"] or "{}")
        except ValueError:
            continue
        _walk_strings(st, f"section:{r['id']}", keys)
    return keys


# ---------- machine translation ----------
# An engine the merchant connects, used for one thing: filling what is
# missing in a language so a shop with two hundred products speaks it
# this afternoon rather than after a fortnight of typing. What it writes
# is marked as the machine's, shown as such on the translations screen,
# and overwritten the moment somebody types the real thing. The
# interface's own words are never sent — those shipped translated.
MT_ENGINES = {
    "argos": {"label": "Argos Translate (in this process, no server, no key)", "url": "",
              "hint": "The open-source engine under LibreTranslate, run inside this install: "
                      "pip install argostranslate, then each language's model (about 100 MB) "
                      "downloads itself the first time it is asked for. Offline after that. "
                      "Batched through CTranslate2: a whole shop in about a minute a language "
                      "on a ten-year-old laptop, seconds on a server. About forty languages, "
                      "all through English; a first pass to read over — its traditional "
                      "Chinese model loops and is best left to an LLM engine. Tags and "
                      "placeholders are kept out of its reach and put back."},
    "nllb": {"label": "NLLB (Meta's 200-language model, in this process)", "url": "",
             "hint": "pip install transformers torch sentencepiece; the model (about 2.5 GB, "
                     "facebook/nllb-200-distilled-600M) downloads on first use. Slow on a "
                     "laptop CPU, fine on a server, and speaks two hundred languages offline."},
    "libretranslate": {"label": "LibreTranslate (this node's, or yours)", "url": "",
                       "hint": "Blank uses the machine's shared translate service "
                               "(scripts/install_translate.sh) or the tenant's "
                               "translate_url; else the address of a LibreTranslate "
                               "server and a key if it asks for one. About thirty "
                               "languages, fully offline."},
    "deepl": {"label": "DeepL", "url": "https://api-free.deepl.com/v2/translate",
              "hint": "A DeepL API key; the free tier translates 500,000 characters a "
                      "month. A paid key uses api.deepl.com — set the address too. "
                      "About thirty languages."},
    "openai": {"label": "An LLM (OpenAI-compatible API)", "url": "https://api.openai.com/v1",
               "hint": "Any OpenAI-compatible chat endpoint — OpenAI, a local Ollama, "
                       "a gateway — with a key and a model name. Every language."},
    "anthropic": {"label": "Claude (Anthropic API)", "url": "https://api.anthropic.com",
                  "hint": "An Anthropic API key and a model name. Every language."},
}
LLM_PROMPT = (
    "You translate a shop's interface and content from English into {lang}. "
    "Return ONLY a JSON array of strings, one per input, same order, same length. "
    "Keep every placeholder in braces like {{name}} or {{oid}} exactly as it is, keep "
    "every HTML tag and attribute exactly as it is and translate only the text "
    "between tags, keep numbers, prices, product codes and the | separator, and "
    "use the natural wording a native shop would use rather than a literal one."
)


def _placeholders(text: str) -> list:
    """What must survive a translation untouched: {braces}, HTML tags."""
    return sorted(re.findall(r"\{[a-z_]+\}", text)) + sorted(
        t.lower() for t in re.findall(r"</?[a-zA-Z][a-zA-Z0-9]*", text))


def _degenerate(out: str) -> bool:
    """A small model sometimes falls into a loop and emits one character
    or one word over and over. That is not a translation and is not
    kept: more than half of a longish answer being one repeated
    character, or one word repeated four times in a row, is the sign."""
    text = re.sub(r"<[^<>]+>|\{[a-z_]+\}", "", out).strip()
    if len(text) >= 12:
        top = max(text.count(ch) for ch in set(text) if not ch.isspace()) if text.strip() else 0
        if top / max(1, len(text.replace(" ", ""))) > 0.5:
            return True
    return bool(re.search(r"(\b\w+\b)(?:\s+\1\b){3,}", text))


def _intact(src: str, out: str) -> bool:
    """A machine answer is kept only if it kept the placeholders and the
    tags the source had. A receipt with {oid} gone is not a translation."""
    return _placeholders(src) == _placeholders(out)


def mt_settings(con) -> dict:
    cfg = _mt_cfg(con)
    node = ""
    try:
        from erp.backend import lookup as _lk
        from erp.backend.main import CFG as _CFG
        node = _lk._translate_endpoint(_CFG)[2]
    except Exception:                                        # noqa: BLE001
        pass
    return {"engine": cfg.get("engine", ""), "url": cfg.get("url", ""),
            "model": cfg.get("model", ""), "has_key": bool(cfg.get("key")),
            "node_translate": node,
            "engines": [{"id": k, **v} for k, v in MT_ENGINES.items()],
            "languages": [language_entry(c) for c, _ in LANGUAGES]}


def _mt_cfg(con) -> dict:
    row = con.execute("SELECT v FROM store_meta WHERE k='mt'").fetchone()
    try:
        return json.loads(row["v"]) if row else {}
    except ValueError:
        return {}


# Argos and NLLB run inside this process. A model is a few hundred
# megabytes to a few gigabytes, so it is loaded once and kept; the
# first request for a language pays for the download, later ones do not.
_ARGOS_READY: set = set()
_NLLB: dict = {}
NLLB_CODES = {
    "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn", "pt": "por_Latn", "it": "ita_Latn",
    "nl": "nld_Latn", "sv": "swe_Latn", "da": "dan_Latn", "nb": "nob_Latn", "fi": "fin_Latn",
    "pl": "pol_Latn", "cs": "ces_Latn", "sk": "slk_Latn", "hu": "hun_Latn", "ro": "ron_Latn",
    "bg": "bul_Cyrl", "el": "ell_Grek", "tr": "tur_Latn", "ru": "rus_Cyrl", "uk": "ukr_Cyrl",
    "he": "heb_Hebr", "ar": "arb_Arab", "fa": "pes_Arab", "hi": "hin_Deva", "bn": "ben_Beng",
    "ur": "urd_Arab", "ta": "tam_Taml", "te": "tel_Telu", "mr": "mar_Deva", "id": "ind_Latn",
    "ms": "zsm_Latn", "vi": "vie_Latn", "th": "tha_Thai", "ko": "kor_Hang", "ja": "jpn_Jpan",
    "zh": "zho_Hans", "zh-tw": "zho_Hant", "sw": "swh_Latn", "tl": "tgl_Latn", "en": "eng_Latn",
}


_TOKEN = re.compile(r"(<[^<>]+>|\{[a-z_]+\}|&[a-z]+;|&#\d+;)")


def _translate_guarded(translate_one, texts: list) -> list:
    """Run a plain-text engine over strings that carry HTML tags and
    {placeholders} without letting it see either. Each string is cut at
    every tag, entity and placeholder; only the prose between them goes
    to the engine; the pieces are put back exactly where they were.
    That is how a statistical engine that would otherwise eat <b> and
    {oid} gets to translate a receipt and a table."""
    out = []
    for text in texts:
        parts = _TOKEN.split(text)
        built = []
        for i, part in enumerate(parts):
            if i % 2 == 1 or not part.strip():
                built.append(part)
                continue
            lead = part[:len(part) - len(part.lstrip())]
            trail = part[len(part.rstrip()):]
            built.append(lead + translate_one(part.strip()) + trail)
        out.append("".join(built))
    return out


def _argos(texts: list, target: str) -> list:
    import os
    # Stanza, the sentence splitter Argos reaches for by default, is a
    # PyTorch model that took minutes per sentence on a laptop; the
    # light splitter is a fraction of a second. Set before the import,
    # and only when the operator has not chosen otherwise.
    os.environ.setdefault("ARGOS_CHUNK_TYPE", "MINISBD")
    os.environ.setdefault("ARGOS_STANZA_AVAILABLE", "0")
    try:
        import argostranslate.package as P
        import argostranslate.translate as T
    except ImportError as e:
        raise HTTPException(400, "Argos Translate is not installed: pip install "
                                 "argostranslate, then try again") from e
    lang = target.split("-")[0]
    if lang == "zh-tw" or target.lower() == "zh-tw":
        lang = "zt"
    if lang not in _ARGOS_READY:
        have = {(p.from_code, p.to_code) for p in P.get_installed_packages()}
        if ("en", lang) not in have:
            P.update_package_index()
            pk = next((p for p in P.get_available_packages()
                       if p.from_code == "en" and p.to_code == lang), None)
            if pk is None:
                raise HTTPException(400, f"Argos has no English → {target} model; use an "
                                         "LLM engine or NLLB for this language")
            P.install_from_path(pk.download())
        _ARGOS_READY.add(lang)
    fast = _argos_fast(lang)
    if fast is not None:
        return _translate_guarded(fast, texts)
    return _translate_guarded(lambda t: T.translate(t, "en", lang), texts)


_CT2: dict = {}
_SENT = re.compile(r"(?<=[.!?。！？])\s+")


def _argos_fast(lang: str):
    """Argos's own model, driven through CTranslate2 directly: a whole
    batch of sentences in one pass, int8 on the CPU, beam of two. Ten
    times what one string at a time gives. Returns a callable that
    translates one string (its sentences batched), or None when the
    package layout is not what is expected — then Argos's own call is
    used, slower but right."""
    if lang in _CT2:
        return _CT2[lang]
    try:
        import ctranslate2
        import sentencepiece as spm
        import argostranslate.package as P
        pkg = next(p for p in P.get_installed_packages()
                   if p.from_code == "en" and p.to_code == lang)
        root = pathlib.Path(pkg.package_path)
        sp = spm.SentencePieceProcessor(model_file=str(root / "sentencepiece.model"))
        tr = ctranslate2.Translator(str(root / "model"), device="cpu",
                                    compute_type="int8", inter_threads=1, intra_threads=0)
    except Exception:                                        # noqa: BLE001
        _CT2[lang] = None
        return None

    def one(text: str) -> str:
        sents = [x for x in _SENT.split(text) if x.strip()] or [text]
        toks = [sp.encode(x, out_type=str) for x in sents]
        res = tr.translate_batch(toks, beam_size=2, max_batch_size=32,
                                 max_decoding_length=512)
        return _join_pieces([sp.decode(r.hypotheses[0]) for r in res], lang)
    _CT2[lang] = one
    return one


NO_SPACE_LANGS = {"zh", "zt", "ja", "th"}


def _join_pieces(pieces: list, lang: str) -> str:
    """Decoded sentences back into one string. SentencePiece's word
    marker sometimes survives decoding at the front of a piece and is
    not a character anyone wants; languages written without spaces
    are joined without one."""
    clean = [p.replace("\u2581", " ").strip() for p in pieces]
    clean = [p for p in clean if p]
    return ("" if lang in NO_SPACE_LANGS else " ").join(clean)


def translate_batch_fast(texts: list, lang: str) -> list:
    """Many strings at once through the batched path: every sentence of
    every string in one CTranslate2 call, then reassembled. What the
    fill uses when Argos is the engine and the model is on disk."""
    fast = _argos_fast(lang)
    if fast is None:
        return None
    import sentencepiece  # noqa: F401  (present if fast is)
    return _translate_guarded(fast, texts)


def _nllb(texts: list, target: str) -> list:
    code = NLLB_CODES.get(target.lower()) or NLLB_CODES.get(target.split("-")[0])
    if not code:
        raise HTTPException(400, f"NLLB has no code for {target} here")
    try:
        if not _NLLB:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            name = "facebook/nllb-200-distilled-600M"
            _NLLB["tok"] = AutoTokenizer.from_pretrained(name, src_lang="eng_Latn")
            _NLLB["model"] = AutoModelForSeq2SeqLM.from_pretrained(name)
    except ImportError as e:
        raise HTTPException(400, "NLLB needs pip install transformers torch sentencepiece") from e
    tok, model = _NLLB["tok"], _NLLB["model"]

    def one(t: str) -> str:
        enc = tok(t, return_tensors="pt", truncation=True, max_length=1024)
        gen = model.generate(**enc, forced_bos_token_id=tok.convert_tokens_to_ids(code),
                             max_length=1024)
        return tok.batch_decode(gen, skip_special_tokens=True)[0]
    return _translate_guarded(one, texts)


def _mt_call(engine: str, cfg: dict, texts: list, target: str, html: bool = False) -> list:
    """The one place a translator is spoken to. Tests replace it."""
    lang = target.split("-")[0]
    if engine == "argos":
        return _argos(texts, target)
    if engine == "nllb":
        return _nllb(texts, target)
    if engine == "deepl":
        url = cfg.get("url") or MT_ENGINES["deepl"]["url"]
        dl = {"zh": "ZH", "nb": "NB", "pt": "PT-BR"}.get(lang, lang.upper())
        if target.lower() == "zh-tw":
            dl = "ZH-HANT"
        data = urllib.parse.urlencode(
            [("text", t) for t in texts] + [("target_lang", dl), ("source_lang", "EN")]
            + ([("tag_handling", "html")] if html else [])).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"DeepL-Auth-Key {cfg.get('key', '')}",
            "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read().decode())
        return [x["text"] for x in out.get("translations", [])]
    if engine == "libretranslate":
        base, key = (cfg.get("url") or "").rstrip("/"), cfg.get("key", "")
        if not base:
            try:
                from erp.backend import lookup as _lk
                from erp.backend.main import CFG as _CFG
                base, key, _ = _lk._translate_endpoint(_CFG)
                base = base.rstrip("/")
            except Exception:                                # noqa: BLE001
                base = ""
        if not base:
            raise HTTPException(400, "LibreTranslate needs a server: set its address, or "
                                     "install the node's translate service")
        body = {"q": texts, "source": "en", "target": "zt" if target.lower() == "zh-tw" else lang,
                "format": "html" if html else "text"}
        if key:
            body["api_key"] = key
        req = urllib.request.Request(base + "/translate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
        t = out.get("translatedText")
        return t if isinstance(t, list) else [t]
    if engine in ("openai", "anthropic"):
        name = LANGUAGE_LABEL.get(target.lower(), target)
        system = LLM_PROMPT.format(lang=f"{name} ({target})")
        user = json.dumps(texts, ensure_ascii=False)
        if engine == "openai":
            base = (cfg.get("url") or MT_ENGINES["openai"]["url"]).rstrip("/")
            body = {"model": cfg.get("model") or "gpt-4o-mini", "temperature": 0,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}]}
            req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {cfg.get('key', '')}"})
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.loads(r.read().decode())
            text = out["choices"][0]["message"]["content"]
        else:
            base = (cfg.get("url") or MT_ENGINES["anthropic"]["url"]).rstrip("/")
            body = {"model": cfg.get("model") or "claude-sonnet-5", "max_tokens": 8000,
                    "temperature": 0, "system": system,
                    "messages": [{"role": "user", "content": user}]}
            req = urllib.request.Request(base + "/v1/messages", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "x-api-key": cfg.get("key", ""),
                                                  "anthropic-version": "2023-06-01"})
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.loads(r.read().decode())
            text = "".join(b.get("text", "") for b in out.get("content", []))
        m = re.search(r"\[.*\]", text, re.S)
        arr = json.loads(m.group(0) if m else text)
        if not isinstance(arr, list) or len(arr) != len(texts):
            raise ValueError("the model did not return one translation per string")
        return [str(x) for x in arr]
    raise HTTPException(400, "no translation engine is connected")


def _chunks(keys: list, want: dict, *, budget: int = 6000, most: int = 40) -> list:
    """Batches sized by characters, not by count: forty short labels go
    together, one long page goes alone."""
    out, cur, size = [], [], 0
    for k in keys:
        n = len(want[k])
        if cur and (size + n > budget or len(cur) >= most):
            out.append(cur); cur, size = [], 0
        cur.append(k); size += n
    if cur:
        out.append(cur)
    return out


def fill_locale(con, locale: str, *, limit: int = 2000, force_machine: bool = False,
                include_ui: bool = True, dry_run: bool = False) -> dict:
    """Translate, by machine, everything this language lacks.

    The algorithm, so it can be run for forty languages without thought:
    what is wanted is every key — the interface's own words and the
    merchant's content — minus what already has a translation; a shipped
    translation counts, a typed one always counts, a machine one counts
    unless `force_machine` asks for a fresh pass. What is wanted goes to
    the engine in batches sized by characters, HTML apart from text; an
    answer that lost a placeholder or a tag is dropped rather than kept;
    what survives is written as the machine's. Run again, it sends only
    what is still missing, so a crash halfway costs nothing.
    """
    cfg = _mt_cfg(con)
    if cfg.get("engine") not in MT_ENGINES:
        raise HTTPException(400, "connect a translation engine first — Store admin → Languages")
    loc = locale.strip().lower()
    if not loc or loc == "en":
        raise HTTPException(400, "pick a language other than the base 'en'")
    own_src = {r["key"]: (r["source"] or "typed") for r in con.execute(
        "SELECT key, source FROM translations WHERE locale=?", (loc,)).fetchall()}
    have = translations_for(con, loc)
    base = dict(content_keys(con))
    if include_ui:
        # The interface's words are sent only when nothing shipped for
        # this language; the six shipped ones never go out.
        shipped = BUILTIN.get(loc) or BUILTIN.get(loc.split("-")[0], {})
        for k, v in ui_strings(con).items():
            if k not in shipped and v.strip():
                base[k] = v
    want = {k: v for k, v in base.items()
            if k not in have or (force_machine and own_src.get(k) == "machine")}
    keys = list(want)[:limit]
    if dry_run:
        return {"ok": True, "locale": loc, "would_send": len(keys),
                "characters": sum(len(want[k]) for k in keys), "dry_run": True}
    done = dropped = 0
    for html in (False, True):
        batch = [k for k in keys if k.endswith(":html") == html]
        for chunk in _chunks(batch, want):
            try:
                out = _mt_call(cfg["engine"], cfg, [want[k] for k in chunk], loc, html=html)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
                con.commit()
                raise HTTPException(502, f"the translation engine did not answer: {e}") from e
            for k, v in zip(chunk, out):
                v = str(v or "").strip()
                if not v or not _intact(want[k], v) or _degenerate(v):
                    dropped += 1
                    if own_src.get(k) == "machine":
                        # A fresh pass that cannot do better than the
                        # machine's old row does not leave the old row:
                        # it was the same engine's answer, and missing
                        # reads as English while junk reads as junk.
                        con.execute("DELETE FROM translations WHERE locale=? AND key=?"
                                    " AND source='machine'", (loc, k))
                    continue
                con.execute(
                    "INSERT INTO translations(locale,key,value,source) VALUES(?,?,?,'machine')"
                    " ON CONFLICT(locale,key) DO UPDATE SET value=excluded.value,"
                    " source='machine'", (loc, k, v))
                done += 1
            con.commit()
    return {"ok": True, "locale": loc, "filled": done, "dropped": dropped,
            "remaining": max(0, len(want) - done)}


def fill_many(con, locales: list, **kw) -> dict:
    """The same, for a list of languages, each reported on its own line;
    one engine failure stops the run and says which language it was on."""
    report = []
    for loc in locales:
        if loc == "en":
            continue
        try:
            r = fill_locale(con, loc, **kw)
        except HTTPException as e:
            report.append({"locale": loc, "error": e.detail})
            break
        report.append(r)
    return {"ok": all("error" not in r for r in report), "languages": report}


def offer_languages(con, codes: list, *, default: str | None = None) -> dict:
    """Add languages to what the shop offers, keeping what was there."""
    cur = i18n_settings(con)
    locs = list(cur["locales"])
    known = {l["code"] for l in locs}
    for c in codes:
        c = c.strip().lower()
        if c and c not in known:
            locs.append(language_entry(c)); known.add(c)
    con.execute("INSERT INTO store_meta(k,v) VALUES('i18n',?)"
                " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (json.dumps({"locales": locs, "default": default or cur["default"],
                             "auto_detect": cur["auto_detect"]}),))
    con.commit()
    return i18n_settings(con)


def strings_for(con, locale: str) -> dict:
    """The interface's words in one language: the shipped English, this
    tenant's overrides, then that locale's translations on top."""
    base = ui_strings(con)
    loc = (locale or "en").lower()
    if loc == "en" or loc not in locales(con):
        return base
    return {**base, **translations_for(con, loc)}


def fmt_money(con, cents: int, locale: str = "en") -> str:
    """The base currency, in the conventions of the language: 1.234,56 €
    for a German reader, $1,234.56 for an American one."""
    cur = (currencies(con) or CURRENCY_DEFAULT)[0]
    v = cents / 100
    loc = (locale or "en").lower().split("-")[0]
    if loc in ("de", "es", "it", "nl", "pt", "fr", "tr", "pl", "ru"):
        whole, frac = f"{abs(v):,.2f}".split(".")
        num = whole.replace(",", "\u00a0" if loc == "fr" else ".") + "," + frac
        sign = "-" if v < 0 else ""
        return f"{sign}{num}\u00a0{cur['symbol']}"
    return f"{'-' if v < 0 else ''}{cur['symbol']}{abs(v):,.2f}"


# The preferences panel, the cart, the checkout and the account, which
# were literals in the shell and the script.
UI_KEYS.update({
    "prefs": "Preferences", "prefs_saved": "Saved on this device.",
    "accessibility": "Accessibility", "text_size": "Text size",
    "high_contrast": "High contrast", "reduce_motion": "Reduce motion",
    "underline_links": "Underline links", "measurement_cookies": "Measurement cookies",
    "region_language": "Region & language", "region": "Region",
    "language": "Language", "currency": "Currency", "reset_all": "Reset all",
    "a11y_open": "Accessibility and language options",
    "empty_cart_line": "Your cart is empty.", "place_order": "Place order",
    "order_placed": "Order placed", "track_my_order": "Track my order",
    "sign_in": "Sign in", "create_account": "Create account",
    "my_account": "My account", "name": "Name", "email": "Email",
    "full_name": "Full name", "shipping_label": "Shipping",
    "payment": "Payment", "pay_on_delivery": "Pay on delivery",
    "menu": "Menu", "search_placeholder": "Search…", "checkout_title": "Checkout",
    "country": "Country", "address": "Address", "street_address": "Street address",
    "optional": "optional", "buy_now": "Buy now", "build_your_own": "Build your own",
    "build_your_own_note": "Pick the capabilities your business actually does and watch the "
                           "price add itself up — the same menu these are cut from, priced "
                           "from the same book.",
    "open_the_menu": "Open the menu", "all_products": "All products",
    "everything": "Everything", "the_case": "The case",
})

# Translations the product ships with, so a shop that offers Spanish
# speaks Spanish the day it is switched on, before anyone has typed a
# word. They cover the interface's own words — the chrome, the cart, the
# checkout, the account, the emails — never a merchant's products or
# pages, which are theirs to translate on the same screen. A merchant's
# own translation of any key wins over the shipped one.
BUILTIN_LOCALES = [
    {"code": "es", "label": "Español", "dir": "ltr"},
    {"code": "fr", "label": "Français", "dir": "ltr"},
    {"code": "de", "label": "Deutsch", "dir": "ltr"},
    {"code": "pt", "label": "Português", "dir": "ltr"},
    {"code": "zh", "label": "中文", "dir": "ltr"},
    {"code": "ar", "label": "العربية", "dir": "rtl"},
]
BUILTIN = {
 "es": {
  "shop": "Tienda", "reviews": "Opiniones", "faq": "Preguntas", "cart": "Tu carrito",
  "checkout": "Pagar →", "add_to_cart": "Añadir al carrito", "search": "Buscar…",
  "account": "Mi cuenta", "track": "Seguir mi pedido", "support": "Ayuda",
  "empty_cart": "Tu carrito está vacío", "discount_code": "Código de descuento",
  "apply": "Aplicar", "total": "Total", "free_shipping_at": "envío gratis desde $40",
  "sold_out": "Agotado", "shop_cta": "Ver la tienda",
  "offer_title": "10% de descuento en tu primer pedido.", "start_plan": "Empezar",
  "plans_heading": "Tus planes", "no_plans": "Nada activo todavía.",
  "nav_account": "Mi cuenta", "nav_track": "Seguir mi pedido", "nav_support": "Ayuda",
  "nav_menu": "Menú", "side_learn": "Aprende con nosotros", "side_learning": "Formación",
  "side_learning_sub": "Tus cursos, lecciones, pruebas y compañeros",
  "side_nutrition": "Nutrición", "side_nutrition_sub": "Planifica, prepara y registra — con o sin coach",
  "side_find": "Ven a vernos", "side_stores": "Encuentra una tienda",
  "side_stores_sub": "Tiendas que venden la gama", "side_events": "Eventos",
  "side_events_sub": "Catas, mercados y eventos", "side_work": "Trabaja con nosotros",
  "side_account": "Tu cuenta", "side_signin": "Iniciar sesión",
  "side_signin_sub": "Clientes y equipo — una sola puerta", "side_track": "Seguir un pedido",
  "side_track_sub": "Dónde está tu pedido ahora mismo", "side_support": "Ayuda",
  "side_support_sub": "Personas reales, el mismo sistema que usa el equipo",
  "side_a11y": "Accesibilidad e idioma", "side_a11y_sub": "Tamaño del texto, contraste, región y moneda",
  "close": "Cerrar", "back": "Atrás", "continue": "Continuar", "cancel": "Cancelar",
  "quantity": "Cantidad", "subtotal": "Subtotal", "shipping": "Envío", "tax": "Impuestos",
  "order_placed": "Pedido realizado", "sign_out": "Cerrar sesión",
  "email_receipt_subject": "¡Tu pedido #{oid} está en marcha!", "email_receipt_thanks": "¡Gracias, {name}!",
  "email_discount": "Descuento {code}", "email_tax": "Impuestos", "email_shipping": "Envío",
  "email_total": "Total", "email_track": "Sigue tu pedido cuando quieras: {url}  →  pedido #{oid}",
  "email_shipped_subject": "El pedido #{oid} va en camino", "email_delivered_subject": "El pedido #{oid} ha llegado",
  "email_hi": "Hola, {name}:", "email_shipped_line": "Tu pedido #{oid} va en camino.",
  "email_delivered_line": "Tu pedido #{oid} ha llegado.", "email_track_it": "Síguelo: {url}  →  pedido #{oid}",
  "prefs": "Preferencias", "prefs_saved": "Se guardan en este dispositivo.",
  "accessibility": "Accesibilidad", "text_size": "Tamaño del texto", "high_contrast": "Alto contraste",
  "reduce_motion": "Menos animación", "underline_links": "Subrayar enlaces",
  "measurement_cookies": "Cookies de medición", "region_language": "Región e idioma",
  "region": "Región", "language": "Idioma", "currency": "Moneda", "reset_all": "Restablecer todo",
  "a11y_open": "Opciones de accesibilidad e idioma", "empty_cart_line": "Tu carrito está vacío.",
  "place_order": "Realizar pedido", "track_my_order": "Seguir mi pedido", "sign_in": "Iniciar sesión",
  "create_account": "Crear cuenta", "my_account": "Mi cuenta", "name": "Nombre", "email": "Correo",
  "full_name": "Nombre completo", "shipping_label": "Envío", "payment": "Pago",
  "pay_on_delivery": "Pago contra entrega", "menu": "Menú", "search_placeholder": "Buscar…",
  "country": "País", "address": "Dirección", "street_address": "Calle y número", "optional": "opcional",
  "checkout_title": "Pago",
  "buy_now": "Comprar",
  "build_your_own": "Arma el tuyo",
  "build_your_own_note": "Elige las capacidades que tu negocio realmente usa y mira cómo el precio se suma solo: el mismo menú del que salen estos, con los precios del mismo libro.", "open_the_menu": "Abrir el menú",
  "all_products": "Todos los productos", "everything": "Todo", "the_case": "La caja",
 },
 "fr": {
  "shop": "Boutique", "reviews": "Avis", "faq": "FAQ", "cart": "Votre panier",
  "checkout": "Commander →", "add_to_cart": "Ajouter au panier", "search": "Rechercher…",
  "account": "Mon compte", "track": "Suivre ma commande", "support": "Assistance",
  "empty_cart": "Votre panier est vide", "discount_code": "Code de réduction",
  "apply": "Appliquer", "total": "Total", "free_shipping_at": "livraison offerte dès 40 $",
  "sold_out": "Épuisé", "shop_cta": "Voir la boutique",
  "offer_title": "10 % de remise sur votre première commande.", "start_plan": "Commencer",
  "plans_heading": "Vos abonnements", "no_plans": "Rien d'actif pour l'instant.",
  "nav_account": "Mon compte", "nav_track": "Suivre ma commande", "nav_support": "Assistance",
  "nav_menu": "Menu", "side_learn": "Apprenez avec nous", "side_learning": "Formation",
  "side_learning_sub": "Vos cours, leçons, quiz et camarades",
  "side_nutrition": "Nutrition", "side_nutrition_sub": "Planifier, préparer et suivre — coach en option",
  "side_find": "Venez nous voir", "side_stores": "Trouver un magasin",
  "side_stores_sub": "Les magasins qui vendent la gamme", "side_events": "Événements",
  "side_events_sub": "Dégustations, pop-ups et marchés", "side_work": "Travaillez avec nous",
  "side_account": "Votre compte", "side_signin": "Se connecter",
  "side_signin_sub": "Clients et équipe — une seule porte", "side_track": "Suivre une commande",
  "side_track_sub": "Où en est votre commande", "side_support": "Assistance",
  "side_support_sub": "De vraies personnes, sur le même système que l'équipe",
  "side_a11y": "Accessibilité et langue", "side_a11y_sub": "Taille du texte, contraste, région et devise",
  "close": "Fermer", "back": "Retour", "continue": "Continuer", "cancel": "Annuler",
  "quantity": "Quantité", "subtotal": "Sous-total", "shipping": "Livraison", "tax": "Taxes",
  "order_placed": "Commande passée", "sign_out": "Se déconnecter",
  "email_receipt_subject": "Votre commande n°{oid} est enregistrée !", "email_receipt_thanks": "Merci {name} !",
  "email_discount": "Réduction {code}", "email_tax": "Taxes", "email_shipping": "Livraison",
  "email_total": "Total", "email_track": "Suivez-la à tout moment : {url}  →  commande n°{oid}",
  "email_shipped_subject": "La commande n°{oid} est en route", "email_delivered_subject": "La commande n°{oid} est arrivée",
  "email_hi": "Bonjour {name},", "email_shipped_line": "Votre commande n°{oid} est en route.",
  "email_delivered_line": "Votre commande n°{oid} est arrivée.", "email_track_it": "Suivez-la : {url}  →  commande n°{oid}",
  "prefs": "Préférences", "prefs_saved": "Enregistrées sur cet appareil.",
  "accessibility": "Accessibilité", "text_size": "Taille du texte", "high_contrast": "Contraste élevé",
  "reduce_motion": "Moins d'animations", "underline_links": "Souligner les liens",
  "measurement_cookies": "Cookies de mesure", "region_language": "Région et langue",
  "region": "Région", "language": "Langue", "currency": "Devise", "reset_all": "Tout réinitialiser",
  "a11y_open": "Options d'accessibilité et de langue", "empty_cart_line": "Votre panier est vide.",
  "place_order": "Passer la commande", "track_my_order": "Suivre ma commande", "sign_in": "Se connecter",
  "create_account": "Créer un compte", "my_account": "Mon compte", "name": "Nom", "email": "E-mail",
  "full_name": "Nom complet", "shipping_label": "Livraison", "payment": "Paiement",
  "pay_on_delivery": "Paiement à la livraison", "menu": "Menu", "search_placeholder": "Rechercher…",
  "country": "Pays", "address": "Adresse", "street_address": "Rue et numéro", "optional": "facultatif",
  "checkout_title": "Commande",
  "buy_now": "Acheter",
  "build_your_own": "Composez le vôtre",
  "build_your_own_note": "Choisissez les capacités que votre entreprise utilise vraiment et regardez le prix s'additionner — le même menu dont ceux-ci sont tirés, aux prix du même livre.", "open_the_menu": "Ouvrir le menu",
  "all_products": "Tous les produits", "everything": "Tout", "the_case": "Le carton",
 },
 "de": {
  "shop": "Shop", "reviews": "Bewertungen", "faq": "FAQ", "cart": "Dein Warenkorb",
  "checkout": "Zur Kasse →", "add_to_cart": "In den Warenkorb", "search": "Suchen…",
  "account": "Mein Konto", "track": "Bestellung verfolgen", "support": "Hilfe",
  "empty_cart": "Dein Warenkorb ist leer", "discount_code": "Rabattcode",
  "apply": "Einlösen", "total": "Gesamt", "free_shipping_at": "versandkostenfrei ab 40 $",
  "sold_out": "Ausverkauft", "shop_cta": "Zum Sortiment",
  "offer_title": "10 % Rabatt auf deine erste Bestellung.", "start_plan": "Starten",
  "plans_heading": "Deine Abos", "no_plans": "Noch nichts aktiv.",
  "nav_account": "Mein Konto", "nav_track": "Bestellung verfolgen", "nav_support": "Hilfe",
  "nav_menu": "Menü", "side_learn": "Lerne mit uns", "side_learning": "Kurse",
  "side_learning_sub": "Deine Kurse, Lektionen, Quizze und Leute",
  "side_nutrition": "Ernährung", "side_nutrition_sub": "Planen, vorbereiten, verfolgen — Coach optional",
  "side_find": "Besuch uns", "side_stores": "Laden finden",
  "side_stores_sub": "Läden, die das Sortiment führen", "side_events": "Veranstaltungen",
  "side_events_sub": "Verkostungen, Pop-ups und Märkte", "side_work": "Arbeite mit uns",
  "side_account": "Dein Konto", "side_signin": "Anmelden",
  "side_signin_sub": "Kunden und Team — eine Tür", "side_track": "Bestellung verfolgen",
  "side_track_sub": "Wo deine Bestellung gerade ist", "side_support": "Hilfe",
  "side_support_sub": "Echte Menschen, dasselbe System wie das Team",
  "side_a11y": "Barrierefreiheit & Sprache", "side_a11y_sub": "Textgröße, Kontrast, Region und Währung",
  "close": "Schließen", "back": "Zurück", "continue": "Weiter", "cancel": "Abbrechen",
  "quantity": "Menge", "subtotal": "Zwischensumme", "shipping": "Versand", "tax": "Steuern",
  "order_placed": "Bestellung aufgegeben", "sign_out": "Abmelden",
  "email_receipt_subject": "Deine Bestellung #{oid} ist da!", "email_receipt_thanks": "Danke, {name}!",
  "email_discount": "Rabatt {code}", "email_tax": "Steuern", "email_shipping": "Versand",
  "email_total": "Gesamt", "email_track": "Jederzeit verfolgen: {url}  →  Bestellung #{oid}",
  "email_shipped_subject": "Bestellung #{oid} ist unterwegs", "email_delivered_subject": "Bestellung #{oid} ist angekommen",
  "email_hi": "Hallo {name},", "email_shipped_line": "Deine Bestellung #{oid} ist unterwegs.",
  "email_delivered_line": "Deine Bestellung #{oid} ist angekommen.", "email_track_it": "Verfolgen: {url}  →  Bestellung #{oid}",
  "prefs": "Einstellungen", "prefs_saved": "Auf diesem Gerät gespeichert.",
  "accessibility": "Barrierefreiheit", "text_size": "Textgröße", "high_contrast": "Hoher Kontrast",
  "reduce_motion": "Weniger Bewegung", "underline_links": "Links unterstreichen",
  "measurement_cookies": "Mess-Cookies", "region_language": "Region & Sprache",
  "region": "Region", "language": "Sprache", "currency": "Währung", "reset_all": "Alles zurücksetzen",
  "a11y_open": "Barrierefreiheit und Sprache", "empty_cart_line": "Dein Warenkorb ist leer.",
  "place_order": "Bestellung aufgeben", "track_my_order": "Bestellung verfolgen", "sign_in": "Anmelden",
  "create_account": "Konto erstellen", "my_account": "Mein Konto", "name": "Name", "email": "E-Mail",
  "full_name": "Vor- und Nachname", "shipping_label": "Versand", "payment": "Zahlung",
  "pay_on_delivery": "Zahlung bei Lieferung", "menu": "Menü", "search_placeholder": "Suchen…",
  "country": "Land", "address": "Adresse", "street_address": "Straße und Hausnummer", "optional": "optional",
  "checkout_title": "Kasse",
  "buy_now": "Jetzt kaufen",
  "build_your_own": "Selbst zusammenstellen",
  "build_your_own_note": "Wähle die Fähigkeiten, die dein Betrieb wirklich braucht, und sieh zu, wie sich der Preis von selbst zusammenrechnet — dasselbe Menü, aus dem diese geschnitten sind, zu denselben Preisen.", "open_the_menu": "Menü öffnen",
  "all_products": "Alle Produkte", "everything": "Alles", "the_case": "Die Kiste",
 },
 "pt": {
  "shop": "Loja", "reviews": "Avaliações", "faq": "Perguntas", "cart": "Seu carrinho",
  "checkout": "Finalizar →", "add_to_cart": "Adicionar ao carrinho", "search": "Buscar…",
  "account": "Minha conta", "track": "Acompanhar pedido", "support": "Ajuda",
  "empty_cart": "Seu carrinho está vazio", "discount_code": "Código de desconto",
  "apply": "Aplicar", "total": "Total", "free_shipping_at": "frete grátis a partir de $40",
  "sold_out": "Esgotado", "shop_cta": "Ver a loja",
  "offer_title": "10% de desconto no seu primeiro pedido.", "start_plan": "Começar",
  "plans_heading": "Seus planos", "no_plans": "Nada ativo ainda.",
  "nav_account": "Minha conta", "nav_track": "Acompanhar pedido", "nav_support": "Ajuda",
  "nav_menu": "Menu", "side_learn": "Aprenda com a gente", "side_learning": "Cursos",
  "side_learning_sub": "Seus cursos, aulas, testes e colegas",
  "side_nutrition": "Nutrição", "side_nutrition_sub": "Planeje, prepare e acompanhe — coach opcional",
  "side_find": "Venha nos ver", "side_stores": "Encontre uma loja",
  "side_stores_sub": "Lojas que vendem a linha", "side_events": "Eventos",
  "side_events_sub": "Degustações, pop-ups e feiras", "side_work": "Trabalhe com a gente",
  "side_account": "Sua conta", "side_signin": "Entrar",
  "side_signin_sub": "Clientes e equipe — uma só porta", "side_track": "Acompanhar um pedido",
  "side_track_sub": "Onde seu pedido está agora", "side_support": "Ajuda",
  "side_support_sub": "Pessoas de verdade, no mesmo sistema da equipe",
  "side_a11y": "Acessibilidade e idioma", "side_a11y_sub": "Tamanho do texto, contraste, região e moeda",
  "close": "Fechar", "back": "Voltar", "continue": "Continuar", "cancel": "Cancelar",
  "quantity": "Quantidade", "subtotal": "Subtotal", "shipping": "Frete", "tax": "Impostos",
  "order_placed": "Pedido feito", "sign_out": "Sair",
  "email_receipt_subject": "Seu pedido #{oid} foi recebido!", "email_receipt_thanks": "Obrigado, {name}!",
  "email_discount": "Desconto {code}", "email_tax": "Impostos", "email_shipping": "Frete",
  "email_total": "Total", "email_track": "Acompanhe quando quiser: {url}  →  pedido #{oid}",
  "email_shipped_subject": "O pedido #{oid} está a caminho", "email_delivered_subject": "O pedido #{oid} chegou",
  "email_hi": "Olá, {name},", "email_shipped_line": "Seu pedido #{oid} está a caminho.",
  "email_delivered_line": "Seu pedido #{oid} chegou.", "email_track_it": "Acompanhe: {url}  →  pedido #{oid}",
  "prefs": "Preferências", "prefs_saved": "Salvas neste aparelho.",
  "accessibility": "Acessibilidade", "text_size": "Tamanho do texto", "high_contrast": "Alto contraste",
  "reduce_motion": "Menos animação", "underline_links": "Sublinhar links",
  "measurement_cookies": "Cookies de medição", "region_language": "Região e idioma",
  "region": "Região", "language": "Idioma", "currency": "Moeda", "reset_all": "Redefinir tudo",
  "a11y_open": "Opções de acessibilidade e idioma", "empty_cart_line": "Seu carrinho está vazio.",
  "place_order": "Fazer pedido", "track_my_order": "Acompanhar pedido", "sign_in": "Entrar",
  "create_account": "Criar conta", "my_account": "Minha conta", "name": "Nome", "email": "E-mail",
  "full_name": "Nome completo", "shipping_label": "Frete", "payment": "Pagamento",
  "pay_on_delivery": "Pagar na entrega", "menu": "Menu", "search_placeholder": "Buscar…",
  "country": "País", "address": "Endereço", "street_address": "Rua e número", "optional": "opcional",
  "checkout_title": "Finalizar compra",
  "buy_now": "Comprar",
  "build_your_own": "Monte o seu",
  "build_your_own_note": "Escolha as capacidades que o seu negócio realmente usa e veja o preço se somar sozinho — o mesmo menu de onde estes saem, com os preços do mesmo livro.", "open_the_menu": "Abrir o menu",
  "all_products": "Todos os produtos", "everything": "Tudo", "the_case": "A caixa",
 },
 "zh": {
  "shop": "商店", "reviews": "评价", "faq": "常见问题", "cart": "购物车",
  "checkout": "结账 →", "add_to_cart": "加入购物车", "search": "搜索…",
  "account": "我的账户", "track": "查询订单", "support": "客服",
  "empty_cart": "购物车是空的", "discount_code": "优惠码",
  "apply": "使用", "total": "合计", "free_shipping_at": "满 $40 免运费",
  "sold_out": "已售罄", "shop_cta": "浏览商品",
  "offer_title": "首单立减 10%。", "start_plan": "开始",
  "plans_heading": "我的订阅", "no_plans": "暂无进行中的订阅。",
  "nav_account": "我的账户", "nav_track": "查询订单", "nav_support": "客服",
  "nav_menu": "菜单", "side_learn": "和我们一起学习", "side_learning": "课程",
  "side_learning_sub": "你的课程、课时、测验和同学",
  "side_nutrition": "营养", "side_nutrition_sub": "计划、准备与记录——教练可选",
  "side_find": "来找我们", "side_stores": "查找门店",
  "side_stores_sub": "有售本系列的门店", "side_events": "活动",
  "side_events_sub": "品鉴、快闪与集市", "side_work": "与我们合作",
  "side_account": "你的账户", "side_signin": "登录",
  "side_signin_sub": "顾客与团队——同一入口", "side_track": "查询订单",
  "side_track_sub": "你的订单现在在哪里", "side_support": "客服",
  "side_support_sub": "真人客服，与团队使用同一系统",
  "side_a11y": "无障碍与语言", "side_a11y_sub": "字号、对比度、地区与货币",
  "close": "关闭", "back": "返回", "continue": "继续", "cancel": "取消",
  "quantity": "数量", "subtotal": "小计", "shipping": "运费", "tax": "税费",
  "order_placed": "已下单", "sign_out": "退出登录",
  "email_receipt_subject": "你的订单 #{oid} 已收到！", "email_receipt_thanks": "谢谢你，{name}！",
  "email_discount": "优惠 {code}", "email_tax": "税费", "email_shipping": "运费",
  "email_total": "合计", "email_track": "随时查询：{url}  →  订单 #{oid}",
  "email_shipped_subject": "订单 #{oid} 已发货", "email_delivered_subject": "订单 #{oid} 已送达",
  "email_hi": "{name}，你好：", "email_shipped_line": "你的订单 #{oid} 已发货。",
  "email_delivered_line": "你的订单 #{oid} 已送达。", "email_track_it": "查询：{url}  →  订单 #{oid}",
  "prefs": "偏好设置", "prefs_saved": "保存在此设备上。",
  "accessibility": "无障碍", "text_size": "字号", "high_contrast": "高对比度",
  "reduce_motion": "减少动效", "underline_links": "链接加下划线",
  "measurement_cookies": "统计 Cookie", "region_language": "地区与语言",
  "region": "地区", "language": "语言", "currency": "货币", "reset_all": "全部重置",
  "a11y_open": "无障碍与语言选项", "empty_cart_line": "购物车是空的。",
  "place_order": "提交订单", "track_my_order": "查询订单", "sign_in": "登录",
  "create_account": "注册", "my_account": "我的账户", "name": "姓名", "email": "邮箱",
  "full_name": "姓名", "shipping_label": "配送", "payment": "支付",
  "pay_on_delivery": "货到付款", "menu": "菜单", "search_placeholder": "搜索…",
  "country": "国家/地区", "address": "地址", "street_address": "街道地址", "optional": "选填",
  "checkout_title": "结账",
  "buy_now": "立即购买",
  "build_your_own": "自选组合",
  "build_your_own_note": "选出你的业务真正用到的能力，看着价格自动加总——这些套餐正是从同一份菜单裁出的，价格来自同一本价目表。", "open_the_menu": "打开菜单",
  "all_products": "全部商品", "everything": "全部", "the_case": "整箱",
 },
 "ar": {
  "shop": "المتجر", "reviews": "التقييمات", "faq": "الأسئلة الشائعة", "cart": "سلتك",
  "checkout": "إتمام الشراء →", "add_to_cart": "أضف إلى السلة", "search": "بحث…",
  "account": "حسابي", "track": "تتبّع طلبي", "support": "الدعم",
  "empty_cart": "سلتك فارغة", "discount_code": "رمز الخصم",
  "apply": "تطبيق", "total": "الإجمالي", "free_shipping_at": "شحن مجاني من $40",
  "sold_out": "نفد", "shop_cta": "تصفّح المتجر",
  "offer_title": "خصم 10% على طلبك الأول.", "start_plan": "ابدأ",
  "plans_heading": "اشتراكاتك", "no_plans": "لا شيء نشط بعد.",
  "nav_account": "حسابي", "nav_track": "تتبّع طلبي", "nav_support": "الدعم",
  "nav_menu": "القائمة", "side_learn": "تعلّم معنا", "side_learning": "الدورات",
  "side_learning_sub": "دوراتك ودروسك واختباراتك وزملاؤك",
  "side_nutrition": "التغذية", "side_nutrition_sub": "خطّط وحضّر وتابع — المدرّب اختياري",
  "side_find": "زرنا", "side_stores": "ابحث عن متجر",
  "side_stores_sub": "المتاجر التي تبيع منتجاتنا", "side_events": "الفعاليات",
  "side_events_sub": "تذوّق ومعارض وأسواق", "side_work": "اعمل معنا",
  "side_account": "حسابك", "side_signin": "تسجيل الدخول",
  "side_signin_sub": "العملاء والفريق — باب واحد", "side_track": "تتبّع طلبًا",
  "side_track_sub": "أين طلبك الآن", "side_support": "الدعم",
  "side_support_sub": "أشخاص حقيقيون، على النظام نفسه الذي يستخدمه الفريق",
  "side_a11y": "سهولة الوصول واللغة", "side_a11y_sub": "حجم النص والتباين والمنطقة والعملة",
  "close": "إغلاق", "back": "رجوع", "continue": "متابعة", "cancel": "إلغاء",
  "quantity": "الكمية", "subtotal": "المجموع الفرعي", "shipping": "الشحن", "tax": "الضريبة",
  "order_placed": "تم الطلب", "sign_out": "تسجيل الخروج",
  "email_receipt_subject": "وصل طلبك رقم {oid}!", "email_receipt_thanks": "شكرًا {name}!",
  "email_discount": "خصم {code}", "email_tax": "الضريبة", "email_shipping": "الشحن",
  "email_total": "الإجمالي", "email_track": "تتبّع في أي وقت: {url}  ←  الطلب رقم {oid}",
  "email_shipped_subject": "الطلب رقم {oid} في الطريق", "email_delivered_subject": "وصل الطلب رقم {oid}",
  "email_hi": "مرحبًا {name}،", "email_shipped_line": "طلبك رقم {oid} في الطريق.",
  "email_delivered_line": "وصل طلبك رقم {oid}.", "email_track_it": "تتبّعه: {url}  ←  الطلب رقم {oid}",
  "prefs": "التفضيلات", "prefs_saved": "محفوظة على هذا الجهاز.",
  "accessibility": "سهولة الوصول", "text_size": "حجم النص", "high_contrast": "تباين عالٍ",
  "reduce_motion": "تقليل الحركة", "underline_links": "تسطير الروابط",
  "measurement_cookies": "ملفات تعريف القياس", "region_language": "المنطقة واللغة",
  "region": "المنطقة", "language": "اللغة", "currency": "العملة", "reset_all": "إعادة ضبط الكل",
  "a11y_open": "خيارات سهولة الوصول واللغة", "empty_cart_line": "سلتك فارغة.",
  "place_order": "إتمام الطلب", "track_my_order": "تتبّع طلبي", "sign_in": "تسجيل الدخول",
  "create_account": "إنشاء حساب", "my_account": "حسابي", "name": "الاسم", "email": "البريد الإلكتروني",
  "full_name": "الاسم الكامل", "shipping_label": "الشحن", "payment": "الدفع",
  "pay_on_delivery": "الدفع عند الاستلام", "menu": "القائمة", "search_placeholder": "بحث…",
  "country": "البلد", "address": "العنوان", "street_address": "الشارع والرقم", "optional": "اختياري",
  "checkout_title": "إتمام الشراء",
  "buy_now": "اشترِ الآن",
  "build_your_own": "كوّن خطتك",
  "build_your_own_note": "اختر القدرات التي يستخدمها عملك فعلًا وشاهد السعر يُحسب من تلقاء نفسه — القائمة نفسها التي قُصّت منها هذه، بأسعار الكتاب نفسه.", "open_the_menu": "افتح القائمة",
  "all_products": "كل المنتجات", "everything": "الكل", "the_case": "الصندوق",
 },
}

# Languages a shop can offer. A code, a name in its own language, and
# which way it reads — the three things a picker and a page need. A
# merchant adds one on Store admin → Languages; translations for it are
# typed on the same screen. Direction is the one that is not guessable
# from a code, so it is stored, not derived.
LOCALE_DEFAULT = [{"code": "en", "label": "English", "dir": "ltr"}]
RTL = {"ar", "he", "fa", "ur", "ps", "sd", "ug", "yi", "dv"}

# The major languages, as a shop would offer them: ISO 639-1 codes, each
# named in its own language, with its reading direction. "Add all major
# languages" offers every one; the fill translates into any of them
# through an engine that speaks it. Roughly the languages with the most
# speakers and the most online commerce, not every language on earth.
LANGUAGES = [
    ("en", "English"), ("es", "Español"), ("fr", "Français"), ("de", "Deutsch"),
    ("pt", "Português"), ("it", "Italiano"), ("nl", "Nederlands"), ("sv", "Svenska"),
    ("da", "Dansk"), ("nb", "Norsk"), ("fi", "Suomi"), ("pl", "Polski"),
    ("cs", "Čeština"), ("sk", "Slovenčina"), ("hu", "Magyar"), ("ro", "Română"),
    ("bg", "Български"), ("el", "Ελληνικά"), ("tr", "Türkçe"), ("ru", "Русский"),
    ("uk", "Українська"), ("he", "עברית"), ("ar", "العربية"), ("fa", "فارسی"),
    ("hi", "हिन्दी"), ("bn", "বাংলা"), ("ur", "اردو"), ("ta", "தமிழ்"),
    ("te", "తెలుగు"), ("mr", "मराठी"), ("id", "Bahasa Indonesia"), ("ms", "Bahasa Melayu"),
    ("vi", "Tiếng Việt"), ("th", "ไทย"), ("ko", "한국어"), ("ja", "日本語"),
    ("zh", "中文（简体）"), ("zh-tw", "中文（繁體）"), ("sw", "Kiswahili"), ("tl", "Filipino"),
]
LANGUAGE_LABEL = dict(LANGUAGES)


def language_entry(code: str) -> dict:
    code = code.strip().lower()
    return {"code": code, "label": LANGUAGE_LABEL.get(code, code.upper()),
            "dir": "rtl" if code.split("-")[0] in RTL else "ltr"}
CURRENCY_DEFAULT = [
    {"code": "USD", "symbol": "$", "rate": 1.0},
    {"code": "EUR", "symbol": "€", "rate": 0.92},
    {"code": "GBP", "symbol": "£", "rate": 0.79},
    {"code": "CAD", "symbol": "C$", "rate": 1.36},
]


def init_tables(con):
    con.executescript(TABLES)
    try:
        con.execute("ALTER TABLE translations ADD COLUMN source TEXT DEFAULT 'typed'")
    except Exception:                                        # noqa: BLE001
        pass
    # Root-relative, not bare fragments. The same nav renders on /blog and
    # /affiliates, where "#shop" is a fragment of a page that has no such
    # section — it silently does nothing. "/#shop" navigates home and then
    # scrolls, and still works as a same-page jump on the home page itself.
    if not con.execute("SELECT 1 FROM store_menus").fetchone():
        con.execute(
            "INSERT INTO store_menus(location,label,url,position) VALUES"
            " ('header','Shop','/#shop',0),('header','Reviews','/#reviews',1),"
            " ('header','FAQ','/#faq',2),('header','Blog','/blog',3),"
            " ('footer','Shop','/#shop',0),('footer','Blog','/blog',1),"
            " ('footer','FAQ','/#faq',2)")
    # Stores seeded before that fix keep their broken links otherwise.
    con.execute("UPDATE store_menus SET url='/'||url WHERE url LIKE '#%'")
    # The affiliate programme needs a way in; add it once, idempotently.
    if not con.execute("SELECT 1 FROM store_menus WHERE url='/affiliates'"
                       ).fetchone():
        con.execute(
            "INSERT INTO store_menus(location,label,url,position)"
            " VALUES('footer','Affiliates','/affiliates',5)")


def menus(con) -> dict:
    out = {"header": [], "footer": []}
    for r in con.execute(
            "SELECT * FROM store_menus ORDER BY location, position, id"
            ).fetchall():
        out.setdefault(r["location"], []).append(dict(r))
    return out


def currencies(con) -> list:
    row = con.execute("SELECT v FROM store_meta WHERE k='currencies'"
                      ).fetchone()
    if row:
        try:
            return json.loads(row["v"])
        except ValueError:
            pass
    return CURRENCY_DEFAULT


def i18n_settings(con) -> dict:
    """Which languages, which is the default, and whether a first visit
    follows the browser's language. Locales come from the setting when
    one is kept and from the translations table when it is not, so an
    install that translated before this setting existed keeps its picker."""
    row = con.execute("SELECT v FROM store_meta WHERE k='i18n'").fetchone()
    cfg = {}
    if row:
        try:
            cfg = json.loads(row["v"])
        except ValueError:
            cfg = {}
    locs = [dict(l) for l in cfg.get("locales") or [] if isinstance(l, dict) and l.get("code")]
    if not cfg:
        # Nothing chosen yet: English and every language the product
        # ships with, so the picker works the day the shop opens. The
        # merchant trims the list on Store admin → Languages.
        locs = [dict(l) for l in BUILTIN_LOCALES]
    known = {l["code"] for l in locs}
    if "en" not in known:
        locs.insert(0, LOCALE_DEFAULT[0])
        known.add("en")
    for r in con.execute("SELECT DISTINCT locale FROM translations ORDER BY locale").fetchall():
        if r["locale"] not in known:
            locs.append(language_entry(r["locale"]))
            known.add(r["locale"])
    for l in locs:
        if not l.get("label"):
            l["label"] = LANGUAGE_LABEL.get(l["code"], l["code"].upper())
        l["dir"] = "rtl" if l.get("dir") == "rtl" or (
            "dir" not in l and l["code"].split("-")[0] in RTL) else "ltr"
    default = cfg.get("default") if cfg.get("default") in known else "en"
    return {"locales": locs, "default": default,
            "auto_detect": bool(cfg.get("auto_detect", True))}


def locales(con) -> list:
    return [l["code"] for l in i18n_settings(con)["locales"]]


def translations_for(con, locale: str) -> dict:
    """The shipped translation of the interface's words for this
    language, with the merchant's own on top. A merchant's product
    names and pages appear only when they typed them."""
    own = {r["key"]: r["value"] for r in con.execute(
        "SELECT key, value FROM translations WHERE locale=?",
        (locale,)).fetchall()}
    base = BUILTIN.get(locale) or BUILTIN.get(locale.split("-")[0], {})
    return {**base, **own}


def ui_strings(con) -> dict:
    """The interface's own words, with this tenant's overrides on top.

    UI_KEYS is the shipped English. A merchant who calls it something else —
    or ships free over a different number — writes those keys to store_meta
    under 'ui_strings' rather than asking for a code change.
    """
    row = con.execute("SELECT v FROM store_meta WHERE k='ui_strings'"
                      ).fetchone()
    if not row:
        return UI_KEYS
    try:
        own = json.loads(row["v"])
    except ValueError:
        return UI_KEYS
    return {**UI_KEYS, **{k: v for k, v in own.items() if isinstance(v, str)}}


def i18n_payload(con) -> str:
    """Injected into every storefront page so the client can localise
    prices and UI strings without a second round trip."""
    from erp.backend.main import CFG
    from . import affiliates as aff
    from .api import get_theme
    i18n = i18n_settings(con)
    data = {"currencies": currencies(con), "locales": locales(con),
            "locale_info": i18n["locales"], "default_locale": i18n["default"],
            "auto_detect": i18n["auto_detect"],
            "ui": ui_strings(con),
            # Which stand-in art this shop draws — the client twin of
            # product_art(), reading the one switch rather than guessing.
            "art": get_theme(con).get("art") or "card",
            "regions": CFG.get("regions") or [],
            "affiliate_window_days": aff.window_days(CFG),
            "strings": {loc: translations_for(con, loc)
                        for loc in locales(con) if loc != "en"}}
    return (f"<script>window.STORE_I18N={json.dumps(data)};</script>")


# ---------- blog ----------

def post_json(r) -> dict:
    d = dict(r)
    d["url"] = f"/blog/{r['slug']}"
    return d


def _day(ts: float) -> str:
    """The day a post went up, as a reader would say it.

    The column has been ordering the journal since it was made and was
    never once shown: a blog whose posts carry no date reads as a blog
    nobody has touched in years, which is the opposite of what an
    up-to-date one is for.
    """
    try:
        return time.strftime("%-d %B %Y", time.localtime(float(ts)))
    except Exception:                                        # noqa: BLE001
        return ""


def _iso(ts: float) -> str:
    """The same moment for machines."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(float(ts)))
    except Exception:                                        # noqa: BLE001
        return ""


@router.get("/api/store/blog")
def list_posts(limit: int = 20, con=Depends(get_con)):
    return [post_json(r) for r in con.execute(
        "SELECT * FROM blog_posts WHERE published=1"
        " ORDER BY published_at DESC LIMIT ?", (min(limit, 50),)).fetchall()]


@router.get("/blog")
def blog_index(request: Request, con=Depends(get_con)):
    from .partners import _require_cap
    _require_cap("marketing")
    posts = con.execute(
        "SELECT * FROM blog_posts WHERE published=1"
        " ORDER BY published_at DESC LIMIT 50").fetchall()
    if posts:
        cards = "".join(
            f'<a class="post-card" href="/blog/{sect.esc(p["slug"])}">'
            + (f'<div class="post-art"><img src="/media/m/{p["media_id"]}/thumb"'
               f' alt="" loading="lazy"></div>' if p["media_id"] else "")
            + f'<div class="post-body"><b>{sect.esc(p["title"])}</b>'
            f'<p class="dim">{sect.esc(p["excerpt"])}</p>'
            f'<span class="dim">{sect.esc(p["author"])}'
            f'{" · " + _day(p["published_at"]) if p["published_at"] else ""}'
            f'</span></div></a>'
            for p in posts)
    else:
        cards = ('<p class="dim">No posts yet — write the first one in '
                 'Store admin → Blog.</p>')
    body = (f'<section class="section"><h2>Journal</h2>'
            f'<div class="post-grid">{cards}</div></section>')
    return HTMLResponse(render_shell(
        con, body, title=f"Journal — {get_theme(con)['brand']}",
        description="Stories, recipes and news."))


@router.get("/blog/{slug}")
def blog_post(slug: str, request: Request, con=Depends(get_con)):
    from .partners import _require_cap
    _require_cap("marketing")
    p = con.execute("SELECT * FROM blog_posts WHERE slug=? AND published=1",
                    (slug,)).fetchone()
    if p is None:
        raise HTTPException(404, "post not found")
    base = str(request.base_url).rstrip("/")
    img = f"{base}/media/m/{p['media_id']}" if p["media_id"] else ""
    ld = {"@context": "https://schema.org", "@type": "BlogPosting",
          "headline": p["title"], "description": p["excerpt"],
          "author": {"@type": "Person", "name": p["author"] or "Team"},
          "mainEntityOfPage": f"{base}/blog/{slug}"}
    if p["published_at"]:
        # datePublished is what a search engine needs to show this as
        # anything other than undated, and the column has been sat on
        # since the table was made — sorted by, never said.
        ld["datePublished"] = _iso(p["published_at"])
    if img:
        ld["image"] = img
    hero = (f'<div class="post-hero"><img src="/media/m/{p["media_id"]}"'
            f' alt="{sect.esc(p["title"])}"></div>' if p["media_id"] else "")
    body = (f'<article class="section post">'
            f'<a class="dim" href="/blog">← Journal</a>'
            f'<h2>{sect.esc(p["title"])}</h2>'
            f'<p class="dim">{sect.esc(p["author"])}'
            f'{" · " + _day(p["published_at"]) if p["published_at"] else ""}'
            f'</p>{hero}'
            f'<div class="post-content">{p["body"]}</div></article>'
            f'<script type="application/ld+json">{json.dumps(ld)}</script>')
    if p["comments_on"]:
        rows = con.execute(
            "SELECT name, body, created_at FROM blog_comments"
            " WHERE post_id=? AND approved=1 ORDER BY id",
            (p["id"],)).fetchall()
        posted = "".join(
            f'<div class="cmt"><b>{sect.esc(r["name"])}</b>'
            f'<p>{sect.esc(r["body"])}</p></div>' for r in rows)
        body += (
            f'<section class="section comments"><h2>Comments</h2>'
            f'{posted or "<p class=dim>Be the first to comment.</p>"}'
            f'<form class="cmt-form" data-slug="{sect.esc(p["slug"])}">'
            f'<div class="cmt-row">'
            f'<label>Name<input name="name" required></label>'
            f'<label>Email <span class="dim">(not published)</span>'
            f'<input name="email" type="email"></label></div>'
            f'<label>Comment<textarea name="body" rows="3" required></textarea>'
            f'</label>'
            f'<button class="btn-pill primary" type="submit">Post comment</button>'
            f'<p class="cmt-msg"></p></form></section>')

    return HTMLResponse(render_shell(
        con, body, title=f"{p['title']} — {get_theme(con)['brand']}",
        description=p["excerpt"] or p["title"]))


class PostBody(BaseModel):
    slug: str = ""
    title: str
    excerpt: str = ""
    body: str = ""
    media_id: int | None = None
    author: str = ""
    tags: str = ""
    published: bool = True


@router.get("/api/store/admin/posts")
def admin_posts(u=Depends(admin_user), con=Depends(get_con)):
    return [post_json(r) for r in con.execute(
        "SELECT * FROM blog_posts ORDER BY id DESC").fetchall()]


@router.post("/api/store/admin/posts")
def save_post(body: PostBody, u=Depends(admin_user), con=Depends(get_con)):
    slug = slugify(body.slug or body.title)
    con.execute(
        "INSERT INTO blog_posts(slug,title,excerpt,body,media_id,author,tags,"
        " published,published_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(slug) DO UPDATE SET title=excluded.title,"
        " excerpt=excluded.excerpt, body=excluded.body,"
        " media_id=excluded.media_id, author=excluded.author,"
        " tags=excluded.tags, published=excluded.published",
        (slug, body.title.strip(), body.excerpt.strip(), body.body,
         body.media_id, body.author.strip(), body.tags.strip(),
         int(body.published), db.now(), db.now()))
    con.commit()
    return {"ok": True, "slug": slug, "url": f"/blog/{slug}"}


@router.delete("/api/store/admin/posts/{slug}")
def delete_post(slug: str, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM blog_posts WHERE slug=?", (slug,))
    con.commit()
    return {"ok": True}


# ---------- menus ----------

class MenuBody(BaseModel):
    location: str = "header"
    label: str
    url: str
    position: int = 0


@router.get("/api/store/admin/menus")
def admin_menus(u=Depends(admin_user), con=Depends(get_con)):
    return menus(con)


@router.post("/api/store/admin/menus")
def add_menu(body: MenuBody, u=Depends(admin_user), con=Depends(get_con)):
    if body.location not in ("header", "footer"):
        raise HTTPException(400, "location must be header or footer")
    con.execute(
        "INSERT INTO store_menus(location,label,url,position)"
        " VALUES(?,?,?,?)", (body.location, body.label.strip()[:40],
                             body.url.strip()[:200], body.position))
    con.commit()
    return {"ok": True}


@router.delete("/api/store/admin/menus/{mid}")
def delete_menu(mid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM store_menus WHERE id=?", (mid,))
    con.commit()
    return {"ok": True}


# ---------- redirects ----------

class RedirectBody(BaseModel):
    from_path: str
    to_path: str
    code: int = 301


@router.get("/api/store/admin/redirects")
def admin_redirects(u=Depends(admin_user), con=Depends(get_con)):
    return [dict(r) for r in con.execute(
        "SELECT * FROM store_redirects ORDER BY hits DESC, id DESC").fetchall()]


@router.post("/api/store/admin/redirects")
def add_redirect(body: RedirectBody, u=Depends(admin_user),
                 con=Depends(get_con)):
    frm = "/" + body.from_path.strip().lstrip("/")
    if body.code not in (301, 302):
        raise HTTPException(400, "code must be 301 or 302")
    if frm in ("/", "/admin", "/ops"):
        raise HTTPException(400, "refusing to redirect a core route")
    con.execute(
        "INSERT INTO store_redirects(from_path,to_path,code,created_at)"
        " VALUES(?,?,?,?) ON CONFLICT(from_path) DO UPDATE SET"
        " to_path=excluded.to_path, code=excluded.code",
        (frm, body.to_path.strip(), body.code, db.now()))
    con.commit()
    return {"ok": True, "from_path": frm}


@router.delete("/api/store/admin/redirects/{rid}")
def delete_redirect(rid: int, u=Depends(admin_user), con=Depends(get_con)):
    con.execute("DELETE FROM store_redirects WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}


def find_redirect(con, path: str):
    r = con.execute("SELECT * FROM store_redirects WHERE from_path=?",
                    (path,)).fetchone()
    if r is None:
        return None
    con.execute("UPDATE store_redirects SET hits=hits+1 WHERE id=?", (r["id"],))
    con.commit()
    return RedirectResponse(r["to_path"], status_code=r["code"])


# ---------- i18n & currency ----------

@router.get("/api/store/i18n")
def get_i18n(con=Depends(get_con)):
    i18n = i18n_settings(con)
    return {"currencies": currencies(con), "locales": locales(con),
            "locale_info": i18n["locales"], "default_locale": i18n["default"],
            "auto_detect": i18n["auto_detect"],
            "ui": UI_KEYS,
            "strings": {loc: translations_for(con, loc)
                        for loc in locales(con) if loc != "en"}}


class MtBody(BaseModel):
    engine: str = ""
    url: str = ""
    key: str = ""
    model: str = ""


@router.get("/api/store/admin/mt")
def mt_get(u=Depends(admin_user), con=Depends(get_con)):
    return mt_settings(con)


@router.post("/api/store/admin/mt")
def mt_save(body: MtBody, u=Depends(admin_user), con=Depends(get_con)):
    """Which translator, and how to reach it. A blank engine disconnects;
    a blank key keeps the one on file."""
    if body.engine and body.engine not in MT_ENGINES:
        raise HTTPException(400, f"engine is one of {sorted(MT_ENGINES)}")
    cur = _mt_cfg(con)
    cfg = {"engine": body.engine, "url": body.url.strip()[:300],
           "model": body.model.strip()[:80],
           "key": body.key.strip()[:200] or (cur.get("key", "") if body.engine == cur.get("engine") else "")}
    con.execute("INSERT INTO store_meta(k,v) VALUES('mt',?)"
                " ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(cfg),))
    con.commit()
    return mt_settings(con)


class FillBody(BaseModel):
    force_machine: bool = False
    dry_run: bool = False


@router.post("/api/store/admin/translations/{locale}/fill")
def translations_fill(locale: str, body: FillBody | None = None, u=Depends(admin_user),
                      con=Depends(get_con)):
    """Fill what this language lacks, by machine, marked as the machine's."""
    body = body or FillBody()
    return fill_locale(con, locale, force_machine=body.force_machine, dry_run=body.dry_run)


class FillAllBody(BaseModel):
    locales: list = []            # empty = every language the shop offers
    force_machine: bool = False
    dry_run: bool = False


@router.post("/api/store/admin/translations/fill-all")
def translations_fill_all(body: FillAllBody, u=Depends(admin_user), con=Depends(get_con)):
    """Every language the shop offers, in one go."""
    locs = [c.strip().lower() for c in body.locales if c.strip()] or locales(con)
    return fill_many(con, locs, force_machine=body.force_machine, dry_run=body.dry_run)


class OfferBody(BaseModel):
    codes: list = []              # empty = all major languages


@router.post("/api/store/admin/i18n/offer")
def i18n_offer(body: OfferBody, u=Depends(admin_user), con=Depends(get_con)):
    """Offer languages — a list, or every major one — keeping what was there."""
    codes = [c for c in body.codes if isinstance(c, str)] or [c for c, _ in LANGUAGES]
    bad = [c for c in codes if not all(ch.isalnum() or ch == "-" for ch in c.strip().lower())]
    if bad:
        raise HTTPException(400, f"not language codes: {bad}")
    return offer_languages(con, codes)


class I18nBody(BaseModel):
    locales: list = []
    default: str = "en"
    auto_detect: bool = True


@router.post("/api/store/admin/i18n")
def save_i18n(body: I18nBody, u=Depends(admin_user), con=Depends(get_con)):
    """The languages the shop offers. A code, a name in its own
    language, and which way it reads."""
    locs, seen = [], set()
    for l in body.locales:
        code = str(l.get("code", "")).strip().lower()[:8]
        if not code or code in seen:
            continue
        if not all(ch.isalnum() or ch == "-" for ch in code):
            raise HTTPException(400, f"'{code}' is not a language code (es, pt-br, zh-hant)")
        seen.add(code)
        locs.append({"code": code, "label": str(l.get("label", "")).strip()[:40] or code.upper(),
                     "dir": "rtl" if str(l.get("dir", "")) == "rtl" or (
                         "dir" not in l and code.split("-")[0] in RTL) else "ltr"})
    if "en" not in seen:
        locs.insert(0, LOCALE_DEFAULT[0]); seen.add("en")
    default = body.default.strip().lower()
    if default not in seen:
        raise HTTPException(400, "the default has to be one of the languages offered")
    con.execute("INSERT INTO store_meta(k,v) VALUES('i18n',?)"
                " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (json.dumps({"locales": locs, "default": default,
                             "auto_detect": body.auto_detect}),))
    con.commit()
    return {"ok": True, **i18n_settings(con)}


class TranslationBody(BaseModel):
    locale: str
    entries: dict


@router.post("/api/store/admin/translations")
def save_translations(body: TranslationBody, u=Depends(admin_user),
                      con=Depends(get_con)):
    loc = body.locale.strip().lower()[:8]
    if not loc or loc == "en":
        raise HTTPException(400, "pick a locale other than the base 'en'")
    for k, v in body.entries.items():
        if not str(v).strip():
            con.execute("DELETE FROM translations WHERE locale=? AND key=?",
                        (loc, k))
        else:
            con.execute(
                "INSERT INTO translations(locale,key,value,source) VALUES(?,?,?,'typed')"
                " ON CONFLICT(locale,key) DO UPDATE SET value=excluded.value, source='typed'",
                (loc, k, str(v)))
    con.commit()
    return {"ok": True, "locale": loc,
            "count": len(translations_for(con, loc))}


@router.get("/api/store/admin/translations/{locale}")
def read_translations(locale: str, u=Depends(admin_user),
                      con=Depends(get_con)):
    keys = {**UI_KEYS, **content_keys(con)}
    own, sources = {}, {}
    for r in con.execute("SELECT key, value, source FROM translations WHERE locale=?",
                         (locale,)).fetchall():
        own[r["key"]] = r["value"]
        sources[r["key"]] = r["source"] or "typed"
    have = translations_for(con, locale)
    return {"locale": locale, "base": keys,
            "values": have,
            "shipped": BUILTIN.get(locale, {}), "own": own, "sources": sources,
            "missing": sum(1 for k in keys if k not in have and k not in ("cart_tag", "cart_note")),
            "mt": mt_settings(con)}


class CurrencyBody(BaseModel):
    currencies: list


@router.post("/api/store/admin/currencies")
def save_currencies(body: CurrencyBody, u=Depends(admin_user),
                    con=Depends(get_con)):
    clean = [{"code": str(c.get("code", ""))[:4].upper(),
              "symbol": str(c.get("symbol", ""))[:3],
              "rate": float(c.get("rate", 1) or 1)}
             for c in body.currencies if c.get("code")]
    if not clean or clean[0]["rate"] != 1.0:
        raise HTTPException(400, "the first currency is the base and must "
                                 "have rate 1.0")
    con.execute("INSERT INTO store_meta(k,v) VALUES('currencies',?)"
                " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (json.dumps(clean),))
    con.commit()
    return {"ok": True, "currencies": clean}
