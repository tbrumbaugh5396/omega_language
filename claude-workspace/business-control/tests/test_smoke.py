"""The smoke suite's front door — same command, same closing line, three
processes now instead of one.

The old single file ran 4-5 minutes and a failure at check 200 hid
everything behind it. The suite is now three independent parts, each a
script-style file over its own throwaway database:

  test_core.py      the single-tenant install: commerce, ops, workforce,
                    supply, integrations, the storefront face
  test_studio.py    the B2B paperwork: kit, engagements, vault, portal,
                    binders, quotes, the scope of work
  test_platform.py  tenancy and up: the split, the router, fleet and
                    worker nodes, entitlements, Learning on tenant alpha

This runner starts all three in parallel, streams nothing while they run,
and then prints each part's own transcript in order — so the output reads
the way it always did, and `all N checks passed` still means what it
meant. One part failing prints that part's tail and exits 1; the others'
results still print, because a failure in core no longer hides what
studio and platform found.

  PYTHONPATH=src .venv/bin/python tests/test_smoke.py            # all three
  PYTHONPATH=src .venv/bin/python tests/test_smoke.py --only core
  PYTHONPATH=src .venv/bin/python tests/test_core.py             # same thing
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = ("core", "studio", "platform")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=PARTS,
                    help="run one part in this terminal, live")
    args = ap.parse_args()

    if args.only:
        # Live and unbuffered — the debugging mode.
        return subprocess.call([sys.executable, "-u",
                                str(HERE / f"test_{args.only}.py")])

    t0 = time.time()
    procs = {p: subprocess.Popen(
        [sys.executable, str(HERE / f"test_{p}.py")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for p in PARTS}

    total, failed = 0, []
    for p in PARTS:
        out, _ = procs[p].communicate()
        m = re.search(rf"^part {p}: (\d+) checks passed$", out, re.M)
        if procs[p].returncode != 0 or not m:
            failed.append(p)
            tail = "\n".join(out.rstrip().split("\n")[-30:])
            print(f"\n==== {p}: FAILED "
                  f"(exit {procs[p].returncode}) ====\n{tail}")
        else:
            total += int(m.group(1))
            print(out.rstrip())

    took = time.time() - t0
    if failed:
        print(f"\nFAILED: {', '.join(failed)} — rerun one live with "
              f"--only {failed[0]}")
        return 1
    print(f"\nall {total} checks passed  ({took:.0f}s, "
          f"{len(PARTS)} parts in parallel)")
    return 0


if __name__ == "__main__":
    # The exit status is a gate: the pre-push hook refuses a push on it,
    # and CI reads it. So it is decided HERE, from the results, and not
    # left to interpreter shutdown — a failed flush at teardown exits 120
    # of its own accord, which reads as "the suite failed" long after the
    # suite has printed that every check passed. Flush what we wrote,
    # then leave immediately with the status the run actually earned.
    _code = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (BrokenPipeError, OSError):
        pass
    os._exit(_code)
