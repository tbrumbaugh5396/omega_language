"""Node services: daemons installed once per machine, shared by every
tenant living on it.

The manifest is `data/node_services.json` — NODE-level, beside the fleet
registry and deliberately outside every tenant directory, because a
service belongs to the machine the way a disk does:

    {"translate": {"url": "http://127.0.0.1:5000", "key": ""}}

The resolution rule, everywhere a service is consumed: **the tenant's own
config wins, the node's manifest is the floor, absence degrades to
exactly the behavior before this file existed.** A tenant that pays for
its own provider keeps it; a tenant with nothing configured gets the
machine's shared daemon; a machine with nothing installed changes
nothing. Health is probed live, never stored — a stored "healthy" is a
lie waiting for a restart.

Installers under scripts/ (install_translate.sh first) stand a service
up under systemd and write its manifest line; they ship in the app
bundle, so every worker node can grow the same services its provider
has.
"""
import json
import urllib.error
import urllib.request

# What each service name means, and how to ask it if it is alive. The
# probe only proves a listener answers — 2xx through 4xx all count, since
# a 404 from the right port is still a daemon, while a refused connection
# is not.
KNOWN = {
    "translate": {"probe": "/languages",
                  "what": "LibreTranslate-compatible translation"},
    # Any server speaking WHIP/WHEP (MediaMTX is what install_sfu.sh
    # stands up). Extra manifest keys it carries: public_url (what the
    # BROWSER dials — the probe url may be localhost), record_dir (where
    # its class tapes land before the platform collects them home).
    "sfu": {"probe": "/",
            "what": "WHIP/WHEP media server for large classes"},
    # The pilot for the tooling family: a git forge (Forgejo) on the
    # node. Today it is an installed daemon with a health pill — the
    # capability that would sell it (repos, CI, releases) is a
    # price-book decision, not a service one.
    "forge": {"probe": "/api/v1/version",
              "what": "git forge (Forgejo) for the tooling family"},
}

_cache = {"stamp": None, "data": {}}


def _path():
    from . import config
    return config.DATA_DIR / "node_services.json"


def manifest() -> dict:
    """The machine's declared services, mtime-cached."""
    p = _path()
    try:
        stamp = p.stat().st_mtime_ns
    except OSError:
        _cache["stamp"], _cache["data"] = None, {}
        return {}
    if _cache["stamp"] != stamp:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            _cache["data"] = data if isinstance(data, dict) else {}
        except ValueError:
            _cache["data"] = {}
        _cache["stamp"] = stamp
    return _cache["data"]


def service(name: str) -> dict | None:
    """One service's config, or None — a manifest row without a url is a
    note, not a service. url and key are normalised; any other keys the
    manifest carries (public_url, record_dir, ...) ride along."""
    s = manifest().get(name)
    if isinstance(s, dict) and str(s.get("url") or "").strip():
        return {**s, "url": str(s["url"]).rstrip("/"),
                "key": str(s.get("key") or "")}
    return None


def declare(name: str, url: str, key: str = "") -> None:
    """Write one manifest line — what an installer does at the end, and
    what an operator does by hand on a machine without one."""
    m = dict(manifest())
    m[name] = {"url": str(url).rstrip("/"), "key": key}
    _path().write_text(json.dumps(m, indent=1), encoding="utf-8")


def health(name: str) -> dict:
    s = service(name)
    if not s:
        return {"installed": False, "healthy": False}
    probe = KNOWN.get(name, {}).get("probe", "/")
    try:
        req = urllib.request.Request(s["url"] + probe,
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            alive = 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        alive = e.code < 500
    except OSError:
        alive = False
    return {"installed": True, "url": s["url"], "healthy": alive}


def summary() -> dict:
    """{name: healthy} for every declared service — what the node's ping
    reports and the Platform tab wears as pills."""
    return {n: health(n)["healthy"] for n in manifest()}
