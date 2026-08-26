"""Export one page section as a standalone HTML file you can open on its own.

Used to keep the hero around for reference after it came off the home page.
It renders through the same renderer the storefront uses, so the file is what
the section actually looked like, not a hand-copy that drifts.

The icon sprite is inlined because `<use href="#i-arrow">` resolves against
the current document — link the sprite instead and every glyph comes out
blank. The stylesheet stays a link so the export tracks the live design;
open it from the running site (/reference/<name>.html) rather than the
filesystem.

    PYTHONPATH=src python3 tools/export_section.py hero --page home
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from erp.backend import config, db                        # noqa: E402
from storefront.backend import sections as sect           # noqa: E402

OUT = config.STOREFRONT_DIR / "reference"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — reference</title>
<link rel="stylesheet" href="/store.css">
<style>
  body {{ padding: 0; }}
  .ref-note {{ font-family: var(--ui); font-size: 13px; color: var(--ink-soft);
    background: #faf7ff; border-bottom: 1px solid var(--line);
    padding: 10px 20px; }}
  .ref-note code {{ font-size: 12px; }}
</style></head>
<body>
<p class="ref-note">Reference copy of the <b>{title}</b> section, exported
from the live theme. Regenerate with
<code>PYTHONPATH=src python3 tools/export_section.py {stype}</code>.</p>
{sprite}
{body}
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stype", help="section type, e.g. hero")
    ap.add_argument("--page", default="home")
    ap.add_argument("--name", default="")
    args = ap.parse_args()

    con = db.connect()
    row = con.execute(
        "SELECT * FROM page_sections WHERE page_slug=? AND type=?"
        " ORDER BY position LIMIT 1", (args.page, args.stype)).fetchone()
    if row is None:
        raise SystemExit(f"no {args.stype!r} section on page {args.page!r}")

    body = sect.render_page(con, [dict(row, enabled=1)])
    sprite = (config.STOREFRONT_DIR / "icons.svg").read_text()

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{args.name or args.stype}.html"
    out.write_text(PAGE.format(
        title=sect.SECTION_TYPES.get(args.stype, {}).get("label", args.stype),
        stype=args.stype, sprite=sprite, body=body))
    print(f"wrote {out}  ({out.stat().st_size / 1024:.1f} KB)")
    print(f"open it at /reference/{out.name} on the running store")


if __name__ == "__main__":
    main()
