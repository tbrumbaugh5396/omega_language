# Reports

The evidence delivered beside the code. Three kinds, all produced by the
procedures in `docs/business-control-b2b-client/procedures/`:

- `test-report-YYYY-MM-DD.md` — the suite's counts, the date audit, the
  commit, the coverage summary, the reviews since the last report.
  Made by `scripts/test_report.py`.
- `coverage/YYYY-MM-DD.md` and `.json` — per area against its floor, per
  file, the never-reached lines. Made by `scripts/coverage.py`.
- `reviews/YYYY-MM-DD-<title>.md` — one record per change, written by the
  reviewer from `procedures/templates/review-record.md`.

Never edited after the fact; a correction is a new report that says what
it corrects.
