# Testing — [RELEASE OR DATE]

*Internal. Never send this to a client. The suite itself: what it is, that it ran on this commit, on the awkward dates, and that every guard is still standing. Every list below grows by its count.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Run by** | |
| **Date** | |
| **Command(s)** | |
| **Transcript kept at** | |

## 1. The parts

*Repeat from here once per test file or group — how many: [HOW MANY]*

### 1.[N] · [PART NAME] — `[PATH]`

| | |
|---|---|
| **Scope** (what it covers) | [SCOPE] |
| **Isolation** (its own data? shares state with another part?) | [ISOLATION] |
| **Checks this run** | [CHECKS THIS RUN] |
| **Checks last release** | [CHECKS LAST RELEASE] |
| **Change explained in** (review record, if the count fell) | [CHANGE EXPLAINED IN] |

*End of the repeated block.*

## 2. The guards

*Checks that read the tree rather than the running app: naming, duplicates, forbidden content, structure.*

*Repeat from here once per guard — how many: [HOW MANY]*

| # | Guard | Where (file · section) | Fails when | Present this run |
|---|---|---|---|---|
| [N] | | | | |

*End of the repeated block.*

## 3. The dates

*Repeat from here once per clock the suite is run on — how many: [HOW MANY]*

| # | Clock | Why this day | Result |
|---|---|---|---|
| [N] | | | |

*End of the repeated block.*

## 4. Verification

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| T1 | The suite ran on this exact commit | | | |
| T2 | Every part passed and the total is the sum of the parts | | | |
| T3 | The count did not fall, or the fall is explained | | | |
| T4 | Every date run is green | | | |
| T5 | Every guard in section 2 is present | | | |
| T6 | Each new behaviour in this release has a new check | | | |
| T7 | No check was weakened or deleted without a record | | | |

*Repeat from here once per further claim — how many: [HOW MANY]*

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| T7+[N] | | | | |

*End of the repeated block.*

## Sign-off

| Release | Commit | Total checks | Dates | Verified by | Date |
|---|---|---|---|---|---|
| | | | | | |
