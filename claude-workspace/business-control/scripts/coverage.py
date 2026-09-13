#!/usr/bin/env python3
"""Coverage: which lines the suite reached, per area against its floor.

    PYTHONPATH=src .venv/bin/python scripts/coverage.py            # measure, report, write the artifact
    PYTHONPATH=src .venv/bin/python scripts/coverage.py --enforce  # exit non-zero below a floor
    PYTHONPATH=src .venv/bin/python scripts/coverage.py --never    # the never-reached lines, sensitive areas

Runs the three parts of the suite under the coverage tool, in parallel,
against throwaway databases exactly as tests/test_smoke.py does, combines
the results, and writes reports/coverage/<date>.md and .json. The areas
and their floors are the ones the client's quality document promises:
sensitive — money, stock, personal data — 95%; the rest of the server 85%.
The browser code is not measured by line; its behaviour is tested through
the suite's browser checks and the frontend guards.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = ("core", "studio", "platform")
SENSITIVE = ("payments", "accounting", "finance", "payroll", "treasury", "pos",
             "inventory", "supply", "health", "datarights", "identity", "auth",
             "governance", "people", "students", "expenses")
FLOORS = {"sensitive": 95.0, "server": 85.0}


def area_of(path: str) -> str:
    name = Path(path).stem
    return "sensitive" if name in SENSITIVE else "server"


def run_suite(python: str) -> int:
    env = dict(os.environ, PYTHONPATH="src", COVERAGE_FILE=str(ROOT / ".coverage"))
    for f in ROOT.glob(".coverage*"):
        f.unlink()
    procs = [subprocess.Popen(
        [python, "-m", "coverage", "run", "--parallel-mode", "--source=src",
         "--omit=*/vendor/*", f"tests/test_{p}.py"], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for p in PARTS]
    rc = 0
    for p, pr in zip(PARTS, procs):
        out, _ = pr.communicate()
        ok = pr.returncode == 0 and f"part {p}:" in out
        print(f"  {p:<9} {'passed' if ok else 'FAILED'}", flush=True)
        rc |= 0 if ok else 1
    subprocess.run([python, "-m", "coverage", "combine"], cwd=ROOT, env=env, check=False,
                   stdout=subprocess.DEVNULL)
    subprocess.run([python, "-m", "coverage", "json", "-o", str(ROOT / ".coverage.json"), "-q"],
                   cwd=ROOT, env=env, check=False)
    return rc


def summarise(data: dict) -> dict:
    areas = {a: {"covered": 0, "total": 0, "files": []} for a in FLOORS}
    for path, f in data["files"].items():
        if not path.replace("\\", "/").startswith("src/") or path.endswith("__init__.py"):
            continue
        a = area_of(path)
        s = f["summary"]
        areas[a]["covered"] += s["covered_lines"]
        areas[a]["total"] += s["num_statements"]
        areas[a]["files"].append({"file": path, "pct": round(s["percent_covered"], 1),
                                  "missed": s["missing_lines"], "lines": f.get("missing_lines", [])})
    for a, v in areas.items():
        v["pct"] = round(100.0 * v["covered"] / v["total"], 1) if v["total"] else 0.0
        v["floor"] = FLOORS[a]
        v["ok"] = v["pct"] >= FLOORS[a]
        v["files"].sort(key=lambda x: -x["missed"])
    return areas


def write_report(areas: dict, when: dt.datetime, sha: str, never: bool) -> Path:
    out_dir = ROOT / "reports" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = when.strftime("%Y-%m-%d")
    verdict = "at or above every floor" if all(v["ok"] for v in areas.values()) else "BELOW A FLOOR"
    lines = [f"# Coverage — {stamp}", "",
             f"**{verdict}** · commit `{sha}` · run {when.strftime('%Y-%m-%d %H:%M')}", "",
             "| Area | Reached | Floor | Statements | |", "|---|---|---|---|---|"]
    for a, v in areas.items():
        lines.append(f"| {a} | **{v['pct']}%** | {v['floor']}% | {v['covered']} / {v['total']} | "
                     f"{'ok' if v['ok'] else 'BELOW'} |")
    for a, v in areas.items():
        lines += ["", f"## {a} — files, most unreached first", "",
                  "| File | Reached | Unreached lines |", "|---|---|---|"]
        for f in v["files"][:40]:
            lines.append(f"| `{f['file']}` | {f['pct']}% | {f['missed']} |")
    if never:
        lines += ["", "## Never reached — sensitive areas", "",
                  "Every line here needs a reason written beside it before release.", ""]
        for f in areas["sensitive"]["files"]:
            if f["lines"]:
                lines.append(f"- `{f['file']}`: " + ", ".join(str(n) for n in f["lines"][:200])
                             + (" …" if len(f["lines"]) > 200 else ""))
    md = out_dir / f"{stamp}.md"
    md.write_text("\n".join(lines) + "\n")
    (out_dir / f"{stamp}.json").write_text(json.dumps(
        {"date": stamp, "commit": sha, "areas": {a: {k: v[k] for k in ("pct", "floor", "ok", "covered", "total")}
                                                 for a, v in areas.items()}}, indent=1))
    return md


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0]
                                 + " Writes reports/coverage/<date>.md and .json.")
    ap.add_argument("--enforce", action="store_true", help="exit non-zero below a floor")
    ap.add_argument("--never", action="store_true", help="list never-reached lines in the sensitive areas")
    ap.add_argument("--from-json", default="", help="report from an existing coverage JSON, run nothing")
    args = ap.parse_args()
    try:
        import coverage  # noqa: F401
    except ImportError:
        print("pip install coverage (it is in requirements-dev.txt)")
        return 2
    t0 = time.time()
    if args.from_json:
        data = json.loads(Path(args.from_json).read_text())
        rc = 0
    else:
        print("running the three parts under coverage…", flush=True)
        rc = run_suite(sys.executable)
        data = json.loads((ROOT / ".coverage.json").read_text())
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                         text=True).stdout.strip() or "?"
    areas = summarise(data)
    md = write_report(areas, dt.datetime.now(), sha, args.never)
    for a, v in areas.items():
        print(f"{a:<10} {v['pct']:>6}%  floor {v['floor']}%  {'ok' if v['ok'] else 'BELOW'}")
    print(f"report: {md.relative_to(ROOT)}  ({int(time.time() - t0)}s)")
    if rc:
        print("the suite was not green — the number above is of a failing run")
        return 1
    if args.enforce and not all(v["ok"] for v in areas.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
