# The test process — how we know it works

*To the client. Sent with the kickoff pack, referred to at every round.*

Your build ships with a test suite that runs on every change, on every push,
and on three fixed dates a year we pick to be awkward. A change that fails
any of it does not ship. This document says what that means in practice.

## The rule

**No change is done until the suite is green.** Not "green apart from the
one that always fails" — green. A test that always fails is deleted or fixed
that day, because a suite people learn to ignore protects nothing.

## What runs, and when

| When | What | How long |
|---|---|---|
| Every save, on the developer's machine | The part of the suite for what changed | seconds to a minute |
| Every change opened for review | The whole suite | a few minutes |
| Every push to the shared branch | The whole suite, on today's date **and one other date** | a few minutes |
| Every release | The whole suite on three awkward dates: a Sunday, a year end, a clock change | ten minutes |
| Every night on the live system | The smoke checks: the pages open, an order can be placed, a login works | a minute |

## The shape of the suite

The suite is three parts that run at once, each against a fresh, throwaway
copy of the database, so a test can never see another test's leftovers and
can never touch your real data:

- **core** — the shop, the operations screens, the workforce, supply, the
  integrations, the storefront face
- **studio** — the paperwork: quotes, agreements, the vault, the portal
- **platform** — the tenancy, the router, the fleet, entitlements

Each part prints what it checked, one line per check, in plain words:
*"a paid order lands in the queue"*, *"a refund cannot exceed what was paid"*.
The last line is the count. At the time of writing the count is over four
thousand.

## What a test is here

A test is a sentence that can be false. *"A customer cannot read the board's
attachments"* is a test; the suite proves it by trying. Every feature ships
with its sentences, and every defect fixed ships with the sentence that
would have caught it — so the same defect cannot come back unnoticed.

## Dates are tested on purpose

Most software is tested on the day it was written. Yours is also run as if
today were a Sunday, New Year's Eve, and the night the clocks change,
because that is where date arithmetic goes wrong, and it goes wrong in
payroll, in reports and in bookings — the places it costs most.

## What you get

- The **count and the date** of the last green run, on every preview and
  every release note.
- The **transcript** of any run, on request: every sentence, checked.
- A **red run stops the release**, and we say so rather than shipping
  around it.

See also: [verification process](verification-process.md) for what we check
by hand, [code coverage](code-coverage.md) for how much of the code the suite
reaches, and [types of testing](types-of-testing.md) for what each kind is
for.
