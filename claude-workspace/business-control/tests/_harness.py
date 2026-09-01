"""The shared floor under the split smoke suite.

Each part file (test_core, test_studio, test_platform) imports this first:
it claims a FRESH throwaway data directory for its own process, builds the
TestClient, and provides ok() with the part's running check count. Parts
are independent by construction — each starts from an empty database and
builds exactly the state it tests — which is what lets test_smoke.py run
them in parallel and add the counts up.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Each part process gets its own data dir, whatever the caller exported —
# a shared dir across parallel parts would be the flakiest test in the file.
os.environ["BUSINESS_CONTROL_DATA"] = tempfile.mkdtemp(prefix="bc_test_")

from fastapi.testclient import TestClient  # noqa: E402
from erp.backend.main import app, CFG  # noqa: E402

c = TestClient(app)
checks = 0


def ok(cond, label):
    global checks
    checks += 1
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"  ok: {label}")


def mint_admin(name="Boss"):
    """The founder, by key — the same first act every part needs."""
    u = c.post("/api/login",
               json={"name": name, "admin_key": CFG["admin_key"]}).json()
    return u, {"Authorization": f"Bearer {u['token']}"}


def ops_app_parts():
    """The ops app's source files, in serve order."""
    return sorted((ROOT / "src" / "erp" / "frontend" / "app").glob("*.js"))


def ops_app_js():
    """The ops app as the browser receives it — the parts, concatenated.
    Tests that grep the app read THIS, so they hold whichever file a
    section lives in."""
    return "\n".join(p.read_text(encoding="utf-8") for p in ops_app_parts())


def done(part):
    """Each part's closing line — the runner reads the number off it."""
    print(f"\npart {part}: {checks} checks passed")
