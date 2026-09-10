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
  **Since 2026-09-09 the preview (`business-control` in launch.json) binds
  `0.0.0.0`**, so a phone on the same wifi reaches it at
  `http://<mac ip>:8860` (`ipconfig getifaddr en0`). A bare IP opens the
  *default* tenant; to test another tenant from a phone, add the IP to
  that tenant's `hosts` in `data/tenants.json` (an exact alias wins).
  `business-control-https` is the same on 8443 with a self-signed cert
  that names the LAN IP (regenerated when the address changes) — needed
  for the camera scanner and Add-to-Home-Screen on a phone; accept the
  warning once. The launcher exports `BC_SCHEME`/`BC_PORT`, and every
  outward link (QR, invite, sign-in) is built from them.

## The books, the bank, the register and the rules

Four capabilities the price book sold with nothing behind them, built
2026-09-09: `accounting.py` (double entry), `treasury.py` (cash and
holdings), `legal.py` (matters and a diary), `automation.py` (rules on
the event bus). Screens: Books and Cash & holdings in a new **Money**
rail group, Legal register and Automations in Company. See
docs/product/finance-and-rules.md.

Things to know before touching them:

- **The ledger posts by derivation, not inline.** `accounting.sync()`
  walks orders and expenses with no journal yet, keyed on
  `(source, source_id)`. Never add an inline post at a call site: a
  payment that succeeds while its posting throws is the failure mode the
  whole design avoids.
- **Corrections reverse.** There is no journal edit and there must not be.
- **Discounts have their own account** (4500). Burying them in other
  income balances fine and is silently wrong.
- **Automation actions are a closed list.** Adding one that spends,
  publishes or mails a customer defeats the point; a rule that wants that
  wants a ticket.
- `finance.py` derives receivables and payables from existing rows and
  never stores them; only the budget is stored. `payroll.py` reads
  `timesheet.hours_for` rather than counting hours again, freezes figures
  on approval, and posts to the ledger only on payment. `onboarding.py`
  owns the templates and adds columns to hiring's `onboarding_tasks`, so
  it inits AFTER hiring.
- **A table has one owner.** The suite asserts no table name is declared
  by two modules: `CREATE TABLE IF NOT EXISTS` on a taken name does
  nothing silently. That guard caught payroll trying to take `pay_rates`
  from classroom.py, and found two live collisions — `api_keys`, which
  had been 500ing every `/api/v1` call, and `audit_log`.
- Invoicing lives in `finance.py`: a draft is editable, an issued invoice
  is not, and a correction is a credit note. It posts to the ledger at
  ISSUE, unlike an order, because a claim you only recognise when it is
  settled cannot tell you what you are owed. Credit notes stay out of the
  outstanding and overdue figures.
- Leaving lives in `onboarding.py`. `close_access()` is one transaction
  and it must stay that way: account off, PIN and badge forgotten, token
  rotated, API keys revoked, future shifts dropped. Never turn it into a
  checklist line.
- `civics.py` is the Civics & policy capability. Its map is an SVG drawn
  in `31-civics.js` from the install's own rows — no tiles, no CDN, no
  network. A test asserts the map function loads nothing.
- **Adding a capability touches six places**: the price book table, the
  parser's count in `pricebook.py`, `CAP_NAMES`, `TAB_CAP` and
  `CAP_LABEL`, the client capability menu, and the sales deck's price
  model. The suite checks every one of them.
- Every capability in the price book has something behind it.

## The agent door

`src/mcp_server/` is a Model Context Protocol server: JSON-RPC over stdio,
in front of one install, offering a hand-picked slice of the API rather
than all of it.

```bash
PYTHONPATH=src BC_MCP_KEY=bck_… python3 -m mcp_server
```

Reads are always offered; writes need `BC_MCP_WRITES=1` and are limited to
additive, reversible acts. Anything that spends money, publishes, or
cannot be undone is left out on purpose and listed in `EXCLUDED` in
`tools.py`. Authorisation is NOT done there — the key is bound to an
account and every call goes through the app's own permission check, so
binding the key narrowly is the real control. See docs/product/agent.md.

**stdout is protocol.** A `print` in that package is a parse error at the
client; log to stderr.

