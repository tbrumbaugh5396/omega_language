"""Split the single install into two tenants: zenjoy and studio.

One-shot. The existing data/ holds two businesses at once — ZenJoy's
storefront, orders and routes, AND the studio's client pipeline
(engagements, documents, signatures, quotes). This pulls them apart:

  data/tenants/zenjoy/  — a full copy, minus the pipeline. ZenJoy's shop,
                          exactly as it was, including today's theme
                          written into store_meta so neutralising
                          THEME_DEFAULT changed nothing it can see.
  data/tenants/studio/  — a fresh install that inherits the pipeline
                          tables, the admin accounts (tokens intact, so
                          sign-ins survive), the documents on disk, and
                          the Business Control brand.

Bare localhost answers as studio — the operator's cockpit; ZenJoy answers
at zenjoy.localhost. The original database stays behind, renamed
*.pre-split.db: the escape hatch.

Usage: python scripts/split_tenants.py [--force]
Refuses while the server is running, and refuses to run twice.
"""
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from erp.backend import config, tenancy  # noqa: E402

# The pipeline: what the studio keeps and ZenJoy must not. A client's
# install containing the studio's quotes ABOUT that client is the wall
# failing in the most embarrassing direction available.
PIPELINE_TABLES = [
    "engagements", "engagement_docs", "engagement_gates",
    "engagement_dates", "engagement_log",
    "documents", "document_signatures", "document_events",
]

# ZenJoy's theme as it rendered before THEME_DEFAULT went neutral — written
# into the zenjoy tenant's store_meta so its storefront does not change by
# one pixel. Values match the old code default verbatim.
ZENJOY_THEME = {
    "brand": "zenjoy", "dot": ".",
    "title": "Zenjoy — Feel Good, Naturally",
    "description": "Functional beverages that help you unwind. "
                   "Shop the collection.",
    "announce": ["Free shipping over $40",
                 "200mg L-theanine in every can"],
    "footer": "© 2026 Zenjoy · powered by business-control",
    # ZenJoy sells a canned drink; the drawn can is its stand-in art. The
    # code default is the neutral card, because most tenants do not.
    "art": "can",
}


def copy_table(src, dst, table):
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
    rows = src.execute(f"SELECT * FROM {table}").fetchall()
    if not rows:
        return 0
    ph = ",".join("?" * len(cols))
    dst.executemany(
        f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({ph})",
        rows)
    return len(rows)


