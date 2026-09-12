# Code review — what we check before you see it

*To the client. Sent with the round 1 preview, so you know what "reviewed" means when we say it.*

Every change to your build is read by a second person before it reaches the
preview you look at. Not skimmed — read, with the questions below in hand.
The review is written down and kept with the change, so a year from now
anyone can see why a thing is the way it is.

## What a review checks

| Question | What we are looking for |
|---|---|
| **Does it do what the requirement says?** | The signed requirement, line by line — not the ticket's paraphrase of it |
| **What happens when it is wrong?** | Bad input, a missing record, a slow network, a double click. Every path that fails has a message a person can act on |
| **Does it touch money, stock or someone's data?** | Then it has a test, an audit line, and a way back |
| **Would the next person understand it?** | Names say what things are; a comment says *why*, never *what* |
| **Is anything new that did not need to be?** | A dependency, a setting, a table, a screen — each is a thing to maintain for years |
| **Does it leak?** | Nothing of yours in a log, an error page, a URL or a third party's hands that was not there before |
| **Is it the same on a phone?** | Every screen is looked at at 375 pixels wide before it is called done |

## How it runs

1. The change is opened for review with a one-paragraph note: what, why, and what could break.
2. The reviewer runs the whole test suite locally, then reads the change.
3. Findings are written as questions or as defects, each with the line it refers to. "Looks good" is not a finding.
4. Nothing merges with an open defect. A question can be answered in writing and closed.
5. The review note, the findings and their answers are kept with the change.

## What you get

- Every preview round comes with a **review summary**: how many changes,
  how many findings, how many were defects, and the three most consequential
  fixes in plain words.
- On request, the full review record for any change.
- A change that skipped review is a defect in our process, and we will tell
  you if it happened.

## What review is not

It is not a second opinion on design — that is the [art direction](../07-brand-exploration/art-direction.md)
and your feedback rounds. It is not testing — that is the [test process](test-process.md).
It is the reading that catches what tests were not written for.
