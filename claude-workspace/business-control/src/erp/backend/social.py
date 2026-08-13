"""Best-effort link previews for affiliate feed posts.

Known platforms go through their public oEmbed endpoints (no API keys);
everything else falls back to the page's OpenGraph tags. Failures are fine —
the post is stored either way, just without a preview card."""
import html
import re
from urllib.parse import urlparse

import httpx

TIMEOUT = 6.0
UA = {"User-Agent": "BusinessControl/1.0 (+local link preview)"}

# host suffix -> oEmbed endpoint. All of these are public and keyless.
OEMBED = {
    "youtube.com": "https://www.youtube.com/oembed?format=json&url=",
    "youtu.be": "https://www.youtube.com/oembed?format=json&url=",
    "tiktok.com": "https://www.tiktok.com/oembed?url=",
    "twitter.com": "https://publish.twitter.com/oembed?omit_script=1&url=",
    "x.com": "https://publish.twitter.com/oembed?omit_script=1&url=",
}


def provider_for(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for suffix in ("instagram.com", "facebook.com", *OEMBED):
        if host == suffix or host.endswith("." + suffix):
            return suffix.split(".")[0]
    return host or "link"


def fetch_preview(url: str) -> dict:
    """Returns {provider, title, image, description}; empty strings on failure."""
    out = {"provider": provider_for(url), "title": "", "image": "",
           "description": ""}
    if not url.startswith(("http://", "https://")):
        return out
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    try:
        with httpx.Client(timeout=TIMEOUT, headers=UA,
                          follow_redirects=True) as client:
            endpoint = next((ep for suf, ep in OEMBED.items()
                             if host == suf or host.endswith("." + suf)), None)
            if endpoint:
                r = client.get(endpoint + url)
                if r.status_code == 200:
                    d = r.json()
                    out["title"] = d.get("title") or ""
                    out["image"] = d.get("thumbnail_url") or ""
                    author = d.get("author_name") or ""
                    if author:
                        out["description"] = f"by {author}"
                    if out["title"] or out["image"]:
                        return out
            # OpenGraph fallback (also used when oEmbed came back empty).
            r = client.get(url)
            if r.status_code == 200 and "html" in r.headers.get(
                    "content-type", "html"):
                og = parse_og(r.text)
                for k in ("title", "image", "description"):
                    out[k] = out[k] or og.get(k, "")
    except Exception:
        pass
    return out


def parse_og(page: str) -> dict:
    """Pull og:title / og:image / og:description (plus <title> fallback)."""
    head = page[:60000]
    out = {}
    for prop in ("title", "image", "description"):
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\']og:' + prop +
            r'["\'][^>]+content=["\']([^"\']*)["\']', head, re.I) or re.search(
            r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']og:'
            + prop + r'["\']', head, re.I)
        if m:
            out[prop] = html.unescape(m.group(1)).strip()
    if not out.get("title"):
        m = re.search(r"<title[^>]*>([^<]*)</title>", head, re.I)
        if m:
            out["title"] = html.unescape(m.group(1)).strip()
    return out