def main() -> int:
    force = "--force" in sys.argv
    pid = config.DATA_DIR / "server.pid"
    if pid.exists():
        print("Server appears to be running — stop it first.")
        return 1
    if tenancy.REGISTRY_PATH.exists() and not force:
        print("data/tenants.json already exists — the split has run. "
              "(--force to re-run against a restored data dir.)")
        return 1
    src_db = config.DATA_DIR / "business_control.db"
    if not src_db.exists():
        print("No data/business_control.db to split.")
        return 1

    tenants = config.DATA_DIR / "tenants"

    # ---- zenjoy: the whole current install, minus the pipeline ----------
    zdir = tenants / "zenjoy"
    if zdir.exists() and force:
        shutil.rmtree(zdir)
    zdir.mkdir(parents=True)
    shutil.copy2(src_db, zdir / "business_control.db")
    for name in ("config.json", "vapid_private.pem"):
        p = config.DATA_DIR / name
        if p.exists():
            shutil.copy2(p, zdir / name)
    if (config.DATA_DIR / "uploads").is_dir():
        shutil.copytree(config.DATA_DIR / "uploads", zdir / "uploads")
    # the pipeline leaves; so do its files
    shutil.rmtree(zdir / "uploads" / "documents", ignore_errors=True)
    zcon = sqlite3.connect(zdir / "business_control.db")
    for t in PIPELINE_TABLES:
        try:
            zcon.execute(f"DELETE FROM {t}")
        except sqlite3.OperationalError:
            pass
    # the theme the neutral default no longer provides
    zcon.execute("INSERT OR REPLACE INTO store_meta(k,v) VALUES('theme',?)",
                 (json.dumps(ZENJOY_THEME),))
    # ...and the one line of interface copy that was ZenJoy's voice living
    # in the shared storefront script.
    zcon.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                 " VALUES('ui_strings',?)",
                 (json.dumps({"shop_cta": "Shop your Zen",
                              "offer_title":
                                  "Take 10% off your first calm.",
                              "cart_tag": "breathe in, check out.",
                              "cart_note": "Free shipping over $40 · skip "
                                           "or cancel boxes any time"}),))
    # ...and its ticket references and topic wording, which were also the
    # codebase's until they became tenant data.
    zcon.execute("INSERT OR REPLACE INTO store_meta(k,v)"
                 " VALUES('support_contact',?)",
                 (json.dumps({"ref_prefix": "ZJ",
                              "topics": {"product":
                                         "A question about the drinks"}}),))
    # zenjoy's ops app is ZenJoy's, not the studio's
    zcfg = json.loads((zdir / "config.json").read_text())
    zcfg["brand_name"] = "Zenjoy"
    (zdir / "config.json").write_text(json.dumps(zcfg, indent=2))
    zcon.commit()
    zcon.close()

    # ---- studio: fresh schema + the pipeline + the operators ------------
    sdir = tenants / "studio"
    if sdir.exists() and force:
        shutil.rmtree(sdir)
    sdir.mkdir(parents=True)
    # same operator, same key: the studio inherits the original secrets
    ocfg = {}
    if (config.DATA_DIR / "config.json").exists():
        ocfg = json.loads((config.DATA_DIR / "config.json").read_text())
    scfg = {k: ocfg[k] for k in
            ("admin_key", "pin_pepper", "smtp", "email_from",
             "public_base_url", "require_passwords") if k in ocfg}
    scfg["brand_name"] = "Business Control"
    (sdir / "config.json").write_text(json.dumps(scfg, indent=2))

    tok = tenancy.CURRENT.set("studio")
    try:
        # importing main runs the legacy init once against the bare dir —
        # acceptable (idempotent) — then init_tenant gives studio schema
        from erp.backend.main import init_tenant
        init_tenant("studio")
        scon = sqlite3.connect(sdir / "business_control.db")
        ocon = sqlite3.connect(src_db)
        ocon.row_factory = sqlite3.Row
        moved = {}
        for t in PIPELINE_TABLES + ["email_log"]:
            try:
                moved[t] = copy_table(ocon, scon, t)
            except sqlite3.OperationalError as e:
                print(f"  skip {t}: {e}")
        # the operators: admin accounts cross with their tokens, so the
        # same sign-in works on the studio cockpit tomorrow morning
        cols = [r[1] for r in ocon.execute("PRAGMA table_info(users)")]
        admins = ocon.execute(
            "SELECT * FROM users WHERE is_admin=1 AND active=1").fetchall()
        ph = ",".join("?" * len(cols))
        scon.executemany(
            f"INSERT OR REPLACE INTO users({','.join(cols)}) VALUES({ph})",
            [tuple(r) for r in admins])
        scon.commit()
        scon.close()
        ocon.close()
    finally:
        tenancy.CURRENT.reset(tok)

    # documents on disk, and the exported client folders, follow the tables
    docs_src = config.DATA_DIR / "uploads" / "documents"
    if docs_src.is_dir():
        shutil.copytree(docs_src, sdir / "uploads" / "documents",
                        dirs_exist_ok=True)
    exp = config.DATA_DIR / "exports"
    if exp.is_dir():
        shutil.copytree(exp, sdir / "exports", dirs_exist_ok=True)

    # ---- the registry: who answers to which name ------------------------
    tenancy.REGISTRY_PATH.write_text(json.dumps({
        "default": "studio",
        "provider": "studio",
        "tenants": {
            "studio": {"hosts": ["localhost", "127.0.0.1"],
                       "created": time.time()},
            "zenjoy": {"hosts": ["zenjoy.localhost"],
                       "created": time.time()},
        }}, indent=2))

    # the escape hatch: the un-split database stays, renamed
    src_db.rename(config.DATA_DIR / "business_control.pre-split.db")
    for suffix in ("-wal", "-shm"):
        p = Path(str(src_db) + suffix)
        if p.exists():
            p.unlink()

    print("split complete:")
    print(f"  studio  → http://localhost:8860        "
          f"({sum(moved.values())} pipeline rows, {len(admins)} admins)")
    print("  zenjoy  → http://zenjoy.localhost:8860  (the shop, as it was)")
    print("  escape hatch: data/business_control.pre-split.db")
    return 0


if __name__ == "__main__":
    sys.exit(main())
