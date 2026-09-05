#!/usr/bin/env python3
"""Run the suite on the days it is most likely to be wrong on.

Two failures in one week came from fixtures that were right on a Friday
and wrong on a Saturday. Neither was findable by reading them; both were
findable by running them on the day they broke. So this runs the whole
suite at a set of dates chosen to be awkward — every weekday, the last
day of a month, the last day of a year, a leap day, and both sides of
each daylight-saving change — and reports which parts fail on which.

    PYTHONPATH=src python3 scripts/audit_dates.py           # the awkward set
    PYTHONPATH=src python3 scripts/audit_dates.py --weekdays  # just the seven

It is not part of the normal suite: it is that suite run seventeen times,
which is a coffee break rather than seconds. Run it when the date
fixtures change, and before trusting a green board on a Tuesday to mean
anything about a Sunday.

Two things the moved clock cannot reach, so a failure in either is this
script's limitation rather than a bug worth chasing:

  * SQLite's own now(). emailer.py has two segment queries using
    strftime('%s','now'), which is the database's clock and not the one
    BC_FAKE_NOW moves. Harmless in production, where both are the same
    OS clock.
  * File modification times. Anything comparing an mtime against the
    clock sees real timestamps against a moved one. A test that wants
    "newer than before" should say that rather than "newer than now" —
    which is a better test anyway, and how the asset-version check now
    reads.
"""
import concurrent.futures as cf
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = ("core", "studio", "platform")


def at(y, m, d, h=10):
    return time.mktime((y, m, d, h, 0, 0, 0, 0, -1))


DATES = [
    # every weekday, because a rota fixture only meets a weekend rarely
    ("Mon", at(2026, 9, 7)), ("Tue", at(2026, 9, 8)),
    ("Wed", at(2026, 9, 9)), ("Thu", at(2026, 9, 10)),
    ("Fri", at(2026, 9, 11)), ("Sat", at(2026, 9, 12)),
    ("Sun", at(2026, 9, 13)),
    # month ends, where "+30 days" and "next month" part company
    ("month-end", at(2026, 1, 31)), ("short-month", at(2026, 2, 28)),
    ("month-end-30", at(2026, 4, 30)),
    # a year end, where a month bucket and a year bucket disagree
    ("year-end", at(2026, 12, 31)), ("new-year", at(2027, 1, 1)),
    # a leap day, and the day after
    ("leap-day", at(2028, 2, 29)), ("post-leap", at(2028, 3, 1)),
    # the clocks changing, where a day is 23 or 25 hours long
    ("dst-spring", at(2027, 3, 14)), ("dst-autumn", at(2026, 11, 1)),
    # and near midnight, where "today" is about to stop being today
    ("late-night", at(2026, 9, 15, 23)),
]


def run(label, when, parts):
    """One date, its parts in parallel — the same shape test_smoke uses,
    because twenty suites end to end is a coffee break and nobody runs a
    check they have to plan around."""
    env = dict(os.environ, BC_FAKE_NOW=str(when), PYTHONPATH="src")
    procs = [(part, subprocess.Popen(
        [sys.executable, f"tests/test_{part}.py"], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
        for part in parts]
    bad = []
    for part, pr in procs:
        out, _ = pr.communicate()
        if pr.returncode != 0:
            fails = [ln for ln in out.splitlines()
                     if ln.startswith("FAIL") or "Error" in ln][-2:]
            bad.append((part, fails or ["(no FAIL line — see the part)"]))
    stamp = time.strftime("%a %Y-%m-%d", time.localtime(when))
    if bad:
        print(f"FAIL  {label:<13} {stamp}", flush=True)
        for part, fails in bad:
            for ln in fails:
                print(f"        {part}: {ln.strip()[:150]}", flush=True)
    else:
        print(f"ok    {label:<13} {stamp}", flush=True)
    return not bad


def main():
    parts = PARTS
    dates = DATES[:7] if "--weekdays" in sys.argv else DATES
    print(f"running {len(parts)} parts at {len(dates)} dates\n", flush=True)
    # A few dates at a time: each one is already three processes, and
    # oversubscribing the box makes the slow parts slower, not the run.
    lanes = max(1, min(4, (os.cpu_count() or 4) // 2))
    with cf.ThreadPoolExecutor(max_workers=lanes) as pool:
        good = sum(pool.map(lambda d: run(d[0], d[1], parts), dates))
    print(f"\n{good}/{len(dates)} dates clean")
    return 0 if good == len(dates) else 1


if __name__ == "__main__":
    sys.exit(main())
