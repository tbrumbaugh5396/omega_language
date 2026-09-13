# Code review — [CHANGE OR RELEASE]

*Internal. Never send this to a client. One record per reviewed change; copy the finding block once per finding and the file block once per file read. A change merges when no defect is open and both people have signed.*

| | |
|---|---|
| **Change** | (commit, branch or pull request) |
| **Requirement it meets** | (the line in the requirements sheet, or "housekeeping") |
| **Author** | |
| **Reviewer** | |
| **Date** | |
| **Suite before review** | (green? checks · dates) |

## 1. The author's note

*What, why, what could break. Written by the author before the review starts. No note, no review.*

## 2. What was read

*Repeat from here one row per file read; a file in the diff not listed here was not reviewed.*
| File | Lines | Read fully? | Notes |
|---|---|---|---|
| | | | |

## 3. Checklist

*One line per item, even the ones that pass. "n/a" is a line; blank is not.*

*Repeat from here add items the team agrees on; never remove one without the team.*
| # | Question | Line |
|---|---|---|
| 1 | Does it do what the requirement says, line by line? | |
| 2 | What happens when it is wrong — does it fail with a sentence? | |
| 3 | If it touches money, stock or a person: test, audit line, way back? | |
| 4 | Can every new test be false? | |
| 5 | Would the next person understand it? | |
| 6 | Is anything new that did not need to be — dependency, setting, table, screen, copy? | |
| 7 | Does anything leak — logs, errors, URLs, third parties? | |
| 8 | Is it the same on a narrow screen? | |
| 9 | Does it respect the tree's rules (see the code organisation sheet)? | |
| 10 | Did the date audit run? | |
| | (add rows) | |

## 4. Findings

*Repeat from here one block per finding.*
### F[N] · [DEFECT OR QUESTION] · `[FILE]:[LINE]`

**Finding.** (What is wrong or unclear, in a sentence the author can act on.)

**Requirement or rule.** (Which line it breaks, if any.)

**Outcome.** fixed in `[COMMIT]` · answered: (the answer) · withdrawn: (why)

**Closed by.** (the reviewer, after re-reading the fix)

*End of the repeated block.*

## 5. Outcome

- [ ] No open defects
- [ ] Every question answered in writing
- [ ] Suite green after the fixes — checks: · dates:
- [ ] The requirements sheet row for this change points at its proof
- [ ] The code organisation sheet is updated if a module, table or screen was added or moved

## Sign-off

| Change | Author | Reviewer | Date | Merged as |
|---|---|---|---|---|
| | | | | |
