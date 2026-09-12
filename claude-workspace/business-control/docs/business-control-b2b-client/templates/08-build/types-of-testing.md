# Types of testing — what each kind is for

*To the client. The words we use, so a release note reads as intended.*

"Tested" covers seven different activities here. They catch different
things, and a build that has had only one of them has not been tested.

| Kind | Question it answers | Who | When |
|---|---|---|---|
| **Unit** | Does this one function do what its sentence says? | The suite | Every save |
| **Integration** | Do the pieces agree — an order, the stock behind it, the accounts it lands in? | The suite | Every change |
| **End to end** | Can a person do the whole thing — find, buy, pay, track — in a real browser? | The suite, in a browser | Every change that touches a screen |
| **Date and time** | Is it still right on a Sunday, a year end, a clock change, a leap day? | The suite, on fixed dates | Every push and every release |
| **Verification** | Is it the right thing, not only a working thing? | A person, with a checklist | Every round and every launch |
| **Load** | Does it hold up when everyone arrives at once? | A script that pretends to be a crowd | Before launch, and before any campaign you tell us about |
| **Security** | Can a stranger read, change or take what they should not? | Us, with the same tools an attacker uses | Before launch, and after any change to sign-in, payment or permissions |

## What each looks like for your build

**Unit and integration** are the bulk of the suite: thousands of sentences,
each proved by trying. *"A refund cannot exceed what was paid."* *"A
customer cannot read the board's attachments."*

**End to end** opens the real pages in a real browser, clicks, types, and
reads what appears — including on a phone-sized screen. It is how we know
the checkout works, not only that its code runs.

**Date and time** is the one most builds skip and the one that costs most
when skipped. Yours runs the whole suite as if today were the three worst
days of the year.

**Verification** is described in its [own document](verification-process.md).

**Load** simulates a burst — a thousand visitors in a minute, a hundred
orders — against a copy of your system, and reports the slowest page and
the point at which anything failed. You get the numbers.

**Security** covers the sign-in, the payment path, every permission, and
the storefront's public face: what a stranger can reach, what a customer
can reach, what a member of staff can reach, and whether any of those is
more than intended. Every request to your site is logged with who made it,
and the operations screen lets you block an address or a pattern the
moment you see it misbehave.

## What is not on the list, on purpose

We do not run "acceptance testing" as a separate stage, because that is
what your feedback rounds *are*. We do not test on your live data; every
test runs against a throwaway copy. And we do not call something tested
because it was clicked once by the person who built it.

See also: [test process](test-process.md), [code coverage](code-coverage.md),
[code review](code-review.md).
