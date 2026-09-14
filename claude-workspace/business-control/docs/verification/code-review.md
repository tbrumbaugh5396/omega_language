# Code review — [CHANGE OR RELEASE]

*Internal. Never send this to a client. One record per reviewed change. Every list below grows by its count: files read, checklist items, findings. A change merges when no defect is open and both people have signed.*

| | |
|---|---|
| **Change** (commit, branch or pull request) | [CHANGE] |
| **Requirement it meets** (the line in the requirements sheet, or "housekeeping") | [REQUIREMENT IT MEETS] |
| **Author** | |
| **Reviewer** | |
| **Date** | |
| **Suite before review** (green? checks · dates) | [SUITE BEFORE REVIEW] |

## 1. The author's note

*What, why, what could break. Written by the author before the review starts. No note, no review.*

______

## 2. What was read

*A file in the diff not listed here was not reviewed.*

*Repeat from here once per file read — how many: [HOW MANY]*

| # | File | Lines | Read fully? | Notes |
|---|---|---|---|---|
| [N] | | | | |

*End of the repeated block.*

## 3. Checklist

*One line per item, even the ones that pass. "n/a" is a line; blank is not.*

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

*Repeat from here once per item the team has added (never remove one without the team) — how many: [HOW MANY]*

| # | Question | Line |
|---|---|---|
| 10+[N] | | |

*End of the repeated block.*

## 4. Findings

*Repeat from here once per finding — how many: [HOW MANY]*

### F[N] · [DEFECT OR QUESTION] · `[FILE]:[LINE]`

**Finding.** [WHAT IS WRONG OR UNCLEAR]

**Requirement or rule.** [WHICH LINE IT BREAKS]

**Outcome.** fixed in [COMMIT] · answered: [ANSWER] · withdrawn: [WHY]

**Closed by.** [REVIEWER, AFTER RE-READING THE FIX]

*End of the repeated block.*

## 5. Outcome

- [ ] No open defects
- [ ] Every question answered in writing
- [ ] Suite green after the fixes — checks: [CHECKS] · dates: [DATES]
- [ ] The requirements sheet row for this change points at its proof
- [ ] The code organisation sheet is updated if a module, table or screen was added or moved

## Sign-off

| Change | Author | Reviewer | Date | Merged as |
|---|---|---|---|---|
| | | | | |
