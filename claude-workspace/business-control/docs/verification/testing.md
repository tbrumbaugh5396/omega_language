# Testing — <release or date>

*The suite itself: what it is, that it ran on this commit, on the awkward dates, and that every guard is still standing. Copy the part block once per test file or test group; the guard block once per guard.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Run by** | |
| **Date** | |
| **Command(s)** | |
| **Transcript kept at** | |

## 1. The parts

<!-- repeat: one block per test file or group -->
### 1.n · <Part name> — `<path>`

| | |
|---|---|
| **Scope** | (what it covers) |
| **Isolation** | (its own data? shares state with another part?) |
| **Checks this run** | |
| **Checks last release** | |
| **Change explained in** | (review record, if the count fell) |

<!-- end repeat -->

## 2. The guards

*Checks that read the tree rather than the running app: naming, duplicates, forbidden content, structure.*

<!-- repeat: one row per guard -->
| Guard | Where (file · section) | Fails when | Present this run |
|---|---|---|---|
| | | | |

## 3. The dates

<!-- repeat: one row per clock the suite is run on -->
| Clock | Why this day | Result |
|---|---|---|
| | | |

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
| | (add rows) | | | |

## Sign-off

| Release | Commit | Total checks | Dates | Verified by | Date |
|---|---|---|---|---|---|
| | | | | | |
