# Test strategy — [RELEASE OR DATE]

*Internal. Never send this to a client. Every kind of test this product gets, who does it, what breaks the build, and where the evidence is kept. One row per type; a type that does not apply says so and why. The run records for each type are the other masters in this folder.*

| | |
|---|---|
| **Release** | |
| **Commit** | |
| **Prepared by** | |
| **Date** | |
| **Release cadence** (e.g. every 6 weeks) | [CADENCE] |
| **Branch / build under test** | [BUILD] |

## 1. Functional — what the software does

| Type | Purpose | Applies? | How (tool · framework · files) | Who writes | Who reviews | Gate (what breaks if it fails) | Evidence kept at |
|---|---|---|---|---|---|---|---|
| Unit | one component in isolation; every line outside the UI and the data layer | | | | | | |
| Integration | modules together, through their real seams; BDD scenarios | | | | | | |
| System | the whole application, end to end, on a built artifact | | | | | | |
| User acceptance (UAT) | the customer confirms it does their job | | | | | | |

## 2. Non-functional — how it behaves

| Type | Purpose | Applies? | How (tool · load · scenario) | Who runs | Threshold that fails it | Evidence kept at |
|---|---|---|---|---|---|---|
| Performance | speed and stability under load | | | | | |
| Security | vulnerabilities, secrets, access | | | | | |
| Usability | can a person do the task without help | | | | | |
| Compatibility | browsers, devices, screen widths, operating systems | | | | | |

## 3. Cross-cutting

| Type | Purpose | Applies? | How | When | Gate | Evidence kept at |
|---|---|---|---|---|---|---|
| Smoke | does it start and do the main thing | | | | | |
| Sanity | did the fix land, quickly, before the deeper run | | | | | |
| Regression, automated | existing features still work after a change | | | | | |
| Regression, full manual | the whole application, by hand, before a release | | | | | |

## 4. Process gates — the order a change goes through

*Repeat from here once per gate in the order a change passes through it — how many: [HOW MANY]*

| # | Gate | Who | Entry (what must be true before) | Exit (what must be true after) | Record kept where |
|---|---|---|---|---|---|
| [N] | | | | | |

*End of the repeated block.*

*Typical order: static analysis · unit coverage · BDD integration written · QA reviews scenarios · design review · manual QA · internal demo · external demo · automated regression written · full manual regression · release.*

## 5. Coverage rules

*Repeat from here once per coverage rule (an area, its floor, and what breaks) — how many: [HOW MANY]*

| # | Area | Floor | Measured by | Breaks the build? | Exceptions (and who may grant one) |
|---|---|---|---|---|---|
| [N] | | | | | |

*End of the repeated block.*

## 6. Static analysis rules

*The handful of rules the team has defined, each one enforced by the build.*

*Repeat from here once per rule — how many: [HOW MANY]*

| # | Rule | Why | Enforced by (tool · check) | Fails the build? |
|---|---|---|---|---|
| [N] | | | | |

*End of the repeated block.*

## 7. Further types

*Repeat from here once per test type not listed above — how many: [HOW MANY]*

| # | Type | Purpose | How | Who | Gate | Evidence kept at |
|---|---|---|---|---|---|---|
| [N] | | | | | | |

*End of the repeated block.*

## 8. Verification

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| S1 | Every type marked as applying has a run record for this release | | | |
| S2 | Every gate in section 4 has its record for this release | | | |
| S3 | Every coverage floor was met, or an exception is written | | | |
| S4 | Every static analysis rule ran on this commit | | | |
| S5 | The release went out on the cadence, or the slip is explained | | | |

*Repeat from here once per further claim — how many: [HOW MANY]*

| # | Claim | How to check | Result | Initials |
|---|---|---|---|---|
| S5+[N] | | | | |

*End of the repeated block.*

## Sign-off

| Release | Commit | Verified by | Date | Types without a record (→ defect) |
|---|---|---|---|---|
| | | | | |
