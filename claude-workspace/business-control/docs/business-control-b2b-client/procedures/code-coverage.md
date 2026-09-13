# Code coverage — the procedure

*Internal. The client sees [the floors and what the number means](../templates/08-build/code-coverage.md); this is how it is measured and what is kept.*

Coverage is measured on every release and on any change to the money, stock
or personal-data areas. The report is an artifact kept with the release.

## Running it

```bash
PYTHONPATH=src .venv/bin/python scripts/coverage.py            # measure, report, write the artifact
PYTHONPATH=src .venv/bin/python scripts/coverage.py --enforce  # and exit non-zero below a floor
PYTHONPATH=src .venv/bin/python scripts/coverage.py --never    # list the never-reached lines in the sensitive areas
```

It runs the three parts of the suite under the coverage tool, in parallel,
against throwaway databases exactly as the suite does, combines the
results, and writes two files under `reports/coverage/`: a Markdown report
for people and a JSON file for the next tool. It takes as long as the suite.

## The areas and their floors

| Area | Files | Floor |
|---|---|---|
| **Sensitive** — money, stock, personal data | payments, accounting, finance, payroll, treasury, pos, inventory, supply, health, datarights, identity, auth, governance, people, students, expenses | **95%** |
| **Server** — everything else under `src/` | the rest | **85%** |
| **Browser** | `*.js` under the frontends | not measured by line — behaviour is tested through the suite's browser checks and the guards |

The map lives in `scripts/coverage.py` as `SENSITIVE`. A new module that
touches money, stock or a person goes on that list in the same change that
creates it.

## Reading the report

The percentage is the floor, not the grade. Read the report top to bottom:

1. **Per area**: at or above the floor, or not. Below is a release blocker.
2. **Per file, sorted worst first**: the files with the most unreached lines.
3. **The never-reached list** for the sensitive areas: every line, with a
   reason written beside it in the report before release. Acceptable reasons
   are few: a defensive branch for a condition the database makes
   impossible; a third-party failure that cannot be simulated. "Hard to
   test" is not one.

## New code

New code in a change is held to the floor on its own, not averaged into old
code that has it. The reviewer checks this with the checklist's item 4: a
sentence that can be false for every branch that matters.

## When the number is wrong

Coverage counts a line as reached if any test ran it, asserting or not. So
a high number with few sentences is suspicious, and a defect that reached
the live system through a "covered" line means the test was the problem:
it is rewritten to be false for that defect, and the record says so.

## Lowering a floor

Only in writing, in the client's own quality document, with the client's
agreement, before the release. There is no other way.
