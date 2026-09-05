# business-control — dev conventions

## Ports

- **8860 is the preview server's.** Tenants are addressed by hostname on it
  (`zenjoy.localhost:8860`, `lingua.localhost:8860`), so `autoPort` stays
  false — a moved port breaks every tenant's front door. Never run an
  ad-hoc server on 8860; killing the preview's process to take the port is
  exactly the collision this file exists to prevent.
- **8861 is the scratch port for verification runs.** Anything Claude (or a
  script) starts by hand goes here:

  ```bash
  nohup .venv/bin/python scripts/launch.py --port 8861 > /tmp/bc-verify.log 2>&1 &
  ```

  Host-header routing ignores the port, so every tenant answers the same
  way: `curl -H "host: zenjoy.localhost" http://127.0.0.1:8861/`. Kill it
  when done (`lsof -ti:8861 | xargs kill`). Both servers share `data/` —
  SQLite WAL handles the two dev processes.

- The server binds `127.0.0.1`; curl that address, not `localhost` (IPv6).

## Tests

`PYTHONPATH=src .venv/bin/python tests/test_smoke.py` — script-style,
prints `all N checks passed`. Since 2026-09-01 that command is a runner
over three independent part files executed in parallel (~100s total),
each on its own throwaway database:

- `tests/test_core.py` — single-tenant install: commerce, ops, supply,
  integrations, storefront
- `tests/test_studio.py` — B2B paperwork: kit, engagements, vault,
  quotes, SOW
- `tests/test_platform.py` — tenancy and up: split, router, fleet,
  Learning on tenant alpha

Debug one part live with `tests/test_smoke.py --only core` (or run the
part file directly). Shared prologue lives in `tests/_harness.py` — a
part must build all of its own state; never lean on another part's.
Still run the full suite in background with output to a file.

## Dates

The suite is green on the day you run it, which is a weaker claim than it
looks: a fixture saying "+35 days" and meaning "next month", or "next
Monday" while a holiday sits on "tomorrow", is right most days and wrong
on the rest. Two such failures appeared within a week of each other from
the calendar alone.

```bash
PYTHONPATH=src python3 scripts/audit_dates.py
```

runs all three parts at seventeen awkward dates — every weekday, month
ends, a year end, a leap day, both clock changes — via `BC_FAKE_NOW`,
which `tests/_harness.py` reads to move `time.time()`, `date.today()` and
`datetime.now()` together. `--weekdays` does just the seven, which is the
cheap version and catches most of it; `--sample` does three — a weekend,
a year end and a clock change, being the three ways a date fixture has
actually been wrong here — and that is what CI runs on every push. The
full seventeen run nightly on a schedule, and `--jobs N` caps the lanes
for a runner with two cores and no interest in swapping.

Rules that fall out of it, for anything a test dates:

- days are calendar days, not multiples of 86400 (a fortnight in seconds
  crosses a clock change an hour out, and lands on the wrong day)
- hours are wall-clock hours, not seconds past midnight
- "next month" is a month, not thirty-five days
- a fixture anchored to `now` and one anchored to a week boundary drift
  into each other; anchor both to the same thing

The pre-push hook runs the suite on today AND on the three sample dates,
which on a four-core machine is about seven minutes against two. When
that is too much for the change in hand:

| `BC_HOOK_DATES=` | what it runs | roughly |
|---|---|---|
| `off` | today only | 2 min |
| `one` | today + one of the three, rotating by commit | 3 min |
| (unset) | today + all three | 7 min |
| `all` | today + all seventeen | go for a walk |

`one` rotates deterministically on the pushed commit, so the same commit
always checks the same date and a failure reproduces. Three pushes cover
what one `sample` run covers.

`scripts/install_hooks.sh` also sets `core.sshCommand` with an SSH
keepalive, and that is not optional decoration. git opens the connection
to the remote *before* running pre-push and then waits: a hook that takes
seven minutes leaves the session idle long enough for GitHub to hang up
with "Connection to github.com closed by remote host" — after the suite
has passed, so the failure reads as anything except what it is. That was
the push flake this repo lived with while the hook took two minutes; at
seven it is not a flake, it is every push.

## Backups

`scripts/backup.py` archives the whole fleet (pulls from worker nodes) and
writes `data/backups/last.json`; exit 1 = some tenant missed. Production
cron: `17 2 * * *` on the provider box only — see docs/product/DEPLOY.md.
