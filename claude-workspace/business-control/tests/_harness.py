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

# --- the clock, when somebody wants to run this on a different day -------
# Two failures in one week came from fixtures that were right on a Friday
# and wrong on a Saturday: "+35 days" meaning "next month", and a shift on
# next Monday meeting a holiday anchored to tomorrow. Neither is findable
# by reading, and both are findable by running the suite on the day it
# breaks. BC_FAKE_NOW moves the whole process to that day.
#
# Time still runs forward from there rather than freezing: a frozen clock
# is its own kind of unreality, and TTLs that never advance would hide
# exactly the expiry bugs this is meant to surface.
_fake = os.environ.get("BC_FAKE_NOW")
if _fake:
    import datetime as _dtm
    import time as _tm

    _origin = float(_fake)
    _real_time = _tm.time                      # the genuine one, kept
    _started = _real_time()
    _tm.time = lambda: _origin + (_real_time() - _started)

    # date.today() and datetime.now() reach the clock through C rather
    # than through time.time(), so they need saying separately or the
    # nutrition and cycles screens would still be living in the present.
    class _Date(_dtm.date):
        @classmethod
        def today(cls):
            return cls.fromtimestamp(_tm.time())

    class _DateTime(_dtm.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(_tm.time(), tz)

        @classmethod
        def utcnow(cls):
            return cls.utcfromtimestamp(_tm.time())

    _dtm.date, _dtm.datetime = _Date, _DateTime
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
