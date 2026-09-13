# Requirements traceability — [RELEASE OR DATE]

*Internal. Never send this to a client. Every requirement, where it is met, what proves it, and that the proof ran. Copy the source block once per place requirements come from (a signed scope, a price list, a standard, an internal invariant), and add requirement rows freely.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Prepared by** | |
| **Date** | |

## 1. Sources

*Repeat from here one row per source of requirements.*
| Source | Holds | Where | Version / date |
|---|---|---|---|
| | | | |

## 2. Requirements

*Repeat from here one block per source; one row per requirement inside it.*
### 2.n · [SOURCE NAME]

| Req. | Statement (as written in the source) | Implemented in (module · screen) | Proof (test file · section or case) | Reviewed in (record) | Ran on this commit | Initials |
|---|---|---|---|---|---|---|
| | | | | | | |

*End of the repeated block.*

## 3. Requirements without a proof

*Every row above with an empty proof column, and what will be done.*

| Req. | Why no proof yet | Owner | Due |
|---|---|---|---|
| | | | |

## 4. Verification

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| Q1 | Every requirement in every source has a row | | | |
| Q2 | Every proof named exists | | | |
| Q3 | Every proof ran green on this commit | | | |
| Q4 | No implementation changed without its proof changing, or a record says why | | | |
| | (add rows) | | | |

## Sign-off

| Release | Commit | Verified by | Date | Rows without proof (→ defect) |
|---|---|---|---|---|
| | | | | |
