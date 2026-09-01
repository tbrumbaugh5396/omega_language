"""Translation and thesaurus lookups — the Voice & translation capability's
server half, ported from lingua-portal.

The default provider is **local and offline**: a small built-in glossary
plus an English synonym set. It is deliberately honest about being small —
a miss returns `found: false` with a clear reason rather than a
plausible-looking guess, because a wrong translation presented confidently
is worse for a learner than no translation at all.

A remote provider is enabled by configuration and is **off by default on
purpose**: a school app should not start sending its students' words to a
third party because someone clicked a button. Config keys (per install,
in config.json):

    translate_url    a LibreTranslate-compatible endpoint (POST /translate)
    translate_key    optional api key for it
    thesaurus        set to "datamuse" to use api.datamuse.com (no key)

Every response carries `via` so nobody has to guess where an answer came
from. Results are cached in-process keyed by (kind, text, from, to) — a
class of twenty looking up the same word should not become twenty
identical outbound requests. Speech itself (dictation in, spoken answers
out) is browser-side and never touches this server at all.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 6

# ── the offline glossary ─────────────────────────────────────────────────────
# Small on purpose: the vocabulary a beginner course actually uses.
# Keys are normalised lowercase.
_GLOSSARY: dict = {
    ("en", "es"): {
        "hello": "hola", "goodbye": "adiós", "please": "por favor",
        "thank you": "gracias", "good morning": "buenos días",
        "good afternoon": "buenas tardes", "good night": "buenas noches",
        "yes": "sí", "no": "no", "water": "agua", "food": "comida",
        "house": "casa", "book": "libro", "teacher": "profesor",
        "student": "estudiante", "school": "escuela", "friend": "amigo",
        "how are you": "¿cómo estás?", "my name is": "me llamo",
        "excuse me": "perdón", "table": "mesa", "chair": "silla",
        "today": "hoy", "tomorrow": "mañana", "yesterday": "ayer",
    },
    ("en", "ja"): {
        "hello": "こんにちは", "goodbye": "さようなら",
        "please": "お願いします", "thank you": "ありがとう",
        "good morning": "おはようございます",
        "good night": "おやすみなさい", "yes": "はい", "no": "いいえ",
        "water": "みず", "food": "たべもの", "house": "いえ",
        "book": "ほん", "teacher": "せんせい", "student": "がくせい",
        "school": "がっこう", "friend": "ともだち", "today": "きょう",
        "tomorrow": "あした", "yesterday": "きのう",
    },
    ("en", "fr"): {
        "hello": "bonjour", "goodbye": "au revoir",
        "please": "s'il vous plaît", "thank you": "merci",
        "good morning": "bonjour", "good night": "bonne nuit",
        "yes": "oui", "no": "non", "water": "eau", "food": "nourriture",
        "house": "maison", "book": "livre", "teacher": "professeur",
        "student": "étudiant", "school": "école", "friend": "ami",
    },
}
# reverse direction comes for free
for (_a, _b), _d in list(_GLOSSARY.items()):
    _GLOSSARY.setdefault((_b, _a), {})
    for _k, _v in _d.items():
        _GLOSSARY[(_b, _a)].setdefault(_v.lower(), _k)

_SYNONYMS: dict = {
    "happy": ["glad", "pleased", "content", "cheerful", "delighted"],
    "sad": ["unhappy", "sorrowful", "downcast", "gloomy"],
    "big": ["large", "great", "huge", "enormous", "vast"],
    "small": ["little", "tiny", "slight", "compact"],
    "fast": ["quick", "rapid", "swift", "speedy"],
    "slow": ["gradual", "leisurely", "unhurried"],
    "say": ["tell", "state", "utter", "remark", "declare"],
    "walk": ["stroll", "wander", "amble", "stride"],
    "important": ["significant", "crucial", "vital", "key"],
    "difficult": ["hard", "tough", "challenging", "demanding"],
    "beautiful": ["lovely", "pretty", "attractive", "gorgeous"],
    "learn": ["study", "acquire", "grasp", "master"],
}

LANGS = {"en": "English", "es": "Spanish", "ja": "Japanese", "fr": "French",
         "de": "German", "it": "Italian", "pt": "Portuguese", "zh": "Chinese"}

_cache: dict = {}
_lock = threading.Lock()


def _translate_endpoint(cfg) -> tuple[str, str, str]:
    """Where translations go, by the node-services resolution rule: the
    tenant's own config wins, the machine's shared daemon is the floor,
    and nothing configured means the offline glossary — exactly the
    behavior before node services existed."""
    url = (cfg.get("translate_url") or "").strip()
    if url:
        return url, (cfg.get("translate_key") or ""), "remote"
    from . import services
    s = services.service("translate")
    if s:
        return s["url"], s["key"], "node service"
    return "", "", ""


def providers(cfg) -> dict:
    """What is actually configured — shown in the UI so nobody guesses."""
    _, _, via = _translate_endpoint(cfg)
    return {
        "translate": via or "local",
        "thesaurus": cfg.get("thesaurus") or "local",
        "languages": LANGS,
    }


def _http_json(url: str, *, data: dict | None = None):
    try:
        if data is None:
            req = urllib.request.Request(
                url, headers={"Accept": "application/json"})
        else:
            req = urllib.request.Request(
                url, data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None   # a provider being down degrades to "not found", not 500


def translate(cfg, text: str, *, source: str = "en",
              target: str = "es") -> dict:
    text = str(text or "").strip()
    if not text:
        return {"found": False, "reason": "nothing to translate"}
    key = ("t", text.lower(), source, target)
    with _lock:
        if key in _cache:
            return _cache[key]

    url, api_key, via = _translate_endpoint(cfg)
    if url:
        payload = {"q": text, "source": source, "target": target,
                   "format": "text"}
        if api_key:
            payload["api_key"] = api_key
        got = _http_json(url.rstrip("/") + "/translate", data=payload)
        t = (got or {}).get("translatedText") if isinstance(got, dict) else None
        out = ({"found": True, "text": t, "via": via,
                "source": source, "target": target} if t else
               {"found": False, "via": via,
                "reason": "the translation service did not answer"})
    else:
        hit = _GLOSSARY.get((source, target), {}).get(text.lower())
        out = ({"found": True, "text": hit, "via": "local glossary",
                "source": source, "target": target} if hit else
               {"found": False, "via": "local glossary",
                "reason": f'"{text}" is not in the offline glossary'
                          f" ({LANGS.get(source, source)} to"
                          f" {LANGS.get(target, target)}). Configure"
                          " translate_url, or install the machine's"
                          " translate service"
                          " (scripts/install_translate.sh)."})
    with _lock:
        _cache[key] = out
    return out


def thesaurus(cfg, word: str, *, lang: str = "en") -> dict:
    word = str(word or "").strip().lower()
    if not word:
        return {"found": False, "reason": "nothing to look up"}
    key = ("s", word, lang, "")
    with _lock:
        if key in _cache:
            return _cache[key]

    if (cfg.get("thesaurus") or "") == "datamuse" and lang == "en":
        got = _http_json("https://api.datamuse.com/words?max=12&rel_syn="
                         + urllib.parse.quote(word))
        syns = [w["word"] for w in got] if isinstance(got, list) else []
        out = ({"found": True, "word": word, "synonyms": syns,
                "via": "datamuse"} if syns else
               {"found": False, "via": "datamuse",
                "reason": "no synonyms found"})
    else:
        syns = _SYNONYMS.get(word, [])
        if not syns:   # also answer when the word IS a synonym we know
            for head, group in _SYNONYMS.items():
                if word in group:
                    syns = [head] + [w for w in group if w != word]
                    break
        out = ({"found": True, "word": word, "synonyms": syns, "via": "local"}
               if syns else
               {"found": False, "via": "local",
                "reason": f'"{word}" is not in the offline thesaurus.'
                          ' Configure thesaurus="datamuse" for a live one.'})
    with _lock:
        _cache[key] = out
    return out


def clear_cache() -> int:
    with _lock:
        n = len(_cache)
        _cache.clear()
    return n