The suite checks every tool against the app's generated OpenAPI document:
the path exists, the method is answered, path placeholders are declared
and required, and body and query fields are ones the route accepts. That
guard exists because the first version sent `topic` to a route that wanted
`title`, which FastAPI drops silently.

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

## Where the rows live

Since 2026-09-09 a tenant's rows can live in Postgres instead of the
SQLite file: `db.connect()` reads the store from `BC_STORE`/`BC_PG_DSN`
or config.json's `store` key, and `erp/backend/pgstore.py` answers the
sqlite3 calls the app makes (see docs/product/multi-tenant.md, "Spanning
nodes"). Files can live in an S3-compatible store the same way
(`erp/backend/blobs.py`, config `blobs` / `BC_BLOBS`).

```bash
PYTHONPATH=src .venv/bin/python tests/test_smoke.py --store postgres
```

runs the whole suite against an embedded Postgres (`pgserver`, in
requirements-dev.txt; one server per part, ~10s to start). It is not
the default gate — SQLite is — but any SQL that only SQLite accepts
(a bare `GROUP BY`, `rowid`, a boolean as `AND 1`, `SUM(x > 0)`) shows
up there and nowhere else. When a new query fails only under Postgres,
fix the query if it is loose SQL and the adapter if it is an idiom.

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

The pre-push hook runs the suite on today AND on **one** other day,
rotating by the commit being pushed.

| `BC_HOOK_DATES=` | what it runs | roughly |
|---|---|---|
| `off` | today only | 2 min |
| (unset) | today + one of three, rotating by commit | 3 min |
| `sample` | today + all three | 7 min |
| `all` | today + all seventeen | go for a walk |

One and not three, which was the first thing tried. The reason is about
people rather than arithmetic: a hook is worth what it actually runs, and
a seven-minute wait on every push is how `--no-verify` becomes muscle
memory. At that point the gate is open on exactly the pushes somebody was
in a hurry to make, which are not a random sample of pushes.

One is enough here because **the hook is not the thorough check and was
never meant to be**. CI runs all three sample dates on every push and all
seventeen nightly. The hook's job is to catch the obvious before it
leaves the machine, cheaply enough that nobody minds paying. Rotating by
commit, three pushes cover what one `sample` run covers, and people push
more than three times.

The rotation is deterministic on the pushed commit, not random: the same
commit always checks the same date, so a failure reproduces. A hook that
checked a different day each time would produce failures nobody could
reproduce, and an unreproducible failure gets waved through as a flake —
which is how both bugs this exists to catch reached main.

`scripts/install_hooks.sh` also sets `core.sshCommand` with an SSH
keepalive, and that is not optional decoration. git opens the connection
to the remote *before* running pre-push and then waits: a hook that takes
seven minutes leaves the session idle long enough for GitHub to hang up
with "Connection to github.com closed by remote host" — after the suite
has passed, so the failure reads as anything except what it is. That was
the push flake this repo lived with while the hook took two minutes; at
seven it is not a flake, it is every push.

## Seeding

`command_utilities/Seed Starter Content.command` is the double-click
version; by hand it is two scripts:

```bash
.venv/bin/python scripts/seed.py                 # catalog, stores, 30 days of orders
.venv/bin/python scripts/seed_live_class.py      # a class that is in session NOW
```

Both take a tenant (`--tenant lingua` / `lingua`); without one the class
seed picks whichever tenant `localhost` opens, because seeding a tenant
nobody looks at is the same as not seeding. Both are safe to re-run.

`seed_live_class.py` exists because half the Learning feature only has a
surface while a class is running — the register, the check-in door, the
badge scanner, the wall display's IN PROGRESS. Seeded a course and no
session, all of those open empty, which reads as broken rather than as
idle. It leaves three students deliberately unmarked: a register where
everyone is already ticked demonstrates nothing, because ticking
somebody is the thing you do on that screen.

It drives `classroom.start_class` and `classroom.do_check_in` rather
than inserting rows. A seed that writes its own rows is a second
implementation of the feature and goes stale the first time the real one
moves.

## Backups

`scripts/backup.py` archives the whole fleet (pulls from worker nodes) and
writes `data/backups/last.json`; exit 1 = some tenant missed. Production
cron: `17 2 * * *` on the provider box only — see docs/product/DEPLOY.md.
