"""The price book, parsed — so the storefront quotes the same numbers.

docs/product/price-book.md is the source; the deck and the quote bench carry
copies, and the test suite holds all three to it. This module makes the book
READABLE BY CODE, so the studio's own storefront takes a fourth copy of
nothing: it reads the tables. A price changed in the book reaches the shop by
re-seeding, and a table this parser cannot read raises rather than quietly
selling the wrong figure.

Nothing here is business-control-specific except the file it reads. A tenant
selling a different thing seeds its own catalogue from wherever it keeps its
own prices.
"""
import re
from pathlib import Path

BOOK = (Path(__file__).resolve().parents[3] / "docs" / "product"
        / "price-book.md")

GROUP_NOTE = {
    "Operations": "Making and moving what you sell.",
    "Revenue ops": "Selling it, and keeping the people who bought.",
    "Finance": "The money, from a payment to a filed year.",
    "People & management": "The people who do the work, and what the work "
                           "is telling you.",
    "IT & legal": "The plumbing everything else stands on.",
}


def _text() -> str:
    return BOOK.read_text(encoding="utf-8")


def _section(head: str, src: str) -> str:
    m = re.search(rf"^## {re.escape(head)}.*?(?=^## |\Z)", src,
                  re.M | re.S)
    if not m:
        raise ValueError(f"price book: no section '{head}'")
    return m.group(0)


def capabilities() -> list:
    """[{name, group, band, price, requires}] — §3, in the book's order."""
    src = _section("3. Capabilities", _text())
    out, group = [], ""
    for line in src.splitlines():
        g = re.match(r"^\| \*\*(.+?)\*\* \| \| \| \|", line)
        if g:
            group = g.group(1)
            continue
        m = re.match(r"^\| ([A-Z][^|*]+?)(?: \*)? \| (Light|Standard|Heavy)"
                     r" \| \*\*\$(\d+)\*\* \| (.+?) \|", line)
        if m:
            out.append({"name": m.group(1).strip(), "group": group,
                        "band": m.group(2).lower(), "price": int(m.group(3)),
                        "requires": m.group(4).strip()})
    if len(out) != 27:
        raise ValueError(f"price book: parsed {len(out)} capabilities, not 27")
    return out


def bands() -> dict:
    src = _section("2. The bands", _text())
    out = {m.group(1).lower(): int(m.group(2)) for m in re.finditer(
        r"^\| \*\*(Light|Standard|Heavy)\*\* \| \*\*\$(\d+)\*\*", src, re.M)}
    if len(out) != 3:
        raise ValueError("price book: the band table did not parse")
    return out


def core_price() -> int:
    m = re.search(r"^## 4\. Platform Core — \$(\d+)", _text(), re.M)
    if not m:
        raise ValueError("price book: no Platform Core price")
    return int(m.group(1))


def _column_table(src: str, headings: list) -> dict:
    """A price-book comparison table: first column is the row label, the
    rest are the products. Returns {product: {row label: cell}}."""
    rows = [r for r in src.splitlines() if r.startswith("|")]
    out = {h: {} for h in headings}
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        label = cells[0].strip("* ")
        if not label or len(cells) - 1 != len(headings):
            continue
        for h, v in zip(headings, cells[1:]):
            out[h][label] = v.strip()
    return out


def _money(cell: str) -> int:
    m = re.search(r"\$([\d,]+)", cell or "")
    return int(m.group(1).replace(",", "")) if m else 0


def tiers() -> list:
    """The three packaged plans — §6, with what each covers."""
    src = _section("6. Packaged tiers", _text())
    t = _column_table(src, ["Starter", "Pro", "Scale"])
    out = []
    for name in ("Starter", "Pro", "Scale"):
        row = t[name]
        out.append({
            "name": name, "price": _money(row.get("Monthly", "")),
            "locations": row.get("Locations", ""),
            "seats": row.get("Staff seats", ""),
            "capabilities": row.get("Capabilities", "").replace("+ ", ""),
            "adds": row.get("Capabilities", "").startswith("+"),
            "email": row.get("Email", ""), "chatbot": row.get("Chatbot", ""),
        })
    if [x["price"] for x in out] != sorted(x["price"] for x in out):
        raise ValueError("price book: tiers are not in ascending order")
    return out


def care_plans() -> list:
    """Part 2 of the bill — §12's care table."""
    src = _section("12. Services", _text())
    t = _column_table(src, ["Essential", "Standard", "Priority"])
    out = []
    for name in ("Essential", "Standard", "Priority"):
        row = t[name]
        out.append({
            "name": name, "price": _money(row.get("Monthly", "")),
            "response": row.get("First response", ""),
            "defects": row.get("Defect targets", ""),
            "updates": row.get("Updates", ""),
            "monitoring": row.get("Key journeys watched", ""),
            "included": row.get("Content changes included", ""),
        })
    if not all(x["price"] for x in out):
        raise ValueError("price book: a care plan has no price")
    return out


def builds() -> list:
    """The one-time build ladder — §12."""
    src = _section("12. Services", _text())
    out = []
    for m in re.finditer(r"^\| (Guided setup|Launch build|Custom build"
                         r"|Flagship) \| \$([\d,]+) \|", src, re.M):
        out.append({"name": m.group(1),
                    "price": int(m.group(2).replace(",", ""))})
    if len(out) != 4:
        raise ValueError("price book: the build ladder did not parse")
    return out


def bundles() -> list:
    """§13 — the worked examples, which are the honest way to show a price."""
    src = _section("13. Bundles", _text())
    out = []
    for m in re.finditer(r"^\| ([A-Z][^|]+?) \| (\d+) \| \$(\d+) \| ([^|]*)"
                         r" \| ([^|]*) \| \*\*\$([\d,.]+)\*\* \|", src, re.M):
        out.append({"name": m.group(1).strip(), "count": int(m.group(2)),
                    "sum": int(m.group(3)), "volume": m.group(4).strip(),
                    "other": m.group(5).strip(),
                    "monthly": float(m.group(6).replace(",", ""))})
    if not out:
        raise ValueError("price book: the bundle table did not parse")
    return out


def groups() -> list:
    """Capability groups in book order, with their capabilities."""
    caps = capabilities()
    seen = []
    for c in caps:
        if c["group"] not in seen:
            seen.append(c["group"])
    return [{"name": g, "note": GROUP_NOTE.get(g, ""),
             "items": [c for c in caps if c["group"] == g]} for g in seen]
