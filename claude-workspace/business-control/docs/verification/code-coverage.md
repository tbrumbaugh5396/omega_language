# Code coverage — [RELEASE OR DATE]

*Internal. Never send this to a client. Which lines the suite reached, per area, against each area's floor; and for the sensitive areas, a reason beside every line it did not reach. Copy the area block once per area; add file rows freely.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Measured by** | |
| **Date** | |
| **Command** | |
| **Report kept at** | |

## 1. Areas and floors

*Repeat from here one row per area.*
| Area | What is in it (modules or paths) | Floor | Reached | At floor? |
|---|---|---|---|---|
| | | | | |

## 2. Per area

*Repeat from here one block per area.*
### 2.n · [AREA]

*Files, most unreached first.*

| File | Reached % | Unreached lines | Changed this release? |
|---|---|---|---|
| | | | |

*End of the repeated block.*

## 3. Never-reached lines — sensitive areas — with reasons

*Allowed reasons: impossible (the schema forbids the state) · outside (a third-party failure that cannot be simulated, and the seam is tested) · scheduled (a test is owed, with the record that owes it). "Hard to test" is not a reason.*

*Repeat from here one row per file with unreached sensitive lines.*
| File | Lines | Reason | By |
|---|---|---|---|
| | | | |

## 4. Verification

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| V1 | Coverage was measured on this commit | | | |
| V2 | The suite was green under the measurement | | | |
| V3 | Every area is at or above its floor | | | |
| V4 | Every unreached sensitive line has a reason | | | |
| V5 | New code in this release is at the floor on its own | | | |
| V6 | No floor was lowered, or the client's document changed first | | | |
| | (add rows) | | | |

## Sign-off

| Release | Commit | Verified by | Date | Areas below floor (→ defect) |
|---|---|---|---|---|
| | | | | |
