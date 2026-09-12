#!/usr/bin/env python3
"""Translate a shop into every major language, from the command line.

    PYTHONPATH=src .venv/bin/python scripts/translate.py --tenant studio \\
        --locales all --engine argos                # a pip package, no key, offline
    …/translate.py --tenant studio --locales all --engine anthropic --key sk-ant-…

    …/translate.py --tenant studio --locales es,fr,de --dry-run
    …/translate.py --tenant studio --locales all --force-machine

The same algorithm the Store admin button runs, for a whole language
list at once and without a browser: offer each language, then send the
engine only what that language still lacks — the interface's words when
nothing shipped for it, and every product, page, section, menu and kind
— in batches sized by characters, dropping any answer that lost a
placeholder or a tag, and marking what it keeps as the machine's. Typed
translations are never touched; machine ones only with --force-machine.
Run it again after adding products; it sends only the new ones.

The engine and key given here are used for this run and saved on the
tenant unless --no-save, so the button in Store admin works afterwards
too. Nothing is printed that a key could be read from.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tenant", default="", help="tenant id; blank = the single-tenant install")
    ap.add_argument("--locales", default="all",
                    help="comma-separated codes, or 'all' for every major language, "
                         "or 'offered' for what the shop already offers")
    ap.add_argument("--engine", choices=("argos", "nllb", "libretranslate", "deepl", "openai", "anthropic"),
                    help="which translator; omit to use the one saved on the tenant. "
                         "argos and nllb are Python packages run in this process — no server, no key")
    ap.add_argument("--key", default="", help="the engine's API key")
    ap.add_argument("--url", default="", help="the engine's address, where one is needed")
    ap.add_argument("--model", default="", help="the model, for an LLM engine")
    ap.add_argument("--dry-run", action="store_true", help="count what would be sent, send nothing")
    ap.add_argument("--force-machine", action="store_true",
                    help="translate machine-made rows again (typed ones are never touched)")
    ap.add_argument("--no-offer", action="store_true", help="fill without adding to the picker")
    ap.add_argument("--no-save", action="store_true", help="do not keep the engine on the tenant")
    ap.add_argument("--ui-only", action="store_true", help="only the interface's words")
    args = ap.parse_args()

    import json
    from erp.backend import db, tenancy
    from storefront.backend import content as C

    tok = None
    if args.tenant:
        if tenancy.registry() and args.tenant not in tenancy.all_tenants():
            print(f"no tenant called {args.tenant!r}; known: {', '.join(tenancy.all_tenants())}")
            return 2
        tok = tenancy.CURRENT.set(args.tenant)
    try:
        con = db.connect()
        C.init_tables(con)
        if args.engine:
            cur = C._mt_cfg(con)
            cfg = {"engine": args.engine, "url": args.url, "model": args.model,
                   "key": args.key or cur.get("key", "")}
            if args.no_save:
                C._mt_cfg = lambda _con, _cfg=cfg: _cfg      # this run only
            else:
                con.execute("INSERT INTO store_meta(k,v) VALUES('mt',?)"
                            " ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(cfg),))
                con.commit()
        if args.locales == "all":
            codes = [c for c, _ in C.LANGUAGES if c != "en"]
        elif args.locales == "offered":
            codes = [c for c in C.locales(con) if c != "en"]
        else:
            codes = [c.strip().lower() for c in args.locales.split(",") if c.strip() and c.strip() != "en"]
        if not args.no_offer and not args.dry_run:
            C.offer_languages(con, codes)
        print(f"{'language':<8} {'sent':>6} {'kept':>6} {'dropped':>8} {'left':>6}")
        total = 0
        for code in codes:
            try:
                r = C.fill_locale(con, code, force_machine=args.force_machine,
                                  dry_run=args.dry_run, include_ui=True)
            except Exception as e:                            # noqa: BLE001
                detail = getattr(e, "detail", str(e))
                print(f"{code:<8} {'—':>6} {'—':>6} {'—':>8} {'—':>6}  {detail}")
                return 1
            if args.dry_run:
                print(f"{code:<8} {r['would_send']:>6} {'':>6} {'':>8} {'':>6}  ~{r['characters']:,} characters")
            else:
                print(f"{code:<8} {r['filled'] + r['dropped']:>6} {r['filled']:>6} {r['dropped']:>8} {r['remaining']:>6}")
                total += r["filled"]
        if not args.dry_run:
            print(f"\n{total} translations written as the machine's across {len(codes)} languages. "
                  f"Read them over on Store admin → Languages; typing a line replaces the machine's.")
        return 0
    finally:
        if tok is not None:
            tenancy.CURRENT.reset(tok)


if __name__ == "__main__":
    raise SystemExit(main())
