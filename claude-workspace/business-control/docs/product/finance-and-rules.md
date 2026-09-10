# The four that were sold and not built

Accounting, Treasury, Legal and Automation were rows in the price book
with nothing behind them. A quote could be built that a customer could
not be delivered. These are them.

| Capability | Screen (rail group) | Module |
|---|---|---|
| Accounting | Books (Money) | `accounting.py` |
| Treasury & investments | Cash & holdings (Money) | `treasury.py` |
| Legal | Legal register (Company) | `legal.py` |
| Automation | Automations (Company) | `automation.py` |

## Accounting — a ledger, not a report

The install always knew what it earned and spent, and `/api/analytics/pnl`
added it up. That answers *how are we doing*. It does not answer *what do
we file*, and the difference is not presentation: a report derived from
operational tables has no opening balance, cannot be closed, cannot be
corrected without changing history, and has nowhere to put a loan, an
owner's contribution or money owed to a member of staff who bought the
paper themselves.

So: accounts with a type, journals with balanced lines, a trial balance
that must come to zero, an income statement and a balance sheet that
agree with each other by construction.

**Posting is derived, once, and idempotent.** Rather than editing every
place that takes money to also write a journal, `sync()` walks the events
with no entry yet and posts them, keyed on `(source, source_id)`. The
obvious alternative — posting inline at each call site — fails the way
books must never fail: the payment succeeds, the posting throws, and the
ledger is quietly short one entry nobody finds until a year end. Here a
failure leaves the event unposted and **visible**, and running again is
safe.

**A discount is not a smaller sale.** It is the full sale and an amount
given away, and the two answer different questions. Discounts post as a
debit to their own income account, so revenue reduces where it should
while "what is the discounting costing us" stays answerable. The first
version buried them in other income, which the ledger accepted and no
reader would have caught.

**Corrections reverse; they never edit.** An edited journal is a history
that changed after somebody relied on it. Closing a period refuses any
later posting dated inside it, and refuses to close at all if the trial
balance is out.

It is a set of books, not an accountant. It does not know your
jurisdiction's rules and files nothing with anybody.

## Treasury — where the money is, and how long it lasts

The ledger says the business holds cash. It does not say the cash is
spread over three accounts, that one is a deposit a week away, or that at
the current burn it runs out in March.

Accounts with stated balances, what is set aside and must not be spent,
transfers, holdings with cost and current value, and the runway that
falls out of it.

**Balances are stated, not derived, on purpose.** A bank account has a
balance whether or not the books are up to date, and a treasury screen
that goes blank because nobody posted last week is one nobody opens.
Where an account names a ledger account the difference between the two is
shown, which is where a reconciliation starts. A difference is reported,
never corrected: the books may simply be behind.

**A transfer is not income.** It has its own verb because recorded as
income or cost it inflates a year that never earned it, and it writes a
movement on both sides.

**Runway is arithmetic on the past** — free cash over average net burn —
and is labelled a projection everywhere it appears. It does not know what
you are about to invoice.

## Legal — the diary above the filing cabinet

The vault already holds contracts, policies and signatures. What it never
held is the *obligation*: that the lease has a ninety-day break clause,
that the insurance renews in March whether or not anyone opens the
folder, that the policy was due for review a year ago. A filing cabinet
is not a diary, and the businesses caught by a notice period are the ones
that filed the contract correctly.

Matters with the dates that matter, obligations under them, and one diary
holding endings, decisions and duties together — because a lease break
and a licence renewal are the same kind of problem.

**A notice period counts backwards from the end date, and that is the
whole of the cleverness.** Somebody types the number; nothing reads the
contract. **Repeats appear on completion**, not in advance: a diary
pre-filled with a year of rows has an overdue count that means nothing.
Months are calendar months, so a quarterly filing due on the 31st is due
on the 30th of a short month.

Nothing here is advice, and it does not know your jurisdiction.

## Automation — when this happens, do that

The install already announces everything that matters and already has
places to send it. What it lacked was a way for the business to say what
should *happen*, without somebody writing code.

Rules ride the same event bus as Discord and the integrations, and
inherit its one hard promise: a listener must never break the thing it
heard. An automation that throws does not fail the order.

**The action list is short and stays short.** A rule may raise attention,
open work, or tell an outside system. It may not spend money, publish,
email a customer, or change a record's state. An engine that can do
anything is a way to arrange, by accident and at three in the morning, an
outcome nobody would have approved on purpose. A rule that looks like it
wants one of those wants a ticket for a person.

Two things stop a rule becoming a problem. **A cooldown**, so a busy
Saturday cannot turn one misconfigured webhook into a thousand. **A log**
of every run, because an automation you cannot see is indistinguishable
from a bug in the thing it acted on. A test route fires a rule against a
payload you write, ignoring the cooldown, because a rule nobody has seen
work is a rule somebody hoped about.

## Still sold and still not built

Three remain, and they are named here rather than left to be discovered.

- **Finance** ($30, requires Payments + Accounting). Now that a ledger
  exists the dependency is satisfiable, but nothing yet answers to the
  name.
- **Payroll** ($30). What exists is a pay overlay for teaching sessions.
  No pay runs, no withholding, no filings.
- **Onboarding** ($20). Hiring writes a first-week list, which is most of
  what the row promises, but there is no screen sold as onboarding.

Two of the four built here also stop short in ways worth stating.
Accounting does no tax computation and no bank feed. Treasury holds no
live prices, so a holding is worth what somebody last marked it at.
