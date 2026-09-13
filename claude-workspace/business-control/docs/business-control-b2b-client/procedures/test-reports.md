# Test reports — the procedure

*Internal. What is kept, per release, so the codebase is delivered with the evidence beside it.*

A release is not delivered as code alone. It is delivered with three
artifacts that say what was proved, how much was reached, and what a second
person read. They live under `reports/` in the repository, next to the code
they describe, and the client's copy of the release includes them.

## The three artifacts

| Artifact | Made by | Where |
|---|---|---|
| **Test report** — the suite's counts per part, the date audit, the commit, the coverage summary, the reviews since the last release | `scripts/test_report.py` | `reports/test-report-YYYY-MM-DD.md` |
| **Coverage report** — per area against its floor, per file, the never-reached lines | `scripts/coverage.py` | `reports/coverage/YYYY-MM-DD.md` and `.json` |
| **Review records** — one per change | a person, from the template | `reports/reviews/YYYY-MM-DD-<title>.md` |

## Producing a release's report

```bash
PYTHONPATH=src .venv/bin/python scripts/coverage.py            # first: the coverage artifact
PYTHONPATH=src .venv/bin/python scripts/test_report.py         # then: runs the suite and the date audit, writes the report
```

The report script runs the whole suite and the three-date audit itself, so
its numbers are its own and not a paste from somebody's terminal. It reads
the newest coverage JSON and lists every review record dated since the last
report. Ten minutes on a laptop. If anything is red, the report says so in
its first line and the release does not go out.

For a report from runs already made — a CI machine, a log kept from the
push hook — pass the logs instead: `--suite-log path --dates-log path`.

## What goes to the client

The Markdown report, the coverage Markdown, and the review records, as they
are. They are written so a client can read them; nothing in them is
internal shorthand, and nothing in them is a secret. The client's quality
documents (stage 08) promise exactly these, so a release without them is
a broken promise, not an oversight.

## Keeping them

Reports are committed with the release. They are small. Ten years of them
is the history of how carefully the thing was built, which is worth more
than the disk it costs. Never edit a report after the fact; a correction is
a new report that says what it corrects.

Template for a hand-written report, when the script cannot run:
[`templates/test-report.md`](templates/test-report.md).
