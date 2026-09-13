# Code review — the procedure

*Internal. The client sees [what review means](../templates/08-build/code-review.md); this is how it is done, and what is kept.*

Every change is read by a second person before it merges. Not skimmed — read,
with the checklist below in hand, with the suite run first, and with the
findings written into a record that lives with the change. The record is the
artifact: a year from now it says why a thing is the way it is.

## Before you review

1. Pull the change. Run the whole suite locally:
   `PYTHONPATH=src .venv/bin/python tests/test_smoke.py`. Red means stop; a
   review of a red change is a review of a moving target.
2. Read the change's note: what, why, what could break. No note, no review —
   send it back with that one line.
3. Open the requirement it claims to meet. Read that first, not the diff.

## The checklist

Work through every item; write a line for each, even the ones that pass.

| # | Question | A defect looks like |
|---|---|---|
| 1 | Does it do what the requirement says, line by line? | A paraphrase of the requirement is met; the requirement is not |
| 2 | What happens when it is wrong? | A path that fails silently, or with a message nobody can act on |
| 3 | Does it touch money, stock or someone's data? | Then: no test, no audit line, or no way back |
| 4 | Is every sentence it adds to the suite a sentence that can be false? | A test that asserts nothing, or asserts its own fixture |
| 5 | Would the next person understand it? | A name that lies; a comment that says *what* instead of *why* |
| 6 | Is anything new that did not need to be? | A dependency, a setting, a table, a screen, a copy of a helper that exists |
| 7 | Does it leak? | Anything of the tenant's in a log, an error page, a URL, a third party's hands |
| 8 | Is it the same at 375 pixels? | A table that overflows, a button under a thumb, a modal that cannot close |
| 9 | Does it respect the guards? | A duplicate id across part files; a button not wired literally; an emoji; an undefined CSS variable; a capability count not lifted in every pinned place |
| 10 | Did the date audit run? | Anything with a date or a "today" that was only run on the day it was written |

## Findings

A finding is a **defect** or a **question**, with the file and line it refers
to. Write it so the author can act without asking:

- *Defect · main.py:1437 · the order insert ignores `country`; the checkout sends it (requirement 5.2).*
- *Question · traffic.py:212 · why five seconds for the rules cache and not one? A ban should bite at once.*

"Looks good" is not a finding. A review with no findings says so explicitly
and says what was checked.

## Rules

- **Nothing merges with an open defect.** A question can be answered in
  writing and closed by the reviewer.
- **The author does not close their own defects.** The reviewer does, after
  re-reading the fix.
- **A change that skipped review is a defect in the process**: it is
  reviewed after the fact, the record says so, and the client is told.
- A review takes as long as it takes. A change too big to review in an hour
  is two changes.

## The record

One file per change, from the template, kept under `reports/reviews/`
named `YYYY-MM-DD-<short-title>.md`. Fill in the header, the checklist
lines, the findings and their outcomes, and the two signatures — author
and reviewer. The test report for a release lists every record since the
last release.

Template: [`templates/review-record.md`](templates/review-record.md).

## What review is not

Not testing (the suite does that thousands of times more patiently), not
verification (a person with a checklist at each gate), not a second opinion
on design. It is the reading that catches what tests were not written for.
