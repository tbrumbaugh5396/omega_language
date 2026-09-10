# The seven that were sold and not built

Accounting, Treasury, Legal, Automation, Finance, Payroll and Onboarding
were rows in the price book with nothing behind them. A quote could be
built that a customer could not be delivered. These are them.

| Capability | Screen (rail group) | Module |
|---|---|---|
| Accounting | Books (Money) | `accounting.py` |
| Treasury & investments | Cash & holdings (Money) | `treasury.py` |
| Legal | Legal register (Company) | `legal.py` |
| Automation | Automations (Company) | `automation.py` |
| Finance | Owed & planned (Money) | `finance.py` |
| Payroll | Payroll (Money) | `payroll.py` |
| Onboarding | Onboarding (Team) | `onboarding.py` |

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

## Finance — owed each way, planned against actual, and the weeks ahead

Accounting records what happened and Treasury says where the money is
now. Neither answers who owes us, whether we are where we said we would
be, or what the next quarter looks like.

**Receivables and payables are derived, never stored.** An unpaid order
is a receivable; an approved expense somebody paid personally is a
payable; a purchase order not yet received is money committed. All three
were already rows and none had a list. Deriving them means nothing can be
paid here and still owed there.

**A budget is the one stored number**, because a plan is the only figure
in the file that is not a consequence of something else. Actuals come
from the ledger, so budget and books cannot drift into two definitions of
a cost. The variance sign follows the account type: under plan is on
track for a cost and off track for income, and one subtraction cannot
mean both.

**The forecast is arithmetic and says so.** An unpaid order is assumed to
land thirty days after it was placed and a staff reimbursement two weeks
after the expense. Neither is a promise anybody made.

## Payroll — hours to a payslip somebody can dispute

**There are no tax tables here and none are implied.** No thresholds, no
bands, no year-to-date, nothing filed with anybody. Deductions are rows
the operator writes: a name, a percentage or a fixed amount, whether it
comes off the employee or sits on top as an employer cost, and an order.
A percentage can be of the gross or of what is left after the ones before
it, which is what makes the order a field rather than an accident of id.
That is the honest shape for software sold in one price book to
businesses in many places.

**Hours come from one place.** `timesheet.hours_for` is the same function
the Hours screen uses, so a payslip and the timesheet behind it cannot
disagree. A second implementation of "how many hours" is how a business
ends up arguing with itself.

**Build, approve, pay, and only then post.** A draft rebuilds as often as
the hours change. Approval freezes the figures and nothing is recomputed
afterwards, because a payslip from March must still say in June what it
said in March. Marking it paid is what reaches the ledger: until then a
wage is a liability rather than a payment. The journal splits the cost,
what was held back and owed onward, and the net that actually left the
bank.

**Everybody sees their own payslip in full**, working included. A number
somebody cannot see the working of is a number they cannot dispute, which
is not the same as one they agree with.

A rate is history rather than a setting, so a rise in April does not
restate what March cost. Anybody without a rate is skipped and named,
never guessed at.

## Onboarding — the first fortnight, as a list somebody owns

Hiring already wrote a six-line list. The same six went to a driver and a
teacher, nothing carried a date so nothing could be late, and the only
way to see how somebody was getting on was to open their record and count
ticks.

Templates per role, steps that each carry a day, and a journey that is
one person walking one template from **their** start date rather than the
day somebody got round to setting it up. A step may need a document,
which is the difference between "we asked for their right-to-work" and
"we have it": it cannot be ticked until one is attached.

Hiring keeps calling this. A role with a template gets it; anything else
gets the built-in list, so an install that never opens the screen behaves
exactly as it did before.

## Two collisions this work uncovered

Neither was in scope; both were found by building on top of the schema.

**The public API was entirely broken.** `erp/backend/apikeys.py` and the
storefront's `api.py` both declared a table called `api_keys` with
different columns. `CREATE TABLE IF NOT EXISTS` on a name somebody has
taken does nothing at all and says nothing about it, so whichever ran
first won — the ERP, on every install. Every call to `/api/v1` answered
500 on a missing `active` column. The storefront's keys now live in
`store_api_keys`. No key was lost, because none could ever have been
stored.

**`audit_log` was declared twice**, once with a `status` column and once
without. The ERP won on every install so this was harmless, and would
have stopped being harmless the first time the init order changed. It has
one owner now.

The suite asserts no table name is declared by two modules. That guard is
what caught payroll's own attempt to take `pay_rates`, which
`classroom.py` has owned all along for teaching pay.

## What these still stop short of

- **Accounting**: no tax computation, no bank feed.
- **Treasury**: no live prices, so a holding is worth what somebody last
  marked it at.
- **Payroll**: no tax tables, no filings, and contractors paid per route
  are deliberately out — that is an invoice, and treating it as a payslip
  is how somebody gets misclassified by accident.
- **Finance**: no invoicing. A receivable here is an unpaid order, not a
  document you can send.

Every capability in the price book now has something behind it.
