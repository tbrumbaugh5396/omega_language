# Code coverage — how much of the code the tests reach

*To the client. A number we report, and what it does and does not mean.*

Coverage measures which lines of the code the test suite actually ran. A
line that no test ever reached is a line whose behaviour nobody has proved.
We measure it on every release and report it to you.

## The number

| Area | Floor we hold | Why that floor |
|---|---|---|
| Anything that moves money, stock or personal data | **95% or above** | A wrong line here is a phone call to a bank or a lawyer |
| The rest of the server | **85% or above** | Screens and reports fail visibly; the cost is a fix, not a loss |
| The browser code | **Behaviour tests, not line counts** | Line coverage of a screen says little; whether the button does the thing says everything |

A release whose number falls below the floor for its area does not ship
until it is back.

## How it is measured

- The whole suite runs under a coverage tool that records every line
  executed, per file.
- The report lists each file with its percentage and, more usefully, the
  **lines never reached**. That list is what we read.
- New code in a change is held to the floor on its own, not averaged into
  old code that already has it.

## What coverage does not tell you

Coverage is a floor, not a grade. A line can be run by a test that asserts
nothing; that counts as covered and proves nothing. So coverage is read
alongside two other things:

- **The sentences.** Every test is a sentence that can be false (see the
  [test process](test-process.md)). A file with high coverage and few
  sentences is suspicious.
- **The defects.** Every defect that reached a preview or the live system
  gets a test that would have caught it. If the line was "covered" and
  still wrong, the test was the problem, and it is rewritten.

## What you get

- The **coverage number per area** on every release note, with the floor
  beside it.
- The **never-reached list** for the money, stock and data areas, on
  request — it is short, and every line on it has a reason written down.
- If the floor is ever lowered for your build, a written reason and your
  agreement first.
