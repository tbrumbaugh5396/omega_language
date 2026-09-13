#!/usr/bin/env python3
"""The test report: what was proved, on which commit, with what beside it.

    PYTHONPATH=src .venv/bin/python scripts/test_report.py
    PYTHONPATH=src .venv/bin/python scripts/test_report.py --suite-log s.log --dates-log d.log

Runs the whole suite and the three-date audit itself — so its numbers are
its own — or reads logs from runs already made. Adds the commit, the
newest coverage summary from reports/coverage/, and every review record
dated since the last report. Writes reports/test-report-<date>.md. The
first line is the verdict; a red one is a release that does not go out.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list) -> str:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          env={**__import__("os").environ, "PYTHONPATH": "src"}).stdout


def parse_suite(text: str) -> dict:
    parts = {p: int(n) for p, n in re.findall(r"^part (\w+): (\d+) checks passed$", text, re.M)}
    total = re.search(r"^all (\d+) checks passed", text, re.M)
    m = re.search(r"^FAILED: ([\w, ]+)", text, re.M)
    failed = [x.strip() for x in m.group(1).split(",")] if m else []
    return {"parts": parts, "total": int(total.group(1)) if total else 0, "failed": failed,
            "green": bool(total) and not failed}


def parse_dates(text: str) -> dict:
    rows = re.findall(r"^(ok|FAIL)\s+(\S+)\s+(.+)$", text, re.M)
    clean = re.search(r"^(\d+)/(\d+) dates clean", text, re.M)
    return {"rows": [{"ok": a == "ok", "name": b, "date": c.strip()} for a, b, c in rows],
            "clean": int(clean.group(1)) if clean else 0, "of": int(clean.group(2)) if clean else 0}


def newest_coverage() -> dict | None:
    d = ROOT / "reports" / "coverage"
    files = sorted(d.glob("*.json")) if d.exists() else []
    return json.loads(files[-1].read_text()) if files else None


def reviews_since(last: str) -> list:
    d = ROOT / "reports" / "reviews"
    out = []
    for f in sorted(d.glob("*.md")) if d.exists() else []:
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)\.md$", f.name)
        if not m or m.group(1) <= last:
            continue
        text = f.read_text()
        reviewer = re.search(r"\*\*Reviewer\*\*\s*\|\s*([^|\n]*)", text)
        defects = len(re.findall(r"^\|\s*\d+\s*\|\s*defect", text, re.M))
        open_ = len(re.findall(r"\|\s*open\s*\|", text, re.I))
        out.append({"date": m.group(1), "title": m.group(2).replace("-", " "),
                    "reviewer": (reviewer.group(1).strip() if reviewer else ""),
                    "defects": defects, "open": open_, "file": f.name})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0]
                                 + " Writes reports/test-report-<date>.md.")
    ap.add_argument("--suite-log", default="", help="a log of tests/test_smoke.py to read instead of running")
    ap.add_argument("--dates-log", default="", help="a log of scripts/audit_dates.py --sample")
    ap.add_argument("--out", default="", help="where to write; default reports/test-report-<date>.md")
    ap.add_argument("--coverage-json", default="", help="a coverage JSON to summarise instead of the newest in reports/coverage/")
    args = ap.parse_args()
    now = dt.datetime.now()
    if args.suite_log:
        suite_txt = Path(args.suite_log).read_text()
    else:
        print("running the suite…", flush=True)
        suite_txt = run([sys.executable, "tests/test_smoke.py"])
    if args.dates_log:
        dates_txt = Path(args.dates_log).read_text()
    else:
        print("running the date audit…", flush=True)
        dates_txt = run([sys.executable, "scripts/audit_dates.py", "--sample"])
    suite, dates = parse_suite(suite_txt), parse_dates(dates_txt)
    sha = run(["git", "rev-parse", "--short", "HEAD"]).strip() or "?"
    cov = json.loads(Path(args.coverage_json).read_text()) if args.coverage_json else newest_coverage()
    reports = sorted((ROOT / "reports").glob("test-report-*.md"))
    last = reports[-1].name[len("test-report-"):-3] if reports else "0000-00-00"
    revs = reviews_since(last)
    cov_ok = cov is None or all(a["ok"] for a in cov["areas"].values())
    green = suite["green"] and dates["of"] and dates["clean"] == dates["of"] and cov_ok
    stamp = now.strftime("%Y-%m-%d")
    verdict = ("GREEN" if green else "RED") + (
        f" · all {suite['total']} checks passed" if suite["green"] else f" · suite failed ({', '.join(suite['failed']) or 'no count'})"
    ) + f" · dates {dates['clean']}/{dates['of']} clean" + (
        "" if cov is None else " · coverage " + ("at or above every floor" if cov_ok else "BELOW A FLOOR"))
    lines = [f"# Test report — {stamp}", "", f"**Verdict:** {verdict}", "",
             "| | |", "|---|---|",
             f"| **Commit** | `{sha}` |",
             f"| **Run on** | {now.strftime('%Y-%m-%d %H:%M')} · {subprocess.run(['hostname'], capture_output=True, text=True).stdout.strip()} |",
             f"| **Suite** | `tests/test_smoke.py` — " + " · ".join(f"{p} {n}" for p, n in suite["parts"].items()) + " |",
             f"| **Date audit** | `scripts/audit_dates.py --sample` — " + " · ".join(
                 f"{r['name']} {'ok' if r['ok'] else 'FAIL'}" for r in dates["rows"]) + " |"]
    if cov:
        a = cov["areas"]
        lines.append(f"| **Coverage** | sensitive {a['sensitive']['pct']}% (floor {a['sensitive']['floor']:.0f}) · "
                     f"server {a['server']['pct']}% (floor {a['server']['floor']:.0f}) — `reports/coverage/{cov['date']}.md` |")
    else:
        lines.append("| **Coverage** | not measured — run `scripts/coverage.py` first |")
    lines += ["", f"## Reviews since {last if last != '0000-00-00' else 'the start'}", ""]
    if revs:
        lines += ["| Date | Change | Reviewer | Defects | Open |", "|---|---|---|---|---|"]
        lines += [f"| {r['date']} | [{r['title']}](reviews/{r['file']}) | {r['reviewer']} | {r['defects']} | {r['open']} |" for r in revs]
    else:
        lines.append("*No review records in `reports/reviews/` since the last report.*")
    lines += ["", "## Anything red", ""]
    reds = []
    if not suite["green"]:
        reds.append("the suite: " + (", ".join(suite["failed"]) or "no count printed"))
    reds += [f"date audit: {r['name']} ({r['date']})" for r in dates["rows"] if not r["ok"]]
    if not dates["of"]:
        reds.append("date audit: no closing count — it did not finish, or the log is not its output")
    if cov and not cov_ok:
        reds += [f"coverage: {a} at {v['pct']}% under its floor {v['floor']:.0f}%" for a, v in cov["areas"].items() if not v["ok"]]
    lines += ["*None.*" if not reds else "\n".join(f"- {r}" for r in reds), ""]
    out = Path(args.out) if args.out else ROOT / "reports" / f"test-report-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(verdict); print(f"report: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
